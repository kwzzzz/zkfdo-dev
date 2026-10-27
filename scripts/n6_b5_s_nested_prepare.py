#!/usr/bin/env python3
"""Prepare the B S-only nested-array rerun without starting zkFuzz."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_QUEUE = ROOT / (
    "runs/n6-b2-2026-10-09.noindex/"
    "pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json"
)
PANIC_COUNTS = ROOT / "runs/n6-b5-2026-10-17.noindex/panic-counts.json"
DEFAULT_OUTPUT = ROOT / "runs/n6-b5-2026-10-17.noindex/s-nested-prep"
NEW_RUNNER = ROOT / "scripts/run_n6_b5_s_nested_queue.py"
OLD_BINARY_SHA256 = "ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def checked_json(path: Path, expected_sha: str) -> dict:
    if sha256(path) != expected_sha:
        raise ValueError(f"SHA-256 mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def replace_binary(source_spec: dict, binary: Path, binary_sha: str) -> tuple[dict, str]:
    spec = deepcopy(source_spec)
    old_pins = [row for row in spec["pinned_files"] if Path(row["path"]).name == "zkfuzz"]
    if len(old_pins) != 1 or old_pins[0]["sha256"] != OLD_BINARY_SHA256:
        raise ValueError("source S spec has an unexpected zkFuzz pin")
    old_path = old_pins[0]["path"]
    if sha256(Path(old_path)) != OLD_BINARY_SHA256:
        raise ValueError("original zkFuzz binary changed")
    old_pins[0]["path"] = str(binary)
    old_pins[0]["sha256"] = binary_sha
    if not spec["targets"]:
        raise ValueError("S spec has no targets")
    for target in spec["targets"]:
        if not target.get("command") or target["command"][0] != old_path:
            raise ValueError("source S target does not call the pinned zkFuzz binary")
        target["command"][0] = str(binary)
    return spec, old_path


def rebind_path(value: str, old_parent: Path, new_parent: Path) -> str:
    target = (old_parent / value).resolve()
    if not target.is_relative_to(ROOT / "runs") or not target.exists():
        raise ValueError(f"source preflight reference missing or outside runs: {target}")
    return os.path.relpath(target, new_parent)


def rebind_preflight(source: dict, source_path: Path, new_path: Path,
                     source_spec_path: Path, source_spec_sha: str,
                     new_spec_path: Path, new_spec_sha: str) -> dict:
    if (source.get("kind") != "policy_a_preflight"
            or source.get("status") not in {"passed", "passed_compile_not_requested"}
            or source.get("spec_sha256") != source_spec_sha):
        raise ValueError("source preflight is not a passed ledger for the source S spec")
    ledger = deepcopy(source)
    ledger["spec_path"] = str(new_spec_path)
    ledger["spec_sha256"] = new_spec_sha
    for snapshot in ledger["source_snapshots"]:
        snapshot["copied_path"] = rebind_path(
            snapshot["copied_path"], source_path.parent, new_path.parent)
    for row in ledger["compile"]:
        for key in ("stdout_path", "stderr_path"):
            if row.get(key):
                row[key] = rebind_path(row[key], source_path.parent, new_path.parent)
    ledger["nested_binary_rebind"] = {
        "source_preflight": relative(source_path),
        "source_preflight_sha256": sha256(source_path),
        "source_spec": relative(source_spec_path),
        "source_spec_sha256": source_spec_sha,
        "allowed_spec_changes": ["pinned zkFuzz path and SHA-256", "target command executable"],
        "reason": "circom preflight compile and source snapshots do not use the zkFuzz executable",
    }
    return ledger


def prepare(binary: Path, expected_binary_sha: str, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"preparation already exists: {output}")
    if not binary.is_file() or sha256(binary) != expected_binary_sha:
        raise ValueError("repaired zkFuzz binary is missing or has a different SHA-256")
    if not NEW_RUNNER.is_file():
        raise ValueError("S-only queue runner is missing")
    panic = json.loads(PANIC_COUNTS.read_text(encoding="utf-8"))
    if panic.get("b_main_w_nested_array_affected_units") != []:
        raise ValueError("B W units require a separate rerun plan")
    source_sha = sha256(SOURCE_QUEUE)
    source = json.loads(SOURCE_QUEUE.read_text(encoding="utf-8"))
    if (source.get("unit_count") != 30 or source.get("spec_count") != 60
            or source.get("budget_policy", {}).get("total_budget_seconds") != 3600
            or source.get("budget_policy", {}).get("physical_memory_cap_bytes") != 10 * 1024**3):
        raise ValueError("source B queue denominator or budget changed")
    old_proof_ref = source["preflight_reuse"]
    old_proof_path = ROOT / old_proof_ref["path"]
    old_proof = checked_json(old_proof_path, old_proof_ref["sha256"])
    if old_proof.get("status") != "passed":
        raise ValueError("source B preflight proof is not passed")

    output.mkdir(parents=True, exist_ok=False)
    new_units = []
    proof_rows = {}
    manifest_rows = []
    for source_unit in source["units"]:
        unit_id = source_unit["unit_id"]
        source_spec_path = ROOT / source_unit["split_spec"]
        source_spec_sha = source_unit["split_spec_sha256"]
        source_spec = checked_json(source_spec_path, source_spec_sha)
        if (source_spec.get("method") != "split"
                or source_spec.get("total_budget_seconds") != 3600
                or source_spec.get("memory_cap_bytes") != 10 * 1024**3
                or source_spec.get("initial_seed") != source_unit["seed"]):
            raise ValueError(f"S spec settings changed: {unit_id}")
        new_spec, old_binary_path = replace_binary(source_spec, binary, expected_binary_sha)
        new_spec_path = output / "specs" / f"{unit_id}-S-nested.json"
        save_new(new_spec_path, new_spec)
        new_spec_sha = sha256(new_spec_path)

        old_row = old_proof["rows"][f"{unit_id}:S"]
        old_ledger_path = ROOT / old_row["destination_preflight"]
        old_ledger = checked_json(old_ledger_path, old_row["destination_preflight_sha256"])
        new_ledger_path = output / "preflight-bindings" / unit_id / "S" / "preflight.json"
        rebound = rebind_preflight(old_ledger, old_ledger_path, new_ledger_path,
                                   source_spec_path, source_spec_sha,
                                   new_spec_path, new_spec_sha)
        save_new(new_ledger_path, rebound)
        new_ledger_sha = sha256(new_ledger_path)
        proof_rows[f"{unit_id}:S"] = {
            "status": "passed_binary_only_rebind",
            "source_spec": relative(source_spec_path),
            "source_spec_sha256": source_spec_sha,
            "destination_spec": relative(new_spec_path),
            "destination_spec_sha256": new_spec_sha,
            "source_preflight": relative(old_ledger_path),
            "source_preflight_sha256": old_row["destination_preflight_sha256"],
            "destination_preflight": relative(new_ledger_path),
            "destination_preflight_sha256": new_ledger_sha,
            "old_zkfuzz_binary": old_binary_path,
            "old_zkfuzz_binary_sha256": OLD_BINARY_SHA256,
            "new_zkfuzz_binary": str(binary),
            "new_zkfuzz_binary_sha256": expected_binary_sha,
        }
        unit = {key: deepcopy(value) for key, value in source_unit.items()
                if key not in {"whole_spec", "whole_spec_sha256", "source_whole_spec",
                               "source_whole_spec_sha256"}}
        unit["split_spec"] = relative(new_spec_path)
        unit["split_spec_sha256"] = new_spec_sha
        new_units.append(unit)
        manifest_rows.append({"unit_id": unit_id, "seed": unit["seed"],
                              "target_index": unit["target_index"],
                              "source_spec_sha256": source_spec_sha,
                              "new_spec_sha256": new_spec_sha,
                              "source_preflight_sha256": old_row["destination_preflight_sha256"],
                              "new_preflight_sha256": new_ledger_sha})

    proof = {
        "schema_version": 1,
        "kind": "n6_b5_s_nested_preflight_binary_only_reuse",
        "status": "passed",
        "source_queue": relative(SOURCE_QUEUE),
        "source_queue_sha256": source_sha,
        "source_proof": relative(old_proof_path),
        "source_proof_sha256": old_proof_ref["sha256"],
        "required_spec_count": 30,
        "recorded_spec_count": len(proof_rows),
        "rows": proof_rows,
    }
    proof_path = output / "preflight-proof.json"
    save_new(proof_path, proof)
    queue = deepcopy(source)
    queue.update({
        "task": "N6-B S nested-array rerun, preparation only",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "methods": ["S"],
        "unit_count": 30,
        "spec_count": 30,
        "units": new_units,
        "source_queues": [{"path": relative(SOURCE_QUEUE), "sha256": source_sha}],
        "queue_runner": {"path": relative(NEW_RUNNER), "sha256": sha256(NEW_RUNNER)},
        "preflight_reuse": {"path": relative(proof_path), "sha256": sha256(proof_path)},
        "zkfuzz_binary": {"path": str(binary), "sha256": expected_binary_sha},
        "rerun_policy": {"methods": ["S"], "retry_once_on": ["environment_pressure",
                                                       "runner_interruption"],
                         "representative": "last unpressured completed run, else last flagged run"},
    })
    queue_path = output / "queue-b-s-nested.json"
    save_new(queue_path, queue)
    manifest = {
        "schema_version": 1,
        "status": "prepared_not_executed",
        "source_queue": relative(SOURCE_QUEUE),
        "source_queue_sha256": source_sha,
        "panic_counts": relative(PANIC_COUNTS),
        "panic_counts_sha256": sha256(PANIC_COUNTS),
        "old_zkfuzz_sha256": OLD_BINARY_SHA256,
        "new_zkfuzz_binary": str(binary),
        "new_zkfuzz_sha256": expected_binary_sha,
        "queue": relative(queue_path),
        "queue_sha256": sha256(queue_path),
        "preflight_proof": relative(proof_path),
        "preflight_proof_sha256": sha256(proof_path),
        "unit_count": len(new_units),
        "spec_count": len(manifest_rows),
        "rows": manifest_rows,
    }
    save_new(output / "preparation.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = prepare(args.binary.resolve(), args.binary_sha256, args.output.resolve())
    print(json.dumps({"status": result["status"], "queue": result["queue"],
                      "queue_sha256": result["queue_sha256"],
                      "unit_count": result["unit_count"],
                      "spec_count": result["spec_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
