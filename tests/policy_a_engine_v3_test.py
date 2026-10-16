"""Deterministic v3 runner tests; no zkFuzz invocation."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/run_policy_a_engine_v3.py"
SPEC = importlib.util.spec_from_file_location("policy_a_v3_test_module", MODULE)
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


class PolicyAEngineV3Test(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def target(self, index, snapshot):
        source = self.root / snapshot
        source.mkdir()
        entrypoint = source / "target.circom"
        entrypoint.write_text("template T() {}\ncomponent main = T();\n")
        return source, {
            "target_id": f"target-{index}", "source_snapshot_id": snapshot,
            "entrypoint_relative": "target.circom",
            "entrypoint_sha256": engine.v1.sha256_file(entrypoint),
            "command": [sys.executable, "-c", "print('No Counter Example Found')",
                        "{entrypoint}", "{workspace}", "{seed}"],
        }

    def make_spec(self, count=3, method="split"):
        pairs = [self.target(index, f"snapshot-{index}") for index in range(count)]
        return {
            "schema_version": 1, "campaign_id": "v3-test", "method": method,
            "total_budget_seconds": 1, "attempt_cap_seconds": 1 if method == "whole" else 0.1,
            "initial_seed": 2026100601, "seed_rule": "increment_per_pass", "concurrency": 1,
            "memory_cap_bytes": 10 * engine.GIB, "require_pinned_command_tools": False,
            "require_save_output": False, "zkfuzz_output": "stderr_report",
            "source_snapshots": [{"id": f"snapshot-{index}", "path": str(source),
                                  "tree_sha256": engine.v1.tree_sha256(source),
                                  "candidate_globs": ["**/zkfdo_report_counterexample.json"],
                                  "expected_baseline_candidates": 0}
                                 for index, (source, _) in enumerate(pairs)],
            "targets": [target for _, target in pairs], "seed_transport": {"kind": "placeholder"},
            "pinned_files": [],
        }

    def test_general_target_count_and_distinct_snapshots(self):
        spec = self.make_spec(3)
        engine.validate_spec_v3(spec)
        spec["targets"][1]["source_snapshot_id"] = spec["targets"][0]["source_snapshot_id"]
        with self.assertRaises(engine.v1.SpecError):
            engine.validate_spec_v3(spec)

    def test_validation_covers_targets_after_the_first_legacy_chunk(self):
        spec = self.make_spec(22)
        spec["targets"][21]["entrypoint_relative"] = "/unsafe/target.circom"
        with self.assertRaises(engine.v1.SpecError):
            engine.validate_spec_v3(spec)

    def test_whole_clone_has_no_copy_fallback(self):
        source = self.root / "source"
        source.mkdir()
        (source / "a").write_text("x")
        destination = self.root / "destination"
        with patch.object(engine.subprocess, "run", return_value=type("R", (), {"returncode": 1,
                                                                                "stderr": "unsupported"})()):
            with self.assertRaises(engine.v1.InfrastructureError):
                engine.apfs_clone_tree(source, destination)
        self.assertFalse(destination.exists())

    def test_memory_cap_kills_and_reaps_process_group(self):
        self.assertEqual(engine.RSS_POLL_SECONDS, 1.0)
        attempt = self.root / "attempt"
        attempt.mkdir()
        engine._ACTIVE_MEMORY_CAP_BYTES = 24 * 1024 * 1024
        start = engine.time.monotonic_ns()
        with patch.object(engine, "process_group_rss_bytes", return_value=80 * 1024 * 1024):
            result = engine.spawn_and_measure_v3(
                [sys.executable, "-c", "import time; x=bytearray(80*1024*1024); time.sleep(5)"],
                attempt, start + int(5e9), start, lambda: False)
        self.assertEqual(result["outcome"], "memory_cap")
        self.assertTrue(result["reaped"])
        self.assertTrue(result["process_group_empty"])
        self.assertGreater(result["resource"]["aggregate_process_tree_peak_memory_bytes"],
                           engine._ACTIVE_MEMORY_CAP_BYTES)
        self.assertEqual(result["resource"]["aggregate_process_tree_peak_memory_sampling"],
                         "ps process-group RSS sum every 1.0s")

    def test_process_tree_monitor_failure_is_fail_closed(self):
        attempt = self.root / "monitor-failure-attempt"
        attempt.mkdir()
        engine._ACTIVE_MEMORY_CAP_BYTES = 10 * engine.GIB
        start = engine.time.monotonic_ns()
        with patch.object(engine, "process_group_rss_bytes", return_value=None):
            result = engine.spawn_and_measure_v3(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                attempt, start + int(5e9), start, lambda: False)
        self.assertEqual(result["outcome"], "resource_monitor_failure")
        self.assertTrue(result["resource_monitor_failed"])
        self.assertTrue(result["process_group_kill_sent"])
        self.assertTrue(result["reaped"])
        self.assertTrue(result["process_group_empty"])
        self.assertEqual(
            result["resource"]["aggregate_process_tree_peak_memory_unknown_reason"],
            "one or more ps samples failed",
        )

    def test_workspace_is_deleted_only_after_result_metadata_is_available(self):
        attempt = self.root / "attempts" / "000000"
        workspace = attempt / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "large.tmp").write_bytes(b"x" * 32)
        row = {"outcome": "no_candidate"}
        engine.atomic_write_v3(attempt / "result.json", row)
        self.assertFalse(workspace.exists())
        persisted = json.loads((attempt / "result.json").read_text())
        self.assertEqual(persisted["workspace_cleanup"]["bytes"], 32)
        self.assertEqual(persisted["workspace_cleanup"]["status"], "deleted")

    def test_coverage_counts_attempt_start_not_completion(self):
        ledger_path = self.root / "ledger.json"
        base = {"ledger": {"attempts": [
                    {"target_id": "before", "process_started": True,
                     "process_start_offset_seconds": 599, "completion_offset_seconds": 700,
                     "resource": {"aggregate_process_tree_peak_memory_bytes": 12}},
                    {"target_id": "after", "process_started": True,
                     "process_start_offset_seconds": 601, "completion_offset_seconds": 602,
                     "resource": {"aggregate_process_tree_peak_memory_bytes": 20}}],
                "campaign_wall_seconds": 700}, "ledger_path": ledger_path,
                "ledger_sha256": "old"}
        spec = {"method": "split", "memory_cap_bytes": 100,
                "targets": [{"target_id": "before"}, {"target_id": "after"}]}
        with patch.object(engine, "_ORIGINAL_RUN_CAMPAIGN", return_value=base):
            result = engine.run_campaign_v3(spec, "spec", {}, self.root, self.root / "out")
        self.assertEqual(result["ledger"]["coverage_checkpoints"]["600"]["attempted_targets"], 1)
        self.assertEqual(result["ledger"]["aggregate_process_tree_peak_memory_bytes"], 20)


if __name__ == "__main__":
    unittest.main()
