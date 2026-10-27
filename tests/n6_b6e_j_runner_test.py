#!/usr/bin/env python3
"""Synthetic checks for B6e's failure handling and unit source pins."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_b6e_j_runner as b6e  # noqa: E402
import n6_b6d_source_bindings as bindings  # noqa: E402
import run_n6_j1 as runner  # noqa: E402


class B6ePreparationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.row = {"request_sha256": "a" * 64, "candidate_sha256": "b" * 64,
                    "method": "S"}
        self.metrics = {"exit_code": 0, "max_rss_bytes": 1024,
                        "wall_seconds": 1.0}

    def result(self, status: str, reason: str | None = None,
               detail: str | None = None) -> dict:
        return {"schema": "zkfdo-lifting-result-v1",
                "request_sha256": self.row["request_sha256"],
                "candidate_sha256": self.row["candidate_sha256"],
                "preparation": {"status": status, "reason": reason,
                                "detail": detail},
                "sites_found": 1}

    def test_all_engine_reasons_are_partitioned(self) -> None:
        self.assertEqual(len(b6e.ENGINE_PREPARATION_REASONS), 29)
        self.assertFalse(b6e.INTRINSIC_REASONS & b6e.ENVIRONMENT_REASONS)
        self.assertEqual(b6e.ENGINE_PREPARATION_REASONS,
                         b6e.INTRINSIC_REASONS | b6e.ENVIRONMENT_REASONS)

    def test_intrinsic_failure_preserves_reason_and_detail(self) -> None:
        result = self.result("preparation_failure", "template_ambiguous",
                             "instance main: two templates")
        status, reason, detail = b6e.classify_preparation(result, self.row,
                                                            self.metrics)
        self.assertEqual((status, reason, detail),
                         ("preparation_failure", "template_ambiguous",
                          "instance main: two templates"))

    def test_candidate_unknown_status_is_preparation_row(self) -> None:
        result = self.result("unknown", "deviation_not_hint_assigned",
                             "no hint assignment")
        self.assertEqual(b6e.classify_preparation(result, self.row, self.metrics),
                         ("unknown", "deviation_not_hint_assigned",
                          "no hint assignment"))

    def test_environment_and_unknown_reason_fail_closed(self) -> None:
        result = self.result("preparation_failure", "io", "disk full")
        self.assertIn(b6e.classify_preparation(result, self.row,
                                               self.metrics)[1],
                      b6e.ENVIRONMENT_REASONS)
        result["preparation"]["reason"] = "future_unclassified_reason"
        with self.assertRaisesRegex(runner.RunnerError,
                                    "unknown or malformed preparation"):
            b6e.classify_preparation(result, self.row, self.metrics)

    def test_status_reason_pairing_and_identity_fail_closed(self) -> None:
        result = self.result("unknown", "template_ambiguous", "two")
        with self.assertRaisesRegex(runner.RunnerError, "pairing"):
            b6e.classify_preparation(result, self.row, self.metrics)
        result = self.result("preparation_failure", "template_ambiguous", "two")
        result["candidate_sha256"] = "c" * 64
        with self.assertRaisesRegex(runner.RunnerError, "identity mismatch"):
            b6e.classify_preparation(result, self.row, self.metrics)

    def test_execute_continues_after_intrinsic_failure_and_resumes(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        out = root / "out"
        cache = root / "external" / "cache"
        workspace = root / "external" / "hint-workspaces"
        stores = root / "external" / "instance-stores"
        for path in (cache, workspace, stores):
            path.mkdir(parents=True)
        rows = []
        for order in range(107):
            request = root / f"request-{order}.json"
            if order < 2:
                request.write_text("{}\n")
            rows.append({"queue_order": order, "scope": "main",
                         "revision_id": "synthetic-revision", "method": "S",
                         "request": str(request), "request_sha256": "a" * 64,
                         "candidate_sha256": "b" * 64,
                         "preparation_failure": None if order < 2 else
                                                "base_input_unavailable"})
        index = {"requests": rows, "request_count": 107}
        calls: list[int] = []

        def lift(row, result_dir, cache_path, store, attempt, method):
            calls.append(row["queue_order"])
            result_dir.mkdir(parents=True)
            if row["queue_order"] == 0:
                preparation = {"status": "preparation_failure",
                               "reason": "template_ambiguous",
                               "detail": "two declarations"}
            else:
                preparation = {"status": "ok", "reason": None, "detail": None}
            (result_dir / "result.json").write_text(json.dumps({
                "schema": "zkfdo-lifting-result-v1",
                "request_sha256": row["request_sha256"],
                "candidate_sha256": row["candidate_sha256"],
                "preparation": preparation, "sites_found": 1}) + "\n")
            return {"exit_code": 0, "wall_seconds": 0.1,
                    "max_rss_bytes": 2048, "measurement_method": method}

        def join(paths, output, path, method):
            path.write_text(json.dumps({"schema": "zkfdo-instance-verdicts-v1",
                                        "results": [str(p.relative_to(output)) for p in paths],
                                        "conflicts": 0}) + "\n")
            return {"exit_code": 0, "wall_seconds": 0.1,
                    "max_rss_bytes": 1024, "measurement_method": method}

        with patch.object(b6e, "OUT", out), \
                patch.object(b6e, "EXTERNAL", root / "external"), \
                patch.object(b6e, "CACHE", cache), \
                patch.object(b6e, "WORKSPACES", workspace), \
                patch.object(b6e, "STORES", stores), \
                patch.object(b6e, "verify_both_pilots"), \
                patch.object(b6e.external_paths, "require_external_root",
                             side_effect=lambda path: path), \
                patch.object(b6e.external_paths, "install_full"), \
                patch.object(runner, "validate_index", return_value=index), \
                patch.object(runner, "probe_time_l", return_value={
                    "measurement_method": "wait4"}), \
                patch.object(runner, "check_disk", return_value={"free": 100}), \
                patch.object(runner, "checked_request_sources"), \
                patch.object(b6e, "initialize_cache",
                             side_effect=lambda *_: cache), \
                patch.object(runner, "run_lift", side_effect=lift), \
                patch.object(runner, "join_instances", side_effect=join):
            state = b6e.execute(out / "request-index-v1.json", "c" * 64,
                                cache / "full-v1", out / "full-v1.noindex")
            resumed = b6e.execute(out / "request-index-v1.json", "c" * 64,
                                  cache / "full-v1", out / "full-v1.noindex")
        self.assertEqual(calls, [0, 1])
        self.assertEqual(state["status"], resumed["status"])
        self.assertEqual(len(state["requests"]), 107)
        self.assertEqual(state["requests"]["0"]["status"], "preparation_failure")
        self.assertEqual(state["requests"]["0"]["preparation_failure"],
                         "template_ambiguous")
        self.assertIsNone(state["requests"]["0"]["result_path"])
        self.assertEqual(state["requests"]["1"]["status"], "completed")
        self.assertEqual(state["revisions"]["main/0001"]["result_count"], 1)
        self.assertEqual(len((out / "full-v1.noindex" / "attempts.jsonl")
                             .read_text().splitlines()), 108)

    def _run_first_failure(self, result_text: str) -> tuple[dict, list[int]]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        out = root / "out"
        cache = root / "external" / "cache"
        workspace = root / "external" / "hint-workspaces"
        stores = root / "external" / "instance-stores"
        for path in (cache, workspace, stores):
            path.mkdir(parents=True)
        request = root / "request-0.json"
        request.write_text("{}\n")
        rows = [{"queue_order": order, "scope": "main",
                 "revision_id": "synthetic-revision", "method": "S",
                 "request": str(request), "request_sha256": "a" * 64,
                 "candidate_sha256": "b" * 64,
                 "preparation_failure": None if order == 0 else
                                        "base_input_unavailable"}
                for order in range(107)]
        calls: list[int] = []

        def lift(row, result_dir, cache_path, store, attempt, method):
            calls.append(row["queue_order"])
            result_dir.mkdir(parents=True)
            (result_dir / "result.json").write_text(result_text)
            return {"exit_code": 0, "wall_seconds": 0.1,
                    "max_rss_bytes": 2048, "measurement_method": method}

        with patch.object(b6e, "OUT", out), \
                patch.object(b6e, "EXTERNAL", root / "external"), \
                patch.object(b6e, "CACHE", cache), \
                patch.object(b6e, "WORKSPACES", workspace), \
                patch.object(b6e, "STORES", stores), \
                patch.object(b6e, "verify_both_pilots"), \
                patch.object(b6e.external_paths, "require_external_root",
                             side_effect=lambda path: path), \
                patch.object(b6e.external_paths, "install_full"), \
                patch.object(runner, "validate_index", return_value={
                    "requests": rows, "request_count": 107}), \
                patch.object(runner, "probe_time_l", return_value={
                    "measurement_method": "wait4"}), \
                patch.object(runner, "check_disk", return_value={"free": 100}), \
                patch.object(runner, "checked_request_sources"), \
                patch.object(b6e, "initialize_cache",
                             side_effect=lambda *_: cache), \
                patch.object(runner, "run_lift", side_effect=lift):
            with self.assertRaises((runner.RunnerError, ValueError)):
                b6e.execute(out / "request-index-v1.json", "c" * 64,
                            cache / "full-v1", out / "full-v1.noindex")
        state = json.loads((out / "full-v1.noindex" / "state.json").read_text())
        return state, calls

    def test_io_preparation_failure_stops_without_next_request(self) -> None:
        result = self.result("preparation_failure", "io", "disk full")
        state, calls = self._run_first_failure(json.dumps(result) + "\n")
        self.assertEqual(calls, [0])
        self.assertEqual(state["status"], "environment_preparation_failure")
        self.assertEqual(state["next_queue_order"], 0)
        self.assertEqual(state["requests"], {})

    def test_resource_detail_stops_even_for_intrinsic_reason(self) -> None:
        result = self.result("preparation_failure", "component_compile_failed",
                             "compiler: No space left on device")
        state, calls = self._run_first_failure(json.dumps(result) + "\n")
        self.assertEqual(calls, [0])
        self.assertEqual(state["status"], "resource_preparation_failure")
        self.assertEqual(state["next_queue_order"], 0)

    def test_malformed_result_stops_without_next_request(self) -> None:
        state, calls = self._run_first_failure('{"schema": broken\n')
        self.assertEqual(calls, [0])
        self.assertEqual(state["status"], "result_invalid")
        self.assertEqual(state["next_queue_order"], 0)
        self.assertEqual(state["requests"], {})

    def test_revised_e2_annotation_requires_exact_pair_coverage(self) -> None:
        pairs = [{"pair_id": str(i), "queue_orders": [i],
                  "original_duplicate": i < 9} for i in range(16)]
        pairs.append({"pair_id": "16", "queue_orders": list(range(16, 107)),
                      "original_duplicate": False})
        audit = {"schema_version": 2, "status": "pass",
                 "b": {"status": "pass", "request_count": 107,
                       "pair_count": 17, "original_duplicate_request_count": 9,
                       "pairs": pairs},
                 "a": {"status": "pass", "request_count": 2926,
                       "revision_count": 26}}
        self.assertEqual(b6e.original_duplicate_orders(audit), set(range(9)))
        audit["b"]["pairs"][0]["original_duplicate"] = False
        with self.assertRaisesRegex(runner.RunnerError,
                                    "original duplicate requests differ"):
            b6e.original_duplicate_orders(audit)


class B6eSourceFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.clone = self.root / "clone"
        self.project = self.root / "staging" / "unit" / "project"
        self.preparation = self.root / "staging" / "unit" / "preparation"
        for directory in (self.clone, self.project, self.preparation):
            directory.mkdir(parents=True)
        original = self.clone / "main.circom"
        staged = self.project / "main.circom"
        original.write_text("template T() {}\n")
        staged.write_bytes(original.read_bytes())
        original_wrapper = self.root / "original-wrapper.circom"
        wrapper = self.preparation / "wrapper.circom"
        original_wrapper.write_text(f'include "{original}";\ncomponent main = T();\n')
        wrapper.write_text(f'include "{staged}";\ncomponent main = T();\n')
        self.pair = {"source_root": str(self.project.parent),
                     "project_root": str(self.project),
                     "preparation_root": str(self.preparation),
                     "original_clone_root": str(self.clone),
                     "original_entrypoint": str(original),
                     "entrypoint": str(staged),
                     "original_wrapper": str(original_wrapper),
                     "wrapper": str(wrapper),
                     "original_wrapper_sha256": runner.sha256(original_wrapper),
                     "wrapper_sha256": runner.sha256(wrapper),
                     "entrypoint_sha256": runner.sha256(original),
                     "original_library_paths": [str(self.clone)],
                     "library_paths": [str(self.project)],
                     "project_files": [{"path": "main.circom",
                                        "original_sha256": runner.sha256(original),
                                        "staged_sha256": runner.sha256(staged)}]}

    def test_accepts_one_regular_project_copy(self) -> None:
        bindings._validate_pair_files(self.pair)

    def test_rejects_changed_project_bytes(self) -> None:
        (self.project / "main.circom").write_text("different\n")
        with self.assertRaisesRegex(runner.RunnerError, "SHA-256"):
            bindings._validate_pair_files(self.pair)

    def test_rejects_extra_project_copy(self) -> None:
        (self.project / "extra.circom").write_text("template Extra() {}\n")
        with self.assertRaisesRegex(runner.RunnerError, "file set changed"):
            bindings._validate_pair_files(self.pair)

    def test_rejects_symlinked_project_file(self) -> None:
        (self.project / "main.circom").unlink()
        (self.project / "main.circom").symlink_to(self.clone / "main.circom")
        with self.assertRaisesRegex(runner.RunnerError, "linked|redirected"):
            bindings._validate_pair_files(self.pair)


if __name__ == "__main__":
    unittest.main()
