#!/usr/bin/env python3
"""Offline policy checks for the Docker base-input collector."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_b5_docker_base_inputs as collector  # noqa: E402
import n6_b5_r1cs_reference as reference  # noqa: E402


TOOLS = {"image": "docker.io/library/node@sha256:" + "a" * 64, "platform": "linux/amd64", "node": "22.23.3",
         "npm": "10.9.9", "corepack": "0.36.0", "yarn_classic": "1.22.22",
         "yarn_modern": "4.10.3", "pnpm": "9.15.9"}


class CollectorPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "project"
        self.package.mkdir()
        (self.package / "package.json").write_text('{"scripts":{"test":"npm run build && mocha test.js","build":"true"}}')

    def lock(self, name: str, content: str = "lock") -> Path:
        path = self.package / name
        path.write_text(content)
        return path

    def test_install_whitelist_and_lock_selection(self) -> None:
        cases = [
            ("package-lock.json", "", ["npm", "ci", "--ignore-scripts"]),
            ("yarn.lock", "classic", ["corepack", "yarn@1.22.22", "install", "--frozen-lockfile", "--ignore-scripts"]),
            ("yarn.lock", "__metadata: {}", ["corepack", "yarn@4.10.3", "install", "--immutable"]),
            ("pnpm-lock.yaml", "", ["corepack", "pnpm@9.15.9", "install", "--frozen-lockfile", "--ignore-scripts"]),
        ]
        for name, content, expected in cases:
            with self.subTest(name=name, content=content):
                lock = self.lock(name, content)
                try:
                    command, selected, _ = collector.choose_install(self.package, self.package, TOOLS)
                    self.assertEqual(command, expected)
                    self.assertEqual(selected, lock)
                finally:
                    lock.unlink()

    def test_wrong_package_manager_and_multiple_locks_fail(self) -> None:
        self.lock("package-lock.json")
        (self.package / "package.json").write_text('{"packageManager":"yarn@1.22.22"}')
        with self.assertRaisesRegex(collector.PolicyFailure, "packageManager"):
            collector.choose_install(self.package, self.package, TOOLS)
        self.lock("yarn.lock")
        with self.assertRaisesRegex(collector.PolicyFailure, "multiple lock"):
            collector.choose_install(self.package, self.package, TOOLS)

    def test_git_dependency_lock_keeps_install_command_and_commit(self) -> None:
        commit = "a" * 40
        lock = self.lock("package-lock.json", json.dumps({
            "name": "synthetic", "lockfileVersion": 3,
            "packages": {"node_modules/dep": {
                "resolved": f"git+https://github.com/public/dep.git#{commit}"}}}))
        command, selected, version = collector.choose_install(self.package, self.package, TOOLS)
        self.assertEqual(command, ["npm", "ci", "--ignore-scripts"])
        self.assertEqual(selected, lock)
        self.assertEqual(version, "npm@10.9.9")
        self.assertEqual(collector.github_ssh_git_config(lock), ({}, []))
        self.assertIn(commit, lock.read_text())

    def test_github_ssh_lock_uses_only_container_git_instead_of_without_network(self) -> None:
        commit = "b" * 40
        lock = self.lock("package-lock.json", json.dumps({
            "name": "synthetic", "lockfileVersion": 3,
            "packages": {"node_modules/one": {
                "resolved": f"git+ssh://git@github.com/public/one.git#{commit}"},
                         "node_modules/two": {
                "resolved": f"ssh://git@github.com/public/two.git#{commit}"}}}))
        original = lock.read_bytes()
        env, recorded = collector.github_ssh_git_config(lock)
        self.assertEqual(env["GIT_CONFIG_COUNT"], "2")
        self.assertEqual([row["value"] for row in recorded], list(collector.GITHUB_SSH_PREFIXES))
        self.assertTrue(all(row["key"] == 'url."https://github.com/".insteadOf' for row in recorded))
        repository = self.root / "offline-git"
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        for index, prefix in enumerate(collector.GITHUB_SSH_PREFIXES):
            name = f"synthetic-{index}"
            subprocess.run(["git", "-C", str(repository), "remote", "add", name,
                            prefix + "public/example.git"], check=True)
            result = subprocess.run(["git", "-C", str(repository), "remote", "get-url", name],
                                    check=True, capture_output=True, text=True,
                                    env={**os.environ, **env})
            self.assertEqual(result.stdout.strip(), "https://github.com/public/example.git")
        self.assertEqual(lock.read_bytes(), original)
        self.assertIn(commit.encode(), original)
        lock.write_text('"ssh://git@other.example/public/dep.git"')
        self.assertEqual(collector.github_ssh_git_config(lock), ({}, []))

    def test_pinned_version_field_and_single_named_build(self) -> None:
        self.lock("yarn.lock")
        (self.package / "package.json").write_text(json.dumps({
            "packageManager": "yarn@1.22.19", "scripts": {
                "test": "yarn build && mocha test.js", "build": "true", "prebuild": "true"}}))
        command, _, version = collector.choose_install(self.package, self.package, TOOLS)
        self.assertEqual(command[:2], ["corepack", "yarn@1.22.19"])
        self.assertEqual(version, "yarn@1.22.19")
        self.assertEqual(collector.package_build_script(self.package), "build")

    def test_nested_named_build_and_lifecycle_scripts_are_traced_in_order(self) -> None:
        (self.package / "package.json").write_text(json.dumps({"scripts": {
            "test": "yarn run build && mocha test.js", "build": "yarn build:types && yarn build:ts",
            "prebuild": "true", "build:types": "true", "build:ts": "true",
            "postbuild": "true"}}))
        selected = collector.package_build_script(self.package)
        self.assertEqual(selected, "build")
        chain = collector.script_chain(self.package, self.package, selected)
        self.assertEqual([entry["script"] for entry in chain],
                         ["prebuild", "build", "build:types", "build:ts", "postbuild"])
        self.assertEqual([entry["order"] for entry in chain], list(range(1, 6)))
        self.assertTrue(all(entry["package_json"] == "/work/package.json" for entry in chain))
        successful = {"exit_code": 0}
        collector.record_script_execution(successful, chain, direct=True)
        self.assertEqual(successful["script_chain_executed"], chain)
        failed = {"exit_code": 1}
        collector.record_script_execution(failed, chain, direct=True)
        self.assertEqual(failed["script_chain_executed"], [])
        self.assertIn("unconfirmed", failed["script_chain_execution_evidence"])

    def test_workspace_child_script_is_traced_with_its_package_path(self) -> None:
        child = self.package / "packages/circuits"
        child.mkdir(parents=True)
        (self.package / "package.json").write_text(json.dumps({
            "workspaces": ["packages/*"], "scripts": {
                "build": "yarn workspace @synthetic/circuits run compile"}}))
        (child / "package.json").write_text(json.dumps({
            "name": "@synthetic/circuits", "scripts": {
                "precompile": "true", "compile": "npm run generate && true",
                "generate": "true", "postcompile": "true"}}))
        chain = collector.script_chain(self.package, self.package, "build")
        self.assertEqual([(entry["package_json"], entry["script"]) for entry in chain], [
            ("/work/package.json", "build"),
            ("/work/packages/circuits/package.json", "precompile"),
            ("/work/packages/circuits/package.json", "compile"),
            ("/work/packages/circuits/package.json", "generate"),
            ("/work/packages/circuits/package.json", "postcompile")])

    def test_top_level_workspace_build_is_selected_in_child_package(self) -> None:
        child = self.package / "packages/circuits"
        child.mkdir(parents=True)
        (self.package / "package.json").write_text(json.dumps({
            "workspaces": ["packages/*"], "scripts": {}}))
        (child / "package.json").write_text(json.dumps({
            "name": "@synthetic/circuits", "scripts": {"build": "true"}}))
        test_file = self.package / "test.js"
        for command in ("yarn workspace @synthetic/circuits build",
                        "npm -w @synthetic/circuits run build",
                        "pnpm -C packages/circuits run build"):
            with self.subTest(command=command):
                test_file.write_text(f'require("child_process").execSync("{command}");\n')
                selected, dynamic = collector.named_build_target(self.package, self.package, test_file)
                self.assertEqual(selected, (child.resolve(), "build", True))
                self.assertEqual(dynamic, [])

    def test_named_compile_script_is_valid_and_multiple_targets_are_rejected(self) -> None:
        (self.package / "package.json").write_text(json.dumps({"scripts": {
            "compile:types": "true", "build": "true"}}))
        test_file = self.package / "test.js"
        test_file.write_text('require("child_process").execSync("npm run compile:types");\n')
        selected, dynamic = collector.named_build_target(self.package, self.package, test_file)
        self.assertEqual(selected, (self.package.resolve(), "compile:types", True))
        self.assertEqual(dynamic, [])
        test_file.write_text('require("child_process").execSync("npm run compile:types");\n'
                             'require("child_process").execSync("npm run build");\n')
        with self.assertRaisesRegex(collector.PolicyFailure, "multiple package scripts"):
            collector.named_build_target(self.package, self.package, test_file)

    def test_nonexecuted_build_literal_is_not_selected(self) -> None:
        (self.package / "package.json").write_text(json.dumps({"scripts": {"build": "true"}}))
        test_file = self.package / "test.js"
        test_file.write_text('// execSync("npm run build");\n'
                             'const note = "npm run build";\n')
        selected, dynamic = collector.named_build_target(self.package, self.package, test_file)
        self.assertIsNone(selected)
        self.assertEqual(dynamic, [])

    def test_dynamic_test_and_tool_calls_are_recorded_without_extra_build(self) -> None:
        (self.package / "package.json").write_text(json.dumps({"scripts": {
            "test": "npm run ${STEP}", "build": "true"}}))
        test_file = self.package / "test.js"
        test_file.write_text("require('child_process').execSync('npm run ' + step);\n")
        selected, dynamic = collector.named_build_target(self.package, self.package, test_file)
        self.assertIsNone(selected)
        self.assertEqual([entry["source"] for entry in dynamic],
                         ["package_test_script", "test_source"])
        self.assertTrue(all(entry["dynamic"] for entry in dynamic))
        self.assertEqual([entry["reason"] for entry in dynamic],
                         ["script_name_dynamic", "script_name_missing"])

    def test_static_script_cycle_is_recorded_and_rejected(self) -> None:
        (self.package / "package.json").write_text(json.dumps({"scripts": {
            "build": "pnpm run build:types", "build:types": "npm run build"}}))
        with self.assertRaisesRegex(collector.ScriptChainCycle, "package_script_cycle") as caught:
            collector.script_chain(self.package, self.package, "build")
        self.assertEqual([entry["script"] for entry in caught.exception.chain],
                         ["build", "build:types", "build"])
        self.assertEqual(caught.exception.chain[-1]["reason"], "cycle")

    def test_static_cycle_becomes_a_d_failure_before_install(self) -> None:
        source = self.root / "cycle-project"
        (source / "test").mkdir(parents=True)
        (source / "package.json").write_text(json.dumps({"scripts": {
            "build": "npm run build:types", "build:types": "npm run build"}}))
        entrypoint = source / "main.circom"
        entrypoint.write_text("component main = Example();\n")
        (source / "test/main.test.js").write_text(
            'const circuit = "main.circom"; circuit.calculateWitness(input);\n'
            'require("child_process").execSync("npm run build");\n')
        output = self.root / "cycle-output"
        output.mkdir()

        def fake_copy(command, **_kwargs):
            self.assertIn("node_modules/", command)
            self.assertIn(".yarn/cache/", command)
            shutil.copytree(source, Path(command[-1]), dirs_exist_ok=True)
            return type("Result", (), {"returncode": 0})()

        class FakeDockerRunner:
            def __init__(self, _project, _output, _tools, _deadline):
                self.steps = []

            def check(self):
                return None

            def run(self, label, *_args, **_kwargs):
                if label != "tool-versions":
                    raise AssertionError("cyclic script must not run")
                versions = output / "versions.stdout.log"
                versions.write_text("v22.23.3\n10.9.9\n0.36.0\n")
                return {"exit_code": 0, "stdout_log": str(versions)}

        with patch.object(collector.subprocess, "run", side_effect=fake_copy), \
                patch.object(collector, "DockerRunner", FakeDockerRunner), \
                patch.object(collector, "verify_no_tracked_install_artifacts"), \
                patch.object(collector.base, "test_command",
                             side_effect=lambda project, *_args: (None, project)):
            picked, failures, execution = collector.docker_project_selection(
                {"project_root": str(source), "entrypoint_absolute": str(entrypoint)},
                output, lambda *_args: None, TOOLS, collector.time.monotonic() + 60)
        self.assertIsNone(picked)
        self.assertEqual([step["kind"] for step in execution], ["script-chain-plan"])
        self.assertEqual(failures[0]["reason"], "package_script_cycle")
        self.assertEqual([row["script"] for row in failures[0]["script_chain_static"]],
                         ["build", "build:types", "build"])
        plan = Path(failures[0]["script_chain_plan_path"])
        self.assertEqual(failures[0]["script_chain_plan_sha256"], collector.base.sha256(plan))
        self.assertEqual(execution[0]["script_chain_plan_path"], str(plan))
        self.assertEqual(json.loads(plan.read_text())["static_status"], "cycle")

    def test_unresolved_script_call_is_dynamic_and_not_preemptively_rejected(self) -> None:
        (self.package / "package.json").write_text(json.dumps({"scripts": {
            "build": "npm run $BUILD_STEP"}}))
        chain = collector.script_chain(self.package, self.package, "build")
        self.assertEqual(chain[0]["script"], "build")
        self.assertTrue(chain[1]["dynamic"])
        self.assertEqual(chain[1]["reason"], "script_name_dynamic")
        completed = {"exit_code": 0}
        collector.record_script_execution(completed, chain, direct=True)
        self.assertEqual([row["script"] for row in completed["script_chain_executed"]],
                         ["build"])
        self.assertEqual(completed["script_chain_execution_evidence"],
                         "successful_script_with_dynamic_subcalls")
        plan_ref = collector.write_script_chain_plan(
            self.root, 1, self.package / "test.js", self.package,
            (self.package, "build", False), chain, [], [])
        plan = json.loads(Path(plan_ref["script_chain_plan_path"]).read_text())
        self.assertEqual(plan["dynamic_markers"][0]["reason"], "script_name_dynamic")
        self.assertEqual(plan["dynamic_execution_status"], "unconfirmed")

    def test_conditional_self_call_is_dynamic_not_a_static_cycle(self) -> None:
        (self.package / "package.json").write_text(json.dumps({"scripts": {
            "build": "if false; then npm run build; fi", "postbuild": "true"}}))
        chain = collector.script_chain(self.package, self.package, "build")
        self.assertEqual([entry["script"] for entry in chain], ["build", None, "postbuild"])
        self.assertEqual(chain[1]["reason"], "conditional_shell_control")
        self.assertTrue(chain[1]["dynamic"])
        self.assertEqual(chain[2]["reason"], "conditional_parent_outcome")

    def test_masked_and_early_exit_calls_are_not_static_executions(self) -> None:
        for command in ("false && npm run child; true", "exit 0; npm run child"):
            with self.subTest(command=command):
                (self.package / "package.json").write_text(json.dumps({"scripts": {
                    "build": command, "child": "npm run build"}}))
                chain = collector.script_chain(self.package, self.package, "build")
                self.assertEqual([entry["script"] for entry in chain], ["build", None])
                self.assertEqual(chain[1]["reason"], "conditional_shell_control")
                completed = {"exit_code": 0}
                collector.record_script_execution(completed, chain, direct=True)
                self.assertEqual(completed["script_chain_executed"], [])

    def test_failed_build_uses_only_announced_scripts_as_executed(self) -> None:
        (self.package / "package.json").write_text(json.dumps({"scripts": {
            "build": "yarn build:types && yarn build:ts",
            "build:types": "./scripts/genTypes.sh", "build:ts": "tsc -p tsconfig.json"}}))
        chain = collector.script_chain(self.package, self.package, "build")
        log = self.root / "build.stdout.log"
        log.write_text("yarn run v1.22.22\n$ yarn build:types && yarn build:ts\n"
                       "yarn run v1.22.22\n$ ./scripts/genTypes.sh\nerror\n")
        failed = {"exit_code": 1, "stdout_log": str(log)}
        collector.record_script_execution(failed, chain, direct=True, project=self.package)
        self.assertEqual([row["script"] for row in failed["script_chain_executed"]],
                         ["build", "build:types"])
        self.assertEqual(failed["script_chain_execution_evidence"],
                         "package_manager_log_announcements")

    def test_docker_invocation_mounts_only_project_and_disables_test_network(self) -> None:
        runner = collector.DockerRunner(self.package, self.root / "output", TOOLS, collector.time.monotonic() + 60)
        runner.script_chain_plan_ref = {"script_chain_plan_path": "synthetic-plan.json",
                                        "script_chain_plan_sha256": "a" * 64}

        def fake_run(command, **kwargs):
            self.assertEqual(command[:2], ["docker", "run"])
            self.assertEqual(command.count("--mount"), 1)
            self.assertIn(f"type=bind,src={self.package},dst=/work", command)
            self.assertEqual(command[command.index("--network") + 1], "none")
            self.assertNotIn("--env-file", command)
            return type("Result", (), {"returncode": 0})()

        with patch.object(collector.subprocess, "run", side_effect=fake_run):
            result = runner.run("test", ["node", "test.js"], self.package, network=False, capture=True)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["network"], False)
        self.assertEqual(result["script_chain_plan_path"], "synthetic-plan.json")

    def test_environment_failures_use_complete_stdout_and_stderr(self) -> None:
        runner = collector.DockerRunner(self.package, self.root / "output", TOOLS, collector.time.monotonic() + 60)
        cases = [
            (b"", b"x" * 70000 + b"npm ERR! EAI_AGAIN registry.npmjs.org", True, "eai_again"),
            (b"x" * 70000 + b"Proxy Authentication Required", b"", True, "proxy authentication"),
            (b"x" * 65535 + b"ENOTFOUND", b"", True, "enotfound"),
            (b"x" * 70000 + b"npm ERR! code EACCES", b"", True, "eacces"),
            (b"permission denied while trying to connect to the Docker API", b"", False,
             "permission denied while trying to connect to the docker api"),
        ]
        for ordinal, (out_bytes, err_bytes, network, marker) in enumerate(cases, 1):
            with self.subTest(ordinal=ordinal):
                def fake_run(_command, **kwargs):
                    kwargs["stdout"].write(out_bytes)
                    kwargs["stderr"].write(err_bytes)
                    return type("Result", (), {"returncode": 1})()

                with patch.object(collector.subprocess, "run", side_effect=fake_run):
                    with self.assertRaises(collector.EnvironmentBlocked):
                        runner.run(f"install-{ordinal}", ["npm", "ci", "--ignore-scripts"],
                                   self.package, network=network)
                self.assertEqual(runner.steps[-1]["environment_error"], marker)
                self.assertEqual(Path(runner.steps[-1]["stdout_log"]).read_bytes(), out_bytes)
                self.assertEqual(Path(runner.steps[-1]["stderr_log"]).read_bytes(), err_bytes)

    def test_non_environment_failures_remain_revision_failures(self) -> None:
        runner = collector.DockerRunner(self.package, self.root / "output", TOOLS, collector.time.monotonic() + 60)

        def fake_run(_command, **kwargs):
            kwargs["stdout"].write(b"ENOTFOUND in a network-disabled project test")
            kwargs["stderr"].write(b"lock file does not satisfy package.json")
            return type("Result", (), {"returncode": 1})()

        with patch.object(collector.subprocess, "run", side_effect=fake_run):
            result = runner.run("test-before-install", ["node", "test.js"], self.package, network=False)
        self.assertEqual(result["exit_code"], 1)
        self.assertNotIn("environment_error", result)

    def test_missing_container_executable_blocks_revision_but_missing_project_bin_does_not(self) -> None:
        runner = collector.DockerRunner(self.package, self.root / "tool-output", TOOLS,
                                        collector.time.monotonic() + 60)
        cases = [
            (b"npm ERR! code ENOENT\nnpm ERR! syscall spawn git\nnpm ERR! path git\n", "git"),
            (b"Yarn: Couldn't find the binary git\n", "git"),
            (b"sh: 1: circom: not found\n", "circom"),
            (b"/bin/sh: 1: python3: not found\n", "python3"),
        ]
        for index, (error_text, expected) in enumerate(cases, 1):
            with self.subTest(tool=expected):
                def fake_run(_command, **kwargs):
                    kwargs["stderr"].write(error_text)
                    return type("Result", (), {"returncode": 1})()

                with patch.object(collector.subprocess, "run", side_effect=fake_run):
                    with self.assertRaisesRegex(collector.ToolBlocked, expected):
                        runner.run(f"install-{index}", ["npm", "ci", "--ignore-scripts"],
                                   self.package, network=True)
                self.assertEqual(runner.steps[-1]["tool_error"],
                                 f"missing_container_executable:{expected}")
        def missing_project_bin(_command, **kwargs):
            kwargs["stderr"].write(b"sh: 1: tsc: not found\n")
            return type("Result", (), {"returncode": 1})()

        with patch.object(collector.subprocess, "run", side_effect=missing_project_bin):
            result = runner.run("build-project-bin", ["npm", "run", "build"],
                                self.package, network=False)
        self.assertEqual(result["exit_code"], 1)
        self.assertNotIn("tool_error", result)

    def test_same_lock_and_folder_are_installed_once_with_recorded_reuse(self) -> None:
        source = self.root / "repeat-lock-project"
        test_dir = source / "test"
        test_dir.mkdir(parents=True)
        (source / "package.json").write_text('{"scripts":{}}')
        (source / "package-lock.json").write_text("lock")
        entrypoint = source / "main.circom"
        entrypoint.write_text("component main = Example();\n")
        for index in (1, 2):
            (test_dir / f"main-{index}.test.js").write_text(
                'const circuit = "main.circom"; circuit.calculateWitness(input);\n')

        def fake_copy(command, **_kwargs):
            shutil.copytree(source, Path(command[-1]), dirs_exist_ok=True)
            return type("Result", (), {"returncode": 0})()

        for first_exit in (0, 1):
            with self.subTest(first_exit=first_exit):
                output = self.root / f"repeat-output-{first_exit}"
                output.mkdir()
                actual_installs = []

                class FakeDockerRunner:
                    def __init__(self, project, _output, _tools, _deadline):
                        self.project = project
                        self.steps = []

                    def check(self):
                        return None

                    def run(self, label, *_args, **_kwargs):
                        if label == "tool-versions":
                            versions = output / "versions.stdout.log"
                            versions.write_text("v22.23.3\n10.9.9\n0.36.0\n")
                            result = {"kind": label, "exit_code": 0, "stdout_log": str(versions)}
                        elif label.startswith("install-"):
                            actual_installs.append(label)
                            if first_exit == 0:
                                modules = self.project / "node_modules"
                                modules.mkdir()
                                (modules / "installed.txt").write_text("from lock")
                            result = {"kind": label, "exit_code": first_exit}
                        else:
                            raise AssertionError("unexpected project execution")
                        self.steps.append(result)
                        return result

                with patch.object(collector.subprocess, "run", side_effect=fake_copy), \
                        patch.object(collector, "DockerRunner", FakeDockerRunner), \
                        patch.object(collector, "verify_no_tracked_install_artifacts"), \
                        patch.object(collector, "requires_circom", return_value=False), \
                        patch.object(collector, "verify_committed_lock", return_value="a" * 64), \
                        patch.object(collector.base, "test_command",
                                     side_effect=lambda project, *_args: (None, project)):
                    picked, failures, execution = collector.docker_project_selection(
                        {"project_root": str(source), "entrypoint_absolute": str(entrypoint)},
                        output, lambda *_args: None, TOOLS, collector.time.monotonic() + 60)
                self.assertIsNone(picked)
                self.assertEqual(actual_installs, ["install-1"])
                installs = [step for step in execution if step["kind"].startswith("install-")]
                self.assertEqual([step["actual_execution"] for step in installs], [True, False])
                self.assertEqual([step["lock_path"] for step in installs],
                                 ["package-lock.json", "package-lock.json"])
                self.assertEqual([step["install_folder"] for step in installs], [".", "."])
                self.assertEqual(installs[1]["reused_from"], "install-1")
                if first_exit == 0:
                    self.assertEqual(installs[1]["initial_installed_packages"],
                                     installs[0]["installed_packages"])
                    self.assertEqual(installs[1]["installed_packages"],
                                     installs[0]["installed_packages"])
                self.assertEqual([failure["reason"] for failure in failures],
                                 (["test_runner_unavailable_after_install"] * 2 if first_exit == 0 else
                                  ["lock_install_failed", "lock_install_failed_no_retry"]))

    def test_panther_same_main_gate_runs_before_test_or_install(self) -> None:
        source = self.root / "panther"
        (source / "circuits/test").mkdir(parents=True)
        (source / "circuits/package.json").write_text('{"name":"@panther-core/circuits"}')
        entrypoint = source / "circuits/target.circom"
        entrypoint.write_text("component main = Target(1);\n")
        (source / "circuits/unrelated.circom").write_text("component main = Other(2);\n")
        test_file = source / "circuits/test/target.test.ts"
        test_file.write_text('const file = "unrelated.circom"; // target.circom\n'
                             'circuit.calculateWitness(input);\n')
        row = {"project_root": str(source), "entrypoint_absolute": str(entrypoint)}
        output = self.root / "panther-output"
        output.mkdir()

        def fake_copy(command, **_kwargs):
            shutil.copytree(source, Path(command[-1]), dirs_exist_ok=True)
            return type("Result", (), {"returncode": 0})()

        class FakeDockerRunner:
            def __init__(self, _project, _output, _tools, _deadline):
                self.steps = []

            def check(self):
                return None

            def run(self, label, *_args, **_kwargs):
                if label != "tool-versions":
                    raise AssertionError("test or install ran despite same-main gate")
                versions = output / "versions.stdout.log"
                versions.write_text("v22.23.3\n10.9.9\n0.36.0\n")
                return {"exit_code": 0, "stdout_log": str(versions)}

        with patch.object(collector.subprocess, "run", side_effect=fake_copy), \
                patch.object(collector, "DockerRunner", FakeDockerRunner), \
                patch.object(collector, "verify_no_tracked_install_artifacts"), \
                patch.object(collector.base, "test_command", side_effect=AssertionError("test command selected")):
            picked, failures, execution = collector.docker_project_selection(
                row, output, lambda *_args: None, TOOLS, collector.time.monotonic() + 60)
        self.assertIsNone(picked)
        self.assertEqual(failures[0]["reason"], "project_test_same_main_unverified")
        self.assertEqual(execution, [])

    def test_build_embedded_in_test_is_not_invoked_separately(self) -> None:
        source = self.root / "embedded-build"
        (source / "test").mkdir(parents=True)
        (source / "package.json").write_text(json.dumps({"scripts": {"build": "true"}}))
        (source / "package-lock.json").write_text("lock")
        entrypoint = source / "main.circom"
        entrypoint.write_text("component main = Example();\n")
        test_file = source / "test/main.test.js"
        test_file.write_text('const circuit = "main.circom"; circuit.calculateWitness(input);\n'
                             'require("child_process").execSync("npm run build");\n')
        row = {"project_root": str(source), "entrypoint_absolute": str(entrypoint)}
        output = self.root / "embedded-output"
        output.mkdir()

        def fake_copy(command, **_kwargs):
            shutil.copytree(source, Path(command[-1]), dirs_exist_ok=True)
            return type("Result", (), {"returncode": 0})()

        class FakeDockerRunner:
            def __init__(self, project, _output, _tools, _deadline):
                self.project = project
                self.steps = []

            def check(self):
                return None

            def run(self, label, *_args, **_kwargs):
                if label == "tool-versions":
                    versions = output / "versions.stdout.log"
                    versions.write_text("v22.23.3\n10.9.9\n0.36.0\n")
                    row_result = {"kind": label, "exit_code": 0, "stdout_log": str(versions)}
                elif label.startswith("install-"):
                    local_bin = self.project / "node_modules/.bin"
                    local_bin.mkdir(parents=True)
                    (local_bin / "mocha").write_text("mock")
                    row_result = {"kind": label, "exit_code": 0}
                elif label.startswith("test-"):
                    row_result = {"kind": label, "exit_code": 1}
                else:
                    raise AssertionError("named build was separately invoked")
                self.steps.append(row_result)
                return row_result

        with patch.object(collector.subprocess, "run", side_effect=fake_copy), \
                patch.object(collector, "DockerRunner", FakeDockerRunner), \
                patch.object(collector, "verify_no_tracked_install_artifacts"), \
                patch.object(collector, "requires_circom", return_value=False), \
                patch.object(collector, "verify_committed_lock", return_value="a" * 64):
            picked, failures, execution = collector.docker_project_selection(
                row, output, lambda *_args: None, TOOLS, collector.time.monotonic() + 60)
        self.assertIsNone(picked)
        self.assertEqual(failures[0]["reason"], "same_test_failed_after_install")
        self.assertEqual([step["kind"] for step in execution],
                         ["tool-versions", "script-chain-plan", "install-1", "test-1-after-install"])
        self.assertEqual(execution[-1]["build_named_by_test_source"], "build")
        self.assertEqual(json.loads(Path(failures[0]["script_chain_plan_path"]).read_text())
                         ["build_chain_static"][0]["script"], "build")

    def test_script_chain_plan_survives_install_failure_and_environment_block(self) -> None:
        source = self.root / "plan-project"
        (source / "test").mkdir(parents=True)
        (source / "package.json").write_text(json.dumps({"scripts": {
            "build": "npm run generate", "generate": "true"}}))
        (source / "package-lock.json").write_text("lock")
        entrypoint = source / "main.circom"
        entrypoint.write_text("component main = Example();\n")
        (source / "test/main.test.js").write_text(
            'const circuit = "main.circom"; circuit.calculateWitness(input);\n'
            'require("child_process").execSync("npm run build");\n')

        def fake_copy(command, **_kwargs):
            shutil.copytree(source, Path(command[-1]), dirs_exist_ok=True)
            return type("Result", (), {"returncode": 0})()

        for blocked in (False, True):
            with self.subTest(environment_blocked=blocked):
                output = self.root / f"plan-output-{blocked}"
                output.mkdir()

                class FakeDockerRunner:
                    def __init__(self, _project, _output, _tools, _deadline):
                        self.steps = []

                    def check(self):
                        return None

                    def run(self, label, *_args, **_kwargs):
                        if label == "tool-versions":
                            versions = output / "versions.stdout.log"
                            versions.write_text("v22.23.3\n10.9.9\n0.36.0\n")
                            result = {"kind": label, "exit_code": 0, "stdout_log": str(versions)}
                        elif label == "install-1":
                            result = {"kind": label, "exit_code": 1}
                        else:
                            raise AssertionError("test or build ran before failed installation")
                        self.steps.append(result)
                        if blocked and label == "install-1":
                            raise collector.EnvironmentBlocked("synthetic network block")
                        return result

                with patch.object(collector.subprocess, "run", side_effect=fake_copy), \
                        patch.object(collector, "DockerRunner", FakeDockerRunner), \
                        patch.object(collector, "verify_no_tracked_install_artifacts"), \
                        patch.object(collector, "requires_circom", return_value=False), \
                        patch.object(collector, "verify_committed_lock", return_value="a" * 64), \
                        patch.object(collector.base, "test_command",
                                     side_effect=lambda project, *_args: (None, project)):
                    if blocked:
                        with self.assertRaises(collector.EnvironmentBlocked) as caught:
                            collector.docker_project_selection(
                                {"project_root": str(source), "entrypoint_absolute": str(entrypoint)},
                                output, lambda *_args: None, TOOLS, collector.time.monotonic() + 60)
                        plan_ref = caught.exception.script_chain_plan_ref
                        execution = caught.exception.project_test_execution
                    else:
                        picked, failures, execution = collector.docker_project_selection(
                            {"project_root": str(source), "entrypoint_absolute": str(entrypoint)},
                            output, lambda *_args: None, TOOLS, collector.time.monotonic() + 60)
                        self.assertIsNone(picked)
                        self.assertEqual(failures[0]["reason"], "lock_install_failed")
                        plan_ref = failures[0]
                plan = Path(plan_ref["script_chain_plan_path"])
                self.assertTrue(plan.is_file())
                self.assertEqual(plan_ref["script_chain_plan_sha256"], collector.base.sha256(plan))
                self.assertEqual([item["script"] for item in json.loads(plan.read_text())
                                  ["build_chain_static"]], ["build", "generate"])
                self.assertEqual([step["kind"] for step in execution],
                                 ["tool-versions", "script-chain-plan", "install-1"])
                self.assertEqual(execution[1]["script_chain_plan_sha256"],
                                 plan_ref["script_chain_plan_sha256"])

    def test_preexisting_dependencies_are_excluded_before_first_test(self) -> None:
        source = self.root / "stale-project"
        (source / "test").mkdir(parents=True)
        (source / "package.json").write_text('{"scripts":{}}')
        (source / "package-lock.json").write_text("lock")
        stale_bin = source / "node_modules/.bin"
        stale_bin.mkdir(parents=True)
        (stale_bin / "mocha").write_text("old unverified runner")
        (source / ".pnp.cjs").write_text("old PnP")
        cache = source / ".yarn/cache"
        cache.mkdir(parents=True)
        (cache / "old.zip").write_text("old cache")
        entrypoint = source / "main.circom"
        entrypoint.write_text("component main = Example();\n")
        (source / "test/main.test.js").write_text(
            'const circuit = "main.circom"; circuit.calculateWitness(input);\n')
        output = self.root / "stale-output"
        output.mkdir()

        def fake_copy(command, **_kwargs):
            self.assertIn("node_modules/", command)
            self.assertIn(".yarn/cache/", command)
            shutil.copytree(source, Path(command[-1]), dirs_exist_ok=True)
            return type("Result", (), {"returncode": 0})()

        class FakeDockerRunner:
            def __init__(self, project, _output, _tools, _deadline):
                self.project = project
                self.steps = []

            def check(self):
                return None

            def run(self, label, *_args, **_kwargs):
                if label == "tool-versions":
                    versions = output / "versions.stdout.log"
                    versions.write_text("v22.23.3\n10.9.9\n0.36.0\n")
                    result = {"kind": label, "exit_code": 0, "stdout_log": str(versions)}
                elif label.startswith("install-"):
                    self_outer.assertFalse((self.project / "node_modules").exists())
                    self_outer.assertFalse((self.project / ".pnp.cjs").exists())
                    self_outer.assertFalse((self.project / ".yarn/cache").exists())
                    fresh = self.project / "node_modules/.bin"
                    fresh.mkdir(parents=True)
                    (fresh / "mocha").write_text("new lock install runner")
                    result = {"kind": label, "exit_code": 0}
                elif label.startswith("test-") and label.endswith("after-install"):
                    result = {"kind": label, "exit_code": 1}
                else:
                    raise AssertionError("stale dependency ran before verified install")
                self.steps.append(result)
                return result

        self_outer = self
        with patch.object(collector.subprocess, "run", side_effect=fake_copy), \
                patch.object(collector, "DockerRunner", FakeDockerRunner), \
                patch.object(collector, "verify_no_tracked_install_artifacts"), \
                patch.object(collector, "requires_circom", return_value=False), \
                patch.object(collector, "verify_committed_lock", return_value="a" * 64):
            picked, failures, execution = collector.docker_project_selection(
                {"project_root": str(source), "entrypoint_absolute": str(entrypoint)},
                output, lambda *_args: None, TOOLS, collector.time.monotonic() + 60)
        self.assertIsNone(picked)
        self.assertEqual(failures[0]["reason"], "same_test_failed_after_install")
        self.assertEqual([step["kind"] for step in execution],
                         ["tool-versions", "script-chain-plan", "install-1", "test-1-after-install"])
        self.assertTrue((stale_bin / "mocha").is_file())
        self.assertTrue((source / ".pnp.cjs").is_file())
        self.assertTrue((cache / "old.zip").is_file())

    def test_tracked_zero_install_file_stops_d_before_project_copy(self) -> None:
        source = self.root / "tracked-project"
        (source / "test").mkdir(parents=True)
        entrypoint = source / "main.circom"
        entrypoint.write_text("component main = Example();\n")
        test_file = source / "test/main.test.js"
        test_file.write_text('const circuit = "main.circom"; circuit.calculateWitness(input);\n')
        output = self.root / "tracked-output"
        output.mkdir()
        row = {"project_root": str(source), "entrypoint_absolute": str(entrypoint),
               "git_repository_path": str(source), "revision_commit": "a" * 40}

        def fake_git(command, **_kwargs):
            self.assertEqual(command[:4], ["git", "-C", str(source.resolve()), "ls-tree"])
            return type("Result", (), {
                "returncode": 0, "stdout": b"package.json\0.yarn/cache/tracked.zip\0"})()

        with patch.object(collector.subprocess, "run", side_effect=fake_git):
            picked, failures, execution = collector.docker_project_selection(
                row, output, lambda *_args: None, TOOLS, collector.time.monotonic() + 60)
        self.assertIsNone(picked)
        self.assertEqual(execution, [])
        self.assertEqual(failures[0]["reason"], "tracked_install_artifact_requires_separate_rule")
        self.assertFalse((output / "project-test-docker-copy").exists())

    def test_b_reference_uses_preflight_artifact_evidence_for_all_revisions(self) -> None:
        evidence = reference.build_map(reference.QUEUE, reference.PROOF, reference.ROOT)
        self.assertEqual(len(evidence["revisions"]), 10)
        self.assertTrue(all(row["status"] == "verified" for row in evidence["revisions"].values()))
        self.assertTrue(all(len(set(row["unit_hashes"].values())) == 1
                            for row in evidence["revisions"].values()))


if __name__ == "__main__":
    unittest.main()
