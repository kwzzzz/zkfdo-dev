//! Reproducible static-ranking plans, ordered execution, and reviewed evaluation.
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    time::Instant,
};

use anyhow::{ensure, Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::{
    corpus::{self, CorpusTarget, Exclusion, PreparedCorpus, SourceFingerprint},
    runner::{RunStatus, ZkFuzzCommand},
    scheduler::{self, OrderedExperimentSummary, OrderedTarget},
    semantic::SourceScope,
    static_rank::{
        rank_targets, tie_summary, RankingInput, RankingStrategy, StaticRankingConfig, TieSummary,
        RANDOM_ALGORITHM,
    },
    structure::STRUCTURAL_METRIC,
    targets::EntrypointInspection,
};

fn schema_version() -> u32 {
    1
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanTarget {
    pub rank: usize,
    pub target_id: String,
    pub definition: CorpusTarget,
    pub inspection: EntrypointInspection,
    pub run_entrypoint: PathBuf,
    pub ranking: RankingInput,
    pub source_fingerprints: Vec<SourceFingerprint>,
    pub snapshot_fingerprints: Vec<SourceFingerprint>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanExclusion {
    pub target_id: String,
    pub label: String,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PreparationAccounting {
    pub inspection_seconds: f64,
    pub snapshot_seconds: f64,
    pub structure_seconds: f64,
    pub semantic_seconds: f64,
    pub legacy_seconds: f64,
    pub excluded_target_elapsed_seconds: f64,
    pub orchestration_overhead_seconds: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExperimentPlan {
    pub schema_version: u32,
    pub plan_id: String,
    pub created_at: DateTime<Utc>,
    pub plan_path: PathBuf,
    pub prepared_path: PathBuf,
    pub prepared_sha256: String,
    pub preparation_profile_strategy: Option<RankingStrategy>,
    pub strategy: RankingStrategy,
    pub ranking_seed: Option<u64>,
    pub random_algorithm: Option<String>,
    pub config_path: PathBuf,
    pub config_sha256: String,
    pub config: StaticRankingConfig,
    pub comparison_target_set: String,
    pub preparation_elapsed_seconds: f64,
    #[serde(default)]
    pub preparation_accounting: PreparationAccounting,
    pub planning_elapsed_seconds: f64,
    pub targets: Vec<PlanTarget>,
    /// Absent in schema 1 plans; in schema 2, verified against the ranking and None for `random`.
    #[serde(default)]
    pub ties: Option<TieSummary>,
    pub exclusions: Vec<PlanExclusion>,
    pub manifest_exclusions: Vec<Exclusion>,
    pub limitations: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecuteOptions {
    pub zkfuzz_bin: PathBuf,
    pub budget_seconds: u64,
    pub total_budget_seconds: u64,
    pub zkfuzz_seed: Option<u64>,
    pub mutation_settings: Option<PathBuf>,
    pub output: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MutationSettingsRecord {
    pub source_path: Option<PathBuf>,
    pub source_sha256: Option<String>,
    pub frozen_path: Option<PathBuf>,
    pub frozen_sha256: Option<String>,
    pub requested_seed: Option<u64>,
    pub effective_seed: Option<u64>,
    pub seed_controlled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CounterexampleArtifact {
    pub target_id: String,
    pub run_id: String,
    pub original_path: PathBuf,
    pub preserved_path: PathBuf,
    pub sha256: String,
    pub classification: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExperimentOutcome {
    pub schema_version: u32,
    pub outcome_id: String,
    pub report_path: PathBuf,
    pub plan_path: PathBuf,
    pub plan_sha256: String,
    pub plan_id: String,
    pub strategy: RankingStrategy,
    pub execution_mode: String,
    pub ranking_preparation_excluded_from_fuzzing_budget: bool,
    pub started_at: DateTime<Utc>,
    pub finished_at: DateTime<Utc>,
    pub elapsed_seconds: f64,
    pub budget_seconds_per_target: u64,
    pub total_budget_seconds: u64,
    pub zkfuzz_binary: PathBuf,
    pub zkfuzz_binary_sha256: String,
    pub mutation_settings: MutationSettingsRecord,
    pub scheduler: OrderedExperimentSummary,
    pub counterexample_candidates: Vec<CounterexampleArtifact>,
    pub limitations: Vec<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "kebab-case")]
pub enum ConfirmationScope {
    Project,
    OriginalComponent,
    WrapperOnly,
    ReachabilityUnknown,
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "kebab-case")]
pub enum EvidenceOrigin {
    #[default]
    BackendExecution,
    StaticWarning,
    ManualSourceReview,
    KnownDefectAnnotation,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum ReviewVerdict {
    Satisfied,
    NotSatisfied,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewCriterion {
    pub verdict: ReviewVerdict,
    pub evidence: Vec<PathBuf>,
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OriginalComponentReview {
    pub input_preconditions: ReviewCriterion,
    pub fixed_original_constraints: ReviewCriterion,
    pub specified_property_violation: ReviewCriterion,
}

impl OriginalComponentReview {
    fn is_satisfied(&self) -> bool {
        [
            &self.input_preconditions,
            &self.fixed_original_constraints,
            &self.specified_property_violation,
        ]
        .into_iter()
        .all(|criterion| criterion.verdict == ReviewVerdict::Satisfied)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DefectConfirmation {
    pub run_id: String,
    pub target_id: String,
    pub root_cause_id: String,
    pub scope: ConfirmationScope,
    #[serde(default)]
    pub evidence_origin: EvidenceOrigin,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub original_component_review: Option<OriginalComponentReview>,
    pub evidence: Vec<PathBuf>,
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConfirmationSet {
    #[serde(default = "schema_version")]
    pub schema_version: u32,
    pub confirmations: Vec<DefectConfirmation>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecallAtK {
    pub k: usize,
    pub retrieved_known_targets: usize,
    pub total_known_targets: usize,
    pub recall: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KnownTargetRank {
    pub target_id: String,
    pub rank: usize,
    pub root_cause_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DetectionPoint {
    pub root_cause_id: String,
    pub target_id: String,
    pub run_id: String,
    pub observed_by_seconds: f64,
    pub cumulative_confirmed_project_defects: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OriginalComponentDetectionPoint {
    pub root_cause_id: String,
    pub target_id: String,
    pub run_id: String,
    pub observed_by_seconds: f64,
    pub cumulative_confirmed_original_component_defects: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvaluationTimings {
    pub preparation_seconds: f64,
    pub preparation_accounting: PreparationAccounting,
    pub planning_seconds: f64,
    pub fuzzing_scheduler_seconds: f64,
    pub evaluation_seconds: f64,
    pub separate_phase_sum_seconds: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvaluationReport {
    pub schema_version: u32,
    pub report_path: PathBuf,
    pub plan_id: String,
    pub outcome_id: String,
    pub strategy: RankingStrategy,
    pub target_count: usize,
    pub preparation_excluded_target_count: usize,
    pub manifest_exclusion_count: usize,
    pub planned_target_ids: Vec<String>,
    pub actual_process_start_target_ids: Vec<String>,
    pub status_counts: BTreeMap<String, usize>,
    pub known_defect_target_count: usize,
    pub known_defect_root_cause_count: usize,
    pub known_target_ranks: Vec<KnownTargetRank>,
    pub recall_at_k: Vec<RecallAtK>,
    pub backend_bug_candidate_count: usize,
    pub preserved_counterexample_count: usize,
    pub reviewed_confirmation_count: usize,
    pub confirmed_project_defect_count: usize,
    pub confirmed_original_component_defect_count: usize,
    pub wrapper_only_confirmation_count: usize,
    pub reachability_unknown_confirmation_count: usize,
    pub evidence_origin_counts: BTreeMap<String, usize>,
    pub confirmed_project_root_causes: Vec<String>,
    pub confirmed_original_component_root_causes: Vec<String>,
    pub detection_curve: Vec<DetectionPoint>,
    pub original_component_detection_curve: Vec<OriginalComponentDetectionPoint>,
    pub first_confirmed_defect_observed_by_seconds: Option<f64>,
    pub first_confirmed_original_component_defect_observed_by_seconds: Option<f64>,
    pub timings: EvaluationTimings,
    pub limitations: Vec<String>,
}

pub fn create_plan(
    prepared_path: &Path,
    strategy: RankingStrategy,
    config_path: &Path,
    ranking_seed: Option<u64>,
    output_path: &Path,
) -> Result<ExperimentPlan> {
    let timer = Instant::now();
    let prepared_path = fs::canonicalize(prepared_path)
        .with_context(|| format!("prepared corpus unavailable: {}", prepared_path.display()))?;
    let prepared_bytes = fs::read(&prepared_path)?;
    let prepared: PreparedCorpus =
        serde_json::from_slice(&prepared_bytes).context("invalid prepared corpus JSON")?;
    ensure!(
        prepared.schema_version == 1,
        "unsupported prepared corpus schema version"
    );

    let config_path = fs::canonicalize(config_path)
        .with_context(|| format!("ranking config unavailable: {}", config_path.display()))?;
    let config_bytes = fs::read(&config_path)?;
    let config: StaticRankingConfig =
        serde_json::from_slice(&config_bytes).context("invalid static ranking config")?;

    let mut candidates = Vec::new();
    let mut exclusions = Vec::new();
    for target in &prepared.targets {
        if !target.eligible {
            exclusions.push(PlanExclusion {
                target_id: target.target_id.clone(),
                label: target.definition.label.clone(),
                reasons: target.exclusion_reasons.clone(),
            });
            continue;
        }
        if prepared.profile_strategy.is_none() {
            validate_common_complete_target(target)?;
        }
        validate_prepared_target(target, strategy, &config)?;
        candidates.push(target.ranking.clone());
    }
    ensure!(
        !candidates.is_empty(),
        "prepared corpus has no targets eligible for {strategy}"
    );
    let ranked = rank_targets(&candidates, strategy, &config, ranking_seed)?;
    let ties = tie_summary(&ranked, strategy, &config);
    let by_id = prepared
        .targets
        .iter()
        .map(|target| (target.target_id.as_str(), target))
        .collect::<BTreeMap<_, _>>();
    let mut targets = Vec::with_capacity(ranked.len());
    for (index, ranking) in ranked.into_iter().enumerate() {
        let prepared_target = by_id
            .get(ranking.target_id.as_str())
            .context("ranked target missing from prepared corpus")?;
        targets.push(PlanTarget {
            rank: index + 1,
            target_id: ranking.target_id.clone(),
            definition: prepared_target.definition.clone(),
            inspection: prepared_target
                .inspection
                .clone()
                .context("eligible target has no inspection")?,
            run_entrypoint: prepared_target
                .run_entrypoint
                .clone()
                .context("eligible target has no executable snapshot")?,
            ranking,
            source_fingerprints: prepared_target.source_fingerprints.clone(),
            snapshot_fingerprints: prepared_target.snapshot_fingerprints.clone(),
        });
    }

    let output_path = absolute_output_path(output_path)?;
    let comparison_target_set = if prepared.profile_strategy.is_none() {
        "common-complete-feature-set"
    } else {
        "strategy-specific-preparation"
    };
    let mut limitations = vec![
        "The plan freezes a target order; ranking scores are hypotheses, not vulnerability probabilities.".to_owned(),
        "Preparation time is recorded but excluded from the ranking-separated fuzzing budget.".to_owned(),
    ];
    if prepared.profile_strategy.is_some() {
        limitations.push(
            "This prepared corpus may not provide the common complete target set required for a multi-strategy comparison."
                .to_owned(),
        );
    }
    let plan = ExperimentPlan {
        schema_version: 2,
        plan_id: Uuid::new_v4().to_string(),
        created_at: Utc::now(),
        plan_path: output_path.clone(),
        prepared_path,
        prepared_sha256: sha256(&prepared_bytes),
        preparation_profile_strategy: prepared.profile_strategy,
        strategy,
        ranking_seed,
        random_algorithm: (strategy == RankingStrategy::Random)
            .then(|| RANDOM_ALGORITHM.to_owned()),
        config_path,
        config_sha256: sha256(&config_bytes),
        config,
        comparison_target_set: comparison_target_set.to_owned(),
        preparation_elapsed_seconds: prepared.elapsed_seconds,
        preparation_accounting: preparation_accounting(&prepared),
        planning_elapsed_seconds: timer.elapsed().as_secs_f64(),
        targets,
        ties,
        exclusions,
        manifest_exclusions: prepared.exclusions,
        limitations,
    };
    write_json(&output_path, &plan)?;
    Ok(plan)
}

pub fn execute_plan(plan_path: &Path, options: &ExecuteOptions) -> Result<ExperimentOutcome> {
    ensure!(
        options.budget_seconds > 0,
        "per-target budget must be positive"
    );
    ensure!(
        options.total_budget_seconds > 0,
        "total budget must be positive"
    );
    if let Some(seed) = options.zkfuzz_seed {
        ensure!(
            seed != 0,
            "zkFuzz seed 0 requests backend-generated randomness; use a nonzero seed for control"
        );
    }
    let started_at = Utc::now();
    let timer = Instant::now();
    let plan_path = fs::canonicalize(plan_path)
        .with_context(|| format!("experiment plan unavailable: {}", plan_path.display()))?;
    let plan_bytes = fs::read(&plan_path)?;
    let plan = load_plan(&plan_bytes)?;

    let zkfuzz_binary = resolve_executable(&options.zkfuzz_bin).with_context(|| {
        format!(
            "zkFuzz binary unavailable: {}",
            options.zkfuzz_bin.display()
        )
    })?;
    let zkfuzz_binary_sha256 = sha256(&fs::read(&zkfuzz_binary)?);
    let execution_root = options.output.join(format!("execution-{}", Uuid::new_v4()));
    fs::create_dir_all(&execution_root)?;
    let execution_root = fs::canonicalize(execution_root)?;
    let mutation_settings = freeze_mutation_settings(
        options.mutation_settings.as_deref(),
        options.zkfuzz_seed,
        &execution_root,
    )?;

    let before = plan
        .targets
        .iter()
        .map(|target| {
            Ok((
                target.target_id.clone(),
                list_counterexamples(&target.run_entrypoint)?,
            ))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    let mut ordered = Vec::with_capacity(plan.targets.len());
    for target in &plan.targets {
        let mut args = vec![target.run_entrypoint.to_string_lossy().into_owned()];
        args.extend(backend_library_args(&target.definition.compile_args)?);
        args.extend([
            "--prime".to_owned(),
            target.definition.prime.clone(),
            "--search_mode".to_owned(),
            "ga".to_owned(),
            "--save_output".to_owned(),
        ]);
        if let Some(path) = &mutation_settings.frozen_path {
            args.push("--path_to_mutation_setting".to_owned());
            args.push(path.to_string_lossy().into_owned());
        }
        ordered.push(OrderedTarget {
            target_id: target.target_id.clone(),
            target: target.run_entrypoint.clone(),
            command: ZkFuzzCommand {
                binary: zkfuzz_binary.clone(),
                args,
            },
        });
    }
    let scheduler = scheduler::run_ordered_experiment(
        &ordered,
        options.budget_seconds,
        options.total_budget_seconds,
        &execution_root,
    )?;
    let counterexample_candidates =
        preserve_counterexamples(&plan, &scheduler, &before, &execution_root)?;
    let report_path = execution_root.join("outcome.json");
    let outcome = ExperimentOutcome {
        schema_version: 1,
        outcome_id: Uuid::new_v4().to_string(),
        report_path: report_path.clone(),
        plan_path,
        plan_sha256: sha256(&plan_bytes),
        plan_id: plan.plan_id.clone(),
        strategy: plan.strategy,
        execution_mode: "ranking-separated".to_owned(),
        ranking_preparation_excluded_from_fuzzing_budget: true,
        started_at,
        finished_at: Utc::now(),
        elapsed_seconds: timer.elapsed().as_secs_f64(),
        budget_seconds_per_target: options.budget_seconds,
        total_budget_seconds: options.total_budget_seconds,
        zkfuzz_binary,
        zkfuzz_binary_sha256,
        mutation_settings,
        scheduler,
        counterexample_candidates,
        limitations: vec![
            "The total fuzzing budget starts inside the ordered scheduler after plan/source validation and command construction.".to_owned(),
            "The scheduler does not let a backend process run beyond the remaining deadline and starts no later target after exhaustion; required log/result persistence is not aborted and can make recorded elapsed time slightly exceed the nominal total.".to_owned(),
            "A backend NOT SAFE result and saved counterexample are candidates until separately reviewed against project input assumptions and root cause.".to_owned(),
            "The runner records successful spawn-call order; it cannot observe the exact OS exec timestamp.".to_owned(),
        ],
    };
    validate_outcome(&outcome, &plan)?;
    write_json(&report_path, &outcome)?;
    Ok(outcome)
}

pub fn evaluate(
    plan_path: &Path,
    outcome_path: &Path,
    confirmations_path: Option<&Path>,
    output_path: &Path,
) -> Result<EvaluationReport> {
    let timer = Instant::now();
    let plan_path = fs::canonicalize(plan_path)?;
    let plan_bytes = fs::read(&plan_path)?;
    let plan = load_plan(&plan_bytes)?;
    let outcome_path = fs::canonicalize(outcome_path)?;
    let outcome: ExperimentOutcome = serde_json::from_slice(&fs::read(&outcome_path)?)?;
    ensure!(
        outcome.schema_version == 1,
        "unsupported outcome schema version"
    );
    ensure!(
        outcome.plan_id == plan.plan_id,
        "outcome belongs to another plan"
    );
    ensure!(
        outcome.plan_sha256 == sha256(&plan_bytes),
        "plan changed after execution"
    );
    validate_outcome(&outcome, &plan)?;

    let confirmations = load_and_validate_confirmations(confirmations_path, &plan, &outcome)?;
    let known_target_ranks = known_target_ranks(&plan);
    let known_target_ids = known_target_ranks
        .iter()
        .map(|target| target.target_id.as_str())
        .collect::<BTreeSet<_>>();
    let known_root_causes = known_target_ranks
        .iter()
        .flat_map(|target| target.root_cause_ids.iter().cloned())
        .collect::<BTreeSet<_>>();
    let recall_at_k = recall_at_k(&plan, &known_target_ids);

    let mut status_counts = BTreeMap::new();
    for run in &outcome.scheduler.runs {
        *status_counts
            .entry(status_name(&run.result.status))
            .or_insert(0) += 1;
    }
    *status_counts
        .entry("runner_failure".to_owned())
        .or_insert(0) += outcome.scheduler.failures.len();
    *status_counts.entry("not_started".to_owned()).or_insert(0) += outcome.scheduler.skipped.len();

    let actual_process_start_target_ids = outcome
        .scheduler
        .runs
        .iter()
        .filter(|run| run.process_start_offset_seconds.is_some())
        .map(|run| run.target_id.clone())
        .collect::<Vec<_>>();
    let run_offsets = outcome
        .scheduler
        .runs
        .iter()
        .map(|run| (run.result.run_id.as_str(), run.completion_offset_seconds))
        .collect::<BTreeMap<_, _>>();

    let project_detections = earliest_confirmations(
        confirmations.iter().filter(|confirmation| {
            confirmation.scope == ConfirmationScope::Project
                && confirmation.evidence_origin == EvidenceOrigin::BackendExecution
        }),
        &run_offsets,
    )?;
    let detection_curve = project_detections
        .iter()
        .enumerate()
        .map(|(index, (confirmation, offset))| DetectionPoint {
            root_cause_id: confirmation.root_cause_id.clone(),
            target_id: confirmation.target_id.clone(),
            run_id: confirmation.run_id.clone(),
            observed_by_seconds: *offset,
            cumulative_confirmed_project_defects: index + 1,
        })
        .collect::<Vec<_>>();
    let first_confirmed_defect_observed_by_seconds = detection_curve
        .first()
        .map(|point| point.observed_by_seconds);
    let confirmed_project_root_causes = detection_curve
        .iter()
        .map(|point| point.root_cause_id.clone())
        .collect::<Vec<_>>();

    let original_component_detections = earliest_confirmations(
        confirmations.iter().filter(|confirmation| {
            confirmation.evidence_origin == EvidenceOrigin::BackendExecution
                && matches!(
                    confirmation.scope,
                    ConfirmationScope::OriginalComponent | ConfirmationScope::Project
                )
                && confirmation
                    .original_component_review
                    .as_ref()
                    .is_some_and(OriginalComponentReview::is_satisfied)
        }),
        &run_offsets,
    )?;
    let original_component_detection_curve = original_component_detections
        .iter()
        .enumerate()
        .map(
            |(index, (confirmation, offset))| OriginalComponentDetectionPoint {
                root_cause_id: confirmation.root_cause_id.clone(),
                target_id: confirmation.target_id.clone(),
                run_id: confirmation.run_id.clone(),
                observed_by_seconds: *offset,
                cumulative_confirmed_original_component_defects: index + 1,
            },
        )
        .collect::<Vec<_>>();
    let first_confirmed_original_component_defect_observed_by_seconds =
        original_component_detection_curve
            .first()
            .map(|point| point.observed_by_seconds);
    let confirmed_original_component_root_causes = original_component_detection_curve
        .iter()
        .map(|point| point.root_cause_id.clone())
        .collect::<Vec<_>>();

    let mut evidence_origin_counts = BTreeMap::new();
    for confirmation in &confirmations {
        *evidence_origin_counts
            .entry(evidence_origin_name(confirmation.evidence_origin).to_owned())
            .or_insert(0) += 1;
    }
    let evaluation_seconds = timer.elapsed().as_secs_f64();
    let output_path = absolute_output_path(output_path)?;
    let report = EvaluationReport {
        schema_version: 2,
        report_path: output_path.clone(),
        plan_id: plan.plan_id,
        outcome_id: outcome.outcome_id,
        strategy: plan.strategy,
        target_count: plan.targets.len(),
        preparation_excluded_target_count: plan.exclusions.len(),
        manifest_exclusion_count: plan.manifest_exclusions.len(),
        planned_target_ids: plan
            .targets
            .iter()
            .map(|target| target.target_id.clone())
            .collect(),
        actual_process_start_target_ids,
        status_counts,
        known_defect_target_count: known_target_ids.len(),
        known_defect_root_cause_count: known_root_causes.len(),
        known_target_ranks,
        recall_at_k,
        backend_bug_candidate_count: outcome
            .scheduler
            .runs
            .iter()
            .filter(|run| run.result.status == RunStatus::BugFound)
            .count(),
        preserved_counterexample_count: outcome.counterexample_candidates.len(),
        reviewed_confirmation_count: confirmations.len(),
        confirmed_project_defect_count: confirmed_project_root_causes.len(),
        confirmed_original_component_defect_count: confirmed_original_component_root_causes.len(),
        wrapper_only_confirmation_count: confirmations
            .iter()
            .filter(|confirmation| confirmation.scope == ConfirmationScope::WrapperOnly)
            .count(),
        reachability_unknown_confirmation_count: confirmations
            .iter()
            .filter(|confirmation| {
                confirmation.scope == ConfirmationScope::ReachabilityUnknown
            })
            .count(),
        evidence_origin_counts,
        confirmed_project_root_causes,
        confirmed_original_component_root_causes,
        detection_curve,
        original_component_detection_curve,
        first_confirmed_defect_observed_by_seconds,
        first_confirmed_original_component_defect_observed_by_seconds,
        timings: EvaluationTimings {
            preparation_seconds: plan.preparation_elapsed_seconds,
            preparation_accounting: plan.preparation_accounting.clone(),
            planning_seconds: plan.planning_elapsed_seconds,
            fuzzing_scheduler_seconds: outcome.scheduler.elapsed_seconds,
            evaluation_seconds,
            separate_phase_sum_seconds: plan.preparation_elapsed_seconds
                + plan.planning_elapsed_seconds
                + outcome.scheduler.elapsed_seconds
                + evaluation_seconds,
        },
        limitations: vec![
            "Recall@K uses the target as its unit and only manifest-annotated known-defect targets as its denominator; unlabeled targets are not safe negatives.".to_owned(),
            "Original-component execution metrics require backend-execution evidence plus satisfied reviews of input preconditions, fixed-original constraints, and the pre-specified property violation; file existence and reviewer declarations are validated structurally, not independently proven.".to_owned(),
            "Legacy project metrics retain their schema-1 meaning. A project record contributes to the original-component metric only when it also supplies the complete satisfied component review.".to_owned(),
            "Static warnings, manual source review, known-defect annotations, crashes, and counterexample files do not contribute to execution-discovered defect curves.".to_owned(),
            "Detection timestamps are scheduler completion upper bounds for linked runs, not exact discovery or human confirmation times; post-run review time is not part of the fuzzing budget.".to_owned(),
            "Separate phase durations may have occurred in different invocations; their sum is accounting, not a single uninterrupted wall-clock measurement.".to_owned(),
        ],
    };
    write_json(&output_path, &report)?;
    Ok(report)
}

fn earliest_confirmations<'a>(
    confirmations: impl Iterator<Item = &'a DefectConfirmation>,
    run_offsets: &BTreeMap<&str, f64>,
) -> Result<Vec<(&'a DefectConfirmation, f64)>> {
    let mut first_by_root: BTreeMap<String, (&DefectConfirmation, f64)> = BTreeMap::new();
    for confirmation in confirmations {
        let offset = *run_offsets
            .get(confirmation.run_id.as_str())
            .context("confirmed run has no completion offset")?;
        match first_by_root.get(&confirmation.root_cause_id) {
            Some((_, old)) if *old <= offset => {}
            _ => {
                first_by_root.insert(confirmation.root_cause_id.clone(), (confirmation, offset));
            }
        }
    }
    let mut detections = first_by_root.into_values().collect::<Vec<_>>();
    detections.sort_by(|left, right| {
        left.1
            .total_cmp(&right.1)
            .then_with(|| left.0.root_cause_id.cmp(&right.0.root_cause_id))
    });
    Ok(detections)
}

fn evidence_origin_name(origin: EvidenceOrigin) -> &'static str {
    match origin {
        EvidenceOrigin::BackendExecution => "backend-execution",
        EvidenceOrigin::StaticWarning => "static-warning",
        EvidenceOrigin::ManualSourceReview => "manual-source-review",
        EvidenceOrigin::KnownDefectAnnotation => "known-defect-annotation",
    }
}

fn validate_prepared_target(
    target: &corpus::PreparedTarget,
    strategy: RankingStrategy,
    config: &StaticRankingConfig,
) -> Result<()> {
    corpus::verify_input_contract_evidence(target)?;
    corpus::verify_fingerprints(&target.source_fingerprints)?;
    corpus::verify_fingerprints(&target.snapshot_fingerprints)?;
    let inspection = target
        .inspection
        .as_ref()
        .context("eligible target has no inspection")?;
    ensure!(
        inspection.complete,
        "eligible target inspection is incomplete"
    );
    let recomputed =
        corpus::stable_target_id(&target.definition, inspection, &target.source_fingerprints)?;
    ensure!(
        recomputed == target.target_id && target.ranking.target_id == target.target_id,
        "prepared target identity does not match its source closure"
    );
    let run_entrypoint = fs::canonicalize(
        target
            .run_entrypoint
            .as_ref()
            .context("eligible target has no executable snapshot")?,
    )?;
    corpus::verify_snapshot_provenance(
        inspection,
        &run_entrypoint,
        &target.source_fingerprints,
        &target.snapshot_fingerprints,
    )?;
    ensure!(
        target.ranking.path == target.definition.entrypoint,
        "ranking path differs from the manifest entrypoint"
    );
    backend_library_args(&target.definition.compile_args)?;

    if matches!(
        strategy,
        RankingStrategy::RiskOnly
            | RankingStrategy::RiskGrouped
            | RankingStrategy::WarningFirst
            | RankingStrategy::CostAware
    ) {
        let semantic = target
            .semantic
            .as_ref()
            .context("selected strategy requires semantic analysis")?;
        ensure!(
            semantic.complete,
            "selected strategy requires complete semantic analysis"
        );
        let expected_scopes = inspection
            .scopes
            .iter()
            .map(|scope| SourceScope {
                path: scope.path.clone(),
                template_name: scope.template_name.clone(),
                start_line: scope.start_line,
                end_line: scope.end_line,
            })
            .collect::<Vec<_>>();
        ensure!(
            semantic.scopes == expected_scopes,
            "semantic scopes differ from the inspected reachable closure"
        );
        ensure!(
            target.ranking.risk_score == semantic.risk_score.map(|value| value as u64)
                && target.ranking.warning_count == Some(semantic.warning_count as u64),
            "semantic ranking values differ from the captured analysis"
        );
    }
    let structure = target
        .structure
        .as_ref()
        .context("eligible target requires a compiled structure profile")?;
    ensure!(
        structure.compile_success
            && structure.size.is_some()
            && target.ranking.size == structure.size,
        "compiled target size is not backed by the structure profile"
    );
    if strategy == RankingStrategy::RiskGrouped {
        ensure!(
            structure.ast_success
                && structure.complexity.is_some()
                && target.ranking.complexity == structure.complexity,
            "risk-grouped complexity is not backed by root AST statistics"
        );
        let groups = config
            .complexity_groups
            .as_ref()
            .context("risk-grouped requires frozen complexity groups")?;
        ensure!(
            groups.metric == STRUCTURAL_METRIC && structure.metric == STRUCTURAL_METRIC,
            "complexity config/profile metric mismatch"
        );
    }
    if strategy == RankingStrategy::Legacy {
        ensure!(
            target.ranking.legacy_score.is_some_and(f64::is_finite),
            "legacy strategy requires a finite captured legacy score"
        );
    }
    Ok(())
}

fn preparation_accounting(prepared: &PreparedCorpus) -> PreparationAccounting {
    let mut accounting = PreparationAccounting::default();
    let mut target_elapsed = 0.0;
    for target in &prepared.targets {
        accounting.inspection_seconds += target.timings.inspection_seconds;
        accounting.snapshot_seconds += target.timings.snapshot_seconds;
        accounting.structure_seconds += target.timings.structure_seconds;
        accounting.semantic_seconds += target.timings.semantic_seconds;
        accounting.legacy_seconds += target.timings.legacy_seconds;
        target_elapsed += target.elapsed_seconds;
        if !target.eligible {
            accounting.excluded_target_elapsed_seconds += target.elapsed_seconds;
        }
    }
    accounting.orchestration_overhead_seconds =
        (prepared.elapsed_seconds - target_elapsed).max(0.0);
    accounting
}

fn validate_common_complete_target(target: &corpus::PreparedTarget) -> Result<()> {
    let structure = target
        .structure
        .as_ref()
        .context("common comparison target has no structure profile")?;
    ensure!(
        structure.compile_success
            && structure.ast_success
            && structure.size.is_some()
            && structure.complexity.is_some()
            && target.ranking.size == structure.size
            && target.ranking.complexity == structure.complexity,
        "common comparison target has incomplete compiled size or root AST complexity"
    );
    let semantic = target
        .semantic
        .as_ref()
        .context("common comparison target has no semantic analysis")?;
    ensure!(
        semantic.complete
            && target.ranking.risk_score == semantic.risk_score.map(|value| value as u64)
            && target.ranking.warning_count == Some(semantic.warning_count as u64),
        "common comparison target has incomplete semantic ranking values"
    );
    ensure!(
        target.ranking.legacy_score.is_some_and(f64::is_finite),
        "common comparison target has no finite legacy score"
    );
    Ok(())
}

/// Schema 1 plans were frozen before tie reporting and must not contain a `ties` key;
/// schema 2 plans must contain it (null only for `random`), checked on the raw JSON
/// because a missing key and an explicit null both deserialize to None.
fn load_plan(plan_bytes: &[u8]) -> Result<ExperimentPlan> {
    let value: serde_json::Value =
        serde_json::from_slice(plan_bytes).context("invalid experiment plan JSON")?;
    let has_ties = value.get("ties").is_some();
    let plan: ExperimentPlan =
        serde_json::from_value(value).context("invalid experiment plan JSON")?;
    ensure!(
        matches!(plan.schema_version, 1 | 2),
        "unsupported plan schema version"
    );
    if plan.schema_version == 1 {
        ensure!(!has_ties, "schema 1 plan must not carry tie reporting");
    } else {
        ensure!(has_ties, "schema 2 plan is missing its tie summary");
    }
    validate_plan(&plan)?;
    Ok(plan)
}

fn validate_plan(plan: &ExperimentPlan) -> Result<()> {
    ensure!(!plan.targets.is_empty(), "experiment plan has no targets");
    ensure!(
        plan.strategy != RankingStrategy::Random || plan.ranking_seed.is_some(),
        "random plan has no ranking seed"
    );
    ensure!(
        plan.strategy != RankingStrategy::Random
            || plan.random_algorithm.as_deref() == Some(RANDOM_ALGORITHM),
        "random plan algorithm is missing or unsupported"
    );
    let config_bytes = fs::read(&plan.config_path)
        .with_context(|| format!("frozen config unavailable: {}", plan.config_path.display()))?;
    ensure!(
        sha256(&config_bytes) == plan.config_sha256,
        "ranking config changed after planning"
    );
    let on_disk_config: StaticRankingConfig =
        serde_json::from_slice(&config_bytes).context("invalid frozen ranking config")?;
    ensure!(
        on_disk_config == plan.config,
        "embedded ranking config differs from the frozen config"
    );
    let prepared_bytes = fs::read(&plan.prepared_path).with_context(|| {
        format!(
            "prepared corpus unavailable: {}",
            plan.prepared_path.display()
        )
    })?;
    ensure!(
        sha256(&prepared_bytes) == plan.prepared_sha256,
        "prepared corpus changed after planning"
    );
    let prepared: PreparedCorpus =
        serde_json::from_slice(&prepared_bytes).context("invalid frozen prepared corpus")?;
    let prepared_by_id = prepared
        .targets
        .iter()
        .map(|target| (target.target_id.as_str(), target))
        .collect::<BTreeMap<_, _>>();
    let expected_ids = prepared
        .targets
        .iter()
        .filter(|target| target.eligible)
        .map(|target| target.target_id.as_str())
        .collect::<BTreeSet<_>>();
    let planned_ids = plan
        .targets
        .iter()
        .map(|target| target.target_id.as_str())
        .collect::<BTreeSet<_>>();
    ensure!(
        planned_ids == expected_ids && plan.targets.len() == expected_ids.len(),
        "plan target set differs from the complete eligible prepared target set"
    );
    ensure!(
        plan.preparation_profile_strategy == prepared.profile_strategy,
        "plan preparation profile label differs from the frozen prepared corpus"
    );
    let mut ids = BTreeSet::new();
    for (index, target) in plan.targets.iter().enumerate() {
        ensure!(target.rank == index + 1, "plan ranks are not contiguous");
        ensure!(
            ids.insert(target.target_id.as_str()),
            "duplicate target in experiment plan"
        );
        let prepared_target = prepared_by_id
            .get(target.target_id.as_str())
            .context("plan target is missing from the prepared corpus")?;
        ensure!(
            prepared_target.eligible,
            "plan contains a target excluded during preparation"
        );
        if prepared.profile_strategy.is_none() {
            validate_common_complete_target(prepared_target)?;
        }
        validate_prepared_target(prepared_target, plan.strategy, &plan.config)?;
        ensure!(
            serde_json::to_value(&target.definition)?
                == serde_json::to_value(&prepared_target.definition)?
                && serde_json::to_value(&target.inspection)?
                    == serde_json::to_value(&prepared_target.inspection)?
                && target.run_entrypoint
                    == *prepared_target
                        .run_entrypoint
                        .as_ref()
                        .context("prepared target has no run entrypoint")?
                && target.ranking == prepared_target.ranking
                && target.source_fingerprints == prepared_target.source_fingerprints
                && target.snapshot_fingerprints == prepared_target.snapshot_fingerprints,
            "plan target metadata differs from the frozen prepared corpus"
        );
        let recomputed = corpus::stable_target_id(
            &target.definition,
            &target.inspection,
            &target.source_fingerprints,
        )?;
        ensure!(
            recomputed == target.target_id && target.ranking.target_id == target.target_id,
            "plan target identity does not match its source closure"
        );
        let entrypoint = fs::canonicalize(&target.run_entrypoint)?;
        corpus::verify_snapshot_provenance(
            &target.inspection,
            &entrypoint,
            &target.source_fingerprints,
            &target.snapshot_fingerprints,
        )?;
    }
    let reranked = rank_targets(
        &plan
            .targets
            .iter()
            .map(|target| target.ranking.clone())
            .collect::<Vec<_>>(),
        plan.strategy,
        &plan.config,
        plan.ranking_seed,
    )?;
    ensure!(
        reranked
            .iter()
            .map(|target| target.target_id.as_str())
            .eq(plan.targets.iter().map(|target| target.target_id.as_str())),
        "stored target order does not match the frozen ranking inputs"
    );
    if plan.schema_version == 2 {
        ensure!(
            plan.ties == tie_summary(&reranked, plan.strategy, &plan.config),
            "stored tie summary does not match the frozen ranking inputs"
        );
    }
    Ok(())
}

fn validate_outcome(outcome: &ExperimentOutcome, plan: &ExperimentPlan) -> Result<()> {
    ensure!(
        outcome.plan_id == plan.plan_id && outcome.strategy == plan.strategy,
        "outcome plan metadata mismatch"
    );
    ensure!(
        outcome.scheduler.scheduler == "uniform-ordered",
        "outcome was not produced by the ordered uniform scheduler"
    );
    let expected_ids = plan
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
            .eq(expected_ids.iter().copied()),
        "outcome planned order differs from plan"
    );
    ensure!(
        outcome.budget_seconds_per_target == outcome.scheduler.budget_seconds_per_target
            && outcome.total_budget_seconds == outcome.scheduler.total_budget_seconds,
        "outcome and scheduler budgets differ"
    );
    let mut accounted = BTreeSet::new();
    let mut previous_run_index = None;
    for run in &outcome.scheduler.runs {
        ensure!(
            run.index < expected_ids.len() && run.target_id == expected_ids[run.index],
            "outcome run target/index differs from plan"
        );
        ensure!(
            accounted.insert(run.index),
            "outcome contains a duplicate target result"
        );
        ensure!(
            previous_run_index.is_none_or(|previous| previous < run.index),
            "outcome run rows are not in planned order"
        );
        previous_run_index = Some(run.index);
    }
    for failure in &outcome.scheduler.failures {
        ensure!(
            failure.index < expected_ids.len() && failure.target_id == expected_ids[failure.index],
            "outcome runner failure target/index differs from plan"
        );
        ensure!(
            accounted.insert(failure.index),
            "outcome contains duplicate accounting for a target"
        );
    }
    for skipped in &outcome.scheduler.skipped {
        ensure!(
            skipped.index < expected_ids.len() && skipped.target_id == expected_ids[skipped.index],
            "outcome skipped target/index differs from plan"
        );
        ensure!(
            accounted.insert(skipped.index),
            "outcome contains duplicate accounting for a target"
        );
    }
    ensure!(
        accounted.len() == expected_ids.len(),
        "outcome does not account for every planned target"
    );
    let runs = outcome
        .scheduler
        .runs
        .iter()
        .map(|run| (run.result.run_id.as_str(), run))
        .collect::<BTreeMap<_, _>>();
    ensure!(
        runs.len() == outcome.scheduler.runs.len(),
        "outcome contains duplicate run IDs"
    );
    for artifact in &outcome.counterexample_candidates {
        let run = runs
            .get(artifact.run_id.as_str())
            .context("counterexample references an unknown run")?;
        ensure!(
            run.target_id == artifact.target_id && run.result.status == RunStatus::BugFound,
            "counterexample is not attached to its BugFound target/run"
        );
        ensure!(
            artifact.classification == "backend-counterexample-candidate-unconfirmed",
            "counterexample has an unsupported classification"
        );
        ensure!(
            artifact.preserved_path.is_file()
                && sha256(&fs::read(&artifact.preserved_path)?) == artifact.sha256,
            "preserved counterexample is unavailable or changed"
        );
    }
    Ok(())
}

fn freeze_mutation_settings(
    source_path: Option<&Path>,
    requested_seed: Option<u64>,
    execution_root: &Path,
) -> Result<MutationSettingsRecord> {
    let (mut bytes, source_path, source_sha256, mut json) = if let Some(path) = source_path {
        let path = fs::canonicalize(path)
            .with_context(|| format!("mutation settings unavailable: {}", path.display()))?;
        let bytes = fs::read(&path)?;
        let json: Value =
            serde_json::from_slice(&bytes).context("invalid mutation settings JSON")?;
        ensure!(json.is_object(), "mutation settings must be a JSON object");
        let source_sha256 = Some(sha256(&bytes));
        (bytes, Some(path), source_sha256, json)
    } else {
        (
            Vec::new(),
            None,
            None,
            Value::Object(Map::<String, Value>::new()),
        )
    };
    if let Some(existing) = json.get("seed") {
        ensure!(
            existing.as_u64().is_some(),
            "mutation settings seed must be an unsigned integer"
        );
    }
    if let Some(seed) = requested_seed {
        json.as_object_mut()
            .context("mutation settings must be an object")?
            .insert("seed".to_owned(), Value::from(seed));
        bytes = serde_json::to_vec_pretty(&json)?;
        bytes.push(b'\n');
    }
    let effective_seed = json
        .get("seed")
        .and_then(Value::as_u64)
        .filter(|seed| *seed != 0);
    let needs_file = source_path.is_some() || requested_seed.is_some();
    let (frozen_path, frozen_sha256) = if needs_file {
        let path = execution_root.join("mutation-settings.json");
        fs::write(&path, &bytes)?;
        (Some(path), Some(sha256(&bytes)))
    } else {
        (None, None)
    };
    Ok(MutationSettingsRecord {
        source_path,
        source_sha256,
        frozen_path,
        frozen_sha256,
        requested_seed,
        effective_seed,
        seed_controlled: effective_seed.is_some(),
    })
}

fn backend_library_args(args: &[String]) -> Result<Vec<String>> {
    let mut output = Vec::new();
    let mut index = 0;
    while index < args.len() {
        ensure!(
            args[index] == "-l",
            "zkFuzz execution cannot reproduce compiler setting {}; only -l library paths are supported",
            args[index]
        );
        index += 1;
        ensure!(
            index < args.len() && !args[index].starts_with('-'),
            "-l requires at least one library path"
        );
        while index < args.len() && !args[index].starts_with('-') {
            output.push("-l".to_owned());
            output.push(args[index].clone());
            index += 1;
        }
    }
    Ok(output)
}

fn list_counterexamples(entrypoint: &Path) -> Result<BTreeSet<PathBuf>> {
    let parent = entrypoint.parent().context("entrypoint has no parent")?;
    let prefix = format!(
        "{}_",
        entrypoint
            .file_name()
            .context("entrypoint has no file name")?
            .to_string_lossy()
    );
    let mut paths = BTreeSet::new();
    for item in fs::read_dir(parent)? {
        let path = item?.path();
        let Some(name) = path.file_name().map(|name| name.to_string_lossy()) else {
            continue;
        };
        if name.starts_with(&prefix) && name.ends_with("_counterexample.json") && path.is_file() {
            paths.insert(fs::canonicalize(path)?);
        }
    }
    Ok(paths)
}

fn preserve_counterexamples(
    plan: &ExperimentPlan,
    scheduler: &OrderedExperimentSummary,
    before: &BTreeMap<String, BTreeSet<PathBuf>>,
    execution_root: &Path,
) -> Result<Vec<CounterexampleArtifact>> {
    let run_by_target = scheduler
        .runs
        .iter()
        .map(|run| (run.target_id.as_str(), run))
        .collect::<BTreeMap<_, _>>();
    let mut artifacts = Vec::new();
    for target in &plan.targets {
        let Some(run) = run_by_target.get(target.target_id.as_str()) else {
            continue;
        };
        let after = list_counterexamples(&target.run_entrypoint)?;
        let old = before
            .get(&target.target_id)
            .context("missing pre-run artifact inventory")?;
        for source in after.difference(old) {
            let directory = execution_root
                .join("counterexample-candidates")
                .join(format!("{:04}", target.rank));
            fs::create_dir_all(&directory)?;
            let destination = directory.join(
                source
                    .file_name()
                    .context("counterexample path has no file name")?,
            );
            fs::copy(source, &destination)?;
            let destination = fs::canonicalize(destination)?;
            artifacts.push(CounterexampleArtifact {
                target_id: target.target_id.clone(),
                run_id: run.result.run_id.clone(),
                original_path: source.clone(),
                sha256: sha256(&fs::read(&destination)?),
                preserved_path: destination,
                classification: "backend-counterexample-candidate-unconfirmed".to_owned(),
            });
        }
    }
    Ok(artifacts)
}

fn load_and_validate_confirmations(
    path: Option<&Path>,
    plan: &ExperimentPlan,
    outcome: &ExperimentOutcome,
) -> Result<Vec<DefectConfirmation>> {
    let Some(path) = path else {
        return Ok(Vec::new());
    };
    let path = fs::canonicalize(path)?;
    let parent = path.parent().context("confirmation file has no parent")?;
    let set: ConfirmationSet =
        serde_json::from_slice(&fs::read(&path)?).context("invalid defect confirmations JSON")?;
    ensure!(
        matches!(set.schema_version, 1 | 2),
        "unsupported confirmation schema version"
    );
    let confirmation_schema_version = set.schema_version;
    let plan_ids = plan
        .targets
        .iter()
        .map(|target| target.target_id.as_str())
        .collect::<BTreeSet<_>>();
    let runs = outcome
        .scheduler
        .runs
        .iter()
        .map(|run| (run.result.run_id.as_str(), run))
        .collect::<BTreeMap<_, _>>();
    let mut unique = BTreeSet::new();
    let mut confirmations = set.confirmations;
    for confirmation in &mut confirmations {
        if confirmation_schema_version == 1 {
            ensure!(
                confirmation.scope != ConfirmationScope::OriginalComponent
                    && confirmation.evidence_origin == EvidenceOrigin::BackendExecution
                    && confirmation.original_component_review.is_none(),
                "original-component reviews and evidence origins require confirmation schema version 2"
            );
        }
        ensure!(
            !confirmation.root_cause_id.trim().is_empty(),
            "confirmation root cause ID must not be empty"
        );
        ensure!(
            plan_ids.contains(confirmation.target_id.as_str()),
            "confirmation target is outside the plan"
        );
        let run = runs
            .get(confirmation.run_id.as_str())
            .context("confirmation references an unknown run")?;
        ensure!(
            run.target_id == confirmation.target_id,
            "confirmation run/target mismatch"
        );
        if confirmation.evidence_origin == EvidenceOrigin::BackendExecution {
            ensure!(
                run.result.status == RunStatus::BugFound,
                "only backend BugFound runs can be confirmed as execution discoveries"
            );
        }
        if confirmation.scope == ConfirmationScope::OriginalComponent {
            ensure!(
                confirmation.original_component_review.is_some(),
                "original-component scope requires a structured original-component review"
            );
        }
        ensure!(
            !confirmation.evidence.is_empty(),
            "confirmation requires at least one evidence file"
        );
        resolve_evidence_paths(&mut confirmation.evidence, parent)?;
        if let Some(review) = &mut confirmation.original_component_review {
            for (name, criterion) in [
                ("input_preconditions", &mut review.input_preconditions),
                (
                    "fixed_original_constraints",
                    &mut review.fixed_original_constraints,
                ),
                (
                    "specified_property_violation",
                    &mut review.specified_property_violation,
                ),
            ] {
                ensure!(
                    !criterion.note.trim().is_empty(),
                    "original-component review criterion {name} requires a note"
                );
                ensure!(
                    !criterion.evidence.is_empty(),
                    "original-component review criterion {name} requires evidence"
                );
                resolve_evidence_paths(&mut criterion.evidence, parent)?;
            }
        }
        ensure!(
            unique.insert((
                confirmation.run_id.clone(),
                confirmation.root_cause_id.clone(),
                confirmation.scope,
                confirmation.evidence_origin,
            )),
            "duplicate defect confirmation"
        );
    }
    Ok(confirmations)
}

fn resolve_evidence_paths(evidence_paths: &mut [PathBuf], parent: &Path) -> Result<()> {
    for evidence in evidence_paths {
        let resolved = if evidence.is_absolute() {
            evidence.clone()
        } else {
            parent.join(&*evidence)
        };
        *evidence = fs::canonicalize(&resolved).with_context(|| {
            format!("confirmation evidence unavailable: {}", resolved.display())
        })?;
        ensure!(
            evidence.is_file(),
            "confirmation evidence must be a file: {}",
            evidence.display()
        );
    }
    Ok(())
}

fn known_target_ranks(plan: &ExperimentPlan) -> Vec<KnownTargetRank> {
    plan.targets
        .iter()
        .filter_map(|target| {
            let root_cause_ids = target
                .definition
                .known_defects
                .iter()
                .filter(|defect| defect.reported)
                .map(|defect| defect.root_cause_id.clone())
                .collect::<BTreeSet<_>>()
                .into_iter()
                .collect::<Vec<_>>();
            (!root_cause_ids.is_empty()).then(|| KnownTargetRank {
                target_id: target.target_id.clone(),
                rank: target.rank,
                root_cause_ids,
            })
        })
        .collect()
}

fn recall_at_k(plan: &ExperimentPlan, known: &BTreeSet<&str>) -> Vec<RecallAtK> {
    let cutoffs = [1, 3, 5, 10, plan.targets.len()]
        .into_iter()
        .map(|cutoff| cutoff.min(plan.targets.len()))
        .filter(|cutoff| *cutoff > 0)
        .collect::<BTreeSet<_>>();
    let total = known.len();
    cutoffs
        .iter()
        .map(|&k| {
            let retrieved = plan
                .targets
                .iter()
                .take(k)
                .filter(|target| known.contains(target.target_id.as_str()))
                .count();
            RecallAtK {
                k,
                retrieved_known_targets: retrieved,
                total_known_targets: total,
                recall: (total > 0).then(|| retrieved as f64 / total as f64),
            }
        })
        .collect()
}

fn status_name(status: &RunStatus) -> String {
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
    .to_owned()
}

pub(crate) fn resolve_executable(path: &Path) -> Result<PathBuf> {
    if path.components().count() > 1 {
        let path = fs::canonicalize(path).context("executable path is unavailable")?;
        ensure!(is_executable_file(&path), "path is not an executable file");
        return Ok(path);
    }
    let search = std::env::var_os("PATH").context("PATH is unavailable")?;
    std::env::split_paths(&search)
        .map(|directory| directory.join(path))
        .find(|candidate| is_executable_file(candidate))
        .map(fs::canonicalize)
        .transpose()?
        .context("executable was not found on PATH")
}

#[cfg(unix)]
fn is_executable_file(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    fs::metadata(path)
        .is_ok_and(|metadata| metadata.is_file() && metadata.permissions().mode() & 0o111 != 0)
}

#[cfg(not(unix))]
fn is_executable_file(path: &Path) -> bool {
    path.is_file()
}

fn absolute_output_path(path: &Path) -> Result<PathBuf> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let parent = fs::canonicalize(parent)?;
    let name = path
        .file_name()
        .context("output path must name a JSON file")?;
    Ok(parent.join(name))
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let temporary = path.with_extension("json.tmp");
    let mut bytes = serde_json::to_vec_pretty(value)?;
    bytes.push(b'\n');
    fs::write(&temporary, bytes)?;
    fs::rename(temporary, path)?;
    Ok(())
}
