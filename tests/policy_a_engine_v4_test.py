"""Deterministic v4 physical-memory runner tests; no zkFuzz invocation."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/run_policy_a_engine_v4.py"
SPEC = importlib.util.spec_from_file_location("policy_a_v4_test_module", MODULE)
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


class PolicyAEngineV4Test(unittest.TestCase):
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
            "schema_version": 1, "campaign_id": "v4-test", "method": method,
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
        engine.validate_spec_v4(spec)
        spec["targets"][1]["source_snapshot_id"] = spec["targets"][0]["source_snapshot_id"]
        with self.assertRaises(engine.v1.SpecError):
            engine.validate_spec_v4(spec)

    def test_validation_covers_targets_after_the_first_legacy_chunk(self):
        spec = self.make_spec(22)
        spec["targets"][21]["entrypoint_relative"] = "/unsafe/target.circom"
        with self.assertRaises(engine.v1.SpecError):
            engine.validate_spec_v4(spec)

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
        sample = {"physical_memory_bytes": 80 * 1024 * 1024,
                  "rss_bytes": 8 * 1024 * 1024,
                  "rusage_resident_bytes": 8 * 1024 * 1024,
                  "process_count": 1, "pids": []}
        result = engine.spawn_and_measure_v4(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            attempt, start + int(5e9), start, lambda: False, lambda _group: sample)
        self.assertEqual(result["outcome"], "memory_cap")
        self.assertTrue(result["reaped"])
        self.assertTrue(result["process_group_empty"])
        self.assertGreater(result["resource"]["aggregate_process_tree_peak_memory_bytes"],
                           engine._ACTIVE_MEMORY_CAP_BYTES)
        self.assertEqual(result["resource"]["aggregate_process_tree_peak_rss_bytes"],
                         8 * 1024 * 1024)
        self.assertIn("ri_phys_footprint",
                      result["resource"]["aggregate_process_tree_peak_memory_sampling"])

    def test_process_tree_monitor_failure_is_fail_closed(self):
        attempt = self.root / "monitor-failure-attempt"
        attempt.mkdir()
        engine._ACTIVE_MEMORY_CAP_BYTES = 10 * engine.GIB
        start = engine.time.monotonic_ns()
        result = engine.spawn_and_measure_v4(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            attempt, start + int(5e9), start, lambda: False, lambda _group: None)
        self.assertEqual(result["outcome"], "resource_monitor_failure")
        self.assertTrue(result["resource_monitor_failed"])
        self.assertTrue(result["process_group_kill_sent"])
        self.assertTrue(result["reaped"])
        self.assertTrue(result["process_group_empty"])
        self.assertEqual(
            result["resource"]["aggregate_process_tree_peak_memory_unknown_reason"],
            "process-group enumeration or proc_pid_rusage sample failed",
        )

    def test_process_group_memory_sums_footprint_and_rss(self):
        ps_result = type("Result", (), {
            "stdout": "101 77 8\n102 77 16\n103 88 32\n",
        })()
        readings = {101: (1000, 700), 102: (2000, 1400)}
        with patch.object(engine.subprocess, "run", return_value=ps_result):
            sample = engine.process_group_memory_bytes(
                77, pid_memory_reader=lambda pid: readings[pid])
        self.assertEqual(sample["physical_memory_bytes"], 3000)
        self.assertEqual(sample["rss_bytes"], 24 * 1024)
        self.assertEqual(sample["rusage_resident_bytes"], 2100)
        self.assertEqual(sample["process_count"], 2)

    def test_process_group_memory_read_failure_is_unknown(self):
        ps_result = type("Result", (), {"stdout": "101 77 8\n"})()
        with patch.object(engine.subprocess, "run", return_value=ps_result):
            sample = engine.process_group_memory_bytes(
                77, pid_memory_reader=lambda _pid: (_ for _ in ()).throw(OSError("denied")))
        self.assertIsNone(sample)

    def test_workspace_is_deleted_only_after_result_metadata_is_available(self):
        attempt = self.root / "attempts" / "000000"
        workspace = attempt / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "large.tmp").write_bytes(b"x" * 32)
        row = {"outcome": "no_candidate"}
        engine.atomic_write_v4(attempt / "result.json", row)
        self.assertFalse(workspace.exists())
        persisted = json.loads((attempt / "result.json").read_text())
        self.assertIsNone(persisted["workspace_cleanup"]["bytes"])
        self.assertEqual(persisted["workspace_cleanup"]["status"], "deleted")
        self.assertIn("forbids recursive", persisted["workspace_cleanup"]["inventory_reason"])

    def test_coverage_counts_attempt_start_not_completion(self):
        ledger_path = self.root / "ledger.json"
        base = {"ledger": {"attempts": [
                    {"target_id": "before", "process_started": True,
                     "process_start_offset_seconds": 599, "completion_offset_seconds": 700,
                     "resource": {"aggregate_process_tree_peak_physical_memory_bytes": 12,
                                  "aggregate_process_tree_peak_rss_bytes": 2}},
                    {"target_id": "after", "process_started": True,
                     "process_start_offset_seconds": 601, "completion_offset_seconds": 602,
                     "resource": {"aggregate_process_tree_peak_physical_memory_bytes": 20,
                                  "aggregate_process_tree_peak_rss_bytes": 3}}],
                "campaign_wall_seconds": 700}, "ledger_path": ledger_path,
                "ledger_sha256": "old"}
        spec = {"method": "split", "memory_cap_bytes": 100,
                "targets": [{"target_id": "before"}, {"target_id": "after"}]}
        with patch.object(engine, "_ORIGINAL_RUN_CAMPAIGN", return_value=base):
            result = engine.run_campaign_v4(spec, "spec", {}, self.root, self.root / "out")
        self.assertEqual(result["ledger"]["coverage_checkpoints"]["600"]["attempted_targets"], 1)
        self.assertEqual(result["ledger"]["aggregate_process_tree_peak_memory_bytes"], 20)
        self.assertEqual(result["ledger"]["aggregate_process_tree_peak_rss_bytes"], 3)


if __name__ == "__main__":
    unittest.main()
