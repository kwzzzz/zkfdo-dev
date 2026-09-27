use std::{fs, path::PathBuf};

use serde_json::Value;
use tempfile::TempDir;
use zkfdo::semantic::{
    analyze_target, import_sarif, AnalysisCapture, AnalysisOptions, FeatureStatus,
    SemanticAnalysis, SourceScope, ANALYZER_REVISION, ANALYZER_VERSION,
};

#[test]
fn analyzer_command_records_deduplicated_library_search_roots() {
    let directory = TempDir::new().unwrap();
    let source = directory.path().join("root.circom");
    fs::write(&source, "template Root() {}\n").unwrap();
    let library = directory.path().join("library");
    fs::create_dir(&library).unwrap();
    let output = directory.path().join("analysis");
    let options = AnalysisOptions {
        binary: directory.path().join("missing-circomspect"),
        library_paths: vec![library.clone(), library.clone()],
        ..AnalysisOptions::default()
    };

    let report = analyze_target(
        &[SourceScope {
            path: source.clone(),
            template_name: "Root".into(),
            start_line: 1,
            end_line: 1,
        }],
        &options,
        &output,
    )
    .unwrap();

    let canonical_library = fs::canonicalize(library)
        .unwrap()
        .to_string_lossy()
        .into_owned();
    let canonical_source = fs::canonicalize(source)
        .unwrap()
        .to_string_lossy()
        .into_owned();
    let command = &report.capture.command;
    let library_flags = command
        .windows(2)
        .filter(|pair| pair[0] == "--library" && pair[1] == canonical_library)
        .count();
    assert_eq!(library_flags, 1);
    assert!(
        command.iter().position(|arg| arg == &canonical_library)
            < command.iter().position(|arg| arg == &canonical_source)
    );
}

fn fixture_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/semantic")
}

fn scope(name: &str) -> SourceScope {
    let path = fixture_root().join("cases.circom");
    let source = fs::read_to_string(&path).unwrap();
    let lines = source.lines().collect::<Vec<_>>();
    let start = lines
        .iter()
        .position(|line| line.starts_with(&format!("template {name}(")))
        .unwrap();
    let mut depth = 0;
    let end = lines
        .iter()
        .enumerate()
        .skip(start)
        .find_map(|(i, line)| {
            depth += line.chars().filter(|c| *c == '{').count();
            depth -= line.chars().filter(|c| *c == '}').count();
            (depth == 0).then_some(i)
        })
        .unwrap();
    SourceScope {
        path,
        template_name: name.into(),
        start_line: start + 1,
        end_line: end + 1,
    }
}

fn capture(temp: &TempDir) -> AnalysisCapture {
    let root = fixture_root();
    for name in ["actual.sarif", "actual.stdout.log", "actual.stderr.log"] {
        let text = fs::read_to_string(root.join(name)).unwrap();
        fs::write(
            temp.path().join(name),
            text.replace("__FIXTURE_ROOT__", &root.to_string_lossy()),
        )
        .unwrap();
    }
    AnalysisCapture {
        tool_path: PathBuf::from("captured official Circomspect fixture"),
        tool_version: ANALYZER_VERSION.into(),
        tool_revision: ANALYZER_REVISION.into(),
        curve: "BN254".into(),
        command: vec![],
        sarif_path: temp.path().join("actual.sarif"),
        stdout_path: temp.path().join("actual.stdout.log"),
        stderr_path: temp.path().join("actual.stderr.log"),
        exit_code: Some(1),
        timed_out: false,
        elapsed_seconds: 0.0,
        execution_error: None,
    }
}

fn analyze_capture(names: &[&str]) -> SemanticAnalysis {
    let temp = TempDir::new().unwrap();
    import_sarif(
        &names.iter().map(|name| scope(name)).collect::<Vec<_>>(),
        capture(&temp),
    )
    .unwrap()
}

fn value(report: &SemanticAnalysis, id: &str) -> Option<u8> {
    report
        .features
        .iter()
        .find(|feature| feature.rule_id == id)
        .unwrap()
        .value
}

#[test]
fn actual_rule_outputs_differ_from_token_presence() {
    let source = fs::read_to_string(fixture_root().join("cases.circom")).unwrap();
    assert!(source.contains("<--") && source.contains("LessThan") && source.contains("assert("));
    let plain = analyze_capture(&["Plain"]);
    assert!(plain.complete, "{:?}", plain.reasons);
    assert_eq!(plain.risk_score, Some(0));
    assert_eq!(plain.warning_count, 0);
    assert!(plain.ignored_out_of_scope_count >= 7);
    let assignment = analyze_capture(&["Assignment"]);
    assert_eq!(assignment.risk_score, Some(1));
    assert_eq!(value(&assignment, "CS0013"), Some(1));
}

#[test]
fn protective_constraints_remove_supported_division_and_range_warnings() {
    let division = analyze_capture(&["Division"]);
    let protected = analyze_capture(&["ProtectedDivision", "IsZero"]);
    assert_eq!(value(&division, "CS0015"), Some(1));
    assert_eq!(value(&protected, "CS0015"), Some(0));
    assert!(protected.risk_score < division.risk_score);
    let comparison = analyze_capture(&["Comparison", "LessThan", "Num2Bits"]);
    let protected = analyze_capture(&["ProtectedComparison", "LessThan", "Num2Bits"]);
    assert_eq!(value(&comparison, "CS0014"), Some(1));
    assert_eq!(value(&protected, "CS0014"), Some(0));
    assert!(protected.risk_score < comparison.risk_score);
}

#[test]
fn assertion_phase_precision_is_explicitly_unsupported() {
    for name in ["ParameterAssertion", "SignalAssertion"] {
        let report = analyze_capture(&[name]);
        assert!(report.complete);
        assert_eq!(report.risk_score, Some(0));
        assert_eq!(
            report.unsupported_features[0].status,
            FeatureStatus::Unsupported
        );
        assert!(!report
            .features
            .iter()
            .any(|feature| feature.rule_name.contains("assert")));
    }
}

#[test]
fn feature_presence_does_not_count_multiple_warnings_or_duplicate_reports_twice() {
    let temp = TempDir::new().unwrap();
    let capture = capture(&temp);
    let mut sarif: Value = serde_json::from_slice(&fs::read(&capture.sarif_path).unwrap()).unwrap();
    let results = sarif["runs"][0]["results"].as_array_mut().unwrap();
    let duplicate = results
        .iter()
        .find(|r| r["ruleId"] == "CS0014")
        .unwrap()
        .clone();
    results.push(duplicate);
    fs::write(&capture.sarif_path, serde_json::to_vec(&sarif).unwrap()).unwrap();
    let report = import_sarif(&[scope("Comparison")], capture).unwrap();
    assert_eq!(report.warning_count, 2);
    assert_eq!(report.duplicate_warning_count, 1);
    assert_eq!(report.risk_score, Some(1));
    assert_eq!(
        report
            .features
            .iter()
            .find(|f| f.rule_id == "CS0014")
            .unwrap()
            .observed_warning_count,
        2
    );
}

#[test]
fn source_locations_and_related_signal_evidence_are_preserved() {
    let report = analyze_capture(&["WeakIntermediate", "UnusedOutput", "Plain"]);
    assert_eq!(value(&report, "CS0017"), Some(1));
    assert_eq!(value(&report, "CS0018"), Some(1));
    let warning = report
        .warnings
        .iter()
        .find(|w| w.rule_id == "CS0017")
        .unwrap();
    assert_eq!(
        warning.attributed_scopes[0].template_name,
        "WeakIntermediate"
    );
    assert!(warning.locations[0].label.contains("intermediate"));
    assert!(!warning.related_locations.is_empty());
    assert!(warning.raw_result_path.ends_with("actual.sarif"));
}

#[test]
fn analysis_failure_preserves_observed_warnings_and_unknown_values() {
    let temp = TempDir::new().unwrap();
    let mut capture = capture(&temp);
    capture.timed_out = true;
    let report = import_sarif(&[scope("Division")], capture).unwrap();
    assert!(!report.complete);
    assert_eq!(report.risk_score, None);
    assert_eq!(report.warning_count, 1);
    assert!(report
        .features
        .iter()
        .all(|f| f.status == FeatureStatus::Unknown && f.value.is_none()));
}

#[test]
fn missing_cfg_completion_internal_timeout_and_wrong_revision_are_not_clean_results() {
    let temp = TempDir::new().unwrap();
    let capture = capture(&temp);
    fs::write(&capture.stderr_path, "").unwrap();
    assert!(!import_sarif(&[scope("Plain")], capture).unwrap().complete);
    let capture = self::capture(&temp);
    let mut stderr = fs::read_to_string(&capture.stderr_path).unwrap();
    stderr.push_str("\nDEBUG failed to propagate degrees within allotted time\n");
    fs::write(&capture.stderr_path, stderr).unwrap();
    assert!(!import_sarif(&[scope("Plain")], capture).unwrap().complete);
    let mut capture = self::capture(&temp);
    capture.tool_revision = "unknown revision".into();
    assert!(!import_sarif(&[scope("Plain")], capture).unwrap().complete);
}

#[test]
fn missing_sarif_and_analyzer_errors_remain_unknown() {
    let temp = TempDir::new().unwrap();
    let capture = capture(&temp);
    fs::remove_file(&capture.sarif_path).unwrap();
    assert!(!import_sarif(&[scope("Plain")], capture).unwrap().complete);
    let capture = self::capture(&temp);
    let mut sarif: Value = serde_json::from_slice(&fs::read(&capture.sarif_path).unwrap()).unwrap();
    sarif["runs"][0]["results"]
        .as_array_mut()
        .unwrap()
        .push(serde_json::json!({"ruleId":"P1000","level":"error"}));
    fs::write(&capture.sarif_path, serde_json::to_vec(&sarif).unwrap()).unwrap();
    assert!(!import_sarif(&[scope("Plain")], capture).unwrap().complete);
}

#[test]
fn overlapping_or_empty_scopes_are_rejected() {
    let temp = TempDir::new().unwrap();
    assert!(import_sarif(&[], capture(&temp)).is_err());
    let first = scope("Division");
    let mut second = first.clone();
    second.template_name = "Ambiguous".into();
    assert!(import_sarif(&[first, second], capture(&temp)).is_err());
}

#[test]
#[ignore = "requires the pinned local Circomspect build; run cargo test --test semantic_test -- --ignored"]
fn real_analyzer_uses_dependency_source_instead_of_short_wrapper() {
    assert_eq!(
        fs::read_to_string(fixture_root().join("wrapper.circom"))
            .unwrap()
            .lines()
            .count(),
        3
    );
    let output = TempDir::new().unwrap();
    let report = analyze_target(
        &[scope("Division")],
        &AnalysisOptions::default(),
        output.path(),
    )
    .unwrap();
    assert!(report.complete, "{:?}", report.reasons);
    assert_eq!(report.risk_score, Some(1));
    assert_eq!(report.capture.exit_code, Some(1));
    assert_eq!(
        report.warnings[0].attributed_scopes[0].template_name,
        "Division"
    );
    assert!(output.path().join("semantic.json").exists());
}

#[test]
#[ignore = "requires the pinned local Circomspect build; run cargo test --test semantic_test -- --ignored"]
fn real_analyzer_does_not_treat_signal_assertion_as_a_supported_assertion_rule() {
    let output = TempDir::new().unwrap();
    let report = analyze_target(
        &[scope("SignalAssertion")],
        &AnalysisOptions::default(),
        output.path(),
    )
    .unwrap();
    assert!(report.complete, "{:?}", report.reasons);
    assert_eq!(report.risk_score, Some(0));
    assert_eq!(
        report.unsupported_features[0].status,
        FeatureStatus::Unsupported
    );
}
