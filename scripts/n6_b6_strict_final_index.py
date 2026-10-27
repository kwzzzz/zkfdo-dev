#!/usr/bin/env python3
"""Preserve the strict B request index after metadata-only verification.

The program reads index rows only in memory. It never prints request IDs,
signal names, candidate paths, inputs, witnesses, or verdict data.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
B5 = ROOT / "runs/n6-b5-2026-10-17.noindex"
PREP = B5 / "batch1-prep.noindex"
OUTPUT = ROOT / "runs/n6-b6-2026-10-18.noindex/strict-final-index.json"
STAGES = ("a_zkbugs", "b_l_series", "c_committed_json", "d_project_test", "e_zero")
SIMPLE_REASON = re.compile(r"[a-z][a-z0-9_]{0,120}\Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "expected JSON object")
    return value


def safe_reason(value: object) -> str:
    """Expose fixed error codes; hash free-form text to avoid value disclosure."""
    if isinstance(value, str) and SIMPLE_REASON.fullmatch(value):
        return value
    encoded = str(value).encode("utf-8")
    return "free_form_sha256:" + hashlib.sha256(encoded).hexdigest()


def summarize_revision(identifier: str, base_row: dict, count: int) -> dict:
    attempts = base_row.get("failed_attempts", [])
    require(isinstance(attempts, list), "invalid base-input attempt list")
    failures: dict[str, list[str]] = {stage: [] for stage in STAGES}
    for item in attempts:
        require(isinstance(item, dict), "invalid base-input attempt")
        stage = item.get("stage")
        if stage in failures:
            failures[stage].append(safe_reason(item.get("reason")))
    expected = base_row.get("b_fuzz_r1cs_sha256")
    actual = base_row.get("compile", {}).get("r1cs_sha256")
    selected = base_row.get("selected_stage")
    stage_summary = {}
    for stage in STAGES:
        stage_summary[stage] = {
            "selected": selected == stage,
            "failure_count": len(failures[stage]),
            "failure_reasons": sorted(set(failures[stage])),
        }
    return {
        "revision": identifier,
        "request_count": count,
        "base_input_status": base_row.get("status"),
        "base_input_available": base_row.get("status") == "passed",
        "selected_stage": selected,
        "original_rule_stage": base_row.get("original_rule_stage"),
        "without_install_stage": base_row.get("without_install_stage"),
        "with_amendment_stage": base_row.get("with_amendment_stage"),
        "fuzz_r1cs_sha256": expected,
        "compiled_r1cs_sha256": actual,
        "r1cs_hash_match": bool(expected and actual and expected == actual
                                and base_row.get("b_fuzz_r1cs_match") is True),
        "zero_input_validated": selected == "e_zero" or
                                base_row.get("original_rule_stage") == "e_zero",
        "stages": stage_summary,
    }


def build() -> dict:
    preflight = read_json(PREP / "stages/preflight/state.json")
    base_state = read_json(PREP / "stages/base-inputs/state.json")
    index_state = read_json(PREP / "stages/index/state.json")
    require(preflight.get("status") == "completed" and preflight.get("exit_code") == 0,
            "strict preflight status incomplete")
    require(base_state.get("status") == "completed" and base_state.get("exit_code") == 0
            and base_state.get("revision_count") == 10, "base-input status incomplete")
    require(index_state.get("status") == "failed" and index_state.get("exit_code") == 1,
            "unexpected strict index stage status")

    base_path = Path(base_state["index"])
    require(base_path == B5 / "b-base-inputs/index.json", "unexpected base-input index path")
    base_sha = sha256(base_path)
    require(base_sha == base_state["index_sha256"], "base-input index hash changed")
    base = read_json(base_path)
    revisions = base.get("revisions")
    require(base.get("schema") == "n6-j1-base-inputs-v1" and
            isinstance(revisions, dict) and len(revisions) == 10,
            "base-input index does not cover ten revisions")
    require(base.get("r1cs_map_sha256") == preflight.get("b_r1cs_reference_sha256"),
            "R1CS reference pin differs")

    source = PREP / "request-index-v1.json"
    overlay_path = PREP / "request-index-v2.2.json"
    index = read_json(source)
    overlay = read_json(overlay_path)
    rows = index.get("requests")
    require(index.get("schema_version") == 1 and index.get("status") == "verified" and
            index.get("request_count") == 107 and isinstance(rows, list) and
            len(rows) == 107, "strict request index is not verified with 107 rows")
    require(index.get("base_index") == str(base_path) and
            index.get("base_index_sha256") == base_sha,
            "strict request index base-input binding differs")
    require(index.get("engine_sha256") == preflight.get("v1_engine_sha256") and
            overlay.get("engine_sha256") == preflight.get("v2_2_engine_sha256"),
            "strict request index engine pin differs")
    require(index.get("plan_index_sha256") ==
            sha256(PREP / "request-index-pending.json"),
            "strict request index plan binding differs")
    require(overlay.get("requests") == rows and
            overlay == {**index, "engine": overlay.get("engine"),
                        "engine_sha256": overlay.get("engine_sha256")},
            "v1 and v2.2 strict request rows differ")
    require(all(isinstance(row, dict) and row.get("method") == "S" and
                row.get("preparation_failure") == "base_input_unavailable" and
                row.get("revision_id") in revisions for row in rows),
            "at least one strict request is callable or has a different failure")
    require(len({row["request"] for row in rows}) == 107,
            "strict request paths are not unique")
    counts = Counter(row["revision_id"] for row in rows)
    require(all(revisions[identifier].get("status") == "base_input_unavailable"
                for identifier in counts), "a requested revision has a base input")

    source_bytes = source.read_bytes()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        require(OUTPUT.read_bytes() == source_bytes, "strict final index differs; refusing overwrite")
    else:
        with OUTPUT.open("xb") as stream:
            stream.write(source_bytes)
    require(sha256(OUTPUT) == sha256(source), "strict final index copy changed")

    return {
        "status": "strict_preparation_failure",
        "request_count": 107,
        "preparation_failure_count": 107,
        "source_index_sha256": sha256(source),
        "final_index_sha256": sha256(OUTPUT),
        "base_index_sha256": base_sha,
        "revision_summaries": [summarize_revision(identifier, revisions[identifier],
                                                  counts[identifier])
                               for identifier in sorted(revisions)],
    }


def main() -> None:
    print(json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
