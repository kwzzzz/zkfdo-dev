#!/usr/bin/env python3
"""Freeze N6-A2 specs, phase queues, and execution-safe preflight reuse records."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "runs/n6-a1b-2026-10-08"
RUN = ROOT / "runs/n6-a2-2026-10-08"
SOURCE_QUEUE = SOURCE_ROOT / "queue-v3.json"
SOURCE_PREFLIGHT = SOURCE_ROOT / "preflight-v3/preflight-all.json"
UNITS = SOURCE_ROOT / "preparation-units.json"
RUNNER = ROOT / "scripts/run_policy_a_engine_v3.py"
QUEUE_RUNNER = ROOT / "scripts/run_n6_a2_queue.py"
EXCLUDED_IDENTIFIER = "aq-038-4e5dcd2256b8"
EXPECTED_SOURCE_QUEUE_SHA256 = "f84ae9d85bd7eb5289e14e5cafd9cb0234b93fe1ce0dfc5d7805e5305f8b6201"


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


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def update_spec(source: Path, destination: Path, runner_hash: str) -> str:
    spec = json.loads(source.read_text())
    spec["campaign_id"] = spec["campaign_id"].replace("N6-A1b-", "N6-A2-")
    found = False
    for row in spec.get("pinned_files", []):
        if row.get("label") == "runner-v3":
            if Path(row["path"]).resolve() != RUNNER.resolve():
                raise ValueError(f"unexpected runner path in {source}")
            row["sha256"] = runner_hash
            found = True
    if not found:
        raise ValueError(f"runner-v3 pin absent in {source}")
    atomic_json(destination, spec)
    return sha256(destination)


def adjust_preflight_path(value: str, source_root: Path, destination_root: Path) -> str:
    absolute = (source_root / value).resolve()
    return os.path.relpath(absolute, destination_root)


def reuse_preflight(source_row: dict[str, Any], destination: Path, spec: Path,
                    spec_hash: str) -> dict[str, Any]:
    source_ledger_path = ROOT / source_row["preflight"]
    source_ledger_root = source_ledger_path.parent
    ledger = deepcopy(json.loads(source_ledger_path.read_text()))
    if not str(ledger.get("status", "")).startswith("passed"):
        raise ValueError(f"refusing failed preflight reuse: {source_ledger_path}")
    for snapshot in ledger.get("source_snapshots", []):
        snapshot["copied_path"] = adjust_preflight_path(
            snapshot["copied_path"], source_ledger_root, destination)
    for compile_row in ledger.get("compile", []):
        for name in ("stdout_path", "stderr_path"):
            if compile_row.get(name):
                compile_row[name] = adjust_preflight_path(
                    compile_row[name], source_ledger_root, destination)
        compile_row["source_wall_seconds"] = compile_row.get("wall_seconds")
        compile_row["wall_seconds"] = 0.0 if compile_row.get("wall_seconds") is not None else None
        compile_row["resource"] = None
        compile_row["reuse_claim"] = True
    ledger.update({
        "spec_path": str(spec.resolve()),
        "spec_sha256": spec_hash,
        "started_at": now(),
        "wall_seconds": 0.0,
        "compile_wall_seconds_sum": 0.0,
        "compile_reuse_claim": True,
        "preflight_reuse": {
            "kind": "execution_only_runner_and_campaign_id_change",
            "source_spec": source_row["spec"],
            "source_spec_sha256": source_row["spec_sha256"],
            "source_preflight": source_row["preflight"],
            "source_preflight_sha256": sha256(source_ledger_path),
            "allowed_spec_differences": [
                "campaign_id",
                "pinned_files[label=runner-v3].sha256",
            ],
            "reason": (
                "The runner change only makes process-tree RSS observation fail closed during "
                "campaign execution; source snapshots, compile commands, tools, and targets are unchanged."
            ),
        },
        "note": "No compile was rerun; the source preflight snapshots and compile verdict are reused.",
    })
    ledger_path = destination / "preflight.json"
    atomic_json(ledger_path, ledger)
    return {
        "status": "passed",
        "failure_type": None,
        "source": "reused_execution_only_change",
        "started_at": ledger["started_at"],
        "finished_at": ledger["started_at"],
        "wall_seconds": 0.0,
        "reported_preflight_wall_seconds": 0.0,
        "reported_compile_wall_seconds_sum": 0.0,
        "reported_compile_status_counts": ledger.get("compile_status_counts"),
        "spec": repo_relative(spec),
        "spec_sha256": spec_hash,
        "preflight": repo_relative(ledger_path),
        "preflight_sha256": sha256(ledger_path),
        "exit_code": 0,
        "artifact_cleanup": None,
        "source_preflight": source_row["preflight"],
        "source_preflight_sha256": sha256(source_ledger_path),
    }


def assert_allowed_spec_diff(source: Path, destination: Path) -> None:
    before = json.loads(source.read_text())
    after = json.loads(destination.read_text())
    before_campaign = before.pop("campaign_id")
    after_campaign = after.pop("campaign_id")
    if before_campaign.replace("N6-A1b-", "N6-A2-") != after_campaign:
        raise ValueError("unexpected campaign ID change")
    before_runner = next(row for row in before["pinned_files"] if row["label"] == "runner-v3")
    after_runner = next(row for row in after["pinned_files"] if row["label"] == "runner-v3")
    before_runner_hash = before_runner.pop("sha256")
    after_runner_hash = after_runner.pop("sha256")
    if before != after or before_runner_hash == after_runner_hash:
        raise ValueError(f"spec differs outside the allowed execution-only fields: {source}")


def main() -> int:
    if sha256(SOURCE_QUEUE) != EXPECTED_SOURCE_QUEUE_SHA256:
        raise ValueError("A1b source queue hash changed")
    source_queue = json.loads(SOURCE_QUEUE.read_text())
    source_summary = json.loads(SOURCE_PREFLIGHT.read_text())
    if source_summary.get("status") != "completed":
        raise ValueError("A1b preflight summary is incomplete")
    branches: dict[str, str] = {}
    unit_inventory = json.loads(UNITS.read_text())
    for row in unit_inventory["development_units"]:
        branches[row["unit_id"]] = "A-D"
    for row in unit_inventory["aq_stage1_units"]:
        branches[row["unit_id"]] = "A-Q"

    runner_hash = sha256(RUNNER)
    queue_runner_hash = sha256(QUEUE_RUNNER)
    selected = [row for row in source_queue["units"]
                if row["identifier"] != EXCLUDED_IDENTIFIER]
    excluded = [row for row in source_queue["units"]
                if row["identifier"] == EXCLUDED_IDENTIFIER]
    if len(excluded) != 3 or len(selected) != 81:
        raise ValueError("unexpected aq-038 exclusion denominator")

    phase_units: dict[str, list[dict[str, Any]]] = {"A-D": [], "A-Q": []}
    specs_root = RUN / "specs-v1"
    for source_unit in selected:
        unit = deepcopy(source_unit)
        phase = branches.get(unit["identifier"])
        if phase not in phase_units:
            raise ValueError(f"branch is missing for {unit['identifier']}")
        for key in ("whole", "split"):
            source_spec = ROOT / unit[f"{key}_spec"]
            destination = specs_root / source_spec.name
            destination_hash = update_spec(source_spec, destination, runner_hash)
            assert_allowed_spec_diff(source_spec, destination)
            unit[f"{key}_spec"] = repo_relative(destination)
            unit[f"{key}_spec_sha256"] = destination_hash
        unit["phase"] = phase
        phase_units[phase].append(unit)

    queues = {}
    for phase, units in phase_units.items():
        queue_path = RUN / f"queue-{phase.lower()}-v1.json"
        queue = {
            "schema_version": 2,
            "version": 1,
            "task": "N6-A2 A execute",
            "phase": phase,
            "status": "preflight_pending",
            "concurrency": 3,
            "load_sample_seconds": 10,
            "minimum_free_disk_gib": 40,
            "preflight_policy": "all selected A1b preflight records frozen before execute",
            "preflight_spec_count": len(units) * 2,
            "unit_count": len(units),
            "unit_order": "source queue order within phase; W then S",
            "source_queue": {
                "path": repo_relative(SOURCE_QUEUE),
                "sha256": EXPECTED_SOURCE_QUEUE_SHA256,
            },
            "queue_runner": {"path": repo_relative(QUEUE_RUNNER), "sha256": queue_runner_hash},
            "target_list": source_queue["target_list"],
            "excluded_identifier": EXCLUDED_IDENTIFIER,
            "units": units,
        }
        atomic_json(queue_path, queue)
        queues[phase] = {"path": repo_relative(queue_path), "sha256": sha256(queue_path),
                         "unit_count": len(units), "spec_count": len(units) * 2}

        output = RUN / "execute" / phase.lower()
        results = {}
        for unit in units:
            for method, spec_key in (("W", "whole_spec"), ("S", "split_spec")):
                key = f"{unit['unit_id']}:{method}"
                source_row = source_summary["results"].get(key)
                if source_row is None or source_row.get("status") != "passed":
                    raise ValueError(f"selected preflight is not passed: {key}")
                destination = output / "preflight" / unit["unit_id"] / method
                spec = ROOT / unit[spec_key]
                results[key] = reuse_preflight(
                    source_row, destination, spec, unit[f"{spec_key}_sha256"])
        summary = {
            "schema_version": 1,
            "kind": "n6_a2_preflight_all",
            "status": "completed",
            "queue": repo_relative(queue_path),
            "queue_sha256": queues[phase]["sha256"],
            "required_spec_count": len(units) * 2,
            "recorded_spec_count": len(results),
            "passed_count": len(results),
            "failed_count": 0,
            "started_at": now(),
            "finished_at": now(),
            "invocation_wall_seconds": 0.0,
            "preflight_wall_seconds_sum": 0.0,
            "source_summary": repo_relative(SOURCE_PREFLIGHT),
            "source_summary_sha256": sha256(SOURCE_PREFLIGHT),
            "reuse_reason": "only campaign_id and fail-closed runner hash changed",
            "results": results,
        }
        atomic_json(output / "preflight-all.json", summary)

    exclusion_source = ROOT / "runs/n6-a1-2026-10-07/units" / EXCLUDED_IDENTIFIER / "leave-one-out.patch"
    exclusion = {
        "identifier": EXCLUDED_IDENTIFIER,
        "excluded_methods": ["W", "S"],
        "excluded_seeds": [row["seed"] for row in excluded],
        "reason": "leave-one-out patch restored a whole overlapping hunk after the template close brace",
        "patch": {"path": repo_relative(exclusion_source), "sha256": sha256(exclusion_source)},
        "selected_hunk": "@@ -9,815 +8,0 @@ template EmailAddrWithNameRegex(msg_bytes) {",
        "observed_compile_error": (
            "P1012 at email_addr_with_name_regex.circom:21:2; var num_bytes is outside the template"
        ),
    }
    atomic_json(RUN / "aq-038-exclusion.json", exclusion)
    execution_list = {
        "schema_version": 1,
        "task": "N6-A2 execute list",
        "created_at": now(),
        "source_queue": {"path": repo_relative(SOURCE_QUEUE),
                         "sha256": EXPECTED_SOURCE_QUEUE_SHA256},
        "ordering": ["A-D", "A-Q"],
        "phase_barrier": "A-Q starts only after every A-D unit completes",
        "queues": queues,
        "runner": {"path": repo_relative(RUNNER), "sha256": runner_hash},
        "queue_runner": {"path": repo_relative(QUEUE_RUNNER), "sha256": queue_runner_hash},
        "selected_unit_count": len(selected),
        "selected_spec_count": len(selected) * 2,
        "excluded": exclusion,
        "unit_ids": {phase: [row["unit_id"] for row in phase_units[phase]]
                     for phase in ("A-D", "A-Q")},
    }
    atomic_json(RUN / "execution-list-v1.json", execution_list)
    print(json.dumps({
        "execution_list": repo_relative(RUN / "execution-list-v1.json"),
        "execution_list_sha256": sha256(RUN / "execution-list-v1.json"),
        "runner_sha256": runner_hash,
        "queues": queues,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
