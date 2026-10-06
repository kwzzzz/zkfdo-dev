import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class E02FixedMeasurementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads((ROOT / "runs/e02-production-mains-2026-10-05/entrypoint-roles-and-paths-v2.json").read_text())
        cls.lock = json.loads((ROOT / "runs/e02-production-mains-2026-10-05/procedure-lock-v6.json").read_text())

    def test_denominator_and_roles_are_locked_without_dropping_harnesses(self):
        self.assertEqual(len(self.inventory["entries"]), 329)
        self.assertEqual(self.inventory["roles"], {"deployment_main": 177, "test_mock_harness": 152})
        self.assertEqual(self.lock["population"], {"all": 329, "deployment_main": 177,
                                                   "test_mock_harness": 152})

    def test_selfxyz_missing_include_retries_have_only_static_derived_paths(self):
        rows = [row for row in self.inventory["entries"]
                if row["repository"] == "selfxyz/self" and row["role"] == "deployment_main"
                and row["e01_compile"]["status"] != "success"]
        self.assertEqual(len(rows), 87)
        for row in rows:
            derived = row["derived_library_evidence"]
            self.assertTrue(any(item["literal"] == "node_modules/circomlib/circuits" for item in derived))
            self.assertTrue(all(item["source_kind"] in {"circom_option", "circomkit_include"} for item in derived))
            self.assertTrue(all(Path(item["path"]).is_dir() for item in derived))

    def test_tool_hash_and_zero_search_are_fixed(self):
        binary = ROOT / self.lock["tools"]["zkfDO_copy"]["path"]
        self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(),
                         "f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1")
        self.assertEqual(self.lock["zkfuzz_invocations"], 0)


class E02SummaryLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = load("e02_summary", "scripts/summarize_e02_production_mains.py")

    def test_compile_sensitivity_does_not_replace_primary_column(self):
        record = {"e01_compile": {"status": "timeout"},
                  "compile_120": {"status": "timeout"},
                  "compile_600": {"status": "success", "constraints": 10}}
        source, chosen = self.summary.chosen_compile(record)
        self.assertEqual(source, "compile_600")
        self.assertEqual(record["compile_120"]["status"], "timeout")
        self.assertEqual(chosen["constraints"], 10)

    def test_prepare_sensitivity_remains_a_separate_column(self):
        record = {"prepare_300": {"status": "timeout"}, "prepare_900": {"status": "success"}}
        self.assertEqual(self.summary.preparation_status(record), ("unknown", "prepare_900_without_verified_outcome"))
        self.assertEqual(record["prepare_300"]["status"], "timeout")

    def test_discovery_timeout_is_not_silently_a_missing_preparation(self):
        record = {"discovery": {"status": "timeout"}, "prepare_300": {"status": "not_started"}}
        self.assertEqual(self.summary.preparation_status(record), ("timeout", "discovery"))

    def test_successful_sensitivity_has_no_reused_compile_failure_reason(self):
        measured = {"reason": "e01_compile_success_reused"}
        prep = {"preparation_outcome": {"status": "success"}}
        self.assertIsNone(self.summary.remaining_reason(measured, prep, {"status": "success"}, {}))

    def test_relative_paths_preserve_nested_measurements_and_input(self):
        original = {"paths": [str(ROOT / "runs/a"), {"path": str(ROOT / "runs/b")}],
                    "command": "compiler -l " + str(ROOT / "runs/lib"),
                    "seconds": 132.4, "verdict": "timeout"}
        expected = {"paths": ["runs/a", {"path": "runs/b"}],
                    "command": "compiler -l runs/lib", "seconds": 132.4, "verdict": "timeout"}
        actual = self.summary.repository_relative(original)
        self.assertEqual(actual, expected)
        self.assertEqual(self.summary.repository_relative(actual), actual)
        self.assertTrue(original["paths"][0].startswith(str(ROOT)))

    def test_external_and_embedded_absolute_paths_fail_closed(self):
        for value in ["/Users/another/file", "/tmp/file", "-l /opt/library", "path=/var/data", "error:/opt/file",
                      "C:\\data\\file", "file:///tmp/file", str(ROOT) + "-other/file"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.summary.repository_relative({"nested": [value]})
        with self.assertRaises(ValueError):
            self.summary.repository_relative({"/tmp/key": "value"})
        self.summary.assert_no_absolute_paths("valid units / all units; load 1/5/15; https://example.test")

    def test_absolute_path_guard_runs_before_either_output_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            markdown = Path(directory) / "result.md"
            output.write_text("preserved-json")
            markdown.write_text("preserved-markdown")
            with patch.object(self.summary, "OUT_JSON", output), patch.object(self.summary, "OUT_MD", markdown), \
                    patch.object(self.summary, "build", return_value={"path": "/tmp/leak"}):
                with self.assertRaises(ValueError):
                    self.summary.main()
            self.assertEqual(output.read_text(), "preserved-json")
            self.assertEqual(markdown.read_text(), "preserved-markdown")

    def test_partial_ratio_excludes_root_and_does_not_trust_eligibility(self):
        units = [{"label": "root", "verified_prepared": False, "reason_codes": ["timeout"]},
                 {"label": "fragment-a", "verified_prepared": True},
                 {"label": "fragment-b", "verified_prepared": False, "reported_eligible": True}]
        result = {"repository": "test", "entrypoint_key": "main", "preparation_outcome": {
            "status": "partial", "unit_outcomes": units, "expected_units": 3, "incomplete_evidence": False}}
        analysis = self.summary.partial_analysis({"item": result})
        self.assertEqual(analysis["median"], 0.5)
        self.assertEqual(analysis["root_not_prepared"], 1)
        result["preparation_outcome"]["expected_units"] = 4
        with self.assertRaises(ValueError):
            self.summary.partial_analysis({"item": result})

    def test_capture_metadata_keeps_total_and_last_attempt_separate(self):
        record = {"schema": "zkfdo-instance-capture-v1", "status": "captured",
                  "compile": {"elapsed_seconds": 100, "success": True},
                  "compile_seconds": 132, "compile_attempts": 2, "instances": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            path.write_text(json.dumps(record))
            actual = self.summary.capture_compile_metadata(path)
            self.assertEqual(actual["compile_seconds"], 132)
            self.assertEqual(actual["compile"]["elapsed_seconds"], 100)
            record["instances"] = [{"compile_seconds": 999}]
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                self.summary.capture_compile_metadata(path)


if __name__ == "__main__":
    unittest.main()
