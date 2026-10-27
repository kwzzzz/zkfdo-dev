#!/usr/bin/env python3
"""Synthetic tests for pinned B6h pair ordering and safe resume."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_b6h_pair_runner as pair


class PairRunnerTests(unittest.TestCase):
    def test_id_sorted_seed_shuffle_and_pair_order(self) -> None:
        ids = ["zeta", "beta", "alpha", "delta", "gamma"]
        with patch.object(pair, "REQUEST_COUNT", 5):
            remaining, tasks = pair.task_sequence(ids, [0, 3])
        expected = [2, 1, 4]
        random.Random(pair.SEED).shuffle(expected)
        self.assertEqual(remaining, expected)
        self.assertEqual([(task["engine"], task["queue_order"])
                          for task in tasks[:2]], [("v1", 0), ("v1", 3)])
        self.assertEqual([(task["engine"], task["queue_order"])
                          for task in tasks[2:]],
                         [(engine, order) for order in expected
                          for engine in ("v2.2", "v1")])
        self.assertTrue(all("request_id" not in task for task in tasks))
        self.assertEqual(tasks[0]["request_id_sha256"], pair.request_id_sha("zeta"))

    def test_state_projection_accesses_only_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({
                "status": "engine_failed",
                "requests": {"0": {"status": "completed",
                                   "candidate": "never expose", "verdict": "never expose"},
                             "2": {"status": "preparation_failure",
                                   "request": "never expose"}},
                "revisions": {"private": "never expose"},
            }))
            with patch.object(pair, "REQUEST_COUNT", 3):
                self.assertEqual(pair.state_projection(state),
                                 ("engine_failed", {0: "completed",
                                                    2: "preparation_failure"}))

    def test_cutoff_finishes_active_call_then_resume_skips_it(self) -> None:
        tasks = [{"engine": "v1", "queue_order": 0},
                 {"engine": "v2.2", "queue_order": 1},
                 {"engine": "v1", "queue_order": 1}]
        finished = {"v1": {0: "completed"}, "v2.2": {}}
        calls: list[tuple[str, int]] = []
        cutoff = datetime(2026, 10, 29, 14, 59, tzinfo=timezone.utc)
        now = cutoff - timedelta(seconds=1)

        def read(engine: str) -> tuple[str, dict[int, str]]:
            return "partial", dict(finished[engine])

        def launch(engine: str, order: int) -> int:
            calls.append((engine, order))
            finished[engine][order] = "completed"
            return 0

        def clock() -> datetime:
            return now if not calls else cutoff

        self.assertEqual(pair.drive_tasks(tasks, read, launch, clock, cutoff),
                         ("time", 2))
        self.assertEqual(calls, [("v2.2", 1)])
        self.assertEqual(pair.drive_tasks(tasks, read, launch,
                                          lambda: cutoff - timedelta(seconds=1),
                                          cutoff), (None, 3))
        self.assertEqual(calls, [("v2.2", 1), ("v1", 1)])

    def test_space_stop_keeps_next_task(self) -> None:
        tasks = [{"engine": "v2.2", "queue_order": 39},
                 {"engine": "v1", "queue_order": 39}]
        cutoff = datetime(2026, 10, 29, 14, 59, tzinfo=timezone.utc)

        def read(_engine: str) -> tuple[str, dict[int, str]]:
            return "disk_guard_stopped", {}

        self.assertEqual(pair.drive_tasks(
            tasks, read, lambda _engine, _order: 2,
            lambda: cutoff - timedelta(seconds=1), cutoff), ("space", 0))

    def test_order_file_is_immutable_and_hash_locked(self) -> None:
        ids = ["c", "a", "b"]
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pair, "REQUEST_COUNT", 3), \
             patch.object(pair, "ORDER_PATH", Path(tmp) / "order.json"):
            document = pair.order_document(ids, ids, "1" * 64, "2" * 64,
                                           {0: "completed"})
            sha = pair.write_new_order(pair.ORDER_PATH, document)
            loaded = pair.load_order(pair.ORDER_PATH, sha, ids, ids,
                                     "1" * 64, "2" * 64)
            self.assertEqual(loaded["tasks"], document["tasks"])
            with self.assertRaises(pair.PairError):
                pair.write_new_order(pair.ORDER_PATH, document)
            with self.assertRaises(pair.PairError):
                pair.load_order(pair.ORDER_PATH, "0" * 64, ids, ids,
                                "1" * 64, "2" * 64)

    def test_one_request_command_preserves_engine_paths(self) -> None:
        class Args:
            v1_index_sha256 = "1" * 64
            v2_2_index_sha256 = "2" * 64
            v1_static_preflight_sha256 = "3" * 64
            v2_2_static_preflight_sha256 = "4" * 64
            first_lead_review_sha256 = "5" * 64
            second_lead_review_sha256 = "6" * 64
            observed_request_peak_bytes = pair.b6h.OBSERVED_REQUEST_PEAK_BYTES

        command = pair.one_request_command(Args(), "v2.2", 39)
        self.assertEqual(command[-4:], ["--action", "execute-one",
                                        "--queue-order", "39"])
        self.assertIn(str(pair.b6h.RUN_OUT / "full-v2.2.noindex"), command)
        self.assertIn(str(pair.b6h.CACHE / "full-v2.2"), command)
        self.assertEqual(pair.reconcile_command(Args(), "v1")[-2:],
                         ["--action", "reconcile-cleanup"])

    def test_revision_groups_use_only_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pair, "REQUEST_COUNT", 3):
            path = Path(tmp) / "index.json"
            path.write_text(json.dumps({"request_count": 3, "requests": [
                {"queue_order": 0, "scope": "main", "revision_id": "a",
                 "candidate": "never expose"},
                {"queue_order": 1, "scope": "main", "revision_id": "a",
                 "verdict": "never expose"},
                {"queue_order": 2, "scope": "main", "revision_id": "b"},
            ]}))
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(pair.index_revision_groups(path, sha), [[0, 1], [2]])

    def test_reconcile_only_fully_finished_revisions(self) -> None:
        groups = [[0, 1], [2], [3, 4]]
        current = {"v2.2": ("engine_failed", {0: "completed", 1: "completed",
                                            2: "preparation_failure"}),
                   "v1": ("completed", {i: "completed" for i in range(5)})}
        calls: list[tuple[str, int]] = []

        def read(engine: str) -> tuple[str, dict[int, str]]:
            top, finished = current[engine]
            return top, dict(finished)

        def launch(engine: str, order: int) -> int:
            calls.append((engine, order))
            return 0

        with patch.object(pair, "REQUEST_COUNT", 5):
            pair.reconcile_completed_revisions(groups, read, launch)
            self.assertEqual(calls, [("v2.2", 1), ("v2.2", 2)])
            current["v2.2"] = ("partial", {i: "completed" for i in range(5)})
            calls.clear()
            pair.reconcile_completed_revisions(groups, read, launch)
            self.assertEqual(calls, [("v2.2", 4)])


if __name__ == "__main__":
    unittest.main()
