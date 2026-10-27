#!/usr/bin/env python3
"""Synthetic deadline comparison tests; never read B result values."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import n6_b6h_result_gate as gate  # noqa: E402


class DeadlineGateTest(unittest.TestCase):
    def test_order_is_prefix_then_seed_locked_pairs(self) -> None:
        order = {"completed_prefix_orders": [0], "shuffled_remaining_orders": [2, 1],
                 "tasks": [
                     {"phase": "prefix", "engine": "v1", "queue_order": 0,
                      "request_id_sha256": "a" * 64},
                     {"phase": "shuffle", "engine": "v2.2", "queue_order": 2,
                      "request_id_sha256": "b" * 64},
                     {"phase": "shuffle", "engine": "v1", "queue_order": 2,
                      "request_id_sha256": "b" * 64},
                     {"phase": "shuffle", "engine": "v2.2", "queue_order": 1,
                      "request_id_sha256": "c" * 64},
                     {"phase": "shuffle", "engine": "v1", "queue_order": 1,
                      "request_id_sha256": "c" * 64}]}
        gate.validate_order(order, 3)
        broken = {**order, "tasks": [dict(t) for t in order["tasks"]]}
        broken["tasks"][1]["engine"] = "v1"
        with self.assertRaises(ValueError):
            gate.validate_order(broken, 3)

    def test_unfinished_are_time_or_space_never_unknown(self) -> None:
        state = {"requests": {"0": {"status": "completed"},
                              "2": {"status": "preparation_failure"}}}
        finished, judged = gate.terminal_orders(state, 3)
        self.assertEqual(finished, {0, 2})
        self.assertEqual(judged, {0})
        self.assertEqual(gate.unfinished_breakdown(3, finished, "space"),
                         {"finished": 2, "unfinished": 1,
                          "unfinished_time": 0, "unfinished_space": 1})
        with self.assertRaises(ValueError):
            gate.unfinished_breakdown(3, finished, None)

    def test_n5_comparisons_use_both_judged_flags(self) -> None:
        self.assertEqual(gate.compare_flags((True, False), (False, True)),
                         {"a_v1_only_l1": True, "b_v2_2_only_l1": False,
                          "c_excluded_vs_l1": True})
        self.assertEqual(gate.compare_flags((False, False), (False, False)),
                         {"a_v1_only_l1": False, "b_v2_2_only_l1": False,
                          "c_excluded_vs_l1": False})

    def test_effective_instance_verdict_controls_l1(self) -> None:
        result = {"request_id": "synthetic", "classes": [
            {"verdict": "unknown", "representative": "main[0]"}]}
        self.assertEqual(gate.judgement_flags(
            result, {("synthetic", "main[0]"): "assumption_violation_reachable"}),
            (True, False))
        self.assertEqual(gate.judgement_flags(
            result, {("synthetic", "main[0]"): "assumption_excluded_in_context"}),
            (False, True))


if __name__ == "__main__":
    unittest.main()
