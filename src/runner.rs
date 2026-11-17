use std::{
    fs::{self, File},
    io::Write,
    path::{Path, PathBuf},
    process::{Command, ExitStatus, Stdio},
    thread,
    time::{Duration, Instant},
};

use anyhow::{bail, Context, Result};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct ZkFuzzCommand {
    pub binary: PathBuf,
    pub args: Vec<String>,
}

impl ZkFuzzCommand {
    pub fn as_shell_words(&self) -> Vec<String> {
        let mut words = Vec::with_capacity(self.args.len() + 1);
        words.push(self.binary.display().to_string());
        words.extend(self.args.clone());
        words
    }
}

#[derive(Debug, Clone)]
pub struct ZkFuzzCommandBuilder {
    binary: PathBuf,
    target: PathBuf,
    extra_args: Vec<String>,
}

impl ZkFuzzCommandBuilder {
    pub fn new(binary: impl Into<PathBuf>, target: impl Into<PathBuf>) -> Self {
        Self {
            binary: binary.into(),
            target: target.into(),
            extra_args: Vec::new(),
        }
    }

    pub fn extra_arg(mut self, arg: impl Into<String>) -> Self {
        self.extra_args.push(arg.into());
        self
    }

    pub fn build(self) -> ZkFuzzCommand {
        let mut args = vec![self.target.display().to_string()];
        args.extend(self.extra_args);

        ZkFuzzCommand {
            binary: self.binary,
            args,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    BugFound,
    NoCounterexample,
    Timeout,
    CompileError,
    RuntimeError,
    ParseError,
    SpawnError,
    Unknown,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct RunResult {
    pub run_id: String,
    pub target: PathBuf,
    pub command: ZkFuzzCommand,
    pub started_at: DateTime<Utc>,
    pub finished_at: DateTime<Utc>,
    pub wall_time_seconds: f64,
    pub budget_seconds: u64,
    #[serde(default)]
    pub execution_limit_seconds: f64,
    /// Offset from execute entry to the successful spawn call (not an OS exec timestamp).
    #[serde(default)]
    pub process_start_offset_seconds: Option<f64>,
    pub timed_out: bool,
    pub exit_code: Option<i32>,
    pub status: RunStatus,
    pub random_seed: Option<u64>,
    pub last_generation: Option<usize>,
    pub stdout_path: PathBuf,
    pub stderr_path: PathBuf,
    pub error: Option<String>,
}

#[derive(Debug, Clone)]
pub struct RunRequest {
    pub target: PathBuf,
    pub command: ZkFuzzCommand,
    pub budget_seconds: u64,
    pub output_root: PathBuf,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct DryRunResult {
    pub command: ZkFuzzCommand,
    pub budget_seconds: u64,
}

pub fn build_dry_run(
    binary: impl AsRef<Path>,
    target: impl AsRef<Path>,
    budget_seconds: u64,
) -> DryRunResult {
    DryRunResult {
        command: ZkFuzzCommandBuilder::new(binary.as_ref(), target.as_ref()).build(),
        budget_seconds,
    }
}

pub fn run_zkfuzz(
    binary: impl AsRef<Path>,
    target: impl AsRef<Path>,
    budget_seconds: u64,
    output_root: impl AsRef<Path>,
) -> Result<RunResult> {
    let target = target.as_ref().to_path_buf();
    let command = ZkFuzzCommandBuilder::new(binary.as_ref(), &target).build();

    execute(RunRequest {
        target,
        command,
        budget_seconds,
        output_root: output_root.as_ref().to_path_buf(),
    })
}

pub fn execute(request: RunRequest) -> Result<RunResult> {
    let limit = Duration::from_secs(request.budget_seconds);
    execute_with_limit(request, limit)
}

pub fn execute_with_limit(request: RunRequest, limit: Duration) -> Result<RunResult> {
    if request.budget_seconds == 0 || limit.is_zero() {
        bail!("budget_seconds and execution limit must be greater than zero");
    }
    let started_at = Utc::now();
    let timer = Instant::now();
    let limit = limit.min(Duration::from_secs(request.budget_seconds));
    let deadline = timer
        .checked_add(limit)
        .context("execution deadline exceeds clock range")?;

    let run_id = Uuid::new_v4().to_string();
    let run_dir = request.output_root.join(&run_id);
    fs::create_dir_all(&run_dir)
        .with_context(|| format!("failed to create run directory: {}", run_dir.display()))?;

    let stdout_path = run_dir.join("stdout.log");
    let stderr_path = run_dir.join("stderr.log");
    let stdout_file = File::create(&stdout_path)
        .with_context(|| format!("failed to create stdout log: {}", stdout_path.display()))?;
    let mut stderr_file = File::create(&stderr_path)
        .with_context(|| format!("failed to create stderr log: {}", stderr_path.display()))?;

    let mut command = Command::new(&request.command.binary);
    command
        .args(&request.command.args)
        .stdout(Stdio::from(stdout_file))
        .stderr(Stdio::from(stderr_file.try_clone()?));
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }

    let mut process_start_offset_seconds = None;
    let (exit_status, timed_out, spawn_error) = if timer.elapsed() >= limit {
        (None, true, None)
    } else {
        let spawn_offset = timer.elapsed().as_secs_f64();
        match command.spawn() {
            Ok(mut child) => {
                process_start_offset_seconds = Some(spawn_offset);
                let (exit_status, timed_out) = wait_with_timeout(&mut child, deadline)?;
                (Some(exit_status), timed_out, None)
            }
            Err(error) => {
                writeln!(stderr_file, "failed to start zkFuzz: {error}")?;
                (None, false, Some(error.to_string()))
            }
        }
    };

    drop(stderr_file);

    let finished_at = Utc::now();
    let wall_time_seconds = timer.elapsed().as_secs_f64();
    let stdout = fs::read_to_string(&stdout_path).unwrap_or_default();
    let stderr = fs::read_to_string(&stderr_path).unwrap_or_default();
    let status = classify_status(
        exit_status.as_ref(),
        timed_out,
        spawn_error.is_some(),
        &stdout,
        &stderr,
    );

    let result = RunResult {
        run_id,
        target: request.target,
        command: request.command,
        started_at,
        finished_at,
        wall_time_seconds,
        budget_seconds: request.budget_seconds,
        execution_limit_seconds: limit.as_secs_f64(),
        process_start_offset_seconds,
        timed_out,
        exit_code: exit_status.as_ref().and_then(ExitStatus::code),
        status,
        random_seed: parse_random_seed(&stdout),
        last_generation: parse_last_generation(&stdout),
        stdout_path,
        stderr_path,
        error: spawn_error,
    };

    write_result_json(&run_dir, &result)?;
    Ok(result)
}

fn wait_with_timeout(
    child: &mut std::process::Child,
    deadline: Instant,
) -> Result<(ExitStatus, bool)> {
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Ok((status, false)),
            Ok(None) => {}
            Err(error) => {
                let _ = kill_process_tree(child);
                let _ = child.wait();
                return Err(error).context("failed to poll zkFuzz process");
            }
        }

        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            let killed = kill_process_tree(child);
            let status = child
                .wait()
                .context("failed to reap timed-out zkFuzz process")?;
            killed?;
            return Ok((status, true));
        }
        thread::sleep(Duration::from_millis(25).min(remaining));
    }
}

fn kill_process_tree(child: &mut std::process::Child) -> Result<()> {
    #[cfg(unix)]
    {
        let group = i32::try_from(child.id()).context("child process ID exceeds pid_t")?;
        // Every command is spawned in its own process group. Negative pid addresses that group.
        let result = unsafe { libc::kill(-group, libc::SIGKILL) };
        if result == -1 {
            let error = std::io::Error::last_os_error();
            if error.raw_os_error() != Some(libc::ESRCH) {
                let _ = child.kill();
                return Err(error).context("failed to kill timed-out zkFuzz process group");
            }
        }
        Ok(())
    }
    #[cfg(not(unix))]
    child
        .kill()
        .context("failed to kill timed-out zkFuzz process")
}

fn classify_status(
    exit_status: Option<&ExitStatus>,
    timed_out: bool,
    spawn_failed: bool,
    stdout: &str,
    stderr: &str,
) -> RunStatus {
    if spawn_failed {
        return RunStatus::SpawnError;
    }

    if timed_out {
        return RunStatus::Timeout;
    }

    let combined = strip_ansi_codes(&format!("{stdout}\n{stderr}"));

    if exit_status.is_some_and(|status| !status.success()) {
        let lowercase = combined.to_ascii_lowercase();

        if lowercase.contains("parse") || lowercase.contains("syntax error") {
            return RunStatus::ParseError;
        }

        if lowercase.contains("compile") || lowercase.contains("type analysis") {
            return RunStatus::CompileError;
        }

        return RunStatus::RuntimeError;
    }

    if combined.contains("NOT SAFE") {
        return RunStatus::BugFound;
    }

    if combined.contains("No Counter Example Found") {
        return RunStatus::NoCounterexample;
    }

    RunStatus::Unknown
}

fn parse_random_seed(stdout: &str) -> Option<u64> {
    let output = strip_ansi_codes(stdout);
    let regex = Regex::new(r"Random Seed:\s*(\d+)").expect("seed regex should compile");
    regex
        .captures(&output)
        .and_then(|captures| captures.get(1))
        .and_then(|value| value.as_str().parse().ok())
}

fn parse_last_generation(stdout: &str) -> Option<usize> {
    let output = strip_ansi_codes(stdout);
    let regex = Regex::new(r"Generation:\s*(\d+)/").expect("generation regex should compile");
    regex
        .captures_iter(&output)
        .filter_map(|captures| captures.get(1))
        .filter_map(|value| value.as_str().parse().ok())
        .last()
}

fn strip_ansi_codes(value: &str) -> String {
    let regex = Regex::new(r"\x1b\[[0-9;]*[A-Za-z]").expect("ANSI regex should compile");
    regex.replace_all(value, "").into_owned()
}

fn write_result_json(run_dir: &Path, result: &RunResult) -> Result<()> {
    let result_path = run_dir.join("result.json");
    let temporary_path = run_dir.join("result.json.tmp");
    let mut json = serde_json::to_vec_pretty(result)?;
    json.push(b'\n');

    fs::write(&temporary_path, json)
        .with_context(|| format!("failed to write run result: {}", temporary_path.display()))?;
    fs::rename(&temporary_path, &result_path)
        .with_context(|| format!("failed to finalize run result: {}", result_path.display()))?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::tempdir;

    use super::*;

    #[test]
    fn dry_run_keeps_budget_out_of_zkfuzz_arguments() {
        let dry_run = build_dry_run("zkfuzz", "circuits/main.circom", 60);

        assert_eq!(
            dry_run.command.as_shell_words(),
            vec!["zkfuzz", "circuits/main.circom"]
        );
        assert_eq!(dry_run.budget_seconds, 60);
    }

    #[test]
    fn parses_ansi_colored_progress_output() {
        let output =
            "🎲 Random Seed: \u{1b}[1;93m42\u{1b}[0m\r🧬 Generation: 3/500\r🧬 Generation: 7/500";

        assert_eq!(parse_random_seed(output), Some(42));
        assert_eq!(parse_last_generation(output), Some(7));
    }

    #[test]
    fn classifies_zkfuzz_summary() {
        assert_eq!(
            classify_status(None, false, false, "", "Verification: NOT SAFE"),
            RunStatus::BugFound
        );
        assert_eq!(
            classify_status(
                None,
                false,
                false,
                "",
                "Verification: No Counter Example Found"
            ),
            RunStatus::NoCounterexample
        );
    }

    #[cfg(unix)]
    #[test]
    fn executes_process_and_writes_structured_result() {
        let temp = tempdir().expect("tempdir");
        let script = temp.path().join("fake-zkfuzz.sh");
        fs::write(
            &script,
            "printf 'Random Seed: 42\\nGeneration: 7/500\\n'\nprintf 'Verification: NOT SAFE\\n' >&2\n",
        )
        .expect("script");

        let result = execute(RunRequest {
            target: PathBuf::from("circuit.circom"),
            command: ZkFuzzCommand {
                binary: PathBuf::from("/bin/sh"),
                args: vec![script.display().to_string()],
            },
            budget_seconds: 2,
            output_root: temp.path().join("runs"),
        })
        .expect("run succeeds");

        assert_eq!(result.status, RunStatus::BugFound);
        assert_eq!(result.random_seed, Some(42));
        assert_eq!(result.last_generation, Some(7));
        assert!(!result.timed_out);
        assert!(result.stdout_path.exists());
        assert!(result.stderr_path.exists());
        assert!(temp
            .path()
            .join("runs")
            .join(&result.run_id)
            .join("result.json")
            .exists());
    }

    #[cfg(unix)]
    #[test]
    fn kills_process_after_budget_expires() {
        let temp = tempdir().expect("tempdir");

        let result = execute(RunRequest {
            target: PathBuf::from("slow.circom"),
            command: ZkFuzzCommand {
                binary: PathBuf::from("/bin/sleep"),
                args: vec!["5".to_string()],
            },
            budget_seconds: 1,
            output_root: temp.path().join("runs"),
        })
        .expect("run result");

        assert_eq!(result.status, RunStatus::Timeout);
        assert!(result.timed_out);
        assert!(result.wall_time_seconds >= 1.0);
        assert!(result.wall_time_seconds < 3.0);
    }
}
