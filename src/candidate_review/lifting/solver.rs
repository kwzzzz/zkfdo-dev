//! Per-request, value-free solver telemetry. Search results never certify a verdict.

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn real_unsat_with_requested_model_keeps_its_verdict() {
        reset();
        let dir = tempfile::tempdir().unwrap();
        let result = run(
            Path::new("z3"),
            "(declare-const w1 Int)\n(assert false)\n(check-sat)\n(get-value (w1))\n".to_owned(),
            &dir.path().join("unsat"),
            Duration::from_secs(1),
        )
        .unwrap();
        assert!(result.starts_with("unsat\n"));
        assert_eq!(take()[0].outcome, "unsat");
    }

    #[test]
    fn nonzero_tool_exit_must_not_certify_unsat() {
        reset();
        let dir = tempfile::tempdir().unwrap();
        let fake = dir.path().join("bad-z3");
        std::fs::write(&fake, "#!/bin/sh\nprintf 'unsat\n'\nexit 7\n").unwrap();
        std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
        assert!(run(
            &fake,
            "(check-sat)\n".to_owned(),
            &dir.path().join("q"),
            Duration::from_secs(1)
        )
        .is_err());
        assert_eq!(take()[0].outcome, "tool_error");
    }

    #[test]
    fn unknown_reason_and_tool_errors_are_separate_from_unsat() {
        reset();
        let dir = tempfile::tempdir().unwrap();
        let fake = dir.path().join("z3");
        std::fs::write(
            &fake,
            "#!/bin/sh\nprintf 'unknown\n(:reason-unknown \"incomplete\")\n'\n",
        )
        .unwrap();
        std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
        let answer = run(
            &fake,
            "(check-sat)\n".to_owned(),
            &dir.path().join("a"),
            std::time::Duration::from_secs(1),
        )
        .unwrap();
        assert!(answer.starts_with("unknown"));
        let calls = take();
        assert_eq!(calls[0].outcome, "unknown");
        assert_eq!(calls[0].unknown_reason.as_deref(), Some("incomplete"));
        assert!(calls[0].seconds >= 0.0);
        assert!(run(
            &dir.path().join("missing"),
            "(check-sat)\n".to_owned(),
            &dir.path().join("b"),
            std::time::Duration::from_secs(1)
        )
        .is_err());
        assert_eq!(take()[0].outcome, "tool_error");
    }
}

use super::super::subprocess::run_bounded_logged;
use anyhow::{bail, Result};
use serde::Serialize;
use std::{
    cell::RefCell,
    path::Path,
    process::Command,
    time::{Duration, Instant},
};

#[derive(Debug, Clone, Serialize)]
pub struct Call {
    pub query: String,
    pub seconds: f64,
    pub timeout_seconds: f64,
    pub outcome: String,
    pub exit_code: Option<i32>,
    pub unknown_reason: Option<String>,
}
thread_local! { static CALLS: RefCell<Vec<Call>> = const { RefCell::new(Vec::new()) }; }
pub(crate) fn reset() {
    CALLS.with(|calls| calls.borrow_mut().clear());
}
pub(crate) fn take() -> Vec<Call> {
    CALLS.with(|calls| std::mem::take(&mut *calls.borrow_mut()))
}

pub(crate) fn run(
    z3: &Path,
    mut text: String,
    scratch: &Path,
    timeout: Duration,
) -> Result<String> {
    let _profile = super::profile_v24::span("solver.run");
    // z3 reports the reason for the preceding check; querying it does not launch a new solve.
    text.push_str("(get-info :reason-unknown)\n");
    let started = Instant::now();
    let mut call = Call {
        query: scratch.to_string_lossy().into_owned(),
        seconds: 0.0,
        timeout_seconds: timeout.as_secs_f64(),
        outcome: "tool_error".to_owned(),
        exit_code: None,
        unknown_reason: None,
    };
    let answer = (|| {
        let wants_model = text
            .lines()
            .any(|line| line.trim_start().starts_with("(get-value "));
        let query = scratch.with_extension("smt2");
        std::fs::write(&query, text)?;
        let log = scratch.with_extension("z3.log");
        let mut command = Command::new(z3);
        command.arg(&query);
        let (status, timed_out) = super::profile_v24::measure("solver.subprocess", || {
            let deadline = if super::search_v27::enabled() {
                timeout
            } else {
                timeout + Duration::from_secs(10)
            };
            run_bounded_logged(&mut command, deadline, &log)
        })?;
        call.exit_code = status.code();
        let output = std::fs::read_to_string(log)?;
        if timed_out {
            call.outcome = "timeout".to_owned();
            call.unknown_reason = Some("external_timeout".to_owned());
            return Ok("timeout\n".to_owned());
        }
        let verdict = output.lines().next().unwrap_or("").trim();
        if !matches!(verdict, "sat" | "unsat" | "unknown" | "timeout") {
            bail!("unexpected z3 answer: {verdict}");
        }
        // A get-value after unsat/unknown intentionally has no model. Accept z3's
        // specific protocol error (exit 1) only when that command was requested.
        // A crash/nonzero exit with plausible verdict text never certifies a proof.
        let errors = output
            .lines()
            .filter(|line| line.trim().starts_with("(error"))
            .collect::<Vec<_>>();
        let unavailable_model = !errors.is_empty()
            && matches!(verdict, "unsat" | "unknown")
            && wants_model
            && errors.iter().all(|line| {
                line.starts_with("(error \"line ") && line.ends_with(": model is not available\")")
            });
        if !(status.success() || status.code() == Some(1) && unavailable_model)
            || (!errors.is_empty() && !unavailable_model)
        {
            bail!(
                "z3 tool failure: exit {:?}, verdict {verdict}",
                status.code()
            );
        }
        call.outcome = verdict.to_owned();
        if matches!(verdict, "unknown" | "timeout") {
            call.unknown_reason = output
                .lines()
                .find_map(|line| {
                    line.trim()
                        .strip_prefix("(:reason-unknown ")
                        .map(|reason| reason.trim_end_matches(')').trim_matches('"').to_owned())
                })
                .or_else(|| Some("not_reported".to_owned()));
        }
        Ok(output
            .lines()
            .filter(|line| !line.trim().starts_with("(:reason-unknown "))
            .collect::<Vec<_>>()
            .join("\n")
            + "\n")
    })();
    call.seconds = started.elapsed().as_secs_f64();
    CALLS.with(|calls| calls.borrow_mut().push(call));
    answer
}
