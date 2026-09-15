# zkfDO

`zkfDO` is a Rust CLI by team `kwzzzz` for ranking Circom fuzzing targets and scheduling zkFuzz runs under a limited time budget.

Repository: <https://github.com/kwzzzz/zkfdo-dev>

The project does not reimplement zkFuzz. It scans Circom projects, extracts target features, ranks targets by estimated vulnerability risk and execution cost, and invokes an existing zkFuzz binary as a budget-limited subprocess.

## Status

This repository has static ranking experiments over explicit Circom targets, a single-target runner, a uniform scheduling baseline, and an MVP for semantic fuzz-target discovery. A bounded seven-strategy dev3 backend-candidate pilot has been completed. Confirmed real-project ranking performance and a confirmed real-project positive control have not yet been established.

Implemented now:

- `zkfDO --help`
- subcommand help output
- dry-run zkFuzz command construction
- Circom file scanning
- reachable concrete template-instantiation discovery for a documented Circom subset
- standalone wrapper generation and optional Circom compile validation
- lexical static feature extraction
- heuristic target ranking
- real zkFuzz subprocess execution with a per-target timeout
- raw stdout/stderr logs and structured JSON run results
- uniform per-target budget scheduling and experiment summaries
- explicit corpus preparation, seven static ranking strategies, saved plans, and execution in ranked order under a total budget
- evaluation JSON separating backend candidates from reviewed project defects
- repeated-pilot validation and aggregation over paired backend seeds
- placeholder modules for reports and database storage

Not implemented yet:

- complete Circom syntax/semantic analysis
- automatic discovery-to-experiment corpus curation (the original `schedule` command remains file-based)
- adaptive scheduling and runtime re-ranking
- SQLite persistence
- general CSV/HTML report generation and implementation of the legacy `report` command
- confirmed-defect performance evaluation on a held-out multi-project corpus and a confirmed real-project positive control

## Quick Start

```sh
cargo run --bin zkfDO -- --help
cargo run --bin zkfDO -- targets --project examples --output .zkfdo/targets
cargo run --bin zkfDO -- run --target examples/main.circom --dry-run
cargo run --bin zkfDO -- run --target examples/main.circom --budget-seconds 10
cargo run --bin zkfDO -- schedule --project examples --budget-seconds 10
```

Completed runs are stored under `runs/<run-id>/` as `result.json`, `stdout.log`, and `stderr.log`.
Uniform experiments are stored under `runs/<experiment-id>/` with a `summary.json` and nested target runs.
Target discovery output is stored under `.zkfdo/targets/<discovery-id>/` as `discovery.json` plus one directory per generated wrapper. Pass `--no-validate` to generate wrappers without invoking `circom`.

For explicit static experiments, use the four separate stages:

```sh
target/debug/zkfDO experiment prepare --manifest YOUR_MANIFEST.json --output runs/prepared
target/debug/zkfDO experiment plan --prepared PREPARED.json --strategy risk-only --output runs/plan.json
target/debug/zkfDO experiment run --plan runs/plan.json --budget-seconds 10 --total-budget-seconds 60 --zkfuzz-seed 123 --output runs/static
target/debug/zkfDO experiment evaluate --plan runs/plan.json --outcome OUTCOME.json --output runs/evaluation.json
```

Replace the uppercase paths with your manifest and the reports produced by prior commands. Preparation without `--strategy` collects a common complete feature set; planning prints JSON without fuzzing. The checked-in `risk-grouped` boundary was frozen from the three-target development manifest, where every observed complexity was zero, so it currently provides no measured grouping benefit. The [bounded repeated-pilot report](experiments/dev3-ranking-pilot-2026-09-15.json) contains 49 strategy executions and candidate-level timing results; it does not establish confirmed-defect superiority. See [the complete workflow, runnable synthetic example, and evidence limits](docs/static_ranking_experiment.md).

## Commands

- `scan`: discover Circom files in a project
- `targets`: find concrete template instantiations reachable from `component main`, generate wrappers, and validate them with Circom
- `features`: extract static features from Circom targets
- `rank`: rank fuzzing targets by risk and cost
- `schedule`: execute all discovered targets with a uniform per-target budget
- `run`: execute or dry-run zkFuzz for one target
- `report`: reserved report command (currently a placeholder)
- `experiment prepare|plan|run|evaluate`: prepare explicit targets, freeze a static order, execute it, and evaluate stored evidence

## Development

```sh
cargo fmt
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```
