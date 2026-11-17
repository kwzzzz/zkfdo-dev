//! L-01 lifting feasibility: connect one component candidate to the call sites of the
//! original entrypoint and decide, per call site, whether a full entrypoint witness that
//! carries the candidate exists and changes the top-level result.
//!
//! Every branch is derived from circuit structure (signal-name sets, R1CS equalities, and
//! `<--` statements); nothing branches on candidate, template, or signal names.

mod bitrange;
mod boost;
pub use boost::BoostOptions;
mod condition;
pub mod instances;
mod predicate;
mod profile_v24;
mod refute;
mod repair;
mod reuse_v25;
mod search_v27;
mod site_probe_identity;
mod site_probe_workspace;
mod site_signal_probe;
pub use site_signal_probe::SiteSignalProbeOptions;
mod solver;
mod source;
mod speed_v24;
mod synth;
mod view_v23;
mod wtns;

use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    process::Command,
    time::{Duration, Instant},
};

use anyhow::{bail, ensure, Context, Result};
use num_bigint::BigUint;
use num_traits::{One, Zero};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use super::r1cs::{R1cs, SymbolTable};
use super::subprocess::run_bounded_logged;
use source::{hint_statements, parse_templates, TemplateDef};

pub const LIFTING_REQUEST_SCHEMA: &str = "zkfdo-lifting-request-v1";
pub const LIFTING_RESULT_SCHEMA: &str = "zkfdo-lifting-result-v1";
const TOOL_TIMEOUT: Duration = Duration::from_secs(600);

pub struct LiftOptions {
    pub request: PathBuf,
    pub output: PathBuf,
    pub cache: Option<PathBuf>,
    pub circom_bin: PathBuf,
    pub node_bin: PathBuf,
    pub snarkjs_bin: PathBuf,
    /// z3 for bounded local solving; when it cannot be found, stage (b) reports
    /// `synthesis_solver_unavailable`.
    pub z3_bin: PathBuf,
    /// Shared assumption-predicate verdicts by (entrypoint, instance), across requests.
    pub instance_store: Option<PathBuf>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LiftRequest {
    schema: String,
    id: String,
    source_root: PathBuf,
    #[serde(default)]
    library_paths: Vec<PathBuf>,
    component_wrapper: PathBuf,
    entrypoint: PathBuf,
    base_input: PathBuf,
    candidate: CandidateRef,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CandidateRef {
    format: CandidateFormat,
    path: PathBuf,
}

#[derive(Debug, Deserialize, Clone, Copy)]
#[serde(rename_all = "snake_case")]
enum CandidateFormat {
    Named,
    Zkfuzz,
}

#[derive(Debug, Serialize, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum Verdict {
    EntrypointViolation,
    /// Second property (L-03): a full witness carrying the candidate's site input values
    /// satisfies the original entrypoint constraints. Says nothing about a project defect.
    AssumptionInputReachable,
    CompatibleNoTopViolationObserved,
    ExcludedInContext,
    Unknown,
    PreparationFailure,
}

impl Verdict {
    fn name(self) -> &'static str {
        match self {
            Verdict::EntrypointViolation => "entrypoint_violation",
            Verdict::AssumptionInputReachable => "assumption_input_reachable",
            Verdict::CompatibleNoTopViolationObserved => "compatible_no_top_violation_observed",
            Verdict::ExcludedInContext => "excluded_in_context",
            Verdict::Unknown => "unknown",
            Verdict::PreparationFailure => "preparation_failure",
        }
    }

    fn conclusive(self) -> bool {
        matches!(
            self,
            Verdict::EntrypointViolation
                | Verdict::AssumptionInputReachable
                | Verdict::CompatibleNoTopViolationObserved
                | Verdict::ExcludedInContext
        )
    }
}

#[derive(Debug, Serialize)]
pub struct LiftResult {
    pub schema: &'static str,
    pub request_id: String,
    pub request_sha256: String,
    pub candidate_sha256: String,
    pub tools: BTreeMap<String, String>,
    /// `tcct_deviation`, `not_tcct_deviation`, or null when preparation failed earlier.
    pub component_classification: Option<String>,
    /// The property the site verdicts answer: `tcct` (does the lifted witness change the
    /// top-level result) or `input_assumption` (can the candidate's site input values occur
    /// in the entrypoint context). Null when no site was evaluated.
    pub property: Option<String>,
    /// L-05 step 1 (input-assumption candidates): the zkFuzz condition the candidate breaks.
    pub violated_condition: Option<condition::ViolatedCondition>,
    pub preparation: Preparation,
    pub component: Option<ComponentSummary>,
    pub entrypoint: Option<EntrypointSummary>,
    pub sites_found: usize,
    pub classes: Vec<ClassResult>,
    pub verdict_counts: BTreeMap<String, usize>,
    pub costs: CostSummary,
}

#[derive(Debug, Serialize)]
pub struct Preparation {
    /// `ok`, or the verdict that applies to the whole request.
    pub status: String,
    pub reason: Option<String>,
    pub detail: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ComponentSummary {
    pub o0_r1cs_sha256: String,
    pub signals: usize,
    pub inputs: usize,
    pub honest_generation: String,
    pub candidate_satisfies_component_o0: Option<bool>,
    pub candidate_names_without_symbol: usize,
    pub deviated_signals: usize,
    pub deviated_hint_signals: usize,
    pub propagated_deviations: usize,
    pub rewritten_statements: Vec<RewriteRecord>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RewriteRecord {
    pub template: String,
    pub file: String,
    pub line: usize,
    pub signal: String,
    pub clauses: usize,
}

#[derive(Debug, Serialize)]
pub struct EntrypointSummary {
    pub r1cs_sha256: String,
    pub sym_sha256: String,
    pub o0_r1cs_sha256: String,
    pub constraints: usize,
    pub public_outputs: usize,
    pub hinted_r1cs_identical: Option<bool>,
    pub hinted_sym_identical: Option<bool>,
    /// When the `.sym` files are not byte-identical: anonymous components renamed (the
    /// files are otherwise equal line by line); None if they differ in any other way.
    pub hinted_sym_anonymous_renames: Option<usize>,
}

#[derive(Debug, Serialize)]
pub struct ClassResult {
    pub pattern: String,
    pub representative: String,
    pub sites: usize,
    pub verdict: Verdict,
    pub reason: String,
    pub inputs: Vec<InputBinding>,
    /// Where the evaluated entrypoint input came from: `base`, `direct` (site inputs bound
    /// to entrypoint inputs), `base_reached`, `synthesized_a`, or `synthesized_b`.
    pub input_origin: Option<String>,
    pub synthesis: Option<SynthesisRecord>,
    pub honest_generation: Option<String>,
    pub deviated_generation: Option<String>,
    pub rust_unsatisfied: Option<usize>,
    pub snarkjs: Option<String>,
    pub public_inputs_equal: Option<bool>,
    pub outputs_differing: Option<usize>,
    pub deviation_sites: Option<usize>,
    pub exceptions: Vec<String>,
    pub evidence: BTreeMap<String, String>,
    /// L-05 step 2: one judgment per broken `LessThan` instance, and their aggregate.
    pub predicates: Vec<predicate::PredicateResult>,
    pub assumption_predicate_verdict: Option<String>,
    pub semantic_deviation_observed: Option<bool>,
}

#[derive(Debug, Serialize, Default)]
pub struct SynthesisRecord {
    pub targets: usize,
    pub a_rounds: usize,
    pub a_tries: usize,
    pub a_paths_found: usize,
    pub b_outcome: Option<String>,
    pub b_cone_unknowns: Option<usize>,
    pub b_cone_constraints: Option<usize>,
    /// Names of the entrypoint inputs changed from the base input (no values).
    pub changed_inputs: Vec<String>,
    /// `honest`, or `hinted_generator` when the honest O0 computation aborted on the input.
    pub reached_with: Option<String>,
    /// Where the reference (unchanged) input aborted, and the kind of failing check.
    pub reference_abort: Option<AbortSite>,
    /// Where the input proposed by the cone model aborted.
    pub model_abort: Option<AbortSite>,
    pub model_comparison_missing: bool,
    pub sweep_branches: Option<usize>,
    pub sweep_end: Option<String>,
    /// The bit-decomposition constraint the reference input violates (diagnostic: found with
    /// every main input of the reference input fixed, so it locates the abort but proves
    /// nothing about other inputs).
    pub abort_instance: Option<String>,
    /// The unresolved cause when the candidate's sweep budget ran out (`budget_exhausted`).
    pub cause_before_budget: Option<String>,
    /// L-04 step 4 hint injection for a model the generator does not reproduce, continued
    /// by L-05 step 3 localization and repair when the injected generator aborts.
    pub injection: Option<repair::RepairRecord>,
    /// L-05 step 3 for a reference input that aborts on a constraint.
    pub repair: Option<repair::RepairRecord>,
    pub note: Option<String>,
}

fn reached_with(deviated: bool) -> String {
    if deviated {
        "hinted_generator"
    } else {
        "honest"
    }
    .to_owned()
}

#[derive(Debug, Serialize, Clone)]
pub struct InputBinding {
    pub component_input: String,
    pub kind: String,
    pub entrypoint_input: Option<String>,
}

#[derive(Debug, Serialize, Default)]
pub struct CostSummary {
    /// Every step by stage; sums to `total_seconds`.
    pub by_stage: BTreeMap<String, f64>,
    /// The subset of steps spent on sites that ended without a conclusive verdict.
    pub failed_attempt_by_stage: BTreeMap<String, f64>,
    pub failed_attempt_seconds: f64,
    pub total_seconds: f64,
    pub wall_seconds: f64,
    pub steps: Vec<Step>,
    pub solver_calls: Vec<solver::Call>,
}

#[derive(Debug, Serialize, Clone)]
pub struct Step {
    pub stage: String,
    pub label: String,
    pub site: Option<String>,
    pub seconds: f64,
    pub status: String,
    pub cached: bool,
}

/// Ends a request before (or instead of) per-site evaluation. `status` is a verdict name,
/// or `not_tcct_deviation` for a candidate that equals the honest component computation.
struct Failure {
    status: &'static str,
    reason: &'static str,
    detail: String,
}

const NOT_TCCT_DEVIATION: &str = "not_tcct_deviation";

fn prep(reason: &'static str) -> impl FnOnce(anyhow::Error) -> Failure {
    move |error| Failure {
        status: Verdict::PreparationFailure.name(),
        reason,
        detail: format!("{error:#}"),
    }
}

struct Tools {
    circom: PathBuf,
    node: PathBuf,
    snarkjs: PathBuf,
    verified_digests: Option<reuse_v25::ToolDigests>,
}

impl Tools {
    fn key_digest(&self, path: &Path) -> Result<String> {
        match &self.verified_digests {
            Some(digests) => digests.digest(path),
            None => sha256_file(path),
        }
    }

    fn check_tool_identity(&self, path: &Path) -> Result<()> {
        if let Some(digests) = &self.verified_digests {
            digests.check_identity(path)?;
        }
        Ok(())
    }
}

struct Ledger {
    steps: Vec<Step>,
    site: Option<String>,
}

impl Ledger {
    fn record(&mut self, stage: &str, label: &str, seconds: f64, status: &str, cached: bool) {
        profile_v24::record_ledger_coverage(seconds);
        self.steps.push(Step {
            stage: stage.to_owned(),
            label: label.to_owned(),
            site: self.site.clone(),
            seconds,
            status: status.to_owned(),
            cached,
        });
    }

    /// Records `elapsed` minus the steps recorded since `from`, for a step that encloses them.
    fn record_remainder(
        &mut self,
        from: usize,
        stage: &str,
        label: &str,
        elapsed: f64,
        status: &str,
        cached: bool,
    ) {
        // The full enclosing interval covers its nested steps and its remainder.
        // The sidecar takes the union, so nested coverage is counted only once.
        profile_v24::record_ledger_coverage(elapsed);
        let nested: f64 = self.steps[from..].iter().map(|step| step.seconds).sum();
        self.record(stage, label, (elapsed - nested).max(0.0), status, cached);
    }

    fn timed<T>(&mut self, stage: &str, label: &str, work: impl FnOnce() -> T) -> T {
        let _profile_span = profile_v24::span(label);
        let started = Instant::now();
        let value = work();
        self.record(stage, label, started.elapsed().as_secs_f64(), "ok", false);
        value
    }
}

#[derive(Clone)]
struct Compiled {
    r1cs: PathBuf,
    sym: PathBuf,
    js_dir: Option<PathBuf>,
    stem: String,
}

pub fn lift(options: &LiftOptions) -> Result<LiftResult> {
    lift_impl(options, None, &BoostOptions::default())
}

/// Separate v2.3 entry point. Requests without the new view take lift unchanged.
pub fn lift_v23(options: &LiftOptions) -> Result<LiftResult> {
    lift_v23_with_boost(options, &BoostOptions::default())
}

/// Optional diagnostics and completion, reported separately from the legacy verdicts.
pub fn lift_v23_with_boost(options: &LiftOptions, boost: &BoostOptions) -> Result<LiftResult> {
    let bytes = fs::read(&options.request)?;
    let Some((normalized, reference)) = view_v23::decode(&bytes)? else {
        return lift_impl(options, None, boost);
    };
    let base = options.request.parent().context("request has no parent")?;
    let view = view_v23::load(&reference, base)?;
    lift_impl(options, Some((normalized, view, reference.sha256)), boost)
}

/// Development-only speed path. Strategy order and all search budgets remain unchanged.
/// `jobs` controls independent full-R1CS checks, not speculative synthesis strategies.
pub fn lift_v24_with_boost(
    options: &LiftOptions,
    boost: &BoostOptions,
    jobs: usize,
) -> Result<LiftResult> {
    let _profiler = profile_v24::activate()?;
    let _guard = speed_v24::activate(jobs)?;
    let started = Instant::now();
    let cpu_before = speed_cpu_usage()?;
    let result = lift_v23_with_boost(options, boost)?;
    let cpu_after = speed_cpu_usage()?;
    let partition = profile_v24::finish()?;
    write_json(
        &options.output.join("j-speed.json"),
        &serde_json::json!({
            "schema": "zkfdo-j-speed-v2.4",
            "j_jobs": jobs,
            "parallel_scope": "independent_r1cs_constraints",
            "strategy_order": "v2.3_sequential",
            "wall_seconds": started.elapsed().as_secs_f64(),
            "cpu_self_seconds": cpu_after.0 - cpu_before.0,
            "cpu_children_seconds": cpu_after.1 - cpu_before.1,
            "cpu_total_seconds": cpu_after.0 + cpu_after.1 - cpu_before.0 - cpu_before.1,
            "measurement_scope": "lift including artifact release; excludes sidecar write; use external wait4 for total cost",
            "runtime": speed_v24::telemetry(),
            "partition": partition,
        }),
    )?;
    Ok(result)
}

/// Development-only v2.5: request-local verified key digests and lazy rewrite structure.
/// Existing v2.3/v2.4 entrypoints never activate this state.
pub fn lift_v25_with_boost(
    options: &LiftOptions,
    boost: &BoostOptions,
    jobs: usize,
) -> Result<LiftResult> {
    let _profiler = profile_v24::activate()?;
    let _speed = speed_v24::activate(jobs)?;
    let _reuse = reuse_v25::activate()?;
    let started = Instant::now();
    let before = speed_cpu_usage()?;
    let result = lift_v23_with_boost(options, boost)?;
    let after = speed_cpu_usage()?;
    let partition = profile_v24::finish()?;
    write_json(
        &options.output.join("j-speed.json"),
        &serde_json::json!({
            "schema": "zkfdo-j-speed-v2.5",
            "j_jobs": jobs,
            "parallel_scope": "independent_r1cs_constraints",
            "strategy_order": "v2.3_sequential",
            "wall_seconds": started.elapsed().as_secs_f64(),
            "cpu_self_seconds": after.0 - before.0,
            "cpu_children_seconds": after.1 - before.1,
            "cpu_total_seconds": after.0 + after.1 - before.0 - before.1,
            "measurement_scope": "lift including artifact release; excludes sidecar write; use external wait4 for total cost",
            "runtime": speed_v24::telemetry(),
            "reuse": reuse_v25::telemetry(),
            "partition": partition,
        }),
    )?;
    Ok(result)
}

/// Opt-in search corrections; the v2.5 verdict gates remain shared.
pub fn lift_v27_with_boost(
    options: &LiftOptions,
    boost: &BoostOptions,
    jobs: usize,
) -> Result<LiftResult> {
    lift_v27_with_repair_limit(options, boost, jobs, None)
}

/// The optional limit applies to candidate repair only and is fixed for this request.
pub fn lift_v27_with_repair_limit(
    options: &LiftOptions,
    boost: &BoostOptions,
    jobs: usize,
    repair_iteration_limit: Option<usize>,
) -> Result<LiftResult> {
    ensure!(
        boost.class_sweep_budget_seconds.is_none(),
        "v2.7 reserves a shared request sweep budget; per-class budget overrides are unsupported"
    );
    ensure!(
        !options.output.exists(),
        "output directory {} already exists",
        options.output.display()
    );
    let _search = match repair_iteration_limit {
        Some(limit) => search_v27::activate_with_limit(limit)?,
        None => search_v27::activate()?,
    };
    let _profiler = profile_v24::activate()?;
    let _speed = speed_v24::activate(jobs)?;
    let _reuse = reuse_v25::activate()?;
    let result = lift_v23_with_boost(options, boost);
    if let Err(error) = &result {
        search_v27::record(
            serde_json::json!({"kind":"request_error", "detail":format!("{error:#}")}),
        );
    }
    let partition = profile_v24::finish()?;
    if options.output.is_dir() {
        search_v27::write(&options.output)?;
        write_json(
            &options.output.join("j-speed.json"),
            &serde_json::json!({
                "schema":"zkfdo-j-speed-v2.7", "j_jobs":jobs,
                "parallel_scope":"independent_r1cs_constraints", "strategy_order":"v2.7_sequential",
                "runtime":speed_v24::telemetry(), "reuse":reuse_v25::telemetry(), "partition":partition,
            }),
        )?;
    }
    result
}

/// Optional baseline-input observation after all classification files have been saved.
pub fn lift_v28_with_probe(
    options: &LiftOptions,
    boost: &BoostOptions,
    jobs: usize,
    repair_iteration_limit: Option<usize>,
    probe: &SiteSignalProbeOptions,
) -> Result<LiftResult> {
    let _version = site_signal_probe::activate(probe.enabled)?;
    let result = lift_v27_with_repair_limit(options, boost, jobs, repair_iteration_limit)?;
    if probe.enabled {
        site_signal_probe::run(options, probe, &result)?;
    }
    Ok(result)
}

/// Measurement-only development mode: legacy arithmetic, no reuse, unchanged strategies.
/// The frozen v2.3 executable and its output directories are never modified.
pub fn profile_v23_with_boost(options: &LiftOptions, boost: &BoostOptions) -> Result<LiftResult> {
    let _profiler = profile_v24::activate()?;
    let started = Instant::now();
    let before = speed_cpu_usage()?;
    let result = lift_v23_with_boost(options, boost)?;
    let after = speed_cpu_usage()?;
    let partition = profile_v24::finish()?;
    write_json(
        &options.output.join("j-profile.json"),
        &serde_json::json!({
            "schema": "zkfdo-j-profile-v1", "mode": "legacy_measurement_only",
            "wall_seconds": started.elapsed().as_secs_f64(),
            "cpu_self_seconds": after.0 - before.0,
            "cpu_children_seconds": after.1 - before.1,
            "cpu_total_seconds": after.0 + after.1 - before.0 - before.1,
            "partition": partition,
        }),
    )?;
    Ok(result)
}

#[cfg(unix)]
fn speed_cpu_usage() -> Result<(f64, f64)> {
    let usage = |who| -> Result<f64> {
        let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
        // getrusage initializes the provided rusage on success. Children include
        // reaped compiler/solver/witness processes; self includes worker threads.
        let status = unsafe { libc::getrusage(who, usage.as_mut_ptr()) };
        ensure!(
            status == 0,
            "getrusage: {}",
            std::io::Error::last_os_error()
        );
        let usage = unsafe { usage.assume_init() };
        Ok(usage.ru_utime.tv_sec as f64
            + usage.ru_utime.tv_usec as f64 / 1_000_000.0
            + usage.ru_stime.tv_sec as f64
            + usage.ru_stime.tv_usec as f64 / 1_000_000.0)
    };
    Ok((usage(libc::RUSAGE_SELF)?, usage(libc::RUSAGE_CHILDREN)?))
}

#[cfg(not(unix))]
fn speed_cpu_usage() -> Result<(f64, f64)> {
    bail!("J v2.4 requires Unix process CPU accounting")
}

fn check_constraints(r1cs: &R1cs, assignment: &[BigUint]) -> Result<Vec<usize>> {
    let _profile_span = profile_v24::span("r1cs_check");
    if speed_v24::enabled() {
        let started = Instant::now();
        let result = r1cs.failed_constraint_indices_with_jobs(assignment, speed_v24::jobs());
        speed_v24::record_check(started.elapsed().as_secs_f64());
        result
    } else {
        r1cs.failed_constraint_indices(assignment)
    }
}

fn lift_impl(
    options: &LiftOptions,
    view: Option<(Vec<u8>, view_v23::View, String)>,
    boost_options: &BoostOptions,
) -> Result<LiftResult> {
    let _profile_span = profile_v24::span("lift_impl");
    let boost = boost::State::new(boost_options.clone());
    solver::reset();
    ensure!(
        !options.output.exists(),
        "output directory {} already exists",
        options.output.display()
    );
    fs::create_dir_all(options.output.join("raw"))?;
    let started = Instant::now();
    let request_bytes = fs::read(&options.request)
        .with_context(|| format!("read request {}", options.request.display()))?;
    let parse_bytes = view
        .as_ref()
        .map(|(bytes, _, _)| bytes.as_slice())
        .unwrap_or(&request_bytes);
    let request: LiftRequest = serde_json::from_slice(parse_bytes).context("parse request")?;
    ensure!(
        request.schema == LIFTING_REQUEST_SCHEMA,
        "unsupported request schema {}",
        request.schema
    );
    let base = options
        .request
        .parent()
        .context("request has no parent directory")?
        .to_path_buf();
    let tools = Tools {
        circom: resolve_executable(&options.circom_bin)?,
        node: resolve_executable(&options.node_bin)?,
        snarkjs: resolve_executable(&options.snarkjs_bin)?,
        verified_digests: reuse_v25::enabled().then(reuse_v25::ToolDigests::default),
    };
    let mut tool_hashes = BTreeMap::new();
    for (name, path) in [
        ("circom", &tools.circom),
        ("node", &tools.node),
        ("snarkjs", &tools.snarkjs),
    ] {
        tool_hashes.insert(format!("{name}_sha256"), tools.key_digest(path)?);
    }
    let candidate_path = base.join(&request.candidate.path);
    let mut result = LiftResult {
        schema: if site_signal_probe::version_enabled() {
            "zkfdo-lifting-result-v2.8"
        } else if search_v27::enabled() {
            "zkfdo-lifting-result-v2.7"
        } else if reuse_v25::enabled() {
            "zkfdo-lifting-result-v2.5"
        } else if speed_v24::enabled() {
            "zkfdo-lifting-result-v2.4"
        } else if view.is_some() {
            "zkfdo-lifting-result-v2.3"
        } else {
            LIFTING_RESULT_SCHEMA
        },
        request_id: request.id.clone(),
        request_sha256: sha256_bytes(&request_bytes),
        candidate_sha256: sha256_file(&candidate_path)?,
        tools: tool_hashes,
        component_classification: None,
        property: None,
        violated_condition: None,
        preparation: Preparation {
            status: "ok".to_owned(),
            reason: None,
            detail: None,
        },
        component: None,
        entrypoint: None,
        sites_found: 0,
        classes: Vec::new(),
        verdict_counts: BTreeMap::new(),
        costs: CostSummary::default(),
    };
    if let Some((_, _, hash)) = &view {
        result
            .tools
            .insert("component_view_spec_sha256".into(), hash.clone());
    }
    let mut ledger = Ledger {
        steps: Vec::new(),
        site: None,
    };
    let outcome = run_lift(
        &request,
        &base,
        &candidate_path,
        &tools,
        options,
        &mut ledger,
        &mut result,
        view.as_ref().map(|(_, spec, _)| spec),
        &boost,
    );
    if let Err(failure) = outcome {
        result.preparation.status = failure.status.to_owned();
        result.preparation.reason = Some(failure.reason.to_owned());
        result.preparation.detail = Some(failure.detail);
    }
    for class in &result.classes {
        *result
            .verdict_counts
            .entry(class.verdict.name().to_owned())
            .or_default() += 1;
    }
    let failed_sites = result
        .classes
        .iter()
        .filter(|class| !class.verdict.conclusive())
        .map(|class| class.representative.clone())
        .collect::<BTreeSet<_>>();
    let mut by_stage = BTreeMap::new();
    let mut failed_attempt_by_stage = BTreeMap::new();
    for step in &ledger.steps {
        *by_stage.entry(step.stage.clone()).or_insert(0.0) += step.seconds;
        if step
            .site
            .as_ref()
            .is_some_and(|site| failed_sites.contains(site))
        {
            *failed_attempt_by_stage
                .entry(step.stage.clone())
                .or_insert(0.0) += step.seconds;
        }
    }
    let wall_ended = Instant::now();
    profile_v24::record_legacy_window(started, wall_ended);
    result.costs = CostSummary {
        total_seconds: by_stage.values().sum(),
        failed_attempt_seconds: failed_attempt_by_stage.values().sum(),
        failed_attempt_by_stage,
        by_stage,
        wall_seconds: wall_ended.duration_since(started).as_secs_f64(),
        steps: ledger.steps,
        solver_calls: solver::take(),
    };
    let text = serde_json::to_string_pretty(&result)?;
    fs::write(options.output.join("result.json"), format!("{text}\n"))?;
    boost.write(&options.output)?;
    Ok(result)
}

#[allow(clippy::too_many_arguments)]
fn run_lift(
    request: &LiftRequest,
    base: &Path,
    candidate_path: &Path,
    tools: &Tools,
    options: &LiftOptions,
    ledger: &mut Ledger,
    result: &mut LiftResult,
    view: Option<&view_v23::View>,
    boost: &boost::State,
) -> std::result::Result<(), Failure> {
    let _profile_span = profile_v24::span("preparation_and_unassigned");
    let raw = options.output.join("raw");
    let source_root = fs::canonicalize(base.join(&request.source_root))
        .context("resolve source root")
        .map_err(prep("source_root_missing"))?;
    let libraries = request
        .library_paths
        .iter()
        .map(|path| fs::canonicalize(base.join(path)).context("resolve library path"))
        .collect::<Result<Vec<_>>>()
        .map_err(prep("library_missing"))?;
    let wrapper = fs::canonicalize(base.join(&request.component_wrapper))
        .context("resolve component wrapper")
        .map_err(prep("component_wrapper_missing"))?;
    let entrypoint = fs::canonicalize(base.join(&request.entrypoint))
        .context("resolve entrypoint")
        .map_err(prep("entrypoint_missing"))?;
    for path in [&wrapper, &entrypoint] {
        if !path.starts_with(&source_root) {
            return Err(Failure {
                status: Verdict::PreparationFailure.name(),
                reason: "source_outside_root",
                detail: format!("{} is outside the source root", path.display()),
            });
        }
    }
    if let Some(view) = view {
        view.validate_wrapper(&wrapper, base)
            .map_err(prep("component_view_invalid"))?;
    }
    let base_input: Value = serde_json::from_slice(
        &fs::read(base.join(&request.base_input))
            .context("read base input")
            .map_err(prep("base_input_missing"))?,
    )
    .context("parse base input")
    .map_err(prep("base_input_invalid"))?;
    let candidate = load_candidate(candidate_path, request.candidate.format)
        .map_err(prep("candidate_invalid"))?;

    // Component: honest witness for the candidate's inputs and the deviated signals.
    let component = compile(
        tools,
        &wrapper,
        &raw.join("component-o0"),
        &source_root,
        &libraries,
        true,
        true,
        ledger,
        None,
    )
    .map_err(prep("component_compile_failed"))?;
    let (component_r1cs, component_sym) = ledger
        .timed("site_discovery", "parse component artifacts", || {
            load_artifacts(&component)
        })
        .map_err(prep("component_artifacts_invalid"))?;
    let component_inputs = main_signals(
        &component_r1cs,
        &component_sym,
        1 + component_r1cs.shape.public_outputs,
        component_r1cs.shape.public_inputs + component_r1cs.shape.private_inputs,
    )
    .map_err(prep("component_inputs_unresolved"))?;
    let component_outputs = main_signals(
        &component_r1cs,
        &component_sym,
        1,
        component_r1cs.shape.public_outputs,
    )
    .map_err(prep("component_outputs_unresolved"))?;
    let mut input_leaves = Vec::new();
    for name in &component_inputs {
        let value = candidate
            .get(name)
            .with_context(|| format!("candidate has no value for input {name}"))
            .map_err(prep("candidate_missing_signals"))?;
        input_leaves.push((name.trim_start_matches("main.").to_owned(), value.clone()));
    }
    let honest_input = raw.join("component-honest-input.json");
    write_json(
        &honest_input,
        &build_input(&input_leaves).map_err(prep("candidate_invalid"))?,
    )
    .map_err(prep("io"))?;
    let honest_component = generate_witness(
        tools,
        &component,
        &honest_input,
        &raw.join("component-honest.wtns"),
        &component_r1cs.prime,
        ledger,
        "site_discovery",
        "component honest witness",
    )
    .map_err(prep("component_witness_failed"))?;

    // The complete raw assignment and all forwarding constraints are checked before
    // dropping wrapper-only names. Projection keeps the original O0 wire positions.
    let projected = view
        .map(|view| {
            view_v23::project(
                &view.target_prefix,
                &component_r1cs,
                &component_sym,
                &candidate,
                &component_inputs,
                &component_outputs,
            )
        })
        .transpose()
        .map_err(prep("component_view_projection_failed"))?;
    let (candidate, component_sym) = if let Some(projected) = projected {
        result.tools.insert(
            "component_view_forwarding_equalities".into(),
            projected.forwarding_equalities.to_string(),
        );
        (projected.candidate, projected.symbols)
    } else {
        (candidate, component_sym)
    };
    let (deviated, unmatched, mut satisfies) =
        ledger.timed("site_discovery", "component deviation", || {
            component_deviation(
                &candidate,
                &component_r1cs,
                &component_sym,
                honest_component.as_ref(),
            )
        });
    if view.is_some() {
        satisfies = Some(true);
    } // Entire raw wrapper was validated above.
    let mut summary = ComponentSummary {
        o0_r1cs_sha256: sha256_file(&component.r1cs).map_err(prep("io"))?,
        signals: component_sym.by_name.len(),
        inputs: component_inputs.len(),
        honest_generation: if honest_component.is_some() {
            "ok"
        } else {
            "aborted"
        }
        .to_owned(),
        candidate_satisfies_component_o0: satisfies,
        candidate_names_without_symbol: unmatched,
        deviated_signals: deviated.len(),
        deviated_hint_signals: 0,
        propagated_deviations: 0,
        rewritten_statements: Vec::new(),
    };
    if satisfies == Some(false) {
        result.component = Some(summary);
        return Err(Failure {
            status: Verdict::Unknown.name(),
            reason: "candidate_violates_component_constraints",
            detail: "the candidate does not satisfy the component's own constraints".to_owned(),
        });
    }
    // A candidate equal to the honest component computation is not a TCCT deviation. It is
    // not lifted for the TCCT property; its site inputs are judged for the second property
    // (can they occur in the entrypoint context), reported separately.
    let property = if honest_component.is_some() && deviated.is_empty() {
        result.component_classification = Some(NOT_TCCT_DEVIATION.to_owned());
        Property::InputAssumption
    } else {
        result.component_classification = Some("tcct_deviation".to_owned());
        Property::Tcct
    };

    // Templates of the source closure, and the hint rewrite.
    let closure = ledger
        .timed("site_discovery", "source closure", || {
            let mut files = BTreeSet::new();
            for root in [&wrapper, &entrypoint] {
                files.extend(crate::targets::discovery_dependency_paths(
                    root,
                    &source_root,
                    &libraries,
                )?);
            }
            Ok::<_, anyhow::Error>(files)
        })
        .map_err(prep("source_closure_unresolved"))?;
    let mut sources = BTreeMap::new();
    let mut templates = Vec::new();
    for file in &closure {
        let text = fs::read_to_string(file)
            .with_context(|| format!("read {}", file.display()))
            .map_err(prep("io"))?;
        templates.extend(parse_templates(file, &text).map_err(prep("source_parse_failed"))?);
        sources.insert(file.clone(), text);
    }
    if let Some(view) = view {
        let deduplicated;
        let definitions = if search_v27::enabled() {
            let target = fs::canonicalize(base.join(&view.target_source))
                .map_err(|error| prep("component_view_definition_invalid")(error.into()))?;
            deduplicated =
                search_v27::view_definitions(&templates, &sources, &target, &view.target_template);
            &deduplicated
        } else {
            &templates
        };
        view.validate_definition(base, definitions)
            .map_err(prep("component_view_definition_invalid"))?;
    }
    let main_template = view
        .map(|view| view.target_template.clone())
        .or_else(|| main_template_name(&sources[&wrapper]));
    let honest_aborted = honest_component.is_none();

    // L-05 step 1: which zkFuzz condition does an honest-equal candidate break? L-07: the
    // component's LessThan instances are the predicate targets when no broken one is known
    // (the candidate is rejected by the component, or breaks none).
    let mut component_lessthan = Vec::new();
    if property == Property::InputAssumption || honest_aborted {
        let mut names = condition::TemplateNames::new(
            &component_sym,
            &templates,
            &sources,
            main_template.clone(),
        );
        component_lessthan = condition::lessthan_instances(&mut names).0;
    }
    if property == Property::InputAssumption {
        let started = Instant::now();
        let mut names = condition::TemplateNames::new(
            &component_sym,
            &templates,
            &sources,
            main_template.clone(),
        );
        let value = |name: &str| {
            candidate.get(name).cloned().or_else(|| {
                let wire = usize::try_from(component_sym.by_name.get(name)?.wire).ok()?;
                honest_component.as_ref()?.get(wire).cloned()
            })
        };
        result.violated_condition = Some(condition::reconstruct(
            &mut names,
            &value,
            honest_component.is_some(),
        ));
        ledger.record(
            "condition",
            "reconstruct the violated condition",
            started.elapsed().as_secs_f64(),
            "ok",
            false,
        );
    }
    let started = Instant::now();
    let component_rewrite_structure = reuse_v25::enabled()
        .then(|| reuse_v25::RewriteStructure::new(&component_sym, &templates, &sources));
    let plan = plan_rewrites(
        &candidate,
        &component_sym,
        &deviated,
        honest_aborted,
        &templates,
        &sources,
        main_template.as_deref(),
        component_rewrite_structure.as_ref(),
    );
    ledger.record(
        "site_discovery",
        "plan hint rewrites",
        started.elapsed().as_secs_f64(),
        if plan.is_ok() { "ok" } else { "failed" },
        false,
    );
    drop(component_rewrite_structure);
    if search_v27::enabled() {
        if let Err(failure) = &plan {
            search_v27::record(serde_json::json!({
                "kind":"component_preparation_failure", "reason":failure.reason,
                "component":summary, "deviated_signals":deviated,
                "assignment_operators":search_v27::assignment_operators(&deviated, &templates, &sources),
            }));
        }
    }
    let mut plan = plan?;
    if search_v27::enabled() {
        source::map_edits_to_entrypoint(
            &mut plan.edits,
            &templates,
            &sources,
            &entrypoint,
            &source_root,
            &libraries,
        )
        .map_err(prep("entrypoint_definition_rewrite_failed"))?;
    }
    summary.deviated_hint_signals = plan.hint_suffixes.len();
    summary.propagated_deviations = plan.propagated;
    summary.rewritten_statements = plan
        .records
        .iter()
        .map(|record| RewriteRecord {
            template: record.template.clone(),
            file: display_relative(&record.file, &source_root, &libraries),
            line: record.line,
            signal: record.signal.clone(),
            clauses: record.clauses,
        })
        .collect();
    result.component = Some(summary);

    // Entrypoint artifacts: original (O1, with generator), O0 for bindings, and hinted.
    let original = compile_cached(
        tools,
        &entrypoint,
        &source_root,
        &libraries,
        &closure,
        false,
        options.cache.as_deref(),
        &raw.join("entry-original"),
        ledger,
    )
    .map_err(prep("entrypoint_compile_failed"))?;
    let original_o0 = compile_cached(
        tools,
        &entrypoint,
        &source_root,
        &libraries,
        &closure,
        true,
        options.cache.as_deref(),
        &raw.join("entry-o0"),
        ledger,
    )
    .map_err(prep("entrypoint_compile_failed"))?;
    let (entry_r1cs, entry_sym) = ledger
        .timed("site_discovery", "parse entrypoint artifacts", || {
            load_artifacts(&original)
        })
        .map_err(prep("entrypoint_artifacts_invalid"))?;
    let (entry_o0_r1cs, entry_o0_sym) = ledger
        .timed("site_discovery", "parse entrypoint O0 artifacts", || {
            load_artifacts(&original_o0)
        })
        .map_err(prep("entrypoint_artifacts_invalid"))?;
    let mut entry_summary = EntrypointSummary {
        r1cs_sha256: sha256_file(&original.r1cs).map_err(prep("io"))?,
        sym_sha256: sha256_file(&original.sym).map_err(prep("io"))?,
        o0_r1cs_sha256: sha256_file(&original_o0.r1cs).map_err(prep("io"))?,
        constraints: entry_r1cs.shape.constraints,
        public_outputs: entry_r1cs.shape.public_outputs,
        hinted_r1cs_identical: None,
        hinted_sym_identical: None,
        hinted_sym_anonymous_renames: None,
    };
    let entry_summary_key = (
        entry_summary.r1cs_sha256.clone(),
        entry_summary.sym_sha256.clone(),
        entry_summary.o0_r1cs_sha256.clone(),
    );

    // Call sites: instances whose complete signal-name set equals the component's.
    let sites = ledger.timed("site_discovery", "enumerate call sites", || {
        enumerate_sites(&component_sym, &entry_o0_sym)
    });
    result.sites_found = sites.len();
    if sites.is_empty() {
        result.entrypoint = Some(entry_summary);
        return Err(Failure {
            status: Verdict::PreparationFailure.name(),
            reason: "no_call_site",
            detail: "no entrypoint instance has the component's signal-name set".to_owned(),
        });
    }
    let bindings = ledger.timed("site_discovery", "index equality bindings", || {
        EqualityIndex::build(&entry_o0_r1cs)
    });
    let original_bindings = ledger.timed("site_discovery", "index original equalities", || {
        EqualityIndex::build(&entry_r1cs)
    });
    let z3 = resolve_executable(&options.z3_bin).ok();
    let classes = ledger.timed("site_discovery", "group site classes", || {
        group_sites(&sites, |site| {
            bind_site(
                site,
                &component_inputs,
                &candidate,
                &bindings,
                &entry_o0_sym,
                None,
            )
            .signature()
        })
    });

    site_signal_probe::capture(|| site_signal_probe::Seed {
        source_root: source_root.clone(),
        libraries: libraries.clone(),
        wrapper: wrapper.clone(),
        entrypoint: entrypoint.clone(),
        base_input: base_input.clone(),
        base_input_path: base.join(&request.base_input),
        candidate: candidate.clone(),
        component: component.clone(),
        component_r1cs: component_r1cs.clone(),
        component_sym: component_sym.clone(),
        component_inputs: component_inputs.clone(),
        component_outputs: component_outputs.clone(),
        original: original.clone(),
        original_o0: original_o0.clone(),
        entry_r1cs: entry_r1cs.clone(),
        entry_sym: entry_sym.clone(),
        entry_o0_r1cs: entry_o0_r1cs.clone(),
        entry_o0_sym: entry_o0_sym.clone(),
        templates: templates.clone(),
        sources: sources.clone(),
        main_template: main_template.clone(),
        hint_suffixes: plan.hint_suffixes.clone(),
        sites: sites.clone(),
        signatures: sites
            .iter()
            .map(|site| {
                (
                    site.clone(),
                    bind_site(
                        site,
                        &component_inputs,
                        &candidate,
                        &bindings,
                        &entry_o0_sym,
                        None,
                    )
                    .signature(),
                )
            })
            .collect(),
        supported: property == Property::Tcct
            && !honest_aborted
            && !plan.hint_suffixes.is_empty()
            && component_outputs.iter().any(|name| deviated.contains(name)),
        concrete_arguments: view.map(|view| view.concrete_arguments.clone()),
    });

    // Hinted generator: same constraints, candidate values returned by the rewritten hints.
    // An honest candidate needs no rewrite; the original generator then carries it.
    let mut hinted = None;
    let mut hint_tree = None;
    if !plan.edits.is_empty() {
        let workspace = raw.join("hint-workspace");
        let started = Instant::now();
        let prepared = write_hint_workspace(&workspace, &source_root, &libraries, &sources, &plan);
        ledger.record(
            "compile",
            "write hint workspace",
            started.elapsed().as_secs_f64(),
            if prepared.is_ok() { "ok" } else { "failed" },
            false,
        );
        let (hint_root, hint_libraries) = prepared.map_err(prep("io"))?;
        let entry_relative = entrypoint.strip_prefix(&source_root).unwrap_or(&entrypoint);
        let hint_entry = hint_root.join(entry_relative);
        let key = match options.cache.as_deref() {
            Some(cache) => Some((
                cache,
                edits_key(
                    tools,
                    entry_relative,
                    &source_root,
                    &libraries,
                    &sources,
                    &plan.edits,
                    false,
                )
                .map_err(prep("io"))?,
            )),
            None => None,
        };
        let compiled = compile_edited(
            tools,
            key,
            &hint_entry,
            &raw.join("entry-hinted"),
            &hint_root,
            &hint_libraries,
            false,
            ledger,
            "compile hinted entrypoint",
        )
        .map_err(prep("hinted_compile_failed"))?;
        let invariant_span = profile_v24::span("initial_artifact_invariants");
        let same_r1cs =
            artifact_bytes_equal("r1cs_bytes_read_compare", &compiled.r1cs, &original.r1cs)
                .map_err(prep("io"))?;
        let same_sym = artifact_bytes_equal("sym_bytes_read_compare", &compiled.sym, &original.sym)
            .map_err(prep("io"))?;
        entry_summary.hinted_r1cs_identical = Some(same_r1cs);
        entry_summary.hinted_sym_identical = Some(same_sym);
        // circom names anonymous components by source byte offset, so a longer rewritten
        // statement earlier in the same file renames them without changing any signal.
        let renamed = repair::sym_equivalence(
            &fs::read_to_string(&original.sym).map_err(|e| prep("io")(e.into()))?,
            &fs::read_to_string(&compiled.sym).map_err(|e| prep("io")(e.into()))?,
        );
        entry_summary.hinted_sym_anonymous_renames = renamed.as_ref().ok().copied();
        if !(same_r1cs && renamed.is_ok()) {
            result.entrypoint = Some(entry_summary);
            return Err(Failure {
                status: Verdict::PreparationFailure.name(),
                reason: "hint_changes_constraints",
                detail: "the hinted entrypoint does not compile to the original R1CS and SYM"
                    .to_owned(),
            });
        }
        drop(invariant_span);
        hinted = Some(compiled);
        hint_tree = Some((hint_entry, hint_root, hint_libraries));
    }
    result.entrypoint = Some(entry_summary);

    let entry_templates;
    let evaluation_templates = if search_v27::enabled() {
        let entry_closure =
            crate::targets::discovery_dependency_paths(&entrypoint, &source_root, &libraries)
                .map_err(prep("source_closure_unresolved"))?
                .into_iter()
                .collect::<BTreeSet<_>>();
        entry_templates = templates
            .iter()
            .filter(|template| entry_closure.contains(&template.file))
            .cloned()
            .collect::<Vec<_>>();
        &entry_templates
    } else {
        &templates
    };
    let mut context = EvalContext {
        boost,
        component_main_template: main_template.clone(),
        sites: &sites,
        component_inputs: &component_inputs,
        component_outputs: &component_outputs,
        range_index: None,
        candidate: &candidate,
        plan: &plan,
        base_input: &base_input,
        bindings: &bindings,
        original_bindings: &original_bindings,
        entry_o0_sym: &entry_o0_sym,
        rewrite_structure: reuse_v25::enabled().then(|| {
            reuse_v25::RewriteStructure::new(&entry_o0_sym, evaluation_templates, &sources)
        }),
        entry_o0_r1cs: &entry_o0_r1cs,
        o0_constraint_index: None,
        entry_r1cs: &entry_r1cs,
        entry_sym: &entry_sym,
        original: &original,
        original_o0: &original_o0,
        hinted: hinted.as_ref().unwrap_or(&original),
        hint_tree,
        hinted_o0: None,
        constraint_index: None,
        tools,
        z3: z3.as_deref(),
        raw: &raw,
        templates: evaluation_templates,
        sources: &sources,
        property,
        source_root: &source_root,
        libraries: &libraries,
        cache: options.cache.as_deref(),
        instance_store: options.instance_store.as_deref(),
        entry_key: format!(
            "v2:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}",
            entry_summary_key.0,
            entry_summary_key.1,
            entry_summary_key.2,
            sha256_file(&original_o0.sym).map_err(prep("io"))?,
            sha256_bytes(
                &serde_json::to_vec(&base_input).map_err(|error| prep("io")(error.into()))?
            ),
            tools.key_digest(&tools.circom).map_err(prep("io"))?,
            tools.key_digest(&tools.node).map_err(prep("io"))?,
            tools.key_digest(&tools.snarkjs).map_err(prep("io"))?,
            z3.as_ref()
                .map(|path| sha256_file(path))
                .transpose()
                .map_err(prep("io"))?
                .unwrap_or_else(|| "unavailable".to_owned()),
            std::env::current_exe()
                .ok()
                .and_then(|path| sha256_file(&path).ok())
                .unwrap_or_else(|| "unavailable".to_owned()),
            sha256_bytes(
                concat!(
                    include_str!("mod.rs"),
                    include_str!("repair.rs"),
                    include_str!("synth.rs"),
                    include_str!("predicate.rs"),
                    include_str!("solver.rs")
                )
                .as_bytes()
            )
        ),
        request_id: result.request_id.clone(),
        public_inputs: public_input_names(&entry_r1cs, &entry_sym),
        entry_relative: entrypoint
            .strip_prefix(&source_root)
            .unwrap_or(&entrypoint)
            .to_path_buf(),
        entry_main_template: main_template_name(&sources[&entrypoint]),
        sweep_remaining: synth::CANDIDATE_SWEEP_BUDGET,
        repair_remaining: search_v27::repair_iteration_limit(),
        repair_limit: search_v27::repair_iteration_limit(),
        structure: None,
        class_witness: None,
    };
    context
        .entry_key
        .push_str(&search_v27::search_identity_suffix());
    if boost.options.active() {
        context.entry_key.push_str(&format!(
            ":boost:{}",
            sha256_bytes(&serde_json::to_vec(&boost.options).map_err(|e| prep("io")(e.into()))?)
        ));
    }
    result.property = Some(
        match property {
            Property::Tcct => "tcct",
            Property::InputAssumption => "input_assumption",
        }
        .to_owned(),
    );
    // L-05 step 2 / L-07: the predicate targets are the instances the candidate breaks, or
    // every LessThan instance of the component when none is known to be broken.
    let (targets, basis) = match result.violated_condition.as_ref() {
        Some(condition) if !condition.broken.is_empty() => (
            condition
                .broken
                .iter()
                .map(|broken| broken.instance.clone())
                .collect::<Vec<_>>(),
            "broken_by_candidate",
        ),
        _ => (component_lessthan.clone(), "component_lessthan_instances"),
    };
    let mut sweep_carry = Duration::ZERO;
    let mut sweep_spent = Duration::ZERO;
    let mut sweep_unallocated = synth::CANDIDATE_SWEEP_BUDGET;
    for (index, class) in classes.iter().enumerate() {
        ledger.site = Some(class.representative.clone());
        search_v27::site(Some(&class.representative));
        context.class_witness = None;
        let base_reserved =
            synth::class_sweep_budget(synth::CANDIDATE_SWEEP_BUDGET, classes.len(), index);
        let carry_in = sweep_carry;
        if search_v27::enabled() {
            context.sweep_remaining = synth::class_sweep_assignment(
                synth::CANDIDATE_SWEEP_BUDGET,
                classes.len(),
                index,
                carry_in,
            );
            sweep_unallocated = sweep_unallocated.saturating_sub(base_reserved);
        } else if let Some(seconds) = boost.options.class_sweep_budget_seconds {
            context.sweep_remaining = Duration::from_secs(seconds);
        }
        let sweep_before = context.sweep_remaining;
        let mut class_result = evaluate_class(index, class, &mut context, ledger);
        let candidate_repair_remaining = context.repair_remaining;
        if targets.is_empty() {
            if result.violated_condition.is_some() {
                class_result.assumption_predicate_verdict = Some("not_applicable".to_owned());
                class_result.semantic_deviation_observed = Some(false);
            }
        } else {
            let witness = context.class_witness.take();
            predicate::judge(
                &mut context,
                &mut class_result,
                &targets,
                basis,
                witness.as_ref(),
                &raw.join(format!("site-{index:03}")),
                ledger,
            );
        }
        if boost.options.active() {
            boost.push(serde_json::json!({"kind":"class_budget", "site":class.representative,
                "assigned_seconds":sweep_before.as_secs_f64(),
                "remaining_seconds":context.sweep_remaining.as_secs_f64(),
                "mode":if boost.options.class_sweep_budget_seconds.is_some() {"per_class"} else {"shared"}}));
        }
        boost::class_diagnostic(boost, &class_result);
        if search_v27::enabled() {
            sweep_carry = context.sweep_remaining.min(sweep_before);
            let spent = sweep_before.saturating_sub(sweep_carry);
            sweep_spent += spent;
            search_v27::record(serde_json::json!({
                "kind":"class_budget", "class_index":index, "class_count":classes.len(),
                "policy":"equal_reserved_with_forward_carry_no_borrowing",
                "base_reserved_seconds":base_reserved.as_secs_f64(),
                "carry_in_seconds":carry_in.as_secs_f64(),
                "carry_out_seconds":sweep_carry.as_secs_f64(),
                "spent_seconds":spent.as_secs_f64(),
                "cumulative_spent_seconds":sweep_spent.as_secs_f64(),
                "unallocated_reserved_seconds":sweep_unallocated.as_secs_f64(),
                "request_total_seconds":synth::CANDIDATE_SWEEP_BUDGET.as_secs_f64(),
                "assigned_seconds":sweep_before.as_secs_f64(),
                "remaining_seconds":context.sweep_remaining.as_secs_f64(),
                "sweep_attempts_by_stage":search_v27::branch_counts(),
                "repair_iteration_limit":context.repair_limit, "repair_iterations_remaining":candidate_repair_remaining,
                "verdict":class_result.verdict, "reason":class_result.reason,
                "synthesis":class_result.synthesis,
            }));
        }
        result.classes.push(class_result);
    }
    ledger.site = None;
    search_v27::site(None);
    if boost.options.post_limit_probe_site.is_some() {
        // Diagnostic work runs only after every legacy class verdict has been computed.
        // It owns a separate ledger and cannot change result.classes.
        repair::run_post_limit_probes(&context);
    }
    if profile_v24::enabled() {
        profile_v24::measure("context_cleanup", || drop(context));
        profile_v24::measure("artifact_handle_release", || {
            drop((
                component_r1cs,
                component_sym,
                entry_r1cs,
                entry_sym,
                entry_o0_r1cs,
                entry_o0_sym,
            ));
        });
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------
// Candidate and component analysis

fn load_candidate(path: &Path, format: CandidateFormat) -> Result<BTreeMap<String, BigUint>> {
    let value: Value = serde_json::from_slice(&fs::read(path)?).context("parse candidate")?;
    let assignment = match format {
        CandidateFormat::Named => value,
        CandidateFormat::Zkfuzz => value
            .get("7_assignment")
            .cloned()
            .context("zkFuzz candidate has no 7_assignment")?,
    };
    let object = assignment
        .as_object()
        .context("candidate assignment must be an object")?;
    let mut candidate = BTreeMap::new();
    for (name, value) in object {
        let text = match value {
            Value::String(text) => text.clone(),
            Value::Number(number) => number.to_string(),
            _ => bail!("candidate value for {name} is not a decimal"),
        };
        ensure!(
            !text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit()),
            "candidate value for {name} is not a canonical decimal"
        );
        candidate.insert(
            name.clone(),
            text.parse::<BigUint>()
                .with_context(|| format!("parse candidate value for {name}"))?,
        );
    }
    Ok(candidate)
}

fn load_artifacts(compiled: &Compiled) -> Result<(R1cs, SymbolTable)> {
    let _profile_span = profile_v24::span("artifact_read_parse");
    let r1cs = R1cs::parse(&fs::read(&compiled.r1cs)?)?;
    let sym = SymbolTable::parse(&fs::read(&compiled.sym)?, &r1cs)?;
    Ok((r1cs, sym))
}

fn artifact_bytes_equal(label: &str, left: &Path, right: &Path) -> Result<bool> {
    profile_v24::measure(label, || Ok(fs::read(left)? == fs::read(right)?))
}

/// Names of the `main` signals stored in wires `[first, first + count)`.
fn main_signals(r1cs: &R1cs, sym: &SymbolTable, first: usize, count: usize) -> Result<Vec<String>> {
    let mut names = Vec::new();
    for wire in first..first + count {
        let name = sym.wire_to_names[wire]
            .iter()
            .find(|name| is_direct_main(name))
            .with_context(|| format!("wire {wire} has no direct main signal name"))?;
        names.push(name.clone());
    }
    ensure!(names.len() == count && first + count <= r1cs.shape.wires);
    Ok(names)
}

fn is_direct_main(name: &str) -> bool {
    name.strip_prefix("main.")
        .is_some_and(|rest| split_instance(rest).0.is_empty())
}

/// Returns signals where the candidate differs from the honest witness, the number of
/// candidate names without a symbol, and whether the candidate satisfies the O0 R1CS.
fn component_deviation(
    candidate: &BTreeMap<String, BigUint>,
    r1cs: &R1cs,
    sym: &SymbolTable,
    honest: Option<&Vec<BigUint>>,
) -> (BTreeSet<String>, usize, Option<bool>) {
    let mut deviated = BTreeSet::new();
    let mut unmatched = 0;
    for (name, value) in candidate {
        match sym.by_name.get(name) {
            Some(symbol) if symbol.wire >= 0 => {
                if let Some(honest) = honest {
                    if &honest[symbol.wire as usize] != value {
                        deviated.insert(name.clone());
                    }
                }
            }
            Some(_) => {}
            None => unmatched += 1,
        }
    }
    let mut vector = vec![BigUint::zero(); r1cs.shape.wires];
    vector[0] = BigUint::one();
    let mut complete = true;
    for (wire, names) in sym.wire_to_names.iter().enumerate().skip(1) {
        match names.iter().find_map(|name| candidate.get(name)) {
            Some(value) => vector[wire] = value.clone(),
            None => complete = false,
        }
    }
    let satisfies = if complete {
        check_constraints(r1cs, &vector)
            .ok()
            .map(|failed| failed.is_empty())
    } else {
        None
    };
    (deviated, unmatched, satisfies)
}

#[derive(Debug, PartialEq, Eq)]
struct RewritePlan {
    /// Per source file: (rhs_start, rhs_end, replacement).
    edits: BTreeMap<PathBuf, Vec<(usize, usize, String)>>,
    records: Vec<PlannedRecord>,
    /// Deviated hint-assigned signals relative to the component main (for example `d`).
    hint_suffixes: BTreeSet<String>,
    propagated: usize,
}

#[derive(Debug, PartialEq, Eq)]
struct PlannedRecord {
    template: String,
    file: PathBuf,
    line: usize,
    signal: String,
    clauses: usize,
}

#[allow(clippy::too_many_arguments)]
fn plan_rewrites(
    candidate: &BTreeMap<String, BigUint>,
    component_sym: &SymbolTable,
    deviated: &BTreeSet<String>,
    honest_aborted: bool,
    templates: &[TemplateDef],
    sources: &BTreeMap<PathBuf, String>,
    main_template: Option<&str>,
    structure: Option<&reuse_v25::RewriteStructure<'_>>,
) -> std::result::Result<RewritePlan, Failure> {
    // A cache owns immutable borrows of exactly these source/symbol objects. It cannot
    // outlive or alias a mutated table; a different table falls back to the legacy path.
    let structure = structure.filter(|cache| cache.matches(component_sym, templates, sources));
    let uncached_signals;
    let instance_signals = if let Some(cache) = structure {
        cache.instance_signals()
    } else {
        uncached_signals = reuse_v25::build_instance_signals(component_sym);
        &uncached_signals
    };
    // When the honest component computation aborts, every hint-assigned signal is a
    // potential deviation; otherwise only the signals where the candidate differs.
    let targets: BTreeSet<String> = if honest_aborted {
        candidate.keys().cloned().collect()
    } else {
        deviated.clone()
    };

    let mut clauses: BTreeMap<(PathBuf, usize, usize), (Vec<String>, PlannedRecord)> =
        BTreeMap::new();
    let mut hint_suffixes = BTreeSet::new();
    let mut propagated = 0;
    let mut resolved: BTreeMap<String, &TemplateDef> = BTreeMap::new();
    for name in &targets {
        let (instance, leaf) = split_instance(name);
        let template = resolve_instance(
            instance,
            instance_signals,
            templates,
            sources,
            main_template,
            &mut resolved,
        )?;
        let source = &sources[&template.file];
        let cached_hints;
        let parsed_hints;
        let (hints, reverse) = if let Some(cache) = structure {
            cached_hints = cache.hints(template).map_err(prep("hint_unsupported"))?;
            cached_hints.as_ref()
        } else {
            parsed_hints = hint_statements(source, template).map_err(prep("hint_unsupported"))?;
            &parsed_hints
        };
        let base = leaf_base(leaf);
        if reverse.contains(base) {
            return Err(Failure {
                status: Verdict::PreparationFailure.name(),
                reason: "reverse_hint_unsupported",
                detail: format!("`-->` assignment to a deviated signal in {}", template.name),
            });
        }
        let statements = hints
            .iter()
            .filter(|hint| hint.signal == base)
            .collect::<Vec<_>>();
        if statements.is_empty() {
            if !honest_aborted {
                propagated += 1;
            }
            continue;
        }
        let value = &candidate[name];
        let key = instance_key(candidate, instance, template)?;
        let leaf_indices = leaf_indices(leaf);
        for statement in statements {
            if statement.indices.len() != leaf_indices.len() {
                return Err(Failure {
                    status: Verdict::PreparationFailure.name(),
                    reason: "hint_index_shape",
                    detail: format!(
                        "`<--` target in {} line {} has a different index depth",
                        template.name, statement.line
                    ),
                });
            }
            let mut condition = key.clone();
            for (expression, index) in statement.indices.iter().zip(&leaf_indices) {
                condition.push(format!("(({expression}) == {index})"));
            }
            let condition = if condition.is_empty() {
                "1".to_owned()
            } else {
                condition.join(" && ")
            };
            let entry = clauses
                .entry((
                    template.file.clone(),
                    statement.rhs_start,
                    statement.rhs_end,
                ))
                .or_insert_with(|| {
                    (
                        Vec::new(),
                        PlannedRecord {
                            template: template.name.clone(),
                            file: template.file.clone(),
                            line: statement.line,
                            signal: base.to_owned(),
                            clauses: 0,
                        },
                    )
                });
            entry.0.push(format!("({condition}) ? {value}"));
            entry.1.clauses += 1;
        }
        hint_suffixes.insert(name.trim_start_matches("main.").to_owned());
    }
    if !targets.is_empty() && hint_suffixes.is_empty() {
        return Err(Failure {
            status: Verdict::Unknown.name(),
            reason: "deviation_not_hint_assigned",
            detail: "no `<--` statement carries a deviated signal".to_owned(),
        });
    }
    let mut edits: BTreeMap<PathBuf, Vec<(usize, usize, String)>> = BTreeMap::new();
    let mut records = Vec::new();
    for ((file, start, end), (alternatives, record)) in clauses {
        let span = &sources[&file][start..end];
        let original = span.trim().to_owned();
        let mut replacement = format!("({original})");
        for alternative in alternatives.iter().rev() {
            replacement = format!("({alternative} : {replacement})");
        }
        // Keep the line count, so generator errors name the original source lines.
        let dropped = span.matches('\n').count() - original.matches('\n').count();
        edits.entry(file).or_default().push((
            start,
            end,
            format!(" {replacement}{}", "\n".repeat(dropped)),
        ));
        records.push(record);
    }
    if search_v27::enabled() {
        search_v27::expand_identical_edits(&mut edits, templates, sources)
            .map_err(prep("identical_definition_rewrite_conflict"))?;
    }
    Ok(RewritePlan {
        edits,
        records,
        hint_suffixes,
        propagated,
    })
}

/// Matches an instance to the template whose declared signal names equal the instance's.
/// Resolves an instance's template, memoized. When several templates declare the same
/// signal names, the parent template's instantiation statement (`name = Template(...)`)
/// decides, with the parent resolved first.
fn resolve_instance<'a>(
    instance: &str,
    instance_signals: &BTreeMap<String, BTreeSet<String>>,
    templates: &'a [TemplateDef],
    sources: &BTreeMap<PathBuf, String>,
    main_template: Option<&str>,
    memo: &mut BTreeMap<String, &'a TemplateDef>,
) -> std::result::Result<&'a TemplateDef, Failure> {
    if let Some(template) = memo.get(instance) {
        return Ok(template);
    }
    let signals = instance_signals.get(instance).cloned().unwrap_or_default();
    let resolved = match resolve_template(instance, &signals, templates, main_template, sources) {
        Ok(template) => template,
        Err(failure) if failure.reason == "template_ambiguous" => {
            let parent = split_instance(instance).0;
            if parent.is_empty() {
                return Err(failure);
            }
            let parent_template = resolve_instance(
                parent,
                instance_signals,
                templates,
                sources,
                main_template,
                memo,
            )?;
            let segment = &instance[parent.len() + 1..];
            let segment = segment.split('[').next().unwrap_or(segment);
            let names = instantiated_templates(
                &sources[&parent_template.file]
                    [parent_template.body_start..parent_template.body_end],
                segment,
            );
            let named = templates
                .iter()
                .filter(|template| template.signals == signals && names.contains(&template.name))
                .collect::<Vec<_>>();
            let named = if search_v27::enabled() {
                search_v27::unique_definitions(&named, sources)
            } else {
                named
            };
            match named.as_slice() {
                [template] => *template,
                _ => return Err(failure),
            }
        }
        Err(failure) => return Err(failure),
    };
    memo.insert(instance.to_owned(), resolved);
    Ok(resolved)
}

/// Template names assigned to component `name` in a template body: `name = T(` or
/// `name[i] = T(`, including `component name = T(`.
fn instantiated_templates(body: &str, name: &str) -> BTreeSet<String> {
    let masked = source::mask(body);
    let pattern = format!(
        r"(?:^|[^\w$]){}\s*(?:\[[^\]]*\]\s*)*=\s*([A-Za-z_$][\w$]*)\s*\(",
        regex::escape(name)
    );
    regex::Regex::new(&pattern)
        .map(|regex| {
            regex
                .captures_iter(&masked)
                .filter_map(|captures| captures.get(1).map(|m| m.as_str().to_owned()))
                .collect()
        })
        .unwrap_or_default()
}

fn resolve_template<'a>(
    instance: &str,
    signals: &BTreeSet<String>,
    templates: &'a [TemplateDef],
    main_template: Option<&str>,
    sources: &BTreeMap<PathBuf, String>,
) -> std::result::Result<&'a TemplateDef, Failure> {
    let matches = templates
        .iter()
        .filter(|template| &template.signals == signals)
        .collect::<Vec<_>>();
    if matches.len() == 1 {
        return Ok(matches[0]);
    }
    // Tie-breaks use circom's own naming: `main` is the wrapper's template, and an
    // anonymous component is named `Template_line_column`.
    let segment = instance.rsplit('.').next().unwrap_or(instance);
    let segment = segment.split('[').next().unwrap_or(segment);
    let wanted = if instance == "main" {
        main_template.map(str::to_owned)
    } else {
        anonymous_template(segment)
    };
    if search_v27::enabled() {
        let named = wanted
            .as_ref()
            .map(|wanted| {
                matches
                    .iter()
                    .copied()
                    .filter(|template| &template.name == wanted)
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let narrowed = if named.is_empty() { &matches } else { &named };
        let unique = search_v27::unique_definitions(narrowed, sources);
        let outcome = match (unique.len(), narrowed.len()) {
            (0, _) => "unmatched",
            (1, 1) => "matched",
            (1, _) => "identical_definitions",
            _ => "ambiguous",
        };
        search_v27::resolution(
            instance,
            &matches,
            sources,
            wanted.as_deref(),
            named.len(),
            unique.len(),
            outcome,
        );
        if unique.len() == 1 {
            return Ok(unique[0]);
        }
    }
    if let Some(wanted) = wanted {
        let named = matches
            .iter()
            .filter(|template| template.name == wanted)
            .collect::<Vec<_>>();
        if named.len() == 1 {
            return Ok(named[0]);
        }
    }
    Err(Failure {
        status: Verdict::PreparationFailure.name(),
        reason: if matches.is_empty() {
            "template_unmatched"
        } else {
            "template_ambiguous"
        },
        detail: format!(
            "instance {instance}: {} templates declare its signal names",
            matches.len()
        ),
    })
}

fn anonymous_template(segment: &str) -> Option<String> {
    let parts = segment.rsplitn(3, '_').collect::<Vec<_>>();
    if parts.len() == 3
        && parts[0].bytes().all(|byte| byte.is_ascii_digit())
        && parts[1].bytes().all(|byte| byte.is_ascii_digit())
        && !parts[0].is_empty()
        && !parts[1].is_empty()
    {
        Some(parts[2].to_owned())
    } else {
        None
    }
}

fn main_template_name(wrapper_source: &str) -> Option<String> {
    let masked = source::mask(wrapper_source);
    let start = masked.find("component main")?;
    let rest = &masked[start..];
    let equals = rest.find('=')?;
    let after = rest[equals + 1..].trim_start();
    let name: String = after
        .chars()
        .take_while(|c| c.is_ascii_alphanumeric() || *c == '_' || *c == '$')
        .collect();
    (!name.is_empty()).then_some(name)
}

/// The condition `in[0] == v0 && ...` over every input leaf of the instance's template.
fn instance_key(
    candidate: &BTreeMap<String, BigUint>,
    instance: &str,
    template: &TemplateDef,
) -> std::result::Result<Vec<String>, Failure> {
    let mut key = Vec::new();
    for input in &template.inputs {
        let prefix = format!("{instance}.{input}");
        let leaves = candidate
            .range(prefix.clone()..)
            .take_while(|(name, _)| name.starts_with(&prefix))
            .filter(|(name, _)| {
                let rest = &name[prefix.len()..];
                rest.is_empty() || rest.starts_with('[')
            })
            .collect::<Vec<_>>();
        if leaves.is_empty() {
            return Err(Failure {
                status: Verdict::PreparationFailure.name(),
                reason: "candidate_missing_signals",
                detail: format!("candidate has no value for an input of {instance}"),
            });
        }
        for (name, value) in leaves {
            key.push(format!("({} == {value})", &name[instance.len() + 1..]));
        }
    }
    Ok(key)
}

// ---------------------------------------------------------------------------------------
// Call sites and bindings

fn enumerate_sites(component_sym: &SymbolTable, entry_sym: &SymbolTable) -> Vec<String> {
    let suffixes = component_sym
        .by_name
        .keys()
        .filter_map(|name| name.strip_prefix("main."))
        .collect::<BTreeSet<_>>();
    let Some(anchor) = suffixes.iter().next() else {
        return Vec::new();
    };
    let anchor = format!(".{anchor}");
    let mut sites = Vec::new();
    for name in entry_sym.by_name.keys() {
        let Some(prefix) = name.strip_suffix(&anchor) else {
            continue;
        };
        let lower = format!("{prefix}.");
        let upper = format!("{prefix}/");
        let members = entry_sym
            .by_name
            .range(lower.clone()..upper)
            .map(|(member, _)| &member[lower.len()..])
            .collect::<BTreeSet<_>>();
        if members == suffixes {
            sites.push(prefix.to_owned());
        }
    }
    sites
}

struct SiteClass {
    pattern: String,
    representative: String,
    members: usize,
}

/// Groups sites by index-abstracted path and by a structural signature (the input
/// binding shape), so sites that share a name pattern but bind differently stay apart.
fn group_sites(sites: &[String], signature: impl Fn(&str) -> String) -> Vec<SiteClass> {
    let mut classes: BTreeMap<(String, String), Vec<&String>> = BTreeMap::new();
    for site in sites {
        classes
            .entry((class_pattern(site), signature(site)))
            .or_default()
            .push(site);
    }
    classes
        .into_iter()
        .map(|((pattern, _), members)| {
            let representative = members
                .iter()
                .min_by_key(|site| index_vector(site))
                .map(|site| (*site).clone())
                .unwrap_or_default();
            SiteClass {
                pattern,
                representative,
                members: members.len(),
            }
        })
        .collect()
}

/// Union-find over `x - y = 0` constraints, with constants from `x = k` constraints.
struct EqualityIndex {
    parent: Vec<usize>,
    constants: BTreeMap<usize, BigUint>,
    inputs: BTreeMap<usize, usize>,
}

impl EqualityIndex {
    fn build(r1cs: &R1cs) -> Self {
        let wires = r1cs.shape.wires;
        let mut parent = (0..wires).collect::<Vec<_>>();
        let mut constants: Vec<(usize, BigUint)> = Vec::new();
        let prime = &r1cs.prime;
        for constraint in &r1cs.constraints {
            if !(constraint.a.is_empty() || constraint.b.is_empty()) {
                continue;
            }
            let terms = constraint
                .c
                .iter()
                .filter(|(_, coefficient)| !coefficient.is_zero())
                .collect::<Vec<_>>();
            let variables = terms
                .iter()
                .filter(|(wire, _)| **wire != 0)
                .collect::<Vec<_>>();
            let constant = terms
                .iter()
                .find(|(wire, _)| **wire == 0)
                .map(|(_, coefficient)| (*coefficient).clone())
                .unwrap_or_default();
            match variables.as_slice() {
                [(left, a), (right, b)] if constant.is_zero() && ((*a + *b) % prime).is_zero() => {
                    let (left, right) = (
                        find(&mut parent, **left as usize),
                        find(&mut parent, **right as usize),
                    );
                    if left != right {
                        parent[left.max(right)] = left.min(right);
                    }
                }
                [(wire, coefficient)] => {
                    // c·x + k = 0  =>  x = -k / c
                    let inverse = coefficient.modpow(&(prime - BigUint::from(2u32)), prime);
                    let value = ((prime - &constant % prime) % prime * inverse) % prime;
                    constants.push((**wire as usize, value));
                }
                _ => {}
            }
        }
        let mut index = Self {
            parent,
            constants: BTreeMap::new(),
            inputs: BTreeMap::new(),
        };
        for wire in 0..wires {
            find(&mut index.parent, wire);
        }
        for (wire, value) in constants {
            let root = index.root(wire);
            index.constants.entry(root).or_insert(value);
        }
        let first = 1 + r1cs.shape.public_outputs;
        for wire in first..first + r1cs.shape.public_inputs + r1cs.shape.private_inputs {
            let root = index.root(wire);
            index.inputs.entry(root).or_insert(wire);
        }
        index
    }

    fn root(&self, wire: usize) -> usize {
        let mut root = wire;
        while self.parent[root] != root {
            root = self.parent[root];
        }
        root
    }
}

/// Public input names (`x`, `a[3]`) from the R1CS layout: the wires after the outputs.
fn public_input_names(r1cs: &R1cs, sym: &SymbolTable) -> BTreeSet<String> {
    let first = 1 + r1cs.shape.public_outputs;
    (first..first + r1cs.shape.public_inputs)
        .filter_map(|wire| sym.wire_to_names.get(wire)?.first())
        .map(|name| name.strip_prefix("main.").unwrap_or(name).to_owned())
        .collect()
}

fn find(parent: &mut [usize], wire: usize) -> usize {
    let mut root = wire;
    while parent[root] != root {
        root = parent[root];
    }
    let mut current = wire;
    while parent[current] != root {
        let next = parent[current];
        parent[current] = root;
        current = next;
    }
    root
}

// ---------------------------------------------------------------------------------------
// Per-class evaluation

struct SiteBinding {
    inputs: Vec<InputBinding>,
    /// O0 wires of inputs computed inside the entrypoint, with the candidate values.
    intermediates: Vec<(usize, BigUint)>,
    substitutions: BTreeMap<String, BigUint>,
    outcome: Option<(Verdict, &'static str)>,
    evidence: Option<String>,
    /// Which R1CS supports a constant exclusion: `o0_and_o1`, or an `o0_only_*` reason.
    evidence_basis: Option<&'static str>,
}

impl SiteBinding {
    /// Structural signature used to split a name class into binding shapes.
    fn signature(&self) -> String {
        let kinds = self
            .inputs
            .iter()
            .map(|binding| format!("{}:{}", binding.component_input, binding.kind))
            .collect::<Vec<_>>()
            .join(",");
        match self.outcome {
            Some((_, reason)) => format!("{kinds};{reason}"),
            None => kinds,
        }
    }
}

/// Binds each component input of `site` to an entrypoint input, a constant, or an
/// intermediate signal, through the O0 equality classes. With `original` (the O1 equality
/// index and symbols), a constant exclusion is cross-checked against the original R1CS.
fn bind_site(
    site: &str,
    component_inputs: &[String],
    candidate: &BTreeMap<String, BigUint>,
    bindings: &EqualityIndex,
    entry_o0_sym: &SymbolTable,
    original: Option<(&EqualityIndex, &SymbolTable)>,
) -> SiteBinding {
    let mut binding = SiteBinding {
        inputs: Vec::new(),
        intermediates: Vec::new(),
        substitutions: BTreeMap::new(),
        outcome: None,
        evidence: None,
        evidence_basis: None,
    };
    let mut excluded: Option<&'static str> = None;
    let mut unresolved: Option<(Verdict, &'static str)> = None;
    for input in component_inputs {
        let suffix = input.trim_start_matches("main.");
        let entry_name = format!("{site}.{suffix}");
        let value = &candidate[input];
        let Some(wire) = entry_o0_sym
            .by_name
            .get(&entry_name)
            .and_then(|symbol| usize::try_from(symbol.wire).ok())
        else {
            binding.inputs.push(InputBinding {
                component_input: suffix.to_owned(),
                kind: "missing".to_owned(),
                entrypoint_input: None,
            });
            unresolved.get_or_insert((Verdict::PreparationFailure, "site_input_has_no_o0_wire"));
            continue;
        };
        let root = bindings.root(wire);
        if let Some(input_wire) = bindings.inputs.get(&root) {
            let name = entry_o0_sym.wire_to_names[*input_wire]
                .iter()
                .find(|name| is_direct_main(name))
                .cloned()
                .unwrap_or_default();
            let path = name.trim_start_matches("main.").to_owned();
            binding.inputs.push(InputBinding {
                component_input: suffix.to_owned(),
                kind: "entrypoint_input".to_owned(),
                entrypoint_input: Some(path.clone()),
            });
            if let Some(previous) = binding.substitutions.insert(path, value.clone()) {
                if &previous != value {
                    excluded.get_or_insert("conflicting_input_binding");
                    binding.evidence.get_or_insert(format!(
                        "two inputs of {site} are tied by O0 equalities to one entrypoint input with different candidate values"
                    ));
                }
            }
        } else if let Some(constant) = bindings.constants.get(&root) {
            let matches = constant == value;
            binding.inputs.push(InputBinding {
                component_input: suffix.to_owned(),
                kind: if matches {
                    "constant_equal"
                } else {
                    "constant_different"
                }
                .to_owned(),
                entrypoint_input: None,
            });
            if !matches && binding.evidence.is_none() {
                excluded.get_or_insert("constant_input_mismatch");
                let basis = constant_basis(&entry_name, constant, original);
                binding.evidence_basis = Some(basis);
                binding.evidence = Some(match basis {
                    "o0_and_o1" => format!(
                        "the O0 R1CS and the original O1 R1CS both fix {entry_name} by linear constraints to a constant different from the candidate"
                    ),
                    "o0_only_signal_eliminated_in_o1" => format!(
                        "O0 R1CS basis only: an O0 linear constraint fixes {entry_name} to a constant different from the candidate; the original O1 R1CS has no wire for it (the compiler substituted the constant), so the equality cannot be re-checked there"
                    ),
                    _ => format!(
                        "O0 R1CS basis only: an O0 linear constraint fixes {entry_name} to a constant different from the candidate; no matching constant equality was found in the original O1 R1CS ({basis})"
                    ),
                });
            } else if !matches {
                excluded.get_or_insert("constant_input_mismatch");
            }
        } else {
            binding.inputs.push(InputBinding {
                component_input: suffix.to_owned(),
                kind: "intermediate".to_owned(),
                entrypoint_input: None,
            });
            binding.intermediates.push((wire, value.clone()));
            unresolved.get_or_insert((Verdict::Unknown, "input_requires_inversion"));
        }
    }
    // An exclusion is a proof for this site and wins over an unresolved input elsewhere.
    binding.outcome = excluded
        .map(|reason| (Verdict::ExcludedInContext, reason))
        .or(unresolved);
    if binding
        .outcome
        .is_none_or(|(verdict, _)| verdict != Verdict::ExcludedInContext)
    {
        binding.evidence = None;
        binding.evidence_basis = None;
    }
    binding
}

/// Cross-checks an O0 constant binding against the original (O1) R1CS.
fn constant_basis(
    entry_name: &str,
    constant: &BigUint,
    original: Option<(&EqualityIndex, &SymbolTable)>,
) -> &'static str {
    let Some((index, sym)) = original else {
        return "o0_only_not_checked";
    };
    match sym.by_name.get(entry_name).map(|symbol| symbol.wire) {
        Some(wire) if wire >= 0 => {
            if index.constants.get(&index.root(wire as usize)) == Some(constant) {
                "o0_and_o1"
            } else {
                "o0_only_o1_wire_without_constant_equality"
            }
        }
        Some(_) => "o0_only_signal_eliminated_in_o1",
        None => "o0_only_name_missing_in_o1",
    }
}

struct EvalContext<'a> {
    boost: &'a boost::State,
    component_main_template: Option<String>,
    sites: &'a [String],
    component_inputs: &'a [String],
    /// Component main outputs; with the inputs they form the candidate's boundary.
    component_outputs: &'a [String],
    range_index: Option<bitrange::RangeIndex>,
    candidate: &'a BTreeMap<String, BigUint>,
    plan: &'a RewritePlan,
    base_input: &'a Value,
    bindings: &'a EqualityIndex,
    original_bindings: &'a EqualityIndex,
    entry_o0_sym: &'a SymbolTable,
    rewrite_structure: Option<reuse_v25::RewriteStructure<'a>>,
    entry_o0_r1cs: &'a R1cs,
    o0_constraint_index: Option<std::rc::Rc<Vec<Vec<usize>>>>,
    entry_r1cs: &'a R1cs,
    entry_sym: &'a SymbolTable,
    original: &'a Compiled,
    original_o0: &'a Compiled,
    hinted: &'a Compiled,
    /// Hinted entrypoint source, root, and libraries, for a lazy O0 compile.
    hint_tree: Option<(PathBuf, PathBuf, Vec<PathBuf>)>,
    hinted_o0: Option<std::result::Result<Compiled, String>>,
    constraint_index: Option<Vec<Vec<usize>>>,
    tools: &'a Tools,
    z3: Option<&'a Path>,
    raw: &'a Path,
    templates: &'a [TemplateDef],
    sources: &'a BTreeMap<PathBuf, String>,
    property: Property,
    source_root: &'a Path,
    libraries: &'a [PathBuf],
    /// Compile cache (`--cache`); repair compiles are kept under `edits/`.
    cache: Option<&'a Path>,
    /// Shared predicate verdicts (`--instance-store`), the entrypoint's key in it, this request.
    instance_store: Option<&'a Path>,
    entry_key: String,
    request_id: String,
    /// Public input names of the entrypoint (`x`, `a[3]`), from the R1CS input layout.
    public_inputs: BTreeSet<String>,
    /// The entrypoint relative to the source root, and its main template.
    entry_relative: PathBuf,
    entry_main_template: Option<String>,
    /// What is left of the candidate's exclusion-sweep budget.
    sweep_remaining: Duration,
    repair_remaining: usize,
    repair_limit: usize,
    /// Signal roles from the sources over the O0 symbols, built when a repair needs them.
    structure: Option<repair::Structure<'a>>,
    /// The witness the current class reached (input-assumption property), for step 2.
    class_witness: Option<predicate::ClassWitness>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Property {
    Tcct,
    InputAssumption,
}

fn evaluate_class(
    index: usize,
    class: &SiteClass,
    context: &mut EvalContext,
    ledger: &mut Ledger,
) -> ClassResult {
    let _profile_span = profile_v24::span("class_control");
    context.repair_remaining = context.repair_limit;
    let site = &class.representative;
    let mut result = ClassResult {
        pattern: class.pattern.clone(),
        representative: site.clone(),
        sites: class.members,
        verdict: Verdict::Unknown,
        reason: String::new(),
        inputs: Vec::new(),
        input_origin: None,
        synthesis: None,
        honest_generation: None,
        deviated_generation: None,
        rust_unsatisfied: None,
        snarkjs: None,
        public_inputs_equal: None,
        outputs_differing: None,
        deviation_sites: None,
        exceptions: Vec::new(),
        evidence: BTreeMap::new(),
        predicates: Vec::new(),
        assumption_predicate_verdict: None,
        semantic_deviation_observed: None,
    };
    let conclude = |mut result: ClassResult, verdict: Verdict, reason: &str| {
        result.verdict = verdict;
        result.reason = reason.to_owned();
        result
    };

    let started = Instant::now();
    let binding = bind_site(
        site,
        context.component_inputs,
        context.candidate,
        context.bindings,
        context.entry_o0_sym,
        Some((context.original_bindings, context.entry_sym)),
    );
    ledger.record(
        "site_discovery",
        "bind site inputs",
        started.elapsed().as_secs_f64(),
        "ok",
        false,
    );
    result.inputs = binding.inputs;
    if let Some(evidence) = binding.evidence {
        result.evidence.insert("excluded_by".to_owned(), evidence);
    }
    if let Some(basis) = binding.evidence_basis {
        result
            .evidence
            .insert("exclusion_basis".to_owned(), basis.to_owned());
    }
    // Intermediate inputs go through reverse synthesis (L-02) below; every other
    // unresolved or excluded binding ends here.
    let pending = binding.outcome == Some((Verdict::Unknown, "input_requires_inversion"));
    if let Some((verdict, reason)) = binding.outcome {
        if !pending {
            return conclude(result, verdict, reason);
        }
    }
    let substitutions = binding.substitutions;
    let intermediates = binding.intermediates;

    // Entrypoint input X: the base input with the bound leaves replaced.
    let folder = context.raw.join(format!("site-{index:03}"));
    if let Err(error) = fs::create_dir_all(&folder) {
        result.exceptions.push(format!("io: {error}"));
        return conclude(result, Verdict::Unknown, "io");
    }
    let mut input = context.base_input.clone();
    for (path, value) in &substitutions {
        if let Err(error) = set_input_leaf(&mut input, path, value) {
            result.exceptions.push(format!("{error:#}"));
            return conclude(result, Verdict::PreparationFailure, "base_input_shape");
        }
    }
    result.input_origin = Some(
        if substitutions.is_empty() {
            "base"
        } else {
            "direct"
        }
        .to_owned(),
    );
    let mut generator_override: Option<Compiled> = None;
    let mut override_o0: Option<Compiled> = None;
    let mut comparator: Option<Compiled> = None;
    // Intermediate inputs need synthesis; for the input-assumption property every site
    // runs it, so a reference abort is classified even when all inputs are bound directly.
    if pending || context.property == Property::InputAssumption {
        let pinned = substitutions
            .iter()
            .filter_map(|(path, value)| {
                let symbol = context.entry_o0_sym.by_name.get(&format!("main.{path}"))?;
                Some((usize::try_from(symbol.wire).ok()?, value.clone()))
            })
            .collect::<BTreeMap<_, _>>();
        let mut record = SynthesisRecord {
            targets: intermediates.len(),
            ..SynthesisRecord::default()
        };
        let outcome = synthesize_inputs(
            context,
            site,
            &pinned,
            &intermediates,
            &mut input,
            &folder,
            ledger,
            &mut record,
        );
        result.synthesis = Some(record);
        match outcome {
            Synthesis::Reached(origin) => {
                if !(intermediates.is_empty() && origin == "base_reached") {
                    result.input_origin = Some(origin.to_owned());
                }
            }
            Synthesis::ReachedInjected(reached) => {
                let repaired = result.synthesis.as_ref().is_some_and(|record| {
                    record.reached_with.as_deref() == Some("hint_injection_with_repair")
                });
                result.input_origin = Some(
                    if repaired {
                        "repaired_hint_injection"
                    } else {
                        "synthesized_b_hint_injection"
                    }
                    .to_owned(),
                );
                result.exceptions.push(format!(
                    "hint_injection: {} rewritten statements in {} instances outside the site",
                    reached.statements, reached.instances
                ));
                input = reached.input;
                generator_override = Some(reached.o1);
                override_o0 = Some(reached.o0);
                comparator = reached.comparator;
            }
            Synthesis::Excluded(evidence) => {
                result.evidence.extend(evidence);
                return conclude(result, Verdict::ExcludedInContext, "closed_cone_unsat");
            }
            Synthesis::Unknown(reason) => return conclude(result, Verdict::Unknown, reason),
        }
    }
    let input_path = folder.join("input.json");
    if write_json(&input_path, &input).is_err() {
        return conclude(result, Verdict::Unknown, "io");
    }
    if let Ok(hash) = sha256_file(&input_path) {
        result.evidence.insert("input_sha256".to_owned(), hash);
    }
    if context.property == Property::InputAssumption {
        let result = evaluate_reachability(
            result,
            context,
            &input_path,
            &folder,
            ledger,
            generator_override.as_ref(),
        );
        if result.verdict == Verdict::AssumptionInputReachable {
            context.class_witness = Some(predicate::ClassWitness {
                input: input_path,
                o0: override_o0,
                o1_witness: folder.join("honest.wtns"),
            });
        }
        return result;
    }
    let entry_r1cs = context.entry_r1cs;
    let prime = &entry_r1cs.prime;
    let tools = context.tools;
    // With injected hints outside the site, the comparison is the same injections without
    // the candidate's own site hints.
    if comparator.is_some() {
        result.exceptions.push(
            "comparator: the injected generator without the candidate's site hints".to_owned(),
        );
    }
    let honest = generate_witness(
        tools,
        comparator.as_ref().unwrap_or(context.original),
        &input_path,
        &folder.join("honest.wtns"),
        prime,
        ledger,
        "witness",
        "entrypoint honest witness",
    );
    let deviated = generate_witness(
        tools,
        generator_override.as_ref().unwrap_or(context.hinted),
        &input_path,
        &folder.join("deviated.wtns"),
        prime,
        ledger,
        "witness",
        "entrypoint deviated witness",
    );
    let mut honest = match honest {
        Ok(witness) => {
            result.honest_generation =
                Some(if witness.is_some() { "ok" } else { "aborted" }.to_owned());
            witness
        }
        Err(error) => {
            result.exceptions.push(format!("{error:#}"));
            return conclude(result, Verdict::Unknown, "honest_generation_error");
        }
    };
    let deviated = match deviated {
        Ok(Some(witness)) => {
            result.deviated_generation = Some("ok".to_owned());
            witness
        }
        Ok(None) => {
            result.deviated_generation = Some("aborted".to_owned());
            let abort = classify_abort(
                &folder.join("deviated.log"),
                context.templates,
                context.sources,
            );
            result
                .evidence
                .insert("deviated_abort_kind".to_owned(), abort.kind.clone());
            // Reuse the class's remaining repair slots. A generator already carrying
            // external repairs cannot be restarted from empty overrides.
            let repaired = if abort.kind == "constraint"
                && generator_override.is_none()
                && context.repair_remaining > 0
            {
                let pinned = substitutions
                    .iter()
                    .filter_map(|(name, _)| {
                        context
                            .entry_o0_sym
                            .by_name
                            .get(&format!("main.{name}"))
                            .and_then(|symbol| usize::try_from(symbol.wire).ok())
                    })
                    .collect();
                let start = repair::Start {
                    label: "deviated_abort",
                    stage: "repair",
                    input: input.clone(),
                    overrides: repair::Overrides::default(),
                    candidate_hints: true,
                    protected_site: Some(site.clone()),
                    inputs_free: true,
                    pinned,
                };
                let requirement = repair::Requirement {
                    targets: intermediates.clone(),
                    predicate: None,
                };
                let (reached, search) = repair::search(
                    context,
                    start,
                    &requirement,
                    &folder.join("deviated-abort-repair"),
                    ledger,
                );
                result
                    .synthesis
                    .get_or_insert_with(SynthesisRecord::default)
                    .repair = Some(search);
                reached
            } else {
                None
            };
            let Some(repaired) = repaired else {
                return try_refutation(
                    result,
                    context,
                    &input,
                    ledger,
                    "deviated_generation_aborted",
                );
            };
            input = repaired.input;
            if write_json(&input_path, &input).is_err() {
                return conclude(result, Verdict::Unknown, "io");
            }
            if let Ok(hash) = sha256_file(&input_path) {
                result.evidence.insert("input_sha256".to_owned(), hash);
            }
            override_o0 = Some(repaired.o0);
            generator_override = Some(repaired.o1);
            comparator = repaired.comparator;
            result.input_origin = Some("repaired_hint_injection".to_owned());
            honest = match generate_witness(
                tools,
                comparator.as_ref().unwrap_or(context.original),
                &input_path,
                &folder.join("honest.wtns"),
                prime,
                ledger,
                "witness",
                "repaired comparator witness",
            ) {
                Ok(witness) => witness,
                Err(error) => {
                    result.exceptions.push(format!("{error:#}"));
                    return conclude(result, Verdict::Unknown, "honest_generation_error");
                }
            };
            result.honest_generation =
                Some(if honest.is_some() { "ok" } else { "aborted" }.to_owned());
            match generate_witness(
                tools,
                generator_override.as_ref().expect("repaired generator"),
                &input_path,
                &folder.join("deviated.wtns"),
                prime,
                ledger,
                "witness",
                "repaired deviated witness",
            ) {
                Ok(Some(witness)) => {
                    result.deviated_generation = Some("ok".to_owned());
                    witness
                }
                Ok(None) => {
                    return try_refutation(
                        result,
                        context,
                        &input,
                        ledger,
                        "deviated_generation_aborted",
                    )
                }
                Err(error) => {
                    result.exceptions.push(format!("{error:#}"));
                    return conclude(result, Verdict::Unknown, "deviated_generation_error");
                }
            }
        }
        Err(error) => {
            result.exceptions.push(format!("{error:#}"));
            return conclude(result, Verdict::Unknown, "deviated_generation_error");
        }
    };

    // Two independent checks of the deviated witness against the original R1CS.
    let started = Instant::now();
    let rust = check_constraints(entry_r1cs, &deviated).map(|failed| failed.len());
    ledger.record(
        "check",
        "rust r1cs evaluation",
        started.elapsed().as_secs_f64(),
        if rust.is_ok() { "ok" } else { "failed" },
        false,
    );
    result.rust_unsatisfied = rust.as_ref().ok().copied();
    let snark = snarkjs_check(
        tools,
        &context.original.r1cs,
        &folder.join("deviated.wtns"),
        ledger,
    )
    .unwrap_or_else(|error| {
        result.exceptions.push(format!("{error:#}"));
        "error".to_owned()
    });
    result.snarkjs = Some(snark.clone());
    if let Ok(hash) = sha256_file(&folder.join("deviated.wtns")) {
        result
            .evidence
            .insert("deviated_wtns_sha256".to_owned(), hash);
    }
    match (result.rust_unsatisfied, snark.as_str()) {
        (Some(0), "correct") => {}
        (Some(count), "not_correct") if count > 0 => {
            return try_refutation(
                result,
                context,
                &input,
                ledger,
                "deviated_witness_unsatisfying",
            );
        }
        _ => return conclude(result, Verdict::Unknown, "checker_disagreement"),
    }

    let outputs = entry_r1cs.shape.public_outputs;
    let inputs = entry_r1cs.shape.public_inputs;
    if let Some(honest) = &honest {
        result.public_inputs_equal = Some(
            honest[1 + outputs..1 + outputs + inputs]
                == deviated[1 + outputs..1 + outputs + inputs],
        );
        result.outputs_differing = Some(
            (1..=outputs)
                .filter(|wire| honest[*wire] != deviated[*wire])
                .count(),
        );
    }
    if result.public_inputs_equal == Some(false) {
        return conclude(result, Verdict::Unknown, "public_inputs_differ");
    }

    // Does the witness carry the candidate at this site? The deviated hint signals must
    // hold the candidate's values on original wires, or on O0 wires when optimization
    // removed them. Other sites that deviate are counted against the honest witness.
    let mut injection = check_injection(
        site,
        context.sites,
        context.plan,
        context.candidate,
        context.component_inputs,
        context.entry_sym,
        &deviated,
    );
    if context.boost.options.injection_diagnostics {
        boost::diagnose(context, site, "O1", context.entry_sym, &deviated);
        if injection.as_ref().is_some_and(|found| !found.carried) {
            if let Err(error) = o0_injection(
                context,
                site,
                &input_path,
                &folder,
                ledger,
                override_o0.as_ref(),
            ) {
                context.boost.push(serde_json::json!({"kind":"injection_diagnostic", "space":"O0", "site":site, "error":format!("{error:#}")}));
            }
        }
    }
    if injection.is_none() {
        match o0_injection(
            context,
            site,
            &input_path,
            &folder,
            ledger,
            override_o0.as_ref(),
        ) {
            Ok(found) => injection = found,
            Err(error) => result.exceptions.push(format!("{error:#}")),
        }
    }
    let Some(injection) = injection else {
        return conclude(result, Verdict::Unknown, "injection_unobservable");
    };
    result.deviation_sites = injection
        .elsewhere
        .map(|elsewhere| elsewhere + usize::from(injection.carried));
    if let Some(elsewhere) = injection.elsewhere.filter(|count| *count > 0) {
        result
            .exceptions
            .push(format!("deviation_at_other_sites: {elsewhere}"));
    }
    if !injection.carried {
        return conclude(result, Verdict::Unknown, "injection_not_applied");
    }
    match (&honest, result.outputs_differing) {
        (None, _) => {
            search_v27::record(serde_json::json!({"kind":"preserved_verdict_branch",
                "branch":"comparator_absent_honest_aborted", "verdict":"entrypoint_violation"}));
            conclude(result, Verdict::EntrypointViolation, "honest_aborted")
        }
        (Some(_), Some(differing)) if differing > 0 => {
            conclude(result, Verdict::EntrypointViolation, "output_differs")
        }
        _ => conclude(
            result,
            Verdict::CompatibleNoTopViolationObserved,
            "outputs_equal",
        ),
    }
}

/// Input-assumption property: the honest witness on the constructed input carries the
/// candidate's site values (the candidate equals the honest component computation), so it
/// only has to exist and satisfy the original constraints under both checkers.
fn evaluate_reachability(
    mut result: ClassResult,
    context: &mut EvalContext,
    input_path: &Path,
    folder: &Path,
    ledger: &mut Ledger,
    generator: Option<&Compiled>,
) -> ClassResult {
    let _profile_span = profile_v24::span("reachability_control");
    let conclude = |mut result: ClassResult, verdict: Verdict, reason: &str| {
        result.verdict = verdict;
        result.reason = reason.to_owned();
        result
    };
    let entry_r1cs = context.entry_r1cs;
    let witness_path = folder.join("honest.wtns");
    // With hint injection the witness comes from the injected generator; the honest one
    // alone would not reach the site inputs.
    let honest = generate_witness(
        context.tools,
        generator.unwrap_or(context.original),
        input_path,
        &witness_path,
        &entry_r1cs.prime,
        ledger,
        "witness",
        "entrypoint witness",
    );
    let honest = match honest {
        Ok(Some(witness)) => {
            result.honest_generation = Some("ok".to_owned());
            witness
        }
        Ok(None) => {
            result.honest_generation = Some("aborted".to_owned());
            let abort = classify_abort(
                &witness_path.with_extension("log"),
                context.templates,
                context.sources,
            );
            result.exceptions.push(format!(
                "honest abort in {} line {} ({})",
                abort.template, abort.line, abort.kind
            ));
            return conclude(result, Verdict::Unknown, "honest_generation_aborted");
        }
        Err(error) => {
            result.exceptions.push(format!("{error:#}"));
            return conclude(result, Verdict::Unknown, "honest_generation_error");
        }
    };
    let started = Instant::now();
    let rust = check_constraints(entry_r1cs, &honest).map(|failed| failed.len());
    ledger.record(
        "check",
        "rust r1cs evaluation",
        started.elapsed().as_secs_f64(),
        if rust.is_ok() { "ok" } else { "failed" },
        false,
    );
    result.rust_unsatisfied = rust.as_ref().ok().copied();
    let snark = snarkjs_check(context.tools, &context.original.r1cs, &witness_path, ledger)
        .unwrap_or_else(|error| {
            result.exceptions.push(format!("{error:#}"));
            "error".to_owned()
        });
    result.snarkjs = Some(snark.clone());
    if let Ok(hash) = sha256_file(&witness_path) {
        result.evidence.insert("witness_sha256".to_owned(), hash);
    }
    if !(result.rust_unsatisfied == Some(0) && snark == "correct") {
        return conclude(result, Verdict::Unknown, "checker_disagreement");
    }
    // The site's signals that keep a wire must hold the candidate's values.
    let site = result.representative.clone();
    let mut compared = 0usize;
    for (name, value) in context.candidate {
        let Some(suffix) = name.strip_prefix("main.") else {
            continue;
        };
        if let Some(wire) = context
            .entry_sym
            .by_name
            .get(&format!("{site}.{suffix}"))
            .and_then(|symbol| usize::try_from(symbol.wire).ok())
        {
            compared += 1;
            if &honest[wire] != value {
                return conclude(result, Verdict::Unknown, "site_values_differ");
            }
        }
    }
    result
        .evidence
        .insert("site_signals_compared".to_owned(), compared.to_string());
    conclude(result, Verdict::AssumptionInputReachable, "input_reached")
}

struct Injection {
    /// Every visible deviated hint signal at the site holds the candidate's value.
    carried: bool,
    /// Other sites where the rewritten hints fire too: every visible site input equals the
    /// candidate's (the hint key). Changes that only propagate downstream do not count.
    elsewhere: Option<usize>,
}

/// None when the site has no wire for any deviated hint signal in `sym`.
fn check_injection(
    site: &str,
    sites: &[String],
    plan: &RewritePlan,
    candidate: &BTreeMap<String, BigUint>,
    component_inputs: &[String],
    sym: &SymbolTable,
    deviated: &[BigUint],
) -> Option<Injection> {
    let _profile_span = profile_v24::span("injection_validation");
    let wire = |name: &str| {
        sym.by_name
            .get(name)
            .and_then(|symbol| usize::try_from(symbol.wire).ok())
    };
    let mut visible = false;
    let mut carried = true;
    for suffix in &plan.hint_suffixes {
        if let Some(position) = wire(&format!("{site}.{suffix}")) {
            visible = true;
            carried &= candidate.get(&format!("main.{suffix}")) == Some(&deviated[position]);
        }
    }
    if !visible {
        return None;
    }
    let elsewhere = sites
        .iter()
        .filter(|other| other.as_str() != site)
        .filter(|other| {
            let visible_inputs = component_inputs
                .iter()
                .filter_map(|input| {
                    let suffix = input.trim_start_matches("main.");
                    wire(&format!("{other}.{suffix}")).map(|position| (input, position))
                })
                .collect::<Vec<_>>();
            !visible_inputs.is_empty()
                && visible_inputs
                    .iter()
                    .all(|(input, position)| candidate.get(*input) == Some(&deviated[*position]))
        })
        .count();
    Some(Injection {
        carried,
        elsewhere: Some(elsewhere),
    })
}

/// [`check_injection`] with O0 generators, where every signal is a wire.
fn o0_injection(
    context: &mut EvalContext,
    site: &str,
    input: &Path,
    folder: &Path,
    ledger: &mut Ledger,
    injected: Option<&Compiled>,
) -> Result<Option<Injection>> {
    let _profile_span = profile_v24::span("o0_injection");
    let hinted_o0 = match injected {
        Some(compiled) => compiled,
        None => {
            ensure_hinted_o0(context, ledger)?;
            let Some(Ok(hinted_o0)) = context.hinted_o0.as_ref() else {
                unreachable!("ensure_hinted_o0 succeeded");
            };
            hinted_o0
        }
    };
    let prime = &context.entry_r1cs.prime;
    let deviated = generate_witness(
        context.tools,
        hinted_o0,
        input,
        &folder.join("deviated-o0.wtns"),
        prime,
        ledger,
        "witness",
        "entrypoint deviated O0 witness",
    )?
    .context("deviated O0 generation aborted")?;
    if context.boost.options.injection_diagnostics {
        boost::diagnose(context, site, "O0", context.entry_o0_sym, &deviated);
    }
    Ok(check_injection(
        site,
        context.sites,
        context.plan,
        context.candidate,
        context.component_inputs,
        context.entry_o0_sym,
        &deviated,
    ))
}

/// Compiles the hinted entrypoint at O0 once per request; it must keep the O0 R1CS.
fn ensure_hinted_o0(context: &mut EvalContext, ledger: &mut Ledger) -> Result<()> {
    let _profile_span = profile_v24::span("hinted_o0_setup");
    if context.hinted_o0.is_none() {
        let (entry, root, libraries) =
            context.hint_tree.clone().context("no hinted source tree")?;
        let original_o0 = context.original_o0;
        let key = match context.cache {
            Some(cache) => edits_key(
                context.tools,
                &context.entry_relative,
                context.source_root,
                context.libraries,
                context.sources,
                &context.plan.edits,
                true,
            )
            .ok()
            .map(|key| (cache, key)),
            None => None,
        };
        let compiled = compile_edited(
            context.tools,
            key,
            &entry,
            &context.raw.join("entry-hinted-o0"),
            &root,
            &libraries,
            true,
            ledger,
            "compile hinted entrypoint --O0",
        )
        .map_err(|error| format!("{error:#}"))
        .and_then(|compiled| {
            if fs::read(&compiled.r1cs).ok() == fs::read(&original_o0.r1cs).ok() {
                Ok(compiled)
            } else {
                Err("hinted O0 R1CS differs from the original O0 R1CS".to_owned())
            }
        });
        context.hinted_o0 = Some(compiled);
    }
    match context.hinted_o0.as_ref() {
        Some(Ok(_)) => Ok(()),
        Some(Err(error)) => bail!("hinted O0 compile failed: {error}"),
        None => unreachable!(),
    }
}

/// Outcome of reverse input synthesis for one site.
enum Synthesis {
    /// `input` now reproduces every target; the value is the input origin.
    Reached(&'static str),
    /// Reached only with solver values injected into hint signals (L-04), possibly after
    /// localizing and repairing aborts (L-05): the injected generators and input.
    ReachedInjected(Box<repair::Reached>),
    /// A closed cone is unsatisfiable (z3 unsat): evidence entries for the class.
    Excluded(BTreeMap<String, String>),
    Unknown(&'static str),
}

/// L-02/L-03 reverse input synthesis. On `Reached`, `input` holds entrypoint inputs whose
/// honest O0 computation reproduces every target value (the hinted generator stands in
/// when the honest computation aborts). Proposals from stage (a) or (b) are never trusted
/// without that re-computation, and the caller still verifies the full witness. When the
/// reference computation aborts, the failing check is classified: a constraint sends the
/// site to the closed-cone stage, an `assert` alone ends as `abort_on_unconstrained_check`.
#[allow(clippy::too_many_arguments)]
fn synthesize_inputs(
    context: &mut EvalContext,
    site: &str,
    pinned: &BTreeMap<usize, BigUint>,
    targets: &[(usize, BigUint)],
    input: &mut Value,
    folder: &Path,
    ledger: &mut Ledger,
    record: &mut SynthesisRecord,
) -> Synthesis {
    let _profile_span = profile_v24::span("synthesis_control");
    let r1cs = context.entry_o0_r1cs;
    if context.o0_constraint_index.is_none() {
        let index = ledger.timed("synthesis_a", "index O0 constraints", || {
            refute::constraint_index(r1cs)
        });
        context.o0_constraint_index = Some(std::rc::Rc::new(index));
    }
    // When the honest computation aborts on a proposal, the hinted generator (identical
    // except at sites whose inputs equal the candidate's) checks reachability instead.
    let fallback_ready = context.hint_tree.is_some() && ensure_hinted_o0(context, ledger).is_ok();
    let deviated_generator = match context.hinted_o0.as_ref() {
        Some(Ok(compiled)) if fallback_ready => Some(compiled),
        _ => None,
    };
    let index_shared = context.o0_constraint_index.clone().unwrap_or_default();
    let index: &[Vec<usize>] = &index_shared;
    let (tools, generator, sym, z3, templates, sources) = (
        context.tools,
        context.original_o0,
        context.entry_o0_sym,
        context.z3,
        context.templates,
        context.sources,
    );
    let prime = &r1cs.prime;
    // Wires inside the site instance are computed from the site inputs; never adjust them.
    let inside = sym
        .by_name
        .range(format!("{site}.")..format!("{site}/"))
        .filter_map(|(_, symbol)| usize::try_from(symbol.wire).ok())
        .collect::<BTreeSet<_>>();
    let internal = |wire: usize| inside.contains(&wire);
    let input_name = |wire: usize| {
        sym.wire_to_names[wire]
            .iter()
            .find(|name| is_direct_main(name))
            .map(|name| name.trim_start_matches("main.").to_owned())
    };
    let directory = folder.join("synthesis");
    if fs::create_dir_all(&directory).is_err() {
        return Synthesis::Unknown("io");
    }
    let mut counter = 0usize;
    let mut last_log = PathBuf::new();
    let mut evaluate = |candidate: &Value, stage: &str, ledger: &mut Ledger, log: &mut PathBuf| {
        counter += 1;
        let path = directory.join(format!("input-{counter:03}.json"));
        write_json(&path, candidate).ok()?;
        *log = path.with_extension("log");
        let honest = generate_witness(
            tools,
            generator,
            &path,
            &path.with_extension("wtns"),
            prime,
            ledger,
            stage,
            "synthesis honest O0 witness",
        )
        .unwrap_or_else(|error| {
            ledger.record(
                stage,
                &format!("honest O0 tool error: {error:#}"),
                0.0,
                "tool_error",
                false,
            );
            None
        });
        if let Some(witness) = honest {
            return Some((witness, false));
        }
        generate_witness(
            tools,
            deviated_generator?,
            &path,
            &path.with_extension("deviated.wtns"),
            prime,
            ledger,
            stage,
            "synthesis hinted O0 witness (honest aborted)",
        )
        .unwrap_or_else(|error| {
            ledger.record(
                stage,
                &format!("hinted O0 tool error: {error:#}"),
                0.0,
                "tool_error",
                false,
            );
            None
        })
        .map(|witness| (witness, true))
    };
    let reached =
        |witness: &[BigUint]| targets.iter().all(|(wire, value)| &witness[*wire] == value);

    let reference_input = input.clone();
    let reference = evaluate(input, "synthesis_a", ledger, &mut last_log);
    let mut fallback: &'static str = "synthesis_model_not_reproduced";
    let mut run_a = true;
    let mut reference_witness = None;
    match reference {
        Some((witness, deviated)) => {
            if reached(&witness) {
                record.reached_with = Some(reached_with(deviated));
                return Synthesis::Reached("base_reached");
            }
            reference_witness = Some((witness, deviated));
        }
        None => {
            let abort = classify_abort(&last_log, templates, sources);
            record.reference_abort = Some(abort.clone());
            match abort.kind.as_str() {
                "assert" => return Synthesis::Unknown("abort_on_unconstrained_check"),
                "constraint" => {
                    fallback = "abort_on_constraint_unresolved";
                    run_a = false;
                }
                _ => return Synthesis::Unknown("synthesis_reference_aborted"),
            }
        }
    }

    // (a) Concrete back-propagation along shortest constraint paths.
    if let Some((reference, reference_deviated)) = reference_witness.clone().filter(|_| run_a) {
        let mut current = reference;
        let mut current_deviated = reference_deviated;
        let mut fixed = pinned.keys().copied().collect::<BTreeSet<_>>();
        let mut changed = BTreeSet::new();
        'rounds: for round in 0..synth::MAX_ROUNDS {
            record.a_rounds = round + 1;
            let unmet = targets
                .iter()
                .filter(|(wire, value)| &current[*wire] != value)
                .cloned()
                .collect::<Vec<_>>();
            if unmet.is_empty() {
                break;
            }
            for (wire, value) in unmet {
                if current[wire] == value {
                    continue;
                }
                let started = Instant::now();
                let paths = {
                    let blocked = |other: usize| fixed.contains(&other) || inside.contains(&other);
                    let graph = synth::Graph {
                        r1cs,
                        index,
                        blocked: &blocked,
                        internal: &internal,
                    };
                    synth::find_paths(&graph, wire, synth::MAX_PATHS)
                };
                ledger.record(
                    "synthesis_a",
                    "find constraint paths",
                    started.elapsed().as_secs_f64(),
                    if paths.is_empty() { "none" } else { "ok" },
                    false,
                );
                record.a_paths_found += paths.len();
                let mut solved = false;
                for path in &paths {
                    if record.a_tries >= synth::MAX_TRIES {
                        break 'rounds;
                    }
                    let Some((input_wire, input_value)) =
                        synth::solve_path(r1cs, &current, wire, &value, path)
                    else {
                        continue;
                    };
                    let Some(name) = input_name(input_wire) else {
                        continue;
                    };
                    let mut trial = input.clone();
                    if set_input_leaf(&mut trial, &name, &input_value).is_err() {
                        continue;
                    }
                    record.a_tries += 1;
                    if let Some((witness, deviated)) =
                        evaluate(&trial, "synthesis_a", ledger, &mut last_log)
                    {
                        if witness[wire] == value {
                            *input = trial;
                            current = witness;
                            current_deviated = deviated;
                            fixed.insert(input_wire);
                            changed.insert(name);
                            solved = true;
                            break;
                        }
                    }
                }
                if !solved {
                    break 'rounds;
                }
            }
        }
        if reached(&current) {
            record.changed_inputs = changed.into_iter().collect();
            record.reached_with = Some(reached_with(current_deviated));
            return Synthesis::Reached("synthesized_a");
        }
    }

    // (b) Closed cone around the targets and the directly bound inputs: only values the
    // candidate determines are fixed, so unsat is a proof for every entrypoint input.
    *input = reference_input.clone();
    let Some(z3) = z3 else {
        record.b_outcome = Some("solver_unavailable".to_owned());
        return Synthesis::Unknown("synthesis_solver_unavailable");
    };
    let mut fixed_values = pinned.clone();
    fixed_values.extend(targets.iter().cloned());
    let starts = fixed_values.keys().copied().collect::<Vec<_>>();
    // For a TCCT candidate the excluded object is its boundary assignment, so its inputs and
    // outputs at the site may all be fixed; this lets downstream constraints in.
    if context.property == Property::Tcct {
        for name in context
            .component_inputs
            .iter()
            .chain(context.component_outputs)
        {
            let suffix = name.trim_start_matches("main.");
            if let (Some(wire), Some(value)) = (
                sym.by_name
                    .get(&format!("{site}.{suffix}"))
                    .and_then(|symbol| usize::try_from(symbol.wire).ok()),
                context.candidate.get(name),
            ) {
                fixed_values.insert(wire, value.clone());
            }
        }
    }
    let starts = {
        let mut all = starts;
        all.extend(fixed_values.keys().copied());
        all.sort_unstable();
        all.dedup();
        all
    };
    let blocked = |other: usize| pinned.contains_key(&other) || inside.contains(&other);
    let graph = synth::Graph {
        r1cs,
        index,
        blocked: &blocked,
        internal: &internal,
    };
    let fixed_names = |cone: &synth::Cone| {
        let mut names = cone
            .constraints
            .iter()
            .flat_map(|position| synth::constraint_wires(&r1cs.constraints[*position]))
            .filter(|wire| fixed_values.contains_key(wire))
            .filter_map(|wire| sym.wire_to_names[wire].first().cloned())
            .collect::<Vec<_>>();
        names.sort();
        names.dedup();
        names
    };
    let exclusion = |cone: &synth::Cone, propagation: bool, how: &str| {
        BTreeMap::from([
            (
                "excluded_by".to_owned(),
                format!(
                    "z3 returned unsat for {} O0 constraints over {} unknown wires ({how}) with only candidate-determined values fixed: the site inputs and the entrypoint inputs bound directly to them",
                    cone.constraints.len(),
                    cone.unknowns.len()
                ),
            ),
            ("exclusion_basis".to_owned(), "o0_closed_cone".to_owned()),
            (
                "exclusion_method".to_owned(),
                if propagation { "z3+propagation" } else { "z3" }.to_owned(),
            ),
            (
                "exclusion_constraints".to_owned(),
                format!("{:?}", cone.constraints),
            ),
            (
                "exclusion_fixed_wires".to_owned(),
                fixed_names(cone).join(", "),
            ),
        ])
    };

    // Bit-decomposition range reasoning first: cheap, sound, and it names the violated
    // decomposition. With the reference input fixed it only locates an abort.
    let started = Instant::now();
    if context.range_index.is_none() {
        let bindings = context.bindings;
        context.range_index = Some(bitrange::build(r1cs, &|wire| bindings.root(wire)));
    }
    let ranges = context.range_index.as_ref().expect("range index");
    let root = |wire: usize| context.bindings.root(wire);
    let instance_of = |wire: usize| {
        sym.wire_to_names[wire]
            .first()
            .map(|name| split_instance(name).0.to_owned())
            .unwrap_or_default()
    };
    if record.reference_abort.is_some() {
        let mut reference_fixed = BTreeMap::new();
        let first = 1 + r1cs.shape.public_outputs;
        for wire in first..first + r1cs.shape.public_inputs + r1cs.shape.private_inputs {
            if let Some(value) =
                input_name(wire).and_then(|name| input_leaf(&reference_input, &name))
            {
                reference_fixed.insert(wire, value);
            }
        }
        if let Some(found) =
            bitrange::propagate(r1cs, index, ranges, &root, &reference_fixed, 2_000_000)
        {
            record.abort_instance = Some(format!(
                "constraint {} ({}), instance {}{}",
                found.constraint,
                found.detail,
                instance_of(found.wire),
                found
                    .decomposition
                    .as_ref()
                    .map(|d| format!(
                        ", {}-bit decomposition at constraint {}",
                        d.bits, d.constraint
                    ))
                    .unwrap_or_default()
            ));
        }
    }
    let range_proof = bitrange::propagate(r1cs, index, ranges, &root, &fixed_values, 2_000_000);
    ledger.record(
        "synthesis_b",
        "bit-decomposition range propagation",
        started.elapsed().as_secs_f64(),
        if range_proof.is_some() {
            "refuted"
        } else {
            "inconclusive"
        },
        false,
    );
    if let Some(found) = range_proof {
        record.b_outcome = Some("range_contradiction".to_owned());
        let mut fixed_names = fixed_values
            .keys()
            .filter_map(|wire| sym.wire_to_names[*wire].first().cloned())
            .collect::<Vec<_>>();
        fixed_names.sort();
        return Synthesis::Excluded(BTreeMap::from([
            (
                "excluded_by".to_owned(),
                format!(
                    "no witness: with only candidate-determined values fixed, forced values and bit-decomposition ranges contradict at O0 constraint {} ({}){}",
                    found.constraint,
                    found.detail,
                    found
                        .decomposition
                        .as_ref()
                        .map(|d| format!("; {}-bit decomposition at constraint {} in {}", d.bits, d.constraint, instance_of(d.target)))
                        .unwrap_or_default()
                ),
            ),
            ("exclusion_basis".to_owned(), "o0_closed_cone".to_owned()),
            (
                "exclusion_method".to_owned(),
                "bit_decomposition_interval".to_owned(),
            ),
            (
                "exclusion_constraints".to_owned(),
                format!("[{}]", found.constraint),
            ),
            ("exclusion_fixed_wires".to_owned(), fixed_names.join(", ")),
        ]));
    }

    if search_v27::enabled() {
        let started = Instant::now();
        let budget = context.sweep_remaining / 4;
        let sweep = synth::candidate_contradiction_sweep(
            &graph,
            &fixed_values,
            &starts,
            z3,
            &directory,
            budget,
        );
        context.sweep_remaining = context.sweep_remaining.saturating_sub(started.elapsed());
        ledger.record(
            "synthesis_b",
            "candidate-only small contradiction search",
            started.elapsed().as_secs_f64(),
            "done",
            false,
        );
        match sweep {
            Ok(sweep) => {
                if let Some((cone, propagation)) = sweep.proof {
                    record.b_outcome = Some("candidate_small_cone_unsat".to_owned());
                    record.sweep_branches = Some(sweep.branches_tried);
                    record.sweep_end = Some("proof_found".to_owned());
                    return Synthesis::Excluded(exclusion(
                        &cone,
                        propagation,
                        "candidate small cone",
                    ));
                }
            }
            Err(error) => search_v27::record(serde_json::json!({
                "kind":"candidate_contradiction_error", "detail":format!("{error:#}")
            })),
        }
    }
    let joint = synth::largest_cone(&graph, &fixed_values, &starts, None);
    if search_v27::enabled() && joint.is_none() {
        search_v27::record(serde_json::json!({"kind":"joint_cone_limit",
            "size_limit_exceeded":true, "sweep_budget_zero":context.sweep_remaining.is_zero()}));
    }
    let mut small = if joint.is_none() {
        let small_started = Instant::now();
        let proposal = synth::small_proposal(
            &graph,
            &fixed_values,
            &starts,
            z3,
            &directory,
            context.sweep_remaining,
        );
        context.sweep_remaining = context
            .sweep_remaining
            .saturating_sub(small_started.elapsed());
        ledger.record(
            "synthesis_b",
            "small closed cone proposal",
            small_started.elapsed().as_secs_f64(),
            if context.sweep_remaining.is_zero() {
                "time_exhausted"
            } else {
                "finished"
            },
            false,
        );
        match proposal {
            Ok(proposal) => proposal,
            Err(error) => {
                record.note = Some(format!("small cone tool error: {error:#}"));
                None
            }
        }
    } else {
        None
    };
    let small_branch = small.is_some();
    let joint = joint.or_else(|| small.as_ref().and_then(|result| result.cone.clone()));
    let started = Instant::now();
    let mut label = "cone_too_large";
    if let Some(cone) = joint {
        record.b_cone_unknowns = Some(cone.unknowns.len());
        record.b_cone_constraints = Some(cone.constraints.len());
        let result = if let Some(proposal) = small.take() {
            Ok(proposal)
        } else {
            synth::solve_cone(
                &graph,
                &fixed_values,
                cone,
                true,
                synth::SOLVER_TIMEOUT,
                z3,
                &directory.join("cone"),
            )
        };
        ledger.record(
            "synthesis_b",
            "z3 joint closed cone",
            started.elapsed().as_secs_f64(),
            "done",
            false,
        );
        match result {
            Err(error) => {
                record.note = Some(format!("solver error: {error:#}"));
                label = "solver_error";
            }
            Ok(result) => match result.outcome {
                synth::ConeOutcome::Unsat { propagation } => {
                    record.b_outcome = Some(
                        if small_branch {
                            "small_cone_unsat"
                        } else {
                            "unsat"
                        }
                        .to_owned(),
                    );
                    let cone = result.cone.expect("solved cone");
                    return Synthesis::Excluded(exclusion(
                        &cone,
                        propagation,
                        if small_branch {
                            "small branch cone"
                        } else {
                            "joint cone"
                        },
                    ));
                }
                synth::ConeOutcome::Model(values) => {
                    label = "model_not_reproduced";
                    if context.boost.options.constraint_witness {
                        if let Some((start, _)) = &reference_witness {
                            let mut query = fixed_values.clone();
                            query.extend(values.clone());
                            boost::capture(
                                context,
                                site,
                                &boost::Snapshot {
                                    start: start.clone(),
                                    query,
                                    scope: pinned.clone(),
                                    origin: "closed_cone".into(),
                                },
                                ledger,
                            );
                        } else {
                            context.boost.push(
                                serde_json::json!({"method":"constraint_witness", "site":site,
                                "status":"unknown", "reason":"starting_witness_missing"}),
                            );
                        }
                    }
                    let mut trial = reference_input.clone();
                    let mut changed = BTreeSet::new();
                    let mut applicable = true;
                    for (wire, value) in values
                        .iter()
                        .filter(|(wire, _)| graph.is_free_input(**wire))
                    {
                        let (wire, value) = (*wire, value.clone());
                        let Some(name) = input_name(wire) else {
                            applicable = false;
                            break;
                        };
                        if input_leaf(&trial, &name).as_ref() == Some(&value) {
                            continue;
                        }
                        if set_input_leaf(&mut trial, &name, &value).is_err() {
                            applicable = false;
                            break;
                        }
                        changed.insert(name);
                    }
                    if applicable {
                        let evaluated = evaluate(&trial, "synthesis_b", ledger, &mut last_log);
                        if let Some((witness, deviated)) = &evaluated {
                            if reached(witness) {
                                *input = trial;
                                record.b_outcome = Some("sat".to_owned());
                                record.changed_inputs = changed.into_iter().collect();
                                record.reached_with = Some(reached_with(*deviated));
                                return Synthesis::Reached("synthesized_b");
                            }
                        } else {
                            record.model_abort =
                                Some(classify_abort(&last_log, templates, sources));
                        }
                        // The generator recomputed some hint-assigned wires differently from
                        // the model (or aborted): inject the model's values into those hints.
                        // Differences are taken against the proposal's own witness, or the
                        // reference witness when the proposal aborted.
                        let comparison = evaluated.map(|(witness, _)| witness).or_else(|| {
                            reference_witness
                                .as_ref()
                                .map(|(witness, _)| witness.clone())
                        });
                        {
                            record.model_comparison_missing = comparison.is_none();
                            let overrides = comparison
                                .as_ref()
                                .map(|comparison| {
                                    model_overrides(context, site, &values, comparison)
                                })
                                .unwrap_or_default();
                            // The compile and witness steps inside are recorded on their
                            // own; this step keeps only the remainder so nothing counts twice.
                            let recorded = ledger.steps.len();
                            let started = Instant::now();
                            let start = repair::Start {
                                label: "model",
                                stage: "synthesis_b",
                                input: trial.clone(),
                                overrides,
                                candidate_hints: context.property == Property::Tcct,
                                protected_site: Some(site.to_owned()),
                                inputs_free: true,
                                pinned: pinned.keys().copied().collect(),
                            };
                            let requirement = repair::Requirement {
                                targets: targets.to_vec(),
                                predicate: None,
                            };
                            let (reached, search) = repair::search(
                                context,
                                start,
                                &requirement,
                                &directory.join("injection"),
                                ledger,
                            );
                            ledger.record_remainder(
                                recorded,
                                "synthesis_b",
                                "hint injection",
                                started.elapsed().as_secs_f64(),
                                if reached.is_some() {
                                    "reached"
                                } else {
                                    "not_reached"
                                },
                                false,
                            );
                            let repaired = !search.localizations.is_empty();
                            if reached.is_none() {
                                record.note = Some(format!(
                                    "hint injection: {}{}",
                                    search.outcome,
                                    search
                                        .note
                                        .as_ref()
                                        .map(|note| format!(" ({note})"))
                                        .unwrap_or_default()
                                ));
                            }
                            changed.extend(search.changed_inputs.iter().cloned());
                            record.injection = Some(search);
                            if let Some(reached) = reached {
                                record.b_outcome = Some("sat_with_hint_injection".to_owned());
                                record.changed_inputs = changed.into_iter().collect();
                                record.reached_with = Some(
                                    if repaired {
                                        "hint_injection_with_repair"
                                    } else {
                                        "hint_injection"
                                    }
                                    .to_owned(),
                                );
                                return Synthesis::ReachedInjected(Box::new(reached));
                            }
                        }
                    }
                }
                synth::ConeOutcome::Sat => label = "sat_without_model",
                synth::ConeOutcome::PropagationOnly => label = "propagation_only",
                synth::ConeOutcome::Timeout => label = "timeout",
            },
        }
    }
    record.b_outcome = Some(label.to_owned());
    if search_v27::enabled() && label == "model_not_reproduced" {
        search_v27::record(serde_json::json!({"kind":"model_replay_failure",
            "outcome":label, "abort":record.model_abort,
            "comparison_missing":record.model_comparison_missing}));
    }

    // Exclusion sweep: one small closed cone per (start wire, constraint) branch, within the
    // candidate's remaining sweep budget.
    let started = Instant::now();
    let remaining = context.sweep_remaining;
    let sweep = synth::exclusion_sweep(&graph, &fixed_values, &starts, z3, &directory, remaining);
    context.sweep_remaining = remaining.saturating_sub(started.elapsed());
    ledger.record(
        "synthesis_b",
        "z3 exclusion sweep",
        started.elapsed().as_secs_f64(),
        "done",
        false,
    );
    let mut exhausted = remaining.is_zero();
    if let Err(error) = &sweep {
        record.sweep_end = Some("tool_error".to_owned());
        record.note = Some(format!("exclusion sweep: {error:#}"));
    }
    if let Ok(sweep) = sweep {
        exhausted |= sweep.exhausted;
        record.sweep_branches = Some(sweep.branches_tried);
        record.sweep_end = Some(
            if sweep.exhausted {
                "time_exhausted"
            } else if sweep.proof.is_some() {
                "proof_found"
            } else {
                "all_branches_finished"
            }
            .to_owned(),
        );
        if let Some((cone, propagation)) = sweep.proof {
            record.b_outcome = Some("sweep_unsat".to_owned());
            return Synthesis::Excluded(exclusion(&cone, propagation, "branch cone"));
        }
        if sweep.propagation_only > 0 {
            record.note = Some(format!(
                "{} branch cones were refuted by propagation but not confirmed by z3",
                sweep.propagation_only
            ));
        }
    }
    let cause = if fallback == "abort_on_constraint_unresolved" {
        fallback
    } else {
        match label {
            "model_not_reproduced" => "synthesis_model_not_reproduced",
            "timeout" => "synthesis_timeout",
            "no_free_input" => "synthesis_no_free_input",
            "propagation_only" => "cone_refuted_by_propagation_only",
            "solver_error" => "synthesis_solver_error",
            _ => "synthesis_cone_too_large",
        }
    };
    // L-05 step 3: a reference input that aborts on a constraint is localized with a
    // diagnostic copy and repaired by re-choosing hint values (never an exclusion).
    if fallback == "abort_on_constraint_unresolved" {
        let start = repair::Start {
            label: "reference",
            stage: "repair",
            input: reference_input.clone(),
            overrides: repair::Overrides::default(),
            candidate_hints: context.property == Property::Tcct,
            protected_site: Some(site.to_owned()),
            inputs_free: true,
            pinned: pinned.keys().copied().collect(),
        };
        let requirement = repair::Requirement {
            targets: targets.to_vec(),
            predicate: None,
        };
        let (reached, search) = repair::search(
            context,
            start,
            &requirement,
            &directory.join("repair"),
            ledger,
        );
        record.changed_inputs = search.changed_inputs.clone();
        record.repair = Some(search);
        if let Some(reached) = reached {
            record.reached_with = Some("hint_injection_with_repair".to_owned());
            return Synthesis::ReachedInjected(Box::new(reached));
        }
    }
    if exhausted {
        // The cause stays on record; the verdict reason says the search was cut short.
        record.cause_before_budget = Some(cause.to_owned());
        return Synthesis::Unknown("budget_exhausted");
    }
    Synthesis::Unknown(cause)
}

/// L-04 step 4: when a cone model's inputs do not reproduce the targets, the hint-assigned
/// wires outside the site whose model values differ from the generator's witness are
/// rewritten to return the model's values, keyed by their instance inputs (as in L-01). The
/// search adds the TCCT candidate's own hints, recompiles, and (L-05) localizes and repairs
/// any abort before the caller checks the witness against the original R1CS.
fn model_overrides(
    context: &EvalContext,
    site: &str,
    model: &BTreeMap<usize, BigUint>,
    witness: &[BigUint],
) -> repair::Overrides {
    let _profile_span = profile_v24::span("model_overrides");
    let sym = context.entry_o0_sym;
    let inside_prefix = format!("{site}.");
    let mut overrides = repair::Overrides::default();
    let mut instances = BTreeSet::new();
    let value_of = |wire: usize| model.get(&wire).unwrap_or(&witness[wire]).clone();
    for (wire, value) in model {
        if &witness[*wire] == value {
            continue;
        }
        let Some(name) = sym.wire_to_names[*wire].first() else {
            continue;
        };
        if name.starts_with(&inside_prefix) {
            continue;
        }
        overrides.rewrite.insert(name.clone(), value.clone());
        let instance = split_instance(name).0.to_owned();
        if instances.insert(instance.clone()) {
            for (member, symbol) in sym
                .by_name
                .range(format!("{instance}.")..format!("{instance}/"))
            {
                if split_instance(&member[instance.len() + 1..]).0.is_empty() {
                    if let Ok(member_wire) = usize::try_from(symbol.wire) {
                        overrides
                            .keys
                            .entry(member.clone())
                            .or_insert_with(|| value_of(member_wire));
                    }
                }
            }
        }
    }
    overrides
}

/// Where a witness generator aborted, and whether the failing check is an R1CS constraint
/// (`===`) or an `assert` that adds no constraint.
#[derive(Debug, Serialize, Clone, Default)]
pub struct AbortSite {
    pub template: String,
    pub line: usize,
    /// `constraint`, `assert`, or `unclassified`.
    pub kind: String,
}

fn classify_abort(
    log: &Path,
    templates: &[TemplateDef],
    sources: &BTreeMap<PathBuf, String>,
) -> AbortSite {
    let text = fs::read_to_string(log).unwrap_or_default();
    let mut site = AbortSite {
        kind: "unclassified".to_owned(),
        ..AbortSite::default()
    };
    let Some(rest) = text.split("Error in template ").nth(1) else {
        return site;
    };
    let mut words = rest.split_whitespace();
    let name = words.next().unwrap_or_default().to_owned();
    let line = words
        .skip_while(|word| *word != "line:")
        .nth(1)
        .and_then(|word| word.parse::<usize>().ok())
        .unwrap_or(0);
    site.template = name.clone();
    site.line = line;
    // circom names template instances `Template_<id>`; strip the id.
    let stripped = name
        .rsplit_once('_')
        .filter(|(_, id)| !id.is_empty() && id.bytes().all(|byte| byte.is_ascii_digit()))
        .map_or(name.as_str(), |(base, _)| base);
    let kinds = templates
        .iter()
        .filter(|template| template.name == stripped || template.name == name)
        .filter_map(|template| {
            let source = sources.get(&template.file)?;
            let masked = source::mask(source);
            let text = masked.lines().nth(line.checked_sub(1)?)?;
            Some(if text.contains("===") {
                "constraint"
            } else if text.contains("assert") {
                "assert"
            } else {
                "unclassified"
            })
        })
        .collect::<BTreeSet<_>>();
    if kinds.len() == 1 {
        site.kind = kinds
            .into_iter()
            .next()
            .unwrap_or("unclassified")
            .to_owned();
    }
    site
}

/// When no carrying witness was built, try to prove that none exists near the site: fix
/// every main input of the constructed input and the candidate's values on the site's
/// signals, and refute a local constraint subset. The original (O1) R1CS is tried first;
/// when optimization removed the site's signals, the O0 R1CS (same solutions on the kept
/// wires) is tried and named as the basis.
fn try_refutation(
    mut result: ClassResult,
    context: &mut EvalContext,
    input: &Value,
    ledger: &mut Ledger,
    fallback: &str,
) -> ClassResult {
    let _profile_span = profile_v24::span("refutation");
    let started = Instant::now();
    let site = result.representative.clone();
    let start_inputs = result
        .inputs
        .iter()
        .filter_map(|binding| binding.entrypoint_input.clone())
        .collect::<Vec<_>>();
    let r1cs = context.entry_r1cs;
    let index = context
        .constraint_index
        .get_or_insert_with(|| refute::constraint_index(r1cs));
    let mut found = refute_view(
        r1cs,
        context.entry_sym,
        index,
        input,
        context.candidate,
        &site,
        &start_inputs,
    )
    .map(|(refutation, signals)| (refutation, signals, "original"));
    if found.is_none() {
        let o0 = context.entry_o0_r1cs;
        let index = context
            .o0_constraint_index
            .get_or_insert_with(|| std::rc::Rc::new(refute::constraint_index(o0)));
        found = refute_view(
            o0,
            context.entry_o0_sym,
            index,
            input,
            context.candidate,
            &site,
            &start_inputs,
        )
        .map(|(refutation, signals)| (refutation, signals, "o0_only"));
    }
    ledger.record(
        "check",
        "local refutation",
        started.elapsed().as_secs_f64(),
        if found.is_some() {
            "refuted"
        } else {
            "inconclusive"
        },
        false,
    );
    result.reason = fallback.to_owned();
    match found {
        Some((refutation, site_signals, basis)) => {
            let (verdict, reason) = refutation_verdict(&result.inputs);
            result.verdict = verdict;
            result.reason = reason.to_owned();
            let key = if verdict == Verdict::ExcludedInContext {
                "excluded_by"
            } else {
                "reference_refuted_by"
            };
            let r1cs_name = if basis == "original" {
                "original (O1)"
            } else {
                "O0 (the original R1CS removed the site signals)"
            };
            result.evidence.insert(
                key.to_owned(),
                format!(
                    "{} {r1cs_name} constraints over {} unknown wires ({} boolean) have no solution with every main input and {site_signals} candidate site signals fixed; constraint indices {:?}",
                    refutation.constraints.len(),
                    refutation.unknowns,
                    refutation.booleans,
                    refutation.constraints
                ),
            );
            result
                .evidence
                .insert("refutation_basis".to_owned(), basis.to_owned());
        }
        None => result.verdict = Verdict::Unknown,
    }
    result
}

/// One refutation attempt on an R1CS view; returns the refutation and the number of
/// candidate site signals that were fixed.
fn refute_view(
    r1cs: &R1cs,
    sym: &SymbolTable,
    index: &[Vec<usize>],
    input: &Value,
    candidate: &BTreeMap<String, BigUint>,
    site: &str,
    start_inputs: &[String],
) -> Option<(refute::Refutation, usize)> {
    let outputs = r1cs.shape.public_outputs;
    let inputs = r1cs.shape.public_inputs + r1cs.shape.private_inputs;
    let mut fixed = BTreeMap::new();
    for wire in 1 + outputs..1 + outputs + inputs {
        let value = sym.wire_to_names[wire]
            .iter()
            .find(|name| is_direct_main(name))
            .and_then(|name| input_leaf(input, name.trim_start_matches("main.")))?;
        fixed.insert(wire as u32, value);
    }
    let mut start = start_inputs
        .iter()
        .filter_map(|path| sym.by_name.get(&format!("main.{path}")))
        .filter_map(|symbol| u32::try_from(symbol.wire).ok())
        .collect::<Vec<_>>();
    let mut site_signals = 0usize;
    for (name, value) in candidate {
        let Some(suffix) = name.strip_prefix("main.") else {
            continue;
        };
        let Some(wire) = sym
            .by_name
            .get(&format!("{site}.{suffix}"))
            .and_then(|symbol| u32::try_from(symbol.wire).ok())
        else {
            continue;
        };
        if fixed.insert(wire, value.clone()).is_none() {
            start.push(wire);
            site_signals += 1;
        }
    }
    if start.is_empty() {
        return None;
    }
    refute::refute(r1cs, index, &fixed, &start).map(|refutation| (refutation, site_signals))
}

/// A refutation fixes every public input of the constructed input. It excludes the site
/// only when each site input is bound directly to an entrypoint input or a constant, so the
/// fixed inputs are exactly what the candidate determines; otherwise it only refutes the
/// reference input that was constructed around the candidate.
fn refutation_verdict(inputs: &[InputBinding]) -> (Verdict, &'static str) {
    let direct = inputs
        .iter()
        .all(|binding| matches!(binding.kind.as_str(), "entrypoint_input" | "constant_equal"));
    if direct && !inputs.is_empty() {
        search_v27::record(serde_json::json!({"kind":"preserved_verdict_branch",
            "branch":"direct_binding_local_constraint_refutation", "inputs":inputs,
            "verdict":"excluded_in_context"}));
        (Verdict::ExcludedInContext, "local_constraint_refutation")
    } else {
        (Verdict::Unknown, "reference_input_refuted")
    }
}

fn input_leaf(input: &Value, path: &str) -> Option<BigUint> {
    let (key, indices) = parse_leaf_path(path).ok()?;
    let mut slot = input.get(&key)?;
    for index in indices {
        slot = slot.get(index)?;
    }
    match slot {
        Value::String(text) => text.parse().ok(),
        Value::Number(number) => number.to_string().parse().ok(),
        _ => None,
    }
}

// ---------------------------------------------------------------------------------------
// Tools

#[allow(clippy::too_many_arguments)]
fn compile(
    tools: &Tools,
    source: &Path,
    output: &Path,
    root: &Path,
    libraries: &[PathBuf],
    o0: bool,
    wasm: bool,
    ledger: &mut Ledger,
    label: Option<&str>,
) -> Result<Compiled> {
    let _profile_span = profile_v24::span("compile_setup");
    fs::create_dir_all(output)?;
    tools.check_tool_identity(&tools.circom)?;
    let mut command = Command::new(&tools.circom);
    command
        .arg(source)
        .args(["--r1cs", "--sym", "--prime", "bn128", "-o"])
        .arg(output)
        .arg("-l")
        .arg(root);
    for library in libraries {
        command.arg("-l").arg(library);
    }
    if wasm {
        command.arg("--wasm");
    }
    if o0 {
        command.arg("--O0");
    }
    let started = Instant::now();
    let (status, timed_out) = profile_v24::measure("compile_process", || {
        run_bounded_logged(
            &mut command,
            site_signal_probe::tool_timeout()?,
            &output.join("compile.log"),
        )
    })?;
    let label = label.map(str::to_owned).unwrap_or_else(|| {
        format!(
            "compile {}{}",
            source.file_name().unwrap_or_default().to_string_lossy(),
            if o0 { " --O0" } else { "" }
        )
    });
    ledger.record(
        "compile",
        &label,
        started.elapsed().as_secs_f64(),
        if timed_out {
            "timeout"
        } else if status.success() {
            "ok"
        } else {
            "failed"
        },
        false,
    );
    ensure!(!timed_out, "circom timed out");
    ensure!(
        status.success(),
        "circom failed: see {}",
        output.join("compile.log").display()
    );
    let stem = source
        .file_stem()
        .context("source has no file stem")?
        .to_string_lossy()
        .into_owned();
    Ok(Compiled {
        r1cs: output.join(format!("{stem}.r1cs")),
        sym: output.join(format!("{stem}.sym")),
        js_dir: wasm.then(|| output.join(format!("{stem}_js"))),
        stem,
    })
}

/// Content key of a compilation of `sources` with `edits` applied: the compiler, the flags,
/// the source and library locations, every source text and the edits. Equal keys are the
/// same compilation (repair copies and hinted entrypoints share `<cache>/edits/<key>`).
fn edits_key(
    tools: &Tools,
    entry_relative: &Path,
    source_root: &Path,
    libraries: &[PathBuf],
    sources: &BTreeMap<PathBuf, String>,
    edits: &repair::Edits,
    o0: bool,
) -> Result<String> {
    let _profile_span = profile_v24::span("compile_key");
    let mut hasher = Sha256::new();
    hasher.update(format!("edits-v1\0o0={o0}\0wasm=true\0"));
    hasher.update(tools.key_digest(&tools.circom)?);
    hasher.update(entry_relative.to_string_lossy().as_bytes());
    for location in std::iter::once(source_root).chain(libraries.iter().map(PathBuf::as_path)) {
        hasher.update(b"\0");
        hasher.update(location.to_string_lossy().as_bytes());
    }
    for (file, text) in sources {
        hasher.update(b"\0");
        hasher.update(file.to_string_lossy().as_bytes());
        hasher.update(Sha256::digest(text.as_bytes()));
    }
    for (file, list) in edits {
        let mut ordered = list.clone();
        ordered.sort();
        hasher.update(b"\0edits\0");
        hasher.update(file.to_string_lossy().as_bytes());
        for (start, end, replacement) in ordered {
            hasher.update(format!("\0{start}:{end}:{}\0", replacement.len()));
            hasher.update(replacement.as_bytes());
        }
    }
    Ok(format!("{:x}", hasher.finalize()))
}

/// Compiles an edited workspace entry; with a cache and a content key the build is kept
/// under `<cache>/edits/<key>` and reused.
#[allow(clippy::too_many_arguments)]
fn compile_edited(
    tools: &Tools,
    cache: Option<(&Path, String)>,
    entry: &Path,
    fallback: &Path,
    root: &Path,
    libraries: &[PathBuf],
    o0: bool,
    ledger: &mut Ledger,
    label: &str,
) -> Result<Compiled> {
    let _profile_span = profile_v24::span("compile_cache_setup");
    let Some((cache, key)) = cache else {
        return compile(
            tools,
            entry,
            fallback,
            root,
            libraries,
            o0,
            true,
            ledger,
            Some(label),
        );
    };
    let folder = cache.join("edits").join(key);
    let stem = entry
        .file_stem()
        .context("entrypoint has no file stem")?
        .to_string_lossy()
        .into_owned();
    if folder.join("complete").exists() {
        ledger.record("compile", &format!("{label} (cache hit)"), 0.0, "ok", true);
        return Ok(Compiled {
            r1cs: folder.join(format!("{stem}.r1cs")),
            sym: folder.join(format!("{stem}.sym")),
            js_dir: Some(folder.join(format!("{stem}_js"))),
            stem,
        });
    }
    if folder.exists() {
        fs::remove_dir_all(&folder)?;
    }
    let compiled = compile(
        tools,
        entry,
        &folder,
        root,
        libraries,
        o0,
        true,
        ledger,
        Some(label),
    )?;
    fs::write(folder.join("complete"), b"")?;
    Ok(compiled)
}

#[allow(clippy::too_many_arguments)]
fn compile_cached(
    tools: &Tools,
    entrypoint: &Path,
    root: &Path,
    libraries: &[PathBuf],
    closure: &BTreeSet<PathBuf>,
    o0: bool,
    cache: Option<&Path>,
    fallback: &Path,
    ledger: &mut Ledger,
) -> Result<Compiled> {
    let _profile_span = profile_v24::span("compile_cache_setup");
    let Some(cache) = cache else {
        return compile(
            tools, entrypoint, fallback, root, libraries, o0, true, ledger, None,
        );
    };
    let mut hasher = Sha256::new();
    hasher.update(format!("o0={o0}\0wasm=true\0"));
    hasher.update(tools.key_digest(&tools.circom)?);
    hasher.update(entrypoint.to_string_lossy().as_bytes());
    for library in std::iter::once(&root.to_path_buf()).chain(libraries) {
        hasher.update(library.to_string_lossy().as_bytes());
    }
    for file in closure {
        hasher.update(file.to_string_lossy().as_bytes());
        hasher.update(sha256_file(file)?);
    }
    let key = format!("{:x}", hasher.finalize());
    let folder = cache.join(&key);
    let stem = entrypoint
        .file_stem()
        .context("entrypoint has no file stem")?
        .to_string_lossy()
        .into_owned();
    if folder.join("complete").exists() {
        ledger.record(
            "compile",
            &format!(
                "compile {stem}{} (cache hit)",
                if o0 { " --O0" } else { "" }
            ),
            0.0,
            "ok",
            true,
        );
        return Ok(Compiled {
            r1cs: folder.join(format!("{stem}.r1cs")),
            sym: folder.join(format!("{stem}.sym")),
            js_dir: Some(folder.join(format!("{stem}_js"))),
            stem,
        });
    }
    if folder.exists() {
        fs::remove_dir_all(&folder)?;
    }
    let compiled = compile(
        tools, entrypoint, &folder, root, libraries, o0, true, ledger, None,
    )?;
    fs::write(folder.join("complete"), b"")?;
    Ok(compiled)
}

/// Runs the circom witness generator. `Ok(None)` means the generator aborted (for
/// example an `assert`), which is a result, not an error.
#[allow(clippy::too_many_arguments)]
fn generate_witness(
    tools: &Tools,
    compiled: &Compiled,
    input: &Path,
    output: &Path,
    prime: &BigUint,
    ledger: &mut Ledger,
    stage: &str,
    label: &str,
) -> Result<Option<Vec<BigUint>>> {
    let _profile_span = profile_v24::span("witness_generation");
    let js_dir = compiled
        .js_dir
        .as_ref()
        .context("artifact has no generator")?;
    tools.check_tool_identity(&tools.node)?;
    let mut command = Command::new(&tools.node);
    command
        .arg(js_dir.join("generate_witness.js"))
        .arg(js_dir.join(format!("{}.wasm", compiled.stem)))
        .arg(input)
        .arg(output);
    let log = output.with_extension("log");
    let started = Instant::now();
    let (status, timed_out) = profile_v24::measure("witness_process", || {
        run_bounded_logged(&mut command, site_signal_probe::tool_timeout()?, &log)
    })?;
    let outcome = if timed_out {
        "timeout"
    } else if status.success() && output.exists() {
        "ok"
    } else {
        "aborted"
    };
    ledger.record(
        stage,
        label,
        started.elapsed().as_secs_f64(),
        outcome,
        false,
    );
    match outcome {
        "timeout" => bail!("witness generation timed out"),
        "aborted" => Ok(None),
        _ => profile_v24::measure("wtns_read_parse", || wtns::read_wtns(output, prime)).map(Some),
    }
}

fn snarkjs_check(
    tools: &Tools,
    r1cs: &Path,
    witness: &Path,
    ledger: &mut Ledger,
) -> Result<String> {
    let _profile_span = profile_v24::span("snarkjs_process");
    tools.check_tool_identity(&tools.snarkjs)?;
    let mut command = Command::new(&tools.snarkjs);
    command.args(["wtns", "check"]).arg(r1cs).arg(witness);
    let log = witness.with_extension("snarkjs.log");
    let started = Instant::now();
    let (status, timed_out) =
        run_bounded_logged(&mut command, site_signal_probe::tool_timeout()?, &log)?;
    let text = fs::read_to_string(&log).unwrap_or_default();
    let verdict = if timed_out {
        "timeout"
    } else if status.success() && text.contains("WITNESS IS CORRECT") {
        "correct"
    } else if text.contains("WITNESS IS NOT CORRECT") {
        "not_correct"
    } else {
        "unresolved"
    };
    ledger.record(
        "check",
        "snarkjs wtns check",
        started.elapsed().as_secs_f64(),
        verdict,
        false,
    );
    Ok(verdict.to_owned())
}

fn write_hint_workspace(
    workspace: &Path,
    source_root: &Path,
    libraries: &[PathBuf],
    sources: &BTreeMap<PathBuf, String>,
    plan: &RewritePlan,
) -> Result<(PathBuf, Vec<PathBuf>)> {
    write_edits_workspace(workspace, source_root, libraries, sources, &plan.edits)
}

/// Copies the source tree and libraries under `workspace` and applies `edits` (original byte
/// ranges, applied back to front) to the copies.
fn write_edits_workspace(
    workspace: &Path,
    source_root: &Path,
    libraries: &[PathBuf],
    sources: &BTreeMap<PathBuf, String>,
    edits: &repair::Edits,
) -> Result<(PathBuf, Vec<PathBuf>)> {
    let _profile_span = profile_v24::span("workspace_copy");
    let root_copy = workspace.join("root");
    copy_circom_tree(source_root, &root_copy)?;
    let mut library_copies = Vec::new();
    for (index, library) in libraries.iter().enumerate() {
        let copy = workspace.join(format!("lib{index}"));
        copy_circom_tree(library, &copy)?;
        library_copies.push(copy);
    }
    for (file, edits) in edits {
        let mut text = sources[file].clone();
        let mut ordered = edits.clone();
        ordered.sort_by_key(|edit| std::cmp::Reverse(edit.0));
        for (start, end, replacement) in ordered {
            text.replace_range(start..end, &replacement);
        }
        // A file may sit under several bases (a library inside the root); rewrite every copy.
        let mut written = false;
        for (base, copy) in std::iter::once((source_root, &root_copy))
            .chain(libraries.iter().map(PathBuf::as_path).zip(&library_copies))
        {
            if let Ok(relative) = file.strip_prefix(base) {
                let target = copy.join(relative);
                // Never write through a recreated link into the original sources.
                let parent = fs::canonicalize(target.parent().context("no parent")?)?;
                ensure!(
                    parent.starts_with(fs::canonicalize(workspace)?)
                        && !fs::symlink_metadata(&target)?.file_type().is_symlink(),
                    "rewritten file {} would leave the hint workspace",
                    target.display()
                );
                fs::write(&target, &text)?;
                written = true;
            }
        }
        ensure!(
            written,
            "rewritten file {} is outside every base",
            file.display()
        );
    }
    Ok((root_copy, library_copies))
}

/// Copies the `.circom` files of a tree. Symbolic links are recreated as links (not
/// followed), so relative links inside the tree keep resolving and link cycles are harmless.
fn copy_circom_tree(from: &Path, to: &Path) -> Result<()> {
    for entry in walkdir::WalkDir::new(from).follow_links(false) {
        site_signal_probe::checkpoint()?;
        let entry = entry?;
        let target = to.join(entry.path().strip_prefix(from)?);
        let is_circom = entry.path().extension().is_some_and(|ext| ext == "circom");
        if entry.file_type().is_symlink() {
            fs::create_dir_all(target.parent().context("copy target has no parent")?)?;
            #[cfg(unix)]
            std::os::unix::fs::symlink(fs::read_link(entry.path())?, &target)?;
            #[cfg(not(unix))]
            bail!("symbolic links are not supported on this platform");
        } else if entry.file_type().is_file() && is_circom {
            fs::create_dir_all(target.parent().context("copy target has no parent")?)?;
            fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------
// Names, inputs, and hashing

/// Splits `a.b[1].c[2]` into (`a.b[1]`, `c[2]`), ignoring dots inside brackets.
fn split_instance(name: &str) -> (&str, &str) {
    let mut depth = 0usize;
    let mut split = None;
    for (index, character) in name.char_indices() {
        match character {
            '[' => depth += 1,
            ']' => depth = depth.saturating_sub(1),
            '.' if depth == 0 => split = Some(index),
            _ => {}
        }
    }
    match split {
        Some(index) => (&name[..index], &name[index + 1..]),
        None => ("", name),
    }
}

fn leaf_base(leaf: &str) -> &str {
    leaf.split('[').next().unwrap_or(leaf)
}

fn leaf_indices(leaf: &str) -> Vec<String> {
    leaf.split('[')
        .skip(1)
        .map(|part| part.trim_end_matches(']').to_owned())
        .collect()
}

fn class_pattern(site: &str) -> String {
    let mut pattern = String::new();
    let mut rest = site;
    while let Some(open) = rest.find('[') {
        let close = rest[open..]
            .find(']')
            .map_or(rest.len(), |offset| open + offset);
        let inner = &rest[open + 1..close];
        pattern.push_str(&rest[..open]);
        if !inner.is_empty() && inner.bytes().all(|byte| byte.is_ascii_digit()) {
            pattern.push_str("[*]");
        } else {
            pattern.push_str(&rest[open..=close.min(rest.len() - 1)]);
        }
        rest = &rest[(close + 1).min(rest.len())..];
    }
    pattern.push_str(rest);
    pattern
}

fn index_vector(site: &str) -> Vec<u64> {
    site.split('[')
        .skip(1)
        .filter_map(|part| part.split(']').next()?.parse().ok())
        .collect()
}

/// Builds a circom input object from leaves like `in[0][1]`.
fn build_input(leaves: &[(String, BigUint)]) -> Result<Value> {
    let mut object = Value::Object(Default::default());
    for (path, value) in leaves {
        let (key, indices) = parse_leaf_path(path)?;
        let map = object.as_object_mut().context("input root")?;
        let mut slot = map.entry(key).or_insert(Value::Null);
        for index in indices {
            if !slot.is_array() {
                *slot = Value::Array(Vec::new());
            }
            let array = slot.as_array_mut().context("input array")?;
            if array.len() <= index {
                array.resize(index + 1, Value::Null);
            }
            slot = &mut array[index];
        }
        *slot = Value::String(value.to_string());
    }
    Ok(object)
}

fn set_input_leaf(input: &mut Value, path: &str, value: &BigUint) -> Result<()> {
    let (key, indices) = parse_leaf_path(path)?;
    let mut slot = input
        .get_mut(&key)
        .with_context(|| format!("base input has no entry for {key}"))?;
    for index in indices {
        slot = slot
            .get_mut(index)
            .with_context(|| format!("base input entry {key} has no index {index}"))?;
    }
    *slot = Value::String(value.to_string());
    Ok(())
}

fn parse_leaf_path(path: &str) -> Result<(String, Vec<usize>)> {
    let key = leaf_base(path).to_owned();
    ensure!(
        !key.is_empty() && !key.contains('.'),
        "unsupported input path {path}"
    );
    let indices = leaf_indices(path)
        .into_iter()
        .map(|index| index.parse::<usize>().context("non-numeric input index"))
        .collect::<Result<Vec<_>>>()?;
    Ok((key, indices))
}

fn write_json(path: &Path, value: &Value) -> Result<()> {
    let _profile_span = profile_v24::span("json_write");
    fs::write(path, serde_json::to_vec_pretty(value)?)?;
    Ok(())
}

fn display_relative(file: &Path, root: &Path, libraries: &[PathBuf]) -> String {
    if let Ok(relative) = file.strip_prefix(root) {
        return relative.display().to_string();
    }
    for (index, library) in libraries.iter().enumerate() {
        if let Ok(relative) = file.strip_prefix(library) {
            return format!("lib{index}/{}", relative.display());
        }
    }
    file.display().to_string()
}

fn resolve_executable(program: &Path) -> Result<PathBuf> {
    if program.components().count() > 1 {
        return fs::canonicalize(program)
            .with_context(|| format!("resolve executable {}", program.display()));
    }
    let path = std::env::var_os("PATH").context("PATH is not set")?;
    for directory in std::env::split_paths(&path) {
        let candidate = directory.join(program);
        if candidate.is_file() {
            return fs::canonicalize(candidate).context("resolve executable");
        }
    }
    bail!("executable {} not found on PATH", program.display())
}

fn sha256_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn sha256_file(path: &Path) -> Result<String> {
    let _profile_span = profile_v24::span("file_hash");
    Ok(sha256_bytes(
        &fs::read(path).with_context(|| format!("read {}", path.display()))?,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn binding(kind: &str) -> InputBinding {
        InputBinding {
            component_input: "x".to_owned(),
            kind: kind.to_owned(),
            entrypoint_input: None,
        }
    }

    #[test]
    fn refutation_excludes_only_when_every_site_input_is_bound_directly() {
        let direct = [binding("entrypoint_input"), binding("constant_equal")];
        assert_eq!(
            refutation_verdict(&direct),
            (Verdict::ExcludedInContext, "local_constraint_refutation")
        );
        let synthesized = [binding("entrypoint_input"), binding("intermediate")];
        assert_eq!(
            refutation_verdict(&synthesized),
            (Verdict::Unknown, "reference_input_refuted")
        );
        assert_eq!(
            refutation_verdict(&[]),
            (Verdict::Unknown, "reference_input_refuted")
        );
    }

    #[test]
    fn constant_exclusions_name_the_r1cs_they_rest_on() {
        use crate::candidate_review::r1cs::{Constraint, Symbol};
        use crate::candidate_review::schema::R1csShape;
        let prime = BigUint::from(101u32);
        // O1 view: wire 1 is fixed to 7 by `w1 - 7 = 0`.
        let r1cs = R1cs {
            prime: prime.clone(),
            shape: R1csShape {
                wires: 2,
                labels: 2,
                public_outputs: 0,
                public_inputs: 0,
                private_inputs: 0,
                constraints: 1,
            },
            constraints: vec![Constraint {
                a: Default::default(),
                b: Default::default(),
                c: [(1u32, BigUint::one()), (0u32, BigUint::from(94u32))]
                    .into_iter()
                    .collect(),
            }],
            wire_labels: vec![0, 1],
        };
        let index = EqualityIndex::build(&r1cs);
        let sym = SymbolTable {
            by_name: [
                ("main.s.kept".to_owned(), Symbol { wire: 1 }),
                ("main.s.gone".to_owned(), Symbol { wire: -1 }),
            ]
            .into_iter()
            .collect(),
            wire_to_names: vec![Vec::new(), vec!["main.s.kept".to_owned()]],
            eliminated_names: BTreeSet::from(["main.s.gone".to_owned()]),
        };
        let seven = BigUint::from(7u32);
        let original = Some((&index, &sym));
        assert_eq!(constant_basis("main.s.kept", &seven, original), "o0_and_o1");
        assert_eq!(
            constant_basis("main.s.kept", &BigUint::from(8u32), original),
            "o0_only_o1_wire_without_constant_equality"
        );
        assert_eq!(
            constant_basis("main.s.gone", &seven, original),
            "o0_only_signal_eliminated_in_o1"
        );
        assert_eq!(
            constant_basis("main.s.kept", &seven, None),
            "o0_only_not_checked"
        );
    }

    #[test]
    fn instantiation_statements_name_the_template() {
        let body = "component lt;\n lt = LessThan(b);\n component bits[2];\n bits[i] = Num2Bits(8); // lt = Other(1)\n";
        assert_eq!(
            instantiated_templates(body, "lt"),
            BTreeSet::from(["LessThan".to_owned()])
        );
        assert_eq!(
            instantiated_templates(body, "bits"),
            BTreeSet::from(["Num2Bits".to_owned()])
        );
        assert!(instantiated_templates(body, "b").is_empty());
    }

    #[test]
    fn aborts_are_classified_by_the_failing_statement() {
        let source = "pragma circom 2.0.0;\ntemplate Range(n) {\n    signal input in;\n    assert(n < 254);\n    in * (in - 1) === 0;\n}\n";
        let file = PathBuf::from("range.circom");
        let templates = parse_templates(&file, source).unwrap();
        let sources = BTreeMap::from([(file, source.to_owned())]);
        let directory = tempfile::tempdir().unwrap();
        let log = directory.path().join("abort.log");
        let classify = |line: usize| {
            fs::write(
                &log,
                format!("Error: Assert Failed.\nError in template Range_0 line: {line}\nError in template Top_1 line: 9\n"),
            )
            .unwrap();
            classify_abort(&log, &templates, &sources)
        };
        let constraint = classify(5);
        assert_eq!(
            (constraint.template.as_str(), constraint.line),
            ("Range_0", 5)
        );
        assert_eq!(constraint.kind, "constraint");
        assert_eq!(classify(4).kind, "assert");
        assert_eq!(classify(3).kind, "unclassified");
        fs::write(&log, "no trace").unwrap();
        assert_eq!(
            classify_abort(&log, &templates, &sources).kind,
            "unclassified"
        );
    }

    #[test]
    fn names_split_on_unbracketed_dots() {
        assert_eq!(split_instance("main.a.b[1].c[2]"), ("main.a.b[1]", "c[2]"));
        assert_eq!(split_instance("main.d"), ("main", "d"));
        assert_eq!(leaf_indices("out[3][1]"), ["3", "1"]);
        assert!(is_direct_main("main.in[0]"));
        assert!(!is_direct_main("main.sub.in"));
    }

    #[test]
    fn classes_abstract_numeric_indices_and_keep_smallest_representative() {
        let sites = ["main.f[10].s", "main.f[2].s", "main.g.s"]
            .map(str::to_owned)
            .to_vec();
        let classes = group_sites(&sites, |_| String::new());
        assert_eq!(classes.len(), 2);
        assert_eq!(classes[0].pattern, "main.f[*].s");
        assert_eq!(classes[0].representative, "main.f[2].s");
        assert_eq!(classes[0].members, 2);
    }

    #[test]
    fn anonymous_component_names_reveal_templates() {
        assert_eq!(
            anonymous_template("IsZero_19_293").as_deref(),
            Some("IsZero")
        );
        assert_eq!(
            anonymous_template("Is_Zero_1_2").as_deref(),
            Some("Is_Zero")
        );
        assert_eq!(anonymous_template("toBits"), None);
    }

    #[test]
    fn inputs_build_and_update_nested_arrays() {
        let one = BigUint::one();
        let mut input = build_input(&[
            ("in[1]".to_owned(), one.clone()),
            ("in[0]".to_owned(), BigUint::zero()),
            ("k".to_owned(), one.clone()),
        ])
        .unwrap();
        assert_eq!(input["in"], serde_json::json!(["0", "1"]));
        set_input_leaf(&mut input, "in[0]", &BigUint::from(7u32)).unwrap();
        assert_eq!(input["in"][0], "7");
        assert!(set_input_leaf(&mut input, "missing", &one).is_err());
    }

    #[test]
    fn an_enclosing_step_does_not_count_its_nested_steps_twice() {
        let mut ledger = Ledger {
            steps: Vec::new(),
            site: None,
        };
        ledger.record("compile", "before", 1.0, "ok", false);
        let from = ledger.steps.len();
        ledger.record("compile", "nested compile", 2.5, "ok", false);
        ledger.record("synthesis_b", "nested witness", 0.5, "aborted", false);
        ledger.record_remainder(from, "synthesis_b", "enclosing", 3.25, "not_reached", false);
        let total: f64 = ledger.steps.iter().map(|step| step.seconds).sum();
        assert_eq!(ledger.steps[3].seconds, 0.25);
        assert_eq!(total, 1.0 + 3.25);
    }
}
