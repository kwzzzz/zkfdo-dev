# Algorithm v0

This document defines the first documented ranking and scheduling algorithm for zkfDO. The formulas are intentionally heuristic. They should be recorded before experiments, evaluated with baselines, and not silently tuned after observing final results.

## Target Definition

### Target Definition v1

A fuzzing target is a Circom entrypoint file that contains a `main` component or can be directly passed to zkFuzz.

This is the required target definition for the first implementation.

### Future Target Definition v2

A fuzzing target may be a template-level target with an automatically generated wrapper circuit.

This is a future extension and is not required in v1.

### Future Target Definition v3

A target may eventually be represented as:

- Template name
- Parameter set
- Include path
- Generated wrapper
- Expected input signal structure

This is a longer-term extension for more precise fuzzing of parameterized Circom templates.

## Feature Groups

### Static Risk Features

- `unsafe_assign_count` for `<--`
- `unsafe_assign_rev_count` for `-->`
- `safe_assign_count` for `<==`
- `constraint_eq_count` for `===`
- `assert_count`
- `division_count`
- `modulo_count`
- `array_access_count`
- `less_than_pattern_count`
- `num2bits_pattern_count`
- `iszero_pattern_count`
- `signal_input_count`
- `signal_output_count`
- `signal_internal_count`
- `component_count`
- `template_count`
- `include_count`

### Cost Features

- `loc`
- `signal_count`
- `component_count`
- `estimated_constraint_count`
- `compile_success`
- `compile_time_sec`
- `r1cs_size_bytes`, later
- `wasm_size_bytes`, later
- `constraint_count`, later if available from circom or zkFuzz stats

### Analyzer Features

- `circomspect_warning_count`
- `circomspect_error_count`
- `circomspect_warning_types`
- Circom inspect warning count, if available

### History Features

- `previous_timeout_count`
- `previous_compile_failure_count`
- `previous_runtime_error_count`
- `previous_bug_found`
- `previous_elapsed_sec`

### Smoke Feedback Features

- `smoke_status`
- `smoke_elapsed_sec`
- `smoke_timeout`
- `smoke_bug_found`
- `smoke_runtime_error`
- `smoke_output_size`
- Possible zkFuzz progress or fitness-related signal, if available later

## Static Risk Formula v0

```text
StaticRisk(t) =
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

These weights are initial heuristic weights. They are not claimed to be theoretically optimal. The weights should be documented before experiments and later evaluated through ablation or sensitivity analysis.

## Estimated Cost Formula v0

```text
EstimatedCost(t) =
    1
  + log(1 + loc)
  + log(1 + signal_count)
  + log(1 + component_count)
```

If `constraint_count` and `compile_time_sec` are available later:

```text
EstimatedCostPlus(t) =
    1
  + log(1 + loc)
  + log(1 + signal_count)
  + log(1 + component_count)
  + log(1 + constraint_count)
  + log(1 + compile_time_sec)
```

The `1` term prevents zero-cost targets and keeps the denominator stable.

## Priority Formula v0

```text
Priority(t) = StaticRisk(t) / EstimatedCost(t)
```

Targets that look risky but are not too expensive should be fuzzed earlier.

## Analyzer-Aware Priority v1

```text
AnalyzerRisk(t) =
    circomspect_warning_weight * circomspect_warning_count
  + circomspect_error_weight   * circomspect_error_count

AnalyzerAwarePriority(t) =
  (StaticRisk(t) + AnalyzerRisk(t)) / EstimatedCost(t)
```

Analyzer features should be optional. If circomspect or a similar analyzer is unavailable, the ranker should fall back to static-risk and cost features.

## Adaptive Priority Formula

```text
FinalPriority(t) =
  (
    alpha * StaticRiskNorm(t)
  + beta  * AnalyzerRiskNorm(t)
  + gamma * SmokeFeedbackNorm(t)
  )
  / (1 + CostNorm(t))
```

Initial weights:

- `alpha = 0.5`
- `beta = 0.2`
- `gamma = 0.3`

If analyzer data is not available in early versions:

```text
FinalPriorityV0(t) =
  (
    0.7 * StaticRiskNorm(t)
  + 0.3 * SmokeFeedbackNorm(t)
  )
  / (1 + CostNorm(t))
```

Normalized scores should be computed consistently within one run, for example by min-max normalization over the discovered target set.

## Budget Split

For adaptive fuzzing, the initial default budget split is:

- Smoke fuzzing: 20% of total budget
- Deep fuzzing: 70% of total budget
- Retry or buffer: 10% of total budget

These are initial defaults and should be configurable.

## Algorithm 1: Static Target Scoring

Input:

- Target set `T`
- Extracted features `F`

Output:

- Ranked target list

```text
for each target t in T:
    features = F[t]
    static_risk = compute_static_risk(features)
    estimated_cost = compute_estimated_cost(features)
    priority = static_risk / estimated_cost
    attach score tuple to t

sort targets by priority descending
return ranked targets
```

## Algorithm 2: Budget-Aware Adaptive Scheduling

Input:

- Circom project `P`
- Total budget `B`
- Jobs `J`
- zkFuzz binary path
- Strategy

Output:

- Run directory with structured results

```text
1. Scan project and discover target candidates.
2. Extract static and cost features.
3. Compute initial priority.
4. Select top-M targets for smoke fuzzing.
5. Allocate B_smoke = 0.2 * B.
6. Run smoke fuzzing with short per-target timeout.
7. Parse smoke results.
8. Update target priorities using smoke feedback.
9. Allocate B_deep = 0.7 * B.
10. Run deep fuzzing on top-K targets.
11. Store stdout, stderr, result.json, and summary CSV.
12. Generate final report.
```
