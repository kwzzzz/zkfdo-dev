#!/usr/bin/env python3
"""Create the one-time B6 constructed-input index from reviewed, checked inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import n6_b6_batch1x_prepare as runner
import n6_j1_base_inputs as original


ROOT = Path(__file__).resolve().parents[1]
CONSTRUCTED = ROOT / "runs/n6-b6-2026-10-18.noindex/constructed-inputs"
MANIFEST = ROOT / "runs/n6-j3-2026-10-14.noindex/revision-manifest.json"
R1CS_MAP = ROOT / "runs/n6-b5-2026-10-17.noindex/b-r1cs-reference-v2.json"
FIRST_TABLE = CONSTRUCTED / "review-table.md"
SECOND_TABLE = CONSTRUCTED / "review-table-2.md"
FIRST_TABLE_SHA256 = "f5876f698b5952155b00d2461cd4e81c48892318edcc4f35cc4079e0388ef22d"
E_ZERO = "60271bae"
FINAL_PATHS = {
    "6079a717": "input.json",
    "b5b5cf5d": "docker-final/input.json",
    "340107e1": "docker-final/input.json",
    "4c221df7": "docker-final/input.json",
    "a8b2aa9c": "input.json",
    "76053f7f": "docker-final/input.json",
    "77e0f2db": "both-v3/input.json",
    "83cc0060": "input.json",
    "e71f158d": "input.json",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-table-2-sha256", required=True)
    args = parser.parse_args()
    output = CONSTRUCTED / "index.json"
    require(not output.exists(), "constructed index already exists; refusing overwrite")
    require(digest(FIRST_TABLE) == FIRST_TABLE_SHA256,
            "first reviewed table changed")
    require(digest(SECOND_TABLE) == args.review_table_2_sha256,
            "second reviewed table changed")
    table_hashes = {
        **runner.review_table_hashes(FIRST_TABLE),
        **runner.review_table_hashes(SECOND_TABLE),
    }
    require(set(table_hashes) == set(FINAL_PATHS), "review tables do not cover nine inputs")

    manifest = json.loads(MANIFEST.read_text())
    manifest_rows = {row["identifier"]: row for row in manifest["rows"]}
    require(len(manifest_rows) == 10 and len(manifest["rows"]) == 10,
            "official B manifest must have ten distinct revisions")
    reference = json.loads(R1CS_MAP.read_text())["revisions"]
    require(set(reference) == set(manifest_rows), "official R1CS map differs from manifest")
    by_short = {key[:8]: key for key in manifest_rows}
    require(len(by_short) == 10 and E_ZERO in by_short,
            "official revision prefix ambiguous or e_zero missing")
    require(set(by_short) == set(FINAL_PATHS) | {E_ZERO},
            "constructed target list differs from manifest")

    revisions = {}
    snarkjs_hash = None
    for short, relative in FINAL_PATHS.items():
        identifier = by_short[short]
        path = (CONSTRUCTED / short / relative).resolve()
        require(path.is_file() and path.is_relative_to(CONSTRUCTED.resolve()),
                f"final constructed input missing: {short}")
        input_sha = digest(path)
        require(table_hashes[short] == input_sha, f"reviewed input SHA differs: {short}")
        check_path = path.parent / "checks" / identifier / "check.json"
        check = json.loads(check_path.read_text())
        expected_r1cs = reference[identifier]["r1cs_sha256"]
        require(check.get("status") == "passed" and
                check.get("validation_reason") == "passed" and
                check.get("r1cs_sha256_match") is True and
                check.get("input_sha256") == input_sha and
                check.get("expected_r1cs_sha256") == expected_r1cs and
                check.get("compile", {}).get("r1cs_sha256") == expected_r1cs and
                all(key in check.get("validation_seconds", {}) for key in
                    ("witness_seconds", "rust_seconds", "snarkjs_seconds")),
                f"original honest checks incomplete: {short}")
        if snarkjs_hash is None:
            snarkjs_hash = check["snarkjs_sha256"]
        require(check["snarkjs_sha256"] == snarkjs_hash,
                "original snarkjs binary changed across revisions")
        generator = ROOT / f"scripts/n6_b6_construct_input_{short}.mjs"
        if not generator.is_file():
            generator = generator.with_suffix(".py")
        require(generator.is_file(), f"constructed generator missing: {short}")
        revision = manifest_rows[identifier]
        constraints = revision["constraints_from_queue"]
        require(isinstance(constraints, int) and constraints > 0,
                f"official constraint count invalid: {short}")
        revisions[identifier] = {
            "identifier": identifier,
            "status": "passed",
            "base_input_path": str(path),
            "base_input_sha256": input_sha,
            "constraints": constraints,
            "r1cs_sha256": expected_r1cs,
            "main_input_count": check["main_input_count"],
            "main_input_wire_count": check["main_input_wire_count"],
            "compile": check["compile"],
            "wall_seconds": check["wall_seconds"],
            "constructed_generator_path": str(generator),
            "constructed_generator_sha256": digest(generator),
            "constructed_check_path": str(check_path),
            "constructed_check_sha256": digest(check_path),
            "rust_checker_sha256": check["rust_checker_sha256"],
        }

    identifier = by_short[E_ZERO]
    constraints = manifest_rows[identifier]["constraints_from_queue"]
    require(isinstance(constraints, int) and constraints > 0,
            "strict e_zero constraint count invalid")
    revisions[identifier] = {
        "identifier": identifier,
        "status": "base_input_unavailable",
        "base_input_path": None,
        "base_input_sha256": None,
        "constraints": constraints,
        "r1cs_sha256": reference[identifier]["r1cs_sha256"],
        "constructed_attempted": False,
        "reason": "strict-layer e_zero already had an input; no new constructed input was made",
    }

    require(digest(original.CIRCOM) == original.CIRCOM_SHA256,
            "original Circom binary changed")
    snarkjs_name = shutil.which("snarkjs")
    require(snarkjs_name is not None, "snarkjs executable unavailable")
    snarkjs = Path(snarkjs_name).resolve()
    require(digest(snarkjs) == snarkjs_hash, "snarkjs binary changed")
    index = {
        "schema": "n6-j1-base-inputs-v1",
        "layer": "constructed",
        "scope": "B",
        "revision_manifest_path": str(MANIFEST),
        "revision_manifest_sha256": digest(MANIFEST),
        "r1cs_map_path": str(R1CS_MAP),
        "r1cs_map_sha256": digest(R1CS_MAP),
        "circom_sha256": original.CIRCOM_SHA256,
        "rust_checker_scope": "per_revision_check_record",
        "snarkjs_path": str(snarkjs),
        "snarkjs_sha256": snarkjs_hash,
        "review_table_path": str(FIRST_TABLE),
        "review_table_sha256": FIRST_TABLE_SHA256,
        "review_table_2_path": str(SECOND_TABLE),
        "review_table_2_sha256": args.review_table_2_sha256,
        "constructed_attempted_revision_count": 9,
        "revisions": revisions,
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(index, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"index_path": str(output), "index_sha256": digest(output),
                      "revision_count": len(revisions), "constructed_passed": 9},
                     sort_keys=True))


if __name__ == "__main__":
    main()
