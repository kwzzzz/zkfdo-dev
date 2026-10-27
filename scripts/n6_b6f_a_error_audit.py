#!/usr/bin/env python3
"""Audit A results against every B6f pilot format rule.

Only state-listed result files are opened. This audit never selects or emits
candidate, witness, or final verdict fields from a result.
"""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import n6_b6f_format_pilot as checker


ROOT = Path(__file__).resolve().parents[1]
V1_ENGINE = "e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed"
V22_ENGINE = "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835"
ARMS = (
    ("v1_original", "runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json",
     "6bfeb70743608235bbf9d7125f84c2aadf2fd8d9e95a461de8a9572411cb0e73",
     "runs/n6-j1-2026-10-09.noindex/request-index.json",
     "35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c",
     V1_ENGINE, 2926, 765),
    ("v2_2_original", "runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/j-execute.noindex/state.json",
     "fa1da116b317d7833a60bec52826c2119a79f50dbec27616f4cbce2932a8a1f6",
     "runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/request-index-v2.json",
     "d1102d837e5d78116cb44a2b67f5a9796f57bbc2a6733d712205eb1d528ceed8",
     V22_ENGINE, 2926, 765),
    ("v2_2_strict", "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/strict-j/state.json",
     "e62a28db4f994995b3e063dd48daf86cee4ec63cccbbefdc1bb80f5e593072bb",
     "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/prepared/strict-request-index.json",
     "c8f8f1aa9b12a953b78685bafda49d7afe02edf2b0c2c27016dd2d71eee0f362",
     V22_ENGINE, 122, 122),
    ("v2_2_constructed", "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/constructed-j/state.json",
     "5625b73a5e52b5a9802447089a4faf7e283c40df811f0e9f4cbd9b0fd7c0f55f",
     "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/prepared/constructed-request-index.json",
     "ebf7fa598fc1ddb4fd9f8e42e7376ab5e99429ccc4ff110c3b83df72151c5fe5",
     V22_ENGINE, 122, 122),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def checked_json(path: Path, expected_sha: str) -> dict[str, Any]:
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == expected_sha, f"SHA-256 mismatch: {path}")
    value = json.loads(raw)
    require(isinstance(value, dict), f"JSON object missing: {path}")
    return value


def audit_arm(name: str, state_rel: str, state_sha: str, index_rel: str,
              index_sha: str, engine_sha: str, indexed: int, completed: int) -> dict[str, Any]:
    state_path = ROOT / state_rel
    state = checked_json(state_path, state_sha)
    index = checked_json(ROOT / index_rel, index_sha)
    require(state.get("status") == "completed", f"A state incomplete: {name}")
    require(state.get("engine_sha256") == engine_sha, f"A engine differs: {name}")
    require(state.get("request_index_sha256") == index_sha, f"A index binding differs: {name}")
    index_rows = index.get("requests")
    require(isinstance(index_rows, list) and len(index_rows) == indexed,
            f"A index row count differs: {name}")
    by_request_sha = {row["request_sha256"]: row for row in index_rows}
    require(len(by_request_sha) == indexed and all(
        isinstance(row, dict) and isinstance(row.get("candidate_sha256"), str)
        for row in index_rows), f"A index candidate binding malformed: {name}")
    requests = state.get("requests")
    require(isinstance(requests, dict) and len(requests) == indexed,
            f"A request count differs: {name}")
    run_root = state_path.parent.resolve()
    results = 0
    records = 0
    errors: Counter[tuple[str, str | None, str]] = Counter()
    rejected: Counter[tuple[str, str | None, str]] = Counter()
    format_rejections: Counter[str] = Counter()
    seen_paths: set[Path] = set()
    checked_by_revision: dict[tuple[str, str], list[tuple[int, str]]] = {}
    checker.runner.ENGINE_SHA256 = engine_sha
    for row in requests.values():
        require(isinstance(row, dict), f"malformed A state request: {name}")
        if row.get("status") != "completed":
            continue
        raw_path = row.get("result_path")
        result_sha = row.get("result_sha256")
        require(isinstance(raw_path, str) and isinstance(result_sha, str),
                f"missing A result binding: {name}")
        result_path = Path(raw_path)
        if not result_path.is_absolute():
            result_path = ROOT / result_path
        result_path = result_path.resolve()
        require(result_path.is_relative_to(run_root) and result_path.name == "result.json",
                f"A result outside listed run: {name}")
        require(result_path not in seen_paths, f"duplicate A result path: {name}")
        seen_paths.add(result_path)
        result = checked_json(result_path, result_sha)
        index_row = by_request_sha.get(row.get("request_sha256"))
        require(index_row is not None and index_row.get("request") == row.get("request"),
                f"A state/index request binding invalid: {name}")
        require(result.get("schema") == "zkfdo-lifting-result-v1" and
                result.get("request_sha256") == row.get("request_sha256") and
                isinstance(result.get("preparation"), dict) and
                result["preparation"].get("status") == "ok", f"A result binding invalid: {name}")
        classes = result.get("classes")
        require(isinstance(classes, list), f"A classes malformed: {name}")
        results += 1
        scope = row.get("scope")
        revision_id = row.get("revision_id")
        queue_order = row.get("queue_order")
        require(isinstance(scope, str) and isinstance(revision_id, str) and
                type(queue_order) is int, f"A revision binding malformed: {name}")
        checked_by_revision.setdefault((scope, revision_id), []).append(
            (queue_order, str(result_path.relative_to(run_root))))
        try:
            checker.check_result_shape(result_path, {
                "request_sha256": row["request_sha256"],
                "candidate_sha256": index_row["candidate_sha256"],
            })
        except (RuntimeError, ValueError, TypeError) as error:
            format_rejections[str(error)] += 1
        for class_row in classes:
            require(isinstance(class_row, dict), f"A class malformed: {name}")
            synthesis = class_row.get("synthesis")
            if synthesis is None:
                continue
            require(isinstance(synthesis, dict), f"A synthesis malformed: {name}")
            for stage in ("repair", "injection"):
                record = synthesis.get(stage)
                if record is None:
                    continue
                require(isinstance(record, dict), f"A method record malformed: {name}")
                records += 1
                if record.get("outcome") != "error":
                    continue
                kind = record.get("error_kind")
                note = record.get("note")
                require((kind is None or isinstance(kind, str)) and isinstance(note, str),
                        f"A error metadata malformed: {name}")
                key = (stage, kind, note)
                errors[key] += 1
                try:
                    disposition = checker.classify_method_error(stage, record, engine_sha)
                    require(disposition == "unsupported", f"unexpected disposition: {name}")
                except (RuntimeError, ValueError, TypeError):
                    rejected[key] += 1
    require(results == completed, f"A completed result count differs: {name}")
    revision_state = state.get("revisions")
    require(isinstance(revision_state, dict), f"A revision state malformed: {name}")
    joins_checked = 0
    join_rejections: Counter[str] = Counter()
    for revision in revision_state.values():
        require(isinstance(revision, dict), f"A revision row malformed: {name}")
        path_text = revision.get("instances_path")
        if path_text is None:
            continue
        join_sha = revision.get("instances_sha256")
        require(isinstance(path_text, str) and isinstance(join_sha, str),
                f"A join binding missing: {name}")
        join_path = Path(path_text)
        if not join_path.is_absolute():
            join_path = ROOT / join_path
        join_path = join_path.resolve()
        require(join_path.is_relative_to(run_root) and join_path.name == "instances.json",
                f"A join outside listed run: {name}")
        checked_json(join_path, join_sha)
        key = (revision.get("scope"), revision.get("revision_id"))
        listed = [relative for _, relative in sorted(checked_by_revision.get(key, []))]
        require(len(listed) == revision.get("result_count"),
                f"A join result count differs: {name}")
        try:
            checker.original.check_instances_shape(join_path, listed)
        except (RuntimeError, ValueError, TypeError) as error:
            join_rejections[str(error)] += 1
        joins_checked += 1
    return {
        "state_path": state_rel,
        "state_sha256": state_sha,
        "request_index_path": index_rel,
        "request_index_sha256": index_sha,
        "engine_sha256": engine_sha,
        "indexed_requests": indexed,
        "completed_results": results,
        "method_records": records,
        "method_error_records": sum(errors.values()),
        "accepted_method_error_records": sum(errors.values()) - sum(rejected.values()),
        "rejected_method_error_records": sum(rejected.values()),
        "full_format_rejected_results": sum(format_rejections.values()),
        "full_format_rejection_reasons": dict(sorted(format_rejections.items())),
        "join_envelopes_checked": joins_checked,
        "join_envelope_rejections": sum(join_rejections.values()),
        "join_envelope_rejection_reasons": dict(sorted(join_rejections.items())),
        "error_kinds_and_notes": [
            {"stage": stage, "error_kind": kind, "note": note, "count": count,
             "rejected_count": rejected[(stage, kind, note)]}
            for (stage, kind, note), count in sorted(
                errors.items(), key=lambda item: (item[0][0], item[0][1] or "", item[0][2]))
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.is_relative_to(ROOT / "runs/n6-b6f-2026-10-20.noindex"),
            "audit output must use the fresh B6f runs folder")
    require(not output.exists(), "audit output already exists")
    arms = {name: audit_arm(name, path, state_sha, index_path, index_sha,
                            engine_sha, indexed, completed)
            for name, path, state_sha, index_path, index_sha, engine_sha, indexed, completed in ARMS}
    report = {"schema": "n6-b6f-a-full-format-audit-v2",
              "status": "pass" if all(row["rejected_method_error_records"] == 0 and
                                      row["full_format_rejected_results"] == 0 and
                                      row["join_envelope_rejections"] == 0
                                      for row in arms.values()) else "fail",
              "scope": "completed A result format and joins; only repair/injection error metadata is emitted",
              "checker_sha256": sha256(Path(checker.__file__).read_bytes()).hexdigest(),
              "arms": arms,
              "totals": {"indexed_requests": sum(row["indexed_requests"] for row in arms.values()),
                         "completed_results": sum(row["completed_results"] for row in arms.values()),
                         "method_error_records": sum(row["method_error_records"] for row in arms.values()),
                         "rejected_method_error_records": sum(row["rejected_method_error_records"]
                                                              for row in arms.values()),
                         "full_format_rejected_results": sum(row["full_format_rejected_results"]
                                                             for row in arms.values()),
                         "join_envelopes_checked": sum(row["join_envelopes_checked"]
                                                       for row in arms.values()),
                         "join_envelope_rejections": sum(row["join_envelope_rejections"]
                                                         for row in arms.values())}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "totals": report["totals"]}, sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
