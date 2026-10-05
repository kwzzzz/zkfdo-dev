"""Metadata regression tests for the all-repository C-03 clean restart."""

import copy
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "c03_recovery", Path(__file__).resolve().parents[1] / "scripts/recover_c03_checkouts_v3.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryMetadataTests(unittest.TestCase):
    def setUp(self):
        self.original = {"schema_version": 2, "classification": {"historical": True},
                         "repositories": [
                             {"canonical_full_name": "Example/Project", "commit_sha": "a" * 40,
                              "clone_path": "old/clone", "classification": {"label": "unknown"},
                              "exposure": {"unknown": True}, "main_eligible": False},
                             {"canonical_full_name": "Other/Project", "commit_sha": "b" * 40,
                              "clone_path": "other/clone", "team_curated": True}]}
        self.records = [{"canonical_full_name": row["canonical_full_name"],
                         "commit_sha": row["commit_sha"], "status": "ok", "clean_worktree": True,
                         "clone_path": "new/" + str(index)}
                        for index, row in enumerate(self.original["repositories"])]

    def derive(self):
        return recovery.derive_census(self.original, self.records, {"sha256": "source"},
                                      {"sha256": "records"})

    def test_every_original_field_survives_except_checkout_location(self):
        before = copy.deepcopy(self.original)
        derived = self.derive()
        self.assertEqual(self.original, before)
        self.assertEqual(derived["classification"], before["classification"])
        for old, new in zip(before["repositories"], derived["repositories"]):
            self.assertNotEqual(new["clone_path"], old["clone_path"])
            new["clone_path"] = old["clone_path"]
            self.assertEqual(new, old)

    def test_failure_prevents_success_only_subset_freeze(self):
        self.records[0]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "incomplete_recovery"):
            self.derive()

    def test_missing_or_duplicate_repository_prevents_freeze(self):
        self.records[1] = copy.deepcopy(self.records[0])
        with self.assertRaisesRegex(ValueError, "exact_original_denominator"):
            self.derive()

    def test_changed_commit_prevents_freeze(self):
        self.records[0]["commit_sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "commit_changed"):
            self.derive()

    def test_dirty_worktree_prevents_freeze(self):
        self.records[0]["clean_worktree"] = False
        with self.assertRaisesRegex(ValueError, "incomplete_recovery"):
            self.derive()


if __name__ == "__main__":
    unittest.main()
