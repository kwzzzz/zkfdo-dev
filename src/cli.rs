use std::path::PathBuf;

use anyhow::Result;
use clap::{Args, Parser, Subcommand};

use crate::runner;

#[derive(Debug, Parser)]
#[command(
    name = "zkfDO",
    version,
    about = "Rank and schedule zkFuzz targets for large Circom projects",
    long_about = "zkfDO helps scan Circom projects, rank fuzzing targets, schedule work under a limited budget, and prepare zkFuzz subprocess commands."
)]
pub struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
pub enum Commands {
    /// Discover Circom files in a project.
    Scan(ProjectPathArgs),

    /// Extract static features from Circom targets.
    Features(ProjectPathArgs),

    /// Rank targets by estimated vulnerability risk and execution cost.
    Rank(ProjectPathArgs),

    /// Build a budget-aware fuzzing schedule.
    Schedule(ScheduleArgs),

    /// Build or dry-run a zkFuzz command for a target.
    Run(RunArgs),

    /// Generate reports from stored run results.
    Report(ReportArgs),
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

    /// Total fuzzing budget in seconds.
    #[arg(short, long, default_value_t = 600)]
    pub budget_seconds: u64,
}

#[derive(Debug, Args)]
pub struct RunArgs {
    /// Target Circom file.
    #[arg(short, long)]
    pub target: PathBuf,

    /// Existing zkFuzz binary to invoke later.
    #[arg(long, default_value = "zkfuzz")]
    pub zkfuzz_bin: PathBuf,

    /// Per-target fuzzing budget in seconds.
    #[arg(short, long)]
    pub budget_seconds: Option<u64>,

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
        Commands::Scan(args) => {
            println!("scan placeholder: {}", args.project.display());
        }
        Commands::Features(args) => {
            println!("features placeholder: {}", args.project.display());
        }
        Commands::Rank(args) => {
            println!("rank placeholder: {}", args.project.display());
        }
        Commands::Schedule(args) => {
            println!(
                "schedule placeholder: project={}, budget_seconds={}",
                args.project.display(),
                args.budget_seconds
            );
        }
        Commands::Run(args) => {
            let dry_run =
                runner::build_dry_run(&args.zkfuzz_bin, &args.target, args.budget_seconds);

            if args.dry_run {
                println!("{}", dry_run.command.as_shell_words().join(" "));
            } else {
                println!(
                    "runner placeholder: add --dry-run to print the zkFuzz command without executing it"
                );
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
