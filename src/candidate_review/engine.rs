use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    ops::Range,
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
    time::Instant,
};

use anyhow::{bail, ensure, Context, Result};
use num_bigint::BigUint;
use num_traits::One;
use serde::{
    de::{MapAccess, Visitor},
    Deserialize, Deserializer, Serialize,
};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::{
    experiment::{
        self, ConfirmationSet, DefectConfirmation, EvidenceOrigin, ExperimentOutcome,
        ExperimentPlan, OriginalComponentReview, ReviewCriterion, ReviewVerdict,
    },
    runner::RunStatus,
    targets,
};

use super::{
    predicate::run_predicate,
    r1cs::{R1cs, SymbolTable},
    schema::*,
    subprocess::{run_bounded, COMPILER_TIMEOUT, EXTERNAL_VERIFIER_TIMEOUT, GENERATOR_TIMEOUT},
};

pub const ENGINE_VERSION: &str = "candidate-review-schema1";
const ZKFUZZ_CANDIDATE_ADAPTER_ID: &str = "zkfuzz-counterexample-v1";
const ZKFUZZ_ASSIGNMENT_ADAPTER_ID: &str = "zkfuzz-assignment-v1";
const WTNS_JSON_ADAPTER_ID: &str = "wtns-json-v1";
const ZKFUZZ_CANDIDATE_ADAPTER_DESCRIPTION: &str =
    "zkfDO candidate adapter zkfuzz-counterexample-v1 schema 1\n";
const ZKFUZZ_ASSIGNMENT_ADAPTER_DESCRIPTION: &str =
    "zkfDO assignment adapter zkfuzz-assignment-v1 schema 1\n";
const WTNS_JSON_ADAPTER_DESCRIPTION: &str = "zkfDO assignment adapter wtns-json-v1 schema 1\n";
const REVIEW_ENGINE_SOURCE: &str = include_str!("engine.rs");
const REVIEW_EXPERIMENT_SOURCE: &str = include_str!("../experiment.rs");
const REVIEW_PREDICATE_SOURCE: &str = include_str!("predicate.rs");
const REVIEW_R1CS_SOURCE: &str = include_str!("r1cs.rs");
const REVIEW_SCHEMA_SOURCE: &str = include_str!("schema.rs");
const REVIEW_SUBPROCESS_SOURCE: &str = include_str!("subprocess.rs");
const REVIEW_STRUCTURE_SOURCE: &str = include_str!("../structure.rs");
const TARGET_DISCOVERY_SOURCE: &str = include_str!("../targets.rs");

#[derive(Debug, Clone)]
pub struct ReviewOptions {
    pub request: PathBuf,
    pub output: PathBuf,
    pub python_bin: PathBuf,
    pub source_revision: String,
    pub engine_source_manifest: PathBuf,
    pub executable: PathBuf,
}

#[derive(Debug, Clone, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewOutput {
    pub report_path: PathBuf,
    pub report_sha256: String,
    pub bundle_index_path: Option<PathBuf>,
    pub bundle_index_sha256: Option<String>,
    pub status: ReportStatus,
}

#[derive(Clone)]
struct LoadedSpec {
    spec: ReviewSpec,
    path: PathBuf,
    sha256: String,
    report_ref: FileRef,
    source_path: PathBuf,
    source_closure: BTreeMap<PathBuf, String>,
    r1cs_path: PathBuf,
    sym_path: PathBuf,
    contract_path: PathBuf,
    predicate_path: PathBuf,
    attribution_path: PathBuf,
    r1cs: R1cs,
    symbols: SymbolTable,
}

#[derive(Debug)]
struct NormalizedAssignment {
    wires: Vec<BigUint>,
    wire_signals: BTreeMap<String, String>,
    eliminated_signals: BTreeMap<String, String>,
    parameters: BTreeMap<String, TypedParameterValue>,
    canonical: bool,
}

impl NormalizedAssignment {
    fn signal(&self, name: &str) -> Result<&str> {
        match (
            self.wire_signals.get(name),
            self.eliminated_signals.get(name),
        ) {
            (Some(value), None) | (None, Some(value)) => Ok(value),
            (None, None) => bail!("assignment signal {name} is unavailable"),
            (Some(_), Some(_)) => bail!("assignment signal {name} has ambiguous categories"),
        }
    }

    fn all_signals(&self) -> Result<BTreeMap<String, String>> {
        let mut result = self.wire_signals.clone();
        for (name, value) in &self.eliminated_signals {
            ensure!(
                result.insert(name.clone(), value.clone()).is_none(),
                "assignment signal {name} has ambiguous categories"
            );
        }
        Ok(result)
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawCounterexample {
    #[serde(rename = "0_target_path")]
    target_path: String,
    #[serde(rename = "1_main_template")]
    main_template: String,
    #[serde(rename = "2_search_mode")]
    search_mode: String,
    #[serde(rename = "3_execution_time")]
    execution_time: String,
    #[serde(rename = "4_git_hash_of_zkfuzz")]
    zkfuzz_revision: String,
    #[serde(rename = "5_flag")]
    flag: Value,
    #[serde(rename = "6_target_output", default)]
    target_output: Option<String>,
    #[serde(
        rename = "7_assignment",
        deserialize_with = "deserialize_unique_assignment"
    )]
    assignment: BTreeMap<String, String>,
    #[serde(rename = "8_auxiliary_result")]
    auxiliary_result: Value,
}

fn deserialize_unique_assignment<'de, D>(
    deserializer: D,
) -> std::result::Result<BTreeMap<String, String>, D::Error>
where
    D: Deserializer<'de>,
{
    struct AssignmentVisitor;

    impl<'de> Visitor<'de> for AssignmentVisitor {
        type Value = BTreeMap<String, String>;

        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("an assignment object with unique signal names")
        }

        fn visit_map<A>(self, mut map: A) -> std::result::Result<Self::Value, A::Error>
        where
            A: MapAccess<'de>,
        {
            let mut assignment = BTreeMap::new();
            while let Some(name) = map.next_key::<String>()? {
                if assignment.contains_key(&name) {
                    return Err(serde::de::Error::custom("duplicate assignment key"));
                }
                assignment.insert(name, map.next_value::<String>()?);
            }
            Ok(assignment)
        }
    }

    deserializer.deserialize_map(AssignmentVisitor)
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct WitnessJson {
    witness: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum WitnessAssignment {
    Object(WitnessJson),
    Array(Vec<String>),
}

#[derive(Clone)]
struct VerifiedQualification {
    index_path: PathBuf,
    index_sha256: String,
    spec_sha256: String,
}

#[derive(Debug, Clone)]
struct VerifiedManifestEntry {
    canonical_path: PathBuf,
    sha256: String,
}

#[derive(Clone)]
struct PreparedCompileBinding {
    r1cs_sha256: String,
    recorded_r1cs_sha256: Option<String>,
    compiler_binary_sha256: String,
    compiler_arguments: Vec<String>,
}

struct StagedOutput {
    staging_path: PathBuf,
    final_path: PathBuf,
    published: bool,
}

impl StagedOutput {
    fn create(requested_final_path: &Path) -> Result<Self> {
        ensure!(
            !requested_final_path.exists(),
            "refusing to overwrite candidate review output: {}",
            requested_final_path.display()
        );
        let absolute = if requested_final_path.is_absolute() {
            requested_final_path.to_path_buf()
        } else {
            std::env::current_dir()?.join(requested_final_path)
        };
        let file_name = absolute
            .file_name()
            .context("candidate review output must name a directory")?
            .to_os_string();
        let parent = absolute
            .parent()
            .context("candidate review output has no parent")?;
        fs::create_dir_all(parent).with_context(|| {
            format!("create candidate review output parent {}", parent.display())
        })?;
        let parent = fs::canonicalize(parent)?;
        let final_path = parent.join(file_name);
        ensure!(
            !final_path.exists(),
            "refusing to overwrite candidate review output: {}",
            final_path.display()
        );
        let staging_path = loop {
            let candidate = parent.join(format!(
                ".zkfdo-candidate-review-{}.staging",
                Uuid::new_v4()
            ));
            match fs::create_dir(&candidate) {
                Ok(()) => break candidate,
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => {
                    return Err(error).with_context(|| {
                        format!(
                            "create candidate review staging directory {}",
                            candidate.display()
                        )
                    });
                }
            }
        };
        Ok(Self {
            staging_path,
            final_path,
            published: false,
        })
    }

    fn path(&self) -> &Path {
        &self.staging_path
    }

    fn publish(mut self) -> Result<PathBuf> {
        ensure!(
            !self.final_path.exists(),
            "candidate review output appeared before publication: {}",
            self.final_path.display()
        );
        fs::rename(&self.staging_path, &self.final_path).with_context(|| {
            format!(
                "publish candidate review output {}",
                self.final_path.display()
            )
        })?;
        self.published = true;
        Ok(self.final_path.clone())
    }
}

impl Drop for StagedOutput {
    fn drop(&mut self) {
        if !self.published {
            let _ = fs::remove_dir_all(&self.staging_path);
        }
    }
}

pub fn review(options: &ReviewOptions) -> Result<ReviewOutput> {
    ensure!(
        !options.output.exists(),
        "refusing to overwrite candidate review output: {}",
        options.output.display()
    );
    ensure!(
        !options.source_revision.trim().is_empty(),
        "engine source revision must not be empty"
    );

    let request_path = fs::canonicalize(&options.request)
        .with_context(|| format!("resolve review request {}", options.request.display()))?;
    let request_bytes = fs::read(&request_path)?;
    let request: ReviewRequest =
        serde_json::from_slice(&request_bytes).context("parse strict review request schema 1")?;
    ensure!(request.schema_version() == 1, "unsupported request schema");
    ensure!(
        !request.request_id().trim().is_empty(),
        "request_id must not be empty"
    );

    let source_manifest = fs::canonicalize(&options.engine_source_manifest).with_context(|| {
        format!(
            "resolve engine source manifest {}",
            options.engine_source_manifest.display()
        )
    })?;
    let executable = resolve_review_executable(&options.executable)?;
    ensure!(
        source_manifest.is_file(),
        "engine source manifest is not a file"
    );
    ensure!(executable.is_file(), "review executable is not a file");
    let predicate_runner = resolve_executable(&options.python_bin)
        .with_context(|| format!("resolve predicate runner {}", options.python_bin.display()))?;
    let engine_sources = verify_directory_manifest(&source_manifest)?;
    verify_engine_source_manifest(&engine_sources)?;

    let staged_output = StagedOutput::create(&options.output)?;
    let output_dir = staged_output.path().to_path_buf();
    let report_path = output_dir.join("review-report.json");
    let request_ref = file_ref_from(&output_dir, &request_path)?;
    let engine = EngineProvenance {
        version: ENGINE_VERSION.to_owned(),
        source_revision: options.source_revision.clone(),
        source_manifest_path: relative_path(&output_dir, &source_manifest)?,
        source_manifest_sha256: sha256_file(&source_manifest)?,
        executable_path: relative_path(&output_dir, &executable)?,
        executable_sha256: sha256_file(&executable)?,
        predicate_runner_path: relative_path(&output_dir, &predicate_runner)?,
        predicate_runner_sha256: sha256_file(&predicate_runner)?,
    };

    let build = match &request {
        ReviewRequest::Backend(backend) => build_backend_report(
            backend,
            &request_path,
            &request_ref,
            &output_dir,
            &engine,
            &predicate_runner,
        ),
        ReviewRequest::Injection(injection) => build_injection_report(
            injection,
            &request_path,
            &request_ref,
            &output_dir,
            &engine,
            &predicate_runner,
        ),
    };

    let (mut report, backend_context, injection_context) = match build {
        Ok(result) => result,
        Err(error) => {
            let kind = match request {
                ReviewRequest::Backend(_) => ReportKind::BackendCandidates,
                ReviewRequest::Injection(_) => ReportKind::InjectionGroundTruth,
            };
            let summary = match kind {
                ReportKind::BackendCandidates => ReviewSummary::Backend(BackendSummary {
                    validated: 0,
                    rejected: 0,
                    unresolved: 0,
                    review_error: 0,
                    unreviewed_candidates: 0,
                    attributed_validated: 0,
                    unique_validated_root_causes: 0,
                }),
                ReportKind::InjectionGroundTruth => ReviewSummary::Injection(InjectionSummary {
                    validated: 0,
                    rejected: 0,
                    unresolved: 0,
                    review_error: 0,
                    qualified: 0,
                }),
            };
            (
                ReviewReport {
                    schema_version: 1,
                    report_id: request.request_id().to_owned(),
                    kind,
                    status: ReportStatus::Failed,
                    review_request: request_ref.clone(),
                    review_specs: Vec::new(),
                    engine: engine.clone(),
                    adapters: request_adapters(&request),
                    failure: Some(ReportFailure {
                        stage: "shared-input-validation".to_owned(),
                        reason_code: stable_shared_failure_code(&error),
                        evidence: vec![request_ref.clone()],
                    }),
                    candidate_inventory: None,
                    executions: Vec::new(),
                    candidate_errors: Vec::new(),
                    unreviewed_candidates: Vec::new(),
                    reviews: Vec::new(),
                    summary,
                    semantic_result_sha256: String::new(),
                    raw_values_persisted: false,
                },
                None,
                None,
            )
        }
    };

    report.semantic_result_sha256 = semantic_result_sha256(&report, &request_ref.sha256)?;
    write_json_new(&report_path, &report)?;
    let report_sha256 = sha256_file(&report_path)?;

    let index_path = if report.status == ReportStatus::Complete {
        match (&request, backend_context, injection_context) {
            (ReviewRequest::Backend(request), Some(context), None) => Some(write_backend_outputs(
                request,
                &request_path,
                &report,
                &report_path,
                &context,
                &output_dir,
            )?),
            (ReviewRequest::Injection(_), None, Some(context)) => {
                if context.qualification == GroundTruthQualification::Qualified {
                    Some(write_injection_index(
                        &report,
                        &report_path,
                        &context,
                        &output_dir,
                        &request_path,
                    )?)
                } else {
                    None
                }
            }
            _ => bail!("internal review output kind mismatch"),
        }
    } else {
        None
    };

    let index_sha256 = index_path.as_deref().map(sha256_file).transpose()?;
    let report_relative = report_path
        .strip_prefix(&output_dir)
        .context("staged report escaped its output directory")?
        .to_path_buf();
    let index_relative = index_path
        .as_deref()
        .map(|path| {
            path.strip_prefix(&output_dir)
                .context("staged index escaped its output directory")
                .map(Path::to_path_buf)
        })
        .transpose()?;
    let status = report.status;
    let final_output_dir = staged_output.publish()?;
    Ok(ReviewOutput {
        report_path: final_output_dir.join(report_relative),
        report_sha256,
        bundle_index_path: index_relative.map(|path| final_output_dir.join(path)),
        bundle_index_sha256: index_sha256,
        status,
    })
}

type BuildResult = (
    ReviewReport,
    Option<BackendOutputContext>,
    Option<InjectionOutputContext>,
);

#[derive(Clone)]
struct BackendOutputContext {
    executions: Vec<BackendExecutionContext>,
    specs: BTreeMap<String, LoadedSpec>,
}

#[derive(Clone)]
struct BackendExecutionContext {
    request: BackendExecutionRequest,
    plan_path: PathBuf,
    outcome_path: PathBuf,
}

#[derive(Clone)]
struct InjectionOutputContext {
    spec: LoadedSpec,
    injection_id: String,
    qualification: GroundTruthQualification,
}

#[derive(Clone)]
struct InjectionErrorContext {
    spec: LoadedSpec,
    injection_id: String,
    disturbance: FileRef,
    clean_reference: FileRef,
}

fn build_backend_report(
    request: &BackendRequest,
    request_path: &Path,
    request_ref: &FileRef,
    report_dir: &Path,
    engine: &EngineProvenance,
    python_bin: &Path,
) -> Result<BuildResult> {
    ensure!(
        request.schema_version == 1,
        "unsupported backend request schema"
    );
    ensure!(
        request.candidate_policy == "all-outcome-candidates",
        "unsupported candidate policy"
    );
    ensure!(
        request.unmatched_candidate_policy == "record-unreviewed",
        "unsupported unmatched-candidate policy"
    );
    ensure!(
        !request.review_specs.is_empty(),
        "backend request has no specs"
    );
    ensure!(
        !request.executions.is_empty(),
        "backend request has no executions"
    );
    ensure!(
        request.candidate_adapter.id == ZKFUZZ_CANDIDATE_ADAPTER_ID,
        "unsupported candidate adapter"
    );
    ensure!(
        request.candidate_adapter.implementation_sha256
            == implementation_hash(ZKFUZZ_CANDIDATE_ADAPTER_DESCRIPTION),
        "candidate adapter implementation hash mismatch"
    );

    let mut specs = BTreeMap::new();
    let mut report_spec_refs = Vec::new();
    for reference in &request.review_specs {
        let loaded = load_spec(request_path, reference, report_dir)?;
        ensure!(
            specs
                .insert(loaded.spec.review_spec_id.clone(), loaded.clone())
                .is_none(),
            "duplicate review_spec_id"
        );
        report_spec_refs.push(loaded.report_ref.clone());
    }
    report_spec_refs.sort_by(|left, right| left.sha256.cmp(&right.sha256));

    let project_scope_verifications = specs
        .iter()
        .filter(|(_, spec)| spec.spec.expected_scope == experiment::ConfirmationScope::Project)
        .map(|(id, spec)| {
            let criterion = verify_production_reachability(spec, report_dir)?;
            ensure!(
                spec.spec.production_reachability.verdict == ReachabilityVerdict::Satisfied
                    && criterion.verdict == CriterionVerdict::Satisfied,
                "project scope requires verified production reachability"
            );
            Ok((id.clone(), criterion))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;

    let mut expected_qualifications = BTreeMap::new();
    for spec in specs
        .values()
        .filter(|spec| spec.spec.attribution.method == AttributionMethod::InjectionSingleDiff)
    {
        let injection = spec
            .spec
            .injection_ground_truth
            .as_ref()
            .context("injection attribution spec lacks injection_ground_truth")?;
        ensure!(
            expected_qualifications
                .insert(injection.injection_id.clone(), spec.sha256.clone())
                .is_none(),
            "multiple backend specs reuse one injection qualification ID"
        );
    }
    let qualifications = verify_qualification_bundles(
        request,
        request_path,
        report_dir,
        engine,
        python_bin,
        &expected_qualifications,
    )?;
    for spec in specs.values() {
        if spec.spec.attribution.method == AttributionMethod::InjectionSingleDiff {
            let injection = spec
                .spec
                .injection_ground_truth
                .as_ref()
                .context("injection attribution spec lacks injection_ground_truth")?;
            let qualification = qualifications
                .get(&injection.injection_id)
                .context("injection backend spec lacks a qualified ground-truth bundle")?;
            ensure!(
                qualification.spec_sha256 == spec.sha256,
                "qualification bundle points to another review spec"
            );
        }
    }

    let mut execution_ids = BTreeSet::new();
    let mut pair_hashes = BTreeSet::new();
    let mut pair_ids = BTreeSet::new();
    let mut outcome_ids = BTreeSet::new();
    let mut experiment_ids = BTreeSet::new();
    let mut campaign_coordinates = BTreeSet::new();
    let mut global_run_ids = BTreeSet::new();
    let mut candidate_paths = BTreeSet::new();
    let mut execution_records = Vec::new();
    let mut candidate_errors = Vec::new();
    let mut unreviewed = Vec::new();
    let mut reviews = Vec::new();
    let mut contexts = Vec::new();
    let mut outcome_candidate_count = 0usize;
    let mut matched_candidate_count = 0usize;
    let mut unmatched_candidate_count = 0usize;
    let mut candidate_error_count = 0usize;
    let mut bound_spec_ids = BTreeSet::new();
    let mut prepared_binding_cache =
        BTreeMap::<(PathBuf, String), BTreeMap<String, PreparedCompileBinding>>::new();

    let coordinated_campaign = request
        .executions
        .iter()
        .all(|execution| execution.campaign_coordinates.is_some());
    ensure!(
        coordinated_campaign
            || (request.executions.len() == 1
                && request.executions[0].campaign_coordinates.is_none()),
        "campaign coordinates must cover every execution or a single pilot"
    );

    for execution in &request.executions {
        ensure!(
            !execution.execution_id.trim().is_empty(),
            "execution_id must not be empty"
        );
        ensure!(
            execution_ids.insert(execution.execution_id.clone()),
            "duplicate execution_id"
        );
        let plan_path = verify_file_ref(request_path, &execution.plan)?;
        let outcome_path = verify_file_ref(request_path, &execution.outcome)?;
        ensure!(
            pair_hashes.insert((
                execution.plan.sha256.clone(),
                execution.outcome.sha256.clone()
            )),
            "duplicate plan/outcome pair"
        );
        let plan_bytes = fs::read(&plan_path)?;
        let plan = experiment::load_plan(&plan_bytes)?;
        let prepared_path = fs::canonicalize(&plan.prepared_path).with_context(|| {
            format!(
                "resolve frozen prepared corpus {}",
                plan.prepared_path.display()
            )
        })?;
        let prepared_key = (prepared_path, plan.prepared_sha256.clone());
        if !prepared_binding_cache.contains_key(&prepared_key) {
            prepared_binding_cache.insert(prepared_key.clone(), prepared_compile_bindings(&plan)?);
        }
        let prepared_bindings = prepared_binding_cache
            .get(&prepared_key)
            .context("prepared compile binding cache lost its inserted entry")?;
        let outcome: ExperimentOutcome = serde_json::from_slice(&fs::read(&outcome_path)?)
            .context("parse experiment outcome")?;
        validate_outcome_structure(&plan, &plan_bytes, &outcome)?;
        ensure!(
            !plan.plan_id.trim().is_empty()
                && !outcome.outcome_id.trim().is_empty()
                && !outcome.scheduler.experiment_id.trim().is_empty(),
            "plan, outcome, and scheduler experiment IDs must not be empty"
        );
        for target in &plan.targets {
            for spec in specs
                .values()
                .filter(|spec| spec.spec.target_binding.target_id == target.target_id)
            {
                let compile_binding = prepared_bindings
                    .get(&target.target_id)
                    .context("plan target has no frozen prepared compile binding")?;
                validate_spec_plan_source_binding(spec, target, compile_binding)?;
                bound_spec_ids.insert(spec.spec.review_spec_id.clone());
            }
        }
        ensure!(
            pair_ids.insert((plan.plan_id.clone(), outcome.outcome_id.clone())),
            "duplicate plan/outcome identity"
        );
        ensure!(
            outcome_ids.insert(outcome.outcome_id.clone()),
            "duplicate outcome_id"
        );
        ensure!(
            experiment_ids.insert(outcome.scheduler.experiment_id.clone()),
            "duplicate scheduler experiment_id"
        );
        if let Some(coordinates) = &execution.campaign_coordinates {
            ensure!(
                coordinates.strategy == plan.strategy.to_string(),
                "campaign strategy differs from plan strategy"
            );
            ensure!(
                campaign_coordinates.insert((coordinates.block, coordinates.strategy.clone())),
                "duplicate campaign coordinates"
            );
        }

        let run_map = outcome
            .scheduler
            .runs
            .iter()
            .map(|run| (run.result.run_id.as_str(), run))
            .collect::<BTreeMap<_, _>>();
        let mut candidate_counts = BTreeMap::<String, usize>::new();
        for artifact in &outcome.counterexample_candidates {
            *candidate_counts.entry(artifact.run_id.clone()).or_default() += 1;
        }
        for run in &outcome.scheduler.runs {
            ensure!(
                !run.result.run_id.trim().is_empty(),
                "backend run ID must not be empty"
            );
            ensure!(
                global_run_ids.insert(run.result.run_id.clone()),
                "backend run ID is repeated across executions"
            );
            let count = candidate_counts
                .get(&run.result.run_id)
                .copied()
                .unwrap_or_default();
            ensure!(
                (run.result.status == RunStatus::BugFound && count > 0)
                    || (run.result.status != RunStatus::BugFound && count == 0),
                "candidate inventory is inconsistent with backend status"
            );
            execution_records.push(ExecutionRecord {
                execution_id: execution.execution_id.clone(),
                plan_index: run.index,
                run_id: Some(run.result.run_id.clone()),
                target_id: run.target_id.clone(),
                backend_status: run_status_name(&run.result.status).to_owned(),
                candidate_count: count,
                candidate_status: if count == 0 {
                    CandidateStatus::NoCandidate
                } else {
                    CandidateStatus::CandidatePresent
                },
            });
        }
        for failure in &outcome.scheduler.failures {
            execution_records.push(ExecutionRecord {
                execution_id: execution.execution_id.clone(),
                plan_index: failure.index,
                run_id: None,
                target_id: failure.target_id.clone(),
                backend_status: "runner_failure".to_owned(),
                candidate_count: 0,
                candidate_status: CandidateStatus::NotApplicable,
            });
        }
        for skipped in &outcome.scheduler.skipped {
            execution_records.push(ExecutionRecord {
                execution_id: execution.execution_id.clone(),
                plan_index: skipped.index,
                run_id: None,
                target_id: skipped.target_id.clone(),
                backend_status: "not_started".to_owned(),
                candidate_count: 0,
                candidate_status: CandidateStatus::NotApplicable,
            });
        }

        for (candidate_index, artifact) in outcome.counterexample_candidates.iter().enumerate() {
            outcome_candidate_count += 1;
            let record_id = format!("{}/{candidate_index:04}", execution.execution_id);
            let candidate_path = resolve_path(
                outcome_path.parent().context("outcome has no parent")?,
                &artifact.preserved_path,
            );
            let candidate_identity =
                fs::canonicalize(&candidate_path).unwrap_or_else(|_| candidate_path.clone());
            ensure!(
                candidate_paths.insert(candidate_identity),
                "candidate path is repeated in the request"
            );
            let candidate_bytes = fs::read(&candidate_path).ok();
            let observed_hash = candidate_bytes.as_deref().map(sha256_bytes);
            if observed_hash.as_deref() != Some(artifact.sha256.as_str()) {
                candidate_error_count += 1;
                candidate_errors.push(CandidateError {
                    candidate_record_id: record_id,
                    execution_id: execution.execution_id.clone(),
                    target_id: artifact.target_id.clone(),
                    path: relative_path_allow_missing(report_dir, &candidate_path)?,
                    expected_sha256: artifact.sha256.clone(),
                    observed_sha256: observed_hash,
                    reason_code: "candidate-unavailable-or-hash-mismatch".to_owned(),
                });
                continue;
            }
            let matching = specs
                .values()
                .filter(|spec| spec.spec.target_binding.target_id == artifact.target_id)
                .cloned()
                .collect::<Vec<_>>();
            if matching.is_empty() {
                unmatched_candidate_count += 1;
                unreviewed.push(UnreviewedCandidate {
                    candidate_record_id: record_id,
                    candidate: file_ref_from(report_dir, &candidate_path)?,
                    execution_id: execution.execution_id.clone(),
                    run_id: artifact.run_id.clone(),
                    target_id: artifact.target_id.clone(),
                    reason_code: "no-matching-spec".to_owned(),
                });
                continue;
            }
            matched_candidate_count += 1;
            let plan_target = plan
                .targets
                .iter()
                .find(|target| target.target_id == artifact.target_id)
                .context("candidate target is absent from plan")?;
            let run = run_map
                .get(artifact.run_id.as_str())
                .context("candidate references an unknown run")?;
            for spec in matching {
                let review = review_backend_candidate(
                    &record_id,
                    execution,
                    &candidate_path,
                    candidate_bytes
                        .as_deref()
                        .context("verified candidate bytes are unavailable")?,
                    artifact,
                    run.index,
                    plan_target,
                    &spec,
                    qualifications.get(
                        spec.spec
                            .injection_ground_truth
                            .as_ref()
                            .map(|ground_truth| ground_truth.injection_id.as_str())
                            .unwrap_or(""),
                    ),
                    project_scope_verifications.get(&spec.spec.review_spec_id),
                    report_dir,
                    python_bin,
                );
                reviews.push(ReviewRecord::Backend(Box::new(review)));
            }
        }

        contexts.push(BackendExecutionContext {
            request: execution.clone(),
            plan_path,
            outcome_path,
        });
    }

    ensure!(
        bound_spec_ids.len() == specs.len()
            && specs.keys().all(|spec_id| bound_spec_ids.contains(spec_id)),
        "every backend review spec must bind a target in at least one supplied plan"
    );

    execution_records.sort_by(|left, right| {
        (
            left.execution_id.as_str(),
            left.plan_index,
            left.target_id.as_str(),
            left.run_id.as_deref().unwrap_or(""),
        )
            .cmp(&(
                right.execution_id.as_str(),
                right.plan_index,
                right.target_id.as_str(),
                right.run_id.as_deref().unwrap_or(""),
            ))
    });
    candidate_errors
        .sort_by(|left, right| left.candidate_record_id.cmp(&right.candidate_record_id));
    unreviewed.sort_by(|left, right| left.candidate_record_id.cmp(&right.candidate_record_id));
    reviews.sort_by(review_sort_key);

    let review_pair_count = reviews.len();
    let terminal_review_pair_count = reviews.len();
    ensure!(
        outcome_candidate_count
            == matched_candidate_count + unmatched_candidate_count + candidate_error_count,
        "candidate inventory accounting mismatch"
    );
    let review_error_count = reviews
        .iter()
        .filter(|review| matches!(review, ReviewRecord::Backend(row) if row.disposition == Disposition::ReviewError))
        .count();
    let inventory_complete = unmatched_candidate_count == 0
        && candidate_error_count == 0
        && review_pair_count == terminal_review_pair_count;
    let status =
        if candidate_error_count > 0 || unmatched_candidate_count > 0 || review_error_count > 0 {
            ReportStatus::Incomplete
        } else {
            ReportStatus::Complete
        };
    let summary = backend_summary(&reviews, unmatched_candidate_count);
    let report = ReviewReport {
        schema_version: 1,
        report_id: request.request_id.clone(),
        kind: ReportKind::BackendCandidates,
        status,
        review_request: request_ref.clone(),
        review_specs: report_spec_refs,
        engine: engine.clone(),
        adapters: vec![AdapterProvenance {
            id: ZKFUZZ_CANDIDATE_ADAPTER_ID.to_owned(),
            implementation_sha256: implementation_hash(ZKFUZZ_CANDIDATE_ADAPTER_DESCRIPTION),
        }],
        failure: None,
        candidate_inventory: Some(CandidateInventory {
            outcome_candidate_count,
            matched_candidate_count,
            unmatched_candidate_count,
            candidate_error_count,
            review_pair_count,
            terminal_review_pair_count,
            complete: inventory_complete,
        }),
        executions: execution_records,
        candidate_errors,
        unreviewed_candidates: unreviewed,
        reviews,
        summary: ReviewSummary::Backend(summary),
        semantic_result_sha256: String::new(),
        raw_values_persisted: false,
    };
    Ok((
        report,
        Some(BackendOutputContext {
            executions: contexts,
            specs,
        }),
        None,
    ))
}

#[allow(clippy::too_many_arguments)]
fn review_backend_candidate(
    record_id: &str,
    execution: &BackendExecutionRequest,
    candidate_path: &Path,
    candidate_bytes: &[u8],
    artifact: &experiment::CounterexampleArtifact,
    plan_index: usize,
    plan_target: &experiment::PlanTarget,
    spec: &LoadedSpec,
    qualification: Option<&VerifiedQualification>,
    project_scope_verification: Option<&Criterion>,
    report_dir: &Path,
    python_bin: &Path,
) -> BackendReview {
    let timer = Instant::now();
    let candidate_ref = FileRef {
        path: relative_path(report_dir, candidate_path)
            .unwrap_or_else(|_| candidate_path.to_path_buf()),
        sha256: artifact.sha256.clone(),
    };
    let mut review = BackendReview {
        candidate_record_id: record_id.to_owned(),
        candidate: candidate_ref.clone(),
        binding: CandidateBinding {
            execution_id: execution.execution_id.clone(),
            plan_index,
            run_id: artifact.run_id.clone(),
            target_id: artifact.target_id.clone(),
            candidate_hash_verified: true,
            candidate_metadata_verified: false,
        },
        review_spec: SpecRef {
            id: spec.spec.review_spec_id.clone(),
            path: spec.report_ref.path.clone(),
            sha256: spec.sha256.clone(),
        },
        root_cause_id: spec.spec.root_cause_id.clone(),
        expected_scope: spec.spec.expected_scope,
        artifact_verification: BackendArtifactVerification {
            r1cs_sha256_verified: true,
            sym_sha256_verified: true,
            assignment_complete: false,
        },
        failed_target_constraint_count: 0,
        failed_target_constraint_indices: Vec::new(),
        criteria: empty_common_criteria(),
        disposition: Disposition::ReviewError,
        cause_attribution: CauseAttribution {
            verdict: AttributionVerdict::Unknown,
            reason_code: "review-not-complete".to_owned(),
            evidence: Vec::new(),
        },
        ground_truth_qualification: None,
        violation_class: None,
        confirmation_eligible: false,
        automated_review_seconds: 0.0,
        predicate_stream_nonempty: false,
    };

    let result = (|| -> Result<()> {
        let raw: RawCounterexample =
            serde_json::from_slice(candidate_bytes).context("parse strict zkFuzz candidate")?;
        validate_candidate_metadata(&raw, plan_target, &spec.spec)?;
        review.binding.candidate_metadata_verified = true;
        let normalized = normalize_zkfuzz_assignment(&raw, plan_target, spec)?;
        review.artifact_verification.assignment_complete = true;

        let candidate_evidence = vec![candidate_ref.clone()];
        review.criteria.assignment_encoding = Some(Criterion {
            verdict: if normalized.canonical {
                CriterionVerdict::Satisfied
            } else {
                CriterionVerdict::NotSatisfied
            },
            reason_code: if normalized.canonical {
                "canonical".to_owned()
            } else {
                "noncanonical-field-element".to_owned()
            },
            evidence: candidate_evidence.clone(),
            note: if normalized.canonical {
                "All field-valued assignment entries are canonical.".to_owned()
            } else {
                "At least one field-valued assignment entry is noncanonical.".to_owned()
            },
        });

        if normalized.canonical {
            let failed = spec.r1cs.failed_constraint_indices(&normalized.wires)?;
            review.failed_target_constraint_count = failed.len();
            review.failed_target_constraint_indices = failed.clone();
            review.criteria.fixed_target_constraints = Some(Criterion {
                verdict: if failed.is_empty() {
                    CriterionVerdict::Satisfied
                } else {
                    CriterionVerdict::NotSatisfied
                },
                reason_code: if failed.is_empty() {
                    "all-constraints-satisfied".to_owned()
                } else {
                    "target-constraint-failed".to_owned()
                },
                evidence: vec![
                    candidate_ref.clone(),
                    file_ref_from(report_dir, &spec.r1cs_path)?,
                ],
                note: if failed.is_empty() {
                    "All constraints in the fixed target R1CS are satisfied.".to_owned()
                } else {
                    "One or more constraints in the fixed target R1CS are not satisfied.".to_owned()
                },
            });
        } else {
            review.criteria.fixed_target_constraints = Some(Criterion {
                verdict: CriterionVerdict::Unknown,
                reason_code: "noncanonical-assignment".to_owned(),
                evidence: vec![candidate_ref.clone()],
                note: "Target constraints are not interpreted for a noncanonical assignment."
                    .to_owned(),
            });
        }

        let context = PredicateContext {
            schema_version: 1,
            field_modulus_decimal: spec.spec.field.modulus_decimal.clone(),
            wire_signals: normalized.wire_signals,
            eliminated_signals: normalized.eliminated_signals,
            parameters: normalized.parameters,
            predicate_config: spec.spec.contract.predicate.config.clone(),
            request_kind: ReportKind::BackendCandidates,
            injection_id: spec
                .spec
                .injection_ground_truth
                .as_ref()
                .map(|ground_truth| ground_truth.injection_id.clone()),
            clean_reference_signals: None,
        };
        match run_predicate(
            python_bin,
            &spec.predicate_path,
            &spec.spec.contract.predicate,
            &context,
        ) {
            Ok(output) => {
                let contract_ref = file_ref_from(report_dir, &spec.contract_path)?;
                review.criteria.input_preconditions = Some(predicate_criterion(
                    &spec.spec.contract.predicate,
                    PredicateCriterion::InputPreconditions,
                    &output.input_preconditions,
                    vec![candidate_ref.clone(), contract_ref.clone()],
                )?);
                review.criteria.specified_property_violation = Some(predicate_criterion(
                    &spec.spec.contract.predicate,
                    PredicateCriterion::SpecifiedPropertyViolation,
                    &output.specified_property_violation,
                    vec![candidate_ref.clone(), contract_ref],
                )?);
                review.violation_class = output.specified_property_violation.violation_class;
            }
            Err(error) => {
                review.predicate_stream_nonempty = error.stream_nonempty;
                bail!("predicate worker failed");
            }
        }

        ensure!(
            (spec.spec.expected_scope == experiment::ConfirmationScope::Project)
                == project_scope_verification.is_some(),
            "project scope verification was not completed as a shared input"
        );
        review.cause_attribution = backend_attribution(spec, qualification, report_dir)?;
        if let Some(scope) = project_scope_verification {
            review
                .cause_attribution
                .evidence
                .extend(scope.evidence.iter().cloned());
            review.cause_attribution.evidence.sort_by(|left, right| {
                (&left.sha256, &left.path).cmp(&(&right.sha256, &right.path))
            });
            review
                .cause_attribution
                .evidence
                .dedup_by(|left, right| left.sha256 == right.sha256 && left.path == right.path);
        }
        review.disposition = disposition(&review.criteria);
        review.confirmation_eligible = review.disposition == Disposition::Validated
            && review.cause_attribution.verdict == AttributionVerdict::Matched
            && project_scope_verification
                .is_none_or(|criterion| criterion.verdict == CriterionVerdict::Satisfied);
        Ok(())
    })();

    if result.is_err() {
        review.disposition = Disposition::ReviewError;
        review.confirmation_eligible = false;
        if review.cause_attribution.verdict == AttributionVerdict::Unknown {
            review.cause_attribution.reason_code = "review-error".to_owned();
        }
    }
    review.automated_review_seconds = timer.elapsed().as_secs_f64();
    review
}

fn validate_candidate_metadata(
    candidate: &RawCounterexample,
    plan_target: &experiment::PlanTarget,
    spec: &ReviewSpec,
) -> Result<()> {
    ensure!(
        candidate.target_path == plan_target.run_entrypoint.to_string_lossy(),
        "candidate target path differs from the frozen plan entrypoint"
    );
    ensure!(
        candidate.main_template == plan_target.definition.template_name
            && candidate.main_template == spec.target_binding.template,
        "candidate template differs from its plan/spec binding"
    );
    ensure!(
        spec.target_binding.target_id == plan_target.target_id,
        "spec target differs from plan target"
    );
    ensure!(
        spec.target_binding.concrete_parameters.len()
            == plan_target.definition.concrete_parameters.len(),
        "spec parameter count differs from plan"
    );
    for (expected_position, parameter) in spec.target_binding.concrete_parameters.iter().enumerate()
    {
        ensure!(
            parameter.position == expected_position
                && parameter.value_decimal
                    == plan_target.definition.concrete_parameters[expected_position],
            "spec concrete parameter differs from plan"
        );
    }
    ensure!(
        !candidate.search_mode.trim().is_empty(),
        "empty search mode"
    );
    ensure!(
        !candidate.execution_time.trim().is_empty(),
        "empty candidate execution time"
    );
    ensure!(
        candidate.zkfuzz_revision.len() == 40
            && candidate
                .zkfuzz_revision
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit()),
        "invalid zkFuzz revision metadata"
    );
    validate_flag_shape(&candidate.flag)?;
    validate_auxiliary_shape(&candidate.auxiliary_result)?;
    if let Some(output) = &candidate.target_output {
        ensure!(!output.is_empty(), "empty target output metadata");
    }
    Ok(())
}

fn prepared_compile_bindings(
    plan: &ExperimentPlan,
) -> Result<BTreeMap<String, PreparedCompileBinding>> {
    let prepared_path = fs::canonicalize(&plan.prepared_path).with_context(|| {
        format!(
            "resolve frozen prepared corpus {}",
            plan.prepared_path.display()
        )
    })?;
    let prepared_bytes = fs::read(&prepared_path)?;
    ensure!(
        sha256_bytes(&prepared_bytes) == plan.prepared_sha256,
        "prepared corpus changed while binding review artifacts"
    );
    let prepared: crate::corpus::PreparedCorpus = serde_json::from_slice(&prepared_bytes)
        .context("parse frozen prepared corpus for review binding")?;
    let prepared_by_id = prepared
        .targets
        .iter()
        .map(|target| (target.target_id.as_str(), target))
        .collect::<BTreeMap<_, _>>();
    let prepared_parent = prepared_path
        .parent()
        .context("prepared corpus has no parent")?;
    let recorded_compiler_path = prepared
        .environment
        .get("circom_binary")
        .context("prepared corpus does not record its circom binary")?;
    let recorded_compiler_sha256 = prepared
        .environment
        .get("circom_binary_sha256")
        .context("prepared corpus does not record its circom binary hash")?;
    validate_hex(recorded_compiler_sha256)?;
    let recorded_compiler = fs::canonicalize(resolve_path(
        prepared_parent,
        Path::new(recorded_compiler_path),
    ))
    .context("resolve the compiler recorded by the prepared corpus")?;
    ensure!(
        sha256_file(&recorded_compiler)? == *recorded_compiler_sha256,
        "prepared corpus compiler binary changed after preparation"
    );

    let mut bindings = BTreeMap::new();
    for plan_target in &plan.targets {
        let prepared_target = prepared_by_id
            .get(plan_target.target_id.as_str())
            .context("plan target is absent from its prepared corpus")?;
        ensure!(
            prepared_target.eligible
                && prepared_target.definition.compile_args == plan_target.definition.compile_args,
            "plan target compile arguments differ from its prepared target"
        );
        let structure = prepared_target
            .structure
            .as_ref()
            .context("prepared target has no structural compile result")?;
        ensure!(
            structure.compile_success
                && structure.compile.success
                && !structure.compile.timed_out
                && structure.compile_args == plan_target.definition.compile_args,
            "prepared target has no successful matching compiler result"
        );
        let r1cs_path = structure
            .r1cs_path
            .as_ref()
            .context("prepared target has no R1CS artifact")?;
        let r1cs_path = fs::canonicalize(resolve_path(prepared_parent, r1cs_path))
            .context("resolve prepared target R1CS artifact")?;
        let observed_r1cs_sha256 = sha256_file(&r1cs_path)?;
        if let Some(recorded) = &structure.r1cs_sha256 {
            validate_hex(recorded)?;
            ensure!(
                recorded == &observed_r1cs_sha256,
                "prepared target R1CS changed after preparation"
            );
        }
        let compiler_path =
            fs::canonicalize(resolve_path(prepared_parent, &structure.compile.binary))
                .context("resolve prepared target compiler binary")?;
        ensure!(
            compiler_path == recorded_compiler,
            "prepared target compiler differs from the prepared environment"
        );
        let compiler_binary_sha256 = sha256_file(&compiler_path)?;
        ensure!(
            compiler_binary_sha256 == *recorded_compiler_sha256,
            "prepared target compiler hash differs from the prepared environment"
        );
        ensure!(
            bindings
                .insert(
                    plan_target.target_id.clone(),
                    PreparedCompileBinding {
                        r1cs_sha256: observed_r1cs_sha256,
                        recorded_r1cs_sha256: structure.r1cs_sha256.clone(),
                        compiler_binary_sha256,
                        compiler_arguments: plan_target.definition.compile_args.clone(),
                    },
                )
                .is_none(),
            "duplicate prepared target compile binding"
        );
    }
    Ok(bindings)
}

fn validate_spec_plan_source_binding(
    spec: &LoadedSpec,
    plan_target: &experiment::PlanTarget,
    compile_binding: &PreparedCompileBinding,
) -> Result<()> {
    let fingerprint_map = |fingerprints: &[crate::corpus::SourceFingerprint]| {
        fingerprints
            .iter()
            .map(|fingerprint| {
                Ok((
                    fs::canonicalize(&fingerprint.path)?,
                    fingerprint.sha256.clone(),
                ))
            })
            .collect::<Result<BTreeMap<_, _>>>()
    };
    let source_fingerprints = fingerprint_map(&plan_target.source_fingerprints)?;
    let snapshot_fingerprints = fingerprint_map(&plan_target.snapshot_fingerprints)?;
    let inspected_root = plan_target
        .inspection
        .root
        .as_ref()
        .context("plan target has no inspected root instance")?;
    let inspected_root_path = fs::canonicalize(&inspected_root.path)?;
    let spec_parameters = spec
        .spec
        .target_binding
        .concrete_parameters
        .iter()
        .map(|parameter| parameter.value_decimal.as_str())
        .collect::<Vec<_>>();
    ensure!(
        spec.spec.target_binding.template == inspected_root.template_name
            && spec_parameters.iter().copied().eq(inspected_root
                .concrete_parameters
                .iter()
                .map(String::as_str)),
        "review spec template instance differs from the inspected plan root"
    );
    // An injected spec's closure also holds the entrypoint files that production reachability
    // needs; only the part its direct wrapper compiles corresponds to the prepared target.
    let spec_target_closure = if spec.spec.subject_kind == SubjectKind::InjectedMutant {
        injected_wrapper_closure(spec, &plan_target.inspection.project_root)?
    } else {
        spec.source_closure.clone()
    };
    let (expected_root_path, selected_fingerprints) = if spec_target_closure == source_fingerprints
    {
        (inspected_root_path, &source_fingerprints)
    } else if spec.spec.subject_kind != SubjectKind::InjectedMutant
        && spec_target_closure == snapshot_fingerprints
    {
        let mut original_base = plan_target.inspection.project_root.as_path();
        let entrypoint_parent = plan_target
            .inspection
            .entrypoint
            .parent()
            .context("plan entrypoint has no parent")?;
        while !entrypoint_parent.starts_with(original_base) {
            original_base = original_base
                .parent()
                .context("plan entrypoint and project root have no common ancestor")?;
        }
        let relative_entrypoint = plan_target
            .inspection
            .entrypoint
            .strip_prefix(original_base)?;
        let mut snapshot_base = fs::canonicalize(&plan_target.run_entrypoint)?;
        for _ in relative_entrypoint.components() {
            ensure!(
                snapshot_base.pop(),
                "snapshot layout is shorter than the original source layout"
            );
        }
        ensure!(
            snapshot_base.join(relative_entrypoint)
                == fs::canonicalize(&plan_target.run_entrypoint)?,
            "snapshot entrypoint layout differs from the inspected source"
        );
        let logical_root = inspected_root.path.strip_prefix(original_base)?;
        (
            fs::canonicalize(snapshot_base.join(logical_root))?,
            &snapshot_fingerprints,
        )
    } else {
        bail!("review spec source closure differs from the frozen plan target")
    };
    ensure!(
        spec.source_path == expected_root_path
            && selected_fingerprints
                .get(&expected_root_path)
                .is_some_and(|sha256| sha256 == &spec.spec.target_binding.source_sha256),
        "review spec target source differs from the inspected plan root source"
    );
    ensure!(
        spec.spec.compiled_subject.r1cs_sha256 == compile_binding.r1cs_sha256
            && spec.spec.compiler.binary_sha256 == compile_binding.compiler_binary_sha256
            && spec.spec.compiler.arguments == compile_binding.compiler_arguments,
        "review spec compiled subject or compiler differs from the frozen prepared target"
    );
    if spec.spec.subject_kind == SubjectKind::InjectedMutant {
        ensure!(
            compile_binding.recorded_r1cs_sha256.as_deref()
                == Some(spec.spec.compiled_subject.r1cs_sha256.as_str()),
            "injected review requires an R1CS hash frozen inside the prepared corpus"
        );
    }
    Ok(())
}

/// Files that an injected spec's direct wrapper compiles: the dependency closure of the mutant
/// compilation entrypoint, inspected with the spec's semantic library paths, each carrying the
/// hash that the pinned source closure records for it.
fn injected_wrapper_closure(
    spec: &LoadedSpec,
    project_root: &Path,
) -> Result<BTreeMap<PathBuf, String>> {
    let injection = spec
        .spec
        .injection_ground_truth
        .as_ref()
        .context("injected review spec has no injection ground truth")?;
    let spec_parent = spec.path.parent().context("review spec has no parent")?;
    let manifest_path = verify_file_ref_from_parent(spec_parent, &injection.compilation_manifest)?;
    let manifest: CompilationReproductionManifest =
        serde_json::from_slice(&fs::read(&manifest_path)?)
            .context("parse strict compilation reproduction manifest schema 1")?;
    let manifest_parent = manifest_path
        .parent()
        .context("compilation reproduction manifest has no parent")?;
    let closure_path = verify_declared_file(
        manifest_parent,
        &manifest.variants.mutant.source_closure_manifest_path,
        &manifest.variants.mutant.source_closure_manifest_sha256,
    )?;
    ensure!(
        manifest.variants.mutant.source_closure_manifest_sha256
            == spec.spec.target_binding.source_closure_manifest_sha256,
        "mutant compilation closure is not the target-binding source closure"
    );
    let entries = verify_directory_manifest_entries(&closure_path)?;
    let wrapper = &entries
        .get(&manifest.variants.mutant.entrypoint_path)
        .context("mutant source closure omits the compiled wrapper")?
        .canonical_path;
    let mut libraries = Vec::new();
    let mut arguments = spec.spec.compiler.arguments.iter().peekable();
    while let Some(argument) = arguments.next() {
        if argument == "-l" {
            while let Some(path) = arguments.next_if(|path| !path.starts_with('-')) {
                libraries.push(PathBuf::from(path));
            }
        }
    }
    let inspection = targets::inspect_entrypoint_with_libraries(wrapper, project_root, &libraries)?;
    ensure!(
        inspection.complete,
        "injected wrapper closure cannot be inspected completely"
    );
    inspection
        .dependency_paths
        .iter()
        .map(|path| {
            let sha256 = spec
                .source_closure
                .get(path)
                .context("injected wrapper dependency is outside the pinned source closure")?;
            Ok((path.clone(), sha256.clone()))
        })
        .collect()
}

fn validate_flag_shape(value: &Value) -> Result<()> {
    let object = value
        .as_object()
        .context("candidate flag is not an object")?;
    ensure!(object.len() == 2, "candidate flag has unexpected fields");
    ensure!(
        object.get("1_type").is_some_and(Value::is_string),
        "candidate flag has no string type"
    );
    let detail = if let Some(value) = object.get("2_expected_output") {
        value
    } else {
        object
            .get("2_violated_condition")
            .context("candidate flag has an unsupported detail field")?
    };
    ensure!(detail.is_object(), "candidate flag detail is not an object");
    Ok(())
}

fn validate_auxiliary_shape(value: &Value) -> Result<()> {
    let object = value
        .as_object()
        .context("candidate auxiliary_result is not an object")?;
    ensure!(
        object.len() == 2
            && object.contains_key("mutation_test_config")
            && object.contains_key("mutation_test_log"),
        "candidate auxiliary_result has unexpected fields"
    );
    Ok(())
}

fn normalize_zkfuzz_assignment(
    candidate: &RawCounterexample,
    plan_target: &experiment::PlanTarget,
    spec: &LoadedSpec,
) -> Result<NormalizedAssignment> {
    let mut raw = candidate.assignment.clone();
    let mut parameters = BTreeMap::new();
    for parameter in &spec.spec.target_binding.concrete_parameters {
        let qualified = format!("main.{}", parameter.name);
        if let Some(value) = raw
            .remove(&qualified)
            .or_else(|| raw.remove(&parameter.name))
        {
            ensure!(
                value == parameter.value_decimal,
                "candidate compile-time parameter differs from spec"
            );
        }
        ensure!(
            plan_target.definition.concrete_parameters[parameter.position]
                == parameter.value_decimal,
            "plan compile-time parameter differs from spec"
        );
        parameters.insert(
            parameter.name.clone(),
            TypedParameterValue {
                kind: parameter.kind,
                value_decimal: parameter.value_decimal.clone(),
            },
        );
    }

    let mut wires = vec![None; spec.r1cs.shape.wires];
    wires[0] = Some(BigUint::one());
    let mut eliminated = BTreeMap::new();
    let mut canonical = true;
    for (name, text) in raw {
        let symbol = spec
            .symbols
            .by_name
            .get(&name)
            .with_context(|| format!("unexpected assignment entry {name}"))?;
        let (value, canonical_text) = parse_assignment_field(&text)?;
        canonical &= canonical_text && value < spec.r1cs.prime;
        if symbol.wire >= 0 {
            let wire = usize::try_from(symbol.wire)?;
            if let Some(existing) = &wires[wire] {
                ensure!(existing == &value, "positive-wire aliases disagree");
            } else {
                wires[wire] = Some(value);
            }
        } else {
            eliminated.insert(name, value.to_str_radix(10));
        }
    }
    let wires = wires
        .into_iter()
        .enumerate()
        .map(|(wire, value)| value.with_context(|| format!("assignment misses wire {wire}")))
        .collect::<Result<Vec<_>>>()?;
    let wire_signals = spec
        .symbols
        .by_name
        .iter()
        .filter_map(|(name, symbol)| {
            usize::try_from(symbol.wire)
                .ok()
                .map(|wire| (name.clone(), wires[wire].to_str_radix(10)))
        })
        .collect();
    Ok(NormalizedAssignment {
        wires,
        wire_signals,
        eliminated_signals: eliminated,
        parameters,
        canonical,
    })
}

fn predicate_criterion(
    spec: &PredicateSpec,
    criterion: PredicateCriterion,
    result: &PredicateResult,
    evidence: Vec<FileRef>,
) -> Result<Criterion> {
    let allowed = spec
        .allowed_results
        .iter()
        .find(|entry| {
            entry.criterion == criterion
                && entry.verdict == result.verdict
                && entry.reason_code == result.reason_code
        })
        .context("predicate result is outside its reason catalog")?;
    Ok(Criterion {
        verdict: result.verdict,
        reason_code: result.reason_code.clone(),
        evidence,
        note: allowed.note.clone(),
    })
}

fn backend_attribution(
    spec: &LoadedSpec,
    qualification: Option<&VerifiedQualification>,
    report_dir: &Path,
) -> Result<CauseAttribution> {
    let mut evidence = vec![file_ref_from(report_dir, &spec.attribution_path)?];
    match spec.spec.attribution.method {
        AttributionMethod::KnownDefectSingleTarget => Ok(CauseAttribution {
            verdict: AttributionVerdict::Matched,
            reason_code: "known-defect-binding-matched".to_owned(),
            evidence,
        }),
        AttributionMethod::InjectionSingleDiff => {
            let qualification = qualification.context("missing qualification bundle")?;
            evidence.push(file_ref_from(report_dir, &qualification.index_path)?);
            ensure!(
                qualification.index_sha256 == sha256_file(&qualification.index_path)?,
                "qualification bundle changed"
            );
            Ok(CauseAttribution {
                verdict: AttributionVerdict::Matched,
                reason_code: "injection-binding-and-qualification-matched".to_owned(),
                evidence,
            })
        }
        AttributionMethod::Unattributed => Ok(CauseAttribution {
            verdict: AttributionVerdict::Unknown,
            reason_code: "unattributed-spec".to_owned(),
            evidence,
        }),
    }
}

fn disposition(criteria: &CommonCriteria) -> Disposition {
    let values = [
        criteria.assignment_encoding.as_ref(),
        criteria.input_preconditions.as_ref(),
        criteria.fixed_target_constraints.as_ref(),
        criteria.specified_property_violation.as_ref(),
    ];
    if values.iter().any(|criterion| criterion.is_none()) {
        Disposition::ReviewError
    } else if values
        .iter()
        .flatten()
        .any(|criterion| criterion.verdict == CriterionVerdict::NotSatisfied)
    {
        Disposition::Rejected
    } else if values
        .iter()
        .flatten()
        .any(|criterion| criterion.verdict == CriterionVerdict::Unknown)
    {
        Disposition::Unresolved
    } else {
        Disposition::Validated
    }
}

fn empty_common_criteria() -> CommonCriteria {
    CommonCriteria {
        assignment_encoding: None,
        input_preconditions: None,
        fixed_target_constraints: None,
        specified_property_violation: None,
    }
}

fn preflight_injection_request(
    request: &InjectionRequest,
    request_path: &Path,
    report_dir: &Path,
) -> Result<InjectionErrorContext> {
    ensure!(
        request.schema_version == 1,
        "unsupported injection request schema"
    );
    ensure!(
        request.disturbance_assignment.origin == AssignmentOrigin::DisturbanceTwin
            && request.clean_reference_assignment.origin == AssignmentOrigin::CleanWitnessGenerator,
        "assignment origins do not match the injection roles"
    );
    ensure!(
        request.disturbance_assignment.adapter_implementation_sha256
            == expected_assignment_adapter_hash(request.disturbance_assignment.format)
            && request
                .clean_reference_assignment
                .adapter_implementation_sha256
                == expected_assignment_adapter_hash(request.clean_reference_assignment.format),
        "assignment adapter implementation hash mismatch"
    );
    let spec_reference = FileRef {
        path: request.review_spec.path.clone(),
        sha256: request.review_spec.sha256.clone(),
    };
    let spec = load_spec(request_path, &spec_reference, report_dir)?;
    ensure!(
        spec.spec.subject_kind == SubjectKind::InjectedMutant,
        "injection request points to a non-injected review spec"
    );
    let injection = spec
        .spec
        .injection_ground_truth
        .as_ref()
        .context("injected review spec has no injection ground truth")?;
    verify_compilation_reproduction(&spec, injection)?;

    let generation_path = verify_file_ref(request_path, &request.generation_manifest)?;
    let generation: GenerationManifest = serde_json::from_slice(&fs::read(&generation_path)?)
        .context("parse strict generation manifest schema 1")?;
    ensure!(
        generation.schema_version == 1,
        "unsupported generation manifest"
    );
    let generation_parent = generation_path
        .parent()
        .context("generation manifest has no parent")?;
    verify_file_ref_from_parent(generation_parent, &generation.common_input)?;
    validate_generator_files(generation_parent, &generation.generators.clean)?;
    validate_generator_files(generation_parent, &generation.generators.disturbance_twin)?;
    let disturbance_path = verify_assignment_ref(request_path, &request.disturbance_assignment)?;
    let clean_reference_path =
        verify_assignment_ref(request_path, &request.clean_reference_assignment)?;
    ensure!(
        sha256_file(&disturbance_path)? == generation.generators.disturbance_twin.assignment_sha256
            && sha256_file(&clean_reference_path)? == generation.generators.clean.assignment_sha256,
        "request assignments differ from the generation manifest"
    );

    let spec_parent = spec.path.parent().context("review spec has no parent")?;
    let (clean_r1cs, clean_symbols, _, _) = load_variant(
        spec_parent,
        &injection.compiled_variants.clean,
        &spec.spec.field.modulus_decimal,
    )?;
    for signal in spec
        .spec
        .contract
        .input_signal_names
        .iter()
        .chain(spec.spec.contract.property_signal_names.iter())
    {
        ensure!(
            clean_symbols.by_name.contains_key(signal),
            "contract signal is absent from the clean SYM"
        );
    }
    load_variant(
        spec_parent,
        &injection.compiled_variants.disturbance_twin,
        &spec.spec.field.modulus_decimal,
    )?;
    let projection_path = verify_file_ref_from_parent(spec_parent, &injection.projection_manifest)?;
    let projection: ProjectionManifest = serde_json::from_slice(&fs::read(projection_path)?)
        .context("parse strict projection manifest schema 1")?;
    validate_projection_shape(
        &projection,
        &injection.operator_id,
        &clean_r1cs,
        &clean_symbols,
    )?;
    validate_relation_verifier_artifacts(&spec, injection)?;
    verify_production_reachability(&spec, report_dir)?;

    Ok(InjectionErrorContext {
        injection_id: injection.injection_id.clone(),
        disturbance: file_ref_from(report_dir, &disturbance_path)?,
        clean_reference: file_ref_from(report_dir, &clean_reference_path)?,
        spec,
    })
}

fn build_injection_review_error(
    request: &InjectionRequest,
    request_ref: &FileRef,
    engine: &EngineProvenance,
    context: InjectionErrorContext,
) -> BuildResult {
    let review = InjectionReview {
        candidate_record_id: None,
        candidate: None,
        binding: None,
        assignments: AssignmentLinks {
            disturbance: context.disturbance,
            clean_reference: context.clean_reference,
        },
        review_spec: SpecRef {
            id: context.spec.spec.review_spec_id.clone(),
            path: context.spec.report_ref.path.clone(),
            sha256: context.spec.sha256.clone(),
        },
        root_cause_id: context.spec.spec.root_cause_id.clone(),
        injection_id: context.injection_id.clone(),
        artifact_verification: InjectionArtifactVerification {
            mutant_r1cs: true,
            mutant_sym: true,
            clean_r1cs: true,
            clean_sym: true,
            twin_r1cs: true,
            twin_sym: true,
            generation_reproduced: false,
        },
        failed_target_constraint_count: 0,
        failed_target_constraint_indices: Vec::new(),
        failed_clean_constraint_count: 0,
        failed_clean_constraint_indices: Vec::new(),
        criteria: empty_common_criteria(),
        qualification_criteria: QualificationCriteria {
            twin_r1cs_identity: None,
            twin_sym_identity: None,
            generation_reproducibility: None,
            clean_reference_assignment_encoding: None,
            clean_reference_constraints: None,
            clean_input_equivalence: None,
            clean_rejection: None,
            clean_relation_exclusion: None,
            production_reachability: None,
        },
        disposition: Disposition::ReviewError,
        cause_attribution: CauseAttribution {
            verdict: AttributionVerdict::Unknown,
            reason_code: "review-error".to_owned(),
            evidence: Vec::new(),
        },
        ground_truth_qualification: GroundTruthQualification::ReviewError,
        violation_class: None,
        confirmation_eligible: false,
        automated_review_seconds: 0.0,
        predicate_stream_nonempty: false,
    };
    let report = ReviewReport {
        schema_version: 1,
        report_id: request.request_id.clone(),
        kind: ReportKind::InjectionGroundTruth,
        status: ReportStatus::Incomplete,
        review_request: request_ref.clone(),
        review_specs: vec![context.spec.report_ref.clone()],
        engine: engine.clone(),
        adapters: request_adapters(&ReviewRequest::Injection(request.clone())),
        failure: None,
        candidate_inventory: None,
        executions: Vec::new(),
        candidate_errors: Vec::new(),
        unreviewed_candidates: Vec::new(),
        reviews: vec![ReviewRecord::Injection(Box::new(review))],
        summary: ReviewSummary::Injection(InjectionSummary {
            validated: 0,
            rejected: 0,
            unresolved: 0,
            review_error: 1,
            qualified: 0,
        }),
        semantic_result_sha256: String::new(),
        raw_values_persisted: false,
    };
    (
        report,
        None,
        Some(InjectionOutputContext {
            spec: context.spec,
            injection_id: context.injection_id,
            qualification: GroundTruthQualification::ReviewError,
        }),
    )
}

fn build_injection_report(
    request: &InjectionRequest,
    request_path: &Path,
    request_ref: &FileRef,
    report_dir: &Path,
    engine: &EngineProvenance,
    python_bin: &Path,
) -> Result<BuildResult> {
    let context = preflight_injection_request(request, request_path, report_dir)?;
    match build_injection_report_inner(
        request,
        request_path,
        request_ref,
        report_dir,
        engine,
        python_bin,
    ) {
        Ok(result) => Ok(result),
        Err(_) => Ok(build_injection_review_error(
            request,
            request_ref,
            engine,
            context,
        )),
    }
}

fn build_injection_report_inner(
    request: &InjectionRequest,
    request_path: &Path,
    request_ref: &FileRef,
    report_dir: &Path,
    engine: &EngineProvenance,
    python_bin: &Path,
) -> Result<BuildResult> {
    ensure!(
        request.schema_version == 1,
        "unsupported injection request schema"
    );
    ensure!(
        request.disturbance_assignment.origin == AssignmentOrigin::DisturbanceTwin
            && request.clean_reference_assignment.origin == AssignmentOrigin::CleanWitnessGenerator,
        "assignment origins do not match the injection roles"
    );
    ensure!(
        request.disturbance_assignment.adapter_implementation_sha256
            == expected_assignment_adapter_hash(request.disturbance_assignment.format)
            && request
                .clean_reference_assignment
                .adapter_implementation_sha256
                == expected_assignment_adapter_hash(request.clean_reference_assignment.format),
        "assignment adapter implementation hash mismatch"
    );

    let spec_reference = FileRef {
        path: request.review_spec.path.clone(),
        sha256: request.review_spec.sha256.clone(),
    };
    let spec = load_spec(request_path, &spec_reference, report_dir)?;
    ensure!(
        spec.spec.subject_kind == SubjectKind::InjectedMutant,
        "injection request points to a non-injected review spec"
    );
    let injection = spec
        .spec
        .injection_ground_truth
        .as_ref()
        .context("injected review spec has no injection ground truth")?
        .clone();
    let generation_path = verify_file_ref(request_path, &request.generation_manifest)?;
    let generation: GenerationManifest = serde_json::from_slice(&fs::read(&generation_path)?)
        .context("parse strict generation manifest schema 1")?;
    ensure!(
        generation.schema_version == 1,
        "unsupported generation manifest"
    );
    let generation_parent = generation_path
        .parent()
        .context("generation manifest has no parent")?;
    let common_input = verify_file_ref_from_parent(generation_parent, &generation.common_input)?;
    validate_generator_files(generation_parent, &generation.generators.clean)?;
    validate_generator_files(generation_parent, &generation.generators.disturbance_twin)?;

    let disturbance_path = verify_assignment_ref(request_path, &request.disturbance_assignment)?;
    let clean_reference_path =
        verify_assignment_ref(request_path, &request.clean_reference_assignment)?;
    ensure!(
        sha256_file(&disturbance_path)? == generation.generators.disturbance_twin.assignment_sha256
            && sha256_file(&clean_reference_path)? == generation.generators.clean.assignment_sha256,
        "request assignments differ from the generation manifest"
    );

    let spec_parent = spec.path.parent().context("review spec has no parent")?;
    let (clean_r1cs, clean_symbols, clean_r1cs_path, clean_sym_path) = load_variant(
        spec_parent,
        &injection.compiled_variants.clean,
        &spec.spec.field.modulus_decimal,
    )?;
    let (_twin_r1cs, _twin_symbols, twin_r1cs_path, twin_sym_path) = load_variant(
        spec_parent,
        &injection.compiled_variants.disturbance_twin,
        &spec.spec.field.modulus_decimal,
    )?;
    let disturbance = normalize_assignment_file(
        &disturbance_path,
        request.disturbance_assignment.format,
        &spec.r1cs,
        &spec.symbols,
        &spec.spec.target_binding.concrete_parameters,
    )?;
    let clean_reference = normalize_assignment_file(
        &clean_reference_path,
        request.clean_reference_assignment.format,
        &clean_r1cs,
        &clean_symbols,
        &spec.spec.target_binding.concrete_parameters,
    )?;

    let timer = Instant::now();
    let disturbance_ref = file_ref_from(report_dir, &disturbance_path)?;
    let clean_reference_ref = file_ref_from(report_dir, &clean_reference_path)?;
    let clean_reference_failed = if clean_reference.canonical {
        Some(clean_r1cs.failed_constraint_indices(&clean_reference.wires)?)
    } else {
        None
    };
    let clean_inputs_equal = input_signals_equal(
        &spec.spec.contract.input_signal_names,
        &disturbance,
        &clean_reference,
    )?;
    let semantic_gate_failure = if !disturbance.canonical {
        Some((
            "noncanonical-disturbance-assignment",
            "Dependent semantic checks are not interpreted for a noncanonical disturbance assignment.",
        ))
    } else if !clean_reference.canonical {
        Some((
            "noncanonical-clean-reference",
            "Dependent semantic checks are not interpreted for a noncanonical clean reference.",
        ))
    } else if clean_reference_failed
        .as_ref()
        .is_some_and(|indices| !indices.is_empty())
    {
        Some((
            "clean-reference-constraint-failed",
            "Dependent semantic checks require a clean reference that satisfies every clean constraint.",
        ))
    } else if !clean_inputs_equal {
        Some((
            "clean-inputs-differ",
            "Dependent semantic checks require identical contract inputs in the disturbance and clean reference assignments.",
        ))
    } else {
        None
    };
    let mut common = empty_common_criteria();
    common.assignment_encoding = Some(boolean_criterion(
        disturbance.canonical,
        "canonical",
        "noncanonical-field-element",
        "All field-valued disturbance assignment entries are canonical.",
        "At least one disturbance assignment field element is noncanonical.",
        vec![disturbance_ref.clone()],
    ));
    let mut failed_target = Vec::new();
    if disturbance.canonical {
        failed_target = spec.r1cs.failed_constraint_indices(&disturbance.wires)?;
        common.fixed_target_constraints = Some(boolean_criterion(
            failed_target.is_empty(),
            "all-constraints-satisfied",
            "target-constraint-failed",
            "All constraints in the fixed injected-mutant R1CS are satisfied.",
            "One or more fixed injected-mutant constraints are not satisfied.",
            vec![
                disturbance_ref.clone(),
                file_ref_from(report_dir, &spec.r1cs_path)?,
            ],
        ));
    } else {
        common.fixed_target_constraints = Some(unknown_criterion(
            "noncanonical-assignment",
            "Mutant constraints are not interpreted for a noncanonical assignment.",
            vec![disturbance_ref.clone()],
        ));
    }

    let mut predicate_stream_nonempty = false;
    let mut violation_class = None;
    if let Some((reason_code, note)) = semantic_gate_failure {
        let evidence = vec![disturbance_ref.clone(), clean_reference_ref.clone()];
        common.input_preconditions = Some(unknown_criterion(reason_code, note, evidence.clone()));
        common.specified_property_violation = Some(unknown_criterion(reason_code, note, evidence));
    } else {
        let predicate_context = PredicateContext {
            schema_version: 1,
            field_modulus_decimal: spec.spec.field.modulus_decimal.clone(),
            wire_signals: disturbance.wire_signals.clone(),
            eliminated_signals: disturbance.eliminated_signals.clone(),
            parameters: disturbance.parameters.clone(),
            predicate_config: spec.spec.contract.predicate.config.clone(),
            request_kind: ReportKind::InjectionGroundTruth,
            injection_id: Some(injection.injection_id.clone()),
            clean_reference_signals: Some(clean_reference.all_signals()?),
        };
        let predicate_result = run_predicate(
            python_bin,
            &spec.predicate_path,
            &spec.spec.contract.predicate,
            &predicate_context,
        );
        match predicate_result {
            Ok(output) => {
                let contract_ref = file_ref_from(report_dir, &spec.contract_path)?;
                common.input_preconditions = Some(predicate_criterion(
                    &spec.spec.contract.predicate,
                    PredicateCriterion::InputPreconditions,
                    &output.input_preconditions,
                    vec![disturbance_ref.clone(), contract_ref.clone()],
                )?);
                common.specified_property_violation = Some(predicate_criterion(
                    &spec.spec.contract.predicate,
                    PredicateCriterion::SpecifiedPropertyViolation,
                    &output.specified_property_violation,
                    vec![disturbance_ref.clone(), contract_ref],
                )?);
                violation_class = output.specified_property_violation.violation_class;
            }
            Err(error) => predicate_stream_nonempty = error.stream_nonempty,
        }
    }
    let common_disposition = disposition(&common);

    let twin_r1cs_identical = injection.compiled_variants.mutant.r1cs_sha256
        == injection.compiled_variants.disturbance_twin.r1cs_sha256;
    let twin_sym_identical = injection.compiled_variants.mutant.sym_sha256
        == injection.compiled_variants.disturbance_twin.sym_sha256;
    let generation_reproduced =
        reproduce_generation(&generation, generation_parent, &common_input)?;
    let projection_path = verify_file_ref_from_parent(spec_parent, &injection.projection_manifest)?;
    let projection: ProjectionManifest = serde_json::from_slice(&fs::read(&projection_path)?)
        .context("parse strict projection manifest schema 1")?;
    let projected = if semantic_gate_failure.is_none() {
        Some(project_disturbance_to_clean(
            &projection,
            &injection.operator_id,
            &clean_r1cs,
            &clean_symbols,
            &disturbance,
            &clean_reference,
        )?)
    } else {
        None
    };
    let failed_clean = projected
        .as_ref()
        .map(|assignment| clean_r1cs.failed_constraint_indices(assignment))
        .transpose()?
        .unwrap_or_default();
    let clean_rejection_intersection = failed_clean
        .iter()
        .any(|index| injection.expected_clean_constraint_indices.contains(index));

    let twin_r1cs_ref = file_ref_from(report_dir, &twin_r1cs_path)?;
    let twin_sym_ref = file_ref_from(report_dir, &twin_sym_path)?;
    let clean_r1cs_ref = file_ref_from(report_dir, &clean_r1cs_path)?;
    let clean_sym_ref = file_ref_from(report_dir, &clean_sym_path)?;
    let generation_ref = file_ref_from(report_dir, &generation_path)?;
    let projection_ref = file_ref_from(report_dir, &projection_path)?;
    let mut qualification_criteria = QualificationCriteria {
        twin_r1cs_identity: Some(boolean_criterion(
            twin_r1cs_identical,
            "twin-r1cs-identical",
            "twin-r1cs-differs",
            "The disturbance twin and mutant R1CS raw hashes are identical.",
            "The disturbance twin and mutant R1CS raw hashes differ.",
            vec![file_ref_from(report_dir, &spec.r1cs_path)?, twin_r1cs_ref],
        )),
        twin_sym_identity: Some(boolean_criterion(
            twin_sym_identical,
            "twin-sym-identical",
            "twin-sym-differs",
            "The disturbance twin and mutant SYM raw hashes are identical.",
            "The disturbance twin and mutant SYM raw hashes differ.",
            vec![file_ref_from(report_dir, &spec.sym_path)?, twin_sym_ref],
        )),
        generation_reproducibility: Some(boolean_criterion(
            generation_reproduced,
            "generation-reproduced",
            "generation-hash-mismatch",
            "Both pinned generators reproduced their witness and assignment hashes.",
            "At least one pinned generator did not reproduce its fixed hashes.",
            vec![generation_ref],
        )),
        clean_reference_assignment_encoding: Some(boolean_criterion(
            clean_reference.canonical,
            "canonical",
            "noncanonical-clean-reference",
            "The clean reference assignment is complete and canonical.",
            "The clean reference assignment contains a noncanonical field element.",
            vec![clean_reference_ref.clone()],
        )),
        clean_reference_constraints: Some(clean_reference_failed.as_ref().map_or_else(
            || {
                unknown_criterion(
                    "noncanonical-clean-reference",
                    "Clean constraints are not interpreted for a noncanonical clean reference.",
                    vec![
                        clean_reference_ref.clone(),
                        clean_r1cs_ref.clone(),
                        clean_sym_ref.clone(),
                    ],
                )
            },
            |failed| {
                boolean_criterion(
                    failed.is_empty(),
                    "clean-reference-satisfies-constraints",
                    "clean-reference-constraint-failed",
                    "The same-input clean reference satisfies every clean R1CS constraint.",
                    "The clean reference does not satisfy every clean R1CS constraint.",
                    vec![
                        clean_reference_ref.clone(),
                        clean_r1cs_ref.clone(),
                        clean_sym_ref.clone(),
                    ],
                )
            },
        )),
        clean_input_equivalence: Some(boolean_criterion(
            clean_inputs_equal,
            "clean-inputs-equal",
            "clean-inputs-differ",
            "The clean and disturbance assignments have identical contract inputs.",
            "The clean and disturbance assignments differ on a contract input.",
            vec![disturbance_ref.clone(), clean_reference_ref.clone()],
        )),
        clean_rejection: Some(if let Some((reason_code, note)) = semantic_gate_failure {
            unknown_criterion(
                reason_code,
                note,
                vec![
                    disturbance_ref.clone(),
                    clean_reference_ref.clone(),
                    clean_r1cs_ref.clone(),
                    projection_ref.clone(),
                ],
            )
        } else if failed_clean.is_empty() {
            boolean_criterion(
                false,
                "clean-projection-rejected",
                "clean-projection-accepted",
                "The projected disturbance is rejected by the clean R1CS.",
                "The projected disturbance is accepted by the clean R1CS.",
                vec![
                    disturbance_ref.clone(),
                    clean_r1cs_ref.clone(),
                    projection_ref.clone(),
                ],
            )
        } else if clean_rejection_intersection {
            boolean_criterion(
                true,
                "clean-projection-rejected",
                "clean-projection-accepted",
                "The projected disturbance fails a predeclared injection-related clean constraint.",
                "The projected disturbance is accepted by the clean R1CS.",
                vec![
                    disturbance_ref.clone(),
                    clean_r1cs_ref.clone(),
                    projection_ref.clone(),
                ],
            )
        } else {
            unknown_criterion(
                "clean-failure-outside-expected-set",
                "The clean projection fails, but not at a predeclared injection-related constraint.",
                vec![
                    disturbance_ref.clone(),
                    clean_r1cs_ref.clone(),
                    projection_ref.clone(),
                ],
            )
        }),
        clean_relation_exclusion: None,
        production_reachability: None,
    };
    qualification_criteria.clean_relation_exclusion = Some(
        if let Some((reason_code, note)) = semantic_gate_failure {
            unknown_criterion(
                reason_code,
                note,
                vec![
                    disturbance_ref.clone(),
                    clean_reference_ref.clone(),
                    clean_r1cs_ref.clone(),
                    projection_ref.clone(),
                ],
            )
        } else if clean_rejection_intersection {
            verify_relation_exclusion(
                &spec,
                &injection,
                &clean_r1cs,
                &clean_symbols,
                &projection,
                projected
                    .as_deref()
                    .context("clean projection is absent after its prerequisites passed")?,
                &failed_clean,
                &disturbance,
                report_dir,
            )?
        } else {
            unknown_criterion(
                "clean-rejection-not-established",
                "Clean relation exclusion is not interpreted because the projected disturbance was not rejected by a predeclared injection-related clean constraint.",
                vec![
                    disturbance_ref.clone(),
                    clean_r1cs_ref.clone(),
                    projection_ref.clone(),
                ],
            )
        },
    );
    qualification_criteria.production_reachability =
        Some(verify_production_reachability(&spec, report_dir)?);

    let mut attribution_evidence = vec![
        file_ref_from(report_dir, &spec.attribution_path)?,
        file_ref_from(
            report_dir,
            &verify_file_ref_from_parent(spec_parent, &injection.single_diff)?,
        )?,
    ];
    attribution_evidence
        .sort_by(|left, right| (&left.sha256, &left.path).cmp(&(&right.sha256, &right.path)));
    attribution_evidence
        .dedup_by(|left, right| left.sha256 == right.sha256 && left.path == right.path);
    let attribution = CauseAttribution {
        verdict: AttributionVerdict::Matched,
        reason_code: "injection-source-transition-matched".to_owned(),
        evidence: attribution_evidence,
    };
    let qualification = ground_truth_qualification(
        common_disposition,
        &qualification_criteria,
        attribution.verdict,
    );
    let review = InjectionReview {
        candidate_record_id: None,
        candidate: None,
        binding: None,
        assignments: AssignmentLinks {
            disturbance: disturbance_ref,
            clean_reference: clean_reference_ref,
        },
        review_spec: SpecRef {
            id: spec.spec.review_spec_id.clone(),
            path: spec.report_ref.path.clone(),
            sha256: spec.sha256.clone(),
        },
        root_cause_id: spec.spec.root_cause_id.clone(),
        injection_id: injection.injection_id.clone(),
        artifact_verification: InjectionArtifactVerification {
            mutant_r1cs: true,
            mutant_sym: true,
            clean_r1cs: true,
            clean_sym: true,
            twin_r1cs: true,
            twin_sym: true,
            generation_reproduced,
        },
        failed_target_constraint_count: failed_target.len(),
        failed_target_constraint_indices: failed_target,
        failed_clean_constraint_count: failed_clean.len(),
        failed_clean_constraint_indices: failed_clean,
        criteria: common,
        qualification_criteria,
        disposition: common_disposition,
        cause_attribution: attribution,
        ground_truth_qualification: qualification,
        violation_class,
        confirmation_eligible: false,
        automated_review_seconds: timer.elapsed().as_secs_f64(),
        predicate_stream_nonempty,
    };
    let report_status = if common_disposition == Disposition::ReviewError
        || qualification == GroundTruthQualification::ReviewError
    {
        ReportStatus::Incomplete
    } else {
        ReportStatus::Complete
    };
    let summary = InjectionSummary {
        validated: usize::from(common_disposition == Disposition::Validated),
        rejected: usize::from(common_disposition == Disposition::Rejected),
        unresolved: usize::from(common_disposition == Disposition::Unresolved),
        review_error: usize::from(common_disposition == Disposition::ReviewError),
        qualified: usize::from(qualification == GroundTruthQualification::Qualified),
    };
    let adapters = request_adapters(&ReviewRequest::Injection(request.clone()));
    let report = ReviewReport {
        schema_version: 1,
        report_id: request.request_id.clone(),
        kind: ReportKind::InjectionGroundTruth,
        status: report_status,
        review_request: request_ref.clone(),
        review_specs: vec![spec.report_ref.clone()],
        engine: engine.clone(),
        adapters,
        failure: None,
        candidate_inventory: None,
        executions: Vec::new(),
        candidate_errors: Vec::new(),
        unreviewed_candidates: Vec::new(),
        reviews: vec![ReviewRecord::Injection(Box::new(review))],
        summary: ReviewSummary::Injection(summary),
        semantic_result_sha256: String::new(),
        raw_values_persisted: false,
    };
    Ok((
        report,
        None,
        Some(InjectionOutputContext {
            spec,
            injection_id: injection.injection_id.clone(),
            qualification,
        }),
    ))
}

fn boolean_criterion(
    value: bool,
    satisfied_reason: &str,
    not_satisfied_reason: &str,
    satisfied_note: &str,
    not_satisfied_note: &str,
    evidence: Vec<FileRef>,
) -> Criterion {
    Criterion {
        verdict: if value {
            CriterionVerdict::Satisfied
        } else {
            CriterionVerdict::NotSatisfied
        },
        reason_code: if value {
            satisfied_reason.to_owned()
        } else {
            not_satisfied_reason.to_owned()
        },
        evidence,
        note: if value {
            satisfied_note.to_owned()
        } else {
            not_satisfied_note.to_owned()
        },
    }
}

fn unknown_criterion(reason_code: &str, note: &str, evidence: Vec<FileRef>) -> Criterion {
    Criterion {
        verdict: CriterionVerdict::Unknown,
        reason_code: reason_code.to_owned(),
        evidence,
        note: note.to_owned(),
    }
}

fn verify_assignment_ref(declaring_path: &Path, reference: &AssignmentRef) -> Result<PathBuf> {
    validate_hex(&reference.sha256)?;
    verify_declared_file(
        declaring_path.parent().context("request has no parent")?,
        &reference.path,
        &reference.sha256,
    )
}

fn validate_generator_files(parent: &Path, generator: &GeneratorSpec) -> Result<()> {
    let runner = verify_declared_file(parent, &generator.runner_path, &generator.runner_sha256)?;
    let artifact_manifest = verify_declared_file(
        parent,
        &generator.artifact_manifest_path,
        &generator.artifact_manifest_sha256,
    )?;
    let artifacts = verify_directory_manifest(&artifact_manifest)?;
    verify_declared_file(parent, &generator.witness_path, &generator.witness_sha256)?;
    verify_declared_file(
        parent,
        &generator.assignment_path,
        &generator.assignment_sha256,
    )?;
    validate_generator_arguments(&generator.arguments)?;
    validate_literal_path_arguments(
        parent,
        &generator.arguments,
        &runner,
        &artifacts,
        &BTreeSet::new(),
    )
}

fn validate_generator_arguments(arguments: &[String]) -> Result<()> {
    ensure!(
        arguments
            .iter()
            .any(|argument| argument.contains("{common_input}"))
            && arguments
                .iter()
                .any(|argument| argument.contains("{witness_output}"))
            && arguments
                .iter()
                .any(|argument| argument.contains("{assignment_output}")),
        "generator arguments must declare the common-input and both output placeholders"
    );
    Ok(())
}

fn validate_literal_path_arguments(
    parent: &Path,
    arguments: &[String],
    runner: &Path,
    artifacts: &BTreeMap<PathBuf, String>,
    allowed_directories: &BTreeSet<PathBuf>,
) -> Result<()> {
    let allowed = artifacts.keys().cloned().collect::<BTreeSet<_>>();
    for argument in arguments {
        for candidate in literal_path_candidates(argument) {
            let resolved = resolve_path(parent, Path::new(candidate));
            if !resolved.exists() {
                if candidate.contains('{') || candidate.contains('}') {
                    continue;
                }
                ensure!(
                    unresolved_path_is_under_allowed_root(parent, candidate, allowed_directories)?,
                    "literal path argument is unavailable or outside the closed scratch roots"
                );
                continue;
            }
            let canonical = fs::canonicalize(&resolved)?;
            if canonical.is_file() {
                ensure!(
                    canonical == runner || allowed.contains(&canonical),
                    "literal file argument is not pinned by the runner or artifact manifest"
                );
            } else if canonical.is_dir() {
                ensure!(
                    allowed_directories
                        .iter()
                        .any(|root| canonical == *root || canonical.starts_with(root)),
                    "literal directory argument is outside the closed scratch roots"
                );
            } else {
                bail!("literal path argument has an unsupported file type");
            }
        }
    }
    Ok(())
}

fn literal_path_candidates(argument: &str) -> impl Iterator<Item = &str> {
    let mut candidates = Vec::new();
    for fragment in argument.split([',', ';', ':']) {
        let candidate = fragment
            .split_once('=')
            .map_or(fragment, |(_, value)| value);
        let path_like = Path::new(candidate).is_absolute()
            || candidate.contains('/')
            || candidate.contains('\\')
            || candidate.starts_with('.');
        if path_like && !candidate.is_empty() {
            candidates.push(candidate);
        }
    }
    candidates.into_iter()
}

fn unresolved_path_is_under_allowed_root(
    parent: &Path,
    candidate: &str,
    allowed_directories: &BTreeSet<PathBuf>,
) -> Result<bool> {
    if candidate
        .chars()
        .any(|character| matches!(character, '\'' | '"' | '(' | ')' | '[' | ']' | '{' | '}'))
    {
        return Ok(false);
    }
    let resolved = resolve_path(parent, Path::new(candidate));
    let mut ancestor = resolved.as_path();
    while !ancestor.exists() {
        let Some(parent) = ancestor.parent() else {
            return Ok(false);
        };
        ancestor = parent;
    }
    let ancestor = fs::canonicalize(ancestor)?;
    Ok(allowed_directories
        .iter()
        .any(|root| ancestor == *root || ancestor.starts_with(root)))
}

fn load_variant(
    parent: &Path,
    variant: &CompiledVariant,
    modulus_decimal: &str,
) -> Result<(R1cs, SymbolTable, PathBuf, PathBuf)> {
    let r1cs_path = verify_declared_file(parent, &variant.r1cs_path, &variant.r1cs_sha256)?;
    let sym_path = verify_declared_file(parent, &variant.sym_path, &variant.sym_sha256)?;
    let r1cs = R1cs::parse(&fs::read(&r1cs_path)?)?;
    r1cs.validate_shape(&variant.shape)?;
    ensure!(
        r1cs.prime == parse_decimal_field(modulus_decimal)?,
        "compiled variant field differs from spec"
    );
    let symbols = SymbolTable::parse(&fs::read(&sym_path)?, &r1cs)?;
    Ok((r1cs, symbols, r1cs_path, sym_path))
}

fn verify_compilation_reproduction(
    spec: &LoadedSpec,
    injection: &InjectionGroundTruth,
) -> Result<()> {
    let spec_parent = spec.path.parent().context("review spec has no parent")?;
    let manifest_path = verify_file_ref_from_parent(spec_parent, &injection.compilation_manifest)?;
    let manifest: CompilationReproductionManifest =
        serde_json::from_slice(&fs::read(&manifest_path)?)
            .context("parse strict compilation reproduction manifest schema 1")?;
    ensure!(
        manifest.schema_version == 1,
        "unsupported compilation reproduction manifest"
    );
    ensure!(
        !manifest.compiler.version.trim().is_empty()
            && manifest.compiler.version == spec.spec.compiler.version
            && manifest.compiler.runner_sha256 == spec.spec.compiler.binary_sha256,
        "compilation reproduction compiler differs from the review spec"
    );
    validate_compilation_arguments(&manifest.compiler.arguments)?;

    let manifest_parent = manifest_path
        .parent()
        .context("compilation reproduction manifest has no parent")?;
    let runner = verify_declared_file(
        manifest_parent,
        &manifest.compiler.runner_path,
        &manifest.compiler.runner_sha256,
    )?;
    let artifact_manifest = verify_declared_file(
        manifest_parent,
        &manifest.compiler.artifact_manifest_path,
        &manifest.compiler.artifact_manifest_sha256,
    )?;
    let compiler_artifacts = verify_directory_manifest(&artifact_manifest)?;
    validate_literal_path_arguments(
        manifest_parent,
        &manifest.compiler.arguments,
        &runner,
        &compiler_artifacts,
        &BTreeSet::new(),
    )?;
    ensure!(
        manifest.variants.clean.entrypoint_path == manifest.variants.mutant.entrypoint_path
            && manifest.variants.mutant.entrypoint_path
                == manifest.variants.disturbance_twin.entrypoint_path
            && manifest.variants.clean.r1cs_output_path
                == manifest.variants.mutant.r1cs_output_path
            && manifest.variants.mutant.r1cs_output_path
                == manifest.variants.disturbance_twin.r1cs_output_path
            && manifest.variants.clean.sym_output_path == manifest.variants.mutant.sym_output_path
            && manifest.variants.mutant.sym_output_path
                == manifest.variants.disturbance_twin.sym_output_path,
        "compilation variants must use one logical entrypoint and output layout"
    );

    let mutant_closure_path =
        verify_file_ref_from_parent(spec_parent, &injection.source_closures.mutant)?;
    let mutant_sources = verify_directory_manifest_entries(&mutant_closure_path)?;
    let target_logical_path = mutant_sources
        .iter()
        .find_map(|(logical_path, entry)| {
            (entry.canonical_path == spec.source_path).then_some(logical_path.clone())
        })
        .context("mutant compilation closure omits the bound target source")?;
    let target_parameters = spec
        .spec
        .target_binding
        .concrete_parameters
        .iter()
        .map(|parameter| parameter.value_decimal.clone())
        .collect::<Vec<_>>();

    for (label, declared, expected_closure, expected_compiled) in [
        (
            "clean",
            &manifest.variants.clean,
            &injection.source_closures.clean,
            &injection.compiled_variants.clean,
        ),
        (
            "mutant",
            &manifest.variants.mutant,
            &injection.source_closures.mutant,
            &injection.compiled_variants.mutant,
        ),
        (
            "disturbance-twin",
            &manifest.variants.disturbance_twin,
            &injection.source_closures.disturbance_twin,
            &injection.compiled_variants.disturbance_twin,
        ),
    ] {
        reproduce_compiled_variant(
            label,
            manifest_parent,
            &manifest.compiler,
            &runner,
            &artifact_manifest,
            &compiler_artifacts,
            declared,
            spec_parent,
            expected_closure,
            expected_compiled,
            &target_logical_path,
            &spec.spec.target_binding.template,
            &target_parameters,
        )?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn reproduce_compiled_variant(
    label: &str,
    manifest_parent: &Path,
    compiler: &CompilationCompiler,
    runner: &Path,
    artifact_manifest: &Path,
    compiler_artifacts: &BTreeMap<PathBuf, String>,
    declared: &CompilationReproductionVariant,
    spec_parent: &Path,
    expected_closure: &FileRef,
    expected_compiled: &CompiledVariant,
    target_logical_path: &Path,
    target_template: &str,
    target_parameters: &[String],
) -> Result<()> {
    validate_safe_relative_path(&declared.entrypoint_path, "compilation entrypoint")?;
    validate_safe_relative_path(&declared.r1cs_output_path, "R1CS output")?;
    validate_safe_relative_path(&declared.sym_output_path, "SYM output")?;
    ensure!(
        declared.r1cs_output_path != declared.sym_output_path,
        "compilation outputs must be distinct"
    );

    let declared_closure_path = verify_declared_file(
        manifest_parent,
        &declared.source_closure_manifest_path,
        &declared.source_closure_manifest_sha256,
    )?;
    let expected_closure_path = verify_file_ref_from_parent(spec_parent, expected_closure)?;
    ensure!(
        declared_closure_path == expected_closure_path
            && declared.source_closure_manifest_sha256 == expected_closure.sha256,
        "compilation source closure differs from injection ground truth"
    );
    let source_files = verify_directory_manifest_entries(&declared_closure_path)?;
    ensure!(
        source_files.contains_key(&declared.entrypoint_path),
        "compilation entrypoint is absent from the source closure"
    );

    let scratch = ScratchDirectory::create(&format!("candidate-compilation-{label}"))?;
    let source_root = scratch.0.join("source");
    let output_dir = scratch.0.join("output");
    fs::create_dir_all(&source_root)?;
    fs::create_dir_all(&output_dir)?;
    let mut materialized_sources = BTreeMap::new();
    for (logical_path, entry) in &source_files {
        validate_safe_relative_path(logical_path, "source closure entry")?;
        let destination = source_root.join(logical_path);
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&destination, fs::read(&entry.canonical_path)?)?;
        ensure!(
            sha256_file(&destination)? == entry.sha256,
            "materialized source closure changed"
        );
        materialized_sources.insert(fs::canonicalize(destination)?, entry.sha256.clone());
    }

    let entrypoint = fs::canonicalize(source_root.join(&declared.entrypoint_path))?;
    let target_source = fs::canonicalize(source_root.join(target_logical_path))
        .context("resolve the materialized bound target source")?;
    ensure!(
        materialized_sources.contains_key(&target_source),
        "materialized compilation closure omits the bound target source"
    );
    let r1cs_output = output_dir.join(&declared.r1cs_output_path);
    let sym_output = output_dir.join(&declared.sym_output_path);
    for output in [&r1cs_output, &sym_output] {
        if let Some(parent) = output.parent() {
            fs::create_dir_all(parent)?;
        }
    }
    let artifact_root = artifact_manifest
        .parent()
        .context("compiler artifact manifest has no parent")?;
    let replacements = [
        ("{entrypoint}", entrypoint.as_path()),
        ("{source_root}", source_root.as_path()),
        ("{output_dir}", output_dir.as_path()),
        ("{r1cs_output}", r1cs_output.as_path()),
        ("{sym_output}", sym_output.as_path()),
        ("{artifact_manifest}", artifact_manifest),
        ("{artifact_root}", artifact_root),
    ];
    let arguments = compiler
        .arguments
        .iter()
        .map(|argument| {
            let value = replacements
                .iter()
                .fold(argument.clone(), |value, (key, path)| {
                    value.replace(key, &path.to_string_lossy())
                });
            value.replace("{variant}", label)
        })
        .collect::<Vec<_>>();
    ensure!(
        arguments
            .iter()
            .all(|argument| !argument.contains('{') && !argument.contains('}')),
        "compilation argument contains an unresolved placeholder"
    );
    let library_paths = compiler_library_paths(&arguments, &source_root)?;
    validate_closed_circom_source_closure(
        &entrypoint,
        &source_root,
        &library_paths,
        &materialized_sources,
    )?;
    let discovery = targets::discover_project_targets_with(
        &source_root,
        scratch.0.join("target-binding-discovery"),
        &targets::DiscoveryOptions {
            entrypoint: Some(entrypoint.clone()),
            library_paths: library_paths.clone(),
            circom_bin: None,
            compile_timeout_seconds: targets::DEFAULT_WRAPPER_COMPILE_TIMEOUT_SECONDS,
            instance_capture: None,
            capture_timeout_seconds: targets::DEFAULT_CAPTURE_TIMEOUT_SECONDS,
        },
    )?;
    let expected_instance_key =
        targets::concrete_instance_key(&target_source, target_template, target_parameters)?;
    ensure!(
        discovery.entrypoint_status == targets::EntrypointStatus::Found
            && discovery.unsupported.is_empty()
            && discovery.root_instance_key.as_deref() == Some(expected_instance_key.as_str()),
        "compiled wrapper main differs from the bound target template instance"
    );
    let mut allowed_inputs = compiler_artifacts.clone();
    allowed_inputs.extend(materialized_sources);
    allowed_inputs.insert(
        fs::canonicalize(artifact_manifest)?,
        sha256_file(artifact_manifest)?,
    );
    let tmp = scratch.0.join("tmp");
    fs::create_dir(&tmp)?;
    let allowed_directories = BTreeSet::from([
        fs::canonicalize(&source_root)?,
        fs::canonicalize(&output_dir)?,
        fs::canonicalize(&tmp)?,
    ]);
    validate_literal_path_arguments(
        &scratch.0,
        &arguments,
        runner,
        &allowed_inputs,
        &allowed_directories,
    )?;

    let mut command = Command::new(runner);
    command
        .args(&arguments)
        .current_dir(&scratch.0)
        .env_clear()
        .env("TMPDIR", &tmp)
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .stdin(Stdio::null());
    let output = run_bounded(&mut command, COMPILER_TIMEOUT)
        .with_context(|| format!("start pinned {label} compiler"))?;
    ensure!(
        !output.timed_out,
        "pinned {label} compiler exceeded its fixed timeout"
    );
    ensure!(
        output.status.success(),
        "pinned {label} compiler exited unsuccessfully"
    );
    ensure!(
        r1cs_output.is_file() && sym_output.is_file(),
        "pinned {label} compiler did not create both declared outputs"
    );
    ensure!(
        sha256_file(&r1cs_output)? == expected_compiled.r1cs_sha256
            && sha256_file(&sym_output)? == expected_compiled.sym_sha256,
        "pinned {label} compilation did not reproduce the compiled variant"
    );
    Ok(())
}

fn validate_compilation_arguments(arguments: &[String]) -> Result<()> {
    let joined = arguments.join("\0");
    ensure!(
        joined.contains("{entrypoint}")
            && (joined.contains("{output_dir}")
                || (joined.contains("{r1cs_output}") && joined.contains("{sym_output}"))),
        "compilation arguments must bind the entrypoint and declared outputs"
    );
    let mut without_known = joined;
    for placeholder in [
        "{entrypoint}",
        "{source_root}",
        "{output_dir}",
        "{r1cs_output}",
        "{sym_output}",
        "{artifact_manifest}",
        "{artifact_root}",
        "{variant}",
    ] {
        without_known = without_known.replace(placeholder, "");
    }
    ensure!(
        !without_known.contains('{') && !without_known.contains('}'),
        "compilation arguments contain an unsupported placeholder"
    );
    Ok(())
}

/// The review spec stores the exact semantic compiler settings that are frozen in a
/// prepared target and later passed to zkFuzz. The placeholder-bearing full invocation
/// belongs to the separate compilation-reproduction manifest.
fn validate_prepared_compiler_arguments(arguments: &[String]) -> Result<()> {
    let mut index = 0;
    while index < arguments.len() {
        ensure!(
            arguments[index] == "-l",
            "prepared compiler arguments may contain only -l library paths"
        );
        index += 1;
        ensure!(
            index < arguments.len() && !arguments[index].starts_with('-'),
            "-l requires at least one library path"
        );
        while index < arguments.len() && !arguments[index].starts_with('-') {
            ensure!(
                !arguments[index].contains('{') && !arguments[index].contains('}'),
                "prepared compiler library paths cannot contain placeholders"
            );
            index += 1;
        }
    }
    Ok(())
}

fn validate_safe_relative_path(path: &Path, label: &str) -> Result<()> {
    ensure!(
        !path.as_os_str().is_empty()
            && !path.is_absolute()
            && path
                .components()
                .all(|component| matches!(component, Component::Normal(_))),
        "{label} must be a normalized relative path"
    );
    Ok(())
}

fn validate_closed_circom_source_closure(
    entrypoint: &Path,
    source_root: &Path,
    library_paths: &[PathBuf],
    materialized_sources: &BTreeMap<PathBuf, String>,
) -> Result<()> {
    let source_root = fs::canonicalize(source_root)?;
    let mut pending = vec![fs::canonicalize(entrypoint)?];
    let mut visited = BTreeSet::new();
    while let Some(source) = pending.pop() {
        ensure!(
            source.starts_with(&source_root) && materialized_sources.contains_key(&source),
            "Circom source escaped the materialized source closure"
        );
        if !visited.insert(source.clone()) {
            continue;
        }
        for literal in targets::circom_include_literals(&source)? {
            let include = Path::new(&literal);
            ensure!(
                !include.is_absolute(),
                "Circom source closure contains an absolute include"
            );
            let local_parent = source.parent().context("Circom source has no parent")?;
            let mut resolved = None;
            for candidate in [local_parent.join(include), source_root.join(include)]
                .into_iter()
                .chain(library_paths.iter().map(|root| root.join(include)))
            {
                if candidate.is_file() {
                    resolved = Some(fs::canonicalize(candidate)?);
                    break;
                }
            }
            let resolved = resolved.with_context(|| {
                format!("Circom include is absent from source closure: {literal}")
            })?;
            ensure!(
                resolved.starts_with(&source_root) && materialized_sources.contains_key(&resolved),
                "Circom include resolved outside the materialized source closure"
            );
            pending.push(resolved);
        }
    }
    Ok(())
}

fn compiler_library_paths(arguments: &[String], source_root: &Path) -> Result<Vec<PathBuf>> {
    let source_root = fs::canonicalize(source_root)?;
    let mut paths = Vec::new();
    let mut index = 0;
    while index < arguments.len() {
        if arguments[index] != "-l" {
            index += 1;
            continue;
        }
        index += 1;
        let first_library = index;
        while index < arguments.len() && !arguments[index].starts_with('-') {
            let path = Path::new(&arguments[index]);
            ensure!(path.is_absolute(), "compiler library path must be absolute");
            let path = fs::canonicalize(path).with_context(|| {
                format!("compiler library path is unavailable: {}", path.display())
            })?;
            ensure!(
                path.is_dir() && path.starts_with(&source_root),
                "compiler library path is outside the materialized source closure"
            );
            if !paths.contains(&path) {
                paths.push(path);
            }
            index += 1;
        }
        ensure!(
            index > first_library,
            "compiler -l option has no library path"
        );
    }
    ensure!(
        paths.first().is_some_and(|path| path == &source_root),
        "compiler library search must begin with the materialized source root"
    );
    Ok(paths)
}

fn normalize_assignment_file(
    path: &Path,
    format: AssignmentFormat,
    r1cs: &R1cs,
    symbols: &SymbolTable,
    parameters: &[ConcreteParameter],
) -> Result<NormalizedAssignment> {
    match format {
        AssignmentFormat::WtnsJsonV1 => {
            let parsed: WitnessAssignment = serde_json::from_slice(&fs::read(path)?)
                .context("parse strict wtns-json-v1 assignment")?;
            let values = match parsed {
                WitnessAssignment::Object(object) => object.witness,
                WitnessAssignment::Array(values) => values,
            };
            ensure!(
                values.len() == r1cs.shape.wires,
                "witness JSON wire count differs from R1CS"
            );
            let parsed = values
                .iter()
                .map(|value| parse_assignment_field(value))
                .collect::<Result<Vec<_>>>()?;
            let wires = parsed
                .iter()
                .map(|(value, _)| value.clone())
                .collect::<Vec<_>>();
            ensure!(
                wires.first() == Some(&BigUint::one()),
                "witness constant wire is not one"
            );
            let canonical = parsed
                .iter()
                .all(|(value, canonical_text)| *canonical_text && value < &r1cs.prime);
            let wire_signals = symbols
                .by_name
                .iter()
                .filter_map(|(name, symbol)| {
                    usize::try_from(symbol.wire)
                        .ok()
                        .map(|wire| (name.clone(), wires[wire].to_str_radix(10)))
                })
                .collect();
            Ok(NormalizedAssignment {
                wires,
                wire_signals,
                eliminated_signals: BTreeMap::new(),
                parameters: parameters
                    .iter()
                    .map(|parameter| {
                        (
                            parameter.name.clone(),
                            TypedParameterValue {
                                kind: parameter.kind,
                                value_decimal: parameter.value_decimal.clone(),
                            },
                        )
                    })
                    .collect(),
                canonical,
            })
        }
        AssignmentFormat::ZkfuzzAssignmentV1 => {
            let raw: RawCounterexample = serde_json::from_slice(&fs::read(path)?)
                .context("parse strict zkFuzz assignment")?;
            normalize_named_assignment(&raw.assignment, r1cs, symbols, parameters)
        }
    }
}

fn normalize_named_assignment(
    assignment: &BTreeMap<String, String>,
    r1cs: &R1cs,
    symbols: &SymbolTable,
    parameters: &[ConcreteParameter],
) -> Result<NormalizedAssignment> {
    let mut raw = assignment.clone();
    let mut typed_parameters = BTreeMap::new();
    for parameter in parameters {
        let qualified = format!("main.{}", parameter.name);
        if let Some(value) = raw
            .remove(&qualified)
            .or_else(|| raw.remove(&parameter.name))
        {
            ensure!(
                value == parameter.value_decimal,
                "assignment parameter differs from spec"
            );
        }
        typed_parameters.insert(
            parameter.name.clone(),
            TypedParameterValue {
                kind: parameter.kind,
                value_decimal: parameter.value_decimal.clone(),
            },
        );
    }
    let mut wires = vec![None; r1cs.shape.wires];
    wires[0] = Some(BigUint::one());
    let mut eliminated = BTreeMap::new();
    let mut canonical = true;
    for (name, text) in raw {
        let symbol = symbols
            .by_name
            .get(&name)
            .with_context(|| format!("unexpected assignment entry {name}"))?;
        let (value, canonical_text) = parse_assignment_field(&text)?;
        canonical &= canonical_text && value < r1cs.prime;
        if symbol.wire >= 0 {
            let wire = usize::try_from(symbol.wire)?;
            if let Some(existing) = &wires[wire] {
                ensure!(existing == &value, "positive-wire aliases disagree");
            } else {
                wires[wire] = Some(value);
            }
        } else {
            eliminated.insert(name, value.to_str_radix(10));
        }
    }
    let wires = wires
        .into_iter()
        .enumerate()
        .map(|(wire, value)| value.with_context(|| format!("assignment misses wire {wire}")))
        .collect::<Result<Vec<_>>>()?;
    let wire_signals = symbols
        .by_name
        .iter()
        .filter_map(|(name, symbol)| {
            usize::try_from(symbol.wire)
                .ok()
                .map(|wire| (name.clone(), wires[wire].to_str_radix(10)))
        })
        .collect();
    Ok(NormalizedAssignment {
        wires,
        wire_signals,
        eliminated_signals: eliminated,
        parameters: typed_parameters,
        canonical,
    })
}

fn validate_projection_shape(
    projection: &ProjectionManifest,
    operator_id: &str,
    clean_r1cs: &R1cs,
    clean_symbols: &SymbolTable,
) -> Result<()> {
    ensure!(
        projection.schema_version == 1 && projection.operator_id == operator_id,
        "projection manifest does not match the injection operator"
    );
    ensure!(
        !projection.operator_justification.trim().is_empty(),
        "projection operator justification is empty"
    );
    ensure!(
        projection.mappings.len() + 1 == clean_r1cs.shape.wires,
        "projection must cover every nonconstant clean wire"
    );
    for (expected_wire, mapping) in projection.mappings.iter().enumerate() {
        let wire = expected_wire + 1;
        ensure!(
            mapping.clean_wire_index == wire,
            "projection mappings must be sorted and contiguous"
        );
        let mut expected_names = clean_symbols.wire_to_names[wire].clone();
        expected_names.sort();
        let mut declared_names = mapping.clean_signal_names.clone();
        declared_names.sort();
        ensure!(
            declared_names.windows(2).all(|pair| pair[0] != pair[1]),
            "projection repeats a clean signal alias"
        );
        ensure!(
            declared_names == expected_names,
            "projection clean signal aliases differ from pinned SYM"
        );
        ensure!(
            matches!(
                (mapping.source_kind, mapping.source_signal_name.as_ref()),
                (ProjectionSourceKind::DisturbanceSignal, Some(_))
                    | (ProjectionSourceKind::CleanReferenceWire, None)
            ),
            "projection source kind and source signal disagree"
        );
    }
    Ok(())
}

fn project_disturbance_to_clean(
    projection: &ProjectionManifest,
    operator_id: &str,
    clean_r1cs: &R1cs,
    clean_symbols: &SymbolTable,
    disturbance: &NormalizedAssignment,
    clean_reference: &NormalizedAssignment,
) -> Result<Vec<BigUint>> {
    validate_projection_shape(projection, operator_id, clean_r1cs, clean_symbols)?;
    let mut projected = vec![BigUint::one(); clean_r1cs.shape.wires];
    for (expected_wire, mapping) in projection.mappings.iter().enumerate() {
        let wire = expected_wire + 1;
        projected[wire] = match mapping.source_kind {
            ProjectionSourceKind::DisturbanceSignal => {
                let name = mapping
                    .source_signal_name
                    .as_ref()
                    .context("disturbance projection lacks a source signal")?;
                parse_decimal_field(disturbance.signal(name)?)?
            }
            ProjectionSourceKind::CleanReferenceWire => {
                ensure!(
                    mapping.source_signal_name.is_none(),
                    "clean-reference projection must not name a disturbance signal"
                );
                clean_reference.wires[wire].clone()
            }
        };
    }
    clean_r1cs.validate_assignment(&projected)?;
    Ok(projected)
}

fn input_signals_equal(
    names: &[String],
    disturbance: &NormalizedAssignment,
    clean_reference: &NormalizedAssignment,
) -> Result<bool> {
    let mut equal = true;
    for name in names {
        let disturbance_value = disturbance
            .signal(name)
            .context("resolve disturbance contract input")?;
        let clean_value = clean_reference
            .signal(name)
            .context("resolve clean reference contract input")?;
        equal &= disturbance_value == clean_value;
    }
    Ok(equal)
}

fn ground_truth_qualification(
    common: Disposition,
    criteria: &QualificationCriteria,
    attribution: AttributionVerdict,
) -> GroundTruthQualification {
    let values = [
        criteria.twin_r1cs_identity.as_ref(),
        criteria.twin_sym_identity.as_ref(),
        criteria.generation_reproducibility.as_ref(),
        criteria.clean_reference_assignment_encoding.as_ref(),
        criteria.clean_reference_constraints.as_ref(),
        criteria.clean_input_equivalence.as_ref(),
        criteria.clean_rejection.as_ref(),
        criteria.clean_relation_exclusion.as_ref(),
        criteria.production_reachability.as_ref(),
    ];
    if common == Disposition::ReviewError || values.iter().any(|value| value.is_none()) {
        GroundTruthQualification::ReviewError
    } else if common == Disposition::Rejected
        || values
            .iter()
            .flatten()
            .any(|criterion| criterion.verdict == CriterionVerdict::NotSatisfied)
        || attribution == AttributionVerdict::NotMatched
    {
        GroundTruthQualification::Rejected
    } else if common == Disposition::Unresolved
        || values
            .iter()
            .flatten()
            .any(|criterion| criterion.verdict == CriterionVerdict::Unknown)
        || attribution == AttributionVerdict::Unknown
    {
        GroundTruthQualification::Unresolved
    } else {
        GroundTruthQualification::Qualified
    }
}

struct ScratchDirectory(PathBuf);

impl ScratchDirectory {
    fn create(label: &str) -> Result<Self> {
        let path = std::env::temp_dir().join(format!("zkfdo-{label}-{}", Uuid::new_v4()));
        fs::create_dir(&path)
            .with_context(|| format!("create scratch directory {}", path.display()))?;
        Ok(Self(path))
    }
}

impl Drop for ScratchDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn reproduce_generation(
    manifest: &GenerationManifest,
    manifest_parent: &Path,
    common_input: &Path,
) -> Result<bool> {
    let clean = reproduce_generator(
        &manifest.generators.clean,
        manifest_parent,
        common_input,
        "clean",
    )?;
    let twin = reproduce_generator(
        &manifest.generators.disturbance_twin,
        manifest_parent,
        common_input,
        "disturbance-twin",
    )?;
    Ok(clean && twin)
}

fn reproduce_generator(
    generator: &GeneratorSpec,
    manifest_parent: &Path,
    common_input: &Path,
    label: &str,
) -> Result<bool> {
    let runner = verify_declared_file(
        manifest_parent,
        &generator.runner_path,
        &generator.runner_sha256,
    )?;
    let artifact_manifest = verify_declared_file(
        manifest_parent,
        &generator.artifact_manifest_path,
        &generator.artifact_manifest_sha256,
    )?;
    let artifacts = verify_directory_manifest(&artifact_manifest)?;
    let scratch = ScratchDirectory::create("candidate-generation")?;
    let witness_output = scratch.0.join(format!("{label}.witness"));
    let assignment_output = scratch.0.join(format!("{label}.assignment.json"));
    let tmp = scratch.0.join("tmp");
    fs::create_dir(&tmp)?;
    let replacements = [
        ("{common_input}", common_input),
        ("{witness_output}", witness_output.as_path()),
        ("{assignment_output}", assignment_output.as_path()),
        ("{artifact_manifest}", artifact_manifest.as_path()),
    ];
    let arguments = generator
        .arguments
        .iter()
        .map(|argument| {
            replacements
                .iter()
                .fold(argument.clone(), |value, (key, path)| {
                    value.replace(key, &path.to_string_lossy())
                })
        })
        .collect::<Vec<_>>();
    ensure!(
        arguments
            .iter()
            .all(|argument| !argument.contains('{') && !argument.contains('}')),
        "generator argument contains an unresolved placeholder"
    );
    let mut allowed_inputs = artifacts;
    allowed_inputs.insert(fs::canonicalize(common_input)?, sha256_file(common_input)?);
    allowed_inputs.insert(
        fs::canonicalize(&artifact_manifest)?,
        sha256_file(&artifact_manifest)?,
    );
    let allowed_directories =
        BTreeSet::from([fs::canonicalize(&scratch.0)?, fs::canonicalize(&tmp)?]);
    validate_literal_path_arguments(
        &scratch.0,
        &arguments,
        &runner,
        &allowed_inputs,
        &allowed_directories,
    )?;
    let mut command = Command::new(&runner);
    command
        .args(&arguments)
        .current_dir(&scratch.0)
        .env_clear()
        .env("TMPDIR", &tmp)
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .stdin(Stdio::null());
    let output = run_bounded(&mut command, GENERATOR_TIMEOUT)
        .with_context(|| format!("start pinned {label} generator"))?;
    ensure!(
        !output.timed_out,
        "pinned {label} generator exceeded its fixed timeout"
    );
    ensure!(
        !output.stdout_nonempty && !output.stderr_nonempty,
        "generator wrote outside its fixed output channels"
    );
    ensure!(output.status.success(), "generator exited unsuccessfully");
    ensure!(
        witness_output.is_file() && assignment_output.is_file(),
        "generator did not create both declared outputs"
    );
    Ok(sha256_file(&witness_output)? == generator.witness_sha256
        && sha256_file(&assignment_output)? == generator.assignment_sha256)
}

fn validate_relation_verifier_artifacts(
    spec: &LoadedSpec,
    injection: &InjectionGroundTruth,
) -> Result<()> {
    let spec_parent = spec.path.parent().context("review spec has no parent")?;
    let exclusion = &injection.clean_relation_exclusion;
    let certificate_path = verify_declared_file(
        spec_parent,
        &exclusion.certificate_path,
        &exclusion.certificate_sha256,
    )?;
    let manifest_path = verify_declared_file(
        spec_parent,
        &exclusion.verifier_manifest_path,
        &exclusion.verifier_manifest_sha256,
    )?;
    let manifest: RelationVerifierManifest = serde_json::from_slice(&fs::read(&manifest_path)?)
        .context("parse strict relation verifier manifest")?;
    ensure!(
        manifest.schema_version == 1
            && manifest.api_version == 1
            && manifest.method == exclusion.method
            && !manifest.verifier_id.trim().is_empty()
            && !manifest.certificate_format.trim().is_empty(),
        "relation verifier manifest does not match the spec"
    );
    ensure!(
        !manifest.allowed_results.is_empty(),
        "relation verifier result catalog is empty"
    );
    let mut allowed = BTreeSet::new();
    for result in &manifest.allowed_results {
        ensure!(
            !result.reason_code.trim().is_empty()
                && allowed.insert((result.verdict, result.reason_code.as_str())),
            "relation verifier result catalog contains an empty or duplicate entry"
        );
    }
    let manifest_parent = manifest_path
        .parent()
        .context("verifier manifest has no parent")?;
    let source_manifest = verify_declared_file(
        manifest_parent,
        &manifest.implementation.source_manifest_path,
        &manifest.implementation.source_manifest_sha256,
    )?;
    let verifier_sources = verify_directory_manifest(&source_manifest)?;

    match manifest.implementation.kind {
        VerifierImplementationKind::EngineBuiltin => {
            ensure!(
                exclusion.method == RelationExclusionMethod::FullyFixedConstraint
                    && manifest.certificate_format == "fully-fixed-constraint-v1"
                    && manifest.implementation.executable_path.is_none()
                    && manifest.implementation.executable_sha256.is_none(),
                "invalid built-in relation verifier manifest"
            );
            require_manifest_source(
                &verifier_sources,
                "engine.rs",
                REVIEW_ENGINE_SOURCE.as_bytes(),
            )?;
            require_manifest_source(&verifier_sources, "r1cs.rs", REVIEW_R1CS_SOURCE.as_bytes())?;
            require_manifest_source(
                &verifier_sources,
                "schema.rs",
                REVIEW_SCHEMA_SOURCE.as_bytes(),
            )?;
            let certificate: FullyFixedConstraintCertificate =
                serde_json::from_slice(&fs::read(certificate_path)?)
                    .context("parse strict fully-fixed-constraint certificate")?;
            ensure!(
                certificate.schema_version == 1
                    && certificate.method == RelationExclusionMethod::FullyFixedConstraint,
                "invalid fully-fixed-constraint certificate"
            );
            ensure_sorted_unique(&certificate.clean_constraint_indices)?;
            ensure_sorted_unique(&certificate.fixed_signal_names)?;
            ensure!(
                !certificate.clean_constraint_indices.is_empty()
                    && !certificate.fixed_signal_names.is_empty(),
                "fully-fixed certificate lists must not be empty"
            );
            ensure!(
                certificate
                    .clean_constraint_indices
                    .iter()
                    .all(|index| injection.expected_clean_constraint_indices.contains(index)),
                "certificate checks a constraint outside the predeclared injection set"
            );
            let allowed_fixed = spec
                .spec
                .contract
                .input_signal_names
                .iter()
                .chain(spec.spec.contract.property_signal_names.iter())
                .collect::<BTreeSet<_>>();
            ensure!(
                certificate
                    .fixed_signal_names
                    .iter()
                    .all(|name| allowed_fixed.contains(name)),
                "certificate fixes a signal outside the contract input/property set"
            );
        }
        VerifierImplementationKind::External => {
            ensure!(
                matches!(
                    exclusion.method,
                    RelationExclusionMethod::OperatorProof
                        | RelationExclusionMethod::SolverUnsatCertificate
                ),
                "external verifier method is unsupported"
            );
            let executable_path = manifest
                .implementation
                .executable_path
                .as_ref()
                .context("external verifier has no executable path")?;
            let executable_sha256 = manifest
                .implementation
                .executable_sha256
                .as_ref()
                .context("external verifier has no executable hash")?;
            verify_declared_file(manifest_parent, executable_path, executable_sha256)?;
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn verify_relation_exclusion(
    spec: &LoadedSpec,
    injection: &InjectionGroundTruth,
    clean_r1cs: &R1cs,
    clean_symbols: &SymbolTable,
    projection: &ProjectionManifest,
    projected: &[BigUint],
    failed_clean: &[usize],
    disturbance: &NormalizedAssignment,
    report_dir: &Path,
) -> Result<Criterion> {
    let spec_parent = spec.path.parent().context("review spec has no parent")?;
    let exclusion = &injection.clean_relation_exclusion;
    let certificate_path = verify_declared_file(
        spec_parent,
        &exclusion.certificate_path,
        &exclusion.certificate_sha256,
    )?;
    let manifest_path = verify_declared_file(
        spec_parent,
        &exclusion.verifier_manifest_path,
        &exclusion.verifier_manifest_sha256,
    )?;
    let manifest: RelationVerifierManifest = serde_json::from_slice(&fs::read(&manifest_path)?)
        .context("parse strict relation verifier manifest")?;
    ensure!(
        manifest.schema_version == 1
            && manifest.api_version == 1
            && manifest.method == exclusion.method,
        "relation verifier manifest does not match the spec"
    );
    let manifest_parent = manifest_path
        .parent()
        .context("verifier manifest has no parent")?;
    let verifier_source_manifest = verify_declared_file(
        manifest_parent,
        &manifest.implementation.source_manifest_path,
        &manifest.implementation.source_manifest_sha256,
    )?;
    let verifier_sources = verify_directory_manifest(&verifier_source_manifest)?;
    let evidence = vec![
        file_ref_from(report_dir, &certificate_path)?,
        file_ref_from(report_dir, &manifest_path)?,
    ];
    let result = match manifest.implementation.kind {
        VerifierImplementationKind::EngineBuiltin => {
            ensure!(
                exclusion.method == RelationExclusionMethod::FullyFixedConstraint
                    && manifest.certificate_format == "fully-fixed-constraint-v1"
                    && manifest.implementation.executable_path.is_none()
                    && manifest.implementation.executable_sha256.is_none(),
                "invalid built-in relation verifier manifest"
            );
            require_manifest_source(
                &verifier_sources,
                "engine.rs",
                REVIEW_ENGINE_SOURCE.as_bytes(),
            )?;
            require_manifest_source(&verifier_sources, "r1cs.rs", REVIEW_R1CS_SOURCE.as_bytes())?;
            require_manifest_source(
                &verifier_sources,
                "schema.rs",
                REVIEW_SCHEMA_SOURCE.as_bytes(),
            )?;
            verify_fully_fixed_constraint(
                &certificate_path,
                &exclusion.certificate_sha256,
                &injection.expected_clean_constraint_indices,
                clean_r1cs,
                clean_symbols,
                projection,
                projected,
                failed_clean,
                &spec.spec.contract,
                disturbance,
            )?
        }
        VerifierImplementationKind::External => run_external_relation_verifier(
            &manifest,
            &manifest_path,
            &certificate_path,
            exclusion,
            injection,
            spec,
            disturbance,
        )?,
    };
    ensure!(
        manifest.allowed_results.iter().any(|allowed| {
            allowed.verdict == result.verdict && allowed.reason_code == result.reason_code
        }),
        "relation verifier returned a result outside its manifest"
    );
    ensure!(
        result.method == exclusion.method
            && result.certificate_sha256 == exclusion.certificate_sha256,
        "relation verifier result binding mismatch"
    );
    Ok(Criterion {
        verdict: result.verdict,
        reason_code: result.reason_code,
        evidence,
        note: match result.verdict {
            CriterionVerdict::Satisfied => {
                "A pinned verifier excludes every clean extension for the fixed contract signals."
                    .to_owned()
            }
            CriterionVerdict::NotSatisfied => {
                "The pinned verifier found that a clean extension was not excluded.".to_owned()
            }
            CriterionVerdict::Unknown => {
                "The pinned verifier could not complete the clean relation exclusion proof."
                    .to_owned()
            }
        },
    })
}

#[allow(clippy::too_many_arguments)]
fn verify_fully_fixed_constraint(
    certificate_path: &Path,
    certificate_sha256: &str,
    expected_clean_constraint_indices: &[usize],
    clean_r1cs: &R1cs,
    clean_symbols: &SymbolTable,
    projection: &ProjectionManifest,
    projected: &[BigUint],
    failed_clean: &[usize],
    contract: &ContractSpec,
    disturbance: &NormalizedAssignment,
) -> Result<VerifierResult> {
    let certificate: FullyFixedConstraintCertificate =
        serde_json::from_slice(&fs::read(certificate_path)?)
            .context("parse strict fully-fixed-constraint certificate")?;
    ensure!(
        certificate.schema_version == 1
            && certificate.method == RelationExclusionMethod::FullyFixedConstraint,
        "invalid fully-fixed-constraint certificate"
    );
    ensure_sorted_unique(&certificate.clean_constraint_indices)?;
    ensure_sorted_unique(&certificate.fixed_signal_names)?;
    ensure!(
        !certificate.clean_constraint_indices.is_empty()
            && !certificate.fixed_signal_names.is_empty(),
        "fully-fixed certificate lists must not be empty"
    );
    ensure!(
        certificate
            .clean_constraint_indices
            .iter()
            .all(|index| expected_clean_constraint_indices.contains(index)),
        "certificate checks a constraint outside the predeclared injection set"
    );
    let allowed_fixed = contract
        .input_signal_names
        .iter()
        .chain(contract.property_signal_names.iter())
        .collect::<BTreeSet<_>>();
    ensure!(
        certificate
            .fixed_signal_names
            .iter()
            .all(|name| allowed_fixed.contains(name) && disturbance.signal(name).is_ok()),
        "certificate fixes a signal outside the contract input/property set"
    );
    let fixed = certificate
        .fixed_signal_names
        .iter()
        .collect::<BTreeSet<_>>();
    let mut all_constraints_fully_fixed = true;
    for &constraint_index in &certificate.clean_constraint_indices {
        ensure!(
            constraint_index < clean_r1cs.constraints.len(),
            "certificate constraint index is outside the clean R1CS"
        );
        let constraint = &clean_r1cs.constraints[constraint_index];
        let wires = constraint
            .a
            .keys()
            .chain(constraint.b.keys())
            .chain(constraint.c.keys())
            .copied()
            .filter(|wire| *wire != 0)
            .collect::<BTreeSet<_>>();
        let wires_are_bound_to_disturbance = wires.iter().all(|wire| {
            let wire = *wire as usize;
            let Some(mapping) = projection.mappings.get(wire - 1) else {
                return false;
            };
            if mapping.clean_wire_index != wire
                || mapping.source_kind != ProjectionSourceKind::DisturbanceSignal
            {
                return false;
            }
            let Some(source_name) = mapping.source_signal_name.as_ref() else {
                return false;
            };
            if !fixed.contains(source_name)
                || !clean_symbols.wire_to_names[wire].contains(source_name)
            {
                return false;
            }
            disturbance
                .signal(source_name)
                .ok()
                .and_then(|value| parse_decimal_field(value).ok())
                .is_some_and(|value| value == projected[wire])
        });
        all_constraints_fully_fixed &=
            failed_clean.contains(&constraint_index) && wires_are_bound_to_disturbance;
    }
    ensure!(
        clean_r1cs.failed_constraint_indices(projected)? == failed_clean,
        "caller-supplied clean failure set differs from a fresh evaluation"
    );
    Ok(VerifierResult {
        schema_version: 1,
        method: RelationExclusionMethod::FullyFixedConstraint,
        verdict: if all_constraints_fully_fixed {
            CriterionVerdict::Satisfied
        } else {
            CriterionVerdict::NotSatisfied
        },
        reason_code: if all_constraints_fully_fixed {
            "clean-relation-excluded".to_owned()
        } else {
            "clean-extension-not-excluded".to_owned()
        },
        checked_clean_constraint_indices: certificate.clean_constraint_indices,
        fixed_signal_names: certificate.fixed_signal_names,
        certificate_sha256: certificate_sha256.to_owned(),
    })
}

fn run_external_relation_verifier(
    manifest: &RelationVerifierManifest,
    manifest_path: &Path,
    certificate_path: &Path,
    exclusion: &CleanRelationExclusion,
    injection: &InjectionGroundTruth,
    spec: &LoadedSpec,
    disturbance: &NormalizedAssignment,
) -> Result<VerifierResult> {
    ensure!(
        matches!(
            exclusion.method,
            RelationExclusionMethod::OperatorProof
                | RelationExclusionMethod::SolverUnsatCertificate
        ),
        "external verifier method is unsupported"
    );
    let manifest_parent = manifest_path
        .parent()
        .context("verifier manifest has no parent")?;
    let executable_path = manifest
        .implementation
        .executable_path
        .as_ref()
        .context("external verifier has no executable path")?;
    let executable_sha256 = manifest
        .implementation
        .executable_sha256
        .as_ref()
        .context("external verifier has no executable hash")?;
    let executable = verify_declared_file(manifest_parent, executable_path, executable_sha256)?;
    let spec_parent = spec.path.parent().context("review spec has no parent")?;
    let clean = &injection.compiled_variants.clean;
    let clean_r1cs = verify_declared_file(spec_parent, &clean.r1cs_path, &clean.r1cs_sha256)?;
    let clean_sym = verify_declared_file(spec_parent, &clean.sym_path, &clean.sym_sha256)?;
    verify_file_ref_from_parent(spec_parent, &injection.projection_manifest)?;
    let fixed_signals = spec
        .spec
        .contract
        .input_signal_names
        .iter()
        .chain(spec.spec.contract.property_signal_names.iter())
        .map(|name| {
            disturbance
                .signal(name)
                .map(|value| (name.clone(), value.to_owned()))
                .with_context(|| format!("resolve external-verifier fixed signal {name}"))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    let scratch = ScratchDirectory::create("relation-verifier")?;
    let context_path = scratch.0.join("context.json");
    let result_path = scratch.0.join("result.json");
    let context = json!({
        "schema_version": 1,
        "method": serde_json::to_value(exclusion.method)?,
        "field_modulus_decimal": spec.spec.field.modulus_decimal,
        "clean_r1cs": {"path": clean_r1cs, "sha256": clean.r1cs_sha256},
        "clean_sym": {"path": clean_sym, "sha256": clean.sym_sha256},
        "projection_manifest_sha256": injection.projection_manifest.sha256,
        "expected_clean_constraint_indices": injection.expected_clean_constraint_indices,
        "contract_input_signal_names": spec.spec.contract.input_signal_names,
        "property_signal_names": spec.spec.contract.property_signal_names,
        "fixed_signals": fixed_signals,
        "certificate": {"path": certificate_path, "sha256": exclusion.certificate_sha256},
    });
    fs::write(&context_path, serde_json::to_vec(&context)?)?;
    let tmp = scratch.0.join("tmp");
    fs::create_dir(&tmp)?;
    let mut command = Command::new(executable);
    command
        .arg(&context_path)
        .arg(&result_path)
        .current_dir(&scratch.0)
        .env_clear()
        .env("TMPDIR", &tmp)
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .stdin(Stdio::null());
    let output = run_bounded(&mut command, EXTERNAL_VERIFIER_TIMEOUT)
        .context("start external relation verifier")?;
    ensure!(
        !output.timed_out,
        "external relation verifier exceeded its fixed timeout"
    );
    ensure!(
        !output.stdout_nonempty && !output.stderr_nonempty,
        "external verifier wrote to stdout or stderr"
    );
    ensure!(
        output.status.success(),
        "external verifier exited unsuccessfully"
    );
    let result: VerifierResult = serde_json::from_slice(&fs::read(result_path)?)
        .context("parse strict external verifier result")?;
    ensure!(
        result.schema_version == 1,
        "unsupported verifier result schema"
    );
    ensure_sorted_unique(&result.checked_clean_constraint_indices)?;
    ensure_sorted_unique(&result.fixed_signal_names)?;
    ensure!(
        result
            .checked_clean_constraint_indices
            .iter()
            .all(|index| injection.expected_clean_constraint_indices.contains(index)),
        "external verifier checked an undeclared constraint"
    );
    ensure!(
        result
            .fixed_signal_names
            .iter()
            .all(|name| fixed_signals.contains_key(name)),
        "external verifier fixed a signal outside the supplied context"
    );
    if result.verdict == CriterionVerdict::Satisfied {
        ensure!(
            !result.checked_clean_constraint_indices.is_empty()
                && !result.fixed_signal_names.is_empty(),
            "a satisfied external proof must report checked constraints and fixed signals"
        );
    }
    Ok(result)
}

fn verify_production_reachability(spec: &LoadedSpec, report_dir: &Path) -> Result<Criterion> {
    let reachability = &spec.spec.production_reachability;
    if reachability.verdict != ReachabilityVerdict::Satisfied {
        return Ok(match reachability.verdict {
            ReachabilityVerdict::NotSatisfied => boolean_criterion(
                false,
                "production-reachable",
                "production-unreachable",
                "The injected target is reachable from a production entrypoint.",
                "The injected target is not reachable from a production entrypoint.",
                vec![spec.report_ref.clone()],
            ),
            ReachabilityVerdict::Unknown => unknown_criterion(
                "production-reachability-unknown",
                "Production reachability has not been established by a complete pinned discovery.",
                vec![spec.report_ref.clone()],
            ),
            ReachabilityVerdict::Satisfied => unreachable!(),
        });
    }
    let spec_parent = spec.path.parent().context("review spec has no parent")?;
    let evidence_path = verify_declared_file(
        spec_parent,
        reachability
            .evidence_path
            .as_ref()
            .context("missing reachability evidence")?,
        reachability
            .evidence_sha256
            .as_ref()
            .context("missing reachability evidence hash")?,
    )?;
    let verifier_path = verify_declared_file(
        spec_parent,
        reachability
            .verifier_manifest_path
            .as_ref()
            .context("missing reachability verifier manifest")?,
        reachability
            .verifier_manifest_sha256
            .as_ref()
            .context("missing reachability verifier hash")?,
    )?;
    let evidence: ReachabilityEvidence = serde_json::from_slice(&fs::read(&evidence_path)?)
        .context("parse strict reachability evidence")?;
    let verifier: ReachabilityVerifierManifest = serde_json::from_slice(&fs::read(&verifier_path)?)
        .context("parse strict reachability verifier manifest")?;
    ensure!(
        evidence.schema_version == 1
            && verifier.schema_version == 1
            && evidence.completion == ReachabilityCompletion::Complete
            && evidence.unsupported.is_empty()
            && evidence.unresolved.is_empty(),
        "reachability discovery is incomplete"
    );
    let verifier_parent = verifier_path
        .parent()
        .context("reachability verifier manifest has no parent")?;
    let verifier_source_manifest = verify_declared_file(
        verifier_parent,
        &verifier.source_manifest_path,
        &verifier.source_manifest_sha256,
    )?;
    let verifier_sources = verify_directory_manifest(&verifier_source_manifest)?;
    require_manifest_source(
        &verifier_sources,
        "targets.rs",
        TARGET_DISCOVERY_SOURCE.as_bytes(),
    )?;
    let discovery_path = verify_declared_file(
        verifier_parent,
        &verifier.discovery_report_path,
        &verifier.discovery_report_sha256,
    )?;
    let pinned_discovery: targets::TargetDiscoveryReport =
        serde_json::from_slice(&fs::read(&discovery_path)?)
            .context("parse pinned reachability discovery report")?;
    ensure!(
        evidence.entrypoint_target_id
            == *reachability
                .entrypoint_target_id
                .as_ref()
                .context("missing entrypoint target")?
            && evidence.target_instance_key
                == *reachability
                    .instance_key
                    .as_ref()
                    .context("missing target instance")?
            && spec.spec.target_binding.instance_key.as_ref() == reachability.instance_key.as_ref()
            && evidence.source_closure_sha256 == spec.target_binding_source_closure_sha256(),
        "reachability evidence binding mismatch"
    );
    let source_closure_path = verify_declared_file(
        spec_parent,
        &spec.spec.target_binding.source_closure_manifest_path,
        &spec.spec.target_binding.source_closure_manifest_sha256,
    )?;
    let source_closure = verify_directory_manifest(&source_closure_path)?;
    let rerun_discovery = reproduce_reachability_discovery(&pinned_discovery, &source_closure)?;
    let discovery_root_key = rerun_discovery
        .root_instance_key
        .as_deref()
        .context("reproduced discovery has no root instance key")?;
    let mut instances = BTreeMap::new();
    for instance in &evidence.instances {
        ensure!(
            instances
                .insert(instance.instance_key.as_str(), instance)
                .is_none(),
            "duplicate reachability instance key"
        );
        let source = resolve_path(
            evidence_path
                .parent()
                .context("reachability evidence has no parent")?,
            &instance.source_path,
        );
        let canonical_source = fs::canonicalize(&source)?;
        ensure!(
            source.is_file() && sha256_file(&source)? == instance.source_sha256,
            "reachability source hash mismatch"
        );
        ensure!(
            source_closure
                .get(&canonical_source)
                .is_some_and(|sha256| sha256 == &instance.source_sha256),
            "reachability source is outside the pinned source closure"
        );
        let len = fs::metadata(source)?.len() as usize;
        ensure!(
            instance.start_byte < instance.end_byte && instance.end_byte <= len,
            "reachability source range is invalid"
        );
        let expected_key = format!(
            "{}::{}({})",
            canonical_source.display(),
            instance.template,
            instance
                .concrete_parameters
                .iter()
                .map(|parameter| parameter.value_decimal.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        );
        ensure!(
            instance.instance_key == expected_key,
            "reachability instance key differs from its source/template/parameters"
        );
        let (template_start, template_end) =
            targets::template_source_byte_range(&canonical_source, &instance.template)?;
        ensure!(
            instance.start_byte == template_start && instance.end_byte == template_end,
            "reachability instance range differs from the parsed template definition"
        );
        if instance.instance_key == discovery_root_key {
            ensure!(
                instance.parent_instance_key.is_none(),
                "reachability discovery root has a parent"
            );
        } else {
            let matching_edge = rerun_discovery.targets.iter().any(|target| {
                target.instance_key == instance.instance_key
                    && (!target.parent_instance_key.is_empty())
                        .then_some(target.parent_instance_key.as_str())
                        == instance.parent_instance_key.as_deref()
                    && fs::canonicalize(&target.source_path)
                        .is_ok_and(|path| path == canonical_source)
                    && target.template_name == instance.template
                    && target.concrete_parameters
                        == instance
                            .concrete_parameters
                            .iter()
                            .map(|parameter| parameter.value_decimal.clone())
                            .collect::<Vec<_>>()
            });
            ensure!(
                matching_edge,
                "reachability parent edge is absent from reproduced discovery"
            );
        }
    }
    let target_key = reachability
        .instance_key
        .as_deref()
        .context("missing reachability target instance")?;
    let target = instances
        .get(target_key)
        .context("reachability target instance is absent")?;
    ensure!(
        target.target_id == spec.spec.target_binding.target_id
            && target.template == spec.spec.target_binding.template
            && target.concrete_parameters == spec.spec.target_binding.concrete_parameters
            && target.source_sha256 == spec.spec.target_binding.source_sha256,
        "reachability target differs from review spec"
    );
    let target_source = resolve_path(
        evidence_path
            .parent()
            .context("reachability evidence has no parent")?,
        &target.source_path,
    );
    let bound_source = resolve_path(
        spec.path.parent().context("review spec has no parent")?,
        &spec.spec.target_binding.source_path,
    );
    ensure!(
        fs::canonicalize(&target_source)? == fs::canonicalize(&bound_source)?,
        "reachability target source path differs from review spec"
    );
    if let Some(injection) = &spec.spec.injection_ground_truth {
        let location_source = resolve_path(
            spec.path.parent().context("review spec has no parent")?,
            &injection.source_location.path,
        );
        ensure!(
            fs::canonicalize(location_source)? == fs::canonicalize(&target_source)?
                && injection.source_location.source_sha256 == target.source_sha256
                && target.start_byte <= injection.source_location.start_byte
                && injection.source_location.end_byte <= target.end_byte,
            "reachability target source differs from the injected source"
        );
    }
    let mut seen = BTreeSet::new();
    let mut cursor = target;
    loop {
        ensure!(
            seen.insert(cursor.instance_key.as_str()),
            "reachability parent chain contains a cycle"
        );
        match cursor.parent_instance_key.as_deref() {
            Some(parent) => {
                cursor = instances
                    .get(parent)
                    .context("reachability parent chain is disconnected")?;
            }
            None => break,
        }
    }
    ensure!(
        cursor.target_id == evidence.entrypoint_target_id
            && cursor.source_sha256 == evidence.entrypoint_source_sha256,
        "reachability chain does not terminate at the production entrypoint"
    );
    Ok(boolean_criterion(
        true,
        "production-reachable",
        "production-unreachable",
        "A complete pinned parent-instance chain reaches the production entrypoint.",
        "The injected target is not reachable from a production entrypoint.",
        vec![
            file_ref_from(report_dir, &evidence_path)?,
            file_ref_from(report_dir, &verifier_path)?,
            file_ref_from(report_dir, &discovery_path)?,
        ],
    ))
}

fn reproduce_reachability_discovery(
    pinned: &targets::TargetDiscoveryReport,
    source_closure: &BTreeMap<PathBuf, String>,
) -> Result<targets::TargetDiscoveryReport> {
    ensure!(
        pinned.entrypoint_status == targets::EntrypointStatus::Found
            && pinned.unsupported.is_empty(),
        "pinned reachability discovery is incomplete"
    );
    let selected_entrypoint = pinned
        .selected_entrypoint
        .as_ref()
        .context("pinned reachability discovery has no selected entrypoint")?;
    let selected_entrypoint = fs::canonicalize(selected_entrypoint)?;
    ensure!(
        source_closure.contains_key(&selected_entrypoint),
        "reachability entrypoint is outside the pinned source closure"
    );
    let dependency_paths = targets::discovery_dependency_paths(
        &selected_entrypoint,
        &pinned.project_root,
        &pinned.library_paths,
    )?;
    for path in dependency_paths {
        let observed_sha256 = sha256_file(&path)?;
        ensure!(
            source_closure
                .get(&path)
                .is_some_and(|expected| expected == &observed_sha256),
            "reachability discovery dependency is outside the pinned source closure"
        );
    }
    let scratch = tempfile::tempdir().context("create reachability reproduction directory")?;
    let rerun = targets::discover_project_targets_with(
        &pinned.project_root,
        scratch.path(),
        &targets::DiscoveryOptions {
            entrypoint: Some(selected_entrypoint.clone()),
            library_paths: pinned.library_paths.clone(),
            circom_bin: None,
            compile_timeout_seconds: targets::DEFAULT_WRAPPER_COMPILE_TIMEOUT_SECONDS,
            instance_capture: None,
            capture_timeout_seconds: targets::DEFAULT_CAPTURE_TIMEOUT_SECONDS,
        },
    )?;
    ensure!(
        rerun.entrypoint_status == targets::EntrypointStatus::Found
            && rerun.unsupported.is_empty()
            && rerun.root_instance_key == pinned.root_instance_key
            && rerun.entrypoints == pinned.entrypoints
            && rerun.selected_entrypoint.as_deref() == Some(selected_entrypoint.as_path()),
        "reachability discovery could not be reproduced"
    );

    let semantic_rows = |report: &targets::TargetDiscoveryReport| {
        report
            .targets
            .iter()
            .map(|target| {
                ensure!(
                    !target.identity.trim().is_empty() && !target.instance_key.trim().is_empty(),
                    "reachability discovery target lacks stable identity"
                );
                let source_path = fs::canonicalize(&target.source_path)?;
                let observed_sha256 = sha256_file(&source_path)?;
                ensure!(
                    source_closure
                        .get(&source_path)
                        .is_some_and(|sha256| sha256 == &observed_sha256),
                    "reachability discovery target is outside the pinned source closure"
                );
                Ok((
                    target.identity.clone(),
                    target.instance_key.clone(),
                    target.parent_instance_key.clone(),
                    source_path,
                    target.template_name.clone(),
                    target.concrete_parameters.clone(),
                ))
            })
            .collect::<Result<BTreeSet<_>>>()
    };
    ensure!(
        semantic_rows(&rerun)? == semantic_rows(pinned)?,
        "pinned and reproduced reachability discoveries differ"
    );
    Ok(rerun)
}

impl LoadedSpec {
    fn target_binding_source_closure_sha256(&self) -> String {
        self.spec
            .target_binding
            .source_closure_manifest_sha256
            .clone()
    }
}

fn load_spec(declaring_path: &Path, reference: &FileRef, report_dir: &Path) -> Result<LoadedSpec> {
    let path = verify_file_ref(declaring_path, reference)?;
    let bytes = fs::read(&path)?;
    let spec: ReviewSpec =
        serde_json::from_slice(&bytes).context("parse strict review-spec schema 1")?;
    ensure!(spec.schema_version == 1, "unsupported review-spec schema");
    ensure!(
        !spec.review_spec_id.trim().is_empty() && !spec.root_cause_id.trim().is_empty(),
        "review spec IDs must not be empty"
    );
    ensure!(
        spec.field.assignment_encoding == "canonical-field-elements",
        "unsupported assignment encoding"
    );
    ensure!(
        spec.contract.predicate.api_version == 1
            && spec.contract.predicate.entrypoint == "evaluate",
        "unsupported predicate API"
    );
    ensure!(
        !spec.contract.input_signal_names.is_empty()
            && !spec.contract.property_signal_names.is_empty(),
        "contract signal sets must not be empty"
    );
    ensure_unique_sorted_or_unsorted_names(&spec.contract.input_signal_names)?;
    ensure_unique_sorted_or_unsorted_names(&spec.contract.property_signal_names)?;
    validate_hex(&spec.compiler.binary_sha256)?;
    validate_prepared_compiler_arguments(&spec.compiler.arguments)?;

    let parent = path.parent().context("review spec has no parent")?;
    let source_path = verify_declared_file(
        parent,
        &spec.target_binding.source_path,
        &spec.target_binding.source_sha256,
    )?;
    let closure_path = verify_declared_file(
        parent,
        &spec.target_binding.source_closure_manifest_path,
        &spec.target_binding.source_closure_manifest_sha256,
    )?;
    let r1cs_path = verify_declared_file(
        parent,
        &spec.compiled_subject.r1cs_path,
        &spec.compiled_subject.r1cs_sha256,
    )?;
    let sym_path = verify_declared_file(
        parent,
        &spec.compiled_subject.sym_path,
        &spec.compiled_subject.sym_sha256,
    )?;
    let library_path = verify_declared_file(
        parent,
        &spec.compiler.library_manifest_path,
        &spec.compiler.library_manifest_sha256,
    )?;
    let contract_path = verify_declared_file(
        parent,
        &spec.contract.definition_path,
        &spec.contract.definition_sha256,
    )?;
    let predicate_path = verify_declared_file(
        parent,
        &spec.contract.predicate.path,
        &spec.contract.predicate.sha256,
    )?;
    let attribution_path = verify_declared_file(
        parent,
        &spec.attribution.evidence_path,
        &spec.attribution.evidence_sha256,
    )?;
    ensure!(source_path.is_file(), "target source is not a regular file");
    let closure_files = verify_directory_manifest(&closure_path)?;
    ensure!(
        closure_files
            .get(&source_path)
            .is_some_and(|sha256| sha256 == &spec.target_binding.source_sha256),
        "source closure manifest does not contain the bound target source"
    );
    verify_directory_manifest(&library_path)?;

    let modulus = parse_decimal_field(&spec.field.modulus_decimal)?;
    let r1cs = R1cs::parse(&fs::read(&r1cs_path)?)?;
    ensure!(r1cs.prime == modulus, "review-spec field differs from R1CS");
    r1cs.validate_shape(&spec.compiled_subject.expected_shape)?;
    let symbols = SymbolTable::parse(&fs::read(&sym_path)?, &r1cs)?;
    for signal in spec
        .contract
        .input_signal_names
        .iter()
        .chain(spec.contract.property_signal_names.iter())
    {
        ensure!(
            symbols.by_name.contains_key(signal),
            "contract signal is absent from the pinned SYM"
        );
    }
    validate_parameters(&spec.target_binding.concrete_parameters)?;
    validate_predicate_catalog(&spec.contract.predicate)?;
    validate_reachability_reference_shape(&spec.production_reachability)?;

    match (&spec.subject_kind, &spec.injection_ground_truth) {
        (SubjectKind::PublishedVulnerableSource, None) => ensure!(
            spec.attribution.method != AttributionMethod::InjectionSingleDiff,
            "published source cannot use injection attribution"
        ),
        (SubjectKind::InjectedMutant, Some(injection)) => {
            ensure!(
                spec.attribution.method == AttributionMethod::InjectionSingleDiff,
                "injected subject must use injection-single-diff attribution"
            );
            validate_injection_spec(&spec, injection, parent)?;
        }
        _ => bail!("subject_kind and injection_ground_truth disagree"),
    }

    Ok(LoadedSpec {
        report_ref: file_ref_from(report_dir, &path)?,
        spec,
        path,
        sha256: reference.sha256.clone(),
        source_path,
        source_closure: closure_files,
        r1cs_path,
        sym_path,
        contract_path,
        predicate_path,
        attribution_path,
        r1cs,
        symbols,
    })
}

fn validate_parameters(parameters: &[ConcreteParameter]) -> Result<()> {
    let mut names = BTreeSet::new();
    for (position, parameter) in parameters.iter().enumerate() {
        ensure!(
            parameter.position == position,
            "concrete parameter positions must be contiguous"
        );
        ensure!(
            !parameter.name.trim().is_empty() && names.insert(parameter.name.as_str()),
            "concrete parameter names must be nonempty and unique"
        );
        validate_integer_text(&parameter.value_decimal)?;
    }
    Ok(())
}

fn validate_predicate_catalog(predicate: &PredicateSpec) -> Result<()> {
    ensure!(
        !predicate.allowed_results.is_empty(),
        "predicate result catalog is empty"
    );
    let mut results = BTreeSet::new();
    let mut criteria = BTreeSet::new();
    for entry in &predicate.allowed_results {
        ensure!(
            !entry.reason_code.trim().is_empty() && !entry.note.trim().is_empty(),
            "predicate result catalog contains empty text"
        );
        ensure!(
            results.insert((entry.criterion, entry.verdict, entry.reason_code.as_str())),
            "duplicate predicate result catalog entry"
        );
        criteria.insert(entry.criterion);
    }
    ensure!(
        criteria
            == BTreeSet::from([
                PredicateCriterion::InputPreconditions,
                PredicateCriterion::SpecifiedPropertyViolation,
            ]),
        "predicate catalog must cover both criteria"
    );
    ensure_unique_sorted_or_unsorted_names(&predicate.allowed_violation_classes)?;
    Ok(())
}

fn validate_reachability_reference_shape(reachability: &ProductionReachability) -> Result<()> {
    let values_present = [
        reachability.entrypoint_target_id.is_some(),
        reachability.instance_key.is_some(),
        reachability.evidence_path.is_some(),
        reachability.evidence_sha256.is_some(),
        reachability.verifier_manifest_path.is_some(),
        reachability.verifier_manifest_sha256.is_some(),
    ];
    if reachability.verdict == ReachabilityVerdict::Satisfied {
        ensure!(
            values_present.into_iter().all(|value| value),
            "satisfied reachability is missing pinned evidence"
        );
    } else {
        ensure!(
            values_present.into_iter().all(|value| !value),
            "non-satisfied reachability must not carry partial evidence"
        );
    }
    Ok(())
}

fn validate_injection_spec(
    spec: &ReviewSpec,
    injection: &InjectionGroundTruth,
    parent: &Path,
) -> Result<()> {
    ensure!(
        !injection.injection_id.trim().is_empty() && !injection.operator_id.trim().is_empty(),
        "injection IDs must not be empty"
    );
    ensure!(
        matches!(injection.clean_revision.len(), 40 | 64)
            && injection
                .clean_revision
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
        "clean revision must be a full lowercase Git object ID"
    );
    let source_location_path = verify_declared_file(
        parent,
        &injection.source_location.path,
        &injection.source_location.source_sha256,
    )?;
    let source_len = fs::metadata(&source_location_path)?.len() as usize;
    ensure!(
        injection.source_location.start_byte < injection.source_location.end_byte
            && injection.source_location.end_byte <= source_len,
        "injection source byte range is invalid"
    );
    let target_source_path = verify_declared_file(
        parent,
        &spec.target_binding.source_path,
        &spec.target_binding.source_sha256,
    )?;
    ensure!(
        source_location_path == target_source_path
            && injection.source_location.source_sha256 == spec.target_binding.source_sha256,
        "injection source location is not the bound mutant target source"
    );
    let single_diff_path = verify_file_ref_from_parent(parent, &injection.single_diff)?;
    let attribution_path = verify_declared_file(
        parent,
        &spec.attribution.evidence_path,
        &spec.attribution.evidence_sha256,
    )?;
    ensure!(
        single_diff_path == attribution_path
            && injection.single_diff.sha256 == spec.attribution.evidence_sha256,
        "injection attribution evidence is not the pinned single diff"
    );

    let clean_closure_path = verify_file_ref_from_parent(parent, &injection.source_closures.clean)?;
    let mutant_closure_path =
        verify_file_ref_from_parent(parent, &injection.source_closures.mutant)?;
    let twin_closure_path =
        verify_file_ref_from_parent(parent, &injection.source_closures.disturbance_twin)?;
    let target_closure_path = verify_declared_file(
        parent,
        &spec.target_binding.source_closure_manifest_path,
        &spec.target_binding.source_closure_manifest_sha256,
    )?;
    ensure!(
        mutant_closure_path == target_closure_path
            && injection.source_closures.mutant.sha256
                == spec.target_binding.source_closure_manifest_sha256,
        "mutant source closure is not the target-binding source closure"
    );
    let clean_closure = verify_directory_manifest_entries(&clean_closure_path)?;
    let mutant_closure = verify_directory_manifest_entries(&mutant_closure_path)?;
    let twin_closure = verify_directory_manifest_entries(&twin_closure_path)?;
    ensure!(
        clean_closure.keys().eq(mutant_closure.keys())
            && mutant_closure.keys().eq(twin_closure.keys()),
        "injection source closures do not have the same logical file set"
    );
    let target_logical_path = mutant_closure
        .iter()
        .find_map(|(logical_path, entry)| {
            (entry.canonical_path == target_source_path).then_some(logical_path.clone())
        })
        .context("mutant closure does not contain the bound target source")?;
    ensure!(
        changed_manifest_entries(&clean_closure, &mutant_closure)
            == vec![target_logical_path.clone()],
        "clean and mutant closures must differ only at the injected source"
    );
    ensure!(
        changed_manifest_entries(&mutant_closure, &twin_closure) == vec![target_logical_path],
        "mutant and disturbance-twin closures must differ only at the injected source"
    );
    let target_logical_path = mutant_closure
        .iter()
        .find_map(|(logical_path, entry)| {
            (entry.canonical_path == target_source_path).then_some(logical_path)
        })
        .context("mutant closure target source disappeared during validation")?;
    let clean_source = fs::read(&clean_closure[target_logical_path].canonical_path)?;
    let mutant_source = fs::read(&mutant_closure[target_logical_path].canonical_path)?;
    let twin_source = fs::read(&twin_closure[target_logical_path].canonical_path)?;
    let (_, clean_to_mutant_range) = minimal_changed_ranges(&clean_source, &mutant_source);
    let (mutant_to_twin_range, _) = minimal_changed_ranges(&mutant_source, &twin_source);
    ensure!(
        injection.source_location.start_byte <= clean_to_mutant_range.start
            && clean_to_mutant_range.end <= injection.source_location.end_byte
            && injection.source_location.start_byte <= mutant_to_twin_range.start
            && mutant_to_twin_range.end <= injection.source_location.end_byte,
        "source changes escape the declared injection byte range"
    );
    verify_file_ref_from_parent(parent, &injection.projection_manifest)?;
    for variant in [
        &injection.compiled_variants.clean,
        &injection.compiled_variants.mutant,
        &injection.compiled_variants.disturbance_twin,
    ] {
        let r1cs_path = verify_declared_file(parent, &variant.r1cs_path, &variant.r1cs_sha256)?;
        let sym_path = verify_declared_file(parent, &variant.sym_path, &variant.sym_sha256)?;
        let parsed = R1cs::parse(&fs::read(r1cs_path)?)?;
        parsed.validate_shape(&variant.shape)?;
        ensure!(
            parsed.prime == parse_decimal_field(&spec.field.modulus_decimal)?,
            "injection variant uses another field"
        );
        SymbolTable::parse(&fs::read(sym_path)?, &parsed)?;
    }
    verify_file_ref_from_parent(parent, &injection.compilation_manifest)?;
    let mutant = &injection.compiled_variants.mutant;
    ensure!(
        resolve_path(parent, &mutant.r1cs_path)
            == resolve_path(parent, &spec.compiled_subject.r1cs_path)
            && mutant.r1cs_sha256 == spec.compiled_subject.r1cs_sha256
            && resolve_path(parent, &mutant.sym_path)
                == resolve_path(parent, &spec.compiled_subject.sym_path)
            && mutant.sym_sha256 == spec.compiled_subject.sym_sha256
            && mutant.shape == spec.compiled_subject.expected_shape,
        "compiled_subject must be the injected mutant"
    );
    ensure_sorted_unique(&injection.expected_clean_constraint_indices)?;
    ensure!(
        !injection.expected_clean_constraint_indices.is_empty(),
        "expected clean constraint set is empty"
    );
    ensure!(
        injection.clean_relation_exclusion.method
            == match injection.clean_relation_exclusion.method {
                RelationExclusionMethod::FullyFixedConstraint => {
                    RelationExclusionMethod::FullyFixedConstraint
                }
                RelationExclusionMethod::OperatorProof => RelationExclusionMethod::OperatorProof,
                RelationExclusionMethod::SolverUnsatCertificate => {
                    RelationExclusionMethod::SolverUnsatCertificate
                }
            },
        "invalid relation exclusion method"
    );
    verify_declared_file(
        parent,
        &injection.clean_relation_exclusion.certificate_path,
        &injection.clean_relation_exclusion.certificate_sha256,
    )?;
    verify_declared_file(
        parent,
        &injection.clean_relation_exclusion.verifier_manifest_path,
        &injection.clean_relation_exclusion.verifier_manifest_sha256,
    )?;
    Ok(())
}

fn verify_qualification_engine_provenance(
    report_parent: &Path,
    reported: &EngineProvenance,
    current_parent: &Path,
    current: &EngineProvenance,
) -> Result<()> {
    ensure!(
        reported.version == ENGINE_VERSION
            && reported.version == current.version
            && !reported.source_revision.trim().is_empty()
            && reported.source_revision == current.source_revision
            && reported.source_manifest_sha256 == current.source_manifest_sha256
            && reported.executable_sha256 == current.executable_sha256
            && reported.predicate_runner_sha256 == current.predicate_runner_sha256,
        "qualification report uses different review-engine provenance"
    );
    let reported_manifest = verify_declared_file(
        report_parent,
        &reported.source_manifest_path,
        &reported.source_manifest_sha256,
    )?;
    verify_declared_file(
        current_parent,
        &current.source_manifest_path,
        &current.source_manifest_sha256,
    )?;
    let sources = verify_directory_manifest(&reported_manifest)?;
    verify_engine_source_manifest(&sources)?;
    verify_declared_file(
        report_parent,
        &reported.executable_path,
        &reported.executable_sha256,
    )?;
    verify_declared_file(
        report_parent,
        &reported.predicate_runner_path,
        &reported.predicate_runner_sha256,
    )?;
    verify_declared_file(
        current_parent,
        &current.executable_path,
        &current.executable_sha256,
    )?;
    verify_declared_file(
        current_parent,
        &current.predicate_runner_path,
        &current.predicate_runner_sha256,
    )?;
    Ok(())
}

fn verify_criterion_evidence(parent: &Path, criterion: Option<&Criterion>) -> Result<()> {
    if let Some(criterion) = criterion {
        for evidence in &criterion.evidence {
            verify_file_ref_from_parent(parent, evidence)?;
        }
    }
    Ok(())
}

fn verify_qualification_review_file_refs(parent: &Path, review: &InjectionReview) -> Result<()> {
    verify_file_ref_from_parent(parent, &review.assignments.disturbance)?;
    verify_file_ref_from_parent(parent, &review.assignments.clean_reference)?;
    verify_declared_file(parent, &review.review_spec.path, &review.review_spec.sha256)?;
    for criterion in [
        review.criteria.assignment_encoding.as_ref(),
        review.criteria.input_preconditions.as_ref(),
        review.criteria.fixed_target_constraints.as_ref(),
        review.criteria.specified_property_violation.as_ref(),
        review.qualification_criteria.twin_r1cs_identity.as_ref(),
        review.qualification_criteria.twin_sym_identity.as_ref(),
        review
            .qualification_criteria
            .generation_reproducibility
            .as_ref(),
        review
            .qualification_criteria
            .clean_reference_assignment_encoding
            .as_ref(),
        review
            .qualification_criteria
            .clean_reference_constraints
            .as_ref(),
        review
            .qualification_criteria
            .clean_input_equivalence
            .as_ref(),
        review.qualification_criteria.clean_rejection.as_ref(),
        review
            .qualification_criteria
            .clean_relation_exclusion
            .as_ref(),
        review
            .qualification_criteria
            .production_reachability
            .as_ref(),
    ] {
        verify_criterion_evidence(parent, criterion)?;
    }
    for evidence in &review.cause_attribution.evidence {
        verify_file_ref_from_parent(parent, evidence)?;
    }
    Ok(())
}

fn replay_review_projection(review: &InjectionReview) -> Result<Value> {
    fn strip_runtime_locations(value: Value) -> Value {
        match value {
            Value::Array(values) => {
                Value::Array(values.into_iter().map(strip_runtime_locations).collect())
            }
            Value::Object(values) => Value::Object(
                values
                    .into_iter()
                    .filter_map(|(key, value)| {
                        (!matches!(key.as_str(), "path" | "automated_review_seconds"))
                            .then(|| (key, strip_runtime_locations(value)))
                    })
                    .collect(),
            ),
            other => other,
        }
    }
    Ok(strip_runtime_locations(serde_json::to_value(review)?))
}

fn verify_qualification_bundles(
    request: &BackendRequest,
    request_path: &Path,
    report_dir: &Path,
    engine: &EngineProvenance,
    python_bin: &Path,
    expected_qualifications: &BTreeMap<String, String>,
) -> Result<BTreeMap<String, VerifiedQualification>> {
    let mut requested_qualifications = BTreeMap::new();
    for reference in &request.qualification_bundles {
        ensure!(
            requested_qualifications
                .insert(reference.injection_id.clone(), reference.sha256.clone())
                .is_none(),
            "duplicate qualification injection_id"
        );
    }
    ensure!(
        requested_qualifications
            .keys()
            .eq(expected_qualifications.keys()),
        "qualification bundle set differs from injected backend specs"
    );

    let mut result = BTreeMap::new();
    for reference in &request.qualification_bundles {
        validate_hex(&reference.sha256)?;
        let path = resolve_path(
            request_path.parent().context("request has no parent")?,
            &reference.path,
        );
        ensure!(path.is_file(), "qualification bundle is unavailable");
        ensure!(
            sha256_file(&path)? == reference.sha256,
            "qualification bundle hash mismatch"
        );
        let index: GroundTruthBundleIndex = serde_json::from_slice(&fs::read(&path)?)
            .context("parse strict ground-truth bundle index")?;
        ensure!(
            index.schema_version == 1
                && index.kind == "injection-ground-truth"
                && index.injection_id == reference.injection_id
                && index.qualification == GroundTruthQualification::Qualified,
            "qualification bundle is not a qualified matching injection"
        );
        let index_parent = path.parent().context("qualification index has no parent")?;
        let spec_path = verify_file_ref_from_parent(index_parent, &index.review_spec)?;
        ensure!(
            expected_qualifications
                .get(&reference.injection_id)
                .is_some_and(|sha256| sha256 == &index.review_spec.sha256),
            "qualification bundle points to a spec outside the backend request"
        );
        let qualification_request_path =
            verify_file_ref_from_parent(index_parent, &index.review_request)?;
        let report_path = verify_file_ref_from_parent(index_parent, &index.review_report)?;
        let qualification_spec: ReviewSpec = serde_json::from_slice(&fs::read(&spec_path)?)
            .context("parse qualification review spec")?;
        let qualification_injection = qualification_spec
            .injection_ground_truth
            .as_ref()
            .context("qualification spec has no injection ground truth")?;
        ensure!(
            qualification_spec.schema_version == 1
                && qualification_injection.injection_id == reference.injection_id,
            "qualification spec injection binding mismatch"
        );
        let qualification_request: ReviewRequest =
            serde_json::from_slice(&fs::read(&qualification_request_path)?)
                .context("parse qualification review request")?;
        let ReviewRequest::Injection(qualification_request) = qualification_request else {
            bail!("qualification index points to a backend request");
        };
        let request_spec_path = verify_file_ref(
            &qualification_request_path,
            &qualification_request.review_spec,
        )?;
        ensure!(
            request_spec_path == spec_path
                && qualification_request.review_spec.sha256 == index.review_spec.sha256,
            "qualification request points to another spec"
        );
        let report: ReviewReport = serde_json::from_slice(&fs::read(&report_path)?)
            .context("parse strict qualification report")?;
        let report_parent = report_path
            .parent()
            .context("qualification report has no parent")?;
        let report_request_path =
            verify_file_ref_from_parent(report_parent, &report.review_request)?;
        let report_spec_paths = report
            .review_specs
            .iter()
            .map(|item| {
                Ok((
                    verify_file_ref_from_parent(report_parent, item)?,
                    item.sha256.as_str(),
                ))
            })
            .collect::<Result<Vec<_>>>()?;
        ensure!(
            report.schema_version == 1
                && report.report_id == qualification_request.request_id
                && report.kind == ReportKind::InjectionGroundTruth
                && report.status == ReportStatus::Complete
                && report.failure.is_none()
                && !report.raw_values_persisted
                && report.candidate_inventory.is_none()
                && report.executions.is_empty()
                && report.candidate_errors.is_empty()
                && report.unreviewed_candidates.is_empty()
                && report_request_path == qualification_request_path
                && report.review_request.sha256 == index.review_request.sha256
                && report_spec_paths.len() == 1
                && report_spec_paths[0].0 == spec_path
                && report_spec_paths[0].1 == index.review_spec.sha256
                && matches!(
                    report.reviews.as_slice(),
                    [ReviewRecord::Injection(review)]
                        if review.ground_truth_qualification == GroundTruthQualification::Qualified
                            && review.injection_id == reference.injection_id
                            && review.review_spec.sha256 == index.review_spec.sha256
                            && review.review_spec.id == qualification_spec.review_spec_id
                            && review.candidate_record_id.is_none()
                            && review.candidate.is_none()
                            && review.binding.is_none()
                ),
            "qualification report is not a completed qualification"
        );
        let [ReviewRecord::Injection(qualification_review)] = report.reviews.as_slice() else {
            unreachable!("the completed-qualification shape was checked above")
        };
        let common_criteria = [
            qualification_review.criteria.assignment_encoding.as_ref(),
            qualification_review.criteria.input_preconditions.as_ref(),
            qualification_review
                .criteria
                .fixed_target_constraints
                .as_ref(),
            qualification_review
                .criteria
                .specified_property_violation
                .as_ref(),
        ];
        let qualification_criteria = [
            qualification_review
                .qualification_criteria
                .twin_r1cs_identity
                .as_ref(),
            qualification_review
                .qualification_criteria
                .twin_sym_identity
                .as_ref(),
            qualification_review
                .qualification_criteria
                .generation_reproducibility
                .as_ref(),
            qualification_review
                .qualification_criteria
                .clean_reference_assignment_encoding
                .as_ref(),
            qualification_review
                .qualification_criteria
                .clean_reference_constraints
                .as_ref(),
            qualification_review
                .qualification_criteria
                .clean_input_equivalence
                .as_ref(),
            qualification_review
                .qualification_criteria
                .clean_rejection
                .as_ref(),
            qualification_review
                .qualification_criteria
                .clean_relation_exclusion
                .as_ref(),
            qualification_review
                .qualification_criteria
                .production_reachability
                .as_ref(),
        ];
        ensure!(
            qualification_review.disposition == Disposition::Validated
                && qualification_review.cause_attribution.verdict == AttributionVerdict::Matched
                && !qualification_review.confirmation_eligible
                && common_criteria.iter().all(|criterion| {
                    criterion
                        .is_some_and(|criterion| criterion.verdict == CriterionVerdict::Satisfied)
                })
                && qualification_criteria.iter().all(|criterion| {
                    criterion
                        .is_some_and(|criterion| criterion.verdict == CriterionVerdict::Satisfied)
                })
                && matches!(
                    &report.summary,
                    ReviewSummary::Injection(summary)
                        if summary.validated == 1
                            && summary.rejected == 0
                            && summary.unresolved == 0
                            && summary.review_error == 0
                            && summary.qualified == 1
                ),
            "qualification report invariants do not describe one qualified ground truth"
        );
        ensure!(
            semantic_result_sha256(&report, &index.review_request.sha256)?
                == report.semantic_result_sha256,
            "qualification report semantic digest mismatch"
        );
        verify_qualification_engine_provenance(report_parent, &report.engine, report_dir, engine)?;
        let expected_adapters =
            request_adapters(&ReviewRequest::Injection(qualification_request.clone()));
        ensure!(
            report.adapters == expected_adapters,
            "qualification report adapters differ from its request"
        );
        verify_qualification_review_file_refs(report_parent, qualification_review)?;

        let replay_request_ref = file_ref_from(report_dir, &qualification_request_path)?;
        let (replay_report, replay_backend, replay_context) = build_injection_report(
            &qualification_request,
            &qualification_request_path,
            &replay_request_ref,
            report_dir,
            engine,
            python_bin,
        )?;
        ensure!(
            replay_backend.is_none()
                && replay_context.is_some_and(|context| {
                    context.qualification == GroundTruthQualification::Qualified
                        && context.injection_id == reference.injection_id
                        && context.spec.sha256 == index.review_spec.sha256
                })
                && replay_report.status == ReportStatus::Complete
                && replay_report.failure.is_none(),
            "qualification replay did not reproduce a qualified result"
        );
        let [ReviewRecord::Injection(replay_review)] = replay_report.reviews.as_slice() else {
            bail!("qualification replay did not produce exactly one injection review")
        };
        ensure!(
            replay_review.ground_truth_qualification == GroundTruthQualification::Qualified
                && replay_review_projection(qualification_review)?
                    == replay_review_projection(replay_review)?,
            "qualification report differs from current-engine replay"
        );
        ensure!(
            serde_json::to_value(&report.summary)? == serde_json::to_value(&replay_report.summary)?,
            "qualification report summary differs from current-engine replay"
        );
        ensure!(
            result
                .insert(
                    reference.injection_id.clone(),
                    VerifiedQualification {
                        index_path: path,
                        index_sha256: reference.sha256.clone(),
                        spec_sha256: sha256_file(&spec_path)?,
                    },
                )
                .is_none(),
            "duplicate qualification injection_id"
        );
    }
    Ok(result)
}

fn validate_outcome_structure(
    plan: &ExperimentPlan,
    plan_bytes: &[u8],
    outcome: &ExperimentOutcome,
) -> Result<()> {
    ensure!(outcome.schema_version == 1, "unsupported outcome schema");
    ensure!(
        outcome.plan_id == plan.plan_id
            && outcome.strategy == plan.strategy
            && outcome.plan_sha256 == sha256_bytes(plan_bytes),
        "outcome plan binding mismatch"
    );
    ensure!(
        outcome.scheduler.scheduler == "uniform-ordered",
        "outcome does not use the ordered scheduler"
    );
    let expected = plan
        .targets
        .iter()
        .map(|target| target.target_id.as_str())
        .collect::<Vec<_>>();
    ensure!(
        outcome
            .scheduler
            .planned_target_ids
            .iter()
            .map(String::as_str)
            .eq(expected.iter().copied()),
        "outcome planned order differs from plan"
    );
    ensure!(
        outcome.budget_seconds_per_target == outcome.scheduler.budget_seconds_per_target
            && outcome.total_budget_seconds == outcome.scheduler.total_budget_seconds,
        "outcome scheduler budgets disagree"
    );
    let mut accounted = BTreeSet::new();
    let mut run_ids = BTreeSet::new();
    let mut previous_run = None;
    for run in &outcome.scheduler.runs {
        ensure!(
            run.index < expected.len() && run.target_id == expected[run.index],
            "run target/index differs from plan"
        );
        ensure!(accounted.insert(run.index), "duplicate target accounting");
        ensure!(
            previous_run.is_none_or(|previous| previous < run.index),
            "run rows are not in plan order"
        );
        previous_run = Some(run.index);
        ensure!(
            run_ids.insert(run.result.run_id.as_str()),
            "duplicate backend run ID"
        );
    }
    for failure in &outcome.scheduler.failures {
        ensure!(
            failure.index < expected.len() && failure.target_id == expected[failure.index],
            "runner failure target/index differs from plan"
        );
        ensure!(
            accounted.insert(failure.index),
            "duplicate target accounting"
        );
    }
    for skipped in &outcome.scheduler.skipped {
        ensure!(
            skipped.index < expected.len() && skipped.target_id == expected[skipped.index],
            "skipped target/index differs from plan"
        );
        ensure!(
            accounted.insert(skipped.index),
            "duplicate target accounting"
        );
    }
    ensure!(
        accounted.len() == expected.len(),
        "outcome does not account for every plan target"
    );
    let runs = outcome
        .scheduler
        .runs
        .iter()
        .map(|run| (run.result.run_id.as_str(), run))
        .collect::<BTreeMap<_, _>>();
    let mut artifact_keys = BTreeSet::new();
    for artifact in &outcome.counterexample_candidates {
        validate_hex(&artifact.sha256)?;
        let run = runs
            .get(artifact.run_id.as_str())
            .context("candidate references an unknown run")?;
        ensure!(
            run.target_id == artifact.target_id && run.result.status == RunStatus::BugFound,
            "candidate is not attached to its bug_found run/target"
        );
        ensure!(
            artifact.classification == "backend-counterexample-candidate-unconfirmed",
            "unsupported candidate classification"
        );
        ensure!(
            artifact_keys.insert((artifact.run_id.as_str(), artifact.preserved_path.as_path())),
            "duplicate candidate artifact record"
        );
    }
    Ok(())
}

fn backend_summary(reviews: &[ReviewRecord], unreviewed: usize) -> BackendSummary {
    let backend = reviews.iter().filter_map(|record| match record {
        ReviewRecord::Backend(review) => Some(review),
        ReviewRecord::Injection(_) => None,
    });
    let rows = backend.collect::<Vec<_>>();
    let roots = rows
        .iter()
        .filter(|review| {
            review.disposition == Disposition::Validated
                && review.cause_attribution.verdict == AttributionVerdict::Matched
        })
        .map(|review| review.root_cause_id.as_str())
        .collect::<BTreeSet<_>>();
    BackendSummary {
        validated: rows
            .iter()
            .filter(|review| review.disposition == Disposition::Validated)
            .count(),
        rejected: rows
            .iter()
            .filter(|review| review.disposition == Disposition::Rejected)
            .count(),
        unresolved: rows
            .iter()
            .filter(|review| review.disposition == Disposition::Unresolved)
            .count(),
        review_error: rows
            .iter()
            .filter(|review| review.disposition == Disposition::ReviewError)
            .count(),
        unreviewed_candidates: unreviewed,
        attributed_validated: rows
            .iter()
            .filter(|review| {
                review.disposition == Disposition::Validated
                    && review.cause_attribution.verdict == AttributionVerdict::Matched
            })
            .count(),
        unique_validated_root_causes: roots.len(),
    }
}

fn review_sort_key(left: &ReviewRecord, right: &ReviewRecord) -> std::cmp::Ordering {
    fn key(review: &ReviewRecord) -> (&str, &str) {
        match review {
            ReviewRecord::Backend(row) => (&row.candidate_record_id, &row.review_spec.sha256),
            ReviewRecord::Injection(row) => (&row.injection_id, &row.review_spec.sha256),
        }
    }
    key(left).cmp(&key(right))
}

fn request_adapters(request: &ReviewRequest) -> Vec<AdapterProvenance> {
    match request {
        ReviewRequest::Backend(request) => vec![AdapterProvenance {
            id: request.candidate_adapter.id.clone(),
            implementation_sha256: request.candidate_adapter.implementation_sha256.clone(),
        }],
        ReviewRequest::Injection(request) => {
            let mut adapters = vec![
                AdapterProvenance {
                    id: assignment_adapter_id(request.disturbance_assignment.format).to_owned(),
                    implementation_sha256: request
                        .disturbance_assignment
                        .adapter_implementation_sha256
                        .clone(),
                },
                AdapterProvenance {
                    id: assignment_adapter_id(request.clean_reference_assignment.format).to_owned(),
                    implementation_sha256: request
                        .clean_reference_assignment
                        .adapter_implementation_sha256
                        .clone(),
                },
            ];
            adapters.sort_by(|left, right| {
                (&left.id, &left.implementation_sha256)
                    .cmp(&(&right.id, &right.implementation_sha256))
            });
            adapters.dedup_by(|left, right| {
                left.id == right.id && left.implementation_sha256 == right.implementation_sha256
            });
            adapters
        }
    }
}

fn stable_shared_failure_code(_error: &anyhow::Error) -> String {
    "shared-input-invalid".to_owned()
}

fn run_status_name(status: &RunStatus) -> &'static str {
    match status {
        RunStatus::BugFound => "bug_found",
        RunStatus::NoCounterexample => "no_counterexample",
        RunStatus::Timeout => "timeout",
        RunStatus::CompileError => "compile_error",
        RunStatus::RuntimeError => "runtime_error",
        RunStatus::ParseError => "parse_error",
        RunStatus::SpawnError => "spawn_error",
        RunStatus::Unknown => "unknown",
    }
}

fn parse_decimal_field(text: &str) -> Result<BigUint> {
    ensure!(
        text == "0" || (!text.starts_with('0') && text.bytes().all(|byte| byte.is_ascii_digit())),
        "field value is not canonical unsigned decimal text"
    );
    BigUint::parse_bytes(text.as_bytes(), 10).context("invalid decimal field value")
}

fn parse_assignment_field(text: &str) -> Result<(BigUint, bool)> {
    ensure!(
        !text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit()),
        "field assignment is not unsigned decimal text"
    );
    let value =
        BigUint::parse_bytes(text.as_bytes(), 10).context("invalid decimal field assignment")?;
    let canonical_text = text == "0" || !text.starts_with('0');
    Ok((value, canonical_text))
}

fn validate_integer_text(text: &str) -> Result<()> {
    let digits = text.strip_prefix('-').unwrap_or(text);
    ensure!(
        !digits.is_empty()
            && (digits == "0"
                || (!digits.starts_with('0') && digits.bytes().all(|byte| byte.is_ascii_digit()))),
        "integer parameter is not canonical decimal text"
    );
    ensure!(text != "-0", "integer parameter must not use negative zero");
    Ok(())
}

fn validate_hex(value: &str) -> Result<()> {
    ensure!(
        value.len() == 64
            && value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
        "SHA-256 must be lowercase 64-character hexadecimal"
    );
    Ok(())
}

fn ensure_unique_sorted_or_unsorted_names(values: &[String]) -> Result<()> {
    let unique = values.iter().collect::<BTreeSet<_>>();
    ensure!(
        unique.len() == values.len(),
        "duplicate string in fixed list"
    );
    ensure!(
        values.iter().all(|value| !value.trim().is_empty()),
        "empty string in fixed list"
    );
    Ok(())
}

fn ensure_sorted_unique<T: Ord>(values: &[T]) -> Result<()> {
    ensure!(
        values.windows(2).all(|pair| pair[0] < pair[1]),
        "list must be sorted and unique"
    );
    Ok(())
}

fn implementation_hash(description: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(REVIEW_ENGINE_SOURCE.as_bytes());
    hasher.update(b"\0");
    hasher.update(description.as_bytes());
    format!("{:x}", hasher.finalize())
}

fn assignment_adapter_id(format: AssignmentFormat) -> &'static str {
    match format {
        AssignmentFormat::ZkfuzzAssignmentV1 => ZKFUZZ_ASSIGNMENT_ADAPTER_ID,
        AssignmentFormat::WtnsJsonV1 => WTNS_JSON_ADAPTER_ID,
    }
}

fn expected_assignment_adapter_hash(format: AssignmentFormat) -> String {
    match format {
        AssignmentFormat::ZkfuzzAssignmentV1 => {
            implementation_hash(ZKFUZZ_ASSIGNMENT_ADAPTER_DESCRIPTION)
        }
        AssignmentFormat::WtnsJsonV1 => implementation_hash(WTNS_JSON_ADAPTER_DESCRIPTION),
    }
}

fn sha256_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn sha256_file(path: &Path) -> Result<String> {
    Ok(sha256_bytes(
        &fs::read(path).with_context(|| format!("read {}", path.display()))?,
    ))
}

fn resolve_executable(program: &Path) -> Result<PathBuf> {
    let has_directory_component = program.is_absolute() || program.components().count() > 1;
    let resolved = if has_directory_component {
        program.to_path_buf()
    } else {
        let path = std::env::var_os("PATH").context("PATH is unavailable")?;
        std::env::split_paths(&path)
            .map(|directory| directory.join(program))
            .find(|candidate| candidate.is_file())
            .with_context(|| format!("executable {} is absent from PATH", program.display()))?
    };
    ensure!(
        resolved.is_file(),
        "executable is unavailable: {}",
        resolved.display()
    );
    Ok(fs::canonicalize(resolved)?)
}

fn resolve_review_executable(declared: &Path) -> Result<PathBuf> {
    let declared = fs::canonicalize(declared)
        .with_context(|| format!("resolve review executable {}", declared.display()))?;
    ensure!(declared.is_file(), "review executable is not a file");
    let current =
        fs::canonicalize(std::env::current_exe().context("resolve current review executable")?)
            .context("canonicalize current review executable")?;
    ensure!(
        declared == current,
        "declared review executable does not match the running executable"
    );
    Ok(current)
}

fn verify_file_ref(declaring_path: &Path, reference: &FileRef) -> Result<PathBuf> {
    let parent = declaring_path
        .parent()
        .context("declaring JSON has no parent")?;
    verify_file_ref_from_parent(parent, reference)
}

fn verify_file_ref_from_parent(parent: &Path, reference: &FileRef) -> Result<PathBuf> {
    validate_hex(&reference.sha256)?;
    verify_declared_file(parent, &reference.path, &reference.sha256)
}

fn verify_declared_file(parent: &Path, path: &Path, expected_sha256: &str) -> Result<PathBuf> {
    validate_hex(expected_sha256)?;
    let resolved = resolve_path(parent, path);
    ensure!(
        resolved.is_file(),
        "referenced file is unavailable: {}",
        resolved.display()
    );
    ensure!(
        sha256_file(&resolved)? == expected_sha256,
        "referenced file hash mismatch: {}",
        resolved.display()
    );
    Ok(fs::canonicalize(resolved)?)
}

fn verify_directory_manifest(path: &Path) -> Result<BTreeMap<PathBuf, String>> {
    Ok(verify_directory_manifest_entries(path)?
        .into_values()
        .map(|entry| (entry.canonical_path, entry.sha256))
        .collect())
}

fn require_manifest_source(
    files: &BTreeMap<PathBuf, String>,
    file_name: &str,
    source: &[u8],
) -> Result<()> {
    let matches = files
        .iter()
        .filter(|(path, _)| path.file_name().is_some_and(|name| name == file_name))
        .collect::<Vec<_>>();
    ensure!(
        matches.len() == 1 && matches[0].1 == &sha256_bytes(source),
        "source manifest does not bind the current {file_name} implementation"
    );
    Ok(())
}

fn verify_engine_source_manifest(files: &BTreeMap<PathBuf, String>) -> Result<()> {
    for (file_name, source) in [
        ("engine.rs", REVIEW_ENGINE_SOURCE.as_bytes()),
        ("experiment.rs", REVIEW_EXPERIMENT_SOURCE.as_bytes()),
        ("predicate.rs", REVIEW_PREDICATE_SOURCE.as_bytes()),
        ("r1cs.rs", REVIEW_R1CS_SOURCE.as_bytes()),
        ("schema.rs", REVIEW_SCHEMA_SOURCE.as_bytes()),
        ("subprocess.rs", REVIEW_SUBPROCESS_SOURCE.as_bytes()),
        ("structure.rs", REVIEW_STRUCTURE_SOURCE.as_bytes()),
        ("targets.rs", TARGET_DISCOVERY_SOURCE.as_bytes()),
    ] {
        require_manifest_source(files, file_name, source)?;
    }
    Ok(())
}

fn verify_directory_manifest_entries(
    path: &Path,
) -> Result<BTreeMap<PathBuf, VerifiedManifestEntry>> {
    let manifest: DirectoryManifest = serde_json::from_slice(&fs::read(path)?)
        .with_context(|| format!("parse strict directory manifest {}", path.display()))?;
    ensure!(
        manifest.schema_version == 1,
        "unsupported directory manifest"
    );
    ensure!(!manifest.files.is_empty(), "directory manifest is empty");
    let parent = path.parent().context("directory manifest has no parent")?;
    let mut previous: Option<&Path> = None;
    let mut verified = BTreeMap::new();
    for entry in &manifest.files {
        ensure!(
            !entry.path.is_absolute(),
            "directory manifest paths must be relative"
        );
        if let Some(previous) = previous {
            ensure!(
                previous < entry.path.as_path(),
                "directory manifest paths must be sorted and unique"
            );
        }
        previous = Some(&entry.path);
        validate_hex(&entry.sha256)?;
        let resolved = resolve_path(parent, &entry.path);
        ensure!(resolved.is_file(), "directory manifest file is unavailable");
        ensure!(
            fs::metadata(&resolved)?.len() == entry.size,
            "directory manifest file size mismatch"
        );
        ensure!(
            sha256_file(&resolved)? == entry.sha256,
            "directory manifest file hash mismatch"
        );
        verified.insert(
            entry.path.clone(),
            VerifiedManifestEntry {
                canonical_path: fs::canonicalize(resolved)?,
                sha256: entry.sha256.clone(),
            },
        );
    }
    Ok(verified)
}

fn changed_manifest_entries(
    left: &BTreeMap<PathBuf, VerifiedManifestEntry>,
    right: &BTreeMap<PathBuf, VerifiedManifestEntry>,
) -> Vec<PathBuf> {
    left.iter()
        .filter_map(|(logical_path, left_entry)| {
            right
                .get(logical_path)
                .is_none_or(|right_entry| right_entry.sha256 != left_entry.sha256)
                .then_some(logical_path.clone())
        })
        .collect()
}

fn minimal_changed_ranges(left: &[u8], right: &[u8]) -> (Range<usize>, Range<usize>) {
    let prefix = left
        .iter()
        .zip(right)
        .take_while(|(left, right)| left == right)
        .count();
    let remaining = left.len().min(right.len()).saturating_sub(prefix);
    let suffix = left[prefix..]
        .iter()
        .rev()
        .zip(right[prefix..].iter().rev())
        .take(remaining)
        .take_while(|(left, right)| left == right)
        .count();
    (
        prefix..left.len().saturating_sub(suffix),
        prefix..right.len().saturating_sub(suffix),
    )
}

fn resolve_path(parent: &Path, path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        parent.join(path)
    }
}

fn file_ref_from(relative_to: &Path, path: &Path) -> Result<FileRef> {
    let path = fs::canonicalize(path)?;
    Ok(FileRef {
        path: relative_path(relative_to, &path)?,
        sha256: sha256_file(&path)?,
    })
}

fn relative_path(from_directory: &Path, to: &Path) -> Result<PathBuf> {
    let from = fs::canonicalize(from_directory)?;
    let to = fs::canonicalize(to)?;
    relative_components(&from, &to)
}

fn relative_path_allow_missing(from_directory: &Path, to: &Path) -> Result<PathBuf> {
    let from = fs::canonicalize(from_directory)?;
    let to = fs::canonicalize(to).unwrap_or_else(|_| normalize_lexical_path(to));
    ensure!(
        to.is_absolute(),
        "recorded artifact path must resolve absolutely"
    );
    relative_components(&from, &to)
}

fn normalize_lexical_path(path: &Path) -> PathBuf {
    let mut result = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                if !result.pop() && !path.is_absolute() {
                    result.push("..");
                }
            }
            Component::Prefix(prefix) => result.push(prefix.as_os_str()),
            Component::RootDir => result.push(component.as_os_str()),
            Component::Normal(value) => result.push(value),
        }
    }
    result
}

fn relative_components(from: &Path, to: &Path) -> Result<PathBuf> {
    let from_components = from.components().collect::<Vec<_>>();
    let to_components = to.components().collect::<Vec<_>>();
    let common = from_components
        .iter()
        .zip(&to_components)
        .take_while(|(left, right)| left == right)
        .count();
    ensure!(common > 0, "paths do not share a filesystem root");
    let mut result = PathBuf::new();
    for component in &from_components[common..] {
        if matches!(component, Component::Normal(_)) {
            result.push("..");
        }
    }
    for component in &to_components[common..] {
        result.push(component.as_os_str());
    }
    if result.as_os_str().is_empty() {
        result.push(".");
    }
    Ok(result)
}

fn write_json_new<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    ensure!(!path.exists(), "refusing to overwrite {}", path.display());
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut bytes = serde_json::to_vec_pretty(value)?;
    bytes.push(b'\n');
    fs::write(path, bytes).with_context(|| format!("write {}", path.display()))
}

fn semantic_result_sha256(report: &ReviewReport, request_sha256: &str) -> Result<String> {
    let mut spec_sha256s = report
        .review_specs
        .iter()
        .map(|reference| Value::String(reference.sha256.clone()))
        .collect::<Vec<_>>();
    spec_sha256s.sort_by(|left, right| left.as_str().cmp(&right.as_str()));
    let mut adapters = report.adapters.clone();
    adapters.sort_by(|left, right| {
        (&left.id, &left.implementation_sha256).cmp(&(&right.id, &right.implementation_sha256))
    });
    let mut projection = Map::new();
    projection.insert("schema_version".to_owned(), Value::from(1));
    projection.insert("kind".to_owned(), serde_json::to_value(report.kind)?);
    projection.insert(
        "request_sha256".to_owned(),
        Value::String(request_sha256.to_owned()),
    );
    projection.insert("spec_sha256s".to_owned(), Value::Array(spec_sha256s));
    projection.insert(
        "engine".to_owned(),
        json!({
            "source_manifest_sha256": report.engine.source_manifest_sha256,
            "executable_sha256": report.engine.executable_sha256,
            "predicate_runner_sha256": report.engine.predicate_runner_sha256,
        }),
    );
    projection.insert("adapters".to_owned(), serde_json::to_value(adapters)?);
    projection.insert(
        "candidate_inventory".to_owned(),
        semanticize(serde_json::to_value(&report.candidate_inventory)?),
    );
    projection.insert(
        "executions".to_owned(),
        semanticize(serde_json::to_value(&report.executions)?),
    );
    projection.insert(
        "candidate_errors".to_owned(),
        semanticize(serde_json::to_value(&report.candidate_errors)?),
    );
    projection.insert(
        "unreviewed_candidates".to_owned(),
        semanticize(serde_json::to_value(&report.unreviewed_candidates)?),
    );
    projection.insert(
        "reviews".to_owned(),
        semanticize(serde_json::to_value(&report.reviews)?),
    );
    let mut canonical = String::new();
    write_jcs(&Value::Object(projection), &mut canonical)?;
    Ok(sha256_bytes(canonical.as_bytes()))
}

fn semanticize(value: Value) -> Value {
    match value {
        Value::Array(values) => Value::Array(values.into_iter().map(semanticize).collect()),
        Value::Object(values) => {
            let mut result = Map::new();
            for (key, value) in values {
                if matches!(
                    key.as_str(),
                    "path" | "automated_review_seconds" | "note" | "semantic_result_sha256"
                ) {
                    continue;
                }
                let mut semantic = semanticize(value);
                if matches!(
                    key.as_str(),
                    "failed_target_constraint_indices"
                        | "failed_clean_constraint_indices"
                        | "checked_clean_constraint_indices"
                ) {
                    if let Value::Array(entries) = &mut semantic {
                        entries.sort_by_key(|entry| {
                            entry
                                .as_u64()
                                .expect("constraint index projection must contain integers")
                        });
                        entries.dedup();
                    }
                } else if matches!(key.as_str(), "fixed_signal_names" | "evidence") {
                    if let Value::Array(entries) = &mut semantic {
                        entries.sort_by(|left, right| {
                            canonical_json_sort_key(left).cmp(&canonical_json_sort_key(right))
                        });
                        entries.dedup();
                    }
                }
                result.insert(key, semantic);
            }
            Value::Object(result)
        }
        other => other,
    }
}

fn canonical_json_sort_key(value: &Value) -> String {
    let mut output = String::new();
    write_jcs(value, &mut output).expect("semantic values contain only supported JSON numbers");
    output
}

fn write_jcs(value: &Value, output: &mut String) -> Result<()> {
    match value {
        Value::Null => output.push_str("null"),
        Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
        Value::Number(number) => {
            ensure!(
                number.is_i64() || number.is_u64(),
                "semantic projection must not contain floats"
            );
            output.push_str(&number.to_string());
        }
        Value::String(value) => output.push_str(&serde_json::to_string(value)?),
        Value::Array(values) => {
            output.push('[');
            for (index, value) in values.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                write_jcs(value, output)?;
            }
            output.push(']');
        }
        Value::Object(values) => {
            output.push('{');
            let sorted = values.iter().collect::<BTreeMap<_, _>>();
            for (index, (key, value)) in sorted.into_iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                output.push_str(&serde_json::to_string(key)?);
                output.push(':');
                write_jcs(value, output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

fn write_backend_outputs(
    request: &BackendRequest,
    request_path: &Path,
    report: &ReviewReport,
    report_path: &Path,
    context: &BackendOutputContext,
    output_dir: &Path,
) -> Result<PathBuf> {
    let confirmation_dir = output_dir.join("confirmations");
    let evaluation_dir = output_dir.join("evaluations");
    fs::create_dir(&confirmation_dir)?;
    fs::create_dir(&evaluation_dir)?;
    let mut execution_evaluations = Vec::new();
    let mut by_execution = Vec::new();
    let mut campaign_roots = BTreeSet::new();

    for execution in &context.executions {
        let safe_id = safe_execution_name(&execution.request.execution_id);
        let confirmation_path = confirmation_dir.join(format!("{safe_id}.schema2.json"));
        let evaluation_path = evaluation_dir.join(format!("{safe_id}.json"));
        let mut eligible = report
            .reviews
            .iter()
            .filter_map(|record| match record {
                ReviewRecord::Backend(review)
                    if review.binding.execution_id == execution.request.execution_id
                        && review.confirmation_eligible =>
                {
                    Some(review)
                }
                _ => None,
            })
            .collect::<Vec<_>>();
        eligible.sort_by(|left, right| {
            (
                left.candidate.sha256.as_str(),
                left.review_spec.sha256.as_str(),
                left.candidate_record_id.as_str(),
            )
                .cmp(&(
                    right.candidate.sha256.as_str(),
                    right.review_spec.sha256.as_str(),
                    right.candidate_record_id.as_str(),
                ))
        });
        let mut confirmations = BTreeMap::new();
        let mut roots = BTreeSet::new();
        for review in eligible {
            let spec = context
                .specs
                .get(&review.review_spec.id)
                .context("eligible review references an unknown spec")?;
            ensure!(
                spec.sha256 == review.review_spec.sha256,
                "eligible review spec hash mismatch"
            );
            let key = (
                review.binding.run_id.clone(),
                review.root_cause_id.clone(),
                review.expected_scope,
                EvidenceOrigin::BackendExecution,
            );
            if confirmations.contains_key(&key) {
                continue;
            }
            let criteria = &review.criteria;
            let original_component_review = if matches!(
                review.expected_scope,
                experiment::ConfirmationScope::OriginalComponent
                    | experiment::ConfirmationScope::Project
            ) {
                Some(OriginalComponentReview {
                    input_preconditions: confirmation_criterion(
                        criteria
                            .input_preconditions
                            .as_ref()
                            .context("eligible input criterion is missing")?,
                        output_dir,
                        &confirmation_dir,
                    )?,
                    fixed_original_constraints: confirmation_criterion(
                        criteria
                            .fixed_target_constraints
                            .as_ref()
                            .context("eligible target criterion is missing")?,
                        output_dir,
                        &confirmation_dir,
                    )?,
                    specified_property_violation: confirmation_criterion(
                        criteria
                            .specified_property_violation
                            .as_ref()
                            .context("eligible property criterion is missing")?,
                        output_dir,
                        &confirmation_dir,
                    )?,
                })
            } else {
                None
            };
            let spec_path = resolve_path(output_dir, &review.review_spec.path);
            ensure!(
                sha256_file(&spec_path)? == review.review_spec.sha256,
                "eligible spec changed before confirmation projection"
            );
            roots.insert(review.root_cause_id.clone());
            confirmations.insert(
                key,
                DefectConfirmation {
                    run_id: review.binding.run_id.clone(),
                    target_id: review.binding.target_id.clone(),
                    root_cause_id: review.root_cause_id.clone(),
                    scope: review.expected_scope,
                    evidence_origin: EvidenceOrigin::BackendExecution,
                    original_component_review,
                    evidence: vec![
                        relative_path(&confirmation_dir, report_path)?,
                        relative_path(&confirmation_dir, &spec_path)?,
                    ],
                    note:
                        "Automated review validated the fixed candidate contract and cause binding."
                            .to_owned(),
                },
            );
        }
        let set = ConfirmationSet {
            schema_version: 2,
            confirmations: confirmations.into_values().collect(),
        };
        write_json_new(&confirmation_path, &set)?;
        experiment::evaluate(
            &execution.plan_path,
            &execution.outcome_path,
            Some(&confirmation_path),
            &evaluation_path,
        )?;
        campaign_roots.extend(roots.iter().cloned());
        by_execution.push(ExecutionCampaignSummary {
            execution_id: execution.request.execution_id.clone(),
            campaign_coordinates: execution.request.campaign_coordinates.clone(),
            validated_attributed_root_cause_ids: roots.into_iter().collect(),
        });
        execution_evaluations.push(ExecutionEvaluation {
            execution_id: execution.request.execution_id.clone(),
            confirmation: file_ref_from(output_dir, &confirmation_path)?,
            evaluator_output: file_ref_from(output_dir, &evaluation_path)?,
        });
    }
    execution_evaluations.sort_by(|left, right| left.execution_id.cmp(&right.execution_id));
    by_execution.sort_by(|left, right| left.execution_id.cmp(&right.execution_id));
    let campaign_roots = campaign_roots.into_iter().collect::<Vec<_>>();
    let index = BackendBundleIndex {
        schema_version: 1,
        kind: "backend-review-bundle".to_owned(),
        review_specs: report.review_specs.clone(),
        review_request: file_ref_from(output_dir, request_path)?,
        review_report: file_ref_from(output_dir, report_path)?,
        execution_evaluations,
        campaign_summary: CampaignSummary {
            pair_count: request.executions.len(),
            by_execution,
            unique_validated_root_cause_count: campaign_roots.len(),
            unique_validated_root_cause_ids: campaign_roots,
        },
    };
    let path = output_dir.join("bundle-index.json");
    write_json_new(&path, &index)?;
    Ok(path)
}

fn confirmation_criterion(
    criterion: &Criterion,
    report_dir: &Path,
    confirmation_dir: &Path,
) -> Result<ReviewCriterion> {
    ensure!(
        criterion.verdict == CriterionVerdict::Satisfied,
        "confirmation criterion is not satisfied"
    );
    ensure!(
        !criterion.note.trim().is_empty() && !criterion.evidence.is_empty(),
        "confirmation criterion lacks note or evidence"
    );
    let mut evidence = Vec::new();
    for reference in &criterion.evidence {
        let path = resolve_path(report_dir, &reference.path);
        ensure!(path.is_file(), "criterion evidence is unavailable");
        ensure!(
            sha256_file(&path)? == reference.sha256,
            "criterion evidence changed before projection"
        );
        evidence.push(relative_path(confirmation_dir, &path)?);
    }
    evidence.sort();
    evidence.dedup();
    Ok(ReviewCriterion {
        verdict: ReviewVerdict::Satisfied,
        evidence,
        note: criterion.note.clone(),
    })
}

fn safe_execution_name(execution_id: &str) -> String {
    let prefix = execution_id
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_') {
                character
            } else {
                '_'
            }
        })
        .take(80)
        .collect::<String>();
    format!(
        "{}-{}",
        prefix,
        &sha256_bytes(execution_id.as_bytes())[..12]
    )
}

fn write_injection_index(
    report: &ReviewReport,
    report_path: &Path,
    context: &InjectionOutputContext,
    output_dir: &Path,
    request_path: &Path,
) -> Result<PathBuf> {
    let index = GroundTruthBundleIndex {
        schema_version: 1,
        kind: "injection-ground-truth".to_owned(),
        injection_id: context.injection_id.clone(),
        review_spec: file_ref_from(output_dir, &context.spec.path)?,
        review_request: file_ref_from(output_dir, request_path)?,
        review_report: file_ref_from(output_dir, report_path)?,
        qualification: context.qualification,
    };
    ensure!(
        report.kind == ReportKind::InjectionGroundTruth,
        "cannot write injection index for backend report"
    );
    let path = output_dir.join("ground-truth-index.json");
    write_json_new(&path, &index)?;
    Ok(path)
}

#[cfg(test)]
mod assignment_tests {
    use super::*;
    use crate::candidate_review::r1cs::Constraint;

    fn raw_counterexample(assignment: &str) -> String {
        format!(
            r#"{{
                "0_target_path": "synthetic.circom",
                "1_main_template": "Synthetic",
                "2_search_mode": "test",
                "3_execution_time": "0ms",
                "4_git_hash_of_zkfuzz": "test",
                "5_flag": null,
                "7_assignment": {assignment},
                "8_auxiliary_result": null
            }}"#
        )
    }

    fn assignment(
        wire_signals: &[(&str, &str)],
        eliminated_signals: &[(&str, &str)],
    ) -> NormalizedAssignment {
        let map = |entries: &[(&str, &str)]| {
            entries
                .iter()
                .map(|(name, value)| ((*name).to_owned(), (*value).to_owned()))
                .collect()
        };
        NormalizedAssignment {
            wires: vec![BigUint::one(), BigUint::from(7_u32)],
            wire_signals: map(wire_signals),
            eliminated_signals: map(eliminated_signals),
            parameters: BTreeMap::new(),
            canonical: true,
        }
    }

    fn projection_fixture() -> (R1cs, SymbolTable, ProjectionManifest) {
        let r1cs = R1cs {
            prime: BigUint::from(257_u32),
            shape: R1csShape {
                wires: 2,
                labels: 3,
                public_outputs: 1,
                public_inputs: 0,
                private_inputs: 0,
                constraints: 0,
            },
            constraints: Vec::new(),
            wire_labels: vec![0, 1],
        };
        let symbols = SymbolTable::parse(b"1,1,0,main.out\n2,1,1,main.alias\n", &r1cs).unwrap();
        let projection = ProjectionManifest {
            schema_version: 1,
            operator_id: "synthetic".to_owned(),
            operator_justification: "synthetic projection test".to_owned(),
            mappings: vec![ProjectionMapping {
                clean_wire_index: 1,
                clean_signal_names: vec!["main.out".to_owned(), "main.alias".to_owned()],
                source_kind: ProjectionSourceKind::DisturbanceSignal,
                source_signal_name: Some("main.shared".to_owned()),
            }],
        };
        (r1cs, symbols, projection)
    }

    #[test]
    fn raw_counterexample_rejects_duplicate_assignment_keys() {
        for raw in [
            r#"{"main.in":"7","main.in":"8"}"#,
            r#"{"main.in":"7","main.in":"7"}"#,
            r#"{"main.in":"7","main.\u0069n":"7"}"#,
        ] {
            let error =
                serde_json::from_str::<RawCounterexample>(&raw_counterexample(raw)).unwrap_err();
            assert!(error.to_string().contains("duplicate assignment key"));
        }
        let raw: RawCounterexample =
            serde_json::from_str(&raw_counterexample(r#"{"main.in":"7","main.out":"8"}"#)).unwrap();
        assert_eq!(raw.assignment.len(), 2);
    }

    #[test]
    fn named_assignment_requires_positive_wire_aliases_to_agree() {
        let (r1cs, symbols, _) = projection_fixture();
        let mut values = BTreeMap::from([
            ("main.out".to_owned(), "7".to_owned()),
            ("main.alias".to_owned(), "7".to_owned()),
        ]);
        let normalized = normalize_named_assignment(&values, &r1cs, &symbols, &[]).unwrap();
        assert_eq!(normalized.wires, vec![BigUint::one(), BigUint::from(7_u32)]);
        values.insert("main.alias".to_owned(), "8".to_owned());
        let error = normalize_named_assignment(&values, &r1cs, &symbols, &[]).unwrap_err();
        assert!(error.to_string().contains("positive-wire aliases disagree"));
    }

    #[test]
    fn input_comparison_resolves_wire_and_eliminated_signals() {
        let names = vec!["main.in".to_owned()];
        for disturbance in [
            assignment(&[("main.in", "7")], &[]),
            assignment(&[], &[("main.in", "7")]),
        ] {
            for clean in [
                assignment(&[("main.in", "7")], &[]),
                assignment(&[], &[("main.in", "7")]),
            ] {
                assert!(input_signals_equal(&names, &disturbance, &clean).unwrap());
            }
            let different = assignment(&[], &[("main.in", "8")]);
            assert!(!input_signals_equal(&names, &disturbance, &different).unwrap());
        }
    }

    #[test]
    fn input_comparison_rejects_missing_and_ambiguous_signals() {
        let names = vec!["main.in".to_owned()];
        let missing = assignment(&[], &[]);
        let present = assignment(&[("main.in", "7")], &[]);
        let ambiguous = assignment(&[("main.in", "7")], &[("main.in", "7")]);
        for (disturbance, clean) in [
            (&missing, &missing),
            (&missing, &present),
            (&present, &missing),
            (&ambiguous, &present),
            (&present, &ambiguous),
        ] {
            assert!(input_signals_equal(&names, disturbance, clean).is_err());
        }

        // A prior unequal value must not short-circuit validation of later inputs.
        let names = vec!["main.in".to_owned(), "main.missing".to_owned()];
        let different = assignment(&[("main.in", "8")], &[]);
        assert!(input_signals_equal(&names, &present, &different).is_err());
    }

    #[test]
    fn projection_resolves_wire_and_eliminated_signals() {
        let (r1cs, symbols, projection) = projection_fixture();
        let clean = assignment(&[], &[]);
        for disturbance in [
            assignment(&[("main.shared", "8")], &[]),
            assignment(&[], &[("main.shared", "8")]),
        ] {
            assert_eq!(
                project_disturbance_to_clean(
                    &projection,
                    "synthetic",
                    &r1cs,
                    &symbols,
                    &disturbance,
                    &clean,
                )
                .unwrap(),
                vec![BigUint::one(), BigUint::from(8_u32)]
            );
        }
        assert!(project_disturbance_to_clean(
            &projection,
            "synthetic",
            &r1cs,
            &symbols,
            &assignment(&[], &[]),
            &clean,
        )
        .is_err());
    }

    #[test]
    fn projection_rejects_duplicate_clean_signal_names() {
        let (r1cs, symbols, mut projection) = projection_fixture();
        projection.mappings[0]
            .clean_signal_names
            .push("main.out".to_owned());
        let error = project_disturbance_to_clean(
            &projection,
            "synthetic",
            &r1cs,
            &symbols,
            &assignment(&[("main.shared", "8")], &[]),
            &assignment(&[], &[]),
        )
        .unwrap_err();
        assert!(error.to_string().contains("repeats a clean signal alias"));
    }

    #[test]
    fn assignment_text_with_leading_zero_is_a_scientific_rejection() {
        let (r1cs, symbols, _) = projection_fixture();
        let normalized = normalize_named_assignment(
            &BTreeMap::from([("main.out".to_owned(), "07".to_owned())]),
            &r1cs,
            &symbols,
            &[],
        )
        .unwrap();
        assert_eq!(normalized.wires[1], BigUint::from(7_u32));
        assert!(!normalized.canonical);
    }

    #[test]
    fn generator_arguments_must_bind_the_common_input() {
        let outputs_only = vec![
            "{witness_output}".to_owned(),
            "{assignment_output}".to_owned(),
        ];
        assert!(validate_generator_arguments(&outputs_only).is_err());
        let complete = vec![
            "{common_input}".to_owned(),
            "{witness_output}".to_owned(),
            "{assignment_output}".to_owned(),
        ];
        validate_generator_arguments(&complete).unwrap();
    }

    #[test]
    fn literal_path_arguments_reject_unpinned_files_and_directories() {
        let temporary = tempfile::tempdir().unwrap();
        let runner = temporary.path().join("runner");
        let pinned = temporary.path().join("pinned.py");
        let unpinned = temporary.path().join("unpinned.py");
        let directory = temporary.path().join("unpinned-directory");
        fs::write(&runner, b"runner").unwrap();
        fs::write(&pinned, b"pinned").unwrap();
        fs::write(&unpinned, b"unpinned").unwrap();
        fs::create_dir(&directory).unwrap();
        let runner = fs::canonicalize(runner).unwrap();
        let pinned = fs::canonicalize(pinned).unwrap();
        let artifacts = BTreeMap::from([(pinned.clone(), sha256_file(&pinned).unwrap())]);
        validate_literal_path_arguments(
            temporary.path(),
            &[pinned.to_string_lossy().into_owned()],
            &runner,
            &artifacts,
            &BTreeSet::new(),
        )
        .unwrap();
        for argument in [
            unpinned.to_string_lossy().into_owned(),
            directory.to_string_lossy().into_owned(),
            format!("--cfg={{common_input}},{}", unpinned.display()),
            format!("-c=open('{}')", unpinned.display()),
        ] {
            assert!(validate_literal_path_arguments(
                temporary.path(),
                &[argument],
                &runner,
                &artifacts,
                &BTreeSet::new(),
            )
            .is_err());
        }
    }

    #[test]
    fn circom_compilation_requires_a_closed_materialized_include_closure() {
        let temporary = tempfile::tempdir().unwrap();
        let source_root = temporary.path().join("source");
        fs::create_dir(&source_root).unwrap();
        let entrypoint = source_root.join("main.circom");
        let dependency = source_root.join("dependency.circom");
        fs::write(
            &entrypoint,
            "pragma circom 2.1.6;\ninclude \"dependency.circom\";\ncomponent main = Dependency();\n",
        )
        .unwrap();
        fs::write(
            &dependency,
            "pragma circom 2.1.6;\ntemplate Dependency() { signal output out; out <== 0; }\n",
        )
        .unwrap();
        let entrypoint = fs::canonicalize(entrypoint).unwrap();
        let dependency = fs::canonicalize(dependency).unwrap();
        let sources = BTreeMap::from([
            (entrypoint.clone(), sha256_file(&entrypoint).unwrap()),
            (dependency.clone(), sha256_file(&dependency).unwrap()),
        ]);
        validate_closed_circom_source_closure(&entrypoint, &source_root, &[], &sources).unwrap();

        let external = temporary.path().join("external.circom");
        fs::write(
            &external,
            "pragma circom 2.1.6;\ntemplate External() { signal output out; out <== 0; }\n",
        )
        .unwrap();
        fs::write(
            &entrypoint,
            format!(
                "pragma circom 2.1.6;\ninclude \"{}\";\ncomponent main = External();\n",
                external.display()
            ),
        )
        .unwrap();
        assert!(
            validate_closed_circom_source_closure(&entrypoint, &source_root, &[], &sources)
                .is_err()
        );

        let first_library = source_root.join("z-first-library");
        let second_library = source_root.join("a-second-library");
        fs::create_dir(&first_library).unwrap();
        fs::create_dir(&second_library).unwrap();
        let first_dependency = first_library.join("shared.circom");
        let second_dependency = second_library.join("shared.circom");
        fs::write(
            &first_dependency,
            "pragma circom 2.1.6;\ntemplate Shared() { signal output out; out <== 1; }\n",
        )
        .unwrap();
        fs::write(
            &second_dependency,
            "pragma circom 2.1.6;\ntemplate Shared() { signal output out; out <== 2; }\n",
        )
        .unwrap();
        fs::write(
            &entrypoint,
            "pragma circom 2.1.6;\ninclude \"shared.circom\";\ncomponent main = Shared();\n",
        )
        .unwrap();
        let first_library = fs::canonicalize(first_library).unwrap();
        let second_library = fs::canonicalize(second_library).unwrap();
        let first_dependency = fs::canonicalize(first_dependency).unwrap();
        let canonical_source_root = fs::canonicalize(&source_root).unwrap();
        assert!(compiler_library_paths(
            &[
                "-l".to_owned(),
                first_library.to_string_lossy().into_owned(),
            ],
            &source_root,
        )
        .is_err());
        let ordered = compiler_library_paths(
            &[
                "-l".to_owned(),
                canonical_source_root.to_string_lossy().into_owned(),
                "-l".to_owned(),
                first_library.to_string_lossy().into_owned(),
                second_library.to_string_lossy().into_owned(),
                "--r1cs".to_owned(),
            ],
            &source_root,
        )
        .unwrap();
        assert_eq!(
            ordered,
            vec![canonical_source_root, first_library, second_library.clone()]
        );
        let library_sources = BTreeMap::from([
            (entrypoint.clone(), sha256_file(&entrypoint).unwrap()),
            (
                first_dependency.clone(),
                sha256_file(&first_dependency).unwrap(),
            ),
        ]);
        validate_closed_circom_source_closure(
            &entrypoint,
            &source_root,
            &ordered,
            &library_sources,
        )
        .unwrap();
        assert!(validate_closed_circom_source_closure(
            &entrypoint,
            &source_root,
            &[ordered[0].clone(), ordered[2].clone(), ordered[1].clone()],
            &library_sources,
        )
        .is_err());
    }

    #[test]
    fn circom_include_resolution_requires_explicit_source_root_first() {
        let temporary = tempfile::tempdir().unwrap();
        let source_root = temporary.path().join("source");
        let nested = source_root.join("nested");
        let library = source_root.join("library");
        fs::create_dir_all(&nested).unwrap();
        fs::create_dir(&library).unwrap();
        let entrypoint = nested.join("main.circom");
        let root_dependency = source_root.join("shared.circom");
        let library_dependency = library.join("shared.circom");
        fs::write(
            &entrypoint,
            "pragma circom 2.1.6;\ninclude \"shared.circom\";\ncomponent main = Shared();\n",
        )
        .unwrap();
        fs::write(
            &root_dependency,
            "pragma circom 2.1.6;\ntemplate Shared() { signal output out; out <== 1; }\n",
        )
        .unwrap();
        fs::write(
            &library_dependency,
            "pragma circom 2.1.6;\ntemplate Shared() { signal output out; out <== 2; }\n",
        )
        .unwrap();
        let source_root = fs::canonicalize(source_root).unwrap();
        let library = fs::canonicalize(library).unwrap();
        let entrypoint = fs::canonicalize(entrypoint).unwrap();
        let root_dependency = fs::canonicalize(root_dependency).unwrap();
        let ordered = compiler_library_paths(
            &[
                "-l".to_owned(),
                source_root.to_string_lossy().into_owned(),
                "-l".to_owned(),
                library.to_string_lossy().into_owned(),
            ],
            &source_root,
        )
        .unwrap();
        assert_eq!(ordered, vec![source_root.clone(), library.clone()]);
        let sources = BTreeMap::from([
            (entrypoint.clone(), sha256_file(&entrypoint).unwrap()),
            (
                root_dependency.clone(),
                sha256_file(&root_dependency).unwrap(),
            ),
        ]);
        validate_closed_circom_source_closure(&entrypoint, &source_root, &ordered, &sources)
            .unwrap();
        assert!(compiler_library_paths(
            &[
                "-l".to_owned(),
                library.to_string_lossy().into_owned(),
                "-l".to_owned(),
                source_root.to_string_lossy().into_owned(),
            ],
            &source_root,
        )
        .is_err());
    }

    #[test]
    fn fully_fixed_proof_requires_a_disturbance_bound_projection() {
        let prime = BigUint::from(257_u32);
        let r1cs = R1cs {
            prime,
            shape: R1csShape {
                wires: 2,
                labels: 2,
                public_outputs: 1,
                public_inputs: 0,
                private_inputs: 0,
                constraints: 1,
            },
            constraints: vec![Constraint {
                a: BTreeMap::from([(1, BigUint::one())]),
                b: BTreeMap::from([(0, BigUint::one())]),
                c: BTreeMap::new(),
            }],
            wire_labels: vec![0, 1],
        };
        let symbols = SymbolTable::parse(b"1,1,0,main.out\n", &r1cs).unwrap();
        let scratch = ScratchDirectory::create("fully-fixed-test").unwrap();
        let certificate_path = scratch.0.join("certificate.json");
        fs::write(
            &certificate_path,
            serde_json::to_vec(&FullyFixedConstraintCertificate {
                schema_version: 1,
                method: RelationExclusionMethod::FullyFixedConstraint,
                clean_constraint_indices: vec![0],
                fixed_signal_names: vec!["main.out".to_owned()],
            })
            .unwrap(),
        )
        .unwrap();
        let contract = ContractSpec {
            definition_path: PathBuf::from("contract.json"),
            definition_sha256: "0".repeat(64),
            input_contract_id: "test-input".to_owned(),
            property_id: "test-property".to_owned(),
            input_contract_statement: "test input".to_owned(),
            property_statement: "test property".to_owned(),
            input_signal_names: vec!["main.out".to_owned()],
            property_signal_names: vec!["main.out".to_owned()],
            predicate: PredicateSpec {
                api_version: 1,
                path: PathBuf::from("predicate.py"),
                sha256: "0".repeat(64),
                entrypoint: "evaluate".to_owned(),
                config: Value::Null,
                allowed_results: Vec::new(),
                allowed_violation_classes: Vec::new(),
            },
        };
        let disturbance = assignment(&[("main.out", "8")], &[]);
        let projected = vec![BigUint::one(), BigUint::from(8_u32)];
        let mut projection = ProjectionManifest {
            schema_version: 1,
            operator_id: "synthetic".to_owned(),
            operator_justification: "test".to_owned(),
            mappings: vec![ProjectionMapping {
                clean_wire_index: 1,
                clean_signal_names: vec!["main.out".to_owned()],
                source_kind: ProjectionSourceKind::DisturbanceSignal,
                source_signal_name: Some("main.out".to_owned()),
            }],
        };
        let satisfied = verify_fully_fixed_constraint(
            &certificate_path,
            &"0".repeat(64),
            &[0],
            &r1cs,
            &symbols,
            &projection,
            &projected,
            &[0],
            &contract,
            &disturbance,
        )
        .unwrap();
        assert_eq!(satisfied.verdict, CriterionVerdict::Satisfied);

        projection.mappings[0].source_kind = ProjectionSourceKind::CleanReferenceWire;
        projection.mappings[0].source_signal_name = None;
        let rejected = verify_fully_fixed_constraint(
            &certificate_path,
            &"0".repeat(64),
            &[0],
            &r1cs,
            &symbols,
            &projection,
            &projected,
            &[0],
            &contract,
            &disturbance,
        )
        .unwrap();
        assert_eq!(rejected.verdict, CriterionVerdict::NotSatisfied);
        assert_eq!(rejected.reason_code, "clean-extension-not-excluded");
    }

    #[test]
    fn semantic_projection_sorts_and_deduplicates_unordered_evidence() {
        let value = json!({
            "failed_clean_constraint_indices": [10, 2, 10],
            "evidence": [
                {"path": "z", "sha256": "b"},
                {"path": "a", "sha256": "a"},
                {"path": "other", "sha256": "a"}
            ]
        });
        assert_eq!(
            semanticize(value),
            json!({
                "failed_clean_constraint_indices": [2, 10],
                "evidence": [{"sha256": "a"}, {"sha256": "b"}]
            })
        );
    }

    #[test]
    fn engine_provenance_requires_every_semantic_source() {
        let incomplete = BTreeMap::from([(
            PathBuf::from("engine.rs"),
            sha256_bytes(REVIEW_ENGINE_SOURCE.as_bytes()),
        )]);
        assert!(verify_engine_source_manifest(&incomplete)
            .expect_err("incomplete source manifest")
            .to_string()
            .contains("experiment.rs"));

        let complete = BTreeMap::from([
            (
                PathBuf::from("engine.rs"),
                sha256_bytes(REVIEW_ENGINE_SOURCE.as_bytes()),
            ),
            (
                PathBuf::from("experiment.rs"),
                sha256_bytes(REVIEW_EXPERIMENT_SOURCE.as_bytes()),
            ),
            (
                PathBuf::from("predicate.rs"),
                sha256_bytes(REVIEW_PREDICATE_SOURCE.as_bytes()),
            ),
            (
                PathBuf::from("r1cs.rs"),
                sha256_bytes(REVIEW_R1CS_SOURCE.as_bytes()),
            ),
            (
                PathBuf::from("schema.rs"),
                sha256_bytes(REVIEW_SCHEMA_SOURCE.as_bytes()),
            ),
            (
                PathBuf::from("subprocess.rs"),
                sha256_bytes(REVIEW_SUBPROCESS_SOURCE.as_bytes()),
            ),
            (
                PathBuf::from("structure.rs"),
                sha256_bytes(REVIEW_STRUCTURE_SOURCE.as_bytes()),
            ),
            (
                PathBuf::from("targets.rs"),
                sha256_bytes(TARGET_DISCOVERY_SOURCE.as_bytes()),
            ),
        ]);
        verify_engine_source_manifest(&complete).expect("complete source manifest");
    }

    #[test]
    fn declared_review_executable_must_be_the_running_binary() {
        let temporary = tempfile::tempdir().unwrap();
        let unrelated = temporary.path().join("unrelated-executable");
        fs::write(&unrelated, b"not the running test executable").unwrap();
        let error = resolve_review_executable(&unrelated).unwrap_err();
        assert!(error
            .to_string()
            .contains("does not match the running executable"));

        let current = std::env::current_exe().unwrap();
        assert_eq!(
            resolve_review_executable(&current).unwrap(),
            fs::canonicalize(current).unwrap()
        );
    }

    #[test]
    fn staged_output_is_removed_on_error_and_published_by_rename() {
        let temporary = tempfile::tempdir().unwrap();
        let final_path = temporary.path().join("review-output");
        let abandoned_staging_path = {
            let staged = StagedOutput::create(&final_path).unwrap();
            let staging_path = staged.path().to_path_buf();
            fs::write(
                staging_path.join("review-report.json"),
                b"complete but unpublished",
            )
            .unwrap();
            staging_path
        };
        assert!(!abandoned_staging_path.exists());
        assert!(!final_path.exists());

        let staged = StagedOutput::create(&final_path).unwrap();
        let staging_path = staged.path().to_path_buf();
        fs::write(
            staging_path.join("review-report.json"),
            b"complete and published",
        )
        .unwrap();
        let published = staged.publish().unwrap();
        assert_eq!(
            published,
            fs::canonicalize(temporary.path())
                .unwrap()
                .join("review-output")
        );
        assert!(!staging_path.exists());
        assert_eq!(
            fs::read(final_path.join("review-report.json")).unwrap(),
            b"complete and published"
        );
    }

    #[test]
    fn integer_parameters_require_canonical_nonempty_decimal_text() {
        for accepted in ["0", "1", "-1", "123456"] {
            validate_integer_text(accepted).unwrap();
        }
        for rejected in ["", "-", "-0", "00", "01", "+1", "1a"] {
            assert!(validate_integer_text(rejected).is_err(), "{rejected:?}");
        }
    }
}
