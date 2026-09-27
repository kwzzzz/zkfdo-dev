use std::{
    fs,
    path::{Path, PathBuf},
};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tempfile::TempDir;
use zkfdo::candidate_review::{
    review,
    schema::{BackendBundleIndex, Disposition, ReportStatus, ReviewRecord, ReviewReport},
    ReviewOptions,
};

const REGRESSION: &str = "reports/candidate-review-regression-2026-09-27";
const PLAN: &str = "reports/controlled-v3-preflight-2026-09-23/evidence/plan.json";
const OUTCOME: &str = "reports/controlled-v3-pilot-2026-09-23/evidence/outcome.json";

fn repository() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn bytes(path: impl AsRef<Path>) -> Vec<u8> {
    fs::read(path).unwrap()
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn little_u32(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}

fn little_u64(bytes: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap())
}

fn alter_first_r1cs_coefficient(bytes: &mut [u8]) {
    assert_eq!(&bytes[..4], b"r1cs");
    let section_count = little_u32(bytes, 8) as usize;
    let mut cursor = 12;
    let mut header = None;
    let mut constraints = None;
    for _ in 0..section_count {
        let kind = little_u32(bytes, cursor);
        let length = little_u64(bytes, cursor + 4) as usize;
        let start = cursor + 12;
        match kind {
            1 => header = Some((start, length)),
            2 => constraints = Some((start, length)),
            _ => {}
        }
        cursor = start + length;
    }
    let (header_start, _) = header.unwrap();
    let field_bytes = little_u32(bytes, header_start) as usize;
    let constraint_count = little_u32(bytes, header_start + 28 + field_bytes) as usize;
    let (mut cursor, constraint_length) = constraints.unwrap();
    let constraint_end = cursor + constraint_length;
    for _ in 0..constraint_count {
        for _ in 0..3 {
            let term_count = little_u32(bytes, cursor) as usize;
            cursor += 4;
            if term_count > 0 {
                cursor += 4;
                assert!(cursor + field_bytes <= constraint_end);
                let replacement = if bytes[cursor] == 2
                    && bytes[cursor + 1..cursor + field_bytes]
                        .iter()
                        .all(|byte| *byte == 0)
                {
                    3
                } else {
                    2
                };
                bytes[cursor..cursor + field_bytes].fill(0);
                bytes[cursor] = replacement;
                return;
            }
        }
    }
    panic!("R1CS fixture contains no coefficient to alter");
}

fn write_json(path: &Path, value: &Value) {
    fs::write(path, serde_json::to_vec_pretty(value).unwrap()).unwrap();
}

fn candidate_adapter_sha256() -> String {
    let mut hasher = Sha256::new();
    hasher.update(include_bytes!("../src/candidate_review/engine.rs"));
    hasher.update(b"\0");
    hasher.update(b"zkfDO candidate adapter zkfuzz-counterexample-v1 schema 1\n");
    format!("{:x}", hasher.finalize())
}

fn engine_source_manifest(temporary: &TempDir) -> PathBuf {
    let sources: [(&str, &[u8]); 8] = [
        (
            "engine.rs",
            include_bytes!("../src/candidate_review/engine.rs"),
        ),
        ("experiment.rs", include_bytes!("../src/experiment.rs")),
        (
            "predicate.rs",
            include_bytes!("../src/candidate_review/predicate.rs"),
        ),
        ("r1cs.rs", include_bytes!("../src/candidate_review/r1cs.rs")),
        (
            "schema.rs",
            include_bytes!("../src/candidate_review/schema.rs"),
        ),
        ("structure.rs", include_bytes!("../src/structure.rs")),
        (
            "subprocess.rs",
            include_bytes!("../src/candidate_review/subprocess.rs"),
        ),
        ("targets.rs", include_bytes!("../src/targets.rs")),
    ];
    for (name, source) in sources {
        fs::write(temporary.path().join(name), source).unwrap();
    }
    let manifest = temporary.path().join("engine-source-manifest.json");
    write_json(
        &manifest,
        &json!({
            "schema_version": 1,
            "files": sources.into_iter().map(|(name, source)| json!({
                "path": name,
                "size": source.len(),
                "sha256": sha256(source)
            })).collect::<Vec<_>>()
        }),
    );
    manifest
}

fn absolute_spec_copy(temporary: &TempDir) -> PathBuf {
    let original = repository().join(format!("{REGRESSION}/inputs/v3-spec.json"));
    let original_parent = original.parent().unwrap();
    let mut spec: Value = serde_json::from_slice(&bytes(&original)).unwrap();
    spec["review_spec_id"] = Value::String("regression/v3/decoder/second-spec".to_owned());
    for pointer in [
        "/target_binding/source_path",
        "/target_binding/source_closure_manifest_path",
        "/compiled_subject/r1cs_path",
        "/compiled_subject/sym_path",
        "/compiler/library_manifest_path",
        "/contract/definition_path",
        "/contract/predicate/path",
        "/attribution/evidence_path",
    ] {
        let relative = spec.pointer(pointer).unwrap().as_str().unwrap();
        let absolute = original_parent.join(relative).canonicalize().unwrap();
        *spec.pointer_mut(pointer).unwrap() = Value::String(absolute.to_string_lossy().into());
    }
    let path = temporary.path().join("second-spec.json");
    write_json(&path, &spec);
    path
}

fn run_case(
    temporary: &TempDir,
    outcome: &Value,
    specs: &[PathBuf],
    mutate_request: impl FnOnce(&mut Value),
) -> zkfdo::candidate_review::ReviewOutput {
    let plan = temporary.path().join("plan.json");
    fs::copy(repository().join(PLAN), &plan).unwrap();
    let outcome_path = temporary.path().join("outcome.json");
    write_json(&outcome_path, outcome);
    let request_path = temporary.path().join("request.json");
    let mut request = json!({
        "schema_version": 1,
        "request_id": "backend-failure-matrix",
        "kind": "backend-candidates",
        "review_specs": specs.iter().map(|path| json!({
            "path": path,
            "sha256": sha256(&bytes(path))
        })).collect::<Vec<_>>(),
        "executions": [{
            "execution_id": "synthetic-v3",
            "campaign_coordinates": null,
            "plan": {"path": plan, "sha256": sha256(&bytes(&plan))},
            "outcome": {"path": outcome_path, "sha256": sha256(&bytes(&outcome_path))}
        }],
        "candidate_adapter": {
            "id": "zkfuzz-counterexample-v1",
            "implementation_sha256": candidate_adapter_sha256()
        },
        "candidate_policy": "all-outcome-candidates",
        "unmatched_candidate_policy": "record-unreviewed",
        "qualification_bundles": []
    });
    mutate_request(&mut request);
    write_json(&request_path, &request);
    review(&ReviewOptions {
        request: request_path,
        output: temporary.path().join("output"),
        python_bin: "python3".into(),
        source_revision: "synthetic-backend-test".to_owned(),
        engine_source_manifest: engine_source_manifest(temporary),
        executable: std::env::current_exe().unwrap(),
    })
    .unwrap()
}

fn original_outcome() -> Value {
    serde_json::from_slice(&bytes(repository().join(OUTCOME))).unwrap()
}

fn original_spec() -> PathBuf {
    repository().join(format!("{REGRESSION}/inputs/v3-spec.json"))
}

#[test]
fn multiple_candidates_and_specs_keep_all_reviews_but_deduplicate_confirmation() {
    let temporary = tempfile::tempdir().unwrap();
    let mut outcome = original_outcome();
    let original_candidate = outcome["counterexample_candidates"][0].clone();
    let original_path = PathBuf::from(original_candidate["preserved_path"].as_str().unwrap());
    let candidate_bytes = bytes(original_path);
    let mut candidates = Vec::new();
    for index in 0..2 {
        let path = temporary.path().join(format!("candidate-{index}.json"));
        fs::write(&path, &candidate_bytes).unwrap();
        let mut candidate = original_candidate.clone();
        candidate["preserved_path"] = Value::String(path.to_string_lossy().into());
        candidates.push(candidate);
    }
    outcome["counterexample_candidates"] = Value::Array(candidates);
    let second_spec = absolute_spec_copy(&temporary);
    let result = run_case(
        &temporary,
        &outcome,
        &[original_spec(), second_spec],
        |_| {},
    );
    assert_eq!(result.status, ReportStatus::Complete);
    let report: ReviewReport = serde_json::from_slice(&bytes(&result.report_path)).unwrap();
    assert_eq!(report.reviews.len(), 4);
    assert!(report.reviews.iter().all(|review| {
        matches!(review, ReviewRecord::Backend(row) if row.disposition == Disposition::Validated)
    }));
    let inventory = report.candidate_inventory.unwrap();
    assert_eq!(inventory.outcome_candidate_count, 2);
    assert_eq!(inventory.matched_candidate_count, 2);
    assert_eq!(inventory.review_pair_count, 4);

    let index_path = result.bundle_index_path.unwrap();
    let index: BackendBundleIndex = serde_json::from_slice(&bytes(&index_path)).unwrap();
    assert_eq!(index.execution_evaluations.len(), 1);
    assert_eq!(index.campaign_summary.unique_validated_root_cause_count, 1);
    let confirmation_ref = &index.execution_evaluations[0].confirmation;
    let confirmation_path = index_path.parent().unwrap().join(&confirmation_ref.path);
    let confirmation: Value = serde_json::from_slice(&bytes(confirmation_path)).unwrap();
    assert_eq!(confirmation["confirmations"].as_array().unwrap().len(), 1);
}

#[test]
fn unavailable_candidate_is_an_incomplete_inventory_error() {
    let temporary = tempfile::tempdir().unwrap();
    let mut outcome = original_outcome();
    let missing = temporary.path().join("missing.json");
    outcome["counterexample_candidates"][0]["preserved_path"] =
        Value::String(missing.to_string_lossy().into());
    let result = run_case(&temporary, &outcome, &[original_spec()], |_| {});
    assert_eq!(result.status, ReportStatus::Incomplete);
    let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
    assert_eq!(report.candidate_errors.len(), 1);
    assert!(!report.candidate_errors[0].path.is_absolute());
    assert_eq!(
        report.candidate_errors[0]
            .path
            .file_name()
            .and_then(|name| name.to_str()),
        Some("missing.json")
    );
    assert!(report.reviews.is_empty());
    assert!(!report.candidate_inventory.unwrap().complete);
}

#[test]
fn malformed_verified_candidate_is_a_pair_review_error() {
    let temporary = tempfile::tempdir().unwrap();
    let mut outcome = original_outcome();
    let candidate_path = temporary.path().join("malformed-candidate.json");
    fs::write(&candidate_path, b"{}\n").unwrap();
    outcome["counterexample_candidates"][0]["preserved_path"] =
        Value::String(candidate_path.to_string_lossy().into());
    outcome["counterexample_candidates"][0]["sha256"] =
        Value::String(sha256(&bytes(&candidate_path)));
    let result = run_case(&temporary, &outcome, &[original_spec()], |_| {});
    assert_eq!(result.status, ReportStatus::Incomplete);
    let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
    assert!(report.candidate_errors.is_empty());
    assert!(matches!(
        report.reviews.as_slice(),
        [ReviewRecord::Backend(row)] if row.disposition == Disposition::ReviewError
    ));
}

#[test]
fn shared_inventory_or_spec_hash_damage_is_a_failed_report() {
    for damage_spec_hash in [false, true] {
        let temporary = tempfile::tempdir().unwrap();
        let mut outcome = original_outcome();
        if !damage_spec_hash {
            outcome["counterexample_candidates"] = Value::Array(Vec::new());
        }
        let result = run_case(&temporary, &outcome, &[original_spec()], |request| {
            if damage_spec_hash {
                request["review_specs"][0]["sha256"] = Value::String("0".repeat(64));
            }
        });
        assert_eq!(result.status, ReportStatus::Failed);
        let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
        assert!(report.failure.is_some());
        assert!(report.reviews.is_empty());
        assert!(report.executions.is_empty());
    }
}

#[test]
fn duplicated_or_mislabeled_campaign_evidence_is_rejected() {
    let scenarios: [fn(&TempDir, &mut Value); 6] = [
        |temporary, request| {
            let mut duplicate = request["executions"][0].clone();
            duplicate["execution_id"] = Value::String("copied-evidence".to_owned());
            for kind in ["plan", "outcome"] {
                let original = PathBuf::from(duplicate[kind]["path"].as_str().unwrap());
                let copied = temporary.path().join(format!("{kind}-copy.json"));
                fs::copy(original, &copied).unwrap();
                duplicate[kind]["path"] = Value::String(copied.to_string_lossy().into());
            }
            request["executions"]
                .as_array_mut()
                .unwrap()
                .push(duplicate);
        },
        |_temporary, request| {
            request["executions"][0]["campaign_coordinates"] =
                json!({"block": 0, "strategy": "random"});
        },
        |temporary, request| {
            let mut first = request["executions"][0].clone();
            first["campaign_coordinates"] = json!({"block": 0, "strategy": "risk-only"});
            request["executions"][0] = first.clone();
            let mut outcome: Value = serde_json::from_slice(&bytes(PathBuf::from(
                first["outcome"]["path"].as_str().unwrap(),
            )))
            .unwrap();
            outcome["outcome_id"] =
                Value::String("distinct-outcome-for-coordinate-test".to_owned());
            outcome["scheduler"]["experiment_id"] =
                Value::String("distinct-experiment-for-coordinate-test".to_owned());
            let copied = temporary.path().join("coordinate-outcome.json");
            write_json(&copied, &outcome);
            let mut duplicate = first;
            duplicate["execution_id"] = Value::String("duplicate-coordinate".to_owned());
            duplicate["outcome"] = json!({
                "path": copied,
                "sha256": sha256(&bytes(&copied))
            });
            request["executions"]
                .as_array_mut()
                .unwrap()
                .push(duplicate);
        },
        |temporary, request| {
            request["executions"][0]["campaign_coordinates"] =
                json!({"block": 0, "strategy": "risk-only"});
            let first = request["executions"][0].clone();
            let mut outcome: Value = serde_json::from_slice(&bytes(PathBuf::from(
                first["outcome"]["path"].as_str().unwrap(),
            )))
            .unwrap();
            outcome["outcome_id"] = Value::String("distinct-outcome-for-run-test".to_owned());
            outcome["scheduler"]["experiment_id"] =
                Value::String("distinct-experiment-for-run-test".to_owned());
            let copied = temporary.path().join("repeated-run-outcome.json");
            write_json(&copied, &outcome);
            let mut duplicate = first;
            duplicate["execution_id"] = Value::String("repeated-runs".to_owned());
            duplicate["campaign_coordinates"] = json!({"block": 1, "strategy": "risk-only"});
            duplicate["outcome"] = json!({
                "path": copied,
                "sha256": sha256(&bytes(&copied))
            });
            request["executions"]
                .as_array_mut()
                .unwrap()
                .push(duplicate);
        },
        |temporary, request| {
            request["executions"][0]["campaign_coordinates"] =
                json!({"block": 0, "strategy": "risk-only"});
            let first = request["executions"][0].clone();
            let mut outcome: Value = serde_json::from_slice(&bytes(PathBuf::from(
                first["outcome"]["path"].as_str().unwrap(),
            )))
            .unwrap();
            outcome["outcome_id"] = Value::String("distinct-outcome-same-experiment".to_owned());
            let copied = temporary.path().join("repeated-experiment-outcome.json");
            write_json(&copied, &outcome);
            let mut duplicate = first;
            duplicate["execution_id"] = Value::String("repeated-experiment".to_owned());
            duplicate["campaign_coordinates"] = json!({"block": 1, "strategy": "risk-only"});
            duplicate["outcome"] = json!({
                "path": copied,
                "sha256": sha256(&bytes(&copied))
            });
            request["executions"]
                .as_array_mut()
                .unwrap()
                .push(duplicate);
        },
        |_temporary, request| {
            request["executions"][0]["execution_id"] = Value::String(String::new());
        },
    ];

    for mutate in scenarios {
        let temporary = tempfile::tempdir().unwrap();
        let result = run_case(
            &temporary,
            &original_outcome(),
            &[original_spec()],
            |request| mutate(&temporary, request),
        );
        assert_eq!(result.status, ReportStatus::Failed);
        assert!(result.bundle_index_path.is_none());
        let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
        assert!(report.failure.is_some());
        assert!(report.reviews.is_empty());
        assert!(report.executions.is_empty());
    }
}

#[test]
fn project_scope_without_satisfied_reachability_is_rejected() {
    let temporary = tempfile::tempdir().unwrap();
    let spec_path = absolute_spec_copy(&temporary);
    let mut spec: Value = serde_json::from_slice(&bytes(&spec_path)).unwrap();
    spec["expected_scope"] = Value::String("project".to_owned());
    write_json(&spec_path, &spec);

    let result = run_case(&temporary, &original_outcome(), &[spec_path], |_| {});
    assert_eq!(result.status, ReportStatus::Failed);
    assert!(result.bundle_index_path.is_none());
    let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
    assert!(report.failure.is_some());
    assert!(report.reviews.is_empty());
}

#[test]
fn every_backend_spec_must_bind_a_target_in_a_supplied_plan() {
    let temporary = tempfile::tempdir().unwrap();
    let spec_path = absolute_spec_copy(&temporary);
    let mut spec: Value = serde_json::from_slice(&bytes(&spec_path)).unwrap();
    spec["target_binding"]["target_id"] = Value::String("f".repeat(64));
    write_json(&spec_path, &spec);

    let result = run_case(&temporary, &original_outcome(), &[spec_path], |_| {});
    assert_eq!(result.status, ReportStatus::Failed);
    assert!(result.bundle_index_path.is_none());
    let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
    assert!(report.failure.is_some());
    assert!(report.reviews.is_empty());
    assert!(report.executions.is_empty());
}

#[test]
fn qualification_bundle_set_must_exactly_match_injected_backend_specs() {
    let temporary = tempfile::tempdir().unwrap();
    let result = run_case(
        &temporary,
        &original_outcome(),
        &[original_spec()],
        |request| {
            request["qualification_bundles"] = json!([{
                "injection_id": "unrequested-injection",
                "path": "must-not-be-opened.json",
                "sha256": "0".repeat(64)
            }]);
        },
    );
    assert_eq!(result.status, ReportStatus::Failed);
    assert!(result.bundle_index_path.is_none());
    let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
    assert!(report.failure.is_some());
    assert!(report.reviews.is_empty());
    assert!(report.executions.is_empty());
}

#[test]
fn review_spec_source_closure_must_match_the_plan_target() {
    let temporary = tempfile::tempdir().unwrap();
    let spec_path = absolute_spec_copy(&temporary);
    let unrelated_source = temporary.path().join("unrelated.circom");
    fs::write(&unrelated_source, b"template Decoder(w) {}\n").unwrap();
    let closure_path = temporary.path().join("unrelated-closure.json");
    write_json(
        &closure_path,
        &json!({
            "schema_version": 1,
            "files": [{
                "path": "unrelated.circom",
                "size": fs::metadata(&unrelated_source).unwrap().len(),
                "sha256": sha256(&bytes(&unrelated_source))
            }]
        }),
    );
    let mut spec: Value = serde_json::from_slice(&bytes(&spec_path)).unwrap();
    spec["target_binding"]["source_path"] =
        Value::String(unrelated_source.to_string_lossy().into());
    spec["target_binding"]["source_sha256"] = Value::String(sha256(&bytes(&unrelated_source)));
    spec["target_binding"]["source_closure_manifest_path"] =
        Value::String(closure_path.to_string_lossy().into());
    spec["target_binding"]["source_closure_manifest_sha256"] =
        Value::String(sha256(&bytes(&closure_path)));
    write_json(&spec_path, &spec);

    let result = run_case(&temporary, &original_outcome(), &[spec_path], |_| {});
    assert_eq!(result.status, ReportStatus::Failed);
    assert!(result.bundle_index_path.is_none());
    let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
    assert!(report.failure.is_some());
    assert!(report.reviews.is_empty());
}

#[test]
fn review_spec_cannot_bind_another_file_from_the_same_plan_closure() {
    let temporary = tempfile::tempdir().unwrap();
    let spec_path = absolute_spec_copy(&temporary);
    let other_source = repository()
        .join("datasets/controlled-v3/circomlib-decoder/vulnerable/project/circuit.circom")
        .canonicalize()
        .unwrap();
    let mut spec: Value = serde_json::from_slice(&bytes(&spec_path)).unwrap();
    spec["target_binding"]["source_path"] = Value::String(other_source.to_string_lossy().into());
    spec["target_binding"]["source_sha256"] = Value::String(sha256(&bytes(&other_source)));
    write_json(&spec_path, &spec);

    let result = run_case(&temporary, &original_outcome(), &[spec_path], |_| {});
    assert_eq!(result.status, ReportStatus::Failed);
    assert!(result.bundle_index_path.is_none());
    let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
    assert!(report.failure.is_some());
    assert!(report.reviews.is_empty());
}

#[test]
fn review_spec_compilation_must_match_the_frozen_prepared_target() {
    for scenario in ["arguments", "binary", "r1cs"] {
        let temporary = tempfile::tempdir().unwrap();
        let spec_path = absolute_spec_copy(&temporary);
        let mut spec: Value = serde_json::from_slice(&bytes(&spec_path)).unwrap();
        match scenario {
            "arguments" => spec["compiler"]["arguments"] = json!([]),
            "binary" => spec["compiler"]["binary_sha256"] = Value::String("0".repeat(64)),
            "r1cs" => {
                let original =
                    PathBuf::from(spec["compiled_subject"]["r1cs_path"].as_str().unwrap());
                let mut changed = bytes(original);
                alter_first_r1cs_coefficient(&mut changed);
                let changed_path = temporary.path().join("changed-but-valid.r1cs");
                fs::write(&changed_path, &changed).unwrap();
                spec["compiled_subject"]["r1cs_path"] =
                    Value::String(changed_path.to_string_lossy().into_owned());
                spec["compiled_subject"]["r1cs_sha256"] = Value::String(sha256(&changed));
            }
            _ => unreachable!(),
        }
        write_json(&spec_path, &spec);

        let result = run_case(&temporary, &original_outcome(), &[spec_path], |_| {});
        assert_eq!(result.status, ReportStatus::Failed, "{scenario}");
        assert!(result.bundle_index_path.is_none());
        let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
        assert!(report.failure.is_some(), "{scenario}");
        assert!(report.reviews.is_empty(), "{scenario}");
        assert!(report.executions.is_empty(), "{scenario}");
    }
}

#[cfg(unix)]
#[test]
fn review_spec_accepts_the_matching_snapshot_root_and_closure() {
    use std::os::unix::fs::symlink;

    let temporary = tempfile::tempdir().unwrap();
    let spec_path = absolute_spec_copy(&temporary);
    let mut spec: Value = serde_json::from_slice(&bytes(&spec_path)).unwrap();
    let target_id = spec["target_binding"]["target_id"].as_str().unwrap();
    let plan: Value = serde_json::from_slice(&bytes(repository().join(PLAN))).unwrap();
    let target = plan["targets"]
        .as_array()
        .unwrap()
        .iter()
        .find(|target| target["target_id"] == target_id)
        .unwrap();
    let root_hash = spec["target_binding"]["source_sha256"]
        .as_str()
        .unwrap()
        .to_owned();
    let mut manifest_files = Vec::new();
    let mut snapshot_root = None;
    for (index, fingerprint) in target["snapshot_fingerprints"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        let source = PathBuf::from(fingerprint["path"].as_str().unwrap());
        let name = format!("snapshot-{index:04}.circom");
        symlink(&source, temporary.path().join(&name)).unwrap();
        let fingerprint_hash = fingerprint["sha256"].as_str().unwrap();
        manifest_files.push(json!({
            "path": name,
            "size": fs::metadata(&source).unwrap().len(),
            "sha256": fingerprint_hash
        }));
        if fingerprint_hash == root_hash {
            assert!(snapshot_root.replace(source).is_none());
        }
    }
    let closure_path = temporary.path().join("snapshot-closure.json");
    write_json(
        &closure_path,
        &json!({"schema_version": 1, "files": manifest_files}),
    );
    let snapshot_root = snapshot_root.unwrap();
    spec["target_binding"]["source_path"] = Value::String(snapshot_root.to_string_lossy().into());
    spec["target_binding"]["source_closure_manifest_path"] =
        Value::String(closure_path.to_string_lossy().into());
    spec["target_binding"]["source_closure_manifest_sha256"] =
        Value::String(sha256(&bytes(&closure_path)));
    write_json(&spec_path, &spec);

    let result = run_case(&temporary, &original_outcome(), &[spec_path], |_| {});
    assert_eq!(result.status, ReportStatus::Complete);
    let report: ReviewReport = serde_json::from_slice(&bytes(result.report_path)).unwrap();
    assert!(matches!(
        report.reviews.as_slice(),
        [ReviewRecord::Backend(row)] if row.disposition == Disposition::Validated
    ));
}
