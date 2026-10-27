#!/usr/bin/env python3
"""Recheck B6d source closures using the B6e original-duplicate E2 rule.

Only request path fields and Circom source are read for B.  The A final summary
is projected onto preparation status and reason for the one duplicate pair.
No B candidate, witness, result, or J workspace file is opened.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any

import n6_b6d_closure_equivalence as b6d


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_B_AUDIT = ROOT / "runs/n6-b6d-2026-10-20.noindex/b-closure-equivalence-v1.json"
DEFAULT_A_AUDIT = ROOT / "runs/n6-b6d-2026-10-20.noindex/a-closure-audit-v2.json"
DEFAULT_A_SUMMARY = ROOT / "runs/n6-j1-2026-10-09.noindex/j-summary-final.json"
DEFAULT_OUTPUT = ROOT / "runs/n6-b6e-2026-10-20.noindex/e2-equivalence-v2.json"
OLD_MAIN_COUNT_FAILURE = "main template file count is not one in both closures"


def digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def classify_b_pair(old: dict[str, Any], main_files: list[dict[str, str]]) -> dict[str, Any]:
    """Treat a preexisting main duplicate as equivalent only with exact bytes."""
    original_count = old.get("original_main_template_file_count")
    staged_count = old.get("staged_main_template_file_count")
    duplicate = isinstance(original_count, int) and original_count > 1
    reasons: list[str] = []
    if old.get("e1_status") != "pass":
        reasons.append("E1 closure or source-byte mapping failed")
    if not isinstance(original_count, int) or original_count < 1 or (
            original_count != staged_count):
        reasons.append("main declaration count differs or is zero")
    if old.get("original_duplicate_template_names") != old.get(
            "staged_duplicate_template_names"):
        reasons.append("duplicate template counts differ")
    if duplicate:
        if old.get("failures") != [OLD_MAIN_COUNT_FAILURE]:
            reasons.append("old E2 has a failure beyond original main duplication")
        if old.get("original_duplicate_template_names", {}).get(
                old.get("main_template")) != original_count:
            reasons.append("main duplication absent from declaration inventory")
        if len(main_files) != original_count:
            reasons.append("main declaration mapping count differs")
        if len({entry["original"] for entry in main_files}) != len(main_files) or (
                len({entry["staged"] for entry in main_files}) != len(main_files)):
            reasons.append("main declaration mapping is not one-to-one")
        if any(entry["original_sha256"] != entry["staged_sha256"]
               for entry in main_files):
            reasons.append("main declaration source bytes differ")
    elif old.get("e2_status") != "pass" or old.get("failures"):
        reasons.append("old E2 failed without an original main duplication")
    return {
        "pair_id": old["pair_id"],
        "revision_id": old["revision_id"],
        "queue_orders": old["queue_orders"],
        "request_count": len(old["queue_orders"]),
        "status": "pass" if not reasons else "fail",
        "original_duplicate": duplicate,
        "main_template": old.get("main_template"),
        "original_main_template_file_count": original_count,
        "staged_main_template_file_count": staged_count,
        "original_duplicate_template_names": old.get(
            "original_duplicate_template_names", {}),
        "main_declaration_files": main_files,
        "reasons": reasons,
    }


def duplicate_main_files(
        old: dict[str, Any], pair: dict[str, Any], original_request: dict[str, Any],
        staged_request: dict[str, Any], binary: Path) -> list[dict[str, str]]:
    """Use the fixed engine closure and parser to bind duplicate file bytes."""
    answers = b6d.fixed_closures([original_request, staged_request], binary)
    require(all(answer["error"] is None for answer in answers),
            f"closure failed for {old['pair_id']}")
    cache: dict[str, list[str]] = {}
    original_names = b6d.declarations(answers[0]["union"], cache)
    staged_names = b6d.declarations(answers[1]["union"], cache)
    main = old["main_template"]
    originals = original_names.get(main, [])
    staged = set(staged_names.get(main, []))
    require(len(originals) == old["original_main_template_file_count"],
            f"original main count drift for {old['pair_id']}")
    require(len(staged) == old["staged_main_template_file_count"],
            f"staged main count drift for {old['pair_id']}")
    mapped: list[dict[str, str]] = []
    for source in originals:
        target = str(b6d.mapped_path(Path(source), pair))
        require(target in staged, f"main declaration mapping differs for {old['pair_id']}")
        mapped.append({"original": source, "staged": target,
                       "original_sha256": b6d.sha256_file(Path(source)),
                       "staged_sha256": b6d.sha256_file(Path(target))})
    require({entry["staged"] for entry in mapped} == staged,
            f"main declaration mapping incomplete for {old['pair_id']}")
    return mapped


def inspect_b(old_report: dict[str, Any], manifest: dict[str, Any],
              original_index: dict[str, Any], binary: Path) -> dict[str, Any]:
    old = old_report["b"]
    pairs_by_id = {pair["pair_id"]: pair for pair in manifest["pairs"]}
    queue = {row["queue_order"]: row for row in original_index["requests"]}
    records: list[dict[str, Any]] = []
    for item in old["pairs"]:
        pair = pairs_by_id[item["pair_id"]]
        main_files: list[dict[str, str]] = []
        if item["original_main_template_file_count"] > 1:
            first = queue[item["queue_orders"][0]]
            original_request = b6d.source_request(Path(first["request"]))
            staged_request = {
                "source_root": pair["source_root"],
                "component_wrapper": pair["wrapper"],
                "entrypoint": pair["entrypoint"],
                "library_paths": pair["library_paths"],
            }
            main_files = duplicate_main_files(item, pair, original_request,
                                              staged_request, binary)
        records.append(classify_b_pair(item, main_files))
    revision_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        counts = revision_counts[record["revision_id"]]
        counts["pairs"] += 1
        counts["requests"] += record["request_count"]
        counts[record["status"]] += 1
        if record["original_duplicate"]:
            counts["original_duplicate_pairs"] += 1
            counts["original_duplicate_requests"] += record["request_count"]
    return {
        "status": "pass" if all(row["status"] == "pass" for row in records) else "fail",
        "request_count": old["request_count"],
        "pair_count": old["pair_count"],
        "original_duplicate_pair_count": sum(row["original_duplicate"] for row in records),
        "original_duplicate_request_count": sum(
            row["request_count"] for row in records if row["original_duplicate"]),
        "revisions": {name: dict(sorted(counts.items())) for name, counts
                      in sorted(revision_counts.items())},
        "pairs": records,
    }


def inspect_a(old_report: dict[str, Any], index: dict[str, Any],
              summary: dict[str, Any]) -> dict[str, Any]:
    old = old_report["a"]
    summary_rows = {row["request_sha256"]: row for row in summary["candidates"]}
    require(len(summary_rows) == len(summary["candidates"]) == old["request_count"],
            "A final summary request keys are incomplete")
    pairs: dict[str, dict[str, Any]] = {}
    for pair in old["pairs"]:
        duplicate = pair.get("main_template_file_count", 0) > 1
        status = pair["status"]
        require(status in {"ok", "premarked_main_template_not_unique"},
                f"unexpected A baseline E2 status: {status}")
        require(duplicate == (status == "premarked_main_template_not_unique"),
                f"A original duplicate status inconsistent: {pair['pair_id']}")
        pairs[pair["pair_id"]] = {
            "pair_id": pair["pair_id"],
            "revisions": pair["revisions"],
            "status": "pass",
            "original_duplicate": duplicate,
            "main_template": pair.get("main_template"),
            "main_template_file_count": pair.get("main_template_file_count"),
            "main_template_files": pair.get("main_template_files", []),
            "duplicate_template_names": pair.get("duplicate_template_names", {}),
            "engine_invoked_request_count": pair["engine_invoked_request_count"],
            "affected_request_count": 0,
            "affected_preparation_outcomes": {},
        }
    outcomes: dict[str, Counter[str]] = defaultdict(Counter)
    for row in index["requests"]:
        source = b6d.source_request(Path(row["request"]))
        key = b6d.request_key(source)
        pair_id = hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]
        require(pair_id in pairs, f"A pair missing from recheck: {pair_id}")
        if not pairs[pair_id]["original_duplicate"]:
            continue
        actual = summary_rows.get(row["request_sha256"])
        require(actual is not None and actual["revision_id"] == row["revision_id"],
                f"A final summary row missing: {row['request_sha256']}")
        require(actual["request"] == row["request"],
                f"A final summary request path differs: {pair_id}")
        pair_row = pairs[pair_id]
        pair_row["affected_request_count"] += 1
        outcomes[pair_id][f"status:{actual['status']}"] += 1
        reason = actual.get("preparation_failure")
        if reason is not None:
            outcomes[pair_id][f"preparation_failure:{reason}"] += 1
        if actual.get("result_path") is not None:
            outcomes[pair_id]["engine_result_count"] += 1
    for pair_id, counts in outcomes.items():
        pairs[pair_id]["affected_preparation_outcomes"] = dict(sorted(counts.items()))
    revision_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for pair in pairs.values():
        for revision in pair["revisions"]:
            counts = revision_counts[revision]
            counts["pairs"] += 1
            counts[pair["status"]] += 1
            if pair["original_duplicate"]:
                counts["original_duplicate_pairs"] += 1
                counts["original_duplicate_requests"] += pair["affected_request_count"]
    for revision, original in old["revisions"].items():
        counts = revision_counts[revision]
        counts["requests"] = original["requests"]
        counts["engine_invoked"] = original.get("engine_invoked", 0)
        counts["premarked"] = original.get("premarked", 0)
    return {
        "status": "pass",
        "request_count": old["request_count"],
        "revision_count": old["revision_count"],
        "unique_pair_count": old["unique_pair_count"],
        "original_duplicate_pair_count": sum(
            pair["original_duplicate"] for pair in pairs.values()),
        "original_duplicate_request_count": sum(
            pair["affected_request_count"] for pair in pairs.values()
            if pair["original_duplicate"]),
        "revisions": {name: dict(sorted(counts.items())) for name, counts
                      in sorted(revision_counts.items())},
        "pairs": list(pairs.values()),
    }


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b6d-b-audit", type=Path, default=DEFAULT_B_AUDIT)
    parser.add_argument("--b6d-a-audit", type=Path, default=DEFAULT_A_AUDIT)
    parser.add_argument("--a-summary", type=Path, default=DEFAULT_A_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    require(not args.output.exists(), f"new output already exists: {args.output}")
    b_old = b6d.read_json(args.b6d_b_audit)
    a_old = b6d.read_json(args.b6d_a_audit)
    b_index_path = Path(b_old["original_b_index"])
    manifest_path = Path(b_old["staging_manifest"])
    a_index_path = Path(a_old["a_index"])
    for path, expected in (
            (b_index_path, b_old["original_b_index_sha256"]),
            (manifest_path, b_old["staging_manifest_sha256"]),
            (a_index_path, a_old["a_index_sha256"])):
        require(b6d.sha256_file(path) == expected, f"input SHA-256 changed: {path}")
    a_summary = b6d.read_json(args.a_summary)
    require(a_summary["source"]["request_index_sha256"] == a_old["a_index_sha256"],
            "A final summary does not bind the audited index")
    binary = b6d.helper_binary()
    require(b6d.sha256_file(binary) == b_old["helper_binary_sha256"] ==
            a_old["helper_binary_sha256"], "fixed closure helper SHA-256 changed")
    fresh_b = b6d.inspect_b(b_index_path, manifest_path, binary)
    fresh_a = b6d.inspect_a(a_index_path, binary)
    require(fresh_b == b_old["b"], "fresh B6d B closure/source audit differs")
    require(fresh_a == a_old["a"], "fresh B6d A closure/source audit differs")
    report = {
        "schema_version": 2,
        "kind": "n6_b6e_e2_original_duplicate_equivalence",
        "status": "pass",
        "fixed_engine_commit": b6d.FIXED_ENGINE_COMMIT,
        "fixed_closure_helper_sha256": b6d.sha256_file(binary),
        "b6d_b_audit": str(args.b6d_b_audit.resolve()),
        "b6d_b_audit_sha256": b6d.sha256_file(args.b6d_b_audit),
        "b6d_a_audit": str(args.b6d_a_audit.resolve()),
        "b6d_a_audit_sha256": b6d.sha256_file(args.b6d_a_audit),
        "a_final_summary": str(args.a_summary.resolve()),
        "a_final_summary_sha256": b6d.sha256_file(args.a_summary),
        "b_original_index_sha256": b_old["original_b_index_sha256"],
        "b_unit_manifest_sha256": b_old["staging_manifest_sha256"],
        "a_index_sha256": a_old["a_index_sha256"],
        "fresh_b6d_b_audit_identical": True,
        "fresh_b6d_a_audit_identical": True,
        "criterion": "An original main duplicate passes only when original/staged "
                     "declaration counts, canonical mapped files, and file SHA-256 "
                     "match one-to-one; any new or changed duplicate fails.",
        "b": inspect_b(b_old, b6d.read_json(manifest_path),
                       b6d.read_json(b_index_path), binary),
        "a": inspect_a(a_old, b6d.read_json(a_index_path), a_summary),
    }
    report["status"] = "pass" if report["b"]["status"] == report["a"]["status"] == "pass" else "fail"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "status": report["status"],
                      "b_pairs": report["b"]["pair_count"],
                      "b_original_duplicate_requests": report["b"]["original_duplicate_request_count"],
                      "a_revisions": report["a"]["revision_count"],
                      "a_original_duplicate_requests": report["a"]["original_duplicate_request_count"]},
                     sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(cli())
