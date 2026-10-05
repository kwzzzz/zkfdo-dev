"""Counterexamples for the deterministic budget model; no engine or fuzzing."""

import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "policy_a_budget_model",
    Path(__file__).resolve().parents[1] / "scripts/policy_a_budget_model.py",
)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def event(kind="no_candidate", duration_ms=1, startup_ms=0, cleanup_ms=0, **extra):
    return {"kind": kind, "duration_ms": duration_ms, "startup_ms": startup_ms,
            "cleanup_ms": cleanup_ms, **extra}


class PolicyABudgetModelTest(unittest.TestCase):
    def test_candidate_does_not_end_unit_or_drop_duplicate_markers(self):
        result = policy.simulate(["one"], [7, 9],
                                 [event("candidate", 2, marker="same-marker")], 6, 4)
        self.assertEqual(result["end_reason"], "budget_exhausted")
        self.assertEqual(result["consumed_ms"], 6)
        self.assertEqual(result["remaining_ms"], 0)
        self.assertEqual(len(result["attempts"]), 3)
        self.assertEqual([row["candidate_marker"] for row in result["attempts"]],
                         ["same-marker"] * 3)
        self.assertEqual([row["seed"] for row in result["attempts"]], [7, 9, 7])

    def test_twenty_one_targets_share_one_budget_instead_of_multiplying_it(self):
        many_targets = [f"target-{index}" for index in range(21)]
        single = policy.simulate(["whole"], [1], [event()], 5, 2)
        split = policy.simulate(many_targets, [1], [event()], 5, 2)
        self.assertEqual(single["consumed_ms"], 5)
        self.assertEqual(split["consumed_ms"], 5)
        self.assertEqual(split["remaining_ms"], 0)
        self.assertEqual(len(single["attempts"]), 5)
        self.assertEqual(len(split["attempts"]), 5)
        self.assertEqual(len(split["targets"]), 21)
        self.assertEqual([row["target_id"] for row in split["attempts"]], many_targets[:5])

    def test_small_remaining_budget_clips_attempt_and_records_cleanup_overrun(self):
        result = policy.simulate(["one"], [1], [event("timeout", 99, cleanup_ms=2)], 3, 10)
        self.assertEqual(result["end_reason"], "budget_exhausted")
        self.assertEqual(len(result["attempts"]), 1)
        row = result["attempts"][0]
        self.assertEqual(row["allocated_ms"], 3)
        self.assertEqual(row["process_wall_ms"], 3)
        self.assertEqual(row["cleanup_ms"], 2)
        self.assertEqual(result["consumed_ms"], 5)
        self.assertEqual(result["overrun_ms"], 2)
        self.assertEqual(result["remaining_ms"], 0)

    def test_restart_and_cleanup_costs_are_debited_and_reservations_released(self):
        result = policy.simulate(["one"], [1],
                                 [event(duration_ms=1, startup_ms=1, cleanup_ms=1)], 6, 4)
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["consumed_ms"], 6)
        first, second = result["attempts"]
        self.assertEqual(first["reservation_before_ms"], 6)
        self.assertEqual(first["allocated_ms"], 4)
        self.assertEqual(first["released_ms"], 1)
        self.assertEqual(first["remaining_after_ms"], 3)
        self.assertEqual(second["allocated_ms"], 3)
        self.assertEqual(second["remaining_after_ms"], 0)
        for row in result["attempts"]:
            self.assertEqual(row["debit_ms"],
                             row["startup_ms"] + row["process_wall_ms"] + row["cleanup_ms"])
            self.assertEqual(row["released_ms"], max(row["allocated_ms"] - row["debit_ms"], 0))

    def test_cancellation_keeps_cleanup_cost_and_prevents_next_attempt(self):
        result = policy.simulate(["left", "right"], [1],
                                 [event(duration_ms=10, startup_ms=1, cleanup_ms=2)],
                                 20, 15, cancel_at_ms=3)
        self.assertEqual(result["end_reason"], "cancelled")
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["consumed_ms"], 5)
        self.assertEqual(result["remaining_ms"], 15)
        self.assertEqual(result["attempts"][0]["cleanup_ms"], 2)

    def test_start_failure_cost_is_preserved_without_restarting_unit_budget(self):
        result = policy.simulate(["left", "right"], [1],
                                 [event("start_failed", 0, startup_ms=1, cleanup_ms=1), event()],
                                 4, 3, max_attempts=2)
        self.assertEqual(result["end_reason"], "attempt_cap")
        self.assertEqual(result["consumed_ms"], 3)
        self.assertEqual(result["remaining_ms"], 1)
        self.assertEqual([row["target_id"] for row in result["attempts"]], ["left", "right"])
        self.assertEqual(result["attempts"][0]["outcome"], "start_failed")
        self.assertEqual(result["attempts"][0]["process_wall_ms"], 0)
        self.assertEqual(result["attempts"][0]["debit_ms"], 2)

    def test_reap_or_persistence_failure_stops_without_reporting_budget_success(self):
        failures = [
            ("reap_failed", [event(reaped=False)], {}),
            ("persistence_failed", [event()], {"save_failure_at": 0}),
        ]
        for reason, events, options in failures:
            with self.subTest(reason=reason):
                result = policy.simulate(["left", "right"], [1], events, 10, 4, **options)
                self.assertEqual(result["end_reason"], reason)
                self.assertEqual(len(result["attempts"]), 1)
                self.assertEqual(result["consumed_ms"], 1)
                self.assertEqual(result["remaining_ms"], 9)

    def test_clock_stall_stops_and_zero_budget_never_creates_zero_allocation(self):
        stalled = policy.simulate(["one"], [1], [event(duration_ms=0)], 3, 2)
        self.assertEqual(stalled["end_reason"], "clock_stalled")
        self.assertLessEqual(len(stalled["attempts"]), 1)
        self.assertEqual(stalled["consumed_ms"], 0)
        self.assertEqual(stalled["remaining_ms"], 3)
        empty = policy.simulate(["one"], [1], [event()], 0, 2)
        self.assertEqual(empty["end_reason"], "budget_exhausted")
        self.assertEqual(empty["attempts"], [])
        for row in stalled["attempts"]:
            self.assertGreater(row["allocated_ms"], 0)

    def test_candidate_kind_does_not_change_fixed_target_or_seed_order(self):
        options = (["a", "b", "c"], [3, 11])
        negative = policy.simulate(*options, [event()], 8, 1)
        positive = policy.simulate(*options, [event("candidate", marker="opaque")], 8, 1)
        expected_targets = ["a", "b", "c", "a", "b", "c", "a", "b"]
        expected_seeds = [3, 3, 3, 11, 11, 11, 3, 3]
        for result in (negative, positive):
            self.assertEqual(result["end_reason"], "budget_exhausted")
            self.assertEqual([row["target_id"] for row in result["attempts"]], expected_targets)
            self.assertEqual([row["seed"] for row in result["attempts"]], expected_seeds)
            self.assertEqual(result["consumed_ms"], 8)

    def test_invalid_budget_or_empty_schedule_is_not_a_successful_execution(self):
        invalid = [([], [1], [event()], 3, 2),
                   (["one"], [], [event()], 3, 2),
                   (["one"], [0], [event()], 3, 2),
                   (["one"], [1], [], 3, 2),
                   (["one"], [1], [event()], -1, 2),
                   (["one"], [1], [event()], 3, 0)]
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                policy.simulate(*arguments)


if __name__ == "__main__":
    unittest.main()
