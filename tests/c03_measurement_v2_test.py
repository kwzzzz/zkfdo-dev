"""Setup extension must be fixed before installation and cannot hide changes."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import measure_c03_corpus_v2 as meter


class ExtensionLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.run = self.root / "run"
        self.run.mkdir()
        for name in ("census.json", "measurement-lock.json", "entrypoints-before.json"):
            (self.run / name).write_text("{}")
        self.census = self.run / "census.json"
        patcher = patch.object(meter.base, "RUN", self.run)
        patcher.start()
        self.addCleanup(patcher.stop)
        def reference(path):
            return {"path": str(path), "sha256": meter.base.legacy.digest(path)}
        patcher = patch.object(meter.base, "ref", side_effect=reference)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_existing_lock_is_not_rewritten(self):
        meter.extension_lock(self.census)
        path = self.run / "measurement-extension-lock.v2.json"
        before = path.read_bytes()
        meter.extension_lock(self.census)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(json.loads(before)["setup_started"])

    def test_changed_census_cannot_reuse_lock(self):
        meter.extension_lock(self.census)
        self.census.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, "identity_changed"):
            meter.extension_lock(self.census)

    def test_late_lock_after_setup_is_rejected(self):
        (self.run / "setups").mkdir()
        with self.assertRaisesRegex(ValueError, "fixed_before_setup"):
            meter.extension_lock(self.census)


if __name__ == "__main__":
    unittest.main()
