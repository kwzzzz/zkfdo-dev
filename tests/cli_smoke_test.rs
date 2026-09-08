use assert_cmd::Command;
use predicates::prelude::*;
use std::fs;
use tempfile::tempdir;

#[test]
fn top_level_help_mentions_zkfdo() {
    let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");

    cmd.arg("--help").assert().success().stdout(
        predicate::str::contains("zkfDO")
            .and(predicate::str::contains("scan"))
            .and(predicate::str::contains("run")),
    );
}

#[test]
fn subcommand_help_is_available() {
    for subcommand in [
        "scan", "targets", "features", "rank", "schedule", "run", "report",
    ] {
        let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");

        cmd.arg(subcommand)
            .arg("--help")
            .assert()
            .success()
            .stdout(predicate::str::contains("Usage:"));
    }
}

#[test]
fn targets_discovers_concrete_instantiations_without_compiling() {
    let temp = tempdir().expect("tempdir");
    let fixture =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/target_discovery");

    let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");
    cmd.args(["targets", "--project"])
        .arg(fixture)
        .args(["--output"])
        .arg(temp.path())
        .arg("--no-validate")
        .assert()
        .success()
        .stdout(
            predicate::str::contains("\"entrypoint_status\": \"found\"")
                .and(predicate::str::contains("\"template_name\": \"RSA\""))
                .and(predicate::str::contains("\"concrete_parameters\": ["))
                .and(predicate::str::contains("\"generated_wrapper_count\": 7")),
        );
}

#[test]
fn run_dry_run_prints_zkfuzz_command() {
    let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");

    cmd.args([
        "run",
        "--target",
        "circuits/main.circom",
        "--budget-seconds",
        "60",
        "--dry-run",
    ])
    .assert()
    .success()
    .stdout(predicate::str::contains("zkfuzz circuits/main.circom"));
}

#[cfg(unix)]
#[test]
fn run_executes_process_and_outputs_result_json() {
    let temp = tempdir().expect("tempdir");
    let fake_zkfuzz = temp.path().join("fake-zkfuzz.sh");
    fs::write(
        &fake_zkfuzz,
        "printf 'Random Seed: 123\\nGeneration: 4/500\\n'\nprintf 'Verification: No Counter Example Found\\n' >&2\n",
    )
    .expect("fake zkFuzz");

    let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");

    cmd.args(["run", "--target"])
        .arg(&fake_zkfuzz)
        .args([
            "--zkfuzz-bin",
            "/bin/sh",
            "--budget-seconds",
            "2",
            "--output",
        ])
        .arg(temp.path().join("runs"))
        .assert()
        .success()
        .stdout(
            predicate::str::contains("\"status\": \"no_counterexample\"")
                .and(predicate::str::contains("\"random_seed\": 123"))
                .and(predicate::str::contains("\"last_generation\": 4")),
        );
}

#[cfg(unix)]
#[test]
fn schedule_runs_discovered_targets_and_writes_summary() {
    let temp = tempdir().expect("tempdir");
    let project = temp.path().join("project");
    let output = temp.path().join("experiments");
    fs::create_dir_all(&project).expect("project directory");
    fs::write(
        project.join("a.circom"),
        "printf 'Random Seed: 101\\nGeneration: 1/500\\n'\nprintf 'Verification: No Counter Example Found\\n' >&2\n",
    )
    .expect("first target");
    fs::write(
        project.join("b.circom"),
        "printf 'fake target error\\n' >&2\nexit 9\n",
    )
    .expect("second target");

    let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");
    cmd.args(["schedule", "--project"])
        .arg(&project)
        .args([
            "--zkfuzz-bin",
            "/bin/sh",
            "--budget-seconds",
            "2",
            "--output",
        ])
        .arg(&output)
        .assert()
        .success()
        .stdout(
            predicate::str::contains("\"scheduler\": \"uniform\"")
                .and(predicate::str::contains("\"target_count\": 2"))
                .and(predicate::str::contains("\"run_count\": 2"))
                .and(predicate::str::contains("\"status\": \"runtime_error\"")),
        );

    let experiment_dirs = fs::read_dir(&output)
        .expect("output directory")
        .collect::<Result<Vec<_>, _>>()
        .expect("experiment entries");
    assert_eq!(experiment_dirs.len(), 1);

    let experiment_dir = experiment_dirs[0].path();
    assert!(experiment_dir.join("summary.json").exists());
    let target_runs = fs::read_dir(experiment_dir.join("runs"))
        .expect("target runs directory")
        .collect::<Result<Vec<_>, _>>()
        .expect("target run entries");
    assert_eq!(target_runs.len(), 2);
}

#[test]
fn scan_outputs_discovered_circom_targets() {
    let temp = tempdir().expect("tempdir");
    fs::create_dir_all(temp.path().join("circuits")).expect("circuits dir");
    fs::write(
        temp.path().join("circuits/main.circom"),
        "component main = Main();",
    )
    .expect("main circuit");

    let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");

    cmd.args(["scan", "--project"])
        .arg(temp.path())
        .assert()
        .success()
        .stdout(predicate::str::contains("main.circom"));
}

#[test]
fn features_outputs_static_feature_json() {
    let temp = tempdir().expect("tempdir");
    fs::write(
        temp.path().join("main.circom"),
        "template Main(){ signal input a; signal output out; out <== a; }",
    )
    .expect("main circuit");

    let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");

    cmd.args(["features", "--project"])
        .arg(temp.path())
        .assert()
        .success()
        .stdout(
            predicate::str::contains("\"signal_input_count\": 1")
                .and(predicate::str::contains("\"constraint_count_estimate\": 1")),
        );
}

#[test]
fn rank_outputs_ranked_target_json() {
    let temp = tempdir().expect("tempdir");
    fs::write(
        temp.path().join("safe.circom"),
        "template Safe(){ signal input a; signal output out; out <== a; }",
    )
    .expect("safe circuit");
    fs::write(
        temp.path().join("risky.circom"),
        "template Risky(){ signal input a; signal output out; out <-- a / 2; assert(out === a); }",
    )
    .expect("risky circuit");

    let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");

    cmd.args(["rank", "--project"])
        .arg(temp.path())
        .assert()
        .success()
        .stdout(
            predicate::str::contains("risky.circom")
                .and(predicate::str::contains("\"risk_score\""))
                .and(predicate::str::contains("\"rank_score\"")),
        );
}
