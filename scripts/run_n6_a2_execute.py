#!/usr/bin/env python3
"""Run frozen N6-A2 A-D and A-Q phase queues under one caffeinate session."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a2-2026-10-08"
EXECUTION_LIST = RUN / "execution-list-v1.json"
QUEUE_RUNNER = ROOT / "scripts/run_n6_a2_queue.py"
STATE = RUN / "controller-state.json"
MINIMUM_FREE_BYTES = 40 * 1024**3
SLEEP_PATTERN = re.compile(r"\bSleep\b.*\bEntering Sleep state\b", re.IGNORECASE)


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
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def pmset_log(path: Path) -> dict[str, Any]:
    started = time.monotonic_ns()
    result = subprocess.run(["pmset", "-g", "log"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    path.write_text(result.stdout)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "exit_code": result.returncode,
        "stderr": result.stderr.strip() or None,
        "wall_seconds": (time.monotonic_ns() - started) / 1e9,
        "line_count": len(result.stdout.splitlines()),
    }


def caffeinate_assertion() -> dict[str, Any]:
    result = subprocess.run(["pmset", "-g", "assertions"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid_marker = f"(pid {os.getpid()})"
    lines = result.stdout.splitlines()
    matching = []
    for index, line in enumerate(lines):
        if pid_marker in line and "caffeinate asserting on behalf of" in line:
            owner = lines[index - 1].strip() if index else ""
            matching.append({"owner": owner, "details": line.strip()})
    return {"exit_code": result.returncode, "pid": os.getpid(), "matching_lines": matching,
            "is_caffeinate": result.returncode == 0 and bool(matching),
            "stderr": result.stderr.strip() or None}


def new_sleep_lines(before: str, after: str) -> list[str]:
    if after.startswith(before):
        delta = after[len(before):]
        return [line for line in delta.splitlines() if SLEEP_PATTERN.search(line)]
    before_counts: dict[str, int] = {}
    for line in before.splitlines():
        before_counts[line] = before_counts.get(line, 0) + 1
    rows = []
    for line in after.splitlines():
        if before_counts.get(line, 0):
            before_counts[line] -= 1
        elif SLEEP_PATTERN.search(line):
            rows.append(line)
    return rows


def main() -> int:
    execution = json.loads(EXECUTION_LIST.read_text())
    if execution.get("ordering") != ["A-D", "A-Q"]:
        raise ValueError("N6-A2 phase order changed")
    if sha256(QUEUE_RUNNER) != execution["queue_runner"]["sha256"]:
        raise ValueError("queue runner hash changed")
    assertion = caffeinate_assertion()
    if not assertion["is_caffeinate"]:
        raise RuntimeError("execute must hold a caffeinate command-line power assertion")
    RUN.mkdir(parents=True, exist_ok=True)
    before_path = RUN / "pmset-before.log"
    after_path = RUN / "pmset-after.log"
    before = pmset_log(before_path)
    if before["exit_code"] != 0:
        raise RuntimeError("pmset baseline failed")
    state = {
        "schema_version": 1,
        "task": "N6-A2 execute controller",
        "status": "running",
        "started_at": now(),
        "execution_list": EXECUTION_LIST.relative_to(ROOT).as_posix(),
        "execution_list_sha256": sha256(EXECUTION_LIST),
        "caffeinate_assertion": assertion,
        "pmset_before": before,
        "phases": {},
    }
    atomic_json(STATE, state)
    exit_code = 0
    for phase in execution["ordering"]:
        queue_record = execution["queues"][phase]
        queue_path = ROOT / queue_record["path"]
        if sha256(queue_path) != queue_record["sha256"]:
            raise ValueError(f"{phase} queue changed")
        free = shutil.disk_usage(RUN).free
        if free < MINIMUM_FREE_BYTES:
            state["status"] = "disk_guard"
            state["stopped_before_phase"] = phase
            state["disk_free_bytes"] = free
            atomic_json(STATE, state)
            exit_code = 2
            break
        output = RUN / "execute" / phase.lower()
        record = {"status": "running", "started_at": now(),
                  "disk_free_before_bytes": free,
                  "load_average_before": os.getloadavg()}
        state["phases"][phase] = record
        atomic_json(STATE, state)
        call = subprocess.run(
            [sys.executable, str(QUEUE_RUNNER), "--queue", str(queue_path),
             "--output", str(output), "--action", "execute"],
            stdin=subprocess.DEVNULL,
        )
        record.update({"status": "completed" if call.returncode == 0 else "failed",
                       "exit_code": call.returncode, "finished_at": now(),
                       "disk_free_after_bytes": shutil.disk_usage(RUN).free,
                       "load_average_after": os.getloadavg()})
        atomic_json(STATE, state)
        if call.returncode != 0:
            state["status"] = "phase_failed"
            state["stopped_after_phase"] = phase
            atomic_json(STATE, state)
            exit_code = call.returncode
            break
    after = pmset_log(after_path)
    sleep_lines = new_sleep_lines(before_path.read_text(), after_path.read_text())
    pmset_summary = {
        "schema_version": 1,
        "task": "N6-A2 sleep audit",
        "before": before,
        "after": after,
        "sleep_event_count": len(sleep_lines),
        "sleep_events": sleep_lines,
        "status": "passed" if after["exit_code"] == 0 and not sleep_lines else "failed",
    }
    atomic_json(RUN / "pmset-summary.json", pmset_summary)
    state.update({"finished_at": now(), "pmset_summary": {
        "path": (RUN / "pmset-summary.json").relative_to(ROOT).as_posix(),
        "sha256": sha256(RUN / "pmset-summary.json"),
        "sleep_event_count": len(sleep_lines),
    }})
    if exit_code == 0:
        state["status"] = "completed" if not sleep_lines else "sleep_detected"
        if sleep_lines:
            exit_code = 3
    atomic_json(STATE, state)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
