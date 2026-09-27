# Common candidate-review regression

This directory contains deterministic schema-1 review specs and requests for the preserved
controlled-v1.1 Subtract, controlled-v2 Banyan, and controlled-v3 Decoder evidence. Raw
assignments remain under ignored `runs/`; generated reports contain paths, hashes, verdicts,
constraint indices, and value-free notes only.

`build_inputs.py` rebuilds the specs, requests, source-closure manifests, and review-engine
source manifest from the frozen records. Each request is run into a new result directory with
`zkfDO experiment review`. Existing reports and verdict files are never overwritten.

The required substantive regression is:

| Case | Plan/outcome pairs | Execution rows | Candidates | Expected review |
|---|---:|---:|---:|---|
| v1.1 Subtract | 36 | 72 | 36 | 36 validated and attributed |
| v2 Banyan | 36 | 144 | 36 | 36 validated and attributed |
| v3 Decoder | 1 | 4 | 1 | 1 validated and attributed |

Each pair gets a schema-2 confirmation file and a real evaluator output. Campaign summaries
deduplicate the repeated candidates to one root cause per case.

The final 2026-09-27 regeneration used the source snapshot recorded by
`provenance/engine-source-manifest.json`; the report `source_revision` stores that manifest's full
SHA-256 rather than claiming that the then-uncommitted worktree was an existing Git commit. The
reports were produced by a copy of the executable preserved at the ignored path
`runs/candidate-review-regression-2026-09-27/zkfDO` (not the mutable `target/` build output), and
each report binds that copy and the canonical Python predicate runner by path and raw SHA-256.
The runner hash is part of the semantic-result digest.

This regeneration followed a fix that made the tests runnable in a clean checkout: two engine test
and robustness edits changed the snapshot, and the semantic content of all three reports (status,
summary, inventory, execution rows, reviews, adapters, request and spec bindings) is identical to
the earlier same-day run. Only the four engine provenance fields changed.

`verify_regression.py` checks all 73 plan/outcome pairs against the frozen reviews and evaluator
records, all 220 execution rows (including 147 non-candidate rows), confirmation contents,
campaign root-cause deduplication, internal path/hash links, exact result-file inventory, and the
absence of raw assignment keys from every generated JSON file. It has two modes:

- **Tracked evidence (default).** Every reference that resolves to a Git-tracked file must exist
  with its recorded hash. References to ignored or external local evidence (raw candidates,
  compiled R1CS/SYM, the preserved executable, the predicate interpreter) are counted in
  `local_references_skipped` and not opened. The recorded engine snapshot is not compared with the
  working tree, which may have moved on. This is the mode that `cargo test` and CI run.
- **Local evidence (`--require-local-evidence`).** Additionally every skipped reference must exist
  with its recorded hash, the working tree must equal the recorded engine snapshot, and the
  candidate adapter hash is recomputed from `engine.rs`. This only passes on a machine that holds
  the preserved raw evidence, at the recorded source snapshot.

Run the checks with:

```sh
python3 reports/candidate-review-regression-2026-09-27/build_inputs.py
python3 reports/candidate-review-regression-2026-09-27/verify_regression.py
python3 reports/candidate-review-regression-2026-09-27/verify_regression.py --require-local-evidence
```

The results were regenerated into fresh directories with:

```sh
R=reports/candidate-review-regression-2026-09-27
M=$R/provenance/engine-source-manifest.json
for c in v1.1 v2 v3; do
  runs/candidate-review-regression-2026-09-27/zkfDO experiment review \
    --request $R/inputs/$c-request.json --output $R/results/$c \
    --source-revision "worktree-engine-manifest:$(shasum -a 256 $M | cut -d' ' -f1)" \
    --engine-source-manifest $M
done
```

Tests that need the gitignored evidence are marked `#[ignore]` and do not run in CI:
`cargo test --lib -- --ignored`, `cargo test --test candidate_review_backend_failure_test -- --ignored`,
and `cargo test --test candidate_review_schema_test -- --ignored`. Moving the backend boundary tests
onto synthetic fixtures, so that CI covers them, is a follow-up.
