# zkfDO

`zkfDO` is a Rust CLI by team `kwzzzz` for ranking Circom fuzzing targets and scheduling zkFuzz runs under a limited time budget.

Repository: <https://github.com/kwzzzz/zkfdo-dev>

The project does not reimplement zkFuzz. It scans Circom projects, extracts target features, ranks targets by estimated vulnerability risk and execution cost, and invokes an existing zkFuzz binary as a budget-limited subprocess.

## Status

As of 2026-09-23, the explicit prepare → plan → run → evaluate pipeline has rediscovered and reviewed one distinct known original-component cause in each of the controlled-v1.1, controlled-v2, and controlled-v3 development campaigns. These campaigns have different targets and protocols, so their findings are not a pooled performance score. No project-caller defect is confirmed. Controlled-v3's static risk scores tied within both vulnerable/fixed pairs and its fixed variants were ordered first; general ranking superiority is unproven. A non-zkbugs large-project study and a broader held-out evaluation remain open. See the [research goal](docs/problem_statement.md), [evaluation plan](docs/evaluation_plan.md), and [controlled-v3 development pilot](reports/controlled-v3-pilot-2026-09-23/REPORT.md).

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
- explicit corpus preparation, eight static ranking strategies, saved plans, and execution in ranked order under a total budget
- evaluation JSON separating backend candidates, reviewed original-component defects, and project-context defects
- repeated-pilot validation and aggregation over paired backend seeds
- placeholder modules for reports and database storage

Not implemented yet:

- complete Circom syntax/semantic analysis
- automatic discovery-to-experiment corpus curation (the original `schedule` command remains file-based)
- adaptive scheduling and runtime re-ranking
- SQLite persistence
- general CSV/HTML report generation and implementation of the legacy `report` command
- a sufficiently broad held-out confirmed-defect comparison and project-caller-confirmed positive control

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

New corpus manifests can use schema 2 to declare an `input_contract` for each target. `{"kind":"field_only"}` declares that the evaluated property has no narrower input domain. A bounded property uses `{"kind":"bounded","enforcement":"unverified"}` until the executable target has been reviewed; this target remains in the preparation report but is excluded from plans. `reviewed_in_executable` additionally requires an evidence file SHA-256, the reviewed entrypoint SHA-256, and a SHA-256 of the serialized prepared source fingerprints. Preparation, planning, and execution recheck those hashes. This binds a human review to source bytes; it does not prove that the review's range-constraint conclusion is correct. Existing schema 1 manifests and the frozen controlled-v1 inputs retain their prior identities and behavior.

`experiment evaluate --confirmations FILE` accepts legacy confirmation schema 1 and structured schema 2. Schema 2 can record the review of input preconditions, fixed-original constraints, and a pre-specified property violation. Only records whose evidence origin is `backend-execution`, whose run and target match the plan, and whose backend status is `bug_found` can contribute to execution-discovery metrics. The evaluator checks this structure and the existence of evidence files; it does not prove the reviewer's conclusions.

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
