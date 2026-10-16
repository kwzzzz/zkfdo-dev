"""Queue policy tests with no zkFuzz or circuit execution."""

import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/run_n6_b_queue.py"
SPEC = importlib.util.spec_from_file_location("n6_b_queue_test_module", MODULE)
queue = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = queue
SPEC.loader.exec_module(queue)


class N6BQueueTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_state_rejects_changed_queue(self):
        queue_path = self.root / "queue.json"
        queue_path.write_text(json.dumps({"units": [{"unit_id": "u"}]}))
        value = {"_path": str(queue_path), "units": [{"unit_id": "u"}]}
        state_path = self.root / "state.json"
        queue.load_or_create_state(value, state_path)
        queue_path.write_text(json.dumps({"units": [{"unit_id": "changed"}]}))
        with self.assertRaises(ValueError):
            queue.load_or_create_state(value, state_path)

    def test_preflight_cleanup_deletes_only_recorded_compile_outputs(self):
        generated = self.root / "compile/0000/artifacts/out.r1cs"
        generated.parent.mkdir(parents=True)
        generated.write_bytes(b"compiled")
        source = self.root / "snapshots/whole/source.r1cs"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"preserve")
        result = queue.cleanup_preflight_artifacts(self.root)
        self.assertEqual(result["deleted_count"], 1)
        self.assertFalse(generated.exists())
        self.assertTrue(source.exists())
        plan = json.loads((self.root / "artifact-deletion-plan.json").read_text())
        self.assertEqual(plan["artifacts"][0]["sha256"], hashlib.sha256(b"compiled").hexdigest())

    def test_w_preflight_failure_does_not_suppress_split(self):
        unit = {"unit_id": "u", "resource_class": "normal"}
        state = {"actual_start_order": [], "units": {
            "u": {"status": "pending", "W": "pending", "S": "pending"}}}
        called = []

        def fake_method(_unit, method, _output, _preflights, _root):
            called.append(method)
            return {"status": "preflight_failed" if method == "W" else "completed"}

        with patch.object(queue, "run_method", side_effect=fake_method):
            result = queue.run_unit(unit, self.root, self.root / "state.json", state, {})
        self.assertEqual(called, ["W", "S"])
        self.assertEqual(result["W"]["status"], "preflight_failed")
        self.assertEqual(result["S"]["status"], "completed")
        self.assertEqual(state["actual_start_order"][0]["unit_id"], "u")

    def test_busy_million_plus_skips_to_next_normal_unit(self):
        pending = [{"unit_id": "large", "resource_class": "million_plus"},
                   {"unit_id": "normal", "resource_class": "normal"}]
        selected = queue.pop_next_runnable(pending, million_plus_running=True)
        self.assertEqual(selected["unit_id"], "normal")
        self.assertEqual([row["unit_id"] for row in pending], ["large"])
        self.assertIsNone(queue.pop_next_runnable(pending, million_plus_running=True))

    def test_execute_gate_requires_all_preflights(self):
        queue_path = self.root / "queue.json"
        queue_path.write_text("{}")
        fixed = {"_path": str(queue_path), "units": [
            {"unit_id": "u", "whole_spec": "w", "split_spec": "s"}]}
        (self.root / "preflight-all.json").write_text(json.dumps({
            "queue_sha256": queue.sha256(queue_path), "status": "running", "results": {}}))
        with self.assertRaisesRegex(ValueError, "all 60 preflights"):
            queue.load_completed_preflights(fixed, self.root)

    def test_preflight_reuse_allows_only_campaign_and_seed_changes(self):
        first = self.root / "first.json"
        second = self.root / "second.json"
        base = {"campaign_id": "a", "initial_seed": 1, "method": "split",
                "targets": [{"target_id": "t"}]}
        first.write_text(json.dumps(base))
        second.write_text(json.dumps({**base, "campaign_id": "b", "initial_seed": 2}))
        queue.assert_preflight_equivalent(first, second)
        second.write_text(json.dumps({**base, "campaign_id": "b", "initial_seed": 2,
                                      "targets": [{"target_id": "changed"}]}))
        with self.assertRaisesRegex(ValueError, "outside campaign_id/initial_seed"):
            queue.assert_preflight_equivalent(first, second)

    def test_exact_preflight_reuse_requires_identical_spec_hash(self):
        source_spec = self.root / "source.json"
        destination_spec = self.root / "destination.json"
        source_spec.write_text('{"same":true}\n')
        destination_spec.write_text('{"same":false}\n')
        unit = {"unit_id": "u", "whole_spec": str(destination_spec),
                "whole_spec_sha256": queue.sha256(destination_spec)}
        source_row = {"spec": str(source_spec), "spec_sha256": queue.sha256(source_spec),
                      "preflight": "absent.json"}
        with patch.object(queue, "ROOT", Path("/")):
            with self.assertRaisesRegex(ValueError, "source and destination specs differ"):
                queue.materialize_reused_preflight(
                    unit, "W", self.root / "output", source_row, exact_spec=True)

    def test_fixed_queue_has_60_preflights_and_nonblocking_large_rule(self):
        path = ROOT / "runs/n6-2026-10-06/queue-v7.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(data["concurrency"], 3)
        self.assertEqual(data["preflight_spec_count"], 60)
        self.assertEqual(len(data["units"]), 30)
        self.assertEqual(data["unit_order"],
                         "seed order, then frozen stage1 order; W then S within unit")
        self.assertIn("next normal unit", data["large_unit_rule"])
        self.assertEqual(sum(row["resource_class"] == "million_plus" for row in data["units"]), 6)
        self.assertTrue(all("specs-v7" in row["whole_spec"] and
                            "specs-v7" in row["split_spec"] for row in data["units"]))
        self.assertEqual(data["preflight_execution"]["execute_methods"], ["S"])
        self.assertEqual(data["preflight_execution"]["seed_reuse_methods"], [])
        self.assertEqual(data["preflight_execution"]["exact_reuse"]["method"], "W")

    def test_v7_preserves_w_and_appends_original_split_libraries(self):
        v6 = json.loads((ROOT / "runs/n6-2026-10-06/queue-v6.json").read_text())
        v7 = json.loads((ROOT / "runs/n6-2026-10-06/queue-v7.json").read_text())
        self.assertEqual(len(v6["units"]), len(v7["units"]))
        for old_unit, new_unit in zip(v6["units"], v7["units"], strict=True):
            old_w = ROOT / old_unit["whole_spec"]
            new_w = ROOT / new_unit["whole_spec"]
            self.assertEqual(old_w.read_bytes(), new_w.read_bytes())
            old_s = json.loads((ROOT / old_unit["split_spec"]).read_text())
            new_s = json.loads((ROOT / new_unit["split_spec"]).read_text())
            self.assertEqual(len(old_s["targets"]), len(new_s["targets"]))
            for old_target, new_target in zip(old_s["targets"], new_s["targets"], strict=True):
                old_command_libraries = [old_target["command"][index + 1]
                                         for index, value in enumerate(old_target["command"])
                                         if value == "-l"]
                new_command_libraries = [new_target["command"][index + 1]
                                         for index, value in enumerate(new_target["command"])
                                         if value == "-l"]
                original = new_target["appended_original_library_paths"]
                self.assertEqual(new_command_libraries[:len(old_command_libraries)],
                                 old_command_libraries)
                self.assertEqual(new_command_libraries[len(old_command_libraries):], original)
                compile_libraries = [new_target["preflight_compile_command"][index + 1]
                                     for index, value in enumerate(
                                         new_target["preflight_compile_command"])
                                     if value == "-l"]
                self.assertEqual(compile_libraries, new_command_libraries)


if __name__ == "__main__":
    unittest.main()
