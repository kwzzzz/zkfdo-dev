#!/usr/bin/env python3
"""Synthetic runner/real-cleanup integration; all engine/join/scorer calls mocked."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import n6_a_remeasure_aq_execute_v2_test as fixtures
import n6_a_remeasure_aq_execute_v2 as aq


REAL_CLEANUP_REQUEST = aq.cleanup_request
REAL_REVISION_CLEANUP = aq.revision_cleanup
REAL_RESERVE_BYTES = aq.reserve_bytes


class CleanupIntegrationTests(fixtures.RunnerTests):
    """Use the runner fixture while replacing only its cleanup mocks with real code."""

    # Do not inherit and rerun the parent's independent state-machine cases here.
    for _name in dir(fixtures.RunnerTests):
        if _name.startswith("test_"):
            locals()[_name] = None
    del _name

    def setUp(self):
        super().setUp()
        self.patch(aq, "cleanup_request", REAL_CLEANUP_REQUEST)
        self.patch(aq, "revision_cleanup", REAL_REVISION_CLEANUP)
        self.patch(aq, "reserve_bytes", REAL_RESERVE_BYTES)
        self.between_requests = []
        self.join_observations = []
        self.lift.side_effect = self.lift_with_artifacts
        self.join.side_effect = self.join_with_evidence_check

    def evidence(self, engine, row, attempt=1):
        return aq.attempt_paths(engine, row, attempt)[2] / "raw/site-001/input.json"

    def lift_with_artifacts(self, row, workspace, cache, store, attempt, method):
        engine = workspace.relative_to(self.external).parts[0]
        previous = [r for r in self.rows if r["revision_id"] == row["revision_id"]
                    and r["queue_order"] < row["queue_order"]]
        for earlier in previous:
            evidence = self.evidence(engine, earlier)
            self.assertTrue(evidence.is_file(), "store evidence vanished before later request")
            prior_workspace = aq.attempt_paths(engine, earlier, 1)[2]
            self.assertFalse((prior_workspace / "result.json").exists())
            self.assertFalse((prior_workspace / "large-disposable.bin").exists())
            self.assertFalse(prior_workspace.with_suffix(".stdout.log").exists())
            self.assertFalse(prior_workspace.with_suffix(".stderr.log").exists())
            self.between_requests.append((engine, earlier["queue_order"], row["queue_order"]))
        if engine == "v1":
            # Engine-major revision cleanup must not wait for the second engine.
            for earlier in self.rows:
                self.assertFalse(aq.attempt_paths("v2.2", earlier, 1)[2].parent.exists())
            self.assertFalse((self.external / "v2.2/caches/main/0001").exists())
            self.assertFalse((self.external / "v2.2/stores/main/0001").exists())
        metrics = self.lift_result(row, workspace, cache, store, attempt, method)
        evidence = workspace / "raw/site-001/input.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_bytes(b"synthetic retained witness input")
        (evidence.parent / "honest.wtns").write_bytes(b"synthetic witness")
        (workspace / "large-disposable.bin").write_bytes(b"x" * 8192)
        workspace.with_suffix(".stdout.log").write_text("synthetic stdout")
        workspace.with_suffix(".stderr.log").write_text("synthetic stderr")
        store.mkdir(parents=True, exist_ok=True)
        (store / "stored.json").write_text("{}")
        (cache / "compiled.bin").write_bytes(b"synthetic cache")
        return metrics

    def join_with_evidence_check(self, paths, output, target, method):
        engine = target.relative_to(self.output).parts[2]
        requests = [aq.read(path)["request_id"] for path in paths]
        for row in self.rows:
            if f"request-{row['queue_order']}" in requests:
                self.assertTrue(self.evidence(engine, row).is_file())
                self.join_observations.append((engine, row["queue_order"]))
        return self.join_results(paths, output, target, method)

    def assert_cleaned(self, state):
        for engine in aq.ENGINES:
            for row in self.rows:
                event = state["engines"][engine]["requests"][str(row["queue_order"])]
                self.assertFalse(aq.attempt_paths(engine, row, event["attempt"])[2].parent.exists())
                aq.checked_event(engine, row, event)
            for scope, ordinal, _revision, _rows in aq.runner.groups(self.rows):
                self.assertFalse((self.external / engine / "caches" / scope / f"{ordinal:04d}").exists())
                self.assertFalse((self.external / engine / "stores" / scope / f"{ordinal:04d}").exists())

    def test_request_cleanup_preserves_store_evidence_until_join_and_cleans_before_other_engine(self):
        self.row(1)
        self.row(2)
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.between_requests, [("v2.2", 1, 2), ("v1", 1, 2)])
        self.assertEqual(self.join_observations, [(e, q) for e in aq.ENGINES for q in (1, 2)])
        self.assert_cleaned(state)
        request_receipts = [r for r in state["cleanup_receipts"] if "attempt" in r["binding"]]
        self.assertTrue(any(r["status"] == "retained_evidence" for r in request_receipts))
        for receipt in request_receipts:
            self.assertIn("result_sha256", receipt["binding"])
            self.assertIn("metrics_sha256", receipt["binding"])
            for label in ("before", "after"):
                self.assertEqual(aq.runner.sha256(Path(receipt[f"{label}_path"])),
                                 receipt[f"{label}_sha256"])
        self.assertGreater(sum(r["freed_du_bytes"] for r in state["cleanup_receipts"]), 0)

    def test_join_failure_still_cleans_engine_revision_and_continues(self):
        self.row(1, "r1")
        self.row(2, "r2")
        calls = []

        def failing_join(paths, output, target, method):
            calls.append(target)
            if len(calls) == 1:
                self.assertTrue(self.evidence("v2.2", self.rows[0]).is_file())
                raise aq.runner.RunnerError("synthetic join failure")
            return self.join_with_evidence_check(paths, output, target, method)

        self.join.side_effect = failing_join
        state, result = self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(state["revisions"]["v2.2/r1"]["status"], "failed")
        self.assertEqual(state["revisions"]["v2.2/r2"]["status"], "completed")
        self.assertEqual([c[:3] for c in self.calls],
                         [(e, revision, queue) for e in aq.ENGINES
                          for revision, queue in (("r1", 1), ("r2", 2))])
        self.assert_cleaned(state)


if __name__ == "__main__":
    unittest.main()
