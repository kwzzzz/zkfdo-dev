#!/usr/bin/env python3
"""Audit the A preparation evidence available for B6c V1/V2, without running J.

This deliberately reports V1/V2 as unproved. The fixed engines have no public
preparation-only entrypoint, and most successful A results do not record the
selected template file. A result audit cannot replace the required rerun of
the same preparation check on original and include-closed A sources.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_INDEX_SHA256 = "35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c"
ARMS = {
    "v1": (
        "runs/n6-j1-2026-10-09.noindex/request-index.json",
        "runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json",
    ),
    "v2.2": (
        "runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/request-index-v2.json",
        "runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/j-execute.noindex/state.json",
    ),
    "calibration_strict": (
        "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/prepared/strict-request-index.json",
        "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/strict-j/state.json",
    ),
    "calibration_constructed": (
        "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/prepared/constructed-request-index.json",
        "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/constructed-j/state.json",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def circom_count(root: Path) -> int:
    """Inspect one A index-named source root; never walk runs as a whole."""
    if not root.is_dir():
        raise ValueError(f"A source root missing: {root}")
    count = 0
    for directory, subdirectories, files in os.walk(root, followlinks=False):
        subdirectories[:] = [name for name in subdirectories
                             if not (Path(directory) / name).is_symlink()]
        count += sum(name.endswith(".circom") for name in files)
    return count


def source_category(root: Path, revision: str) -> str:
    if str(root).endswith(f"/units/{revision}"):
        return "unit_root_parent_of_project_and_preparation"
    if str(root).endswith(f"/units/{revision}/project"):
        return "project_root"
    if str(root).endswith("/project/circuits"):
        return "project_circuits_subdirectory"
    if str(root).endswith("/n6-a3-2026-10-08.noindex"):
        return "a3_run_root_parent_of_project_and_preparation"
    return "other"


def rewrite_identity(record: dict[str, Any], request: dict[str, Any]) -> tuple[str, str, str]:
    """Hash the recorded A source file, using the fixed engine's display rule."""
    relative = record.get("file")
    name = record.get("template")
    if not isinstance(relative, str) or not isinstance(name, str):
        raise ValueError("A rewrite template or file absent")
    libraries = request.get("library_paths")
    if not isinstance(libraries, list):
        raise ValueError("A request libraries absent")
    if relative.startswith("lib") and "/" in relative:
        prefix, rest = relative.split("/", 1)
        suffix = prefix[3:]
        if not suffix.isdigit() or int(suffix) >= len(libraries):
            raise ValueError("A rewrite library index invalid")
        source = (Path(libraries[int(suffix)]) / rest).resolve()
    else:
        source = (Path(request["source_root"]) / relative).resolve()
    if not source.is_file():
        raise ValueError(f"A recorded rewrite source missing: {source}")
    return name, relative, sha256_file(source)


def audit_arm(index_path: Path, state_path: Path) -> tuple[dict[str, Any], dict[int, tuple[Any, ...]]]:
    index = read_json(index_path)
    state = read_json(state_path)
    rows = index.get("requests")
    states = state.get("requests")
    if not isinstance(rows, list) or index.get("request_count") != len(rows):
        raise ValueError(f"A request index count invalid: {index_path}")
    if not isinstance(states, dict) or len(states) != len(rows):
        raise ValueError(f"A state request count invalid: {state_path}")
    if state.get("status") != "completed" or state.get("request_index_sha256") != sha256_file(index_path):
        raise ValueError(f"A state/index binding invalid: {state_path}")
    statuses: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    per_revision: dict[str, Counter[str]] = defaultdict(Counter)
    rewrite_rows: dict[int, tuple[Any, ...]] = {}
    for position, row in enumerate(rows):
        current = states.get(str(position))
        if not isinstance(row, dict) or not isinstance(current, dict):
            raise ValueError(f"A index/state row missing at {position}")
        revision = row.get("revision_id")
        if not isinstance(revision, str) or current.get("revision_id") != revision:
            raise ValueError(f"A revision mismatch at {position}")
        request_path = Path(row["request"])
        if sha256_file(request_path) != row.get("request_sha256"):
            raise ValueError(f"A request SHA-256 mismatch at {position}")
        request = read_json(request_path)
        status = current.get("status")
        statuses[str(status)] += 1
        per_revision[revision]["requests"] += 1
        if status == "preparation_failure":
            reason = current.get("preparation_failure") or row.get("preparation_failure")
            if not isinstance(reason, str):
                raise ValueError(f"A planned preparation reason missing at {position}")
            failures[reason] += 1
            per_revision[revision][f"failure:{reason}"] += 1
            if current.get("result_path") is not None:
                raise ValueError(f"A planned preparation failure has result at {position}")
            continue
        if status != "completed":
            raise ValueError(f"A request not complete at {position}: {status}")
        result_path = Path(current["result_path"])
        if sha256_file(result_path) != current.get("result_sha256"):
            raise ValueError(f"A result SHA-256 mismatch at {position}")
        result = read_json(result_path)
        preparation = result.get("preparation") or {}
        if preparation.get("status") != "ok":
            reason = preparation.get("reason") or "unknown"
            failures[reason] += 1
            per_revision[revision][f"failure:{reason}"] += 1
            continue
        per_revision[revision]["preparation_ok"] += 1
        rewrites = (result.get("component") or {}).get("rewritten_statements") or []
        if rewrites:
            if not isinstance(rewrites, list):
                raise ValueError(f"A rewrite metadata invalid at {position}")
            rewrite_rows[position] = tuple(sorted(rewrite_identity(record, request)
                                                  for record in rewrites))
    return ({"index_path": str(index_path), "index_sha256": sha256_file(index_path),
             "state_path": str(state_path), "state_sha256": sha256_file(state_path),
             "request_count": len(rows), "statuses": dict(sorted(statuses.items())),
             "preparation_failure_reasons": dict(sorted(failures.items())),
             "template_ambiguous": failures["template_ambiguous"],
             "successful_rows_with_rewrite_template_file": len(rewrite_rows),
             "successful_rows_without_rewrite_template_file":
                 sum(x["preparation_ok"] for x in per_revision.values()) - len(rewrite_rows),
             "request_sha_mismatch": 0,
             "result_sha_mismatch": 0,
             "by_revision": {key: dict(sorted(value.items()))
                             for key, value in sorted(per_revision.items())}}, rewrite_rows)


def audit() -> dict[str, Any]:
    original_index = ROOT / ARMS["v1"][0]
    if sha256_file(original_index) != ORIGINAL_INDEX_SHA256:
        raise ValueError("original A index SHA-256 differs")
    original = read_json(original_index)
    roots: dict[str, dict[str, Any]] = {}
    source_locations: Counter[str] = Counter()
    for row in original["requests"]:
        request = read_json(Path(row["request"]))
        path = Path(request["source_root"]).resolve()
        revision = row["revision_id"]
        key = f"{revision}|{path}"
        if key not in roots:
            roots[key] = {"revision_id": revision, "path": str(path),
                          "category": source_category(path, revision),
                          "circom_files": circom_count(path), "request_count": 0}
        roots[key]["request_count"] += 1
        source_locations[roots[key]["category"]] += 1
    arms: dict[str, dict[str, Any]] = {}
    observed_rewrites: dict[str, dict[int, tuple[Any, ...]]] = {}
    for label, (index_rel, state_rel) in ARMS.items():
        arms[label], observed_rewrites[label] = audit_arm(ROOT / index_rel, ROOT / state_rel)
    return {
        "schema": "n6-b6c-a-observed-preparation-audit-v1",
        "original_a_request_count": len(original["requests"]),
        "source_root_count": len({entry["path"] for entry in roots.values()}),
        "source_roots_by_revision": sorted(roots.values(), key=lambda x: (x["revision_id"], x["path"])),
        "source_location_request_counts": dict(sorted(source_locations.items())),
        "arms": arms,
        "observed_rewrite_identity_v1_v22_equal":
            observed_rewrites["v1"] == observed_rewrites["v2.2"],
        "observed_rewrite_identity_calibration_equal":
            observed_rewrites["calibration_strict"] == observed_rewrites["calibration_constructed"],
        "v1": {"status": "not_proven", "reason":
               "fixed engine has no preparation-only entrypoint; 2161 original A requests were planned failures without engine execution"},
        "v2": {"status": "not_proven", "reason":
               "include-closed A staging was not run; selected template identity is absent from 723 of 765 successful full-A results"},
        "equivalence_gate": "blocked",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    report = audit()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"output": str(output), "v1": report["v1"]["status"],
                      "v2": report["v2"]["status"],
                      "original_a_request_count": report["original_a_request_count"]},
                     sort_keys=True))
    return 0 if report["equivalence_gate"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
