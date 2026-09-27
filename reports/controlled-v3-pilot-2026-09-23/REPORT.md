# controlled-v3 development pilot result

Date: 2026-09-23. This was the **single predeclared pilot run** of the two-pair development set under the [frozen protocol](../../docs/controlled_v3_development_protocol.md). All four targets started in the saved risk-only order, with zkFuzz seed `2026092301`, 30 seconds per target and 120 seconds total. There were no runner failures or replacement runs.

**One new independent original-component cause was rediscovered and validated:** circomlib `Decoder(4)` permits an output that disagrees with its declared equality test. UniRep `BigLessThan()` produced no saved candidate before its 30-second limit. The campaign result is **1/2 selected known causes**, with **0 project-level confirmed defects**.

| Plan order | Target | Backend status | Completion upper bound from plan start |
|---:|---|---|---:|
| 1 | UniRep BigLessThan fixed comparator | timeout | 30.008 s |
| 2 | UniRep BigLessThan vulnerable | timeout | 60.012 s |
| 3 | circomlib Decoder fixed comparator | no counterexample | 74.097 s |
| 4 | circomlib Decoder vulnerable | bug candidate | 74.156 s |

The Decoder candidate was hash-matched to the saved run and target. Its input met the canonical BN128 precondition. A separate compile with symbol output produced an R1CS byte-identical to the frozen prepared R1CS (SHA-256 `89627dd5…`); the complete assignment satisfied **all six** constraints. It violated the [predeclared Decoder output equivalence](../../datasets/contracts.controlled-v3-development.json). The value-free [candidate review](candidate-review.json) records all three verdicts; the [schema 2 confirmation](confirmation.schema2.json) was accepted by the stored [evaluation](evaluation.json) as one original-component root cause and zero project-level causes. The preserved candidate SHA-256 is `d5a3d6f2…`; signal values remain only in the ignored local run directory.

The candidate-producing Decoder process completed in about 0.056 seconds after it started. The **74.156-second detection time is a scheduler completion upper bound** that includes the three earlier targets, including two 30-second UniRep timeouts. It is not an exact candidate-generation timestamp. Preparation took 1.620 seconds, scheduler execution 74.156 seconds, and automated post-run review is recorded separately. Manual review time was not instrumented.

The [value-free outcome and per-target records](evidence.json) are byte-identical copies of the local execution records. The fixed plan and prepared record are in the [preflight evidence](../controlled-v3-preflight-2026-09-23/evidence.json). The review program is [review_candidate.py](review_candidate.py); it checks the full R1CS assignment and property without writing signal values to reports. The raw candidate and generated R1CS/SYM are ignored local evidence, so a teammate using only this Git commit can verify hashes and the reported verdict structure but must recreate or obtain the raw local evidence to independently recompute the witness checks.

This result shows an additional end-to-end validated known defect on a second project. It does not establish that risk-only ranks vulnerable variants well: each vulnerable/fixed pair had a tied static risk score, and the saved tie-break put both fixed variants first. One run cannot compare strategies, and the BigLessThan timeout is an inconclusive search outcome. Both cases were examined during development, so this is not a held-out performance estimate. The larger real-project caller experiment and the planned ≥5-cause, ≥3-project held-out set remain open.
