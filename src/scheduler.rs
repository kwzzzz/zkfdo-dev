use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use anyhow::{bail, ensure, Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::runner::{self, RunResult, RunStatus};

const UNIFORM_SCHEDULER: &str = "uniform";

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct ScheduledTarget {
    pub path: PathBuf,
    pub budget_seconds: u64,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct FuzzingSchedule {
    pub scheduler: String,
    pub budget_seconds_per_target: u64,
    pub total_budget_seconds: u64,
    pub targets: Vec<ScheduledTarget>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ExperimentRunSummary {
    pub run_id: String,
    pub target: PathBuf,
    pub budget_seconds: u64,
    pub elapsed_seconds: f64,
    pub exit_code: Option<i32>,
    pub status: RunStatus,
    pub timed_out: bool,
    pub bug_found: bool,
    pub no_counterexample: bool,
    pub seed: Option<u64>,
    pub generation: Option<usize>,
    pub result_path: PathBuf,
    pub stdout_path: PathBuf,
    pub stderr_path: PathBuf,
    pub error: Option<String>,
}

impl From<&RunResult> for ExperimentRunSummary {
    fn from(result: &RunResult) -> Self {
        let run_dir = result
            .stdout_path
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_default();

        Self {
            run_id: result.run_id.clone(),
            target: result.target.clone(),
            budget_seconds: result.budget_seconds,
            elapsed_seconds: result.wall_time_seconds,
            exit_code: result.exit_code,
            status: result.status.clone(),
            timed_out: result.timed_out,
            bug_found: result.status == RunStatus::BugFound,
            no_counterexample: result.status == RunStatus::NoCounterexample,
            seed: result.random_seed,
            generation: result.last_generation,
            result_path: run_dir.join("result.json"),
            stdout_path: result.stdout_path.clone(),
            stderr_path: result.stderr_path.clone(),
            error: result.error.clone(),
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct ExperimentRunFailure {
    pub target: PathBuf,
    pub error: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ExperimentSummary {
    pub experiment_id: String,
    pub scheduler: String,
    pub budget_seconds_per_target: u64,
    pub total_budget_seconds: u64,
    pub target_count: usize,
    pub run_count: usize,
    pub started_at: DateTime<Utc>,
    pub finished_at: DateTime<Utc>,
    pub elapsed_seconds: f64,
    pub runs: Vec<ExperimentRunSummary>,
    pub failures: Vec<ExperimentRunFailure>,
}

pub fn build_uniform_schedule(
    targets: &[PathBuf],
    budget_seconds_per_target: u64,
) -> Result<FuzzingSchedule> {
    if budget_seconds_per_target == 0 {
        bail!("budget_seconds_per_target must be greater than zero");
    }

    let target_count = u64::try_from(targets.len()).context("target count exceeds u64")?;
    let total_budget_seconds = budget_seconds_per_target
        .checked_mul(target_count)
        .context("total budget exceeds u64")?;
    let targets = targets
        .iter()
        .map(|path| ScheduledTarget {
            path: path.clone(),
            budget_seconds: budget_seconds_per_target,
        })
        .collect();

    Ok(FuzzingSchedule {
        scheduler: UNIFORM_SCHEDULER.to_string(),
        budget_seconds_per_target,
        total_budget_seconds,
        targets,
    })
}

pub fn run_uniform_experiment(
    targets: &[PathBuf],
    budget_seconds_per_target: u64,
    zkfuzz_bin: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
) -> Result<ExperimentSummary> {
    let schedule = build_uniform_schedule(targets, budget_seconds_per_target)?;
    let experiment_id = Uuid::new_v4().to_string();
    let experiment_dir = output_root.as_ref().join(&experiment_id);
    let target_runs_dir = experiment_dir.join("runs");
    fs::create_dir_all(&target_runs_dir).with_context(|| {
        format!(
            "failed to create experiment run directory: {}",
            target_runs_dir.display()
        )
    })?;

    let started_at = Utc::now();
    let timer = Instant::now();
    let mut runs = Vec::with_capacity(schedule.targets.len());
    let mut failures = Vec::new();

    for target in &schedule.targets {
        match runner::run_zkfuzz(
            zkfuzz_bin.as_ref(),
            &target.path,
            target.budget_seconds,
            &target_runs_dir,
        ) {
            Ok(result) => runs.push(ExperimentRunSummary::from(&result)),
            Err(error) => failures.push(ExperimentRunFailure {
                target: target.path.clone(),
                error: format!("{error:#}"),
            }),
        }
    }

    let summary = ExperimentSummary {
        experiment_id,
        scheduler: schedule.scheduler,
        budget_seconds_per_target: schedule.budget_seconds_per_target,
        total_budget_seconds: schedule.total_budget_seconds,
        target_count: schedule.targets.len(),
        run_count: runs.len(),
        started_at,
        finished_at: Utc::now(),
        elapsed_seconds: timer.elapsed().as_secs_f64(),
        runs,
        failures,
    };

    write_summary_json(&experiment_dir, &summary)?;
    Ok(summary)
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct OrderedTarget {
    pub target_id: String,
    pub target: PathBuf,
    pub command: runner::ZkFuzzCommand,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct OrderedRunEntry {
    pub target_id: String,
    /// Zero-based index in the supplied plan, including failed spawn attempts.
    pub index: usize,
    /// Monotonic offset to successful spawn-call entry, not an OS exec timestamp.
    pub process_start_offset_seconds: Option<f64>,
    /// Monotonic offset after runner completion and result persistence.
    pub completion_offset_seconds: f64,
    pub execution_limit_seconds: f64,
    pub result: RunResult,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct OrderedRunFailure {
    pub target_id: String,
    pub index: usize,
    pub error: String,
    pub completion_offset_seconds: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct OrderedSkippedTarget {
    pub target_id: String,
    pub index: usize,
    pub reason: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct OrderedExperimentSummary {
    pub experiment_id: String,
    pub scheduler: String,
    pub budget_seconds_per_target: u64,
    pub total_budget_seconds: u64,
    pub planned_target_ids: Vec<String>,
    pub started_at: DateTime<Utc>,
    pub finished_at: DateTime<Utc>,
    /// After input validation through all runner returns; final summary serialization is excluded.
    pub elapsed_seconds: f64,
    pub runs: Vec<OrderedRunEntry>,
    /// Runner infrastructure errors. Process failures remain in runs with their RunStatus.
    pub failures: Vec<OrderedRunFailure>,
    pub skipped: Vec<OrderedSkippedTarget>,
    pub summary_path: PathBuf,
}

pub fn run_ordered_experiment(
    targets: &[OrderedTarget],
    budget_seconds_per_target: u64,
    total_budget_seconds: u64,
    output_root: impl AsRef<Path>,
) -> Result<OrderedExperimentSummary> {
    ensure!(
        budget_seconds_per_target > 0,
        "budget_seconds_per_target must be greater than zero"
    );
    ensure!(
        total_budget_seconds > 0,
        "total_budget_seconds must be greater than zero"
    );
    let mut ids = BTreeSet::new();
    for target in targets {
        ensure!(
            !target.target_id.trim().is_empty(),
            "target ID must not be empty"
        );
        ensure!(
            ids.insert(&target.target_id),
            "duplicate target ID: {}",
            target.target_id
        );
    }

    let started_at = Utc::now();
    let timer = Instant::now();
    let total_limit = Duration::from_secs(total_budget_seconds);
    let target_limit = Duration::from_secs(budget_seconds_per_target);
    let experiment_id = Uuid::new_v4().to_string();
    let experiment_dir = output_root.as_ref().join(&experiment_id);
    let target_runs_dir = experiment_dir.join("runs");
    fs::create_dir_all(&target_runs_dir).with_context(|| {
        format!(
            "failed to create experiment run directory: {}",
            target_runs_dir.display()
        )
    })?;

    let mut runs = Vec::with_capacity(targets.len());
    let mut failures = Vec::new();
    let mut skipped = Vec::new();
    for (index, target) in targets.iter().enumerate() {
        let request = runner::RunRequest {
            target: target.target.clone(),
            command: target.command.clone(),
            budget_seconds: budget_seconds_per_target,
            output_root: target_runs_dir.clone(),
        };
        let remaining = total_limit.saturating_sub(timer.elapsed());
        if remaining.is_zero() {
            skipped.extend(targets[index..].iter().enumerate().map(|(offset, target)| {
                OrderedSkippedTarget {
                    target_id: target.target_id.clone(),
                    index: index + offset,
                    reason: "total_budget_exhausted".to_owned(),
                }
            }));
            break;
        }
        let limit = target_limit.min(remaining);
        let attempt_offset = timer.elapsed().as_secs_f64();
        match runner::execute_with_limit(request, limit) {
            Ok(result) => {
                let process_start_offset_seconds = result
                    .process_start_offset_seconds
                    .map(|offset| attempt_offset + offset);
                runs.push(OrderedRunEntry {
                    target_id: target.target_id.clone(),
                    index,
                    process_start_offset_seconds,
                    completion_offset_seconds: timer.elapsed().as_secs_f64(),
                    execution_limit_seconds: result.execution_limit_seconds,
                    result,
                });
            }
            Err(error) => failures.push(OrderedRunFailure {
                target_id: target.target_id.clone(),
                index,
                error: format!("{error:#}"),
                completion_offset_seconds: timer.elapsed().as_secs_f64(),
            }),
        }
    }

    let summary = OrderedExperimentSummary {
        experiment_id,
        scheduler: "uniform-ordered".to_owned(),
        budget_seconds_per_target,
        total_budget_seconds,
        planned_target_ids: targets
            .iter()
            .map(|target| target.target_id.clone())
            .collect(),
        started_at,
        finished_at: Utc::now(),
        elapsed_seconds: timer.elapsed().as_secs_f64(),
        runs,
        failures,
        skipped,
        summary_path: experiment_dir.join("summary.json"),
    };
    write_summary_json(&experiment_dir, &summary)?;
    // Return the exact persisted representation so callers and the evidence artifact agree even
    // for floating-point offsets whose shortest JSON decimal lies on a rounding boundary.
    Ok(serde_json::from_slice(&fs::read(&summary.summary_path)?)?)
}

fn write_summary_json(experiment_dir: &Path, summary: &impl Serialize) -> Result<()> {
    let summary_path = experiment_dir.join("summary.json");
    let temporary_path = experiment_dir.join("summary.json.tmp");
    let mut json = serde_json::to_vec_pretty(summary)?;
    json.push(b'\n');

    fs::write(&temporary_path, json).with_context(|| {
        format!(
            "failed to write experiment summary: {}",
            temporary_path.display()
        )
    })?;
    fs::rename(&temporary_path, &summary_path).with_context(|| {
        format!(
            "failed to finalize experiment summary: {}",
            summary_path.display()
        )
    })?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::tempdir;

    use super::*;

    #[test]
    fn assigns_the_same_budget_to_every_target() {
        let targets = vec![
            PathBuf::from("a.circom"),
            PathBuf::from("b.circom"),
            PathBuf::from("c.circom"),
        ];

        let schedule = build_uniform_schedule(&targets, 10).expect("uniform schedule");

        assert_eq!(schedule.scheduler, "uniform");
        assert_eq!(schedule.budget_seconds_per_target, 10);
        assert_eq!(schedule.total_budget_seconds, 30);
        assert_eq!(schedule.targets.len(), 3);
        assert!(schedule
            .targets
            .iter()
            .all(|target| target.budget_seconds == 10));
    }

    #[cfg(unix)]
    #[test]
    fn executes_all_targets_and_continues_after_process_error() {
        let temp = tempdir().expect("tempdir");
        let first = temp.path().join("a.circom");
        let failing = temp.path().join("b.circom");
        let last = temp.path().join("c.circom");
        fs::write(
            &first,
            "printf 'Random Seed: 11\\nGeneration: 1/500\\n'\nprintf 'Verification: No Counter Example Found\\n' >&2\n",
        )
        .expect("first target");
        fs::write(&failing, "printf 'runtime failure\\n' >&2\nexit 7\n").expect("failing target");
        fs::write(
            &last,
            "printf 'Random Seed: 33\\nGeneration: 3/500\\n'\nprintf 'Verification: NOT SAFE\\n' >&2\n",
        )
        .expect("last target");
        let targets = vec![first, failing, last];
        let output_root = temp.path().join("experiments");

        let summary = run_uniform_experiment(&targets, 2, "/bin/sh", &output_root)
            .expect("experiment succeeds");

        assert_eq!(summary.target_count, 3);
        assert_eq!(summary.run_count, 3);
        assert!(summary.failures.is_empty());
        assert_eq!(summary.runs[0].status, RunStatus::NoCounterexample);
        assert_eq!(summary.runs[1].status, RunStatus::RuntimeError);
        assert_eq!(summary.runs[2].status, RunStatus::BugFound);
        assert_eq!(summary.runs[2].seed, Some(33));
        assert!(summary.runs.iter().all(|run| run.budget_seconds == 2));
        assert!(summary.runs.iter().all(|run| run.result_path.exists()));
        assert!(summary.runs.iter().all(|run| run.stdout_path.exists()));
        assert!(summary.runs.iter().all(|run| run.stderr_path.exists()));

        let summary_path = output_root
            .join(&summary.experiment_id)
            .join("summary.json");
        let saved: ExperimentSummary =
            serde_json::from_slice(&fs::read(summary_path).expect("summary file"))
                .expect("valid summary");
        assert_eq!(saved.target_count, 3);
        assert_eq!(saved.target_count, saved.run_count);
        assert_eq!(saved.run_count, saved.runs.len());
    }

    #[cfg(unix)]
    #[test]
    fn aggregates_timeout_and_continues_with_next_target() {
        let temp = tempdir().expect("tempdir");
        let slow = temp.path().join("a-slow.circom");
        let next = temp.path().join("b-next.circom");
        fs::write(&slow, "exec /bin/sleep 5\n").expect("slow target");
        fs::write(
            &next,
            "printf 'Random Seed: 22\\nGeneration: 2/500\\n'\nprintf 'Verification: No Counter Example Found\\n' >&2\n",
        )
        .expect("next target");

        let summary =
            run_uniform_experiment(&[slow, next], 1, "/bin/sh", temp.path().join("experiments"))
                .expect("experiment succeeds");

        assert_eq!(summary.target_count, 2);
        assert_eq!(summary.run_count, 2);
        assert_eq!(summary.runs[0].status, RunStatus::Timeout);
        assert!(summary.runs[0].timed_out);
        assert_eq!(summary.runs[1].status, RunStatus::NoCounterexample);
        assert_eq!(summary.runs[1].seed, Some(22));
    }
}
