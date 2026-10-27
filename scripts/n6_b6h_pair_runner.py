#!/usr/bin/env python3
"""Run the fixed B J engines in a pinned request-pair order.

Order preparation reads only index request path basenames and the B state status
projection. Execution delegates one request at a time to n6_b6h_j_runner.
This module never reads request bodies, result JSON, or verdict fields.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
from typing import Any, Callable

import n6_b6h_j_runner as b6h


SEED = 20261024
CUTOFF_UTC = "2026-10-29T14:59:00Z"
REQUEST_COUNT = 107
TERMINAL = frozenset({"completed", "preparation_failure", "inspection_failure"})
PAIR_ROOT = b6h.RECORD_OUT.parent
ORDER_PATH = PAIR_ROOT / "pair-order-v1.json"
STATE_PATH = PAIR_ROOT / "pair-state-v1.json"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class PairError(Exception):
    """A pinned order, state, or one-request execution is unsafe to continue."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PairError(message)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(moment: datetime | None = None) -> str:
    return (moment or utc_now()).astimezone(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"file missing or linked: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_sha(path: Path, expected: str, label: str) -> None:
    require(bool(HEX64.fullmatch(expected)), f"{label} SHA-256 invalid")
    require(sha256_file(path) == expected, f"{label} SHA-256 differs")


def index_ids(path: Path, expected_sha: str) -> list[str]:
    """Project only queue_order and request filename, never a request body."""
    checked_sha(path, expected_sha, "request index")
    with path.open(encoding="utf-8") as stream:
        index = json.load(stream)
    rows = index.get("requests")
    require(isinstance(rows, list) and len(rows) == REQUEST_COUNT and
            index.get("request_count") == REQUEST_COUNT,
            "request index count differs")
    ids: list[str] = []
    for order, row in enumerate(rows):
        require(isinstance(row, dict) and row.get("queue_order") == order,
                f"request index order differs at {order}")
        request_text = row.get("request")
        require(isinstance(request_text, str),
                f"request index path missing at {order}")
        request = Path(request_text)
        require(request.is_absolute() and request.suffix == ".json" and
                bool(request.stem), f"request index path invalid at {order}")
        ids.append(request.stem)
    require(len(set(ids)) == REQUEST_COUNT, "request IDs are not unique")
    return ids


def index_revision_groups(path: Path, expected_sha: str) -> list[list[int]]:
    """Project only revision boundaries and queue orders from the fixed index."""
    checked_sha(path, expected_sha, "request index")
    with path.open(encoding="utf-8") as stream:
        index = json.load(stream)
    rows = index.get("requests")
    require(isinstance(rows, list) and len(rows) == REQUEST_COUNT and
            index.get("request_count") == REQUEST_COUNT,
            "request index count differs")
    groups: list[list[int]] = []
    previous: tuple[str, str] | None = None
    seen: set[tuple[str, str]] = set()
    for order, row in enumerate(rows):
        require(isinstance(row, dict) and row.get("queue_order") == order and
                isinstance(row.get("scope"), str) and
                isinstance(row.get("revision_id"), str),
                f"request revision metadata differs at {order}")
        key = (row["scope"], row["revision_id"])
        if key != previous:
            require(key not in seen, "request revision is not contiguous")
            groups.append([])
            seen.add(key)
            previous = key
        groups[-1].append(order)
    return groups


def state_projection(path: Path, *, required: bool = False) -> tuple[str, dict[int, str]]:
    """Access only top status and each request key/status in a B state."""
    if not path.exists():
        require(not required, f"B state missing: {path}")
        return "not_started", {}
    require(path.is_file() and not path.is_symlink(), f"B state invalid: {path}")
    with path.open(encoding="utf-8") as stream:
        state = json.load(stream)
    require(isinstance(state, dict), f"B state object invalid: {path}")
    top = state.get("status")
    requests = state.get("requests")
    require(isinstance(top, str) and isinstance(requests, dict),
            f"B state status projection invalid: {path}")
    projected: dict[int, str] = {}
    for key, item in requests.items():
        require(isinstance(key, str) and key.isdecimal() and
                isinstance(item, dict), f"B state request key invalid: {path}")
        order = int(key)
        status = item.get("status")
        require(0 <= order < REQUEST_COUNT and status in TERMINAL,
                f"B state request status invalid at {order}")
        require(order not in projected, f"B state duplicate order {order}")
        projected[order] = status
    return top, projected


def engine_state_path(engine: str) -> Path:
    require(engine in {"v1", "v2.2"}, "unknown B engine")
    return b6h.RUN_OUT / f"full-{engine}.noindex" / "state.json"


def request_id_sha(request_id: str) -> str:
    return hashlib.sha256(request_id.encode("utf-8")).hexdigest()


def task_sequence(ids: list[str], prefix_orders: list[int]) -> tuple[list[int], list[dict[str, Any]]]:
    require(len(ids) == REQUEST_COUNT and len(set(ids)) == REQUEST_COUNT,
            "request ID projection invalid")
    require(prefix_orders == sorted(set(prefix_orders)) and
            all(type(order) is int and 0 <= order < REQUEST_COUNT
                for order in prefix_orders), "completed prefix invalid")
    prefix = set(prefix_orders)
    remaining = sorted((order for order in range(REQUEST_COUNT)
                        if order not in prefix), key=lambda order: ids[order])
    random.Random(SEED).shuffle(remaining)
    tasks: list[dict[str, Any]] = []
    for order in prefix_orders:
        tasks.append({"phase": "prefix", "engine": "v1", "queue_order": order,
                      "request_id_sha256": request_id_sha(ids[order])})
    for order in remaining:
        for engine in ("v2.2", "v1"):
            tasks.append({"phase": "shuffle", "engine": engine,
                          "queue_order": order,
                          "request_id_sha256": request_id_sha(ids[order])})
    return remaining, tasks


def order_document(v1_ids: list[str], v22_ids: list[str],
                   v1_sha: str, v22_sha: str,
                   v22_finished: dict[int, str]) -> dict[str, Any]:
    require(v1_ids == v22_ids, "v1/v2.2 request IDs differ")
    prefix = sorted(v22_finished)
    remaining, tasks = task_sequence(v22_ids, prefix)
    return {"schema_version": 1, "kind": "n6_b6h_pair_order",
            "created_at": utc_text(), "seed": SEED, "cutoff_utc": CUTOFF_UTC,
            "v1_index_sha256": v1_sha, "v2_2_index_sha256": v22_sha,
            "completed_prefix_orders": prefix,
            "shuffled_remaining_orders": remaining, "tasks": tasks}


def validate_order(document: dict[str, Any], v1_ids: list[str],
                   v22_ids: list[str], v1_sha: str, v22_sha: str) -> None:
    require(isinstance(document, dict) and
            document.get("schema_version") == 1 and
            document.get("kind") == "n6_b6h_pair_order" and
            document.get("seed") == SEED and
            document.get("cutoff_utc") == CUTOFF_UTC and
            document.get("v1_index_sha256") == v1_sha and
            document.get("v2_2_index_sha256") == v22_sha,
            "pair order lock differs")
    require(v1_ids == v22_ids, "v1/v2.2 request IDs differ")
    prefix = document.get("completed_prefix_orders")
    require(isinstance(prefix, list), "pair prefix missing")
    remaining, tasks = task_sequence(v22_ids, prefix)
    require(document.get("shuffled_remaining_orders") == remaining and
            document.get("tasks") == tasks,
            "pair order is not the pinned ID-sort shuffle")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    require(not path.is_symlink(), f"pair state is linked: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_new_order(path: Path, document: dict[str, Any]) -> str:
    require(path == ORDER_PATH and not path.exists() and not path.is_symlink(),
            "pair order path differs or already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return sha256_file(path)


def load_order(path: Path, expected_sha: str, v1_ids: list[str],
               v22_ids: list[str], v1_sha: str, v22_sha: str) -> dict[str, Any]:
    require(path == ORDER_PATH, "pair order path differs")
    checked_sha(path, expected_sha, "pair order")
    with path.open(encoding="utf-8") as stream:
        document = json.load(stream)
    validate_order(document, v1_ids, v22_ids, v1_sha, v22_sha)
    return document


def first_pending(tasks: list[dict[str, Any]],
                  projections: dict[str, dict[int, str]]) -> int:
    for index, task in enumerate(tasks):
        if task["queue_order"] not in projections[task["engine"]]:
            return index
    return len(tasks)


def pair_state(document: dict[str, Any], order_sha: str, *,
               status: str, stop_kind: str | None = None,
               stop_at: str | None = None) -> dict[str, Any]:
    require(status in {"prepared", "running", "stopped", "completed"} and
            stop_kind in {None, "space", "time"}, "pair status invalid")
    projections = {engine: state_projection(engine_state_path(engine))[1]
                   for engine in ("v1", "v2.2")}
    tasks = document["tasks"]
    return {"schema_version": 1, "kind": "n6_b6h_pair_state",
            "order_file": str(ORDER_PATH), "order_sha256": order_sha,
            "cutoff_utc": CUTOFF_UTC, "status": status,
            "stop_kind": stop_kind, "stop_at": stop_at,
            "next_task_index": first_pending(tasks, projections),
            "task_count": len(tasks),
            "completed_prefix_orders": document["completed_prefix_orders"],
            "shuffled_remaining_orders": document["shuffled_remaining_orders"],
            "unfinished_by_engine": {
                engine: REQUEST_COUNT - len(projections[engine])
                for engine in ("v1", "v2.2")},
            "updated_at": utc_text()}


def engine_command(args: argparse.Namespace, engine: str) -> list[str]:
    require(engine in {"v1", "v2.2"}, "unknown B engine")
    index_sha = (args.v1_index_sha256 if engine == "v1"
                 else args.v2_2_index_sha256)
    static_sha = (args.v1_static_preflight_sha256 if engine == "v1"
                  else args.v2_2_static_preflight_sha256)
    return [sys.executable, str(b6h.ROOT / "scripts/n6_b6h_j_runner.py"),
            "--engine", engine,
            "--index", str(b6h.OUT / f"request-index-{engine}.json"),
            "--index-sha256", index_sha,
            "--static-preflight", str(b6h.OUT / f"static-preflight-96mib-{engine}.json"),
            "--static-preflight-sha256", static_sha,
            "--first-lead-review-sha256", args.first_lead_review_sha256,
            "--second-lead-review-sha256", args.second_lead_review_sha256,
            "--cache-root", str(b6h.CACHE / f"full-{engine}"),
            "--output", str(b6h.RUN_OUT / f"full-{engine}.noindex"),
            "--workspace-root", str(b6h.WORKSPACES),
            "--instance-root", str(b6h.STORES),
            "--observed-request-peak-bytes", str(args.observed_request_peak_bytes)]


def one_request_command(args: argparse.Namespace, engine: str, order: int) -> list[str]:
    require(type(order) is int and 0 <= order < REQUEST_COUNT,
            "one-request command target invalid")
    return engine_command(args, engine) + [
        "--action", "execute-one", "--queue-order", str(order)]


def reconcile_command(args: argparse.Namespace, engine: str) -> list[str]:
    return engine_command(args, engine) + ["--action", "reconcile-cleanup"]


def reconcile_completed_revisions(
    groups: list[list[int]],
    status_reader: Callable[[str], tuple[str, dict[int, str]]],
    launch: Callable[[str, int], int],
) -> None:
    """Replay only terminal rows to finish a join interrupted after result state."""
    require(sum(map(len, groups)) == REQUEST_COUNT and
            sorted(order for group in groups for order in group) ==
            list(range(REQUEST_COUNT)), "revision groups differ from index")
    for engine in ("v2.2", "v1"):
        top, finished = status_reader(engine)
        if top == "completed":
            continue
        representatives = ([groups[-1][-1]] if len(finished) == REQUEST_COUNT
                           else [group[-1] for group in groups
                                 if all(order in finished for order in group)])
        for representative in representatives:
            exit_code = launch(engine, representative)
            require(exit_code == 0,
                    f"{engine} completed revision replay failed at {representative}")
            _top, after = status_reader(engine)
            require(set(finished) <= set(after) and
                    representative in after,
                    f"{engine} completed revision replay regressed state")
            finished = after


def drive_tasks(
    tasks: list[dict[str, Any]],
    status_reader: Callable[[str], tuple[str, dict[int, str]]],
    launch: Callable[[str, int], int],
    clock: Callable[[], datetime],
    cutoff: datetime,
    progress: Callable[[], None] | None = None,
) -> tuple[str | None, int]:
    """Run only absent engine/request pairs; do not interrupt an active call."""
    for index, task in enumerate(tasks):
        engine = task["engine"]
        order = task["queue_order"]
        _top, finished = status_reader(engine)
        if order in finished:
            if progress is not None:
                progress()
            continue
        if clock() >= cutoff:
            return "time", index
        exit_code = launch(engine, order)
        top, finished = status_reader(engine)
        if exit_code != 0:
            if top == "disk_guard_stopped":
                return "space", index
            raise PairError(f"{engine} request {order} stopped with exit {exit_code}; B state status {top}")
        require(order in finished,
                f"{engine} request {order} returned without terminal B state")
        if progress is not None:
            progress()
    return None, len(tasks)


def execute_pairs(args: argparse.Namespace, document: dict[str, Any],
                  order_sha: str) -> int:
    cutoff = datetime.fromisoformat(CUTOFF_UTC.replace("Z", "+00:00"))
    baseline = document["completed_prefix_orders"]
    current_v22 = state_projection(engine_state_path("v2.2"), required=True)[1]
    require(all(order in current_v22 for order in baseline),
            "v2.2 completed prefix has regressed")
    if STATE_PATH.exists():
        require(STATE_PATH.is_file() and not STATE_PATH.is_symlink(),
                "pair state invalid")
        with STATE_PATH.open(encoding="utf-8") as stream:
            old = json.load(stream)
        require(isinstance(old, dict) and
                old.get("kind") == "n6_b6h_pair_state" and
                old.get("order_sha256") == order_sha and
                old.get("cutoff_utc") == CUTOFF_UTC,
                "existing pair state lock differs")

    def update(status: str, stop_kind: str | None = None,
               stop_at: str | None = None) -> dict[str, Any]:
        value = pair_state(document, order_sha, status=status,
                           stop_kind=stop_kind, stop_at=stop_at)
        atomic_json(STATE_PATH, value)
        return value

    def read(engine: str) -> tuple[str, dict[int, str]]:
        return state_projection(engine_state_path(engine))

    def invoke(command: list[str]) -> int:
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(command, cwd=b6h.ROOT, env=environment,
                              check=False).returncode

    def launch(engine: str, order: int) -> int:
        return invoke(one_request_command(args, engine, order))

    update("running")
    try:
        for engine in ("v2.2", "v1"):
            require(invoke(reconcile_command(args, engine)) == 0,
                    f"{engine} cleanup reconciliation failed")
        groups = index_revision_groups(b6h.OUT / "request-index-v2.2.json",
                                       args.v2_2_index_sha256)
        require(groups == index_revision_groups(
            b6h.OUT / "request-index-v1.json", args.v1_index_sha256),
            "v1/v2.2 revision grouping differs")
        reconcile_completed_revisions(groups, read, launch)
        stop_kind, _next = drive_tasks(document["tasks"], read, launch,
                                       utc_now, cutoff, lambda: update("running"))
    except PairError:
        update("stopped", stop_at=utc_text())
        raise
    if stop_kind is not None:
        state = update("stopped", stop_kind, utc_text())
        print(json.dumps({"status": "incomplete", "stop_kind": stop_kind,
                          "next_task_index": state["next_task_index"],
                          "unfinished_by_engine": state["unfinished_by_engine"],
                          "pair_state": str(STATE_PATH)}, sort_keys=True))
        return 3
    tops = {engine: state_projection(engine_state_path(engine))[0]
            for engine in ("v1", "v2.2")}
    state = update("completed" if all(top == "completed" for top in tops.values())
                   else "stopped")
    require(state["status"] == "completed" and
            all(count == 0 for count in state["unfinished_by_engine"].values()),
            "all pair tasks finished but engine state is not completed")
    print(json.dumps({"status": "completed", "order_sha256": order_sha,
                      "task_count": state["task_count"],
                      "pair_state": str(STATE_PATH)}, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("prepare-order", "execute-pairs"),
                        required=True)
    parser.add_argument("--v1-index-sha256", required=True)
    parser.add_argument("--v2-2-index-sha256", required=True)
    parser.add_argument("--v1-static-preflight-sha256", required=True)
    parser.add_argument("--v2-2-static-preflight-sha256", required=True)
    parser.add_argument("--first-lead-review-sha256", required=True)
    parser.add_argument("--second-lead-review-sha256", required=True)
    parser.add_argument("--observed-request-peak-bytes", type=int, required=True)
    parser.add_argument("--no-new-request-after", required=True)
    parser.add_argument("--order-sha256")
    args = parser.parse_args(argv)
    try:
        require(args.no_new_request_after == CUTOFF_UTC,
                "B6h no-new-request cutoff differs")
        require(args.observed_request_peak_bytes == b6h.OBSERVED_REQUEST_PEAK_BYTES,
                "B6h measured peak differs")
        for label, value in (
            ("v1 index", args.v1_index_sha256),
            ("v2.2 index", args.v2_2_index_sha256),
            ("v1 static preflight", args.v1_static_preflight_sha256),
            ("v2.2 static preflight", args.v2_2_static_preflight_sha256),
            ("first lead review", args.first_lead_review_sha256),
            ("second lead review", args.second_lead_review_sha256),
        ):
            require(bool(HEX64.fullmatch(value)), f"{label} SHA-256 invalid")
        v1_ids = index_ids(b6h.OUT / "request-index-v1.json",
                           args.v1_index_sha256)
        v22_ids = index_ids(b6h.OUT / "request-index-v2.2.json",
                            args.v2_2_index_sha256)
        if args.action == "prepare-order":
            require(args.order_sha256 is None,
                    "prepare-order must not accept an existing order SHA")
            require(not STATE_PATH.exists() and not STATE_PATH.is_symlink(),
                    "pair state already exists")
            _top, finished = state_projection(engine_state_path("v2.2"),
                                              required=True)
            document = order_document(v1_ids, v22_ids,
                                      args.v1_index_sha256,
                                      args.v2_2_index_sha256, finished)
            order_sha = write_new_order(ORDER_PATH, document)
            state = pair_state(document, order_sha, status="prepared")
            atomic_json(STATE_PATH, state)
            print(json.dumps({"status": "prepared", "order_file": str(ORDER_PATH),
                              "order_sha256": order_sha,
                              "completed_prefix_count": len(document["completed_prefix_orders"]),
                              "shuffled_remaining_count": len(document["shuffled_remaining_orders"]),
                              "task_count": len(document["tasks"])}, sort_keys=True))
            return 0
        require(isinstance(args.order_sha256, str),
                "execute-pairs requires --order-sha256")
        document = load_order(ORDER_PATH, args.order_sha256, v1_ids, v22_ids,
                              args.v1_index_sha256, args.v2_2_index_sha256)
        return execute_pairs(args, document, args.order_sha256)
    except (OSError, ValueError, json.JSONDecodeError, PairError) as error:
        print(f"B6h pair runner refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
