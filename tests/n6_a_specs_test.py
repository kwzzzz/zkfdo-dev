import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class N6ASpecTest(unittest.TestCase):
    def test_queue_and_specs_preserve_protocol_budget(self):
        path = ROOT / "runs/n6-a1-2026-10-07/queue-v2.json"
        if not path.exists():
            self.skipTest("spec generation has not run")
        queue = json.loads(path.read_text())
        self.assertEqual(queue["preflight_spec_count"], len(queue["units"]) * 2)
        for unit in queue["units"]:
            whole = json.loads((ROOT / unit["whole_spec"]).read_text())
            split = json.loads((ROOT / unit["split_spec"]).read_text())
            self.assertEqual(whole["total_budget_seconds"], 600)
            self.assertEqual(whole["attempt_cap_seconds"], 600)
            self.assertEqual(split["total_budget_seconds"], 600)
            self.assertEqual(split["attempt_cap_seconds"], 30)
            self.assertEqual(whole["initial_seed"], split["initial_seed"])


if __name__ == "__main__":
    unittest.main()
