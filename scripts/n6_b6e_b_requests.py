#!/usr/bin/env python3
"""Adopt B6d units for a new, value-free B6e request index.

This script reads request path/hash metadata, not candidate contents or J
verdicts. It never runs the judging engine and creates outputs exclusively.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import n6_b5_format_pilot as pilot
import n6_b6d_b_requests as b6d
import n6_j3_b_pilot_wait4 as selection
from n6_j1_requests import sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/n6-b6e-2026-10-20.noindex"
B6D = ROOT / "runs/n6-b6d-2026-10-20.noindex"
E2_AUDIT = OUT / "e2-equivalence-v2.json"
GATE = OUT / "equivalence-gate-v2.json"
PLAN = OUT / "request-index-pending.json"
INDEX_V1 = OUT / "request-index-v1.json"
INDEX_V22 = OUT / "request-index-v2.2.json"
REQUESTS = OUT / "requests"
SELECTION = OUT / "pilot-selection.json"
CHANGE_AUDIT = OUT / "index-change-audit.json"
INSTRUCTION = ROOT / "runs/handoff/n6_b6e_instruction_2026-10-20.md"
INSTRUCTION_SHA = "c19de060dd6cbeafd608dc72a2762a9ea44a7e5abc23feac69dde1a2158c8a95"
B6D_MANIFEST_SHA = "148425dd95eaf137d34b56b8c8868d410db3431ef7d18ae053346597f0e387f0"
B6D_B_AUDIT_SHA = "046e7b2b474e884b2faa50f8b77c1868efea03a2d9ff5b4531fbc08c0f9a5088"
B6D_A_AUDIT_SHA = "8e79ebc9b761f73eb664866c9ae27e0b08e350790a008ba9e8b47318dab5ec39"
B6D_R1CS_SHA = "47977c59d634a877b1b871280c7a8eb00d1454cba09d42907b40d10a6e863eec"
B6_ORIGINAL_INDEX_SHA = "b2b9da31cdc7708a7e1ef908c8c0aabb6f880cb6557c9573d91c88cb5ee5582e"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def checked_object(path: Path, digest: str) -> dict[str, Any]:
    require(path.is_file() and sha256_file(path) == digest,
            f"input SHA-256 differs: {path}")
    return read_object(path)


def write_new(path: Path, value: dict[str, Any]) -> str:
    require(not path.exists(), f"refuse to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return sha256_file(path)


def evidence() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate E1/E3/E4 and the revised E2 without touching candidate data."""
    require(sha256_file(INSTRUCTION) == INSTRUCTION_SHA,
            "B6e instruction SHA-256 changed")
    manifest = checked_object(b6d.MANIFEST, B6D_MANIFEST_SHA)
    original_b = checked_object(b6d.B_CLOSURE, B6D_B_AUDIT_SHA)
    original_a = checked_object(b6d.A_CLOSURE, B6D_A_AUDIT_SHA)
    r1cs = checked_object(b6d.R1CS_EVIDENCE, B6D_R1CS_SHA)
    revised = read_object(E2_AUDIT)
    require(revised.get("schema_version") == 2 and revised.get("status") == "pass" and
            revised.get("b6d_b_audit_sha256") == B6D_B_AUDIT_SHA and
            revised.get("b6d_a_audit_sha256") == B6D_A_AUDIT_SHA,
            "revised E2 audit does not bind B6d evidence")
    old_b = original_b.get("b", {})
    old_a = original_a.get("a", {})
    new_b = revised.get("b", {})
    new_a = revised.get("a", {})
    require(old_b.get("e1", {}).get("status") == "pass" and
            old_b.get("e2", {}).get("status") == "fail" and
            old_b.get("request_count") == new_b.get("request_count") == 107 and
            old_b.get("pair_count") == new_b.get("pair_count") == 17 and
            new_b.get("status") == "pass" and
            new_b.get("original_duplicate_request_count") == 9 and
            old_a.get("status") == new_a.get("status") == "pass" and
            old_a.get("request_count") == new_a.get("request_count") == 2926 and
            old_a.get("revision_count") == new_a.get("revision_count") == 26 and
            r1cs.get("e3_passed") is True and r1cs.get("e4_passed") is True and
            r1cs.get("pair_count") == 17 and r1cs.get("request_count") == 107 and
            r1cs.get("unit_manifest_sha256") == B6D_MANIFEST_SHA and
            original_b.get("staging_manifest_sha256") == B6D_MANIFEST_SHA and
            original_b.get("original_b_index_sha256") ==
            revised.get("b_original_index_sha256") == B6_ORIGINAL_INDEX_SHA and
            sha256_file(Path(original_b["original_b_index"])) ==
            B6_ORIGINAL_INDEX_SHA,
            "E1–E4 evidence is incomplete")
    old_pairs = {row["pair_id"]: row for row in old_b["pairs"]}
    new_pairs = {row["pair_id"]: row for row in new_b.get("pairs", [])}
    require(len(old_pairs) == len(new_pairs) == 17 and
            set(old_pairs) == set(new_pairs),
            "revised E2 pair coverage differs")
    duplicate_orders: set[int] = set()
    for pair_id, row in new_pairs.items():
        prior = old_pairs[pair_id]
        require(row.get("status") == "pass" and
                row.get("revision_id") == prior.get("revision_id") and
                row.get("queue_orders") == prior.get("queue_orders") and
                isinstance(row.get("original_duplicate"), bool),
                f"revised E2 pair differs: {pair_id}")
        if row["original_duplicate"]:
            require(prior.get("original_main_template_file_count", 0) > 1 and
                    prior.get("original_main_template_file_count") ==
                    prior.get("staged_main_template_file_count"),
                    "original duplicate marker lacks B6d support")
            duplicate_orders.update(row["queue_orders"])
        else:
            require(prior.get("original_main_template_file_count") == 1 and
                    prior.get("staged_main_template_file_count") == 1,
                    "unmarked main template is not unique")
    require(duplicate_orders == set(range(9)),
            "original duplicate must cover exactly anon-aadhaar queue 0–8")
    stage = b6d.verify_stage(manifest)
    require(stage["e4_passed"] and stage["project_file_count"] == 3872,
            "B6d unit byte audit failed")
    return manifest, revised, stage


def make_gate() -> dict[str, Any]:
    require(not GATE.exists(), "B6e gate already exists")
    manifest, revised, _stage = evidence()
    require(manifest.get("source_index_sha256") == b6d.SOURCE_INDEX_SHA,
            "B6d unit source index differs")
    gate = {
        "schema_version": 2, "kind": "n6_b6e_equivalence_gate",
        "status": "passed", "request_count": 107, "pair_count": 17,
        "e1": "passed", "e2": "passed", "e3": "passed", "e4": "passed",
        "original_template_duplicate_queue_orders": list(range(9)),
        "instruction_sha256": INSTRUCTION_SHA,
        "source_index_sha256": b6d.SOURCE_INDEX_SHA,
        "unit_manifest": str(b6d.MANIFEST),
        "unit_manifest_sha256": B6D_MANIFEST_SHA,
        "b_closure_audit": str(b6d.B_CLOSURE),
        "b_closure_audit_sha256": B6D_B_AUDIT_SHA,
        "a_closure_audit": str(b6d.A_CLOSURE),
        "a_closure_audit_sha256": B6D_A_AUDIT_SHA,
        "r1cs_equivalence": str(b6d.R1CS_EVIDENCE),
        "r1cs_equivalence_sha256": B6D_R1CS_SHA,
        "e2_audit": str(E2_AUDIT),
        "e2_audit_sha256": sha256_file(E2_AUDIT),
        "a_original_duplicate_pair_count": sum(bool(row.get("original_duplicate"))
                                                for row in revised["a"]["pairs"]),
    }
    write_new(GATE, gate)
    return gate


def checked_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    gate = read_object(GATE)
    manifest, revised, _stage = evidence()
    require(gate.get("schema_version") == 2 and gate.get("status") == "passed" and
            gate.get("request_count") == 107 and gate.get("pair_count") == 17 and
            all(gate.get(key) == "passed" for key in ("e1", "e2", "e3", "e4")) and
            gate.get("original_template_duplicate_queue_orders") == list(range(9)) and
            gate.get("instruction_sha256") == INSTRUCTION_SHA and
            gate.get("source_index_sha256") == b6d.SOURCE_INDEX_SHA and
            gate.get("unit_manifest") == str(b6d.MANIFEST) and
            gate.get("unit_manifest_sha256") == B6D_MANIFEST_SHA and
            gate.get("b_closure_audit_sha256") == B6D_B_AUDIT_SHA and
            gate.get("a_closure_audit_sha256") == B6D_A_AUDIT_SHA and
            gate.get("r1cs_equivalence_sha256") == B6D_R1CS_SHA and
            gate.get("e2_audit") == str(E2_AUDIT) and
            gate.get("e2_audit_sha256") == sha256_file(E2_AUDIT) and
            gate.get("a_original_duplicate_pair_count") ==
            sum(bool(row.get("original_duplicate")) for row in revised["a"]["pairs"]),
            "B6e gate differs from its evidence")
    return manifest, revised


def make_index() -> dict[str, Any]:
    require(all(not path.exists() for path in
                (PLAN, INDEX_V1, INDEX_V22, REQUESTS, SELECTION, CHANGE_AUDIT)),
            "B6e request output already exists")
    manifest, revised = checked_gate()
    source_plan, source_index, source_plan_rows = b6d.source_rows()
    require(sha256_file(b6d.SOURCE_INDEX_V22) == b6d.SOURCE_INDEX_V22_SHA,
            "B6b v2.2 source index SHA changed")
    source_v22 = read_object(b6d.SOURCE_INDEX_V22)
    require(source_v22 == {**source_index, "engine": source_v22.get("engine"),
                            "engine_sha256": source_v22.get("engine_sha256")},
            "B6b v2.2 differs beyond fixed engine")
    pair_by_order = {order: pair for pair in manifest["pairs"]
                     for order in pair["queue_orders"]}
    require(set(pair_by_order) == set(range(107)),
            "B6d units do not cover all request orders")
    e2_by_pair = {pair["pair_id"]: pair for pair in revised["b"]["pairs"]}
    base_path = Path(source_index["base_index"])
    require(sha256_file(base_path) == source_index["base_index_sha256"],
            "constructed input index SHA changed")
    base = read_object(base_path)
    new_plan_rows: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    request_payloads: list[tuple[Path, bytes]] = []
    changed_fields = {"source_root", "entrypoint", "component_wrapper", "library_paths"}
    for order, (old_row, old_plan) in enumerate(zip(source_index["requests"],
                                                    source_plan_rows)):
        require(old_row.get("queue_order") == order,
                f"B6b source order differs at {order}")
        pair = pair_by_order[order]
        require(pair["revision_id"] == old_row["revision_id"],
                f"B6d revision differs at {order}")
        e2_row = e2_by_pair[pair["pair_id"]]
        duplicate = e2_row["original_duplicate"]
        require(duplicate == (order in range(9)),
                f"original duplicate flag differs at {order}")
        old_request_path = Path(old_row["request"])
        require(sha256_file(old_request_path) == old_row["request_sha256"],
                f"B6b request SHA changed at {order}")
        old_request = read_object(old_request_path)
        request_id = old_request_path.stem
        require(old_request.get("id") == request_id and
                old_request.get("candidate", {}).get("path") ==
                old_plan["candidate_path"] and
                old_request.get("source_root") == old_plan["source_root"] and
                old_request.get("component_wrapper") == old_plan["component_wrapper"] and
                old_request.get("entrypoint") == old_plan["entrypoint"] and
                old_request.get("library_paths") == old_plan["library_paths"],
                f"B6b source request binding differs at {order}")
        request_path = (REQUESTS / old_row["scope"] / old_row["revision_id"] /
                        f"{request_id}.json")
        new_request = {**old_request, "source_root": pair["source_root"],
                       "entrypoint": pair["entrypoint"],
                       "component_wrapper": pair["wrapper"],
                       "library_paths": pair["library_paths"]}
        require({key for key in old_request if new_request[key] != old_request[key]}
                <= changed_fields and
                new_request.get("candidate") == old_request.get("candidate") and
                new_request.get("base_input") == old_request.get("base_input") and
                "original_template_duplicate" not in new_request,
                f"B6e engine request changed frozen fields at {order}")
        encoded = (json.dumps(new_request, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n").encode()
        request_payloads.append((request_path, encoded))
        new_plan_rows.append({**old_plan, "request": str(request_path),
                              "source_root": pair["source_root"],
                              "component_wrapper": pair["wrapper"],
                              "component_wrapper_sha256": pair["wrapper_sha256"],
                              "original_component_wrapper_sha256":
                              pair["original_wrapper_sha256"],
                              "entrypoint": pair["entrypoint"],
                              "library_paths": pair["library_paths"],
                              "original_library_paths": pair["original_library_paths"],
                              "original_template_duplicate": duplicate})
        base_row = base["revisions"][old_row["revision_id"]]
        require(old_request.get("base_input") == base_row["base_input_path"],
                f"constructed input path changed at {order}")
        new_rows.append({**old_row, "request": str(request_path),
                         "request_sha256": hashlib.sha256(encoded).hexdigest(),
                         "component_wrapper_sha256": pair["wrapper_sha256"],
                         "original_request": str(old_request_path),
                         "original_request_sha256": old_row["request_sha256"],
                         "original_component_wrapper_sha256":
                         pair["original_wrapper_sha256"],
                         "original_library_paths": pair["original_library_paths"],
                         "base_input_sha256": base_row["base_input_sha256"],
                         "original_template_duplicate": duplicate})
        require(new_rows[-1]["candidate_sha256"] == old_row["candidate_sha256"],
                "candidate SHA changed")
    require(sum(row["original_template_duplicate"] for row in new_rows) == 9,
            "anon-aadhaar duplicate marker count differs")
    gate_sha = sha256_file(GATE)
    plan = {**source_plan, "requests": new_plan_rows,
            "source_plan": str(b6d.SOURCE_PLAN),
            "source_plan_sha256": sha256_file(b6d.SOURCE_PLAN),
            "unit_manifest": str(b6d.MANIFEST),
            "unit_manifest_sha256": B6D_MANIFEST_SHA,
            "equivalence_gate": str(GATE),
            "equivalence_gate_sha256": gate_sha}
    index = {**source_index, "requests": new_rows,
             "plan_index": str(PLAN),
             "source_index": str(b6d.SOURCE_INDEX),
             "source_index_sha256": b6d.SOURCE_INDEX_SHA,
             "unit_manifest": str(b6d.MANIFEST),
             "unit_manifest_sha256": B6D_MANIFEST_SHA,
             "equivalence_gate": str(GATE),
             "equivalence_gate_sha256": gate_sha}
    INDEX_V22_ENGINE = {"engine": source_v22["engine"],
                        "engine_sha256": source_v22["engine_sha256"]}
    chosen = selection.select_requests(index, base)
    require([row["queue_order"] for row in chosen] == [9, 25],
            "B6e pilot selection differs from original max/min rule")
    selection_record = {"schema_version": 1,
                        "requests": pilot.selected_ids(chosen)}
    # Every binding above is checked before the first output is created.
    REQUESTS.mkdir(parents=True, exist_ok=False)
    for path, payload in request_payloads:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
    index["plan_index_sha256"] = write_new(PLAN, plan)
    index_v1_sha = write_new(INDEX_V1, index)
    index_v22_sha = write_new(INDEX_V22, {**index, **INDEX_V22_ENGINE})
    selection_sha = write_new(SELECTION, selection_record)
    write_new(CHANGE_AUDIT, {
        "schema_version": 1, "kind": "n6_b6e_request_field_audit",
        "request_count": 107, "original_template_duplicate_count": 9,
        "original_template_duplicate_queue_orders": list(range(9)),
        "source_index": str(b6d.SOURCE_INDEX),
        "source_index_sha256": b6d.SOURCE_INDEX_SHA,
        "index_v1": str(INDEX_V1), "index_v1_sha256": index_v1_sha,
        "index_v22": str(INDEX_V22), "index_v22_sha256": index_v22_sha,
        "selection": str(SELECTION), "selection_sha256": selection_sha,
        "engine_request_changed_fields_allowed": sorted(changed_fields),
        "engine_request_original_template_duplicate_field_count": 0,
        "preserved_index_row_fields": sorted(set(source_index["requests"][0]) -
                                             {"request", "request_sha256",
                                              "component_wrapper_sha256"}),
        "candidate_sha256_unchanged_count": 107,
        "constructed_base_input_path_unchanged_count": 107,
        "request_id_unchanged_count": 107,
    })
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("gate", "index"))
    args = parser.parse_args(argv)
    if args.action == "gate":
        make_gate()
        print(GATE)
    else:
        make_index()
        print(INDEX_V1)
        print(INDEX_V22)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
