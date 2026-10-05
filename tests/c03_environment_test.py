"""Metadata-only setup regressions; no registry access or repository code runs."""
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import c03_environment as env


class EnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.circuit = self.repo / "circuits/main.circom"
        self.circuit.parent.mkdir()
        self.circuit.write_text("// Non-executable metadata placeholder.\n")

    def write(self, relative, value):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value, dict) else value)
        return path

    def tool(self, name, version="11.12.1"):
        path = self.base / (name + "-trusted-tool")
        path.write_text("synthetic trusted tool identity only")
        return {"argv": [str(path)], "version": version,
                "files": [{"path": str(path), "sha256": env.digest(path)}]}

    def test_npm_ci_and_lockless_install_are_distinct(self):
        self.write("package.json", {})
        plan = env.plan_installations(self.repo, [self.circuit])[0]
        self.assertFalse(plan["lockfile_present"])
        self.assertEqual(plan["command"], "install")
        self.write("package-lock.json", {})
        plan = env.plan_installations(self.repo, [self.circuit])[0]
        self.assertEqual(plan["command"], "ci")
        self.assertIn("--ignore-scripts", env.install_command(plan, self.tool("npm")))

    def test_conflicting_locks_require_declared_manager(self):
        self.write("package.json", {})
        self.write("package-lock.json", {})
        self.write("yarn.lock", "# yarn lockfile v1\n")
        self.assertEqual(env.plan_installations(self.repo, [self.circuit])[0]["failure_type"],
                         "ambiguous_lockfiles")
        self.write("package.json", {"packageManager": "yarn@1.22.22"})
        plan = env.plan_installations(self.repo, [self.circuit])[0]
        self.assertEqual(plan["manager"], "yarn")
        self.assertEqual(len(plan["lockfiles"]), 2)
        self.assertEqual(plan["lockfile_selection"], "declared_manager")

    def test_declared_manager_does_not_override_unrelated_lock(self):
        self.write("package.json", {"packageManager": "yarn@1.22.22"})
        self.write("package-lock.json", {})
        self.assertEqual(env.plan_installations(self.repo, [self.circuit])[0]["failure_type"],
                         "declared_manager_lockfile_mismatch")

    def test_workspace_root_selected_over_nested_package(self):
        self.write("package.json", {"workspaces": ["packages/*"]})
        self.write("yarn.lock", "# yarn lockfile v1\n")
        self.write("packages/circuits/package.json", {})
        source = self.write("packages/circuits/src/main.circom", "// placeholder")
        plans = env.plan_installations(self.repo, [source])
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["install_root"], str(self.repo.resolve()))

    def test_independent_nested_packages_remain_distinct(self):
        self.write("package.json", {})
        self.write("package-lock.json", {})
        self.write("tools/package.json", {})
        self.write("tools/pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
        source = self.write("tools/circuits/main.circom", "// placeholder")
        plans = env.plan_installations(self.repo, [source])
        self.assertEqual([p["manager"] for p in plans], ["npm", "pnpm"])

    def test_ancestor_lockfile_selected_without_workspace_declaration(self):
        self.write("package.json", {})
        self.write("package-lock.json", {})
        self.write("circuits/package.json", {})
        self.assertEqual(len(env.plan_installations(self.repo, [self.circuit])), 1)

    def test_no_metadata_is_no_package_install_not_failure(self):
        self.assertEqual(env.plan_installations(self.repo, [self.circuit]), [])

    def test_modern_yarn_is_not_run_with_classic_contract(self):
        self.write("package.json", {})
        self.write("yarn.lock", "__metadata:\n  version: 8\n")
        self.assertEqual(env.plan_installations(self.repo, [self.circuit])[0]["failure_type"],
                         "unsupported_yarn_modern")

    def test_symlink_metadata_cannot_escape_repository(self):
        outside = self.base / "outside.json"
        outside.write_text("{}")
        (self.repo / "package.json").symlink_to(outside)
        self.assertEqual(env.plan_installations(self.repo, [self.circuit])[0]["failure_type"],
                         "invalid_package_metadata")
        self.assertIn("symlink", env.plan_installations(self.repo, [self.circuit])[0]["reason"])

    def test_parent_path_and_symlink_escape_are_rejected(self):
        result = env.plan_installations(self.repo, ["../outside/main.circom"])
        self.assertEqual(result[0]["failure_type"], "invalid_package_metadata")
        with self.assertRaisesRegex(ValueError, "path_outside_repository"):
            env.include_paths(self.repo, "../outside/main.circom")

    def test_include_order_preserves_root_and_nested_node_modules(self):
        source = self.write("packages/p/src/main.circom", "// placeholder")
        paths = env.include_paths(self.repo, source)
        self.assertEqual(paths[:3], [str(self.repo.resolve()), str(self.repo.resolve() / "node_modules"),
                                     str(source.resolve().parent)])
        self.assertIn(str(self.repo.resolve() / "packages/p/node_modules"), paths)
        self.assertEqual(len(paths), len(set(paths)))

    def test_tools_must_match_pins_and_not_corepack(self):
        tool = self.tool("npm")
        Path(tool["argv"][0]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "tool_hash_mismatch"):
            env._validate_tool(tool, "npm")
        with self.assertRaisesRegex(ValueError, "corepack"):
            env._validate_tool(self.tool("corepack"), "npm")

    def test_all_install_commands_disable_scripts_and_dynamic_manager(self):
        cases = [("npm", "11.12.1"), ("yarn", "1.22.22"), ("pnpm", "10.33.0")]
        for manager, version in cases:
            argv = env.install_command({"manager": manager, "command": "install"},
                                       self.tool(manager, version))
            self.assertIn("--ignore-scripts", argv)
            if manager != "npm":
                self.assertIn("--frozen-lockfile", argv)
            if manager == "pnpm":
                self.assertIn("--ignore-pnpmfile", argv)
                self.assertIn("--manage-package-manager-versions=false", argv)
            if manager == "yarn":
                self.assertIn("--no-default-rc", argv)

    def test_pnpm_executable_configuration_is_explicitly_unsupported(self):
        self.write("package.json", {})
        self.write("pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
        self.write("pnpm-workspace.yaml", "configDependencies:\n  hooks: '1.0.0'\n")
        self.assertEqual(env.plan_installations(self.repo, [self.circuit])[0]["failure_type"],
                         "unsupported_pnpm_executable_configuration")

    def test_environment_does_not_inherit_node_hooks_or_credentials(self):
        with patch.dict(os.environ, {"NODE_OPTIONS": "--require arbitrary.js",
                                    "NPM_TOKEN": "test-placeholder", "PATH": str(self.repo)}):
            isolated = env.isolated_environment(self.base / "raw", ["/trusted/bin"])
        self.assertNotIn("NODE_OPTIONS", isolated)
        self.assertNotIn("NPM_TOKEN", isolated)
        self.assertNotIn(str(self.repo), isolated["PATH"])
        self.assertNotIn("HOME", isolated)
        self.assertEqual(isolated["YARN_IGNORE_PATH"], "1")
        self.assertEqual(isolated["GIT_CONFIG_VALUE_1"], "never")

    def test_submodule_and_package_failure_are_retained_separately(self):
        self.write("package.json", {})
        tools = {"git": self.tool("git", "2.50.0"), "npm": self.tool("npm")}
        calls = []
        def runner(argv, directory, cap, cwd, isolated):
            calls.append(argv)
            return {"status": "timeout" if len(calls) == 1 else "success", "elapsed_seconds": 1.0}
        result = env.run_setup(self.repo, [self.circuit], self.base / "setup", tools, runner=runner)
        self.assertEqual(result["status"], "setup_failure")
        self.assertEqual(result["failure_types"], ["submodule_timeout"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][-4:], ["submodule", "update", "--init", "--recursive"])
        self.assertEqual(result["steps"][1]["status"], "success")
        self.assertEqual(result["manual_intervention_count"], 0)
        self.assertEqual(result["zkfuzz_invocations"], 0)

    def test_manager_unavailable_does_not_invoke_other_manager(self):
        self.write("package.json", {})
        self.write("yarn.lock", "# yarn lockfile v1\n")
        calls = []
        def runner(argv, *unused):
            calls.append(argv)
            return {"status": "success"}
        result = env.run_setup(self.repo, [self.circuit], self.base / "setup", 
                               {"git": self.tool("git", "2.50.0"), "npm": self.tool("npm")},
                               runner=runner)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["failure_types"], ["package_manager_unavailable"])

    def test_installed_npm_blocks_project_lifecycle_even_when_rc_requests_scripts(self):
        node, npm = shutil.which("node"), shutil.which("npm")
        if not node or not npm:
            self.skipTest("trusted local Node/npm unavailable")
        node, npm = str(Path(node).resolve()), str(Path(npm).resolve())
        version = subprocess.check_output([node, npm, "--version"], text=True,
                                          cwd=self.base, timeout=10).strip()
        if not version.startswith("11."):
            self.skipTest("test contract requires pinned npm 11")
        tool = {"argv": [node, npm], "version": version,
                "files": [{"path": p, "sha256": env.digest(p)} for p in (node, npm)]}
        self.write("package.json", {"name": "c03-empty-setup-control", "version": "1.0.0",
                                    "scripts": {"preinstall": "touch lifecycle-ran",
                                                "postinstall": "touch lifecycle-ran"}})
        self.write(".npmrc", "ignore-scripts=false\n")
        plan = env.plan_installations(self.repo, [self.circuit])[0]
        isolated = env.isolated_environment(self.base / "npm-control", [Path(node).parent])
        capture = subprocess.run(env.install_command(plan, tool) + ["--offline"],
                                 cwd=self.repo, env=isolated, capture_output=True, text=True,
                                 timeout=30, check=False)
        self.assertEqual(capture.returncode, 0, capture.stderr)
        self.assertFalse((self.repo / "lifecycle-ran").exists())
        self.assertTrue((self.repo / "package-lock.json").is_file())

    def test_setup_result_cannot_overwrite_a_previous_run(self):
        directory = self.base / "setup"
        directory.mkdir()
        with self.assertRaises(FileExistsError):
            env.run_setup(self.repo, [], directory, {})

    def test_invalid_package_json_is_failure_not_no_dependencies(self):
        self.write("package.json", "{broken}")
        self.assertEqual(env.plan_installations(self.repo, [self.circuit])[0]["failure_type"],
                         "invalid_package_metadata")

    def test_failure_classification_always_has_a_type(self):
        self.assertEqual(env._failure({"status": "failure"}, "package_install"),
                         "package_install_command_failed")
        self.assertEqual(env._failure({"status": "start_failure"}, "submodule"),
                         "submodule_start_failure")
        self.assertIsNone(env._failure({"status": "success"}, "package_install"))


if __name__ == "__main__":
    unittest.main()
