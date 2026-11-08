#!/usr/bin/env python3
"""Typed post-stop adapters. No RQ-C data is used for request generation or order."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import copy
import json
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import s_round4c_postdeadline_20261027 as p


def pin(path):
    path = p.checked_input(path)
    return {"path": str(path), "sha256": p.sha(path)}


def preflight(plan):
    """Read only explicit small inputs; never inspect the live aq state here."""
    problems = []
    for pin_value in plan.get("code_pins", []):
        try:
            p.require(p.sha(p.checked_input(pin_value["path"])) == pin_value["sha256"], "code SHA changed")
        except (OSError, KeyError, ValueError) as error:
            problems.append(str(error))
    fields = ("replay_inventory", "S_plan", "J_contexts",
              "old_candidate_inventory", "j_test_harness", "W_resources", "W_J_contexts")
    if plan.get("view_plan"):
        fields += ("view_plan",)
    loaded = {}
    for name in fields:
        try:
            p.require(isinstance(plan.get(name), dict), name + " missing")
            _, loaded[name] = p.read_pin(plan[name])
        except (OSError, ValueError, KeyError, TypeError) as error:
            problems.append(f"{name}: {error}")
    s = loaded.get("S_plan")
    if "replay_inventory" in loaded and not plan.get("view_plan"):
        if any(not r.get("source_closure") for r in loaded["replay_inventory"].get("rows", [])
               if r.get("corpus") == "banyan"):
            problems.append("Banyan view conversion needs pinned source closures")
    if s:
        if not s.get("ready_for_execution"):
            problems.append("S_plan: improved tag/view preparation is not complete")
        for job in s.get("jobs", []):
            if any(type(job.get(k)) is not int or job[k] < (1 if k == "peak_bytes" else 0)
                   for k in ("peak_bytes", "retained_bytes")):
                problems.append("S_plan: measured disk peak/reserve missing")
                break
        required_revisions = {j["revision"] for j in s.get("jobs", [])}
        if set(plan.get("preparation_cost_receipts", {})) != required_revisions:
            problems.append("preparation costs: all 15 revision receipts are required")
    mean = plan.get("new_j_expected_seconds_per_request")
    if not isinstance(mean, (float, int)) or not math.isfinite(mean) or mean <= 0:
        problems.append("new J request-time estimate missing")
    for name in ("preflight", "cargo24", "replay", "view", "S", "score"):
        seconds = plan.get("stage_estimates_seconds", {}).get(name)
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            problems.append("stage estimate missing: " + name)
    return {"ready": not problems, "problems": problems}


def run_cargo_tests(plan, monitor, output):
    _, harness = p.read_pin(plan["j_test_harness"])
    manifest = Path(harness["manifest"]["path"])
    p.require(p.sha(manifest) == harness["manifest"]["sha256"], "test manifest SHA changed")
    for row in harness["sources"]:
        p.require(p.sha(Path(row["source"])) == row["source_sha256"] and
                  p.sha(Path(row["generated"])) == row["generated_sha256"], "test assertions changed")
    label = "cargo24-build"
    monitor.limits[label] = math.ceil(plan["stage_estimates_seconds"]["cargo24"])
    run = monitor.run(["cargo", "test", "--manifest-path", str(manifest), "--offline", "-j", "1",
                       "--no-run", "--message-format=json"], label, cargo=True)
    p.require(run["status"] == "completed", "J test harness build failed")
    artifacts = []
    for line in (p.OUT / "monitor" / label / "stdout.log").read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if value.get("reason") == "compiler-artifact" and value.get("executable"):
            artifacts.append(value)
    tests = {v["target"]["name"]: v["executable"] for v in artifacts if v["profile"].get("test")}
    joins = [v["executable"] for v in artifacts if v["target"]["name"] == "s-round4c-join" and not v["profile"].get("test")]
    p.require(len(joins) == 1, "join helper binary missing")
    plan["join_engine"] = pin(joins[0])
    temporary = p.IMAGE / "cargo24-temporary"
    temporary.mkdir(parents=True, exist_ok=False)
    config = p.write_new(output / "bridge-config.json", {
        "engine": plan["engine"], "join_engine": plan["join_engine"],
        "tools": plan["tools"], "temporary_root": str(temporary)})
    launcher = output / "test-bridge"
    launcher.write_text("#!/bin/sh\nexec " + __import__("shlex").quote(sys.executable) + " -B " +
                        __import__("shlex").quote(str(p.ROOT / "scripts/s_round4c_j_test_bridge_20261027.py")) + ' "$@"\n')
    launcher.chmod(0o700)
    previous = {key: os.environ.get(key) for key in ("S_ROUND4C_TEST_CONFIG", "S_ROUND4C_TEST_BRIDGE",
                "S_ROUND4C_TEST_TMP", "N6_J4C_REGRESSION_ENGINE", "S_ROUND4C_TMPDIR")}
    os.environ.update(S_ROUND4C_TEST_CONFIG=json.dumps(config), S_ROUND4C_TEST_BRIDGE=str(launcher),
                      S_ROUND4C_TEST_TMP=str(temporary), N6_J4C_REGRESSION_ENGINE=str(launcher),
                      S_ROUND4C_TMPDIR=str(temporary))
    results = []
    try:
        for index, name in enumerate(harness["test_names"]):
            source = next(row for row in harness["sources"] if "fn " + name + "(" in Path(row["generated"]).read_text())
            binary = tests[Path(source["generated"]).stem]
            label = f"cargo24-case-{index:02d}"
            monitor.limits[label] = math.ceil(plan["stage_estimates_seconds"]["cargo24"])
            row = monitor.run([binary, name, "--exact", "--test-threads=1"], label)
            p.require(row["status"] == "completed", "v2.3 regression failed: " + name)
            log = (p.OUT / "monitor" / label / "stdout.log").read_text()
            p.require("1 passed; 0 failed" in log, "test was filtered out: " + name)
            results.append({"name": name, **row})
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return {"passed": len(results) == 24, "tests": results, "join_engine": plan["join_engine"]}


def build_new_j(plan, s_summary, output, method="S"):
    """Materialize only actual ledger candidates from an independently fixed context."""
    p.require(method in ("S", "W"), "unknown method")
    _, contexts = p.read_pin(plan["J_contexts" if method == "S" else "W_J_contexts"])
    by_key = {(r["revision"], r["target_id"]): r for r in contexts["targets"]}
    p.require(len(by_key) == len(contexts["targets"]), "duplicate J target context")
    _, summary = p.read_pin(s_summary)
    rows = []
    for run in summary["runs"]:
        ledger_path = Path(run["campaign"]) / "ledger.json"
        ledger_ref = pin(ledger_path)
        _, ledger = p.read_pin(ledger_ref)
        p.require(ledger["status"] == "completed" and ledger["method"] ==
                  ("split" if method == "S" else "whole"), "unfinished campaign ledger")
        spec = json.loads(Path(run["spec"]).read_text())
        p.require(p.sha(Path(run["spec"])) == ledger["spec_sha256"], "ledger/spec SHA mismatch")
        for attempt in ledger["attempts"]:
            target = spec["targets"][attempt["target_index"]]
            p.require(target["target_id"] == attempt["target_id"], "S target mapping changed")
            for candidate in attempt.get("candidates", []):
                cpath = (ledger_path.parent / candidate["path"]).resolve()
                p.require(cpath.is_relative_to(ledger_path.parent.resolve()) and
                          p.sha(cpath) == candidate["sha256"], "candidate escaped ledger or changed")
                context = by_key[run["revision"], target["target_id"]]
                _, request = p.read_pin(context["request_template"])
                request = copy.deepcopy(request)
                p.require(context["component_wrapper_sha256"] == target["entrypoint_sha256"],
                          "J context does not describe the prepared S wrapper")
                index = len(rows)
                request["id"] = f"round4c-{method}-{index:06d}"
                request["candidate"] = {"format": "zkfuzz", "path": str(cpath)}
                ref = p.write_new(output / f"request-{index:06d}.json", request)
                candidate_ref = {"path": str(cpath), "sha256": candidate["sha256"]}
                rows.append({**context, "revision": run["revision"], "seed": run["seed"],
                             "method": method, "scope": "main", "queue_order": index,
                             "request": ref, "candidate": candidate_ref, "S_ledger": ledger_ref,
                             "inputs": [*context["inputs"], candidate_ref],
                             "completion_offset_seconds": attempt.get("completion_offset_seconds")})
    return p.write_new(output / "new-J-plan.json", {"requests": rows,
        "old_candidate_inventory": plan["old_candidate_inventory"], "S_summary": s_summary})


def score_new(plan, bundle_pin, result, monitor, output):
    """Use original attribution; constructed-input requests stay outside strict."""
    import s_round4c_strict_score_20261027 as scorer
    output.mkdir(parents=True, exist_ok=False)
    _, bundle = p.read_pin(bundle_pin)
    index_rows, states, grouped = [], {}, defaultdict(list)
    observed = set()
    excluded = []
    for row, done in zip(bundle["requests"], result["requests"]):
        p.require(row["candidate"]["sha256"] == done["candidate_sha256"], "J results reordered")
        if row.get("input_layer") != "strict":
            excluded.append({"request": row["request"], "layer": row.get("input_layer", "unverified")})
            continue
        if done["status"] == "old_or_duplicate":
            # Reusing scientific evidence requires the original request and
            # context, not just a candidate hash. Until those are bound, refuse
            # a complete score instead of silently losing an observation.
            if done.get("skip_reason") == "historical_judged":
                source = done["historical_source"]
                old_request, old = p.read_pin(source["request"])
                _, old_result = p.read_pin(done["historical_result"])
                p.require(source["revision"] == row["revision"] and
                          source["entrypoint_sha256"] == row["entrypoint_sha256"] and
                          old_result["request_sha256"] == source["request"]["sha256"],
                          "historical result/request/revision binding differs")
                p.require(p.sha(Path(old["source_root"]) / old["candidate"]["path"]) ==
                          row["candidate"]["sha256"], "historical candidate binding differs")
                row = {**row, "request": source["request"]}
                done = {**done, "result": done["historical_result"]}
            else:
                p.require(done.get("skip_reason") == "current_batch_duplicate", "unknown duplicate kind")
                first = next((r for r in bundle["requests"] if
                              r["candidate"]["sha256"] == row["candidate"]["sha256"]), None)
                p.require(first and first["revision"] == row["revision"] and
                          first["target_id"] == row["target_id"], "cross-context duplicate needs separate attribution")
                continue
        key = (row["revision"], row["method"], row["request"]["sha256"])
        if key in observed:
            continue
        observed.add(key)
        q = len(index_rows)
        index_rows.append({"queue_order": q, "scope": "main", "revision_id": row["revision"],
                           "method": row["method"], "seed": row["seed"],
                           "entrypoint_sha256": row["entrypoint_sha256"],
                           "request": row["request"]["path"], "request_sha256": row["request"]["sha256"],
                           "completion_offset_seconds": row.get("completion_offset_seconds")})
        states[str(q)] = {"status": "completed", "request_sha256": row["request"]["sha256"],
                          "result_path": done["result"]["path"], "result_sha256": done["result"]["sha256"]}
        grouped[row["revision"]].append(done["result"]["path"])
    revisions = {}
    for i, (revision, results) in enumerate(sorted(grouped.items())):
        joined = output / f"join-{i:02d}.json"
        engine = p.checked_input(plan["join_engine"]["path"])
        p.require(p.sha(engine) == plan["join_engine"]["sha256"], "join helper changed")
        label = f"{output.name}-join-{i:02d}"
        monitor.limits[label] = math.ceil(plan["stage_estimates_seconds"]["score"])
        receipt = monitor.run([str(engine), "--result", *results, "--output", str(joined)], label)
        p.require(receipt["status"] == "completed", "instance join failed")
        revisions[revision] = {"scope": "main", "revision_id": revision,
                               "instances_path": str(joined), "instances_sha256": p.sha(joined)}
    index = p.write_new(output / "index.json", {"engine_sha256": scorer.V23_SHA,
                        "request_count": len(index_rows), "requests": index_rows})
    state = p.write_new(output / "state.json", {"engine_sha256": scorer.V23_SHA,
                        "request_index_sha256": index["sha256"], "requests": states, "revisions": revisions})
    args = SimpleNamespace(**{name: Path(plan["score_inputs"][name]["path"])
                             for name in ("protocol", "targets", "mapping", "preparation")},
                           index=Path(index["path"]), state=Path(state["path"]), engine="v2.3",
                           joins_source=None, layer="strict")
    for item in plan["score_inputs"].values():
        p.require(p.sha(p.checked_input(item["path"])) == item["sha256"], "score input changed")
    score = p.write_new(output / "score.json", scorer.score(args, len(states)))
    audit = p.write_new(output / "strict-audit.json", {"passed": True, "complete": True,
        "layer": "strict", "constructed_inputs_used": False, "score_sha256": score["sha256"],
        "outside_strict": excluded, "index": index, "state": state})
    return {"score": score, "strict_input_audit": audit}


def measured_costs(plan, s_summary, new_j_plan, result, start_pin, output):
    _, s = p.read_pin(s_summary)
    _, j = p.read_pin(new_j_plan)
    revisions = {}
    for run in s["runs"]:
        row = revisions.setdefault(run["revision"], {"revision": run["revision"], "complete": True,
                          "J_complete": True, "new_candidates": 0, "stages": []})
        row["stages"] += [{"phase": "preparation", "receipt": run["preflight_monitor"]},
                          {"phase": "fuzz", "seed": run["seed"], "receipt": run["monitor"]}]
    for request, done in zip(j["requests"], result["requests"]):
        if done["status"] == "completed":
            row = revisions[request["revision"]]
            row["new_candidates"] += 1
            row["stages"].append({"phase": "J", "receipt": done["run"]})
    # Source preparation must be included, not silently lost because snapshots
    # were prepared before launch. Its receipts are a required reviewed input.
    for revision, pins in plan["preparation_cost_receipts"].items():
        for receipt in pins:
            revisions[revision]["stages"].append({"phase": "preparation", "receipt": receipt})
    return p.write_new(output / "costs.json", {"schema": "s-round4c-cost-receipts-v1",
        "complete": True, "execution_start": start_pin, "revisions": list(revisions.values())})
