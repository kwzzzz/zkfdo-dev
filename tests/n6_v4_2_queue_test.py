"""Deterministic N6 queue v4.2 environment-gate tests; no campaign execution."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/run_n6_v4_2_queue.py"
SPEC = importlib.util.spec_from_file_location("n6_v4_2_queue_test_module", MODULE)
queue = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = queue
SPEC.loader.exec_module(queue)


class N6V4QueueTest(unittest.TestCase):
    def test_swap_parser_uses_reported_unit(self):
        with patch.object(queue, "run_text", return_value=(
                "total = 43008.00M  used = 41818.50M  free = 1189.50M")):
            self.assertEqual(queue.swap_used_bytes(), round(41818.5 * 1024**2))

    def test_stable_swap_requires_full_window_and_no_growth(self):
        stable = [
            {"monotonic_ns": 0, "swap_used_bytes": 100},
            {"monotonic_ns": 60_000_000_000, "swap_used_bytes": 100},
        ]
        self.assertEqual(queue.stable_swap_window(stable), (True, "stable"))
        increased = [stable[0], {"monotonic_ns": 60_000_000_000,
                                 "swap_used_bytes": 101}]
        self.assertEqual(queue.stable_swap_window(increased), (False, "swap_increased"))
        self.assertEqual(queue.stable_swap_window(stable[:1]),
                         (False, "swap_samples_missing"))

    def test_thermal_warning_ignores_explicit_no_warning_lines(self):
        clean = "Note: No thermal warning level has been recorded\n"
        with patch.object(queue, "run_text", return_value=clean):
            self.assertFalse(queue.thermal_status()["warning"])
        with patch.object(queue, "run_text", return_value="Thermal warning level: 1\n"):
            self.assertTrue(queue.thermal_status()["warning"])

    def test_unit_pressure_uses_swap_memory_and_thermal_thresholds(self):
        with tempfile.TemporaryDirectory() as temporary:
            recorder = queue.HealthRecorder(Path(temporary) / "health.jsonl", [])
            recorder.samples = [
                {"monotonic_ns": 10, "sampled_at": "first", "swap_used_bytes": 100,
                 "memorystatus_level": 50, "thermal": {"warning": False}, "errors": []},
                {"monotonic_ns": 20, "sampled_at": "last",
                 "swap_used_bytes": 100 + 512 * queue.MIB + 1,
                 "memorystatus_level": 14, "thermal": {"warning": True}, "errors": []},
            ]
            result = recorder.assess_unit(10, 20)
        self.assertTrue(result["environment_pressure"])
        self.assertEqual(result["reasons"], [
            "memorystatus_below_15", "swap_increase_over_512_mib", "thermal_warning"])

    def test_incomplete_health_record_cannot_be_selected_as_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            recorder = queue.HealthRecorder(Path(temporary) / "health.jsonl", [])
            recorder.samples = [{"monotonic_ns": 10, "sampled_at": "only",
                                 "swap_used_bytes": None, "memorystatus_level": None,
                                 "errors": ["unreadable"]}]
            result = recorder.assess_unit(10, 20)
        self.assertTrue(result["environment_pressure"])
        self.assertIn("health_monitor_incomplete", result["reasons"])

    def test_a_q_waits_for_every_a_d_unit(self):
        aq = {"unit_id": "aq", "phase": "A-Q"}
        ad = {"unit_id": "ad", "phase": "A-D"}
        self.assertFalse(queue.phase_allowed(aq, [aq, ad], {}))
        self.assertFalse(queue.phase_allowed(aq, [aq], {object(): ad}))
        self.assertTrue(queue.phase_allowed(aq, [aq], {}))

    def test_million_plus_selection_skips_to_normal_unit(self):
        pending = [
            {"unit_id": "large", "phase": None, "resource_class": "million_plus"},
            {"unit_id": "normal", "phase": None, "resource_class": "normal"},
        ]
        selected = queue.select_unit(pending, {}, True)
        self.assertEqual(selected["unit_id"], "normal")

    def test_failed_start_gate_exits_before_any_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue_path = root / "queue.json"
            queue_path.write_text("{}\n")
            output = root / "execute.noindex"
            frozen = {
                "units": [{"unit_id": "u1"}],
                "health_policy": {"sample_seconds": 1},
            }
            gate = {"status": "failed", "checks": {"ac_power": False}}
            with patch.object(queue, "load_queue", return_value=frozen), \
                    patch.object(queue, "load_preflight_rows", return_value={}), \
                    patch.object(queue, "collect_start_gate", return_value=(gate, [])), \
                    patch.object(queue, "run_unit") as run_unit:
                exit_code = queue.execute(queue_path, output)
            self.assertEqual(exit_code, 2)
            run_unit.assert_not_called()
            state = json.loads((output / "state.json").read_text())
            summary = json.loads((output / "queue-summary.json").read_text())
            self.assertEqual(state["status"], "start_gate_failed")
            self.assertEqual(summary["start_gate_status"], "failed")

    def test_disk_guard_is_not_overwritten_by_finalization(self):
        self.assertEqual(queue.final_queue_status("disk_guard", False), "disk_guard")
        self.assertEqual(queue.final_queue_status("running", False),
                         "stopped_between_units")


    def test_start_gate_window_excludes_setup_time(self):
        def slow(value):
            def read(*_args, **_kwargs):
                time.sleep(0.05)
                return value
            return read

        def reader(include_thermal=False):
            return {"monotonic_ns": time.monotonic_ns(), "swap_used_bytes": 100,
                    "memorystatus_level": 75, "errors": []}

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(queue, "ac_power_connected", slow((True, "ac"))), \
                patch.object(queue, "low_power_mode", slow((0, "lp"))), \
                patch.object(queue, "thermal_status", slow({"warning": False})), \
                patch.object(queue, "top_physical_processes",
                             return_value={"processes": [{}] * 10}):
            gate, samples = queue.collect_start_gate(
                Path(directory), duration_seconds=2, sample_seconds=0.5,
                sample_reader=reader)
        self.assertGreaterEqual(samples[-1]["monotonic_ns"] - samples[0]["monotonic_ns"],
                                2_000_000_000)
        self.assertEqual(gate["swap_window_reason"], "stable")
        self.assertEqual(gate["status"], "passed")

    def test_load_queue_accepts_only_concurrency_one_or_three(self):
        frozen = {
            "schema_version": 4,
            "status": "ready_for_execution",
            "branch": "B",
            "minimum_free_disk_gib": 35,
            "health_policy": {"sample_seconds": 1},
            "unit_count": 1,
            "units": [{"unit_id": "u1"}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queue.json"
            for concurrency in (1, 3):
                path.write_text(json.dumps({**frozen, "concurrency": concurrency}))
                self.assertEqual(queue.load_queue(path)["concurrency"], concurrency)
            for concurrency in (None, 0, 2, 4, True, "1", 3.0):
                path.write_text(json.dumps({**frozen, "concurrency": concurrency}))
                with self.subTest(concurrency=concurrency), \
                        self.assertRaisesRegex(ValueError, "concurrency must be 1 or 3"):
                    queue.load_queue(path)

    def test_concurrency_one_runs_units_without_overlap(self):
        units = [{"unit_id": f"u{index}", "resource_class": "normal"}
                 for index in range(3)]
        frozen = {"concurrency": 1, "minimum_free_disk_gib": 35, "units": units}
        gate = {"status": "passed"}
        lock = threading.Lock()
        active = 0
        maximum_active = 0

        class FakeHealthRecorder:
            def __init__(self, *_args):
                pass

            def start(self):
                pass

            def close(self):
                pass

        def fake_run_unit(unit, _preflights, _output, _health, _run_number,
                          _run_kind, gate_wait_seconds, actual_concurrency):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {"run_kind": "primary", "gate_wait_seconds": gate_wait_seconds,
                    "actual_concurrency_at_start": actual_concurrency,
                    "environment": {"environment_pressure": False}}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue_path = root / "queue.json"
            queue_path.write_text("{}\n")
            output = root / "execute.noindex"
            queue._stop_after_units.clear()
            with patch.object(queue, "load_queue", return_value=frozen), \
                    patch.object(queue, "load_preflight_rows", return_value={}), \
                    patch.object(queue, "collect_start_gate", return_value=(gate, [])), \
                    patch.object(queue, "HealthRecorder", FakeHealthRecorder), \
                    patch.object(queue, "wait_for_start_permission", return_value=0), \
                    patch.object(queue.shutil, "disk_usage",
                                 return_value=SimpleNamespace(free=100 * queue.GIB)), \
                    patch.object(queue, "run_unit", side_effect=fake_run_unit):
                exit_code = queue.execute(queue_path, output)
            state = json.loads((output / "state.json").read_text())
        self.assertEqual(exit_code, 0)
        self.assertEqual(maximum_active, 1)
        self.assertEqual([row["actual_concurrency"]
                          for row in state["actual_start_order"]], [1, 1, 1])
        self.assertEqual([row["unit_id"] for row in state["actual_start_order"]],
                         ["u0", "u1", "u2"])

if __name__ == "__main__":
    unittest.main()
