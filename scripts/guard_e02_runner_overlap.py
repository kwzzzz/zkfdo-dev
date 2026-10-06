#!/usr/bin/env python3
"""Pause the existing E-02 main process tree before unfinished tail overlap."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/e02-production-mains-2026-10-05"


def processes():
    output = subprocess.check_output(
        ["/bin/ps", "-axo", "pid=,ppid=,command="], text=True
    )
    rows = {}
    for line in output.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            rows[int(parts[0])] = {"parent": int(parts[1]), "command": parts[2]}
    return rows


def descendants(pid, rows):
    selected = {pid}
    while True:
        expanded = selected | {key for key, value in rows.items() if value["parent"] in selected}
        if expanded == selected:
            return selected
        selected = expanded


def completed(identifier):
    path = RUN / "preparation-measurements" / identifier / "result.json"
    try:
        return bool(json.loads(path.read_text()).get("finished_at"))
    except (OSError, ValueError):
        return False


def write_event(value):
    value["recorded_at"] = datetime.now(timezone.utc).isoformat()
    with (RUN / "runner-overlap-guard.jsonl").open("a") as stream:
        stream.write(json.dumps(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(value), flush=True)


def pause_tree(pid, expected_command):
    rows = processes()
    if pid not in rows or rows[pid]["command"] != expected_command:
        return []
    # Freeze the scheduler first so no pending futures can start while children
    # are inspected. All affected processes belong to this verified runner.
    os.kill(pid, signal.SIGSTOP)
    stopped = {pid}
    for _ in range(3):
        rows = processes()
        for child in sorted(descendants(pid, rows) - stopped):
            try:
                os.kill(child, signal.SIGSTOP)
                stopped.add(child)
            except ProcessLookupError:
                pass
    return sorted(stopped)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-pid", type=int, required=True)
    parser.add_argument("--tail-pid", type=int, required=True)
    parser.add_argument("--pause-index", type=int, default=68)
    args = parser.parse_args()
    rows = processes()
    main_command = rows.get(args.main_pid, {}).get("command", "")
    tail_command = rows.get(args.tail_pid, {}).get("command", "")
    if "scripts/run_e02_production_mains.py prepare --workers 2" not in main_command:
        raise RuntimeError("main PID does not identify the existing authorized runner")
    if "scripts/run_e02_prepare_tail.py" not in tail_command:
        raise RuntimeError("tail PID does not identify the existing authorized runner")
    selection = json.loads((RUN / "preparation-selection.json").read_text())["entries"]
    tail = set(json.loads((RUN / "preparation-tail-selection.json").read_text())["entries"])
    tail_start = min(index for index, item in enumerate(selection) if item["identifier"] in tail)
    if not 0 <= args.pause_index < tail_start:
        raise ValueError("pause threshold must precede the tail")
    write_event({"event": "guard_started", "main_pid": args.main_pid,
                 "tail_pid": args.tail_pid, "pause_index_zero_based": args.pause_index,
                 "tail_start_index_zero_based": tail_start,
                 "disk_guard_bytes": 35 * 1024**3,
                 "action": "SIGSTOP verified runner trees; preserve all files; never restart or resume"})
    previous = None
    while True:
        rows = processes()
        main_alive = rows.get(args.main_pid, {}).get("command") == main_command
        tail_alive = rows.get(args.tail_pid, {}).get("command") == tail_command
        tail_done = sum(completed(identifier) for identifier in tail)
        started = [index for index, item in enumerate(selection[:tail_start])
                   if (RUN / "preparation-measurements" / item["identifier"]).exists()]
        furthest = max(started, default=-1)
        state = (furthest, tail_done, main_alive, tail_alive)
        if state != previous:
            write_event({"event": "progress", "main_furthest_index_zero_based": furthest,
                         "tail_completed": tail_done, "tail_denominator": len(tail),
                         "main_alive": main_alive, "tail_alive": tail_alive})
            previous = state
        free = shutil.disk_usage(RUN).free
        disk_low = free < 35 * 1024**3
        overlap_risk = main_alive and furthest >= args.pause_index and (tail_alive or tail_done != len(tail))
        if disk_low or overlap_risk:
            write_event({"event": "pause_required", "reason": "disk_below_35_gib" if disk_low else "unfinished_tail_near_overlap",
                         "free_bytes": free, "main_furthest_index_zero_based": furthest,
                         "tail_completed": tail_done})
            main_stopped = pause_tree(args.main_pid, main_command) if main_alive else []
            tail_stopped = pause_tree(args.tail_pid, tail_command) if disk_low and tail_alive else []
            write_event({"event": "paused_no_automatic_resume", "main_stopped_pids": main_stopped,
                         "tail_stopped_pids": tail_stopped})
            return
        if not main_alive and not tail_alive:
            write_event({"event": "runners_exited", "tail_complete": tail_done == len(tail)})
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
