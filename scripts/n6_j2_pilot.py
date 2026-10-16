#!/usr/bin/env python3
"""Select and measure the six N6 J pilot-v2 requests in a fresh output directory."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Any

import run_n6_j1 as runner


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = ROOT / "runs/n6-j1-2026-10-09.noindex/request-index.json"
DEFAULT_BASE_INDEX = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
FIXED = [
    ("aq-036-", "W"),
    ("aq-036-", "S"),
    ("inference-original", "S"),
    ("aq-035-", "S"),
    ("zkemail-fpmul-vulnerable", "S"),
]


def revision_matches(identifier: str, wanted: str) -> bool:
    return identifier.startswith(wanted) if wanted.startswith("aq-") else identifier == wanted


def select_requests(index: dict[str, Any], base_index: dict[str, Any]) -> list[dict[str, Any]]:
    # Within each requested revision/method choose the first callable request by
    # queue_order. The sixth revision is the largest callable one outside FIXED;
    # revision id breaks equal-constraint ties.
    base_revisions = base_index.get("revisions", {})
    rows = [row for row in index["requests"] if row["scope"] == "main" and
            row["preparation_failure"] is None and
            base_revisions.get(row["revision_id"], {}).get("status") == "passed"]
    selected: list[dict[str, Any]] = []
    selected_orders: set[int] = set()
    for wanted, method in FIXED:
        revisions = {row["revision_id"] for row in rows
                     if revision_matches(row["revision_id"], wanted)}
        runner.require(len(revisions) == 1, f"pilot revision ambiguous/missing: {wanted}")
        revision = next(iter(revisions))
        candidates = [row for row in rows if row["revision_id"] == revision
                      and row["method"] == method]
        runner.require(bool(candidates), f"pilot callable request missing: {wanted} {method}")
        row = min(candidates, key=lambda item: item["queue_order"])
        runner.require(row["queue_order"] not in selected_orders, "pilot duplicate request")
        selected.append(row)
        selected_orders.add(row["queue_order"])
    fixed_revisions = {row["revision_id"] for row in selected}
    choices = sorted(
        ((identifier, value["constraints"]) for identifier, value in base_revisions.items()
         if identifier not in fixed_revisions and value.get("status") == "passed"
         and isinstance(value.get("constraints"), int)
         and any(row["revision_id"] == identifier and row["method"] == "S" for row in rows)),
        key=lambda pair: (-pair[1], pair[0]))
    runner.require(bool(choices), "pilot largest callable S revision missing")
    identifier, _constraints = choices[0]
    candidates = [row for row in rows if row["revision_id"] == identifier
                  and row["method"] == "S"]
    row = min(candidates, key=lambda item: item["queue_order"])
    runner.require(row["queue_order"] not in selected_orders, "pilot duplicate request")
    selected.append(row)
    runner.require(len(selected) == 6, "pilot selection count is not six")
    return selected


def load_inputs(index_path: Path, index_sha256: str, base_index_path: Path,
                base_index_sha256: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    index = runner.validate_index(index_path, index_sha256)
    runner.checked_sha(base_index_path, base_index_sha256, "J base input index")
    base = json.loads(base_index_path.read_text())
    runner.require(base.get("schema") == "n6-j1-base-inputs-v1" and
                   isinstance(base.get("revisions"), dict),
                   "invalid J base input index")
    selected = select_requests(index, base)
    return index, base, selected


def check_selected_request(row: dict[str, Any], base: dict[str, Any]) -> None:
    runner.require(row["preparation_failure"] is None,
                   f"pilot preparation failure: {row['revision_id']}")
    selected_base = base["revisions"].get(row["revision_id"])
    runner.require(isinstance(selected_base, dict) and selected_base.get("status") == "passed",
                   f"pilot base input not passed: {row['revision_id']}")
    runner.checked_sha(Path(selected_base["base_input_path"]),
                       selected_base["base_input_sha256"], "pilot base input")
    request_path = Path(row["request"])
    runner.checked_sha(request_path, row["request_sha256"], "pilot request")
    request = json.loads(request_path.read_text())
    runner.checked_request_sources(row, request, row["queue_order"])
    runner.require(request["base_input"] == selected_base["base_input_path"] and
                   request["candidate"]["path"] == row["candidate_path"],
                   f"pilot input/candidate binding mismatch: {request_path}")


def tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for directory, subdirs, files in os.walk(path, followlinks=False):
        current = Path(directory)
        for name in subdirs + files:
            item = current / name
            if item.is_symlink():
                raise runner.RunnerError(f"pilot output contains symlink: {item}")
            if item.is_file():
                total += item.stat().st_size
    return total


def rss_from_wait4(usage: resource.struct_rusage) -> int:
    # Darwin reports bytes; Linux reports KiB.
    return int(usage.ru_maxrss) * (1 if sys.platform == "darwin" else 1024)


def run_with_rusage(command: list[str], stdout_path: Path,
                    stderr_path: Path) -> tuple[int, float, int]:
    started = time.monotonic()
    with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        _pid, wait_status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(wait_status)
    return process.returncode, time.monotonic() - started, rss_from_wait4(usage)


def probe_time_l() -> dict[str, Any]:
    """Probe the instrument on /usr/bin/true, without touching any J request."""
    try:
        process = subprocess.run([str(runner.TIME_BIN), "-l", "/usr/bin/true"],
                                 capture_output=True, text=True, check=False)
    except OSError as error:
        return {"measurement_method": "wait4", "exit_code": None,
                "max_rss_bytes": None, "time_probe_failure": str(error)}
    match = runner.RSS_RE.search(process.stderr)
    passed = process.returncode == 0 and match is not None
    return {"measurement_method": "time-l" if passed else "wait4",
            "exit_code": process.returncode,
            "max_rss_bytes": int(match.group(1)) if match else None,
            "time_probe_failure": None if passed else process.stderr.strip() or
            "time -l returned no maximum resident set size"}


def run_one(row: dict[str, Any], output_dir: Path, cache: Path,
            store: Path, measurement_method: str) -> dict[str, Any]:
    """Run one J request exactly once with the preselected measurement method."""
    runner.require(measurement_method in {"time-l", "wait4"},
                   "unknown pilot measurement method")
    output_dir.mkdir(parents=True, exist_ok=False)
    common = [str(runner.ENGINE), "experiment", "lift", "--request", row["request"],
              "--cache", str(cache), "--circom-bin", str(runner.CIRCOM),
              "--instance-store", str(store)]
    target = output_dir / "lift"
    command = common + ["--output", str(target)]
    stdout_path = output_dir / "lift.stdout.log"
    stderr_path = output_dir / "lift.stderr.log"
    if measurement_method == "time-l":
        started = time.monotonic()
        with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
            process = subprocess.run([str(runner.TIME_BIN), "-l", *command],
                                     stdout=stdout, stderr=stderr, check=False)
        exit_code = process.returncode
        wall = time.monotonic() - started
        rss = runner.max_rss_bytes(stderr_path)
    else:
        exit_code, wall, rss = run_with_rusage(command, stdout_path, stderr_path)
    return {"measurement_method": measurement_method, "exit_code": exit_code,
            "wall_seconds": wall, "max_rss_bytes": rss,
            "result_path": str(target / "result.json") if (target / "result.json").is_file() else None,
            "stdout_path": str(stdout_path), "stderr_path": str(stderr_path)}


def join_pilot_revision(result_paths: list[Path], output: Path,
                        instance_path: Path) -> dict[str, Any]:
    """Join only this pilot revision's completed results with the locked engine."""
    runner.require(bool(result_paths) and not instance_path.exists(),
                   "invalid pilot instance join target")
    runner.checked_sha(runner.ENGINE, runner.ENGINE_SHA256, "locked J engine")
    relative = [str(path.relative_to(output)) for path in result_paths]
    command = [str(runner.ENGINE), "experiment", "lift-instances",
               "--result", *relative, "--output", str(instance_path)]
    stdout_path = instance_path.with_suffix(".stdout.log")
    stderr_path = instance_path.with_suffix(".stderr.log")
    started = time.monotonic()
    with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
        process = subprocess.run(command, cwd=output, stdout=stdout, stderr=stderr,
                                 check=False)
    metrics = {"exit_code": process.returncode,
               "wall_seconds": time.monotonic() - started,
               "stdout_path": str(stdout_path), "stderr_path": str(stderr_path)}
    runner.require(process.returncode == 0 and instance_path.is_file(),
                   f"pilot lift-instances failed: {instance_path}")
    joined = json.loads(instance_path.read_text())
    runner.require(joined.get("schema") == "zkfdo-instance-verdicts-v1" and
                   joined.get("results") == relative and
                   joined.get("conflicts") == 0,
                   f"pilot joined results mismatch: {instance_path}")
    return metrics


def run_pilot(index_path: Path, index_sha256: str, base_index_path: Path,
              base_index_sha256: str, cache_root: Path, output: Path) -> dict[str, Any]:
    _index, base, selected = load_inputs(index_path, index_sha256,
                                         base_index_path, base_index_sha256)
    runner.require(cache_root.is_absolute() and cache_root.parent.is_dir() and
                   not cache_root.exists(),
                   "--cache-root must be a new absolute directory under an existing parent")
    cache_root = cache_root.resolve()
    output = output.resolve()
    runner.require(not output.exists(), f"pilot output already exists: {output}")
    runner.require(not (output == cache_root or output.is_relative_to(cache_root) or
                       cache_root.is_relative_to(output)),
                   "pilot cache and output must be separate directories")
    output.mkdir(parents=True)
    cache_root.mkdir()
    probe = probe_time_l()
    revisions: dict[str, dict[str, Any]] = {}
    record: dict[str, Any] = {
        "schema_version": 1, "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "request_index": str(index_path), "request_index_sha256": index_sha256,
        "base_index": str(base_index_path), "base_index_sha256": base_index_sha256,
        "engine_sha256": runner.ENGINE_SHA256, "circom_sha256": runner.CIRCOM_SHA256,
        "cache_root": str(cache_root), "output": str(output),
        "measurement_method": probe["measurement_method"],
        "time_probe": probe,
        "time_probe_failure": probe["time_probe_failure"],
        "selected_queue_orders": [row["queue_order"] for row in selected],
        "selection": [{"pilot_order": order, "queue_order": row["queue_order"],
                       "revision_id": row["revision_id"], "seed": row["seed"],
                       "method": row["method"],
                       "role": "fixed" if order < 5 else "largest_callable_revision",
                       "constraints": base.get("revisions", {}).get(row["revision_id"], {}).get(
                           "constraints")}
                      for order, row in enumerate(selected)],
        "requests": [], "revisions": revisions,
    }
    record_path = output / "pilot.json"
    state_path = output / "state.json"
    state: dict[str, Any] = {
        "schema_version": 1, "kind": "n6_j1_pilot_state",
        "status": "running", "request_index_sha256": index_sha256,
        "engine_sha256": runner.ENGINE_SHA256,
        "circom_sha256": runner.CIRCOM_SHA256,
        "cache_root": str(cache_root), "requests": {}, "revisions": {},
    }
    runner.atomic_json(record_path, record)
    runner.atomic_json(state_path, state)

    def ensure_revision(revision_id: str) -> dict[str, Any]:
        if revision_id not in revisions:
            ordinal = len(revisions) + 1
            cache = cache_root / f"{ordinal:02d}"
            store = output / "revisions" / f"{ordinal:02d}" / "store"
            revisions[revision_id] = {"revision_ordinal": ordinal,
                                      "cache_path": str(cache),
                                      "instance_store": str(store),
                                      "max_cache_bytes": 0}
            state["revisions"][f"main/{ordinal:04d}"] = {
                "scope": "main", "revision_ordinal": ordinal,
                "revision_id": revision_id, "status": "running",
                "cache_path": str(cache), "instance_store": str(store),
                "instances_path": None, "instances_sha256": None,
                "result_count": 0,
            }
            runner.atomic_json(state_path, state)
        return revisions[revision_id]

    had_unavailable = False
    for pilot_order, row in enumerate(selected):
        try:
            revision_id = row["revision_id"]
            revision = ensure_revision(revision_id)
            base_row = base.get("revisions", {}).get(row["revision_id"])
            unavailable = row["preparation_failure"] or (
                "base_input_unavailable" if not isinstance(base_row, dict) or
                base_row.get("status") != "passed" else None)
            if unavailable is not None:
                had_unavailable = True
                record["requests"].append({
                    "pilot_order": pilot_order, "queue_order": row["queue_order"],
                    "revision_id": row["revision_id"], "seed": row["seed"],
                    "method": row["method"], "request": row["request"],
                    "request_sha256": row["request_sha256"],
                    "candidate_sha256": row["candidate_sha256"],
                    "status": "preparation_failure",
                    "preparation_failure": unavailable,
                    "result_path": None, "exit_code": None,
                    "wall_seconds": None, "max_rss_bytes": None,
                })
                state["requests"][str(row["queue_order"])] = {
                    "status": "preparation_failure", "queue_order": row["queue_order"],
                    "scope": "main", "revision_id": revision_id,
                    "request": row["request"],
                    "request_sha256": row["request_sha256"],
                    "preparation_failure": unavailable,
                    "result_path": None, "result_sha256": None,
                    "exit_code": None, "wall_seconds": None,
                    "max_rss_bytes": None,
                }
                runner.atomic_json(record_path, record)
                runner.atomic_json(state_path, state)
                continue
            check_selected_request(row, base)
            free = runner.check_disk(output, cache_root)
            cache = Path(revision["cache_path"])
            if not cache.exists():
                cache.mkdir()
            store = Path(revision["instance_store"])
            before = {"output_bytes": tree_bytes(output),
                      "cache_bytes": tree_bytes(cache),
                      "output_free_bytes": free["output_free_bytes"],
                      "cache_free_bytes": free["cache_free_bytes"]}
            run_dir = output / "requests" / f"{pilot_order:02d}-{row['queue_order']:06d}"
            metrics = run_one(row, run_dir, cache, store,
                              record["measurement_method"])
            after = {"output_bytes": tree_bytes(output),
                     "cache_bytes": tree_bytes(cache),
                     "output_free_bytes": runner.disk_free(output),
                     "cache_free_bytes": runner.disk_free(cache_root)}
            revision["max_cache_bytes"] = max(revision["max_cache_bytes"],
                                               after["cache_bytes"])
            event = {"pilot_order": pilot_order, "queue_order": row["queue_order"],
                     "revision_id": revision_id, "seed": row["seed"],
                     "method": row["method"], "request": row["request"],
                     "request_sha256": row["request_sha256"],
                     "candidate_sha256": row["candidate_sha256"],
                     "before": before, "after": after,
                     "delta": {key: after[key] - before[key] for key in before},
                     "disk_increase_bytes": {
                         "output": max(0, before["output_free_bytes"] - after["output_free_bytes"]),
                         "cache": max(0, before["cache_free_bytes"] - after["cache_free_bytes"]),
                     },
                     **metrics}
            result_path = Path(metrics["result_path"]) if metrics["result_path"] else None
            if result_path is not None:
                result = json.loads(result_path.read_text())
                runner.require(result.get("request_sha256") == row["request_sha256"] and
                               result.get("candidate_sha256") == row["candidate_sha256"],
                               f"pilot result SHA mismatch: {result_path}")
                event["result_sha256"] = runner.sha256(result_path)
                event["preparation"] = result.get("preparation")
                event["sites_found"] = result.get("sites_found")
                event["verdict_counts"] = result.get("verdict_counts")
                event["self_verdicts"] = sorted({entry["verdict"] for entry in
                                                result.get("classes", [])})
            record["requests"].append(event)
            state["requests"][str(row["queue_order"])] = {
                "status": "completed" if metrics["exit_code"] == 0 and result_path else "failed",
                "queue_order": row["queue_order"], "scope": "main",
                "revision_id": revision_id, "request": row["request"],
                "request_sha256": row["request_sha256"],
                "preparation_failure": None,
                "result_path": str(result_path) if result_path else None,
                "result_sha256": event.get("result_sha256"),
                "exit_code": metrics["exit_code"],
                "wall_seconds": metrics["wall_seconds"],
                "max_rss_bytes": metrics["max_rss_bytes"],
            }
            runner.atomic_json(record_path, record)
            runner.atomic_json(state_path, state)
            runner.require(metrics["exit_code"] == 0 and result_path is not None,
                           f"pilot engine failed at queue order {row['queue_order']}")
            runner.require(metrics["max_rss_bytes"] is not None,
                           f"pilot measurement missing at queue order {row['queue_order']}")
            preparation = result.get("preparation")
            runner.require(isinstance(preparation, dict) and preparation.get("status") == "ok",
                           f"pilot preparation failure at queue order {row['queue_order']}")
            runner.check_disk(output, cache_root)
        except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError) as error:
            record["status"] = "stopped"
            record["stop_reason"] = str(error)
            record["stop_pilot_order"] = pilot_order
            state["status"] = "stopped"
            state["stop_reason"] = str(error)
            runner.atomic_json(record_path, record)
            runner.atomic_json(state_path, state)
            raise
    try:
        for revision_id, revision in revisions.items():
            ordinal = revision["revision_ordinal"]
            revision_state = state["revisions"][f"main/{ordinal:04d}"]
            result_paths = [Path(state["requests"][str(row["queue_order"])]["result_path"])
                            for row in selected if row["revision_id"] == revision_id
                            and state["requests"][str(row["queue_order"])]["status"] == "completed"]
            if not result_paths:
                revision_state["status"] = "no_results"
                revision_state["result_count"] = 0
                revision["join_status"] = "no_results"
                runner.atomic_json(state_path, state)
                runner.atomic_json(record_path, record)
                continue
            for path in result_paths:
                runner.require(path.is_file() and path.is_relative_to(output),
                               f"pilot result missing/outside output: {path}")
                matching = [entry for entry in state["requests"].values()
                            if entry.get("result_path") == str(path)]
                runner.require(len(matching) == 1, f"pilot result state missing: {path}")
                runner.checked_sha(path, matching[0]["result_sha256"], "pilot result")
            instance_path = output / "revisions" / f"{ordinal:02d}" / "instances.json"
            instance_path.parent.mkdir(parents=True, exist_ok=True)
            metrics = join_pilot_revision(result_paths, output, instance_path)
            instance_sha = runner.sha256(instance_path)
            revision_state.update({"status": "joined", "instances_path": str(instance_path),
                                   "instances_sha256": instance_sha,
                                   "result_count": len(result_paths)})
            revision.update({"join_status": "joined", "instances_path": str(instance_path),
                             "instances_sha256": instance_sha, "join_metrics": metrics})
            runner.atomic_json(state_path, state)
            runner.atomic_json(record_path, record)
    except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError) as error:
        record["status"] = "stopped"
        record["stop_reason"] = str(error)
        record["stop_phase"] = "lift-instances"
        state["status"] = "join_failed"
        state["stop_reason"] = str(error)
        runner.atomic_json(record_path, record)
        runner.atomic_json(state_path, state)
        raise
    record["status"] = "completed_with_unavailable" if had_unavailable else "passed"
    state["status"] = record["status"]
    record["completed_at"] = datetime.now(timezone.utc).isoformat()
    runner.atomic_json(record_path, record)
    runner.atomic_json(state_path, state)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--base-index", type=Path, default=DEFAULT_BASE_INDEX)
    parser.add_argument("--base-index-sha256", required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--action", choices=("validate-only", "execute"), default="validate-only")
    args = parser.parse_args(argv)
    try:
        if args.action == "validate-only":
            _index, base, selected = load_inputs(args.index.resolve(), args.index_sha256,
                                                  args.base_index.resolve(),
                                                  args.base_index_sha256)
            skipped = []
            for row in selected:
                base_row = base["revisions"].get(row["revision_id"])
                if row["preparation_failure"] is not None or not isinstance(base_row, dict) or \
                        base_row.get("status") != "passed":
                    skipped.append({"queue_order": row["queue_order"],
                                    "preparation_failure": row["preparation_failure"] or
                                    "base_input_unavailable"})
                    continue
                check_selected_request(row, base)
            runner.require(args.cache_root.is_absolute() and args.cache_root.parent.is_dir() and
                           not args.cache_root.exists(),
                           "--cache-root must be a new absolute directory under an existing parent")
            print(json.dumps({"status": "valid_with_preparation_failures" if skipped else "valid",
                              "selected_queue_orders":
                              [row["queue_order"] for row in selected],
                              "skipped": skipped}, sort_keys=True))
        else:
            record = run_pilot(args.index.resolve(), args.index_sha256,
                               args.base_index.resolve(), args.base_index_sha256,
                               args.cache_root, args.output)
            print(json.dumps({"status": record["status"],
                              "pilot_json": str(args.output.resolve() / "pilot.json")},
                             sort_keys=True))
        return 0
    except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError) as error:
        print(f"J pilot failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
