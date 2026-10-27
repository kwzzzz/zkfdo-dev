#!/usr/bin/env python3
"""Gate the final three-request A pair smoke and deadline accounting."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

import n6_b6h_build_a_smoke as fixture
import n6_b6h_gate_a_smoke as a_gate
import n6_b6h_pair_runner as pair
import n6_b6h_result_gate as deadline_gate


ROOT = Path("/Volumes/zkfdo-jcache/n6-b6h-smoke-final")
FIXTURES = ROOT / "fixtures-97-102-115"
ORDER = ROOT / "pair-order-v1.json"
PAIR_STATE = ROOT / "pair-state-v1.json"
CUTOFF = "2026-10-29T14:59:00Z"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    result = json.loads(path.read_text())
    require(isinstance(result, dict), f"JSON object expected: {path}")
    return result


def original_effective(engine: str, original_state: dict) -> dict[tuple[str, str], str]:
    effective: dict[tuple[str, str], str] = {}
    revisions = {"inference-c9221e8d", "inference-c79f42ee"}
    for revision in original_state["revisions"].values():
        if revision.get("revision_id") not in revisions:
            continue
        instance_path = Path(revision["instances_path"])
        require(digest(instance_path) == revision["instances_sha256"],
                f"{engine} original A instances SHA differs")
        joined = read(instance_path)
        for item in joined.get("classes", []):
            key = (item.get("request_id"), item.get("representative"))
            require(all(isinstance(x, str) for x in key),
                    f"{engine} original instance class malformed")
            effective[key] = item.get("effective")
    return effective


def checked_evidence(root: Path, order_sha: str, states: dict[str, dict]) -> dict:
    named = {
        "cutoff": (root / "cutoff-smoke.json", "n6-b6h-a-pair-cutoff-smoke-v1"),
        "space": (root / "space-smoke.json", "n6-b6h-a-pair-space-smoke-v1"),
        "interruption": (root / "pair-interrupt-resume.json", "n6-b6h-a-pair-interruption-v1"),
        "idempotence": (root / "pair-idempotence.json", "n6-b6h-a-pair-idempotence-v1"),
    }
    records = {}
    for name, (path, schema) in named.items():
        value = read(path)
        require(value.get("schema") == schema and value.get("status") == "passed",
                f"A pair {name} evidence differs")
        records[name] = {"path": str(path), "sha256": digest(path)}
    cutoff, space = read(named["cutoff"][0]), read(named["space"][0])
    interrupted, repeat = read(named["interruption"][0]), read(named["idempotence"][0])
    require(cutoff.get("clock_override") == "after-cutoff" and
            cutoff.get("returncode") == 3 and
            cutoff.get("stop_kind") == "time" and
            cutoff.get("next_task_index") == 0 and
            cutoff.get("v1_output_absent") is True and
            space.get("returncode") == 3 and
            space.get("stop_kind") == "space" and
            space.get("next_task_index") == 0 and
            space.get("v1_requests_started") == 0 and
            space.get("stress_observed_peak_bytes") == 400 * 1024**3,
            "A pair time/space stops did not precede the first task")
    require(interrupted.get("order_sha256") == order_sha and
            interrupted.get("first_process_returncode") == -15 and
            interrupted.get("restart_returncode") == 0 and
            interrupted.get("v1_first_result_sha256_before_after") ==
            states["v1"]["requests"]["0"]["result_sha256"] and
            interrupted.get("v2_2_prefix_result_sha256_before_after") ==
            states["v2.2"]["requests"]["0"]["result_sha256"] and
            interrupted.get("v1_first_attempt_after") == 1 and
            interrupted.get("v2_2_second_attempt_after") ==
            states["v2.2"]["requests"]["1"]["attempt"] >= 2 and
            repeat.get("returncode") == 0 and
            repeat.get("request_snapshots_unchanged") is True and
            repeat.get("pair_state_sha256") == digest(PAIR_STATE),
            "A pair interruption/restart/skip evidence differs")
    return records


def build_summary(args: argparse.Namespace, join_root: Path) -> dict:
    require(args.no_new_request_after == CUTOFF and
            args.output.parent == ROOT and
            args.output.is_absolute() and not args.output.exists(),
            "A pair gate cutoff/output differs")
    manifest_path = FIXTURES / "fixture-manifest.json"
    manifest = read(manifest_path)
    require(manifest.get("original_queue_orders") == list(fixture.ORDERS),
            "A pair fixture orders differ")
    expected = {"v1": args.v1_index_sha256,
                "v2.2": args.v2_2_index_sha256}
    for engine in ("v1", "v2.2"):
        item = manifest["engines"][engine]
        require(item["index_sha256"] == expected[engine] and
                digest(Path(item["index_path"])) == expected[engine],
                f"{engine} A fixture SHA differs")
    require(digest(ORDER) == args.order_sha256, "A pair order SHA differs")
    order = read(ORDER)
    deadline_gate.validate_order(order, 3)
    pair.REQUEST_COUNT = 3
    ids = {engine: pair.index_ids(Path(manifest["engines"][engine]["index_path"]),
                                  expected[engine])
           for engine in ("v1", "v2.2")}
    pair.validate_order(order, ids["v1"], ids["v2.2"],
                        expected["v1"], expected["v2.2"])
    require(order["completed_prefix_orders"] == [0] and
            order["shuffled_remaining_orders"] == [1, 2],
            "A pair prefix/shuffle differs")
    pair_state = read(PAIR_STATE)
    require(pair_state.get("kind") == "n6_b6h_pair_state" and
            pair_state.get("status") == "completed" and
            pair_state.get("stop_kind") is None and
            pair_state.get("order_sha256") == args.order_sha256 and
            pair_state.get("cutoff_utc") == CUTOFF and
            pair_state.get("next_task_index") == 5 and
            pair_state.get("task_count") == 5 and
            pair_state.get("unfinished_by_engine") == {"v1": 0, "v2.2": 0},
            "A pair state did not finish the pinned tasks")

    engine_gates = {}
    states = {}
    indexes = {}
    finished = {}
    judged = {}
    outputs = {}
    for engine in ("v1", "v2.2"):
        item = manifest["engines"][engine]
        engine_gates[engine] = a_gate.gate_engine(engine, ROOT, item)
        states[engine] = read(ROOT / f"full-{engine}.noindex/state.json")
        indexes[engine] = read(Path(item["index_path"]))
        outputs[engine] = ROOT / f"full-{engine}.noindex"
        finished[engine], judged[engine] = deadline_gate.terminal_orders(
            states[engine], 3)
    summaries = {engine: deadline_gate.unfinished_breakdown(
                    3, finished[engine], pair_state["stop_kind"])
                 for engine in ("v1", "v2.2")}
    paired = finished["v1"] & finished["v2.2"]
    paired_judged = judged["v1"] & judged["v2.2"]
    require(paired == paired_judged == {0, 1, 2},
            "A pair final denominator differs")

    results = {"v1": {}, "v2.2": {}}
    effective = {}
    join_artifacts = {}
    original_results = {"v1": {}, "v2.2": {}}
    original_effectives = {}
    for engine in ("v1", "v2.2"):
        paths = {}
        for order_number in sorted(paired_judged):
            path, result = deadline_gate.checked_result(
                states[engine]["requests"][str(order_number)],
                outputs[engine], order_number)
            paths[order_number] = path
            results[engine][order_number] = result
        effective[engine], join_artifacts[engine] = deadline_gate.joined_effective(
            engine, outputs[engine], paths,
            deadline_gate.groups_by_revision(indexes[engine]), join_root)
        original_path, original_sha = a_gate.ORIGINAL_STATE[engine]
        require(digest(original_path) == original_sha,
                f"{engine} original A state SHA differs")
        original_state = read(original_path)
        original_effectives[engine] = original_effective(engine, original_state)
        for new_order, old_order in enumerate(fixture.ORDERS):
            old_event = original_state["requests"][str(old_order)]
            _old_path, original_results[engine][new_order] = \
                deadline_gate.checked_result(old_event, original_path.parent,
                                             old_order)
    counts = Counter()
    original_counts = Counter()
    for order_number in sorted(paired_judged):
        flags = deadline_gate.compare_flags(
            deadline_gate.judgement_flags(results["v1"][order_number],
                                          effective["v1"]),
            deadline_gate.judgement_flags(results["v2.2"][order_number],
                                          effective["v2.2"]))
        old_flags = deadline_gate.compare_flags(
            deadline_gate.judgement_flags(original_results["v1"][order_number],
                                          original_effectives["v1"]),
            deadline_gate.judgement_flags(original_results["v2.2"][order_number],
                                          original_effectives["v2.2"]))
        for key, value in flags.items():
            counts[key] += value
        for key, value in old_flags.items():
            original_counts[key] += value
    comparison_keys = ("a_v1_only_l1", "b_v2_2_only_l1", "c_excluded_vs_l1")
    require(all(counts[key] == original_counts[key] for key in comparison_keys),
            "A pair deadline comparisons differ from original A")
    evidence = checked_evidence(ROOT, args.order_sha256, states)
    return {
        "schema_version": 1, "kind": "n6_b6h_a_pair_deadline_gate",
        "status": "passed", "cutoff_utc": CUTOFF,
        "fixture_manifest_sha256": digest(manifest_path),
        "order_file": str(ORDER), "order_sha256": args.order_sha256,
        "pair_state": str(PAIR_STATE), "pair_state_sha256": digest(PAIR_STATE),
        "engines": summaries,
        "paired_finished_requests": len(paired),
        "paired_judged_requests": len(paired_judged),
        "paired_unjudgeable_requests": len(paired) - len(paired_judged),
        "comparisons": {key: counts[key] for key in comparison_keys},
        "original_a_comparisons": {key: original_counts[key]
                                   for key in comparison_keys},
        "engine_gates": engine_gates,
        "paired_joins": join_artifacts,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-index-sha256", required=True)
    parser.add_argument("--v2-2-index-sha256", required=True)
    parser.add_argument("--order-sha256", required=True)
    parser.add_argument("--no-new-request-after", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        join_root = args.output.with_suffix(".paired-joins.noindex")
        require(not join_root.exists() and not join_root.is_symlink(),
                "A pair gate join output exists")
        join_root.mkdir(parents=True, exist_ok=False)
        summary = build_summary(args, join_root)
        with args.output.open("x") as stream:
            json.dump(summary, stream, sort_keys=True, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"status": "passed", "output": str(args.output),
                          "output_sha256": digest(args.output),
                          "engines": summary["engines"],
                          "paired_finished_requests": summary["paired_finished_requests"],
                          "paired_judged_requests": summary["paired_judged_requests"],
                          "comparisons": summary["comparisons"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"A pair deadline gate refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
