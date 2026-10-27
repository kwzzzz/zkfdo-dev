#!/usr/bin/env python3
"""Low-priority, single-job inspection development command with bounded disk use."""
import argparse
import fcntl
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/s-inspection-improve-2026-10-27c"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command or not (command[0] == "cargo" or Path(command[0]).name in {"s_inspection_audit", "s_inspection_prepare_round3"}):
        raise SystemExit("only cargo checks/builds and the inspection-only audit example are permitted")
    if command[0] == "cargo":
        if command[1] not in {"fmt", "clippy", "test", "build"}:
            raise SystemExit("unsupported cargo command")
        if command[1] != "fmt" and "-j" not in command:
            command[2:2] = ["-j", "1"]
        if command[1] == "test" and "--list" not in command:
            skips = json.loads((OUT / "cargo-command-reference.json").read_text())["skipped_J_tests"]
            if "--" not in command:
                command.append("--")
            for skip in skips:
                command.extend(["--skip", skip])
            command.extend(["--test-threads=1"])
    if os.getpriority(os.PRIO_PROCESS, 0) < 19:
        raise SystemExit("run with nice -n 19")
    if shutil.disk_usage(ROOT).free < 15 * 2**30:
        raise SystemExit("internal disk free space below 15 GiB")
    folder = OUT / args.label
    folder.mkdir(exist_ok=False)
    stamp = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    record = {"command": command, "start_utc": stamp(), "cpu_contention": True,
              "nice": os.getpriority(os.PRIO_PROCESS, 0), "jobs": 1,
              "free_bytes_start": shutil.disk_usage(ROOT).free}
    (folder / "command.json").write_text(json.dumps(record, indent=2) + "\n")
    env = dict(os.environ, CARGO_BUILD_JOBS="1", CARGO_INCREMENTAL="0", CARGO_NET_OFFLINE="true",
               RAYON_NUM_THREADS="1", RUST_TEST_THREADS="1")
    started = time.monotonic()
    with (folder / "output.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        record["child_pid"] = process.pid
        while process.poll() is None:
            if shutil.disk_usage(ROOT).free < 15 * 2**30:
                record["stop_reason"] = "internal disk free space below 15 GiB"
                process.terminate()
                break
            time.sleep(2)
        record["returncode"] = process.wait()
    record.update(end_utc=stamp(), elapsed_seconds=time.monotonic()-started,
                  free_bytes_end=shutil.disk_usage(ROOT).free)
    (folder / "command.json").write_text(json.dumps(record, indent=2) + "\n")
    ledger = OUT / "cpu-contention.json"
    with (OUT / ".cpu-contention.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(ledger.read_text())
        data["records"].append({"kind": "cargo" if command[0] == "cargo" else "inspection", "label": args.label,
                                "record_path": str(folder / "command.json"), **record})
        temporary = ledger.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.replace(ledger)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    raise SystemExit(record["returncode"] or (1 if "stop_reason" in record else 0))

if __name__ == "__main__":
    main()
