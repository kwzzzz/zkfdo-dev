#!/usr/bin/env python3
"""Mock-only pilot selection, telemetry fallback, and stop checks."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_j1_pilot as pilot  # noqa: E402
import n6_j1_summarize as summary  # noqa: E402


def row(order: int, revision: str, method: str, *, seed: int = 1) -> dict:
    return {"scope": "main", "revision_id": revision, "method": method,
            "seed": seed, "queue_order": order, "request": f"/fake/{order}.json",
            "request_sha256": f"{order:064x}",
            "candidate_sha256": f"{order + 1:064x}",
            "preparation_failure": None}


class PilotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.output = self.root / "pilot-output"

    def selected_fixture(self) -> tuple[dict, dict, list[dict]]:
        rows = [
            row(0, "banyan-vulnerable", "W"),
            row(1, "aq-036-abc", "W"),
            row(2, "inference-original", "S"),
            row(3, "banyan-vulnerable", "S"),
            row(4, "aq-035-def", "S"),
            row(5, "zkemail-fpmul-vulnerable", "S"),
            row(6, "aq-036-abc", "S"),
            row(7, "aq-012-xyz", "S"),
        ]
        index = {"requests": rows}
        base = {"revisions": {
            "aq-036-abc": {"status": "passed", "constraints": 900},
            "aq-012-xyz": {"status": "passed", "constraints": 800},
        }}
        return index, base, pilot.select_requests(index, base)

    def test_selects_fixed_six_and_highest_constraint_aq_unique(self) -> None:
        index, base, selected = self.selected_fixture()
        self.assertEqual([item["queue_order"] for item in selected], list(range(7)))
        self.assertEqual(selected[6]["revision_id"], "aq-036-abc")
        self.assertEqual(selected[6]["method"], "S")
        # The first seed wins even if another seed's request appears earlier in the index.
        index["requests"].append(row(8, "aq-012-xyz", "S", seed=2))
        self.assertEqual(pilot.select_requests(index, base)[6]["queue_order"], 6)

    def test_probe_selects_wait4_and_lift_runs_once(self) -> None:
        request = row(0, "banyan-vulnerable", "W")
        output_dir = self.root / "one"

        def fake_probe(command, *, capture_output, text, check):
            return type("Exit", (), {"returncode": 1,
                                     "stderr": "sysctl kern.clockrate: Operation not permitted\n"})()

        def fake_wait4(command, stdout_path, stderr_path):
            target = Path(command[command.index("--output") + 1])
            target.mkdir()
            (target / "result.json").write_text("{}\n")
            stdout_path.write_text("")
            stderr_path.write_text("")
            return 0, 2.5, 4096

        with patch.object(pilot.subprocess, "run", side_effect=fake_probe) as time_call, \
                patch.object(pilot, "run_with_rusage", side_effect=fake_wait4) as child_call, \
                patch.object(pilot.runner, "ENGINE", self.root / "fake-engine"):
            probe = pilot.probe_time_l()
            result = pilot.run_one(request, output_dir, self.cache,
                                   self.root / "store", probe["measurement_method"])
        self.assertEqual(probe["measurement_method"], "wait4")
        self.assertIn("sysctl kern.clockrate", probe["time_probe_failure"])
        self.assertEqual(result["measurement_method"], "wait4")
        self.assertEqual(result["max_rss_bytes"], 4096)
        self.assertEqual(time_call.call_count, 1)
        self.assertEqual(child_call.call_count, 1)

    def test_stops_and_records_w_without_main_call_site(self) -> None:
        selected = [row(0, "banyan-vulnerable", "W")]

        def fake_run(request, run_dir, cache, store, measurement_method):
            run_dir.mkdir(parents=True)
            result_path = run_dir / "result.json"
            result_path.write_text(json.dumps({
                "request_sha256": request["request_sha256"],
                "candidate_sha256": request["candidate_sha256"],
                "preparation": {"status": "ok"}, "sites_found": 0,
                "verdict_counts": {},
            }) + "\n")
            return {"measurement_method": measurement_method,
                    "exit_code": 0, "wall_seconds": 1.0,
                    "max_rss_bytes": 1000, "result_path": str(result_path)}

        base = {"revisions": {"banyan-vulnerable": {"status": "passed"}}}
        with patch.object(pilot, "load_inputs", return_value=({}, base, selected)), \
                patch.object(pilot, "probe_time_l", return_value={
                    "measurement_method": "wait4", "time_probe_failure": "mock",
                    "exit_code": 1, "max_rss_bytes": None}), \
                patch.object(pilot, "check_selected_request"), \
                patch.object(pilot.runner, "check_disk", return_value={
                    "output_free_bytes": 100 * 1024**3,
                    "cache_free_bytes": 100 * 1024**3}), \
                patch.object(pilot.runner, "disk_free", return_value=100 * 1024**3), \
                patch.object(pilot, "run_one", side_effect=fake_run):
            with self.assertRaisesRegex(pilot.runner.RunnerError, "no main call site"):
                pilot.run_pilot(self.root / "index", "a" * 64, self.root / "base",
                                "b" * 64, self.cache, self.output)
        record = json.loads((self.output / "pilot.json").read_text())
        self.assertEqual(record["status"], "stopped")
        self.assertEqual(record["stop_pilot_order"], 0)
        self.assertEqual(record["requests"][0]["sites_found"], 0)

    def test_s_preparation_failure_recorded_and_other_samples_continue(self) -> None:
        selected = [row(0, "inference-original", "S")]
        selected[0]["preparation_failure"] = "base_input_unavailable"
        with patch.object(pilot, "load_inputs", return_value=({}, {}, selected)), \
                patch.object(pilot, "probe_time_l", return_value={
                    "measurement_method": "wait4", "time_probe_failure": "mock",
                    "exit_code": 1, "max_rss_bytes": None}), \
                patch.object(pilot, "run_one") as engine:
            pilot.run_pilot(self.root / "index", "a" * 64, self.root / "base",
                            "b" * 64, self.cache, self.output)
        engine.assert_not_called()
        record = json.loads((self.output / "pilot.json").read_text())
        self.assertEqual(record["status"], "failed_criteria")
        self.assertEqual(record["selected_queue_orders"], [0])
        self.assertEqual(record["requests"][0]["preparation_failure"],
                         "base_input_unavailable")
        state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(state["revisions"]["main/0001"]["status"], "no_results")

    def test_unavailable_first_w_stops_before_later_lifts(self) -> None:
        selected = [row(0, "banyan-vulnerable", "W"),
                    row(1, "inference-original", "S")]
        selected[0]["preparation_failure"] = "base_input_unavailable"
        base = {"revisions": {"inference-original": {"status": "passed"}}}
        with patch.object(pilot, "load_inputs", return_value=({}, base, selected)), \
                patch.object(pilot, "probe_time_l", return_value={
                    "measurement_method": "wait4", "time_probe_failure": "mock",
                    "exit_code": 1, "max_rss_bytes": None}), \
                patch.object(pilot, "run_one") as engine:
            with self.assertRaisesRegex(pilot.runner.RunnerError,
                                        "pilot W preparation failure"):
                pilot.run_pilot(self.root / "index", "a" * 64, self.root / "base",
                                "b" * 64, self.cache, self.output)
        engine.assert_not_called()
        record = json.loads((self.output / "pilot.json").read_text())
        self.assertEqual(record["status"], "stopped")
        self.assertEqual(record["stop_pilot_order"], 0)
        self.assertEqual(len(record["requests"]), 1)
        state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(state["requests"]["0"]["status"], "preparation_failure")
        self.assertNotIn("1", state["requests"])

    def test_join_failure_stops_without_instance_output(self) -> None:
        result_path = self.output / "requests/one/result.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_text("{}\n")
        instance_path = self.output / "revisions/01/instances.json"
        instance_path.parent.mkdir(parents=True)
        with patch.object(pilot.runner, "checked_sha"), \
                patch.object(pilot.subprocess, "run", return_value=type(
                    "Exit", (), {"returncode": 1})()):
            with self.assertRaisesRegex(pilot.runner.RunnerError, "lift-instances failed"):
                pilot.join_pilot_revision([result_path], self.output, instance_path)
        self.assertFalse(instance_path.exists())

    def test_join_conflict_rejected(self) -> None:
        result_path = self.output / "requests/one/result.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_text("{}\n")
        instance_path = self.output / "revisions/01/instances.json"
        instance_path.parent.mkdir(parents=True)

        def fake_join(command, *, cwd, stdout, stderr, check):
            instance_path.write_text(json.dumps({
                "schema": "zkfdo-instance-verdicts-v1",
                "results": [str(result_path.relative_to(self.output))],
                "conflicts": 1,
            }) + "\n")
            return type("Exit", (), {"returncode": 0})()

        with patch.object(pilot.runner, "checked_sha"), \
                patch.object(pilot.subprocess, "run", side_effect=fake_join):
            with self.assertRaisesRegex(pilot.runner.RunnerError, "joined results mismatch"):
                pilot.join_pilot_revision([result_path], self.output, instance_path)

    def test_pilot_state_and_join_feed_partial_summary(self) -> None:
        skipped = row(0, "aq-001", "S")
        skipped["preparation_failure"] = "base_input_unavailable"
        ready = row(1, "aq-001", "W")
        for item in (skipped, ready):
            item.update({"unit_id": "aq-001-s01", "attempt_number": 1,
                         "candidate_index": 0,
                         "completion_offset_seconds": float(item["queue_order"] + 2),
                         "target_id": f"{item['method']}-target",
                         "original_target_id": None,
                         "candidate_path": str(self.root / f"candidate-{item['method']}.json")})
        index = {"schema_version": 1, "status": "verified", "request_count": 2,
                 "requests": [skipped, ready]}
        base = {"revisions": {"aq-001": {"status": "passed", "constraints": 10}}}
        index_path = self.root / "index.json"
        index_path.write_text(json.dumps(index) + "\n")
        prep_path = self.root / "preparation.json"
        prep_path.write_text(json.dumps({"aq_stage1_units": [
            {"unit_id": "aq-001", "item_ids": ["item"],
             "revision_kind": "fixed", "leave_one_out": None}]}) + "\n")
        targets_path = self.root / "targets.json"
        targets_path.write_text(json.dumps({"items": [
            {"id": "item", "location": {"Function": "LessThan"}}]}) + "\n")
        rq_c_map_path = self.root / "rq-c-map.json"
        rq_c_map_path.write_text(json.dumps({
            "status": "verified", "mapping_scope": "selected_aq_revisions",
            "preparation_units_sha256": pilot.runner.sha256(prep_path),
            "targets_sha256": pilot.runner.sha256(targets_path),
            "revisions": [{"revision_id": "aq-001", "mapping_basis": "mock_capture",
                           "items": [{"item_id": "item", "status": "mapped",
                                      "instance_paths": ["main.LessThan[0]"],
                                      "missing_templates": []}]}],
        }) + "\n")
        main_queue = self.root / "main-queue.json"
        main_queue.write_text(json.dumps({"units": [
            {"unit_id": "aq-001-s01", "identifier": "aq-001", "seed": 1}]}) + "\n")
        mem_queue = self.root / "mem20-queue.json"
        mem_queue.write_text('{"units": []}\n')

        def fake_run(request, run_dir, cache, store, measurement_method):
            result_path = run_dir / "lift/result.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_text(json.dumps({
                "schema": "zkfdo-lifting-result-v1", "request_id": "request-s",
                "request_sha256": request["request_sha256"],
                "candidate_sha256": request["candidate_sha256"],
                "preparation": {"status": "ok", "reason": None},
                "sites_found": 1,
                "classes": [{"representative": "main.LessThan[0]",
                             "verdict": "assumption_input_reachable",
                             "assumption_predicate_verdict": "assumption_violation_reachable",
                             "predicates": [{"verdict": "assumption_violation_reachable",
                                             "reach_inputs": {"classification": "private_only"}}]}],
                "costs": {"steps": []},
            }) + "\n")
            return {"measurement_method": measurement_method, "exit_code": 0,
                    "wall_seconds": 3.0, "max_rss_bytes": 1024,
                    "result_path": str(result_path)}

        def fake_join(paths, output, instance_path):
            instance_path.write_text(json.dumps({
                "schema": "zkfdo-instance-verdicts-v1",
                "results": [str(path.relative_to(output)) for path in paths],
                "conflicts": 0,
                "classes": [{"request_id": "request-s",
                             "representative": "main.LessThan[0]",
                             "own": "assumption_violation_reachable",
                             "effective": "assumption_violation_reachable",
                             "target_basis": "broken_by_candidate"}],
                "instances": [{"instance": "main.LessThan[0]", "entry_key": "hash-key",
                               "verdict": "assumption_violation_reachable",
                               "reach_classification": "private_only"}],
            }) + "\n")
            return {"exit_code": 0, "wall_seconds": 0.1}

        with patch.object(pilot, "load_inputs", return_value=(index, base, [skipped, ready])), \
                patch.object(pilot, "probe_time_l", return_value={
                    "measurement_method": "wait4", "time_probe_failure": "mock",
                    "exit_code": 1, "max_rss_bytes": None}), \
                patch.object(pilot, "check_selected_request"), \
                patch.object(pilot.runner, "check_disk", return_value={
                    "output_free_bytes": 100 * 1024**3,
                    "cache_free_bytes": 100 * 1024**3}), \
                patch.object(pilot.runner, "disk_free", return_value=100 * 1024**3), \
                patch.object(pilot, "run_one", side_effect=fake_run), \
                patch.object(pilot, "join_pilot_revision", side_effect=fake_join):
            record = pilot.run_pilot(index_path, "a" * 64, self.root / "base",
                                     "b" * 64, self.cache, self.output)
        self.assertEqual(record["status"], "failed_criteria")
        state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(state["requests"]["0"]["status"], "preparation_failure")
        self.assertEqual(state["requests"]["1"]["status"], "completed")
        self.assertEqual(state["revisions"]["main/0001"]["status"], "joined")
        aggregate = summary.build_summary(index_path, self.output, prep_path,
                                          targets_path, main_queue, mem_queue,
                                          rq_c_map_path)
        self.assertEqual(aggregate["counts"]["completed_results"], 1)
        self.assertEqual(aggregate["counts"]["preparation_failures"], 1)
        self.assertEqual(aggregate["counts"]["joined_revisions"], 1)


if __name__ == "__main__":
    unittest.main()
