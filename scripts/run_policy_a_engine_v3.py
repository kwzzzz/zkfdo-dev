#!/usr/bin/env python3
"""Policy-A v3: general targets, APFS whole clones, RSS cap, and compact attempts.

This imports the hash-pinned v1/v2 implementation instead of changing either file. Candidate
contents stay below the ignored run root; ledgers contain paths, hashes, timings, and outcomes.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable


HERE = Path(__file__).resolve().parent
GIB = 1024**3
DEFAULT_MEMORY_CAP_BYTES = 10 * GIB
RSS_POLL_SECONDS = 1.0
_ACTIVE_MEMORY_CAP_BYTES = DEFAULT_MEMORY_CAP_BYTES
_ACTIVE_METHOD = "split"
_ORIGINAL_COPYTREE = shutil.copytree


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


v2 = _load("run_policy_a_engine_v2_for_v3", "run_policy_a_engine_v2.py")
v1 = v2.v1
_ORIGINAL_VALIDATE_SPEC = v1.validate_spec


def validate_spec_v3(spec: Any) -> None:
    if not isinstance(spec, dict) or spec.get("schema_version") != 1:
        raise v1.SpecError("spec schema_version must be 1")
    method = spec.get("method")
    if method not in {"whole", "split"}:
        raise v1.SpecError("method must be whole or split")
    total = v1.positive_number(spec.get("total_budget_seconds"), "total_budget_seconds")
    cap = v1.positive_number(spec.get("attempt_cap_seconds"), "attempt_cap_seconds")
    if method == "whole" and cap != total:
        raise v1.SpecError("whole must allocate its full budget to the first attempt")
    if method == "split" and cap > total:
        raise v1.SpecError("split attempt cap cannot exceed total budget")
    memory = spec.get("memory_cap_bytes")
    if isinstance(memory, bool) or not isinstance(memory, int) or memory <= 0:
        raise v1.SpecError("memory_cap_bytes must be a positive integer")
    targets = spec.get("targets")
    if not isinstance(targets, list) or not targets:
        raise v1.SpecError("targets must be nonempty")

    # Reuse v1 validation after temporarily presenting its historical denominator.
    expected = 1 if method == "whole" else 21
    original_targets = targets
    try:
        if method == "whole" and len(targets) != 1:
            raise v1.SpecError("whole must contain exactly one entrypoint")
        chunks = [targets] if method == "whole" else [
            targets[index:index + expected] for index in range(0, len(targets), expected)]
        for chunk_index, chunk in enumerate(chunks):
            synthetic = list(chunk)
            while len(synthetic) < expected:
                clone = dict(chunk[-1])
                clone["target_id"] = (
                    f"{chunk[-1]['target_id']}#validation-{chunk_index}-{len(synthetic)}")
                synthetic.append(clone)
            spec["targets"] = synthetic
            _ORIGINAL_VALIDATE_SPEC(spec)
    finally:
        spec["targets"] = original_targets
    v2.validate_report_mode(spec)
    snapshot_ids = [row["id"] for row in spec["source_snapshots"]]
    if method == "split" and len(snapshot_ids) != len(set(snapshot_ids)):
        raise v1.SpecError("split snapshot IDs must be unique")
    if method == "split" and len({row["source_snapshot_id"] for row in targets}) != len(targets):
        raise v1.SpecError("every split target must use its own source snapshot")


def verify_plan_v3(spec: dict[str, Any], clean_roots: dict[str, Path]) -> dict[str, Any]:
    plan_pin = next((item for item in spec.get("pinned_files", []) if item["label"] == "plan"), None)
    if plan_pin is None:
        return {"status": "not_applicable", "reason": "no pinned plan declared"}
    if spec["method"] == "whole":
        return {"status": "provenance_only",
                "reason": "split plan is pinned but does not define the whole entrypoint"}
    plan = v1.load_json(Path(plan_pin["path"]))
    planned = plan.get("targets") if isinstance(plan, dict) else None
    if not isinstance(planned, list) or len(planned) != len(spec["targets"]):
        raise v1.SpecError("pinned plan target denominator differs from the spec")
    fingerprints = 0
    for index, (declared, row) in enumerate(zip(spec["targets"], planned, strict=True)):
        if row.get("target_id") != declared["target_id"]:
            raise v1.SpecError(f"pinned plan order differs at target {index}")
        root = clean_roots[declared["source_snapshot_id"]]
        entrypoint = root / declared["entrypoint_relative"]
        if not entrypoint.is_file() or v1.sha256_file(entrypoint) != declared["entrypoint_sha256"]:
            raise v1.SpecError(f"prepared entrypoint differs at target {index}")
        source_rows = row.get("source_fingerprints")
        snapshot_rows = row.get("snapshot_fingerprints")
        if not isinstance(source_rows, list) or not isinstance(snapshot_rows, list):
            raise v1.SpecError(f"pinned plan target {index} lacks fingerprints")
        if sorted(item.get("sha256") for item in source_rows) != sorted(
                item.get("sha256") for item in snapshot_rows):
            raise v1.SpecError(f"plan source/snapshot fingerprints differ at target {index}")
        for fingerprint in snapshot_rows:
            absolute = Path(fingerprint["path"])
            try:
                relative = absolute.relative_to(Path(declared["source_snapshot_path"]))
            except ValueError as error:
                raise v1.SpecError(f"snapshot fingerprint escapes target {index}") from error
            path = root / relative
            if not path.is_file() or v1.sha256_file(path) != fingerprint.get("sha256"):
                raise v1.SpecError(f"prepared fingerprint differs at target {index}: {relative}")
            fingerprints += 1
    return {"status": "verified", "target_count": len(planned),
            "fingerprints": fingerprints, "snapshot_model": "one source snapshot per target"}


def process_group_rss_bytes(group: int) -> int | None:
    """Return the simultaneous RSS sum for a process group from ps, in bytes."""
    try:
        result = subprocess.run(
            ["ps", "-axo", "pgid=,rss="],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    total_kib = 0
    observed = False
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            pgid, rss_kib = map(int, fields)
        except ValueError:
            continue
        if pgid == group:
            observed = True
            total_kib += rss_kib
    return total_kib * 1024 if observed else 0


def _empty_execution(outcome: str, attempt_dir: Path, campaign_start_ns: int,
                     error: str | None = None) -> dict[str, Any]:
    end = time.monotonic_ns()
    stdout = attempt_dir / "stdout.log"
    stderr = attempt_dir / "stderr.log"
    v1.atomic_write_bytes(stdout, b"")
    v1.atomic_write_bytes(stderr, b"")
    return {
        "outcome": outcome, "process_started": False,
        "process_start_offset_seconds": None, "process_end_offset_seconds": None,
        "spawn_call_end_offset_seconds": (end - campaign_start_ns) / 1e9,
        "exit_code": None, "timed_out": outcome == "deadline_before_spawn",
        "cancelled": False, "reaped": None, "process_group_empty": None,
        "resource": None, "observations": [], "reported_seed": None,
        "last_generation": None, "engine_reported_execution_seconds": [],
        "stdout_path": stdout, "stderr_path": stderr, "error": error,
    }


def spawn_and_measure_v3(command: list[str], attempt_dir: Path, deadline_ns: int,
                         campaign_start_ns: int,
                         cancel_check: Callable[[], bool]) -> dict[str, Any]:
    stdout_path = attempt_dir / "stdout.log"
    stderr_path = attempt_dir / "stderr.log"
    temporary = [attempt_dir / "stdout.log.tmp", attempt_dir / "stderr.log.tmp"]
    state = v1.StreamState(threading.Lock(), [])
    if time.monotonic_ns() >= deadline_ns:
        return _empty_execution("deadline_before_spawn", attempt_dir, campaign_start_ns)
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
    except OSError as error:
        return _empty_execution("spawn_error", attempt_dir, campaign_start_ns, str(error))
    process_start_ns = time.monotonic_ns()
    assert process.stdout is not None and process.stderr is not None
    drain_errors: list[str] = []
    threads = [
        threading.Thread(target=v1.drain_stream,
                         args=(process.stdout, temporary[0], state, "stdout", campaign_start_ns,
                               drain_errors), daemon=True),
        threading.Thread(target=v1.drain_stream,
                         args=(process.stderr, temporary[1], state, "stderr", campaign_start_ns,
                               drain_errors), daemon=True),
    ]
    for thread in threads:
        thread.start()
    status = usage = None
    timed_out = cancelled = memory_capped = monitor_failed = group_kill_sent = False
    peak_rss: int | None = None
    rss_unknown = False
    while status is None:
        try:
            waited, raw_status, raw_usage = os.wait4(process.pid, os.WNOHANG)
        except InterruptedError:
            continue
        except ChildProcessError as error:
            v1.kill_group(process.pid)
            raise v1.InfrastructureError("direct child could not be reaped with wait4") from error
        if waited == process.pid:
            status, usage = raw_status, raw_usage
            break
        rss = process_group_rss_bytes(process.pid)
        if rss is None:
            rss_unknown = True
            monitor_failed = True
            v1.kill_group(process.pid)
            group_kill_sent = True
        else:
            peak_rss = max(peak_rss or 0, rss)
            if rss > _ACTIVE_MEMORY_CAP_BYTES:
                memory_capped = True
                v1.kill_group(process.pid)
                group_kill_sent = True
        if cancel_check() and not memory_capped and not monitor_failed:
            cancelled = True
            v1.kill_group(process.pid)
            group_kill_sent = True
        elif time.monotonic_ns() >= deadline_ns and not memory_capped and not monitor_failed:
            timed_out = True
            v1.kill_group(process.pid)
            group_kill_sent = True
        if memory_capped or monitor_failed or cancelled or timed_out:
            while True:
                try:
                    waited, status, usage = os.wait4(process.pid, 0)
                    break
                except InterruptedError:
                    continue
            if waited != process.pid:
                raise v1.InfrastructureError("wait4 reaped an unexpected process")
            break
        time.sleep(min(RSS_POLL_SECONDS, max((deadline_ns - time.monotonic_ns()) / 1e9, 0)))
    process.returncode = v1.wait_status_code(status)
    process_end_ns = time.monotonic_ns()
    residual_killed = v1.process_group_exists(process.pid)
    if residual_killed:
        v1.kill_group(process.pid)
        group_kill_sent = True
    group_empty = v1.verify_group_empty(process.pid)
    if not group_empty:
        raise v1.InfrastructureError("process group remained live after kill/reap cleanup")
    v1.finish_logs(threads, temporary, [stdout_path, stderr_path], drain_errors)
    if memory_capped:
        outcome = "memory_cap"
    elif monitor_failed:
        outcome = "resource_monitor_failure"
    elif cancelled:
        outcome = "cancelled"
    elif timed_out:
        outcome = "timeout"
    elif process.returncode != 0:
        outcome = "engine_nonzero"
    elif state.candidate_seen:
        outcome = "candidate"
    elif state.no_candidate_seen:
        outcome = "no_candidate"
    else:
        outcome = "finished_unknown"
    resource = v1.rusage_record(usage)
    resource.update({
        "aggregate_process_tree_peak_memory_bytes": peak_rss,
        "aggregate_process_tree_peak_memory_cap_bytes": _ACTIVE_MEMORY_CAP_BYTES,
        "aggregate_process_tree_peak_memory_sampling": "ps process-group RSS sum every 1.0s",
        "aggregate_process_tree_peak_memory_unknown_reason": (
            "one or more ps samples failed" if rss_unknown else None
        ),
    })
    return {
        "outcome": outcome, "process_started": True,
        "process_start_offset_seconds": (process_start_ns - campaign_start_ns) / 1e9,
        "process_end_offset_seconds": (process_end_ns - campaign_start_ns) / 1e9,
        "spawn_call_end_offset_seconds": (process_start_ns - campaign_start_ns) / 1e9,
        "exit_code": process.returncode, "timed_out": timed_out,
        "cancelled": cancelled, "memory_capped": memory_capped,
        "resource_monitor_failed": monitor_failed, "reaped": True,
        "process_group_empty": group_empty,
        "residual_process_group_killed": residual_killed,
        "process_group_kill_sent": group_kill_sent, "resource": resource,
        "observations": sorted(state.observations,
                               key=lambda row: row["campaign_offset_seconds"]),
        "reported_seed": state.seed, "last_generation": state.generation,
        "engine_reported_execution_seconds": state.engine_reported_execution_seconds or [],
        "stdout_path": stdout_path, "stderr_path": stderr_path, "error": None,
    }


def apfs_clone_tree(source: Path | str, destination: Path | str, *args, **kwargs):
    """Whole-mode copy primitive. It deliberately has no ordinary-copy fallback."""
    source_path, destination_path = Path(source), Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["cp", "-cR", str(source_path), str(destination_path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise v1.InfrastructureError("APFS clone failed: " + result.stderr.strip())
    return destination_path


def copytree_v3(source, destination, *args, **kwargs):
    if _ACTIVE_METHOD == "whole":
        return apfs_clone_tree(source, destination)
    return _ORIGINAL_COPYTREE(source, destination, *args, **kwargs)


def tree_size(root: Path) -> tuple[int, int]:
    files = total = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files += 1
            total += path.stat().st_size
    return files, total


def atomic_write_v3(path: Path, value: Any) -> None:
    path = Path(path)
    if path.name == "result.json" and path.parent.parent.name == "attempts" and isinstance(value, dict):
        workspace = path.parent / "workspace"
        if workspace.is_dir():
            files, size = tree_size(workspace)
            started = time.monotonic_ns()
            shutil.rmtree(workspace)
            value["workspace_cleanup"] = {
                "status": "deleted", "files": files, "bytes": size,
                "wall_seconds": (time.monotonic_ns() - started) / 1e9,
            }
    return _ORIGINAL_ATOMIC_WRITE(path, value)


_ORIGINAL_ATOMIC_WRITE = v1.atomic_write
_ORIGINAL_RUN_CAMPAIGN = v1.run_campaign


def run_campaign_v3(spec, spec_sha256, snapshots, preflight_root, output, **kwargs):
    global _ACTIVE_MEMORY_CAP_BYTES, _ACTIVE_METHOD
    _ACTIVE_MEMORY_CAP_BYTES = spec["memory_cap_bytes"]
    _ACTIVE_METHOD = spec["method"]
    result = _ORIGINAL_RUN_CAMPAIGN(spec, spec_sha256, snapshots, preflight_root, output, **kwargs)
    ledger = result["ledger"]
    for point in (600, 3600):
        attempted = {row["target_id"] for row in ledger["attempts"]
                     if row.get("process_started")
                     and row.get("process_start_offset_seconds", float("inf")) <= point}
        ledger.setdefault("coverage_checkpoints", {})[str(point)] = {
            "elapsed_seconds": point,
            "attempted_targets": len(attempted),
            "eligible_targets": len(spec["targets"]),
            "coverage": len(attempted) / len(spec["targets"]),
            "status": "observed" if ledger["campaign_wall_seconds"] >= point else "campaign_ended_before_checkpoint",
        }
    ledger["memory_cap_bytes"] = spec["memory_cap_bytes"]
    sampled_peaks = [(row.get("resource") or {}).get("aggregate_process_tree_peak_memory_bytes")
                     for row in ledger["attempts"]]
    ledger["aggregate_process_tree_peak_memory_bytes"] = max(
        (value for value in sampled_peaks if value is not None), default=None)
    ledger["aggregate_process_tree_peak_memory_measurement"] = (
        "maximum simultaneous process-group RSS sum sampled every 1.0 second across attempts")
    ledger["workspace_policy"] = (
        "APFS clone via cp -cR only" if spec["method"] == "whole"
        else "one independently pinned source snapshot per split target"
    )
    _ORIGINAL_ATOMIC_WRITE(result["ledger_path"], ledger)
    result["ledger_sha256"] = v1.sha256_file(result["ledger_path"])
    return result


@contextmanager
def installed():
    previous = (v1.validate_spec, v1.spawn_and_measure, v1.run_campaign,
                v1.atomic_write, v1.shutil.copytree, v1.ensure_no_symlinks, v1.verify_plan)
    v1.validate_spec = validate_spec_v3
    v1.spawn_and_measure = v2.with_report_capture(spawn_and_measure_v3)
    v1.run_campaign = run_campaign_v3
    v1.atomic_write = atomic_write_v3
    v1.shutil.copytree = copytree_v3
    v1.ensure_no_symlinks = lambda _root: None
    v1.verify_plan = verify_plan_v3
    try:
        yield
    finally:
        (v1.validate_spec, v1.spawn_and_measure, v1.run_campaign,
         v1.atomic_write, v1.shutil.copytree, v1.ensure_no_symlinks, v1.verify_plan) = previous


def self_test(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    base = v1.self_test(output / "v1-state-machine")
    attempt = output / "memory-cap-attempt"
    attempt.mkdir()
    global _ACTIVE_MEMORY_CAP_BYTES
    _ACTIVE_MEMORY_CAP_BYTES = 24 * 1024 * 1024
    command = [sys.executable, "-c",
               "import time; x=bytearray(80*1024*1024); print(len(x), flush=True); time.sleep(5)"]
    start = time.monotonic_ns()
    measured = spawn_and_measure_v3(command, attempt, start + int(5e9), start, lambda: False)
    checks = {
        "v1_state_machine": all(base["summary"]["checks"].values()),
        "memory_cap_outcome": measured["outcome"] == "memory_cap",
        "memory_cap_reaped": measured["reaped"] is True and measured["process_group_empty"] is True,
        "memory_cap_measured": measured["resource"]["aggregate_process_tree_peak_memory_bytes"]
        > _ACTIVE_MEMORY_CAP_BYTES,
    }
    if not all(checks.values()):
        raise AssertionError(f"v3 self-test failed: {checks}")
    summary = {"schema_version": 3, "kind": "policy_a_v3_self_test",
               "checks": checks,
               "memory_attempt": {
                   **measured,
                   "stdout_path": str(measured["stdout_path"]),
                   "stderr_path": str(measured["stderr_path"]),
               },
               "v1_summary": v1.relative_to(base["summary_path"], output)}
    path = output / "self-test-v3.json"
    _ORIGINAL_ATOMIC_WRITE(path, summary)
    return {"summary_path": path, "summary_sha256": v1.sha256_file(path), "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("preflight", "run"):
        item = sub.add_parser(action)
        item.add_argument("--spec", type=Path, required=True)
        item.add_argument("--output", type=Path, required=True)
        if action == "run":
            item.add_argument("--preflight", type=Path, required=True)
            item.add_argument("--cancel-file", type=Path)
    item = sub.add_parser("self-test")
    item.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "self-test":
        result = self_test(args.output)
        print(json.dumps({"summary_path": str(result["summary_path"]),
                          "summary_sha256": result["summary_sha256"]}))
        return 0
    forwarded = [args.action, "--spec", str(args.spec)]
    if args.action == "preflight":
        spec = json.loads(args.spec.read_text())
        global _ACTIVE_METHOD
        _ACTIVE_METHOD = spec["method"]
        forwarded += ["--output", str(args.output)]
    else:
        forwarded += ["--preflight", str(args.preflight), "--output", str(args.output)]
        if args.cancel_file:
            forwarded += ["--cancel-file", str(args.cancel_file)]
    with installed():
        return v1.main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
