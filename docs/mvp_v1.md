# Implementation Milestone 1

This document defines the first implementation milestone for zkfDO. It does not replace the full graduation-project goal described in `problem_statement.md`, `system_design.md`, and `evaluation_plan.md`.

The full project goal remains project-level assistance around zkFuzz: deciding which Circom targets should be fuzzed, in what order, for how long, and how results should be collected and evaluated under a limited budget.

## Milestone Goal

Milestone 1 builds the static front half of the project-level pipeline: discover Circom targets, extract cheap target features, and produce an initial ranking that later scheduling and zkFuzz execution can consume.

## Milestone Scope

This milestone pipeline is:

1. Scan a project directory for `.circom` files.
2. Extract lexical static features from each file.
3. Compute a heuristic risk score and cost score.
4. Sort targets by `rank_score = risk_score / cost_score`.
5. Print structured JSON from the CLI for reproducible experiments.

## Non-Scope For This Milestone

- Do not reimplement zkFuzz.
- Do not implement a new TCCT fuzzer.
- Do not implement program mutation, input mutation, evolutionary search, Row-Vortex commitments, Violation IOPs, or LLM mutation-template oracles.
- Do not build a web UI.
- Do not require circom, circomspect, or zkFuzz to be installed for ranking.
- Do not generate wrapper circuits for parameterized templates yet.
- Do not claim that static features prove a bug exists.
- Do not tune weights after seeing final experiment results without documenting the change.

## Relationship To zkFuzz And zkCraft

zkFuzz is the fuzzing engine and research baseline. It defines TCCT and detects trace-constraint inconsistencies through program/input mutation and guided search.

zkCraft is adjacent work at the fuzzing-engine layer. It improves TCCT-powered fuzzing using ZK-native localization, proof-bearing search, and LLM-guided mutation templates.

zkfDO should avoid competing at that layer. Its intended contribution is the project-level decision layer around existing fuzzers:

- target discovery across large Circom repositories
- static and cost feature extraction for candidate targets
- initial target prioritization before expensive fuzzing
- budget-aware smoke and deep scheduling
- adaptive re-ranking from smoke-run feedback
- structured result collection for reproducible evaluation
- baseline comparison against random, small-first, large-first, warning-first, and fuzzer-default execution

## Feature Set

The first implementation uses lexical features that are cheap to compute and easy to explain:

- Lines of code after comment removal
- Signal declarations
- Input, output, and internal signal declarations
- Template declarations
- Component declarations
- Include statements
- Constraint-like operators: `<==`, `==>`, `===`
- Unsafe assignment operators: `<--`, `-->`
- Assertions
- Division and modulo operators
- Array access syntax
- Common Circom patterns such as `LessThan`, `Num2Bits`, and `IsZero`

These features are intentionally approximate. They are useful for ranking and experiment planning, not for formal Circom parsing.

## Scoring Formula

```text
risk_score =
    20 * unsafe_assign_count
  + 20 * unsafe_assign_rev_count
  + 15 * assert_count
  + 8  * division_count
  + 6  * modulo_count
  + 5  * array_access_count
  + 5  * less_than_pattern_count
  + 5  * num2bits_pattern_count
  + 5  * iszero_pattern_count
  + 3  * signal_input_count
```

```text
cost_score =
    1
  + ln(1 + loc)
  + ln(1 + signal_count)
  + ln(1 + component_count)
  + ln(1 + constraint_count_estimate)
```

```text
rank_score = risk_score / cost_score
```

The constant `1` prevents division by zero and keeps tiny files stable.

## Acceptance Criteria

- `zkfDO scan --project <dir>` prints discovered Circom files as JSON.
- `zkfDO features --project <dir>` prints static feature rows as JSON.
- `zkfDO rank --project <dir>` prints targets sorted by descending rank score.
- Unit or integration tests cover scanner, feature extraction, ranking, and CLI smoke behavior.
- `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, and `cargo test` pass.

## Post-Milestone Progress

Completed after this milestone:

1. Real zkFuzz subprocess execution with timeout handling.
2. Uniform per-target budget scheduling and experiment summaries.
3. Semantic discovery of concrete, reachable template instantiations for a supported Circom subset.
4. Standalone wrapper generation and optional `circom --inspect` validation.

The current scheduler still consumes file-level scan results. The next integration milestone is to feed successfully validated wrappers into runner/scheduler experiments before comparing random, small-first, static-rank, and adaptive allocation strategies.
