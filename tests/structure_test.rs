use zkfdo::structure::{parse_constraint_count, parse_root_ast_csv, STRUCTURAL_METRIC};

const HEADER: &str = "template_name,num_statements,num_variables,num_if_then_else,num_while,num_constraint_equality,num_assign_var,num_assign_constraint_signal,num_assign_signal,avg_loc_constraint_equality,avg_loc_assign_constraint_signal,avg_loc_assign_signal\n";

#[test]
fn only_exact_root_template_contributes_to_ast_statistics() {
    let text = format!("{HEADER}Dependency,9999,0,300,500,0,0,0,0,0,0,0\nRoot,20,0,2,3,0,0,0,0,0,0,0\nUnreachable,999,0,10,20,0,0,0,0,0,0,0\n");
    let stats = parse_root_ast_csv(&text, "Root").unwrap();
    assert_eq!(stats.template_name, "Root");
    assert_eq!(stats.num_statements, 20);
    assert_eq!(stats.num_if_then_else, 2);
    assert_eq!(stats.num_while, 3);
    assert_eq!(stats.complexity().unwrap(), 5);
    assert_eq!(STRUCTURAL_METRIC, "root_ast_if_plus_while");
}

#[test]
fn missing_duplicate_and_malformed_root_rows_are_errors() {
    for text in [
        format!("{HEADER}Other,20,0,2,3,0,0,0,0,0,0,0\n"),
        format!("{HEADER}Root,20,0,2,3,0,0,0,0,0,0,0\nRoot,20,0,2,3,0,0,0,0,0,0,0\n"),
        format!("{HEADER}Root,20,0,?,3,0,0,0,0,0,0,0\n"),
        format!("{HEADER}Root,20,0,2,-1,0,0,0,0,0,0,0\n"),
        format!("{HEADER}Root,20,0,2\n"),
        format!("{HEADER}Root,1,0,2,3,0,0,0,0,0,0,0\n"),
        "template_name,num_statements,num_if_then_else\nRoot,20,2\n".to_owned(),
        "template_name,num_statements,num_if_then_else,num_while,num_while\nRoot,20,2,3,3\n"
            .to_owned(),
        String::new(),
    ] {
        assert!(
            parse_root_ast_csv(&text, "Root").is_err(),
            "accepted malformed root stats: {text}"
        );
    }
}

#[test]
fn zero_control_flow_is_an_observation_not_missing_data() {
    let stats =
        parse_root_ast_csv(&format!("{HEADER}Root,3,0,0,0,0,0,0,0,0,0,0\n"), "Root").unwrap();
    assert_eq!(stats.complexity().unwrap(), 0);
}

#[test]
fn compiler_counts_are_exact_checked_and_allow_zero() {
    assert_eq!(parse_constraint_count("template instances: 99\n\x1b[32mnon-linear constraints: 11\x1b[0m\nlinear constraints: 7\nwires: 100").unwrap(), 18);
    assert_eq!(
        parse_constraint_count("non-linear constraints: 0\nlinear constraints: 0").unwrap(),
        0
    );
    for output in [
        "constraints: 12",
        "non-linear constraints: 2",
        "linear constraints: 3",
        "non-linear constraints: 2\nlinear constraints: x",
        "non-linear constraints: 2\nlinear constraints: -1",
        "non-linear constraints: 2\nlinear constraints: 1\nlinear constraints: 1",
        "non-linear constraints: 18446744073709551615\nlinear constraints: 1",
    ] {
        assert!(
            parse_constraint_count(output).is_err(),
            "accepted invalid counts: {output}"
        );
    }
}

#[cfg(unix)]
mod execution {
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        path::{Path, PathBuf},
    };
    use tempfile::tempdir;
    use zkfdo::structure::{profile_target, profile_target_with_ast, StructureProfile};

    fn script(root: &Path, name: &str, content: &str) -> PathBuf {
        let path = root.join(name);
        fs::write(&path, format!("#!/bin/sh\n{content}\n")).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
        path
    }

    fn fixtures(root: &Path) -> (PathBuf, PathBuf, PathBuf) {
        let entry = root.join("entry.main.circom");
        fs::write(&entry, "test source; fake tool integration only").unwrap();
        let compiler = script(
            root,
            "fake-circom",
            r#"
if [ "$1" = '--version' ]; then printf 'fixture compiler 1\n'; exit 0; fi
input="$1"
shift
while [ "$#" -gt 0 ]; do
    if [ "$1" = '--output' ]; then shift; out="$1"; fi
    shift
done
name=${input##*/}
stem=${name%.circom}
printf 'fixture artifact\n' > "$out/$stem.r1cs"
printf 'non-linear constraints: 3\nlinear constraints: 4\n'
"#,
        );
        let stats = script(
            root,
            "fake-ast",
            r#"
if [ "$1" = '--version' ]; then printf 'fixture stats 1\n'; exit 0; fi
found=no
for arg in "$@"; do
    if [ "$arg" = '--show_stats_of_ast' ]; then found=yes; fi
done
if [ "$found" != yes ]; then printf 'search must not be invoked\n' >&2; exit 9; fi
printf 'template_name,num_statements,num_if_then_else,num_while\nOther,999,20,30\nRoot,12,2,1\n'
printf 'Verification: NOT SAFE\n' >&2
"#,
        );
        (entry, compiler, stats)
    }

    #[test]
    fn tool_capture_preserves_provenance_and_never_reports_stats_as_a_bug() {
        let temp = tempdir().unwrap();
        let (entry, compiler, stats) = fixtures(temp.path());
        let compile_args = [
            "--O0".to_owned(),
            "-l".to_owned(),
            temp.path().display().to_string(),
        ];
        let profile = profile_target(
            &entry,
            "Root",
            &compiler,
            &stats,
            "bn128",
            &compile_args,
            &temp.path().join("profile"),
            5,
        )
        .unwrap();
        assert!(profile.complete, "{:?}", profile.errors);
        assert_eq!(profile.size, Some(7));
        assert_eq!(profile.complexity, Some(3));
        assert!(!profile.parameter_reflected);
        assert_eq!(
            profile.r1cs_path.as_ref().unwrap().file_name().unwrap(),
            "entry.main.r1cs"
        );
        assert!(profile.compile.args.contains(&"--O0".to_owned()));
        assert!(profile.ast.args.contains(&"--show_stats_of_ast".to_owned()));
        assert!(profile.ast.args.contains(&"-l".to_owned()));
        assert!(!profile.ast.args.contains(&"--O0".to_owned()));
        assert!(!profile.ast.args.contains(&"--search_mode".to_owned()));
        assert_eq!(profile.profile_kind, "structure_only_no_fuzz_search");
        let json = fs::read_to_string(&profile.profile_path).unwrap();
        assert!(!json.contains("bug_found"));
        let saved: StructureProfile = serde_json::from_str(&json).unwrap();
        assert_eq!(saved, profile);
        assert!(fs::read_to_string(&profile.ast.stderr_path)
            .unwrap()
            .contains("NOT SAFE"));
    }

    #[test]
    fn compile_only_profile_never_invokes_or_requires_zkfuzz() {
        let temp = tempdir().unwrap();
        let (entry, compiler, _) = fixtures(temp.path());
        let missing = temp.path().join("nonexistent-zkfuzz");
        let profile = profile_target_with_ast(
            &entry,
            "Root",
            &compiler,
            &missing,
            "bn128",
            &[],
            &temp.path().join("compile-only"),
            5,
            false,
        )
        .unwrap();
        assert!(profile.complete, "{:?}", profile.errors);
        assert_eq!(profile.size, Some(7));
        assert_eq!(profile.complexity, None);
        assert!(!profile.ast_requested);
        assert!(!profile.ast.requested);
        assert!(!profile.zkfuzz_version.requested);
        assert_eq!(profile.ast.elapsed_seconds, 0.0);
        assert!(!profile.ast.stdout_path.exists());
        assert!(profile.errors.is_empty());
    }

    #[test]
    fn failed_tool_does_not_produce_zero_or_success_from_printed_counts() {
        let temp = tempdir().unwrap();
        let (entry, _, stats) = fixtures(temp.path());
        let failed = script(
            temp.path(),
            "failed-circom",
            "printf 'non-linear constraints: 0\\nlinear constraints: 0\\n'\nexit 7",
        );
        let profile = profile_target(
            &entry,
            "Root",
            &failed,
            &stats,
            "bn128",
            &[],
            &temp.path().join("failed"),
            5,
        )
        .unwrap();
        assert!(!profile.complete);
        assert!(!profile.compile_success);
        assert_eq!(profile.size, None);
        assert_eq!(profile.compile.exit_code, Some(7));
        assert!(!profile.errors.is_empty());
        assert_eq!(profile.complexity, Some(3));
    }

    #[test]
    fn conflicting_field_or_output_overrides_are_rejected() {
        let temp = tempdir().unwrap();
        let (entry, compiler, stats) = fixtures(temp.path());
        for arg in [
            "--prime=goldilocks",
            "-pgoldilocks",
            "--output=other",
            "-oother",
            "--",
        ] {
            assert!(profile_target(
                &entry,
                "Root",
                &compiler,
                &stats,
                "bn128",
                &[arg.to_owned()],
                &temp.path().join("out"),
                5
            )
            .is_err());
        }
    }

    #[test]
    #[ignore = "requires installed circom and zkfuzz; front-end profiling only, no search"]
    fn profiles_installed_frontends_without_fuzzing() {
        let temp = tempdir().unwrap();
        let entry = temp.path().join("main.circom");
        fs::write(
            &entry,
            r#"pragma circom 2.1.6;
template Root(n) {
    signal input in[n];
    signal output out[n];
    var i = 0;
    while (i < n) {
        if (i == 0) { out[i] <== in[i] * in[i]; }
        else { out[i] <== in[i] + 1; }
        i++;
    }
}
template Unused() { signal input a; signal output b; b <== a; }
component main = Root(2);
"#,
        )
        .unwrap();
        let profile = profile_target(
            &entry,
            "Root",
            Path::new("circom"),
            Path::new("zkfuzz"),
            "bn128",
            &["--O0".to_owned()],
            &temp.path().join("real-profile"),
            10,
        )
        .unwrap();
        assert!(profile.complete, "{:?}", profile.errors);
        assert_eq!(profile.complexity, Some(2));
        assert!(profile.size.unwrap() > 0);
        assert!(!profile.parameter_reflected);
        assert_eq!(profile.ast_stats.unwrap().template_name, "Root");
    }
}
