# XorWords case evidence

This is the reviewed, minimal evidence archive for the
[case analysis](../../xorwords-case-study-2026-09-15.md). It preserves an existing dev3
connection-smoke result and the case study's retained reproduction. The supported
scope is **`wrapper-only`**; the declared original project revision and caller context
have not been verified. This archive is not a corpus addition or a benchmark run.
The 49-strategy pilot's raw runs remain outside this archive; this package supports
only the selected wrapper case. `datasets/manifest.dev10.json` records frozen
pre-execution metadata: its "Not reproduced by this work" and unverified fields
are historical preparation state, not an updated case conclusion.

## Contents and provenance

The candidate JSON, logs, result, settings, and fixture files are byte-for-byte
copies. Original filenames and paths are recorded in `provenance.json`. Absolute
paths inside the raw files are historical provenance and are not portable paths to
open on another machine. `SHA256SUMS` covers every file here except itself.

- `original/`: existing smoke candidate, stdout/stderr, and runner result.
- `reproduction/`: retained same-settings replay candidate and stdout/stderr.
- `mutation-settings.json`: seed `424242`; identical in both runs. The candidates
  also record the resolved mutation configuration and zkFuzz revision.
- `fixture/`: isolated zkbugs fixture and upstream metadata, **not a checkout of
  the declared Reclaim project commit**. `zkbugs_vars.sh` is retained as evidence
  of the entrypoint mapping, not as a runnable setup script at this new location.
- `verify.py`: offline checksum, JSON equivalence, and witness arithmetic checks.
  This does not compile a circuit or verify an original-project proof.

The fixture and metadata are from [zkbugs at
`a0eed744ba1a816acaa2fae597f4e79b4fd01aea`](https://github.com/zksecurity/zkbugs/tree/a0eed744ba1a816acaa2fae597f4e79b4fd01aea/dataset/circom/reclaimprotocol/circom-chacha20/zksecurity_Unsound_XOR_gadget).
They are redistributed under the upstream MIT license, copyright (c) 2024
ZkSecurity; the complete notice is in [`fixture/LICENSE.zkbugs`](fixture/LICENSE.zkbugs).
The audit PDF is referenced by pinned URL and checksum in `provenance.json` and is
not copied into this archive. Upstream metadata claims remain upstream claims;
in particular, `Compiled Original=true` does not establish project reachability.

## Offline verification

From the repository root:

```sh
python3 experiments/evidence/xorwords-2026-09-15/verify.py
```

For the exact historical replay command, see the case analysis. A portable replay
requires zkFuzz revision `072bf1fbbd1c9ecad58d4f6d2204c3b96e7fec17` and the copied
fixture/settings, and must write fresh outputs outside this immutable archive.

This curated archive is the explicitly requested exception for sharing this case;
bulk generated runs and compiled artifacts remain excluded from Git.
