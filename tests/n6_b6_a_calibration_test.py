"""Synthetic checks for the fixed A calibration comparison rules."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_b6_a_calibration as calibration  # noqa: E402


class ACalibrationSummaryTest(unittest.TestCase):
    def test_matrix_keeps_all_three_outcomes(self) -> None:
        matrix = calibration.matrix(
            ["L1", "excluded", "unknown", "L1"],
            ["excluded", "unknown", "L1", "L1"],
        )
        self.assertEqual(matrix["L1"], {"L1": 1, "excluded": 1, "unknown": 0})
        self.assertEqual(matrix["excluded"]["unknown"], 1)
        self.assertEqual(matrix["unknown"]["L1"], 1)

    def test_old_run_reads_only_selected_completed_requests(self) -> None:
        index = {"requests": [
            {"queue_order": 0, "scope": "main", "revision_id": "unselected"},
            {"queue_order": 1, "scope": "main", "revision_id": "selected"},
        ]}
        state = {"status": "completed", "requests": {"1": {"status": "completed"}}}
        completed = {"status": "completed", "l1": False,
                     "classes": [{"self_verdict": "excluded_in_context",
                                  "effective_verdict": None}]}
        with patch.object(calibration.summary, "load_revisions", return_value=({}, {})), \
                patch.object(calibration.summary, "summarize_request", return_value=completed) as mock:
            result = calibration.categories(index, state, Path("/tmp"), {1})
        self.assertEqual(result, {1: "excluded"})
        self.assertEqual(mock.call_count, 1)

    def test_reachable_or_compatible_is_not_proven_excluded(self) -> None:
        index = {"requests": [{"queue_order": 0, "scope": "main", "revision_id": "selected"}]}
        state = {"status": "completed", "requests": {"0": {"status": "completed"}}}
        for verdict in ("assumption_input_reachable", "compatible_no_top_violation_observed"):
            completed = {"status": "completed", "l1": False,
                         "classes": [{"self_verdict": verdict, "effective_verdict": None}]}
            with self.subTest(verdict=verdict), \
                    patch.object(calibration.summary, "load_revisions", return_value=({}, {})), \
                    patch.object(calibration.summary, "summarize_request", return_value=completed):
                self.assertEqual(calibration.categories(index, state, Path("/tmp")), {0: "unknown"})

    def test_effective_predicate_exclusion_counts_as_proven(self) -> None:
        index = {"requests": [{"queue_order": 0, "scope": "main", "revision_id": "selected"}]}
        state = {"status": "completed", "requests": {"0": {"status": "completed"}}}
        completed = {"status": "completed", "l1": False,
                     "classes": [{"self_verdict": "assumption_input_reachable",
                                  "effective_verdict": "assumption_excluded_in_context"}]}
        with patch.object(calibration.summary, "load_revisions", return_value=({}, {})), \
                patch.object(calibration.summary, "summarize_request", return_value=completed):
            self.assertEqual(calibration.categories(index, state, Path("/tmp")), {0: "excluded"})

    def test_active_b_pilot_blocks_a_j(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stages = Path(folder) / "stages"
            active = stages / "pilot-v2.2" / "state.json"
            active.parent.mkdir(parents=True)
            active.write_text('{"status":"running"}')
            with patch.object(calibration, "B6_STAGES", stages), \
                    patch.object(calibration, "S_STATE", Path(folder) / "missing.json"):
                with self.assertRaises(calibration.runner.RunnerError):
                    calibration.check_s_idle()


if __name__ == "__main__":
    unittest.main()
