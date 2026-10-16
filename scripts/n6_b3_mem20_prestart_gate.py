#!/usr/bin/env python3
"""Run the B2 host start gates for the prepared six-unit B mem20 queue.

The B2 gate stays unchanged. This version validates the 20 GiB sensitivity
queue and its reused preflights before calling the same host checks and tests.
It does not start a campaign.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-prep"
SOURCE_QUEUE = (ROOT / "runs/n6-b2-2026-10-09.noindex"
                / "pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json")
SOURCE_INCLUDES = ROOT / "runs/n6-b2-2026-10-09.noindex/include-provenance-final-v3.json"
B2_GATE = ROOT / "scripts/n6_b2_prestart_gate.py"
QUEUE_RUNNER = ROOT / "scripts/run_n6_v4_3_queue.py"
GIB = 1024**3


def load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ValueError(f"cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


b2 = load_module("n6_b2_gate_for_mem20", B2_GATE)
runner = load_module("n6_v4_3_queue_for_mem20_gate", QUEUE_RUNNER)
source_validate_inputs = b2.validate_inputs


def validate_inputs(queue_path: Path, include_path: Path) -> dict[str, Any]:
    if include_path.resolve() != SOURCE_INCLUDES.resolve():
        raise ValueError("mem20 must use the pinned B2 include provenance")
    source = json.loads(SOURCE_QUEUE.read_text(encoding="utf-8"))
    source_checks = source_validate_inputs(SOURCE_QUEUE, include_path)
    source_by_id = {unit["unit_id"]: unit for unit in source["units"]}

    preparation_path = PREP / "preparation.json"
    preparation = json.loads(preparation_path.read_text(encoding="utf-8"))
    queue = runner.load_queue(queue_path)
    queue_sha = runner.sha256(queue_path)
    if (preparation.get("status") != "prepared_not_executed"
            or preparation.get("campaign_executed") is not False
            or preparation.get("candidate_contents_opened") is not False
            or preparation.get("queue") != runner.path_text(queue_path)
            or preparation.get("queue_sha256") != queue_sha
            or preparation.get("source_queue_sha256") != runner.sha256(SOURCE_QUEUE)
            or queue.get("branch") != "B" or queue.get("concurrency") != 1
            or queue.get("minimum_free_disk_gib") != 35
            or queue.get("budget_policy", {}).get("physical_memory_cap_bytes") != 20 * GIB
            or queue.get("budget_policy", {}).get("total_budget_seconds") != 3600
            or queue.get("budget_policy", {}).get("split_attempt_cap_seconds") != 30
            or queue.get("budget_policy", {}).get("seeds")
            != [2026100601, 2026100602, 2026100603]):
        raise ValueError("mem20 preparation or queue policy mismatch")

    selected = [row["unit_id"] for row in preparation["memory_cap_counts"]
                if row["W_memory_cap"] > 0 or row["S_memory_cap"] > 0]
    ordered = [unit["unit_id"] for unit in source["units"] if unit["unit_id"] in selected]
    if (len(selected) != 6 or len(set(selected)) != 6
            or preparation.get("selected_unit_ids") != ordered
            or [unit["unit_id"] for unit in queue["units"]] != ordered
            or {unit_id.split("-seed-", 1)[0] for unit_id in ordered}
            != {"6079a717f929aaf04a04e329", "340107e1f1d8b0a45656cffa"}
            or queue.get("unit_count") != 6 or queue.get("spec_count") != 12):
        raise ValueError("mem20 selected units or source order mismatch")

    proof_rows = runner.load_preflight_rows(queue)
    for unit in queue["units"]:
        original = source_by_id[unit["unit_id"]]
        for method, key in (("W", "whole"), ("S", "split")):
            source_path = ROOT / original[f"{key}_spec"]
            new_path = runner.spec_for(unit, method)
            old_spec = json.loads(source_path.read_text(encoding="utf-8"))
            new_spec = json.loads(new_path.read_text(encoding="utf-8"))
            differences = {name for name in old_spec.keys() | new_spec.keys()
                           if old_spec.get(name) != new_spec.get(name)}
            if (runner.sha256(source_path) != original[f"{key}_spec_sha256"]
                    or differences != {"campaign_id", "memory_cap_bytes"}
                    or old_spec.get("memory_cap_bytes") != 10 * GIB
                    or new_spec.get("memory_cap_bytes") != 20 * GIB
                    or old_spec.get("total_budget_seconds") != 3600
                    or new_spec.get("total_budget_seconds") != 3600
                    or new_spec.get("concurrency") != 1):
                raise ValueError(f"mem20 spec changed beyond the sensitivity rule: {unit['unit_id']}:{method}")
            proof = proof_rows[f"{unit['unit_id']}:{method}"]
            if (proof.get("status") != "passed"
                    or proof.get("source_spec") != original[f"{key}_spec"]
                    or proof.get("source_spec_sha256") != original[f"{key}_spec_sha256"]
                    or proof.get("destination_spec") != unit[f"{key}_spec"]
                    or proof.get("destination_spec_sha256") != unit[f"{key}_spec_sha256"]
                    or proof.get("allowed_spec_differences")
                    != ["campaign_id", "memory_cap_bytes"]):
                raise ValueError(f"mem20 preflight linkage mismatch: {unit['unit_id']}:{method}")
            ledger = json.loads((ROOT / proof["destination_preflight"])
                                .read_text(encoding="utf-8"))
            if (ledger.get("status") != "passed"
                    or ledger.get("spec_sha256") != unit[f"{key}_spec_sha256"]
                    or ledger.get("preflight_reuse", {}).get("source_preflight_sha256")
                    != proof["source_preflight_sha256"]):
                raise ValueError(f"mem20 preflight ledger mismatch: {unit['unit_id']}:{method}")
    return {
        "queue": b2.path_record(queue_path),
        "preparation": b2.path_record(preparation_path),
        "source_queue": b2.path_record(SOURCE_QUEUE),
        "source_include_provenance": b2.path_record(include_path),
        "source_checks": source_checks,
        "unit_count": 6,
        "spec_count": 12,
        "preflight_row_count": len(proof_rows),
        "minimum_free_bytes": queue["minimum_free_disk_gib"] * GIB,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=PREP / "queue-b-mem20.json")
    parser.add_argument("--include-provenance", type=Path, default=SOURCE_INCLUDES)
    parser.add_argument("--output", type=Path,
                        default=PREP.parent / "gates/prestart-gate-mem20.json")
    parser.add_argument("--validate-inputs-only", action="store_true")
    args = parser.parse_args()
    if args.validate_inputs_only:
        inputs = validate_inputs(args.queue, args.include_provenance)
        print(json.dumps({"status": "valid", "units": inputs["unit_count"],
                          "specs": inputs["spec_count"],
                          "preflight_rows": inputs["preflight_row_count"]}))
        return 0
    b2.validate_inputs = validate_inputs
    result = b2.evaluate(args.queue, args.include_provenance, args.output)
    result["task"] = "N6-B3 mem20 prestart gates"
    result["gate_adapter"] = b2.path_record(Path(__file__))
    b2.atomic_json(args.output, result)
    print(json.dumps({"status": result["status"], "checks": result["checks"],
                      "errors": result["errors"], "output": str(args.output),
                      "sha256": b2.sha256(args.output)}, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
