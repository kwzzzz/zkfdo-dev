#!/usr/bin/env python3
"""Run a preregistered Policy-A campaign through one measured subprocess path.

The public ledger never parses or embeds counterexample values.  Candidate files stay
under the ignored output directory and are represented by relative paths and hashes.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterable


SCHEMA_VERSION = 1
POLL_SECONDS = 0.01
GROUP_EXIT_GRACE_SECONDS = 2.0
ANSI = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]")
SEED = re.compile(rb"Random Seed:\s*(\d+)")
GENERATION = re.compile(rb"Generation:\s*(\d+)/")
EXECUTION_TIME = re.compile(
    rb"Execution Time\s*:\s*([0-9]+(?:\.[0-9]+)?)(ns|us|\xc2\xb5s|ms|s)"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SpecError(ValueError):
    pass


class InfrastructureError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    """Hash relative names, node kinds, symlink text, and regular-file bytes."""
    root = root.resolve()
    if not root.is_dir():
        raise SpecError(f"source snapshot is not a directory: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            kind = b"L"
            payload = os.readlink(path).encode()
        elif path.is_dir():
            kind = b"D"
            payload = b""
        elif path.is_file():
            kind = b"F"
            payload = bytes.fromhex(sha256_file(path))
        else:
            raise SpecError(f"unsupported source node: {path}")
        digest.update(kind + len(relative).to_bytes(8, "big") + relative)
        digest.update(len(payload).to_bytes(8, "big") + payload)
    return digest.hexdigest()


def ensure_no_symlinks(root: Path) -> None:
    links = [path for path in root.rglob("*") if path.is_symlink()]
    if links:
        raise SpecError(f"source snapshot contains symlink: {links[0]}")


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True).encode() + b"\n"


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise InfrastructureError(f"atomic-write temporary already exists: {temporary}")
    data = json_bytes(value)
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise InfrastructureError(f"atomic-write temporary already exists: {temporary}")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        raise InfrastructureError(f"candidate temporary already exists: {temporary}")
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def relative_to(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise SpecError(f"{label} must be a lowercase SHA-256")
    return value


def positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise SpecError(f"{label} must be positive")
    return float(value)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as error:
        raise SpecError(f"invalid JSON {path}: {error}") from error


def load_spec(path: Path) -> tuple[dict[str, Any], str]:
    path = path.resolve()
    data = path.read_bytes()
    try:
        spec = json.loads(data)
    except Exception as error:
        raise SpecError(f"invalid spec JSON: {error}") from error
    validate_spec(spec)
    return spec, hashlib.sha256(data).hexdigest()


def validate_spec(spec: Any) -> None:
    if not isinstance(spec, dict) or spec.get("schema_version") != SCHEMA_VERSION:
        raise SpecError("spec schema_version must be 1")
    method = spec.get("method")
    if method not in {"whole", "split"}:
        raise SpecError("method must be whole or split")
    positive_number(spec.get("total_budget_seconds"), "total_budget_seconds")
    positive_number(spec.get("attempt_cap_seconds"), "attempt_cap_seconds")
    seed = spec.get("initial_seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 < seed < 2**64:
        raise SpecError("initial_seed must be a nonzero u64")
    if spec.get("seed_rule") != "increment_per_pass":
        raise SpecError("seed_rule must be increment_per_pass")
    if spec.get("concurrency") != 1:
        raise SpecError("concurrency must be 1")
    if not isinstance(spec.get("require_pinned_command_tools", True), bool):
        raise SpecError("require_pinned_command_tools must be boolean")
    if not isinstance(spec.get("require_save_output", True), bool):
        raise SpecError("require_save_output must be boolean")

    snapshots = spec.get("source_snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise SpecError("source_snapshots must be nonempty")
    snapshot_ids: set[str] = set()
    for index, snapshot in enumerate(snapshots):
        if not isinstance(snapshot, dict):
            raise SpecError(f"source_snapshots[{index}] must be an object")
        identifier = snapshot.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in snapshot_ids:
            raise SpecError("source snapshot IDs must be nonempty and unique")
        snapshot_ids.add(identifier)
        if not isinstance(snapshot.get("path"), str):
            raise SpecError(f"source snapshot {identifier} has no path")
        require_sha(snapshot.get("tree_sha256"), f"source snapshot {identifier} tree_sha256")
        patterns = snapshot.get("candidate_globs")
        if not isinstance(patterns, list) or not patterns or not all(
            isinstance(pattern, str) and pattern for pattern in patterns
        ):
            raise SpecError(f"source snapshot {identifier} needs candidate_globs")
        if snapshot.get("expected_baseline_candidates") != 0:
            raise SpecError("A-02 requires zero candidates in every clean baseline")

    targets = spec.get("targets")
    if not isinstance(targets, list) or not targets:
        raise SpecError("targets must be nonempty")
    expected_count = 1 if method == "whole" else 21
    if len(targets) != expected_count:
        raise SpecError(f"{method} requires exactly {expected_count} target(s)")
    target_ids: set[str] = set()
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise SpecError(f"targets[{index}] must be an object")
        identifier = target.get("target_id")
        if not isinstance(identifier, str) or not identifier or identifier in target_ids:
            raise SpecError("target IDs must be nonempty and unique")
        target_ids.add(identifier)
        if target.get("source_snapshot_id") not in snapshot_ids:
            raise SpecError(f"target {identifier} references an unknown source snapshot")
        entrypoint = target.get("entrypoint_relative")
        if (
            not isinstance(entrypoint, str)
            or not entrypoint
            or Path(entrypoint).is_absolute()
            or ".." in Path(entrypoint).parts
        ):
            raise SpecError(f"target {identifier} entrypoint_relative is unsafe")
        require_sha(target.get("entrypoint_sha256"), f"target {identifier} entrypoint_sha256")
        command = target.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(argument, str) and argument for argument in command
        ):
            raise SpecError(f"target {identifier} command must be a nonempty argv list")
        joined = "\0".join(command)
        if "{entrypoint}" not in joined or "{workspace}" not in joined:
            raise SpecError(f"target {identifier} command must use cloned entrypoint/workspace")
        if spec.get("require_save_output", True) and "--save_output" not in command:
            raise SpecError(f"target {identifier} command must request --save_output")
        compile_command = target.get("preflight_compile_command")
        if compile_command is not None and (
            not isinstance(compile_command, list)
            or not compile_command
            or not all(isinstance(argument, str) and argument for argument in compile_command)
        ):
            raise SpecError(f"target {identifier} preflight compile command is invalid")

    transport = spec.get("seed_transport")
    if not isinstance(transport, dict) or transport.get("kind") not in {
        "mutation_settings",
        "placeholder",
    }:
        raise SpecError("seed_transport.kind must be mutation_settings or placeholder")
    if transport["kind"] == "mutation_settings":
        argument = transport.get("argument")
        if not isinstance(argument, str) or not argument:
            raise SpecError("mutation_settings transport needs an argument")
        base = transport.get("base")
        if base is not None and not isinstance(base, dict):
            raise SpecError("mutation_settings base must be an object")
    elif any("{seed}" not in "\0".join(target["command"]) for target in targets):
        raise SpecError("placeholder seed transport requires {seed} in every command")

    pinned = spec.get("pinned_files", [])
    if not isinstance(pinned, list):
        raise SpecError("pinned_files must be an array")
    labels: set[str] = set()
    for item in pinned:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            raise SpecError("every pinned file needs a label")
        if item["label"] in labels:
            raise SpecError("pinned file labels must be unique")
        labels.add(item["label"])
        if not isinstance(item.get("path"), str):
            raise SpecError(f"pinned file {item['label']} has no path")
        require_sha(item.get("sha256"), f"pinned file {item['label']} sha256")
    pinned_trees = spec.get("pinned_trees", [])
    if not isinstance(pinned_trees, list):
        raise SpecError("pinned_trees must be an array")
    tree_labels: set[str] = set()
    for item in pinned_trees:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            raise SpecError("every pinned tree needs a label")
        if item["label"] in tree_labels:
            raise SpecError("pinned tree labels must be unique")
        tree_labels.add(item["label"])
        if not isinstance(item.get("path"), str):
            raise SpecError(f"pinned tree {item['label']} has no path")
        require_sha(item.get("tree_sha256"), f"pinned tree {item['label']} tree_sha256")


def candidate_inventory(root: Path, patterns: Iterable[str]) -> dict[str, str]:
    inventory: dict[str, str] = {}
    root = root.resolve()
    for pattern in patterns:
        for raw in glob.glob(str(root / pattern), recursive=True):
            path = Path(raw)
            if not path.is_file() or path.is_symlink():
                continue
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError as error:
                raise InfrastructureError(f"candidate escaped workspace: {path}") from error
            inventory[relative] = sha256_file(resolved)
    return dict(sorted(inventory.items()))


def verify_pins(spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for pin in spec.get("pinned_files", []):
        path = Path(pin["path"]).resolve()
        actual = sha256_file(path) if path.is_file() else None
        if actual != pin["sha256"]:
            raise SpecError(f"pinned file changed or is absent: {pin['label']}")
        rows.append({"label": pin["label"], "path": str(path), "sha256": actual})
    return rows


def verify_tree_pins(spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for pin in spec.get("pinned_trees", []):
        path = Path(pin["path"]).resolve()
        actual = tree_sha256(path) if path.is_dir() else None
        if actual != pin["tree_sha256"]:
            raise SpecError(f"pinned tree changed or is absent: {pin['label']}")
        rows.append({"label": pin["label"], "path": str(path), "tree_sha256": actual})
    return rows


def verify_command_pins(spec: dict[str, Any], pinned_files: list[dict[str, Any]]) -> None:
    if not spec.get("require_pinned_command_tools", True):
        return
    pinned = {str(Path(row["path"]).resolve()): row["sha256"] for row in pinned_files}
    commands = [target["command"] for target in spec["targets"]]
    commands.extend(
        target["preflight_compile_command"]
        for target in spec["targets"]
        if target.get("preflight_compile_command") is not None
    )
    for command in commands:
        binary = Path(command[0]).resolve()
        expected = pinned.get(str(binary))
        if expected is None:
            raise SpecError(f"command executable is not pinned: {binary}")
        if not binary.is_file() or sha256_file(binary) != expected:
            raise SpecError(f"command executable changed: {binary}")


def verify_plan(spec: dict[str, Any], clean_roots: dict[str, Path]) -> dict[str, Any]:
    plan_pin = next((item for item in spec.get("pinned_files", []) if item["label"] == "plan"), None)
    if plan_pin is None:
        return {"status": "not_applicable", "reason": "no pinned plan declared"}
    plan = load_json(Path(plan_pin["path"]))
    plan_targets = plan.get("targets") if isinstance(plan, dict) else None
    if spec["method"] == "whole":
        return {
            "status": "provenance_only",
            "reason": "the split plan is pinned but does not define the whole entrypoint",
        }
    if not isinstance(plan_targets, list) or len(plan_targets) != len(spec["targets"]):
        raise SpecError("pinned plan target denominator differs from the spec")
    checked = 0
    for index, (declared, planned) in enumerate(zip(spec["targets"], plan_targets, strict=True)):
        if planned.get("target_id") != declared["target_id"]:
            raise SpecError(f"pinned plan order differs at target {index}")
        definition = planned.get("definition", {})
        project_root = Path(definition.get("project_root", ""))
        try:
            planned_entrypoint = Path(definition["entrypoint"]).relative_to(project_root)
        except (KeyError, ValueError) as error:
            raise SpecError(f"plan entrypoint is outside project root at target {index}") from error
        if planned_entrypoint.as_posix() != declared["entrypoint_relative"]:
            raise SpecError(f"declared entrypoint differs from plan at target {index}")
        source_fingerprints = planned.get("source_fingerprints")
        snapshot_fingerprints = planned.get("snapshot_fingerprints")
        if not isinstance(source_fingerprints, list) or not isinstance(snapshot_fingerprints, list):
            raise SpecError(f"pinned plan target {index} lacks fingerprints")
        snapshot_hashes = sorted(item.get("sha256") for item in snapshot_fingerprints)
        source_hashes = sorted(item.get("sha256") for item in source_fingerprints)
        if snapshot_hashes != source_hashes:
            raise SpecError(f"plan source/snapshot fingerprints differ at target {index}")
        clean = clean_roots[declared["source_snapshot_id"]]
        for fingerprint in source_fingerprints:
            path = Path(fingerprint["path"])
            try:
                relative = path.relative_to(project_root)
            except ValueError as error:
                raise SpecError(f"plan fingerprint is outside project root at target {index}") from error
            clean_file = clean / relative
            if not clean_file.is_file() or sha256_file(clean_file) != fingerprint.get("sha256"):
                raise SpecError(f"clean source differs from plan fingerprint: {relative}")
            checked += 1
    return {"status": "verified", "target_count": len(plan_targets), "fingerprints": checked}


def expand_command(template: list[str], replacements: dict[str, str]) -> list[str]:
    expanded = []
    for argument in template:
        for key, value in replacements.items():
            argument = argument.replace("{" + key + "}", value)
        if re.search(r"\{[a-z_]+\}", argument):
            raise SpecError(f"unexpanded command placeholder: {argument}")
        expanded.append(argument)
    return expanded


def wait_status_code(status: int) -> int:
    return os.waitstatus_to_exitcode(status)


def rusage_record(usage: Any) -> dict[str, Any]:
    cpu = float(usage.ru_utime + usage.ru_stime)
    if sys.platform == "darwin":
        rss = int(usage.ru_maxrss) if usage.ru_maxrss > 0 else None
        unit = "Darwin wait4 ru_maxrss bytes"
    elif sys.platform.startswith("linux"):
        rss = int(usage.ru_maxrss * 1024) if usage.ru_maxrss > 0 else None
        unit = "Linux wait4 ru_maxrss KiB normalized to bytes"
    else:
        rss = None
        unit = "unsupported host unit"
    return {
        "cpu_seconds": cpu,
        "cpu_scope": "wait4 terminated process and children accumulated by the host kernel",
        "ru_maxrss_bytes": rss,
        "ru_maxrss_scope": unit,
        "aggregate_process_tree_peak_memory_bytes": None,
        "aggregate_process_tree_peak_memory_unknown_reason": (
            "wait4 ru_maxrss is not a sampled simultaneous sum across all live process-group members"
        ),
    }


@dataclass
class StreamState:
    lock: threading.Lock
    observations: list[dict[str, Any]]
    seed: int | None = None
    generation: int | None = None
    candidate_seen: bool = False
    no_candidate_seen: bool = False
    engine_reported_execution_seconds: list[float] | None = None


def observe_line(line: bytes, state: StreamState, stream_name: str, clock_ns: Callable[[], int]) -> None:
    clean = ANSI.sub(b"", line)
    kinds = []
    if b"NOT SAFE" in clean:
        kinds.append("not_safe")
    if b"No Counter Example Found" in clean:
        kinds.append("no_counterexample")
    seed = SEED.search(clean)
    generation = GENERATION.search(clean)
    execution_time = EXECUTION_TIME.search(clean)
    with state.lock:
        if seed:
            state.seed = int(seed.group(1))
            kinds.append("random_seed")
        if generation:
            state.generation = int(generation.group(1))
            kinds.append("generation")
        if execution_time:
            magnitude = float(execution_time.group(1))
            unit = execution_time.group(2).decode()
            scale = {"ns": 1e-9, "us": 1e-6, "µs": 1e-6, "ms": 1e-3, "s": 1.0}[unit]
            seconds = magnitude * scale
            if state.engine_reported_execution_seconds is None:
                state.engine_reported_execution_seconds = []
            state.engine_reported_execution_seconds.append(seconds)
            state.observations.append(
                {
                    "kind": "engine_reported_execution_time",
                    "stream": stream_name,
                    "campaign_offset_seconds": clock_ns() / 1e9,
                    "engine_reported_seconds": seconds,
                    "meaning": "value printed by zkFuzz; distinct from parent observation offset",
                }
            )
        if "not_safe" in kinds:
            state.candidate_seen = True
        if "no_counterexample" in kinds:
            state.no_candidate_seen = True
        for kind in kinds:
            state.observations.append(
                {"kind": kind, "stream": stream_name, "campaign_offset_seconds": clock_ns() / 1e9}
            )


def drain_stream(
    stream: Any,
    temporary_log: Path,
    state: StreamState,
    stream_name: str,
    campaign_start_ns: int,
    errors: list[str],
) -> None:
    buffer = b""
    try:
        with temporary_log.open("xb") as output:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                output.write(chunk)
                buffer += chunk
                parts = re.split(rb"[\r\n]", buffer)
                buffer = parts.pop()
                for line in parts:
                    observe_line(line, state, stream_name, lambda: time.monotonic_ns() - campaign_start_ns)
            if buffer:
                observe_line(buffer, state, stream_name, lambda: time.monotonic_ns() - campaign_start_ns)
            output.flush()
            os.fsync(output.fileno())
    except Exception as error:
        errors.append(f"{stream_name}: {type(error).__name__}: {error}")
    finally:
        stream.close()


def process_group_exists(group: int) -> bool:
    try:
        os.killpg(group, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_group(group: int) -> None:
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass


def verify_group_empty(group: int) -> bool:
    deadline = time.monotonic() + GROUP_EXIT_GRACE_SECONDS
    while process_group_exists(group):
        kill_group(group)
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)
    return True


def finish_logs(
    threads: list[threading.Thread],
    temporary: list[Path],
    final: list[Path],
    errors: list[str],
) -> None:
    for thread in threads:
        thread.join(GROUP_EXIT_GRACE_SECONDS)
        if thread.is_alive():
            raise InfrastructureError("log drain did not finish after process-group cleanup")
    if errors:
        raise InfrastructureError("log drain failed: " + "; ".join(errors))
    for source, destination in zip(temporary, final, strict=True):
        os.replace(source, destination)


def spawn_and_measure(
    command: list[str],
    attempt_dir: Path,
    deadline_ns: int,
    campaign_start_ns: int,
    cancel_check: Callable[[], bool],
) -> dict[str, Any]:
    stdout_path = attempt_dir / "stdout.log"
    stderr_path = attempt_dir / "stderr.log"
    temporary = [attempt_dir / "stdout.log.tmp", attempt_dir / "stderr.log.tmp"]
    state = StreamState(threading.Lock(), [])
    start_call_ns = time.monotonic_ns()
    if start_call_ns >= deadline_ns:
        spawn_call_end = time.monotonic_ns()
        for path in (stdout_path, stderr_path):
            atomic_write_bytes(path, b"")
        return {
            "outcome": "deadline_before_spawn",
            "process_started": False,
            "process_start_offset_seconds": None,
            "process_end_offset_seconds": None,
            "spawn_call_end_offset_seconds": (spawn_call_end - campaign_start_ns) / 1e9,
            "exit_code": None,
            "timed_out": True,
            "cancelled": False,
            "reaped": None,
            "process_group_empty": None,
            "resource": None,
            "observations": [],
            "reported_seed": None,
            "last_generation": None,
            "engine_reported_execution_seconds": [],
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "error": None,
        }
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        spawn_call_end = time.monotonic_ns()
        for path in (stdout_path, stderr_path):
            atomic_write_bytes(path, b"")
        return {
            "outcome": "spawn_error",
            "process_started": False,
            "process_start_offset_seconds": None,
            "process_end_offset_seconds": None,
            "spawn_call_end_offset_seconds": (spawn_call_end - campaign_start_ns) / 1e9,
            "exit_code": None,
            "timed_out": False,
            "cancelled": False,
            "reaped": None,
            "process_group_empty": None,
            "resource": None,
            "observations": [],
            "reported_seed": None,
            "last_generation": None,
            "engine_reported_execution_seconds": [],
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "error": str(error),
        }
    process_start_ns = time.monotonic_ns()
    assert process.stdout is not None and process.stderr is not None
    drain_errors: list[str] = []
    threads = [
        threading.Thread(
            target=drain_stream,
            args=(process.stdout, temporary[0], state, "stdout", campaign_start_ns, drain_errors),
            daemon=True,
        ),
        threading.Thread(
            target=drain_stream,
            args=(process.stderr, temporary[1], state, "stderr", campaign_start_ns, drain_errors),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    status = None
    usage = None
    timed_out = False
    cancelled = False
    group_kill_sent = False
    while status is None:
        try:
            waited, raw_status, raw_usage = os.wait4(process.pid, os.WNOHANG)
        except InterruptedError:
            continue
        except ChildProcessError as error:
            kill_group(process.pid)
            raise InfrastructureError("direct child could not be reaped with wait4") from error
        if waited == process.pid:
            status, usage = raw_status, raw_usage
            break
        if cancel_check():
            cancelled = True
            kill_group(process.pid)
            group_kill_sent = True
        elif time.monotonic_ns() >= deadline_ns:
            timed_out = True
            kill_group(process.pid)
            group_kill_sent = True
        if cancelled or timed_out:
            while True:
                try:
                    waited, status, usage = os.wait4(process.pid, 0)
                    break
                except InterruptedError:
                    continue
            if waited != process.pid:
                raise InfrastructureError("wait4 reaped an unexpected process")
            break
        time.sleep(min(POLL_SECONDS, max((deadline_ns - time.monotonic_ns()) / 1e9, 0)))

    process.returncode = wait_status_code(status)
    process_end_ns = time.monotonic_ns()
    residual_killed = process_group_exists(process.pid)
    if residual_killed:
        kill_group(process.pid)
        group_kill_sent = True
    group_empty = verify_group_empty(process.pid)
    if not group_empty:
        raise InfrastructureError("process group remained live after kill/reap cleanup")
    finish_logs(threads, temporary, [stdout_path, stderr_path], drain_errors)
    exit_code = process.returncode
    if cancelled:
        outcome = "cancelled"
    elif timed_out:
        outcome = "timeout"
    elif exit_code != 0:
        outcome = "engine_nonzero"
    elif state.candidate_seen:
        outcome = "candidate"
    elif state.no_candidate_seen:
        outcome = "no_candidate"
    else:
        outcome = "finished_unknown"
    return {
        "outcome": outcome,
        "process_started": True,
        "process_start_offset_seconds": (process_start_ns - campaign_start_ns) / 1e9,
        "process_end_offset_seconds": (process_end_ns - campaign_start_ns) / 1e9,
        "spawn_call_end_offset_seconds": (process_start_ns - campaign_start_ns) / 1e9,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "cancelled": cancelled,
        "reaped": True,
        "process_group_empty": group_empty,
        "residual_process_group_killed": residual_killed,
        "process_group_kill_sent": group_kill_sent,
        "resource": rusage_record(usage),
        "observations": sorted(state.observations, key=lambda row: row["campaign_offset_seconds"]),
        "reported_seed": state.seed,
        "last_generation": state.generation,
        "engine_reported_execution_seconds": state.engine_reported_execution_seconds or [],
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "error": None,
    }


def verify_entrypoints(spec: dict[str, Any], roots: dict[str, Path]) -> None:
    for target in spec["targets"]:
        entrypoint = roots[target["source_snapshot_id"]] / target["entrypoint_relative"]
        if not entrypoint.is_file() or sha256_file(entrypoint) != target["entrypoint_sha256"]:
            raise SpecError(f"target entrypoint changed or is absent: {target['target_id']}")


def prepare_seed(spec: dict[str, Any], attempt_dir: Path, seed: int) -> tuple[dict[str, str], str | None]:
    transport = spec["seed_transport"]
    replacements = {"seed": str(seed)}
    if transport["kind"] == "placeholder":
        return replacements, None
    settings = dict(transport.get("base", {}))
    settings["seed"] = seed
    path = attempt_dir / "mutation-settings.json"
    atomic_write(path, settings)
    replacements["seed_settings"] = str(path)
    return replacements, sha256_file(path)


def command_with_seed(
    spec: dict[str, Any], target: dict[str, Any], replacements: dict[str, str]
) -> list[str]:
    command = expand_command(target["command"], replacements)
    transport = spec["seed_transport"]
    if transport["kind"] == "mutation_settings":
        if transport["argument"] in command:
            raise SpecError("seed transport argument is already present in command template")
        command.extend([transport["argument"], replacements["seed_settings"]])
    if spec.get("require_save_output", True) and "--save_output" not in command:
        raise SpecError("actual zkFuzz command must contain --save_output")
    return command


def public_command(command: list[str], output_root: Path, preflight_root: Path) -> list[str]:
    replacements = sorted(
        [(str(output_root.resolve()), "$CAMPAIGN"), (str(preflight_root.resolve()), "$PREFLIGHT")],
        key=lambda item: len(item[0]),
        reverse=True,
    )
    result = []
    for argument in command:
        for source, destination in replacements:
            argument = argument.replace(source, destination)
        result.append(argument)
    return result


def public_text(value: str | None, output_root: Path, preflight_root: Path) -> str | None:
    if value is None:
        return None
    return public_command([value], output_root, preflight_root)[0]


def read_preflight(spec: dict[str, Any], spec_sha256: str, ledger_path: Path) -> tuple[dict[str, Path], Path]:
    ledger_path = ledger_path.resolve()
    ledger = load_json(ledger_path)
    if ledger.get("schema_version") != 1 or ledger.get("kind") != "policy_a_preflight":
        raise SpecError("invalid preflight ledger")
    if ledger.get("spec_sha256") != spec_sha256:
        raise SpecError("preflight belongs to a different spec")
    if ledger.get("status") == "failed":
        raise SpecError("preflight compile or validation failed; actual campaign is refused")
    root = ledger_path.parent
    snapshots = {}
    for row in ledger.get("source_snapshots", []):
        snapshot = root / row["copied_path"]
        expected = next(item for item in spec["source_snapshots"] if item["id"] == row["id"])
        if tree_sha256(snapshot) != expected["tree_sha256"]:
            raise SpecError(f"preflight snapshot changed: {row['id']}")
        snapshots[row["id"]] = snapshot
    if set(snapshots) != {item["id"] for item in spec["source_snapshots"]}:
        raise SpecError("preflight snapshot denominator differs from spec")
    verify_entrypoints(spec, snapshots)
    return snapshots, root


def run_campaign(
    spec: dict[str, Any],
    spec_sha256: str,
    snapshots: dict[str, Path],
    preflight_root: Path,
    output: Path,
    cancel_check: Callable[[], bool] = lambda: False,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    output = output.resolve()
    for snapshot in snapshots.values():
        snapshot = snapshot.resolve()
        if output == snapshot or output.is_relative_to(snapshot):
            raise SpecError("campaign output must not be inside a frozen source snapshot")
    output.mkdir(parents=True, exist_ok=False)
    attempts_root = output / "attempts"
    attempts_root.mkdir()
    total_seconds = float(spec["total_budget_seconds"])
    cap_seconds = float(spec["attempt_cap_seconds"])
    total_ns = int(total_seconds * 1e9)
    cap_ns = int(cap_seconds * 1e9)
    started_at = utc_now()
    campaign_start_ns = time.monotonic_ns()
    campaign_deadline_ns = campaign_start_ns + total_ns
    attempts: list[dict[str, Any]] = []
    duplicate_hashes: dict[str, str] = {}
    termination = None
    fatal_error = None
    targets = spec["targets"]

    while termination is None:
        if max_attempts is not None and len(attempts) >= max_attempts:
            termination = "self_test_attempt_limit"
            break
        if cancel_check():
            termination = "cancelled"
            break
        dispatch_ns = time.monotonic_ns()
        remaining_before_ns = max(campaign_deadline_ns - dispatch_ns, 0)
        if remaining_before_ns == 0:
            termination = "budget_exhausted"
            break
        index = len(attempts)
        target_index = index % len(targets)
        pass_index = index // len(targets)
        target = targets[target_index]
        seed = spec["initial_seed"] + pass_index
        if seed >= 2**64:
            termination = "seed_overflow"
            fatal_error = "increment_per_pass exceeded u64"
            break
        allocated_ns = min(cap_ns, remaining_before_ns)
        attempt_deadline_ns = dispatch_ns + allocated_ns
        attempt_dir = attempts_root / f"{index:06d}"
        attempt_dir.mkdir()
        workspace = attempt_dir / "workspace"
        row: dict[str, Any] = {
            "attempt_index": index,
            "pass_index": pass_index,
            "target_index": target_index,
            "target_id": target["target_id"],
            "seed": seed,
            "dispatch_offset_seconds": (dispatch_ns - campaign_start_ns) / 1e9,
            "remaining_before_seconds": remaining_before_ns / 1e9,
            "allocated_attempt_seconds": allocated_ns / 1e9,
        }
        try:
            shutil.copytree(snapshots[target["source_snapshot_id"]], workspace, symlinks=True)
            if tree_sha256(workspace) != next(
                snapshot["tree_sha256"]
                for snapshot in spec["source_snapshots"]
                if snapshot["id"] == target["source_snapshot_id"]
            ):
                raise InfrastructureError("attempt workspace differs from frozen clean snapshot")
            entrypoint = workspace / target["entrypoint_relative"]
            replacements, settings_sha = prepare_seed(spec, attempt_dir, seed)
            replacements.update(
                {
                    "workspace": str(workspace),
                    "entrypoint": str(entrypoint),
                    "attempt_dir": str(attempt_dir),
                }
            )
            command = command_with_seed(spec, target, replacements)
            if str(snapshots[target["source_snapshot_id"]].resolve()) in "\0".join(command):
                raise SpecError("command references frozen source directly instead of attempt workspace")
            execution = spawn_and_measure(
                command, attempt_dir, attempt_deadline_ns, campaign_start_ns, cancel_check
            )
            patterns = next(
                snapshot["candidate_globs"]
                for snapshot in spec["source_snapshots"]
                if snapshot["id"] == target["source_snapshot_id"]
            )
            found = candidate_inventory(workspace, patterns)
            candidates = []
            for relative, digest in found.items():
                source = workspace / relative
                destination = attempt_dir / "candidates" / relative
                atomic_copy(source, destination)
                if sha256_file(destination) != digest:
                    raise InfrastructureError("candidate changed while it was preserved")
                candidate_row = {
                    "path": relative_to(destination, output),
                    "source_workspace_path": relative,
                    "sha256": digest,
                    "duplicate_of": duplicate_hashes.get(digest),
                }
                if digest not in duplicate_hashes:
                    duplicate_hashes[digest] = candidate_row["path"]
                candidates.append(candidate_row)
            if candidates and execution["outcome"] in {"no_candidate", "finished_unknown"}:
                execution["outcome"] = "candidate_file_without_not_safe_log"
            process_start = execution["process_start_offset_seconds"]
            reaped = execution["process_end_offset_seconds"]
            before_persist_ns = time.monotonic_ns()
            before_persist_offset = (before_persist_ns - campaign_start_ns) / 1e9
            spawn_call_end = execution["spawn_call_end_offset_seconds"]
            phase_end = reaped if reaped is not None else spawn_call_end
            pre_spawn_seconds = spawn_call_end - row["dispatch_offset_seconds"]
            process_wall_seconds = (
                None if process_start is None or reaped is None else reaped - process_start
            )
            cleanup_seconds = before_persist_offset - phase_end
            spawn_fatal = execution["outcome"] == "spawn_error"
            row.update(
                {
                    "seed_settings_sha256": settings_sha,
                    "command": public_command(command, output, preflight_root),
                    "command_sha256": hashlib.sha256(json_bytes(command)).hexdigest(),
                    "process_start_offset_seconds": process_start,
                    "process_end_offset_seconds": reaped,
                    "spawn_call_end_offset_seconds": spawn_call_end,
                    "pre_spawn_copy_settings_seconds": pre_spawn_seconds,
                    "startup_seconds": pre_spawn_seconds,
                    "process_wall_seconds": process_wall_seconds,
                    "cleanup_before_result_seconds": cleanup_seconds,
                    "outcome": execution["outcome"],
                    "exit_code": execution["exit_code"],
                    "timed_out": execution["timed_out"],
                    "cancelled": execution["cancelled"],
                    "process_started": execution["process_started"],
                    "reaped": execution["reaped"],
                    "process_group_empty": execution["process_group_empty"],
                    "residual_process_group_killed": execution.get("residual_process_group_killed"),
                    "process_group_kill_sent": execution.get("process_group_kill_sent"),
                    "resource": execution["resource"],
                    "reported_seed": execution["reported_seed"],
                    "last_generation": execution["last_generation"],
                    "engine_reported_execution_seconds": execution[
                        "engine_reported_execution_seconds"
                    ],
                    "engine_reported_execution_time_meaning": (
                        "values printed by zkFuzz; not parent wall or log observation offsets"
                    ),
                    "log_observations": execution["observations"],
                    "internal_candidate_time_seconds": None,
                    "internal_candidate_time_unknown_reason": (
                        "zkFuzz output exposes no engine-internal candidate creation timestamp"
                    ),
                    "stdout_path": relative_to(execution["stdout_path"], output),
                    "stderr_path": relative_to(execution["stderr_path"], output),
                    "spawn_error": public_text(execution["error"], output, preflight_root),
                    "candidates": candidates,
                    "fatal_error": (
                        f"spawn_error: {public_text(execution['error'], output, preflight_root)}"
                        if spawn_fatal
                        else None
                    ),
                }
            )
            result_path = attempt_dir / "result.json"
            persist_start = time.monotonic_ns()
            atomic_write(result_path, row)
            persist_end = time.monotonic_ns()
            completion_ns = persist_end
            row["result"] = {
                "path": relative_to(result_path, output),
                "sha256": sha256_file(result_path),
            }
            row["result_persistence_seconds"] = (persist_end - persist_start) / 1e9
            row["restart_cleanup_seconds"] = (
                pre_spawn_seconds + cleanup_seconds + row["result_persistence_seconds"]
            )
            row["completion_offset_seconds"] = (completion_ns - campaign_start_ns) / 1e9
            row["actual_attempt_wall_seconds"] = (completion_ns - dispatch_ns) / 1e9
            row["remaining_after_seconds"] = max(campaign_deadline_ns - completion_ns, 0) / 1e9
            row["attempt_overrun_seconds"] = max(completion_ns - attempt_deadline_ns, 0) / 1e9
            row["released_reservation_seconds"] = max(
                allocated_ns / 1e9 - row["actual_attempt_wall_seconds"], 0
            )
            attempts.append(row)
            if spawn_fatal:
                termination = "infrastructure_failure"
                fatal_error = row["fatal_error"]
            elif execution["cancelled"]:
                termination = "cancelled"
            elif completion_ns >= campaign_deadline_ns:
                termination = "budget_exhausted"
        except (SpecError, InfrastructureError, OSError) as error:
            termination = "infrastructure_failure"
            fatal_error = f"{type(error).__name__}: {error}"
            row["fatal_error"] = fatal_error
            row["completion_offset_seconds"] = (time.monotonic_ns() - campaign_start_ns) / 1e9
            attempts.append(row)

    campaign_end_ns = time.monotonic_ns()
    target_rows = []
    for target_index, target in enumerate(targets):
        rows = [row for row in attempts if row.get("target_id") == target["target_id"]]
        starts = sum(bool(row.get("process_started")) for row in rows)
        target_rows.append(
            {
                "target_index": target_index,
                "target_id": target["target_id"],
                "attempt_count": len(rows),
                "process_start_count": starts,
                "status": "started" if starts else "not_started",
                "not_started_reason": None if starts else termination,
            }
        )
    known_cpu = [
        row["resource"]["cpu_seconds"]
        for row in attempts
        if isinstance(row.get("resource"), dict)
        and row["resource"].get("cpu_seconds") is not None
    ]
    known_rss = [
        row["resource"]["ru_maxrss_bytes"]
        for row in attempts
        if isinstance(row.get("resource"), dict)
        and row["resource"].get("ru_maxrss_bytes") is not None
    ]
    pre_spawn_sum = sum(
        row.get("pre_spawn_copy_settings_seconds", 0.0) for row in attempts
    )
    process_wall_sum = sum(
        row.get("process_wall_seconds") or 0.0 for row in attempts
    )
    cleanup_sum = sum(row.get("cleanup_before_result_seconds", 0.0) for row in attempts)
    persistence_sum = sum(row.get("result_persistence_seconds", 0.0) for row in attempts)
    first_process_start = next(
        (
            row["process_start_offset_seconds"]
            for row in attempts
            if row.get("process_start_offset_seconds") is not None
        ),
        None,
    )
    ledger = {
        "schema_version": 1,
        "kind": "policy_a_actual_campaign",
        "spec_sha256": spec_sha256,
        "campaign_id": spec.get("campaign_id"),
        "method": spec["method"],
        "clock": "host monotonic_ns; campaign origin immediately before first dispatch",
        "started_at": started_at,
        "finished_at": utc_now(),
        "total_budget_seconds": total_seconds,
        "attempt_cap_seconds": cap_seconds,
        "initial_seed": spec["initial_seed"],
        "seed_rule": spec["seed_rule"],
        "concurrency": 1,
        "campaign_wall_seconds": (campaign_end_ns - campaign_start_ns) / 1e9,
        "first_process_start_offset_seconds": first_process_start,
        "pre_spawn_copy_settings_seconds_sum": pre_spawn_sum,
        "process_wall_seconds_sum": process_wall_sum,
        "cleanup_before_result_seconds_sum": cleanup_sum,
        "attempt_result_persistence_seconds_sum": persistence_sum,
        "restart_cleanup_seconds_sum": pre_spawn_sum + cleanup_sum + persistence_sum,
        "remaining_seconds": max(campaign_deadline_ns - campaign_end_ns, 0) / 1e9,
        "overrun_seconds": max(campaign_end_ns - campaign_deadline_ns, 0) / 1e9,
        "termination_reason": termination,
        "fatal_error": fatal_error,
        "status": (
            "incomplete"
            if fatal_error or termination == "seed_overflow"
            else "interrupted"
            if termination == "cancelled"
            else "self_test_completed"
            if termination == "self_test_attempt_limit"
            else "completed"
        ),
        "outcome_counts": dict(Counter(row.get("outcome", "infrastructure_failure") for row in attempts)),
        "actual_cpu_seconds_sum": sum(known_cpu) if known_cpu else None,
        "actual_cpu_measurement": (
            "sum of per-attempt wait4 CPU; timeout descendants that were not waited by the direct child may be absent"
        ),
        "ru_maxrss_bytes_max": max(known_rss) if known_rss else None,
        "aggregate_process_tree_peak_memory_bytes": None,
        "aggregate_process_tree_peak_memory_unknown_reason": (
            "wait4 ru_maxrss is not a simultaneous aggregate of live process-group RSS"
        ),
        "targets": target_rows,
        "attempts": attempts,
        "limitations": [
            "Candidate log offsets are parent observations, not engine-internal creation times.",
            "Candidate location or hash is unreviewed and is not a confirmed defect.",
            "Per-attempt source copying and zkFuzz internal compilation are included in campaign wall; preflight compilation is separate and is not claimed to be reused.",
        ],
    }
    ledger_path = output / "ledger.json"
    ledger_persist_start = time.monotonic_ns()
    atomic_write(ledger_path, ledger)
    ledger_persist_end = time.monotonic_ns()
    # The self-referential final-ledger write is outside campaign wall and reported by the CLI.
    return {
        "ledger": ledger,
        "ledger_path": ledger_path,
        "ledger_sha256": sha256_file(ledger_path),
        "ledger_persistence_seconds": (ledger_persist_end - ledger_persist_start) / 1e9,
    }


def preflight(spec_path: Path, output: Path) -> dict[str, Any]:
    spec, spec_sha = load_spec(spec_path)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    started = time.monotonic_ns()
    pins = verify_pins(spec)
    tree_pins = verify_tree_pins(spec)
    verify_command_pins(spec, pins)
    copied: dict[str, Path] = {}
    snapshot_rows = []
    for snapshot in spec["source_snapshots"]:
        source = Path(snapshot["path"]).resolve()
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise SpecError("preflight output and clean source snapshot must be disjoint")
        ensure_no_symlinks(source)
        if tree_sha256(source) != snapshot["tree_sha256"]:
            raise SpecError(f"clean source tree changed: {snapshot['id']}")
        baseline = candidate_inventory(source, snapshot["candidate_globs"])
        if baseline:
            raise SpecError(f"clean source tree contains candidate files: {snapshot['id']}")
        destination = output / "snapshots" / snapshot["id"]
        timer = time.monotonic_ns()
        shutil.copytree(source, destination, symlinks=True)
        copy_seconds = (time.monotonic_ns() - timer) / 1e9
        if tree_sha256(destination) != snapshot["tree_sha256"]:
            raise InfrastructureError(f"copied source tree differs: {snapshot['id']}")
        copied[snapshot["id"]] = destination
        snapshot_rows.append(
            {
                "id": snapshot["id"],
                "source_path": str(source),
                "copied_path": relative_to(destination, output),
                "tree_sha256": snapshot["tree_sha256"],
                "baseline_candidate_count": 0,
                "copy_wall_seconds": copy_seconds,
            }
        )
    verify_entrypoints(spec, copied)
    plan_validation = verify_plan(spec, copied)

    compile_rows = []
    timeout = positive_number(spec.get("preflight_compile_timeout_seconds", 600), "compile timeout")
    for index, target in enumerate(spec["targets"]):
        template = target.get("preflight_compile_command")
        if template is None:
            compile_rows.append(
                {
                    "target_index": index,
                    "target_id": target["target_id"],
                    "status": "not_requested",
                    "wall_seconds": None,
                    "note": "zkFuzz internal compilation cannot be separated by this runner",
                }
            )
            continue
        directory = output / "compile" / f"{index:04d}"
        directory.mkdir(parents=True)
        (directory / "artifacts").mkdir()
        workspace = directory / "workspace"
        shutil.copytree(copied[target["source_snapshot_id"]], workspace, symlinks=True)
        entrypoint = workspace / target["entrypoint_relative"]
        command = expand_command(
            template,
            {
                "workspace": str(workspace),
                "entrypoint": str(entrypoint),
                "compile_output": str(directory / "artifacts"),
            },
        )
        timer = time.monotonic_ns()
        execution = spawn_and_measure(
            command,
            directory,
            timer + int(timeout * 1e9),
            timer,
            lambda: False,
        )
        if (
            execution["process_started"]
            and not execution["timed_out"]
            and not execution["cancelled"]
            and execution["exit_code"] == 0
        ):
            compile_status = "succeeded"
        elif execution["outcome"] == "timeout":
            compile_status = "timeout"
        elif execution["outcome"] == "spawn_error":
            compile_status = "spawn_error"
        else:
            compile_status = "failed"
        compile_rows.append(
            {
                "target_index": index,
                "target_id": target["target_id"],
                "status": compile_status,
                "backend_outcome": execution["outcome"],
                "exit_code": execution["exit_code"],
                "timed_out": execution["timed_out"],
                "process_started": execution["process_started"],
                "wall_seconds": (time.monotonic_ns() - timer) / 1e9,
                "resource": execution["resource"],
                "stdout_path": relative_to(execution["stdout_path"], output),
                "stderr_path": relative_to(execution["stderr_path"], output),
                "reuse_claim": False,
            }
        )
    compile_failures = sum(
        row["status"] not in {"succeeded", "not_requested"} for row in compile_rows
    )
    compile_not_requested = sum(row["status"] == "not_requested" for row in compile_rows)
    compile_status_counts = dict(Counter(row["status"] for row in compile_rows))
    compile_wall_sum = sum(
        row["wall_seconds"] for row in compile_rows if row["wall_seconds"] is not None
    )
    preflight_status = (
        "failed"
        if compile_failures
        else "passed_compile_not_requested"
        if compile_not_requested
        else "passed"
    )
    ledger = {
        "schema_version": 1,
        "kind": "policy_a_preflight",
        "spec_path": str(spec_path.resolve()),
        "spec_sha256": spec_sha,
        "started_at": started_at,
        "wall_seconds": (time.monotonic_ns() - started) / 1e9,
        "pinned_files": pins,
        "pinned_trees": tree_pins,
        "plan_validation": plan_validation,
        "source_snapshots": snapshot_rows,
        "compile": compile_rows,
        "compile_failure_count": compile_failures,
        "compile_not_requested_count": compile_not_requested,
        "compile_status_counts": compile_status_counts,
        "compile_wall_seconds_sum": compile_wall_sum,
        "status": preflight_status,
        "compile_reuse_claim": False,
        "note": "preflight is outside campaign wall; zkFuzz may compile again internally",
    }
    ledger_path = output / "preflight.json"
    atomic_write(ledger_path, ledger)
    return {"ledger_path": ledger_path, "ledger_sha256": sha256_file(ledger_path), "ledger": ledger}


def fake_child(arguments: argparse.Namespace) -> int:
    if arguments.spawn_descendant_marker:
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import pathlib,time,sys; time.sleep(float(sys.argv[2])); pathlib.Path(sys.argv[1]).write_text('survived')",
                arguments.spawn_descendant_marker,
                str(arguments.descendant_delay),
            ]
        )
    if arguments.seed is not None:
        print(f"Random Seed: {arguments.seed}", flush=True)
    if arguments.mode == "candidate":
        print("Verification: NOT SAFE", flush=True)
        print("Execution Time : 12.5ms", flush=True)
        if arguments.candidate:
            path = Path(arguments.candidate)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"opaque_fake_candidate":true}\n')
    elif arguments.mode == "no_candidate":
        print("Verification: No Counter Example Found", flush=True)
        print("Execution Time : 12.5ms", flush=True)
    elif arguments.mode == "nonzero":
        print("synthetic engine failure", file=sys.stderr, flush=True)
        return 7
    elif arguments.mode == "sleep":
        time.sleep(arguments.sleep_seconds)
    return 0


def self_test(output: Path) -> dict[str, Any]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / "fixture-source"
    source.mkdir()
    (source / "a.circom").write_text("template A() {}\ncomponent main = A();\n")
    source_hash = tree_sha256(source)
    entry_hash = sha256_file(source / "a.circom")
    script = Path(__file__).resolve()

    def spec_for(mode: str, targets: int = 1, cap: float = 0.2, total: float = 1.0) -> dict[str, Any]:
        rows = []
        for index in range(targets):
            candidate = "{workspace}/same_counterexample.json"
            command = [
                sys.executable,
                str(script),
                "_fake-child",
                "--mode",
                mode,
                "--seed",
                "{seed}",
            ]
            if mode == "candidate":
                command.extend(["--candidate", candidate])
            rows.append(
                {
                    "target_id": f"target-{index}",
                    "source_snapshot_id": "clean",
                    "entrypoint_relative": "a.circom",
                    "entrypoint_sha256": entry_hash,
                    "command": command
                    + [
                        "--workspace-placeholder",
                        "{workspace}",
                        "--entrypoint-placeholder",
                        "{entrypoint}",
                    ],
                }
            )
        return {
            "schema_version": 1,
            "campaign_id": "fake",
            "method": "whole" if targets == 1 else "split",
            "total_budget_seconds": total,
            "attempt_cap_seconds": cap,
            "initial_seed": 2026092931,
            "seed_rule": "increment_per_pass",
            "concurrency": 1,
            "require_save_output": False,
            "source_snapshots": [
                {
                    "id": "clean",
                    "path": str(source),
                    "tree_sha256": source_hash,
                    "candidate_globs": ["**/*_counterexample.json"],
                    "expected_baseline_candidates": 0,
                }
            ],
            "targets": rows,
            "seed_transport": {"kind": "placeholder"},
            "pinned_files": [],
        }

    cases = {}
    for name, mode, attempt_count in [
        ("candidate_duplicate", "candidate", 3),
        ("no_candidate", "no_candidate", 2),
        ("engine_nonzero", "nonzero", 2),
    ]:
        spec = spec_for(mode)
        validate_spec(spec)
        case = run_campaign(
            spec,
            hashlib.sha256(json_bytes(spec)).hexdigest(),
            {"clean": source},
            output,
            output / name,
            max_attempts=attempt_count,
        )
        cases[name] = {
            "ledger": relative_to(case["ledger_path"], output),
            "sha256": case["ledger_sha256"],
        }

    timeout_spec = spec_for("sleep", cap=0.05, total=0.2)
    timeout_spec["targets"][0]["command"].extend(
        [
            "--sleep-seconds",
            "1",
            "--spawn-descendant-marker",
            str(output / "descendant-survived"),
            "--descendant-delay",
            "0.25",
        ]
    )
    timeout_case = run_campaign(
        timeout_spec,
        hashlib.sha256(json_bytes(timeout_spec)).hexdigest(),
        {"clean": source},
        output,
        output / "timeout",
        max_attempts=1,
    )
    time.sleep(0.3)
    if (output / "descendant-survived").exists():
        raise AssertionError("timed-out descendant survived")
    cases["timeout"] = {
        "ledger": relative_to(timeout_case["ledger_path"], output),
        "sha256": timeout_case["ledger_sha256"],
    }

    spawn_spec = spec_for("no_candidate")
    spawn_spec["targets"][0]["command"][0] = str(output / "missing-executable")
    spawn_case = run_campaign(
        spawn_spec,
        hashlib.sha256(json_bytes(spawn_spec)).hexdigest(),
        {"clean": source},
        output,
        output / "spawn_error",
        max_attempts=2,
    )
    cases["spawn_error"] = {
        "ledger": relative_to(spawn_case["ledger_path"], output),
        "sha256": spawn_case["ledger_sha256"],
    }

    cancel_spec = spec_for("sleep", cap=1.0, total=2.0)
    cancel_spec["targets"][0]["command"].extend(["--sleep-seconds", "1"])
    cancel_at = time.monotonic() + 0.05
    cancel_case = run_campaign(
        cancel_spec,
        hashlib.sha256(json_bytes(cancel_spec)).hexdigest(),
        {"clean": source},
        output,
        output / "cancel",
        cancel_check=lambda: time.monotonic() >= cancel_at,
    )
    cases["cancel"] = {
        "ledger": relative_to(cancel_case["ledger_path"], output),
        "sha256": cancel_case["ledger_sha256"],
    }

    order_spec = spec_for("no_candidate", targets=21, cap=0.2, total=5.0)
    order_case = run_campaign(
        order_spec,
        hashlib.sha256(json_bytes(order_spec)).hexdigest(),
        {"clean": source},
        output,
        output / "target_order_seed_pass",
        max_attempts=23,
    )
    cases["target_order_seed_pass"] = {
        "ledger": relative_to(order_case["ledger_path"], output),
        "sha256": order_case["ledger_sha256"],
    }

    candidate_rows = load_json(output / cases["candidate_duplicate"]["ledger"])["attempts"]
    order_rows = load_json(output / cases["target_order_seed_pass"]["ledger"])["attempts"]
    spawn_ledger = load_json(output / cases["spawn_error"]["ledger"])

    checks = {
        "candidate_continues": len(cases) > 0
        and len(candidate_rows) == 3,
        "duplicate_preserved": all(
            row["candidates"] for row in candidate_rows
        ),
        "residual_budget_released": all(
            row["remaining_after_seconds"] < row["remaining_before_seconds"]
            and row["released_reservation_seconds"] > 0
            for row in candidate_rows
        ),
        "engine_time_separate": all(
            row["engine_reported_execution_seconds"] == [0.0125]
            and any(
                observation["kind"] == "engine_reported_execution_time"
                and "campaign_offset_seconds" in observation
                for observation in row["log_observations"]
            )
            for row in candidate_rows
        ),
        "timeout_reaped": load_json(output / cases["timeout"]["ledger"])["attempts"][0]["reaped"] is True,
        "spawn_failure_is_fatal": len(spawn_ledger["attempts"]) == 1
        and spawn_ledger["termination_reason"] == "infrastructure_failure",
        "engine_nonzero_continues": len(load_json(output / cases["engine_nonzero"]["ledger"])["attempts"]) == 2,
        "cancel_stops": load_json(output / cases["cancel"]["ledger"])["termination_reason"] == "cancelled",
        "target_order_fixed": [row["target_id"] for row in order_rows]
        == [f"target-{index}" for index in range(21)] + ["target-0", "target-1"],
        "seed_increments_per_pass": [row["seed"] for row in order_rows]
        == [2026092931] * 21 + [2026092932] * 2,
    }
    if not all(checks.values()):
        raise AssertionError(f"self-test failed: {checks}")
    summary = {"schema_version": 1, "kind": "policy_a_fake_self_test", "checks": checks, "cases": cases}
    path = output / "self-test.json"
    atomic_write(path, summary)
    return {"summary_path": path, "summary_sha256": sha256_file(path), "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    hash_parser = subparsers.add_parser("hash-tree")
    hash_parser.add_argument("--path", type=Path, required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--spec", type=Path, required=True)
    preflight_parser.add_argument("--output", type=Path, required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--spec", type=Path, required=True)
    run_parser.add_argument("--preflight", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--cancel-file", type=Path)
    self_parser = subparsers.add_parser("self-test")
    self_parser.add_argument("--output", type=Path, required=True)
    fake = subparsers.add_parser("_fake-child")
    fake.add_argument("--mode", choices=["candidate", "no_candidate", "nonzero", "sleep"], required=True)
    fake.add_argument("--seed", type=int)
    fake.add_argument("--candidate")
    fake.add_argument("--sleep-seconds", type=float, default=0.0)
    fake.add_argument("--spawn-descendant-marker")
    fake.add_argument("--descendant-delay", type=float, default=0.25)
    fake.add_argument("--workspace-placeholder")
    fake.add_argument("--entrypoint-placeholder")
    arguments = parser.parse_args(argv)
    if arguments.action == "hash-tree":
        path = arguments.path.resolve()
        print(json.dumps({"path": str(path), "tree_sha256": tree_sha256(path)}))
        return 0
    if arguments.action == "_fake-child":
        return fake_child(arguments)
    if not hasattr(os, "wait4") or not hasattr(os, "killpg"):
        raise SystemExit("Policy-A engine requires Unix wait4 and process groups")
    exit_code = 0
    if arguments.action == "preflight":
        result = preflight(arguments.spec, arguments.output)
        if result["ledger"]["status"] == "failed":
            exit_code = 2
    elif arguments.action == "self-test":
        result = self_test(arguments.output)
    else:
        spec, spec_sha = load_spec(arguments.spec)
        snapshots, preflight_root = read_preflight(spec, spec_sha, arguments.preflight)
        result = run_campaign(
            spec,
            spec_sha,
            snapshots,
            preflight_root,
            arguments.output,
            cancel_check=(
                (lambda: arguments.cancel_file.exists())
                if arguments.cancel_file is not None
                else (lambda: False)
            ),
        )
        if result["ledger"]["status"] != "completed":
            exit_code = 2
    print(
        json.dumps(
            {key: str(value) if isinstance(value, Path) else value for key, value in result.items() if key != "ledger" and key != "summary"},
            ensure_ascii=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
