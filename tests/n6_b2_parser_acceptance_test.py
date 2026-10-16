"""Parser acceptance controls; no B campaign or B parser probes are launched here."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/n6_b2_parser_acceptance.py"
SPEC = importlib.util.spec_from_file_location("n6_b2_parser_acceptance_test_module", SOURCE)
parser = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parser
SPEC.loader.exec_module(parser)


class ParserAcceptanceTest(unittest.TestCase):
    def test_scan_recognizes_split_marker_and_stderr_error_code(self):
        tail, marker, error, codes = parser.scan_chunk(
            "stderr", b"", b"Gath", parser.MARKER)
        self.assertFalse(marker)
        self.assertFalse(error)
        self.assertEqual(codes, [])
        _, marker, error, codes = parser.scan_chunk(
            "stderr", tail, b"ering Trace/Side Constraints...\nerror[P1003]: version\n")
        self.assertTrue(marker)
        self.assertTrue(error)
        self.assertEqual(codes, ["P1003"])

    def test_stdout_error_is_not_treated_as_parser_error(self):
        _, marker, error, codes = parser.scan_chunk("stdout", b"", b"error[P1003]")
        self.assertFalse(marker)
        self.assertFalse(error)
        self.assertEqual(codes, [])

    def test_parser_identity_changes_if_target_command_changes(self):
        spec = {key: [] for key in (
            "source_snapshots", "targets", "pinned_files", "pinned_trees")}
        spec["targets"] = [{"command": ["zkfuzz", "source.circom"]}]
        baseline = parser.identity_sha256(spec)
        spec["targets"][0]["command"].append("-l")
        self.assertNotEqual(baseline, parser.identity_sha256(spec))

    def test_probe_kills_group_and_discards_temporary_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = [sys.executable, "-c", (
                "import sys,time; "
                "sys.stderr.write('Gathering Trace/Side Constraints...\\n'); "
                "sys.stderr.flush(); time.sleep(3)"
            )]
            result = parser.run_probe(command, max_seconds=2,
                                      memory_sampler=lambda _pid: {"physical_memory_bytes": 1},
                                      temporary_root=root)
            self.assertEqual(result["status"], "accepted")
            self.assertTrue(result["process_group_empty"])
            self.assertEqual(list(root.iterdir()), [])

    def test_probe_fails_closed_when_memory_sample_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            command = [sys.executable, "-c", "import time; time.sleep(3)"]
            result = parser.run_probe(command, max_seconds=2,
                                      memory_sampler=lambda _pid: None,
                                      temporary_root=Path(temporary))
            self.assertEqual(result["status"], "resource_monitor_failure")
            self.assertTrue(result["process_group_empty"])

    def test_fast_natural_parser_error_is_recorded_after_group_exits(self):
        with tempfile.TemporaryDirectory() as temporary:
            command = [sys.executable, "-c", (
                "import sys; sys.stderr.write('error[P1003]: version\\n')"
            )]
            result = parser.run_probe(command, max_seconds=2,
                                      memory_sampler=lambda _pid: {"physical_memory_bytes": 1},
                                      temporary_root=Path(temporary))
            self.assertEqual(result["status"], "parser_error")
            self.assertEqual(result["error_codes"], ["P1003"])
            self.assertTrue(result["process_group_empty"])


if __name__ == "__main__":
    unittest.main()
