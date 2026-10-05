//! L-07: assumption-predicate verdicts per (entrypoint, instance) over a set of lift results.
//!
//! A predicate is a property of the entrypoint instance, not of the candidate that led to it.
//! Joining the per-request judgments makes the instance verdict independent of the order in
//! which requests ran: reachable if any request checked a witness on which it holds, excluded
//! if any request proved it impossible, `conflict` if both (an engine error), unknown otherwise.

use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result};
use serde::Serialize;
use serde_json::Value;

use super::predicate::{EXCLUDED, VIOLATION_REACHABLE};

pub const INSTANCE_VERDICTS_SCHEMA: &str = "zkfdo-instance-verdicts-v1";

#[derive(Debug, Serialize, Default)]
pub struct InstanceRow {
    pub entry_key: String,
    pub instance: String,
    pub verdict: String,
    /// Reach classification of the checked witnesses: `private_only` if any reach needs no
    /// public input change, else `public_inputs_changed`.
    pub reach_classification: Option<String>,
    pub reached_by: Vec<Judgment>,
    pub excluded_by: Vec<Judgment>,
    pub unknown_in: Vec<String>,
}

#[derive(Debug, Serialize, Clone)]
pub struct Judgment {
    pub request_id: String,
    pub method: Option<String>,
    pub shared_from: Option<String>,
    pub classification: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ClassRow {
    pub request_id: String,
    pub representative: String,
    /// The class's own verdict in its result.json.
    pub own: Option<String>,
    /// The verdict from the instance rows of its predicate targets.
    pub effective: String,
    pub target_basis: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct InstanceVerdicts {
    pub schema: String,
    pub results: Vec<PathBuf>,
    pub instances: Vec<InstanceRow>,
    pub classes: Vec<ClassRow>,
    pub counts: BTreeMap<String, usize>,
    pub conflicts: usize,
    /// Classes whose effective verdict differs from their own.
    pub changed_by_sharing: usize,
}

fn text(value: &Value, key: &str) -> Option<String> {
    value.get(key).and_then(Value::as_str).map(str::to_owned)
}

pub fn aggregate(results: &[PathBuf]) -> Result<InstanceVerdicts> {
    let mut rows: BTreeMap<(String, String), InstanceRow> = BTreeMap::new();
    let mut classes = Vec::new();
    let mut targets: Vec<(usize, Vec<(String, String)>)> = Vec::new();
    for path in results {
        let result: Value = serde_json::from_slice(
            &fs::read(path).with_context(|| format!("read {}", path.display()))?,
        )
        .with_context(|| format!("parse {}", path.display()))?;
        let request_id = text(&result, "request_id").unwrap_or_default();
        let Some(entry) = result.get("entrypoint").filter(|entry| entry.is_object()) else {
            continue;
        };
        let entry_key = ["r1cs_sha256", "sym_sha256", "o0_r1cs_sha256"]
            .iter()
            .map(|key| text(entry, key).unwrap_or_default())
            .collect::<Vec<_>>()
            .join(":");
        for class in result
            .get("classes")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let predicates = class
                .get("predicates")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if predicates.is_empty() {
                continue;
            }
            let mut keys = Vec::new();
            for predicate in &predicates {
                let instance = text(predicate, "instance").unwrap_or_default();
                let key = (entry_key.clone(), instance.clone());
                let row = rows.entry(key.clone()).or_insert_with(|| InstanceRow {
                    entry_key: entry_key.clone(),
                    instance,
                    ..InstanceRow::default()
                });
                let judgment = Judgment {
                    request_id: request_id.clone(),
                    method: text(predicate, "method"),
                    shared_from: text(predicate, "shared_from"),
                    classification: predicate
                        .get("reach_inputs")
                        .and_then(|reach| text(reach, "classification")),
                };
                match text(predicate, "verdict").as_deref() {
                    Some(VIOLATION_REACHABLE) => row.reached_by.push(judgment),
                    Some(EXCLUDED) => row.excluded_by.push(judgment),
                    _ => row.unknown_in.push(request_id.clone()),
                }
                keys.push(key);
            }
            classes.push(ClassRow {
                request_id: request_id.clone(),
                representative: text(class, "representative").unwrap_or_default(),
                own: text(class, "assumption_predicate_verdict"),
                effective: String::new(),
                target_basis: predicates
                    .first()
                    .and_then(|predicate| text(predicate, "target_basis")),
            });
            targets.push((classes.len() - 1, keys));
        }
    }
    for row in rows.values_mut() {
        row.verdict = match (row.reached_by.is_empty(), row.excluded_by.is_empty()) {
            (false, false) => "conflict",
            (false, true) => VIOLATION_REACHABLE,
            (true, false) => EXCLUDED,
            (true, true) => "unknown",
        }
        .to_owned();
        let kinds = row
            .reached_by
            .iter()
            .filter_map(|judgment| judgment.classification.clone())
            .collect::<BTreeSet<_>>();
        row.reach_classification = if kinds.contains("private_only") {
            Some("private_only".to_owned())
        } else {
            kinds.into_iter().next()
        };
    }
    for (class, keys) in targets {
        let verdicts = keys
            .iter()
            .map(|key| rows[key].verdict.as_str())
            .collect::<Vec<_>>();
        classes[class].effective = if verdicts.contains(&"conflict") {
            "conflict"
        } else if verdicts.contains(&VIOLATION_REACHABLE) {
            VIOLATION_REACHABLE
        } else if verdicts.iter().all(|verdict| *verdict == EXCLUDED) {
            EXCLUDED
        } else {
            "unknown"
        }
        .to_owned();
    }
    let instances = rows.into_values().collect::<Vec<_>>();
    let mut counts = BTreeMap::new();
    for row in &instances {
        *counts.entry(row.verdict.clone()).or_insert(0) += 1;
    }
    Ok(InstanceVerdicts {
        schema: INSTANCE_VERDICTS_SCHEMA.to_owned(),
        results: results.to_vec(),
        conflicts: instances
            .iter()
            .filter(|row| row.verdict == "conflict")
            .count(),
        changed_by_sharing: classes
            .iter()
            .filter(|class| class.own.as_deref() != Some(class.effective.as_str()))
            .count(),
        instances,
        classes,
        counts,
    })
}

pub fn write(results: &[PathBuf], output: &Path) -> Result<InstanceVerdicts> {
    let verdicts = aggregate(results)?;
    fs::write(output, serde_json::to_vec_pretty(&verdicts)?)
        .with_context(|| format!("write {}", output.display()))?;
    Ok(verdicts)
}
