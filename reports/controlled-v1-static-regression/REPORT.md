# controlled-v1 static regression review

Date: 2026-09-19

## Scope and conclusion

Question: what differences do the current zkfDO static ranking signals show between the frozen vulnerable and fixed `Subtract` variants?

**Conclusion: the current static signals distinguish this pair.** The vulnerable variant receives semantic risk `2` and selected-warning count `2`; the fixed variant receives `0` and `0`. The existing lexical `legacy` score is also higher for the vulnerable variant (`4.638574590472789` versus `1.163042446019645`). Both analyses completed, so the fixed zero is an observed zero for the five selected rules rather than an analysis failure or unsupported result.

This is a static regression observation for one frozen pair. The diagnostics are not execution-validated defects, and the fixed variant's selected-rule zero is not proof of safety. No fuzzing, counterexample, witness, proof, or WASM execution was performed. Execution discovery count and time remain `null` in [diagnostics.json](diagnostics.json).

## Frozen setup

The pre-run record is [run-config.json](run-config.json), SHA-256 `a721084a096349b60f62e59cb5fb010f0f19bc126a0be993d4977d0ea3bbc532`. The relevant tracked implementation and configuration files had no worktree diff before the run. No input source, rule, weight, or implementation was changed after seeing the result.

| Item | Frozen value |
|---|---|
| Analyzer | Circomspect `0.9.0`, revision `ece9efe0a21e6c422a43ab6f2e1c0ce99678013b` |
| Analyzer binary | `.external/circomspect/target/release/circomspect`, SHA-256 `6acebb5f1c00fd3823e96388cb322cd29bd516f8bacecf855fee5652431c3590` |
| Curve and timeout | `BN254`, 60 seconds per tool invocation |
| Selected semantic rules | `CS0013`, `CS0014`, `CS0015`, `CS0017`, `CS0018` |
| Semantic risk | sum of the five complete binary rule-existence features |
| Warning count | deduplicated, in-scope diagnostics from the same five rules |
| Existing lexical score | current weighted lexical risk divided by current estimated cost |
| Vulnerable source | revision `d310309c141d36504b3486cebd96ed70ef3a4fdf`, SHA-256 `502ee44b70a368066fafcf09cc2d0356479f8a862bfa726bde8097c728c83cc1` |
| Fixed source | revision `b8f92bdec1694138df0e069921f1aa0bdc94053e`, SHA-256 `c5d6aa9de7e95f09283e6b014dcbda85e16e583c3e157d7f8fdd95bb001023ba` |

The semantic rule set is declared in [`src/semantic.rs`](../../src/semantic.rs#L14-L17); its binary feature and score calculation is at [`src/semantic.rs`](../../src/semantic.rs#L377-L412). The semantic values are copied into ranking input at [`src/corpus.rs`](../../src/corpus.rs#L601-L651). The existing lexical formula is in [`src/ranker.rs`](../../src/ranker.rs#L41-L55) and is captured for the `legacy` strategy at [`src/corpus.rs`](../../src/corpus.rs#L671-L690). `configs/static-ranking.json` only supplies the structural groups used later by `risk-grouped`; it does not change semantic or lexical feature weights during preparation.

The exact command in `run-config.json` ran common preparation with no strategy filter. That requested entrypoint inspection, source snapshotting, compile/structure preparation, Circomspect analysis, and the existing lexical extractor. It did not create an experiment plan or invoke the zkFuzz search path.

## Result

| Variant | Analysis | Selected diagnostics | Semantic risk | Selected warning count | Legacy score | R1CS size | Complexity |
|---|---:|---|---:|---:|---:|---:|---:|
| Vulnerable | complete | `CS0013` at line 8; `CS0017` at line 7, related constraint line 9 | 2 | 2 | 4.638574590472789 | 1 | 0 |
| Fixed | complete | none from the selected five rules | 0 | 0 | 1.163042446019645 | 1 | 0 |

Both targets were eligible, compiled successfully, did not time out, and had no execution error or analysis-completion reason. Circomspect exited `1` for both because it emitted at least one issue; this is an accepted diagnostic exit status in the current adapter. Completion summaries and successful `Subtract` CFG lifting are preserved in the raw stdout and stderr logs.

### Selected semantic diagnostics

The vulnerable source produced:

- `CS0013` at [`subtractTensor.circom:8`](../../datasets/controlled-v1/subtract/vulnerable/subtractTensor.circom#L8): `d <-- 1` uses a single-arrow assignment where the analyzer says constraint assignment is possible.
- `CS0017` at [`subtractTensor.circom:7`](../../datasets/controlled-v1/subtract/vulnerable/subtractTensor.circom#L7), with related location at line 9: intermediate signal `d` occurs in only one separate constraint under the analyzer's approximation.

`CS0014`, `CS0015`, and `CS0018` were complete zeros for the vulnerable variant. All five selected features were complete zeros for the fixed variant. There were no out-of-scope or duplicate selected diagnostics.

Raw evidence:

- Vulnerable: [semantic summary](evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/targets/0000/semantic/semantic.json), [SARIF](evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/targets/0000/semantic/analysis.sarif), [stdout](evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/targets/0000/semantic/stdout.log), [stderr](evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/targets/0000/semantic/stderr.log)
- Fixed: [semantic summary](evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/targets/0001/semantic/semantic.json), [SARIF](evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/targets/0001/semantic/analysis.sarif), [stdout](evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/targets/0001/semantic/stdout.log), [stderr](evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/targets/0001/semantic/stderr.log)
- Full preparation output: [prepare.stdout.json](evidence/prepare.stdout.json)

### Diagnostics intentionally not scored

Circomspect also emitted `CS0004` as a `note` about field arithmetic:

- vulnerable line 9, expression `(a - b)*d`
- fixed line 7, expression `(a - b)`

The adapter records each as `ignored_other_rule_count: 1` because `CS0004` is outside the frozen five-rule feature set. It therefore changes neither semantic risk nor selected warning count. The analyzer's compile-time-parameter-assertion versus signal-assertion distinction remains explicitly `unsupported`; assertions are not scored. Neither source contains an assertion, so this unsupported feature does not create the observed difference.

### Lexical feature contribution

The captured `legacy` scores were independently recomputed from the frozen source and current formula as a consistency check:

| Component | Vulnerable | Fixed |
|---|---:|---:|
| `<--` count | 1 | 0 |
| input signal count | 2 | 2 |
| lexical risk numerator | 26 | 6 |
| nonempty LOC | 9 | 7 |
| total signal count | 4 | 3 |
| estimated cost denominator | 5.605170185988092 | 5.1588830833596715 |
| final legacy score | 4.638574590472789 | 1.163042446019645 |

All other weighted lexical features were zero in both sources. The legacy difference is primarily the 20-point `<--` feature; both receive six numerator points from two inputs. This score is a lexical baseline and is not a semantic defect probability.

## Effect on current ranking strategies

- `risk-only`: vulnerable before fixed (`2 > 0`).
- `warning-first`: vulnerable before fixed (`2 > 0`).
- `risk-grouped`: both have complexity `0`; within that group, semantic risk places vulnerable first.
- `legacy`: vulnerable before fixed (`4.6386 > 1.1630`).
- `small-first`: tied at one compiled constraint; its target-ID tie-break applies.
- `path-order` and `random`: do not use these risk signals.

Equal R1CS size and structural complexity do not establish semantic equivalence or safety. This run measures neither zkFuzz detection success nor relative strategy performance.

If this result is used to modify features, analyzer rules, weights, wrappers, or ranking behavior, this `Subtract` root-cause group must be reclassified from held-out evaluation data to development data before later claims are made.
