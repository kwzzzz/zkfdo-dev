#!/usr/bin/env python3
"""B6h metadata records, reserve calculation, and failed-attempt safety."""

from __future__ import annotations

from collections import namedtuple
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import n6_b6h_cleanup as cleanup  # noqa: E402
import n6_b6h_cleanup_cli as cli  # noqa: E402
import n6_b6h_j_runner as b6h  # noqa: E402


class CleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.external = self.root / "external"
        self.external.mkdir()
        self.records = self.root / "runs/n6-b6h/cleanup-records"

    def test_record_exists_before_deletion_and_does_not_open_target_contents(self) -> None:
        target = self.external / "cache/main/0001"
        target.mkdir(parents=True)
        source = target / "opaque.bin"
        source.write_bytes(b"do-not-read")
        original_open = Path.open
        original_unlink = Path.unlink
        observed = []

        def checked_open(path: Path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(target), "external file was opened")
            return original_open(path, *args, **kwargs)

        def checked_unlink(path: Path, *args, **kwargs):
            if path == source:
                manifests = list((self.records / "revision_cache").glob("*.json"))
                self.assertEqual(len(manifests), 1)
                self.assertTrue(manifests[0].is_file())
                observed.append("record-before-delete")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "open", checked_open), patch.object(Path, "unlink", checked_unlink):
            result = cleanup.cleanup_tree(
                self.external, target, self.records, "revision_cache", {"revision": 1})
        self.assertEqual(observed, ["record-before-delete"])
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["file_count"], 1)
        self.assertGreater(result["du_bytes"], 0)
        self.assertFalse(target.exists())
        manifest = json.loads(Path(result["manifest"]).read_text())
        self.assertEqual(manifest["file_list_sha256"], result["file_list_sha256"])
        self.assertEqual(result["file_list_sha256"],
                         hashlib.sha256(b"opaque.bin\0").hexdigest())
        self.assertEqual(manifest["kind"], "n6_b6h_external_cleanup_before_delete")

    def test_v22_request_cleanup_retains_only_store_evidence_until_join(self) -> None:
        root = self.external / "hint-workspaces"
        target = root / "full-v2.2.noindex/main/0005/requests/000038"
        site = target / "attempt-0001/raw/site-000"
        predicate = site / "predicate-00"
        predicate.mkdir(parents=True)
        evidence = [site / "input.json", site / "honest.wtns",
                    predicate / "class-o0.wtns",
                    predicate / "exclusion-0.smt2",
                    predicate / "exclusion-0.z3.log",
                    predicate / "found-input.json", predicate / "found.wtns"]
        for item in evidence:
            item.write_bytes(b"opaque-evidence")
        disposable = [target / "attempt-0001.stdout.log",
                      target / "attempt-0001/raw/huge.bin",
                      site / "unrelated.bin",
                      predicate / "search/temporary.bin"]
        for item in disposable:
            item.parent.mkdir(parents=True, exist_ok=True)
            item.write_bytes(b"opaque-disposable")
        before = {}
        original_open = Path.open
        original_unlink = Path.unlink

        def checked_open(item: Path, *args, **kwargs):
            self.assertFalse(item.is_relative_to(target), "external contents opened")
            return original_open(item, *args, **kwargs)

        def checked_unlink(item: Path, *args, **kwargs):
            if item.is_relative_to(target):
                before["manifest_present"] = bool(list(
                    (self.records / "request_workspace").glob("*.json")))
            return original_unlink(item, *args, **kwargs)

        with patch.object(Path, "open", checked_open), \
                patch.object(Path, "unlink", checked_unlink):
            result = cleanup.cleanup_request_workspace(
                root, target, self.records, {"queue_order": 38},
                preserve_v22_evidence=True)
        self.assertEqual(result["status"], "retained_evidence")
        self.assertTrue(before["manifest_present"])
        self.assertEqual(result["retained_evidence"]["file_count"], len(evidence))
        self.assertEqual(result["deleted_files"]["file_count"], len(disposable))
        self.assertTrue(all(item.is_file() for item in evidence))
        self.assertTrue(all(not item.exists() for item in disposable))
        cleanup.verify_retained_workspace(root, target, result["retained_evidence"])
        manifest = json.loads(Path(result["manifest"]).read_text())
        self.assertEqual(manifest["retained_evidence"], result["retained_evidence"])
        self.assertEqual(manifest["deleted_files"], result["deleted_files"])
        final = cleanup.cleanup_tree(root, target, self.records,
                                     "revision_evidence", {"revision": 5})
        self.assertEqual(final["status"], "deleted")
        self.assertFalse(target.exists())

    def test_guard_uses_twice_measured_peak_and_20_gib_internal(self) -> None:
        usage = namedtuple("usage", "total used free")
        output = self.root / "result"
        cache = self.root / "cache"
        work = self.root / "work"
        store = self.root / "store"
        peak = 280 * cleanup.GIB
        def free(path: Path):
            available = 20 * cleanup.GIB if path == output else 560 * cleanup.GIB
            return usage(1000 * cleanup.GIB, 0, available)
        with patch.object(cleanup.shutil, "disk_usage", side_effect=free):
            result = cleanup.disk_guard(output, cache, work, store, peak)
        self.assertEqual(result["required_ssd_free_bytes"], 560 * cleanup.GIB)
        with patch.object(cleanup.shutil, "disk_usage", side_effect=lambda path:
                          usage(1000 * cleanup.GIB, 0,
                                20 * cleanup.GIB if path == output else 914 * cleanup.GIB)):
            paired = cleanup.disk_guard(output, cache, work, store, peak,
                                        other_engine_cache_growth_bytes=177 * cleanup.GIB)
        self.assertEqual(paired["required_ssd_free_bytes"], 914 * cleanup.GIB)
        with patch.object(cleanup.shutil, "disk_usage", side_effect=free):
            with self.assertRaises(cleanup.DiskGuardStop):
                cleanup.disk_guard(output, cache, work, store, peak,
                                   retained_evidence_du_bytes=cleanup.GIB)
        with patch.object(cleanup.shutil, "disk_usage", side_effect=lambda path:
                          usage(1000 * cleanup.GIB, 0,
                                19 * cleanup.GIB if path == output else 560 * cleanup.GIB)):
            with self.assertRaises(cleanup.DiskGuardStop):
                cleanup.disk_guard(output, cache, work, store, peak)
        with patch.object(cleanup.shutil, "disk_usage", side_effect=lambda path:
                          usage(1000 * cleanup.GIB, 0,
                                20 * cleanup.GIB if path == output else 559 * cleanup.GIB)):
            with self.assertRaises(cleanup.DiskGuardStop):
                cleanup.disk_guard(output, cache, work, store, peak)

    def test_guard_reserve_counts_only_live_retained_evidence(self) -> None:
        state = {"requests": {
            "0": {"workspace_cleanup": {"status": "retained_evidence",
                                          "retained_evidence": {"du_bytes": 4096}}},
            "1": {"workspace_cleanup": {"status": "retained_evidence",
                                          "retained_evidence": {"du_bytes": 8192}},
                  "workspace_cleanup_final": {"status": "deleted"}},
            "2": {"workspace_cleanup": {"status": "deleted"}},
        }}
        self.assertEqual(b6h._retained_evidence_du_bytes(state), 4096)

    def test_manual_cli_rejects_a_and_unlisted_b_paths(self) -> None:
        legacy = cli.VOLUME / "n6-b6f-batch1x/cache"
        cli.approved(legacy, "legacy_cache", {})
        cli.approved(cli.VOLUME / "n6-b6-batch1x/pilot-v2.2", "legacy_cache", {})
        with self.assertRaises(cleanup.CleanupError):
            cli.approved(cli.VOLUME / "n6-b6-batch1x/other", "legacy_cache", {})
        with self.assertRaises(cleanup.CleanupError):
            cli.approved(cli.VOLUME / "n6-b6-acal/cache", "legacy_cache", {})
        other = cli.B6G / "hint-workspaces/full-v2.2.noindex/main/0004/requests/000036"
        with self.assertRaises(cleanup.CleanupError):
            cli.approved(other, "request_workspace", {})
        cli.approved(other, "request_workspace",
                     {(str(other), "request_workspace"):
                      {"path": str(other), "category": "request_workspace"}})
        unfinished_revision = cli.B6G / "hint-workspaces/full-v2.2.noindex/main/0005/requests/000038"
        with self.assertRaises(cleanup.CleanupError):
            cli.approved(unfinished_revision, "request_workspace",
                         {(str(unfinished_revision), "request_workspace"):
                          {"path": str(unfinished_revision),
                           "category": "request_workspace"}})
        store_root = self.external / "n6-b6g-batch1x"
        store = store_root / "instance-stores/full-v2.2.noindex/main/0002/store"
        with (patch.object(cli, "VOLUME", self.external),
              patch.object(cli, "B6G", store_root)):
            with self.assertRaises(cleanup.CleanupError):
                cli.approved(store, "revision_store", {})
            cli.approved(store, "revision_store",
                         {(str(store), "revision_store"):
                          {"path": str(store), "category": "revision_store"}})
        with self.assertRaises(cleanup.CleanupError):
            cli.approved(cli.CACHE_39 / ("a" * 64), "abandoned_cache", {})

    def test_selective_cli_requires_exact_approved_request_metadata(self) -> None:
        volume = self.external
        batch = volume / "n6-b6g-batch1x"
        target = batch / "hint-workspaces/full-v2.2.noindex/main/0005/requests/000038"
        target.mkdir(parents=True)
        (target / "attempt-0001.stdout.log").write_bytes(b"opaque")
        summary, _, _ = cleanup.inventory(volume, target)
        item = {"path": str(target), "category": "request_workspace",
                "birthtime_unix": target.lstat().st_birthtime,
                "precleanup_file_count": summary["file_count"],
                "precleanup_file_list_sha256": summary["file_list_sha256"],
                "precleanup_du_kib": summary["du_bytes"] // 1024}
        key = (str(target), "request_workspace")
        with (patch.object(cli, "VOLUME", volume),
              patch.object(cli, "B6G", batch)):
            cli.approved(target, "selective_request_workspace", {key: item})
            bad = {**item, "precleanup_file_count": item["precleanup_file_count"] + 1}
            with self.assertRaises(cleanup.CleanupError):
                cli.approved(target, "selective_request_workspace", {key: bad})
            with self.assertRaises(cleanup.CleanupError):
                cli.approved(target, "request_workspace", {key: item})

    def test_existing_revision_store_needs_matching_birthtime(self) -> None:
        store = self.external / "instance-stores/main/0002/store"
        store.mkdir(parents=True)
        key = (str(store), "revision_store")
        with self.assertRaises(cleanup.CleanupError):
            cli._dynamic_entry(store, "revision_store", {key: {}})
        with self.assertRaises(cleanup.CleanupError):
            cli._dynamic_entry(store, "revision_store",
                               {key: {"birthtime_unix": store.lstat().st_birthtime + 1}})
        cli._dynamic_entry(store, "revision_store",
                           {key: {"birthtime_unix": store.lstat().st_birthtime}})

    def test_half_written_external_attempt_keeps_local_result_and_retries(self) -> None:
        output = self.root / "runs/full-v2.2.noindex"
        request = output / "main/0005/requests/000039"
        local = request / "attempt-0001"
        local.mkdir(parents=True)
        result = local / "result.json"
        result.write_text("preserve existing result\n")
        work = self.external / "hint-workspaces"
        partial = work / output.name / "main/0005/requests/000039"
        (partial / "attempt-0001").mkdir(parents=True)
        (partial / "attempt-0001/partial.bin").write_bytes(b"unfinished")
        cleanup.cleanup_tree(work, partial, self.records, "abandoned_workspace",
                             {"queue_order": 39, "attempt": 1})
        self.assertEqual(result.read_text(), "preserve existing result\n")
        self.assertFalse(partial.exists())
        self.assertEqual(b6h._next_fresh_attempt(request, output, work), 2)


if __name__ == "__main__":
    unittest.main()
