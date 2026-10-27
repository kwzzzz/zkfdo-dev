#!/usr/bin/env python3
"""Run the prepared B S-only nested-array queue with one bounded retry.

Validation and gate-only actions never start fuzzing. The execute action is for
the later, separately authorized rerun step.
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import signal
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_QUEUE = ROOT / (
    "runs/n6-b2-2026-10-09.noindex/"
    "pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json"
)
GIB = 1024**3


def load_base():
    path = ROOT / "scripts/run_n6_v4_4_queue.py"
    spec = importlib.util.spec_from_file_location("n6_v4_4_for_b5_s_nested", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


base = load_base()
collect_start_gate = base.collect_start_gate


def read_checked(path: Path, expected_sha: str) -> dict[str, Any]:
    if base.sha256(path) != expected_sha:
        raise ValueError(f"SHA-256 mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def binary_only_spec_change(old: dict[str, Any], new: dict[str, Any],
                            old_binary: str, old_sha: str,
                            new_binary: str, new_sha: str) -> bool:
    expected = deepcopy(old)
    pins = [row for row in expected["pinned_files"] if row["path"] == old_binary]
    if len(pins) != 1 or pins[0]["sha256"] != old_sha:
        return False
    pins[0]["path"] = new_binary
    pins[0]["sha256"] = new_sha
    if not expected["targets"]:
        return False
    for target in expected["targets"]:
        if not target.get("command") or target["command"][0] != old_binary:
            return False
        target["command"][0] = new_binary
    return expected == new


def old_ledger_equivalent(old: dict[str, Any], old_path: Path,
                          new: dict[str, Any], new_path: Path,
                          new_spec: Path, new_spec_sha: str,
                          source_spec: Path, source_spec_sha: str) -> bool:
    restored = deepcopy(new)
    binding = restored.pop("nested_binary_rebind", None)
    if not isinstance(binding, dict) or binding != {
        "source_preflight": base.path_text(old_path),
        "source_preflight_sha256": base.sha256(old_path),
        "source_spec": base.path_text(source_spec),
        "source_spec_sha256": source_spec_sha,
        "allowed_spec_changes": ["pinned zkFuzz path and SHA-256", "target command executable"],
        "reason": "circom preflight compile and source snapshots do not use the zkFuzz executable",
    }:
        return False
    if restored.get("spec_path") != str(new_spec) or restored.get("spec_sha256") != new_spec_sha:
        return False
    restored["spec_path"] = old["spec_path"]
    restored["spec_sha256"] = old["spec_sha256"]
    if len(restored["source_snapshots"]) != len(old["source_snapshots"]):
        return False
    for prior, current in zip(old["source_snapshots"], restored["source_snapshots"]):
        if (new_path.parent / current["copied_path"]).resolve() != (
                old_path.parent / prior["copied_path"]).resolve():
            return False
        current["copied_path"] = prior["copied_path"]
    if len(restored["compile"]) != len(old["compile"]):
        return False
    for prior, current in zip(old["compile"], restored["compile"]):
        for key in ("stdout_path", "stderr_path"):
            if prior.get(key):
                if (new_path.parent / current[key]).resolve() != (
                        old_path.parent / prior[key]).resolve():
                    return False
                current[key] = prior[key]
    return restored == old


def validate_queue(queue_path: Path) -> dict[str, Any]:
    queue = base.load_queue(queue_path)
    source_sha = base.sha256(SOURCE_QUEUE)
    source = json.loads(SOURCE_QUEUE.read_text(encoding="utf-8"))
    if (queue.get("branch") != "B" or queue.get("methods") != ["S"]
            or queue.get("unit_count") != 30 or queue.get("spec_count") != 30
            or queue.get("source_queues") != [{"path": base.path_text(SOURCE_QUEUE),
                                                "sha256": source_sha}]
            or queue.get("zkfuzz_binary", {}).get("sha256") is None
            or queue.get("rerun_policy") != {
                "methods": ["S"],
                "retry_once_on": ["environment_pressure", "runner_interruption"],
                "representative": "last unpressured completed run, else last flagged run",
            }):
        raise ValueError("S-only queue identity or retry rule mismatch")
    new_binary = queue["zkfuzz_binary"]["path"]
    new_sha = queue["zkfuzz_binary"]["sha256"]
    if base.sha256(Path(new_binary)) != new_sha:
        raise ValueError("repaired zkFuzz binary changed")
    if queue.get("queue_runner") != {"path": base.path_text(Path(__file__)),
                                      "sha256": base.sha256(Path(__file__))}:
        raise ValueError("S-only queue runner changed")
    allowed_queue_changes = {"_path", "task", "created_at", "methods", "spec_count", "units",
                             "source_queues", "queue_runner", "preflight_reuse",
                             "zkfuzz_binary", "rerun_policy"}
    for key in set(source) | set(queue):
        if key not in allowed_queue_changes and source.get(key) != queue.get(key):
            raise ValueError(f"source queue setting changed: {key}")
    if len(queue["units"]) != len(source["units"]):
        raise ValueError("B S unit count changed")
    source_by_id = {u["unit_id"]: u for u in source["units"]}
    if [u["unit_id"] for u in queue["units"]] != [u["unit_id"] for u in source["units"]]:
        raise ValueError("B S unit or seed order changed")
    old_proof = read_checked(ROOT / source["preflight_reuse"]["path"],
                             source["preflight_reuse"]["sha256"])
    new_proof = read_checked(ROOT / queue["preflight_reuse"]["path"],
                             queue["preflight_reuse"]["sha256"])
    if (new_proof.get("kind") != "n6_b5_s_nested_preflight_binary_only_reuse"
            or new_proof.get("status") != "passed"
            or new_proof.get("source_queue_sha256") != source_sha
            or new_proof.get("source_proof_sha256") != source["preflight_reuse"]["sha256"]
            or new_proof.get("required_spec_count") != 30
            or new_proof.get("recorded_spec_count") != 30
            or set(new_proof.get("rows", {})) != {u["unit_id"] + ":S" for u in queue["units"]}):
        raise ValueError("S-only preflight proof mismatch")
    for unit in queue["units"]:
        unit_id = unit["unit_id"]
        prior = source_by_id[unit_id]
        trimmed = {key: value for key, value in prior.items()
                   if key not in {"whole_spec", "whole_spec_sha256",
                                  "source_whole_spec", "source_whole_spec_sha256",
                                  "split_spec", "split_spec_sha256"}}
        current = {key: value for key, value in unit.items()
                   if key not in {"split_spec", "split_spec_sha256"}}
        if trimmed != current:
            raise ValueError(f"B S target, seed, or setting changed: {unit_id}")
        source_spec_path = ROOT / prior["split_spec"]
        source_spec = read_checked(source_spec_path, prior["split_spec_sha256"])
        new_spec_path = ROOT / unit["split_spec"]
        new_spec = read_checked(new_spec_path, unit["split_spec_sha256"])
        old_row = old_proof["rows"][unit_id + ":S"]
        new_row = new_proof["rows"][unit_id + ":S"]
        old_binary = new_row["old_zkfuzz_binary"]
        old_sha = new_row["old_zkfuzz_binary_sha256"]
        if (new_row["source_spec"] != base.path_text(source_spec_path)
                or new_row["source_spec_sha256"] != prior["split_spec_sha256"]
                or new_row["destination_spec"] != base.path_text(new_spec_path)
                or new_row["destination_spec_sha256"] != unit["split_spec_sha256"]
                or new_row["new_zkfuzz_binary"] != new_binary
                or new_row["new_zkfuzz_binary_sha256"] != new_sha
                or base.sha256(Path(old_binary)) != old_sha
                or not binary_only_spec_change(source_spec, new_spec,
                                               old_binary, old_sha,
                                               new_binary, new_sha)):
            raise ValueError(f"B S spec changed beyond binary replacement: {unit_id}")
        old_ledger_path = ROOT / old_row["destination_preflight"]
        old_ledger = read_checked(old_ledger_path, old_row["destination_preflight_sha256"])
        new_ledger_path = ROOT / new_row["destination_preflight"]
        new_ledger = read_checked(new_ledger_path, new_row["destination_preflight_sha256"])
        if (new_row["source_preflight"] != base.path_text(old_ledger_path)
                or new_row["source_preflight_sha256"] != old_row["destination_preflight_sha256"]
                or new_ledger.get("status") != old_ledger.get("status")
                or new_ledger.get("spec_sha256") != unit["split_spec_sha256"]
                or not old_ledger_equivalent(old_ledger, old_ledger_path,
                                             new_ledger, new_ledger_path,
                                             new_spec_path, unit["split_spec_sha256"],
                                             source_spec_path, prior["split_spec_sha256"])):
            raise ValueError(f"B S preflight binding mismatch: {unit_id}")
    return queue


def run_s_unit(unit: dict[str, Any], preflights: dict[str, Any], output: Path,
               health: Any, run_number: int, run_kind: str,
               gate_wait_seconds: float, actual_concurrency: int) -> dict[str, Any]:
    run_root = output / "units" / unit["unit_id"] / "runs" / f"{run_number:02d}-{run_kind}"
    run_root.mkdir(parents=True, exist_ok=False)
    start_ns = time.monotonic_ns()
    row: dict[str, Any] = {"run_number": run_number, "run_kind": run_kind,
                           "started_at": base.now(), "gate_wait_seconds": gate_wait_seconds,
                           "actual_concurrency_at_start": actual_concurrency,
                           "methods": {}}
    try:
        row["methods"]["S"] = base.run_method(unit, "S", preflights, run_root)
    except Exception as error:  # preserve a failed run for the one allowed retry
        row["methods"]["S"] = {"status": "runner_interrupted", "exit_code": None,
                               "error_class": type(error).__name__,
                               "ledger": None, "ledger_sha256": None}
    row.update({"finished_at": base.now(),
                "environment": health.assess_unit(start_ns, time.monotonic_ns())})
    base.atomic_json(run_root / "unit-run.json", row)
    return row


def needs_retry(row: dict[str, Any]) -> bool:
    return (row["environment"]["environment_pressure"]
            or row["methods"]["S"]["status"] != "completed")


def execute(queue_path: Path, output: Path) -> int:
    queue = validate_queue(queue_path)
    if output.exists() or not output.name.endswith(".noindex"):
        raise ValueError("rerun output must be a new .noindex directory")
    output.mkdir(parents=True, exist_ok=False)
    proof = json.loads((ROOT / queue["preflight_reuse"]["path"]).read_text())
    preflights = proof["rows"]
    gate, initial_samples = base.collect_start_gate(output)
    state_path = output / "state.json"
    state = {"schema_version": 4, "status": "start_gate_failed",
             "created_at": base.now(), "queue_sha256": base.sha256(queue_path),
             "actual_start_order": [],
             "units": {unit["unit_id"]: {"status": "pending", "runs": []}
                       for unit in queue["units"]}}
    base.record_state(state_path, state)
    if gate["status"] != "passed":
        base.write_queue_summary(output, state, gate)
        return 2
    state["status"] = "running"
    base.record_state(state_path, state)
    health = base.HealthRecorder(output / "host-health.jsonl", initial_samples)
    health.start()
    retries: list[dict[str, Any]] = []
    pending = list(queue["units"])
    running: dict[Any, dict[str, Any]] = {}
    million_plus_running = False
    try:
        with ThreadPoolExecutor(max_workers=queue["concurrency"]) as pool:
            while pending or running:
                while (pending and len(running) < queue["concurrency"]
                       and not base._stop_after_units.is_set()):
                    if shutil.disk_usage(output).free < queue["minimum_free_disk_gib"] * GIB:
                        state["status"] = "disk_guard"
                        state["disk_free_bytes"] = shutil.disk_usage(output).free
                        base.record_state(state_path, state)
                        base._stop_after_units.set()
                        break
                    unit = base.select_unit(pending, running, million_plus_running)
                    if unit is None:
                        break
                    waited = base.wait_for_start_permission(
                        health, output / "unit-gate-waits.jsonl", unit["unit_id"],
                        state_path=state_path, state=state)
                    if base._stop_after_units.is_set():
                        pending.insert(0, unit)
                        break
                    concurrency = sum(not future.done() for future in running) + 1
                    if unit.get("resource_class") == "million_plus":
                        million_plus_running = True
                    state["actual_start_order"].append({
                        "sequence": len(state["actual_start_order"]),
                        "unit_id": unit["unit_id"], "run_kind": "primary",
                        "started_at": base.now(), "gate_wait_seconds": waited,
                        "actual_concurrency": concurrency,
                    })
                    state["units"][unit["unit_id"]]["status"] = "running_primary"
                    base.record_state(state_path, state)
                    future = pool.submit(run_s_unit, unit, preflights, output, health,
                                         1, "primary", waited, concurrency)
                    running[future] = unit
                if not running:
                    break
                done, _ = wait(set(running), return_when=FIRST_COMPLETED)
                for future in done:
                    unit = running.pop(future)
                    row = future.result()
                    state_row = state["units"][unit["unit_id"]]
                    state_row["runs"].append(row)
                    if needs_retry(row):
                        state_row["status"] = "retry_pending"
                        state_row["retry_reason"] = (
                            "environment_pressure" if row["environment"]["environment_pressure"]
                            else "runner_interruption")
                        retries.append(unit)
                    else:
                        state_row["status"] = "completed_unpressured"
                        state_row["selected_run_number"] = 1
                    if unit.get("resource_class") == "million_plus":
                        million_plus_running = False
                    base.record_state(state_path, state)

        for unit in retries:
            if base._stop_after_units.is_set():
                break
            if shutil.disk_usage(output).free < queue["minimum_free_disk_gib"] * GIB:
                state["status"] = "disk_guard"
                state["disk_free_bytes"] = shutil.disk_usage(output).free
                base.record_state(state_path, state)
                break
            waited = base.wait_for_start_permission(
                health, output / "unit-gate-waits.jsonl", unit["unit_id"],
                state_path=state_path, state=state)
            if base._stop_after_units.is_set():
                break
            state["actual_start_order"].append({
                "sequence": len(state["actual_start_order"]),
                "unit_id": unit["unit_id"], "run_kind": "bounded_retry",
                "started_at": base.now(), "gate_wait_seconds": waited,
                "actual_concurrency": 1,
            })
            result = run_s_unit(unit, preflights, output, health, 2,
                                "bounded_retry", waited, 1)
            state_row = state["units"][unit["unit_id"]]
            state_row["runs"].append(result)
            state_row["representative_run_number"] = 2
            state_row["representative_environment_pressure"] = result["environment"][
                "environment_pressure"]
            state_row["representative_runner_interruption"] = (
                result["methods"]["S"]["status"] != "completed")
            if result["environment"]["environment_pressure"]:
                state_row["status"] = "retry_environment_pressure"
                state_row["selected_run_number"] = None
            elif result["methods"]["S"]["status"] != "completed":
                state_row["status"] = "retry_runner_interruption"
                state_row["selected_run_number"] = None
            else:
                state_row["status"] = "completed_unpressured_retry"
                state_row["selected_run_number"] = 2
            base.record_state(state_path, state)
        complete = all(row["status"] in {
            "completed_unpressured", "completed_unpressured_retry",
            "retry_environment_pressure", "retry_runner_interruption",
        } for row in state["units"].values())
        state["status"] = base.final_queue_status(state.get("status", ""), complete)
        base.record_state(state_path, state)
    finally:
        health.close()
    base.write_queue_summary(output, state, gate)
    return 0 if state["status"] == "completed" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--action", choices=("validate-only", "gate-only", "execute"),
                        required=True)
    args = parser.parse_args()
    queue_path = args.queue.resolve()
    queue = validate_queue(queue_path)
    if args.action == "validate-only":
        print(json.dumps({"status": "valid", "units": len(queue["units"]),
                          "specs": 30, "methods": ["S"],
                          "queue_sha256": base.sha256(queue_path)}))
        return 0
    if args.output is None:
        parser.error("--output is required for gate-only and execute")
    output = args.output.resolve()
    if args.action == "gate-only":
        if output.exists() or not output.name.endswith(".noindex"):
            raise ValueError("gate-only output must be a new .noindex directory")
        output.mkdir(parents=True, exist_ok=False)
        gate, _samples = base.collect_start_gate(output)
        print(json.dumps({"status": gate["status"],
                          "gate": base.path_text(output / "start-gate.json")}))
        return 0 if gate["status"] == "passed" else 2
    signal.signal(signal.SIGINT, lambda *_: base._stop_after_units.set())
    signal.signal(signal.SIGTERM, lambda *_: base._stop_after_units.set())
    return execute(queue_path, output)


if __name__ == "__main__":
    raise SystemExit(main())
