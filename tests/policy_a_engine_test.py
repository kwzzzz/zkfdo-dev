"""Regression tests for the A-02 real campaign state machine using fake children only."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/run_policy_a_engine.py"
SPEC = importlib.util.spec_from_file_location("run_policy_a_engine", MODULE_PATH)
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


class PolicyAEngineTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "clean-tree"
        (self.source / "src").mkdir(parents=True)
        (self.source / "src" / "core.circom").write_text("template Core() {}\n")
        (self.source / "zkfdo-targets").mkdir()
        self.script = MODULE_PATH.resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def add_entrypoints(self, count):
        rows = []
        for index in range(count):
            relative = f"zkfdo-targets/target-{index:02d}.circom"
            path = self.source / relative
            path.write_text(
                'include "../src/core.circom";\ncomponent main = Core();\n'
            )
            rows.append((f"target-{index:02d}", relative, engine.sha256_file(path)))
        return rows

    def fake_command(self, mode, candidate=False, extra=None):
        command = [
            sys.executable,
            str(self.script),
            "_fake-child",
            "--mode",
            mode,
            "--seed",
            "{seed}",
            "--workspace-placeholder",
            "{workspace}",
            "--entrypoint-placeholder",
            "{entrypoint}",
        ]
        if candidate:
            command.extend(
                ["--candidate", "{workspace}/opaque_counterexample.json"]
            )
        if extra:
            command.extend(extra)
        return command

    def make_spec(self, method="whole", mode="no_candidate", candidate=False):
        count = 1 if method == "whole" else 21
        entrypoints = self.add_entrypoints(count)
        targets = [
            {
                "target_id": identifier,
                "source_snapshot_id": "clean",
                "entrypoint_relative": relative,
                "entrypoint_sha256": digest,
                "command": self.fake_command(mode, candidate),
            }
            for identifier, relative, digest in entrypoints
        ]
        return {
            "schema_version": 1,
            "campaign_id": "test-campaign",
            "method": method,
            "total_budget_seconds": 10,
            "attempt_cap_seconds": 1,
            "initial_seed": 2026092931,
            "seed_rule": "increment_per_pass",
            "concurrency": 1,
            "require_pinned_command_tools": False,
            "require_save_output": False,
            "source_snapshots": [
                {
                    "id": "clean",
                    "path": str(self.source),
                    "tree_sha256": engine.tree_sha256(self.source),
                    "candidate_globs": ["**/*_counterexample.json"],
                    "expected_baseline_candidates": 0,
                }
            ],
            "targets": targets,
            "seed_transport": {"kind": "placeholder"},
            "pinned_files": [],
        }

    @staticmethod
    def spec_digest(spec):
        return engine.hashlib.sha256(engine.json_bytes(spec)).hexdigest()

    def test_fake_self_test_covers_candidate_timeout_spawn_cancel_and_nonzero(self):
        result = engine.self_test(self.root / "self-test")
        summary = result["summary"]
        self.assertTrue(all(summary["checks"].values()))
        candidate_ledger = json.loads(
            (self.root / "self-test" / summary["cases"]["candidate_duplicate"]["ledger"])
            .read_text()
        )
        self.assertEqual([row["outcome"] for row in candidate_ledger["attempts"]], ["candidate"] * 3)
        self.assertEqual(
            [row["seed"] for row in candidate_ledger["attempts"]],
            [2026092931, 2026092932, 2026092933],
        )
        self.assertTrue(
            all(row["engine_reported_execution_seconds"] == [0.0125] for row in candidate_ledger["attempts"])
        )
        self.assertIsNone(candidate_ledger["attempts"][0]["candidates"][0]["duplicate_of"])
        self.assertIsNotNone(candidate_ledger["attempts"][1]["candidates"][0]["duplicate_of"])
        self.assertNotIn("opaque_fake_candidate", json.dumps(candidate_ledger))

        timeout = json.loads(
            (self.root / "self-test" / summary["cases"]["timeout"]["ledger"])
            .read_text()
        )
        attempt = timeout["attempts"][0]
        self.assertEqual(attempt["outcome"], "timeout")
        self.assertTrue(attempt["reaped"])
        self.assertTrue(attempt["process_group_empty"])
        self.assertTrue(attempt["process_group_kill_sent"])
        self.assertFalse((self.root / "self-test" / "descendant-survived").exists())

        cancel = json.loads(
            (self.root / "self-test" / summary["cases"]["cancel"]["ledger"])
            .read_text()
        )
        self.assertEqual(cancel["termination_reason"], "cancelled")
        self.assertEqual(cancel["status"], "interrupted")

    def test_split_cycles_fixed_order_and_increments_seed_only_per_pass(self):
        spec = self.make_spec(method="split")
        original_hash = engine.tree_sha256(self.source)
        result = engine.run_campaign(
            spec,
            self.spec_digest(spec),
            {"clean": self.source},
            self.root,
            self.root / "split-run",
            max_attempts=23,
        )
        ledger = result["ledger"]
        expected_ids = [target["target_id"] for target in spec["targets"]]
        self.assertEqual(
            [row["target_id"] for row in ledger["attempts"]],
            expected_ids + expected_ids[:2],
        )
        self.assertEqual(
            [row["seed"] for row in ledger["attempts"]],
            [2026092931] * 21 + [2026092932] * 2,
        )
        self.assertEqual(len(ledger["targets"]), 21)
        self.assertTrue(all(row["status"] == "started" for row in ledger["targets"]))
        self.assertEqual(engine.tree_sha256(self.source), original_hash)
        self.assertEqual(engine.candidate_inventory(self.source, ["**/*_counterexample.json"]), {})

    def test_preflight_binds_clean_tree_plan_fingerprints_and_target_order(self):
        spec = self.make_spec(method="split")
        core = self.source / "src" / "core.circom"
        plan_targets = []
        for target in spec["targets"]:
            entrypoint = self.source / target["entrypoint_relative"]
            fingerprints = [
                {"path": str(core), "sha256": engine.sha256_file(core)},
                {"path": str(entrypoint), "sha256": engine.sha256_file(entrypoint)},
            ]
            plan_targets.append(
                {
                    "target_id": target["target_id"],
                    "definition": {
                        "project_root": str(self.source),
                        "entrypoint": str(entrypoint),
                    },
                    "source_fingerprints": fingerprints,
                    "snapshot_fingerprints": [
                        {"path": f"/prepared/sources/{Path(row['path']).relative_to(self.source)}", "sha256": row["sha256"]}
                        for row in fingerprints
                    ],
                }
            )
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps({"targets": plan_targets}))
        dependency = self.root / "dependency-tree"
        dependency.mkdir()
        (dependency / "library.circom").write_text("template Library() {}\n")
        spec["pinned_files"] = [
            {
                "label": "plan",
                "path": str(plan_path),
                "sha256": engine.sha256_file(plan_path),
            },
            {
                "label": "python",
                "path": str(Path(sys.executable).resolve()),
                "sha256": engine.sha256_file(Path(sys.executable).resolve()),
            },
        ]
        spec["pinned_trees"] = [
            {
                "label": "external-dependency",
                "path": str(dependency),
                "tree_sha256": engine.tree_sha256(dependency),
            }
        ]
        spec["require_pinned_command_tools"] = True
        spec_path = self.root / "spec.json"
        spec_path.write_text(json.dumps(spec, indent=2))
        result = engine.preflight(spec_path, self.root / "preflight")
        ledger = result["ledger"]
        self.assertEqual(ledger["plan_validation"]["status"], "verified")
        self.assertEqual(ledger["plan_validation"]["target_count"], 21)
        self.assertEqual(len(ledger["source_snapshots"]), 1)
        self.assertEqual(ledger["pinned_trees"][0]["label"], "external-dependency")
        self.assertEqual(ledger["source_snapshots"][0]["baseline_candidate_count"], 0)
        self.assertEqual(len(ledger["compile"]), 21)
        self.assertTrue(all(row["status"] == "not_requested" for row in ledger["compile"]))
        self.assertEqual(ledger["status"], "passed_compile_not_requested")

        loaded, spec_sha = engine.load_spec(spec_path)
        snapshots, root = engine.read_preflight(
            loaded, spec_sha, result["ledger_path"]
        )
        self.assertEqual(root, (self.root / "preflight").resolve())
        self.assertEqual(engine.tree_sha256(snapshots["clean"]), spec["source_snapshots"][0]["tree_sha256"])

    def test_preflight_compile_exit_zero_succeeds_and_failure_blocks_run(self):
        good = self.make_spec()
        compile_command = lambda mode: [
            sys.executable,
            str(self.script),
            "_fake-child",
            "--mode",
            mode,
            "--workspace-placeholder",
            "{workspace}",
            "--entrypoint-placeholder",
            "{entrypoint}",
        ]
        good["targets"][0]["preflight_compile_command"] = compile_command("no_candidate")
        good_path = self.root / "good-spec.json"
        good_path.write_text(json.dumps(good))
        passed = engine.preflight(good_path, self.root / "good-preflight")
        self.assertEqual(passed["ledger"]["status"], "passed")
        self.assertEqual(passed["ledger"]["compile"][0]["status"], "succeeded")

        bad = self.make_spec()
        bad["targets"][0]["preflight_compile_command"] = compile_command("nonzero")
        bad_path = self.root / "bad-spec.json"
        bad_path.write_text(json.dumps(bad))
        failed = engine.preflight(bad_path, self.root / "bad-preflight")
        self.assertEqual(failed["ledger"]["status"], "failed")
        self.assertEqual(failed["ledger"]["compile"][0]["status"], "failed")
        loaded, digest = engine.load_spec(bad_path)
        with self.assertRaises(engine.SpecError):
            engine.read_preflight(loaded, digest, failed["ledger_path"])

    def test_infrastructure_persistence_failure_is_fatal_but_engine_errors_continue(self):
        spec = self.make_spec(mode="nonzero")
        nonzero = engine.run_campaign(
            spec,
            self.spec_digest(spec),
            {"clean": self.source},
            self.root,
            self.root / "nonzero",
            max_attempts=2,
        )["ledger"]
        self.assertEqual([row["outcome"] for row in nonzero["attempts"]], ["engine_nonzero"] * 2)
        self.assertIsNone(nonzero["fatal_error"])

        original = engine.atomic_write
        failed = False

        def fail_first_result(path, value):
            nonlocal failed
            if path.name == "result.json" and not failed:
                failed = True
                raise OSError("synthetic persistence failure")
            return original(path, value)

        engine.atomic_write = fail_first_result
        try:
            failed_ledger = engine.run_campaign(
                spec,
                self.spec_digest(spec),
                {"clean": self.source},
                self.root,
                self.root / "persistence-failure",
            )["ledger"]
        finally:
            engine.atomic_write = original
        self.assertEqual(failed_ledger["termination_reason"], "infrastructure_failure")
        self.assertEqual(failed_ledger["status"], "incomplete")
        self.assertIn("synthetic persistence failure", failed_ledger["fatal_error"])
        self.assertEqual(len(failed_ledger["targets"]), 1)

    def test_spawn_error_is_one_recorded_fatal_attempt(self):
        spec = self.make_spec()
        spec["targets"][0]["command"][0] = str(self.root / "missing-engine")
        ledger = engine.run_campaign(
            spec,
            self.spec_digest(spec),
            {"clean": self.source},
            self.root,
            self.root / "spawn-error",
        )["ledger"]
        self.assertEqual(len(ledger["attempts"]), 1)
        self.assertEqual(ledger["attempts"][0]["outcome"], "spawn_error")
        self.assertEqual(ledger["termination_reason"], "infrastructure_failure")
        self.assertEqual(ledger["status"], "incomplete")

    def test_spec_rejects_dirty_baseline_wrong_denominator_and_unsafe_entrypoint(self):
        whole = self.make_spec()
        wrong = json.loads(json.dumps(whole))
        wrong["method"] = "split"
        with self.assertRaises(engine.SpecError):
            engine.validate_spec(wrong)

        unsafe = json.loads(json.dumps(whole))
        unsafe["targets"][0]["entrypoint_relative"] = "../escape.circom"
        with self.assertRaises(engine.SpecError):
            engine.validate_spec(unsafe)

        (self.source / "old_counterexample.json").write_text("{}")
        dirty = json.loads(json.dumps(whole))
        dirty["source_snapshots"][0]["tree_sha256"] = engine.tree_sha256(self.source)
        dirty_path = self.root / "dirty-spec.json"
        dirty_path.write_text(json.dumps(dirty))
        with self.assertRaises(engine.SpecError):
            engine.preflight(dirty_path, self.root / "dirty-preflight")


if __name__ == "__main__":
    unittest.main()
