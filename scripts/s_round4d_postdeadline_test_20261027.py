#!/usr/bin/env python3
"""Synthetic first-spec disk and S-ledger → J → strict-score → W contracts."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import s_round4c_pipeline_20261027 as pipeline
import s_round4c_postdeadline_20261027 as old
import s_round4c_protocol_20261027 as protocol
import s_round4c_sequence_20261027 as sequence
import s_round4d_postdeadline_20261027 as runner


class Contracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="zkfdo-round4d-contract-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        output = root / "output"
        output.mkdir()
        for module in (runner, old, protocol):
            for name, value in (("ROOT", root), ("OUT", output)):
                context = patch.object(module, name, value)
                context.start()
                self.addCleanup(context.stop)

    def test_preparation_cost_receipts_are_new_and_revision_bound(self):
        with tempfile.TemporaryDirectory(dir=runner.OUT) as temporary:
            output = Path(temporary) / "S"
            output.mkdir()
            plan = {"preparation_cost_receipts": {"r1": [], "r2": []}}
            s_plan = {"jobs": [{"revision": revision, "prepared_spec": {"path": revision}}
                               for revision in ("r1", "r2")]}
            spec = {"source_snapshots": [{"id": "x", "path": temporary}],
                    "targets": [{}]}
            with patch.object(old, "OUT", Path(temporary)), \
                 patch.object(old, "read_pin", return_value=(None, spec)), \
                 patch("run_policy_a_engine_v4.verify_plan_v4",
                       return_value={"status": "verified", "target_count": 1}):
                runner.record_input_preparation(plan, s_plan, output)
            self.assertEqual(set(plan["preparation_cost_receipts"]), {"r1", "r2"})
            for revision, pins in plan["preparation_cost_receipts"].items():
                self.assertEqual(len(pins), 1)
                receipt = json.loads(Path(pins[0]["path"]).read_text())
                self.assertEqual(receipt["revision"], revision)
                self.assertEqual(receipt["status"], "completed")

    def test_first_spec_disk_gate_stops_before_second_spec(self):
        with tempfile.TemporaryDirectory(dir=runner.OUT) as temporary:
            output = Path(temporary) / "S"
            first = output / "0"
            first.mkdir(parents=True)
            (first / "ledger.json").write_bytes(b"x" * 100)

            class FakeMonitor:
                RUNROOT, GIB = runner.ROUND, runner.GIB
                limits = {}

                @staticmethod
                def free_bytes():
                    return 18 * runner.GIB + 44 * 100 - 1

                @staticmethod
                def run(_argv, _label, _timeout=0, _cargo=False):
                    return {"status": "completed"}

            gate = runner.FirstSpecDiskGate(FakeMonitor(), output)
            with patch.object(old, "OUT", Path(temporary)):
                with self.assertRaisesRegex(ValueError, "S disk gate"):
                    gate.run([], "post-S-S-0")
            self.assertEqual(gate.max_spec_bytes, 100)

    def chain(self, mode: str):
        with tempfile.TemporaryDirectory(dir=runner.OUT) as temporary:
            folder = Path(temporary)

            def save(name: str, value: dict):
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = (json.dumps(value, sort_keys=True) + "\n").encode()
                path.write_bytes(raw)
                return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}

            candidate = save("campaign/candidate.json", {"7_assignment": {}})
            spec = save("spec.json", {"targets": [{"target_id": "t", "entrypoint_sha256": "w"}]})
            save("campaign/ledger.json", {"status": "completed", "method": "split",
                "spec_sha256": spec["sha256"], "attempts": [{"target_index": 0, "target_id": "t",
                "candidates": [{"path": "candidate.json", "sha256": candidate["sha256"]}]}]})
            template = save("request-template.json", {"schema": "zkfdo-lifting-request-v1",
                "source_root": str(folder), "candidate": {"path": "candidate.json", "format": "zkfuzz"}})
            contexts = save("contexts.json", {"targets": [{"revision": "r", "target_id": "t",
                "request_template": template, "component_wrapper_sha256": "w", "inputs": []}]})
            inventory = save("inventory.json", {"complete": True, "rows": []})
            summary = save("S-summary.json", {"runs": [{"revision": "r", "seed": 1,
                "campaign": str(folder / "campaign"), "spec": spec["path"]}]})
            replay = save("replay.json", {"schema": "s-round4c-replay-inventory-v1", "rows": []})
            state = save("state.json", {"engines": {}})
            result = save("fake-J-result.json", {"candidate_sha256": candidate["sha256"],
                "preparation": {"status": "ok"}, "classes": []})
            score = save("fake-score.json", {"new_strict_L1": mode == "L1"})
            audit = save("fake-audit.json", {"passed": True, "complete": True, "layer": "strict",
                "outside_strict": [], "constructed_inputs_used": False})
            costs = save("fake-costs.json", {"total_ns": 9_000_000_000})
            resources = save("W-resources.json", {"jobs": [{"revision": "r", "seed": seed,
                "expected_preflight_seconds": 1, "expected_overhead_seconds": 1}
                for seed in (1, 2, 3)]})
            w_runs = save("W-runs.json", {"jobs": [{"revision": "r", "seed": seed,
                "campaign": "campaign", "spec": "spec"} for seed in (1, 2, 3)]})
            calls = []

            class Monitor:
                def __init__(self, limits):
                    self.limits = limits
                    self.retained_image_bytes = 0

                @staticmethod
                def begin_phase(_name, _expected):
                    return None

                @staticmethod
                def end_phase():
                    return None

            original_build = pipeline.build_new_j

            def build(plan, s, output, method="S"):
                calls.append("build-" + method)
                if method == "S":
                    return original_build(plan, s, output, method)
                return old.write_new(output / "new-J-plan.json", {"requests": [],
                    "old_candidate_inventory": inventory, "S_summary": s})

            def judge(plan, _monitor, _output):
                calls.append("J")
                rows = old.read_pin(plan["new_J_plan"])[1]["requests"]
                return {"requests": [{"candidate_sha256": candidate["sha256"],
                    "status": "completed", "result": result}] if rows else []}

            def strict_score(_plan, _bundle, _j, _monitor, _output):
                calls.append("score")
                if mode == "score-fails":
                    raise ValueError("synthetic strict score failure")
                return {"score": score, "strict_input_audit": audit}

            def make_w(scored, _reg):
                if not json.loads(Path(scored["score"]["path"]).read_text())["new_strict_L1"]:
                    return {"jobs": [], "fuzz_budget_seconds": 0}
                jobs = []
                for seed in (1, 2, 3):
                    original = {"method": "whole", "targets": [{}], "initial_seed": seed,
                        "concurrency": 1, "memory_cap_bytes": 10 * runner.GIB,
                        "campaign_id": "W", "total_budget_seconds": 1,
                        "attempt_cap_seconds": 1}
                    budget = sequence.w_spec(original, seed, 9_000_000_000)["total_budget_seconds"]
                    jobs.append({"revision": "r", "seed": seed, "budget_seconds": budget})
                self.assertEqual([j["budget_seconds"] for j in jobs], [3, 3, 3])
                return {"jobs": jobs, "fuzz_budget_seconds": 9}

            def execute_w(plan, _resources, _out):
                calls.append("W")
                self.assertEqual([(j["revision"], j["seed"]) for j in plan["jobs"]],
                                 [("r", 1), ("r", 2), ("r", 3)])
                return w_runs

            plan = {"amendment_sha256": old.sha(runner.AMENDMENT),
                "previous_amendment_sha256": old.PREVIOUS_AMENDMENT_SHA,
                "preregistration_sha256": protocol.REG_SHA,
                "baseline_engine_sha256": "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835",
                "aq_observed_peak_bytes": 1, "stage_estimates_seconds": {key: 10 for key in
                ("preflight", "cargo24", "replay", "view", "S", "score")},
                "replay_inventory": replay, "J_contexts": contexts,
                "old_candidate_inventory": inventory, "W_resources": resources,
                "new_j_expected_seconds_per_request": 1}
            patches = [patch.object(old, "AMENDMENT", runner.AMENDMENT),
                patch.object(old, "OUT", folder), patch.object(old, "IMAGE", folder / "fake-image"),
                patch.object(old.os, "getpriority", return_value=19),
                patch.object(old, "PostMonitor", Monitor),
                patch.object(pipeline, "preflight", return_value={"ready": True, "problems": []}),
                patch.object(old, "capture_aq_state", return_value=(state, {})),
                patch.object(old, "image_gate", return_value={}),
                patch.object(old, "select_replay", return_value=[]),
                patch.object(pipeline, "run_cargo_tests", return_value={"passed": True}),
                patch.object(old, "replay", return_value={"rows": []}),
                patch.object(old, "compare_views", return_value={}),
                patch.object(old, "execute_s", return_value={"summary": summary}),
                patch.object(pipeline, "build_new_j", side_effect=build),
                patch.object(old, "new_j", side_effect=judge),
                patch.object(pipeline, "score_new", side_effect=strict_score),
                patch.object(pipeline, "measured_costs", return_value=costs),
                patch.object(protocol, "registration", return_value={}),
                patch.object(sequence, "make_w_plan", side_effect=make_w),
                patch.object(sequence, "execute_w", side_effect=execute_w),
                patch.object(sequence, "finish_comparison", return_value={"conclusion": "synthetic"})]
            with ExitStack() as stack:
                for item in patches:
                    stack.enter_context(item)
                if mode == "score-fails":
                    with self.assertRaisesRegex(ValueError, "strict score failure"):
                        old.execute_sequence(plan, plan["amendment_sha256"], folder / "run",
                                             aq_stopped_by_miiz=True)
                else:
                    old.execute_sequence(plan, plan["amendment_sha256"], folder / "run",
                                         aq_stopped_by_miiz=True)
            return calls, folder / "run" / "sequence-failed.json"

    def test_no_new_l1_ends_without_w(self):
        calls, _ = self.chain("none")
        self.assertIn("build-S", calls)
        self.assertEqual(calls.count("W"), 0)

    def test_new_l1_runs_only_three_matching_w_seeds(self):
        calls, _ = self.chain("L1")
        self.assertEqual(calls.count("W"), 1)
        self.assertIn("build-W", calls)

    def test_strict_score_failure_stops_before_w(self):
        calls, _ = self.chain("score-fails")
        self.assertIn("score", calls)
        self.assertNotIn("W", calls)


if __name__ == "__main__":
    unittest.main()
