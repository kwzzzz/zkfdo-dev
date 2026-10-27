#!/usr/bin/env python3
"""Gate three-request A smoke states and compare actual engine judgements."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SMOKE_ROOT = Path("/Volumes/zkfdo-jcache/n6-b6g-smoke/routed")

import n6_b6g_build_a_smoke as fixture  # noqa: E402
from n6_b5_j_adapter import ENGINE_V1_SHA, ENGINE_V22_SHA  # noqa: E402
import run_n6_j1 as runner  # noqa: E402


ORIGINAL_STATE = {
    "v1": (REPO / "runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json",
           "6bfeb70743608235bbf9d7125f84c2aadf2fd8d9e95a461de8a9572411cb0e73"),
    "v2.2": (REPO / "runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/j-execute.noindex/state.json",
             "fa1da116b317d7833a60bec52826c2119a79f50dbec27616f4cbce2932a8a1f6"),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"JSON object expected: {path}")
    return value


def decision(result: dict) -> dict:
    classes = result.get("classes")
    require(isinstance(classes, list), "result classes missing")
    return {
        "component_classification": result.get("component_classification"),
        "verdict_counts": result.get("verdict_counts"),
        "class_verdicts": [
            {"pattern": item.get("pattern"), "verdict": item.get("verdict"),
             "reason": item.get("reason")}
            for item in classes
        ],
    }


def method_limits(result: dict) -> list[dict]:
    values = []
    for item in result.get("classes", []):
        synthesis = item.get("synthesis") or {}
        for stage in ("injection", "repair"):
            method = synthesis.get(stage) or {}
            if method.get("outcome") == "error":
                values.append({"stage": stage, "outcome": "error",
                               "error_kind": method.get("error_kind"),
                               "note": method.get("note")})
    return values


def gate_engine(engine: str, root: Path, item: dict) -> dict:
    index_path = Path(item["index_path"])
    index_sha = item["index_sha256"]
    require(digest(index_path) == index_sha, f"{engine} fixture index SHA differs")
    index = read(index_path)
    rows = index.get("requests")
    require(isinstance(rows, list) and len(rows) == 3 and
            tuple(row["request_sha256"] for row in rows) == fixture.EXPECTED_REQUEST_SHA,
            f"{engine} fixture rows differ")
    output = root / f"full-{engine}.noindex"
    state_path = output / "state.json"
    state = read(state_path)
    expected_engine_sha = ENGINE_V1_SHA if engine == "v1" else ENGINE_V22_SHA
    require(state.get("status") == "completed" and
            state.get("request_index_sha256") == index_sha and
            state.get("engine_sha256") == expected_engine_sha and
            state.get("cache_root") == str(root / "cache" / f"full-{engine}") and
            isinstance(state.get("completed_at"), str) and
            isinstance(state.get("requests"), dict) and
            set(state["requests"]) == {"0", "1", "2"},
            f"{engine} smoke state incomplete or unbound")
    original_state_path, original_state_sha = ORIGINAL_STATE[engine]
    require(digest(original_state_path) == original_state_sha,
            f"{engine} original A state SHA differs")
    original_state = read(original_state_path)
    original_by_sha = {row["request_sha256"]: row
                       for row in original_state["requests"].values()}
    comparison = []
    result_paths = []
    for new_order, row in enumerate(rows):
        record = state["requests"][str(new_order)]
        original = original_by_sha[row["request_sha256"]]
        require(record.get("status") == "completed" and
                record.get("request_sha256") == row["request_sha256"] and
                record.get("queue_order") == new_order and
                record.get("exit_code") == 0 and
                type(record.get("wall_seconds")) in (int, float) and
                record["wall_seconds"] > 0 and
                type(record.get("attempt")) is int and
                record["attempt"] > 0,
                f"{engine} request {new_order} incomplete")
        result_path = Path(record["result_path"])
        require(result_path.is_file() and not result_path.is_symlink() and
                result_path.resolve().is_relative_to(output.resolve()) and
                digest(result_path) == record["result_sha256"],
                f"{engine} request {new_order} result path/SHA differs")
        result_paths.append(result_path)
        current = read(result_path)
        require(current.get("request_sha256") == row["request_sha256"] and
                current.get("candidate_sha256") == row["candidate_sha256"] and
                current.get("preparation", {}).get("status") == "ok",
                f"{engine} request {new_order} result identity/preparation differs")
        old_path = Path(original["result_path"])
        require(original["status"] == "completed" and
                digest(old_path) == original["result_sha256"],
                f"{engine} original A result SHA differs")
        old = read(old_path)
        current_decision, old_decision = decision(current), decision(old)
        comparison.append({
            "new_queue_order": new_order,
            "original_queue_order": fixture.ORDERS[new_order],
            "request_sha256": row["request_sha256"],
            "status": record["status"],
            "attempt": record["attempt"],
            "wall_seconds": record["wall_seconds"],
            "original_wall_seconds": original["wall_seconds"],
            "new_result_path": str(result_path),
            "original_result_path": str(old_path),
            "new_result_sha256": record["result_sha256"],
            "original_result_sha256": original["result_sha256"],
            "same_decision": current_decision == old_decision,
            "new_decision": current_decision,
            "original_decision": old_decision,
            "new_method_limits": method_limits(current),
            "original_method_limits": method_limits(old),
        })
    revisions = state.get("revisions")
    require(isinstance(revisions, dict) and set(revisions) == {"main/0001"},
            f"{engine} revision join coverage differs")
    revision = revisions["main/0001"]
    instance_path = Path(revision.get("instances_path", ""))
    require(revision.get("status") == "joined" and
            revision.get("result_count") == 3 and
            instance_path.is_file() and not instance_path.is_symlink() and
            instance_path.resolve().is_relative_to(output.resolve()) and
            digest(instance_path) == revision.get("instances_sha256"),
            f"{engine} instance join missing or differs")
    instance = read(instance_path)
    require(instance.get("schema") == "zkfdo-instance-verdicts-v1" and
            instance.get("results") == [str(path.relative_to(output))
                                        for path in result_paths] and
            instance.get("conflicts") == 0,
            f"{engine} instance join verdict structure differs")
    require(all(row["same_decision"] for row in comparison),
            f"{engine} A smoke judgements differ from frozen A")
    return {"status": "passed", "index_sha256": index_sha,
            "state_sha256": digest(state_path),
            "instance_sha256": digest(instance_path), "requests": comparison}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        root = args.smoke_root
        require(root == SMOKE_ROOT and args.output.is_absolute() and
                args.output.parent == root and not args.output.exists(),
                "A smoke gate output must be new and under smoke root")
        manifest_path = root / "fixtures/fixture-manifest.json"
        manifest = read(manifest_path)
        require(manifest.get("schema") == "n6-b6g-a-smoke-fixtures-v1" and
                manifest.get("original_queue_orders") == list(fixture.ORDERS),
                "A smoke fixture manifest invalid")
        summary = {"schema": "n6-b6g-a-smoke-gate-v1", "status": "passed",
                   "fixture_manifest_sha256": digest(manifest_path),
                   "engines": {}}
        for engine in ("v2.2", "v1"):
            summary["engines"][engine] = gate_engine(
                engine, root, manifest["engines"][engine])
        interruptions = {}
        for engine in ("v2.2", "v1"):
            path = root / f"interrupt-resume-{engine}.json"
            if not path.is_file():
                continue
            record = read(path)
            requests = summary["engines"][engine]["requests"]
            require(record.get("schema") == "n6-b6g-a-smoke-interruption-v1" and
                    record.get("status") == "passed" and record.get("engine") == engine and
                    record.get("first_result_sha256_before") ==
                    record.get("first_result_sha256_after") ==
                    requests[0]["new_result_sha256"] and
                    record.get("first_attempt_after") == 1 and
                    record.get("second_attempt_after", 0) >= 2 and
                    record.get("second_attempt_after") == requests[1]["attempt"],
                    f"{engine} interruption evidence differs")
            interruptions[engine] = {"path": str(path), "sha256": digest(path)}
        require(bool(interruptions), "A smoke interruption/restart evidence missing")
        summary["interruptions"] = interruptions
        with args.output.open("x") as stream:
            json.dump(summary, stream, sort_keys=True, indent=2, ensure_ascii=False)
            stream.write("\n")
        print(json.dumps({"status": "passed", "engines": ["v2.2", "v1"],
                          "output": str(args.output)}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"A smoke gate refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
