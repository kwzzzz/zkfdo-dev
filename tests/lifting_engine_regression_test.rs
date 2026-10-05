//! Engine regressions (L-02 to L-04) that need no fixture expectations file. Requires circom,
//! node, snarkjs, and z3 on PATH.

use std::{fs, path::Path};

use assert_cmd::Command;
use serde_json::Value;

fn lift(fixture: &str) -> Value {
    lift_in("tests/fixtures/lifting_engine", fixture)
}

fn lift_in(directory: &str, fixture: &str) -> Value {
    let fixture = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(directory)
        .join(fixture);
    let output = tempfile::tempdir().unwrap();
    let directory = output.path().join("result");
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args(["experiment", "lift", "--request"])
        .arg(fixture.join("request.json"))
        .arg("--output")
        .arg(&directory)
        .assert()
        .success();
    serde_json::from_slice(&fs::read(directory.join("result.json")).unwrap()).unwrap()
}

/// L-04 step 3: the 8-bit range of the caller's bit decomposition refutes the candidate's
/// site input (300) without enumerating bits, and the evidence names the decomposition.
#[test]
fn bit_decomposition_range_excludes_out_of_range_intermediate() {
    let result = lift_in("tests/fixtures/lifting", "range_unreachable_intermediate");
    let class = &result["classes"][0];
    assert_eq!(class["verdict"], "excluded_in_context", "{result}");
    assert_eq!(
        class["evidence"]["exclusion_method"],
        "bit_decomposition_interval"
    );
    assert!(class["evidence"]["excluded_by"]
        .as_str()
        .unwrap()
        .contains("8-bit decomposition"));
}

/// L-04 step 4: the site input is the remainder of an unconstrained `<--` division hint,
/// which the honest computation keeps below 4. The solver's model (r = 100) satisfies the
/// constraints but no entrypoint input reproduces it, so the engine injects the model's
/// values into the hint, and the witness still has to satisfy the original R1CS in both
/// checkers.
#[test]
fn hint_injection_reaches_a_site_the_honest_hints_never_compute() {
    let result = lift("hint_injection");
    assert_eq!(result["property"], "input_assumption", "{result}");
    let class = &result["classes"][0];
    assert_eq!(class["verdict"], "assumption_input_reachable", "{result}");
    assert_eq!(class["synthesis"]["reached_with"], "hint_injection");
    assert_eq!(class["rust_unsatisfied"], 0);
    assert_eq!(class["snarkjs"], "correct");
    assert!(class["exceptions"][0]
        .as_str()
        .unwrap()
        .starts_with("hint_injection: 2 rewritten statements"));
}

/// Counter-control for the closed-cone promotion: the same 8-bit range circuit as
/// `range_unreachable_intermediate`, but the candidate's site input (200) fits the range,
/// so the cone is satisfiable and the site must not be excluded.
#[test]
fn in_range_intermediate_is_not_excluded() {
    let result = lift("range_in_bounds");
    let classes = result["classes"].as_array().unwrap();
    assert_eq!(classes.len(), 1, "{result}");
    assert_eq!(result["property"], "tcct");
    assert_ne!(classes[0]["verdict"], "excluded_in_context", "{result}");
}

/// A caller constraint (`flag.success === 1`) rules out the candidate's all-zero assignment.
/// The refutation fixes every main input and the candidate's site signals, and the site
/// input is bound directly to a main input, so the site is excluded.
#[test]
fn caller_constraint_excludes_candidate_site_signals() {
    let fixture = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/lifting_engine/site_signal_refutation");
    let output = tempfile::tempdir().unwrap();
    let directory = output.path().join("result");
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args(["experiment", "lift", "--request"])
        .arg(fixture.join("request.json"))
        .arg("--output")
        .arg(&directory)
        .assert()
        .success();
    let result: Value =
        serde_json::from_slice(&fs::read(directory.join("result.json")).unwrap()).unwrap();
    let classes = result["classes"].as_array().unwrap();
    assert_eq!(classes.len(), 1, "{result}");
    assert_eq!(classes[0]["representative"], "main.flag");
    assert_eq!(classes[0]["deviated_generation"], "aborted");
    assert_eq!(classes[0]["verdict"], "excluded_in_context");
    assert_eq!(classes[0]["reason"], "local_constraint_refutation");
    assert!(classes[0]["evidence"]["excluded_by"]
        .as_str()
        .unwrap()
        .contains("candidate site signals fixed"));
}

/// L-05 steps 1-2: the candidate equals the honest comparator, whose 8-bit `LessThan` wraps
/// on `a = p - 1`. Step 1 names the broken instance. The caller range-checks both inputs to
/// 8 bits, so the predicate (out differs from the integer comparison) is excluded with
/// nothing fixed, using only implied range facts.
#[test]
fn caller_range_checks_exclude_the_broken_comparison() {
    let result = lift("lessthan_excluded");
    assert_eq!(
        result["violated_condition"]["kind"], "lessthan_semantic",
        "{result}"
    );
    assert_eq!(
        result["violated_condition"]["broken"][0]["instance"],
        "main.c"
    );
    let class = &result["classes"][0];
    assert_eq!(class["verdict"], "excluded_in_context", "{result}");
    assert_eq!(
        class["assumption_predicate_verdict"],
        "assumption_excluded_in_context"
    );
    assert_eq!(class["semantic_deviation_observed"], false);
    let predicate = &class["predicates"][0];
    assert_eq!(predicate["instance"], "main.cmp.c");
    assert_eq!(predicate["method"], "z3_cone_with_range_facts");
}

/// Without range checks the candidate's own witness reaches the site, and the predicate
/// holds on it: a semantic deviation is observed.
#[test]
fn unchecked_inputs_reach_the_broken_comparison() {
    let result = lift("lessthan_reachable");
    let class = &result["classes"][0];
    assert_eq!(class["verdict"], "assumption_input_reachable", "{result}");
    assert_eq!(
        class["assumption_predicate_verdict"],
        "assumption_violation_reachable"
    );
    assert_eq!(class["semantic_deviation_observed"], true);
    let predicate = &class["predicates"][0];
    assert_eq!(predicate["method"], "candidate_witness");
    assert_eq!(predicate["o0_o1_agree"], true);
}

/// The candidate's exact values are excluded (the second input is the constant 5), but the
/// predicate is still reachable with other values: the search finds a witness, which passes
/// both checkers.
#[test]
fn predicate_search_reaches_a_violation_the_candidate_values_cannot() {
    let result = lift("lessthan_search");
    let class = &result["classes"][0];
    assert_eq!(class["verdict"], "excluded_in_context", "{result}");
    assert_eq!(class["reason"], "constant_input_mismatch");
    assert_eq!(
        class["assumption_predicate_verdict"],
        "assumption_violation_reachable"
    );
    let predicate = &class["predicates"][0];
    assert_eq!(
        predicate["reason"], "predicate_holds_on_found_witness",
        "{result}"
    );
    assert_eq!(predicate["rust_unsatisfied"], 0);
    assert_eq!(predicate["snarkjs"], "correct");
    assert_eq!(predicate["search"]["changed_inputs"][0], "x");
}

/// L-05 step 3: the reference input aborts on a 4-bit check of a hint quotient. The
/// diagnostic copy blanks the check, its witness names the failing instance by the
/// unsatisfied O0 constraint, and re-chosen hints (q = 15 or less, r unchecked) give a witness
/// that satisfies the original R1CS in both checkers.
#[test]
fn an_aborting_range_check_is_located_and_repaired() {
    let result = lift("abort_repair");
    let class = &result["classes"][0];
    assert_eq!(class["verdict"], "assumption_input_reachable", "{result}");
    assert_eq!(class["input_origin"], "repaired_hint_injection");
    assert_eq!(class["rust_unsatisfied"], 0);
    assert_eq!(class["snarkjs"], "correct");
    let repair = &class["synthesis"]["repair"];
    assert_eq!(repair["outcome"], "reached");
    let located = &repair["localizations"][0];
    assert_eq!(located["blanked_checks"][0]["kind"], "constraint");
    assert_eq!(located["failing_instances"][0]["representative"], "main.rq");
    assert_eq!(
        result["violated_condition"]["kind"],
        "condition_not_reconstructed"
    );
}

/// L-06: with `--cache`, the repair compiles (diagnostic copies, injected generators) of a
/// second identical lift are cache hits and the result is the same apart from costs.
#[test]
fn repair_compiles_are_reused_from_the_cache() {
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/lifting_engine/abort_repair");
    let output = tempfile::tempdir().unwrap();
    let cache = output.path().join("cache");
    let run = |name: &str| -> Value {
        let directory = output.path().join(name);
        Command::cargo_bin("zkfDO")
            .unwrap()
            .args(["experiment", "lift", "--request"])
            .arg(fixture.join("request.json"))
            .arg("--output")
            .arg(&directory)
            .arg("--cache")
            .arg(&cache)
            .assert()
            .success();
        serde_json::from_slice(&fs::read(directory.join("result.json")).unwrap()).unwrap()
    };
    let repair_steps = |result: &Value| -> Vec<(String, bool)> {
        result["costs"]["steps"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|step| {
                let label = step["label"].as_str().unwrap();
                label.starts_with("compile diagnostic copy")
                    || label.starts_with("compile injected generator")
            })
            .map(|step| {
                (
                    step["label"].as_str().unwrap().to_owned(),
                    step["cached"].as_bool().unwrap(),
                )
            })
            .collect()
    };
    let (mut first, mut second) = (run("first"), run("second"));
    let (cold, warm) = (repair_steps(&first), repair_steps(&second));
    assert!(
        !cold.is_empty() && cold.iter().all(|(_, cached)| !cached),
        "{cold:?}"
    );
    assert_eq!(cold.len(), warm.len());
    assert!(
        warm.iter()
            .all(|(label, cached)| *cached && label.ends_with("(cache hit)")),
        "{warm:?}"
    );
    assert!(fs::read_dir(cache.join("edits")).unwrap().count() > 0);
    for result in [&mut first, &mut second] {
        result.as_object_mut().unwrap().remove("costs");
    }
    assert_eq!(first, second);
}

/// L-07: the sum of two 8-bit inputs reaches the comparator; its interval follows from the
/// decompositions through the linear constraint and proves that the comparison cannot wrap.
#[test]
fn linear_range_propagation_excludes_a_sum_of_checked_inputs() {
    let result = lift("lessthan_propagation");
    let predicate = &result["classes"][0]["predicates"][0];
    assert_eq!(
        predicate["verdict"], "assumption_excluded_in_context",
        "{result}"
    );
    assert_eq!(predicate["method"], "z3_cone_with_range_facts");
    assert_ne!(
        predicate["evidence"]["linear_propagation_constraints_used"],
        "[]"
    );
}

/// L-07: a component with the fix applied rejects the candidate (its honest computation
/// aborts), so no broken instance is known; the component's comparators are judged anyway.
#[test]
fn a_fixed_component_still_gets_its_comparators_judged() {
    let result = lift("lessthan_fixed_component");
    assert!(result["violated_condition"].is_null(), "{result}");
    let class = &result["classes"][0];
    assert_eq!(
        class["assumption_predicate_verdict"],
        "assumption_excluded_in_context"
    );
    let predicate = &class["predicates"][0];
    assert_eq!(predicate["instance"], "main.cmp.c");
    assert_eq!(predicate["target_basis"], "component_lessthan_instances");
}

/// L-07: a reach records which top-level inputs differ from the base input, split by the
/// entrypoint's public inputs.
#[test]
fn reaches_record_public_and_private_input_changes() {
    let private = lift("lessthan_private");
    let reach = &private["classes"][0]["predicates"][0]["reach_inputs"];
    assert_eq!(reach["classification"], "private_only", "{private}");
    assert_eq!(reach["public_changed_count"], 0);
    assert!(reach["private_changed_count"].as_u64().unwrap() > 0);
    let public = lift("lessthan_search");
    let reach = &public["classes"][0]["predicates"][0]["reach_inputs"];
    assert_eq!(reach["classification"], "public_inputs_changed", "{public}");
    assert_eq!(reach["public_changed"][0], "x");
}

/// L-07: with an instance store the second request on the same entrypoint reuses the proved
/// verdict without searching, and `lift-instances` joins both into one instance row.
#[test]
fn instance_verdicts_are_shared_across_requests() {
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/lifting_engine/lessthan_search");
    let output = tempfile::tempdir().unwrap();
    let store = output.path().join("store");
    let run = |name: &str| -> Value {
        let directory = output.path().join(name);
        Command::cargo_bin("zkfDO")
            .unwrap()
            .args(["experiment", "lift", "--request"])
            .arg(fixture.join("request.json"))
            .arg("--output")
            .arg(&directory)
            .arg("--instance-store")
            .arg(&store)
            .assert()
            .success();
        serde_json::from_slice(&fs::read(directory.join("result.json")).unwrap()).unwrap()
    };
    let (first, second) = (run("first"), run("second"));
    let found = &first["classes"][0]["predicates"][0];
    assert_eq!(
        found["reason"], "predicate_holds_on_found_witness",
        "{first}"
    );
    let shared = &second["classes"][0]["predicates"][0];
    assert_eq!(
        shared["verdict"], "assumption_violation_reachable",
        "{second}"
    );
    assert_eq!(shared["reason"], "instance_verdict_shared");
    assert_eq!(shared["shared_from"], "lessthan_search");
    assert!(shared["search"].is_null());
    assert_eq!(shared["reach_inputs"], found["reach_inputs"]);
    let joined = output.path().join("instances.json");
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args(["experiment", "lift-instances", "--result"])
        .arg(output.path().join("first/result.json"))
        .arg(output.path().join("second/result.json"))
        .arg("--output")
        .arg(&joined)
        .assert()
        .success();
    let joined: Value = serde_json::from_slice(&fs::read(&joined).unwrap()).unwrap();
    assert_eq!(joined["instances"].as_array().unwrap().len(), 1);
    assert_eq!(
        joined["instances"][0]["verdict"],
        "assumption_violation_reachable"
    );
    assert_eq!(
        joined["instances"][0]["reach_classification"],
        "public_inputs_changed"
    );
    assert_eq!(joined["conflicts"], 0);
    assert_eq!(joined["changed_by_sharing"], 0);
}
