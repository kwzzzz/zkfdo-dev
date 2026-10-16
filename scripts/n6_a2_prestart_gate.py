#!/usr/bin/env python3
"""Record the final N6-A2 execution gates without opening candidate files."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a2-2026-10-08"
EXECUTION_LIST = RUN / "execution-list-v1.json"
INCLUDES = RUN / "include-provenance.json"
SELF_TEST = RUN / "gates/v3-self-test/self-test-v3.json"
OUTPUT = RUN / "gates/prestart-gates.json"
SPEC_MANIFEST = RUN / "spec-manifest.json"
MINIMUM_FREE_BYTES = 40 * 1024**3


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


def active_heavy_processes() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,%cpu=,%mem=,command="],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    rows = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 4)
        if len(fields) != 5:
            continue
        pid, ppid, cpu, memory, command = fields
        try:
            executable = shlex.split(command)[0]
        except (ValueError, IndexError):
            executable = command.split()[0] if command.split() else ""
        basename = Path(executable).name
        is_heavy = basename in {"zkfuzz", "circom", "cargo", "rustc"}
        is_heavy = is_heavy or basename in {
            "run_n6_a2_execute.py", "run_n6_a2_queue.py", "run_policy_a_engine_v3.py"
        }
        if is_heavy and int(pid) != os.getpid():
            rows.append({"pid": int(pid), "ppid": int(ppid), "cpu_percent": float(cpu),
                         "memory_percent": float(memory), "command": command})
    return {"exit_code": result.returncode, "stderr": result.stderr.strip() or None}, rows


def main() -> int:
    execution = json.loads(EXECUTION_LIST.read_text())
    includes = json.loads(INCLUDES.read_text())
    self_test = json.loads(SELF_TEST.read_text())
    specs = []
    for phase in execution["ordering"]:
        queue_path = ROOT / execution["queues"][phase]["path"]
        queue = json.loads(queue_path.read_text())
        for unit in queue["units"]:
            for method, key in (("W", "whole_spec"), ("S", "split_spec")):
                path = ROOT / unit[key]
                specs.append({"unit_id": unit["unit_id"], "phase": phase, "method": method,
                              "path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)})
    atomic_json(SPEC_MANIFEST, {"schema_version": 1, "task": "N6-A2 spec manifest",
                                "created_at": now(), "spec_count": len(specs), "specs": specs})

    fail_closed = subprocess.run(
        [sys.executable, "-m", "unittest",
         "tests.policy_a_engine_v3_test.PolicyAEngineV3Test."
         "test_process_tree_monitor_failure_is_fail_closed", "-v"],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)
    fail_closed_log = RUN / "gates/fail-closed-test.log"
    fail_closed_log.write_text(fail_closed.stdout)
    ps_result, heavy = active_heavy_processes()
    pmset = subprocess.run(["pmset", "-g", "log"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    disk = shutil.disk_usage(RUN)
    checks = {
        "execution_spec_denominator": len(specs) == 162,
        "include_provenance": includes.get("status") == "passed"
                              and includes.get("spec_count") == 162,
        "memory_cap_actual_self_test": all(self_test["checks"].values()),
        "ps_failure_fail_closed": fail_closed.returncode == 0,
        "process_inventory_available": ps_result["exit_code"] == 0,
        "no_other_heavy_experiment": not heavy,
        "caffeinate_available": shutil.which("caffeinate") is not None,
        "pmset_log_available": pmset.returncode == 0,
        "disk_guard": disk.free >= MINIMUM_FREE_BYTES,
    }
    result = {
        "schema_version": 1,
        "task": "N6-A2 prestart gates",
        "recorded_at": now(),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "execution_list": {"path": EXECUTION_LIST.relative_to(ROOT).as_posix(),
                           "sha256": sha256(EXECUTION_LIST)},
        "spec_manifest": {"path": SPEC_MANIFEST.relative_to(ROOT).as_posix(),
                          "sha256": sha256(SPEC_MANIFEST), "spec_count": len(specs)},
        "include_provenance": {"path": INCLUDES.relative_to(ROOT).as_posix(),
                               "sha256": sha256(INCLUDES)},
        "memory_self_test": {"path": SELF_TEST.relative_to(ROOT).as_posix(),
                             "sha256": sha256(SELF_TEST)},
        "fail_closed_test": {"path": fail_closed_log.relative_to(ROOT).as_posix(),
                             "sha256": sha256(fail_closed_log),
                             "exit_code": fail_closed.returncode},
        "process_inventory": ps_result,
        "active_heavy_processes": heavy,
        "load_average_1_5_15_minutes": os.getloadavg(),
        "disk": {"total_bytes": disk.total, "used_bytes": disk.used,
                 "free_bytes": disk.free, "minimum_free_bytes": MINIMUM_FREE_BYTES},
        "pmset": {"exit_code": pmset.returncode, "stderr": pmset.stderr.strip() or None},
    }
    atomic_json(OUTPUT, result)
    print(json.dumps({"status": result["status"], "checks": checks,
                      "load": result["load_average_1_5_15_minutes"],
                      "disk_free_bytes": disk.free, "sha256": sha256(OUTPUT)}, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
