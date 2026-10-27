#!/usr/bin/env python3
"""Bounded low-priority prototype command recorder; never runs judging or fuzzing."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/s-tag-wrapper-2026-10-27"
FROZEN_UNTIL = datetime.datetime(2026, 10, 28, 15, tzinfo=datetime.timezone.utc)
def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
def record(kind, value):
    with (OUT / ".cpu-contention.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = OUT / "cpu-contention.json"
        data = json.loads(path.read_text())
        data[kind].append(value)
        temporary = OUT / "cpu-contention.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
def gate():
    if os.getpriority(os.PRIO_PROCESS, 0) < 19:
        raise RuntimeError("nice 19 required")
    started = time.monotonic()
    while True:
        free = shutil.disk_usage(ROOT).free
        record("disk_checks", {"utc": now(), "free_bytes": free})
        if free >= 15 * 2**30:
            return free
        elapsed = time.monotonic() - started
        print(json.dumps({"status": "disk_wait", "free_gib": free/2**30, "elapsed_seconds": elapsed}), flush=True)
        if elapsed >= 1800:
            raise RuntimeError("disk remained below 15 GiB for 30 minutes")
        time.sleep(300)
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command or Path(command[0]).name not in {"python3", "circom"}:
        raise SystemExit("only Python prototype/calculation or Circom compilation is permitted")
    if Path(args.label).name != args.label or args.label in {".", ".."}:
        raise SystemExit("invalid label")
    if Path(command[0]).name == "circom":
        if hashlib.sha256(Path(command[0]).read_bytes()).hexdigest() != "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227":
            raise SystemExit("Circom SHA mismatch")
        if "--output" not in command or not Path(command[command.index("--output")+1]).resolve().is_relative_to(OUT):
            raise SystemExit("Circom output must be in the new prototype folder")
    free = gate()
    folder = OUT / "commands" / args.label
    folder.mkdir(parents=True, exist_ok=False)
    row = {"label": args.label, "command": command, "start_utc": now(), "cpu_contention": datetime.datetime.now(datetime.timezone.utc)<FROZEN_UNTIL,
           "nice": os.getpriority(os.PRIO_PROCESS, 0), "free_bytes_start": free}
    started = time.monotonic()
    env = dict(os.environ, RAYON_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    try:
        with (folder/"stdout.log").open("xb") as stdout, (folder/"stderr.log").open("xb") as stderr:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            row["owned_process_group"] = process.pid
            try:
                row["returncode"] = process.wait(timeout=args.timeout or None)
            finally:
                # Only the new session created above; never inspect or signal pre-existing jobs.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
    except subprocess.TimeoutExpired:
        row.update(returncode=124, error="own prototype child exceeded recorded timeout")
    except OSError as error:
        row.update(returncode=127, error=str(error))
    row.update(end_utc=now(), elapsed_seconds=time.monotonic()-started, free_bytes_end=shutil.disk_usage(ROOT).free)
    (folder/"command.json").write_text(json.dumps(row, ensure_ascii=False, indent=2)+"\n")
    record("records", {"record_path": str(folder/"command.json"), **row})
    print(json.dumps(row, ensure_ascii=False), flush=True)
    raise SystemExit(row["returncode"])
if __name__ == "__main__":
    main()
