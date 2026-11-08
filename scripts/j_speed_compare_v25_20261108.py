#!/usr/bin/env python3
"""Sequential A-development J v2.5 comparison against preserved v2.4 j1/j4 records."""
from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import sys
import time

import j_speed_compare_20261103 as base

ROOT = base.ROOT
BASELINE = ROOT / "runs/j-speed-2026-11-03/comparison-v3"
RUN_ROOT = ROOT / "runs/preexp-cleanup-2026-11-08/j-v25-comparison-v1"
BINARY = ROOT / "runs/preexp-cleanup-2026-11-08/target/debug/zkfdo-j-v25"
SUSPEND_THRESHOLD_SECONDS = 0.25


class SuspendClock:
    """Compare suspend-inclusive and suspend-exclusive clocks, independent of UTC."""

    def __init__(self):
        if sys.platform == "darwin":
            self.library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            self.library.mach_absolute_time.restype = ctypes.c_uint64
            self.library.mach_continuous_time.restype = ctypes.c_uint64

            class Timebase(ctypes.Structure):
                _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

            value = Timebase()
            if self.library.mach_timebase_info(ctypes.byref(value)) or not value.denom:
                raise RuntimeError("mach timebase unavailable; refusing unverified timing")
            self.factor = value.numer / value.denom / 1e9
            self.source = "mach_continuous_time_minus_mach_absolute_time"
        elif sys.platform.startswith("linux") and hasattr(time, "CLOCK_BOOTTIME"):
            self.source = "CLOCK_BOOTTIME_minus_CLOCK_MONOTONIC"
        else:
            raise RuntimeError("suspend-aware clock unavailable; refusing timing run")

    def sample(self):
        if sys.platform == "darwin":
            return {"continuous": self.library.mach_continuous_time() * self.factor,
                    "awake": self.library.mach_absolute_time() * self.factor}
        return {"continuous": time.clock_gettime(time.CLOCK_BOOTTIME),
                "awake": time.clock_gettime(time.CLOCK_MONOTONIC)}


def sleep_assessment(before, after, source):
    continuous = after["continuous"] - before["continuous"]
    awake = after["awake"] - before["awake"]
    suspended = max(0.0, continuous - awake)
    return {"clock_source": source, "continuous_seconds": continuous, "awake_seconds": awake,
            "suspended_seconds": suspended, "threshold_seconds": SUSPEND_THRESHOLD_SECONDS,
            "valid_without_suspend": suspended <= SUSPEND_THRESHOLD_SECONDS}


def tool_snapshot():
    return {name: {"path": str(path), "sha256": base.sha(path)} for name, path in base.TOOLS.items()}


def inventory(baseline):
    rows = json.loads((baseline / "inventory.json").read_text())
    if len(rows) != 14 or [row["index"] for row in rows] != list(range(14)):
        raise RuntimeError("expected the preserved ordered 14-request inventory")
    for row in rows:
        if base.sha(Path(row["path"])) != row["sha256"]:
            raise RuntimeError(f"preserved request changed: {row['index']}")
    return rows


def compare_baselines(index, result, baseline):
    compared = {}
    for arm in ("j1", "j4"):
        folder = baseline / "requests" / f"{index:02d}" / arm
        record_path = folder / "record.json"
        previous = json.loads(record_path.read_text())
        result_path = folder / "out/result.json"
        if previous["status"] != "complete" or base.sha(result_path) != previous["result_sha256"]:
            raise RuntimeError(f"preserved {index}/{arm} result identity mismatch")
        compared[arm] = {**base.compare_results(json.loads(result_path.read_text()), result),
                         "record_path": str(record_path), "record_sha256": base.sha(record_path),
                         "result_sha256": previous["result_sha256"],
                         "baseline_wall_seconds": previous["resources"]["wall_seconds"],
                         "baseline_cpu_seconds": previous["resources"]["cpu_seconds"],
                         # The historical report identifies request 01 j4 as suspended.
                         "baseline_timing_valid": not (index == 1 and arm == "j4")}
    return compared


def summary(run_root):
    rows = [json.loads(path.read_text()) for path in sorted(run_root.glob("requests/*/record.json"))]
    valid = [row for row in rows if row.get("execution_valid")]
    data = {"schema": "j-v25-comparison-index-v1", "updated": base.utc(), "rows": rows,
            "recorded": len(rows), "execution_valid": len(valid),
            "semantic_equal": sum(row.get("semantic_equal", False) for row in rows),
            "basis_equal": sum(row.get("basis_equal", False) for row in rows),
            "timing_comparison": {"baseline": "preserved v2.4 jobs1; different execution date, not paired",
                                  "requests": [row["request_index"] for row in valid],
                                  "v24_wall_seconds": sum(row["comparisons"]["j1"]["baseline_wall_seconds"] for row in valid),
                                  "v25_wall_seconds": sum(row["resources"]["wall_seconds"] for row in valid),
                                  "v24_cpu_seconds": sum(row["comparisons"]["j1"]["baseline_cpu_seconds"] for row in valid),
                                  "v25_cpu_seconds": sum(row["resources"]["cpu_seconds"] for row in valid)}}
    base.atomic_summary(run_root / "index.json", data)
    return data


def run_one(row, run_root, baseline, binary):
    index = row["index"]
    directory = run_root / "requests" / f"{index:02d}"
    record_path = directory / "record.json"
    if record_path.exists():
        print(json.dumps({"request_index": index, "status": "already_recorded"}), flush=True)
        return json.loads(record_path.read_text())
    base.disk_gate(run_root)
    request = Path(row["path"])
    before = base.source_snapshot(request)
    preserved = json.loads((baseline / f"request-{index:02d}-inputs.json").read_text())
    if before != preserved:
        raise RuntimeError(f"request {index} source snapshot differs from preserved comparison")
    tools_before = tool_snapshot()
    if tools_before != json.loads((baseline / "tools.json").read_text()):
        raise RuntimeError("tool content differs from preserved v2.4 comparison")
    binary_before = base.sha(binary)
    base.bind_identity(run_root, "binary-v25", {"path": str(binary), "sha256": binary_before})
    base.bind_identity(run_root, "tools", tools_before)
    base.bind_identity(run_root, f"request-{index:02d}-inputs", before)
    clock = SuspendClock()
    directory.mkdir(parents=True, exist_ok=False)
    argv = [binary, "--request", request, "--output", directory / "out", "--cache", directory / "cache",
            "--instance-store", directory / "instance-store", "--j-jobs", "1"]
    for name, path in base.TOOLS.items():
        argv.extend([f"--{name}-bin", path])
    base.save_new(directory / "start.json", {"schema": "j-v25-start-v1", "utc": base.utc(),
                  "request_index": index, "argv": [str(value) for value in argv],
                  "request_sha256": row["sha256"], "binary_sha256": binary_before,
                  "cache_policy": "empty request-local cache and instance store; no cross-request artifact reuse",
                  "minimum_free_bytes": base.MIN_FREE_BYTES, "clock_source": clock.source})
    print(json.dumps({"request_index": index, "status": "running", "utc": base.utc()}), flush=True)
    clock_before = clock.sample()
    try:
        resources = base.run_process(argv, directory)
    except BaseException:
        base.save_new(directory / "suspend-interrupted.json", sleep_assessment(clock_before, clock.sample(), clock.source))
        raise
    sleep = sleep_assessment(clock_before, clock.sample(), clock.source)
    tools_after = tool_snapshot()
    binary_after = base.sha(binary)
    after = base.source_snapshot(request)
    result_path = directory / "out/result.json"
    record = {"schema": "j-v25-record-v1", "request_index": index, "request": str(request),
              "request_sha256": row["sha256"], "resources": resources, "suspend": sleep,
              "binary_sha256_before": binary_before, "binary_sha256_after": binary_after,
              "tools_before": tools_before, "tools_after": tools_after,
              "inputs_unchanged": before == after, "tools_unchanged": tools_before == tools_after,
              "binary_unchanged": binary_before == binary_after,
              "result": str(result_path), "execution_valid": False, "status": "engine_error"}
    if resources["returncode"] == 0 and result_path.exists():
        result = json.loads(result_path.read_text())
        comparisons = compare_baselines(index, result, baseline)
        record.update(result_sha256=base.sha(result_path), comparisons=comparisons,
                      semantic_equal=all(item["semantic_equal"] for item in comparisons.values()),
                      basis_equal=all(item["basis_equal"] for item in comparisons.values()),
                      preparation=result.get("preparation"), verdict_counts=result.get("verdict_counts"),
                      semantic_sha256=base.canonical_sha(base.semantic_fingerprint(result)),
                      basis_sha256=base.canonical_sha(base.basis_fingerprint(result)))
        record["execution_valid"] = all((sleep["valid_without_suspend"], record["inputs_unchanged"],
                                         record["tools_unchanged"], record["binary_unchanged"]))
        record["status"] = ("invalid_suspend" if not sleep["valid_without_suspend"] else
                            "input_or_tool_drift" if not record["execution_valid"] else
                            "semantic_mismatch" if not record["semantic_equal"] else
                            "basis_mismatch" if not record["basis_equal"] else "complete")
        sidecar = directory / "out/j-speed.json"
        record["speed_sidecar"] = {"path": str(sidecar), "sha256": base.sha(sidecar)}
    base.save_new(record_path, record)
    summary(run_root)
    print(json.dumps({"request_index": index, "status": record["status"], "wall_seconds": resources["wall_seconds"],
                      "cpu_seconds": resources["cpu_seconds"], "semantic_equal": record.get("semantic_equal"),
                      "basis_equal": record.get("basis_equal"), "suspended_seconds": sleep["suspended_seconds"]}), flush=True)
    if not all((record["inputs_unchanged"], record["tools_unchanged"], record["binary_unchanged"])):
        raise RuntimeError("input/tool drift: remaining requests were not started")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--binary", type=Path, default=BINARY)
    parser.add_argument("--request-index", type=int, choices=range(14))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    rows = inventory(args.baseline)
    if args.list:
        print(json.dumps(rows, indent=2))
        return 0
    run_root = args.run_root.resolve()
    if not run_root.is_relative_to((ROOT / "runs").resolve()):
        parser.error("generated artifacts must stay under ignored runs/")
    run_root.mkdir(parents=True, exist_ok=True)
    with (run_root / ".runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base.bind_identity(run_root, "inventory", rows)
        base.bind_identity(run_root, "source-manifest", [{"path": str(path.relative_to(ROOT)), "sha256": base.sha(path)}
                           for path in sorted((ROOT / "src").rglob("*.rs"))])
        for row in rows:
            if args.request_index is None or row["index"] == args.request_index:
                run_one(row, run_root, args.baseline.resolve(), args.binary.resolve())
        result = summary(run_root)
    return 0 if all(row["status"] == "complete" for row in result["rows"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
