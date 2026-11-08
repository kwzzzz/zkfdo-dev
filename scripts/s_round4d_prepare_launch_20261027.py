#!/usr/bin/env python3
"""Build a SHA-pinned 4d launch command and disclose every unsatisfied gate."""
from __future__ import annotations

import json
import math
from pathlib import Path

import s_round4d_postdeadline_20261027 as runner

ROOT, ROUND, OUT = runner.ROOT, runner.ROUND, runner.OUT


def main() -> None:
    runner.old.OUT = OUT
    base = OUT / "launch-v5"
    if base.exists():
        raise ValueError("new launch output required")
    base.mkdir(parents=True)
    old_plan_path = ROUND / "round4c-main/s-execution-plan-v1.json"
    old_plan = json.loads(old_plan_path.read_text())
    bundle_path = OUT / "prepared-s-v3/s-input-bundle.json"
    bundle = json.loads(bundle_path.read_text())
    by_key = {(j["revision"], j["seed"]): j for j in bundle["jobs"]}
    table = {row["revision"]: row for row in bundle["table"]}
    historical_preflight = {}
    for job in old_plan["jobs"]:
        revision = job["revision"]
        historical_preflight[revision] = max(historical_preflight.get(revision, 0),
                                             job["expected_preflight_seconds"])
    jobs = []
    for job in old_plan["jobs"]:
        new = by_key[job["revision"], job["seed"]]
        counts = table[job["revision"]]
        expected_preflight = math.ceil(1.25 * historical_preflight[job["revision"]] *
                                       counts["final_bundle_targets"] / counts["old_S_targets"])
        jobs.append({**job, "prepared_spec": new["prepared_spec"],
                     "prepared_plan": new["prepared_plan"],
                     "order_metadata": new["order_metadata"],
                     "source_snapshot_count": new["source_snapshot_count"],
                     "plan_validation": new["plan_validation"],
                     "expected_preflight_seconds": expected_preflight,
                     "preflight_estimate_basis": "1.25 × historical maximum for this revision × new/old target count"})
    s_plan = {**old_plan, "schema": "s-round4d-S-plan-v1", "jobs": jobs,
              "source_bundle": {"path": str(bundle_path), "sha256": runner.old.sha(bundle_path)},
              "ready_for_execution": False,
              "remaining": "21 inspection-eligible targets lack compiler evidence; six compiled tag wrappers remain inspection-incomplete"}
    s_ref = runner.old.write_new(base / "s-execution-plan.json", s_plan)
    previous = json.loads((ROUND / "round4c-main/continuation-20261027/launch-v2/launch-plan.json").read_text())
    estimates = json.loads((OUT / "j-estimates-v2.json").read_text())
    measured = [r["expected_seconds_per_new_request"] for r in estimates["rows"].values()
                if r["expected_seconds_per_new_request"]]
    code_paths = sorted((ROOT / "scripts").glob("s_round4c_*.py"))
    code_paths += sorted((ROOT / "scripts").glob("s_round4d_*.py"))
    code_paths += [runner.AMENDMENT, runner.old.PREVIOUS_AMENDMENT]
    plan = {**previous, "schema": "s-round4d-launch-v5",
            "amendment_sha256": runner.old.sha(runner.AMENDMENT),
            "previous_amendment_sha256": runner.old.PREVIOUS_AMENDMENT_SHA,
            "S_plan": s_ref, "S_disk_gate": "first-completed-spec-45x-v1",
            "j_test_harness": {"path": str(OUT / "j-tests-v2/preparation.json"),
                               "sha256": runner.old.sha(OUT / "j-tests-v2/preparation.json")},
            "new_j_expected_seconds_per_request": max(measured),
            "preparation_cost_receipts": {revision: [] for revision in bundle["revision_ids"]},
            "j_estimates_source": {"path": str(OUT / "j-estimates-v2.json"),
                                   "sha256": runner.old.sha(OUT / "j-estimates-v2.json")},
            "code_pins": [{"path": str(path), "sha256": runner.old.sha(path)} for path in code_paths],
            "stage_estimates_seconds": {**previous["stage_estimates_seconds"], "S": 40000,
                                        "cargo24": 240},
            "estimate_provenance": {**previous["estimate_provenance"],
                "new_J": "per-revision final aq state completed-request wall maximum; 2x cap; no 7.43 s assumption",
                "S": "45×600 s campaign plus 11,124 s scaled preflight and input verification allowance; provisional until measured"},
            "readiness": None, "ready_for_execution": False}
    with runner.patched_executor(plan):
        readiness = runner.pipeline.preflight(plan)
    plan["readiness"] = readiness
    plan["ready_for_execution"] = readiness["ready"]
    saved = runner.old.write_new(base / "launch-plan.json", plan)
    runner.old.write_new(base / "readiness.json", readiness)
    command = ["nice", "-n", "19", "python3", "-B",
               "scripts/s_round4d_postdeadline_20261027.py", "--plan", saved["path"],
               "--plan-sha256", saved["sha256"], "--amendment-sha256", plan["amendment_sha256"],
               "--output", str(OUT / "post-stop-run-01"), "--execute"]
    runner.old.write_new(base / "command-not-executed.json",
                         {"argv": command, "executed": False, "ready": readiness["ready"],
                          "before_deadline_add": "--aq-stopped-by-miiz"})
    print(json.dumps({"plan": saved, "ready": readiness["ready"],
                      "problems": readiness["problems"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
