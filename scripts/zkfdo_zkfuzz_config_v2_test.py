#!/usr/bin/env python3
"""Platform-profile and native-probe binding checks; no tool processes run."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import zkfdo_zkfuzz_config_v2 as config


class PlatformProfileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "zkfuzz"
        self.binary.write_bytes(b"synthetic native binary; never executed")
        self.binary_sha = self.ref(self.binary)["sha256"]
        original = json.loads(config.DEFAULTS_PROFILE_PATH.read_text())
        self.profile = {key: copy.deepcopy(original[key]) for key in (
            "mutation_config", "default_whitelist", "semantic_defaults")}
        self.profile.update(schema="zkfuzz-defaults-v2", status="ready", platform="linux",
                            architecture="aarch64", binary_sha256=self.binary_sha)
        self.profile["source_files"] = [self.write(name, {"fixture": name}) for name in (
            "main.rs", "input_user.rs", "mutation_config.rs")]
        self.seed = 73
        defaults = {**self.profile["mutation_config"], "seed": self.seed}
        observations = []
        for arm in ("seed-only", "expanded"):
            candidate = self.write(arm + "-candidate.json", {
                "5_flag": {"synthetic": True}, "6_target_output": "1", "7_assignment": {"x": "1"}})
            candidate["mutation_config"] = defaults
            observations.append(self.write(arm + "-observation.json", {
                "binary": {"sha256": self.binary_sha}, "status": "completed",
                "measurement_valid": True, "cleanup_complete": True, "candidates": [candidate]}))
        self.probe = {"schema": "zkfuzz-settings-paired-probe-v2", "platform": "linux",
                      "architecture": "aarch64", "binary_sha256": self.binary_sha,
                      "equivalent": True, "checks": {key: True for key in (
                          "5_flag", "6_target_output", "7_assignment", "runtime_config")},
                      "observations": observations,
                      "settings": [self.write("seed-settings.json", {"seed": self.seed}),
                                   self.write("expanded-settings.json", defaults)]}
        self.profile["attestation"] = {"status": "passed", "binary_sha256": self.binary_sha}
        self.profile_path = self.root / "linux-profile.json"
        self.tool = {"path": str(self.binary), "sha256": self.binary_sha,
                     "defaults_profile_path": str(self.profile_path)}
        self.update()
        self.addCleanup(patch.stopall)
        patch.object(config.sys, "platform", "linux").start()
        patch.object(config.platform, "machine", return_value="aarch64").start()

    def ref(self, path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data))
        return self.ref(path)

    def update(self):
        self.profile["attestation"]["paired_probe"] = self.write("paired-probe.json", self.probe)
        self.profile_path.write_text(json.dumps(self.profile))

    def test_native_manifest_profile_materializes_and_resolves(self):
        materialized = config.materialize_settings({}, 9, self.tool)
        self.assertEqual(materialized, {**self.profile["mutation_config"], "seed": 9})
        settings = self.write("settings.json", materialized)
        resolved = config.resolve_configuration([str(self.binary), "synthetic.circom",
            "--path_to_mutation_setting", settings["path"]], self.tool)
        self.assertEqual(resolved["provenance"]["defaults_profile"]["path"], str(self.profile_path.resolve()))
        self.assertEqual(resolved["mutation_config"], materialized)

    def test_non_darwin_has_no_mac_profile_fallback(self):
        del self.tool["defaults_profile_path"]
        with self.assertRaisesRegex(config.ConfigurationError, "platform-specific"):
            config.materialize_settings({}, 1, self.tool)

    def test_wrong_platform_architecture_and_binary_are_rejected(self):
        for key, value, expected in (("platform", "darwin", "platform"),
                                     ("architecture", "x86_64", "architecture"),
                                     ("binary_sha256", "0" * 64, "different zkFuzz")):
            with self.subTest(key=key):
                old = self.profile[key]
                self.profile[key] = value
                self.update()
                with self.assertRaisesRegex(config.ConfigurationError, expected):
                    config.materialize_settings({}, 1, self.tool)
                self.profile[key] = old

    def test_mac_attestation_cannot_be_relabelled_linux(self):
        self.probe["binary_sha256"] = "a" * 64
        self.update()
        with self.assertRaisesRegex(config.ConfigurationError, "binding differs"):
            config.materialize_settings({}, 1, self.tool)

    def test_invalid_observation_is_rejected(self):
        observation = json.loads(Path(self.probe["observations"][0]["path"]).read_text())
        observation["measurement_valid"] = False
        self.probe["observations"][0] = self.write("seed-only-observation.json", observation)
        self.update()
        with self.assertRaisesRegex(config.ConfigurationError, "observation is invalid"):
            config.materialize_settings({}, 1, self.tool)

    def test_claimed_equivalence_requires_matching_raw_observations(self):
        observation = json.loads(Path(self.probe["observations"][0]["path"]).read_text())
        changed = self.write("changed-candidate.json", {
            "5_flag": {"synthetic": True}, "6_target_output": "2", "7_assignment": {"x": "1"}})
        changed["mutation_config"] = observation["candidates"][0]["mutation_config"]
        observation["candidates"] = [changed]
        self.probe["observations"][0] = self.write("seed-only-observation.json", observation)
        self.update()
        with self.assertRaisesRegex(config.ConfigurationError, "observations differ"):
            config.materialize_settings({}, 1, self.tool)

    def test_manifest_can_pin_profile_digest(self):
        self.tool["defaults_profile_sha256"] = "f" * 64
        with self.assertRaisesRegex(config.ConfigurationError, "profile SHA256"):
            config.materialize_settings({}, 1, self.tool)

    def test_empty_linux_template_fails_closed(self):
        self.tool["defaults_profile_path"] = str(config.ROOT / "configs/zkfuzz_defaults_2.2.1_linux-aarch64_v1.json")
        with self.assertRaisesRegex(config.ConfigurationError, "not ready"):
            config.materialize_settings({}, 1, self.tool)

    def test_legacy_profile_copy_is_rejected(self):
        self.profile["schema"] = "zkfuzz-defaults-v1"
        self.update()
        with self.assertRaisesRegex(config.ConfigurationError, "legacy defaults profile"):
            config.materialize_settings({}, 1, self.tool)


if __name__ == "__main__":
    unittest.main()
