"""M-01 population and guardrail tests; no compiler or fuzzer is invoked."""

import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "m01", Path(__file__).resolve().parents[1] / "scripts/measure_m01_discovery.py")
m01 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m01)

SUMMARY_SPEC = importlib.util.spec_from_file_location(
    "m01_summary", Path(__file__).resolve().parents[1] / "scripts/summarize_m01_discovery.py")
summary = importlib.util.module_from_spec(SUMMARY_SPEC)
SUMMARY_SPEC.loader.exec_module(summary)


class PopulationTests(unittest.TestCase):
    def test_population_is_every_e01_compile_success(self):
        population = m01.population()
        expected = []
        for path in m01.E01_RUN.glob("measurements/*/after/result.json"):
            record = json.loads(path.read_text())
            if record["compile"]["status"] == "success":
                expected.append(path.parent.parent.name)
        self.assertEqual({row["identifier"] for row in population}, set(expected))
        self.assertEqual(len(population), 125)
        self.assertEqual(sum(row["constraints"] >= 100_000 for row in population), 49)

    def test_inputs_resolve_only_to_e01_clones(self):
        for item in m01.population():
            _, _, root, entrypoint = m01.validate_item(item)
            self.assertTrue(root.resolve().is_relative_to((m01.E01_RUN / "repositories").resolve()))
            self.assertNotIn("runs/f01-2026-10-03", str(entrypoint))

    def test_pinned_hashes_are_exact(self):
        self.assertEqual(m01.legacy.digest(m01.F01_BINARY), m01.EXPECTED_ZKFDO)
        self.assertEqual(m01.legacy.digest(m01.CIRCOM), m01.EXPECTED_CIRCOM)


class AggregationGuardTests(unittest.TestCase):
    def test_discovery_and_capture_failures_remain_explicit(self):
        discovery_failure = {
            "m01_component_status": "failed",
            "discovery": {"status": "timeout", "failure_type": "timeout"},
            "preparation": {"failure_types": ["discovery_timeout"]},
        }
        self.assertEqual(summary.capture_category(discovery_failure), "discovery_timeout")
        self.assertIn("discovery:timeout", summary.remaining(discovery_failure))
        incomplete = {
            "m01_component_status": "partial",
            "discovery": {"status": "success", "unsupported": []},
            "instance_discovery": {"selected": "compiler", "compiler_complete": False,
                                   "capture_status": "partial"},
            "preparation": {"failure_types": []},
        }
        self.assertEqual(summary.capture_category(incomplete), "compiler_incomplete")
        self.assertIn("instance_capture:partial", summary.remaining(incomplete))

    def test_success_has_no_invented_limitation(self):
        result = {
            "m01_component_status": "success",
            "discovery": {"status": "success", "unsupported": []},
            "instance_discovery": {"selected": "compiler", "compiler_complete": True},
            "preparation": {"failure_types": []},
        }
        self.assertEqual(summary.remaining(result), [])


if __name__ == "__main__":
    unittest.main()
