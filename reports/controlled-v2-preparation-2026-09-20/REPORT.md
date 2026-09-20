# controlled-v2 held-out preparation

Date: 2026-09-20

Status before backend execution: **material and protocol frozen; 0 strategy executions, 0 target attempts, 0 reviewed candidates**.

## Selected independent causes

| Pair | Public vulnerable/fixed relationship | Frozen targets | Preparation result |
|---|---|---|---|
| Tangle `SetMembership(3)` | vulnerable `848d073…` is an ancestor of fix `eeb4fc7…`; the named change initializes the product with one | vulnerable and fixed comparator | both compile; risk 0; 6 constraints |
| Banyan `CheckDepth` | vulnerable `76b8310…` is a parent/ancestor of merge fix `e37eb56…`; the named change adds 8-bit input constraints | vulnerable and fixed comparator | both compile; risk 1; 29 and 47 constraints |

The cases are different projects and different cause classes. Vulnerable and fixed variants in a pair share one `root_cause_id`; they are not independent defects. Public metadata and static scores are not execution discoveries.

The exact revisions, blobs, SHA-256 values, component contracts, input preconditions and predeclared properties are in `datasets/contracts.controlled-v2.json`. The four executable targets are in `datasets/manifest.controlled-v2.json`.

## Candidate survey decisions made before execution

| Candidate | Decision | Reason |
|---|---|---|
| controlled-v1.1 Subtract | excluded | observed development positive control |
| dev3 Reclaim family | excluded | previously used development/validation causes and variants |
| SIV `ExtractStringFromPoint` | excluded | pinned fix and metadata disagree on `RShift1` parameter; documented encoder domain does not resolve the mismatch |
| Aptos `Base64DecodedLength` | excluded | frozen inspection is incomplete for the source syntax and frozen zkFuzz rejects the fixed pragma |
| Telepathy `ArrayXOR` | excluded | frozen zkfDO parser does not support the fixed component-array construction |
| zk-email `FpMul` | not selected | the two-case minimum was already satisfied; the more complex modular-arithmetic contract was not expanded |

No zkFuzz outcome or target-order result was used in these decisions.

## Frozen comparison

- Protocol: `docs/controlled_v2_execution_protocol.md`, SHA-256 `4835c9bb340e34a436c71c4e86a91e6ff2c17f9dbd05747852d635ef0f894b76`.
- Manifest: SHA-256 `758180ae4827f53adbaa35d8075566a3f3eb3a090be221dbd5183527657c70b7`.
- Contracts: SHA-256 `a9f0d595dfee347f0d54a9c2b253ea4da84ae74c76d39cb108ad1151dd2152a0`.
- Accepted prepared record: SHA-256 `967135b38000ee09b1d82aa15cf1bbbdb354fbecf437692e77a9e440f99dd504`; all four targets are eligible.
- Campaign driver: `runs/controlled-v2/frozen-tools/campaign_driver.py`, SHA-256 `77176be1e0479454adc11c71baf442fbbe20bc085474090f049f4980ade4b6fb`.
- The environment/hash preflight passed on the stated hardware and current comparison environment.
- The plan is 12 paired blocks, 36 strategy executions and 144 target attempts. Target limit is 30 seconds and strategy total limit is 120 seconds.

The preflight plans preserve distinct risk-only and small-first orders and the twelve frozen random orders. No backend was invoked during preparation. Earlier rejected preparation directories and logs are retained as evidence of eligibility failures; only the accepted prepared record named by the protocol is executable evidence.

This preparation establishes eligibility and a frozen comparison. It does not establish that zkFuzz can rediscover either cause or that one strategy is better.
