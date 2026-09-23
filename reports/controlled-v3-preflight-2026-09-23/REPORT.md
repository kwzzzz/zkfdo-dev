# controlled-v3 development preflight

Date: 2026-09-23. Status at this freeze: **four targets prepared and planned; zero controlled-v3 backend attempts and zero reviewed candidates**.

The initial survey compiled ten vulnerable/fixed variants from five proposed pairs under Circom 2.2.3 and BN128. Compilation alone did not establish a valid evaluation set. After source, fix, contract and parser review, only circomlib `Decoder(4)` and UniRep `BigLessThan()` were selected as two independent **development** causes. Both pairs were used while fixing target inspection, so they cannot serve as a held-out measure of ranking performance. The original ≥5 independent causes in ≥3 projects evaluation goal remains open.

| Pair | Vulnerable / fixed source | Frozen constraints | Static risk and warnings |
|---|---|---:|---:|
| circomlib Decoder | `cff5ab6…` / direct-child `9d2918e…` | 6 / 12 | 0 and 0 / 0 and 0 |
| UniRep BigLessThan | `0985a28…` / public fix `3348caa…` | 780 / 1306 | 1 and 1 / 4 and 4 |

All four targets have complete inspection, successful compilation and semantic analysis, and no preparation exclusion. Within each pair, the current static risk score is tied; this preflight does **not** show that ranking identifies the vulnerable variant. The saved risk-only plan orders the fixed BigLessThan first, its vulnerable pair second, fixed Decoder third and vulnerable Decoder fourth.

Source revisions, Git blob hashes, SHA-256 hashes, the BN128 input contracts and the component properties are in [contracts](../../datasets/contracts.controlled-v3-development.json). The [protocol](../../docs/controlled_v3_development_protocol.md) fixes one 30-second-per-target, 120-second-total backend pilot with seed `2026092301` before execution. [Evidence](evidence.json) records the exact source checkpoint, initial compile survey, prepared record, plan, hashes, target IDs and scores. Byte-identical value-free [prepared](evidence/prepared.json) and [plan](evidence/plan.json) copies are checked in; raw future candidates stay under ignored `runs/`.

The four other local candidate surveys remain present and ignored, with their original bytes listed in the local pre-freeze checkpoint. BigMod and zk-email FpMul need parser support and a stronger bounded arithmetic contract; Rarimo DateEncoder's named fix leaves another witness-only quantity; UniRep EpochKeyLite has a contaminated pair and an external semantic boundary. MiMC's historical source does not compile in the current environment and its compatibility variant repeats an earlier cause. None of these is a selected target or a backend attempt. The Rarimo include-path regression did verify an adapter fix, but did not make Rarimo an eligible cause.

The direct wrappers establish component-level reachability under the frozen source snapshots. A larger project caller, production source provenance and general project impact have not been established. Backend discovery, full assignment validation and detection time remain unmeasured at this freeze.
