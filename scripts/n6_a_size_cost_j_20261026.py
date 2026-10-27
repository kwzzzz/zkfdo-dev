#!/usr/bin/env python3
"""Summarize saved main-scope A J results without running a judging engine.

The caller supplies verified indexes, states, joins and the frozen location
mapping. Only completed result receipts are opened, through the caller's
guarded/hash-checking JSON reader. This module has no command-line action.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from pathlib import Path
import statistics
from typing import Any, Callable

import n6_light_rqc_20261026 as rqc


REACH = "assumption_violation_reachable"
EXCLUDED = "assumption_excluded_in_context"
COUNTS = ("L1_requests", "bug_location_L1_requests", "other_L1_requests",
          "unassigned_L1_requests", "ambiguous_location_L1_requests",
          "excluded_requests", "unknown_requests")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _stats(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "sum": math.fsum(values) if values else None,
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None}


def _group() -> dict[str, Any]:
    return {"requests": 0, "statuses": Counter(), "counts": Counter(),
            "request_times": [], "attempt_times": [], "completed_times": [],
            "attempts_without_time": 0, "untimed_requests": 0,
            "partial_timing_requests": 0, "results": [], "join_keys": set()}


def _duration(event: dict[str, Any]) -> float | None:
    value = event.get("wall_seconds")
    if value is None:
        return None
    _require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
             "invalid recorded request wall time")
    return float(value)


def _timings(event: dict[str, Any] | None, group: dict[str, Any]) -> None:
    if event is None:
        group["untimed_requests"] += 1
        return
    attempts = [*event.get("history", []), event]
    seen = set()
    times = []
    missing = 0
    for attempt in attempts:
        number = attempt.get("attempt")
        if number is not None:
            _require(number not in seen, "duplicate attempt in request history")
            seen.add(number)
        duration = _duration(attempt)
        if duration is None:
            missing += 1
        else:
            times.append(duration)
    group["attempts_without_time"] += missing
    if times:
        group["request_times"].append(math.fsum(times))
        group["attempt_times"].extend(times)
        group["partial_timing_requests"] += int(missing > 0)
    else:
        group["untimed_requests"] += 1
    if event.get("status") == "completed" and (duration := _duration(event)) is not None:
        group["completed_times"].append(duration)


def _joined(join: dict[str, Any]) -> tuple[dict, dict]:
    _require(join.get("schema") == "zkfdo-instance-verdicts-v1" and
             join.get("conflicts") == 0, "invalid saved join schema/conflicts")
    instances = {}
    classes = {}
    for item in join.get("instances", []):
        _require(item["instance"] not in instances, "duplicate joined instance")
        instances[item["instance"]] = item
    for item in join.get("classes", []):
        key = (item["request_id"], item["representative"])
        _require(key not in classes, "duplicate joined request/class")
        classes[key] = item["effective"]
    return instances, classes


def _classify(result: dict[str, Any], mappings: list[dict[str, Any]],
              instances: dict, effective: dict) -> dict[str, int]:
    """Keep saved A request precedence; location flags describe L1 separately."""
    l1 = excluded = bug_l1 = other_l1 = ambiguous_l1 = False
    roots = {root for mapping in mappings for root in mapping["instance_paths"]}
    entry_key = ":".join(result.get("entrypoint", {}).get(key, "") for key in
                         ("r1cs_sha256", "sym_sha256", "o0_r1cs_sha256"))
    classes = result.get("classes")
    _require(isinstance(classes, list), "missing result classes")
    for item in classes:
        representative = item.get("representative")
        _require(isinstance(representative, str), "missing result representative")
        joined = effective.get((result["request_id"], representative))
        own = item.get("verdict")
        l1 |= own == "entrypoint_violation" or joined == REACH
        excluded |= own == "excluded_in_context" or joined == EXCLUDED
        if roots and own == "entrypoint_violation":
            other_l1 |= not any(rqc.under(representative, root) for root in roots)
        for predicate in item.get("predicates", []):
            instance = instances.get(predicate["instance"])
            _require(instance is not None and instance.get("entry_key") == entry_key,
                     "predicate missing from join or entrypoint hash differs")
            _require(joined is not None, "predicate class missing from saved join")
            if roots and instance["verdict"] == REACH:
                other_l1 |= not any(rqc.under(predicate["instance"], root) for root in roots)
        for _, observation in rqc.attribute_class(item, mappings, instances):
            if observation["status"] == "L1":
                if observation["ambiguous_bug_ids"]:
                    ambiguous_l1 = True
                else:
                    bug_l1 = True
    _require(not (bug_l1 or other_l1 or ambiguous_l1) or l1,
             "location attribution conflicts with saved class join")
    return {"L1_requests": int(l1), "bug_location_L1_requests": int(bug_l1),
            "other_L1_requests": int(other_l1),
            "unassigned_L1_requests": int(l1 and not roots),
            "ambiguous_location_L1_requests": int(ambiguous_l1),
            "excluded_requests": int(excluded and not l1),
            "unknown_requests": int(not l1 and not excluded)}


def _finish(group: dict[str, Any]) -> dict[str, Any]:
    return {"requests": group["requests"], "statuses": dict(sorted(group["statuses"].items())),
            **{key: group["counts"][key] for key in COUNTS},
            "wall_seconds": {**_stats(group["request_times"]),
                "unit": "per-request sum of all recorded attempts, including failed history",
                "untimed_requests": group["untimed_requests"],
                "partially_timed_requests": group["partial_timing_requests"]},
            "attempt_wall_seconds": {**_stats(group["attempt_times"]),
                                     "attempts_without_time": group["attempts_without_time"]},
            "completed_final_wall_seconds": _stats(group["completed_times"]),
            "workspace_peak_bytes": None,
            "workspace_peak_reason": "no explicit per-request workspace peak measurement in these states",
            "result_sources": group["results"],
            "join_keys": [list(key) for key in sorted(group["join_keys"])]}


def summarize_j(index: dict[str, Any], state: dict[str, Any],
                joins: dict[tuple[str, str], dict[str, Any]], mapping: dict[str, Any],
                read_json_callable: Callable[[Path, str], dict[str, Any]], *,
                layer: str, engine: str) -> dict[str, Any]:
    """Return main-only revision/method rows and totals from saved A records.

    The reader must enforce allowed paths, sufficient free space and expected
    SHA. The caller verifies index/state/join provenance and resolves each
    join's result path set relative to the source state directory. An optional
    ``_resolved_result_paths`` list on a join enables that coverage check here.
    No request, candidate, input, witness or workspace files are opened.
    """
    _require(layer in {"strict", "exploratory"}, "unknown reporting layer")
    _require(engine in {"v1", "v2.2"}, "unknown J engine")
    _require(not str(state.get("schema", "")).startswith("n6-a-remeasure-aq-"),
             "aq snapshots are outside this helper's scope")
    rows = index["requests"]
    _require(index.get("request_count") == len(rows), "index request count differs")
    _require(len({row["queue_order"] for row in rows}) == len(rows), "duplicate index queue order")
    _require(set(state["requests"]) <= {str(row["queue_order"]) for row in rows},
             "saved requests outside index")
    _require(index.get("engine_sha256") == state.get("engine_sha256"), "engine binding differs")
    mapped = {revision["revision_id"]: revision for revision in mapping["revisions"]}
    prepared_joins = {key: _joined(value) for key, value in joins.items() if key[0] == "main"}
    groups = {}
    completed_paths = defaultdict(set)
    all_paths = set()
    for row in rows:
        if row["scope"] != "main":
            continue
        revision, method = row["revision_id"], row["method"]
        _require(method in {"W", "S"}, "unknown method")
        # Keep a zero-request counterpart; absence of candidates is not unknown.
        for candidate_method in ("W", "S"):
            groups.setdefault((revision, candidate_method), _group())
        group = groups[(revision, method)]
        group["requests"] += 1
        event = state["requests"].get(str(row["queue_order"]))
        status = event.get("status", "not_run") if event else "not_run"
        group["statuses"][status] += 1
        _timings(event, group)
        revision_mapping = mapped.get(revision)
        if revision_mapping:
            _require(row.get("entrypoint_sha256") == revision_mapping["entrypoint_sha256"],
                     "index entrypoint differs from frozen location mapping")
        if status != "completed":
            continue
        _require(event["request_sha256"] == row["request_sha256"], "saved request binding differs")
        path = Path(event["result_path"])
        _require(path.is_absolute() and "aq-exec" not in path.parts,
                 "result path is outside this helper's scope")
        _require(str(path) not in all_paths, "same result reused for multiple requests")
        all_paths.add(str(path))
        result = read_json_callable(path, event["result_sha256"])
        _require(result.get("schema") == "zkfdo-lifting-result-v1" and
                 result.get("request_sha256") == row["request_sha256"] and
                 isinstance(result.get("request_id"), str), "result request identity differs")
        key = ("main", revision)
        completed_paths[key].add(str(path))
        instances, effective = prepared_joins.get(key, ({}, {}))
        group["counts"].update(_classify(result,
            revision_mapping["items"] if revision_mapping else [], instances, effective))
        group["results"].append({"path": str(path), "sha256": event["result_sha256"],
                                  "queue_order": row["queue_order"]})
        if key in joins:
            group["join_keys"].add(key)
    for key, join in joins.items():
        if key[0] != "main":
            continue
        _require(len(join["results"]) == len(completed_paths[key]), "saved join result count differs")
        if "_resolved_result_paths" in join:
            _require(set(join["_resolved_result_paths"]) == completed_paths[key],
                     "saved join result path coverage differs")
    total = _group()
    output = []
    for (revision, method), group in sorted(groups.items()):
        output.append({"layer": layer, "engine": engine, "scope": "main",
                       "revision_id": revision, "method": method, **_finish(group)})
        for key in ("requests", "untimed_requests", "partial_timing_requests", "attempts_without_time"):
            total[key] += group[key]
        for key in ("statuses", "counts"):
            total[key].update(group[key])
        for key in ("request_times", "attempt_times", "completed_times", "results"):
            total[key].extend(group[key])
        total["join_keys"].update(group["join_keys"])
    return {"schema": "n6-a-size-cost-j-v1", "layer": layer, "engine": engine,
            "revision_methods": output, "totals": _finish(total),
            "supplemental_requests_excluded": sum(row["scope"] != "main" for row in rows),
            "definitions": {
                "classification": "Any own entrypoint violation or joined reachable class is L1; "
                    "otherwise any own/joined exclusion is excluded; remaining completed requests are unknown.",
                "L1_location_flags": "Bug-location means an unambiguous frozen mapped observation; other means "
                    "an observed L1 outside available mapped roots. These flags may overlap. With no mapping, "
                    "L1 is unassigned, never automatically other. Ambiguous mapped L1 stays separate.",
                "unit": "requests, not unique bugs; main only; W and S kept separate",
                "timing": "Recorded durations only; no zero imputation. Request sums include failed/history "
                    "attempts. Completed-final durations are also reported separately. Input validation, "
                    "joins, cleanup, fuzzing and human work are not included unless recorded in an attempt.",
                "disk": "Workspace peak is unavailable; RSS, current directory size and cache deletion bytes "
                    "are not substitutes.",
                "provenance": "Caller verifies supplied state/index/join/mapping receipts; result receipts "
                    "are read through caller callback. Join path-set checks need _resolved_result_paths."}}
