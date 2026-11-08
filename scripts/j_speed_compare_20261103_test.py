#!/usr/bin/env python3
"""Synthetic tests only: no saved J case or Circom compilation is executed."""
import copy
import importlib.util
import json
import os
import signal
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("j_speed_compare_20261103.py")
spec = importlib.util.spec_from_file_location("j_speed_compare", MODULE_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def result():
    return {"preparation": {"status": "ok", "reason": None}, "component_classification": "tcct_deviation", "property": "tcct", "sites_found": 1, "verdict_counts": {"entrypoint_violation": 1}, "classes": [{"pattern": "main.test", "representative": "main.test", "sites": 1, "verdict": "entrypoint_violation", "reason": "output_differs", "rust_unsatisfied": 0, "snarkjs": "correct", "public_inputs_equal": True, "outputs_differing": 1, "synthesis": {"reached_with": "honest"}, "evidence": {"deviated_wtns_sha256": "one"}, "predicates": []}], "costs": {"wall_seconds": 0.1}}


class ComparisonTests(unittest.TestCase):
    def test_checks_classes_and_predicates_are_semantic(self):
        base = result()
        for field, value in [("verdict", "unknown"), ("rust_unsatisfied", 1), ("snarkjs", "invalid"), ("public_inputs_equal", False), ("outputs_differing", 0), ("sites", 2), ("representative", "main.other")]:
            other = copy.deepcopy(base)
            other["classes"][0][field] = value
            self.assertFalse(runner.compare_results(base, other)["semantic_equal"], field)
        other = copy.deepcopy(base)
        other["classes"][0]["predicates"] = [{"verdict": "unknown"}]
        self.assertFalse(runner.compare_results(base, other)["semantic_equal"])

    def test_basis_and_witness_identity_changes_are_reported_separately(self):
        base = result()
        other = copy.deepcopy(base)
        other["costs"]["wall_seconds"] = 9.0
        other["classes"][0]["synthesis"]["reached_with"] = "hint_injection"
        other["classes"][0]["evidence"]["deviated_wtns_sha256"] = "two"
        comparison = runner.compare_results(base, other)
        self.assertTrue(comparison["semantic_equal"])
        self.assertFalse(comparison["basis_equal"])
        self.assertEqual(len(comparison["basis_differences"]), 2)

    def test_disk_gate_boundary(self):
        disk = shutil_usage = type("Usage", (), {"free": runner.MIN_FREE_BYTES - 1, "used": 0, "total": 999})()
        with patch.object(runner.shutil, "disk_usage", return_value=disk):
            with self.assertRaisesRegex(RuntimeError, "disk gate"):
                runner.disk_gate(runner.ROOT)
        shutil_usage.free += 1
        with patch.object(runner.shutil, "disk_usage", return_value=shutil_usage):
            self.assertEqual(runner.disk_gate(runner.ROOT)["free"], runner.MIN_FREE_BYTES)


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zkfdo-j-speed-test-")
        self.directory = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_wait4_captures_descendant_cpu_and_exit_status(self):
        child = "import time; end=time.process_time()+0.15\nwhile time.process_time()<end: pass"
        script = "import subprocess,sys; subprocess.run([sys.executable,'-c',sys.argv[1]],check=True); sys.exit(7)"
        record = runner.run_process([sys.executable, "-c", script, child], self.directory)
        self.assertEqual(record["returncode"], 7)
        self.assertGreater(record["cpu_seconds"], 0.13)
        self.assertGreater(record["wall_seconds"], 0.13)
        self.assertEqual(json.loads((self.directory / "child.json").read_text())["pid"], record["pid"])

    def test_interrupt_reaps_child_and_preserves_cost(self):
        original_sleep = runner.time.sleep
        previous_term = signal.getsignal(signal.SIGTERM)

        def interrupt_after_start(_seconds):
            original_sleep(0.08)
            raise KeyboardInterrupt("synthetic test interrupt")

        with patch.object(runner.time, "sleep", side_effect=interrupt_after_start):
            with self.assertRaises(KeyboardInterrupt):
                runner.run_process([sys.executable, "-c", "while True: pass"], self.directory)
        receipt = json.loads((self.directory / "interrupted.json").read_text())
        metrics = receipt["resources"]
        self.assertEqual(receipt["exception"], "KeyboardInterrupt")
        self.assertEqual(metrics["returncode"], -signal.SIGTERM)
        self.assertGreater(metrics["wall_seconds"], 0.05)
        self.assertGreaterEqual(metrics["cpu_seconds"], 0)
        self.assertEqual(receipt["reaped_pid"], metrics["pid"])
        with self.assertRaises(ChildProcessError):
            os.waitpid(metrics["pid"], os.WNOHANG)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous_term)

    def test_profile_uses_new_binary_and_only_marks_historical_drift(self):
        sources = self.directory / "source"
        sources.mkdir()
        circuit = sources / "test.circom"
        circuit.write_text("template T() {}\n")
        candidate = self.directory / "candidate.json"
        candidate.write_text("{}")
        request = self.directory / "request.json"
        request.write_text(json.dumps({"source_root": str(sources), "library_paths": [], "entrypoint": str(circuit), "component_wrapper": str(circuit), "base_input": str(candidate), "candidate": {"path": str(candidate)}}))
        historical = self.directory / "out/result.json"
        historical.parent.mkdir()
        historical.write_text(json.dumps(result()))
        changed = result()
        changed["classes"][0]["rust_unsatisfied"] = 1
        engine = self.directory / "profile-engine.py"
        engine.write_text("#!" + sys.executable + "\nimport sys,json\nfrom pathlib import Path\na=sys.argv\nassert '--profile-only' in a and '--j-jobs' not in a\nout=Path(a[a.index('--output')+1]);out.mkdir(parents=True)\n(out/'result.json').write_text(json.dumps(" + repr(changed) + "))\n(out/'j-profile.json').write_text('{}')\n")
        engine.chmod(0o700)
        run_root = self.directory / "runs"
        run_root.mkdir()
        with patch.object(runner, "BASELINE", self.directory / "missing-baseline"), patch.object(runner, "TOOLS", {}), patch.object(runner, "disk_gate", return_value={}):
            record = runner.run_arm(0, request, "profile", run_root, engine)
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["mode"], "legacy_semantics_profile_only")
        self.assertFalse(record["historical_comparison"]["semantic_equal"])
        self.assertNotIn("comparison", record)
        self.assertTrue(record["profile_sidecar"]["exists"])
        self.assertEqual(json.loads((run_root / "binary-v24.json").read_text())["path"], str(engine))
        self.assertFalse((run_root / "STOP.json").exists())
        self.assertEqual(runner.ARMS, ("v23", "j1", "j4"))

    def test_mismatch_writes_stop_and_prevents_later_arm(self):
        sources = self.directory / "source"
        sources.mkdir()
        (sources / "test.circom").write_text("template T() {}\n")
        candidate = self.directory / "candidate.json"
        candidate.write_text("{}")
        request = self.directory / "request.json"
        request.write_text(json.dumps({"source_root": str(sources), "library_paths": [], "entrypoint": str(sources / "test.circom"), "component_wrapper": str(sources / "test.circom"), "base_input": str(candidate), "candidate": {"path": str(candidate)}}))
        engine = self.directory / "engine.py"
        engine.write_text("#!" + sys.executable + "\nimport sys,json\nfrom pathlib import Path\na=sys.argv\nout=Path(a[a.index('--output')+1]);out.mkdir(parents=True)\nr=" + repr(result()) + "\nif '--j-jobs' in a: r['classes'][0]['rust_unsatisfied']=1\n(out/'result.json').write_text(json.dumps(r))\n")
        engine.chmod(0o700)
        run_root = self.directory / "runs"
        run_root.mkdir()
        with patch.object(runner, "BASELINE", engine), patch.object(runner, "BASELINE_SHA", runner.sha(engine)), patch.object(runner, "TOOLS", {}), patch.object(runner, "disk_gate", return_value={}):
            runner.run_arm(0, request, "v23", run_root, engine)
            with self.assertRaisesRegex(RuntimeError, "semantic_mismatch"):
                runner.run_arm(0, request, "j1", run_root, engine)
            self.assertTrue((run_root / "STOP.json").exists())
            with self.assertRaisesRegex(RuntimeError, "global STOP"):
                runner.run_arm(0, request, "j4", run_root, engine)
            self.assertFalse((run_root / "requests/00/j4").exists())
            first = json.loads((run_root / "requests/00/v23/record.json").read_text())
            self.assertEqual(first["historical_comparison"]["status"], "historical_result_missing")
            second = json.loads((run_root / "requests/00/j1/record.json").read_text())
            self.assertEqual(second["comparison"]["semantic_differences"][0]["path"], "/classes/0/rust_unsatisfied")


if __name__ == "__main__":
    unittest.main()
