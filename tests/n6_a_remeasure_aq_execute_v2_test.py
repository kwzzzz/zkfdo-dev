#!/usr/bin/env python3
"""Temp-only v2 state-machine tests. All engine, join and scorer calls are mocked."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_a_remeasure_aq_execute_v2 as aq


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / "aq-exec"
        self.external = self.root / "image/j"
        self.output.mkdir()
        self.external.mkdir(parents=True)
        self.input_shas = {}
        self.rows = []
        self.outcomes = {}
        self.preparation_reasons = {}
        self.stderr_text = {}
        self.calls = []
        self.scored = []
        self.clock = datetime(2026, 10, 26, tzinfo=timezone.utc)
        self.deadline = self.clock + timedelta(days=2)
        original_owned = aq.owned
        self.patch(aq, "OUTPUT", self.output)
        self.patch(aq, "EXTERNAL", self.external)
        self.patch(aq, "MOUNT", self.external.parent)
        self.patch(aq, "ROOT", self.root)
        self.patch(aq, "INPUT_SHA256", self.input_shas)
        self.patch(aq, "STOP_SIGNAL", None)
        self.patch(aq, "owned", lambda path, boundary=None: original_owned(
            path, self.output if boundary is None else boundary))
        self.configure = self.patch(aq, "configure", Mock())
        self.patch(aq, "mount_check", Mock(side_effect=lambda: self.space()))
        self.patch(aq, "reserve_bytes", Mock(return_value={
            "retained_evidence_bytes": 0}))
        self.patch(aq, "legacy_peak", Mock(return_value=aq.INITIAL_PEAK))
        self.patch(aq.runner, "checked_request_sources", Mock())
        self.patch(aq.runner, "initialize_cache", Mock(side_effect=self.cache))
        self.patch(aq.runner, "probe_time_l", Mock(return_value={"measurement_method": "synthetic"}))
        self.patch(aq.runner, "disk_free", Mock(return_value=300 * aq.GIB))
        self.lift = self.patch(aq.runner, "run_lift", Mock(side_effect=self.lift_result))
        self.join = self.patch(aq.runner, "join_instances", Mock(side_effect=self.join_results))
        self.real_score_revision = aq.score_revision
        self.scorer = self.patch(aq, "score_revision", Mock(side_effect=self.score))
        self.cleanup = self.patch(aq, "cleanup_request", Mock(side_effect=self.verify_cleanup))
        self.revision_cleanup = self.patch(aq, "revision_cleanup", Mock(return_value=0))
        # Any omitted process mock fails immediately instead of reaching a real tool.
        self.process = self.patch(aq.subprocess, "run", Mock(side_effect=AssertionError(
            "real subprocess forbidden in synthetic tests")))
        clock_mock = self.patch(aq, "datetime", Mock(wraps=datetime))
        clock_mock.now.side_effect = lambda _zone=None: self.clock
        self.stdout = io.StringIO()
        self.redirect = redirect_stdout(self.stdout)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def patch(self, obj, key, value):
        patcher = patch.object(obj, key, value)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def write(self, path, value):
        aq.runner.atomic_json(path, value)
        return aq.runner.sha256(path)

    def space(self, *, external=None, repo=None):
        return {"external_free_bytes": 300 * aq.GIB if external is None else external,
                "repo_free_bytes": 100 * aq.GIB if repo is None else repo,
                "mounted": True, "mount": str(self.external.parent), "j_root": str(self.external)}

    def cache(self, root, scope, ordinal, _revision, _index_sha):
        path = root / scope / f"{ordinal:04d}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def row(self, queue, revision="r1"):
        base = self.root / "inputs" / revision / "input.json"
        self.input_shas[revision] = self.write(base, {"synthetic": revision})
        path = self.root / "requests" / f"{queue}.json"
        sha = self.write(path, {"id": f"request-{queue}", "base_input": str(base)})
        row = {"queue_order": queue, "revision_id": revision, "scope": "main", "method": "S",
               "request": str(path), "request_sha256": sha, "candidate_sha256": "c" * 64}
        self.rows.append(row)
        return row

    def state(self):
        return {"schema": aq.SCHEMA, "layer": aq.LAYER, "config": {}, "status": "ready",
                "active_revision": None, "revisions": {},
                "engines": {e: {"requests": {}, "groups": {}} for e in aq.ENGINES},
                "observed_request_peak_bytes": aq.INITIAL_PEAK, "cleanup_receipts": [],
                "request_failure_streak": {}, "revision_failure_streak": {}}

    def lift_result(self, row, workspace, _cache, _store, attempt, _method):
        engine = workspace.relative_to(self.external).parts[0]
        self.calls.append((engine, row["revision_id"], row["queue_order"], attempt))
        choices = self.outcomes.get(row["queue_order"], [0])
        outcome = choices[min(attempt - 1, len(choices) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        workspace.mkdir(parents=True)
        result = {"schema": "zkfdo-lifting-result-v1", "request_id": f"request-{row['queue_order']}",
                  "request_sha256": row["request_sha256"], "candidate_sha256": row["candidate_sha256"],
                  "preparation": {"status": "failed" if outcome == "preparation" else "ok"},
                  "classes": [{"representative": "main.synthetic", "verdict": "entrypoint_violation"}]}
        if outcome == "preparation" and row["queue_order"] in self.preparation_reasons:
            result["preparation"]["reason"] = self.preparation_reasons[row["queue_order"]]
        self.write(workspace / "result.json", result)
        metrics = {"exit_code": 0 if outcome == "preparation" else outcome,
                   "wall_seconds": 1.25, "max_rss_bytes": 1024, "measurement_method": "synthetic"}
        if row["queue_order"] in self.stderr_text:
            stderr = workspace.with_suffix(".stderr.log")
            stderr.write_text(self.stderr_text[row["queue_order"]])
            metrics["stderr_path"] = str(stderr)
        return metrics

    def join_results(self, paths, output, target, _method):
        self.write(target, {"schema": "zkfdo-instance-verdicts-v1", "conflicts": 0,
                           "results": [str(path.relative_to(output)) for path in paths], "classes": []})
        return {"exit_code": 0, "wall_seconds": 0.5, "measurement_method": "synthetic"}

    def score(self, _state, engine, revision):
        self.scored.append((engine, revision))
        path = self.output / "rqc" / f"synthetic-{len(self.scored)}.json"
        sha = self.write(path, {"layer": "exploratory", "engine": engine})
        return {"status": "completed", "path": str(path), "sha256": sha}

    def verify_cleanup(self, _state, engine, row, event, **_kwargs):
        # Cleanup is reached only after both immutable evidence hashes are valid.
        aq.checked_event(engine, row, event)
        return 0

    def indexes(self):
        return {e: {"requests": self.rows} for e in aq.ENGINES}

    def order(self):
        return [{"engine": e, "revision": r["revision_id"], "queue_order": r["queue_order"],
                 "mapped": False} for e in aq.ENGINES for r in self.rows]

    def execute(self, state=None, revisions=None):
        state = self.state() if state is None else state
        revisions = revisions or tuple(dict.fromkeys(r["revision_id"] for r in self.rows))
        with patch.object(aq, "DEFAULT_REVISIONS", revisions):
            result = aq.execute(state, self.indexes(), self.order(), self.deadline)
        return state, result

    def request(self, state, row, engine="v2.2"):
        aq.run_request(state, engine, row, "main", 1, self.deadline)
        return state["engines"][engine]["requests"][str(row["queue_order"])]

    def progress_lines(self):
        return [json.loads(line) for line in (self.output / "progress-v2.jsonl").read_text().splitlines()]

    def legacy_binding(self):
        return {"plan_sha256": "p" * 64, "index_sha256": {e: e for e in aq.ENGINES},
                "engine_sha256": {e: e for e in aq.ENGINES}, "external_root": str(self.external)}

    def import_state(self, state):
        (self.output / "state-v2.json").unlink(missing_ok=True)
        binding = self.legacy_binding()
        self.write(self.output / "state.json", {"schema": "n6-a-remeasure-aq-execute-v1",
                   "config": binding, "engines": state["engines"]})
        return aq.load_state(binding), binding

    def test_request_failure_continues_to_next_request_and_engine(self):
        self.row(1)
        self.row(2)
        self.outcomes[1] = [7]
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual([c[:3] for c in self.calls], [
            (e, "r1", q) for e in aq.ENGINES for q in (1, 2)])
        for engine in aq.ENGINES:
            self.assertEqual(state["engines"][engine]["requests"]["1"]["failure_reason"], "lift_exit_7")
            self.assertEqual(state["engines"][engine]["requests"]["2"]["status"], "completed")
        self.assertEqual([p["failures"] for p in self.progress_lines()], [1, 1])

    def test_runner_exception_is_recorded_and_does_not_skip_next_request(self):
        self.row(1)
        self.row(2)
        self.outcomes[1] = [OSError(5, "synthetic I/O failure")]
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["engines"]["v2.2"]["requests"]["1"]["failure_reason"], "OSError:errno=5")
        self.assertEqual(len(self.calls), 4)

    def test_low_disk_failure_retries_once_only_after_gate(self):
        row = self.row(1)
        self.outcomes[1] = [7, 0]
        aq.runner.disk_free.side_effect = [aq.GIB - 1, 100 * aq.GIB]
        gates = []

        def gate(_state):
            gates.append(len(self.calls))
            return self.space()

        with patch.object(aq, "request_guard", side_effect=gate):
            event = self.request(self.state(), row)
        self.assertEqual(gates, [0, 1])
        self.assertEqual([c[3] for c in self.calls], [1, 2])
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["disk_retries"], 1)
        self.assertFalse(event["retry_pending"])
        self.assertTrue(event["history"][0]["retry_pending"])

    def test_low_disk_retry_exhaustion_continues_without_third_attempt(self):
        first, second = self.row(1), self.row(2)
        self.outcomes[1] = [7, 7, 0]
        aq.runner.disk_free.return_value = aq.GIB - 1
        state = self.state()
        event = self.request(state, first)
        self.request(state, second)
        self.assertEqual([(c[2], c[3]) for c in self.calls], [(1, 1), (1, 2), (2, 1)])
        self.assertEqual(event["status"], "failed")
        self.assertFalse(event["retry_pending"])
        self.assertEqual(event["disk_retries"], 1)

    def test_fifth_same_request_failure_stops(self):
        for q in range(1, 7):
            self.row(q)
            self.outcomes[q] = [7]
        state, result = self.execute()
        self.assertEqual(result["stop_kind"], "repeated_request_failure")
        self.assertEqual([c[2] for c in self.calls], [1, 2, 3, 4, 5])
        self.assertEqual(state["request_failure_streak"], {"reason": "lift_exit_7", "count": 5})
        self.assertNotIn("6", state["engines"]["v2.2"]["requests"])

    def test_request_streak_resets_on_different_reason_and_success(self):
        outcomes = [7] * 4 + [8] * 4 + [0] + [8] * 4
        state = self.state()
        for q, exit_code in enumerate(outcomes, 1):
            row = self.row(q)
            self.outcomes[q] = [exit_code]
            self.request(state, row)
            if q in (5, 9):
                expected = {} if q == 9 else {"reason": "lift_exit_8", "count": 1}
                self.assertEqual(state["request_failure_streak"], expected)
        self.assertEqual(state["request_failure_streak"], {"reason": "lift_exit_8", "count": 4})

    def test_preparation_failure_is_terminal_and_continues(self):
        self.row(1)
        self.row(2)
        self.outcomes[1] = ["preparation"]
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["engines"]["v2.2"]["requests"]["1"]["status"], "preparation_failure")
        self.assertEqual([p["preparation_failure"] for p in self.progress_lines()], [1, 1])

    def test_distinct_preparation_causes_reset_the_request_failure_streak(self):
        state = self.state()
        for queue, reason in ((1, "compile_failed"), (2, "missing_main")):
            row = self.row(queue)
            self.outcomes[queue] = ["preparation"]
            self.preparation_reasons[queue] = reason
            event = self.request(state, row)
            self.assertEqual(event["failure_reason"], "preparation:" + reason)
            self.assertEqual(state["request_failure_streak"], {
                "reason": "preparation:" + reason, "count": 1})

    def test_five_same_preparation_causes_stop_the_request_sequence(self):
        for queue in range(1, 7):
            self.row(queue)
            self.outcomes[queue] = ["preparation"]
            self.preparation_reasons[queue] = "compile_failed"
        state, result = self.execute()
        self.assertEqual(result["stop_kind"], "repeated_request_failure")
        self.assertEqual([call[2] for call in self.calls], [1, 2, 3, 4, 5])
        self.assertEqual(state["request_failure_streak"], {
            "reason": "preparation:compile_failed", "count": 5})

    def test_distinct_preparation_causes_do_not_trigger_same_revision_cause_stop(self):
        for queue, reason in ((1, "compile_failed"), (2, "missing_main")):
            self.row(queue, f"r{queue}")
            self.outcomes[queue] = ["preparation"]
            self.preparation_reasons[queue] = reason
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.calls), 4)
        self.assertEqual([line["revision_status"] for line in self.progress_lines()], ["failed"] * 4)
        self.assertEqual(state["revision_failure_streak"]["count"], 1)

    def test_same_exit_code_with_distinct_stderr_causes_resets_failure_streak(self):
        state = self.state()
        for queue, message in ((1, "error: missing compiler"), (2, "error: invalid source")):
            row = self.row(queue)
            self.outcomes[queue] = [7]
            self.stderr_text[queue] = "synthetic log header\n" + message + "\n"
            event = self.request(state, row)
            self.assertEqual(event["failure_reason"], "lift_exit_7:" + message)
            self.assertEqual(event["failure_detail"], message)
            self.assertEqual(event["failure_diagnostic"], message)
            self.assertEqual(event["stderr_sha256"], aq.runner.sha256(Path(event["stderr_path"])))
            self.assertEqual(state["request_failure_streak"]["count"], 1)
            aq.checked_event("v2.2", row, event)

    def test_stderr_same_cause_normalizes_request_paths_for_streaks(self):
        state = self.state()
        for queue in range(1, 3):
            row = self.row(queue)
            self.outcomes[queue] = [7]
            self.stderr_text[queue] = f"error: failed to compile /synthetic/request-{queue}\n"
            event = self.request(state, row)
        self.assertEqual(event["failure_reason"], "lift_exit_7:error: failed to compile <path>")
        self.assertEqual(state["request_failure_streak"]["count"], 2)

    def test_revision_prepare_failure_continues_to_next_revision(self):
        self.row(1, "r1")
        self.row(2, "r2")
        self.configure.side_effect = [ValueError("synthetic prepare failed"), None, None, None, None, None, None]
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["revisions"]["v2.2/r1"]["status"], "failed")
        self.assertEqual(self.calls[0][:3], ("v2.2", "r2", 2))
        self.assertEqual(len(self.progress_lines()), 4)

    def test_revision_join_failure_continues_to_next_revision(self):
        self.row(1, "r1")
        self.row(2, "r2")
        original = self.join_results
        joins = 0

        def join(*args):
            nonlocal joins
            joins += 1
            if joins == 1:
                raise ValueError("synthetic join failed")
            return original(*args)

        self.join.side_effect = join
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["revisions"]["v2.2/r1"]["status"], "failed")
        self.assertEqual(state["revisions"]["v2.2/r2"]["status"], "completed")
        self.assertEqual(self.progress_lines()[0]["classification_error"], "synthetic join failed")

    def test_two_same_revision_failures_stop(self):
        for q in range(1, 4):
            self.row(q, f"r{q}")
        self.configure.side_effect = ValueError("synthetic prepare failed")
        state, result = self.execute()
        self.assertEqual(result["stop_kind"], "repeated_failure")
        self.assertEqual(state["revision_failure_streak"]["count"], 2)
        self.assertNotIn("v2.2/r3", state["revisions"])
        self.assertEqual(self.calls, [])
        self.assertEqual(state["revisions"]["v2.2/r2"]["status"], "failed")
        self.assertEqual(len(self.progress_lines()), 2)

    def test_revision_streak_resets_on_different_reason_and_success(self):
        state = self.state()
        aq.streak(state, "revision_failure_streak", "first", 2, "repeated_failure")
        aq.streak(state, "revision_failure_streak", "second", 2, "repeated_failure")
        self.assertEqual(state["revision_failure_streak"], {"reason": "second", "count": 1})
        aq.streak(state, "revision_failure_streak", None, 2, "repeated_failure")
        aq.streak(state, "revision_failure_streak", "second", 2, "repeated_failure")
        self.assertEqual(state["revision_failure_streak"], {"reason": "second", "count": 1})

    def test_execution_is_engine_major_and_cleans_each_engine_revision(self):
        self.row(1, "r1")
        self.row(2, "r2")
        state, result = self.execute()
        expected = [(e, r) for e in aq.ENGINES for r in ("r1", "r2")]
        self.assertEqual(result["status"], "completed")
        self.assertEqual([c[:2] for c in self.calls], expected)
        self.assertEqual([(c.args[1], c.args[3]) for c in self.revision_cleanup.call_args_list], expected)
        self.assertEqual(self.scored, expected)
        self.assertEqual(state["active_revision"], None)

    def test_deadline_finishes_active_revision_then_refuses_next(self):
        self.row(1, "r1")
        self.row(2, "r1")
        self.row(3, "r2")

        def lift(*args):
            result = self.lift_result(*args)
            self.clock = self.deadline
            return result

        self.lift.side_effect = lift
        state, result = self.execute()
        self.assertEqual(result["stop_kind"], "deadline")
        self.assertEqual([c[2] for c in self.calls], [1, 2])
        self.assertEqual(state["revisions"]["v2.2/r1"]["status"], "completed")
        self.assertNotIn("v2.2/r2", state["revisions"])
        self.assertEqual(self.scored, [("v2.2", "r1")])

    def test_resume_active_revision_after_deadline_finishes_it(self):
        self.row(1, "r1")
        self.row(2, "r2")
        state = self.state()
        state["active_revision"] = "v2.2/r1"
        self.clock = self.deadline
        state, result = self.execute(state)
        self.assertEqual(result["stop_kind"], "deadline")
        self.assertEqual([c[2] for c in self.calls], [1])
        self.assertEqual(state["revisions"]["v2.2/r1"]["status"], "completed")

    def test_disk_gate_waits_five_minutes_and_rechecks_before_launch(self):
        row = self.row(1)
        state = self.state()
        state["observed_request_peak_bytes"] = 70 * aq.GIB
        aq.reserve_bytes.return_value = {"retained_evidence_bytes": 7 * aq.GIB}
        aq.mount_check.side_effect = [self.space(external=147 * aq.GIB - 1),
                                     self.space(external=147 * aq.GIB)]
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            self.assertEqual(self.calls, [])
            self.assertEqual(state["engines"]["v2.2"]["requests"], {})

        with patch.object(aq.time, "sleep", side_effect=sleep):
            event = self.request(state, row)
        self.assertEqual(waits, [60] * 5)
        self.assertEqual(aq.mount_check.call_count, 2)
        self.assertEqual(event["disk_before"]["required_external_free_bytes"], 147 * aq.GIB)
        records = (self.output / "disk-waits-v2.jsonl").read_text().splitlines()
        self.assertEqual(len(records), 1)
        self.assertEqual(len(self.calls), 1)

    def test_internal_disk_gate_waits_even_when_image_has_space(self):
        aq.mount_check.side_effect = [self.space(repo=15 * aq.GIB - 1), self.space(repo=15 * aq.GIB)]
        with patch.object(aq.time, "sleep") as sleep:
            aq.request_guard(self.state())
        self.assertEqual([c.args for c in sleep.call_args_list], [(60,)] * 5)
        self.assertEqual(self.calls, [])

    def test_import_completed_reverifies_and_reuses_without_lift(self):
        row = self.row(1)
        original = self.state()
        for engine in aq.ENGINES:
            original["active_revision"] = None
            self.request(original, row, engine)
        state, _binding = self.import_state(original)
        old_sha = aq.runner.sha256(self.output / "state.json")
        self.assertEqual(aq.recover(state, self.indexes(), readonly=True), {"completed": 2})
        self.calls.clear()
        state, result = self.execute(state)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.calls, [])
        self.assertEqual(aq.runner.sha256(self.output / "state.json"), old_sha)
        self.assertTrue(state["engines"]["v2.2"]["requests"]["1"]["imported_v1"])

    def test_import_failed_request_is_resumed_as_new_attempt(self):
        row = self.row(2185)
        self.outcomes[2185] = [7, 0]
        original = self.state()
        self.request(original, row)
        state, _binding = self.import_state(original)
        self.assertTrue(state["engines"]["v2.2"]["requests"]["2185"]["resume_pending"])
        event = self.request(state, row)
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["attempt"], 2)
        self.assertEqual(len(event["history"]), 1)

    def test_imported_state_tampering_is_refused(self):
        state, binding = self.import_state(self.state())
        aq.save(state)
        path = self.output / "state.json"
        original = json.loads(path.read_text())
        self.write(path, {**original, "tampered": True})
        with self.assertRaisesRegex(aq.runner.RunnerError, "original v1 state changed"):
            aq.load_state(binding)
        self.assertEqual(self.calls, [])

    def test_resume_configuration_tampering_is_refused(self):
        state, binding = self.import_state(self.state())
        aq.save(state)
        with self.assertRaisesRegex(aq.runner.RunnerError, "configuration/hash differs"):
            aq.load_state({**binding, "external_root": "changed"})
        self.assertEqual(self.calls, [])

    def test_imported_result_and_metrics_sha_tampering_are_refused(self):
        row = self.row(1)
        original = self.state()
        event = self.request(original, row)
        state, _binding = self.import_state(original)
        for key in ("result_path", "metrics_path"):
            with self.subTest(key=key):
                path = Path(event[key])
                saved = path.read_bytes()
                path.write_bytes(saved + b" ")
                with self.assertRaisesRegex(aq.runner.RunnerError, "SHA-256 mismatch"):
                    aq.recover(state, self.indexes(), readonly=True)
                path.write_bytes(saved)
        self.assertEqual(len(self.calls), 1)

    def test_request_binding_tampering_is_refused_even_with_untouched_files(self):
        row = self.row(1)
        original = self.state()
        self.request(original, row)
        state, _binding = self.import_state(original)
        state["engines"]["v2.2"]["requests"]["1"]["request_sha256"] = "0" * 64
        with self.assertRaisesRegex(aq.runner.RunnerError, "request SHA differs"):
            aq.recover(state, self.indexes(), readonly=True)

    def test_scoring_exception_is_nonfatal_and_progress_records_error(self):
        self.row(1, "r1")
        self.row(2, "r2")
        self.scorer.side_effect = ValueError("synthetic scoring failure")
        _state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.calls), 4)
        lines = self.progress_lines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(p["rqc"] == {"status": "error", "reason": "synthetic scoring failure"}
                            for p in lines))
        for line in lines:
            self.assertEqual((line["requests"], line["completed"], line["failures"], line["L1"],
                              line["excluded"], line["unknown"]), (1, 1, 0, 1, 0, 0))
            self.assertEqual(line["wall_seconds"]["sum"], 1.25)
            self.assertIn("workspace_bytes_freed", line)

    def test_successful_progress_records_new_scoring_path_and_hash(self):
        self.row(1)
        self.execute()
        lines = self.progress_lines()
        self.assertEqual(len({p["rqc"]["path"] for p in lines}), 2)
        for line in lines:
            receipt = line["rqc"]
            self.assertEqual(aq.runner.sha256(Path(receipt["path"])), receipt["sha256"])
            self.assertEqual(receipt["status"], "completed")

    def test_crash_after_request_final_before_streak_is_counted_once_on_resume(self):
        state = self.state()
        for queue in range(1, 7):
            row = self.row(queue)
            self.outcomes[queue] = [7]
            if queue < 5:
                self.request(state, row)
            elif queue == 5:
                # Persist the final event but simulate a crash before streak accounting.
                with patch.object(aq, "account_request", return_value=None):
                    self.request(state, row)
        self.assertEqual(state["request_failure_streak"]["count"], 4)
        self.assertNotIn("streak_counted", state["engines"]["v2.2"]["requests"]["5"])
        self.calls.clear()
        state, result = self.execute(state)
        self.assertEqual(result["stop_kind"], "repeated_request_failure")
        self.assertEqual(state["request_failure_streak"]["count"], 5)
        self.assertEqual(self.calls, [])
        state, result = self.execute(state)
        self.assertEqual(result["stop_kind"], "repeated_request_failure")
        self.assertEqual(state["request_failure_streak"]["count"], 5)
        self.assertEqual(self.calls, [])

    def test_interrupted_request_without_metrics_recovers_and_resumes(self):
        row = self.row(1)
        state = self.state()
        _result, metrics, workspace = aq.attempt_paths("v2.2", row, 1)
        state["engines"]["v2.2"]["requests"]["1"] = {
            "status": "running", "engine": "v2.2", "revision": "r1", "scope": "main",
            "method": "S", "queue_order": 1, "request_sha256": row["request_sha256"],
            "workspace": str(workspace), "attempt": 1, "disk_retries": 0, "history": []}
        self.assertEqual(aq.recover(state, self.indexes(), readonly=True), {"interrupted": 1})
        self.assertFalse(metrics.exists())
        self.assertEqual(aq.recover(state, self.indexes(), readonly=False), {"interrupted": 1})
        event = state["engines"]["v2.2"]["requests"]["1"]
        self.assertEqual(event["status"], "failed")
        self.assertEqual(event["runner_error_kind"], "interrupted_without_metrics")
        self.assertTrue(event["resume_pending"])
        aq.checked_event("v2.2", row, event)
        final = self.request(state, row)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["attempt"], 2)
        self.assertEqual(final["history"][0]["metrics_sha256"], aq.runner.sha256(metrics))

    def test_crash_after_failed_metrics_without_disk_pressure_does_not_rerun(self):
        row = self.row(1)
        self.outcomes[1] = [7, 0]
        state = self.state()
        with patch.object(aq, "finish_event", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.request(state, row)
        self.assertEqual(state["engines"]["v2.2"]["requests"]["1"]["status"], "running")
        aq.recover(state, self.indexes(), readonly=False)
        event = state["engines"]["v2.2"]["requests"]["1"]
        self.assertEqual(event["status"], "failed")
        self.assertFalse(aq.needs_request(event))
        self.request(state, row)
        self.assertEqual([call[3] for call in self.calls], [1])

    def test_crash_after_low_disk_preparation_failure_keeps_one_retry_pending(self):
        row = self.row(1)
        self.outcomes[1] = ["preparation", 0]
        aq.runner.disk_free.return_value = aq.GIB - 1
        state = self.state()
        with patch.object(aq, "finish_event", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.request(state, row)
        aq.recover(state, self.indexes(), readonly=False)
        event = state["engines"]["v2.2"]["requests"]["1"]
        self.assertEqual(event["status"], "preparation_failure")
        self.assertTrue(event["retry_pending"])
        self.assertTrue(aq.needs_request(event))
        final = self.request(state, row)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["disk_retries"], 1)
        self.assertEqual([call[3] for call in self.calls], [1, 2])

    def test_crash_after_retry_metrics_cannot_schedule_a_third_disk_attempt(self):
        row = self.row(1)
        self.outcomes[1] = [7, 7, 0]
        aq.runner.disk_free.return_value = aq.GIB - 1
        state = self.state()
        original_finish = aq.finish_event

        def finish(*args):
            if args[2]["attempt"] == 2:
                raise KeyboardInterrupt
            return original_finish(*args)

        with patch.object(aq, "finish_event", side_effect=finish):
            with self.assertRaises(KeyboardInterrupt):
                self.request(state, row)
        aq.recover(state, self.indexes(), readonly=False)
        event = state["engines"]["v2.2"]["requests"]["1"]
        self.assertEqual(event["status"], "failed")
        self.assertEqual(event["disk_retries"], 1)
        self.assertFalse(aq.needs_request(event))
        self.request(state, row)
        self.assertEqual([call[3] for call in self.calls], [1, 2])

    def test_crash_after_revision_final_recovers_progress_from_saved_join(self):
        self.row(1)
        with patch.object(aq, "progress", side_effect=KeyboardInterrupt):
            state, result = self.execute()
        self.assertEqual(result["stop_kind"], "interrupted")
        self.assertEqual(state["revisions"]["v2.2/r1"]["status"], "completed")
        self.assertNotIn("progress_saved", state["revisions"]["v2.2/r1"])
        self.assertEqual(len(self.calls), 1)
        self.calls.clear()
        self.join.reset_mock()
        state, result = self.execute(state)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([call[0] for call in self.calls], ["v1"])
        self.assertEqual(self.join.call_count, 1)
        lines = self.progress_lines()
        self.assertEqual([(line["engine"], line["L1"]) for line in lines], [("v2.2", 1), ("v1", 1)])
        self.assertTrue(all("classification_error" not in line for line in lines))
        self.assertTrue(state["revisions"]["v2.2/r1"]["streak_counted"])

    def test_request_setup_error_is_recorded_and_continues(self):
        self.row(1)
        self.row(2)
        calls = 0

        def cache(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError(5, "synthetic cache setup error")
            return self.cache(*args)

        aq.runner.initialize_cache.side_effect = cache
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        failure = state["engines"]["v2.2"]["requests"]["1"]
        self.assertEqual(failure["failure_reason"], "OSError:errno=5")
        self.assertEqual(failure["status"], "failed")
        self.assertEqual([call[:3] for call in self.calls], [
            ("v2.2", "r1", 2), ("v1", "r1", 1), ("v1", "r1", 2)])

    def test_initial_peak_floor_remains_sixty_gib(self):
        state = self.state()
        state["observed_request_peak_bytes"] = 1
        gate = aq.request_guard(state)
        self.assertEqual(gate["observed_request_peak_bytes"], 60 * aq.GIB)
        self.assertEqual(gate["required_external_free_bytes"], 120 * aq.GIB)

    def test_disk_wait_signal_stops_before_launch(self):
        row = self.row(1)
        aq.mount_check.side_effect = lambda: self.space(external=0)

        def interrupt(_seconds):
            aq.STOP_SIGNAL = 15

        with patch.object(aq.time, "sleep", side_effect=interrupt) as sleep:
            with self.assertRaises(aq.Stop) as caught:
                self.request(self.state(), row)
        self.assertEqual(caught.exception.kind, "interrupted")
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(self.calls, [])

    def test_scorer_nonzero_exit_and_missing_output_are_nonfatal_receipts(self):
        state = self.state()
        self.process.side_effect = None
        self.process.return_value = SimpleNamespace(returncode=9, stdout="", stderr="synthetic scorer error")
        with patch.object(aq.rqc, "normalize_state", side_effect=lambda value, _engine: value):
            failed = self.real_score_revision(state, "v2.2", "r1")
            self.process.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
            missing = self.real_score_revision(state, "v2.2", "r1")
        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["exit_code"], 9)
        self.assertEqual(missing["status"], "error")
        self.assertEqual(missing["reason"], "scorer returned no output")
        self.assertNotEqual(failed["path"], missing["path"])
        self.assertNotIn("sha256", failed)
        self.assertNotIn("sha256", missing)
        command = self.process.call_args.args[0]
        self.assertEqual(command[command.index("--layer") + 1], "exploratory")


if __name__ == "__main__":
    unittest.main()
