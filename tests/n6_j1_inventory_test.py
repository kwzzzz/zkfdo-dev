#!/usr/bin/env python3
"""Metadata-only checks for the N6-J1 candidate inventory."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_j1_inventory as inventory  # noqa: E402


class InventoryTest(unittest.TestCase):
    def test_selects_last_unpressured_run(self) -> None:
        unit = {
            "status": "completed_unpressured_retry",
            "selected_run_number": 3,
            "runs": [
                {"run_number": 1, "environment": {"environment_pressure": False}},
                {"run_number": 2, "environment": {"environment_pressure": True}},
                {"run_number": 3, "environment": {"environment_pressure": False}},
            ],
        }
        self.assertEqual(inventory.select_unpressured_run(unit)["run_number"], 3)

    def test_rejects_state_selection_that_is_not_last_unpressured(self) -> None:
        unit = {
            "status": "completed_unpressured_retry",
            "selected_run_number": 1,
            "runs": [
                {"run_number": 1, "environment": {"environment_pressure": False}},
                {"run_number": 2, "environment": {"environment_pressure": False}},
            ],
        }
        with self.assertRaises(inventory.InventoryError):
            inventory.select_unpressured_run(unit)

    def synthetic_campaign(self, root: Path) -> tuple[dict, dict, Path]:
        unit = {"unit_id": "u-s01", "identifier": "aq-035", "seed": 1}
        method_states = {}
        candidate_file = root / "run" / "units" / "u-s01" / "runs" / "01-primary" / "W" / "campaign" / "attempts" / "000000" / "candidate.json"
        candidate_file.parent.mkdir(parents=True)
        candidate_file.write_bytes(b'{"synthetic":true}\n')
        for method, stem in (("W", "whole"), ("S", "split")):
            spec_name = f"{stem}.json"
            spec = {"method": stem, "targets": [{"target_id": f"{method}-new", "source_snapshot_id": "snapshot"}]}
            spec_path = root / spec_name
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            unit[f"{stem}_spec"] = spec_name
            unit[f"{stem}_spec_sha256"] = inventory.sha256_file(spec_path)
            ledger_path = root / "run" / "units" / "u-s01" / "runs" / "01-primary" / method / "campaign" / "ledger.json"
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            candidates = ([{"path": "attempts/000000/candidate.json",
                            "sha256": inventory.sha256_file(candidate_file), "duplicate_of": None}]
                          if method == "W" else [])
            attempts = ([{"attempt_index": 0, "target_index": 0, "target_id": f"{method}-new",
                          "completion_offset_seconds": 2.5, "candidates": candidates}]
                        if method == "W" else [])
            ledger = {"status": "completed", "spec_sha256": unit[f"{stem}_spec_sha256"],
                      "method": stem, "attempts": attempts}
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            method_states[method] = {"status": "completed", "ledger": str(ledger_path.relative_to(root)),
                                     "ledger_sha256": inventory.sha256_file(ledger_path)}
        source = {
            "queue_name": Path("queue.json"), "queue_sha256": "0" * 64,
            "run_root": root / "run",
            "state": {"units": {"u-s01": {
                "status": "completed_unpressured", "selected_run_number": 1,
                "runs": [{"run_number": 1, "environment": {"environment_pressure": False},
                          "methods": method_states}],
            }}},
        }
        return source, unit, candidate_file

    def test_candidate_row_has_verified_metadata_and_original_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, unit, candidate_file = self.synthetic_campaign(root)
            rows = inventory.campaign_candidates(root, source, unit, "main", {"W-new": "W-old"}, set())
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["candidate_path"], str(candidate_file.resolve()))
            self.assertEqual(row["candidate_sha256"], inventory.sha256_file(candidate_file))
            self.assertEqual(row["candidate_index"], 0)
            self.assertEqual(row["completion_offset_seconds"], 2.5)
            self.assertEqual(row["source_snapshot_id"], "snapshot")
            self.assertEqual(row["original_target_id"], "W-old")

    def test_rejects_candidate_byte_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, unit, candidate_file = self.synthetic_campaign(root)
            candidate_file.write_bytes(b"changed")
            with self.assertRaises(inventory.InventoryError):
                inventory.campaign_candidates(root, source, unit, "main", {}, set())

    def test_rejects_repeated_candidate_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, unit, candidate_file = self.synthetic_campaign(root)
            with self.assertRaises(inventory.InventoryError):
                inventory.campaign_candidates(root, source, unit, "main", {},
                                              {inventory.sha256_file(candidate_file)})

    def test_preflight_library_paths_keep_order_and_substitute_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = {"preflight_compile_command": ["circom", "{entrypoint}", "-l", "{workspace}",
                                                    "-l", "{workspace}/src"]}
            self.assertEqual(inventory.preflight_library_paths(target, root),
                             [str(root.resolve()), str((root / "src").resolve())])


if __name__ == "__main__":
    unittest.main()
