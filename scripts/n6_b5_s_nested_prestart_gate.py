#!/usr/bin/env python3
"""Check the prepared B S-only nested-array queue without starting fuzzing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "runs/n6-b5-2026-10-17.noindex/s-nested-prep"
SOURCE_QUEUE = ROOT / (
    "runs/n6-b2-2026-10-09.noindex/"
    "pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json"
)
SOURCE_INCLUDES = ROOT / "runs/n6-b2-2026-10-09.noindex/include-provenance-final-v3.json"
PANIC_COUNTS = ROOT / "runs/n6-b5-2026-10-17.noindex/panic-counts.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


b2 = load_module("n6_b2_for_b5_s_gate", ROOT / "scripts/n6_b2_prestart_gate.py")
runner = load_module("n6_b5_s_runner_for_gate", ROOT / "scripts/run_n6_b5_s_nested_queue.py")
b2.QUEUE_RUNNER = ROOT / "scripts/run_n6_b5_s_nested_queue.py"


def evaluate(queue_path: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"gate record exists: {output}")
    source_gate_path = output.with_name("source-b2-" + output.name)
    if source_gate_path.exists() or source_gate_path.with_suffix("").exists():
        raise FileExistsError(f"source gate record exists: {source_gate_path}")
    queue = runner.validate_queue(queue_path)
    panic = json.loads(PANIC_COUNTS.read_text(encoding="utf-8"))
    b_main_s = next(row for row in panic["summary_by_source_method"]
                    if row["source"] == "b_main_10gib" and row["method"] == "S")
    if (panic.get("b_main_w_nested_array_affected_units") != []
            or b_main_s["abnormal_reasons"].get("nested_array_panic_utils_rs_522") != 197):
        raise ValueError("B nested-array panic denominator or W rerun set changed")
    original_inputs = b2.validate_inputs(SOURCE_QUEUE, SOURCE_INCLUDES)
    source_gate = b2.evaluate(SOURCE_QUEUE, SOURCE_INCLUDES, source_gate_path)
    result = {
        "schema_version": 1,
        "task": "N6-B5 S-only nested-array rerun prestart gate",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if source_gate["status"] == "passed" else "failed",
        "queue": b2.path_record(queue_path),
        "queue_unit_count": len(queue["units"]),
        "queue_spec_count": queue["spec_count"],
        "methods": queue["methods"],
        "repaired_binary": b2.path_record(Path(queue["zkfuzz_binary"]["path"])),
        "panic_counts": b2.path_record(PANIC_COUNTS),
        "source_queue": b2.path_record(SOURCE_QUEUE),
        "source_inputs": original_inputs,
        "source_host_gate": b2.path_record(source_gate_path),
        "source_host_gate_status": source_gate["status"],
        "checks": {"s_only_binary_spec_preflight": True,
                   "source_b_inputs": True,
                   "b_w_rerun_empty": True,
                   "host_gate": source_gate["status"] == "passed"},
        "fuzzing_executed": False,
    }
    b2.atomic_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=PREP / "queue-b-s-nested.json")
    parser.add_argument("--output", type=Path,
                        default=PREP / "gates/prestart-gate-s-nested.json")
    args = parser.parse_args()
    result = evaluate(args.queue.resolve(), args.output.resolve())
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "sha256": b2.sha256(args.output),
                      "checks": result["checks"]}, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
