#!/usr/bin/env python3
"""Offline budget accounting model plus one fixed, non-security resource probe.

No engine adapter, arbitrary command runner, target file reader or fuzzing backend.
Virtual milliseconds describe a model; they are never reported as measured wall.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
KINDS = {"candidate", "no_candidate", "timeout", "start_failed"}


def natural(value, name, positive=False):
    if type(value) is not int or value < int(positive):
        raise ValueError(name + " must be a " + ("positive" if positive else "nonnegative") + " integer")


def unknown_resource():
    return {"value": None, "reason": "virtual model has no OS process or measured resource use"}


def simulate(targets, seeds, events, total_ms, attempt_cap_ms, max_attempts=128,
             cancel_at_ms=None, save_failure_at=None):
    """One accounting path for one or many opaque model labels, no execution."""
    natural(total_ms, "total_ms")
    natural(attempt_cap_ms, "attempt_cap_ms", True)
    natural(max_attempts, "max_attempts", True)
    if not targets or any(not isinstance(t, str) or not t for t in targets) or len(set(targets)) != len(targets):
        raise ValueError("nonempty unique target labels required")
    if not seeds or not events:
        raise ValueError("nonempty seeds and events required")
    for seed in seeds:
        natural(seed, "seed", True)
    for event in events:
        if event.get("kind") not in KINDS:
            raise ValueError("unsupported synthetic outcome")
        for name in ("duration_ms", "startup_ms", "cleanup_ms"):
            natural(event[name], name)
        if type(event.get("reaped", True)) is not bool:
            raise ValueError("reaped must be boolean")
    for name, value in (("cancel_at_ms", cancel_at_ms), ("save_failure_at", save_failure_at)):
        if value is not None:
            natural(value, name)
    attempts, elapsed = [], 0
    end_reason = None
    for index in range(max_attempts):
        if cancel_at_ms is not None and elapsed >= cancel_at_ms:
            end_reason = "cancelled"
            break
        remaining = max(total_ms - elapsed, 0)
        if remaining == 0:
            end_reason = "budget_exhausted"
            break
        event = events[index % len(events)]
        allocated = min(attempt_cap_ms, remaining)
        before = elapsed
        cutoff = min(before + allocated, total_ms)
        if cancel_at_ms is not None:
            cutoff = min(cutoff, cancel_at_ms)
        startup = min(event["startup_ms"], max(cutoff - elapsed, 0))
        elapsed += startup
        process_started = event["kind"] != "start_failed" and elapsed < cutoff
        process_start = elapsed if process_started else None
        process_wall = min(event["duration_ms"], max(cutoff - elapsed, 0)) if process_started else 0
        elapsed += process_wall
        cancelled = cancel_at_ms is not None and elapsed >= cancel_at_ms
        if cancelled:
            outcome = "cancelled"
        elif event["kind"] == "start_failed":
            outcome = "start_failed"
        elif not process_started or event["duration_ms"] > process_wall or event["kind"] == "timeout":
            outcome = "timeout"
        else:
            outcome = event["kind"]
        process_end = elapsed if process_started else None
        # Cleanup must be accounted even if it crosses the deadline.
        cleanup = event["cleanup_ms"]
        elapsed += cleanup
        debit = elapsed - before
        reaped = event.get("reaped", True) if process_started else None
        persisted = index != save_failure_at
        attempt = {"index": index, "target_id": targets[index % len(targets)],
            "seed": seeds[(index // len(targets)) % len(seeds)], "clock": "virtual_monotonic_ms",
            "dispatch_ms": before, "process_start_ms": process_start, "process_end_ms": process_end,
            "end_ms": elapsed, "allocated_ms": allocated, "reservation_before_ms": remaining,
            "remaining_after_ms": max(total_ms - elapsed, 0), "debit_ms": debit,
            "released_ms": max(allocated - debit, 0), "attempt_overrun_ms": max(debit - allocated, 0),
            "startup_ms": startup, "process_wall_ms": process_wall, "cleanup_ms": cleanup,
            "restart_cost_ms": startup + cleanup, "outcome": outcome,
            "simulated_process_started": process_started, "simulated_reaped": reaped,
            "simulated_persisted": persisted,
            "candidate_marker": event.get("marker") if outcome == "candidate" else None,
            "cpu_seconds": unknown_resource(), "peak_memory_bytes": unknown_resource()}
        attempts.append(attempt)
        if reaped is False:
            end_reason = "reap_failed"
        elif not persisted:
            end_reason = "persistence_failed"
        elif cancelled:
            end_reason = "cancelled"
        elif elapsed >= total_ms:
            end_reason = "budget_exhausted"
        elif debit == 0:
            end_reason = "clock_stalled"
        if end_reason:
            break
    if end_reason is None:
        end_reason = "attempt_cap"
    target_rows = []
    for target in targets:
        rows = [a for a in attempts if a["target_id"] == target]
        starts = sum(a["simulated_process_started"] for a in rows)
        target_rows.append({"target_id": target, "attempts": len(rows), "simulated_starts": starts,
                            "status": "model_started" if starts else "not_started",
                            "not_started_reason": None if starts else "start_failed_or_campaign_stopped" if rows else end_reason})
    return {"schema_version": 1, "policy_id": "A-01-offline-model-v1", "execution_kind": "deterministic_model_only",
        "clock_origin": "virtual attempt dispatch, not an observed OS start timestamp",
        "allocation_total_ms": total_ms, "attempt_cap_ms": attempt_cap_ms, "attempt_count_cap": max_attempts,
        "consumed_ms": elapsed, "remaining_ms": max(total_ms - elapsed, 0), "overrun_ms": max(elapsed - total_ms, 0),
        "reservation_sum_ms": sum(a["allocated_ms"] for a in attempts),
        "released_sum_ms": sum(a["released_ms"] for a in attempts),
        "end_reason": end_reason, "status": "incomplete" if end_reason in {"reap_failed", "persistence_failed", "clock_stalled"} else "model_completed",
        "outcome_counts": dict(Counter(a["outcome"] for a in attempts)), "attempts": attempts, "targets": target_rows,
        "actual_processes": 0, "cpu_seconds": unknown_resource(), "peak_memory_bytes": unknown_resource()}


def resource_probe():
    """Measure only a fixed arithmetic child. It launches no descendants."""
    if not hasattr(os, "fork") or not hasattr(os, "wait4"):
        return {"status": "unsupported", "reason": "fork/wait4 unavailable", "cpu_seconds": None, "peak_memory_bytes": None}
    started = time.monotonic_ns()
    try:
        pid = os.fork()
    except OSError as error:
        return {"status": "start_failed", "reason": str(error), "cpu_seconds": None, "peak_memory_bytes": None}
    if pid == 0:
        # Fixed benign arithmetic: no user-selected command, input file, or backend.
        value = sum(i * i for i in range(200_000))
        os._exit(0 if value > 0 else 1)
    waited, status, usage = os.wait4(pid, 0)
    ended = time.monotonic_ns()
    cpu = usage.ru_utime + usage.ru_stime
    scale = 1 if sys.platform == "darwin" else 1024 if sys.platform.startswith("linux") else None
    memory = int(usage.ru_maxrss * scale) if scale is not None and usage.ru_maxrss > 0 else None
    return {"status": "passed" if waited == pid and os.waitstatus_to_exitcode(status) == 0 else "failed",
        "scope": "one direct fixed arithmetic child; no descendants; no engine process-tree validation",
        "clock": "host_monotonic_ns", "start_call_ns": started, "reaped_ns": ended,
        "wall_seconds": (ended - started) / 1e9, "cpu_seconds": cpu,
        "cpu_measurement": "wait4 child user+system CPU", "peak_memory_bytes": memory,
        "memory_measurement": "wait4 ru_maxrss normalized for host OS",
        "memory_unknown_reason": None if memory is not None else "peak RSS unavailable or host unit unsupported",
        "reaped": waited == pid, "exit_code": os.waitstatus_to_exitcode(status)}


def file_ref(path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_json(path, value):
    # No overwrites and no successful return after a failed save.
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "runs"):
        raise ValueError("output must be under ignored runs/")
    spec = json.loads((output / "preregistered-model.json").read_text())
    conditions = {"created_at": datetime.now(timezone.utc).isoformat(), "owner": "miiz",
        "spec": file_ref(output / "preregistered-model.json"), "script": file_ref(__file__),
        "scope": file_ref(ROOT / "reports/n4-1-policy-a-2026-10-02/SCOPE.md"),
        "python": file_ref(sys.executable), "engine_execution": "not implemented or run"}
    write_json(output / "conditions.json", conditions)
    kwargs = {"seeds": spec["seed_cycle"], "events": spec["outcome_cycle"], "total_ms": spec["total_ms"],
              "attempt_cap_ms": spec["attempt_cap_ms"], "max_attempts": spec["attempt_count_cap"]}
    models = {}
    models["whole-model"] = simulate(["whole-placeholder"], **kwargs)
    models["split-model"] = simulate([f"piece-{i:02d}" for i in range(1, 22)], **kwargs)
    models["cancel-model"] = simulate(["cancel-placeholder"], **kwargs, cancel_at_ms=250)
    models["save-failure-model"] = simulate(["save-placeholder"], **kwargs, save_failure_at=0)
    reap = [{**spec["outcome_cycle"][0], "reaped": False}]
    models["reap-failure-model"] = simulate(["reap-placeholder"], **{**kwargs, "events": reap})
    stalled = [{"kind": "candidate", "duration_ms": 0, "startup_ms": 0, "cleanup_ms": 0}]
    models["no-progress-model"] = simulate(["clock-placeholder"], **{**kwargs, "events": stalled})
    for name, model in models.items():
        write_json(output / (name + ".json"), model)
    probe = resource_probe()
    write_json(output / "fixed-child-resource-probe.json", probe)
    write_json(output / "summary.json", {"schema_version": 1, "owner": "miiz", "scope": "partial, non-security validation only",
        "models": {k: file_ref(output / (k + ".json")) for k in models},
        "resource_probe": file_ref(output / "fixed-child-resource-probe.json"),
        "requested_engine_campaigns": file_ref(output / "requested-engine-not-run.json"),
        "A_01_complete": False})
    print(json.dumps({k: {f: m[f] for f in ("end_reason", "consumed_ms", "remaining_ms", "overrun_ms", "outcome_counts")}
                      for k, m in models.items()}))
    return 0 if probe["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
