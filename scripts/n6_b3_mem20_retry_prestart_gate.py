#!/usr/bin/env python3
"""Record the v4.4 mem20 retry prestart gates without starting a campaign.

Reuse the frozen mem20 input validation and B2 host checks, but bind both the
input-validation runner and the delegated host-gate runner to v4.4. The source
state and requested retry units are checked by v4.4 before any live host tests.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MEM20_GATE = ROOT / "scripts/n6_b3_mem20_prestart_gate.py"
QUEUE_RUNNER = ROOT / "scripts/run_n6_v4_4_queue.py"
DEFAULT_OUTPUT = (ROOT / "runs/n6-b3-2026-10-12.noindex"
                  / "gates/prestart-gate-mem20-retry.json")


def load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ValueError(f"cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


mem20 = load_module("n6_b3_mem20_for_retry_gate", MEM20_GATE)
runner = load_module("n6_v4_4_queue_for_mem20_retry_gate", QUEUE_RUNNER)
b2 = mem20.b2
# These assignments affect only this process's imported module objects. The
# frozen v4.3 runner, old gate scripts, and their recorded hashes stay unchanged.
mem20.runner = runner
b2.QUEUE_RUNNER = QUEUE_RUNNER
source_classify_process = b2.classify_process


def classify_process(command: str) -> bool:
    if source_classify_process(command):
        return True
    try:
        argv = shlex.split(command)
    except ValueError:
        argv = command.split()
    if not argv:
        return False
    executable = Path(argv[0]).name.lower()
    if executable.endswith(".py"):
        scripts = [executable]
    elif executable.startswith(("python", "pypy")):
        scripts = [Path(arg).name.lower() for arg in argv[1:] if arg.endswith(".py")]
    else:
        scripts = []
    return any(name in {"n6_b3_mem20_prestart_gate.py",
                        "n6_b3_mem20_retry_prestart_gate.py"} for name in scripts)


b2.classify_process = classify_process


def validate_inputs(queue_path: Path, include_path: Path, from_state: Path,
                    unit_ids: list[str]) -> dict[str, Any]:
    _queue, source_ref, selected = runner.prepare_retry(queue_path, from_state, unit_ids)
    result = mem20.validate_inputs(queue_path, include_path)
    result["retry"] = {
        "source_state": source_ref,
        "selected_unit_ids": [unit["unit_id"] for unit in selected],
        "selected_unit_count": len(selected),
        "selected_spec_count": 2 * len(selected),
        "run_number": 2,
        "run_kind": "pressure_retry",
        "concurrency": 1,
    }
    return result


def evaluate(queue_path: Path, include_path: Path, from_state: Path,
             unit_ids: list[str], output: Path) -> dict[str, Any]:
    previous_validator = b2.validate_inputs
    b2.validate_inputs = lambda queue, includes: validate_inputs(
        queue, includes, from_state, unit_ids)
    try:
        # B2 refuses an existing output or output.with_suffix("") run directory.
        result = b2.evaluate(queue_path, include_path, output)
    finally:
        b2.validate_inputs = previous_validator
    result["task"] = "N6-B3 mem20 v4.4 retry prestart gates"
    result["gate_adapter"] = b2.path_record(Path(__file__))
    result["reused_mem20_gate"] = b2.path_record(MEM20_GATE)
    result["reused_b2_gate"] = b2.path_record(mem20.B2_GATE)
    b2.atomic_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=mem20.PREP / "queue-b-mem20.json")
    parser.add_argument("--include-provenance", type=Path, default=mem20.SOURCE_INCLUDES)
    parser.add_argument("--from-state", type=Path, required=True)
    parser.add_argument("--units", nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-inputs-only", action="store_true")
    args = parser.parse_args(argv)
    if args.validate_inputs_only:
        inputs = validate_inputs(args.queue, args.include_provenance,
                                 args.from_state, args.units)
        print(json.dumps({"status": "valid", "units": inputs["unit_count"],
                          "specs": inputs["spec_count"],
                          "preflight_rows": inputs["preflight_row_count"],
                          "retry": inputs["retry"]}))
        return 0
    result = evaluate(args.queue, args.include_provenance, args.from_state,
                      args.units, args.output)
    print(json.dumps({"status": result["status"], "checks": result["checks"],
                      "errors": result["errors"], "output": str(args.output),
                      "sha256": b2.sha256(args.output)}, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
