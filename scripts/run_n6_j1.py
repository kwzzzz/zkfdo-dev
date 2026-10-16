#!/usr/bin/env python3
"""Run the locked N6 J request index sequentially; never generate candidates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from n6_j1_cache_cleanup import cleanup_revision, initialize_cache, sha256
from run_policy_a_engine import tree_sha256


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = ROOT / "runs/n6-j1-2026-10-09.noindex/request-index.json"
DEFAULT_OUTPUT = ROOT / "runs/n6-j1-2026-10-09.noindex/j-execute.noindex"
ENGINE = ROOT / "runs/l07-2026-10-05/tools/zkfDO"
ENGINE_SHA256 = "e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed"
CIRCOM = Path("/Users/miiz/.cargo/bin/circom")
CIRCOM_SHA256 = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
MIN_FREE_BYTES = 40 * 1024**3
TIME_BIN = Path("/usr/bin/time")
RSS_RE = re.compile(r"^\s*(\d+)\s+maximum resident set size\s*$", re.MULTILINE)


class RunnerError(RuntimeError):
    pass


class DiskGuardStop(RunnerError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RunnerError(message)


def checked_sha(path: Path, expected: str, label: str) -> None:
    require(path.is_file(), f"{label} missing: {path}")
    actual = sha256(path)
    require(actual == expected, f"{label} SHA-256 mismatch: {path}: {actual}")


def checked_request_sources(row: dict[str, Any], request_json: dict[str, Any],
                            sequence: int) -> None:
    source_root = Path(request_json.get("source_root", ""))
    wrapper = Path(request_json.get("component_wrapper", ""))
    entrypoint = Path(request_json.get("entrypoint", ""))
    require(source_root.is_absolute() and source_root.is_dir() and
            wrapper.is_absolute() and entrypoint.is_absolute(),
            f"request source paths invalid at {sequence}")
    source_root = source_root.resolve()
    wrapper = wrapper.resolve()
    entrypoint = entrypoint.resolve()
    require(wrapper.is_relative_to(source_root) and entrypoint.is_relative_to(source_root),
            f"wrapper/entrypoint outside source_root at {sequence}")
    checked_sha(wrapper, row.get("component_wrapper_sha256", ""),
                f"wrapper {sequence}")
    checked_sha(entrypoint, row.get("entrypoint_sha256", ""),
                f"entrypoint {sequence}")
    libraries = request_json.get("library_paths")
    require(isinstance(libraries, list) and bool(libraries) and
            all(isinstance(path, str) and Path(path).is_absolute() and
                Path(path).is_dir() for path in libraries),
            f"request library paths invalid at {sequence}")
    candidate = request_json.get("candidate")
    require(isinstance(candidate, dict) and candidate.get("format") == "zkfuzz" and
            candidate.get("path") == row.get("candidate_path"),
            f"request candidate binding mismatch at {sequence}")
    checked_sha(Path(row["candidate_path"]), row["candidate_sha256"],
                f"candidate {sequence}")


def checked_spec(name: str, expected_sha: str,
                 cache: dict[Path, tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    require(isinstance(name, str) and bool(name) and
            not Path(name).is_absolute(), f"invalid relative spec path: {name}")
    path = (ROOT / name).resolve()
    require(path.is_relative_to(ROOT), f"spec outside repository: {path}")
    if path not in cache:
        checked_sha(path, expected_sha, "J source spec")
        spec = json.loads(path.read_text())
        require(isinstance(spec, dict), f"source spec is not an object: {path}")
        cache[path] = (expected_sha, spec)
    require(cache[path][0] == expected_sha, f"source spec SHA inconsistent: {path}")
    return cache[path][1]


def checked_target(spec: dict[str, Any], target_index: int,
                   target_id: str | None, method: str,
                   trees: dict[Path, str]) -> tuple[Path, Path, dict[str, Any]]:
    require(spec.get("method") == ("whole" if method == "W" else "split"),
            f"source spec method mismatch: {method}")
    targets = spec.get("targets")
    require(isinstance(targets, list) and type(target_index) is int and
            0 <= target_index < len(targets), f"source target index invalid: {target_index}")
    target = targets[target_index]
    require(isinstance(target, dict) and target.get("target_id") == target_id,
            f"source target ID mismatch: {target_id}")
    snapshots = spec.get("source_snapshots")
    require(isinstance(snapshots, list), "source snapshots missing")
    by_id = {item.get("id"): item for item in snapshots if isinstance(item, dict)}
    require(len(by_id) == len(snapshots), "duplicate or invalid source snapshots")
    snapshot = by_id.get(target.get("source_snapshot_id"))
    require(isinstance(snapshot, dict), f"target source snapshot missing: {target_id}")
    root_text, expected_tree = snapshot.get("path"), snapshot.get("tree_sha256")
    require(isinstance(root_text, str) and Path(root_text).is_absolute() and
            isinstance(expected_tree, str) and re.fullmatch(r"[0-9a-f]{64}", expected_tree),
            f"invalid source snapshot pin: {target_id}")
    source_root = Path(root_text).resolve()
    require(source_root.is_dir(), f"source snapshot missing: {source_root}")
    if source_root in trees:
        require(trees[source_root] == expected_tree,
                f"conflicting source tree pins: {source_root}")
    else:
        trees[source_root] = expected_tree
    relative = target.get("entrypoint_relative")
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(),
            f"source target entrypoint invalid: {target_id}")
    entrypoint = (source_root / relative).resolve()
    require(entrypoint.is_relative_to(source_root),
            f"source target leaves snapshot: {target_id}")
    return entrypoint, source_root, target


def preflight_libraries(target: dict[str, Any], snapshot_root: Path) -> list[str]:
    command = target.get("preflight_compile_command")
    require(isinstance(command, list) and all(isinstance(arg, str) for arg in command),
            "preflight compile command missing")
    libraries: list[str] = []
    for position, token in enumerate(command):
        if token == "-l":
            require(position + 1 < len(command), "preflight library argument missing")
            value = command[position + 1].replace("{workspace}", str(snapshot_root))
            path = Path(value).resolve()
            require(path.is_absolute() and path.is_dir(),
                    f"preflight library path missing: {path}")
            libraries.append(str(path))
    require(bool(libraries), "preflight library paths missing")
    return libraries


def validate_source_bindings(index_rows: list[dict[str, Any]], inventory: dict[str, Any],
                             requests: list[dict[str, Any]]) -> None:
    """Bind every request to the frozen W/S specs and hash each used source tree once."""
    inventory_rows = inventory.get("rows")
    require(inventory.get("status") == "verified" and
            isinstance(inventory_rows, list) and len(inventory_rows) == len(index_rows),
            "candidate inventory rows do not match request index")
    by_candidate = {item.get("candidate_sha256"): item for item in inventory_rows
                    if isinstance(item, dict)}
    require(len(by_candidate) == len(index_rows),
            "candidate inventory SHA values missing or duplicated")
    spec_cache: dict[Path, tuple[str, dict[str, Any]]] = {}
    trees: dict[Path, str] = {}
    for sequence, (row, request) in enumerate(zip(index_rows, requests)):
        source = by_candidate.get(row.get("candidate_sha256"))
        require(isinstance(source, dict), f"candidate source inventory missing: {sequence}")
        bindings = (("scope", "lane"), ("revision_id", "identifier"),
                    ("unit_id", "unit_id"), ("seed", "seed"),
                    ("method", "method"), ("candidate_index", "candidate_index"),
                    ("target_id", "target_id"), ("original_target_id", "original_target_id"))
        require(all(row.get(index_key) == source.get(inventory_key)
                    for index_key, inventory_key in bindings) and
                row.get("attempt_number") == source.get("attempt_index", -1) + 1 and
                Path(row["candidate_path"]).resolve() ==
                Path(source["candidate_path"]).resolve(),
                f"request/inventory candidate binding mismatch: {sequence}")
        w_spec = checked_spec(source["whole_spec"], source["whole_spec_sha256"], spec_cache)
        method = row["method"]
        method_spec = (w_spec if method == "W" else
                       checked_spec(source["split_spec"], source["split_spec_sha256"],
                                    spec_cache))
        w_targets = w_spec.get("targets")
        require(isinstance(w_targets, list) and len(w_targets) == 1,
                f"W spec must have one target: {sequence}")
        entrypoint, _w_root, w_target = checked_target(
            w_spec, 0, w_targets[0].get("target_id"), "W", trees)
        wrapper, method_root, target = checked_target(
            method_spec, source["target_index"], source["target_id"], method, trees)
        require(source.get("source_snapshot_id") == target.get("source_snapshot_id"),
                f"inventory source snapshot ID mismatch: {sequence}")
        require(row.get("entrypoint_sha256") == w_target.get("entrypoint_sha256") and
                row.get("component_wrapper_sha256") == target.get("entrypoint_sha256") and
                Path(request["entrypoint"]).resolve() == entrypoint and
                Path(request["component_wrapper"]).resolve() == wrapper,
                f"request/spec target binding mismatch: {sequence}")
        expected_root = Path(os.path.commonpath((entrypoint.parent, wrapper.parent))).resolve()
        require(Path(request["source_root"]).resolve() == expected_root,
                f"request source root differs from spec targets: {sequence}")
        require(request.get("library_paths") == preflight_libraries(target, method_root),
                f"request/preflight library path mismatch: {sequence}")
    for path, expected_sha in trees.items():
        require(tree_sha256(path) == expected_sha,
                f"source snapshot tree SHA-256 mismatch: {path}")


def validate_index(index_path: Path, index_sha256: str) -> dict[str, Any]:
    require(index_path.is_absolute(), "request index path must be absolute")
    checked_sha(index_path, index_sha256, "request index")
    index = json.loads(index_path.read_text())
    require(index.get("schema_version") == 1 and index.get("status") == "verified",
            "request index is not verified schema 1")
    require(index.get("engine_sha256") == ENGINE_SHA256 and
            Path(index.get("engine", "")) == ENGINE,
            "request index engine lock mismatch")
    require(index.get("circom_sha256") == CIRCOM_SHA256 and
            Path(index.get("circom", "")) == CIRCOM,
            "request index circom lock mismatch")
    checked_sha(ENGINE, ENGINE_SHA256, "locked J engine")
    checked_sha(CIRCOM, CIRCOM_SHA256, "locked circom")
    inventory_path = Path(index.get("inventory", ""))
    base_index_path = Path(index.get("base_index", ""))
    require(inventory_path.is_absolute() and base_index_path.is_absolute(),
            "inventory/base index paths must be absolute")
    checked_sha(inventory_path, index.get("inventory_sha256", ""), "candidate inventory")
    inventory = json.loads(inventory_path.read_text())
    checked_sha(base_index_path, index.get("base_index_sha256", ""), "base input index")
    base_index = json.loads(base_index_path.read_text())
    require(base_index.get("schema") == "n6-j1-base-inputs-v1" and
            isinstance(base_index.get("revisions"), dict), "invalid base input index")
    rows = index.get("requests")
    require(isinstance(rows, list) and index.get("request_count") == len(rows),
            "request index count mismatch")
    seen_groups: set[tuple[str, str]] = set()
    last_group: tuple[str, str] | None = None
    last_within_group: tuple[int, int, int, int] | None = None
    mem20_started = False
    checked_bases: set[str] = set()
    request_documents: list[dict[str, Any]] = []
    for sequence, row in enumerate(rows):
        require(isinstance(row, dict) and row.get("queue_order") == sequence,
                f"request order gap at {sequence}")
        scope = row.get("scope")
        revision_id = row.get("revision_id")
        require(scope in {"main", "mem20"} and isinstance(revision_id, str) and revision_id,
                f"invalid scope/revision at {sequence}")
        if scope == "mem20":
            mem20_started = True
        require(not (mem20_started and scope == "main"),
                "main request after mem20 request")
        group = (scope, revision_id)
        if group != last_group:
            require(group not in seen_groups, f"noncontiguous revision: {group}")
            seen_groups.add(group)
            last_group = group
            last_within_group = None
        require(row.get("method") in {"W", "S"} and
                isinstance(row.get("attempt_number"), int) and row["attempt_number"] >= 1,
                f"invalid method/attempt at {sequence}")
        require(isinstance(row.get("seed"), int) and
                isinstance(row.get("candidate_index"), int) and row["candidate_index"] >= 0,
                f"invalid seed/candidate index at {sequence}")
        within_group = (row["seed"], 0 if row["method"] == "W" else 1,
                        row["attempt_number"], row["candidate_index"])
        require(last_within_group is None or last_within_group <= within_group,
                f"seed/W/S/attempt order mismatch at {sequence}")
        last_within_group = within_group
        request = Path(row.get("request", ""))
        require(request.is_absolute(), f"nonabsolute request at {sequence}")
        checked_sha(request, row.get("request_sha256", ""), f"request {sequence}")
        request_json = json.loads(request.read_text())
        request_documents.append(request_json)
        require(request_json.get("schema") == "zkfdo-lifting-request-v1",
                f"request content mismatch at {sequence}")
        checked_request_sources(row, request_json, sequence)
        require(row.get("preparation_failure") is None or
                isinstance(row.get("preparation_failure"), str),
                f"invalid preparation failure at {sequence}")
        base_row = base_index["revisions"].get(revision_id)
        require(isinstance(base_row, dict), f"base revision missing: {revision_id}")
        if row["preparation_failure"] is None:
            require(base_row.get("status") == "passed" and
                    request_json.get("base_input") == base_row.get("base_input_path"),
                    f"base input binding mismatch at {sequence}")
            if revision_id not in checked_bases:
                checked_sha(Path(base_row["base_input_path"]),
                            base_row["base_input_sha256"], f"base input {revision_id}")
                checked_bases.add(revision_id)
        else:
            require(row["preparation_failure"] == "base_input_unavailable" and
                    base_row.get("status") == "base_input_unavailable",
                    f"preparation/base status mismatch at {sequence}")
    validate_source_bindings(rows, inventory, request_documents)
    return index


def groups(rows: list[dict[str, Any]]) -> list[tuple[str, int, str, list[dict[str, Any]]]]:
    result: list[tuple[str, int, str, list[dict[str, Any]]]] = []
    counts = {"main": 0, "mem20": 0}
    for row in rows:
        scope, revision_id = row["scope"], row["revision_id"]
        if not result or (result[-1][0], result[-1][2]) != (scope, revision_id):
            counts[scope] += 1
            result.append((scope, counts[scope], revision_id, []))
        result[-1][3].append(row)
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_state(output: Path, index_sha256: str, cache_root: Path) -> dict[str, Any]:
    path = output / "state.json"
    expected = {"schema_version": 1, "request_index_sha256": index_sha256,
                "engine_sha256": ENGINE_SHA256, "circom_sha256": CIRCOM_SHA256,
                "cache_root": str(cache_root)}
    if path.exists():
        state = json.loads(path.read_text())
        for key, value in expected.items():
            require(state.get(key) == value, f"state lock mismatch: {key}")
        require(isinstance(state.get("requests"), dict) and
                isinstance(state.get("revisions"), dict), "invalid J state")
        return state
    return {**expected, "status": "running", "requests": {}, "revisions": {},
            "started_at": datetime.now(timezone.utc).isoformat()}


def disk_free(path: Path) -> int:
    return shutil.disk_usage(path).free


def check_disk(output: Path, cache_root: Path) -> dict[str, int]:
    free = {"output_free_bytes": disk_free(output),
            "cache_free_bytes": disk_free(cache_root)}
    if min(free.values()) < MIN_FREE_BYTES:
        raise DiskGuardStop(f"less than 40 GiB free before next request: {free}")
    return free


def successful_result_issue(row: dict[str, Any], metrics: dict[str, Any],
                            result: Any) -> str | None:
    """Reject zero-exit results that cannot count as a completed J request."""
    if not isinstance(result, dict):
        return "result_not_object"
    if result.get("request_sha256") != row["request_sha256"] or \
            result.get("candidate_sha256") != row["candidate_sha256"]:
        return "result_input_sha_mismatch"
    rss = metrics.get("max_rss_bytes")
    if type(rss) is not int or rss <= 0:
        return "max_rss_missing_or_invalid"
    preparation = result.get("preparation")
    if not isinstance(preparation, dict) or preparation.get("status") != "ok":
        return "preparation_not_ok"
    sites = result.get("sites_found")
    if row["method"] == "W" and (type(sites) is not int or sites < 1):
        return "w_main_site_missing"
    return None


def result_for_row(row: dict[str, Any], request_dir: Path) -> tuple[Path, int] | None:
    found: list[tuple[Path, int]] = []
    for attempt_dir in sorted(request_dir.glob("attempt-*")):
        if not attempt_dir.is_dir():
            continue
        match = re.fullmatch(r"attempt-(\d{4})", attempt_dir.name)
        require(match is not None, f"unexpected attempt directory: {attempt_dir}")
        metrics_path = request_dir / f"{attempt_dir.name}.metrics.json"
        if not metrics_path.is_file():
            continue
        metrics = json.loads(metrics_path.read_text())
        if metrics.get("exit_code") != 0:
            continue
        result = attempt_dir / "result.json"
        if result.exists():
            try:
                value = json.loads(result.read_text())
            except (OSError, ValueError) as error:
                raise RunnerError(f"invalid previous zero-exit result JSON: {result}") from error
            issue = successful_result_issue(row, metrics, value)
            require(issue is None, f"invalid previous zero-exit result ({issue}): {result}")
            found.append((result, int(match.group(1))))
    require(len(found) <= 1, f"multiple completed results: {request_dir}")
    return found[0] if found else None


def next_attempt(request_dir: Path) -> int:
    existing = [int(match.group(1)) for item in request_dir.glob("attempt-*")
                if (match := re.fullmatch(r"attempt-(\d{4})", item.name))]
    return max(existing, default=0) + 1


def max_rss_bytes(stderr_path: Path) -> int | None:
    match = RSS_RE.search(stderr_path.read_text(errors="replace"))
    return int(match.group(1)) if match else None


def probe_time_l() -> dict[str, Any]:
    """Choose a measurement method before running any lifting request."""
    try:
        process = subprocess.run([str(TIME_BIN), "-l", "/usr/bin/true"],
                                 capture_output=True, text=True, check=False)
    except OSError as error:
        return {"measurement_method": "wait4", "exit_code": None,
                "max_rss_bytes": None, "time_probe_failure": str(error)}
    match = RSS_RE.search(process.stderr)
    passed = process.returncode == 0 and match is not None
    return {"measurement_method": "time-l" if passed else "wait4",
            "exit_code": process.returncode,
            "max_rss_bytes": int(match.group(1)) if match else None,
            "time_probe_failure": None if passed else process.stderr.strip() or
            "time -l returned no maximum resident set size"}


def run_with_rusage(command: list[str], stdout_path: Path,
                    stderr_path: Path, *, cwd: Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
        process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr)
        _pid, wait_status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(wait_status)
    rss_bytes = int(usage.ru_maxrss) * (1 if sys.platform == "darwin" else 1024)
    return {"exit_code": process.returncode,
            "wall_seconds": time.monotonic() - started,
            "max_rss_bytes": rss_bytes}


def run_lift(row: dict[str, Any], output_dir: Path, cache: Path,
             store: Path, attempt: int, measurement_method: str) -> dict[str, Any]:
    """Invoke the pinned engine once; output_dir must not already exist."""
    require(not output_dir.exists(), f"attempt output already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    prefix = output_dir.parent / f"attempt-{attempt:04d}"
    stdout_path = Path(str(prefix) + ".stdout.log")
    stderr_path = Path(str(prefix) + ".stderr.log")
    require(measurement_method in {"time-l", "wait4"}, "unknown measurement method")
    command = [str(ENGINE), "experiment", "lift",
               "--request", row["request"], "--output", str(output_dir),
               "--cache", str(cache), "--circom-bin", str(CIRCOM),
               "--instance-store", str(store)]
    if measurement_method == "wait4":
        metrics = run_with_rusage(command, stdout_path, stderr_path)
    else:
        started = time.monotonic()
        with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
            process = subprocess.run([str(TIME_BIN), "-l", *command],
                                     stdout=stdout, stderr=stderr, check=False)
        metrics = {"exit_code": process.returncode,
                   "wall_seconds": time.monotonic() - started,
                   "max_rss_bytes": max_rss_bytes(stderr_path)}
    return {**metrics, "measurement_method": measurement_method,
            "stdout_path": str(stdout_path), "stderr_path": str(stderr_path)}


def join_instances(result_paths: list[Path], output: Path, instance_path: Path,
                   measurement_method: str) -> dict[str, Any]:
    require(result_paths and not instance_path.exists(), "invalid or existing instance output")
    relative = [str(path.relative_to(output)) for path in result_paths]
    require(measurement_method in {"time-l", "wait4"}, "unknown measurement method")
    command = [str(ENGINE), "experiment", "lift-instances",
               "--result", *relative, "--output", str(instance_path)]
    stdout_path = instance_path.with_suffix(".stdout.log")
    stderr_path = instance_path.with_suffix(".stderr.log")
    if measurement_method == "wait4":
        metrics = run_with_rusage(command, stdout_path, stderr_path, cwd=output)
    else:
        started = time.monotonic()
        with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
            process = subprocess.run([str(TIME_BIN), "-l", *command], cwd=output,
                                     stdout=stdout, stderr=stderr, check=False)
        metrics = {"exit_code": process.returncode,
                   "wall_seconds": time.monotonic() - started,
                   "max_rss_bytes": max_rss_bytes(stderr_path)}
    return {**metrics, "measurement_method": measurement_method,
            "stdout_path": str(stdout_path), "stderr_path": str(stderr_path)}


def execute(index_path: Path, index_sha256: str, cache_root: Path,
            output: Path, *, cleanup_cache_per_revision: bool = False) -> dict[str, Any]:
    index = validate_index(index_path, index_sha256)
    require(cache_root.is_absolute() and cache_root.is_dir(),
            "--cache-root must be an existing absolute directory")
    cache_root = cache_root.resolve()
    output = output.resolve()
    require(not (output == cache_root or output.is_relative_to(cache_root) or
                 cache_root.is_relative_to(output)),
            "cache and output directories must be separate")
    output.mkdir(parents=True, exist_ok=True)
    state = load_state(output, index_sha256, cache_root)
    probe = probe_time_l()
    state["status"] = "running"
    state["measurement_method"] = probe["measurement_method"]
    state["time_probe"] = probe
    state.pop("stop_reason", None)
    state.pop("next_queue_order", None)
    state_path, attempts_path = output / "state.json", output / "attempts.jsonl"
    atomic_json(state_path, state)
    for scope, ordinal, revision_id, rows in groups(index["requests"]):
        revision_key = f"{scope}/{ordinal:04d}"
        revision_dir = output / scope / f"{ordinal:04d}"
        revision_dir.mkdir(parents=True, exist_ok=True)
        revision_state = state["revisions"].setdefault(revision_key, {
            "scope": scope, "revision_ordinal": ordinal, "revision_id": revision_id,
            "status": "running", "instance_store": str(revision_dir / "store"),
            "cache_path": str(cache_root / scope / f"{ordinal:04d}")})
        require(revision_state["revision_id"] == revision_id,
                f"revision state mismatch: {revision_key}")
        require(revision_state.get("cache_path") == str(cache_root / scope / f"{ordinal:04d}"),
                f"revision cache namespace mismatch: {revision_key}")
        cache_paths = [row.get("cache_path") for row in state["revisions"].values()]
        require(len(cache_paths) == len(set(cache_paths)),
                "two revisions share one cache namespace")
        atomic_json(state_path, state)
        result_paths: list[Path] = []
        for row in rows:
            queue_order = row["queue_order"]
            request_key = str(queue_order)
            request_dir = revision_dir / "requests" / f"{queue_order:06d}"
            previous = state["requests"].get(request_key)
            if previous:
                require(previous.get("request_sha256") == row["request_sha256"],
                        f"request state SHA mismatch: {queue_order}")
            if row["preparation_failure"] is not None:
                require(not previous or previous.get("status") == "preparation_failure",
                        f"preparation state mismatch: {queue_order}")
                if not previous:
                    entry = {"status": "preparation_failure", "queue_order": queue_order,
                             "scope": scope, "revision_id": revision_id,
                             "request": row["request"],
                             "request_sha256": row["request_sha256"],
                             "preparation_failure": row["preparation_failure"],
                             "result_path": None, "result_sha256": None,
                             "exit_code": None, "wall_seconds": None,
                             "max_rss_bytes": None}
                    state["requests"][request_key] = entry
                    append_jsonl(attempts_path, entry)
                    atomic_json(state_path, state)
                continue
            checked_sha(Path(row["candidate_path"]), row["candidate_sha256"],
                        f"candidate {queue_order}")
            try:
                existing = result_for_row(row, request_dir)
            except RunnerError as error:
                state["status"] = "result_invalid"
                state["stop_reason"] = str(error)
                state["next_queue_order"] = queue_order
                atomic_json(state_path, state)
                raise
            if existing:
                result_path, attempt = existing
                metrics = json.loads((request_dir / f"attempt-{attempt:04d}.metrics.json").read_text())
                if previous and previous.get("status") == "completed":
                    require(previous.get("result_path") == str(result_path) and
                            previous.get("result_sha256") == sha256(result_path),
                            f"completed result state mismatch: {queue_order}")
                else:
                    entry = {"status": "completed", "queue_order": queue_order,
                             "scope": scope, "revision_id": revision_id,
                             "request": row["request"],
                             "request_sha256": row["request_sha256"],
                             "preparation_failure": None,
                             "attempt": attempt, "resumed_result": True,
                             "result_path": str(result_path),
                             "result_sha256": sha256(result_path),
                             "exit_code": metrics["exit_code"],
                             "wall_seconds": metrics["wall_seconds"],
                             "max_rss_bytes": metrics["max_rss_bytes"]}
                    state["requests"][request_key] = entry
                    append_jsonl(attempts_path, entry)
                    atomic_json(state_path, state)
                result_paths.append(result_path)
                continue
            require(not previous or previous.get("status") != "completed",
                    f"completed result missing: {queue_order}")
            request_json = json.loads(Path(row["request"]).read_text())
            checked_request_sources(row, request_json, queue_order)
            try:
                free = check_disk(output, cache_root)
            except DiskGuardStop as error:
                state["status"] = "disk_guard_stopped"
                state["stop_reason"] = str(error)
                state["next_queue_order"] = queue_order
                atomic_json(state_path, state)
                raise
            cache = initialize_cache(cache_root, scope, ordinal,
                                     revision_id, index_sha256)
            attempt = next_attempt(request_dir)
            attempt_dir = request_dir / f"attempt-{attempt:04d}"
            metrics = run_lift(row, attempt_dir, cache, revision_dir / "store", attempt,
                               probe["measurement_method"])
            atomic_json(request_dir / f"attempt-{attempt:04d}.metrics.json", metrics)
            result_path = attempt_dir / "result.json"
            issue = None
            if metrics["exit_code"] == 0:
                if not result_path.is_file():
                    issue = "result_missing"
                else:
                    try:
                        result = json.loads(result_path.read_text())
                    except (OSError, ValueError, json.JSONDecodeError):
                        issue = "result_invalid_json"
                    else:
                        issue = successful_result_issue(row, metrics, result)
            event = {"status": "completed" if metrics["exit_code"] == 0 and issue is None
                     else "failed",
                     "queue_order": queue_order, "scope": scope,
                     "revision_id": revision_id, "request": row["request"],
                     "request_sha256": row["request_sha256"],
                     "preparation_failure": None,
                     "attempt": attempt, "result_path": str(result_path) if result_path.is_file() else None,
                     "result_sha256": sha256(result_path) if result_path.is_file() else None,
                     "failure_reason": issue if issue is not None else
                     (f"lift_exit_{metrics['exit_code']}" if metrics["exit_code"] != 0 else None),
                     "disk_before": free, **metrics}
            state["requests"][request_key] = event
            append_jsonl(attempts_path, event)
            atomic_json(state_path, state)
            if issue is not None:
                state["status"] = "result_invalid"
                state["stop_reason"] = f"invalid lift result ({issue}) at {queue_order}"
                atomic_json(state_path, state)
                raise RunnerError(state["stop_reason"])
            if metrics["exit_code"] != 0:
                state["status"] = "engine_failed"
                state["stop_reason"] = f"lift exit {metrics['exit_code']} at {queue_order}"
                atomic_json(state_path, state)
                raise RunnerError(state["stop_reason"])
            result_paths.append(result_path)
        instance_path = revision_dir / "instances.json"
        if result_paths:
            if instance_path.exists():
                instance_json = json.loads(instance_path.read_text())
                require(instance_json.get("schema") == "zkfdo-instance-verdicts-v1",
                        f"invalid existing instance verdicts: {instance_path}")
                expected_results = [str(path.relative_to(output)) for path in result_paths]
                require(instance_json.get("results") == expected_results,
                        f"existing instance inputs mismatch: {instance_path}")
                require(instance_json.get("conflicts") == 0,
                        f"instance verdict conflict: {instance_path}")
                if revision_state.get("instances_sha256") is not None:
                    require(revision_state["instances_sha256"] == sha256(instance_path),
                            f"instance SHA mismatch: {instance_path}")
            else:
                join_attempts = [int(match.group(1)) for item in revision_dir.glob("instances-attempt-*.json")
                                 if (match := re.fullmatch(r"instances-attempt-(\d{4})\.json", item.name))]
                join_attempt = max(join_attempts, default=0) + 1
                working_path = revision_dir / f"instances-attempt-{join_attempt:04d}.json"
                metrics = join_instances(result_paths, output, working_path,
                                         probe["measurement_method"])
                atomic_json(revision_dir / f"instances-attempt-{join_attempt:04d}.metrics.json",
                            metrics)
                append_jsonl(attempts_path, {"kind": "lift-instances", "scope": scope,
                                             "revision_id": revision_id,
                                             "revision_ordinal": ordinal,
                                             "output": str(working_path), **metrics})
                if metrics["exit_code"] != 0 or not working_path.is_file():
                    state["status"] = "join_failed"
                    state["stop_reason"] = f"lift-instances failed: {revision_key}"
                    revision_state["status"] = "join_failed"
                    atomic_json(state_path, state)
                    raise RunnerError(state["stop_reason"])
                instance_json = json.loads(working_path.read_text())
                expected_results = [str(path.relative_to(output)) for path in result_paths]
                require(instance_json.get("schema") == "zkfdo-instance-verdicts-v1" and
                        instance_json.get("results") == expected_results and
                        instance_json.get("conflicts") == 0,
                        f"lift-instances output mismatch: {working_path}")
                os.replace(working_path, instance_path)
            revision_state.update({"status": "joined", "instances_path": str(instance_path),
                                   "instances_sha256": sha256(instance_path),
                                   "result_count": len(result_paths)})
        else:
            revision_state.update({"status": "no_results", "instances_path": None,
                                   "instances_sha256": None, "result_count": 0})
        atomic_json(state_path, state)
        if cleanup_cache_per_revision and revision_state.get("cleanup", {}).get("status") != "deleted":
            cache_path = cache_root / scope / f"{ordinal:04d}"
            if cache_path.exists():
                revision_state["cleanup"] = cleanup_revision(cache_root, output, scope, ordinal,
                    revision_id, index_sha256, delete=True)
                atomic_json(state_path, state)
    state["status"] = "completed"
    state.pop("stop_reason", None)
    state.pop("next_queue_order", None)
    state["completed_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(state_path, state)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--action", choices=("validate-only", "execute"), default="validate-only")
    parser.add_argument("--cleanup-cache-per-revision", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "validate-only":
            index = validate_index(args.index.resolve(), args.index_sha256)
            require(args.cache_root.is_absolute() and args.cache_root.is_dir(),
                    "--cache-root must be an existing absolute directory")
            print(json.dumps({"status": "valid", "request_count": index["request_count"],
                              "index_sha256": args.index_sha256}, sort_keys=True))
        else:
            state = execute(args.index.resolve(), args.index_sha256, args.cache_root,
                            args.output, cleanup_cache_per_revision=args.cleanup_cache_per_revision)
            print(json.dumps({"status": state["status"],
                              "request_count": len(state["requests"]),
                              "output": str(args.output.resolve())}, sort_keys=True))
        return 0
    except DiskGuardStop as error:
        print(f"J disk guard stopped: {error}", file=sys.stderr)
        return 3
    except (OSError, ValueError, RunnerError, json.JSONDecodeError) as error:
        print(f"J runner failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
