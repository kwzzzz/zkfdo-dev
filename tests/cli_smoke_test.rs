use assert_cmd::Command;
use predicates::prelude::*;

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
