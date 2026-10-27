#!/usr/bin/env python3
"""Prepare a new staged B batch and, later, its two reviewed format pilots.

The ``prepare`` action never calls the J engine. It creates a new 107-row
request index, checks the fixed engines' hint-copy prerequisites statically,
and runs each Python validate-only gate. The ``pilot`` action is reserved for
the human's later, explicit command; it preserves the B6 lead and selection
gates and writes all new output under B6b paths.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import n6_b6_batch1x_prepare as b6
import n6_j3_b_pilot_wait4 as selection
import run_n6_j1 as runner
from n6_b5_j_adapter import (ENGINE_V1, ENGINE_V1_SHA, ENGINE_V22,
                             ENGINE_V22_SHA, verify_mem20)
from n6_b6b_runtime_paths import require_external_root


ROOT = Path(__file__).resolve().parents[1]
B6B = ROOT / "runs/n6-b6b-2026-10-19.noindex"
OUT = B6B / "batch1x-prep.noindex"
EXTERNAL = Path("/Volumes/zkfdo-jcache/n6-b6b-batch1x")
STAGING = EXTERNAL / "source-staging"
WORKSPACES = EXTERNAL / "hint-workspaces"
STORES = EXTERNAL / "instance-stores"
CACHE = EXTERNAL / "cache"
PLAN = OUT / "request-index-pending.json"
INDEX_V1 = OUT / "request-index-v1.json"
INDEX_V22 = OUT / "request-index-v2.2.json"
REQUESTS = OUT / "requests"
STATIC = OUT / "static-preflight.json"
STATIC_REVISED = OUT / "static-preflight-96mib.json"
SOURCE_CAP_EVIDENCE = B6B / "source-cap-evidence.json"
REVISED_CIRCOM_BYTE_CAP = 96 * 1024 * 1024
INDEX_FAILED = OUT / "request-index-preparation-failed.json"
SELECTION = OUT / "pilot-selection.json"
ADAPTER = ROOT / "scripts/n6_b6b_j_adapter.py"
STATIC_TOOL = ROOT / "scripts/n6_b6b_static_preflight.py"
N5_AMENDMENT = ROOT / "docs/n5_amendment_b_judging_2026-10-17.md"
R1CS_COMPARISON = B6B / "r1cs-comparison.json"
BASE = b6.BASE
INVENTORY = b6.INVENTORY
QUEUE = b6.QUEUE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "expected JSON object")
    return value


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(name: str) -> Path:
    return OUT / "stages" / name / "state.json"


def save_state(name: str, value: dict[str, Any]) -> None:
    path = state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    sort_keys=True) + "\n")
    temporary.replace(path)


def stage(name: str, action, verify) -> dict[str, Any]:
    path = state_path(name)
    if path.exists():
        previous = read_json(path)
        require(previous.get("status") == "completed" and previous.get("exit_code") == 0,
                "incomplete B6b stage exists; preserve it for review")
        verify(previous)
        return previous
    value: dict[str, Any] = {"schema_version": 1, "stage": name,
                             "status": "running", "started_at": stamp()}
    save_state(name, value)
    try:
        value.update(action() or {})
        value["status"] = "completed"
        value["exit_code"] = 0
    except Exception as error:
        value["status"] = "failed"
        value["exit_code"] = 1
        value["error_type"] = type(error).__name__
        raise
    finally:
        value["completed_at"] = stamp()
        save_state(name, value)
    return value


def logged_command(name: str, command: list[str]) -> int:
    b6.s_idle()
    directory = state_path(name).parent
    directory.mkdir(parents=True, exist_ok=True)
    number = len(list(directory.glob("command-*.log"))) + 1
    with (directory / f"command-{number:03d}.log").open("x") as stream:
        return subprocess.run(command, cwd=ROOT, stdout=stream,
                              stderr=subprocess.STDOUT, check=False).returncode


def adapter_command(kind: str, engine: str, *args: str) -> list[str]:
    return [sys.executable, str(ADAPTER), "--stage", kind,
            "--engine", engine, "--source-staging-root", str(STAGING), *args]


def preflight() -> dict[str, Any]:
    b6.s_idle()
    verify_mem20()
    require(os.path.ismount(EXTERNAL.parent), "B6b external J volume is not mounted")
    for path in (STAGING, WORKSPACES, STORES, CACHE):
        require_external_root(path)
    require(sha256(ENGINE_V1) == ENGINE_V1_SHA and
            sha256(ENGINE_V22) == ENGINE_V22_SHA and
            runner.ENGINE == ENGINE_V1 and runner.ENGINE_SHA256 == ENGINE_V1_SHA,
            "fixed J engine pin differs")
    require(sha256(runner.CIRCOM) == runner.CIRCOM_SHA256,
            "fixed circom pin differs")
    require(all(path.is_file() for path in
                (INVENTORY, QUEUE, ADAPTER, STATIC_TOOL, N5_AMENDMENT,
                 b6.TABLE, b6.LEAD, b6.TABLE2, b6.LEAD2, BASE)),
            "B6b preparation input or review record missing")
    b6.base_index()
    disk_free = {"repository": shutil.disk_usage(ROOT).free,
                 "external": shutil.disk_usage(EXTERNAL).free}
    require(min(disk_free.values()) >= runner.MIN_FREE_BYTES,
            "B6b disk free below the runner minimum")
    require(logged_command("preflight", ["docker", "info"]) == 0,
            "Docker Desktop unavailable")
    require(logged_command("preflight", ["docker", "system", "df"]) == 0,
            "Docker disk inspection failed")
    return {"n5_amendment_sha256": sha256(N5_AMENDMENT),
            "base_index_sha256": sha256(BASE),
            "first_review_table_sha256": sha256(b6.TABLE),
            "first_lead_review_sha256": sha256(b6.LEAD),
            "second_review_table_sha256": sha256(b6.TABLE2),
            "second_lead_review_sha256": sha256(b6.LEAD2),
            "inventory_sha256": sha256(INVENTORY), "queue_sha256": sha256(QUEUE),
            "adapter_sha256": sha256(ADAPTER), "static_tool_sha256": sha256(STATIC_TOOL),
            "v1_engine_sha256": ENGINE_V1_SHA, "v2_2_engine_sha256": ENGINE_V22_SHA,
            "disk_free_bytes": disk_free}


def verify_preflight(saved: dict[str, Any]) -> None:
    b6.s_idle()
    verify_mem20()
    require(os.path.ismount(EXTERNAL.parent), "B6b external J volume is not mounted")
    for path in (STAGING, WORKSPACES, STORES, CACHE):
        require_external_root(path)
    for key, path in (("n5_amendment_sha256", N5_AMENDMENT),
                      ("base_index_sha256", BASE),
                      ("first_review_table_sha256", b6.TABLE),
                      ("first_lead_review_sha256", b6.LEAD),
                      ("second_review_table_sha256", b6.TABLE2),
                      ("second_lead_review_sha256", b6.LEAD2),
                      ("inventory_sha256", INVENTORY), ("queue_sha256", QUEUE),
                      ("adapter_sha256", ADAPTER),
                      ("static_tool_sha256", STATIC_TOOL)):
        require(saved.get(key) == sha256(path), "B6b preflight evidence changed")
    require(saved.get("v1_engine_sha256") == ENGINE_V1_SHA and
            saved.get("v2_2_engine_sha256") == ENGINE_V22_SHA,
            "B6b engine pin changed")
    b6.base_index()


def verify_preflight_gate() -> None:
    """Use the later adapter-only preflight if its old SHA was superseded."""
    path = state_path(preflight_stage_name())
    require(path.is_file(), "B6b preflight state missing")
    state = read_json(path)
    require(state.get("status") == "completed" and state.get("exit_code") == 0,
            "B6b preflight stage incomplete")
    verify_preflight(state)


def preflight_stage_name() -> str:
    original = state_path("preflight")
    if not original.is_file():
        return "preflight"
    saved = read_json(original)
    if saved.get("status") == "completed" and \
            saved.get("adapter_sha256") != sha256(ADAPTER):
        # A new adapter gate was added after the first preflight. All other
        # pinned inputs must remain identical; keep the old state untouched.
        for key, path in (("n5_amendment_sha256", N5_AMENDMENT),
                          ("base_index_sha256", BASE),
                          ("first_review_table_sha256", b6.TABLE),
                          ("first_lead_review_sha256", b6.LEAD),
                          ("second_review_table_sha256", b6.TABLE2),
                          ("second_lead_review_sha256", b6.LEAD2),
                          ("inventory_sha256", INVENTORY),
                          ("queue_sha256", QUEUE),
                          ("static_tool_sha256", STATIC_TOOL)):
            require(saved.get(key) == sha256(path),
                    "B6b preflight input changed besides adapter")
        updated = state_path("preflight-updated-adapter")
        if updated.is_file() and read_json(updated).get("adapter_sha256") == sha256(ADAPTER):
            return "preflight-updated-adapter"
        return "preflight-adapter-" + sha256(ADAPTER)[:12]
    return "preflight"


def write_new(path: Path, value: dict[str, Any]) -> str:
    require(not path.exists(), "refusing to overwrite B6b artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return sha256(path)


def index_summary() -> dict[str, Any]:
    require(all(path.is_file() for path in (PLAN, INDEX_V1, INDEX_V22)),
            "B6b request index missing")
    plan = read_json(PLAN)
    v1 = read_json(INDEX_V1)
    v22 = read_json(INDEX_V22)
    rows = v1.get("requests")
    planned = plan.get("requests")
    require(plan.get("status") == "awaiting_base_input" and
            plan.get("request_count") == 107 and
            isinstance(planned, list) and len(planned) == 107,
            "B6b request plan is not 107 rows")
    require(v1.get("schema_version") == 1 and v1.get("status") == "verified" and
            v1.get("request_count") == 107 and
            isinstance(rows, list) and len(rows) == 107,
            "B6b final request index is not 107 rows")
    require(plan.get("queue_sha256") == sha256(QUEUE) and
            plan.get("inventory_sha256") == sha256(INVENTORY),
            "B6b request plan input lock differs")
    require(v1.get("base_index") == str(BASE) and
            v1.get("base_index_sha256") == sha256(BASE) and
            v1.get("plan_index_sha256") == sha256(PLAN) and
            v1.get("inventory_sha256") == sha256(INVENTORY) and
            v1.get("engine_sha256") == ENGINE_V1_SHA,
            "B6b request index input lock differs")
    require(v22 == {**v1, "engine": str(ENGINE_V22),
                    "engine_sha256": ENGINE_V22_SHA},
            "B6b v2.2 overlay changed request rows")
    require(all(isinstance(row, dict) and row.get("method") == "S" and
                isinstance(row.get("original_entrypoint"), str) and
                isinstance(row.get("original_component_wrapper"), str) and
                row.get("preparation_failure") is None for row in rows) and
            len({row["request"] for row in rows}) == 107,
            "B6b request methods, staging metadata or readiness differ")
    require(all(isinstance(row, dict) and
                Path(row["source_root"]).resolve().is_relative_to(STAGING.resolve())
                for row in planned), "B6b planned source root escaped staging")
    return {"plan_sha256": sha256(PLAN), "v1_index_sha256": sha256(INDEX_V1),
            "v2_2_index_sha256": sha256(INDEX_V22), "request_count": 107,
            "ready_count": v1.get("preparation_counts", {}).get("ready", 0)}


def prepare_index() -> dict[str, Any]:
    common = ("--scope", "main", "--inventory", str(INVENTORY),
              "--queue", str(QUEUE), "--request-root", str(REQUESTS),
              "--plan-index", str(PLAN), "--index", str(INDEX_V1))
    if not PLAN.exists():
        require(logged_command("index", adapter_command("requests", "v1", *common)) == 0,
                "B6b request plan failed")
    if not INDEX_V1.exists():
        require(not REQUESTS.exists(),
                "partial B6b request files exist; preserve for review")
        require(logged_command("index", adapter_command(
            "requests", "v1", *common, "--base-index", str(BASE))) == 0,
            "B6b request finalization failed")
    if not INDEX_V22.exists():
        v1 = read_json(INDEX_V1)
        require(v1.get("engine") == str(ENGINE_V1) and
                v1.get("engine_sha256") == ENGINE_V1_SHA,
                "B6b v1 engine lock differs")
        write_new(INDEX_V22, {**v1, "engine": str(ENGINE_V22),
                              "engine_sha256": ENGINE_V22_SHA})
    return index_summary()


def static_summary() -> dict[str, Any]:
    report_path = STATIC_REVISED if STATIC_REVISED.is_file() else STATIC
    require(report_path.is_file(), "B6b static preparation report missing")
    report = read_json(report_path)
    require(report.get("index_path") == str(INDEX_V1.resolve()) and
            report.get("index_sha256") == sha256(INDEX_V1) and
            report.get("request_count") == 107,
            "B6b static report index binding differs")
    engines = report.get("per_engine")
    require(isinstance(engines, dict) and set(engines) == {"v1", "v2.2"},
            "B6b static report engine coverage differs")
    return {"report_sha256": sha256(report_path),
            "v1_passed": engines["v1"].get("passed"),
            "v2_2_passed": engines["v2.2"].get("passed"),
            "all_passed": report.get("all_passed") is True}


def static_stage_name() -> str:
    old = state_path("static")
    if not old.is_file() or read_json(old).get("status") != "failed":
        return "static"
    report = read_json(STATIC)
    require(report.get("limits", {}).get("circom_bytes") == 64 * 1024 * 1024 and
            report.get("request_count") == 107 and
            report.get("per_engine", {}).get("v1", {}).get("failed") == 70 and
            report.get("per_engine", {}).get("v2.2", {}).get("failed") == 70 and
            all(row.get("reasons") == ["circom_byte_cap_exceeded"] and
                str(row.get("revision_id", "")).startswith("a8b2aa9c")
                for row in report.get("row_checks", [])
                if row.get("status") != "passed"),
            "B6b static failure is not solely the measured 64 MiB cap")
    evidence = read_json(SOURCE_CAP_EVIDENCE)
    require(evidence.get("plan_sha256") == sha256(PLAN) and
            evidence.get("source_root_count") == 17 and
            evidence.get("max_circom_files", 0) <= 2_000 and
            64 * 1024 * 1024 < evidence.get("max_circom_bytes", 0) <=
            REVISED_CIRCOM_BYTE_CAP,
            "B6b revised source cap lacks bounded measurement evidence")
    return "static-cap-revised"


def verify_static_gate() -> None:
    stage_name = static_stage_name()
    path = state_path(stage_name)
    require(path.is_file(), "B6b static preparation stage missing")
    saved = read_json(path)
    current = static_summary()
    require(saved.get("status") == "completed" and saved.get("exit_code") == 0 and
            current["all_passed"] and current["v1_passed"] == 107 and
            current["v2_2_passed"] == 107 and
            all(saved.get(key) == value for key, value in current.items()),
            "B6b static preparation gate changed")


def preparation_failure_index() -> str:
    """Keep 107 rows, mark failed ones, and make this new index non-runnable."""
    report = read_json(STATIC)
    original = read_json(INDEX_V1)
    checks = report.get("row_checks")
    rows = original.get("requests")
    require(isinstance(checks, list) and len(checks) == 107 and
            isinstance(rows, list) and len(rows) == 107,
            "B6b static failure row coverage differs")
    marked = []
    failures = 0
    for order, (row, checked) in enumerate(zip(rows, checks)):
        require(isinstance(row, dict) and row.get("queue_order") == order and
                isinstance(checked, dict) and checked.get("queue_order") == order and
                checked.get("revision_id") == row.get("revision_id"),
                "B6b static failure row binding differs")
        next_row = dict(row)
        if checked.get("status") != "passed":
            reasons = checked.get("reasons")
            require(isinstance(reasons, list) and reasons and
                    all(isinstance(reason, str) and reason for reason in reasons),
                    "B6b static failure reason missing")
            next_row["preparation_failure"] = "B6b static: " + ", ".join(reasons)
            failures += 1
        marked.append(next_row)
    require(failures > 0, "B6b static failure overlay has no failed rows")
    overlay = {**original, "status": "preparation_failed",
               "preparation_counts": {"ready": 107 - failures,
                                      "preparation_failed": failures},
               "static_preflight": str(STATIC),
               "static_preflight_sha256": sha256(STATIC), "requests": marked}
    if INDEX_FAILED.exists():
        require(read_json(INDEX_FAILED) == overlay,
                "B6b static failure index differs; preserve for review")
    else:
        write_new(INDEX_FAILED, overlay)
    return sha256(INDEX_FAILED)


def static_preflight() -> dict[str, Any]:
    revised = static_stage_name() == "static-cap-revised"
    report_path = STATIC_REVISED if revised else STATIC
    if not report_path.exists():
        command = [sys.executable, str(STATIC_TOOL), "--index", str(INDEX_V1),
                   "--source-staging-root", str(STAGING),
                   "--workspace-root", str(WORKSPACES),
                   "--instance-root", str(STORES), "--cache-root", str(CACHE),
                   "--output", str(report_path)]
        if revised:
            command.extend(("--max-circom-bytes", str(REVISED_CIRCOM_BYTE_CAP)))
        status = logged_command("static-cap-revised" if revised else "static", command)
        require(status in {0, 2}, "B6b static preflight process failed")
    summary = static_summary()
    if not summary["all_passed"] or summary["v1_passed"] != 107 or \
            summary["v2_2_passed"] != 107:
        if not revised:
            preparation_failure_index()
    require(summary["all_passed"] and summary["v1_passed"] == 107 and
            summary["v2_2_passed"] == 107,
            "B6b static preparation failure; J validation and pilot refused")
    if not revised:
        require(not INDEX_FAILED.exists(), "B6b failed preparation index exists")
    return summary


def r1cs_gate() -> dict[str, Any]:
    """Bind all 17 original/staged S-wrapper comparisons before any J call."""
    require(R1CS_COMPARISON.is_file(), "B6b S-wrapper R1CS comparison missing")
    report = read_json(R1CS_COMPARISON)
    pairs = report.get("pairs")
    require(report.get("schema") == "n6-b6b-r1cs-comparison-v1" and
            report.get("status") == "matched" and
            report.get("index_sha256") == sha256(INDEX_V1) and
            report.get("request_count") == 107 and
            report.get("source_pair_count") == 17 and
            isinstance(pairs, list) and len(pairs) == 17 and
            all(isinstance(pair, dict) and pair.get("match") is True and
                isinstance(pair.get("original"), dict) and
                isinstance(pair.get("staged"), dict) and
                pair["original"].get("r1cs_sha256") ==
                pair["staged"].get("r1cs_sha256") for pair in pairs),
            "B6b S-wrapper R1CS equality gate failed")
    orders = [order for pair in pairs for order in pair.get("queue_orders", [])]
    require(sorted(orders) == list(range(107)),
            "B6b S-wrapper R1CS request coverage differs")
    return {"r1cs_comparison_sha256": sha256(R1CS_COMPARISON),
            "source_pair_count": 17, "request_count": 107}


def validate(engine: str, index: Path) -> dict[str, Any]:
    command = adapter_command("validate", engine, "--index", str(index),
                              "--index-sha256", sha256(index),
                              "--cache-root", str(CACHE),
                              "--action", "validate-only")
    require(logged_command(f"validate-{engine}", command) == 0,
            "B6b validate-only failed")
    return {"index_sha256": sha256(index), "validation_exit_code": 0}


def verify_validate(saved: dict[str, Any], index: Path) -> None:
    require(saved.get("index_sha256") == sha256(index) and
            saved.get("validation_exit_code") == 0,
            "B6b validate-only evidence changed")


def selected_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"request_id": Path(row["request"]).stem,
             "queue_order": row["queue_order"],
             "revision_id": row["revision_id"]} for row in rows]


def pilot_selection() -> dict[str, Any]:
    base = b6.base_index()
    index = read_json(INDEX_V1)
    approved = b6.review_gate(base, index)
    b6.results_review_gate(base, index)
    selected = selection.select_requests(index, base)
    require(len(selected) == 2 and all(row["revision_id"] in approved and
                                       row["preparation_failure"] is None
                                       for row in selected),
            "two approved callable B pilot requests required")
    expected = {"schema_version": 1, "requests": selected_ids(selected)}
    if SELECTION.exists():
        require(read_json(SELECTION) == expected, "B6b pilot selection changed")
    else:
        write_new(SELECTION, expected)
    return {"selection_sha256": sha256(SELECTION), "selected_count": 2,
            "first_review_table_sha256": sha256(b6.TABLE),
            "first_lead_review_sha256": sha256(b6.LEAD),
            "second_review_table_sha256": sha256(b6.TABLE2),
            "second_lead_review_sha256": sha256(b6.LEAD2)}


def verify_selection(saved: dict[str, Any]) -> None:
    current = pilot_selection()
    require(all(saved.get(key) == value for key, value in current.items()),
            "B6b pilot selection or lead review changed")


def pilot_state(engine: str, index: Path, output: Path) -> dict[str, Any]:
    state_file = output / "state.json"
    state = read_json(state_file)
    rows = {row["queue_order"]: row for row in read_json(index)["requests"]}
    require(state.get("kind") == "n6_b5_format_only_pilot_state" and
            state.get("status") == "passed" and
            state.get("request_index_sha256") == sha256(index) and
            state.get("base_index_sha256") == sha256(BASE) and
            state.get("selection_sha256") == sha256(SELECTION) and
            state.get("engine_sha256") ==
            (ENGINE_V22_SHA if engine == "v2.2" else ENGINE_V1_SHA),
            "B6b format pilot state binding differs")
    records = state.get("requests")
    require(isinstance(records, dict) and len(records) == 2 and
            all(isinstance(record, dict) and record.get("status") == "completed" and
                record.get("exit_code") == 0 and record.get("format_ok") is True and
                type(record.get("max_rss_bytes")) is int and
                record["max_rss_bytes"] > 0 for record in records.values()),
            "B6b format pilot did not complete two requests")
    for record in records.values():
        row = rows.get(record.get("queue_order"))
        result = record.get("result_path")
        require(isinstance(row, dict) and isinstance(result, str) and
                record.get("request_sha256") == row.get("request_sha256") and
                Path(result).is_file() and sha256(Path(result)) ==
                record.get("result_sha256"),
                "B6b pilot result/request hash binding differs")
    revisions = state.get("revisions")
    require(isinstance(revisions, dict) and revisions and
            all(isinstance(row, dict) and row.get("status") == "joined" and
                row.get("format_ok") is True and row.get("exit_code") == 0 and
                isinstance(row.get("instances_path"), str) and
                Path(row["instances_path"]).is_file() and
                sha256(Path(row["instances_path"])) == row.get("instances_sha256")
                for row in revisions.values()),
            "B6b pilot joined instance hash binding differs")
    return {"output": str(output), "state_sha256": sha256(state_file),
            "completed_request_count": 2, "format_ok": True}


def pilot(engine: str, index: Path) -> dict[str, Any]:
    b6.review_gate(b6.base_index(), read_json(INDEX_V1))
    r1cs_gate()
    verify_static_gate()
    output = OUT / f"pilot-{engine}.noindex"
    cache = CACHE / f"pilot-{engine}"
    require(not output.exists() and not cache.exists(),
            "B6b pilot output/cache already exists; preserve for review")
    command = adapter_command(
        "pilot", engine, "--index", str(index), "--index-sha256", sha256(index),
        "--base-index", str(BASE), "--base-index-sha256", sha256(BASE),
        "--selection", str(SELECTION), "--cache-root", str(cache),
        "--workspace-root", str(WORKSPACES), "--instance-root", str(STORES),
        "--output", str(output), "--action", "execute")
    require(logged_command(f"pilot-{engine}", command) == 0,
            "B6b format pilot failed")
    return {"engine": engine, "cache_root": str(cache),
            **pilot_state(engine, index, output)}


def verify_pilot(saved: dict[str, Any], engine: str, index: Path) -> None:
    output = OUT / f"pilot-{engine}.noindex"
    cache = CACHE / f"pilot-{engine}"
    require(cache.is_dir(), "B6b pilot cache missing")
    current = {"engine": engine, "cache_root": str(cache),
               **pilot_state(engine, index, output)}
    require(all(saved.get(key) == value for key, value in current.items()),
            "B6b pilot state changed")


def full_state(engine: str, index: Path, cache: Path,
               output: Path) -> dict[str, Any]:
    state_file = output / "state.json"
    state = read_json(state_file)
    require(state.get("status") == "completed" and
            state.get("request_index_sha256") == sha256(index) and
            state.get("engine_sha256") ==
            (ENGINE_V22_SHA if engine == "v2.2" else ENGINE_V1_SHA) and
            state.get("cache_root") == str(cache) and
            isinstance(state.get("requests"), dict) and
            len(state["requests"]) == 107,
            "B6b full J state incomplete")
    return {"output": str(output), "cache_root": str(cache),
            "state_sha256": sha256(state_file), "request_count": 107}


def full(engine: str, index: Path) -> dict[str, Any]:
    """Future full J entry point, behind both successful new format pilots."""
    b6.results_review_gate(b6.base_index(), read_json(INDEX_V1))
    r1cs_gate()
    verify_static_gate()
    cache = CACHE / f"full-{engine}"
    output = OUT / f"full-{engine}.noindex"
    require(not cache.exists() and not output.exists(),
            "B6b full J output/cache already exists; preserve for review")
    cache.mkdir(parents=True, exist_ok=False)
    command = adapter_command(
        "validate", engine, "--index", str(index), "--index-sha256", sha256(index),
        "--cache-root", str(cache), "--workspace-root", str(WORKSPACES),
        "--instance-root", str(STORES), "--output", str(output),
        "--action", "execute")
    require(logged_command(f"full-{engine}", command) == 0,
            "B6b full J execution stopped")
    return {"engine": engine, **full_state(engine, index, cache, output)}


def verify_full(saved: dict[str, Any], engine: str, index: Path) -> None:
    cache = CACHE / f"full-{engine}"
    output = OUT / f"full-{engine}.noindex"
    current = {"engine": engine, **full_state(engine, index, cache, output)}
    require(all(saved.get(key) == value for key, value in current.items()),
            "B6b full J state changed")


def prepare() -> None:
    stage(preflight_stage_name(), preflight, verify_preflight)
    index_stage = "index"
    if state_path("index").is_file():
        previous = read_json(state_path("index"))
        if previous.get("status") == "failed":
            require(previous.get("error_type") == "ValueError" and
                    all(path.is_file() for path in (PLAN, INDEX_V1, INDEX_V22)) and
                    REQUESTS.is_dir(),
                    "B6b failed index has incomplete artifacts; preserve for review")
            # Preserve the original failed state and record a new verification.
            index_stage = "index-recovered"
    stage(index_stage, prepare_index if index_stage == "index" else index_summary,
          lambda saved: require(all(saved.get(key) == value
                                    for key, value in index_summary().items()),
                                "B6b request index changed"))
    stage(static_stage_name(), static_preflight,
          lambda saved: require(all(saved.get(key) == value
                                    for key, value in static_summary().items()) and
                                saved.get("all_passed") is True,
                                "B6b static preparation changed"))
    stage("validate-v2.2", lambda: validate("v2.2", INDEX_V22),
          lambda saved: verify_validate(saved, INDEX_V22))
    stage("validate-v1", lambda: validate("v1", INDEX_V1),
          lambda saved: verify_validate(saved, INDEX_V1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("prepare", "pilot", "full"), required=True)
    args = parser.parse_args(argv)
    prepare()
    if args.action == "pilot":
        r1cs_gate()
        stage("pilot-selection", pilot_selection, verify_selection)
        stage("pilot-v2.2", lambda: pilot("v2.2", INDEX_V22),
              lambda saved: verify_pilot(saved, "v2.2", INDEX_V22))
        stage("pilot-v1", lambda: pilot("v1", INDEX_V1),
              lambda saved: verify_pilot(saved, "v1", INDEX_V1))
    if args.action == "full":
        r1cs_gate()
        selection_state = read_json(state_path("pilot-selection"))
        require(selection_state.get("status") == "completed" and
                selection_state.get("exit_code") == 0,
                "B6b pilot selection is incomplete")
        verify_selection(selection_state)
        for engine, index in (("v2.2", INDEX_V22), ("v1", INDEX_V1)):
            state = read_json(state_path(f"pilot-{engine}"))
            require(state.get("status") == "completed" and state.get("exit_code") == 0,
                    "both B6b format pilots must pass before full J")
            verify_pilot(state, engine, index)
        stage("full-v2.2", lambda: full("v2.2", INDEX_V22),
              lambda saved: verify_full(saved, "v2.2", INDEX_V22))
        stage("full-v1", lambda: full("v1", INDEX_V1),
              lambda saved: verify_full(saved, "v1", INDEX_V1))
    print(f"B6b {args.action}: exit_code=0", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"B6b batch1x stopped: {type(error).__name__}; review new stage state/logs",
              file=sys.stderr)
        raise SystemExit(2) from error
