#!/usr/bin/env python3
"""Validate and run the B6h 107-request J index.

This version keeps the locked engines and J verdict logic. Source-backed
method limits pass the format gate. Nonenvironment format failures occupy a
request slot and stop the run at five; environmental failures stop immediately.
A smoke requests may be executed here; B J remains miiz-run.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

import n6_b6_batch1x_prepare as b6
import n6_b6h_runtime_paths as external_paths
import n6_b6h_cleanup as cleanup
import n6_b6d_source_bindings as source_bindings
import n6_b6f_format_pilot as format_gate
import n6_j3_b_pilot_wait4 as selection
import run_n6_j1 as runner
from n6_b5_j_adapter import (ENGINE_V1, ENGINE_V1_SHA, ENGINE_V22,
                             ENGINE_V22_SHA, verify_mem20)
from n6_j1_cache_cleanup import initialize_cache


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/n6-b6e-2026-10-20.noindex"
RUN_OUT = ROOT / "runs/n6-b6g-2026-10-23.noindex"
RECORD_OUT = ROOT / "runs/n6-b6h-2026-10-24.noindex/cleanup-records"
PILOT_OUT = ROOT / "runs/n6-b6f-2026-10-20.noindex"
EXTERNAL = Path("/Volumes/zkfdo-jcache/n6-b6g-batch1x")
STAGING = Path("/Volumes/zkfdo-jcache/n6-b6d-batch1x/units")
WORKSPACES = EXTERNAL / "hint-workspaces"
STORES = EXTERNAL / "instance-stores"
CACHE = EXTERNAL / "cache"
OBSERVED_REQUEST_PEAK_BYTES = 280 * 1024**3
OTHER_ENGINE_CACHE_GROWTH_BYTES = 177 * 1024**3
SOURCE_INDEX = ROOT / "runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-v1.json"
B6D_OUT = ROOT / "runs/n6-b6d-2026-10-20.noindex"
MANIFEST = B6D_OUT / "unit-staging-manifest.json"
B_AUDIT = B6D_OUT / "b-closure-equivalence-v1.json"
A_AUDIT = B6D_OUT / "a-closure-audit-v2.json"
R1CS_AUDIT = B6D_OUT / "r1cs-equivalence.json"
E2_AUDIT = OUT / "e2-equivalence-v2.json"
GATE = OUT / "equivalence-gate-v2.json"

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
RESOURCE_DETAIL = re.compile(
    r"\b(?:ENOSPC|ENOMEM|EMFILE|EDQUOT|disk full|no space left on device|"
    r"out of memory|cannot allocate memory|allocation failed|memory allocation failed|"
    r"too many open files|quota exceeded|resource temporarily unavailable)\b",
    re.IGNORECASE,
)


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


def original_duplicate_orders(audit: dict[str, Any]) -> set[int]:
    """Bind the non-engine index annotation to all 17 reviewed pairs."""
    b = audit.get("b")
    a = audit.get("a")
    require(audit.get("schema_version") == 2 and audit.get("status") == "pass" and
            isinstance(b, dict) and isinstance(a, dict) and
            b.get("status") == a.get("status") == "pass" and
            b.get("request_count") == 107 and b.get("pair_count") == 17 and
            b.get("original_duplicate_request_count") == 9 and
            a.get("request_count") == 2926 and a.get("revision_count") == 26,
            "B6e E2 audit envelope differs")
    pairs = b.get("pairs")
    require(isinstance(pairs, list) and len(pairs) == 17,
            "B6e E2 audit does not cover 17 pairs")
    all_orders: set[int] = set()
    duplicate_orders: set[int] = set()
    pair_ids: set[str] = set()
    for pair in pairs:
        require(isinstance(pair, dict) and
                isinstance(pair.get("pair_id"), str) and pair["pair_id"] and
                pair["pair_id"] not in pair_ids and
                type(pair.get("original_duplicate")) is bool and
                isinstance(pair.get("queue_orders"), list) and
                pair["queue_orders"],
                "B6e E2 audit pair is malformed")
        pair_ids.add(pair["pair_id"])
        orders = pair["queue_orders"]
        require(all(type(order) is int and 0 <= order < 107 and
                    order not in all_orders for order in orders),
                "B6e E2 audit queue mapping is malformed")
        all_orders.update(orders)
        if pair["original_duplicate"]:
            duplicate_orders.update(orders)
    require(all_orders == set(range(107)) and
            duplicate_orders == set(range(9)),
            "B6e E2 original duplicate requests differ")
    return duplicate_orders


def verify_equivalence_gate(index: dict[str, Any]) -> dict[str, Any]:
    """Require the revised E2 gate and exact B6d E1/E3/E4 evidence."""
    require(index.get("equivalence_gate") == str(GATE) and
            isinstance(index.get("equivalence_gate_sha256"), str),
            "B6e index does not pin the revised E1–E4 gate")
    gate = _gate_input(GATE, index["equivalence_gate_sha256"], "B6e E1–E4 gate")
    require(gate.get("schema_version") == 2 and gate.get("status") == "passed" and
            gate.get("request_count") == 107 and gate.get("pair_count") == 17 and
            all(gate.get(key) == "passed" for key in ("e1", "e2", "e3", "e4")),
            "B6e E1–E4 gate is not fully passed")
    source = _gate_input(SOURCE_INDEX, gate.get("source_index_sha256"),
                         "B6b source request index")
    manifest = _gate_input(MANIFEST, gate.get("unit_manifest_sha256"),
                           "B6e unit manifest")
    b_audit = _gate_input(B_AUDIT, gate.get("b_closure_audit_sha256"),
                          "B6e B closure audit")
    a_audit = _gate_input(A_AUDIT, gate.get("a_closure_audit_sha256"),
                          "B6e A closure audit")
    r1cs = _gate_input(R1CS_AUDIT, gate.get("r1cs_equivalence_sha256"),
                       "B6e R1CS equivalence")
    e2_audit = _gate_input(E2_AUDIT, gate.get("e2_audit_sha256"),
                           "B6e revised E2 audit")
    duplicate_orders = original_duplicate_orders(e2_audit)
    staged_pairs = {pair["pair_id"]: pair["queue_orders"]
                    for pair in manifest.get("pairs", [])}
    require(len(staged_pairs) == 17 and all(
        staged_pairs.get(pair["pair_id"]) == pair["queue_orders"]
        for pair in e2_audit["b"]["pairs"]),
        "B6e E2 audit pair mapping differs from adopted units")
    require(source.get("request_count") == 107 and
            manifest.get("source_index_sha256") ==
            gate.get("source_index_sha256") and
            manifest.get("schema") == source_bindings.EXPECTED_SCHEMA and
            manifest.get("request_count") == 107 and
            manifest.get("pair_count") == 17 and
            b_audit.get("b", {}).get("e1", {}).get("status") == "pass" and
            b_audit.get("b", {}).get("request_count") == 107 and
            b_audit.get("b", {}).get("pair_count") == 17 and
            a_audit.get("a", {}).get("status") == "pass" and
            a_audit.get("a", {}).get("request_count") == 2926 and
            r1cs.get("e3_passed") is True and r1cs.get("e4_passed") is True and
            len(r1cs.get("pairs", [])) == 17,
            "B6e E1–E4 evidence does not support the gate")
    return {"gate": gate, "source": source, "manifest": manifest,
            "original_duplicate_orders": duplicate_orders}


def verify_original_index(index: dict[str, Any], original: dict[str, Any],
                          duplicate_orders: set[int]) -> None:
    """Only path, ordered -l, request SHA and staged wrapper SHA may change."""
    require(index.get("schema_version") == original.get("schema_version") == 1 and
            index.get("status") == original.get("status") == "verified" and
            index.get("request_count") == original.get("request_count") == 107,
            "B6e/B6b request index envelope differs")
    added_top = {"source_index", "source_index_sha256", "unit_manifest",
                 "unit_manifest_sha256", "equivalence_gate",
                 "equivalence_gate_sha256"}
    for key in original.keys() - {"requests", "engine", "engine_sha256",
                                  "plan_index", "plan_index_sha256"}:
        require(index.get(key) == original[key],
                f"B6e changed frozen index field: {key}")
    require(set(index) == set(original) | added_top,
            "B6e index has unexpected metadata fields")
    require(index.get("source_index") == str(SOURCE_INDEX) and
            index.get("source_index_sha256") == runner.sha256(SOURCE_INDEX) and
            index.get("unit_manifest") == str(MANIFEST) and
            index.get("unit_manifest_sha256") == runner.sha256(MANIFEST),
            "B6e source index or unit manifest binding differs")
    plan_path = Path(index.get("plan_index", ""))
    require(plan_path.is_absolute() and plan_path.is_file() and
            plan_path.is_relative_to(OUT) and
            runner.sha256(plan_path) == index.get("plan_index_sha256"),
            "B6e new plan index is missing or changed")
    old_rows, new_rows = original.get("requests"), index.get("requests")
    require(isinstance(old_rows, list) and isinstance(new_rows, list) and
            len(old_rows) == len(new_rows) == 107,
            "B6e index does not retain 107 rows")
    new_row_fields = {"original_request", "original_request_sha256",
                      "original_component_wrapper_sha256",
                      "original_library_paths", "base_input_sha256",
                      "original_template_duplicate"}
    changed_row_fields = {"request", "request_sha256", "component_wrapper_sha256"}
    changed_request_fields = {"source_root", "entrypoint", "component_wrapper",
                              "library_paths"}
    base = read_object(Path(index["base_index"]))
    for position, (old_row, new_row) in enumerate(zip(old_rows, new_rows)):
        require(set(new_row) == set(old_row) | new_row_fields,
                f"B6e row has unexpected fields at {position}")
        require(type(new_row.get("original_template_duplicate")) is bool and
                new_row["original_template_duplicate"] ==
                (position in duplicate_orders),
                f"B6e original duplicate annotation differs at {position}")
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
                f"B6e row changed frozen binding at {position}")
        old_request = read_object(Path(old_row["request"]))
        new_request = read_object(Path(new_row["request"]))
        require(set(new_request) == set(old_request) and
                all(new_request[key] == old_request[key]
                    for key in old_request.keys() - changed_request_fields) and
                new_row.get("original_library_paths") == old_request.get("library_paths"),
                f"B6e request changed ID, candidate, input or schema at {position}")


def verify_static_preflight(path: Path, expected_sha: str,
                            index_path: Path, index_sha: str) -> None:
    report = _gate_input(path, expected_sha, "B6e static preflight")
    require(report.get("kind") == "n6_b6b_static_hint_copy_preflight" and
            report.get("index_path") == str(index_path) and
            report.get("index_sha256") == index_sha and
            report.get("request_count") == 107 and
            report.get("source_root_count") == 17 and
            report.get("limits") == {"circom_bytes": 100_663_296,
                                     "circom_files": 2_000,
                                     "walk_directories": 20_000,
                                     "walk_entries": 250_000} and
            report.get("all_passed") is True and
            len(report.get("row_checks", [])) == 107,
            "B6e static preflight does not cover this index")
    for engine in ("v1", "v2.2"):
        item = report.get("per_engine", {}).get(engine, {})
        require(item.get("passed") == 107 and item.get("failed") == 0,
                f"B6e {engine} static preflight incomplete")


def configure(engine: str, index_path: Path, index_sha: str,
              static_path: Path, static_sha: str,
              first_lead_sha: str, second_lead_sha: str) -> dict[str, Any]:
    """Validate all non-verdict inputs before creating any J output."""
    require(engine in {"v1", "v2.2"}, "B6e engine selection invalid")
    require(index_path.is_absolute() and index_path.parent == OUT and
            index_path.name == f"request-index-{engine}.json",
            "B6e J index is outside the new output folder")
    verify_mem20()
    runner.checked_sha(b6.LEAD, first_lead_sha, "first lead-input-review.json")
    runner.checked_sha(b6.LEAD2, second_lead_sha, "second lead-input-review.json")
    runner.ENGINE = ENGINE_V1 if engine == "v1" else ENGINE_V22
    runner.ENGINE_SHA256 = ENGINE_V1_SHA if engine == "v1" else ENGINE_V22_SHA
    runner.preflight_libraries = selection.preflight_libraries
    runner.checked_sha(index_path, index_sha, "B6e request index")
    index_metadata = read_object(index_path)
    evidence = verify_equivalence_gate(index_metadata)
    source_bindings.install(STAGING, MANIFEST,
                            evidence["gate"]["unit_manifest_sha256"])
    index = runner.validate_index(index_path, index_sha)
    verify_original_index(index, evidence["source"],
                          evidence["original_duplicate_orders"])
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
            "B6e engine result identity mismatch")
    require(type(metrics.get("max_rss_bytes")) is int and
            metrics["max_rss_bytes"] > 0,
            "B6e engine result RSS missing")
    preparation = result.get("preparation")
    require(isinstance(preparation, dict), "B6e preparation metadata missing")
    status = preparation.get("status")
    if status == "ok":
        issue = runner.successful_result_issue(row, metrics, result)
        require(issue is None, f"B6e completed result invalid: {issue}")
        return "completed", None, None
    reason, detail = preparation.get("reason"), preparation.get("detail")
    require(status in {"preparation_failure", "unknown"} and
            isinstance(reason, str) and reason and
            isinstance(detail, str) and detail and
            reason in ENGINE_PREPARATION_REASONS,
            "B6e unknown or malformed preparation failure")
    expected_status = ("unknown" if reason in {
        "candidate_violates_component_constraints", "deviation_not_hint_assigned"
    } else "preparation_failure")
    require(status == expected_status,
            "B6e preparation status/reason pairing invalid")
    return status, reason, detail


def inspect_result(result_path: Path, row: dict[str, Any],
                   metrics: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """Classify preparation, then run the same format gate used by the pilot."""
    try:
        result = read_object(result_path)
    except OSError:
        raise
    except (ValueError, runner.RunnerError) as error:
        return "inspection_failure", "result_structure_invalid", str(error)
    try:
        classification = classify_preparation(result, row, metrics)
    except (ValueError, runner.RunnerError) as error:
        return "inspection_failure", "result_structure_invalid", str(error)
    if classification[0] != "completed":
        return classification
    try:
        format_gate.check_result_shape(result_path, row)
    except format_gate.FormatInspectionError as error:
        if error.environment:
            raise
        return "inspection_failure", error.code, str(error)
    except OSError:
        raise
    except (ValueError, runner.RunnerError) as error:
        return "inspection_failure", "format_invalid", str(error)
    return classification


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
                f"B6e attempt directory name invalid: {attempt_dir}")
        number = int(suffix)
        metrics_path = request_dir / f"attempt-{number:04d}.metrics.json"
        if not metrics_path.is_file():
            continue
        metrics = read_object(metrics_path)
        if metrics.get("exit_code") != 0:
            continue
        result_path = attempt_dir / "result.json"
        # A zero-exit process can still leave no published result if the
        # workspace filled during publication. Treat only this unrecorded
        # attempt as unfinished; a recorded completed result is checked below.
        if not result_path.is_file():
            continue
        classification = inspect_result(result_path, row, metrics)
        found.append((result_path, number, metrics, classification))
    require(len(found) <= 1, f"B6e multiple zero-exit results: {request_dir}")
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
    if status == "inspection_failure":
        require(isinstance(reason, str) and reason and
                isinstance(detail, str) and detail,
                "B6f inspection failure metadata missing")
        return {**common, "status": "inspection_failure",
                "preparation_failure": None, "result_path": None,
                "result_sha256": None, "inspection_failure_reason": reason,
                "inspection_failure_detail": detail,
                "inspection_artifact_path": str(result_path),
                "inspection_artifact_sha256": runner.sha256(result_path)}
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
            f"B6e prior request state differs at {order}")
    for field in ("result_path", "result_sha256", "preparation_failure",
                  "preparation_artifact_path", "preparation_artifact_sha256",
                  "inspection_failure_reason", "inspection_failure_detail",
                  "inspection_artifact_path", "inspection_artifact_sha256"):
        require(previous.get(field) == event.get(field),
                f"B6e prior {field} differs at {order}")


V22_RECHECK = PILOT_OUT / "v2-2-pilot-recheck.json"


def _checked_pilot_artifact(path_text: Any, digest: Any, root: Path,
                            label: str) -> None:
    require(isinstance(path_text, str) and isinstance(digest, str) and
            len(digest) == 64, f"{label} path/SHA absent")
    path = Path(path_text)
    require(path.is_absolute() and path.is_file() and not path.is_symlink() and
            path.resolve().is_relative_to(root.resolve()),
            f"{label} missing, linked, or outside pilot")
    runner.checked_sha(path, digest, label)


def verify_both_pilots() -> None:
    """Bind the new v1 pilot and read-only v2.2 result recheck to full J."""
    selection_path = OUT / "pilot-selection.json"
    require(selection_path.is_file(), "B6f pilot selection missing")
    selection_sha = runner.sha256(selection_path)
    v1_index = OUT / "request-index-v1.json"
    v22_index = OUT / "request-index-v2.2.json"
    indices = {"v1": read_object(v1_index), "v2.2": read_object(v22_index)}
    require(indices["v2.2"] == {**indices["v1"], "engine": str(ENGINE_V22),
                                   "engine_sha256": ENGINE_V22_SHA},
            "B6f v2.2 index differs from v1 beyond the fixed engine")

    v1_pilot = PILOT_OUT / "pilot-v1.noindex"
    state = read_object(v1_pilot / "state.json")
    requests = state.get("requests")
    revisions = state.get("revisions")
    require(state.get("schema_version") == 1 and
            state.get("kind") == "n6_b5_format_only_pilot_state" and
            state.get("status") == "passed" and
            state.get("request_index_sha256") == runner.sha256(v1_index) and
            state.get("base_index_sha256") == runner.sha256(b6.BASE) and
            state.get("selection_sha256") == selection_sha and
            state.get("engine_sha256") == ENGINE_V1_SHA and
            state.get("measurement_method") == "wait4" and
            isinstance(requests, dict) and set(requests) == {"9", "25"} and
            isinstance(revisions, dict) and len(revisions) == 2,
            "B6f v1 format pilot incomplete")
    for order, item in requests.items():
        require(isinstance(item, dict) and item.get("status") == "completed" and
                item.get("queue_order") == int(order) and
                item.get("format_ok") is True and item.get("exit_code") == 0,
                f"B6f v1 pilot request {order} invalid")
        _checked_pilot_artifact(item.get("result_path"),
                                item.get("result_sha256"), v1_pilot,
                                f"B6f v1 pilot result {order}")
    for key, item in revisions.items():
        require(isinstance(item, dict) and item.get("status") == "joined" and
                item.get("format_ok") is True and item.get("exit_code") == 0,
                f"B6f v1 pilot revision {key} invalid")
        _checked_pilot_artifact(item.get("instances_path"),
                                item.get("instances_sha256"), v1_pilot,
                                f"B6f v1 pilot instances {key}")

    recheck = read_object(V22_RECHECK)
    old_pilot = OUT / "pilot-v2.2.noindex"
    old_state = old_pilot / "state.json"
    require(recheck.get("schema_version") == 1 and
            recheck.get("kind") == "n6_b6f_v22_pilot_result_recheck" and
            recheck.get("status") == "passed" and
            recheck.get("engine_sha256") == ENGINE_V22_SHA and
            recheck.get("request_index") == str(v22_index) and
            recheck.get("request_index_sha256") == runner.sha256(v22_index) and
            recheck.get("selection_sha256") == selection_sha and
            recheck.get("old_pilot_path") == str(old_pilot) and
            recheck.get("old_pilot_state_sha256") == runner.sha256(old_state) and
            recheck.get("checker_sha256") == runner.sha256(
                ROOT / "scripts/n6_b6f_format_pilot.py") and
            recheck.get("join_rechecked") is False and
            recheck.get("verdict_values_read") is False and
            isinstance(recheck.get("requests"), list) and
            len(recheck["requests"]) == 2,
            "B6f read-only v2.2 recheck differs")
    for ordinal, order in enumerate((9, 25)):
        item = recheck["requests"][ordinal]
        expected_path = old_pilot / "requests" / f"{ordinal:02d}-{order:06d}" / "lift/result.json"
        require(isinstance(item, dict) and item.get("queue_order") == order and
                item.get("status") == "format_passed" and
                item.get("result_path") == str(expected_path) and
                isinstance(item.get("method_errors"), list),
                f"B6f rechecked v2.2 request {order} invalid")
        _checked_pilot_artifact(item.get("result_path"),
                                item.get("result_sha256"), old_pilot,
                                f"B6f rechecked v2.2 result {order}")


def _next_fresh_attempt(request_dir: Path, output: Path,
                        workspace_root: Path) -> int:
    """Keep every artifact from an interrupted attempt and use a new number."""
    attempt = runner.next_attempt(request_dir)
    while attempt <= 9999:
        prefix = request_dir / f"attempt-{attempt:04d}"
        local = (prefix, request_dir / f"attempt-{attempt:04d}.metrics.json")
        external = workspace_root / output.name / prefix.relative_to(output)
        logs = (external.with_suffix(".stdout.log"),
                external.with_suffix(".stderr.log"))
        if not any(path.exists() or path.is_symlink()
                   for path in (*local, external, *logs)):
            return attempt
        attempt += 1
    raise runner.RunnerError("B6g attempt numbers exhausted")


def _next_fresh_join_attempt(revision_dir: Path, output: Path,
                             workspace_root: Path) -> int:
    """Preserve an interrupted instances join and its external logs."""
    for attempt in range(1, 10000):
        working = revision_dir / f"instances-attempt-{attempt:04d}.json"
        metrics = revision_dir / f"instances-attempt-{attempt:04d}.metrics.json"
        external = workspace_root / output.name / working.relative_to(output)
        logs = (external.with_suffix(".stdout.log"),
                external.with_suffix(".stderr.log"))
        if not any(path.exists() or path.is_symlink()
                   for path in (working, metrics, *logs)):
            return attempt
    raise runner.RunnerError("B6g instances attempt numbers exhausted")



def _retained_evidence_du_bytes(state: dict[str, Any]) -> int:
    total = 0
    for event in state.get("requests", {}).values():
        cleanup_record = event.get("workspace_cleanup")
        final = event.get("workspace_cleanup_final")
        if not isinstance(cleanup_record, dict) or \
                cleanup_record.get("status") != "retained_evidence" or \
                (isinstance(final, dict) and final.get("status") in {"deleted", "absent"}):
            continue
        retained = cleanup_record.get("retained_evidence")
        require(isinstance(retained, dict) and
                type(retained.get("du_bytes")) is int and
                retained["du_bytes"] >= 0,
                "B6h retained evidence size missing from state")
        total += retained["du_bytes"]
    return total


def _cleanup_finished_workspace(event: dict[str, Any], request_dir: Path,
                                output: Path, workspace_root: Path,
                                state_path: Path, state: dict[str, Any]) -> None:
    """Remove request bytes, keeping v2.2 store evidence until revision join."""
    attempt = event.get("attempt")
    require(type(attempt) is int and attempt > 0,
            "B6h workspace cleanup requires a recorded attempt")
    artifact = (event.get("result_path") or event.get("preparation_artifact_path")
                or event.get("inspection_artifact_path"))
    artifact_sha = (event.get("result_sha256") or
                    event.get("preparation_artifact_sha256") or
                    event.get("inspection_artifact_sha256"))
    expected = request_dir / f"attempt-{attempt:04d}" / "result.json"
    require(event.get("exit_code") == 0 and artifact == str(expected) and
            isinstance(artifact_sha, str) and len(artifact_sha) == 64 and
            expected.is_file() and runner.sha256(expected) == artifact_sha,
            "B6h workspace cleanup lacks durable result")
    target = workspace_root / output.name / request_dir.relative_to(output)
    final = event.get("workspace_cleanup_final")
    if isinstance(final, dict) and final.get("status") in {"deleted", "absent"}:
        require(not target.exists() and not target.is_symlink(),
                "B6h revision evidence reappeared after final cleanup")
        return
    earlier = event.get("workspace_cleanup")
    if isinstance(earlier, dict):
        if earlier.get("status") in {"deleted", "absent"}:
            require(not target.exists() and not target.is_symlink(),
                    "B6h cleaned workspace reappeared")
            return
        if earlier.get("status") == "retained_evidence":
            if not target.exists() and not target.is_symlink():
                revision_key = f"{event['scope']}/{request_dir.parents[1].name}"
                revision = state.get("revisions", {}).get(revision_key, {})
                require(revision.get("status") in {"joined", "no_results"},
                        "B6h retained evidence vanished before revision join")
                # The final revision cleanup may have finished immediately
                # before a crash, without its state update.
                return
            cleanup.verify_retained_workspace(
                workspace_root, target, earlier.get("retained_evidence"))
            return
    result = cleanup.cleanup_request_workspace(
        workspace_root, target, RECORD_OUT,
        {"queue_order": event["queue_order"], "attempt": attempt,
         "revision_id": event["revision_id"], "result_sha256": artifact_sha},
        preserve_v22_evidence=_engine_label() == "v2.2")
    event["workspace_cleanup"] = result
    runner.atomic_json(state_path, state)


def _cleanup_finished_revision(revision_state: dict[str, Any], cache_root: Path,
                               instance_root: Path, workspace_root: Path,
                               output: Path, scope: str, ordinal: int,
                               rows: list[dict[str, Any]], state_path: Path,
                               state: dict[str, Any]) -> None:
    """Remove retained evidence and revision cache/store after durable join."""
    require(revision_state.get("status") in {"joined", "no_results"},
            "B6h revision cleanup precedes join state")
    for row in rows:
        event = state["requests"].get(str(row["queue_order"]))
        require(isinstance(event, dict), "B6h revision cleanup lacks request state")
        record = event.get("workspace_cleanup")
        if not isinstance(record, dict) or record.get("status") != "retained_evidence":
            continue
        request_dir = output / scope / f"{ordinal:04d}" / "requests" / f"{row['queue_order']:06d}"
        target = workspace_root / output.name / request_dir.relative_to(output)
        previous = event.get("workspace_cleanup_final")
        if isinstance(previous, dict) and previous.get("status") in {"deleted", "absent"}:
            require(not target.exists() and not target.is_symlink(),
                    "B6h cleaned revision evidence reappeared")
            continue
        if target.exists() or target.is_symlink():
            cleanup.verify_retained_workspace(
                workspace_root, target, record.get("retained_evidence"))
        result = cleanup.cleanup_tree(
            workspace_root, target, RECORD_OUT, "revision_evidence",
            {"queue_order": row["queue_order"],
             "revision_id": revision_state["revision_id"],
             "instances_sha256": revision_state.get("instances_sha256")})
        event["workspace_cleanup_final"] = result
        runner.atomic_json(state_path, state)
    targets = (
        ("cache_cleanup", "revision_cache", cache_root,
         cache_root / scope / f"{ordinal:04d}"),
        ("store_cleanup", "revision_store", instance_root,
         instance_root / output.name / scope / f"{ordinal:04d}" / "store"),
    )
    for key, category, root, target in targets:
        prior = revision_state.get(key)
        if isinstance(prior, dict) and prior.get("status") == "deleted":
            require(not target.exists() and not target.is_symlink(),
                    f"B6h cleaned {category} reappeared")
            continue
        result = cleanup.cleanup_tree(
            root, target, RECORD_OUT, category,
            {"scope": scope, "revision_ordinal": ordinal,
             "revision_id": revision_state["revision_id"],
             "instances_sha256": revision_state.get("instances_sha256")})
        revision_state[key] = result
        runner.atomic_json(state_path, state)


def reconcile_cleanup(index_path: Path, index_sha: str, cache_root: Path,
                      output: Path, workspace_root: Path,
                      instance_root: Path) -> dict[str, Any]:
    """Repair recorded external cleanup without starting either J engine step."""
    require(cache_root.is_absolute() and cache_root == CACHE / f"full-{_engine_label()}" and
            output.is_absolute() and output == RUN_OUT / f"full-{_engine_label()}.noindex" and
            workspace_root.is_absolute() and workspace_root == WORKSPACES and
            instance_root.is_absolute() and instance_root == STORES,
            "B6h reconcile paths differ from the locked J paths")
    if not output.exists():
        return {"status": "no_state", "request_cleanup_checked": 0,
                "revision_cleanup_checked": 0}
    require((output / "state.json").is_file(),
            "B6h existing output has no resumable state")
    external_paths.EXTERNAL = EXTERNAL
    for external in (workspace_root, instance_root, CACHE, cache_root):
        external_paths.require_external_root(external)
    index = runner.validate_index(index_path, index_sha)
    state = runner.load_state(output, index_sha, cache_root)
    state_path = output / "state.json"
    terminal = {"completed", "preparation_failure", "inspection_failure"}
    request_count = revision_count = 0
    for scope, ordinal, revision_id, rows in runner.groups(index["requests"]):
        revision_key = f"{scope}/{ordinal:04d}"
        revision = state["revisions"].get(revision_key)
        for row in rows:
            event = state["requests"].get(str(row["queue_order"]))
            if event is None:
                continue
            require(event.get("request_sha256") == row["request_sha256"] and
                    event.get("revision_id") == revision_id and
                    event.get("status") in terminal,
                    "B6h reconcile request state differs from index")
            if type(event.get("attempt")) is not int:
                require(row.get("preparation_failure") is not None and
                        event.get("status") == "preparation_failure",
                        "B6h reconcile missing completed attempt")
                continue
            request_dir = output / scope / f"{ordinal:04d}" / "requests" / \
                f"{row['queue_order']:06d}"
            _cleanup_finished_workspace(event, request_dir, output,
                                        workspace_root, state_path, state)
            request_count += 1
        if revision is None or revision.get("status") not in {"joined", "no_results"}:
            continue
        if not all(str(row["queue_order"]) in state["requests"] for row in rows):
            continue
        if revision.get("status") == "joined":
            path_text = revision.get("instances_path")
            digest = revision.get("instances_sha256")
            require(isinstance(path_text, str) and isinstance(digest, str) and
                    len(digest) == 64 and Path(path_text).is_file() and
                    runner.sha256(Path(path_text)) == digest,
                    "B6h reconcile joined instances SHA differs")
        _cleanup_finished_revision(revision, cache_root, instance_root,
                                   workspace_root, output, scope, ordinal,
                                   rows, state_path, state)
        revision_count += 1
    return {"status": "reconciled", "request_cleanup_checked": request_count,
            "revision_cleanup_checked": revision_count}


def execute(index_path: Path, index_sha: str, cache_root: Path,
            output: Path, workspace_root: Path,
            instance_root: Path, observed_request_peak_bytes: int,
            only_order: int | None = None) -> dict[str, Any]:
    """Execute only after configure() has passed every input and evidence gate."""
    require(cache_root.is_absolute() and cache_root == CACHE / f"full-{_engine_label()}" and
            output.is_absolute() and output == RUN_OUT / f"full-{_engine_label()}.noindex" and
            workspace_root.is_absolute() and workspace_root == WORKSPACES and
            instance_root.is_absolute() and instance_root == STORES,
            "B6g full J paths are not the prepared new paths")
    verify_both_pilots()
    if output.exists():
        require(output.is_dir() and (output / "state.json").is_file(),
                "B6f existing full J output has no resumable state")
    external_paths.EXTERNAL = EXTERNAL
    external_paths.require_external_root(workspace_root)
    external_paths.require_external_root(instance_root)
    external_paths.require_external_root(CACHE)
    external_paths.require_external_root(cache_root)
    output.mkdir(parents=True, exist_ok=True)
    external_paths.install_full(output, workspace_root, instance_root)
    index = runner.validate_index(index_path, index_sha)
    if only_order is not None:
        require(type(only_order) is int and
                any(row["queue_order"] == only_order for row in index["requests"]),
                "B6h execute-one queue order is absent from the full index")
    state = runner.load_state(output, index_sha, cache_root)
    state_path = output / "state.json"
    checker_sha = runner.sha256(ROOT / "scripts/n6_b6f_format_pilot.py")
    if state["requests"]:
        require(state.get("format_checker_sha256") == checker_sha,
                "B6f format checker changed during full J")
    state["format_checker_sha256"] = checker_sha
    inspection_count = sum(
        item.get("status") == "inspection_failure"
        for item in state["requests"].values())
    require(inspection_count <= 5, "B6f inspection failure count exceeds five")
    state["inspection_failure_count"] = inspection_count
    if inspection_count == 5:
        state["status"] = "inspection_failure_limit_reached"
        state["stop_reason"] = "B6f five inspection failures already recorded"
        runner.atomic_json(state_path, state)
        raise runner.RunnerError(state["stop_reason"])
    probe = runner.probe_time_l()
    state["status"] = "running"
    state["measurement_method"] = probe["measurement_method"]
    state["time_probe"] = probe
    attempts_path = output / "attempts.jsonl"
    runner.atomic_json(state_path, state)
    for scope, ordinal, revision_id, rows in runner.groups(index["requests"]):
        if only_order is not None and not any(
                row["queue_order"] == only_order for row in rows):
            continue
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
                "B6f revision state lock differs")
        runner.atomic_json(state_path, state)
        result_paths: list[Path] = []
        for row in rows:
            order = row["queue_order"]
            request_dir = revision_dir / "requests" / f"{order:06d}"
            previous = state["requests"].get(str(order))
            if previous is not None:
                require(previous.get("request_sha256") == row["request_sha256"],
                        f"B6f request state SHA mismatch at {order}")
            if only_order is not None and order != only_order:
                if previous is not None and previous.get("status") == "completed":
                    prior_result = previous.get("result_path")
                    prior_sha = previous.get("result_sha256")
                    require(isinstance(prior_result, str) and
                            isinstance(prior_sha, str) and len(prior_sha) == 64 and
                            Path(prior_result).is_file() and
                            runner.sha256(Path(prior_result)) == prior_sha,
                            f"B6h prior result SHA differs at {order}")
                    result_paths.append(Path(prior_result))
                continue
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
            try:
                prior = _prior_zero_exit(row, request_dir)
            except (OSError, format_gate.FormatInspectionError) as error:
                state["status"] = "environment_inspection_failure"
                state["stop_reason"] = f"B6f environment inspection failure at {order}: {error}"
                state["next_queue_order"] = order
                runner.atomic_json(state_path, state)
                raise
            free: dict[str, int] | None = None
            if prior is None:
                require(previous is None or previous.get("status") not in
                        {"completed", "preparation_failure", "inspection_failure"},
                        f"B6f completed request artifact missing at {order}")
                request = read_object(Path(row["request"]))
                runner.checked_request_sources(row, request, order)
                try:
                    free = cleanup.disk_guard(
                        output, cache_root, workspace_root, instance_root,
                        observed_request_peak_bytes,
                        _retained_evidence_du_bytes(state),
                        OTHER_ENGINE_CACHE_GROWTH_BYTES if
                        (only_order is None or only_order >= 39) else 0)
                except cleanup.DiskGuardStop as error:
                    state["status"] = "disk_guard_stopped"
                    state["stop_reason"] = str(error)
                    state["next_queue_order"] = order
                    runner.atomic_json(state_path, state)
                    raise
                cache = initialize_cache(cache_root, scope, ordinal,
                                         revision_id, index_sha)
                request_dir.mkdir(parents=True, exist_ok=True)
                attempt = _next_fresh_attempt(request_dir, output, workspace_root)
                result_dir = request_dir / f"attempt-{attempt:04d}"
                metrics = runner.run_lift(row, result_dir, cache,
                                          revision_dir / "store", attempt,
                                          probe["measurement_method"])
                runner.atomic_json(request_dir / f"attempt-{attempt:04d}.metrics.json",
                                   metrics)
                result_path = result_dir / "result.json"
                if metrics.get("exit_code") != 0 or not result_path.is_file():
                    state["status"] = "engine_failed"
                    state["stop_reason"] = f"B6f lift exit/result failure at {order}"
                    state["next_queue_order"] = order
                    runner.atomic_json(state_path, state)
                    raise runner.RunnerError(state["stop_reason"])
                try:
                    classification = inspect_result(result_path, row, metrics)
                except (OSError, format_gate.FormatInspectionError) as error:
                    state["status"] = "environment_inspection_failure"
                    state["stop_reason"] = f"B6f environment inspection failure at {order}: {error}"
                    state["next_queue_order"] = order
                    runner.atomic_json(state_path, state)
                    raise
            else:
                result_path, attempt, metrics, classification = prior
            status, reason, detail = classification
            if status != "completed" and reason in ENVIRONMENT_REASONS:
                state["status"] = "environment_preparation_failure"
                state["stop_reason"] = f"B6f environment preparation failure: {reason} at {order}"
                state["next_queue_order"] = order
                runner.atomic_json(state_path, state)
                raise runner.RunnerError(state["stop_reason"])
            if status != "completed" and isinstance(detail, str) and \
                    RESOURCE_DETAIL.search(detail):
                state["status"] = "resource_preparation_failure"
                state["stop_reason"] = (
                    f"B6f resource preparation failure: {reason} at {order}")
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
                if event["status"] == "inspection_failure":
                    inspection_count += 1
                    state["inspection_failure_count"] = inspection_count
                runner.append_jsonl(attempts_path, event)
                runner.atomic_json(state_path, state)
            # The result artifact and state SHA are durable before external cleanup.
            _cleanup_finished_workspace(state["requests"][str(order)], request_dir,
                                        output, workspace_root, state_path, state)
            if event["status"] == "completed":
                result_paths.append(result_path)
            if inspection_count == 5:
                state["status"] = "inspection_failure_limit_reached"
                state["stop_reason"] = f"B6f fifth inspection failure recorded at {order}"
                state["next_queue_order"] = order + 1
                runner.atomic_json(state_path, state)
                raise runner.RunnerError(state["stop_reason"])
        if only_order is not None and any(
                str(row["queue_order"]) not in state["requests"] for row in rows):
            revision_state["status"] = "running"
            runner.atomic_json(state_path, state)
            continue
        instance_path = revision_dir / "instances.json"
        if result_paths:
            if instance_path.exists():
                instance = read_object(instance_path)
                require(instance.get("schema") == "zkfdo-instance-verdicts-v1" and
                        instance.get("results") ==
                        [str(path.relative_to(output)) for path in result_paths] and
                        instance.get("conflicts") == 0,
                        "B6f existing instance join differs")
            else:
                join_attempt = _next_fresh_join_attempt(revision_dir, output,
                                                        workspace_root)
                working = revision_dir / f"instances-attempt-{join_attempt:04d}.json"
                metrics = runner.join_instances(result_paths, output, working,
                                                probe["measurement_method"])
                runner.atomic_json(revision_dir /
                                   f"instances-attempt-{join_attempt:04d}.metrics.json",
                                   metrics)
                runner.append_jsonl(attempts_path, {"kind": "lift-instances",
                                                     "scope": scope,
                                                     "revision_id": revision_id,
                                                     "revision_ordinal": ordinal,
                                                     "output": str(working), **metrics})
                require(metrics.get("exit_code") == 0 and working.is_file(),
                        "B6f instance join failed")
                instance = read_object(working)
                require(instance.get("schema") == "zkfdo-instance-verdicts-v1" and
                        instance.get("results") ==
                        [str(path.relative_to(output)) for path in result_paths] and
                        instance.get("conflicts") == 0,
                        "B6f instance join output invalid")
                working.replace(instance_path)
            revision_state.update({"status": "joined", "instances_path": str(instance_path),
                                   "instances_sha256": runner.sha256(instance_path),
                                   "result_count": len(result_paths)})
        else:
            revision_state.update({"status": "no_results", "instances_path": None,
                                   "instances_sha256": None, "result_count": 0})
        runner.atomic_json(state_path, state)
        # Join has consumed every runs/ result and recorded its own SHA.
        _cleanup_finished_revision(revision_state, cache_root, instance_root,
                                   workspace_root, output, scope, ordinal,
                                   rows, state_path, state)
    if only_order is not None:
        if len(state["requests"]) < index["request_count"]:
            state["status"] = "partial"
            state.pop("stop_reason", None)
            state.pop("next_queue_order", None)
            runner.atomic_json(state_path, state)
            return state
        require(set(state["requests"]) ==
                {str(row["queue_order"]) for row in index["requests"]},
                "B6h execute-one terminal request coverage differs")
        # Every request already has durable state. The normal replay can now
        # finalize any joined revision left by an interrupted prior invocation;
        # its existing-result checks prohibit starting another new request.
        return execute(index_path, index_sha, cache_root, output,
                       workspace_root, instance_root,
                       observed_request_peak_bytes)
    require(len(state["requests"]) == index["request_count"],
            "B6g run did not cover every indexed request")
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
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--instance-root", type=Path, required=True)
    parser.add_argument("--observed-request-peak-bytes", type=int, required=True)
    parser.add_argument("--action", choices=("validate-only", "execute-all",
                                             "execute-one", "reconcile-cleanup"),
                        default="validate-only")
    parser.add_argument("--queue-order", type=int)
    args = parser.parse_args(argv)
    try:
        require((args.action == "execute-one") == (args.queue_order is not None),
                "--queue-order is required only for execute-one")
        require(args.observed_request_peak_bytes == OBSERVED_REQUEST_PEAK_BYTES,
                "B6h observed request peak differs from the measured 280 GiB bound")
        index = configure(args.engine, args.index, args.index_sha256,
                          args.static_preflight, args.static_preflight_sha256,
                          args.first_lead_review_sha256,
                          args.second_lead_review_sha256)
        if args.action == "validate-only":
            print(json.dumps({"status": "valid", "request_count": index["request_count"],
                              "index_sha256": args.index_sha256}, sort_keys=True))
            return 0
        if args.action == "reconcile-cleanup":
            report = reconcile_cleanup(args.index, args.index_sha256,
                                       args.cache_root, args.output,
                                       args.workspace_root, args.instance_root)
            print(json.dumps(report, sort_keys=True))
            return 0
        state = execute(args.index, args.index_sha256,
                        args.cache_root, args.output,
                        args.workspace_root, args.instance_root,
                        args.observed_request_peak_bytes,
                        args.queue_order if args.action == "execute-one" else None)
        print(json.dumps({"status": state["status"],
                          "request_count": len(state["requests"]),
                          "output": str(args.output)}, sort_keys=True))
        return 0
    except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError) as error:
        print(f"B6h J runner refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
