#!/usr/bin/env python3
"""Versioned A aq runner: read-only validation; explicit execute resumes v1.

Never fuzz. Preserve the v1 state/results; write state-v2.json and new attempts.
Engine-major, mapped sites first, bounded retries, audited A-only cleanup.
"""

from __future__ import annotations

import argparse
import copy
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
import re
from pathlib import Path
import signal
import sys
import subprocess
import time
from typing import Any

import n6_a_remeasure as banyan
import n6_a_remeasure_aq as prepared
import n6_a_remeasure_aq_cleanup_v2 as workspace_cleanup
import n6_a_remeasure_aq_order_v2 as ordering
import n6_light_rqc_20261026 as rqc
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
ENGINE_SHA256 = {
    "v2.2": "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835",
    "v1": "e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed",
}
DEFAULT_REVISIONS = (
    "aq-024-6f6781246415", "aq-017-9703bbce0c43", "aq-011-93343c3cd34c",
    "aq-016-0a7d49b1c135", "aq-026-2bcd7ed6110f", "aq-040-da54d3e7bc8a",
    "aq-008-9c9e702d061d", "aq-025-70328d3fd35e", "aq-012-44d0df2ab46e",
    "aq-037-94fe3080fc18", "aq-039-0ad3923f2f5b", "aq-006-1680f955c185",
    "aq-007-0bb83f9eab0f",
)
DEFAULT_DEADLINE = "2026-10-28T15:00:00Z"
MIN_FREE_BYTES = 15 * 1024**3
TERMINAL = {"completed", "preparation_failure"}
LAYER = "A 탐색층"
STOP_SIGNAL: int | None = None
GIB = 1024**3
INITIAL_PEAK = 60 * GIB
SCHEMA = "n6-a-remeasure-aq-execute-v2"
MAPPING = ROOT / "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json"
ERRORS = (OSError, ValueError, KeyError, TypeError, runner.RunnerError)
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


def mount_check(*, require_write: bool = True) -> dict[str, Any]:
    # Never create a directory under an absent mount (which would use the repo disk).
    if (not MOUNT.is_mount() or MOUNT.resolve() != MOUNT or
            not EXTERNAL.is_dir() or EXTERNAL.resolve() != EXTERNAL or
            EXTERNAL.stat().st_dev != MOUNT.stat().st_dev or
            MOUNT.stat().st_dev == ROOT.stat().st_dev):
        raise Stop("mount", f"required external mount/directory unavailable: {EXTERNAL}")
    if require_write and not os.access(EXTERNAL, os.W_OK | os.X_OK):
        raise Stop("mount", f"external J directory is not writable: {EXTERNAL}")
    return {"mount": str(MOUNT), "j_root": str(EXTERNAL), "mounted": True,
            "repo_free_bytes": runner.disk_free(ROOT),
            "external_free_bytes": runner.disk_free(EXTERNAL)}


def rows_for(index: dict[str, Any], revision: str) -> list[dict[str, Any]]:
    # Filter, never sort: retain the original main + mem20 queue order.
    return [row for row in index["requests"] if row["revision_id"] == revision]

def groups_for(index: dict[str, Any], revision: str) -> list[tuple]:
    return [group for group in runner.groups(index["requests"]) if group[2] == revision]

def configure(engine: str) -> None:
    require(prepared.ENGINES[engine]["sha256"] == ENGINE_SHA256[engine], "engine pin differs")
    runner.ENGINE = prepared.ENGINES[engine]["path"]
    runner.ENGINE_SHA256 = prepared.ENGINES[engine]["sha256"]
    runner.checked_sha(runner.ENGINE, runner.ENGINE_SHA256, "frozen J engine")

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
        try:
            result = read(result_path)
        except (ValueError, runner.RunnerError):
            require(event["status"] == "failed", "invalid completed result JSON")
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
             "result_path": str(result_path) if result_path.is_file() else None,
             "result_sha256": runner.sha256(result_path) if result_path.is_file() else None}
    if preparation_failed:
        preparation = result["preparation"]
        final["failure_reason"] = "preparation:" + str(preparation.get("reason") or preparation["status"])
        final["failure_detail"] = preparation.get("detail")
    elif status == "failed" and metrics.get("failure_diagnostic"):
        final["failure_reason"] = str(issue) + ":" + reason_code(ValueError(metrics["failure_diagnostic"]))
        final["failure_detail"] = metrics["failure_diagnostic"]
    checked_event(engine, row, final)
    return final

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
            folder = owned(OUTPUT / "aggregates-v2" / "joins" / engine / scope / f"{ordinal:04d}")
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
    path = owned(OUTPUT / "progress-v2.jsonl")
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

def handle_signal(signum: int, _frame: Any) -> None:
    global STOP_SIGNAL
    STOP_SIGNAL = signum



def validate_sources(revisions: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    require(bool(revisions) and len(revisions) == len(set(revisions)) and
            set(revisions) <= set(DEFAULT_REVISIONS), "provide unique approved aq revisions")
    owned(OUTPUT)
    mount = mount_check(require_write=False)
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
        "engine_major_order": list(ENGINES), "revision_order": revisions,
        "request_counts": [{"revision": revision, "per_engine": {
            engine: {"requests": len(rows_for(indexes[engine], revision)),
                     "scopes": dict(Counter(r["scope"] for r in rows_for(indexes[engine], revision))),
                     "methods": {m: sum(r["method"] == m for r in rows_for(indexes[engine], revision))
                                 for m in ("W", "S")}} for engine in ENGINES}}
            for revision in revisions],
        "total_requests": sum(len(rows_for(indexes[e], r)) for r in revisions for e in ENGINES),
        "min_repo_free_bytes": MIN_FREE_BYTES, "mount": mount}

INPUT_SHA256 = {'aq-006-1680f955c185': '1306d1490fde47ab71a3ce72c9c37f57dc2b8022d6abae7ddcd3d629b8daf5d5',
 'aq-007-0bb83f9eab0f': 'cb6400035658e009aa68f563b51459e10ffa3d031ff2ceb95475bc9bd352e7b7',
 'aq-008-9c9e702d061d': '0feb3d19f9e13c977aef45a10fb65af57e68794393fab9512db9671532f8d1f8',
 'aq-011-93343c3cd34c': 'cc8ccc2e563c60ceafabd26bcedb7d18933cac0b732f9ca42a078ab6fdcccc22',
 'aq-025-70328d3fd35e': '64b682ae859f3870931cc4192319a1842ab9c1386595d1d5d110b352807cf1de',
 'aq-026-2bcd7ed6110f': 'c88e50147ebb3ee221c240aca3fe68d4795b1898874a7b4b45980a56e4fc9162',
 'aq-012-44d0df2ab46e': '5ad467c4e76decb3a0882eb10c197ddd1b6cf2ced00d8369a7e3e6908c9ad1ae',
 'aq-016-0a7d49b1c135': 'b91d881aa99c5ae966930c6afaea03bd5b9cd839937a581baff77150ef2a46b5',
 'aq-024-6f6781246415': 'cab37e5c0d8a102580b32d2f713a6b71555d3c2bf034a576842d806d0890ce27',
 'aq-017-9703bbce0c43': '7dab8471550d0fbdc911ce7a432e1ac855a1115c068dccee8aa82d6507114d0a',
 'aq-040-da54d3e7bc8a': '4ce29bfd9932417a45686cc326e82d2541df916d0b4576c02620d621dd7315c2',
 'aq-037-94fe3080fc18': 'a7c9785954e54664485359a15a93d2404a83071410c80ecdcd336def092824e6',
 'aq-039-0ad3923f2f5b': 'eec7f3d030bdbc145970f84b0e0e879d9a00386a2a0f61fd414c2b04a4e04b52'}


def save(state: dict[str, Any]) -> None:
    runner.atomic_json(owned(OUTPUT / "state-v2.json"), state)


def digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def verify_pins() -> dict[str, Any]:
    """Check all engines, indexes and documented inputs before source inspection."""
    doc = ROOT / "docs/n6_a_remeasure_aq_inputs_2026-10-25.md"
    pattern = r"^\| (aq-[^ |]+) \| " + chr(96) + r"([0-9a-f]{64})" + chr(96) + r" \|$"
    documented = dict(re.findall(pattern, doc.read_text(), re.M))
    require(documented == INPUT_SHA256, "documented constructed input pins differ")
    plan = prepared.read(prepared.PREPARED / "plan.json", PLAN_SHA256)
    for engine in ENGINES:
        configure(engine)
        runner.checked_sha(prepared.PREPARED / f"request-index-{engine}.json",
                           INDEX_SHA256[engine], "frozen aq index")
    require(set(plan["inputs"]) == set(INPUT_SHA256), "constructed input set differs")
    for revision, sha in INPUT_SHA256.items():
        expected = prepared.OUTPUT / "inputs" / revision / "input.json"
        entry = plan["inputs"][revision]
        require(entry["path"] == str(expected) and entry["sha256"] == sha,
                f"constructed input plan binding differs: {revision}")
        runner.checked_sha(expected, sha, "documented constructed input")
    runner.checked_sha(MAPPING, rqc.MAP_SHA, "fixed RQ-C map")
    return {"inputs_verified": len(INPUT_SHA256), "input_sha256": INPUT_SHA256,
            "input_document_sha256": runner.sha256(doc)}


def configuration(order: list[dict[str, Any]], deadline: datetime) -> dict[str, Any]:
    dependencies = [Path(__file__), Path(workspace_cleanup.__file__), Path(ordering.__file__),
                    Path(prepared.__file__), Path(banyan.__file__), Path(runner.__file__),
                    Path(rqc.__file__), ROOT / "scripts/n6_a_aq_workspace_cleanup.py",
                    ROOT / "scripts/n6_b6h_cleanup.py", ROOT / "scripts/run_policy_a_engine.py"]
    return {"plan_sha256": PLAN_SHA256, "index_sha256": INDEX_SHA256,
            "engine_sha256": {e: prepared.ENGINES[e]["sha256"] for e in ENGINES},
            "input_sha256": INPUT_SHA256, "mapping_sha256": rqc.MAP_SHA,
            "revision_order": list(DEFAULT_REVISIONS), "engine_order": list(ENGINES),
            "request_order_sha256": digest_json(order), "external_root": str(EXTERNAL),
            "no_new_revision_after": deadline.isoformat(),
            "script_sha256": {str(p): runner.sha256(p) for p in dependencies}}


def legacy_peak() -> int:
    # Read only the explicit cleanup record directory, never enumerate runs/.
    peak = INITIAL_PEAK
    folder = OUTPUT / "workspace-cleanup-20261026"
    if folder.is_dir():
        for path in folder.glob("*-before.json"):
            record = read(owned(path))
            target = Path(record["target"])
            external(target)
            require(target.is_relative_to(EXTERNAL / "v2.2" / "workspaces"),
                    "legacy cleanup target differs")
            peak = max(peak, record["deleted_du_bytes"] + record["retained_du_bytes"])
    return peak


def load_state(binding: dict[str, Any]) -> dict[str, Any]:
    source = owned(OUTPUT / "state.json")
    source_sha = runner.sha256(source)
    path = owned(OUTPUT / "state-v2.json")
    if path.exists():
        state = read(path)
        require(state.get("schema") == SCHEMA and state.get("config") == binding,
                "v2 resume configuration/hash differs; use unchanged scripts/command")
        require(state["imported_state"] == {"path": str(source), "sha256": source_sha},
                "original v1 state changed after v2 import")
        return state
    prior = read(source)
    require(prior.get("schema") == "n6-a-remeasure-aq-execute-v1",
            "unexpected import state schema")
    require(prior.get("status") != "running" and all(
        event["status"] != "running" for data in prior["engines"].values()
        for event in data["requests"].values()), "v1 must be durably stopped before import")
    for key in ("plan_sha256", "index_sha256", "engine_sha256", "external_root"):
        require(prior["config"][key] == binding[key], f"v1 import binding differs: {key}")
    state = {"schema": SCHEMA, "layer": LAYER, "config": binding, "started_at": now(),
             "status": "ready", "active_revision": None, "revisions": {},
             "engines": copy.deepcopy(prior["engines"]),
             "imported_state": {"path": str(source), "sha256": source_sha},
             "observed_request_peak_bytes": legacy_peak(),
             "cleanup_receipts": [], "request_failure_streak": {}, "revision_failure_streak": {}}
    for engine in ENGINES:
        for event in state["engines"][engine]["requests"].values():
            event["imported_v1"] = True
            event["streak_counted"] = True
            if event["status"] == "failed":
                event["resume_pending"] = True
                free = event.get("disk_before", {}).get("external_free_bytes")
                event["retry_pending"] = free is not None and free < GIB
                event["retry_reason"] = "legacy_disk_below_1_gib" if event["retry_pending"] else None
    return state


def recover(state: dict[str, Any], indexes: dict[str, Any], *, readonly: bool) -> dict[str, int]:
    counts = Counter()
    for engine in ENGINES:
        known = {str(r["queue_order"]): r for r in indexes[engine]["requests"]}
        for key, event in list(state["engines"][engine]["requests"].items()):
            require(key in known, "state contains request outside pinned aq index")
            row = known[key]
            require(event["request_sha256"] == row["request_sha256"], "resume request SHA differs")
            require(event.get("workspace") == str(attempt_paths(engine, row, event["attempt"])[2]),
                    "resume workspace differs")
            if event["status"] == "running":
                _, metrics, _ = attempt_paths(engine, row, event["attempt"])
                counts["interrupted"] += 1
                if not readonly:
                    interrupted = not metrics.exists()
                    if interrupted:
                        write_fixed(metrics, {"exit_code": -1, "wall_seconds": 0.0,
                            "max_rss_bytes": None, "measurement_method": "interrupted",
                            "runner_error_kind": "interrupted_without_metrics"})
                    final = finish_event(engine, row, event)
                    final["resumed_result"] = True
                    finalize_retry(final, read(metrics), interrupted=interrupted)
                    state["engines"][engine]["requests"][key] = final
                    save(state)
            else:
                require(event["status"] in TERMINAL | {"failed"}, "unknown saved status")
                checked_event(engine, row, event)
                counts[event["status"]] += 1
            for old in event.get("history", []):
                checked_event(engine, row, old)
        for group in state["engines"][engine]["groups"].values():
            receipt = group.get("join")
            if receipt:
                for key, sha_key in (("path", "sha256"), ("metrics_path", "metrics_sha256")):
                    runner.checked_sha(owned(Path(receipt[key])), receipt[sha_key], "saved join")
    for receipt in state.get("cleanup_receipts", []):
        for key in ("before", "after"):
            runner.checked_sha(owned(Path(receipt[f"{key}_path"])),
                               receipt[f"{key}_sha256"], f"saved cleanup {key}")
    return dict(counts)


def reserve_bytes(state: dict[str, Any]) -> dict[str, int]:
    retained = 0
    seen = set()
    for engine in ENGINES:
        for event in state["engines"][engine]["requests"].values():
            for attempt in [*event.get("history", []), event]:
                path = external(Path(attempt["workspace"]))
                if path not in seen and path.exists():
                    retained += workspace_cleanup.scan_stats(path)["retained_evidence"]["du_bytes"]
                    seen.add(path)
    return {"retained_evidence_bytes": retained}


def request_guard(state: dict[str, Any]) -> dict[str, Any]:
    while True:
        if STOP_SIGNAL is not None:
            raise Stop("interrupted", f"signal {STOP_SIGNAL}; stopped between requests")
        space = mount_check()
        reserve = reserve_bytes(state)
        peak = max(INITIAL_PEAK, state["observed_request_peak_bytes"])
        # Gate multiplier 1.2 (miiz, 2026-10-26; was 2): one observed peak plus 20 % headroom.
        required = math.ceil(1.2 * peak) + sum(reserve.values())
        record = {**space, **reserve, "observed_request_peak_bytes": peak,
                  "required_external_free_bytes": required,
                  "required_repo_free_bytes": MIN_FREE_BYTES, "checked_at": now()}
        if space["external_free_bytes"] >= required and space["repo_free_bytes"] >= MIN_FREE_BYTES:
            return record
        runner.append_jsonl(owned(OUTPUT / "disk-waits-v2.jsonl"), record)
        print(json.dumps({"status": "waiting_for_disk", **record}), flush=True)
        for _ in range(5):
            time.sleep(60)
            if STOP_SIGNAL is not None:
                raise Stop("interrupted", f"signal {STOP_SIGNAL}; disk wait interrupted")


def cleanup_request(state: dict[str, Any], engine: str, row: dict[str, Any],
                    event: dict[str, Any], *, retain: bool = True) -> int:
    checked_event(engine, row, event)
    workspace = attempt_paths(engine, row, event["attempt"])[2].parent
    legacy = OUTPUT / "workspace-cleanup-20261026"
    before = legacy / f"{row['revision_id']}-{row['queue_order']:06d}-before.json"
    after = legacy / f"{row['revision_id']}-{row['queue_order']:06d}-deleted.json"
    while event.get("imported_v1") and before.exists() and not after.exists():
        print(json.dumps({"status": "waiting_for_legacy_cleanup",
                          "queue_order": row["queue_order"]}), flush=True)
        time.sleep(60)
        if STOP_SIGNAL is not None:
            raise Stop("interrupted", "interrupted while waiting for legacy cleanup")
    stats = workspace_cleanup.scan_stats(workspace)
    state["observed_request_peak_bytes"] = max(state["observed_request_peak_bytes"], stats["du_bytes"])
    save(state)  # The measured peak must survive a crash during deletion.
    binding = {key: event.get(key) for key in ("engine", "queue_order", "revision",
                "attempt", "result_path", "result_sha256", "metrics_path", "metrics_sha256")}
    binding["request_sha256"] = row["request_sha256"]
    current = state["engines"][engine]["requests"][str(row["queue_order"])]
    binding["attempts"] = []
    for saved in [*current.get("history", []), current]:
        checked_event(engine, row, saved)
        binding["attempts"].append({k: saved.get(k) for k in
            ("attempt", "result_path", "result_sha256", "metrics_path", "metrics_sha256")})
    receipt = workspace_cleanup.cleanup_tree(workspace, EXTERNAL,
                owned(OUTPUT / "workspace-cleanup"), binding, retain)
    state["cleanup_receipts"].append(receipt)
    save(state)
    return receipt["freed_du_bytes"]


def revision_cleanup(state: dict[str, Any], engine: str, index: dict[str, Any],
                     revision: str) -> int:
    """Both pinned joins consume result JSON only; later engines need no store."""
    freed = 0
    results = []
    for row in rows_for(index, revision):
        event = state["engines"][engine]["requests"].get(str(row["queue_order"]))
        if not event:
            continue
        require(not needs_request(event), "cannot clean a group with pending requests")
        checked_event(engine, row, event)
        for attempt in [*event.get("history", []), event]:
            freed += cleanup_request(state, engine, row, attempt, retain=False)
        results.append({k: event.get(k) for k in
                        ("queue_order", "result_path", "result_sha256", "metrics_path", "metrics_sha256")})
    # Results/metrics live internally; remove sibling attempt logs and empty parents too.
    for row in rows_for(index, revision):
        event = state["engines"][engine]["requests"].get(str(row["queue_order"]))
        if event:
            target = attempt_paths(engine, row, event["attempt"])[2].parent
            if target.exists():
                receipt = workspace_cleanup.cleanup_tree(target, EXTERNAL,
                    owned(OUTPUT / "workspace-cleanup"),
                    {"engine": engine, "revision": revision, "queue_order": row["queue_order"],
                     "kind": "request_remainder", "results": results}, False)
                state["cleanup_receipts"].append(receipt)
                save(state)
                freed += receipt["freed_du_bytes"]
    for scope, ordinal, _, _ in groups_for(index, revision):
        for kind in ("caches", "stores"):
            target = external(EXTERNAL / engine / kind / scope / f"{ordinal:04d}")
            if target.exists():
                receipt = workspace_cleanup.cleanup_tree(target, EXTERNAL,
                    owned(OUTPUT / "workspace-cleanup"),
                    {"engine": engine, "revision": revision, "scope": scope,
                     "kind": kind, "results": results}, False)
                state["cleanup_receipts"].append(receipt)
                save(state)
                freed += receipt["freed_du_bytes"]
    return freed


def needs_request(event: dict[str, Any] | None) -> bool:
    return event is None or event["status"] == "running" or bool(
        event.get("retry_pending") or event.get("resume_pending"))


def reason_code(error: BaseException) -> str:
    if isinstance(error, OSError):
        return f"{type(error).__name__}:errno={error.errno}"
    return re.sub(r"\d+", "#", re.sub(r"/\S+", "<path>", str(error)))


def streak(state: dict[str, Any], field: str, reason: str | None, limit: int,
           stop_kind: str) -> None:
    previous = state.get(field, {})
    if reason is None:
        state[field] = {}
    else:
        count = previous.get("count", 0) + 1 if previous.get("reason") == reason else 1
        state[field] = {"reason": reason, "count": count}
        save(state)
        if count >= limit:
            raise Stop(stop_kind, f"{count} consecutive failures: {reason}")
    save(state)




def finalize_retry(final: dict[str, Any], metrics: dict[str, Any], *, interrupted: bool = False) -> None:
    failed = final["status"] in {"failed", "preparation_failure"}
    if failed and metrics.get("runner_error_kind"):
        final["failure_reason"] = metrics["runner_error_kind"]
    free = metrics.get("judging_free_bytes_at_finish")
    final["retry_pending"] = bool(failed and free is not None and free < GIB
                                  and final.get("disk_retries", 0) < 1)
    final["retry_reason"] = "judging_disk_below_1_gib" if final["retry_pending"] else None
    final["resume_pending"] = bool(interrupted and final["status"] == "failed")


def account_request(state: dict[str, Any], event: dict[str, Any]) -> Stop | None:
    if event.get("streak_counted") or event.get("retry_pending"):
        return None
    event["streak_counted"] = True
    reason = event.get("failure_reason") if event["status"] in {"failed", "preparation_failure"} else None
    try:
        streak(state, "request_failure_streak", reason, 5, "repeated_request_failure")
    except Stop as stop:
        return stop
    return None


def account_revision(state: dict[str, Any], key: str) -> None:
    record = state["revisions"][key]
    if not record.get("streak_counted"):
        record["streak_counted"] = True
        streak(state, "revision_failure_streak", record.get("failure_cause"), 2, "repeated_failure")


def run_request(state: dict[str, Any], engine: str, row: dict[str, Any],
                scope: str, ordinal: int, deadline: datetime) -> None:
    key = str(row["queue_order"])
    while needs_request(state["engines"][engine]["requests"].get(key)):
        old = state["engines"][engine]["requests"].get(key)
        free = request_guard(state)
        active = f"{engine}/{row['revision_id']}"
        if state.get("active_revision") != active:
            require(state.get("active_revision") is None, "unexpected unfinished revision")
            if datetime.now(timezone.utc) >= deadline:
                raise Stop("deadline", "no new revision at/after the UTC deadline")
            state["active_revision"] = active
            save(state)
        attempt = old["attempt"] + 1 if old else 1
        result_path, metrics_path, workspace = attempt_paths(engine, row, attempt)
        while any(p.exists() for p in (result_path, metrics_path, workspace)) or any(
                workspace.parent.glob(f"{workspace.name}.*")):
            attempt += 1
            result_path, metrics_path, workspace = attempt_paths(engine, row, attempt)
        probe = {"measurement_method": "wait4"}
        history = [*old.get("history", []), {k: v for k, v in old.items() if k != "history"}] if old else []
        retries = old.get("disk_retries", 0) + int(bool(old.get("retry_pending"))) if old else 0
        event = {"status": "running", "engine": engine, "queue_order": row["queue_order"],
                 "revision": row["revision_id"], "scope": scope, "method": row["method"],
                 "request_sha256": row["request_sha256"], "attempt": attempt,
                 "started_at": now(), "workspace": str(workspace),
                 "disk_before": free, "time_probe": probe, "disk_retries": retries,
                 "history": history}
        state["engines"][engine]["requests"][key] = event
        save(state)
        started = time.monotonic()
        try:
            runner.checked_sha(Path(row["request"]), row["request_sha256"], "request")
            request = read(Path(row["request"]))
            runner.checked_request_sources(row, request, row["queue_order"])
            runner.checked_sha(Path(request["base_input"]), INPUT_SHA256[row["revision_id"]], "constructed input")
            cache_root = external(EXTERNAL / engine / "caches")
            cache_root.mkdir(parents=True, exist_ok=True)
            cache = runner.initialize_cache(cache_root, scope, ordinal, row["revision_id"], INDEX_SHA256[engine])
            store = external(EXTERNAL / engine / "stores" / scope / f"{ordinal:04d}")
            store.parent.mkdir(parents=True, exist_ok=True)
            probe = runner.probe_time_l()
            event.update({"store": str(store), "time_probe": probe})
            save(state)
            metrics = runner.run_lift(row, workspace, cache, store, attempt, probe["measurement_method"])
        except ERRORS as error:
            metrics = {"exit_code": -1, "wall_seconds": time.monotonic() - started,
                       "max_rss_bytes": None, "measurement_method": probe["measurement_method"],
                       "runner_error": str(error), "runner_error_kind": reason_code(error)}
        metrics["judging_free_bytes_at_finish"] = runner.disk_free(MOUNT)
        if metrics.get("exit_code") != 0 and metrics.get("stderr_path"):
            stderr = external(Path(metrics["stderr_path"]))
            if stderr.is_file():
                metrics["stderr_sha256"] = runner.sha256(stderr)
                with stderr.open("rb") as stream:
                    stream.seek(max(0, stderr.stat().st_size - 65536))
                    lines = stream.read().decode("utf-8", errors="replace").splitlines()
                diagnostics = [line.strip() for line in lines if
                    line.lstrip().lower().startswith(("error:", "error[", "caused by:", "thread '"))]
                if diagnostics:
                    metrics["failure_diagnostic"] = "\\n".join(diagnostics[:8])
        write_fixed(metrics_path, metrics)
        final = finish_event(engine, row, event)
        finalize_retry(final, metrics)
        state["engines"][engine]["requests"][key] = final
        save(state)
        runner.append_jsonl(owned(OUTPUT / "attempts-v2.jsonl"), final)
        failure_stop = account_request(state, final)
        cleanup_request(state, engine, row, final)
        if failure_stop:
            raise failure_stop
        if STOP_SIGNAL is not None:
            raise Stop("interrupted", f"signal {STOP_SIGNAL}; request saved")


def score_revision(state: dict[str, Any], engine: str, revision: str) -> dict[str, Any]:
    serial = 1
    directory = owned(OUTPUT / "rqc")
    directory.mkdir(parents=True, exist_ok=True)
    while (directory / f"{engine}-{revision}-{serial:04d}.json").exists() or (
            OUTPUT / f"rqc-state-{engine}-{revision}-{serial:04d}.json").exists():
        serial += 1
    output = directory / f"{engine}-{revision}-{serial:04d}.json"
    # Snapshot stays at OUTPUT so relative join-result paths keep their meaning.
    snapshot = owned(OUTPUT / f"rqc-state-{engine}-{revision}-{serial:04d}.json")
    compatible = copy.deepcopy(state)
    compatible["schema"] = "n6-a-remeasure-aq-execute-v1"
    write_fixed(snapshot, rqc.normalize_state(compatible, engine))
    command = [sys.executable, "-B", str(Path(rqc.__file__)), "--protocol",
        str(ROOT / "docs/n5_evaluation_protocol_v1_2026-10-06.md"), "--targets",
        str(ROOT / "docs/n6_targets_a_2026-10-07.json"), "--mapping", str(MAPPING),
        "--preparation", str(ROOT / "runs/n6-a1-2026-10-07/preparation-units.json"),
        "--index", str(prepared.PREPARED / f"request-index-{engine}.json"),
        "--state", str(snapshot), "--engine", engine, "--layer", "exploratory",
        "--output", str(output)]
    receipt = {"path": str(output), "state_path": str(snapshot),
               "state_sha256": runner.sha256(snapshot), "command": command}
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        receipt.update({"exit_code": completed.returncode, "stdout": completed.stdout,
                        "stderr": completed.stderr, "status": "completed" if completed.returncode == 0 else "error"})
        if output.is_file():
            receipt["sha256"] = runner.sha256(output)
        require(completed.returncode != 0 or output.is_file(), "scorer returned no output")
    except ERRORS as error:
        receipt.update({"status": "error", "reason": str(error)})
    return receipt


def progress(state: dict[str, Any], engine: str, index: dict[str, Any], revision: str,
             effective: dict[tuple[str, str], str] | None, error: str | None = None) -> None:
    flush_progress(state)
    rows = rows_for(index, revision)
    if effective is None:
        counts = Counter(state["engines"][engine]["requests"].get(str(r["queue_order"]), {})
                         .get("status", "not_run") for r in rows)
        times = [e["wall_seconds"] for r in rows
                 if (e := state["engines"][engine]["requests"].get(str(r["queue_order"])))
                 and e.get("wall_seconds") is not None]
        stats = {"requests": len(rows), "completed": counts["completed"],
                 "preparation_failure": counts["preparation_failure"], "errors": counts["failed"],
                 "not_run": counts["not_run"], "running": counts["running"],
                 "L1": None, "excluded": None, "unknown": None,
                 "wall_seconds": {"count": len(times), "sum": sum(times),
                      "mean": sum(times) / len(times) if times else None, "max": max(times) if times else None},
                 "classification_error": error}
    else:
        stats = summary(state, engine, rows, effective)
    key = f"{engine}/{revision}"
    record = {"engine": engine, "revision": revision, "layer": LAYER, "finished_at": now(),
              **stats, "failures": stats["errors"] + stats["preparation_failure"],
              "workspace_bytes_freed": sum(r["freed_du_bytes"] for r in state["cleanup_receipts"]
                  if r["binding"].get("engine") == engine and r["binding"].get("revision") == revision
                  and r["binding"].get("kind") not in {"caches", "stores"}),
              "cache_store_bytes_freed": sum(r["freed_du_bytes"] for r in state["cleanup_receipts"]
                  if r["binding"].get("engine") == engine and r["binding"].get("revision") == revision
                  and r["binding"].get("kind") in {"caches", "stores"}),
              "revision_status": state["revisions"][key]["status"], "revision_error": error}
    save(state)
    try:
        record["rqc"] = score_revision(state, engine, revision)
    except ERRORS as score_error:
        record["rqc"] = {"status": "error", "reason": str(score_error)}
    path = owned(OUTPUT / "progress-v2.jsonl")
    state["pending_progress"] = {"offset": path.stat().st_size if path.exists() else 0,
        "line": json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"}
    state["revisions"][key]["progress_saved"] = True
    save(state)
    flush_progress(state)


def execute_revision(state: dict[str, Any], engine: str, index: dict[str, Any],
                     revision: str, order: list[dict[str, Any]], deadline: datetime) -> None:
    key = f"{engine}/{revision}"
    effective = None
    error = cause = None
    state["revisions"].setdefault(key, {"status": "pending", "started_at": now()})
    rows = {r["queue_order"]: r for r in rows_for(index, revision)}
    group_map = {r["queue_order"]: (scope, ordinal) for scope, ordinal, _, group
                 in groups_for(index, revision) for r in group}
    try:
        configure(engine)
        for item in order:
            if item["engine"] != engine or item["revision"] != revision:
                continue
            row = rows[item["queue_order"]]
            event = state["engines"][engine]["requests"].get(str(row["queue_order"]))
            if event and not needs_request(event):
                checked_event(engine, row, event)
                failure_stop = account_request(state, event)
                cleanup_request(state, engine, row, event)
                if failure_stop:
                    raise failure_stop
                continue
            run_request(state, engine, row, *group_map[row["queue_order"]], deadline)
        try:
            effective = effective_for(state, engine, index, revision, allow_join=True)
        finally:
            revision_cleanup(state, engine, index, revision)
        events = [state["engines"][engine]["requests"].get(str(r), {}) for r in rows]
        if events and all(e.get("status") in {"preparation_failure", "failed"} for e in events):
            reasons = sorted({e.get("failure_reason") or "preparation_not_ok" for e in events})
            error = cause = "all_requests_failed:" + ",".join(reasons)
    except Stop:
        raise
    except ERRORS as failure:
        error, cause = str(failure), reason_code(failure)
    state["revisions"][key].pop("progress_saved", None)
    state["revisions"][key].pop("streak_counted", None)
    state["revisions"][key].update({"status": "failed" if error else "completed",
        "failure_reason": error, "failure_cause": cause, "finished_at": now()})
    state["active_revision"] = None
    save(state)
    progress(state, engine, index, revision, effective, error)
    account_revision(state, key)


def execute(state: dict[str, Any], indexes: dict[str, Any], order: list[dict[str, Any]],
            deadline: datetime) -> dict[str, Any]:
    engine = revision = None
    try:
        flush_progress(state)
        recover(state, indexes, readonly=False)
        for field, limit, kind in (("request_failure_streak", 5, "repeated_request_failure"),
                                   ("revision_failure_streak", 2, "repeated_failure")):
            if state.get(field, {}).get("count", 0) >= limit:
                raise Stop(kind, f"saved failure limit reached: {state[field]}")
        # Reconcile imported/completed attempts before the first disk gate.
        for prior_engine in ENGINES:
            by_key = {str(r["queue_order"]): r for r in indexes[prior_engine]["requests"]}
            for prior_key, prior_event in state["engines"][prior_engine]["requests"].items():
                if prior_event["status"] != "running":
                    cleanup_request(state, prior_engine, by_key[prior_key], prior_event)
        state.update({"status": "running", "stop_kind": None, "stop_reason": None})
        save(state)
        for engine in ENGINES:
            for revision in DEFAULT_REVISIONS:
                key = f"{engine}/{revision}"
                record = state["revisions"].get(key, {})
                if record.get("status") in {"completed", "failed"}:
                    if not record.get("progress_saved"):
                        effective = (effective_for(state, engine, indexes[engine], revision, allow_join=False)
                                     if record["status"] == "completed" else None)
                        progress(state, engine, indexes[engine], revision, effective, record.get("failure_reason"))
                    account_revision(state, key)
                    continue
                if state.get("active_revision") != key and datetime.now(timezone.utc) >= deadline:
                    raise Stop("deadline", "no new revision at/after the UTC deadline")
                execute_revision(state, engine, indexes[engine], revision, order, deadline)
        state.update({"status": "completed", "finished_at": now()})
        save(state)
    except (*ERRORS, KeyboardInterrupt) as error:
        kind = error.kind if isinstance(error, Stop) else "interrupted" if isinstance(error, KeyboardInterrupt) else "error"
        state.update({"status": "stopped", "stop_kind": kind, "stop_reason": str(error), "stopped_at": now()})
        save(state)
        if (engine and revision and f"{engine}/{revision}" in state["revisions"]
                and state["revisions"][f"{engine}/{revision}"]["status"] not in {"completed", "failed"}):
            state["revisions"][f"{engine}/{revision}"]["status"] = "interrupted"
            try:
                progress(state, engine, indexes[engine], revision, None, str(error))
            except ERRORS as progress_error:
                state["progress_error"] = str(progress_error)
                save(state)
    return {"status": state["status"], "stop_kind": state.get("stop_kind"),
            "reason": state.get("stop_reason"), "state": str(OUTPUT / "state-v2.json"),
            "completed": {e: sum(x["status"] == "completed" for x in state["engines"][e]["requests"].values())
                          for e in ENGINES}, "layer": LAYER}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=("validate-only", "execute"))
    parser.add_argument("--no-new-revision-after", default=DEFAULT_DEADLINE)
    args = parser.parse_args()
    try:
        deadline = deadline_value(args.no_new_revision_after)
        require(deadline == deadline_value(DEFAULT_DEADLINE), "approved deadline must remain unchanged")
        pins = verify_pins()
        indexes, report = validate_sources(list(DEFAULT_REVISIONS))
        order = ordering.computed_order(indexes, list(DEFAULT_REVISIONS), read(MAPPING))
        binding = configuration(order, deadline)
        state = load_state(binding)
        resume = recover(state, indexes, readonly=True)
        report.update(pins)
        report.update({"schema": SCHEMA, "script_sha256": runner.sha256(Path(__file__)),
            "resume": resume, "resume_source": state["imported_state"],
            "state_v2_exists": (OUTPUT / "state-v2.json").exists(),
            "computed_order": order, "computed_order_sha256": digest_json(order),
            "observed_request_peak_bytes": state["observed_request_peak_bytes"],
            "no_new_revision_after": deadline.isoformat(), "judging_executed": False})
        if args.action == "validate-only":
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0 if report["status"] == "valid" else 2
        require(report["status"] == "valid", f"source validation failed: {report['source_errors']}")
        with owned(OUTPUT / ".runner.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state = load_state(binding)
            write_fixed(OUTPUT / "request-order-v2.json",
                        {"sha256": digest_json(order), "requests": order, "config": binding})
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
            result = execute(state, indexes, order, deadline)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 3 if result["status"] == "stopped" else 0
    except ERRORS as error:
        print(json.dumps({"status": "stopped", "stop_kind": getattr(error, "kind", "error"),
                          "reason": str(error), "judging_executed": False}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
