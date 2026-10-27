#!/usr/bin/env python3
"""Synthetic path-only checks for B6b's pre-J hint-copy gate."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_b6b_static_preflight as preflight  # noqa: E402


class StaticPreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.staging = self.root / "staging"
        self.source = self.staging / "revision" / "1234567890abcdef"
        self.source.mkdir(parents=True)
        self.entrypoint = self.source / "project" / "main.circom"
        self.wrapper = self.source / "wrapper" / "S.circom"
        for path in (self.entrypoint, self.wrapper):
            path.parent.mkdir(parents=True)
            path.write_text("pragma circom 2.1.0;\n")
        self.library = self.root / "library"
        self.library.mkdir()
        self.workspace = self.root / "output" / "workspaces"
        self.instance = self.root / "output" / "instances"
        self.cache = self.root / "cache"
        self.request_path = self.root / "requests" / "one.json"
        self.request_path.parent.mkdir()
        self.request = {"source_root": str(self.source),
                        "entrypoint": str(self.entrypoint),
                        "component_wrapper": str(self.wrapper),
                        "library_paths": [str(self.library)],
                        "candidate": {"path": "unopened-value-file"}}
        self.write_request()

    def write_request(self) -> None:
        self.request_path.write_text(json.dumps(self.request) + "\n")
        index = {"request_count": 1, "requests": [{
            "queue_order": 0, "revision_id": "revision", "request": str(self.request_path),
            "request_sha256": preflight.digest(self.request_path)}]}
        self.index = self.root / "index.json"
        self.index.write_text(json.dumps(index) + "\n")

    def inspect(self, **kwargs):
        return preflight.inspect_index(
            self.index, staging_root=self.staging,
            workspace_root=kwargs.get("workspace", self.workspace),
            instance_root=self.instance, cache_root=self.cache,
            max_files=kwargs.get("max_files", 2000),
            max_bytes=kwargs.get("max_bytes", 64 * 1024 * 1024))

    def test_passes_both_engines_and_reports_only_path_metadata(self) -> None:
        report = self.inspect()
        self.assertTrue(report["all_passed"])
        self.assertEqual(report["per_engine"]["v1"]["by_revision"]["revision"]["passed"], 1)
        self.assertEqual(report["per_engine"]["v2.2"]["by_revision"]["revision"]["passed"], 1)
        self.assertEqual(report["row_checks"][0]["circom_files"], 2)
        self.assertNotIn("candidate", json.dumps(report))
        self.assertNotIn("unopened-value-file", json.dumps(report))

    def test_rejects_workspace_inside_source_root(self) -> None:
        report = self.inspect(workspace=self.source / "hint-workspace")
        self.assertFalse(report["all_passed"])
        self.assertIn("workspace_overlaps_source_root", report["row_checks"][0]["reasons"])

    def test_rejects_library_containing_workspace(self) -> None:
        self.request["library_paths"] = [str(self.root)]
        self.write_request()
        report = self.inspect()
        self.assertIn("workspace_overlaps_library", report["row_checks"][0]["reasons"])

    def test_rejects_symlink_in_staging_tree(self) -> None:
        (self.source / "shortcut").symlink_to(self.root)
        report = self.inspect()
        self.assertIn("source_tree_symlink", report["row_checks"][0]["reasons"])

    def test_rejects_file_count_and_byte_caps(self) -> None:
        self.assertIn("circom_file_cap_exceeded",
                      self.inspect(max_files=1)["row_checks"][0]["reasons"])
        self.assertIn("circom_byte_cap_exceeded",
                      self.inspect(max_bytes=1)["row_checks"][0]["reasons"])

    def test_rejects_request_hash_change(self) -> None:
        self.request_path.write_text("{}\n")
        report = self.inspect()
        self.assertIn("request_file_missing_or_hash_changed",
                      report["row_checks"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
