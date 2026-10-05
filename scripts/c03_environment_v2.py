#!/usr/bin/env python3
"""C-03 setup extension: inventory package coverage after submodule initialization.

V1 remains unchanged. Only tracked Circom path names are inventoried; source
contents, inputs, witnesses and repository scripts are not read or executed.
Independent nested package manifests do not inherit an unrelated ancestor lock.
"""

import ast
from datetime import datetime, timezone
import fnmatch
from pathlib import Path, PurePosixPath
import re
import shlex
import time

import c03_environment as v1


LOCKS = v1.LOCKS
include_paths = v1.include_paths
install_command = v1.install_command
run_command = v1.run_command


def _glob_parts_match(path_parts, pattern_parts):
    if not pattern_parts:
        return not path_parts
    if pattern_parts[0] == "**":
        return (_glob_parts_match(path_parts, pattern_parts[1:])
                or bool(path_parts) and _glob_parts_match(path_parts[1:], pattern_parts))
    return (bool(path_parts) and fnmatch.fnmatchcase(path_parts[0], pattern_parts[0])
            and _glob_parts_match(path_parts[1:], pattern_parts[1:]))


def _patterns_cover(relative, patterns):
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise ValueError("invalid_workspace_metadata")
    positives, negatives = [], []
    for pattern in patterns:
        negative = pattern.startswith("!")
        pattern = pattern[1:] if negative else pattern
        pattern = pattern.removeprefix("./").rstrip("/")
        if (not pattern or pattern.startswith("/") or ".." in pattern.split("/")
                or any(char in pattern for char in "{}\\")):
            raise ValueError("unsupported_workspace_pattern")
        matched = _glob_parts_match(relative.split("/"), pattern.split("/"))
        (negatives if negative else positives).append(matched)
    return any(positives) and not any(negatives)


def _yaml_pattern(value):
    tokens = shlex.split(value, comments=True, posix=True)
    if len(tokens) != 1 or tokens[0].startswith(("&", "*")):
        # A leading glob '*' is valid when quoted. Unquoted YAML '*' can be an
        # alias and is deliberately not interpreted by this limited parser.
        if not (len(tokens) == 1 and value.lstrip().startswith(("'", '"'))):
            raise ValueError("unsupported_pnpm_workspace_scalar")
    return tokens[0]


def _pnpm_patterns(path):
    """Read only explicit packages: string lists; do not evaluate YAML tags."""
    if path.is_symlink():
        raise ValueError("symlink_package_config")
    lines = path.read_text().splitlines()
    found = None
    for index, line in enumerate(lines):
        match = re.match(r"^packages\s*:\s*(.*)$", line)
        if not match:
            continue
        if found is not None:
            raise ValueError("duplicate_pnpm_packages_key")
        inline = match.group(1).strip()
        if inline and not inline.startswith("#"):
            try:
                found = ast.literal_eval(inline)
            except (SyntaxError, ValueError) as error:
                raise ValueError("unsupported_pnpm_workspace_inline_list") from error
            if not isinstance(found, list) or not all(isinstance(p, str) for p in found):
                raise ValueError("invalid_workspace_metadata")
            continue
        found = []
        for subsequent in lines[index + 1:]:
            if not subsequent.strip() or subsequent.lstrip().startswith("#"):
                continue
            # YAML allows an indentationless sequence under a mapping key.
            item = re.match(r"^\s*-\s+(.+)$", subsequent)
            if item:
                found.append(_yaml_pattern(item.group(1)))
            elif not subsequent[0].isspace():
                break
            else:
                raise ValueError("unsupported_pnpm_workspace_packages_shape")
    return found


def _workspace_covers(package, directory, nested_package):
    workspace = directory / "pnpm-workspace.yaml"
    patterns = _pnpm_patterns(workspace) if workspace.is_file() else None
    if patterns is None:
        patterns = package.get("workspaces", [])
        if isinstance(patterns, dict):
            patterns = patterns.get("packages", [])
    return _patterns_cover(nested_package.relative_to(directory).as_posix(), patterns)


def _install_root(root, location):
    ancestors = v1._ancestors(root, location)
    packages = [(directory, v1._json(directory / "package.json")) for directory in ancestors
                if (directory / "package.json").exists()]
    if not packages:
        # Preserve a malformed lock-only root as an explicit blocked plan.
        return next((directory for directory in ancestors
                     if any((directory / lock).exists() for lock in LOCKS)), None)
    nearest = packages[0][0]
    for directory, package in reversed(packages[1:]):
        if _workspace_covers(package, directory, nearest):
            return directory
    return nearest


def plan_installations(repo_root, circuit_paths):
    root = Path(repo_root).resolve()
    locations = [Path(p) if Path(p).is_absolute() else root / p for p in circuit_paths]
    if (root / "package.json").is_file() or any((root / lock).exists() for lock in LOCKS):
        locations.insert(0, root)
    plans, selected = [], set()
    for location in locations:
        try:
            chosen = _install_root(root, location)
            if chosen is None or chosen in selected:
                continue
            selected.add(chosen)
            plan = v1._plan_root(chosen)
            plan["installation_root_rule"] = "nearest_package_manifest_unless_explicit_ancestor_workspace_member"
            plans.append(plan)
        except (OSError, ValueError, TypeError) as error:
            plans.append(v1._blocked("invalid_package_metadata", reason=str(error),
                                    requested_location=str(location)))
    return sorted(plans, key=lambda plan: plan.get("install_root") or plan.get("requested_location", ""))


def _tracked_circom_paths(capture):
    reference = capture.get("stdout")
    if not isinstance(reference, dict) or not reference.get("path"):
        raise ValueError("tracked_inventory_stdout_missing")
    path = Path(reference["path"])
    if not reference.get("sha256") or v1.digest(path) != reference["sha256"]:
        raise ValueError("tracked_inventory_stdout_hash_mismatch")
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\0"):
        raise ValueError("tracked_inventory_incomplete_nul_record")
    paths = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        name = record.decode("utf-8", errors="surrogateescape")
        if not name.endswith(".circom"):
            continue
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("tracked_inventory_path_outside_repository")
        paths.add(name)
    return sorted(paths)


def run_setup(repo_root, circuit_paths, raw_dir, tools, caps=None, runner=None):
    """Initialize submodules, inventory tracked paths, then install package roots.

    Inventory failure is recorded as setup_failure while known circuit paths
    still receive their package setup attempts. No result directory is reused.
    """
    root, raw = Path(repo_root).resolve(), Path(raw_dir).resolve()
    raw.mkdir(parents=True, exist_ok=False)
    caps = caps or {"submodule": 180, "install": 600, "inventory": 120}
    runner = runner or run_command
    started = time.monotonic()
    tool_dirs = [Path(arg).parent for tool in tools.values() for arg in tool.get("argv", [])]
    isolated = v1.isolated_environment(raw, tool_dirs)
    known_paths = list(dict.fromkeys(str(path) for path in circuit_paths))
    result = {"schema_version": 2, "repository": str(root), "automatic_setup": True,
              "manual_intervention_count": 0, "zkfuzz_invocations": 0,
              "started_at": datetime.now(timezone.utc).isoformat(), "steps": [],
              "coverage_rule": "known_sources_plus_tracked_Circom_paths_after_submodule_initialization",
              "known_circuit_paths": known_paths}
    git_argv = None
    try:
        git_argv = v1._validate_tool(tools.get("git", {}), "git")
        safe_git = git_argv + ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
        capture = runner(safe_git + ["submodule", "update", "--init", "--recursive"],
                         raw / "submodule", caps["submodule"], root, isolated)
        result["steps"].append({"phase": "submodule", "capture": capture,
                                "status": capture["status"],
                                "failure_type": v1._failure(capture, "submodule")})
    except (OSError, ValueError, KeyError) as error:
        result["steps"].append({"phase": "submodule", "status": "unsupported",
                                "failure_type": "submodule_tool_unavailable", "reason": str(error)})
    tracked = []
    inventory_step = {"phase": "tracked_circom_inventory", "status": "unsupported",
                      "failure_type": "tracked_inventory_tool_unavailable"}
    if git_argv is not None:
        try:
            capture = runner(git_argv + ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                                        "ls-files", "--recurse-submodules", "-z"],
                             raw / "tracked-circom-inventory", caps.get("inventory", 120), root, isolated)
            inventory_step.update(capture=capture, status=capture["status"],
                                  failure_type=v1._failure(capture, "tracked_inventory"))
            if capture["status"] == "success":
                tracked = _tracked_circom_paths(capture)
        except (OSError, ValueError, KeyError, TypeError) as error:
            inventory_step.update(status="unknown", failure_type="tracked_inventory_unavailable", reason=str(error))
    inventory_step["tracked_circom_path_count"] = len(tracked)
    result["steps"].append(inventory_step)
    result["tracked_circom_paths"] = tracked
    result["tracked_inventory_status"] = inventory_step["status"]
    combined = list(dict.fromkeys(known_paths + tracked))
    result["installation_input_paths"] = combined
    plans = plan_installations(root, combined)
    result["installation_plans"] = plans
    for index, plan in enumerate(plans):
        step = {"phase": "package_install", "install_root": plan.get("install_root"),
                "manager": plan.get("manager"), "lockfile_present": plan.get("lockfile_present")}
        if plan["status"] != "ready":
            step.update(status="unsupported", failure_type=plan["failure_type"])
        else:
            try:
                tool = tools.get(plan["manager"], {})
                capture = runner(install_command(plan, tool), raw / ("install-" + str(index)),
                                 caps["install"], Path(plan["install_root"]), isolated)
                step.update(status=capture["status"], capture=capture,
                            failure_type=v1._failure(capture, "package_install"),
                            tool={"version": tool["version"], "files": tool["files"]})
            except (OSError, ValueError, KeyError) as error:
                step.update(status="unsupported", failure_type="package_manager_unavailable", reason=str(error))
        result["steps"].append(step)
    failures = [step["failure_type"] for step in result["steps"] if step.get("failure_type")]
    result.update(status="setup_failure" if failures else "success", failure_types=failures,
                  elapsed_seconds=time.monotonic() - started,
                  finished_at=datetime.now(timezone.utc).isoformat())
    v1.write_new(raw / "setup.json", result)
    return result
