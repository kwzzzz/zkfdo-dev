#!/usr/bin/env python3
"""Temp-only storage seeding tests; no real caches, engines, or processes used."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_a_remeasure_aq_storage_v3 as storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "protected-v2" / "store"
        self.source.mkdir(parents=True)
        (self.source / "attempts-v2.1").mkdir()
        (self.source / "attempts-v2.1/search.json").write_bytes(b'{"retained": "failed search"}')
        (self.source / "verdict.json").write_bytes(b'{"evidence": "/unchanged/absolute/path"}')
        (self.source / "empty").mkdir()
        self.boundary = self.root / "external/v3"
        self.target = self.boundary / "v2.2/stores/main/0001"
        self.records = self.root / "output/storage-seeds-v3"

    def seed(self):
        return storage.clone_storage_tree(self.source, self.target, self.boundary, self.records)

    def partial_seed(self, prefix=b'{"ret'):
        def interrupted(source, target, _expected):
            target.write_bytes(prefix)
            raise OSError("synthetic interrupted copy")
        with patch.object(storage, "_copy_file", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "synthetic interrupted"):
                self.seed()
        return self.target.with_name(self.target.name + ".seed-v3")

    def test_recursive_independent_copy_preserves_source_and_hashes(self):
        source_before = storage._inventory(self.source, hashes=True)
        receipt = self.seed()
        self.assertEqual(receipt["status"], "seeded")
        self.assertEqual(receipt["source_tree_sha256"], receipt["target_tree_sha256"])
        self.assertEqual(receipt["file_count"], 2)
        self.assertEqual(receipt["copied_bytes"], receipt["logical_bytes"])
        self.assertEqual(storage._inventory(self.source, hashes=True), source_before)
        self.assertTrue((self.target / "empty").is_dir())
        for relative in ("attempts-v2.1/search.json", "verdict.json"):
            original = self.source / relative
            copied = self.target / relative
            self.assertEqual(original.read_bytes(), copied.read_bytes())
            self.assertNotEqual(original.stat().st_ino, copied.stat().st_ino)
            self.assertEqual(copied.stat().st_nlink, 1)
        before = json.loads(Path(receipt["before_path"]).read_text())
        self.assertTrue(all(len(row["sha256"]) == 64 for row in before["inventory"]["files"]))
        for label in ("before", "after"):
            self.assertEqual(storage._hash(Path(receipt[f"{label}_path"])), receipt[f"{label}_sha256"])

    def test_resume_appends_verified_partial_prefix_without_deletion(self):
        staging = self.partial_seed()
        before_path = next(self.records.glob("*-before.json"))
        before = before_path.read_bytes()
        partial = staging / "attempts-v2.1/search.json"
        inode = partial.stat().st_ino
        receipt = self.seed()
        self.assertEqual((self.target / "attempts-v2.1/search.json").stat().st_ino, inode)
        self.assertEqual(receipt["copied_bytes"], receipt["logical_bytes"] - len(b'{"ret'))
        self.assertEqual(before_path.read_bytes(), before)
        self.assertFalse(staging.exists())

    def test_wrong_partial_prefix_is_refused_and_preserved(self):
        staging = self.partial_seed(b"wrong-prefix")
        path = staging / "attempts-v2.1/search.json"
        before = path.read_bytes()
        with self.assertRaisesRegex(storage.StorageError, "prefix differs"):
            self.seed()
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.target.exists())

    def test_changed_source_during_resume_is_refused(self):
        staging = self.partial_seed()
        (self.source / "verdict.json").write_bytes(b"changed by an outside actor")
        with self.assertRaisesRegex(storage.StorageError, "source changed"):
            self.seed()
        self.assertTrue(staging.is_dir())
        self.assertFalse(self.target.exists())

    def test_crash_after_publish_recovers_without_copying_again(self):
        write = storage._write_new

        def interrupt_after(path, value):
            if value["kind"] == "n6_a_aq_storage_seed_after":
                raise OSError("synthetic crash before completion receipt")
            return write(path, value)

        with patch.object(storage, "_write_new", side_effect=interrupt_after):
            with self.assertRaisesRegex(OSError, "synthetic crash"):
                self.seed()
        inode = self.target.stat().st_ino
        with patch.object(storage, "_copy_file", side_effect=AssertionError("must not recopy")):
            receipt = self.seed()
        self.assertEqual(receipt["copied_bytes"], 0)
        self.assertEqual(self.target.stat().st_ino, inode)

    def test_partial_before_record_is_not_published_and_resume_preserves_fragment(self):
        with patch.object(storage.json, "dump", side_effect=self.interrupted_dump("before")):
            with self.assertRaisesRegex(OSError, "interrupted record"):
                self.seed()
        self.assertEqual(list(self.records.glob("*-before.json")), [])
        self.assertFalse(self.target.exists())
        fragment = next(self.records.glob(".*.tmp"))
        partial = fragment.read_bytes()
        receipt = self.seed()
        self.assertEqual(receipt["status"], "seeded")
        self.assertEqual(fragment.read_bytes(), partial)
        json.loads(Path(receipt["before_path"]).read_bytes())

    def test_partial_after_record_recovers_without_recopying_or_removing_fragment(self):
        with patch.object(storage.json, "dump", side_effect=self.interrupted_dump("after")):
            with self.assertRaisesRegex(OSError, "interrupted record"):
                self.seed()
        self.assertEqual(list(self.records.glob("*-after.json")), [])
        inode = self.target.stat().st_ino
        fragment = next(self.records.glob(".*.tmp"))
        partial = fragment.read_bytes()
        with patch.object(storage, "_copy_file", side_effect=AssertionError("must not recopy")):
            receipt = self.seed()
        self.assertEqual(receipt["copied_bytes"], 0)
        self.assertEqual(self.target.stat().st_ino, inode)
        self.assertEqual(fragment.read_bytes(), partial)
        json.loads(Path(receipt["after_path"]).read_bytes())

    def interrupted_dump(self, suffix):
        dump = storage.json.dump

        def interrupted(value, stream, **kwargs):
            if value.get("kind", "").endswith(suffix):
                stream.write('{"interrupted": ')
                stream.flush()
                raise OSError("synthetic interrupted record")
            return dump(value, stream, **kwargs)

        return interrupted

    def test_atomic_publication_never_overwrites_existing_path(self):
        original = self.root / "existing.json"
        original.write_bytes(b"preserved")
        staged = self.root / "temporary.json"
        staged.write_bytes(b"replacement")
        with self.assertRaises(FileExistsError):
            storage._publish_new(staged, original)
        self.assertEqual(original.read_bytes(), b"preserved")
        self.assertEqual(staged.read_bytes(), b"replacement")
        linked = self.root / "existing-link"
        linked.symlink_to(original)
        with self.assertRaises(FileExistsError):
            storage._publish_new(staged, linked)
        self.assertTrue(linked.is_symlink())
        self.assertEqual(original.read_bytes(), b"preserved")

    def test_finalized_receipt_reuse_never_refreshes_engine_changes(self):
        receipt = self.seed()
        after_before = Path(receipt["after_path"]).read_bytes()
        (self.target / "verdict.json").write_bytes(b"new engine verdict")
        (self.target / "new-engine-record.json").write_bytes(b"new")
        with patch.object(storage, "_copy_file", side_effect=AssertionError("must not refresh")):
            again = self.seed()
        self.assertEqual(again["status"], "reused")
        self.assertEqual((self.target / "verdict.json").read_bytes(), b"new engine verdict")
        self.assertEqual(Path(receipt["after_path"]).read_bytes(), after_before)
        self.assertEqual((self.source / "verdict.json").read_bytes(),
                         b'{"evidence": "/unchanged/absolute/path"}')

    def test_source_symlink_and_special_file_rejected_without_following(self):
        outside = self.root / "outside"
        outside.write_bytes(b"untouched")
        link = self.source / "link"
        link.symlink_to(outside)
        with self.assertRaisesRegex(storage.StorageError, "symlink or special"):
            self.seed()
        self.assertEqual(outside.read_bytes(), b"untouched")
        link.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.source / "fifo")
            with self.assertRaisesRegex(storage.StorageError, "symlink or special"):
                self.seed()
        self.assertFalse(self.target.exists())

    def test_linked_target_ancestor_escape_and_existing_target_rejected(self):
        self.boundary.mkdir(parents=True)
        (self.boundary / "v2.2").symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.seed()
        self.assertFalse((self.source / "stores").exists())
        with self.assertRaises(storage.StorageError):
            storage.clone_storage_tree(self.source, self.root / "elsewhere", self.boundary, self.records)

    def test_partial_and_finalized_hardlinks_rejected(self):
        staging = self.partial_seed()
        partial = staging / "attempts-v2.1/search.json"
        os.link(partial, self.root / "hardlink")
        with self.assertRaisesRegex(storage.StorageError, "hardlinked target"):
            self.seed()

    def test_finalized_hardlink_rejected(self):
        self.seed()
        os.link(self.target / "verdict.json", self.root / "hardlink")
        with self.assertRaisesRegex(storage.StorageError, "hardlinked target"):
            self.seed()

    def test_scan_allocated_is_metadata_only(self):
        with patch.object(storage, "_hash", side_effect=AssertionError("file contents forbidden")):
            stats = storage.scan_allocated(self.source)
        self.assertEqual(stats["file_count"], 2)
        self.assertGreaterEqual(stats["du_bytes"], 0)
        self.assertNotIn("files", stats)


if __name__ == "__main__":
    unittest.main()
