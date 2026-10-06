import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "e02_incremental_cleanup", REPOSITORY / "scripts/e02_incremental_cleanup.py"
)
CLEANUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLEANUP)


class E02IncrementalCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.saved = (CLEANUP.ROOT, CLEANUP.RUN, CLEANUP.LEDGER, CLEANUP.STATE)
        CLEANUP.ROOT = root
        CLEANUP.RUN = root / "runs/e02-production-mains-2026-10-05"
        CLEANUP.LEDGER = CLEANUP.RUN / "incremental-cleanup-ledger.jsonl"
        CLEANUP.STATE = CLEANUP.RUN / "incremental-cleanup-state.json"
        self.addCleanup(self.restore_globals)

    def restore_globals(self):
        CLEANUP.ROOT, CLEANUP.RUN, CLEANUP.LEDGER, CLEANUP.STATE = self.saved

    def entry(self, identifier="unit"):
        path = CLEANUP.RUN / "preparation-measurements" / identifier
        path.mkdir(parents=True)
        return path

    def test_only_result_bearing_entry_is_eligible(self):
        complete = self.entry("complete")
        active = self.entry("active")
        (complete / "result.json").write_text("{}\n")
        (active / "work.r1cs").write_bytes(b"active")
        rows = list(CLEANUP.completed_entries())
        self.assertEqual([(stage, path.name) for stage, path, _ in rows],
                         [("preparation-measurements", "complete")])

    def test_records_then_deletes_only_authorized_artifacts(self):
        entry = self.entry()
        result = entry / "result.json"
        result.write_text('{"status":"complete"}\n')
        compiled = entry / "prepared/work.r1cs"
        compiled.parent.mkdir()
        compiled.write_bytes(b"compiled")
        preserved_sym = entry / "prepared/work.sym"
        preserved_sym.write_bytes(b"symbols")
        preserved_log = entry / "run.log"
        preserved_log.write_text("log\n")
        preserved_node_object = entry / "node_modules/pkg/native.o"
        preserved_node_object.parent.mkdir(parents=True)
        preserved_node_object.write_bytes(b"dependency")
        call = entry / "discovery/call"
        diagnostic = call / "instance-capture/diagnostic-copy"
        diagnostic.mkdir(parents=True)
        (diagnostic / "copy.dat").write_bytes(b"diagnostic")
        (call / "instance-capture.json").write_text('{"instances":[1]}\n')
        (call / "instance-args.json").write_text('{"args":[1]}\n')

        state = {"schema_version": 1, "task": "E-02", "completed_batches": {}}
        completion = CLEANUP.clean_entry("preparation-measurements", entry, result, state)

        self.assertFalse(compiled.exists())
        self.assertFalse(diagnostic.exists())
        self.assertTrue(preserved_sym.exists())
        self.assertTrue(preserved_log.exists())
        self.assertTrue(preserved_node_object.exists())
        self.assertEqual(completion["skipped"], [])
        events = [json.loads(line) for line in CLEANUP.LEDGER.read_text().splitlines()]
        self.assertEqual([row["event"] for row in events],
                         ["recorded_before_deletion", "deletion_completed"])
        recorded_paths = {row["path"] for row in events[0]["files"]}
        self.assertIn(str(compiled.relative_to(CLEANUP.ROOT)), recorded_paths)
        self.assertIn(str((diagnostic / "copy.dat").relative_to(CLEANUP.ROOT)), recorded_paths)

    def test_missing_capture_pair_preserves_diagnostic_copy(self):
        entry = self.entry()
        result = entry / "result.json"
        result.write_text("{}\n")
        call = entry / "discovery/call"
        diagnostic = call / "instance-capture/diagnostic-copy"
        diagnostic.mkdir(parents=True)
        artifact = diagnostic / "work.r1cs"
        artifact.write_bytes(b"keep")
        (call / "instance-capture.json").write_text('{"instances":[1]}\n')

        with self.assertRaisesRegex(RuntimeError, "capture values not persisted"):
            CLEANUP.clean_entry("preparation-measurements", entry, result,
                                {"schema_version": 1, "task": "E-02", "completed_batches": {}})
        self.assertTrue(artifact.exists())
        self.assertFalse(CLEANUP.LEDGER.exists())

    def test_clone_and_incomplete_result_are_preserved(self):
        entry = self.entry()
        result = entry / "result.json"
        result.write_text('{"status":')
        original = entry / "clone/source.r1cs"
        original.parent.mkdir()
        original.write_bytes(b"original")
        self.assertEqual(list(CLEANUP.completed_entries()), [])
        result.write_text('{}')
        files, _, _ = CLEANUP.inventory(entry)
        self.assertEqual(files, [])
        self.assertTrue(original.exists())

    def test_failed_ledger_write_deletes_nothing(self):
        entry = self.entry()
        result = entry / "result.json"
        result.write_text('{}')
        artifact = entry / "output.r1cs"
        artifact.write_bytes(b"artifact")
        with patch.object(CLEANUP, "append_ledger", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                CLEANUP.clean_entry("preparation-measurements", entry, result,
                                    {"completed_batches": {}})
        self.assertEqual(artifact.read_bytes(), b"artifact")

    def test_same_size_change_after_record_is_not_deleted(self):
        entry = self.entry()
        result = entry / "result.json"
        result.write_text('{}')
        artifact = entry / "output.r1cs"
        artifact.write_bytes(b"before")
        original_append = CLEANUP.append_ledger

        def append_and_change(record):
            original_append(record)
            if record["event"] == "recorded_before_deletion":
                artifact.write_bytes(b"change")

        with patch.object(CLEANUP, "append_ledger", side_effect=append_and_change):
            completion = CLEANUP.clean_entry("preparation-measurements", entry, result,
                                            {"completed_batches": {}})
        self.assertEqual(artifact.read_bytes(), b"change")
        self.assertEqual(completion["deleted_files"], 0)
        self.assertEqual(len(completion["skipped"]), 1)

    def test_sibling_capture_files_cannot_authorize_deletion(self):
        entry = self.entry()
        diagnostic = entry / "discovery/a/instance-capture/diagnostic-copy"
        diagnostic.mkdir(parents=True)
        sibling = entry / "discovery/b"
        sibling.mkdir()
        (sibling / "instance-capture.json").write_text('{"instances":[1]}')
        (sibling / "instance-args.json").write_text('{"args":[1]}')
        verification = CLEANUP.capture_verification(entry, [diagnostic])
        self.assertFalse(verification["verified"])


if __name__ == "__main__":
    unittest.main()
