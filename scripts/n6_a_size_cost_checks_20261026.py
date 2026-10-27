#!/usr/bin/env python3
"""In-memory saved-result aggregation tests; no engine or run data access."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_a_size_cost_j_20261026 as cost


class SavedCostTests(unittest.TestCase):
    def setUp(self):
        self.index = {"requests": [], "request_count": 0, "engine_sha256": "engine"}
        self.state = {"requests": {}, "engine_sha256": "engine"}
        self.results = {}
        self.opened = []
        self.joins = {}
        self.mapping = {"revisions": [{"revision_id": "mapped", "entrypoint_sha256": "entry",
            "items": [{"item_id": "bug", "instance_paths": ["main.bug"]}]}]}

    def add(self, classes=None, *, revision="mapped", method="S", status="completed",
            time=1.0, scope="main", history=None):
        queue = len(self.index["requests"])
        path = Path(f"/synthetic/{queue}/result.json")
        row = {"queue_order": queue, "revision_id": revision, "method": method,
            "scope": scope, "entrypoint_sha256": "entry", "request_sha256": f"request-{queue}"}
        event = {"queue_order": queue, "revision_id": revision, "status": status,
            "request_sha256": row["request_sha256"], "attempt": 2 if history else 1,
            "result_path": str(path), "result_sha256": f"result-{queue}", "wall_seconds": time}
        if history:
            event["history"] = history
        result = {"schema": "zkfdo-lifting-result-v1", "request_id": f"id-{queue}",
            "request_sha256": row["request_sha256"], "classes": classes or [],
            "entrypoint": {"r1cs_sha256": "a", "sym_sha256": "b", "o0_r1cs_sha256": "c"}}
        self.index["requests"].append(row)
        self.index["request_count"] += 1
        self.state["requests"][str(queue)] = event
        self.results[path] = (event["result_sha256"], result)
        return row, event, result

    def read(self, path, expected):
        self.opened.append(path)
        sha, result = self.results[path]
        self.assertEqual(expected, sha)
        return result

    def summarize(self):
        return cost.summarize_j(self.index, self.state, self.joins, self.mapping,
                                self.read, layer="strict", engine="v1")

    @staticmethod
    def own(name, verdict="entrypoint_violation"):
        return {"representative": name, "verdict": verdict}

    def test_location_flags_overlap_but_unmapped_is_not_other(self):
        self.add([self.own("main.bug")])
        self.add([self.own("main.other")])
        self.add([self.own("main.bug"), self.own("main.other")])
        self.add([self.own("main")], revision="unmapped")
        total = self.summarize()["totals"]
        self.assertEqual(total["L1_requests"], 4)
        self.assertEqual(total["bug_location_L1_requests"], 2)
        self.assertEqual(total["other_L1_requests"], 2)
        self.assertEqual(total["unassigned_L1_requests"], 1)

    def test_empty_mapping_roots_cannot_establish_other_location(self):
        self.add([self.own("main")])
        self.mapping["revisions"][0]["items"][0]["instance_paths"] = []
        total = self.summarize()["totals"]
        self.assertEqual(total["unassigned_L1_requests"], 1)
        self.assertEqual(total["other_L1_requests"], 0)

    def test_any_exclusion_keeps_existing_precedence_and_prep_failure_separate(self):
        self.add([self.own("main.bug", "excluded_in_context"), self.own("main.other", "unknown")])
        self.add([self.own("main.bug", "unknown")])
        self.add(status="preparation_failure", time=None)
        value = self.summarize()
        self.assertEqual(value["totals"]["excluded_requests"], 1)
        self.assertEqual(value["totals"]["unknown_requests"], 1)
        self.assertEqual(value["totals"]["wall_seconds"]["untimed_requests"], 1)
        self.assertEqual(len(self.opened), 2)
        zero = next(row for row in value["revision_methods"] if row["method"] == "W")
        self.assertEqual(zero["requests"], 0)
        self.assertIsNone(zero["wall_seconds"]["sum"])

    def test_failed_history_cost_is_preserved_and_final_duration_stays_separate(self):
        self.add([self.own("main.bug")], time=3,
                 history=[{"attempt": 1, "status": "failed", "wall_seconds": 2}])
        self.add(status="failed", time=7)
        self.add(status="preparation_failure", time=None)
        total = self.summarize()["totals"]
        self.assertEqual(total["wall_seconds"]["sum"], 12)
        self.assertEqual(total["wall_seconds"]["median"], 6)
        self.assertEqual(total["attempt_wall_seconds"]["count"], 3)
        self.assertEqual(total["completed_final_wall_seconds"]["sum"], 3)
        self.assertIsNone(total["workspace_peak_bytes"])

    def test_saved_join_reach_and_ambiguity_are_preserved(self):
        _, event, result = self.add([{"representative": "main",
            "verdict": "unknown", "predicates": [{"instance": "main.bug.child",
                                                    "verdict": "unknown"}]}])
        join = {"schema": "zkfdo-instance-verdicts-v1", "conflicts": 0,
            "results": ["relative/result.json"], "_resolved_result_paths": [event["result_path"]],
            "instances": [{"instance": "main.bug.child", "entry_key": "a:b:c",
                           "verdict": cost.REACH}],
            "classes": [{"request_id": result["request_id"], "representative": "main",
                         "effective": cost.REACH}]}
        self.joins[("main", "mapped")] = join
        total = self.summarize()["totals"]
        self.assertEqual(total["bug_location_L1_requests"], 1)
        self.mapping["revisions"][0]["items"].append(
            {"item_id": "second-bug", "instance_paths": ["main.bug"]})
        total = self.summarize()["totals"]
        self.assertEqual(total["bug_location_L1_requests"], 0)
        self.assertEqual(total["ambiguous_location_L1_requests"], 1)
        join["_resolved_result_paths"] = ["/wrong/result.json"]
        with self.assertRaisesRegex(ValueError, "coverage differs"):
            self.summarize()

    def test_mem20_not_read_and_bad_hash_binding_or_nonfinite_time_refused(self):
        self.add([self.own("main.bug")], scope="mem20")
        self.assertEqual(self.summarize()["supplemental_requests_excluded"], 1)
        self.assertEqual(self.opened, [])
        _, event, _ = self.add([self.own("main.bug")])
        event["wall_seconds"] = float("nan")
        with self.assertRaisesRegex(ValueError, "wall time"):
            self.summarize()
        event["wall_seconds"] = 1
        event["request_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "binding differs"):
            self.summarize()


class SizeParsingAndBoundsTests(unittest.TestCase):
    """Compiler text and reader policy checks with no run input access."""

    def setUp(self):
        import n6_a_size_cost_sizes_20261026 as sizes
        import n6_a_size_cost_table_20261026 as table

        self.sizes = sizes
        self.table = table
        self.counts = "non-linear constraints: 3241\nlinear constraints: 9\nwires: 3251\n"

    def test_compiler_counts_add_linear_and_nonlinear_with_ansi(self):
        text = "compiler header\n\x1b[32m" + self.counts + "\x1b[0mWritten successfully\n"
        self.assertEqual(self.sizes.parse_counts(text), {
            "nonlinear": 3241, "linear": 9, "constraints": 3250, "wires": 3251})

    def test_zero_counts_are_valid(self):
        self.assertEqual(self.sizes.parse_counts(
            "wires: 1\nlinear constraints: 0\nnon-linear constraints: 0\n"), {
                "nonlinear": 0, "linear": 0, "constraints": 0, "wires": 1})

    def test_each_missing_or_duplicate_count_is_rejected(self):
        lines = self.counts.splitlines(keepends=True)
        for line in lines:
            with self.subTest(missing=line), self.assertRaisesRegex(ValueError, "exactly one"):
                self.sizes.parse_counts(self.counts.replace(line, ""))
            with self.subTest(duplicate=line), self.assertRaisesRegex(ValueError, "exactly one"):
                self.sizes.parse_counts(self.counts + line)

    def test_negative_or_fractional_count_is_rejected(self):
        for invalid in ("-1", "1.5", "unknown"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.sizes.parse_counts(self.counts.replace("3251", invalid))

    def test_constraint_bands_include_exact_lower_boundaries(self):
        cases = ((0, "<100k"), (99999, "<100k"), (100000, "100k–<1m"),
                 (999999, "100k–<1m"), (1000000, "≥1m"), (2017059, "≥1m"))
        for count, expected in cases:
            with self.subTest(count=count):
                self.assertEqual(self.table.band(count), expected)

    def test_reader_rejects_forbidden_paths_and_limits_aq_to_named_files(self):
        import posixpath
        from unittest.mock import patch

        reader = object.__new__(self.table.Reader)
        reader.root = Path("/synthetic")
        reader.latest_rqc = None
        # Normalize lexically: these policy tests must not resolve filesystem links.
        with patch.object(Path, "resolve", lambda path: Path(posixpath.normpath(str(path)))):
            forbidden = ("../outside.json", "/outside.json", "runs/n6-b6g-ignored/state.json",
                "runs/n6-b6h-ignored/state.json", "runs/h1-heldout/file.json",
                "runs/ordinary/candidates/value.json", "runs/ordinary/witness.wtns",
                self.table.AQ + "/state-v4.json", self.table.AQ + "/rqc/unselected.json",
                self.table.AQ + "/workspace-cleanup/sub/x-before.json",
                self.table.AQ + "/workspace-cleanup/x-after.json")
            for path in forbidden:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    reader.abspath(path)
            self.assertEqual(reader.abspath("docs/report.md"), reader.root / "docs/report.md")
            for name in ("state.json", "state-v2.json", "state-v3.json", "state-v3_1.json", "workspace-cleanup/x-before.json"):
                self.assertEqual(reader.abspath(self.table.AQ + "/" + name),
                                 reader.root / self.table.AQ / name)
            reader.latest_rqc = reader.root / self.table.AQ / "rqc/latest.json"
            self.assertEqual(reader.abspath(reader.latest_rqc), reader.latest_rqc)
            with self.assertRaises(ValueError):
                reader.abspath(self.table.AQ + "/rqc/older.json")

    def test_reader_guards_priority_free_space_and_elapsed_time(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        reader = object.__new__(self.table.Reader)
        reader.root, reader.started, reader.max_seconds = Path("/synthetic"), 0, 180
        cases = ((19, 15 * 1024**3, 180, None), (18, 15 * 1024**3, 0, "nice 19"),
                 (19, 15 * 1024**3 - 1, 0, "below 15 GiB"),
                 (19, 15 * 1024**3, 181, "time exceeded"))
        for priority, free, now, expected in cases:
            with self.subTest(priority=priority, free=free, now=now), \
                    patch.object(self.table.os, "getpriority", return_value=priority), \
                    patch.object(self.table.shutil, "disk_usage", return_value=SimpleNamespace(free=free)), \
                    patch.object(self.table.time, "monotonic", return_value=now):
                if expected is None:
                    reader.guard()
                else:
                    with self.assertRaisesRegex(ValueError, expected):
                        reader.guard()


class FuzzCostTests(unittest.TestCase):
    """Pure in-memory campaign fixtures; candidate files cannot be opened."""

    def setUp(self):
        import hashlib
        import json
        import n6_a_size_cost_fuzz_20261026 as fuzz

        self.fuzz = fuzz
        self.hashlib = hashlib
        self.json = json
        self.root = Path("/synthetic-fuzz")
        self.blobs = {}
        self.opened = []
        self.source_objects = {}
        self.corrected = "aq-035-8f826c822cb8"
        self.main = self.source("main", [("ordinary", 1), (self.corrected, 1), ("ordinary", 2)])
        self.pragma = self.source("pragma", [(self.corrected, 1)])

    def abspath(self, path):
        value = Path(path)
        return value if value.is_absolute() else self.root / value

    def publish(self, path, value):
        path = self.abspath(path)
        data = self.json.dumps(value, sort_keys=True).encode()
        self.blobs[path] = data
        return self.hashlib.sha256(data).hexdigest()

    def reader(self):
        owner = self

        class MemoryReader:
            def abspath(self, path):
                return owner.abspath(path)

            def json(self, path, expected=None):
                path = owner.abspath(path)
                owner.opened.append(path)
                if path not in owner.blobs:
                    raise AssertionError(f"unexpected metadata/candidate read: {path}")
                raw = owner.blobs[path]
                digest = owner.hashlib.sha256(raw).hexdigest()
                if expected is not None and digest != expected:
                    raise ValueError(f"SHA-256 mismatch: {path}")
                return owner.json.loads(raw)

        return MemoryReader()

    def source(self, label, selections):
        folder = self.root / label
        units, unit_states = [], {}
        for revision, seed in selections:
            unit = {"identifier": revision, "unit_id": f"{revision}-seed-{seed}", "seed": seed}
            methods = {}
            for short, name, cap in (("W", "whole", 600), ("S", "split", 30)):
                targets = [{"target_id": f"{revision}:{short}:{index}"}
                           for index in range(1 if short == "W" else 3)]
                spec = {"schema_version": 1, "method": name, "initial_seed": seed,
                        "total_budget_seconds": 600, "attempt_cap_seconds": cap,
                        "campaign_id": f"{label}-{revision}-{seed}-{short}", "targets": targets}
                specpath = folder / "specs" / f"{revision}-{seed}-{short}.json"
                specsha = self.publish(specpath, spec)
                unit[name + "_spec"] = str(specpath)
                unit[name + "_spec_sha256"] = specsha
                target_index = 0 if short == "W" else seed - 1
                candidate_count = (2 if label == "pragma" else 9 if revision == self.corrected else 1)
                outcome = "candidate" if short == "W" else "timeout"
                attempt = {"attempt_index": 0, "target_index": target_index,
                    "target_id": targets[target_index]["target_id"],
                    "candidates": [{"duplicate_of": None, "path": "NEVER_OPEN_CANDIDATE"}
                                   for _ in range(candidate_count)] if short == "W" else [],
                    "outcome": outcome, "process_started": True, "exit_code": 0 if short == "W" else -9}
                attempts = [attempt]
                outcomes = {outcome: 1}
                if short == "W":
                    attempts.append({"attempt_index": 1, "target_index": 0, "target_id": targets[0]["target_id"],
                        "candidates": [], "outcome": "deadline_before_spawn", "process_started": False,
                        "exit_code": None})
                    outcomes["deadline_before_spawn"] = 1
                ledger = {**{key: spec[key] for key in ("schema_version", "method", "initial_seed",
                    "total_budget_seconds", "attempt_cap_seconds", "campaign_id")},
                    "kind": "policy_a_actual_campaign", "status": "completed", "spec_sha256": specsha,
                    "campaign_wall_seconds": 601.0, "process_wall_seconds_sum": 500.0,
                    "attempts": attempts, "outcome_counts": outcomes, "termination_reason": "budget_exhausted"}
                ledgerpath = folder / "units" / unit["unit_id"] / short / "campaign/ledger.json"
                methods[short] = {"status": "completed", "exit_code": 0,
                    "ledger": str(ledgerpath), "ledger_sha256": self.publish(ledgerpath, ledger)}
            units.append(unit)
            unit_states[unit["unit_id"]] = {"status": "completed_unpressured_retry", "selected_run_number": 2,
                "runs": [{"run_number": 1, "environment": {"environment_pressure": True}, "methods": {}},
                         {"run_number": 2, "environment": {"environment_pressure": False}, "methods": methods},
                         {"run_number": 3, "environment": {"environment_pressure": True}, "methods": {}}]}
        queuepath, statepath = folder / "queue.json", folder / "state.json"
        queue = {"schema_version": 4, "unit_count": len(units), "units": units}
        state = {"schema_version": 4, "status": "completed", "queue_sha256": self.publish(queuepath, queue),
                 "units": unit_states}
        self.publish(statepath, state)
        self.source_objects[label] = (queue, state)
        return queuepath, statepath

    def collect(self):
        return self.fuzz.collect_fuzz(*self.main, *self.pragma, self.reader())

    def test_last_unpressured_selection_and_pragma_substitution_preserve_main_order(self):
        rows = self.collect()
        self.assertEqual([row["revision"] for row in rows], ["ordinary", self.corrected])
        self.assertEqual(rows[0]["W"]["candidates"], 2)
        self.assertEqual(rows[1]["W"]["candidates"], 2)
        self.assertEqual(rows[0]["W"]["initial_seeds"], [1, 2])
        self.assertTrue(all(entry["run_number"] == 2 for row in rows for method in ("W", "S")
                            for entry in row[method]["per_seed"]))
        self.assertTrue(all("/pragma/" in path for path in rows[1]["W"]["ledger_paths"]))
        self.assertFalse(any(f"/main/specs/{self.corrected}" in str(path) for path in self.opened))
        self.assertTrue(all(path.is_absolute() for path in self.opened))

    def test_campaign_process_budget_and_fragment_units_remain_distinct(self):
        ordinary = self.collect()[0]
        self.assertEqual(ordinary["W"]["budget"], 1200)
        self.assertEqual(ordinary["W"]["campaign_seconds"], 1202)
        self.assertEqual(ordinary["W"]["process_seconds"], 1000)
        self.assertEqual(ordinary["W"]["attempt_cap_seconds"], 600)
        self.assertEqual(ordinary["S"]["attempt_cap_seconds"], 30)
        self.assertEqual(ordinary["S"]["units"], 3)
        self.assertEqual(ordinary["S"]["started_units"], 2)
        self.assertEqual(ordinary["S"]["unit_seed_count"], 6)
        self.assertEqual(ordinary["S"]["started_unit_seed_count"], 2)

    def test_deadline_before_spawn_and_normal_candidate_exit_are_not_timeouts_or_panic(self):
        whole = self.collect()[0]["W"]
        self.assertEqual(whole["outcomes"], {"candidate": 2, "deadline_before_spawn": 2})
        self.assertEqual((whole["attempts"], whole["started_attempts"]), (4, 2))
        self.assertEqual(whole["candidate_exit_zero_attempts"], 2)
        self.assertEqual(whole["candidate_nonzero_attempts"], 0)
        self.assertEqual(whole["panic_recorded"], 0)
        self.assertIn("logs not reinspected", whole["panic_basis"])
        self.assertEqual(whole["termination_reasons"], {"budget_exhausted": 2})

    def test_candidate_value_paths_are_never_opened(self):
        self.collect()
        self.assertFalse(any("CANDIDATE" in str(path) for path in self.opened))
        self.assertTrue(all(path.suffix == ".json" for path in self.opened))
        self.assertFalse(any(path.name in {"stdout.log", "stderr.log"} for path in self.opened))

    def test_queue_spec_and_ledger_hash_mismatches_are_rejected(self):
        row = self.collect()[0]
        paths = (self.main[0], Path(row["W"]["spec_paths"][0]), Path(row["W"]["ledger_paths"][0]))
        for path in paths:
            original = self.blobs[path]
            self.blobs[path] = original + b" "
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                self.collect()
            self.blobs[path] = original

    def test_selected_run_number_cannot_choose_a_later_pressured_run(self):
        _queue, state = self.source_objects["main"]
        state["units"]["ordinary-seed-1"]["selected_run_number"] = 3
        self.publish(self.main[1], state)
        with self.assertRaisesRegex(ValueError, "last unpressured"):
            self.collect()


class LatestScoreBoundaryTests(unittest.TestCase):
    def run_latest(self, value, *, symlink=False):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        import n6_a_size_cost_table_20261026 as report

        reader = SimpleNamespace(root=Path("/synthetic-cost"), guard=Mock(),
            latest_rqc=None, json=Mock(return_value=value))
        listing = SimpleNamespace(returncode=0, stdout="new.json\nold.json\n")
        with patch.object(report.subprocess, "run", return_value=listing) as listing_call, \
             patch.object(Path, "is_symlink", return_value=symlink), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "stat", return_value=SimpleNamespace(st_mtime=0)):
            try:
                answer = report.latest_rqc(reader, report.AQ + "/rqc")
            finally:
                self.assertEqual(listing_call.call_args.args[0],
                    ["ls", "-1t", str(reader.root / report.AQ / "rqc")])
                if symlink:
                    reader.json.assert_not_called()
        return answer, reader

    def test_symlink_is_refused_before_any_score_read(self):
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.run_latest({}, symlink=True)

    def test_only_latest_exploratory_score_is_read(self):
        answer, reader = self.run_latest({"schema": "n6-light-rqc-v1", "engine": "v2.2",
                                          "layer": "exploratory"})
        self.assertEqual(answer["status"], "available")
        self.assertEqual(reader.json.call_count, 1)
        self.assertEqual(reader.json.call_args.args[0].name, "new.json")

    def test_other_score_layers_are_not_silently_used(self):
        with self.assertRaisesRegex(ValueError, "exploratory aq score"):
            self.run_latest({"schema": "n6-light-rqc-v1", "engine": "v1", "layer": "strict"})


if __name__ == "__main__":
    unittest.main()
