# Experiments

Use this directory for reproducible experiment notes and scripts.

Generated outputs belong in `runs/` or `reports/generated/`, which are ignored by git.

Each `zkfDO run` execution creates a directory under `runs/<run-id>/` containing:

- `result.json`: timing, status, exit code, seed, and last observed generation
- `stdout.log`: raw zkFuzz standard output
- `stderr.log`: raw zkFuzz standard error

Each `zkfDO schedule` execution creates a uniform-baseline experiment:

```text
runs/<experiment-id>/
  summary.json
  runs/<target-run-id>/
    result.json
    stdout.log
    stderr.log
```

The explicit static-ranking workflow writes prepared corpora, immutable plans, ordered
scheduler summaries, outcomes, and evaluations as described in
[`docs/static_ranking_experiment.md`](../docs/static_ranking_experiment.md). Small checked-in
JSON files in this directory summarize completed, bounded validation runs; bulk raw generated
logs remain under ignored `runs/`. The explicitly requested, reviewed minimal case archive
under `evidence/` is an exception for sharing the existing XorWords evidence.

- [`dev10-preparation-2026-09-15.json`](dev10-preparation-2026-09-15.json) records preparation, plans, the synthetic control, and the initial dev3 connection smoke.
- [`dev3-ranking-pilot-2026-09-15.json`](dev3-ranking-pilot-2026-09-15.json) validates and summarizes 49 repeated strategy executions. Its timing table concerns unconfirmed backend candidates and does not establish confirmed-defect performance.
- [`xorwords-case-study-2026-09-15.md`](xorwords-case-study-2026-09-15.md) traces one existing dev3 `XorWords` counterexample to its direct fixture and audit context; the supported scope is `wrapper-only`.
- [`evidence/xorwords-2026-09-15/`](evidence/xorwords-2026-09-15/README.md) preserves that case's small raw evidence set, licensed direct fixture, pinned provenance, checksums, and an offline arithmetic verifier.
