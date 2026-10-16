#!/usr/bin/env python3
"""Summarize J verdict metadata; never read counterexample values."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MAIN_QUEUE = ROOT / "runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json"
MEM20_QUEUE = ROOT / "runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json"
RQ_C_MAP = ROOT / "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json"
REACHABLE = "assumption_violation_reachable"


class SummaryError(RuntimeError):
    """A summary cannot be trusted because source metadata is inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SummaryError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, expected_sha: str | None = None) -> dict[str, Any]:
    require(path.is_file(), f"missing JSON: {path}")
    if expected_sha is not None:
        require(sha256_file(path) == expected_sha, f"SHA-256 mismatch: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def source_path(path_text: str, root: Path = ROOT) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else root / path


def instance_under_representative(instance: str, representative: str) -> bool:
    return (instance == representative or instance.startswith(representative + ".")
            or instance.startswith(representative + "["))


def result_classes(result: dict[str, Any],
                   effective: dict[tuple[str, str], dict[str, Any]] | None,
                   instances: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], bool | None, list[str]]:
    classes = result.get("classes")
    require(isinstance(classes, list), "result classes missing")
    request_id = result.get("request_id")
    require(isinstance(request_id, str), "result request_id missing")
    rows: list[dict[str, Any]] = []
    seen_representatives: set[str] = set()
    reach_inputs: set[str] = set()
    own_violation = False
    effective_reach = False
    for entry in classes:
        representative = entry.get("representative")
        require(isinstance(representative, str) and representative not in seen_representatives,
                "duplicate or missing class representative")
        seen_representatives.add(representative)
        own = entry.get("verdict")
        require(isinstance(own, str), "class verdict missing")
        joined = effective.get((request_id, representative)) if effective is not None else None
        if effective is not None and entry.get("assumption_predicate_verdict") is not None:
            require(joined is not None, f"predicate class absent from instance join: {request_id}/{representative}")
        effective_verdict = joined.get("effective") if joined is not None else None
        if joined is not None:
            require(isinstance(effective_verdict, str), "effective verdict missing")
        own_violation |= own == "entrypoint_violation"
        effective_reach |= effective_verdict == REACHABLE
        for predicate in entry.get("predicates") or []:
            if predicate.get("verdict") == REACHABLE:
                classification = (predicate.get("reach_inputs") or {}).get("classification")
                if isinstance(classification, str):
                    reach_inputs.add(classification)
        if effective_verdict == REACHABLE:
            for instance in instances or []:
                name = instance.get("instance")
                classification = instance.get("reach_classification")
                if (isinstance(name, str) and isinstance(classification, str)
                        and instance.get("verdict") == REACHABLE
                        and instance_under_representative(name, representative)):
                    reach_inputs.add(classification)
        rows.append({"representative": representative, "self_verdict": own,
                     "self_assumption_verdict": entry.get("assumption_predicate_verdict"),
                     "effective_verdict": effective_verdict,
                     "target_basis": joined.get("target_basis") if joined is not None else None})
    if own_violation:
        l1: bool | None = True
    elif effective is None:
        l1 = None
    else:
        l1 = effective_reach
    return rows, l1, sorted(reach_inputs)


def cost_fields(result: dict[str, Any]) -> dict[str, int | float]:
    steps = (result.get("costs") or {}).get("steps") or []
    require(isinstance(steps, list), "cost steps malformed")
    return {
        "compile_seconds": sum(float(step.get("seconds", 0)) for step in steps
                               if step.get("stage") == "compile"),
        "compile_cache_hits": sum(bool(step.get("cached")) for step in steps
                                  if step.get("stage") == "compile"),
        "instance_store_hits": sum(step.get("label") == "instance store hit" for step in steps),
    }


def load_revisions(run_output: Path, state: dict[str, Any]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    revision_state: dict[tuple[str, str], dict[str, Any]] = {}
    joins: dict[tuple[str, str], dict[str, Any]] = {}
    for key, row in (state.get("revisions") or {}).items():
        scope = key.split("/", 1)[0]
        revision_id = row.get("revision_id")
        require(scope in {"main", "mem20"} and isinstance(revision_id, str),
                f"invalid revision state key: {key}")
        pair = (scope, revision_id)
        require(pair not in revision_state, f"duplicate revision state: {pair}")
        revision_state[pair] = row
        instance_path = row.get("instances_path")
        if instance_path is None:
            require(row.get("instances_sha256") is None, f"instance SHA without path: {pair}")
            if row.get("status") == "no_results":
                require(row.get("result_count") == 0, f"no_results revision has results: {pair}")
            continue
        require(row.get("status") == "joined", f"instance path on unjoined revision: {pair}")
        path = source_path(instance_path).resolve()
        require(path.is_relative_to(run_output), f"instances outside run output: {path}")
        joined = read_json(path, row.get("instances_sha256"))
        require(joined.get("schema") == "zkfdo-instance-verdicts-v1",
                f"unexpected instance schema: {path}")
        conflicts = joined.get("conflicts")
        require(type(conflicts) is int and conflicts == 0,
                f"instance join conflict or missing conflict count: {path}")
        classes = joined.get("classes")
        instances = joined.get("instances")
        result_names = joined.get("results")
        require(isinstance(classes, list) and isinstance(instances, list)
                and isinstance(result_names, list),
                f"malformed instance join: {path}")
        result_paths: set[str] = set()
        for result_name in result_names:
            require(isinstance(result_name, str), f"invalid joined result path: {path}")
            result_path = (run_output / result_name).resolve()
            require(result_path.is_relative_to(run_output), f"joined result outside run: {result_name}")
            require(str(result_path) not in result_paths, f"duplicate joined result: {result_name}")
            result_paths.add(str(result_path))
        class_lookup: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in classes:
            class_key = (entry["request_id"], entry["representative"])
            require(class_key not in class_lookup, f"duplicate joined class: {path}")
            class_lookup[class_key] = entry
        joins[pair] = {"classes": class_lookup, "instances": instances, "path": str(path),
                       "sha256": row["instances_sha256"], "result_paths": result_paths}
    return revision_state, joins


def summarize_request(index_row: dict[str, Any], state_row: dict[str, Any] | None,
                      join: dict[str, Any] | None, run_output: Path) -> dict[str, Any]:
    scope, revision_id = index_row["scope"], index_row["revision_id"]
    row = {key: index_row.get(key) for key in (
        "scope", "revision_id", "unit_id", "queue_order", "seed", "method", "attempt_number",
        "candidate_index", "completion_offset_seconds", "target_id", "original_target_id",
        "candidate_path", "candidate_sha256", "request", "request_sha256")}
    row.update({"status": "pending", "self_verdicts": [], "effective_verdicts": [],
                "classes": [], "reach_inputs": [], "l1": None, "l1_time_seconds": None,
                "planned_preparation_failure": index_row.get("preparation_failure"),
                "preparation_failure": None,
                "result_path": None, "result_sha256": None,
                "wall_seconds": None, "max_rss_bytes": None,
                "compile_seconds": 0.0, "compile_cache_hits": 0,
                "instance_store_hits": 0})
    if state_row is None:
        return row
    status = state_row.get("status")
    row["status"] = status
    row["wall_seconds"] = state_row.get("wall_seconds")
    row["max_rss_bytes"] = state_row.get("max_rss_bytes")
    if state_row.get("request_sha256") is not None:
        require(state_row["request_sha256"] == index_row["request_sha256"],
                f"request SHA mismatch at queue order {index_row['queue_order']}")
    if status == "preparation_failure":
        require(state_row.get("result_path") is None, "preparation failure has result path")
        reason = state_row.get("preparation_failure") or row["planned_preparation_failure"]
        require(isinstance(reason, str) and bool(reason), "preparation failure reason missing")
        row["preparation_failure"] = reason
        row["self_verdicts"] = ["preparation_failure"]
        row["effective_verdicts"] = ["preparation_failure"]
        row["l1"] = False
        return row
    if status != "completed":
        return row
    require(row["planned_preparation_failure"] is None,
            "completed result contradicts planned preparation failure")
    path_text = state_row.get("result_path")
    require(isinstance(path_text, str), "completed request has no result path")
    result_path = source_path(path_text).resolve()
    require(result_path.is_relative_to(run_output), f"result outside run output: {result_path}")
    result_sha = state_row.get("result_sha256")
    require(isinstance(result_sha, str), "completed request has no result SHA")
    result = read_json(result_path, result_sha)
    require(result.get("schema") == "zkfdo-lifting-result-v1", f"unexpected result schema: {result_path}")
    require(result.get("request_sha256") == index_row["request_sha256"]
            and result.get("candidate_sha256") == index_row["candidate_sha256"],
            f"result request/candidate SHA mismatch: {result_path}")
    preparation = result.get("preparation") or {}
    if preparation.get("status") != "ok":
        row["preparation_failure"] = preparation.get("reason") or "unknown"
        row["self_verdicts"] = ["preparation_failure"]
        row["effective_verdicts"] = ["preparation_failure"]
        row["l1"] = False
    else:
        classes, l1, reach_inputs = result_classes(
            result, join["classes"] if join else None,
            join["instances"] if join else None)
        row["classes"] = classes
        row["self_verdicts"] = sorted({entry["self_verdict"] for entry in classes})
        row["effective_verdicts"] = sorted({entry["effective_verdict"] for entry in classes
                                            if entry["effective_verdict"] is not None})
        row["reach_inputs"] = reach_inputs
        row["l1"] = l1
        if l1 is True:
            row["l1_time_seconds"] = index_row["completion_offset_seconds"]
        if join is None:
            row["status"] = "pending_instance_join"
    row["result_path"] = str(result_path)
    row["result_sha256"] = result_sha
    row.update(cost_fields(result))
    return row


def unit_rows(candidates: list[dict[str, Any]], main_queue: dict[str, Any],
              mem20_queue: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[(candidate["scope"], candidate["unit_id"], candidate["method"])].append(candidate)
    units: list[dict[str, Any]] = []
    for scope, queue in (("main", main_queue), ("mem20", mem20_queue)):
        for unit in queue["units"]:
            for method in ("W", "S"):
                entries = grouped.get((scope, unit["unit_id"], method), [])
                complete = all(e["l1"] is not None and e["status"] in
                               {"completed", "preparation_failure"} for e in entries)
                l1_times = [e["l1_time_seconds"] for e in entries if e["l1"] is True]
                own_counts = Counter(v for e in entries for v in e["self_verdicts"])
                effective_counts = Counter(v for e in entries for v in e["effective_verdicts"])
                failures = Counter(e["preparation_failure"] for e in entries
                                   if e["preparation_failure"])
                units.append({"scope": scope, "identifier": unit["identifier"],
                              "unit_id": unit["unit_id"], "seed": unit["seed"],
                              "method": method, "status": "complete" if complete else "partial",
                              "candidate_count": len(entries),
                              "first_l1_seconds": (min(l1_times) if l1_times else 600.0) if complete else None,
                              "censored_at_600_seconds": complete and not l1_times,
                              "l1_count": sum(e["l1"] is True for e in entries),
                              "self_verdict_counts": dict(sorted(own_counts.items())),
                              "effective_verdict_counts": dict(sorted(effective_counts.items())),
                              "preparation_failure_counts": dict(sorted(failures.items()))})
    known = {(u["scope"], u["unit_id"], u["method"]) for u in units}
    require(set(grouped) <= known, "request index references unit outside queues")
    return units


def k5a_rows(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: dict[tuple[str, str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in units:
        if row["scope"] == "main":
            pairs[(row["identifier"], row["unit_id"], row["seed"])][row["method"]] = row
    output = []
    for (identifier, unit_id, seed), methods in pairs.items():
        require(set(methods) == {"W", "S"}, f"missing K5a method: {unit_id}")
        w, s = methods["W"], methods["S"]
        complete = w["status"] == s["status"] == "complete"
        w_l1, s_l1 = w["l1_count"] > 0, s["l1_count"] > 0
        output.append({"identifier": identifier, "unit_id": unit_id, "seed": seed,
                       "status": "complete" if complete else "partial",
                       "r_s_plus_j_only_l1": s_l1 and not w_l1 if complete else None,
                       "l_w_only_l1": w_l1 and not s_l1 if complete else None})
    return output


def rq_c_rows(preparation: dict[str, Any], targets: dict[str, Any],
              mapping: dict[str, Any],
              selected_identifiers: set[str], joins: dict[tuple[str, str], dict[str, Any]],
              revision_state: dict[tuple[str, str], dict[str, Any]],
              request_counts: Counter[tuple[str, str]]) -> list[dict[str, Any]]:
    mapped: dict[tuple[str, str], dict[str, Any]] = {}
    for revision in mapping["revisions"]:
        revision_id = revision["revision_id"]
        for item in revision["items"]:
            key = (revision_id, item["item_id"])
            require(key not in mapped, f"duplicate RQ-C mapping: {key}")
            require(item.get("status") in {"mapped", "partial_mapping", "unresolved_mapping"},
                    f"invalid RQ-C mapping status: {key}")
            paths = item["instance_paths"]
            require(isinstance(paths, list) and all(isinstance(path, str) and
                    (path == "main" or path.startswith("main.")) for path in paths)
                    and len(paths) == len(set(paths)), f"invalid RQ-C paths: {key}")
            mapped[key] = {**item, "mapping_basis": revision.get("mapping_basis")}
    prep_by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in preparation["aq_stage1_units"]:
        if row["unit_id"] in selected_identifiers:
            for item_id in row["item_ids"]:
                prep_by_item[item_id].append(row)
    output = []
    for item in targets["items"]:
        item_id = item["id"]
        function = (item.get("location") or {}).get("Function")
        function = function if isinstance(function, str) else ""
        revisions = []
        for prep in prep_by_item.get(item_id, []):
            revision_id = prep["unit_id"]
            mapping_row = mapped.get((revision_id, item_id))
            mapping_status = mapping_row.get("status") if mapping_row else "unresolved_mapping"
            paths = mapping_row["instance_paths"] if mapping_row else []
            join = joins.get(("main", revision_id))
            state = revision_state.get(("main", revision_id))
            instances = []
            if join is not None:
                for instance in join["instances"]:
                    name = instance.get("instance")
                    if (isinstance(name, str) and
                            any(instance_under_representative(name, path) for path in paths)):
                        instances.append({"instance": name, "entry_key": instance.get("entry_key"),
                                          "verdict": instance.get("verdict"),
                                          "reach_classification": instance.get("reach_classification")})
            no_results = ((state is not None and state.get("status") == "no_results")
                          or request_counts[("main", revision_id)] == 0)
            observed_reach = any(x["verdict"] == REACHABLE for x in instances)
            reached = True if observed_reach else None
            if mapping_row is None or mapping_status == "unresolved_mapping":
                unresolved_reason = "template_instance_mapping_missing"
            elif join is None:
                unresolved_reason = "instance_join_incomplete"
            elif not instances:
                unresolved_reason = "no_joined_predicate_target_in_mapped_instances"
            elif not observed_reach:
                unresolved_reason = "no_reachable_joined_predicate_target_observed"
            else:
                unresolved_reason = None
            revisions.append({"revision_id": revision_id, "revision_kind": prep["revision_kind"],
                              "join_status": "joined" if join is not None else
                              "no_results" if no_results else "pending_join",
                              "instances": instances, "matched_instance_count": len(instances),
                              "mapping_status": mapping_status,
                              "mapping_basis": mapping_row.get("mapping_basis") if mapping_row else None,
                              "mapped_instance_count": len(paths),
                              "missing_templates": mapping_row.get("missing_templates") if mapping_row else [],
                              "unresolved_reason": unresolved_reason,
                              "observed_reach": observed_reach if join is not None and paths else None,
                              "reach": reached,
                              "enumeration_scope": "joined_predicate_targets",
                              "coverage_limitation": "join enumerates predicate targets from submitted candidates, not every entrypoint instance",
                              "leave_one_out": prep.get("leave_one_out") is not None})
        vulnerable = [r for r in revisions if r["revision_kind"] == "vulnerable"]
        fixed = [r for r in revisions if r["revision_kind"] == "fixed"]
        loo = [r for r in revisions if r["revision_kind"] == "leave_one_out"]
        fix_reach = True if any(r["reach"] is True for r in fixed) else None
        output.append({"item_id": item_id, "location_function": function,
                       "selected_for_j": bool(revisions), "revisions": revisions,
                       "enumeration_scope": "joined_predicate_targets",
                       "pair": {"vulnerable_revision_ids": [r["revision_id"] for r in vulnerable],
                                "fixed_revision_ids": [r["revision_id"] for r in fixed],
                                "vulnerable_reach": True if any(r["reach"] is True for r in vulnerable) else None,
                                "fixed_reach": fix_reach},
                       "fix_reach": fix_reach,
                       "leave_one_out_revision_ids": [r["revision_id"] for r in loo]})
    return output


def mem20_comparison(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    main = {(u["unit_id"], u["method"]): u for u in units if u["scope"] == "main"}
    output = []
    for supplemental in units:
        if supplemental["scope"] != "mem20":
            continue
        primary = main[(supplemental["unit_id"], supplemental["method"])]
        complete = primary["status"] == supplemental["status"] == "complete"
        output.append({"unit_id": supplemental["unit_id"], "identifier": supplemental["identifier"],
                       "seed": supplemental["seed"], "method": supplemental["method"],
                       "status": "complete" if complete else "partial",
                       "main_first_l1_seconds": primary["first_l1_seconds"],
                       "mem20_first_l1_seconds": supplemental["first_l1_seconds"],
                       "main_candidate_count": primary["candidate_count"],
                       "mem20_candidate_count": supplemental["candidate_count"],
                       "main_self_verdict_counts": primary["self_verdict_counts"],
                       "mem20_self_verdict_counts": supplemental["self_verdict_counts"],
                       "main_effective_verdict_counts": primary["effective_verdict_counts"],
                       "mem20_effective_verdict_counts": supplemental["effective_verdict_counts"],
                       "main_preparation_failure_counts": primary["preparation_failure_counts"],
                       "mem20_preparation_failure_counts": supplemental["preparation_failure_counts"],
                       "verdict_counts_changed": (primary["self_verdict_counts"] != supplemental["self_verdict_counts"]
                                                  or primary["effective_verdict_counts"] !=
                                                  supplemental["effective_verdict_counts"])
                       if complete else None,
                       "l1_changed": ((primary["l1_count"] > 0) != (supplemental["l1_count"] > 0))
                       if complete else None})
    return output


def build_summary(index_path: Path, run_output: Path, preparation_path: Path,
                  targets_path: Path, main_queue_path: Path = MAIN_QUEUE,
                  mem20_queue_path: Path = MEM20_QUEUE,
                  rq_c_map_path: Path = RQ_C_MAP,
                  require_complete: bool = False) -> dict[str, Any]:
    index_path = index_path.resolve()
    run_output = run_output.resolve()
    preparation_path = preparation_path.resolve()
    targets_path = targets_path.resolve()
    main_queue_path = main_queue_path.resolve()
    mem20_queue_path = mem20_queue_path.resolve()
    rq_c_map_path = rq_c_map_path.resolve()
    index = read_json(index_path)
    state = read_json(run_output / "state.json")
    preparation = read_json(preparation_path)
    targets = read_json(targets_path)
    main_queue = read_json(main_queue_path)
    mem20_queue = read_json(mem20_queue_path)
    rq_c_map = read_json(rq_c_map_path)
    require(rq_c_map.get("status") == "verified"
            and rq_c_map.get("mapping_scope") == "selected_aq_revisions"
            and rq_c_map.get("preparation_units_sha256") == sha256_file(preparation_path)
            and rq_c_map.get("targets_sha256") == sha256_file(targets_path),
            "RQ-C template mapping source mismatch")
    requests = index.get("requests")
    require(isinstance(requests, list) and index.get("request_count") == len(requests),
            "request index count mismatch")
    inventory_path = index.get("inventory")
    if inventory_path is not None:
        inventory = read_json(source_path(inventory_path), index.get("inventory_sha256"))
        inventory_rows = inventory.get("rows")
        require(isinstance(inventory_rows, list) and len(inventory_rows) == len(requests),
                "request index does not cover the candidate inventory")
        require({row["candidate_sha256"] for row in inventory_rows}
                == {row["candidate_sha256"] for row in requests},
                "request index candidate SHA set differs from inventory")
    base_index_path = index.get("base_index")
    if base_index_path is not None:
        base_index = read_json(source_path(base_index_path), index.get("base_index_sha256"))
        require(base_index.get("revision_manifest_sha256") == rq_c_map.get("manifest_sha256"),
                "RQ-C map and base input revision manifest differ")
    state_requests = state.get("requests") or {}
    require(isinstance(state_requests, dict), "runner state requests missing")
    revision_state, joins = load_revisions(run_output, state)
    candidates: list[dict[str, Any]] = []
    seen_orders: set[int] = set()
    for request in requests:
        order = request.get("queue_order")
        require(isinstance(order, int) and order not in seen_orders, "duplicate/invalid queue order")
        seen_orders.add(order)
        scope, revision_id = request["scope"], request["revision_id"]
        require(scope in {"main", "mem20"}, f"invalid scope at order {order}")
        candidates.append(summarize_request(request, state_requests.get(str(order)),
                                            joins.get((scope, revision_id)), run_output))
    require(set(state_requests) <= {str(order) for order in seen_orders},
            "runner state has request outside index")
    completed_by_revision: dict[tuple[str, str], set[str]] = defaultdict(set)
    for candidate in candidates:
        if candidate["result_path"] is not None:
            completed_by_revision[(candidate["scope"], candidate["revision_id"])].add(
                str(Path(candidate["result_path"]).resolve()))
    for pair, join in joins.items():
        require(join["result_paths"] == completed_by_revision.get(pair, set()),
                f"instance join result set differs from completed requests: {pair}")
    units = unit_rows(candidates, main_queue, mem20_queue)
    k5a = k5a_rows(units)
    selected_identifiers = {unit["identifier"] for unit in main_queue["units"]}
    request_counts: Counter[tuple[str, str]] = Counter((r["scope"], r["revision_id"])
                                                     for r in requests)
    rq_c = rq_c_rows(preparation, targets, rq_c_map, selected_identifiers, joins,
                     revision_state, request_counts)
    mem20 = mem20_comparison(units)
    costs = {}
    for scope in ("main", "mem20"):
        subset = [row for row in candidates if row["scope"] == scope]
        costs[scope] = {"request_wall_seconds_sum": sum(float(r["wall_seconds"] or 0) for r in subset),
                        "compile_seconds_sum": sum(r["compile_seconds"] for r in subset),
                        "compile_cache_hits": sum(r["compile_cache_hits"] for r in subset),
                        "instance_store_hits": sum(r["instance_store_hits"] for r in subset),
                        "max_request_rss_bytes": max((r["max_rss_bytes"] or 0 for r in subset), default=0)}
    complete = (all(row["status"] in {"completed", "preparation_failure"} and row["l1"] is not None
                    for row in candidates)
                and all(row["status"] == "complete" for row in units))
    if require_complete:
        require(complete, "full J summary is incomplete")
    return {"schema_version": 1, "status": "complete" if complete else "partial",
            "source": {"request_index": str(index_path), "request_index_sha256": sha256_file(index_path),
                       "run_state": str(run_output / "state.json"),
                       "run_state_sha256": sha256_file(run_output / "state.json"),
                       "preparation_units": str(preparation_path),
                       "targets": str(targets_path),
                       "rq_c_instance_map": str(rq_c_map_path),
                       "rq_c_instance_map_sha256": sha256_file(rq_c_map_path)},
            "counts": {"indexed_requests": len(requests),
                       "completed_results": sum(r["status"] == "completed" for r in candidates),
                       "preparation_failures": sum(r["preparation_failure"] is not None for r in candidates),
                       "pending_or_failed": sum(r["status"] not in {"completed", "preparation_failure"}
                                                for r in candidates),
                       "joined_revisions": len(joins)},
            "candidates": candidates, "unit_methods": units, "k5a": k5a,
            "rq_c": rq_c, "mem20_comparison": mem20, "costs": costs,
            "revision_state_count": len(revision_state)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--run-output", type=Path, required=True)
    parser.add_argument("--preparation-units", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--main-queue", type=Path, default=MAIN_QUEUE)
    parser.add_argument("--mem20-queue", type=Path, default=MEM20_QUEUE)
    parser.add_argument("--rq-c-map", type=Path, default=RQ_C_MAP)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    require(not output.exists(), f"refuse to overwrite summary: {output}")
    summary = build_summary(args.index.resolve(), args.run_output.resolve(),
                            args.preparation_units.resolve(), args.targets.resolve(),
                            args.main_queue.resolve(), args.mem20_queue.resolve(),
                            args.rq_c_map.resolve(),
                            args.require_complete)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"output": str(output), "status": summary["status"],
                      "counts": summary["counts"]}, sort_keys=True))


if __name__ == "__main__":
    main()
