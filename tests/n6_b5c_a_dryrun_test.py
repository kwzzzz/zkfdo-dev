#!/usr/bin/env python3
"""Offline checks for the bounded, three-round A tool rerun."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_b5c_a_dryrun as runner  # noqa: E402


FAKE_COLLECTOR = '''#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys
p = argparse.ArgumentParser()
p.add_argument('--scope')
p.add_argument('--identifier')
p.add_argument('--tools', type=Path)
p.add_argument('--output-root', type=Path)
a = p.parse_args()
assert a.scope == 'A' and a.tools.is_file()
d = a.output_root / a.identifier
d.mkdir(parents=True, exist_ok=True)
print('PRIVATE_CAPTURE_DO_NOT_ECHO')
if a.identifier == 'tool':
    (d / 'tool-blocked.json').write_text(json.dumps({
        'status': 'tool_blocked', 'reason': 'container_git_missing'}))
    sys.exit(3)
if a.identifier == 'environment':
    (d / 'environment-blocked.json').write_text(json.dumps({
        'status': 'environment_blocked', 'reason': 'network blocked'}))
    sys.exit(3)
if a.identifier == 'changed':
    with Path(__file__).open('a') as stream:
        stream.write('# synthetic changed\\n')
result = {'status':'base_input_unavailable', 'selected_stage':None,
          'stages':['a_zkbugs','b_l_series','c_committed_json','d_project_test','e_zero'],
          'failed_attempts':[{'stage':'d_project_test','reason':'committed_lock_missing'}]}
(d / 'selection.json').write_text(json.dumps(result))
index = a.output_root / 'index.json'
data = json.loads(index.read_text()) if index.exists() else {'revisions':{}}
data['revisions'][a.identifier] = result
index.write_text(json.dumps(data))
'''


class AThreeRoundRerunTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.collector = self.root / "fake_collector.py"
        self.collector.write_text(FAKE_COLLECTOR)
        self.tools = self.root / "install-tools.json"
        self.tools.write_text(json.dumps({"image": "node@sha256:" + "a" * 64}))
        self.output = self.root / "a-dryrun-v3"

    def run_trial(self, identifiers: tuple[str, ...], round_number: int = 1,
                  start: datetime | None = None) -> tuple[int, str]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = runner.run_campaign(self.output, self.collector, self.tools,
                                       round_number, start, identifiers)
        return code, stdout.getvalue()

    def state(self, identifier: str, round_number: int = 1) -> dict:
        path = runner.round_output(self.output, round_number) / identifier / "state.json"
        return json.loads(path.read_text())

    def test_fixed_queue_output_and_limits(self) -> None:
        self.assertEqual(runner.IDENTIFIERS, (
            "aq-011-93343c3cd34c", "aq-012-44d0df2ab46e", "aq-016-0a7d49b1c135",
            "aq-017-9703bbce0c43", "aq-024-6f6781246415"))
        self.assertEqual(runner.OUTPUT.name, "a-dryrun-v3")
        self.assertEqual(runner.CAMPAIGN_SECONDS, 7200)
        self.assertEqual(runner.REVISION_SECONDS, 3600)
        self.assertEqual(runner.MAX_ROUNDS, 3)
        self.assertEqual(runner.round_output(self.output, 2), self.output / "round-2")
        with self.assertRaisesRegex(ValueError, "only rounds"):
            runner.round_output(self.output, 4)

    def test_serial_and_private_output(self) -> None:
        code, stdout = self.run_trial(("one", "two"))
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[0] for line in stdout.splitlines()], ["one", "two"])
        self.assertNotIn("PRIVATE_CAPTURE_DO_NOT_ECHO", stdout)
        for identifier in ("one", "two"):
            self.assertEqual(self.state(identifier)["status"], "base_input_unavailable")
            self.assertEqual(self.state(identifier)["stages"]["d_project_test"], "failed")
            self.assertIn("PRIVATE_CAPTURE_DO_NOT_ECHO",
                          (self.output / identifier / "collector.stdout.log").read_text())
        first = json.loads((self.output / "round.json").read_text())
        self.assertEqual(first["collector_sha256"], runner.previous.sha256(self.collector))
        self.assertEqual(first["tools_sha256"], runner.previous.sha256(self.tools))
        self.assertEqual(first["image"], "node@sha256:" + "a" * 64)

    def test_tool_block_stops_remaining_revisions(self) -> None:
        code, _ = self.run_trial(("tool", "later"))
        self.assertEqual(code, 1)
        self.assertEqual(self.state("tool")["status"], "tool_blocked")
        self.assertEqual(self.state("tool")["stages"]["d_project_test"], "tool_blocked")
        self.assertEqual(self.state("later")["status"], "not_run_after_stop")
        self.assertFalse((self.output / "later/collector.stdout.log").exists())

    def test_environment_block_also_stops(self) -> None:
        code, _ = self.run_trial(("environment", "later"))
        self.assertEqual(code, 1)
        self.assertEqual(self.state("environment")["status"], "environment_blocked")
        self.assertEqual(self.state("later")["status"], "not_run_after_stop")

    def test_rounds_reuse_first_start_and_allow_tool_fix(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(minutes=3)
        self.run_trial(("tool", "later"), start=start)
        self.tools.write_text(json.dumps({"image": "node@sha256:" + "b" * 64}))
        self.collector.write_text(FAKE_COLLECTOR.replace("if a.identifier == 'tool':", "if False:"))
        code, _ = self.run_trial(("tool", "later"), round_number=2)
        self.assertEqual(code, 0)
        self.assertEqual(self.state("tool", 2)["status"], "base_input_unavailable")
        self.assertEqual(self.state("later", 2)["status"], "base_input_unavailable")
        self.assertEqual(self.state("tool")["status"], "tool_blocked")
        self.assertEqual(json.loads((self.output / "round.json").read_text())["image"],
                         "node@sha256:" + "a" * 64)
        self.assertEqual(json.loads((self.output / "round-2/round.json").read_text())["image"],
                         "node@sha256:" + "b" * 64)
        with self.assertRaisesRegex(ValueError, "start cannot change"):
            self.run_trial(("tool", "later"), round_number=3,
                           start=datetime.now(timezone.utc))

    def test_round_two_requires_finished_round_one(self) -> None:
        with self.assertRaisesRegex(ValueError, "preceding A round is missing"):
            self.run_trial(("one",), round_number=2)
        self.run_trial(("one", "two"))
        (self.output / "two/state.json").unlink()
        with self.assertRaisesRegex(ValueError, "preceding A round is incomplete"):
            self.run_trial(("one", "two"), round_number=2)

    def test_two_hour_clock_shared_by_later_rounds(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(hours=2, minutes=1)
        self.run_trial(("tool", "later"), start=start)
        self.collector.write_text(FAKE_COLLECTOR.replace("if a.identifier == 'tool':", "if False:"))
        code, _ = self.run_trial(("tool", "later"), round_number=2)
        self.assertEqual(code, 0)
        self.assertEqual(self.state("tool", 2)["status"], "time_not_run")
        self.assertEqual(self.state("later", 2)["status"], "time_not_run")
        self.assertFalse((self.output / "round-2/tool/collector.stdout.log").exists())
        saved = json.loads((self.output / "campaign.json").read_text())
        self.assertAlmostEqual(datetime.fromisoformat(saved["started_at_utc"]).timestamp(),
                               start.timestamp(), delta=0.01)

    def test_mid_round_collector_change_stops(self) -> None:
        code, _ = self.run_trial(("changed", "later"))
        self.assertEqual(code, 1)
        self.assertEqual(self.state("changed")["status"], "base_input_unavailable")
        self.assertEqual(self.state("later")["status"], "collector_changed")

    def test_prior_output_is_untouched(self) -> None:
        for name in ("a-dryrun", "a-dryrun-v2"):
            path = self.root / name
            path.mkdir()
            (path / "marker.txt").write_text("preserve")
        self.run_trial(("one",))
        for name in ("a-dryrun", "a-dryrun-v2"):
            self.assertEqual((self.root / name / "marker.txt").read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
