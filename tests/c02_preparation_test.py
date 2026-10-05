"""Negative aggregation/command-contract tests; no external project or fuzzer."""
import importlib.util
import json
from pathlib import Path
import struct
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("c02", Path(__file__).resolve().parents[1] / "scripts/measure_c02_preparation.py")
c02 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c02)


class PreparationTests(unittest.TestCase):
    def test_nested_prepare_report_uses_compile_only_contract(self):
        with tempfile.TemporaryDirectory(dir=c02.ROOT / "runs") as temp:
            directory = Path(temp)
            discovery_path = directory / "discovery.json"
            discovery = {"root_instance_key": "main.circom::Main()", "entrypoint_status": "found",
                         "targets": [], "compile_units": [], "compile_process_count": 0, "unsupported": []}
            discovery_path.write_text(json.dumps(discovery))
            repo = {"full_name": "synthetic/example", "commit_sha": "0" * 40, "checkout_path": str(directory)}
            commands = []

            def fake_command(argv, log_dir, cap):
                commands.append(argv)
                if "prepare" in argv:
                    definition = json.loads((directory / "manifest.json").read_text())["targets"][0]
                    prepared = directory / "prepared/prepare-uuid/prepared.json"
                    prepared.parent.mkdir(parents=True)
                    prepared.write_text(json.dumps({"targets": [{"definition": definition,
                        "eligible": True, "exclusion_reasons": [], "elapsed_seconds": 0,
                        "structure": {"size": 0, "ast_requested": False, "zkfuzz_version": {"requested": False},
                                      "compile": {"elapsed_seconds": 0, "process_started": True}}}]}))
                else:
                    (directory / "plan.json").write_text("{}")
                return {"status": "success"}

            result = {"discovery": {}}
            with patch.object(c02, "run_command", fake_command):
                c02.complete_preparation(result, repo, directory / "main.circom", discovery_path, directory, [])
            self.assertEqual(result["preparation"]["status"], "success")
            self.assertEqual(result["preparation"]["targets"][0]["constraints"], 0)
            self.assertEqual(commands[0][commands[0].index("--strategy") + 1], "small-first")
            self.assertEqual(commands[0][commands[0].index("--zkfuzz-bin") + 1], "/nonexistent/c02-zkfuzz-forbidden")
            self.assertEqual(commands[1][1:3], ["experiment", "plan"])

    def test_missing_prepare_report_cannot_be_success(self):
        with tempfile.TemporaryDirectory(dir=c02.ROOT / "runs") as temp:
            directory = Path(temp)
            discovery_path = directory / "discovery.json"
            discovery_path.write_text(json.dumps({"root_instance_key": "main.circom::Main()", "entrypoint_status": "found",
                "targets": [], "compile_units": [], "compile_process_count": 0, "unsupported": []}))
            repo = {"full_name": "synthetic/example", "commit_sha": "0" * 40, "checkout_path": str(directory)}
            result = {"discovery": {}}
            with patch.object(c02, "run_command", return_value={"status": "success"}):
                c02.complete_preparation(result, repo, directory / "main.circom", discovery_path, directory, [])
            self.assertEqual(result["preparation"]["status"], "unknown")
            self.assertNotIn("plan", result)

    def test_timeout_cleans_child_in_another_process_group(self):
        with tempfile.TemporaryDirectory(dir=c02.ROOT / "runs") as temp:
            directory = Path(temp)
            script = ("import subprocess,sys,time; "
                      "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'], process_group=0); "
                      "print(p.pid,flush=True); time.sleep(60)")
            result = c02.run_command([sys.executable, "-c", script], directory / "groups", 0.4)
            child = int((directory / "groups/stdout.log").read_text().strip())
            self.assertEqual(result["status"], "timeout")
            self.assertIn(child, result["cleanup_signaled_pids"])
            status = subprocess.run(["/bin/ps", "-p", str(child), "-o", "stat="], capture_output=True, text=True).stdout.strip()
            self.assertTrue(not status or status.startswith("Z"), status)
            self.assertNotIn(os.getpid(), result["cleanup_signaled_pids"])

    def test_uuid_nested_reports_are_found_without_arbitrary_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.assertIsNone(c02.locate_report(directory, "discovery.json"))
            report = directory / "uuid-1/discovery.json"
            report.parent.mkdir()
            report.write_text("{}")
            self.assertEqual(c02.locate_report(directory, "discovery.json"), report)
            other = directory / "uuid-2/discovery.json"
            other.parent.mkdir()
            other.write_text("{}")
            with self.assertRaises(ValueError):
                c02.locate_report(directory, "discovery.json")

    def test_concrete_parameters_are_not_guessed(self):
        self.assertEqual(c02.parse_instance("a::path.circom::T(-1, 8)"), ("T", ["-1", "8"]))
        self.assertEqual(c02.parse_instance("a::T()"), ("T", []))
        for value in (None, "a::T(2**8)", "T(8)", "a::T([1,2])"):
            with self.assertRaises(ValueError):
                c02.parse_instance(value)

    def test_callsites_do_not_duplicate_compile_units(self):
        repo = {"full_name": "synthetic/example", "commit_sha": "0" * 40, "checkout_path": "/synthetic"}
        discovery = {"root_instance_key": "main.circom::Main()", "targets": [{}, {}],
                     "compile_units": [{"key": "a", "wrapper_path": "/wrapper.circom", "instance_key": "lib.circom::Add(8)"}]}
        manifest = c02.manifest_for(repo, "/main.circom", discovery, ["/synthetic"])
        self.assertEqual(len(manifest["targets"]), 2)
        self.assertEqual(manifest["targets"][1]["concrete_parameters"], ["8"])
        self.assertNotIn("input_contract", manifest["targets"][0])
        discovery["compile_units"].append(discovery["compile_units"][0])
        with self.assertRaises(ValueError):
            c02.manifest_for(repo, "/main.circom", discovery, [])

    def test_successful_plan_does_not_hide_partial_preparation(self):
        discovery = {"entrypoint_status": "found", "unsupported": [],
                     "targets": [{"wrapper_status": "compile_succeeded"}]}
        prepared = {"targets": [{"eligible": True}, {"eligible": True}]}
        plan = {"status": "success"}
        self.assertEqual(c02.preparation_status(discovery, prepared, plan, 2), "success")
        discovery["unsupported"] = [{"reason": "unresolved syntax"}]
        self.assertEqual(c02.preparation_status(discovery, prepared, plan, 2), "partial")
        discovery["unsupported"] = []
        prepared["targets"].pop()
        self.assertEqual(c02.preparation_status(discovery, prepared, plan, 2), "partial")
        prepared["targets"][0]["eligible"] = False
        self.assertEqual(c02.preparation_status(discovery, prepared, plan, 2), "failed")

    def test_zero_constraints_is_measured_not_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "header.r1cs"
            header = struct.pack("<I", 32) + bytes(32) + struct.pack("<IIIIQI", 1, 0, 0, 0, 1, 0)
            path.write_bytes(b"r1cs" + struct.pack("<II", 1, 1) + struct.pack("<IQ", 1, len(header)) + header)
            self.assertEqual(c02.r1cs_count(path), 0)
            path.write_bytes(b"r1cs" + struct.pack("<II", 1, 0))
            with self.assertRaises(ValueError):
                c02.r1cs_count(path)

    def test_bounded_child_failure_and_timeout_preserve_logs(self):
        with tempfile.TemporaryDirectory(dir=c02.ROOT / "runs") as temp:
            directory = Path(temp)
            failure = c02.run_command([sys.executable, "-c", "import sys; sys.exit(7)"], directory / "failure", 1)
            self.assertEqual((failure["status"], failure["exit_code"]), ("failure", 7))
            timeout = c02.run_command([sys.executable, "-c", "import time; time.sleep(10)"], directory / "timeout", 0.05)
            self.assertEqual(timeout["status"], "timeout")
            self.assertTrue(timeout["process_started"])
            self.assertIsNotNone(timeout["exit_code"])
            record = json.loads((directory / "timeout/invocation.json").read_text())
            self.assertEqual(record["stdout"]["sha256"], c02.digest(directory / "timeout/stdout.log"))


if __name__ == "__main__":
    unittest.main()
