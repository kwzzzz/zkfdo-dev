#!/usr/bin/env python3
"""Small synthetic checks for the offline counters; never run J or fuzzing."""
import json
from pathlib import Path
import tempfile
import unittest

import n6_light_rqc_20261026 as score


def cls(own="unknown", predicates=None, representative="main.site"):
    return {"verdict": own, "representative": representative,
            "predicates": predicates or []}


def pred(name, verdict):
    return {"instance": name, "verdict": verdict}


class OfflineChecks(unittest.TestCase):
    def test_unknown_predicate_prevents_all_excluded(self):
        item = cls(predicates=[pred("main.site.a", score.EXCLUDED), pred("main.site.b", "unknown")])
        self.assertEqual(score.classify_class(item, ["main.site"], {})["status"], "unknown")

    def test_all_predicates_excluded(self):
        item = cls(predicates=[pred("main.site.a", score.EXCLUDED), pred("main.site.b", score.EXCLUDED)])
        self.assertEqual(score.classify_class(item, ["main.site"], {})["status"], "excluded")

    def test_ancestor_violation_not_attributed_to_child(self):
        self.assertIsNone(score.classify_class(cls("entrypoint_violation", representative="main"), ["main.site"], {}))

    def test_lexical_prefix_is_not_descendant(self):
        self.assertFalse(score.under("main.siteOther.lt", "main.site"))
        self.assertTrue(score.under("main.site[1].lt", "main.site"))

    def test_shared_reach_for_same_instance_only(self):
        item = cls(predicates=[pred("main.site.lt", "unknown")])
        unrelated = {"main.other.lt": {"verdict": score.REACH}}
        self.assertEqual(score.classify_class(item, ["main.site"], unrelated)["status"], "unknown")
        same = {"main.site.lt": {"verdict": score.REACH, "reach_classification": "private_only"}}
        result = score.classify_class(item, ["main.site"], same)
        self.assertEqual(result["status"], "L1")
        self.assertFalse(result["self_l1"])

    def test_missing_observation_not_unknown_or_exclusion(self):
        result = score.aggregate_cells([])
        self.assertTrue(result["no_observation"])
        self.assertFalse(result["unknown_observed"])
        self.assertFalse(result["excluded_observed"])

    def test_duplicate_repetitions_do_not_count_as_bugs(self):
        cell = {"observed_statuses": ["L1"], "evidence_sources": [1],
                "revision_id": "r", "reach_inputs": ["private_only"]}
        self.assertEqual(score.aggregate_cells([cell] * 100), score.aggregate_cells([cell]))

    def test_mixed_results_preserved(self):
        cells = [{"observed_statuses": [status], "evidence_sources": [1],
                  "revision_id": "r", "reach_inputs": []} for status in ("excluded", "unknown")]
        result = score.aggregate_cells(cells)
        self.assertTrue(result["mixed_statuses_definition_outside"])
        self.assertEqual(result["observed_statuses"], ["excluded", "unknown"])

    def test_wrong_sha_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            path.write_text(json.dumps({"schema": "synthetic"}))
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                score.Reader().read(path, "0" * 64)

    def test_future_aq_nested_state_adapter(self):
        state = {"schema": "n6-a-remeasure-aq-execute-v1",
                 "config": {"index_sha256": {"v1": "index"}, "engine_sha256": {"v1": "engine"}},
                 "engines": {"v1": {"requests": {"7": {"status": "not_run"}},
                    "groups": {"main/0001": {"scope": "main", "revision": "aq-synthetic",
                                              "join": {"path": "saved.json", "sha256": "saved"}}}}}}
        result = score.normalize_state(state, "v1")
        self.assertEqual(result["request_index_sha256"], "index")
        self.assertEqual(result["revisions"]["main/0001"]["instances_path"], "saved.json")
        self.assertEqual(result["requests"], state["engines"]["v1"]["requests"])

    def test_same_location_not_credited_to_two_bugs(self):
        maps = [{"item_id": name, "instance_paths": ["main.site"]} for name in ("bug-a", "bug-b")]
        item = cls(predicates=[pred("main.site.lt", score.REACH)])
        rows = score.attribute_class(item, maps, {})
        self.assertTrue(all(obs["ambiguous_bug_ids"] for _, obs in rows))

    def test_distinct_predicate_locations_not_ambiguous(self):
        maps = [{"item_id": "bug-a", "instance_paths": ["main.a"]},
                {"item_id": "bug-b", "instance_paths": ["main.b"]}]
        item = cls(predicates=[pred("main.a.lt", score.REACH), pred("main.b.lt", score.REACH)], representative="main")
        rows = score.attribute_class(item, maps, {})
        self.assertTrue(all(not obs["ambiguous_bug_ids"] for _, obs in rows))


if __name__ == "__main__":
    unittest.main()
