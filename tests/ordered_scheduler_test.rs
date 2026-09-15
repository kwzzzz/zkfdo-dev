#![cfg(unix)]

use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    thread,
    time::{Duration, Instant},
};

use tempfile::tempdir;
use zkfdo::{
    runner::{execute, execute_with_limit, RunRequest, RunStatus, ZkFuzzCommand},
    scheduler::{run_ordered_experiment, OrderedExperimentSummary, OrderedTarget},
};

fn script(root: &Path, name: &str, contents: &str) -> PathBuf {
    let path = root.join(name);
    fs::write(&path, format!("#!/bin/sh\n{contents}\n")).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

fn target(id: &str, binary: &Path, args: Vec<String>) -> OrderedTarget {
    OrderedTarget {
        target_id: id.to_owned(),
        target: PathBuf::from(format!("{id}.circom")),
        command: ZkFuzzCommand {
            binary: PathBuf::from("/bin/sh"),
            args: std::iter::once(binary.display().to_string())
                .chain(args)
                .collect(),
        },
    }
}

fn request(binary: &Path, args: Vec<String>, budget: u64, output: &Path) -> RunRequest {
    RunRequest {
        target: PathBuf::from("fixture.circom"),
        command: ZkFuzzCommand {
            binary: binary.to_path_buf(),
            args,
        },
        budget_seconds: budget,
        output_root: output.to_path_buf(),
    }
}

#[test]
fn supplied_c_a_b_order_matches_real_process_side_effects() {
    let temp = tempdir().unwrap();
    let calls = temp.path().join("actual-calls.txt");
    let executable = script(
        temp.path(),
        "fake-zkfuzz",
        r#"
printf '%s\n' "$1" >> "$2"
printf 'Verification: No Counter Example Found\n'
"#,
    );
    let targets = ["C", "A", "B"].map(|id| {
        target(
            id,
            &executable,
            vec![id.to_owned(), calls.display().to_string()],
        )
    });
    let summary = run_ordered_experiment(&targets, 1, 5, temp.path().join("runs")).unwrap();
    assert_eq!(fs::read_to_string(calls).unwrap(), "C\nA\nB\n");
    assert_eq!(summary.planned_target_ids, ["C", "A", "B"]);
    assert_eq!(
        summary
            .runs
            .iter()
            .map(|run| run.target_id.as_str())
            .collect::<Vec<_>>(),
        ["C", "A", "B"]
    );
    assert!(summary.skipped.is_empty());
    assert!(summary.failures.is_empty());
    let mut previous_completion = 0.0;
    for (index, run) in summary.runs.iter().enumerate() {
        assert_eq!(run.index, index);
        let started = run.process_start_offset_seconds.unwrap();
        assert!(started >= previous_completion);
        assert!(run.completion_offset_seconds >= started);
        assert_eq!(run.result.status, RunStatus::NoCounterexample);
        assert_eq!(run.result.budget_seconds, 1);
        assert!(run.result.stdout_path.exists());
        assert!(run.result.stderr_path.exists());
        assert!(run
            .result
            .stdout_path
            .parent()
            .unwrap()
            .join("result.json")
            .exists());
        previous_completion = run.completion_offset_seconds;
    }
    let saved: OrderedExperimentSummary =
        serde_json::from_slice(&fs::read(&summary.summary_path).unwrap()).unwrap();
    assert_eq!(saved, summary);
}

#[test]
fn nonzero_exit_does_not_become_success_from_summary_text() {
    let temp = tempdir().unwrap();
    for (index, (message, error, expected)) in [
        (
            "Verification: No Counter Example Found",
            "",
            RunStatus::RuntimeError,
        ),
        ("Verification: NOT SAFE", "", RunStatus::RuntimeError),
        (
            "Verification: NOT SAFE",
            "type analysis failed",
            RunStatus::CompileError,
        ),
        (
            "Verification: No Counter Example Found",
            "syntax error",
            RunStatus::ParseError,
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let executable = script(
            temp.path(),
            &format!("failure-{index}"),
            &format!("printf '%s\\n' '{message}'\nprintf '%s\\n' '{error}' >&2\nexit 7"),
        );
        let result = execute(request(&executable, vec![], 2, &temp.path().join("runs"))).unwrap();
        assert_eq!(result.status, expected);
        assert_eq!(result.exit_code, Some(7));
        assert!(!result.timed_out);
    }
}

#[test]
fn exact_subsecond_limit_does_not_round_up_to_nominal_budget() {
    let temp = tempdir().unwrap();
    let timer = Instant::now();
    let result = execute_with_limit(
        request(
            Path::new("/bin/sleep"),
            vec!["2".to_owned()],
            2,
            temp.path(),
        ),
        Duration::from_millis(150),
    )
    .unwrap();
    assert_eq!(result.status, RunStatus::Timeout);
    assert_eq!(result.budget_seconds, 2);
    assert_eq!(result.execution_limit_seconds, 0.15);
    assert!(result.process_start_offset_seconds.is_some());
    assert!(result.wall_time_seconds >= 0.15);
    assert!(timer.elapsed() < Duration::from_millis(900));
}

#[test]
fn timeout_kills_descendant_processes_before_they_can_write() {
    let temp = tempdir().unwrap();
    let marker = temp.path().join("orphan-survived");
    let child_pid = temp.path().join("child.pid");
    let executable = script(
        temp.path(),
        "spawns-child",
        r#"
(
    /bin/sleep 0.6
    printf 'survived\n' > "$1"
) &
printf '%s\n' "$!" > "$2"
wait
"#,
    );
    let result = execute_with_limit(
        request(
            Path::new("/bin/sh"),
            vec![
                executable.display().to_string(),
                marker.display().to_string(),
                child_pid.display().to_string(),
            ],
            2,
            &temp.path().join("runs"),
        ),
        Duration::from_millis(200),
    )
    .unwrap();
    assert_eq!(result.status, RunStatus::Timeout);
    assert!(child_pid.exists(), "the descendant was actually spawned");
    thread::sleep(Duration::from_millis(650));
    assert!(!marker.exists(), "a timed-out descendant kept running");
    assert!(result
        .stdout_path
        .parent()
        .unwrap()
        .join("result.json")
        .exists());
}

#[test]
fn total_deadline_caps_last_run_with_remaining_fraction_and_skips_rest() {
    let temp = tempdir().unwrap();
    let calls = temp.path().join("calls.txt");
    let executable = script(
        temp.path(),
        "timed-fake",
        r#"
printf '%s\n' "$1" >> "$2"
/bin/sleep "$3"
printf 'Verification: No Counter Example Found\n'
"#,
    );
    let targets = [("C", "0.35"), ("A", "3"), ("B", "0")].map(|(id, seconds)| {
        target(
            id,
            &executable,
            vec![
                id.to_owned(),
                calls.display().to_string(),
                seconds.to_owned(),
            ],
        )
    });
    let timer = Instant::now();
    let summary = run_ordered_experiment(&targets, 2, 1, temp.path().join("runs")).unwrap();
    assert_eq!(fs::read_to_string(calls).unwrap(), "C\nA\n");
    assert_eq!(summary.runs.len(), 2);
    assert_eq!(summary.runs[0].result.status, RunStatus::NoCounterexample);
    assert_eq!(summary.runs[1].result.status, RunStatus::Timeout);
    assert!(summary.runs[1].execution_limit_seconds > 0.0);
    assert!(summary.runs[1].execution_limit_seconds < 0.8);
    assert_eq!(summary.runs[1].result.budget_seconds, 2);
    assert_eq!(summary.skipped.len(), 1);
    assert_eq!(summary.skipped[0].target_id, "B");
    assert_eq!(summary.skipped[0].index, 2);
    assert_eq!(summary.skipped[0].reason, "total_budget_exhausted");
    assert!(summary.elapsed_seconds >= 1.0);
    assert!(timer.elapsed() < Duration::from_millis(1700));
}

#[test]
fn timeout_runtime_error_and_spawn_error_all_allow_next_target() {
    let temp = tempdir().unwrap();
    let slow = script(temp.path(), "slow", "exec /bin/sleep 4");
    let failing = script(
        temp.path(),
        "failing",
        "printf 'runtime failure\\n' >&2\nexit 8",
    );
    let okay = script(
        temp.path(),
        "okay",
        "printf 'Verification: No Counter Example Found\\n'",
    );
    let missing = temp.path().join("does-not-exist");
    let mut missing_target = target("missing", &missing, vec![]);
    missing_target.command.binary = missing;
    missing_target.command.args.clear();
    let targets = [
        target("slow", &slow, vec![]),
        target("failed", &failing, vec![]),
        missing_target,
        target("okay", &okay, vec![]),
    ];
    let summary = run_ordered_experiment(&targets, 1, 4, temp.path().join("runs")).unwrap();
    assert_eq!(
        summary
            .runs
            .iter()
            .map(|run| &run.result.status)
            .collect::<Vec<_>>(),
        [
            &RunStatus::Timeout,
            &RunStatus::RuntimeError,
            &RunStatus::SpawnError,
            &RunStatus::NoCounterexample
        ]
    );
    assert!(summary.runs[2].process_start_offset_seconds.is_none());
    assert!(summary.runs[2].result.error.is_some());
    assert!(summary.skipped.is_empty());
    assert!(
        summary.failures.is_empty(),
        "process statuses are preserved as run results"
    );
}

#[test]
fn duplicate_ids_and_invalid_budgets_fail_before_execution() {
    let temp = tempdir().unwrap();
    let missing = temp.path().join("does-not-exist");
    let duplicate = [
        target("same", &missing, vec![]),
        target("same", &missing, vec![]),
    ];
    let output = temp.path().join("runs");
    let error = run_ordered_experiment(&duplicate, 1, 2, &output).unwrap_err();
    assert!(error.to_string().contains("duplicate target ID"));
    assert!(!output.exists());
    assert!(run_ordered_experiment(&[], 0, 1, &output).is_err());
    assert!(run_ordered_experiment(&[], 1, 0, &output).is_err());
}

#[test]
fn empty_ordered_plan_is_saved_without_starting_any_process() {
    let temp = tempdir().unwrap();
    let summary = run_ordered_experiment(&[], 1, 1, temp.path()).unwrap();
    assert!(summary.planned_target_ids.is_empty());
    assert!(summary.runs.is_empty());
    assert!(summary.failures.is_empty());
    assert!(summary.skipped.is_empty());
    assert!(summary.summary_path.exists());
}
