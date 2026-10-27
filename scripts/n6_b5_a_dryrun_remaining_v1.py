#!/usr/bin/env python3
"""Run the nine remaining exploratory A base-input trials, with a shared deadline.

Only the A Docker collector is invoked. Collector output stays in per-revision
logs; stdout contains stage statuses and never a captured input or verdict.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runs/n6-b5-2026-10-17.noindex/a-dryrun/remaining"
COLLECTOR = ROOT / "scripts/n6_b5_docker_base_inputs.py"
IDENTIFIERS = (
    "aq-011-93343c3cd34c",
    "aq-012-44d0df2ab46e",
    "aq-016-0a7d49b1c135",
    "aq-017-9703bbce0c43",
    "aq-024-6f6781246415",
    "aq-026-2bcd7ed6110f",
    "aq-037-94fe3080fc18",
    "aq-039-0ad3923f2f5b",
    "aq-040-da54d3e7bc8a",
)
STAGES = ("a_zkbugs", "b_l_series", "c_committed_json", "d_project_test", "e_zero")
CAMPAIGN_SECONDS = 3 * 60 * 60
REVISION_SECONDS = 60 * 60
CLEANUP_RESERVE_SECONDS = 15


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def print_stages(identifier: str, stages: dict[str, str]) -> None:
    print(identifier + " " + " ".join(f"{stage}:{stages[stage]}" for stage in STAGES), flush=True)


def blank_state(identifier: str, status: str, reason: str, seconds: float = 0.0) -> dict:
    return {"schema": "n6-b5-a-dryrun-revision-state-v1", "identifier": identifier,
            "stage": None, "status": status, "reason": reason, "seconds": seconds,
            "stages": {stage: "not_run" for stage in STAGES},
            "finished_at_utc": utc_now()}


def summarize_selection(identifier: str, selection: dict, seconds: float) -> dict:
    status = selection.get("status")
    selected = selection.get("selected_stage")
    if status not in {"passed", "base_input_unavailable"} or (selected is not None and selected not in STAGES):
        raise ValueError("unexpected A collector status or selected stage")
    if (status == "passed") != (selected is not None):
        raise ValueError("collector status and selected stage disagree")
    attempts = selection.get("failed_attempts", [])
    if not isinstance(attempts, list):
        raise ValueError("failed_attempts must be a list")
    failure_reasons: dict[str, list[str]] = {stage: [] for stage in STAGES}
    for attempt in attempts:
        if isinstance(attempt, dict) and attempt.get("stage") in STAGES:
            reason = attempt.get("reason")
            if isinstance(reason, str) and reason not in failure_reasons[attempt["stage"]]:
                failure_reasons[attempt["stage"]].append(reason[:512])
    stages = {}
    for stage in STAGES:
        if stage == selected:
            stages[stage] = "passed"
        elif selected is not None and STAGES.index(stage) > STAGES.index(selected):
            stages[stage] = "not_run"
        elif stage in selection.get("stages", ()):
            stages[stage] = "failed" if failure_reasons[stage] else "no_input"
        else:
            stages[stage] = "not_run"
    failed_stage = next((stage for stage in reversed(STAGES) if failure_reasons[stage]), None)
    final_stage = selected or failed_stage
    reason = None if selected else (failure_reasons[failed_stage][-1] if failed_stage else "base_input_unavailable")
    return {"schema": "n6-b5-a-dryrun-revision-state-v1", "identifier": identifier,
            "stage": final_stage, "status": status, "reason": reason,
            "seconds": seconds, "stages": stages,
            "stage_reasons": {stage: reasons for stage, reasons in failure_reasons.items() if reasons},
            "finished_at_utc": utc_now()}


def stop_process(process: subprocess.Popen, revision_dir: Path) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)
    # The Docker CLI can outlive its client. Only remove containers whose CID
    # files were created by this revision's collector invocation.
    for cidfile in (revision_dir / "docker-logs").glob("*.cid"):
        cid = cidfile.read_text().strip()
        if cid:
            subprocess.run(["docker", "rm", "-f", cid], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=8, check=False)
        cidfile.unlink(missing_ok=True)


def run_campaign(output: Path, collector: Path, campaign_start: datetime,
                 identifiers: tuple[str, ...] = IDENTIFIERS) -> int:
    if campaign_start.tzinfo is None:
        raise ValueError("campaign start must include a UTC offset")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "orchestrator.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another A dry-run orchestrator is active") from error
        remaining = campaign_start.timestamp() + CAMPAIGN_SECONDS - time.time()
        campaign_deadline = time.monotonic() + max(0, remaining)
        stop_reason = None
        for identifier in identifiers:
            revision_dir = output / identifier
            state_path = revision_dir / "state.json"
            if state_path.is_file():
                existing = json.loads(state_path.read_text())
                if existing.get("status") not in {"running", "collector_error"}:
                    print_stages(identifier, existing["stages"])
                    continue
                stop_reason = "interrupted_previous_run"
            seconds_left = campaign_deadline - time.monotonic()
            if stop_reason or seconds_left <= CLEANUP_RESERVE_SECONDS:
                reason = stop_reason or "시간 미실행: A 시험 전체 3시간 초과"
                status = ("time_not_run" if not stop_reason or stop_reason.startswith("시간 미실행")
                          else "not_run_after_stop")
                state = blank_state(identifier, status, reason)
                write_json(state_path, state)
                print_stages(identifier, state["stages"])
                continue
            revision_dir.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            command = [sys.executable, str(collector), "--scope", "A", "--identifier", identifier,
                       "--output-root", str(output)]
            state = blank_state(identifier, "running", "collector_started")
            started_utc = utc_now()
            state["started_at_utc"] = started_utc
            state.pop("finished_at_utc")
            write_json(state_path, state)
            with (revision_dir / "collector.stdout.log").open("wb") as stdout, \
                    (revision_dir / "collector.stderr.log").open("wb") as stderr:
                process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                                           stdin=subprocess.DEVNULL, start_new_session=True)
                deadline = min(campaign_deadline - CLEANUP_RESERVE_SECONDS,
                               started + REVISION_SECONDS)
                try:
                    code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    stop_process(process, revision_dir)
                    elapsed = time.monotonic() - started
                    overall = campaign_deadline - time.monotonic() <= CLEANUP_RESERVE_SECONDS
                    state = blank_state(identifier, "time_exceeded" if overall else "revision_timeout",
                                        "A 시험 전체 3시간 초과" if overall else "리비전 60분 초과", elapsed)
                    state["stage"] = "collector"
                    state["started_at_utc"] = started_utc
                    write_json(state_path, state)
                    print_stages(identifier, state["stages"])
                    if overall:
                        stop_reason = "시간 미실행: A 시험 전체 3시간 초과"
                    continue
            elapsed = time.monotonic() - started
            if code:
                blocked = revision_dir / "environment-blocked.json"
                if blocked.is_file():
                    item = json.loads(blocked.read_text())
                    reason = str(item.get("reason", "environment_blocked"))[:512]
                    status = "environment_blocked"
                else:
                    reason, status = f"collector_exit_{code}", "collector_error"
                state = blank_state(identifier, status, reason, elapsed)
                state["stage"] = "collector"
                stop_reason = reason
            else:
                selection_path = revision_dir / "selection.json"
                index_path = output / "index.json"
                try:
                    selection = json.loads(selection_path.read_text())
                    index = json.loads(index_path.read_text())
                    if index["revisions"][identifier]["status"] != selection["status"]:
                        raise ValueError("collector index/selection status mismatch")
                    state = summarize_selection(identifier, selection, elapsed)
                except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
                    state = blank_state(identifier, "collector_error", str(error)[:512], elapsed)
                    state["stage"] = "collector"
                    stop_reason = state["reason"]
            state["started_at_utc"] = started_utc
            write_json(state_path, state)
            print_stages(identifier, state["stages"])
        return 0 if stop_reason is None else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-start-utc", required=True,
                        help="UTC start of the first aq-025 A trial, e.g. 2026-10-17T15:55:11Z")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.campaign_start_utc.replace("Z", "+00:00"))
    first = OUTPUT.parent / "aq-025-70328d3fd35e/selection.json"
    second = OUTPUT.parent / "with-linux-circom/aq-025-70328d3fd35e/selection.json"
    if not first.is_file() or not second.is_file():
        parser.error("both direct aq-025 A trial records are required")
    first_record = json.loads(first.read_text())
    first_started = first.stat().st_mtime - float(first_record["wall_seconds"])
    if start.timestamp() > first_started + 1:
        parser.error("campaign start is later than the first direct A trial")
    return run_campaign(OUTPUT, COLLECTOR, start)


if __name__ == "__main__":
    sys.exit(main())
