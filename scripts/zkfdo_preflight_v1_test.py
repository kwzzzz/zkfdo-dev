import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import zkfdo_preflight_v1 as preflight


class PreparationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zkfdo-preflight-")
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def profile(self, requirements):
        return {"revision_id": "revision-one", "revision_commit": "a" * 40,
                "requirements": requirements}

    def test_missing_inputs_prevent_fuzz_start_and_do_not_log_env_values(self):
        profile = self.profile([{"id": "jwt", "kind": "environment", "name": "RAW_JWT"},
                                {"id": "fixture", "kind": "file", "path": "input.json"}])
        receipt = preflight.check_revision(profile, self.root, {"RAW_JWT": "private-value"})
        self.assertEqual(receipt["status"], "preparation_assets_missing")
        self.assertNotIn("private-value", json.dumps(receipt))
        with self.assertRaisesRegex(preflight.PreflightFailed, "fixture"):
            preflight.require_ready(receipt)
        self.assertFalse(receipt["fuzzing_started"])
        self.assertEqual(receipt["checks"][0]["status"], "present")

    def test_empty_environment_is_missing(self):
        receipt = preflight.check_revision(self.profile([
            {"id": "jwt", "kind": "environment", "name": "RAW_JWT"}]), self.root, {"RAW_JWT": ""})
        self.assertEqual(receipt["failures"][0]["reason"], "environment_missing_or_empty")

    def test_wasm_lfs_pointer_and_invalid_binary_are_rejected(self):
        wasm = self.root / "input.wasm"
        profile = self.profile([{"id": "wasm", "kind": "wasm", "path": "input.wasm"}])
        for contents, reason in [(b"version https://git-lfs.github.com/spec/v1\n", "git_lfs_pointer"),
                                 (b"not wasm", "invalid_wasm_header"), (b"\x00asm\x01\x00\x00\x00", None)]:
            wasm.write_bytes(contents)
            receipt = preflight.check_revision(profile, self.root, {})
            self.assertEqual(receipt["checks"][0]["reason"], reason)
            if reason is None:
                preflight.require_ready(receipt)

    def test_input_key_comparison_never_exposes_values(self):
        (self.root / "input.json").write_text(json.dumps({"unexpected": "sensitive-fixture"}))
        receipt = preflight.check_revision(self.profile([
            {"id": "input", "kind": "json_keys", "path": "input.json", "keys": ["expected"]}]), self.root, {})
        self.assertEqual(receipt["failures"][0]["reason"], "main_input_keys_mismatch")
        self.assertNotIn("sensitive-fixture", json.dumps(receipt))

    def test_original_source_pin_change_is_failure(self):
        source = self.root / "tool.ts"
        source.write_text("original")
        profile = self.profile([{"id": "source", "kind": "file", "path": "tool.ts",
                                 "sha256": preflight.sha256(source)}])
        source.write_text("changed")
        self.assertEqual(preflight.check_revision(profile, self.root, {})["failures"][0]["reason"],
                         "asset_sha256_mismatch")

    def test_same_main_requires_identical_template_and_arguments(self):
        (self.root / "entry.circom").write_text("component main {public [x]} = Main(2, 3);")
        reference = self.root / "fixture.circom"
        reference.write_text("/*comment*/ component main = Main(2,3);")
        profile = self.profile([{"id": "main", "kind": "same_main", "path": "fixture.circom",
                                 "entrypoint": "entry.circom"}])
        preflight.require_ready(preflight.check_revision(profile, self.root, {}))
        reference.write_text("component main = Main(2,4);")
        with self.assertRaises(preflight.PreflightFailed):
            preflight.require_ready(preflight.check_revision(profile, self.root, {}))

    def test_executable_is_checked_without_running_it(self):
        local = self.root / "node_modules/.bin"
        local.mkdir(parents=True)
        tool = local / "yarn"
        tool.write_text("#!/bin/sh\nexit 99\n")
        tool.chmod(0o700)
        profile = self.profile([{"id": "yarn", "kind": "executable", "name": "yarn",
                                 "search_dirs": ["node_modules/.bin"]}])
        with patch("shutil.which", wraps=preflight.shutil.which) as which:
            preflight.require_ready(preflight.check_revision(profile, self.root, {"PATH": ""}))
            self.assertEqual(which.call_count, 1)

    def test_missing_revision_wrong_commit_or_changed_profile_rejected(self):
        profile = self.profile([{"id": "pkg", "kind": "directory", "path": "pkg"}])
        catalog = self.root / "profile.json"
        catalog.write_text(json.dumps({"schema": preflight.SCHEMA, "revisions": {"revision-one": profile}}))
        digest = preflight.sha256(catalog)
        self.assertEqual(preflight.load_revision_profile(catalog, "revision-one", digest, "a" * 40)["revision_id"],
                         "revision-one")
        for revision, commit in [("revision", None), ("revision-one", "b" * 40)]:
            with self.assertRaises(ValueError):
                preflight.load_revision_profile(catalog, revision, digest, commit)
        catalog.write_text(catalog.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            preflight.load_revision_profile(catalog, "revision-one", digest)

    def test_unknown_requirement_and_path_escape_fail_closed(self):
        profile = self.profile([{"id": "pkg", "kind": "file", "path": "../outside"}])
        self.assertEqual(preflight.check_revision(profile, self.root, {})["status"], "preparation_assets_missing")
        unknown = copy.deepcopy(profile)
        unknown["requirements"][0]["kind"] = "pretend_ready"
        with self.assertRaises(ValueError):
            preflight.check_revision(unknown, self.root, {})


if __name__ == "__main__":
    unittest.main()
