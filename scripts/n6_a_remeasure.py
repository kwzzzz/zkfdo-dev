#!/usr/bin/env python3
"""Re-measure A Banyan with checked constructed inputs and frozen J engines.

Only this run's directory is writable. Original requests retain their order and
IDs; their sole semantic change is base_input. No candidate is generated here.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any

import run_n6_j1 as runner


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runs/n6-a-remeasure-2026-10-25.noindex"
PREPARED = OUTPUT / "prepared"
BASE = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
BASE_SHA = "18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508"
ENGINES = {
    "v2.2": {
        "path": ROOT / "runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2",
        "sha256": "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835",
        "index": ROOT / "runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/request-index-v2.json",
        "index_sha256": "d1102d837e5d78116cb44a2b67f5a9796f57bbc2a6733d712205eb1d528ceed8",
    },
    "v1": {
        "path": ROOT / "runs/l07-2026-10-05/tools/zkfDO",
        "sha256": "e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed",
        "index": ROOT / "runs/n6-j1-2026-10-09.noindex/request-index.json",
        "index_sha256": "35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c",
    },
}
REVISIONS = ("banyan-vulnerable", "banyan-fixed")
EXPECTED_COUNTS = {("banyan-vulnerable", "W"): 1699,
                   ("banyan-vulnerable", "S"): 108,
                   ("banyan-fixed", "S"): 24}
MIN_FREE_BYTES = 8 * 1024**3
PROJECTION_MIN_REQUESTS = 8
MAX_TOTAL_SECONDS = 3 * 60 * 60
TERMINAL = {"completed", "preparation_failure"}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    runner.require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def owned(path: Path) -> Path:
    resolved = path.resolve()
    runner.require(resolved.is_relative_to(OUTPUT) and not path.is_symlink(),
                   f"path outside this A run: {path}")
    return resolved


def write_fixed(path: Path, value: dict[str, Any]) -> None:
    owned(path)
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists():
        runner.require(path.read_text() == content, f"refuse to overwrite fixed artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(content)


def selected(index: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in index["requests"] if row["revision_id"] in REVISIONS]
    runner.require(Counter((r["revision_id"], r["method"]) for r in rows) == EXPECTED_COUNTS
                   and all(r["scope"] == "main" and
                           r["preparation_failure"] == "base_input_unavailable" for r in rows),
                   "frozen Banyan selection differs")
    orders = [row["queue_order"] for row in rows]
    runner.require(orders == sorted(set(orders)), "original queue order is not unique/sorted")
    return rows


def checked_inputs() -> dict[str, dict[str, str]]:
    runner.checked_sha(BASE, BASE_SHA, "official A base index")
    official = read(BASE)
    inputs = {}
    for revision in REVISIONS:
        path = owned(OUTPUT / "inputs" / revision / "input.json")
        check = owned(path.with_name("check.json"))
        record = read(check)
        expected = official["revisions"][revision]["compile"]["r1cs_sha256"]
        runner.require(record.get("schema") == "n6-b6-constructed-check-v1" and
                       record.get("scope") == "A" and record.get("identifier") == revision and
                       record.get("status") == "passed" and
                       record.get("input_path") == str(path) and
                       record.get("input_sha256") == runner.sha256(path) and
                       record.get("r1cs_map_sha256") == BASE_SHA and
                       record.get("r1cs_sha256_match") is True and
                       record.get("expected_r1cs_sha256") == expected and
                       record.get("compile", {}).get("r1cs_sha256") == expected,
                       f"constructed input/check binding invalid: {revision}")
        audit = record.get("child_audit", [])
        runner.require(all(any(child.get("kind") == kind and child.get("exit_code") == 0
                               for child in audit)
                           for kind in ("node_witness", "rust_r1cs", "snarkjs_r1cs")),
                       f"honest witness/Rust/snarkjs checks missing: {revision}")
        inputs[revision] = {"path": str(path), "sha256": runner.sha256(path),
                            "check": str(check), "check_sha256": runner.sha256(check),
                            "r1cs_sha256": expected}
    return inputs


def frozen_index(engine: str) -> dict[str, Any]:
    pin = ENGINES[engine]
    runner.checked_sha(pin["path"], pin["sha256"], f"frozen {engine} engine")
    runner.checked_sha(pin["index"], pin["index_sha256"], f"frozen {engine} index")
    runner.checked_sha(runner.CIRCOM, runner.CIRCOM_SHA256, "frozen circom")
    index = read(pin["index"])
    runner.require(index.get("schema_version") == 1 and index.get("status") == "verified"
                   and index.get("request_count") == len(index.get("requests", [])) == 2926
                   and index.get("engine") == str(pin["path"])
                   and index.get("engine_sha256") == pin["sha256"]
                   and index.get("base_index") == str(BASE)
                   and index.get("base_index_sha256") == BASE_SHA
                   and index.get("circom") == str(runner.CIRCOM)
                   and index.get("circom_sha256") == runner.CIRCOM_SHA256,
                   f"frozen {engine} locks differ")
    return index


def prepare() -> dict[str, Any]:
    inputs = checked_inputs()  # Inputs are fixed before any request document is read.
    indexes = {}
    base = copy.deepcopy(read(BASE))
    for revision, binding in inputs.items():
        base["revisions"][revision].update({"status": "passed", "selected_stage": "constructed",
                                           "base_input_path": binding["path"],
                                           "base_input_sha256": binding["sha256"]})
    base["layer"] = "A_constructed_base_input_remeasurement"
    base_path = PREPARED / "constructed-base-index.json"
    write_fixed(base_path, base)
    for engine in ENGINES:
        original = frozen_index(engine)
        rows = selected(original)
        originals = []
        new_rows = []
        for row in rows:
            path = Path(row["request"])
            runner.checked_sha(path, row["request_sha256"], "original A request")
            request = read(path)
            old_base = request.get("base_input")
            runner.require(old_base is None or
                           isinstance(old_base, str) and not Path(old_base).is_file(),
                           "original unavailable base input unexpectedly exists")
            overlay = copy.deepcopy(request)
            overlay["base_input"] = inputs[row["revision_id"]]["path"]
            target = PREPARED / engine / "requests" / f"{row['queue_order']:06d}.json"
            write_fixed(target, overlay)
            revised = copy.deepcopy(row)
            revised.update({"request": str(target), "request_sha256": runner.sha256(target),
                            "preparation_failure": None})
            new_rows.append(revised)
            originals.append({"queue_order": row["queue_order"], "request_id": request["id"]})
        runner.require(len({row["request_id"] for row in originals}) == len(rows),
                       "duplicate original request ID")
        index = copy.deepcopy(original)
        index.update({"requests": new_rows, "request_count": len(new_rows),
                      "base_index": str(base_path), "base_index_sha256": runner.sha256(base_path),
                      "preparation_counts": {"ready": len(new_rows), "base_input_unavailable": 0},
                      "remeasurement_original_index": str(ENGINES[engine]["index"]),
                      "remeasurement_original_index_sha256": ENGINES[engine]["index_sha256"],
                      "layer": "A_constructed_base_input_remeasurement"})
        path = PREPARED / f"request-index-{engine}.json"
        write_fixed(path, index)
        indexes[engine] = {"path": str(path), "sha256": runner.sha256(path),
                           "request_count": len(new_rows)}
    plan = {"schema": "n6-a-remeasure-banyan-plan-v1", "inputs": inputs, "indexes": indexes,
            "engine_order": list(ENGINES), "total_requests": 3662,
            "min_free_bytes": MIN_FREE_BYTES, "max_total_seconds": MAX_TOTAL_SECONDS,
            "projection_min_requests": PROJECTION_MIN_REQUESTS,
            "classification": "B6h judgement_flags: own entrypoint_violation or joined effective "
                              "assumption_violation_reachable; otherwise any own/effective excluded; "
                              "otherwise unknown",
            "strict_A_results_unchanged": True}
    write_fixed(PREPARED / "plan.json", plan)
    validate()
    return {"status": "prepared", "plan_sha256": runner.sha256(PREPARED / "plan.json"),
            "indexes": indexes, "inputs": inputs}


def validate() -> dict[str, Any]:
    plan = read(PREPARED / "plan.json")
    runner.require(plan.get("schema") == "n6-a-remeasure-banyan-plan-v1" and
                   plan.get("inputs") == checked_inputs() and
                   plan.get("engine_order") == list(ENGINES) and
                   set(plan.get("indexes", {})) == set(ENGINES) and plan.get("total_requests") == 3662,
                   "prepared plan or checked input changed")
    for engine, entry in plan["indexes"].items():
        runner.require(engine in ENGINES and entry["path"] == str(PREPARED / f"request-index-{engine}.json"),
                       "prepared engine/index path differs")
        original = frozen_index(engine)
        source_rows = selected(original)
        path = owned(Path(entry["path"]))
        runner.checked_sha(path, entry["sha256"], "prepared request index")
        index = read(path)
        runner.require(index.get("request_count") == len(index.get("requests", [])) == len(source_rows)
                       and index.get("engine") == original["engine"]
                       and index.get("engine_sha256") == original["engine_sha256"]
                       and index.get("inventory") == original["inventory"]
                       and index.get("inventory_sha256") == original["inventory_sha256"],
                       "prepared index bindings differ")
        runner.checked_sha(Path(index["base_index"]), index["base_index_sha256"], "constructed base index")
        base = read(Path(index["base_index"]))
        for revision, binding in plan["inputs"].items():
            runner.require(base["revisions"][revision]["base_input_path"] == binding["path"] and
                           base["revisions"][revision]["base_input_sha256"] == binding["sha256"] and
                           base["revisions"][revision]["status"] == "passed",
                           "constructed base index input binding differs")
        requests = []
        for row, source in zip(index["requests"], source_rows, strict=True):
            expected = copy.deepcopy(source)
            expected.update({"request": str(PREPARED / engine / "requests" / f"{source['queue_order']:06d}.json"),
                             "request_sha256": row["request_sha256"], "preparation_failure": None})
            runner.require(row == expected, "prepared row changed beyond base availability/request binding")
            runner.checked_sha(Path(source["request"]), source["request_sha256"], "frozen source request")
            runner.checked_sha(owned(Path(row["request"])), row["request_sha256"], "constructed request")
            before, after = read(Path(source["request"])), read(Path(row["request"]))
            before["base_input"] = plan["inputs"][row["revision_id"]]["path"]
            runner.require(before == after, "request changed beyond base_input")
            runner.checked_request_sources(row, after, row["queue_order"])
            requests.append(after)
        inventory_path = Path(index["inventory"])
        runner.checked_sha(inventory_path, index["inventory_sha256"], "frozen candidate inventory")
        inventory = read(inventory_path)
        hashes = {row["candidate_sha256"] for row in source_rows}
        subset = {**inventory, "rows": [row for row in inventory["rows"]
                                        if row["candidate_sha256"] in hashes]}
        runner.validate_source_bindings(index["requests"], subset, requests)
    return plan


def configure_engine(engine: str) -> None:
    runner.ENGINE = ENGINES[engine]["path"]
    runner.ENGINE_SHA256 = ENGINES[engine]["sha256"]
    runner.MIN_FREE_BYTES = MIN_FREE_BYTES


def output_for(engine: str) -> Path:
    return owned(OUTPUT / f"j-{engine}")


def stats(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "mean": statistics.mean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None, "total": sum(values)}


def projection(plan: dict[str, Any], elapsed_seconds: float) -> dict[str, Any]:
    observed: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    pending: Counter = Counter()
    for engine, entry in plan["indexes"].items():
        state_path = output_for(engine) / "state.json"
        state = read(state_path) if state_path.exists() else {"requests": {}}
        for row in read(Path(entry["path"]))["requests"]:
            key = (engine, row["revision_id"], row["method"])
            event = state["requests"].get(str(row["queue_order"]), {})
            seconds = event.get("wall_seconds")
            if event.get("status") in TERMINAL and isinstance(seconds, (int, float)):
                observed[key].append(seconds)
            else:
                pending[key] += 1
    values = [value for group in observed.values() for value in group]
    overall = statistics.mean(values) if values else None
    remaining = 0.0
    assumptions = []
    for key, count in pending.items():
        own = observed.get(key, [])
        other = [v for k, vs in observed.items() if k[1:] == key[1:] for v in vs]
        sample = own or other or values
        mean = statistics.mean(sample) if sample else None
        if mean is not None:
            remaining += mean * count
        assumptions.append({"engine": key[0], "revision": key[1], "method": key[2],
                            "remaining": count, "sample_count": len(sample),
                            "mean_seconds": mean,
                            "basis": "same_group" if own else "other_engine_same_group" if other else "pooled"})
    return {"observed_requests": len(values), "observed_wall_seconds": stats(values),
            "elapsed_execution_seconds": elapsed_seconds,
            "projected_total_seconds": elapsed_seconds + remaining if overall is not None else None,
            "remaining_requests": sum(pending.values()), "assumptions": assumptions,
            "limitation": "Ordered development requests, not a random sample. Unseen groups/engine "
                          "use observed same-group or pooled means; later costs can differ."}


def checked_event(row: dict[str, Any], event: dict[str, Any], request_dir: Path) -> Path:
    runner.require(event.get("request_sha256") == row["request_sha256"], "resume request SHA changed")
    path = owned(Path(event["result_path"]))
    runner.checked_sha(path, event["result_sha256"], "resume result")
    metrics_path = request_dir / f"attempt-{event['attempt']:04d}.metrics.json"
    runner.checked_sha(metrics_path, event["metrics_sha256"], "resume metrics")
    metrics = read(metrics_path)
    runner.require(all(event.get(key) == metrics.get(key) for key in
                       ("exit_code", "wall_seconds", "max_rss_bytes")), "resume metrics binding differs")
    result = read(path)
    runner.require(result.get("schema") == "zkfdo-lifting-result-v1" and
                   result.get("request_id") == read(Path(row["request"]))["id"] and
                   result.get("request_sha256") == row["request_sha256"] and
                   result.get("candidate_sha256") == row["candidate_sha256"], "resume result binding differs")
    seconds = metrics.get("wall_seconds")
    runner.require(isinstance(seconds, (int, float)) and math.isfinite(seconds) and seconds >= 0,
                   "resume request wall time invalid")
    if event["status"] == "completed":
        runner.require(runner.successful_result_issue(row, metrics, result) is None,
                       "resume completed result invalid")
    else:
        runner.require(result.get("preparation", {}).get("status") not in (None, "ok"),
                       "resume preparation failure invalid")
    return path


def finish_event(row: dict[str, Any], event: dict[str, Any], request_dir: Path) -> dict[str, Any]:
    """Recover the exact saved attempt after a crash between metrics and state writes."""
    attempt = event["attempt"]
    metrics_path = request_dir / f"attempt-{attempt:04d}.metrics.json"
    metrics = read(metrics_path)
    result_path = request_dir / f"attempt-{attempt:04d}" / "result.json"
    result = read(result_path) if result_path.is_file() else None
    issue = (runner.successful_result_issue(row, metrics, result)
             if metrics["exit_code"] == 0 else f"lift_exit_{metrics['exit_code']}")
    preparation_failed = issue == "preparation_not_ok" and isinstance(result, dict) and \
        result.get("preparation", {}).get("status") is not None
    status = "completed" if issue is None else "preparation_failure" if preparation_failed else "failed"
    return {**event, "status": status, "result_path": str(result_path) if result is not None else None,
            "result_sha256": runner.sha256(result_path) if result is not None else None,
            "metrics_path": str(metrics_path), "metrics_sha256": runner.sha256(metrics_path),
            "preparation_failure": result.get("preparation") if preparation_failed else None,
            "failure_reason": issue, **metrics}


def next_attempt(request_dir: Path) -> int:
    if not request_dir.exists():
        return 1
    numbers = [int(match.group(1)) for item in request_dir.iterdir()
               if (match := re.match(r"attempt-(\d{4})(?:\.|$)", item.name))]
    return max(numbers, default=0) + 1


def check_disk(output: Path, cache: Path) -> dict[str, int]:
    free = {"output_free_bytes": runner.disk_free(output), "cache_free_bytes": runner.disk_free(cache)}
    if min(free.values()) < MIN_FREE_BYTES:
        raise runner.DiskGuardStop(f"less than 8 GiB free before next A request: {free}")
    return free


def execute() -> dict[str, Any]:
    plan = validate()
    root_path = OUTPUT / "state.json"
    plan_sha = runner.sha256(PREPARED / "plan.json")
    previous = read(root_path) if root_path.exists() else {}
    runner.require(not previous or previous.get("plan_sha256") == plan_sha, "run plan changed")
    before = previous.get("elapsed_execution_seconds", 0.0)
    started = time.monotonic()
    root_state = {"schema": "n6-a-remeasure-state-v1", "status": "running",
                  "plan_sha256": plan_sha, "started_at": previous.get("started_at", datetime.now(timezone.utc).isoformat()),
                  "elapsed_execution_seconds": before, "min_free_bytes": MIN_FREE_BYTES}
    runner.atomic_json(root_path, root_state)
    try:
        for engine in plan["engine_order"]:
            index_entry = plan["indexes"][engine]
            configure_engine(engine)
            output = output_for(engine)
            cache_root = owned(OUTPUT / "caches" / engine)
            output.mkdir(parents=True, exist_ok=True)
            cache_root.mkdir(parents=True, exist_ok=True)
            state = runner.load_state(output, index_entry["sha256"], cache_root)
            state["status"] = "running"
            probe = runner.probe_time_l()
            state.update({"measurement_method": probe["measurement_method"], "time_probe": probe})
            state_path = output / "state.json"
            runner.atomic_json(state_path, state)
            index = read(Path(index_entry["path"]))
            for scope, ordinal, revision, rows in runner.groups(index["requests"]):
                key = f"{scope}/{ordinal:04d}"
                revision_dir = output / scope / f"{ordinal:04d}"
                revision_dir.mkdir(parents=True, exist_ok=True)
                revision_state = state["revisions"].setdefault(key, {
                    "scope": scope, "revision_ordinal": ordinal, "revision_id": revision,
                    "status": "running", "instance_store": str(revision_dir / "store"),
                    "cache_path": str(cache_root / scope / f"{ordinal:04d}")})
                for row in rows:
                    order = row["queue_order"]
                    request_dir = revision_dir / "requests" / f"{order:06d}"
                    old = state["requests"].get(str(order))
                    if old and old.get("status") == "running" and (
                            request_dir / f"attempt-{old['attempt']:04d}.metrics.json").is_file():
                        runner.require(old.get("request_sha256") == row["request_sha256"],
                                       "interrupted request SHA changed")
                        old = finish_event(row, old, request_dir)
                        old["resumed_result"] = True
                        state["requests"][str(order)] = old
                        runner.append_jsonl(output / "attempts.jsonl", old)
                        runner.atomic_json(state_path, state)
                    if old and old.get("status") in TERMINAL:
                        checked_event(row, old, request_dir)
                        continue
                    estimate = projection(plan, before + time.monotonic() - started)
                    root_state.update({"projection": estimate, "engine": engine, "next_queue_order": order,
                                       "elapsed_execution_seconds": estimate["elapsed_execution_seconds"]})
                    if estimate["elapsed_execution_seconds"] >= MAX_TOTAL_SECONDS or (
                            estimate["observed_requests"] >= PROJECTION_MIN_REQUESTS and
                            estimate["projected_total_seconds"] > MAX_TOTAL_SECONDS):
                        state["status"] = "time_projection_stopped"
                        runner.atomic_json(state_path, state)
                        root_state["status"] = "time_projection_stopped"
                        return root_state
                    runner.atomic_json(root_path, root_state)
                    free = check_disk(output, cache_root)
                    runner.checked_request_sources(row, read(Path(row["request"])), order)
                    cache = runner.initialize_cache(cache_root, scope, ordinal, revision, index_entry["sha256"])
                    revision_state.pop("cleanup", None)
                    attempt = next_attempt(request_dir)
                    attempt_dir = request_dir / f"attempt-{attempt:04d}"
                    event = {"status": "running", "queue_order": order, "scope": scope,
                             "revision_id": revision, "method": row["method"], "request": row["request"],
                             "request_sha256": row["request_sha256"], "attempt": attempt, "disk_before": free}
                    state["requests"][str(order)] = event
                    runner.atomic_json(state_path, state)
                    metrics = runner.run_lift(row, attempt_dir, cache, revision_dir / "store", attempt,
                                              probe["measurement_method"])
                    metrics_path = request_dir / f"attempt-{attempt:04d}.metrics.json"
                    runner.atomic_json(metrics_path, metrics)
                    event = finish_event(row, event, request_dir)
                    state["requests"][str(order)] = event
                    status, issue = event["status"], event["failure_reason"]
                    runner.append_jsonl(output / "attempts.jsonl", event)
                    runner.atomic_json(state_path, state)
                    print(json.dumps({"engine": engine, "queue_order": order, "revision": revision,
                                      "method": row["method"], "status": status,
                                      "wall_seconds": metrics["wall_seconds"],
                                      "max_rss_bytes": metrics["max_rss_bytes"]}), flush=True)
                    runner.require(status != "failed", f"{engine} request {order}: {issue}")
                revision_state["status"] = "completed"
                runner.atomic_json(state_path, state)
                cleanup_caches(engine, state, index_entry["sha256"])
            state["status"] = "completed"
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            runner.atomic_json(state_path, state)
        root_state["status"] = "completed"
        return root_state
    except BaseException as error:
        root_state.update({"status": "stopped", "stop_reason": str(error), "error_class": type(error).__name__})
        raise
    finally:
        root_state["elapsed_execution_seconds"] = before + time.monotonic() - started
        runner.atomic_json(root_path, root_state)
        for engine, entry in plan["indexes"].items():
            state_path = output_for(engine) / "state.json"
            if state_path.exists():
                state = read(state_path)
                if state.get("status") == "running":
                    state["status"] = "stopped"
                cleanup_caches(engine, state, entry["sha256"])


def cleanup_caches(engine: str, state: dict[str, Any], index_sha: str) -> None:
    output = output_for(engine)
    cache_root = owned(OUTPUT / "caches" / engine)
    for revision in state["revisions"].values():
        path = owned(Path(revision["cache_path"]))
        if path.exists():
            revision["cleanup"] = runner.cleanup_revision(
                cache_root, output, revision["scope"], revision["revision_ordinal"],
                revision["revision_id"], index_sha, delete=True)
    runner.atomic_json(output / "state.json", state)


def judgement_flags(result: dict[str, Any], effective: dict[tuple[str, str], str]) -> tuple[bool, bool]:
    """Same L1 and excluded flags as n6_b6h_result_gate.py; no B data access."""
    request_id, classes = result.get("request_id"), result.get("classes")
    runner.require(isinstance(request_id, str) and isinstance(classes, list), "result classes invalid")
    l1 = excluded = False
    for item in classes:
        runner.require(isinstance(item, dict) and isinstance(item.get("representative"), str),
                       "result representative missing")
        own = item.get("verdict")
        joined = effective.get((request_id, item["representative"]))
        l1 |= own == "entrypoint_violation" or joined == "assumption_violation_reachable"
        excluded |= own == "excluded_in_context" or joined == "assumption_excluded_in_context"
    return l1, excluded and not l1


def aggregate() -> dict[str, Any]:
    plan = validate()
    rows_out = []
    joins = []
    for engine, entry in plan["indexes"].items():
        configure_engine(engine)
        output = output_for(engine)
        state_path = output / "state.json"
        state = read(state_path) if state_path.exists() else {"requests": {}}
        index = read(Path(entry["path"]))
        results = {}
        effective = {}
        for scope, ordinal, revision, rows in runner.groups(index["requests"]):
            paths = []
            for row in rows:
                event = state["requests"].get(str(row["queue_order"]), {})
                if event.get("status") in TERMINAL:
                    directory = output / scope / f"{ordinal:04d}" / "requests" / f"{row['queue_order']:06d}"
                    path = checked_event(row, event, directory)
                    if event["status"] == "completed":
                        paths.append(path)
                        results[row["queue_order"]] = read(path)
            if not paths:
                continue
            fingerprint = hashlib.sha256(json.dumps([(str(p), runner.sha256(p)) for p in paths]).encode()).hexdigest()
            join_path = owned(OUTPUT / "aggregates" / "joins" / f"{engine}-{scope}-{ordinal:04d}-{fingerprint}.json")
            join_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path = join_path.with_suffix(".receipt.json")
            metrics_path = join_path.with_suffix(".metrics.json")
            if not join_path.exists():
                metrics = runner.join_instances(paths, output, join_path, runner.probe_time_l()["measurement_method"])
                write_fixed(metrics_path, metrics)
                runner.require(metrics["exit_code"] == 0, "lift-instances failed")
                write_fixed(receipt_path, {"engine_sha256": ENGINES[engine]["sha256"],
                                          "inputs_fingerprint": fingerprint,
                                          "join_sha256": runner.sha256(join_path),
                                          "metrics_sha256": runner.sha256(metrics_path)})
            receipt = read(receipt_path)
            runner.require(receipt.get("engine_sha256") == ENGINES[engine]["sha256"] and
                           receipt.get("inputs_fingerprint") == fingerprint,
                           "saved join receipt binding invalid")
            runner.checked_sha(join_path, receipt["join_sha256"], "saved instance join")
            runner.checked_sha(metrics_path, receipt["metrics_sha256"], "saved instance join metrics")
            joined = read(join_path)
            runner.require(joined.get("schema") == "zkfdo-instance-verdicts-v1" and
                           joined.get("results") == [str(p.relative_to(output)) for p in paths] and
                           joined.get("conflicts") == 0, "joined result binding/conflict invalid")
            for item in joined["classes"]:
                key = (item["request_id"], item["representative"])
                runner.require(key not in effective, "duplicate joined class")
                effective[key] = item["effective"]
            joins.append({"engine": engine, "revision": revision, "path": str(join_path),
                          "sha256": runner.sha256(join_path), "result_count": len(paths)})
        for revision in REVISIONS:
            for method in ("W", "S"):
                selected_rows = [r for r in index["requests"] if r["revision_id"] == revision and r["method"] == method]
                counts = Counter()
                times = []
                for row in selected_rows:
                    event = state["requests"].get(str(row["queue_order"]), {})
                    status = event.get("status", "not_run")
                    counts[status] += 1
                    seconds = event.get("wall_seconds")
                    if isinstance(seconds, (int, float)) and math.isfinite(seconds):
                        times.append(seconds)
                    if status == "completed":
                        l1, excluded = judgement_flags(results[row["queue_order"]], effective)
                        counts["L1" if l1 else "excluded" if excluded else "unknown"] += 1
                rows_out.append({"engine": engine, "revision": revision, "method": method,
                                 "requests": len(selected_rows), **{key: counts[key] for key in
                                    ("completed", "preparation_failure", "failed", "running", "not_run",
                                     "L1", "excluded", "unknown")}, "wall_seconds": stats(times)})
    result = {"schema": "n6-a-remeasure-banyan-aggregate-v1", "layer": "A_constructed_base_input",
              "plan_sha256": runner.sha256(PREPARED / "plan.json"), "rows": rows_out,
              "joins": joins, "classification": plan["classification"],
              "timing_scope": "Recorded final request attempts (completed, preparation failure, or failed); "
                              "join/validation/cleanup excluded. Root elapsed includes execution overhead.",
              "execution": read(OUTPUT / "state.json") if (OUTPUT / "state.json").exists() else None}
    folder = OUTPUT / "aggregates"
    folder.mkdir(parents=True, exist_ok=True)
    serial = 1
    while (folder / f"aggregate-{serial:04d}.json").exists():
        serial += 1
    path = folder / f"aggregate-{serial:04d}.json"
    write_fixed(path, result)
    return {"status": "aggregated", "path": str(path), "sha256": runner.sha256(path), "rows": rows_out}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("prepare", "validate-only", "execute", "aggregate"), required=True)
    args = parser.parse_args()
    try:
        runner.require(OUTPUT.resolve() == OUTPUT and not OUTPUT.is_symlink(), "unsafe output root")
        OUTPUT.mkdir(parents=True, exist_ok=True)
        with (OUTPUT / ".runner.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == "prepare":
                result = prepare()
            elif args.action == "validate-only":
                plan = validate()
                result = {"status": "valid", "indexes": plan["indexes"]}
            elif args.action == "execute":
                result = execute()
            else:
                result = aggregate()
            print(json.dumps(result, sort_keys=True, ensure_ascii=False))
            return 3 if result.get("status") == "time_projection_stopped" else 0
    except (OSError, ValueError, runner.RunnerError) as error:
        print(f"A remeasurement stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
