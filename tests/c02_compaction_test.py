"""Count projection checks on synthetic metadata; no circuit or tool execution."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).resolve().parents[1] / "scripts/compact_c02_results.py"
SPEC = importlib.util.spec_from_file_location("compact_c02", PATH)
COMPACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPACT)


def fixture():
    reason = {"reason_class": "unsupported_syntax", "reason_subtype": "compile_time_variable_array", "reason_sha256": "a" * 64}
    diagnostic = {**reason, "source_path": "library.circom", "line": 8}
    wrapped = {**reason, "source_path": "library.circom", "wrapper_status": "unsupported", "callsite_identity_sha256": "d" * 64}
    measurement = {"reference": {"path": "runs/unit/result-v2.json", "sha256": "b" * 64},
                   "history": [{"reference": {"path": "runs/unit/result.json", "sha256": "c" * 64}, "elapsed_seconds": None}],
                   "compile": {"status": "success", "constraints": 0, "elapsed_seconds": 2.3},
                   "discovery": {"unsupported": [diagnostic] * 8,
                                 "wrapper_failure_diagnostics": [wrapped] * 6,
                                 "callsite_wrapper_statuses": ["unsupported"] * 6 + ["compile_succeeded"] * 2},
                   "preparation": {"status": "partial", "targets": [{"label": "root", "eligible": False,
                                              "constraints": None, "exclusion_reasons": [reason] * 5}]}}
    return {"schema_version": 1, "overall": {"entrypoint_files": 1, "compile_success_rate": {"numerator": 1, "denominator": 1}},
            "by_source": {"github_top200": {"repositories": 1}}, "by_exposure": {"unknown": {"repositories": 1}},
            "repositories": [{"full_name": "example/toy", "entrypoints": [{"path": "main.circom", "sha256": "e" * 64,
                                                                            "measurement": measurement}]}]}


class CountProjection(unittest.TestCase):
    def test_counts_and_all_non_diagnostic_data_are_preserved(self):
        original = fixture()
        fingerprint = COMPACT.canonical_fingerprint(original)
        result = COMPACT.project(copy.deepcopy(original), {"path": "raw.json", "sha256": "f" * 64, "bytes": 10})
        self.assertEqual(COMPACT.canonical_fingerprint(result), fingerprint)
        for key in ("overall", "by_source", "by_exposure"):
            self.assertEqual(original[key], result[key])
        before = original["repositories"][0]["entrypoints"][0]
        after = result["repositories"][0]["entrypoints"][0]
        self.assertEqual(before["path"], after["path"])
        for key in ("reference", "history", "compile"):
            self.assertEqual(before["measurement"][key], after["measurement"][key])
        projected = after["measurement"]["discovery"]["callsite_wrapper_statuses"]
        self.assertEqual({group["wrapper_status"]: group["occurrences"] for group in projected["groups"]},
                         {"unsupported": 6, "compile_succeeded": 2})
        self.assertEqual(result["diagnostic_projection"]["array_occurrences_before"],
                         {"unsupported": 8, "wrapper_failure_diagnostics": 6, "callsite_wrapper_statuses": 8, "exclusion_reasons": 5})

    def test_unknown_and_different_reason_hashes_are_not_merged(self):
        value = fixture()
        rows = value["repositories"][0]["entrypoints"][0]["measurement"]["discovery"]["unsupported"]
        rows[0] = {"reason_class": "unknown", "reason_subtype": "unknown_missing_reason", "reason_sha256": None}
        rows[1] = {**rows[2], "reason_sha256": "2" * 64}
        result = COMPACT.project(value, {})
        projected = result["repositories"][0]["entrypoints"][0]["measurement"]["discovery"]["unsupported"]
        self.assertEqual(sorted(group["occurrences"] for group in projected["groups"]), [1, 1, 6])
        self.assertEqual(projected["total_occurrences"], 8)

    def test_future_unrecognized_diagnostic_fields_and_double_projection_are_rejected(self):
        value = fixture()
        value["repositories"][0]["entrypoints"][0]["measurement"]["discovery"]["unsupported"][0]["new_semantic_verdict"] = "must_not_drop"
        with self.assertRaisesRegex(ValueError, "unrecognized diagnostic"):
            COMPACT.project(value, {})
        value = COMPACT.project(fixture(), {})
        with self.assertRaisesRegex(ValueError, "schema 1"):
            COMPACT.project(value, {})

    def test_dry_run_writes_nothing_then_atomic_replacement_preserves_exact_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, raw = root / "shared.json", root / "raw/expanded.json"
            original_bytes = json.dumps(fixture()).encode()
            source.write_bytes(original_bytes)
            report = COMPACT.run(source, source, raw)
            self.assertEqual(report["status"], "dry_run_no_files_changed")
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertFalse(raw.exists())
            COMPACT.run(source, source, raw, write=True)
            self.assertEqual(raw.read_bytes(), original_bytes)
            compact = json.loads(source.read_text())
            self.assertEqual(compact["schema_version"], 2)
            self.assertEqual(compact["diagnostic_projection"]["expanded_source"]["sha256"], COMPACT.digest(raw))
            with self.assertRaisesRegex(ValueError, "preservation path exists"):
                COMPACT.run(source, source, raw, write=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
