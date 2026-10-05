# Problem Statement

Current direction: 2026-10-01. The [current plan](plan_revision_2026-10-01.md) assigns work; the [evaluation design](evaluation_plan_2026-10-01.md) defines the proposed measurements. These documents do not replace any frozen protocol or historical verdict.

miiz's [versioned N3 decision](scope_decision_accepted_2026-10-01.md) adopts the corrected scope, claims, freeze procedure, design A preference, stage order, and work caps. N3 is complete; N4 remains in progress. The [common evidence/review recording and offline aggregation paths](evidence_aggregate_v1.md) have been implemented and structurally tested with non-security synthetic metadata; the full N4-1 comparability gate has not passed. Automatic decomposition remains the main contribution hypothesis, ranking a secondary hypothesis, and context candidate exclusion a reliability task. The evaluation protocol remains unfrozen. This scope does not include a repeated-fuzzing runner or new candidate-generation features or runs.

## Research Objective

zkfDO studies whether component analysis constructed automatically from an original Circom project entrypoint can make zkFuzz practical and its results interpretable at project scale. Target construction must not depend on knowing the defect location. The study jointly measures applicability, reviewed distinct defect causes under equal time and resource limits, and the reliability of warnings after component isolation removes caller constraints.

The central question is whether the benefit of decomposition survives automatic target preparation, its costs, and review in the original context. A ranking advantage is a secondary hypothesis, not the premise of the project.

## Project Identity

zkfDO is a Rust helper CLI for zkFuzz. DO refers to DOUM ("도움", help). zkFuzz remains the external analysis engine. Target discovery, compilation reuse, scheduling, evidence collection, and candidate review are system components; their existence alone does not establish research novelty or performance superiority.

The existing implementation supports bounded target discovery, concrete instance handling, compilation reuse, static ranking, budgeted execution, and candidate review. Circom coverage is incomplete. General caller-context checking is proposed work, not an implemented guarantee. Projection to a first divergent component, whole-candidate cause attribution, and wrapper semantic preservation require evidence within a declared scope; none is a demonstrated general result. Calling an original template from a wrapper alone does not prove preservation of its caller constraints or compiler-level signal correspondence.

## Inputs and Outputs

Inputs are a reproducibly identified original project and entrypoint, its dependency and compiler configuration, the fixed zkFuzz version, and a preregistered resource budget. Versioned local documents, target lists, tool/file hashes, and miiz's decision record can record the freeze; a new git commit is not required. Known-defect labels may support independent outcome review but must not guide automatic target construction.

Expected outputs are:

- A target inventory linked to concrete instances and their call sites, with unsupported constructs and preparation failures retained.
- Structured execution and cost records, including preparation, compilation, analysis, and review costs.
- Candidate-level evidence and explicitly scoped review outcomes, deduplicated by defect cause rather than warning count.
- A reproducible comparison of whole-entrypoint and automatic component analysis on the fixed evaluation population.

## Research Questions and Priority

**RQ1 — Primary: applicability and reviewed results.** On original project entrypoints, how often can automatic component analysis prepare and run, and how does it compare with whole-entrypoint analysis in reviewed distinct causes and time to a reviewed result under equal resource limits? Report preparation failures, timeouts, and misses in the full denominator. Keep discovery time and review cost distinguishable.

**Context reliability — Primary validity requirement.** Which particular component candidates can be excluded as impossible in their original caller contexts, which remain unresolved, and which receive separate entrypoint or project-property confirmation? The initial method targets candidate-level exclusion within a declared supported scope. Excluding a candidate does not exclude its entire cause or justify deleting the warning. This validates the interpretation of automatic decomposition results; it is not a complete automatic project verifier or a change of the main contribution hypothesis.

**RQ2 — Secondary: static order.** Within the same prepared component set and budget, do existing static orders differ in reviewed outcomes or discovery time? Use fixed baseline strategies. Negative results are valid; adaptive scheduling and feature retuning are not prerequisites for RQ1.

## Meaning of Review Outcomes

Component validity and project context are separate dimensions. A component result may remain confirmed even if its particular candidate is excluded in the selected project's contexts.

These are research review categories. The [common record v1](evidence_record_v1.md) now preserves component, entrypoint TCCT, projection, attribution, and completion metadata separately, including general, contract, and legacy layers. It imports reported observations without performing semantic review. Context classification and project confirmation remain separate obligations; implementing the record does not establish those outcomes.

| Outcome | Required meaning |
|---|---|
| `component_confirmed` | The candidate satisfies the declared component input assumptions and all pinned original component constraints, and violates a predefined component property. |
| `context_excluded` | A sound argument excludes this candidate in every relevant call context covered by the selected entrypoint. Missing or unsupported contexts prevent an aggregate exclusion verdict. This does not prove the component or project defect-free. |
| `context_unresolved` | Available evidence establishes neither exclusion across all relevant contexts nor compatibility within the declared context scope. Missing support, incomplete evidence, and timeouts remain unknown. |
| `context_compatible` | Evidence establishes compatibility within the declared context scope. This alone does not establish a project property violation. |
| Entrypoint TCCT confirmation without component-cause attribution | Separate evidence rechecks all pinned entrypoint constraints and the declared input/output or computation-abort relation, with the entrypoint's role recorded. Report these results and attribution failures separately; do not add them to component-confirmed distinct causes or treat them as project-property violations. |
| `project_confirmed` | Separate evidence establishes a violation of the predefined project property in the pinned original project, including its input assumptions, constraints, and relevant call context. |

Matching a known defect's template or location is insufficient to count rediscovery: review must establish the same cause. Compatibility with all project constraints is insufficient to establish a project property violation. A component output may be only an intermediate value in the original project.

Reuse of an identical compiled instance must preserve all its distinct call contexts. Failure to find a contradiction is not confirmation. Post-hoc candidate classification changes the interpretation of recorded evidence; it does not justify deleting the warning or establish warning-level precision, and it does not recover exploration lost when the external engine stopped at an earlier candidate.

The N3 record proposes reporting at least one confirmed result per entrypoint execution unit, time to the first subsequently confirmed candidate, and distinct causes together at the same component-confirmation and attribution level. General TCCT criteria form the proposed main layer; contract-specific and project-semantic properties form separate layers. Distinct-cause yield can compare fixed pipelines, including termination and allocation policies. A binary metric does not remove first-candidate stopping effects. Known and additional causes require symmetric preregistered rules. Report projection, attribution, and review unknowns by method, including their effect on conclusions; do not create component-cause bounds by adding entrypoint-only confirmations. Incomplete review of earlier candidates prevents an exact first-confirmation claim.

Budget-bounded repeated attempts (design A) are the adopted research-design preference requiring separate implementation and validation. Native-stop is an explicit alternative, not an automatic fallback. Consuming an allocation does not establish equal actual CPU, wall time, memory, or idle time. Measure resource use and unused allocation separately. At least as many lost as rescued units would refute an observed net binary gain in that comparison, but would not by itself refute gains in discovery time, distinct causes, cost, or RQ1 as a whole.

## Contribution Hypotheses and Evidence Needed

1. Automatic component construction can improve usable analysis coverage and reviewed results on real project entrypoints. This requires multiple independent projects and equal-resource comparisons, not repeated runs of one development case.
2. Restricted, sound candidate exclusion can clarify which recorded candidates cannot occur in their declared caller contexts while preserving warnings and unknown outcomes. Its supported semantics, exclusion obligations, unresolved fraction, and review cost must be explicit; candidate exclusion alone does not establish warning-level precision.
3. Reuse and structured evidence can make the workflow affordable and auditable. Their measured engineering benefit supports the system contribution; first-of-its-kind claims require a separate related-work comparison.

Existing development pilots motivate these hypotheses. They do not establish general superiority, a held-out evaluation result, or project-level impact. N1 completed the metadata audit; execution eligibility and independence still require evidence before setting the final claim scope. A shortfall reduces that scope rather than justifying reuse of development cases as held-out evidence.

N1 found 70 Circom case records, 56 declared original cases, and 36 potential project/commit/entrypoint groups whose configurations remain unverified. All 70 have metadata and public-result exposure. Evaluation separated from method development must therefore be distinguished from never-exposed generalization, with evidence required for non-development use and project-family boundaries. The [N3 contribution criteria and metric-specific gates](scope_decision_final_2026-10-01.md#6-지표별-기여-판단과-중단-기준) require evidence of technical distinction, evaluation separated from tuning, reliable review, and total cost. Weak ranking results do not by themselves refute decomposition, and successful candidate exclusion alone does not establish its contribution. Narrowing claims to applicability or case studies is distinct from changing the research direction; any such change requires a separate decision with supporting evidence.

The adopted N4 sequence checks comparability before preparation bottlenecks and conditional context classification, with a gate after the first stage. The 40-hour total and 12/10/10/8-hour stage caps are work limits, not completion estimates. The current N4-1 authorization covers the recording path and structural checks stated in the decision plus the subsequent metadata-only offline aggregation request; it does not authorize new candidate-generation runs or automatic progression to N4-2. N5 must freeze an initial target list, inclusion rules, execution-unit generation and deduplication, budgets, and preparation-failure rules. Preparation artifacts may then be generated and hashed before their corresponding evaluation runs, retaining every planned target's disposition. Success-only post-hoc selection is prohibited. Historical preparation remains a separate evidence and exposure layer; a new freeze cannot erase it.

## Non-Goals for the Current Study

- A new fuzzing engine, solver, compiler, general verifier, or complete Circom frontend.
- Adaptive scheduling, an ML/LLM ranker, or extension to multiple analysis engines.
- A mandatory new-vulnerability count or expansion to unrelated project families to meet a numerical target.
- Guaranteed discovery, universal soundness outside the declared context-filter scope, or a claim that every local warning implies a project defect.
- Recasting legacy injection results or development pilots as independent evaluation evidence.

## Evidence and Change Discipline

All changes remain local for human review; no commit, push, or pull request is performed by an agent. Frozen protocols, manifests, contracts, run records, and verdicts remain unchanged; revisions use new versioned files. Do not run zkFuzz on held-out candidates before the applicable evaluation protocol is frozen. Keep raw candidates and compiled artifacts under ignored `runs/`; retain only value-free paths, hashes, verdicts, and timings in tracked evidence. The current plan records task ownership and status.
