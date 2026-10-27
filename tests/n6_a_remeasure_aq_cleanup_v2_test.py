#!/usr/bin/env python3
"""Synthetic cleanup safety and durable-record tests; no real A/B trees used."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_a_remeasure_aq_cleanup_v2 as cleanup  # noqa: E402


class CleanupTests(unittest.TestCase):
    def setUp(self):
        parent = "/private/tmp" if Path("/private/tmp").is_dir() else "/tmp"
        self.temporary = tempfile.TemporaryDirectory(prefix="aq-cleanup-v2-", dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.boundary = self.root / "aq-external"
        self.boundary.mkdir()
        self.target = self.boundary / "v2.2" / "workspaces" / "aq-test" / "000001"
        self.target.mkdir(parents=True)
        self.records = self.root / "records"
        self.binding = {"engine": "v2.2", "queue_order": 1,
                        "result_path": str(self.root / "result.json"),
                        "result_sha256": "a" * 64, "metrics_sha256": "b" * 64}

    def write(self, relative, content=b"evidence"):
        path = self.target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def run_cleanup(self, retain=True):
        return cleanup.cleanup_tree(self.target, self.boundary, self.records,
                                    self.binding, retain)

    def test_retains_exact_evidence_and_unlinks_links_without_following(self):
        retained = [self.write("attempt-0001/raw/site-001/input.json"),
                    self.write("attempt-0001/raw/site-001/honest.wtns"),
                    self.write("attempt-0001/raw/site-001/predicate-01/class-o0.wtns"),
                    self.write("attempt-0001/raw/site-001/predicate-01/exclusion-0.smt2")]
        self.write("attempt-0001/raw/site-001/not-evidence.json", b"x" * 8192)
        self.write("attempt-0001/raw/site-001/predicate-01/exclusion-2.smt2")
        self.write("attempt-0001/result.json")
        outside = self.root / "untouched"
        outside.mkdir()
        payload = outside / "evidence"
        payload.write_bytes(b"do not delete or read through links")
        (self.target / "directory-link").symlink_to(outside, target_is_directory=True)
        (self.target / "file-link").symlink_to(payload)
        (self.target / "broken-link").symlink_to(outside / "missing")
        before = cleanup.scan_stats(self.target)
        receipt = self.run_cleanup()
        self.assertEqual(receipt["status"], "retained_evidence")
        self.assertEqual(receipt["deleted_files"]["link_count"], 3)
        self.assertEqual(receipt["retained_evidence"]["file_count"], 4)
        self.assertEqual(receipt["file_count"], 7)
        self.assertEqual(receipt["du_bytes"], before["du_bytes"])
        self.assertTrue(all(path.read_bytes() == b"evidence" for path in retained))
        self.assertEqual(payload.read_bytes(), b"do not delete or read through links")
        self.assertFalse((self.target / "directory-link").is_symlink())
        self.assertGreaterEqual(receipt["freed_du_bytes"], 8192)
        names = sorted(str(path.relative_to(self.target)) for path in retained)
        expected = hashlib.sha256(b"".join(name.encode() + b"\0" for name in names)).hexdigest()
        self.assertEqual(receipt["retained_evidence"]["file_list_sha256"], expected)
        for label in ("before", "after"):
            record_path = Path(receipt[f"{label}_path"])
            self.assertEqual(hashlib.sha256(record_path.read_bytes()).hexdigest(),
                             receipt[f"{label}_sha256"])
            self.assertEqual(json.loads(record_path.read_text())["binding"], self.binding)

    def test_full_delete_and_repeat_are_separately_audited(self):
        self.write("attempt-0001/raw/site-001/input.json")
        first = self.run_cleanup(False)
        before_bytes = Path(first["before_path"]).read_bytes()
        second = self.run_cleanup(False)
        self.assertEqual(first["status"], "deleted")
        self.assertEqual(second["status"], "absent")
        self.assertFalse(self.target.exists())
        self.assertNotEqual(first["before_path"], second["before_path"])
        self.assertEqual(Path(first["before_path"]).read_bytes(), before_bytes)
        self.assertEqual(second["freed_du_bytes"], 0)

    def test_attempt_root_preserves_same_exact_v22_evidence(self):
        self.target = self.target / "attempt-0001"
        self.target.mkdir()
        retained = self.write("raw/site-001/input.json")
        self.write("raw/site-001/predicate-01/found.wtns")
        self.write("raw/site-001/predicate-01/not-evidence.wtns")
        self.write("result.json")
        self.assertEqual(cleanup.scan_stats(self.target)["retained_evidence"]["file_count"], 2)
        receipt = self.run_cleanup()
        self.assertEqual(receipt["retained_evidence"]["file_count"], 2)
        self.assertEqual(receipt["deleted_files"]["file_count"], 2)
        self.assertEqual(retained.read_bytes(), b"evidence")

    def test_recovery_after_partial_deletion_keeps_all_before_records(self):
        self.write("a")
        self.write("b")
        self.write("c")
        unlink = Path.unlink
        calls = []

        def interrupt(path, *args, **kwargs):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("synthetic interruption")
            return unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", interrupt):
            with self.assertRaisesRegex(OSError, "synthetic interruption"):
                self.run_cleanup(False)
        before_paths = list(self.records.glob("*-before.json"))
        self.assertEqual(len(before_paths), 1)
        initial = before_paths[0].read_bytes()
        receipt = self.run_cleanup(False)
        self.assertEqual(receipt["deleted_files"]["file_count"], 2)
        self.assertEqual(len(list(self.records.glob("*-before.json"))), 2)
        self.assertEqual(before_paths[0].read_bytes(), initial)
        self.assertFalse(self.target.exists())

    def test_refuses_linked_target_ancestor_boundary_and_record_directory(self):
        real = self.root / "outside"
        real.mkdir()
        secret = real / "secret"
        secret.write_text("keep")
        linked = self.boundary / "linked"
        linked.symlink_to(real, target_is_directory=True)
        for target, boundary, records in (
                (linked, self.boundary, self.records),
                (linked / "child", self.boundary, self.records),
                (linked / "child", linked, self.records)):
            with self.subTest(target=target, boundary=boundary):
                with self.assertRaises(cleanup.CleanupError):
                    cleanup.cleanup_tree(target, boundary, records, self.binding, False)
        self.records.symlink_to(real, target_is_directory=True)
        with self.assertRaises(cleanup.CleanupError):
            self.run_cleanup(False)
        self.assertEqual(secret.read_text(), "keep")

    def test_refuses_boundary_itself_escape_and_special_files(self):
        for target in (self.boundary, self.root, self.boundary / ".." / "outside"):
            with self.subTest(target=target):
                with self.assertRaises(cleanup.CleanupError):
                    cleanup.cleanup_tree(target, self.boundary, self.records, self.binding, False)
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.target / "pipe")
            with self.assertRaises(cleanup.CleanupError):
                self.run_cleanup(False)

    def test_mutation_after_before_record_stops_before_deletion(self):
        path = self.write("artifact")
        original = cleanup._write_new

        def mutate(record, value):
            digest = original(record, value)
            if value["kind"] == "n6_a_aq_cleanup_before_delete":
                path.write_bytes(b"changed since inventory")
            return digest

        with mock.patch.object(cleanup, "_write_new", mutate):
            with self.assertRaisesRegex(cleanup.CleanupError, "changed after"):
                self.run_cleanup(False)
        self.assertEqual(path.read_bytes(), b"changed since inventory")
        self.assertEqual(len(list(self.records.glob("*-before.json"))), 1)
        self.assertFalse(list(self.records.glob("*-after.json")))


if __name__ == "__main__":
    unittest.main()
