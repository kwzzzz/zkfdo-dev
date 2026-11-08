#!/usr/bin/env python3
"""Assemble a reviewable launch plan; missing evidence is explicit, never zero-filled."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import shutil

import s_round4c_pipeline_20261027 as pipeline
import s_round4c_postdeadline_20261027 as post
import s_round4c_protocol_20261027 as protocol


def pin(path):
    path = Path(path).absolute()
    return {"path": str(path), "sha256": post.sha(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = post.checked_output(args.output)
    output.mkdir(parents=True, exist_ok=False)
    base = post.OUT / "continuation-20261027"
    # The live aq tree is never read by this preparation command.
    state = json.loads((base / "state-v3_2.json").read_text())
    peaks = post.aq_disk_peaks(state)
    peak = max(peaks.values(), default=post.aq_v32.INITIAL_PEAK)
    reg = protocol.registration()
    tools = {}
    for name in ("circom", "node", "snarkjs", "z3"):
        found = shutil.which(name)
        if found:
            tools[name] = pin(found)
    paths = sorted((post.ROOT / "scripts").glob("s_round4c_*.py"))
    paths += [post.AMENDMENT, post.PREVIOUS_AMENDMENT,
              post.ROOT / "docs/s_round4c_amendment_2026-10-27_v2.md"]
    copy = post.ROUND / "inputs/aggregate-0001.json"
    banyan = None
    if copy.is_file():
        banyan = pin(copy)
        post.require(banyan["sha256"] == "82b91a1c525167667a7ec80dc6555839a5e7af7ca1acad14db81e0607066c683",
                     "Banyan copy SHA differs")
    plan = {"schema": "s-round4c-launch-v1", "ready_for_execution": False,
        "amendment_sha256": post.sha(post.AMENDMENT),
        "previous_amendment_sha256": post.PREVIOUS_AMENDMENT_SHA,
        "preregistration_sha256": protocol.REG_SHA,
        "baseline_engine_sha256": "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835",
        "engine": pin(post.ROUND / "round4b/bin/zkfDO-v2.3-development"), "tools": tools,
        "code_pins": [pin(p) for p in paths], "banyan_copy": banyan,
        "replay_inventory": None, "view_plan": None, "auto_view_conversion": True,
        "S_plan": pin(post.OUT / "s-execution-plan-v1.json"),
        "J_contexts": None, "W_J_contexts": None, "old_candidate_inventory": None,
        "W_resources": None, "preparation_cost_receipts": {},
        "j_test_harness": pin(base / "j-tests-v1/preparation.json"),
        "aq_observed_peak_bytes": peak,
        "image_minimum_before_retained_bytes": post.required_image_bytes(peak, 0),
        "new_j_expected_seconds_per_request": 7.43,
        "stage_estimates_seconds": {"preflight": 300, "cargo24": 1800, "replay": None,
                                    "view": None, "S": 29608.498, "score": 60},
        "estimate_provenance": {"S": "historical preparation + 45 preflight + 45 campaigns; actual improved preparation may differ",
            "cargo24": "provisional 30 minutes, not a completed J timing",
            "new_J": "prior report's provisional mean; estimate, not a measured maximum",
            "replay_and_view": "must be computed from intact selected request timing after the copy arrives"},
        "fixed_revisions": reg["revision_ids"], "fixed_seeds": reg["seeds"],
        "score_inputs": {name: pin(post.ROOT / path) for name, path in {
            "protocol": "docs/n5_evaluation_protocol_v1_2026-10-06.md",
            "targets": "docs/n6_targets_a_2026-10-07.json",
            "mapping": "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json",
            "preparation": "runs/n6-a1-2026-10-07/preparation-units.json"}.items()}}
    readiness = pipeline.preflight(plan)
    plan["readiness"] = readiness
    plan["ready_for_execution"] = readiness["ready"]
    saved = post.write_new(output / "launch-plan.json", plan)
    post.write_new(output / "readiness.json", readiness)
    command = ["nice", "-n", "19", "python3", "-B", "scripts/s_round4c_postdeadline_20261027.py",
               "--plan", saved["path"], "--plan-sha256", saved["sha256"], "--amendment-sha256", plan["amendment_sha256"],
               "--output", str(post.OUT / "post-stop-run-01"), "--execute"]
    post.write_new(output / "command-not-executed.json", {"argv": command, "executed": False,
        "ready": readiness["ready"], "before_deadline_add": "--aq-stopped-by-miiz"})
    print(json.dumps({"plan": saved, "ready": readiness["ready"], "problems": readiness["problems"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
