#!/usr/bin/env python3
"""Synthetic, offline checks for the remaining A trial orchestrator."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_b5_a_dryrun_remaining_v1 as runner  # noqa: E402


FAKE_COLLECTOR = '''#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys
import time
p = argparse.ArgumentParser()
p.add_argument('--scope')
p.add_argument('--identifier')
p.add_argument('--output-root', type=Path)
a = p.parse_args()
assert a.scope == 'A'
d = a.output_root / a.identifier
d.mkdir(parents=True, exist_ok=True)
print('PRIVATE_CAPTURE_DO_NOT_ECHO')
if a.identifier == 'blocked':
    (d / 'environment-blocked.json').write_text(json.dumps({'reason':'Docker unavailable'}))
    sys.exit(3)
if a.identifier == 'slow':
    time.sleep(2)
result = {'status':'base_input_unavailable', 'selected_stage':None,
          'stages':['a_zkbugs','b_l_series','c_committed_json','d_project_test','e_zero'],
          'failed_attempts':[{'stage':'d_project_test','reason':'committed_lock_missing'}]}
(d / 'selection.json').write_text(json.dumps(result))
index = a.output_root / 'index.json'
data = json.loads(index.read_text()) if index.exists() else {'revisions':{}}
data['revisions'][a.identifier] = result
index.write_text(json.dumps(data))
'''


class RemainingATest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.collector = self.root / "fake_collector.py"
        self.collector.write_text(FAKE_COLLECTOR)
        self.output = self.root / "a-dryrun/remaining"

    def run_trial(self, identifiers: tuple[str, ...], start: datetime | None = None) -> tuple[int, str]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = runner.run_campaign(self.output, self.collector,
                                         start or datetime.now(timezone.utc), identifiers)
        return result, stdout.getvalue()

    def state(self, identifier: str) -> dict:
        return json.loads((self.output / identifier / "state.json").read_text())

    def test_fixed_queue_excludes_first_trial_and_b(self) -> None:
        self.assertEqual(len(runner.IDENTIFIERS), 9)
        self.assertEqual(len(set(runner.IDENTIFIERS)), 9)
        self.assertTrue(all(identifier.startswith("aq-") for identifier in runner.IDENTIFIERS))
        self.assertFalse(any("aq-025" in identifier for identifier in runner.IDENTIFIERS))

    def test_sequential_stage_records_and_private_collector_output(self) -> None:
        code, stdout = self.run_trial(("first", "second"))
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[0] for line in stdout.splitlines()], ["first", "second"])
        self.assertNotIn("PRIVATE_CAPTURE_DO_NOT_ECHO", stdout)
        for identifier in ("first", "second"):
            state = self.state(identifier)
            self.assertEqual(state["status"], "base_input_unavailable")
            self.assertEqual(state["stage"], "d_project_test")
            self.assertEqual(state["reason"], "committed_lock_missing")
            self.assertGreaterEqual(state["seconds"], 0)
            self.assertEqual(state["stages"]["d_project_test"], "failed")
            self.assertIn("PRIVATE_CAPTURE_DO_NOT_ECHO",
                          (self.output / identifier / "collector.stdout.log").read_text())

    def test_expired_three_hour_budget_marks_everything_time_not_run(self) -> None:
        code, stdout = self.run_trial(("first", "second"),
                                      datetime.now(timezone.utc) - timedelta(hours=4))
        self.assertEqual(code, 0)
        self.assertEqual(len(stdout.splitlines()), 2)
        for identifier in ("first", "second"):
            self.assertEqual(self.state(identifier)["status"], "time_not_run")
            self.assertFalse((self.output / identifier / "collector.stdout.log").exists())

    def test_environment_block_stops_later_trials(self) -> None:
        code, _ = self.run_trial(("blocked", "second"))
        self.assertEqual(code, 1)
        self.assertEqual(self.state("blocked")["status"], "environment_blocked")
        self.assertEqual(self.state("second")["status"], "not_run_after_stop")
        self.assertFalse((self.output / "second/collector.stdout.log").exists())

    def test_revision_timeout_does_not_extend_campaign(self) -> None:
        with patch.object(runner, "REVISION_SECONDS", 0.1):
            code, _ = self.run_trial(("slow",))
        self.assertEqual(code, 0)
        self.assertEqual(self.state("slow")["status"], "revision_timeout")


if __name__ == "__main__":
    unittest.main()
