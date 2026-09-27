use std::{fs, path::Path, process::Command};

use serde::de::DeserializeOwned;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tempfile::tempdir;
use zkfdo::candidate_review::{
    review,
    schema::{BackendBundleIndex, ReportStatus, ReviewReport, ReviewRequest, ReviewSpec},
    ReviewOptions,
};

const ROOT: &str = "reports/candidate-review-regression-2026-09-27";

fn read(path: impl AsRef<Path>) -> Vec<u8> {
    fs::read(path).unwrap()
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn assert_unknown_field_rejected<T: DeserializeOwned>(path: impl AsRef<Path>) {
    let mut value: Value = serde_json::from_slice(&read(path)).unwrap();
    value
        .as_object_mut()
        .unwrap()
        .insert("unexpected_field".to_owned(), Value::Bool(true));
    assert!(serde_json::from_value::<T>(value).is_err());
}

fn assert_missing_field_rejected<T: DeserializeOwned>(path: impl AsRef<Path>, pointer: &str) {
    let mut value: Value = serde_json::from_slice(&read(path)).unwrap();
    let (parent, key) = pointer.rsplit_once('/').unwrap();
    let removed = value
        .pointer_mut(parent)
        .unwrap()
        .as_object_mut()
        .unwrap()
        .remove(key);
    assert!(removed.is_some(), "missing test field at {pointer}");
    assert!(
        serde_json::from_value::<T>(value).is_err(),
        "schema accepted absent required nullable field {pointer}"
    );
}

#[test]
fn checked_in_review_schemas_parse_and_reject_unknown_top_level_fields() {
    let spec = format!("{ROOT}/inputs/v3-spec.json");
    let request = format!("{ROOT}/inputs/v3-request.json");
    let report = format!("{ROOT}/results/v3/review-report.json");
    let index = format!("{ROOT}/results/v3/bundle-index.json");
    serde_json::from_slice::<ReviewSpec>(&read(&spec)).unwrap();
    serde_json::from_slice::<ReviewRequest>(&read(&request)).unwrap();
    serde_json::from_slice::<ReviewReport>(&read(&report)).unwrap();
    serde_json::from_slice::<BackendBundleIndex>(&read(&index)).unwrap();
    assert_unknown_field_rejected::<ReviewSpec>(&spec);
    assert_unknown_field_rejected::<ReviewRequest>(&request);
    assert_unknown_field_rejected::<ReviewReport>(&report);
    assert_unknown_field_rejected::<BackendBundleIndex>(&index);
}

#[test]
fn nullable_wire_fields_are_required_and_must_use_explicit_null() {
    let spec = format!("{ROOT}/inputs/v3-spec.json");
    let request = format!("{ROOT}/inputs/v3-request.json");
    let report = format!("{ROOT}/results/v3/review-report.json");
    let index = format!("{ROOT}/results/v3/bundle-index.json");

    for pointer in [
        "/injection_ground_truth",
        "/target_binding/instance_key",
        "/production_reachability/evidence_path",
    ] {
        assert_missing_field_rejected::<ReviewSpec>(&spec, pointer);
    }
    assert_missing_field_rejected::<ReviewRequest>(&request, "/executions/0/campaign_coordinates");
    for pointer in [
        "/failure",
        "/candidate_inventory",
        "/executions/0/run_id",
        "/reviews/0/ground_truth_qualification",
        "/reviews/0/violation_class",
        "/reviews/0/criteria/assignment_encoding",
    ] {
        assert_missing_field_rejected::<ReviewReport>(&report, pointer);
    }
    assert_missing_field_rejected::<BackendBundleIndex>(
        &index,
        "/campaign_summary/by_execution/0/campaign_coordinates",
    );

    let predicate_without_class = json!({
        "verdict": "satisfied",
        "reason_code": "contract-satisfied"
    });
    serde_json::from_value::<zkfdo::candidate_review::schema::PredicateResult>(
        predicate_without_class,
    )
    .unwrap();
}

#[test]
fn checked_in_regressions_are_complete_value_free_and_substantively_identical() {
    let cases = [
        ("v1.1", 36usize, 72usize),
        ("v2", 36usize, 144usize),
        ("v3", 1usize, 4usize),
    ];
    for (case, candidates, executions) in cases {
        let path = format!("{ROOT}/results/{case}/review-report.json");
        let value: Value = serde_json::from_slice(&read(&path)).unwrap();
        let report: ReviewReport = serde_json::from_value(value.clone()).unwrap();
        assert_eq!(
            report.status,
            zkfdo::candidate_review::schema::ReportStatus::Complete
        );
        assert!(!report.raw_values_persisted);
        assert_eq!(report.executions.len(), executions);
        assert_eq!(report.reviews.len(), candidates);
        let inventory = report.candidate_inventory.unwrap();
        assert!(inventory.complete);
        assert_eq!(inventory.outcome_candidate_count, candidates);
        assert_eq!(inventory.matched_candidate_count, candidates);
    }

    let verifier = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(ROOT)
        .join("verify_regression.py");
    let output = Command::new("python3")
        .arg(&verifier)
        .output()
        .unwrap_or_else(|error| panic!("failed to run {}: {error}", verifier.display()));
    assert!(
        output.status.success(),
        "{} failed\nstdout:\n{}\nstderr:\n{}",
        verifier.display(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    let verified: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(verified["status"], "pass");
    assert_eq!(verified["totals"]["pairs"], 73);
    assert_eq!(verified["totals"]["execution_rows"], 220);
    assert_eq!(verified["totals"]["validated"], 73);
    assert_eq!(verified["totals"]["noncandidate_rows"], 147);
}

#[test]
fn zero_candidate_outcome_is_a_complete_negative_review() {
    let repository = Path::new(env!("CARGO_MANIFEST_DIR"));
    let temporary = tempdir().unwrap();
    let plan_source =
        repository.join("reports/controlled-v3-preflight-2026-09-23/evidence/plan.json");
    let outcome_source =
        repository.join("reports/controlled-v3-pilot-2026-09-23/evidence/outcome.json");
    let spec = repository.join(format!("{ROOT}/inputs/v3-spec.json"));
    let plan = temporary.path().join("plan.json");
    let outcome = temporary.path().join("outcome.json");
    fs::copy(&plan_source, &plan).unwrap();

    let mut outcome_value: Value = serde_json::from_slice(&read(&outcome_source)).unwrap();
    let runs = outcome_value["scheduler"]["runs"].as_array_mut().unwrap();
    let candidate_run = runs
        .iter_mut()
        .find(|run| run["result"]["status"] == "bug_found")
        .unwrap();
    candidate_run["result"]["status"] = Value::String("no_counterexample".to_owned());
    outcome_value["counterexample_candidates"] = Value::Array(Vec::new());
    fs::write(&outcome, serde_json::to_vec_pretty(&outcome_value).unwrap()).unwrap();

    let engine_source = include_bytes!("../src/candidate_review/engine.rs");
    let engine_sources: [(&str, &[u8]); 8] = [
        ("engine.rs", engine_source),
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
    for (name, source) in engine_sources {
        fs::write(temporary.path().join(name), source).unwrap();
    }
    let source_manifest = temporary.path().join("engine-source-manifest.json");
    fs::write(
        &source_manifest,
        serde_json::to_vec_pretty(&json!({
            "schema_version": 1,
            "files": engine_sources.into_iter().map(|(name, source)| json!({
                "path": name,
                "size": source.len(),
                "sha256": sha256(source)
            })).collect::<Vec<_>>()
        }))
        .unwrap(),
    )
    .unwrap();

    let mut adapter_hasher = Sha256::new();
    adapter_hasher.update(engine_source);
    adapter_hasher.update(b"\0");
    adapter_hasher.update(b"zkfDO candidate adapter zkfuzz-counterexample-v1 schema 1\n");
    let adapter_sha256 = format!("{:x}", adapter_hasher.finalize());
    let request = temporary.path().join("request.json");
    fs::write(
        &request,
        serde_json::to_vec_pretty(&json!({
            "schema_version": 1,
            "request_id": "zero-candidate-regression",
            "kind": "backend-candidates",
            "review_specs": [{"path": spec, "sha256": sha256(&read(&spec))}],
            "executions": [{
                "execution_id": "zero-candidate-v3",
                "campaign_coordinates": null,
                "plan": {"path": plan, "sha256": sha256(&read(&plan))},
                "outcome": {"path": outcome, "sha256": sha256(&read(&outcome))}
            }],
            "candidate_adapter": {
                "id": "zkfuzz-counterexample-v1",
                "implementation_sha256": adapter_sha256
            },
            "candidate_policy": "all-outcome-candidates",
            "unmatched_candidate_policy": "record-unreviewed",
            "qualification_bundles": []
        }))
        .unwrap(),
    )
    .unwrap();

    let output = temporary.path().join("review-output");
    let result = review(&ReviewOptions {
        request,
        output: output.clone(),
        python_bin: "python3".into(),
        source_revision: "synthetic-zero-candidate-test".to_owned(),
        engine_source_manifest: source_manifest,
        executable: std::env::current_exe().unwrap(),
    })
    .unwrap();
    assert_eq!(result.status, ReportStatus::Complete);
    let report: ReviewReport = serde_json::from_slice(&read(result.report_path)).unwrap();
    assert!(report.reviews.is_empty());
    assert!(report.candidate_errors.is_empty());
    assert!(report.unreviewed_candidates.is_empty());
    assert_eq!(report.executions.len(), 4);
    assert!(report.executions.iter().all(|row| row.candidate_count == 0));
    let inventory = report.candidate_inventory.unwrap();
    assert!(inventory.complete);
    assert_eq!(inventory.outcome_candidate_count, 0);
    assert_eq!(inventory.review_pair_count, 0);

    let index_path = result.bundle_index_path.unwrap();
    let index: BackendBundleIndex = serde_json::from_slice(&read(&index_path)).unwrap();
    assert_eq!(index.execution_evaluations.len(), 1);
    let execution = &index.execution_evaluations[0];
    let index_directory = index_path.parent().unwrap();
    let confirmation_path = index_directory.join(&execution.confirmation.path);
    let confirmation_bytes = read(&confirmation_path);
    assert_eq!(sha256(&confirmation_bytes), execution.confirmation.sha256);
    let confirmation: Value = serde_json::from_slice(&confirmation_bytes).unwrap();
    assert_eq!(confirmation["schema_version"], 2);
    assert_eq!(confirmation["confirmations"], json!([]));

    let evaluator_path = index_directory.join(&execution.evaluator_output.path);
    let evaluator_bytes = read(&evaluator_path);
    assert_eq!(sha256(&evaluator_bytes), execution.evaluator_output.sha256);
    let evaluator: Value = serde_json::from_slice(&evaluator_bytes).unwrap();
    assert_eq!(evaluator["target_count"], 4);
    assert_eq!(evaluator["backend_bug_candidate_count"], 0);
    assert_eq!(evaluator["preserved_counterexample_count"], 0);
    assert_eq!(evaluator["reviewed_confirmation_count"], 0);
    assert_eq!(evaluator["confirmed_project_defect_count"], 0);
    assert_eq!(evaluator["confirmed_original_component_defect_count"], 0);
    assert_eq!(evaluator["confirmed_project_root_causes"], json!([]));
    assert_eq!(
        evaluator["confirmed_original_component_root_causes"],
        json!([])
    );
    assert_eq!(evaluator["detection_curve"], json!([]));
    assert_eq!(evaluator["original_component_detection_curve"], json!([]));
    assert!(evaluator["first_confirmed_defect_observed_by_seconds"].is_null());
    assert!(evaluator["first_confirmed_original_component_defect_observed_by_seconds"].is_null());
    assert_eq!(index.campaign_summary.unique_validated_root_cause_count, 0);
    assert!(index
        .campaign_summary
        .unique_validated_root_cause_ids
        .is_empty());
}
