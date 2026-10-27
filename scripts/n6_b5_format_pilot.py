#!/usr/bin/env python3
"""Run two B J pilot requests and save only execution and format evidence.

The locked J engines produce their normal result and instance files. This
pilot checks JSON structure and non-verdict tool metadata, including class
synthesis error status, without reading or copying verdict values.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import n6_j2_pilot as low_level
import n6_j3_b_pilot_wait4 as b_selection
import run_n6_j1 as runner
from n6_b5_j_adapter import ENGINE_V1_SHA, ENGINE_V22_SHA


def require(condition: bool, message: str) -> None:
    if not condition:
        raise runner.RunnerError(message)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_result_shape(path: Path, row: dict[str, Any]) -> None:
    """Check execution metadata and types; leave verdict field contents unopened."""
    result = json.loads(path.read_text())
    require(isinstance(result, dict) and
            result.get("schema") == "zkfdo-lifting-result-v1" and
            result.get("request_sha256") == row["request_sha256"] and
            result.get("candidate_sha256") == row["candidate_sha256"] and
            isinstance(result.get("preparation"), dict) and
            result["preparation"].get("status") == "ok" and
            isinstance(result.get("classes"), list) and
            isinstance(result.get("verdict_counts"), dict),
            "pilot result envelope or structure invalid")
    costs = result.get("costs")
    require(isinstance(costs, dict) and type(costs.get("steps")) is list,
            "pilot tool-disposition metadata missing")
    # v1 has no solver_calls array. Its solver errors can instead be recorded
    # only in class synthesis metadata while its cost step still says "done".
    if runner.ENGINE_SHA256 == ENGINE_V22_SHA:
        require(type(costs.get("solver_calls")) is list,
                "v2.2 pilot solver-call metadata missing")
        for call in costs["solver_calls"]:
            require(isinstance(call, dict) and
                    call.get("outcome") in {"sat", "unsat", "unknown", "timeout"},
                    "pilot solver tool failure or invalid outcome")
    else:
        require(runner.ENGINE_SHA256 == ENGINE_V1_SHA,
                "pilot engine has no supported format gate")
    # Bounded solver unknown/timeout and an honest witness abort can be normal
    # unknown paths. Explicit tool failures stop the pilot.
    for step in costs["steps"]:
        require(isinstance(step, dict) and isinstance(step.get("status"), str) and
                step["status"] not in {"tool_error", "failed", "unresolved",
                                       "error", "timeout"},
                "pilot step tool failure or invalid status")
    for class_record in result["classes"]:
        require(isinstance(class_record, dict), "pilot class structure invalid")
        synthesis = class_record.get("synthesis")
        if synthesis is None:
            continue
        require(isinstance(synthesis, dict), "pilot synthesis structure invalid")
        outcome = synthesis.get("b_outcome")
        note = synthesis.get("note")
        require((outcome is None or isinstance(outcome, str)) and
                (note is None or isinstance(note, str)),
                "pilot synthesis metadata structure invalid")
        require(outcome not in {"solver_error", "solver_unavailable", "tool_error"} and
                not (isinstance(note, str) and note.startswith("solver error:")),
                "pilot synthesis tool failure")
        for repair_name in ("injection", "repair"):
            repair = synthesis.get(repair_name)
            if repair is not None:
                require(isinstance(repair, dict) and
                        isinstance(repair.get("outcome"), str) and
                        repair["outcome"] != "error",
                        "pilot repair tool failure or invalid structure")
        if runner.ENGINE_SHA256 == ENGINE_V1_SHA and outcome in {
                "cone_too_large", "model_not_reproduced", "timeout",
                "sat_without_model", "propagation_only", "sweep_unsat"}:
            # v1 records the sweep step as "done" even on Err. A completed
            # sweep records its branch count; its absence is a hidden error.
            require(type(synthesis.get("sweep_branches")) is int and
                    synthesis["sweep_branches"] >= 0,
                    "v1 pilot sweep did not record successful completion")


def check_instances_shape(path: Path, relative_results: list[str]) -> None:
    """Check the join envelope; leave its classes and verdicts unopened."""
    joined = json.loads(path.read_text())
    require(isinstance(joined, dict) and
            joined.get("schema") == "zkfdo-instance-verdicts-v1" and
            joined.get("results") == relative_results and
            type(joined.get("conflicts")) is int and joined["conflicts"] == 0,
            "pilot instance envelope invalid")


def selected_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"request_id": Path(row["request"]).stem,
             "queue_order": row["queue_order"],
             "revision_id": row["revision_id"]} for row in rows]


def run_quiet_wait4(command: list[str], stderr_path: Path,
                    cwd: Path | None = None) -> dict[str, Any]:
    """Discard the J CLI's verdict-bearing stdout while measuring the child."""
    started = time.monotonic()
    with stderr_path.open("x") as stderr:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.DEVNULL,
                                   stderr=stderr)
        _pid, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    return {"exit_code": process.returncode,
            "wall_seconds": time.monotonic() - started,
            "max_rss_bytes": low_level.rss_from_wait4(usage)}


def run_lift(row: dict[str, Any], run_dir: Path, cache: Path,
             store: Path) -> dict[str, Any]:
    runner.checked_sha(runner.ENGINE, runner.ENGINE_SHA256, "locked J engine")
    run_dir.mkdir(parents=True, exist_ok=False)
    target = run_dir / "lift"
    command = [str(runner.ENGINE), "experiment", "lift", "--request", row["request"],
               "--cache", str(cache), "--circom-bin", str(runner.CIRCOM),
               "--instance-store", str(store), "--output", str(target)]
    metrics = run_quiet_wait4(command, run_dir / "lift.stderr.log")
    result_path = target / "result.json"
    return {**metrics, "result_path": str(result_path) if result_path.is_file() else None}


def run_join(results: list[Path], output: Path,
             instance_path: Path) -> dict[str, Any]:
    runner.checked_sha(runner.ENGINE, runner.ENGINE_SHA256, "locked J engine")
    relative = [str(path.relative_to(output)) for path in results]
    command = [str(runner.ENGINE), "experiment", "lift-instances", "--result",
               *relative, "--output", str(instance_path)]
    return run_quiet_wait4(command, instance_path.with_suffix(".stderr.log"), output)


def run_format_pilot(index_path: Path, index_sha: str, base_path: Path,
                     base_sha: str, selection_path: Path, cache_root: Path,
                     output: Path) -> dict[str, Any]:
    index = runner.validate_index(index_path, index_sha)
    runner.checked_sha(base_path, base_sha, "B base input index")
    base = json.loads(base_path.read_text())
    require(base.get("schema") == "n6-j1-base-inputs-v1" and
            isinstance(base.get("revisions"), dict), "invalid B base input index")
    rows = b_selection.select_requests(index, base)
    require(len(rows) == 2 and all(row["preparation_failure"] is None for row in rows),
            "two callable B S requests required")
    chosen = json.loads(selection_path.read_text())
    require(chosen == {"schema_version": 1, "requests": selected_ids(rows)},
            "pre-recorded pilot selection differs")
    require(cache_root.is_absolute() and cache_root.parent.is_dir() and
            not cache_root.exists(), "pilot cache root must be a new absolute directory")
    require(output.is_absolute() and not output.exists() and
            not output.is_relative_to(cache_root) and
            not cache_root.is_relative_to(output), "pilot output must be new and separate")
    output.mkdir(parents=True)
    cache_root.mkdir()
    state: dict[str, Any] = {
        "schema_version": 1, "kind": "n6_b5_format_only_pilot_state",
        "status": "running", "started_at": stamp(),
        "request_index_sha256": index_sha, "base_index_sha256": base_sha,
        "selection_sha256": runner.sha256(selection_path),
        "engine_sha256": runner.ENGINE_SHA256,
        "measurement_method": "wait4", "requests": {}, "revisions": {},
    }
    state_path = output / "state.json"
    runner.atomic_json(state_path, state)
    revisions: dict[str, dict[str, Any]] = {}
    try:
        for order, row in enumerate(rows):
            runner.check_disk(output, cache_root)
            low_level.check_selected_request(row, base)
            revision_id = row["revision_id"]
            if revision_id not in revisions:
                ordinal = len(revisions) + 1
                revisions[revision_id] = {
                    "ordinal": ordinal,
                    "cache": cache_root / f"{ordinal:02d}",
                    "store": output / "revisions" / f"{ordinal:02d}" / "store",
                    "results": [],
                }
                revisions[revision_id]["cache"].mkdir()
            revision = revisions[revision_id]
            run_dir = output / "requests" / f"{order:02d}-{row['queue_order']:06d}"
            metrics = run_lift(row, run_dir, revision["cache"], revision["store"])
            require(metrics["exit_code"] == 0 and metrics["result_path"] is not None and
                    type(metrics["max_rss_bytes"]) is int and metrics["max_rss_bytes"] > 0,
                    "pilot J request failed or wait4 measurement missing")
            result_path = Path(metrics["result_path"])
            check_result_shape(result_path, row)
            revision["results"].append(result_path)
            state["requests"][str(row["queue_order"])] = {
                "status": "completed", "queue_order": row["queue_order"],
                "revision_id": revision_id, "request_sha256": row["request_sha256"],
                "result_path": str(result_path),
                "result_sha256": runner.sha256(result_path),
                "exit_code": metrics["exit_code"],
                "wall_seconds": metrics["wall_seconds"],
                "max_rss_bytes": metrics["max_rss_bytes"],
                "format_ok": True,
            }
            runner.atomic_json(state_path, state)
        for revision_id, revision in revisions.items():
            runner.check_disk(output, cache_root)
            ordinal = revision["ordinal"]
            instance_path = output / "revisions" / f"{ordinal:02d}" / "instances.json"
            instance_path.parent.mkdir(parents=True, exist_ok=True)
            results = revision["results"]
            metrics = run_join(results, output, instance_path)
            require(metrics["exit_code"] == 0 and instance_path.is_file() and
                    type(metrics["max_rss_bytes"]) is int and metrics["max_rss_bytes"] > 0,
                    "pilot instance join failed or wait4 measurement missing")
            check_instances_shape(instance_path,
                                  [str(path.relative_to(output)) for path in results])
            state["revisions"][f"main/{ordinal:04d}"] = {
                "revision_id": revision_id, "status": "joined",
                "result_count": len(results), "exit_code": metrics["exit_code"],
                "max_rss_bytes": metrics["max_rss_bytes"],
                "instances_path": str(instance_path),
                "instances_sha256": runner.sha256(instance_path),
                "format_ok": True,
            }
            runner.atomic_json(state_path, state)
        state["status"] = "passed"
        state["completed_at"] = stamp()
        runner.atomic_json(state_path, state)
        return state
    except Exception as error:
        state["status"] = "stopped"
        state["error_type"] = type(error).__name__
        state["completed_at"] = stamp()
        runner.atomic_json(state_path, state)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--base-index", type=Path, required=True)
    parser.add_argument("--base-index-sha256", required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--action", choices=("execute",), required=True)
    args = parser.parse_args(argv)
    runner.preflight_libraries = b_selection.preflight_libraries
    try:
        run_format_pilot(args.index.resolve(), args.index_sha256,
                         args.base_index.resolve(), args.base_index_sha256,
                         args.selection.resolve(), args.cache_root.resolve(),
                         args.output.resolve())
        print("pilot: exit_code=0 format_ok=1", flush=True)
        return 0
    except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError):
        print("pilot: exit_code=2 format_ok=0", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
