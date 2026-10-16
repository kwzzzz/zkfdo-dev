#!/usr/bin/env python3
"""Synthetic verdict metadata tests for the N6-J1 summary."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_j1_summarize as summary  # noqa: E402


def write_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return summary.sha256_file(path)


class SummaryTest(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
        index_path = root / "request-index.json"
        run_output = root / "run"
        preparation_path = root / "preparation.json"
        targets_path = root / "targets.json"
        main_queue_path = root / "main-queue.json"
        mem20_queue_path = root / "mem20-queue.json"
        rq_c_map_path = root / "rq-c-map.json"
        write_json(main_queue_path, {"units": [{"unit_id": "aq-001-s01", "identifier": "aq-001", "seed": 1}]})
        write_json(mem20_queue_path, {"units": []})
        write_json(preparation_path, {"aq_stage1_units": [{"unit_id": "aq-001", "item_ids": ["item"],
                                                            "revision_kind": "fixed", "leave_one_out": None}]})
        write_json(targets_path, {"items": [{"id": "item", "location": {"Function": "LessThan"}}]})
        write_json(rq_c_map_path, {"status": "verified", "mapping_scope": "selected_aq_revisions",
                                   "preparation_units_sha256": summary.sha256_file(preparation_path),
                                   "targets_sha256": summary.sha256_file(targets_path),
                                   "revisions": [{"revision_id": "aq-001",
                                                  "mapping_basis": "same_entrypoint_sha256",
                                                  "items": [{"item_id": "item", "status": "mapped",
                                                             "templates": ["LessThan"],
                                                             "missing_templates": [],
                                                             "instance_paths": ["main.lesser"]}]}]})
        requests = []
        for order, method in ((0, "W"), (1, "S")):
            requests.append({"scope": "main", "revision_id": "aq-001", "unit_id": "aq-001-s01",
                             "queue_order": order, "seed": 1, "method": method,
                             "attempt_number": 0, "candidate_index": 0,
                             "completion_offset_seconds": 2.0 if method == "W" else 4.0,
                             "target_id": f"{method}-target", "original_target_id": None,
                             "candidate_path": str(root / f"candidate-{method}.json"),
                             "candidate_sha256": ("a" if method == "W" else "b") * 64,
                             "request": str(root / f"request-{method}.json"),
                             "request_sha256": ("c" if method == "W" else "d") * 64,
                             "preparation_failure": "base_input_unavailable" if method == "W" else None})
        write_json(index_path, {"schema_version": 1, "status": "verified", "request_count": 2,
                                "requests": requests})
        result_path = run_output / "main/0001/requests/000001/attempt-0001/result.json"
        result = {"schema": "zkfdo-lifting-result-v1", "request_id": "request-s",
                  "request_sha256": "d" * 64, "candidate_sha256": "b" * 64,
                  "preparation": {"status": "ok", "reason": None},
                  "classes": [{"representative": "main.lesser[0]", "verdict": "assumption_input_reachable",
                               "assumption_predicate_verdict": "assumption_violation_reachable",
                               "predicates": [{"verdict": "assumption_violation_reachable",
                                               "reach_inputs": {"classification": "private_only"}}]}],
                  "costs": {"steps": [{"stage": "compile", "seconds": 1.5, "cached": True,
                                        "label": "compile (cache hit)"},
                                       {"stage": "site_discovery", "seconds": 0.5,
                                        "label": "instance store hit"}]}}
        result_sha = write_json(result_path, result)
        instances_path = run_output / "main/0001/instances.json"
        instance_join = {"schema": "zkfdo-instance-verdicts-v1", "conflicts": 0,
                         "results": [str(result_path.relative_to(run_output))],
                         "classes": [{"request_id": "request-s", "representative": "main.lesser[0]",
                                      "own": "assumption_violation_reachable",
                                      "effective": "assumption_violation_reachable",
                                      "target_basis": "broken_by_candidate"}],
                         "instances": [{"instance": "main.lesser[0]", "entry_key": "hash-key",
                                        "verdict": "assumption_violation_reachable",
                                        "reach_classification": "private_only"}]}
        instances_sha = write_json(instances_path, instance_join)
        state = {"requests": {
            "0": {"status": "preparation_failure", "request_sha256": "c" * 64,
                  "result_path": None, "preparation_failure": "base_input_unavailable",
                  "wall_seconds": 0.0, "max_rss_bytes": 0},
            "1": {"status": "completed", "request_sha256": "d" * 64,
                  "result_path": str(result_path), "result_sha256": result_sha,
                  "preparation_failure": None, "wall_seconds": 3.0, "max_rss_bytes": 1024},
        }, "revisions": {"main/0001": {"revision_id": "aq-001", "status": "joined",
                                          "instances_path": str(instances_path),
                                          "instances_sha256": instances_sha, "result_count": 1}}}
        write_json(run_output / "state.json", state)
        return (index_path, run_output, preparation_path, targets_path,
                main_queue_path, mem20_queue_path, rq_c_map_path)

    def test_complete_summary_l1_k5a_rq_c_and_costs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            data = summary.build_summary(*args, require_complete=True)
            self.assertEqual(data["status"], "complete")
            self.assertEqual(data["counts"]["preparation_failures"], 1)
            self.assertEqual(data["counts"]["completed_results"], 1)
            self.assertEqual(data["candidates"][1]["l1_time_seconds"], 4.0)
            self.assertEqual(data["candidates"][1]["reach_inputs"], ["private_only"])
            self.assertTrue(data["k5a"][0]["r_s_plus_j_only_l1"])
            self.assertEqual(data["unit_methods"][0]["first_l1_seconds"], 600.0)
            self.assertEqual(data["unit_methods"][1]["first_l1_seconds"], 4.0)
            self.assertTrue(data["rq_c"][0]["fix_reach"])
            self.assertEqual(data["rq_c"][0]["revisions"][0]["instances"][0]["instance"],
                             "main.lesser[0]")
            self.assertEqual(data["rq_c"][0]["revisions"][0]["mapping_status"], "mapped")
            self.assertEqual(data["costs"]["main"]["compile_seconds_sum"], 1.5)
            self.assertEqual(data["costs"]["main"]["compile_cache_hits"], 1)
            self.assertEqual(data["costs"]["main"]["instance_store_hits"], 1)

    def test_partial_pilot_and_require_complete_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            state_path = args[1] / "state.json"
            state = json.loads(state_path.read_text())
            state["requests"].pop("0")
            write_json(state_path, state)
            data = summary.build_summary(*args)
            self.assertEqual(data["status"], "partial")
            self.assertEqual(data["counts"]["preparation_failures"], 0)
            self.assertEqual(data["candidates"][0]["planned_preparation_failure"],
                             "base_input_unavailable")
            self.assertIsNone(data["candidates"][0]["preparation_failure"])
            self.assertEqual(data["unit_methods"][0]["preparation_failure_counts"], {})
            self.assertIsNone(data["k5a"][0]["r_s_plus_j_only_l1"])
            with self.assertRaises(summary.SummaryError):
                summary.build_summary(*args, require_complete=True)

    def test_completed_result_cannot_override_planned_preparation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            state_path = args[1] / "state.json"
            state = json.loads(state_path.read_text())
            state["requests"]["0"]["status"] = "completed"
            write_json(state_path, state)
            with self.assertRaises(summary.SummaryError):
                summary.build_summary(*args)

    def test_rejects_stale_instance_join_result_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            state_path = args[1] / "state.json"
            state = json.loads(state_path.read_text())
            instances_path = Path(state["revisions"]["main/0001"]["instances_path"])
            joined = json.loads(instances_path.read_text())
            joined["results"] = []
            state["revisions"]["main/0001"]["instances_sha256"] = write_json(instances_path, joined)
            write_json(state_path, state)
            with self.assertRaises(summary.SummaryError):
                summary.build_summary(*args)

    def test_rejects_instance_join_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            state_path = args[1] / "state.json"
            state = json.loads(state_path.read_text())
            instances_path = Path(state["revisions"]["main/0001"]["instances_path"])
            joined = json.loads(instances_path.read_text())
            joined["conflicts"] = 1
            state["revisions"]["main/0001"]["instances_sha256"] = write_json(instances_path, joined)
            write_json(state_path, state)
            with self.assertRaises(summary.SummaryError):
                summary.build_summary(*args)

    def test_entrypoint_violation_is_l1_without_instance_join(self) -> None:
        result = {"request_id": "r", "classes": [{"representative": "main.X[0]",
                                                   "verdict": "entrypoint_violation",
                                                   "assumption_predicate_verdict": None,
                                                   "predicates": []}]}
        classes, l1, reach = summary.result_classes(result, None)
        self.assertEqual(classes[0]["self_verdict"], "entrypoint_violation")
        self.assertIs(l1, True)
        self.assertEqual(reach, [])

    def test_mapped_root_template_includes_descendant_instances(self) -> None:
        preparation = {"aq_stage1_units": [{"unit_id": "aq-fixed", "item_ids": ["item"],
                                            "revision_kind": "fixed", "leave_one_out": None}]}
        targets = {"items": [{"id": "item", "location": {"Function": "Spend"}}]}
        mapping = {"revisions": [{"revision_id": "aq-fixed", "mapping_basis": "pragma_equivalent",
                                  "items": [{"item_id": "item", "status": "mapped",
                                             "instance_paths": ["main"], "missing_templates": []}]}]}
        joins = {("main", "aq-fixed"): {"instances": [{"instance": "main.rangeCheck[0]",
                                                        "verdict": "assumption_violation_reachable"}]}}
        rows = summary.rq_c_rows(preparation, targets, mapping, {"aq-fixed"}, joins, {},
                                 summary.Counter({("main", "aq-fixed"): 1}))
        self.assertIs(rows[0]["fix_reach"], True)
        self.assertEqual(rows[0]["revisions"][0]["mapping_basis"], "pragma_equivalent")

    def test_shared_effective_reach_uses_joined_instance_classification(self) -> None:
        result = {"request_id": "r", "classes": [{"representative": "main.LessThan[0]",
                                                   "verdict": "excluded_in_context",
                                                   "assumption_predicate_verdict": "assumption_excluded_in_context",
                                                   "predicates": []}]}
        joined = {("r", "main.LessThan[0]"): {"effective": "assumption_violation_reachable",
                                                 "target_basis": "shared_instance"}}
        instances = [{"instance": "main.LessThan[0].check[0]",
                      "verdict": "assumption_violation_reachable",
                      "reach_classification": "public_only"}]
        _, l1, reach = summary.result_classes(result, joined, instances)
        self.assertIs(l1, True)
        self.assertEqual(reach, ["public_only"])

    def test_no_matching_joined_instance_keeps_rq_c_reach_unknown(self) -> None:
        preparation = {"aq_stage1_units": [{"unit_id": "aq-fixed", "item_ids": ["item"],
                                            "revision_kind": "fixed", "leave_one_out": None}]}
        targets = {"items": [{"id": "item", "location": {"Function": "LessThan"}}]}
        mapping = {"revisions": [{"revision_id": "aq-fixed", "mapping_basis": "same_entrypoint_sha256",
                                  "items": [{"item_id": "item", "status": "mapped",
                                             "instance_paths": ["main.less"], "missing_templates": []}]}]}
        joins = {("main", "aq-fixed"): {"instances": [{"instance": "main.Other[0]",
                                                        "verdict": "assumption_violation_reachable"}]}}
        rows = summary.rq_c_rows(preparation, targets, mapping, {"aq-fixed"}, joins, {},
                                 summary.Counter({("main", "aq-fixed"): 1}))
        self.assertIsNone(rows[0]["fix_reach"])
        self.assertIsNone(rows[0]["revisions"][0]["reach"])
        self.assertEqual(rows[0]["revisions"][0]["unresolved_reason"],
                         "no_joined_predicate_target_in_mapped_instances")
        self.assertEqual(rows[0]["enumeration_scope"], "joined_predicate_targets")


if __name__ == "__main__":
    unittest.main()
