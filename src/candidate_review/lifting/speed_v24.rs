//! Opt-in, request-local execution options and check timing. Structural SYM
//! equivalence is checked in full on every call; no artifacts or comparison
//! verdicts are cached here.

use std::{cell::RefCell, marker::PhantomData, rc::Rc, time::Instant};

use anyhow::{ensure, Result};
use serde::Serialize;
use serde_json::Value;

#[derive(Default, Serialize)]
struct Stats {
    sym_equivalence_calls: u64,
    sym_equivalence_successes: u64,
    sym_equivalence_failures: u64,
    check_calls: u64,
    check_seconds: f64,
    sym_equivalence_seconds: f64,
}

struct State {
    jobs: usize,
    stats: Stats,
}

thread_local! {
    static STATE: RefCell<Option<State>> = const { RefCell::new(None) };
}

/// A guard cannot move to another thread: its drop must clear the same TLS slot
/// it activated. Errors and unwinding also discard the request's state.
pub(crate) struct Guard {
    _not_send: PhantomData<Rc<()>>,
}

pub(crate) fn activate(jobs: usize) -> Result<Guard> {
    ensure!((1..=64).contains(&jobs), "--j-jobs must be in 1..=64");
    STATE.with(|slot| {
        let mut slot = slot.borrow_mut();
        ensure!(
            slot.is_none(),
            "a J v2.4 request is already active on this thread"
        );
        *slot = Some(State {
            jobs,
            stats: Stats::default(),
        });
        Ok(Guard {
            _not_send: PhantomData,
        })
    })
}

impl Drop for Guard {
    fn drop(&mut self) {
        STATE.with(|slot| *slot.borrow_mut() = None);
    }
}

pub(crate) fn enabled() -> bool {
    STATE.with(|slot| slot.borrow().is_some())
}

pub(crate) fn jobs() -> usize {
    STATE.with(|slot| slot.borrow().as_ref().map_or(1, |state| state.jobs))
}

pub(crate) fn record_check(seconds: f64) {
    STATE.with(|slot| {
        if let Some(state) = slot.borrow_mut().as_mut() {
            state.stats.check_calls += 1;
            state.stats.check_seconds += seconds;
        }
    });
}

pub(crate) fn telemetry() -> Value {
    STATE.with(|slot| match slot.borrow().as_ref() {
        Some(state) => serde_json::json!({
            "enabled": true,
            "max_j_jobs": state.jobs,
            "scope": "single_request",
            "stats": state.stats,
            "sym_equivalence_policy": "full_structural_comparison_every_call",
        }),
        None => serde_json::json!({"enabled": false}),
    })
}

pub(crate) fn sym_equivalence(original: &str, other: &str) -> Result<usize> {
    let _profile_span = super::profile_v24::span("sym.full_comparison");
    STATE.with(|slot| {
        let mut slot = slot.borrow_mut();
        let Some(state) = slot.as_mut() else {
            return super::repair::sym_equivalence_uncached(original, other);
        };
        state.stats.sym_equivalence_calls += 1;
        let started = Instant::now();
        let result = super::repair::sym_equivalence_fast(original, other);
        state.stats.sym_equivalence_seconds += started.elapsed().as_secs_f64();
        if result.is_ok() {
            state.stats.sym_equivalence_successes += 1;
        } else {
            state.stats.sym_equivalence_failures += 1;
        }
        result
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn equivalence_checks_every_call_including_repeated_and_invalid_text() {
        let _guard = activate(1).unwrap();
        let original = "1,1,0,main.x\n";
        assert_eq!(sym_equivalence(original, original).unwrap(), 0);
        assert_eq!(sym_equivalence(original, original).unwrap(), 0);
        assert_eq!(telemetry()["stats"]["sym_equivalence_calls"], 2);
        assert_eq!(telemetry()["stats"]["sym_equivalence_successes"], 2);
        assert!(sym_equivalence(original, "1,1,0,main.y\n").is_err());
        assert!(sym_equivalence("invalid", "invalid").is_err());
        assert!(sym_equivalence("invalid", "invalid").is_err());
        assert_eq!(telemetry()["stats"]["sym_equivalence_calls"], 5);
        assert_eq!(telemetry()["stats"]["sym_equivalence_successes"], 2);
        assert_eq!(telemetry()["stats"]["sym_equivalence_failures"], 3);
    }

    #[test]
    fn guard_clears_state_when_request_unwinds() {
        let result = std::panic::catch_unwind(|| {
            let _guard = activate(2).unwrap();
            assert_eq!(
                sym_equivalence("1,1,0,main.x\n", "1,1,0,main.x\n").unwrap(),
                0
            );
            panic!("synthetic request failure");
        });
        assert!(result.is_err());
        assert!(!enabled());
        assert!(activate(0).is_err());
        assert!(activate(65).is_err());
        let _guard = activate(1).unwrap();
        assert_eq!(telemetry()["stats"]["sym_equivalence_calls"], 0);
    }

    #[test]
    fn request_options_and_counters_do_not_cross_guard_boundaries() {
        record_check(99.0);
        assert_eq!(telemetry(), serde_json::json!({"enabled": false}));
        let guard = activate(4).unwrap();
        assert!(activate(1).is_err());
        record_check(0.25);
        assert_eq!(jobs(), 4);
        assert_eq!(telemetry()["stats"]["check_calls"], 1);
        assert_eq!(telemetry()["stats"]["check_seconds"], 0.25);
        drop(guard);
        assert!(!enabled());
        assert_eq!(jobs(), 1);
        let _next = activate(2).unwrap();
        assert_eq!(jobs(), 2);
        assert_eq!(telemetry()["stats"]["check_calls"], 0);
        assert_eq!(telemetry()["stats"]["check_seconds"], 0.0);
    }

    #[test]
    fn anonymous_rename_counts_and_request_states_are_thread_local() {
        let _guard = activate(4).unwrap();
        let original = "1,1,0,main.Inner_1_20.x\n";
        let renamed = "1,1,0,main.Inner_1_30.x\n";
        assert_eq!(sym_equivalence(original, renamed).unwrap(), 1);
        assert_eq!(sym_equivalence(original, renamed).unwrap(), 1);
        std::thread::spawn(|| {
            assert!(!enabled());
            assert_eq!(jobs(), 1);
            let _guard = activate(2).unwrap();
            assert_eq!(telemetry()["stats"]["sym_equivalence_calls"], 0);
            assert_eq!(jobs(), 2);
        })
        .join()
        .unwrap();
        assert_eq!(jobs(), 4);
        assert_eq!(telemetry()["stats"]["sym_equivalence_calls"], 2);
        assert_eq!(telemetry()["stats"]["sym_equivalence_successes"], 2);
    }
}
