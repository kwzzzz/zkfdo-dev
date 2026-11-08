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

/// A damaged v2 proof must trigger fresh checking, even when the entry/instance match.
#[test]
fn corrupted_instance_proof_is_not_shared() {
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/lifting_engine/lessthan_search");
    let temp = tempfile::tempdir().unwrap();
    let store = temp.path().join("store");
    let run = |name: &str| -> Value {
        let output = temp.path().join(name);
        Command::cargo_bin("zkfDO")
            .unwrap()
            .args(["experiment", "lift", "--request"])
            .arg(fixture.join("request.json"))
            .arg("--output")
            .arg(&output)
            .arg("--instance-store")
            .arg(&store)
            .assert()
            .success();
        serde_json::from_slice(&fs::read(output.join("result.json")).unwrap()).unwrap()
    };
    let first = run("first");
    assert_eq!(
        first["classes"][0]["predicates"][0]["verdict"],
        "assumption_violation_reachable"
    );
    let proof = fs::read_dir(&store)
        .unwrap()
        .map(|p| p.unwrap().path())
        .find(|p| !p.to_string_lossy().contains("attempt-v2"))
        .unwrap();
    let mut saved: Value = serde_json::from_slice(&fs::read(&proof).unwrap()).unwrap();
    saved["rust_unsatisfied"] = 1.into();
    fs::write(proof, serde_json::to_vec(&saved).unwrap()).unwrap();
    let second = run("second");
    assert_ne!(
        second["classes"][0]["predicates"][0]["reason"],
        "instance_verdict_shared"
    );
    assert_eq!(second["classes"][0]["predicates"][0]["rust_unsatisfied"], 0);
}

/// Unknown and failed solver calls never certify a predicate exclusion or a reach.
#[test]
fn solver_unknown_and_tool_error_remain_unknown() {
    use std::os::unix::fs::PermissionsExt;
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/lifting_engine/lessthan_search");
    let temp = tempfile::tempdir().unwrap();
    for (name, answer) in [
        ("unknown", "unknown\\n(:reason-unknown \"incomplete\")\\n"),
        ("error", "broken tool\\n"),
    ] {
        let fake = temp.path().join(format!("z3-{name}"));
        fs::write(&fake, format!("#!/bin/sh\nprintf '{answer}'\n")).unwrap();
        fs::set_permissions(&fake, fs::Permissions::from_mode(0o755)).unwrap();
        let output = temp.path().join(name);
        Command::cargo_bin("zkfDO")
            .unwrap()
            .args(["experiment", "lift", "--request"])
            .arg(fixture.join("request.json"))
            .arg("--output")
            .arg(&output)
            .arg("--z3-bin")
            .arg(fake)
            .assert()
            .success();
        let result: Value =
            serde_json::from_slice(&fs::read(output.join("result.json")).unwrap()).unwrap();
        assert_eq!(
            result["classes"][0]["assumption_predicate_verdict"], "unknown",
            "{result}"
        );
        let calls = result["costs"]["solver_calls"].as_array().unwrap();
        assert!(!calls.is_empty());
        assert!(calls.iter().all(|call| call["outcome"]
            == if name == "unknown" {
                "unknown"
            } else {
                "tool_error"
            }));
    }
}

#[test]
fn instance_store_separates_different_base_inputs() {
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/lifting_engine/lessthan_search");
    let temp = tempfile::tempdir().unwrap();
    let store = temp.path().join("store");
    for (index, base) in ["1", "2"].into_iter().enumerate() {
        let input = temp.path().join(format!("base-{index}.json"));
        fs::write(&input, format!("{{\"x\":\"{base}\"}}")).unwrap();
        let mut request: Value =
            serde_json::from_slice(&fs::read(fixture.join("request.json")).unwrap()).unwrap();
        request["source_root"] = fixture.join("src").to_string_lossy().into_owned().into();
        request["component_wrapper"] = fixture
            .join("src/standalone.circom")
            .to_string_lossy()
            .into_owned()
            .into();
        request["entrypoint"] = fixture
            .join("src/entrypoint.circom")
            .to_string_lossy()
            .into_owned()
            .into();
        request["base_input"] = input.to_string_lossy().into_owned().into();
        request["candidate"]["path"] = fixture
            .join("candidate.json")
            .to_string_lossy()
            .into_owned()
            .into();
        let request_path = temp.path().join(format!("request-{index}.json"));
        fs::write(&request_path, serde_json::to_vec(&request).unwrap()).unwrap();
        let output = temp.path().join(format!("run-{index}"));
        Command::cargo_bin("zkfDO")
            .unwrap()
            .args(["experiment", "lift", "--request"])
            .arg(request_path)
            .arg("--output")
            .arg(&output)
            .arg("--instance-store")
            .arg(&store)
            .assert()
            .success();
        let result: Value =
            serde_json::from_slice(&fs::read(output.join("result.json")).unwrap()).unwrap();
        assert_ne!(
            result["classes"][0]["predicates"][0]["reason"],
            "instance_verdict_shared"
        );
    }
    assert_eq!(fs::read_dir(store).unwrap().count(), 2);
}

/// Frozen search boundaries can be inconsistent even when no global exclusion is known.
#[test]
fn search_only_unsat_does_not_become_predicate_exclusion() {
    use std::os::unix::fs::PermissionsExt;
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/lifting_engine/lessthan_search");
    let temp = tempfile::tempdir().unwrap();
    let fake = temp.path().join("z3");
    fs::write(&fake, "#!/bin/sh\ncase \"$1\" in *exclusion*) printf 'unknown\\n(:reason-unknown \"incomplete\")\\n';; *) printf 'unsat\\n';; esac\n").unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o755)).unwrap();
    let output = temp.path().join("result");
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args(["experiment", "lift", "--request"])
        .arg(fixture.join("request.json"))
        .arg("--output")
        .arg(&output)
        .arg("--z3-bin")
        .arg(fake)
        .assert()
        .success();
    let result: Value =
        serde_json::from_slice(&fs::read(output.join("result.json")).unwrap()).unwrap();
    let predicate = &result["classes"][0]["predicates"][0];
    assert_eq!(predicate["verdict"], "unknown", "{result}");
    assert_eq!(predicate["search"]["outcome"], "no_progress");
    assert!(predicate["search"]["solves"]
        .as_array()
        .unwrap()
        .iter()
        .any(|solve| solve["outcome"] == "unsat"));
}

fn executable_on_path(name: &str) -> String {
    let output = std::process::Command::new("which")
        .arg(name)
        .output()
        .unwrap();
    assert!(output.status.success());
    String::from_utf8(output.stdout).unwrap().trim().to_owned()
}

#[test]
fn checker_disagreement_does_not_produce_a_reach() {
    use std::os::unix::fs::PermissionsExt;
    let temp = tempfile::tempdir().unwrap();
    let fake = temp.path().join("snarkjs");
    let real = serde_json::to_string(&executable_on_path("snarkjs")).unwrap();
    fs::write(&fake, format!("#!/usr/bin/env python3\nimport subprocess,sys\nif '/site-' in sys.argv[-1]:\n print('WITNESS IS NOT CORRECT')\n sys.exit(1)\nsys.exit(subprocess.run([{real}, *sys.argv[1:]]).returncode)\n")).unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o755)).unwrap();
    let fixture = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/lifting_engine/hint_injection/request.json");
    let output = temp.path().join("result");
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args(["experiment", "lift", "--request"])
        .arg(fixture)
        .arg("--output")
        .arg(&output)
        .arg("--snarkjs-bin")
        .arg(fake)
        .assert()
        .success();
    let result: Value =
        serde_json::from_slice(&fs::read(output.join("result.json")).unwrap()).unwrap();
    assert_eq!(result["classes"][0]["rust_unsatisfied"], 0);
    assert_eq!(result["classes"][0]["snarkjs"], "not_correct");
    assert_eq!(result["classes"][0]["verdict"], "unknown");
}

#[test]
fn changed_repair_r1cs_and_sym_are_rejected() {
    use std::os::unix::fs::PermissionsExt;
    let real = serde_json::to_string(&executable_on_path("circom")).unwrap();
    for extension in ["r1cs", "sym"] {
        let temp = tempfile::tempdir().unwrap();
        let fake = temp.path().join("circom");
        fs::write(&fake, format!("#!/usr/bin/env python3\nimport subprocess,sys,pathlib\np=subprocess.run([{real}, *sys.argv[1:]])\nif p.returncode==0 and any('variant-o0' in a for a in sys.argv):\n d=pathlib.Path(sys.argv[sys.argv.index('-o')+1])\n for f in d.glob('*.{extension}'):\n  b=f.read_bytes()\n  f.write_bytes(b'X'+b[1:])\nsys.exit(p.returncode)\n")).unwrap();
        fs::set_permissions(&fake, fs::Permissions::from_mode(0o755)).unwrap();
        let fixture = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures/lifting_engine/abort_repair/request.json");
        let output = temp.path().join("result");
        Command::cargo_bin("zkfDO")
            .unwrap()
            .args(["experiment", "lift", "--request"])
            .arg(fixture)
            .arg("--output")
            .arg(&output)
            .arg("--circom-bin")
            .arg(fake)
            .assert()
            .success();
        let result: Value =
            serde_json::from_slice(&fs::read(output.join("result.json")).unwrap()).unwrap();
        assert_eq!(
            result["classes"][0]["verdict"], "unknown",
            "{extension}: {result}"
        );
        assert_eq!(
            result["classes"][0]["synthesis"]["repair"]["error_kind"], "evidence_invariant",
            "{extension}: {result}"
        );
    }
}

#[test]
fn simultaneous_range_failures_repair_locally() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let original = root.join("tests/fixtures/lifting_engine/abort_repair");
    let temp = tempfile::tempdir().unwrap();
    let fixture = temp.path();
    fs::create_dir(fixture.join("src")).unwrap();
    for name in ["component.circom", "standalone.circom", "entrypoint.circom"] {
        let mut source = fs::read_to_string(original.join("src").join(name)).unwrap();
        if name == "entrypoint.circom" {
            source = source.replace("o <== q;", "signal q2 <-- d.y \\ 5;\n    signal r2 <-- d.y % 5;\n    d.y === q2 * 5 + r2;\n    component rq2 = Num2Bits(4);\n    rq2.in <== q2;\n    signal q3 <-- d.y \\ 6;\n    signal r3 <-- d.y % 6;\n    d.y === q3 * 6 + r3;\n    component rq3 = Num2Bits(4);\n    rq3.in <== q3;\n    o <== q;");
        }
        fs::write(fixture.join("src").join(name), source).unwrap();
    }
    for name in ["request.json", "candidate.json", "base_input.json"] {
        fs::copy(original.join(name), fixture.join(name)).unwrap();
    }
    let output = fixture.join("result");
    let mut command = match std::env::var_os("N6_J4C_REGRESSION_ENGINE") {
        Some(engine) => Command::new(engine),
        None => Command::cargo_bin("zkfDO").unwrap(),
    };
    command
        .args(["experiment", "lift", "--request"])
        .arg(fixture.join("request.json"))
        .arg("--output")
        .arg(&output)
        .assert()
        .success();
    let result: Value =
        serde_json::from_slice(&fs::read(output.join("result.json")).unwrap()).unwrap();
    let class = &result["classes"][0];
    assert_eq!(class["verdict"], "assumption_input_reachable", "{result}");
    assert_eq!(class["rust_unsatisfied"], 0);
    assert_eq!(class["snarkjs"], "correct");
    let repair = &class["synthesis"]["repair"];
    assert_eq!(repair["localizations"][0]["unsatisfied_constraints"], 3);
    for solve in repair["solves"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|s| s["iteration"] == 0)
    {
        assert_eq!(solve["carry"], "without");
        assert_eq!(solve["carried_constraints"], 0);
        assert_eq!(
            solve["carried_dropped"], 0,
            "current iteration must not enter history"
        );
    }
}
