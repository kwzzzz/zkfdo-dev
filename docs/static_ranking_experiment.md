**Static ranking experiments: implemented workflow**

`zkfDO experiment` prepares explicit executable Circom targets, saves a static ordering, passes that ordering to the existing zkFuzz backend, and evaluates stored results. The ordered scheduler gives each target the same maximum time and stops at an overall deadline. It does not update rankings from runtime feedback, resume a target, or allocate score-dependent time slices. Existing `rank`, `schedule`, `run`, and `targets` commands retain their previous behavior; `rank` remains the lexical heuristic and `schedule` remains the file-based uniform baseline.

The implementation and synthetic integration checks establish that the saved order reaches actual subprocess calls. A bounded repeated dev3 pilot now exercises every strategy, but **confirmed real-project ranking performance and a confirmed real-project positive control have not been established.** `datasets/manifest.dev10.json` contains three distinct pinned zkbugs direct-mode targets; despite its historical name, it is not ten targets or an independent evaluation set. `manifest.dev30.json` remains an empty placeholder.

A bounded local validation used the real zkFuzz backend. Its upstream synthetic positive control produced one `bug_found` result and one preserved counterexample with seed 424242. A single path-order dev3 smoke then started all three targets in the planned order and preserved three backend candidates. Review classified one as wrapper-only, one as reachability-unknown, and left one unconfirmed. The subsequent repeated pilot did not reuse those review classifications: its evaluations contain no reviewed confirmations, so a zero confirmed-project count means that no candidate was promoted by evidence, not that every candidate was disproved. Preparation and smoke details are in [the checked-in validation summary](../experiments/dev10-preparation-2026-09-15.json).

**Bounded dev3 repeated pilot — 2026-09-15**

The ranking-separated pilot ran zkFuzz seeds 2026091501 through 2026091507 across all seven strategies: 49 strategy executions and 147 target attempts. Every cell used the same three target IDs, prepared corpus, ranking configuration, backend binary, 3-second per-target limit, and 10-second total limit. Each seed was shared by all strategies. Strategy invocation order was cyclically rotated so each strategy occupied every machine-order slot once. `random` used separately frozen ranking seeds 2026092501 through 2026092507.

All 49 planned orders matched actual process-start order. Every target started; there were no runner failures or budget skips. Across all strategies there were 119 `bug_found` backend candidates and 28 timeouts. Each strategy had exactly 17 candidates and four timeouts over its 21 target attempts because the paired seeds produced the same per-target backend statuses. The table reports candidates only; they are not confirmed project defects.

| Strategy | Order used | Mean candidates by 0.1 s | Mean candidates by 1.0 s | Mean final candidates | Median first candidate upper bound |
|---|---|---:|---:|---:|---:|
| `path-order` | Add → Xor → Rotate | 2.00 | 2.43 | 2.43 | 0.0361 s |
| `random` | Four permutations across fixed seeds | 0.86 | 1.86 | 2.43 | 0.0373 s |
| `small-first` | Add → Rotate → Xor | 1.00 | 1.86 | 2.43 | 0.0348 s |
| `legacy` | Xor → Rotate → Add | 1.00 | 1.86 | 2.43 | 0.0355 s |
| `warning-first` | Add → Rotate → Xor | 1.00 | 1.86 | 2.43 | 0.0363 s |
| `risk-only` | Add → Rotate → Xor | 1.00 | 1.86 | 2.43 | 0.0355 s |
| `risk-grouped` | Add → Rotate → Xor | 1.00 | 1.86 | 2.43 | 0.0349 s |

`path-order` completed the two consistently fast candidate-producing targets before Rotate, so its candidate curve rose earlier. This is a development-set backend-candidate observation, not evidence that path order finds confirmed defects better. Final candidate counts were identical. `risk-only` and `risk-grouped` were algorithmically indistinguishable because all structural scores were zero; `small-first` and `warning-first` also produced the same order. The small wall-clock differences among those identical orders are measurement noise, not ranking effects. Random's first-candidate mean was 0.6398 seconds even though its median was 0.0373 seconds because Rotate appeared first in three repetitions.

Every repeated-pilot evaluation has zero supplied project-scope confirmations and `null` first-confirmed-defect time. Target-level Recall@1 is 1/3 and Recall@3 is 1 for every ordering because all three development targets are manifest-reported positives. The stated confirmed-defect research question therefore remains inconclusive. The complete per-run values, raw paths, integrity checks, and metric definitions are in [the repeated pilot report](../experiments/dev3-ranking-pilot-2026-09-15.json); raw logs remain under ignored `runs/dev3-ranking-pilot-2026-09-15/`.

The per-cell command was:

```sh
target/debug/zkfDO experiment run \
  --plan PLAN.json \
  --zkfuzz-bin .external/zkFuzz/target/release/zkfuzz \
  --budget-seconds 3 \
  --total-budget-seconds 10 \
  --zkfuzz-seed PAIRED_SEED \
  --output CELL/executions > CELL/outcome.stdout.json

target/debug/zkfDO experiment evaluate \
  --plan PLAN.json \
  --outcome PERSISTED_OUTCOME.json \
  --output CELL/evaluation.json > CELL/evaluation.stdout.json

python3 scripts/summarize_static_ranking_pilot.py \
  --root runs/dev3-ranking-pilot-2026-09-15 \
  --output experiments/dev3-ranking-pilot-2026-09-15.json
```

**The seven strategies**

All nonrandom score ties use ascending stable target ID. `path-order` sorts by entrypoint path first, then ID. Missing required measurements cause an explicit error or preparation exclusion; they never become zero.

| CLI strategy | Ordering | Required ranking measurements |
|---|---|---|
| `path-order` | Ascending entrypoint path | None |
| `random` | Canonical ID order, then a seeded permutation | Explicit `--ranking-seed` |
| `small-first` | Ascending compiled constraint count | `size` |
| `legacy` | Descending existing lexical risk/cost score | Finite `legacy_score` |
| `warning-first` | Descending deduplicated selected diagnostic count | `warning_count` |
| `risk-only` | Descending sum of five 0/1 semantic features | `risk_score` |
| `risk-grouped` | Same risk ordering within structural groups, then fixed round robin across groups | `risk_score`, `complexity`, explicit group configuration |

`random` uses `splitmix64-fisher-yates-rejection-v1`: SplitMix64, rejection sampling for unbiased indices, and Fisher–Yates. Its ranking seed is independent of the zkFuzz seed. The same target IDs and ranking seed reproduce the permutation regardless of discovery order.

The five risk features are existence indicators for Circomspect rules CS0013, CS0014, CS0015, CS0017, and CS0018. Each contributes at most one point; all weights are 1, so complete risk scores range from 0 to 5. `warning-first` counts deduplicated diagnostics from those same five rules, allowing multiple distinct warnings of a rule to contribute. Neither score is a vulnerability probability or a confirmed-defect count. Attribution uses parser-validated reachable template scopes. See [the semantic adapter contract](semantic_features.md) for rule meanings, the pinned analyzer revision, completion checks, and unsupported assertion analysis.

`legacy` calls the unchanged functions in [src/ranker.rs](../src/ranker.rs): the existing weighted lexical risk divided by `1 + ln(1+LOC) + ln(1+signals) + ln(1+components) + ln(1+estimated constraints)`. In experiments its lexical input is the entire source file containing the root template, including unrelated templates in that file. It is a preserved baseline, not the semantic risk definition.

`size` is the Circom compiler's `non-linear constraints` plus `linear constraints`, requiring successful compilation and the expected R1CS artifact. `complexity` is exactly `root_ast_if_plus_while`: `num_if_then_else + num_while` from the exact root-template row of zkFuzz's `--show_stats_of_ast` CSV. It counts the root template definition, not its parameter-expanded execution, dependency bodies, or total R1CS size. Profiles record `parameter_reflected: false`; `num_statements` is also preserved. AST collection runs no fuzz search.

For `risk-grouped`, every target is assigned to one structural group; each group is ordered by the same risk score used in `risk-only`. Each round selects one remaining target from each group in configured order and skips exhausted groups. Complexity never changes a risk point or divides the score. This experiment tests grouping as a separate hypothesis.

**Preparation and a common comparison set**

A manifest specifies concrete entrypoints, their parsed root templates and parameters, project revision, prime, compile arguments, and input assumptions. Paths are resolved relative to the manifest. Preparation inspects the reachable source closure, validates manifest parameters against the parsed root, copies sources for execution, records hashes and stable IDs, compiles each target, and captures requested features. Unsupported reachable syntax, unresolved dependencies, mismatched parameters, failed required tools, and duplicate executable identities remain explicit exclusions.

| `experiment prepare` option | R1CS compilation | Root AST statistics | Semantic diagnostics | Legacy lexical score |
|---|---|---|---|---|
| Omit `--strategy` | Yes | Yes | Yes | Yes |
| `--strategy path-order`, `random`, or `small-first` | Yes | No | No | No |
| `--strategy legacy` | Yes | No | No | Yes |
| `--strategy warning-first` or `risk-only` | Yes | No | Yes | No |
| `--strategy risk-grouped` | Yes | Yes | Yes | No |

For a comparison that isolates ordering, prepare once **without `--strategy`** and create all plans from the same prepared JSON. Only targets complete for all collected features are eligible. Keep the same target IDs, backend/settings, fuzzing seed, per-target budget, and overall budget across compared strategies; record random ranking seeds separately.

Strategy-specific preparation measures the features that strategy requests and records its own cost, but can produce a different eligible set. Plans label this `strategy-specific-preparation` and include a warning. The CLI does not automatically intersect separately prepared sets or make them a valid seven-strategy comparison. The implemented execution mode is `ranking-separated`; a timed end-to-end comparison with an explicitly fixed common eligible set remains separate experimental work.

Preparation stores the supported Circomspect package/revision contract. Its default binary is `.external/circomspect/target/release/circomspect`. See the semantic document for the local pinned build. `--circom-bin`, `--zkfuzz-bin`, and `--circomspect-bin` select tool paths; `--tool-timeout-seconds` defaults to 60 and applies to each tool invocation. An unavailable analyzer is harmless only when semantic analysis was not requested.

**Frozen structural groups are required**

The checked-in [static configuration](../configs/static-ranking.json) currently contains:

```json
{
  "schema_version": 1,
  "complexity_groups": {
    "metric": "root_ast_if_plus_while",
    "upper_bounds": [0],
    "group_order": [0, 1],
    "provenance": "Frozen from the three-target development profile before fuzzing; see the checked-in config for the exact record."
  }
}
```

All three current development targets measured structural complexity zero. The checked-in boundary therefore places them in the same group and reserves the second group for positive complexity. `risk-grouped` is executable, but on this corpus its order is expected to match `risk-only`; the tiny profile does not validate the boundary or show a grouping benefit. Do not retune it from held-out defect-discovery outcomes.

The non-null `complexity_groups` object has exactly these fields:

| Field | Required value |
|---|---|
| `metric` | `"root_ast_if_plus_while"` |
| `upper_bounds` | Strictly increasing inclusive integer upper bounds; one overflow group follows the final bound |
| `group_order` | A permutation of all group indices, from 0 through `upper_bounds.length` |
| `provenance` | Nonempty description of the development measurements and boundary decision |

An empty bounds list gives one group, which adds no structural diversification. Configuration and its hash are recorded in the plan.

**Reproducible command example**

Run the following from the repository root after making `circom` and `zkfuzz` available. This creates a synthetic fully constrained example solely to exercise the workflow. It is neither a corpus entry with a known defect nor a positive control.

```sh
cargo build --offline --bin zkfDO
mkdir -p runs/static-demo
cat > runs/static-demo/main.circom <<'CIRCOM'
pragma circom 2.1.0;
template Demo() {
    signal input x;
    signal output y;
    y <== x;
}
component main = Demo();
CIRCOM
cat > runs/static-demo/manifest.json <<'JSON'
{
  "schema_version": 1,
  "name": "static-demo",
  "description": "Synthetic workflow example; no known defect claim.",
  "targets": [{
    "label": "demo",
    "project": "static-demo",
    "revision": "documentation-fixture-v1",
    "project_root": ".",
    "entrypoint": "main.circom",
    "template_name": "Demo",
    "concrete_parameters": [],
    "prime": "bn128",
    "compile_args": [],
    "mode": "original",
    "input_assumptions": "One arbitrary field input x; output constrained to x.",
    "known_defects": []
  }]
}
JSON
target/debug/zkfDO experiment prepare \
  --manifest runs/static-demo/manifest.json \
  --strategy path-order \
  --output runs/static-demo/prepared \
  > runs/static-demo/prepared.stdout.json

target/debug/zkfDO experiment plan \
  --prepared runs/static-demo/prepared.stdout.json \
  --strategy path-order \
  --output runs/static-demo/path-order.plan.json
```

`prepare` and `plan` perform no fuzz search. Every command prints complete JSON; the persisted report's `report_path` or the saved complete stdout can be used as input to the next phase. Preparation creates a unique subdirectory, so avoid guessing its UUID. Planning records and prints the order without executing it.

The following command **does execute zkFuzz**, then evaluates its stored outcome without claiming any reviewed defects:

```sh
target/debug/zkfDO experiment run \
  --plan runs/static-demo/path-order.plan.json \
  --zkfuzz-bin zkfuzz \
  --budget-seconds 10 \
  --total-budget-seconds 10 \
  --zkfuzz-seed 123 \
  --output runs/static-demo/executions \
  > runs/static-demo/outcome.stdout.json

target/debug/zkfDO experiment evaluate \
  --plan runs/static-demo/path-order.plan.json \
  --outcome runs/static-demo/outcome.stdout.json \
  --output runs/static-demo/evaluation.json
```

For common preparation, omit `--strategy` and use a fresh output location. For a random plan add `--strategy random --ranking-seed 42`. For a grouped plan add `--strategy risk-grouped --config PATH_TO_YOUR_FROZEN_CONFIG`; that file must first be created from development profiling. These options replace the example plan's `--strategy path-order`.

The runner explicitly invokes zkFuzz GA search with the manifest prime and `--save_output`. Currently only `-l` library-path compile arguments can be reproduced in backend execution; unsupported compiler settings are rejected. Manifest `mode` must be `original` for a project entrypoint or `direct` for an isolated wrapper. It declares entrypoint provenance and contributes to target identity; it does not select the fixed GA search mode. An optional `--mutation-settings FILE` is copied and hashed. `--zkfuzz-seed` writes or overrides its `seed` field in the frozen settings; use a nonzero seed. Without a nonzero effective seed, the report marks randomness as uncontrolled. Source/snapshot hashes, ranking inputs, ordered IDs, backend hash, settings, commands, and raw output remain available for review. These records support reproduction; they do not make a wall-clock-limited backend deterministic.

**Timing, failures, and stored evidence**

| Measurement | Boundary |
|---|---|
| Preparation and planning seconds | Their respective phases, recorded separately from fuzzing |
| `total_budget_seconds` | Starts inside the ordered scheduler after plan/source validation and command setup; caps backend process attempts and later starts, while required result persistence can finish just after it |
| Per-target execution limit | Minimum of the fixed per-target budget and precise remaining scheduler duration; includes runner file setup and process startup |
| `RunResult.wall_time_seconds` | Runner entry through process completion/timeout handling, before log parsing and final result persistence |
| `process_start_offset_seconds` | Successful spawn-call entry relative to scheduler start; not the exact OS exec timestamp; absent if no process was started |
| `completion_offset_seconds` | Scheduler offset after the runner returns, including result persistence |
| Scheduler `elapsed_seconds` | Through all runner returns, excluding final summary serialization |
| Outcome `elapsed_seconds` | Wider execution phase, including validation and candidate preservation, before outcome serialization |

After the deadline, remaining targets are `not_started`/`total_budget_exhausted`. A process can receive a fractional final time slice. Timeout cleanup and persistence can finish after the deadline; it is not a promise of exact end-to-end CLI return time. On Unix, timeout cleanup kills the child's process group and reaps the child. Process failures and runner infrastructure errors are recorded separately and do not stop later targets while budget remains. A nonzero exit cannot become `bug_found` or `no_counterexample` merely by printing a matching line.

An execution writes `outcome.json`, frozen mutation settings when used, a nested ordered scheduler `summary.json`, per-run `result.json`/`stdout.log`/`stderr.log`, and newly observed counterexample candidates when available. Use the recorded paths. `outcome.scheduler.planned_target_ids` and each run's ID/index/timing expose both the plan and actual starts. Preparation and AST/analyzer captures never become fuzzing bug results.

The evaluation's `separate_phase_sum_seconds` sums preparation, planning, scheduler, and evaluation measurements. It omits parts of the wider execution phase and final serialization; it is not a measured end-to-end duration.

**Reviewed confirmations and evaluation**

`bug_found` means the backend reported a candidate. Static warnings, compiler failures, crashes, and saved counterexamples are not automatically confirmed defects. Confirmation input schema 2 can record an original-component review as follows, replacing all illustrative IDs, notes, and paths with actual review data:

```json
{
  "schema_version": 2,
  "confirmations": [{
    "run_id": "ACTUAL_RUN_ID",
    "target_id": "sha256:ACTUAL_TARGET_ID",
    "root_cause_id": "PROJECT/REVISION/REVIEWED_ROOT_CAUSE",
    "scope": "original-component",
    "evidence_origin": "backend-execution",
    "original_component_review": {
      "input_preconditions": {
        "verdict": "satisfied",
        "evidence": ["evidence/component-review.md"],
        "note": "State the pinned source of each precondition and how the input meets it."
      },
      "fixed_original_constraints": {
        "verdict": "satisfied",
        "evidence": ["evidence/component-review.md"],
        "note": "State the pinned original revision and whole-component constraint check."
      },
      "specified_property_violation": {
        "verdict": "satisfied",
        "evidence": ["evidence/component-review.md"],
        "note": "State the property fixed before evaluation and the observed violation."
      }
    },
    "evidence": ["evidence/component-review.md"],
    "note": "Reviewer summary; this example is a schema illustration, not a defect record."
  }]
}
```

Pass it with `experiment evaluate --confirmations FILE`, alongside the same plan/outcome/output arguments. Evidence paths are absolute or relative to the confirmation file and must exist. Every record must refer to a matching run/target from the same plan. An execution discovery additionally requires `evidence_origin: "backend-execution"` and backend status `bug_found`. Other origins are `static-warning`, `manual-source-review`, and `known-defect-annotation`; they remain visible in `evidence_origin_counts` but never enter an execution-discovery curve.

Allowed scopes are `project`, `original-component`, `wrapper-only`, and `reachability-unknown`. `original-component` requires all three structured criteria to be present. A criterion with `not-satisfied` or `unknown` preserves the review record but does not qualify it as a valid component defect. `project` retains the existing project metric; it also enters the new component metric only when the same complete component review is present and satisfied. `wrapper-only` and `reachability-unknown` never receive that promotion. Repeated qualifying records with the same root-cause ID count once, using the earliest linked run completion.

The evaluator verifies enum values, run/target linkage, backend status for execution-origin records, notes, and evidence-file existence. These checks structure the review; they do not establish that a report's scientific claims are true. Human review completion time and its cost remain outside the fuzzing budget and are not represented by the run-completion curve.

Confirmation schema 1 remains accepted. Its omitted `evidence_origin` has the legacy meaning `backend-execution`, and a schema-1 `project` record continues to contribute to the existing project metric after the same `bug_found` linkage validation. It does not enter the original-component metric because it lacks the three new review judgments. Evaluation output is schema 2: all old project fields keep their names and meanings, while these fields are added:

```json
{
  "schema_version": 2,
  "confirmed_original_component_defect_count": 0,
  "confirmed_original_component_root_causes": [],
  "original_component_detection_curve": [],
  "first_confirmed_original_component_defect_observed_by_seconds": null,
  "evidence_origin_counts": {}
}
```

A manifest's `known_defects` annotation instead records `root_cause_id`, `location`, `source_url`, `reported`, `local_reproduction`, `tcct_status`, `reachability`, and optional `evidence`. It is provenance, not a finding from this execution. `known_target_ranks` and Recall@K use targets annotated with `reported: true`; the denominator is known targets, not all defects or presumed safe negatives. With no known targets, recall is `null`.

Evaluation separates status counts, backend candidates, preserved artifacts, reviewed evidence records, valid original-component root causes, wrapper-only findings, and project-context root causes. Both curves use the earliest completing qualifying run per root cause. `first_confirmed_defect_observed_by_seconds` remains the legacy project completion-time upper bound. `first_confirmed_original_component_defect_observed_by_seconds` is the separate component-level upper bound and stays `null` when no qualifying execution-linked review exists. A controlled regression set and a held-out multi-project corpus with reviewed positives remain required before drawing ranking-performance conclusions.

**Verification commands**

```sh
cargo test --offline --test static_rank_test --test ordered_scheduler_test
cargo test --offline --test experiment_cli_test --test cli_smoke_test
cargo test --offline --test corpus_test --test structure_test --test semantic_test
```

The CLI integration tests use synthetic sources and fake tools to check saved order, actual subprocess call order, continued execution after failure, explicit budgets, and persisted evaluations. Separate ignored tests can invoke installed real frontends/analyzer; consult their test names and [semantic verification notes](semantic_features.md). Passing them establishes adapter/workflow behavior, not comparative fuzzing effectiveness.
