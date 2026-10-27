#!/usr/bin/env python3
"""Synthetic, value-free checks for B6b's staged J source bindings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_b6b_j_source_bindings as staged  # noqa: E402
import run_n6_j1 as runner  # noqa: E402
from run_policy_a_engine import tree_sha256  # noqa: E402


def save(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return runner.sha256(path)


class StagedSourceBindingsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        root_patch = patch.object(runner, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

        self.revision = "abc12345" + "0" * 32
        self.w_root = self.root / "frozen" / "whole"
        self.s_root = self.root / "frozen" / "split"
        self.w_file = self.w_root / "main.circom"
        self.w_dependency = self.w_root / "dependency.circom"
        self.s_file = self.s_root / "discovery" / "S.circom"
        self.w_file.parent.mkdir(parents=True)
        self.s_file.parent.mkdir(parents=True)
        self.w_file.write_text("pragma circom 2.1.0; component main = Main();\n")
        self.w_dependency.write_text("template Dependency() {}\n")
        self.s_file.write_text("pragma circom 2.1.0; component main = Split();\n")
        w_target = {"target_id": "W", "source_snapshot_id": "W-source",
                    "entrypoint_relative": "main.circom",
                    "entrypoint_sha256": runner.sha256(self.w_file),
                    "preflight_compile_command": ["circom", "{workspace}/main.circom",
                                                  "-l", str(self.w_root)]}
        s_target = {"target_id": "S", "source_snapshot_id": "S-source",
                    "entrypoint_relative": "discovery/S.circom",
                    "entrypoint_sha256": runner.sha256(self.s_file),
                    "preflight_compile_command": ["circom", "{workspace}/discovery/S.circom",
                                                  "-l", str(self.s_root)]}
        w_spec = {"method": "whole", "targets": [w_target],
                  "source_snapshots": [{"id": "W-source", "path": str(self.w_root),
                                        "tree_sha256": tree_sha256(self.w_root)}]}
        s_spec = {"method": "split", "targets": [s_target],
                  "source_snapshots": [{"id": "S-source", "path": str(self.s_root),
                                        "tree_sha256": tree_sha256(self.s_root)}]}
        self.w_spec_path = "specs/W.json"
        self.s_spec_path = "specs/S.json"
        self.w_spec_sha = save(self.root / self.w_spec_path, w_spec)
        self.s_spec_sha = save(self.root / self.s_spec_path, s_spec)

        self.staging_root = self.root / "staging"
        key = hashlib.sha256((str(self.w_root) + "\0" + str(self.s_root)).encode(
            "utf-8")).hexdigest()[:16]
        self.source_root = self.staging_root / self.revision / key
        shutil.copytree(self.w_root, self.source_root / "project")
        shutil.copytree(self.s_root, self.source_root / "wrapper")
        self.entrypoint = self.source_root / "project" / "main.circom"
        self.wrapper = self.source_root / "wrapper" / "discovery" / "S.circom"
        copies = []
        for label, original_root, files in (("project", self.w_root,
                                             (self.w_dependency, self.w_file)),
                                            ("wrapper", self.s_root, (self.s_file,))):
            for original in files:
                copies.append({"path": str(Path(label) / original.relative_to(original_root)),
                               "source": str(original), "sha256": runner.sha256(original)})
        save(self.source_root / "source-staging.json", {
            "schema_version": 1, "revision_id": self.revision,
            "project_root": str(self.w_root), "wrapper_root": str(self.s_root),
            "files": copies})
        candidate_sha = "f" * 64
        candidate_path = str(self.root / "unopened-candidate.json")
        self.row = {"scope": "main", "revision_id": self.revision, "unit_id": "unit",
                    "seed": 1, "method": "S", "candidate_index": 0,
                    "attempt_number": 1, "candidate_sha256": candidate_sha,
                    "candidate_path": candidate_path, "target_id": "S",
                    "original_target_id": None,
                    "entrypoint_sha256": runner.sha256(self.w_file),
                    "component_wrapper_sha256": runner.sha256(self.s_file),
                    "original_entrypoint": str(self.w_file),
                    "original_component_wrapper": str(self.s_file)}
        self.inventory = {"status": "verified", "rows": [{
            "lane": "main", "identifier": self.revision, "unit_id": "unit",
            "seed": 1, "method": "S", "candidate_index": 0,
            "attempt_index": 0, "candidate_sha256": candidate_sha,
            "candidate_path": candidate_path, "target_id": "S",
            "original_target_id": None, "target_index": 0,
            "source_snapshot_id": "S-source",
            "whole_spec": self.w_spec_path, "whole_spec_sha256": self.w_spec_sha,
            "split_spec": self.s_spec_path, "split_spec_sha256": self.s_spec_sha}]}
        self.request = {"source_root": str(self.source_root),
                        "entrypoint": str(self.entrypoint),
                        "component_wrapper": str(self.wrapper),
                        "library_paths": [str(self.s_root)]}

    def check(self) -> None:
        staged.validate_staged_source_bindings([self.row], self.inventory,
                                                [self.request], self.staging_root)

    def test_accepts_exact_staged_pair_and_original_specs(self) -> None:
        self.check()

    def test_rejects_staged_wrapper_with_changed_bytes(self) -> None:
        self.wrapper.write_text("changed\n")
        with self.assertRaisesRegex(runner.RunnerError, "SHA-256"):
            self.check()

    def test_rejects_other_staged_source_with_changed_bytes(self) -> None:
        (self.source_root / "project" / "dependency.circom").write_text("changed\n")
        with self.assertRaisesRegex(runner.RunnerError, "staged Circom tree"):
            self.check()

    def test_rejects_wrong_original_binding(self) -> None:
        self.row["original_entrypoint"] = str(self.s_file)
        with self.assertRaisesRegex(runner.RunnerError, "request/spec target binding"):
            self.check()

    def test_rejects_staging_root_outside_pinned_pair(self) -> None:
        self.request["source_root"] = str(self.root / "frozen")
        with self.assertRaisesRegex(runner.RunnerError, "bounded staged pair"):
            self.check()

    def test_rejects_library_order_or_path_change(self) -> None:
        self.request["library_paths"] = [str(self.w_root)]
        with self.assertRaisesRegex(runner.RunnerError, "library path mismatch"):
            self.check()

    def test_rejects_staged_wrapper_path_substitution(self) -> None:
        alternate = self.source_root / "project" / "discovery" / "S.circom"
        alternate.parent.mkdir(parents=True)
        shutil.copyfile(self.s_file, alternate)
        self.request["component_wrapper"] = str(alternate)
        with self.assertRaisesRegex(runner.RunnerError, "staged W/S"):
            self.check()


if __name__ == "__main__":
    unittest.main()
