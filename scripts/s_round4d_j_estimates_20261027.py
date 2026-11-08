#!/usr/bin/env python3
"""Per-revision J time and workspace estimates from a saved aq state copy."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "runs/s-round4-2026-10-27"
GIB = 2**30
INITIAL_PEAK = 60 * GIB


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def estimate(state: dict, revisions: list[str]) -> dict:
    workspace = {}
    for receipt in state.get("cleanup_receipts", []):
        binding = receipt.get("binding", {})
        key = (binding.get("engine"), binding.get("queue_order"), binding.get("request_sha256"))
        size = receipt.get("du_bytes")
        if (key[0] and type(key[1]) is int and key[2] and type(size) is int and size > 0 and
                binding.get("kind") not in ("caches", "stores", "request_remainder")):
            workspace[key] = max(workspace.get(key, 0), size)
    requests = state.get("engines", {}).get("v2.2", {}).get("requests", {})
    rows = {}
    for revision in revisions:
        completed = [r for r in requests.values() if r.get("revision") == revision and
                     r.get("status") == "completed" and type(r.get("wall_seconds")) in (int, float) and
                     r["wall_seconds"] > 0]
        times = [r["wall_seconds"] for r in completed]
        peaks = [workspace.get(("v2.2", r["queue_order"], r["request_sha256"])) for r in completed]
        present = [p for p in peaks if p is not None]
        rows[revision] = {"completed_requests": len(completed),
                          "wall_seconds_mean": mean(times) if times else None,
                          "wall_seconds_max": max(times) if times else None,
                          "expected_seconds_per_new_request": math.ceil(max(times)) if times else None,
                          "cap_seconds_per_new_request": 2 * math.ceil(max(times)) if times else None,
                          "request_workspace_peaks_recorded": len(present),
                          "request_workspace_peak_bytes": max(present) if present else None,
                          "image_required_before_retained_bytes": math.ceil(1.2 * max(
                              INITIAL_PEAK, state.get("observed_request_peak_bytes", 0),
                              max(present) if present else 0)) if times else None}
    return {"schema": "s-round4d-J-estimates-v2", "rows": rows,
            "basis": "completed v2.2 request wall_seconds maximum and request cleanup du_bytes in state copy; cap=2x expectation",
            "unmeasured_revisions": [r for r in revisions if not rows[r]["completed_requests"]]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    state_path = args.state.absolute()
    if not state_path.is_relative_to(ROUND) or "n6-a-remeasure-2026-10-25.noindex" in state_path.parts:
        raise ValueError("only explicit Round4 state copy allowed")
    state = json.loads(state_path.read_text())
    bundle = json.loads(args.bundle.read_text())
    result = estimate(state, bundle["revision_ids"])
    result["source"] = {"path": str(state_path), "sha256": digest(state_path)}
    output = args.output.absolute()
    if not output.is_relative_to(ROUND / "round4d") or output.exists():
        raise ValueError("new Round4d output required")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"measured": 15 - len(result["unmeasured_revisions"]),
                      "unmeasured": len(result["unmeasured_revisions"]),
                      "output": str(output)}))


if __name__ == "__main__":
    main()
