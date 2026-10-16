#!/usr/bin/env python3
"""N6-A1b preflight-only wrapper over the v3 queue state machine."""

from pathlib import Path
import json
import sys
import shutil

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


def load_or_create_preflight_summary(value, output):
    path = output / "preflight-all.json"
    queue_hash = queue.sha256(Path(value["_path"]))
    if path.is_file():
        summary = json.loads(path.read_text())
        if summary.get("queue_sha256") != queue_hash:
            raise ValueError("queue changed since N6-A1b preflight-all began")
        return path, summary
    summary = {
        "schema_version": 1, "kind": "n6_a1b_preflight_all",
        "status": "running", "queue": str(Path(value["_path"]).relative_to(queue.ROOT)),
        "queue_sha256": queue_hash,
        "required_spec_count": value["preflight_spec_count"],
        "started_at": queue.now(),
        "disk_free_before_bytes": shutil.disk_usage(output).free,
        "results": {},
    }
    queue.atomic_json(path, summary)
    return path, summary


queue.load_queue = load_queue
queue.load_or_create_preflight_summary = load_or_create_preflight_summary

if __name__ == "__main__":
    if "--action" in sys.argv:
        index = sys.argv.index("--action")
        action = sys.argv[index + 1] if index + 1 < len(sys.argv) else None
    else:
        action = None
    if action not in {None, "preflight-all"}:
        raise SystemExit("N6-A1b runner is preflight-only; execute is disabled")
    raise SystemExit(queue.main())
