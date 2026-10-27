#!/usr/bin/env python3
"""Synthetic lead-review gates; no B request or J output is opened."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import n6_b6_batch1x_prepare as batch  # noqa: E402


HEADER = (
    "| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | "
    "스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | "
    "Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |"
)


class ConstructedBatchLeadGateTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.constructed = self.root / "constructed-inputs"
        self.constructed.mkdir()
        self.input = self.constructed / "abcdef12" / "input.json"
        self.input.parent.mkdir()
        self.input.write_text('{"synthetic": 1}\n')
        self.digest = batch.sha256(self.input)
        self.full = "abcdef120000000000000000"
        self.base = {"revisions": {self.full: {
            "status": "passed", "base_input_path": str(self.input),
            "base_input_sha256": self.digest,
        }}}
        self.index = {"requests": [{"revision_id": self.full,
                                     "preparation_failure": None}]}
        self.table = self.root / "review-table.md"
        self.table.write_text("\n".join([
            HEADER,
            "|" + "---|" * 14,
            f"| abcdef12 | synthetic | test | {'a' * 64} | {self.digest} | "
            "on | no | test | passed | passed | passed | yes | 1 | none |",
        ]) + "\n")
        self.lead = self.root / "lead-input-review.json"

    def write_review(self, **changes: object) -> None:
        record = {"reviewed_table_sha256": batch.sha256(self.table),
                  "approved_revisions": ["abcdef12"], "reviewer": "lead",
                  "time_utc": "2026-10-18T00:00:00Z"}
        record.update(changes)
        self.lead.write_text(json.dumps(record) + "\n")

    def gate(self) -> set[str]:
        return batch.review_gate(self.base, self.index, lead_path=self.lead,
                                 table_path=self.table,
                                 constructed_root=self.constructed)

    def test_missing_review_stops_before_pilot(self) -> None:
        with self.assertRaisesRegex(ValueError, "lead input review record missing"):
            self.gate()

    def test_approved_input_requires_table_and_file_hashes(self) -> None:
        self.write_review()
        self.assertEqual(self.gate(), {self.full})
        self.input.write_text('{"synthetic": 2}\n')
        with self.assertRaisesRegex(ValueError, "approved input file/hash differs"):
            self.gate()

    def test_table_change_and_unapproved_callable_revision_stop(self) -> None:
        self.write_review()
        self.table.write_text(self.table.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "lead review table binding differs"):
            self.gate()
        self.write_review()
        self.index["requests"].append({"revision_id": "123456780000000000000000",
                                        "preparation_failure": None})
        with self.assertRaisesRegex(ValueError, "unapproved constructed input"):
            self.gate()

    def test_s_terminal_states_allow_work_but_running_blocks(self) -> None:
        s_state = self.root / "synthetic-s-state.json"
        a_state = self.root / "synthetic-a-state.json"
        with patch.object(batch, "S_STATE", s_state), patch.object(batch, "A_STATE", a_state):
            for status in ("completed", "stopped_between_units", "start_gate_failed",
                           "disk_guard"):
                s_state.write_text(json.dumps({"status": status}) + "\n")
                batch.s_idle()
            s_state.write_text('{"status":"running"}\n')
            with self.assertRaisesRegex(ValueError, "S prestart check or refuzz"):
                batch.s_idle()

    def test_pilot_rechecks_result_and_joined_instance_hashes(self) -> None:
        base = self.root / "base.json"
        selection = self.root / "selection.json"
        index = self.root / "request-index.json"
        output = self.root / "pilot.noindex"
        output.mkdir()
        base.write_text('{"synthetic": "base"}\n')
        selection.write_text('{"synthetic": "selection"}\n')
        index.write_text(json.dumps({"requests": [
            {"queue_order": 0, "request_sha256": "request-zero"},
            {"queue_order": 1, "request_sha256": "request-one"},
        ]}) + "\n")
        result_zero = output / "result-zero.json"
        result_one = output / "result-one.json"
        instances = output / "instances.json"
        for path in (result_zero, result_one, instances):
            path.write_text('{"synthetic": true}\n')
        requests = {}
        for order, path in enumerate((result_zero, result_one)):
            requests[str(order)] = {
                "queue_order": order, "request_sha256": f"request-{'zero' if order == 0 else 'one'}",
                "status": "completed", "exit_code": 0, "format_ok": True,
                "max_rss_bytes": 1, "result_path": str(path),
                "result_sha256": batch.sha256(path),
            }
        state = {
            "kind": "n6_b5_format_only_pilot_state", "status": "passed",
            "request_index_sha256": batch.sha256(index),
            "base_index_sha256": batch.sha256(base),
            "selection_sha256": batch.sha256(selection),
            "engine_sha256": batch.ENGINE_V1_SHA,
            "requests": requests,
            "revisions": {"synthetic": {
                "status": "joined", "format_ok": True, "exit_code": 0,
                "instances_path": str(instances),
                "instances_sha256": batch.sha256(instances),
            }},
        }
        (output / "state.json").write_text(json.dumps(state) + "\n")
        with patch.object(batch, "BASE", base), patch.object(batch, "SELECTION", selection):
            self.assertTrue(batch.pilot_state("v1", index, output)["format_ok"])
            result_zero.write_text('{"synthetic": false}\n')
            with self.assertRaisesRegex(ValueError, "pilot result file/hash differs"):
                batch.pilot_state("v1", index, output)
            result_zero.write_text('{"synthetic": true}\n')
            instances.write_text('{"synthetic": false}\n')
            with self.assertRaisesRegex(ValueError, "joined instance file/hash differs"):
                batch.pilot_state("v1", index, output)


class ConstructedBatchResultsGateTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.constructed = self.root / "constructed-inputs"
        self.constructed.mkdir()
        self.first_table = self.constructed / "review-table.md"
        self.second_table = self.constructed / "review-table-2.md"
        self.first_lead = self.root / "lead-input-review.json"
        self.second_lead = self.root / "lead-input-review-2.json"
        self.full = {short: short + "0" * 16 for short in
                     batch.FIRST_REVISIONS | batch.SECOND_REVISIONS}
        self.base = {"schema": "n6-j1-base-inputs-v1", "layer": "constructed",
                     "revisions": {"60271bae" + "0" * 16: {
                         "status": "base_input_unavailable", "base_input_path": None,
                         "base_input_sha256": None,
                     }}}
        self.digests: dict[str, str] = {}
        for short, identifier in self.full.items():
            if short in {"6079a717", "76053f7f"}:
                path = self.constructed / identifier / "input.json"
                path.parent.mkdir()
                path.write_text('{"synthetic": true}\n')
                digest = batch.sha256(path)
                self.base["revisions"][identifier] = {
                    "status": "passed", "base_input_path": str(path),
                    "base_input_sha256": digest,
                }
                self.digests[short] = digest
            else:
                self.base["revisions"][identifier] = {
                    "status": "base_input_unavailable", "base_input_path": None,
                    "base_input_sha256": None,
                }
        self.index = {"requests": [{"revision_id": self.full["6079a717"],
                                     "preparation_failure": None}]}
        self.write_table(self.first_table, batch.FIRST_REVISIONS)
        self.write_table(self.second_table, batch.SECOND_REVISIONS)
        self.write_lead(self.first_lead, self.first_table, ["6079a717"])
        self.write_lead(self.second_lead, self.second_table, ["76053f7f"])

    def write_table(self, path: Path, shorts: frozenset[str]) -> None:
        rows = [HEADER, "|" + "---|" * 14]
        for short in sorted(shorts):
            digest = self.digests.get(short, "없음")
            rows.append(f"| {short} | synthetic | test | {'a' * 64} | {digest} | "
                        "on | no | test | passed | passed | passed | yes | 1 | none |")
        path.write_text("\n".join(rows) + "\n")

    def write_lead(self, path: Path, table: Path, approved: list[str]) -> None:
        path.write_text(json.dumps({
            "reviewed_table_sha256": batch.sha256(table),
            "approved_revisions": approved, "reviewer": "lead",
            "time_utc": "2026-10-18T00:00:00Z",
        }) + "\n")

    def gate(self) -> None:
        batch.results_review_gate(
            self.base, self.index, first_table=self.first_table,
            first_lead=self.first_lead, second_table=self.second_table,
            second_lead=self.second_lead, constructed_root=self.constructed)

    def test_both_review_partitions_pass_with_no_request_second_revision(self) -> None:
        self.gate()

    def test_missing_second_review_stops_result_access(self) -> None:
        self.second_lead.unlink()
        with self.assertRaisesRegex(ValueError, "review table or lead record missing"):
            self.gate()

    def test_second_table_change_stops_result_access(self) -> None:
        self.second_table.write_text(self.second_table.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "result review table binding differs"):
            self.gate()

    def test_second_approved_input_hash_must_match_actual_file(self) -> None:
        path = Path(self.base["revisions"][self.full["76053f7f"]]["base_input_path"])
        path.write_text('{"synthetic": false}\n')
        with self.assertRaisesRegex(ValueError, "approved input file/hash differs"):
            self.gate()

    def test_no_request_passed_revision_must_be_approved(self) -> None:
        self.write_lead(self.second_lead, self.second_table, [])
        with self.assertRaisesRegex(ValueError, "unapproved available input"):
            self.gate()

    def test_second_table_must_cover_all_four_revisions(self) -> None:
        self.second_table.write_text("\n".join(
            line for line in self.second_table.read_text().splitlines()
            if "| 83cc0060 |" not in line) + "\n")
        self.write_lead(self.second_lead, self.second_table, ["76053f7f"])
        with self.assertRaisesRegex(ValueError, "does not cover its revision partition"):
            self.gate()

    def test_unavailable_second_input_cannot_claim_a_hash_in_table(self) -> None:
        self.digests["83cc0060"] = "b" * 64
        self.write_table(self.second_table, batch.SECOND_REVISIONS)
        self.write_lead(self.second_lead, self.second_table, ["76053f7f"])
        with self.assertRaisesRegex(ValueError, "unapproved available input"):
            self.gate()

    def test_full_engines_and_state_hash_required_before_result_access(self) -> None:
        first = self.root / "full-v2.2.json"
        second = self.root / "full-v1.json"
        def full_state(engine: str) -> dict[str, object]:
            name = f"full-{engine}"
            output = self.root / f"{name}.noindex"
            output.mkdir(exist_ok=True)
            output_state = output / "state.json"
            output_state.write_text('{"synthetic": true}\n')
            return {"stage": name, "engine": engine, "status": "completed",
                    "exit_code": 0, "request_count": 107,
                    "output": str(output),
                    "cache_root": str(batch.CACHE / name),
                    "state_sha256": batch.sha256(output_state)}
        first.write_text(json.dumps(full_state("v2.2")) + "\n")
        index = self.root / "index.json"
        index.write_text(json.dumps(self.index) + "\n")
        with patch.object(batch, "state_path", side_effect=lambda name: self.root / f"{name}.json"), \
             patch.object(batch, "index_summary", return_value={}), \
             patch.object(batch, "base_index", return_value=self.base), \
             patch.object(batch, "INDEX_V1", index), \
             patch.object(batch, "OUT", self.root), \
             patch.object(batch, "results_review_gate", return_value=None):
            with self.assertRaisesRegex(ValueError, "both full engines must finish"):
                batch.verify_results_gate()
            second.write_text(json.dumps(full_state("v2.2")) + "\n")
            with self.assertRaisesRegex(ValueError, "both full engines must finish"):
                batch.verify_results_gate()
            second.write_text(json.dumps(full_state("v1")) + "\n")
            batch.verify_results_gate()
            (self.root / "full-v1.noindex/state.json").write_text('{"synthetic": false}\n')
            with self.assertRaisesRegex(ValueError, "full J state file/hash differs"):
                batch.verify_results_gate()


class ReviewTableCorrectionTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.table = Path(temporary.name) / "review-table.md"
        self.old_digest = "a" * 64
        self.new_digest = "b" * 64
        self.original = self.table_text(self.old_digest).encode()
        self.table.write_bytes(self.original)
        self.original_sha = batch.sha256(self.table)

    @staticmethod
    def table_text(digest: str, *, omit: str | None = None,
                   duplicate: str | None = None) -> str:
        rows = [HEADER, "|" + "---|" * 14]
        for short in sorted(batch.FIRST_REVISIONS):
            if short == omit:
                continue
            rows.append(f"| {short} | synthetic | test | {'a' * 64} | {digest} | "
                        "on | no | test | passed | passed | passed | yes | 1 | none |")
            if short == duplicate:
                rows.append(rows[-1])
        return "\n".join(rows) + "\n"

    def append_correction(self, *, omit: str | None = None,
                          duplicate: str | None = None) -> None:
        self.table.write_bytes(
            self.original + batch.REVIEW_TABLE_CORRECTION_MARKER +
            b"Original SHA and correction reason recorded here.\n\n" +
            self.table_text(self.new_digest, omit=omit, duplicate=duplicate).encode())

    def parse(self) -> dict[str, str]:
        with patch.object(batch, "TABLE", self.table), \
             patch.object(batch, "REVIEW_TABLE_ORIGINAL_BYTES", len(self.original)), \
             patch.object(batch, "REVIEW_TABLE_ORIGINAL_SHA", self.original_sha):
            return batch.review_table_hashes(self.table)

    def test_append_only_correction_uses_complete_last_table(self) -> None:
        self.append_correction()
        self.assertEqual(self.table.read_bytes()[:len(self.original)], self.original)
        self.assertEqual(self.parse(), {
            short: self.new_digest for short in batch.FIRST_REVISIONS})

    def test_original_table_remains_valid_before_correction(self) -> None:
        self.assertEqual(self.parse(), {
            short: self.old_digest for short in batch.FIRST_REVISIONS})

    def test_correction_rejects_changed_original_prefix(self) -> None:
        self.append_correction()
        raw = bytearray(self.table.read_bytes())
        raw[10] = ord("X")
        self.table.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "original review table prefix changed"):
            self.parse()

    def test_correction_rejects_incomplete_or_duplicate_rows(self) -> None:
        self.append_correction(omit="340107e1")
        with self.assertRaisesRegex(ValueError, "complete revision table"):
            self.parse()
        self.append_correction(duplicate="340107e1")
        with self.assertRaisesRegex(ValueError, "complete revision table"):
            self.parse()

    def test_correction_rejects_unmarked_append(self) -> None:
        self.table.write_bytes(self.original + b"\nunmarked correction\n")
        with self.assertRaisesRegex(ValueError, "correction heading missing"):
            self.parse()


class ReviewTable2CorrectionTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.table = Path(temporary.name) / "review-table-2.md"
        self.original = self.table_text("a" * 64).encode()
        self.table.write_bytes(self.original)
        self.original_sha = batch.sha256(self.table)
        self.first_correction: bytes | None = None
        self.first_sha: str | None = None

    @staticmethod
    def table_text(digest: str, *, omit: str | None = None,
                   duplicate: str | None = None) -> str:
        rows = [HEADER, "|" + "---|" * 14]
        for short in sorted(batch.SECOND_REVISIONS):
            if short == omit:
                continue
            rows.append(f"| {short} | synthetic | test | {'a' * 64} | {digest} | "
                        "on | no | test | passed | passed | passed | yes | 1 | none |")
            if short == duplicate:
                rows.append(rows[-1])
        return "\n".join(rows) + "\n"

    def append_correction(self, *, omit: str | None = None,
                          duplicate: str | None = None) -> None:
        self.table.write_bytes(
            self.original + batch.REVIEW_TABLE_CORRECTION_MARKER +
            b"Original SHA and correction reason recorded here.\n\n" +
            self.table_text("b" * 64, omit=omit, duplicate=duplicate).encode())
        self.first_correction = self.table.read_bytes()
        self.first_sha = batch.sha256(self.table)

    def append_second_correction(self, *, omit: str | None = None,
                                 duplicate: str | None = None) -> None:
        assert self.first_correction is not None
        self.table.write_bytes(
            self.first_correction + batch.REVIEW_TABLE_SECOND_CORRECTION_MARKER +
            b"First correction SHA and transcription reason recorded here.\n\n" +
            self.table_text("c" * 64, omit=omit, duplicate=duplicate).encode())

    def parse(self) -> dict[str, str]:
        with patch.object(batch, "TABLE2", self.table), \
             patch.object(batch, "REVIEW_TABLE2_ORIGINAL_BYTES", len(self.original)), \
             patch.object(batch, "REVIEW_TABLE2_ORIGINAL_SHA", self.original_sha), \
             patch.object(batch, "REVIEW_TABLE2_FIRST_CORRECTION_BYTES",
                          len(self.first_correction) if self.first_correction else 11749), \
             patch.object(batch, "REVIEW_TABLE2_FIRST_CORRECTION_SHA",
                          self.first_sha or batch.REVIEW_TABLE2_FIRST_CORRECTION_SHA):
            return batch.review_table_hashes(self.table)

    def test_second_original_and_complete_correction(self) -> None:
        self.assertEqual(self.parse(), {
            short: "a" * 64 for short in batch.SECOND_REVISIONS})
        self.append_correction()
        self.assertEqual(self.table.read_bytes()[:len(self.original)], self.original)
        self.assertEqual(self.parse(), {
            short: "b" * 64 for short in batch.SECOND_REVISIONS})

    def test_second_correction_rejects_changed_prefix(self) -> None:
        self.append_correction()
        raw = bytearray(self.table.read_bytes())
        raw[10] = ord("X")
        self.table.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "original review table prefix changed"):
            self.parse()

    def test_second_correction_rejects_incomplete_or_duplicate_rows(self) -> None:
        self.append_correction(omit="77e0f2db")
        with self.assertRaisesRegex(ValueError, "complete revision table"):
            self.parse()
        self.append_correction(duplicate="77e0f2db")
        with self.assertRaisesRegex(ValueError, "complete revision table"):
            self.parse()

    def test_second_append_selects_final_four_rows_after_bad_first_sha(self) -> None:
        self.append_correction()
        assert self.first_correction is not None
        self.first_correction = self.first_correction.replace(b"b" * 64, b"b" * 62, 1)
        self.table.write_bytes(self.first_correction)
        self.first_sha = batch.sha256(self.table)
        self.append_second_correction()
        self.assertEqual(self.table.read_bytes()[:len(self.first_correction)],
                         self.first_correction)
        self.assertEqual(self.parse(), {
            short: "c" * 64 for short in batch.SECOND_REVISIONS})

    def test_second_append_rejects_changed_first_prefix(self) -> None:
        self.append_correction()
        self.append_second_correction()
        raw = bytearray(self.table.read_bytes())
        raw[len(self.original) + 5] = ord("X")
        self.table.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "second review table correction prefix changed"):
            self.parse()

    def test_second_append_rejects_incomplete_or_duplicate_final_rows(self) -> None:
        self.append_correction()
        self.append_second_correction(omit="77e0f2db")
        with self.assertRaisesRegex(ValueError, "complete revision table"):
            self.parse()
        self.append_second_correction(duplicate="77e0f2db")
        with self.assertRaisesRegex(ValueError, "complete revision table"):
            self.parse()


if __name__ == "__main__":
    unittest.main()
