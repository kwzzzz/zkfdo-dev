# Evaluation Plan

> **Current plan (2026-10-01):** use [evaluation_plan_2026-10-01.md](evaluation_plan_2026-10-01.md) and [plan_revision_2026-10-01.md](plan_revision_2026-10-01.md). RQ1 now centers on applicability, reviewed discoveries, and total cost; caller-context screening is a validity requirement, and ranking is secondary. The evaluation protocol is not frozen. Everything below is historical reference, including the earlier research-question numbering and strategy requirements.

> **Revised 2026-09-24:** see [plan_revision_2026-09-24.md](plan_revision_2026-09-24.md). The held-out evaluation uses budget-constrained project target sets; the required baselines are `random`, `small-first`, `path-order`, `risk-only`, and a new `cost-aware`; `analyzer-aware` and `adaptive` (RQ4) are moved to future work. Scarcity is created by one elapsed-time budget per project run in a single campaign (the separate top-K start-limit condition was cancelled on 2026-09-26); ranking quality is analyzed separately as planned placement of known defects and as execution-verified discoveries within the first k targets. Runs are per project, and results are aggregated with equal project weight and reported descriptively. The original plan below is kept for reference.

Evaluation will compare target ordering, bug discovery latency, and useful fuzzing progress under equal fuzzing budgets. The goal is to show whether zkfDO makes zkFuzz more effective and manageable on larger Circom projects than naive execution strategies.

## Research Questions

### RQ1

Does target prioritization reduce time-to-first-bug compared with random execution?

### RQ2

Does cost-aware ranking reduce wasted fuzzing time and timeout rate compared with large-first or naive execution?

### RQ3

Do analyzer warnings improve ranking quality when combined with static risk features?

### RQ4

Does smoke fuzzing feedback improve deep fuzz target selection?

### RQ5

Can zkfDO make zkFuzz execution more manageable on larger Circom projects than naive per-file execution?

## Baselines

- `random`: randomly order targets.
- `small-first`: prioritize smaller targets by lines of code or estimated cost.
- `large-first`: prioritize larger targets by lines of code or estimated cost.
- `warning-first`: prioritize targets with analyzer warnings.
- `static-risk`: prioritize targets by static risk score only.
- `cost-aware`: prioritize targets by static risk divided by estimated cost.
- `analyzer-aware`: combine static risk, analyzer warnings, and estimated cost.
- `adaptive`: use static ranking, smoke fuzzing feedback, and deep fuzzing promotion.

## Metrics

- Time to first execution-linked, reviewed original-component defect
- Unique execution-linked, reviewed original-component defects within a fixed fuzzing budget
- Project-context-confirmed unique defects, reported separately
- Bugs per hour
- Top-K hit rate
- Timeout rate
- Wasted fuzzing time
- Ranking overhead
- Compile success rate
- Smoke-to-deep promotion accuracy, later
- Reproducibility of runs

The primary comparison unit is a unique root cause that was produced by the evaluated execution and subsequently passed the original-component review. That review records three separate judgments with evidence: the input preconditions were satisfied, all constraints of the pinned original component were satisfied, and a property specified before evaluation was violated. Post-run review time is recorded outside the fuzzing budget. A project-context confirmation is a separate, stronger result and retains its own metric.

Backend `bug_found` statuses, counterexample files, static warnings, manual source review, and known-defect annotations are evidence categories rather than interchangeable defects. A completion-time curve uses the scheduler completion time of the earliest qualifying run for each root cause as an upper bound; it is not the human confirmation time. Repeated observations of one root cause across seeds, targets, strategies, or wrappers count once within an evaluation.

## Datasets

- Synthetic buggy Circom circuits
- zkbugs Circom subset
- Real-world large Circom projects
- Optionally circomlib-based examples

## Experiment Setup

For fair comparison, each strategy should use:

- Same dataset
- Same total budget
- Same per-target timeout
- Same hardware
- Same zkFuzz version or commit
- Same circom version
- Same target discovery rules

The random strategy should be repeated with multiple seeds and reported with aggregate statistics.

## Main Expected Graph

The primary graph should show cumulative reviewed original-component defects over time:

- x-axis: elapsed time
- y-axis: cumulative bugs found
- lines:
  - random
  - small-first
  - large-first
  - warning-first
  - cost-aware
  - adaptive

This graph visualizes whether a strategy produced subsequently validated defects earlier within the same fuzzing budget. Project-context-confirmed defects should be shown as a separate series or table rather than merged into the component count.

Large target sets create an allocation problem because the total execution budget may not reach every target. Expensive individual targets create a different problem because preparation or execution can consume a large share of the budget. Static ordering can address the first question and may use cost estimates, but it is not assumed to solve both. Preparation, ranking, fuzzing, and post-run validation costs must remain separately visible.

## Ablation Plan

Compare:

- adaptive full
- without analyzer features
- without smoke feedback
- without cost model
- static-risk only
- random

The ablation should help identify whether improvements come from static risk scoring, cost awareness, analyzer information, smoke feedback, or their combination.

## Reporting Requirements

Each experiment run should record:

- CLI version or git commit
- zkFuzz version or commit
- circom version
- strategy name
- total budget
- per-target timeout
- random seed, if applicable
- target list
- ranking output
- run results
- summary metrics

These fields make the results easier to reproduce and easier to use later in the graduation project report or paper.
