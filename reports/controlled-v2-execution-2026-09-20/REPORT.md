# controlled-v2 held-out execution report

Date: 2026-09-20

## Result

The fixed campaign completed **12 paired blocks, 36 strategy executions and 144 target attempts** without a retry, missing outcome or unreviewed candidate.

One of the two eligible independent causes was rediscovered and validated: Banyan `Blake3NovaTreePath_CheckDepth` missing 8-bit comparator input constraints. Tangle `SetMembership(3)` wrong product initialization was not rediscovered. The 36 validated candidate records are repetitions of the same Banyan root cause, so the campaign-level valid independent-cause count is **1**, not 36.

| Strategy | blocks with any valid cause | detected cause opportunities | independent causes found | mean first valid completion upper bound | median | backend statuses |
|---|---:|---:|---:|---:|---:|---|
| risk-only | 12/12 | 12/24 (50%) | 1/2 | 0.032 s | 0.033 s | 12 bug_found, 12 timeout, 24 no_counterexample |
| random | 12/12 | 12/24 (50%) | 1/2 | 16.420 s | 7.806 s | 12 bug_found, 12 timeout, 24 no_counterexample |
| small-first | 12/12 | 12/24 (50%) | 1/2 | 7.851 s | 7.853 s | 12 bug_found, 12 timeout, 24 no_counterexample |

All three strategies found the same one cause in every block, so risk-only did **not** improve the number or rate of independent causes found. Its earlier upper bound comes from the frozen target order: risk-only placed the Banyan vulnerable target first, small-first placed it third, and random placed it first twice, second four times, third five times and fourth once.

In the paired descriptive comparison, risk-only's first valid completion upper bound was lower than random in 10/12 blocks and lower than small-first in 12/12 blocks. The mean paired differences (`risk-only - comparator`) were -16.388 seconds versus random and -7.819 seconds versus small-first. No inferential test was added after seeing the results. These are scheduler completion upper bounds, not exact candidate-generation times.

## Candidate adjudication

Each of the 36 `bug_found` artifacts was hash-checked against its preserved campaign copy and linked to the same saved plan run and Banyan vulnerable target. Every artifact met the frozen three-part contract:

1. `depth` and `leaf_depth` were canonical BN128 field elements.
2. The complete assignment satisfied all 29 constraints in the hash-pinned prepared R1CS.
3. It violated the predeclared component property because the satisfying assignment used an input outside the component's required unsigned 8-bit domain.

The independently recompiled review R1CS is byte-identical to the prepared campaign R1CS (SHA-256 `2ce972ae628f4e107f52aaea51994670b39937f4d010e8da895eaa99adacacc9`). The review records contain verdicts, hashes and links, and do not contain signal values.

All 36 validated records were accepted by evaluation schema 2 as `backend-execution` / `original-component`. The confirmed project-level count is **0** because caller reachability and project impact were not reviewed.

## Execution integrity and costs

- Campaign ledger: [byte-identical Git-visible copy](evidence/campaign-ledger.json) of `runs/controlled-v2/campaigns/campaign-20260920T112512Z/campaign.json`, SHA-256 `ce48197f3bcab4fca083af1388af1623f966549261ba290ebbd2a16d17c7be10`. The [record index](evidence/record-index.json) maps the original paths to value-free copies of the 12 block records, 12 environment records, 36 plans, 36 outcomes and frozen driver. Raw candidates remain only in the ignored campaign directory.
- Candidate review: `candidate-review.json`, SHA-256 `b02fa047b580421704cc70287efb6159d1506a8604b8989619d01aa82fc5323e`.
- Schema-2 evaluation index: `evaluation-index.json`, SHA-256 `53093150384fc4519d261b8783c5db41bf30406050fd24b7d8347214ecde432c`.
- Analysis: `analysis.json`, SHA-256 `29370a724442a808db1e318e02dd115d45536776df6c3e7849c06202e0f14335`.
- Campaign wall time was 1381.721 seconds. Shared preparation was 1.755 seconds.
- Mean scheduler time was 37.943 seconds for risk-only, 37.830 for random and 37.859 for small-first.
- Automated post-run constraint/property review took 0.050 seconds; schema-2 evaluation driver time was 1.421 seconds. Manual review setup time was not instrumented and remains `null`.
- There were 36 fixed-comparator timeouts, 72 completed no-counterexample attempts, zero runner failures and zero not-started targets.

The 36 source-directory raw duplicates were deleted only after byte/hash equality with their ignored `runs/controlled-v2/` preserved copies was verified. `raw-candidate-storage-cleanup.json` records paths and hashes without values. Raw candidate values are not in this report or the Git-visible evidence.

## Scope

The selection was fixed before backend execution. Subtract was excluded as an observed development positive control, and dev3 Reclaim causes and variants were excluded. Tangle and Banyan are different projects and cause classes; their vulnerable/fixed variants are paired comparators rather than four independent cases. SIV, Aptos and Telepathy were excluded for the provenance/contract/tool-compatibility reasons recorded in the preparation report; zk-email `FpMul` was not expanded after the two-case minimum was met.

The protocol and contract files intentionally retain their pre-execution `not_run` status as the immutable freeze point. This report, `candidate-review.json`, `evaluation-index.json` and `analysis.json` record the completed post-freeze state.

This result supports a limited target-order finding: for the one cause that zkFuzz rediscovered, putting its target first reduced the completion-time upper bound. It does not show that risk-only finds more independent causes, does not show that it can rediscover Tangle under this configuration, and does not establish general multi-project superiority. Static scores, public defect labels and fixed-variant status were not counted as discoveries.
