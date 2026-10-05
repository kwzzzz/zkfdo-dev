//! Candidate-linked timing only. Never reinterpret legacy free-text timestamps.
use super::{known, occurrence_ref};
use crate::evidence_record::{aggregate_schema::*, schema::*};
use std::collections::{BTreeMap, BTreeSet};

type Frame = (String, String, String, TimeBasis);

pub(super) fn summarize(
    records: &[&EvidenceRecord],
    occurrences: &[Occurrence],
    inventory_complete: bool,
    review_inventory_complete: bool,
    require_attribution: bool,
) -> TimeSummary {
    let qualifies = |o: &&Occurrence| {
        if require_attribution {
            o.attributed
        } else {
            o.confirmed
        }
    };
    let confirmed: Vec<_> = occurrences.iter().filter(qualifies).collect();
    let mut frames: BTreeMap<Frame, BTreeMap<OccurrenceRef, f64>> = BTreeMap::new();
    let mut ignored = 0;
    for r in records {
        let Some(meta) = &r.aggregation_metadata else {
            continue;
        };
        for t in &meta.candidate_times {
            if !t.basis_verified
                || known(&r.execution.run_id) != Some(&t.run_id)
                || known(&r.execution.target_id) != Some(&t.target_id)
                || known(&r.execution.campaign_id) != Some(&t.campaign_id)
                || !r
                    .execution
                    .candidates
                    .iter()
                    .any(|c| c.sha256.eq_ignore_ascii_case(&t.candidate_sha256))
            {
                ignored += 1;
                continue;
            }
            let frame = (
                t.campaign_id.clone(),
                t.clock_id.clone(),
                t.origin.clone(),
                t.basis,
            );
            frames.entry(frame).or_default().insert(
                OccurrenceRef {
                    record_id: r.record_id.clone(),
                    candidate_sha256: t.candidate_sha256.to_ascii_lowercase(),
                },
                t.seconds,
            );
        }
    }
    let mut series = Vec::new();
    for ((campaign_id, clock_id, origin, basis), times) in frames {
        let linked: Vec<_> = confirmed
            .iter()
            .filter_map(|o| times.get(&occurrence_ref(o)).map(|t| (*o, *t)))
            .collect();
        let Some(seconds) = linked.iter().map(|(_, t)| *t).min_by(f64::total_cmp) else {
            continue;
        };
        let mut blockers = Vec::new();
        if !inventory_complete {
            blockers.push("candidate/campaign inventory is incomplete; unseen earlier candidates remain possible".into());
        }
        if !review_inventory_complete {
            blockers.push("expected review inventory is incomplete".into());
        }
        if linked.len() != confirmed.len() {
            blockers.push(
                "some confirmed occurrences have no compatible timestamp in this frame".into(),
            );
        }
        for o in occurrences.iter().filter(|o| o.unresolved) {
            let is_later = basis == TimeBasis::ExactGeneration
                && times.get(&occurrence_ref(o)).is_some_and(|t| *t > seconds);
            if !is_later {
                blockers.push(format!(
                    "{}:{} unresolved review can precede this result",
                    o.record_id, o.candidate_sha256
                ));
            }
        }
        let kind = if !blockers.is_empty() {
            TimeResultKind::ObservedMinimum
        } else {
            match basis {
                TimeBasis::ExactGeneration => TimeResultKind::ExactFirst,
                TimeBasis::CompletionUpperBound => TimeResultKind::CompletionUpperBound,
                TimeBasis::LogObservation => TimeResultKind::ObservedMinimum,
            }
        };
        let candidate_refs: BTreeSet<_> = linked
            .into_iter()
            .filter(|(_, t)| *t == seconds)
            .map(|(o, _)| occurrence_ref(o))
            .collect();
        series.push(TimeSeries {
            campaign_id,
            clock_id,
            origin,
            basis,
            kind,
            seconds,
            candidate_refs: candidate_refs.into_iter().collect(),
            blockers,
        });
    }
    let (kind, seconds, reason) = if series.len() == 1 {
        let s = &series[0];
        (s.kind,Recorded::known(s.seconds),match s.kind {
            TimeResultKind::ExactFirst => "earliest exact generation timestamp among reported qualifying confirmations; declared inventory and preceding review are complete",
            TimeResultKind::CompletionUpperBound => "completion-based upper bound on first qualifying generation; not an exact discovery or review-confirmation timestamp",
            _ => "minimum linked observation in this compatible frame; does not establish the first qualifying generation",
        }.to_string())
    } else if series.is_empty() {
        (TimeResultKind::Unavailable,Recorded::unknown("no qualifying confirmation with a bound, verified candidate timestamp"),format!("legacy unlinked times are not assigned to candidates; {ignored} invalid/unverified candidate-time links ignored"))
    } else {
        (TimeResultKind::Unavailable,Recorded::unknown("multiple incompatible timing frames; no cross-frame minimum"),"time basis, origin, clock or campaign differ; inspect separate series without selecting a favorable frame".into())
    };
    TimeSummary {
        kind,
        seconds,
        reason,
        series,
    }
}
