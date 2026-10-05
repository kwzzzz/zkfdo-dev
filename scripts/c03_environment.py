#!/usr/bin/env python3
"""C-03 bounded, script-disabled dependency setup. No compiler or search engine.

Tool argv/version/file hashes must be supplied by the frozen experiment lock.
Only registry-provisioned npm, Yarn Classic and pnpm 10 are supported; Corepack,
project Yarn releases/plugins and package-manager auto-download are not invoked.
"""

from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from measure_c02_preparation import cleanup_session, session_members

LOCKS = {"npm-shrinkwrap.json": "npm", "package-lock.json": "npm",
         "yarn.lock": "yarn", "pnpm-lock.yaml": "pnpm"}
CONFIG_FILES = (".npmrc", ".yarnrc", ".yarnrc.yml", ".pnpmfile.cjs",
                ".pnpmfile.mjs", "pnpm-workspace.yaml")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def write_new(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _inside(path, root):
    path = Path(path)
    try:
        path.resolve().relative_to(root)
    except ValueError as error:
        raise ValueError("path_outside_repository") from error
    return path.resolve()


def _ancestors(root, location):
    location = _inside(location, root)
    current = location if location.is_dir() else location.parent
    result = []
    while True:
        result.append(current)
        if current == root:
            return result
        current = current.parent


def _json(path):
    if path.is_symlink():
        raise ValueError("symlink_package_metadata")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("invalid_package_metadata")
    return value


def _workspace_contains(package, root, location):
    patterns = package.get("workspaces", [])
    if isinstance(patterns, dict):
        patterns = patterns.get("packages", [])
    if not isinstance(patterns, list) or not all(isinstance(x, str) for x in patterns):
        raise ValueError("invalid_workspace_metadata")
    relative = location.relative_to(root).as_posix()
    prefixes = [relative] + [p.as_posix() for p in Path(relative).parents if str(p) != "."]
    return any(fnmatch.fnmatchcase(p, pattern.rstrip("/"))
               for pattern in patterns for p in prefixes)


def _install_root(root, location):
    ancestors = _ancestors(root, location)
    packages = [(directory, _json(directory / "package.json")) for directory in ancestors
                if (directory / "package.json").exists()]
    for directory, package in reversed(packages):
        if directory != ancestors[0] and _workspace_contains(package, directory, ancestors[0]):
            return directory
        if (directory / "pnpm-workspace.yaml").is_file():
            return directory
    for directory in ancestors:
        if any((directory / name).exists() for name in LOCKS):
            return directory
    return packages[0][0] if packages else None


def _blocked(failure_type, root=None, **extra):
    return {"status": "unsupported", "failure_type": failure_type,
            "install_root": str(root) if root else None, **extra}


def _plan_root(root):
    package_path = root / "package.json"
    if not package_path.is_file():
        return _blocked("lockfile_without_package_json", root)
    package = _json(package_path)
    locks = [root / name for name in LOCKS if (root / name).exists()]
    if any(path.is_symlink() for path in locks):
        return _blocked("symlink_lockfile", root)
    managers = {LOCKS[path.name] for path in locks}
    declared = package.get("packageManager")
    declared_manager = declared.split("@", 1)[0] if isinstance(declared, str) else None
    if len(managers) > 1:
        if declared_manager in managers:
            manager = declared_manager
        else:
            return _blocked("ambiguous_lockfiles", root, lockfiles=[ref(p) for p in locks])
    else:
        manager = next(iter(managers), "npm")
    if declared_manager and managers and declared_manager != manager:
        return _blocked("declared_manager_lockfile_mismatch", root)
    if any((root / name).is_symlink() for name in CONFIG_FILES):
        return _blocked("symlink_package_config", root)
    config_refs = [ref(root / name) for name in CONFIG_FILES if (root / name).is_file()]
    if manager == "yarn":
        yarn_lock = (root / "yarn.lock").read_text(errors="replace")
        if re.search(r"(?m)^__metadata:", yarn_lock) or (
                isinstance(declared, str) and re.match(r"yarn@(?:[2-9]|\d{2})", declared)):
            return _blocked("unsupported_yarn_modern", root, configuration=config_refs)
    workspace = root / "pnpm-workspace.yaml"
    rc = root / ".npmrc"
    # pnpm can load configuration dependencies and provision a Node runtime before
    # lifecycle flags apply. Do not interpret or execute these project extensions.
    if manager == "pnpm":
        text = "\n".join(path.read_text(errors="replace") for path in (workspace, rc)
                         if path.is_file())
        if re.search(r"(?im)^\s*(configDependencies|config-dependencies|useNodeVersion|use-node-version)\s*[:=]", text):
            return _blocked("unsupported_pnpm_executable_configuration", root,
                            configuration=config_refs)
        if "executionEnv" in package.get("pnpm", {}) or "configDependencies" in package:
            return _blocked("unsupported_pnpm_executable_configuration", root,
                            configuration=config_refs)
    return {"status": "ready", "failure_type": None, "install_root": str(root),
            "manager": manager, "declared_package_manager": declared,
            "lockfile_present": bool(locks), "lockfiles": [ref(p) for p in locks],
            "package_json": ref(package_path), "configuration": config_refs,
            "lockfile_selection": "declared_manager" if len(managers) > 1 else "unambiguous",
            "command": "ci" if manager == "npm" and locks else "install"}


def plan_installations(repo_root, circuit_paths):
    """Select workspace/ancestor lock roots from metadata, never tool outcomes."""
    root = Path(repo_root).resolve()
    locations = [Path(p) if Path(p).is_absolute() else root / p for p in circuit_paths]
    if (root / "package.json").is_file() or any((root / name).exists() for name in LOCKS):
        locations.insert(0, root)
    plans, selected = [], set()
    for location in locations:
        try:
            chosen = _install_root(root, location)
            if chosen is None or chosen in selected:
                continue
            selected.add(chosen)
            plans.append(_plan_root(chosen))
        except (OSError, ValueError, TypeError) as error:
            plans.append(_blocked("invalid_package_metadata", reason=str(error),
                                  requested_location=str(location)))
    return sorted(plans, key=lambda p: p.get("install_root") or p.get("requested_location", ""))


def include_paths(repo_root, circuit, plans=()):
    """Fixed search order: root, root/node_modules, circuit dir, ancestor modules."""
    root = Path(repo_root).resolve()
    circuit = Path(circuit)
    if not circuit.is_absolute():
        circuit = root / circuit
    ancestors = _ancestors(root, circuit)
    candidates = [root, root / "node_modules", ancestors[0]]
    candidates.extend(directory / "node_modules" for directory in ancestors)
    candidates.extend(Path(p["install_root"]) / "node_modules" for p in plans
                      if p.get("install_root") and Path(p["install_root"]) in ancestors)
    return list(dict.fromkeys(str(p) for p in candidates))


def _validate_tool(tool, manager):
    argv, pins = tool.get("argv", []), tool.get("files", [])
    if not argv or not pins or not all(Path(arg).is_absolute() for arg in argv):
        raise ValueError("untrusted_tool_definition")
    for pin in pins:
        if digest(pin["path"]) != pin["sha256"]:
            raise ValueError("tool_hash_mismatch")
    by_path = {str(Path(p["path"]).resolve()): p["sha256"] for p in pins}
    for arg in argv:
        path = Path(arg)
        if str(path.resolve()) not in by_path or digest(path) != by_path[str(path.resolve())]:
            raise ValueError("tool_hash_mismatch")
    version = tool.get("version", "")
    if manager == "npm" and not version.startswith("11."):
        raise ValueError("unsupported_npm_tool_version")
    if manager == "yarn" and not version.startswith("1."):
        raise ValueError("unsupported_yarn_tool_version")
    if manager == "pnpm" and not version.startswith("10."):
        raise ValueError("unsupported_pnpm_tool_version")
    if any("corepack" in str(arg).lower() for arg in argv):
        raise ValueError("corepack_is_not_a_pinned_manager")
    return list(argv)


def isolated_environment(raw_dir, tool_dirs):
    raw_dir = Path(raw_dir).resolve()
    configuration = raw_dir / "isolated-config"
    configuration.mkdir(parents=True, exist_ok=False)
    for name in ("user.npmrc", "global.npmrc", "gitconfig"):
        (configuration / name).write_text("")
    # Do not inherit NODE_OPTIONS, credentials, project PATH or package-manager
    # variables. Do not change HOME; explicit config locations replace user rc.
    env = {"PATH": os.pathsep.join(dict.fromkeys([*map(str, tool_dirs), "/usr/bin", "/bin"])),
           "LANG": "C.UTF-8", "CI": "true", "GIT_TERMINAL_PROMPT": "0",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(configuration / "gitconfig"),
           "GIT_CONFIG_SYSTEM": str(configuration / "gitconfig"),
           "GIT_CONFIG_COUNT": "4", "GIT_CONFIG_KEY_0": "core.hooksPath",
           "GIT_CONFIG_VALUE_0": "/dev/null", "GIT_CONFIG_KEY_1": "protocol.allow",
           "GIT_CONFIG_VALUE_1": "never", "GIT_CONFIG_KEY_2": "protocol.https.allow",
           "GIT_CONFIG_VALUE_2": "always", "GIT_CONFIG_KEY_3": "credential.helper",
           "GIT_CONFIG_VALUE_3": "", "npm_config_userconfig": str(configuration / "user.npmrc"),
           "npm_config_globalconfig": str(configuration / "global.npmrc"),
           "npm_config_cache": str(raw_dir / "npm-cache"), "npm_config_ignore_scripts": "true",
           "npm_config_store_dir": str(raw_dir / "pnpm-store"),
           "npm_config_prefix": str(raw_dir / "local-prefix"),
           "YARN_CACHE_FOLDER": str(raw_dir / "yarn-cache"),
           "YARN_GLOBAL_FOLDER": str(raw_dir / "yarn-global"),
           "XDG_CACHE_HOME": str(raw_dir / "cache"),
           "XDG_CONFIG_HOME": str(configuration / "xdg"),
           "XDG_DATA_HOME": str(raw_dir / "data"),
           "npm_config_git": "/usr/bin/git", "npm_config_audit": "false", "npm_config_fund": "false",
           "npm_config_update_notifier": "false", "YARN_IGNORE_PATH": "1",
           "YARN_IGNORE_SCRIPTS": "1", "COREPACK_ENABLE_PROJECT_SPEC": "0",
           "COREPACK_ENABLE_NETWORK": "0", "PNPM_PACKAGE_MANAGER_STRICT": "false"}
    return env


def install_command(plan, tool):
    manager = plan["manager"]
    argv = _validate_tool(tool, manager)
    if manager == "npm":
        return argv + [plan["command"], "--ignore-scripts", "--no-audit", "--no-fund",
                       "--git=/usr/bin/git", "--registry=https://registry.npmjs.org"]
    if manager == "yarn":
        return argv + ["install", "--frozen-lockfile", "--ignore-scripts", "--no-default-rc",
                       "--non-interactive", "--registry=https://registry.npmjs.org"]
    return argv + ["install", "--frozen-lockfile", "--ignore-scripts", "--ignore-pnpmfile",
                   "--manage-package-manager-versions=false", "--package-manager-strict=false",
                   "--registry=https://registry.npmjs.org"]


def run_command(argv, directory, cap, cwd, env):
    """Bound complete session, including descendants with separate process groups."""
    session_members(os.getsid(0))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    result = {"argv": list(argv), "started_at": datetime.now(timezone.utc).isoformat(),
              "cap_seconds": cap, "status": "start_failure", "exit_code": None,
              "process_started": False}
    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            result["process_started"] = True
            try:
                result["exit_code"] = process.wait(timeout=cap)
                result["status"] = "success" if process.returncode == 0 else "failure"
            except subprocess.TimeoutExpired:
                result["cleanup_signaled_pids"] = cleanup_session(process.pid)
                result["exit_code"] = process.wait()
                result["status"] = "timeout"
            result["post_exit_cleanup_signaled_pids"] = cleanup_session(process.pid)
        except OSError as error:
            result["reason"] = str(error)
    result.update(elapsed_seconds=time.monotonic() - start,
                  finished_at=datetime.now(timezone.utc).isoformat(),
                  stdout=ref(directory / "stdout.log"), stderr=ref(directory / "stderr.log"))
    write_new(directory / "invocation.json", result)
    return result


def _failure(capture, phase):
    if capture["status"] == "success":
        return None
    if capture["status"] != "failure":
        return phase + "_" + capture["status"]
    text = "\n".join(Path(capture[key]["path"]).read_text(errors="replace")
                     for key in ("stdout", "stderr") if capture.get(key)).lower()
    for label, needles in [
        ("network", ("enotfound", "econn", "network", "could not resolve", "unable to access")),
        ("lockfile_mismatch", ("frozen-lockfile", "outdated_lockfile", "lock file's", "npm ci can only")),
        ("dependency_resolution", ("eresolve", "couldn't find package", "no matching version")),
        ("authentication", ("401", "403", "authentication", "permission denied")),
        ("unsupported_protocol", ("unsupported url", "unsupported protocol", "not allowed")),
        ("engine_version", ("unsupported engine", "incompatible with this module")),
    ]:
        if any(needle in text for needle in needles):
            return phase + "_" + label
    return phase + "_command_failed"


def run_setup(repo_root, circuit_paths, raw_dir, tools, caps=None, runner=None):
    """Perform each automatic step once; retain failures and continue other roots.

    caps = {'submodule': seconds, 'install': seconds}; runner injection supports
    synthetic tests. Existing result directories are never overwritten.
    """
    root, raw = Path(repo_root).resolve(), Path(raw_dir).resolve()
    raw.mkdir(parents=True, exist_ok=False)
    caps = caps or {"submodule": 120, "install": 300}
    runner = runner or run_command
    started = time.monotonic()
    tool_dirs = [Path(arg).parent for tool in tools.values() for arg in tool.get("argv", [])]
    env = isolated_environment(raw, tool_dirs)
    result = {"schema_version": 1, "repository": str(root), "automatic_setup": True,
              "manual_intervention_count": 0, "zkfuzz_invocations": 0,
              "started_at": datetime.now(timezone.utc).isoformat(), "steps": []}
    try:
        git_argv = _validate_tool(tools.get("git", {}), "git")
        capture = runner(git_argv + ["submodule", "update", "--init", "--recursive"],
                         raw / "submodule", caps["submodule"], root, env)
        result["steps"].append({"phase": "submodule", "capture": capture,
                                "status": capture["status"],
                                "failure_type": _failure(capture, "submodule")})
    except (OSError, ValueError, KeyError) as error:
        result["steps"].append({"phase": "submodule", "status": "unsupported",
                                "failure_type": "submodule_tool_unavailable", "reason": str(error)})
    # Submodule initialization may introduce the package metadata used below.
    plans = plan_installations(root, circuit_paths)
    result["installation_plans"] = plans
    for index, plan in enumerate(plans):
        step = {"phase": "package_install", "install_root": plan.get("install_root"),
                "manager": plan.get("manager"), "lockfile_present": plan.get("lockfile_present")}
        if plan["status"] != "ready":
            step.update(status="unsupported", failure_type=plan["failure_type"])
        else:
            try:
                tool = tools.get(plan["manager"], {})
                argv = install_command(plan, tool)
                capture = runner(argv, raw / ("install-" + str(index)), caps["install"],
                                 Path(plan["install_root"]), env)
                step.update(status=capture["status"], capture=capture,
                            failure_type=_failure(capture, "package_install"),
                            tool={"version": tool["version"], "files": tool["files"]})
            except (OSError, ValueError, KeyError) as error:
                step.update(status="unsupported", failure_type="package_manager_unavailable",
                            reason=str(error))
        result["steps"].append(step)
    failures = [step["failure_type"] for step in result["steps"] if step.get("failure_type")]
    result.update(status="setup_failure" if failures else "success", failure_types=failures,
                  elapsed_seconds=time.monotonic() - started,
                  finished_at=datetime.now(timezone.utc).isoformat())
    write_new(raw / "setup.json", result)
    return result
