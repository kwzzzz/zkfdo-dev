//! Offline inspection only: no compiler, judging engine, or fuzz process is invoked.
use anyhow::{ensure, Context, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    fs,
    io::Write,
    path::{Path, PathBuf},
    time::Instant,
};
use zkfdo::{corpus, targets};

fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn allowed(path: &Path) -> Result<()> {
    let path = path.to_string_lossy();
    ensure!(
        !path.contains("n6-a-remeasure-2026-10-25.noindex")
            && !path.starts_with("/Volumes/zkfdo-jcache"),
        "forbidden audit input"
    );
    Ok(())
}

fn guard() -> Result<()> {
    // These read-only libc calls inspect this process and the internal filesystem only.
    ensure!(
        unsafe { libc::getpriority(libc::PRIO_PROCESS, 0) } >= 19,
        "nice 19 required"
    );
    let mut stat = std::mem::MaybeUninit::<libc::statvfs>::uninit();
    ensure!(
        unsafe { libc::statvfs(c"/".as_ptr(), stat.as_mut_ptr()) } == 0,
        "disk query failed"
    );
    let stat = unsafe { stat.assume_init() };
    ensure!(
        (stat.f_bavail as u128) * (stat.f_frsize as u128) >= 15 * 1024_u128.pow(3),
        "internal disk below 15 GiB"
    );
    Ok(())
}

fn reason_category(reason: &str) -> String {
    let prefix = if reason.starts_with("unsupported inspection: ") {
        "unsupported inspection: "
    } else {
        ""
    };
    let core = if reason.contains("unsupported expression token [") {
        "unsupported expression token [".to_owned()
    } else if reason.contains("compile-time variable arrays are unsupported") {
        "compile-time variable arrays are unsupported".to_owned()
    } else if let Some((_, suffix)) = reason.rsplit_once("unknown compile-time value ") {
        format!(
            "unknown compile-time value {}",
            suffix.chars().take(80).collect::<String>()
        )
    } else if reason.contains("binding/component reassignment affecting target resolution") {
        "binding/component reassignment affecting target resolution".to_owned()
    } else if reason.contains("component is assigned more than once in the concrete expansion") {
        "component is assigned more than once in the concrete expansion".to_owned()
    } else if reason.contains("compile-r1cs failed") {
        "compile-r1cs failed".to_owned()
    } else if reason.contains("unsupported expression ") {
        "unsupported expression".to_owned()
    } else if reason.starts_with("manifest parameters ") {
        "manifest parameters differ from parsed root".to_owned()
    } else if reason.starts_with("manifest template ") {
        "manifest template differs from parsed root".to_owned()
    } else {
        reason
            .rsplit_once(": ")
            .map_or(reason, |(_, tail)| tail)
            .to_owned()
    };
    let value = format!("{prefix}{core}");
    if value.chars().count() <= 250 {
        value
    } else {
        format!("{}…", value.chars().take(249).collect::<String>())
    }
}

fn compact_reasons(row: &mut Value) -> Result<()> {
    for field in ["reasons", "old_exclusion_reasons"] {
        let raw = row[field].as_array().context("reason list missing")?;
        let digest = digest(&serde_json::to_vec(raw)?);
        let total = raw.len();
        let mut counts = std::collections::BTreeMap::<String, usize>::new();
        for reason in raw {
            *counts
                .entry(reason_category(
                    reason.as_str().context("reason is not text")?,
                ))
                .or_default() += 1;
        }
        row[field] = json!(counts.keys().collect::<Vec<_>>());
        row[format!("{field}_counts")] = json!(counts);
        row[format!("{field}_sha256")] = json!(digest);
        row[format!("{field}_total")] = json!(total);
    }
    Ok(())
}

fn wrapper_arguments(
    definition: &corpus::CorpusTarget,
    root: &targets::InspectedTemplateInstance,
    original_wrapper: &[u8],
) -> Result<Vec<String>> {
    if !root
        .concrete_parameters
        .iter()
        .any(|value| value.starts_with("[sha256:"))
    {
        return Ok(root.concrete_parameters.clone());
    }
    ensure!(
        definition.prime == "bn128",
        "array literal rendering requires the explicit bn128 field"
    );
    let prime: num_bigint::BigUint =
        "21888242871839275222246405745257275088548364400416034343698204186575808495617".parse()?;
    let source = std::str::from_utf8(original_wrapper).context("wrapper is not UTF-8")?;
    let (template, values) =
        targets::main_literal_arguments(&definition.entrypoint, source, &prime)
            .map_err(anyhow::Error::msg)?;
    ensure!(
        template == root.template_name,
        "literal wrapper template differs from inspection"
    );
    let values = values
        .into_iter()
        .map(|value| value.map_err(anyhow::Error::msg))
        .collect::<Result<Vec<_>>>()?;
    let keys = values
        .iter()
        .map(|value| value.key_token(&prime))
        .collect::<Result<Vec<_>>>()?;
    ensure!(
        keys == root.concrete_parameters,
        "literal wrapper arguments differ from inspection"
    );
    values.iter().map(|value| value.literal(&prime)).collect()
}

fn main() -> Result<()> {
    guard()?;
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    ensure!(
        args.len() == 2,
        "usage: s_inspection_audit PREPARED_JSON NEW_OUTPUT_JSON"
    );
    let input = PathBuf::from(&args[0]);
    let output = PathBuf::from(&args[1]);
    allowed(&input)?;
    allowed(&output)?;
    ensure!(!output.exists(), "output must be new");
    let started = chrono::Utc::now();
    let timer = Instant::now();
    let input_bytes = fs::read(&input)?;
    let prepared: Value = serde_json::from_slice(&input_bytes)?;
    let old_targets = prepared["targets"]
        .as_array()
        .context("prepared targets missing")?;
    let mut rows = Vec::new();
    let mut captures = HashMap::new();
    for (index, old) in old_targets.iter().enumerate() {
        guard()?;
        let definition: corpus::CorpusTarget = serde_json::from_value(old["definition"].clone())?;
        allowed(&definition.entrypoint)?;
        allowed(&definition.project_root)?;
        let libraries = corpus::compile_library_paths(&definition);
        for library in &libraries {
            allowed(library)?;
        }
        let wrapper_bytes = fs::read(&definition.entrypoint)?;
        let inspected = if let Some(capture_path) = &definition.instance_capture {
            allowed(capture_path)?;
            if !captures.contains_key(capture_path) {
                captures.insert(
                    capture_path.clone(),
                    serde_json::from_slice(&fs::read(capture_path)?)?,
                );
            }
            targets::inspect_entrypoint_from_capture(
                &definition.entrypoint,
                &definition.project_root,
                &libraries,
                &captures[capture_path],
            )
        } else {
            targets::inspect_entrypoint_with_libraries_and_prime(
                &definition.entrypoint,
                &definition.project_root,
                &libraries,
                &definition.prime,
            )
        };
        let mut row = json!({"index": index, "label": definition.label, "template": definition.template_name,
            "old_eligible": old["eligible"], "old_target_id": old["target_id"],
            "old_exclusion_reasons": old["exclusion_reasons"],
            "wrapper_path": definition.entrypoint, "existing_wrapper_sha256": digest(&wrapper_bytes),
            "definition_sha256": digest(&serde_json::to_vec(&definition)?),
            "inspection_eligible": false, "reasons": []});
        match inspected {
            Ok(inspection) => {
                // Keep source locations separately from compact diagnostic categories.
                row["source_diagnostics"] = json!(inspection
                    .unsupported
                    .iter()
                    .map(|issue| {
                        json!({"source_path": issue.source_path, "line": issue.line,
                        "reason": issue.reason.chars().take(2000).collect::<String>()})
                    })
                    .collect::<Vec<_>>());
                let mut reasons = inspection
                    .unsupported
                    .iter()
                    .map(|issue| format!("{}: {}", issue.construct, issue.reason))
                    .collect::<Vec<_>>();
                if !inspection.complete && reasons.is_empty() {
                    reasons.push("entrypoint inspection is incomplete".into());
                }
                if let Some(root) = &inspection.root {
                    if root.template_name != definition.template_name
                        || root.concrete_parameters != definition.concrete_parameters
                    {
                        reasons.push("manifest/root identity mismatch".into());
                    }
                    match wrapper_arguments(&definition, root, &wrapper_bytes) {
                        Ok(arguments) => {
                            let rendered = targets::render_fragment_wrapper(
                                &root.path,
                                &root.template_name,
                                &arguments,
                            );
                            row["rendered_wrapper_sha256"] = json!(digest(rendered.as_bytes()));
                            row["rendered_matches_existing"] =
                                json!(rendered.as_bytes() == wrapper_bytes);
                        }
                        Err(error) => reasons.push(format!("wrapper arguments: {error:#}")),
                    }
                } else {
                    reasons.push("parsed root template is unavailable".into());
                }
                for path in &inspection.dependency_paths {
                    allowed(path)?;
                }
                let fingerprints = corpus::fingerprint_sources(&inspection.dependency_paths)?;
                match corpus::stable_target_id(&definition, &inspection, &fingerprints) {
                    Ok(target_id) => {
                        // This is the deterministic executable fragment identity/spec payload;
                        // timings, output directories and compilation products are excluded.
                        let spec = json!({"definition": definition, "inspection": inspection, "target_id": target_id, "source_fingerprints": fingerprints});
                        row["fragment_spec_sha256"] = json!(digest(&serde_json::to_vec(&spec)?));
                        row["target_id"] = spec["target_id"].clone();
                    }
                    Err(error) => reasons.push(format!("identity: {error:#}")),
                }
                row["inspection_sha256"] = json!(digest(&serde_json::to_vec(&inspection)?));
                row["inspection_eligible"] = json!(inspection.complete && reasons.is_empty());
                row["reasons"] = json!(reasons);
            }
            Err(error) => row["reasons"] = json!([format!("inspection error: {error:#}")]),
        }
        compact_reasons(&mut row)?;
        rows.push(row);
    }
    guard()?;
    let result = json!({"schema_version":1, "kind":"offline_fragment_inspection", "compiler_invocations":0,
        "judging_invocations":0, "fuzz_invocations":0, "prepared_path":input,
        "prepared_sha256":digest(&input_bytes), "started_at":started, "finished_at":chrono::Utc::now(),
        "elapsed_seconds":timer.elapsed().as_secs_f64(), "targets":rows});
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(output)?;
    file.write_all(&serde_json::to_vec(&result)?)?;
    file.write_all(b"\n")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compact_reason_counts_preserve_evidence_without_array_values() {
        let long = format!("unsupported inspection: T([{}]): main template parameters are not concrete: unsupported expression token [", "123456789,".repeat(10000));
        let mut row = json!({"reasons":[long, long], "old_exclusion_reasons":[], "fragment_spec_sha256":"preserved", "inspection_eligible":false});
        compact_reasons(&mut row).unwrap();
        assert_eq!(row["reasons_total"], 2);
        assert_eq!(
            row["reasons_counts"]["unsupported inspection: unsupported expression token ["],
            2
        );
        assert_eq!(row["fragment_spec_sha256"], "preserved");
        assert!(serde_json::to_vec(&row).unwrap().len() < 1000);
        assert!(reason_category(&"x".repeat(1000)).chars().count() <= 250);
    }

    fn fixture(
        parameters: Vec<String>,
    ) -> (corpus::CorpusTarget, targets::InspectedTemplateInstance) {
        let definition = serde_json::from_value(json!({
            "label":"audit", "project":"fixture", "revision":"development",
            "project_root":"/fixture", "entrypoint":"/fixture/wrapper.circom",
            "template_name":"T", "concrete_parameters":parameters,
            "prime":"bn128", "mode":"direct", "input_assumptions":"synthetic"
        }))
        .unwrap();
        let root = targets::InspectedTemplateInstance {
            path: PathBuf::from("/fixture/template.circom"),
            template_name: "T".into(),
            concrete_parameters: parameters,
        };
        (definition, root)
    }

    #[test]
    fn scalar_wrapper_arguments_preserve_legacy_spelling() {
        let (definition, root) = fixture(vec!["-1".into(), "2".into()]);
        assert_eq!(
            wrapper_arguments(&definition, &root, b"unused").unwrap(),
            root.concrete_parameters
        );
    }

    #[test]
    fn array_wrapper_arguments_use_literal_instead_of_identity_hash() {
        let prime = "21888242871839275222246405745257275088548364400416034343698204186575808495617"
            .parse()
            .unwrap();
        let value = zkfdo::instance_capture::CapturedValue::Array {
            dims: vec![2, 2],
            values: vec!["1".into(), "2".into(), "3".into(), "4".into()],
        };
        let (definition, root) = fixture(vec![value.key_token(&prime).unwrap()]);
        let actual = wrapper_arguments(
            &definition,
            &root,
            b"pragma circom 2.1.6; component main = T([[1, 2], [3, 4]]);",
        )
        .unwrap();
        assert_eq!(actual, vec!["[[1, 2], [3, 4]]"]);
        assert!(
            wrapper_arguments(&definition, &root, b"component main = T([[1, 2], [3, 5]]);")
                .is_err()
        );
    }

    #[test]
    fn array_wrapper_arguments_refuse_an_unconfirmed_field() {
        let (mut definition, root) = fixture(vec!["[sha256:unconfirmed]".into()]);
        definition.prime = "goldilocks".into();
        assert!(wrapper_arguments(&definition, &root, b"component main = T([1]);").is_err());
    }
}
