"""Fail-closed tests for the C-03 actual executable provenance audit."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "c03_tool_provenance",
    Path(__file__).resolve().parents[1] / "scripts/audit_c03_tool_provenance.py",
)
provenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provenance)


class ToolProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.run = self.root / "runs/c03-corpus-2026-10-02/recovery-v3"
        self.run.mkdir(parents=True)
        self.actual_tools = self.root / "runs/c02-corpus-2026-10-02/tools"
        self.recovery_tools = self.run / "tools"
        self.actual_tools.mkdir(parents=True)
        self.recovery_tools.mkdir()
        for name, content in (("circom", b"synthetic-circom-2.2.3\n"), ("zkfDO", b"synthetic-zkfdo\n")):
            (self.actual_tools / name).write_bytes(content)
            (self.recovery_tools / name).write_bytes(content)
        self.tool_lock = self.actual_tools.parent / "tool-lock.json"
        self.write_json(self.tool_lock, {"tools": [
            {"path": str(self.actual_tools / name),
             "sha256": provenance.digest(self.actual_tools / name)} for name in ("zkfDO", "circom")
        ], "zkfuzz_executions": 0})
        self.repository = "synthetic/service"
        self.commit = "1" * 40
        self.checkout = (self.run / "repositories/synthetic__service/clone").resolve()
        self.source = self.checkout / "circuits/main.circom"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("pragma circom 2.2.3;\n")
        self.entry = {"key": "source:circuits/main.circom", "kind": "source_main",
                      "source_path": "circuits/main.circom", "path": str(self.source)}
        self.identifier = provenance.measurement_id(self.repository, self.entry["key"])
        inventory = {"known_entrypoint_count": 1, "repositories": [{"full_name": self.repository,
            "commit_sha": self.commit, "entries": [self.entry]}]}
        self.write_json(self.run / "entrypoints-after.v4.json", inventory)
        census = {"repositories": [{"full_name": self.repository, "commit_sha": self.commit,
                                    "clone_path": str(self.checkout)}]}
        self.write_json(self.run / "census.v3.json", census)
        selection = {"schema_version": 4, "active_after_directory": "after-v4",
            "all_after_entries_remeasured": True,
            "after_inventory_ref": provenance.reference(self.run / "entrypoints-after.v4.json", self.root),
            "census_ref": provenance.reference(self.run / "census.v3.json", self.root)}
        self.write_json(self.run / "final-measurement-selection.v4.json", selection)
        self.write_json(self.run / "measurement-lock.json", {"compiler_tools": [
            provenance.reference(self.recovery_tools / "circom", self.root),
            provenance.reference(self.recovery_tools / "zkfDO", self.root),
        ]})
        self.result_dir = self.run / "measurements" / self.identifier / "after-v4"
        self.result_dir.mkdir(parents=True)
        (self.result_dir / "original").mkdir()
        (self.result_dir / "discovery").mkdir()
        prepared = self.result_dir / "prepared/prepare-synthetic/prepared.json"
        prepared.parent.mkdir(parents=True); self.write_json(prepared, {})
        manifest = self.result_dir / "manifest.json"; self.write_json(manifest, {})
        plan_output = self.result_dir / "plan.json"; self.write_json(plan_output, {})
        libraries = [str(self.checkout)]
        result = {"repository": self.repository, "commit_sha": self.commit,
            "entrypoint_key": self.entry["key"], "entrypoint_kind": self.entry["kind"],
            "phase": "after", "physical_result_directory": "after-v4",
            "source_sha256": "2" * 64, "library_paths": libraries}
        commands = {
            "compile": [str(self.recovery_tools.resolve() / "circom"), str(self.source), "--r1cs", "-o",
                        str(self.result_dir / "original"), "-l", str(self.checkout)],
            "discover": [str(self.actual_tools.resolve() / "zkfDO"), "targets", "--project", str(self.checkout),
                         "--entrypoint", str(self.source), "--output", str(self.result_dir / "discovery"),
                         "--circom-bin", str(self.actual_tools.resolve() / "circom"),
                         "--compile-timeout-seconds", "60", "--library-path", str(self.checkout)],
            "prepare": [str(self.actual_tools / "zkfDO"), "experiment", "prepare",
                        "--manifest", str(manifest), "--output", str(self.result_dir / "prepared"),
                        "--strategy", "small-first",
                        "--circom-bin", str(self.actual_tools / "circom"),
                        "--zkfuzz-bin", provenance.FORBIDDEN_ZKFUZZ,
                        "--circomspect-bin", provenance.FORBIDDEN_ANALYZER,
                        "--tool-timeout-seconds", "60"],
            "plan": [str(self.actual_tools / "zkfDO"), "experiment", "plan",
                     "--prepared", str(prepared), "--strategy", "small-first",
                     "--config", str(self.root.resolve() / "configs/static-ranking.json"),
                     "--output", str(plan_output)],
        }
        result_keys = {"compile": "compile", "discover": "discovery", "prepare": "preparation", "plan": "plan"}
        for index, (stage, argv) in enumerate(commands.items()):
            call_name = provenance.STAGES[stage][1]
            call = self.result_dir / call_name
            call.mkdir()
            stdout, stderr = call / "stdout.log", call / "stderr.log"
            stdout.write_text(""); stderr.write_text("")
            invocation = {"argv": argv, "started_at": f"2026-10-02T00:00:0{index}Z",
                "finished_at": f"2026-10-02T00:00:0{index}Z", "cap_seconds": 30,
                "status": "success", "exit_code": 0, "process_started": True,
                "elapsed_seconds": 0.1, "stdout": provenance.reference(stdout, self.root),
                "stderr": provenance.reference(stderr, self.root)}
            self.write_json(call / "invocation.json", invocation)
            capture = {key: value for key, value in invocation.items() if key != "argv"}
            if stage == "prepare":
                capture["status"] = "partial"
                capture["manifest"] = provenance.reference(manifest, self.root)
                capture["report"] = provenance.reference(prepared, self.root)
            if stage == "plan":
                capture["report"] = provenance.reference(plan_output, self.root)
            result[result_keys[stage]] = capture
        self.write_json(self.result_dir / "result.json", result)

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def error_codes(self, callable_):
        with self.assertRaises(provenance.ProvenanceError) as raised:
            callable_()
        return {row["code"] for row in raised.exception.errors}

    def invocation(self, stage):
        path = self.result_dir / provenance.STAGES[stage][1] / "invocation.json"
        return path, json.loads(path.read_text())

    @staticmethod
    def replace_option(argv, option, value):
        argv[argv.index(option) + 1] = str(value)

    def test_passed_record_reports_actual_alias_and_hash_equivalent_pin(self):
        record = provenance.audit(self.run, repository_root=self.root)
        self.assertEqual(record["status"], "passed")
        self.assertEqual(record["coverage"]["expected_results"], 1)
        self.assertEqual(len(record["call_records"]), 4)
        self.assertTrue(record["tools"]["all_hashes_equivalent"])
        self.assertEqual(record["c02_tool_lock_ref"], provenance.reference(self.tool_lock, self.root))
        self.assertEqual(record["sentinel_absence"]["status"], "passed")
        self.assertTrue(all(row["status"] == "absent"
                            for row in record["sentinel_absence"]["paths"].values()))
        self.assertEqual(record["tool_path_policy"]["path_divergence_status"],
                         "distinct_paths_with_sha256_equivalent_bytes")
        discover = next(row for row in record["call_records"] if row["stage"] == "discover")
        self.assertEqual(Path(discover["executable_path"]).resolve(), (self.actual_tools / "zkfDO").resolve())

    def test_incomplete_denominator_refuses_record_creation(self):
        (self.result_dir / "result.json").unlink()
        output = self.run / "actual-tool-provenance.v4.json"
        codes = self.error_codes(lambda: provenance.write_new(output,
            provenance.audit(self.run, repository_root=self.root)))
        self.assertIn("active_measurement_incomplete", codes)
        self.assertIn("active_result_missing", codes)
        self.assertFalse(output.exists())

    def test_result_identity_mismatch_is_rejected(self):
        path = self.result_dir / "result.json"
        result = json.loads(path.read_text()); result["commit_sha"] = "9" * 40
        self.write_json(path, result)
        self.assertIn("active_result_identity_mismatch",
                      self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root)))

    def test_wrong_actual_executable_is_rejected(self):
        path = self.result_dir / "discover-call/invocation.json"
        invocation = json.loads(path.read_text()); invocation["argv"][0] = str(self.recovery_tools / "zkfDO")
        self.write_json(path, invocation)
        self.assertIn("stage_executable_or_subcommand_mismatch",
                      self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root)))

    def test_wrong_or_extra_tool_argument_is_rejected(self):
        path = self.result_dir / "prepare-call/invocation.json"
        invocation = json.loads(path.read_text())
        index = invocation["argv"].index("--circom-bin") + 1
        invocation["argv"][index] = str(self.recovery_tools / "circom")
        invocation["argv"].extend(["--other-bin", "/tmp/unknown-tool"])
        self.write_json(path, invocation)
        codes = self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root))
        self.assertIn("stage_tool_argument_mismatch", codes)

    def test_source_and_output_paths_cannot_escape_or_reuse_an_old_checkout(self):
        cases = (("compile", None, 1, self.root / "runs/c02-corpus-2026-10-02/old/main.circom"),
                 ("compile", "-o", None, self.root / "outside/original"),
                 ("discover", "--entrypoint", None, self.root / "old-checkout/main.circom"),
                 ("discover", "--output", None, self.root / "outside/discovery"),
                 ("prepare", "--output", None, self.root / "outside/prepared"),
                 ("plan", "--output", None, self.root / "outside/plan.json"))
        for stage, option, index, replacement in cases:
            with self.subTest(stage=stage, option=option, replacement=replacement):
                path, original = self.invocation(stage)
                changed = json.loads(json.dumps(original))
                if option is None:
                    changed["argv"][index] = str(replacement)
                else:
                    self.replace_option(changed["argv"], option, replacement)
                self.write_json(path, changed)
                codes = self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root))
                self.assertIn("active_data_path_or_argument_mismatch", codes)
                self.write_json(path, original)

    def test_unexpected_frontend_verbs_are_rejected(self):
        for stage, index in (("discover", 1), ("prepare", 2), ("plan", 2)):
            path, original = self.invocation(stage)
            for verb in ("run", "evaluate", "review", "lift"):
                with self.subTest(stage=stage, verb=verb):
                    changed = json.loads(json.dumps(original)); changed["argv"][index] = verb
                    self.write_json(path, changed)
                    codes = self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root))
                    self.assertIn("stage_executable_or_subcommand_mismatch", codes)
                    self.assertIn("active_data_path_or_argument_mismatch", codes)
            self.write_json(path, original)

    def test_library_paths_remain_anchored_in_recovery_checkout(self):
        outside = self.root / "outside-library"; outside.mkdir()
        result_path = self.result_dir / "result.json"
        result = json.loads(result_path.read_text()); result["library_paths"] = [str(outside)]
        self.write_json(result_path, result)
        for stage, flag in (("compile", "-l"), ("discover", "--library-path")):
            path, invocation = self.invocation(stage)
            self.replace_option(invocation["argv"], flag, outside)
            self.write_json(path, invocation)
        self.assertIn("active_library_path_contract_mismatch",
                      self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root)))

    def test_prepare_and_plan_fixed_policy_arguments_are_enforced(self):
        path, original = self.invocation("prepare")
        changed = json.loads(json.dumps(original)); self.replace_option(changed["argv"], "--strategy", "largest-first")
        self.write_json(path, changed)
        self.assertIn("active_data_path_or_argument_mismatch",
                      self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root)))
        self.write_json(path, original)
        path, changed = self.invocation("plan")
        self.replace_option(changed["argv"], "--prepared", self.root / "old-run/prepared.json")
        self.write_json(path, changed)
        self.assertIn("active_data_path_or_argument_mismatch",
                      self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root)))

    def test_config_generated_source_uses_recovery_generated_directory_and_repository_project(self):
        generated = self.checkout.parent / "config-generated-after/generated.circom"
        generated.parent.mkdir(); generated.write_text("pragma circom 2.2.3;\n")
        inventory_path = self.run / "entrypoints-after.v4.json"
        inventory = json.loads(inventory_path.read_text())
        entry = inventory["repositories"][0]["entries"][0]
        entry.update(kind="config_generated", path=str(generated),
                     metadata={"path": str(generated)}, source_path="circuits/template.circom")
        self.write_json(inventory_path, inventory)
        selection_path = self.run / "final-measurement-selection.v4.json"
        selection = json.loads(selection_path.read_text())
        selection["after_inventory_ref"] = provenance.reference(inventory_path, self.root)
        self.write_json(selection_path, selection)
        result_path = self.result_dir / "result.json"
        result = json.loads(result_path.read_text())
        result["entrypoint_kind"] = "config_generated"
        result["library_paths"] = [str(self.checkout), str(generated.parent)]
        self.write_json(result_path, result)
        path, invocation = self.invocation("compile")
        invocation["argv"][1] = str(generated); invocation["argv"].extend(["-l", str(generated.parent)])
        self.write_json(path, invocation)
        path, invocation = self.invocation("discover")
        self.replace_option(invocation["argv"], "--project", self.checkout.parent)
        self.replace_option(invocation["argv"], "--entrypoint", generated)
        invocation["argv"].extend(["--library-path", str(generated.parent)])
        self.write_json(path, invocation)
        record = provenance.audit(self.run, repository_root=self.root)
        self.assertEqual(record["active_data_path_policy"]["status"], "passed")
        self.assertTrue(all(row["data_path_validation"] == "passed" for row in record["call_records"]))

    def test_config_generated_source_outside_fixed_generated_directory_is_rejected(self):
        outside = self.checkout / "circuits/generated.circom"
        inventory_path = self.run / "entrypoints-after.v4.json"
        inventory = json.loads(inventory_path.read_text())
        entry = inventory["repositories"][0]["entries"][0]
        entry.update(kind="config_generated", path=str(outside), metadata={"path": str(outside)})
        self.write_json(inventory_path, inventory)
        selection_path = self.run / "final-measurement-selection.v4.json"
        selection = json.loads(selection_path.read_text())
        selection["after_inventory_ref"] = provenance.reference(inventory_path, self.root)
        self.write_json(selection_path, selection)
        result_path = self.result_dir / "result.json"
        result = json.loads(result_path.read_text()); result["entrypoint_kind"] = "config_generated"
        self.write_json(result_path, result)
        path, invocation = self.invocation("compile"); invocation["argv"][1] = str(outside); self.write_json(path, invocation)
        path, invocation = self.invocation("discover")
        self.replace_option(invocation["argv"], "--project", self.checkout.parent)
        self.replace_option(invocation["argv"], "--entrypoint", outside)
        self.write_json(path, invocation)
        self.assertIn("active_entrypoint_path_contract_mismatch",
                      self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root)))

    def test_alias_bytes_must_equal_recovery_pin(self):
        (self.actual_tools / "zkfDO").write_bytes(b"different executable\n")
        self.assertIn("actual_alias_recovery_hash_mismatch",
                      self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root)))

    def test_c02_tool_lock_must_pin_actual_path_and_hash(self):
        lock = json.loads(self.tool_lock.read_text())
        lock["tools"][0]["sha256"] = "0" * 64
        self.write_json(self.tool_lock, lock)
        self.assertIn("c02_tool_lock_actual_alias_mismatch",
                      self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root)))

    def test_forbidden_tool_sentinel_must_be_absent_even_as_a_path(self):
        sentinel = self.root / "unexpected-zkfuzz"
        sentinel.write_text("must remain unused\n")
        old = provenance.FORBIDDEN_ZKFUZZ
        provenance.FORBIDDEN_ZKFUZZ = str(sentinel)
        self.addCleanup(setattr, provenance, "FORBIDDEN_ZKFUZZ", old)
        invocation_path = self.result_dir / "prepare-call/invocation.json"
        invocation = json.loads(invocation_path.read_text())
        index = invocation["argv"].index("--zkfuzz-bin") + 1
        invocation["argv"][index] = str(sentinel)
        self.write_json(invocation_path, invocation)
        self.assertIn("forbidden_tool_sentinel_exists",
                      self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root)))

    def test_missing_expected_invocation_is_rejected(self):
        (self.result_dir / "compile-call/invocation.json").unlink()
        codes = self.error_codes(lambda: provenance.audit(self.run, repository_root=self.root))
        self.assertIn("call_invocation_record_missing", codes)
        self.assertIn("expected_invocation_missing", codes)

    def test_record_writer_is_create_only(self):
        output = self.run / "actual-tool-provenance.v4.json"
        provenance.write_new(output, provenance.audit(self.run, repository_root=self.root))
        before = output.read_bytes()
        with self.assertRaises(FileExistsError):
            provenance.write_new(output, provenance.audit(self.run, repository_root=self.root))
        self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
