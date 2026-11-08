//! Separate development engine; no implicit cache or output directory.
use std::path::PathBuf;

use clap::Parser;
use zkfdo::candidate_review::lifting::{
    lift_v24_with_boost, profile_v23_with_boost, BoostOptions, LiftOptions,
};

#[derive(Parser)]
#[command(
    name = "zkfdo-j-v24",
    version,
    about = "Speed development engine; ordered strategies and parallel R1CS checks"
)]
struct Args {
    #[arg(long)]
    request: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long)]
    cache: PathBuf,
    #[arg(long)]
    instance_store: PathBuf,
    #[arg(long)]
    circom_bin: PathBuf,
    #[arg(long)]
    node_bin: PathBuf,
    #[arg(long)]
    snarkjs_bin: PathBuf,
    #[arg(long)]
    z3_bin: PathBuf,
    /// Parallel workers for independent R1CS checks; strategies stay sequential.
    #[arg(long, default_value_t = 1, value_parser = clap::value_parser!(u16).range(1..=64))]
    j_jobs: u16,
    /// Measure legacy operations without enabling speed changes.
    #[arg(long, conflicts_with = "j_jobs")]
    profile_only: bool,
    #[arg(long)]
    constraint_witness: bool,
    #[arg(long)]
    class_sweep_budget_seconds: Option<u64>,
    #[arg(long)]
    injection_diagnostics: bool,
    #[arg(long, requires = "constraint_witness")]
    aligned_diagnostics: bool,
    /// Run one separate diagnostic after all class verdicts have been computed.
    #[arg(long)]
    post_limit_probe_site: Option<String>,
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();
    let options = LiftOptions {
        request: args.request,
        output: args.output,
        cache: Some(args.cache.join("j-v2.4")),
        instance_store: Some(args.instance_store.join("j-v2.4")),
        circom_bin: args.circom_bin,
        node_bin: args.node_bin,
        snarkjs_bin: args.snarkjs_bin,
        z3_bin: args.z3_bin,
    };
    let boost = BoostOptions {
        constraint_witness: args.constraint_witness,
        class_sweep_budget_seconds: args.class_sweep_budget_seconds,
        injection_diagnostics: args.injection_diagnostics,
        aligned_diagnostics: args.aligned_diagnostics,
        post_limit_probe_site: args.post_limit_probe_site,
    };
    let result = if args.profile_only {
        profile_v23_with_boost(&options, &boost)?
    } else {
        lift_v24_with_boost(&options, &boost, usize::from(args.j_jobs))?
    };
    println!(
        "{}",
        serde_json::json!({"schema":result.schema,"preparation":result.preparation,"sites_found":result.sites_found})
    );
    Ok(())
}
