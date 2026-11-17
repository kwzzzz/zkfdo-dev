# zkFDO

zkFDO is a Rust tool for finding bugs in Circom circuits. It cuts a large circuit into fragments and runs zkFuzz on each one. Each candidate it finds is then checked against the original circuit, so the check uses the full context and not just the fragment.

Repository: <https://github.com/kwzzzz/zkfdo-dev>

This branch has the source code only: the judging engine, the fragment preparation code, the command-line entry point, and the pipeline driver. Reports, experiment records, evaluation data, and documentation are left out.

## How it works

1. **Fragment fuzzing (S).** The circuit is split into components. zkFuzz runs on each fragment within a time budget.
2. **Judging in context (J).** Each candidate from S is checked against the constraints of the original circuit. The judge gives one verdict and records the reason. See [Terms](#terms).
3. **Site probe (v2.8).** For candidates the judge could not decide, the probe changes one hint at a time on a fixed input. It looks for a second witness with the same input and a different top-level output. External Rust and snarkjs checkers verify each pair against the original constraints before it is reported. Probe results are stored separately and do not change the judge's verdicts.

## Terms

- **Violation**: the judge found a witness pair that satisfies the original constraints and gives different outputs.
- **Compatible**: no violation was seen for this candidate in context.
- **Excluded**: the candidate was ruled out in context. The reason is recorded, for example a constant input mismatch.
- **Unknown**: the judge could not decide. The reason is recorded, for example the budget ran out. Unknown does not mean safe.
- **Validated counterexample**: a probe pair that passed the external checks. It is a witness pair for the circuit, not a verdict on the original candidate.
- **Output identical**: the probe saw no change in output for the values it tried. This does not show the hint is safe.

## Status

This branch includes:

- The `zkFDO` command-line entry point (`src/main.rs`)
- The judging engine, versions v2.5 to v2.8 (`src/candidate_review/lifting/`, `src/bin/zkfdo-j-v27.rs`, `src/bin/zkfdo-j-v28.rs`)
- The v2.8 site probe (`site_signal_probe.rs`, `site_probe_identity.rs`, `site_probe_workspace.rs`)
- Target preparation and instance capture (`src/targets.rs`, `src/instance_capture.rs`)
- The staged pipeline driver, its dry-run mode, and its unit tests (`scripts/run_sj_pipeline_v1.py`)

Notes:

- The staged pipeline has only been run in dry-run mode so far.
- Timings recorded during development are functional checks. They are not performance results.

This is a research prototype. Interfaces and output formats may change.

## Repository layout

```
Cargo.toml, Cargo.lock       Rust package
src/main.rs                  zkFDO command-line entry point
src/candidate_review/        candidate review and judging
  lifting/                   judging engine (v2.5 to v2.8), site probe, repair and solver
src/bin/                     judge executables and relation verifier
src/targets.rs               target preparation and Circom discovery
src/instance_capture.rs      reader for compiler instance captures
scripts/run_sj_pipeline_v1.py        staged S-to-J pipeline driver
scripts/run_sj_pipeline_v1_test.py   unit tests for the driver
LICENSE                      MIT
```

## Dependencies

These tools are not included. Install them separately:

- Rust toolchain
- circom 2.x
- snarkjs 0.7.x
- Node.js
- z3
- zkFuzz (an upstream project; zkFDO does not reimplement it)

The pipeline reads a tools manifest with the path and SHA-256 of each tool:

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

## Quick start

```sh
cargo build --release
cargo run --bin zkFDO -- --help
```

To check a pipeline plan without starting the engine, run a dry run:

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

`--corpus-layer` is required. It takes `development`, `regression`, or `hunt`. Evaluation runs are outside this pipeline.

## Output of a pipeline run

Each run writes to its own output directory:

- `identity.json`: the identity of the run (inputs, tool hashes, settings)
- `ledger.json`: stage status and budgets. `immutable-ledger/` keeps the allocation history.
- `stage-records/`: one folder per stage, with attempt receipts
- `work/`: the source snapshot and intermediate files

A finished output directory is never overwritten. An interrupted run can resume in the same directory only while its status is partial. Otherwise, start a new directory.

## Testing

```sh
cargo test
python3 -B -m unittest scripts/run_sj_pipeline_v1_test.py
```

The Python tests use fixtures and stubs. They do not run circom, zkFuzz, or the judge.

## Limits

- zkFDO is not a complete Circom analyzer. Unsupported constructs are reported as unsupported and are not analyzed.
- A candidate with verdict unknown, excluded, or output identical is not proof that the circuit is safe.
- Budgets apply per run. A result that is unknown because the budget ran out says nothing about the circuit.
- The pipeline needs external tools whose hashes are known. It does not download them.

## Reporting findings

No finding has been reported from this code yet. Any finding will be checked against the original circuit and its current version before it is described publicly. For a vulnerability in a third-party circuit, contact the maintainers privately before posting any details.

## License

MIT. See `LICENSE`.
