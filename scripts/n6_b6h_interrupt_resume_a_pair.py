#!/usr/bin/env python3
"""Interrupt the second A pair task and restart the identical pair command."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path("/Volumes/zkfdo-jcache/n6-b6h-smoke-final")
ORDER = ROOT / "pair-order-v1.json"
V1_STATE = ROOT / "full-v1.noindex/state.json"
V22_STATE = ROOT / "full-v2.2.noindex/state.json"
PAIR_STATE = ROOT / "pair-state-v1.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"JSON object expected: {path}")
    return value


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def value_after(command: list[str], flag: str) -> str:
    require(command.count(flag) == 1, f"{flag} missing or repeated")
    index = command.index(flag)
    require(index + 1 < len(command), f"{flag} has no value")
    return command[index + 1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    process: subprocess.Popen | None = None
    try:
        require(len(command) >= 3 and
                Path(command[1]).name == "n6_b6h_smoke_a_pair_runner.py" and
                value_after(command, "--action") == "execute-pairs" and
                value_after(command, "--observed-request-peak-bytes") == "1073741824" and
                value_after(command, "--order-sha256") == digest(ORDER),
                "A pair command or order SHA differs")
        order = read(ORDER)
        require(order.get("completed_prefix_orders") == [0] and
                order.get("shuffled_remaining_orders") == [1, 2] and
                [(task.get("engine"), task.get("queue_order"))
                 for task in order.get("tasks", [])][:2] == [("v1", 0), ("v2.2", 1)],
                "A pair task order differs")
        before_v22 = read(V22_STATE)
        before_v1 = read(V1_STATE)
        require(set(before_v22.get("requests", {})) == {"0"} and
                before_v1.get("requests") == {},
                "A pair baseline already ran a task")
        first_v22_sha = before_v22["requests"]["0"]["result_sha256"]
        second_log = (ROOT / "hint-workspaces/full-v2.2.noindex/main/0001/"
                      "requests/000001/attempt-0001.stdout.log")
        second_result = (ROOT / "full-v2.2.noindex/main/0001/requests/000001/"
                         "attempt-0001/result.json")
        first_stdout = ROOT / "pair-interrupt-first.stdout.log"
        first_stderr = ROOT / "pair-interrupt-first.stderr.log"
        resume_stdout = ROOT / "pair-interrupt-resume.stdout.log"
        resume_stderr = ROOT / "pair-interrupt-resume.stderr.log"
        evidence_path = ROOT / "pair-interrupt-resume.json"
        require(not any(path.exists() or path.is_symlink() for path in
                        (first_stdout, first_stderr, resume_stdout,
                         resume_stderr, evidence_path)),
                "A pair interruption evidence already exists")
        with first_stdout.open("x") as out, first_stderr.open("x") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err,
                                       start_new_session=True)
            deadline = time.monotonic() + args.timeout_seconds
            first_v1_sha = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise ValueError(
                        f"A pair exited before interruption: {process.returncode}")
                v1 = read(V1_STATE)
                v22 = read(V22_STATE)
                first = v1.get("requests", {}).get("0", {})
                if first.get("status") == "completed":
                    first_v1_sha = first.get("result_sha256")
                    if "1" not in v22.get("requests", {}) and second_log.is_file():
                        time.sleep(0.05)
                        v22 = read(V22_STATE)
                        if process.poll() is None and \
                                "1" not in v22.get("requests", {}) and \
                                not second_result.exists():
                            break
                time.sleep(0.02)
            else:
                raise ValueError("A pair second task did not start before timeout")
            require(isinstance(first_v1_sha, str) and len(first_v1_sha) == 64,
                    "A pair first task was not durable before interruption")
            interrupted_at = utc_now()
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=20)
        v1_before_restart = read(V1_STATE)
        v22_before_restart = read(V22_STATE)
        require(v1_before_restart["requests"]["0"]["result_sha256"] ==
                first_v1_sha and
                v22_before_restart["requests"]["0"]["result_sha256"] ==
                first_v22_sha and
                "1" not in v22_before_restart["requests"],
                "A pair did not stop during the second unfinished task")
        with resume_stdout.open("x") as out, resume_stderr.open("x") as err:
            resumed = subprocess.run(command, stdout=out, stderr=err, check=False)
        require(resumed.returncode == 0,
                f"A pair identical restart exited {resumed.returncode}")
        v1_after = read(V1_STATE)
        v22_after = read(V22_STATE)
        pair_after = read(PAIR_STATE)
        require(pair_after.get("status") == "completed" and
                pair_after.get("order_sha256") == digest(ORDER) and
                set(v1_after.get("requests", {})) == {"0", "1", "2"} and
                set(v22_after.get("requests", {})) == {"0", "1", "2"} and
                v1_after["requests"]["0"]["result_sha256"] == first_v1_sha and
                v1_after["requests"]["0"]["attempt"] == 1 and
                v22_after["requests"]["0"]["result_sha256"] == first_v22_sha and
                v22_after["requests"]["0"]["attempt"] == 1 and
                v22_after["requests"]["1"]["attempt"] >= 2,
                "A pair restart did not preserve finished tasks and order")
        evidence = {
            "schema": "n6-b6h-a-pair-interruption-v1",
            "status": "passed", "command": command,
            "order_sha256": digest(ORDER),
            "interrupted_at": interrupted_at,
            "first_process_returncode": process.returncode,
            "restart_returncode": resumed.returncode,
            "v1_first_result_sha256_before_after": first_v1_sha,
            "v2_2_prefix_result_sha256_before_after": first_v22_sha,
            "v1_first_attempt_after": v1_after["requests"]["0"]["attempt"],
            "v2_2_second_attempt_after": v22_after["requests"]["1"]["attempt"],
            "second_started_log_path": str(second_log),
            "pair_state_sha256": digest(PAIR_STATE),
            "completed_at": utc_now(),
        }
        with evidence_path.open("x") as stream:
            json.dump(evidence, stream, sort_keys=True, indent=2)
            stream.write("\n")
        print(json.dumps({"status": "passed", "output": str(evidence_path)},
                         sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=20)
        print(f"A pair interruption refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
