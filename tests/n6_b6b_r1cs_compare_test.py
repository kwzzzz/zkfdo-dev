#!/usr/bin/env python3
"""Synthetic R1CS comparison checks; no compiler or preserved B data is opened."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import n6_b6b_r1cs_compare as comparison  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class B6bR1CSComparisonTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original = self.root / "pinned-project"
        self.staging = self.root / "source-staging"
        self.stage = self.staging / "revision" / "0123456789abcdef"
        self.entry = self.original / "main.circom"
        self.wrapper = self.original / "snapshot" / "target.circom"
        self.staged_entry = self.stage / "project" / "main.circom"
        self.staged_wrapper = self.stage / "wrapper" / "target.circom"
        for path in (self.entry, self.wrapper, self.staged_entry, self.staged_wrapper):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.entry.write_text("component main = Test();\n")
        self.wrapper.write_text("component main = Test();\n")
        self.staged_entry.write_bytes(self.entry.read_bytes())
        self.staged_wrapper.write_bytes(self.wrapper.read_bytes())
        self.library = self.root / "library"
        self.library.mkdir()
        self.plan_path = self.root / "request-index-pending.json"
        self.index_path = self.root / "request-index.json"
        planned_rows = []
        index_rows = []
        for order in range(2):
            request = str(self.root / f"request-{order}.json")
            planned_rows.append({"request": request, "revision_id": "revision",
                                 "queue_order": order, "source_root": str(self.stage),
                                 "original_component_wrapper": str(self.wrapper),
                                 "component_wrapper": str(self.staged_wrapper),
                                 "component_wrapper_sha256": digest(self.wrapper),
                                 "original_entrypoint": str(self.entry),
                                 "entrypoint": str(self.staged_entry),
                                 "entrypoint_sha256": digest(self.entry),
                                 "library_paths": [str(self.library)]})
            index_rows.append({"request": request, "revision_id": "revision",
                               "queue_order": order, "preparation_failure": None,
                               "original_component_wrapper": str(self.wrapper),
                               "component_wrapper_sha256": digest(self.wrapper),
                               "entrypoint_sha256": digest(self.entry)})
        self.plan_path.write_text(json.dumps({
            "status": "awaiting_base_input", "request_count": 2,
            "requests": planned_rows,
        }))
        self.index_path.write_text(json.dumps({
            "status": "verified", "request_count": 2,
            "plan_index": str(self.plan_path),
            "plan_index_sha256": digest(self.plan_path), "requests": index_rows,
        }))

    def test_two_requests_map_to_one_pinned_source_pair(self) -> None:
        path, pairs = comparison.pairs_from_index(
            self.index_path, self.staging, expected_requests=2, expected_pairs=1)
        self.assertEqual(path, self.plan_path.resolve())
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["queue_orders"], [0, 1])
        self.assertEqual(pairs[0]["original_root"], str(self.original.resolve()))
        self.assertEqual(pairs[0]["wrapper_source_sha256"], digest(self.wrapper))

    def test_changed_staged_source_fails_before_compilation(self) -> None:
        self.staged_wrapper.write_text("changed staged source\n")
        with self.assertRaisesRegex(ValueError, "original/staged source hash differs"):
            comparison.pairs_from_index(
                self.index_path, self.staging, expected_requests=2, expected_pairs=1)

    def test_component_command_matches_fixed_engine_flags(self) -> None:
        command = comparison.component_command(
            self.wrapper, self.root / "output", self.original,
            [str(self.library)], self.root / "circom")
        self.assertEqual(command, [str(self.root / "circom"), str(self.wrapper),
                                   "--r1cs", "--sym", "--prime", "bn128",
                                   "-o", str(self.root / "output"), "-l", str(self.original),
                                   "-l", str(self.library), "--wasm", "--O0"])

    def test_compile_hashes_mock_artifact_and_refuses_overwrite(self) -> None:
        output = self.root / "cache" / "one"
        seen = []

        def fake_compiler(command, **kwargs):
            seen.append((command, kwargs["timeout"]))
            (output / "target.r1cs").write_bytes(b"synthetic R1CS artifact")
            return Mock(returncode=0)

        with patch.object(comparison.subprocess, "run", side_effect=fake_compiler), \
                patch.object(comparison, "MIN_FREE_BYTES", 1):
            result = comparison.compile_component(
                self.wrapper, self.original, [str(self.library)], output,
                circom=self.root / "circom")
        self.assertEqual(result["r1cs_sha256"], digest(output / "target.r1cs"))
        self.assertEqual(seen[0][1], comparison.TOOL_TIMEOUT_SECONDS)
        with self.assertRaisesRegex(ValueError, "refuse to overwrite"):
            comparison.compile_component(
                self.wrapper, self.original, [str(self.library)], output,
                circom=self.root / "circom")


if __name__ == "__main__":
    unittest.main()
