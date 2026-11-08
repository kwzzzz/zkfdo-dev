#!/usr/bin/env python3
"""Pure contracts for the post-stop chain; no compiler, J or fuzzer calls."""
import json
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import s_round4c_postdeadline_20261027 as runner
import s_round4c_pipeline_20261027 as pipeline
import s_round4c_protocol_20261027 as protocol
import s_round4c_sequence_20261027 as sequence
import s_round4c_view_replay_20261027 as view


class PipelineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="zkfdo-round4c-pipeline-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        output = root / "output"
        output.mkdir()
        for module in (runner, protocol):
            for name, value in (("ROOT", root), ("OUT", output)):
                context = patch.object(module, name, value)
                context.start()
                self.addCleanup(context.stop)

    def test_preflight_lists_missing_inputs_without_opening_aq(self):
        with patch.object(runner, "capture_aq_state", side_effect=AssertionError("aq read")):
            result = pipeline.preflight({})
        self.assertFalse(result["ready"])
        self.assertTrue(any("replay_inventory" in s for s in result["problems"]))
        self.assertTrue(any("W_resources" in s for s in result["problems"]))

    def test_early_start_costs_use_verified_invocation_not_fixed_deadline(self):
        receipts = {"start": {"start_utc": "2026-10-27T12:00:00+00:00", "aq_final_verified": True,
                              "aq_process_absent": True, "aq_stopped_by_miiz": True}}
        stages = []
        for i, phase in enumerate(("preparation", "fuzz", "fuzz", "fuzz")):
            receipts[str(i)] = {"start_utc": f"2026-10-27T12:00:0{i}+00:00",
                                "end_utc": f"2026-10-27T12:00:0{i+1}+00:00", "status": "completed"}
            stages.append({"phase": phase, "seed": i, "receipt": {"path": str(i), "sha256": str(i)}})
        data = {"schema": "s-round4c-cost-receipts-v1", "complete": True,
                "execution_start": {"path": "start"}, "revisions": [{"revision": "r", "complete": True,
                "J_complete": True, "new_candidates": 0, "stages": stages}]}
        value = protocol.cost_totals(data, ["r"], [1, 2, 3], loader=lambda p: receipts[p["path"]])
        self.assertEqual(value["r"]["total_ns"], 4_000_000_000)
        receipts["start"]["aq_stopped_by_miiz"] = False
        with self.assertRaises(ValueError):
            protocol.cost_totals(data, ["r"], [1, 2, 3], loader=lambda p: receipts[p["path"]])

    def test_phase_cap_is_twice_estimate_even_above_three_hours(self):
        monitor = runner.PostMonitor({})
        with patch.object(runner.time, "monotonic", return_value=100):
            monitor.begin_phase("S", 30000)
        self.assertEqual(monitor.phase_end, 60100)
        with patch.object(runner.time, "monotonic", return_value=60101):
            with self.assertRaisesRegex(ValueError, "twice"):
                monitor.end_phase()

    def test_forwarded_candidate_preserves_internal_names_and_io_copies(self):
        ports = [{"name": "x", "direction": "input", "tags": []},
                 {"name": "y", "direction": "output", "tags": []}]
        data = view.assignment({"7_assignment": {"main.x[0]": "2", "main.y[0]": 11,
                                "main.inner.z": "8"}}, "zkfuzz", ports)
        self.assertEqual(data["main.__s_tag_target.inner.z"], "8")
        self.assertEqual(data["main.x[0]"], data["main.__s_tag_target.x[0]"])
        self.assertNotIn("main.inner.z", data)
        with self.assertRaises(ValueError):
            view.assignment({"main.x": True}, "named", ports)

    def test_dynamic_requests_come_only_from_saved_ledger_and_wrapper_pin(self):
        with tempfile.TemporaryDirectory(dir=runner.OUT) as temp:
            folder = Path(temp)
            save = lambda name, value: runner.write_new(folder / name, value)
            candidate = save("campaign/candidate.json", {"7_assignment": {}})
            template = save("template.json", {"schema": "zkfdo-lifting-request-v1", "source_root": str(folder)})
            spec = save("spec.json", {"targets": [{"target_id": "t", "entrypoint_sha256": "wrapper"}]})
            save("campaign/ledger.json", {"status": "completed", "method": "split", "spec_sha256": spec["sha256"],
                "attempts": [{"target_id": "t", "target_index": 0, "candidates": [
                    {"path": "candidate.json", "sha256": candidate["sha256"]}]}]})
            contexts = save("contexts.json", {"targets": [{"revision": "r", "target_id": "t",
                "request_template": template, "component_wrapper_sha256": "wrapper", "inputs": []}]})
            summary = save("summary.json", {"runs": [{"revision": "r", "seed": 1,
                "campaign": str(folder / "campaign"), "spec": spec["path"]}]})
            plan = pipeline.build_new_j({"J_contexts": contexts, "old_candidate_inventory": {}}, summary, folder / "new")
            rows = runner.read_pin(plan)[1]["requests"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["candidate"], {"path": candidate["path"], "sha256": candidate["sha256"]})
            Path(candidate["path"]).write_text("changed")
            with self.assertRaisesRegex(ValueError, "candidate"):
                pipeline.build_new_j({"J_contexts": contexts, "old_candidate_inventory": {}}, summary, folder / "new2")

    def chain(self, fail_replay=False, new_l1=False):
        with tempfile.TemporaryDirectory(dir=runner.OUT) as temp:
            folder = Path(temp)
            calls = []
            plan = {"amendment_sha256": runner.sha(runner.AMENDMENT),
                    "previous_amendment_sha256": runner.PREVIOUS_AMENDMENT_SHA,
                    "preregistration_sha256": protocol.REG_SHA,
                    "baseline_engine_sha256": "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835",
                    "aq_observed_peak_bytes": 1, "stage_estimates_seconds": {k: 10 for k in
                    ("preflight", "cargo24", "replay", "view", "S", "score")},
                    "replay_inventory": {}, "view_plan": {}, "new_j_expected_seconds_per_request": 1,
                    "W_resources": {"path": "resources"}}
            def read(ref):
                if ref.get("path") == "resources":
                    return folder, {"jobs": [{"revision": "r", "seed": 1,
                                             "expected_preflight_seconds": 1, "expected_overhead_seconds": 1}]}
                if ref.get("path") == "w_runs":
                    return folder, {"jobs": [{"revision": "r", "seed": 1, "campaign": "campaign", "spec": "spec"}]}
                return folder, {"rows": [], "requests": []}
            def action(name, value):
                def run(*args, **kwargs):
                    calls.append(name)
                    if name == "replay" and fail_replay:
                        raise ValueError("verdict differs")
                    return value
                return run
            patches = [patch.object(runner, "OUT", folder), patch.object(runner, "IMAGE", folder / "fake-image"),
                 patch.object(runner.os, "getpriority", return_value=19),
                 patch.object(pipeline, "preflight", return_value={"ready": True, "problems": []}),
                 patch.object(runner, "capture_aq_state", return_value=({"sha256": "state"}, {})),
                 patch.object(runner, "image_gate", return_value={}),
                 patch.object(runner, "read_pin", side_effect=read),
                 patch.object(runner, "select_replay", return_value=[]),
                 patch.object(pipeline, "run_cargo_tests", side_effect=action("cargo24", {})),
                 patch.object(runner, "replay", side_effect=action("replay", {"rows": []})),
                 patch.object(runner, "compare_views", side_effect=action("view", {})),
                 patch.object(runner, "execute_s", side_effect=action("S", {"summary": {}})),
                 patch.object(pipeline, "build_new_j", side_effect=action("build-J", {})),
                 patch.object(runner, "new_j", side_effect=action("J", {"requests": []})),
                 patch.object(pipeline, "score_new", side_effect=action("score", {"strict_input_audit": {}})),
                 patch.object(pipeline, "measured_costs", side_effect=action("cost", {})),
                 patch.object(protocol, "registration", return_value={}),
                 patch.object(sequence, "make_w_plan", return_value={"jobs": [{"revision": "r", "seed": 1}] if new_l1 else [], "fuzz_budget_seconds": 6}),
                 patch.object(sequence, "execute_w", side_effect=action("W", {"path": "w_runs", "sha256": "w"})),
                 patch.object(sequence, "finish_comparison", return_value={"conclusion": "탐지 효용 미확인"})]
            with ExitStack() as stack:
                for context in patches:
                    stack.enter_context(context)
                if fail_replay:
                    with self.assertRaisesRegex(ValueError, "differs"):
                        runner.execute_sequence(plan, plan["amendment_sha256"], folder / "run", aq_stopped_by_miiz=True)
                else:
                    runner.execute_sequence(plan, plan["amendment_sha256"], folder / "run", aq_stopped_by_miiz=True)
            return calls

    def test_one_command_order_no_new_l1_has_no_w(self):
        self.assertEqual(self.chain(), ["cargo24", "replay", "view", "S", "build-J", "J", "score", "cost"])

    def test_any_replay_difference_prevents_s(self):
        self.assertEqual(self.chain(True), ["cargo24", "replay"])

    def test_new_l1_runs_required_w_and_confirms_its_candidates(self):
        self.assertEqual(self.chain(new_l1=True), ["cargo24", "replay", "view", "S", "build-J", "J",
                                                 "score", "cost", "W", "build-J", "J", "score"])


if __name__ == "__main__":
    unittest.main()
