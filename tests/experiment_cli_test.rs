use assert_cmd::Command;
use predicates::prelude::*;
use tempfile::tempdir;

#[test]
fn nested_experiment_help_exposes_the_four_explicit_stages() {
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args(["experiment", "--help"])
        .assert()
        .success()
        .stdout(
            predicate::str::contains("prepare")
                .and(predicate::str::contains("plan"))
                .and(predicate::str::contains("run"))
                .and(predicate::str::contains("evaluate")),
        );
    for stage in ["prepare", "plan", "run", "evaluate"] {
        Command::cargo_bin("zkfDO")
            .unwrap()
            .args(["experiment", stage, "--help"])
            .assert()
            .success()
            .stdout(predicate::str::contains("Usage:"));
    }
}

#[test]
fn experiment_run_requires_both_explicit_time_budgets_before_loading_a_plan() {
    let temp = tempdir().unwrap();
    let output = temp.path().join("not-created");
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args([
            "experiment",
            "run",
            "--plan",
            "missing-plan.json",
            "--budget-seconds",
            "2",
            "--output",
        ])
        .arg(&output)
        .assert()
        .failure()
        .stderr(predicate::str::contains("--total-budget-seconds"));
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args([
            "experiment",
            "run",
            "--plan",
            "missing-plan.json",
            "--total-budget-seconds",
            "2",
            "--output",
        ])
        .arg(&output)
        .assert()
        .failure()
        .stderr(predicate::str::contains("--budget-seconds"));
    assert!(!output.exists());
}

#[test]
fn random_plan_requires_a_separate_ranking_seed() {
    let temp = tempdir().unwrap();
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args([
            "experiment",
            "plan",
            "--prepared",
            "missing.json",
            "--strategy",
            "random",
            "--output",
        ])
        .arg(temp.path().join("plan.json"))
        .assert()
        .failure()
        .stderr(predicate::str::contains("--ranking-seed"));
}

#[test]
fn plans_require_explicit_supported_static_strategy() {
    let temp = tempdir().unwrap();
    for strategy in ["adaptive", "risk-cost", "boian"] {
        Command::cargo_bin("zkfDO")
            .unwrap()
            .args([
                "experiment",
                "plan",
                "--prepared",
                "missing.json",
                "--strategy",
                strategy,
                "--output",
            ])
            .arg(temp.path().join("plan.json"))
            .assert()
            .failure()
            .stderr(predicate::str::contains("unknown static ranking strategy"));
    }
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args([
            "experiment",
            "plan",
            "--prepared",
            "missing.json",
            "--output",
        ])
        .arg(temp.path().join("plan.json"))
        .assert()
        .failure()
        .stderr(predicate::str::contains("--strategy"));
}

#[test]
fn zero_budgets_are_rejected_without_starting_tools() {
    let temp = tempdir().unwrap();
    for (per_target, total) in [("0", "2"), ("2", "0")] {
        Command::cargo_bin("zkfDO")
            .unwrap()
            .args([
                "experiment",
                "run",
                "--plan",
                "missing.json",
                "--budget-seconds",
                per_target,
                "--total-budget-seconds",
                total,
                "--output",
            ])
            .arg(temp.path())
            .assert()
            .failure()
            .stderr(predicate::str::contains("invalid value '0'"));
    }
    Command::cargo_bin("zkfDO")
        .unwrap()
        .args([
            "experiment",
            "prepare",
            "--manifest",
            "missing.json",
            "--tool-timeout-seconds",
            "0",
            "--output",
        ])
        .arg(temp.path())
        .assert()
        .failure()
        .stderr(predicate::str::contains("invalid value '0'"));
}

#[cfg(unix)]
mod workflow {
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        path::{Path, PathBuf},
    };

    use assert_cmd::Command;
    use serde_json::{json, Value};
    use tempfile::tempdir;

    fn script(root: &Path, name: &str, body: &str) -> PathBuf {
        let path = root.join(name);
        fs::write(&path, format!("#!/bin/sh\n{body}\n")).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
        path
    }

    fn prepare_path_order_fixture(root: &Path) -> Value {
        let source_root = root.join("sources");
        fs::create_dir(&source_root).unwrap();
        let definitions = ["C", "A", "B"]
            .into_iter()
            .map(|label| {
                let entrypoint = source_root.join(format!("{label}.circom"));
                fs::write(
                    &entrypoint,
                    format!(
                        "pragma circom 2.1.0;\ntemplate Root{label}() {{\nsignal input x;\nsignal output y;\ny <== x;\n}}\ncomponent main = Root{label}();\n"
                    ),
                )
                .unwrap();
                json!({
                    "label": label,
                    "project": "cli-fixture",
                    "revision": "test-fixture-v1",
                    "project_root": source_root,
                    "entrypoint": entrypoint,
                    "template_name": format!("Root{label}"),
                    "concrete_parameters": [],
                    "prime": "bn128",
                    "compile_args": [],
                    "mode": "original",
                    "input_assumptions": "One unconstrained field input; synthetic CLI fixture.",
                    "known_defects": []
                })
            })
            .collect::<Vec<_>>();
        let manifest = root.join("manifest.json");
        fs::write(
            &manifest,
            serde_json::to_vec_pretty(&json!({
                "schema_version": 1,
                "name": "cli-fixture",
                "description": "Synthetic command integration only, no defect claims.",
                "targets": definitions
            }))
            .unwrap(),
        )
        .unwrap();
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
printf 'non-linear constraints: 1\nlinear constraints: 0\n'
"#,
        );
        let result = Command::cargo_bin("zkfDO")
            .unwrap()
            .args(["experiment", "prepare", "--manifest"])
            .arg(manifest)
            .args(["--strategy", "path-order", "--circom-bin"])
            .arg(compiler)
            .arg("--zkfuzz-bin")
            .arg(root.join("unavailable-zkfuzz"))
            .arg("--circomspect-bin")
            .arg(root.join("unavailable-analyzer"))
            .args(["--tool-timeout-seconds", "10", "--output"])
            .arg(root.join("prepared"))
            .assert()
            .success()
            .get_output()
            .stdout
            .clone();
        serde_json::from_slice(&result).unwrap()
    }

    #[test]
    fn bare_output_paths_support_saved_plan_run_and_evaluation() {
        let temp = tempdir().unwrap();
        let prepared = prepare_path_order_fixture(temp.path());
        let plan_path = temp.path().join("plan.json");
        let calls = temp.path().join("fuzz-calls.txt");
        let fake_zkfuzz = script(
            temp.path(),
            "fake-zkfuzz",
            r#"
if [ "$1" = '--version' ]; then printf 'fixture zkFuzz 1\n'; exit 0; fi
name=${1##*/}
printf '%s\n' "$name" >> "$CLI_FUZZ_LOG"
printf 'Random Seed: 123\nGeneration: 1/500\n'
if [ "$name" = 'B.circom' ]; then
    printf 'fixture failure\n' >&2
    exit 9
fi
printf 'Verification: No Counter Example Found\n'
"#,
        );
        let plan_bytes = Command::cargo_bin("zkfDO")
            .unwrap()
            .current_dir(temp.path())
            .args(["experiment", "plan", "--prepared"])
            .arg(prepared["report_path"].as_str().unwrap())
            .args(["--strategy", "path-order", "--config"])
            .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("configs/static-ranking.json"))
            .args(["--output", "plan.json"])
            .env("CLI_FUZZ_LOG", &calls)
            .assert()
            .success()
            .get_output()
            .stdout
            .clone();
        let plan: Value = serde_json::from_slice(&plan_bytes).unwrap();
        let persisted_plan: Value = serde_json::from_slice(&fs::read(&plan_path).unwrap()).unwrap();
        assert_eq!(plan, persisted_plan);
        let plan_targets = plan["targets"].as_array().unwrap();
        assert_eq!(
            plan_targets
                .iter()
                .map(|target| target["definition"]["label"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["A", "B", "C"]
        );
        let planned_ids = plan_targets
            .iter()
            .map(|target| target["target_id"].clone())
            .collect::<Vec<_>>();
        assert!(!calls.exists(), "planning must not launch the fuzz backend");

        let outcome_bytes = Command::cargo_bin("zkfDO")
            .unwrap()
            .args(["experiment", "run", "--plan"])
            .arg(&plan_path)
            .arg("--zkfuzz-bin")
            .arg(fake_zkfuzz)
            .args([
                "--budget-seconds",
                "10",
                "--total-budget-seconds",
                "30",
                "--zkfuzz-seed",
                "123",
                "--output",
            ])
            .arg(temp.path().join("runs"))
            .env("CLI_FUZZ_LOG", &calls)
            .assert()
            .success()
            .get_output()
            .stdout
            .clone();
        assert_eq!(
            fs::read_to_string(calls).unwrap(),
            "A.circom\nB.circom\nC.circom\n"
        );
        let outcome: Value = serde_json::from_slice(&outcome_bytes).unwrap();
        assert_eq!(
            outcome["scheduler"]["planned_target_ids"],
            json!(planned_ids)
        );
        let runs = outcome["scheduler"]["runs"].as_array().unwrap();
        assert_eq!(
            runs.iter()
                .map(|run| run["target_id"].clone())
                .collect::<Vec<_>>(),
            planned_ids
        );
        assert_eq!(
            runs.iter()
                .map(|run| run["result"]["status"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["no_counterexample", "runtime_error", "no_counterexample"]
        );
        assert!(runs
            .iter()
            .all(|run| run["process_start_offset_seconds"].is_number()));
        assert_eq!(outcome["scheduler"]["failures"], json!([]));
        assert_eq!(outcome["scheduler"]["skipped"], json!([]));
        assert_eq!(outcome["mutation_settings"]["effective_seed"], 123);
        assert_eq!(outcome["mutation_settings"]["seed_controlled"], true);
        let persisted_outcome: Value =
            serde_json::from_slice(&fs::read(outcome["report_path"].as_str().unwrap()).unwrap())
                .unwrap();
        assert_eq!(outcome, persisted_outcome);
        // The CLI's complete stdout is also a portable saved outcome input.
        let outcome_path = temp.path().join("saved-outcome.json");
        fs::write(&outcome_path, outcome_bytes).unwrap();
        let evaluation_path = temp.path().join("evaluation.json");
        let evaluation_bytes = Command::cargo_bin("zkfDO")
            .unwrap()
            .current_dir(temp.path())
            .args(["experiment", "evaluate", "--plan"])
            .arg(plan_path)
            .arg("--outcome")
            .arg(outcome_path)
            .args(["--output", "evaluation.json"])
            .assert()
            .success()
            .get_output()
            .stdout
            .clone();
        let evaluation: Value = serde_json::from_slice(&evaluation_bytes).unwrap();
        let persisted_evaluation: Value =
            serde_json::from_slice(&fs::read(evaluation_path).unwrap()).unwrap();
        assert_eq!(evaluation, persisted_evaluation);
        assert_eq!(evaluation["planned_target_ids"], json!(planned_ids));
        assert_eq!(
            evaluation["actual_process_start_target_ids"],
            json!(planned_ids)
        );
        assert_eq!(evaluation["status_counts"]["no_counterexample"], 2);
        assert_eq!(evaluation["status_counts"]["runtime_error"], 1);
        assert_eq!(evaluation["confirmed_project_defect_count"], 0);
        assert_eq!(evaluation["reviewed_confirmation_count"], 0);
        assert_eq!(evaluation["backend_bug_candidate_count"], 0);
        assert_eq!(
            evaluation["first_confirmed_defect_observed_by_seconds"],
            Value::Null
        );
    }

    #[test]
    fn path_order_preparation_requires_no_analyzer_or_ast_frontend() {
        let temp = tempdir().unwrap();
        let prepared = prepare_path_order_fixture(temp.path());
        assert_eq!(prepared["profile_strategy"], "path-order");
        let targets = prepared["targets"].as_array().unwrap();
        assert_eq!(targets.len(), 3);
        for target in targets {
            assert_eq!(target["eligible"], true, "{target:#}");
            assert_eq!(target["ranking"]["size"], 1);
            assert_eq!(target["ranking"]["risk_score"], Value::Null);
            assert_eq!(target["ranking"]["complexity"], Value::Null);
            assert_eq!(target["structure"]["ast_requested"], false);
            assert_eq!(target["structure"]["ast"]["requested"], false);
            assert_eq!(target["semantic"], Value::Null);
            assert!(
                !Path::new(target["structure"]["ast"]["stdout_path"].as_str().unwrap()).exists()
            );
        }
        let persisted: Value =
            serde_json::from_slice(&fs::read(prepared["report_path"].as_str().unwrap()).unwrap())
                .unwrap();
        assert_eq!(persisted, prepared);
    }
}
