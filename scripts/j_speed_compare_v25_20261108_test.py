#!/usr/bin/env python3
"""Synthetic clock/record tests; never run a preserved candidate or compiler."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import j_speed_compare_v25_20261108 as runner


class SuspendTests(unittest.TestCase):
    def test_sleep_invalidates_even_when_monotonic_time_is_short(self):
        before = {"continuous": 100.0, "awake": 90.0}
        valid = runner.sleep_assessment(before, {"continuous": 103.0, "awake": 93.0}, "synthetic")
        invalid = runner.sleep_assessment(before, {"continuous": 133.0, "awake": 93.0}, "synthetic")
        self.assertTrue(valid["valid_without_suspend"])
        self.assertFalse(invalid["valid_without_suspend"])
        self.assertEqual(invalid["suspended_seconds"], 30.0)

    def test_native_clock_can_be_read_without_launching_work(self):
        clock = runner.SuspendClock()
        before = clock.sample()
        after = clock.sample()
        self.assertTrue(runner.sleep_assessment(before, after, clock.source)["valid_without_suspend"])

    def test_summary_excludes_suspended_cost_but_retains_differential_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = {"request_index": 0, "execution_valid": True, "semantic_equal": True, "basis_equal": True,
                   "resources": {"wall_seconds": 3.0, "cpu_seconds": 2.0},
                   "comparisons": {"j1": {"baseline_wall_seconds": 4.0, "baseline_cpu_seconds": 3.0}}}
            for i in range(2):
                item = copy.deepcopy(row)
                item.update(request_index=i, execution_valid=i == 0)
                directory = root / "requests" / f"{i:02d}"
                directory.mkdir(parents=True)
                (directory / "record.json").write_text(json.dumps(item))
            result = runner.summary(root)
            self.assertEqual(result["recorded"], 2)
            self.assertEqual(result["semantic_equal"], 2)
            self.assertEqual(result["execution_valid"], 1)
            self.assertEqual(result["timing_comparison"]["v25_wall_seconds"], 3.0)


if __name__ == "__main__":
    unittest.main()
