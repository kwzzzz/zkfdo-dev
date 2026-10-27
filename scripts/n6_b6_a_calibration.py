#!/usr/bin/env python3
"""Prepare A's paired constructed/strict v2.2 J reruns; execute only on request.

The program handles existing A request documents in memory to change only the
base-input binding. It never prints candidate payloads or edits frozen files.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import n6_j1_summarize as summary
import run_n6_j1 as runner


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_INDEX = ROOT / "runs/n6-j1-2026-10-09.noindex/request-index.json"
ORIGINAL_INDEX_SHA256 = "35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c"
OFFICIAL_BASE = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
OFFICIAL_BASE_SHA256 = "18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508"
OLD_V22_STATE = ROOT / "runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/j-execute.noindex/state.json"
OLD_V22_STATE_SHA256 = "fa1da116b317d7833a60bec52826c2119a79f50dbec27616f4cbce2932a8a1f6"
OLD_V22_OUTPUT = OLD_V22_STATE.parent
ENGINE = ROOT / "runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2"
ENGINE_SHA256 = "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835"
SETTINGS = ROOT / "docs/n6_j4b_engine_v2_settings_v2_2026-10-17.json"
SETTINGS_SHA256 = "a4867e018a54df656dc1bdd079d7bb4fb6862a984b6e88784e5b30176e5da001"
OUTPUT = ROOT / "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex"
PREPARED = OUTPUT / "prepared"
COMPARISON_METHOD = PREPARED / "comparison-method-v2.json"
COMPARISON_METHOD_SHA256 = "8889bd92adb973897a8821d4a1e70166201b5e3b7b38c9a76357eb1315c1b536"
COMPARISON_METHOD_CONTENT = {
    "schema": "n6-b6-a-comparison-method-v2",
    "status": "fixed_before_any_calibration_j",
    "request_count": 122,
    "categories": ["L1", "excluded", "unknown"],
    "l1": "own entrypoint_violation or joined effective assumption_violation_reachable",
    "excluded": "completed non-L1 and every class has own excluded_in_context or joined effective assumption_excluded_in_context",
    "unknown": "all other completed non-L1 results",
    "matrix_rows_columns": [
        {"name": "strict_rerun_vs_constructed", "rows": "strict_rerun", "columns": "constructed"},
        {"name": "old_v22_vs_strict_rerun", "rows": "old_v22", "columns": "strict_rerun"},
    ],
    "statistics": ["agreement_rate", "constructed_l1_lost", "constructed_l1_gained",
                   "constructed_excluded_lost", "constructed_excluded_gained"],
    "injected_bug_confirmation": "aq-036 same-cause review pending; inference development revisions not injected",
    "interpretation": "A calibration only; never a B judgment gate",
}
CACHE = Path("/Volumes/zkfdo-jcache/n6-b6-acal")
S_STATE = ROOT / "runs/n6-b5-2026-10-17.noindex/s-nested-execute.noindex/state.json"
B6_STAGES = ROOT / "runs/n6-b6-2026-10-18.noindex/batch1x-prep.noindex/stages"
SELECTED = {
    "inference-original": 69,
    "aq-036-6d7df64759b6": 27,
    "inference-r-intdiv": 26,
}
METHODS = ("L1", "excluded", "unknown")


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def checked(path: Path, expected: str) -> None:
    runner.require(path.is_file() and digest(path) == expected, f"SHA-256 mismatch: {path}")


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def write_new(path: Path, value: Any) -> None:
    runner.require(not path.exists(), f"refuse to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")


def check_s_idle() -> None:
    if S_STATE.is_file():
        status = read(S_STATE).get("status")
        runner.require(status not in {"running", "start_checking", "starting", "start_gate_running"},
                       f"S rerun active: {status}")
    for stage in ("pilot-v2.2", "pilot-v1", "full-v2.2", "full-v1"):
        path = B6_STAGES / stage / "state.json"
        if path.is_file():
            status = read(path).get("status")
            runner.require(status != "running", f"B6 {stage} J stage active")


def check_fixed_inputs() -> tuple[dict, dict]:
    checked(ORIGINAL_INDEX, ORIGINAL_INDEX_SHA256)
    checked(OFFICIAL_BASE, OFFICIAL_BASE_SHA256)
    checked(ENGINE, ENGINE_SHA256)
    checked(SETTINGS, SETTINGS_SHA256)
    original = read(ORIGINAL_INDEX)
    base = read(OFFICIAL_BASE)
    runner.require(original["base_index_sha256"] == OFFICIAL_BASE_SHA256 and
                   Path(original["base_index"]) == OFFICIAL_BASE,
                   "A official base index binding changed")
    return original, base


def selected_rows(original: dict) -> list[dict]:
    rows = [row for row in original["requests"]
            if row["scope"] == "main" and row["method"] == "S"
            and row["revision_id"] in SELECTED]
    counts = Counter(row["revision_id"] for row in rows)
    runner.require(dict(counts) == SELECTED and
                   all(row["preparation_failure"] is None for row in rows),
                   f"A S selection/count changed: {dict(counts)}")
    return rows


def prepare() -> dict:
    check_s_idle()
    runner.require(not PREPARED.exists(), "A calibration preparation already exists")
    original, official = check_fixed_inputs()
    source_rows = selected_rows(original)
    inventory_path = Path(original["inventory"])
    checked(inventory_path, original["inventory_sha256"])
    inventory = read(inventory_path)
    candidate_hashes = {row["candidate_sha256"] for row in source_rows}
    inventory_rows = [row for row in inventory["rows"]
                      if row["candidate_sha256"] in candidate_hashes]
    runner.require(len(inventory_rows) == len(source_rows) == len(candidate_hashes),
                   "A selected inventory mapping is not one-to-one")

    check_s_idle()
    if not os.path.ismount(CACHE.parent):
        raise runner.RunnerError("/Volumes/zkfdo-jcache is not a mount point")
    PREPARED.mkdir(parents=True, exist_ok=False)
    write_new(COMPARISON_METHOD, COMPARISON_METHOD_CONTENT)
    checked(COMPARISON_METHOD, COMPARISON_METHOD_SHA256)

    subset_inventory = copy.deepcopy(inventory)
    subset_inventory["rows"] = inventory_rows
    subset_inventory["candidate_count"] = len(inventory_rows)
    subset_inventory["counts"] = {"main": {"S": len(inventory_rows), "W": 0},
                                  "mem20": {"S": 0, "W": 0}}
    subset_inventory["by_identifier"] = {
        "main": {identifier: count for identifier, count in SELECTED.items()},
        "mem20": {},
    }
    subset_inventory_path = PREPARED / "selected-inventory.json"
    write_new(subset_inventory_path, subset_inventory)

    constructed_base = copy.deepcopy(official)
    input_hashes = {}
    for identifier in SELECTED:
        strict = official["revisions"][identifier]
        runner.require(strict["status"] == "passed" and strict["selected_stage"] in
                       {"a_zkbugs", "b_l_series", "c_committed_json", "d_project_test", "e_zero"},
                       f"strict A input not passed: {identifier}")
        checked(Path(strict["base_input_path"]), strict["base_input_sha256"])
        constructed = OUTPUT / "constructed-inputs" / identifier / "input.json"
        check_record = OUTPUT / "constructed-inputs" / identifier / "check.json"
        runner.require(constructed.is_file() and check_record.is_file(),
                       f"constructed A input or check missing: {identifier}")
        record = read(check_record)
        runner.require(record["status"] == "passed" and record["r1cs_sha256_match"] is True
                       and record["input_sha256"] == digest(constructed)
                       and record["public_outputs_all_zero"] is False,
                       f"constructed A input failed fixed checks: {identifier}")
        runner.require(record["expected_r1cs_sha256"] == strict["compile"]["r1cs_sha256"],
                       f"constructed A R1CS reference mismatch: {identifier}")
        runner.require(digest(constructed) != strict["base_input_sha256"],
                       f"constructed and strict A inputs are identical: {identifier}")
        constructed_base["revisions"][identifier]["base_input_path"] = str(constructed.resolve())
        constructed_base["revisions"][identifier]["base_input_sha256"] = digest(constructed)
        constructed_base["revisions"][identifier]["selected_stage"] = "constructed"
        input_hashes[identifier] = {
            "constructed": digest(constructed),
            "strict": strict["base_input_sha256"],
            "constructed_check_sha256": digest(check_record),
        }
    constructed_base_path = PREPARED / "constructed-base-index.json"
    write_new(constructed_base_path, constructed_base)

    prepared_rows = {"constructed": [], "strict": []}
    selected_metadata = []
    for sequence, source_row in enumerate(source_rows):
        request_path = Path(source_row["request"])
        checked(request_path, source_row["request_sha256"])
        request = read(request_path)
        runner.require(request.get("base_input") ==
                       official["revisions"][source_row["revision_id"]]["base_input_path"],
                       "strict A request/base input binding changed")
        selected_metadata.append({"selected_order": sequence,
                                  "original_queue_order": source_row["queue_order"],
                                  "revision_id": source_row["revision_id"],
                                  "request_id": request["id"]})
        strict_row = copy.deepcopy(source_row)
        strict_row["queue_order"] = sequence
        strict_row["original_queue_order"] = source_row["queue_order"]
        prepared_rows["strict"].append(strict_row)

        overlay = copy.deepcopy(request)
        overlay["base_input"] = constructed_base["revisions"][source_row["revision_id"]]["base_input_path"]
        overlay_path = PREPARED / "constructed-requests" / f"{sequence:04d}.json"
        write_new(overlay_path, overlay)
        constructed_row = copy.deepcopy(strict_row)
        constructed_row["request"] = str(overlay_path.resolve())
        constructed_row["request_sha256"] = digest(overlay_path)
        prepared_rows["constructed"].append(constructed_row)

    indexes = {}
    for arm in ("constructed", "strict"):
        index = copy.deepcopy(original)
        index["engine"] = str(ENGINE.resolve())
        index["engine_sha256"] = ENGINE_SHA256
        index["inventory"] = str(subset_inventory_path.resolve())
        index["inventory_sha256"] = digest(subset_inventory_path)
        index["base_index"] = str((constructed_base_path if arm == "constructed" else OFFICIAL_BASE).resolve())
        index["base_index_sha256"] = digest(constructed_base_path) if arm == "constructed" else OFFICIAL_BASE_SHA256
        index["requests"] = prepared_rows[arm]
        index["request_count"] = len(prepared_rows[arm])
        index["preparation_counts"] = {"ready": len(prepared_rows[arm]), "base_input_unavailable": 0}
        index_path = PREPARED / f"{arm}-request-index.json"
        write_new(index_path, index)
        indexes[arm] = {"path": str(index_path.resolve()), "sha256": digest(index_path)}

    plan = {
        "schema": "n6-b6-a-calibration-plan-v1",
        "status": "prepared_not_executed",
        "selected_s_request_counts": SELECTED,
        "selected_requests": selected_metadata,
        "original_index_sha256": ORIGINAL_INDEX_SHA256,
        "official_base_index_sha256": OFFICIAL_BASE_SHA256,
        "engine_sha256": ENGINE_SHA256,
        "settings_sha256": SETTINGS_SHA256,
        "old_v22_state_sha256": OLD_V22_STATE_SHA256,
        "indexes": indexes,
        "input_hashes": input_hashes,
        "cache_roots": {arm: str((CACHE / f"{arm}-j").resolve())
                        for arm in ("constructed", "strict")},
        "output_roots": {arm: str((OUTPUT / f"{arm}-j").resolve())
                         for arm in ("constructed", "strict")},
        "comparison": {
            "classes": list(METHODS),
            "matrices": ["strict_rerun_vs_constructed", "old_v22_vs_strict_rerun"],
            "statistics": ["agreement_rate", "constructed_l1_lost", "constructed_l1_gained",
                           "constructed_excluded_lost", "constructed_excluded_gained",
                           "known_bug_confirmation_by_revision"],
        },
    }
    plan_path = PREPARED / "plan.json"
    write_new(plan_path, plan)
    validate()
    return {"status": "prepared_not_executed", "request_count": len(source_rows),
            "plan_sha256": digest(plan_path),
            "constructed_index_sha256": indexes["constructed"]["sha256"],
            "strict_index_sha256": indexes["strict"]["sha256"]}


def validate() -> dict:
    check_s_idle()
    check_fixed_inputs()
    checked(COMPARISON_METHOD, COMPARISON_METHOD_SHA256)
    plan_path = PREPARED / "plan.json"
    runner.require(plan_path.is_file(), "A calibration plan missing")
    plan = read(plan_path)
    runner.require(plan["status"] == "prepared_not_executed" and
                   plan["selected_s_request_counts"] == SELECTED,
                   "A calibration plan changed")
    runner.ENGINE, runner.ENGINE_SHA256 = ENGINE, ENGINE_SHA256
    for identifier, hashes in plan["input_hashes"].items():
        checked(OUTPUT / "constructed-inputs" / identifier / "input.json", hashes["constructed"])
        checked(OUTPUT / "constructed-inputs" / identifier / "check.json", hashes["constructed_check_sha256"])
        runner.require(read(OFFICIAL_BASE)["revisions"][identifier]["base_input_sha256"] == hashes["strict"],
                       f"strict A input SHA changed: {identifier}")
    for arm in ("constructed", "strict"):
        entry = plan["indexes"][arm]
        index_path = Path(entry["path"])
        runner.validate_index(index_path, entry["sha256"])
    return {"status": "valid_not_executed", "request_count": sum(SELECTED.values()),
            "plan_sha256": digest(plan_path)}


def execute() -> dict:
    validate()
    runner.require(os.path.ismount(CACHE.parent), "A calibration cache mount missing")
    plan = read(PREPARED / "plan.json")
    state_path = OUTPUT / "state.json"
    root_state = {"schema": "n6-b6-a-calibration-state-v1",
                  "status": "running", "plan_sha256": digest(PREPARED / "plan.json"),
                  "constructed": "pending", "strict": "pending"}
    if state_path.exists():
        previous = read(state_path)
        runner.require(previous.get("schema") == root_state["schema"] and
                       previous.get("plan_sha256") == root_state["plan_sha256"] and
                       previous.get("status") == "stopped",
                       "A calibration state already active or complete")
    runner.atomic_json(state_path, root_state)
    original_lift, original_join = runner.run_lift, runner.join_instances

    def guarded_lift(*args: Any) -> dict:
        check_s_idle()
        return original_lift(*args)

    def guarded_join(*args: Any) -> dict:
        check_s_idle()
        return original_join(*args)

    runner.run_lift, runner.join_instances = guarded_lift, guarded_join
    try:
        states = {}
        for arm in ("constructed", "strict"):
            check_s_idle()
            cache = Path(plan["cache_roots"][arm])
            runner.require(not cache.exists() or cache.is_dir(), "cache root is not a directory")
            cache.mkdir(parents=True, exist_ok=True)
            index = plan["indexes"][arm]
            output = Path(plan["output_roots"][arm])
            state = runner.execute(Path(index["path"]), index["sha256"], cache,
                                   output, cleanup_cache_per_revision=False)
            states[arm] = state.get("status")
            root_state[arm] = state.get("status")
            runner.atomic_json(state_path, root_state)
            runner.require(state.get("status") == "completed", f"{arm} A rerun incomplete")
        root_state["status"] = "completed"
        runner.atomic_json(state_path, root_state)
    except BaseException:
        root_state["status"] = "stopped"
        runner.atomic_json(state_path, root_state)
        raise
    finally:
        runner.run_lift, runner.join_instances = original_lift, original_join
    return {"status": "completed", "runs": states}


def categories(index: dict, state: dict, output: Path,
               selected_orders: set[int] | None = None) -> dict[int, str]:
    runner.require(state.get("status") == "completed", "A calibration J state incomplete")
    _revision_state, joins = summary.load_revisions(output, state)
    found = {}
    for row in index["requests"]:
        sequence = row["queue_order"]
        if selected_orders is not None and sequence not in selected_orders:
            continue
        joined = joins.get((row["scope"], row["revision_id"]))
        result = summary.summarize_request(row, state["requests"].get(str(sequence)), joined, output)
        runner.require(result["status"] == "completed" and result["l1"] is not None,
                       f"A calibration request incomplete: {sequence}")
        if result["l1"] is True:
            category = "L1"
        elif result["classes"] and all(
                entry["self_verdict"] == "excluded_in_context" or
                entry["effective_verdict"] == "assumption_excluded_in_context"
                for entry in result["classes"]):
            category = "excluded"
        else:
            category = "unknown"
        found[sequence] = category
    return found


def matrix(left: list[str], right: list[str]) -> dict:
    values = {a: {b: 0 for b in METHODS} for a in METHODS}
    for a, b in zip(left, right, strict=True):
        values[a][b] += 1
    return values


def aggregate() -> dict:
    validate()
    checked(OLD_V22_STATE, OLD_V22_STATE_SHA256)
    plan = read(PREPARED / "plan.json")
    original = read(ORIGINAL_INDEX)
    old_state = read(OLD_V22_STATE)
    categories_by_arm = {}
    for arm in ("constructed", "strict"):
        index = read(Path(plan["indexes"][arm]["path"]))
        output = Path(plan["output_roots"][arm])
        state_path = output / "state.json"
        runner.require(state_path.is_file(), f"A {arm} state missing")
        categories_by_arm[arm] = categories(index, read(state_path), output)
    selection = plan["selected_requests"]
    old_categories = categories(original, old_state, OLD_V22_OUTPUT,
                                {row["original_queue_order"] for row in selection})
    strict = [categories_by_arm["strict"][row["selected_order"]] for row in selection]
    constructed = [categories_by_arm["constructed"][row["selected_order"]] for row in selection]
    old = [old_categories[row["original_queue_order"]] for row in selection]
    changes = {
        "constructed_l1_lost": sum(a == "L1" and b != "L1" for a, b in zip(strict, constructed, strict=True)),
        "constructed_l1_gained": sum(a != "L1" and b == "L1" for a, b in zip(strict, constructed, strict=True)),
        "constructed_excluded_lost": sum(a == "excluded" and b != "excluded" for a, b in zip(strict, constructed, strict=True)),
        "constructed_excluded_gained": sum(a != "excluded" and b == "excluded" for a, b in zip(strict, constructed, strict=True)),
    }
    bug_status = {}
    for identifier in SELECTED:
        if identifier == "aq-036-6d7df64759b6":
            bug_status[identifier] = {
                "known_item_id": "worm-privacy/proof-of-burn/koukyosyumei_spend_missing_range_check",
                "constructed_l1_requests": sum(row["revision_id"] == identifier and cat == "L1"
                                               for row, cat in zip(selection, constructed, strict=True)),
                "confirmation": "manual_same_cause_review_required",
            }
        else:
            bug_status[identifier] = {"confirmation": "not_an_injected_bug_revision"}
    record = {
        "schema": "n6-b6-a-calibration-summary-v1",
        "plan_sha256": digest(PREPARED / "plan.json"),
        "comparison_method_sha256": COMPARISON_METHOD_SHA256,
        "request_count": len(selection),
        "per_request": [
            {"request_id": row["request_id"], "revision_id": row["revision_id"],
             "old_v22": old[i], "strict_rerun": strict[i], "constructed": constructed[i]}
            for i, row in enumerate(selection)
        ],
        "strict_rerun_vs_constructed": matrix(strict, constructed),
        "old_v22_vs_strict_rerun": matrix(old, strict),
        "agreement_rate": {
            "strict_vs_constructed": sum(a == b for a, b in zip(strict, constructed, strict=True)) / len(selection),
            "old_vs_strict": sum(a == b for a, b in zip(old, strict, strict=True)) / len(selection),
        },
        **changes,
        "known_bug_confirmation_by_revision": bug_status,
    }
    path = OUTPUT / "summary.json"
    write_new(path, record)
    return {"status": "summarized", "summary_sha256": digest(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("prepare", "validate-only", "execute", "aggregate"),
                        required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare()
        elif args.action == "validate-only":
            result = validate()
        elif args.action == "execute":
            result = execute()
        else:
            result = aggregate()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as error:
        print(f"A calibration stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
