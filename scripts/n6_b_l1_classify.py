#!/usr/bin/env python3
"""Classify hash-pinned L1 results without running J or reading witness files.

Supply --index/--index-sha256 and either --state/--state-sha256 (runner state
with result_path/result_sha256 entries) or repeated --result PATH SHA256.
Only those result files are opened; index references to requests, candidates,
inputs, logs, sources and caches are never followed. Run separately per engine.

Normal mode requires --entrypoint-table/--entrypoint-table-sha256 with the
frozen B5 table digest below. --a-calibration restricts every opened file to
the A calibration directory and defaults to harness without a table; an
explicit, hash-pinned A table with the same schema is also accepted.

L1 follows n6_b6h_result_gate.py:135. Instance sharing is reproduced from
lifting/instances.rs:70-170 over ALL supplied results, separately per scope
and revision. A subset of results can have fewer L1s than a complete run.
Conflicting reachable/excluded instance evidence is refused.

Fields follow lifting/mod.rs:2221-2232 literally. public_inputs_equal compares
two witnesses at the same evaluated input, not against original base inputs;
the honest comparator may retain other injected/repaired hints (:2007-2023).
These limitations are flagged on each emitted class. Missing fields remain
unknown, including predicate-only L1s. Dimensions are never combined across
classes. stdout contains only request IDs, revision IDs, classification fields
and counts. Errors never include parsed data or underlying exception text.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
A_ROOT = ROOT / "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex"
TABLE_SHA256 = "126745ca432de49f4ee7bdf901d8f4eb81082b96eb11b4b623c29f61057bd660"
REACHABLE = "assumption_violation_reachable"
EXCLUDED = "assumption_excluded_in_context"
REAL = "real_vulnerability_candidate"
DEFECT = "constraint_defect_confirmed"
VERDICTS = {
    "entrypoint_violation", "assumption_input_reachable",
    "compatible_no_top_violation_observed", "excluded_in_context",
    "unknown", "preparation_failure",
}


class Refused(Exception):
    """A fixed, value-free diagnostic."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Refused(message)


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def digest_arg(value: Any) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value)
            is not None, "missing or invalid SHA-256")
    return value.lower()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in obj, "duplicate JSON key")
        obj[key] = value
    return obj


def reject_constant(_value: str) -> None:
    raise Refused("nonfinite JSON number")


def checked_json(path: Path, expected: str, calibration: bool) -> dict[str, Any]:
    expected = digest_arg(expected)
    if calibration:
        # Check lexically before resolving links, then check the resolved target.
        require(Path(os.path.abspath(path)).is_relative_to(A_ROOT),
                "A mode input outside calibration directory")
        require(path.resolve().is_relative_to(A_ROOT.resolve()),
                "A mode input resolves outside calibration directory")
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, "SHA-256 mismatch")
    obj = json.loads(data, object_pairs_hook=unique_object,
                     parse_constant=reject_constant)
    require(isinstance(obj, dict), "JSON object required")
    return obj


def main_key(value: Any) -> str | None:
    # Metadata only: never resolve, stat or open a main/source path.
    return os.path.normpath(value) if nonempty(value) else None


def load_table(args: argparse.Namespace) -> dict[tuple[str, str], str] | None:
    if args.entrypoint_table is None:
        require(args.a_calibration and args.entrypoint_table_sha256 is None,
                "entrypoint table and SHA-256 required")
        return None
    expected = digest_arg(args.entrypoint_table_sha256)
    require(args.a_calibration or expected == TABLE_SHA256,
            "entrypoint table SHA-256 differs from frozen B5 digest")
    obj = checked_json(args.entrypoint_table, expected, args.a_calibration)
    require(obj.get("schema_version") == 1 and isinstance(obj.get("rows"), list),
            "entrypoint table schema invalid")
    table: dict[tuple[str, str], str] = {}
    for row in obj["rows"]:
        require(isinstance(row, dict) and nonempty(row.get("revision_id")) and
                main_key(row.get("main_file")) is not None and
                row.get("classification") in ("deployed", "harness"),
                "entrypoint table row invalid")
        key = (row["revision_id"], main_key(row["main_file"]))
        require(key not in table, "duplicate entrypoint table key")
        table[key] = row["classification"]
    return table


def index_rows(index: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = index.get("requests")
    require(isinstance(rows, list) and type(index.get("request_count")) is int
            and index["request_count"] == len(rows), "request index count invalid")
    found: dict[int, dict[str, Any]] = {}
    hashes: set[str] = set()
    for row in rows:
        require(isinstance(row, dict), "request index row invalid")
        order = row.get("queue_order")
        require(type(order) is int and order >= 0 and order not in found and
                nonempty(row.get("revision_id")) and nonempty(row.get("scope")),
                "request index identity invalid")
        sha = digest_arg(row.get("request_sha256"))
        require(sha not in hashes, "duplicate indexed request SHA-256")
        hashes.add(sha)
        found[order] = row
    return found


def references(args: argparse.Namespace, rows: dict[int, dict[str, Any]],
               index: dict[str, Any]) -> list[tuple[Path, str, int | None]]:
    if args.state is None:
        require(args.state_sha256 is None, "state SHA-256 without state")
        return [(Path(path), digest_arg(sha), None) for path, sha in args.result]
    state = checked_json(args.state, args.state_sha256, args.a_calibration)
    require(state.get("request_index_sha256") == args.index_sha256.lower(),
            "state/index SHA-256 binding mismatch")
    if "engine_sha256" in index:
        require(state.get("engine_sha256") == index["engine_sha256"],
                "state/index engine binding mismatch")
    events = state.get("requests")
    require(isinstance(events, dict), "state requests invalid")
    refs = []
    for key, event in events.items():
        require(isinstance(event, dict), "state request invalid")
        order = event.get("queue_order")
        require(type(order) is int and order in rows and str(order) == key,
                "state request order invalid")
        row = rows[order]
        require(all(event.get(field) == row.get(field) for field in
                    ("request_sha256", "revision_id", "scope")),
                "state request/index identity mismatch")
        require(nonempty(event.get("status")), "state request status missing")
        # Failed/preparation/unfinished entries are counted as unclassified,
        # never turned into negatives and never followed to other artifacts.
        if event["status"] != "completed":
            continue
        require(nonempty(event.get("result_path")), "completed result path missing")
        refs.append((Path(event["result_path"]),
                     digest_arg(event.get("result_sha256")), order))
    return refs


def project_class(item: Any, ordinal: int) -> dict[str, Any]:
    require(isinstance(item, dict) and item.get("verdict") in VERDICTS and
            nonempty(item.get("representative")), "class identity/verdict invalid")
    public_input = item.get("public_inputs_equal")
    output_count = item.get("outputs_differing")
    require(public_input is None or type(public_input) is bool,
            "public input comparison must be boolean or null")
    require(output_count is None or (type(output_count) is int and output_count >= 0),
            "public output difference count must be nonnegative integer or null")
    predicates = item.get("predicates", [])
    require(isinstance(predicates, list), "predicate list invalid")
    targets = []
    for predicate in predicates:
        require(isinstance(predicate, dict) and nonempty(predicate.get("instance"))
                and predicate.get("verdict") in (REACHABLE, EXCLUDED, "unknown"),
                "predicate identity/verdict invalid")
        targets.append((predicate["instance"], predicate["verdict"]))
    return {"ordinal": ordinal, "representative": item["representative"],
            "own": item["verdict"], "public_input": public_input,
            "output_count": output_count, "predicates": targets}


def load_results(args: argparse.Namespace, rows: dict[int, dict[str, Any]],
                 refs: list[tuple[Path, str, int | None]]) -> list[dict[str, Any]]:
    by_sha = {digest_arg(row["request_sha256"]): order for order, row in rows.items()}
    found = []
    orders: set[int] = set()
    identities: set[str] = set()
    for path, sha, expected_order in refs:
        obj = checked_json(path, sha, args.a_calibration)
        require(obj.get("schema") == "zkfdo-lifting-result-v1" and
                nonempty(obj.get("request_id")), "result schema/identity invalid")
        order = by_sha.get(digest_arg(obj.get("request_sha256")))
        require(order is not None and (expected_order is None or order == expected_order),
                "result/index request binding mismatch")
        row = rows[order]
        require(order not in orders and obj["request_id"] not in identities,
                "duplicate result request")
        if "request_id" in row:
            require(row["request_id"] == obj["request_id"], "request ID mismatch")
        if "candidate_sha256" in row:
            require(obj.get("candidate_sha256") == row["candidate_sha256"],
                    "result/index candidate SHA-256 binding mismatch")
        orders.add(order)
        identities.add(obj["request_id"])
        prep = obj.get("preparation")
        require(isinstance(prep, dict) and prep.get("status") in
                ("ok", "unknown", "preparation_failure"), "preparation status invalid")
        classes = obj.get("classes")
        require(isinstance(classes, list), "result classes invalid")
        if prep["status"] != "ok":
            require(not classes, "unsuccessful preparation has classes")
            continue
        projected = [project_class(item, i) for i, item in enumerate(classes)]
        require(len({item["representative"] for item in projected}) == len(projected),
                "duplicate class representative")
        entry = obj.get("entrypoint")
        require(isinstance(entry, dict), "entrypoint summary missing")
        entry_key = tuple(digest_arg(entry.get(field)) for field in
                          ("r1cs_sha256", "sym_sha256", "o0_r1cs_sha256"))
        found.append({"order": order, "id": obj["request_id"], "row": row,
                      "entry_key": entry_key, "classes": projected})
    return sorted(found, key=lambda result: result["order"])


def instance_key(result: dict[str, Any], instance: str) -> tuple[Any, ...]:
    row = result["row"]
    return (row["scope"], row["revision_id"], *result["entry_key"], instance)


def joined_reachable(results: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    evidence: dict[tuple[Any, ...], set[str]] = {}
    for result in results:
        for item in result["classes"]:
            for instance, verdict in item["predicates"]:
                evidence.setdefault(instance_key(result, instance), set()).add(verdict)
    require(all(not {REACHABLE, EXCLUDED}.issubset(flags) for flags in evidence.values()),
            "conflicting instance evidence")
    return {key for key, flags in evidence.items() if REACHABLE in flags}


def entrypoint_class(row: dict[str, Any], table: dict | None) -> tuple[str, str]:
    if table is None:
        return "harness", "a_harness_fallback"
    # B6g/h preserve original_entrypoint when staging moves the actual main.
    main = next((main_key(row.get(field)) for field in
                 ("original_entrypoint", "main_file", "main", "entrypoint")
                 if main_key(row.get(field)) is not None), None)
    if main is None:
        return "harness", "missing_main"
    key = (row["revision_id"], main)
    return (table[key], "table_match") if key in table else ("harness", "not_in_table")


def classify(results: list[dict[str, Any]], table: dict | None,
             indexed: int) -> dict[str, Any]:
    reached = joined_reachable(results)
    requests = []
    dimensions = {
        "public_input": Counter(dict.fromkeys(
            ("private_reach", "public_input_change_reach", "unknown"), 0)),
        "public_output": Counter(dict.fromkeys(("output_change", "internal_only", "unknown"), 0)),
        "entrypoint": Counter(dict.fromkeys(("deployed", "harness"), 0)),
        "classification": Counter(dict.fromkeys((REAL, DEFECT), 0)),
    }
    request_counts = Counter(dict.fromkeys((REAL, DEFECT), 0))
    for result in results:
        entrypoint, lookup = entrypoint_class(result["row"], table)
        classes = []
        for item in result["classes"]:
            own_l1 = item["own"] == "entrypoint_violation"
            shared_l1 = any(instance_key(result, target) in reached
                            for target, _verdict in item["predicates"])
            if not (own_l1 or shared_l1):
                continue
            public_input = ("unknown" if item["public_input"] is None else
                            "private_reach" if item["public_input"] else
                            "public_input_change_reach")
            public_output = ("unknown" if item["output_count"] is None else
                             "output_change" if item["output_count"] > 0 else "internal_only")
            real = (public_input == "private_reach" and public_output == "output_change"
                    and entrypoint == "deployed")
            cls = {"class_index": item["ordinal"], "public_input": public_input,
                   "public_output": public_output, "entrypoint": entrypoint,
                   "entrypoint_lookup": lookup, "classification": REAL if real else DEFECT,
                   "real_vulnerability_candidate": real,
                   "l1_basis": "entrypoint_violation" if own_l1 else "joined_predicate_reach",
                   "comparison_evidence": (
                       "comparison_missing" if (item["public_input"] is None or
                                                item["output_count"] is None) else
                       "class_tcct_pair" if own_l1 else
                       "predicate_reach_without_matched_output_evidence"),
                   "public_input_comparison": "evaluated_input_not_original_base",
                   "public_output_comparison": "engine_honest_or_repaired_comparator"}
            classes.append(cls)
            for dimension, counts in dimensions.items():
                counts[cls[dimension]] += 1
        if classes:
            real = any(cls["real_vulnerability_candidate"] for cls in classes)
            classification = REAL if real else DEFECT
            request_counts[classification] += 1
            requests.append({"request_id": result["id"],
                             "revision_id": result["row"]["revision_id"],
                             "classes": classes, "classification": classification,
                             "real_vulnerability_candidate": real})
    return {"requests": requests, "counts": {
        "indexed_requests": indexed, "classified_result_requests": len(results),
        "unclassified_requests": indexed - len(results),
        "non_l1_requests": len(results) - len(requests), "l1_requests": len(requests),
        "l1_classes": sum(dimensions["classification"].values()),
        "request_classification": dict(request_counts),
        "class_dimensions": {key: dict(value) for key, value in dimensions.items()},
    }}


class SafeParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.exit(2, "n6_b_l1_classify: invalid arguments; use --help\n")


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--index-sha256", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--state", type=Path)
    source.add_argument("--result", nargs=2, action="append", metavar=("PATH", "SHA256"))
    parser.add_argument("--state-sha256")
    parser.add_argument("--entrypoint-table", type=Path)
    parser.add_argument("--entrypoint-table-sha256")
    parser.add_argument("--a-calibration", action="store_true")
    args = parser.parse_args(argv)
    try:
        table = load_table(args)
        index = checked_json(args.index, args.index_sha256, args.a_calibration)
        rows = index_rows(index)
        refs = references(args, rows, index)
        results = load_results(args, rows, refs)
        report = classify(results, table, len(rows))
    except Refused as error:
        print(f"n6_b_l1_classify: refused: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print("n6_b_l1_classify: refused: unreadable or malformed input", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
