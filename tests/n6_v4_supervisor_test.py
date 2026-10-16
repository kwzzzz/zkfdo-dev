"""Standalone N6 v4 supervisor failure-recording tests; no campaign execution."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
MODULE = REPOSITORY / "scripts/run_n6_v4_campaigns.py"
SPEC = importlib.util.spec_from_file_location("n6_v4_supervisor_test_module", MODULE)
supervisor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = supervisor
SPEC.loader.exec_module(supervisor)


class N6V4SupervisorTest(unittest.TestCase):
    def test_pin_failure_is_written_to_final_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            manifest_path = root / "manifest.json"
            summary_path = root / "output/execution-summary.json"
            manifest = {
                "status": "prepared_not_executed",
                "order": ["A", "B"],
                "queue_runner": {"path": "missing-runner.py", "sha256": "0" * 64},
                "runner": {"path": "missing-engine.py", "sha256": "0" * 64},
                "supervisor": {"path": "missing-supervisor.py", "sha256": "0" * 64},
                "queues": {},
                "outputs": {
                    "events": "output/events.jsonl",
                    "summary": "output/execution-summary.json",
                },
            }
            manifest_path.write_text(json.dumps(manifest) + "\n")
            with patch.object(supervisor, "ROOT", root), patch.object(
                    sys, "argv", ["run_n6_v4_campaigns.py", "--manifest", str(manifest_path)]):
                with self.assertRaises(ValueError):
                    supervisor.main()
            summary = json.loads(summary_path.read_text())
            self.assertEqual(summary["status"], "supervisor_error")
            self.assertEqual(summary["error"]["type"], "ValueError")
            self.assertIn("pinned file changed", summary["error"]["message"])
            self.assertIsNotNone(summary["finished_at"])


if __name__ == "__main__":
    unittest.main()
