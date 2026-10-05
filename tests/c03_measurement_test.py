"""Prevent denominator loss, unpinned baseline compilation and manual fallback."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import measure_c03_corpus as meter


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo/clone"
        self.repo.mkdir(parents=True)
        self.run = self.root / "run"
        self.run.mkdir()
        self.row = {"full_name": "owner/repo", "clone_path": str(self.repo), "commit_sha": "abc"}
        self.source = self.repo / "main.circom"
        self.source.write_text("pragma circom 2.2.3; template T(){signal input x;signal output y;y<==x+1;} component main=T();")
        self.entry = meter.original_entry(self.row, {"path": "main.circom", "sha256": meter.legacy.digest(self.source)})
        for name, value in (("ROOT", self.root), ("RUN", self.run)):
            mock = patch.object(meter, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_same_path_in_distinct_repositories_is_not_merged(self):
        self.assertNotEqual(meter.identifier(self.row, self.entry),
                            meter.identifier(dict(self.row, full_name="other/repo"), self.entry))

    def test_config_keys_not_template_names_determine_identity(self):
        a = meter.generated_entry({"circomkit_path": "circomkit.json", "config_key": "n1", "template": "T"})
        b = meter.generated_entry({"circomkit_path": "circomkit.json", "config_key": "n2", "template": "T"})
        self.assertNotEqual(meter.identifier(self.row, a), meter.identifier(self.row, b))

    def test_missing_source_is_not_zero_constraint_success(self):
        self.source.unlink()
        with patch.object(meter.legacy, "run_command") as run:
            value = meter.compile_entry(self.row, self.entry, self.run, [])
        run.assert_not_called()
        self.assertEqual(value["compile"]["failure_type"], "entrypoint_source_missing")
        self.assertIsNone(value["compile"]["constraints"])

    def test_changed_baseline_does_not_run_compiler(self):
        self.source.write_text("changed source")
        with patch.object(meter.legacy, "run_command") as run:
            value = meter.compile_entry(self.row, self.entry, self.run, [])
        run.assert_not_called()
        self.assertEqual(value["compile"]["failure_type"], "baseline_source_hash_mismatch")

    def test_external_source_is_not_accepted(self):
        outside = self.root / "external.circom"
        outside.write_text("not inside the pinned checkout")
        value = meter.compile_entry(self.row, dict(self.entry, path=str(outside)), self.run, [])
        self.assertEqual(value["compile"]["failure_type"], "entrypoint_outside_pinned_project")

    def test_after_inventory_retains_missing_old_entry(self):
        self.source.unlink()
        listing = type("Listing", (), {"returncode": 0, "stdout": b""})()
        with patch.object(meter.subprocess, "run", return_value=listing), \
             patch.object(meter.config, "generate_config_entrypoints", return_value={"entries": [], "failures": []}):
            value = meter.inventory_one(self.row, "after", {"entries": [self.entry]})
        self.assertEqual([row["key"] for row in value["entries"]], [self.entry["key"]])

    def test_setup_requires_every_baseline_even_if_last_one_missing(self):
        census = self.run / "census.json"
        census.write_text(json.dumps({"repositories": [self.row]}))
        inventory = {"repositories": [{"full_name": self.row["full_name"], "entries": [self.entry]}]}
        with patch.object(meter, "make_inventory", return_value=inventory), \
             patch.object(meter, "ensure_tools"), patch.object(meter, "setup_one") as setup:
            with self.assertRaisesRegex(ValueError, "setup_requires_complete_baseline"):
                meter.execute(census, "setup")
        setup.assert_not_called()

    def test_generated_main_is_outside_checkout_but_within_structural_project(self):
        (self.repo / "circomkit.json").write_text('{"dirCircuits":".","circuits":"circuits.json"}')
        (self.repo / "circuits.json").write_text('{"normal":{"file":"main","template":"T","params":[],"pubs":["x"]}}')
        before = meter.inventory_one(self.row, "before")
        listing = type("Listing", (), {"returncode": 0, "stdout": b""})()
        with patch.object(meter.subprocess, "run", return_value=listing):
            after = meter.inventory_one(self.row, "after", before)
        a, b = before["entries"][0], after["entries"][0]
        self.assertEqual(a["expected_sha256"], b["expected_sha256"])
        self.assertFalse(Path(a["path"]).is_relative_to(self.repo))
        self.assertTrue(Path(a["path"]).is_relative_to(self.repo.parent))


if __name__ == "__main__":
    unittest.main()
