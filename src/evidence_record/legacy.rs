//! Offline projection of legacy metadata; does not open candidate or source files.
use std::{collections::BTreeMap, path::PathBuf};

use anyhow::{bail, ensure, Context as _, Result};
use serde_json::{Map, Value};

use super::schema::{
    Context, ExecutionObservation, MetadataSource, Method, Recorded, TimingObservation,
};
use crate::candidate_review::schema::FileRef;

pub(super) fn import(
    source: &MetadataSource,
    value: &Value,
    context: &Context,
) -> Result<ExecutionObservation> {
    let data = object(value, "metadata")?;
    let schema_version = schema_version(data)?;
    let mut imported = match source {
        MetadataSource::RunnerResult { target_id, .. } => {
            ensure!(!target_id.trim().is_empty(), "request target_id is empty");
            check_id(data, "target_id", target_id)?;
            let mut result = runner(data)?;
            if matches!(result.target_id, Recorded::Unknown { .. }) {
                result.target_id = Recorded::unknown(
                    "RunResult does not record target_id; requested target is retained in source only",
                );
            }
            result.source_method = method(data, "method", context)?;
            add_completion_time(&mut result, false);
            Ok(result)
        }
        MetadataSource::ExperimentOutcome { run_id, .. } => {
            ensure!(!run_id.trim().is_empty(), "selected run_id is empty");
            let scheduler = object(
                data.get("scheduler")
                    .context("outcome.scheduler is absent")?,
                "outcome.scheduler",
            )?;
            let runs = array(scheduler.get("runs"), "scheduler.runs")?
                .context("scheduler.runs is absent")?;
            let mut selected = Vec::new();
            for entry in runs {
                let entry = object(entry, "scheduler run")?;
                if let Some(raw_result) = present(entry.get("result")) {
                    let result = object(raw_result, "scheduler run.result")?;
                    if string(result, "run_id")?.as_deref() == Some(run_id) {
                        selected.push((entry, result));
                    }
                }
            }
            ensure!(
                selected.len() == 1,
                "selected run_id must match exactly one scheduler run"
            );
            let (entry, raw_result) = selected[0];
            let mut result = runner(raw_result)?;
            let target_id = string(entry, "target_id")?;
            if let Some(target_id) = &target_id {
                check_id(raw_result, "target_id", target_id)?;
            }
            result.target_id = record_string(target_id.clone(), "scheduler target_id is absent");
            result.campaign_id = text(data, "outcome_id")?;
            result.source_plan_index = unsigned(entry, "index")?;
            result.attempt_index =
                Recorded::unknown("legacy ordered target index is not an actual attempt ordinal");
            result.process_start_offset = TimingObservation {
                seconds: numeric(entry, "process_start_offset_seconds")?,
                meaning: "spawn-call offset; not OS exec or engine start".into(),
                origin: "scheduler start".into(),
            };
            result
                .source_versions
                .insert("outcome_id".into(), text(data, "outcome_id")?);
            result.source_versions.insert(
                "outcome_sha256".into(),
                Recorded::known(source.file().sha256.clone()),
            );
            result
                .source_versions
                .insert("plan_id".into(), text(data, "plan_id")?);
            result
                .source_versions
                .insert("plan_sha256".into(), text(data, "plan_sha256")?);
            result
                .source_versions
                .insert("backend".into(), text(data, "zkfuzz_binary_sha256")?);
            result
                .source_versions
                .insert("backend_sha256".into(), text(data, "zkfuzz_binary_sha256")?);
            let mutation_hash = match present(data.get("mutation_settings")) {
                Some(value) => text(object(value, "mutation_settings")?, "source_sha256")?,
                None => Recorded::unknown("mutation_settings is absent or null"),
            };
            result
                .source_versions
                .insert("mutation_settings_source_sha256".into(), mutation_hash);
            result.allocated_campaign_seconds = numeric(data, "total_budget_seconds")?;
            result.source_method = method(data, "execution_mode", context)?;
            let entry_limit = numeric(entry, "execution_limit_seconds")?;
            if matches!(entry_limit, Recorded::Known { value } if value > 0.0) {
                result.execution_limit_seconds = entry_limit;
            }
            let (candidates, inventory) = candidates(data, run_id, target_id.as_deref())?;
            result.candidates = candidates;
            result.candidate_inventory = inventory;
            if is_candidate_status(&result.backend_status)
                && result.candidates.is_empty()
                && matches!(result.candidate_inventory, Recorded::Known { .. })
            {
                result.candidate_inventory = Recorded::unknown(
                    "bug_found run has no candidate reference; the inventory is missing, not empty",
                );
            }
            let completion_offset = numeric(entry, "completion_offset_seconds")?;
            if is_candidate_status(&result.backend_status) || !result.candidates.is_empty() {
                result.candidate_times.push(TimingObservation {
                    seconds: completion_offset,
                    meaning: "scheduler-run-completion-upper-bound; not discovery or review-confirmation time".into(),
                    origin: "scheduler start; after runner completion and result persistence".into(),
                });
            }
            Ok(result)
        }
        MetadataSource::P2Ledger {
            execution_index, ..
        } => import_p2(data, *execution_index, context),
    }?;
    imported
        .source_versions
        .insert("schema_version".into(), schema_version);
    imported.source_versions.insert(
        "metadata_sha256".into(),
        Recorded::known(source.file().sha256.clone()),
    );
    Ok(imported)
}

fn runner(data: &Map<String, Value>) -> Result<ExecutionObservation> {
    let mut result = empty();
    result.run_id = text(data, "run_id")?;
    result.target_id = text(data, "target_id")?;
    result.seed = unsigned(data, "random_seed")?;
    result.started_at = text(data, "started_at")?;
    result.finished_at = text(data, "finished_at")?;
    result.allocated_attempt_seconds = numeric(data, "budget_seconds")?;
    result.execution_limit_seconds = numeric(data, "execution_limit_seconds")?;
    if matches!(result.execution_limit_seconds, Recorded::Known { value } if value == 0.0) {
        result.execution_limit_seconds = Recorded::unknown(
            "zero may be the legacy deserialization default; execution limit is unverified",
        );
    }
    result.actual_wall_seconds = numeric(data, "wall_time_seconds")?;
    result.process_start_offset = TimingObservation {
        seconds: numeric(data, "process_start_offset_seconds")?,
        meaning: "spawn-call offset; not OS exec or engine start".into(),
        origin: "runner execute entry".into(),
    };
    result.backend_status = text(data, "status")?;
    result.exit_code = match present(data.get("exit_code")) {
        Some(value) => Recorded::known(value.as_i64().context("exit_code must be an integer")?),
        None => Recorded::unknown("exit_code is absent or null"),
    };
    result.termination_reason = termination(&result.backend_status, boolean(data, "timed_out")?);
    Ok(result)
}

fn import_p2(
    data: &Map<String, Value>,
    execution_index: usize,
    context: &Context,
) -> Result<ExecutionObservation> {
    let executions = array(data.get("executions"), "ledger.executions")?
        .context("ledger.executions is absent")?;
    let entry = object(
        executions
            .get(execution_index)
            .context("P2 execution_index is out of range")?,
        "P2 execution",
    )?;
    let lane = string(data, "lane")?;
    let source_method = match lane.as_deref() {
        Some("whole") => Method::Whole,
        Some("path-order" | "small-first" | "random") => Method::Split,
        _ => bail!("P2 lane is absent or unrecognized; comparison method is not inferred"),
    };
    ensure!(
        source_method == context.method,
        "P2 lane disagrees with context.method"
    );
    let mut result = empty();
    result.source_method = record_string(lane, "P2 lane is absent");
    result.source_repetition = repetition(entry, "block")?;
    if let (Recorded::Known { value: source }, Recorded::Known { value: expected }) =
        (&result.source_repetition, &context.repetition)
    {
        ensure!(
            source == expected,
            "P2 block disagrees with context.repetition"
        );
    }
    result.run_id = text(entry, "run_id")?;
    result.target_id = text(entry, "target_id")?;
    result.seed = unsigned(entry, "zkfuzz_seed")?;
    result.ranking_seed = unsigned(entry, "random_ranking_seed")?;
    result.actual_wall_seconds = numeric(entry, "elapsed_seconds")?;
    result.backend_status = text(entry, "status")?;
    result.termination_reason = termination(&result.backend_status, None);
    let seconds = numeric(entry, "found_at_seconds")?;
    let found = boolean(entry, "found")?;
    ensure!(
        found != Some(false) || !matches!(seconds, Recorded::Known { .. }),
        "P2 found=false conflicts with a found_at_seconds value"
    );
    if found == Some(true) || matches!(seconds, Recorded::Known { .. }) {
        let (meaning, origin) = match source_method {
            Method::Whole => (
                "backend-log-arrival; not exact candidate generation or review-confirmation time",
                "P2 direct process helper start; NOT SAFE log line received",
            ),
            Method::Split => (
                "known-label-run-completion-upper-bound; not all candidates or review-confirmation time",
                "P2 split campaign start; minimum completion among configured ground-truth labels",
            ),
        };
        result.candidate_times.push(TimingObservation {
            seconds,
            meaning: meaning.into(),
            origin: origin.into(),
        });
    }
    result.candidate_inventory = Recorded::unknown(
        "P2 found/ground_truth/candidate_pieces are backend summaries, not hash-bound candidate inventory",
    );
    Ok(result)
}

fn candidates(
    data: &Map<String, Value>,
    run_id: &str,
    target_id: Option<&str>,
) -> Result<(Vec<FileRef>, Recorded<String>)> {
    let Some(entries) = array(
        data.get("counterexample_candidates"),
        "counterexample_candidates",
    )?
    else {
        return Ok((
            Vec::new(),
            Recorded::unknown("counterexample_candidates is absent or null"),
        ));
    };
    let mut candidates = Vec::new();
    let mut ambiguous = 0;
    for entry in entries {
        let entry = object(entry, "counterexample metadata")?;
        let candidate_run = string(entry, "run_id")?;
        let candidate_target = string(entry, "target_id")?;
        ensure!(
            !(candidate_run.as_deref() == Some(run_id)
                && target_id.is_some()
                && candidate_target.is_some()
                && candidate_target.as_deref() != target_id),
            "candidate metadata has the same run ID but a conflicting target ID"
        );
        if candidate_run.is_none() || candidate_target.is_none() || target_id.is_none() {
            ambiguous += 1;
            continue;
        }
        if candidate_run.as_deref() != Some(run_id) || candidate_target.as_deref() != target_id {
            continue;
        }
        let path = string(entry, "preserved_path")?;
        let sha256 = string(entry, "sha256")?;
        match (path, sha256) {
            (Some(path), Some(sha256)) => {
                ensure!(
                    sha256.len() == 64 && sha256.bytes().all(|byte| byte.is_ascii_hexdigit()),
                    "candidate sha256 must be 64 hexadecimal characters"
                );
                candidates.push(FileRef {
                    path: PathBuf::from(path),
                    sha256,
                });
            }
            _ => ambiguous += 1,
        }
    }
    let inventory = if ambiguous == 0 {
        Recorded::known("legacy outcome candidate references selected by run_id and target_id; files not opened or verified".into())
    } else {
        Recorded::unknown(format!("{ambiguous} candidate metadata entries lack sufficient identity or file reference; not treated as absent"))
    };
    Ok((candidates, inventory))
}

fn add_completion_time(result: &mut ExecutionObservation, scheduler: bool) {
    if is_candidate_status(&result.backend_status) {
        result.candidate_times.push(TimingObservation {
            seconds: result.actual_wall_seconds.clone(),
            meaning: if scheduler {
                "scheduler-run-completion-upper-bound"
            } else {
                "runner-completion-upper-bound; not discovery or review-confirmation time"
            }
            .into(),
            origin:
                "runner execute entry; process exit and log closure, before result JSON persistence"
                    .into(),
        });
    }
}

fn is_candidate_status(status: &Recorded<String>) -> bool {
    matches!(status, Recorded::Known { value } if value == "bug_found")
}

fn termination(status: &Recorded<String>, timed_out: Option<bool>) -> Recorded<String> {
    if timed_out == Some(true) {
        return Recorded::known(
            "legacy timed_out flag; timeout observed, campaign exhaustion not established".into(),
        );
    }
    match status {
        Recorded::Known { value } if matches!(value.as_str(), "bug_found" | "no_counterexample" | "timeout" | "compile_error" | "runtime_error" | "parse_error" | "spawn_error" | "finished") =>
            Recorded::known(format!("legacy backend status {value}; detailed stop cause and native/first-candidate policy unverified")),
        _ => Recorded::unknown("legacy status does not establish a termination reason"),
    }
}

fn empty() -> ExecutionObservation {
    ExecutionObservation {
        campaign_id: Recorded::unknown("legacy campaign identity is absent"),
        attempt_index: Recorded::unknown("legacy attempt index is absent"),
        source_plan_index: Recorded::unknown("legacy planned target index is absent"),
        round_index: Recorded::unknown("legacy metadata does not record an A-policy round"),
        seed: Recorded::unknown("legacy metadata does not record the seed"),
        ranking_seed: Recorded::unknown("legacy metadata does not record the ranking seed"),
        instance_key: Recorded::unknown(
            "legacy result metadata does not identify a concrete instance",
        ),
        source_versions: BTreeMap::from([
            (
                "compiler".into(),
                Recorded::unknown("compiler version is not recorded in this legacy metadata"),
            ),
            (
                "backend".into(),
                Recorded::unknown("backend version is not recorded in this legacy metadata"),
            ),
            (
                "harness".into(),
                Recorded::unknown("harness version is not recorded in this legacy metadata"),
            ),
        ]),
        run_id: Recorded::unknown("legacy run_id is absent"),
        target_id: Recorded::unknown("legacy target_id is absent"),
        source_repetition: Recorded::unknown("repetition is not recorded in this legacy format"),
        source_method: Recorded::unknown("comparison method is not recorded in this legacy format"),
        started_at: Recorded::unknown("started_at is absent"),
        finished_at: Recorded::unknown("finished_at is absent"),
        allocated_attempt_seconds: Recorded::unknown("attempt allocation is absent"),
        allocated_campaign_seconds: Recorded::unknown("campaign allocation is absent"),
        execution_limit_seconds: Recorded::unknown("execution limit is absent"),
        actual_wall_seconds: Recorded::unknown("wall measurement is absent"),
        actual_cpu_seconds: Recorded::unknown("legacy metadata does not measure actual CPU time"),
        peak_memory_bytes: Recorded::unknown("legacy metadata does not measure peak memory"),
        idle_seconds: Recorded::unknown("legacy metadata does not measure idle time"),
        remaining_budget_seconds: Recorded::unknown(
            "legacy metadata does not establish remaining budget under policy A",
        ),
        remaining_at_attempt_start_seconds: Recorded::unknown(
            "legacy metadata does not record remaining allocation at attempt start",
        ),
        backend_status: Recorded::unknown("backend status is absent"),
        termination_reason: Recorded::unknown("detailed termination reason is absent"),
        campaign_termination_reason: Recorded::unknown(
            "legacy attempt status does not establish campaign termination under policy A",
        ),
        exit_code: Recorded::unknown("exit_code is absent"),
        candidate_times: Vec::new(),
        process_start_offset: TimingObservation {
            seconds: Recorded::unknown("legacy metadata does not record a process spawn offset"),
            meaning: "unknown; not usable as candidate generation time".into(),
            origin: "unrecorded".into(),
        },
        exact_candidate_time: Recorded::unknown(
            "legacy metadata does not establish exact candidate generation time",
        ),
        candidates: Vec::new(),
        candidate_inventory: Recorded::unknown(
            "this legacy record does not contain a hash-bound candidate inventory",
        ),
    }
}

fn present(value: Option<&Value>) -> Option<&Value> {
    value.filter(|value| !value.is_null())
}

fn object<'a>(value: &'a Value, field: &str) -> Result<&'a Map<String, Value>> {
    value
        .as_object()
        .with_context(|| format!("{field} must be an object"))
}

fn array<'a>(value: Option<&'a Value>, field: &str) -> Result<Option<&'a Vec<Value>>> {
    present(value)
        .map(|value| {
            value
                .as_array()
                .with_context(|| format!("{field} must be an array"))
        })
        .transpose()
}

fn string(data: &Map<String, Value>, field: &str) -> Result<Option<String>> {
    present(data.get(field))
        .map(|value| {
            let value = value
                .as_str()
                .with_context(|| format!("{field} must be a string"))?;
            ensure!(!value.trim().is_empty(), "{field} must not be empty");
            Ok(value.to_owned())
        })
        .transpose()
}

fn record_string(value: Option<String>, reason: &str) -> Recorded<String> {
    value.map_or_else(|| Recorded::unknown(reason), Recorded::known)
}

fn text(data: &Map<String, Value>, field: &str) -> Result<Recorded<String>> {
    Ok(record_string(
        string(data, field)?,
        &format!("{field} is absent or null"),
    ))
}

fn numeric(data: &Map<String, Value>, field: &str) -> Result<Recorded<f64>> {
    match present(data.get(field)) {
        Some(value) => {
            let value = value
                .as_f64()
                .with_context(|| format!("{field} must be numeric"))?;
            ensure!(
                value.is_finite() && value >= 0.0,
                "{field} must be finite and nonnegative"
            );
            Ok(Recorded::known(value))
        }
        None => Ok(Recorded::unknown(format!("{field} is absent or null"))),
    }
}

fn unsigned(data: &Map<String, Value>, field: &str) -> Result<Recorded<u64>> {
    match present(data.get(field)) {
        Some(value) => {
            Ok(Recorded::known(value.as_u64().with_context(|| {
                format!("{field} must be a nonnegative integer")
            })?))
        }
        None => Ok(Recorded::unknown(format!("{field} is absent or null"))),
    }
}

fn schema_version(data: &Map<String, Value>) -> Result<Recorded<String>> {
    match unsigned(data, "schema_version")? {
        Recorded::Known { value } => {
            ensure!(value == 1, "unsupported legacy schema_version: {value}");
            Ok(Recorded::known(value.to_string()))
        }
        Recorded::Unknown { reason } => Ok(Recorded::unknown(reason)),
    }
}

fn boolean(data: &Map<String, Value>, field: &str) -> Result<Option<bool>> {
    present(data.get(field))
        .map(|value| {
            value
                .as_bool()
                .with_context(|| format!("{field} must be boolean"))
        })
        .transpose()
}

fn check_id(data: &Map<String, Value>, field: &str, expected: &str) -> Result<()> {
    if let Some(value) = string(data, field)? {
        ensure!(
            value == expected,
            "{field} conflicts with selected metadata identity"
        );
    }
    Ok(())
}

fn method(data: &Map<String, Value>, field: &str, context: &Context) -> Result<Recorded<String>> {
    let value = string(data, field)?;
    if let Some(method) = value.as_deref().and_then(|value| match value {
        "whole" => Some(Method::Whole),
        "split" => Some(Method::Split),
        _ => None,
    }) {
        ensure!(
            method == context.method,
            "source method disagrees with context.method"
        );
    }
    Ok(record_string(value, &format!("{field} is absent or null")))
}

fn repetition(data: &Map<String, Value>, field: &str) -> Result<Recorded<String>> {
    match present(data.get(field)) {
        None => Ok(Recorded::unknown(format!("{field} is absent or null"))),
        Some(Value::String(value)) => {
            ensure!(!value.trim().is_empty(), "{field} must not be empty");
            Ok(Recorded::known(value.clone()))
        }
        Some(Value::Number(value)) => {
            let value = value
                .as_u64()
                .with_context(|| format!("{field} must be a nonnegative integer"))?;
            Ok(Recorded::known(value.to_string()))
        }
        Some(_) => bail!("{field} must be a string or nonnegative integer"),
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use serde_json::json;

    use super::*;

    fn context(method: Method) -> Context {
        Context {
            execution_unit_id: "synthetic-unit".into(),
            method,
            repetition: Recorded::known("1".into()),
            project: Recorded::unknown("synthetic"),
            source_version: Recorded::unknown("synthetic"),
            entrypoint: Recorded::unknown("synthetic"),
            settings_sha256: Recorded::unknown("synthetic"),
            tool_versions: BTreeMap::new(),
        }
    }

    fn file() -> FileRef {
        FileRef {
            path: "synthetic-metadata.json".into(),
            sha256: "a".repeat(64),
        }
    }

    #[test]
    fn absent_metadata_stays_unknown_and_zero_limit_is_not_a_measurement() {
        let source = MetadataSource::RunnerResult {
            file: file(),
            target_id: "target".into(),
        };
        let record = import(
            &source,
            &json!({"execution_limit_seconds": 0}),
            &context(Method::Whole),
        )
        .unwrap();
        assert!(matches!(record.run_id, Recorded::Unknown { .. }));
        assert!(matches!(
            record.execution_limit_seconds,
            Recorded::Unknown { .. }
        ));
        assert!(matches!(
            record.remaining_budget_seconds,
            Recorded::Unknown { .. }
        ));
        assert!(record.candidate_times.is_empty());
        for bad in [
            json!({"wall_time_seconds": -1}),
            json!({"wall_time_seconds": "1"}),
            json!({"run_id": 3}),
            json!({"schema_version": 2}),
            json!({"schema_version": "1"}),
            json!({"random_seed": -1}),
        ] {
            assert!(import(&source, &bad, &context(Method::Whole)).is_err());
        }
        let versionless = import(
            &source,
            &json!({"schema_version":null}),
            &context(Method::Whole),
        )
        .unwrap();
        assert!(matches!(
            versionless.source_versions["schema_version"],
            Recorded::Unknown { .. }
        ));
        for key in ["compiler", "backend", "harness"] {
            assert!(matches!(
                versionless.source_versions[key],
                Recorded::Unknown { .. }
            ));
        }
    }

    #[test]
    fn p2_time_definitions_and_method_repetition_conflicts_remain_distinct() {
        let source = MetadataSource::P2Ledger {
            file: file(),
            execution_index: 0,
        };
        let mut value =
            json!({"lane":"whole", "executions":[{"block":1,"found":true,"found_at_seconds":2.0}]});
        let whole = import(&source, &value, &context(Method::Whole)).unwrap();
        assert!(whole.candidate_times[0]
            .meaning
            .starts_with("backend-log-arrival"));
        assert!(import(&source, &value, &context(Method::Split)).is_err());
        value["lane"] = json!("small-first");
        let split = import(&source, &value, &context(Method::Split)).unwrap();
        assert!(split.candidate_times[0]
            .meaning
            .starts_with("known-label-run-completion-upper-bound"));
        value["executions"][0]["block"] = json!(2);
        assert!(import(&source, &value, &context(Method::Split)).is_err());
    }

    #[test]
    fn outcome_selection_keeps_duplicate_refs_and_completion_bound() {
        let source = MetadataSource::ExperimentOutcome {
            file: file(),
            run_id: "run".into(),
        };
        let candidate = json!({"run_id":"run","target_id":"target","preserved_path":"synthetic-ref.json","sha256":"b".repeat(64)});
        let mut value = json!({"schema_version":1,"outcome_id":"campaign","plan_id":"plan","plan_sha256":"c".repeat(64),"zkfuzz_binary_sha256":"d".repeat(64),"mutation_settings":{"source_sha256":"e".repeat(64)},"scheduler":{"runs":[{"index":2,"target_id":"target","completion_offset_seconds":8,"result":{"run_id":"run","status":"bug_found","wall_time_seconds":3,"random_seed":17}}]},"counterexample_candidates":[candidate.clone(),candidate]});
        let record = import(&source, &value, &context(Method::Split)).unwrap();
        assert_eq!(record.candidates.len(), 2);
        assert!(matches!(
            record.source_plan_index,
            Recorded::Known { value: 2 }
        ));
        assert!(matches!(record.attempt_index, Recorded::Unknown { .. }));
        assert!(matches!(record.seed, Recorded::Known { value: 17 }));
        assert!(matches!(record.campaign_id, Recorded::Known { ref value } if value == "campaign"));
        assert!(
            matches!(record.source_versions["plan_sha256"], Recorded::Known { ref value } if value == &"c".repeat(64))
        );
        assert!(
            matches!(record.source_versions["backend"], Recorded::Known { ref value } if value == &"d".repeat(64))
        );
        assert!(
            matches!(record.source_versions["mutation_settings_source_sha256"], Recorded::Known { ref value } if value == &"e".repeat(64))
        );
        assert!(matches!(record.round_index, Recorded::Unknown { .. }));
        assert!(matches!(
            record.campaign_termination_reason,
            Recorded::Unknown { .. }
        ));
        assert!(
            matches!(record.candidate_times[0].seconds, Recorded::Known { value } if value == 8.0)
        );
        assert!(record.candidate_times[0]
            .meaning
            .starts_with("scheduler-run-completion-upper-bound"));
        let duplicate = value["scheduler"]["runs"][0].clone();
        value["scheduler"]["runs"]
            .as_array_mut()
            .unwrap()
            .push(duplicate);
        assert!(import(&source, &value, &context(Method::Split)).is_err());
    }

    #[test]
    fn invalid_completion_measurement_is_rejected_even_without_candidate() {
        let source = MetadataSource::ExperimentOutcome {
            file: file(),
            run_id: "run".into(),
        };
        let value = json!({"scheduler":{"runs":[{"completion_offset_seconds":-1,"result":{"run_id":"run","status":"no_counterexample"}}]}});
        assert!(import(&source, &value, &context(Method::Split)).is_err());
    }
}
