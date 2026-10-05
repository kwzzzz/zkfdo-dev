#!/usr/bin/env python3
"""E-01 script-disabled Yarn Berry/pnpm/npm workspace setup extension."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

import c03_environment as v1
import c03_environment_v2 as v2


LOCKS = v1.LOCKS
include_paths = v1.include_paths
run_command = v1.run_command


def _tool(tools, key):
    tool = tools.get(key)
    if not isinstance(tool, dict) or not tool.get("argv") or not tool.get("files"):
        raise ValueError("package_manager_unavailable:" + key)
    pinned = {str(Path(item["path"]).resolve()): item["sha256"] for item in tool["files"]}
    for argument in tool["argv"]:
        path = str(Path(argument).resolve())
        if path not in pinned or v1.digest(path) != pinned[path]:
            raise ValueError("tool_hash_mismatch:" + key)
    return tool


def _declared_version(value, manager):
    if not isinstance(value, str) or not value.startswith(manager + "@"):
        return None
    raw = value.split("@", 1)[1].split("+", 1)[0]
    return raw if re.fullmatch(r"\d+\.\d+\.\d+", raw) else None


def _repository_yarn_version(root):
    versions = set()
    for package in root.rglob("package.json"):
        if "node_modules" in package.parts:
            continue
        try:
            version = _declared_version(json.loads(package.read_text()).get("packageManager"), "yarn")
        except (OSError, ValueError, TypeError):
            continue
        if version and int(version.split(".", 1)[0]) >= 2:
            versions.add(version)
    if len(versions) != 1:
        raise ValueError("ambiguous_yarn_berry_version")
    return versions.pop()


def _plan_root(root, repository_root):
    root = Path(root).resolve()
    package_path = root / "package.json"
    if not package_path.is_file():
        return v1._blocked("lockfile_without_package_json", root)
    package = v1._json(package_path)
    locks = [root / name for name in LOCKS if (root / name).exists()]
    managers = {LOCKS[path.name] for path in locks}
    declared = package.get("packageManager")
    declared_manager = declared.split("@", 1)[0] if isinstance(declared, str) else None
    if len(managers) > 1:
        if declared_manager in managers:
            manager = declared_manager
        else:
            return v1._blocked("ambiguous_lockfiles", root, lockfiles=[v1.ref(path) for path in locks])
    else:
        manager = next(iter(managers), declared_manager or "npm")
    if declared_manager and managers and declared_manager != manager:
        return v1._blocked("declared_manager_lockfile_mismatch", root)
    version = _declared_version(declared, manager)
    tool_key = manager
    effective_manager = manager
    if manager == "yarn":
        modern = bool((root / "yarn.lock").is_file() and re.search(
            r"(?m)^__metadata:", (root / "yarn.lock").read_text(errors="replace")))
        if modern:
            version = version or _repository_yarn_version(Path(repository_root).resolve())
            effective_manager = "yarn_berry"
            tool_key = "yarn@" + version
        else:
            tool_key = "yarn_classic"
    elif manager == "pnpm":
        if not version:
            return v1._blocked("pnpm_version_not_declared", root)
        tool_key = "pnpm@" + version
    elif manager == "npm":
        tool_key = "npm"
    else:
        return v1._blocked("unsupported_package_manager", root)
    return {
        "status": "ready", "failure_type": None, "install_root": str(root),
        "manager": effective_manager, "declared_package_manager": declared,
        "manager_version": version, "tool_key": tool_key,
        "lockfile_present": bool(locks), "lockfiles": [v1.ref(path) for path in locks],
        "package_json": v1.ref(package_path),
        "command": "ci" if manager == "npm" and locks else "install",
        "installation_root_rule": "nearest_package_manifest_unless_explicit_ancestor_workspace_member",
    }


def plan_installations(repo_root, circuit_paths):
    root = Path(repo_root).resolve()
    locations = [Path(path) if Path(path).is_absolute() else root / path for path in circuit_paths]
    if (root / "package.json").is_file() or any((root / lock).exists() for lock in LOCKS):
        locations.insert(0, root)
    selected, plans = set(), []
    for location in locations:
        try:
            chosen = v2._install_root(root, location)
            if chosen is None or chosen in selected:
                continue
            selected.add(chosen)
            plans.append(_plan_root(chosen, root))
        except (OSError, ValueError, TypeError) as error:
            plans.append(v1._blocked("invalid_package_metadata", reason=str(error),
                                     requested_location=str(location)))
    return sorted(plans, key=lambda plan: plan.get("install_root") or plan.get("requested_location", ""))


def install_command(plan, tools):
    tool = _tool(tools, plan["tool_key"])
    argv = list(tool["argv"])
    if plan["manager"] == "npm":
        return argv + [plan["command"], "--ignore-scripts", "--no-audit", "--no-fund",
                       "--git=/usr/bin/git", "--registry=https://registry.npmjs.org"]
    if plan["manager"] == "yarn":
        return argv + ["install", "--frozen-lockfile", "--ignore-scripts", "--ignore-engines",
                       "--no-default-rc", "--non-interactive", "--registry=https://registry.npmjs.org"]
    if plan["manager"] == "yarn_berry":
        return argv + ["install", "--immutable"]
    return argv + ["install", "--frozen-lockfile", "--ignore-scripts", "--ignore-pnpmfile",
                   "--config.manage-package-manager-versions=false",
                   "--config.package-manager-strict=false", "--registry=https://registry.npmjs.org"]


def _install_environment(base, plan, raw, index):
    env = dict(base)
    if plan["manager"] == "yarn_berry":
        # Yarn Classic's YARN_IGNORE_SCRIPTS maps to a removed Berry setting.
        # Berry uses enableScripts=false instead.
        env.pop("YARN_IGNORE_SCRIPTS", None)
        env.update({
            "YARN_ENABLE_SCRIPTS": "false", "YARN_IGNORE_PATH": "1",
            "YARN_NODE_LINKER": "node-modules", "YARN_ENABLE_GLOBAL_CACHE": "false",
            "YARN_CACHE_FOLDER": str(raw / ("yarn-berry-cache-" + str(index))),
        })
    return env


def _https_rewrites(root):
    path = Path(root) / ".gitmodules"
    if not path.is_file():
        return []
    rewrites = []
    for original in re.findall(r"(?m)^\s*url\s*=\s*(\S+)\s*$", path.read_text(errors="replace")):
        match = re.fullmatch(r"git@([^:]+):(.+)", original)
        if match:
            replacement = "https://" + match.group(1) + "/" + match.group(2)
        else:
            match = re.fullmatch(r"ssh://(?:git@)?([^/]+)/(.+)", original)
            replacement = "https://" + match.group(1) + "/" + match.group(2) if match else None
        if replacement:
            rewrites.append({"original": original, "https": replacement})
    return rewrites


def run_setup(repo_root, circuit_paths, raw_dir, tools, caps=None, runner=None):
    root, raw = Path(repo_root).resolve(), Path(raw_dir).resolve()
    raw.mkdir(parents=True, exist_ok=False)
    caps = caps or {"submodule": 180, "install": 600, "inventory": 120}
    execute = runner or run_command
    started = time.monotonic()
    tool_dirs = [Path(argument).parent for tool in tools.values() for argument in tool.get("argv", [])]
    isolated = v1.isolated_environment(raw, tool_dirs)
    result = {"schema_version": 1, "task": "E-01", "repository": str(root),
              "automatic_setup": True, "manual_intervention_count": 0,
              "zkfuzz_invocations": 0, "started_at": datetime.now(timezone.utc).isoformat(),
              "steps": [], "known_circuit_paths": list(dict.fromkeys(map(str, circuit_paths)))}
    git = _tool(tools, "git")["argv"]
    safe = list(git) + ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
    capture = execute(safe + ["submodule", "update", "--init", "--recursive"],
                      raw / "submodule-original", caps["submodule"], root, isolated)
    rewrites = _https_rewrites(root)
    submodule = {"phase": "submodule", "original_attempt": capture, "https_rewrites": rewrites,
                 "https_retry_performed": False}
    if capture["status"] != "success" and rewrites:
        command = list(safe)
        for rewrite in rewrites:
            command.extend(["-c", "url." + rewrite["https"] + ".insteadOf=" + rewrite["original"]])
        retry = execute(command + ["submodule", "update", "--init", "--recursive"],
                        raw / "submodule-https-retry", caps["submodule"], root, isolated)
        submodule.update(https_retry_performed=True, https_attempt=retry,
                         status=retry["status"], failure_type=v1._failure(retry, "submodule"))
    else:
        submodule.update(status=capture["status"], failure_type=v1._failure(capture, "submodule"))
    result["steps"].append(submodule)
    inventory = execute(safe + ["ls-files", "--recurse-submodules", "-z"],
                        raw / "tracked-circom-inventory", caps.get("inventory", 120), root, isolated)
    tracked = []
    if inventory["status"] == "success":
        tracked = [item.decode(errors="surrogateescape") for item in
                   Path(inventory["stdout"]["path"]).read_bytes().split(b"\0") if item.endswith(b".circom")]
    result["steps"].append({"phase": "tracked_circom_inventory", "capture": inventory,
                            "status": inventory["status"],
                            "failure_type": v1._failure(inventory, "tracked_inventory"),
                            "tracked_circom_path_count": len(tracked)})
    combined = list(dict.fromkeys(result["known_circuit_paths"] + tracked))
    plans = plan_installations(root, combined)
    result["installation_plans"] = plans
    for index, plan in enumerate(plans):
        step = {"phase": "package_install", "install_root": plan.get("install_root"),
                "manager": plan.get("manager"), "manager_version": plan.get("manager_version"),
                "tool_key": plan.get("tool_key"), "lockfile_present": plan.get("lockfile_present")}
        if plan["status"] != "ready":
            step.update(status="unsupported", failure_type=plan["failure_type"])
        else:
            try:
                command = install_command(plan, tools)
                capture = execute(command, raw / ("install-" + str(index)), caps["install"],
                                  Path(plan["install_root"]), _install_environment(isolated, plan, raw, index))
                step.update(command=command, capture=capture, status=capture["status"],
                            failure_type=v1._failure(capture, "package_install"),
                            script_policy="disabled_by_cli_and_isolated_environment")
            except (OSError, ValueError, KeyError) as error:
                step.update(status="unsupported", failure_type="package_manager_unavailable",
                            reason=type(error).__name__ + ": " + str(error))
        result["steps"].append(step)
    failures = [step["failure_type"] for step in result["steps"] if step.get("failure_type")]
    result.update(status="setup_failure" if failures else "success", failure_types=failures,
                  elapsed_seconds=time.monotonic() - started,
                  finished_at=datetime.now(timezone.utc).isoformat())
    v1.write_new(raw / "setup.json", result)
    return result
