#!/usr/bin/env python3
"""Build read-only-source A fixtures for the B6h runner smoke.

The three original A requests remain untouched. Only index queue numbers and
the index's inventory reference change; the pinned candidate/request digests,
engine, circom, source trees, and base input index remain the originals.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ORDERS = (97, 102, 115)
ORIGINS = {
    "v1": REPO / "runs/n6-j1-2026-10-09.noindex/request-index.json",
    "v2.2": REPO / "runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/request-index-v2.json",
}
EXPECTED_ORIGIN_SHA = {
    "v1": "35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c",
    "v2.2": "d1102d837e5d78116cb44a2b67f5a9796f57bbc2a6733d712205eb1d528ceed8",
}
EXPECTED_REQUEST_SHA = (
    "ceef0a2982874923a725b077a153a5c06698afa9fd9d57fd1778dd9c20264e6d",
    "450a2ae00fd5990c63fe68145fda9dc39d8f86b04c6e82ea79c253d21f6b8b12",
    "81c4bf6321490150eed904104fb78b53757c5ffa37dbba9ec201281f97a133c4",
)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"JSON object expected: {path}")
    return data


def write_new(path: Path, data: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(payload)
    return sha256(payload).hexdigest()


def build(out: Path) -> dict:
    if not out.is_absolute():
        raise ValueError("fixture directory must be absolute")
    manifest = {"schema": "n6-b6h-a-smoke-fixtures-v1", "original_queue_orders": list(ORDERS),
                "engines": {}}
    for engine, origin_path in ORIGINS.items():
        origin_sha = digest(origin_path)
        if origin_sha != EXPECTED_ORIGIN_SHA[engine]:
            raise ValueError(f"frozen A index SHA differs: {engine}")
        origin = read(origin_path)
        original_rows = origin["requests"]
        if any(original_rows[n]["queue_order"] != n for n in ORDERS):
            raise ValueError(f"original A queue changed: {engine}")
        rows = deepcopy([original_rows[n] for n in ORDERS])
        if tuple(row["request_sha256"] for row in rows) != EXPECTED_REQUEST_SHA:
            raise ValueError(f"selected A request SHA differs: {engine}")
        if len({row["candidate_sha256"] for row in rows}) != 3 or any(
            row["scope"] != "main" or row["revision_id"] != revision
            or row["method"] != "S" or row["preparation_failure"] is not None
            for row, revision in zip(rows, (
                "inference-c9221e8d", "inference-c9221e8d",
                "inference-c79f42ee"))
        ):
            raise ValueError(f"selected A request metadata differs: {engine}")
        for order, row in enumerate(rows):
            row["queue_order"] = order
        inventory_path = Path(origin["inventory"])
        if digest(inventory_path) != origin["inventory_sha256"]:
            raise ValueError(f"original A inventory SHA differs: {engine}")
        inventory = read(inventory_path)
        by_sha = {row["candidate_sha256"]: row for row in inventory["rows"]}
        if len(by_sha) != len(inventory["rows"]):
            raise ValueError("original A inventory has duplicate candidate SHAs")
        inventory_rows = [deepcopy(by_sha[row["candidate_sha256"]]) for row in rows]
        ident_counts = Counter(row["identifier"] for row in inventory_rows)
        fixture_inventory = deepcopy(inventory)
        fixture_inventory["rows"] = inventory_rows
        fixture_inventory["candidate_count"] = 3
        fixture_inventory["counts"] = {"main": {"W": 0, "S": 3},
                                       "mem20": {"W": 0, "S": 0}}
        fixture_inventory["by_identifier"] = {"main": dict(ident_counts), "mem20": {}}
        inventory_out = out / f"inventory-{engine}.json"
        inventory_sha = write_new(inventory_out, fixture_inventory)
        fixture_index = deepcopy(origin)
        fixture_index["requests"] = rows
        fixture_index["request_count"] = 3
        fixture_index["preparation_counts"] = {"ready": 3}
        fixture_index["inventory"] = str(inventory_out)
        fixture_index["inventory_sha256"] = inventory_sha
        index_out = out / f"request-index-{engine}.json"
        index_sha = write_new(index_out, fixture_index)
        static_out = out / f"static-preflight-{engine}.json"
        static_sha = write_new(static_out, {
            "kind": "n6_b6h_a_smoke_static_preflight",
            "status": "passed",
            "engine": engine,
            "request_count": 3,
            "index_path": str(index_out),
            "index_sha256": index_sha,
            "original_index_path": str(origin_path),
            "original_index_sha256": origin_sha,
            "original_queue_orders": list(ORDERS),
            "request_sha256": list(EXPECTED_REQUEST_SHA),
        })
        manifest["engines"][engine] = {
            "original_index_path": str(origin_path),
            "original_index_sha256": origin_sha,
            "index_path": str(index_out),
            "index_sha256": index_sha,
            "inventory_path": str(inventory_out),
            "inventory_sha256": inventory_sha,
            "static_preflight_path": str(static_out),
            "static_preflight_sha256": static_sha,
        }
    write_new(out / "fixture-manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.out), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
