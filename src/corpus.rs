//! Curated executable targets and reproducible, read-only feature preparation.
use std::{
    collections::{BTreeMap, BTreeSet, HashMap},
    fs,
    path::{Path, PathBuf},
    time::Instant,
};

use anyhow::{ensure, Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::{
    features::extract_features_from_source,
    ranker::{estimated_cost_score, static_risk_score},
    semantic::{self, AnalysisOptions, SemanticAnalysis, SourceScope},
    static_rank::{RankingInput, RankingStrategy},
    structure::{profile_target_with_ast, StructureProfile},
    targets::{
        inspect_entrypoint_with_libraries, inspect_entrypoint_with_libraries_and_prime,
        EntrypointInspection,
    },
};

fn schema_version() -> u32 {
    1
}
fn default_prime() -> String {
    "bn128".to_owned()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CorpusManifest {
    #[serde(default = "schema_version")]
    pub schema_version: u32,
    pub name: String,
    pub description: String,
    pub targets: Vec<CorpusTarget>,
    #[serde(default)]
    pub exclusions: Vec<Exclusion>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CorpusTarget {
    pub label: String,
    pub project: String,
    pub revision: String,
    pub project_root: PathBuf,
    pub entrypoint: PathBuf,
    pub template_name: String,
    pub concrete_parameters: Vec<String>,
    #[serde(default = "default_prime")]
    pub prime: String,
    #[serde(default)]
    pub compile_args: Vec<String>,
    /// Entrypoint provenance: `original` for a project entrypoint or `direct` for an isolated wrapper.
    pub mode: String,
    pub input_assumptions: String,
    /// Machine-readable eligibility for schema 2 manifests. Legacy schema 1 keeps its behavior.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub input_contract: Option<InputContract>,
    #[serde(default)]
    pub known_defects: Vec<KnownDefect>,
    /// F-01: an `instance-capture.json` from discovery. When set, the inspection is built from
    /// the captured instances (the interpreter still runs, for comparison).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instance_capture: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum InputContract {
    /// The specified property uses the field directly, without a narrower input domain.
    FieldOnly,
    /// The property needs an additional domain constraint, such as an integer range.
    Bounded {
        enforcement: BoundedEnforcement,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        evidence: Option<ContractEvidence>,
    },
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BoundedEnforcement {
    Unverified,
    ReviewedInExecutable,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContractEvidence {
    pub path: PathBuf,
    pub sha256: String,
    pub entrypoint_sha256: String,
    pub source_closure_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnownDefect {
    pub root_cause_id: String,
    pub location: String,
    pub source_url: String,
    pub reported: bool,
    pub local_reproduction: String,
    pub tcct_status: String,
    pub reachability: String,
    #[serde(default)]
    pub evidence: Vec<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Exclusion {
    pub label: String,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PrepareOptions {
    pub circom_bin: PathBuf,
    pub zkfuzz_bin: PathBuf,
    pub analyzer_bin: PathBuf,
    pub analyzer_version: String,
    pub analyzer_revision: String,
    pub timeout_seconds: u64,
    /// None collects the common superset for a ranking-only comparison.
    pub strategy: Option<RankingStrategy>,
}

impl Default for PrepareOptions {
    fn default() -> Self {
        Self {
            circom_bin: PathBuf::from("circom"),
            zkfuzz_bin: PathBuf::from("zkfuzz"),
            analyzer_bin: AnalysisOptions::default().binary,
            analyzer_version: semantic::ANALYZER_VERSION.to_owned(),
            analyzer_revision: semantic::ANALYZER_REVISION.to_owned(),
            timeout_seconds: 60,
            strategy: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceFingerprint {
    pub path: PathBuf,
    pub sha256: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PreparationTimings {
    pub inspection_seconds: f64,
    pub snapshot_seconds: f64,
    pub structure_seconds: f64,
    pub semantic_seconds: f64,
    pub legacy_seconds: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreparedTarget {
    pub target_id: String,
    pub definition: CorpusTarget,
    pub inspection: Option<EntrypointInspection>,
    pub run_entrypoint: Option<PathBuf>,
    pub structure: Option<StructureProfile>,
    pub semantic: Option<SemanticAnalysis>,
    pub ranking: RankingInput,
    pub eligible: bool,
    pub exclusion_reasons: Vec<String>,
    pub source_fingerprints: Vec<SourceFingerprint>,
    pub snapshot_fingerprints: Vec<SourceFingerprint>,
    pub timings: PreparationTimings,
    pub elapsed_seconds: f64,
    pub limitations: Vec<String>,
    /// F-01: where the inspection came from and how the interpreter's compares.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instance_inspection: Option<InspectionSource>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InspectionSource {
    /// `compiler` (from the instance capture) or `interpreter`.
    pub source: String,
    pub capture_path: PathBuf,
    pub capture_sha256: String,
    pub compiler_complete: bool,
    pub interpreter_complete: bool,
    pub interpreter_unsupported: usize,
    /// Distinct (source, template, parameters) instances found by one method only.
    pub instances_only_interpreter: Vec<String>,
    pub instances_only_compiler: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreparedCorpus {
    pub schema_version: u32,
    pub name: String,
    pub description: String,
    pub manifest_path: PathBuf,
    pub manifest_sha256: String,
    pub output_dir: PathBuf,
    pub report_path: PathBuf,
    pub profile_strategy: Option<RankingStrategy>,
    pub options: PrepareOptions,
    pub environment: BTreeMap<String, String>,
    pub started_at: DateTime<Utc>,
    pub finished_at: DateTime<Utc>,
    pub elapsed_seconds: f64,
    pub targets: Vec<PreparedTarget>,
    pub exclusions: Vec<Exclusion>,
    pub limitations: Vec<String>,
}

pub fn fingerprint_sources(paths: &[PathBuf]) -> Result<Vec<SourceFingerprint>> {
    paths
        .iter()
        .map(|path| {
            fs::canonicalize(path)
                .with_context(|| format!("source unavailable: {}", path.display()))
        })
        .collect::<Result<BTreeSet<_>>>()?
        .into_iter()
        .map(|path| {
            let bytes = fs::read(&path)
                .with_context(|| format!("cannot hash source: {}", path.display()))?;
            Ok(SourceFingerprint {
                path,
                sha256: sha256(&bytes),
            })
        })
        .collect()
}

pub fn verify_fingerprints(fingerprints: &[SourceFingerprint]) -> Result<()> {
    for fingerprint in fingerprints {
        let bytes = fs::read(&fingerprint.path).with_context(|| {
            format!(
                "fingerprinted source unavailable: {}",
                fingerprint.path.display()
            )
        })?;
        ensure!(
            sha256(&bytes) == fingerprint.sha256,
            "source changed after preparation: {}",
            fingerprint.path.display()
        );
    }
    Ok(())
}

/// Verify that every executable source is the exact copied counterpart of its original.
/// Independent hash lists alone do not bind a runnable snapshot to a target identity.
pub fn verify_snapshot_provenance(
    inspection: &EntrypointInspection,
    run_entrypoint: &Path,
    originals: &[SourceFingerprint],
    snapshots: &[SourceFingerprint],
) -> Result<()> {
    verify_fingerprints(originals)?;
    verify_fingerprints(snapshots)?;
    let expected_sources = inspection.dependency_paths.iter().collect::<BTreeSet<_>>();
    let original_sources = originals
        .iter()
        .map(|value| &value.path)
        .collect::<BTreeSet<_>>();
    ensure!(
        expected_sources == original_sources && original_sources.len() == originals.len(),
        "snapshot provenance requires exactly the inspected original source closure"
    );
    let original_base = source_common_root(inspection)?;
    let relative_entrypoint = inspection.entrypoint.strip_prefix(original_base)?;
    let run_entrypoint = fs::canonicalize(run_entrypoint)?;
    let mut snapshot_base = run_entrypoint.as_path();
    for _ in relative_entrypoint.components() {
        snapshot_base = snapshot_base
            .parent()
            .context("snapshot layout is shorter than original source layout")?;
    }
    ensure!(
        snapshot_base.join(relative_entrypoint) == run_entrypoint,
        "snapshot entrypoint layout differs from the selected original entrypoint"
    );
    let actual = snapshots
        .iter()
        .map(|value| (value.path.clone(), value.sha256.clone()))
        .collect::<BTreeMap<_, _>>();
    ensure!(
        actual.len() == snapshots.len(),
        "duplicate snapshot fingerprint"
    );
    let mut expected = BTreeMap::new();
    for source in originals {
        let copied_path = snapshot_base.join(source.path.strip_prefix(original_base)?);
        let canonical = fs::canonicalize(&copied_path)
            .with_context(|| format!("source snapshot missing: {}", copied_path.display()))?;
        ensure!(
            canonical == copied_path && canonical != source.path,
            "snapshot source must be an independent file at its original relative layout"
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let original_metadata = fs::metadata(&source.path)?;
            let copied_metadata = fs::metadata(&canonical)?;
            ensure!(
                original_metadata.dev() != copied_metadata.dev()
                    || original_metadata.ino() != copied_metadata.ino(),
                "snapshot source must not be a hard link to an original source"
            );
        }
        expected.insert(canonical, source.sha256.clone());
    }
    ensure!(
        actual == expected,
        "snapshot contents or source layout do not match the inspected original source closure"
    );
    Ok(())
}

/// Identity uses logical source paths and source content, not a temporary wrapper filename.
pub fn stable_target_id(
    definition: &CorpusTarget,
    inspection: &EntrypointInspection,
    fingerprints: &[SourceFingerprint],
) -> Result<String> {
    let root = inspection
        .root
        .as_ref()
        .context("root template unavailable for identity")?;
    let expected = inspection.dependency_paths.iter().collect::<BTreeSet<_>>();
    let actual = fingerprints
        .iter()
        .map(|value| &value.path)
        .collect::<BTreeSet<_>>();
    ensure!(
        actual == expected && actual.len() == fingerprints.len(),
        "identity requires exactly the inspected source closure"
    );
    let logical_path = |path: &Path| -> Result<String> {
        if path == inspection.entrypoint && path != root.path {
            return Ok("@entrypoint".to_owned());
        }
        if path == inspection.entrypoint && !path.starts_with(&inspection.project_root) {
            return Ok("@external-entrypoint-root".to_owned());
        }
        Ok(path
            .strip_prefix(&inspection.project_root)
            .context("identity dependency is outside project root")?
            .to_string_lossy()
            .into_owned())
    };
    let mut sources = fingerprints
        .iter()
        .map(|value| Ok((logical_path(&value.path)?, &value.sha256)))
        .collect::<Result<Vec<_>>>()?;
    sources.sort();
    let mut compile_settings = definition.compile_args.clone();
    map_library_paths(&mut compile_settings, |path| {
        path.strip_prefix(&inspection.project_root)
            .map(|relative| Path::new("@project-root").join(relative))
            .unwrap_or_else(|_| path.to_path_buf())
    });
    let mut descriptor = serde_json::json!({
        "identity_version": 1,
        "project": definition.project,
        "revision": definition.revision,
        "root_source": logical_path(&root.path)?,
        "root_template": root.template_name,
        "parameters": root.concrete_parameters,
        "sources": sources,
        "prime": definition.prime,
        "compile_args": compile_settings,
        "mode": definition.mode,
        "input_assumptions": definition.input_assumptions,
    });
    if let Some(contract) = &definition.input_contract {
        descriptor["input_contract"] = match contract {
            InputContract::FieldOnly => serde_json::json!({"kind": "field_only"}),
            InputContract::Bounded {
                enforcement,
                evidence,
            } => serde_json::json!({
                "kind": "bounded",
                "enforcement": enforcement,
                "evidence_sha256": evidence.as_ref().map(|value| &value.sha256),
                "entrypoint_sha256": evidence.as_ref().map(|value| &value.entrypoint_sha256),
            }),
        };
    }
    Ok(format!(
        "sha256:{}",
        sha256(&serde_json::to_vec(&descriptor)?)
    ))
}

pub fn prepare_manifest(
    manifest_path: &Path,
    options: &PrepareOptions,
    output_root: &Path,
) -> Result<PreparedCorpus> {
    ensure!(
        options.timeout_seconds > 0,
        "preparation timeout must be positive"
    );
    let started_at = Utc::now();
    let started = Instant::now();
    let manifest_path = fs::canonicalize(manifest_path).context("manifest is unavailable")?;
    let manifest_bytes = fs::read(&manifest_path)?;
    let manifest: CorpusManifest =
        serde_json::from_slice(&manifest_bytes).context("invalid corpus manifest")?;
    ensure!(
        matches!(manifest.schema_version, 1 | 2),
        "unsupported corpus manifest schema version"
    );
    let manifest_schema_version = manifest.schema_version;
    ensure!(!manifest.name.trim().is_empty(), "corpus name is required");
    let manifest_dir = manifest_path.parent().context("manifest has no parent")?;
    let output_dir = output_root.join(format!("prepare-{}", Uuid::new_v4()));
    fs::create_dir_all(&output_dir)?;
    let output_dir = fs::canonicalize(output_dir)?;
    let options = absolute_options(options)?;
    let mut environment = BTreeMap::from([
        ("os".to_owned(), std::env::consts::OS.to_owned()),
        ("arch".to_owned(), std::env::consts::ARCH.to_owned()),
        (
            "zkfdo_version".to_owned(),
            env!("CARGO_PKG_VERSION").to_owned(),
        ),
        (
            "working_directory".to_owned(),
            std::env::current_dir()?.to_string_lossy().into_owned(),
        ),
    ]);
    let mut binaries = vec![("circom", &options.circom_bin)];
    if options.strategy.is_none() || options.strategy == Some(RankingStrategy::RiskGrouped) {
        binaries.push(("zkfuzz", &options.zkfuzz_bin));
    }
    if options.strategy.is_none()
        || matches!(
            options.strategy,
            Some(
                RankingStrategy::RiskOnly
                    | RankingStrategy::RiskGrouped
                    | RankingStrategy::WarningFirst
                    | RankingStrategy::CostAware
            )
        )
    {
        binaries.push(("circomspect", &options.analyzer_bin));
    }
    for (name, binary) in binaries {
        environment.insert(
            format!("{name}_binary"),
            binary.to_string_lossy().into_owned(),
        );
        if let Ok(bytes) = fs::read(binary) {
            environment.insert(format!("{name}_binary_sha256"), sha256(&bytes));
        }
    }
    let mut targets = Vec::new();
    // Instance captures shared by the manifest's targets, parsed once (F-01).
    let mut captures = HashMap::new();
    for (index, target) in manifest.targets.into_iter().enumerate() {
        let definition = resolve_definition(target, manifest_dir);
        let directory = output_dir.join("targets").join(format!("{index:04}"));
        fs::create_dir_all(&directory)?;
        let mut prepared = empty_target(definition)?;
        let target_start = Instant::now();
        if let Err(error) = prepare_target(&mut prepared, &options, &directory, &mut captures) {
            prepared
                .exclusion_reasons
                .push(format!("preparation failed: {error:#}"));
        }
        prepared.exclusion_reasons.extend(input_contract_exclusions(
            &prepared,
            manifest_schema_version,
        ));
        prepared.elapsed_seconds = target_start.elapsed().as_secs_f64();
        prepared.eligible = prepared.exclusion_reasons.is_empty();
        targets.push(prepared);
    }
    let mut identities: BTreeMap<String, Vec<usize>> = BTreeMap::new();
    for (index, target) in targets.iter().enumerate() {
        identities
            .entry(target.target_id.clone())
            .or_default()
            .push(index);
    }
    for indices in identities.values().filter(|indices| indices.len() > 1) {
        for index in indices {
            targets[*index].eligible = false;
            targets[*index].exclusion_reasons.push(
                "duplicate executable target identity in manifest; deduplicate explicitly"
                    .to_owned(),
            );
        }
    }
    for (index, target) in targets.iter().enumerate() {
        write_json(
            &output_dir
                .join("targets")
                .join(format!("{index:04}"))
                .join("prepared-target.json"),
            target,
        )?;
    }
    let report = PreparedCorpus {
        schema_version: 1,
        name: manifest.name,
        description: manifest.description,
        manifest_sha256: sha256(&manifest_bytes),
        manifest_path,
        report_path: output_dir.join("prepared.json"),
        output_dir,
        profile_strategy: options.strategy,
        options,
        environment,
        started_at,
        finished_at: Utc::now(),
        elapsed_seconds: started.elapsed().as_secs_f64(),
        targets,
        exclusions: manifest.exclusions,
        limitations: vec![
            "Manifest defect annotations are user-supplied provenance; preparation does not establish a reproduction or a discovered bug.".to_owned(),
            "Eligibility requires the supported parser's complete reachable template closure; unsupported syntax remains explicitly excluded.".to_owned(),
            "Semantic diagnostics analyze template definitions, not concrete parameter-specialized instances.".to_owned(),
            "Source and snapshot hashes must be rechecked before planning and execution; absolute includes retain read-only references to original files.".to_owned(),
        ],
    };
    write_json(&report.report_path, &report)?;
    Ok(report)
}

fn prepare_target(
    target: &mut PreparedTarget,
    options: &PrepareOptions,
    directory: &Path,
    captures: &mut HashMap<PathBuf, (String, crate::instance_capture::InstanceCapture)>,
) -> Result<()> {
    for (name, value) in [
        ("label", &target.definition.label),
        ("project", &target.definition.project),
        ("revision", &target.definition.revision),
        ("template_name", &target.definition.template_name),
        ("prime", &target.definition.prime),
        ("mode", &target.definition.mode),
        ("input_assumptions", &target.definition.input_assumptions),
    ] {
        if value.trim().is_empty() {
            target
                .exclusion_reasons
                .push(format!("manifest {name} is empty"));
        }
    }
    if !matches!(target.definition.mode.as_str(), "original" | "direct") {
        target.exclusion_reasons.push(
            "manifest mode must be original or direct (entrypoint provenance, not zkFuzz search mode)"
                .to_owned(),
        );
    }
    let start = Instant::now();
    let mut inspection = if target.definition.instance_capture.is_some() {
        // F-01 already supplies these values. Preserve its original comparison metadata.
        inspect_entrypoint_with_libraries(
            &target.definition.entrypoint,
            &target.definition.project_root,
            &compile_library_paths(&target.definition),
        )?
    } else {
        inspect_entrypoint_with_libraries_and_prime(
            &target.definition.entrypoint,
            &target.definition.project_root,
            &compile_library_paths(&target.definition),
            &target.definition.prime,
        )?
    };
    if let Some(capture_path) = target.definition.instance_capture.clone() {
        if !captures.contains_key(&capture_path) {
            let bytes = fs::read(&capture_path)
                .with_context(|| format!("read instance capture {}", capture_path.display()))?;
            let capture: crate::instance_capture::InstanceCapture =
                serde_json::from_slice(&bytes).context("parse instance capture")?;
            captures.insert(capture_path.clone(), (sha256(&bytes), capture));
        }
        let (capture_sha256, capture) = &captures[&capture_path];
        let captured = crate::targets::inspect_entrypoint_from_capture(
            &target.definition.entrypoint,
            &target.definition.project_root,
            &compile_library_paths(&target.definition),
            capture,
        )?;
        let describe = |instance: &crate::targets::InspectedTemplateInstance| {
            format!(
                "{}::{}({})",
                instance.path.display(),
                instance.template_name,
                instance.concrete_parameters.join(", ")
            )
        };
        let compiler = captured
            .instances
            .iter()
            .map(describe)
            .collect::<BTreeSet<_>>();
        let interpreter = inspection
            .instances
            .iter()
            .map(describe)
            .collect::<BTreeSet<_>>();
        target.instance_inspection = Some(InspectionSource {
            source: "compiler".to_owned(),
            capture_path,
            capture_sha256: capture_sha256.clone(),
            compiler_complete: captured.complete,
            interpreter_complete: inspection.complete,
            interpreter_unsupported: inspection.unsupported.len(),
            instances_only_interpreter: interpreter.difference(&compiler).cloned().collect(),
            instances_only_compiler: compiler.difference(&interpreter).cloned().collect(),
        });
        inspection = captured;
    }
    target.timings.inspection_seconds = start.elapsed().as_secs_f64();
    if !inspection.complete {
        target
            .exclusion_reasons
            .extend(inspection.unsupported.iter().map(|case| {
                format!(
                    "unsupported inspection: {}: {}",
                    case.construct, case.reason
                )
            }));
        if inspection.unsupported.is_empty() {
            target
                .exclusion_reasons
                .push("entrypoint inspection is incomplete".to_owned());
        }
    }
    if let Some(root) = &inspection.root {
        if root.template_name != target.definition.template_name {
            target.exclusion_reasons.push(format!(
                "manifest template {} differs from parsed root {}",
                target.definition.template_name, root.template_name
            ));
        }
        if root.concrete_parameters != target.definition.concrete_parameters {
            target.exclusion_reasons.push(format!(
                "manifest parameters {:?} differ from parsed root {:?}",
                target.definition.concrete_parameters, root.concrete_parameters
            ));
        }
    } else {
        target
            .exclusion_reasons
            .push("parsed root template is unavailable".to_owned());
    }
    target.inspection = Some(inspection.clone());
    target.source_fingerprints = fingerprint_sources(&inspection.dependency_paths)?;
    if inspection.root.is_some() {
        target.target_id =
            stable_target_id(&target.definition, &inspection, &target.source_fingerprints)?;
        target.ranking.target_id = target.target_id.clone();
    }
    let start = Instant::now();
    let (run_entrypoint, snapshots) = snapshot_sources(
        &inspection,
        &target.source_fingerprints,
        &directory.join("sources"),
    )?;
    target.run_entrypoint = Some(run_entrypoint.clone());
    target.snapshot_fingerprints = snapshots;
    target.timings.snapshot_seconds = start.elapsed().as_secs_f64();
    let collect_ast =
        options.strategy.is_none() || options.strategy == Some(RankingStrategy::RiskGrouped);
    let collect_semantic = options.strategy.is_none()
        || matches!(
            options.strategy,
            Some(
                RankingStrategy::RiskOnly
                    | RankingStrategy::RiskGrouped
                    | RankingStrategy::WarningFirst
                    | RankingStrategy::CostAware
            )
        );
    let collect_legacy =
        options.strategy.is_none() || options.strategy == Some(RankingStrategy::Legacy);
    let root_name = inspection
        .root
        .as_ref()
        .map(|root| root.template_name.as_str())
        .unwrap_or(&target.definition.template_name);
    let start = Instant::now();
    match profile_target_with_ast(
        &run_entrypoint,
        root_name,
        &options.circom_bin,
        &options.zkfuzz_bin,
        &target.definition.prime,
        &target.definition.compile_args,
        &directory.join("structure"),
        options.timeout_seconds,
        collect_ast,
    ) {
        Ok(profile) => {
            if !profile.complete {
                target.exclusion_reasons.extend(
                    profile
                        .errors
                        .iter()
                        .map(|error| format!("structure: {error}")),
                );
            }
            if !profile.compile_success || profile.size.is_none() {
                target
                    .exclusion_reasons
                    .push("compilation or compiled size is unavailable".to_owned());
            }
            if collect_ast && profile.complexity.is_none() {
                target
                    .exclusion_reasons
                    .push("required root AST complexity is unavailable".to_owned());
            }
            target.ranking.size = profile.size;
            target.ranking.complexity = profile.complexity;
            target.structure = Some(profile);
        }
        Err(error) => target
            .exclusion_reasons
            .push(format!("structure preparation failed: {error:#}")),
    }
    target.timings.structure_seconds = start.elapsed().as_secs_f64();
    if collect_semantic {
        let start = Instant::now();
        if inspection.complete {
            // Source scopes are always parser-produced. Original paths preserve absolute include
            // semantics and SARIF provenance; the analyzer only writes into its output directory.
            let scopes = inspection
                .scopes
                .iter()
                .map(|scope| SourceScope {
                    path: scope.path.clone(),
                    template_name: scope.template_name.clone(),
                    start_line: scope.start_line,
                    end_line: scope.end_line,
                })
                .collect::<Vec<_>>();
            let curve = match target.definition.prime.as_str() {
                "bn128" => Some("BN254"),
                "bls12381" => Some("BLS12_381"),
                "goldilocks" => Some("GOLDILOCKS"),
                _ => None,
            };
            if let Some(curve) = curve {
                let analysis_options = AnalysisOptions {
                    binary: options.analyzer_bin.clone(),
                    curve: curve.to_owned(),
                    timeout_seconds: options.timeout_seconds,
                    tool_version: options.analyzer_version.clone(),
                    tool_revision: options.analyzer_revision.clone(),
                    library_paths: semantic_library_paths(&target.definition),
                };
                match semantic::analyze_target(
                    &scopes,
                    &analysis_options,
                    &directory.join("semantic"),
                ) {
                    Ok(analysis) => {
                        if analysis.complete {
                            target.ranking.risk_score =
                                analysis.risk_score.map(|score| score as u64);
                            target.ranking.warning_count = Some(analysis.warning_count as u64);
                        } else {
                            target.exclusion_reasons.extend(
                                analysis
                                    .reasons
                                    .iter()
                                    .map(|reason| format!("semantic: {reason}")),
                            );
                            target
                                .exclusion_reasons
                                .push("required semantic features are incomplete".to_owned());
                        }
                        target.semantic = Some(analysis);
                    }
                    Err(error) => target
                        .exclusion_reasons
                        .push(format!("semantic preparation failed: {error:#}")),
                }
            } else {
                target.exclusion_reasons.push(format!(
                    "Circomspect does not support prime {}",
                    target.definition.prime
                ));
            }
        } else {
            target.exclusion_reasons.push(
                "semantic attribution unavailable because reachable scopes are incomplete"
                    .to_owned(),
            );
        }
        target.timings.semantic_seconds = start.elapsed().as_secs_f64();
    }
    if collect_legacy {
        let start = Instant::now();
        if let Some(root) = &inspection.root {
            match fs::read_to_string(&root.path) {
                Ok(source) => {
                    let features = extract_features_from_source(&root.path, &source);
                    target.ranking.legacy_score =
                        Some(static_risk_score(&features) / estimated_cost_score(&features));
                }
                Err(error) => target
                    .exclusion_reasons
                    .push(format!("legacy root source is unavailable: {error}")),
            }
        } else {
            target
                .exclusion_reasons
                .push("legacy root source is unknown".to_owned());
        }
        target.timings.legacy_seconds = start.elapsed().as_secs_f64();
        target.limitations.push("Legacy baseline maps the existing lexical risk/cost formula over the entire root template source file, including unrelated templates in that file; it is not semantic risk.".to_owned());
    }
    verify_fingerprints(&target.source_fingerprints)?;
    verify_fingerprints(&target.snapshot_fingerprints)?;
    Ok(())
}

fn input_contract_exclusions(target: &PreparedTarget, manifest_schema_version: u32) -> Vec<String> {
    if manifest_schema_version == 1 {
        return if target.definition.input_contract.is_some() {
            vec!["input_contract requires corpus manifest schema 2".to_owned()]
        } else {
            Vec::new()
        };
    }
    if target.definition.input_contract.is_none() {
        return vec!["schema 2 target is missing input_contract".to_owned()];
    }
    verify_input_contract_evidence(target)
        .err()
        .map(|error| vec![format!("{error:#}")])
        .unwrap_or_default()
}

/// Recheck the review record before planning or execution. A matching hash binds the review
/// to the executable source; it does not independently prove the reviewer's conclusion.
pub fn verify_input_contract_evidence(target: &PreparedTarget) -> Result<()> {
    match &target.definition.input_contract {
        None | Some(InputContract::FieldOnly) => Ok(()),
        Some(InputContract::Bounded {
            enforcement: BoundedEnforcement::Unverified,
            ..
        }) => anyhow::bail!("bounded input contract is not reviewed in the executable target"),
        Some(InputContract::Bounded {
            enforcement: BoundedEnforcement::ReviewedInExecutable,
            evidence,
        }) => {
            let evidence = evidence
                .as_ref()
                .context("reviewed bounded input contract has no evidence")?;
            let entrypoint = target
                .source_fingerprints
                .iter()
                .find(|source| source.path == target.definition.entrypoint)
                .context("reviewed bounded input contract has no fingerprinted entrypoint")?;
            ensure!(
                entrypoint.sha256 == evidence.entrypoint_sha256,
                "input contract evidence is bound to a different entrypoint"
            );
            ensure!(
                sha256(&serde_json::to_vec(&target.source_fingerprints)?)
                    == evidence.source_closure_sha256,
                "input contract evidence is bound to a different source closure"
            );
            let bytes =
                fs::read(&evidence.path).context("input contract evidence is unavailable")?;
            ensure!(
                sha256(&bytes) == evidence.sha256,
                "input contract evidence hash mismatch"
            );
            Ok(())
        }
    }
}

fn empty_target(definition: CorpusTarget) -> Result<PreparedTarget> {
    let target_id = format!("invalid:{}", sha256(&serde_json::to_vec(&definition)?));
    let ranking = RankingInput {
        target_id: target_id.clone(),
        path: definition.entrypoint.clone(),
        risk_score: None,
        warning_count: None,
        complexity: None,
        size: None,
        legacy_score: None,
    };
    Ok(PreparedTarget {
        target_id, definition, inspection: None, run_entrypoint: None, structure: None, semantic: None,
        ranking, eligible: false, exclusion_reasons: Vec::new(), source_fingerprints: Vec::new(),
        snapshot_fingerprints: Vec::new(), timings: PreparationTimings::default(), elapsed_seconds: 0.0,
        limitations: vec!["Semantic locations refer to the fingerprinted original sources; compiler/AST execution and future fuzzing use the copied entrypoint. Absolute includes can retain read-only original dependencies.".to_owned()],
        instance_inspection: None,
    })
}

fn snapshot_sources(
    inspection: &EntrypointInspection,
    fingerprints: &[SourceFingerprint],
    snapshot_dir: &Path,
) -> Result<(PathBuf, Vec<SourceFingerprint>)> {
    let common = source_common_root(inspection)?;
    let mut paths = Vec::new();
    for fingerprint in fingerprints {
        let relative = fingerprint
            .path
            .strip_prefix(common)
            .context("source outside snapshot root")?;
        let destination = snapshot_dir.join(relative);
        fs::create_dir_all(
            destination
                .parent()
                .context("snapshot file has no parent")?,
        )?;
        let bytes = fs::read(&fingerprint.path)?;
        ensure!(
            sha256(&bytes) == fingerprint.sha256,
            "source changed before snapshot: {}",
            fingerprint.path.display()
        );
        fs::write(&destination, bytes)?;
        paths.push(destination);
    }
    let entrypoint = snapshot_dir.join(inspection.entrypoint.strip_prefix(common)?);
    ensure!(
        entrypoint.is_file(),
        "entrypoint was not captured in source closure"
    );
    Ok((fs::canonicalize(entrypoint)?, fingerprint_sources(&paths)?))
}

fn source_common_root(inspection: &EntrypointInspection) -> Result<&Path> {
    let mut common = inspection.project_root.as_path();
    let entry_parent = inspection
        .entrypoint
        .parent()
        .context("entrypoint has no parent")?;
    while !entry_parent.starts_with(common) {
        common = common
            .parent()
            .context("entrypoint and project have no common ancestor")?;
    }
    Ok(common)
}

fn resolve_definition(mut target: CorpusTarget, parent: &Path) -> CorpusTarget {
    target.project_root = resolve_path(parent, &target.project_root);
    target.entrypoint = resolve_path(parent, &target.entrypoint);
    if let Some(capture) = &target.instance_capture {
        target.instance_capture = Some(resolve_path(parent, capture));
    }
    if let Some(InputContract::Bounded {
        evidence: Some(evidence),
        ..
    }) = &mut target.input_contract
    {
        evidence.path = resolve_path(parent, &evidence.path);
    }
    for defect in &mut target.known_defects {
        for evidence in &mut defect.evidence {
            *evidence = resolve_path(parent, evidence);
        }
    }
    // Only library search operands are paths. Other compiler flags retain their exact spelling.
    map_library_paths(&mut target.compile_args, |path| resolve_path(parent, path));
    target
}

fn map_library_paths(args: &mut [String], map: impl Fn(&Path) -> PathBuf) {
    let mut index = 0;
    while index < args.len() {
        if args[index] == "-l" {
            index += 1;
            while index < args.len() && !args[index].starts_with('-') {
                args[index] = map(Path::new(&args[index])).to_string_lossy().into_owned();
                index += 1;
            }
        } else {
            index += 1;
        }
    }
}

/// The `-l` operands of the semantic compile arguments, in compiler search order.
pub fn compile_library_paths(definition: &CorpusTarget) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    let mut index = 0;
    while index < definition.compile_args.len() {
        if definition.compile_args[index] == "-l" {
            index += 1;
            while index < definition.compile_args.len()
                && !definition.compile_args[index].starts_with('-')
            {
                paths.push(PathBuf::from(&definition.compile_args[index]));
                index += 1;
            }
        } else {
            index += 1;
        }
    }
    paths
}

fn semantic_library_paths(definition: &CorpusTarget) -> Vec<PathBuf> {
    let mut paths = vec![definition.project_root.clone()];
    let mut index = 0;
    while index < definition.compile_args.len() {
        if definition.compile_args[index] == "-l" {
            index += 1;
            while index < definition.compile_args.len()
                && !definition.compile_args[index].starts_with('-')
            {
                paths.push(PathBuf::from(&definition.compile_args[index]));
                index += 1;
            }
        } else {
            index += 1;
        }
    }
    paths.sort();
    paths.dedup();
    paths
}

fn resolve_path(parent: &Path, path: &Path) -> PathBuf {
    let joined = if path.is_absolute() {
        path.to_path_buf()
    } else {
        parent.join(path)
    };
    fs::canonicalize(&joined).unwrap_or(joined)
}

fn absolute_options(options: &PrepareOptions) -> Result<PrepareOptions> {
    let cwd = std::env::current_dir()?;
    let mut resolved = options.clone();
    for binary in [
        &mut resolved.circom_bin,
        &mut resolved.zkfuzz_bin,
        &mut resolved.analyzer_bin,
    ] {
        if binary.components().count() > 1 {
            *binary = resolve_path(&cwd, binary);
        } else if let Some(found) = std::env::var_os("PATH")
            .into_iter()
            .flat_map(|path| std::env::split_paths(&path).collect::<Vec<_>>())
            .map(|directory| directory.join(&*binary))
            .find(|candidate| candidate.is_file())
        {
            *binary = resolve_path(&cwd, &found);
        }
    }
    Ok(resolved)
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let temporary = path.with_extension("json.tmp");
    fs::write(&temporary, serde_json::to_vec_pretty(value)?)?;
    fs::rename(temporary, path)?;
    Ok(())
}
