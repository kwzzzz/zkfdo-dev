#!/usr/bin/env python3
"""N6-A queue wrapper with the same v3 preflight/execute state machine as N6-B."""

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_n6_b_queue as queue  # noqa: E402


def load_queue(path: Path):
    value = json.loads(path.read_text())
    value["_path"] = str(path.resolve())
    if value.get("schema_version") != 2 or value.get("status") != "preflight_pending":
        raise ValueError("queue is not a frozen N6-A preflight-pending queue")
    if len(value.get("units", [])) != value.get("unit_count") or value.get("concurrency") != 3:
        raise ValueError("N6-A queue unit count or concurrency mismatch")
    if value.get("preflight_spec_count") != len(value["units"]) * 2:
        raise ValueError("N6-A queue preflight denominator mismatch")
    return value


queue.load_queue = load_queue

if __name__ == "__main__":
    raise SystemExit(queue.main())
