#!/usr/bin/env python3
"""Construct a seeded honest Banyan input from its recorded A source only.

The two revisions independently use the same ordinary interior tree position:
1 <= depth < leaf_depth - 1 and 4 <= leaf_depth <= 64. No candidate, request,
ledger, prior input, or J result is read. --check invokes the existing checker
with only its external-cache and unrelated-run guards adapted to this A run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a-remeasure-2026-10-25.noindex"
MANIFEST = ROOT / "runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json"
MANIFEST_SHA256 = "f059fe7d6aa21234168b7867537f069ec980c45c2c025184cbc12e169f687441"
REFERENCE = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
REFERENCE_SHA256 = "18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508"
SEED = "20261025-a-banyan"
REVISIONS = {
    "banyan-vulnerable": (
        "76b83107eb00c8f886bde82172eaa3cdd5d57f25",
        "f7d04495f0bf186ab2376e860ce0fc2468087f32b0b80d6a0f2d3d6f0bd28f52",
    ),
    "banyan-fixed": (
        "e37eb56e29b304024055f3d0a1681e6f22132ecc",
        "33fcc0ce24971e32de2a60d84f4220356ab7a6985e6b7c9c4be9051c0f96bb4d",
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def check_source(revision: str) -> dict:
    require(digest(MANIFEST) == MANIFEST_SHA256, "recorded A manifest changed")
    require(digest(REFERENCE) == REFERENCE_SHA256, "recorded A R1CS index changed")
    rows = [row for row in json.loads(MANIFEST.read_text())["rows"]
            if row["identifier"] == revision]
    require(len(rows) == 1, "revision missing or duplicated")
    row = rows[0]
    commit, source_sha = REVISIONS[revision]
    require(row["revision_commit"] == commit, "recorded revision commit changed")
    sources = []
    for relative, expected in (
        ("circuit.circom", row["entrypoint_sha256"]),
        ("source/circuits/blake3_nova.circom", source_sha),
    ):
        staged = Path(row["project_root"]) / relative
        recorded = Path(row["source_project_path"]) / relative
        require(digest(staged) == digest(recorded) == expected,
                f"recorded/staged source mismatch: {relative}")
        sources.append({"path": str(staged), "recorded_source_path": str(recorded),
                        "sha256": expected})
    reference = json.loads(REFERENCE.read_text())["revisions"][revision]
    return {"revision_commit": commit, "sources": sources,
            "expected_r1cs_sha256": reference["compile"]["r1cs_sha256"]}


def construct() -> dict[str, int]:
    def offset(label: str, span: int) -> int:
        value = hashlib.sha256(f"{SEED}:{label}".encode()).digest()
        return int.from_bytes(value[:8], "big") % span

    leaf_depth = 4 + offset("leaf_depth", 61)
    return {"depth": 1 + offset("depth", leaf_depth - 2), "leaf_depth": leaf_depth}


def local_path(path: Path) -> Path:
    resolved = path.resolve()
    require(resolved.is_relative_to(RUN.resolve()) and resolved != RUN.resolve(),
            "output and cache must be strictly inside the new A run root")
    return resolved


def run_checker(revision: str, output_root: Path, cache: Path) -> int:
    import n6_b6_check_constructed_input as checker

    def local_guard() -> None:
        # The inherited guard reads unrelated B state. This A-only invocation
        # instead enforces the authorized local paths and touches no processes.
        local_path(output_root)
        local_path(cache)

    arguments = [str(Path(checker.__file__)), "--scope", "A", "--identifier", revision,
                 "--input", str(output_root / revision / "input.json"),
                 "--output-root", str(output_root), "--cache-root", str(cache),
                 "--manifest", str(MANIFEST), "--r1cs-map", str(REFERENCE)]
    # '/' is the real filesystem mount containing this repository. No checker
    # compile, witness, Rust, snarkjs, or R1CS-hash validation is replaced.
    with patch.object(checker, "MOUNT", Path("/")), \
            patch.object(checker, "check_heavy_idle", local_guard), \
            patch.object(sys, "argv", arguments), \
            patch.dict(os.environ, {"CARGO_NET_OFFLINE": "true"}):
        return checker.main()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", choices=tuple(REVISIONS), required=True)
    parser.add_argument("--output-root", type=Path, default=RUN / "inputs")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output_root = local_path(args.output_root)
    cache = local_path(RUN / "cache/input-checks")
    source = check_source(args.revision)
    folder = output_root / args.revision
    folder.mkdir(parents=True, exist_ok=False)
    input_path = folder / "input.json"
    with input_path.open("x") as output:
        output.write(json.dumps(construct(), sort_keys=True, separators=(",", ":")) + "\n")
    record = {
        "schema": "n6-a-banyan-constructed-input-v1", "revision_id": args.revision,
        "seed": SEED, "script_sha256": digest(Path(__file__)), **source,
        "manifest_path": str(MANIFEST), "manifest_sha256": MANIFEST_SHA256,
        "r1cs_reference_path": str(REFERENCE), "r1cs_reference_sha256": REFERENCE_SHA256,
        "input_path": str(input_path), "input_sha256": digest(input_path),
        "method": "SHA-256 offsets; 4 <= leaf_depth <= 64; 1 <= depth < leaf_depth - 1",
        "source_rationale": "CheckDepth inputs and max-depth-64 comment; ordinary interior parent",
        "candidate_request_ledger_j_reads": False,
        "checker_adapter": {
            "script": "scripts/n6_b6_check_constructed_input.py", "scope": "A",
            "changes": ["MOUNT=/", "unrelated-run guard replaced by local-path guard"],
            "validation_functions_unchanged": True, "cargo_offline": True,
            "cache_root": str(cache),
        },
    }
    with (folder / "construction.json").open("x") as output:
        json.dump(record, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps({"revision": args.revision, "input_path": str(input_path),
                      "input_sha256": record["input_sha256"]}, sort_keys=True), flush=True)
    return run_checker(args.revision, output_root, cache) if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
