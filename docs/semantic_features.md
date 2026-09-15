**Semantic feature adapter: implemented contract and limits**

`src/semantic.rs` imports existing Circomspect diagnostics. It does not add a Circom analyzer, replace zkFuzz, or treat warnings as confirmed defects. The five required features are frozen existence indicators: when every required analysis is complete, `risk = sum(feature.value)` with each value either 0 or 1. Execution cost is not part of this score. This is a development hypothesis, not a published Circom vulnerability probability.

| Required rule ID | Verified analyzer name | Meaning used here |
|---|---|---|
| CS0013 | unnecessary-signal-assignment | A single-arrow assignment has a quadratic RHS that could use `<==`. Separate constraints may already make it correct. |
| CS0014 | unconstrained-less-than | The analyzer did not establish its supported input-range check for a `LessThan` use. |
| CS0015 | unconstrained-division | The analyzer did not find its supported `IsZero`-based nonzero constraint for the divisor. |
| CS0017 | under-constrained-signal | An intermediate signal has fewer than two separate constraint occurrences under the analyzer's approximation; constraints in loops receive special handling. |
| CS0018 | unused-output-signal | A component output is not accessed as expected, subject to the analyzer's allowlist and access approximation. |

The adapter deliberately does not score the generic CS0005 single-arrow review diagnostic, general arithmetic/comparison lint, or assertion counts. The verified release has no dedicated rule establishing the requested distinction between compile-time parameter assertions and signal-dependent assertions. That candidate is stored as `unsupported`, outside the required feature set. Tests preserve this limitation rather than inventing assertion precision.

The rule IDs and pass behavior were checked against official Circomspect revision `ece9efe0a21e6c422a43ab6f2e1c0ce99678013b`, CLI package version `0.9.0`:

- [Rule IDs and names](https://github.com/trailofbits/circomspect/blob/ece9efe0a21e6c422a43ab6f2e1c0ce99678013b/program_structure/src/program_library/report_code.rs)
- [Analysis definitions](https://github.com/trailofbits/circomspect/blob/ece9efe0a21e6c422a43ab6f2e1c0ce99678013b/doc/analysis_passes.md)
- [CLI filtering and exit status](https://github.com/trailofbits/circomspect/blob/ece9efe0a21e6c422a43ab6f2e1c0ce99678013b/cli/src/main.rs)
- [SARIF serialization](https://github.com/trailofbits/circomspect/blob/ece9efe0a21e6c422a43ab6f2e1c0ce99678013b/program_structure/src/utils/sarif_conversion.rs)

**Attribution and missing analysis**

The API takes caller-validated `SourceScope` entries: source path, template name, and inclusive source line range. The caller must establish that these definitions belong to the concrete target's reachable dependency closure. The adapter rejects empty, invalid, and overlapping scopes. It cannot infer reachability or validate caller assumptions.

Every distinct scope source is explicitly passed to Circomspect. This matters because this CLI analyzes user-supplied files and filters diagnostics to them: running only a short wrapper would omit included template warnings. A warning contributes only if its primary source region is fully inside a validated reachable scope. Warnings in uncalled templates in the same file are excluded. Related locations and labels preserve the analyzer's signal/component/constraint evidence; they do not independently establish ownership.

Within one target, identical rule/message/primary-location diagnostics are deduplicated. Multiple different warnings of one rule still produce one risk point. `warning_count` counts deduplicated diagnostics from the same five selected rules, allowing warning-first to differ from rule-existence risk-only. All other diagnostics remain in raw SARIF. If two targets share a reachable definition, its warning can appear in both reports; unique-defect counting remains a separate experiment concern.

Circomspect analyzes template definitions, without substituting a concrete target's arguments. The report explicitly records this abstraction. Warnings can be conservative for some arguments; the adapter does not claim instance-specific proofs or path-sensitive feasibility. Scopes with unsupported reachability must be excluded upstream, rather than attributed using whole-file membership.

SARIF alone does not establish analysis completion. Exit code 1 means one or more diagnostics were emitted, including ordinary warnings. This release provides neither `--version` nor tool-version/completion metadata inside SARIF. The adapter records supplied package/revision provenance and requires the verified contract, normal exit 0/1, final CLI summary, per-template analysis and successful CFG-lifting log evidence, a valid SARIF report, no reported errors, and no observed internal lifting/propagation failure. Health logging is enabled explicitly. Unknown revisions are not treated as compatible silently.

An observed failure conservatively makes every required feature `unknown` with `value: null` and `risk_score: null`; observed warning evidence is retained. Missing SARIF, missing health logs, external timeout, unavailable binary, malformed locations, and analyzer errors do not become zero risk. “Complete, no warnings” means no warning from these rules under this analyzer's approximation, never “safe circuit.” Some analyzer limitations are inherent and cannot be certified away by its exit status.

**Local build and verification**

The analyzer was built in the ignored `.external` directory without global installation:

```sh
git clone https://github.com/trailofbits/circomspect.git .external/circomspect
git -C .external/circomspect checkout ece9efe0a21e6c422a43ab6f2e1c0ce99678013b
cargo build --locked --release --manifest-path .external/circomspect/Cargo.toml -p circomspect
```

The build used rustc `1.94.1` and cargo `1.94.1` on the development machine. The official dependency emits an unused-return-value warning, and Cargo reports a future-compatibility warning in `num-bigint-dig 0.8.4`; no analyzer source was changed. Actual version provenance comes from the checkout's `cli/Cargo.toml` and git revision, not an invented `--version` invocation.

Ordinary tests import real recorded outputs under `tests/fixtures/semantic`. `capture.json` documents the actual command and exit status. Only the fixture directory prefix was replaced by `__FIXTURE_ROOT__` for relocation; test loading restores it. Sources, rule IDs, messages, and health log content otherwise remain analyzer output. These are unit fixtures, not real-project corpus entries or performance measurements.

```sh
cargo test --offline --test semantic_test
cargo test --offline --test semantic_test -- --ignored
```

The second command explicitly runs the local analyzer. It requires the pinned binary at `.external/circomspect/target/release/circomspect`. The real fixtures verify that adding supported range/nonzero constraints suppresses the corresponding warnings, unreachable definitions are not attributed, multiple warnings remain one rule-existence point, and assertion classification stays unsupported. Mutated copies of captured output exercise duplicated reports and incomplete/corrupt analysis handling. No test result establishes improved bug-discovery performance.
