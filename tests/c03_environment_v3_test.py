"""PnPM CLI spelling correction and complete setup-path regression controls."""

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import c03_environment_v3 as env


class EnvironmentV3Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()

    def tool(self, manager, version):
        path = self.base / ("trusted-" + manager)
        path.write_text("inert pinned test executable; not run")
        return {"argv": [str(path)], "files": [{"path": str(path), "sha256": env.v2.v1.digest(path)}], "version": version}

    def test_pnpm_uses_configuration_namespace_and_preserves_safety_options(self):
        tool = self.tool("pnpm", "10.34.6")
        plan = {"manager": "pnpm", "command": "install"}
        legacy = env.v2.install_command(plan, tool)
        corrected = env.install_command(plan, tool)
        self.assertIn("--manage-package-manager-versions=false", legacy)
        self.assertNotIn("--manage-package-manager-versions=false", corrected)
        self.assertNotIn("--package-manager-strict=false", corrected)
        self.assertIn("--config.manage-package-manager-versions=false", corrected)
        self.assertIn("--config.package-manager-strict=false", corrected)
        for flag in ("--ignore-scripts", "--ignore-pnpmfile", "--frozen-lockfile"):
            self.assertIn(flag, corrected)
        self.assertEqual([env._PNPM_OPTIONS.get(arg, arg) for arg in legacy], corrected)

    def test_npm_and_yarn_commands_are_unchanged(self):
        for manager, version in (("npm", "11.12.1"), ("yarn", "1.22.22")):
            tool = self.tool(manager, version)
            plan = {"manager": manager, "command": "ci"}
            self.assertEqual(env.install_command(plan, tool), env.v2.install_command(plan, tool))

    def test_other_executable_with_similar_options_is_not_rewritten(self):
        tool = self.tool("pnpm", "10.34.6")
        argv = ["/different/tool", "install", "--package-manager-strict=false"]
        self.assertEqual(env._correct_pnpm_argv(argv, tool), argv)

    def test_actual_setup_runner_receives_corrected_pnpm_not_only_helper_return_value(self):
        repo = self.base / "repo"; repo.mkdir()
        (repo / "package.json").write_text('{"name":"synthetic-empty"}')
        (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
        tools = {"git": self.tool("git", "2.50.1"), "pnpm": self.tool("pnpm", "10.34.6")}
        calls = []
        def runner(argv, directory, cap, cwd, isolated):
            calls.append(list(argv))
            if "ls-files" in argv:
                directory.mkdir(); output = directory / "stdout.log"; output.write_bytes(b"")
                return {"status": "success", "exit_code": 0, "stdout": env.v2.v1.ref(output)}
            return {"status": "success", "exit_code": 0}
        original = env.v2.install_command
        result = env.run_setup(repo, [], self.base / "setup", tools, runner=runner)
        self.assertEqual(result["status"], "success")
        self.assertIs(env.v2.install_command, original)
        self.assertIn("--config.manage-package-manager-versions=false", calls[-1])
        self.assertNotIn("--manage-package-manager-versions=false", calls[-1])
        self.assertEqual(result["manual_intervention_count"], 0)
        self.assertEqual(result["zkfuzz_invocations"], 0)

    def test_tool_hash_validation_still_applies(self):
        tool = self.tool("pnpm", "10.34.6")
        Path(tool["argv"][0]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "tool_hash_mismatch"):
            env.install_command({"manager": "pnpm"}, tool)

    def test_empty_offline_control_requires_command_success_and_all_markers_absent(self):
        tools = {"pnpm": self.tool("pnpm", "10.34.6"), "yarn": self.tool("yarn", "1.22.22")}
        tools_path = self.base / "tools.json"; tools_path.write_text(json.dumps(tools))
        def rejected(argv, directory, cap, cwd, isolated):
            self.assertIn("--offline", argv)
            self.assertIn("--ignore-scripts", argv)
            return {"status": "failure", "exit_code": 1}
        result = env.run_offline_controls(self.base / "rejected", tools_path, runner=rejected)
        self.assertFalse(result["passed"])
        self.assertTrue(all(not any(row["marker_presence"].values()) for row in result["controls"]))
        def script_ran(argv, directory, cap, cwd, isolated):
            (cwd / "lifecycle-ran").write_text("bad")
            return {"status": "success", "exit_code": 0}
        result = env.run_offline_controls(self.base / "script-ran", tools_path, runner=script_ran)
        self.assertFalse(result["passed"])

    def test_offline_control_never_overwrites_existing_results(self):
        path = self.base / "existing"; path.mkdir()
        with self.assertRaises(FileExistsError):
            env.run_offline_controls(path, self.base / "tools.json")


if __name__ == "__main__":
    unittest.main()
