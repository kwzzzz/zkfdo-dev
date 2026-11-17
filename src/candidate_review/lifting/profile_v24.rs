//! Request-local wall-clock attribution. Each completed span contributes its
//! inclusive duration and its duration excluding completed direct children.
//! Only exclusive durations may be added across labels.

use std::{cell::RefCell, collections::BTreeMap, marker::PhantomData, rc::Rc, time::Instant};

use anyhow::{ensure, Context, Result};
use serde::Serialize;
use serde_json::Value;

#[derive(Default, Serialize)]
struct Totals {
    calls: u64,
    inclusive_seconds: f64,
    exclusive_seconds: f64,
}

struct Frame {
    id: u64,
    label: String,
    started: Instant,
    children_seconds: f64,
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct Interval {
    start: f64,
    end: f64,
}

impl Interval {
    fn seconds(self) -> f64 {
        self.end - self.start
    }

    fn intersect(self, other: Self) -> Option<Self> {
        let intersection = Self {
            start: self.start.max(other.start),
            end: self.end.min(other.end),
        };
        (intersection.end > intersection.start).then_some(intersection)
    }
}

struct Segment {
    interval: Interval,
    label: String,
    path: String,
}

#[derive(Serialize)]
struct Coverage {
    legacy_window_seconds: f64,
    coverage_interval_sum_seconds: f64,
    ledger_union_seconds: f64,
    uncovered_total_seconds: f64,
    covered_by_label: BTreeMap<String, f64>,
    uncovered_by_label: BTreeMap<String, f64>,
    uncovered_by_path: BTreeMap<String, f64>,
    uncovered_attribution_residual_seconds: f64,
}

fn merge_intervals(intervals: &[Interval], window: Interval) -> Vec<Interval> {
    let mut clipped = intervals
        .iter()
        .filter_map(|interval| interval.intersect(window))
        .collect::<Vec<_>>();
    clipped.sort_by(|left, right| left.start.total_cmp(&right.start));
    let mut merged: Vec<Interval> = Vec::new();
    for interval in clipped {
        if let Some(previous) = merged.last_mut() {
            if interval.start <= previous.end {
                previous.end = previous.end.max(interval.end);
                continue;
            }
        }
        merged.push(interval);
    }
    merged
}

fn attribute_coverage(segments: &[Segment], intervals: &[Interval], window: Interval) -> Coverage {
    let merged = merge_intervals(intervals, window);
    let coverage_interval_sum_seconds = intervals
        .iter()
        .filter_map(|interval| interval.intersect(window))
        .map(Interval::seconds)
        .sum();
    let ledger_union_seconds: f64 = merged.iter().copied().map(Interval::seconds).sum();
    let uncovered_total_seconds = window.seconds() - ledger_union_seconds;
    let mut covered_by_label = BTreeMap::new();
    let mut uncovered_by_label = BTreeMap::new();
    let mut uncovered_by_path = BTreeMap::new();
    for segment in segments {
        let Some(part) = segment.interval.intersect(window) else {
            continue;
        };
        let covered: f64 = merged
            .iter()
            .filter_map(|interval| interval.intersect(part))
            .map(Interval::seconds)
            .sum();
        let uncovered = part.seconds() - covered;
        *covered_by_label.entry(segment.label.clone()).or_insert(0.0) += covered;
        *uncovered_by_label
            .entry(segment.label.clone())
            .or_insert(0.0) += uncovered;
        *uncovered_by_path.entry(segment.path.clone()).or_insert(0.0) += uncovered;
    }
    Coverage {
        legacy_window_seconds: window.seconds(),
        coverage_interval_sum_seconds,
        ledger_union_seconds,
        uncovered_total_seconds,
        uncovered_attribution_residual_seconds: uncovered_total_seconds
            - uncovered_by_label.values().sum::<f64>(),
        covered_by_label,
        uncovered_by_label,
        uncovered_by_path,
    }
}

struct State {
    token: Rc<()>,
    stack: Vec<Frame>,
    next_id: u64,
    totals: BTreeMap<String, Totals>,
    anchor: Instant,
    last_transition: Instant,
    segments: Vec<Segment>,
    ledger_coverage: Vec<Interval>,
    legacy_window: Option<Interval>,
    invalid: bool,
}

thread_local! {
    static STATE: RefCell<Option<State>> = const { RefCell::new(None) };
}

pub(crate) struct Guard {
    token: Rc<()>,
}

/// Spans and their request guard must stay on the owning thread. The token also
/// prevents a late span drop from affecting a later request on the same thread.
pub(crate) struct Span {
    identity: Option<(Rc<()>, u64)>,
    _not_send: PhantomData<Rc<()>>,
}

pub(crate) fn activate() -> Result<Guard> {
    STATE.with(|slot| {
        let mut slot = slot.borrow_mut();
        ensure!(
            slot.is_none(),
            "a J wall profile is already active on this thread"
        );
        let token = Rc::new(());
        let anchor = Instant::now();
        *slot = Some(State {
            token: Rc::clone(&token),
            stack: vec![Frame {
                id: 0,
                label: "request".to_owned(),
                started: anchor,
                children_seconds: 0.0,
            }],
            next_id: 1,
            totals: BTreeMap::new(),
            anchor,
            last_transition: anchor,
            segments: Vec::new(),
            ledger_coverage: Vec::new(),
            legacy_window: None,
            invalid: false,
        });
        Ok(Guard { token })
    })
}

impl Drop for Guard {
    fn drop(&mut self) {
        STATE.with(|slot| {
            let mut slot = slot.borrow_mut();
            if slot
                .as_ref()
                .is_some_and(|state| Rc::ptr_eq(&self.token, &state.token))
            {
                *slot = None;
            }
        });
    }
}

pub(crate) fn span(label: &str) -> Span {
    let identity = STATE.with(|slot| {
        let mut slot = slot.borrow_mut();
        let state = slot.as_mut()?;
        if state.stack.is_empty() {
            return None;
        }
        let id = state.next_id;
        state.next_id += 1;
        let now = Instant::now();
        state.transition(now);
        state.stack.push(Frame {
            id,
            label: label.to_owned(),
            started: now,
            children_seconds: 0.0,
        });
        Some((Rc::clone(&state.token), id))
    });
    Span {
        identity,
        _not_send: PhantomData,
    }
}

pub(crate) fn measure<T>(label: &str, work: impl FnOnce() -> T) -> T {
    let _span = span(label);
    work()
}

pub(crate) fn enabled() -> bool {
    STATE.with(|slot| {
        slot.borrow()
            .as_ref()
            .is_some_and(|state| !state.stack.is_empty())
    })
}

/// Legacy ledger rows contain durations, not start/end timestamps. Reconstruct
/// each covered interval as ending at this call; its endpoint is therefore
/// approximate by the timer-to-record call overhead. Enclosing intervals may
/// overlap rows inside them: finish takes their union instead of adding them.
pub(crate) fn record_ledger_coverage(seconds: f64) {
    if !seconds.is_finite() || seconds <= 0.0 {
        return;
    }
    STATE.with(|slot| {
        let mut slot = slot.borrow_mut();
        let Some(state) = slot.as_mut().filter(|state| !state.stack.is_empty()) else {
            return;
        };
        let end = state.offset(Instant::now());
        state.ledger_coverage.push(Interval {
            start: end - seconds,
            end,
        });
    });
}

/// Record the exact Instant boundaries used for legacy costs.wall_seconds.
pub(crate) fn record_legacy_window(started: Instant, ended: Instant) {
    STATE.with(|slot| {
        let mut slot = slot.borrow_mut();
        let Some(state) = slot.as_mut().filter(|state| !state.stack.is_empty()) else {
            return;
        };
        if ended < started || state.legacy_window.is_some() {
            state.invalid = true;
            return;
        }
        state.legacy_window = Some(Interval {
            start: state.offset(started),
            end: state.offset(ended),
        });
    });
}

impl State {
    fn offset(&self, instant: Instant) -> f64 {
        match instant.checked_duration_since(self.anchor) {
            Some(duration) => duration.as_secs_f64(),
            None => -self.anchor.duration_since(instant).as_secs_f64(),
        }
    }

    fn transition(&mut self, now: Instant) {
        let active = self.stack.last().expect("active profile has a root span");
        self.segments.push(Segment {
            interval: Interval {
                start: self.offset(self.last_transition),
                end: self.offset(now),
            },
            label: active.label.clone(),
            // JSON encodes the label list without ambiguous path separators.
            path: serde_json::to_string(
                &self
                    .stack
                    .iter()
                    .map(|frame| &frame.label)
                    .collect::<Vec<_>>(),
            )
            .expect("string label lists are serializable"),
        });
        self.last_transition = now;
    }

    fn close_top(&mut self, now: Instant) -> f64 {
        let frame = self.stack.pop().expect("span stack checked before closing");
        let inclusive = now.duration_since(frame.started).as_secs_f64();
        // Direct child intervals are disjoint and contained in the parent. Do
        // not clamp: keeping the subtraction exposes any accounting defect.
        let exclusive = inclusive - frame.children_seconds;
        let totals = self.totals.entry(frame.label).or_default();
        totals.calls += 1;
        totals.inclusive_seconds += inclusive;
        totals.exclusive_seconds += exclusive;
        if let Some(parent) = self.stack.last_mut() {
            parent.children_seconds += inclusive;
        }
        inclusive
    }
}

impl Drop for Span {
    fn drop(&mut self) {
        let Some((token, id)) = self.identity.take() else {
            return;
        };
        STATE.with(|slot| {
            let mut slot = slot.borrow_mut();
            let Some(state) = slot.as_mut() else {
                return;
            };
            if !Rc::ptr_eq(&token, &state.token) {
                return;
            }
            if state.stack.last().is_some_and(|frame| frame.id == id) {
                let now = Instant::now();
                state.transition(now);
                state.close_top(now);
            } else {
                // Drop must not cause a second panic during unwinding. Refuse
                // to publish an invalid profile through finish instead.
                state.invalid = true;
            }
        });
    }
}

pub(crate) fn finish() -> Result<Value> {
    STATE.with(|slot| {
        let mut slot = slot.borrow_mut();
        let state = slot.as_mut().context("no J wall profile is active")?;
        ensure!(
            !state.invalid,
            "J wall profile spans were dropped out of order"
        );
        ensure!(
            state.stack.len() == 1 && state.stack[0].id == 0,
            "J wall profile must finish with only the root span open"
        );
        let now = Instant::now();
        state.transition(now);
        let root_wall_seconds = state.close_top(now);
        let exclusive_total_seconds: f64 = state
            .totals
            .values()
            .map(|value| value.exclusive_seconds)
            .sum();
        let segment_total_seconds: f64 = state
            .segments
            .iter()
            .map(|segment| segment.interval.seconds())
            .sum();
        if let Some(window) = state.legacy_window {
            ensure!(
                window.start >= 0.0 && window.end <= root_wall_seconds,
                "legacy wall window must lie within the profile root"
            );
        }
        let coverage = state.legacy_window.map(|window| {
            attribute_coverage(&state.segments, &state.ledger_coverage, window)
        });
        Ok(serde_json::json!({
            "schema": "zkfdo-j-wall-profile-v2",
            "scope": "single_request_owning_thread_wall",
            "root_wall_seconds": root_wall_seconds,
            "exclusive_total_seconds": exclusive_total_seconds,
            "accounting_residual_seconds": root_wall_seconds - exclusive_total_seconds,
            "segment_total_seconds": segment_total_seconds,
            "segment_accounting_residual_seconds": root_wall_seconds - segment_total_seconds,
            "segment_count": state.segments.len(),
            "labels": state.totals,
            "legacy_coverage": coverage,
            "coverage_note": "Ledger duration intervals end at record calls, so endpoints include small timer-to-record overhead. Overlapping/enclosing intervals are merged by union; coverage_interval_sum_seconds is not the legacy ledger sum. Attribution applies only to the exact legacy wall window. Full paths are JSON-encoded label lists.",
        }))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nested_and_repeated_labels_partition_root_without_parent_double_counting() {
        let _guard = activate().unwrap();
        let legacy_started = Instant::now();
        measure("parent", || {
            measure("child", || {
                std::thread::sleep(std::time::Duration::from_micros(50))
            });
            measure("child", || {
                std::thread::sleep(std::time::Duration::from_micros(50))
            });
        });
        record_legacy_window(legacy_started, Instant::now());
        let result = finish().unwrap();
        let labels = &result["labels"];
        let root = result["root_wall_seconds"].as_f64().unwrap();
        let parent = labels["parent"]["inclusive_seconds"].as_f64().unwrap();
        let children = labels["child"]["inclusive_seconds"].as_f64().unwrap();
        let parent_exclusive = labels["parent"]["exclusive_seconds"].as_f64().unwrap();
        assert_eq!(labels["child"]["calls"], 2);
        assert!(root >= parent && parent >= children && children > 0.0);
        assert!((parent - children - parent_exclusive).abs() < 1e-9);
        assert!(
            result["accounting_residual_seconds"]
                .as_f64()
                .unwrap()
                .abs()
                < 1e-9
        );
        assert!(
            result["segment_accounting_residual_seconds"]
                .as_f64()
                .unwrap()
                .abs()
                < 1e-9
        );
        let coverage = &result["legacy_coverage"];
        assert_eq!(coverage["ledger_union_seconds"], 0.0);
        assert_eq!(
            coverage["legacy_window_seconds"],
            coverage["uncovered_total_seconds"]
        );
        assert!(
            coverage["uncovered_attribution_residual_seconds"]
                .as_f64()
                .unwrap()
                .abs()
                < 1e-9
        );
        assert!(finish().is_err());
    }

    #[test]
    fn interval_union_clips_merges_nested_touching_and_overlapping_intervals() {
        let intervals = [
            Interval {
                start: -2.0,
                end: 2.0,
            },
            Interval {
                start: 1.0,
                end: 5.0,
            },
            Interval {
                start: 4.0,
                end: 7.0,
            },
            Interval {
                start: 7.0,
                end: 8.0,
            },
            Interval {
                start: 9.0,
                end: 12.0,
            },
            Interval {
                start: 20.0,
                end: 21.0,
            },
            Interval {
                start: 2.0,
                end: 3.0,
            },
        ];
        assert_eq!(
            merge_intervals(
                &intervals,
                Interval {
                    start: 1.0,
                    end: 10.0
                }
            ),
            vec![
                Interval {
                    start: 1.0,
                    end: 8.0
                },
                Interval {
                    start: 9.0,
                    end: 10.0
                }
            ]
        );
        assert!(Interval {
            start: 1.0,
            end: 2.0
        }
        .intersect(Interval {
            start: 2.0,
            end: 3.0
        })
        .is_none());
    }

    #[test]
    fn uncovered_attribution_uses_interval_union_and_exact_window_clipping() {
        let segment = |start, end, label: &str, path: &str| Segment {
            interval: Interval { start, end },
            label: label.into(),
            path: path.into(),
        };
        let segments = [
            segment(0.0, 3.0, "a", "first_a"),
            segment(3.0, 6.0, "b", "b"),
            segment(6.0, 10.0, "a", "second_a"),
        ];
        let intervals = [
            Interval {
                start: 0.0,
                end: 2.0,
            },
            Interval {
                start: 1.0,
                end: 4.0,
            },
            Interval {
                start: 5.0,
                end: 7.0,
            },
            Interval {
                start: 8.0,
                end: 12.0,
            },
        ];
        let window = Interval {
            start: 1.0,
            end: 9.0,
        };
        let coverage = attribute_coverage(&segments, &intervals, window);
        assert_eq!(coverage.legacy_window_seconds, 8.0);
        assert_eq!(coverage.coverage_interval_sum_seconds, 7.0);
        assert_eq!(coverage.ledger_union_seconds, 6.0);
        assert_eq!(coverage.uncovered_total_seconds, 2.0);
        assert_eq!(coverage.covered_by_label["a"], 4.0);
        assert_eq!(coverage.covered_by_label["b"], 2.0);
        assert_eq!(coverage.uncovered_by_label["a"], 1.0);
        assert_eq!(coverage.uncovered_by_label["b"], 1.0);
        assert_eq!(coverage.uncovered_by_path["first_a"], 0.0);
        assert_eq!(coverage.uncovered_by_path["second_a"], 1.0);
        assert_eq!(coverage.uncovered_attribution_residual_seconds, 0.0);
        let empty = attribute_coverage(&segments, &[], window);
        assert_eq!(empty.ledger_union_seconds, 0.0);
        assert_eq!(empty.uncovered_total_seconds, 8.0);
        assert_eq!(empty.uncovered_by_label["a"], 5.0);
        let full = attribute_coverage(
            &segments,
            &[Interval {
                start: 0.0,
                end: 10.0,
            }],
            window,
        );
        assert_eq!(full.ledger_union_seconds, 8.0);
        assert_eq!(full.uncovered_total_seconds, 0.0);
    }

    #[test]
    fn coverage_api_ignores_zero_and_inactive_rows_and_deduplicates_nested_coverage() {
        record_ledger_coverage(1.0);
        let before = Instant::now();
        record_legacy_window(before, before);
        let _guard = activate().unwrap();
        record_ledger_coverage(0.0);
        record_ledger_coverage(-1.0);
        record_ledger_coverage(f64::NAN);
        assert!(STATE.with(|slot| slot.borrow().as_ref().unwrap().ledger_coverage.is_empty()));
        let started = Instant::now();
        std::thread::sleep(std::time::Duration::from_micros(50));
        let ended = Instant::now();
        record_legacy_window(started, ended);
        // Both intervals entirely enclose the small exact legacy window.
        record_ledger_coverage(1_000_000.0);
        record_ledger_coverage(1_000_000.0);
        let result = finish().unwrap();
        let coverage = &result["legacy_coverage"];
        assert_eq!(
            coverage["ledger_union_seconds"],
            coverage["legacy_window_seconds"]
        );
        assert_eq!(coverage["uncovered_total_seconds"], 0.0);
    }

    #[test]
    fn inactive_and_unwinding_requests_leave_no_state() {
        assert!(finish().is_err());
        assert_eq!(measure("disabled", || 7), 7);
        let failure = std::panic::catch_unwind(|| {
            let _guard = activate().unwrap();
            assert!(activate().is_err());
            measure("failure", || panic!("synthetic profile failure"));
        });
        assert!(failure.is_err());
        assert!(finish().is_err());
        let _guard = activate().unwrap();
        assert!(finish().unwrap()["labels"].get("failure").is_none());
    }

    #[test]
    fn threads_and_late_spans_cannot_mix_requests() {
        let guard = activate().unwrap();
        let stale = span("stale");
        drop(guard);
        let _guard = activate().unwrap();
        drop(stale);
        std::thread::spawn(|| {
            assert!(finish().is_err());
            let _guard = activate().unwrap();
            measure("worker_request", || ());
            assert!(finish().unwrap()["labels"].get("worker_request").is_some());
        })
        .join()
        .unwrap();
        let result = finish().unwrap();
        assert!(result["labels"].get("stale").is_none());
        assert!(result["labels"].get("worker_request").is_none());
    }

    #[test]
    fn invalid_drop_order_and_open_spans_refuse_a_profile() {
        let _guard = activate().unwrap();
        let parent = span("parent");
        let child = span("child");
        assert!(finish().is_err());
        drop(parent);
        drop(child);
        assert!(finish().is_err());
    }
}
