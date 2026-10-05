//! Structural, value-free import checks. These fixtures contain no circuit,
//! candidate assignment, executable backend, or semantic verification evidence.
use std::{fs, path::Path};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tempfile::TempDir;
use zkfdo::candidate_review::schema::{BackendReview, ReviewRecord, ReviewReport};
use zkfdo::evidence_record::{import_record, schema::EvidenceRecord};

fn known(value: impl Into<Value>) -> Value {
    json!({"state": "known", "value": value.into()})
}

fn unknown(reason: &str) -> Value {
    json!({"state": "unknown", "reason": reason})
}

fn write_json(path: &Path, value: &Value) -> Value {
    let bytes = serde_json::to_vec_pretty(value).unwrap();
    fs::write(path, &bytes).unwrap();
    json!({"path": path, "sha256": format!("{:x}", Sha256::digest(bytes))})
}

fn runner_result() -> Value {
    json!({
        "run_id": "synthetic-run", "target": "metadata-only-target",
        "command": {"binary": "not-an-executable", "args": []},
        "started_at": "2026-10-01T00:00:00Z", "finished_at": "2026-10-01T00:00:03Z",
        "wall_time_seconds": 3.0, "budget_seconds": 20,
        "execution_limit_seconds": 20.0, "process_start_offset_seconds": 0.02,
        "timed_out": false, "exit_code": 0, "status": "bug_found",
        "random_seed": null, "last_generation": null,
        "stdout_path": "absent-stdout", "stderr_path": "absent-stderr", "error": null
    })
}

fn candidate_ref() -> Value {
    // The path intentionally does not exist: this API imports references only.
    json!({"path": "absent-synthetic-candidate-metadata", "sha256": "a".repeat(64)})
}

fn outcome(with_candidate: bool) -> Value {
    let reference = candidate_ref();
    let artifacts = if with_candidate {
        vec![json!({
            "target_id": "synthetic-target", "run_id": "synthetic-run",
            "original_path": reference["path"], "preserved_path": reference["path"],
            "sha256": reference["sha256"], "classification": "synthetic-metadata"
        })]
    } else {
        Vec::new()
    };
    json!({
        "schema_version": 1, "outcome_id": "synthetic-outcome",
        "report_path": "absent-outcome", "plan_path": "absent-plan",
        "plan_sha256": "b".repeat(64), "plan_id": "synthetic-plan",
        "strategy": "risk-only", "execution_mode": "ordered",
        "ranking_preparation_excluded_from_fuzzing_budget": true,
        "started_at": "2026-10-01T00:00:00Z", "finished_at": "2026-10-01T00:00:04Z",
        "elapsed_seconds": 4.0, "budget_seconds_per_target": 20, "total_budget_seconds": 60,
        "zkfuzz_binary": "not-an-executable", "zkfuzz_binary_sha256": "c".repeat(64),
        "mutation_settings": {
            "source_path": null, "source_sha256": null, "frozen_path": null,
            "frozen_sha256": null, "requested_seed": null,
            "effective_seed": null, "seed_controlled": false
        },
        "scheduler": {
            "experiment_id": "synthetic-experiment", "scheduler": "ordered",
            "budget_seconds_per_target": 20, "total_budget_seconds": 60,
            "planned_target_ids": ["synthetic-target"],
            "started_at": "2026-10-01T00:00:00Z", "finished_at": "2026-10-01T00:00:04Z",
            "elapsed_seconds": 3.8,
            "runs": [{
                "target_id": "synthetic-target", "index": 0,
                "process_start_offset_seconds": 0.1, "completion_offset_seconds": 3.4,
                "execution_limit_seconds": 20.0, "result": runner_result()
            }],
            "failures": [], "skipped": [], "summary_path": "absent-summary"
        },
        "counterexample_candidates": artifacts, "limitations": ["synthetic metadata only"]
    })
}

fn request(source: Value, method: &str) -> Value {
    json!({
        "schema_version": 1, "record_id": "synthetic-record",
        "context": {
            "execution_unit_id": "synthetic-unit", "method": method,
            "repetition": unknown("not present in imported metadata"),
            "project": unknown("fixture has no project"),
            "source_version": unknown("fixture has no source tree"),
            "entrypoint": unknown("fixture has no circuit"),
            "settings_sha256": unknown("not recorded"), "tool_versions": {}
        },
        "policy_intent": {
            "design": "a", "unit_wall_budget_seconds": known(60),
            "attempt_wall_limit_seconds": known(20), "cpu_limit": unknown("not decided"),
            "memory_limit_bytes": unknown("not decided"),
            "seed_order_ref": unknown("not frozen")
        },
        "source": source, "review_reports": [], "review_observations": []
    })
}

fn runner_request(temp: &TempDir, method: &str) -> Value {
    let reference = write_json(&temp.path().join("source.json"), &runner_result());
    request(
        json!({"format": "runner-result", "file": reference, "target_id": "synthetic-target"}),
        method,
    )
}

fn outcome_request(temp: &TempDir, with_candidate: bool) -> Value {
    let reference = write_json(&temp.path().join("source.json"), &outcome(with_candidate));
    request(
        json!({"format": "experiment-outcome", "file": reference, "run_id": "synthetic-run"}),
        "whole",
    )
}

fn import(temp: &TempDir, request: &Value) -> Value {
    let request_path = temp.path().join("request.json");
    let output_path = temp.path().join("record.json");
    write_json(&request_path, request);
    let record = import_record(&request_path, &output_path).unwrap();
    let value = serde_json::to_value(record).unwrap();
    let persisted: Value = serde_json::from_slice(&fs::read(&output_path).unwrap()).unwrap();
    assert_eq!(value, persisted);
    let _: EvidenceRecord = serde_json::from_value(persisted).unwrap();
    value
}

fn assert_unknown(value: &Value) {
    assert_eq!(value["state"], "unknown");
    assert!(!value["reason"].as_str().unwrap().trim().is_empty());
}

fn assessment(state: &str, evidence: &Value) -> Value {
    json!({"state": state, "reason": "synthetic imported claim, not a semantic check", "evidence": [evidence]})
}

fn observation(id: &str, evidence: &Value) -> Value {
    json!({
        "observation_id": id, "run_id": "synthetic-run", "target_id": "synthetic-target",
        "candidate": candidate_ref(), "candidate_record_id": known("synthetic-candidate-record"),
        "component_layer": "general",
        "localization": {"state": "localized", "instance_key": "synthetic-instance", "evidence": [evidence]},
        "cause_deduplication": {"state": "canonical"},
        "component": assessment("reported-confirmed", evidence),
        "entrypoint_tcct": assessment("not-attempted", evidence),
        "projection": assessment("reported-confirmed", evidence),
        "attribution": {
            "state": "matched", "method": known("manual-cause-review"),
            "proposed_cause_id": known("synthetic-cause"),
            "reason": "synthetic imported association", "evidence": [evidence]
        },
        "completion": "complete", "completion_reason": "synthetic annotation completed",
        "automated_review_seconds": unknown("not recorded"),
        "human_review_seconds": unknown("not recorded"),
        "duplicate_of": unknown("no earlier observation")
    })
}

#[test]
fn whole_and_split_roundtrip_without_inventing_missing_metadata_or_resources() {
    for method in ["whole", "split"] {
        let temp = TempDir::new().unwrap();
        let input = runner_request(&temp, method);
        let source_before = fs::read(temp.path().join("source.json")).unwrap();
        let record = import(&temp, &input);
        assert_eq!(record["context"]["method"], method);
        assert_unknown(&record["context"]["repetition"]);
        assert_unknown(&record["context"]["source_version"]);
        assert_eq!(record["execution"]["actual_wall_seconds"], known(3.0));
        assert_eq!(
            record["execution"]["process_start_offset"]["seconds"],
            known(0.02)
        );
        assert_eq!(
            record["execution"]["process_start_offset"]["origin"],
            "runner execute entry"
        );
        assert_eq!(
            record["execution"]["allocated_attempt_seconds"]["value"],
            20.0
        );
        for field in [
            "actual_cpu_seconds",
            "peak_memory_bytes",
            "remaining_budget_seconds",
            "idle_seconds",
            "exact_candidate_time",
        ] {
            assert_unknown(&record["execution"][field]);
        }
        assert_eq!(record["policy_intent"]["design"], "a");
        assert!(!record["policy_rules"].as_array().unwrap().is_empty());
        assert_ne!(record["policy_execution_verified"], known(true));
        assert!(record["component_cause_links"]
            .as_object()
            .unwrap()
            .is_empty());
        assert_eq!(
            fs::read(temp.path().join("source.json")).unwrap(),
            source_before
        );
    }
}

fn incomplete_aggregation_metadata() -> Value {
    json!({
        "candidate_inventory": {
            "complete": false,
            "reason": "synthetic metadata does not establish inventory completeness",
            "evidence": []
        },
        "review_inventory": [],
        "candidate_times": []
    })
}

#[test]
fn old_record_request_stays_v1_and_v2_declarations_are_preserved() {
    for version in [1, 2] {
        let temp = TempDir::new().unwrap();
        let mut input = runner_request(&temp, "whole");
        input["schema_version"] = json!(version);
        if version == 2 {
            input["aggregation_metadata"] = incomplete_aggregation_metadata();
        }
        let record = import(&temp, &input);
        assert_eq!(record["schema_version"], version);
        if version == 1 {
            assert!(record.get("aggregation_metadata").is_none());
        } else {
            assert_eq!(
                record["aggregation_metadata"],
                input["aggregation_metadata"]
            );
        }
    }
}

#[test]
fn version_metadata_mismatch_and_unsupported_versions_do_not_create_records() {
    for (version, metadata_present) in [(1, true), (2, false), (3, true)] {
        let temp = TempDir::new().unwrap();
        let mut input = runner_request(&temp, "whole");
        input["schema_version"] = json!(version);
        if metadata_present {
            input["aggregation_metadata"] = incomplete_aggregation_metadata();
        }
        let request_path = temp.path().join("request.json");
        let output_path = temp.path().join("record.json");
        write_json(&request_path, &input);
        assert!(import_record(&request_path, &output_path).is_err());
        assert!(!output_path.exists());
    }
}

#[test]
fn complete_inventory_without_evidence_is_rejected_before_output_creation() {
    let temp = TempDir::new().unwrap();
    let mut input = runner_request(&temp, "whole");
    input["schema_version"] = json!(2);
    input["aggregation_metadata"] = incomplete_aggregation_metadata();
    input["aggregation_metadata"]["candidate_inventory"]["complete"] = json!(true);
    let request_path = temp.path().join("request.json");
    let output_path = temp.path().join("record.json");
    write_json(&request_path, &input);
    assert!(import_record(&request_path, &output_path).is_err());
    assert!(!output_path.exists());
}

#[test]
fn unattempted_projection_cannot_create_a_cause_in_either_method() {
    for method in ["whole", "split"] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        input["context"]["method"] = json!(method);
        let mut claim = observation("projection-not-attempted", &input["source"]["file"]);
        claim["projection"] = assessment("not-attempted", &input["source"]["file"]);
        input["review_observations"] = json!([claim]);
        let record = import(&temp, &input);
        assert_eq!(
            record["reviews"][0]["observation"]["projection"]["state"],
            "not-attempted"
        );
        assert!(record["component_cause_links"]
            .as_object()
            .unwrap()
            .is_empty());
    }
}

#[test]
fn split_entrypoint_root_claim_is_preserved_without_becoming_a_cause_link() {
    let temp = TempDir::new().unwrap();
    let mut input = outcome_request(&temp, true);
    input["context"]["method"] = json!("split");
    let mut claim = observation("split-root-claim", &input["source"]["file"]);
    claim["localization"] = json!({"state": "root", "evidence": [input["source"]["file"]]});
    input["review_observations"] = json!([claim]);
    let record = import(&temp, &input);
    assert_eq!(
        record["reviews"][0]["observation"]["localization"]["state"],
        "root"
    );
    assert!(record["component_cause_links"]
        .as_object()
        .unwrap()
        .is_empty());
    assert!(record["aggregation_issues"]["split-root-claim"]
        .as_str()
        .unwrap()
        .contains("entrypoint"));
}

#[test]
fn malformed_explicit_evidence_references_cannot_support_confirmation() {
    for field in ["component", "projection", "attribution", "localization"] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        let mut claim = observation("malformed-ref", &input["source"]["file"]);
        claim[field]["evidence"][0]["sha256"] = json!("not-a-sha256");
        input["review_observations"] = json!([claim]);
        let request_path = temp.path().join("request.json");
        let output_path = temp.path().join("record.json");
        write_json(&request_path, &input);
        assert!(import_record(&request_path, &output_path).is_err());
        assert!(!output_path.exists());
    }
}

#[test]
fn orphan_and_cyclic_cause_aliases_remain_observations_not_causes() {
    for cycle in [false, true] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        let mut first = observation("alias-a", &input["source"]["file"]);
        first["cause_deduplication"] =
            json!({"state": "duplicate-of", "cause_id": "synthetic-cause-b"});
        let mut claims = vec![first];
        if cycle {
            let mut second = observation("alias-b", &input["source"]["file"]);
            second["attribution"]["proposed_cause_id"] = known("synthetic-cause-b");
            second["cause_deduplication"] =
                json!({"state": "duplicate-of", "cause_id": "synthetic-cause"});
            claims.push(second);
        }
        input["review_observations"] = json!(claims);
        let record = import(&temp, &input);
        assert_eq!(record["reviews"].as_array().unwrap().len(), claims.len());
        assert!(record["component_cause_links"]
            .as_object()
            .unwrap()
            .is_empty());
        assert!(record["aggregation_issues"].as_object().unwrap().len() >= claims.len());
    }
}

#[test]
fn orphan_cycle_and_wrong_cause_observation_links_do_not_silently_deduplicate() {
    for invalid in ["orphan", "cycle", "wrong-cause"] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        let mut first = observation("duplicate-a", &input["source"]["file"]);
        first["duplicate_of"] = known("duplicate-b");
        let mut claims = vec![first];
        if invalid != "orphan" {
            let mut second = observation("duplicate-b", &input["source"]["file"]);
            if invalid == "cycle" {
                second["duplicate_of"] = known("duplicate-a");
            } else {
                second["attribution"]["proposed_cause_id"] = known("synthetic-cause-b");
                second["duplicate_of"] = known("duplicate-a");
            }
            claims.push(second);
        }
        input["review_observations"] = json!(claims);
        let record = import(&temp, &input);
        assert_eq!(record["reviews"].as_array().unwrap().len(), claims.len());
        assert!(record["component_cause_links"]
            .as_object()
            .unwrap()
            .is_empty());
        assert!(!record["aggregation_issues"].as_object().unwrap().is_empty());
    }
}

#[test]
fn older_result_missing_execution_limit_does_not_gain_a_zero_limit() {
    let temp = TempDir::new().unwrap();
    let mut source = runner_result();
    source
        .as_object_mut()
        .unwrap()
        .remove("execution_limit_seconds");
    source
        .as_object_mut()
        .unwrap()
        .remove("process_start_offset_seconds");
    let reference = write_json(&temp.path().join("source.json"), &source);
    let input = request(
        json!({"format": "runner-result", "file": reference, "target_id": "synthetic-target"}),
        "whole",
    );
    let record = import(&temp, &input);
    assert_unknown(&record["execution"]["execution_limit_seconds"]);
    assert_unknown(&record["execution"]["source_repetition"]);
    assert_unknown(&record["execution"]["source_method"]);
    assert_unknown(&record["execution"]["candidate_inventory"]);
    assert_unknown(&record["execution"]["process_start_offset"]["seconds"]);
}

#[test]
fn timing_origins_do_not_turn_log_or_completion_time_into_exact_generation_time() {
    let mut meanings = Vec::new();
    for lane in ["whole", "random"] {
        let temp = TempDir::new().unwrap();
        let ledger = json!({
            "schema_version": 1, "case": "synthetic", "lane": lane,
            "executions": [{
                "block": 1, "elapsed_seconds": 8.0, "status": "bug_found",
                "found": true, "found_at_seconds": 7.0,
                "ground_truth": {"synthetic-label": {"completed_at_seconds": 7.0}},
                "log": "absent-log"
            }]
        });
        let reference = write_json(&temp.path().join("source.json"), &ledger);
        let input = request(
            json!({"format": "p2-ledger", "file": reference, "execution_index": 0}),
            if lane == "whole" { "whole" } else { "split" },
        );
        let record = import(&temp, &input);
        assert_unknown(&record["execution"]["exact_candidate_time"]);
        let times = record["execution"]["candidate_times"].as_array().unwrap();
        assert!(!times.is_empty());
        assert_eq!(times[0]["seconds"], known(7.0));
        assert!(!times[0]["origin"].as_str().unwrap().is_empty());
        meanings.push(times[0]["meaning"].as_str().unwrap().to_owned());
    }
    let temp = TempDir::new().unwrap();
    let input = outcome_request(&temp, true);
    let record = import(&temp, &input);
    assert_unknown(&record["execution"]["exact_candidate_time"]);
    let times = record["execution"]["candidate_times"].as_array().unwrap();
    assert_eq!(times[0]["seconds"], known(3.4));
    assert_eq!(
        record["execution"]["process_start_offset"]["seconds"],
        known(0.1)
    );
    assert_eq!(
        record["execution"]["process_start_offset"]["origin"],
        "scheduler start"
    );
    meanings.push(times[0]["meaning"].as_str().unwrap().to_owned());
    assert_ne!(meanings[0], meanings[1]);
    assert_ne!(meanings[0], meanings[2]);
    assert_ne!(meanings[1], meanings[2]);
}

#[test]
fn cause_links_preserve_duplicates_without_mixing_tcct_or_unresolved_results() {
    let temp = TempDir::new().unwrap();
    let mut input = outcome_request(&temp, true);
    let evidence = input["source"]["file"].clone();
    let first = observation("component-1", &evidence);
    let mut duplicate = observation("component-2", &evidence);
    duplicate["duplicate_of"] = known("component-1");
    duplicate["cause_deduplication"] =
        json!({"state": "duplicate-of", "cause_id": "synthetic-cause"});
    let mut tcct = observation("entrypoint-only", &evidence);
    tcct["component"] = assessment("not-attempted", &evidence);
    tcct["entrypoint_tcct"] = assessment("reported-confirmed", &evidence);
    tcct["projection"] = assessment("unresolved", &evidence);
    tcct["attribution"]["state"] = json!("unknown");
    tcct["completion"] = json!("incomplete");
    let mut failed = observation("attribution-failed", &evidence);
    failed["attribution"]["state"] = json!("not-matched");
    let mut interrupted = observation("review-interrupted", &evidence);
    interrupted["component"] = assessment("unresolved", &evidence);
    interrupted["projection"] = assessment("interrupted", &evidence);
    interrupted["attribution"]["state"] = json!("unknown");
    interrupted["completion"] = json!("interrupted");
    input["review_observations"] = json!([first, duplicate, tcct, failed, interrupted]);
    let record = import(&temp, &input);
    assert_eq!(
        record["component_cause_links"],
        json!({"synthetic-cause": ["component-1", "component-2"]})
    );
    let reviews = record["reviews"].as_array().unwrap();
    assert_eq!(reviews.len(), 5);
    for review in reviews {
        assert_eq!(review["metadata_binding"], known(true));
    }
    assert_eq!(
        reviews[1]["observation"]["duplicate_of"],
        known("component-1")
    );
    assert_eq!(
        reviews[2]["observation"]["entrypoint_tcct"]["state"],
        "reported-confirmed"
    );
    assert_eq!(
        reviews[2]["observation"]["projection"]["state"],
        "unresolved"
    );
    assert_eq!(
        reviews[3]["observation"]["attribution"]["proposed_cause_id"],
        known("synthetic-cause")
    );
    assert_eq!(reviews[4]["observation"]["completion"], "interrupted");
}

#[test]
fn absent_candidate_inventory_cannot_bind_manual_claim_by_identity_alone() {
    let temp = TempDir::new().unwrap();
    let mut input = outcome_request(&temp, false);
    input["review_observations"] = json!([observation("unbound-claim", &input["source"]["file"])]);
    let record = import(&temp, &input);
    assert_unknown(&record["reviews"][0]["metadata_binding"]);
    assert!(record["component_cause_links"]
        .as_object()
        .unwrap()
        .is_empty());
    assert_eq!(
        record["reviews"][0]["observation"]["component"]["state"],
        "reported-confirmed"
    );
}

#[test]
fn mismatched_review_identity_or_candidate_hash_cannot_enter_cause_links() {
    for dimension in ["run_id", "target_id", "candidate_hash"] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        let mut claim = observation("mismatched-claim", &input["source"]["file"]);
        if dimension == "candidate_hash" {
            claim["candidate"]["sha256"] = json!("d".repeat(64));
        } else {
            claim[dimension] = json!("different-identity");
        }
        input["review_observations"] = json!([claim]);
        let record = import(&temp, &input);
        assert_ne!(record["reviews"][0]["metadata_binding"], known(true));
        assert!(record["component_cause_links"]
            .as_object()
            .unwrap()
            .is_empty());
    }
}

#[test]
fn missing_source_hash_mismatch_unknown_request_field_and_negative_policy_are_rejected() {
    for invalid in [
        "missing-file",
        "hash-mismatch",
        "unknown-field",
        "negative-budget",
    ] {
        let temp = TempDir::new().unwrap();
        let mut input = runner_request(&temp, "whole");
        match invalid {
            "missing-file" => {
                fs::remove_file(temp.path().join("source.json")).unwrap();
            }
            "hash-mismatch" => input["source"]["file"]["sha256"] = json!("0".repeat(64)),
            "unknown-field" => input["unrecognized_option"] = json!(true),
            "negative-budget" => input["policy_intent"]["unit_wall_budget_seconds"] = known(-1.0),
            _ => unreachable!(),
        }
        let request_path = temp.path().join("request.json");
        let output_path = temp.path().join("record.json");
        write_json(&request_path, &input);
        assert!(
            import_record(&request_path, &output_path).is_err(),
            "accepted {invalid}"
        );
        assert!(!output_path.exists());
    }
}

#[test]
fn negative_observed_wall_time_is_rejected_instead_of_becoming_known() {
    let temp = TempDir::new().unwrap();
    let mut source = runner_result();
    source["wall_time_seconds"] = json!(-1.0);
    let reference = write_json(&temp.path().join("source.json"), &source);
    let input = request(
        json!({"format": "runner-result", "file": reference, "target_id": "synthetic-target"}),
        "split",
    );
    let request_path = temp.path().join("request.json");
    let output_path = temp.path().join("record.json");
    write_json(&request_path, &input);
    assert!(import_record(&request_path, &output_path).is_err());
    assert!(!output_path.exists());
}

#[test]
fn output_is_create_new_and_never_overwrites_an_existing_record() {
    let temp = TempDir::new().unwrap();
    let input = runner_request(&temp, "whole");
    let request_path = temp.path().join("request.json");
    let output_path = temp.path().join("record.json");
    write_json(&request_path, &input);
    fs::write(&output_path, b"previous immutable record\n").unwrap();
    assert!(import_record(&request_path, &output_path).is_err());
    assert_eq!(
        fs::read(&output_path).unwrap(),
        b"previous immutable record\n"
    );
}

#[test]
fn binding_only_matched_claim_is_preserved_but_cannot_count_as_cause_evidence() {
    for method in [
        "binding-only",
        "KnownDefectSingleTarget",
        "known_defect_single_target",
        "location-match",
        "single-target",
        "known-defect-target",
        "p2-found",
        "ground-truth-location",
        "unregistered-procedure",
    ] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        let mut claim = observation("binding-only-claim", &input["source"]["file"]);
        claim["attribution"]["method"] = known(method);
        input["review_observations"] = json!([claim]);
        let record = import(&temp, &input);
        assert_eq!(record["reviews"][0]["metadata_binding"], known(true));
        assert_eq!(
            record["reviews"][0]["observation"]["attribution"]["state"],
            "unknown"
        );
        let request_bytes = fs::read(temp.path().join("request.json")).unwrap();
        let preserved_request: Value = serde_json::from_slice(&request_bytes).unwrap();
        assert_eq!(preserved_request, input);
        assert_eq!(
            preserved_request["review_observations"][0]["attribution"]["state"],
            "matched"
        );
        assert_eq!(
            record["request"]["sha256"],
            format!("{:x}", Sha256::digest(request_bytes))
        );
        assert_eq!(
            record["reviews"][0]["observation"]["attribution"]["method"],
            known(method)
        );
        assert!(record["component_cause_links"]
            .as_object()
            .unwrap()
            .is_empty());
    }
}

#[test]
fn unresolved_deduplication_does_not_hide_a_conflicting_matched_cause() {
    let temp = TempDir::new().unwrap();
    let mut input = outcome_request(&temp, true);
    let first = observation("canonical-claim", &input["source"]["file"]);
    let mut second = observation("unresolved-duplicate-claim", &input["source"]["file"]);
    second["attribution"]["proposed_cause_id"] = known("synthetic-cause-b");
    second["cause_deduplication"] =
        json!({"state": "unresolved", "reason": "synthetic duplicate identity unresolved"});
    input["review_observations"] = json!([first, second]);
    let record = import(&temp, &input);
    assert_eq!(record["reviews"].as_array().unwrap().len(), 2);
    assert!(record["component_cause_links"]
        .as_object()
        .unwrap()
        .is_empty());
    assert!(record["aggregation_issues"]["a".repeat(64)]
        .as_str()
        .unwrap()
        .contains("ambiguous"));
}

#[test]
fn duplicate_alias_cannot_redirect_to_an_existing_but_different_cause() {
    let temp = TempDir::new().unwrap();
    let mut metadata = outcome(true);
    let mut second_candidate = metadata["counterexample_candidates"][0].clone();
    second_candidate["sha256"] = json!("d".repeat(64));
    metadata["counterexample_candidates"]
        .as_array_mut()
        .unwrap()
        .push(second_candidate);
    let source_ref = write_json(&temp.path().join("source.json"), &metadata);
    let mut input = request(
        json!({"format": "experiment-outcome", "file": source_ref, "run_id": "synthetic-run"}),
        "whole",
    );
    let canonical = observation("canonical-claim", &input["source"]["file"]);
    let mut alias = observation("unsupported-alias", &input["source"]["file"]);
    alias["candidate"]["sha256"] = json!("d".repeat(64));
    alias["attribution"]["proposed_cause_id"] = known("different-proposed-cause");
    alias["cause_deduplication"] = json!({"state": "duplicate-of", "cause_id": "synthetic-cause"});
    input["review_observations"] = json!([canonical, alias]);
    let record = import(&temp, &input);
    assert_eq!(
        record["component_cause_links"],
        json!({"synthetic-cause": ["canonical-claim"]})
    );
    assert!(record["aggregation_issues"]["unsupported-alias"]
        .as_str()
        .unwrap()
        .contains("alias"));
}

#[test]
fn runner_request_target_remains_a_request_claim_not_an_observed_identity() {
    let temp = TempDir::new().unwrap();
    let input = runner_request(&temp, "whole");
    let record = import(&temp, &input);
    assert_unknown(&record["execution"]["target_id"]);
    assert_eq!(record["source"]["target_id"], "synthetic-target");
    assert!(record["execution"]["target_id"]["reason"]
        .as_str()
        .unwrap()
        .contains("requested target"));
}

#[test]
fn p2_known_lanes_enforce_method_and_unknown_lanes_fail_closed() {
    for lane in [
        "whole",
        "path-order",
        "small-first",
        "random",
        "unrecognized",
    ] {
        for method in ["whole", "split"] {
            let temp = TempDir::new().unwrap();
            let metadata =
                json!({"lane": lane, "executions": [{"block": 0, "elapsed_seconds": 3.0}]});
            let reference = write_json(&temp.path().join("source.json"), &metadata);
            let input = request(
                json!({"format": "p2-ledger", "file": reference, "execution_index": 0}),
                method,
            );
            let request_path = temp.path().join("request.json");
            let output_path = temp.path().join("record.json");
            write_json(&request_path, &input);
            let result = import_record(&request_path, &output_path);
            let expected = lane != "unrecognized" && (lane == "whole") == (method == "whole");
            assert_eq!(result.is_ok(), expected, "lane={lane}, method={method}");
            if !expected {
                assert!(!output_path.exists());
            }
        }
    }
}

#[test]
fn same_run_with_conflicting_target_in_candidate_metadata_is_rejected() {
    let temp = TempDir::new().unwrap();
    let mut metadata = outcome(true);
    metadata["counterexample_candidates"][0]["target_id"] = json!("conflicting-target");
    let reference = write_json(&temp.path().join("source.json"), &metadata);
    let input = request(
        json!({"format": "experiment-outcome", "file": reference, "run_id": "synthetic-run"}),
        "whole",
    );
    let request_path = temp.path().join("request.json");
    let output_path = temp.path().join("record.json");
    write_json(&request_path, &input);
    assert!(import_record(&request_path, &output_path).is_err());
    assert!(!output_path.exists());
}

#[test]
fn two_canonical_causes_for_one_candidate_are_ambiguous_without_silent_selection() {
    let temp = TempDir::new().unwrap();
    let mut input = outcome_request(&temp, true);
    let first = observation("cause-claim-1", &input["source"]["file"]);
    let mut second = observation("cause-claim-2", &input["source"]["file"]);
    second["attribution"]["proposed_cause_id"] = known("another-synthetic-cause");
    input["review_observations"] = json!([first, second]);
    let record = import(&temp, &input);
    assert_eq!(record["reviews"].as_array().unwrap().len(), 2);
    assert!(record["component_cause_links"]
        .as_object()
        .unwrap()
        .is_empty());
    assert!(!record["aggregation_issues"].as_object().unwrap().is_empty());
    assert_eq!(
        record["reviews"][0]["observation"]["attribution"]["proposed_cause_id"],
        known("synthetic-cause")
    );
    assert_eq!(
        record["reviews"][1]["observation"]["attribution"]["proposed_cause_id"],
        known("another-synthetic-cause")
    );
}

#[test]
fn contract_and_unspecified_legacy_claims_remain_outside_general_cause_links() {
    for layer in ["contract", "legacy-unspecified"] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        let mut claim = observation("non-general-claim", &input["source"]["file"]);
        claim["component_layer"] = json!(layer);
        input["review_observations"] = json!([claim]);
        let record = import(&temp, &input);
        assert_eq!(
            record["reviews"][0]["observation"]["component_layer"],
            layer
        );
        assert!(record["component_cause_links"]
            .as_object()
            .unwrap()
            .is_empty());
    }
}

#[test]
fn failed_or_multi_localization_does_not_create_a_cause_in_either_method() {
    for method in ["whole", "split"] {
        for localization in [
            json!({"state": "failed", "reason": "synthetic mapping unavailable"}),
            json!({"state": "multi", "instance_keys": ["synthetic-a", "synthetic-b"], "reason": "synthetic ambiguous localization"}),
        ] {
            let temp = TempDir::new().unwrap();
            let mut input = outcome_request(&temp, true);
            input["context"]["method"] = json!(method);
            let mut claim = observation("unlocalized-claim", &input["source"]["file"]);
            claim["localization"] = localization.clone();
            input["review_observations"] = json!([claim]);
            let record = import(&temp, &input);
            assert_eq!(
                record["reviews"][0]["observation"]["localization"],
                localization
            );
            assert_eq!(
                record["reviews"][0]["observation"]["component"]["state"],
                "reported-confirmed"
            );
            assert!(record["component_cause_links"]
                .as_object()
                .unwrap()
                .is_empty());
        }
    }
}

#[test]
fn cli_records_metadata_without_changing_the_hash_pinned_source() {
    let temp = TempDir::new().unwrap();
    let input = runner_request(&temp, "split");
    let request_path = temp.path().join("request.json");
    let output_path = temp.path().join("record.json");
    write_json(&request_path, &input);
    let source_before = fs::read(temp.path().join("source.json")).unwrap();
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_zkfDO"))
        .args(["experiment", "record", "--request"])
        .arg(&request_path)
        .arg("--output")
        .arg(&output_path)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let record: EvidenceRecord = serde_json::from_slice(&fs::read(&output_path).unwrap()).unwrap();
    assert_eq!(record.record_id, "synthetic-record");
    assert_eq!(
        fs::read(temp.path().join("source.json")).unwrap(),
        source_before
    );
    assert_eq!(
        input["source"]["file"]["sha256"],
        format!("{:x}", Sha256::digest(source_before))
    );
}

fn source_for_existing_review(temp: &TempDir, row: &BackendReview) -> Value {
    let mut metadata = outcome(true);
    metadata["scheduler"]["planned_target_ids"] = json!([row.binding.target_id]);
    metadata["scheduler"]["runs"][0]["target_id"] = json!(row.binding.target_id);
    metadata["scheduler"]["runs"][0]["result"]["run_id"] = json!(row.binding.run_id);
    metadata["counterexample_candidates"] = json!([{
        "target_id": row.binding.target_id, "run_id": row.binding.run_id,
        "original_path": row.candidate.path, "preserved_path": row.candidate.path,
        "sha256": row.candidate.sha256, "classification": "existing-value-free-review-reference"
    }]);
    let reference = write_json(&temp.path().join("source.json"), &metadata);
    request(
        json!({"format": "experiment-outcome", "file": reference, "run_id": row.binding.run_id}),
        "split",
    )
}

/// Shape-only copy of an existing value-free metadata report. No referenced
/// candidate, circuit, assignment, predicate or other nested file is read.
fn synthetic_legacy_report() -> (Value, BackendReview) {
    let report_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("reports/candidate-review-regression-2026-09-27/results/v3/review-report.json");
    let report: ReviewReport = serde_json::from_slice(&fs::read(report_path).unwrap()).unwrap();
    assert!(!report.raw_values_persisted);
    let ReviewRecord::Backend(row) = &report.reviews[0] else {
        panic!("expected value-free backend metadata");
    };
    let mut row = (**row).clone();
    row.binding.run_id = "synthetic-run".into();
    row.binding.target_id = "synthetic-target".into();
    row.candidate_record_id = "synthetic-candidate-record".into();
    row.root_cause_id = "synthetic-cause".into();
    row.candidate = serde_json::from_value(candidate_ref()).unwrap();
    let mut copy = serde_json::to_value(report).unwrap();
    copy["report_id"] = json!("synthetic-shape-only-report");
    copy["reviews"] = json!([ReviewRecord::Backend(Box::new(row.clone()))]);
    copy["unreviewed_candidates"] = json!([]);
    (copy, row)
}

#[test]
fn legacy_scopes_keep_their_reported_criteria_without_entrypoint_promotion() {
    for scope in [
        "original-component",
        "project",
        "wrapper-only",
        "reachability-unknown",
    ] {
        let temp = TempDir::new().unwrap();
        let (mut report, row) = synthetic_legacy_report();
        report["reviews"][0]["expected_scope"] = json!(scope);
        let mut input = source_for_existing_review(&temp, &row);
        input["review_reports"] = json!([write_json(
            &temp.path().join("synthetic-review.json"),
            &report
        )]);
        let record = import(&temp, &input);
        let normalized = &record["reviews"][0]["observation"];
        assert_eq!(normalized["component_layer"], "legacy-unspecified");
        assert_eq!(normalized["component"]["state"], "reported-confirmed");
        assert!(normalized["component"]["reason"]
            .as_str()
            .unwrap()
            .contains(scope));
        assert_eq!(normalized["entrypoint_tcct"]["state"], "not-attempted");
        assert!(record["component_cause_links"]
            .as_object()
            .unwrap()
            .is_empty());
        assert_eq!(record["preserved_review_reports"][0]["report"], report);
    }
}

#[test]
fn legacy_precondition_rejection_retains_the_failed_criterion_and_scope() {
    let temp = TempDir::new().unwrap();
    let (mut report, row) = synthetic_legacy_report();
    report["reviews"][0]["expected_scope"] = json!("project");
    report["reviews"][0]["disposition"] = json!("rejected");
    report["reviews"][0]["criteria"]["input_preconditions"]["verdict"] = json!("not-satisfied");
    report["reviews"][0]["criteria"]["input_preconditions"]["reason_code"] =
        json!("synthetic-contract-precondition-failed");
    let mut input = source_for_existing_review(&temp, &row);
    input["review_reports"] = json!([write_json(
        &temp.path().join("synthetic-review.json"),
        &report
    )]);
    let record = import(&temp, &input);
    let normalized = &record["reviews"][0]["observation"];
    assert_eq!(normalized["component"]["state"], "rejected");
    assert_eq!(normalized["component_layer"], "legacy-unspecified");
    let reason = normalized["component"]["reason"].as_str().unwrap();
    assert!(reason.contains("scope=project"));
    assert!(reason.contains("input-preconditions"));
    assert!(reason.contains("synthetic-contract-precondition-failed"));
    assert!(record["component_cause_links"]
        .as_object()
        .unwrap()
        .is_empty());
}

#[test]
fn duplicate_report_hash_case_and_conflicting_review_target_are_rejected() {
    for invalid in ["duplicate-hash-case", "conflicting-target"] {
        let temp = TempDir::new().unwrap();
        let (mut report, row) = synthetic_legacy_report();
        let mut input = source_for_existing_review(&temp, &row);
        if invalid == "conflicting-target" {
            report["reviews"][0]["binding"]["target_id"] = json!("different-target");
        }
        let reference = write_json(&temp.path().join("synthetic-review.json"), &report);
        input["review_reports"] = json!([reference]);
        if invalid == "duplicate-hash-case" {
            let mut duplicate = reference.clone();
            duplicate["sha256"] = json!(reference["sha256"].as_str().unwrap().to_ascii_uppercase());
            input["review_reports"]
                .as_array_mut()
                .unwrap()
                .push(duplicate);
        }
        let request_path = temp.path().join("request.json");
        let output_path = temp.path().join("record.json");
        write_json(&request_path, &input);
        assert!(import_record(&request_path, &output_path).is_err());
        assert!(!output_path.exists());
    }
}

#[test]
fn existing_value_free_report_preserves_matched_legacy_claim_without_promoting_it() {
    let report_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("reports/candidate-review-regression-2026-09-27/results/v3/review-report.json");
    let original_bytes = fs::read(&report_path).unwrap();
    let original_hash = format!("{:x}", Sha256::digest(&original_bytes));
    let report: ReviewReport = serde_json::from_slice(&original_bytes).unwrap();
    assert!(!report.raw_values_persisted);
    let ReviewRecord::Backend(row) = &report.reviews[0] else {
        panic!("expected a value-free backend review");
    };
    let original_row = serde_json::to_value(row).unwrap();
    assert_eq!(original_row["cause_attribution"]["verdict"], "matched");
    assert_eq!(
        original_row["cause_attribution"]["reason_code"],
        "known-defect-binding-matched"
    );
    let temp = TempDir::new().unwrap();
    let mut input = source_for_existing_review(&temp, row);
    input["review_reports"] = json!([{"path": report_path, "sha256": original_hash}]);
    let record = import(&temp, &input);
    assert_eq!(record["reviews"].as_array().unwrap().len(), 1);
    assert_eq!(record["reviews"][0]["metadata_binding"], known(true));
    assert_eq!(record["reviews"][0]["legacy_review"], original_row);
    let normalized = &record["reviews"][0]["observation"];
    assert_eq!(normalized["component_layer"], "legacy-unspecified");
    assert_eq!(normalized["attribution"]["state"], "unknown");
    assert_unknown(&normalized["attribution"]["method"]);
    assert_eq!(
        normalized["attribution"]["proposed_cause_id"],
        known(row.root_cause_id.as_str())
    );
    assert_eq!(
        normalized["candidate_record_id"],
        known(row.candidate_record_id.as_str())
    );
    assert_eq!(
        record["preserved_review_reports"][0]["report"],
        serde_json::to_value(report).unwrap()
    );
    assert!(record["component_cause_links"]
        .as_object()
        .unwrap()
        .is_empty());
    assert_eq!(fs::read(&report_path).unwrap(), original_bytes);
    assert_eq!(
        record["preserved_review_reports"][0]["file"]["sha256"],
        original_hash
    );
}

#[test]
fn synthetic_interrupted_copy_retains_missing_review_without_negative_inference() {
    let report_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("reports/candidate-review-regression-2026-09-27/results/v3/review-report.json");
    let original_bytes = fs::read(&report_path).unwrap();
    let report: ReviewReport = serde_json::from_slice(&original_bytes).unwrap();
    let ReviewRecord::Backend(row) = &report.reviews[0] else {
        panic!("expected a value-free backend review");
    };
    let mut interrupted = serde_json::to_value(&report).unwrap();
    interrupted["report_id"] = json!("synthetic-interrupted-copy");
    interrupted["status"] = json!("incomplete");
    interrupted["reviews"] = json!([]);
    interrupted["unreviewed_candidates"] = json!([{
        "candidate_record_id": row.candidate_record_id, "candidate": row.candidate,
        "execution_id": row.binding.execution_id, "run_id": row.binding.run_id,
        "target_id": row.binding.target_id, "reason_code": "synthetic-review-interruption"
    }]);
    interrupted["candidate_inventory"]["complete"] = json!(false);
    interrupted["candidate_inventory"]["terminal_review_pair_count"] = json!(0);
    interrupted["summary"] = json!({
        "validated": 0, "rejected": 0, "unresolved": 0, "review_error": 0,
        "unreviewed_candidates": 1, "attributed_validated": 0, "unique_validated_root_causes": 0
    });
    let temp = TempDir::new().unwrap();
    let mut input = source_for_existing_review(&temp, row);
    let report_ref = write_json(
        &temp.path().join("synthetic-interrupted-report.json"),
        &interrupted,
    );
    input["review_reports"] = json!([report_ref]);
    let record = import(&temp, &input);
    assert_eq!(record["preserved_review_reports"][0]["report"], interrupted);
    let normalized = &record["reviews"][0]["observation"];
    assert_eq!(normalized["completion"], "interrupted");
    assert_eq!(normalized["component"]["state"], "not-attempted");
    assert_eq!(normalized["attribution"]["state"], "unknown");
    assert_unknown(&normalized["attribution"]["proposed_cause_id"]);
    assert!(record["component_cause_links"]
        .as_object()
        .unwrap()
        .is_empty());
    assert_eq!(fs::read(report_path).unwrap(), original_bytes);
}

// Importer regressions for the offline aggregation errors found in the
// independent verification of 2026-10-01. Value-free metadata only.

fn v2_metadata(complete: bool, semantics: Value) -> Value {
    json!({
        "candidate_inventory": {
            "complete": complete, "reason": "synthetic declaration only",
            "evidence": [candidate_ref()]
        },
        "review_inventory": [], "candidate_times": [], "review_semantics": semantics
    })
}

fn semantics(id: &str, kind: &str, validated: Value) -> Value {
    json!([{
        "observation_id": id, "violation_kind": known(kind),
        "violation_evidence": [candidate_ref()],
        "localization_method": known("synthetic-localization"),
        "localization_method_validated": validated,
        "localization_evidence": [candidate_ref()]
    }])
}

fn import_error(temp: &TempDir, request: &Value) -> String {
    let request_path = temp.path().join("request.json");
    let output_path = temp.path().join("record.json");
    write_json(&request_path, request);
    let error = import_record(&request_path, &output_path).unwrap_err();
    assert!(!output_path.exists());
    format!("{error:#}")
}

#[test]
fn bug_found_without_a_candidate_reference_is_a_missing_inventory() {
    let temp = TempDir::new().unwrap();
    let record = import(&temp, &outcome_request(&temp, false));
    assert_unknown(&record["execution"]["candidate_inventory"]);
    assert!(record["execution"]["candidate_inventory"]["reason"]
        .as_str()
        .unwrap()
        .contains("bug_found"));
    for source in ["outcome", "runner"] {
        let temp = TempDir::new().unwrap();
        let mut input = if source == "outcome" {
            outcome_request(&temp, false)
        } else {
            runner_request(&temp, "whole")
        };
        input["schema_version"] = json!(2);
        input["aggregation_metadata"] = v2_metadata(true, json!([]));
        let error = import_error(&temp, &input);
        assert!(error.contains("conflicts with source metadata"), "{error}");
    }
    // A finished search without a counterexample may declare an empty inventory.
    let temp = TempDir::new().unwrap();
    let mut source = outcome(false);
    source["scheduler"]["runs"][0]["result"]["status"] = json!("no_counterexample");
    let reference = write_json(&temp.path().join("source.json"), &source);
    let mut input = request(
        json!({"format": "experiment-outcome", "file": reference, "run_id": "synthetic-run"}),
        "whole",
    );
    input["schema_version"] = json!(2);
    input["aggregation_metadata"] = v2_metadata(true, json!([]));
    let record = import(&temp, &input);
    assert_eq!(record["execution"]["candidate_inventory"]["state"], "known");
}

#[test]
fn tool_specific_check_is_kept_but_not_linked_as_a_general_cause() {
    for (kind, linked) in [("tool-specific-check", false), ("computation-abort", true)] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        input["schema_version"] = json!(2);
        input["review_observations"] =
            json!([observation("general-claim", &input["source"]["file"])]);
        input["aggregation_metadata"] = v2_metadata(
            false,
            semantics("general-claim", kind, unknown("no validation record")),
        );
        let record = import(&temp, &input);
        assert_eq!(
            record["reviews"][0]["observation"]["component"]["state"],
            "reported-confirmed"
        );
        let links = record["component_cause_links"].as_object().unwrap();
        assert_eq!(!links.is_empty(), linked, "{kind}");
        if !linked {
            assert!(record["aggregation_issues"]["general-claim"]
                .as_str()
                .unwrap()
                .contains("tool-specific-check"));
        }
    }
}

#[test]
fn cause_claims_conflicting_across_component_layers_are_ambiguous() {
    for (contract_cause, ambiguous) in [
        ("another-synthetic-cause", true),
        ("synthetic-cause", false),
    ] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        let general = observation("general-claim", &input["source"]["file"]);
        let mut contract = observation("contract-claim", &input["source"]["file"]);
        contract["component_layer"] = json!("contract");
        contract["attribution"]["proposed_cause_id"] = known(contract_cause);
        input["review_observations"] = json!([general, contract]);
        let record = import(&temp, &input);
        if ambiguous {
            assert!(record["component_cause_links"]
                .as_object()
                .unwrap()
                .is_empty());
            assert!(record["aggregation_issues"]["a".repeat(64)]
                .as_str()
                .unwrap()
                .contains("ambiguous"));
        } else {
            assert_eq!(
                record["component_cause_links"]["synthetic-cause"],
                json!(["general-claim"])
            );
        }
    }
}

#[test]
fn runner_result_reports_review_rows_it_cannot_bind_to_an_observed_target() {
    let temp = TempDir::new().unwrap();
    let (report, _) = synthetic_legacy_report();
    let mut input = runner_request(&temp, "whole");
    let reference = write_json(&temp.path().join("synthetic-review.json"), &report);
    input["review_reports"] = json!([reference]);
    let record = import(&temp, &input);
    assert!(record["reviews"].as_array().unwrap().is_empty());
    assert_eq!(record["preserved_review_reports"][0]["report"], report);
    let key = format!(
        "legacy-review-rows-not-imported:{}",
        reference["sha256"].as_str().unwrap()
    );
    assert!(record["aggregation_issues"][key]
        .as_str()
        .unwrap()
        .contains("observed target"));
}

#[test]
fn validated_localization_claim_needs_a_validation_record() {
    for (validated, accepted) in [
        (known(true), false),
        (known(false), true),
        (unknown("no validation record"), true),
    ] {
        let temp = TempDir::new().unwrap();
        let mut input = outcome_request(&temp, true);
        input["schema_version"] = json!(2);
        input["review_observations"] =
            json!([observation("general-claim", &input["source"]["file"])]);
        input["aggregation_metadata"] = v2_metadata(
            false,
            semantics("general-claim", "output-difference", validated.clone()),
        );
        if accepted {
            import(&temp, &input);
        } else {
            let error = import_error(&temp, &input);
            assert!(error.contains("validation record"), "{error}");
        }
    }
}
