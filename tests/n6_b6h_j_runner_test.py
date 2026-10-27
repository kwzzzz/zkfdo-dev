#!/usr/bin/env python3
"""Synthetic first-request and interrupted-attempt checks for B6h J routing."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import n6_b6h_j_runner as b6h  # noqa: E402
import run_n6_j1 as runner  # noqa: E402
from n6_b5_j_adapter import ENGINE_V1_SHA  # noqa: E402


class B6hFreshOutputTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.run_out = self.root / "runs"
        self.external = self.root / "external"
        self.cache = self.external / "cache"
        self.workspace = self.external / "hint-workspaces"
        self.stores = self.external / "instance-stores"
        for path in (self.cache, self.workspace, self.stores):
            path.mkdir(parents=True)
        self.output = self.run_out / "full-v1.noindex"
        self.records = self.root / "cleanup-records"
        self.index_sha = "a" * 64
        self.rows = []
        for order in range(3):
            request = self.root / f"request-{order}.json"
            request.write_text("{}\n")
            self.rows.append({
                "queue_order": order, "scope": "main", "revision_id": "synthetic",
                "method": "S", "request": str(request),
                "request_sha256": "r" * 64, "candidate_sha256": "c" * 64,
                "preparation_failure": None if order < 2 else
                "base_input_unavailable",
            })

    def test_first_request_starts_from_empty_output_and_routes_logs(self) -> None:
        calls: list[str] = []

        def measured(command, stdout_path, stderr_path, *, cwd=None):
            stdout_path.write_text("stdout\n")
            stderr_path.write_text("stderr\n")
            if "lift-instances" in command:
                calls.append("join")
                target = Path(command[command.index("--output") + 1])
                target.write_text(json.dumps({
                    "schema": "zkfdo-instance-verdicts-v1",
                    "results": [str(path.relative_to(self.output)) for path in
                                (self.output / "main/0001/requests/000001/attempt-0001/result.json",)],
                    "conflicts": 0,
                }) + "\n")
            else:
                request = Path(command[command.index("--request") + 1])
                order = int(request.stem.rsplit("-", 1)[1])
                self.assertTrue((self.output / "main/0001/requests" /
                                 f"{order:06d}").is_dir())
                calls.append(f"lift-{order}")
                target = Path(command[command.index("--output") + 1])
                target.mkdir(parents=True)
                (target / "raw").mkdir()
                prep = ({"status": "preparation_failure", "reason": "template_ambiguous",
                         "detail": "two declarations"} if order == 0 else
                        {"status": "ok"})
                (target / "result.json").write_text(json.dumps({
                    "schema": "zkfdo-lifting-result-v1",
                    "request_sha256": "r" * 64,
                    "candidate_sha256": "c" * 64,
                    "preparation": prep,
                    "sites_found": 1,
                }) + "\n")
            return {"exit_code": 0, "wall_seconds": 0.1, "max_rss_bytes": 4096}

        def external_root(path: Path) -> Path:
            path.mkdir(parents=True, exist_ok=True)
            return path

        with (patch.object(b6h, "ROOT",
                           Path(b6h.format_gate.__file__).resolve().parents[1]),
              patch.object(b6h, "RUN_OUT", self.run_out),
              patch.object(b6h, "RECORD_OUT", self.records),
              patch.object(b6h, "EXTERNAL", self.external),
              patch.object(b6h, "CACHE", self.cache),
              patch.object(b6h, "WORKSPACES", self.workspace),
              patch.object(b6h, "STORES", self.stores),
              patch.object(b6h, "verify_both_pilots"),
              patch.object(b6h.external_paths, "require_external_root",
                           side_effect=external_root),
              patch.object(runner, "ENGINE_SHA256", ENGINE_V1_SHA),
              patch.object(runner, "validate_index", return_value={
                  "request_count": 3, "requests": self.rows}),
              patch.object(runner, "probe_time_l", return_value={
                  "measurement_method": "wait4"}),
              patch.object(b6h.cleanup, "disk_guard", return_value={"free": 100}),
              patch.object(runner, "checked_request_sources"),
              patch.object(b6h, "initialize_cache",
                           side_effect=lambda *_: self.cache),
              patch.object(b6h.format_gate, "check_result_shape"),
              patch.object(runner, "run_with_rusage", side_effect=measured),
              patch.object(runner, "atomic_json", runner.atomic_json),
              patch.object(runner, "run_lift", runner.run_lift),
              patch.object(runner, "join_instances", runner.join_instances)):
            state = b6h.execute(self.run_out / "index.json", self.index_sha,
                                self.cache / "full-v1", self.output,
                                self.workspace, self.stores, 1024)

        self.assertEqual(calls, ["lift-0", "lift-1", "join"])
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["requests"]["0"]["status"], "preparation_failure")
        self.assertEqual(state["requests"]["1"]["status"], "completed")
        self.assertEqual(state["revisions"]["main/0001"]["instance_store"],
                         str(self.stores / "full-v1.noindex/main/0001/store"))
        request_dir = self.output / "main/0001/requests/000000"
        self.assertTrue(request_dir.is_dir())
        self.assertTrue((request_dir / "attempt-0001/result.json").is_file())
        self.assertFalse((request_dir / "attempt-0001.stdout.log").exists())
        self.assertFalse((request_dir / "attempt-0001/raw").is_symlink())
        self.assertFalse((self.workspace /
                          "full-v1.noindex/main/0001/requests/000000").exists())
        self.assertEqual(state["requests"]["0"]["workspace_cleanup"]["status"], "deleted")
        self.assertFalse((self.workspace /
                          "full-v1.noindex/main/0001/requests/000000/attempt-0001.stdout.log").exists())
        self.assertTrue((self.workspace /
                         "full-v1.noindex/main/0001/instances-attempt-0001.stdout.log").is_file())

    def test_execute_one_starts_only_selected_request_and_joins_when_complete(self) -> None:
        calls: list[str] = []

        def fake_lift(row, result_dir, cache, store, attempt, method):
            calls.append(f"lift-{row['queue_order']}")
            result_dir.mkdir(parents=True)
            (result_dir / "result.json").write_text("{}\n")
            return {"exit_code": 0, "wall_seconds": 0.1,
                    "max_rss_bytes": 4096, "measurement_method": method}

        def fake_join(result_paths, output, working, method):
            calls.append("join")
            working.write_text(json.dumps({
                "schema": "zkfdo-instance-verdicts-v1",
                "results": [str(path.relative_to(self.output)) for path in result_paths],
                "conflicts": 0,
            }) + "\n")
            return {"exit_code": 0, "wall_seconds": 0.1,
                    "max_rss_bytes": 4096, "measurement_method": method}

        with (patch.object(b6h, "ROOT",
                           Path(b6h.format_gate.__file__).resolve().parents[1]),
              patch.object(b6h, "RUN_OUT", self.run_out),
              patch.object(b6h, "RECORD_OUT", self.records),
              patch.object(b6h, "EXTERNAL", self.external),
              patch.object(b6h, "CACHE", self.cache),
              patch.object(b6h, "WORKSPACES", self.workspace),
              patch.object(b6h, "STORES", self.stores),
              patch.object(b6h, "verify_both_pilots"),
              patch.object(b6h.external_paths, "require_external_root",
                           side_effect=lambda path: path),
              patch.object(b6h.external_paths, "install_full"),
              patch.object(runner, "ENGINE_SHA256", ENGINE_V1_SHA),
              patch.object(runner, "validate_index", return_value={
                  "request_count": 3, "requests": self.rows}),
              patch.object(runner, "probe_time_l", return_value={
                  "measurement_method": "wait4"}),
              patch.object(b6h.cleanup, "disk_guard", return_value={"free": 100}),
              patch.object(runner, "checked_request_sources"),
              patch.object(b6h, "initialize_cache", side_effect=lambda *_: self.cache),
              patch.object(b6h, "inspect_result", return_value=("completed", None, None)),
              patch.object(runner, "run_lift", side_effect=fake_lift),
              patch.object(runner, "join_instances", side_effect=fake_join)):
            first = b6h.execute(self.run_out / "index.json", self.index_sha,
                                 self.cache / "full-v1", self.output,
                                 self.workspace, self.stores, 1024, only_order=0)
            self.assertEqual(first["status"], "partial")
            self.assertEqual(calls, ["lift-0"])
            second = b6h.execute(self.run_out / "index.json", self.index_sha,
                                  self.cache / "full-v1", self.output,
                                  self.workspace, self.stores, 1024, only_order=1)
            self.assertEqual(second["status"], "partial")
            self.assertEqual(calls, ["lift-0", "lift-1"])
            final = b6h.execute(self.run_out / "index.json", self.index_sha,
                                 self.cache / "full-v1", self.output,
                                 self.workspace, self.stores, 1024, only_order=2)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(calls, ["lift-0", "lift-1", "join"])
        self.assertEqual(final["revisions"]["main/0001"]["status"], "joined")

    def test_reconcile_cleanup_repairs_terminal_request_without_j(self) -> None:
        request_dir = self.output / "main/0001/requests/000000"
        result_dir = request_dir / "attempt-0001"
        result_dir.mkdir(parents=True)
        result = result_dir / "result.json"
        result.write_text("{}\n")
        external = self.workspace / "full-v1.noindex/main/0001/requests/000000"
        external.mkdir(parents=True)
        (external / "opaque.bin").write_bytes(b"opaque")
        state = {"requests": {"0": {
            "status": "completed", "queue_order": 0, "scope": "main",
            "revision_id": "synthetic", "request_sha256": "r" * 64,
            "attempt": 1, "exit_code": 0, "result_path": str(result),
            "result_sha256": runner.sha256(result)}},
            "revisions": {"main/0001": {"status": "running",
                                          "revision_id": "synthetic"}}}
        (self.output / "state.json").write_text("{}\n")
        with (patch.object(b6h, "RUN_OUT", self.run_out),
              patch.object(b6h, "RECORD_OUT", self.records),
              patch.object(b6h, "EXTERNAL", self.external),
              patch.object(b6h, "CACHE", self.cache),
              patch.object(b6h, "WORKSPACES", self.workspace),
              patch.object(b6h, "STORES", self.stores),
              patch.object(runner, "ENGINE_SHA256", ENGINE_V1_SHA),
              patch.object(b6h.external_paths, "require_external_root",
                           side_effect=lambda path: path.mkdir(parents=True,
                                                                exist_ok=True) or path),
              patch.object(runner, "validate_index", return_value={
                  "request_count": 1, "requests": [self.rows[0]]}),
              patch.object(runner, "load_state", return_value=state),
              patch.object(runner, "run_lift", side_effect=AssertionError("J lift called")),
              patch.object(runner, "join_instances",
                           side_effect=AssertionError("J join called"))):
            report = b6h.reconcile_cleanup(
                self.run_out / "index.json", self.index_sha,
                self.cache / "full-v1", self.output,
                self.workspace, self.stores)
        self.assertEqual(report["status"], "reconciled")
        self.assertEqual(report["request_cleanup_checked"], 1)
        self.assertFalse(external.exists())
        self.assertEqual(state["requests"]["0"]["workspace_cleanup"]["status"],
                         "deleted")

    def test_resume_after_revision_evidence_deleted_before_state_update(self) -> None:
        output = self.run_out / "full-v2.2.noindex"
        request_dir = output / "main/0001/requests/000000"
        result_dir = request_dir / "attempt-0001"
        result_dir.mkdir(parents=True)
        result = result_dir / "result.json"
        result.write_text("{}\n")
        event = {"queue_order": 0, "scope": "main", "revision_id": "synthetic",
                 "attempt": 1, "exit_code": 0,
                 "result_path": str(result), "result_sha256": runner.sha256(result),
                 "workspace_cleanup": {"status": "retained_evidence",
                                       "retained_evidence": {"file_count": 1,
                                                             "du_bytes": 4096}}}
        revision = {"status": "joined", "revision_id": "synthetic",
                    "instances_sha256": "a" * 64}
        state = {"requests": {"0": event},
                 "revisions": {"main/0001": revision}}
        state_path = output / "state.json"
        with patch.object(b6h, "RECORD_OUT", self.records):
            b6h._cleanup_finished_workspace(event, request_dir, output,
                                            self.workspace, state_path, state)
            b6h._cleanup_finished_revision(
                revision, self.cache, self.stores, self.workspace,
                output, "main", 1, [{"queue_order": 0}], state_path, state)
        self.assertEqual(event["workspace_cleanup_final"]["status"], "absent")
        self.assertEqual(revision["cache_cleanup"]["status"], "absent")
        self.assertEqual(revision["store_cleanup"]["status"], "absent")

    def test_zero_exit_without_result_is_retried_with_new_attempt(self) -> None:
        request_dir = self.output / "main/0001/requests/000000"
        (request_dir / "attempt-0001").mkdir(parents=True)
        (request_dir / "attempt-0001.metrics.json").write_text(json.dumps({
            "exit_code": 0, "wall_seconds": 0.1, "max_rss_bytes": 4096}) + "\n")
        self.assertIsNone(b6h._prior_zero_exit(self.rows[0], request_dir))
        self.assertEqual(b6h._next_fresh_attempt(request_dir, self.output,
                                                 self.workspace), 2)

    def test_interrupted_attempt_keeps_old_logs_and_uses_new_number(self) -> None:
        request_dir = self.output / "main/0001/requests/000001"
        request_dir.mkdir(parents=True)
        orphan = self.workspace / "full-v1.noindex/main/0001/requests/000001/attempt-0001"
        orphan.mkdir(parents=True)
        orphan.with_suffix(".stdout.log").write_text("partial\n")
        self.assertEqual(b6h._next_fresh_attempt(request_dir, self.output,
                                                 self.workspace), 2)
        self.assertEqual(orphan.with_suffix(".stdout.log").read_text(), "partial\n")
        revision_dir = self.output / "main/0001"
        join_log = self.workspace / "full-v1.noindex/main/0001/instances-attempt-0001.stdout.log"
        join_log.parent.mkdir(parents=True, exist_ok=True)
        join_log.write_text("partial join\n")
        self.assertEqual(b6h._next_fresh_join_attempt(revision_dir, self.output,
                                                      self.workspace), 2)
        self.assertEqual(join_log.read_text(), "partial join\n")


if __name__ == "__main__":
    unittest.main()
