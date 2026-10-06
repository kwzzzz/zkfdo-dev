# Third-Party Notices

zkfDO's own source code is licensed under the MIT License (see [LICENSE](LICENSE)).

This repository also contains copies of third-party Circom circuits, patches and dataset metadata. They are kept unchanged as research evidence: frozen datasets, preparation snapshots and review records. **These files are not covered by zkfDO's MIT License.** Each keeps the license of its upstream project, listed below. License texts are in [third_party/licenses/](third_party/licenses/).

The frozen directories were not edited when this notice was added on 2026-10-06. Where a copied file carries its own license header, that header applies.

## Redistributed third-party content

| Upstream | Revisions used | License | Where it appears here | License text |
|---|---|---|---|---|
| [iden3/circomlib](https://github.com/iden3/circomlib) | `cff5ab62…`, `9d2918e5…`, plus copies vendored by the projects below | GPL-3.0-or-later, per the header of each file (Copyright 2018 0KIMS association). The pinned revisions have no top-level license file; the current upstream `LICENSE` is LGPL-3.0. | `datasets/controlled-v3/circomlib-decoder/`; every `circomlib/`, `node_modules/circomlib/` and `dependencies/circomlib/` directory under `datasets/` and `reports/controlled-v2-preparation-2026-09-20/evidence/`; `reports/dev-injection-2026-09-27/circomlib-o4-num2bits-strict/single.diff` | [GPL-3.0.txt](third_party/licenses/GPL-3.0.txt) |
| [tangle-network/protocol-solidity](https://github.com/tangle-network/protocol-solidity) | `848d073b…`, `eeb4fc7a…` | MIT or Apache-2.0 (both files present at these revisions). Copyright (c) 2023 Webb Technologies Ltd. | `datasets/controlled-v2/tangle-set-membership/`; the matching targets in `reports/controlled-v2-preparation-2026-09-20/evidence/` | [MIT](third_party/licenses/tangle-network_protocol-solidity_LICENSE.MIT.txt), [Apache-2.0](third_party/licenses/tangle-network_protocol-solidity_LICENSE.Apache-2.0.txt) |
| [banyancomputer/hot-proofs-blake3-circom](https://github.com/banyancomputer/hot-proofs-blake3-circom) | `76b83107…`, `e37eb56e…` | MIT. Copyright 2025 Banyan Storage Inc. | `datasets/controlled-v2/banyan-check-depth/`; the matching targets in `reports/controlled-v2-preparation-2026-09-20/evidence/` | [LICENSE.md](third_party/licenses/banyancomputer_hot-proofs-blake3-circom_LICENSE.md.txt) |
| [Unirep/Unirep](https://github.com/Unirep/Unirep) | `0985a28c…`, `3348caa3…` | MIT. Copyright (c) 2022 Ethereum Foundation. | `datasets/controlled-v3/unirep-big-less-than/` | [LICENSE](third_party/licenses/Unirep_Unirep_LICENSE.txt) |
| [0xbok/circom-bigint](https://github.com/0xbok/circom-bigint) | as recorded in the run's provenance | GPL-3.0 | `reports/dev-injection-2026-09-27/bigint-o3-split/single.diff` | [GPL-3.0.txt](third_party/licenses/GPL-3.0.txt) |
| [zksecurity/zkbugs](https://github.com/zksecurity/zkbugs) | `a0eed744…` (local checkout) | MIT. Copyright (c) 2024 ZkSecurity. | `experiments/evidence/xorwords-2026-09-15/fixture/zkbugs_config.json`, `zkbugs_vars.sh`, already accompanied by `LICENSE.zkbugs` | [LICENSE](third_party/licenses/zksecurity_zkbugs_LICENSE.txt) |

The license texts were downloaded from each upstream repository at the revisions above (zkbugs and circom-bigint from their default branch). For tangle, Banyan and Unirep, the vulnerable and fixed revisions carry byte-identical license files.

## Content with no license grant

The following upstream repositories publish no license file, either at the revisions used or on their default branch (checked 2026-10-06). Without a license, the authors keep all rights. The copies below are kept for private research review only. They **must not** be included in a public release unless the authors grant permission. The public artifact should refer to them by repository URL and commit hash instead.

| Upstream | Revisions used | Where it appears here |
|---|---|---|
| [inference-labs-inc/subnet-2-circom](https://github.com/inference-labs-inc/subnet-2-circom) | `d310309c…`, `b8f92bde…` and commits of PR #2 | `datasets/controlled-v1/subtract/`; `reports/controlled-v1-static-regression/evidence/preparation/**/sources/`; `single.diff` and `normalization.diff` under `reports/dev-injection-2026-09-27/inference-*` and `reports/dev-ranking-pilot-2026-09-27/` |
| [reclaim-1/circom-chacha20](https://github.com/reclaim-1/circom-chacha20) (zkbugs entry `reclaimprotocol/circom-chacha20`; its `package.json` declares no license either) | as recorded in each report | `experiments/evidence/xorwords-2026-09-15/fixture/*.circom`; `reports/add32bits-component-check-2026-09-15/component-check/`; `reports/rotateleft-fixture-fidelity-2026-09-15/component-check/`; `reports/rotateleft-candidate-check-2026-09-17/component-check/` |

## Code written for this project

- Test fixtures under `tests/fixtures/` are synthetic circuits written for this project. Some define small templates named `LessThan` or `Num2Bits`. They follow the standard comparator and bit-decomposition construction so that zkFuzz's `LessThan` oracle applies. They are not copies of circomlib files.
- Top-level wrapper circuits that the study generated (for example a dataset's `project/circuit.circom` that instantiates one template) are zkfDO output.

## Tools used but not redistributed

These tools are run as separate programs. Their source code is not included in or linked into zkfDO.

| Tool | License |
|---|---|
| [zkFuzz](https://github.com/Koukyosyumei/zkFuzz) (revision `072bf1f`) | GPL-3.0 |
| [circom](https://github.com/iden3/circom) 2.2.3 | GPL-3.0 |
| [snarkjs](https://github.com/iden3/snarkjs) | GPL-3.0 |
| [z3](https://github.com/Z3Prover/z3) | MIT |
| [circomspect](https://github.com/trailofbits/circomspect) | GPL-3.0 |

zkfDO's Rust dependencies are listed in `Cargo.toml` and `Cargo.lock`. Their licenses are those published on crates.io.

License status was checked from the upstream repositories on 2026-10-06. This file records provenance; it is not legal advice.
