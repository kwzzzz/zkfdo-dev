#!/usr/bin/env python3
"""Guards for the frozen N6-A1b preparation and preflight inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a1b-2026-10-08"
TARGETS = ROOT / "docs/n6_targets_a_2026-10-07.json"
TARGETS_SHA = "6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758"
SHORT_FIXES = {
    "0621e84", "1055906", "1763ca4", "3375335", "54d4d0a", "69db60e",
    "6dfcc56", "7ff5ba7", "8fdab18", "903edd3", "ccb2a8b",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class N6A1bTest(unittest.TestCase):
    def test_frozen_denominator_and_unretrievable_fixes(self) -> None:
        self.assertEqual(sha256(TARGETS), TARGETS_SHA)
        inventory = json.loads((RUN / "preparation-units.json").read_text())
        self.assertEqual(inventory["counts"]["development_units"], 12)
        self.assertEqual(inventory["counts"]["aq_stage1_units"], 41)
        self.assertEqual(inventory["counts"]["all_preparation_units"], 53)
        materialized = json.loads((RUN / "materialization-summary.json").read_text())
        short = {row["revision"] for row in materialized["units"]
                 if row.get("failure_type") == "fix_commit_unretrievable"}
        self.assertEqual(short, SHORT_FIXES)
        for row in materialized["units"]:
            if row["revision"] in SHORT_FIXES:
                self.assertEqual(row["status"], "not_started")
                self.assertFalse(row["rq_c_inclusion"])

    def test_preparation_has_no_zkfuzz_frontend_or_campaign(self) -> None:
        prepared = json.loads((RUN / "preparation-summary.json").read_text())
        self.assertEqual(len(prepared["units"]), 53)
        for row in prepared["units"]:
            self.assertEqual(row["zkfuzz_invocations"], 0)
        records = list(RUN.glob("*.json")) + list(RUN.glob("units/*/materialization.json")) + \
            list(RUN.glob("units/*/preparation/result.json"))
        for path in records:
            value = json.loads(path.read_text())
            if isinstance(value, dict) and "zkfuzz_invocations" in value:
                self.assertEqual(value["zkfuzz_invocations"], 0, path)
        self.assertFalse(any(RUN.rglob("zkfdo_report_counterexample.json")))

    def test_queue_budget_seed_and_preflight_only_contract(self) -> None:
        queue_path = RUN / "queue-v3.json"
        queue = json.loads(queue_path.read_text())
        self.assertEqual(queue["unit_count"], 84)
        self.assertEqual(queue["preflight_spec_count"], 168)
        self.assertEqual({row["seed"] for row in queue["units"]},
                         {2026100601, 2026100602, 2026100603})
        self.assertIn("preflight-only", (ROOT / "scripts/run_n6_a1b_queue.py").read_text())
        for unit in queue["units"]:
            for key, method, cap in (("whole_spec", "whole", 600),
                                     ("split_spec", "split", 30)):
                spec = json.loads((ROOT / unit[key]).read_text())
                self.assertEqual(spec["method"], method)
                self.assertEqual(spec["total_budget_seconds"], 600)
                self.assertEqual(spec["attempt_cap_seconds"], cap)
                self.assertEqual(spec["initial_seed"], unit["seed"])

    def test_original_library_roots_follow_workspace_roots(self) -> None:
        queue = json.loads((RUN / "queue-v3.json").read_text())
        for unit in queue["units"]:
            for key in ("whole_spec", "split_spec"):
                spec = json.loads((ROOT / unit[key]).read_text())
                for target in spec["targets"]:
                    command = target["preflight_compile_command"]
                    libraries = [command[index + 1] for index, token in enumerate(command[:-1])
                                 if token == "-l"]
                    recorded = list(dict.fromkeys(target["recorded_library_paths"]))
                    if recorded:
                        self.assertEqual(libraries[-len(recorded):], recorded)

    def test_official_evidence_and_full_sha_recovery_are_recorded(self) -> None:
        recovery = json.loads((RUN /
            "repositories/pantherfoundation__panther-core/acquisition-recovery.json").read_text())
        self.assertEqual(recovery["status"], "success")
        self.assertTrue(all(row["status"] == "present" for row in recovery["commits"]))
        materialized = json.loads((RUN / "materialization-summary.json").read_text())
        official = [row for row in materialized["units"] if row["branch"] == "A-Q-stage1"]
        self.assertEqual(len(official), 41)
        self.assertTrue(all(row["official_script"]["sha256"] for row in official))


if __name__ == "__main__":
    unittest.main()
