#!/usr/bin/env python3
"""Compare B6b staged S-wrapper R1CS bytes with their pinned originals.

This reads request index and plan path/hash metadata only. It never opens
candidate inputs, witness files, J results, or hint workspaces. Compilation
uses the fixed lifting engine's component flags (mod.rs compile(), O0/wasm).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from n6_j1_requests import CIRCOM, CIRCOM_SHA, sha256_file


ROOT = Path(__file__).resolve().parents[1]
VOLUME = Path("/Volumes/zkfdo-jcache")
DEFAULT_STAGING = VOLUME / "n6-b6b-batch1x/source-staging"
DEFAULT_CACHE = VOLUME / "n6-b6b-batch1x/r1cs-compare"
DEFAULT_OUTPUT = ROOT / "runs/n6-b6b-2026-10-19.noindex/r1cs-comparison.json"
TOOL_TIMEOUT_SECONDS = 600  # src/candidate_review/lifting/mod.rs:40
MIN_FREE_BYTES = 40 * 1024**3  # scripts/run_n6_j1.py:30


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def pairs_from_index(index_path: Path, staging_root: Path,
                     expected_requests: int = 107,
                     expected_pairs: int = 17) -> tuple[Path, list[dict[str, Any]]]:
    """Bind all requests by path metadata, without reading request files."""
    index_path = index_path.resolve()
    staging_root = staging_root.resolve()
    index = read_json(index_path)
    rows = index.get("requests")
    require(index.get("status") == "verified" and
            index.get("request_count") == expected_requests and
            isinstance(rows, list) and len(rows) == expected_requests,
            "B6b final request index count/status differs")
    plan_path = Path(index["plan_index"]).resolve()
    require(plan_path.is_file() and sha256_file(plan_path) == index.get("plan_index_sha256"),
            "B6b request plan hash differs")
    plan = read_json(plan_path)
    planned = plan.get("requests")
    require(plan.get("status") == "awaiting_base_input" and
            plan.get("request_count") == expected_requests and
            isinstance(planned, list) and len(planned) == expected_requests,
            "B6b request plan count/status differs")
    plan_by_request = {row["request"]: row for row in planned}
    require(len(plan_by_request) == expected_requests, "B6b request plan paths repeated")
    pairs: dict[str, dict[str, Any]] = {}
    orders = set()
    for row in rows:
        require(isinstance(row, dict) and row.get("preparation_failure") is None,
                "B6b request not ready")
        request = row.get("request")
        require(request in plan_by_request, "B6b final request absent from plan")
        planned_row = plan_by_request[request]
        require(row.get("revision_id") == planned_row.get("revision_id") and
                row.get("queue_order") == planned_row.get("queue_order") and
                row.get("component_wrapper_sha256") ==
                planned_row.get("component_wrapper_sha256") and
                row.get("original_component_wrapper") ==
                planned_row.get("original_component_wrapper"),
                "B6b request source binding differs")
        order = row["queue_order"]
        require(isinstance(order, int) and order not in orders,
                "B6b queue order repeated or invalid")
        orders.add(order)
        source_root = Path(planned_row["source_root"]).resolve()
        original_wrapper = Path(planned_row["original_component_wrapper"]).resolve()
        staged_wrapper = Path(planned_row["component_wrapper"]).resolve()
        original_entrypoint = Path(planned_row["original_entrypoint"]).resolve()
        staged_entrypoint = Path(planned_row["entrypoint"]).resolve()
        libraries = [str(Path(path).resolve()) for path in planned_row["library_paths"]]
        require(source_root.is_relative_to(staging_root) and
                staged_wrapper.is_relative_to(source_root) and
                staged_entrypoint.is_relative_to(source_root) and
                all(Path(path).is_dir() for path in libraries),
                "B6b staged source or library path invalid")
        original_root = Path(os.path.commonpath(
            (original_wrapper.parent, original_entrypoint.parent))).resolve()
        require(original_wrapper.is_relative_to(original_root) and
                original_entrypoint.is_relative_to(original_root),
                "B6b original source root invalid")
        for source, expected in (
            (original_wrapper, row["component_wrapper_sha256"]),
            (staged_wrapper, row["component_wrapper_sha256"]),
            (original_entrypoint, row["entrypoint_sha256"]),
            (staged_entrypoint, row["entrypoint_sha256"]),
        ):
            require(source.is_file() and sha256_file(source) == expected,
                    f"B6b original/staged source hash differs: {source}")
        key = str(source_root)
        binding = {
            "revision_id": row["revision_id"], "source_root": key,
            "original_root": str(original_root),
            "original_wrapper": str(original_wrapper),
            "staged_wrapper": str(staged_wrapper),
            "original_entrypoint": str(original_entrypoint),
            "staged_entrypoint": str(staged_entrypoint),
            "library_paths": libraries,
            "wrapper_source_sha256": row["component_wrapper_sha256"],
            "entrypoint_source_sha256": row["entrypoint_sha256"],
        }
        if key not in pairs:
            pairs[key] = {**binding, "queue_orders": []}
        else:
            require(all(pairs[key][field] == value for field, value in binding.items()),
                    "B6b staged source pair has conflicting bindings")
        pairs[key]["queue_orders"].append(order)
    require(orders == set(range(expected_requests)), "B6b queue order incomplete")
    require(len(pairs) == expected_pairs, "B6b unique W/S source pair count differs")
    return plan_path, sorted(pairs.values(), key=lambda pair: min(pair["queue_orders"]))


def component_command(source: Path, output: Path, source_root: Path,
                      libraries: list[str], circom: Path = CIRCOM) -> list[str]:
    """Exact component compile flags from lifting/mod.rs:3542-3583."""
    command = [str(circom), str(source), "--r1cs", "--sym", "--prime", "bn128",
               "-o", str(output), "-l", str(source_root)]
    for library in libraries:
        command.extend(("-l", library))
    return command + ["--wasm", "--O0"]


def compile_component(source: Path, source_root: Path, libraries: list[str],
                      output: Path, circom: Path = CIRCOM,
                      timeout: int = TOOL_TIMEOUT_SECONDS) -> dict[str, Any]:
    require(not output.exists(), f"refuse to overwrite compile output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    require(shutil.disk_usage(output.parent).free >= MIN_FREE_BYTES,
            "external cache free space below J runner minimum")
    output.mkdir(parents=True, exist_ok=False)
    command = component_command(source, output, source_root, libraries, circom)
    started = time.monotonic()
    with (output / "compile.log").open("x") as log:
        try:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                       timeout=timeout, check=False)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("fixed engine Circom timeout") from error
    require(completed.returncode == 0, "fixed engine Circom compile failed")
    r1cs = output / f"{source.stem}.r1cs"
    require(r1cs.is_file(), "fixed engine Circom R1CS artifact missing")
    return {"r1cs_path": str(r1cs), "r1cs_sha256": sha256_file(r1cs),
            "wall_seconds": round(time.monotonic() - started, 3)}


def compare(index_path: Path, staging_root: Path, cache_root: Path,
            output_path: Path) -> dict[str, Any]:
    cache_root = cache_root.resolve()
    output_path = output_path.resolve()
    staging_root = staging_root.resolve()
    require(cache_root.is_relative_to(VOLUME) and os.path.ismount(VOLUME),
            "B6b external cache volume is not mounted")
    require(not cache_root.exists() and not output_path.exists(),
            "refuse to overwrite R1CS comparison output")
    require(not cache_root.is_relative_to(staging_root) and
            not staging_root.is_relative_to(cache_root),
            "R1CS compile cache overlaps source staging")
    require(CIRCOM.is_file() and sha256_file(CIRCOM) == CIRCOM_SHA,
            "fixed Circom binary SHA-256 differs")
    plan_path, pairs = pairs_from_index(index_path, staging_root)
    cache_root.parent.mkdir(parents=True, exist_ok=True)
    require(shutil.disk_usage(cache_root.parent).free >= MIN_FREE_BYTES,
            "external cache free space below J runner minimum")
    cache_root.mkdir(parents=True, exist_ok=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema": "n6-b6b-r1cs-comparison-v1", "status": "running",
        "request_count": 107, "source_pair_count": 17,
        "index": str(index_path.resolve()), "index_sha256": sha256_file(index_path),
        "plan": str(plan_path), "plan_sha256": sha256_file(plan_path),
        "circom": str(CIRCOM), "circom_sha256": CIRCOM_SHA,
        "source_staging_root": str(staging_root), "cache_root": str(cache_root),
        "component_compile_flags": ["--r1cs", "--sym", "--prime", "bn128",
                                    "-l source_root", "-l library_paths", "--wasm", "--O0"],
        "comparison_basis": "original wrapper newly compiled; original request has no S R1CS SHA",
        "entrypoint_check": "original/staged source SHA-256 only; W R1CS not compiled",
        "pairs": [],
    }
    try:
        for pair in pairs:
            key = Path(pair["source_root"]).name
            unit = {"revision_id": pair["revision_id"], "stage_key": key,
                    "queue_orders": pair["queue_orders"],
                    "wrapper_source_sha256": pair["wrapper_source_sha256"],
                    "entrypoint_source_sha256": pair["entrypoint_source_sha256"]}
            report["pairs"].append(unit)
            original = compile_component(
                Path(pair["original_wrapper"]), Path(pair["original_root"]),
                pair["library_paths"], cache_root / pair["revision_id"] / key / "original")
            unit["original"] = original
            staged = compile_component(
                Path(pair["staged_wrapper"]), Path(pair["source_root"]),
                pair["library_paths"], cache_root / pair["revision_id"] / key / "staged")
            unit["staged"] = staged
            unit["match"] = original["r1cs_sha256"] == staged["r1cs_sha256"]
            require(unit["match"], "original/staged S-wrapper R1CS SHA-256 differs")
        report["status"] = "matched"
    except (OSError, RuntimeError, ValueError) as error:
        report["status"] = "failed"
        report["failure_type"] = type(error).__name__
        report["failure_reason"] = str(error)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = compare(args.index, args.staging_root, args.cache_root, args.output)
    print(json.dumps({"status": report["status"], "request_count": report["request_count"],
                      "source_pair_count": report["source_pair_count"],
                      "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if report["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
