#!/usr/bin/env python3
"""Rerun only the five A revisions affected by the former nested-build rule.

Only the A Docker collector is invoked. Collector output stays in per-revision
logs; stdout contains stage statuses and never a captured input or verdict.
The original a-dryrun/ output is never read or changed by this runner.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runs/n6-b5-2026-10-17.noindex/a-dryrun-v2"
COLLECTOR = ROOT / "scripts/n6_b5_docker_base_inputs.py"
IDENTIFIERS = (
    "aq-011-93343c3cd34c",
    "aq-012-44d0df2ab46e",
    "aq-016-0a7d49b1c135",
    "aq-017-9703bbce0c43",
    "aq-024-6f6781246415",
)
STAGES = ("a_zkbugs", "b_l_series", "c_committed_json", "d_project_test", "e_zero")
CAMPAIGN_SECONDS = 90 * 60
REVISION_SECONDS = 60 * 60
CLEANUP_RESERVE_SECONDS = 15


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    recorded_stages = selection.get("stages", ())
    if not isinstance(recorded_stages, (list, tuple)) or any(
            stage not in STAGES for stage in recorded_stages):
        raise ValueError("unexpected A collector stages")
    original_rule = selection.get("original_rule_stage")
    if original_rule not in (*STAGES, "base_input_unavailable", None):
        raise ValueError("unexpected original rule stage")
    failure_reasons: dict[str, list[str]] = {stage: [] for stage in STAGES}
    for attempt in attempts:
        if isinstance(attempt, dict) and attempt.get("stage") in STAGES:
            reason = attempt.get("reason")
            if isinstance(reason, str) and reason not in failure_reasons[attempt["stage"]]:
                failure_reasons[attempt["stage"]].append(reason[:512])
    if selected == "d_project_test" and original_rule != "e_zero" and not failure_reasons["e_zero"]:
        raise ValueError("zero stage result missing after project-test selection")
    stages = {}
    for stage in STAGES:
        if stage == selected or stage == original_rule:
            stages[stage] = "passed"
        elif failure_reasons[stage]:
            stages[stage] = "failed"
        elif selected is not None and STAGES.index(stage) > STAGES.index(selected):
            stages[stage] = "not_run"
        elif stage in recorded_stages:
            # In the original collector this list is the planned fixed stage
            # order. Selection stops early, except that (e) still runs after
            # (d) to determine the original-rule outcome.
            stages[stage] = "no_input"
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


def run_campaign(output: Path, collector: Path, campaign_start: datetime | None = None,
                 identifiers: tuple[str, ...] = IDENTIFIERS) -> int:
    if campaign_start is not None and campaign_start.tzinfo is None:
        raise ValueError("campaign start must include a UTC offset")
    if not collector.is_file():
        raise FileNotFoundError(collector)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "orchestrator.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another A dry-run orchestrator is active") from error
        campaign_path = output / "campaign.json"
        collector_digest = sha256(collector)
        if campaign_path.is_file():
            campaign = json.loads(campaign_path.read_text())
            if (campaign.get("schema") != "n6-b5b-a-dryrun-campaign-v1" or
                    campaign.get("identifiers") != list(identifiers) or
                    campaign.get("collector_sha256") != collector_digest or
                    campaign.get("campaign_seconds") != CAMPAIGN_SECONDS or
                    campaign.get("revision_seconds") != REVISION_SECONDS or
                    campaign.get("output_root") != str(output.resolve())):
                raise ValueError("A campaign queue or collector changed; preserve this output")
            saved_start = datetime.fromisoformat(campaign["started_at_utc"].replace("Z", "+00:00"))
            if campaign_start is not None and abs((campaign_start - saved_start).total_seconds()) > 1:
                raise ValueError("A campaign start cannot change on resume")
            campaign_start = saved_start
        else:
            if (output / "index.json").exists():
                raise ValueError("A output index exists without campaign metadata")
            campaign_start = campaign_start or datetime.now(timezone.utc)
            write_json(campaign_path, {
                "schema": "n6-b5b-a-dryrun-campaign-v1",
                "started_at_utc": campaign_start.isoformat(timespec="microseconds"),
                "campaign_seconds": CAMPAIGN_SECONDS,
                "revision_seconds": REVISION_SECONDS,
                "collector_path": str(collector.resolve()),
                "collector_sha256": collector_digest,
                "identifiers": list(identifiers),
                "output_root": str(output.resolve()),
            })
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
                stop_reason = ("interrupted_previous_run" if existing.get("status") == "running"
                               else "collector_error_previous_run")
                # Do not relabel a partially executed or failed revision as an
                # unstarted one. Its raw logs remain for review.
                continue
            seconds_left = campaign_deadline - time.monotonic()
            if stop_reason or seconds_left <= CLEANUP_RESERVE_SECONDS:
                reason = stop_reason or "시간 미실행: A 재시험 전체 90분 초과"
                status = ("time_not_run" if not stop_reason or stop_reason.startswith("시간 미실행")
                          else "not_run_after_stop")
                state = blank_state(identifier, status, reason)
                write_json(state_path, state)
                print_stages(identifier, state["stages"])
                continue
            try:
                current_collector_digest = sha256(collector)
            except OSError:
                current_collector_digest = None
            if current_collector_digest != collector_digest:
                state = blank_state(identifier, "collector_changed",
                                    "collector_sha256_changed_during_campaign")
                state["expected_collector_sha256"] = collector_digest
                state["observed_collector_sha256"] = current_collector_digest
                write_json(state_path, state)
                print_stages(identifier, state["stages"])
                stop_reason = state["reason"]
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
                                        "A 재시험 전체 90분 초과" if overall else "리비전 60분 초과", elapsed)
                    state["stage"] = "collector"
                    state["started_at_utc"] = started_utc
                    write_json(state_path, state)
                    print_stages(identifier, state["stages"])
                    if overall:
                        stop_reason = "시간 미실행: A 재시험 전체 90분 초과"
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
    parser.add_argument("--campaign-start-utc",
                        help="optional fixed UTC start; a saved campaign keeps its original start")
    args = parser.parse_args()
    start = (datetime.fromisoformat(args.campaign_start_utc.replace("Z", "+00:00"))
             if args.campaign_start_utc else None)
    return run_campaign(OUTPUT, COLLECTOR, start)


if __name__ == "__main__":
    sys.exit(main())
