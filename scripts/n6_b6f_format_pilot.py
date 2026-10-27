#!/usr/bin/env python3
"""B6f format gate: classify method limits and recheck the existing v2.2 pilot.

The recheck action reads the two existing result files without invoking J. The
execute-v1 action is reserved for miiz and writes a new pilot directory. Neither
action reads a verdict field or candidate value.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

import n6_b5_format_pilot as original
import n6_b6e_j_runner as b6e
import n6_b6b_runtime_paths as paths
import n6_j3_b_pilot_wait4 as selection
import run_n6_j1 as runner
from n6_b5_j_adapter import ENGINE_V1_SHA, ENGINE_V22_SHA


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/n6-b6f-2026-10-20.noindex"
EXTERNAL = Path("/Volumes/zkfdo-jcache/n6-b6f-batch1x")
WORKSPACES = EXTERNAL / "hint-workspaces"
STORES = EXTERNAL / "instance-stores"
CACHE = EXTERNAL / "cache"
OLD_V22_PILOT = b6e.OUT / "pilot-v2.2.noindex"

# These are the exact, source-derived method limits. The first note is emitted
# by mod.rs:1228-1233 through repair.rs:913-922. The abort and diagnostic-copy
# limits are at repair.rs:1120-1165; the two region bounds are at :1371-1375
# and :1562-1565. repair.rs:775-795 supplies the v2.2 error_kind mapping.
DEVIATION_NOTE = "deviation_not_hint_assigned: no `<--` statement carries a deviated signal"
ABORT_NOTE = re.compile(
    r"the generator aborted in [^\n]* line [0-9]+ "
    r"\((?:constraint|assert|unclassified)\) "
    r"and no new statement there can be blanked\Z"
)
TOOL_UNAVAILABLE_DETAIL = re.compile(
    r"\b(?:no such file or directory|executable not found|command not found|"
    r"permission denied|failed to spawn|could not spawn)\b",
    re.IGNORECASE,
)
METHOD_LIMIT_NOTES = {
    DEVIATION_NOTE: "tool_or_unsupported",
    "the predicate instance has too many constraints": "region_limit",
    "repair region has too many constraints": "region_limit",
    "the diagnostic copy still aborts after blanking 6 checks": "diagnostic_failure",
}


class FormatInspectionError(runner.RunnerError):
    """A refused format disposition with a structured environment flag."""

    def __init__(self, code: str, message: str, *, environment: bool) -> None:
        self.code = code
        self.environment = environment
        super().__init__(message)


class MethodInspectionError(FormatInspectionError):
    """A method error that the format gate refuses to accept as unsupported."""

    def __init__(self, code: str, stage: str, kind: str | None,
                 note: str | None, *, environment: bool = False) -> None:
        self.stage = stage
        self.error_kind = kind
        self.note = note
        super().__init__(code, f"{code}: {stage}: {kind}: {note}",
                         environment=environment)


def require(condition: bool, message: str) -> None:
    runner.require(condition, message)


def classify_method_error(stage: str, record: dict[str, Any],
                          engine_sha: str) -> str:
    """Accept a known method limit; reject tool faults and unlisted notes.

    The caller must only pass repair/injection records. This function does not
    inspect any result verdict or candidate value.
    """
    require(stage in {"repair", "injection"} and isinstance(record, dict),
            "invalid method-error stage or record")
    require(record.get("outcome") == "error", "method-error outcome differs")
    note = record.get("note")
    kind = record.get("error_kind")
    if not isinstance(note, str) or not note or not (
            kind is None or isinstance(kind, str)):
        raise MethodInspectionError("method_error_malformed", stage,
                                    kind if isinstance(kind, str) else None,
                                    note if isinstance(note, str) else None)
    require(engine_sha in {ENGINE_V1_SHA, ENGINE_V22_SHA},
            "method-error engine is not fixed v1 or v2.2")
    expected_kind = METHOD_LIMIT_NOTES.get(note)
    if expected_kind is None and ABORT_NOTE.fullmatch(note):
        expected_kind = "tool_or_unsupported"
    if engine_sha == ENGINE_V1_SHA and note == "repair region has too many constraints":
        expected_kind = None
    environment = (kind == "io" or note == "z3 is not available" or
                   b6e.RESOURCE_DETAIL.search(note) is not None or
                   TOOL_UNAVAILABLE_DETAIL.search(note) is not None)
    if expected_kind is None:
        raise MethodInspectionError("method_error_unlisted", stage, kind, note,
                                    environment=environment)
    if kind != (None if engine_sha == ENGINE_V1_SHA else expected_kind):
        raise MethodInspectionError("method_error_kind_mismatch", stage, kind, note,
                                    environment=environment)
    return "unsupported"


def check_result_shape(path: Path, row: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep B5's non-verdict checks, allowing source-derived method limits.

    Returned details are restricted to stage, outcome, error_kind, and note.
    The JSON parser necessarily loads the envelope, but this code never
    accesses verdict entries, witness data, or candidate values.
    """
    result = json.loads(path.read_text())
    require(isinstance(result, dict) and
            result.get("schema") == "zkfdo-lifting-result-v1" and
            result.get("request_sha256") == row["request_sha256"] and
            result.get("candidate_sha256") == row["candidate_sha256"] and
            isinstance(result.get("preparation"), dict) and
            result["preparation"].get("status") == "ok" and
            isinstance(result.get("classes"), list),
            "pilot result envelope or structure invalid")
    costs = result.get("costs")
    require(isinstance(costs, dict) and type(costs.get("steps")) is list,
            "pilot tool-disposition metadata missing")
    if runner.ENGINE_SHA256 == ENGINE_V22_SHA:
        require(type(costs.get("solver_calls")) is list,
                "v2.2 pilot solver-call metadata missing")
        for call in costs["solver_calls"]:
            require(isinstance(call, dict), "pilot solver-call structure invalid")
            solver_outcome = call.get("outcome")
            if solver_outcome in {"solver_error", "solver_unavailable", "tool_error"}:
                raise FormatInspectionError(
                    "solver_tool_failure", "pilot solver tool failure",
                    environment=True)
            require(solver_outcome in {"sat", "unsat", "unknown", "timeout"},
                    "pilot solver invalid outcome")
    else:
        require(runner.ENGINE_SHA256 == ENGINE_V1_SHA,
                "pilot engine has no supported format gate")
    for step in costs["steps"]:
        require(isinstance(step, dict) and isinstance(step.get("status"), str),
                "pilot step structure invalid")
        if step["status"] == "tool_error":
            raise FormatInspectionError("step_tool_failure",
                                        "pilot step tool failure", environment=True)
        require(step["status"] not in {"failed", "unresolved", "error", "timeout"},
                "pilot step failure or invalid status")
    method_errors: list[dict[str, Any]] = []
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
        if outcome in {"solver_error", "solver_unavailable", "tool_error"} or (
                isinstance(note, str) and note.startswith("solver error:")):
            raise FormatInspectionError("synthesis_tool_failure",
                                        "pilot synthesis tool failure",
                                        environment=True)
        for stage in ("injection", "repair"):
            method = synthesis.get(stage)
            if method is None:
                continue
            require(isinstance(method, dict) and
                    isinstance(method.get("outcome"), str),
                    "pilot repair structure invalid")
            if method["outcome"] == "error":
                classify_method_error(stage, method, runner.ENGINE_SHA256)
                method_errors.append({"stage": stage, "outcome": "error",
                                      "error_kind": method.get("error_kind"),
                                      "note": method.get("note")})
        if runner.ENGINE_SHA256 == ENGINE_V1_SHA and outcome in {
                "cone_too_large", "model_not_reproduced", "timeout",
                "sat_without_model", "propagation_only", "sweep_unsat"}:
            require(type(synthesis.get("sweep_branches")) is int and
                    synthesis["sweep_branches"] >= 0,
                    "v1 pilot sweep did not record successful completion")
    return method_errors


def recheck_v22(index_path: Path, index_sha: str, old_output: Path,
                report_path: Path) -> dict[str, Any]:
    """Recheck old result files only; never start either engine or a join."""
    require(index_path == b6e.OUT / "request-index-v2.2.json" and
            old_output == OLD_V22_PILOT and
            report_path.parent == OUT and not report_path.exists(),
            "B6f v2.2 recheck paths differ or report exists")
    runner.checked_sha(index_path, index_sha, "B6f v2.2 request index")
    index = b6e.read_object(index_path)
    rows = index.get("requests")
    require(isinstance(rows, list) and len(rows) == 107 and
            all(isinstance(row, dict) and row.get("queue_order") == order
                for order, row in enumerate(rows)),
            "B6f v2.2 index order invalid")
    selection_path = b6e.OUT / "pilot-selection.json"
    selection_record = b6e.read_object(selection_path)
    chosen = [rows[9], rows[25]]
    require(selection_record == {"schema_version": 1,
                                 "requests": original.selected_ids(chosen)} and
            all(row.get("preparation_failure") is None for row in chosen),
            "B6f pilot selection differs from queue 9 and 25")
    old_state_path = old_output / "state.json"
    old_state = b6e.read_object(old_state_path)
    require(old_state.get("kind") == "n6_b5_format_only_pilot_state" and
            old_state.get("request_index_sha256") == index_sha and
            old_state.get("engine_sha256") == ENGINE_V22_SHA and
            old_state.get("selection_sha256") == runner.sha256(selection_path) and
            old_state.get("measurement_method") == "wait4" and
            old_state.get("status") in {"stopped", "passed"},
            "B6f old v2.2 pilot state differs")
    runner.ENGINE_SHA256 = ENGINE_V22_SHA
    checked: list[dict[str, Any]] = []
    for ordinal, row in enumerate(chosen):
        order = row["queue_order"]
        path = old_output / "requests" / f"{ordinal:02d}-{order:06d}" / "lift/result.json"
        require(path.is_file() and not path.is_symlink(),
                f"B6f old pilot result missing at queue {order}")
        errors = check_result_shape(path, row)
        checked.append({"queue_order": order, "status": "format_passed",
                        "result_path": str(path),
                        "result_sha256": runner.sha256(path),
                        "method_errors": errors})
    report = {"schema_version": 1, "kind": "n6_b6f_v22_pilot_result_recheck",
              "status": "passed", "engine_sha256": ENGINE_V22_SHA,
              "request_index": str(index_path), "request_index_sha256": index_sha,
              "selection_sha256": runner.sha256(selection_path),
              "old_pilot_state_sha256": runner.sha256(old_state_path),
              "old_pilot_path": str(old_output),
              "checker_sha256": runner.sha256(Path(__file__)),
              "join_rechecked": False, "requests": checked,
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "verdict_values_read": False}
    OUT.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return report


def execute_v1(args: argparse.Namespace) -> None:
    """Run a fresh v1 pilot when miiz invokes the command in Kitty."""
    require(args.engine == "v1" and
            args.output == OUT / "pilot-v1.noindex" and
            args.cache_root == CACHE / "pilot-v1" and
            args.workspace_root == WORKSPACES and
            args.instance_root == STORES,
            "B6f v1 pilot paths differ from prepared new paths")
    index = b6e.configure("v1", args.index, args.index_sha256,
                          args.static_preflight, args.static_preflight_sha256,
                          args.first_lead_review_sha256,
                          args.second_lead_review_sha256)
    base = b6e.b6.base_index()
    chosen = selection.select_requests(index, base)
    require([row["queue_order"] for row in chosen] == [9, 25] and
            all(row["preparation_failure"] is None for row in chosen),
            "B6f pilot is not original max/min queue 9 and 25")
    runner.checked_sha(args.selection, args.selection_sha256,
                       "B6f pilot selection")
    require(json.loads(args.selection.read_text()) ==
            {"schema_version": 1, "requests": original.selected_ids(chosen)},
            "B6f pilot selection differs from original rule")
    paths.EXTERNAL = EXTERNAL
    workspace_root = paths.require_external_root(args.workspace_root)
    instance_root = paths.require_external_root(args.instance_root)
    paths.require_external_root(args.cache_root.parent)
    require(not args.output.exists() and not args.cache_root.exists(),
            "B6f pilot output/cache already exists")

    def run_lift(row: dict[str, Any], run_dir: Path, cache: Path,
                 store: Path) -> dict[str, Any]:
        runner.checked_sha(runner.ENGINE, runner.ENGINE_SHA256,
                           "locked B6f pilot engine")
        runner.check_disk(workspace_root, instance_root)
        run_dir.mkdir(parents=True, exist_ok=False)
        target = run_dir / "lift"
        external_output = paths.external_lift_output(target, args.output,
                                                     workspace_root)
        routed_store = paths.external_store(store, args.output, instance_root)
        command = [str(runner.ENGINE), "experiment", "lift",
                   "--request", row["request"], "--cache", str(cache),
                   "--circom-bin", str(runner.CIRCOM),
                   "--instance-store", str(routed_store),
                   "--output", str(external_output)]
        try:
            metrics = original.run_quiet_wait4(command, run_dir / "lift.stderr.log")
        finally:
            if external_output.is_dir():
                paths.publish_lift_output(external_output, target,
                                          args.output, workspace_root)
            elif not target.exists():
                target.mkdir(parents=True, exist_ok=False)
        result_path = target / "result.json"
        return {**metrics,
                "result_path": str(result_path) if result_path.is_file() else None}

    original.run_lift = run_lift
    original.check_result_shape = check_result_shape
    original.run_format_pilot(args.index, args.index_sha256,
                              b6e.b6.BASE, runner.sha256(b6e.b6.BASE),
                              args.selection, args.cache_root, args.output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("recheck-v2.2", "execute-v1"), required=True)
    parser.add_argument("--engine", choices=("v1", "v2.2"))
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--existing-output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--static-preflight", type=Path)
    parser.add_argument("--static-preflight-sha256")
    parser.add_argument("--first-lead-review-sha256")
    parser.add_argument("--second-lead-review-sha256")
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--selection-sha256")
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--instance-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "recheck-v2.2":
            require(args.existing_output is not None and args.report is not None,
                    "B6f v2.2 recheck paths missing")
            report = recheck_v22(args.index, args.index_sha256,
                                 args.existing_output, args.report)
            print(json.dumps({"status": "passed", "checked_orders": [9, 25],
                              "report": str(args.report),
                              "report_sha256": runner.sha256(args.report),
                              "method_errors": [
                                  {"queue_order": item["queue_order"],
                                   "errors": item["method_errors"]}
                                  for item in report["requests"]]},
                             ensure_ascii=False, sort_keys=True))
            return 0
        require(args.engine == "v1" and
                all(value is not None for value in (
                    args.static_preflight, args.static_preflight_sha256,
                    args.first_lead_review_sha256,
                    args.second_lead_review_sha256, args.selection,
                    args.selection_sha256, args.cache_root,
                    args.workspace_root, args.instance_root, args.output)),
                "B6f v1 pilot arguments missing")
        execute_v1(args)
        print("pilot: exit_code=0 format_ok=1", flush=True)
        return 0
    except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError) as error:
        print(f"B6f pilot: exit_code=2 format_ok=0 ({error})",
              file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
