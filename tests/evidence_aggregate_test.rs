//! Value-free metadata tests: references below deliberately have no candidate,
//! circuit, witness, predicate, or executable backing them. A passing test
//! establishes aggregation structure, never the truth of an imported claim.
use std::{fs, path::Path};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tempfile::TempDir;
use zkfdo::evidence_record::{aggregate::aggregate_records, import_record};

fn known(value: impl Into<Value>) -> Value {
    json!({"state": "known", "value": value.into()})
}

fn unknown(reason: &str) -> Value {
    json!({"state": "unknown", "reason": reason})
}

fn reference(label: &str, hash: char) -> Value {
    json!({"path": format!("absent-value-free-{label}"), "sha256": hash.to_string().repeat(64)})
}

fn proof() -> Value {
    reference("registration-evidence", 'f')
}

fn write_json(path: &Path, value: &Value) -> Value {
    let bytes = serde_json::to_vec_pretty(value).unwrap();
    fs::write(path, &bytes).unwrap();
    json!({"path": path, "sha256": format!("{:x}", Sha256::digest(bytes))})
}

fn coverage(complete: bool) -> Value {
    json!({"complete": complete, "reason": "synthetic inventory declaration only", "evidence": [proof()]})
}

fn record(temp: &TempDir, id: &str, method: &str) -> Value {
    let source = json!({
        "run_id": format!("run-{id}"), "target": "synthetic-target",
        "command": {"binary": "absent-do-not-execute", "args": []},
        "started_at": "2026-10-01T00:00:00Z", "finished_at": "2026-10-01T00:00:03Z",
        "wall_time_seconds": 3.0, "budget_seconds": 20,
        "execution_limit_seconds": 20.0, "process_start_offset_seconds": 0.02,
        "timed_out": false, "exit_code": 0, "status": "bug_found",
        "random_seed": null, "last_generation": null,
        "stdout_path": "absent-stdout", "stderr_path": "absent-stderr", "error": null
    });
    let source_ref = write_json(&temp.path().join(format!("source-{id}.json")), &source);
    let request = json!({
        "schema_version": 1, "record_id": id,
        "context": {
            "execution_unit_id": "synthetic-unit", "method": method,
            "repetition": known("repeat-1"), "project": known("synthetic-project"),
            "source_version": known("synthetic-version"),
            "entrypoint": known("absent-entrypoint"),
            "settings_sha256": known("4".repeat(64)),
            "tool_versions": {"synthetic-tool": known("version-1")}
        },
        "policy_intent": {
            "design": "a", "unit_wall_budget_seconds": known(60),
            "attempt_wall_limit_seconds": known(20),
            "cpu_limit": unknown("not measured"),
            "memory_limit_bytes": unknown("not measured"),
            "seed_order_ref": unknown("not frozen")
        },
        "source": {"format": "runner-result", "file": source_ref, "target_id": "synthetic-target"},
        "review_reports": [], "review_observations": []
    });
    let request_path = temp.path().join(format!("import-{id}.json"));
    write_json(&request_path, &request);
    let imported = import_record(
        &request_path,
        &temp.path().join(format!("imported-{id}.json")),
    )
    .unwrap();
    let mut record = serde_json::to_value(imported).unwrap();
    // A synthetic metadata declaration, not a guessed mapping from the runner's
    // display-name `target` field to a source target identity.
    record["execution"]["target_id"] = known("synthetic-target");
    record["execution"]["campaign_id"] = known("campaign-1");
    record["execution"]["source_repetition"] = known("repeat-1");
    record["execution"]["source_method"] = known(method);
    record
}

fn assessment(state: &str) -> Value {
    json!({"state": state, "reason": "synthetic reported claim only", "evidence": [proof()]})
}

fn add_review(record: &mut Value, id: &str, hash: char) {
    let candidate = reference(&format!("candidate-{hash}"), hash);
    let candidates = record["execution"]["candidates"].as_array_mut().unwrap();
    if !candidates
        .iter()
        .any(|item| item["sha256"] == candidate["sha256"])
    {
        candidates.push(candidate.clone());
    }
    let review = json!({
        "source_report": unknown("synthetic explicit observation"),
        "metadata_binding": known(true), "legacy_review": null,
        "observation": {
            "observation_id": id, "run_id": record["execution"]["run_id"]["value"],
            "target_id": "synthetic-target", "candidate": candidate,
            "candidate_record_id": known(format!("candidate-{hash}")),
            "component_layer": "general",
            "localization": {"state": "localized", "instance_key": "synthetic-instance", "evidence": [proof()]},
            "cause_deduplication": {"state": "canonical"},
            "component": assessment("reported-confirmed"),
            "entrypoint_tcct": assessment("not-attempted"),
            "projection": assessment("reported-confirmed"),
            "attribution": {
                "state": "matched", "method": known("manual-cause-review"),
                "proposed_cause_id": known("cause-1"),
                "reason": "synthetic cause declaration", "evidence": [proof()]
            },
            "completion": "complete", "completion_reason": "synthetic review complete",
            "automated_review_seconds": unknown("not measured"),
            "human_review_seconds": unknown("not measured"),
            "duplicate_of": unknown("no previous row")
        }
    });
    record["reviews"].as_array_mut().unwrap().push(review);
}

fn complete_inventories(record: &mut Value) {
    let observations: Vec<Value> = record["reviews"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["observation"]["observation_id"].clone())
        .collect();
    let layer_ids = |layer: &str| -> Vec<Value> {
        record["reviews"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|row| row["observation"]["component_layer"] == layer)
            .map(|row| row["observation"]["observation_id"].clone())
            .collect()
    };
    let general_ids = layer_ids("general");
    let contract_ids = layer_ids("contract");
    let legacy_ids = layer_ids("legacy-unspecified");
    let semantics: Vec<Value> = observations
        .iter()
        .map(|id| {
            json!({
                "observation_id": id,
                "violation_kind": known("output-difference"),
                "violation_evidence": [proof()],
                "localization_method": known("synthetic-localization"),
                "localization_method_validated": unknown("not semantically validated"),
                "localization_evidence": [proof()]
            })
        })
        .collect();
    record["schema_version"] = json!(2);
    record["aggregation_metadata"] = json!({
        "candidate_inventory": coverage(true),
        "review_inventory": [
            {"layer": "component-general", "expected_observation_ids": general_ids, "coverage": coverage(true)},
            {"layer": "entrypoint-tcct", "expected_observation_ids": observations, "coverage": coverage(true)},
            {"layer": "component-contract", "expected_observation_ids": contract_ids, "coverage": coverage(true)},
            {"layer": "legacy-unspecified", "expected_observation_ids": legacy_ids, "coverage": coverage(true)}
        ],
        "review_semantics": semantics,
        "candidate_times": []
    });
}

fn time(record: &mut Value, hash: char, basis: &str, seconds: f64, clock: &str) {
    let value = json!({
        "candidate_sha256": hash.to_string().repeat(64),
        "run_id": record["execution"]["run_id"]["value"], "target_id": "synthetic-target",
        "campaign_id": "campaign-1", "clock_id": clock, "origin": "synthetic campaign start",
        "basis": basis, "basis_verified": true, "seconds": seconds, "evidence": [proof()]
    });
    record["aggregation_metadata"]["candidate_times"]
        .as_array_mut()
        .unwrap()
        .push(value);
}

fn campaign(records: &[Value]) -> Value {
    json!({
        "execution_unit_id": "synthetic-unit", "method": records[0]["context"]["method"],
        "campaign_id": "campaign-1", "repetition": "repeat-1",
        "record_ids": records.iter().map(|r| r["record_id"].clone()).collect::<Vec<_>>(),
        "coverage": coverage(true)
    })
}

fn registration(members: &[(&str, &str)]) -> Value {
    json!({
        "scope_id": "synthetic-project-at-version", "cause_id": "cause-1",
        "execution_unit_ids": ["synthetic-unit"], "source_versions": ["synthetic-version"],
        "members": members.iter().map(|(r, o)| json!({"record_id": r, "observation_id": o})).collect::<Vec<_>>(),
        "evidence": [proof()]
    })
}

fn aggregate(
    temp: &TempDir,
    records: &[Value],
    campaigns: Vec<Value>,
    registry: Vec<Value>,
) -> Value {
    let refs: Vec<Value> = records
        .iter()
        .enumerate()
        .map(|(i, value)| {
            write_json(
                &temp.path().join(format!("aggregate-input-{i}.json")),
                value,
            )
        })
        .collect();
    let before: Vec<Vec<u8>> = refs
        .iter()
        .map(|r| fs::read(r["path"].as_str().unwrap()).unwrap())
        .collect();
    let request = json!({"schema_version": 1, "records": refs, "campaigns": campaigns, "cause_registry": registry});
    let request_path = temp.path().join("aggregate-request.json");
    write_json(&request_path, &request);
    let output_path = temp.path().join("aggregate-output.json");
    let result = aggregate_records(&request_path, &output_path).unwrap();
    for (reference, bytes) in refs.iter().zip(before) {
        assert_eq!(
            fs::read(reference["path"].as_str().unwrap()).unwrap(),
            bytes
        );
    }
    let value = serde_json::to_value(result).unwrap();
    assert_eq!(
        value,
        serde_json::from_slice::<Value>(&fs::read(output_path).unwrap()).unwrap()
    );
    value
}

fn aggregate_error(temp: &TempDir, records: &[Value]) -> String {
    let refs: Vec<Value> = records
        .iter()
        .enumerate()
        .map(|(i, value)| write_json(&temp.path().join(format!("rejected-input-{i}.json")), value))
        .collect();
    let request_path = temp.path().join("rejected-request.json");
    write_json(
        &request_path,
        &json!({"schema_version": 1, "records": refs, "campaigns": [], "cause_registry": []}),
    );
    let output_path = temp.path().join("rejected-output.json");
    let error = aggregate_records(&request_path, &output_path).unwrap_err();
    assert!(!output_path.exists());
    format!("{error:#}")
}

fn groups(report: &Value, layer: &str) -> Vec<Value> {
    report["groups"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|group| group["layer"] == layer)
        .cloned()
        .collect()
}

fn general(report: &Value) -> Value {
    let groups = groups(report, "component-general");
    assert_eq!(groups.len(), 1, "{report:#}");
    groups[0].clone()
}

fn assert_unknown(value: &Value) {
    assert_eq!(value["state"], "unknown");
    assert!(!value["reason"].as_str().unwrap().trim().is_empty());
}

#[test]
fn legacy_empty_candidate_list_does_not_become_a_completed_negative() {
    let temp = TempDir::new().unwrap();
    let record = record(&temp, "r1", "whole");
    let report = aggregate(&temp, &[record], vec![], vec![]);
    let group = general(&report);
    assert_eq!(group["state"], "unknown-incomplete");
    assert_eq!(group["candidate_inventory_complete"], false);
    assert_eq!(group["confirmation_exists"], false);
    assert_unknown(&group["distinct_cause_count"]);
    assert_eq!(group["time"]["kind"], "unavailable");
}

#[test]
fn no_candidate_requires_record_and_campaign_inventory_evidence() {
    for complete_campaign in [false, true] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        // A finished search; bug_found without a reference is not absence.
        record["execution"]["backend_status"] = known("no_counterexample");
        complete_inventories(&mut record);
        let records = vec![record];
        let campaigns = if complete_campaign {
            vec![campaign(&records)]
        } else {
            vec![]
        };
        let report = aggregate(&temp, &records, campaigns, vec![]);
        let group = general(&report);
        assert_eq!(
            group["state"],
            if complete_campaign {
                "no-candidate"
            } else {
                "unknown-incomplete"
            }
        );
        assert_eq!(group["confirmation_exists"], false);
    }
}

#[test]
fn missing_expected_review_or_record_prevents_complete_negative() {
    for missing in ["review", "record"] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "split");
        add_review(&mut record, "o1", 'a');
        record["reviews"][0]["observation"]["component"] = assessment("rejected");
        complete_inventories(&mut record);
        let mut campaigns = vec![campaign(&[record.clone()])];
        if missing == "review" {
            record["aggregation_metadata"]["review_inventory"][0]["expected_observation_ids"] =
                json!(["o1", "absent-o2"]);
        } else {
            campaigns[0]["record_ids"] = json!(["r1", "absent-r2"]);
        }
        let report = aggregate(&temp, &[record], campaigns, vec![]);
        assert_eq!(general(&report)["state"], "unknown-incomplete");
    }
}

#[test]
fn terminal_unresolved_and_interrupted_reviews_are_never_negative() {
    for (state, completion) in [
        ("unresolved", "complete"),
        ("interrupted", "interrupted"),
        ("error", "failed"),
    ] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        add_review(&mut record, "o1", 'a');
        record["reviews"][0]["observation"]["component"] = assessment(state);
        record["reviews"][0]["observation"]["completion"] = json!(completion);
        complete_inventories(&mut record);
        let records = vec![record];
        let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
        let group = general(&report);
        assert_eq!(group["state"], "unknown-incomplete");
        assert_eq!(group["review_results_complete"], false);
        assert_eq!(group["unresolved_occurrences"].as_array().unwrap().len(), 1);
    }
}

#[test]
fn completed_rejection_requires_a_complete_candidate_review_inventory() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    add_review(&mut record, "o1", 'a');
    record["reviews"][0]["observation"]["component"] = assessment("rejected");
    complete_inventories(&mut record);
    let records = vec![record];
    let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
    assert_eq!(general(&report)["state"], "not-confirmed-complete");
}

#[test]
fn a_confirmed_occurrence_does_not_erase_remaining_unresolved_work() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "split");
    add_review(&mut record, "o1", 'a');
    add_review(&mut record, "o2", 'b');
    record["reviews"][1]["observation"]["component"] = assessment("unresolved");
    complete_inventories(&mut record);
    let records = vec![record];
    let report = aggregate(
        &temp,
        &records,
        vec![campaign(&records)],
        vec![registration(&[("r1", "o1")])],
    );
    let group = general(&report);
    assert_eq!(group["state"], "confirmed-attributed");
    assert_eq!(group["confirmation_exists"], true);
    assert_eq!(group["cause_count_complete"], false);
    assert_eq!(group["unresolved_occurrences"].as_array().unwrap().len(), 1);
}

#[test]
fn same_unit_id_with_settings_version_or_policy_conflict_keeps_both_records() {
    for field in ["settings", "version", "policy"] {
        let temp = TempDir::new().unwrap();
        let first = record(&temp, "r1", "whole");
        let mut second = record(&temp, "r2", "whole");
        match field {
            "settings" => second["context"]["settings_sha256"] = known("5".repeat(64)),
            "version" => second["context"]["source_version"] = known("different-version"),
            "policy" => second["policy_intent"]["unit_wall_budget_seconds"] = known(120),
            _ => unreachable!(),
        }
        let report = aggregate(&temp, &[first, second], vec![], vec![]);
        assert!(!report["conflicts"].as_array().unwrap().is_empty());
        let groups = groups(&report, "component-general");
        assert_eq!(groups.len(), 2);
        let mut retained: Vec<Value> = groups
            .iter()
            .flat_map(|g| g["record_ids"].as_array().unwrap().clone())
            .collect();
        retained.sort_by_key(|id| id.as_str().unwrap().to_owned());
        assert_eq!(retained, vec![json!("r1"), json!("r2")]);
    }
}

#[test]
fn unknown_campaign_or_repetition_is_not_a_shared_execution_identity() {
    for missing in ["campaign", "repetition"] {
        let temp = TempDir::new().unwrap();
        let mut records = vec![record(&temp, "r1", "whole"), record(&temp, "r2", "whole")];
        for record in &mut records {
            if missing == "campaign" {
                record["execution"]["campaign_id"] = unknown("legacy campaign unavailable");
            } else {
                record["context"]["repetition"] = unknown("legacy repetition unavailable");
                record["execution"]["source_repetition"] = unknown("legacy repetition unavailable");
            }
        }
        let report = aggregate(&temp, &records, vec![], vec![]);
        assert_eq!(groups(&report, "component-general").len(), 2);
    }
}

#[test]
fn methods_campaigns_and_repetitions_remain_separate() {
    let temp = TempDir::new().unwrap();
    let first = record(&temp, "r1", "whole");
    let second = record(&temp, "r2", "split");
    let mut third = record(&temp, "r3", "whole");
    third["execution"]["campaign_id"] = known("campaign-2");
    let mut fourth = record(&temp, "r4", "whole");
    fourth["context"]["repetition"] = known("repeat-2");
    fourth["execution"]["source_repetition"] = known("repeat-2");
    let report = aggregate(&temp, &[first, second, third, fourth], vec![], vec![]);
    assert_eq!(groups(&report, "component-general").len(), 4);
}

#[test]
fn forged_cause_links_and_backend_found_never_replace_review_evidence() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    record["component_cause_links"] = json!({"forged-cause": ["absent-observation"]});
    record["execution"]["backend_status"] = known("found");
    let report = aggregate(&temp, &[record], vec![], vec![]);
    let group = general(&report);
    assert_eq!(group["confirmation_exists"], false);
    assert_eq!(group["attributed_confirmation_exists"], false);
    assert!(group["registered_causes"].as_array().unwrap().is_empty());
}

#[test]
fn stored_true_binding_is_rechecked_against_run_target_and_candidate_inventory() {
    for mismatch in ["run", "target", "candidate"] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        add_review(&mut record, "o1", 'a');
        match mismatch {
            "run" => record["reviews"][0]["observation"]["run_id"] = json!("unrelated-run"),
            "target" => {
                record["reviews"][0]["observation"]["target_id"] = json!("unrelated-target")
            }
            "candidate" => {
                record["execution"]["candidates"] = json!([reference("other-candidate", 'b')])
            }
            _ => unreachable!(),
        }
        complete_inventories(&mut record);
        let records = vec![record];
        let report = aggregate(
            &temp,
            &records,
            vec![campaign(&records)],
            vec![registration(&[("r1", "o1")])],
        );
        let group = general(&report);
        assert_eq!(group["attributed_confirmation_exists"], false);
        assert_ne!(group["state"], "not-confirmed-complete");
        assert!(group["registered_causes"].as_array().unwrap().is_empty());
    }
}

#[test]
fn contract_and_legacy_layers_do_not_leak_into_general_confirmation() {
    for layer in ["contract", "legacy-unspecified"] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "split");
        add_review(&mut record, "o1", 'a');
        record["reviews"][0]["observation"]["component_layer"] = json!(layer);
        if layer == "legacy-unspecified" {
            // The preserved legacy Matched label supplies no independent cause
            // method; it must not be resurrected by the registry or link table.
            record["reviews"][0]["observation"]["attribution"]["method"] =
                unknown("legacy Matched was target binding only");
            record["reviews"][0]["observation"]["attribution"]["state"] = json!("unknown");
        }
        complete_inventories(&mut record);
        let report = aggregate(&temp, &[record], vec![], vec![]);
        assert_eq!(general(&report)["confirmation_exists"], false);
        assert_eq!(general(&report)["attributed_confirmation_exists"], false);
        let layer_key = if layer == "contract" {
            "component-contract"
        } else {
            "legacy-unspecified"
        };
        let other = groups(&report, layer_key);
        assert_eq!(other.len(), 1);
        assert_eq!(other[0]["confirmation_exists"], true);
        assert_unknown(&other[0]["distinct_cause_count"]);
    }
}

#[test]
fn binding_only_and_failed_projection_do_not_become_attributed_causes() {
    for failure in ["binding", "projection", "localization", "attribution"] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        add_review(&mut record, "o1", 'a');
        let observation = &mut record["reviews"][0]["observation"];
        match failure {
            "binding" => observation["attribution"]["method"] = known("KnownDefectSingleTarget"),
            "projection" => observation["projection"] = assessment("unresolved"),
            "localization" => {
                observation["localization"] =
                    json!({"state": "failed", "reason": "synthetic missing mapping"})
            }
            "attribution" => observation["attribution"]["state"] = json!("unknown"),
            _ => unreachable!(),
        }
        complete_inventories(&mut record);
        let records = vec![record];
        let report = aggregate(
            &temp,
            &records,
            vec![campaign(&records)],
            vec![registration(&[("r1", "o1")])],
        );
        let group = general(&report);
        assert_eq!(
            group["attributed_confirmation_exists"], false,
            "{failure}: {group:#}"
        );
        assert!(group["registered_causes"].as_array().unwrap().is_empty());
        assert_ne!(group["state"], "not-confirmed-complete");
        assert_unknown(&group["distinct_cause_count"]);
    }
}

#[test]
fn component_rejection_with_failed_or_unattempted_mapping_is_not_a_negative_unit() {
    for failure in [
        "not-attempted",
        "rejected",
        "error",
        "unresolved",
        "missing-localization",
        "split-root",
    ] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "split");
        add_review(&mut record, "o1", 'a');
        let o = &mut record["reviews"][0]["observation"];
        o["component"] = assessment("rejected");
        if failure == "missing-localization" {
            o["localization"] = json!({"state":"not-attempted","reason":"no mapping evidence"});
        } else if failure == "split-root" {
            o["localization"] = json!({"state":"root","evidence":[proof()]});
        } else {
            o["projection"] = assessment(failure);
        }
        complete_inventories(&mut record);
        let records = vec![record];
        let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
        let group = general(&report);
        assert_eq!(group["state"], "unknown-incomplete", "{failure}");
        assert_eq!(group["review_results_complete"], false);
        assert_unknown(&group["distinct_cause_count"]);
    }
}

#[test]
fn attributed_presence_does_not_invent_a_scoped_unique_cause_count() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    add_review(&mut record, "o1", 'a');
    complete_inventories(&mut record);
    let records = vec![record];
    let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
    let group = general(&report);
    assert_eq!(group["state"], "confirmed-attributed");
    assert_unknown(&group["distinct_cause_count"]);
    assert_eq!(group["cause_count_complete"], false);
}

#[test]
fn scoped_registered_cause_deduplicates_occurrences_without_dropping_them() {
    let temp = TempDir::new().unwrap();
    let mut first = record(&temp, "r1", "split");
    let mut second = record(&temp, "r2", "split");
    add_review(&mut first, "o1", 'a');
    add_review(&mut second, "o2", 'a');
    // Each record reports its own occurrence. The scoped registry, rather than
    // an invented cross-record string in the legacy duplicate_of field,
    // establishes their shared cause identity.
    complete_inventories(&mut first);
    complete_inventories(&mut second);
    let records = vec![first, second];
    let report = aggregate(
        &temp,
        &records,
        vec![campaign(&records)],
        vec![registration(&[("r1", "o1"), ("r2", "o2")])],
    );
    let group = general(&report);
    assert_eq!(group["distinct_cause_count"], known(1));
    assert_eq!(group["cause_count_complete"], true);
    assert_eq!(group["occurrences"].as_array().unwrap().len(), 2);
    assert_eq!(
        group["registered_causes"][0]["members"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
}

#[test]
fn the_same_candidate_cannot_gain_two_causes_from_different_registry_scopes() {
    let temp = TempDir::new().unwrap();
    let mut first = record(&temp, "r1", "whole");
    let mut second = record(&temp, "r2", "whole");
    add_review(&mut first, "o1", 'a');
    add_review(&mut second, "o2", 'a');
    complete_inventories(&mut first);
    complete_inventories(&mut second);
    let first_key = registration(&[("r1", "o1")]);
    let mut second_key = registration(&[("r2", "o2")]);
    second_key["scope_id"] = json!("different-scope-no-equivalence-evidence");
    let records = vec![first, second];
    let report = aggregate(
        &temp,
        &records,
        vec![campaign(&records)],
        vec![first_key, second_key],
    );
    let group = general(&report);
    assert_unknown(&group["distinct_cause_count"]);
    assert_eq!(group["cause_count_complete"], false);
    assert!(group.to_string().to_lowercase().contains("ambig"));
}

#[test]
fn empty_candidates_with_missing_declared_review_is_still_incomplete() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    complete_inventories(&mut record);
    record["aggregation_metadata"]["review_inventory"][0]["expected_observation_ids"] =
        json!(["missing-review-declared-by-inventory"]);
    let records = vec![record];
    let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
    let group = general(&report);
    assert_eq!(group["state"], "unknown-incomplete");
    assert_eq!(group["review_inventory_complete"], false);
}

#[test]
fn contradictory_reviews_preserve_positive_existence_and_unresolved_completeness() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    add_review(&mut record, "confirmed", 'a');
    add_review(&mut record, "rejected", 'a');
    record["reviews"][1]["observation"]["component"] = assessment("rejected");
    complete_inventories(&mut record);
    let records = vec![record];
    let report = aggregate(
        &temp,
        &records,
        vec![campaign(&records)],
        vec![registration(&[("r1", "confirmed")])],
    );
    let group = general(&report);
    assert_eq!(group["confirmation_exists"], true);
    assert_eq!(group["review_results_complete"], false);
    assert_eq!(group["cause_count_complete"], false);
    assert_unknown(&group["distinct_cause_count"]);
    assert_eq!(
        group["occurrences"][0]["review_refs"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
}

#[test]
fn conflicting_cause_ids_for_one_candidate_are_ambiguous_across_records() {
    let temp = TempDir::new().unwrap();
    let mut first = record(&temp, "r1", "whole");
    let mut second = record(&temp, "r2", "whole");
    add_review(&mut first, "o1", 'a');
    add_review(&mut second, "o2", 'a');
    second["reviews"][0]["observation"]["attribution"]["proposed_cause_id"] = known("cause-2");
    complete_inventories(&mut first);
    complete_inventories(&mut second);
    let records = vec![first, second];
    let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
    let group = general(&report);
    assert_eq!(group["confirmation_exists"], true);
    assert_eq!(group["attributed_confirmation_exists"], false);
    assert_unknown(&group["distinct_cause_count"]);
    assert_eq!(group["confirmed_unattributed"].as_array().unwrap().len(), 2);
    assert!(group.to_string().to_lowercase().contains("ambig"));
}

#[test]
fn entrypoint_tcct_is_separate_from_component_confirmation_and_cause_counts() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    add_review(&mut record, "o1", 'a');
    record["reviews"][0]["observation"]["component"] = assessment("unresolved");
    record["reviews"][0]["observation"]["entrypoint_tcct"] = assessment("reported-confirmed");
    record["reviews"][0]["observation"]["projection"] = assessment("unresolved");
    complete_inventories(&mut record);
    let records = vec![record];
    let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
    assert_eq!(general(&report)["state"], "unknown-incomplete");
    assert_eq!(general(&report)["confirmation_exists"], false);
    let tcct = groups(&report, "entrypoint-tcct");
    assert_eq!(tcct.len(), 1);
    assert_eq!(tcct[0]["state"], "confirmed-unattributed-only");
    assert_eq!(tcct[0]["attributed_confirmation_exists"], false);
    assert!(tcct[0]["registered_causes"].as_array().unwrap().is_empty());
}

#[test]
fn unlinked_v1_times_are_not_assigned_to_a_candidate() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    add_review(&mut record, "o1", 'a');
    record["execution"]["exact_candidate_time"] = known(1.0);
    record["execution"]["candidate_times"] = json!([{"seconds": known(1.0), "meaning": "claimed generation", "origin": "unknown origin"}]);
    let report = aggregate(&temp, &[record], vec![], vec![]);
    let group = general(&report);
    assert_eq!(group["time"]["kind"], "unavailable");
    assert_unknown(&group["time"]["seconds"]);
}

#[test]
fn exact_completion_and_log_time_claims_keep_distinct_meanings() {
    for (basis, expected) in [
        ("exact-generation", "exact-first"),
        ("completion-upper-bound", "completion-upper-bound"),
        ("log-observation", "observed-minimum"),
    ] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        add_review(&mut record, "o1", 'a');
        complete_inventories(&mut record);
        time(&mut record, 'a', basis, 9.0, "clock-1");
        let records = vec![record];
        let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
        let group = general(&report);
        assert_eq!(group["time"]["kind"], expected);
        assert_eq!(group["time"]["seconds"], known(9.0));
    }
}

#[test]
fn preceding_unresolved_candidate_blocks_an_exact_first_time() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "split");
    add_review(&mut record, "early", 'a');
    add_review(&mut record, "later", 'b');
    record["reviews"][0]["observation"]["component"] = assessment("unresolved");
    complete_inventories(&mut record);
    time(&mut record, 'a', "exact-generation", 5.0, "clock-1");
    time(&mut record, 'b', "exact-generation", 9.0, "clock-1");
    let records = vec![record];
    let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
    let group = general(&report);
    assert_eq!(group["time"]["kind"], "observed-minimum");
    assert_eq!(group["time"]["seconds"], known(9.0));
    assert!(!group["time"]["series"][0]["blockers"]
        .as_array()
        .unwrap()
        .is_empty());
}

#[test]
fn incomplete_candidate_inventory_blocks_first_even_with_one_confirmed_timestamp() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    add_review(&mut record, "o1", 'a');
    complete_inventories(&mut record);
    record["aggregation_metadata"]["candidate_inventory"] = coverage(false);
    time(&mut record, 'a', "exact-generation", 9.0, "clock-1");
    let records = vec![record];
    let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
    assert_eq!(general(&report)["time"]["kind"], "observed-minimum");
}

#[test]
fn incompatible_time_bases_or_clocks_are_reported_as_separate_series() {
    for differing in ["basis", "clock"] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        add_review(&mut record, "o1", 'a');
        add_review(&mut record, "o2", 'b');
        complete_inventories(&mut record);
        time(&mut record, 'a', "exact-generation", 3.0, "clock-1");
        time(
            &mut record,
            'b',
            if differing == "basis" {
                "completion-upper-bound"
            } else {
                "exact-generation"
            },
            8.0,
            if differing == "clock" {
                "clock-2"
            } else {
                "clock-1"
            },
        );
        let records = vec![record];
        let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
        let group = general(&report);
        assert_eq!(group["time"]["kind"], "unavailable");
        assert_unknown(&group["time"]["seconds"]);
        assert_eq!(group["time"]["series"].as_array().unwrap().len(), 2);
    }
}

#[test]
fn missing_candidate_binding_or_unverified_basis_cannot_supply_a_time() {
    for missing in ["candidate", "run", "campaign", "verification"] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        add_review(&mut record, "o1", 'a');
        complete_inventories(&mut record);
        time(&mut record, 'a', "exact-generation", 9.0, "clock-1");
        let stamp = &mut record["aggregation_metadata"]["candidate_times"][0];
        match missing {
            "candidate" => stamp["candidate_sha256"] = json!("b".repeat(64)),
            "run" => stamp["run_id"] = json!("other-run"),
            "campaign" => stamp["campaign_id"] = json!("other-campaign"),
            "verification" => stamp["basis_verified"] = json!(false),
            _ => unreachable!(),
        }
        let records = vec![record];
        let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
        let group = general(&report);
        assert_eq!(group["time"]["kind"], "unavailable");
        assert_unknown(&group["time"]["seconds"]);
    }
}

#[test]
fn aggregate_hash_pins_and_create_new_protect_original_metadata() {
    let temp = TempDir::new().unwrap();
    let record = record(&temp, "r1", "whole");
    let report = aggregate(&temp, &[record], vec![], vec![]);
    assert!(!report["limitations"].as_array().unwrap().is_empty());
    let request_path = temp.path().join("aggregate-request.json");
    let output_path = temp.path().join("aggregate-output.json");
    let output_before = fs::read(&output_path).unwrap();
    assert!(aggregate_records(&request_path, &output_path).is_err());
    assert_eq!(fs::read(&output_path).unwrap(), output_before);
    fs::write(temp.path().join("aggregate-input-0.json"), b"{}").unwrap();
    assert!(aggregate_records(&request_path, &temp.path().join("different-output.json")).is_err());
    assert!(!temp.path().join("different-output.json").exists());
}

#[test]
fn offline_aggregate_cli_accepts_only_metadata_and_writes_a_new_report() {
    let temp = TempDir::new().unwrap();
    let record = record(&temp, "r1", "whole");
    let input_path = temp.path().join("cli-record.json");
    let input = write_json(&input_path, &record);
    let input_before = fs::read(&input_path).unwrap();
    let request_path = temp.path().join("cli-request.json");
    write_json(
        &request_path,
        &json!({
            "schema_version": 1, "records": [input], "campaigns": [], "cause_registry": []
        }),
    );
    let output_path = temp.path().join("cli-output.json");
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_zkfDO"))
        .args(["experiment", "aggregate", "--request"])
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
    let report: Value = serde_json::from_slice(&fs::read(output_path).unwrap()).unwrap();
    assert_eq!(general(&report)["state"], "unknown-incomplete");
    assert_eq!(fs::read(input_path).unwrap(), input_before);
}

// Regressions for the offline aggregation errors N1–N7 found in the
// independent verification of 2026-10-01. Value-free metadata only.

#[test]
fn failed_unknown_or_reference_less_runs_are_not_completed_absence() {
    // bug_found without a candidate reference, then runs that did not finish a search.
    for status in [
        known("bug_found"),
        known("compile_error"),
        known("runtime_error"),
        known("parse_error"),
        known("spawn_error"),
        known("finished"),
        unknown("status absent"),
    ] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        record["execution"]["backend_status"] = status.clone();
        complete_inventories(&mut record);
        let records = vec![record];
        let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
        let group = general(&report);
        assert_eq!(group["state"], "unknown-incomplete", "{status}");
        assert_eq!(group["candidate_inventory_complete"], false);
        assert_eq!(group["cause_count_complete"], false);
        assert_unknown(&group["distinct_cause_count"]);
        assert!(group["reasons"]
            .as_array()
            .unwrap()
            .iter()
            .any(|reason| reason.as_str().unwrap().starts_with("r1: ")));
    }
    for status in ["no_counterexample", "timeout"] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        record["execution"]["backend_status"] = known(status);
        complete_inventories(&mut record);
        let records = vec![record];
        let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
        let group = general(&report);
        assert_eq!(group["state"], "no-candidate", "{status}");
        assert_eq!(group["distinct_cause_count"], known(0));
    }
}

#[test]
fn a_failed_attempt_keeps_its_campaign_incomplete() {
    let temp = TempDir::new().unwrap();
    let mut finished = record(&temp, "r1", "whole");
    add_review(&mut finished, "o1", 'a');
    finished["reviews"][0]["observation"]["component"] = assessment("rejected");
    complete_inventories(&mut finished);
    let mut failed = record(&temp, "r2", "whole");
    failed["execution"]["backend_status"] = known("runtime_error");
    complete_inventories(&mut failed);
    let records = vec![finished, failed];
    let report = aggregate(&temp, &records, vec![campaign(&records)], vec![]);
    let group = general(&report);
    assert_eq!(group["state"], "unknown-incomplete");
    assert_eq!(group["candidate_inventory_complete"], false);
    assert!(group["reasons"]
        .to_string()
        .contains("r2: backend status runtime_error"));
}

#[test]
fn records_that_confirm_and_reject_one_candidate_stay_unresolved() {
    for same_run in [true, false] {
        let temp = TempDir::new().unwrap();
        let mut confirming = record(&temp, "x", "whole");
        let mut rejecting = record(&temp, "y", "whole");
        if same_run {
            // A later annotation of the same run under a new record ID.
            confirming["execution"]["run_id"] = known("run-shared");
            rejecting["execution"]["run_id"] = known("run-shared");
        }
        add_review(&mut confirming, "ox", 'a');
        add_review(&mut rejecting, "oy", 'a');
        let o = &mut rejecting["reviews"][0]["observation"];
        o["component"] = assessment("rejected");
        o["attribution"]["state"] = json!("not-matched");
        complete_inventories(&mut confirming);
        complete_inventories(&mut rejecting);
        let records = vec![confirming, rejecting];
        let report = aggregate(
            &temp,
            &records,
            vec![campaign(&records)],
            vec![registration(&[("x", "ox")])],
        );
        let group = general(&report);
        assert_eq!(group["state"], "confirmed-attributed", "{same_run}");
        assert_eq!(group["review_results_complete"], false);
        assert_eq!(group["cause_count_complete"], false);
        assert_unknown(&group["distinct_cause_count"]);
        assert_eq!(group["unresolved_occurrences"].as_array().unwrap().len(), 2);
        assert!(group["reasons"]
            .to_string()
            .contains("confirmed in records [x], rejected in records [y]"));
    }
    // Agreeing annotations of the same run remain complete and deduplicated.
    let temp = TempDir::new().unwrap();
    let mut first = record(&temp, "x", "whole");
    let mut second = record(&temp, "y", "whole");
    first["execution"]["run_id"] = known("run-shared");
    second["execution"]["run_id"] = known("run-shared");
    add_review(&mut first, "ox", 'a');
    add_review(&mut second, "oy", 'a');
    complete_inventories(&mut first);
    complete_inventories(&mut second);
    let records = vec![first, second];
    let report = aggregate(
        &temp,
        &records,
        vec![campaign(&records)],
        vec![registration(&[("x", "ox"), ("y", "oy")])],
    );
    let group = general(&report);
    assert_eq!(group["review_results_complete"], true);
    assert_eq!(group["distinct_cause_count"], known(1));
    assert_eq!(group["occurrences"].as_array().unwrap().len(), 2);
}

#[test]
fn overlapping_registry_scopes_do_not_count_causes_as_distinct() {
    for second_cause in ["cause-1", "cause-2"] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        add_review(&mut record, "o1", 'a');
        add_review(&mut record, "o2", 'b');
        record["reviews"][1]["observation"]["attribution"]["proposed_cause_id"] =
            known(second_cause);
        complete_inventories(&mut record);
        let first = registration(&[("r1", "o1")]);
        let mut second = registration(&[("r1", "o2")]);
        second["scope_id"] = json!("overlapping-scope-same-unit-and-version");
        second["cause_id"] = json!(second_cause);
        let records = vec![record];
        let report = aggregate(
            &temp,
            &records,
            vec![campaign(&records)],
            vec![first, second],
        );
        let group = general(&report);
        assert_eq!(group["attributed_confirmation_exists"], true);
        assert_eq!(group["cause_count_complete"], false, "{second_cause}");
        assert_unknown(&group["distinct_cause_count"]);
        assert!(group["reasons"]
            .to_string()
            .contains("overlapping registry scopes"));
    }
    // Distinct cause IDs registered in one scope stay countable.
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    add_review(&mut record, "o1", 'a');
    add_review(&mut record, "o2", 'b');
    record["reviews"][1]["observation"]["attribution"]["proposed_cause_id"] = known("cause-2");
    complete_inventories(&mut record);
    let first = registration(&[("r1", "o1")]);
    let mut second = registration(&[("r1", "o2")]);
    second["cause_id"] = json!("cause-2");
    let records = vec![record];
    let report = aggregate(
        &temp,
        &records,
        vec![campaign(&records)],
        vec![first, second],
    );
    let group = general(&report);
    assert_eq!(group["cause_count_complete"], true);
    assert_eq!(group["distinct_cause_count"], known(2));
}

#[test]
fn tool_specific_checks_are_not_counted_as_general_tcct_causes() {
    for (kind, attributed) in [
        ("tool-specific-check", false),
        ("computation-abort", true),
        ("output-difference", true),
    ] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        add_review(&mut record, "o1", 'a');
        complete_inventories(&mut record);
        record["aggregation_metadata"]["review_semantics"][0]["violation_kind"] = known(kind);
        let records = vec![record];
        let report = aggregate(
            &temp,
            &records,
            vec![campaign(&records)],
            vec![registration(&[("r1", "o1")])],
        );
        let group = general(&report);
        assert_eq!(group["confirmation_exists"], true, "{kind}");
        assert_eq!(
            group["attributed_confirmation_exists"], attributed,
            "{kind}"
        );
        if attributed {
            assert_eq!(group["distinct_cause_count"], known(1));
        } else {
            assert_eq!(group["state"], "confirmed-unattributed-only");
            assert_unknown(&group["distinct_cause_count"]);
            assert!(group["occurrences"][0]["reasons"]
                .to_string()
                .contains("tool-specific-check"));
        }
    }
}

#[test]
fn cause_claims_on_one_candidate_conflict_across_component_layers() {
    for (contract_cause, ambiguous) in [("cause-2", true), ("cause-1", false)] {
        let temp = TempDir::new().unwrap();
        let mut record = record(&temp, "r1", "whole");
        add_review(&mut record, "general", 'a');
        add_review(&mut record, "contract", 'a');
        let o = &mut record["reviews"][1]["observation"];
        o["component_layer"] = json!("contract");
        o["attribution"]["proposed_cause_id"] = known(contract_cause);
        complete_inventories(&mut record);
        let records = vec![record];
        let report = aggregate(
            &temp,
            &records,
            vec![campaign(&records)],
            vec![registration(&[("r1", "general")])],
        );
        let group = general(&report);
        assert_eq!(group["confirmation_exists"], true);
        assert_eq!(
            group["attributed_confirmation_exists"], !ambiguous,
            "{contract_cause}"
        );
        if ambiguous {
            assert_unknown(&group["distinct_cause_count"]);
            assert!(group.to_string().to_lowercase().contains("ambig"));
        } else {
            assert_eq!(group["distinct_cause_count"], known(1));
        }
    }
}

#[test]
fn a_validated_localization_claim_without_a_validation_record_is_rejected() {
    let temp = TempDir::new().unwrap();
    let mut record = record(&temp, "r1", "whole");
    add_review(&mut record, "o1", 'a');
    complete_inventories(&mut record);
    record["aggregation_metadata"]["review_semantics"][0]["localization_method_validated"] =
        known(true);
    let error = aggregate_error(&temp, &[record]);
    assert!(error.contains("validation record"), "{error}");
}
