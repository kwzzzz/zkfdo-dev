"""B6f method-error format gate and resumable inspection-failure tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import n6_b6f_format_pilot as pilot  # noqa: E402
import n6_b6f_j_runner as b6f  # noqa: E402
import run_n6_j1 as runner  # noqa: E402
from n6_b5_j_adapter import ENGINE_V1_SHA, ENGINE_V22_SHA  # noqa: E402


def result_record(method: dict | None = None) -> dict:
    synthesis: dict = {"b_outcome": "timeout", "note": None}
    if method is not None:
        synthesis["repair"] = method
    return {"schema": "zkfdo-lifting-result-v1",
            "request_sha256": "r" * 64, "candidate_sha256": "c" * 64,
            "preparation": {"status": "ok"},
            "classes": [{"synthesis": synthesis}],
            "costs": {"steps": [{"status": "done"}], "solver_calls": []}}


def row_record(order: int = 9) -> dict:
    return {"queue_order": order, "request_sha256": "r" * 64,
            "candidate_sha256": "c" * 64, "method": "S",
            "request": f"/synthetic/request-{order}.json", "revision_id": "rev"}


class B6fPilotRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_result(self, value: dict, name: str = "result.json") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n")
        return path

    def test_source_backed_unsupported_notes_pass(self) -> None:
        observed_a = (
            "the generator aborted in  line 0 (unclassified) "
            "and no new statement there can be blanked"
        )
        pairs = [(ENGINE_V1_SHA, None, observed_a),
                 (ENGINE_V22_SHA, "tool_or_unsupported", observed_a),
                 (ENGINE_V22_SHA, "tool_or_unsupported", pilot.DEVIATION_NOTE),
                 (ENGINE_V22_SHA, "region_limit",
                  "the predicate instance has too many constraints"),
                 (ENGINE_V22_SHA, "region_limit",
                  "repair region has too many constraints"),
                 (ENGINE_V22_SHA, "diagnostic_failure",
                  "the diagnostic copy still aborts after blanking 6 checks")]
        for engine_sha, kind, note in pairs:
            with self.subTest(engine=engine_sha[:8], note=note):
                for stage in ("repair", "injection"):
                    self.assertEqual(
                        pilot.classify_method_error(
                            stage, {"outcome": "error", "error_kind": kind,
                                    "note": note}, engine_sha),
                        "unsupported")

    def test_fault_unknown_and_kind_mismatch_stop(self) -> None:
        cases = [({"outcome": "error", "error_kind": "io",
                  "note": "cannot read tool output"}, True),
                 ({"outcome": "error", "error_kind": None,
                   "note": "z3 is not available"}, True),
                 ({"outcome": "error", "error_kind": "tool_or_unsupported",
                   "note": "No such file or directory (os error 2)"}, True),
                 ({"outcome": "error", "error_kind": "tool_timeout",
                   "note": "solver timed out"}, False),
                 ({"outcome": "error", "error_kind": "tool_or_unsupported",
                   "note": "unexpected note"}, False),
                 ({"outcome": "error", "error_kind": "io",
                   "note": pilot.DEVIATION_NOTE}, True)]
        for record, environment in cases:
            with self.subTest(record=record):
                with self.assertRaises(pilot.MethodInspectionError) as caught:
                    pilot.classify_method_error("repair", record, ENGINE_V22_SHA)
                self.assertEqual(caught.exception.environment, environment)
        with self.assertRaises(pilot.MethodInspectionError):
            pilot.classify_method_error(
                "repair", {"outcome": "error", "error_kind": None,
                           "note": "repair region has too many constraints"},
                ENGINE_V1_SHA)

    def test_full_format_gate_accepts_unsupported_and_rejects_fault(self) -> None:
        method = {"outcome": "error", "error_kind": "tool_or_unsupported",
                  "note": pilot.DEVIATION_NOTE}
        path = self.write_result(result_record(method))
        with patch.object(runner, "ENGINE_SHA256", ENGINE_V22_SHA):
            errors = pilot.check_result_shape(path, row_record())
            self.assertEqual(errors, [{"stage": "repair", "outcome": "error",
                                       "error_kind": "tool_or_unsupported",
                                       "note": pilot.DEVIATION_NOTE}])
            method["error_kind"] = "evidence_invariant"
            self.write_result(result_record(method))
            with self.assertRaises(pilot.MethodInspectionError):
                pilot.check_result_shape(path, row_record())
            malformed = result_record()
            malformed["classes"] = "broken"
            self.write_result(malformed)
            with self.assertRaises(runner.RunnerError):
                pilot.check_result_shape(path, row_record())

    def test_external_tool_failure_stops_immediately(self) -> None:
        row = row_record()
        value = result_record()
        value["costs"]["solver_calls"] = [{"outcome": "solver_unavailable"}]
        path = self.write_result(value)
        metrics = {"max_rss_bytes": 100}
        with patch.object(runner, "ENGINE_SHA256", ENGINE_V22_SHA):
            with self.assertRaises(pilot.FormatInspectionError) as caught:
                pilot.check_result_shape(path, row)
            self.assertTrue(caught.exception.environment)
            with self.assertRaises(pilot.FormatInspectionError):
                b6f.inspect_result(path, row, metrics)
            value["costs"]["solver_calls"] = []
            value["costs"]["steps"] = [{"status": "tool_error"}]
            self.write_result(value)
            with self.assertRaises(pilot.FormatInspectionError) as caught:
                pilot.check_result_shape(path, row)
            self.assertTrue(caught.exception.environment)

    def test_nonenvironment_invalid_structure_occupies_request(self) -> None:
        row = row_record()
        value = result_record()
        value["classes"] = "broken"
        path = self.write_result(value)
        with patch.object(runner, "ENGINE_SHA256", ENGINE_V22_SHA):
            status, reason, detail = b6f.inspect_result(
                path, row, {"max_rss_bytes": 100})
        self.assertEqual(status, "inspection_failure")
        self.assertEqual(reason, "format_invalid")
        self.assertIn("structure", detail)

    def test_format_gate_does_not_select_final_verdict_fields(self) -> None:
        class Poison(dict):
            def get(self, key, default=None):
                if key in {"verdict", "verdict_counts", "reason", "witness"}:
                    raise AssertionError("final verdict field accessed")
                return super().get(key, default)

            def __getitem__(self, key):
                if key in {"verdict", "verdict_counts", "reason", "witness"}:
                    raise AssertionError("final verdict field accessed")
                return super().__getitem__(key)

        synthetic = Poison(result_record())
        synthetic["classes"] = [Poison({"synthesis": {"b_outcome": None}})]
        path = self.write_result({})
        with (patch.object(runner, "ENGINE_SHA256", ENGINE_V22_SHA),
              patch.object(pilot.json, "loads", return_value=synthetic)):
            self.assertEqual(pilot.check_result_shape(path, row_record()), [])

    def test_existing_v22_results_are_rechecked_without_execution_or_mutation(self) -> None:
        old_base = self.root / "old"
        old_pilot = old_base / "pilot-v2.2.noindex"
        new_base = self.root / "new"
        new_base.mkdir()
        old_pilot.mkdir(parents=True)
        rows = [row_record(order) for order in range(107)]
        index_path = old_base / "request-index-v2.2.json"
        index_path.write_text(json.dumps({"requests": rows}) + "\n")
        selection = {"schema_version": 1,
                     "requests": pilot.original.selected_ids([rows[9], rows[25]])}
        selection_path = old_base / "pilot-selection.json"
        selection_path.write_text(json.dumps(selection) + "\n")
        state_path = old_pilot / "state.json"
        state_path.write_text(json.dumps({
            "kind": "n6_b5_format_only_pilot_state", "status": "stopped",
            "request_index_sha256": runner.sha256(index_path),
            "selection_sha256": runner.sha256(selection_path),
            "engine_sha256": ENGINE_V22_SHA,
            "measurement_method": "wait4"}) + "\n")
        for ordinal, order in enumerate((9, 25)):
            path = (old_pilot / "requests" / f"{ordinal:02d}-{order:06d}" /
                    "lift/result.json")
            path.parent.mkdir(parents=True)
            value = result_record({"outcome": "error",
                                   "error_kind": "tool_or_unsupported",
                                   "note": pilot.DEVIATION_NOTE}) if order == 25 else result_record()
            path.write_text(json.dumps(value) + "\n")
        before = hashlib.sha256(state_path.read_bytes()).hexdigest()
        report_path = new_base / "v2-2-pilot-recheck.json"
        with (patch.object(pilot.b6e, "OUT", old_base),
              patch.object(pilot, "OLD_V22_PILOT", old_pilot),
              patch.object(pilot, "OUT", new_base),
              patch.object(runner, "run_lift", side_effect=AssertionError("J invoked")),
              patch.object(pilot.original, "run_format_pilot",
                           side_effect=AssertionError("pilot invoked"))):
            evidence = pilot.recheck_v22(index_path, runner.sha256(index_path),
                                         old_pilot, report_path)
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual([item["queue_order"] for item in evidence["requests"]], [9, 25])
        self.assertEqual(evidence["join_rechecked"], False)
        self.assertEqual(before, hashlib.sha256(state_path.read_bytes()).hexdigest())

    def test_inspection_failure_is_recorded_and_recovered(self) -> None:
        row = row_record()
        request_dir = self.root / "requests/000009"
        attempt_dir = request_dir / "attempt-0001"
        attempt_dir.mkdir(parents=True)
        result = result_record({"outcome": "error",
                                "error_kind": "tool_or_unsupported",
                                "note": "unexpected note"})
        result_path = attempt_dir / "result.json"
        result_path.write_text(json.dumps(result) + "\n")
        metrics = {"exit_code": 0, "max_rss_bytes": 100,
                   "wall_seconds": 1.0}
        (request_dir / "attempt-0001.metrics.json").write_text(
            json.dumps(metrics) + "\n")
        with patch.object(runner, "ENGINE_SHA256", ENGINE_V22_SHA):
            recovered = b6f._prior_zero_exit(row, request_dir)
            self.assertIsNotNone(recovered)
            path, attempt, measured, classification = recovered
            self.assertEqual(classification[0], "inspection_failure")
            event = b6f._record_result(row, "main", "rev", path, attempt,
                                       measured, classification)
            self.assertEqual(event["status"], "inspection_failure")
            self.assertEqual(event["result_path"], None)
            self.assertEqual(event["inspection_artifact_sha256"],
                             runner.sha256(result_path))
            b6f._check_resume(event, event, row["queue_order"])

    def test_fifth_inspection_failure_stops_and_restart_keeps_threshold(self) -> None:
        run_out = self.root / "runs"
        cache = self.root / "cache"
        output = run_out / "full-v1.noindex"
        output.mkdir(parents=True)
        (output / "state.json").write_text("{}\n")
        row = {**row_record(4), "preparation_failure": None}
        result_path = self.write_result(result_record(), "fifth-result.json")
        metrics = {"exit_code": 0, "max_rss_bytes": 100,
                   "wall_seconds": 1.0}
        state = {"schema_version": 1, "status": "running",
                 "requests": {str(order): {"status": "inspection_failure"}
                              for order in range(4)},
                 "revisions": {},
                 "format_checker_sha256": runner.sha256(
                     Path(pilot.__file__))}

        def load_state(_output: Path, _sha: str, _cache: Path) -> dict:
            return json.loads((output / "state.json").read_text()) if \
                (output / "state.json").read_text() != "{}\n" else state

        with (patch.object(b6f, "RUN_OUT", run_out),
              patch.object(b6f, "CACHE", cache),
              patch.object(b6f, "verify_both_pilots"),
              patch.object(b6f.external_paths, "require_external_root"),
              patch.object(b6f.external_paths, "install_full"),
              patch.object(runner, "ENGINE_SHA256", ENGINE_V1_SHA),
              patch.object(runner, "validate_index", return_value={"requests": [row]}),
              patch.object(runner, "load_state", side_effect=load_state),
              patch.object(runner, "probe_time_l",
                           return_value={"measurement_method": "wait4"}),
              patch.object(runner, "groups",
                           return_value=[("main", 1, "rev", [row])]),
              patch.object(b6f, "_prior_zero_exit",
                           return_value=(result_path, 1, metrics,
                                         ("inspection_failure", "format_invalid",
                                          "synthetic structure failure"))),
              patch.object(runner, "run_lift",
                           side_effect=AssertionError("request rerun")) as run_lift):
            with self.assertRaisesRegex(runner.RunnerError, "fifth inspection failure"):
                b6f.execute(self.root / "index.json", "i" * 64,
                            cache / "full-v1", output)
            saved = json.loads((output / "state.json").read_text())
            self.assertEqual(saved["status"], "inspection_failure_limit_reached")
            self.assertEqual(saved["inspection_failure_count"], 5)
            self.assertEqual(saved["requests"]["4"]["status"], "inspection_failure")
            self.assertEqual(saved["requests"]["4"]["inspection_artifact_sha256"],
                             runner.sha256(result_path))
            with self.assertRaisesRegex(runner.RunnerError, "already recorded"):
                b6f.execute(self.root / "index.json", "i" * 64,
                            cache / "full-v1", output)
            run_lift.assert_not_called()

    def test_first_inspection_failure_continues_to_next_request(self) -> None:
        run_out = self.root / "runs"
        cache = self.root / "cache"
        output = run_out / "full-v1.noindex"
        output.mkdir(parents=True)
        (output / "state.json").write_text("{}\n")
        bad_row = {**row_record(4), "preparation_failure": None}
        next_row = {**row_record(5),
                    "preparation_failure": "base_input_unavailable"}
        result_path = self.write_result(result_record(), "first-result.json")
        metrics = {"exit_code": 0, "max_rss_bytes": 100,
                   "wall_seconds": 1.0}
        unrelated = {str(order): {"status": "preparation_failure"}
                     for order in range(107) if order not in {4, 5}}
        state = {"schema_version": 1, "status": "running",
                 "requests": unrelated, "revisions": {},
                 "format_checker_sha256": runner.sha256(Path(pilot.__file__))}
        with (patch.object(b6f, "RUN_OUT", run_out),
              patch.object(b6f, "CACHE", cache),
              patch.object(b6f, "verify_both_pilots"),
              patch.object(b6f.external_paths, "require_external_root"),
              patch.object(b6f.external_paths, "install_full"),
              patch.object(runner, "ENGINE_SHA256", ENGINE_V1_SHA),
              patch.object(runner, "validate_index",
                           return_value={"requests": [bad_row, next_row]}),
              patch.object(runner, "load_state", return_value=state),
              patch.object(runner, "probe_time_l",
                           return_value={"measurement_method": "wait4"}),
              patch.object(runner, "groups",
                           return_value=[("main", 1, "rev", [bad_row, next_row])]),
              patch.object(b6f, "_prior_zero_exit",
                           return_value=(result_path, 1, metrics,
                                         ("inspection_failure", "format_invalid",
                                          "synthetic structure failure"))),
              patch.object(runner, "run_lift",
                           side_effect=AssertionError("request rerun")) as run_lift):
            completed = b6f.execute(self.root / "index.json", "i" * 64,
                                    cache / "full-v1", output)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["inspection_failure_count"], 1)
        self.assertEqual(completed["requests"]["4"]["status"],
                         "inspection_failure")
        self.assertEqual(completed["requests"]["5"]["status"],
                         "preparation_failure")
        run_lift.assert_not_called()


if __name__ == "__main__":
    unittest.main()
