#!/usr/bin/env python3
"""Record N6-B2 prestart gates without starting a B campaign or reading candidates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-b2-2026-10-09.noindex"
DEFAULT_QUEUE = ROOT / "runs/n6-a2b-2026-10-08.noindex/queue-b-v4.json"
DEFAULT_INCLUDES = RUN / "include-provenance-v3.json"
SOURCE_QUEUE_SHA256 = "d39e821fd65cea1852ad6a20b88ab59e03a7c363be9022224221986716161600"
SOURCE_INCLUDE_SHA256 = "792af9508592d26c6e67e5f53f38c67bd5ff9a86d33cceccc4424f7d3e63c03d"
DEFAULT_OUTPUT = RUN / "gates/prestart-gates.json"
ENGINE = ROOT / "scripts/run_policy_a_engine_v4.py"
QUEUE_RUNNER = ROOT / "scripts/run_n6_v4_3_queue.py"
GIB = 1024**3


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


def repo_path(value: str) -> Path:
    root = ROOT.resolve()
    path = (root / value).resolve()
    path.relative_to(root)
    return path


def path_record(path: Path) -> dict[str, str]:
    try:
        shown = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        shown = str(path.resolve())
    return {"path": shown, "sha256": sha256(path)}


def validate_library_root_copies(provenance: dict[str, Any]) -> None:
    files = provenance.get("library_root_external_files")
    references = provenance.get("library_root_external_references")
    if (provenance.get("schema_version") != 3 or not isinstance(files, list)
            or not isinstance(references, list)
            or provenance.get("library_root_external_unique_file_count") != len(files)
            or provenance.get("library_root_external_reference_count") != len(references)
            or provenance.get("library_root_external_missing_copy_count") != 0
            or provenance.get("library_root_external_copy_mismatch_count") != 0):
        raise ValueError("B library-root copy evidence incomplete")
    by_path = {}
    for row in files:
        original = row["path"]
        expected = row["sha256"]
        copies = row.get("snapshot_copies")
        if (original in by_path or not isinstance(copies, list) or not copies
                or sha256(repo_path(original)) != expected):
            raise ValueError(f"B library-root original or copy missing: {original}")
        by_path[original] = expected
        for copy in copies:
            if (copy.get("matches_external") is not True or copy.get("sha256") != expected
                    or sha256(repo_path(copy["path"])) != expected):
                raise ValueError(f"B library-root snapshot copy mismatch: {original}")
    for row in references:
        expected = by_path.get(row.get("path"))
        copies = row.get("snapshot_copies")
        if (expected is None or row.get("sha256") != expected
                or not isinstance(copies, list) or not copies
                or not all(copy.get("matches_external") is True
                           and copy.get("sha256") == expected for copy in copies)):
                raise ValueError("B library-root reference mismatch")


def validate_external_copies(provenance: dict[str, Any]) -> None:
    files = provenance.get("external_unique_files")
    if (provenance.get("schema_version") != 3 or not isinstance(files, list)
            or provenance.get("external_unique_file_count") != len(files)
            or provenance.get("external_unique_file_without_copy_count") != 0
            or provenance.get("external_reference_missing_copy_count") != 0):
        raise ValueError("B external snapshot copy evidence incomplete")
    for row in files:
        copies = row.get("snapshot_copies")
        if (not isinstance(copies, list) or not copies
                or not isinstance(row.get("reference_count"), int)
                or row["reference_count"] < 1
                or any(copy.get("matches_external") is not True
                       or copy.get("sha256") != row.get("sha256") for copy in copies)):
            raise ValueError("B external snapshot copy mismatch")


def validate_inputs(queue_path: Path, include_path: Path) -> dict[str, Any]:
    queue = json.loads(queue_path.read_text())
    includes = json.loads(include_path.read_text())
    source_includes = (includes if include_path.resolve() == DEFAULT_INCLUDES.resolve()
                       else json.loads(DEFAULT_INCLUDES.read_text()))
    if (source_includes.get("status") != "passed"
            or sha256(DEFAULT_INCLUDES) != SOURCE_INCLUDE_SHA256
            or source_includes.get("queue_sha256") != SOURCE_QUEUE_SHA256
            or source_includes.get("spec_count") != 60
            or source_includes.get("unresolved_include_count") != 0
            or source_includes.get("snapshot_copy_mismatch_count") != 0):
        raise ValueError("B source include provenance failed")
    validate_library_root_copies(source_includes)
    validate_external_copies(source_includes)
    if (queue.get("schema_version") != 4 or queue.get("status") != "ready_for_execution"
            or queue.get("branch") != "B" or queue.get("unit_count") != 30
            or len(queue.get("units", [])) != 30 or queue.get("concurrency") != 3
            or queue.get("minimum_free_disk_gib") != 35):
        raise ValueError("B queue denominator, concurrency, or disk guard mismatch")
    budget = queue.get("budget_policy", {})
    if (budget.get("physical_memory_cap_bytes") != 10 * GIB
            or budget.get("total_budget_seconds") != 3600
            or budget.get("split_attempt_cap_seconds") != 30
            or budget.get("seeds") != [2026100601, 2026100602, 2026100603]):
        raise ValueError("B queue budget policy mismatch")
    queue_sha = sha256(queue_path)
    if (includes.get("status") != "passed" or includes.get("spec_count") != 60
            or includes.get("unresolved_include_count") != 0
            or includes.get("snapshot_copy_mismatch_count") != 0
            or includes.get("queue_sha256") != queue_sha):
        raise ValueError("B include provenance does not match the final queue")
    validate_library_root_copies(includes)
    validate_external_copies(includes)
    spec_rows = includes.get("specs")
    if not isinstance(spec_rows, list) or len(spec_rows) != 60:
        raise ValueError("B include provenance spec rows missing")
    proven_specs = {row.get("spec"): row.get("spec_sha256") for row in spec_rows}
    if len(proven_specs) != 60:
        raise ValueError("B include provenance spec rows duplicated")
    spec_count = 0
    for unit in queue["units"]:
        for key in ("whole", "split"):
            name = unit[f"{key}_spec"]
            expected = unit[f"{key}_spec_sha256"]
            if proven_specs.get(name) != expected or sha256(repo_path(name)) != expected:
                raise ValueError(f"B spec or include provenance hash mismatch: {name}")
            spec = json.loads(repo_path(name).read_text())
            if spec.get("memory_cap_bytes") != 10 * GIB:
                raise ValueError(f"B spec memory cap mismatch: {name}")
            spec_count += 1
    return {"queue": path_record(queue_path),
            "source_include_provenance": path_record(DEFAULT_INCLUDES),
            "include_provenance": path_record(include_path),
            "unit_count": len(queue["units"]), "spec_count": spec_count,
            "minimum_free_bytes": queue["minimum_free_disk_gib"] * GIB}


def classify_process(command: str) -> bool:
    try:
        argv = shlex.split(command)
    except ValueError:
        argv = command.split()
    if not argv:
        return False
    executable = Path(argv[0]).name.lower()
    if executable in {"zkfuzz", "circom", "cargo", "rustc", "zkfdo"}:
        return True
    if executable.endswith(".py"):
        scripts = [executable]
    elif executable.startswith(("python", "pypy")):
        scripts = [Path(arg).name.lower() for arg in argv[1:] if arg.endswith(".py")]
    else:
        scripts = []
    return any(name.startswith("run_n6_") or name.startswith("run_policy_a_engine_")
               or name.startswith("n6_j") or name == "n6_b2_prestart_gate.py"
               for name in scripts)


def process_inventory() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,%cpu=,%mem=,command="],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False)
    rows = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            fields = line.strip().split(None, 4)
            if len(fields) != 5:
                continue
            pid, ppid, cpu, memory, command = fields
            if int(pid) != os.getpid() and classify_process(command):
                rows.append({"pid": int(pid), "ppid": int(ppid),
                             "cpu_percent": float(cpu), "memory_percent": float(memory),
                             "command": command})
    return {"exit_code": result.returncode, "stderr": result.stderr.strip() or None}, rows


def run_command(argv: list[str], *, timeout: int) -> dict[str, Any]:
    process = subprocess.Popen(
        argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, start_new_session=True)
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
    return {"exit_code": process.returncode, "timed_out": timed_out, "output": output}


def run_self_test(run_dir: Path) -> tuple[dict[str, Any], bool]:
    destination = run_dir / "v4-self-test"
    command = run_command([sys.executable, str(ENGINE), "self-test", "--output",
                           str(destination)], timeout=240)
    log_path = run_dir / "v4-self-test.log"
    log_path.write_text(command.pop("output"))
    command["log"] = path_record(log_path)
    summary_path = destination / "self-test-v4.json"
    if command["exit_code"] != 0 or command["timed_out"] or not summary_path.is_file():
        return command, False
    summary = json.loads(summary_path.read_text())
    required = {"v1_state_machine", "two_gib_step_program_stopped_at_one_gib_physical_cap",
                "physical_cap_child_reaped", "proc_pid_rusage_within_five_percent_of_footprint",
                "injected_low_rss_high_physical_is_capped",
                "injected_reader_failure_is_fail_closed"}
    checks = summary.get("checks")
    passed = (summary.get("schema_version") == 4
              and summary.get("kind") == "policy_a_v4_self_test"
              and isinstance(checks, dict) and required <= checks.keys()
              and all(checks.values()))
    command["summary"] = path_record(summary_path)
    command["checks"] = checks
    return command, passed


def run_fail_closed_test(run_dir: Path) -> tuple[dict[str, Any], bool]:
    command = run_command(
        [sys.executable, "-m", "unittest",
         "tests.policy_a_engine_v4_test.PolicyAEngineV4Test."
         "test_process_tree_monitor_failure_is_fail_closed", "-v"], timeout=60)
    log_path = run_dir / "fail-closed-test.log"
    log_path.write_text(command.pop("output"))
    command["log"] = path_record(log_path)
    return command, command["exit_code"] == 0 and not command["timed_out"]


def pmset_available(option: str) -> dict[str, Any]:
    result = subprocess.run(["pmset", "-g", option], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, check=False)
    return {"exit_code": result.returncode, "stderr": result.stderr.strip() or None}


def collect_host_start_gate(run_dir: Path) -> tuple[dict[str, Any], bool]:
    spec = importlib.util.spec_from_file_location("n6_b2_queue_for_gate", QUEUE_RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    gate, _samples = module.collect_start_gate(run_dir)
    return {"result": path_record(run_dir / "start-gate.json"),
            "checks": gate["checks"], "status": gate["status"]}, gate["status"] == "passed"


def evaluate(queue_path: Path, include_path: Path, output: Path) -> dict[str, Any]:
    if output.exists() or output.with_suffix("").exists():
        raise FileExistsError(f"use a new --output path for a new gate record: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    run_dir = output.with_suffix("")
    run_dir.mkdir()
    check_names = (
        "queue_and_specs", "include_provenance", "memory_cap_actual_self_test",
        "resource_monitor_failure_fail_closed", "process_inventory_available",
        "no_other_heavy_experiment", "caffeinate_available", "pmset_log_available",
        "pmset_assertions_available", "disk_guard", "host_start_gate",
    )
    checks = {name: False for name in check_names}
    result: dict[str, Any] = {"schema_version": 1, "task": "N6-B2 prestart gates",
                              "recorded_at": now(), "status": "failed", "checks": checks,
                              "errors": [], "queue": str(queue_path),
                              "include_provenance": str(include_path),
                              "engine": path_record(ENGINE),
                              "queue_runner": path_record(QUEUE_RUNNER)}
    try:
        inputs = validate_inputs(queue_path, include_path)
        result["inputs"] = inputs
        checks["queue_and_specs"] = True
        checks["include_provenance"] = True
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        result["errors"].append(f"inputs: {error}")
    try:
        inventory, heavy = process_inventory()
        result["process_inventory_before"] = inventory
        result["active_heavy_processes_before"] = heavy
        checks["process_inventory_available"] = inventory["exit_code"] == 0
        checks["no_other_heavy_experiment"] = not heavy and checks["process_inventory_available"]
    except (OSError, ValueError) as error:
        result["errors"].append(f"process_inventory: {error}")
    checks["caffeinate_available"] = shutil.which("caffeinate") is not None
    for option, check in (("log", "pmset_log_available"),
                          ("assertions", "pmset_assertions_available")):
        try:
            row = pmset_available(option)
            result[f"pmset_{option}"] = row
            checks[check] = row["exit_code"] == 0
        except (OSError, ValueError) as error:
            result["errors"].append(f"pmset_{option}: {error}")
    try:
        disk = shutil.disk_usage(output.parent)
        minimum = result.get("inputs", {}).get("minimum_free_bytes", 35 * GIB)
        result["disk"] = {"total_bytes": disk.total, "used_bytes": disk.used,
                          "free_bytes": disk.free, "minimum_free_bytes": minimum}
        checks["disk_guard"] = disk.free >= minimum
    except OSError as error:
        result["errors"].append(f"disk: {error}")
    result["load_average_1_5_15_minutes"] = list(os.getloadavg())
    prerequisites = ("queue_and_specs", "include_provenance", "process_inventory_available",
                     "no_other_heavy_experiment", "caffeinate_available",
                     "pmset_log_available", "pmset_assertions_available", "disk_guard")
    if all(checks[name] for name in prerequisites):
        try:
            row, checks["memory_cap_actual_self_test"] = run_self_test(run_dir)
            result["memory_self_test"] = row
            row, checks["resource_monitor_failure_fail_closed"] = run_fail_closed_test(run_dir)
            result["fail_closed_test"] = row
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            result["errors"].append(f"self_test: {error}")
        if (checks["memory_cap_actual_self_test"]
                and checks["resource_monitor_failure_fail_closed"]):
            try:
                row, checks["host_start_gate"] = collect_host_start_gate(run_dir)
                result["host_start_gate"] = row
            except (OSError, ValueError, KeyError, TypeError) as error:
                result["errors"].append(f"host_start_gate: {error}")
            try:
                inventory, heavy = process_inventory()
                result["process_inventory_after"] = inventory
                result["active_heavy_processes_after"] = heavy
                checks["process_inventory_available"] &= inventory["exit_code"] == 0
                checks["no_other_heavy_experiment"] &= not heavy and inventory["exit_code"] == 0
            except (OSError, ValueError) as error:
                checks["process_inventory_available"] = False
                checks["no_other_heavy_experiment"] = False
                result["errors"].append(f"process_inventory_after: {error}")
            try:
                disk = shutil.disk_usage(output.parent)
                result["disk_after"] = {"free_bytes": disk.free}
                checks["disk_guard"] &= disk.free >= result["disk"]["minimum_free_bytes"]
            except OSError as error:
                checks["disk_guard"] = False
                result["errors"].append(f"disk_after: {error}")
    result["status"] = "passed" if all(checks.values()) else "failed"
    atomic_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--include-provenance", type=Path, default=DEFAULT_INCLUDES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = evaluate(args.queue, args.include_provenance, args.output)
    print(json.dumps({"status": result["status"], "checks": result["checks"],
                      "errors": result["errors"], "output": str(args.output),
                      "sha256": sha256(args.output)}, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
