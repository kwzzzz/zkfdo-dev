use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
    process::Command,
};

use tempfile::tempdir;
use zkfdo::{
    instance_capture::{capture_command, CapturedValue, InstanceCapture},
    targets::{
        discover_project_targets_with, inspect_entrypoint_from_capture, DiscoveryOptions,
        TargetDiscoveryReport,
    },
};

fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
        .canonicalize()
        .expect("fixture")
}

fn circom_available() -> bool {
    Command::new("circom").arg("--version").output().is_ok()
}

fn discover(project: &Path, output: &Path, capture: bool) -> TargetDiscoveryReport {
    discover_project_targets_with(
        project,
        output,
        &DiscoveryOptions {
            entrypoint: Some(project.join("main.circom")),
            circom_bin: Some(PathBuf::from("circom")),
            compile_timeout_seconds: 60,
            instance_capture: capture.then(|| PathBuf::from("circom")),
            ..DiscoveryOptions::default()
        },
    )
    .expect("discovery")
}

fn read_capture(report: &TargetDiscoveryReport) -> InstanceCapture {
    let path = &report.instance_discovery.as_ref().unwrap().capture_path;
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}

fn resolved(capture: &InstanceCapture, path: &str) -> (String, Vec<String>) {
    let instance = capture
        .instances
        .iter()
        .find(|instance| instance.path == path)
        .unwrap_or_else(|| panic!("instance {path}"));
    let values = instance
        .arguments
        .as_ref()
        .expect("captured arguments")
        .iter()
        .map(|value| match value {
            CapturedValue::Scalar { value } => value.clone(),
            CapturedValue::ArrayRef { sha256 } => match &capture.arrays[sha256] {
                CapturedValue::Array { dims, values } => format!("{dims:?}{values:?}"),
                other => panic!("interned value {other:?}"),
            },
            CapturedValue::Array { dims, values } => format!("{dims:?}{values:?}"),
        })
        .collect();
    (instance.template_name.clone(), values)
}

#[test]
fn captures_array_arguments_and_leaves_the_original_constraints_unchanged() {
    if !circom_available() {
        return;
    }
    let project = fixture("instance_capture");
    let output = tempdir().unwrap();
    let report = capture_command(
        &project,
        &project.join("main.circom"),
        &[],
        &output.path().join("capture"),
        Path::new("circom"),
        120,
        true,
    )
    .expect("capture");
    assert_eq!(report.status, "captured");
    assert!(report.complete, "{report:?}");
    let neutrality = report.neutrality.expect("neutrality check");
    assert!(neutrality.identical, "{neutrality:?}");
    assert!(neutrality.capture_constraints_removed > 0);
    assert_eq!(
        neutrality.diagnostic_constraints - neutrality.capture_constraints_removed,
        neutrality.original_constraints
    );

    let capture: InstanceCapture =
        serde_json::from_slice(&fs::read(&report.capture_path).unwrap()).unwrap();
    let table = r#"[3]["13", "14", "15"]"#;
    let expected = [
        ("main", "Body", vec!["2"]),
        ("main.scales[0]", "Scale", vec!["0", table]),
        ("main.scales[1]", "Scale", vec!["1", table]),
        ("main.cells[0][0]", "Scale", vec!["1", r#"[2]["1", "2"]"#]),
        ("main.cells[0][1]", "Scale", vec!["2", r#"[2]["1", "2"]"#]),
        ("main.cells[1][0]", "Scale", vec!["3", r#"[2]["3", "4"]"#]),
        ("main.cells[1][1]", "Scale", vec!["4", r#"[2]["3", "4"]"#]),
        ("main.pass", "Pass", vec![table]),
        ("main.pass.inner", "Scale", vec!["2", table]),
    ];
    for (path, template, values) in expected {
        assert_eq!(
            resolved(&capture, path),
            (
                template.to_owned(),
                values.into_iter().map(str::to_owned).collect()
            ),
            "{path}"
        );
    }
    let squares = capture
        .instances
        .iter()
        .filter(|instance| instance.template_name == "Square")
        .collect::<Vec<_>>();
    assert_eq!(squares.len(), 2);
    assert!(squares.iter().all(|instance| {
        instance.line == Some(61)
            && instance
                .component_name
                .as_deref()
                .is_some_and(|name| name.starts_with("@anonymous:61:"))
    }));
    // Each distinct array is stored once and its key hashes the canonical encoding.
    assert_eq!(capture.arrays.len(), 3);
    let prime = capture.prime().unwrap();
    for (hash, value) in &capture.arrays {
        assert_eq!(value.key_token(&prime).unwrap(), format!("[sha256:{hash}]"));
    }
}

#[test]
fn compiler_instances_reproduce_the_interpreter_where_it_is_complete() {
    if !circom_available() {
        return;
    }
    let project = fixture("target_discovery");
    let (plain_dir, captured_dir) = (tempdir().unwrap(), tempdir().unwrap());
    let plain = discover(&project, plain_dir.path(), false);
    let captured = discover(&project, captured_dir.path(), true);
    let instance = captured.instance_discovery.as_ref().expect("comparison");
    assert_eq!(instance.selected, "compiler");
    assert!(instance.interpreter_complete && instance.compiler_complete);
    assert!(
        instance.slot_differences.is_empty(),
        "{:?}",
        instance.slot_differences
    );
    assert!(instance.instance_keys_only_interpreter.is_empty());
    assert!(instance.instance_keys_only_compiler.is_empty());
    assert_eq!(
        instance.interpreter_root_instance_key,
        instance.compiler_root_instance_key
    );
    assert_eq!(captured.root_instance_key, plain.root_instance_key);
    assert!(captured
        .targets
        .iter()
        .all(|target| target.methods_agree == Some(true)
            && target.instance_source.as_deref() == Some("compiler")));
    let keys = |report: &TargetDiscoveryReport| {
        report
            .compile_units
            .iter()
            .map(|unit| (unit.key.clone(), unit.instance_key.clone()))
            .collect::<BTreeSet<_>>()
    };
    assert_eq!(keys(&captured), keys(&plain));
    assert_eq!(
        captured
            .targets
            .iter()
            .map(|target| (
                target.instance_key.clone(),
                target.parent_instance_key.clone()
            ))
            .collect::<BTreeSet<_>>(),
        plain
            .targets
            .iter()
            .map(|target| (
                target.instance_key.clone(),
                target.parent_instance_key.clone()
            ))
            .collect::<BTreeSet<_>>()
    );
}

#[test]
fn negative_scalars_use_the_signed_key_form_of_the_interpreter() {
    if !circom_available() {
        return;
    }
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("main.circom"),
        "pragma circom 2.1.6;\n\
         template Leaf(k) {\n    signal input in;\n    signal output out;\n    out <== in * (k + 7);\n}\n\
         template Top(n) {\n    signal input in;\n    signal output out;\n    component leaf = Leaf(n - 5);\n    leaf.in <== in;\n    out <== leaf.out;\n}\n\
         component main = Top(2);\n",
    )
    .unwrap();
    let project = project.path().canonicalize().unwrap();
    let output = tempdir().unwrap();
    let report = discover(&project, output.path(), true);
    let instance = report.instance_discovery.as_ref().unwrap();
    assert_eq!(instance.selected, "compiler");
    assert!(instance.slot_differences.is_empty(), "{instance:?}");
    assert_eq!(report.targets.len(), 1);
    assert_eq!(report.targets[0].concrete_parameters, ["-3"]);
    assert_eq!(report.targets[0].methods_agree, Some(true));
}

/// Captures a one-file project with the neutrality check; the temporary directories live as
/// long as the returned guards.
fn capture_source(
    source: &str,
) -> (
    tempfile::TempDir,
    tempfile::TempDir,
    zkfdo::instance_capture::CaptureCommandReport,
    InstanceCapture,
) {
    let project = tempdir().unwrap();
    fs::write(project.path().join("main.circom"), source).unwrap();
    let root = project.path().canonicalize().unwrap();
    let output = tempdir().unwrap();
    let report = capture_command(
        &root,
        &root.join("main.circom"),
        &[],
        &output.path().join("capture"),
        Path::new("circom"),
        120,
        true,
    )
    .expect("capture");
    let capture = serde_json::from_slice(&fs::read(&report.capture_path).unwrap()).unwrap();
    (project, output, report, capture)
}

/// `Mix` passes its array parameter on twice: as a copy in a local variable (an argument the
/// compiler computes and the copy captures at the site) and directly (a pass-through of the
/// value taken from the main literal); `Leaf` receives one element as a captured scalar.
const MAIN_LITERAL_TEMPLATES: &str = "pragma circom 2.1.6;\n\
     template Leaf(k) {\n    signal input in;\n    signal output out;\n    out <== in * (k + 1);\n}\n\
     template Use(table) {\n    signal input in;\n    signal output out;\n    out <== in * table[0];\n}\n\
     template Mix(n, table) {\n    signal input in;\n    signal output out;\n    var copy[4] = table;\n    component leaf = Leaf(table[n]);\n    component computed = Use(copy);\n    component passed = Use(table);\n    leaf.in <== in;\n    computed.in <== leaf.out;\n    passed.in <== computed.out;\n    out <== passed.out;\n}\n";

#[test]
fn main_literal_arrays_match_the_values_circom_computes() {
    if !circom_available() {
        return;
    }
    // A negative literal, hexadecimal literals, and a decimal literal above the prime.
    let above_prime =
        "21888242871839275222246405745257275088548364400416034343698204186575808495618";
    let (_project, _output, report, capture) = capture_source(&format!(
        "{MAIN_LITERAL_TEMPLATES}component main = Mix(2, [-1, 0x10, 0xff, {above_prime}]);\n"
    ));
    assert!(report.complete, "{report:?}");
    assert!(report.neutrality.as_ref().unwrap().identical);
    assert_eq!(capture.main_literal_parameters, ["table"]);
    let prime = capture.prime().unwrap();
    let table = format!(r#"[4]["{}", "16", "255", "1"]"#, &prime - 1u32);
    assert_eq!(
        resolved(&capture, "main"),
        ("Mix".to_owned(), vec!["2".to_owned(), table.clone()])
    );
    // The compiler's own values: the site-captured copy and the captured element.
    assert_eq!(
        resolved(&capture, "main.computed"),
        ("Use".to_owned(), vec![table.clone()])
    );
    assert_eq!(
        resolved(&capture, "main.passed"),
        ("Use".to_owned(), vec![table])
    );
    assert_eq!(
        resolved(&capture, "main.leaf"),
        ("Leaf".to_owned(), vec!["255".to_owned()])
    );
    let key = |path: &str| {
        let instance = capture.instances.iter().find(|i| i.path == path).unwrap();
        capture.instance_key(instance).unwrap().unwrap()
    };
    assert_eq!(key("main.computed"), key("main.passed"));
}

#[test]
fn non_literal_main_arrays_are_unsupported_with_the_reason() {
    if !circom_available() {
        return;
    }
    for (argument, expression) in [("[1 + 2, 4, 5, 6]", "1 + 2"), ("FOUR()", "FOUR")] {
        let (_project, _output, report, capture) = capture_source(&format!(
            "{MAIN_LITERAL_TEMPLATES}function FOUR() {{\n    return [3, 4, 5, 6];\n}}\n\
             component main = Mix(0, {argument});\n"
        ));
        assert_eq!(report.status, "captured");
        assert!(!report.complete);
        assert!(report.neutrality.as_ref().unwrap().identical);
        assert!(capture.main_literal_parameters.is_empty());
        let main = capture.root().unwrap();
        assert!(main.arguments.is_none());
        let reason = main.unsupported.as_deref().unwrap();
        assert!(
            reason.starts_with("array parameter table of the main component is not captured: ")
                && reason.contains(expression),
            "{reason}"
        );
        assert!(capture
            .unsupported
            .iter()
            .any(|case| case.construct == "main (Mix)" && case.reason.contains(reason)));
        // Children that do not depend on the unresolved array keep compiler values.
        assert_eq!(
            resolved(&capture, "main.leaf"),
            ("Leaf".to_owned(), vec!["3".to_owned()])
        );
        assert_eq!(
            resolved(&capture, "main.computed").1,
            [r#"[4]["3", "4", "5", "6"]"#]
        );
        assert!(capture
            .instances
            .iter()
            .find(|i| i.path == "main.passed")
            .unwrap()
            .arguments
            .is_none());
    }
}

#[test]
fn anonymous_components_in_var_declarations_stay_in_scope() {
    if !circom_available() {
        return;
    }
    let (_project, _output, report, capture) = capture_source(
        "pragma circom 2.1.6;\n\
         template Sq() {\n    signal input in;\n    signal output out;\n    out <== in * in;\n}\n\
         template Top(n) {\n    signal input in[n];\n    signal output out;\n    var acc = 0;\n    for (var i = 0; i < n; i++) {\n        var s = Sq()(in[i]);\n        acc += s;\n    }\n    out <== acc;\n}\n\
         component main = Top(3);\n",
    );
    assert_eq!(report.status, "captured", "{:?}", report.failure);
    assert!(report.complete);
    assert!(report.neutrality.as_ref().unwrap().identical);
    assert_eq!(
        capture
            .instances
            .iter()
            .filter(|i| i.template_name == "Sq" && i.line == Some(12))
            .count(),
        3
    );
}

#[test]
fn inspections_resolve_array_literal_wrappers_from_the_capture() {
    if !circom_available() {
        return;
    }
    let project = fixture("instance_capture");
    let output = tempdir().unwrap();
    let report = discover(&project, output.path(), true);
    let capture = read_capture(&report);
    assert!(capture.complete());
    let unit = |key_part: &str| {
        report
            .compile_units
            .iter()
            .find(|unit| unit.instance_key.ends_with(key_part))
            .unwrap_or_else(|| panic!("compile unit {key_part}"))
    };
    let table = capture
        .arrays
        .iter()
        .find(
            |(_, value)| matches!(value, CapturedValue::Array { values, .. } if values.len() == 3),
        )
        .map(|(hash, _)| hash.clone())
        .unwrap();

    let pass = unit(&format!("::Pass([sha256:{table}])"));
    assert!(fs::read_to_string(&pass.wrapper_path)
        .unwrap()
        .contains("component main = Pass([13, 14, 15]);"));
    let inspection =
        inspect_entrypoint_from_capture(&pass.wrapper_path, &project, &[], &capture).unwrap();
    assert!(inspection.complete, "{:?}", inspection.unsupported);
    let root = inspection.root.as_ref().unwrap();
    assert_eq!(root.template_name, "Pass");
    assert_eq!(root.concrete_parameters, [format!("[sha256:{table}]")]);
    assert_eq!(
        inspection
            .instances
            .iter()
            .map(|instance| (
                instance.template_name.clone(),
                instance.concrete_parameters.clone()
            ))
            .collect::<BTreeSet<_>>(),
        BTreeSet::from([
            ("Pass".to_owned(), vec![format!("[sha256:{table}]")]),
            (
                "Scale".to_owned(),
                vec!["2".to_owned(), format!("[sha256:{table}]")]
            ),
        ])
    );

    // The whole entrypoint inspects from the captured main.
    let whole =
        inspect_entrypoint_from_capture(&project.join("main.circom"), &project, &[], &capture)
            .unwrap();
    assert!(whole.complete);
    assert_eq!(whole.root.as_ref().unwrap().template_name, "Body");
    // Distinct instances: Body, six Scale argument tuples, Pass, and Square.
    assert_eq!(whole.instances.len(), 10);
}

#[test]
fn failed_captures_keep_interpreter_targets_labelled_with_the_reason() {
    if !circom_available() {
        return;
    }
    let project = tempdir().unwrap();
    fs::write(
        project.path().join("main.circom"),
        "pragma circom 2.1.6;\n\
         template Leaf(k) {\n    signal input in;\n    signal output out;\n    out <== in * k;\n}\n\
         template Top(n) {\n    signal input in;\n    signal output out;\n    assert(n > 100);\n    component leaf = Leaf(n);\n    leaf.in <== in;\n    out <== leaf.out;\n}\n\
         component main = Top(2);\n",
    )
    .unwrap();
    let project = project.path().canonicalize().unwrap();
    let output = tempdir().unwrap();
    let report = discover(&project, output.path(), true);
    let instance = report.instance_discovery.as_ref().unwrap();
    assert_eq!(instance.selected, "interpreter");
    assert_ne!(instance.capture_status, "captured");
    assert!(instance.capture_failure.is_some());
    assert_eq!(report.targets.len(), 1);
    assert_eq!(
        report.targets[0].instance_source.as_deref(),
        Some("interpreter")
    );
    assert_eq!(report.targets[0].methods_agree, None);
}
