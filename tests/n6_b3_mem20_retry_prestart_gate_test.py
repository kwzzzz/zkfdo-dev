"""Deterministic retry adapter tests; host checks and input files are mocked."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/n6_b3_mem20_retry_prestart_gate.py"
SPEC = importlib.util.spec_from_file_location("n6_b3_mem20_retry_gate_test_module", MODULE)
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


class N6B3Mem20RetryPrestartGateTest(unittest.TestCase):
    def test_all_runner_hooks_use_v4_4(self):
        self.assertIs(gate.mem20.runner, gate.runner)
        self.assertEqual(gate.b2.QUEUE_RUNNER, gate.QUEUE_RUNNER)
        self.assertEqual(gate.QUEUE_RUNNER.name, "run_n6_v4_4_queue.py")
        self.assertNotIn("mem20-retry.noindex", gate.DEFAULT_OUTPUT.parts)
        self.assertEqual(gate.DEFAULT_OUTPUT.name, "prestart-gate-mem20-retry.json")

    def test_retry_validation_reuses_runner_and_preserves_selected_order(self):
        source_ref = {"path": "old/state.json", "sha256": "0" * 64}
        selected = [{"unit_id": "u2"}, {"unit_id": "u1"}]
        with patch.object(gate.runner, "prepare_retry", return_value=(
                {}, source_ref, selected)) as prepare, \
                patch.object(gate.mem20, "validate_inputs", return_value={
                    "unit_count": 6, "spec_count": 12}) as original:
            result = gate.validate_inputs(Path("queue.json"), Path("includes.json"),
                                          Path("state.json"), ["u2", "u1"])
        prepare.assert_called_once_with(Path("queue.json"), Path("state.json"), ["u2", "u1"])
        original.assert_called_once_with(Path("queue.json"), Path("includes.json"))
        self.assertEqual(result["unit_count"], 6)
        self.assertEqual(result["retry"], {
            "source_state": source_ref, "selected_unit_ids": ["u2", "u1"],
            "selected_unit_count": 2, "selected_spec_count": 4,
            "run_number": 2, "run_kind": "pressure_retry", "concurrency": 1,
        })

    def test_bad_retry_state_fails_before_reused_input_validation(self):
        with patch.object(gate.runner, "prepare_retry", side_effect=ValueError(
                "source state must be stopped_between_units")), \
                patch.object(gate.mem20, "validate_inputs") as original:
            with self.assertRaisesRegex(ValueError, "stopped_between_units"):
                gate.validate_inputs(Path("queue.json"), Path("includes.json"),
                                     Path("state.json"), ["u1"])
        original.assert_not_called()

    def test_other_mem20_gate_processes_are_heavy(self):
        for script in ("n6_b3_mem20_prestart_gate.py",
                       "n6_b3_mem20_retry_prestart_gate.py", "run_n6_v4_4_queue.py"):
            with self.subTest(script=script):
                self.assertTrue(gate.classify_process(f"python3 /repo/scripts/{script}"))
        self.assertFalse(gate.classify_process("python3 -m unittest tests.n6_v4_4_queue_test"))

    def test_failed_retry_input_blocks_self_tests_and_restores_validator(self):
        previous = gate.b2.validate_inputs
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "prestart.json"
            with patch.object(gate, "validate_inputs", side_effect=ValueError("bad retry")), \
                    patch.object(gate.b2, "process_inventory", return_value=(
                        {"exit_code": 0}, [])), \
                    patch.object(gate.b2.shutil, "which", return_value="/usr/bin/caffeinate"), \
                    patch.object(gate.b2, "pmset_available", return_value={"exit_code": 0}), \
                    patch.object(gate.b2.shutil, "disk_usage", return_value=SimpleNamespace(
                        total=100 * gate.b2.GIB, used=0, free=100 * gate.b2.GIB)), \
                    patch.object(gate.b2.os, "getloadavg", return_value=(0, 0, 0)), \
                    patch.object(gate.b2, "run_self_test") as self_test, \
                    patch.object(gate.b2, "collect_host_start_gate") as host_gate:
                result = gate.evaluate(Path("queue.json"), Path("includes.json"),
                                       Path("state.json"), ["u1"], output)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["checks"]["queue_and_specs"])
            self.assertIn("bad retry", result["errors"][0])
            self_test.assert_not_called()
            host_gate.assert_not_called()
            self.assertIs(gate.b2.validate_inputs, previous)
            record = json.loads(output.read_text())
            self.assertEqual(record["queue_runner"]["path"], "scripts/run_n6_v4_4_queue.py")
            self.assertEqual(record["gate_adapter"]["path"], MODULE.relative_to(ROOT).as_posix())

    def test_existing_output_or_gate_directory_is_preserved(self):
        previous = gate.b2.validate_inputs
        for existing in ("output", "directory"):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "prestart.json"
                if existing == "output":
                    output.write_text("preserve\n")
                else:
                    output.with_suffix("").mkdir()
                with patch.object(gate.b2, "process_inventory") as inventory:
                    with self.assertRaises(FileExistsError):
                        gate.evaluate(Path("queue.json"), Path("includes.json"),
                                      Path("state.json"), ["u1"], output)
                inventory.assert_not_called()
                self.assertIs(gate.b2.validate_inputs, previous)
                if existing == "output":
                    self.assertEqual(output.read_text(), "preserve\n")

    def test_validate_only_cli_never_evaluates_host(self):
        with patch.object(gate, "validate_inputs", return_value={
                "unit_count": 6, "spec_count": 12, "preflight_row_count": 12,
                "retry": {"selected_unit_ids": ["u2", "u1"]}}) as inputs, \
                patch.object(gate, "evaluate") as evaluate, \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = gate.main(["--queue", "queue.json", "--include-provenance", "includes.json",
                              "--from-state", "state.json", "--units", "u2", "u1",
                              "--validate-inputs-only"])
        self.assertEqual(code, 0)
        inputs.assert_called_once_with(Path("queue.json"), Path("includes.json"),
                                       Path("state.json"), ["u2", "u1"])
        evaluate.assert_not_called()
        self.assertEqual(json.loads(stdout.getvalue())["status"], "valid")


if __name__ == "__main__":
    unittest.main()
