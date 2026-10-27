#!/usr/bin/env python3
"""Check both human-run B6g J states and write a value-free 107-row summary.

The gate reads request-index and state metadata. It hashes result and join
artifacts but never parses their verdict-bearing contents or candidate request
JSON. Preparation and inspection failures are counted separately. Execute
this only after miiz has run both full engines.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

import n6_b6g_j_runner as b6g
import run_n6_j1 as runner
from n6_b5_j_adapter import ENGINE_V1_SHA, ENGINE_V22_SHA


def artifact(path_text: Any, digest: Any, output: Path, label: str) -> None:
    b6g.require(isinstance(path_text, str) and isinstance(digest, str) and
                len(digest) == 64, f"{label} path/SHA missing")
    path = Path(path_text)
    b6g.require(path.is_absolute() and path.resolve().is_relative_to(output.resolve()) and
                path.is_file() and not path.is_symlink(),
                f"{label} is missing, linked, or outside its run")
    runner.checked_sha(path, digest, label)


def summarize_engine(index: dict[str, Any], state: dict[str, Any],
                     output: Path, engine: str, index_sha256: str,
                     cache_root: Path) -> dict[str, Any]:
    """Count all rows from state metadata; never parse result/instance JSON."""
    expected_engine = ENGINE_V1_SHA if engine == "v1" else ENGINE_V22_SHA
    rows = index.get("requests")
    b6g.require(isinstance(rows, list) and len(rows) == 107 and
                index.get("request_count") == 107 and
                state.get("schema_version") == 1 and
                state.get("status") == "completed" and
                state.get("request_index_sha256") == index_sha256 and
                state.get("engine_sha256") == expected_engine and
                state.get("circom_sha256") == runner.CIRCOM_SHA256 and
                state.get("format_checker_sha256") == runner.sha256(
                    b6g.ROOT / "scripts/n6_b6f_format_pilot.py") and
                state.get("cache_root") == str(cache_root) and
                isinstance(state.get("completed_at"), str) and
                isinstance(state.get("requests"), dict) and
                set(state["requests"]) == {str(i) for i in range(107)} and
                isinstance(state.get("revisions"), dict),
                f"B6g {engine} completed state/index lock differs")
    by_reason: Counter[str] = Counter()
    completed = 0
    planned = 0
    engine_preparation = 0
    inspection_failure = 0
    inspection_by_reason: Counter[str] = Counter()
    preparation_unknown = 0
    original_duplicate_ambiguous = 0
    group_result_count: Counter[str] = Counter()
    groups = runner.groups(rows)
    expected_revision_keys = {f"{scope}/{ordinal:04d}"
                              for scope, ordinal, _revision, _rows in groups}
    b6g.require(set(state["revisions"]) == expected_revision_keys,
                f"B6g {engine} revision state coverage differs")
    for scope, ordinal, revision, group_rows in groups:
        key = f"{scope}/{ordinal:04d}"
        for row in group_rows:
            order = row["queue_order"]
            item = state["requests"][str(order)]
            request_dir = output / scope / f"{ordinal:04d}" / "requests" / f"{order:06d}"
            b6g.require(isinstance(item, dict) and
                        item.get("queue_order") == order and
                        item.get("scope") == scope and
                        item.get("revision_id") == revision and
                        item.get("request") == row["request"] and
                        item.get("request_sha256") == row["request_sha256"],
                        f"B6g {engine} request identity differs at {order}")
            status = item.get("status")
            if status == "completed":
                b6g.require(row["preparation_failure"] is None and
                            item.get("preparation_failure") is None and
                            type(item.get("attempt")) is int and
                            item["attempt"] > 0 and
                            item.get("result_path") == str(
                                request_dir / f"attempt-{item['attempt']:04d}" / "result.json") and
                            item.get("exit_code") == 0 and
                            type(item.get("max_rss_bytes")) is int and
                            item["max_rss_bytes"] > 0,
                            f"B6g {engine} completed request metadata invalid at {order}")
                artifact(item.get("result_path"), item.get("result_sha256"),
                         output, f"B6g {engine} completed result {order}")
                completed += 1
                group_result_count[key] += 1
                continue
            if status == "inspection_failure":
                b6g.require(row["preparation_failure"] is None and
                            item.get("preparation_failure") is None and
                            item.get("result_path") is None and
                            item.get("result_sha256") is None and
                            item.get("preparation_artifact_path") is None and
                            item.get("preparation_artifact_sha256") is None and
                            type(item.get("attempt")) is int and
                            item["attempt"] > 0 and
                            item.get("inspection_artifact_path") == str(
                                request_dir / f"attempt-{item['attempt']:04d}" / "result.json") and
                            isinstance(item.get("inspection_failure_reason"), str) and
                            bool(item["inspection_failure_reason"]) and
                            isinstance(item.get("inspection_failure_detail"), str) and
                            bool(item["inspection_failure_detail"]) and
                            not b6g.RESOURCE_DETAIL.search(
                                item["inspection_failure_detail"]) and
                            item.get("exit_code") == 0 and
                            type(item.get("max_rss_bytes")) is int and
                            item["max_rss_bytes"] > 0,
                            f"B6g {engine} inspection failure metadata invalid at {order}")
                artifact(item.get("inspection_artifact_path"),
                         item.get("inspection_artifact_sha256"), output,
                         f"B6g {engine} inspection artifact {order}")
                inspection_failure += 1
                inspection_by_reason[item["inspection_failure_reason"]] += 1
                continue
            b6g.require(status == "preparation_failure" and
                        item.get("result_path") is None and
                        item.get("result_sha256") is None,
                        f"B6g {engine} request status invalid at {order}")
            reason = item.get("preparation_failure")
            b6g.require(isinstance(reason, str) and reason,
                        f"B6g {engine} preparation reason absent at {order}")
            if row["preparation_failure"] is not None:
                b6g.require(reason == row["preparation_failure"] ==
                            "base_input_unavailable" and
                            item.get("preparation_artifact_path") is None and
                            item.get("preparation_artifact_sha256") is None,
                            f"B6g {engine} planned failure differs at {order}")
                planned += 1
            else:
                expected_status = ("unknown" if reason in {
                    "candidate_violates_component_constraints",
                    "deviation_not_hint_assigned"} else "preparation_failure")
                b6g.require(reason in b6g.INTRINSIC_REASONS and
                            item.get("preparation_status") == expected_status and
                            type(item.get("attempt")) is int and
                            item["attempt"] > 0 and
                            item.get("preparation_artifact_path") == str(
                                request_dir / f"attempt-{item['attempt']:04d}" / "result.json") and
                            isinstance(item.get("preparation_detail"), str) and
                            item["preparation_detail"] and
                            not b6g.RESOURCE_DETAIL.search(item["preparation_detail"]) and
                            item.get("exit_code") == 0 and
                            type(item.get("max_rss_bytes")) is int and
                            item["max_rss_bytes"] > 0,
                            f"B6g {engine} engine preparation failure invalid at {order}")
                artifact(item.get("preparation_artifact_path"),
                         item.get("preparation_artifact_sha256"), output,
                         f"B6g {engine} preparation artifact {order}")
                engine_preparation += 1
                preparation_unknown += item["preparation_status"] == "unknown"
                if row["original_template_duplicate"] and reason == "template_ambiguous":
                    original_duplicate_ambiguous += 1
            by_reason[reason] += 1
        revision_state = state["revisions"][key]
        result_count = group_result_count[key]
        b6g.require(isinstance(revision_state, dict) and
                    revision_state.get("revision_id") == revision and
                    revision_state.get("result_count") == result_count,
                    f"B6g {engine} revision result count differs: {key}")
        if result_count:
            b6g.require(revision_state.get("status") == "joined",
                        f"B6g {engine} joined revision status differs: {key}")
            b6g.require(revision_state.get("instances_path") == str(
                output / scope / f"{ordinal:04d}" / "instances.json"),
                f"B6g {engine} instance join path differs: {key}")
            artifact(revision_state.get("instances_path"),
                     revision_state.get("instances_sha256"), output,
                     f"B6g {engine} instance join {key}")
        else:
            b6g.require(revision_state.get("status") == "no_results" and
                        revision_state.get("instances_path") is None and
                        revision_state.get("instances_sha256") is None,
                        f"B6g {engine} empty revision status differs: {key}")
    b6g.require(state.get("inspection_failure_count") == inspection_failure and
                inspection_failure <= 4,
                f"B6g {engine} inspection failure limit exceeded")
    b6g.require(completed + planned + engine_preparation + inspection_failure == 107,
                f"B6g {engine} denominator differs")
    return {
        "denominator": 107,
        "completed_results": completed,
        "preparation_failure_count": planned + engine_preparation,
        "planned_preparation_failure_count": planned,
        "engine_preparation_failure_count": engine_preparation,
        "preparation_failures_by_reason": dict(sorted(by_reason.items())),
        "inspection_failure_count": inspection_failure,
        "inspection_failures_by_reason": dict(sorted(inspection_by_reason.items())),
        "preparation_status_unknown_count": preparation_unknown,
        "original_duplicate_template_ambiguous_count":
            original_duplicate_ambiguous,
        "verdict_unknown_count": None,
        "verdict_values_read": False,
        "joined_revisions": sum(count > 0 for count in group_result_count.values()),
    }


def build_summary(index_shas: dict[str, str]) -> dict[str, Any]:
    b6g.verify_both_pilots()
    pilot_evidence = {
        "v2.2_recheck": b6g.PILOT_OUT / "v2-2-pilot-recheck.json",
        "v1_pilot_state": b6g.PILOT_OUT / "pilot-v1.noindex/state.json",
    }
    b6g.require(all(path.is_file() and not path.is_symlink()
                    for path in pilot_evidence.values()),
                "B6g pilot evidence is missing or linked")
    summaries: dict[str, dict[str, Any]] = {}
    inputs: dict[str, dict[str, str]] = {}
    for engine in ("v1", "v2.2"):
        index_path = b6g.OUT / f"request-index-{engine}.json"
        output = b6g.RUN_OUT / f"full-{engine}.noindex"
        state_path = output / "state.json"
        index_sha = index_shas[engine]
        runner.checked_sha(index_path, index_sha, f"B6g {engine} index")
        index = b6g.read_object(index_path)
        b6g.verify_equivalence_gate(index)
        state = b6g.read_object(state_path)
        summaries[engine] = summarize_engine(index, state, output, engine,
                                             index_sha,
                                             b6g.CACHE / f"full-{engine}")
        inputs[engine] = {"request_index": str(index_path),
                          "request_index_sha256": index_sha,
                          "run_state": str(state_path),
                          "run_state_sha256": runner.sha256(state_path)}
    return {"schema_version": 1, "kind": "n6_b6g_value_free_result_gate",
            "status": "passed", "denominator_per_engine": 107,
            "engines": summaries, "inputs": inputs,
            "equivalence_gate": str(b6g.GATE),
            "equivalence_gate_sha256": runner.sha256(b6g.GATE),
            "pilot_evidence": {
                name: {"path": str(path), "sha256": runner.sha256(path)}
                for name, path in pilot_evidence.items()},
            "verdict_values_read": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-index-sha256", required=True)
    parser.add_argument("--v2-2-index-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        b6g.require(args.output.is_absolute() and
                    args.output.parent == b6g.RUN_OUT and not args.output.exists(),
                    "B6g result gate output must be new and in B6g output")
        summary = build_summary({"v1": args.v1_index_sha256,
                                 "v2.2": args.v2_2_index_sha256})
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2,
                      sort_keys=True)
            stream.write("\n")
        print(json.dumps({"status": "passed", "output": str(args.output),
                          "output_sha256": runner.sha256(args.output),
                          "engines": summary["engines"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError) as error:
        print(f"B6g result gate refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
