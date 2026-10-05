//! Runs `experiment lift` on every synthetic lifting fixture request and honest control.
//! Unimplemented inversion targets may match a narrowly pinned pending snapshot, reported
//! separately from target passes. Requires circom, node, and snarkjs; missing tools fail.

use std::{collections::BTreeMap, fs, path::Path};

use assert_cmd::Command;
use serde_json::{json, Value};

fn class_values(result: &Value, field: &str) -> BTreeMap<String, String> {
    result["classes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|class| {
            (
                class["representative"].as_str().unwrap().to_owned(),
                class[field].as_str().unwrap().to_owned(),
            )
        })
        .collect()
}

fn expected_values(value: &Value) -> BTreeMap<String, String> {
    value
        .as_object()
        .unwrap()
        .iter()
        .map(|(site, value)| (site.clone(), value.as_str().unwrap().to_owned()))
        .collect()
}

/// Empty site maps alone are insufficient: preparation must also match. Reason maps,
/// when specified, pin every class so an unrelated unknown cannot pass a pending case.
fn mismatch(result: &Value, expected: &Value) -> Option<String> {
    let default_preparation = json!({"status": "ok", "reason": null});
    let preparation = expected.get("preparation").unwrap_or(&default_preparation);
    if result["preparation"]["status"] != preparation["status"]
        || result["preparation"]["reason"] != preparation["reason"]
    {
        return Some(format!(
            "preparation {:?}, expected {preparation}",
            result["preparation"]
        ));
    }
    if preparation["status"] == "not_tcct_deviation"
        && (result["component"]["honest_generation"] != "ok"
            || result["component"]["deviated_signals"] != 0
            || result["component"]["candidate_satisfies_component_o0"] != true)
    {
        return Some("non-deviation control lacks an equal, valid honest component witness".into());
    }
    if result["sites_found"] != expected["sites_found"]
        || class_values(result, "verdict") != expected_values(&expected["sites"])
    {
        return Some(format!(
            "got {:?} ({} sites), expected {} ({} sites)",
            class_values(result, "verdict"),
            result["sites_found"],
            expected["sites"],
            expected["sites_found"]
        ));
    }
    for field in ["property", "component_classification"] {
        if let Some(value) = expected.get(field) {
            if &result[field] != value {
                return Some(format!("{field} {}, expected {value}", result[field]));
            }
        }
    }
    if let Some(reasons) = expected.get("reasons") {
        if class_values(result, "reason") != expected_values(reasons) {
            return Some(format!(
                "reasons {:?}, expected {reasons}",
                class_values(result, "reason")
            ));
        }
    }
    None
}

fn pending_snapshot<'a>(fixture: &str, expected: &'a Value) -> Option<&'a Value> {
    let pending = expected.get("pending_engine")?;
    assert!(
        matches!(fixture, "linear_inversion" | "bitdecomp_inversion"),
        "pending snapshots are not allowed for {fixture}"
    );
    assert!(
        pending["capability"]
            .as_str()
            .is_some_and(|s| !s.is_empty()),
        "pending capability must be explained"
    );
    assert_eq!(
        pending["preparation"],
        json!({"status": "ok", "reason": null}),
        "a preparation failure is not a pending inversion result"
    );
    assert_eq!(pending["sites"], json!({"main.child": "unknown"}));
    assert_eq!(pending["sites_found"], json!(1));
    let reason = match fixture {
        "linear_inversion" => "input_requires_inversion",
        "bitdecomp_inversion" => "synthesis_local_unsat",
        "range_unreachable_intermediate" => "synthesis_local_unsat",
        _ => unreachable!(),
    };
    assert_eq!(pending["reasons"], json!({"main.child": reason}));
    if fixture == "range_unreachable_intermediate" {
        assert_eq!(
            pending["observed_reason_versions"],
            json!(["synthesis_local_unsat", "synthesis_cone_unsat"])
        );
    } else {
        assert!(pending.get("observed_reason_versions").is_none());
    }
    Some(pending)
}

fn pending_matches(result: &Value, baseline: &Value) -> bool {
    let mut versioned = baseline.clone();
    if let Some(versions) = baseline.get("observed_reason_versions") {
        let reasons = class_values(result, "reason");
        if reasons.len() != 1
            || !reasons
                .get("main.child")
                .is_some_and(|reason| versions.as_array().unwrap().contains(&json!(reason)))
        {
            return false;
        }
        versioned["reasons"] = json!(reasons);
    }
    mismatch(result, &versioned).is_none()
}

#[test]
fn lifting_engine_matches_fixture_expectations() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/lifting");
    let output = tempfile::tempdir().unwrap();
    let mut target_passed = 0;
    let mut pending_count = 0;
    let mut evaluated = 0;
    let mut mismatches = Vec::new();
    let mut entries = fs::read_dir(&root)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| path.is_dir())
        .collect::<Vec<_>>();
    entries.sort();
    for fixture in entries {
        let fixture_name = fixture.file_name().unwrap().to_str().unwrap();
        let expected: Value =
            serde_json::from_slice(&fs::read(fixture.join("expected.json")).unwrap()).unwrap();
        let engine_version = fixture.join("expected.engine-v2.json");
        let engine_target: Value = if engine_version.is_file() {
            serde_json::from_slice(&fs::read(engine_version).unwrap()).unwrap()
        } else {
            expected.clone()
        };
        // Preserve the earlier control verdicts as history when the engine
        // introduces an explicit pre-lifting non-deviation status.
        // L-03 judges honest controls for the input-assumption property (control-v3).
        let control_version = ["expected.control-v3.json", "expected.control-v2.json"]
            .into_iter()
            .map(|name| fixture.join(name))
            .find(|path| path.is_file());
        let control: Value = match control_version {
            Some(path) => serde_json::from_slice(&fs::read(path).unwrap()).unwrap(),
            None => expected["control"].clone(),
        };
        let pending = pending_snapshot(fixture_name, &expected);
        for (request, target) in [
            ("request.json", &engine_target),
            ("control_request.json", &control),
        ] {
            if !fixture.join(request).exists() {
                continue;
            }
            let name = format!("{fixture_name}-{request}");
            let directory = output.path().join(&name);
            Command::cargo_bin("zkfDO")
                .unwrap()
                .args(["experiment", "lift", "--request"])
                .arg(fixture.join(request))
                .arg("--output")
                .arg(&directory)
                .assert()
                .success();
            let result: Value =
                serde_json::from_slice(&fs::read(directory.join("result.json")).unwrap()).unwrap();
            evaluated += 1;
            match mismatch(&result, target) {
                None => target_passed += 1,
                Some(target_mismatch) => {
                    let baseline_matches = request == "request.json"
                        && pending.is_some_and(|baseline| pending_matches(&result, baseline));
                    if baseline_matches {
                        pending_count += 1;
                        println!(
                            "PENDING {name}: target not met; {target_mismatch}; reasons {:?}",
                            class_values(&result, "reason")
                        );
                    } else {
                        mismatches.push(format!(
                            "{name}: {target_mismatch}; actual reasons {:?}",
                            class_values(&result, "reason")
                        ));
                    }
                }
            }
        }
    }
    println!(
        "Lifting engine: {target_passed} target matches, {pending_count} PENDING snapshots, \
         {} mismatches across {evaluated} requests",
        mismatches.len()
    );
    assert!(
        evaluated >= 18,
        "only {evaluated} fixture requests were found"
    );
    assert!(mismatches.is_empty(), "{}", mismatches.join("\n"));
}

#[test]
fn empty_sites_require_the_expected_preparation_status_and_reason() {
    let expected = json!({
        "sites": {}, "sites_found": 0,
        "preparation": {"status": "preparation_failure", "reason": "no_call_site"}
    });
    let result = json!({
        "classes": [], "sites_found": 0,
        "preparation": {"status": "preparation_failure", "reason": "no_call_site"}
    });
    assert!(mismatch(&result, &expected).is_none());
    let mut incorrect = result.clone();
    incorrect["preparation"]["reason"] = json!("component_compile_failed");
    assert!(mismatch(&incorrect, &expected).is_some());
    incorrect = result.clone();
    incorrect["preparation"]["status"] = json!("ok");
    assert!(mismatch(&incorrect, &expected).is_some());
    let default_ok = json!({"sites": {}, "sites_found": 0});
    assert!(mismatch(&result, &default_ok).is_some());
}

#[test]
fn pending_unknown_requires_the_exact_reason_and_successful_preparation() {
    let baseline = json!({
        "sites": {"main.child": "unknown"}, "sites_found": 1,
        "reasons": {"main.child": "input_requires_inversion"},
        "preparation": {"status": "ok", "reason": null}
    });
    let mut result = json!({
        "classes": [{"representative": "main.child", "verdict": "unknown",
                     "reason": "input_requires_inversion"}],
        "sites_found": 1, "preparation": {"status": "ok", "reason": null}
    });
    assert!(mismatch(&result, &baseline).is_none());
    result["classes"][0]["reason"] = json!("other_unknown");
    assert!(mismatch(&result, &baseline).is_some());
    result["classes"][0]["reason"] = json!("input_requires_inversion");
    result["preparation"]["status"] = json!("preparation_failure");
    assert!(mismatch(&result, &baseline).is_some());
    let mut versioned = baseline.clone();
    versioned["observed_reason_versions"] =
        json!(["synthesis_local_unsat", "synthesis_cone_unsat"]);
    result["preparation"]["status"] = json!("ok");
    for reason in ["synthesis_local_unsat", "synthesis_cone_unsat"] {
        result["classes"][0]["reason"] = json!(reason);
        assert!(pending_matches(&result, &versioned));
    }
    result["classes"][0]["reason"] = json!("synthesis_solver_error");
    assert!(!pending_matches(&result, &versioned));
}

#[test]
fn non_deviation_control_requires_a_valid_equal_component_witness() {
    let expected = json!({"sites": {}, "sites_found": 0, "preparation": {
        "status": "not_tcct_deviation", "reason": "component_equals_honest"
    }});
    let mut result = json!({"classes": [], "sites_found": 0,
        "preparation": expected["preparation"],
        "component": {"honest_generation": "ok", "deviated_signals": 0,
            "candidate_satisfies_component_o0": true}
    });
    assert!(mismatch(&result, &expected).is_none());
    result["component"]["deviated_signals"] = json!(1);
    assert!(mismatch(&result, &expected).is_some());
    result["component"]["deviated_signals"] = json!(0);
    result["component"]["candidate_satisfies_component_o0"] = Value::Null;
    assert!(mismatch(&result, &expected).is_some());
}
