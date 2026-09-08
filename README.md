# zkfDO

`zkfDO` is a Rust CLI by team `kwzzzz` for ranking Circom fuzzing targets and scheduling zkFuzz runs under a limited time budget.

Repository: <https://github.com/kwzzzz/zkfdo-dev>

The project does not reimplement zkFuzz. It scans Circom projects, extracts target features, ranks targets by estimated vulnerability risk and execution cost, schedules fuzzing work, and later invokes an existing zkFuzz binary as a subprocess.

## Status

This repository is in the initial CLI skeleton phase.

Implemented now:

- `zkfDO --help`
- subcommand help output
- dry-run zkFuzz command construction
- Circom file scanning
- lexical static feature extraction
- heuristic target ranking
- placeholder modules for scheduler, reports, and database storage

Not implemented yet:

- recursive Circom parsing
- real zkFuzz subprocess execution
- SQLite persistence
- CSV/JSON/HTML report generation
- adaptive re-ranking after smoke fuzzing

## Quick Start

```sh
cargo run --bin zkfDO -- --help
cargo run --bin zkfDO -- run --target examples/main.circom --dry-run
```

## Commands

- `scan`: discover Circom files in a project
- `features`: extract static features from Circom targets
- `rank`: rank fuzzing targets by risk and cost
- `schedule`: build a budget-aware fuzzing plan
- `run`: build or dry-run a zkFuzz command
- `report`: generate reports from stored run results

## Development

```sh
cargo fmt
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```
