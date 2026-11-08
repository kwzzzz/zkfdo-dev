#!/usr/bin/env python3
"""Validate and (when miiz invokes it) run B6d's 107-request J index.

This version keeps the locked engines and J verdict logic. A known intrinsic
preparation failure occupies its request slot, records only preparation
status/reason/detail, and lets the next request run. Environmental failures
and unknown reasons stop the run for review. The B6d preparation task
must never invoke the execute action.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import n6_b6_batch1x_prepare as b6
import n6_b6b_runtime_paths as external_paths
import n6_b6d_source_bindings as source_bindings
import n6_j3_b_pilot_wait4 as selection
import run_n6_j1 as runner
from n6_b5_j_adapter import (ENGINE_V1, ENGINE_V1_SHA, ENGINE_V22,
                             ENGINE_V22_SHA, verify_mem20)
from n6_j1_cache_cleanup import initialize_cache


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/n6-b6d-2026-10-20.noindex"
EXTERNAL = Path("/Volumes/zkfdo-jcache/n6-b6d-batch1x")
STAGING = EXTERNAL / "units"
WORKSPACES = EXTERNAL / "hint-workspaces"
STORES = EXTERNAL / "instance-stores"
CACHE = EXTERNAL / "cache"
SOURCE_INDEX = ROOT / "runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-v1.json"
MANIFEST = OUT / "unit-staging-manifest.json"
B_AUDIT = OUT / "b-closure-equivalence-v1.json"
A_AUDIT = OUT / "a-closure-audit-v2.json"
R1CS_AUDIT = OUT / "r1cs-equivalence.json"
GATE = OUT / "equivalence-gate-v1.json"

# Exhaustive preparation.reason values in both fixed engine sources, from
# src/candidate_review/lifting/mod.rs (v2.2 8065e2b7; v1 cb40e3e0).
# Source/candidate/compile semantics can make these requests intrinsically
# unjudgeable. The frozen J denominator still includes their rows.
INTRINSIC_REASONS = frozenset({
    "candidate_invalid", "candidate_missing_signals",
    "candidate_violates_component_constraints", "component_compile_failed",
    "component_inputs_unresolved", "component_outputs_unresolved",
    "deviation_not_hint_assigned", "entrypoint_compile_failed",
    "hint_changes_constraints", "hint_index_shape", "hint_unsupported",
    "hinted_compile_failed", "no_call_site", "reverse_hint_unsupported",
    "source_closure_unresolved", "source_parse_failed",
    "template_ambiguous", "template_unmatched",
})
ENVIRONMENT_REASONS = frozenset({
    "base_input_invalid", "base_input_missing", "component_artifacts_invalid",
    "component_witness_failed", "component_wrapper_missing",
    "entrypoint_artifacts_invalid", "entrypoint_missing", "io",
    "library_missing", "source_outside_root", "source_root_missing",
})
ENGINE_PREPARATION_REASONS = INTRINSIC_REASONS | ENVIRONMENT_REASONS


def require(condition: bool, message: str) -> None:
    runner.require(condition, message)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"JSON object expected: {path}")
    return value


def _gate_input(path: Path, digest: Any, label: str) -> dict[str, Any]:
    require(isinstance(digest, str) and len(digest) == 64,
            f"{label} SHA-256 absent")
    runner.checked_sha(path, digest, label)
    return read_object(path)


def verify_equivalence_gate(index: dict[str, Any]) -> dict[str, Any]:
    """Require the pre-index E1–E4 gate and its exact value-free evidence."""
    require(index.get("equivalence_gate") == str(GATE) and
            isinstance(index.get("equivalence_gate_sha256"), str),
            "B6d index does not pin the E1–E4 gate")
    gate = _gate_input(GATE, index["equivalence_gate_sha256"], "B6d E1–E4 gate")
    require(gate.get("schema_version") == 1 and gate.get("status") == "passed" and
            gate.get("request_count") == 107 and gate.get("pair_count") == 17 and
            all(gate.get(key) == "passed" for key in ("e1", "e2", "e3", "e4")),
            "B6d E1–E4 gate is not fully passed")
    source = _gate_input(SOURCE_INDEX, gate.get("source_index_sha256"),
                         "B6b source request index")
    manifest = _gate_input(MANIFEST, gate.get("unit_manifest_sha256"),
                           "B6d unit manifest")
    b_audit = _gate_input(B_AUDIT, gate.get("b_closure_audit_sha256"),
                          "B6d B closure audit")
    a_audit = _gate_input(A_AUDIT, gate.get("a_closure_audit_sha256"),
                          "B6d A closure audit")
    r1cs = _gate_input(R1CS_AUDIT, gate.get("r1cs_equivalence_sha256"),
                       "B6d R1CS equivalence")
    require(source.get("request_count") == 107 and
            manifest.get("source_index_sha256") ==
            gate.get("source_index_sha256") and
            manifest.get("schema") == source_bindings.EXPECTED_SCHEMA and
            manifest.get("request_count") == 107 and
            manifest.get("pair_count") == 17 and
            b_audit.get("b", {}).get("e1", {}).get("status") == "pass" and
            b_audit.get("b", {}).get("e2", {}).get("status") == "pass" and
            b_audit.get("b", {}).get("request_count") == 107 and
            b_audit.get("b", {}).get("pair_count") == 17 and
            a_audit.get("a", {}).get("status") == "pass" and
            a_audit.get("a", {}).get("request_count") == 2926 and
            r1cs.get("e3_passed") is True and r1cs.get("e4_passed") is True and
            len(r1cs.get("pairs", [])) == 17,
            "B6d E1–E4 evidence does not support the gate")
    return {"gate": gate, "source": source, "manifest": manifest}


def verify_original_index(index: dict[str, Any], original: dict[str, Any]) -> None:
    """Only path, ordered -l, request SHA and staged wrapper SHA may change."""
    require(index.get("schema_version") == original.get("schema_version") == 1 and
            index.get("status") == original.get("status") == "verified" and
            index.get("request_count") == original.get("request_count") == 107,
            "B6d/B6b request index envelope differs")
    added_top = {"source_index", "source_index_sha256", "unit_manifest",
                 "unit_manifest_sha256", "equivalence_gate",
                 "equivalence_gate_sha256"}
    for key in original.keys() - {"requests", "engine", "engine_sha256",
                                  "plan_index", "plan_index_sha256"}:
        require(index.get(key) == original[key],
                f"B6d changed frozen index field: {key}")
    require(set(index) == set(original) | added_top,
            "B6d index has unexpected metadata fields")
    require(index.get("source_index") == str(SOURCE_INDEX) and
            index.get("source_index_sha256") == runner.sha256(SOURCE_INDEX) and
            index.get("unit_manifest") == str(MANIFEST) and
            index.get("unit_manifest_sha256") == runner.sha256(MANIFEST),
            "B6d source index or unit manifest binding differs")
    plan_path = Path(index.get("plan_index", ""))
    require(plan_path.is_absolute() and plan_path.is_file() and
            plan_path.is_relative_to(OUT) and
            runner.sha256(plan_path) == index.get("plan_index_sha256"),
            "B6d new plan index is missing or changed")
    old_rows, new_rows = original.get("requests"), index.get("requests")
    require(isinstance(old_rows, list) and isinstance(new_rows, list) and
            len(old_rows) == len(new_rows) == 107,
            "B6d index does not retain 107 rows")
    new_row_fields = {"original_request", "original_request_sha256",
                      "original_component_wrapper_sha256",
                      "original_library_paths", "base_input_sha256"}
    changed_row_fields = {"request", "request_sha256", "component_wrapper_sha256"}
    changed_request_fields = {"source_root", "entrypoint", "component_wrapper",
                              "library_paths"}
    base = read_object(Path(index["base_index"]))
    for position, (old_row, new_row) in enumerate(zip(old_rows, new_rows)):
        require(set(new_row) == set(old_row) | new_row_fields,
                f"B6d row has unexpected fields at {position}")
        require(all(new_row[key] == old_row[key]
                    for key in old_row.keys() - changed_row_fields) and
                new_row.get("original_component_wrapper_sha256") ==
                old_row.get("component_wrapper_sha256") and
                new_row.get("original_request") == old_row.get("request") and
                new_row.get("original_request_sha256") ==
                old_row.get("request_sha256") and
                new_row.get("base_input_sha256") ==
                base.get("revisions", {}).get(old_row["revision_id"], {}).get(
                    "base_input_sha256"),
                f"B6d row changed frozen binding at {position}")
        old_request = read_object(Path(old_row["request"]))
        new_request = read_object(Path(new_row["request"]))
        require(set(new_request) == set(old_request) and
                all(new_request[key] == old_request[key]
                    for key in old_request.keys() - changed_request_fields) and
                new_row.get("original_library_paths") == old_request.get("library_paths"),
                f"B6d request changed ID, candidate, input or schema at {position}")


def verify_static_preflight(path: Path, expected_sha: str,
                            index_path: Path, index_sha: str) -> None:
    report = _gate_input(path, expected_sha, "B6d static preflight")
    require(report.get("kind") == "n6_b6b_static_hint_copy_preflight" and
            report.get("index_path") == str(index_path) and
            report.get("index_sha256") == index_sha and
            report.get("request_count") == 107 and
            report.get("source_root_count") == 17 and
            report.get("all_passed") is True and
            len(report.get("row_checks", [])) == 107,
            "B6d static preflight does not cover this index")
    for engine in ("v1", "v2.2"):
        item = report.get("per_engine", {}).get(engine, {})
        require(item.get("passed") == 107 and item.get("failed") == 0,
                f"B6d {engine} static preflight incomplete")


def configure(engine: str, index_path: Path, index_sha: str,
              static_path: Path, static_sha: str,
              first_lead_sha: str, second_lead_sha: str) -> dict[str, Any]:
    """Validate all non-verdict inputs before creating any J output."""
    require(engine in {"v1", "v2.2"}, "B6d engine selection invalid")
    require(index_path.is_absolute() and index_path.parent == OUT and
            index_path.name == f"request-index-{engine}.json",
            "B6d J index is outside the new output folder")
    verify_mem20()
    runner.checked_sha(b6.LEAD, first_lead_sha, "first lead-input-review.json")
    runner.checked_sha(b6.LEAD2, second_lead_sha, "second lead-input-review.json")
    runner.ENGINE = ENGINE_V1 if engine == "v1" else ENGINE_V22
    runner.ENGINE_SHA256 = ENGINE_V1_SHA if engine == "v1" else ENGINE_V22_SHA
    runner.preflight_libraries = selection.preflight_libraries
    runner.checked_sha(index_path, index_sha, "B6d request index")
    index_metadata = read_object(index_path)
    evidence = verify_equivalence_gate(index_metadata)
    source_bindings.install(STAGING, MANIFEST,
                            evidence["gate"]["unit_manifest_sha256"])
    index = runner.validate_index(index_path, index_sha)
    verify_original_index(index, evidence["source"])
    verify_static_preflight(static_path, static_sha, index_path, index_sha)
    base = b6.base_index()
    b6.results_review_gate(base, index)
    return index


def classify_preparation(result: Any, row: dict[str, Any],
                         metrics: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """Read only identity and preparation metadata, never a verdict value."""
    require(isinstance(result, dict) and
            result.get("schema") == "zkfdo-lifting-result-v1" and
            result.get("request_sha256") == row["request_sha256"] and
            result.get("candidate_sha256") == row["candidate_sha256"],
            "B6d engine result identity mismatch")
    require(type(metrics.get("max_rss_bytes")) is int and
            metrics["max_rss_bytes"] > 0,
            "B6d engine result RSS missing")
    preparation = result.get("preparation")
    require(isinstance(preparation, dict), "B6d preparation metadata missing")
    status = preparation.get("status")
    if status == "ok":
        issue = runner.successful_result_issue(row, metrics, result)
        require(issue is None, f"B6d completed result invalid: {issue}")
        return "completed", None, None
    reason, detail = preparation.get("reason"), preparation.get("detail")
    require(status in {"preparation_failure", "unknown"} and
            isinstance(reason, str) and reason and
            isinstance(detail, str) and detail and
            reason in ENGINE_PREPARATION_REASONS,
            "B6d unknown or malformed preparation failure")
    expected_status = ("unknown" if reason in {
        "candidate_violates_component_constraints", "deviation_not_hint_assigned"
    } else "preparation_failure")
    require(status == expected_status,
            "B6d preparation status/reason pairing invalid")
    return status, reason, detail


def _prior_zero_exit(row: dict[str, Any], request_dir: Path) -> tuple[Path, int,
                                                                       dict[str, Any],
                                                                       tuple[str, str | None,
                                                                             str | None]] | None:
    """Recover one completed engine result without opening verdict fields."""
    found = []
    for attempt_dir in sorted(request_dir.glob("attempt-*")):
        if not attempt_dir.is_dir() or not attempt_dir.name.startswith("attempt-"):
            continue
        suffix = attempt_dir.name.removeprefix("attempt-")
        require(len(suffix) == 4 and suffix.isdigit(),
                f"B6d attempt directory name invalid: {attempt_dir}")
        number = int(suffix)
        metrics_path = request_dir / f"attempt-{number:04d}.metrics.json"
        if not metrics_path.is_file():
            continue
        metrics = read_object(metrics_path)
        if metrics.get("exit_code") != 0:
            continue
        result_path = attempt_dir / "result.json"
        require(result_path.is_file(), "B6d zero-exit prior result missing")
        classification = classify_preparation(read_object(result_path), row, metrics)
        found.append((result_path, number, metrics, classification))
    require(len(found) <= 1, f"B6d multiple zero-exit results: {request_dir}")
    return found[0] if found else None


def _record_result(row: dict[str, Any], scope: str, revision_id: str,
                   result_path: Path, attempt: int, metrics: dict[str, Any],
                   classification: tuple[str, str | None, str | None],
                   *, resumed: bool = False) -> dict[str, Any]:
    status, reason, detail = classification
    common = {"queue_order": row["queue_order"], "scope": scope,
              "revision_id": revision_id, "request": row["request"],
              "request_sha256": row["request_sha256"], "attempt": attempt,
              "resumed_result": resumed, "exit_code": metrics["exit_code"],
              "wall_seconds": metrics["wall_seconds"],
              "max_rss_bytes": metrics["max_rss_bytes"]}
    if status == "ok" or status == "completed":
        return {**common, "status": "completed", "preparation_failure": None,
                "result_path": str(result_path),
                "result_sha256": runner.sha256(result_path)}
    return {**common, "status": "preparation_failure",
            "preparation_failure": reason,
            "preparation_status": status, "preparation_detail": detail,
            "result_path": None, "result_sha256": None,
            "preparation_artifact_path": str(result_path),
            "preparation_artifact_sha256": runner.sha256(result_path)}


def _check_resume(previous: dict[str, Any] | None,
                  event: dict[str, Any], order: int) -> None:
    if previous is None:
        return
    require(previous.get("status") == event["status"] and
            previous.get("request_sha256") == event["request_sha256"],
            f"B6d prior request state differs at {order}")
    for field in ("result_path", "result_sha256", "preparation_failure",
                  "preparation_artifact_path", "preparation_artifact_sha256"):
        require(previous.get(field) == event.get(field),
                f"B6d prior {field} differs at {order}")


def verify_both_pilots() -> None:
    """Full J requires both completed B6d format pilots, using state only."""
    selection_path = OUT / "pilot-selection.json"
    require(selection_path.is_file(), "B6d pilot selection missing")
    selection_sha = runner.sha256(selection_path)
    indices: dict[str, dict[str, Any]] = {}
    for engine, engine_sha in (("v1", ENGINE_V1_SHA),
                               ("v2.2", ENGINE_V22_SHA)):
        index_path = OUT / f"request-index-{engine}.json"
        require(index_path.is_file(), f"B6d {engine} index missing")
        indices[engine] = read_object(index_path)
        state_path = OUT / f"pilot-{engine}.noindex" / "state.json"
        require(state_path.is_file(), f"B6d {engine} pilot state missing")
        state = read_object(state_path)
        requests = state.get("requests")
        revisions = state.get("revisions")
        require(state.get("schema_version") == 1 and
                state.get("kind") == "n6_b5_format_only_pilot_state" and
                state.get("status") == "passed" and
                state.get("request_index_sha256") == runner.sha256(index_path) and
                state.get("base_index_sha256") == runner.sha256(b6.BASE) and
                state.get("selection_sha256") == selection_sha and
                state.get("engine_sha256") == engine_sha and
                state.get("measurement_method") == "wait4" and
                isinstance(requests, dict) and set(requests) == {"9", "25"} and
                all(isinstance(item, dict) and item.get("status") == "completed" and
                    item.get("format_ok") is True and item.get("exit_code") == 0 and
                    isinstance(item.get("result_sha256"), str)
                    for item in requests.values()) and
                isinstance(revisions, dict) and len(revisions) == 2 and
                all(isinstance(item, dict) and item.get("status") == "joined" and
                    item.get("format_ok") is True and item.get("exit_code") == 0 and
                    isinstance(item.get("instances_sha256"), str)
                    for item in revisions.values()),
                f"B6d {engine} format pilot incomplete")
    require(indices["v2.2"] == {**indices["v1"], "engine": str(ENGINE_V22),
                                   "engine_sha256": ENGINE_V22_SHA},
            "B6d v2.2 index differs from v1 beyond the fixed engine")


def execute(index_path: Path, index_sha: str, cache_root: Path,
            output: Path) -> dict[str, Any]:
    """Execute only after configure() has passed every input and evidence gate."""
    require(cache_root.is_absolute() and cache_root == CACHE / f"full-{_engine_label()}" and
            output.is_absolute() and output == OUT / f"full-{_engine_label()}.noindex",
            "B6d full J paths are not the prepared new paths")
    verify_both_pilots()
    if output.exists():
        require(output.is_dir() and (output / "state.json").is_file(),
                "B6d existing full J output has no resumable state")
    external_paths.EXTERNAL = EXTERNAL
    external_paths.require_external_root(WORKSPACES)
    external_paths.require_external_root(STORES)
    external_paths.require_external_root(CACHE)
    external_paths.require_external_root(cache_root)
    output.mkdir(parents=True, exist_ok=True)
    external_paths.install_full(output, WORKSPACES, STORES)
    index = runner.validate_index(index_path, index_sha)
    state = runner.load_state(output, index_sha, cache_root)
    probe = runner.probe_time_l()
    state["status"] = "running"
    state["measurement_method"] = probe["measurement_method"]
    state["time_probe"] = probe
    state_path = output / "state.json"
    attempts_path = output / "attempts.jsonl"
    runner.atomic_json(state_path, state)
    for scope, ordinal, revision_id, rows in runner.groups(index["requests"]):
        revision_key = f"{scope}/{ordinal:04d}"
        revision_dir = output / scope / f"{ordinal:04d}"
        revision_dir.mkdir(parents=True, exist_ok=True)
        revision_state = state["revisions"].setdefault(revision_key, {
            "scope": scope, "revision_ordinal": ordinal, "revision_id": revision_id,
            "status": "running", "instance_store": str(revision_dir / "store"),
            "cache_path": str(cache_root / scope / f"{ordinal:04d}")})
        require(revision_state.get("revision_id") == revision_id and
                revision_state.get("cache_path") ==
                str(cache_root / scope / f"{ordinal:04d}"),
                "B6d revision state lock differs")
        runner.atomic_json(state_path, state)
        result_paths: list[Path] = []
        for row in rows:
            order = row["queue_order"]
            request_dir = revision_dir / "requests" / f"{order:06d}"
            previous = state["requests"].get(str(order))
            if previous is not None:
                require(previous.get("request_sha256") == row["request_sha256"],
                        f"B6d request state SHA mismatch at {order}")
            if row["preparation_failure"] is not None:
                event = {"status": "preparation_failure", "queue_order": order,
                         "scope": scope, "revision_id": revision_id,
                         "request": row["request"],
                         "request_sha256": row["request_sha256"],
                         "preparation_failure": row["preparation_failure"],
                         "result_path": None, "result_sha256": None,
                         "exit_code": None, "wall_seconds": None,
                         "max_rss_bytes": None}
                _check_resume(previous, event, order)
                if previous is None:
                    state["requests"][str(order)] = event
                    runner.append_jsonl(attempts_path, event)
                    runner.atomic_json(state_path, state)
                continue
            prior = _prior_zero_exit(row, request_dir)
            free: dict[str, int] | None = None
            if prior is None:
                require(previous is None or previous.get("status") not in
                        {"completed", "preparation_failure"},
                        f"B6d completed request artifact missing at {order}")
                request = read_object(Path(row["request"]))
                runner.checked_request_sources(row, request, order)
                try:
                    free = runner.check_disk(output, cache_root)
                    runner.check_disk(WORKSPACES, STORES)
                except runner.DiskGuardStop as error:
                    state["status"] = "disk_guard_stopped"
                    state["stop_reason"] = str(error)
                    state["next_queue_order"] = order
                    runner.atomic_json(state_path, state)
                    raise
                cache = initialize_cache(cache_root, scope, ordinal,
                                         revision_id, index_sha)
                attempt = runner.next_attempt(request_dir)
                result_dir = request_dir / f"attempt-{attempt:04d}"
                metrics = runner.run_lift(row, result_dir, cache,
                                          revision_dir / "store", attempt,
                                          probe["measurement_method"])
                runner.atomic_json(request_dir / f"attempt-{attempt:04d}.metrics.json",
                                   metrics)
                result_path = result_dir / "result.json"
                if metrics.get("exit_code") != 0 or not result_path.is_file():
                    state["status"] = "engine_failed"
                    state["stop_reason"] = f"B6d lift exit/result failure at {order}"
                    state["next_queue_order"] = order
                    runner.atomic_json(state_path, state)
                    raise runner.RunnerError(state["stop_reason"])
                try:
                    classification = classify_preparation(read_object(result_path), row,
                                                          metrics)
                except (OSError, ValueError, runner.RunnerError) as error:
                    state["status"] = "result_invalid"
                    state["stop_reason"] = f"B6d invalid result at {order}: {error}"
                    state["next_queue_order"] = order
                    runner.atomic_json(state_path, state)
                    raise
            else:
                result_path, attempt, metrics, classification = prior
            status, reason, _detail = classification
            if status != "completed" and reason in ENVIRONMENT_REASONS:
                state["status"] = "environment_preparation_failure"
                state["stop_reason"] = f"B6d environment preparation failure: {reason} at {order}"
                state["next_queue_order"] = order
                runner.atomic_json(state_path, state)
                raise runner.RunnerError(state["stop_reason"])
            event = _record_result(row, scope, revision_id, result_path, attempt,
                                   metrics, classification, resumed=prior is not None)
            _check_resume(previous, event, order)
            if previous is None:
                if free is not None:
                    event["disk_before"] = free
                state["requests"][str(order)] = event
                runner.append_jsonl(attempts_path, event)
                runner.atomic_json(state_path, state)
            if event["status"] == "completed":
                result_paths.append(result_path)
        instance_path = revision_dir / "instances.json"
        if result_paths:
            if instance_path.exists():
                instance = read_object(instance_path)
                require(instance.get("schema") == "zkfdo-instance-verdicts-v1" and
                        instance.get("results") ==
                        [str(path.relative_to(output)) for path in result_paths] and
                        instance.get("conflicts") == 0,
                        "B6d existing instance join differs")
            else:
                working = revision_dir / "instances-attempt-0001.json"
                require(not working.exists(), "B6d prior instance join artifact exists")
                metrics = runner.join_instances(result_paths, output, working,
                                                probe["measurement_method"])
                runner.atomic_json(revision_dir / "instances-attempt-0001.metrics.json",
                                   metrics)
                runner.append_jsonl(attempts_path, {"kind": "lift-instances",
                                                     "scope": scope,
                                                     "revision_id": revision_id,
                                                     "revision_ordinal": ordinal,
                                                     "output": str(working), **metrics})
                require(metrics.get("exit_code") == 0 and working.is_file(),
                        "B6d instance join failed")
                instance = read_object(working)
                require(instance.get("schema") == "zkfdo-instance-verdicts-v1" and
                        instance.get("results") ==
                        [str(path.relative_to(output)) for path in result_paths] and
                        instance.get("conflicts") == 0,
                        "B6d instance join output invalid")
                working.replace(instance_path)
            revision_state.update({"status": "joined", "instances_path": str(instance_path),
                                   "instances_sha256": runner.sha256(instance_path),
                                   "result_count": len(result_paths)})
        else:
            revision_state.update({"status": "no_results", "instances_path": None,
                                   "instances_sha256": None, "result_count": 0})
        runner.atomic_json(state_path, state)
    require(len(state["requests"]) == 107, "B6d run did not cover all 107 requests")
    state["status"] = "completed"
    state["completed_at"] = datetime.now(timezone.utc).isoformat()
    state.pop("stop_reason", None)
    state.pop("next_queue_order", None)
    runner.atomic_json(state_path, state)
    return state


def _engine_label() -> str:
    return "v1" if runner.ENGINE_SHA256 == ENGINE_V1_SHA else "v2.2"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("v1", "v2.2"), required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--static-preflight", type=Path, required=True)
    parser.add_argument("--static-preflight-sha256", required=True)
    parser.add_argument("--first-lead-review-sha256", required=True)
    parser.add_argument("--second-lead-review-sha256", required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--action", choices=("validate-only", "execute-all"),
                        default="validate-only")
    args = parser.parse_args(argv)
    try:
        index = configure(args.engine, args.index, args.index_sha256,
                          args.static_preflight, args.static_preflight_sha256,
                          args.first_lead_review_sha256,
                          args.second_lead_review_sha256)
        if args.action == "validate-only":
            print(json.dumps({"status": "valid", "request_count": 107,
                              "index_sha256": args.index_sha256}, sort_keys=True))
            return 0
        state = execute(args.index, args.index_sha256,
                        args.cache_root, args.output)
        print(json.dumps({"status": state["status"],
                          "request_count": len(state["requests"]),
                          "output": str(args.output)}, sort_keys=True))
        return 0
    except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError) as error:
        print(f"B6d J runner refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
