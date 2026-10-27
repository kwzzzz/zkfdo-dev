"""Checks for the S-only B rerun adapter without starting a campaign."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_n6_b5_s_nested_queue.py"
spec = importlib.util.spec_from_file_location("n6_b5_s_nested_queue_under_test", SCRIPT)
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
assert spec.loader is not None
spec.loader.exec_module(runner)


class FakeHealth:
    def assess_unit(self, _start_ns, _end_ns):
        return {"environment_pressure": False, "reasons": []}


class N6B5SNestedQueueTest(unittest.TestCase):
    def test_binary_change_is_the_only_allowed_spec_change(self):
        old = {"pinned_files": [{"path": "/old/zkfuzz", "sha256": "old"}],
               "targets": [{"command": ["/old/zkfuzz", "circuit.circom"]}],
               "total_budget_seconds": 3600}
        new = {"pinned_files": [{"path": "/new/zkfuzz", "sha256": "new"}],
               "targets": [{"command": ["/new/zkfuzz", "circuit.circom"]}],
               "total_budget_seconds": 3600}
        self.assertTrue(runner.binary_only_spec_change(
            old, new, "/old/zkfuzz", "old", "/new/zkfuzz", "new"))
        changed_budget = json.loads(json.dumps(new))
        changed_budget["total_budget_seconds"] = 7200
        self.assertFalse(runner.binary_only_spec_change(
            old, changed_budget, "/old/zkfuzz", "old", "/new/zkfuzz", "new"))

    def test_run_unit_calls_only_s_and_marks_runner_interruption_for_retry(self):
        unit = {"unit_id": "synthetic-seed-1"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(runner.base, "run_method", return_value={
                    "status": "runner_nonzero", "exit_code": 2}) as called:
                row = runner.run_s_unit(unit, {}, output, FakeHealth(), 1,
                                        "primary", 0.0, 1)
            self.assertEqual(called.call_count, 1)
            self.assertEqual(called.call_args.args[1], "S")
            self.assertEqual(set(row["methods"]), {"S"})
            self.assertTrue(runner.needs_retry(row))
            self.assertTrue((output / "units/synthetic-seed-1/runs/01-primary/unit-run.json").is_file())

    def test_pressure_triggers_one_retry_even_when_s_completed(self):
        row = {"methods": {"S": {"status": "completed"}},
               "environment": {"environment_pressure": True}}
        self.assertTrue(runner.needs_retry(row))
        row["environment"]["environment_pressure"] = False
        self.assertFalse(runner.needs_retry(row))


if __name__ == "__main__":
    unittest.main()
