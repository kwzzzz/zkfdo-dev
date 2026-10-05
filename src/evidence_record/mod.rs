//! Offline, append-only metadata import. No candidate, compiler, predicate, or
//! backend is opened or executed. Importing a claim is not semantic validation.
pub mod aggregate;
pub mod aggregate_schema;
mod legacy;
pub mod schema;

use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::Write,
    path::Path,
};

use anyhow::{ensure, Context as _, Result};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::{
    candidate_review::schema::{
        AttributionVerdict, BackendReview, CriterionVerdict, Disposition, FileRef, ReportKind,
        ReportStatus, ReviewRecord, ReviewReport,
    },
    experiment::ConfirmationScope,
};
use schema::*;

/// Read hash-pinned metadata and write a new record, refusing any overwrite.
pub fn import_record(request_path: &Path, output_path: &Path) -> Result<EvidenceRecord> {
    let request_path = fs::canonicalize(request_path).context("request unavailable")?;
    let request_bytes = fs::read(&request_path)?;
    let request: ImportRequest =
        serde_json::from_slice(&request_bytes).context("invalid evidence record request")?;
    validate_request(&request)?;
    let base = request_path.parent().context("request has no parent")?;
    let source_bytes = read_pinned(base, request.source.file())?;
    let metadata: Value =
        serde_json::from_slice(&source_bytes).context("invalid source metadata")?;
    let execution = legacy::import(&request.source, &metadata, &request.context)?;
    for candidate in &execution.candidates {
        validate_ref(candidate)?;
    }

    let mut reviews = Vec::new();
    let mut preserved = Vec::new();
    let mut skipped_reports = Vec::new();
    for reference in &request.review_reports {
        // Same run, but the source records no observed target to bind the rows to.
        let mut skipped_rows = false;
        let bytes = read_pinned(base, reference)?;
        let report: ReviewReport =
            serde_json::from_slice(&bytes).context("invalid value-free review report")?;
        ensure!(
            report.schema_version == 1,
            "unsupported review report schema"
        );
        ensure!(
            report.kind == ReportKind::BackendCandidates,
            "not a backend review report"
        );
        ensure!(
            !report.raw_values_persisted,
            "review report must be value-free"
        );
        for row in &report.reviews {
            let ReviewRecord::Backend(row) = row else {
                anyhow::bail!("injection review in backend report");
            };
            ensure!(
                !(same_known(&execution.run_id, &row.binding.run_id)
                    && matches!(&execution.target_id, Recorded::Known { value } if value != &row.binding.target_id)),
                "legacy review has the same run ID but a conflicting target ID"
            );
            // Keep other executions in the preserved report, not this attempt's links.
            if !same_known(&execution.run_id, &row.binding.run_id)
                || !same_known(&execution.target_id, &row.binding.target_id)
            {
                skipped_rows |= same_known(&execution.run_id, &row.binding.run_id);
                continue;
            }
            let observation = from_legacy(row, reference);
            validate_observation(&observation)?;
            let binding = metadata_binding(&execution, &observation);
            let binding = if row.binding.candidate_hash_verified
                && row.binding.candidate_metadata_verified
            {
                binding
            } else {
                Recorded::unknown("legacy review did not verify candidate hash/metadata binding")
            };
            reviews.push(ImportedReview {
                source_report: Recorded::known(reference.clone()),
                metadata_binding: binding,
                observation,
                legacy_review: Some((**row).clone()),
            });
        }
        for row in &report.unreviewed_candidates {
            ensure!(
                !(same_known(&execution.run_id, &row.run_id)
                    && matches!(&execution.target_id, Recorded::Known { value } if value != &row.target_id)),
                "unreviewed candidate has the same run ID but a conflicting target ID"
            );
            if !same_known(&execution.run_id, &row.run_id)
                || !same_known(&execution.target_id, &row.target_id)
            {
                skipped_rows |= same_known(&execution.run_id, &row.run_id);
                continue;
            }
            let observation = ReviewObservation {
                observation_id: format!(
                    "{}/unreviewed/{}",
                    reference.sha256, row.candidate_record_id
                ),
                run_id: row.run_id.clone(),
                target_id: row.target_id.clone(),
                candidate: row.candidate.clone(),
                candidate_record_id: Recorded::known(row.candidate_record_id.clone()),
                component_layer: ComponentLayer::LegacyUnspecified,
                localization: Localization::NotAttempted {
                    reason: "not in legacy report".into(),
                },
                cause_deduplication: CauseDeduplication::Unresolved {
                    reason: "not assessed".into(),
                },
                component: not_attempted(&row.reason_code),
                entrypoint_tcct: not_attempted(
                    "legacy report contains no entrypoint TCCT assessment",
                ),
                projection: not_attempted("legacy report contains no projection assessment"),
                attribution: unknown_attribution(&row.reason_code),
                completion: match report.status {
                    ReportStatus::Complete => Completion::Incomplete,
                    ReportStatus::Incomplete => Completion::Interrupted,
                    ReportStatus::Failed => Completion::Failed,
                },
                completion_reason: row.reason_code.clone(),
                automated_review_seconds: Recorded::unknown("candidate was not reviewed"),
                human_review_seconds: Recorded::unknown("not recorded"),
                duplicate_of: Recorded::unknown("not assessed"),
            };
            validate_observation(&observation)?;
            reviews.push(ImportedReview {
                source_report: Recorded::known(reference.clone()),
                metadata_binding: metadata_binding(&execution, &observation),
                observation,
                legacy_review: None,
            });
        }
        if skipped_rows {
            skipped_reports.push(reference.sha256.to_ascii_lowercase());
        }
        preserved.push(PreservedReport {
            file: reference.clone(),
            report,
        });
    }
    for observation in &request.review_observations {
        let mut observation = observation.clone();
        if observation.attribution.state == AttributionState::Matched
            && !matches!(&observation.attribution.method, Recorded::Known { value } if attribution_method_supported(value))
        {
            observation.attribution.state = AttributionState::Unknown;
            observation.attribution.reason = format!(
                "binding-only or unregistered method is not accepted cause attribution: {}",
                observation.attribution.reason
            );
        }
        reviews.push(ImportedReview {
            source_report: Recorded::unknown(
                "explicit request observation; not produced by legacy engine",
            ),
            metadata_binding: metadata_binding(&execution, &observation),
            observation,
            legacy_review: None,
        });
    }

    let mut ids = std::collections::BTreeSet::new();
    for row in &reviews {
        ensure!(
            ids.insert(&row.observation.observation_id),
            "duplicate observation ID"
        );
    }
    // General cause links need a general TCCT violation kind. A tool-specific
    // check keeps its reported claim but is not linked as a general cause.
    let tool_specific: BTreeSet<String> = request
        .aggregation_metadata
        .iter()
        .flat_map(|m| &m.review_semantics)
        .filter(|s| {
            matches!(
                s.violation_kind,
                Recorded::Known {
                    value: aggregate_schema::ViolationKind::ToolSpecificCheck
                }
            )
        })
        .map(|s| s.observation_id.clone())
        .collect();
    let method = request.context.method;
    let invalid_duplicates = invalid_duplicate_links(&reviews, method, &tool_specific);
    let mut component_cause_links: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut candidate_causes: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut aggregation_issues = invalid_duplicates.clone();
    for report in skipped_reports {
        aggregation_issues.insert(
            format!("legacy-review-rows-not-imported:{report}"),
            "rows for this run were not imported: the source records no observed target ID to bind them; the report is preserved, not linked".into(),
        );
    }
    for row in &reviews {
        let observation = &row.observation;
        if observation.component_layer == ComponentLayer::General
            && observation.attribution.state == AttributionState::Matched
            && tool_specific.contains(&observation.observation_id)
        {
            let issue = aggregation_issues
                .entry(observation.observation_id.clone())
                .or_default();
            if !issue.is_empty() {
                issue.push_str("; ");
            }
            issue.push_str("tool-specific-check is not general TCCT violation evidence; the reported claim is kept but not linked as a general cause");
        }
        // Conflicting reported attributions remain ambiguous even if one row
        // has unresolved deduplication, failed localization or missing binding,
        // and across component layers: no per-layer cause rule has been decided.
        if observation.attribution.state == AttributionState::Matched {
            let causes = candidate_causes
                .entry(observation.candidate.sha256.to_ascii_lowercase())
                .or_default();
            if let Recorded::Known { value } = &observation.attribution.proposed_cause_id {
                causes.insert(value.clone());
            }
            if let CauseDeduplication::DuplicateOf { cause_id } = &observation.cause_deduplication {
                causes.insert(cause_id.clone());
            }
        }
    }
    for (candidate, causes) in &candidate_causes {
        if causes.len() > 1 {
            aggregation_issues.insert(candidate.clone(),
                "ambiguous: one candidate is linked to multiple causes; per-cause localization evidence has not been adjudicated".into());
        }
    }
    for row in &reviews {
        let observation = &row.observation;
        if eligible(row, method, &tool_specific)
            && !invalid_duplicates.contains_key(&observation.observation_id)
            && !aggregation_issues.contains_key(&observation.candidate.sha256.to_ascii_lowercase())
        {
            if let Some(value) = canonical_cause(observation) {
                component_cause_links
                    .entry(value)
                    .or_default()
                    .push(observation.observation_id.clone());
            }
        }
    }
    let record = EvidenceRecord {
        schema_version: request.schema_version,
        record_id: request.record_id,
        request: FileRef { path: request_path, sha256: sha256(&request_bytes) },
        source: request.source,
        context: request.context,
        policy_intent: request.policy_intent,
        policy_rules: vec![
            "A: one common unit allocation; do not duplicate its budget per fragment or label".into(),
            "A: attempts and leftover handling must not depend on candidate kind or later review".into(),
            "A: stop at the common unit allocation or a preregistered attempt cap; limit each attempt by the remaining allocation".into(),
            "A: seed order, attempt limits, restart overhead and environmental retries require N5 rules".into(),
            "A is design intent, not evidence that the imported historical execution implemented it".into(),
        ],
        policy_execution_verified: Recorded::unknown("offline import does not execute or verify policy A"),
        execution,
        reviews,
        preserved_review_reports: preserved,
        component_cause_links,
        aggregation_issues,
        aggregation_metadata: request.aggregation_metadata,
        limitations: vec![
            "Structural metadata linkage only; no semantic review, projection, attribution or wrapper equivalence was performed by this importer".into(),
            "Reported component claims, entrypoint TCCT claims and incomplete review remain separate; no negative outcome is inferred from missing review".into(),
            "Legacy component claims are not promoted to the general TCCT layer. Binding-only or unspecified attribution is not a confirmed cause".into(),
            "Cause links are within this record, not a benchmark total; cross-unit/family deduplication requires a frozen rule".into(),
            "Candidate/evidence references are retained, not opened or rehashed; source metadata and review report hashes alone are checked".into(),
            "Reference paths retain their original bases: request-relative for import inputs/annotations, source-report-relative for preserved nested evidence".into(),
            "Exact candidate generation and earliest confirmed time are not reconstructed from log arrival or run completion upper bounds".into(),
        ],
    };
    aggregate::validate_aggregation_metadata(&record)?;
    if let (Some(meta), Some(missing)) = (
        &record.aggregation_metadata,
        aggregate::missing_candidate_refs(&record),
    ) {
        ensure!(
            !meta.candidate_inventory.complete,
            "complete candidate inventory conflicts with source metadata: {missing}"
        );
    }
    let mut encoded = serde_json::to_vec_pretty(&record)?;
    encoded.push(b'\n');
    // Serialize before opening and use create_new even for an identical re-import.
    let mut output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output_path)
        .context("output must be a new file in an existing directory")?;
    if let Err(error) = output.write_all(&encoded) {
        drop(output);
        let _ = fs::remove_file(output_path);
        return Err(error.into());
    }
    Ok(record)
}

pub(super) fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub(super) fn validate_ref(reference: &FileRef) -> Result<()> {
    ensure!(
        !reference.path.as_os_str().is_empty(),
        "empty evidence path"
    );
    ensure!(
        reference.sha256.len() == 64 && reference.sha256.bytes().all(|b| b.is_ascii_hexdigit()),
        "evidence reference requires a SHA-256"
    );
    Ok(())
}

pub(super) fn read_pinned(base: &Path, reference: &FileRef) -> Result<Vec<u8>> {
    validate_ref(reference)?;
    let bytes = fs::read(base.join(&reference.path))
        .with_context(|| format!("metadata unavailable: {}", reference.path.display()))?;
    ensure!(
        sha256(&bytes).eq_ignore_ascii_case(&reference.sha256),
        "metadata SHA-256 mismatch"
    );
    Ok(bytes)
}

fn validate_request(request: &ImportRequest) -> Result<()> {
    ensure!(
        matches!(request.schema_version, 1 | 2),
        "unsupported record request schema"
    );
    ensure!(
        (request.schema_version == 2) == request.aggregation_metadata.is_some(),
        "schema 1 has no aggregation_metadata; schema 2 requires aggregation_metadata"
    );
    ensure!(!request.record_id.trim().is_empty(), "empty record ID");
    ensure!(
        !request.context.execution_unit_id.trim().is_empty(),
        "empty execution unit ID"
    );
    validate_recorded(&serde_json::to_value(request)?)?;
    if let Recorded::Known { value } = &request.context.settings_sha256 {
        ensure!(
            value.len() == 64 && value.bytes().all(|b| b.is_ascii_hexdigit()),
            "settings identity must be a SHA-256 or unknown"
        );
    }
    for observation in &request.review_observations {
        validate_observation(observation)?;
    }
    let mut reports = std::collections::BTreeSet::new();
    for report in &request.review_reports {
        validate_ref(report)?;
        ensure!(
            reports.insert(report.sha256.to_ascii_lowercase()),
            "duplicate review report SHA-256"
        );
    }
    Ok(())
}

pub(super) fn validate_recorded(value: &Value) -> Result<()> {
    match value {
        Value::Object(object) => {
            if object.get("state").and_then(Value::as_str) == Some("unknown") {
                ensure!(
                    object
                        .get("reason")
                        .and_then(Value::as_str)
                        .is_some_and(|r| !r.trim().is_empty()),
                    "unknown requires a reason"
                );
            }
            if object.get("state").and_then(Value::as_str) == Some("known") {
                let v = &object["value"];
                ensure!(!v.is_null(), "known cannot be null");
                if let Some(number) = v.as_f64() {
                    ensure!(
                        number.is_finite() && number >= 0.0,
                        "invalid negative/nonfinite measurement"
                    );
                }
                if let Some(s) = v.as_str() {
                    ensure!(!s.trim().is_empty(), "known identity cannot be empty");
                }
            }
            for item in object.values() {
                validate_recorded(item)?;
            }
        }
        Value::Array(items) => {
            for item in items {
                validate_recorded(item)?;
            }
        }
        _ => {}
    }
    Ok(())
}

pub(super) fn validate_observation(observation: &ReviewObservation) -> Result<()> {
    ensure!(
        !observation.observation_id.trim().is_empty(),
        "empty observation ID"
    );
    ensure!(
        !observation.run_id.trim().is_empty() && !observation.target_id.trim().is_empty(),
        "review requires run and target link IDs"
    );
    validate_ref(&observation.candidate)?;
    ensure!(
        !observation.completion_reason.trim().is_empty(),
        "review completion requires a reason"
    );
    validate_recorded(&serde_json::to_value(observation)?)?;
    for assessment in [
        &observation.component,
        &observation.entrypoint_tcct,
        &observation.projection,
    ] {
        ensure!(
            !assessment.reason.trim().is_empty(),
            "assessment requires a reason"
        );
        if assessment.state == ReviewState::ReportedConfirmed {
            ensure!(
                !assessment.evidence.is_empty(),
                "reported confirmation requires evidence references"
            );
        }
        for reference in &assessment.evidence {
            validate_ref(reference)?;
        }
    }
    ensure!(
        !observation.attribution.reason.trim().is_empty(),
        "attribution requires a reason"
    );
    if observation.attribution.state == AttributionState::Matched {
        ensure!(
            matches!(
                observation.attribution.proposed_cause_id,
                Recorded::Known { .. }
            ) && !observation.attribution.evidence.is_empty(),
            "matched attribution requires cause ID and evidence"
        );
    }
    for reference in &observation.attribution.evidence {
        validate_ref(reference)?;
    }
    match &observation.localization {
        Localization::Localized {
            instance_key,
            evidence,
        } => {
            ensure!(
                !instance_key.trim().is_empty() && !evidence.is_empty(),
                "localized claim needs instance and evidence"
            );
            for reference in evidence {
                validate_ref(reference)?;
            }
        }
        Localization::Root { evidence } => {
            ensure!(!evidence.is_empty(), "root localization needs evidence");
            for reference in evidence {
                validate_ref(reference)?;
            }
        }
        Localization::Multi {
            instance_keys,
            reason,
        } => {
            ensure!(
                instance_keys.len() > 1
                    && instance_keys.iter().all(|s| !s.trim().is_empty())
                    && !reason.trim().is_empty(),
                "multi localization needs instances and reason"
            );
        }
        Localization::Failed { reason } | Localization::NotAttempted { reason } => {
            ensure!(!reason.trim().is_empty(), "localization requires reason");
        }
    }
    match &observation.cause_deduplication {
        CauseDeduplication::DuplicateOf { cause_id } => {
            ensure!(!cause_id.trim().is_empty(), "duplicate cause requires ID")
        }
        CauseDeduplication::Unresolved { reason } => ensure!(
            !reason.trim().is_empty(),
            "unresolved duplicate requires reason"
        ),
        CauseDeduplication::Canonical => {}
    }
    Ok(())
}

fn same_known(value: &Recorded<String>, expected: &str) -> bool {
    matches!(value, Recorded::Known { value } if value == expected)
}

pub(super) fn binding_only(method: &str) -> bool {
    let normalized: String = method
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .flat_map(char::to_lowercase)
        .collect();
    normalized.contains("binding") || normalized == "knowndefectsingletarget"
}

/// A method identifier reports the claimed procedure, not its validity. New
/// identifiers require an explicit schema/code change rather than a blacklist.
pub(super) fn attribution_method_supported(method: &str) -> bool {
    !binding_only(method) && matches!(method, "manual-cause-review" | "fixed-constraint-rejection")
}

fn eligible(row: &ImportedReview, method: Method, excluded: &BTreeSet<String>) -> bool {
    let observation = &row.observation;
    !excluded.contains(&observation.observation_id)
        && matches!(row.metadata_binding, Recorded::Known { value: true })
        && observation.component_layer == ComponentLayer::General
        && observation.component.state == ReviewState::ReportedConfirmed
        && observation.projection.state == ReviewState::ReportedConfirmed
        && observation.attribution.state == AttributionState::Matched
        && matches!(&observation.attribution.method, Recorded::Known { value } if attribution_method_supported(value))
        && observation.completion == Completion::Complete
        && matches!(
            observation.localization,
            Localization::Localized { .. } | Localization::Root { .. }
        )
        && !(method == Method::Split
            && matches!(observation.localization, Localization::Root { .. }))
        && row
            .legacy_review
            .as_ref()
            .is_none_or(|r| r.confirmation_eligible)
}

/// Preserve malformed/unsupported duplicate claims without choosing a cause.
/// This is only a within-record linkage check, not a cause registry or a
/// semantic adjudication of whether two observations share a cause.
fn invalid_duplicate_links(
    reviews: &[ImportedReview],
    method: Method,
    excluded: &BTreeSet<String>,
) -> BTreeMap<String, String> {
    let by_id: BTreeMap<_, _> = reviews
        .iter()
        .map(|row| (row.observation.observation_id.as_str(), row))
        .collect();
    let canonical_ids: std::collections::BTreeSet<_> = reviews
        .iter()
        .filter(|row| eligible(row, method, excluded))
        .filter(|row| {
            matches!(
                row.observation.cause_deduplication,
                CauseDeduplication::Canonical
            )
        })
        .filter_map(|row| canonical_cause(&row.observation))
        .collect();
    let mut issues = BTreeMap::new();
    for row in reviews {
        let observation = &row.observation;
        let mut reasons = Vec::new();
        if method == Method::Split && matches!(observation.localization, Localization::Root { .. })
        {
            reasons.push("root denotes the entrypoint main; a split fragment root requires an explicit localized instance link");
        }
        if let CauseDeduplication::DuplicateOf { cause_id } = &observation.cause_deduplication {
            if !canonical_ids.contains(cause_id) {
                reasons.push("duplicate cause lacks an eligible canonical observation in this record; orphan or alias chain is not resolved");
            }
            if !matches!(&observation.attribution.proposed_cause_id, Recorded::Known { value } if value == cause_id)
            {
                reasons.push("duplicate target differs from the proposed cause; no explicit alias registration was supplied");
            }
        }
        let mut seen = std::collections::BTreeSet::from([observation.observation_id.as_str()]);
        let mut current = observation;
        while let Recorded::Known { value } = &current.duplicate_of {
            if !seen.insert(value.as_str()) {
                reasons.push("duplicate observation links contain a cycle");
                break;
            }
            let Some(target) = by_id.get(value.as_str()) else {
                reasons.push("duplicate observation target is absent from this record");
                break;
            };
            if eligible(row, method, excluded)
                && (!eligible(target, method, excluded)
                    || canonical_cause(observation) != canonical_cause(&target.observation))
            {
                reasons
                    .push("duplicate observation target does not support the same eligible cause");
                break;
            }
            current = &target.observation;
        }
        if !reasons.is_empty() {
            issues.insert(
                observation.observation_id.clone(),
                format!("ambiguous: {}", reasons.join("; ")),
            );
        }
    }
    issues
}

fn canonical_cause(observation: &ReviewObservation) -> Option<String> {
    match &observation.cause_deduplication {
        CauseDeduplication::Canonical => match &observation.attribution.proposed_cause_id {
            Recorded::Known { value } => Some(value.clone()),
            Recorded::Unknown { .. } => None,
        },
        CauseDeduplication::DuplicateOf { cause_id } => Some(cause_id.clone()),
        CauseDeduplication::Unresolved { .. } => None,
    }
}

pub(super) fn metadata_binding(
    execution: &ExecutionObservation,
    review: &ReviewObservation,
) -> Recorded<bool> {
    if !same_known(&execution.run_id, &review.run_id)
        || !same_known(&execution.target_id, &review.target_id)
    {
        return Recorded::unknown("source run/target identity missing or does not match review");
    }
    if !execution
        .candidates
        .iter()
        .any(|c| c.sha256.eq_ignore_ascii_case(&review.candidate.sha256))
    {
        return Recorded::unknown(
            "candidate hash not linked by source metadata; candidate content was not read",
        );
    }
    Recorded::known(true)
}

fn not_attempted(reason: &str) -> Assessment {
    Assessment {
        state: ReviewState::NotAttempted,
        reason: reason.into(),
        evidence: vec![],
    }
}

fn unknown_attribution(reason: &str) -> Attribution {
    Attribution {
        state: AttributionState::Unknown,
        method: Recorded::unknown(reason),
        proposed_cause_id: Recorded::unknown(reason),
        reason: reason.into(),
        evidence: vec![],
    }
}

fn from_legacy(row: &BackendReview, report: &FileRef) -> ReviewObservation {
    let criteria = [
        ("assignment-encoding", &row.criteria.assignment_encoding),
        ("input-preconditions", &row.criteria.input_preconditions),
        (
            "fixed-target-constraints",
            &row.criteria.fixed_target_constraints,
        ),
        (
            "specified-property-violation",
            &row.criteria.specified_property_violation,
        ),
    ];
    let complete_criteria = criteria.iter().all(|(_, criterion)| {
        criterion
            .as_ref()
            .is_some_and(|c| c.verdict == CriterionVerdict::Satisfied)
    });
    let scope = match row.expected_scope {
        ConfirmationScope::OriginalComponent => "original-component",
        ConfirmationScope::Project => "project",
        ConfirmationScope::WrapperOnly => "wrapper-only",
        ConfirmationScope::ReachabilityUnknown => "reachability-unknown",
    };
    let unresolved_criteria: Vec<_> = criteria
        .iter()
        .filter_map(|(name, criterion)| match criterion {
            Some(c) if c.verdict == CriterionVerdict::Satisfied => None,
            Some(c) => Some(format!("{name}={:?} ({})", c.verdict, c.reason_code)),
            None => Some(format!("{name}=not-recorded")),
        })
        .collect();
    let component = Assessment {
        state: match row.disposition {
            Disposition::Validated
                if complete_criteria
                    && row.artifact_verification.r1cs_sha256_verified
                    && row.artifact_verification.sym_sha256_verified
                    && row.artifact_verification.assignment_complete
                    && row.failed_target_constraint_count == 0 => ReviewState::ReportedConfirmed,
            Disposition::Rejected => ReviewState::Rejected,
            Disposition::ReviewError => ReviewState::Error,
            _ => ReviewState::Unresolved,
        },
        reason: format!(
            "imported legacy criteria; scope={scope}; disposition={:?}; non-satisfied criteria=[{}]; legacy violation_class={:?}; no general/entrypoint promotion or revalidation",
            row.disposition, unresolved_criteria.join("; "), row.violation_class
        ),
        evidence: vec![report.clone()],
    };
    ReviewObservation {
        observation_id: format!(
            "{}/{}/{}",
            report.sha256, row.candidate_record_id, row.review_spec.id
        ),
        run_id: row.binding.run_id.clone(),
        target_id: row.binding.target_id.clone(),
        candidate: row.candidate.clone(),
        candidate_record_id: Recorded::known(row.candidate_record_id.clone()),
        component_layer: ComponentLayer::LegacyUnspecified,
        localization: Localization::NotAttempted {
            reason: "legacy target binding does not establish cause localization".into(),
        },
        cause_deduplication: CauseDeduplication::Unresolved {
            reason: "legacy root_cause_id does not establish canonical deduplication".into(),
        },
        component,
        entrypoint_tcct: not_attempted(
            "legacy scope cannot establish an entrypoint TCCT assessment",
        ),
        projection: not_attempted("legacy report does not establish whole-to-component projection"),
        attribution: Attribution {
            state: match row.cause_attribution.verdict {
                AttributionVerdict::Matched => AttributionState::Unknown,
                AttributionVerdict::NotMatched => AttributionState::NotMatched,
                AttributionVerdict::Unknown => AttributionState::Unknown,
            },
            proposed_cause_id: Recorded::known(row.root_cause_id.clone()),
            method: Recorded::unknown(
                "legacy report does not distinguish cause evidence from target binding",
            ),
            reason: format!(
                "{}; legacy Matched is not promoted to cause attribution",
                row.cause_attribution.reason_code
            ),
            evidence: row.cause_attribution.evidence.clone(),
        },
        completion: if row.disposition == Disposition::ReviewError {
            Completion::Failed
        } else {
            Completion::Complete
        },
        completion_reason:
            "legacy terminal review row; see preserved report for inventory completeness".into(),
        automated_review_seconds: Recorded::known(row.automated_review_seconds),
        human_review_seconds: Recorded::unknown("legacy report does not record human review time"),
        duplicate_of: Recorded::unknown(
            "no duplicate verdict imported; shared cause links retain all rows",
        ),
    }
}
