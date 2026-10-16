"""N6-B2 prestart gate checks without a campaign or live host sampling."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/n6_b2_prestart_gate.py"
SPEC = importlib.util.spec_from_file_location("n6_b2_prestart_gate_test_module", MODULE)
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


class N6B2PrestartGateTest(unittest.TestCase):
    def make_inputs(self, root):
        specs = []
        units = []
        for index in range(30):
            unit = {"unit_id": f"u{index}"}
            for key in ("whole", "split"):
                path = root / "specs" / f"u{index}-{key}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"memory_cap_bytes": 10 * gate.GIB}))
                unit[f"{key}_spec"] = path.relative_to(root).as_posix()
                unit[f"{key}_spec_sha256"] = gate.sha256(path)
                specs.append({"spec": unit[f"{key}_spec"],
                              "spec_sha256": unit[f"{key}_spec_sha256"]})
            units.append(unit)
        queue_path = root / "queue.json"
        queue_path.write_text(json.dumps({
            "schema_version": 4, "status": "ready_for_execution", "branch": "B",
            "unit_count": 30, "units": units, "concurrency": 3,
            "minimum_free_disk_gib": 35,
            "budget_policy": {"physical_memory_cap_bytes": 10 * gate.GIB,
                              "total_budget_seconds": 3600,
                              "split_attempt_cap_seconds": 30,
                              "seeds": [2026100601, 2026100602, 2026100603]},
        }))
        original = root / "library/source.circom"
        copy = root / "snapshot/source.circom"
        original.parent.mkdir(parents=True)
        copy.parent.mkdir(parents=True)
        original.write_text("pragma circom 2.2.1;\n")
        copy.write_bytes(original.read_bytes())
        original_name = original.relative_to(root).as_posix()
        copy_name = copy.relative_to(root).as_posix()
        file_hash = gate.sha256(original)
        snapshot_copy = {"path": copy_name, "sha256": file_hash,
                         "matches_external": True}
        include_path = root / "include.json"
        include_path.write_text(json.dumps({
            "schema_version": 3, "status": "passed", "spec_count": 60, "specs": specs,
            "unresolved_include_count": 0, "snapshot_copy_mismatch_count": 0,
            "queue_sha256": gate.sha256(queue_path),
            "external_unique_file_count": 1,
            "external_unique_file_without_copy_count": 0,
            "external_reference_missing_copy_count": 0,
            "external_unique_files": [{"path": original_name, "sha256": file_hash,
                                       "reference_count": 1,
                                       "snapshot_copies": [snapshot_copy]}],
            "library_root_external_reference_count": 1,
            "library_root_external_unique_file_count": 1,
            "library_root_external_missing_copy_count": 0,
            "library_root_external_copy_mismatch_count": 0,
            "library_root_external_files": [{"path": original_name, "sha256": file_hash,
                                             "snapshot_copies": [snapshot_copy]}],
            "library_root_external_references": [{"path": original_name,
                                                   "sha256": file_hash,
                                                   "snapshot_copies": [snapshot_copy]}],
        }))
        return queue_path, include_path

    def test_input_binding_fails_closed_on_queue_hash_and_memory_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue_path, include_path = self.make_inputs(root)
            with patch.object(gate, "ROOT", root), \
                    patch.object(gate, "DEFAULT_INCLUDES", include_path), \
                    patch.object(gate, "SOURCE_QUEUE_SHA256", gate.sha256(queue_path)), \
                    patch.object(gate, "SOURCE_INCLUDE_SHA256", gate.sha256(include_path)):
                row = gate.validate_inputs(queue_path, include_path)
                self.assertEqual(row["spec_count"], 60)
                copy = root / "snapshot/source.circom"
                copy.write_text("mismatched\n")
                with self.assertRaisesRegex(ValueError, "snapshot copy mismatch"):
                    gate.validate_inputs(queue_path, include_path)
                copy.write_text("pragma circom 2.2.1;\n")
                include = json.loads(include_path.read_text())
                include["queue_sha256"] = "0" * 64
                include_path.write_text(json.dumps(include))
                with self.assertRaisesRegex(ValueError, "include provenance"):
                    gate.validate_inputs(queue_path, include_path)
                include["queue_sha256"] = gate.sha256(queue_path)
                include_path.write_text(json.dumps(include))
                spec_path = root / "specs/u0-whole.json"
                spec_path.write_text(json.dumps({"memory_cap_bytes": 20 * gate.GIB}))
                with self.assertRaisesRegex(ValueError, "spec or include provenance hash"):
                    gate.validate_inputs(queue_path, include_path)

    def test_process_classification_covers_tools_and_n6_execution_scripts(self):
        for command in ("/tmp/zkFuzz --help", "/opt/circom file.circom",
                        "cargo test", "/tmp/zkfDO experiment lift",
                        "python3 /repo/scripts/run_n6_v4_3_queue.py --action execute",
                        "python3 /repo/scripts/n6_j1_execute.py"):
            with self.subTest(command=command):
                self.assertTrue(gate.classify_process(command))
        self.assertFalse(gate.classify_process("python3 -m unittest tests.n6_b2_test"))
        self.assertFalse(gate.classify_process(
            "zsh -lc 'python3 scripts/n6_b2_prestart_gate.py --queue queue.json'"))

    def test_busy_process_prevents_self_test_and_records_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "gates/prestart-gates.json"
            with patch.object(gate, "validate_inputs", return_value={
                    "minimum_free_bytes": 35 * gate.GIB}), \
                    patch.object(gate, "process_inventory", return_value=(
                        {"exit_code": 0}, [{"pid": 100, "command": "cargo test"}])), \
                    patch.object(gate.shutil, "which", return_value="/usr/bin/caffeinate"), \
                    patch.object(gate, "pmset_available", return_value={"exit_code": 0}), \
                    patch.object(gate.shutil, "disk_usage", return_value=SimpleNamespace(
                        total=100 * gate.GIB, used=0, free=100 * gate.GIB)), \
                    patch.object(gate, "run_self_test") as self_test:
                result = gate.evaluate(Path("queue.json"), Path("include.json"), output)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["checks"]["no_other_heavy_experiment"])
            self_test.assert_not_called()
            self.assertTrue(output.is_file())

    def test_failed_monitor_test_blocks_host_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "gates/prestart-gates.json"
            with patch.object(gate, "validate_inputs", return_value={
                    "minimum_free_bytes": 35 * gate.GIB}), \
                    patch.object(gate, "process_inventory", return_value=(
                        {"exit_code": 0}, [])), \
                    patch.object(gate.shutil, "which", return_value="/usr/bin/caffeinate"), \
                    patch.object(gate, "pmset_available", return_value={"exit_code": 0}), \
                    patch.object(gate.shutil, "disk_usage", return_value=SimpleNamespace(
                        total=100 * gate.GIB, used=0, free=100 * gate.GIB)), \
                    patch.object(gate, "run_self_test", return_value=({}, True)), \
                    patch.object(gate, "run_fail_closed_test", return_value=({}, False)), \
                    patch.object(gate, "collect_host_start_gate") as host_gate:
                result = gate.evaluate(Path("queue.json"), Path("include.json"), output)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["checks"]["resource_monitor_failure_fail_closed"])
            host_gate.assert_not_called()
            with self.assertRaises(FileExistsError):
                gate.evaluate(Path("queue.json"), Path("include.json"), output)


if __name__ == "__main__":
    unittest.main()
