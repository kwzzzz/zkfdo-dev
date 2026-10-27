#!/usr/bin/env python3
"""Execute the prepared 13-revision A exploratory remeasurement (never fuzz).

validate-only is read-only and launches no engine. execute is opt-in, revision
major, v2.2 then v1. All large J workspaces/stores/caches stay on the mounted SSD.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
from typing import Any

import n6_a_remeasure as banyan
import n6_a_remeasure_aq as prepared
import n6_j1_cache_cleanup as cache_cleanup
import run_n6_j1 as runner

ROOT = prepared.ROOT
OUTPUT = prepared.OUTPUT / "aq-exec"
MOUNT = Path("/Volumes/zkfdo-jcache")
EXTERNAL = MOUNT / "n6-a-remeasure-aq/j"
PLAN_SHA256 = "72358f45c78b459928c6f9ed6adbf1eeef51fd4a29cf4036fb5a8b5c194afd70"
INDEX_SHA256 = {
    "v2.2": "1d0ea66aa677ad319dea34034af771fddc6fe19a57dddf2360f0ddb5aabc6f72",
    "v1": "4f60f8dbd5fa4af0054f002d2bb2bcdc6a8d19ffdd094de17d81355d7fd58cec",
}
ENGINES = ("v2.2", "v1")
DEFAULT_REVISIONS = (
    "aq-025-70328d3fd35e", "aq-026-2bcd7ed6110f", "aq-011-93343c3cd34c",
    "aq-012-44d0df2ab46e", "aq-016-0a7d49b1c135", "aq-017-9703bbce0c43",
    "aq-024-6f6781246415", "aq-037-94fe3080fc18", "aq-039-0ad3923f2f5b",
    "aq-040-da54d3e7bc8a", "aq-006-1680f955c185", "aq-007-0bb83f9eab0f",
    "aq-008-9c9e702d061d",
)
DEFAULT_DEADLINE = "2026-10-28T15:00:00Z"
MIN_FREE_BYTES = 15 * 1024**3
TERMINAL = {"completed", "preparation_failure"}
LAYER = "A 탐색층"
STOP_SIGNAL: int | None = None
read = banyan.read
require = runner.require


class Stop(runner.RunnerError):
    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind = kind


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def deadline_value(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "deadline must include a timezone")
    return parsed.astimezone(timezone.utc)


def owned(path: Path, boundary: Path = OUTPUT) -> Path:
    require(path.is_absolute() and path.is_relative_to(boundary) and
            path.resolve() == path and boundary.resolve() == boundary and
            not path.is_symlink(), f"unsafe output path: {path}")
    return path


def external(path: Path) -> Path:
    return owned(path, EXTERNAL)


def write_fixed(path: Path, value: dict[str, Any]) -> None:
    owned(path)
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists():
        require(path.read_text() == content, f"immutable record differs: {path}")
    else:
        runner.atomic_json(path, value)


def mount_check() -> dict[str, Any]:
    # Never create a directory under an absent mount (which would use the repo disk).
    if (not MOUNT.is_mount() or MOUNT.resolve() != MOUNT or
            not EXTERNAL.is_dir() or EXTERNAL.resolve() != EXTERNAL or
            EXTERNAL.stat().st_dev != MOUNT.stat().st_dev or
            MOUNT.stat().st_dev == ROOT.stat().st_dev):
        raise Stop("mount", f"required external mount/directory unavailable: {EXTERNAL}")
    if not os.access(EXTERNAL, os.W_OK | os.X_OK):
        raise Stop("mount", f"external J directory is not writable: {EXTERNAL}")
    return {"mount": str(MOUNT), "j_root": str(EXTERNAL), "mounted": True,
            "repo_free_bytes": runner.disk_free(ROOT),
            "external_free_bytes": runner.disk_free(EXTERNAL)}


def request_guard() -> dict[str, Any]:
    if STOP_SIGNAL is not None:
        raise Stop("interrupted", f"signal {STOP_SIGNAL}; stopped between requests")
    space = mount_check()
    if space["repo_free_bytes"] < MIN_FREE_BYTES:
        raise Stop("space", f"repo filesystem has less than 15 GiB free: {space['repo_free_bytes']}")
    return space


def validate(revisions: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    require(bool(revisions) and len(revisions) == len(set(revisions)) and
            set(revisions) <= set(DEFAULT_REVISIONS), "provide unique approved aq revisions")
    owned(OUTPUT)
    mount = mount_check()
    plan = prepared.read(prepared.PREPARED / "plan.json", PLAN_SHA256)
    canonical = tuple(prepared.EXPECTED_COUNTS)
    require(plan.get("schema") == prepared.SCHEMA and
            plan.get("selected_revisions") == list(canonical) and
            plan.get("engine_order") == list(ENGINES) and plan.get("total_requests") == 660,
            "prepared aq plan differs")
    for engine in ENGINES:
        require(plan["indexes"][engine] == {
            "path": str(prepared.PREPARED / f"request-index-{engine}.json"),
            "sha256": INDEX_SHA256[engine], "request_count": 330}, "aq index pin differs")
    base = prepared.read(Path(plan["base_index"]), plan["base_index_sha256"])
    prepared.validate_overlays(canonical, plan["inputs"], plan["indexes"],
                               base, plan["request_counts"])
    indexes = {}
    source_errors = []
    for engine in ENGINES:
        index = prepared.read(Path(plan["indexes"][engine]["path"]), INDEX_SHA256[engine])
        documents = []
        for row in index["requests"]:
            request = prepared.read(Path(row["request"]), row["request_sha256"])
            if row["revision_id"] in revisions:
                runner.checked_request_sources(row, request, row["queue_order"])
            documents.append(request)
        runner.checked_sha(Path(index["inventory"]), index["inventory_sha256"], "A inventory")
        inventory = read(Path(index["inventory"]))
        print(f"Checking source bindings: {engine}", file=sys.stderr, flush=True)
        rows = [row for row in index["requests"] if row["revision_id"] in revisions]
        hashes = {row["candidate_sha256"] for row in rows}
        subset = {**inventory, "rows": [row for row in inventory["rows"]
                                       if row["candidate_sha256"] in hashes]}
        requests = [doc for row, doc in zip(index["requests"], documents, strict=True)
                    if row["revision_id"] in revisions]
        try:
            # The shared verifier hashes each used tree once, and fails closed
            # at the first bad binding. A failure never authorizes execution.
            runner.validate_source_bindings(rows, subset, requests)
        except (OSError, ValueError, runner.RunnerError) as error:
            source_errors.append({"engine": engine, "reason": str(error)})
        indexes[engine] = index
    return indexes, {"status": "invalid" if source_errors else "valid",
        "source_errors": source_errors, "layer": LAYER, "judging_executed": False,
        "script_sha256": runner.sha256(Path(__file__)),
        "plan_sha256": PLAN_SHA256, "index_sha256": INDEX_SHA256,
        "engine_sha256": {e: prepared.ENGINES[e]["sha256"] for e in ENGINES},
        "engine_order_per_revision": list(ENGINES), "revision_order": revisions,
        "request_counts": [{"revision": revision, "per_engine": {
            engine: {"requests": len(rows_for(indexes[engine], revision)),
                     "scopes": dict(Counter(r["scope"] for r in rows_for(indexes[engine], revision))),
                     "methods": {m: sum(r["method"] == m for r in rows_for(indexes[engine], revision))
                                 for m in ("W", "S")}} for engine in ENGINES}}
            for revision in revisions],
        "total_requests": sum(len(rows_for(indexes[e], r)) for r in revisions for e in ENGINES),
        "min_repo_free_bytes": MIN_FREE_BYTES, "mount": mount}


def rows_for(index: dict[str, Any], revision: str) -> list[dict[str, Any]]:
    # Filter, never sort: retain the original main + mem20 queue order.
    return [row for row in index["requests"] if row["revision_id"] == revision]


def groups_for(index: dict[str, Any], revision: str) -> list[tuple]:
    return [group for group in runner.groups(index["requests"]) if group[2] == revision]


def configure(engine: str) -> None:
    runner.ENGINE = prepared.ENGINES[engine]["path"]
    runner.ENGINE_SHA256 = prepared.ENGINES[engine]["sha256"]
    runner.checked_sha(runner.ENGINE, runner.ENGINE_SHA256, "frozen J engine")


def config(revisions: list[str], deadline: datetime) -> dict[str, Any]:
    scripts = (Path(__file__), Path(prepared.__file__), Path(banyan.__file__),
               Path(runner.__file__), ROOT / "scripts/n6_j1_cache_cleanup.py",
               ROOT / "scripts/run_policy_a_engine.py")
    return {"plan_sha256": PLAN_SHA256, "index_sha256": INDEX_SHA256,
            "revision_order": revisions, "engine_order": list(ENGINES),
            "no_new_revision_after": deadline.isoformat(), "min_repo_free_bytes": MIN_FREE_BYTES,
            "external_root": str(EXTERNAL), "output_root": str(OUTPUT),
            "engine_sha256": {e: prepared.ENGINES[e]["sha256"] for e in ENGINES},
            "script_sha256": {str(p.resolve()): runner.sha256(p) for p in scripts}}


def save(state: dict[str, Any]) -> None:
    runner.atomic_json(owned(OUTPUT / "state.json"), state)


def load_state(binding: dict[str, Any]) -> dict[str, Any]:
    path = owned(OUTPUT / "state.json")
    if path.exists():
        state = read(path)
        require(state.get("schema") == "n6-a-remeasure-aq-execute-v1" and
                state.get("config") == binding, "resume configuration/hash differs; use the same command")
        return state
    return {"schema": "n6-a-remeasure-aq-execute-v1", "layer": LAYER,
            "config": binding, "started_at": now(), "status": "ready",
            "active_revision": None, "revisions": {},
            "engines": {e: {"requests": {}, "groups": {}} for e in ENGINES}}


def local_request(engine: str, row: dict[str, Any]) -> Path:
    return owned(OUTPUT / engine / "requests" / f"{row['queue_order']:06d}")


def attempt_paths(engine: str, row: dict[str, Any], attempt: int) -> tuple[Path, Path, Path]:
    directory = local_request(engine, row)
    name = f"attempt-{attempt:04d}"
    return (owned(directory / f"{name}.result.json"),
            owned(directory / f"{name}.metrics.json"),
            external(EXTERNAL / engine / "workspaces" / row["revision_id"] /
                     f"{row['queue_order']:06d}" / name))


def checked_event(engine: str, row: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    require(event.get("request_sha256") == row["request_sha256"] and
            event.get("queue_order") == row["queue_order"], "resume request binding differs")
    result_path, metrics_path, _ = attempt_paths(engine, row, event["attempt"])
    require(event.get("metrics_path") == str(metrics_path), "resume metrics path differs")
    runner.checked_sha(metrics_path, event["metrics_sha256"], "saved metrics")
    metrics = read(metrics_path)
    require(all(event.get(k) == metrics.get(k) for k in metrics), "saved metrics values differ")
    seconds = metrics.get("wall_seconds")
    require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0,
            "invalid request wall_seconds")
    result = None
    if event.get("result_path") is not None:
        require(event["result_path"] == str(result_path), "resume result path differs")
        runner.checked_sha(result_path, event["result_sha256"], "saved result")
        result = read(result_path)
    if event["status"] in TERMINAL:
        require(result is not None and result.get("schema") == "zkfdo-lifting-result-v1" and
                result.get("request_id") == read(Path(row["request"]))["id"] and
                metrics.get("exit_code") == 0, "invalid terminal result identity/exit")
        issue = runner.successful_result_issue(row, metrics, result)
        require(issue == (None if event["status"] == "completed" else "preparation_not_ok"),
                "terminal request classification differs")
        if event["status"] == "preparation_failure":
            require(result.get("preparation", {}).get("status") not in (None, "ok"),
                    "invalid preparation failure")
    return result


def finish_event(engine: str, row: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    result_path, metrics_path, workspace = attempt_paths(engine, row, event["attempt"])
    metrics = read(metrics_path)
    raw_result = external(workspace / "result.json")
    if raw_result.is_file():
        data = raw_result.read_bytes()
        if result_path.exists():
            require(result_path.read_bytes() == data, "saved/raw result bytes differ")
        else:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic copy of the original JSON bytes, including artifact paths.
            temporary = owned(result_path.with_suffix(".tmp"))
            with temporary.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, result_path)
    try:
        result = read(result_path) if result_path.is_file() else None
    except (ValueError, runner.RunnerError):
        result = None
    issue = (runner.successful_result_issue(row, metrics, result)
             if metrics.get("exit_code") == 0 else f"lift_exit_{metrics.get('exit_code')}")
    if isinstance(result, dict) and (result.get("schema") != "zkfdo-lifting-result-v1" or
            result.get("request_id") != read(Path(row["request"]))["id"]):
        issue = "result_identity_mismatch"
    preparation_failed = issue == "preparation_not_ok" and isinstance(result, dict) and \
        result.get("preparation", {}).get("status") not in (None, "ok")
    status = "completed" if issue is None else "preparation_failure" if preparation_failed else "failed"
    final = {**event, **metrics, "status": status, "finished_at": now(),
             "failure_reason": issue, "metrics_path": str(metrics_path),
             "metrics_sha256": runner.sha256(metrics_path),
             "result_path": str(result_path) if result is not None else None,
             "result_sha256": runner.sha256(result_path) if result is not None else None}
    checked_event(engine, row, final)
    return final


def recover(state: dict[str, Any], indexes: dict[str, Any]) -> None:
    # Validate every stored request before either skipping it or making a new call.
    for engine in ENGINES:
        known = {str(r["queue_order"]): r for r in indexes[engine]["requests"]
                 if r["revision_id"] in state["config"]["revision_order"]}
        for key, event in list(state["engines"][engine]["requests"].items()):
            require(key in known, "state contains an unselected request")
            row = known[key]
            require(event.get("request_sha256") == row["request_sha256"], "saved request SHA differs")
            if event["status"] == "running":
                _, metrics, _ = attempt_paths(engine, row, event["attempt"])
                if metrics.is_file():
                    event = finish_event(engine, row, event)
                    event["resumed_result"] = True
                    state["engines"][engine]["requests"][key] = event
                    save(state)
            else:
                require(event["status"] in TERMINAL | {"failed"}, "unknown request status")
                checked_event(engine, row, event)


def group_state(state: dict[str, Any], engine: str, scope: str, ordinal: int,
                revision: str) -> dict[str, Any]:
    return state["engines"][engine]["groups"].setdefault(f"{scope}/{ordinal:04d}", {
        "scope": scope, "ordinal": ordinal, "revision": revision})


def effective_for(state: dict[str, Any], engine: str, index: dict[str, Any],
                  revision: str, *, allow_join: bool) -> dict[tuple[str, str], str]:
    effective = {}
    for scope, ordinal, _, rows in groups_for(index, revision):
        paths = []
        for row in rows:
            event = state["engines"][engine]["requests"].get(str(row["queue_order"]), {})
            if event.get("status") == "completed":
                checked_event(engine, row, event)
                paths.append(Path(event["result_path"]))
        if not paths:
            continue
        fingerprint = hashlib.sha256(json.dumps([(str(p), runner.sha256(p)) for p in paths]).encode()).hexdigest()
        group = group_state(state, engine, scope, ordinal, revision)
        receipt = group.get("join")
        if not receipt or receipt.get("inputs_fingerprint") != fingerprint:
            require(allow_join, "saved instance join missing or stale")
            configure(engine)
            folder = owned(OUTPUT / "aggregates" / "joins" / engine / scope / f"{ordinal:04d}")
            folder.mkdir(parents=True, exist_ok=True)
            # Each invocation uses a new name, retaining crash fragments and logs.
            attempt = group.get("join_attempt", 0) + 1
            while any(folder.glob(f"join-{attempt:04d}.*")):
                attempt += 1
            group["join_attempt"] = attempt
            save(state)
            join_path = owned(folder / f"join-{attempt:04d}.json")
            metrics = runner.join_instances(paths, OUTPUT, join_path,
                                           runner.probe_time_l()["measurement_method"])
            metrics_path = join_path.with_suffix(".metrics.json")
            write_fixed(metrics_path, metrics)
            require(metrics["exit_code"] == 0 and join_path.is_file(), "lift-instances failed")
            receipt = {"path": str(join_path), "sha256": runner.sha256(join_path),
                       "metrics_path": str(metrics_path), "metrics_sha256": runner.sha256(metrics_path),
                       "engine_sha256": prepared.ENGINES[engine]["sha256"],
                       "inputs_fingerprint": fingerprint, "result_count": len(paths)}
            group["join"] = receipt
            save(state)
        require(receipt["engine_sha256"] == prepared.ENGINES[engine]["sha256"], "join engine differs")
        join_path = owned(Path(receipt["path"]))
        runner.checked_sha(join_path, receipt["sha256"], "saved instance join")
        runner.checked_sha(owned(Path(receipt["metrics_path"])), receipt["metrics_sha256"], "join metrics")
        joined = read(join_path)
        require(joined.get("schema") == "zkfdo-instance-verdicts-v1" and joined.get("conflicts") == 0 and
                joined.get("results") == [str(p.relative_to(OUTPUT)) for p in paths], "instance join binding/conflict")
        for item in joined["classes"]:
            key = (item["request_id"], item["representative"])
            require(key not in effective, "duplicate joined class")
            effective[key] = item["effective"]
    return effective


def summary(state: dict[str, Any], engine: str, rows: list[dict[str, Any]],
            effective: dict[tuple[str, str], str]) -> dict[str, Any]:
    counts: Counter = Counter()
    times = []
    for row in rows:
        event = state["engines"][engine]["requests"].get(str(row["queue_order"]), {})
        status = event.get("status", "not_run")
        counts[status] += 1
        if status != "running" and event:
            result = checked_event(engine, row, event)
            times.append(event["wall_seconds"])
            if status == "completed":
                l1, excluded = banyan.judgement_flags(result, effective)
                counts["L1" if l1 else "excluded" if excluded else "unknown"] += 1
    return {"requests": len(rows), **{k: counts[k] for k in
            ("completed", "preparation_failure", "L1", "excluded", "unknown", "running", "not_run")},
            "errors": counts["failed"], "wall_seconds": {
                "count": len(times), "sum": sum(times),
                "mean": sum(times) / len(times) if times else None,
                "max": max(times) if times else None}}


def flush_progress(state: dict[str, Any]) -> None:
    pending = state.get("pending_progress")
    if pending is None:
        return
    path = owned(OUTPUT / "progress.jsonl")
    payload = pending["line"].encode()
    offset = pending["offset"]
    with path.open("a+b") as stream:
        stream.seek(offset)
        existing = stream.read()
        require(payload.startswith(existing), "progress outbox differs from log")
        stream.write(payload[len(existing):])  # Finish a torn append without duplicating it.
        stream.flush()
        os.fsync(stream.fileno())
    print(pending["line"], end="", flush=True)
    del state["pending_progress"]
    save(state)


def progress(state: dict[str, Any], indexes: dict[str, Any], revision: str,
             stop: dict[str, str] | None = None) -> None:
    flush_progress(state)
    record = {"revision": revision, "finished_at": now(), "layer": LAYER, "engines": {}}
    for engine in ENGINES:
        try:
            effective = effective_for(state, engine, indexes[engine], revision, allow_join=True)
            record["engines"][engine] = summary(state, engine, rows_for(indexes[engine], revision), effective)
        except (OSError, ValueError, KeyError, TypeError, runner.RunnerError) as error:
            if not stop:
                raise
            # Never turn an unavailable join or corrupt result into an unknown verdict.
            rows = rows_for(indexes[engine], revision)
            counts = Counter(state["engines"][engine]["requests"].get(str(r["queue_order"]), {})
                             .get("status", "not_run") for r in rows)
            record["engines"][engine] = {"requests": len(rows),
                **{k: counts[k] for k in ("completed", "preparation_failure", "running", "not_run")},
                "errors": counts["failed"], "L1": None, "excluded": None, "unknown": None,
                "wall_seconds": {"sum": None, "mean": None, "max": None},
                "classification_error": str(error)}
    if stop:
        record["stop"] = stop
    else:
        state["revisions"][revision].update({"status": "completed", "finished_at": record["finished_at"]})
        state["active_revision"] = None
    path = owned(OUTPUT / "progress.jsonl")
    state["pending_progress"] = {"offset": path.stat().st_size if path.exists() else 0,
        "line": json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"}
    save(state)
    flush_progress(state)


def cleanup(state: dict[str, Any], engine: str, index: dict[str, Any], revision: str) -> None:
    mount_check()
    cache_root = external(EXTERNAL / engine / "caches")
    for scope, ordinal, _, _ in groups_for(index, revision):
        group = group_state(state, engine, scope, ordinal, revision)
        if group.get("cleanup"):
            receipt = group["cleanup"]
            runner.checked_sha(owned(Path(receipt["manifest"])), receipt["manifest_sha256"], "cache cleanup")
            continue
        path = external(cache_root / scope / f"{ordinal:04d}")
        pending = group.get("cleanup_pending")
        if pending and owned(Path(pending)).is_file():
            # The shared helper writes the inventory before deleting any file.
            # Recover a crash during deletion, even if its owner marker is gone.
            manifest = owned(Path(pending))
            record = read(manifest)
            require(record.get("kind") == "n6_j1_cache_cleanup" and
                    record.get("cache_path") == str(path) and record.get("scope") == scope and
                    record.get("revision_ordinal") == ordinal and record.get("revision_id") == revision and
                    record.get("request_index_sha256") == INDEX_SHA256[engine], "cleanup inventory binding differs")
            expected = {item["path"]: item for item in record["files"]}
            if path.exists():
                remaining, directories = cache_cleanup.inventory(path)
                require(all(item == expected.get(item["path"]) for item in remaining),
                        "cache changed after cleanup inventory was recorded")
                for item in remaining:
                    external(path / item["path"]).unlink()
                for directory in directories:
                    external(directory).rmdir()
            group["cleanup"] = {"status": "deleted", "recovered": True,
                "cache_path": str(path), "manifest": str(manifest),
                "manifest_sha256": runner.sha256(manifest),
                "file_count": record["file_count"], "bytes": record["bytes"]}
            group.pop("cleanup_pending", None)
            save(state)
            continue
        if path.exists():
            folder = owned(OUTPUT / "cache-cleanup" / engine)
            folder.mkdir(parents=True, exist_ok=True)
            serial = 1
            manifest = folder / f"{scope}-{ordinal:04d}-{serial:04d}.json"
            while manifest.exists():
                serial += 1
                manifest = folder / f"{scope}-{ordinal:04d}-{serial:04d}.json"
            group["cleanup_pending"] = str(manifest)
            save(state)
            group["cleanup"] = runner.cleanup_revision(cache_root, OUTPUT, scope, ordinal,
                revision, INDEX_SHA256[engine], delete=True, manifest_path=manifest)
            group.pop("cleanup_pending", None)
            save(state)


def execute(state: dict[str, Any], indexes: dict[str, Any], deadline: datetime) -> dict[str, Any]:
    revision = state.get("active_revision")
    try:
        flush_progress(state)
        recover(state, indexes)
        state.update({"status": "running", "stop_kind": None, "stop_reason": None})
        save(state)
        for revision in state["config"]["revision_order"]:
            if state["revisions"].get(revision, {}).get("status") == "completed":
                # Re-verify joins and cleanup receipts too; completed requests were checked above.
                for engine in ENGINES:
                    effective_for(state, engine, indexes[engine], revision, allow_join=False)
                    for scope, ordinal, _, _ in groups_for(indexes[engine], revision):
                        receipt = group_state(state, engine, scope, ordinal, revision).get("cleanup")
                        if receipt:
                            runner.checked_sha(owned(Path(receipt["manifest"])),
                                               receipt["manifest_sha256"], "saved cache cleanup")
                continue
            for engine in ENGINES:
                configure(engine)
                index = indexes[engine]
                cache_root = external(EXTERNAL / engine / "caches")
                group_map = {row["queue_order"]: (scope, ordinal) for scope, ordinal, _, rows
                             in groups_for(index, revision) for row in rows}
                for row in rows_for(index, revision):
                    key = str(row["queue_order"])
                    old = state["engines"][engine]["requests"].get(key)
                    if old and old["status"] in TERMINAL:
                        checked_event(engine, row, old)
                        continue
                    runner.checked_sha(Path(row["request"]), row["request_sha256"], "request")
                    request = read(Path(row["request"]))
                    runner.checked_request_sources(row, request, row["queue_order"])
                    binding = prepared.read(prepared.PREPARED / "plan.json", PLAN_SHA256)["inputs"][revision]
                    runner.checked_sha(Path(binding["path"]), binding["sha256"], "constructed input")
                    free = request_guard()
                    if state.get("active_revision") is None:
                        if datetime.now(timezone.utc) >= deadline:
                            raise Stop("deadline", "no new revision at/after the UTC deadline")
                        state["active_revision"] = revision
                        state["revisions"][revision] = {"status": "running", "started_at": now()}
                        save(state)
                    require(state["active_revision"] == revision, "unfinished revision order differs")
                    scope, ordinal = group_map[row["queue_order"]]
                    cache_root.mkdir(parents=True, exist_ok=True)
                    cache = runner.initialize_cache(cache_root, scope, ordinal, revision, INDEX_SHA256[engine])
                    store = external(EXTERNAL / engine / "stores" / scope / f"{ordinal:04d}")
                    store.parent.mkdir(parents=True, exist_ok=True)
                    attempt = old["attempt"] + 1 if old else 1
                    result_path, metrics_path, workspace = attempt_paths(engine, row, attempt)
                    while workspace.exists() or metrics_path.exists() or result_path.exists() or any(
                            workspace.parent.glob(f"{workspace.name}.*")):
                        attempt += 1
                        result_path, metrics_path, workspace = attempt_paths(engine, row, attempt)
                    probe = runner.probe_time_l()
                    event = {"status": "running", "engine": engine, "queue_order": row["queue_order"],
                        "revision": revision, "scope": scope, "method": row["method"],
                        "request_sha256": row["request_sha256"], "attempt": attempt,
                        "started_at": now(), "workspace": str(workspace), "store": str(store),
                        "disk_before": free, "time_probe": probe}
                    state["engines"][engine]["requests"][key] = event
                    save(state)
                    metrics = runner.run_lift(row, workspace, cache, store, attempt, probe["measurement_method"])
                    write_fixed(metrics_path, metrics)
                    final = finish_event(engine, row, event)
                    state["engines"][engine]["requests"][key] = final
                    save(state)
                    runner.append_jsonl(owned(OUTPUT / "attempts.jsonl"), final)
                    if final["status"] == "failed":
                        raise Stop("interrupted" if STOP_SIGNAL is not None else "error",
                                   f"{engine} request {key}: {final['failure_reason']}")
            # Both engines and both scopes finish before joins, cache cleanup and progress.
            for engine in ENGINES:
                effective_for(state, engine, indexes[engine], revision, allow_join=True)
                cleanup(state, engine, indexes[engine], revision)
            progress(state, indexes, revision)
        state.update({"status": "completed", "finished_at": now()})
        save(state)
        return {"status": "completed", "state": str(OUTPUT / "state.json"), "layer": LAYER}
    except (OSError, ValueError, KeyError, TypeError, runner.RunnerError, KeyboardInterrupt) as error:
        kind = error.kind if isinstance(error, Stop) else "interrupted" if isinstance(error, KeyboardInterrupt) else "error"
        state.update({"status": "stopped", "stop_kind": kind, "stop_reason": str(error), "stopped_at": now()})
        save(state)
        if revision:
            try:
                progress(state, indexes, revision, {"stop_kind": kind, "reason": str(error)})
            except (OSError, ValueError, KeyError, TypeError, runner.RunnerError) as progress_error:
                state["progress_error"] = str(progress_error)
                save(state)
        return {"status": "stopped", "stop_kind": kind, "reason": str(error),
                "state": str(OUTPUT / "state.json"), "progress_error": state.get("progress_error")}


def aggregate(state: dict[str, Any], indexes: dict[str, Any]) -> dict[str, Any]:
    recover(state, indexes)
    rows = []
    for revision in state["config"]["revision_order"]:
        for engine in ENGINES:
            effective = effective_for(state, engine, indexes[engine], revision, allow_join=True)
            for method in ("W", "S"):
                selected = [r for r in rows_for(indexes[engine], revision) if r["method"] == method]
                rows.append({"revision": revision, "engine": engine, "method": method,
                             **summary(state, engine, selected, effective)})
    result = {"schema": "n6-a-remeasure-aq-aggregate-v1", "layer": LAYER, "generated_at": now(),
              "config": state["config"], "rows": rows, "execution_status": state["status"],
              "stop_kind": state.get("stop_kind"),
              "revisions_completed": sum(r.get("status") == "completed" for r in state["revisions"].values()),
              "revisions_selected": len(state["config"]["revision_order"]),
              "classification": "Banyan/B6h request flags; only completed requests classify. "
                                "L1 precedes any own/effective exclusion, otherwise unknown.",
              "timing_scope": "Final saved request attempts only; joins, validation, cleanup and earlier retries excluded.",
              "note": "A 개발 세트 탐색층; 배제는 구성 입력 기준. 요청 수는 회로 크기와 후보 수에 좌우됨.",
              "joins": {e: state["engines"][e]["groups"] for e in ENGINES}}
    folder = owned(OUTPUT / "aggregates")
    folder.mkdir(parents=True, exist_ok=True)
    serial = 1
    while (folder / f"aggregate-{serial:04d}.json").exists():
        serial += 1
    path = folder / f"aggregate-{serial:04d}.json"
    write_fixed(path, result)
    return {"status": "aggregated", "path": str(path), "sha256": runner.sha256(path), "rows": rows}


def handle_signal(signum: int, _frame: Any) -> None:
    global STOP_SIGNAL
    STOP_SIGNAL = signum


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=("validate-only", "execute", "aggregate"))
    parser.add_argument("--revisions", nargs="+", choices=DEFAULT_REVISIONS, default=list(DEFAULT_REVISIONS))
    parser.add_argument("--no-new-revision-after", default=DEFAULT_DEADLINE)
    args = parser.parse_args()
    try:
        deadline = deadline_value(args.no_new_revision_after)
        indexes, report = validate(args.revisions)
        report["no_new_revision_after"] = deadline.isoformat()
        if args.action == "validate-only":
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 2 if report["status"] == "invalid" else 0
        require(report["status"] == "valid",
                f"source validation failed; run validate-only for details: {report['source_errors']}")
        OUTPUT.mkdir(parents=True, exist_ok=True)
        with owned(OUTPUT / ".runner.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state = load_state(config(args.revisions, deadline))
            if args.action == "execute":
                signal.signal(signal.SIGINT, handle_signal)
                signal.signal(signal.SIGTERM, handle_signal)
                result = execute(state, indexes, deadline)
            else:
                require((OUTPUT / "state.json").is_file(), "no execution state to aggregate")
                result = aggregate(state, indexes)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 3 if result["status"] == "stopped" else 0
    except (OSError, ValueError, KeyError, TypeError, runner.RunnerError) as error:
        print(json.dumps({"status": "stopped", "stop_kind": getattr(error, "kind", "error"),
                          "reason": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
