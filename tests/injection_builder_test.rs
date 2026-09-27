use std::{
    fs,
    path::{Path, PathBuf},
};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tempfile::tempdir;
use zkfdo::{
    candidate_review::{review, schema::ReportStatus, ReviewOptions},
    injection::{build, InjectOptions},
};

const MUX: &str = "pragma circom 2.1.6;

template Mux() {
    signal input s;
    signal input c[2];
    signal output out;
    signal t1;
    signal t2;
    s * (1 - s) === 0;
    t1 <== c[0] * s;
    t2 <== c[1] * (1 - s);
    out <== t1 + t2;
}
";

const MAIN: &str = "pragma circom 2.1.6;

include \"mux.circom\";

template Top() {
    signal input s;
    signal input c[2];
    signal output out;
    component m = Mux();
    m.s <== s;
    m.c[0] <== c[0];
    m.c[1] <== c[1];
    out <== m.out;
}

component main = Top();
";

const PREDICATE: &str = r#"API_VERSION = 1


def evaluate(context):
    modulus = int(context["field_modulus_decimal"])
    signals = context["wire_signals"]
    s = int(signals["main.s"])
    c = [int(signals["main.c[0]"]), int(signals["main.c[1]"])]
    if s not in (0, 1):
        return {
            "input_preconditions": {"verdict": "not-satisfied", "reason_code": "selector-not-boolean"},
            "specified_property_violation": {"verdict": "unknown", "reason_code": "unresolved"},
        }
    holds = int(signals["main.out"]) == (c[0] * s + c[1] * (1 - s)) % modulus
    violation = {"verdict": "not-satisfied", "reason_code": "property-holds"}
    if not holds:
        violation = {
            "verdict": "satisfied",
            "reason_code": "property-violated",
            "violation_class": "selected-output-mismatch",
        }
    return {
        "input_preconditions": {"verdict": "satisfied", "reason_code": "contract-satisfied"},
        "specified_property_violation": violation,
    }
"#;

fn plan(twin_replace: &str) -> Value {
    let result = |criterion: &str, verdict: &str, reason: &str| {
        json!({"criterion": criterion, "verdict": verdict, "reason_code": reason,
            "note": "Synthetic mux predicate result."})
    };
    json!({
        "schema_version": 1,
        "injection_id": "synthetic-o1-mux",
        "root_cause_id": "synthetic/o1-mux-output",
        "operator": {"id": "O1", "justification": "Synthetic O1 on the mux output."},
        "project": {"name": "synthetic/mux", "revision": "a".repeat(40), "checkout": "project",
            "entrypoint": "src/main.circom", "library_paths": []},
        "target": {"source_path": "src/mux.circom", "template": "Mux", "concrete_parameters": []},
        "mutant_edit": {"find": "    out <== t1 + t2;\n", "replace": "    out <-- t1 + t2;\n"},
        "twin_edit": {"find": "    out <-- t1 + t2;\n", "replace": twin_replace},
        "contract": {
            "input_contract_id": "mux-selector-boolean",
            "property_id": "mux-returns-selected-choice",
            "input_contract_statement": "main.s is boolean.",
            "property_statement": "main.out is the selected choice.",
            "input_contract": {"kind": "bounded", "enforcement": "unverified"},
            "input_signal_names": ["main.c[0]", "main.c[1]", "main.s"],
            "property_signal_names": ["main.out"],
            "predicate": {
                "path": "mux.py",
                "config": {},
                "allowed_results": [
                    result("input_preconditions", "satisfied", "contract-satisfied"),
                    result("input_preconditions", "not-satisfied", "selector-not-boolean"),
                    result("specified_property_violation", "satisfied", "property-violated"),
                    result("specified_property_violation", "not-satisfied", "property-holds"),
                    result("specified_property_violation", "unknown", "unresolved")
                ],
                "allowed_violation_classes": ["selected-output-mismatch"]
            }
        },
        "common_input": "input.json",
        "relation_exclusion": "operator-proof",
        "workspace": "workspace",
        "output": "output"
    })
}

fn write_fixture(root: &Path, twin_replace: &str) -> PathBuf {
    fs::create_dir_all(root.join("project/src")).unwrap();
    fs::write(root.join("project/src/mux.circom"), MUX).unwrap();
    fs::write(root.join("project/src/main.circom"), MAIN).unwrap();
    fs::write(root.join("mux.py"), PREDICATE).unwrap();
    fs::write(
        root.join("input.json"),
        br#"{"s": "1", "c": ["123456789", "987654321"]}"#,
    )
    .unwrap();
    let plan_path = root.join("plan.json");
    fs::write(
        &plan_path,
        serde_json::to_vec_pretty(&plan(twin_replace)).unwrap(),
    )
    .unwrap();
    plan_path
}

fn options(plan: PathBuf) -> InjectOptions {
    InjectOptions {
        plan,
        circom_bin: PathBuf::from("circom"),
        node_bin: PathBuf::from("node"),
        relation_verifier_bin: PathBuf::from(env!("CARGO_BIN_EXE_zkfdo-relation-verifier")),
    }
}

fn python_bin() -> PathBuf {
    std::env::var_os("PATH")
        .into_iter()
        .flat_map(|paths| std::env::split_paths(&paths).collect::<Vec<_>>())
        .map(|directory| directory.join("python3"))
        .find(|path| path.is_file())
        .map(|path| fs::canonicalize(path).unwrap())
        .expect("python3 is required")
}

#[test]
#[ignore = "requires circom 2.2.3 and node; run cargo test --test injection_builder_test -- --ignored"]
fn built_o1_injection_is_qualified_by_the_engine() {
    let temporary = tempdir().unwrap();
    let plan = write_fixture(temporary.path(), "    out <-- t1 + t2 + 1;\n");
    let built = build(&options(plan)).unwrap();
    assert_eq!(built.expected_clean_constraint_count, 1);
    assert_eq!(built.certificate_constraint_count, 1);
    let output = review(&ReviewOptions {
        request: built.request.clone(),
        output: temporary.path().join("qualification"),
        python_bin: python_bin(),
        source_revision: built.source_revision.clone(),
        engine_source_manifest: built.engine_source_manifest.clone(),
        executable: std::env::current_exe().unwrap(),
    })
    .unwrap();
    let report: Value = serde_json::from_slice(&fs::read(&output.report_path).unwrap()).unwrap();
    assert_eq!(output.status, ReportStatus::Complete, "{report:#}");
    let review = &report["reviews"][0];
    assert_eq!(review["disposition"], "validated", "{report:#}");
    assert_eq!(
        review["ground_truth_qualification"], "qualified",
        "{report:#}"
    );
    for criterion in review["qualification_criteria"]
        .as_object()
        .unwrap()
        .values()
    {
        assert_eq!(criterion["verdict"], "satisfied", "{report:#}");
    }
    // Tracked outputs carry no raw input value.
    for entry in fs::read_dir(temporary.path().join("output")).unwrap() {
        let path = entry.unwrap().path();
        if path.is_file() {
            let text = fs::read_to_string(&path).unwrap();
            assert!(!text.contains("123456789"), "{}", path.display());
        }
    }
    let digest = format!(
        "{:x}",
        Sha256::digest(fs::read(&output.report_path).unwrap())
    );
    assert_eq!(output.report_sha256, digest);
}

#[test]
#[ignore = "requires circom 2.2.3 and node; run cargo test --test injection_builder_test -- --ignored"]
fn a_twin_that_keeps_the_selected_output_is_refused() {
    let temporary = tempdir().unwrap();
    // The twin changes only how the same value is written, so no clean constraint fails.
    let plan = write_fixture(temporary.path(), "    out <-- t2 + t1;\n");
    let error = build(&options(plan)).unwrap_err().to_string();
    assert!(
        error.contains("fails no injection-related clean constraint"),
        "{error}"
    );
}
