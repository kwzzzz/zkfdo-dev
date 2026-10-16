#!/usr/bin/env python3
"""Request ordering and fixed-path checks against the preserved A inventory."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.n6_j1_requests import (J_ROOT, ROOT, RequestError, base_for, build,
                                    library_paths, sha256_file)


class JRequestsTest(unittest.TestCase):
    def test_method_snapshot_library_order_and_duplicates_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            split_snapshot = root / "split-sources"
            original_project = root / "original-project"
            split_snapshot.mkdir()
            original_project.mkdir()
            target = {"preflight_compile_command": [
                "circom", "{entrypoint}", "--r1cs",
                "-l", "{workspace}", "-l", str(original_project),
                "-l", str(original_project),
            ]}
            self.assertEqual(library_paths(target, split_snapshot), [
                str(split_snapshot.resolve()), str(original_project.resolve()),
                str(original_project.resolve())])

    def test_real_inventory_has_one_ordered_request_per_candidate(self):
        inventory = J_ROOT / "candidate-inventory.json"
        revisions = J_ROOT / "revision-manifest-v2.json"
        if not inventory.is_file() or not revisions.is_file():
            self.skipTest("preserved A run inventory is unavailable")
        names = [row["identifier"] for row in json.loads(revisions.read_text())["rows"]]
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            bases = temp / "base-index.json"
            bases.write_text(json.dumps({"revisions": {
                name: {"status": "base_input_unavailable"} for name in names
            }}))
            index, files = build(ROOT, inventory, bases, temp / "requests", temp / "index.json")
            self.assertEqual(index["request_count"], 2926)
            self.assertEqual(len(files), 2926)
            self.assertEqual([row["queue_order"] for row in index["requests"]],
                             list(range(2926)))
            self.assertEqual(len({request["id"] for _, request in files}), 2926)
            self.assertEqual(index["requests"][-1]["scope"], "mem20")
            self.assertEqual(index["preparation_counts"], {"base_input_unavailable": 2926})
            groups = [(row["scope"], row["revision_id"]) for row in index["requests"]]
            closed = set()
            previous = None
            for group in groups:
                if group != previous:
                    self.assertNotIn(group, closed)
                    if previous is not None:
                        closed.add(previous)
                    previous = group
            for group in set(groups):
                subset = [row for row in index["requests"]
                          if (row["scope"], row["revision_id"]) == group]
                keys = [(row["seed"], 0 if row["method"] == "W" else 1,
                         row["attempt_number"], row["candidate_index"]) for row in subset]
                self.assertEqual(keys, sorted(keys))
            for row, (_, request) in zip(index["requests"], files):
                root = Path(request["source_root"])
                self.assertTrue(Path(request["component_wrapper"]).is_relative_to(root))
                self.assertTrue(Path(request["entrypoint"]).is_relative_to(root))
                self.assertEqual(row["component_wrapper_sha256"],
                                 sha256_file(Path(request["component_wrapper"])))
                self.assertEqual(row["entrypoint_sha256"],
                                 sha256_file(Path(request["entrypoint"])))
                self.assertEqual(row["candidate_sha256"],
                                 sha256_file(Path(request["candidate"]["path"])))
            self.assertFalse((temp / "requests").exists())

    def test_base_input_hash_mismatch_blocks_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            base = temp / "base.json"
            base.write_text("{}")
            index = {"revisions": {"sample": {"status": "passed",
                                               "base_input_path": str(base),
                                               "base_input_sha256": "0" * 64}}}
            with self.assertRaises(RequestError):
                base_for("sample", index, temp)


if __name__ == "__main__":
    unittest.main()
