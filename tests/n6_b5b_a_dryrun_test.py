#!/usr/bin/env python3
"""Synthetic, offline checks for the five-revision A rerun orchestrator."""

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
import n6_b5b_a_dryrun as runner  # noqa: E402


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
if a.identifier == 'failed':
    sys.exit(9)
result = {'status':'base_input_unavailable', 'selected_stage':None,
          'stages':['a_zkbugs','b_l_series','c_committed_json','d_project_test','e_zero'],
          'failed_attempts':[{'stage':'d_project_test','reason':'committed_lock_missing'}]}
(d / 'selection.json').write_text(json.dumps(result))
index = a.output_root / 'index.json'
data = json.loads(index.read_text()) if index.exists() else {'revisions':{}}
data['revisions'][a.identifier] = result
index.write_text(json.dumps(data))
if a.identifier == 'mutates':
    with Path(__file__).open('a') as stream:
        stream.write('# synthetic collector changed between revisions\\n')
'''


class ABuildChainRerunTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.collector = self.root / "fake_collector.py"
        self.collector.write_text(FAKE_COLLECTOR)
        self.output = self.root / "a-dryrun-v2"

    def run_trial(self, identifiers: tuple[str, ...], start: datetime | None = None) -> tuple[int, str]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = runner.run_campaign(self.output, self.collector,
                                         start or datetime.now(timezone.utc), identifiers)
        return result, stdout.getvalue()

    def state(self, identifier: str) -> dict:
        return json.loads((self.output / identifier / "state.json").read_text())

    def test_fixed_queue_is_only_the_five_nested_build_revisions(self) -> None:
        self.assertEqual(runner.IDENTIFIERS, (
            "aq-011-93343c3cd34c", "aq-012-44d0df2ab46e", "aq-016-0a7d49b1c135",
            "aq-017-9703bbce0c43", "aq-024-6f6781246415"))
        self.assertEqual(runner.OUTPUT.name, "a-dryrun-v2")
        self.assertEqual(runner.CAMPAIGN_SECONDS, 90 * 60)
        self.assertEqual(runner.REVISION_SECONDS, 60 * 60)

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

    def test_zero_stage_pass_after_project_test_selection_is_recorded(self) -> None:
        selection = {"status": "passed", "selected_stage": "d_project_test",
                     "original_rule_stage": "e_zero", "stages": list(runner.STAGES),
                     "failed_attempts": []}
        state = runner.summarize_selection("synthetic", selection, 1.0)
        self.assertEqual(state["stages"]["d_project_test"], "passed")
        self.assertEqual(state["stages"]["e_zero"], "passed")
        self.assertEqual(state["stage"], "d_project_test")
        self.assertIsNone(state["reason"])

    def test_zero_stage_failure_after_project_test_selection_is_recorded(self) -> None:
        selection = {"status": "passed", "selected_stage": "d_project_test",
                     "original_rule_stage": "base_input_unavailable",
                     "stages": list(runner.STAGES),
                     "failed_attempts": [{"stage": "e_zero", "reason": "zero_witness_failed"}]}
        state = runner.summarize_selection("synthetic", selection, 1.0)
        self.assertEqual(state["stages"]["d_project_test"], "passed")
        self.assertEqual(state["stages"]["e_zero"], "failed")
        self.assertEqual(state["stage_reasons"]["e_zero"], ["zero_witness_failed"])

    def test_missing_zero_outcome_after_project_selection_fails_closed(self) -> None:
        selection = {"status": "passed", "selected_stage": "d_project_test",
                     "original_rule_stage": "base_input_unavailable",
                     "stages": list(runner.STAGES), "failed_attempts": []}
        with self.assertRaisesRegex(ValueError, "zero stage result missing"):
            runner.summarize_selection("synthetic", selection, 1.0)

    def test_early_selection_keeps_later_stages_not_run(self) -> None:
        selection = {"status": "passed", "selected_stage": "a_zkbugs",
                     "original_rule_stage": "a_zkbugs", "stages": list(runner.STAGES),
                     "failed_attempts": []}
        state = runner.summarize_selection("synthetic", selection, 1.0)
        self.assertEqual(state["stages"]["a_zkbugs"], "passed")
        self.assertEqual(state["stages"]["e_zero"], "not_run")

    def test_collector_exception_metadata_marks_reported_failure(self) -> None:
        selection = {"status": "base_input_unavailable", "selected_stage": None,
                     "original_rule_stage": "base_input_unavailable",
                     "failed_attempts": [{"stage": "d_project_test", "reason": "collector_policy_error"}]}
        state = runner.summarize_selection("synthetic", selection, 1.0)
        self.assertEqual(state["stages"]["d_project_test"], "failed")
        self.assertEqual(state["stages"]["e_zero"], "not_run")

    def test_expired_ninety_minute_budget_marks_everything_time_not_run(self) -> None:
        code, stdout = self.run_trial(("first", "second"),
                                      datetime.now(timezone.utc) - timedelta(minutes=91))
        self.assertEqual(code, 0)
        self.assertEqual(len(stdout.splitlines()), 2)
        for identifier in ("first", "second"):
            self.assertEqual(self.state(identifier)["status"], "time_not_run")
            self.assertFalse((self.output / identifier / "collector.stdout.log").exists())

    def test_campaign_start_persists_and_cannot_reset_on_resume(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(minutes=89)
        code, _ = self.run_trial(("first",), start)
        self.assertEqual(code, 0)
        saved = json.loads((self.output / "campaign.json").read_text())
        self.assertAlmostEqual(datetime.fromisoformat(saved["started_at_utc"]).timestamp(),
                               start.timestamp(), delta=0.01)
        with self.assertRaisesRegex(ValueError, "start cannot change"):
            runner.run_campaign(self.output, self.collector, datetime.now(timezone.utc),
                                ("first",))

    def test_collector_hash_change_cannot_resume_old_campaign(self) -> None:
        self.run_trial(("first",))
        self.collector.write_text(FAKE_COLLECTOR + "\n# changed\n")
        with self.assertRaisesRegex(ValueError, "collector changed"):
            runner.run_campaign(self.output, self.collector, identifiers=("first",))

    def test_collector_change_between_revisions_stops_without_replacing_first_result(self) -> None:
        code, stdout = self.run_trial(("mutates", "second", "third"))
        self.assertEqual(code, 1)
        self.assertEqual([line.split()[0] for line in stdout.splitlines()],
                         ["mutates", "second", "third"])
        self.assertEqual(self.state("mutates")["status"], "base_input_unavailable")
        changed = self.state("second")
        self.assertEqual(changed["status"], "collector_changed")
        self.assertEqual(changed["reason"], "collector_sha256_changed_during_campaign")
        self.assertNotEqual(changed["expected_collector_sha256"],
                            changed["observed_collector_sha256"])
        self.assertEqual(self.state("third")["status"], "not_run_after_stop")
        self.assertFalse((self.output / "second/collector.stdout.log").exists())
        self.assertFalse((self.output / "third/collector.stdout.log").exists())
        self.assertTrue((self.output / "mutates/selection.json").is_file())

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

    def test_collector_failure_stops_following_revisions(self) -> None:
        code, _ = self.run_trial(("failed", "second"))
        self.assertEqual(code, 1)
        self.assertEqual(self.state("failed")["status"], "collector_error")
        self.assertEqual(self.state("second")["status"], "not_run_after_stop")
        self.assertFalse((self.output / "second/collector.stdout.log").exists())

    def test_existing_old_output_is_untouched(self) -> None:
        old_output = self.root / "a-dryrun"
        old_output.mkdir()
        marker = old_output / "preserve.txt"
        marker.write_text("original")
        self.run_trial(("first",))
        self.assertEqual(marker.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
