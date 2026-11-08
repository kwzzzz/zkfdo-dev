#!/usr/bin/env python3
"""Small contract tests. No real J, fuzzing, image access or large compile."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import s_round4c_postdeadline_20261027 as runner
import s_round4c_strict_score_20261027 as scorer


class Contract(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="zkfdo-round4c-contract-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        output = root / "output"
        output.mkdir()
        for module in (runner, runner.protocol):
            for name, value in (("ROOT", root), ("OUT", output)):
                context = patch.object(module, name, value)
                context.start()
                self.addCleanup(context.stop)

    BEFORE = datetime(2026, 10, 28, 14, 59, tzinfo=timezone.utc)
    AFTER = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)

    @staticmethod
    def aq_state(status="completed", **changes):
        state = {"schema": "n6-a-remeasure-aq-execute-v3", "status": status,
                 "engines": {"v2.2": {"requests": {}}, "v1": {"requests": {}}},
                 "cleanup_receipts": []}
        if status == "completed":
            state["finished_at"] = "2026-10-28T14:58:00+00:00"
        else:
            state.update({"stopped_at": "2026-10-28T14:58:00+00:00",
                          "stop_kind": "deadline" if status == "deadline" else "interrupted",
                          "stop_reason": "no new segment at/after the UTC deadline" if status == "deadline"
                          else "signal 15; request saved"})
            state["status"] = "stopped"
        state.update(changes)
        return state

    def test_final_aq_states_and_early_start_flag(self):
        for state in (self.aq_state(), self.aq_state("deadline"), self.aq_state("signal")):
            with self.subTest(state=state.get("stop_kind", "completed")):
                with self.assertRaises(ValueError):
                    runner.validate_aq_state(state, now=self.BEFORE)
                self.assertIs(runner.validate_aq_state(
                    state, now=self.BEFORE, aq_stopped_by_miiz=True), state)
                self.assertIs(runner.validate_aq_state(state, now=self.AFTER), state)

        bad = [self.aq_state("error", stop_kind="error", stop_reason="engine failed"),
               self.aq_state("signal", stop_reason="signal 15; disk wait interrupted"),
               self.aq_state("signal", stop_reason="signal 15; stopped between requests"),
               self.aq_state("signal", stopped_at=None),
               self.aq_state("signal", engines={"v2.2": {"requests": {
                   "2209": {"status": "running"}}}, "v1": {"requests": {}}})]
        for state in bad:
            with self.subTest(reason=state.get("stop_reason")):
                with self.assertRaises(ValueError):
                    runner.validate_aq_state(state, now=self.AFTER)

    def test_aq_state_capture_preserves_start_bytes_and_checks_process_first(self):
        runner.OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runner.OUT) as name:
            folder = Path(name)
            source, target = folder / "state-v3_2.json", folder / "state-at-start.json"
            raw = json.dumps(self.aq_state("signal"), separators=(",", ":")).encode() + b"\n"
            source.write_bytes(raw)
            with patch.object(runner, "quiet_host", side_effect=ValueError("aq active")):
                with self.assertRaisesRegex(ValueError, "aq active"):
                    runner.capture_aq_state(target, source=source, now=self.BEFORE,
                                            aq_stopped_by_miiz=True)
            self.assertFalse(target.exists())
            with patch.object(runner, "quiet_host"):
                with self.assertRaises(ValueError):
                    runner.capture_aq_state(target, source=source, now=self.BEFORE)
                self.assertFalse(target.exists())
                pin, state = runner.capture_aq_state(target, source=source, now=self.BEFORE,
                                                     aq_stopped_by_miiz=True)
            self.assertEqual(target.read_bytes(), raw)
            self.assertEqual(pin["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(state["status"], "stopped")
            receipt = json.loads(Path(pin["receipt"]["path"]).read_text())
            self.assertEqual(receipt["source_sha256"], pin["sha256"])
            self.assertEqual(receipt["snapshot_sha256"], pin["sha256"])
            source.write_text("{}\n")
            self.assertEqual(target.read_bytes(), raw)

    def test_saved_aq_request_hashes_must_match(self):
        runner.OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runner.OUT) as name:
            folder = Path(name)
            metrics, result = folder / "metrics.json", folder / "result.json"
            metrics.write_text('{"wall_seconds":1}\n')
            result.write_text('{"preparation":{"status":"ok"}}\n')
            pin = lambda path: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            state = self.aq_state("signal")
            state["engines"]["v2.2"]["requests"]["1"] = {
                "status": "completed", "metrics_path": str(metrics),
                "metrics_sha256": pin(metrics)["sha256"],
                "result_path": str(result), "result_sha256": pin(result)["sha256"]}
            self.assertIs(runner.validate_aq_state(state, now=self.AFTER), state)
            result.write_text('{}\n')
            with self.assertRaises(ValueError):
                runner.validate_aq_state(state, now=self.AFTER)

    def test_image_gate_has_no_absolute_time_condition(self):
        fake = runner.OUT / "fake-image"
        fake.mkdir(parents=True, exist_ok=True)
        answer = runner.image_gate(100, 0, mount=fake,
                                   free_bytes=lambda _: 100 * runner.GIB,
                                   is_mount=lambda _: True)
        self.assertEqual(answer["image_free_bytes"], 100 * runner.GIB)

    def test_fake_mount_and_df_space(self):
        fake = runner.OUT / "fake-image"
        fake.mkdir(parents=True, exist_ok=True)
        peak = 400 * runner.GIB
        reserve = 5 * runner.GIB
        needed = runner.required_image_bytes(peak, reserve)
        answer = runner.image_gate(peak, reserve, mount=fake, free_bytes=lambda _: needed,
                                   is_mount=lambda _: True)
        self.assertEqual(answer["image_required_bytes"], needed)
        with self.assertRaisesRegex(ValueError, "image free"):
            runner.image_gate(peak, reserve, mount=fake, free_bytes=lambda _: needed - 1,
                              is_mount=lambda _: True)

    def test_replay_selection_has_no_bug_field(self):
        runner.OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runner.OUT) as name:
            folder = Path(name)
            request = folder / "request.json"
            result = folder / "result.json"
            payload = folder / "candidate.json"
            request.write_text('{"schema":"zkfdo-lifting-request-v1"}\n')
            request_sha = hashlib.sha256(request.read_bytes()).hexdigest()
            result.write_text(json.dumps({"request_sha256": request_sha,
                                          "preparation": {"status": "ok"}}))
            payload.write_text("{}\n")
            pin = lambda path: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            rows = []
            state = self.aq_state()
            for revision, count in (("banyan-fixed", 24), ("banyan-vulnerable", 108), ("aq-01", 7)):
                for index in range(count):
                    aq = revision.startswith("aq")
                    queue = 100 + index if aq else index
                    peak = (count - index) * runner.GIB
                    row = {"corpus": "aq" if aq else "banyan",
                                 "revision": revision, "method": "S", "queue_order": queue,
                                 "status": "completed", "recorded_wall_seconds": 1,
                                 "recorded_peak_bytes": peak,
                                 "request": pin(request), "completed_result": pin(result), "inputs": [pin(payload)]}
                    if aq:
                        row["engine"] = "v2.2"
                        state["engines"]["v2.2"]["requests"][str(queue)] = {
                            "status": "completed", "queue_order": queue,
                            "request_sha256": row["request"]["sha256"],
                            "result_sha256": row["completed_result"]["sha256"]}
                        state["cleanup_receipts"].append({
                            "binding": {"engine": "v2.2", "queue_order": queue,
                                        "request_sha256": row["request"]["sha256"]},
                            "du_bytes": peak})
                    rows.append(row)
            state["cleanup_receipts"].append({
                "binding": {"engine": "v2.2", "queue_order": 100,
                            "request_sha256": rows[-7]["request"]["sha256"],
                            "kind": "caches"},
                "du_bytes": 1000 * runner.GIB})
            # The lowest peak has no completed aq event; the next one has a
            # mismatched inventory peak. Neither can enter the fixed five.
            state["engines"]["v2.2"]["requests"]["106"]["status"] = "failed"
            rows[-2]["recorded_peak_bytes"] += 1
            selected = runner.select_replay({"schema": "s-round4c-replay-inventory-v1", "rows": rows}, state)
            self.assertEqual(len(selected), 137)
            self.assertEqual([r["queue_order"] for r in selected[-5:]], [104, 103, 102, 101, 100])

    def test_only_adjudicated_historical_sha_is_skipped(self):
        runner.OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runner.OUT) as name:
            folder = Path(name)
            pin = lambda path: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            judged_candidate = folder / "judged-candidate.json"
            judged_candidate.write_text('{"old":true}\n')
            unjudged_candidate = folder / "unjudged-candidate.json"
            unjudged_candidate.write_text('{"old":false}\n')
            judged, unjudged = pin(judged_candidate)["sha256"], pin(unjudged_candidate)["sha256"]
            result = folder / "old-result.json"
            result.write_text(json.dumps({"candidate_sha256": judged,
                                          "preparation": {"status": "ok"},
                                          "classes": [], "verdict_counts": {}}))
            inventory = {"complete": True, "rows": [
                {"sha256": judged, "status": "judged", "completed_result": pin(result)},
                {"sha256": unjudged, "status": "unjudged"}]}
            self.assertEqual(runner.judged_old_hashes(inventory), {judged})
            bad = json.loads(json.dumps(inventory))
            bad["rows"][0]["sha256"] = "c" * 64
            with self.assertRaises(ValueError):
                runner.judged_old_hashes(bad)

            inventory_path = folder / "inventory.json"
            inventory_path.write_text(json.dumps(inventory))
            ledger = folder / "S-ledger.json"
            ledger.write_text(json.dumps({"attempts": [{"candidates": [
                {"sha256": judged}, {"sha256": unjudged}]}]}))
            requests = [{"candidate": pin(candidate), "S_ledger": pin(ledger)}
                        for candidate in (judged_candidate, unjudged_candidate, unjudged_candidate)]
            bundle = folder / "new-J-plan.json"
            bundle.write_text(json.dumps({"old_candidate_inventory": pin(inventory_path),
                                          "requests": requests}))
            with patch.object(runner, "ROUND", runner.OUT), \
                    patch.object(runner, "execute_j", return_value={"request": pin(unjudged_candidate)}) as execute:
                outcome = runner.new_j({"new_J_plan": pin(bundle), "new_j_expected_seconds_per_request": 1},
                                       runner.PostMonitor({}), folder)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual([r["status"] for r in outcome["requests"]],
                             ["old_or_duplicate", "completed", "old_or_duplicate"])
            self.assertEqual(outcome["requests"][0]["skip_reason"], "historical_judged")
            self.assertEqual(outcome["requests"][0]["historical_result"], pin(result))
            self.assertTrue(outcome["requests"][1]["historical_unjudged"])
            self.assertEqual(outcome["requests"][2]["skip_reason"], "current_batch_duplicate")

    def test_v23_envelope_preserves_scoring_fields(self):
        result = json.loads((runner.ROUND / "round4b/synthetic-final/view/j-output/result.json").read_text())
        compatible = scorer.validate_result(result)
        self.assertEqual(compatible["schema"], "zkfdo-lifting-result-v1")
        self.assertEqual(compatible["classes"], result["classes"])
        self.assertEqual(compatible["request_sha256"], result["request_sha256"])

    def test_cleanup_uses_a_dedicated_fake_image_tree(self):
        runner.OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runner.OUT) as name:
            base = Path(name)
            fake = base / "fake-image"
            request = fake / "request-0000"
            (request / "cache").mkdir(parents=True)
            (request / "cache" / "generated.bin").write_bytes(b"generated")
            receipt = runner.cleanup.cleanup_tree(request, fake, base / "receipts",
                                                  {"request_sha256": "synthetic"}, False)
            self.assertEqual(receipt["status"], "deleted")
            self.assertFalse(request.exists())
            self.assertTrue(Path(receipt["before_path"]).is_file())
            self.assertTrue(Path(receipt["after_path"]).is_file())

    def test_j_cleanup_never_targets_aq_cache_or_judging_folder(self):
        runner.OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runner.OUT) as name:
            folder = Path(name)
            output, image = folder / "round4c-output", folder / "round4c-image"
            aq_cache = folder / "aq-cache"
            aq_cache.mkdir()
            sentinel = aq_cache / "keep.bin"
            sentinel.write_bytes(b"aq remains resumable")
            candidate = folder / "candidate.json"
            candidate.write_text("{}\n")
            request = folder / "request.json"
            source_root = folder / "sources"
            source_root.mkdir()
            request.write_text(json.dumps({"schema": "zkfdo-lifting-request-v1",
                                           "source_root": str(source_root),
                                           "candidate": {"path": str(candidate)}}))
            pin = lambda path: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            row = {"request": pin(request), "inputs": [pin(candidate)],
                   "recorded_peak_bytes": runner.GIB, "retained_image_bytes": 0,
                   "recorded_internal_peak_bytes": runner.GIB, "retained_internal_bytes": 0}
            cleanup_targets = []

            def fake_run(_argv, _label):
                result = image / "request-0000/result/result.json"
                result.parent.mkdir(parents=True)
                result.write_text('{"preparation":{"status":"ok"}}\n')
                return {"status": "completed", "receipt": {"path": str(folder / "run.json")}}

            def fake_cleanup(target, boundary, _records, _binding, _retain):
                cleanup_targets.append((target, boundary))
                self.assertEqual(boundary, image)
                self.assertEqual(target, image / "request-0000")
                self.assertFalse(target.is_relative_to(aq_cache))
                return {"before_path": str(folder / "before.json"), "before_sha256": "before",
                        "after_path": str(folder / "after.json"), "after_sha256": "after",
                        "freed_du_bytes": 0}

            class Monitor:
                run = staticmethod(fake_run)

            with patch.object(runner, "OUT", output), patch.object(runner, "IMAGE", image), \
                 patch.object(runner, "image_gate", return_value={}), \
                 patch.object(runner, "internal_gate", return_value={}), \
                 patch.object(runner, "j_command", return_value=["fake-J"]), \
                 patch.object(runner.cleanup, "cleanup_tree", side_effect=fake_cleanup):
                runner.execute_j({"aq_observed_peak_bytes": runner.GIB}, row, 0, Monitor(), "synthetic")
            self.assertEqual(cleanup_targets, [(image / "request-0000", image)])
            self.assertEqual(sentinel.read_bytes(), b"aq remains resumable")

    def test_postdeadline_monitor_keeps_30_20_18_and_target_gates(self):
        monitor = runner.PostMonitor({})
        with patch.object(runner, "quiet_host"), \
             patch.object(runner.os, "getpriority", return_value=19), \
             patch.object(monitor, "free_bytes", return_value=29 * runner.GIB), \
             patch.object(monitor, "target_bytes", return_value=0):
            with self.assertRaisesRegex(ValueError, "30 GiB"):
                monitor.gate(cargo=True)
        with patch.object(runner, "quiet_host"), \
             patch.object(runner.os, "getpriority", return_value=19), \
             patch.object(monitor, "free_bytes", return_value=30 * runner.GIB), \
             patch.object(monitor, "target_bytes", return_value=8 * runner.GIB + 1):
            with self.assertRaisesRegex(ValueError, "8 GiB"):
                monitor.gate(cargo=True)
        with patch.object(runner, "quiet_host"), \
             patch.object(runner.os, "getpriority", return_value=19), \
             patch.object(monitor, "free_bytes", return_value=30 * runner.GIB), \
             patch.object(monitor, "target_bytes", return_value=0):
            monitor.gate(cargo=True)
        with patch.object(runner, "quiet_host"), \
             patch.object(runner.os, "getpriority", return_value=19), \
             patch.object(monitor, "free_bytes", return_value=19 * runner.GIB):
            with self.assertRaisesRegex(ValueError, "20 GiB"):
                monitor.gate()


if __name__ == "__main__":
    unittest.main()
