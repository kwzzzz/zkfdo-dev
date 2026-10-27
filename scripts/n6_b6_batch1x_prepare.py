#!/usr/bin/env python3
"""Prepare and later run B batch 1 with reviewed constructed base inputs.

The pilot action creates a fresh request index, validates both fixed engines,
and runs two format-only pilots after lead approval. The execute-all action
requires those pilots and runs v2.2 before v1. Neither action prints candidate
values, request identifiers, verdicts, or J result contents.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

import n6_j3_b_pilot_wait4 as b_selection
import run_n6_j1 as runner
from n6_b5_j_adapter import (ENGINE_V1, ENGINE_V1_SHA, ENGINE_V22,
                             ENGINE_V22_SHA, verify_mem20)


ROOT = Path(__file__).resolve().parents[1]
B6 = ROOT / "runs/n6-b6-2026-10-18.noindex"
OUT = B6 / "batch1x-prep.noindex"
CONSTRUCTED = B6 / "constructed-inputs"
BASE = CONSTRUCTED / "index.json"
TABLE = CONSTRUCTED / "review-table.md"
LEAD = B6 / "lead-input-review.json"
TABLE2 = CONSTRUCTED / "review-table-2.md"
LEAD2 = B6 / "lead-input-review-2.json"
N5_AMENDMENT = ROOT / "docs/n5_amendment_b_judging_2026-10-17.md"
N5_AMENDMENT_SHA = "751c305aacd5fb63683551efcb8b867597ddc95739e8ab9eac0cc08d18fabb72"
INVENTORY = ROOT / "runs/n6-j3-2026-10-14.noindex/candidate-inventory.json"
QUEUE = ROOT / "runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json"
ADAPTER = ROOT / "scripts/n6_b5_j_adapter.py"
S_STATE = ROOT / "runs/n6-b5-2026-10-17.noindex/s-nested-execute.noindex/state.json"
A_STATE = B6 / "a-calibration.noindex/state.json"
VOLUME = Path("/Volumes/zkfdo-jcache")
CACHE = VOLUME / "n6-b6-batch1x"
PLAN = OUT / "request-index-pending.json"
INDEX_V1 = OUT / "request-index-v1.json"
INDEX_V22 = OUT / "request-index-v2.2.json"
REQUESTS = OUT / "requests"
SELECTION = OUT / "pilot-selection.json"
REVISION8 = re.compile(r"[0-9a-f]{8}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
FIRST_REVISIONS = frozenset({"6079a717", "b5b5cf5d", "340107e1",
                             "4c221df7", "a8b2aa9c"})
SECOND_REVISIONS = frozenset({"76053f7f", "77e0f2db", "83cc0060",
                              "e71f158d"})
REVIEW_TABLE_ORIGINAL_BYTES = 4896
REVIEW_TABLE_ORIGINAL_SHA = "ac7d444367e6ec85ada9bf513e68efbded16fb33d43e88691ead80c9e061ff99"
REVIEW_TABLE2_ORIGINAL_BYTES = 6945
REVIEW_TABLE2_ORIGINAL_SHA = "af277cd83a415b539007c966be6ca6a2987ba9997d58470e91a517e812b89918"
REVIEW_TABLE2_FIRST_CORRECTION_BYTES = 11749
REVIEW_TABLE2_FIRST_CORRECTION_SHA = "b7d1a1f8e7a434f28b7612257001c18582e40deb23dc69cd3b7dacdba29abfb1"
REVIEW_TABLE_CORRECTION_MARKER = "\n## 정정본\n".encode()
REVIEW_TABLE_SECOND_CORRECTION_MARKER = "\n## 정정본 2\n".encode()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "expected JSON object")
    return value


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def s_idle() -> None:
    if S_STATE.is_file():
        status = read_json(S_STATE).get("status")
        require(status in {"completed", "failed", "stopped", "stopped_between_units",
                           "start_gate_failed", "disk_guard"},
                "S prestart check or refuzz is active; B J work refused")
    if A_STATE.is_file():
        status = read_json(A_STATE).get("status")
        require(status in {"completed", "failed", "stopped"},
                "A calibration is active; B J work refused")


def cache_volume() -> None:
    require(os.path.ismount(VOLUME), "J cache volume is not mounted")
    require(VOLUME.is_dir(), "J cache volume is missing")
    CACHE.mkdir(exist_ok=True)
    require(CACHE.is_dir(), "B6 cache directory is unavailable")


def state_path(name: str) -> Path:
    return OUT / "stages" / name / "state.json"


def save_state(name: str, value: dict[str, Any]) -> None:
    path = state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def stage(name: str, action, verify) -> dict[str, Any]:
    path = state_path(name)
    if path.exists():
        previous = read_json(path)
        require(previous.get("status") == "completed" and previous.get("exit_code") == 0,
                "incomplete B6 stage exists; preserve it for review")
        verify(previous)
        return previous
    value: dict[str, Any] = {"schema_version": 1, "stage": name,
                             "status": "running", "started_at": stamp()}
    save_state(name, value)
    try:
        value.update(action() or {})
        value["status"] = "completed"
        value["exit_code"] = 0
    except Exception as error:
        value["status"] = "failed"
        value["exit_code"] = 1
        value["error_type"] = type(error).__name__
        raise
    finally:
        value["completed_at"] = stamp()
        save_state(name, value)
    return value


def logged_command(name: str, command: list[str]) -> int:
    s_idle()
    directory = state_path(name).parent
    directory.mkdir(parents=True, exist_ok=True)
    number = len(list(directory.glob("command-*.log"))) + 1
    log = directory / f"command-{number:03d}.log"
    with log.open("x") as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, check=False)
    return result.returncode


def adapter_command(stage_name: str, engine: str, *args: str) -> list[str]:
    return [sys.executable, str(ADAPTER), "--stage", stage_name,
            "--engine", engine, *args]


def base_index() -> dict[str, Any]:
    base = read_json(BASE)
    revisions = base.get("revisions")
    require(base.get("schema") == "n6-j1-base-inputs-v1" and
            base.get("layer") == "constructed" and isinstance(revisions, dict) and
            len(revisions) == 10, "constructed base-input index incomplete")
    for row in revisions.values():
        require(isinstance(row, dict) and row.get("status") in
                {"passed", "base_input_unavailable"},
                "constructed base-input revision status invalid")
        if row["status"] == "passed":
            path = Path(row["base_input_path"])
            require(path.is_file() and sha256(path) == row.get("base_input_sha256"),
                    "constructed base-input file/hash differs")
        else:
            require(row.get("base_input_path") is None and
                    row.get("base_input_sha256") is None,
                    "unavailable constructed input unexpectedly has a path")
    return base


def preflight() -> dict[str, Any]:
    s_idle()
    verify_mem20()
    cache_volume()
    require(sha256(N5_AMENDMENT) == N5_AMENDMENT_SHA,
            "N5 constructed-input amendment SHA changed")
    require(sha256(ENGINE_V1) == ENGINE_V1_SHA and
            sha256(ENGINE_V22) == ENGINE_V22_SHA and
            runner.ENGINE == ENGINE_V1 and runner.ENGINE_SHA256 == ENGINE_V1_SHA,
            "fixed J engine pin differs")
    require(sha256(runner.CIRCOM) == runner.CIRCOM_SHA256,
            "fixed circom pin differs")
    require(all(path.is_file() for path in (INVENTORY, QUEUE, ADAPTER, TABLE, BASE)),
            "B6 preparation input missing")
    base_index()
    disk_free = {"repository": shutil.disk_usage(ROOT).free,
                 "cache": shutil.disk_usage(CACHE).free}
    require(min(disk_free.values()) >= runner.MIN_FREE_BYTES,
            "B6 disk free below the runner minimum")
    require(logged_command("preflight", ["docker", "info"]) == 0,
            "Docker Desktop unavailable")
    require(logged_command("preflight", ["docker", "system", "df"]) == 0,
            "Docker disk inspection failed")
    return {"n5_amendment_sha256": N5_AMENDMENT_SHA,
            "base_index_sha256": sha256(BASE), "review_table_sha256": sha256(TABLE),
            "inventory_sha256": sha256(INVENTORY), "queue_sha256": sha256(QUEUE),
            "adapter_sha256": sha256(ADAPTER), "orchestrator_sha256": sha256(Path(__file__)),
            "v1_engine_sha256": ENGINE_V1_SHA, "v2_2_engine_sha256": ENGINE_V22_SHA,
            "disk_free_bytes": disk_free}


def verify_preflight(saved: dict[str, Any]) -> None:
    s_idle()
    cache_volume()
    require(saved.get("n5_amendment_sha256") == sha256(N5_AMENDMENT) == N5_AMENDMENT_SHA and
            saved.get("base_index_sha256") == sha256(BASE) and
            saved.get("review_table_sha256") == sha256(TABLE) and
            saved.get("inventory_sha256") == sha256(INVENTORY) and
            saved.get("queue_sha256") == sha256(QUEUE) and
            saved.get("adapter_sha256") == sha256(ADAPTER) and
            saved.get("orchestrator_sha256") == sha256(Path(__file__)),
            "B6 preflight evidence changed")
    base_index()


def write_new(path: Path, value: dict[str, Any]) -> str:
    require(not path.exists(), "refusing to overwrite B6 artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return sha256(path)


def index_summary() -> dict[str, Any]:
    require(all(path.is_file() for path in (PLAN, INDEX_V1, INDEX_V22)),
            "B6 request index missing")
    plan = read_json(PLAN)
    v1 = read_json(INDEX_V1)
    v22 = read_json(INDEX_V22)
    rows = v1.get("requests")
    require(plan.get("status") == "awaiting_base_input" and
            plan.get("request_count") == 107 and
            len(plan.get("requests", [])) == 107,
            "B6 request plan is not 107 rows")
    require(v1.get("schema_version") == 1 and v1.get("status") == "verified" and
            v1.get("request_count") == 107 and isinstance(rows, list) and len(rows) == 107,
            "B6 final request index is not 107 rows")
    require(v1.get("base_index") == str(BASE) and
            v1.get("base_index_sha256") == sha256(BASE) and
            v1.get("plan_index_sha256") == sha256(PLAN) and
            v1.get("inventory_sha256") == sha256(INVENTORY) and
            v1.get("engine_sha256") == ENGINE_V1_SHA,
            "B6 request index input lock differs")
    require(v22 == {**v1, "engine": str(ENGINE_V22),
                    "engine_sha256": ENGINE_V22_SHA},
            "B6 v2.2 overlay changed request rows")
    require(all(isinstance(row, dict) and row.get("method") == "S" for row in rows) and
            len({row["request"] for row in rows}) == 107,
            "B6 request methods/paths differ")
    return {"plan_sha256": sha256(PLAN), "v1_index_sha256": sha256(INDEX_V1),
            "v2_2_index_sha256": sha256(INDEX_V22), "request_count": 107,
            "ready_count": v1.get("preparation_counts", {}).get("ready", 0)}


def prepare_index() -> dict[str, Any]:
    common = ("--scope", "main", "--inventory", str(INVENTORY),
              "--queue", str(QUEUE), "--request-root", str(REQUESTS),
              "--plan-index", str(PLAN), "--index", str(INDEX_V1))
    if not PLAN.exists():
        require(logged_command("index", adapter_command("requests", "v1", *common)) == 0,
                "B6 request plan failed")
    if not INDEX_V1.exists():
        require(not REQUESTS.exists(), "partial B6 request files exist; preserve for review")
        require(logged_command("index", adapter_command(
            "requests", "v1", *common, "--base-index", str(BASE))) == 0,
            "B6 request finalization failed")
    if not INDEX_V22.exists():
        v1 = read_json(INDEX_V1)
        require(v1.get("engine") == str(ENGINE_V1) and
                v1.get("engine_sha256") == ENGINE_V1_SHA,
                "B6 v1 engine lock differs")
        write_new(INDEX_V22, {**v1, "engine": str(ENGINE_V22),
                              "engine_sha256": ENGINE_V22_SHA})
    return index_summary()


def validate(engine: str, index: Path) -> dict[str, Any]:
    require(logged_command(f"validate-{engine}", adapter_command(
        "validate", engine, "--index", str(index),
        "--index-sha256", sha256(index), "--cache-root", str(CACHE),
        "--action", "validate-only")) == 0,
        "B6 validate-only failed")
    return {"index_sha256": sha256(index), "validation_exit_code": 0}


def verify_validate(saved: dict[str, Any], index: Path) -> None:
    require(saved.get("index_sha256") == sha256(index) and
            saved.get("validation_exit_code") == 0,
            "B6 validate-only evidence changed")


def review_table_hashes(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    corrected = False
    frozen = None
    if path.resolve() == TABLE.resolve():
        frozen = (REVIEW_TABLE_ORIGINAL_BYTES, REVIEW_TABLE_ORIGINAL_SHA,
                  FIRST_REVISIONS)
    elif path.resolve() == TABLE2.resolve():
        frozen = (REVIEW_TABLE2_ORIGINAL_BYTES, REVIEW_TABLE2_ORIGINAL_SHA,
                  SECOND_REVISIONS)
    if path.resolve() == TABLE2.resolve() and len(raw) > REVIEW_TABLE2_FIRST_CORRECTION_BYTES:
        require(hashlib.sha256(raw[:REVIEW_TABLE2_ORIGINAL_BYTES]).hexdigest() ==
                REVIEW_TABLE2_ORIGINAL_SHA and
                hashlib.sha256(raw[:REVIEW_TABLE2_FIRST_CORRECTION_BYTES]).hexdigest() ==
                REVIEW_TABLE2_FIRST_CORRECTION_SHA,
                "B6 second review table correction prefix changed")
        suffix = raw[REVIEW_TABLE2_FIRST_CORRECTION_BYTES:]
        require(suffix.startswith(REVIEW_TABLE_SECOND_CORRECTION_MARKER) and
                suffix.count(REVIEW_TABLE_SECOND_CORRECTION_MARKER) == 1,
                "B6 second review table correction heading missing or repeated")
        raw = suffix
        corrected = True
        expected_revisions = SECOND_REVISIONS
    elif frozen is not None:
        original_bytes, original_sha, expected_revisions = frozen
        if hashlib.sha256(raw).hexdigest() == original_sha:
            require(len(raw) == original_bytes,
                    "B6 original review table size differs")
        else:
            require(len(raw) > original_bytes and
                    hashlib.sha256(raw[:original_bytes]).hexdigest() == original_sha,
                    "B6 original review table prefix changed")
            suffix = raw[original_bytes:]
            require(suffix.startswith(REVIEW_TABLE_CORRECTION_MARKER) and
                    suffix.count(REVIEW_TABLE_CORRECTION_MARKER) == 1,
                    "B6 review table correction heading missing or repeated")
            raw = suffix
            corrected = True
    lines = raw.decode("utf-8").splitlines()
    expected_header = ["revision", "project", "모사 입력", "생성 스크립트 SHA-256",
                       "input.json SHA-256", "스위치류 입력 값", "공개 출력 전부 0",
                       "예시 형태 일치·근거", "정직 witness", "Rust", "snarkjs",
                       "R1CS SHA-256 일치", "소요 시간(초)", "실패 사유"]
    tables = [line for line in lines if line.startswith("|")]
    require(tables, "B6 review table has no rows")
    cells = lambda line: [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
    require(cells(tables[0]) == expected_header, "B6 review table header differs")
    if corrected:
        require(len(tables) == len(expected_revisions) + 2 and
                len(cells(tables[1])) == len(expected_header) and
                all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells(tables[1])),
                "B6 corrected review table must have one complete revision table")
    rows: dict[str, str] = {}
    for line in tables[1:]:
        parts = cells(line)
        if all(part and set(part) <= {"-", ":", " "} for part in parts):
            continue
        require(len(parts) == len(expected_header), "B6 review table column count differs")
        short, digest = parts[0], parts[4]
        require(REVISION8.fullmatch(short) is not None and
                (SHA64.fullmatch(digest) is not None or digest == "없음") and
                short not in rows, "B6 review table revision/hash invalid")
        rows[short] = digest
    if corrected:
        require(set(rows) == expected_revisions,
                "B6 corrected review table revision set differs")
    return rows


def review_gate(base: dict[str, Any], index: dict[str, Any], *,
                lead_path: Path = LEAD, table_path: Path = TABLE,
                constructed_root: Path = CONSTRUCTED) -> set[str]:
    require(lead_path.is_file(), "lead input review record missing; pilot refused")
    review = read_json(lead_path)
    require(review.get("reviewer") == "lead" and
            review.get("reviewed_table_sha256") == sha256(table_path),
            "lead review table binding differs")
    approved = review.get("approved_revisions")
    require(isinstance(approved, list) and approved and
            all(isinstance(item, str) and REVISION8.fullmatch(item) for item in approved) and
            len(set(approved)) == len(approved),
            "lead approved revision list invalid")
    time_utc = review.get("time_utc")
    require(isinstance(time_utc, str) and time_utc.endswith(("Z", "+00:00")),
            "lead review UTC time missing")
    table_hashes = review_table_hashes(table_path)
    revisions = base["revisions"]
    mapped: dict[str, str] = {}
    for short in approved:
        matches = [identifier for identifier in revisions if identifier.startswith(short)]
        require(len(matches) == 1, "approved revision prefix is ambiguous")
        identifier = matches[0]
        row = revisions[identifier]
        digest = table_hashes.get(short)
        require(row.get("status") == "passed" and digest is not None and digest != "없음" and
                row.get("base_input_sha256") == digest,
                "approved input hash/status differs from review table")
        path = Path(row["base_input_path"])
        require(path.is_file() and path.resolve().is_relative_to(constructed_root.resolve()) and
                sha256(path) == digest,
                "approved input file/hash differs")
        mapped[short] = identifier
    callable_revisions = {row["revision_id"] for row in index["requests"]
                          if row["preparation_failure"] is None}
    require(callable_revisions <= set(mapped.values()),
            "an unapproved constructed input is callable")
    return set(mapped.values())


def review_partition(base: dict[str, Any], expected: frozenset[str], *,
                     lead_path: Path, table_path: Path,
                     constructed_root: Path) -> set[str]:
    """Bind every revision in a review partition, including those without B requests."""
    require(table_path.is_file() and lead_path.is_file(),
            "B6 review table or lead record missing; result access refused")
    review = read_json(lead_path)
    require(review.get("reviewer") == "lead" and
            review.get("reviewed_table_sha256") == sha256(table_path),
            "B6 result review table binding differs")
    time_utc = review.get("time_utc")
    require(isinstance(time_utc, str) and time_utc.endswith(("Z", "+00:00")),
            "B6 result review UTC time missing")
    approved = review.get("approved_revisions")
    require(isinstance(approved, list) and
            all(isinstance(short, str) and REVISION8.fullmatch(short)
                for short in approved) and len(set(approved)) == len(approved) and
            set(approved) <= expected,
            "B6 result approved revision list invalid")
    table_hashes = review_table_hashes(table_path)
    require(set(table_hashes) == expected,
            "B6 result review table does not cover its revision partition")
    revisions = base.get("revisions")
    require(isinstance(revisions, dict), "B6 constructed revisions missing")
    mapped: dict[str, str] = {}
    for short in expected:
        matches = [identifier for identifier in revisions if identifier.startswith(short)]
        require(len(matches) == 1, "B6 result revision prefix ambiguous")
        identifier = matches[0]
        row = revisions[identifier]
        require(isinstance(row, dict), "B6 result revision row invalid")
        if short in approved:
            digest = table_hashes[short]
            require(row.get("status") == "passed" and
                    SHA64.fullmatch(digest) is not None and
                    row.get("base_input_sha256") == digest and
                    isinstance(row.get("base_input_path"), str),
                    "B6 result approved input status/hash differs")
            path = Path(row["base_input_path"])
            require(path.is_file() and
                    path.resolve().is_relative_to(constructed_root.resolve()) and
                    sha256(path) == digest,
                    "B6 result approved input file/hash differs")
        else:
            require(row.get("status") == "base_input_unavailable" and
                    row.get("base_input_path") is None and
                    row.get("base_input_sha256") is None and
                    table_hashes[short] == "없음",
                    "B6 result has an unapproved available input")
        mapped[short] = identifier
    return {mapped[short] for short in approved}


def results_review_gate(base: dict[str, Any], index: dict[str, Any], *,
                        first_table: Path = TABLE, first_lead: Path = LEAD,
                        second_table: Path = TABLE2, second_lead: Path = LEAD2,
                        constructed_root: Path = CONSTRUCTED) -> None:
    require(base.get("schema") == "n6-j1-base-inputs-v1" and
            base.get("layer") == "constructed" and
            len(base.get("revisions", {})) == 10,
            "B6 result constructed index incomplete")
    first = review_partition(base, FIRST_REVISIONS, lead_path=first_lead,
                             table_path=first_table, constructed_root=constructed_root)
    review_partition(base, SECOND_REVISIONS, lead_path=second_lead,
                     table_path=second_table, constructed_root=constructed_root)
    callable_revisions = {row["revision_id"] for row in index["requests"]
                          if row["preparation_failure"] is None}
    require(callable_revisions <= first,
            "B6 result includes an unapproved callable revision")


def verify_results_gate() -> None:
    """Read only B6 stage metadata and frozen review/input evidence, never J results."""
    for engine in ("v2.2", "v1"):
        name = f"full-{engine}"
        path = state_path(name)
        require(path.is_file(), "B6 both full engines must finish before result access")
        state = read_json(path)
        state_digest = state.get("state_sha256")
        require(state.get("stage") == name and state.get("engine") == engine and
                state.get("status") == "completed" and state.get("exit_code") == 0 and
                state.get("request_count") == 107 and
                state.get("output") == str(OUT / f"{name}.noindex") and
                state.get("cache_root") == str(CACHE / name) and
                isinstance(state_digest, str) and SHA64.fullmatch(state_digest) is not None,
                "B6 both full engines must finish before result access")
        output_state = OUT / f"{name}.noindex/state.json"
        require(output_state.is_file() and sha256(output_state) == state_digest,
                "B6 full J state file/hash differs before result access")
    index_summary()
    results_review_gate(base_index(), read_json(INDEX_V1))


def selected_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"request_id": Path(row["request"]).stem,
             "queue_order": row["queue_order"],
             "revision_id": row["revision_id"]} for row in rows]


def pilot_selection() -> dict[str, Any]:
    base = base_index()
    index = read_json(INDEX_V1)
    approved = review_gate(base, index)
    selected = b_selection.select_requests(index, base)
    require(len(selected) == 2 and all(row["revision_id"] in approved and
                                       row["preparation_failure"] is None
                                       for row in selected),
            "two approved callable B pilot requests required")
    expected = {"schema_version": 1, "requests": selected_ids(selected)}
    if SELECTION.exists():
        require(read_json(SELECTION) == expected, "B6 pilot selection changed")
    else:
        write_new(SELECTION, expected)
    return {"selection_sha256": sha256(SELECTION), "selected_count": 2,
            "reviewed_table_sha256": sha256(TABLE), "lead_review_sha256": sha256(LEAD)}


def verify_selection(saved: dict[str, Any]) -> None:
    require(SELECTION.is_file(), "B6 pilot selection missing")
    current = pilot_selection()
    require(all(saved.get(key) == value for key, value in current.items()),
            "B6 pilot selection or lead review changed")


def pilot_state(engine: str, index: Path, output: Path) -> dict[str, Any]:
    state_file = output / "state.json"
    state = read_json(state_file)
    index_rows = read_json(index).get("requests")
    require(isinstance(index_rows, list), "B6 pilot request index missing rows")
    rows = {row["queue_order"]: row for row in index_rows}
    require(state.get("kind") == "n6_b5_format_only_pilot_state" and
            state.get("status") == "passed" and
            state.get("request_index_sha256") == sha256(index) and
            state.get("base_index_sha256") == sha256(BASE) and
            state.get("selection_sha256") == sha256(SELECTION) and
            state.get("engine_sha256") == (ENGINE_V22_SHA if engine == "v2.2" else ENGINE_V1_SHA),
            "B6 format pilot state binding differs")
    records = state.get("requests")
    require(isinstance(records, dict) and len(records) == 2 and
            all(isinstance(value, dict) and value.get("status") == "completed" and
                value.get("exit_code") == 0 and value.get("format_ok") is True and
                type(value.get("max_rss_bytes")) is int and value["max_rss_bytes"] > 0
                for value in records.values()),
            "B6 format pilot did not complete two requests")
    for record in records.values():
        row = rows.get(record.get("queue_order"))
        path_value = record.get("result_path")
        require(isinstance(row, dict) and isinstance(path_value, str) and
                record.get("request_sha256") == row.get("request_sha256"),
                "B6 pilot result/request binding differs")
        result_path = Path(path_value)
        require(result_path.is_file() and sha256(result_path) == record.get("result_sha256"),
                "B6 pilot result file/hash differs")
    revisions = state.get("revisions")
    require(isinstance(revisions, dict) and revisions and
            all(isinstance(row, dict) and row.get("status") == "joined" and
                row.get("format_ok") is True and row.get("exit_code") == 0 and
                isinstance(row.get("instances_path"), str) and
                Path(row["instances_path"]).is_file() and
                sha256(Path(row["instances_path"])) == row.get("instances_sha256")
                for row in revisions.values()),
            "B6 pilot joined instance file/hash differs")
    return {"output": str(output), "state_sha256": sha256(state_file),
            "completed_request_count": 2, "format_ok": True}


def pilot(engine: str, index: Path) -> dict[str, Any]:
    base = base_index()
    review_gate(base, read_json(INDEX_V1))
    output = OUT / f"pilot-{engine}.noindex"
    cache = CACHE / f"pilot-{engine}"
    require(not output.exists() and not cache.exists(),
            "B6 pilot output/cache already exists; preserve for review")
    require(logged_command(f"pilot-{engine}", adapter_command(
        "pilot", engine, "--index", str(index), "--index-sha256", sha256(index),
        "--base-index", str(BASE), "--base-index-sha256", sha256(BASE),
        "--selection", str(SELECTION), "--cache-root", str(cache),
        "--output", str(output), "--action", "execute")) == 0,
        "B6 format pilot failed")
    return {"engine": engine, "cache_root": str(cache), **pilot_state(engine, index, output)}


def verify_pilot(saved: dict[str, Any], engine: str, index: Path) -> None:
    require(saved.get("status") == "completed" and saved.get("exit_code") == 0,
            "B6 pilot stage incomplete")
    output = OUT / f"pilot-{engine}.noindex"
    cache = CACHE / f"pilot-{engine}"
    require(cache.is_dir(), "B6 pilot cache missing")
    current = {"engine": engine, "cache_root": str(cache),
               **pilot_state(engine, index, output)}
    require(all(saved.get(key) == value for key, value in current.items()),
            "B6 pilot state changed")


def full_state(engine: str, index: Path, cache: Path, output: Path) -> dict[str, Any]:
    state_file = output / "state.json"
    state = read_json(state_file)
    require(state.get("status") == "completed" and
            state.get("request_index_sha256") == sha256(index) and
            state.get("engine_sha256") == (ENGINE_V22_SHA if engine == "v2.2" else ENGINE_V1_SHA) and
            state.get("cache_root") == str(cache) and
            isinstance(state.get("requests"), dict) and len(state["requests"]) == 107,
            "B6 full J state incomplete")
    return {"output": str(output), "cache_root": str(cache),
            "state_sha256": sha256(state_file), "request_count": 107}


def full(engine: str, index: Path) -> dict[str, Any]:
    review_gate(base_index(), read_json(INDEX_V1))
    cache = CACHE / f"full-{engine}"
    output = OUT / f"full-{engine}.noindex"
    require(not cache.exists() and not output.exists(),
            "B6 full output/cache already exists; preserve for review")
    cache.mkdir()
    require(logged_command(f"full-{engine}", adapter_command(
        "validate", engine, "--index", str(index), "--index-sha256", sha256(index),
        "--cache-root", str(cache), "--output", str(output),
        "--action", "execute")) == 0,
        "B6 full J execution stopped")
    return {"engine": engine, **full_state(engine, index, cache, output)}


def verify_full(saved: dict[str, Any], engine: str, index: Path) -> None:
    cache = CACHE / f"full-{engine}"
    output = OUT / f"full-{engine}.noindex"
    current = {"engine": engine, **full_state(engine, index, cache, output)}
    require(all(saved.get(key) == value for key, value in current.items()),
            "B6 full J state changed")


def prepare() -> None:
    stage("preflight", preflight, verify_preflight)
    stage("index", prepare_index,
          lambda saved: require(all(saved.get(k) == v for k, v in index_summary().items()),
                                "B6 request index changed"))
    stage("validate-v2.2", lambda: validate("v2.2", INDEX_V22),
          lambda saved: verify_validate(saved, INDEX_V22))
    stage("validate-v1", lambda: validate("v1", INDEX_V1),
          lambda saved: verify_validate(saved, INDEX_V1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("prepare", "pilot", "execute-all",
                                             "verify-results-gate"),
                        required=True)
    args = parser.parse_args()
    if args.action in {"prepare", "pilot"}:
        prepare()
    if args.action == "pilot":
        stage("pilot-selection", pilot_selection, verify_selection)
        stage("pilot-v2.2", lambda: pilot("v2.2", INDEX_V22),
              lambda saved: verify_pilot(saved, "v2.2", INDEX_V22))
        stage("pilot-v1", lambda: pilot("v1", INDEX_V1),
              lambda saved: verify_pilot(saved, "v1", INDEX_V1))
    if args.action == "execute-all":
        require(state_path("pilot-v2.2").is_file() and
                state_path("pilot-v1").is_file(),
                "both format pilots must pass before full J")
        prepare()
        selection_state = read_json(state_path("pilot-selection"))
        require(selection_state.get("status") == "completed" and
                selection_state.get("exit_code") == 0,
                "B6 pilot selection stage incomplete")
        verify_selection(selection_state)
        verify_pilot(read_json(state_path("pilot-v2.2")), "v2.2", INDEX_V22)
        verify_pilot(read_json(state_path("pilot-v1")), "v1", INDEX_V1)
        stage("full-v2.2", lambda: full("v2.2", INDEX_V22),
              lambda saved: verify_full(saved, "v2.2", INDEX_V22))
        stage("full-v1", lambda: full("v1", INDEX_V1),
              lambda saved: verify_full(saved, "v1", INDEX_V1))
    if args.action == "verify-results-gate":
        verify_results_gate()
    print(f"B6 {args.action}: exit_code=0", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"B6 batch1x stopped: {type(error).__name__}; review B6 stage state/logs",
              file=sys.stderr)
        raise SystemExit(2) from error
