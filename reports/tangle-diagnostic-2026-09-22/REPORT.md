# Tangle SetMembership missed-finding diagnostic

Date: 2026-09-22

Classification: **zkFuzz expression/search limitation**, specifically an oracle boundary. This is a development diagnostic and is not added to controlled-v2 or controlled-v3 performance metrics.

## Frozen source and contract check

The reviewed vulnerable revision is `848d073bb17f0aaffc6d39f594cc59efedeaec89`; the fixed revision is `eeb4fc7a4883d513e3fe3adbe2c447133ccd39f2`. The vulnerable and fixed source SHA-256 values remain `884f3b47…142a0` and `aa3591a3…aaaa3`. Both use the same `SetMembership(3)` wrapper, SHA-256 `04f13d96…141c`.

The wrapper, component parameter and input contract are consistent with controlled-v2: `element` and the three set entries are canonical BN128 field elements, with no narrower caller precondition. The predeclared property is that every satisfying assignment has `element` equal to at least one set entry.

The vulnerable source constrains

`element × ∏(set[i] − element) = 0`,

while the fixed source constrains

`∏(set[i] − element) = 0`.

The extra `element` factor makes the vulnerable constraint true when `element` is zero even if no set entry is zero. The wrapper and contract therefore expose the published defect; the controlled-v2 miss was not caused by selecting the wrong component or parameter.

## Independent property oracle

Both variants were compiled with Circom 2.2.3 / BN128 into six-constraint R1CS files. The diagnostic enumerated all 16 input assignments in `{0,1}^4`, reconstructed every internal signal from the corresponding source expression, and evaluated all compiled R1CS constraints.

- Vulnerable source: one assignment satisfied all six constraints and violated membership.
- Fixed source: zero assignments both satisfied all constraints and violated membership.
- No raw assignment value is stored in the report.

This establishes existence for the vulnerable direct component and rejection by the fixed component within a fully enumerated subdomain. It does not establish project caller reachability.

## zkFuzz representability and diagnostic runs

The current input generator can represent zero and one, and the direct component exposes four private inputs. More strongly, `quick` mode enumerated all `3^12 = 531,441` assignments over zero, one and minus one for the twelve symbolic signals. That set includes the oracle's binary satisfying property violation. zkFuzz still returned `WellConstrained` and no candidate.

| run | fixed condition | result |
|---|---|---|
| quick enumeration | 30 s process limit | completed in 0.241 s; 531,441 assignments; `WellConstrained`; 0 candidates |
| v2-equivalent GA | seed `2026092001`, 500 generations, 30 s limit | completed in 3.919 s; 0 candidates |
| binary-focused GA | seed `2026092201`, input population 128, 5,000 generations, 120 s limit | budget exhausted at 120.005 s; 0 candidates |

The zkFuzz binary SHA-256 is `ac2d9d16…e4edd`; Circom is `89918878…6227`. Raw stdout/stderr and any candidate location are under the ignored `runs/tangle-diagnostic-2026-09-22/` tree. `diagnosis.json` records complete commands, hashes, budgets and timings without assignment values.

## Cause

zkFuzz's current TCCT oracle reports symbolic-trace/side-constraint disagreement, unexpected rejected input, unused output, or nondeterministic output. For this defect, the vulnerable source trace and its compiled constraints agree: both intentionally compute the same incorrect membership equation. The external membership property is violated, but there is no trace/constraint disagreement for zkFuzz to flag.

The exhaustive quick run shows that increasing GA budget or changing seed cannot by itself turn this semantic violation into a TCCT counterexample. The longer GA run is supporting evidence only. The primary evidence is the property oracle plus exhaustive zkFuzz result.

No zkfDO target-analysis or execution defect was found, and no ranking code or weight was changed. Detecting this class would require an explicit property oracle or differential specification outside the current zkFuzz counterexample definition; that is a new capability, not a minimal bug fix for this milestone.
