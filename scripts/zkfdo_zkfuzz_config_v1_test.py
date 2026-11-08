"""Configuration tests use trusted synthetic metadata; no subprocess is launched."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import zkfdo_zkfuzz_config_v1 as config


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "synthetic-zkfuzz"
        self.binary.write_bytes(b"trusted fixture: never executed\n")
        self.binary_sha = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.profile = json.loads(config.DEFAULTS_PROFILE_PATH.read_text())
        self.defaults = copy.deepcopy(self.profile["mutation_config"])
        self.profile.update(status="ready", binary_sha256=self.binary_sha)
        self.profile["source_files"] = []
        for name in ("main.rs", "input_user.rs", "mutation_config.rs"):
            path = self.root / name
            path.write_text("synthetic source reference " + name)
            self.profile["source_files"].append(self.reference(path))
        receipt = self.root / "paired-probe.json"
        receipt.write_text('{"kind":"synthetic trusted profile fixture"}\n')
        self.profile["attestation"] = {"status": "passed", "paired_probe": self.reference(receipt)}
        self.profile_path = self.root / "defaults.json"
        self.write_profile()
        self.tool = {"path": str(self.binary), "sha256": self.binary_sha,
                     "cwd": str(self.root), "defaults_profile_path": str(self.profile_path)}
        self.settings = self.root / "settings.json"
        self.write_settings({"seed": 2026110501})

    def reference(self, path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def write_profile(self):
        self.profile_path.write_text(json.dumps(self.profile))

    def write_settings(self, value):
        self.settings.write_text(json.dumps(value))

    def argv(self, *extra):
        return [str(self.binary), "circuit.circom", "-l", "sources",
                "--path_to_mutation_setting", "settings.json", *extra]

    def resolve(self, *extra):
        return config.resolve_configuration(self.argv(*extra), self.tool)

    def test_source_constructor_has_exactly_29_fields_and_hidden_defaults(self):
        source = config.ROOT / ".external/zkFuzz/src/mutator/mutation_config.rs"
        import re
        declared = set(re.findall(r"pub ([a-z_]+):", source.read_text()))
        self.assertEqual(declared, config.FIELDS)
        self.assertEqual(len(self.defaults), 29)
        self.assertEqual(self.defaults["random_value_probs"], [0.15, 0.34, 0.01, 0.5])
        self.assertEqual(self.defaults["num_eliminated_individuals"], 5)
        self.assertEqual(self.defaults["operator_mutation_rate"], 0.1)
        self.assertEqual(self.defaults["runtime_mutation_rate"], 0.3)
        self.assertFalse(self.defaults["dissable_heuristic_for_invalid_array_subscript"])
        self.assertEqual(self.defaults["random_value_ranges"][-1][-1],
                         "21888242871839275222246405745257275088548364400416034343698204186575808495617")

    def test_materialization_expands_defaults_and_overrides_only_seed(self):
        base = {"seed": 17, "operator_mutation_rate": 0.7, "max_generations": 0}
        before = copy.deepcopy(base)
        result = config.materialize_settings(base, 91, self.tool)
        self.assertEqual(result, {**self.defaults, **base, "seed": 91})
        self.assertEqual(base, before)
        self.assertEqual(len(result), 29)
        self.write_settings(result)
        resolved = self.resolve()
        self.assertEqual(resolved["mutation_config"], result)
        self.assertTrue(resolved["provenance"]["mutation_settings_file"]["all_29_fields_explicit"])

    def test_seed_only_and_materialized_input_resolve_identically(self):
        before = self.resolve()
        self.write_settings(config.materialize_settings({}, 2026110501, self.tool))
        after = self.resolve()
        self.assertTrue(config.compare_w_s(before, after)["equal"])
        self.assertNotEqual(before["provenance"]["mutation_settings_file"]["sha256"],
                            after["provenance"]["mutation_settings_file"]["sha256"])

    def test_unattested_profile_and_changed_evidence_are_rejected(self):
        self.profile["status"] = "awaiting_binary_probe"
        self.write_profile()
        with self.assertRaisesRegex(config.ConfigurationError, "not ready"):
            self.resolve()
        self.profile["status"] = "ready"
        self.write_profile()
        (self.root / "paired-probe.json").write_text("changed")
        with self.assertRaisesRegex(config.ConfigurationError, "evidence SHA256"):
            self.resolve()

    def test_profile_binary_and_source_binding_are_enforced(self):
        self.binary.write_bytes(b"changed fixture")
        with self.assertRaisesRegex(config.ConfigurationError, "executable SHA256"):
            self.resolve()
        self.binary.write_bytes(b"trusted fixture: never executed\n")
        self.profile["binary_sha256"] = "0" * 64
        self.write_profile()
        with self.assertRaisesRegex(config.ConfigurationError, "different zkFuzz"):
            self.resolve()
        self.profile["binary_sha256"] = self.binary_sha
        self.write_profile()
        (self.root / "input_user.rs").write_text("changed source")
        with self.assertRaisesRegex(config.ConfigurationError, "evidence SHA256"):
            self.resolve()

    def test_missing_invalid_duplicate_and_unknown_settings_fail(self):
        self.settings.unlink()
        with self.assertRaises(config.ConfigurationError):
            self.resolve()
        for raw in ('{', '[]', '{"seed":1,"seed":2}', '{"seed":1,"rate":0.1}',
                    '{"seed":1,"mutation_rate":NaN}'):
            with self.subTest(raw=raw):
                self.settings.write_text(raw)
                with self.assertRaises(config.ConfigurationError):
                    self.resolve()

    def test_reproducible_seed_must_be_a_nonzero_u64(self):
        for seed in (0, -1, 2**64, True, 1.5):
            with self.subTest(seed=seed):
                with self.assertRaises(config.ConfigurationError):
                    config.materialize_settings({}, seed, self.tool)
                self.write_settings({"seed": seed})
                with self.assertRaises(config.ConfigurationError):
                    self.resolve()
        with self.assertRaises(config.ConfigurationError):
            config.resolve_configuration([str(self.binary), "circuit.circom"], self.tool)

    def test_wrong_config_types_and_unsupported_methods_fail(self):
        for override in ({"input_population_size": True}, {"mutation_rate": "0.3"},
                         {"mutation_rate": 10**400},
                         {"save_fitness_scores": 1}, {"random_value_ranges": [[0, 1]]},
                         {"random_value_probs": [False]}, {"trace_mutation_method": "unknown"},
                         {"input_initialization_method": "custom"}, {"fitness_function": "custom"}):
            with self.subTest(override=override):
                self.write_settings({"seed": 1, **override})
                with self.assertRaises(config.ConfigurationError):
                    self.resolve()

    def test_unsupported_options_duplicate_flags_and_invalid_values_fail(self):
        for extra in (("--seed", "1"), ("--show_stats_of_ast",), ("--r1cs",),
                      ("-l", "-unknown"),
                      ("-p", "bn128"), ("--search_mode", "unknown"),
                      ("--prime", "unknown"), ("--debug_prime", "not-an-integer"),
                      ("--save_output", "--save_output"), ("--search_mode",)):
            with self.subTest(extra=extra):
                with self.assertRaises(config.ConfigurationError):
                    self.resolve(*extra)

    def test_static_checks_and_actual_flags_are_recorded(self):
        standard = self.resolve()["semantic_settings"]
        self.assertEqual(standard["static_checks"],
                         {"unused_outputs": True, "lessthan": True, "constraint_asserts": True})
        disabled = self.resolve("--constraint_assert_dissabled", "--lessthan_dissabled",
                                "--search_mode=off")["semantic_settings"]
        self.assertEqual(disabled["static_checks"],
                         {"unused_outputs": False, "lessthan": False, "constraint_asserts": False})
        self.assertFalse(disabled["mutation_config_active"])
        for mode in ("quick", "full", "heuristics", "ga"):
            self.assertTrue(self.resolve("--search_mode", mode)["semantic_settings"]["static_checks"]["unused_outputs"])

    def test_whitelist_preserves_spaces_empty_lines_and_rust_line_rules(self):
        whitelist = self.root / "white.txt"
        whitelist.write_bytes(b" IsZero \nNum2Bits\n\nX\r\ntrail\r")
        result = self.resolve("--path_to_whitelist", "white.txt")
        self.assertEqual(result["provenance"]["whitelist_file"]["lines"],
                         [" IsZero ", "Num2Bits", "", "X", "trail\r"])
        self.assertIn(" IsZero ", result["semantic_settings"]["whitelist"])
        whitelist.unlink()
        with self.assertRaises(config.ConfigurationError):
            self.resolve("--path_to_whitelist", "white.txt")

    def test_effective_whitelist_set_equality_ignores_order_but_not_spaces(self):
        baseline = self.resolve()
        whitelist = self.root / "white.txt"
        whitelist.write_text("Num2Bits\nIsZero\nIsZero\n")
        self.assertTrue(config.compare_w_s(baseline, self.resolve("--path_to_whitelist", "white.txt"))["equal"])
        whitelist.write_text("Num2Bits\nIsZero \n")
        self.assertFalse(config.compare_w_s(baseline, self.resolve("--path_to_whitelist", "white.txt"))["equal"])

    def test_w_s_transport_paths_are_separate_but_seed_and_all_29_fields_compare(self):
        left = self.resolve()
        right = copy.deepcopy(left)
        right["argv"][1] = "other-wrapper.circom"
        right["execution_paths"] = {"input_program": "different", "link_libraries": ["elsewhere"]}
        self.assertTrue(config.compare_w_s(left, right)["equal"])
        for field, value in left["mutation_config"].items():
            changed = copy.deepcopy(right)
            if type(value) is bool:
                replacement = not value
            elif type(value) in (int, float):
                replacement = value + 1
            elif isinstance(value, list):
                replacement = value + value[:1]
            else:
                replacement = {"random": "coverage", "constant_operator": "constant", "error": "const"}[value]
            changed["mutation_config"][field] = replacement
            with self.subTest(field=field):
                result = config.compare_w_s(left, changed)
                self.assertFalse(result["equal"])
                self.assertEqual(result["differences"][0]["field"], "mutation_config." + field)

    def test_runtime_configuration_is_never_fabricated_from_initial_input(self):
        result = self.resolve()
        self.assertIsNone(result["provenance"]["runtime_mutation_config"])
        self.assertEqual(result["mutation_config"]["random_value_probs"], [0.15, 0.34, 0.01, 0.5])

    def test_literal_none_settings_file_is_not_mistaken_for_whitelist_sentinel(self):
        (self.root / "none").write_text('{"seed":73,"max_generations":0}')
        result = config.resolve_configuration([str(self.binary), "circuit.circom"], self.tool)
        self.assertEqual(result["mutation_config"]["seed"], 73)
        self.assertEqual(result["mutation_config"]["max_generations"], 0)
        self.assertEqual(result["semantic_settings"]["whitelist"], ["IsZero", "Num2Bits"])


if __name__ == "__main__":
    unittest.main()
