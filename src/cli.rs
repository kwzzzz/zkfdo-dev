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
        Commands::Targets(args) => {
            let circom_bin = (!args.no_validate).then_some(args.circom_bin.as_path());
            let report =
                targets::discover_project_targets(&args.project, &args.output, circom_bin)?;
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
            println!(
                "report placeholder: input={}, output={}",
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
    }
    Ok(())
}
