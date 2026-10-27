#!/usr/bin/env python3
"""N5 amended base-input selection with a Docker-only project (d) step.

The original (a), (b), (c), (e), compile, and honest-witness checks are reused.
No project test, package install, or build runs on the host. Raw captures and
full container logs stay in the ignored output tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import n6_j1_base_inputs as base

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOOLS = ROOT / "runs/n6-b5-2026-10-17.noindex/install-tools.json"
DEFAULT_B_MANIFEST = ROOT / "runs/n6-j3-2026-10-14.noindex/revision-manifest.json"
DEFAULT_B_R1CS = ROOT / "runs/n6-b5-2026-10-17.noindex/b-r1cs-reference-v2.json"
DEFAULT_A_MANIFEST = ROOT / "runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json"
DEFAULT_A_R1CS = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
MEM20_STATE = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json"
MEM20_RETRY_STATE = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-retry.noindex/state.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PACKAGE_MANAGER = re.compile(r"^(npm|yarn|pnpm)@([0-9][0-9A-Za-z.+-]*)$")
TEST_COMMAND_API = re.compile(r"\b(?:execSync|exec|spawnSync|spawn|execa|execFileSync)\s*\(")
TEST_COMMAND_LITERAL = re.compile(
    r"\b(?:execSync|exec|spawnSync|spawn|execa|execFileSync)\s*\(\s*(['\"`])([^'\"`]*?)\1",
    re.DOTALL)
NETWORK_ERRORS = (
    b"enotfound", b"eai_again", b"econnrefused", b"enetunreach", b"ehostunreach",
    b"etimedout", b"econnreset", b"esockettimedout", b"und_err_connect_timeout",
    b"could not resolve host", b"temporary failure in name resolution",
    b"network is unreachable", b"connection refused", b"connection timed out",
    b"proxy error", b"proxyconnect", b"proxy connection", b"proxy authentication",
    b"proxy authorization", b"407 proxy", b"err_proxy_",
    b"tunneling socket could not be established",
)
DOCKER_ERRORS = (
    b"cannot connect to the docker daemon",
    b"permission denied while trying to connect to the docker api",
    b"permission denied while trying to connect to the docker daemon socket",
    b"docker.sock: connect: permission denied",
)
INSTALL_PERMISSION_ERRORS = (b"eacces", b"eperm", b"permission denied")
CONTAINER_TOOLS = ("git", "circom", "python", "python3", "make", "g++", "gcc",
                   "cc", "bash", "sh", "node", "npm", "npx", "corepack", "yarn", "pnpm")
GITHUB_SSH_PREFIXES = ("git+ssh://git@github.com/", "ssh://git@github.com/")


class EnvironmentBlocked(RuntimeError):
    """Docker or network cannot be used in this environment; retry later."""


class ToolBlocked(RuntimeError):
    """A required executable or pinned tool is missing from our container."""


class PolicyFailure(RuntimeError):
    """The unchanged project does not satisfy the amended (d) rule."""


class ScriptChainCycle(PolicyFailure):
    """A statically resolved package script would call itself again."""

    def __init__(self, chain: list[dict]):
        super().__init__("package_script_cycle")
        self.chain = chain


def load_tools(path: Path) -> dict:
    tools = json.loads(path.read_text())
    image = tools.get("image", "")
    if not image.startswith("docker.io/library/node@sha256:") or not HEX64.fullmatch(image.split(":")[-1]):
        raise ValueError("official Node image must be pinned by digest")
    if tools.get("platform") != "linux/amd64":
        raise ValueError("pinned official circom release requires linux/amd64")
    for key in ("node", "npm", "corepack", "yarn_classic", "yarn_modern", "pnpm"):
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", tools.get(key, "")):
            raise ValueError(f"fixed {key} version missing")
    return tools


def reference_hashes(path: Path, scope: str) -> dict[str, dict]:
    reference = json.loads(path.read_text())
    if scope == "B":
        if reference.get("schema") != "n6-b5-r1cs-reference-v1":
            raise ValueError("unexpected B fuzz R1CS reference schema")
        return reference["revisions"]
    if reference.get("schema") != "n6-j1-base-inputs-v1":
        raise ValueError("unexpected A original base-input index schema")
    rows = {}
    for identifier, row in reference["revisions"].items():
        digest = row.get("compile", {}).get("r1cs_sha256")
        rows[identifier] = {"status": "verified" if isinstance(digest, str) and HEX64.fullmatch(digest) else "unavailable",
                            "r1cs_sha256": digest}
    return rows


def mem20_finished() -> bool:
    if not MEM20_STATE.is_file():
        return False
    original = json.loads(MEM20_STATE.read_text())
    if original.get("status") == "completed":
        return True
    if original.get("status") != "stopped_between_units" or not MEM20_RETRY_STATE.is_file():
        return False
    retry = json.loads(MEM20_RETRY_STATE.read_text())
    source = retry.get("source_state", {})
    return (retry.get("status") == "completed" and
            retry.get("queue_sha256") == original.get("queue_sha256") and
            (ROOT / source.get("path", "")).resolve() == MEM20_STATE.resolve() and
            source.get("sha256") == base.sha256(MEM20_STATE))


def choose_install(package_dir: Path, project: Path, tools: dict) -> tuple[list[str], Path, str]:
    """Select exactly one lock and its whitelisted immutable install command."""
    for folder in (package_dir, *[p for p in package_dir.parents if p.is_relative_to(project)]):
        if folder == project.parent:
            break
        package = folder / "package.json"
        if not package.is_file():
            continue
        locks = [p for name in ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
                 if (p := folder / name).is_file()]
        if len(locks) > 1:
            raise PolicyFailure("multiple lock formats in one package directory")
        if not locks:
            continue
        lock = locks[0]
        payload = json.loads(package.read_text())
        manager = "npm" if lock.name in ("package-lock.json", "npm-shrinkwrap.json") else (
            "yarn" if lock.name == "yarn.lock" else "pnpm")
        declared = payload.get("packageManager")
        if declared:
            match = PACKAGE_MANAGER.fullmatch(declared)
            if match is None or match.group(1) != manager:
                raise PolicyFailure("packageManager does not match committed lock")
            version = match.group(2)
        else:
            version = (tools["npm"] if manager == "npm" else
                       tools["yarn_modern"] if manager == "yarn" and "__metadata" in lock.read_text(errors="ignore") else
                       tools["yarn_classic"] if manager == "yarn" else tools["pnpm"])
        modern_yarn = manager == "yarn" and "__metadata" in lock.read_text(errors="ignore")
        command = (["npm", "ci", "--ignore-scripts"] if manager == "npm" else
                   ["corepack", f"yarn@{version}", "install", "--immutable"] if modern_yarn else
                   ["corepack", f"yarn@{version}", "install", "--frozen-lockfile", "--ignore-scripts"] if manager == "yarn" else
                   ["corepack", f"pnpm@{version}", "install", "--frozen-lockfile", "--ignore-scripts"])
        if manager == "npm" and version != tools["npm"]:
            command = ["corepack", f"npm@{version}", "ci", "--ignore-scripts"]
        return command, lock, f"{manager}@{version}"
    raise PolicyFailure("committed lock and package.json not found")


def verify_committed_lock(row: dict, lock: Path, staged_project: Path) -> str:
    repository = base.workspace_path(row["git_repository_path"])
    revision = row["revision_commit"]
    relative = lock.relative_to(staged_project).as_posix()
    try:
        committed = subprocess.run(["git", "-C", str(repository), "show", f"{revision}:{relative}"],
                                   capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PolicyFailure("committed lock lookup failed") from error
    if committed.returncode:
        raise PolicyFailure("lock absent from recorded revision")
    digest = hashlib.sha256(committed.stdout).hexdigest()
    if digest != base.sha256(lock):
        raise PolicyFailure("copied lock differs from recorded revision")
    return digest


def github_ssh_git_config(lock: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Use Git's container-local URL rewrite only for GitHub SSH refs in this lock."""
    contents = lock.read_text(errors="ignore")
    present = [prefix for prefix in GITHUB_SSH_PREFIXES if prefix in contents]
    if not present:
        return {}, []
    configuration = {"GIT_CONFIG_COUNT": str(len(present))}
    recorded = []
    for index, prefix in enumerate(present):
        configuration[f"GIT_CONFIG_KEY_{index}"] = "url.https://github.com/.insteadOf"
        configuration[f"GIT_CONFIG_VALUE_{index}"] = prefix
        recorded.append({"key": 'url."https://github.com/".insteadOf',
                         "value": prefix})
    return configuration, recorded


def verify_no_tracked_install_artifacts(row: dict) -> None:
    """Do not silently remove zero-install files from the recorded revision."""
    if "git_repository_path" not in row or "revision_commit" not in row:
        raise PolicyFailure("recorded revision missing for dependency provenance")
    repository = base.workspace_path(row["git_repository_path"])
    revision = row["revision_commit"]
    try:
        result = subprocess.run(["git", "-C", str(repository), "ls-tree", "-r", "-z",
                                 "--name-only", revision], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PolicyFailure("tracked install artifact lookup failed") from error
    if result.returncode:
        raise PolicyFailure("tracked install artifact lookup failed")
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        parts = raw.decode("utf-8", errors="surrogateescape").split("/")
        if ("node_modules" in parts or any(name.startswith(".pnp.") for name in parts) or
                any(parts[index:index + 2] in ([".yarn", "cache"], [".yarn", "unplugged"])
                    for index in range(len(parts) - 1)) or
                (len(parts) >= 2 and parts[-2] == ".yarn" and
                 parts[-1] in {"install-state.gz", "build-state.yml"})):
            raise PolicyFailure("tracked_install_artifact_requires_separate_rule")


def node_modules_hash(package_dir: Path) -> str | None:
    root = package_dir / "node_modules"
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        files.sort()
        for name in dirs + files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode() + b"\0")
            if path.is_symlink():
                digest.update(b"link\0" + os.readlink(path).encode() + b"\0")
            elif path.is_file():
                digest.update(b"file\0" + base.sha256(path).encode() + b"\0")
            else:
                digest.update(b"dir\0")
    return digest.hexdigest()


def installed_packages_record(package_dir: Path) -> dict:
    modules = node_modules_hash(package_dir)
    if modules:
        return {"method": "node_modules_tree_sha256", "sha256": modules}
    pnp = package_dir / ".pnp.cjs"
    if pnp.is_file():
        cache = package_dir / ".yarn/cache"
        if not cache.is_dir():
            raise PolicyFailure("Yarn PnP cache absent after install")
        digest = hashlib.sha256()
        digest.update(base.sha256(pnp).encode())
        for path in sorted(cache.iterdir()):
            if path.is_file():
                digest.update(path.name.encode() + b"\0" + base.sha256(path).encode() + b"\0")
        return {"method": "yarn_pnp_and_cache_sha256", "sha256": digest.hexdigest()}
    raise PolicyFailure("installed package inventory missing")


def package_build_script(package_dir: Path, test_file: Path | None = None) -> str | None:
    selected, _ = named_build_target(package_dir, package_dir, test_file)
    return selected[1] if selected else None


def _script_segments(command: str) -> tuple[list[list[str]], bool]:
    """Split shell control operators without treating quoted text as commands."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return [], True
    segments: list[list[str]] = []
    current: list[str] = []
    conditional = False
    operators = []
    for token in tokens:
        if token and set(token) <= set(";&|()"):
            operators.append(token)
            if current:
                segments.append(current)
                current = []
            if token not in {"&&", ";"}:
                conditional = True
        else:
            current.append(token)
    if current:
        segments.append(current)
    if any(token in {"if", "then", "else", "elif", "fi", "for", "while", "do", "done",
                     "case", "esac", "exit", "return", "break", "continue"}
           for segment in segments for token in segment):
        conditional = True
    if "&&" in operators and (";" in operators or "\n" in command):
        conditional = True
    return segments, conditional


def _script_invocation(tokens: list[str]) -> dict | None:
    """Recognize ordinary npm, Yarn, and pnpm script invocations."""
    index = 0
    while index < len(tokens) and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]) or
                                   tokens[index] in {"env", "cross-env", "cross-env-shell"}):
        index += 1
    if index < len(tokens) and tokens[index] == "corepack":
        index += 1
    if index >= len(tokens):
        return None
    manager = tokens[index].split("@", 1)[0]
    if manager not in {"npm", "yarn", "pnpm"}:
        return None
    args = tokens[index + 1:]
    workspace = None
    directory = None
    kept = []
    offset = 0
    while offset < len(args):
        token = args[offset]
        if token in {"-w", "--workspace", "--filter", "-F", "-C", "--dir", "--cwd"}:
            if offset + 1 >= len(args):
                return {"dynamic": True, "reason": "workspace_argument_missing"}
            if token in {"-C", "--dir", "--cwd"}:
                directory = args[offset + 1]
            else:
                workspace = args[offset + 1]
            offset += 2
            continue
        if token.startswith(("--workspace=", "--filter=", "--dir=", "--cwd=")):
            key, value = token.split("=", 1)
            if key in {"--dir", "--cwd"}:
                directory = value
            else:
                workspace = value
            offset += 1
            continue
        kept.append(token)
        offset += 1
    args = kept
    if manager == "yarn" and args[:1] == ["workspace"]:
        if len(args) < 3:
            return {"dynamic": True, "reason": "workspace_script_unresolved"}
        workspace, args = args[1], args[2:]
    elif manager == "yarn" and args[:2] == ["workspaces", "foreach"]:
        return {"dynamic": True, "reason": "workspace_foreach"}
    if args[:1] in (["run"], ["run-script"]):
        args = args[1:]
    elif manager == "npm" and args[:1] not in (["test"], ["start"], ["stop"]):
        if "run" in args or "run-script" in args:
            return {"dynamic": True, "reason": "workspace_selector_unresolved"}
        return None
    elif manager == "yarn" and args[:1] in (["install"], ["add"], ["remove"], ["exec"], ["dlx"], ["node"]):
        return None
    elif manager == "pnpm" and args[:1] in (["install"], ["add"], ["remove"], ["exec"], ["dlx"]):
        return None
    if args[:1] in (["-r"], ["--recursive"]):
        return {"dynamic": True, "reason": "workspace_recursive"}
    if not args:
        return {"dynamic": True, "reason": "script_name_missing"}
    script = args[0]
    if "$" in script or "`" in script or not re.fullmatch(r"[A-Za-z0-9:._-]+", script):
        return {"dynamic": True, "reason": "script_name_dynamic"}
    return {"script": script, "workspace": workspace, "directory": directory}


def _workspace_package(project: Path, current: Path, selector: str) -> Path | None:
    """Resolve a workspace name or path only within the staged repository."""
    root = next((folder for folder in (current, *current.parents)
                 if folder.is_relative_to(project) and
                 ((folder / "package.json").is_file() and
                  json.loads((folder / "package.json").read_text()).get("workspaces") or
                  (folder / "pnpm-workspace.yaml").is_file())), project)
    direct = (root / selector).resolve()
    if direct.is_relative_to(project.resolve()) and (direct / "package.json").is_file():
        return direct
    patterns = []
    package = root / "package.json"
    if package.is_file():
        declared = json.loads(package.read_text()).get("workspaces", [])
        patterns.extend(declared.get("packages", []) if isinstance(declared, dict) else declared)
    workspace_file = root / "pnpm-workspace.yaml"
    if workspace_file.is_file():
        patterns.extend(re.findall(r"^\s*-\s*['\"]?([^'\"\s]+)",
                                   workspace_file.read_text(), re.MULTILINE))
    matches = []
    for pattern in patterns:
        if not isinstance(pattern, str) or pattern.startswith("!") or ".." in Path(pattern).parts:
            continue
        for folder in root.glob(pattern):
            manifest = folder / "package.json"
            if folder.resolve().is_relative_to(project.resolve()) and manifest.is_file():
                if json.loads(manifest.read_text()).get("name") == selector:
                    matches.append(folder.resolve())
    return matches[0] if len(set(matches)) == 1 else None


def named_build_target(project: Path, package_dir: Path,
                       test_file: Path | None) -> tuple[tuple[Path, str, bool] | None, list[dict]]:
    """Find the one package script named by the test, retaining unresolved calls."""
    project = project.resolve()
    package_dir = package_dir.resolve()
    package = package_dir / "package.json"
    sources = []
    unknown_test_command = False
    if package.is_file():
        scripts = json.loads(package.read_text()).get("scripts", {})
        sources.append(("package_test_script", scripts.get("test", "")))
    if test_file is not None:
        source = test_file.read_text(errors="ignore")
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        source = re.sub(r"(?m)//[^\n]*", "", source)
        literals = list(TEST_COMMAND_LITERAL.finditer(source))
        for match in literals:
            sources.append(("test_source", match.group(2)))
        unknown_test_command = any(
            not any(literal.start() == call.start() for literal in literals)
            for call in TEST_COMMAND_API.finditer(source))
    targets: dict[tuple[Path, str], bool] = {}
    dynamic: list[dict] = []
    for origin, source in sources:
        segments, conditional = _script_segments(source)
        if conditional:
            dynamic.append({"order": len(dynamic) + 1,
                            "package_json": container_path(package, project),
                            "script": None, "relation": "test_or_tool", "source": origin,
                            "dynamic": True, "reason": "conditional_test_script"})
            continue
        for tokens in segments:
            call = _script_invocation(tokens)
            if call is None:
                continue
            reason = call.get("reason") if call.get("dynamic") else None
            target = package_dir
            if not reason and call["directory"]:
                target = (target / call["directory"]).resolve()
                if not target.is_relative_to(project):
                    reason = "directory_outside_project"
            if not reason and call["workspace"]:
                target = _workspace_package(project, target, call["workspace"])
                if target is None:
                    reason = "workspace_unresolved"
            if reason:
                dynamic.append({"order": len(dynamic) + 1,
                                "package_json": container_path(package, project),
                                "script": call.get("script"), "relation": "test_or_tool",
                                "source": origin, "dynamic": True, "reason": reason})
                continue
            name = call["script"]
            if not (target / "package.json").is_file():
                dynamic.append({"order": len(dynamic) + 1,
                                "package_json": container_path(package, project),
                                "script": name, "relation": "test_or_tool", "source": origin,
                                "dynamic": True, "reason": "package_json_unresolved"})
                continue
            scripts = json.loads((target / "package.json").read_text()).get("scripts", {})
            if name not in scripts:
                if target == package_dir and origin == "package_test_script":
                    raise PolicyFailure("named package script is absent")
                dynamic.append({"order": len(dynamic) + 1,
                                "package_json": container_path(target / "package.json", project),
                                "script": name, "relation": "test_or_tool", "source": origin,
                                "dynamic": True, "reason": "script_unresolved"})
                continue
            key = (target, name)
            targets[key] = targets.get(key, False) or origin == "test_source"
    if unknown_test_command:
        dynamic.append({"order": len(dynamic) + 1,
                        "package_json": container_path(package, project),
                        "script": None, "relation": "test_or_tool", "source": "test_source",
                        "dynamic": True, "reason": "test_command_dynamic"})
    if len(targets) > 1:
        raise PolicyFailure("test names multiple package scripts")
    if not targets:
        return None, dynamic
    (directory, name), embedded = next(iter(targets.items()))
    return (directory, name, embedded), dynamic


def script_chain(project: Path, package_dir: Path, script: str) -> list[dict]:
    """Record the ordered, statically knowable package-script call chain."""
    project = project.resolve()
    package_dir = package_dir.resolve()
    chain: list[dict] = []
    active: list[tuple[Path, str]] = []

    def append(package: Path, name: str | None, relation: str,
               *, dynamic: bool = False, reason: str | None = None) -> None:
        row = {"order": len(chain) + 1, "package_json": container_path(package / "package.json", project),
               "script": name, "relation": relation}
        if dynamic:
            row.update({"dynamic": True, "reason": reason})
        chain.append(row)

    def expand(directory: Path, name: str, relation: str) -> None:
        package = (directory / "package.json").resolve()
        if not package.is_relative_to(project.resolve()) or not package.is_file():
            append(directory, name, relation, dynamic=True, reason="package_json_unresolved")
            return
        scripts = json.loads(package.read_text()).get("scripts", {})
        if name not in scripts or not isinstance(scripts[name], str):
            append(directory, name, relation, dynamic=True, reason="script_unresolved")
            return
        key = (package, name)
        if key in active:
            append(directory, name, relation, dynamic=True, reason="cycle")
            raise ScriptChainCycle(chain)
        if len(chain) >= 512:
            append(directory, name, relation, dynamic=True, reason="static_chain_limit")
            return
        active.append(key)
        if "pre" + name in scripts:
            expand(directory, "pre" + name, "lifecycle_pre")
        append(directory, name, relation)
        segments, conditional = _script_segments(scripts[name])
        if conditional:
            append(directory, None, "nested", dynamic=True, reason="conditional_shell_control")
            if "post" + name in scripts:
                append(directory, "post" + name, "lifecycle_post", dynamic=True,
                       reason="conditional_parent_outcome")
            active.pop()
            return
        running_directory = directory
        for tokens in segments:
            if tokens[:1] == ["cd"]:
                if len(tokens) != 2 or "$" in tokens[1] or "`" in tokens[1]:
                    append(directory, None, "nested", dynamic=True, reason="directory_dynamic")
                    continue
                next_directory = (running_directory / tokens[1]).resolve()
                if not next_directory.is_relative_to(project):
                    append(directory, None, "nested", dynamic=True, reason="directory_outside_project")
                    continue
                running_directory = next_directory
                continue
            call = _script_invocation(tokens)
            if call is None:
                if tokens and (tokens[0].startswith("./") or tokens[0] in {"sh", "bash", "node"}):
                    append(directory, None, "nested", dynamic=True, reason="external_command")
                continue
            if call.get("dynamic"):
                append(directory, None, "nested", dynamic=True, reason=call["reason"])
                continue
            target = running_directory
            if call["directory"]:
                target = (running_directory / call["directory"]).resolve()
                if not target.is_relative_to(project.resolve()):
                    append(directory, call["script"], "nested", dynamic=True, reason="directory_outside_project")
                    continue
            if call["workspace"]:
                selected = _workspace_package(project, target, call["workspace"])
                if selected is None:
                    append(directory, call["script"], "nested", dynamic=True, reason="workspace_unresolved")
                    continue
                target = selected
            expand(target, call["script"], "nested")
        if "post" + name in scripts:
            expand(directory, "post" + name, "lifecycle_post")
        active.pop()

    expand(package_dir, script, "entrypoint")
    return chain


def _scripts_observed_in_logs(row: dict, chain: list[dict], project: Path) -> list[dict]:
    """Use package-manager script announcements for a conservative failure trace."""
    log = row.get("stdout_log")
    if not log or not Path(log).is_file():
        return []
    observed = []
    with Path(log).open(errors="ignore") as stream:
        for item in chain:
            if item.get("dynamic"):
                continue
            relative = item["package_json"].removeprefix("/work/")
            manifest = project / relative
            if not manifest.is_file():
                break
            body = json.loads(manifest.read_text()).get("scripts", {}).get(item["script"])
            if not isinstance(body, str):
                break
            npm_name = re.compile(r"^>\s+\S+@\S+\s+" + re.escape(item["script"]) + r"(?:\s|$)")
            for line in stream:
                if line.strip() == "$ " + body or npm_name.match(line.strip()):
                    observed.append(item)
                    break
            else:
                break
    return observed


def record_script_execution(row: dict, chain: list[dict], *, direct: bool,
                            project: Path | None = None) -> None:
    """Separate pre-run static expansion from what exit status confirms ran."""
    row["script_chain_static"] = chain
    concrete = [item for item in chain if not item.get("dynamic")]
    conditional = any(item.get("reason") == "conditional_shell_control" for item in chain)
    observed = _scripts_observed_in_logs(row, chain, project) if project else []
    if row["exit_code"] == 0 and direct and not conditional:
        row["script_chain_executed"] = concrete
        row["script_chain_execution_evidence"] = (
            "successful_script_with_dynamic_subcalls" if len(concrete) != len(chain)
            else "successful_unconditional_script")
    elif observed:
        row["script_chain_executed"] = observed
        row["script_chain_execution_evidence"] = "package_manager_log_announcements"
    else:
        row["script_chain_executed"] = []
        row["script_chain_execution_evidence"] = "script_execution_unconfirmed"


def write_script_chain_plan(output: Path, ordinal: int, test_file: Path,
                            project: Path, selected_build: tuple[Path, str, bool] | None,
                            build_chain: list[dict], test_chain: list[dict],
                            dynamic_calls: list[dict], error: PolicyFailure | None = None) -> dict:
    """Persist the static plan before a test, build, or installation can run."""
    path = output / f"script-chain-plan-{ordinal}.json"
    target = None
    if selected_build:
        directory, script, embedded = selected_build
        target = {"package_json": container_path((directory / "package.json").resolve(),
                                                 project.resolve()),
                  "script": script, "embedded_in_test": embedded}
    dynamic_markers = [entry for entry in [*build_chain, *dynamic_calls] if entry.get("dynamic")]
    plan = {"schema": "n6-b5-script-chain-plan-v1", "ordinal": ordinal,
            "test_path": str(test_file), "build_target": target,
            "build_chain_static": build_chain, "test_chain_static": test_chain,
            "dynamic_calls_from_test_or_tool": dynamic_calls,
            "dynamic_markers": dynamic_markers,
            "dynamic_execution_status": "unconfirmed" if dynamic_markers else "no_dynamic_marker",
            "static_status": "cycle" if isinstance(error, ScriptChainCycle) else
                             "policy_failure" if error else "expanded",
            "static_failure_reason": str(error) if error else None,
            "execution_status": "not_observed_by_static_plan"}
    base.dump_json(path, plan)
    return {"script_chain_plan_path": str(path),
            "script_chain_plan_sha256": base.sha256(path)}


def container_path(path: Path, project: Path) -> str:
    return "/work/" + path.relative_to(project).as_posix()


def requires_circom(test_file: Path, package_dir: Path) -> bool:
    source = test_file.read_text(errors="ignore")
    package = package_dir / "package.json"
    if package.is_file():
        scripts = json.loads(package.read_text()).get("scripts", {})
        source += "\n" + scripts.get("test", "") + "\n" + scripts.get("build", "")
    return bool(re.search(r"\bcircom\b|circom[_-]?tester|circomTester", source, re.IGNORECASE))


def environment_error_in_logs(stdout: Path, stderr: Path, *, network: bool,
                              installation: bool) -> str | None:
    """Inspect both complete logs in bounded memory without disclosing their contents."""
    markers = (DOCKER_ERRORS + (NETWORK_ERRORS if network else ()) +
               (INSTALL_PERMISSION_ERRORS if installation else ()))
    longest = max(map(len, markers))
    for path in (stdout, stderr):
        tail = b""
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                window = (tail + chunk).lower()
                for marker in markers:
                    if marker in window:
                        return marker.decode("ascii")
                tail = window[-(longest - 1):]
    return None


def missing_container_tool_in_logs(stdout: Path, stderr: Path) -> str | None:
    """Recognize OS tool absence, without mistaking missing project packages for it."""
    tool_names = b"|".join(re.escape(name.encode()) for name in CONTAINER_TOOLS)
    patterns = (
        re.compile(rb"\b(?:spawn|syscall spawn)\s+(" + tool_names +
                   rb")\b.{0,1024}?\benoent\b", re.DOTALL),
        re.compile(rb"\benoent\b.{0,1024}?\b(?:spawn|syscall spawn)\s+(" +
                   tool_names + rb")\b", re.DOTALL),
        re.compile(rb"(?:^|[\r\n])[^\r\n]{0,160}?\b(" + tool_names +
                   rb"):\s*(?:command\s+)?not found\b"),
        re.compile(rb"(?:^|[\r\n])[^\r\n]{0,160}?\b(" + tool_names +
                   rb")[\x27\x22]?:\s*no such file or directory\b"),
        re.compile(rb"exec:\s*[\x27\x22](" + tool_names +
                   rb")[\x27\x22]:\s*executable file not found"),
        re.compile(rb"couldn[\x27\x22]?t find the binary\s+(" + tool_names + rb")\b"),
    )
    for path in (stdout, stderr):
        tail = b""
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                window = (tail + chunk).lower()
                for pattern in patterns:
                    if match := pattern.search(window):
                        return match.group(1).decode("ascii")
                tail = window[-2048:]
    return None


def remove_staged_dependencies(project: Path) -> list[str]:
    """Ensure a copied project cannot reuse pre-existing installed packages."""
    excluded = []
    for directory, dirs, files in os.walk(project, topdown=True, followlinks=False):
        current = Path(directory)
        for name in list(dirs):
            if name == "node_modules" or (current.name == ".yarn" and name in {"cache", "unplugged"}):
                target = current / name
                target.unlink() if target.is_symlink() else shutil.rmtree(target)
                dirs.remove(name)
                excluded.append(target.relative_to(project).as_posix())
        for name in files:
            if name.startswith(".pnp.") or (current.name == ".yarn" and
                                            name in {"install-state.gz", "build-state.yml"}):
                target = current / name
                target.unlink()
                excluded.append(target.relative_to(project).as_posix())
    return sorted(excluded)


class DockerRunner:
    def __init__(self, project: Path, output: Path, tools: dict, deadline: float):
        self.project, self.output, self.tools, self.deadline = project, output, tools, deadline
        self.log_dir = output / "docker-logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict] = []
        self.count = 0
        self.script_chain_plan_ref: dict = {}

    def check(self) -> None:
        try:
            result = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                    capture_output=True, text=True)
        except OSError as error:
            raise EnvironmentBlocked("Docker Desktop을 켜고 같은 명령을 다시 실행") from error
        if result.returncode:
            raise EnvironmentBlocked("Docker Desktop을 켜고 같은 명령을 다시 실행: " + result.stderr.strip()[:300])

    def run(self, label: str, command: list[str], cwd: Path, *, network: bool,
            capture: bool = False, capture_writes: bool = False,
            env: dict[str, str] | None = None) -> dict:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise PolicyFailure("revision_60min_exceeded")
        self.count += 1
        name = f"{self.count:02d}-{label}"
        stdout = self.log_dir / f"{name}.stdout.log"
        stderr = self.log_dir / f"{name}.stderr.log"
        cidfile = self.log_dir / f"{name}.cid"
        invocation = ["docker", "run", "--rm", "--platform", self.tools["platform"],
                      "--cidfile", str(cidfile),
                      "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                      "--network", "bridge" if network else "none",
                      "--mount", f"type=bind,src={self.project},dst=/work",
                      "--workdir", container_path(cwd, self.project)]
        if capture:
            invocation.extend(["--env", "NODE_OPTIONS=--require=/work/.n6_b5_capture.cjs",
                               "--env", "N6_J1_CAPTURE_PATH=/work/.n6_b5_capture.jsonl",
                               "--env", f"N6_J1_CAPTURE_WRITES={1 if capture_writes else 0}"])
        for key, value in sorted((env or {}).items()):
            if key not in {"YARN_ENABLE_SCRIPTS", "PATH", "GIT_CONFIG_COUNT"} and not re.fullmatch(
                    r"GIT_CONFIG_(?:KEY|VALUE)_[01]", key):
                raise ValueError("container environment key not allowlisted")
            invocation.extend(["--env", f"{key}={value}"])
        invocation.extend([self.tools["image"], *command])
        started = time.monotonic()
        with stdout.open("wb") as out, stderr.open("wb") as err:
            try:
                result = subprocess.run(invocation, stdout=out, stderr=err,
                                        timeout=max(1, remaining))
                code, disposition = result.returncode, "completed"
            except OSError as error:
                raise EnvironmentBlocked(f"Docker container could not start; logs: {stdout}, {stderr}") from error
            except subprocess.TimeoutExpired:
                code, disposition = None, "timeout"
                if cidfile.is_file():
                    subprocess.run(["docker", "rm", "-f", cidfile.read_text().strip()],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        cidfile.unlink(missing_ok=True)
        seconds = time.monotonic() - started
        row = {"kind": label, "command": command, "cwd": container_path(cwd, self.project),
               "network": network, "exit_code": code, "disposition": disposition,
               "seconds": seconds, "stdout_log": str(stdout), "stdout_sha256": base.sha256(stdout),
               "stderr_log": str(stderr), "stderr_sha256": base.sha256(stderr)}
        row.update(self.script_chain_plan_ref)
        marker = environment_error_in_logs(
            stdout, stderr, network=network, installation=label.startswith("install-")) if code else None
        missing_tool = missing_container_tool_in_logs(stdout, stderr) if code else None
        if missing_tool:
            row["tool_error"] = f"missing_container_executable:{missing_tool}"
        if code == 125 or marker:
            row["environment_error"] = marker or "docker_run_exit_125"
        self.steps.append(row)
        if "tool_error" in row:
            raise ToolBlocked(f"{row['tool_error']}; logs: {stdout}, {stderr}")
        if "environment_error" in row:
            raise EnvironmentBlocked(
                f"container/network environment blocked ({row['environment_error']}); "
                f"logs: {stdout}, {stderr}")
        return row


def docker_project_selection(row: dict, output: Path, validate, tools: dict,
                             revision_deadline: float) -> tuple[tuple[Path, dict] | None, list[dict], list[dict]]:
    source = base.workspace_path(row["project_root"])
    entrypoint = base.workspace_path(row["entrypoint_absolute"])
    files = base.matching_project_files(source, entrypoint)
    if not files:
        return None, [{"stage": "d_project_test", "reason": "matching_test_or_tool_missing"}], []
    try:
        verify_no_tracked_install_artifacts(row)
    except PolicyFailure as error:
        return None, [{"stage": "d_project_test", "reason": str(error)}], []
    staging = output / "project-test-docker-copy"
    if staging.exists():
        raise PolicyFailure("project copy already exists; refuse to overwrite")
    staging.mkdir(parents=True)
    copied = subprocess.run(["rsync", "-a", "--exclude", ".git/",
                             "--exclude", "node_modules/", "--exclude", ".yarn/cache/",
                             "--exclude", ".yarn/unplugged/", "--exclude", ".pnp.*",
                             "--exclude", ".yarn/install-state.gz",
                             "--exclude", ".yarn/build-state.yml",
                             str(source) + "/", str(staging) + "/"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=max(1, revision_deadline - time.monotonic()))
    if copied.returncode:
        return None, [{"stage": "d_project_test", "reason": "project_stage_copy_failed",
                       "exit_code": copied.returncode}], []
    git_metadata = staging / ".git"
    if git_metadata.is_dir():
        shutil.rmtree(git_metadata)
    elif git_metadata.exists():
        git_metadata.unlink()
    excluded = remove_staged_dependencies(staging)
    base.dump_json(output / "staged-dependency-exclusions.json",
                   {"copy_exclude_patterns": ["node_modules/", ".yarn/cache/",
                                              ".yarn/unplugged/", ".pnp.*",
                                              ".yarn/install-state.gz", ".yarn/build-state.yml"],
                    "removed_after_copy": excluded, "removed_count": len(excluded)})
    shutil.copyfile(base.CAPTURE, staging / ".n6_b5_capture.cjs")
    linux_circom = tools.get("circom_linux")
    if linux_circom:
        binary = Path(linux_circom)
        if not binary.is_file() or base.sha256(binary) != tools.get("circom_linux_sha256"):
            raise ToolBlocked("pinned_linux_circom_unavailable_or_hash_mismatch")
        bin_dir = staging / ".n6_b5_bin"
        bin_dir.mkdir()
        shutil.copyfile(binary, bin_dir / "circom")
        (bin_dir / "circom").chmod(0o755)
    runner = DockerRunner(staging, output, tools, revision_deadline)
    runner.check()
    try:
        version_check = runner.run("tool-versions", ["sh", "-lc",
            "node --version && npm --version && corepack --version"], staging, network=False)
        if version_check["exit_code"] != 0:
            raise ToolBlocked("pinned_node_image_tool_version_check_failed")
        versions = Path(version_check["stdout_log"]).read_text().splitlines()
        if versions[:3] != ["v" + tools["node"], tools["npm"], tools["corepack"]]:
            raise ToolBlocked("pinned_node_image_tool_versions_changed")
        if linux_circom:
            circom_check = runner.run("circom-version", ["/work/.n6_b5_bin/circom", "--version"],
                                      staging, network=False)
            version_text = Path(circom_check["stdout_log"]).read_text(errors="ignore") + \
                Path(circom_check["stderr_log"]).read_text(errors="ignore")
            if circom_check["exit_code"] != 0 or tools["circom_version_required"] not in version_text:
                raise ToolBlocked("pinned_linux_circom_version_changed")
    except ToolBlocked as error:
        error.project_test_execution = list(runner.steps)
        raise
    failures = []
    install_cache: dict[tuple[str, str, str], dict] = {}
    staged_entrypoint = staging / entrypoint.relative_to(source)
    active_plan_ref: dict = {}
    try:
        for ordinal, original_test in enumerate(files, 1):
            active_plan_ref = {}
            runner.script_chain_plan_ref = {}
            test_file = staging / original_test.relative_to(source)
            same_main_setup, same_main_error = base.project_test_setup(
                staging, test_file, staged_entrypoint, {}, output, revision_deadline,
                {}, perform_build=False)
            runner.steps.extend(same_main_setup)
            if same_main_error is not None:
                failures.append({**same_main_error, "test_path": str(original_test)})
                continue
            command, package_dir = base.test_command(staging, test_file,
                                                       entrypoint.relative_to(source).as_posix())
            selected_build = None
            dynamic_calls: list[dict] = []
            build_chain: list[dict] = []
            test_chain: list[dict] = []
            try:
                selected_build, dynamic_calls = named_build_target(staging, package_dir, test_file)
                build_dir, named_build, embedded_build = (selected_build if selected_build else
                                                          (package_dir, None, False))
                build_chain = script_chain(staging, build_dir, named_build) if named_build else []
                test_chain = [*build_chain, *dynamic_calls] if embedded_build else dynamic_calls
                test_chain = [{**entry, "order": index} for index, entry in enumerate(test_chain, 1)]
            except PolicyFailure as error:
                if isinstance(error, ScriptChainCycle):
                    build_chain = error.chain
                    if selected_build and selected_build[2]:
                        test_chain = error.chain
                active_plan_ref = write_script_chain_plan(
                    output, ordinal, original_test, staging, selected_build,
                    build_chain, test_chain, dynamic_calls, error)
                runner.script_chain_plan_ref = active_plan_ref
                runner.steps.append({"kind": "script-chain-plan", "ordinal": ordinal,
                                     **active_plan_ref})
                failure = {"stage": "d_project_test", "reason": str(error),
                           "test_path": str(original_test), **active_plan_ref}
                if isinstance(error, ScriptChainCycle):
                    failure["script_chain_static"] = error.chain
                failures.append(failure)
                continue
            active_plan_ref = write_script_chain_plan(
                output, ordinal, original_test, staging, selected_build,
                build_chain, test_chain, dynamic_calls)
            runner.script_chain_plan_ref = active_plan_ref
            runner.steps.append({"kind": "script-chain-plan", "ordinal": ordinal,
                                 **active_plan_ref})
            if requires_circom(test_file, package_dir) and not linux_circom:
                raise ToolBlocked("pinned_linux_circom_unavailable")
            if command:
                command = [container_path(Path(arg), staging) if arg.startswith(str(staging)) else arg
                           for arg in command]
            capture_path = staging / ".n6_b5_capture.jsonl"
            if capture_path.exists():
                capture_path.unlink()
            first = None
            if command:
                first = runner.run(f"test-{ordinal}-before-install", command, package_dir,
                                   network=False, capture=True, capture_writes=test_file.name == "cli.ts",
                                   env={"PATH": "/work/.n6_b5_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"} if linux_circom else None)
                if embedded_build:
                    first["build_named_by_test_source"] = named_build
                if test_chain:
                    record_script_execution(first, test_chain, direct=False, project=staging)
                if first["exit_code"] == 0:
                    picked = read_capture(capture_path, output, ordinal, original_test, source,
                                          entrypoint, validate, revision_deadline)
                    if picked:
                        return picked, failures, runner.steps
            trigger = command is None or (first and base.project_error_kind(
                (Path(first["stdout_log"]).read_bytes() + Path(first["stderr_log"]).read_bytes())[:1 << 20])
                in {"module_missing", "project_package_manager_unavailable", "typescript_build"})
            if not trigger:
                failures.append({"stage": "d_project_test", "reason": "original_test_failed_without_install_trigger",
                                 "test_path": str(original_test), "exit_code": first["exit_code"] if first else None,
                                 **active_plan_ref})
                continue
            try:
                install, lock, version = choose_install(package_dir, staging, tools)
                lock_before = base.sha256(lock)
                committed_lock = verify_committed_lock(row, lock, staging)
                lock_relative = lock.relative_to(staging).as_posix()
                folder_relative = lock.parent.relative_to(staging).as_posix()
                cache_key = (lock_relative, folder_relative, lock_before)
                prior = install_cache.get(cache_key)
                if prior is None:
                    git_env, git_config = github_ssh_git_config(lock)
                    install_env = ({"YARN_ENABLE_SCRIPTS": "0"} if "--immutable" in install else {})
                    install_env.update(git_env)
                    try:
                        install_row = runner.run(f"install-{ordinal}", install, lock.parent, network=True,
                                                 env=install_env)
                    except (ToolBlocked, EnvironmentBlocked):
                        if runner.steps and runner.steps[-1].get("kind") == f"install-{ordinal}":
                            runner.steps[-1].update({"package_manager": version,
                                                     "lock_path": lock_relative,
                                                     "install_folder": folder_relative,
                                                     "lock_sha256": lock_before,
                                                     "committed_lock_sha256": committed_lock,
                                                     "git_url_rewrite": git_config,
                                                     "actual_execution": True})
                        raise
                    install_row.update({"package_manager": version, "lock_path": lock_relative,
                                        "install_folder": folder_relative,
                                        "lock_sha256": lock_before,
                                        "committed_lock_sha256": committed_lock,
                                        "git_url_rewrite": git_config,
                                        "actual_execution": True})
                    install_cache[cache_key] = install_row
                else:
                    install_row = {"kind": f"install-{ordinal}-reuse", "command": install,
                                   "cwd": container_path(lock.parent, staging), "network": False,
                                   "exit_code": prior["exit_code"], "disposition": "reused_prior_result",
                                   "seconds": 0.0, "lock_path": lock_relative,
                                   "install_folder": folder_relative, "lock_sha256": lock_before,
                                   "committed_lock_sha256": committed_lock,
                                   "package_manager": version, "git_url_rewrite": prior["git_url_rewrite"],
                                   "actual_execution": False, "reused_from": prior["kind"],
                                   **active_plan_ref}
                    runner.steps.append(install_row)
                if base.sha256(lock) != lock_before:
                    raise PolicyFailure("committed lock changed during install")
                if install_row["exit_code"] != 0:
                    raise PolicyFailure("lock_install_failed_no_retry" if prior else "lock_install_failed")
                if prior is None:
                    install_row["installed_packages"] = installed_packages_record(lock.parent)
                else:
                    if "installed_packages" not in prior:
                        raise PolicyFailure("installed_package_inventory_missing_no_retry")
                    install_row["initial_installed_packages"] = prior["installed_packages"]
                    install_row["installed_packages"] = installed_packages_record(lock.parent)
                if named_build and not embedded_build:
                    manager = version.split("@", 1)[0]
                    run_build = (["npm", "run", named_build] if manager == "npm" else
                                 ["corepack", version, "run", named_build])
                    build_row = runner.run(f"build-{ordinal}", run_build, build_dir,
                                           network=True,
                                           env={"PATH": "/work/.n6_b5_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"} if linux_circom else None)
                    build_row["script"] = named_build
                    record_script_execution(build_row, build_chain, direct=True, project=staging)
                    if build_row["exit_code"] != 0:
                        raise PolicyFailure("named_build_failed")
                command, package_dir = base.test_command(staging, test_file,
                                                          entrypoint.relative_to(source).as_posix())
                if command is None:
                    raise PolicyFailure("test_runner_unavailable_after_install")
                command = [container_path(Path(arg), staging) if arg.startswith(str(staging)) else arg
                           for arg in command]
                if capture_path.exists():
                    capture_path.unlink()
                retest = runner.run(f"test-{ordinal}-after-install", command, package_dir,
                                    network=False, capture=True, capture_writes=test_file.name == "cli.ts",
                                    env={"PATH": "/work/.n6_b5_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"} if linux_circom else None)
                if embedded_build:
                    retest["build_named_by_test_source"] = named_build
                if test_chain:
                    record_script_execution(retest, test_chain, direct=False, project=staging)
                if retest["exit_code"] == 0:
                    picked = read_capture(capture_path, output, ordinal, original_test, source,
                                          entrypoint, validate, revision_deadline)
                    if picked:
                        return picked, failures, runner.steps
                raise PolicyFailure("same_test_failed_after_install")
            except PolicyFailure as error:
                failures.append({"stage": "d_project_test", "reason": str(error),
                                 "test_path": str(original_test), **active_plan_ref})
        return None, failures, runner.steps
    except Exception as error:
        error.script_chain_plan_ref = active_plan_ref
        error.project_test_execution = list(runner.steps)
        raise
    finally:
        # Keep logs and captured inputs under output, but remove the installed copy.
        shutil.rmtree(staging, ignore_errors=True)


def read_capture(capture_path: Path, output: Path, ordinal: int, test_file: Path,
                 source: Path, entrypoint: Path, validate, deadline: float) -> tuple[Path, dict] | None:
    if not capture_path.is_file():
        return None
    same_names = base.equivalent_main_names(source, entrypoint)
    stems = {Path(name).stem for name in same_names}
    archive = output / "project-test-captures"
    archive.mkdir(exist_ok=True)
    saved = archive / f"{ordinal:04d}.jsonl"
    shutil.copyfile(capture_path, saved)
    for number, line in enumerate(saved.read_text().splitlines(), 1):
        try:
            capture = json.loads(line)
            candidate = capture["input"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        if not isinstance(candidate, dict):
            continue
        kind, source_name = capture.get("kind"), str(capture.get("source", ""))
        if kind == "calculateWitness" and Path(source_name).name not in same_names:
            continue
        if kind == "wtns.calculate" and not any(stem in Path(source_name).name for stem in stems):
            continue
        if kind not in {"calculateWitness", "wtns.calculate", "input-tool-output"}:
            continue
        candidate_path = output / "project-test-inputs" / f"{ordinal:04d}-{number:04d}.json"
        base.dump_json(candidate_path, candidate)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PolicyFailure("revision_60min_exceeded")
        passed, _, details = validate(candidate_path, remaining)
        if passed:
            return candidate_path, details
    return None


def collect_one(row: dict, output: Path, checker: Path, snarkjs: Path, l_inputs: dict,
                tools: dict, expected_r1cs: str, compile_timeout: float,
                validation_timeout: float) -> dict:
    deadline = time.monotonic() + 3600
    original_compile = base.compile_entrypoint
    original_project = base.project_test_selection
    docker_details = {"attempted": False, "installation_used": False}

    def guarded_compile(item, folder, timeout):
        artifacts, metadata = original_compile(item, folder, min(timeout, deadline - time.monotonic()))
        if metadata["r1cs_sha256"] != expected_r1cs:
            raise PolicyFailure("b_fuzz_r1cs_hash_mismatch")
        return artifacts, metadata

    def docker_selection(item, folder, _unused_deadline, validate, _artifacts):
        docker_details["attempted"] = True
        picked, failures, execution = docker_project_selection(item, folder, validate, tools, deadline)
        docker_details["installation_used"] = any(step["kind"].startswith("install-") for step in execution)
        return picked, failures, execution

    try:
        with patch.object(base, "compile_entrypoint", guarded_compile), \
                patch.object(base, "project_test_selection", docker_selection):
            result = base.select_one(row, output, checker, snarkjs, l_inputs,
                                     compile_timeout, validation_timeout)
    except (PolicyFailure, ToolBlocked, EnvironmentBlocked):
        raise
    result["b_fuzz_r1cs_sha256"] = expected_r1cs
    result["b_fuzz_r1cs_match"] = True
    result["docker_image"] = tools["image"]
    result["docker_tools"] = {key: tools[key] for key in
                              ("node", "npm", "corepack", "yarn_classic", "yarn_modern", "pnpm")}
    if result["selected_stage"] == "d_project_test" and not docker_details["installation_used"]:
        result["original_rule_stage"] = "d_project_test"
    result["without_install_stage"] = result["original_rule_stage"]
    result["with_amendment_stage"] = result["selected_stage"] or "base_input_unavailable"
    result["installation_used"] = docker_details["installation_used"]
    base.dump_json(output / row["identifier"] / "selection.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("A", "B"), required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--r1cs-map", type=Path)
    parser.add_argument("--tools", type=Path, default=DEFAULT_TOOLS)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--identifier")
    parser.add_argument("--compile-timeout-seconds", type=float, default=1800)
    parser.add_argument("--validation-timeout-seconds", type=float, default=600)
    args = parser.parse_args()
    args.manifest = args.manifest or (DEFAULT_B_MANIFEST if args.scope == "B" else DEFAULT_A_MANIFEST)
    args.r1cs_map = args.r1cs_map or (DEFAULT_B_R1CS if args.scope == "B" else DEFAULT_A_R1CS)
    if args.scope == "B" and not mem20_finished():
        raise SystemExit("B mem20 main/retry completion evidence missing")
    tools = load_tools(args.tools)
    manifest = json.loads(args.manifest.read_text())
    rows = manifest["rows"]
    if args.scope == "B" and (len(rows) != 10 or len({r["identifier"] for r in rows}) != 10):
        raise SystemExit("B manifest must contain ten distinct revisions")
    reference = reference_hashes(args.r1cs_map, args.scope)
    if args.identifier and args.identifier not in {r["identifier"] for r in rows}:
        raise SystemExit("identifier absent from manifest")
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
        if index["manifest_sha256"] != base.sha256(args.manifest) or index["r1cs_map_sha256"] != base.sha256(args.r1cs_map):
            raise SystemExit("base-input index input hash changed")
    else:
        index = {"schema": "n6-j1-base-inputs-v1", "amendment_schema": "n6-b5-docker-base-inputs-v1",
                 "scope": args.scope,
                 "manifest_path": str(args.manifest.resolve()), "manifest_sha256": base.sha256(args.manifest),
                 "revision_manifest_path": str(args.manifest.resolve()),
                 "revision_manifest_sha256": base.sha256(args.manifest),
                 "circom_sha256": base.CIRCOM_SHA256,
                 "r1cs_map_path": str(args.r1cs_map.resolve()), "r1cs_map_sha256": base.sha256(args.r1cs_map),
                 "tools_path": str(args.tools.resolve()), "tools_sha256": base.sha256(args.tools),
                 "revisions": {}}
    checker = base.checker_binary(output)
    snarkjs_name = shutil.which("snarkjs")
    if snarkjs_name is None or base.sha256(base.CIRCOM) != base.CIRCOM_SHA256:
        raise SystemExit("fixed Mac witness tools unavailable or changed")
    snarkjs = Path(snarkjs_name).resolve()
    index["rust_checker_path"] = str(checker)
    index["rust_checker_sha256"] = base.sha256(checker)
    index["snarkjs_path"] = str(snarkjs)
    index["snarkjs_sha256"] = base.sha256(snarkjs)
    base.dump_json(index_path, index)
    selected_rows = [row for row in rows if not args.identifier or row["identifier"] == args.identifier]
    # The current A installation trial and all B revisions have no L-series
    # project family, so avoid recursively searching ignored run trees.
    l_inputs = (base.l_series_inputs() if any(base.project_family(
        base.workspace_path(row["project_root"])) for row in selected_rows) else {})
    for row in rows:
        identifier = row["identifier"]
        if args.identifier and identifier != args.identifier or identifier in index["revisions"]:
            continue
        expected = reference.get(identifier, {})
        digest = expected.get("r1cs_sha256")
        if expected.get("status") != "verified" or not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise SystemExit(f"authoritative fuzz R1CS hash unavailable: {identifier}")
        try:
            result = collect_one(row, output, checker, snarkjs, l_inputs, tools, digest,
                                 args.compile_timeout_seconds, args.validation_timeout_seconds)
        except ToolBlocked as error:
            shutil.rmtree(output / identifier / "project-test-docker-copy", ignore_errors=True)
            plan_ref = getattr(error, "script_chain_plan_ref", {})
            base.dump_json(output / identifier / "tool-blocked.json",
                           {"identifier": identifier, "status": "tool_blocked", "reason": str(error),
                            "project_test_execution": getattr(error, "project_test_execution", []),
                            "failed_attempts": [{"stage": "tool_blocked", "reason": str(error),
                                                 **plan_ref}]})
            raise SystemExit(str(error)) from error
        except EnvironmentBlocked as error:
            shutil.rmtree(output / identifier / "project-test-docker-copy", ignore_errors=True)
            plan_ref = getattr(error, "script_chain_plan_ref", {})
            base.dump_json(output / identifier / "environment-blocked.json",
                           {"identifier": identifier, "status": "environment_blocked", "reason": str(error),
                            "project_test_execution": getattr(error, "project_test_execution", []),
                            "failed_attempts": [{"stage": "environment_blocked", "reason": str(error),
                                                 **plan_ref}]})
            raise SystemExit(str(error)) from error
        except (PolicyFailure, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            shutil.rmtree(output / identifier / "project-test-docker-copy", ignore_errors=True)
            plan_ref = getattr(error, "script_chain_plan_ref", {})
            result = {"identifier": identifier, "status": "base_input_unavailable", "selected_stage": None,
                      "original_rule_stage": "base_input_unavailable", "without_install_stage": "base_input_unavailable",
                      "with_amendment_stage": "base_input_unavailable", "base_input_path": None,
                      "base_input_sha256": None, "failed_attempts": [{"stage": "d_project_test",
                                                                      "reason": str(error), **plan_ref}],
                      "project_test_execution": getattr(error, "project_test_execution", [])}
            base.dump_json(output / identifier / "selection.json", result)
        index["revisions"][identifier] = result
        base.dump_json(index_path, index)
        print(identifier, result["status"], result.get("with_amendment_stage"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
