#!/usr/bin/env python3
"""Interrupt A smoke during request two and rerun the identical CLI command."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path("/Volumes/zkfdo-jcache/n6-b6g-smoke/routed")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "A smoke state is not an object")
    return value


def value_after(argv: list[str], flag: str) -> str:
    require(argv.count(flag) == 1, f"{flag} missing or repeated")
    position = argv.index(flag)
    require(position + 1 < len(argv), f"{flag} has no value")
    return argv[position + 1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    process = None
    try:
        require(len(command) >= 3 and Path(command[1]).name == "n6_b6g_smoke_a_runner.py",
                "A smoke harness command required after --")
        require(value_after(command, "--action") == "execute-all",
                "interruption command must execute all")
        engine = value_after(command, "--engine")
        require(engine in {"v1", "v2.2"}, "A smoke engine invalid")
        output = Path(value_after(command, "--output"))
        workspace = Path(value_after(command, "--workspace-root"))
        require(output == ROOT / f"full-{engine}.noindex" and
                workspace == ROOT / "hint-workspaces" and not output.exists(),
                "A smoke output/workspace must be new in the locked SSD folder")
        state_path = output / "state.json"
        second_log = (workspace / output.name / "main/0001/requests/000001/attempt-0001.stdout.log")
        first_stdout = ROOT / f"interrupt-first-{engine}.stdout.log"
        first_stderr = ROOT / f"interrupt-first-{engine}.stderr.log"
        resume_stdout = ROOT / f"interrupt-resume-{engine}.stdout.log"
        resume_stderr = ROOT / f"interrupt-resume-{engine}.stderr.log"
        evidence_path = ROOT / f"interrupt-resume-{engine}.json"
        require(not any(p.exists() for p in (first_stdout, first_stderr,
                                            resume_stdout, resume_stderr,
                                            evidence_path)),
                "A smoke interruption evidence already exists")
        with first_stdout.open("x") as out, first_stderr.open("x") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err,
                                       start_new_session=True)
            deadline = time.monotonic() + args.timeout_seconds
            first = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise ValueError(f"A smoke exited before interruption: {process.returncode}")
                state = read_state(state_path)
                requests = state.get("requests", {})
                if isinstance(requests, dict) and requests.get("0", {}).get("status") == "completed":
                    first = requests["0"]
                    if "1" not in requests and second_log.is_file():
                        time.sleep(0.5)
                        state = read_state(state_path)
                        requests = state.get("requests", {})
                        if process.poll() is None and "1" not in requests:
                            break
                time.sleep(0.1)
            else:
                raise ValueError("second A request did not start before timeout")
            require(first is not None and first.get("result_sha256"),
                    "first A request was not completed before interruption")
            first_sha = first["result_sha256"]
            interrupted_at = utc_now()
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=20)
        before_resume = read_state(state_path)
        require(before_resume.get("requests", {}).get("0", {}).get("result_sha256") ==
                first_sha and "1" not in before_resume.get("requests", {}),
                "A smoke did not stop while request two was unfinished")
        with resume_stdout.open("x") as out, resume_stderr.open("x") as err:
            resumed = subprocess.run(command, stdout=out, stderr=err, check=False)
        require(resumed.returncode == 0,
                f"A smoke identical restart failed with exit {resumed.returncode}")
        after = read_state(state_path)
        requests = after.get("requests", {})
        require(after.get("status") == "completed" and
                set(requests) == {"0", "1", "2"} and
                requests["0"].get("result_sha256") == first_sha and
                requests["0"].get("attempt") == 1 and
                requests["1"].get("status") == "completed" and
                requests["1"].get("attempt", 0) >= 2 and
                requests["2"].get("status") == "completed",
                "A smoke restart did not preserve/complete all requests")
        evidence = {
            "schema": "n6-b6g-a-smoke-interruption-v1",
            "status": "passed", "engine": engine,
            "command": command, "interrupted_at": interrupted_at,
            "first_process_returncode": process.returncode,
            "restart_returncode": resumed.returncode,
            "first_result_sha256_before": first_sha,
            "first_result_sha256_after": requests["0"]["result_sha256"],
            "first_attempt_after": requests["0"]["attempt"],
            "second_attempt_after": requests["1"]["attempt"],
            "third_attempt_after": requests["2"]["attempt"],
            "second_started_log_path": str(second_log),
            "completed_at": utc_now(),
        }
        with evidence_path.open("x") as stream:
            json.dump(evidence, stream, sort_keys=True, indent=2)
            stream.write("\n")
        print(json.dumps({"status": "passed", "engine": engine,
                          "output": str(evidence_path)}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=20)
        print(f"A smoke interruption refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
