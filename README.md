# zkFDO

`zkFDO` is a Rust tool by team `kwzzzz` for finding bugs in Circom circuits. It splits a large circuit into fragments, runs zkFuzz on each fragment, and then judges each resulting candidate against the original circuit, so that a finding is checked in its full context rather than in isolation.

Repository: <https://github.com/kwzzzz/zkfdo-dev>

This branch contains the source only: the judging engine, the fragment preparation code, the command-line entry point, and the staged pipeline driver. Reports, experiment records, evaluation corpora, and documentation are not included.

## How it works

1. **Fragment fuzzing (S).** A large circuit is cut into components. zkFuzz runs on each fragment with a per-target time budget.
2. **Judging in context (J).** Each candidate from S is re-checked against the original circuit's constraints. The judge returns one of: violation, compatible, excluded, or unknown, with the reason recorded.
3. **Site probe (v2.8).** For unresolved candidates, the probe changes one hint at a time on a given input and looks for a second witness with the same full input and a different top-level output. Every such pair is checked again against the original constraints by external Rust and snarkjs checkers before it is reported. Probe results are kept apart from the judge's verdicts and never overwrite them.

## Status

Implemented in this branch:

- `zkFDO` command-line entry point (`src/main.rs`)
- Judging engine, versions v2.5 through v2.8 (`src/candidate_review/lifting/`, `src/bin/zkfdo-j-v27.rs`, `src/bin/zkfdo-j-v28.rs`)
- Site probe for v2.8 (`site_signal_probe.rs`, `site_probe_identity.rs`, `site_probe_workspace.rs`)
- Target preparation and instance capture (`src/targets.rs`, `src/instance_capture.rs`)
- Staged pipeline driver, dry-run mode, and its unit tests (`scripts/run_sj_pipeline_v1.py`)

Not yet verified:

- The branch has not been built or tested as a whole since it was assembled. Build errors are possible.
- The staged pipeline has been checked in dry-run mode only. Its end-to-end run is not yet verified.
- Timings recorded during development are functional checks, not performance results.

This is a research prototype. Interfaces and output formats may change.

## Dependencies

The following tools are not included and must be installed separately:

- Rust toolchain
- circom 2.x
- snarkjs 0.7.x
- Node.js
- z3
- zkFuzz (upstream project)

The pipeline reads a tools manifest that gives the path and SHA-256 of each tool:

```json
{
  "schema": "zkfdo-tools-v1",
  "platform": "darwin",
  "architecture": "arm64",
  "status": "ready",
  "tools": {
    "circom": {"path": "/absolute/path/circom", "sha256": "<64 hex characters>", "version": "2.2.3", "role": "compiler", "optional": false}
  }
}
```

## Quick Start

```sh
cargo build --release
cargo run --bin zkFDO -- --help
```

Dry-run of the staged pipeline (builds the plan only; the engine is not started):

```sh
python3 scripts/run_sj_pipeline_v1.py \
  --entrypoint <main.circom> \
  --base-input <input.json> \
  --project-root <project root> \
  --library-path <library path> \
  --tools-manifest <tools.json> \
  --out <new output directory> \
  --corpus-layer development \
  --dry-run
```

Each run writes to a new output directory. A directory is reused only to resume an interrupted run.

## License

MIT. See `LICENSE`.
