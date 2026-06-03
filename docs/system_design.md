# System Design

## Technical Identity

zkfDO is a Rust-based helper CLI for zkFuzz. It uses zkFuzz as an external binary and does not replace zkFuzz. The project improves the project-level fuzzing workflow around zkFuzz by adding target discovery, prioritization, budget-aware scheduling, structured result collection, and reporting.

## Module Architecture

### `cli.rs`

Defines the command-line interface and subcommand parsing. This module should stay focused on argument definitions and dispatching work to other modules.

### `config.rs`

Defines project config, zkFuzz config, and fuzzing profile config structures. Later versions should load `.zkfdo/config.toml` and named profiles such as fast, balanced, and deep.

### `scanner.rs`

Implements Circom project scanning and target discovery. The first version should discover `.circom` files and identify entrypoint candidates.

### `features.rs`

Extracts static and cost features from Circom targets. Early features can be lexical and file-level; later features may use compiler outputs or analyzer outputs.

### `ranker.rs`

Implements ranking strategies and priority scoring, including static-risk, cost-aware, analyzer-aware, and adaptive ranking.

### `scheduler.rs`

Builds budget-aware fuzzing schedules. This module decides which targets receive smoke fuzzing, deep fuzzing, retries, or no budget.

### `runner.rs`

Builds zkFuzz commands, executes subprocesses, handles timeouts, and captures stdout and stderr. The current implementation starts with command building and dry-run behavior.

### `report.rs`

Generates CSV, JSON, and eventually HTML reports from structured run results.

### `db.rs`

Stores structured run data, later using SQLite or another local storage format.

### `error.rs`

Defines shared error handling types used across modules.

## Planned Pipeline

The full CLI may eventually support this workflow:

```sh
zkfDO doctor
zkfDO init
zkfDO scan ./circuits
zkfDO features ./circuits
zkfDO rank ./circuits --strategy cost-aware
zkfDO fuzz ./circuits --strategy adaptive --budget 6h --jobs 4
zkfDO report runs/latest --format html
```

The initial scaffold does not implement all of these commands yet. They describe the intended system direction.

## Run Directory Structure

```text
runs/<run_id>/
  metadata.json
  targets.json
  features.csv
  ranking.csv
  results.csv
  target-<id>/
    stdout.log
    stderr.log
    result.json
    generated_settings.json
```

`generated_settings.json` is optional and should be used only when zkfDO generates a wrapper, config, or target-specific settings file.

## Result Schema

### RunStatus

- `BugFound`
- `NoCounterexample`
- `Timeout`
- `CompileError`
- `RuntimeError`
- `ParseError`
- `Unknown`

### RunResult

- `run_id`
- `target_id`
- `target_path`
- `command`
- `status`
- `elapsed_sec`
- `exit_code`
- `stdout_path`
- `stderr_path`
- `output_dir`
- `started_at`
- `finished_at`

## CLI Command Responsibilities

### `zkfDO doctor`

Checks external tools:

- zkFuzz
- circom
- circomspect, optional
- cargo/rustc, optional

### `zkfDO init`

Creates `.zkfdo/config.toml` with default project settings.

### `zkfDO scan`

Discovers `.circom` files and target candidates.

### `zkfDO features`

Extracts static and cost features.

### `zkfDO rank`

Ranks targets according to the selected strategy.

### `zkfDO fuzz-one`

Runs or dry-runs zkFuzz on one target.

### `zkfDO fuzz`

Executes project-level scheduled fuzzing.

### `zkfDO report`

Summarizes run outputs and generates human-readable reports.
