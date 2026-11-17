#!/usr/bin/env python3
"""Run generic split discovery, S fuzzing, J v2.8, and pair validation."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import Any, Callable
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPTS))

from measure_f01_discovery import manifest_for  # noqa: E402
import run_policy_a_engine as policy_v1  # noqa: E402
import run_policy_a_engine_v5_1 as policy_v51  # noqa: E402
import zkfdo_tools_v1 as tool_manifest  # noqa: E402


SCHEMA = "zkfdo-sj-pipeline-v1"
STAGES = ("preflight", "baseline", "preparation", "s_campaign", "j_requests", "postcheck", "summary")
DEFAULT_SEED = 2026100601
DEFAULT_S_SECONDS = 3600.0
DEFAULT_ATTEMPT_SECONDS = 30.0
DEFAULT_J_REQUEST_SECONDS = 2 * 60 * 60.0
DEFAULT_J_TOTAL_SECONDS = 6 * 60 * 60.0
DEFAULT_PROBE_SECONDS = 900
DEFAULT_FREE_GIB = 65.0
DEFAULT_MAX_DISK_GIB = 512.0
GIB = 2**30
CANDIDATE_GLOB = "**/zkfdo_report_counterexample.json"
SNARKJS_MARKERS = ("WITNESS CHECKING FINISHED SUCCESSFULLY", "WITNESS IS CORRECT")
J_NAMES = ("J_v28", "j_v28", "J")
REQUIRED_TOOLS = ("prepare", "circom", "zkfuzz", "node", "snarkjs", "z3", "rust_checker")
REUSED_MODULE_ROOTS = (
    ROOT / "scripts/measure_f01_discovery.py",
    ROOT / "scripts/run_policy_a_engine.py",
    ROOT / "scripts/run_policy_a_engine_v5_1.py",
    ROOT / "scripts/zkfdo_tools_v1.py",
)
INCLUDE = re.compile(r"\binclude\s+\"([^\"\r\n]+)\"\s*;")
SHA_RE = re.compile(r"\A[0-9a-f]{64}\Z")
PROBE_VALUE_POLICY = "p1-single-hint-minus-plus-zero-original-v1"
PROBE_CONTRACT = "original_baseline_comparator-no-repair-no-solver-v1"
PROBE_PREDICATE = "component_output_violation_and_top_output_difference"
PROCESS_TERM_GRACE_SECONDS = 2.0
PROCESS_KILL_GRACE_SECONDS = 5.0
PROCESS_POLL_SECONDS = 0.05
DISK_MONITOR_SECONDS = 1.0
S_PROCESS_CLEANUP_CAP_SECONDS = 5.0


class PipelineError(RuntimeError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


class SupervisorSignal(BaseException):
    status = "supervisor_signal"

    def __init__(self, signum: int):
        super().__init__(f"supervisor received signal {signum}")
        self.signum = signum


@contextmanager
def supervisor_signal_scope():
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous: dict[int, Any] = {}

    def handle(signum: int, _frame: object) -> None:
        raise SupervisorSignal(signum)

    try:
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, handle)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def positive(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


def sha256(path: str | Path) -> str:
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError(f"file changed while hashing: {path}")
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def value_sha(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def local_module_closure(roots: tuple[Path, ...]) -> list[Path]:
    pending = [path.resolve() for path in roots]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        if not path.is_file() or path.is_symlink() or not path.is_relative_to(SCRIPTS):
            raise ValueError(f"local module root differs: {path}")
        visited.add(path)
        tree = ast.parse(path.read_text(), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".", 1)[0])
        for name in names:
            module = SCRIPTS / f"{name}.py"
            package = SCRIPTS / name / "__init__.py"
            for candidate in (module, package):
                if candidate.is_file() and candidate.resolve() not in visited:
                    pending.append(candidate.resolve())
    return sorted(visited, key=lambda item: item.relative_to(ROOT).as_posix())


def atomic_bytes(path: str | Path, value: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=path.name + ".tmp-", dir=path.parent)
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_json(path: str | Path, value: Any) -> None:
    atomic_bytes(path, json_bytes(value))


def atomic_text(path: str | Path, value: str) -> None:
    atomic_bytes(path, value.encode())


def exclusive_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(json_bytes(value))
        output.flush()
        os.fsync(output.fileno())


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def reject_symlink_ancestry(path: Path, label: str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(path)))
    cursor = lexical
    while True:
        if cursor.is_symlink():
            raise PipelineError("output_ownership_failed", f"{label} has a symlink ancestor: {cursor}")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    return lexical


def path_root_label(path: Path, roots: list[tuple[str, Path]]) -> str | None:
    matches = [(len(root.parts), label) for label, root in roots if path.is_relative_to(root)]
    return max(matches, default=(0, None))[1]


def source_closure_layout(entrypoint: Path, libraries: list[Path], pinned_root: Path) -> dict[str, Any]:
    pinned_root = pinned_root.resolve()
    roots = [("source", pinned_root)]
    roots.extend((f"library-{index:02d}", path.resolve())
                 for index, path in enumerate(libraries))
    pending = [entrypoint]
    visited: set[Path] = set()
    files: list[dict[str, Any]] = []
    includes: list[dict[str, Any]] = []
    while pending:
        raw = pending.pop()
        if raw.is_symlink():
            raise PipelineError("unsupported:include_layout", f"source is a symlink: {raw}")
        path = raw.resolve()
        if not path.is_file() or not path.is_relative_to(pinned_root):
            raise PipelineError("unsupported:include_layout",
                                f"source lies outside the pinned copy: {path}")
        if path in visited:
            continue
        visited.add(path)
        relative = path.relative_to(pinned_root).as_posix()
        files.append({"path": str(path), "relative": relative, "sha256": sha256(path),
                      "target_root": path_root_label(path, roots)})
        source = strip_comments(path.read_text())
        matches = list(INCLUDE.finditer(source))
        for match in reversed(matches):
            literal = match.group(1)
            absolute = Path(literal).is_absolute()
            candidates = ([Path(literal)] if absolute else
                          [path.parent / literal, *(root / literal for root in libraries)])
            target = next((candidate for candidate in candidates if candidate.is_file()), None)
            if target is None or target.is_symlink():
                raise PipelineError("unsupported:include_layout",
                                    f"include is missing or a symlink: {literal} from {path}")
            resolved = target.resolve()
            if not resolved.is_relative_to(pinned_root):
                raise PipelineError("unsupported:include_layout",
                                    f"include target lies outside the pinned copy: {resolved}")
            includes.append({
                "source": str(path), "literal": literal,
                "layout": "absolute" if absolute else "relative",
                "resolved": str(resolved),
                "target_root": path_root_label(resolved, roots),
            })
            if resolved not in visited:
                pending.append(resolved)
    files.sort(key=lambda row: row["relative"])
    includes.sort(key=lambda row: (row["source"], row["literal"], row["resolved"]))
    identity = [{key: row[key] for key in ("relative", "sha256")} for row in files]
    return {"entrypoint": str(entrypoint.resolve()), "files": files, "includes": includes,
            "closure_sha256": value_sha(identity),
            "absolute_include_count": sum(row["layout"] == "absolute" for row in includes),
            "relative_include_count": sum(row["layout"] == "relative" for row in includes)}


class OutputLock:
    def __init__(self, output: Path):
        self.output = reject_symlink_ancestry(output, "output")
        self.path = self.output / ".sj-pipeline.lock"
        self.owner_id = uuid.uuid4().hex
        self.descriptor: int | None = None
        self.owner: dict[str, Any] | None = None

    def acquire(self) -> "OutputLock":
        if self.output.exists():
            if not self.output.is_dir() or self.output.is_symlink():
                raise PipelineError("output_ownership_failed", "output is not a real directory")
        else:
            self.output.mkdir(parents=True, exist_ok=False)
        if self.path.is_symlink():
            raise PipelineError("output_ownership_failed", "output lock path is a symlink")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as error:
            if self.path.is_symlink():
                raise PipelineError(
                    "output_ownership_failed", "output lock path is a symlink") from error
            raise
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise PipelineError("output_ownership_failed", "output lock path is not a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.lseek(descriptor, 0, os.SEEK_SET)
            raw = os.read(descriptor, 1024 * 1024).decode(errors="replace")
            os.close(descriptor)
            try:
                owner = json.loads(raw)
            except json.JSONDecodeError:
                owner = {"record": raw}
            raise PipelineError("output_locked", f"output has an active owner: {owner}") from error
        self.descriptor = descriptor
        os.lseek(descriptor, 0, os.SEEK_SET)
        previous_raw = os.read(descriptor, 1024 * 1024)
        if previous_raw:
            try:
                previous = json.loads(previous_raw)
            except (UnicodeError, json.JSONDecodeError):
                previous = {"status": "unreadable", "raw_sha256": hashlib.sha256(previous_raw).hexdigest()}
            history = self.output / ".sj-pipeline-lock-history"
            if history.exists() and (history.is_symlink() or not history.is_dir()):
                raise PipelineError("output_ownership_failed", "lock history path differs")
            history.mkdir(exist_ok=True)
            prior_id = str(previous.get("owner_id") or hashlib.sha256(previous_raw).hexdigest())
            prior_path = history / f"{prior_id}.json"
            if prior_path.exists():
                if prior_path.is_symlink() or read_json(prior_path) != previous:
                    raise PipelineError("output_ownership_failed", "prior lock history differs")
            else:
                atomic_json(prior_path, previous)
        self.owner = {
            "schema": "zkfdo-sj-output-lock-v1", "owner_id": self.owner_id,
            "status": "active", "pid": os.getpid(), "host": socket.gethostname(),
            "started_utc": utc(), "output": str(self.output),
        }
        raw = json_bytes(self.owner)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, raw)
        os.fsync(descriptor)
        return self

    def release(self) -> None:
        if self.descriptor is None:
            return
        descriptor = self.descriptor
        record = {**(self.owner or {}), "status": "released", "released_utc": utc()}
        history = self.output / ".sj-pipeline-lock-history"
        history.mkdir(exist_ok=True)
        receipt = history / f"{self.owner_id}.json"
        if receipt.exists():
            if receipt.is_symlink() or read_json(receipt) != record:
                raise PipelineError("output_ownership_failed", "lock release history differs")
        else:
            atomic_json(receipt, record)
        raw = json_bytes(record)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, raw)
        os.fsync(descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        self.descriptor = None

    def __enter__(self) -> "OutputLock":
        return self.acquire()

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.release()


def existing_ancestor(path: Path) -> Path:
    path = path.absolute()
    while not path.exists():
        if path.parent == path:
            raise ValueError("no existing output ancestor")
        path = path.parent
    return path


def disk_gate(path: Path, minimum_bytes: int, usage: Callable[[Path], Any] = shutil.disk_usage) -> dict[str, int]:
    if isinstance(minimum_bytes, bool) or not isinstance(minimum_bytes, int) or minimum_bytes <= 0:
        raise ValueError("minimum disk bytes must be positive")
    target = existing_ancestor(path)
    total, used, free = usage(target)
    receipt = {"path": str(target.resolve()), "total_bytes": total, "used_bytes": used,
               "free_bytes": free, "minimum_free_bytes": minimum_bytes}
    if free < minimum_bytes:
        raise PipelineError("insufficient_disk", f"free disk is below {minimum_bytes} bytes")
    return receipt


def strip_comments(source: str) -> str:
    output: list[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(source):
        char = source[index]
        pair = source[index:index + 2]
        if state == "code":
            if pair == "//":
                output.extend("  ")
                state = "line"
                index += 2
                continue
            if pair == "/*":
                output.extend("  ")
                state = "block"
                index += 2
                continue
            if char in ("\"", "'"):
                quote = char
                state = "string"
            output.append(char)
        elif state == "line":
            output.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "code"
        elif state == "block":
            if pair == "*/":
                output.extend("  ")
                state = "code"
                index += 2
                continue
            output.append("\n" if char == "\n" else " ")
        else:
            output.append(char)
            if char == "\\" and index + 1 < len(source):
                index += 1
                output.append(source[index])
            elif char == quote:
                state = "code"
        index += 1
    if state == "block":
        raise ValueError("unterminated block comment")
    return "".join(output)


def resolve_include(name: str, including: Path, libraries: list[Path]) -> Path:
    if not name or Path(name).is_absolute():
        raise ValueError(f"unsupported include path: {name!r}")
    candidates = [including.parent / name, *(root / name for root in libraries)]
    matches: list[Path] = []
    for candidate in candidates:
        if candidate.is_symlink():
            raise ValueError(f"include is a symlink: {candidate}")
        resolved = candidate.resolve()
        if resolved.is_file() and resolved not in matches:
            matches.append(resolved)
    if not matches:
        raise ValueError(f"include not found: {name} from {including}")
    return matches[0]


def dependency_closure(entrypoint: Path, libraries: list[Path]) -> list[Path]:
    pending = [entrypoint.resolve()]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"source is missing or a symlink: {path}")
        visited.add(path)
        text = strip_comments(path.read_text())
        for name in INCLUDE.findall(text):
            child = resolve_include(name, path, libraries)
            if child not in visited:
                pending.append(child)
    return sorted(visited, key=lambda item: str(item))


def git_capture(project_root: Path) -> dict[str, Any]:
    def call(*args: str) -> str:
        try:
            process = subprocess.run(["git", "-C", str(project_root), *args], capture_output=True,
                                     text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PipelineError("revision_preflight_failed",
                                f"git {' '.join(args)} could not complete") from error
        if process.returncode:
            raise PipelineError("revision_preflight_failed", f"git {' '.join(args)} failed")
        return process.stdout

    top = Path(call("rev-parse", "--show-toplevel").strip()).resolve()
    head = call("rev-parse", "--verify", "HEAD").strip()
    if not re.match(r"\A[0-9a-f]{40,64}\Z", head):
        raise PipelineError("revision_preflight_failed", "invalid revision commit")
    return {"repository_root": str(top), "commit": head,
            "branch": call("branch", "--show-current").strip() or None,
            "status_porcelain": call("status", "--porcelain=v1", "--untracked-files=all")}


def logical_source(path: Path, project_root: Path, libraries: list[Path]) -> tuple[str, Path, Path]:
    if path.is_relative_to(project_root):
        return "project", project_root, path.relative_to(project_root)
    roots = [(f"library-{index:02d}", root) for index, root in enumerate(libraries) if root != project_root]
    choices = [(label, root, path.relative_to(root)) for label, root in roots if path.is_relative_to(root)]
    if not choices:
        raise PipelineError("revision_preflight_failed", f"source lies outside declared roots: {path}")
    choices.sort(key=lambda row: (len(row[2].parts), row[0]))
    return choices[0]


def normalize_inputs(entrypoint: Path, base_input: Path, project_root: Path,
                     library_paths: list[Path]) -> dict[str, Any]:
    if project_root.is_symlink() or entrypoint.is_symlink() or base_input.is_symlink():
        raise PipelineError("input_preflight_failed", "input paths must not be symlinks")
    if any(path.is_symlink() for path in library_paths):
        raise PipelineError("input_preflight_failed", "library paths must not be symlinks")
    project_root = project_root.resolve()
    entrypoint = entrypoint.resolve()
    base_input = base_input.resolve()
    libraries: list[Path] = []
    for path in [project_root, *library_paths]:
        resolved = path.resolve()
        if resolved not in libraries:
            libraries.append(resolved)
    if not project_root.is_dir() or not entrypoint.is_file() or not entrypoint.is_relative_to(project_root):
        raise PipelineError("input_preflight_failed", "entrypoint must be a file below project root")
    if any(not path.is_dir() or path.is_symlink() for path in libraries):
        raise PipelineError("input_preflight_failed", "library paths must be real directories")
    try:
        base_value = json.loads(base_input.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PipelineError("input_preflight_failed", f"base input is not valid JSON: {type(error).__name__}") from error
    if not isinstance(base_value, dict):
        raise PipelineError("input_preflight_failed", "base input must be a JSON object")
    closure = dependency_closure(entrypoint, libraries)
    rows = []
    for source in closure:
        label, root, relative = logical_source(source, project_root, libraries)
        rows.append({"root": label, "root_path": str(root), "relative": relative.as_posix(),
                     "source_path": str(source), "sha256": sha256(source)})
    closure_identity = [{key: row[key] for key in ("root", "relative", "sha256")} for row in rows]
    revision = git_capture(project_root)
    normalized = json_bytes(base_value)
    return {"entrypoint": str(entrypoint), "entrypoint_relative": entrypoint.relative_to(project_root).as_posix(),
            "project_root": str(project_root), "library_paths": [str(path) for path in libraries],
            "base_input": str(base_input), "base_input_sha256": sha256(base_input),
            "normalized_base_input_sha256": hashlib.sha256(normalized).hexdigest(),
            "base_value": base_value, "closure": rows, "closure_sha256": value_sha(closure_identity),
            "revision": revision}


def select_j_tool(tools: dict[str, dict[str, Any]]) -> str:
    for name in J_NAMES:
        if name not in tools:
            continue
        entry = tools[name]
        path = Path(entry["path"])
        expected = entry.get("sha256")
        if not SHA_RE.match(str(expected)) or sha256(path) != expected:
            raise ValueError("J v2.8 manifest SHA differs from the executable")
        try:
            version = subprocess.run([str(path), "--version"], capture_output=True, text=True,
                                     timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError("J v2.8 version check could not complete") from error
        output = (version.stdout + "\n" + version.stderr).strip()
        if version.returncode != 0 or not re.search(r"\bzkfdo-j-v28\b", output, re.IGNORECASE):
            raise ValueError("J executable does not identify itself as zkfdo-j-v28")
        entry["verified_version_output"] = output
        return name
    raise ValueError("tools manifest needs an explicitly identified J v2.8 executable")


def load_tools(path: Path, verify: bool = True) -> tuple[dict[str, Any], str]:
    required = list(REQUIRED_TOOLS)
    loaded = tool_manifest.load_manifest(path, required=required, verify=verify)
    j_name = select_j_tool(loaded["tools"])
    loaded["selected_j_tool"] = j_name
    return loaded, j_name


def command_view(argv: list[str | Path]) -> list[str]:
    return [str(item) for item in argv]


class CommandRunner:
    def __init__(self, ledger: dict[str, Any], checkpoint: Callable[[], None],
                 executable_sha256: dict[str, str] | None = None):
        self.ledger = ledger
        self.checkpoint = checkpoint
        self.executable_sha256 = executable_sha256 or {}

    @staticmethod
    def _group_exists(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @classmethod
    def _wait_group_gone(cls, process: subprocess.Popen[bytes], process_group: int,
                         seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            process.poll()
            if not cls._group_exists(process_group):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(PROCESS_POLL_SECONDS)

    @classmethod
    def _stop_process(cls, process: subprocess.Popen[bytes], row: dict[str, Any], reason: str) -> None:
        started = time.monotonic()
        process_group = int(row.get("process_group") or process.pid)
        row["termination_reason"] = reason
        termination = {"process_group": process_group, "term_sent": False,
                       "kill_sent": False, "group_gone": False}
        row["termination"] = termination
        try:
            os.killpg(process_group, signal.SIGTERM)
            termination["term_sent"] = True
        except ProcessLookupError:
            termination["group_gone"] = True
        except OSError as error:
            row["termination_error"] = f"{type(error).__name__}: {error}"
        if not termination["group_gone"]:
            termination["group_gone"] = cls._wait_group_gone(
                process, process_group, PROCESS_TERM_GRACE_SECONDS)
        if not termination["group_gone"]:
            try:
                os.killpg(process_group, signal.SIGKILL)
                termination["kill_sent"] = True
            except ProcessLookupError:
                termination["group_gone"] = True
            except OSError as error:
                row["termination_error"] = f"{type(error).__name__}: {error}"
            if not termination["group_gone"]:
                termination["group_gone"] = cls._wait_group_gone(
                    process, process_group, PROCESS_KILL_GRACE_SECONDS)
        try:
            process.wait(timeout=0)
        except (subprocess.TimeoutExpired, ChildProcessError):
            pass
        termination["wall_seconds"] = time.monotonic() - started
        if not termination["group_gone"]:
            raise PipelineError("process_group_cleanup_failed",
                                f"process group {process_group} survived TERM and KILL")

    def run(self, stage: str, label: str, argv: list[str | Path], directory: Path,
            timeout: float, *, cwd: Path | None = None, env_add: dict[str, str] | None = None,
            disk_path: Path | None = None, minimum_free_bytes: int | None = None,
            disk_interval_seconds: float = DISK_MONITOR_SECONDS,
            disk_usage: Callable[[Path], Any] = shutil.disk_usage) -> dict[str, Any]:
        timeout = positive(timeout, "command timeout")
        if (disk_path is None) != (minimum_free_bytes is None):
            raise ValueError("disk monitor path and floor must be provided together")
        if disk_path is not None:
            positive(disk_interval_seconds, "disk monitor interval")
        directory.mkdir(parents=True, exist_ok=False)
        argv_text = command_view(argv)
        row = {"stage": stage, "label": label, "argv": argv_text, "argv_sha256": value_sha(argv_text),
               "directory": str(directory), "timeout_seconds": timeout, "status": "starting",
               "start_utc": utc(), "start_epoch_seconds": time.time(),
               "wall_seconds": 0.0, "cpu_seconds": None}
        self.ledger.setdefault("commands", []).append(row)
        self.checkpoint()
        started = time.monotonic()
        before = os.times()
        process = None
        environment = os.environ.copy()
        if env_add:
            environment.update(env_add)
            row["environment_additions"] = dict(env_add)
        previous_handlers: dict[int, Any] = {}
        try:
            with (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
                executable = Path(argv_text[0]).resolve()
                expected_sha = (self.executable_sha256.get(str(executable))
                                or self.executable_sha256.get(argv_text[0]))
                if expected_sha is not None:
                    actual_sha = sha256(executable)
                    row["executable"] = {"path": str(executable), "expected_sha256": expected_sha,
                                         "actual_sha256": actual_sha, "verified": actual_sha == expected_sha}
                    if actual_sha != expected_sha:
                        row["status"] = "executable_identity_failed"
                        raise PipelineError("executable_identity_failed",
                                            f"executable SHA differs immediately before launch: {executable}")
                process = subprocess.Popen(argv_text, cwd=str(cwd) if cwd else None, env=environment,
                                           stdout=stdout, stderr=stderr, start_new_session=True)
                row.update(pid=process.pid, process_group=process.pid)
                self.checkpoint()
                if threading.current_thread() is threading.main_thread():
                    def handle_supervisor_signal(signum: int, _frame: object) -> None:
                        row["supervisor_signal"] = signum
                        self._stop_process(process, row, f"supervisor_signal_{signum}")
                        raise SupervisorSignal(signum)

                    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                        previous_handlers[signum] = signal.getsignal(signum)
                        signal.signal(signum, handle_supervisor_signal)
                deadline = started + timeout
                next_disk = started
                while True:
                    returncode = process.poll()
                    if returncode is not None:
                        row.update(status="completed" if returncode == 0 else "command_failed",
                                   returncode=returncode)
                        break
                    now = time.monotonic()
                    if disk_path is not None and now >= next_disk:
                        try:
                            receipt = disk_gate(disk_path, int(minimum_free_bytes), usage=disk_usage)
                        except PipelineError:
                            self._stop_process(process, row, "disk_floor")
                            row.update(status="disk_floor", returncode=process.returncode)
                            break
                        row.setdefault("disk_checks", []).append({**receipt, "utc": utc()})
                        next_disk = now + disk_interval_seconds
                        self.checkpoint()
                    if now >= deadline:
                        self._stop_process(process, row, "timeout")
                        row.update(status="timeout", returncode=process.returncode)
                        break
                    wait_for = min(PROCESS_POLL_SECONDS, max(0.0, deadline - now))
                    if disk_path is not None:
                        wait_for = min(wait_for, max(0.0, next_disk - now))
                    time.sleep(wait_for)
        except PipelineError:
            if process is not None and process.poll() is None:
                self._stop_process(process, row, "execution_error")
            raise
        except OSError as error:
            if process is not None:
                self._stop_process(process, row, "execution_error")
            row.update(status="spawn_failed" if process is None else "execution_failed",
                       error=f"{type(error).__name__}: {error}")
        except BaseException as error:
            if process is not None and process.poll() is None:
                self._stop_process(process, row, "interrupted")
            row.update(status="interrupted", error=f"{type(error).__name__}: {error}",
                       returncode=None if process is None else process.returncode)
            raise
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
            after = os.times()
            row["wall_seconds"] = time.monotonic() - started
            row["cpu_seconds"] = (after.children_user + after.children_system
                                  - before.children_user - before.children_system)
            for name in ("stdout.log", "stderr.log"):
                path = directory / name
                if path.is_file():
                    row[name.replace(".", "_")] = {"path": str(path), "sha256": sha256(path),
                                                      "bytes": path.stat().st_size}
            self.checkpoint()
        return row


def next_attempt(directory: Path) -> Path:
    attempts = directory / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    numbers = [int(path.name) for path in attempts.iterdir() if path.is_dir() and path.name.isdigit()]
    number = max(numbers, default=0) + 1
    if number > 9999:
        raise PipelineError("attempt_limit", f"attempt limit reached: {directory}")
    return attempts / f"{number:04d}"


def find_one(directory: Path, name: str) -> Path:
    paths = list(directory.rglob(name))
    if len(paths) != 1:
        raise ValueError(f"expected one {name}, found {len(paths)}")
    return paths[0]


def order_key(row: dict[str, Any]) -> tuple[Any, ...]:
    definition = row["definition"]
    return (row.get("ranking", {}).get("size") or 0, definition["template_name"],
            tuple(str(value) for value in definition.get("concrete_parameters") or []), row["target_id"])


def r1cs_shape(path: Path) -> dict[str, int]:
    with path.open("rb") as source:
        if source.read(4) != b"r1cs":
            raise ValueError("invalid R1CS magic")
        version, sections = struct.unpack("<II", source.read(8))
        if version != 1:
            raise ValueError("unsupported R1CS version")
        header = None
        for _ in range(sections):
            kind, length = struct.unpack("<IQ", source.read(12))
            if kind == 1:
                if length > 4096:
                    raise ValueError("oversized R1CS header")
                header = source.read(length)
                if len(header) != length:
                    raise ValueError("truncated R1CS section")
            else:
                source.seek(length, os.SEEK_CUR)
            if source.tell() > path.stat().st_size:
                raise ValueError("truncated R1CS section")
    if header is None:
        raise ValueError("R1CS header is absent")
    width = struct.unpack_from("<I", header, 0)[0]
    offset = 4 + width
    if width <= 0 or offset + 28 != len(header):
        raise ValueError("invalid R1CS header")
    wires, outputs, public, private = struct.unpack_from("<IIII", header, offset)
    constraints = struct.unpack_from("<I", header, offset + 24)[0]
    if 1 + outputs + public + private > wires:
        raise ValueError("invalid R1CS input range")
    return {"wires": wires, "outputs": outputs, "public_inputs": public,
            "private_inputs": private, "constraints": constraints}


def wtns_metadata(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    with path.open("rb") as source:
        if source.read(4) != b"wtns":
            raise ValueError("invalid WTNS magic")
        raw = source.read(8)
        if len(raw) != 8:
            raise ValueError("short WTNS header")
        version, section_count = struct.unpack("<II", raw)
        if version != 2:
            raise ValueError("unsupported WTNS version")
        sections: dict[int, tuple[int, int]] = {}
        for _ in range(section_count):
            raw = source.read(12)
            if len(raw) != 12:
                raise ValueError("truncated WTNS section header")
            kind, length = struct.unpack("<IQ", raw)
            offset = source.tell()
            if kind in sections or offset + length > size:
                raise ValueError("invalid WTNS section")
            sections[kind] = (offset, length)
            source.seek(length, os.SEEK_CUR)
        if source.tell() != size or set(sections) != {1, 2}:
            raise ValueError("unexpected WTNS sections")
        header_offset, header_length = sections[1]
        if header_length < 8 or header_length > 4096:
            raise ValueError("invalid WTNS header")
        source.seek(header_offset)
        header = source.read(header_length)
    width = struct.unpack_from("<I", header, 0)[0]
    if width <= 0 or width > 512 or len(header) != 8 + width:
        raise ValueError("invalid WTNS header")
    prime = int.from_bytes(header[4:4 + width], "little")
    count = struct.unpack_from("<I", header, 4 + width)[0]
    data_offset, data_length = sections[2]
    if data_length != count * width:
        raise ValueError("WTNS value length differs")
    return {"prime": prime, "width": width, "count": count, "data_offset": data_offset}


def compare_wtns_range(left_path: Path, right_path: Path, left: dict[str, Any],
                       right: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    if start < 0 or end < start or end > left["count"] or end > right["count"]:
        raise ValueError("WTNS comparison range differs")
    width = left["width"]
    differences: list[int] = []
    difference_count = 0
    with left_path.open("rb") as lhs, right_path.open("rb") as rhs:
        for first in range(start, end, 4096):
            count = min(4096, end - first)
            lhs.seek(left["data_offset"] + first * width)
            rhs.seek(right["data_offset"] + first * width)
            left_raw, right_raw = lhs.read(count * width), rhs.read(count * width)
            if len(left_raw) != count * width or len(right_raw) != count * width:
                raise ValueError("truncated WTNS data")
            for offset in range(count):
                begin = offset * width
                left_value = int.from_bytes(left_raw[begin:begin + width], "little")
                right_value = int.from_bytes(right_raw[begin:begin + width], "little")
                if left_value >= left["prime"] or right_value >= right["prime"]:
                    raise ValueError("noncanonical WTNS value")
                if left_value != right_value:
                    difference_count += 1
                    if len(differences) < 1024:
                        differences.append(first + offset)
    return {"count": difference_count, "wires": differences,
            "wire_list_truncated": difference_count > len(differences)}


def compare_pair(r1cs: Path, comparator: Path, deviated: Path) -> dict[str, Any]:
    shape = r1cs_shape(r1cs)
    left, right = wtns_metadata(comparator), wtns_metadata(deviated)
    if (left["prime"] != right["prime"] or left["width"] != right["width"]
            or left["count"] != shape["wires"] or right["count"] != shape["wires"]):
        raise ValueError("witness shape or prime differs")
    first_input = 1 + shape["outputs"]
    last_input = first_input + shape["public_inputs"] + shape["private_inputs"]
    outputs = compare_wtns_range(comparator, deviated, left, right, 1, 1 + shape["outputs"])
    inputs = compare_wtns_range(comparator, deviated, left, right, first_input, last_input)
    return {"shape": shape, "same_full_input": inputs["count"] == 0,
            "differing_input_count": inputs["count"], "differing_input_wires": inputs["wires"],
            "differing_input_wire_list_truncated": inputs["wire_list_truncated"],
            "outputs_differ": outputs["count"] > 0, "differing_output_count": outputs["count"],
            "differing_output_wires": outputs["wires"],
            "differing_output_wire_list_truncated": outputs["wire_list_truncated"]}


def safe_owned(path: Path, root: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{label} path is not absolute")
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file() or path.is_symlink():
        raise ValueError(f"{label} escapes owned output")
    cursor = path.parent
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError(f"{label} has a symlink ancestor")
        parent = cursor.parent
        if parent == cursor:
            raise ValueError(f"{label} has no owned ancestor")
        cursor = parent
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"{label} root differs")
    return resolved


def safe_owned_directory(path: Path, root: Path, label: str) -> Path:
    if not path.is_absolute():
        raise PipelineError("output_ownership_failed", f"{label} path is not absolute")
    root_resolved = root.resolve()
    resolved = path.resolve()
    if path.is_symlink() or not path.is_dir() or not resolved.is_relative_to(root_resolved):
        raise PipelineError("output_ownership_failed", f"{label} escapes owned output")
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            raise PipelineError("output_ownership_failed", f"{label} has a symlink ancestor")
        parent = cursor.parent
        if parent == cursor:
            raise PipelineError("output_ownership_failed", f"{label} has no owned ancestor")
        cursor = parent
    if root.is_symlink() or not root.is_dir():
        raise PipelineError("output_ownership_failed", f"{label} root differs")
    return resolved


def copy_verified(source: Path, destination: Path, expected_sha: str) -> dict[str, Any]:
    if not SHA_RE.match(expected_sha) or sha256(source) != expected_sha:
        raise ValueError("source SHA256 differs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_symlink() or sha256(destination) != expected_sha:
            raise ValueError(f"preserved file differs: {destination}")
    else:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=destination.name + ".tmp-", dir=destination.parent)
        temporary = Path(raw_temporary)
        try:
            with source.open("rb") as src, os.fdopen(descriptor, "wb") as dst:
                descriptor = -1
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            if sha256(temporary) != expected_sha:
                raise ValueError("copy changed while preserving")
            os.replace(temporary, destination)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
    return {"path": str(destination), "sha256": expected_sha, "bytes": destination.stat().st_size}


@contextmanager
def stage_attempt(pipeline: "Pipeline", name: str):
    identity = pipeline.stage_identity(name)
    previous = pipeline.ledger["stages"].get(name)
    if previous and previous.get("status") == "completed":
        if previous.get("identity_sha256") != identity:
            pipeline.ledger.setdefault("resume_events", []).append({
                "stage": name, "status": "rejected_identity_mismatch", "utc": utc(),
                "previous_identity_sha256": previous.get("identity_sha256"),
                "current_identity_sha256": identity,
            })
            pipeline.checkpoint()
            raise PipelineError("resume_identity_mismatch", f"completed stage identity differs: {name}")
        else:
            started, cpu_started = time.monotonic(), time.process_time()
            try:
                pipeline.validate_completed_stage(name, previous)
            except BaseException as error:
                pipeline.ledger.setdefault("resume_events", []).append({
                    "stage": name,
                    "status": "failed", "wall_seconds": time.monotonic() - started,
                    "cpu_seconds": time.process_time() - cpu_started, "utc": utc(),
                    "terminal_status": getattr(error, "status", "resume_validation_failed"),
                    "error": f"{type(error).__name__}: {error}",
                })
                pipeline.checkpoint()
                raise
            pipeline.ledger.setdefault("resume_events", []).append(
                {"stage": name, "status": "skipped", "utc": utc()})
            pipeline.checkpoint()
            yield None
            return
    if previous:
        pipeline.archive_stage_record(name, previous, recovered=True)
    attempt_dir = next_attempt(pipeline.output / "stage-records" / name)
    attempt_dir.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.monotonic(), time.process_time()
    row = {"stage": name, "status": "running", "identity_sha256": identity, "attempt": attempt_dir.name,
           "directory": str(attempt_dir), "started_utc": utc(),
           "started_epoch_seconds": time.time(), "wall_seconds": 0.0, "cpu_seconds": 0.0}
    pipeline.ledger["stages"][name] = row
    pipeline.checkpoint()
    try:
        yield row
    except BaseException as error:
        row.update(status="failed", terminal_status=getattr(error, "status", "operational_failure"),
                   error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
        raise
    else:
        row["status"] = ("partial" if (row.get("terminal_status") == "candidates_pending"
                                       or row.get("resume_required"))
                         else "completed")
        row["terminal_status"] = row.get("terminal_status", "completed")
    finally:
        wall_seconds = time.monotonic() - started
        cpu_seconds = time.process_time() - cpu_started
        if name == "j_requests":
            row["raw_wall_seconds"] = wall_seconds
            row["raw_cpu_seconds"] = cpu_seconds
            wall_seconds = max(0.0, wall_seconds - float(
                row.get("embedded_postcheck_wall_seconds") or 0))
            cpu_seconds = max(0.0, cpu_seconds - float(
                row.get("embedded_postcheck_cpu_seconds") or 0))
        elif name == "postcheck":
            row["aggregation_wall_seconds"] = wall_seconds
            row["aggregation_cpu_seconds"] = cpu_seconds
            request_costs = (row.get("outputs") or {}).get("request_costs") or {}
            wall_seconds += float(request_costs.get("wall_seconds") or 0)
            cpu_seconds += float(request_costs.get("cpu_seconds") or 0)
        elif name == "preflight":
            row["local_wall_seconds"] = wall_seconds
            row["local_cpu_seconds"] = cpu_seconds
            startup = row.get("startup_preflight_costs") or {}
            wall_seconds += float(startup.get("wall_seconds") or 0)
            cpu_seconds += float(startup.get("cpu_seconds") or 0)
        row["wall_seconds"] = wall_seconds
        row["cpu_seconds"] = cpu_seconds
        row["finished_utc"] = utc()
        pipeline.archive_stage_record(name, row, recovered=False)
        pipeline.checkpoint()


class Pipeline:
    def __init__(self, args: argparse.Namespace, normalized: dict[str, Any], tools: dict[str, Any],
                 j_name: str, identity: dict[str, Any],
                 startup_preflight: dict[str, Any] | None = None):
        self.args = args
        self.normalized = normalized
        self.tools_manifest = tools
        self.tools_manifest_path = Path(tools["manifest_path"])
        self.tools = tools["tools"]
        self.j_name = j_name
        self.identity = identity
        self.identity_sha = value_sha(identity)
        self.startup_preflight = startup_preflight or {
            "wall_seconds": 0.0, "cpu_seconds": 0.0, "phases": [],
        }
        self.output = reject_symlink_ancestry(args.out, "output").resolve()
        self.source_root = self.output / "work/source"
        self.project = self.source_root / "project"
        self.base_input = self.source_root / "base-input.json"
        self.library_paths = self._snapshot_libraries()
        self.entrypoint = self.project / normalized["entrypoint_relative"]
        self.ledger_path = self.output / "ledger.json"
        self.identity_path = self.output / "identity.json"
        self.ledger = self._open_ledger()
        self._recovered_extra_allocation_seconds = 0.0
        self.reconcile_immutable_history()
        executable_sha256 = {
            str(Path(entry["path"]).resolve()): entry["sha256"]
            for entry in self.tools.values()
        }
        self.runner = CommandRunner(self.ledger, self.checkpoint, executable_sha256)

    def _snapshot_libraries(self) -> list[Path]:
        paths = [self.project]
        project_root = Path(self.normalized["project_root"])
        for index, raw in enumerate(self.normalized["library_paths"]):
            root = Path(raw)
            if root == project_root:
                snapshot = self.project
            elif root.is_relative_to(project_root):
                snapshot = self.project / root.relative_to(project_root)
            else:
                snapshot = self.source_root / f"library-{index:02d}"
            if snapshot not in paths:
                paths.append(snapshot)
        return paths

    def _open_ledger(self) -> dict[str, Any]:
        if self.output.exists():
            if not self.output.is_dir() or self.output.is_symlink():
                raise PipelineError("output_ownership_failed", "output is not a real directory")
            administrative = {".sj-pipeline.lock", ".sj-pipeline-lock-history"}
            unowned = [path for path in self.output.iterdir() if path.name not in administrative]
            if not self.identity_path.exists() and unowned:
                raise PipelineError("output_ownership_failed", "nonempty output has no pipeline identity")
        else:
            self.output.mkdir(parents=True, exist_ok=False)
        if self.identity_path.exists():
            if self.identity_path.is_symlink() or not self.identity_path.is_file():
                raise PipelineError("output_ownership_failed", "pipeline identity is not a real file")
            saved = read_json(self.identity_path)
            if saved != self.identity:
                raise PipelineError("resume_identity_mismatch", "output identity differs")
        else:
            atomic_json(self.identity_path, self.identity)
        if self.ledger_path.exists():
            if self.ledger_path.is_symlink() or not self.ledger_path.is_file():
                raise PipelineError("output_ownership_failed", "pipeline ledger is not a real file")
            ledger = read_json(self.ledger_path)
            if ledger.get("identity_sha256") != self.identity_sha:
                raise PipelineError("resume_identity_mismatch", "ledger identity differs")
            if ledger.get("complete") and ledger.get("status") != "dry_run":
                raise PipelineError("terminal_output_immutable",
                                    "completed or failed output is immutable; use a new output suffix")
            return ledger
        ledger = {"schema": SCHEMA, "status": "starting", "complete": False,
                  "engine_started": False, "identity_sha256": self.identity_sha,
                  "created_utc": utc(), "stages": {}, "commands": [],
                  "budgets": self.identity["budgets"], "seed_policy": self.identity["seed_policy"],
                  "corpus_layer": self.args.corpus_layer,
                  "stage_attempt_history": {},
                  "budget_accounting": {
                      "s": {"allocated_seconds": self.args.s_budget_seconds,
                            "consumed_seconds": 0.0, "events": []},
                      "j": {"base_allocated_seconds": self.args.j_total_seconds,
                            "extra_allocated_seconds": 0.0,
                            "allocated_seconds": self.args.j_total_seconds,
                            "consumed_seconds": 0.0, "events": []},
                  },
                  "limitations": [
                      "A terminal unsupported or exhausted status is not a safety finding.",
                      "An output-identical observation applies only to the recorded input and intervention.",
                      "Local elapsed time is functional evidence only.",
                      "Source discovery supports literal Circom include paths only.",
                      "Source roots must be real non-symlink paths in a Git repository with a commit.",
                      "Baseline and fragment compilation use O0; S uses the bn128 prime.",
                      "External pair comparison supports R1CS v1 and WTNS v2 evidence.",
                      "Preparation syntax support is limited by the pinned preparation executable.",
                      "Periodic disk sampling cannot prevent an instantaneous peak inside a sampling interval.",
                  ]}
        atomic_json(self.ledger_path, ledger)
        return ledger

    def archive_stage_record(self, name: str, row: dict[str, Any], *, recovered: bool) -> None:
        raw_directory = row.get("directory")
        if not isinstance(raw_directory, str) or not raw_directory:
            return
        directory = Path(raw_directory)
        if not directory.is_dir() or directory.is_symlink():
            return
        attempts_root = (self.output / "stage-records" / name / "attempts").resolve()
        if not directory.resolve().is_relative_to(attempts_root):
            raise PipelineError("attempt_history_mismatch",
                                f"stage attempt directory escapes history: {name}")
        snapshot = {key: value for key, value in row.items() if key != "attempt_receipt"}
        if (recovered and "finished_utc" not in snapshot
                and "archived_as" not in snapshot):
            snapshot = {**snapshot, "archived_as": "interrupted_on_resume",
                        "archived_utc": utc()}
        path = directory / "attempt-receipt.json"
        if path.exists():
            if path.is_symlink() or read_json(path) != snapshot:
                raise PipelineError("attempt_history_mismatch", f"stage attempt history differs: {name}")
        else:
            atomic_json(path, snapshot)
        reference = {"attempt": row.get("attempt"), "path": str(path), "sha256": sha256(path),
                     "status": snapshot.get("status"),
                     "terminal_status": snapshot.get("terminal_status")}
        history = self.ledger.setdefault("stage_attempt_history", {}).setdefault(name, [])
        if reference not in history:
            history.append(reference)
        row["attempt_receipt"] = reference

    def checkpoint(self) -> None:
        self.ledger["updated_utc"] = utc()
        atomic_json(self.ledger_path, self.ledger)

    def _immutable_event(self, category: str, value: dict[str, Any]) -> dict[str, Any]:
        directory = self.output / "immutable-ledger" / category
        directory.mkdir(parents=True, exist_ok=True)
        numbers = [int(path.stem) for path in directory.glob("*.json") if path.stem.isdigit()]
        path = directory / f"{max(numbers, default=0) + 1:06d}.json"
        exclusive_json(path, value)
        return {"path": str(path), "sha256": sha256(path)}

    def _numbered_immutable_events(self, category: str) -> list[dict[str, Any]]:
        directory = self.output / "immutable-ledger" / category
        if not directory.exists():
            return []
        if directory.is_symlink() or not directory.is_dir():
            raise PipelineError("immutable_history_mismatch",
                                f"immutable history directory differs: {category}")
        paths = sorted(directory.glob("*.json"))
        expected_names = [f"{index:06d}.json" for index in range(1, len(paths) + 1)]
        if [path.name for path in paths] != expected_names:
            raise PipelineError("immutable_history_mismatch",
                                f"immutable history sequence differs: {category}")
        events = []
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise PipelineError("immutable_history_mismatch",
                                    f"immutable history entry differs: {category}")
            value = read_json(path)
            if not isinstance(value, dict) or "receipt" in value:
                raise PipelineError("immutable_history_mismatch",
                                    f"immutable history entry is invalid: {category}")
            events.append({**value, "receipt": {"path": str(path), "sha256": sha256(path)}})
        return events

    @staticmethod
    def _event_prefix(saved: list[dict[str, Any]], recovered: list[dict[str, Any]],
                      label: str) -> None:
        if len(saved) > len(recovered) or saved != recovered[:len(saved)]:
            raise PipelineError("immutable_history_mismatch", f"{label} history differs")

    def _reconcile_budget_history(self) -> bool:
        events = self._numbered_immutable_events("budget-events")
        accounting = self.ledger["budget_accounting"]
        if not events:
            if accounting["s"].get("events") or accounting["j"].get("events"):
                raise PipelineError("immutable_history_mismatch",
                                    "budget ledger has no immutable receipts")
            return False
        recovered: dict[str, list[dict[str, Any]]] = {"s": [], "j": []}
        allocated = {"s": 0.0, "j": 0.0}
        base = {"s": 0.0, "j": 0.0}
        consumed = {"s": 0.0, "j": 0.0}
        old_counts = {name: len(accounting[name].get("events") or []) for name in ("s", "j")}
        orphan_extra = 0.0
        charge_ids: set[str] = set()
        for event in events:
            budget = event.get("budget")
            kind = event.get("kind")
            seconds = event.get("seconds")
            if (event.get("schema") != "zkfdo-sj-budget-event-v1"
                    or budget not in recovered or isinstance(seconds, bool)
                    or not isinstance(seconds, (int, float)) or not math.isfinite(seconds)
                    or seconds < 0):
                raise PipelineError("immutable_history_mismatch", "budget receipt is invalid")
            seconds = float(seconds)
            if kind == "base_allocation":
                expected = (self.args.s_budget_seconds if budget == "s"
                            else self.args.j_total_seconds)
                if allocated[budget] != 0 or seconds != expected:
                    raise PipelineError("immutable_history_mismatch",
                                        f"{budget} base allocation differs")
                base[budget] = seconds
                allocated[budget] = seconds
                cumulative_key = "cumulative_allocated_seconds"
            elif kind == "extra_allocation":
                if budget != "j" or base[budget] == 0:
                    raise PipelineError("immutable_history_mismatch",
                                        "extra allocation receipt is invalid")
                allocated[budget] += seconds
                cumulative_key = "cumulative_allocated_seconds"
                if len(recovered[budget]) >= old_counts[budget]:
                    orphan_extra += seconds
            elif kind == "consumption":
                if base[budget] == 0:
                    raise PipelineError("immutable_history_mismatch",
                                        "consumption precedes base allocation")
                charge_id = event.get("charge_id")
                if (not isinstance(charge_id, str) or not charge_id
                        or charge_id in charge_ids):
                    raise PipelineError("immutable_history_mismatch",
                                        "budget consumption identity differs")
                charge_ids.add(charge_id)
                consumed[budget] += seconds
                cumulative_key = "cumulative_consumed_seconds"
            else:
                raise PipelineError("immutable_history_mismatch", "budget event kind differs")
            expected_cumulative = (allocated[budget] if "allocated" in cumulative_key
                                   else consumed[budget])
            if abs(float(event.get(cumulative_key, -1)) - expected_cumulative) > 1e-9:
                raise PipelineError("immutable_history_mismatch",
                                    f"{budget} cumulative budget differs")
            recovered[budget].append(event)
        for budget in ("s", "j"):
            self._event_prefix(accounting[budget].get("events") or [], recovered[budget],
                               f"{budget} budget")
            accounting[budget]["events"] = recovered[budget]
            accounting[budget]["allocated_seconds"] = allocated[budget]
            accounting[budget]["consumed_seconds"] = consumed[budget]
        accounting["j"]["base_allocated_seconds"] = base["j"]
        accounting["j"]["extra_allocated_seconds"] = allocated["j"] - base["j"]
        self._recovered_extra_allocation_seconds = orphan_extra
        return any(len(recovered[name]) != old_counts[name] for name in ("s", "j"))

    def _reconcile_stage_history(self) -> bool:
        changed = False
        stages_root = self.output / "stage-records"
        if not stages_root.exists():
            return False
        if stages_root.is_symlink() or not stages_root.is_dir():
            raise PipelineError("attempt_history_mismatch", "stage history root differs")
        for name in STAGES:
            attempts_root = stages_root / name / "attempts"
            if not attempts_root.exists():
                continue
            if attempts_root.is_symlink() or not attempts_root.is_dir():
                raise PipelineError("attempt_history_mismatch", f"stage attempts differ: {name}")
            rows: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
            for directory in sorted(path for path in attempts_root.iterdir() if path.is_dir()):
                if directory.is_symlink() or not directory.name.isdigit():
                    raise PipelineError("attempt_history_mismatch",
                                        f"stage attempt directory differs: {name}")
                receipt = directory / "attempt-receipt.json"
                if not receipt.exists():
                    continue
                if receipt.is_symlink() or not receipt.is_file():
                    raise PipelineError("attempt_history_mismatch",
                                        f"stage attempt receipt differs: {name}")
                row = read_json(receipt)
                if (row.get("stage") != name or row.get("attempt") != directory.name
                        or row.get("directory") != str(directory)):
                    raise PipelineError("attempt_history_mismatch",
                                        f"stage attempt identity differs: {name}")
                reference = {"attempt": directory.name, "path": str(receipt),
                             "sha256": sha256(receipt), "status": row.get("status"),
                             "terminal_status": row.get("terminal_status")}
                rows.append((int(directory.name), row, reference))
            canonical = [reference for _, _, reference in rows]
            history = self.ledger.setdefault("stage_attempt_history", {}).setdefault(name, [])
            self._event_prefix(history, canonical, f"{name} stage attempt")
            if history != canonical:
                history[:] = canonical
                changed = True
            if not rows:
                continue
            current = self.ledger.setdefault("stages", {}).get(name)
            current_number = int(current.get("attempt", "0")) if current and str(
                current.get("attempt", "")).isdigit() else 0
            last_number, last_row, last_reference = rows[-1]
            if last_number >= current_number:
                if (last_number == current_number and current
                        and current.get("status") not in ("running", last_row.get("status"))):
                    raise PipelineError("attempt_history_mismatch",
                                        f"current stage record differs: {name}")
                recovered_row = {**last_row, "attempt_receipt": last_reference}
                if current != recovered_row:
                    self.ledger["stages"][name] = recovered_row
                    changed = True
        return changed

    def reconcile_immutable_history(self) -> None:
        changed = self._reconcile_budget_history()
        changed = self._reconcile_stage_history() or changed
        if changed:
            self.ledger.setdefault("resume_events", []).append({
                "status": "recovered_immutable_history", "utc": utc()})
            self.checkpoint()

    def register_budget_allocation(self) -> None:
        accounting = self.ledger["budget_accounting"]
        if not accounting["s"]["events"]:
            event = {"schema": "zkfdo-sj-budget-event-v1", "kind": "base_allocation",
                     "budget": "s", "utc": utc(), "seconds": self.args.s_budget_seconds,
                     "cumulative_allocated_seconds": self.args.s_budget_seconds}
            event["receipt"] = self._immutable_event("budget-events", event)
            accounting["s"]["events"].append(event)
        if not accounting["j"]["events"]:
            event = {"schema": "zkfdo-sj-budget-event-v1", "kind": "base_allocation",
                     "budget": "j", "utc": utc(), "seconds": self.args.j_total_seconds,
                     "cumulative_allocated_seconds": self.args.j_total_seconds}
            event["receipt"] = self._immutable_event("budget-events", event)
            accounting["j"]["events"].append(event)
        extra = float(self.args.j_extra_total_seconds)
        if extra > 0 and abs(extra - self._recovered_extra_allocation_seconds) <= 1e-9:
            self.ledger.setdefault("resume_events", []).append({
                "status": "recovered_extra_allocation", "utc": utc(), "seconds": extra})
            extra = 0.0
        self._recovered_extra_allocation_seconds = 0.0
        if extra > 0:
            allocated = float(accounting["j"]["allocated_seconds"]) + extra
            event = {"schema": "zkfdo-sj-budget-event-v1", "kind": "extra_allocation",
                     "budget": "j", "utc": utc(), "seconds": extra,
                     "cumulative_allocated_seconds": allocated}
            event["receipt"] = self._immutable_event("budget-events", event)
            accounting["j"]["events"].append(event)
            accounting["j"]["extra_allocated_seconds"] = (
                float(accounting["j"]["extra_allocated_seconds"]) + extra)
            accounting["j"]["allocated_seconds"] = allocated
        self.checkpoint()

    def charge_budget(self, budget: str, seconds: float, scope: str,
                      reference: dict[str, Any] | None = None, *,
                      charge_id: str) -> dict[str, Any]:
        if seconds < 0 or not math.isfinite(seconds):
            raise ValueError("budget charge must be finite and nonnegative")
        if not isinstance(charge_id, str) or not charge_id:
            raise ValueError("budget charge identity must be nonempty")
        accounting = self.ledger["budget_accounting"][budget]
        existing = [event for event in accounting["events"]
                    if event.get("kind") == "consumption"
                    and event.get("charge_id") == charge_id]
        if len(existing) > 1:
            raise PipelineError("immutable_history_mismatch",
                                f"budget charge identity is duplicated: {charge_id}")
        expected_reference = reference or {}
        if existing:
            event = existing[0]
            if (event.get("budget") != budget or event.get("scope") != scope
                    or event.get("reference") != expected_reference):
                raise PipelineError("immutable_history_mismatch",
                                    f"budget charge identity was reused: {charge_id}")
            return event
        consumed = float(accounting["consumed_seconds"]) + seconds
        event = {"schema": "zkfdo-sj-budget-event-v1", "kind": "consumption",
                 "budget": budget, "utc": utc(), "seconds": seconds,
                 "scope": scope, "charge_id": charge_id,
                 "cumulative_consumed_seconds": consumed,
                 "reference": expected_reference}
        event["receipt"] = self._immutable_event("budget-events", event)
        accounting["events"].append(event)
        accounting["consumed_seconds"] = consumed
        self.checkpoint()
        return event

    def j_budget_remaining(self) -> float:
        accounting = self.ledger["budget_accounting"]["j"]
        return max(0.0, float(accounting["allocated_seconds"])
                   - float(accounting["consumed_seconds"]))

    def s_budget_remaining(self) -> float:
        accounting = self.ledger["budget_accounting"]["s"]
        return max(0.0, float(accounting["allocated_seconds"])
                   - float(accounting["consumed_seconds"]))

    def reconcile_interrupted_consumption(self) -> None:
        s_record = self.ledger.get("stages", {}).get("s_campaign") or {}
        if s_record.get("status") == "running" and not s_record.get("budget_charge"):
            started = s_record.get("started_epoch_seconds")
            if isinstance(started, (int, float)) and not isinstance(started, bool):
                elapsed = min(
                    max(0.0, time.time() - float(started)),
                    self.s_budget_remaining() + S_PROCESS_CLEANUP_CAP_SECONDS)
                s_record["budget_charge"] = self.charge_budget(
                    "s", elapsed, "s_campaign",
                    {"stage_attempt": s_record.get("attempt")},
                    charge_id=f"s-stage:{s_record.get('attempt')}")
                s_record["budget_reconciled_utc"] = utc()
        commands = {row.get("label"): row for row in self.ledger.get("commands", [])}
        for state in self.ledger.get("candidate_states", []):
            self._reconcile_candidate_events(state)
            for request in state.get("attempts", []):
                self._reconcile_request_receipt(request)
                command = commands.get(request.get("request_id"))
                if command and not request.get("budget_charge"):
                    measured = float(command.get("wall_seconds") or 0)
                    started = command.get("start_epoch_seconds")
                    if (command.get("status") in ("starting", "running")
                            and isinstance(started, (int, float)) and not isinstance(started, bool)):
                        observed = max(0.0, time.time() - float(started))
                        cap = (float(command.get("timeout_seconds") or self.args.j_request_seconds)
                               + PROCESS_TERM_GRACE_SECONDS + PROCESS_KILL_GRACE_SECONDS)
                        measured = max(measured, min(observed, cap))
                    request["budget_charge"] = self.charge_budget(
                        "j", measured, request["request_id"],
                        {"command_argv_sha256": command.get("argv_sha256")},
                        charge_id=f"j-request:{request['request_id']}")
                    request["budget_reconciled_utc"] = utc()
                if request.get("terminal_receipt"):
                    if state.get("state") != "judged" and request.get("status") != "interrupted":
                        self.candidate_event(
                            state, "judged", request.get("terminal_status", "recovered_terminal"),
                            request_id=request.get("request_id"),
                            request_attempt=request.get("request_attempt"),
                            request_receipt=request["terminal_receipt"],
                            reason="terminal request receipt recovered after interruption")
                    continue
                if request.get("status") in ("starting", "running", "completed"):
                    request.update(
                        status="interrupted", terminal_status="recovered_interrupted_request",
                        reason="request was active when the previous supervisor stopped",
                        finished_utc=utc(),
                        cache_cleanup={
                            "status": "retained_for_recovery",
                            "reason": "request recovery did not establish completed preservation",
                        },
                    )
                    self._write_request_receipt(request)
                    if state.get("state") != "judged":
                        self.candidate_event(
                            state, "in_progress_interrupted", "recovered_interrupted_request",
                            request_id=request.get("request_id"),
                            request_attempt=request.get("request_attempt"),
                            request_receipt=request["terminal_receipt"],
                            reason=request["reason"])
        self.checkpoint()

    def _reconcile_candidate_events(self, state: dict[str, Any]) -> None:
        index = state["candidate_index"]
        events = self._numbered_immutable_events(f"candidate-{index:06d}")
        saved = state.setdefault("events", [])
        self._event_prefix(saved, events, f"candidate {index}")
        for sequence, event in enumerate(events, start=1):
            if (event.get("schema") != "zkfdo-sj-candidate-event-v1"
                    or event.get("candidate_index") != index
                    or event.get("candidate_sha256") != state["candidate"]["sha256"]
                    or event.get("sequence") != sequence
                    or event.get("state") not in (
                        "judged", "in_progress_interrupted", "pending_not_run")):
                raise PipelineError("immutable_history_mismatch",
                                    f"candidate {index} event identity differs")
        if events:
            saved[:] = events
            latest = events[-1]
            state.update(state=latest["state"], terminal_status=latest["terminal_status"],
                         updated_utc=latest["utc"], last_event=latest["receipt"])

    def _reconcile_request_receipt(self, request: dict[str, Any]) -> None:
        directory = Path(request.get("directory", ""))
        if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
            raise PipelineError("request_history_mismatch", "request directory differs")
        receipt = directory / "terminal-receipt.json"
        reference = request.get("terminal_receipt")
        if not receipt.exists():
            if reference:
                raise PipelineError("request_history_mismatch", "request receipt is absent")
            return
        if receipt.is_symlink() or not receipt.is_file():
            raise PipelineError("request_history_mismatch", "request receipt differs")
        saved = read_json(receipt)
        saved_reference = {"path": str(receipt), "sha256": sha256(receipt)}
        stable = ("index", "request_attempt", "request_id", "candidate", "directory",
                  "stage_attempt_directory")
        if any(saved.get(key) != request.get(key) for key in stable):
            raise PipelineError("request_history_mismatch", "request receipt identity differs")
        if reference:
            if reference != saved_reference or saved != {
                    key: value for key, value in request.items() if key != "terminal_receipt"}:
                raise PipelineError("request_history_mismatch", "request terminal history differs")
            return
        request.clear()
        request.update(saved)
        request["terminal_receipt"] = saved_reference

    @staticmethod
    def candidate_budget_consumed(state: dict[str, Any]) -> float:
        return sum(float((request.get("budget_charge") or {}).get("seconds") or 0)
                   for request in state.get("attempts", []))

    def candidate_event(self, state_row: dict[str, Any], state: str,
                        terminal_status: str, **details: Any) -> dict[str, Any]:
        if state not in ("judged", "in_progress_interrupted", "pending_not_run"):
            raise ValueError(f"invalid candidate state: {state}")
        events = state_row.setdefault("events", [])
        event = {"schema": "zkfdo-sj-candidate-event-v1",
                 "candidate_index": state_row["candidate_index"],
                 "candidate_sha256": state_row["candidate"]["sha256"],
                 "sequence": len(events) + 1, "utc": utc(), "state": state,
                 "terminal_status": terminal_status, **details}
        event["receipt"] = self._immutable_event(
            f"candidate-{state_row['candidate_index']:06d}", event)
        events.append(event)
        state_row.update(state=state, terminal_status=terminal_status,
                         updated_utc=event["utc"], last_event=event["receipt"])
        self.checkpoint()
        return event

    def initialize_candidate_states(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        current = self.ledger.get("candidate_states")
        if current is not None:
            saved = [row["candidate"] for row in current]
            if len(saved) > len(candidates) or saved != candidates[:len(saved)]:
                raise PipelineError("resume_identity_mismatch", "candidate inventory differs on resume")
            for index, candidate in enumerate(candidates[len(saved):], start=len(saved)):
                row = {"candidate_index": index, "candidate": candidate, "events": []}
                current.append(row)
                if self._numbered_immutable_events(f"candidate-{index:06d}"):
                    self._reconcile_candidate_events(row)
                else:
                    self.candidate_event(row, "pending_not_run", "not_started")
            for row in current:
                self._reconcile_candidate_events(row)
            self.checkpoint()
            return current
        current = []
        self.ledger["candidate_states"] = current
        for index, candidate in enumerate(candidates):
            row = {"candidate_index": index, "candidate": candidate, "events": []}
            current.append(row)
            if self._numbered_immutable_events(f"candidate-{index:06d}"):
                self._reconcile_candidate_events(row)
            else:
                self.candidate_event(row, "pending_not_run", "not_started")
        self.checkpoint()
        return current

    def stage_identity(self, name: str) -> str:
        dependencies = STAGES[:STAGES.index(name)]
        completed = {}
        for stage in dependencies:
            record = self.ledger["stages"].get(stage, {})
            completed[stage] = {
                "identity_sha256": record.get("identity_sha256"),
                "attempt": record.get("attempt"),
                "terminal_status": record.get("terminal_status"),
                "outputs_sha256": value_sha(record.get("outputs")) if "outputs" in record else None,
            }
        return value_sha({"pipeline_identity": self.identity_sha, "stage": name, "dependencies": completed})

    def tool(self, name: str) -> str:
        return str(self.tools[name]["path"])

    def verify_tool_identities(self, names: tuple[str, ...]) -> dict[str, Any]:
        observed = []
        for name in names:
            entry = self.tools[name]
            path = Path(entry["path"]).resolve()
            expected = entry["sha256"]
            actual = sha256(path)
            observed.append({"name": name, "path": str(path),
                             "expected_sha256": expected, "actual_sha256": actual,
                             "verified": actual == expected})
            if actual != expected:
                raise PipelineError(
                    "executable_identity_failed",
                    f"executable SHA differs immediately before J: {path}")
        return {"utc": utc(), "tools": observed}

    def mark_started(self) -> None:
        if not self.ledger["engine_started"]:
            self.ledger["engine_started"] = True
            self.ledger["engine_started_utc"] = utc()
            self.checkpoint()

    def validate_completed_stage(self, name: str, record: dict[str, Any]) -> None:
        outputs = record.get("outputs") or {}

        def exact(value: dict[str, Any], label: str) -> None:
            path = safe_owned(Path(value["path"]), self.output, label)
            if sha256(path) != value["sha256"]:
                raise PipelineError("resume_identity_mismatch", f"completed {label} artifact differs")

        if name == "preflight":
            self.write_source_snapshot()
            manifest = self.output / "work/source-manifest.json"
            if (outputs.get("source_manifest") != str(manifest)
                    or sha256(manifest) != outputs.get("source_manifest_sha256")):
                raise PipelineError("resume_identity_mismatch", "source manifest identity differs")
        elif name == "baseline":
            for key in ("r1cs", "sym", "witness"):
                exact(outputs[key], f"baseline {key}")
        elif name == "preparation":
            for key in ("discovery", "manifest", "prepared", "plan"):
                exact(outputs[key], f"preparation {key}")
            safe_owned_directory(Path(outputs["prepared_root"]), self.source_root,
                                 "prepared output root")
            for binding in outputs.get("bindings", []):
                wrapper = safe_owned(Path(binding["wrapper"]), self.source_root, "prepared wrapper")
                sources = Path(binding["sources"])
                if not sources.is_dir() or not sources.resolve().is_relative_to(self.source_root.resolve()):
                    raise PipelineError("resume_identity_mismatch", "prepared source directory differs")
                if (sha256(wrapper) != binding["wrapper_sha256"]
                        or policy_v1.tree_sha256(sources) != binding["sources_tree_sha256"]):
                    raise PipelineError("resume_identity_mismatch", "prepared source identity differs")
                self.prepared_binding_layout(binding, compare_saved=True)
        elif name == "s_campaign":
            exact(outputs["spec"], "S specification")
            exact(outputs["revision_profile"], "S revision profile")
            exact(outputs["campaign_ledger"], "S ledger")
        elif name == "j_requests":
            exact(outputs["selected_candidates"], "selected candidate list")
            inventory = read_json(outputs["selected_candidates"]["path"])
            for candidate in inventory.get("representatives", []):
                path = safe_owned(Path(candidate["path"]), self.output, "selected candidate")
                if sha256(path) != candidate["sha256"]:
                    raise PipelineError("resume_identity_mismatch", "selected candidate differs")
            for request in outputs.get("requests", []):
                self._owned_request_root(request)
                if request.get("status") == "completed":
                    for key in ("request", "result", "probe"):
                        exact(request[key], f"J {key}")
                    self._read_request_postcheck(request)
                receipt = request.get("terminal_receipt")
                if receipt:
                    exact(receipt, "J terminal receipt")
                self._validate_cache_state(request)
        elif name == "postcheck":
            exact(outputs["record"], "postcheck record")
            for request in outputs.get("checks", []):
                original = request.get("original") or {}
                for key in ("r1cs", "sym", "identity"):
                    if key in original:
                        exact(original[key], f"postcheck original {key}")
                for pair in request.get("pairs", []):
                    for check_key in ("comparator_check", "deviated_check"):
                        witness = (pair.get(check_key) or {}).get("witness")
                        if witness:
                            exact(witness, f"postcheck {check_key}")
            for value in outputs.get("validated_counterexamples", []):
                for key in ("original_r1cs", "comparator_wtns", "deviated_wtns"):
                    exact(value[key], f"validated {key}")
        elif name == "summary":
            for key in ("summary_json", "summary_markdown"):
                exact(outputs[key], f"summary {key}")

    def _validate_source_tree(self, expected_files: list[dict[str, Any]]) -> None:
        expected = {row["snapshot_relative"] for row in expected_files}
        for library in self.library_paths:
            relative_root = library.relative_to(self.source_root)
            expected_below = {
                name for name in expected
                if Path(name).is_relative_to(relative_root)
            }
            actual: set[str] = set()
            for path in library.rglob("*"):
                if path.is_symlink() or not (path.is_file() or path.is_dir()):
                    raise PipelineError("resume_identity_mismatch", "source snapshot has a special node")
                if path.is_file():
                    actual.add(path.relative_to(self.source_root).as_posix())
            if actual != expected_below:
                raise PipelineError("resume_identity_mismatch", "source snapshot file set differs")

    def write_source_snapshot(self) -> dict[str, Any]:
        work = self.output / "work"
        if work.exists():
            if work.is_symlink() or work.resolve() != self.output.resolve() / "work":
                raise PipelineError("resume_identity_mismatch", "work directory identity differs")
        else:
            work.mkdir()
        manifest_path = work / "source-manifest.json"
        if self.source_root.exists():
            expected_source = self.output.resolve() / "work/source"
            if self.source_root.is_symlink() or self.source_root.resolve() != expected_source:
                raise PipelineError("resume_identity_mismatch", "source snapshot is a symlink")
            if not manifest_path.is_file():
                if self.ledger.get("engine_started"):
                    raise PipelineError("resume_identity_mismatch", "source snapshot manifest is absent")
                shutil.rmtree(self.source_root)
            else:
                manifest = read_json(manifest_path)
                expected_files = [
                    {**{key: row[key] for key in ("root", "relative", "sha256")},
                     "snapshot_relative": f"{row['root']}/{row['relative']}"}
                    for row in self.normalized["closure"]
                ]
                expected_base = {"path": str(self.base_input),
                                 "sha256": self.normalized["normalized_base_input_sha256"]}
                if (manifest.get("schema") != "zkfdo-sj-source-snapshot-v1"
                        or manifest.get("closure_sha256") != self.normalized["closure_sha256"]
                        or manifest.get("files") != expected_files
                        or manifest.get("base_input") != expected_base):
                    raise PipelineError("resume_identity_mismatch", "source manifest differs")
                if any(not path.is_dir() or path.is_symlink()
                       or path.resolve() != self.source_root.resolve() / path.relative_to(self.source_root)
                       for path in self.library_paths):
                    raise PipelineError("resume_identity_mismatch", "snapshot library path differs")
                self._validate_source_tree(expected_files)
                for row in manifest["files"]:
                    path = self.source_root / row["snapshot_relative"]
                    if not path.is_file() or path.is_symlink() or sha256(path) != row["sha256"]:
                        raise PipelineError("resume_identity_mismatch", "source snapshot differs")
                if sha256(self.base_input) != self.normalized["normalized_base_input_sha256"]:
                    raise PipelineError("resume_identity_mismatch", "normalized base input differs")
                return manifest
        staging = self.output / "work/source.staging"
        if staging.exists():
            expected_staging = self.output.resolve() / "work/source.staging"
            if (staging.is_symlink() or staging.resolve() != expected_staging
                    or self.ledger.get("engine_started")):
                raise PipelineError("resume_identity_mismatch", "source staging path differs")
            shutil.rmtree(staging)
        files = []
        staging.mkdir(parents=True, exist_ok=False)
        for library in self.library_paths:
            (staging / library.relative_to(self.source_root)).mkdir(parents=True, exist_ok=True)
        for row in self.normalized["closure"]:
            destination = staging / row["root"] / row["relative"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            copy_verified(Path(row["source_path"]), destination, row["sha256"])
            files.append({**{key: row[key] for key in ("root", "relative", "sha256")},
                          "snapshot_relative": destination.relative_to(staging).as_posix()})
        staged_base = staging / "base-input.json"
        with staged_base.open("xb") as output:
            output.write(json_bytes(self.normalized["base_value"]))
            output.flush()
            os.fsync(output.fileno())
        if sha256(staged_base) != self.normalized["normalized_base_input_sha256"]:
            raise ValueError("normalized base input SHA differs")
        os.replace(staging, self.source_root)
        manifest = {"schema": "zkfdo-sj-source-snapshot-v1", "files": files,
                    "closure_sha256": self.normalized["closure_sha256"],
                    "base_input": {"path": str(self.base_input), "sha256": sha256(self.base_input)}}
        atomic_json(manifest_path, manifest)
        return manifest

    def verify_pinned_source(self, scope: str) -> dict[str, Any]:
        manifest_path = self.output / "work/source-manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise PipelineError("source_identity_failed", "source snapshot manifest is absent")
        manifest = read_json(manifest_path)
        expected_files = manifest.get("files") or []
        self._validate_source_tree(expected_files)
        observed = []
        for row in expected_files:
            path = self.source_root / row["snapshot_relative"]
            if path.is_symlink() or not path.is_file() or sha256(path) != row["sha256"]:
                raise PipelineError("source_identity_failed", f"pinned source changed: {path}")
            observed.append({key: row[key] for key in ("root", "relative", "sha256")})
        try:
            base_value = json.loads(self.base_input.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PipelineError("base_input_identity_failed", "normalized base input is unreadable") from error
        normalized_sha = hashlib.sha256(json_bytes(base_value)).hexdigest()
        if (sha256(self.base_input) != self.normalized["normalized_base_input_sha256"]
                or normalized_sha != self.normalized["normalized_base_input_sha256"]):
            raise PipelineError("base_input_identity_failed", "normalized base input changed")
        closure_sha = value_sha(observed)
        if closure_sha != self.normalized["closure_sha256"]:
            raise PipelineError("source_identity_failed", "pinned source closure SHA differs")
        return {"schema": "zkfdo-sj-pinned-source-check-v1", "scope": scope, "utc": utc(),
                "closure_sha256": closure_sha,
                "expected_closure_sha256": self.normalized["closure_sha256"],
                "normalized_base_input_sha256": normalized_sha,
                "source_manifest_sha256": sha256(manifest_path)}

    def prepared_binding_layout(self, binding: dict[str, Any], *, compare_saved: bool) -> dict[str, Any]:
        wrapper = safe_owned(Path(binding["wrapper"]), self.source_root, "prepared wrapper")
        sources = Path(binding["sources"])
        safe_owned_directory(sources, self.source_root, "prepared source root")
        if (sha256(wrapper) != binding["wrapper_sha256"]
                or policy_v1.tree_sha256(sources) != binding["sources_tree_sha256"]):
            raise PipelineError("preparation_identity_failed", "prepared source identity differs")
        libraries = []
        for path in [sources.resolve(), *self.library_paths]:
            if path not in libraries:
                libraries.append(path)
        layout = source_closure_layout(wrapper, libraries, self.source_root)
        if compare_saved:
            saved = binding.get("include_layout") or {}
            if (layout["closure_sha256"] != binding.get("closure_sha256")
                    or layout != saved):
                raise PipelineError("preparation_identity_failed",
                                    "prepared include closure changed")
        return layout

    def preflight_stage(self) -> dict[str, Any]:
        with stage_attempt(self, "preflight") as row:
            if row is None:
                started, cpu_started = time.monotonic(), time.process_time()
                try:
                    disk = disk_gate(self.output, int(self.args.min_free_gib * GIB))
                except BaseException as error:
                    previous = self.ledger["stages"]["preflight"]
                    previous["resume_disk_gate"] = {
                        "status": "failed", "wall_seconds": time.monotonic() - started,
                        "cpu_seconds": time.process_time() - cpu_started, "utc": utc(),
                        "terminal_status": getattr(error, "status", "operational_failure"),
                        "error": f"{type(error).__name__}: {error}",
                    }
                    self.checkpoint()
                    raise
                self.ledger.setdefault("resume_events", []).append({
                    "stage": "preflight", "status": "disk_gate_passed", "disk_gate": disk,
                    "startup_preflight": self.startup_preflight,
                    "wall_seconds": time.monotonic() - started,
                    "cpu_seconds": time.process_time() - cpu_started, "utc": utc(),
                })
                self.checkpoint()
                return self.ledger["stages"]["preflight"]["outputs"]
            row["startup_preflight_costs"] = self.startup_preflight
            disk = disk_gate(self.output, int(self.args.min_free_gib * GIB))
            snapshot = self.write_source_snapshot()
            if not self.entrypoint.is_file():
                raise PipelineError("revision_preflight_failed", "entrypoint is absent from source snapshot")
            outputs = {"disk_gate": disk, "revision": self.normalized["revision"],
                       "closure_sha256": self.normalized["closure_sha256"],
                       "startup_preflight": self.startup_preflight,
                       "entrypoint": str(self.entrypoint), "base_input": str(self.base_input),
                       "source_manifest": str(self.output / "work/source-manifest.json"),
                       "source_manifest_sha256": sha256(self.output / "work/source-manifest.json")}
            row["outputs"] = outputs
            return outputs

    def baseline_stage(self) -> dict[str, Any]:
        with stage_attempt(self, "baseline") as row:
            if row is None:
                return self.ledger["stages"]["baseline"]["outputs"]
            self.mark_started()
            attempt = Path(row["directory"])
            artifacts = attempt / "artifacts"
            artifacts.mkdir()
            compile_argv = [self.tool("circom"), self.entrypoint, "--O0", "--r1cs", "--sym", "--wasm",
                            "--output", artifacts]
            for library in self.library_paths:
                compile_argv.extend(["-l", library])
            command = self.runner.run("baseline", "compile", compile_argv, attempt / "commands/compile",
                                      self.args.baseline_seconds, cwd=self.project)
            if command["status"] != "completed":
                raise PipelineError("baseline_input_invalid", "original O0 compilation failed")
            stem = self.entrypoint.stem
            r1cs = artifacts / f"{stem}.r1cs"
            sym = artifacts / f"{stem}.sym"
            wasm = artifacts / f"{stem}_js/{stem}.wasm"
            generator = artifacts / f"{stem}_js/generate_witness.js"
            if not all(path.is_file() for path in (r1cs, sym, wasm, generator)):
                raise PipelineError("baseline_input_invalid", "original compile artifacts are incomplete")
            witness = attempt / "honest.wtns"
            node = self.runner.run("baseline", "honest_witness",
                                   [self.tool("node"), generator, wasm, self.base_input, witness],
                                   attempt / "commands/honest-witness", self.args.baseline_seconds, cwd=self.project)
            if node["status"] != "completed" or not witness.is_file():
                raise PipelineError("baseline_input_invalid", "honest witness generation failed")
            environment = {"N6_J1_R1CS": str(r1cs), "N6_J1_WTNS": str(witness)}
            rust = self.runner.run("baseline", "rust_check",
                                   [self.tool("rust_checker"), "check_current_witness", "--exact", "--ignored"],
                                   attempt / "commands/rust-check", self.args.baseline_seconds,
                                   cwd=ROOT, env_add=environment)
            if rust["status"] != "completed":
                raise PipelineError("baseline_input_invalid", "Rust witness check failed")
            snark = self.runner.run("baseline", "snarkjs_check",
                                    [self.tool("snarkjs"), "wtns", "check", r1cs, witness],
                                    attempt / "commands/snarkjs-check", self.args.baseline_seconds, cwd=ROOT)
            snark_log = Path(snark["stdout_log"]["path"]) if snark.get("stdout_log") else None
            confirmed = (snark["status"] == "completed" and snark_log is not None
                         and any(marker in snark_log.read_text(errors="replace") for marker in SNARKJS_MARKERS))
            if not confirmed:
                raise PipelineError("baseline_input_invalid", "snarkjs witness check failed")
            shape = r1cs_shape(r1cs)
            outputs = {"status": "valid", "r1cs": {"path": str(r1cs), "sha256": sha256(r1cs)},
                       "sym": {"path": str(sym), "sha256": sha256(sym)},
                       "witness": {"path": str(witness), "sha256": sha256(witness)}, "shape": shape,
                       "rust_check": "passed", "snarkjs_check": "passed"}
            row["outputs"] = outputs
            return outputs

    def _capture_path(self, discovery: dict[str, Any], report_path: Path) -> Path | None:
        instance = discovery.get("instance_discovery") or {}
        raw = instance.get("capture_path") or (instance.get("capture") or {}).get("path")
        if not raw:
            return None
        path = Path(raw)
        if path.is_absolute():
            return path
        choices = [report_path.parent / path, self.source_root / path, ROOT / path]
        found = [choice.resolve() for choice in choices if choice.resolve().is_file()]
        if len(set(found)) != 1:
            raise ValueError("relative instance capture is missing or ambiguous")
        return found[0]

    def _prepared_sources(self, entrypoint: Path, prepared_root: Path) -> Path:
        prepared_root = prepared_root.resolve()
        choices = [
            parent for parent in entrypoint.resolve().parents
            if (parent.name == "sources" and parent.parent.parent.name == "targets"
                and parent.is_relative_to(prepared_root))
        ]
        if len(choices) != 1:
            raise PipelineError("fragment_plan_failed", "prepared source root is unavailable or ambiguous")
        return choices[0]

    def preparation_stage(self) -> dict[str, Any]:
        with stage_attempt(self, "preparation") as row:
            if row is None:
                return self.ledger["stages"]["preparation"]["outputs"]
            attempt = Path(row["directory"])
            discovery_output = self.source_root / f"discovery-{attempt.name}"
            argv = [self.tool("prepare"), "targets", "--project", self.project,
                    "--entrypoint", self.entrypoint, "--output", discovery_output,
                    "--circom-bin", self.tool("circom"), "--compile-timeout-seconds", "60",
                    "--instance-capture", "--capture-timeout-seconds", "60"]
            for library in self.library_paths:
                argv.extend(["--library-path", library])
            result = self.runner.run("preparation", "targets", argv, attempt / "commands/targets",
                                     self.args.preparation_command_seconds, cwd=ROOT)
            if result["status"] != "completed":
                raise PipelineError("target_discovery_failed", "target discovery failed")
            report_path = find_one(discovery_output, "discovery.json")
            discovery = read_json(report_path)
            capture = self._capture_path(discovery, report_path)
            revision = self.normalized["revision"]
            manifest = manifest_for(Path(revision["repository_root"]).name, revision["commit"], self.project,
                                    self.entrypoint, discovery, self.library_paths, capture)
            manifest_path = attempt / "manifest.json"
            atomic_json(manifest_path, manifest)
            prepared_output = self.source_root / f"prepared-{attempt.name}"
            prep = self.runner.run("preparation", "prepare",
                                   [self.tool("prepare"), "experiment", "prepare", "--manifest", manifest_path,
                                    "--output", prepared_output, "--strategy", "small-first",
                                    "--circom-bin", self.tool("circom"), "--tool-timeout-seconds", "60"],
                                   attempt / "commands/prepare", self.args.preparation_command_seconds, cwd=ROOT)
            if prep["status"] != "completed":
                raise PipelineError("fragment_preparation_failed", "fragment preparation failed")
            prepared_path = find_one(prepared_output, "prepared.json")
            plan_path = attempt / "split-plan.json"
            ranking = ROOT / "configs/static-ranking.json"
            plan = self.runner.run("preparation", "plan",
                                   [self.tool("prepare"), "experiment", "plan", "--prepared", prepared_path,
                                    "--strategy", "small-first", "--config", ranking, "--output", plan_path],
                                   attempt / "commands/plan", self.args.preparation_command_seconds, cwd=ROOT)
            if plan["status"] != "completed" or not plan_path.is_file():
                raise PipelineError("fragment_plan_failed", "fragment ranking plan failed")
            plan_value = read_json(plan_path)
            targets = sorted(plan_value.get("targets", []), key=order_key)
            if not targets:
                raise PipelineError("unsupported_no_fragments", "preparation produced no runnable fragments")
            bindings = []
            for item in targets:
                run_entrypoint = safe_owned(Path(item["run_entrypoint"]), self.source_root,
                                            "prepared entrypoint")
                sources = self._prepared_sources(run_entrypoint, prepared_output)
                binding = {"target_id": item["target_id"], "wrapper": str(run_entrypoint),
                           "sources": str(sources),
                           "wrapper_sha256": sha256(run_entrypoint),
                           "sources_tree_sha256": policy_v1.tree_sha256(sources),
                           "definition_entrypoint": item["definition"]["entrypoint"],
                           "template": item["definition"]["template_name"],
                           "parameters": item["definition"].get("concrete_parameters") or []}
                layout = self.prepared_binding_layout(binding, compare_saved=False)
                binding.update(include_layout=layout,
                               closure_sha256=layout["closure_sha256"])
                bindings.append(binding)
            outputs = {"discovery": {"path": str(report_path), "sha256": sha256(report_path)},
                       "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
                       "prepared": {"path": str(prepared_path), "sha256": sha256(prepared_path)},
                       "prepared_root": str(prepared_output),
                       "plan": {"path": str(plan_path), "sha256": sha256(plan_path)},
                       "target_count": len(targets), "bindings": bindings}
            row["outputs"] = outputs
            return outputs

    def build_s_spec(self, preparation: dict[str, Any], destination: Path) -> tuple[dict[str, Any], Path]:
        plan = read_json(preparation["plan"]["path"])
        planned = sorted(plan["targets"], key=order_key)
        snapshots, targets, revisions, profiles = [], [], [], {}
        commit = self.normalized["revision"]["commit"]
        for index, item in enumerate(planned):
            entrypoint = Path(item["run_entrypoint"]).resolve()
            snapshot = self._prepared_sources(entrypoint, Path(preparation["prepared_root"]))
            identifier = f"target-{index:04d}"
            relative = entrypoint.relative_to(snapshot).as_posix()
            entry_sha = sha256(entrypoint)
            snapshots.append({"id": identifier, "path": str(snapshot),
                              "tree_sha256": policy_v1.tree_sha256(snapshot),
                              "expected_baseline_candidates": 0, "candidate_globs": [CANDIDATE_GLOB]})
            targets.append({"target_id": item["target_id"], "rank": index + 1,
                            "source_snapshot_id": identifier, "entrypoint_relative": relative,
                            "entrypoint_sha256": entry_sha,
                            "command": [self.tool("zkfuzz"), "{entrypoint}", "--prime", "bn128",
                                        "--search_mode", "ga", "-l", "{workspace}"],
                            "preflight_compile_command": [self.tool("circom"), "{entrypoint}", "--r1cs", "--sym",
                                                          "--O0", "--output", "{compile_output}", "-l", "{workspace}"]})
            revision_id = f"sj-{identifier}"
            profiles[revision_id] = {"revision_id": revision_id, "revision_commit": commit,
                                     "requirements": [{"id": "prepared-entrypoint", "kind": "file",
                                                       "path": relative, "sha256": entry_sha}]}
        profile_path = destination / "revision-profiles.json"
        atomic_json(profile_path, {"schema": "zkfdo-preparation-assets-v1", "revisions": profiles})
        profile_sha = sha256(profile_path)
        for index, snapshot in enumerate(snapshots):
            revisions.append({"source_snapshot_id": snapshot["id"], "revision_id": f"sj-target-{index:04d}",
                              "revision_commit": commit, "profile_path": str(profile_path),
                              "profile_sha256": profile_sha})
        spec = {"schema_version": 1, "method": "split", "campaign_id": "sj-pipeline-v1",
                "total_budget_seconds": self.args.s_budget_seconds,
                "attempt_cap_seconds": self.args.s_attempt_seconds, "concurrency": 1,
                "initial_seed": self.args.initial_seed, "seed_rule": "increment_per_pass",
                "seed_transport": {"kind": "mutation_settings", "argument": "--path_to_mutation_setting", "base": {}},
                "max_tree_rss_bytes": None, "coverage_checkpoints_seconds": [self.args.s_budget_seconds],
                "preflight_compile_timeout_seconds": 60, "require_pinned_command_tools": True,
                "require_save_output": False, "zkfuzz_output": "stderr_report", "pinned_trees": [],
                "pinned_files": [{"label": name, "path": self.tool(name), "sha256": self.tools[name]["sha256"]}
                                 for name in ("circom", "zkfuzz")],
                "source_snapshots": snapshots, "targets": targets, "revision_preflights": revisions}
        return spec, profile_path

    def s_campaign_stage(self, preparation: dict[str, Any]) -> dict[str, Any]:
        with stage_attempt(self, "s_campaign") as row:
            if row is None:
                return self.ledger["stages"]["s_campaign"]["outputs"]
            if sha256(self.tools_manifest_path) != self.tools_manifest["manifest_sha256"]:
                raise PipelineError("tools_manifest_changed", "tools manifest changed after preflight")
            attempt = Path(row["directory"])
            source_check = self.verify_pinned_source("immediately_before_s")
            binding_checks = [self.prepared_binding_layout(binding, compare_saved=True)
                              for binding in preparation["bindings"]]
            remaining = self.s_budget_remaining()
            if remaining <= 0:
                outputs = {"status": "stopped", "termination_reason": "budget_exhausted",
                           "measurement_valid": False, "invalid_reasons": ["S budget already consumed"],
                           "attempt_count": 0, "continue_to_j": False,
                           "source_check": source_check, "binding_checks": binding_checks,
                           "s_budget_remaining_seconds": 0.0}
                row.update(outputs=outputs, terminal_status="budget_exhausted")
                return outputs
            spec, profile = self.build_s_spec(preparation, attempt)
            spec["total_budget_seconds"] = remaining
            spec["coverage_checkpoints_seconds"] = [remaining]
            spec_path = attempt / "spec.json"
            atomic_json(spec_path, spec)
            campaign_output = attempt / "campaign"
            self.mark_started()
            campaign_started = time.monotonic()
            try:
                campaign_ledger = policy_v51.run_campaign(
                    spec_path, campaign_output, max_disk_bytes=int(self.args.max_disk_gib * GIB),
                    max_attempts=None, tools_manifest_path=self.tools_manifest_path,
                    load_tools_manifest=True,
                    purpose="discovery", min_free_bytes=int(self.args.run_min_free_gib * GIB),
                    tree_interval_seconds=1.0, free_interval_seconds=0.0)
            finally:
                elapsed = time.monotonic() - campaign_started
                row["budget_charge"] = self.charge_budget(
                    "s", elapsed, "s_campaign", {"stage_attempt": row["attempt"]},
                    charge_id=f"s-stage:{row['attempt']}")
            campaign_ledger_path = campaign_output / "ledger.json"
            outputs = {"spec": {"path": str(spec_path), "sha256": sha256(spec_path)},
                       "revision_profile": {"path": str(profile), "sha256": sha256(profile)},
                       "campaign_output": str(campaign_output),
                       "campaign_ledger": {"path": str(campaign_ledger_path),
                                           "sha256": sha256(campaign_ledger_path)},
                       "status": campaign_ledger.get("status"),
                       "termination_reason": campaign_ledger.get("termination_reason"),
                       "measurement_valid": campaign_ledger.get("measurement_valid"),
                       "invalid_reasons": campaign_ledger.get("invalid_reasons", []),
                       "attempt_count": len(campaign_ledger.get("attempts", [])),
                       "source_check": source_check, "binding_checks": binding_checks,
                       "s_budget_allocated_this_attempt_seconds": remaining,
                       "s_budget_remaining_seconds": self.s_budget_remaining()}
            row["outputs"] = outputs
            termination = campaign_ledger.get("termination_reason")
            usable = (campaign_ledger.get("status") == "completed"
                      or (campaign_ledger.get("status") == "stopped"
                          and termination in ("budget_exhausted", "disk_limit", "interrupted")))
            if not usable:
                raise PipelineError("s_campaign_failed", "v5.1 campaign did not reach a usable terminal state")
            outputs["resume_required"] = termination == "interrupted"
            outputs["continue_to_j"] = termination not in ("disk_limit", "interrupted")
            if termination in ("budget_exhausted", "disk_limit", "interrupted"):
                row["terminal_status"] = termination
            if termination == "interrupted":
                row["resume_required"] = True
            return outputs

    def candidate_inventory(self, s_outputs: dict[str, Any]) -> dict[str, Any]:
        campaigns: list[dict[str, Any]] = []
        seen_ledgers: set[str] = set()
        for reference in self.ledger.get("stage_attempt_history", {}).get("s_campaign", []):
            receipt_path = Path(reference.get("path", ""))
            if (not receipt_path.is_file() or receipt_path.is_symlink()
                    or sha256(receipt_path) != reference.get("sha256")):
                raise PipelineError("attempt_history_mismatch", "S attempt receipt differs")
            outputs = (read_json(receipt_path).get("outputs") or {})
            if outputs.get("campaign_ledger"):
                campaigns.append(outputs)
                seen_ledgers.add(outputs["campaign_ledger"]["path"])
        if s_outputs["campaign_ledger"]["path"] not in seen_ledgers:
            campaigns.append(s_outputs)
        representatives: list[dict[str, Any]] = []
        preserved: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        representative_by_sha: dict[str, dict[str, Any]] = {}
        for stage_attempt_index, campaign in enumerate(campaigns):
            ledger_path = Path(campaign["campaign_ledger"]["path"])
            if sha256(ledger_path) != campaign["campaign_ledger"]["sha256"]:
                raise PipelineError("evidence_identity_failed", "S ledger changed")
            ledger = read_json(ledger_path)
            root = safe_owned_directory(Path(campaign["campaign_output"]), self.output,
                                        "S campaign output")
            for attempt in ledger.get("attempts", []):
                for index, candidate in enumerate(attempt.get("candidates", [])):
                    path = safe_owned(Path(candidate["path"]), root, "candidate")
                    digest = candidate.get("sha256")
                    if not SHA_RE.match(str(digest)) or sha256(path) != digest:
                        raise PipelineError("evidence_identity_failed", "candidate SHA differs")
                    row = {"preserved_order": len(preserved),
                           "s_stage_attempt_index": stage_attempt_index,
                           "attempt_index": attempt["attempt_index"],
                           "candidate_index": index, "target_id": attempt["target_id"],
                           "seed": attempt["seed"], "path": str(path), "sha256": digest,
                           "duplicate_of": candidate.get("duplicate_of")}
                    preserved.append(row)
                    representative = representative_by_sha.get(digest)
                    if representative is None and candidate.get("duplicate_of") is None:
                        representative = {**row, "order": len(representatives)}
                        representatives.append(representative)
                        representative_by_sha[digest] = representative
                    else:
                        if representative is None:
                            raise PipelineError("evidence_identity_failed",
                                                "duplicate candidate has no earlier representative")
                        duplicates.append({
                            **row, "disposition": "merged_with_representative",
                            "representative_reference": {
                                "order": representative["order"],
                                "sha256": representative["sha256"],
                                "path": representative["path"],
                            },
                        })
        return {
            "schema": "zkfdo-sj-candidate-inventory-v1",
            "order_policy": "first_unique_candidates_in_campaign_ledger_order",
            "order_basis": ["S stage attempt order", "S campaign attempt order",
                            "candidate order within attempt"],
            "preserved": preserved, "representatives": representatives,
            "merged_duplicates": duplicates,
            "diagnostic_limit": self.args.j_candidates,
        }

    def selected_candidates(self, s_outputs: dict[str, Any]) -> list[dict[str, Any]]:
        return self.candidate_inventory(s_outputs)["representatives"]

    def _binding_map(self, preparation: dict[str, Any]) -> dict[str, dict[str, Any]]:
        bindings = {row["target_id"]: row for row in preparation["bindings"]}
        if len(bindings) != len(preparation["bindings"]):
            raise PipelineError("preparation_identity_failed", "duplicate prepared target identifier")
        return bindings

    def _j_request(self, candidate: dict[str, Any], binding: dict[str, Any], request_id: str) -> dict[str, Any]:
        wrapper = safe_owned(Path(binding["wrapper"]), self.source_root, "component wrapper")
        prepared_sources = Path(binding["sources"]).resolve()
        if not prepared_sources.is_dir() or not prepared_sources.is_relative_to(self.source_root):
            raise PipelineError("preparation_identity_failed", "prepared source root differs")
        if (sha256(wrapper) != binding["wrapper_sha256"]
                or policy_v1.tree_sha256(prepared_sources) != binding["sources_tree_sha256"]):
            raise PipelineError("preparation_identity_failed", "prepared source identity differs")
        libraries = []
        for path in [prepared_sources, *self.library_paths]:
            if path not in libraries:
                libraries.append(path)
        return {
            "schema": "zkfdo-lifting-request-v1",
            "id": request_id,
            "source_root": str(self.source_root),
            "library_paths": [str(path) for path in libraries],
            "component_wrapper": str(wrapper),
            "entrypoint": str(self.entrypoint),
            "base_input": str(self.base_input),
            "candidate": {"format": "zkfuzz", "path": candidate["path"]},
        }

    def _pre_j_identity(self, binding: dict[str, Any], request_id: str) -> dict[str, Any]:
        source = self.verify_pinned_source(f"immediately_before_{request_id}")
        layout = self.prepared_binding_layout(binding, compare_saved=True)
        return {"schema": "zkfdo-sj-pre-j-identity-v1", "request_id": request_id,
                "utc": utc(), "source": source, "component_closure": layout,
                "normalized_base_input_sha256": sha256(self.base_input)}

    def _validate_probe_contract(self, request_sha: str, candidate: dict[str, Any],
                                 result: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
        entrypoint = result.get("entrypoint") or {}
        identity = probe.get("identity") or {}
        expected_policy = ("all" if self.args.probe_classes == "all"
                           else "unknown_or_excluded_in_context")
        required_top = {
            "schema": "zkfdo-site-signal-probe-v1", "enabled": True,
            "budget_seconds": self.args.probe_seconds, "classes_policy": expected_policy,
            "value_policy": PROBE_VALUE_POLICY, "contract": PROBE_CONTRACT,
            "repair_attempts": 0, "request_sha256": request_sha,
            "candidate_sha256": candidate["sha256"],
        }
        for key, expected in required_top.items():
            if probe.get(key) != expected:
                raise PipelineError("probe_result_invalid", f"probe field differs: {key}")
        required_identity = {
            "request_sha256": request_sha, "candidate_sha256": candidate["sha256"],
            "budget_seconds": self.args.probe_seconds, "value_policy": PROBE_VALUE_POLICY,
            "contract": PROBE_CONTRACT, "predicate": PROBE_PREDICATE,
            "base_input_sha256": sha256(self.base_input),
        }
        for key, expected in required_identity.items():
            if identity.get(key) != expected:
                raise PipelineError("probe_result_invalid", f"probe identity differs: {key}")
        original = probe.get("original") or {}
        if (original.get("original_r1cs_sha256") != entrypoint.get("r1cs_sha256")
                or original.get("original_sym_sha256") != entrypoint.get("sym_sha256")):
            raise PipelineError("probe_result_invalid", "probe original artifact identity differs")
        result_classes = result.get("classes") or []
        probe_classes = probe.get("classes") or []
        seen_indices: set[int] = set()
        for class_row in probe_classes:
            index = class_row.get("class_index")
            if (isinstance(index, bool) or not isinstance(index, int) or index < 0
                    or index in seen_indices):
                raise PipelineError("probe_result_invalid", "probe class index differs")
            seen_indices.add(index)
            if index >= len(result_classes):
                raise PipelineError("probe_result_invalid", "probe class is absent from J result")
            result_class = result_classes[index]
            expected_class = {"pattern": result_class.get("pattern"),
                              "representative": result_class.get("representative"),
                              "existing_verdict": result_class.get("verdict")}
            for key, expected in expected_class.items():
                if class_row.get(key) != expected:
                    raise PipelineError("probe_result_invalid", f"probe class field differs: {key}")
            class_identity = class_row.get("identity") or {}
            for key, expected in required_identity.items():
                if class_identity.get(key) != expected:
                    raise PipelineError("probe_result_invalid",
                                        f"probe class identity differs: {key}")
            for probe_attempt in class_row.get("attempts") or []:
                if probe_attempt.get("repair_attempts") != 0:
                    raise PipelineError("probe_result_invalid", "probe attempt used repair")
                attempt_identity = probe_attempt.get("identity") or {}
                for key, expected in required_identity.items():
                    if attempt_identity.get(key) != expected:
                        raise PipelineError("probe_result_invalid",
                                            f"probe attempt identity differs: {key}")
                if probe_attempt.get("status") in ("positive", "verified_output_identical"):
                    evidence = probe_attempt.get("evidence") or {}
                    for key in ("comparator_wtns_sha256", "deviated_wtns_sha256"):
                        if not SHA_RE.match(str(evidence.get(key))):
                            raise PipelineError("evidence_identity_failed",
                                                f"probe evidence is missing {key}")
                    if (evidence.get("original_r1cs_sha256") != entrypoint.get("r1cs_sha256")
                            or evidence.get("original_sym_sha256") != entrypoint.get("sym_sha256")):
                        raise PipelineError("probe_result_invalid",
                                            "probe attempt original artifact identity differs")
        if seen_indices != set(range(len(result_classes))):
            raise PipelineError("probe_result_invalid", "probe class coverage differs from J result")
        return {"schema": "zkfdo-sj-probe-contract-check-v1", "status": "validated",
                "base_input_sha256": required_identity["base_input_sha256"],
                "original_r1cs_sha256": entrypoint.get("r1cs_sha256"),
                "original_sym_sha256": entrypoint.get("sym_sha256"),
                "budget_seconds": self.args.probe_seconds,
                "classes_policy": expected_policy, "value_policy": PROBE_VALUE_POLICY,
                "contract": PROBE_CONTRACT, "repair_attempts": 0}

    def _write_request_receipt(self, record: dict[str, Any]) -> dict[str, Any]:
        path = Path(record["directory"]) / "terminal-receipt.json"
        snapshot = {key: value for key, value in record.items() if key != "terminal_receipt"}
        if path.exists():
            if path.is_symlink() or read_json(path) != snapshot:
                raise PipelineError("request_history_mismatch", "request terminal receipt differs")
        else:
            exclusive_json(path, snapshot)
        reference = {"path": str(path), "sha256": sha256(path)}
        record["terminal_receipt"] = reference
        return reference

    def j_requests_stage(self, preparation: dict[str, Any], s_outputs: dict[str, Any]) -> dict[str, Any]:
        with stage_attempt(self, "j_requests") as row:
            if row is None:
                return self.ledger["stages"]["j_requests"]["outputs"]
            attempt = Path(row["directory"])
            inventory = self.candidate_inventory(s_outputs)
            inventory_path = self.output / "candidate-ledger/inventory.json"
            if inventory_path.exists():
                if inventory_path.is_symlink() or read_json(inventory_path) != inventory:
                    raise PipelineError("resume_identity_mismatch", "candidate inventory changed")
            else:
                exclusive_json(inventory_path, inventory)
            selected = inventory["representatives"]
            states = self.initialize_candidate_states(selected)
            bindings = self._binding_map(preparation)
            requests = [request for state in states for request in state.get("attempts", [])]
            diagnostic_limit = self.args.j_candidates
            scheduled_scope = (len(selected) if diagnostic_limit is None
                               else min(len(selected), diagnostic_limit))
            outputs = {
                "selected_candidates": {"path": str(inventory_path),
                                        "sha256": sha256(inventory_path)},
                "total_candidate_count": len(selected),
                "selected_count": scheduled_scope,
                "diagnostic_candidate_limit": diagnostic_limit,
                "diagnostic_limit_active": diagnostic_limit is not None,
                "requested_count": len(requests),
                "completed_count": 0, "judged_count": 0,
                "in_progress_interrupted_count": 0, "pending_not_run_count": 0,
                "requests": requests,
                "order_policy": "first_unique_candidates_in_campaign_ledger_order",
                "order_basis": inventory["order_basis"],
                "merged_duplicates": inventory["merged_duplicates"],
                "j_jobs": 1,
                "j_base_budget_seconds": self.args.j_total_seconds,
                "j_allocated_seconds": self.ledger["budget_accounting"]["j"]["allocated_seconds"],
                "j_command_wall_seconds": self.ledger["budget_accounting"]["j"]["consumed_seconds"],
                "j_budget_remaining_seconds": self.j_budget_remaining(),
                "budget_events": self.ledger["budget_accounting"]["j"]["events"],
                "request_postcheck_costs": {"wall_seconds": 0.0, "cpu_seconds": 0.0},
            }
            row["outputs"] = outputs

            def save_requests() -> None:
                outputs["requested_count"] = len(requests)
                counts = Counter(state["state"] for state in states)
                outputs["judged_count"] = counts["judged"]
                outputs["completed_count"] = counts["judged"]
                outputs["in_progress_interrupted_count"] = counts["in_progress_interrupted"]
                outputs["pending_not_run_count"] = counts["pending_not_run"]
                outputs["candidate_status"] = {
                    "total": len(states), "judged": counts["judged"],
                    "in_progress_interrupted": counts["in_progress_interrupted"],
                    "pending_not_run": counts["pending_not_run"],
                }
                outputs["j_allocated_seconds"] = self.ledger["budget_accounting"]["j"]["allocated_seconds"]
                outputs["j_command_wall_seconds"] = self.ledger["budget_accounting"]["j"]["consumed_seconds"]
                outputs["j_budget_remaining_seconds"] = self.j_budget_remaining()
                outputs["budget_events"] = self.ledger["budget_accounting"]["j"]["events"]
                postchecks = [request.get("postcheck") or {} for request in requests]
                outputs["request_postcheck_costs"] = {
                    "wall_seconds": sum(float(item.get("wall_seconds") or 0)
                                        for item in postchecks),
                    "cpu_seconds": sum(float(item.get("cpu_seconds") or 0)
                                       for item in postchecks),
                }
                current_postchecks = [
                    request.get("postcheck") or {} for request in requests
                    if request.get("stage_attempt_directory") == str(attempt)
                ]
                row["embedded_postcheck_wall_seconds"] = sum(
                    float(item.get("wall_seconds") or 0) for item in current_postchecks)
                row["embedded_postcheck_cpu_seconds"] = sum(
                    float(item.get("cpu_seconds") or 0) for item in current_postchecks)
                self.checkpoint()

            def finish_request(state: dict[str, Any], record: dict[str, Any], *,
                               candidate_state: str, status: str,
                               terminal_status: str, reason: str) -> None:
                record.update(status=status, terminal_status=terminal_status, reason=reason,
                              finished_utc=utc())
                if "cache_cleanup" not in record:
                    record["cache_cleanup"] = {
                        "status": "retained_for_recovery",
                        "reason": "cache is retained until preservation and interpretation complete",
                    }
                self._write_request_receipt(record)
                self.candidate_event(
                    state, candidate_state, terminal_status,
                    request_id=record["request_id"], request_attempt=record["request_attempt"],
                    request_receipt=record["terminal_receipt"], reason=reason)
                save_requests()

            save_requests()
            for state in states:
                index = state["candidate_index"]
                candidate = state["candidate"]
                if state["state"] == "judged":
                    continue
                if diagnostic_limit is not None and index >= diagnostic_limit:
                    continue
                remaining = self.j_budget_remaining()
                if remaining <= 0:
                    break
                candidate_remaining = max(
                    0.0, self.args.j_request_seconds - self.candidate_budget_consumed(state))
                if candidate_remaining <= 0:
                    self.candidate_event(
                        state, "judged", "candidate_budget_exhausted",
                        reason="candidate cumulative request budget is exhausted")
                    save_requests()
                    continue
                request_attempt = len(state.get("attempts", [])) + 1
                request_id = f"candidate-{index:06d}-attempt-{request_attempt:04d}"
                request_root = attempt / "requests" / f"{index:06d}-{request_attempt:04d}"
                request_root.mkdir(parents=True, exist_ok=False)
                record: dict[str, Any] = {
                    "index": index, "request_attempt": request_attempt,
                    "request_id": request_id,
                    "candidate": candidate,
                    "directory": str(request_root),
                    "stage_attempt_directory": str(attempt),
                    "status": "running", "terminal_status": "in_progress_interrupted",
                    "started_utc": utc(),
                }
                state.setdefault("attempts", []).append(record)
                state["latest_request"] = record
                requests.append(record)
                self.candidate_event(state, "in_progress_interrupted", "request_started",
                                     request_id=request_id, request_attempt=request_attempt)
                save_requests()
                binding = bindings.get(candidate["target_id"])
                if binding is None:
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status="preparation_identity_failed",
                                   reason="candidate target has no preparation binding")
                    continue
                try:
                    record["disk_gate"] = disk_gate(
                        self.output, int(self.args.run_min_free_gib * GIB))
                except PipelineError as error:
                    finish_request(state, record, candidate_state="pending_not_run",
                                   status="not_started", terminal_status=error.status,
                                   reason=str(error))
                    break
                try:
                    record["tool_identity"] = self.verify_tool_identities(
                        (self.j_name, "circom", "node", "snarkjs", "z3"))
                except PipelineError as error:
                    finish_request(state, record, candidate_state="pending_not_run",
                                   status="not_started", terminal_status=error.status,
                                   reason=str(error))
                    break
                try:
                    pre_identity = self._pre_j_identity(binding, request_id)
                except PipelineError as error:
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status=error.status, reason=str(error))
                    continue
                pre_identity_path = request_root / "pre-j-identity.json"
                exclusive_json(pre_identity_path, pre_identity)
                record["pre_j_identity"] = {"path": str(pre_identity_path),
                                            "sha256": sha256(pre_identity_path)}
                request = self._j_request(candidate, binding, request_id)
                request_path = request_root / "request.json"
                atomic_json(request_path, request)
                output = request_root / "out"
                cache = request_root / "cache"
                store = request_root / "instance-store"
                timeout = min(candidate_remaining, remaining)
                argv = [
                    self.tool(self.j_name), "--request", request_path, "--output", output,
                    "--cache", cache, "--instance-store", store,
                    "--circom-bin", self.tool("circom"), "--node-bin", self.tool("node"),
                    "--snarkjs-bin", self.tool("snarkjs"), "--z3-bin", self.tool("z3"),
                    "--j-jobs", "1", "--site-signal-probe",
                    "--site-signal-probe-classes", self.args.probe_classes,
                    "--site-signal-probe-seconds", str(self.args.probe_seconds),
                ]
                self.mark_started()
                try:
                    command = self.runner.run("j_requests", request_id, argv, request_root / "command",
                                              timeout, cwd=ROOT, disk_path=self.output,
                                              minimum_free_bytes=int(self.args.run_min_free_gib * GIB))
                except BaseException as error:
                    command_row = next((item for item in reversed(self.ledger.get("commands", []))
                                        if item.get("label") == request_id), None)
                    if command_row is not None and not record.get("budget_charge"):
                        record["budget_charge"] = self.charge_budget(
                            "j", float(command_row.get("wall_seconds") or 0), request_id,
                            {"command_argv_sha256": command_row.get("argv_sha256")},
                            charge_id=f"j-request:{request_id}")
                    finish_request(state, record, candidate_state="in_progress_interrupted",
                                   status="interrupted", terminal_status="j_request_interrupted",
                                   reason=f"{type(error).__name__}: {error}")
                    raise
                record["budget_charge"] = self.charge_budget(
                    "j", float(command.get("wall_seconds") or 0), request_id,
                    {"command_argv_sha256": command.get("argv_sha256")},
                    charge_id=f"j-request:{request_id}")
                record["command"] = {key: command.get(key) for key in (
                    "status", "returncode", "wall_seconds", "cpu_seconds", "argv_sha256",
                    "termination", "termination_reason", "executable"
                )}
                if command["status"] == "timeout":
                    candidate_exhausted = (
                        self.candidate_budget_consumed(state) + 1e-9
                        >= self.args.j_request_seconds)
                    finish_request(
                        state, record,
                        candidate_state="judged" if candidate_exhausted else "in_progress_interrupted",
                        status="failed" if candidate_exhausted else "interrupted",
                        terminal_status="j_timeout",
                        reason="J request was interrupted before a terminal result")
                    if candidate_exhausted:
                        continue
                    break
                if command["status"] in ("disk_floor", "interrupted"):
                    finish_request(
                        state, record, candidate_state="in_progress_interrupted",
                        status="interrupted", terminal_status=f"j_{command['status']}",
                        reason="J request was interrupted before a terminal result")
                    break
                result_path = output / "result.json"
                probe_path = output / "site-signal-probe.json"
                if command["status"] != "completed":
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status="j_command_failed",
                                   reason="J command failed before a terminal result; cache retained")
                    continue
                if not result_path.is_file():
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status="j_result_missing",
                                   reason="J command completed but result evidence is absent; cache retained")
                    continue
                try:
                    result = read_json(result_path)
                except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status="j_result_invalid",
                                   reason=f"post-command result interpretation failed: {type(error).__name__}: {error}")
                    continue
                if result.get("schema") != "zkfdo-lifting-result-v2.8":
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status="j_result_invalid",
                                   reason="unexpected J result schema; cache retained")
                    continue
                request_sha = sha256(request_path)
                if (result.get("request_id") != request_id or result.get("request_sha256") != request_sha
                        or result.get("candidate_sha256") != candidate["sha256"]):
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status="j_result_invalid",
                                   reason="J result request or candidate identity differs; cache retained")
                    continue
                baseline = self.ledger["stages"].get("baseline", {}).get("outputs") or {}
                baseline_sha = (baseline.get("r1cs") or {}).get("sha256")
                if (not SHA_RE.match(str(baseline_sha))
                        or (result.get("entrypoint") or {}).get("o0_r1cs_sha256") != baseline_sha):
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status="o0_r1cs_identity_mismatch",
                                   reason="J O0 R1CS differs from the independent baseline; cache retained")
                    continue
                if not probe_path.is_file():
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status="probe_result_missing",
                                   reason="probe sidecar is absent after command completion; cache retained")
                    continue
                try:
                    probe = read_json(probe_path)
                except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status="probe_result_invalid",
                                   reason=f"post-command probe interpretation failed: {type(error).__name__}: {error}")
                    continue
                try:
                    probe_contract = self._validate_probe_contract(
                        request_sha, candidate, result, probe)
                except PipelineError as error:
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status=error.status,
                                   reason=f"probe contract validation failed: {error}; cache retained")
                    continue
                try:
                    pair_evidence = self._bind_pair_evidence(record, output, result, probe)
                except (OSError, ValueError, KeyError, TypeError, PipelineError) as error:
                    finish_request(state, record, candidate_state="judged", status="failed",
                                   terminal_status=getattr(error, "status", "evidence_identity_failed"),
                                   reason=f"pair evidence binding failed: {error}; cache retained")
                    continue
                record.update(
                    status="completed",
                    terminal_status="completed",
                    request={"path": str(request_path), "sha256": request_sha},
                    result={"path": str(result_path), "sha256": sha256(result_path)},
                    probe={"path": str(probe_path), "sha256": sha256(probe_path)},
                    verdict_counts=result.get("verdict_counts", {}),
                    preparation=result.get("preparation", {}),
                    probe_status=probe.get("status"),
                    probe_contract=probe_contract,
                    pair_evidence=pair_evidence,
                )
                save_requests()
                try:
                    postcheck = self._postcheck_request(record, save_requests)
                except BaseException as error:
                    finish_request(state, record, candidate_state="in_progress_interrupted",
                                   status="interrupted", terminal_status="postcheck_interrupted",
                                   reason=f"{type(error).__name__}: {error}")
                    raise
                record["postcheck_status"] = postcheck["status"]
                finish_request(state, record, candidate_state="judged", status="completed",
                               terminal_status=postcheck["check"]["terminal_status"],
                               reason="J result and request postcheck reached a terminal state")
            save_requests()
            if any(state["state"] != "judged" for state in states):
                row["terminal_status"] = "candidates_pending"
                outputs["pipeline_status"] = "partial:candidates_pending"
            else:
                outputs["pipeline_status"] = "completed"
            return outputs

    def _owned_request_root(self, request: dict[str, Any]) -> Path:
        stage = self.ledger.get("stages", {}).get("j_requests") or {}
        stage_dir = Path(request.get("stage_attempt_directory") or stage.get("directory", ""))
        safe_owned_directory(stage_dir, self.output, "J stage directory")
        attempts_root = self.output / "stage-records/j_requests/attempts"
        safe_owned_directory(attempts_root, self.output, "J attempts directory")
        if not stage_dir.resolve().is_relative_to(attempts_root.resolve()):
            raise PipelineError("output_ownership_failed", "J stage attempt escapes history")
        requests_root = stage_dir / "requests"
        safe_owned_directory(requests_root, stage_dir, "J requests directory")
        index = request.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise PipelineError("output_ownership_failed", "J request index differs")
        request_attempt = request.get("request_attempt")
        expected = (requests_root / f"{index:06d}-{request_attempt:04d}"
                    if isinstance(request_attempt, int) and not isinstance(request_attempt, bool)
                    else requests_root / f"{index:02d}")
        actual = Path(request.get("directory", ""))
        if actual != expected:
            raise PipelineError("output_ownership_failed", "J request directory differs")
        safe_owned_directory(actual, requests_root, "J request directory")
        return actual

    def _original_artifacts(self, request: dict[str, Any], result: dict[str, Any],
                            probe: dict[str, Any]) -> dict[str, Any]:
        request_root = self._owned_request_root(request)
        entrypoint = result.get("entrypoint") or {}
        expected_r1cs = entrypoint.get("r1cs_sha256")
        expected_sym = entrypoint.get("sym_sha256")
        if not SHA_RE.match(str(expected_r1cs)) or not SHA_RE.match(str(expected_sym)):
            raise PipelineError("original_identity_missing", "J result has no original artifact identity")
        originals = self.output / "originals"
        if originals.exists():
            safe_owned_directory(originals, self.output, "originals directory")
        else:
            originals.mkdir()
        destination = originals / f"{expected_r1cs}-{expected_sym}"
        if destination.exists():
            safe_owned_directory(destination, originals, "original artifact directory")
        else:
            destination.mkdir()
        preserved_r1cs = destination / "original.r1cs"
        preserved_sym = destination / "original.sym"
        identity_path = destination / "identity.json"
        if preserved_r1cs.is_file() and preserved_sym.is_file() and identity_path.is_file():
            if (sha256(preserved_r1cs) != expected_r1cs or sha256(preserved_sym) != expected_sym
                    or read_json(identity_path).get("schema") != "zkfdo-sj-original-v1"):
                raise PipelineError("original_identity_failed", "preserved original identity differs")
            return {"r1cs": {"path": str(preserved_r1cs), "sha256": expected_r1cs,
                              "bytes": preserved_r1cs.stat().st_size},
                    "sym": {"path": str(preserved_sym), "sha256": expected_sym,
                            "bytes": preserved_sym.stat().st_size},
                    "identity": {"path": str(identity_path), "sha256": sha256(identity_path)}}
        original = probe.get("original") or {}
        pair: tuple[Path, Path] | None = None
        if original.get("original_r1cs") and original.get("original_sym"):
            candidate_r1cs = safe_owned(Path(original["original_r1cs"]), request_root, "original R1CS")
            candidate_sym = safe_owned(Path(original["original_sym"]), request_root, "original SYM")
            pair = (candidate_r1cs, candidate_sym)
        if pair is None:
            roots = [request_root / "cache", request_root / "instance-store"]
            owned_roots = [safe_owned_directory(root, request_root, "J artifact directory")
                           for root in roots if root.exists()]
            r1cs = [safe_owned(path, request_root, "original R1CS")
                    for root in owned_roots for path in root.rglob("*.r1cs")
                    if path.is_file() and not path.is_symlink() and sha256(path) == expected_r1cs]
            sym = [safe_owned(path, request_root, "original SYM")
                   for root in owned_roots for path in root.rglob("*.sym")
                   if path.is_file() and not path.is_symlink() and sha256(path) == expected_sym]
            if not r1cs or not sym:
                raise PipelineError("original_artifacts_missing", "original R1CS or SYM is unavailable")
            pair = (sorted(set(r1cs), key=str)[0], sorted(set(sym), key=str)[0])
        r1cs_path, sym_path = pair
        if sha256(r1cs_path) != expected_r1cs or sha256(sym_path) != expected_sym:
            raise PipelineError("original_identity_failed", "original artifact SHA differs")
        preserved_r1cs = copy_verified(r1cs_path, destination / "original.r1cs", expected_r1cs)
        preserved_sym = copy_verified(sym_path, destination / "original.sym", expected_sym)
        identity = {"schema": "zkfdo-sj-original-v1", "r1cs": preserved_r1cs, "sym": preserved_sym}
        identity_path = destination / "identity.json"
        if identity_path.exists() and read_json(identity_path) != identity:
            raise PipelineError("original_identity_failed", "preserved original identity differs")
        atomic_json(identity_path, identity)
        return {"r1cs": preserved_r1cs, "sym": preserved_sym,
                "identity": {"path": str(identity_path), "sha256": sha256(identity_path)}}

    def _snarkjs_check(self, stage_dir: Path, label: str, r1cs: Path, witness: Path) -> dict[str, Any]:
        command = self.runner.run("postcheck", label,
                                  [self.tool("snarkjs"), "wtns", "check", r1cs, witness],
                                  stage_dir, self.args.postcheck_seconds, cwd=ROOT)
        log = Path(command["stdout_log"]["path"]) if command.get("stdout_log") else None
        passed = (command["status"] == "completed" and log is not None
                  and any(marker in log.read_text(errors="replace") for marker in SNARKJS_MARKERS))
        return {"passed": passed, "command_status": command["status"],
                "witness": {"path": str(witness), "sha256": sha256(witness)}}

    def _check_pair(self, attempt: Path, label: str, r1cs: Path,
                    comparator: Path, deviated: Path, expected_output_difference: bool,
                    comparator_sha256: str | None = None,
                    deviated_sha256: str | None = None,
                    evidence_root: Path | None = None) -> dict[str, Any]:
        owned_root = self.output if evidence_root is None else evidence_root
        comparator = safe_owned(comparator, owned_root, "comparator witness")
        deviated = safe_owned(deviated, owned_root, "deviated witness")
        if not SHA_RE.match(str(comparator_sha256)) or sha256(comparator) != comparator_sha256:
            raise PipelineError("evidence_identity_failed", "comparator witness SHA differs")
        if not SHA_RE.match(str(deviated_sha256)) or sha256(deviated) != deviated_sha256:
            raise PipelineError("evidence_identity_failed", "deviated witness SHA differs")
        first = self._snarkjs_check(attempt / f"{label}-comparator", f"{label}-comparator", r1cs, comparator)
        second = self._snarkjs_check(attempt / f"{label}-deviated", f"{label}-deviated", r1cs, deviated)
        comparison = compare_pair(r1cs, comparator, deviated)
        passed = (first["passed"] and second["passed"] and comparison["same_full_input"]
                  and comparison["outputs_differ"] == expected_output_difference)
        return {"status": "validated" if passed else "external_check_failed", "passed": passed,
                "expected_output_difference": expected_output_difference,
                "comparator_check": first, "deviated_check": second, "comparison": comparison}

    def _bind_pair_evidence(self, request: dict[str, Any], output: Path,
                            result: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
        request_root = self._owned_request_root(request)
        output = safe_owned_directory(output, request_root, "J output")
        rows: list[dict[str, Any]] = []

        def witness(path: Path, expected_sha: str, label: str) -> dict[str, Any]:
            path = safe_owned(path, request_root, label)
            if not SHA_RE.match(str(expected_sha)) or sha256(path) != expected_sha:
                raise PipelineError("evidence_identity_failed", f"{label} SHA differs")
            return {"path": str(path), "sha256": expected_sha}

        for index, class_row in enumerate(result.get("classes", [])):
            if class_row.get("verdict") != "entrypoint_violation":
                continue
            directory = output / "raw" / f"site-{index:03d}"
            comparator = safe_owned(directory / "honest.wtns", request_root,
                                    "normal comparator witness")
            comparator_sha = sha256(comparator)
            evidence = class_row.get("evidence") or {}
            rows.append({
                "kind": "entrypoint_violation", "class_index": index,
                "attempt_index": None, "label": f"normal-{index:03d}",
                "expected_output_difference": True,
                "comparator": witness(comparator, comparator_sha, "normal comparator witness"),
                "deviated": witness(directory / "deviated.wtns",
                                     evidence.get("deviated_wtns_sha256"),
                                     "normal deviated witness"),
            })
        for class_row in probe.get("classes", []):
            for attempt_index, probe_attempt in enumerate(class_row.get("attempts", [])):
                status = probe_attempt.get("status")
                if status not in ("positive", "verified_output_identical"):
                    continue
                evidence = probe_attempt.get("evidence") or {}
                rows.append({
                    "kind": f"probe_{status}",
                    "class_index": class_row.get("class_index"),
                    "attempt_index": attempt_index,
                    "label": f"probe-{class_row.get('class_index', 0):03d}-{attempt_index:03d}",
                    "expected_output_difference": status == "positive",
                    "comparator": witness(Path(evidence.get("comparator_wtns", "")),
                                          evidence.get("comparator_wtns_sha256"),
                                          "probe comparator witness"),
                    "deviated": witness(Path(evidence.get("deviated_wtns", "")),
                                        evidence.get("deviated_wtns_sha256"),
                                        "probe deviated witness"),
                })
        data = {"schema": "zkfdo-sj-pair-evidence-v1",
                "request_id": request["request_id"], "bound_utc": utc(), "pairs": rows}
        path = request_root / "pair-evidence.json"
        exclusive_json(path, data)
        return {"path": str(path), "sha256": sha256(path), "pair_count": len(rows)}

    def _bound_pairs(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        request_root = self._owned_request_root(request)
        reference = request.get("pair_evidence") or {}
        path = Path(reference.get("path", ""))
        if path != request_root / "pair-evidence.json":
            raise PipelineError("evidence_identity_failed", "pair evidence path differs")
        path = safe_owned(path, request_root, "pair evidence")
        if sha256(path) != reference.get("sha256"):
            raise PipelineError("evidence_identity_failed", "pair evidence receipt differs")
        data = read_json(path)
        if (data.get("schema") != "zkfdo-sj-pair-evidence-v1"
                or data.get("request_id") != request["request_id"]
                or len(data.get("pairs") or []) != reference.get("pair_count")):
            raise PipelineError("evidence_identity_failed", "pair evidence identity differs")
        pairs = []
        for row in data.get("pairs") or []:
            comparator = row.get("comparator") or {}
            deviated = row.get("deviated") or {}
            pairs.append({
                "kind": row.get("kind"), "class_index": row.get("class_index"),
                "attempt_index": row.get("attempt_index"), "label": row.get("label"),
                "expected_output_difference": row.get("expected_output_difference"),
                "comparator": Path(comparator.get("path", "")),
                "deviated": Path(deviated.get("path", "")),
                "comparator_sha256": comparator.get("sha256"),
                "deviated_sha256": deviated.get("sha256"),
            })
        return pairs

    def _cleanup_cache(self, request: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        request_root = self._owned_request_root(request)
        cache = request_root / "cache"
        cleanup_path = request_root / "cache-cleanup.json"
        if cache.is_symlink():
            raise PipelineError("cache_ownership_failed", "request cache is a symlink")
        if not cache.exists():
            if cleanup_path.is_file() and not cleanup_path.is_symlink():
                cleanup = read_json(cleanup_path)
                if cleanup.get("path") != str(cache) or cleanup.get("status") != "removed":
                    raise PipelineError("cache_ownership_failed", "cache cleanup receipt differs")
                cleanup = {**cleanup, "resume_status": "already_absent",
                           "receipt": {"path": str(cleanup_path),
                                       "sha256": sha256(cleanup_path)}}
            else:
                cleanup = {"status": "already_absent", "path": str(cache), "utc": utc()}
            record["cache_cleanup"] = cleanup
            return cleanup
        safe_owned_directory(cache, request_root, "request cache")
        before = sum(path.stat().st_size for path in cache.rglob("*")
                     if path.is_file() and not path.is_symlink())
        shutil.rmtree(cache)
        cleanup = {"status": "removed", "path": str(cache), "bytes_before": before, "utc": utc()}
        atomic_json(cleanup_path, cleanup)
        recorded = {**cleanup, "receipt": {"path": str(cleanup_path),
                                           "sha256": sha256(cleanup_path)}}
        record["cache_cleanup"] = recorded
        return recorded

    def _validate_cache_state(self, request: dict[str, Any]) -> None:
        request_root = self._owned_request_root(request)
        cache = request_root / "cache"
        cleanup = request.get("cache_cleanup") or {}
        status = cleanup.get("status")
        if status in ("removed", "already_absent"):
            if cache.exists() or cache.is_symlink():
                raise PipelineError("cache_cleanup_identity_failed", "cleaned request cache exists")
            receipt = cleanup.get("receipt")
            if status == "removed" or receipt is not None:
                if not isinstance(receipt, dict):
                    raise PipelineError("cache_cleanup_identity_failed", "cache receipt is absent")
                path = Path(receipt.get("path", ""))
                if path != request_root / "cache-cleanup.json":
                    raise PipelineError("cache_cleanup_identity_failed", "cache receipt path differs")
                path = safe_owned(path, request_root, "cache cleanup receipt")
                if sha256(path) != receipt.get("sha256"):
                    raise PipelineError("cache_cleanup_identity_failed", "cache receipt SHA differs")
                saved = read_json(path)
                if saved.get("status") != "removed" or saved.get("path") != str(cache):
                    raise PipelineError("cache_cleanup_identity_failed", "cache receipt content differs")
            return
        if status == "retained_for_recovery":
            if cache.exists():
                safe_owned_directory(cache, request_root, "retained request cache")
            return
        if status == "failed":
            return
        raise PipelineError("cache_cleanup_identity_failed", "request cache terminal state is absent")

    def _finish_request_postcheck(self, request: dict[str, Any], request_check: dict[str, Any],
                                  validated: list[dict[str, Any]], status: str,
                                  started: float, cpu_started: float,
                                  checkpoint: Callable[[], None]) -> dict[str, Any]:
        request_root = self._owned_request_root(request)
        data = {
            "schema": "zkfdo-sj-request-postcheck-v1",
            "request_id": request["request_id"],
            "status": status,
            "check": request_check,
            "validated_counterexamples": validated,
            "costs": {"wall_seconds": time.monotonic() - started,
                      "cpu_seconds": time.process_time() - cpu_started},
        }
        path = request_root / "postcheck.json"
        atomic_json(path, data)
        request["postcheck"] = {
            "path": str(path), "sha256": sha256(path), "status": status,
            "terminal_status": request_check["terminal_status"], **data["costs"],
        }
        request["cache_cleanup"] = request_check.get("cache_cleanup")
        request.pop("postcheck_progress", None)
        checkpoint()
        return data

    def _postcheck_request(self, request: dict[str, Any],
                           checkpoint: Callable[[], None]) -> dict[str, Any]:
        started, cpu_started = time.monotonic(), time.process_time()
        request_check: dict[str, Any] = {
            "request_id": request["request_id"], "request_status": request["status"],
            "terminal_status": "postcheck_running", "pairs": [],
        }
        validated: list[dict[str, Any]] = []
        request["postcheck_progress"] = {
            "status": "running", "check": request_check,
            "validated_counterexamples": validated,
        }
        checkpoint()

        def finish(status: str) -> dict[str, Any]:
            return self._finish_request_postcheck(
                request, request_check, validated, status, started, cpu_started, checkpoint)

        try:
            try:
                request_root = self._owned_request_root(request)
                result_path = Path(request["result"]["path"])
                probe_path = Path(request["probe"]["path"])
                if (result_path != request_root / "out/result.json"
                        or probe_path != request_root / "out/site-signal-probe.json"):
                    raise PipelineError("evidence_identity_failed", "J result path differs")
                result_path = safe_owned(result_path, request_root, "J result")
                probe_path = safe_owned(probe_path, request_root, "probe result")
                if (sha256(result_path) != request["result"]["sha256"]
                        or sha256(probe_path) != request["probe"]["sha256"]):
                    raise PipelineError("evidence_identity_failed",
                                        "J result or probe changed before postcheck")
                result, probe = read_json(result_path), read_json(probe_path)
            except (OSError, ValueError, KeyError, TypeError, PipelineError,
                    json.JSONDecodeError) as error:
                request_check.update(
                    terminal_status=getattr(error, "status", "evidence_identity_failed"),
                    reason=f"{type(error).__name__}: {error}",
                    cache_cleanup={"status": "retained_for_recovery",
                                   "reason": "trusted result evidence is unavailable"},
                )
                return finish("completed_with_unobserved")
            try:
                preserved = self._original_artifacts(request, result, probe)
            except (OSError, ValueError, KeyError, TypeError, PipelineError,
                    json.JSONDecodeError) as error:
                request_check.update(
                    terminal_status=getattr(error, "status", "postcheck_failed"),
                    reason=f"{type(error).__name__}: {error}",
                    cache_cleanup={"status": "retained_for_recovery",
                                   "reason": "original artifact preservation did not complete"},
                )
                return finish("completed_with_unobserved")
            request_check["original"] = preserved
            r1cs = Path(preserved["r1cs"]["path"])
            try:
                pair_rows = self._bound_pairs(request)
            except (OSError, ValueError, KeyError, TypeError, PipelineError,
                    json.JSONDecodeError) as error:
                request_check.update(
                    terminal_status=getattr(error, "status", "postcheck_failed"),
                    reason=f"{type(error).__name__}: {error}",
                    cache_cleanup={"status": "retained_for_recovery",
                                   "reason": "eligible pair discovery did not complete"},
                )
                return finish("completed_with_unobserved")
            all_passed = True
            pair_root = request_root / "postcheck/pairs"
            for pair in pair_rows:
                public = {key: value for key, value in pair.items()
                          if key not in ("comparator", "deviated")}
                if pair.get("not_observed"):
                    public["status"] = "not_observed"
                    request_check["pairs"].append(public)
                    all_passed = False
                    checkpoint()
                    continue
                try:
                    check = self._check_pair(pair_root, pair["label"], r1cs, pair["comparator"],
                                             pair["deviated"], pair["expected_output_difference"],
                                             pair.get("comparator_sha256"),
                                             pair.get("deviated_sha256"), request_root)
                except (OSError, ValueError, KeyError, TypeError, PipelineError,
                        json.JSONDecodeError) as error:
                    public.update(
                        status="external_check_failed", passed=False,
                        failure_terminal_status=getattr(error, "status", "external_check_failed"),
                        reason=f"{type(error).__name__}: {error}",
                    )
                    request_check["pairs"].append(public)
                    all_passed = False
                    checkpoint()
                    continue
                public.update(check)
                request_check["pairs"].append(public)
                all_passed = all_passed and check["passed"]
                if check["passed"] and pair["expected_output_difference"]:
                    validated.append({
                        "request_id": request["request_id"],
                        "candidate_sha256": request["candidate"]["sha256"],
                        "kind": pair["kind"],
                        "class_index": pair["class_index"],
                        "attempt_index": pair.get("attempt_index"),
                        "original_r1cs": preserved["r1cs"],
                        "comparator_wtns": check["comparator_check"]["witness"],
                        "deviated_wtns": check["deviated_check"]["witness"],
                        "same_full_input": True,
                        "outputs_differ": True,
                    })
                checkpoint()
            request_check["terminal_status"] = (
                "no_eligible_pairs" if not pair_rows
                else "validated" if all_passed else "external_check_failed")
            if all_passed:
                try:
                    self._cleanup_cache(request, request_check)
                except (OSError, ValueError, KeyError, TypeError, PipelineError,
                        json.JSONDecodeError) as error:
                    request_check["primary_terminal_status"] = request_check["terminal_status"]
                    request_check["terminal_status"] = getattr(
                        error, "status", "cache_cleanup_failed")
                    request_check["reason"] = f"cache cleanup failed: {type(error).__name__}: {error}"
                    request_check["cache_cleanup"] = {"status": "failed"}
            else:
                request_check["cache_cleanup"] = {
                    "status": "retained_for_recovery",
                    "reason": "pair preservation or interpretation did not complete successfully",
                }
            return finish("completed")
        except BaseException as error:
            request_check.update(
                terminal_status="postcheck_interrupted",
                reason=f"{type(error).__name__}: {error}",
                cache_cleanup={"status": "retained_for_recovery",
                               "reason": "external checks did not finish"},
            )
            try:
                finish("interrupted")
            except (OSError, ValueError, KeyError, TypeError, PipelineError,
                    json.JSONDecodeError) as record_error:
                request["postcheck_record_error"] = f"{type(record_error).__name__}: {record_error}"
                checkpoint()
            raise

    def _read_request_postcheck(self, request: dict[str, Any]) -> dict[str, Any]:
        request_root = self._owned_request_root(request)
        reference = request.get("postcheck") or {}
        path = Path(reference.get("path", ""))
        if path != request_root / "postcheck.json":
            raise PipelineError("postcheck_identity_failed", "request postcheck path differs")
        path = safe_owned(path, request_root, "request postcheck")
        if sha256(path) != reference.get("sha256"):
            raise PipelineError("postcheck_identity_failed", "request postcheck SHA differs")
        data = read_json(path)
        if (data.get("schema") != "zkfdo-sj-request-postcheck-v1"
                or data.get("request_id") != request["request_id"]
                or data.get("status") != reference.get("status")
                or data.get("check", {}).get("terminal_status") != reference.get("terminal_status")):
            raise PipelineError("postcheck_identity_failed", "request postcheck identity differs")

        def exact(value: dict[str, Any], label: str) -> None:
            artifact = safe_owned(Path(value["path"]), self.output, label)
            if sha256(artifact) != value["sha256"]:
                raise PipelineError("postcheck_identity_failed", f"{label} differs")

        original = data.get("check", {}).get("original") or {}
        for key in ("r1cs", "sym", "identity"):
            if key in original:
                exact(original[key], f"request postcheck original {key}")
        for pair in data.get("check", {}).get("pairs", []):
            for check_key in ("comparator_check", "deviated_check"):
                witness = (pair.get(check_key) or {}).get("witness")
                if witness:
                    exact(witness, f"request postcheck {check_key}")
        for value in data.get("validated_counterexamples", []):
            for key in ("original_r1cs", "comparator_wtns", "deviated_wtns"):
                exact(value[key], f"request validated {key}")
        return data

    def postcheck_stage(self, j_outputs: dict[str, Any]) -> dict[str, Any]:
        with stage_attempt(self, "postcheck") as row:
            if row is None:
                return self.ledger["stages"]["postcheck"]["outputs"]
            attempt = Path(row["directory"])
            checks: list[dict[str, Any]] = []
            validated: list[dict[str, Any]] = []
            request_wall = 0.0
            request_cpu = 0.0
            for request in j_outputs["requests"]:
                self._validate_cache_state(request)
                if request["status"] == "completed":
                    data = self._read_request_postcheck(request)
                    checks.append(data["check"])
                    validated.extend(data.get("validated_counterexamples", []))
                    request_wall += float(data.get("costs", {}).get("wall_seconds") or 0)
                    request_cpu += float(data.get("costs", {}).get("cpu_seconds") or 0)
                else:
                    checks.append({
                        "request_id": request["request_id"],
                        "request_status": request["status"],
                        "terminal_status": "not_observed",
                        "reason": request.get("reason", "J request did not complete"),
                        "cache_cleanup": request.get("cache_cleanup"),
                        "pairs": [],
                    })
            outputs = {
                "checks": checks, "validated_counterexamples": validated,
                "validated_count": len(validated),
                "request_costs": {"wall_seconds": request_wall, "cpu_seconds": request_cpu},
            }
            result_path = attempt / "postcheck.json"
            atomic_json(result_path, outputs)
            outputs["record"] = {"path": str(result_path), "sha256": sha256(result_path)}
            row["outputs"] = outputs
            if j_outputs.get("pipeline_status") == "partial:candidates_pending":
                row["terminal_status"] = "candidates_pending"
            return outputs

    def _candidate_counts(self, s_outputs: dict[str, Any] | None) -> dict[str, int]:
        inventory_path = self.output / "candidate-ledger/inventory.json"
        if inventory_path.is_file() and not inventory_path.is_symlink():
            try:
                inventory = read_json(inventory_path)
                if inventory.get("schema") == "zkfdo-sj-candidate-inventory-v1":
                    return {"preserved": len(inventory.get("preserved") or []),
                            "eligible_unique": len(inventory.get("representatives") or [])}
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass
        if not s_outputs:
            return {"preserved": 0, "eligible_unique": 0}
        try:
            path = Path(s_outputs["campaign_ledger"]["path"])
            if sha256(path) != s_outputs["campaign_ledger"]["sha256"]:
                return {"preserved": 0, "eligible_unique": 0}
            attempts = read_json(path).get("attempts", [])
            return {
                "preserved": sum(len(item.get("candidates", [])) for item in attempts),
                "eligible_unique": sum(
                    candidate.get("duplicate_of") is None
                    for item in attempts for candidate in item.get("candidates", [])
                ),
            }
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return {"preserved": 0, "eligible_unique": 0}

    def build_summary(self, summary_stage_preview: bool = False) -> dict[str, Any]:
        stages = []
        observations = []
        for name in STAGES:
            record = self.ledger["stages"].get(name, {})
            stage = {"stage": name, "status": record.get("status", "not_run"),
                     "terminal_status": record.get("terminal_status", "not_observed"),
                     "wall_seconds": record.get("wall_seconds", 0.0),
                     "cpu_seconds": record.get("cpu_seconds", 0.0),
                     "cost_scope": record.get("cost_scope", "full_stage")}
            if (summary_stage_preview and name == "summary"
                    and stage["status"] == "running"):
                stage.update(status="completed", terminal_status="completed")
            stages.append(stage)
            if name != "summary" and stage["terminal_status"] not in ("completed", "validated"):
                observations.append({"scope": f"stage:{name}", "status": "not_observed",
                                     "reason": stage["terminal_status"]})
        pipeline_status = self.ledger.get("status")
        if pipeline_status not in ("completed", "completed_with_unobserved", "dry_run", "running"):
            observations.append({"scope": "pipeline", "status": "not_observed",
                                 "reason": pipeline_status})
        s_outputs = self.ledger["stages"].get("s_campaign", {}).get("outputs")
        j_outputs = self.ledger["stages"].get("j_requests", {}).get("outputs") or {}
        post_outputs = self.ledger["stages"].get("postcheck", {}).get("outputs") or {}
        verdicts: Counter[str] = Counter()
        probe_statuses: Counter[str] = Counter()
        probe_attempts: Counter[str] = Counter()
        request_rows = []
        post_by_request = {item["request_id"]: item for item in post_outputs.get("checks", [])}
        for request in j_outputs.get("requests", []):
            item = {"request_id": request["request_id"], "status": request["status"],
                    "terminal_status": request["terminal_status"],
                    "candidate_sha256": request["candidate"]["sha256"],
                    "postcheck": post_by_request.get(request["request_id"],
                                                     {"terminal_status": "not_observed", "pairs": []})}
            if request["status"] != "completed":
                item["observation"] = "not_observed"
                item["reason"] = request.get("reason")
                observations.append({"scope": request["request_id"], "status": "not_observed",
                                     "reason": request.get("reason", request["terminal_status"])})
            else:
                try:
                    if (sha256(request["result"]["path"]) != request["result"]["sha256"]
                            or sha256(request["probe"]["path"]) != request["probe"]["sha256"]):
                        raise PipelineError("evidence_identity_failed", "J summary evidence differs")
                    result = read_json(request["result"]["path"])
                    probe = read_json(request["probe"]["path"])
                    verdicts.update(row.get("verdict", "unknown") for row in result.get("classes", []))
                    probe_statuses[probe.get("status", "unknown")] += 1
                    item["preparation"] = result.get("preparation")
                    item["verdict_counts"] = result.get("verdict_counts", {})
                    item["classes"] = []
                    for class_index, class_row in enumerate(result.get("classes", [])):
                        classification = {key: class_row.get(key) for key in (
                            "pattern", "representative", "verdict", "reason", "input_origin",
                            "honest_generation", "deviated_generation", "rust_unsatisfied",
                            "snarkjs", "public_inputs_equal", "outputs_differing"
                        )}
                        classification["class_index"] = class_index
                        item["classes"].append(classification)
                        if class_row.get("verdict") in ("unknown", "excluded_in_context"):
                            observations.append({"scope": f"{request['request_id']}:class-{class_index:03d}",
                                                 "status": "not_observed",
                                                 "reason": class_row.get("verdict")})
                    probe_classes = []
                    for class_row in probe.get("classes", []):
                        attempts = []
                        for attempt_index, probe_attempt in enumerate(class_row.get("attempts", [])):
                            attempt_status = probe_attempt.get("status", "unknown")
                            probe_attempts[attempt_status] += 1
                            attempts.append({"attempt_index": attempt_index, "status": attempt_status,
                                             "reasons": probe_attempt.get("reasons", []),
                                             "checks": probe_attempt.get("checks", {})})
                            if (attempt_status in ("budget_exhausted", "unsupported", "generation_failed")
                                    or attempt_status.endswith("_failed")):
                                observations.append({
                                    "scope": (f"{request['request_id']}:probe-class-"
                                              f"{class_row.get('class_index', 0):03d}-attempt-{attempt_index:03d}"),
                                    "status": "not_observed", "reason": attempt_status})
                            elif attempt_status == "condition_unmet":
                                observations.append({
                                    "scope": (f"{request['request_id']}:probe-class-"
                                              f"{class_row.get('class_index', 0):03d}-attempt-{attempt_index:03d}"),
                                    "status": "limited_observation", "reason": attempt_status})
                        class_status = class_row.get("status", "unknown")
                        probe_classes.append({"class_index": class_row.get("class_index"),
                                              "existing_verdict": class_row.get("existing_verdict"),
                                              "status": class_status,
                                              "reasons": class_row.get("reasons", []),
                                              "attempts": attempts})
                        if (class_status in ("budget_exhausted", "unsupported", "no_component_candidate")
                                or class_status.endswith("_failed")):
                            observations.append({
                                "scope": f"{request['request_id']}:probe-class-{class_row.get('class_index', 0):03d}",
                                "status": "not_observed", "reason": class_status})
                    item["probe"] = {"status": probe.get("status"),
                                     "reasons": probe.get("reasons", []), "classes": probe_classes}
                    if result.get("preparation", {}).get("status") != "ok":
                        observations.append({"scope": request["request_id"], "status": "not_observed",
                                             "reason": result.get("preparation", {}).get("status")})
                    if probe.get("status") in ("budget_exhausted", "unsupported"):
                        observations.append({"scope": request["request_id"] + ":probe",
                                             "status": "not_observed", "reason": probe.get("status")})
                except (OSError, ValueError, KeyError, PipelineError, json.JSONDecodeError) as error:
                    item["observation"] = "not_observed"
                    item["reason"] = f"result summary failed: {type(error).__name__}"
                    observations.append({
                        "scope": request["request_id"] + ":result_summary",
                        "status": "not_observed", "reason": item["reason"],
                    })
            request_rows.append(item)
            postcheck = item["postcheck"]
            if postcheck.get("terminal_status") not in ("validated",):
                observations.append({"scope": request["request_id"] + ":postcheck",
                                     "status": "not_observed",
                                     "reason": postcheck.get("terminal_status", "not_observed")})
        if s_outputs and s_outputs.get("termination_reason"):
            observations.append({"scope": "S", "status": "not_observed",
                                 "reason": s_outputs["termination_reason"]})
        if s_outputs and s_outputs.get("measurement_valid") is False:
            observations.append({"scope": "S costs", "status": "not_observed",
                                 "reason": "invalid_measurement"})
        if probe_attempts.get("verified_output_identical"):
            observations.append({"scope": "probe_output_identical", "status": "limited_observation",
                                 "reason": "recorded input and intervention only; not a safety finding"})
        candidate_counts = self._candidate_counts(s_outputs)
        state_counts = Counter(row.get("state") for row in self.ledger.get("candidate_states", []))
        state_total = sum(state_counts.values())
        if j_outputs and j_outputs.get("selected_count", 0) == 0:
            observations.append({"scope": "J", "status": "not_observed",
                                 "reason": "no preserved candidate selected"})
        if self.args.j_candidates is not None:
            observations.append({"scope": "J candidates after selection limit", "status": "not_observed",
                                 "reason": "explicit diagnostic candidate limit"})
        return {
            "schema": "zkfdo-sj-summary-v1",
            "pipeline_status": self.ledger.get("status"),
            "engine_started": self.ledger.get("engine_started", False),
            "identity_sha256": self.identity_sha,
            "corpus_layer": self.args.corpus_layer,
            "stages": stages,
            "costs": {
                "stage_wall_seconds": sum(float(item["wall_seconds"] or 0) for item in stages),
                "stage_cpu_seconds": sum(float(item["cpu_seconds"] or 0) for item in stages),
                "command_wall_seconds": sum(float(item.get("wall_seconds") or 0)
                                            for item in self.ledger.get("commands", [])),
                "command_cpu_seconds": sum(float(item.get("cpu_seconds") or 0)
                                           for item in self.ledger.get("commands", [])),
            },
            "candidates": {"preserved": candidate_counts["preserved"],
                           "eligible_unique": candidate_counts["eligible_unique"],
                           "total": state_total or candidate_counts["eligible_unique"],
                           "judged": state_counts["judged"],
                           "in_progress_interrupted": state_counts["in_progress_interrupted"],
                           "pending_not_run": state_counts["pending_not_run"],
                           "selected_for_j": j_outputs.get("selected_count", 0),
                           "selection_limit": self.args.j_candidates,
                           "diagnostic_limit_active": self.args.j_candidates is not None,
                           "order_policy": j_outputs.get(
                               "order_policy", "first_unique_candidates_in_campaign_ledger_order"),
                           "merged_duplicates": j_outputs.get("merged_duplicates", [])},
            "j": {"requests": request_rows, "verdict_counts": dict(sorted(verdicts.items())),
                  "probe_status_counts": dict(sorted(probe_statuses.items())),
                  "probe_attempt_counts": dict(sorted(probe_attempts.items())),
                  "budget": self.ledger.get("budget_accounting", {}).get("j", {})},
            "validated_counterexample": post_outputs.get("validated_counterexamples", []),
            "not_observed": observations,
            "safety_conclusion": "not_made",
            "limitations": self.ledger.get("limitations", []),
        }

    def write_summary(self, summary_stage_preview: bool = False) -> dict[str, Any]:
        summary = self.build_summary(summary_stage_preview=summary_stage_preview)
        json_path = self.output / "summary.json"
        markdown_path = self.output / "summary.md"
        atomic_json(json_path, summary)

        def cell(value: Any) -> str:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if value is None:
                return ""
            return str(value).replace("|", "\\|").replace("\n", " ")

        lines = [
            "# S→J pipeline summary", "",
            f"- Pipeline status: `{summary['pipeline_status']}`",
            f"- Engine started: `{str(summary['engine_started']).lower()}`",
            f"- Corpus layer: `{summary['corpus_layer']}`",
            f"- Preserved candidates: `{summary['candidates']['preserved']}`",
            f"- Selected J candidates: `{summary['candidates']['selected_for_j']}`",
            (f"- Candidate status: total `{summary['candidates']['total']}`, judged "
             f"`{summary['candidates']['judged']}`, pending not run "
             f"`{summary['candidates']['pending_not_run']}`, interrupted "
             f"`{summary['candidates']['in_progress_interrupted']}`"),
            (f"- Diagnostic candidate limit: `{summary['candidates']['selection_limit']}`"
             if summary['candidates']['diagnostic_limit_active']
             else "- Diagnostic candidate limit: `none (all candidates)`"),
            f"- Validated counterexamples: `{len(summary['validated_counterexample'])}`", "",
            "## Stages", "",
            "| Stage | Status | Terminal status | Wall seconds | CPU seconds | Cost scope |",
            "|---|---|---|---:|---:|---|",
        ]
        for stage in summary["stages"]:
            lines.append(f"| {stage['stage']} | {stage['status']} | {stage['terminal_status']} | "
                         f"{float(stage['wall_seconds'] or 0):.3f} | "
                         f"{float(stage['cpu_seconds'] or 0):.3f} | {cell(stage['cost_scope'])} |")
        lines.extend(["", "## Findings", "",
                      f"- Verdict counts: `{json.dumps(summary['j']['verdict_counts'], sort_keys=True)}`",
                      f"- Probe attempt counts: `{json.dumps(summary['j']['probe_attempt_counts'], sort_keys=True)}`",
                      "- No safety conclusion is made from unsupported, exhausted, or output-identical cases.",
                      "", "## J requests", "",
                      "| Request | Candidate SHA-256 | Status | Terminal | Preparation | Probe | Postcheck |",
                      "|---|---|---|---|---|---|---|"])
        for request in summary["j"]["requests"]:
            lines.append(
                f"| {cell(request.get('request_id'))} | {cell(request.get('candidate_sha256'))} | "
                f"{cell(request.get('status'))} | {cell(request.get('terminal_status'))} | "
                f"{cell((request.get('preparation') or {}).get('status'))} | "
                f"{cell((request.get('probe') or {}).get('status'))} | "
                f"{cell((request.get('postcheck') or {}).get('terminal_status'))} |")
        lines.extend(["", "## J classes", "",
                      "| Request | Class | Pattern | Verdict | Reason |",
                      "|---|---:|---|---|---|"])
        for request in summary["j"]["requests"]:
            for classification in request.get("classes", []):
                lines.append(
                    f"| {cell(request.get('request_id'))} | {cell(classification.get('class_index'))} | "
                    f"{cell(classification.get('pattern'))} | {cell(classification.get('verdict'))} | "
                    f"{cell(classification.get('reason'))} |")
        lines.extend(["", "## Probe results", "",
                      "| Request | Class | Class status | Attempt | Attempt status | Reasons |",
                      "|---|---:|---|---:|---|---|"])
        for request in summary["j"]["requests"]:
            for probe_class in (request.get("probe") or {}).get("classes", []):
                attempts = probe_class.get("attempts") or [None]
                for attempt in attempts:
                    lines.append(
                        f"| {cell(request.get('request_id'))} | {cell(probe_class.get('class_index'))} | "
                        f"{cell(probe_class.get('status'))} | "
                        f"{cell(None if attempt is None else attempt.get('attempt_index'))} | "
                        f"{cell(None if attempt is None else attempt.get('status'))} | "
                        f"{cell(probe_class.get('reasons') if attempt is None else attempt.get('reasons'))} |")
        lines.extend(["", "## Validated counterexamples", "",
                      "| Request | Kind | Class | Attempt | Original R1CS | Comparator WTNS | Deviated WTNS |",
                      "|---|---|---:|---:|---|---|---|"])
        for pair in summary["validated_counterexample"]:
            lines.append(
                f"| {cell(pair.get('request_id'))} | {cell(pair.get('kind'))} | "
                f"{cell(pair.get('class_index'))} | {cell(pair.get('attempt_index'))} | "
                f"{cell((pair.get('original_r1cs') or {}).get('path'))} | "
                f"{cell((pair.get('comparator_wtns') or {}).get('path'))} | "
                f"{cell((pair.get('deviated_wtns') or {}).get('path'))} |")
        lines.extend(["", "## Not observed and limited", "",
                      "| Scope | Status | Reason |", "|---|---|---|"])
        for observation in summary["not_observed"]:
            lines.append(f"| {cell(observation.get('scope'))} | {cell(observation.get('status'))} | "
                         f"{cell(observation.get('reason'))} |")
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {cell(limit)}" for limit in summary["limitations"])
        lines.append("")
        atomic_text(markdown_path, "\n".join(lines))
        return {"summary_json": str(json_path), "summary_markdown": str(markdown_path)}

    def summary_stage(self) -> dict[str, Any]:
        name = "summary"
        identity = self.stage_identity(name)
        previous = self.ledger["stages"].get(name)
        if previous and previous.get("status") == "completed":
            if previous.get("identity_sha256") != identity:
                raise PipelineError("resume_identity_mismatch",
                                    "completed stage identity differs: summary")
            self.validate_completed_stage(name, previous)
            self.ledger.setdefault("resume_events", []).append(
                {"stage": name, "status": "skipped", "utc": utc()})
            self.checkpoint()
            return previous["outputs"]
        if previous:
            self.archive_stage_record(name, previous, recovered=True)
        attempt_dir = next_attempt(self.output / "stage-records" / name)
        attempt_dir.mkdir(parents=True, exist_ok=False)
        started, cpu_started = time.monotonic(), time.process_time()
        row = {
            "stage": name, "status": "running", "identity_sha256": identity,
            "attempt": attempt_dir.name, "directory": str(attempt_dir),
            "started_utc": utc(), "started_epoch_seconds": time.time(),
            "wall_seconds": 0.0, "cpu_seconds": 0.0,
            "cost_scope": "through_initial_durable_render",
        }
        self.ledger["stages"][name] = row
        self.checkpoint()
        try:
            self.write_summary(summary_stage_preview=True)
            partial = self.ledger.get("status") == "partial:candidates_pending"
            row.update(
                status="partial" if partial else "completed",
                terminal_status="candidates_pending" if partial else "completed",
                wall_seconds=time.monotonic() - started,
                cpu_seconds=time.process_time() - cpu_started,
            )
            refresh_started, refresh_cpu_started = time.monotonic(), time.process_time()
            paths = self.write_summary()
            row["terminal_refresh_wall_seconds"] = time.monotonic() - refresh_started
            row["terminal_refresh_cpu_seconds"] = time.process_time() - refresh_cpu_started
            immutable_paths = {}
            for key, path in paths.items():
                source = Path(path)
                destination = attempt_dir / source.name
                immutable_paths[key] = copy_verified(source, destination, sha256(source))
            row["outputs"] = immutable_paths
            row["finished_utc"] = utc()
            self.archive_stage_record(name, row, recovered=False)
            self.checkpoint()
            return row["outputs"]
        except BaseException as error:
            failed_wall = time.monotonic() - started
            failed_cpu = time.process_time() - cpu_started
            row.update(
                status="failed",
                terminal_status=getattr(error, "status", "operational_failure"),
                error=f"{type(error).__name__}: {error}",
                traceback=traceback.format_exc(),
                wall_seconds=failed_wall, cpu_seconds=failed_cpu,
                observed_wall_seconds=failed_wall,
                observed_cpu_seconds=failed_cpu,
                cost_scope="through_failure",
                finished_utc=utc(),
            )
            self.checkpoint()
            raise

    def _finish_missing(self) -> None:
        for name in STAGES:
            if name == "summary":
                continue
            previous = self.ledger["stages"].get(name)
            if previous and previous.get("status") not in ("planned", "not_run"):
                continue
            request_costs = {}
            if name == "postcheck":
                request_costs = ((self.ledger["stages"].get("j_requests", {}).get("outputs") or {})
                                 .get("request_postcheck_costs") or {})
            self.ledger["stages"][name] = {
                "stage": name, "status": "not_run", "terminal_status": "not_observed",
                "wall_seconds": float(request_costs.get("wall_seconds") or 0),
                "cpu_seconds": float(request_costs.get("cpu_seconds") or 0),
                "request_costs": request_costs,
            }

    def run(self) -> bool:
        with supervisor_signal_scope():
            return self._run_with_signal_handling()

    def _run_with_signal_handling(self) -> bool:
        if self.ledger.get("complete"):
            raise PipelineError("terminal_output_immutable",
                                "completed or failed output is immutable; use a new output suffix")
        try:
            self.register_budget_allocation()
            self.reconcile_interrupted_consumption()
            self.ledger.update(status="running", complete=False)
            self.checkpoint()
            self.preflight_stage()
            self.baseline_stage()
            preparation = self.preparation_stage()
            s_outputs = self.s_campaign_stage(preparation)
            if s_outputs.get("resume_required"):
                self._finish_missing()
                self.ledger.update(status="partial:interrupted", complete=False,
                                   last_attempt_finished_utc=utc())
                self.write_summary()
                self.checkpoint()
                return False
            if not s_outputs.get("continue_to_j", True):
                self._finish_missing()
                self.ledger.update(status="completed_with_unobserved", complete=True, finished_utc=utc())
                self.summary_stage()
                self.checkpoint()
                return True
            j_outputs = self.j_requests_stage(preparation, s_outputs)
            self.postcheck_stage(j_outputs)
            if j_outputs.get("pipeline_status") == "partial:candidates_pending":
                self.ledger.update(status="partial:candidates_pending", complete=False,
                                   last_attempt_finished_utc=utc())
                self.summary_stage()
                self.checkpoint()
                return True
            self.ledger["status"] = "completed"
            observations = self.build_summary()["not_observed"]
            final_status = ("completed_with_unobserved"
                            if any(item.get("status") == "not_observed" for item in observations)
                            else "completed")
            self.ledger.update(status=final_status, complete=True, finished_utc=utc())
            self.summary_stage()
            self.checkpoint()
            return True
        except SupervisorSignal as error:
            self._finish_missing()
            self.ledger.update(status="partial:interrupted", complete=False,
                               last_attempt_finished_utc=utc(),
                               error=f"{type(error).__name__}: {error}")
            self.checkpoint()
            try:
                self.write_summary()
            except BaseException as summary_error:
                self.ledger["summary_error"] = f"{type(summary_error).__name__}: {summary_error}"
                self.checkpoint()
            return False
        except BaseException as error:
            self._finish_missing()
            self.ledger.update(status=getattr(error, "status", "operational_failure"), complete=True,
                               finished_utc=utc(), error=f"{type(error).__name__}: {error}")
            self.checkpoint()
            try:
                previous_summary = self.ledger["stages"].get("summary")
                if previous_summary and previous_summary.get("status") == "completed":
                    self.ledger.setdefault("summary_events", []).append({
                        "status": "superseded_for_failure_report",
                        "attempt": previous_summary.get("attempt"),
                        "identity_sha256": previous_summary.get("identity_sha256"),
                        "outputs": previous_summary.get("outputs"),
                        "utc": utc(),
                    })
                    previous_summary["status"] = "superseded_for_failure_report"
                    self.checkpoint()
                self.summary_stage()
                summary_record = self.ledger["stages"].get("summary")
                if summary_record and summary_record.get("status") == "completed":
                    summary_record["status"] = "reported_after_failure"
            except BaseException as summary_error:
                self.ledger["summary_error"] = f"{type(summary_error).__name__}: {summary_error}"
            self.checkpoint()
            return False

    def dry_run(self) -> dict[str, Any]:
        if self.ledger.get("status") == "dry_run":
            path = self.output / "dry-run.json"
            if self.ledger.get("engine_started") or not path.is_file():
                raise PipelineError("resume_identity_mismatch", "saved dry-run state differs")
            if sha256(path) != self.ledger.get("dry_run_sha256"):
                raise PipelineError("resume_identity_mismatch", "saved dry-run record differs")
            saved = read_json(path)
            if saved.get("identity_sha256") != self.identity_sha:
                raise PipelineError("resume_identity_mismatch", "saved dry-run identity differs")
            return saved
        if self.ledger.get("engine_started") or self.ledger.get("stages"):
            raise PipelineError("resume_state_conflict", "dry-run cannot replace an existing run ledger")
        out = self.output
        source = out / "work/source"
        stage_root = out / "stage-records"
        attempts = {name: stage_root / name / "attempts/0001" for name in STAGES}
        baseline = attempts["baseline"]
        baseline_artifacts = baseline / "artifacts"
        stem = self.entrypoint.stem
        original_r1cs = baseline_artifacts / f"{stem}.r1cs"
        original_sym = baseline_artifacts / f"{stem}.sym"
        original_wasm = baseline_artifacts / f"{stem}_js/{stem}.wasm"
        witness_generator = baseline_artifacts / f"{stem}_js/generate_witness.js"
        honest_witness = baseline / "honest.wtns"
        preparation = attempts["preparation"]
        discovery_output = source / "discovery-0001"
        preparation_manifest = preparation / "manifest.json"
        prepared_output = source / "prepared-0001"
        split_plan = preparation / "split-plan.json"
        s_attempt = attempts["s_campaign"]
        s_spec = s_attempt / "spec.json"
        s_profiles = s_attempt / "revision-profiles.json"
        s_campaign = s_attempt / "campaign"
        j_attempt = attempts["j_requests"]

        def command(stage: str, label: str, argv: list[str | Path], directory: Path,
                    timeout: float, cwd: Path, **extra: Any) -> dict[str, Any]:
            return {"kind": "subprocess", "stage": stage, "label": label,
                    "argv": command_view(argv), "directory": str(directory),
                    "cwd": str(cwd), "timeout_seconds": timeout, **extra}

        compile_argv: list[str | Path] = [
            self.tool("circom"), self.entrypoint, "--O0", "--r1cs", "--sym", "--wasm",
            "--output", baseline_artifacts,
        ]
        targets_argv: list[str | Path] = [
            self.tool("prepare"), "targets", "--project", self.project,
            "--entrypoint", self.entrypoint, "--output", discovery_output,
            "--circom-bin", self.tool("circom"), "--compile-timeout-seconds", "60",
            "--instance-capture", "--capture-timeout-seconds", "60",
        ]
        for library in self.library_paths:
            compile_argv.extend(["-l", library])
            targets_argv.extend(["--library-path", library])
        preflight_git = [
            ("git_repository_root", ["git", "-C", self.normalized["project_root"],
                                     "rev-parse", "--show-toplevel"]),
            ("git_commit", ["git", "-C", self.normalized["project_root"],
                            "rev-parse", "--verify", "HEAD"]),
            ("git_branch", ["git", "-C", self.normalized["project_root"],
                            "branch", "--show-current"]),
            ("git_status", ["git", "-C", self.normalized["project_root"],
                            "status", "--porcelain=v1", "--untracked-files=all"]),
        ]
        commands = [
            {"kind": "preflight_subprocess", "stage": "preflight", "label": label,
             "argv": argv, "cwd": self.normalized["project_root"], "timeout_seconds": 60,
             "execution_phase": "completed_before_dry_run_plan",
             "receipt": self.normalized["revision"]}
            for label, argv in preflight_git
        ] + [
            command("baseline", "compile", compile_argv, baseline / "commands/compile",
                    self.args.baseline_seconds, self.project),
            command("baseline", "honest_witness",
                    [self.tool("node"), witness_generator, original_wasm,
                     self.base_input, honest_witness],
                    baseline / "commands/honest-witness", self.args.baseline_seconds,
                    self.project),
            command("baseline", "rust_check",
                    [self.tool("rust_checker"), "check_current_witness", "--exact", "--ignored"],
                    baseline / "commands/rust-check", self.args.baseline_seconds, ROOT,
                    environment_additions={"N6_J1_R1CS": str(original_r1cs),
                                           "N6_J1_WTNS": str(honest_witness)}),
            command("baseline", "snarkjs_check",
                    [self.tool("snarkjs"), "wtns", "check", original_r1cs, honest_witness],
                    baseline / "commands/snarkjs-check", self.args.baseline_seconds, ROOT),
            command("preparation", "targets", targets_argv,
                    preparation / "commands/targets", self.args.preparation_command_seconds, ROOT,
                    internal_timeouts_seconds={"compile": 60, "instance_capture": 60}),
            command("preparation", "prepare",
                    [self.tool("prepare"), "experiment", "prepare", "--manifest",
                     preparation_manifest, "--output", prepared_output, "--strategy", "small-first",
                     "--circom-bin", self.tool("circom"), "--tool-timeout-seconds", "60"],
                    preparation / "commands/prepare", self.args.preparation_command_seconds, ROOT,
                    internal_timeouts_seconds={"tool": 60}),
            {"kind": "subprocess", "stage": "preparation", "label": "plan",
             "argv_template": command_view([
                 self.tool("prepare"), "experiment", "plan", "--prepared", "${prepared_json}",
                 "--strategy", "small-first", "--config", ROOT / "configs/static-ranking.json",
                 "--output", split_plan,
             ]),
             "directory": str(preparation / "commands/plan"), "cwd": str(ROOT),
             "timeout_seconds": self.args.preparation_command_seconds,
             "deferred_paths": {"prepared_json": {"produced_by": "preparation.prepare",
                                                   "search_root": str(prepared_output),
                                                   "unique_name": "prepared.json"}}},
            {"kind": "python_call", "stage": "s_campaign", "label": "policy_v5_1",
             "callable": "run_policy_a_engine_v5_1.run_campaign",
             "positional_arguments": [str(s_spec), str(s_campaign)],
             "keyword_arguments": {
                 "max_disk_bytes": int(self.args.max_disk_gib * GIB), "max_attempts": None,
                 "tools_manifest_path": str(self.tools_manifest_path),
                 "load_tools_manifest": True, "purpose": "discovery",
                 "min_free_bytes": int(self.args.run_min_free_gib * GIB),
                 "tree_interval_seconds": 1.0, "free_interval_seconds": 0.0,
             },
             "specification": {
                 "path": str(s_spec), "revision_profiles": str(s_profiles),
                 "total_budget_seconds": self.args.s_budget_seconds,
                 "attempt_cap_seconds": self.args.s_attempt_seconds,
                 "concurrency": 1, "initial_seed": self.args.initial_seed,
                 "seed_rule": "increment_per_pass", "preflight_compile_timeout_seconds": 60,
             }},
            {"kind": "subprocess_template", "stage": "s_campaign",
             "label": "fragment_preflight_compile",
             "argv_template": command_view([
                 str(s_campaign / "preflight/${target_index_4d}/process-compiler-gate/circom"),
                 "${prepared_entrypoint}", "--r1cs", "--sym", "--O0",
                 "--output", "${fragment_compile_output}", "-l", "${fragment_workspace}",
             ]),
             "original_argv_template": command_view([
                 self.tool("circom"), "${prepared_entrypoint}", "--r1cs", "--sym", "--O0",
                 "--output", "${fragment_compile_output}", "-l", "${fragment_workspace}",
             ]),
             "directory_template": str(
                 s_campaign / "preflight/${target_index_4d}/process"),
             "cwd_template": "${fragment_workspace}", "timeout_seconds": 60,
             "timeout_policy": {
                 "rule": "min(command_cap_seconds, remaining_s_total_seconds)",
                 "command_cap_seconds": 60,
                 "total_seconds": self.args.s_budget_seconds,
             },
             "deferred_by_stage": "preparation.plan",
             "deferred_paths": {
                 "fragment_workspace": str(
                     s_campaign / "preflight/${target_index_4d}/workspace"),
                 "fragment_compile_output": str(
                     s_campaign / "preflight/${target_index_4d}/artifacts"),
                 "prepared_entrypoint": str(
                     s_campaign / "preflight/${target_index_4d}/workspace/${entrypoint_relative}"),
                 "compiler_gate": str(
                     s_campaign / "preflight/${target_index_4d}/process-compiler-gate/circom"),
             }},
            {"kind": "subprocess_template", "stage": "s_campaign", "label": "fragment_fuzz",
             "argv_template": command_view([
                 self.tool("zkfuzz"), "${prepared_entrypoint}", "--prime", "bn128",
                 "--search_mode", "ga", "-l", "${fragment_workspace}",
                 "--path_to_mutation_setting",
                 str(s_campaign / "attempts/${attempt_index_6d}/mutation-settings.json"),
             ]),
             "directory_template": str(
                 s_campaign / "attempts/${attempt_index_6d}/fuzz"),
             "cwd_template": "${fragment_workspace}",
             "timeout_seconds": self.args.s_attempt_seconds,
             "total_budget_seconds": self.args.s_budget_seconds,
             "timeout_policy": {
                 "rule": "min(command_cap_seconds, remaining_s_total_seconds)",
                 "command_cap_seconds": self.args.s_attempt_seconds,
                 "total_seconds": self.args.s_budget_seconds,
             },
             "deferred_by_stage": "preparation.plan",
             "deferred_paths": {
                 "fragment_workspace": str(
                     s_campaign / "attempts/${attempt_index_6d}/sources/wrapper"),
                 "prepared_entrypoint": str(
                     s_campaign / "attempts/${attempt_index_6d}/sources/wrapper/${entrypoint_relative}"),
                 "s_attempt_directory": str(
                     s_campaign / "attempts/${attempt_index_6d}"),
             },
             "seed_transport": {"kind": "mutation_settings",
                                "initial_seed": self.args.initial_seed,
                                "rule": "increment_per_pass"}},
        ]
        request_id = "candidate-${candidate_index_6d}-attempt-${request_attempt_4d}"
        request_root = j_attempt / "requests/${candidate_index_6d}-${request_attempt_4d}"
        request_path = request_root / "request.json"
        request_output = request_root / "out"
        cache = request_root / "cache"
        store = request_root / "instance-store"
        j_path_template = {
            "request_id": request_id, "root": str(request_root),
            "request": str(request_path), "output": str(request_output),
            "cache": str(cache), "instance_store": str(store),
            "result": str(request_output / "result.json"),
            "probe": str(request_output / "site-signal-probe.json"),
            "postcheck": str(request_root / "postcheck.json"),
            "cache_cleanup": str(request_root / "cache-cleanup.json"),
        }
        commands.append(command(
            "j_requests", request_id,
            [self.tool(self.j_name), "--request", request_path, "--output", request_output,
             "--cache", cache, "--instance-store", store,
             "--circom-bin", self.tool("circom"), "--node-bin", self.tool("node"),
             "--snarkjs-bin", self.tool("snarkjs"), "--z3-bin", self.tool("z3"),
             "--j-jobs", "1", "--site-signal-probe", "--site-signal-probe-classes",
             self.args.probe_classes, "--site-signal-probe-seconds", str(self.args.probe_seconds)],
            request_root / "command", self.args.j_request_seconds, ROOT,
            repeat_for="every unique candidate in preserved campaign order, unless diagnostic limit is set",
            timeout_policy={"rule": ("min(request_seconds, "
                                             "remaining_cumulative_j_wall_budget_seconds)"),
                            "request_seconds": self.args.j_request_seconds,
                            "base_total_seconds": self.args.j_total_seconds,
                            "extra_seconds_this_invocation": self.args.j_extra_total_seconds,
                            "budget_scope": "J subprocess wall including process-group cleanup"},
            request_template={
                "schema": "zkfdo-lifting-request-v1", "id": request_id,
                "source_root": str(source),
                "library_paths": ["${prepared_sources}",
                                  *[str(path) for path in self.library_paths]],
                "component_wrapper": "${prepared_wrapper}",
                "entrypoint": str(self.entrypoint), "base_input": str(self.base_input),
                "candidate": {"format": "zkfuzz", "path": "${selected_candidate_path}"},
            },
            deferred_request_fields=["candidate.path", "component_wrapper", "library_paths"],
            deferred_paths={
                "prepared_sources": {"produced_by": "preparation.plan",
                                     "owned_root": str(prepared_output)},
                "prepared_wrapper": {"produced_by": "preparation.plan",
                                     "owned_root": str(prepared_output)},
                "selected_candidate_path": {
                    "produced_by": "s_campaign.candidate_collection",
                    "owned_root": str(s_campaign),
                },
            }))
        commands.append({
            "kind": "subprocess_template", "stage": "postcheck",
            "label": request_id + "-qualified-pair",
            "argv_template": command_view([
                self.tool("snarkjs"), "wtns", "check", "${preserved_original_r1cs}",
                "${comparator_or_deviated_wtns}",
            ]),
            "directory_template": str(request_root / "postcheck/pairs/${pair_label}-${side}"),
            "cwd": str(ROOT), "timeout_seconds": self.args.postcheck_seconds,
            "repeat_for": ["entrypoint_violation", "probe_positive",
                           "probe_verified_output_identical"],
            "execution_order": "immediately_after_request_before_next_candidate",
            "deferred_paths": {
                "preserved_original_r1cs": {
                    "produced_by": "postcheck.preserve_original_r1cs_and_sym",
                    "path_template": str(
                        out / "originals/${r1cs_sha256}-${sym_sha256}/original.r1cs"),
                },
                "comparator_or_deviated_wtns": {
                    "produced_by": "J result or probe evidence",
                    "owned_root": str(request_output / "raw"),
                    "identity_fields": ["comparator_wtns_sha256", "deviated_wtns_sha256"],
                },
            },
        })
        plan = {
            "schema": "zkfdo-sj-dry-run-v1",
            "engine_started": False,
            "identity_sha256": self.identity_sha,
            "corpus_layer": self.args.corpus_layer,
            "tools_manifest": dict(self.identity["tools_manifest"]),
            "paths": {
                "output": str(out), "source_root": str(source),
                "identity": str(out / "identity.json"),
                "ledger": str(out / "ledger.json"),
                "dry_run": str(out / "dry-run.json"),
                "source_manifest": str(out / "work/source-manifest.json"),
                "tools_manifest": str(self.tools_manifest_path),
                "summary": {"json": str(out / "summary.json"),
                            "markdown": str(out / "summary.md")},
                "entrypoint": str(source / "project" / self.normalized["entrypoint_relative"]),
                "base_input": str(source / "base-input.json"),
                "originals": str(out / "originals"),
                "stage_attempts": {name: str(path) for name, path in attempts.items()},
                "baseline": {"artifacts": str(baseline_artifacts), "r1cs": str(original_r1cs),
                             "sym": str(original_sym), "wasm": str(original_wasm),
                             "witness_generator": str(witness_generator),
                             "honest_witness": str(honest_witness)},
                "preparation": {"discovery_root": str(discovery_output),
                                "manifest": str(preparation_manifest),
                                "prepared_root": str(prepared_output),
                                "split_plan": str(split_plan)},
                "s_campaign": {"spec": str(s_spec), "revision_profiles": str(s_profiles),
                               "output": str(s_campaign),
                               "ledger": str(s_campaign / "ledger.json"),
                               "revision_preflight_receipt_template": str(
                                   s_campaign / "revision-preflight/${target_index_4d}.json"),
                               "report_link_template": str(
                                   s_campaign / "attempts/${attempt_index_6d}/report_link.json"),
                               "candidate_report_template": str(
                                   s_campaign / "attempts/${attempt_index_6d}/candidates/"
                                   "zkfdo_report_counterexample.json")},
                "selected_candidates": str(out / "candidate-ledger/inventory.json"),
                "postcheck_record": str(attempts["postcheck"] / "postcheck.json"),
                "j_request_template": j_path_template,
            },
            "budgets": self.identity["budgets"],
            "seed_policy": self.identity["seed_policy"],
            "j": {
                **self.identity["j"],
                "tool_name": self.j_name,
                "path": self.tool(self.j_name),
                "sha256": self.tools[self.j_name]["sha256"],
            },
            "actions": [
                {"stage": "preflight", "label": "normalize_inputs_and_capture_revision",
                 "inputs": [self.normalized["entrypoint"], self.normalized["base_input"],
                            *self.normalized["library_paths"]],
                 "closure_sha256": self.normalized["closure_sha256"]},
                {"stage": "preflight", "label": "disk_gate",
                 "minimum_free_gib": self.args.min_free_gib, "path": str(out)},
                {"stage": "preflight", "label": "write_source_snapshot",
                 "path": str(source), "manifest": str(out / "work/source-manifest.json")},
                {"stage": "s_campaign", "label": "verify_pinned_source_and_include_closures",
                 "frequency": "immediately_before S"},
                {"stage": "j_requests", "label": "verify_pinned_source_include_closure_and_disk",
                 "frequency": "immediately before every J request and periodically while it runs"},
                {"stage": "preparation", "label": "write_fragment_manifest",
                 "path": str(preparation_manifest)},
                {"stage": "postcheck", "label": "preserve_original_r1cs_and_sym",
                 "path_template": str(out / "originals/${r1cs_sha256}-${sym_sha256}")},
                {"stage": "postcheck", "label": "remove_request_cache_after_checks",
                 "path_template": j_path_template["cache"],
                 "condition": "only after original R1CS/SYM preservation and terminal interpretation",
                 "preserves": ["out", "instance-store", "request.json"]},
                {"stage": "summary", "label": "write_terminal_tables",
                 "paths": [str(out / "summary.json"), str(out / "summary.md")]},
            ],
            "commands": commands,
            "deferred_paths": {
                "prepared_json": {"produced_by": "preparation.prepare",
                                  "search_root": str(prepared_output), "unique_name": "prepared.json"},
                "prepared_targets": {"produced_by": "preparation.plan",
                                     "plan": str(split_plan)},
                "s_attempt_directory": {
                    "produced_by": "s_campaign",
                    "path_template": str(s_campaign / "attempts/${attempt_index_6d}"),
                    "attempt_index_format": "six decimal digits",
                    "seed_rule": "initial_seed plus completed pass index",
                },
                "preserved_original": {"produced_by": "request_postcheck",
                                       "path_template": str(out / "originals/${r1cs_sha256}-${sym_sha256}")},
            },
            "execution_order": [
                "preflight", "baseline", "preparation", "s_campaign",
                "for each selected candidate: J then request postcheck then cache cleanup",
                "postcheck aggregation", "summary",
            ],
            "support_limits": [
                "literal Circom includes only", "real non-symlink source paths",
                "Git project root with a resolvable commit", "bn128 and O0",
                "R1CS v1 and WTNS v2 external evidence",
                "periodic disk sampling cannot prevent an instantaneous peak inside a sampling interval",
            ],
        }
        path = out / "dry-run.json"
        atomic_json(path, plan)
        self.ledger.update(status="dry_run", complete=True, engine_started=False, finished_utc=utc())
        self.ledger["dry_run_sha256"] = sha256(path)
        for name in STAGES:
            self.ledger["stages"][name] = {"stage": name, "status": "planned",
                                                   "terminal_status": "not_started",
                                                   "wall_seconds": 0.0, "cpu_seconds": 0.0}
        self.ledger["stages"]["preflight"].update(
            planning_costs=self.startup_preflight,
            wall_seconds=float(self.startup_preflight.get("wall_seconds") or 0),
            cpu_seconds=float(self.startup_preflight.get("cpu_seconds") or 0),
        )
        self.checkpoint()
        self.write_summary()
        return plan


def pipeline_identity(args: argparse.Namespace, normalized: dict[str, Any],
                      tools: dict[str, Any], j_name: str) -> dict[str, Any]:
    selected_names = [*REQUIRED_TOOLS, j_name]
    selected_tools = {
        name: {"path": str(tools["tools"][name]["path"]), "sha256": tools["tools"][name]["sha256"]}
        for name in selected_names
    }
    return {
        "schema": "zkfdo-sj-pipeline-identity-v1",
        "corpus_layer": args.corpus_layer,
        "script_sha256": sha256(__file__),
        "reused_module_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in local_module_closure(REUSED_MODULE_ROOTS)
        },
        "entrypoint": normalized["entrypoint"],
        "entrypoint_relative": normalized["entrypoint_relative"],
        "project_root": normalized["project_root"],
        "library_paths": normalized["library_paths"],
        "base_input": normalized["base_input"],
        "base_input_sha256": normalized["base_input_sha256"],
        "normalized_base_input_sha256": normalized["normalized_base_input_sha256"],
        "closure_sha256": normalized["closure_sha256"],
        "revision": normalized["revision"],
        "tools_manifest": {"path": tools["manifest_path"],
                           "sha256": tools["manifest_sha256"]},
        "tools": selected_tools,
        "static_ranking_sha256": sha256(ROOT / "configs/static-ranking.json"),
        "budgets": {
            "s_main_seconds": args.s_budget_seconds,
            "s_attempt_seconds": args.s_attempt_seconds,
            "j_candidate_limit": args.j_candidates,
            "j_request_seconds": args.j_request_seconds,
            "j_total_seconds": args.j_total_seconds,
            "probe_request_seconds": args.probe_seconds,
            "baseline_command_seconds": args.baseline_seconds,
            "preparation_command_seconds": args.preparation_command_seconds,
            "postcheck_command_seconds": args.postcheck_seconds,
            "minimum_free_gib": args.min_free_gib,
            "run_minimum_free_gib": args.run_min_free_gib,
            "maximum_disk_gib": args.max_disk_gib,
        },
        "seed_policy": {"initial_seed": args.initial_seed, "rule": "increment_per_pass",
                        "candidate_order": "first_unique_candidates_in_campaign_ledger_order",
                        "candidate_limit": args.j_candidates},
        "j": {"jobs": 1, "probe_enabled": True, "probe_classes": args.probe_classes,
              "verified_version_output": tools["tools"][j_name].get("verified_version_output")},
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--entrypoint", type=Path, required=True)
    value.add_argument("--base-input", type=Path, required=True)
    value.add_argument("--project-root", type=Path, required=True)
    value.add_argument("--library-path", type=Path, action="append", default=[])
    value.add_argument("--tools-manifest", type=Path, required=True)
    value.add_argument("--out", type=Path, required=True)
    value.add_argument("--corpus-layer", choices=("development", "regression", "hunt"),
                       required=True)
    value.add_argument("--s-budget-seconds", type=float, default=DEFAULT_S_SECONDS)
    value.add_argument("--s-attempt-seconds", type=float, default=DEFAULT_ATTEMPT_SECONDS)
    value.add_argument("--j-candidates", type=int)
    value.add_argument("--j-request-seconds", type=float, default=DEFAULT_J_REQUEST_SECONDS)
    value.add_argument("--j-total-seconds", type=float, default=DEFAULT_J_TOTAL_SECONDS)
    value.add_argument("--j-extra-total-seconds", type=float, default=0.0)
    value.add_argument("--probe-seconds", type=int, default=DEFAULT_PROBE_SECONDS)
    value.add_argument("--probe-classes", choices=("unresolved", "all"), default="unresolved")
    value.add_argument("--j-jobs", type=int, choices=(1,), default=1)
    value.add_argument("--initial-seed", type=int, default=DEFAULT_SEED)
    value.add_argument("--min-free-gib", type=float, default=DEFAULT_FREE_GIB)
    value.add_argument("--run-min-free-gib", type=float, default=25.0)
    value.add_argument("--max-disk-gib", type=float, default=DEFAULT_MAX_DISK_GIB)
    value.add_argument("--baseline-seconds", type=float, default=300.0)
    value.add_argument("--preparation-command-seconds", type=float, default=600.0)
    value.add_argument("--postcheck-seconds", type=float, default=300.0)
    value.add_argument("--dry-run", action="store_true")
    return value


def validate_args(args: argparse.Namespace) -> None:
    for name in ("s_budget_seconds", "s_attempt_seconds", "j_request_seconds", "j_total_seconds",
                 "min_free_gib", "run_min_free_gib", "max_disk_gib", "baseline_seconds",
                 "preparation_command_seconds", "postcheck_seconds"):
        setattr(args, name, positive(getattr(args, name), name.replace("_", "-")))
    if args.j_candidates is not None and (
            isinstance(args.j_candidates, bool) or args.j_candidates <= 0):
        raise ValueError("j-candidates must be positive when set")
    if (isinstance(args.j_extra_total_seconds, bool)
            or not isinstance(args.j_extra_total_seconds, (int, float))
            or not math.isfinite(args.j_extra_total_seconds)
            or args.j_extra_total_seconds < 0):
        raise ValueError("j-extra-total-seconds must be finite and nonnegative")
    args.j_extra_total_seconds = float(args.j_extra_total_seconds)
    if isinstance(args.probe_seconds, bool) or args.probe_seconds <= 0:
        raise ValueError("probe-seconds must be positive")
    if isinstance(args.initial_seed, bool) or not 0 < args.initial_seed < 2**64:
        raise ValueError("initial-seed must be a nonzero u64")
    if args.j_total_seconds < args.j_request_seconds:
        raise ValueError("j-total-seconds must be at least j-request-seconds")
    output = args.out.resolve()
    project = args.project_root.resolve()
    roots = [project, *(path.resolve() for path in args.library_path)]
    if any(output == root or root.is_relative_to(output) or output.is_relative_to(root) for root in roots):
        raise ValueError("output and declared source roots must be disjoint")


def write_startup_failure(args: argparse.Namespace, phase: str, error: BaseException,
                          started: float, cpu_started: float) -> bool:
    raw_output = args.out.absolute()
    output = args.out.resolve()
    if raw_output.is_symlink():
        return False
    if output.exists():
        administrative = {".sj-pipeline.lock", ".sj-pipeline-lock-history"}
        unowned = [path for path in output.iterdir() if path.name not in administrative]
        if not output.is_dir() or output.is_symlink() or unowned:
            return False
    else:
        output.mkdir(parents=True, exist_ok=False)
    argument_record = {
        key: ([str(item) for item in value] if isinstance(value, list)
              else str(value) if isinstance(value, Path) else value)
        for key, value in sorted(vars(args).items())
    }
    identity = {
        "schema": "zkfdo-sj-startup-failure-identity-v1",
        "script_sha256": sha256(__file__),
        "arguments": argument_record,
    }
    identity_sha = value_sha(identity)
    terminal_status = getattr(error, "status", None)
    if terminal_status is None:
        terminal_status = "tools_preflight_failed" if phase == "tools_manifest" else "startup_preflight_failed"
    wall_seconds = time.monotonic() - started
    cpu_seconds = time.process_time() - cpu_started
    stages = {
        name: {
            "stage": name,
            "status": "failed" if name == "preflight" else "not_run",
            "terminal_status": terminal_status if name == "preflight" else "not_observed",
            "wall_seconds": wall_seconds if name == "preflight" else 0.0,
            "cpu_seconds": cpu_seconds if name == "preflight" else 0.0,
        }
        for name in STAGES
    }
    stages["preflight"].update(phase=phase, error=f"{type(error).__name__}: {error}")
    stages["summary"].update(status="reported_after_failure", terminal_status="completed")
    ledger = {
        "schema": SCHEMA,
        "status": terminal_status,
        "complete": True,
        "engine_started": False,
        "identity_sha256": identity_sha,
        "corpus_layer": args.corpus_layer,
        "created_utc": utc(),
        "finished_utc": utc(),
        "stages": stages,
        "commands": [],
        "error": f"{type(error).__name__}: {error}",
        "limitations": ["Startup preflight did not reach an executable engine stage."],
    }
    summary = {
        "schema": "zkfdo-sj-summary-v1",
        "pipeline_status": terminal_status,
        "engine_started": False,
        "identity_sha256": identity_sha,
        "stages": [stages[name] for name in STAGES],
        "costs": {"stage_wall_seconds": wall_seconds, "stage_cpu_seconds": cpu_seconds,
                  "command_wall_seconds": 0.0, "command_cpu_seconds": 0.0},
        "corpus_layer": args.corpus_layer,
        "candidates": {
            "preserved": 0, "eligible_unique": 0, "selected_for_j": 0,
            "selection_limit": args.j_candidates,
            "diagnostic_limit_active": args.j_candidates is not None,
            "total": 0, "judged": 0,
            "in_progress_interrupted": 0, "pending_not_run": 0,
        },
        "j": {"requests": [], "verdict_counts": {}, "probe_status_counts": {},
              "probe_attempt_counts": {}},
        "validated_counterexample": [],
        "not_observed": [{"scope": "pipeline", "status": "not_observed",
                          "reason": terminal_status}],
        "safety_conclusion": "not_made",
        "limitations": ledger["limitations"],
    }
    atomic_json(output / "identity.json", identity)
    atomic_json(output / "ledger.json", ledger)
    atomic_json(output / "summary.json", summary)
    atomic_text(output / "summary.md",
        "# S→J pipeline summary\n\n"
        f"- Pipeline status: `{terminal_status}`\n"
        "- Engine started: `false`\n"
        f"- Startup phase: `{phase}`\n"
        "- Candidate state: total `0`, judged `0`, in progress interrupted `0`, "
        "pending not run `0`\n"
        "- Safety conclusion: `not_made`\n"
    )
    return True


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    started, cpu_started = time.monotonic(), time.process_time()
    output_validated = False
    phase = "argument_validation"
    pipeline: Pipeline | None = None
    output_lock: OutputLock | None = None
    try:
        validate_args(args)
        output_validated = True
        phase = "output_lock"
        output_lock = OutputLock(args.out).acquire()
        startup_started, startup_cpu_started = time.monotonic(), time.process_time()
        startup_phases: list[dict[str, Any]] = []

        def begin_phase(name: str) -> tuple[str, float, float]:
            return name, time.monotonic(), time.process_time()

        def finish_phase(receipt: tuple[str, float, float]) -> None:
            name, phase_started, phase_cpu_started = receipt
            startup_phases.append({
                "phase": name,
                "wall_seconds": time.monotonic() - phase_started,
                "cpu_seconds": time.process_time() - phase_cpu_started,
            })

        phase = "input_and_revision_preflight"
        receipt = begin_phase(phase)
        try:
            normalized = normalize_inputs(
                args.entrypoint, args.base_input, args.project_root, args.library_path)
        finally:
            finish_phase(receipt)
        phase = "tools_manifest"
        receipt = begin_phase(phase)
        try:
            tools, j_name = load_tools(args.tools_manifest)
        finally:
            finish_phase(receipt)
        phase = "identity"
        receipt = begin_phase(phase)
        try:
            identity = pipeline_identity(args, normalized, tools, j_name)
        finally:
            finish_phase(receipt)
        startup_preflight = {
            "wall_seconds": time.monotonic() - startup_started,
            "cpu_seconds": time.process_time() - startup_cpu_started,
            "phases": startup_phases,
        }
        pipeline = Pipeline(args, normalized, tools, j_name, identity, startup_preflight)
        if args.dry_run:
            print(json.dumps(pipeline.dry_run(), ensure_ascii=False, sort_keys=True, indent=2))
            return 0
        return 0 if pipeline.run() else 1
    except (OSError, ValueError, KeyError, PipelineError, json.JSONDecodeError) as error:
        if output_validated and pipeline is None and output_lock is not None:
            try:
                write_startup_failure(args, phase, error, started, cpu_started)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as record_error:
                print(f"STARTUP RECORD FAILED: {type(record_error).__name__}: {record_error}", file=sys.stderr)
        print(f"STOP: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    finally:
        if output_lock is not None:
            try:
                output_lock.release()
            except (OSError, ValueError, PipelineError, json.JSONDecodeError) as error:
                print(f"LOCK RELEASE FAILED: {type(error).__name__}: {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
