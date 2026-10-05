"""A tooling recovery cannot change the selected corpus or its prior labels."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import measure_c03_corpus_v3 as meter


class RecoveryMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.original = {"repositories": [{"full_name": "owner/repo", "commit_sha": "a" * 40,
            "clone_path": "original/clone", "classification": {"classification": "production"},
            "main_eligible": True, "entrypoints": [{"path": "main.circom", "sha256": "b" * 64}]}]}
        self.recovered = copy.deepcopy(self.original)
        self.recovered["repositories"][0]["clone_path"] = "recovery/clone"

    def test_only_checkout_location_can_change(self):
        self.assertIn("owner/repo", meter.identical_selection(self.original, self.recovered))

    def test_commit_change_rejected(self):
        self.recovered["repositories"][0]["commit_sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "metadata_changed"):
            meter.identical_selection(self.original, self.recovered)

    def test_preparation_result_cannot_change_nature_label(self):
        self.recovered["repositories"][0]["classification"]["classification"] = "library"
        with self.assertRaisesRegex(ValueError, "metadata_changed"):
            meter.identical_selection(self.original, self.recovered)

    def test_recovery_cannot_drop_or_duplicate_repository(self):
        for rows in ([], self.recovered["repositories"] * 2):
            with self.assertRaisesRegex(ValueError, "set_changed"):
                meter.identical_selection(self.original, {"repositories": rows})

    def test_reused_baseline_bytes_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "original.json"
            target = Path(directory) / "copy/result.json"
            source.write_bytes(b'{"status":"failure"}\n')
            meter.copied(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            source.write_bytes(b'{"status":"success"}\n')
            with self.assertRaisesRegex(ValueError, "identity_changed"):
                meter.copied(source, target)
            self.assertEqual(target.read_bytes(), b'{"status":"failure"}\n')


if __name__ == "__main__":
    unittest.main()
