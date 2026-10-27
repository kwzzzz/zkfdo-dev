#!/usr/bin/env python3
"""After the deadline, count paired B6h requests and compare fixed-engine J results.

Only miiz invokes this on B. The gate emits counts, never candidate or verdict
values. It runs each pinned engine's unchanged lift-instances on the paired
completed subset so N5's effective instance judgement is preserved.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import n6_b6h_j_runner as b6h
import run_n6_j1 as runner
from n6_b5_j_adapter import ENGINE_V1, ENGINE_V1_SHA, ENGINE_V22, ENGINE_V22_SHA

ROOT = Path(__file__).resolve().parents[1]
RUN_OUT = ROOT / "runs/n6-b6g-2026-10-23.noindex"
B6H_OUT = ROOT / "runs/n6-b6h-2026-10-24.noindex"
INDEX_OUT = ROOT / "runs/n6-b6e-2026-10-20.noindex"
PAIR_ORDER = B6H_OUT / "pair-order-v1.json"
PAIR_STATE = B6H_OUT / "pair-state-v1.json"
CUTOFF = "2026-10-29T14:59:00Z"
TERMINAL = frozenset({"completed", "preparation_failure", "inspection_failure"})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def parse_utc(value: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), "UTC cutoff is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.utcoffset() is not None, "UTC cutoff lacks timezone")
    return parsed.astimezone(timezone.utc)


def validate_order(order: dict[str, Any], count: int) -> None:
    prefix = order.get("completed_prefix_orders")
    remaining = order.get("shuffled_remaining_orders")
    tasks = order.get("tasks")
    require(isinstance(prefix, list) and isinstance(remaining, list) and
            isinstance(tasks, list) and
            all(type(i) is int and 0 <= i < count for i in prefix + remaining) and
            prefix == sorted(prefix) and
            len(set(prefix + remaining)) == count and
            set(prefix + remaining) == set(range(count)),
            "pair order coverage differs")
    expected = [("prefix", "v1", i) for i in prefix]
    for i in remaining:
        expected.extend((("shuffle", "v2.2", i), ("shuffle", "v1", i)))
    require(len(tasks) == len(expected), "pair task count differs")
    for task, (phase, engine, index) in zip(tasks, expected):
        require(isinstance(task, dict) and task.get("phase") == phase and
                task.get("engine") == engine and task.get("queue_order") == index and
                isinstance(task.get("request_id_sha256"), str) and
                len(task["request_id_sha256"]) == 64,
                "pair task sequence differs")


def terminal_orders(state: dict[str, Any] | None, count: int) -> tuple[set[int], set[int]]:
    """Read only B state request keys and status metadata."""
    if state is None:
        return set(), set()
    requests = state.get("requests")
    require(isinstance(requests, dict), "request state mapping missing")
    finished: set[int] = set()
    judged: set[int] = set()
    for key, item in requests.items():
        require(isinstance(key, str) and key.isdigit() and isinstance(item, dict),
                "request state entry malformed")
        order = int(key)
        require(0 <= order < count, "request state order outside index")
        status = item.get("status")
        require(status in TERMINAL, "state contains nonterminal request event")
        finished.add(order)
        if status == "completed":
            judged.add(order)
    return finished, judged


def unfinished_breakdown(count: int, finished: set[int], stop_kind: str | None) -> dict[str, int]:
    remaining = count - len(finished)
    require(remaining >= 0 and stop_kind in (None, "time", "space"),
            "invalid gate stop cause")
    require(remaining == 0 or stop_kind in ("time", "space"),
            "unfinished requests lack time/space cause")
    return {"finished": len(finished), "unfinished": remaining,
            "unfinished_time": remaining if stop_kind == "time" else 0,
            "unfinished_space": remaining if stop_kind == "space" else 0}


def compare_flags(v1: tuple[bool, bool], v22: tuple[bool, bool]) -> dict[str, bool]:
    """N5 (가), (나), (다) on one request judged by both engines."""
    v1_l1, v1_excluded = v1
    v22_l1, v22_excluded = v22
    return {"a_v1_only_l1": v1_l1 and not v22_l1,
            "b_v2_2_only_l1": v22_l1 and not v1_l1,
            "c_excluded_vs_l1": ((v1_excluded and v22_l1) or
                                  (v22_excluded and v1_l1))}


def judgement_flags(result: dict[str, Any], effective: dict[tuple[str, str], str]) -> tuple[bool, bool]:
    request_id = result.get("request_id")
    classes = result.get("classes")
    require(isinstance(request_id, str) and isinstance(classes, list),
            "paired result format differs")
    l1 = False
    excluded = False
    for item in classes:
        require(isinstance(item, dict), "paired class format differs")
        own = item.get("verdict")
        representative = item.get("representative")
        require(isinstance(representative, str), "paired class representative missing")
        instance = effective.get((request_id, representative))
        l1 |= own == "entrypoint_violation" or instance == "assumption_violation_reachable"
        excluded |= own == "excluded_in_context" or instance == "assumption_excluded_in_context"
    return l1, excluded and not l1


def checked_result(item: dict[str, Any], output: Path, order: int) -> tuple[Path, dict[str, Any]]:
    """Only called for rows with both engines terminal and both result-bearing."""
    path_text = item.get("result_path")
    recorded_sha = item.get("result_sha256")
    require(isinstance(path_text, str) and isinstance(recorded_sha, str) and
            len(recorded_sha) == 64, f"paired result reference missing at {order}")
    path = Path(path_text)
    require(path.is_absolute() and path.is_file() and not path.is_symlink() and
            path.resolve().is_relative_to(output.resolve()),
            f"paired result path missing or escaped at {order}")
    require(digest(path) == recorded_sha, f"paired result SHA differs at {order}")
    result = read_object(path)
    require(result.get("schema") == "zkfdo-lifting-result-v1" and
            result.get("request_sha256") == item.get("request_sha256"),
            f"paired result binding differs at {order}")
    return path, result


def groups_by_revision(index: dict[str, Any]) -> dict[int, tuple[str, int]]:
    groups = runner.groups(index["requests"])
    mapping: dict[int, tuple[str, int]] = {}
    for scope, ordinal, _revision, rows in groups:
        for row in rows:
            mapping[row["queue_order"]] = (scope, ordinal)
    require(len(mapping) == index["request_count"], "index grouping incomplete")
    return mapping


def joined_effective(engine: str, output: Path, result_paths: dict[int, Path],
                     groups: dict[int, tuple[str, int]], join_root: Path) -> tuple[dict[tuple[str, str], str], list[dict[str, Any]]]:
    by_revision: dict[tuple[str, int], list[Path]] = defaultdict(list)
    for order, path in sorted(result_paths.items()):
        by_revision[groups[order]].append(path)
    engine_path = ENGINE_V1 if engine == "v1" else ENGINE_V22
    engine_sha = ENGINE_V1_SHA if engine == "v1" else ENGINE_V22_SHA
    require(digest(engine_path) == engine_sha, "fixed J engine SHA differs")
    effective: dict[tuple[str, str], str] = {}
    artifacts: list[dict[str, Any]] = []
    for (scope, ordinal), paths in sorted(by_revision.items()):
        destination = join_root / f"{engine}-{scope}-{ordinal:04d}.json"
        require(not destination.exists(), "paired join output already exists")
        relative = [str(path.relative_to(output)) for path in paths]
        command = [str(engine_path), "experiment", "lift-instances", "--result",
                   *relative, "--output", str(destination)]
        process = subprocess.run(command, cwd=output, capture_output=True, check=False)
        require(process.returncode == 0 and destination.is_file(),
                f"fixed {engine} paired lift-instances failed at {scope}/{ordinal:04d}")
        joined = read_object(destination)
        require(joined.get("schema") == "zkfdo-instance-verdicts-v1" and
                joined.get("results") == relative and joined.get("conflicts") == 0 and
                isinstance(joined.get("classes"), list),
                f"fixed {engine} paired join format differs")
        for item in joined["classes"]:
            require(isinstance(item, dict) and
                    isinstance(item.get("request_id"), str) and
                    isinstance(item.get("representative"), str) and
                    isinstance(item.get("effective"), str),
                    "paired effective class format differs")
            key = (item["request_id"], item["representative"])
            require(key not in effective, "paired class appears twice")
            effective[key] = item["effective"]
        artifacts.append({"path": str(destination), "sha256": digest(destination),
                          "request_count": len(paths)})
    return effective, artifacts


def build_summary(v1_index_sha: str, v22_index_sha: str, order_sha: str,
                  cutoff: str, join_root: Path, now: datetime | None = None) -> dict[str, Any]:
    require(cutoff == CUTOFF, "B6h fixed UTC cutoff differs")
    require(PAIR_ORDER.is_file() and not PAIR_ORDER.is_symlink() and
            digest(PAIR_ORDER) == order_sha, "B6h pair order SHA differs")
    order = read_object(PAIR_ORDER)
    require(order.get("schema_version") == 1 and
            order.get("kind") == "n6_b6h_pair_order" and
            order.get("seed") == 20261024 and
            order.get("cutoff_utc") == cutoff and
            order.get("v1_index_sha256") == v1_index_sha and
            order.get("v2_2_index_sha256") == v22_index_sha and
            isinstance(order.get("tasks"), list), "pair order lock differs")
    validate_order(order, 107)
    pair = read_object(PAIR_STATE)
    require(pair.get("kind") == "n6_b6h_pair_state" and
            pair.get("order_sha256") == order_sha and
            pair.get("cutoff_utc") == cutoff and
            pair.get("status") in {"stopped", "completed"} and
            pair.get("order_file") == str(PAIR_ORDER) and
            pair.get("task_count") == len(order["tasks"]) and
            type(pair.get("next_task_index")) is int and
            0 <= pair["next_task_index"] <= len(order["tasks"]),
            "pair execution has not reached a terminal stop")
    states: dict[str, dict[str, Any] | None] = {}
    indexes: dict[str, dict[str, Any]] = {}
    outputs: dict[str, Path] = {}
    for engine, expected_sha in (("v1", v1_index_sha), ("v2.2", v22_index_sha)):
        index_path = INDEX_OUT / f"request-index-{engine}.json"
        require(index_path.is_file() and digest(index_path) == expected_sha,
                f"{engine} index SHA differs")
        index = read_object(index_path)
        require(index.get("request_count") == 107 and
                isinstance(index.get("requests"), list) and len(index["requests"]) == 107,
                f"{engine} request index differs")
        indexes[engine] = index
        output = RUN_OUT / f"full-{engine}.noindex"
        outputs[engine] = output
        state_path = output / "state.json"
        states[engine] = read_object(state_path) if state_path.is_file() else None
    now = now or datetime.now(timezone.utc)
    finished: dict[str, set[int]] = {}
    judged: dict[str, set[int]] = {}
    for engine in ("v1", "v2.2"):
        finished[engine], judged[engine] = terminal_orders(states[engine], 107)
    fully_finished = all(len(finished[engine]) == 107 for engine in ("v1", "v2.2"))
    stop_kind = pair.get("stop_kind")
    require(fully_finished or now >= parse_utc(cutoff) or stop_kind == "space",
            "deadline gate is too early")
    require(fully_finished or stop_kind in {"time", "space"},
            "unfinished pair task lacks time/space stop")
    summaries = {engine: unfinished_breakdown(107, finished[engine], stop_kind)
                 for engine in ("v1", "v2.2")}
    paired = finished["v1"] & finished["v2.2"]
    paired_judged = judged["v1"] & judged["v2.2"]
    result_values: dict[str, dict[int, dict[str, Any]]] = {"v1": {}, "v2.2": {}}
    join_artifacts: dict[str, list[dict[str, Any]]] = {}
    effective: dict[str, dict[tuple[str, str], str]] = {}
    for engine in ("v1", "v2.2"):
        paths: dict[int, Path] = {}
        for order_number in sorted(paired_judged):
            state = states[engine]
            require(state is not None, "paired state missing")
            path, result = checked_result(state["requests"][str(order_number)],
                                          outputs[engine], order_number)
            paths[order_number] = path
            result_values[engine][order_number] = result
        effective[engine], join_artifacts[engine] = joined_effective(
            engine, outputs[engine], paths, groups_by_revision(indexes[engine]), join_root)
    comparisons: Counter[str] = Counter()
    for order_number in sorted(paired_judged):
        flags = compare_flags(
            judgement_flags(result_values["v1"][order_number], effective["v1"]),
            judgement_flags(result_values["v2.2"][order_number], effective["v2.2"]))
        for name, true in flags.items():
            comparisons[name] += true
    require(paired_judged <= paired and
            all(summaries[e]["finished"] + summaries[e]["unfinished"] == 107
                for e in ("v1", "v2.2")), "deadline denominator differs")
    return {"schema_version": 1, "kind": "n6_b6h_deadline_pair_result_gate",
            "status": "passed", "cutoff_utc": cutoff,
            "order_file": str(PAIR_ORDER), "order_sha256": order_sha,
            "pair_state": str(PAIR_STATE), "pair_state_sha256": digest(PAIR_STATE),
            "engines": summaries,
            "paired_finished_requests": len(paired),
            "paired_judged_requests": len(paired_judged),
            "paired_unjudgeable_requests": len(paired) - len(paired_judged),
            "comparisons": {name: comparisons[name] for name in
                            ("a_v1_only_l1", "b_v2_2_only_l1", "c_excluded_vs_l1")},
            "paired_joins": join_artifacts,
            "verdict_values_emitted": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-index-sha256", required=True)
    parser.add_argument("--v2-2-index-sha256", required=True)
    parser.add_argument("--order-sha256", required=True)
    parser.add_argument("--no-new-request-after", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(args.output.is_absolute() and args.output.parent == B6H_OUT and
                not args.output.exists() and not args.output.is_symlink(),
                "B6h result gate output must be a new B6h runs file")
        join_root = args.output.with_suffix(".paired-joins.noindex")
        require(not join_root.exists(), "paired join output already exists")
        join_root.mkdir(parents=True, exist_ok=False)
        summary = build_summary(args.v1_index_sha256,
                                args.v2_2_index_sha256,
                                args.order_sha256,
                                args.no_new_request_after,
                                join_root)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(summary, stream, sort_keys=True, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"status": "passed", "output": str(args.output),
                          "output_sha256": digest(args.output),
                          "engines": summary["engines"],
                          "paired_finished_requests": summary["paired_finished_requests"],
                          "paired_judged_requests": summary["paired_judged_requests"],
                          "comparisons": summary["comparisons"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"B6h result gate refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
