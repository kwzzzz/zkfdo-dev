import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/n6_make_targets_a.py"


def load_module():
    spec = importlib.util.spec_from_file_location("n6_make_targets_a", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class N6TargetsATest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        if cls.module.main() != 0:
            raise AssertionError("target generator failed")
        cls.data = json.loads((ROOT / "docs/n6_targets_a_2026-10-07.json").read_text())

    def test_full_denominator_and_partition(self):
        self.assertEqual(len(self.data["items"]), 70)
        self.assertEqual(sum(bool(row["fix_commits"]) for row in self.data["items"]), 50)
        self.assertEqual(sum(not row["fix_commits"] for row in self.data["items"]), 20)
        self.assertEqual(sum(self.data["counts"][key] for key in
                             ["A-D", "A-Q-stage1", "A-Q-stage2", "vulnerable_only"]), 70)

    def test_development_precedence_and_original_mode(self):
        projects = {name.lower() for name in self.data["rules"]["development_precedence"]}
        for row in self.data["items"]:
            if row["project"].lower() in projects:
                self.assertEqual(row["bucket"], "A-D")
            self.assertIsNotNone(row["original_entrypoint"])
            self.assertIn(row["original_entrypoint_kind"],
                          {"project_main", "project_test", "original_is_direct", "zkbugs_thin"})

    def test_setup_is_any_success_and_exact_repository(self):
        for row in self.data["items"]:
            statuses = {item["status"] for item in row["setup_observations"]}
            self.assertEqual(row["setup_success"], "success" in statuses)
            for item in row["setup_observations"]:
                if item.get("repository"):
                    self.assertEqual(item["repository"].lower(), row["project_match_key"])

    def test_shared_fix_groups_require_scoped_leave_one_out(self):
        rows = [row for row in self.data["items"] if row["leave_one_out"]]
        self.assertEqual(len(rows), self.data["counts"]["leave_one_out_items"])
        self.assertGreater(len(rows), 0)
        for row in rows:
            scope = row["leave_one_out"]["planned_diff_scope"]
            self.assertTrue(scope["path"])
            self.assertTrue(scope["line"])

    def test_shared_document_has_no_absolute_user_path_or_execution_result(self):
        text = json.dumps(self.data)
        self.assertNotIn("/Users/", text)
        self.assertEqual(self.data["zkfuzz_invocations"], 0)
        self.assertTrue(self.data["selection_before_preparation"])


if __name__ == "__main__":
    unittest.main()
