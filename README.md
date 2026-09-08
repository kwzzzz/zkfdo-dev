# zkfDO

`zkfDO` is a Rust CLI by team `kwzzzz` for ranking Circom fuzzing targets and scheduling zkFuzz runs under a limited time budget.

Repository: <https://github.com/kwzzzz/zkfdo-dev>

The project does not reimplement zkFuzz. It scans Circom projects, extracts target features, ranks targets by estimated vulnerability risk and execution cost, and invokes an existing zkFuzz binary as a budget-limited subprocess.

## Status

This repository has a working static-ranking pipeline and a minimal single-target runner.

Implemented now:

- `zkfDO --help`
- subcommand help output
- dry-run zkFuzz command construction
- Circom file scanning
- lexical static feature extraction
- heuristic target ranking
- real zkFuzz subprocess execution with a per-target timeout
- raw stdout/stderr logs and structured JSON run results
- placeholder modules for scheduler, reports, and database storage

Not implemented yet:

- recursive Circom parsing
- SQLite persistence
- CSV/JSON/HTML report generation
- adaptive re-ranking after smoke fuzzing

## Quick Start

```sh
cargo run --bin zkfDO -- --help
cargo run --bin zkfDO -- run --target examples/main.circom --dry-run
cargo run --bin zkfDO -- run --target examples/main.circom --budget-seconds 10
```

Completed runs are stored under `runs/<run-id>/` as `result.json`, `stdout.log`, and `stderr.log`.

## Commands

- `scan`: discover Circom files in a project
- `features`: extract static features from Circom targets
- `rank`: rank fuzzing targets by risk and cost
- `schedule`: build a budget-aware fuzzing plan
- `run`: execute or dry-run zkFuzz for one target
- `report`: generate reports from stored run results

## Development

```sh
cargo fmt
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```
