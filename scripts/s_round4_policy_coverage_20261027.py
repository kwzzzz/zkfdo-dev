#!/usr/bin/env python3
"""Offline, fixed-identity Policy A/B coverage model. Never launches a process.

make-input --inventory INVENTORY --prototype-compile-summary SUMMARY --output MANIFEST
calculate --input MANIFEST --output REPORT
self-test

Every input is an explicitly named, SHA-256 verified metadata file. The two
availability scenarios require round-2 inspection success AND known compilation
success with a constraint count. Historical identity is retained for timing and
tie-breaking even if a prototype wrapper changed. This does not certify full
preparation, candidate coverage, runtime behavior, or judging outcomes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import unittest

import run_policy_b_order as policy
from s_round4_monitor_20261027 import write_new as write_json

ROOT = policy.ROOT
UNITS = ("aq-024-6f6781246415", "aq-017-9703bbce0c43")
SEEDS = (2026100601, 2026100602, 2026100603)
PREPARED = (
    "runs/n6-a1b-2026-10-08/units/aq-024-6f6781246415/preparation/prepared-small-first/prepare-6d36fa6b-c11a-48a4-a5d7-1b825043f5e2/prepared.json",
    "runs/n6-a1b-2026-10-08/units/aq-017-9703bbce0c43/preparation/prepared-small-first/prepare-92649d88-3a4d-4efc-ba9a-0e167d5aeecd/prepared.json",
)
ROUND2 = "runs/s-inspection-improve-2026-10-27"
NEW = "runs/s-tag-wrapper-2026-10-27"
MAPPING = "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json"
MODEL = (
    "Offline counterfactual, fixed original target identity; no new fuzzing. "
    "Availability = round-2 inspection pass AND hash-bound successful compilation with known constraints. "
    "Known original target_id binds historical per-seed attempt wall time, including recorded overrun. "
    "For duplicate target/seed records the largest observed wall time is used. "
    "Unobserved target/seed costs the allocated min(30, remaining) seconds. "
    "A record allocated less than 30 seconds is censored; its cost is at least the new allocation. "
    "A changed prototype borrows its original target's timing solely for this counterfactual. "
    "An attempt is counted if it starts before 600 seconds, with allocation min(30, remaining); "
    "a recorded overrun may make modeled final elapsed exceed 600. Each full order pass increments seed. "
    "Recorded costs round upward to integer nanoseconds to avoid floating-point extra starts. "
    "No extra scheduler overhead is invented. Counts are starts, not completed fuzz attempts or bug findings."
)
require = policy.require


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_metadata(name, expected=None):
    policy.guard()
    path = policy.checked_path(name)
    require(path.stat().st_size <= 128 * 1024**2, "metadata file exceeds 128 MiB")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    require(expected is None or digest == expected, "input SHA-256 mismatch: " + str(path))
    return json.loads(data), {"path": str(path), "sha256": digest}


class Inputs:
    def __init__(self):
        self.refs = {}

    def load(self, ref):
        require(isinstance(ref, dict) and isinstance(ref.get("path"), str)
                and isinstance(ref.get("sha256"), str), "input reference requires path and SHA-256")
        data, verified = read_metadata(ref["path"], ref["sha256"])
        old = self.refs.get(verified["path"])
        require(old is None or old == verified, "same input path has conflicting hashes")
        self.refs[verified["path"]] = verified
        return data


def file_ref(path):
    policy.guard()
    path = policy.checked_path(path)
    require(path.stat().st_size <= 128 * 1024**2, "metadata file exceeds 128 MiB")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest()}


def make_input(args):
    require(args.inventory and args.prototype_compile_summary and args.output,
            "make-input requires --inventory, --prototype-compile-summary, --output")
    units = []
    for unit, prepared in zip(UNITS, PREPARED):
        ledgers = [file_ref(ROOT / ("runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/"
                    + unit + "-seed-" + str(seed) + "/runs/01-primary/S/campaign/ledger.json"))
                   for seed in SEEDS]
        units.append({"unit": unit, "prepared": file_ref(ROOT / prepared),
                      "inspection": file_ref(ROOT / ROUND2 / "after" / (unit + ".json")),
                      "ledgers": ledgers})
    doc = {"schema_version": 1, "policy_script_sha256": sha(policy.__file__),
           "preregistration": file_ref(ROOT / NEW / "policy-preregistration.json"),
           "inventory": file_ref(args.inventory), "mapping": file_ref(ROOT / MAPPING),
           "current_compile_summary": file_ref(ROOT / ROUND2 / "compile-summary.json"),
           "prototype_compile_summary": file_ref(args.prototype_compile_summary), "units": units}
    print(json.dumps(write_json(args.output, doc)))


def count_header(result):
    if not result["compile_success"]:
        return None
    headers = [result["r1cs_header"]] if result.get("r1cs_header") else [
        a["header"] for a in result.get("artifacts", []) if a.get("header")]
    require(len(headers) == 1, "successful compile needs one captured R1CS header")
    size = headers[0].get("constraints")
    require(type(size) is int and size >= 0, "R1CS header constraint count invalid")
    return size


def compile_proofs(inputs, summary_ref):
    doc = inputs.load(summary_ref)
    rows = doc.get("results", doc.get("all_request_timings", doc.get("current_attempt_receipts")))
    require(isinstance(rows, list), "compile summary has no known receipt list")
    results = {}
    for row in rows:
        ref = row.get("result", row)
        data = inputs.load(ref)
        key = data["unit"], data["label"]
        require(key not in results, "duplicate compile receipt")
        require(type(data.get("compile_success")) is bool, "compile success must be boolean")
        for field in ("unit", "label", "template", "compile_success"):
            require(field not in row or row[field] == data.get(field), "compile summary/receipt binding differs")
        results[key] = {"compile_success": data["compile_success"], "constraints": count_header(data),
                        "template": data["template"], "wrapper_sha256": data.get("wrapper_sha256"),
                        "proof": {"path": ref["path"], "sha256": ref["sha256"]}}
    return results


def keyed(rows, key):
    result = {}
    for row in rows:
        value = key(row)
        require(value not in result, "duplicate metadata identity")
        result[value] = row
    return result


def bind_proof(proof, template, wrapper_sha):
    require(proof["template"] == template, "compile proof template differs")
    require(isinstance(wrapper_sha, str) and proof["wrapper_sha256"] == wrapper_sha,
            "compile proof wrapper SHA-256 differs")
    return proof


def assemble(unit, prepared, inspection, inventory, current, prototype, prepared_ref):
    old = keyed(prepared["targets"], lambda r: r["definition"]["label"])
    after = keyed(inspection["targets"], lambda r: r["label"])
    require(set(old) == set(after), "prepared/inspection target labels differ")
    scenarios = {"current_compiled": [], "prototype_compiled": []}
    details = []
    for label, target in old.items():
        d, measured = target["definition"], after[label]
        inv = inventory.get((unit, label))
        require(measured["template"] == d["template_name"], "inspection template differs")
        require(measured.get("old_target_id") == target["target_id"], "inspection original identity differs")
        passed = measured["inspection_eligible"]
        require(type(passed) is bool, "inspection eligibility is not boolean")
        require(not passed or inv is not None, "passing inspection target missing from inventory")
        source = None
        if inv:
            require(inv["original_target_id"] == target["target_id"], "inventory original identity differs")
            require(inv["template"] == d["template_name"] and inv["concrete_parameters"] == d["concrete_parameters"],
                    "inventory template/parameters differ")
            require(inv.get("inspection_complete", inv.get("inspection_eligible")) == passed,
                    "inventory inspection status differs")
            require(inv.get("round2_target_id") == measured.get("target_id"), "inventory round2 identity differs")
            require(inv.get("original_wrapper_sha256") == measured.get("existing_wrapper_sha256"),
                    "inventory original wrapper differs")
            source = inv.get("defining_source_file")
        root = target.get("inspection", {}).get("root")
        if not source and root:
            require(root["template_name"] == d["template_name"], "historical defining-source template differs")
            source = root["path"]
        if source:
            policy.source_class(source)
        structure = target.get("structure", {})
        old_success = structure.get("compile_success") is True
        old_size = structure.get("size")
        old_known = old_success and type(old_size) is int and old_size >= 0
        proof = {"compile_success": old_success, "constraints": old_size if old_known else None,
                 "proof": dict(prepared_ref, target_label=label, field="structure.compile_success/size"),
                 "proof_kind": "historical_prepared"}
        k = unit, label
        if k in current:
            proof = dict(bind_proof(current[k], d["template_name"], measured.get("existing_wrapper_sha256")),
                         proof_kind="round2_compile_receipt")
        bridge = proof
        if k in prototype:
            require(inv is not None and isinstance(inv.get("wrapper"), dict),
                    "prototype compile receipt has no generated-wrapper binding")
            bridge = dict(bind_proof(prototype[k], d["template_name"], inv["wrapper"]["sha256"]),
                          proof_kind="prototype_compile_receipt")
        detail = {"unit": unit, "label": label, "template": d["template_name"],
                  "original_target_id": target["target_id"], "round2_target_id": measured.get("target_id"),
                  "concrete_parameters": d["concrete_parameters"], "defining_source_file": source,
                  "inspection_complete": passed, "states": {}}
        for scenario, selected in (("current_compiled", proof), ("prototype_compiled", bridge)):
            reasons = []
            if not passed: reasons.append("inspection_incomplete")
            if not selected["compile_success"]: reasons.append("compile_not_proven_successful")
            if type(selected["constraints"]) is not int or selected["constraints"] < 0:
                reasons.append("constraints_unknown")
            if source is None: reasons.append("defining_source_unknown")
            available = not reasons
            state = {"available": available, "reasons": reasons, "constraints": selected["constraints"],
                     "compile_success": selected["compile_success"], "compile_proof": selected["proof"],
                     "proof_kind": selected["proof_kind"]}
            detail["states"][scenario] = state
            if available:
                scenarios[scenario].append({"label": label, "target_id": target["target_id"],
                    "template": d["template_name"], "defining_source_file": source,
                    "constraints": selected["constraints"], "eligible": True,
                    "concrete_parameters": d["concrete_parameters"],
                    "round2_target_id": measured.get("target_id"), "proof_kind": selected["proof_kind"]})
        details.append(detail)
    return scenarios, details


def durations(ledger_docs):
    """The maximum observed time per original target and actual seed is conservative."""
    values, seeds, receipts = {}, set(), []
    for ledger, ref in ledger_docs:
        require(ledger.get("total_budget_seconds") == 600 and ledger.get("attempt_cap_seconds") == 30,
                "historical ledger budget/cap differs from frozen policy")
        require(ledger.get("seed_rule") == "increment_per_pass", "historical seed rule differs")
        initial = ledger["initial_seed"]
        require(type(initial) is int and 0 <= initial < 2**64 and initial not in seeds,
                "duplicate/invalid initial seed")
        seeds.add(initial)
        recorded = []
        for attempt in ledger["attempts"]:
            seed, tid = attempt.get("seed"), attempt.get("target_id")
            seconds, allocated = attempt.get("actual_attempt_wall_seconds"), attempt.get("allocated_attempt_seconds")
            require(type(seed) is int and isinstance(tid, str) and tid, "attempt seed/target identity invalid")
            require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0,
                    "recorded attempt duration must be positive and finite")
            require(type(allocated) in (int, float) and math.isfinite(allocated) and 0 < allocated <= 30,
                    "recorded attempt allocation invalid")
            key = tid, seed
            entry = {"seconds": seconds, "allocated_seconds": allocated,
                     "censored": allocated < 30 - 1e-6,
                     "source": dict(ref, attempt_index=attempt.get("attempt_index"), initial_seed=initial),
                     "observations": 1}
            if key in values:
                previous = values[key]
                if (seconds, allocated) > (previous["seconds"], previous["allocated_seconds"]):
                    entry["observations"] = previous["observations"] + 1
                    values[key] = entry
                else:
                    previous["observations"] += 1
            else:
                values[key] = entry
            recorded.append(seconds)
        receipts.append({"initial_seed": initial, "input": ref,
                         "recorded_attempts": len(recorded), "recorded_time_seconds": stats(recorded)})
    return values, sorted(seeds), receipts


def stats(values):
    return {"count": len(values), "min": min(values) if values else None,
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None, "sum": math.fsum(values)}


def simulate(order, initial_seed, observations, budget=600, cap=30):
    require(budget == 600 and cap == 30, "coverage budget/cap cannot be changed")
    elapsed_ns, index = 0, 0
    nanos = 1_000_000_000
    visited, groups, costs, observed, defaults = {}, set(), [], [], []
    censored, repeated, last_allocation = 0, 0, None
    observed_targets, fallback_targets, raw_observed = set(), set(), []
    if not order:
        return {"initial_seed": initial_seed, "attempt_starts": 0, "distinct_targets": 0,
                "distinct_groups": 0, "modeled_elapsed_seconds": 0, "first_visits": [],
                "recorded_cost_seconds": stats([]), "fallback_cost_seconds": stats([])}
    while elapsed_ns < budget * nanos:
        require(index < 1_000_000, "simulation attempt safety limit exceeded")
        row = order[index % len(order)]
        seed = initial_seed + index // len(order)
        require(seed < 2**64, "seed overflow")
        elapsed = elapsed_ns / nanos
        allocation_ns = min(cap * nanos, budget * nanos - elapsed_ns)
        allocation = allocation_ns / nanos
        observation = observations.get((row["target_id"], seed))
        if observation:
            cost_ns = math.ceil(observation["seconds"] * nanos)
            if observation["censored"]:
                cost_ns = max(cost_ns, allocation_ns)
                censored += 1
            cost = cost_ns / nanos
            observed.append(cost)
            raw_observed.append(observation["seconds"])
            observed_targets.add(row["label"])
            repeated += observation["observations"] > 1
            source = observation["source"]
        else:
            cost_ns = allocation_ns
            cost = allocation
            defaults.append(cost)
            fallback_targets.add(row["label"])
            source = None
        require(cost > 0 and math.isfinite(cost), "model cost must advance time")
        if row["label"] not in visited:
            visited[row["label"]] = {"label": row["label"], "original_target_id": row["target_id"],
                "template": row["template"], "defining_source_file": row["defining_source_file"],
                "constraints": row["constraints"], "first_attempt_index": index, "first_seed": seed,
                "start_seconds": elapsed, "allocated_seconds": allocation, "charged_seconds": cost,
                "timing_source": source, "used_recorded_duration": observation is not None,
                "censored_recorded_duration": bool(observation and observation["censored"])}
        groups.add(policy.group_key(row)); costs.append(cost)
        elapsed_ns += cost_ns; index += 1; last_allocation = allocation
    return {"initial_seed": initial_seed, "attempt_starts": index, "distinct_targets": len(visited),
            "distinct_groups": len(groups), "modeled_elapsed_seconds": elapsed_ns / nanos,
            "recorded_duration_starts": len(observed), "fallback_30s_starts": len(defaults),
            "censored_recorded_starts": censored, "duplicate_observation_starts": repeated,
            "recorded_unique_targets": len(observed_targets),
            "fallback_unique_targets": len(fallback_targets),
            "raw_recorded_seconds": stats(raw_observed),
            "recorded_cost_seconds": stats(observed), "fallback_cost_seconds": stats(defaults),
            "all_cost_seconds": stats(costs), "last_allocation_seconds": last_allocation,
            "first_visits": list(visited.values())}


def mapping_templates(mapping, unit):
    entries = [r for r in mapping["revisions"] if r["revision_id"] == unit]
    require(len(entries) == 1, "RQ-C revision mapping is absent or ambiguous")
    return sorted({t for item in entries[0]["items"] for t in item["templates"]})


def annotate_rqc(run, required, available):
    # Called only after both complete policy orders and simulations are computed.
    reached = {r["template"] for r in run["first_visits"]}
    eligible = {r["template"] for r in available}
    run["rqc_report_only"] = {"mapped_template_names": required,
        "available_template_names": sorted(set(required) & eligible),
        "reached_template_names": sorted(set(required) & reached),
        "reached_template_count": len(set(required) & reached),
        "reached_target_count": sum(r["template"] in required for r in run["first_visits"]),
        "reached_group_count": len({(r["template"], r["defining_source_file"])
                                     for r in run["first_visits"] if r["template"] in required})}


def calculate(args):
    start = datetime.now(timezone.utc).isoformat()
    manifest, manifest_ref = read_metadata(args.input)
    require(manifest.get("schema_version") == 1, "unsupported coverage manifest schema")
    expected = manifest["policy_script_sha256"]
    require(sha(policy.__file__) == expected, "policy script differs from input manifest")
    inputs = Inputs(); inputs.refs[manifest_ref["path"]] = manifest_ref
    prereg = inputs.load(manifest["preregistration"])
    require(prereg.get("policy_sha256") == expected and prereg.get("policy_text") == policy.POLICY_TEXT,
            "policy was not preregistered with this exact code and text")
    require(datetime.fromisoformat(prereg["recorded_at"]) <= datetime.fromisoformat(start),
            "preregistration timestamp is in the future")
    inventory = inputs.load(manifest["inventory"])
    inv = keyed(inventory["targets"], lambda r: (r["unit"], r["label"]))
    current = compile_proofs(inputs, manifest["current_compile_summary"])
    prototype = compile_proofs(inputs, manifest["prototype_compile_summary"])
    results, pending = [], []
    require({r["unit"] for r in manifest["units"]} == set(UNITS) and len(manifest["units"]) == 2,
            "exactly the two requested A units are required")
    for item in manifest["units"]:
        policy.guard()
        unit = item["unit"]
        prepared = inputs.load(item["prepared"]); inspected = inputs.load(item["inspection"])
        scenarios, details = assemble(unit, prepared, inspected, inv, current, prototype, item["prepared"])
        ledgers = [(inputs.load(ref), ref) for ref in item["ledgers"]]
        observed, seeds, recorded = durations(ledgers)
        require(tuple(seeds) == SEEDS, "exactly three recorded initial seeds required")
        original_ids = {t["target_id"] for t in prepared["targets"]}
        require(all(tid in original_ids for tid, _ in observed), "ledger target not bound to original preparation")
        unit_result = {"unit": unit, "historical_targets": len(details),
                       "inspection_pass_targets": sum(d["inspection_complete"] for d in details),
                       "recorded_timing_inputs": recorded, "scenarios": {}}
        for name, rows in scenarios.items():
            reasons = Counter(reason for d in details for reason in d["states"][name]["reasons"])
            state = {"available_targets": len(rows), "available_groups": len({policy.group_key(r) for r in rows}),
                     "unavailable_reason_counts": dict(sorted(reasons.items())),
                     "compile_proof_kinds": dict(Counter(r["proof_kind"] for r in rows)), "policies": {}}
            for label, order_fn in (("A", policy.policy_a_order), ("B", policy.policy_b_order)):
                order = order_fn(rows)
                order_fields = [{k: r[k] for k in ("label", "target_id", "template", "defining_source_file", "constraints")}
                                for r in order]
                order_hash = hashlib.sha256(json.dumps(order_fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                runs = [simulate(order, seed, observed) for seed in seeds]
                state["policies"][label] = {"full_order_sha256": order_hash, "first_20": order_fields[:20],
                                           "seeds": runs}
                pending.append((unit, rows, runs))
            unit_result["scenarios"][name] = state
        results.append(unit_result)
        pending.append((unit, details, None))
        del prepared, inspected, ledgers
    # Freeze adoption from group counts before loading any bug mapping.
    comparisons = []
    for unit in results:
        candidate = unit["scenarios"]["prototype_compiled"]["policies"]
        for a, b in zip(candidate["A"]["seeds"], candidate["B"]["seeds"]):
            require(a["initial_seed"] == b["initial_seed"], "seed comparison mismatch")
            comparisons.append({"unit": unit["unit"], "seed": a["initial_seed"],
                                "A_groups": a["distinct_groups"], "B_groups": b["distinct_groups"],
                                "strict_improvement": b["distinct_groups"] > a["distinct_groups"]})
    adoption = {"recorded_utc": datetime.now(timezone.utc).isoformat(),
                "selected_policy": "B" if all(r["strict_improvement"] for r in comparisons) else "A",
                "criterion": "B must strictly increase distinct groups for every seed in both units",
                "policy_script_sha256": expected, "comparisons": comparisons,
                "mapping_loaded": False}
    adoption_ref = write_json(Path(args.output).with_name("policy-adoption.json"), adoption)
    # RQ-C mapping is deliberately loaded only AFTER the on-disk adoption decision.
    mapping = inputs.load(manifest["mapping"])
    for unit, rows, runs in pending:
        required = mapping_templates(mapping, unit)
        if runs is not None:
            for run in runs: annotate_rqc(run, required, rows)
        else:
            report = next(r for r in results if r["unit"] == unit)
            report["rqc_availability_report_only"] = [d for d in rows if d["template"] in required]
            report["compile_pass_inspection_fail_report_only"] = [d for d in rows if not d["inspection_complete"]
                and any(s["compile_success"] for s in d["states"].values())]
    output = {"schema_version": 1, "kind": "offline_fixed_identity_policy_coverage",
              "start_utc": start, "end_utc": datetime.now(timezone.utc).isoformat(), "model": MODEL,
              "budget_seconds": 600, "attempt_cap_seconds": 30, "units": results,
              "policy_script_sha256": expected, "calculator_sha256": sha(__file__), "adoption": adoption_ref,
              "inputs": sorted(inputs.refs.values(), key=lambda r: r["path"]),
              "compiler_invocations": 0, "fuzz_invocations": 0, "judging_invocations": 0}
    print(json.dumps({"result": write_json(args.output, output), "selected_policy": adoption["selected_policy"], "comparisons": comparisons}))


class CoverageTests(unittest.TestCase):
    @staticmethod
    def target(label, size=1, template="T"):
        return {"label": label, "target_id": label, "template": template,
                "defining_source_file": "own.circom", "constraints": size, "eligible": True}

    @staticmethod
    def observation(seconds, allocated=30, count=1):
        return {"seconds": seconds, "allocated_seconds": allocated,
                "censored": allocated < 30 - 1e-6, "source": {"path": "record", "sha256": "0"}, "observations": count}

    def test_unknown_thirty_second_budget(self):
        run = simulate([self.target(str(n)) for n in range(30)], 1, {})
        self.assertEqual((run["attempt_starts"], run["distinct_targets"], run["modeled_elapsed_seconds"]), (20, 20, 600))

    def test_float_roundoff_cannot_create_extra_start(self):
        rows = [self.target(str(n)) for n in range(21)]
        observed = {(str(n), 1): self.observation(29.999999999999996) for n in range(20)}
        self.assertEqual(simulate(rows, 1, observed)["attempt_starts"], 20)

    def test_small_remaining_still_starts(self):
        rows = [self.target(str(n)) for n in range(30)]
        run = simulate(rows, 1, {("0", 1): self.observation(589)})
        self.assertEqual(run["attempt_starts"], 2)
        self.assertEqual(run["last_allocation_seconds"], 11)

    def test_recorded_overrun_is_full_cost(self):
        run = simulate([self.target("a")], 1, {("a", 1): self.observation(601)})
        self.assertEqual(run["attempt_starts"], 1)
        self.assertEqual(run["modeled_elapsed_seconds"], 601)

    def test_seed_increments_only_per_complete_order_pass(self):
        rows = [self.target("a"), self.target("b")]
        observations = {(x, s): self.observation(1) for x in ("a", "b") for s in (10, 11)}
        run = simulate(rows, 10, observations)
        self.assertEqual(run["recorded_duration_starts"], 4)
        self.assertEqual(run["distinct_targets"], 2)
        self.assertEqual(run["distinct_groups"], 1)
        self.assertEqual(run["recorded_unique_targets"], 2)
        self.assertEqual(run["fallback_unique_targets"], 2)

    def test_partial_historical_record_is_censored(self):
        run = simulate([self.target("a")], 1, {("a", 1): self.observation(2, allocated=1)})
        self.assertEqual(run["first_visits"][0]["charged_seconds"], 30)
        self.assertEqual(run["censored_recorded_starts"], 1)

    def test_duplicate_duration_maximum(self):
        def ledger(initial, seed, duration):
            return ({"total_budget_seconds": 600, "attempt_cap_seconds": 30, "seed_rule": "increment_per_pass",
                     "initial_seed": initial, "attempts": [{"target_id": "x", "seed": seed,
                     "actual_attempt_wall_seconds": duration, "allocated_attempt_seconds": 30}]}, {"path": str(initial), "sha256": "0"})
        observed, _, _ = durations([ledger(1, 2, 5), ledger(2, 2, 7)])
        self.assertEqual(observed[("x", 2)]["seconds"], 7)
        self.assertEqual(observed[("x", 2)]["observations"], 2)

    def test_invalid_time_rejected(self):
        ledger = {"total_budget_seconds": 600, "attempt_cap_seconds": 30, "seed_rule": "increment_per_pass",
                  "initial_seed": 1, "attempts": [{"target_id": "x", "seed": 1,
                  "actual_attempt_wall_seconds": float("nan"), "allocated_attempt_seconds": 30}]}
        with self.assertRaises(ValueError): durations([(ledger, {"path": "x", "sha256": "0"})])

    def test_rqc_annotation_does_not_change_order_or_coverage(self):
        rows = [self.target("a", template="A"), self.target("b", template="B")]
        run = simulate(rows, 1, {})
        before = json.dumps(run, sort_keys=True)
        annotate_rqc(run, ["B"], rows)
        self.assertEqual(run["rqc_report_only"]["reached_template_names"], ["B"])
        del run["rqc_report_only"]
        self.assertEqual(json.dumps(run, sort_keys=True), before)

    def test_proof_requires_exact_wrapper_binding(self):
        proof = {"template": "T", "wrapper_sha256": "abc"}
        self.assertEqual(bind_proof(proof, "T", "abc"), proof)
        with self.assertRaises(ValueError): bind_proof(proof, "T", "different")

    def test_header_requires_known_nonnegative_count(self):
        self.assertEqual(count_header({"compile_success": True, "r1cs_header": {"constraints": 0}}), 0)
        with self.assertRaises(ValueError): count_header({"compile_success": True, "r1cs_header": {"constraints": None}})
        self.assertIsNone(count_header({"compile_success": False}))

    def fixture(self, inspection_pass=True):
        definition = {"label": "a", "template_name": "T", "concrete_parameters": ["2"]}
        prepared = {"targets": [{"target_id": "old", "definition": definition,
                     "inspection": {}, "structure": {"compile_success": True, "size": 12}}]}
        inspected = {"targets": [{"label": "a", "template": "T", "old_target_id": "old", "target_id": "new",
                      "inspection_eligible": inspection_pass, "existing_wrapper_sha256": "original"}]}
        inv = {("unit", "a"): {"original_target_id": "old", "round2_target_id": "new", "template": "T",
                  "concrete_parameters": ["2"], "inspection_complete": inspection_pass,
                  "defining_source_file": "own.circom", "original_wrapper_sha256": "original", "wrapper": {"sha256": "bridge"}}}
        return prepared, inspected, inv

    def test_compiled_but_inspection_failed_never_attempted(self):
        prepared, inspected, inv = self.fixture(False)
        scenarios, details = assemble("unit", prepared, inspected, inv, {}, {}, {"path": "p", "sha256": "0"})
        self.assertEqual(scenarios["current_compiled"], [])
        self.assertIn("inspection_incomplete", details[0]["states"]["current_compiled"]["reasons"])

    def test_prototype_success_keeps_original_timing_identity(self):
        prepared, inspected, inv = self.fixture()
        current = {("unit", "a"): {"compile_success": False, "constraints": None, "template": "T",
                    "wrapper_sha256": "original", "proof": {"path": "c", "sha256": "0"}}}
        proto = {("unit", "a"): {"compile_success": True, "constraints": 7, "template": "T",
                    "wrapper_sha256": "bridge", "proof": {"path": "b", "sha256": "0"}}}
        scenarios, _ = assemble("unit", prepared, inspected, inv, current, proto, {"path": "p", "sha256": "0"})
        self.assertEqual(scenarios["current_compiled"], [])
        self.assertEqual(scenarios["prototype_compiled"][0]["target_id"], "old")
        self.assertEqual(scenarios["prototype_compiled"][0]["constraints"], 7)

    def test_missing_constraints_excluded_without_guess(self):
        prepared, inspected, inv = self.fixture()
        prepared["targets"][0]["structure"]["size"] = None
        scenarios, details = assemble("unit", prepared, inspected, inv, {}, {}, {"path": "p", "sha256": "0"})
        self.assertEqual(scenarios["current_compiled"], [])
        self.assertIn("constraints_unknown", details[0]["states"]["current_compiled"]["reasons"])

    def test_mismatched_parameters_refused(self):
        prepared, inspected, inv = self.fixture()
        inv[("unit", "a")]["concrete_parameters"] = ["3"]
        with self.assertRaises(ValueError): assemble("unit", prepared, inspected, inv, {}, {}, {"path": "p", "sha256": "0"})


def self_test():
    result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(CoverageTests))
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}))
    if not result.wasSuccessful():
        for _, message in result.failures + result.errors: print(message)
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("self-test", "make-input", "calculate"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--prototype-compile-summary", type=Path)
    args = parser.parse_args(); policy.guard()
    if args.action == "self-test": return self_test()
    if args.action == "make-input": make_input(args)
    else:
        require(args.input and args.output, "calculate requires --input and --output")
        calculate(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
