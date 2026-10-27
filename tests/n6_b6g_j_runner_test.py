#!/usr/bin/env python3
"""Synthetic first-request and interrupted-attempt checks for B6g J routing."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import n6_b6g_j_runner as b6g  # noqa: E402
import run_n6_j1 as runner  # noqa: E402
from n6_b5_j_adapter import ENGINE_V1_SHA  # noqa: E402


class B6gFreshOutputTest(unittest.TestCase):
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

        with (patch.object(b6g, "ROOT",
                           Path(b6g.format_gate.__file__).resolve().parents[1]),
              patch.object(b6g, "RUN_OUT", self.run_out),
              patch.object(b6g, "EXTERNAL", self.external),
              patch.object(b6g, "CACHE", self.cache),
              patch.object(b6g, "WORKSPACES", self.workspace),
              patch.object(b6g, "STORES", self.stores),
              patch.object(b6g, "verify_both_pilots"),
              patch.object(b6g.external_paths, "require_external_root",
                           side_effect=external_root),
              patch.object(runner, "ENGINE_SHA256", ENGINE_V1_SHA),
              patch.object(runner, "validate_index", return_value={
                  "request_count": 3, "requests": self.rows}),
              patch.object(runner, "probe_time_l", return_value={
                  "measurement_method": "wait4"}),
              patch.object(runner, "check_disk", return_value={"free": 100}),
              patch.object(runner, "checked_request_sources"),
              patch.object(b6g, "initialize_cache",
                           side_effect=lambda *_: self.cache),
              patch.object(b6g.format_gate, "check_result_shape"),
              patch.object(runner, "run_with_rusage", side_effect=measured),
              patch.object(runner, "atomic_json", runner.atomic_json),
              patch.object(runner, "run_lift", runner.run_lift),
              patch.object(runner, "join_instances", runner.join_instances)):
            state = b6g.execute(self.run_out / "index.json", self.index_sha,
                                self.cache / "full-v1", self.output,
                                self.workspace, self.stores)

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
        self.assertTrue((self.workspace /
                         "full-v1.noindex/main/0001/requests/000000/attempt-0001.stdout.log").is_file())
        self.assertTrue((self.workspace /
                         "full-v1.noindex/main/0001/instances-attempt-0001.stdout.log").is_file())

    def test_interrupted_attempt_keeps_old_logs_and_uses_new_number(self) -> None:
        request_dir = self.output / "main/0001/requests/000001"
        request_dir.mkdir(parents=True)
        orphan = self.workspace / "full-v1.noindex/main/0001/requests/000001/attempt-0001"
        orphan.mkdir(parents=True)
        orphan.with_suffix(".stdout.log").write_text("partial\n")
        self.assertEqual(b6g._next_fresh_attempt(request_dir, self.output,
                                                 self.workspace), 2)
        self.assertEqual(orphan.with_suffix(".stdout.log").read_text(), "partial\n")
        revision_dir = self.output / "main/0001"
        join_log = self.workspace / "full-v1.noindex/main/0001/instances-attempt-0001.stdout.log"
        join_log.parent.mkdir(parents=True, exist_ok=True)
        join_log.write_text("partial join\n")
        self.assertEqual(b6g._next_fresh_join_attempt(revision_dir, self.output,
                                                      self.workspace), 2)
        self.assertEqual(join_log.read_text(), "partial join\n")


if __name__ == "__main__":
    unittest.main()
