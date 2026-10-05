//! Offline aggregation of *reported* metadata claims, never semantic certification.
//! Only the request and its hash-pinned evidence records are read.
use super::{
    aggregate_schema::*, attribution_method_supported, metadata_binding, read_pinned, schema::*,
    sha256, validate_observation, validate_recorded, validate_ref,
};
use crate::candidate_review::schema::FileRef;
use anyhow::{ensure, Context as _, Result};
use serde_json::json;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::Write,
    path::Path,
};

#[path = "aggregate_time.rs"]
mod time;

fn known<T>(v: &Recorded<T>) -> Option<&T> {
    match v {
        Recorded::Known { value } => Some(value),
        Recorded::Unknown { .. } => None,
    }
}
fn text_required(v: &str) -> Result<()> {
    ensure!(!v.trim().is_empty(), "empty aggregation identity/reason");
    Ok(())
}
fn refs(v: &[FileRef]) -> Result<()> {
    for r in v {
        validate_ref(r)?;
    }
    Ok(())
}
fn coverage(v: &Coverage) -> Result<()> {
    text_required(&v.reason)?;
    refs(&v.evidence)?;
    ensure!(
        !v.complete || !v.evidence.is_empty(),
        "complete inventory requires evidence references"
    );
    Ok(())
}
fn unique<'a>(v: impl Iterator<Item = &'a str>) -> bool {
    let mut seen = BTreeSet::new();
    v.into_iter().all(|x| seen.insert(x))
}

pub(super) fn validate_aggregation_metadata(record: &EvidenceRecord) -> Result<()> {
    ensure!(
        matches!(record.schema_version, 1 | 2),
        "unsupported evidence record schema"
    );
    ensure!(
        (record.schema_version == 2) == record.aggregation_metadata.is_some(),
        "v1 has no aggregation metadata; v2 requires it"
    );
    let Some(meta) = &record.aggregation_metadata else {
        return Ok(());
    };
    coverage(&meta.candidate_inventory)?;
    let mut layers = BTreeSet::new();
    for item in &meta.review_inventory {
        coverage(&item.coverage)?;
        ensure!(
            layers.insert(item.layer),
            "duplicate review inventory layer"
        );
        ensure!(
            unique(item.expected_observation_ids.iter().map(String::as_str)),
            "duplicate expected review ID"
        );
        for id in &item.expected_observation_ids {
            text_required(id)?;
        }
    }
    let mut times = BTreeMap::new();
    for t in &meta.candidate_times {
        for s in [
            &t.run_id,
            &t.target_id,
            &t.campaign_id,
            &t.clock_id,
            &t.origin,
        ] {
            text_required(s)?;
        }
        validate_ref(&FileRef {
            path: "metadata-only-time-link".into(),
            sha256: t.candidate_sha256.clone(),
        })?;
        ensure!(
            t.seconds.is_finite() && t.seconds >= 0.0,
            "invalid candidate time"
        );
        refs(&t.evidence)?;
        ensure!(
            !t.basis_verified || !t.evidence.is_empty(),
            "verified time basis needs evidence"
        );
        let key = (
            t.candidate_sha256.to_ascii_lowercase(),
            &t.run_id,
            &t.target_id,
            &t.campaign_id,
            &t.clock_id,
            &t.origin,
            t.basis,
        );
        if let Some(previous) = times.insert(key, t.seconds) {
            ensure!(
                previous == t.seconds,
                "conflicting candidate timestamps in one frame"
            );
        }
    }
    ensure!(
        unique(
            meta.review_semantics
                .iter()
                .map(|x| x.observation_id.as_str())
        ),
        "duplicate review semantics ID"
    );
    for s in &meta.review_semantics {
        text_required(&s.observation_id)?;
        ensure!(
            record
                .reviews
                .iter()
                .any(|r| r.observation.observation_id == s.observation_id),
            "semantics refers to absent observation"
        );
        validate_recorded(&serde_json::to_value(s)?)?;
        refs(&s.violation_evidence)?;
        refs(&s.localization_evidence)?;
        ensure!(
            known(&s.violation_kind).is_none() || !s.violation_evidence.is_empty(),
            "violation kind requires type-specific evidence"
        );
        ensure!(
            known(&s.localization_method).is_none() || !s.localization_evidence.is_empty(),
            "localization method requires evidence"
        );
        // The schema has no validation-record reference, so true would be an unsupported claim.
        ensure!(
            !matches!(
                s.localization_method_validated,
                Recorded::Known { value: true }
            ),
            "validated localization method needs a validation record; record it as unknown"
        );
    }
    Ok(())
}

/// Source metadata shows that candidate references are missing, not empty.
pub(super) fn missing_candidate_refs(r: &EvidenceRecord) -> Option<String> {
    if known(&r.execution.backend_status).is_some_and(|s| s == "bug_found")
        && r.execution.candidates.is_empty()
    {
        return Some("bug_found without a candidate reference; the inventory is missing".into());
    }
    match (&r.source, &r.execution.candidate_inventory) {
        (MetadataSource::ExperimentOutcome { .. }, Recorded::Unknown { reason }) => Some(format!(
            "source metadata did not establish the candidate list: {reason}"
        )),
        _ => None,
    }
}

/// Only a finished search lets a candidate list stand for the attempt's output.
/// Failed or unknown executions are not candidate absence.
fn inventory_blocker(r: &EvidenceRecord) -> Option<String> {
    match known(&r.execution.backend_status).map(String::as_str) {
        Some("no_counterexample" | "timeout" | "bug_found") => missing_candidate_refs(r),
        Some(status) => Some(format!(
            "backend status {status} is not a finished search; absence is not established"
        )),
        None => Some("backend status unknown; candidate absence is not established".into()),
    }
}

fn validate_record(r: &EvidenceRecord) -> Result<()> {
    text_required(&r.record_id)?;
    text_required(&r.context.execution_unit_id)?;
    validate_aggregation_metadata(r)?;
    // Exit status is signed, unlike resource/time measurements.
    let mut value = serde_json::to_value(r)?;
    value["execution"]["exit_code"] = json!(Recorded::<i32>::unknown(
        "signed exit status validated by deserialization"
    ));
    // Legacy backend records have their own vocabulary and are preserved, not reinterpreted.
    value["preserved_review_reports"] = json!([]);
    for row in value["reviews"].as_array_mut().into_iter().flatten() {
        row["legacy_review"] = serde_json::Value::Null;
    }
    validate_recorded(&value)?;
    validate_ref(&r.request)?;
    validate_ref(r.source.file())?;
    refs(&r.execution.candidates)?;
    if let Some(hash) = known(&r.context.settings_sha256) {
        validate_ref(&FileRef {
            path: "settings-identity".into(),
            sha256: hash.clone(),
        })?;
    }
    ensure!(
        unique(
            r.reviews
                .iter()
                .map(|row| row.observation.observation_id.as_str())
        ),
        "duplicate observation ID within record"
    );
    for row in &r.reviews {
        validate_observation(&row.observation)?;
        if let Some(reference) = known(&row.source_report) {
            validate_ref(reference)?;
        }
    }
    let mut reports = BTreeSet::new();
    for p in &r.preserved_review_reports {
        validate_ref(&p.file)?;
        ensure!(
            reports.insert(p.file.sha256.to_ascii_lowercase()),
            "duplicate preserved report"
        );
        ensure!(
            p.report.schema_version == 1
                && p.report.kind == crate::candidate_review::schema::ReportKind::BackendCandidates
                && !p.report.raw_values_persisted,
            "aggregation accepts only value-free schema-1 backend review metadata"
        );
    }
    if let (Some(a), Some(b)) = (
        known(&r.context.repetition),
        known(&r.execution.source_repetition),
    ) {
        ensure!(a == b, "requested and observed repetition conflict");
    }
    if let Some(method) = known(&r.execution.source_method) {
        ensure!(
            !matches!(method.as_str(), "whole" | "split")
                || (method == "whole") == (r.context.method == Method::Whole),
            "requested and observed method conflict"
        );
        if matches!(r.source, MetadataSource::P2Ledger { .. }) {
            let observed = match method.as_str() {
                "whole" => Method::Whole,
                "path-order" | "small-first" | "random" => Method::Split,
                _ => anyhow::bail!("unrecognized P2 lane in evidence record"),
            };
            ensure!(
                observed == r.context.method,
                "P2 lane conflicts with declared method"
            );
        }
    }
    Ok(())
}

fn layer_of(o: &ReviewObservation) -> Layer {
    match o.component_layer {
        ComponentLayer::General => Layer::ComponentGeneral,
        ComponentLayer::Contract => Layer::ComponentContract,
        ComponentLayer::LegacyUnspecified => Layer::LegacyUnspecified,
    }
}
fn applies(o: &ReviewObservation, layer: Layer) -> bool {
    layer == Layer::EntrypointTcct || layer_of(o) == layer
}
fn bound(r: &EvidenceRecord, row: &ImportedReview) -> bool {
    matches!(row.metadata_binding, Recorded::Known { value: true })
        && matches!(
            metadata_binding(&r.execution, &row.observation),
            Recorded::Known { value: true }
        )
}
fn confirmed(r: &EvidenceRecord, row: &ImportedReview, layer: Layer) -> bool {
    let o = &row.observation;
    if !bound(r, row) || o.completion != Completion::Complete {
        return false;
    }
    if layer == Layer::EntrypointTcct {
        return row.legacy_review.is_none()
            && o.entrypoint_tcct.state == ReviewState::ReportedConfirmed;
    }
    if layer_of(o) != layer || (layer != Layer::LegacyUnspecified && row.legacy_review.is_some()) {
        return false;
    }
    o.component.state == ReviewState::ReportedConfirmed && mapped(r, o)
}
fn mapped(r: &EvidenceRecord, o: &ReviewObservation) -> bool {
    o.projection.state == ReviewState::ReportedConfirmed
        && matches!(
            o.localization,
            Localization::Localized { .. } | Localization::Root { .. }
        )
        && !(r.context.method == Method::Split
            && matches!(o.localization, Localization::Root { .. }))
}
fn semantics<'a>(r: &'a EvidenceRecord, o: &ReviewObservation) -> Option<&'a ReviewSemantics> {
    r.aggregation_metadata
        .as_ref()?
        .review_semantics
        .iter()
        .find(|s| s.observation_id == o.observation_id)
}
/// The general layer holds the general TCCT kinds. A tool-specific check stays
/// a confirmed claim there but is not a general cause.
fn kind_attributable(kind: &ViolationKind, layer: Layer) -> bool {
    layer != Layer::ComponentGeneral
        || matches!(
            kind,
            ViolationKind::OutputDifference | ViolationKind::ComputationAbort
        )
}
fn tool_specific(r: &EvidenceRecord, o: &ReviewObservation) -> bool {
    semantics(r, o).is_some_and(|s| {
        matches!(
            s.violation_kind,
            Recorded::Known {
                value: ViolationKind::ToolSpecificCheck
            }
        )
    })
}
fn basic_attribution(r: &EvidenceRecord, row: &ImportedReview, layer: Layer) -> bool {
    let o = &row.observation;
    layer != Layer::EntrypointTcct
        && layer != Layer::LegacyUnspecified
        && confirmed(r, row, layer)
        && o.attribution.state == AttributionState::Matched
        && known(&o.attribution.method).is_some_and(|m| attribution_method_supported(m))
        && known(&o.attribution.proposed_cause_id).is_some()
        && semantics(r, o).is_some_and(|s| {
            known(&s.violation_kind).is_some_and(|k| kind_attributable(k, layer))
                && !s.violation_evidence.is_empty()
                && known(&s.localization_method).is_some()
                && !s.localization_evidence.is_empty()
        })
}
fn valid_duplicate(r: &EvidenceRecord, row: &ImportedReview, layer: Layer) -> bool {
    let o = &row.observation;
    let cause = known(&o.attribution.proposed_cause_id);
    match &o.cause_deduplication {
        CauseDeduplication::Canonical => {}
        CauseDeduplication::DuplicateOf { cause_id } => {
            if cause != Some(cause_id)
                || !r.reviews.iter().any(|x| {
                    basic_attribution(r, x, layer)
                        && matches!(
                            x.observation.cause_deduplication,
                            CauseDeduplication::Canonical
                        )
                        && known(&x.observation.attribution.proposed_cause_id) == Some(cause_id)
                })
            {
                return false;
            }
        }
        CauseDeduplication::Unresolved { .. } => return false,
    }
    let mut seen = BTreeSet::from([o.observation_id.as_str()]);
    let mut current = row;
    while let Some(id) = known(&current.observation.duplicate_of) {
        if !seen.insert(id) {
            return false;
        }
        let Some(next) = r
            .reviews
            .iter()
            .find(|x| &x.observation.observation_id == id)
        else {
            return false;
        };
        if !basic_attribution(r, next, layer)
            || known(&next.observation.attribution.proposed_cause_id) != cause
        {
            return false;
        }
        current = next;
    }
    true
}
fn review_ref(r: &EvidenceRecord, row: &ImportedReview) -> ReviewRef {
    ReviewRef {
        record_id: r.record_id.clone(),
        observation_id: row.observation.observation_id.clone(),
    }
}
fn occurrence_ref(o: &Occurrence) -> OccurrenceRef {
    OccurrenceRef {
        record_id: o.record_id.clone(),
        candidate_sha256: o.candidate_sha256.clone(),
    }
}

fn material(r: &EvidenceRecord) -> Result<String> {
    let mut versions = r.execution.source_versions.clone();
    // These identify the observation container, not the executed configuration.
    for key in ["outcome_id", "plan_id", "schema_version", "metadata_sha256"] {
        versions.remove(key);
    }
    Ok(sha256(&serde_json::to_vec(
        &json!({"context":r.context, "policy":r.policy_intent,"rules":r.policy_rules,"versions":versions}),
    )?))
}
fn unit_material(r: &EvidenceRecord) -> Result<String> {
    Ok(sha256(&serde_json::to_vec(&json!([
        r.context.project,
        r.context.source_version,
        r.context.entrypoint,
        r.context.settings_sha256,
        r.context.tool_versions
    ]))?))
}
fn identity_known(r: &EvidenceRecord) -> bool {
    known(&r.context.project).is_some()
        && known(&r.context.source_version).is_some()
        && known(&r.context.entrypoint).is_some()
        && known(&r.context.settings_sha256).is_some()
        && !r.context.tool_versions.is_empty()
        && r.context.tool_versions.values().all(|x| known(x).is_some())
}
fn campaign_matches(c: &CampaignCoverage, r: &EvidenceRecord) -> bool {
    c.execution_unit_id == r.context.execution_unit_id
        && c.method == r.context.method
        && known(&r.execution.campaign_id) == Some(&c.campaign_id)
        && known(&r.context.repetition) == Some(&c.repetition)
}
fn inventory(r: &EvidenceRecord, layer: Layer) -> bool {
    let Some(meta) = &r.aggregation_metadata else {
        return false;
    };
    let Some(c) = meta.review_inventory.iter().find(|x| x.layer == layer) else {
        return false;
    };
    let actual: BTreeSet<_> = r
        .reviews
        .iter()
        .filter(|x| applies(&x.observation, layer))
        .map(|x| &x.observation.observation_id)
        .collect();
    c.coverage.complete && actual == c.expected_observation_ids.iter().collect()
}

/// Aggregate metadata into a new file. Neither nested references nor candidates are opened.
pub fn aggregate_records(request_path: &Path, output_path: &Path) -> Result<AggregateReport> {
    let path = fs::canonicalize(request_path).context("aggregate request unavailable")?;
    let bytes = fs::read(&path)?;
    let request: AggregateRequest =
        serde_json::from_slice(&bytes).context("invalid aggregate request")?;
    ensure!(
        request.schema_version == 1,
        "unsupported aggregate request version"
    );
    ensure!(!request.records.is_empty(), "aggregate needs input records");
    let base = path.parent().context("request has no parent")?;
    let mut records = Vec::new();
    let mut ids = BTreeSet::new();
    for input in &request.records {
        let record: EvidenceRecord = serde_json::from_slice(&read_pinned(base, input)?)
            .context("invalid evidence record")?;
        validate_record(&record)?;
        ensure!(
            ids.insert(record.record_id.clone()),
            "duplicate record ID; disambiguate input identity, do not select one"
        );
        records.push(record);
    }
    for c in &request.campaigns {
        coverage(&c.coverage)?;
        for x in [&c.execution_unit_id, &c.campaign_id, &c.repetition] {
            text_required(x)?;
        }
        ensure!(
            !c.record_ids.is_empty() && unique(c.record_ids.iter().map(String::as_str)),
            "campaign needs unique record IDs"
        );
    }
    let registrations = validate_registry(&request.cause_registry, &records)?;
    let mut partitions: BTreeMap<String, Vec<&EvidenceRecord>> = BTreeMap::new();
    let mut conflicts = Vec::new();
    let mut conflict_records = BTreeSet::new();
    for (i, r) in records.iter().enumerate() {
        for previous in &records[..i] {
            if r.context.execution_unit_id != previous.context.execution_unit_id {
                continue;
            }
            let same_campaign = r.context.method == previous.context.method
                && known(&r.execution.campaign_id).is_some()
                && r.execution.campaign_id == previous.execution.campaign_id
                && known(&r.context.repetition).is_some()
                && r.context.repetition == previous.context.repetition;
            if unit_material(r)? != unit_material(previous)?
                || (same_campaign && material(r)? != material(previous)?)
            {
                let pair = vec![previous.record_id.clone(), r.record_id.clone()];
                conflict_records.extend(pair.clone());
                conflicts.push(Issue {code:"identity-policy-conflict".into(),record_ids:pair,reason:"same execution unit ID has incompatible settings, versions, context or policy; records remain in separate groups and completeness is not claimed".into()});
            }
        }
        let isolate = known(&r.execution.campaign_id).is_none()
            || known(&r.context.repetition).is_none()
            || !identity_known(r);
        let key = serde_json::to_string(&json!([
            r.context.execution_unit_id,
            r.context.method,
            r.execution.campaign_id,
            r.context.repetition,
            material(r)?,
            if isolate { &r.record_id } else { "" }
        ]))?;
        partitions.entry(key).or_default().push(r);
    }
    let mut groups = Vec::new();
    for (key, rows) in partitions {
        for layer in [
            Layer::ComponentGeneral,
            Layer::ComponentContract,
            Layer::LegacyUnspecified,
            Layer::EntrypointTcct,
        ] {
            groups.push(group(
                &key,
                &rows,
                layer,
                &request.campaigns,
                &registrations,
                &conflict_records,
            )?);
        }
    }
    let mut accepted: BTreeMap<(Layer, String, String), RegisteredCause> = BTreeMap::new();
    for g in &groups {
        for c in &g.registered_causes {
            let entry = accepted
                .entry((c.layer, c.scope_id.clone(), c.cause_id.clone()))
                .or_insert_with(|| RegisteredCause {
                    members: vec![],
                    ..c.clone()
                });
            entry.members.extend(c.members.clone());
            entry.members.sort();
            entry.members.dedup();
        }
    }
    let record_contexts = records
        .iter()
        .zip(&request.records)
        .map(|(r, input)| RecordContext {
            record_id: r.record_id.clone(),
            input_record: input.clone(),
            original_request: r.request.clone(),
            source: r.source.clone(),
            context: r.context.clone(),
            policy_intent: r.policy_intent.clone(),
            execution: r.execution.clone(),
            actual_wall_scope: match &r.source {
                MetadataSource::RunnerResult { .. } | MetadataSource::ExperimentOutcome { .. } => {
                    Recorded::known("attempt wall; not a campaign total".into())
                }
                MetadataSource::P2Ledger { .. } => {
                    match known(&r.execution.source_method).map(String::as_str) {
                        Some("whole") => Recorded::known("P2 whole process elapsed wall".into()),
                        Some("path-order" | "small-first" | "random") => Recorded::known(
                            "P2 split campaign elapsed wall; not per-attempt".into(),
                        ),
                        _ => Recorded::unknown("legacy P2 lane does not establish wall scope"),
                    }
                }
            },
            review_semantics: r
                .reviews
                .iter()
                .map(|row| {
                    r.aggregation_metadata
                        .as_ref()
                        .and_then(|m| {
                            m.review_semantics
                                .iter()
                                .find(|s| s.observation_id == row.observation.observation_id)
                        })
                        .cloned()
                        .unwrap_or_else(|| ReviewSemantics {
                            observation_id: row.observation.observation_id.clone(),
                            violation_kind: Recorded::unknown(
                                "type-specific violation evidence is not recorded",
                            ),
                            violation_evidence: vec![],
                            localization_method: Recorded::unknown(
                                "localization method is not recorded",
                            ),
                            localization_method_validated: Recorded::unknown(
                                "localization method has no semantic validation record",
                            ),
                            localization_evidence: vec![],
                        })
                })
                .collect(),
        })
        .collect();
    let report = AggregateReport {
        schema_version:1,request:FileRef {path,sha256:sha256(&bytes)},inputs:request.records,
        groups,conflicts,record_contexts,registered_causes:accepted.into_values().collect(),
        limitations:vec![
            "Aggregation of input-reported outcomes only; this tool does not certify cause meaning, violation types, projection, attribution, localization or wrapper preservation".into(),
            "Only request and hash-pinned evidence record files were read. Nested evidence, source, candidate, circuit, witness and predicate references were NOT opened or rehashed; reported completeness and registry evidence are declarations, not semantic verification".into(),
            "Group/cause/time completeness is relative to the declared inventories and scoped registry; neither candidate counts nor occurrence/spec counts are cause counts. No cross-layer, cross-method or incompatible-frame total is produced".into(),
            "Resource observations and policy intent remain per record; actual wall scopes are labelled, not summed. Policy A execution, equal actual resource use and leftover-budget behavior remain unverified".into(),
            "Time is linked candidate generation/observation/completion timing, not time of human review confirmation. V1 unlinked times never become candidate timestamps".into(),
            "Input source-report relationships and evidence bases remain as recorded. Missing violation/localization semantics stay unknown; method_validated is a reported claim, not a result of this tool".into(),
        ],
    };
    let mut encoded = serde_json::to_vec_pretty(&report)?;
    encoded.push(b'\n');
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output_path)
        .context("aggregate output must be a new file")?;
    if let Err(e) = file.write_all(&encoded) {
        drop(file);
        let _ = fs::remove_file(output_path);
        return Err(e.into());
    }
    Ok(report)
}

type Registry = BTreeMap<ReviewRef, Vec<CauseRegistration>>;
fn validate_registry(
    registry: &[CauseRegistration],
    records: &[EvidenceRecord],
) -> Result<Registry> {
    let mut result: Registry = BTreeMap::new();
    let mut keys = BTreeSet::new();
    for c in registry {
        text_required(&c.scope_id)?;
        text_required(&c.cause_id)?;
        ensure!(
            keys.insert((&c.scope_id, &c.cause_id)),
            "duplicate scoped cause registration; provide one explicit member list"
        );
        ensure!(
            !c.evidence.is_empty()
                && !c.members.is_empty()
                && !c.execution_unit_ids.is_empty()
                && !c.source_versions.is_empty(),
            "cause registry needs scope, members and evidence"
        );
        refs(&c.evidence)?;
        ensure!(
            c.members.iter().collect::<BTreeSet<_>>().len() == c.members.len(),
            "duplicate registry member"
        );
        for member in &c.members {
            let r = records
                .iter()
                .find(|r| r.record_id == member.record_id)
                .context("registry refers to absent record")?;
            ensure!(
                r.reviews
                    .iter()
                    .any(|x| x.observation.observation_id == member.observation_id),
                "registry refers to absent observation"
            );
            ensure!(
                c.execution_unit_ids.contains(&r.context.execution_unit_id)
                    && known(&r.context.source_version)
                        .is_some_and(|v| c.source_versions.contains(v)),
                "cause registration scope does not include member unit/version"
            );
            result.entry(member.clone()).or_default().push(c.clone());
        }
    }
    Ok(result)
}

fn group(
    key: &str,
    records: &[&EvidenceRecord],
    layer: Layer,
    campaigns: &[CampaignCoverage],
    registry: &Registry,
    conflict_records: &BTreeSet<String>,
) -> Result<AggregateGroup> {
    let first = records[0];
    let record_ids: Vec<_> = records.iter().map(|r| r.record_id.clone()).collect();
    let has_conflict = record_ids.iter().any(|id| conflict_records.contains(id));
    // A declaration cannot turn a failed run or missing references into absence.
    let execution_blockers: Vec<String> = records
        .iter()
        .filter_map(|r| inventory_blocker(r).map(|b| format!("{}: {b}", r.record_id)))
        .collect();
    let declared_complete = records.iter().all(|r| {
        r.aggregation_metadata
            .as_ref()
            .is_some_and(|m| m.candidate_inventory.complete)
    });
    let candidate_inventory_complete = declared_complete && execution_blockers.is_empty();
    let declarations: Vec<_> = campaigns
        .iter()
        .filter(|c| campaign_matches(c, first))
        .collect();
    let campaign_inventory_complete = !has_conflict
        && records.iter().all(|r| identity_known(r))
        && declarations.len() == 1
        && declarations[0].coverage.complete
        && declarations[0].record_ids.iter().collect::<BTreeSet<_>>()
            == record_ids.iter().collect();
    let historical_review_incomplete = records.iter().any(|r| {
        r.preserved_review_reports.iter().any(|p| {
            p.report.status != crate::candidate_review::schema::ReportStatus::Complete
                || p.report.failure.is_some()
                || !p.report.candidate_errors.is_empty()
                || !p.report.unreviewed_candidates.is_empty()
        })
    });
    let review_inventory_complete =
        !historical_review_incomplete && records.iter().all(|r| inventory(r, layer));
    let mut reasons = Vec::new();
    if !declared_complete {
        reasons.push(
            "candidate inventory lacks complete scoped evidence; empty does not establish absence"
                .into(),
        );
    }
    reasons.extend(execution_blockers);
    if !campaign_inventory_complete {
        reasons.push("campaign inventory absent, conflicting, unknown, or does not match all expected records".into());
    }
    if !review_inventory_complete {
        reasons.push(
            "expected review inventory missing or differs from actual observation IDs".into(),
        );
    }
    if has_conflict {
        reasons.push(
            "identity/policy conflict prevents completeness; no favorable record selected".into(),
        );
    }
    if historical_review_incomplete {
        reasons.push("preserved report has incomplete/failed review, candidate errors or unreviewed entries; a new inventory declaration cannot erase that history".into());
    }
    let mut occurrences = Vec::new();
    let mut rejections = Vec::new();
    let mut causes: BTreeMap<(String, String), RegisteredCause> = BTreeMap::new();
    let mut attribution_count_incomplete = false;
    let mut orphan_reviews = false;
    // Ambiguity includes all matched claims on the candidate, in every layer and
    // record, not just those eligible for counting in this layer.
    let mut claims: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut scoped_claims: BTreeMap<String, BTreeSet<(String, String)>> = BTreeMap::new();
    for r in records {
        for row in &r.reviews {
            let o = &row.observation;
            if o.attribution.state == AttributionState::Matched {
                let set = claims
                    .entry(o.candidate.sha256.to_ascii_lowercase())
                    .or_default();
                if let Some(id) = known(&o.attribution.proposed_cause_id) {
                    set.insert(id.clone());
                }
                if let CauseDeduplication::DuplicateOf { cause_id } = &o.cause_deduplication {
                    set.insert(cause_id.clone());
                }
                for c in registry.get(&review_ref(r, row)).into_iter().flatten() {
                    scoped_claims
                        .entry(o.candidate.sha256.to_ascii_lowercase())
                        .or_default()
                        .insert((c.scope_id.clone(), c.cause_id.clone()));
                }
            }
        }
    }
    for r in records {
        let hashes: BTreeSet<_> = r
            .execution
            .candidates
            .iter()
            .map(|c| c.sha256.to_ascii_lowercase())
            .collect();
        for row in r.reviews.iter().filter(|x| applies(&x.observation, layer)) {
            if !hashes.contains(&row.observation.candidate.sha256.to_ascii_lowercase())
                || !bound(r, row)
            {
                orphan_reviews = true;
            }
        }
        for hash in hashes {
            let rows: Vec<_> = r
                .reviews
                .iter()
                .filter(|x| {
                    applies(&x.observation, layer)
                        && x.observation.candidate.sha256.eq_ignore_ascii_case(&hash)
                })
                .collect();
            let mut o = Occurrence {
                record_id: r.record_id.clone(),
                candidate_sha256: hash.clone(),
                review_refs: rows.iter().map(|x| review_ref(r, x)).collect(),
                confirmed: false,
                attributed: false,
                unresolved: rows.is_empty(),
                reasons: vec![],
            };
            if rows.is_empty() {
                o.reasons
                    .push("candidate has no review in this layer".into());
            }
            let ambiguous = claims.get(&hash).is_some_and(|x| x.len() > 1)
                || scoped_claims.get(&hash).is_some_and(|x| x.len() > 1);
            let mut saw_rejected = false;
            for row in rows {
                let ob = &row.observation;
                let state = if layer == Layer::EntrypointTcct {
                    ob.entrypoint_tcct.state
                } else {
                    ob.component.state
                };
                let positive = confirmed(r, row, layer);
                let rejected = bound(r, row)
                    && ob.completion == Completion::Complete
                    && state == ReviewState::Rejected
                    && (layer == Layer::LegacyUnspecified || row.legacy_review.is_none())
                    && (layer == Layer::EntrypointTcct || mapped(r, ob));
                o.confirmed |= positive;
                saw_rejected |= rejected;
                if !positive && !rejected {
                    o.unresolved = true;
                    o.reasons.push(format!("{}: missing binding, incomplete/unresolved review, projection/localization failure, or unverified legacy layer",ob.observation_id));
                }
                if positive && layer != Layer::EntrypointTcct {
                    let attributed = basic_attribution(r, row, layer)
                        && valid_duplicate(r, row, layer)
                        && !ambiguous;
                    o.attributed |= attributed;
                    if !attributed {
                        attribution_count_incomplete = true;
                        o.unresolved = true;
                        o.reasons.push("reported confirmation lacks unambiguous supported attribution/type/localization metadata".into());
                        if layer == Layer::ComponentGeneral && tool_specific(r, ob) {
                            o.reasons.push(format!("{}: tool-specific-check is not general TCCT violation evidence; confirmed but not attributed in this layer", ob.observation_id));
                        }
                    }
                    if attributed {
                        let rr = review_ref(r, row);
                        if let Some(registrations) = registry.get(&rr).filter(|v| v.len() == 1) {
                            let c = &registrations[0];
                            if known(&ob.attribution.proposed_cause_id) == Some(&c.cause_id) {
                                causes
                                    .entry((c.scope_id.clone(), c.cause_id.clone()))
                                    .or_insert_with(|| RegisteredCause {
                                        layer,
                                        scope_id: c.scope_id.clone(),
                                        cause_id: c.cause_id.clone(),
                                        members: vec![],
                                        evidence: c.evidence.clone(),
                                    })
                                    .members
                                    .push(rr);
                            } else {
                                attribution_count_incomplete = true;
                                o.reasons.push(
                                    "registry key conflicts with reported cause; no implicit alias"
                                        .into(),
                                );
                            }
                        } else {
                            attribution_count_incomplete = true;
                            o.reasons.push("missing or ambiguous scoped cause registration; no cross-record cause merge".into());
                        }
                    }
                }
            }
            if ambiguous {
                o.attributed = false;
                o.unresolved = true;
                o.reasons.push(
                    "ambiguous multiple cause claims without independent adjudication".into(),
                );
                attribution_count_incomplete = true;
            }
            if saw_rejected && o.confirmed {
                o.unresolved = true;
                o.reasons.push("positive and rejected reported reviews coexist; existence is reported positive but review/cause completeness is not asserted".into());
            }
            occurrences.push(o);
            rejections.push(saw_rejected);
        }
    }
    // Records in one group that annotate the same candidate must agree. No
    // record is preferred: confirmation in one and rejection in another stay
    // unresolved, while the reported positive existence is kept.
    let mut verdicts: BTreeMap<String, (BTreeSet<String>, BTreeSet<String>)> = BTreeMap::new();
    for (o, rejected) in occurrences.iter().zip(&rejections) {
        let v = verdicts.entry(o.candidate_sha256.clone()).or_default();
        if o.confirmed {
            v.0.insert(o.record_id.clone());
        }
        if *rejected {
            v.1.insert(o.record_id.clone());
        }
    }
    for (hash, (positive, negative)) in &verdicts {
        if !positive.iter().any(|p| negative.iter().any(|n| n != p)) {
            continue;
        }
        let join = |ids: &BTreeSet<String>| ids.iter().cloned().collect::<Vec<_>>().join(", ");
        let detail = format!(
            "confirmed in records [{}], rejected in records [{}]",
            join(positive),
            join(negative)
        );
        reasons.push(format!(
            "candidate {hash} is {detail}; no record is preferred and completeness is not asserted"
        ));
        for o in occurrences
            .iter_mut()
            .filter(|o| &o.candidate_sha256 == hash)
        {
            o.unresolved = true;
            o.reasons
                .push(format!("records disagree on this candidate: {detail}"));
        }
    }
    // Scope IDs are separate cause namespaces. Causes counted from more than one
    // scope in one group come from overlapping scopes, so their distinctness is
    // not established.
    let scopes: BTreeSet<_> = causes.keys().map(|(scope, _)| scope.as_str()).collect();
    if scopes.len() > 1 {
        attribution_count_incomplete = true;
        reasons.push(format!("ambiguous: counted causes come from overlapping registry scopes ({}); the registered list is not a distinct total", scopes.into_iter().collect::<Vec<_>>().join(", ")));
    }
    if orphan_reviews {
        reasons.push("unbound or orphan review observations retained in input; no negative or complete result inferred".into());
    }
    let confirmation_exists = occurrences.iter().any(|x| x.confirmed);
    let attributed_confirmation_exists = occurrences.iter().any(|x| x.attributed);
    let review_results_complete =
        review_inventory_complete && !orphan_reviews && occurrences.iter().all(|x| !x.unresolved);
    let complete =
        candidate_inventory_complete && campaign_inventory_complete && review_results_complete;
    let cause_count_complete = complete
        && !attribution_count_incomplete
        && layer != Layer::EntrypointTcct
        && layer != Layer::LegacyUnspecified;
    let state = if attributed_confirmation_exists {
        UnitState::ConfirmedAttributed
    } else if confirmation_exists {
        UnitState::ConfirmedUnattributedOnly
    } else if candidate_inventory_complete
        && campaign_inventory_complete
        && review_inventory_complete
        && occurrences.is_empty()
        && !orphan_reviews
    {
        UnitState::NoCandidate
    } else if complete {
        UnitState::NotConfirmedComplete
    } else {
        UnitState::UnknownIncomplete
    };
    let time = time::summarize(
        records,
        &occurrences,
        candidate_inventory_complete && campaign_inventory_complete,
        review_inventory_complete && !orphan_reviews,
        layer != Layer::EntrypointTcct,
    );
    let mut registered_causes: Vec<_> = causes.into_values().collect();
    for c in &mut registered_causes {
        c.members.sort();
        c.members.dedup();
    }
    Ok(AggregateGroup {
        group_id: sha256(format!("{key}:{layer:?}").as_bytes()),
        execution_unit_id: first.context.execution_unit_id.clone(),
        method: first.context.method,
        campaign_id: first.execution.campaign_id.clone(),
        repetition: first.context.repetition.clone(),
        layer,
        record_ids,
        state,
        confirmation_exists,
        attributed_confirmation_exists,
        candidate_inventory_complete,
        campaign_inventory_complete,
        review_inventory_complete,
        review_results_complete,
        cause_count_complete,
        distinct_cause_count: if cause_count_complete {
            Recorded::known(registered_causes.len())
        } else {
            Recorded::unknown("inventory, review, attribution or scoped registration is incomplete; registered subset is not a total")
        },
        registered_causes,
        confirmed_unattributed: occurrences
            .iter()
            .filter(|x| x.confirmed && !x.attributed)
            .map(occurrence_ref)
            .collect(),
        unresolved_occurrences: occurrences
            .iter()
            .filter(|x| x.unresolved)
            .map(occurrence_ref)
            .collect(),
        occurrences,
        time,
        reasons,
    })
}
