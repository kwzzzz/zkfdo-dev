#!/usr/bin/env python3
"""Execute a frozen N6-A2 phase queue with the Policy-A v3 state machine."""

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_n6_b_queue as queue  # noqa: E402


def load_queue(path: Path):
    value = json.loads(path.read_text())
    value["_path"] = str(path.resolve())
    if value.get("schema_version") != 2 or value.get("status") != "preflight_pending":
        raise ValueError("queue is not a frozen N6-A2 phase queue")
    units = value.get("units", [])
    if not units or len(units) != value.get("unit_count"):
        raise ValueError("N6-A2 queue unit denominator mismatch")
    if value.get("concurrency") != 3:
        raise ValueError("N6-A2 concurrency must be 3")
    if value.get("preflight_spec_count") != len(units) * 2:
        raise ValueError("N6-A2 preflight denominator mismatch")
    if value.get("phase") not in {"A-D", "A-Q"}:
        raise ValueError("N6-A2 queue phase must be A-D or A-Q")
    return value


queue.load_queue = load_queue


if __name__ == "__main__":
    if "--action" in sys.argv:
        index = sys.argv.index("--action")
        action = sys.argv[index + 1] if index + 1 < len(sys.argv) else None
    else:
        action = None
    if action not in {None, "execute"}:
        raise SystemExit("N6-A2 phase queues are execute-only; preflight is already frozen")
    raise SystemExit(queue.main())
