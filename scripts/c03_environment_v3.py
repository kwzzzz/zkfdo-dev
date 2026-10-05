#!/usr/bin/env python3
"""C-03 v3: fix only pinned pnpm CLI configuration option spelling.

V1/v2 remain immutable. V2's setup coverage, caps, script disabling, and package
selection are unchanged. Captured argv carries the corrected config.* options;
the setup report retains v2's schema. No global function is replaced.
"""

import argparse
import json
from pathlib import Path

import c03_environment_v2 as v2


LOCKS = v2.LOCKS
include_paths = v2.include_paths
plan_installations = v2.plan_installations
run_command = v2.run_command
_PNPM_OPTIONS = {
    "--manage-package-manager-versions=false": "--config.manage-package-manager-versions=false",
    "--package-manager-strict=false": "--config.package-manager-strict=false",
}


def _correct_pnpm_argv(argv, tool):
    prefix = tool.get("argv", [])
    if not prefix or list(argv[:len(prefix)]) != prefix or list(argv[len(prefix):len(prefix) + 1]) != ["install"]:
        return list(argv)
    return list(argv[:len(prefix)]) + [_PNPM_OPTIONS.get(part, part) for part in argv[len(prefix):]]


def install_command(plan, tool):
    """Use pnpm's accepted configuration namespace, retaining all safeguards."""
    argv = v2.install_command(plan, tool)
    return _correct_pnpm_argv(argv, tool) if plan["manager"] == "pnpm" else argv


def run_setup(repo_root, circuit_paths, raw_dir, tools, caps=None, runner=None):
    """V2-compatible setup with corrected argv only at the actual runner edge."""
    execute = runner or run_command

    def corrected_runner(argv, directory, cap, cwd, isolated):
        return execute(_correct_pnpm_argv(argv, tools.get("pnpm", {})), directory, cap, cwd, isolated)

    return v2.run_setup(repo_root, circuit_paths, raw_dir, tools, caps, corrected_runner)


def run_offline_controls(raw_dir, tools_path, runner=None):
    """Run empty synthetic pnpm/Yarn packages only; never a corpus install.

    Existing output is refused. Offline commands, source/tool hashes, captures,
    and marker absence are preserved; a rejected command cannot pass a control.
    """
    raw, tools_path = Path(raw_dir).resolve(), Path(tools_path).resolve()
    raw.mkdir(parents=True, exist_ok=False)
    tools = json.loads(tools_path.read_text())
    execute = runner or run_command
    controls = []
    for manager in ("pnpm", "yarn"):
        tool = tools[manager]
        package = raw / (manager + "-package")
        package.mkdir()
        manifest = {"name": "c03-offline-script-control-v3", "version": "1.0.0", "private": True,
                    "scripts": {hook: 'node -e "require(\'fs\').writeFileSync(\'lifecycle-ran\', \'unexpected\')"'
                                for hook in ("preinstall", "install", "postinstall", "prepare")}}
        if manager == "pnpm":
            # A different declared version must not replace the pinned manager.
            manifest["packageManager"] = "pnpm@10.0.0"
        v2.v1.write_new(package / "package.json", manifest)
        (package / ".npmrc").write_text("ignore-scripts=false\nmanage-package-manager-versions=true\npackage-manager-strict=true\n")
        if manager == "pnpm":
            (package / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\nsettings:\n  autoInstallPeers: true\n  excludeLinksFromLockfile: false\nimporters:\n  .: {}\n")
            (package / ".pnpmfile.cjs").write_text("require('fs').writeFileSync('configuration-hook-ran', 'unexpected'); module.exports = {};\n")
        else:
            (package / "yarn.lock").write_text("# yarn lockfile v1\n")
            (package / ".yarnrc").write_text('yarn-path "./project-manager.js"\nignore-scripts false\n')
            (package / "project-manager.js").write_text("require('fs').writeFileSync('configuration-hook-ran', 'unexpected'); process.exit(79);\n")
        plans = plan_installations(package, [package])
        if len(plans) != 1 or plans[0].get("status") != "ready" or plans[0].get("manager") != manager:
            raise ValueError("synthetic_control_plan_unexpected")
        command = install_command(plans[0], tool) + ["--offline"]
        isolated = v2.v1.isolated_environment(raw / (manager + "-environment"), [Path(arg).parent for arg in tool["argv"]])
        capture = execute(command, raw / (manager + "-invocation"), 30, package, isolated)
        markers = {name: (package / name).exists() for name in ("lifecycle-ran", "configuration-hook-ran")}
        passed = capture.get("status") == "success" and capture.get("exit_code") == 0 and not any(markers.values())
        controls.append({"manager": manager, "version": tool["version"], "tool_files": tool["files"],
                         "command": command, "capture": capture, "marker_presence": markers,
                         "package": v2.v1.ref(package / "package.json"), "passed": passed,
                         "configuration": [v2.v1.ref(path) for path in sorted(package.iterdir())
                                           if path.is_file() and path.name in {".npmrc", ".yarnrc", ".pnpmfile.cjs", "project-manager.js", "pnpm-lock.yaml", "yarn.lock"}]})
    result = {"schema_version": 3, "purpose": "pinned manager CLI acceptance and script suppression on offline empty packages",
              "tools": v2.v1.ref(tools_path), "implementation": v2.v1.ref(Path(__file__)),
              "controls": controls, "passed": all(control["passed"] for control in controls),
              "offline_requested": True, "corpus_installs": 0, "zkfuzz_invocations": 0}
    v2.v1.write_new(raw / "controls.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-controls", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    args = parser.parse_args()
    result = run_offline_controls(args.offline_controls, args.tools)
    print(json.dumps({"passed": result["passed"], "controls": [{key: row[key] for key in
                      ("manager", "version", "passed", "marker_presence")} for row in result["controls"]]}, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
