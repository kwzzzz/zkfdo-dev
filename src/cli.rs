use std::path::PathBuf;

use anyhow::Result;
use clap::{Args, Parser, Subcommand};

use crate::static_rank::RankingStrategy;
use crate::{corpus, experiment, features, ranker, runner, scanner, scheduler, targets};

#[derive(Debug, Parser)]
#[command(
    name = "zkfDO",
    version,
    about = "Rank and schedule zkFuzz targets for large Circom projects",
    long_about = "zkfDO helps scan Circom projects, rank fuzzing targets, and execute zkFuzz subprocesses under a limited budget."
)]
pub struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
pub enum Commands {
    /// Discover Circom files in a project.
    Scan(ProjectPathArgs),

    /// Discover concrete, reachable template instantiations and generate wrappers.
    Targets(TargetDiscoveryArgs),

    /// Capture every template instance and its arguments from an instrumented O0 compile (F-01).
    Capture(CaptureArgs),

    /// Extract static features from Circom targets.
    Features(ProjectPathArgs),

    /// Rank targets by estimated vulnerability risk and execution cost.
    Rank(ProjectPathArgs),

    /// Run every discovered target with the same fuzzing budget.
    Schedule(ScheduleArgs),

    /// Execute or dry-run zkFuzz for one target.
    Run(RunArgs),

    /// Generate reports from stored run results.
    Report(ReportArgs),

    /// Prepare, plan, run, and evaluate explicit static ranking experiments.
    Experiment(ExperimentArgs),
}

#[derive(Debug, Args)]
pub struct ProjectPathArgs {
    /// Circom project root.
    #[arg(short, long, default_value = ".")]
    pub project: PathBuf,
}

#[derive(Debug, Args)]
pub struct ScheduleArgs {
    /// Circom project root.
    #[arg(short, long, default_value = ".")]
    pub project: PathBuf,

    /// Fuzzing budget per target in seconds.
    #[arg(short, long, default_value_t = 60)]
    pub budget_seconds: u64,

    /// Existing zkFuzz binary to invoke.
    #[arg(long, default_value = "zkfuzz")]
    pub zkfuzz_bin: PathBuf,

    /// Root directory for experiment results and raw logs.
    #[arg(short, long, default_value = "runs")]
    pub output: PathBuf,
}

#[derive(Debug, Args)]
pub struct TargetDiscoveryArgs {
    /// Circom project root.
    #[arg(short, long, default_value = ".")]
    pub project: PathBuf,

    /// Root directory for discovery reports and generated wrappers.
    #[arg(short, long, default_value = ".zkfdo/targets")]
    pub output: PathBuf,

    /// Circom compiler used to validate generated wrappers.
    #[arg(long, default_value = "circom")]
    pub circom_bin: PathBuf,

    /// Generate wrappers without invoking the Circom compiler.
    #[arg(long)]
    pub no_validate: bool,

    /// Discover only from this file's component main and its include closure.
    #[arg(long)]
    pub entrypoint: Option<PathBuf>,

    /// Circom library directory (-l); repeatable, searched in the given order.
    #[arg(long = "library-path", requires = "entrypoint")]
    pub library_paths: Vec<PathBuf>,

    /// Per-wrapper compile limit; the compiler process group is killed when it expires.
    #[arg(long, default_value_t = targets::DEFAULT_WRAPPER_COMPILE_TIMEOUT_SECONDS)]
    pub compile_timeout_seconds: u64,

    /// Also discover instances from an instrumented O0 compile of the entrypoint (F-01). The
    /// interpreter still runs; the report says which result each target came from.
    #[arg(long, requires = "entrypoint")]
    pub instance_capture: bool,

    /// Compile limit for the instrumented copy.
    #[arg(long, default_value_t = targets::DEFAULT_CAPTURE_TIMEOUT_SECONDS)]
    pub capture_timeout_seconds: u64,
}

#[derive(Debug, Args)]
pub struct CaptureArgs {
    /// Circom project root.
    #[arg(short, long)]
    pub project: PathBuf,

    /// Entrypoint with `component main`.
    #[arg(long)]
    pub entrypoint: PathBuf,

    /// Circom library directory (-l); repeatable.
    #[arg(long = "library-path")]
    pub library_paths: Vec<PathBuf>,

    /// New directory for instance-capture.json and the diagnostic build.
    #[arg(short, long)]
    pub output: PathBuf,

    #[arg(long, default_value = "circom")]
    pub circom_bin: PathBuf,

    #[arg(long, default_value_t = targets::DEFAULT_CAPTURE_TIMEOUT_SECONDS)]
    pub timeout_seconds: u64,

    /// Also compile the original at O0 and check that removing the capture signals and their
    /// constraints gives back the original O0 R1CS.
    #[arg(long)]
    pub verify_neutrality: bool,
}

#[derive(Debug, Args)]
pub struct RunArgs {
    /// Target Circom file.
    #[arg(short, long)]
    pub target: PathBuf,

    /// Existing zkFuzz binary to invoke.
    #[arg(long, default_value = "zkfuzz")]
    pub zkfuzz_bin: PathBuf,

    /// Per-target fuzzing budget in seconds.
    #[arg(short, long, default_value_t = 60)]
    pub budget_seconds: u64,

    /// Root directory for run results and raw logs.
    #[arg(short, long, default_value = "runs")]
    pub output: PathBuf,

    /// Print the zkFuzz command without executing it.
    #[arg(long)]
    pub dry_run: bool,
}

#[derive(Debug, Args)]
pub struct ReportArgs {
    /// Run directory to read.
    #[arg(short, long, default_value = "runs")]
    pub input: PathBuf,

    /// Report output directory.
    #[arg(short, long, default_value = "reports/generated")]
    pub output: PathBuf,
}

#[derive(Debug, Args)]
pub struct ExperimentArgs {
    #[command(subcommand)]
    pub command: ExperimentCommands,
}

#[derive(Debug, Subcommand)]
pub enum ExperimentCommands {
    /// Prepare concrete corpus targets and requested static analysis; no fuzz search.
    Prepare(ExperimentPrepareArgs),
    /// Write and print a ranked execution plan without running zkFuzz.
    Plan(ExperimentPlanArgs),
    /// Execute a saved plan in order under explicit per-target and total budgets.
    Run(ExperimentRunArgs),
    /// Evaluate stored results using optional reviewed defect confirmations.
    Evaluate(ExperimentEvaluateArgs),
    /// Review preserved backend candidates or qualify injected ground truth.
    Review(ExperimentReviewArgs),
    /// Import value-free whole/split metadata and existing review claims; no execution.
    Record(ExperimentRecordArgs),
    /// Aggregate hash-pinned evidence metadata offline; no candidate or evidence execution.
    Aggregate(ExperimentAggregateArgs),
    /// Build the review inputs that qualify one planned development injection.
    Inject(ExperimentInjectArgs),
    /// Lift one component candidate to the entrypoint's call sites (L-01 feasibility).
    Lift(ExperimentLiftArgs),
    /// Join assumption-predicate verdicts per (entrypoint, instance) over lift results.
    LiftInstances(ExperimentLiftInstancesArgs),
}

#[derive(Debug, Args)]
pub struct ExperimentPrepareArgs {
    /// Corpus manifest file.
    #[arg(long)]
    pub manifest: PathBuf,

    /// Root directory for prepared targets, captures, and prepared.json.
    #[arg(short, long)]
    pub output: PathBuf,

    /// Prepare only features needed by this strategy; omit for the common comparison set.
    #[arg(long)]
    pub strategy: Option<RankingStrategy>,

    /// Circom compiler used for concrete R1CS size and compile validation.
    #[arg(long, default_value = "circom")]
    pub circom_bin: PathBuf,

    /// Existing zkFuzz frontend used for AST statistics when requested.
    #[arg(long, default_value = "zkfuzz")]
    pub zkfuzz_bin: PathBuf,

    /// Circomspect binary; defaults to the supported local build in .external/circomspect.
    #[arg(long = "circomspect-bin", alias = "analyzer-bin")]
    pub analyzer_bin: Option<PathBuf>,

    /// Recorded analyzer version override for a deliberately selected build.
    #[arg(long)]
    pub analyzer_version: Option<String>,

    /// Recorded analyzer source revision override for a deliberately selected build.
    #[arg(long)]
    pub analyzer_revision: Option<String>,

    /// Maximum wall-clock seconds for each preparation tool invocation.
    #[arg(long, default_value_t = 60, value_parser = clap::value_parser!(u64).range(1..))]
    pub tool_timeout_seconds: u64,
}

#[derive(Debug, Args)]
pub struct ExperimentPlanArgs {
    /// Prepared corpus JSON produced by experiment prepare.
    #[arg(long)]
    pub prepared: PathBuf,

    /// path-order, random, small-first, legacy, warning-first, risk-only, risk-grouped, or cost-aware.
    #[arg(long)]
    pub strategy: RankingStrategy,

    /// Frozen static ranking configuration.
    #[arg(long, default_value = "configs/static-ranking.json")]
    pub config: PathBuf,

    /// Seed for the random target permutation, separate from zkFuzz's seed.
    #[arg(long, required_if_eq("strategy", "random"))]
    pub ranking_seed: Option<u64>,

    /// Destination JSON plan file.
    #[arg(short, long)]
    pub output: PathBuf,
}

#[derive(Debug, Args)]
pub struct ExperimentRunArgs {
    /// Saved execution plan JSON.
    #[arg(long)]
    pub plan: PathBuf,

    /// Existing zkFuzz binary to invoke.
    #[arg(long, default_value = "zkfuzz")]
    pub zkfuzz_bin: PathBuf,

    /// Maximum fuzzing wall-clock seconds per target.
    #[arg(long, value_parser = clap::value_parser!(u64).range(1..))]
    pub budget_seconds: u64,

    /// Overall process-attempt budget; required result persistence can finish just after it.
    #[arg(long, value_parser = clap::value_parser!(u64).range(1..))]
    pub total_budget_seconds: u64,

    /// zkFuzz seed, separate from the plan's ranking seed.
    #[arg(long)]
    pub zkfuzz_seed: Option<u64>,

    /// Existing zkFuzz mutation settings file.
    #[arg(long)]
    pub mutation_settings: Option<PathBuf>,

    /// Root directory for experiment results and raw logs.
    #[arg(short, long)]
    pub output: PathBuf,
}

#[derive(Debug, Args)]
pub struct ExperimentEvaluateArgs {
    /// Saved execution plan JSON.
    #[arg(long)]
    pub plan: PathBuf,

    /// Saved experiment outcome JSON.
    #[arg(long)]
    pub outcome: PathBuf,

    /// Schema 1/2 reviewed evidence; only linked backend discoveries enter defect curves.
    #[arg(long)]
    pub confirmations: Option<PathBuf>,

    /// Destination evaluation JSON file.
    #[arg(short, long)]
    pub output: PathBuf,
}

#[derive(Debug, Args)]
pub struct ExperimentRecordArgs {
    /// Schema-1 or schema-2 offline evidence import request with hash-pinned metadata.
    #[arg(long)]
    pub request: PathBuf,

    /// New JSON file; existing files are never overwritten.
    #[arg(short, long)]
    pub output: PathBuf,
}

#[derive(Debug, Args)]
pub struct ExperimentAggregateArgs {
    /// Schema-1 aggregate request listing hash-pinned v1/v2 evidence records.
    #[arg(long)]
    pub request: PathBuf,

    /// New JSON file; existing files are never overwritten.
    #[arg(short, long)]
    pub output: PathBuf,
}

#[derive(Debug, Args)]
pub struct ExperimentReviewArgs {
    /// Strict schema-1 backend or injection review request.
    #[arg(long)]
    pub request: PathBuf,

    /// New directory for the value-free report, confirmations, and bundle index.
    #[arg(short, long)]
    pub output: PathBuf,

    /// Python interpreter used for hash-pinned predicate workers.
    #[arg(long, default_value = "python3")]
    pub python_bin: PathBuf,

    /// Source identity label (Git revision or pinned worktree-manifest hash).
    #[arg(long)]
    pub source_revision: String,

    /// Sorted source-file manifest that fixes the review engine implementation.
    #[arg(long)]
    pub engine_source_manifest: PathBuf,
}

#[derive(Debug, Args)]
pub struct ExperimentInjectArgs {
    /// Strict schema-1 injection plan.
    #[arg(long)]
    pub plan: PathBuf,

    /// Circom compiler that is copied into the workspace and pinned.
    #[arg(long, default_value = "circom")]
    pub circom_bin: PathBuf,

    /// Node.js runtime used by the pinned witness generators.
    #[arg(long, default_value = "node")]
    pub node_bin: PathBuf,

    /// External relation verifier; defaults to the one built next to this executable.
    #[arg(long)]
    pub relation_verifier_bin: Option<PathBuf>,
}

#[derive(Debug, Args)]
pub struct ExperimentLiftArgs {
    /// Lifting request (zkfdo-lifting-request-v1).
    #[arg(long)]
    pub request: PathBuf,

    /// New directory for result.json and the raw (value-bearing) artifacts.
    #[arg(short, long)]
    pub output: PathBuf,

    /// Optional directory that reuses entrypoint compilations across requests.
    #[arg(long)]
    pub cache: Option<PathBuf>,

    #[arg(long, default_value = "circom")]
    pub circom_bin: PathBuf,

    #[arg(long, default_value = "node")]
    pub node_bin: PathBuf,

    #[arg(long, default_value = "snarkjs")]
    pub snarkjs_bin: PathBuf,

    /// z3 for bounded local input synthesis (optional; stage b is skipped if absent).
    #[arg(long, default_value = "z3")]
    pub z3_bin: PathBuf,

    /// Directory of proved assumption-predicate verdicts shared by (entrypoint, instance).
    #[arg(long)]
    pub instance_store: Option<PathBuf>,
}

#[derive(Debug, Args)]
pub struct ExperimentLiftInstancesArgs {
    /// Lift result.json files to join.
    #[arg(long, required = true, num_args = 1..)]
    pub result: Vec<PathBuf>,

    /// Output JSON (zkfdo-instance-verdicts-v1).
    #[arg(short, long)]
    pub output: PathBuf,
}

pub fn run() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .with_target(false)
        .without_time()
        .init();

    let cli = Cli::parse();
    handle(cli)
}

pub fn handle(cli: Cli) -> Result<()> {
    match cli.command {
        Commands::Experiment(args) => handle_experiment(args)?,
        Commands::Scan(args) => {
            let targets = scanner::scan_project(&args.project)?;
            println!("{}", serde_json::to_string_pretty(&targets)?);
        }
        Commands::Capture(args) => {
            let report = crate::instance_capture::capture_command(
                &args.project,
                &args.entrypoint,
                &args.library_paths,
                &args.output,
                &args.circom_bin,
                args.timeout_seconds,
                args.verify_neutrality,
            )?;
            println!("{}", serde_json::to_string_pretty(&report)?);
        }
        Commands::Targets(args) => {
            let options = targets::DiscoveryOptions {
                entrypoint: args.entrypoint,
                library_paths: args.library_paths,
                circom_bin: (!args.no_validate).then_some(args.circom_bin.clone()),
                compile_timeout_seconds: args.compile_timeout_seconds,
                instance_capture: args.instance_capture.then_some(args.circom_bin),
                capture_timeout_seconds: args.capture_timeout_seconds,
            };
            let report =
                targets::discover_project_targets_with(&args.project, &args.output, &options)?;
            println!("{}", serde_json::to_string_pretty(&report)?);
        }
        Commands::Features(args) => {
            let features = features::extract_project_features(&args.project)?;
            println!("{}", serde_json::to_string_pretty(&features)?);
        }
        Commands::Rank(args) => {
            let features = features::extract_project_features(&args.project)?;
            let ranked = ranker::rank_targets(&features);
            println!("{}", serde_json::to_string_pretty(&ranked)?);
        }
        Commands::Schedule(args) => {
            let targets = scanner::scan_project(&args.project)?
                .into_iter()
                .map(|target| target.path)
                .collect::<Vec<_>>();
            let summary = scheduler::run_uniform_experiment(
                &targets,
                args.budget_seconds,
                &args.zkfuzz_bin,
                &args.output,
            )?;
            println!("{}", serde_json::to_string_pretty(&summary)?);
        }
        Commands::Run(args) => {
            if args.dry_run {
                let dry_run =
                    runner::build_dry_run(&args.zkfuzz_bin, &args.target, args.budget_seconds);
                println!("{}", dry_run.command.as_shell_words().join(" "));
            } else {
                let result = runner::run_zkfuzz(
                    &args.zkfuzz_bin,
                    &args.target,
                    args.budget_seconds,
                    &args.output,
                )?;
                println!("{}", serde_json::to_string_pretty(&result)?);
            }
        }
        Commands::Report(args) => {
            anyhow::bail!(
                "report is not implemented: input={}, output={}",
                args.input.display(),
                args.output.display()
            );
        }
    }

    Ok(())
}

fn handle_experiment(args: ExperimentArgs) -> Result<()> {
    match args.command {
        ExperimentCommands::Prepare(args) => {
            let mut options = corpus::PrepareOptions {
                circom_bin: args.circom_bin,
                zkfuzz_bin: args.zkfuzz_bin,
                timeout_seconds: args.tool_timeout_seconds,
                strategy: args.strategy,
                ..Default::default()
            };
            if let Some(binary) = args.analyzer_bin {
                options.analyzer_bin = binary;
            }
            if let Some(version) = args.analyzer_version {
                options.analyzer_version = version;
            }
            if let Some(revision) = args.analyzer_revision {
                options.analyzer_revision = revision;
            }
            let prepared = corpus::prepare_manifest(&args.manifest, &options, &args.output)?;
            println!("{}", serde_json::to_string_pretty(&prepared)?);
        }
        ExperimentCommands::Plan(args) => {
            let plan = experiment::create_plan(
                &args.prepared,
                args.strategy,
                &args.config,
                args.ranking_seed,
                &args.output,
            )?;
            println!("{}", serde_json::to_string_pretty(&plan)?);
        }
        ExperimentCommands::Run(args) => {
            let outcome = experiment::execute_plan(
                &args.plan,
                &experiment::ExecuteOptions {
                    zkfuzz_bin: args.zkfuzz_bin,
                    budget_seconds: args.budget_seconds,
                    total_budget_seconds: args.total_budget_seconds,
                    zkfuzz_seed: args.zkfuzz_seed,
                    mutation_settings: args.mutation_settings,
                    output: args.output,
                },
            )?;
            println!("{}", serde_json::to_string_pretty(&outcome)?);
        }
        ExperimentCommands::Evaluate(args) => {
            let evaluation = experiment::evaluate(
                &args.plan,
                &args.outcome,
                args.confirmations.as_deref(),
                &args.output,
            )?;
            println!("{}", serde_json::to_string_pretty(&evaluation)?);
        }
        ExperimentCommands::Record(args) => {
            let record = crate::evidence_record::import_record(&args.request, &args.output)?;
            println!("{}", serde_json::to_string_pretty(&record)?);
        }
        ExperimentCommands::Aggregate(args) => {
            let report =
                crate::evidence_record::aggregate::aggregate_records(&args.request, &args.output)?;
            println!("{}", serde_json::to_string_pretty(&report)?);
        }
        ExperimentCommands::Review(args) => {
            let output =
                crate::candidate_review::review(&crate::candidate_review::ReviewOptions {
                    request: args.request,
                    output: args.output,
                    python_bin: args.python_bin,
                    source_revision: args.source_revision,
                    engine_source_manifest: args.engine_source_manifest,
                    executable: std::env::current_exe()?,
                })?;
            println!("{}", serde_json::to_string_pretty(&output)?);
        }
        ExperimentCommands::Lift(args) => {
            let result = crate::candidate_review::lifting::lift(
                &crate::candidate_review::lifting::LiftOptions {
                    request: args.request,
                    output: args.output,
                    cache: args.cache,
                    circom_bin: args.circom_bin,
                    node_bin: args.node_bin,
                    snarkjs_bin: args.snarkjs_bin,
                    z3_bin: args.z3_bin,
                    instance_store: args.instance_store,
                },
            )?;
            println!(
                "{}",
                serde_json::to_string_pretty(&serde_json::json!({
                    "request_id": result.request_id,
                    "preparation": result.preparation,
                    "sites_found": result.sites_found,
                    "verdict_counts": result.verdict_counts,
                    "total_seconds": result.costs.total_seconds,
                }))?
            );
        }
        ExperimentCommands::LiftInstances(args) => {
            let verdicts =
                crate::candidate_review::lifting::instances::write(&args.result, &args.output)?;
            println!(
                "{}",
                serde_json::to_string_pretty(&serde_json::json!({
                    "results": verdicts.results.len(),
                    "instances": verdicts.instances.len(),
                    "counts": verdicts.counts,
                    "conflicts": verdicts.conflicts,
                    "changed_by_sharing": verdicts.changed_by_sharing,
                }))?
            );
        }
        ExperimentCommands::Inject(args) => {
            let relation_verifier_bin = match args.relation_verifier_bin {
                Some(path) => path,
                None => std::env::current_exe()?
                    .parent()
                    .map(|directory| directory.join("zkfdo-relation-verifier"))
                    .ok_or_else(|| anyhow::anyhow!("executable has no parent directory"))?,
            };
            let output = crate::injection::build(&crate::injection::InjectOptions {
                plan: args.plan,
                circom_bin: args.circom_bin,
                node_bin: args.node_bin,
                relation_verifier_bin,
            })?;
            println!("{}", serde_json::to_string_pretty(&output)?);
        }
    }
    Ok(())
}
