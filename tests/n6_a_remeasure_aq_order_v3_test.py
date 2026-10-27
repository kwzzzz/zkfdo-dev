#!/usr/bin/env python3
"""Synthetic v3 scheduling checks; no J execution or real state/output writes."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_a_remeasure_aq_order_v3 as order


class TwoPassOrderingTests(unittest.TestCase):
    def baseline(self, counts=None):
        counts = counts or {revision: (2, 2) for revision in order.DEFAULT_REVISIONS}
        rows = []
        for engine in order.ENGINES:
            for index, revision in enumerate(order.DEFAULT_REVISIONS):
                mapped, rest = counts.get(revision, (0, 0))
                for offset, flag in enumerate([True] * mapped + [False] * rest):
                    rows.append({"engine": engine, "revision": revision,
                                 "queue_order": index * 100 + offset, "mapped": flag,
                                 "request_sha256": f"sha-{engine}-{index}-{offset}",
                                 "site_count": 20 + offset, "sites_sha256": f"sites-{index}-{offset}",
                                 "sites_preview": ["main.component"], "mapped_roots": ["main"] if flag else []})
        return rows

    def compute(self, baseline, revisions=None):
        with mock.patch.object(order.previous, "computed_order", return_value=baseline) as inherited:
            result = order.computed_order({}, revisions or list(order.DEFAULT_REVISIONS), {})
        return result, inherited

    def test_engine_major_two_pass_order_preserves_classification_and_metadata(self):
        baseline = self.baseline()
        saved = copy.deepcopy(baseline)
        result, _ = self.compute(baseline)
        expected = []
        for engine in order.ENGINES:
            for pass_name, revisions in (("A", order.PRIORITY_REVISIONS),
                                          ("B", order.PRIORITY_REVISIONS),
                                          ("rest", order.DEFAULT_REVISIONS[7:])):
                for revision in revisions:
                    expected.extend((engine, revision, pass_name, row["queue_order"])
                                    for row in baseline if row["engine"] == engine and
                                    row["revision"] == revision and
                                    (pass_name == "rest" or row["mapped"] == (pass_name == "A")))
        self.assertEqual([(row["engine"], row["revision"], row["pass"], row["queue_order"])
                          for row in result], expected)
        self.assertEqual(baseline, saved)
        original = {(row["engine"], row["queue_order"]): row for row in baseline}
        for row in result:
            self.assertEqual({key: value for key, value in row.items()
                              if key not in {"pass", "segment_id", "segment_is_final"}},
                             original[(row["engine"], row["queue_order"])])
            self.assertEqual(row["segment_is_final"], row["pass"] != "A")

    def test_empty_b_segments_finalize_after_all_a_segments(self):
        baseline = self.baseline({revision: (1, 0) for revision in order.DEFAULT_REVISIONS})
        result, _ = self.compute(baseline)
        segments = order.segments_for(result)
        self.assertEqual(len(segments), 40)
        first_engine = [segment for segment in segments if segment["engine"] == "v2.2"]
        self.assertEqual([segment["pass"] for segment in first_engine], ["A"] * 7 + ["B"] * 7 + ["rest"] * 6)
        self.assertTrue(all(not segment["final_for_revision"] for segment in first_engine[:7]))
        self.assertTrue(all(segment["final_for_revision"] and not segment["requests"]
                            for segment in first_engine[7:14]))

    def test_empty_a_segments_and_completely_empty_revision_are_explicit(self):
        counts = {revision: (0, 1) for revision in order.DEFAULT_REVISIONS}
        counts[order.PRIORITY_REVISIONS[2]] = (0, 0)
        baseline = self.baseline(counts)
        result, _ = self.compute(baseline)
        segments = order.segments_for(result, list(order.DEFAULT_REVISIONS))
        self.assertEqual(len(segments), 40)
        empty_revision = [segment for segment in segments
                          if segment["revision"] == order.PRIORITY_REVISIONS[2]]
        self.assertEqual(len(empty_revision), 4)
        self.assertTrue(all(not segment["requests"] for segment in empty_revision))
        self.assertEqual([segment["final_for_revision"] for segment in empty_revision],
                         [False, True, False, True])
        self.assertEqual(len(order.segments_for([], list(order.DEFAULT_REVISIONS))), 40)
        self.assertEqual(order.segments_for([]), [])

    def test_selection_filters_fixed_approved_order(self):
        selected = [order.DEFAULT_REVISIONS[8], order.DEFAULT_REVISIONS[1], order.DEFAULT_REVISIONS[0]]
        baseline = [row for row in self.baseline() if row["revision"] in selected]
        result, inherited = self.compute(baseline, selected)
        canonical = list(order.DEFAULT_REVISIONS[:2]) + [order.DEFAULT_REVISIONS[8]]
        self.assertEqual(inherited.call_args.args[1], canonical)
        self.assertEqual([segment["revision"] for segment in order.segments_for(result, selected)[:5]],
                         canonical[:2] + canonical[:2] + canonical[2:])
        for bad in ([selected[0], selected[0]], ["aq-unapproved"]):
            with self.assertRaises(ValueError):
                order.computed_order({}, bad, {})

    def test_rest_preserves_full_v2_order_and_failed_request_2185(self):
        revision = order.DEFAULT_REVISIONS[7]
        baseline = [{"engine": engine, "revision": revision, "queue_order": queue,
                     "mapped": mapped, "request_sha256": f"sha-{queue}"}
                    for engine in order.ENGINES
                    for queue, mapped in ((2193, True), (2185, False), (2186, False))]
        result, _ = self.compute(baseline, [revision])
        self.assertEqual([row["queue_order"] for row in result], [2193, 2185, 2186] * 2)
        self.assertTrue(all(row["pass"] == "rest" and row["segment_is_final"] for row in result))

    def test_segments_reject_inconsistent_order_duplicate_or_flags(self):
        result, _ = self.compute(self.baseline())
        with self.assertRaisesRegex(ValueError, "out of order"):
            order.segments_for(list(reversed(result)))
        with self.assertRaisesRegex(ValueError, "duplicated"):
            order.segments_for([result[0], result[0]])
        bad = copy.deepcopy(result)
        bad[0]["mapped"] = False
        with self.assertRaisesRegex(ValueError, "mapped flag"):
            order.segments_for(bad)
        bad = copy.deepcopy(result)
        bad[0]["segment_is_final"] = True
        with self.assertRaisesRegex(ValueError, "metadata differs"):
            order.segments_for(bad)

    def test_real_v2_helper_integration_reads_only_temporary_requests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            revisions = list(order.PRIORITY_REVISIONS[:2]) + [order.DEFAULT_REVISIONS[7]]
            rows = []
            for index, revision in enumerate(revisions):
                for offset, site in enumerate(("main.other", "main.mapped", "main.other2")):
                    queue = 10 * index + offset
                    path = root / f"{queue}.json"
                    path.write_text(json.dumps({"site": site}))
                    rows.append({"queue_order": queue, "revision_id": revision, "method": "S",
                                 "request": str(path), "request_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            indexes = {engine: {"requests": rows} for engine in order.ENGINES}
            mapping = {"revisions": [{"revision_id": revision, "items": [{"instance_paths": ["main.mapped"]}]}
                                       for revision in revisions]}
            result = order.computed_order(indexes, revisions, mapping)
            self.assertEqual([row["queue_order"] for row in result], [1, 11, 0, 2, 10, 12, 21, 20, 22] * 2)
            self.assertEqual([row["pass"] for row in result[:9]], ["A", "A", "B", "B", "B", "B", "rest", "rest", "rest"])


if __name__ == "__main__":
    unittest.main()
