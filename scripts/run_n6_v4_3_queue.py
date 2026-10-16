#!/usr/bin/env python3
"""Run frozen N6 A/B queues with Policy-A v4 and macOS environment gates (queue v4.3)."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_policy_a_engine_v4.py"
GIB = 1024**3
MIB = 1024**2
_stop_after_units = threading.Event()
_state_lock = threading.RLock()


def _load_engine():
    spec = importlib.util.spec_from_file_location("policy_a_v4_for_queue", RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


engine = _load_engine()


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


def path_text(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()


def run_text(argv: list[str]) -> str:
    return subprocess.run(
        argv,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout


def parse_size(value: str, unit: str) -> int:
    scales = {"K": 1024, "M": MIB, "G": GIB}
    return round(float(value) * scales[unit.upper()])


def swap_used_bytes() -> int:
    output = run_text(["sysctl", "-n", "vm.swapusage"])
    match = re.search(r"used\s*=\s*([\d.]+)([KMG])", output, re.IGNORECASE)
    if match is None:
        raise ValueError("vm.swapusage output lacks used value")
    return parse_size(match.group(1), match.group(2))


def memorystatus_level() -> int:
    return int(run_text(["sysctl", "-n", "kern.memorystatus_level"]).strip())


def ac_power_connected() -> tuple[bool, str]:
    output = run_text(["pmset", "-g", "batt"])
    return "AC Power" in output, output.strip()


def low_power_mode() -> tuple[int | None, str]:
    output = run_text(["pmset", "-g", "custom"])
    section = output.split("AC Power:", 1)[1] if "AC Power:" in output else output
    match = re.search(r"^\s*lowpowermode\s+(\d+)\s*$", section, re.MULTILINE)
    return (int(match.group(1)) if match else None), output.strip()


def thermal_status() -> dict[str, Any]:
    output = run_text(["pmset", "-g", "therm"])
    warning_lines = [
        line.strip()
        for line in output.splitlines()
        if "warning" in line.lower() and not re.search(r"\bno\b.*\bwarning", line, re.I)
    ]
    return {"warning": bool(warning_lines), "warning_lines": warning_lines,
            "raw": output.strip()}


def top_physical_processes(limit: int = 10) -> dict[str, Any]:
    output = run_text(["ps", "-axo", "pid=,comm="])
    rows = []
    unreadable = []
    for line in output.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        try:
            pid = int(fields[0])
            physical, resident = engine.proc_pid_memory_bytes(pid)
        except (ValueError, OSError) as error:
            unreadable.append({"pid": fields[0], "error": str(error)})
            continue
        rows.append({"pid": pid, "command": fields[1],
                     "physical_memory_bytes": physical,
                     "rusage_resident_bytes": resident})
    rows.sort(key=lambda row: row["physical_memory_bytes"], reverse=True)
    return {"processes": rows[:limit], "unreadable_process_count": len(unreadable),
            "unreadable": unreadable}


def health_sample(*, include_thermal: bool) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "sampled_at": now(),
        "monotonic_ns": time.monotonic_ns(),
        "load_average_1_5_15_minutes": list(os.getloadavg()),
        "errors": [],
    }
    for key, reader in (("memorystatus_level", memorystatus_level),
                        ("swap_used_bytes", swap_used_bytes)):
        try:
            sample[key] = reader()
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            sample[key] = None
            sample["errors"].append(f"{key}: {error}")
    if include_thermal:
        try:
            sample["thermal"] = thermal_status()
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            sample["thermal"] = None
            sample["errors"].append(f"thermal: {error}")
        try:
            sample["ac_power"], sample["ac_power_raw"] = ac_power_connected()
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            sample["ac_power"] = None
            sample["ac_power_raw"] = None
            sample["errors"].append(f"ac_power: {error}")
    return sample


def stable_swap_window(samples: list[dict[str, Any]], seconds: int = 60) -> tuple[bool, str]:
    usable = [row for row in samples if row.get("swap_used_bytes") is not None]
    if len(usable) < 2:
        return False, "swap_samples_missing"
    if (usable[-1]["monotonic_ns"] - usable[0]["monotonic_ns"]) < seconds * 1_000_000_000:
        return False, "swap_window_short"
    if usable[-1]["swap_used_bytes"] > usable[0]["swap_used_bytes"]:
        return False, "swap_increased"
    return True, "stable"


def collect_start_gate(
    output: Path,
    *,
    duration_seconds: int = 60,
    sample_seconds: float = 1.0,
    sample_reader: Callable[..., dict[str, Any]] = health_sample,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started_at = now()
    errors = []
    try:
        ac, ac_raw = ac_power_connected()
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        ac, ac_raw = False, None
        errors.append(f"ac_power: {error}")
    try:
        low_power, low_power_raw = low_power_mode()
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        low_power, low_power_raw = None, None
        errors.append(f"lowpowermode: {error}")
    try:
        thermal = thermal_status()
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        thermal = None
        errors.append(f"thermal: {error}")
    samples = []
    while True:
        samples.append(sample_reader(include_thermal=False))
        # v4.1: measure the window from the first sample, the same basis
        # stable_swap_window uses; v4 counted setup time and ended at ~59.98 s.
        elapsed = (samples[-1]["monotonic_ns"] - samples[0]["monotonic_ns"]) / 1e9
        if elapsed >= duration_seconds:
            break
        time.sleep(min(sample_seconds, max(duration_seconds - elapsed, 0)))
    swap_stable, swap_reason = stable_swap_window(samples, duration_seconds)
    final_level = samples[-1].get("memorystatus_level")
    checks = {
        "ac_power": ac,
        "lowpowermode_zero": low_power == 0,
        "thermal_warning_absent": thermal is not None and not thermal["warning"],
        "memorystatus_level_at_least_50": final_level is not None and final_level >= 50,
        "swap_not_increasing_for_60_seconds": swap_stable,
        "sampling_complete": not errors and all(not row.get("errors") for row in samples),
    }
    try:
        top = top_physical_processes(10)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        top = {"processes": [], "unreadable_process_count": None,
               "error": str(error)}
        checks["sampling_complete"] = False
    checks["top_10_physical_processes_recorded"] = len(top.get("processes", [])) == 10
    gate = {
        "schema_version": 1,
        "kind": "n6_v4_start_gate",
        "started_at": started_at,
        "finished_at": now(),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "errors": errors,
        "ac_power_raw": ac_raw,
        "lowpowermode": low_power,
        "lowpowermode_raw": low_power_raw,
        "thermal": thermal,
        "swap_window_reason": swap_reason,
        "samples": samples,
        "top_physical_processes": top,
    }
    atomic_json(output / "start-gate.json", gate)
    return gate, samples


class HealthRecorder:
    def __init__(self, path: Path, initial_samples: list[dict[str, Any]]):
        self.path = path
        self.samples = list(initial_samples)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        for sample in self.samples:
            append_jsonl(self.path, sample)
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(5)

    def _run(self) -> None:
        last_thermal_ns = 0
        while not self.stop.is_set():
            current_ns = time.monotonic_ns()
            include_thermal = current_ns - last_thermal_ns >= 60 * 1_000_000_000
            sample = health_sample(include_thermal=include_thermal)
            if include_thermal:
                last_thermal_ns = current_ns
            with self.lock:
                self.samples.append(sample)
            append_jsonl(self.path, sample)
            self.stop.wait(1.0)

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.samples)

    def unit_start_gate(self) -> tuple[bool, list[str]]:
        samples = self.snapshot()
        cutoff = time.monotonic_ns() - 61 * 1_000_000_000
        window = [row for row in samples if row["monotonic_ns"] >= cutoff]
        reasons = []
        stable, reason = stable_swap_window(window, 60)
        if not stable:
            reasons.append(reason)
        if not window or window[-1].get("memorystatus_level") is None:
            reasons.append("memorystatus_missing")
        elif window[-1]["memorystatus_level"] < 40:
            reasons.append("memorystatus_below_40")
        latest_ac = next((row for row in reversed(window) if "ac_power" in row), None)
        if latest_ac is None or latest_ac["ac_power"] is not True:
            reasons.append("ac_power_absent")
        if any(row.get("errors") for row in window):
            reasons.append("health_sample_error")
        return not reasons, sorted(set(reasons))

    def assess_unit(self, start_ns: int, end_ns: int) -> dict[str, Any]:
        samples = [row for row in self.snapshot()
                   if start_ns <= row["monotonic_ns"] <= end_ns]
        reasons = []
        swap_values = [row["swap_used_bytes"] for row in samples
                       if row.get("swap_used_bytes") is not None]
        levels = [row["memorystatus_level"] for row in samples
                  if row.get("memorystatus_level") is not None]
        if not samples or len(swap_values) != len(samples) or len(levels) != len(samples):
            reasons.append("health_monitor_incomplete")
        swap_increase = max(swap_values) - swap_values[0] if swap_values else None
        if swap_increase is not None and swap_increase > 512 * MIB:
            reasons.append("swap_increase_over_512_mib")
        minimum_level = min(levels) if levels else None
        if minimum_level is not None and minimum_level < 15:
            reasons.append("memorystatus_below_15")
        thermal_warning = any(
            row.get("thermal") is not None and row["thermal"].get("warning")
            for row in samples
        )
        if thermal_warning:
            reasons.append("thermal_warning")
        if any(row.get("ac_power") is False for row in samples):
            reasons.append("ac_power_lost")
        if any(row.get("errors") for row in samples):
            reasons.append("health_monitor_incomplete")
        reasons = sorted(set(reasons))
        return {
            "environment_pressure": bool(reasons),
            "reasons": reasons,
            "sample_count": len(samples),
            "swap_increase_bytes": swap_increase,
            "minimum_memorystatus_level": minimum_level,
            "thermal_warning": thermal_warning,
            "first_sampled_at": samples[0]["sampled_at"] if samples else None,
            "last_sampled_at": samples[-1]["sampled_at"] if samples else None,
        }


def load_queue(path: Path) -> dict[str, Any]:
    queue = json.loads(path.read_text())
    queue["_path"] = str(path.resolve())
    if queue.get("schema_version") != 4 or queue.get("status") != "ready_for_execution":
        raise ValueError("queue is not a frozen N6 v4 queue")
    if type(queue.get("concurrency")) is not int or queue["concurrency"] not in (1, 3):
        raise ValueError("N6 v4.2 concurrency must be 1 or 3")
    if queue.get("minimum_free_disk_gib") not in {35, 40}:
        raise ValueError("N6 v4 disk guard must preserve the frozen A/B threshold")
    if queue.get("health_policy", {}).get("sample_seconds") != 1:
        raise ValueError("N6 v4 health sampling must be 1 second")
    units = queue.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("N6 v4 queue has no units")
    if queue.get("unit_count") != len(units):
        raise ValueError("N6 v4 unit denominator mismatch")
    if queue.get("branch") == "A" and [row.get("phase") for row in units] != sorted(
            (row.get("phase") for row in units), key=lambda value: {"A-D": 0, "A-Q": 1}[value]):
        raise ValueError("A phase barrier order is not frozen")
    return queue


def spec_for(unit: dict[str, Any], method: str) -> Path:
    key = "whole" if method == "W" else "split"
    path = ROOT / unit[f"{key}_spec"]
    if sha256(path) != unit[f"{key}_spec_sha256"]:
        raise ValueError(f"spec changed for {unit['unit_id']} {method}")
    return path


def load_preflight_rows(queue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    declaration = queue["preflight_reuse"]
    path = ROOT / declaration["path"]
    if sha256(path) != declaration["sha256"]:
        raise ValueError("preflight reuse proof changed")
    proof = json.loads(path.read_text())
    if proof.get("status") != "passed":
        raise ValueError("preflight reuse proof did not pass")
    expected = {f"{unit['unit_id']}:{method}" for unit in queue["units"]
                for method in ("W", "S")}
    if set(proof.get("rows", {})) != expected:
        raise ValueError("preflight reuse denominator mismatch")
    for key, row in proof["rows"].items():
        source_ledger = ROOT / row["source_preflight"]
        if not source_ledger.is_file() or sha256(source_ledger) != row["source_preflight_sha256"]:
            raise ValueError(f"source preflight ledger changed: {key}")
        ledger = ROOT / row["destination_preflight"]
        if not ledger.is_file() or sha256(ledger) != row["destination_preflight_sha256"]:
            raise ValueError(f"v4 preflight ledger changed: {key}")
        if sha256(ROOT / row["destination_spec"]) != row["destination_spec_sha256"]:
            raise ValueError(f"destination spec changed: {key}")
    return proof["rows"]


def run_command(argv: list[str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("xb") as stream:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=stream,
                              stderr=subprocess.STDOUT, start_new_session=True).returncode


def run_method(unit: dict[str, Any], method: str, preflights: dict[str, Any],
               run_root: Path) -> dict[str, Any]:
    key = f"{unit['unit_id']}:{method}"
    spec = spec_for(unit, method)
    preflight = ROOT / preflights[key]["destination_preflight"]
    method_root = run_root / method
    campaign = method_root / "campaign"
    started_at = now()
    exit_code = run_command(
        [sys.executable, str(RUNNER), "run", "--spec", str(spec),
         "--preflight", str(preflight), "--output", str(campaign)],
        method_root / "campaign-command.log",
    )
    ledger = campaign / "ledger.json"
    return {"status": "completed" if exit_code == 0 else "runner_nonzero",
            "started_at": started_at, "finished_at": now(), "exit_code": exit_code,
            "ledger": str(ledger.relative_to(ROOT)) if ledger.is_file() else None,
            "ledger_sha256": sha256(ledger) if ledger.is_file() else None}


def run_unit(unit: dict[str, Any], preflights: dict[str, Any], output: Path,
             health: HealthRecorder, run_number: int, run_kind: str,
             gate_wait_seconds: float, actual_concurrency: int) -> dict[str, Any]:
    run_root = output / "units" / unit["unit_id"] / "runs" / f"{run_number:02d}-{run_kind}"
    run_root.mkdir(parents=True, exist_ok=False)
    start_ns = time.monotonic_ns()
    row = {"run_number": run_number, "run_kind": run_kind, "started_at": now(),
           "gate_wait_seconds": gate_wait_seconds,
           "actual_concurrency_at_start": actual_concurrency, "methods": {}}
    for method in ("W", "S"):
        row["methods"][method] = run_method(unit, method, preflights, run_root)
    end_ns = time.monotonic_ns()
    row.update({"finished_at": now(), "environment": health.assess_unit(start_ns, end_ns)})
    atomic_json(run_root / "unit-run.json", row)
    return row


def phase_allowed(unit: dict[str, Any], pending: list[dict[str, Any]],
                  running: dict[Any, dict[str, Any]]) -> bool:
    if unit.get("phase") != "A-Q":
        return True
    return not any(row.get("phase") == "A-D" for row in pending) and not any(
        row.get("phase") == "A-D" for row in running.values())


def select_unit(pending: list[dict[str, Any]], running: dict[Any, dict[str, Any]],
                million_plus_running: bool) -> dict[str, Any] | None:
    for index, unit in enumerate(pending):
        if not phase_allowed(unit, pending, running):
            continue
        if million_plus_running and unit.get("resource_class") == "million_plus":
            continue
        return pending.pop(index)
    return None


def record_state(path: Path, state: dict[str, Any]) -> None:
    with _state_lock:
        state["updated_at"] = now()
        atomic_json(path, state)


def write_queue_summary(output: Path, state: dict[str, Any], gate: dict[str, Any]) -> Path:
    units = list(state["units"].values())
    statuses: dict[str, int] = {}
    runs = []
    for unit in units:
        statuses[unit["status"]] = statuses.get(unit["status"], 0) + 1
        runs.extend(unit.get("runs", []))
    summary = {
        "schema_version": 1,
        "kind": "n6_v4_queue_summary",
        "written_at": now(),
        "status": state["status"],
        "start_gate_status": gate["status"],
        "unit_status_counts": dict(sorted(statuses.items())),
        "unit_count": len(units),
        "recorded_run_count": len(runs),
        "environment_pressure_run_count": sum(
            row.get("environment", {}).get("environment_pressure") is True for row in runs),
        "pressure_retry_run_count": sum(row.get("run_kind") == "pressure_retry" for row in runs),
        "gate_wait_seconds_sum": sum(row.get("gate_wait_seconds", 0) for row in runs),
        "actual_concurrency_at_start": [row.get("actual_concurrency_at_start") for row in runs],
        "state": path_text(output / "state.json"),
        "candidate_contents_opened": False,
        "j_review_performed": False,
    }
    path = output / "queue-summary.json"
    atomic_json(path, summary)
    return path


def wait_for_start_permission(health: HealthRecorder, wait_log: Path,
                              unit_id: str) -> float:
    started = time.monotonic_ns()
    while not _stop_after_units.is_set():
        passed, reasons = health.unit_start_gate()
        if passed:
            return (time.monotonic_ns() - started) / 1e9
        append_jsonl(wait_log, {"sampled_at": now(), "unit_id": unit_id,
                                "reasons": reasons})
        time.sleep(1)
    return (time.monotonic_ns() - started) / 1e9


def final_queue_status(current_status: str, complete: bool) -> str:
    if current_status == "disk_guard":
        return current_status
    return "completed" if complete else "stopped_between_units"


def execute(queue_path: Path, output: Path) -> int:
    queue = load_queue(queue_path)
    if not output.name.endswith(".noindex"):
        raise ValueError("N6 v4 output directory must end in .noindex")
    output.mkdir(parents=True, exist_ok=True)
    preflights = load_preflight_rows(queue)
    gate, initial_samples = collect_start_gate(output)
    state_path = output / "state.json"
    state = {"schema_version": 4, "status": "start_gate_failed", "created_at": now(),
             "queue_sha256": sha256(queue_path), "actual_start_order": [],
             "units": {unit["unit_id"]: {"status": "pending", "runs": []}
                       for unit in queue["units"]}}
    record_state(state_path, state)
    if gate["status"] != "passed":
        write_queue_summary(output, state, gate)
        return 2
    state["status"] = "running"
    record_state(state_path, state)
    health = HealthRecorder(output / "host-health.jsonl", initial_samples)
    health.start()
    retries: list[dict[str, Any]] = []
    pending = list(queue["units"])
    running: dict[Any, dict[str, Any]] = {}
    million_plus_running = False
    try:
        with ThreadPoolExecutor(max_workers=queue["concurrency"]) as pool:
            while pending or running:
                while (pending and len(running) < queue["concurrency"]
                       and not _stop_after_units.is_set()):
                    if shutil.disk_usage(output).free < queue["minimum_free_disk_gib"] * GIB:
                        state["status"] = "disk_guard"
                        state["disk_free_bytes"] = shutil.disk_usage(output).free
                        record_state(state_path, state)
                        _stop_after_units.set()
                        break
                    unit = select_unit(pending, running, million_plus_running)
                    if unit is None:
                        break
                    waited_seconds = wait_for_start_permission(
                        health, output / "unit-gate-waits.jsonl", unit["unit_id"])
                    if _stop_after_units.is_set():
                        pending.insert(0, unit)
                        break
                    concurrency = sum(not future.done() for future in running) + 1
                    if unit.get("resource_class") == "million_plus":
                        million_plus_running = True
                    state["actual_start_order"].append({
                        "sequence": len(state["actual_start_order"]),
                        "unit_id": unit["unit_id"], "run_kind": "primary",
                        "started_at": now(), "gate_wait_seconds": waited_seconds,
                        "actual_concurrency": concurrency,
                    })
                    state["units"][unit["unit_id"]]["status"] = "running_primary"
                    record_state(state_path, state)
                    future = pool.submit(run_unit, unit, preflights, output, health, 1,
                                         "primary", waited_seconds, concurrency)
                    running[future] = unit
                if not running:
                    break
                done, _ = wait(set(running), return_when=FIRST_COMPLETED)
                for future in done:
                    unit = running.pop(future)
                    row = future.result()
                    state_row = state["units"][unit["unit_id"]]
                    state_row["runs"].append(row)
                    if row["environment"]["environment_pressure"]:
                        state_row["status"] = "environment_pressure_retry_pending"
                        retries.append(unit)
                    else:
                        state_row["status"] = "completed_unpressured"
                        state_row["selected_run_number"] = 1
                    if unit.get("resource_class") == "million_plus":
                        million_plus_running = False
                    record_state(state_path, state)

        for unit in retries:
            if _stop_after_units.is_set():
                break
            if shutil.disk_usage(output).free < queue["minimum_free_disk_gib"] * GIB:
                state["status"] = "disk_guard"
                state["disk_free_bytes"] = shutil.disk_usage(output).free
                record_state(state_path, state)
                break
            waited_seconds = wait_for_start_permission(
                health, output / "unit-gate-waits.jsonl", unit["unit_id"])
            if _stop_after_units.is_set():
                break
            state["actual_start_order"].append({
                "sequence": len(state["actual_start_order"]),
                "unit_id": unit["unit_id"], "run_kind": "pressure_retry",
                "started_at": now(), "gate_wait_seconds": waited_seconds,
                "actual_concurrency": 1,
            })
            result = run_unit(unit, preflights, output, health, 2,
                              "pressure_retry", waited_seconds, 1)
            state_row = state["units"][unit["unit_id"]]
            state_row["runs"].append(result)
            if result["environment"]["environment_pressure"]:
                state_row["status"] = "retry_environment_pressure"
                state_row["selected_run_number"] = None
            else:
                state_row["status"] = "completed_unpressured_retry"
                state_row["selected_run_number"] = 2
            record_state(state_path, state)
        complete = all(row["status"] in {"completed_unpressured",
                                         "completed_unpressured_retry",
                                         "retry_environment_pressure"}
                       for row in state["units"].values())
        state["status"] = final_queue_status(state.get("status", ""), complete)
        record_state(state_path, state)
    finally:
        health.close()
    write_queue_summary(output, state, gate)
    return 0 if state["status"] == "completed" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--action", choices=("validate-only", "gate-only", "execute"),
                        required=True)
    args = parser.parse_args()
    queue = load_queue(args.queue.resolve())
    if args.action == "validate-only":
        load_preflight_rows(queue)
        print(json.dumps({"status": "valid", "units": len(queue["units"]),
                          "specs": len(queue["units"]) * 2,
                          "queue_sha256": sha256(args.queue)}))
        return 0
    if args.output is None:
        parser.error("--output is required for gate-only and execute")
    output = args.output.resolve()
    if not output.name.endswith(".noindex"):
        raise ValueError("N6 v4 output directory must end in .noindex")
    output.mkdir(parents=True, exist_ok=True)
    if args.action == "gate-only":
        gate, _samples = collect_start_gate(output)
        print(json.dumps({"status": gate["status"],
                          "gate": str((output / 'start-gate.json').relative_to(ROOT))}))
        return 0 if gate["status"] == "passed" else 2
    signal.signal(signal.SIGINT, lambda *_: _stop_after_units.set())
    signal.signal(signal.SIGTERM, lambda *_: _stop_after_units.set())
    return execute(args.queue.resolve(), output)


if __name__ == "__main__":
    raise SystemExit(main())
