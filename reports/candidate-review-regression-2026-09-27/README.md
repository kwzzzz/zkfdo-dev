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

The 2026-09-27 final regeneration used the source snapshot recorded by
`provenance/engine-source-manifest.json`; the report `source_revision` stores that manifest's full
SHA-256 rather than claiming that the then-uncommitted worktree was an existing Git commit.
Each report also binds the canonical Python predicate runner path and raw executable SHA-256; the
verifier rechecks that reference and includes the runner hash in the semantic-result digest.
`verify_regression.py` checks all 73 plan/outcome pairs against the frozen reviews and evaluator
records, all 220 execution rows (including 147 non-candidate rows), confirmation contents,
campaign root-cause deduplication, internal path/hash links, exact result-file inventory, and the
absence of raw assignment keys from every generated JSON file.

Run the deterministic checks with:

```sh
python3 reports/candidate-review-regression-2026-09-27/build_inputs.py
python3 reports/candidate-review-regression-2026-09-27/verify_regression.py
```
