#!/usr/bin/env python3
"""Synthetic metadata-only checks for B6f's post-run result gate."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_b6f_result_gate as gate  # noqa: E402
import run_n6_j1 as runner  # noqa: E402
from n6_b5_j_adapter import ENGINE_V1_SHA  # noqa: E402


class B6fResultGateTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / "full-v1.noindex"
        self.output.mkdir()
        self.cache = self.root / "cache" / "full-v1"
        self.index_sha = "a" * 64
        self.rows = []
        self.requests = {}
        for order in range(107):
            row = {"queue_order": order, "scope": "main",
                   "revision_id": "revision", "request": str(self.root / f"r{order}.json"),
                   "request_sha256": f"{order:064x}",
                   "preparation_failure": None if order < 2 else
                                          "base_input_unavailable",
                   "original_template_duplicate": order == 0}
            self.rows.append(row)
            event = {"queue_order": order, "scope": "main",
                     "revision_id": "revision", "request": row["request"],
                     "request_sha256": row["request_sha256"]}
            if order >= 2:
                event.update({"status": "preparation_failure",
                              "preparation_failure": "base_input_unavailable",
                              "result_path": None, "result_sha256": None})
            self.requests[str(order)] = event
        prep_artifact = (self.output / "main/0001/requests/000000/"
                         "attempt-0001/result.json")
        prep_artifact.parent.mkdir(parents=True)
        prep_artifact.write_text("opaque preparation artifact\n")
        self.requests["0"].update({
            "status": "preparation_failure", "preparation_failure": "template_ambiguous",
            "result_path": None, "result_sha256": None,
            "preparation_status": "preparation_failure",
            "preparation_detail": "two declarations", "attempt": 1, "exit_code": 0,
            "max_rss_bytes": 2048,
            "preparation_artifact_path": str(prep_artifact),
            "preparation_artifact_sha256": runner.sha256(prep_artifact),
        })
        result = self.output / "main/0001/requests/000001/attempt-0001/result.json"
        result.parent.mkdir(parents=True)
        result.write_text("opaque verdict-bearing artifact; deliberately not JSON\n")
        self.requests["1"].update({
            "status": "completed", "preparation_failure": None,
            "attempt": 1, "exit_code": 0, "max_rss_bytes": 4096,
            "result_path": str(result), "result_sha256": runner.sha256(result),
        })
        instance = self.output / "main/0001/instances.json"
        instance.write_text("opaque joined verdict artifact; deliberately not JSON\n")
        self.state = {"schema_version": 1, "status": "completed",
                      "completed_at": "2026-10-20T00:00:00+00:00",
                      "request_index_sha256": self.index_sha,
                      "engine_sha256": ENGINE_V1_SHA,
                      "circom_sha256": runner.CIRCOM_SHA256,
                      "format_checker_sha256": runner.sha256(
                          gate.b6f.ROOT / "scripts/n6_b6f_format_pilot.py"),
                      "cache_root": str(self.cache), "requests": self.requests,
                      "inspection_failure_count": 0,
                      "revisions": {"main/0001": {
                          "revision_id": "revision", "status": "joined",
                          "result_count": 1, "instances_path": str(instance),
                          "instances_sha256": runner.sha256(instance)}}}
        self.index = {"request_count": 107, "requests": self.rows}

    def summarize(self) -> dict:
        return gate.summarize_engine(self.index, self.state, self.output,
                                     "v1", self.index_sha, self.cache)

    def test_counts_preparation_by_reason_without_parsing_verdicts(self) -> None:
        summary = self.summarize()
        self.assertEqual(summary["denominator"], 107)
        self.assertEqual(summary["completed_results"], 1)
        self.assertEqual(summary["preparation_failure_count"], 106)
        self.assertEqual(summary["preparation_failures_by_reason"], {
            "base_input_unavailable": 105, "template_ambiguous": 1})
        self.assertEqual(summary["original_duplicate_template_ambiguous_count"], 1)
        self.assertIsNone(summary["verdict_unknown_count"])
        self.assertFalse(summary["verdict_values_read"])
        self.assertEqual(summary["joined_revisions"], 1)

    def test_unknown_preparation_remains_separate_from_verdict_unknown(self) -> None:
        self.requests["0"].update({
            "preparation_failure": "deviation_not_hint_assigned",
            "preparation_status": "unknown"})
        summary = self.summarize()
        self.assertEqual(summary["preparation_status_unknown_count"], 1)
        self.assertEqual(summary["preparation_failures_by_reason"]
                         ["deviation_not_hint_assigned"], 1)
        self.assertIsNone(summary["verdict_unknown_count"])

    def test_inspection_failure_counts_separately_without_parsing_artifact(self) -> None:
        event = self.requests["1"]
        event.update({
            "status": "inspection_failure", "result_path": None,
            "result_sha256": None,
            "inspection_failure_reason": "unlisted_stage_note",
            "inspection_failure_detail": "opaque structural issue",
            "inspection_artifact_path": str(result_path := self.output /
                "main/0001/requests/000001/attempt-0001/result.json"),
            "inspection_artifact_sha256": runner.sha256(result_path),
        })
        self.state["revisions"]["main/0001"].update({
            "status": "no_results", "result_count": 0,
            "instances_path": None, "instances_sha256": None,
        })
        self.state["inspection_failure_count"] = 1
        summary = self.summarize()
        self.assertEqual(summary["denominator"], 107)
        self.assertEqual(summary["completed_results"], 0)
        self.assertEqual(summary["preparation_failure_count"], 106)
        self.assertEqual(summary["inspection_failure_count"], 1)
        self.assertEqual(summary["inspection_failures_by_reason"],
                         {"unlisted_stage_note": 1})
        self.assertIsNone(summary["verdict_unknown_count"])

    def test_inspection_failure_requires_new_artifact_hash(self) -> None:
        event = self.requests["1"]
        event.update({
            "status": "inspection_failure", "result_path": None,
            "result_sha256": None,
            "inspection_failure_reason": "unlisted_stage_note",
            "inspection_failure_detail": "opaque structural issue",
            "inspection_artifact_path": str(self.output /
                "main/0001/requests/000001/attempt-0001/result.json"),
            "inspection_artifact_sha256": "0" * 64,
        })
        with self.assertRaisesRegex(runner.RunnerError, "SHA-256 mismatch"):
            self.summarize()

    def test_completed_state_rejects_fifth_inspection_failure(self) -> None:
        for order in range(1, 6):
            self.rows[order]["preparation_failure"] = None
            artifact_path = (self.output / "main/0001/requests" /
                             f"{order:06d}/attempt-0001/result.json")
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text("opaque result\n")
            self.requests[str(order)].update({
                "status": "inspection_failure", "preparation_failure": None,
                "result_path": None, "result_sha256": None,
                "attempt": 1, "exit_code": 0, "max_rss_bytes": 1024,
                "inspection_failure_reason": "unlisted_stage_note",
                "inspection_failure_detail": "opaque structural issue",
                "inspection_artifact_path": str(artifact_path),
                "inspection_artifact_sha256": runner.sha256(artifact_path),
            })
        self.state["inspection_failure_count"] = 5
        self.state["revisions"]["main/0001"].update({
            "status": "no_results", "result_count": 0,
            "instances_path": None, "instances_sha256": None,
        })
        with self.assertRaisesRegex(runner.RunnerError,
                                    "inspection failure limit exceeded"):
            self.summarize()

    def test_rejects_unclassified_reason(self) -> None:
        self.requests["0"]["preparation_failure"] = "unknown_engine_reason"
        with self.assertRaisesRegex(runner.RunnerError,
                                    "engine preparation failure invalid"):
            self.summarize()

    def test_rejects_tampered_opaque_artifact(self) -> None:
        Path(self.requests["1"]["result_path"]).write_text("changed\n")
        with self.assertRaisesRegex(runner.RunnerError, "SHA-256 mismatch"):
            self.summarize()

    def test_rejects_missing_request(self) -> None:
        del self.requests["106"]
        with self.assertRaisesRegex(runner.RunnerError,
                                    "completed state/index lock differs"):
            self.summarize()

    def test_rejects_changed_format_checker(self) -> None:
        self.state["format_checker_sha256"] = "0" * 64
        with self.assertRaisesRegex(runner.RunnerError,
                                    "completed state/index lock differs"):
            self.summarize()


if __name__ == "__main__":
    unittest.main()
