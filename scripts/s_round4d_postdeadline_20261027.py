#!/usr/bin/env python3
"""One-command post-stop replay → S → new J → strict score → required W.

The unchanged 4c executor supplies the scientific sequence. This version adds
the first-spec disk gate, the v2.3 24-test harness, and per-revision J estimates.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s_round4c_pipeline_20261027 as pipeline
import s_round4c_postdeadline_20261027 as old
import s_round4d_j_estimates_20261027 as jcost

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "runs/s-round4-2026-10-27"
OUT = ROUND / "round4d"
AMENDMENT = ROOT / "docs/s_round4d_amendment_2026-10-27.md"
IMAGE = Path("/Volumes/zkfdo-jcache/s-round4d-20261027")
GIB = 2**30


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def folder_bytes(folder: Path) -> int:
    """Measure only one known completed S spec folder, including its preflight."""
    require(folder.is_dir() and folder.resolve().is_relative_to(OUT), "owned S spec folder required")
    total = 0
    stack = [folder]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                require(not entry.is_symlink(), "symlink in measured S output")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                else:
                    raise ValueError("unsupported S output entry")
    return total


class FirstSpecDiskGate:
    def __init__(self, monitor: old.PostMonitor, output: Path, jobs: int = 45):
        self.monitor, self.output, self.jobs = monitor, output, jobs
        self.max_spec_bytes = None
        self.limits = monitor.limits
        self.RUNROOT, self.GIB = monitor.RUNROOT, monitor.GIB

    def __getattr__(self, name):
        return getattr(self.monitor, name)

    def check(self, remaining: int) -> None:
        if self.max_spec_bytes is None:
            return
        free = self.monitor.free_bytes()
        required = 18 * GIB + remaining * self.max_spec_bytes
        require(free >= required,
                f"S disk gate: {remaining} specs require {required} bytes, free {free}; stop before next spec")

    def run(self, argv, label, timeout=0, cargo=False):
        prefix = f"post-{self.output.name}-preflight-"
        if label.startswith(prefix):
            self.check(self.jobs - int(label.removeprefix(prefix)))
        result = self.monitor.run(argv, label, timeout, cargo)
        campaign_prefix = f"post-{self.output.name}-S-"
        if label.startswith(campaign_prefix) and result["status"] == "completed":
            index = int(label.removeprefix(campaign_prefix))
            size = folder_bytes(self.output / str(index))
            require(size > 0, "first S spec output is empty")
            self.max_spec_bytes = max(self.max_spec_bytes or 0, size)
            remaining = self.jobs - index - 1
            record = {"schema": "s-round4d-first-spec-disk-gate-v1", "completed_spec": index,
                      "measured_spec_output_bytes": size, "largest_completed_spec_bytes": self.max_spec_bytes,
                      "remaining_specs": remaining,
                      "projected_remaining_bytes": remaining * self.max_spec_bytes,
                      "internal_free_bytes": self.monitor.free_bytes(), "floor_bytes": 18 * GIB}
            old.write_new(self.output / f"disk-gate-{index:02d}.json", record)
            self.check(remaining)
        return result


def record_input_preparation(plan: dict, s_plan: dict, output: Path) -> None:
    """Charge this invocation's source verification before S preflights begin."""
    import run_policy_a_engine_v4 as engine

    revisions = list(dict.fromkeys(row["revision"] for row in s_plan["jobs"]))
    require(set(plan["preparation_cost_receipts"]) == set(revisions) and
            all(not pins for pins in plan["preparation_cost_receipts"].values()),
            "new invocation must start with empty preparation cost slots")
    folder = output / "input-preparation"
    folder.mkdir()
    for index, revision in enumerate(revisions):
        job = next(row for row in s_plan["jobs"] if row["revision"] == revision)
        _, spec = old.read_pin(job["prepared_spec"])
        roots = {row["id"]: Path(row["path"]) for row in spec["source_snapshots"]}
        started = datetime.now(timezone.utc)
        verified = engine.verify_plan_v4(spec, roots)
        ended = datetime.now(timezone.utc)
        require(verified["status"] == "verified" and
                verified["target_count"] == len(spec["targets"]),
                "S source preparation verification failed")
        receipt = old.write_new(folder / f"revision-{index:02d}.json", {
            "schema": "s-round4d-input-preparation-receipt-v1",
            "revision": revision, "start_utc": started.isoformat(),
            "end_utc": ended.isoformat(), "status": "completed",
            "prepared_spec": job["prepared_spec"], "verification": verified})
        plan["preparation_cost_receipts"][revision] = [receipt]


def execute_s(plan: dict, monitor: old.PostMonitor, output: Path) -> dict:
    import s_round4b_postdeadline_20261027 as previous

    _, s_plan = old.read_pin(plan["S_plan"])
    require(s_plan.get("schema") == "s-round4d-S-plan-v1" and
            s_plan.get("ready_for_execution") is True and len(s_plan.get("jobs", [])) == 45,
            "complete improved 15×3 S plan required")
    for index, job in enumerate(s_plan["jobs"]):
        monitor.limits[f"post-{output.name}-preflight-{index}"] = job["expected_preflight_seconds"]
        monitor.limits[f"post-{output.name}-S-{index}"] = job["expected_campaign_seconds"]
    # The 4b compatibility fields are deliberately not claimed as measured peaks.
    runtime = {**s_plan, "jobs": [{**job, "peak_bytes": 1, "retained_bytes": 0}
                                   for job in s_plan["jobs"]]}
    proxy = FirstSpecDiskGate(monitor, output)
    original = previous.monitor, previous.availability, previous.__file__
    try:
        previous.monitor = proxy
        previous.availability = lambda _peak, _retained: old.internal_gate(1, 0)
        previous.__file__ = old.__file__
        output.mkdir(parents=True, exist_ok=False)
        record_input_preparation(plan, s_plan, output)
        previous.fuzz(runtime, output)
    finally:
        previous.monitor, previous.availability, previous.__file__ = original
    summary = json.loads((output / "summary.json").read_text())
    for index, run in enumerate(summary["runs"]):
        receipt = old.OUT / "monitor" / f"post-{output.name}-preflight-{index}" / "result.json"
        run["preflight_monitor"] = {"path": str(receipt), "sha256": old.sha(receipt)}
    return {"summary": old.write_new(output / "summary-with-costs.json", summary)}


def preflight(plan: dict, original) -> dict:
    result = original(plan)
    if plan.get("S_disk_gate") == "first-completed-spec-45x-v1":
        problems = [item for item in result["problems"]
                    if item != "S_plan: measured disk peak/reserve missing"]
        return {"ready": not problems, "problems": problems}
    return result


def cargo24(plan: dict, monitor: old.PostMonitor, output: Path) -> dict:
    _, harness = old.read_pin(plan["j_test_harness"])
    require(harness["schema"] == "s-round4d-j-tests-v1" and len(harness["test_names"]) == 24,
            "24-test harness changed")
    manifest = Path(plan["j_test_harness"]["path"]).parent / "Cargo.toml"
    require(old.sha(manifest) == harness["manifest_sha256"], "harness manifest changed")
    for row in harness["source_rows"]:
        require(old.sha(Path(row["source"])) == row["source_sha256"] and
                old.sha(Path(row["generated"])) == row["generated_sha256"],
                "historical assertion or harness source changed")
    probe = Path(harness["fixture_probe"])
    require(json.loads(probe.read_text())["all_at_most_1000"], "J fixture exceeds 1000 constraints")
    monitor.limits["cargo24-build"] = math.ceil(plan["stage_estimates_seconds"]["cargo24"])
    built = monitor.run(["cargo", "test", "--offline", "-j", "1", "--manifest-path",
                         str(manifest), "--no-run", "--message-format=json"], "cargo24-build", cargo=True)
    require(built["status"] == "completed", "24-test harness build failed")
    build_log = old.OUT / "monitor/cargo24-build/stdout.log"
    join = None
    for line in build_log.read_text().splitlines():
        try:
            artifact = json.loads(line)
        except ValueError:
            continue
        if (artifact.get("reason") == "compiler-artifact" and
                artifact.get("target", {}).get("name") == "s-round4d-join" and
                artifact.get("executable") and not artifact.get("profile", {}).get("test")):
            join = artifact["executable"]
    require(join is not None, "J join helper not built")
    plan["join_engine"] = {"path": join, "sha256": old.sha(Path(join))}
    monitor.limits["cargo24-tests"] = math.ceil(plan["stage_estimates_seconds"]["cargo24"])
    old_env = os.environ.get("S_ROUND4D_BUILD_LOG")
    os.environ["S_ROUND4D_BUILD_LOG"] = str(build_log)
    try:
        result = monitor.run([sys.executable, "-B", str(ROOT / "scripts/s_round4d_j_tests_20261027.py"),
                              "run-tests", "--harness", str(manifest.parent), "--output", str(output)],
                             "cargo24-tests")
    finally:
        if old_env is None:
            os.environ.pop("S_ROUND4D_BUILD_LOG", None)
        else:
            os.environ["S_ROUND4D_BUILD_LOG"] = old_env
    require(result["status"] == "completed", "v2.3 24-test result differs")
    summary = json.loads((output / "summary.json").read_text())
    require(summary["passed"] == 24 and summary["failed"] == 0, "J test denominator differs")
    return {"passed": True, "tests": summary["rows"], "join_engine": plan["join_engine"]}


@contextmanager
def patched_executor(plan: dict):
    original = (old.AMENDMENT, old.IMAGE, old.OUT, old.execute_s,
                old.capture_aq_state, pipeline.preflight, pipeline.build_new_j,
                pipeline.run_cargo_tests)
    old.AMENDMENT, old.IMAGE, old.OUT, old.execute_s = AMENDMENT, IMAGE, OUT, execute_s
    capture = original[4]
    build_j = original[6]

    def capture_estimates(*args, **kwargs):
        state_pin, state = capture(*args, **kwargs)
        estimates = jcost.estimate(state, plan["fixed_revisions"])
        old.write_new(old.OUT / "J-estimates-at-start.json", estimates)
        require(not estimates["unmeasured_revisions"],
                "aq state lacks per-revision J timing for: " + ", ".join(estimates["unmeasured_revisions"]))
        plan["j_by_revision"] = {key: row["expected_seconds_per_new_request"]
                                  for key, row in estimates["rows"].items()}
        plan["j_peak_by_revision"] = {key: row["request_workspace_peak_bytes"]
                                      for key, row in estimates["rows"].items()}
        plan["new_j_expected_seconds_per_request"] = max(plan["j_by_revision"].values())
        plan["aq_observed_peak_bytes"] = max(plan["aq_observed_peak_bytes"],
                                            state.get("observed_request_peak_bytes", 0))
        return state_pin, state

    def estimated_j(*args, **kwargs):
        initial = build_j(*args, **kwargs)
        _, bundle = old.read_pin(initial)
        for row in bundle["requests"]:
            row["expected_seconds"] = plan["j_by_revision"][row["revision"]]
            recorded = plan["j_peak_by_revision"][row["revision"]]
            row["recorded_peak_bytes"] = max(recorded or 0, plan["aq_observed_peak_bytes"])
            row["peak_provenance"] = ("request cleanup receipt + aq global reserve" if recorded else
                                      "aq global reserve; revision cleanup peak unavailable")
        output = Path(initial["path"]).with_name("new-J-plan-estimated.json")
        return old.write_new(output, bundle)

    old.capture_aq_state = capture_estimates
    pipeline.preflight = lambda value: preflight(value, original[5])
    pipeline.build_new_j = estimated_j
    pipeline.run_cargo_tests = cargo24
    try:
        yield
    finally:
        (old.AMENDMENT, old.IMAGE, old.OUT, old.execute_s,
         old.capture_aq_state, pipeline.preflight, pipeline.build_new_j,
         pipeline.run_cargo_tests) = original


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--amendment-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--aq-stopped-by-miiz", action="store_true")
    args = parser.parse_args()
    plan_path = args.plan.absolute()
    output = args.output.absolute()
    require(plan_path.is_relative_to(OUT) and output.is_relative_to(OUT) and not output.exists(),
            "new Round4d plan/output required")
    require(old.sha(plan_path) == args.plan_sha256, "launch plan SHA differs")
    require(old.sha(AMENDMENT) == args.amendment_sha256, "new amendment SHA differs")
    plan = json.loads(plan_path.read_text())
    require(plan["schema"] == "s-round4d-launch-v5" and
            plan["S_disk_gate"] == "first-completed-spec-45x-v1", "4d launch plan required")
    with patched_executor(plan):
        if args.validate_only:
            require(not args.execute, "validation cannot execute")
            output.parent.mkdir(parents=True, exist_ok=True)
            old.write_new(output, pipeline.preflight(plan))
        else:
            require(args.execute, "explicit --execute required")
            old.execute_sequence(plan, args.amendment_sha256, output,
                                 aq_stopped_by_miiz=args.aq_stopped_by_miiz)


if __name__ == "__main__":
    main()
