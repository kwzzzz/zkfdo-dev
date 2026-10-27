#!/usr/bin/env python3
"""Prepare immutable A aq request overlays from checked constructed inputs only.

This command cannot execute J. It opens frozen request indexes/documents only
after every selected input passes checked_inputs(). Candidate references are
copied without opening candidate payloads or their inventory. Banyan artifacts
and scripts remain unchanged.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import fcntl
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runs/n6-a-remeasure-2026-10-25.noindex"
PREPARED = OUTPUT / "prepared-aq"
BASE = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
BASE_SHA = "18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508"
CIRCOM = Path("/Users/miiz/.cargo/bin/circom")
CIRCOM_SHA = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
# These are the same immutable A pins as n6_a_remeasure.py. No runner is imported.
ENGINES = {
    "v2.2": {
        "path": ROOT / "runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2",
        "sha256": "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835",
        "index": ROOT / "runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/request-index-v2.json",
        "index_sha256": "d1102d837e5d78116cb44a2b67f5a9796f57bbc2a6733d712205eb1d528ceed8",
    },
    "v1": {
        "path": ROOT / "runs/l07-2026-10-05/tools/zkfDO",
        "sha256": "e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed",
        "index": ROOT / "runs/n6-j1-2026-10-09.noindex/request-index.json",
        "index_sha256": "35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c",
    },
}
EXPECTED_COUNTS = {
    "aq-006-1680f955c185": 42,
    "aq-007-0bb83f9eab0f": 42,
    "aq-008-9c9e702d061d": 42,
    "aq-011-93343c3cd34c": 33,
    "aq-025-70328d3fd35e": 27,
    "aq-026-2bcd7ed6110f": 27,
    "aq-012-44d0df2ab46e": 24,
    "aq-016-0a7d49b1c135": 24,
    "aq-024-6f6781246415": 24,
    "aq-017-9703bbce0c43": 21,
    "aq-040-da54d3e7bc8a": 12,
    "aq-037-94fe3080fc18": 6,
    "aq-039-0ad3923f2f5b": 6,
}
SCHEMA = "n6-a-remeasure-aq-prepare-v1"
LAYER = "A_constructed_base_input_remeasurement"


class PrepareError(ValueError):
    """A binding or immutable-output check failed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PrepareError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path, expected_sha: str | None = None) -> dict[str, Any]:
    content = path.read_bytes()
    if expected_sha is not None:
        require(hashlib.sha256(content).hexdigest() == expected_sha,
                f"frozen JSON SHA differs: {path}")
    value = json.loads(content)
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def checked_sha(path: Path, expected: str, label: str) -> None:
    require(sha256(path) == expected, f"{label} SHA differs")


def canonical_revisions(revisions: list[str]) -> tuple[str, ...]:
    require(bool(revisions) and len(revisions) == len(set(revisions)),
            "provide one or more unique aq revisions")
    require(all(revision in EXPECTED_COUNTS for revision in revisions),
            "revision outside the approved 13 aq revisions")
    return tuple(revision for revision in EXPECTED_COUNTS if revision in revisions)


def owned(path: Path, *, prepared: bool = True) -> Path:
    boundary = PREPARED if prepared else OUTPUT / "inputs"
    require(OUTPUT.resolve() == OUTPUT and not OUTPUT.is_symlink(), "unsafe A output root")
    require(path.resolve() == path and path.is_relative_to(boundary) and not path.is_symlink(),
            f"path outside the permitted A output or contains a symlink: {path}")
    return path


def encode(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_fixed(path: Path, value: dict[str, Any]) -> None:
    owned(path)
    content = encode(value)
    if path.exists():
        require(path.read_text() == content, f"refuse to overwrite fixed artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def checked_inputs(revisions: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Freeze input/check hashes before any request data is opened."""
    require(tuple(canonical_revisions(list(revisions))) == revisions,
            "revision selection is not in approved order")
    official = read(BASE, BASE_SHA)
    bindings = {}
    for revision in revisions:
        path = owned(OUTPUT / "inputs" / revision / "input.json", prepared=False)
        check = owned(path.with_name("check.json"), prepared=False)
        check_sha = sha256(check)
        record = read(check, check_sha)
        expected = official["revisions"][revision]["compile"]["r1cs_sha256"]
        input_sha = sha256(path)
        require(record.get("schema") == "n6-b6-constructed-check-v1" and
                record.get("scope") == "A" and record.get("identifier") == revision and
                record.get("status") == "passed" and record.get("input_path") == str(path) and
                record.get("input_sha256") == input_sha and
                record.get("r1cs_map_sha256") == BASE_SHA and
                record.get("r1cs_sha256_match") is True and
                record.get("expected_r1cs_sha256") == expected and
                record.get("compile", {}).get("r1cs_sha256") == expected,
                f"constructed input/check binding invalid: {revision}")
        audit = record.get("child_audit", [])
        require(isinstance(audit, list) and
                all(any(isinstance(child, dict) and child.get("kind") == kind and
                        child.get("exit_code") == 0 for child in audit)
                    for kind in ("node_witness", "rust_r1cs", "snarkjs_r1cs")),
                f"honest witness/Rust/snarkjs checks missing: {revision}")
        work_end = owned(path.with_name("work-end.json"), prepared=False)
        work_end_sha = sha256(work_end)
        completion = read(work_end, work_end_sha)
        elapsed = completion.get("elapsed_work_seconds")
        require(completion.get("revision_id") == revision and
                completion.get("check_sha256") == check_sha and
                completion.get("checker_exit_code") == 0 and
                completion.get("adapter_exit_code", 0) == 0 and
                completion.get("within_work_cap", True) is True and
                isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and
                math.isfinite(elapsed) and 0 <= elapsed <= 10800,
                f"constructed input work-cap binding invalid: {revision}")
        bindings[revision] = {"path": str(path), "sha256": input_sha,
                              "check": str(check), "check_sha256": check_sha,
                              "work_end": str(work_end), "work_end_sha256": work_end_sha,
                              "r1cs_sha256": expected}
    return bindings


def frozen_index(engine: str) -> dict[str, Any]:
    pin = ENGINES[engine]
    checked_sha(pin["path"], pin["sha256"], f"frozen {engine} engine")
    checked_sha(CIRCOM, CIRCOM_SHA, "frozen circom")
    index = read(pin["index"], pin["index_sha256"])
    require(index.get("schema_version") == 1 and index.get("status") == "verified" and
            index.get("request_count") == len(index.get("requests", [])) == 2926 and
            index.get("engine") == str(pin["path"]) and
            index.get("engine_sha256") == pin["sha256"] and
            index.get("base_index") == str(BASE) and index.get("base_index_sha256") == BASE_SHA and
            index.get("circom") == str(CIRCOM) and index.get("circom_sha256") == CIRCOM_SHA,
            f"frozen {engine} index locks differ")
    return index


def selected(index: dict[str, Any], revisions: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = [row for row in index["requests"] if row["revision_id"] in revisions]
    require(Counter(row["revision_id"] for row in rows) ==
            {revision: EXPECTED_COUNTS[revision] for revision in revisions},
            "selected aq request counts differ from approved totals")
    # The approved aq counts include frozen main and mem20 requests. Their
    # original scopes are copied verbatim and verified by validate_overlays().
    require(all(row.get("scope") in {"main", "mem20"} and row.get("method") in {"W", "S"} and
                row.get("preparation_failure") == "base_input_unavailable" for row in rows),
            "selected aq scope/method/base availability differs")
    orders = [row["queue_order"] for row in rows]
    require(all(isinstance(order, int) and not isinstance(order, bool) for order in orders) and
            orders == sorted(set(orders)), "original queue order is not unique/sorted")
    return rows


def method_counts(rows: list[dict[str, Any]], revisions: tuple[str, ...]) -> dict[str, dict[str, int]]:
    counts = Counter((row["revision_id"], row["method"]) for row in rows)
    return {revision: {method: counts[revision, method] for method in ("W", "S")}
            for revision in revisions}


def prepare(revisions: tuple[str, ...]) -> dict[str, Any]:
    inputs = checked_inputs(revisions)  # This must precede every request read.
    base = read(BASE, BASE_SHA)
    for revision, binding in inputs.items():
        base["revisions"][revision].update({"status": "passed", "selected_stage": "constructed",
                                           "base_input_path": binding["path"],
                                           "base_input_sha256": binding["sha256"]})
    base["layer"] = LAYER
    base_path = PREPARED / "constructed-base-index.json"
    documents = {base_path: base}
    base_sha = hashlib.sha256(encode(base).encode()).hexdigest()
    indexes = {}
    counts = {}
    for engine, pin in ENGINES.items():
        original = frozen_index(engine)
        rows = selected(original, revisions)
        revised_rows = []
        ids = []
        for row in rows:
            request = read(Path(row["request"]), row["request_sha256"])
            old_base = request.get("base_input")
            require(old_base is None or isinstance(old_base, str) and not Path(old_base).is_file(),
                    "original unavailable base input unexpectedly exists")
            require(isinstance(request.get("id"), str) and bool(request["id"]),
                    "original request ID missing")
            ids.append(request["id"])
            overlay = copy.deepcopy(request)
            overlay["base_input"] = inputs[row["revision_id"]]["path"]
            target = PREPARED / engine / "requests" / f"{row['queue_order']:06d}.json"
            documents[target] = overlay
            revised = copy.deepcopy(row)
            revised.update({"request": str(target),
                            "request_sha256": hashlib.sha256(encode(overlay).encode()).hexdigest(),
                            "preparation_failure": None})
            revised_rows.append(revised)
        require(len(set(ids)) == len(ids), "duplicate original request ID")
        index = copy.deepcopy(original)
        index.update({"requests": revised_rows, "request_count": len(rows),
                      "base_index": str(base_path), "base_index_sha256": base_sha,
                      "preparation_counts": {"ready": len(rows), "base_input_unavailable": 0},
                      "remeasurement_original_index": str(pin["index"]),
                      "remeasurement_original_index_sha256": pin["index_sha256"], "layer": LAYER})
        target = PREPARED / f"request-index-{engine}.json"
        documents[target] = index
        indexes[engine] = {"path": str(target),
                           "sha256": hashlib.sha256(encode(index).encode()).hexdigest(),
                           "request_count": len(rows)}
        counts[engine] = method_counts(rows, revisions)
    require(len({json.dumps(value, sort_keys=True) for value in counts.values()}) == 1,
            "engine request counts by revision/method differ")
    require(checked_inputs(revisions) == inputs, "input/check changed while preparing requests")
    plan = {"schema": SCHEMA, "action": "prepare", "selected_revisions": list(revisions),
            "inputs": inputs, "indexes": indexes, "request_counts": counts,
            "base_index": str(base_path), "base_index_sha256": base_sha,
            "source_base_index": str(BASE), "source_base_index_sha256": BASE_SHA,
            "engine_order": list(ENGINES),
            "total_requests": sum(entry["request_count"] for entry in indexes.values()),
            "script_sha256": sha256(Path(__file__).resolve()),
            "layer": LAYER, "strict_A_results_unchanged": True,
            "judging_executed": False,
            "candidate_payloads_read": False,
            "validation_scope": "Frozen index/request hashes and exact base_input-only overlays; "
                                "candidate payloads, inventory contents and J outputs are not opened."}
    # Refuse a different selected subset before writing any additional artifacts.
    plan_path = PREPARED / "plan.json"
    if plan_path.exists():
        require(read(plan_path) == plan, "prepared aq plan already fixed with different bindings")
    for path, document in documents.items():
        write_fixed(path, document)
    require(checked_inputs(revisions) == inputs, "input/check changed while writing requests")
    validate_overlays(revisions, inputs, indexes, base, counts)
    write_fixed(plan_path, plan)
    require(checked_inputs(revisions) == inputs, "input/check changed after plan was fixed")
    return {"status": "prepared", "selected_revisions": list(revisions),
            "plan": str(plan_path), "plan_sha256": sha256(plan_path),
            "indexes": indexes, "request_counts": counts,
            "total_requests": plan["total_requests"], "judging_executed": False}


def validate_overlays(revisions: tuple[str, ...], inputs: dict[str, Any],
                      indexes: dict[str, Any], base: dict[str, Any],
                      counts: dict[str, Any]) -> None:
    """Check exact overlays without runner helpers that open candidate payloads."""
    require(checked_inputs(revisions) == inputs, "checked inputs changed before validation")
    base_path = PREPARED / "constructed-base-index.json"
    require(read(base_path) == base, "constructed base index changed")
    for engine, entry in indexes.items():
        original = frozen_index(engine)
        source_rows = selected(original, revisions)
        index = read(owned(Path(entry["path"])), entry["sha256"])
        rows = index.get("requests", [])
        require(index.get("request_count") == len(rows) == len(source_rows) and
                method_counts(rows, revisions) == counts[engine], "prepared request counts differ")
        expected_index = copy.deepcopy(original)
        expected_index.update({"requests": rows, "request_count": len(rows),
                               "base_index": str(base_path), "base_index_sha256": sha256(base_path),
                               "preparation_counts": {"ready": len(rows), "base_input_unavailable": 0},
                               "remeasurement_original_index": str(ENGINES[engine]["index"]),
                               "remeasurement_original_index_sha256": ENGINES[engine]["index_sha256"],
                               "layer": LAYER})
        require(index == expected_index, "prepared index changed beyond the permitted overlay")
        for row, source in zip(rows, source_rows, strict=True):
            target = PREPARED / engine / "requests" / f"{source['queue_order']:06d}.json"
            expected = copy.deepcopy(source)
            expected.update({"request": str(target), "request_sha256": row["request_sha256"],
                             "preparation_failure": None})
            require(row == expected, "request row changed beyond the permitted overlay")
            before = read(Path(source["request"]), source["request_sha256"])
            after = read(owned(target), row["request_sha256"])
            before["base_input"] = inputs[row["revision_id"]]["path"]
            require(before == after, "request changed beyond base_input")
    require(checked_inputs(revisions) == inputs, "input/check changed during overlay validation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=("prepare",))
    parser.add_argument("--revisions", required=True, nargs="+", choices=tuple(EXPECTED_COUNTS))
    args = parser.parse_args()
    try:
        revisions = canonical_revisions(args.revisions)
        # Gate even lock-file creation on all selected checks; this opens no requests.
        checked_inputs(revisions)
        owned(PREPARED / ".prepare.lock")
        PREPARED.mkdir(parents=True, exist_ok=True)
        with (PREPARED / ".prepare.lock").open("a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = prepare(revisions)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"A aq preparation stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
