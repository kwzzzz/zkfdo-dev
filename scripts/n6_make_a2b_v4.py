#!/usr/bin/env python3
"""Create N6-A2b A/B v4 specs, preflight-reuse proofs, and frozen queues."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a2b-2026-10-08.noindex"
RUNNER = ROOT / "scripts/run_policy_a_engine_v4.py"
QUEUE_RUNNER = ROOT / "scripts/run_n6_v4_queue.py"
SUPERVISOR = ROOT / "scripts/run_n6_v4_campaigns.py"
A_QUEUES = [
    ROOT / "runs/n6-a2-2026-10-08/queue-a-d-v1.json",
    ROOT / "runs/n6-a2-2026-10-08/queue-a-q-v1.json",
]
A_PREFLIGHTS = [
    ROOT / "runs/n6-a2-2026-10-08/execute/a-d/preflight-all.json",
    ROOT / "runs/n6-a2-2026-10-08/execute/a-q/preflight-all.json",
]
B_QUEUE = ROOT / "runs/n6-2026-10-06/queue-v7.json"
B_PREFLIGHT = ROOT / "runs/n6-2026-10-06/stage1-v7/preflight-all.json"


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
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def normalized_preflight_spec(value: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(value)
    value.pop("campaign_id")
    value["pinned_files"] = [
        row for row in value.get("pinned_files", [])
        if not str(row.get("label", "")).startswith("runner-v")
    ]
    return value


def update_spec(source: Path, destination: Path, branch: str, runner_hash: str) -> str:
    before = json.loads(source.read_text())
    after = deepcopy(before)
    if branch == "A":
        if not after["campaign_id"].startswith("N6-A2-"):
            raise ValueError(f"unexpected A campaign ID: {source}")
        after["campaign_id"] = after["campaign_id"].replace("N6-A2-", "N6-A2b-", 1)
    else:
        if not after["campaign_id"].startswith("N6-B-stage1-"):
            raise ValueError(f"unexpected B campaign ID: {source}")
        after["campaign_id"] = after["campaign_id"].replace(
            "N6-B-stage1-", "N6-B-v4-stage1-", 1)
    runner_rows = [row for row in after["pinned_files"]
                   if str(row.get("label", "")).startswith("runner-v")]
    if len(runner_rows) != 1:
        raise ValueError(f"expected one runner pin: {source}")
    runner_rows[0].update({"label": "runner-v4", "path": str(RUNNER.resolve()),
                           "sha256": runner_hash})
    if normalized_preflight_spec(before) != normalized_preflight_spec(after):
        raise ValueError(f"compile-relevant spec fields changed: {source}")
    atomic_json(destination, after)
    return sha256(destination)


def load_passed_rows(paths: list[Path]) -> dict[str, dict[str, Any]]:
    rows = {}
    for path in paths:
        summary = json.loads(path.read_text())
        if summary.get("status") != "completed":
            raise ValueError(f"source preflight is incomplete: {path}")
        for key, row in summary["results"].items():
            if row.get("status") != "passed":
                raise ValueError(f"source preflight did not pass: {key}")
            if key in rows:
                raise ValueError(f"duplicate source preflight key: {key}")
            rows[key] = row
    return rows


def materialize_preflight(unit: dict[str, Any], method: str, key: str,
                          source_row: dict[str, Any], branch: str) -> tuple[Path, str]:
    source_ledger = ROOT / source_row["preflight"]
    source_root = source_ledger.parent
    destination_spec = ROOT / unit[f"{key}_spec"]
    destination_root = RUN / "preflight-v4" / branch.lower() / unit["unit_id"] / method
    ledger = deepcopy(json.loads(source_ledger.read_text()))
    for snapshot in ledger.get("source_snapshots", []):
        absolute = (source_root / snapshot["copied_path"]).resolve()
        snapshot["copied_path"] = os.path.relpath(absolute, destination_root)
    for compile_row in ledger.get("compile", []):
        for name in ("stdout_path", "stderr_path"):
            if compile_row.get(name):
                absolute = (source_root / compile_row[name]).resolve()
                compile_row[name] = os.path.relpath(absolute, destination_root)
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
            "kind": "n6_v4_runtime_monitor_only_change",
            "source_preflight": relative(source_ledger),
            "source_preflight_sha256": sha256(source_ledger),
            "allowed_spec_differences": ["campaign_id", "runner-v3 pin -> runner-v4 pin"],
            "reason": "source snapshots and every compile-relevant spec field are unchanged",
        },
        "note": "No preflight compile was rerun; this ledger binds the verified source snapshots to the v4 spec hash.",
    })
    destination = destination_root / "preflight.json"
    atomic_json(destination, ledger)
    return destination, sha256(destination)


def transform_units(source_units: list[dict[str, Any]], branch: str,
                    runner_hash: str) -> list[dict[str, Any]]:
    destination_root = RUN / "specs-v4" / branch.lower()
    units = []
    for source_unit in source_units:
        unit = deepcopy(source_unit)
        for method, key in (("W", "whole"), ("S", "split")):
            source = ROOT / unit[f"{key}_spec"]
            destination = destination_root / source.name.replace(
                "-W.json", "-W-v4.json").replace("-S.json", "-S-v4.json")
            unit[f"source_{key}_spec"] = relative(source)
            unit[f"source_{key}_spec_sha256"] = sha256(source)
            unit[f"{key}_spec"] = relative(destination)
            unit[f"{key}_spec_sha256"] = update_spec(
                source, destination, branch, runner_hash)
        units.append(unit)
    return units


def make_reuse_proof(branch: str, units: list[dict[str, Any]],
                     source_rows: dict[str, dict[str, Any]],
                     source_summaries: list[Path]) -> tuple[Path, str]:
    rows = {}
    for unit in units:
        for method, key in (("W", "whole"), ("S", "split")):
            row_key = f"{unit['unit_id']}:{method}"
            source_row = source_rows.get(row_key)
            if source_row is None:
                raise ValueError(f"missing preflight row: {row_key}")
            source_spec = ROOT / unit[f"source_{key}_spec"]
            destination_spec = ROOT / unit[f"{key}_spec"]
            if normalized_preflight_spec(json.loads(source_spec.read_text())) != \
                    normalized_preflight_spec(json.loads(destination_spec.read_text())):
                raise ValueError(f"preflight inputs differ: {row_key}")
            ledger = ROOT / source_row["preflight"]
            if not ledger.is_file() or sha256(ledger) != source_row["preflight_sha256"]:
                raise ValueError(f"preflight ledger hash mismatch: {row_key}")
            destination_ledger, destination_ledger_hash = materialize_preflight(
                unit, method, key, source_row, branch)
            rows[row_key] = {
                "status": "passed",
                "allowed_spec_differences": ["campaign_id", "runner-v3 pin -> runner-v4 pin"],
                "source_spec": relative(source_spec),
                "source_spec_sha256": sha256(source_spec),
                "destination_spec": relative(destination_spec),
                "destination_spec_sha256": sha256(destination_spec),
                "source_preflight": relative(ledger),
                "source_preflight_sha256": sha256(ledger),
                "destination_preflight": relative(destination_ledger),
                "destination_preflight_sha256": destination_ledger_hash,
            }
    proof = {
        "schema_version": 1,
        "kind": "n6_v4_preflight_reuse_proof",
        "branch": branch,
        "created_at": now(),
        "status": "passed",
        "reason": "v4 changes campaign runtime monitoring only; compile inputs are byte-equivalent",
        "source_summaries": [{"path": relative(path), "sha256": sha256(path)}
                             for path in source_summaries],
        "required_spec_count": len(units) * 2,
        "recorded_spec_count": len(rows),
        "rows": rows,
    }
    path = RUN / f"preflight-reuse-{branch.lower()}-v4.json"
    atomic_json(path, proof)
    return path, sha256(path)


def assert_budget(branch: str, units: list[dict[str, Any]]) -> None:
    expected_total = 600 if branch == "A" else 3600
    for unit in units:
        if unit["seed"] not in {2026100601, 2026100602, 2026100603}:
            raise ValueError(f"unexpected seed: {unit['unit_id']}")
        for method, key in (("W", "whole"), ("S", "split")):
            spec = json.loads((ROOT / unit[f"{key}_spec"]).read_text())
            if spec["total_budget_seconds"] != expected_total:
                raise ValueError(f"budget changed: {unit['unit_id']} {method}")
            expected_attempt = expected_total if method == "W" else 30
            if spec["attempt_cap_seconds"] != expected_attempt:
                raise ValueError(f"attempt cap changed: {unit['unit_id']} {method}")
            if spec["memory_cap_bytes"] != 10 * 1024**3:
                raise ValueError(f"memory cap changed: {unit['unit_id']} {method}")


def make_queue(branch: str, units: list[dict[str, Any]], proof: Path, proof_hash: str,
               sources: list[Path], runner_hash: str, queue_runner_hash: str) -> tuple[Path, str]:
    queue = {
        "schema_version": 4,
        "version": 4,
        "task": f"N6-{branch} Policy-A v4 execute",
        "branch": branch,
        "status": "ready_for_execution",
        "created_at": now(),
        "concurrency": 3,
        "minimum_free_disk_gib": 40 if branch == "A" else 35,
        "unit_count": len(units),
        "spec_count": len(units) * 2,
        "output_directory_suffix": ".noindex",
        "source_queues": [{"path": relative(path), "sha256": sha256(path)} for path in sources],
        "runner": {"path": relative(RUNNER), "sha256": runner_hash},
        "queue_runner": {"path": relative(QUEUE_RUNNER), "sha256": queue_runner_hash},
        "preflight_reuse": {"path": relative(proof), "sha256": proof_hash},
        "phase_barrier": "A-D completes before A-Q starts" if branch == "A" else None,
        "large_unit_rule": (
            "at most one million_plus primary unit runs at once" if branch == "B" else None),
        "budget_policy": {
            "total_budget_seconds": 600 if branch == "A" else 3600,
            "split_attempt_cap_seconds": 30,
            "whole_attempt_cap": "remaining total budget",
            "seeds": [2026100601, 2026100602, 2026100603],
            "physical_memory_cap_bytes": 10 * 1024**3,
        },
        "start_gate": {
            "ac_power": True, "lowpowermode": 0, "thermal_warning": False,
            "minimum_memorystatus_level": 50, "swap_growth_window_seconds": 60,
            "maximum_swap_growth_bytes": 0,
        },
        "new_unit_gate": {
            "minimum_memorystatus_level": 40, "swap_growth_window_seconds": 60,
            "maximum_swap_growth_bytes": 0,
        },
        "health_policy": {
            "sample_seconds": 1, "thermal_sample_seconds": 60,
            "pressure_swap_growth_bytes": 512 * 1024**2,
            "pressure_memorystatus_below": 15,
            "pressure_thermal_warning": True,
            "pressure_retry": "queue tail with concurrency 1; preserve both runs",
            "result_selection": "only an execution without environment_pressure",
        },
        "units": units,
    }
    path = RUN / f"queue-{branch.lower()}-v4.json"
    atomic_json(path, queue)
    return path, sha256(path)


def main() -> int:
    for path in [RUNNER, QUEUE_RUNNER, SUPERVISOR, *A_QUEUES, *A_PREFLIGHTS,
                 B_QUEUE, B_PREFLIGHT]:
        if not path.is_file():
            raise FileNotFoundError(path)
    a_sources = [json.loads(path.read_text()) for path in A_QUEUES]
    a_source_units = [unit for source in a_sources for unit in source["units"]]
    if len(a_source_units) != 81 or any(unit["identifier"].startswith("aq-038-")
                                        for unit in a_source_units):
        raise ValueError("A denominator or aq-038 exclusion changed")
    b_source = json.loads(B_QUEUE.read_text())
    if len(b_source["units"]) != 30:
        raise ValueError("B denominator changed")
    runner_hash = sha256(RUNNER)
    queue_runner_hash = sha256(QUEUE_RUNNER)
    a_units = transform_units(a_source_units, "A", runner_hash)
    b_units = transform_units(b_source["units"], "B", runner_hash)
    assert_budget("A", a_units)
    assert_budget("B", b_units)
    a_proof, a_proof_hash = make_reuse_proof(
        "A", a_units, load_passed_rows(A_PREFLIGHTS), A_PREFLIGHTS)
    b_proof, b_proof_hash = make_reuse_proof(
        "B", b_units, load_passed_rows([B_PREFLIGHT]), [B_PREFLIGHT])
    a_queue, a_queue_hash = make_queue(
        "A", a_units, a_proof, a_proof_hash, A_QUEUES, runner_hash, queue_runner_hash)
    b_queue, b_queue_hash = make_queue(
        "B", b_units, b_proof, b_proof_hash, [B_QUEUE], runner_hash, queue_runner_hash)
    manifest = {
        "schema_version": 1, "task": "N6-A2b v4 execution manifest",
        "created_at": now(), "status": "prepared_not_executed",
        "order": ["A", "B"],
        "runner": {"path": relative(RUNNER), "sha256": runner_hash},
        "queue_runner": {"path": relative(QUEUE_RUNNER), "sha256": queue_runner_hash},
        "supervisor": {"path": relative(SUPERVISOR), "sha256": sha256(SUPERVISOR)},
        "queues": {
            "A": {"path": relative(a_queue), "sha256": a_queue_hash, "units": 81},
            "B": {"path": relative(b_queue), "sha256": b_queue_hash, "units": 30},
        },
        "outputs": {
            "A": relative(RUN / "a-execute.noindex"),
            "B": relative(RUN / "b-execute.noindex"),
            "events": relative(RUN / "execution-events.jsonl"),
            "summary": relative(RUN / "execution-summary.json"),
            "terminal_log": relative(RUN / "terminal.log"),
        },
    }
    manifest_path = RUN / "execution-manifest-v4.json"
    atomic_json(manifest_path, manifest)
    print(json.dumps({"runner_sha256": runner_hash,
                      "queue_runner_sha256": queue_runner_hash,
                      "A_queue_sha256": a_queue_hash,
                      "B_queue_sha256": b_queue_hash,
                      "manifest": relative(manifest_path),
                      "manifest_sha256": sha256(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
