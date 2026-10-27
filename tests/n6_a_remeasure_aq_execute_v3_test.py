#!/usr/bin/env python3
"""Synthetic v3 segment and import regressions; no real engine/process execution."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import copy
import math
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_a_remeasure_aq_execute_v3 as aq

R1, R2 = aq.DEFAULT_REVISIONS[:2]
REST = aq.DEFAULT_REVISIONS[7]


class V3RunnerTests(unittest.TestCase):
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
        self.mapped = {}
        self.timeline = []
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
        self.patch(aq, "mount_check", Mock(side_effect=lambda **_kwargs: self.space()))
        self.real_reserve_bytes = aq.reserve_bytes
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
        self.real_cleanup_request = aq.cleanup_request
        self.real_revision_cleanup = aq.revision_cleanup
        self.cleanup = self.patch(aq, "cleanup_request", Mock(side_effect=self.verify_cleanup))
        self.revision_cleanup = self.patch(aq, "revision_cleanup", Mock(side_effect=self.final_cleanup))
        self.patch(aq, "seed_storage", Mock(return_value=None))
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

    def row(self, queue, revision=R1, *, mapped=True):
        base = self.root / "inputs" / revision / "input.json"
        self.input_shas[revision] = self.write(base, {"synthetic": revision})
        path = self.root / "requests" / f"{queue}.json"
        sha = self.write(path, {"id": f"request-{queue}", "base_input": str(base)})
        row = {"queue_order": queue, "revision_id": revision, "scope": "main", "method": "S",
               "request": str(path), "request_sha256": sha, "candidate_sha256": "c" * 64}
        self.rows.append(row)
        self.mapped[queue] = mapped
        return row

    def state(self):
        return {"schema": aq.SCHEMA, "layer": aq.LAYER, "config": {}, "status": "ready",
                "active_revision": None, "revisions": {},
                "engines": {e: {"requests": {}, "groups": {}} for e in aq.ENGINES},
                "observed_request_peak_bytes": aq.INITIAL_PEAK, "cleanup_receipts": [],
                "request_failure_streak": {}, "revision_failure_streak": {}}

    def lift_result(self, row, workspace, _cache, _store, attempt, _method):
        engine = workspace.relative_to(self.external).parts[1]
        self.calls.append((engine, row["revision_id"], row["queue_order"], attempt))
        self.timeline.append(("request", engine, row["revision_id"], row["queue_order"]))
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

    def final_cleanup(self, _state, engine, _index, revision):
        self.timeline.append(("final_cleanup", engine, revision))
        return 0

    def score(self, _state, engine, revision, pass_name=None):
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

    def selected(self):
        present = {row["revision_id"] for row in self.rows}
        return [revision for revision in aq.DEFAULT_REVISIONS if revision in present]

    def order(self):
        result = []
        selected = self.selected()
        for engine in aq.ENGINES:
            for pass_name in ("A", "B", "rest"):
                for revision in selected:
                    priority = revision in aq.ordering.PRIORITY_REVISIONS
                    if (pass_name == "rest") == priority:
                        continue
                    for row in self.rows:
                        mapped = self.mapped[row["queue_order"]]
                        if row["revision_id"] != revision or (pass_name != "rest" and mapped != (pass_name == "A")):
                            continue
                        result.append({"engine": engine, "revision": revision, "queue_order": row["queue_order"],
                            "mapped": mapped, "pass": pass_name, "segment_id": f"{engine}/{pass_name}/{revision}",
                            "segment_is_final": pass_name != "A"})
        return result

    def execute(self, state=None):
        state = self.state() if state is None else state
        with patch.object(aq, "DEFAULT_REVISIONS", tuple(self.selected())):
            result = aq.execute(state, self.indexes(), self.order(), self.deadline)
        return state, result

    def request(self, state, row, engine="v2.2"):
        aq.run_request(state, engine, row, "main", 1, self.deadline)
        return state["engines"][engine]["requests"][str(row["queue_order"])]

    def progress_lines(self):
        return [json.loads(line) for line in (self.output / "progress-v3.jsonl").read_text().splitlines()]

    def import_binding(self):
        return {"plan_sha256": aq.PLAN_SHA256, "index_sha256": aq.INDEX_SHA256,
                "engine_sha256": aq.ENGINE_SHA256, "external_root": str(self.external)}

    def old_event(self, row, *, engine="v2.2", status="completed", attempt=1,
                  with_metrics=True, **extra):
        event = {"status": status, "engine": engine, "revision": row["revision_id"], "scope": "main",
                 "method": "S", "queue_order": row["queue_order"], "request_sha256": row["request_sha256"],
                 "attempt": attempt, "disk_retries": 0, "history": [], "imported_from": "state-v2.json"}
        result, metrics, workspace = aq.event_paths(engine, row, event)
        event["workspace"] = str(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "untouched-old-workspace").write_text("preserve old bytes")
        if with_metrics:
            value = {"exit_code": 0 if status == "completed" else 7, "wall_seconds": 1.25,
                     "max_rss_bytes": 1024, "measurement_method": "synthetic"}
            event.update(value)
            event.update({"metrics_path": str(metrics), "metrics_sha256": self.write(metrics, value)})
            result_value = {"schema": "zkfdo-lifting-result-v1", "request_id": f"request-{row['queue_order']}",
                "request_sha256": row["request_sha256"], "candidate_sha256": row["candidate_sha256"],
                "preparation": {"status": "ok"},
                "classes": [{"representative": "main.synthetic", "verdict": "entrypoint_violation"}]}
            event.update({"result_path": str(result), "result_sha256": self.write(result, result_value),
                          "failure_reason": None if status == "completed" else "lift_exit_7"})
        event.pop("imported_from")
        event.update(extra)
        return event

    def import_fixture(self, baseline_events=(), latest_events=(), *, latest_status="stopped"):
        binding = self.import_binding()

        def engines(events):
            result = {engine: {"requests": {}, "groups": {}} for engine in aq.ENGINES}
            for event in events:
                result[event["engine"]]["requests"][str(event["queue_order"])] = copy.deepcopy(event)
            return result

        baseline = {"schema": "n6-a-remeasure-aq-execute-v1", "config": binding,
                    "status": "stopped", "engines": engines(baseline_events)}
        baseline_path = self.output / "state.json"
        baseline_sha = self.write(baseline_path, baseline)
        latest = {"schema": "n6-a-remeasure-aq-execute-v2", "config": binding,
                  "status": latest_status, "engines": engines(latest_events),
                  "imported_state": {"path": str(baseline_path), "sha256": baseline_sha},
                  "observed_request_peak_bytes": 80 * aq.GIB,
                  "request_failure_streak": {}, "revision_failure_streak": {}}
        self.write(self.output / "state-v2.json", latest)
        return aq.load_state(binding), binding

    def old_snapshot(self):
        files = [self.output / "state.json", self.output / "state-v2.json"]
        for engine in aq.ENGINES:
            for root in (self.output / engine, self.external / engine):
                if root.exists():
                    files.extend(path for path in root.rglob("*") if path.is_file())
        return {str(path): path.read_bytes() for path in files}

    def test_two_pass_engine_major_schedule_defers_cleanup_until_b(self):
        self.row(1, R1, mapped=True)
        self.row(2, R1, mapped=False)
        self.row(3, R2, mapped=True)
        self.row(4, R2, mapped=False)
        self.row(5, REST, mapped=False)
        _state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        expected = [1, 3, 2, 4, 5]
        self.assertEqual([call[2] for call in self.calls], expected * 2)
        self.assertEqual([call[0] for call in self.calls], ["v2.2"] * 5 + ["v1"] * 5)
        for engine in aq.ENGINES:
            first_cleanup = self.timeline.index(("final_cleanup", engine, R1))
            self.assertGreater(first_cleanup, self.timeline.index(("request", engine, R2, 3)))
            self.assertGreater(first_cleanup, self.timeline.index(("request", engine, R1, 2)))
            self.assertLess(first_cleanup, self.timeline.index(("request", engine, R2, 4)))
        self.assertEqual(self.revision_cleanup.call_count, 6)

    def test_empty_b_is_explicit_and_finalizes_only_after_all_a_segments(self):
        self.row(1, R1, mapped=True)
        self.row(2, R2, mapped=True)
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual([call[2] for call in self.calls], [1, 2, 1, 2])
        self.assertEqual(self.revision_cleanup.call_count, 4)
        for engine in aq.ENGINES:
            key = f"{engine}/B/{R1}"
            self.assertEqual(state["revisions"][key]["status"], "completed")
            self.assertGreater(self.timeline.index(("final_cleanup", engine, R1)),
                               self.timeline.index(("request", engine, R2, 2)))
        self.assertEqual(len(self.progress_lines()), 8)

    def test_deadline_finishes_active_a_but_blocks_even_empty_b(self):
        self.row(1, R1, mapped=True)
        self.row(2, R1, mapped=True)

        def lift(*args):
            result = self.lift_result(*args)
            self.clock = self.deadline
            return result

        self.lift.side_effect = lift
        state, result = self.execute()
        self.assertEqual(result["stop_kind"], "deadline")
        self.assertEqual([call[2] for call in self.calls], [1, 2])
        self.assertEqual(state["revisions"][f"v2.2/A/{R1}"]["status"], "completed")
        self.assertNotIn(f"v2.2/B/{R1}", state["revisions"])
        self.assertEqual(self.revision_cleanup.call_count, 0)

    def test_deadline_finishes_active_b_then_stops_before_next_b(self):
        for queue, revision, mapped in ((1, R1, True), (2, R1, False),
                                        (3, R1, False), (4, R2, True), (5, R2, False)):
            self.row(queue, revision, mapped=mapped)

        def lift(*args):
            result = self.lift_result(*args)
            if args[0]["queue_order"] == 2:
                self.clock = self.deadline
            return result

        self.lift.side_effect = lift
        state, result = self.execute()
        self.assertEqual(result["stop_kind"], "deadline")
        self.assertEqual([call[2] for call in self.calls], [1, 4, 2, 3])
        self.assertEqual(state["revisions"][f"v2.2/B/{R1}"]["status"], "completed")
        self.assertNotIn(f"v2.2/B/{R2}", state["revisions"])
        self.assertEqual([(call.args[1], call.args[3]) for call in self.revision_cleanup.call_args_list],
                         [("v2.2", R1)])

    def test_disk_wait_crossing_cutoff_does_not_start_a_new_segment(self):
        self.row(1, R1)
        aq.mount_check.side_effect = [self.space(external=0), self.space()]
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            self.assertEqual(self.calls, [])
            self.clock = self.deadline

        with patch.object(aq.time, "sleep", side_effect=sleep):
            state, result = self.execute()
        self.assertEqual(result["stop_kind"], "deadline")
        self.assertEqual(waits, [60] * 5)
        self.assertEqual(self.calls, [])
        self.assertEqual(state["active_revision"], None)

    def test_disk_wait_crossing_cutoff_keeps_running_segment_eligible(self):
        self.row(1, R1)
        self.row(2, R1)
        waited = False

        def space(**_kwargs):
            nonlocal waited
            if len(self.calls) == 1 and not waited:
                waited = True
                return self.space(external=0)
            return self.space()

        aq.mount_check.side_effect = space

        def sleep(_seconds):
            self.clock = self.deadline

        with patch.object(aq.time, "sleep", side_effect=sleep) as sleep_mock:
            _state, result = self.execute()
        self.assertEqual(result["stop_kind"], "deadline")
        self.assertEqual([call[2] for call in self.calls], [1, 2])
        self.assertEqual(sleep_mock.call_count, 5)
        self.assertEqual(self.revision_cleanup.call_count, 0)

    def test_v3_disk_gate_uses_one_point_two_peak_plus_deferred_reservation(self):
        state = self.state()
        state["observed_request_peak_bytes"] = 70 * aq.GIB + 1
        aq.reserve_bytes.return_value = {"retained_evidence_bytes": 3 * aq.GIB,
                                         "deferred_cache_store_bytes": 4 * aq.GIB}
        required = math.ceil(1.2 * state["observed_request_peak_bytes"]) + 7 * aq.GIB
        aq.mount_check.side_effect = [self.space(external=required - 1), self.space(external=required)]
        with patch.object(aq.time, "sleep") as sleep:
            gate = aq.request_guard(state)
        self.assertEqual(gate["required_external_free_bytes"], required)
        self.assertEqual(sleep.call_count, 5)
        self.assertEqual(self.calls, [])

    def test_v3_disk_gate_keeps_fifteen_gib_internal_requirement(self):
        aq.mount_check.side_effect = [self.space(repo=15 * aq.GIB - 1), self.space(repo=15 * aq.GIB)]
        with patch.object(aq.time, "sleep") as sleep:
            gate = aq.request_guard(self.state())
        self.assertEqual(gate["required_repo_free_bytes"], 15 * aq.GIB)
        self.assertEqual(sleep.call_count, 5)
        self.assertEqual(gate["required_external_free_bytes"], math.ceil(1.2 * 60 * aq.GIB))

    def test_partial_v2_completed_requests_are_hash_reverified_and_reused(self):
        first = self.row(1, R1, mapped=True)
        second = self.row(2, R1, mapped=False)
        self.row(3, R2, mapped=True)
        old_first = self.old_event(first)
        old_second = self.old_event(second)
        state, _binding = self.import_fixture([old_first], [old_first, old_second])
        before = self.old_snapshot()
        self.assertEqual(aq.recover(state, self.indexes(), readonly=True), {"completed": 2})
        self.assertEqual(state["observed_request_peak_bytes"], 80 * aq.GIB)
        aq.prepare_storage(state, self.indexes())
        _state, result = self.execute(state)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([call[2] for call in self.calls if call[0] == "v2.2"], [3])
        self.assertEqual(self.old_snapshot(), before)
        self.assertEqual(len(state["imported_states"]), 2)

    def test_v2_result_metrics_and_both_imported_state_hashes_are_checked(self):
        row = self.row(1)
        old = self.old_event(row)
        state, binding = self.import_fixture([old], [old])
        for key in ("result_path", "metrics_path"):
            path = Path(old[key])
            before = path.read_bytes()
            path.write_bytes(before + b" ")
            with self.subTest(key=key), self.assertRaisesRegex(aq.runner.RunnerError, "SHA-256 mismatch"):
                aq.recover(state, self.indexes(), readonly=True)
            path.write_bytes(before)
        aq.save(state)
        for name in ("state.json", "state-v2.json"):
            path = self.output / name
            before = path.read_bytes()
            path.write_bytes(before + b" ")
            with self.subTest(name=name), self.assertRaisesRegex(aq.runner.RunnerError, "SHA-256 mismatch"):
                aq.load_state(binding)
            path.write_bytes(before)
        self.assertEqual(self.calls, [])

    def test_v2_import_refuses_a_baseline_attempt_missing_from_history(self):
        row = self.row(1)
        baseline = self.old_event(row, attempt=1)
        later = self.old_event(row, attempt=2)
        with self.assertRaisesRegex(aq.runner.RunnerError, "lost or changed a baseline request"):
            self.import_fixture([baseline], [later])
        self.assertEqual(self.calls, [])

    def test_failed_2185_pending_in_v2_retries_in_private_v3_paths(self):
        row = self.row(2185, REST, mapped=False)
        failed = self.old_event(row, status="failed", resume_pending=True)
        state, _binding = self.import_fixture([failed], [failed])
        before = self.old_snapshot()
        state, result = self.execute(state)
        self.assertEqual(result["status"], "completed")
        event = state["engines"]["v2.2"]["requests"]["2185"]
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["attempt"], 2)
        self.assertTrue(Path(event["workspace"]).is_relative_to(self.external / "v3"))
        self.assertTrue(Path(event["result_path"]).is_relative_to(self.output / "v3"))
        self.assertEqual(event["history"][0]["imported_from"], "state-v2.json")
        self.assertEqual(self.old_snapshot(), before)

    def test_partial_v2_running_attempt_validation_does_not_write_old_or_new_files(self):
        row = self.row(1)
        running = self.old_event(row, status="running", with_metrics=False)
        state, _binding = self.import_fixture([], [running], latest_status="running")
        before = self.old_snapshot()
        self.assertEqual(aq.recover(state, self.indexes(), readonly=True), {"interrupted": 1})
        self.assertEqual(self.old_snapshot(), before)
        self.assertFalse((self.output / "state-v3.json").exists())
        self.assertFalse((self.output / "v3").exists())
        self.assertEqual(self.calls, [])

    def test_interrupted_v2_migration_keeps_old_files_and_resumes_privately(self):
        row = self.row(1)
        running = self.old_event(row, status="running", with_metrics=False)
        state, _binding = self.import_fixture([], [running], latest_status="running")
        before = self.old_snapshot()
        self.assertEqual(aq.recover(state, self.indexes(), readonly=False), {"interrupted": 1})
        recovered = state["engines"]["v2.2"]["requests"]["1"]
        self.assertNotIn("imported_from", recovered)
        self.assertTrue(recovered["resume_pending"])
        self.assertTrue(Path(recovered["metrics_path"]).is_relative_to(self.output / "v3"))
        self.assertEqual(self.old_snapshot(), before)
        state, result = self.execute(state)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["engines"]["v2.2"]["requests"]["1"]["attempt"], 2)
        self.assertEqual(self.old_snapshot(), before)

    def test_live_v2_process_refuses_switch_over_without_touching_it(self):
        self.process.side_effect = None
        self.process.return_value = SimpleNamespace(returncode=0, stderr="", stdout=
            "987654 python3 /synthetic/n6_a_remeasure_aq_execute_v2.py --action execute\n")
        with self.assertRaises(aq.Stop) as caught:
            aq.check_v2_process()
        self.assertEqual(caught.exception.kind, "v2_running")
        self.assertEqual(self.process.call_args.args[0], ["ps", "-axo", "pid=,command="])
        self.assertEqual(self.calls, [])

    def test_busy_shared_runner_lock_refuses_before_process_inspection(self):
        lock = self.output / ".runner.lock"
        lock.write_bytes(b"synthetic existing lock")
        with patch.object(aq.fcntl, "flock", side_effect=BlockingIOError):
            with self.assertRaises(aq.Stop) as caught:
                with aq.execution_lock():
                    self.fail("busy lock authorized execution")
        self.assertEqual(caught.exception.kind, "v2_running_or_runner_busy")
        self.assertEqual(lock.read_bytes(), b"synthetic existing lock")
        self.process.assert_not_called()

    def test_failed_process_inspection_fails_closed(self):
        self.process.side_effect = None
        self.process.return_value = SimpleNamespace(returncode=1, stdout="", stderr="synthetic ps failure")
        with self.assertRaises(aq.Stop) as caught:
            aq.check_v2_process()
        self.assertEqual(caught.exception.kind, "process_check_unavailable")
        self.assertEqual(self.calls, [])

    def test_final_b_refuses_cleanup_if_prior_a_request_is_still_missing(self):
        self.row(1, R1, mapped=True)
        self.row(2, R1, mapped=False)
        state = self.state()
        segment = next(segment for segment in aq.ordering.segments_for(self.order(), self.selected())
                       if segment["engine"] == "v2.2" and segment["pass"] == "B")
        aq.execute_segment(state, "v2.2", self.indexes()["v2.2"], segment, self.deadline)
        self.assertEqual(state["revisions"][segment["segment_id"]]["status"], "failed")
        self.assertEqual(state["revisions"][segment["segment_id"]]["failure_reason"], "revision_requests_pending")
        self.assertEqual([call[2] for call in self.calls], [2])
        self.revision_cleanup.assert_not_called()

    def test_deadline_before_segment_prevents_seed_join_score_and_state_start(self):
        self.row(1)
        self.clock = self.deadline
        state, result = self.execute()
        self.assertEqual(result["stop_kind"], "deadline")
        self.assertEqual(state["revisions"], {})
        aq.seed_storage.assert_not_called()
        self.join.assert_not_called()
        self.scorer.assert_not_called()
        self.lift.assert_not_called()

    def test_real_reservation_counts_protected_sources_deferred_cache_and_pending_copy(self):
        state = self.state()
        old_workspace = self.external / "v2.2/workspaces/old/000001/attempt-0001"
        private_workspace = self.external / "v3/v2.2/workspaces/new/000002/attempt-0001"
        source = self.external / "v2.2/caches/main/0001"
        cache_root = self.external / "v3/v2.2/caches"
        store_root = self.external / "v3/v2.2/stores"
        for path in (old_workspace, private_workspace, source, cache_root, store_root):
            path.mkdir(parents=True)
        state["protected_workspaces"] = [str(old_workspace.parent), str(old_workspace.parent)]
        state["engines"]["v2.2"]["requests"] = {
            "1": {"workspace": str(old_workspace)}, "2": {"workspace": str(private_workspace),
                "history": [{"workspace": str(private_workspace.parent / "attempt-0000")}]}}
        state["storage_sources"] = [{"engine": "v2.2", "revision": R1, "source": str(source),
            "target": str(cache_root / "main/0001"), "kind": "caches"}]
        allocated = {old_workspace.parent: {"du_bytes": 11}, source: {"du_bytes": 13, "logical_bytes": 17},
                     cache_root: {"du_bytes": 19}, store_root: {"du_bytes": 23}}
        with patch.object(aq.storage, "scan_allocated", side_effect=lambda path: allocated[path]), \
             patch.object(aq.workspace_cleanup, "scan_stats", side_effect=lambda path: {"du_bytes": 11, "retained_evidence": {"du_bytes": 0}} if path == old_workspace.parent else {"du_bytes": 7, "retained_evidence": {"du_bytes": 5}}):
            reserve = self.real_reserve_bytes(state)
            self.assertEqual(reserve, {"retained_evidence_bytes": 7, "protected_v2_bytes": 24,
                "deferred_cache_store_bytes": 42, "pending_storage_copy_bytes": 17})
            state["storage_initialized"] = [f"v2.2/{R1}"]
            after_seed = self.real_reserve_bytes(state)
            self.assertEqual(after_seed["pending_storage_copy_bytes"], 0)
            self.assertEqual(after_seed["protected_v2_bytes"], 24)
            self.assertEqual(after_seed["deferred_cache_store_bytes"], 42)

    def test_imported_running_attempt_with_completed_metrics_reuses_result_without_lift(self):
        row = self.row(1)
        running = self.old_event(row)
        running["status"] = "running"
        state, _binding = self.import_fixture([], [running], latest_status="running")
        before = self.old_snapshot()
        aq.recover(state, self.indexes(), readonly=False)
        event = state["engines"]["v2.2"]["requests"]["1"]
        self.assertEqual(event["status"], "completed")
        self.assertEqual(Path(event["result_path"]).read_bytes(), Path(running["result_path"]).read_bytes())
        state, result = self.execute(state)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([call[0] for call in self.calls], ["v1"])
        self.assertEqual(self.old_snapshot(), before)

    def test_a_failures_do_not_account_full_revision_streak_before_empty_b(self):
        for queue, revision in ((1, R1), (2, R2)):
            self.row(queue, revision, mapped=True)
            self.outcomes[queue] = [7]
        state = self.state()
        segments = aq.ordering.segments_for(self.order(), self.selected())
        for segment in segments[:2]:
            aq.execute_segment(state, "v2.2", self.indexes()["v2.2"], segment, self.deadline)
            self.assertEqual(state["revision_failure_streak"], {})
        state, result = self.execute(state)
        self.assertEqual(result["stop_kind"], "repeated_failure")
        self.assertEqual(state["revision_failure_streak"]["count"], 2)
        self.assertEqual(state["revisions"][f"v2.2/B/{R1}"]["status"], "failed")
        self.assertEqual(state["revisions"][f"v2.2/B/{R2}"]["status"], "failed")
        self.assertEqual([call[2] for call in self.calls], [1, 2])

    def test_b_failure_does_not_fail_whole_revision_with_successful_a(self):
        for queue, revision, mapped in ((1, R1, True), (2, R1, False),
                                        (3, R2, True), (4, R2, False)):
            self.row(queue, revision, mapped=mapped)
            if not mapped:
                self.outcomes[queue] = [7]
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        for engine in aq.ENGINES:
            for revision in (R1, R2):
                self.assertEqual(state["revisions"][f"{engine}/B/{revision}"]["status"], "completed")
        self.assertEqual(state["revision_failure_streak"], {})

    def assert_real_cleanup_deferred(self, *, empty_b):
        self.row(1, R1, mapped=True)
        if not empty_b:
            self.row(2, R1, mapped=False)
        state = self.state()
        artifacts = []

        def lift(row, workspace, cache, store, attempt, method):
            metrics = self.lift_result(row, workspace, cache, store, attempt, method)
            retained = workspace / "raw/site-001/input.json"
            retained.parent.mkdir(parents=True)
            retained.write_text("synthetic store evidence")
            junk = workspace / "compiled.bin"
            junk.write_bytes(b"x" * 4096)
            (cache / "compiled-cache.bin").write_bytes(b"c" * 4096)
            store.mkdir(parents=True, exist_ok=True)
            (store / "store.json").write_text("{}")
            artifacts.append((retained, junk, cache, store))
            return metrics

        self.lift.side_effect = lift
        segments = [segment for segment in aq.ordering.segments_for(self.order(), self.selected())
                    if segment["engine"] == "v2.2"]
        with patch.object(aq, "cleanup_request", side_effect=self.real_cleanup_request), \
             patch.object(aq, "revision_cleanup", side_effect=self.real_revision_cleanup):
            aq.execute_segment(state, "v2.2", self.indexes()["v2.2"], segments[0], self.deadline)
            retained, junk, cache, store = artifacts[0]
            self.assertTrue(retained.is_file())
            self.assertFalse(junk.exists())
            self.assertTrue(cache.is_dir())
            self.assertTrue(store.is_dir())
            self.assertTrue(state["cleanup_receipts"])
            aq.execute_segment(state, "v2.2", self.indexes()["v2.2"], segments[1], self.deadline)
        self.assertEqual(state["revisions"][segments[1]["segment_id"]]["status"], "completed")
        for retained, junk, cache, store in artifacts:
            self.assertFalse(retained.exists())
            self.assertFalse(junk.exists())
            self.assertFalse(cache.exists())
            self.assertFalse(store.exists())
        for row in self.rows:
            event = state["engines"]["v2.2"]["requests"][str(row["queue_order"])]
            aq.checked_event("v2.2", row, event)
            self.assertTrue(Path(event["result_path"]).is_file())
            self.assertTrue(Path(event["metrics_path"]).is_file())
        self.assertGreater(sum(receipt["freed_du_bytes"] for receipt in state["cleanup_receipts"]), 0)

    def test_real_cleanup_preserves_evidence_and_cache_after_a_then_removes_at_b(self):
        self.assert_real_cleanup_deferred(empty_b=False)

    def test_real_cleanup_finalizes_evidence_and_cache_for_empty_b(self):
        self.assert_real_cleanup_deferred(empty_b=True)

    def test_interrupted_import_atomic_result_publication_can_retry_without_old_writes(self):
        row = self.row(1)
        running = self.old_event(row)
        running["status"] = "running"
        state, _binding = self.import_fixture([], [running], latest_status="running")
        before = self.old_snapshot()
        result, _metrics, _workspace = aq.attempt_paths("v2.2", row, 1)
        original_replace = aq.os.replace
        failed_once = False

        def replace(source, target):
            nonlocal failed_once
            if Path(target) == result and not failed_once:
                failed_once = True
                self.assertTrue(Path(source).read_bytes())
                raise OSError(5, "synthetic interrupted publication")
            return original_replace(source, target)

        with patch.object(aq.os, "replace", side_effect=replace):
            with self.assertRaisesRegex(OSError, "synthetic interrupted publication"):
                aq.recover(state, self.indexes(), readonly=False)
            self.assertFalse(result.exists())
            self.assertTrue(result.with_suffix(".import-v3.tmp").is_file())
            self.assertEqual(state["engines"]["v2.2"]["requests"]["1"]["status"], "running")
            aq.recover(state, self.indexes(), readonly=False)
        event = state["engines"]["v2.2"]["requests"]["1"]
        self.assertEqual(event["status"], "completed")
        self.assertEqual(result.read_bytes(), Path(running["result_path"]).read_bytes())
        self.assertFalse(result.with_suffix(".import-v3.tmp").exists())
        self.assertEqual(self.old_snapshot(), before)
        aq.checked_event("v2.2", row, event)
        self.assertEqual(self.calls, [])

    def test_protected_workspace_reservation_does_not_follow_symlink_target(self):
        protected = self.external / "v2.2/workspaces/protected/000001"
        protected.mkdir(parents=True)
        outside = self.root / "unrelated-files"
        outside.mkdir()
        payload = outside / "must-not-count.bin"
        payload.write_bytes(b"x" * (1024 * 1024))
        before = payload.read_bytes()
        link = protected / "outside-link"
        link.symlink_to(outside, target_is_directory=True)
        state = self.state()
        state["protected_workspaces"] = [str(protected)]
        reserve = self.real_reserve_bytes(state)
        self.assertLess(reserve["protected_v2_bytes"], payload.stat().st_blocks * 512)
        self.assertTrue(link.is_symlink())
        self.assertEqual(payload.read_bytes(), before)

    def test_real_scorer_wrapper_uses_exploratory_and_unique_per_segment_outputs(self):
        state = self.state()

        def score_process(command, **_kwargs):
            self.assertEqual(command[command.index("--layer") + 1], "exploratory")
            output = Path(command[command.index("--output") + 1])
            self.write(output, {"synthetic": True})
            return SimpleNamespace(returncode=0, stdout="synthetic score", stderr="")

        self.process.side_effect = score_process
        with patch.object(aq.rqc, "normalize_state", side_effect=lambda value, _engine: value):
            receipts = [self.real_score_revision(state, "v2.2", R1, pass_name=name)
                        for name in ("A", "B", "rest", "A")]
        self.assertEqual(len({receipt["path"] for receipt in receipts}), 4)
        self.assertEqual([receipt["pass"] for receipt in receipts], ["A", "B", "rest", "A"])
        for receipt in receipts:
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["sha256"], aq.runner.sha256(Path(receipt["path"])))
            self.assertEqual(receipt["state_sha256"], aq.runner.sha256(Path(receipt["state_path"])))
        self.assertEqual(self.calls, [])

    def test_recovery_reverifies_storage_seed_receipt_hashes_and_target_binding(self):
        state = self.state()
        target = self.external / "v3/v2.2/caches/main/0001"
        before = self.output / "storage-seeds-v3/synthetic-before.json"
        after = self.output / "storage-seeds-v3/synthetic-after.json"
        receipt = {"target": str(target), "before_path": str(before), "after_path": str(after),
                   "before_sha256": self.write(before, {"kind": "before", "target": str(target)}),
                   "after_sha256": self.write(after, {"kind": "after", "target": str(target)})}
        state["storage_seeds"] = {str(target): receipt}
        self.assertEqual(aq.recover(state, self.indexes(), readonly=True), {})
        for path in (before, after):
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.subTest(path=path.name), self.assertRaisesRegex(aq.runner.RunnerError, "SHA-256 mismatch"):
                aq.recover(state, self.indexes(), readonly=True)
            path.write_bytes(original)
        receipt["target"] = str(target.parent / "wrong-target")
        with self.assertRaisesRegex(aq.runner.RunnerError, "storage seed target binding differs"):
            aq.recover(state, self.indexes(), readonly=True)
        self.assertEqual(self.calls, [])

    def test_main_validate_only_never_locks_inspects_processes_or_writes(self):
        report = {"status": "valid", "judging_executed": False, "synthetic": True}
        before = {str(path): path.read_bytes() for path in self.output.rglob("*") if path.is_file()}
        with patch.object(aq.sys, "argv", ["synthetic-v3", "--action", "validate-only"]), \
             patch.object(aq, "prepare_validation", return_value=({}, [], {}, self.state(), report)) as prepare, \
             patch.object(aq, "execution_lock") as lock, \
             patch.object(aq, "check_v2_process") as inspect, \
             patch.object(aq, "execute") as execute, \
             patch.object(aq, "write_fixed", side_effect=AssertionError("validation wrote an artifact")), \
             patch.object(aq.runner, "atomic_json", side_effect=AssertionError("validation wrote state")):
            self.assertEqual(aq.main(), 0)
        prepare.assert_called_once()
        lock.assert_not_called()
        inspect.assert_not_called()
        execute.assert_not_called()
        self.process.assert_not_called()
        after = {str(path): path.read_bytes() for path in self.output.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(json.loads(self.stdout.getvalue().splitlines()[-1]), report)

    def test_orphan_old_a_storage_process_refuses_but_private_v3_paths_are_allowed(self):
        self.process.side_effect = None
        old_commands = [
            f"synthetic-engine lift --cache {self.external / 'v2.2/caches/main/0001'}",
            f"synthetic-engine lift --output={self.external / 'v1/workspaces/revision/000001'}",
            f"synthetic-engine join --output {self.output / 'aggregates/joins/result.json'}",
            f"synthetic-engine join --output={self.output / 'aggregates-v2/joins/result.json'}",
        ]
        for command in old_commands:
            self.process.return_value = SimpleNamespace(returncode=0, stderr="", stdout=f"987654 {command}\n")
            with self.subTest(command=command), self.assertRaises(aq.Stop) as caught:
                aq.check_v2_process()
            self.assertEqual(caught.exception.kind, "old_a_process_running")
        command = (f"synthetic-engine lift --cache={self.external / 'v3/v2.2/caches/main/0001'} "
                   f"--output {self.output / 'aggregates-v3/joins/result.json'}")
        self.process.return_value = SimpleNamespace(returncode=0, stderr="", stdout=f"987654 {command}\n")
        self.assertIsNone(aq.check_v2_process())
        self.assertTrue(all(call.args[0] == ["ps", "-axo", "pid=,command="]
                            for call in self.process.call_args_list))
        self.assertEqual(self.calls, [])

    def test_fifth_same_request_failure_persists_cleanup_and_restart_refuses_more(self):
        for queue in range(1, 7):
            self.row(queue, R1, mapped=True)
            self.outcomes[queue] = [7]
        with patch.object(aq, "cleanup_request", side_effect=self.real_cleanup_request):
            state, result = self.execute()
            self.assertEqual(result["stop_kind"], "repeated_request_failure")
            self.assertEqual([call[2] for call in self.calls], [1, 2, 3, 4, 5])
            self.assertEqual(state["request_failure_streak"], {"reason": "lift_exit_7", "count": 5})
            self.assertNotIn("6", state["engines"]["v2.2"]["requests"])
            persisted = json.loads((self.output / "state-v3.json").read_text())
            self.assertEqual(persisted["request_failure_streak"]["count"], 5)
            self.assertEqual(len(persisted["cleanup_receipts"]), 5)
            for receipt in persisted["cleanup_receipts"]:
                for when in ("before", "after"):
                    self.assertEqual(aq.runner.sha256(Path(receipt[f"{when}_path"])),
                                     receipt[f"{when}_sha256"])
            for row in self.rows[:5]:
                aq.checked_event("v2.2", row, persisted["engines"]["v2.2"]["requests"][str(row["queue_order"])])
            self.calls.clear()
            resumed, result = self.execute(persisted)
        self.assertEqual(result["stop_kind"], "repeated_request_failure")
        self.assertEqual(resumed["request_failure_streak"]["count"], 5)
        self.assertEqual(self.calls, [])
        self.assertNotIn("6", resumed["engines"]["v2.2"]["requests"])

    def test_low_disk_failure_retries_once_after_a_fresh_gate_then_succeeds(self):
        self.row(1, R1, mapped=True)
        self.outcomes[1] = [7, 0]
        aq.runner.disk_free.side_effect = [aq.GIB - 1, 100 * aq.GIB] * 2
        checks = []

        def space(**_kwargs):
            checks.append(len(self.calls))
            return self.space()

        aq.mount_check.side_effect = space
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual([call[3] for call in self.calls], [1, 2, 1, 2])
        self.assertIn(1, checks)
        self.assertIn(3, checks)
        for engine in aq.ENGINES:
            event = state["engines"][engine]["requests"]["1"]
            self.assertEqual(event["status"], "completed")
            self.assertEqual(event["disk_retries"], 1)
            self.assertFalse(event["retry_pending"])
            self.assertEqual(len(event["history"]), 1)
            self.assertTrue(event["history"][0]["retry_pending"])

    def test_low_disk_retry_exhaustion_continues_without_a_third_attempt(self):
        self.row(1, R1, mapped=True)
        self.row(2, R1, mapped=True)
        self.outcomes[1] = [7, 7, 0]
        aq.runner.disk_free.return_value = aq.GIB - 1
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual([(call[2], call[3]) for call in self.calls], [(1, 1), (1, 2), (2, 1)] * 2)
        for engine in aq.ENGINES:
            failed = state["engines"][engine]["requests"]["1"]
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["disk_retries"], 1)
            self.assertFalse(failed["retry_pending"])
            self.assertEqual(state["engines"][engine]["requests"]["2"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
