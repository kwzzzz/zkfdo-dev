# zkfDO

`zkfDO` is a Rust CLI by team `kwzzzz` for ranking Circom fuzzing targets and scheduling zkFuzz runs under a limited time budget.

Repository: <https://github.com/kwzzzz/zkfdo-dev>

The project does not reimplement zkFuzz. It scans Circom projects, extracts target features, ranks targets by estimated vulnerability risk and execution cost, and invokes an existing zkFuzz binary as a budget-limited subprocess.

## Status

This repository has a working static-ranking pipeline, a minimal single-target runner, and a uniform scheduling baseline.

Implemented now:

- `zkfDO --help`
- subcommand help output
- dry-run zkFuzz command construction
- Circom file scanning
- lexical static feature extraction
- heuristic target ranking
- real zkFuzz subprocess execution with a per-target timeout
- raw stdout/stderr logs and structured JSON run results
- uniform per-target budget scheduling and experiment summaries
- placeholder modules for reports and database storage

Not implemented yet:

- recursive Circom parsing
- rank-aware and adaptive scheduling
- SQLite persistence
- CSV/JSON/HTML report generation
- adaptive re-ranking after smoke fuzzing

## Quick Start

```sh
cargo run --bin zkfDO -- --help
cargo run --bin zkfDO -- run --target examples/main.circom --dry-run
cargo run --bin zkfDO -- run --target examples/main.circom --budget-seconds 10
cargo run --bin zkfDO -- schedule --project examples --budget-seconds 10
```

Completed runs are stored under `runs/<run-id>/` as `result.json`, `stdout.log`, and `stderr.log`.
Uniform experiments are stored under `runs/<experiment-id>/` with a `summary.json` and nested target runs.

## Commands

- `scan`: discover Circom files in a project
- `features`: extract static features from Circom targets
- `rank`: rank fuzzing targets by risk and cost
- `schedule`: execute all discovered targets with a uniform per-target budget
- `run`: execute or dry-run zkFuzz for one target
- `report`: generate reports from stored run results

## Development

```sh
cargo fmt
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```
