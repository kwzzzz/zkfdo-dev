# Lifting fixture format (L-01)

Each fixture is one directory `tests/fixtures/lifting/<name>/`. The test runner executes every directory that contains `request.json` with `zkfDO experiment lift` and compares the result with `expected.json`. Requires `circom` 2.2.x, `node`, and `snarkjs` on `PATH`.

## Files

```
<name>/
  request.json        lifting request (below)
  expected.json       expected verdicts (below)
  src/...             Circom sources: the entrypoint, the component wrapper, shared templates
  base_input.json     a benign entrypoint input; honest witness generation must succeed on it
  candidate.json      the component candidate
```

All paths in `request.json` are relative to the fixture directory. Do not put compiled artifacts in the fixture.

## request.json

```json
{
  "schema": "zkfdo-lifting-request-v1",
  "id": "f1-public-input-violation",
  "source_root": "src",
  "library_paths": [],
  "component_wrapper": "src/component.circom",
  "entrypoint": "src/main.circom",
  "base_input": "base_input.json",
  "candidate": { "format": "named", "path": "candidate.json" }
}
```

- `component_wrapper`: a file whose `component main = T(...)` instantiates the candidate's template with the same parameters as the call sites. Both files must be inside `source_root`.
- `candidate.format`: `named` or `zkfuzz`. `named` is a flat JSON object `{"main.a": "3", "main.sub.out[0]": "1", ...}` of canonical decimal strings. It must name **every** signal of the component, including nested components and eliminated signals, exactly as circom writes them in `.sym` (anonymous components use circom's `Template_line_col` names). `zkfuzz` is a zkFuzz counterexample file; its `7_assignment` object is read.
- Values must satisfy the component's constraints. The engine does not search for candidates.

## expected.json

```json
{
  "sites": { "main.s1": "entrypoint_violation", "main.s2": "excluded_in_context" },
  "sites_found": 2
}
```

- Keys are call-site instance paths in the entrypoint. Only the representative of each site class is evaluated: a class collects the sites whose paths are equal after every numeric index is replaced by `*`, and the representative has the smallest indices. List representatives only.
- `sites_found` is the number of call sites (all classes) the engine must enumerate.
- Verdicts: `entrypoint_violation`, `compatible_no_top_violation_observed`, `excluded_in_context`, `unknown`, `preparation_failure` (definitions: [docs/lifting_feasibility_2026-10-02.md](../../../docs/lifting_feasibility_2026-10-02.md)). Optional `"reasons": {"<site>": "<reason_code>"}` pins the reason code as well.

## What the engine does (so fixtures exercise it)

1. Computes the honest component witness for the candidate's inputs and finds the signals where the candidate differs.
2. Rewrites only the `<--` statements that assign those signals, in the template matched to each instance by its declared signal names, so the hint returns the candidate value when that template's inputs equal the candidate's inputs and the original expression otherwise. The rewritten entrypoint must compile to the same R1CS and `.sym`.
3. Finds call sites in the entrypoint whose full signal-name set equals the component's.
4. Maps each component input through chains of `x - y = 0` constraints in an `--O0` compile to an entrypoint input (substituted into `base_input`), a constant (mismatch → `excluded_in_context`, reason `constant_input_mismatch`; two inputs tied to one entrypoint input with different values → `excluded_in_context`, reason `conflicting_input_binding`), or an intermediate signal (→ `unknown`, reason `input_requires_inversion`).
5. Computes the honest and the hinted witness on the same input and checks the hinted one against the original R1CS with the Rust evaluator and `snarkjs wtns check`.

## Engine changes in L-02

- A candidate equal to the honest component computation stops before lifting with preparation status `not_tcct_deviation` (reason `component_equals_honest`) and no sites. Honest controls therefore end there unless preparation fails earlier.
- An intermediate site input is no longer `unknown` immediately. The engine first tries (a) back-propagation along O0 constraint paths and then (b) a bounded z3 solve of the surrounding constraints. A proposal counts only if the honest O0 computation reproduces the site inputs; if the honest computation aborts, the hinted generator is used instead. The site then goes through the full L-01 check. Unknown reasons include `synthesis_reference_aborted`, `synthesis_cone_too_large`, `synthesis_timeout`, `synthesis_model_not_reproduced`, `synthesis_local_unsat`, and `synthesis_cone_unsat`. The last means the cone is refuted for every entrypoint input but is still not promoted to `excluded_in_context`.
- A refutation after a failed deviated generation is `excluded_in_context` only when every site input is bound directly to an entrypoint input or a constant; otherwise it is `unknown` with reason `reference_input_refuted`.

## Engine changes in L-03

- A closed cone (fixed values are only the candidate's site-input values and the entrypoint inputs bound directly to them) that z3 reports unsat makes the site `excluded_in_context` with reason `closed_cone_unsat`.
- A `not_tcct_deviation` candidate is no longer dropped. It is judged for the second property (`property: input_assumption`): `assumption_input_reachable`, `excluded_in_context`, `unknown`, or `preparation_failure`. Honest controls therefore expect `assumption_input_reachable` (`expected.control-v3.json`).
- When the synthesis reference computation aborts, the failing statement is classified. A `===` constraint sends the site to the closed cone; an `assert` alone ends as `abort_on_unconstrained_check`.

## Engine changes in L-04

- The closed-cone exclusion sweep has one 20-second budget per candidate, shared by all of its sites. A site left undecided after the budget is spent ends as `unknown` with reason `budget_exhausted`; `synthesis.cause_before_budget` keeps the reason it would have had.
- Before z3, the engine propagates bit-decomposition ranges (`x = Σ 2^i·b_i` with boolean `b_i`) and linear intervals from the fixed values. A contradiction makes the site `excluded_in_context` with `exclusion_method = bit_decomposition_interval`, and the evidence names the decomposition's constraint index and instance. For `tcct` candidates the closed cone also fixes the candidate's site outputs.
- When the generator does not reproduce a solver model because a `<--` hint outside the site computes a different value, the engine rewrites those hint statements to return the model's values when their template's inputs equal the model's, recompiles (the R1CS and `.sym` must stay identical), and records the exception `hint_injection: …` with `synthesis.reached_with = hint_injection`. The witness must still satisfy the original R1CS in both checkers.

## Suggested five fixtures

| Fixture | Shape | Expected |
|---|---|---|
| public-input violation | underconstrained hint; site inputs wired to main inputs; output reaches `main` outputs | `entrypoint_violation` |
| masked output | same component, but the entrypoint multiplies its output by 0 (or otherwise discards it) before any output | `compatible_no_top_violation_observed` |
| constant mismatch | a site input bound to a constant different from the candidate's value | `excluded_in_context` |
| intermediate input | a site input computed from a non-linear expression of main inputs | `unknown` |
| constraint-changing hint or unmatched site | e.g. the entrypoint has no instance with the component's signal set (`sites_found: 0`) | `preparation_failure` (empty `sites` allowed) |

Use one template per fixture where possible; do not rely on template or signal names having special meaning — the engine must not branch on them.

## Engine changes in L-05

- **Violated condition (step 1).** For an `input_assumption` candidate, `violated_condition` lists the component instances whose template is named `LessThan` (zkFuzz attaches its integer-comparison condition by that name) and whose candidate values break `(out == 1 && in[0] < in[1]) || (out == 0 && in[0] >= in[1])`, with inputs compared as integers in [0, p). `kind` is `lessthan_semantic`, `original_assert_failure`, or `condition_not_reconstructed`. No other template name is used.
- **Assumption predicate (step 2).** Each class gets one `predicates` entry per broken instance at the class representative: `assumption_violation_reachable` (the class's own reached witness, or a witness found by the search, satisfies the original R1CS in both checkers and the instance's `out` differs from the integer comparison; `semantic_deviation_observed` is set), `assumption_excluded_in_context` (z3 unsat on O0 constraints around the instance with nothing fixed, plus implied range facts: bit-decomposition intervals, boolean classes, constants), or `unknown`. `assumption_predicate_verdict` aggregates them (reachable if any is, excluded if all are).
- **Abort localization and repair (step 3).** When a generator aborts on a check, a diagnostic copy with the check blanked runs to the end; its witness (same O0 wires, confirmed by the `.sym` files) is evaluated on the original O0 R1CS, and the unsatisfied constraint indices name the failing instances (`synthesis.repair.localizations` / `synthesis.injection.localizations`). A small cone (the instance, the links that assign its inputs, and upstream paths to the nearest `<--` hints) is solved by z3 with every other wire at its current value, and changed hints are injected. The copy only locates; verdicts still come from generators whose R1CS equals the original, checked by both checkers. An unsatisfiable repair cone is never an exclusion.
- **`.sym` check for rewritten generators.** circom names anonymous components `Template_<line>_<byte offset>`, so a longer rewritten statement earlier in the same file renames them. Rewritten generators must keep the R1CS byte-identical and the `.sym` identical up to a consistent renaming of those offsets (`hinted_sym_anonymous_renames`); line numbers are preserved.
- **New fixtures** in `tests/fixtures/lifting_engine/` (`lessthan_excluded`, `lessthan_reachable`, `lessthan_search`, `abort_repair`), with candidates written by `make_candidates.py` from the honest component witness.
