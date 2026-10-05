"""C-03 v2 coverage tests with synthetic metadata and injected, inert runners."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import c03_environment_v2 as env


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value, dict) else value)
        return path

    def tool(self, name, version):
        path = self.base / ("trusted-" + name)
        path.write_text("inert tool identity; never executed")
        return {"argv": [str(path)], "version": version,
                "files": [{"path": str(path), "sha256": env.v1.digest(path)}]}

    def tools(self):
        return {"git": self.tool("git", "2.50.0"), "npm": self.tool("npm", "11.12.1")}

    def test_nested_lockless_package_is_not_owned_by_unrelated_root_lock(self):
        self.write("package.json", {"name": "root"})
        self.write("package-lock.json", {})
        self.write("circuits/package.json", {"name": "independent"})
        source = self.write("circuits/main.circom", "metadata placeholder")
        plans = env.plan_installations(self.repo, [source])
        self.assertEqual([p["install_root"] for p in plans], [str(self.repo), str(self.repo / "circuits")])
        self.assertEqual([p["command"] for p in plans], ["ci", "install"])
        self.assertFalse(plans[1]["lockfile_present"])

    def test_explicit_workspace_owns_its_member_and_avoids_duplicate_install(self):
        self.write("package.json", {"workspaces": ["packages/*"]})
        self.write("package-lock.json", {})
        self.write("packages/circuits/package.json", {})
        source = self.write("packages/circuits/src/main.circom", "metadata placeholder")
        plans = env.plan_installations(self.repo, [source])
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["install_root"], str(self.repo))

    def test_workspace_negative_pattern_preserves_independent_package(self):
        self.write("package.json", {"workspaces": ["packages/*", "!packages/separate"]})
        self.write("package-lock.json", {})
        self.write("packages/separate/package.json", {})
        source = self.write("packages/separate/main.circom", "metadata placeholder")
        plans = env.plan_installations(self.repo, [source])
        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[1]["install_root"], str(self.repo / "packages/separate"))

    def test_single_glob_does_not_own_deeper_nested_package(self):
        self.write("package.json", {"workspaces": ["packages/*"]})
        self.write("package-lock.json", {})
        self.write("packages/parent/package.json", {})
        self.write("packages/parent/independent/package.json", {})
        source = self.write("packages/parent/independent/main.circom", "metadata placeholder")
        plans = env.plan_installations(self.repo, [source])
        self.assertEqual(plans[-1]["install_root"], str(self.repo / "packages/parent/independent"))

    def test_pnpm_declared_membership_and_exclusion_are_read_as_metadata(self):
        self.write("package.json", {})
        self.write("pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
        self.write("pnpm-workspace.yaml", "packages:\n  - 'packages/**'\n  - '!packages/separate'\n")
        self.write("packages/separate/package.json", {})
        source = self.write("packages/separate/main.circom", "metadata placeholder")
        plans = env.plan_installations(self.repo, [source])
        self.assertEqual([p["manager"] for p in plans], ["pnpm", "npm"])

    def test_new_submodule_package_is_covered_after_initialization(self):
        self.write("package.json", {})
        known = self.write("circuits/main.circom", "metadata placeholder")
        calls = []
        def runner(argv, directory, cap, cwd, isolated):
            calls.append((list(argv), cwd))
            if "submodule" in argv:
                self.write("submodules/circuit-kit/package.json", {})
                self.write("submodules/circuit-kit/lib/template.circom", "metadata placeholder")
            if "ls-files" in argv:
                directory.mkdir()
                output = directory / "stdout.log"
                output.write_bytes(b"circuits/main.circom\0submodules/circuit-kit/lib/template.circom\0README.md\0")
                return {"status": "success", "stdout": env.v1.ref(output)}
            return {"status": "success"}
        result = env.run_setup(self.repo, [known], self.base / "setup", self.tools(), runner=runner)
        self.assertEqual(result["status"], "success")
        self.assertIn("submodules/circuit-kit/lib/template.circom", result["tracked_circom_paths"])
        roots = {p["install_root"] for p in result["installation_plans"]}
        self.assertEqual(roots, {str(self.repo), str(self.repo / "submodules/circuit-kit")})
        self.assertTrue("submodule" in calls[0][0] and "ls-files" in calls[1][0])
        self.assertEqual(result["manual_intervention_count"], 0)
        self.assertEqual(result["zkfuzz_invocations"], 0)

    def test_failed_inventory_retains_known_paths_and_still_installs(self):
        self.write("package.json", {})
        known = self.write("circuits/main.circom", "metadata placeholder")
        calls = []
        def runner(argv, directory, cap, cwd, isolated):
            calls.append(list(argv))
            return {"status": "timeout" if "ls-files" in argv else "success"}
        result = env.run_setup(self.repo, [known], self.base / "setup", self.tools(), runner=runner)
        self.assertEqual(result["status"], "setup_failure")
        self.assertIn("tracked_inventory_timeout", result["failure_types"])
        self.assertEqual(result["installation_input_paths"], [str(known)])
        self.assertEqual(len(result["installation_plans"]), 1)
        self.assertEqual(calls[-1][1], "install")

    def test_incomplete_or_tampered_path_listing_is_not_complete_coverage(self):
        self.write("package.json", {})
        source = self.write("circuits/main.circom", "metadata placeholder")
        def runner(argv, directory, cap, cwd, isolated):
            if "ls-files" in argv:
                directory.mkdir()
                output = directory / "stdout.log"
                output.write_bytes(b"circuits/main.circom")
                return {"status": "success", "stdout": env.v1.ref(output)}
            return {"status": "success"}
        result = env.run_setup(self.repo, [source], self.base / "setup", self.tools(), runner=runner)
        self.assertEqual(result["status"], "setup_failure")
        self.assertEqual(result["tracked_inventory_status"], "unknown")
        self.assertEqual(result["installation_input_paths"], [str(source)])

    def test_existing_setup_directory_cannot_be_overwritten(self):
        path = self.base / "setup"
        path.mkdir()
        with self.assertRaises(FileExistsError):
            env.run_setup(self.repo, [], path, {})


if __name__ == "__main__":
    unittest.main()
