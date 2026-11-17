//! Separate development engine; no implicit cache or output directory.
use std::path::PathBuf;

use clap::Parser;
use zkfdo::candidate_review::lifting::{lift_v27_with_repair_limit, BoostOptions, LiftOptions};

#[derive(Parser)]
#[command(
    name = "zkfdo-j-v27",
    version,
    about = "Search correction and replay diagnostics development engine"
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
    #[arg(long)]
    constraint_witness: bool,
    /// Diagnostic candidate repair cap; independent predicate jobs retain six iterations.
    #[arg(long, value_parser = clap::value_parser!(u16).range(1..))]
    repair_iteration_limit: Option<u16>,
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
        cache: Some(args.cache.join("j-v2.7")),
        instance_store: Some(args.instance_store.join("j-v2.7")),
        circom_bin: args.circom_bin,
        node_bin: args.node_bin,
        snarkjs_bin: args.snarkjs_bin,
        z3_bin: args.z3_bin,
    };
    let boost = BoostOptions {
        constraint_witness: args.constraint_witness,
        class_sweep_budget_seconds: None,
        injection_diagnostics: args.injection_diagnostics,
        aligned_diagnostics: args.aligned_diagnostics,
        post_limit_probe_site: args.post_limit_probe_site,
    };
    let result = lift_v27_with_repair_limit(
        &options,
        &boost,
        usize::from(args.j_jobs),
        args.repair_iteration_limit.map(usize::from),
    )?;
    println!(
        "{}",
        serde_json::json!({"schema":result.schema,"preparation":result.preparation,"sites_found":result.sites_found})
    );
    Ok(())
}
