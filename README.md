# zkFDO

`zkFDO` is a Rust tool by team `kwzzzz` for finding bugs in Circom circuits. It splits a large circuit into fragments, runs zkFuzz on each fragment, and then judges each resulting candidate against the original circuit, so that a finding is checked in its full context rather than in isolation.

Repository: <https://github.com/kwzzzz/zkfdo-dev>

This branch contains the source only: the judging engine, the fragment preparation code, the command-line entry point, and the staged pipeline driver. Reports, experiment records, evaluation corpora, and documentation are not included.

## How it works

1. **Fragment fuzzing (S).** A large circuit is cut into components. zkFuzz runs on each fragment with a per-target time budget.
2. **Judging in context (J).** Each candidate from S is re-checked against the original circuit's constraints. The judge returns one verdict, with the reason recorded (see [Terms](#terms)).
3. **Site probe (v2.8).** For unresolved candidates, the probe changes one hint at a time on a given input and looks for a second witness with the same full input and a different top-level output. Every such pair is checked again against the original constraints by external Rust and snarkjs checkers before it is reported. Probe results are kept apart from the judge's verdicts and never overwrite them.

## Terms

- **Violation**: the judge found a witness pair that satisfies the original constraints and gives different outputs.
- **Compatible**: no violation was observed for this candidate in context.
- **Excluded**: the candidate was ruled out in context, with the reason recorded (for example, a constant input mismatch).
- **Unknown**: the judge could not decide, with the reason recorded (for example, budget exhausted). Unknown is not a safe result.
- **Validated counterexample**: a probe pair that passed the external checks. It is a circuit-level witness pair, not a verdict on the original candidate.
- **Output identical**: the probe observed no output change for the values it tried. It is not a proof that the hint is safe.

## Status

Implemented in this branch:

- `zkFDO` command-line entry point (`src/main.rs`)
- Judging engine, versions v2.5 through v2.8 (`src/candidate_review/lifting/`, `src/bin/zkfdo-j-v27.rs`, `src/bin/zkfdo-j-v28.rs`)
- Site probe for v2.8 (`site_signal_probe.rs`, `site_probe_identity.rs`, `site_probe_workspace.rs`)
- Target preparation and instance capture (`src/targets.rs`, `src/instance_capture.rs`)
- Staged pipeline driver, dry-run mode, and its unit tests (`scripts/run_sj_pipeline_v1.py`)

- The staged pipeline has been run in dry-run mode so far.
- Timings recorded during development are functional checks, not performance results.

This is a research prototype. Interfaces and output formats may change.

## Repository layout

```
Cargo.toml, Cargo.lock       Rust package
src/main.rs                  zkFDO command-line entry point
src/candidate_review/        candidate review and judging
  lifting/                   judging engine (v2.5 to v2.8), site probe, repair and solver
src/bin/                     judge executables and relation verifier
src/targets.rs               target preparation and Circom discovery
src/instance_capture.rs      compiler instance capture reader
scripts/run_sj_pipeline_v1.py        staged S-to-J pipeline driver
scripts/run_sj_pipeline_v1_test.py   unit tests for the driver
LICENSE                      MIT
```

## Dependencies

The following tools are not included and must be installed separately:

- Rust toolchain
- circom 2.x
- snarkjs 0.7.x
- Node.js
- z3
- zkFuzz (upstream project; this tool does not reimplement it)

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

Dry-run of the staged pipeline. It records the plan only; the engine is not started:

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

`--corpus-layer` is required and takes `development`, `regression`, or `hunt`. The evaluation layer is outside this pipeline.

## Output of a pipeline run

Each run writes to its own output directory:

- `identity.json`: the identity of the run (inputs, tool hashes, settings)
- `ledger.json`: stage status and budgets; `immutable-ledger/` keeps the history of allocations
- `stage-records/`: one folder per stage, with attempt receipts
- `work/`: the source snapshot and intermediate files

A finished output directory is never overwritten. An interrupted run can resume in the same directory only while its status is partial. Otherwise start a new directory.

## Testing

```sh
cargo test
python3 -B -m unittest scripts/run_sj_pipeline_v1_test.py
```

The Python tests use fixtures and stubs; they do not run circom, zkFuzz, or the judge.

## Scope and limitations

- Not a complete Circom analyzer. Unsupported constructs are reported as unsupported, not analyzed.
- A candidate with verdict unknown, excluded, or output identical is not a proof of safety.
- Budgets are per run. A result that is unknown because of a budget is not evidence about the circuit.
- The pipeline needs external tools with known hashes. It does not download them.

## Reporting findings

No finding has been reported from this code yet. Any finding will be checked against the original circuit and its current version before it is described publicly. Please contact the maintainers privately before posting details of a vulnerability in a third-party circuit.

## License

MIT. See `LICENSE`.
