#!/usr/bin/env python3
"""Score saved RQ-C metadata by fixed bug mapping, without running any engine.

Only explicit index/state/join paths are opened. No candidate, witness, input,
source-tree enumeration, engine invocation, or replacement of frozen files.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import shutil

PROTOCOL_SHA = "ad6cf87b80223436db35d8a43c30659075fbc05423f1ade93f8fd8b830fad3e7"
MAP_SHA = "8ad5d43b51d5ceaab0d95dd83a229f45fdc2a2020485a21ccb3b1a43fb4aab85"
REACH = "assumption_violation_reachable"
EXCLUDED = "assumption_excluded_in_context"
ENGINES = {"v1": "e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed",
           "v2.2": "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Reader:
    def __init__(self):
        self.sources = []
        self.ids = {}

    def read(self, name, expected=None, parse=True):
        require(shutil.disk_usage(Path.cwd()).free >= 15 * 1024**3,
                "internal disk below 15 GiB")
        path = Path(name).resolve()
        data = path.read_bytes()
        digest = sha256(data).hexdigest()
        require(expected is None or digest == expected, f"SHA mismatch: {path}")
        key = (str(path), digest)
        if key not in self.ids:
            self.ids[key] = len(self.sources)
            self.sources.append({"path": str(path), "sha256": digest})
        return (json.loads(data) if parse else data), self.ids[key]


def under(name, root):
    return name == root or name.startswith(root + ".") or name.startswith(root + "[")


def classify_class(item, roots, instances):
    """Match mapped template descendants, never attribute an ancestor TCCT to a child."""
    scoped = any(under(item["representative"], root) for root in roots)
    predicates = [p for p in item.get("predicates", [])
                  if any(under(p["instance"], root) for root in roots)]
    if not scoped and not predicates:
        return None
    effective = []
    inputs = set()
    for p in predicates:
        joined = instances.get(p["instance"])
        verdict = joined["verdict"] if joined is not None else p["verdict"]
        effective.append(verdict)
        if verdict == REACH:
            classification = ((joined or {}).get("reach_classification") or
                              (p.get("reach_inputs") or {}).get("classification"))
            inputs.add(classification or "unknown")
    own = item["verdict"] if scoped else None
    if own == "entrypoint_violation" or REACH in effective:
        status = "L1"
        if own == "entrypoint_violation":
            inputs.add({True: "public_inputs_equal", False: "public_inputs_differ"}.get(
                item.get("public_inputs_equal"), "unknown"))
    elif own == "excluded_in_context" or (effective and all(v == EXCLUDED for v in effective)):
        status = "excluded"
    else:
        status = "unknown"
    self_l1 = own == "entrypoint_violation" or any(p["verdict"] == REACH for p in predicates)
    return {"status": status, "self_l1": self_l1,
            "reach_inputs": sorted(inputs),
            "instances": sorted({p["instance"] for p in predicates}),
            "representative": item["representative"]}


def aggregate_cells(cells):
    observed = sorted({v for cell in cells for v in cell["observed_statuses"]})
    refs = sorted({v for cell in cells for v in cell["evidence_sources"]})
    outside = sum(cell.get("ambiguous_location_classes", 0) for cell in cells)
    return {"observed_statuses": observed,
            "L1_observed": "L1" in observed,
            "excluded_observed": "excluded" in observed,
            "unknown_observed": "unknown" in observed,
            "no_observation": not observed and outside == 0,
            "definition_outside_ambiguous_location": outside > 0,
            "mixed_statuses_definition_outside": len(observed) > 1,
            "revision_ids": sorted({c["revision_id"] for c in cells}),
            "evidence_sources": refs,
            "reach_inputs": sorted({v for c in cells for v in c["reach_inputs"]})}


def attribute_class(item, mappings, instances):
    matches = []
    for mapping in mappings:
        observation = classify_class(item, mapping["instance_paths"], instances)
        if observation is None:
            continue
        locations = set(observation["instances"])
        if any(under(item["representative"], root) for root in mapping["instance_paths"]):
            locations.add(item["representative"])
        matches.append((mapping["item_id"], observation, locations))
    answer = []
    for item_id, observation, locations in matches:
        observation["ambiguous_bug_ids"] = sorted({other_id for other_id, _, other_locations in matches
                                                   if other_id != item_id and locations & other_locations})
        answer.append((item_id, observation))
    return answer


def normalize_state(state, engine):
    """Read the existing aq execute-v1 layout without importing its runner."""
    if state.get("schema") != "n6-a-remeasure-aq-execute-v1":
        return state
    own = state["engines"][engine]
    revisions = {}
    for key, group in own["groups"].items():
        receipt = group.get("join") or {}
        revisions[key] = {"scope": group["scope"], "revision_id": group["revision"],
                          "instances_path": receipt.get("path"),
                          "instances_sha256": receipt.get("sha256")}
    return {"request_index_sha256": state["config"]["index_sha256"][engine],
            "engine_sha256": state["config"]["engine_sha256"][engine],
            "requests": own["requests"], "revisions": revisions}


def score(args):
    reader = Reader()
    _, protocol_ref = reader.read(args.protocol, PROTOCOL_SHA, parse=False)
    mapping, mapping_ref = reader.read(args.mapping, MAP_SHA)
    targets, targets_ref = reader.read(args.targets, mapping["targets_sha256"])
    preparation, prep_ref = reader.read(args.preparation, mapping["preparation_units_sha256"])
    index, index_ref = reader.read(args.index)
    state, state_ref = reader.read(args.state)
    state = normalize_state(state, args.engine)
    require(state["request_index_sha256"] == reader.sources[index_ref]["sha256"],
            "state/index binding mismatch")
    require(index["engine_sha256"] == state["engine_sha256"] == ENGINES[args.engine],
            "engine label/index/state binding mismatch")
    require(len(targets["items"]) == 70 and mapping["item_mapping_count"] == 26,
            "fixed denominator changed")
    mapped = defaultdict(list)
    mapped_entrypoints = {}
    selected_ids = set()
    units = {u["unit_id"]: u for u in preparation["aq_stage1_units"]}
    for revision in mapping["revisions"]:
        mapped_entrypoints[revision["revision_id"]] = revision["entrypoint_sha256"]
        for item in revision["items"]:
            selected_ids.add(item["item_id"])
            mapped[revision["revision_id"]].append(item)
    require(len(selected_ids) == 18 and sum(map(len, mapped.values())) == 26,
            "fixed mapping coverage differs")

    joins, join_sources = {}, {}
    join_specs = []
    for rev in state["revisions"].values():
        if rev.get("instances_path"):
            join_specs.append((rev["scope"], rev["revision_id"],
                               rev["instances_path"], rev["instances_sha256"]))
    if args.joins_source:
        joined_manifest, _ = reader.read(args.joins_source)
        for item in joined_manifest["joins"]:
            if item["engine"] == args.engine:
                join_specs.append((item.get("scope", "main"), item.get("revision", item.get("revision_id")),
                                   item["path"], item["sha256"]))
    for scope, revision, path, digest in join_specs:
        join, ref = reader.read(path, digest)
        require(join.get("schema") == "zkfdo-instance-verdicts-v1" and join["conflicts"] == 0,
                "saved instance join schema/conflict")
        key = (scope, revision)
        require(key not in joins, "duplicate saved revision join")
        inst = {}
        for item in join["instances"]:
            name = item["instance"]
            require(name not in inst, "ambiguous instance path within revision")
            inst[name] = item
        joins[key] = {"instances": inst,
                      "results": {str((Path(args.state).resolve().parent / n).resolve())
                                  for n in join["results"]}}
        join_sources[key] = ref

    requests = index["requests"]
    require(index["request_count"] == len(requests), "index count mismatch")
    require(len({x["queue_order"] for x in requests}) == len(requests), "duplicate queue order")
    require(set(state["requests"]) <= {str(x["queue_order"]) for x in requests},
            "state has requests outside index")
    groups = defaultdict(lambda: {"requests": 0, "statuses": Counter(), "evidence": [],
                                  "observations": defaultdict(list)})
    outside = Counter()
    statuses = Counter()
    revision_results = defaultdict(set)
    dev_groups = defaultdict(lambda: {"requests": 0, "statuses": Counter(), "observations": [],
                                     "evidence": []})
    for row in requests:
        scope, revision, method = row["scope"], row["revision_id"], row["method"]
        require(method in ("W", "S"), "unknown method")
        if revision in mapped_entrypoints:
            require(row["entrypoint_sha256"] == mapped_entrypoints[revision],
                    "index entrypoint differs from frozen instance mapping")
        group = groups[(scope, revision, method)]
        group["requests"] += 1
        saved = state["requests"].get(str(row["queue_order"]))
        status = saved["status"] if saved else "not_run"
        group["statuses"][status] += 1
        statuses[status] += 1
        dev = dev_groups[(scope, revision, method)] if revision.startswith("banyan-") else None
        if dev is not None:
            dev["requests"] += 1
            dev["statuses"][status] += 1
        if status != "completed":
            continue
        require(saved["request_sha256"] == row["request_sha256"], "state request hash mismatch")
        result, ref = reader.read(saved["result_path"], saved["result_sha256"])
        require(result.get("schema") == "zkfdo-lifting-result-v1", "result schema mismatch")
        require(result["request_sha256"] == row["request_sha256"], "result request hash mismatch")
        group["evidence"].append(ref)
        key = (scope, revision)
        revision_results[key].add(str(Path(saved["result_path"]).resolve()))
        join = joins.get(key)
        has_predicates = any(c.get("predicates") for c in result["classes"])
        require(not has_predicates or join is not None, "predicate result lacks saved join")
        instances = join["instances"] if join else {}
        entry_key = ":".join(result["entrypoint"].get(k, "") for k in
                             ("r1cs_sha256", "sym_sha256", "o0_r1cs_sha256"))
        for item in result["classes"]:
            for predicate in item.get("predicates", []):
                joined = instances.get(predicate["instance"])
                require(joined is not None and joined["entry_key"] == entry_key,
                        "predicate missing from join or entrypoint hash mismatch")
        if revision not in mapped:
            outside[(scope, revision, method)] += 1
        if scope != "main":
            outside[(scope, revision, method)] += int(revision in mapped)
        for item in result["classes"]:
            for item_id, obs in attribute_class(item, mapped.get(revision, []), instances):
                obs.update({"source": ref, "join_source": join_sources.get(key),
                            "request_id": result["request_id"], "seed": row["seed"],
                            "completion_offset_seconds": row.get("completion_offset_seconds")})
                group["observations"][item_id].append(obs)
        if dev is not None:
            dev["evidence"].append(ref)
            dev["observations"].extend(filter(None, (
                classify_class(c, ["main"], instances) for c in result["classes"])))
    for key, join in joins.items():
        require(join["results"] == revision_results[key], "saved join result coverage mismatch")
    if args.layer == "strict":
        require(statuses["completed"] == 765, "official strict completed total is not 765")

    bugs = []
    for item in targets["items"]:
        bug = {"item_id": item["id"], "development": item["bucket"] == "A-D",
               "has_fix_commit": bool(item["fix_commits"]),
               "selected_for_fixed_mapping": item["id"] in selected_ids,
               "methods": {}}
        for method in ("W", "S"):
            cells = []
            for revision, maps in mapped.items():
                mapped_item = next((m for m in maps if m["item_id"] == item["id"]), None)
                if mapped_item is None:
                    continue
                group = groups[("main", revision, method)]
                raw_observations = group["observations"].get(item["id"], [])
                ambiguous = [o for o in raw_observations if o["ambiguous_bug_ids"]]
                observations = [o for o in raw_observations if not o["ambiguous_bug_ids"]]
                obs_statuses = sorted({x["status"] for x in observations})
                cells.append({"revision_id": revision, "kind": units[revision]["revision_kind"],
                              "mapping_status": mapped_item["status"],
                              "mapped_roots": mapped_item["instance_paths"],
                              "requests": group["requests"], "request_statuses": dict(group["statuses"]),
                              "observed_statuses": obs_statuses,
                              "matched_classes": len(observations),
                              "ambiguous_location_classes": len(ambiguous),
                              "definition_outside": [{"reason": "ambiguous_bug_location",
                                  "other_item_ids": o["ambiguous_bug_ids"], "observed_status": o["status"],
                                  "source": o["source"], "representative": o["representative"],
                                  "instances": o["instances"]} for o in ambiguous],
                              "self_l1_classes": sum(o["self_l1"] for o in observations),
                              "shared_only_l1_classes": sum(o["status"] == "L1" and not o["self_l1"] for o in observations),
                              "reach_inputs": sorted({v for o in observations for v in o["reach_inputs"]}),
                              "observed_instances": sorted({v for o in observations for v in o["instances"]}),
                              "first_l1_candidate_observed_seconds": min(
                                  (o["completion_offset_seconds"] for o in observations
                                   if o["status"] == "L1" and o["completion_offset_seconds"] is not None), default=None),
                              "time_limitation": "candidate completion offset, not J confirmation time; across seeds",
                              "evidence_sources": sorted(set(group["evidence"] +
                                  ([join_sources[("main", revision)]] if ("main", revision) in join_sources else [])))})
            bug["methods"][method] = {
                "vulnerable": aggregate_cells([c for c in cells if c["kind"] == "vulnerable"]),
                "fixed": aggregate_cells([c for c in cells if c["kind"] == "fixed"]),
                "leave_one_out": aggregate_cells([c for c in cells if c["kind"] == "leave_one_out"]),
                "revisions": cells}
        bugs.append(bug)

    totals = {}
    for method in ("W", "S"):
        rows = [b["methods"][method] for b in bugs if b["selected_for_fixed_mapping"]]
        totals[method] = {"selected_bugs": len(rows)}
        for kind in ("vulnerable", "fixed"):
            totals[method][kind] = {
                "L1": sum(r[kind]["L1_observed"] for r in rows),
                "excluded": sum(r[kind]["excluded_observed"] for r in rows),
                "unknown": sum(r[kind]["unknown_observed"] for r in rows),
                "no_observation_with_mapping": sum(r[kind]["no_observation"] and bool(r[kind]["revision_ids"]) for r in rows),
                "no_fixed_mapping": sum(not r[kind]["revision_ids"] for r in rows),
                "ambiguous_location_definition_outside": sum(r[kind]["definition_outside_ambiguous_location"] for r in rows),
                "mixed_definition_outside": sum(r[kind]["mixed_statuses_definition_outside"] for r in rows)}
    development = []
    dev_present = any(key[1].startswith("banyan-") for key in groups)
    for revision in (("banyan-vulnerable", "banyan-fixed") if dev_present else ()):
        for method in ("W", "S"):
            group = dev_groups[("main", revision, method)]
            observed = sorted({o["status"] for o in group["observations"]})
            development.append({"case_id": "banyan-development-pair", "revision_id": revision,
                "method": method, "requests": group["requests"], "request_statuses": dict(group["statuses"]),
                "L1_observed_once": "L1" in observed, "excluded_observed_once": "excluded" in observed,
                "unknown_observed_once": "unknown" in observed, "observed_statuses": observed,
                "no_observation": not observed,
                "reach_inputs": sorted({v for o in group["observations"] for v in o["reach_inputs"]}),
                "formal_bug_score": None, "reason": "development pair outside frozen 18-item/26-row mapping",
                "evidence_sources": group["evidence"]})
    return {"schema": "n6-light-rqc-v1", "layer": args.layer, "engine": args.engine,
            "definitions": {"protocol_source": protocol_ref, "mapping_source": mapping_ref,
                            "targets_source": targets_ref, "preparation_source": prep_ref,
                            "index_source": index_ref, "state_source": state_ref,
                            "unit": "one fixed item_id per method; repetitions never count as bugs",
                            "scope": "main; supplemental mem20 remains separate",
                            "matching": "fixed mapped template root and descendants; no new location mapping",
                            "absent": "no observation is neither unknown nor exclusion",
                            "mixed": "retain overlapping statuses; priority across requests undefined",
                            "signal_limit": "template mapping is not independent root-cause/signal attribution"},
            "denominators": {"fixed_items": 70, "with_fix_commit": sum(bool(x["fix_commits"]) for x in targets["items"]),
                             "selected_items": 18, "mapping_rows": 26, "unmapped_items": 52},
            "request_statuses": dict(statuses), "bug_totals": totals, "bugs": bugs,
            "development_pair_observations": development,
            "completed_outside_mapping_or_main": [{"scope": k[0], "revision_id": k[1], "method": k[2], "count": n}
                                                  for k, n in sorted(outside.items())],
            "sources": reader.sources}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "targets", "mapping", "preparation", "index", "state", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--joins-source", type=Path)
    p.add_argument("--engine", choices=tuple(ENGINES), required=True)
    p.add_argument("--layer", choices=("strict", "exploratory"), required=True)
    args = p.parse_args()
    require(not args.output.exists(), "output exists; choose a new version")
    result = score(args)
    data = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    require(len(data.encode()) <= 2_000_000, "output exceeds 2 MB")
    require(shutil.disk_usage(Path.cwd()).free >= 15 * 1024**3, "internal disk below 15 GiB")
    args.output.write_text(data)
    print(json.dumps({"layer": args.layer, "engine": args.engine,
                      "request_statuses": result["request_statuses"],
                      "bug_totals": result["bug_totals"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
