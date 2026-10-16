#!/usr/bin/env python3
"""Small metadata fixtures for RQ-C template-to-instance bindings."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_j1_rq_c_map as mapping  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class MappingTest(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        identifier = "aq-fixture"
        project = root / "source/project"
        entrypoint = project / "circuit.circom"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("pragma circom 2.1.6;\ncomponent main = Spend();\n")
        spec_path = root / "whole.json"
        write_json(spec_path, {"method": "whole", "source_snapshots": [{"path": str(project)}],
                               "targets": [{"entrypoint_relative": "circuit.circom",
                                            "entrypoint_sha256": mapping.sha256(entrypoint)}]})
        manifest_path = root / "manifest.json"
        write_json(manifest_path, {"rows": [{"identifier": identifier,
                                              "whole_spec": str(spec_path),
                                              "whole_spec_sha256": mapping.sha256(spec_path),
                                              "entrypoint_absolute": str(entrypoint),
                                              "entrypoint_sha256": mapping.sha256(entrypoint)}]})
        preparation_path = root / "preparation.json"
        write_json(preparation_path, {"aq_stage1_units": [{"unit_id": identifier,
                                                            "item_ids": ["spend", "extract", "missing"]}]})
        targets_path = root / "targets.json"
        write_json(targets_path, {"items": [
            {"id": "spend", "location": {"Function": "Spend"}},
            {"id": "extract", "location": {"Function": "ExtractNonce / ExtractIssuer"}},
            {"id": "missing", "location": {"Function": "Absent"}},
        ]})
        capture_root = root / "captures"
        discovery = capture_root / identifier / "preparation/discovery/one"
        capture_path = discovery / "instance-capture.json"
        write_json(capture_path, {"schema": "zkfdo-instance-capture-v1",
                                  "entrypoint": str(entrypoint), "project_root": str(project),
                                  "status": "captured", "instances": [
                                      {"path": "main", "template_name": "Spend"},
                                      {"path": "main.nonce", "template_name": "ExtractNonce"},
                                  ]})
        write_json(discovery / "discovery.json", {
            "project_root": str(project),
            "instance_discovery": {"capture_status": "captured",
                                   "capture_path": str(capture_path)},
        })
        pragma_root = root / "pragma"
        write_json(pragma_root / "source-changes.json", {"changed_files": []})
        write_json(pragma_root / "r1cs-equivalence.json", {"status": "passed", "results": []})
        return manifest_path, preparation_path, targets_path, capture_root, pragma_root

    def test_main_path_and_multi_template_partial_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            result = mapping.build_map(*args)
            self.assertEqual(result["revision_count"], 1)
            items = {row["item_id"]: row for row in result["revisions"][0]["items"]}
            self.assertEqual(items["spend"]["instance_paths"], ["main"])
            self.assertEqual(items["spend"]["status"], "mapped")
            self.assertEqual(items["extract"]["status"], "partial_mapping")
            self.assertEqual(items["extract"]["missing_templates"], ["ExtractIssuer"])
            self.assertEqual(items["missing"]["status"], "unresolved_mapping")

    def test_rejects_stale_w_entrypoint_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            manifest_path = args[0]
            manifest = json.loads(manifest_path.read_text())
            manifest["rows"][0]["entrypoint_sha256"] = "0" * 64
            write_json(manifest_path, manifest)
            with self.assertRaises(mapping.MappingError):
                mapping.build_map(*args)

    def test_pragma_equivalence_requires_only_pragma_change_and_r1cs_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identifier = "aq-035-8f826c822cb8"
            original = root / identifier / "project/circuit.circom"
            corrected = root / "corrected" / identifier / "project/circuit.circom"
            original.parent.mkdir(parents=True)
            corrected.parent.mkdir(parents=True)
            original.write_text("pragma circom 2.2.2;\ncomponent main = Spend();\n")
            corrected.write_text("pragma circom 2.2.1;\ncomponent main = Spend();\n")
            report = {"changed_files": [{"original_path": str(original),
                                          "corrected_path": str(corrected),
                                          "original_sha256": mapping.sha256(original),
                                          "corrected_sha256": mapping.sha256(corrected),
                                          "changed_lines": 1}]}
            proof = {"status": "passed", "results": [{"id": identifier, "equal": True}]}
            mapping.pragma_binding(identifier, original.resolve(), corrected.resolve(),
                                   mapping.sha256(original), mapping.sha256(corrected),
                                   report, proof)
            corrected.write_text("pragma circom 2.2.1;\ncomponent main = Different();\n")
            with self.assertRaises(mapping.MappingError):
                mapping.pragma_binding(identifier, original.resolve(), corrected.resolve(),
                                       mapping.sha256(original), mapping.sha256(corrected),
                                       report, proof)


if __name__ == "__main__":
    unittest.main()
