#!/usr/bin/env python3
"""Synthetic-only checks for the B5 batch-1 adapters and format gate."""

from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import n6_b5_batch1_prepare as batch  # noqa: E402
import n6_b5_format_pilot as format_pilot  # noqa: E402
import n6_b5_j_adapter as adapter  # noqa: E402
import n6_j1_runner_test as fixtures  # noqa: E402
import run_n6_j1 as runner  # noqa: E402


class B5Batch1PreparationTest(unittest.TestCase):
    def test_collector_pin_matches_current_source(self) -> None:
        self.assertEqual(batch.COLLECTOR_SHA, batch.sha256(batch.COLLECTOR))

    def test_install_tools_pin_matches_current_record(self) -> None:
        self.assertEqual(batch.TOOLS_SHA, batch.sha256(batch.TOOLS))

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "runs")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_retry_gate_preserves_original_state(self) -> None:
        original = self.root / "original.json"
        retry = self.root / "retry.json"
        original.write_text('{"status":"stopped_between_units"}\n')
        retry.write_text('{"status":"completed"}\n')
        with (patch.object(adapter, "ORIGINAL_STATE", original),
              patch.object(adapter, "ORIGINAL_SHA", adapter.sha256(original)),
              patch.object(adapter, "RETRY_STATE", retry),
              patch.object(adapter, "RETRY_SHA", adapter.sha256(retry))):
            adapter.verify_mem20()
            retry.write_text('{"status":"running"}\n')
            with self.assertRaises(ValueError):
                adapter.verify_mem20()

    def test_v1_and_overlay_validate_same_synthetic_request_rows(self) -> None:
        fixture = fixtures.JRunnerTest("test_order_revision_isolation_and_resume")
        fixture.setUp()
        try:
            index_path, index_hash = fixture.make_index([
                ("main", "revision-a", "S", 1, None),
                ("main", "revision-b", "S", 1, "base_input_unavailable"),
            ])
            original = runner.validate_index(index_path, index_hash)
            v22_engine = fixture.root / "zkfDO-v2.2"
            v22_engine.write_bytes(b"synthetic second engine")
            v22_index = fixture.root / "index-v2.2.json"
            v22_hash = batch.make_engine_overlay(
                index_path, v22_index, v22_engine, runner.sha256(v22_engine)
            )
            with (patch.object(runner, "ENGINE", v22_engine),
                  patch.object(runner, "ENGINE_SHA256", runner.sha256(v22_engine))):
                overlay = runner.validate_index(v22_index, v22_hash)
            self.assertEqual(original["requests"], overlay["requests"])
            self.assertEqual(len(original["requests"]), 2)
        finally:
            fixture.doCleanups()

    def test_pilot_format_checks_structure_only(self) -> None:
        output = self.root / "pilot"
        output.mkdir()
        base = self.root / "base-index.json"
        base.write_text('{"schema":"n6-j1-base-inputs-v1"}\n')
        selection = self.root / "selection.json"
        selection.write_text('{"requests":[]}\n')
        index = self.root / "index.json"
        rows = [{"queue_order": number, "request_sha256": f"request-{number}",
                 "candidate_sha256": f"candidate-{number}"} for number in range(2)]
        index.write_text(json.dumps({"engine_sha256": "synthetic-engine",
                                     "requests": rows}) + "\n")
        requests_state = {}
        for number, row in enumerate(rows):
            path = output / f"result-{number}.json"
            path.write_text(json.dumps({
                "schema": "zkfdo-lifting-result-v1",
                "request_sha256": row["request_sha256"],
                "candidate_sha256": row["candidate_sha256"],
                "preparation": {"status": "ok"},
                "classes": [{"verdict": "synthetic-test-only"}],
                "verdict_counts": {"synthetic-test-only": 1},
            }) + "\n")
            requests_state[str(number)] = {
                "queue_order": number, "status": "completed", "exit_code": 0,
                "request_sha256": row["request_sha256"], "format_ok": True,
                "max_rss_bytes": 1024, "result_path": str(path),
                "result_sha256": batch.sha256(path),
            }
        joined = output / "instances.json"
        joined.write_text('{"schema":"synthetic"}\n')
        state_header = {"kind": "n6_b5_format_only_pilot_state",
                        "status": "passed", "request_index_sha256": batch.sha256(index),
                        "base_index_sha256": batch.sha256(base),
                        "selection_sha256": batch.sha256(selection),
                        "engine_sha256": "synthetic-engine"}
        (output / "state.json").write_text(json.dumps({**state_header,
            "requests": requests_state,
            "revisions": {"main/0001": {"status": "joined", "exit_code": 0,
                        "format_ok": True,
                        "instances_path": str(joined),
                        "instances_sha256": batch.sha256(joined)}},
        }) + "\n")
        with (patch.object(batch, "BASE", base),
              patch.object(batch, "SELECTION", selection)):
            self.assertEqual(batch.pilot_format(output, index)["completed_request_count"], 2)
            requests_state["1"]["exit_code"] = 1
            (output / "state.json").write_text(json.dumps({**state_header,
                "requests": requests_state,
                "revisions": {"main/0001": {"status": "joined", "exit_code": 0,
                            "format_ok": True,
                            "instances_path": str(joined),
                            "instances_sha256": batch.sha256(joined)}},
            }) + "\n")
            with self.assertRaises(ValueError):
                batch.pilot_format(output, index)

    def test_completed_stage_rechecks_artifact_before_skip(self) -> None:
        artifact = self.root / "artifact.txt"
        artifact.write_text("original\n")
        calls = []

        def action():
            calls.append("run")
            return {"artifact_sha256": batch.sha256(artifact)}

        def verify(saved):
            batch.require(saved["artifact_sha256"] == batch.sha256(artifact),
                          "completed artifact changed")

        with patch.object(batch, "OUT", self.root / "stage-output"), redirect_stdout(io.StringIO()):
            batch.stage("synthetic", action, verify)
            batch.stage("synthetic", action, verify)
            self.assertEqual(calls, ["run"])
            artifact.write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "completed artifact changed"):
                batch.stage("synthetic", action, verify)
            self.assertEqual(calls, ["run"])

    def test_failed_pilot_retry_preserves_prior_attempt(self) -> None:
        output_root = self.root / "batch-output"
        index = self.root / "index.json"
        index.write_text("{}\n")
        base = self.root / "base.json"
        base.write_text("{}\n")
        attempts = []

        def fail_after_partial_output(_name, command):
            output = Path(command[command.index("--output") + 1])
            cache = Path(command[command.index("--cache-root") + 1])
            output.mkdir(parents=True)
            cache.mkdir()
            (output / "state.json").write_text('{"status":"stopped"}\n')
            attempts.append((output, cache))
            return 2

        with (patch.object(batch, "OUT", output_root),
              patch.object(batch, "BASE", base),
              patch.object(batch, "MIN_FREE", 0),
              patch.object(batch, "logged_command", side_effect=fail_after_partial_output),
              redirect_stdout(io.StringIO())):
            for number in (1, 2):
                with self.assertRaises(batch.StageFailure):
                    batch.stage("pilot-v1", lambda: batch.pilot("v1", index, self.root),
                                lambda _saved: None)
                state = batch.read_json(batch.state_path("pilot-v1"))
                self.assertEqual(state["attempt_number"], number)
                self.assertEqual(state["partial_state_sha256"],
                                 batch.sha256(attempts[-1][0] / "state.json"))
                self.assertTrue(attempts[-1][0].is_dir())
                self.assertTrue(attempts[-1][1].is_dir())
        self.assertNotEqual(attempts[0], attempts[1])
        self.assertTrue(attempts[0][0].is_dir())
        self.assertTrue(attempts[0][1].is_dir())

    def test_format_only_pilot_never_records_verdict_values(self) -> None:
        marker = "SYNTHETIC_SECRET_VERDICT_VALUE"
        rows = [
            {"queue_order": number, "request": str(self.root / f"r{number}.json"),
             "revision_id": f"revision-{number}", "method": "S",
             "preparation_failure": None, "request_sha256": f"request-{number}",
             "candidate_sha256": f"candidate-{number}"}
            for number in range(2)
        ]
        base_path = self.root / "base.json"
        base_path.write_text(json.dumps({"schema": "n6-j1-base-inputs-v1",
                                         "revisions": {}}) + "\n")
        selection = self.root / "selection.json"
        selection.write_text(json.dumps({"schema_version": 1,
                                         "requests": format_pilot.selected_ids(rows)}) + "\n")

        def synthetic_run(row, output_dir, _cache, _store):
            path = output_dir / "lift" / "result.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "schema": "zkfdo-lifting-result-v1",
                "request_sha256": row["request_sha256"],
                "candidate_sha256": row["candidate_sha256"],
                "preparation": {"status": "ok"},
                "classes": [{"verdict": marker}],
                "verdict_counts": {marker: 1},
                "costs": {"steps": [{"status": "aborted"}],
                          "solver_calls": [{"outcome": "unknown", "exit_code": 1}]},
            }) + "\n")
            return {"exit_code": 0, "result_path": str(path),
                    "max_rss_bytes": 1024, "wall_seconds": 0.01}

        def synthetic_join(results, output, instance_path):
            instance_path.write_text(json.dumps({
                "schema": "zkfdo-instance-verdicts-v1",
                "results": [str(path.relative_to(output)) for path in results],
                "conflicts": 0,
                "classes": [{"verdict": marker}],
            }) + "\n")
            return {"exit_code": 0, "max_rss_bytes": 1024}

        output = self.root / "pilot"
        with (patch.object(runner, "validate_index", return_value={"requests": rows}),
              patch.object(runner, "checked_sha"),
              patch.object(runner, "check_disk"),
              patch.object(format_pilot.b_selection, "select_requests", return_value=rows),
              patch.object(format_pilot.low_level, "check_selected_request"),
              patch.object(format_pilot, "run_lift", side_effect=synthetic_run),
              patch.object(format_pilot, "run_join", side_effect=synthetic_join)):
            state = format_pilot.run_format_pilot(
                self.root / "index.json", "synthetic-index-sha", base_path,
                batch.sha256(base_path), selection, self.root / "cache", output
            )
        self.assertEqual(state["status"], "passed")
        state_text = (output / "state.json").read_text()
        self.assertNotIn(marker, state_text)
        self.assertNotIn("verdict", state_text)
        self.assertNotIn("classes", state_text)
        self.assertFalse(list(output.rglob("*.stdout.log")))

    def test_tool_failure_metadata_stops_but_solver_unknown_passes(self) -> None:
        path = self.root / "result.json"
        row = {"request_sha256": "request", "candidate_sha256": "candidate"}
        result = {"schema": "zkfdo-lifting-result-v1",
                  "request_sha256": "request", "candidate_sha256": "candidate",
                  "preparation": {"status": "ok"},
                  "classes": [{"verdict": "unknown"}],
                  "verdict_counts": {"unknown": 1},
                  "costs": {"solver_calls": [{"outcome": "unknown", "exit_code": 1}],
                            "steps": [{"status": "aborted"}]}}
        path.write_text(json.dumps(result) + "\n")
        with patch.object(runner, "ENGINE_SHA256", adapter.ENGINE_V22_SHA):
            format_pilot.check_result_shape(path, row)
            result["costs"]["solver_calls"][0]["outcome"] = "timeout"
            path.write_text(json.dumps(result) + "\n")
            format_pilot.check_result_shape(path, row)
            result["costs"]["solver_calls"][0]["outcome"] = "tool_error"
            path.write_text(json.dumps(result) + "\n")
            with self.assertRaises(runner.RunnerError):
                format_pilot.check_result_shape(path, row)
            result["costs"]["steps"][0]["status"] = "timeout"
            path.write_text(json.dumps(result) + "\n")
            with self.assertRaises(runner.RunnerError):
                format_pilot.check_result_shape(path, row)
            result["costs"]["solver_calls"][0]["outcome"] = "unknown"
            result["costs"]["steps"][0]["status"] = "failed"
            path.write_text(json.dumps(result) + "\n")
            with self.assertRaises(runner.RunnerError):
                format_pilot.check_result_shape(path, row)

    def test_v1_solver_and_sweep_errors_use_only_nonverdict_class_metadata(self) -> None:
        path = self.root / "result-v1.json"
        row = {"request_sha256": "request", "candidate_sha256": "candidate"}
        result = {"schema": "zkfdo-lifting-result-v1",
                  "request_sha256": "request", "candidate_sha256": "candidate",
                  "preparation": {"status": "ok"},
                  "classes": [{"verdict": "SYNTHETIC_SECRET_VERDICT_VALUE",
                               "synthesis": {"b_outcome": "timeout",
                                             "sweep_branches": 2, "note": None}}],
                  "verdict_counts": {"SYNTHETIC_SECRET_VERDICT_VALUE": 1},
                  "costs": {"steps": [{"status": "done"}]}}
        with patch.object(runner, "ENGINE_SHA256", adapter.ENGINE_V1_SHA):
            path.write_text(json.dumps(result) + "\n")
            format_pilot.check_result_shape(path, row)
            result["classes"][0]["synthesis"]["sweep_branches"] = None
            path.write_text(json.dumps(result) + "\n")
            with self.assertRaises(runner.RunnerError):
                format_pilot.check_result_shape(path, row)
            result["classes"][0]["synthesis"]["sweep_branches"] = 2
            result["classes"][0]["synthesis"]["b_outcome"] = "solver_error"
            path.write_text(json.dumps(result) + "\n")
            with self.assertRaises(runner.RunnerError):
                format_pilot.check_result_shape(path, row)
            result["classes"][0]["synthesis"]["b_outcome"] = "sweep_unsat"
            result["classes"][0]["synthesis"]["note"] = "solver error: synthetic"
            path.write_text(json.dumps(result) + "\n")
            with self.assertRaises(runner.RunnerError):
                format_pilot.check_result_shape(path, row)
            result["classes"][0]["synthesis"]["note"] = None
            result["classes"][0]["synthesis"]["repair"] = {"outcome": "error"}
            path.write_text(json.dumps(result) + "\n")
            with self.assertRaises(runner.RunnerError):
                format_pilot.check_result_shape(path, row)

    def test_format_gate_does_not_read_verdict_entries(self) -> None:
        class PoisonClass(dict):
            def get(self, key, default=None):
                if key in {"verdict", "reason"}:
                    raise AssertionError("verdict field accessed")
                return super().get(key, default)

            def __getitem__(self, key):
                if key in {"verdict", "reason"}:
                    raise AssertionError("verdict field accessed")
                return super().__getitem__(key)

        class PoisonCounts(dict):
            def __iter__(self):
                raise AssertionError("verdict counts iterated")

            def items(self):
                raise AssertionError("verdict counts read")

            def keys(self):
                raise AssertionError("verdict counts read")

            def values(self):
                raise AssertionError("verdict counts read")

        result = {"schema": "zkfdo-lifting-result-v1",
                  "request_sha256": "request", "candidate_sha256": "candidate",
                  "preparation": {"status": "ok"},
                  "classes": [PoisonClass({"verdict": "secret", "reason": "secret",
                                           "synthesis": {"b_outcome": "timeout",
                                                         "sweep_branches": 0}})],
                  "verdict_counts": PoisonCounts({"secret": 1}),
                  "costs": {"steps": [{"status": "done"}]}}
        path = self.root / "result-poison.json"
        path.write_text("{}\n")
        with (patch.object(runner, "ENGINE_SHA256", adapter.ENGINE_V1_SHA),
              patch.object(format_pilot.json, "loads", return_value=result)):
            format_pilot.check_result_shape(
                path, {"request_sha256": "request", "candidate_sha256": "candidate"})

    def test_quiet_wait4_discards_cli_stdout(self) -> None:
        stderr = self.root / "synthetic.stderr.log"
        metrics = format_pilot.run_quiet_wait4(
            [sys.executable, "-c", "print('SYNTHETIC_VERDICT_SENTINEL')"], stderr
        )
        self.assertEqual(metrics["exit_code"], 0)
        self.assertGreater(metrics["max_rss_bytes"], 0)
        self.assertEqual(stderr.read_text(), "")
        self.assertFalse(list(self.root.glob("*.stdout.log")))

    def test_instance_format_requires_zero_conflicts(self) -> None:
        path = self.root / "instances.json"
        path.write_text(json.dumps({"schema": "zkfdo-instance-verdicts-v1",
                                    "results": ["result.json"], "conflicts": 1,
                                    "classes": [{"verdict": "synthetic"}]}) + "\n")
        with self.assertRaises(runner.RunnerError):
            format_pilot.check_instances_shape(path, ["result.json"])

    def test_entrypoint_direct_reference_and_unknown_default(self) -> None:
        repository = self.root / "recorded-repository"
        repository.mkdir()
        commit = "a" * 40
        target = Path("circuits/main.circom")
        committed_script = b"#!/bin/sh\ncircom ../../circuits/main.circom --r1cs\n"
        changed_script = repository / "ops/deploy/build.sh"
        changed_script.parent.mkdir(parents=True)
        changed_script.write_text("local working tree has no main reference\n")
        tracked = {
            "circuits/main.circom": 23,
            "ops/deploy/build.sh": len(committed_script),
            ".github/workflows/test.yml": 120,
            "runs/build.sh": 100,
        }
        tree = b"".join(
            f"100644 blob {'b' * 40} {size}\t{path}\0".encode()
            for path, size in tracked.items()
        )
        calls = []

        def git_revision(_repository, *args):
            calls.append(args)
            if args == ("rev-parse", "--show-toplevel"):
                return f"{repository}\n".encode()
            if args == ("ls-tree", "-r", "-z", "-l", commit):
                return tree
            if args == ("show", f"{commit}:ops/deploy/build.sh"):
                return committed_script
            raise AssertionError(f"unexpected recorded revision read: {args}")

        with patch.object(batch, "git_output", side_effect=git_revision):
            evidence = batch.direct_reference(repository, commit, target)
        self.assertEqual(evidence["line"], 2)
        self.assertEqual(evidence["file_relative"], "ops/deploy/build.sh")
        self.assertEqual(evidence["file_sha256"],
                         hashlib.sha256(committed_script).hexdigest())
        self.assertEqual(evidence["revision_commit"], commit)
        self.assertEqual(evidence["source"], "recorded_git_revision")
        self.assertNotIn(("show", f"{commit}:runs/build.sh"), calls)
        self.assertNotIn(("show", f"{commit}:.github/workflows/test.yml"), calls)
        workflow_paths = batch.reference_documents({
            "circuits/main.circom": 23,
            ".github/workflows/test.yml": 120,
            ".github/workflows/deploy-test.yml": 120,
            ".github/workflows/deploy.yml": 120,
        }, target)
        self.assertEqual(workflow_paths, [".github/workflows/deploy.yml"])
        self.assertTrue(batch.line_references_main(
            "circom circuits/main.circom --r1cs", "README.md", target))
        self.assertFalse(batch.line_references_main(
            "circom examples/circuits/main.circom", "README.md", target))

    def test_entrypoint_unknown_when_recorded_build_scripts_lack_main(self) -> None:
        repository = self.root / "recorded-repository"
        repository.mkdir()
        commit = "b" * 40
        source = b"#!/bin/sh\ncircom circuits/other.circom --r1cs\n"
        tree = (f"100644 blob {'c' * 40} 23\tcircuits/main.circom\0"
                f"100644 blob {'d' * 40} {len(source)}\ttools/verifier/build.sh\0").encode()

        def git_revision(_repository, *args):
            if args == ("rev-parse", "--show-toplevel"):
                return f"{repository}\n".encode()
            if args == ("ls-tree", "-r", "-z", "-l", commit):
                return tree
            if args == ("show", f"{commit}:tools/verifier/build.sh"):
                return source
            raise AssertionError(args)

        with patch.object(batch, "git_output", side_effect=git_revision):
            self.assertIsNone(batch.direct_reference(
                repository, commit, Path("circuits/main.circom")))

    def test_pragma_only_snapshot_mapping_is_explicit(self) -> None:
        original = b"template Main() {\npragma circom 2.2.3;\ncomponent main = Main();\n"
        adapted = b"template Main() {\npragma circom 2.2.1;\ncomponent main = Main();\n"
        unrelated = b"template Other() {\npragma circom 2.2.1;\ncomponent main = Other();\n"
        self.assertEqual(batch.source_relationship(original, original), "byte_identical")
        self.assertEqual(batch.source_relationship(original, adapted), "pragma_only")
        self.assertEqual(batch.source_relationship(original, unrelated),
                         "other_source_difference")


if __name__ == "__main__":
    unittest.main()
