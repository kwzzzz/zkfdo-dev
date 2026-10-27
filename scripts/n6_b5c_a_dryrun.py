#!/usr/bin/env python3
"""Run only the five A revisions, serially, in up to three tool-check rounds.

The first round uses a-dryrun-v3/ and later rounds use round-2/ or round-3/.
The campaign clock starts once and is never reset. Collector output stays in
per-revision logs; stdout contains only stage states, never input values.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import n6_b5b_a_dryrun as previous


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runs/n6-b5-2026-10-17.noindex/a-dryrun-v3"
COLLECTOR = ROOT / "scripts/n6_b5_docker_base_inputs.py"
TOOLS = ROOT / "runs/n6-b5-2026-10-17.noindex/install-tools.json"
IDENTIFIERS = previous.IDENTIFIERS
STAGES = previous.STAGES
CAMPAIGN_SECONDS = 2 * 60 * 60
REVISION_SECONDS = 60 * 60
CLEANUP_RESERVE_SECONDS = 15
MAX_ROUNDS = 3
CAMPAIGN_SCHEMA = "n6-b5c-a-dryrun-campaign-v1"
ROUND_SCHEMA = "n6-b5c-a-dryrun-round-v1"
STATE_SCHEMA = "n6-b5c-a-dryrun-revision-state-v1"


def round_output(output: Path, round_number: int) -> Path:
    if round_number not in range(1, MAX_ROUNDS + 1):
        raise ValueError("A rerun permits only rounds 1, 2, and 3")
    return output if round_number == 1 else output / f"round-{round_number}"


def blank_state(identifier: str, status: str, reason: str, seconds: float = 0.0) -> dict:
    result = previous.blank_state(identifier, status, reason, seconds)
    result["schema"] = STATE_SCHEMA
    return result


def summarize_selection(identifier: str, selection: dict, seconds: float) -> dict:
    result = previous.summarize_selection(identifier, selection, seconds)
    result["schema"] = STATE_SCHEMA
    return result


def tool_block_state(identifier: str, block: dict, seconds: float) -> dict:
    if block.get("status") != "tool_blocked":
        raise ValueError("tool-blocked metadata has unexpected status")
    reason = block.get("reason")
    if not isinstance(reason, str) or not reason:
        raise ValueError("tool-blocked metadata is missing a reason")
    stage = block.get("stage", "d_project_test")
    if stage not in STAGES:
        stage = "d_project_test"
    result = blank_state(identifier, "tool_blocked", reason[:512], seconds)
    result["stage"] = stage
    result["stages"][stage] = "tool_blocked"
    return result


def read_tool_identity(tools: Path) -> tuple[str, str]:
    value = json.loads(tools.read_text())
    image = value.get("image")
    if not isinstance(image, str) or not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("install-tools image must be digest-pinned")
    return previous.sha256(tools), image


def load_campaign(path: Path, output: Path, identifiers: tuple[str, ...],
                  campaign_start: datetime | None) -> tuple[dict, datetime]:
    if path.is_file():
        campaign = json.loads(path.read_text())
        if (campaign.get("schema") != CAMPAIGN_SCHEMA or
                campaign.get("identifiers") != list(identifiers) or
                campaign.get("campaign_seconds") != CAMPAIGN_SECONDS or
                campaign.get("revision_seconds") != REVISION_SECONDS or
                campaign.get("max_rounds") != MAX_ROUNDS or
                campaign.get("output_root") != str(output.resolve())):
            raise ValueError("A campaign metadata changed; preserve the existing output")
        saved = datetime.fromisoformat(campaign["started_at_utc"].replace("Z", "+00:00"))
        if campaign_start is not None and abs((campaign_start - saved).total_seconds()) > 1:
            raise ValueError("A campaign start cannot change on resume")
        return campaign, saved
    if (output / "index.json").exists() or (output / "round-2").exists() or (output / "round-3").exists():
        raise ValueError("A output exists without campaign metadata")
    start = campaign_start or datetime.now(timezone.utc)
    campaign = {
        "schema": CAMPAIGN_SCHEMA,
        "started_at_utc": start.isoformat(timespec="microseconds"),
        "campaign_seconds": CAMPAIGN_SECONDS,
        "revision_seconds": REVISION_SECONDS,
        "max_rounds": MAX_ROUNDS,
        "identifiers": list(identifiers),
        "output_root": str(output.resolve()),
    }
    previous.write_json(path, campaign)
    return campaign, start


def load_round(path: Path, output: Path, round_number: int, identifiers: tuple[str, ...],
               collector: Path, tools: Path) -> dict:
    collector_digest = previous.sha256(collector)
    tools_digest, image = read_tool_identity(tools)
    if path.is_file():
        saved = json.loads(path.read_text())
        if (saved.get("schema") != ROUND_SCHEMA or
                saved.get("round") != round_number or
                saved.get("collector_sha256") != collector_digest or
                saved.get("tools_sha256") != tools_digest or
                saved.get("image") != image or
                saved.get("identifiers") != list(identifiers) or
                saved.get("output_root") != str(output.resolve())):
            raise ValueError("A round queue, collector, or tools changed; preserve this round")
        return saved
    if (output / "index.json").exists():
        raise ValueError("A round index exists without round metadata")
    saved = {
        "schema": ROUND_SCHEMA,
        "round": round_number,
        "started_at_utc": previous.utc_now(),
        "collector_path": str(collector.resolve()),
        "collector_sha256": collector_digest,
        "tools_path": str(tools.resolve()),
        "tools_sha256": tools_digest,
        "image": image,
        "identifiers": list(identifiers),
        "output_root": str(output.resolve()),
    }
    previous.write_json(path, saved)
    return saved


def check_previous_round(output: Path, round_number: int, identifiers: tuple[str, ...]) -> None:
    if round_number == 1:
        return
    preceding = round_output(output, round_number - 1)
    if not (preceding / "round.json").is_file():
        raise ValueError("preceding A round is missing")
    for identifier in identifiers:
        state = preceding / identifier / "state.json"
        if not state.is_file() or json.loads(state.read_text()).get("status") == "running":
            raise ValueError("preceding A round is incomplete")


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
    for cidfile in (revision_dir / "docker-logs").glob("*.cid"):
        cid = cidfile.read_text().strip()
        if cid:
            subprocess.run(["docker", "rm", "-f", cid], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=8, check=False)
        cidfile.unlink(missing_ok=True)


def run_campaign(output: Path, collector: Path, tools: Path, round_number: int = 1,
                 campaign_start: datetime | None = None,
                 identifiers: tuple[str, ...] = IDENTIFIERS) -> int:
    if campaign_start is not None and campaign_start.tzinfo is None:
        raise ValueError("campaign start must include a UTC offset")
    if round_number not in range(1, MAX_ROUNDS + 1):
        raise ValueError("A rerun permits only rounds 1, 2, and 3")
    if not collector.is_file() or not tools.is_file():
        raise FileNotFoundError("A collector or install-tools missing")
    # Reject a malformed tool pin before starting the shared two-hour clock.
    previous.sha256(collector)
    read_tool_identity(tools)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "orchestrator.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another A dry-run orchestrator is active") from error
        check_previous_round(output, round_number, identifiers)
        _, start = load_campaign(output / "campaign.json", output, identifiers, campaign_start)
        target = round_output(output, round_number)
        target.mkdir(parents=True, exist_ok=True)
        round_meta = load_round(target / "round.json", target, round_number,
                                identifiers, collector, tools)
        remaining = start.timestamp() + CAMPAIGN_SECONDS - time.time()
        deadline = time.monotonic() + max(0, remaining)
        stop_reason = None
        for identifier in identifiers:
            revision_dir = target / identifier
            state_path = revision_dir / "state.json"
            if state_path.is_file():
                existing = json.loads(state_path.read_text())
                if existing.get("status") not in {"running", "collector_error"}:
                    previous.print_stages(identifier, existing["stages"])
                    if existing.get("status") in {"tool_blocked", "environment_blocked", "collector_changed",
                                                  "tools_changed", "time_exceeded", "collector_error"}:
                        stop_reason = existing.get("reason") or existing["status"]
                    continue
                stop_reason = ("interrupted_previous_run" if existing.get("status") == "running"
                               else "collector_error_previous_run")
                continue
            seconds_left = deadline - time.monotonic()
            if stop_reason or seconds_left <= CLEANUP_RESERVE_SECONDS:
                reason = stop_reason or "시간 미실행: A 재시험 전체 2시간 초과"
                status = "not_run_after_stop" if stop_reason else "time_not_run"
                state = blank_state(identifier, status, reason)
                previous.write_json(state_path, state)
                previous.print_stages(identifier, state["stages"])
                continue
            try:
                current_collector = previous.sha256(collector)
                current_tools, current_image = read_tool_identity(tools)
            except (OSError, ValueError, json.JSONDecodeError):
                current_collector, current_tools, current_image = None, None, None
            if (current_collector != round_meta["collector_sha256"] or
                    current_tools != round_meta["tools_sha256"] or
                    current_image != round_meta["image"]):
                status = ("collector_changed" if current_collector != round_meta["collector_sha256"]
                          else "tools_changed")
                state = blank_state(identifier, status, status + "_during_round")
                state["expected_collector_sha256"] = round_meta["collector_sha256"]
                state["observed_collector_sha256"] = current_collector
                state["expected_tools_sha256"] = round_meta["tools_sha256"]
                state["observed_tools_sha256"] = current_tools
                previous.write_json(state_path, state)
                previous.print_stages(identifier, state["stages"])
                stop_reason = state["reason"]
                continue
            revision_dir.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            started_utc = previous.utc_now()
            state = blank_state(identifier, "running", "collector_started")
            state["started_at_utc"] = started_utc
            state.pop("finished_at_utc")
            previous.write_json(state_path, state)
            command = [sys.executable, str(collector), "--scope", "A", "--identifier", identifier,
                       "--tools", str(tools), "--output-root", str(target)]
            with (revision_dir / "collector.stdout.log").open("wb") as stdout, \
                    (revision_dir / "collector.stderr.log").open("wb") as stderr:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                           stdout=stdout, stderr=stderr, start_new_session=True)
                revision_deadline = min(deadline - CLEANUP_RESERVE_SECONDS,
                                        started + REVISION_SECONDS)
                try:
                    code = process.wait(timeout=max(0.1, revision_deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    stop_process(process, revision_dir)
                    elapsed = time.monotonic() - started
                    overall = deadline - time.monotonic() <= CLEANUP_RESERVE_SECONDS
                    state = blank_state(identifier, "time_exceeded" if overall else "revision_timeout",
                                        "A 재시험 전체 2시간 초과" if overall else "리비전 60분 초과", elapsed)
                    state["stage"] = "collector"
                    state["started_at_utc"] = started_utc
                    previous.write_json(state_path, state)
                    previous.print_stages(identifier, state["stages"])
                    if overall:
                        stop_reason = "시간 미실행: A 재시험 전체 2시간 초과"
                    continue
            elapsed = time.monotonic() - started
            blocked = revision_dir / "tool-blocked.json"
            environment = revision_dir / "environment-blocked.json"
            if blocked.is_file():
                try:
                    state = tool_block_state(identifier, json.loads(blocked.read_text()), elapsed)
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    state = blank_state(identifier, "collector_error", str(error)[:512], elapsed)
                stop_reason = state["reason"]
            elif environment.is_file():
                item = json.loads(environment.read_text())
                state = blank_state(identifier, "environment_blocked",
                                    str(item.get("reason", "environment_blocked"))[:512], elapsed)
                state["stage"] = "collector"
                stop_reason = state["reason"]
            elif code:
                state = blank_state(identifier, "collector_error", f"collector_exit_{code}", elapsed)
                state["stage"] = "collector"
                stop_reason = state["reason"]
            else:
                try:
                    selection = json.loads((revision_dir / "selection.json").read_text())
                    index = json.loads((target / "index.json").read_text())
                    if index["revisions"][identifier]["status"] != selection["status"]:
                        raise ValueError("collector index/selection status mismatch")
                    if selection["status"] == "tool_blocked":
                        state = tool_block_state(identifier, selection, elapsed)
                        stop_reason = state["reason"]
                    else:
                        state = summarize_selection(identifier, selection, elapsed)
                except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
                    state = blank_state(identifier, "collector_error", str(error)[:512], elapsed)
                    state["stage"] = "collector"
                    stop_reason = state["reason"]
            state["started_at_utc"] = started_utc
            previous.write_json(state_path, state)
            previous.print_stages(identifier, state["stages"])
        return 0 if stop_reason is None else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--campaign-start-utc", help="optional UTC start; a saved campaign keeps its start")
    args = parser.parse_args()
    start = (datetime.fromisoformat(args.campaign_start_utc.replace("Z", "+00:00"))
             if args.campaign_start_utc else None)
    return run_campaign(OUTPUT, COLLECTOR, TOOLS, args.round, start)


if __name__ == "__main__":
    sys.exit(main())
