# controlled-v3 development backend pilot

Frozen on 2026-09-23, before the first controlled-v3 backend run. The purpose is to check whether the current end-to-end pipeline can run two additional source pairs and produce reviewable results. These two known cases were inspected during parser development. This is a **development compatibility pilot**, not a held-out ranking evaluation. The five-cause, three-project v3 evaluation goal is still unmet.

## Frozen material

- Source set: `datasets/manifest.controlled-v3-development.json`, SHA-256 `4c52bc101a2b3d3dc7a193c4dded8f15778639e4294946b0adb5f222fa73304d`.
- Source provenance, input contracts and properties: `datasets/contracts.controlled-v3-development.json`. The contract is fixed by the pre-execution Git commit; its hash can be recorded after that commit without changing it.
- Prepared record: `runs/controlled-v3-development/frozen-preparation-2026-09-23/prepare-fd0251c3-34fa-4899-8c0e-fe141f14f472/prepared.json`, SHA-256 `2669bd3cf1616b03c52b4c986b6083755f2797d08bda59915e1b4d3e2d4ac443`. Four of four targets are eligible, with no exclusions.
- Execution plan: `runs/controlled-v3-development/pilot-2026-09-23/plan.json`, plan ID `117a6076-a970-4b72-94ec-46e319296445`, SHA-256 `cf4e11f82b5dd2fc5fbc608cbe8b9c9b758c4d4ee13103d79c8230193a8e781e`.
- zkfDO code commit `22eb43934aa942be874f29f8c88ec4b27c3e3211`; frozen binary SHA-256 `11f0b41bd5a8ef819a19be16a3b0fd882fa6640e49cfbd9dadaac6d0af31cc27`. Circom 2.2.3, BN128, Circomspect 0.9.0, zkFuzz 2.2.1 and ranking configuration hashes are in the contracts file.

The development set has two independent named causes in two projects. Vulnerable and fixed variants share a cause and count as one pair. The risk-only score ties within each pair: Decoder is 0/0 and BigLessThan is 1/1. The frozen plan orders the fixed BigLessThan first, vulnerable BigLessThan second, fixed Decoder third, and vulnerable Decoder fourth. This order is a deterministic tie-break, not a conclusion about vulnerability.

## One execution

Run the saved `risk-only` plan exactly once with zkFuzz seed `2026092301`, a 30-second limit per target and 120-second total process-attempt limit. No ranking seed is used by risk-only. Shared preparation and post-run review time are recorded separately from the backend budget. Keep the output and raw candidate files only under the ignored `runs/controlled-v3-development/` tree. Save a Git-visible, value-free outcome/ledger copy and a candidate review record after execution.

Before execution, verify the SHA-256 of the manifest, prepared record, plan, frozen zkfDO binary, zkFuzz binary, Circom binary, Circomspect binary and ranking configuration. If any differs, stop and document it; do not silently substitute another source or tool. A backend timeout, crash, no-counterexample result, or invalid candidate is an observed outcome and does not justify replacing the run. An external interruption before a complete backend outcome is recorded as an invalid pilot attempt and may be followed by a newly labeled run, with both attempts retained.

## Candidate review and reporting

For every `bug_found`, verify the saved plan and run/target link and candidate hash. Then inspect the original frozen target's complete R1CS assignment, the canonical BN128 input contract, and the predeclared property in the contracts file. Record each criterion separately as satisfied, unmet or unresolved. A candidate with any unmet criterion is not a valid finding; an unresolved criterion remains unconfirmed. Unexpected fixed-variant candidates receive the same review and are reported even if they reveal another behavior. Public labels and static diagnostics never count as backend discoveries.

Count a cause once across repeat artifacts and variants. Report backend statuses, validated causes, failed or unresolved reviews, target order, and completion-time upper bounds. Do not present this single development run as a strategy comparison or as evidence about large project callers. Do not change ranking weights, the set, budget or seed after seeing the outcome. A later held-out evaluation needs fresh independent cases and a separately frozen comparison protocol.
