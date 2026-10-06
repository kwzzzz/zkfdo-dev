# zkfDO

`zkfDO` is a Rust CLI by team `kwzzzz` for constructing Circom component-analysis targets from a project entrypoint, managing zkFuzz runs, and linking results to review evidence.

Repository: <https://github.com/kwzzzz/zkfdo-dev>

The project does not reimplement zkFuzz. Its current research focus is the applicability, reviewed discoveries, and total cost of automatic decomposition compared with whole-circuit analysis. Caller-context screening is a proposed validity component; static ranking is a secondary analysis. See the [current goals and task list](docs/plan_revision_2026-10-01.md) and [evaluation design](docs/evaluation_plan_2026-10-01.md).

## Status

For paper writing, start with the [evidence index](docs/paper_evidence_index.md) and [research checkpoint](reports/research-checkpoint-2026-10-01/REPORT.md). The latest work adds normal-execution evidence on two small fixtures and fixes the reproduced offline aggregation errors (297 Rust tests passed, 22 ignored, as reported by the repair task). Preparation savings do not establish lower total processing cost. The [next normal compatibility experiment](docs/next_normal_compatibility_2026-10-01.md) is ready for handoff and has not started.

As of 2026-10-01, controlled-v1.1, controlled-v2, and controlled-v3 each contain a reviewed rediscovery of a different known original-component cause. Their protocols differ, so the findings are not a pooled performance score. The later [P2 development pilot](reports/dev-rq1-pilot-2026-09-29/README.md) gives a positive decomposition signal on inference, but its known-defect candidates were not separately reviewed; zk-email required manual component runs after preparation failed. These are development observations, not independent evidence of general superiority or confirmed project impact. A broader held-out evaluation and caller-context screening remain unfinished. The [N1 metadata audit](reports/sok-artifact-audit-2026-10-01/REPORT.md) and [N2 methodology review](reports/methodology-review-2026-10-01/REVIEW.md) are complete. miiz's [versioned N3 decision](docs/scope_decision_accepted_2026-10-01.md) adopts the corrected scope, design A preference, comparability-first stage order, and work caps. N3 is complete; the [N4-1 recording and offline aggregation paths](docs/evidence_aggregate_v1.md) are implemented and structurally tested with non-security synthetic metadata. N4 remains in progress and N4-2 has not started. The preserved draft, final-decision source, and review retain their historical text. The protocol remains unfrozen; this scope includes no repeated-fuzzing runner or new candidate-generation features or runs. Structural checks do not establish whole-candidate semantic validity or pass the full N4-1 gate.

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
- offline common evidence/review records with source hashes, explicit unknown reasons, separated review levels, time bases, and cause links
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

Stored metadata can also be imported offline with `zkfDO experiment record --request import-request.json --output new-record.json`. It writes a new hash-linked record without overwriting inputs, opening candidate payloads, generating candidates, or rerunning semantic review. Aggregate these records with `zkfDO experiment aggregate --request aggregate-request.json --output new-aggregate.json`. The [aggregation guide](docs/evidence_aggregate_v1.md) describes v1/v2 compatibility, conflict handling, completeness, scoped cause registration, and candidate-linked timing. The [original record v1 guide](docs/evidence_record_v1.md) is preserved as version history. Existing `experiment evaluate` behavior is unchanged; the new record is not a replacement evaluation score.

## Commands

- `scan`: discover Circom files in a project
- `targets`: find concrete template instantiations reachable from `component main`, generate wrappers, and validate them with Circom
- `features`: extract static features from Circom targets
- `rank`: rank fuzzing targets by risk and cost
- `schedule`: execute all discovered targets with a uniform per-target budget
- `run`: execute or dry-run zkFuzz for one target
- `report`: reserved report command (currently a placeholder)
- `experiment prepare|plan|run|evaluate`: prepare explicit targets, freeze a static order, execute it, and evaluate stored evidence
- `experiment record`: import stored value-free execution/review metadata into a new common record; no candidate generation or semantic re-review

## Development

```sh
cargo fmt
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```

## License

zkfDO's own code is licensed under the [MIT License](LICENSE). The `datasets/`, `reports/` and `experiments/` directories also contain third-party circuits and patches kept as research evidence. Those files keep their upstream licenses, and some upstream projects grant no license at all. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before reusing or publishing them.
