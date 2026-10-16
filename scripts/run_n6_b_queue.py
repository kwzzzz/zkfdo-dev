#!/usr/bin/env python3
"""Two-stage N6-B queue: finish every preflight before any W/S campaign."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_policy_a_engine_v3.py"
ARTIFACT_SUFFIXES = {".r1cs", ".wasm", ".cpp", ".dat", ".o"}
_stop_after_units = threading.Event()
_state_lock = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def directory_size(path: Path) -> tuple[int, int]:
    files = size = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            files += 1
            size += item.stat().st_size
    return files, size


def load_queue(queue_path: Path) -> dict[str, Any]:
    queue = json.loads(queue_path.read_text())
    queue["_path"] = str(queue_path.resolve())
    if queue.get("schema_version") != 2 or queue.get("status") != "preflight_pending":
        raise ValueError("queue is not a frozen N6-B preflight-pending queue")
    if len(queue.get("units", [])) != 30 or queue.get("concurrency") != 3:
        raise ValueError("expected 30 fixed stage-1 units and concurrency 3")
    if queue.get("preflight_spec_count") != 60:
        raise ValueError("queue must require all 60 spec preflights")
    return queue


def spec_for(unit: dict[str, Any], method: str) -> tuple[Path, str]:
    key = "whole" if method == "W" else "split"
    spec = ROOT / unit[f"{key}_spec"]
    expected = unit[f"{key}_spec_sha256"]
    if sha256(spec) != expected:
        raise ValueError(f"spec changed for {unit['unit_id']} {method}")
    return spec, expected


def run_command(argv: list[str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("xb") as stream:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=stream,
                              stderr=subprocess.STDOUT, start_new_session=True).returncode


def cleanup_preflight_artifacts(preflight_root: Path) -> dict[str, Any]:
    """Inventory, persist, verify, then delete only compiler outputs below artifacts/."""
    plan_path = preflight_root / "artifact-deletion-plan.json"
    result_path = preflight_root / "artifact-cleanup.json"
    if result_path.is_file():
        return json.loads(result_path.read_text())
    artifacts_root = preflight_root / "compile"
    artifacts = []
    if artifacts_root.is_dir():
        for path in sorted(artifacts_root.glob("*/artifacts/**/*")):
            if path.is_file() and not path.is_symlink() and path.suffix in ARTIFACT_SUFFIXES:
                artifacts.append({"path": path.relative_to(preflight_root).as_posix(),
                                  "sha256": sha256(path), "bytes": path.stat().st_size})
    plan = {"schema_version": 1, "kind": "preflight_compiler_artifact_deletion_plan",
            "recorded_at": now(), "extensions": sorted(ARTIFACT_SUFFIXES),
            "artifact_count": len(artifacts),
            "artifact_bytes": sum(row["bytes"] for row in artifacts),
            "artifacts": artifacts}
    atomic_json(plan_path, plan)
    deleted = []
    for row in artifacts:
        path = preflight_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["bytes"] or sha256(path) != row["sha256"]:
            raise ValueError(f"preflight artifact changed after inventory: {row['path']}")
        path.unlink()
        deleted.append(row)
    result = {"schema_version": 1, "kind": "preflight_compiler_artifact_cleanup",
              "deletion_plan": plan_path.name, "deletion_plan_sha256": sha256(plan_path),
              "finished_at": now(), "status": "completed",
              "deleted_count": len(deleted),
              "deleted_bytes": sum(row["bytes"] for row in deleted),
              "remaining_recorded_artifacts": sum((preflight_root / row["path"]).exists()
                                                  for row in artifacts)}
    atomic_json(result_path, result)
    return result


def preflight_key(unit: dict[str, Any], method: str) -> str:
    return f"{unit['unit_id']}:{method}"


def assert_preflight_equivalent(source_spec: Path, destination_spec: Path) -> None:
    """Prove that two seed specs have the same seed-independent preflight inputs."""
    excluded = {"campaign_id", "initial_seed"}
    source = {key: value for key, value in json.loads(source_spec.read_text()).items()
              if key not in excluded}
    destination = {key: value for key, value in json.loads(destination_spec.read_text()).items()
                   if key not in excluded}
    if source != destination:
        raise ValueError("preflight reuse refused: specs differ outside campaign_id/initial_seed")


def materialize_reused_preflight(unit: dict[str, Any], method: str, output: Path,
                                 source_row: dict[str, Any], *, exact_spec: bool = False) -> dict[str, Any]:
    spec, expected = spec_for(unit, method)
    source_spec = ROOT / source_row["spec"]
    if exact_spec:
        if sha256(source_spec) != expected or source_row.get("spec_sha256") != expected:
            raise ValueError("exact preflight reuse refused: source and destination specs differ")
    else:
        assert_preflight_equivalent(source_spec, spec)
    source_ledger = ROOT / source_row["preflight"]
    if not source_ledger.is_file():
        return run_preflight(unit, method, output)
    root = output / "preflight" / unit["unit_id"] / method
    if root.exists():
        raise ValueError(f"reused preflight destination already exists: {root}")
    root.mkdir(parents=True)
    started_at = now()
    started_ns = time.monotonic_ns()
    ledger = json.loads(source_ledger.read_text())
    source_root = source_ledger.parent
    for snapshot in ledger.get("source_snapshots", []):
        absolute = (source_root / snapshot["copied_path"]).resolve()
        snapshot["copied_path"] = os.path.relpath(absolute, root)
    for compile_row in ledger.get("compile", []):
        for name in ("stdout_path", "stderr_path"):
            if compile_row.get(name):
                absolute = (source_root / compile_row[name]).resolve()
                compile_row[name] = os.path.relpath(absolute, root)
        compile_row["source_wall_seconds"] = compile_row.get("wall_seconds")
        compile_row["wall_seconds"] = 0.0 if compile_row.get("wall_seconds") is not None else None
        compile_row["resource"] = None
        compile_row["reuse_claim"] = True
    original_wall = ledger.get("wall_seconds")
    original_compile_wall = ledger.get("compile_wall_seconds_sum")
    ledger.update({"spec_path": str(spec.resolve()), "spec_sha256": expected,
                   "started_at": started_at,
                   "wall_seconds": (time.monotonic_ns() - started_ns) / 1e9,
                   "compile_wall_seconds_sum": 0.0,
                   "compile_reuse_claim": True,
                   "preflight_reuse": {
                       "kind": ("cross_version_byte_exact_reuse" if exact_spec
                                else "seed_independent_exact_reuse"),
                       "excluded_spec_fields": ([] if exact_spec
                                                else ["campaign_id", "initial_seed"]),
                       "source_spec": str(source_spec.relative_to(ROOT)),
                       "source_spec_sha256": source_row["spec_sha256"],
                       "source_preflight": str(source_ledger.relative_to(ROOT)),
                       "source_preflight_sha256": sha256(source_ledger),
                       "source_wall_seconds": original_wall,
                       "source_compile_wall_seconds_sum": original_compile_wall,
                   },
                   "note": ("preflight spec is byte-identical across queue versions; no compile was rerun"
                            if exact_spec else
                            "preflight source/plan/commands are byte-equivalent after excluding campaign_id and initial_seed; no compile was rerun")})
    ledger_path = root / "preflight.json"
    atomic_json(ledger_path, ledger)
    cleanup = cleanup_preflight_artifacts(root) if str(ledger.get("status", "")).startswith(
        "passed") else None
    return {"status": "passed" if str(ledger.get("status", "")).startswith("passed") else "failed",
            "failure_type": None if str(ledger.get("status", "")).startswith("passed")
            else "reused_preflight_status_failed",
            "source": ("reused_cross_version_byte_exact" if exact_spec
                       else "reused_seed_independent"), "started_at": started_at,
            "finished_at": now(), "wall_seconds": ledger["wall_seconds"],
            "reported_preflight_wall_seconds": ledger["wall_seconds"],
            "reported_compile_wall_seconds_sum": 0.0,
            "reported_compile_status_counts": ledger.get("compile_status_counts"),
            "spec": str(spec.relative_to(ROOT)), "spec_sha256": expected,
            "preflight": str(ledger_path.relative_to(ROOT)),
            "preflight_sha256": sha256(ledger_path), "exit_code": 0,
            "artifact_cleanup": cleanup,
            "disk_free_before_bytes": shutil.disk_usage(output).free,
            "disk_free_after_bytes": shutil.disk_usage(output).free}


def run_preflight(unit: dict[str, Any], method: str, output: Path) -> dict[str, Any]:
    spec, expected = spec_for(unit, method)
    root = output / "preflight" / unit["unit_id"] / method
    ledger = root / "preflight.json"
    command_log = root.parent / f"{method}-preflight-command.log"
    started_at = now()
    started_ns = time.monotonic_ns()
    disk_before = shutil.disk_usage(output).free
    if ledger.is_file():
        recorded = json.loads(ledger.read_text())
        exit_code = 0 if recorded.get("spec_sha256") == expected else 2
        source = "existing"
    elif root.exists():
        return {"status": "failed", "failure_type": "incomplete_existing_preflight",
                "started_at": started_at, "finished_at": now(),
                "wall_seconds": (time.monotonic_ns() - started_ns) / 1e9,
                "spec": str(spec.relative_to(ROOT)), "spec_sha256": expected,
                "preflight": str(ledger.relative_to(ROOT)), "preflight_sha256": None,
                "exit_code": None, "disk_free_before_bytes": disk_before,
                "disk_free_after_bytes": shutil.disk_usage(output).free}
    else:
        exit_code = run_command(
            [sys.executable, str(RUNNER), "preflight", "--spec", str(spec),
             "--output", str(root)], command_log)
        recorded = json.loads(ledger.read_text()) if ledger.is_file() else {}
        source = "executed"
    passed = (exit_code == 0 and recorded.get("spec_sha256") == expected
              and str(recorded.get("status", "")).startswith("passed"))
    cleanup = cleanup_preflight_artifacts(root) if passed else None
    return {"status": "passed" if passed else "failed",
            "failure_type": None if passed else (
                "preflight_status_failed" if ledger.is_file() else "preflight_runner_nonzero"),
            "source": source, "started_at": started_at, "finished_at": now(),
            "wall_seconds": (time.monotonic_ns() - started_ns) / 1e9,
            "reported_preflight_wall_seconds": recorded.get("wall_seconds"),
            "reported_compile_wall_seconds_sum": recorded.get("compile_wall_seconds_sum"),
            "reported_compile_status_counts": recorded.get("compile_status_counts"),
            "spec": str(spec.relative_to(ROOT)), "spec_sha256": expected,
            "preflight": str(ledger.relative_to(ROOT)),
            "preflight_sha256": sha256(ledger) if ledger.is_file() else None,
            "exit_code": exit_code, "artifact_cleanup": cleanup,
            "disk_free_before_bytes": disk_before,
            "disk_free_after_bytes": shutil.disk_usage(output).free}


def load_or_create_preflight_summary(queue: dict[str, Any], output: Path) -> tuple[Path, dict[str, Any]]:
    path = output / "preflight-all.json"
    queue_hash = sha256(Path(queue["_path"]))
    if path.is_file():
        summary = json.loads(path.read_text())
        if summary.get("queue_sha256") != queue_hash:
            raise ValueError("queue changed since preflight-all began")
        return path, summary
    summary = {"schema_version": 1, "kind": "n6_b_preflight_all",
               "status": "running", "queue": str(Path(queue["_path"]).relative_to(ROOT)),
               "queue_sha256": queue_hash, "required_spec_count": 60,
               "started_at": now(), "disk_free_before_bytes": shutil.disk_usage(output).free,
               "results": {}}
    atomic_json(path, summary)
    return path, summary


def load_exact_reuse_rows(queue: dict[str, Any]) -> tuple[str | None, dict[str, dict[str, Any]]]:
    policy = queue.get("preflight_execution", {})
    reuse = policy.get("exact_reuse")
    if reuse is None:
        return None, {}
    method = reuse.get("method")
    if method not in {"W", "S"}:
        raise ValueError("exact preflight reuse method must be W or S")
    source_queue = ROOT / reuse["source_queue"]
    source_summary = ROOT / reuse["source_summary"]
    if sha256(source_queue) != reuse["source_queue_sha256"]:
        raise ValueError("exact preflight reuse source queue hash changed")
    if sha256(source_summary) != reuse["source_summary_sha256"]:
        raise ValueError("exact preflight reuse source summary hash changed")
    recorded = json.loads(source_summary.read_text())
    if recorded.get("status") != "completed" or recorded.get("queue_sha256") != sha256(source_queue):
        raise ValueError("exact preflight reuse source is not a completed matching summary")
    rows = recorded.get("results", {})
    expected = {preflight_key(unit, method) for unit in queue["units"]}
    if not expected.issubset(rows):
        raise ValueError("exact preflight reuse source lacks required rows")
    return method, {key: rows[key] for key in expected}


def preflight_all(queue_path: Path, output: Path) -> int:
    queue = load_queue(queue_path)
    output.mkdir(parents=True, exist_ok=True)
    summary_path, summary = load_or_create_preflight_summary(queue, output)
    started_ns = time.monotonic_ns()
    reusable: dict[tuple[str, str], dict[str, Any]] = {}
    exact_method, exact_rows = load_exact_reuse_rows(queue)
    seed_reuse_methods = set(queue.get("preflight_execution", {}).get(
        "seed_reuse_methods", ["W", "S"]))
    for unit in queue["units"]:
        for method in ("W", "S"):
            key = preflight_key(unit, method)
            if key in summary["results"]:
                if method in seed_reuse_methods:
                    reusable.setdefault((unit["identifier"], method), summary["results"][key])
                continue
            if shutil.disk_usage(output).free < queue["minimum_free_disk_gib"] * 1024**3:
                summary.update({"status": "disk_guard", "stopped_at": now(),
                                "disk_free_after_bytes": shutil.disk_usage(output).free})
                atomic_json(summary_path, summary)
                return 2
            reuse_key = (unit["identifier"], method)
            if method == exact_method:
                row = materialize_reused_preflight(
                    unit, method, output, exact_rows[key], exact_spec=True)
            elif method in seed_reuse_methods and reuse_key in reusable:
                row = materialize_reused_preflight(unit, method, output, reusable[reuse_key])
            else:
                row = run_preflight(unit, method, output)
                if method in seed_reuse_methods:
                    reusable[reuse_key] = row
            summary["results"][key] = row
            atomic_json(summary_path, summary)
    results = list(summary["results"].values())
    summary.update({"status": "completed", "finished_at": now(),
                    "invocation_wall_seconds": (time.monotonic_ns() - started_ns) / 1e9,
                    "recorded_spec_count": len(results),
                    "passed_count": sum(row["status"] == "passed" for row in results),
                    "failed_count": sum(row["status"] == "failed" for row in results),
                    "preflight_wall_seconds_sum": sum(
                        row.get("reported_preflight_wall_seconds") or 0 for row in results),
                    "disk_free_after_bytes": shutil.disk_usage(output).free})
    atomic_json(summary_path, summary)
    return 0


def load_completed_preflights(queue: dict[str, Any], output: Path) -> dict[str, Any]:
    path = output / "preflight-all.json"
    if not path.is_file():
        raise ValueError("execute refused: preflight-all.json is absent")
    summary = json.loads(path.read_text())
    if summary.get("queue_sha256") != sha256(Path(queue["_path"])):
        raise ValueError("execute refused: preflight belongs to another queue")
    expected = {preflight_key(unit, method) for unit in queue["units"] for method in ("W", "S")}
    if summary.get("status") != "completed" or set(summary.get("results", {})) != expected:
        raise ValueError("execute refused: all 60 preflights have not been recorded")
    return summary["results"]


def load_or_create_state(queue: dict[str, Any], state_path: Path) -> dict[str, Any]:
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state["queue_sha256"] != sha256(Path(queue["_path"])):
            raise ValueError("queue changed since state was created")
        return state
    state = {"schema_version": 2, "status": "ready", "created_at": now(),
             "queue_sha256": sha256(Path(queue["_path"])), "actual_start_order": [],
             "units": {row["unit_id"]: {"status": "pending", "W": "pending", "S": "pending"}
                       for row in queue["units"]}}
    atomic_json(state_path, state)
    return state


def record_state(state_path: Path, state: dict[str, Any]) -> None:
    with _state_lock:
        state["updated_at"] = now()
        atomic_json(state_path, state)


def run_method(unit: dict[str, Any], method: str, output: Path,
               preflight_rows: dict[str, Any], unit_root: Path) -> dict[str, Any]:
    spec, _ = spec_for(unit, method)
    preflight_row = preflight_rows[preflight_key(unit, method)]
    if preflight_row["status"] != "passed":
        return {"status": "preflight_failed", "preflight": preflight_row["preflight"],
                "preflight_failure_type": preflight_row.get("failure_type")}
    preflight_ledger = ROOT / preflight_row["preflight"]
    root = unit_root / method
    campaign = root / "campaign"
    if campaign.exists():
        ledger = campaign / "ledger.json"
        if not ledger.is_file():
            raise ValueError(f"incomplete existing campaign needs manual preservation: {campaign}")
        return {"status": "existing", "ledger": str(ledger.relative_to(ROOT)),
                "ledger_sha256": sha256(ledger)}
    started = now()
    run_code = run_command(
        [sys.executable, str(RUNNER), "run", "--spec", str(spec),
         "--preflight", str(preflight_ledger), "--output", str(campaign)],
        root / "campaign-command.log")
    ledger = campaign / "ledger.json"
    return {"status": "completed" if run_code == 0 else "runner_nonzero",
            "started_at": started, "finished_at": now(), "exit_code": run_code,
            "ledger": str(ledger.relative_to(ROOT)) if ledger.is_file() else None,
            "ledger_sha256": sha256(ledger) if ledger.is_file() else None}


def run_unit(unit: dict[str, Any], output: Path, state_path: Path, state: dict[str, Any],
             preflight_rows: dict[str, Any]) -> dict[str, Any]:
    with _state_lock:
        row = state["units"][unit["unit_id"]]
        started_at = now()
        state["actual_start_order"].append({"sequence": len(state["actual_start_order"]),
                                             "unit_id": unit["unit_id"],
                                             "resource_class": unit["resource_class"],
                                             "started_at": started_at})
        row.update({"status": "running", "started_at": started_at,
                    "actual_start_sequence": len(state["actual_start_order"]) - 1})
        record_state(state_path, state)
    unit_root = output / "units" / unit["unit_id"]
    unit_root.mkdir(parents=True, exist_ok=True)
    for method in ("W", "S"):
        result = run_method(unit, method, output, preflight_rows, unit_root)
        with _state_lock:
            row[method] = result
            record_state(state_path, state)
    files, size = directory_size(unit_root)
    with _state_lock:
        row.update({"status": "completed", "finished_at": now(),
                    "run_directory_files": files, "run_directory_bytes": size})
        atomic_json(unit_root / "unit-result.json", row)
        record_state(state_path, state)
    return row


def pop_next_runnable(pending: list[dict[str, Any]], million_plus_running: bool) -> dict[str, Any] | None:
    for index, unit in enumerate(pending):
        if not million_plus_running or unit["resource_class"] != "million_plus":
            return pending.pop(index)
    return None


def sample_load(path: Path, stop: threading.Event, interval: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        while not stop.is_set():
            sample = {"sampled_at": now(), "load_average_1_5_15_minutes": os.getloadavg(),
                      "free_disk_bytes": shutil.disk_usage(path.parent).free}
            stream.write(json.dumps(sample).encode() + b"\n")
            stream.flush()
            stop.wait(interval)


def execute(queue_path: Path, output: Path) -> int:
    queue = load_queue(queue_path)
    preflight_rows = load_completed_preflights(queue, output)
    state_path = output / "state.json"
    state = load_or_create_state(queue, state_path)
    pending = [unit for unit in queue["units"]
               if state["units"][unit["unit_id"]]["status"] != "completed"]
    load_stop = threading.Event()
    sampler = threading.Thread(target=sample_load,
                               args=(output / "host-load.jsonl", load_stop,
                                     queue["load_sample_seconds"]), daemon=True)
    sampler.start()
    running: dict[Any, dict[str, Any]] = {}
    million_plus_running = False
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            while pending or running:
                while pending and len(running) < 3 and not _stop_after_units.is_set():
                    if shutil.disk_usage(output).free < queue["minimum_free_disk_gib"] * 1024**3:
                        state["status"] = "disk_guard"
                        record_state(state_path, state)
                        _stop_after_units.set()
                        break
                    unit = pop_next_runnable(pending, million_plus_running)
                    if unit is None:
                        break
                    if unit["resource_class"] == "million_plus":
                        million_plus_running = True
                    future = pool.submit(run_unit, unit, output, state_path, state, preflight_rows)
                    running[future] = unit
                if not running:
                    break
                done, _ = wait(set(running), return_when=FIRST_COMPLETED)
                for future in done:
                    unit = running.pop(future)
                    future.result()
                    if unit["resource_class"] == "million_plus":
                        million_plus_running = False
            state["status"] = "completed" if not pending and not running else "stopped_between_units"
            record_state(state_path, state)
    finally:
        load_stop.set()
        sampler.join(15)
    return 0 if state["status"] == "completed" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--action", choices=("preflight-all", "execute"))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    queue = load_queue(args.queue.resolve())
    if args.validate_only:
        print(json.dumps({"status": "valid", "units": len(queue["units"]),
                          "specs": queue["preflight_spec_count"],
                          "queue_sha256": sha256(args.queue)}))
        return 0
    if args.action is None:
        parser.error("--action is required unless --validate-only is used")
    args.output.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGINT, lambda *_: _stop_after_units.set())
    signal.signal(signal.SIGTERM, lambda *_: _stop_after_units.set())
    if args.action == "preflight-all":
        return preflight_all(args.queue.resolve(), args.output.resolve())
    return execute(args.queue.resolve(), args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
