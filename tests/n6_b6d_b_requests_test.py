"""Focused B6d path-rewrite and E1–E4 release-gate tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_b6d_b_requests as subject  # noqa: E402


class B6dRequestTests(unittest.TestCase):
    def test_absolute_clone_include_only_is_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clone = root / "clone"
            project = root / "unit/project"
            original = root / "source/target.circom"
            staged = root / "unit/preparation/target.circom"
            target = clone / "lib/needed.circom"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"template Needed() {}\n")
            clone = clone.resolve()
            target = target.resolve()
            external = root / "external.circom"
            raw = (b'pragma circom 2.1.0;\ninclude "' +
                   str(target).encode() + b'"; // keep comment\n' +
                   b'include "relative.circom";\ninclude "' +
                   str(external).encode() + b'";\ncomponent main = Needed();\n')
            output, edits = subject.rewrite_includes(
                raw, clone=clone, project=project,
                original=original, staged=staged)
            self.assertEqual(len(edits), 1)
            self.assertEqual(edits[0]["scope"], "wrapper")
            self.assertEqual(edits[0]["line"], 2)
            self.assertEqual(output, raw.replace(str(target).encode(),
                                                 str(project / "lib/needed.circom").encode()))

    def test_failed_gate_creates_no_request_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = root / "gate.json"
            manifest = root / "manifest.json"
            r1cs = root / "r1cs.json"
            for path in (manifest, r1cs):
                path.write_text("{}\n")
            gate.write_text(json.dumps({"schema_version": 1, "status": "failed"}))
            with patch.multiple(subject, MANIFEST=manifest, R1CS_EVIDENCE=r1cs,
                                PLAN_OUT=root / "plan.json",
                                INDEX_OUT=root / "index.json",
                                INDEX_V22_OUT=root / "index-v22.json",
                                REQUEST_ROOT=root / "requests"):
                with self.assertRaisesRegex(ValueError, "gate has not passed"):
                    subject.final_index(gate)
            self.assertFalse((root / "plan.json").exists())
            self.assertFalse((root / "index.json").exists())
            self.assertFalse((root / "requests").exists())

    def test_failed_b_e2_audit_blocks_forged_passing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            r1cs = root / "r1cs.json"
            a_audit = root / "a.json"
            b_audit = root / "b.json"
            gate = root / "gate.json"
            manifest.write_text("{}\n")
            r1cs.write_text("{}\n")
            a_audit.write_text(json.dumps({"a": {"status": "pass",
                                                   "request_count": 2926,
                                                   "revision_count": 26}}))
            b_audit.write_text(json.dumps({"b": {"e1": {"status": "pass"},
                                                   "e2": {"status": "fail"},
                                                   "request_count": 107,
                                                   "pair_count": 17},
                                           "staging_manifest_sha256":
                                           subject.sha256_file(manifest),
                                           "original_b_index_sha256": "dummy"}))
            gate.write_text(json.dumps({
                "schema_version": 1, "status": "passed", "request_count": 107,
                "pair_count": 17, "e1": "passed", "e2": "passed",
                "e3": "passed", "e4": "passed",
                "source_index_sha256": "dummy",
                "unit_manifest_sha256": subject.sha256_file(manifest),
                "r1cs_equivalence_sha256": subject.sha256_file(r1cs),
                "a_closure_audit": str(a_audit),
                "a_closure_audit_sha256": subject.sha256_file(a_audit),
                "b_closure_audit": str(b_audit),
                "b_closure_audit_sha256": subject.sha256_file(b_audit),
            }))
            with patch.multiple(subject, MANIFEST=manifest, R1CS_EVIDENCE=r1cs,
                                A_CLOSURE=a_audit, B_CLOSURE=b_audit,
                                SOURCE_INDEX_SHA="dummy",
                                PLAN_OUT=root / "plan.json",
                                INDEX_OUT=root / "index.json",
                                INDEX_V22_OUT=root / "index-v22.json",
                                REQUEST_ROOT=root / "requests"):
                with self.assertRaisesRegex(ValueError,
                                            "closure audits have not passed"):
                    subject.final_index(gate)
            self.assertFalse((root / "index.json").exists())
            self.assertFalse((root / "requests").exists())


if __name__ == "__main__":
    unittest.main()
