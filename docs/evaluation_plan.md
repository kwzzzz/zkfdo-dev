# Evaluation Plan

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

- Time-to-first-bug
- Bugs found within fixed budget
- Bugs per hour
- Top-K hit rate
- Timeout rate
- Wasted fuzzing time
- Ranking overhead
- Compile success rate
- Smoke-to-deep promotion accuracy, later
- Reproducibility of runs

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

The primary graph should show cumulative bugs found over time:

- x-axis: elapsed time
- y-axis: cumulative bugs found
- lines:
  - random
  - small-first
  - large-first
  - warning-first
  - cost-aware
  - adaptive

This graph directly visualizes whether a strategy finds bugs earlier within the same budget.

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
