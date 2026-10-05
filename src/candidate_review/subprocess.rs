use std::{
    io::{self, Read},
    process::{Child, Command, ExitStatus, Stdio},
    thread,
    time::{Duration, Instant},
};

use anyhow::{ensure, Context, Result};

pub(crate) const PREDICATE_TIMEOUT: Duration = Duration::from_secs(60);
pub(crate) const GENERATOR_TIMEOUT: Duration = Duration::from_secs(600);
pub(crate) const COMPILER_TIMEOUT: Duration = Duration::from_secs(600);
pub(crate) const EXTERNAL_VERIFIER_TIMEOUT: Duration = Duration::from_secs(600);

#[derive(Debug)]
pub(crate) struct BoundedOutput {
    pub(crate) status: ExitStatus,
    pub(crate) timed_out: bool,
    pub(crate) stdout_nonempty: bool,
    pub(crate) stderr_nonempty: bool,
}

pub(crate) fn run_bounded(command: &mut Command, timeout: Duration) -> Result<BoundedOutput> {
    ensure!(!timeout.is_zero(), "subprocess timeout must be positive");
    let deadline = Instant::now()
        .checked_add(timeout)
        .context("subprocess deadline exceeds clock range")?;
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }

    let mut child = command.spawn().context("start bounded subprocess")?;
    let stdout = child.stdout.take().context("capture subprocess stdout")?;
    let stderr = child.stderr.take().context("capture subprocess stderr")?;
    let stdout_thread = thread::spawn(move || drain_stream(stdout));
    let stderr_thread = thread::spawn(move || drain_stream(stderr));

    let (status, mut timed_out) = loop {
        match child.try_wait() {
            Ok(Some(status)) => break (status, false),
            Ok(None) => {}
            Err(error) => {
                let _ = kill_process_group(&mut child);
                let _ = child.wait();
                return Err(error).context("poll bounded subprocess");
            }
        }

        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            let kill_result = kill_process_group(&mut child);
            let status = child.wait().context("reap timed-out subprocess")?;
            kill_result?;
            break (status, true);
        }
        thread::sleep(Duration::from_millis(25).min(remaining));
    };

    // A launcher may exit after leaving a descendant with the pipes open. Wait only until the
    // same deadline, then terminate the still-existing process group before joining the drains.
    while !stdout_thread.is_finished() || !stderr_thread.is_finished() {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            timed_out = true;
            kill_process_group(&mut child)?;
            break;
        }
        thread::sleep(Duration::from_millis(25).min(remaining));
    }

    let stdout_nonempty = join_drain(stdout_thread, "stdout")?;
    let stderr_nonempty = join_drain(stderr_thread, "stderr")?;
    Ok(BoundedOutput {
        status,
        timed_out,
        stdout_nonempty,
        stderr_nonempty,
    })
}

/// Runs like [`run_bounded`], but writes stdout and stderr to `log` so callers can read
/// tool verdicts afterwards. Returns the exit status and whether the deadline expired.
pub(crate) fn run_bounded_logged(
    command: &mut Command,
    timeout: Duration,
    log: &std::path::Path,
) -> Result<(ExitStatus, bool)> {
    ensure!(!timeout.is_zero(), "subprocess timeout must be positive");
    let deadline = Instant::now()
        .checked_add(timeout)
        .context("subprocess deadline exceeds clock range")?;
    let file = std::fs::File::create(log).context("create subprocess log")?;
    command
        .stdin(Stdio::null())
        .stdout(file.try_clone().context("clone subprocess log")?)
        .stderr(file);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut child = command.spawn().context("start bounded subprocess")?;
    loop {
        if let Some(status) = child.try_wait().context("poll bounded subprocess")? {
            return Ok((status, false));
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            let kill_result = kill_process_group(&mut child);
            let status = child.wait().context("reap timed-out subprocess")?;
            kill_result?;
            return Ok((status, true));
        }
        thread::sleep(Duration::from_millis(10).min(remaining));
    }
}

fn drain_stream(mut stream: impl Read) -> io::Result<bool> {
    let mut nonempty = false;
    let mut buffer = [0_u8; 8 * 1024];
    loop {
        let count = stream.read(&mut buffer)?;
        if count == 0 {
            return Ok(nonempty);
        }
        nonempty = true;
    }
}

fn join_drain(handle: thread::JoinHandle<io::Result<bool>>, stream_name: &str) -> Result<bool> {
    handle
        .join()
        .map_err(|_| anyhow::anyhow!("{stream_name} drain thread panicked"))?
        .with_context(|| format!("drain bounded subprocess {stream_name}"))
}

fn kill_process_group(child: &mut Child) -> Result<()> {
    #[cfg(unix)]
    {
        let group = i32::try_from(child.id()).context("subprocess ID exceeds pid_t")?;
        // The child was spawned in its own group, so a negative PID cannot signal this process.
        // macOS can refuse the signal with EPERM while a just-forked member is still in execve,
        // so that transient refusal is retried briefly before it is reported.
        let mut attempts = 0;
        while unsafe { libc::kill(-group, libc::SIGKILL) } == -1 {
            let error = io::Error::last_os_error();
            match error.raw_os_error() {
                Some(libc::ESRCH) => break,
                Some(libc::EPERM) if attempts < 50 => {
                    attempts += 1;
                    thread::sleep(Duration::from_millis(2));
                }
                _ => {
                    let _ = child.kill();
                    return Err(error).context("kill bounded subprocess group");
                }
            }
        }
        Ok(())
    }
    #[cfg(not(unix))]
    child.kill().context("kill bounded subprocess")
}

#[cfg(test)]
mod tests {
    use std::{fs, path::Path, process::Command, time::Duration};

    use tempfile::tempdir;

    use super::*;

    #[test]
    fn timeout_must_be_positive() {
        let mut command = Command::new("definitely-not-started");
        assert!(run_bounded(&mut command, Duration::ZERO).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn drains_unbounded_output_without_retaining_it() {
        let mut command = Command::new("/bin/sh");
        command
            .arg("-c")
            .arg("while :; do printf 0123456789abcdef; done")
            .env_clear()
            .stdin(Stdio::null());
        let output = run_bounded(&mut command, Duration::from_millis(75)).unwrap();
        assert!(output.timed_out);
        assert!(output.stdout_nonempty);
        assert!(!output.stderr_nonempty);
    }

    #[cfg(unix)]
    #[test]
    fn timeout_kills_the_child_process_group() {
        let temporary = tempdir().unwrap();
        let marker = temporary.path().join("descendant-survived");
        let mut command = Command::new("/bin/sh");
        command
            .arg("-c")
            .arg("(/bin/sleep 0.30; : > \"$1\") & while :; do :; done")
            .arg("bounded-test")
            .arg(&marker)
            .env_clear()
            .stdin(Stdio::null());
        let output = run_bounded(&mut command, Duration::from_millis(50)).unwrap();
        assert!(output.timed_out);
        thread::sleep(Duration::from_millis(400));
        assert!(!Path::new(&marker).exists());
    }

    #[cfg(unix)]
    #[test]
    fn successful_silent_process_is_reported_without_stream_content() {
        let temporary = tempdir().unwrap();
        let marker = temporary.path().join("completed");
        let mut command = Command::new("/bin/sh");
        command
            .arg("-c")
            .arg(": > \"$1\"")
            .arg("bounded-test")
            .arg(&marker)
            .env_clear()
            .stdin(Stdio::null());
        let output = run_bounded(&mut command, Duration::from_secs(1)).unwrap();
        assert!(!output.timed_out);
        assert!(output.status.success());
        assert!(!output.stdout_nonempty);
        assert!(!output.stderr_nonempty);
        assert_eq!(fs::read(marker).unwrap(), b"");
    }
}
