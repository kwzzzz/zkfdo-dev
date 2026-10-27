#!/usr/bin/env python3
"""Synthetic B source staging tests; no preserved request or candidate is opened."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import n6_j3_b_requests as requests  # noqa: E402
from n6_j1_requests import RequestError  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BSourceStagingTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "pinned-project"
        self.split = self.root / "pinned-split"
        self.entrypoint = self.project / "circuits" / "main.circom"
        self.wrapper = self.split / "wrappers" / "target.circom"
        self.entrypoint.parent.mkdir(parents=True)
        self.wrapper.parent.mkdir(parents=True)
        self.entrypoint.write_text('pragma circom 2.1.0;\ninclude "helper.circom";\n')
        (self.entrypoint.parent / "helper.circom").write_text("template Helper() {}\n")
        self.wrapper.write_text("pragma circom 2.1.0;\ncomponent main = Helper();\n")
        (self.project / "ignored.txt").write_text("not Circom source\n")
        self.candidate = self.root / "synthetic-placeholder.bin"
        self.candidate.write_bytes(b"synthetic placeholder")
        self.revision = "abcdef120000000000000000"
        self.staging = self.root / "external-staging"
        self.request_root = self.root / "new-requests"
        w_spec = {"source_snapshots": [{"id": "w", "path": str(self.project)}],
                  "targets": [{"target_id": "whole", "source_snapshot_id": "w",
                               "entrypoint_relative": "circuits/main.circom",
                               "entrypoint_sha256": digest(self.entrypoint)}]}
        s_spec = {"source_snapshots": [{"id": "s", "path": str(self.split)}],
                  "targets": [{"target_id": "split", "source_snapshot_id": "s",
                               "entrypoint_relative": "wrappers/target.circom",
                               "entrypoint_sha256": digest(self.wrapper),
                               "preflight_compile_command": [
                                   "circom", "{entrypoint}", "-l", "{workspace}",
                                   "-l", str(self.project)]}]}
        self.w_spec = self.root / "whole-spec.json"
        self.s_spec = self.root / "split-spec.json"
        self.w_spec.write_text(json.dumps(w_spec))
        self.s_spec.write_text(json.dumps(s_spec))
        self.inventory = {"status": "verified", "candidate_count": 1,
                          "counts": {"mem20": {"S": 1}}, "rows": [{
                              "identifier": self.revision, "unit_id": "synthetic-unit",
                              "seed": 1, "method": "S", "attempt_index": 0,
                              "candidate_index": 0, "completion_offset_seconds": 1,
                              "target_index": 0, "target_id": "split",
                              "candidate_path": str(self.candidate),
                              "candidate_sha256": digest(self.candidate),
                              "whole_spec": str(self.w_spec.relative_to(self.root)),
                              "whole_spec_sha256": digest(self.w_spec),
                              "split_spec": str(self.s_spec.relative_to(self.root)),
                              "split_spec_sha256": digest(self.s_spec),
                          }]}
        self.queue = {"units": [{"unit_id": "synthetic-unit",
                                 "identifier": self.revision}]}

    def rows(self, staging: Path | None) -> list[dict]:
        return requests.planned_rows(self.root, self.inventory, self.queue,
                                     self.request_root, "mem20", staging)

    def test_staging_keeps_sources_and_library_order_with_narrow_root(self) -> None:
        legacy = self.rows(None)[0]
        self.assertNotIn("original_entrypoint", legacy)
        self.assertEqual(legacy["entrypoint"], str(self.entrypoint.resolve()))
        self.assertFalse(self.staging.exists())

        staged = self.rows(self.staging)[0]
        stage_root = Path(staged["source_root"])
        key = hashlib.sha256((str(self.project.resolve()) + "\0" +
                              str(self.split.resolve())).encode("utf-8")).hexdigest()[:16]
        self.assertEqual(stage_root, self.staging.resolve() / self.revision / key)
        self.assertEqual(Path(staged["entrypoint"]),
                         stage_root / "project/circuits/main.circom")
        self.assertEqual(Path(staged["component_wrapper"]),
                         stage_root / "wrapper/wrappers/target.circom")
        self.assertEqual(staged["original_entrypoint"], legacy["entrypoint"])
        self.assertEqual(staged["original_component_wrapper"],
                         legacy["component_wrapper"])
        self.assertEqual(staged["library_paths"], legacy["library_paths"])
        self.assertEqual(digest(Path(staged["entrypoint"])), digest(self.entrypoint))
        self.assertEqual(digest(Path(staged["component_wrapper"])), digest(self.wrapper))
        self.assertTrue((stage_root / "project/circuits/helper.circom").is_file())
        self.assertFalse((stage_root / "project/ignored.txt").exists())
        self.assertEqual(len(requests.circom_files(stage_root)), 3)
        manifest = stage_root / "source-staging.json"
        before = digest(manifest)
        self.assertEqual(self.rows(self.staging)[0], staged)
        self.assertEqual(digest(manifest), before)

    def test_staging_refuses_changed_source_or_partial_output(self) -> None:
        staged = self.rows(self.staging)[0]
        Path(staged["entrypoint"]).write_text("changed staged source\n")
        with self.assertRaisesRegex(RequestError,
                                    "staged source SHA-256 differs"):
            self.rows(self.staging)

    def test_staging_refuses_to_nest_inside_request_output(self) -> None:
        with self.assertRaisesRegex(RequestError,
                                    "staging overlaps"):
            self.rows(self.request_root / "source-staging")


if __name__ == "__main__":
    unittest.main()
