#!/usr/bin/env python3
"""Recheck frozen B queue, 60 specs, preflight proof, and pinned tools."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_n6_v4_3_queue as queue_runner  # noqa: E402
QUEUE = ROOT / "runs/n6-a2b-2026-10-08.noindex/queue-b-v4.json"
OUTPUT = ROOT / "runs/n6-b2-2026-10-09.noindex/fixed-input-check.json"
EXPECTED = {
    "queue": (QUEUE, "d39e821fd65cea1852ad6a20b88ab59e03a7c363be9022224221986716161600"),
    "preflight_reuse": (ROOT / "runs/n6-a2b-2026-10-08.noindex/preflight-reuse-b-v4.json",
                        "4af095fcd9f7370e01cf0fe48fa32d2164a19b2f98273859355f0c7d284be030"),
    "engine_v4": (ROOT / "scripts/run_policy_a_engine_v4.py",
                  "ff36c6db0a7475064c388a9bd0b0a1845863329f1fe2e2b40f06dec641fa9451"),
    "zkfuzz": (Path("/Users/miiz/.cargo/bin/zkfuzz"),
               "ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd"),
    "circom": (Path("/Users/miiz/.cargo/bin/circom"),
               "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    tools = {}
    for label, (path, expected) in EXPECTED.items():
        actual = sha256(path)
        tools[label] = {"path": str(path), "sha256": actual,
                        "expected_sha256": expected, "matches": actual == expected}
    if not all(row["matches"] for row in tools.values()):
        raise ValueError("frozen B input SHA-256 mismatch")
    queue = queue_runner.load_queue(QUEUE)
    preflight = queue_runner.load_preflight_rows(queue)
    if (len(queue["units"]) != 30 or queue["spec_count"] != 60
            or len(preflight) != 60):
        raise ValueError("B queue or preflight denominator mismatch")
    specs = []
    for unit in queue["units"]:
        for method, key in (("W", "whole_spec"), ("S", "split_spec")):
            path = ROOT / unit[key]
            actual = sha256(path)
            expected = unit[f"{key}_sha256"]
            if actual != expected:
                raise ValueError(f"B spec changed: {unit['unit_id']}:{method}")
            specs.append({"unit_id": unit["unit_id"], "method": method,
                          "path": str(path.relative_to(ROOT)), "sha256": actual})
    result = {"schema_version": 1, "status": "passed", "tools": tools,
              "unit_count": len(queue["units"]), "spec_count": len(specs),
              "preflight_row_count": len(preflight), "specs": specs}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "unit_count": result["unit_count"],
                      "spec_count": result["spec_count"],
                      "sha256": sha256(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
