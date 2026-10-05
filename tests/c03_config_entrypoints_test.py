"""Strict config-only main generation; no compiler, package scripts or witness."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("c03_config", Path(__file__).resolve().parents[1] / "scripts/c03_config_entrypoints.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)


class ConfigEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        self.package = self.repo / "packages/circuits"
        (self.package / "src").mkdir(parents=True)
        (self.package / "src/arithmetic.circom").write_text("pragma circom 2.2.3;\ntemplate Arithmetic(n) { signal input x; signal output y; y <== x+n; }\n")
        self.kit = {"dirCircuits": "./src", "circuits": "./circuits.json", "version": "2.1.5", "optimization": 2}
        self.entry = {"file": "arithmetic", "template": "Arithmetic", "params": [3], "pubs": ["x"]}
        self.write()

    def write(self, entries=None):
        (self.package / "circomkit.json").write_text(json.dumps(self.kit))
        (self.package / "circuits.json").write_text(json.dumps(entries if entries is not None else {"arithmetic-test": self.entry}))

    def result(self):
        return config.discover_config_entrypoints(self.repo)

    def test_nested_paths_and_public_are_generated_without_running_package_scripts(self):
        (self.package / "package.json").write_text('{"scripts":{"prepare":"exit 99"}}')
        result = config.generate_config_entrypoints(self.repo, self.base / "generated")
        row = result["entries"][0]
        text = Path(row["path"]).read_text()
        self.assertIn("component main {public [x]} = Arithmetic(3);", text)
        self.assertEqual(row["source_path"], "packages/circuits/src/arithmetic.circom")
        self.assertEqual(row["sha256"], config.digest(row["path"]))
        self.assertEqual(row["declared_compile_settings"]["optimization"], 2)
        self.assertEqual(result["repository_programs_executed"], 0)
        self.assertEqual(len(list(self.repo.rglob("*.circom"))), 1)

    def test_generation_is_deterministic_for_same_relative_layout(self):
        first = config.generate_config_entrypoints(self.repo, self.base / "first")
        second = config.generate_config_entrypoints(self.repo, self.base / "other")
        self.assertEqual(first["entries"][0]["sha256"], second["entries"][0]["sha256"])
        self.assertEqual(first["entries"][0]["logical_id_sha256"], second["entries"][0]["logical_id_sha256"])

    def test_existing_outputs_and_source_tree_are_never_overwritten(self):
        with self.assertRaises(ValueError):
            config.generate_config_entrypoints(self.repo, self.repo / "generated")
        existing = self.base / "existing"
        existing.mkdir()
        marker = existing / "keep"
        marker.write_text("historical")
        with self.assertRaises(FileExistsError):
            config.generate_config_entrypoints(self.repo, existing)
        self.assertEqual(marker.read_text(), "historical")

    def test_public_alias_supported_and_conflict_rejected(self):
        self.entry["public"] = ["x"]
        self.write()
        self.assertEqual(self.result()["entries"][0]["generation_status"], "ready")
        self.entry["public"] = ["y"]
        self.write()
        self.assertEqual(self.result()["entries"][0]["failure_type"], "config_ambiguous_public")

    def test_duplicate_json_keys_cannot_silently_choose_a_definition(self):
        (self.package / "circuits.json").write_text('{"same": {}, "same": {}}')
        result = self.result()
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["failures"][0]["failure_type"], "config_duplicate_json_key")

    def test_bad_entry_does_not_drop_valid_sibling_or_disappear_from_denominator(self):
        self.write({"good": self.entry, "bad": {"file": "missing", "template": "Missing"}})
        rows = self.result()["entries"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["failure_type"], "config_missing_source")
        self.assertEqual(rows[1]["generation_status"], "ready")

    def test_executable_parameter_expressions_are_not_evaluated(self):
        for parameter in ("2 ** 8", "process.exit()", 1.5, True, None, []):
            with self.subTest(parameter=parameter):
                self.entry["params"] = [parameter]
                self.write()
                self.assertEqual(self.result()["entries"][0]["failure_type"], "config_unsupported_params")

    def test_integer_array_parameters_preserve_shape_and_order(self):
        self.entry["params"] = [[3, -1], [[8, 2], [1, 0]]]
        self.write()
        row = self.result()["entries"][0]
        self.assertEqual(row["literal_params"], ["[3, -1]", "[[8, 2], [1, 0]]"])

    def test_identifier_and_public_injection_cannot_enter_generated_source(self):
        self.entry["template"] = "Arithmetic(); component other = Arithmetic"
        self.write()
        self.assertEqual(self.result()["entries"][0]["failure_type"], "config_invalid_identifier")
        self.entry["template"] = "Arithmetic"
        self.entry["pubs"] = ["x]; other"]
        self.write()
        self.assertEqual(self.result()["entries"][0]["failure_type"], "config_invalid_identifier")

    def test_absolute_traversal_and_symlink_escapes_are_rejected(self):
        outside = self.base / "outside.circom"
        outside.write_text("not a corpus file")
        link = self.package / "src/link.circom"
        link.symlink_to(outside)
        for source in (str(outside), "../../../../outside", "link"):
            with self.subTest(source=source):
                self.entry["file"] = source
                self.write()
                self.assertEqual(self.result()["entries"][0]["failure_type"], "config_path_outside_checkout")

    def test_unreferenced_circuits_json_does_not_guess_execution_context(self):
        (self.package / "circomkit.json").unlink()
        result = self.result()
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["failures"][0]["failure_type"], "config_without_circomkit_context")

    def test_dependency_and_symlink_directories_are_not_enumerated(self):
        dependency = self.repo / "node_modules/pkg"
        dependency.mkdir(parents=True)
        (dependency / "circomkit.json").write_text("invalid")
        (self.repo / "linked-package").symlink_to(self.package, target_is_directory=True)
        self.assertEqual(len(self.result()["entries"]), 1)
        self.assertEqual(self.result()["failures"], [])

    def test_missing_config_has_typed_failure(self):
        (self.package / "circuits.json").unlink()
        result = self.result()
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["failures"][0]["failure_type"], "config_missing_file")

    def test_non_json_javascript_is_not_executed(self):
        marker = self.repo / "marker"
        (self.package / "circuits.json").write_text(f"require('fs').writeFileSync('{marker}', 'executed')")
        self.assertEqual(self.result()["failures"][0]["failure_type"], "config_invalid_json")
        self.assertFalse(marker.exists())

    def test_config_location_defaults_are_recorded(self):
        (self.package / "circuits").mkdir()
        (self.package / "circuits/arithmetic.circom").write_bytes((self.package / "src/arithmetic.circom").read_bytes())
        self.kit = {}
        self.write()
        row = self.result()["entries"][0]
        self.assertEqual(row["generation_status"], "ready")
        self.assertEqual(row["config_defaults_applied"], ["circuits", "dirCircuits"])


if __name__ == "__main__":
    unittest.main()
