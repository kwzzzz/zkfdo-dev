use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

use anyhow::{ensure, Context, Result};
use thiserror::Error;
use uuid::Uuid;

use super::schema::{
    AllowedPredicateResult, PredicateContext, PredicateCriterion, PredicateOutput, PredicateSpec,
};
use super::subprocess::{run_bounded, PREDICATE_TIMEOUT};

const WORKER_SOURCE: &str = r#"import importlib.util
import json
import pathlib
import sys

predicate_path = pathlib.Path(sys.argv[1])
context_path = pathlib.Path(sys.argv[2])
result_path = pathlib.Path(sys.argv[3])
entrypoint = sys.argv[4]

module_spec = importlib.util.spec_from_file_location("candidate_review_predicate", predicate_path)
if module_spec is None or module_spec.loader is None:
    raise RuntimeError("cannot load predicate")
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)
if getattr(module, "API_VERSION", None) != 1:
    raise RuntimeError("predicate API_VERSION must be 1")
function = getattr(module, entrypoint, None)
if not callable(function):
    raise RuntimeError("predicate entrypoint is not callable")
with context_path.open("r", encoding="utf-8") as handle:
    context = json.load(handle)
result = function(context)
with result_path.open("x", encoding="utf-8") as handle:
    json.dump(result, handle, separators=(",", ":"), sort_keys=True)
    handle.write("\n")
"#;

#[derive(Debug, Error)]
#[error("{message}")]
pub struct PredicateWorkerError {
    pub message: String,
    pub stream_nonempty: bool,
}

struct ScratchDirectory(PathBuf);

impl ScratchDirectory {
    fn create() -> Result<Self> {
        let path = std::env::temp_dir().join(format!(
            "zkfdo-candidate-review-predicate-{}",
            Uuid::new_v4()
        ));
        fs::create_dir(&path)
            .with_context(|| format!("create predicate scratch directory {}", path.display()))?;
        Ok(Self(path))
    }
}

impl Drop for ScratchDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

pub(crate) fn run_predicate(
    python_bin: &Path,
    predicate_path: &Path,
    spec: &PredicateSpec,
    context: &PredicateContext,
) -> std::result::Result<PredicateOutput, PredicateWorkerError> {
    run_predicate_inner(python_bin, predicate_path, spec, context).map_err(|error| {
        error
            .downcast::<PredicateWorkerError>()
            .unwrap_or_else(|error| PredicateWorkerError {
                message: format!("{error:#}"),
                stream_nonempty: false,
            })
    })
}

fn run_predicate_inner(
    python_bin: &Path,
    predicate_path: &Path,
    spec: &PredicateSpec,
    context: &PredicateContext,
) -> Result<PredicateOutput> {
    ensure!(spec.api_version == 1, "unsupported predicate API version");
    ensure!(
        spec.entrypoint == "evaluate",
        "predicate entrypoint must be evaluate"
    );
    let scratch = ScratchDirectory::create()?;
    let worker_path = scratch.0.join("worker.py");
    let context_path = scratch.0.join("context.json");
    let result_path = scratch.0.join("result.json");
    fs::write(&worker_path, WORKER_SOURCE).context("write predicate worker")?;
    fs::write(&context_path, serde_json::to_vec(context)?).context("write predicate context")?;

    let tmp = scratch.0.join("tmp");
    fs::create_dir(&tmp).context("create predicate temporary directory")?;
    let mut command = Command::new(python_bin);
    // -B keeps the import of a pinned predicate from writing bytecode next to it.
    command
        .arg("-I")
        .arg("-S")
        .arg("-B")
        .arg(&worker_path)
        .arg(predicate_path)
        .arg(&context_path)
        .arg(&result_path)
        .arg(&spec.entrypoint)
        .current_dir(&scratch.0)
        .env_clear()
        .env("TMPDIR", &tmp)
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .stdin(Stdio::null());
    let output = run_bounded(&mut command, PREDICATE_TIMEOUT)
        .with_context(|| format!("start predicate worker with {}", python_bin.display()))?;

    if output.timed_out {
        return Err(PredicateWorkerError {
            message: "predicate worker exceeded its fixed timeout".to_owned(),
            stream_nonempty: output.stdout_nonempty || output.stderr_nonempty,
        }
        .into());
    }
    if output.stdout_nonempty || output.stderr_nonempty {
        return Err(PredicateWorkerError {
            message: format!(
                "predicate worker wrote to stdout or stderr (stdout_nonempty={}, stderr_nonempty={})",
                output.stdout_nonempty, output.stderr_nonempty
            ),
            stream_nonempty: true,
        }
        .into());
    }
    if !output.status.success() {
        return Err(PredicateWorkerError {
            message: "predicate worker exited unsuccessfully".to_owned(),
            stream_nonempty: false,
        }
        .into());
    }

    let bytes = fs::read(&result_path).context("predicate did not produce its result channel")?;
    let result: PredicateOutput =
        serde_json::from_slice(&bytes).context("parse predicate result")?;
    validate_result(spec, &result)?;
    Ok(result)
}

fn validate_result(spec: &PredicateSpec, result: &PredicateOutput) -> Result<()> {
    validate_one(
        &spec.allowed_results,
        PredicateCriterion::InputPreconditions,
        &result.input_preconditions,
    )?;
    validate_one(
        &spec.allowed_results,
        PredicateCriterion::SpecifiedPropertyViolation,
        &result.specified_property_violation,
    )?;
    if let Some(class) = &result.specified_property_violation.violation_class {
        ensure!(
            spec.allowed_violation_classes.contains(class),
            "predicate returned a violation class outside the review spec"
        );
    }
    ensure!(
        result.input_preconditions.violation_class.is_none(),
        "input_preconditions must not return a violation class"
    );
    Ok(())
}

fn validate_one(
    allowed: &[AllowedPredicateResult],
    criterion: PredicateCriterion,
    actual: &super::schema::PredicateResult,
) -> Result<()> {
    ensure!(
        allowed.iter().any(|entry| {
            entry.criterion == criterion
                && entry.verdict == actual.verdict
                && entry.reason_code == actual.reason_code
        }),
        "predicate returned a verdict or reason code outside the review spec"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use serde_json::json;
    use tempfile::tempdir;

    use super::*;
    use crate::candidate_review::schema::{
        CriterionVerdict, ParameterKind, PredicateResult, ReportKind, TypedParameterValue,
    };

    fn python_bin() -> PathBuf {
        std::env::split_paths(&std::env::var_os("PATH").unwrap())
            .map(|directory| directory.join("python3"))
            .find(|candidate| candidate.is_file())
            .unwrap()
            .canonicalize()
            .unwrap()
    }

    fn predicate_spec(path: &Path) -> PredicateSpec {
        PredicateSpec {
            api_version: 1,
            path: path.to_path_buf(),
            sha256: "0".repeat(64),
            entrypoint: "evaluate".to_owned(),
            config: json!({}),
            allowed_results: vec![
                AllowedPredicateResult {
                    criterion: PredicateCriterion::InputPreconditions,
                    verdict: CriterionVerdict::Satisfied,
                    reason_code: "ok".to_owned(),
                    note: "Input is valid.".to_owned(),
                },
                AllowedPredicateResult {
                    criterion: PredicateCriterion::SpecifiedPropertyViolation,
                    verdict: CriterionVerdict::Satisfied,
                    reason_code: "bad".to_owned(),
                    note: "Property is violated.".to_owned(),
                },
            ],
            allowed_violation_classes: vec!["example".to_owned()],
        }
    }

    fn context() -> PredicateContext {
        PredicateContext {
            schema_version: 1,
            field_modulus_decimal: "17".to_owned(),
            wire_signals: BTreeMap::from([("main.in".to_owned(), "3".to_owned())]),
            eliminated_signals: BTreeMap::new(),
            parameters: BTreeMap::from([(
                "main.w".to_owned(),
                TypedParameterValue {
                    kind: ParameterKind::Integer,
                    value_decimal: "4".to_owned(),
                },
            )]),
            predicate_config: json!({}),
            request_kind: ReportKind::BackendCandidates,
            injection_id: None,
            clean_reference_signals: None,
        }
    }

    #[test]
    fn worker_returns_only_allowed_value_free_result() {
        let temp = tempdir().unwrap();
        let predicate = temp.path().join("predicate.py");
        fs::write(
            &predicate,
            "API_VERSION=1\ndef evaluate(context):\n return {'input_preconditions':{'verdict':'satisfied','reason_code':'ok'},'specified_property_violation':{'verdict':'satisfied','reason_code':'bad','violation_class':'example'}}\n",
        )
        .unwrap();
        let result = run_predicate(
            &python_bin(),
            &predicate,
            &predicate_spec(&predicate),
            &context(),
        )
        .unwrap();
        assert_eq!(
            result.input_preconditions,
            PredicateResult {
                verdict: CriterionVerdict::Satisfied,
                reason_code: "ok".to_owned(),
                violation_class: None,
            }
        );
    }

    #[test]
    fn worker_rejects_any_stream_output_without_recording_it() {
        let temp = tempdir().unwrap();
        let predicate = temp.path().join("predicate.py");
        fs::write(
            &predicate,
            "API_VERSION=1\ndef evaluate(context):\n print('secret')\n return {'input_preconditions':{'verdict':'satisfied','reason_code':'ok'},'specified_property_violation':{'verdict':'satisfied','reason_code':'bad','violation_class':'example'}}\n",
        )
        .unwrap();
        let error = run_predicate(
            &python_bin(),
            &predicate,
            &predicate_spec(&predicate),
            &context(),
        )
        .unwrap_err();
        assert!(error.stream_nonempty);
        assert!(!error.to_string().contains("secret"));
    }
}
