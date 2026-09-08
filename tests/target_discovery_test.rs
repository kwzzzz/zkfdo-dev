use std::{fs, path::PathBuf, process::Command};

use tempfile::tempdir;
use zkfdo::targets::{discover_project_targets, EntrypointStatus, WrapperStatus};

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
}

#[test]
fn discovers_reachable_concrete_targets_and_generates_wrappers() {
    let output = tempdir().expect("output dir");
    let report = discover_project_targets(fixture("target_discovery"), output.path(), None)
        .expect("target discovery");

    assert_eq!(report.entrypoint_status, EntrypointStatus::Found);
    assert_eq!(report.entrypoints.len(), 1);
    assert_eq!(
        report.entrypoints[0].template_name.as_deref(),
        Some("ProjectMain")
    );
    assert_eq!(report.entrypoints[0].parameters, ["64"]);
    assert_eq!(report.targets.len(), 7);
    assert_eq!(report.generated_wrapper_count, 7);
    assert_eq!(report.compile_succeeded_count, 0);
    assert!(report.unsupported.is_empty(), "{:?}", report.unsupported);

    let mut bits_parameters = report
        .targets
        .iter()
        .filter(|target| target.template_name == "Bits")
        .map(|target| target.concrete_parameters.clone())
        .collect::<Vec<_>>();
    bits_parameters.sort();
    assert_eq!(bits_parameters, [["256"], ["32"], ["8"]]);

    let bigint = report
        .targets
        .iter()
        .find(|target| target.template_name == "BigInt")
        .expect("nested BigInt target");
    assert_eq!(bigint.concrete_parameters, ["32", "64"]);
    assert_eq!(bigint.origin.parent_template, "RSA");
    assert_eq!(bigint.origin.parent_parameters, ["2048"]);
    assert_eq!(bigint.origin.component_name, "bigint");

    for target in &report.targets {
        assert_eq!(target.wrapper_status, WrapperStatus::Generated);
        let wrapper_path = target
            .generated_wrapper_path
            .as_ref()
            .expect("generated wrapper path");
        let wrapper = fs::read_to_string(wrapper_path).expect("wrapper source");
        assert!(wrapper.contains("include \""));
        assert!(wrapper.contains(&format!(
            "component main = {}({});",
            target.template_name,
            target.concrete_parameters.join(", ")
        )));
    }

    let persisted: serde_json::Value = serde_json::from_slice(
        &fs::read(report.work_dir.join("discovery.json")).expect("discovery report"),
    )
    .expect("valid discovery JSON");
    assert_eq!(persisted["entrypoint_status"], "found");
    assert_eq!(persisted["targets"].as_array().map(Vec::len), Some(7));
}

#[test]
fn validates_generated_library_wrappers_with_circom_when_available() {
    if Command::new("circom").arg("--version").output().is_err() {
        return;
    }

    let output = tempdir().expect("output dir");
    let report = discover_project_targets(
        fixture("target_discovery"),
        output.path(),
        Some(PathBuf::from("circom").as_path()),
    )
    .expect("target discovery");

    assert_eq!(report.generated_wrapper_count, 7);
    assert_eq!(report.compile_succeeded_count, 7);
    assert!(report.targets.iter().all(|target| {
        target.wrapper_status == WrapperStatus::CompileSucceeded
            && target
                .compiler_stdout_path
                .as_ref()
                .is_some_and(|path| path.exists())
            && target
                .compiler_stderr_path
                .as_ref()
                .is_some_and(|path| path.exists())
    }));
}

#[test]
fn records_unsupported_instantiations_instead_of_guessing_targets() {
    let output = tempdir().expect("output dir");
    let report =
        discover_project_targets(fixture("target_discovery_unsupported"), output.path(), None)
            .expect("target discovery");

    assert_eq!(report.entrypoint_status, EntrypointStatus::Found);
    assert!(report.targets.is_empty());
    assert!(report
        .unsupported
        .iter()
        .any(|case| case.reason.contains("component arrays")));
    assert!(report
        .unsupported
        .iter()
        .any(|case| case.reason.contains("inside control flow")));
    assert!(report
        .unsupported
        .iter()
        .any(|case| case.reason.contains("anonymous component")));
}

#[test]
fn reports_missing_and_multiple_entrypoints_explicitly() {
    let missing_project = tempdir().expect("missing-main project");
    fs::write(
        missing_project.path().join("library.circom"),
        "pragma circom 2.1.6; template Library() {}",
    )
    .expect("library source");
    let missing_output = tempdir().expect("missing-main output");
    let missing = discover_project_targets(missing_project.path(), missing_output.path(), None)
        .expect("missing-main discovery");
    assert_eq!(missing.entrypoint_status, EntrypointStatus::Missing);
    assert!(missing.targets.is_empty());
    assert!(missing
        .unsupported
        .iter()
        .any(|case| case.reason.contains("no top-level component main")));

    let multiple_project = tempdir().expect("multiple-main project");
    fs::write(
        multiple_project.path().join("one.circom"),
        "pragma circom 2.1.6; template One() {} component main = One();",
    )
    .expect("first main");
    fs::write(
        multiple_project.path().join("two.circom"),
        "pragma circom 2.1.6; template Two() {} component main = Two();",
    )
    .expect("second main");
    let multiple_output = tempdir().expect("multiple-main output");
    let multiple = discover_project_targets(multiple_project.path(), multiple_output.path(), None)
        .expect("multiple-main discovery");
    assert_eq!(multiple.entrypoint_status, EntrypointStatus::Multiple);
    assert_eq!(multiple.entrypoints.len(), 2);
    assert!(multiple.targets.is_empty());
}

#[test]
fn refuses_wrapper_when_target_source_already_contains_main() {
    let project = tempdir().expect("project");
    fs::write(
        project.path().join("main.circom"),
        r#"pragma circom 2.1.6;
template Root() { component child = Child(); }
template Child() {}
component main = Root();
"#,
    )
    .expect("source");
    let output = tempdir().expect("output");
    let report =
        discover_project_targets(project.path(), output.path(), None).expect("target discovery");

    assert_eq!(report.targets.len(), 1);
    assert_eq!(report.targets[0].template_name, "Child");
    assert_eq!(report.targets[0].wrapper_status, WrapperStatus::Unsupported);
    assert!(report.targets[0].generated_wrapper_path.is_none());
    assert!(report.targets[0]
        .failure_reason
        .as_deref()
        .is_some_and(|reason| reason.contains("component main")));
}
