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
    for subcommand in ["scan", "features", "rank", "schedule", "run", "report"] {
        let mut cmd = Command::cargo_bin("zkfDO").expect("binary exists");

        cmd.arg(subcommand)
            .arg("--help")
            .assert()
            .success()
            .stdout(predicate::str::contains("Usage:"));
    }
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
    .stdout(predicate::str::contains(
        "zkfuzz circuits/main.circom --budget-seconds 60",
    ));
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
