#!/usr/bin/env python3
"""Prepare the N6-B 20 GiB sensitivity queue after the main B run completes.

This tool reads state.json and campaign ledger outcome counts. It never opens
candidate files and never starts a campaign.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = ROOT / "runs/n6-a2b-2026-10-08.noindex/queue-b-v4.json"
DEFAULT_OUTPUT = ROOT / "runs/n6-b2-2026-10-09.noindex/mem20"
QUEUE_RUNNER = ROOT / "scripts/run_n6_v4_3_queue.py"
GIB = 1024**3
SOURCE_CAP = 10 * GIB
SENSITIVITY_CAP = 20 * GIB


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repository_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def read_pinned_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not path.is_file() or sha256(path) != expected_sha256:
        raise ValueError(f"SHA-256 mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def source_preflight_rows(queue: dict[str, Any], root: Path) -> dict[str, Any]:
    declaration = queue["preflight_reuse"]
    proof_path = root / declaration["path"]
    proof = read_pinned_json(proof_path, declaration["sha256"])
    if proof.get("status") != "passed":
        raise ValueError("source preflight proof did not pass")
    expected = {f"{unit['unit_id']}:{method}" for unit in queue["units"]
                for method in ("W", "S")}
    rows = proof.get("rows")
    if not isinstance(rows, dict) or set(rows) != expected:
        raise ValueError("source preflight denominator mismatch")
    expected_specs = {
        f"{unit['unit_id']}:{method}":
        (unit[f"{name}_spec"], unit[f"{name}_spec_sha256"])
        for unit in queue["units"]
        for method, name in (("W", "whole"), ("S", "split"))
    }
    for key, row in rows.items():
        if (row.get("destination_spec"), row.get("destination_spec_sha256")) != \
                expected_specs[key]:
            raise ValueError(f"source preflight points to a different spec: {key}")
        for path_key, hash_key in (("source_preflight", "source_preflight_sha256"),
                                   ("destination_preflight", "destination_preflight_sha256"),
                                   ("destination_spec", "destination_spec_sha256")):
            path = root / row[path_key]
            if not path.is_file() or sha256(path) != row[hash_key]:
                raise ValueError(f"source preflight artifact changed: {key} {path_key}")
        if row.get("status") != "passed":
            raise ValueError(f"source preflight row did not pass: {key}")
        ledger = json.loads((root / row["destination_preflight"]).read_text(encoding="utf-8"))
        if ledger.get("spec_sha256") != expected_specs[key][1]:
            raise ValueError(f"source preflight ledger spec mismatch: {key}")
    return rows


def validate_source_queue(queue: dict[str, Any], root: Path) -> dict[str, Any]:
    if (queue.get("schema_version") != 4 or queue.get("branch") != "B"
            or queue.get("status") != "ready_for_execution"):
        raise ValueError("source must be a ready N6-B v4 queue")
    units = queue.get("units")
    if (not isinstance(units, list) or not units
            or queue.get("unit_count") != len(units)
            or queue.get("spec_count") != 2 * len(units)):
        raise ValueError("source queue unit/spec denominator mismatch")
    if len({unit["unit_id"] for unit in units}) != len(units):
        raise ValueError("duplicate source queue unit")
    for unit in units:
        for method, name in (("W", "whole"), ("S", "split")):
            spec_path = root / unit[f"{name}_spec"]
            spec = read_pinned_json(spec_path, unit[f"{name}_spec_sha256"])
            if (spec.get("memory_cap_bytes") != SOURCE_CAP
                    or spec.get("total_budget_seconds") != 3600
                    or spec.get("attempt_cap_seconds") != (3600 if method == "W" else 30)
                    or spec.get("concurrency") != 1):
                raise ValueError(f"source B policy mismatch: {unit['unit_id']}:{method}")
    return source_preflight_rows(queue, root)


def selected_clean_run(unit_id: str, state_row: dict[str, Any]) -> dict[str, Any] | None:
    runs = state_row.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError(f"no main run recorded: {unit_id}")
    clean = []
    for index, run in enumerate(runs, start=1):
        if run.get("run_number") != index:
            raise ValueError(f"run order mismatch: {unit_id}")
        pressure = run.get("environment", {}).get("environment_pressure")
        if type(pressure) is not bool:
            raise ValueError(f"unknown pressure status: {unit_id} run {index}")
        if pressure is False:
            clean.append(run)
    selected = clean[-1] if clean else None
    expected_number = selected["run_number"] if selected else None
    if state_row.get("selected_run_number") != expected_number:
        raise ValueError(f"state selected run disagrees with last clean run: {unit_id}")
    return selected


def memory_cap_count(method_row: dict[str, Any], *, unit_id: str, method: str,
                     run: dict[str, Any], main_output: Path, root: Path,
                     expected_spec_sha256: str) -> int:
    ledger_name = method_row.get("ledger")
    ledger_hash = method_row.get("ledger_sha256")
    if not isinstance(ledger_name, str) or not isinstance(ledger_hash, str):
        raise ValueError(f"missing campaign ledger: {unit_id}:{method}")
    ledger_path = (root / ledger_name).resolve()
    expected_path = (main_output / "units" / unit_id / "runs"
                     / f"{run['run_number']:02d}-{run['run_kind']}" / method
                     / "campaign" / "ledger.json").resolve()
    if ledger_path != expected_path:
        raise ValueError(f"campaign ledger path mismatch: {unit_id}:{method}")
    ledger = read_pinned_json(ledger_path, ledger_hash)
    if ledger.get("spec_sha256") != expected_spec_sha256:
        raise ValueError(f"campaign ledger spec mismatch: {unit_id}:{method}")
    counts = ledger.get("outcome_counts")
    if not isinstance(counts, dict):
        raise ValueError(f"missing outcome counts: {unit_id}:{method}")
    count = counts.get("memory_cap", 0)
    if type(count) is not int or count < 0:
        raise ValueError(f"invalid memory_cap count: {unit_id}:{method}")
    return count


def select_units(queue: dict[str, Any], state: dict[str, Any], main_output: Path,
                 root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if state.get("status") != "completed":
        raise ValueError("B main queue is not completed")
    state_units = state.get("units")
    expected = {unit["unit_id"] for unit in queue["units"]}
    if not isinstance(state_units, dict) or set(state_units) != expected:
        raise ValueError("B main state denominator mismatch")
    selected_units = []
    counts = []
    no_clean_run = []
    for unit in queue["units"]:
        unit_id = unit["unit_id"]
        run = selected_clean_run(unit_id, state_units[unit_id])
        if run is None:
            no_clean_run.append(unit_id)
            continue
        methods = run.get("methods", {})
        if set(methods) != {"W", "S"}:
            raise ValueError(f"main run methods incomplete: {unit_id}")
        by_method = {}
        for method, name in (("W", "whole"), ("S", "split")):
            by_method[method] = memory_cap_count(
                methods[method], unit_id=unit_id, method=method, run=run,
                main_output=main_output, root=root,
                expected_spec_sha256=unit[f"{name}_spec_sha256"])
        counts.append({"unit_id": unit_id, "selected_run_number": run["run_number"],
                       "W_memory_cap": by_method["W"],
                       "S_memory_cap": by_method["S"]})
        if by_method["W"] > 0 or by_method["S"] > 0:
            selected_units.append(unit)
    return selected_units, counts, no_clean_run


def sensitivity_spec(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("memory_cap_bytes") != SOURCE_CAP:
        raise ValueError("source spec does not use the B 10 GiB cap")
    campaign_id = source.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.startswith("N6-B-"):
        raise ValueError("unexpected source B campaign_id")
    changed = deepcopy(source)
    changed["memory_cap_bytes"] = SENSITIVITY_CAP
    changed["campaign_id"] = "N6-B-mem20-" + campaign_id.removeprefix("N6-B-")
    actual_differences = {key for key in source.keys() | changed.keys()
                          if source.get(key) != changed.get(key)}
    if actual_differences != {"campaign_id", "memory_cap_bytes"}:
        raise AssertionError(f"unexpected spec differences: {actual_differences}")
    return changed


def reuse_ledger(source_path: Path, destination_path: Path, destination_spec: Path,
                 *, root: Path) -> None:
    ledger = json.loads(source_path.read_text(encoding="utf-8"))
    if ledger.get("status") != "passed":
        raise ValueError(f"source preflight did not pass: {source_path}")
    source_directory = source_path.parent
    destination_directory = destination_path.parent
    for snapshot in ledger.get("source_snapshots", []):
        absolute = (source_directory / snapshot["copied_path"]).resolve()
        if not absolute.exists():
            raise ValueError(f"source preflight snapshot missing: {absolute}")
        snapshot["copied_path"] = os.path.relpath(absolute, destination_directory)
    for compile_row in ledger.get("compile", []):
        for key in ("stdout_path", "stderr_path"):
            if compile_row.get(key):
                absolute = (source_directory / compile_row[key]).resolve()
                if not absolute.is_file():
                    raise ValueError(f"source preflight log missing: {absolute}")
                compile_row[key] = os.path.relpath(absolute, destination_directory)
        compile_row["source_wall_seconds"] = compile_row.get("wall_seconds")
        compile_row["wall_seconds"] = 0.0 if compile_row.get("wall_seconds") is not None else None
        compile_row["resource"] = None
        compile_row["reuse_claim"] = True
    ledger.update({
        "spec_path": str(destination_spec.resolve()),
        "spec_sha256": sha256(destination_spec),
        "started_at": now(),
        "wall_seconds": 0.0,
        "compile_wall_seconds_sum": 0.0,
        "compile_reuse_claim": True,
        "preflight_reuse": {
            "kind": "n6_b_mem20_spec_only_change",
            "source_preflight": repository_path(source_path, root),
            "source_preflight_sha256": sha256(source_path),
            "allowed_spec_differences": ["campaign_id", "memory_cap_bytes"],
        },
        "note": "No compile was rerun; this ledger binds the source snapshots to the 20 GiB spec.",
    })
    write_json(destination_path, ledger)


def default_validate(queue_path: Path, queue_runner: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(queue_runner), "--queue", str(queue_path),
         "--action", "validate-only"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"v4.3 validate-only failed: {result.stderr.strip()}")
    response = json.loads(result.stdout)
    if response.get("status") != "valid" or response.get("queue_sha256") != sha256(queue_path):
        raise ValueError("v4.3 validate-only returned inconsistent result")
    return response


def prepare(main_output: Path, source_queue_path: Path, output: Path,
            *, root: Path = ROOT, queue_runner: Path = QUEUE_RUNNER,
            validator: Callable[[Path, Path], dict[str, Any]] = default_validate,
            ) -> dict[str, Any]:
    root = root.resolve()
    main_output = main_output.resolve()
    source_queue_path = source_queue_path.resolve()
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"mem20 output already contains files: {output}")
    state_path = main_output / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    source_queue_hash = sha256(source_queue_path)
    if state.get("queue_sha256") != source_queue_hash:
        raise ValueError("B main state does not match source queue SHA-256")
    source_queue = json.loads(source_queue_path.read_text(encoding="utf-8"))
    source_rows = validate_source_queue(source_queue, root)
    chosen, counts, no_clean_run = select_units(source_queue, state, main_output, root)

    summary: dict[str, Any] = {
        "schema_version": 1,
        "kind": "n6_b_mem20_preparation",
        "created_at": now(),
        "status": "no_target_units" if not chosen else "prepared_not_executed",
        "main_output": repository_path(main_output, root),
        "main_state_sha256": sha256(state_path),
        "source_queue": repository_path(source_queue_path, root),
        "source_queue_sha256": source_queue_hash,
        "source_unit_count": len(source_queue["units"]),
        "selected_unit_count": len(chosen),
        "selected_unit_ids": [unit["unit_id"] for unit in chosen],
        "no_clean_run_unit_ids": no_clean_run,
        "memory_cap_counts": counts,
        "candidate_contents_opened": False,
        "campaign_executed": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    if not chosen:
        write_json(output / "preparation.json", summary)
        return summary

    if not queue_runner.is_file():
        raise ValueError(f"v4.3 queue runner missing: {queue_runner}")
    units = []
    proof_rows = {}
    for source_unit in chosen:
        unit = deepcopy(source_unit)
        unit_id = unit["unit_id"]
        for method, name in (("W", "whole"), ("S", "split")):
            source_spec_path = root / source_unit[f"{name}_spec"]
            source_spec = read_pinned_json(
                source_spec_path, source_unit[f"{name}_spec_sha256"])
            destination_spec = output / "specs" / f"{unit_id}-{method}.json"
            write_json(destination_spec, sensitivity_spec(source_spec))
            unit[f"{name}_spec"] = repository_path(destination_spec, root)
            unit[f"{name}_spec_sha256"] = sha256(destination_spec)

            source_row = source_rows[f"{unit_id}:{method}"]
            source_preflight = root / source_row["destination_preflight"]
            destination_preflight = output / "preflight" / unit_id / method / "preflight.json"
            reuse_ledger(source_preflight, destination_preflight, destination_spec, root=root)
            proof_rows[f"{unit_id}:{method}"] = {
                "status": "passed",
                "allowed_spec_differences": ["campaign_id", "memory_cap_bytes"],
                "source_spec": repository_path(source_spec_path, root),
                "source_spec_sha256": sha256(source_spec_path),
                "destination_spec": repository_path(destination_spec, root),
                "destination_spec_sha256": sha256(destination_spec),
                "source_preflight": repository_path(source_preflight, root),
                "source_preflight_sha256": sha256(source_preflight),
                "destination_preflight": repository_path(destination_preflight, root),
                "destination_preflight_sha256": sha256(destination_preflight),
            }
        units.append(unit)

    proof = {
        "schema_version": 1,
        "kind": "n6_b_mem20_preflight_reuse_proof",
        "created_at": now(),
        "status": "passed",
        "source_queue": repository_path(source_queue_path, root),
        "source_queue_sha256": source_queue_hash,
        "required_spec_count": 2 * len(units),
        "recorded_spec_count": len(proof_rows),
        "rows": proof_rows,
    }
    proof_path = output / "preflight-reuse-b-mem20.json"
    write_json(proof_path, proof)

    queue = deepcopy(source_queue)
    queue.update({
        "task": "N6-B 20 GiB memory-cap sensitivity execute",
        "created_at": now(),
        "concurrency": 1,
        "unit_count": len(units),
        "spec_count": 2 * len(units),
        "units": units,
        "source_queues": [{"path": repository_path(source_queue_path, root),
                           "sha256": source_queue_hash}],
        "preflight_reuse": {"path": repository_path(proof_path, root),
                            "sha256": sha256(proof_path)},
        "queue_runner": {"path": repository_path(queue_runner, root),
                         "sha256": sha256(queue_runner)},
    })
    queue["budget_policy"]["physical_memory_cap_bytes"] = SENSITIVITY_CAP
    queue_path = output / "queue-b-mem20.json"
    write_json(queue_path, queue)
    validation = validator(queue_path, queue_runner)
    summary["queue"] = repository_path(queue_path, root)
    summary["queue_sha256"] = sha256(queue_path)
    summary["preflight_reuse"] = repository_path(proof_path, root)
    summary["preflight_reuse_sha256"] = sha256(proof_path)
    summary["validate_only"] = validation
    write_json(output / "preparation.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-output", type=Path, required=True,
                        help="completed B main execution output directory")
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE,
                        help="the exact final B queue used for the main execution")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = prepare(args.main_output, args.queue, args.output)
    print(json.dumps({key: result[key] for key in
                      ("status", "selected_unit_count", "selected_unit_ids")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
