#!/usr/bin/env python3
"""Standalone N6 v4 supervisor: execute frozen A then B queues and write a summary."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def append_event(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()


def verify_pin(row: dict[str, Any]) -> Path:
    path = ROOT / row["path"]
    if not path.is_file() or sha256(path) != row["sha256"]:
        raise ValueError(f"pinned file changed: {row['path']}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "prepared_not_executed" or manifest.get("order") != ["A", "B"]:
        raise ValueError("manifest is not the frozen A-then-B v4 execution manifest")
    run_root = manifest_path.parent
    events_path = ROOT / manifest["outputs"]["events"]
    summary_path = ROOT / manifest["outputs"]["summary"]
    if summary_path.exists() or events_path.exists():
        raise ValueError("execution output already exists; refusing to overwrite it")
    summary = {
        "schema_version": 1,
        "kind": "n6_v4_standalone_execution_summary",
        "status": "running",
        "started_at": now(),
        "manifest": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": sha256(manifest_path),
        "phases": {},
        "candidate_contents_opened": False,
        "j_review_performed": False,
    }
    atomic_json(summary_path, summary)
    exit_code = 1
    try:
        queue_runner = verify_pin(manifest["queue_runner"])
        verify_pin(manifest["runner"])
        supervisor = ROOT / manifest["supervisor"]["path"]
        if supervisor.resolve() != Path(__file__).resolve() or sha256(supervisor) != manifest[
                "supervisor"]["sha256"]:
            raise ValueError("supervisor changed after manifest creation")
        for branch in manifest["order"]:
            queue = verify_pin(manifest["queues"][branch])
            output = ROOT / manifest["outputs"][branch]
            if output.exists():
                raise ValueError(f"phase output already exists: {output.relative_to(ROOT)}")
            event = {"event": "phase_start", "branch": branch, "at": now(),
                     "queue": str(queue.relative_to(ROOT)), "output": str(output.relative_to(ROOT))}
            append_event(events_path, event)
            summary["phases"][branch] = {"status": "running", "started_at": event["at"]}
            atomic_json(summary_path, summary)
            completed = subprocess.run(
                [sys.executable, str(queue_runner), "--queue", str(queue),
                 "--output", str(output), "--action", "execute"],
                stdin=subprocess.DEVNULL,
            )
            gate_path = output / "start-gate.json"
            gate_status = None
            if gate_path.is_file():
                gate_status = json.loads(gate_path.read_text()).get("status")
            queue_summary = output / "queue-summary.json"
            phase = {
                "status": "completed" if completed.returncode == 0 else (
                    "start_gate_failed" if gate_status == "failed" else "failed"),
                "finished_at": now(),
                "exit_code": completed.returncode,
                "start_gate": str(gate_path.relative_to(ROOT)) if gate_path.is_file() else None,
                "state": str((output / "state.json").relative_to(ROOT))
                if (output / "state.json").is_file() else None,
                "queue_summary": str(queue_summary.relative_to(ROOT))
                if queue_summary.is_file() else None,
                "queue_summary_sha256": sha256(queue_summary)
                if queue_summary.is_file() else None,
            }
            summary["phases"][branch] = phase
            append_event(events_path, {"event": "phase_end", "branch": branch,
                                       "at": phase["finished_at"], **phase})
            atomic_json(summary_path, summary)
            if completed.returncode != 0:
                summary["status"] = phase["status"]
                summary["stopped_after_branch"] = branch
                exit_code = completed.returncode
                break
        else:
            summary["status"] = "completed"
            exit_code = 0
    except BaseException as error:
        summary["status"] = "supervisor_error"
        summary["error"] = {"type": type(error).__name__, "message": str(error),
                            "traceback": traceback.format_exc()}
        append_event(events_path, {"event": "supervisor_error", "at": now(),
                                   "type": type(error).__name__, "message": str(error)})
        raise
    finally:
        summary["finished_at"] = now()
        summary["exit_code"] = exit_code
        summary["run_root"] = str(run_root.relative_to(ROOT))
        atomic_json(summary_path, summary)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
