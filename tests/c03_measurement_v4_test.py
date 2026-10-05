"""Reused inventory identity survives rebasing into the recovered checkout."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import measure_c03_corpus_v4 as meter


class RebasedInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.old = self.root / "old/repo/clone"
        self.new = self.root / "recovered/repo/clone"
        self.old.mkdir(parents=True)
        self.new.mkdir(parents=True)
        self.source = "pragma circom 2.2.3; template T(){signal input x;signal output y;y<==x*x+1;} component main=T();\n"
        for checkout in (self.old, self.new):
            (checkout / "main.circom").write_text(self.source)
        self.repo = {"full_name": "owner/repo", "canonical_full_name": "owner/repo",
                     "commit_sha": "a" * 40, "clone_path": str(self.new),
                     "classification": {"classification": "unknown"}}
        self.census = {"repositories": [self.repo]}
        self.original_entry = meter.base.original_entry(
            dict(self.repo, clone_path=str(self.old)),
            {"path": "main.circom", "sha256": meter.base.legacy.digest(self.old / "main.circom"),
             "template": "T", "main_declarations": [{"line": 1, "template": "T"}]})
        self.config_entry = {"key": "config:circuits.json:normal", "kind": "config_generated",
                             "path": str(self.new.parent / "config-generated-after/normal.circom"),
                             "source_path": "templates/normal.circom", "expected_sha256": "b" * 64,
                             "metadata": {"template": "T", "params": [2], "pubs": ["x"],
                                          "source_sha256": "c" * 64, "config_key": "normal"}}
        self.document = {"schema_version": 1, "phase": "after", "known_entrypoint_count": 2,
                         "census_ref": {"path": "frozen-census.json", "sha256": "d" * 64},
                         "repositories": [{"full_name": "owner/repo", "commit_sha": "a" * 40,
                                           "entries": [self.original_entry, self.config_entry],
                                           "config_failures": [{"failure_type": "unsupported_params"}],
                                           "inventory_failures": []}]}
        self.run = self.root / "run"
        self.run.mkdir()
        for name, value in (("ROOT", self.root), ("RUN", self.run)):
            replacement = patch.object(meter.base, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def rebased(self):
        return meter.rebase_after_inventory(self.document, self.census)

    def test_only_source_main_absolute_path_changes(self):
        original = copy.deepcopy(self.document)
        census = copy.deepcopy(self.census)
        after = self.rebased()
        entry = after["repositories"][0]["entries"][0]
        self.assertEqual(entry["path"], str(self.new / "main.circom"))
        self.assertEqual(meter.base.identifier(self.repo, entry),
                         meter.base.identifier(self.repo, self.original_entry))
        entry["path"] = self.original_entry["path"]
        self.assertEqual(after, original)
        self.assertEqual(self.document, original)
        self.assertEqual(self.census, census)

    def test_returned_nested_metadata_is_independent(self):
        after = self.rebased()
        after["repositories"][0]["entries"][0]["metadata"]["template"] = "Other"
        after["repositories"][0]["config_failures"].clear()
        self.assertEqual(self.original_entry["metadata"]["template"], "T")
        self.assertEqual(len(self.document["repositories"][0]["config_failures"]), 1)

    def test_generated_config_identity_and_path_are_preserved(self):
        after = self.rebased()
        self.assertEqual(after["repositories"][0]["entries"][1], self.config_entry)
        self.assertEqual(after["known_entrypoint_count"], 2)

    def test_missing_recovery_source_never_falls_back_to_old_checkout(self):
        (self.new / "main.circom").unlink()
        self.assertTrue((self.old / "main.circom").is_file())
        entry = self.rebased()["repositories"][0]["entries"][0]
        self.assertEqual(entry["path"], str(self.new / "main.circom"))
        with patch.object(meter.base.legacy, "run_command") as command:
            result = meter.base.compile_entry(self.repo, entry, self.run, [], phase="after")
        command.assert_not_called()
        self.assertEqual(result["compile"]["status"], "not_started")
        self.assertEqual(result["compile"]["failure_type"], "entrypoint_source_missing")
        self.assertFalse(result["compile"]["process_started"])

    def test_original_absolute_path_is_still_blocked(self):
        with patch.object(meter.base.legacy, "run_command") as command:
            result = meter.base.compile_entry(self.repo, self.original_entry, self.run, [], phase="after")
        command.assert_not_called()
        self.assertEqual(result["compile"]["failure_type"], "entrypoint_outside_pinned_project")
        self.assertFalse(result["compile"]["process_started"])

    def test_same_filename_in_two_repositories_remains_separate(self):
        second = dict(self.repo, full_name="other/repo", canonical_full_name="other/repo",
                      clone_path=str(self.root / "another/clone"))
        self.census["repositories"].append(second)
        row = copy.deepcopy(self.document["repositories"][0])
        row["full_name"] = second["full_name"]
        self.document["repositories"].append(row)
        self.document["known_entrypoint_count"] = 4
        after = self.rebased()
        a, b = [row["entries"][0] for row in after["repositories"]]
        self.assertNotEqual(a["path"], b["path"])
        self.assertNotEqual(meter.base.identifier(self.repo, a), meter.base.identifier(second, b))
        self.assertEqual(after["known_entrypoint_count"], 4)

    def test_duplicate_census_repository_is_rejected(self):
        self.census["repositories"].append(copy.deepcopy(self.repo))
        with self.assertRaises(ValueError):
            self.rebased()

    def test_duplicate_inventory_repository_is_rejected(self):
        self.document["repositories"].append(copy.deepcopy(self.document["repositories"][0]))
        with self.assertRaises(ValueError):
            self.rebased()

    def test_duplicate_entrypoint_key_is_rejected(self):
        self.document["repositories"][0]["entries"].append(copy.deepcopy(self.original_entry))
        with self.assertRaises(ValueError):
            self.rebased()

    def test_inventory_repository_missing_from_census_is_rejected(self):
        self.census["repositories"] = []
        with self.assertRaises(ValueError):
            self.rebased()


if __name__ == "__main__":
    unittest.main()
