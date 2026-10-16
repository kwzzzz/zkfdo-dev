"""Small fake-source tests for the N6-B parser correction stages."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/n6_b2_pragma_prepare.py"
SPEC = importlib.util.spec_from_file_location("n6_b2_pragma_prepare_test_module", MODULE_PATH)
correction = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = correction
SPEC.loader.exec_module(correction)


class N6B2PragmaPrepareTest(unittest.TestCase):
    def test_pragma_edit_is_exactly_one_full_line(self):
        before = (b"pragma circom 2.2.3;\r\n"
                  b"// pragma circom 2.2.3;\n"
                  b"pragma circom 2.2.1;\n")
        after, count = correction.pragma_replacement(before)
        self.assertEqual(count, 1)
        self.assertEqual(after, (b"pragma circom 2.2.1;\r\n"
                                 b"// pragma circom 2.2.3;\n"
                                 b"pragma circom 2.2.1;\n"))

    def test_source_correction_requires_matching_recorded_p1003(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = root / "probe.jsonl"
            header = {"kind": "header", "queue_sha256": correction.SOURCE_QUEUE_SHA256}
            target = {"kind": "target", "identifier": correction.IDENTIFIER,
                      "method": "W", "status": "parser_error", "error_codes": ["P1003"],
                      "spec_sha256": "spec", "entrypoint_sha256": "entry"}
            ledger.write_text(json.dumps(header) + "\n" + json.dumps(target) + "\n")
            with patch.object(correction, "ROOT", root):
                proof = correction.confirmed_p1003(ledger, "spec", "entry")
                self.assertEqual(proof["status"], "parser_error")
                target["error_codes"] = ["P1004"]
                ledger.write_text(json.dumps(header) + "\n" + json.dumps(target) + "\n")
                with self.assertRaisesRegex(ValueError, "does not match"):
                    correction.confirmed_p1003(ledger, "spec", "entry")

    def test_absolute_include_only_repoints_same_relative_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_project = root / "original"
            new_project = root / "versioned"
            for project in (old_project, new_project):
                source = project / "circuits/math.circom"
                source.parent.mkdir(parents=True)
                source.write_text("pragma circom 2.2.1;\n")
            before = (f'include "{old_project / "circuits/math.circom"}";\n'
                      'include "relative.circom";\n').encode()
            after, count, paths = correction.include_replacement(
                before, old_project, new_project)
            self.assertEqual(count, 1)
            self.assertEqual(after, (f'include "{new_project / "circuits/math.circom"}";\n'
                                     'include "relative.circom";\n').encode())
            self.assertEqual(paths[0]["new"], str(new_project / "circuits/math.circom"))

    def test_r1cs_mismatch_stops_before_next_fragment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "runs/versioned"
            output.mkdir(parents=True)
            original = root / "runs/original"
            corrected = output / "project"
            original.mkdir(parents=True)
            corrected.mkdir(parents=True)
            for workspace in (original, corrected):
                (workspace / "main.circom").write_text("pragma circom 2.2.1;\n")
            snapshot = root / "runs/snapshot"
            new_snapshot = output / "snapshots/split-0000"
            snapshot.mkdir()
            new_snapshot.mkdir(parents=True)
            for workspace in (snapshot, new_snapshot):
                (workspace / "fragment.circom").write_text("pragma circom 2.2.1;\n")
            whole = {"targets": [{"target_id": "W", "entrypoint_relative": "main.circom"}]}
            split = {"targets": [{"target_id": "S", "rank": 1,
                                  "entrypoint_relative": "fragment.circom"}],
                     "source_snapshots": [{"path": str(snapshot)}]}
            evidence = {"original_project": str(original.relative_to(root)),
                        "corrected_project": str(corrected.relative_to(root)),
                        "snapshots": [{"source": str(snapshot.relative_to(root)),
                                       "corrected": str(new_snapshot.relative_to(root))}]}
            calls = []

            def fake_compile(_target, _entrypoint, _workspace, folder, *_args):
                folder.mkdir()
                contents = b"original" if folder.name == "original" else b"different"
                (folder / "circuit.r1cs").write_bytes(contents)
                calls.append(folder.name)
                return {"r1cs_sha256": correction.sha256(folder / "circuit.r1cs")}

            with patch.object(correction, "ROOT", root), \
                    patch.object(correction, "load_staged", return_value=(
                        {}, whole, split, {}, evidence, [])), \
                    patch.object(correction, "compile_r1cs", side_effect=fake_compile):
                with self.assertRaisesRegex(ValueError, "R1CS bytes differ"):
                    correction.prove_equivalence(output)
            self.assertEqual(calls, ["original", "corrected"])
            proof = json.loads((output / "r1cs-equivalence.json").read_text())
            self.assertEqual(proof["status"], "failed")
            self.assertEqual(proof["failed_target_id"], "W")
            self.assertEqual(len(proof["pairs"]), 1)

    def test_corrected_static_pragma_checks_every_source_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            snapshot = root / "snapshot"
            project.mkdir()
            snapshot.mkdir()
            (project / "entry.circom").write_text("pragma circom 2.2.1;\n")
            (snapshot / "wrapper.circom").write_text("pragma circom 2.1.6;\n")
            with patch.object(correction, "ROOT", root):
                passed = correction.scan_corrected_pragmas([project, snapshot])
                self.assertEqual(passed["status"], "passed")
                self.assertEqual(passed["pragma_version_counts"],
                                 {"2.1.6": 1, "2.2.1": 1})
                (snapshot / "unused.circom").write_text("pragma circom 2.2.3;\n")
                failed = correction.scan_corrected_pragmas([project, snapshot])
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["files_exceeding_parser"], [
                {"file": "snapshot/unused.circom", "version": "2.2.3"}])

    def test_parse_unconfirmed_requires_static_proof_but_does_not_block(self):
        self.assertTrue(correction.parser_result_allowed(
            {"status": "accepted"}, "passed"))
        self.assertTrue(correction.parser_result_allowed(
            {"status": "parse_unconfirmed"}, "passed"))
        self.assertFalse(correction.parser_result_allowed(
            {"status": "parse_unconfirmed"}, "failed"))
        for status in ("parser_error", "other_error", "resource_monitor_failure",
                       "memory_cap"):
            self.assertFalse(correction.parser_result_allowed(
                {"status": status}, "passed"))
        rows = [{"status": "accepted", "static_pragma_status": "passed"}
                for _ in range(305)]
        rows.append({"status": "parse_unconfirmed", "static_pragma_status": "passed"})
        ledger = {"status": "passed", "expected_target_count": 306,
                  "spec_manifest_sha256": "manifest", "static_pragma_sha256": "static",
                  "targets": rows, "accepted_count": 305,
                  "parse_unconfirmed_count": 1}
        self.assertTrue(correction.parser_ledger_complete(ledger, "manifest", "static"))
        ledger["targets"][-1]["status"] = "parser_error"
        self.assertFalse(correction.parser_ledger_complete(ledger, "manifest", "static"))

    def test_reprobe_plan_uses_first_seed_command_and_checks_seed_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "corrected/main.circom"
            source.parent.mkdir()
            source.write_text("pragma circom 2.2.1;\n")
            source_hash = correction.sha256(source)
            units = [{"unit_id": f"unit-{seed}"} for seed in range(3)]
            rows = []
            for unit in units:
                for method, count in (("W", 1), ("S", 305)):
                    spec = {"source_snapshots": [{"id": "snapshot", "path": str(source.parent)}],
                            "targets": [{"source_snapshot_id": "snapshot",
                                         "entrypoint_relative": "main.circom",
                                         "entrypoint_sha256": source_hash,
                                         "target_id": f"{method}-{index}",
                                         "command": ["/fake/zkfuzz", "{entrypoint}",
                                                     "-l", "{workspace}"]}
                                        for index in range(count)]}
                    path = root / "specs" / f"{unit['unit_id']}-{method}.json"
                    path.parent.mkdir(exist_ok=True)
                    path.write_text(json.dumps(spec))
                    rows.append({"unit_id": unit["unit_id"], "method": method,
                                 "corrected_spec": path.relative_to(root).as_posix(),
                                 "corrected_spec_sha256": correction.sha256(path)})
            manifest = {"status": "prepared_not_executed", "spec_count": 6,
                        "rows": rows}
            fake_parser = SimpleNamespace(
                ZKFUZZ=Path("/fake/zkfuzz"),
                identity_sha256=lambda spec: correction.sha256(source) +
                ":" + str(len(spec["targets"])) + ":" +
                spec["targets"][0]["command"][0])
            with patch.object(correction, "ROOT", root):
                plan = correction.corrected_parser_plan(root, manifest, units, fake_parser)
                self.assertEqual(len(plan), 306)
                self.assertEqual(plan[0]["command"][1], str(source))
                self.assertEqual(plan[-1]["target_id"], "S-304")
                changed_path = root / rows[-1]["corrected_spec"]
                changed = json.loads(changed_path.read_text())
                changed["targets"][0]["command"][0] = "/different/zkfuzz"
                changed_path.write_text(json.dumps(changed))
                rows[-1]["corrected_spec_sha256"] = correction.sha256(changed_path)
                with self.assertRaisesRegex(ValueError, "differ across seeds"):
                    correction.corrected_parser_plan(root, manifest, units, fake_parser)


if __name__ == "__main__":
    unittest.main()
