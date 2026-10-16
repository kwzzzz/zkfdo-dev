"""Deterministic v4.4 runner regressions; synthetic metadata, no campaigns."""

from contextlib import ExitStack
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_runner(version):
    spec = importlib.util.spec_from_file_location(
        f"n6_{version}_regression_module", ROOT / f"scripts/run_n6_{version}_queue.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


queue = load_runner("v4_4")
previous = load_runner("v4_3")
SECOND = 1_000_000_000


def sample(at, *, swap=100, level=60, ac=True, errors=None):
    return {"monotonic_ns": at, "sampled_at": f"sample-{at}",
            "swap_used_bytes": swap, "memorystatus_level": level,
            "ac_power": ac, "thermal": {"warning": False},
            "errors": [] if errors is None else errors}


def completed_run(number=1, kind="primary", pressure=True):
    return {"run_number": number, "run_kind": kind,
            "started_at": "synthetic-start", "finished_at": "synthetic-finish",
            "methods": {method: {"status": "completed", "exit_code": 0}
                        for method in ("W", "S")},
            "environment": {"environment_pressure": pressure},
            "gate_wait_seconds": 0, "actual_concurrency_at_start": 1}


class FakeHealth:
    def __init__(self, *_args):
        pass

    def start(self):
        pass

    def close(self):
        pass


class N6V44GateTest(unittest.TestCase):
    def setUp(self):
        queue._stop_after_units.clear()

    def tearDown(self):
        queue._stop_after_units.clear()

    def recorder(self, directory, rows, module=queue):
        return module.HealthRecorder(Path(directory) / "health.jsonl", rows)

    def test_phase_locked_v43_fails_and_v44_passes_every_snapshot(self):
        # Each snapshot is 0.01 seconds before the next 1.04-second sample.
        interval = 1_040_000_000
        rows = [sample(index * interval) for index in range(240)]
        with tempfile.TemporaryDirectory() as directory:
            for last in range(100, 220):
                at = (last + 1) * interval - 10_000_000
                old = self.recorder(directory, rows[:last + 1], previous)
                fixed = self.recorder(directory, rows[:last + 1])
                with self.subTest(snapshot=last), \
                        patch.object(queue.time, "monotonic_ns", return_value=at):
                    self.assertEqual(old.unit_start_gate(),
                                     (False, ["swap_window_short"]))
                    self.assertEqual(fixed.unit_start_gate(), (True, []))

    def test_phase_locked_swap_growth_remains_blocked(self):
        interval = 1_040_000_000
        rows = [sample(index * interval) for index in range(101)]
        rows[-1]["swap_used_bytes"] += 1
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(queue.time, "monotonic_ns",
                             return_value=101 * interval - 10_000_000):
            passed, reasons = self.recorder(directory, rows).unit_start_gate()
        self.assertFalse(passed)
        self.assertIn("swap_increased", reasons)

    def test_gate_fails_closed_for_missing_stale_short_or_unhealthy_samples(self):
        valid = [sample(index * SECOND) for index in range(41, 102)]
        cases = {"empty": [], "short": valid[1:], "stale": valid[:-4]}
        for name, key, value in (
                ("missing_swap", "swap_used_bytes", None),
                ("missing_level", "memorystatus_level", None),
                ("low_level", "memorystatus_level", 39),
                ("ac_absent", "ac_power", False),
                ("ac_missing", "ac_power", None),
                ("sampling_error", "errors", ["synthetic failure"])):
            rows = copy.deepcopy(valid)
            rows[-1][key] = value
            cases[name] = rows
        interior_missing = copy.deepcopy(valid)
        interior_missing[10]["swap_used_bytes"] = None
        cases["interior_missing_swap"] = interior_missing
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(queue.time, "monotonic_ns", return_value=101 * SECOND):
            self.assertEqual(self.recorder(directory, valid).unit_start_gate(),
                             (True, []))
            for name, rows in cases.items():
                with self.subTest(reason=name):
                    passed, reasons = self.recorder(directory, rows).unit_start_gate()
                    self.assertFalse(passed)
                    self.assertTrue(reasons)

    def test_gate_reads_only_recent_tail_without_discarding_assessment_history(self):
        class TailOnlyList(list):
            reads = 0

            def __iter__(self):
                raise AssertionError("gate must not iterate/copy complete history")

            def __getitem__(self, index):
                if isinstance(index, slice):
                    raise AssertionError("gate must not copy a full history slice")
                self.reads += 1
                if self.reads > 65:
                    raise AssertionError("gate traversed beyond its recent window")
                return super().__getitem__(index)

            def __reversed__(self):
                for index in range(len(self) - 1, -1, -1):
                    yield self[index]

        rows = [sample(index * SECOND) for index in range(10_001)]
        rows[10]["memorystatus_level"] = 14
        with tempfile.TemporaryDirectory() as directory:
            recorder = self.recorder(directory, [])
            history = TailOnlyList(rows)
            recorder.samples = history
            with patch.object(queue.time, "monotonic_ns", return_value=10_000 * SECOND), \
                    patch.object(recorder, "snapshot",
                                 side_effect=AssertionError("full snapshot called")):
                self.assertEqual(recorder.unit_start_gate(), (True, []))
            self.assertIs(recorder.samples, history)
            self.assertEqual(len(history), len(rows))
            self.assertLessEqual(history.reads, 65)
            # Restore ordinary iteration only to exercise the unchanged assessment.
            recorder.samples = list(list.__iter__(history))
            assessment = recorder.assess_unit(0, 20 * SECOND)
        self.assertEqual(assessment["sample_count"], 21)
        self.assertTrue(assessment["environment_pressure"])
        self.assertEqual(assessment["reasons"], ["memorystatus_below_15"])

    def test_wait_longer_than_thirty_minutes_is_visible_and_clears_on_success(self):
        clock = {"ns": 0}
        observed = []
        state = {"status": "running"}
        gate_results = iter([(False, ["swap_increased"])] * 4 + [(True, [])])
        health = SimpleNamespace(unit_start_gate=lambda: next(gate_results))

        def advance(seconds):
            self.assertEqual(seconds, 1)
            clock["ns"] += 601 * SECOND

        actual_record = queue.record_state

        def capture(path, current):
            actual_record(path, current)
            observed.append(json.loads(path.read_text()))

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            wait_log = Path(directory) / "waits.jsonl"
            with patch.object(queue.time, "monotonic_ns", side_effect=lambda: clock["ns"]), \
                    patch.object(queue.time, "sleep", side_effect=advance), \
                    patch.object(queue, "now", return_value="synthetic-wait-start"), \
                    patch.object(queue, "record_state", side_effect=capture):
                elapsed = queue.wait_for_start_permission(
                    health, wait_log, "u1", state_path=state_path, state=state)
            logs = [json.loads(line) for line in wait_log.read_text().splitlines()]
            persisted = json.loads(state_path.read_text())
        self.assertEqual(elapsed, 2404)
        self.assertEqual(len(logs), 4)
        waiting = [row for row in observed if "gate_waiting_since" in row]
        self.assertTrue(waiting)
        self.assertEqual(waiting[-1]["gate_waiting_since"], "synthetic-wait-start")
        self.assertEqual(waiting[-1]["gate_wait_last_reasons"], ["swap_increased"])
        self.assertEqual(waiting[-1]["gate_wait_unit_id"], "u1")
        for key in ("gate_waiting_since", "gate_wait_last_reasons", "gate_wait_unit_id"):
            self.assertNotIn(key, state)
            self.assertNotIn(key, persisted)

    def test_unit_pressure_thresholds_and_status_names_match_v43(self):
        cases = [
            [sample(0), sample(SECOND, swap=100 + 512 * queue.MIB)],
            [sample(0), sample(SECOND, swap=101 + 512 * queue.MIB)],
            [sample(0), sample(SECOND, level=14)],
            [sample(0), {**sample(SECOND), "thermal": {"warning": True}}],
            [sample(0), sample(SECOND, ac=False)],
        ]
        with tempfile.TemporaryDirectory() as directory:
            for rows in cases:
                with self.subTest(last=rows[-1]):
                    self.assertEqual(
                        self.recorder(directory, rows).assess_unit(0, SECOND),
                        self.recorder(directory, rows, previous).assess_unit(0, SECOND))
        for status in ("disk_guard", "running", "stopped_between_units"):
            for complete in (False, True):
                self.assertEqual(queue.final_queue_status(status, complete),
                                 previous.final_queue_status(status, complete))


class N6V44RetryTest(unittest.TestCase):
    def setUp(self):
        queue._stop_after_units.clear()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue_path = self.root / "queue.json"
        self.source_path = self.root / "source.noindex" / "state.json"
        self.source_path.parent.mkdir()
        self.output = self.root / "retry.noindex"
        self.frozen = {
            "schema_version": 4, "status": "ready_for_execution", "branch": "B",
            "concurrency": 1, "minimum_free_disk_gib": 35,
            "health_policy": {"sample_seconds": 1}, "unit_count": 3,
            "units": [{"unit_id": f"u{index}", "resource_class": "normal"}
                      for index in range(3)],
        }
        self.queue_path.write_text(json.dumps(self.frozen))
        self.source = {
            "schema_version": 4, "status": "stopped_between_units",
            "queue_sha256": queue.sha256(self.queue_path),
            "actual_start_order": [],
            "units": {f"u{index}": {
                "status": "environment_pressure_retry_pending",
                "runs": [completed_run()]}
                for index in range(3)},
        }
        self.write_source()

    def tearDown(self):
        queue._stop_after_units.clear()
        self.temporary.cleanup()

    def write_source(self):
        self.source_path.write_text(json.dumps(self.source))

    def execute_mocked(self, units=("u2", "u0"), *, pressure=False, disk_free=None,
                       gate_status="passed", stop_on_run=False):
        calls = []
        before = self.source_path.read_bytes()

        def fake_run(unit, _preflights, output, _health, number, kind,
                     waited_seconds, concurrency):
            calls.append((unit["unit_id"], number, kind, concurrency, output))
            if stop_on_run:
                queue._stop_after_units.set()
            return {**completed_run(number, kind, pressure),
                    "gate_wait_seconds": waited_seconds,
                    "actual_concurrency_at_start": concurrency}

        with ExitStack() as stack:
            stack.enter_context(patch.object(queue, "load_preflight_rows", return_value={}))
            stack.enter_context(patch.object(queue, "spec_for", return_value=self.root / "mock-spec.json"))
            stack.enter_context(patch.object(queue, "collect_start_gate", return_value=(
                {"status": gate_status}, [])))
            stack.enter_context(patch.object(queue, "HealthRecorder", FakeHealth))
            stack.enter_context(patch.object(queue, "wait_for_start_permission", return_value=0))
            stack.enter_context(patch.object(queue.shutil, "disk_usage", return_value=
                SimpleNamespace(free=100 * queue.GIB if disk_free is None else disk_free)))
            stack.enter_context(patch.object(queue, "run_unit", side_effect=fake_run))
            # Every experiment/host subprocess is forbidden even if an unexpected
            # runner path is taken. No real campaign or health check can escape.
            stack.enter_context(patch.object(queue.subprocess, "run",
                side_effect=AssertionError("unexpected real subprocess")))
            result = queue.execute_retry(
                self.queue_path, self.output, self.source_path, list(units))
        self.assertEqual(self.source_path.read_bytes(), before)
        state = json.loads((self.output / "state.json").read_text())
        return result, state, calls

    def test_prepare_preserves_requested_order_and_hash_bound_source(self):
        frozen, source_ref, selected = queue.prepare_retry(
            self.queue_path, self.source_path, ["u2", "u0"])
        self.assertEqual([unit["unit_id"] for unit in selected], ["u2", "u0"])
        self.assertEqual(len(frozen["units"]), 3)
        self.assertEqual(Path(source_ref["path"]).resolve(), self.source_path.resolve())
        self.assertEqual(source_ref["sha256"], queue.sha256(self.source_path))

    def test_retry_runs_only_requested_units_once_and_references_original_primary(self):
        result, state, calls = self.execute_mocked()
        self.assertEqual(result, 0)
        self.assertEqual([(unit, number, kind, concurrency)
                          for unit, number, kind, concurrency, _output in calls],
                         [("u2", 2, "pressure_retry", 1),
                          ("u0", 2, "pressure_retry", 1)])
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["action"], "retry")
        self.assertEqual(state["concurrency"], 1)
        self.assertEqual(state["requested_unit_ids"], ["u2", "u0"])
        self.assertEqual(set(state["units"]), {"u2", "u0"})
        self.assertEqual(state["source_state"]["sha256"], queue.sha256(self.source_path))
        self.assertEqual([row["unit_id"] for row in state["actual_start_order"]],
                         ["u2", "u0"])
        for unit_id, unit in state["units"].items():
            self.assertEqual(unit["status"], "completed_unpressured_retry")
            self.assertEqual(unit["selected_run_number"], 2)
            self.assertEqual(len(unit["runs"]), 1)
            self.assertEqual(unit["runs"][0]["run_number"], 2)
            primary_ref = unit["primary_run_ref"]
            self.assertEqual(Path(primary_ref["state_path"]).resolve(),
                             self.source_path.resolve())
            self.assertEqual(primary_ref["state_sha256"], queue.sha256(self.source_path))
            self.assertEqual(primary_ref["json_pointer"], f"/units/{unit_id}/runs/0")
        summary = json.loads((self.output / "queue-summary.json").read_text())
        self.assertEqual(summary["recorded_run_count"], 2)
        self.assertEqual(summary["pressure_retry_run_count"], 2)
        self.assertFalse(summary["candidate_contents_opened"])
        self.assertFalse(summary["j_review_performed"])

    def test_existing_output_is_rejected_without_changes(self):
        self.output.mkdir()
        sentinel = self.output / "preserve.txt"
        sentinel.write_text("existing output")
        before = self.source_path.read_bytes()
        with patch.object(queue, "run_unit") as run_unit, \
                patch.object(queue, "collect_start_gate") as gate, \
                self.assertRaises((ValueError, FileExistsError)):
            queue.execute_retry(self.queue_path, self.output, self.source_path, ["u0"])
        run_unit.assert_not_called()
        gate.assert_not_called()
        self.assertEqual(sentinel.read_text(), "existing output")
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(self.source_path.read_bytes(), before)

    def test_prepare_rejects_duplicate_unknown_or_empty_selection(self):
        for selected in (["u0", "u0"], ["unknown"], []):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                queue.prepare_retry(self.queue_path, self.source_path, selected)

    def test_prepare_rejects_source_mismatch_and_non_retryable_primary_records(self):
        original = copy.deepcopy(self.source)
        mutations = {
            "not_stopped": lambda state: state.update(status="running"),
            "queue_hash_changed": lambda state: state.update(queue_sha256="0" * 64),
            "wrong_status": lambda state: state["units"]["u0"].update(status="completed_unpressured"),
            "no_primary": lambda state: state["units"]["u0"].update(runs=[]),
            "unfinished_primary": lambda state: state["units"]["u0"]["runs"][0].pop("finished_at"),
            "unpressured_primary": lambda state: state["units"]["u0"]["runs"][0]["environment"].update(environment_pressure=False),
            "missing_method": lambda state: state["units"]["u0"]["runs"][0]["methods"].pop("S"),
            "failed_method": lambda state: state["units"]["u0"]["runs"][0]["methods"]["W"].update(status="runner_nonzero"),
            "already_retried": lambda state: state["units"]["u0"]["runs"].append(completed_run(2, "pressure_retry")),
            "duplicate_primary": lambda state: state["units"]["u0"]["runs"].append(completed_run()),
        }
        for name, mutate in mutations.items():
            self.source = copy.deepcopy(original)
            mutate(self.source)
            self.write_source()
            with self.subTest(reason=name), self.assertRaises(ValueError):
                queue.prepare_retry(self.queue_path, self.source_path, ["u0"])

    def test_pressured_retry_finishes_without_another_retry(self):
        result, state, calls = self.execute_mocked(units=("u0",), pressure=True)
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(state["status"], "completed")
        unit = state["units"]["u0"]
        self.assertEqual(unit["status"], "retry_environment_pressure")
        self.assertIsNone(unit["selected_run_number"])
        self.assertEqual(len(unit["runs"]), 1)

    def test_stop_after_active_unit_preserves_remaining_pending_retry(self):
        result, state, calls = self.execute_mocked(stop_on_run=True)
        self.assertEqual(result, 2)
        self.assertEqual([row[0] for row in calls], ["u2"])
        self.assertEqual(state["status"], "stopped_between_units")
        self.assertEqual(state["units"]["u0"]["status"],
                         "environment_pressure_retry_pending")
        self.assertEqual(state["units"]["u0"]["runs"], [])

    def test_disk_guard_stays_visible_and_starts_no_retry(self):
        result, state, calls = self.execute_mocked(disk_free=0)
        self.assertEqual(result, 2)
        self.assertEqual(calls, [])
        self.assertEqual(state["status"], "disk_guard")
        self.assertTrue(all(unit["runs"] == [] for unit in state["units"].values()))

    def test_failed_start_gate_starts_no_retry(self):
        result, state, calls = self.execute_mocked(gate_status="failed")
        self.assertEqual(result, 2)
        self.assertEqual(calls, [])
        self.assertEqual(state["status"], "start_gate_failed")
        self.assertTrue(all(unit["runs"] == [] for unit in state["units"].values()))


if __name__ == "__main__":
    unittest.main()
