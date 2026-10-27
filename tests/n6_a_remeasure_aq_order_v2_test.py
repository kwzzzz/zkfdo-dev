#!/usr/bin/env python3
"""Synthetic scheduling tests; no candidate payload or engine is read/run."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_a_remeasure_aq_order_v2 as order


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return str(path), digest(path)


class OrderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def request(self, queue, revision, site=None, **extra):
        request = {"id": f"request-{queue}", **extra}
        if site is not None:
            request["site"] = site
        path, sha = write_json(self.root / f"request-{queue}.json", request)
        return {"queue_order": queue, "revision_id": revision, "request": path,
                "request_sha256": sha, "method": "S"}

    def mapping(self, **roots):
        return {"revisions": [{"revision_id": revision,
                               "items": [{"instance_paths": paths}]}
                              for revision, paths in roots.items()]}

    def test_prefix_respects_component_and_array_boundaries(self):
        for site in ("main.a", "main.a.b", "main.a[0]", "main.a[0].b"):
            self.assertTrue(order.under(site, "main.a"))
        for site in ("main.ab", "main.a_more", "main.ab[0]", "main"):
            self.assertFalse(order.under(site, "main.a"))
        self.assertFalse(order.under("main.a[10]", "main.a[1]"))
        self.assertTrue(order.under("main.a[1].b", "main.a[1]"))

    def test_explicit_sites_and_malformed_identity(self):
        self.assertEqual(order.request_site({"method": "S"}, {"instance": "main.a"}), ["main.a"])
        self.assertEqual(order.request_site({"method": "W"}, {}), ["main"])
        self.assertEqual(order.request_site({"method": "S"}, {
            "component_wrapper_metadata": {"sites": ["main.b", "main.a", "main.b"]}}),
            ["main.a", "main.b"])
        for bad in ({}, {"site": ""}, {"site": "main.a + main.b"},
                    {"component_wrapper_metadata": {}}, {"site": None}):
            with self.assertRaises(ValueError):
                order.request_site({"method": "S"}, bad)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            order.request_site({"site": "main.a"}, {"site": "main.b"})

    def test_engine_major_and_stable_index_order(self):
        rows = [self.request(17, "r2", "main.other"), self.request(8, "r1", "main.out"),
                self.request(6, "r1", "main.mapped.child"), self.request(2, "r1", "main.out2"),
                self.request(4, "r1", "main.mapped"), self.request(10, "r2", "main.mapped")]
        indexes = {engine: {"requests": rows} for engine in order.ENGINES}
        before = json.dumps(indexes, sort_keys=True)
        result = order.computed_order(indexes, ["r1", "r2"],
                                      self.mapping(r1=["main.mapped"], r2=["main.mapped"]))
        self.assertEqual([row["engine"] for row in result], ["v2.2"] * 6 + ["v1"] * 6)
        self.assertEqual([row["queue_order"] for row in result], [6, 4, 8, 2, 10, 17] * 2)
        self.assertEqual([row["mapped"] for row in result[:6]], [True, True, False, False, True, False])
        self.assertEqual(json.dumps(indexes, sort_keys=True), before)
        self.assertEqual(result[0]["request_sha256"], rows[2]["request_sha256"])

    def fixture_wrapper(self, comments="", main="component main = Widget(8);"):
        original = self.root / "source-root/preparation/discovery/test/wrappers/0001-Widget/target.circom"
        original.parent.mkdir(parents=True)
        original.write_text(f"pragma circom 2.1.6;\n{comments}\n{main}\n")
        copied = self.root / "prepared/targets/0001/sources/preparation/discovery/test/wrappers/0001-Widget/target.circom"
        copied.parent.mkdir(parents=True)
        copied.write_bytes(original.read_bytes())
        return original, copied

    def wrapper_row(self, copied):
        row = self.request(1, "r1", component_wrapper=str(copied),
                           source_root=str(self.root / "source-root"), entrypoint="entrypoint.circom")
        row["component_wrapper_sha256"] = digest(copied)
        return row

    def test_wrapper_comment_metadata(self):
        _, copied = self.fixture_wrapper("// instance_path: main.mapped[2]\n// site: main.other")
        row = self.wrapper_row(copied)
        result = order.computed_order({engine: {"requests": [row]} for engine in order.ENGINES},
                                      ["r1"], self.mapping(r1=["main.mapped"]))
        self.assertTrue(result[0]["mapped"])
        self.assertEqual(result[0]["sites_preview"], ["main.mapped[2]", "main.other"])
        self.assertEqual(result[0]["site_basis"], "wrapper_instance_comments")

    def test_shared_wrapper_resolves_only_matching_source_and_parameters(self):
        original, copied = self.fixture_wrapper()
        row = self.wrapper_row(copied)
        source = str(self.root / "widget.circom")
        target = {"generated_wrapper_path": str(original), "source_path": source,
                  "template_name": "Widget", "concrete_parameters": ["8"]}
        discovery_path, discovery_sha = write_json(self.root / "discovery.json", {
            "selected_entrypoint": "entrypoint.circom", "targets": [target, target]})

        def instance(path, source_path=source, value="8"):
            return {"path": path, "source_path": source_path, "template_name": "Widget",
                    "arguments": [{"kind": "scalar", "value": value}]}

        capture_path, capture_sha = write_json(self.root / "capture.json", {
            "status": "captured", "entrypoint": "entrypoint.circom", "instances": [
                instance("main.mapped.a"), instance("main.other.a"),
                instance("main.mapped.wrong_size", value="7"),
                instance("main.mapped.wrong_source", source_path=str(self.root / "other.circom"))]})
        mapping = self.mapping(r1=["main.mapped"])
        mapping["revisions"][0].update(discovery_path=discovery_path, discovery_sha256=discovery_sha,
                                        capture_path=capture_path, capture_sha256=capture_sha)
        result = order.computed_order({engine: {"requests": [row]} for engine in order.ENGINES},
                                      ["r1"], mapping)
        self.assertEqual(result[0]["sites_preview"], ["main.mapped.a", "main.other.a"])
        self.assertTrue(result[0]["multiple_sites"])
        self.assertTrue(result[0]["mapped"])
        self.assertEqual(result[0]["site_metadata"]["capture_sha256"], capture_sha)
        Path(capture_path).write_text("{}")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            order.computed_order({engine: {"requests": [row]} for engine in order.ENGINES}, ["r1"], mapping)

    def test_compact_site_evidence_classifies_all_sites_not_only_preview(self):
        sites = [f"main.site{x:02d}" for x in range(12)]
        row = self.request(1, "r1", sites=sites)
        result = order.computed_order({engine: {"requests": [row]} for engine in order.ENGINES},
                                      ["r1"], self.mapping(r1=[sites[-1]]))
        record = result[0]
        self.assertEqual(record["site_count"], 12)
        self.assertEqual(record["sites_preview"], sites[:order.SITE_PREVIEW_LIMIT])
        self.assertTrue(record["sites_preview_truncated"])
        self.assertEqual(record["mapped_roots"], [sites[-1]])
        self.assertTrue(record["mapped"])
        self.assertEqual(record["sites_sha256"],
                         hashlib.sha256(json.dumps(sites, separators=(",", ":")).encode()).hexdigest())

    def test_missing_wrapper_fails_instead_of_unmapped(self):
        row = self.request(1, "r1")
        with self.assertRaisesRegex(ValueError, "missing S component wrapper"):
            order.computed_order({engine: {"requests": [row]} for engine in order.ENGINES},
                                 ["r1"], self.mapping(r1=["main.mapped"]))

    def test_bad_wrapper_main_fails_even_without_mapping_revision(self):
        _, copied = self.fixture_wrapper(main="// component main = Widget(8);")
        row = self.wrapper_row(copied)
        with self.assertRaisesRegex(ValueError, "malformed S wrapper main identity"):
            order.computed_order({engine: {"requests": [row]} for engine in order.ENGINES},
                                 ["r1"], self.mapping())

    def test_request_hash_and_duplicate_queue_fail_closed(self):
        row = self.request(1, "r1", "main.mapped")
        indexes = {engine: {"requests": [row, row]} for engine in order.ENGINES}
        with self.assertRaisesRegex(ValueError, "duplicated queues"):
            order.computed_order(indexes, ["r1"], self.mapping())
        Path(row["request"]).write_text("{}")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            order.computed_order({engine: {"requests": [row]} for engine in order.ENGINES},
                                 ["r1"], self.mapping())


if __name__ == "__main__":
    unittest.main()
