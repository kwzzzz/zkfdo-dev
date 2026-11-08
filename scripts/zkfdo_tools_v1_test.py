import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
import unittest
from unittest.mock import patch

import zkfdo_tools_v1 as tools


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zkfdo-tools-")
        self.root = Path(self.temp.name).resolve()
        binary = self.root / "tool"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o700)
        self.data = {"schema": "zkfdo-tools-v1", "platform": tools.platform_name(),
                     "architecture": platform.machine(), "status": "measured", "tools": {
                         "zkfuzz": {"path": str(binary), "sha256": tools.sha256(binary), "version": "test",
                                    "source_commit": None, "build_command": None}}}
        self.path = self.root / "tools.json"

    def tearDown(self):
        self.temp.cleanup()

    def save(self, data=None):
        self.path.write_text(json.dumps(self.data if data is None else data))
        return self.path

    def test_current_manifest_shape_and_binary_hash(self):
        result = tools.load_manifest(self.save(), required=("zkfuzz",))
        self.assertTrue(result["tools"]["zkfuzz"]["sha256_verified"])
        self.assertEqual(result["manifest_sha256"], tools.sha256(self.path))

    def test_changed_binary_rejected(self):
        self.save()
        Path(self.data["tools"]["zkfuzz"]["path"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "SHA256 differs"):
            tools.load_manifest(self.path)

    def test_linux_template_rejected_before_platform_check(self):
        path = tools.ROOT / "configs/tools.linux.json"
        with self.assertRaisesRegex(ValueError, "unfilled template"):
            tools.load_manifest(path)

    def test_platform_and_architecture_mismatch_rejected(self):
        for key, value in [("platform", "unsupported"), ("architecture", "unsupported")]:
            data = copy.deepcopy(self.data)
            data[key] = value
            with self.assertRaises(ValueError):
                tools.load_manifest(self.save(data))

    def test_missing_provenance_field_rejected(self):
        del self.data["tools"]["zkfuzz"]["build_command"]
        with self.assertRaisesRegex(ValueError, "provenance"):
            tools.load_manifest(self.save())

    def test_environment_path_overrides(self):
        self.save()
        with patch.dict(os.environ, {"ZKFDO_TOOLS_MANIFEST": str(self.path), "ZKFDO_RUNS": str(self.root / "elsewhere")}):
            self.assertEqual(tools.load_manifest()["manifest_path"], str(self.path))
            self.assertEqual(tools.output_path(None, "job"), self.root / "elsewhere/policy-a-v5/job")
            self.assertEqual(tools.output_path("new", "job"), self.root / "elsewhere/new")
            with self.assertRaises(ValueError):
                tools.output_path(self.root / "outside", "job")
            with self.assertRaises(ValueError):
                tools.output_path(self.root / "elsewhere", "job")


if __name__ == "__main__":
    unittest.main()
