# System Design

## Technical Identity

zkfDO is a Rust-based helper CLI for zkFuzz. It uses zkFuzz as an external binary and does not replace zkFuzz. The project improves the project-level fuzzing workflow around zkFuzz by adding target discovery, prioritization, budget-aware scheduling, structured result collection, and reporting.

## Module Architecture

### `cli.rs`

Defines the command-line interface and subcommand parsing. This module should stay focused on argument definitions and dispatching work to other modules.

### `config.rs`

Defines project config, zkFuzz config, and fuzzing profile config structures. Later versions should load `.zkfdo/config.toml` and named profiles such as fast, balanced, and deep.

### `scanner.rs`

Recursively discovers `.circom` files. It deliberately remains a filesystem scanner and does not claim that every file is a runnable fuzz target.

### `targets.rs`

Implements the semantic target-discovery MVP. It finds a unique top-level `component main`, follows project-local includes, evaluates a supported subset of compile-time parameter expressions, walks reachable scalar component instantiations, generates standalone wrappers, and optionally validates each wrapper with `circom --inspect`.

Unsupported syntax is stored explicitly in the discovery report instead of producing guessed targets. Component arrays, instantiation in control flow, anonymous components, dynamic/unknown parameter expressions, and include dependencies outside the scanned project are not expanded in this MVP.

### `features.rs`

Extracts static and cost features from Circom targets. Early features can be lexical and file-level; later features may use compiler outputs or analyzer outputs.

### `ranker.rs`

Implements ranking strategies and priority scoring, including static-risk, cost-aware, analyzer-aware, and adaptive ranking.

### `scheduler.rs`

Builds and executes budget-aware fuzzing schedules. The current baseline assigns every discovered target the same per-target budget and stores an experiment summary. Later versions will decide which targets receive smoke fuzzing, deep fuzzing, retries, or no budget.

### `runner.rs`

Builds zkFuzz commands, executes subprocesses, enforces per-target timeouts, captures stdout and stderr, and stores structured JSON results. Later versions may add process-group termination and version-specific output adapters.

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
runs/<single-run-id>/
  result.json
  stdout.log
  stderr.log

runs/<experiment-id>/
  summary.json
  runs/<target-run-id>/
    result.json
    stdout.log
    stderr.log
```

## Result Schema

### RunStatus

- `BugFound`
- `NoCounterexample`
- `Timeout`
- `CompileError`
- `RuntimeError`
- `ParseError`
- `SpawnError`
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

Discovers `.circom` files.

### `zkfDO targets`

Discovers concrete template-instantiation candidates reachable from a unique project entrypoint, generates isolated wrappers, and records compile-validation results.

### `zkfDO features`

Extracts static and cost features.

### `zkfDO rank`

Ranks targets according to the selected strategy.

### `zkfDO run`

Runs or dry-runs zkFuzz on one target.

### `zkfDO schedule`

Executes every discovered project target with a uniform per-target budget and stores an experiment summary.

The current scheduler still consumes the file scanner output. Connecting validated semantic wrappers to scheduling is intentionally a later step.

### `zkfDO report`

Summarizes run outputs and generates human-readable reports.
