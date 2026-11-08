#!/usr/bin/env python3
"""Round 4c internal-only monitor. Never reads the external J cache or old target."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
RUNROOT = ROOT / "runs/s-round4-2026-10-27"
OUT = RUNROOT / "round4c/monitoring"
TARGET = RUNROOT / "cargo-target"
GIB = 2**30


def now():
    return datetime.now(timezone.utc).isoformat()


def capture(argv):
    p = subprocess.run(argv, capture_output=True, text=True, check=False)
    return {"argv": argv, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def free_bytes(path="/"):
    r = capture(["/bin/df", "-k", path])
    if r["returncode"]:
        raise RuntimeError("df failed: " + r["stderr"])
    return int(r["stdout"].splitlines()[-1].split()[3]) * 1024


def snapshot():
    return {"utc": now(), "internal_free_bytes": free_bytes(),
            "cache_free_bytes": None, "cache_status": "not queried: internal-only 4c task",
            "swap": capture(["/usr/sbin/sysctl", "vm.swapusage"]),
            "vm_files": capture(["/bin/ls", "-l", "/System/Volumes/VM"])}


def owned(path):
    path = Path(path).absolute()
    if not path.resolve().is_relative_to(RUNROOT.resolve()) or path == RUNROOT:
        raise ValueError("output must remain under Round 4")
    return path


def write_new(path, value):
    path = owned(path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def output_bytes():
    # This is the only recursively measured run directory.
    total = 0
    for base, dirs, files in os.walk(RUNROOT, followlinks=False):
        if Path(base) == RUNROOT:
            dirs[:] = [name for name in dirs if name != "cargo-target"]
        for name in dirs + files:
            p = Path(base) / name
            if p.is_symlink():
                raise RuntimeError("symlink found in owned output")
        total += sum((Path(base) / name).stat().st_size for name in files)
    return total


def gate():
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise RuntimeError("nice 19 required")
    started = time.monotonic()
    while free_bytes() < 20 * GIB:
        with (OUT / "disk-waits.jsonl").open("a") as f:
            f.write(json.dumps({"utc": now(), "free_bytes": free_bytes()}) + "\n")
        if time.monotonic() - started >= 3 * 3600:
            raise RuntimeError("internal disk stayed below 20 GiB for three hours")
        print("Waiting for 20 GiB internal free space; next check in five minutes.", flush=True)
        # Short waits let the tool be polled and interrupted normally.
        for _ in range(5):
            time.sleep(60)
    # Internal-only jobs never write this image. Its executor owns the dynamic
    # 1.2*peak+retained gate; a pre-existing low value is recorded, not changed.
    # No external cache is read or written by this monitor.
    if output_bytes() >= 2_000_000_000:
        raise RuntimeError("Round 4 internal output limit reached")


def target_size():
    if TARGET.is_symlink():
        raise RuntimeError("internal cargo target must not be a symlink")
    if not TARGET.exists():
        return 0
    r = capture(["/usr/bin/du", "-sk", str(TARGET)])
    if r["returncode"]:
        raise RuntimeError("target size unavailable; cargo refused: " + r["stderr"].strip())
    return int(r["stdout"].split()[0]) * 1024


def compile_output_bytes(argv):
    if Path(argv[0]).name != "circom":
        return None
    flags = [i for i, value in enumerate(argv) if value in ("-o", "--output")]
    if len(flags) != 1 or flags[0] + 1 >= len(argv):
        raise ValueError("one explicit circom output directory required")
    folder = owned(argv[flags[0] + 1])
    return sum(p.stat().st_size for p in folder.iterdir() if p.is_file())


def child(plan_path):
    plan_path = owned(plan_path)
    plan = json.loads(plan_path.read_text())
    os.setsid()
    # Written by the newly created child after setsid, not inferred from ps.
    write_new(plan_path.parent / "child.json", {"pid": os.getpid(), "ppid": os.getppid()})
    os.chdir(ROOT)
    (OUT / "test-tmp").mkdir(exist_ok=True)
    os.execvpe(plan["argv"][0], plan["argv"], dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                 RAYON_NUM_THREADS="1", OMP_NUM_THREADS="1", CARGO_BUILD_JOBS="1",
                 TMPDIR=str(OUT / "test-tmp"),
                 CARGO_TARGET_DIR=str(TARGET), CARGO_INCREMENTAL="0"))


def stop_owned(process, folder):
    p = folder / "child.json"
    if p.exists():
        row = json.loads(p.read_text())
        if row["ppid"] != process.pid or row["pid"] <= 1:
            raise RuntimeError("child ownership could not be established")
        # The child itself recorded its new session/group. Never use broad pkill.
        try:
            os.killpg(row["pid"], signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(row["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
    else:
        # No command has executed before child.json is written.
        process.terminate()
    process.wait(timeout=10)


def append_record(row):
    path = OUT / "disk-log.tsv"
    keys = ["start_utc", "end_utc", "label", "attempt", "status", "returncode",
            "elapsed_seconds", "maximum_resident_set_size_bytes", "artifact_bytes", "round_output_bytes",
            "target_bytes_before", "target_bytes_after", "argv", "before", "after", "receipt"]
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, keys, delimiter="\t")
        if new:
            w.writeheader()
        w.writerow({k: json.dumps(row.get(k), ensure_ascii=False) if isinstance(row.get(k), (dict, list))
                    else row.get(k) for k in keys})
    cpu = OUT / "cpu-contention.json"
    entries = json.loads(cpu.read_text()) if cpu.exists() else []
    entries.append({k: row.get(k) for k in ("start_utc", "end_utc", "label", "argv", "status", "receipt")} | {
        "nice": 19, "overlaps_active_judging": row["start_utc"] < "2026-10-28T15:00:00+00:00"})
    cpu.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")


def run(argv, label, timeout=1800, cargo=False):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", label):
        raise ValueError("invalid job label")
    if not argv or not 1 <= timeout <= 10800:
        raise ValueError("invalid command or timeout")
    if cargo:
        jobs = [i for i, value in enumerate(argv) if value in ("-j", "--jobs")]
        if len(jobs) != 1 or jobs[0] + 1 >= len(argv) or argv[jobs[0]+1] != "1":
            raise ValueError("cargo requires explicit -j 1")
    for attempt in (1, 2):
        gate()
        folder = OUT / "monitor" / f"{label}-{attempt}"
        folder.mkdir(parents=True, exist_ok=False)
        before = snapshot()
        target_before = target_size() if cargo else None
        if cargo:
            baseline = OUT / "cargo-started.json"
            if target_before > 8 * GIB:
                raise RuntimeError("internal cargo target exceeds 8 GiB")
            if not baseline.exists():
                if before["internal_free_bytes"] < 30 * GIB:
                    raise RuntimeError("first cargo build requires 30 GiB internal free")
                write_new(baseline, {"bytes": target_before, "utc": now(), "target": str(TARGET)})
        plan = folder / "command.json"
        compile_output_bytes(argv)  # Validate an explicit, owned compiler destination before launch.
        write_new(plan, {"argv": list(argv), "cwd": str(ROOT)})
        start, tick = time.monotonic(), time.monotonic()
        row = {"label": label, "attempt": attempt, "argv": list(argv), "start_utc": now(),
               "before": before, "target_bytes_before": target_before, "status": "running"}
        with (folder / "stdout.log").open("xb") as out, (folder / "stderr-time.log").open("xb") as err:
            process = subprocess.Popen(["/usr/bin/time", "-l", sys.executable, "-B", str(Path(__file__).resolve()),
                                        "_child", str(plan)], stdout=out, stderr=err, start_new_session=True)
            try:
                while process.poll() is None:
                    elapsed = time.monotonic() - start
                    if time.monotonic() >= tick:
                        free = free_bytes()
                        with (folder / "samples.jsonl").open("a") as samples:
                            samples.write(json.dumps({"utc": now(), "internal_free_bytes": free}) + "\n")
                        tick = time.monotonic() + 10
                        if free < 18 * GIB:
                            row["status"] = "중단(내장)"
                            stop_owned(process, folder)
                            break
                        if cargo and target_size() > 8 * GIB:
                            row["status"] = "cargo_target_8GiB_limit"
                            stop_owned(process, folder)
                            break
                        if output_bytes() >= 2_000_000_000:
                            row["status"] = "output_limit"
                            stop_owned(process, folder)
                            break
                    if elapsed >= timeout:
                        row["status"] = "timeout"
                        stop_owned(process, folder)
                        break
                    time.sleep(0.1)
            except BaseException:
                stop_owned(process, folder)
                raise
            row["returncode"] = process.wait()
        row.update(end_utc=now(), elapsed_seconds=time.monotonic() - start, after=snapshot())
        if row["status"] == "running":
            row["status"] = "completed" if row["returncode"] == 0 else "failed"
        timing = (folder / "stderr-time.log").read_text(errors="replace")
        match = re.search(r"(\d+)\s+maximum resident set size", timing)
        row["maximum_resident_set_size_bytes"] = int(match.group(1)) if match else None
        row["artifact_bytes"] = compile_output_bytes(argv)
        row["round_output_bytes"] = output_bytes()
        row["target_bytes_after"] = target_size() if cargo else None
        if cargo and row["target_bytes_after"] > 8 * GIB:
            row["status"] = "cargo_target_8GiB_limit"
        row["receipt"] = write_new(folder / "result.json", row)
        append_record(row)
        if row["status"] != "중단(내장)":
            return row
        if attempt == 2:
            write_new(folder / "deferred.json", {"reason": "two internal-disk interruptions", "argv": list(argv)})
            return row
    raise AssertionError("unreachable")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "_child":
        child(sys.argv[2])
        return
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--label", required=True)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--cargo", action="store_true")
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    r = run(command, a.label, a.timeout, a.cargo)
    print(json.dumps({k: r[k] for k in ("label", "status", "returncode", "receipt")}, ensure_ascii=False))
    raise SystemExit(0 if r["status"] == "completed" else 2)


if __name__ == "__main__":
    main()
