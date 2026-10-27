"""Small safety checks for the read-only A preparation evidence audit."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_b6c_a_equivalence as audit  # noqa: E402


class APreparationAuditTest(unittest.TestCase):
    def test_library_rewrite_file_uses_recorded_library_order(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            (first / "source.circom").write_text("first", encoding="utf-8")
            chosen = second / "source.circom"
            chosen.write_text("second", encoding="utf-8")
            record = {"template": "T", "file": "lib1/source.circom"}
            request = {"source_root": str(root), "library_paths": [str(first), str(second)]}
            self.assertEqual(audit.rewrite_identity(record, request),
                             ("T", "lib1/source.circom", audit.sha256_file(chosen)))

    def test_audit_arm_rejects_result_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request_path = root / "request.json"
            request_path.write_text(json.dumps({"source_root": str(root), "library_paths": []}))
            result_path = root / "result.json"
            result_path.write_text(json.dumps({"preparation": {"status": "ok"},
                                               "component": {"rewritten_statements": []}}))
            index_path = root / "index.json"
            index_path.write_text(json.dumps({"request_count": 1, "requests": [{
                "request": str(request_path), "request_sha256": audit.sha256_file(request_path),
                "revision_id": "r"}]}))
            state_path = root / "state.json"
            state_path.write_text(json.dumps({"status": "completed",
                "request_index_sha256": audit.sha256_file(index_path),
                "requests": {"0": {"revision_id": "r", "status": "completed",
                                   "result_path": str(result_path), "result_sha256": "0" * 64}}}))
            with self.assertRaisesRegex(ValueError, "result SHA-256 mismatch"):
                audit.audit_arm(index_path, state_path)

    def test_circom_count_stays_inside_named_root(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            named = base / "named"
            named.mkdir()
            (named / "one.circom").write_text("template T() {}")
            (base / "outside.circom").write_text("template U() {}")
            self.assertEqual(audit.circom_count(named), 1)


if __name__ == "__main__":
    unittest.main()
