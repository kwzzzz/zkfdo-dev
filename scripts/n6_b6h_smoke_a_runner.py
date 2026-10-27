#!/usr/bin/env python3
"""Run the B6h runner's actual execution loop on three frozen A requests.

CLI flags match the B execute command. Only B-specific fixed evidence gates
and fixed output roots are replaced in memory. No B request/result is opened.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SMOKE_ROOTS = frozenset({
    Path("/Volumes/zkfdo-jcache/n6-b6h-smoke"),
    Path("/Volumes/zkfdo-jcache/n6-b6h-smoke-final"),
})

import n6_b6h_build_a_smoke as fixture  # noqa: E402
import n6_b6h_j_runner as b6h  # noqa: E402


LEAD1 = "9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e"
LEAD2 = "4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"JSON object expected: {path}")
    return value


def a_configure(engine: str, index_path: Path, index_sha: str,
                static_path: Path, static_sha: str,
                lead1: str, lead2: str) -> dict:
    """Check an exact A subset, then call the normal frozen index validator."""
    require(engine in fixture.ORIGINS, "A smoke engine invalid")
    require(lead1 == LEAD1 and lead2 == LEAD2,
            "A smoke lead-flag values differ from B CLI")
    require(index_path.is_absolute() and index_path.name == f"request-index-{engine}.json",
            "A smoke index path invalid")
    require(static_path == index_path.parent / f"static-preflight-{engine}.json",
            "A smoke static preflight path invalid")
    require(digest(index_path) == index_sha and digest(static_path) == static_sha,
            "A smoke index/static SHA mismatch")
    original_path = fixture.ORIGINS[engine]
    original_sha = fixture.EXPECTED_ORIGIN_SHA[engine]
    require(digest(original_path) == original_sha, "original A index SHA differs")
    original = read(original_path)
    index = read(index_path)
    static = read(static_path)
    require(static == {
        "kind": "n6_b6h_a_smoke_static_preflight",
        "status": "passed",
        "engine": engine,
        "request_count": 3,
        "index_path": str(index_path),
        "index_sha256": index_sha,
        "original_index_path": str(original_path),
        "original_index_sha256": original_sha,
        "original_queue_orders": list(fixture.ORDERS),
        "request_sha256": list(fixture.EXPECTED_REQUEST_SHA),
    }, "A smoke static preflight contents differ")
    original_rows = original["requests"]
    expected_rows = deepcopy([original_rows[n] for n in fixture.ORDERS])
    for order, row in enumerate(expected_rows):
        row["queue_order"] = order
    require(index.get("requests") == expected_rows and index.get("request_count") == 3 and
            index.get("preparation_counts") == {"ready": 3},
            "A smoke index rows differ from frozen A requests")
    allowed_changes = {"requests", "request_count", "preparation_counts",
                       "inventory", "inventory_sha256"}
    require({k: v for k, v in index.items() if k not in allowed_changes} ==
            {k: v for k, v in original.items() if k not in allowed_changes},
            "A smoke index changed a frozen metadata field")
    original_inventory_path = Path(original["inventory"])
    require(digest(original_inventory_path) == original["inventory_sha256"],
            "frozen A inventory SHA differs")
    original_inventory = read(original_inventory_path)
    inventory_path = Path(index["inventory"])
    require(inventory_path == index_path.parent / f"inventory-{engine}.json" and
            digest(inventory_path) == index["inventory_sha256"],
            "A smoke inventory path/SHA invalid")
    inventory = read(inventory_path)
    selected = {row["candidate_sha256"] for row in expected_rows}
    expected_inventory_rows = [row for row in original_inventory["rows"]
                               if row["candidate_sha256"] in selected]
    require(len(expected_inventory_rows) == 3 and
            {row["candidate_sha256"]: row for row in inventory["rows"]} ==
            {row["candidate_sha256"]: row for row in expected_inventory_rows},
            "A smoke inventory rows differ from frozen A inventory")
    b6h.runner.ENGINE = b6h.ENGINE_V1 if engine == "v1" else b6h.ENGINE_V22
    b6h.runner.ENGINE_SHA256 = (
        b6h.ENGINE_V1_SHA if engine == "v1" else b6h.ENGINE_V22_SHA)
    return b6h.runner.validate_index(index_path, index_sha)


def install_a_profile(args: argparse.Namespace) -> None:
    smoke_root = args.output.parent
    require(smoke_root in SMOKE_ROOTS, "A smoke output must use a locked SSD folder")
    require(args.output == smoke_root / f"full-{args.engine}.noindex",
            "A smoke output path differs")
    require(args.index.parent == smoke_root / "fixtures-97-102-115",
            "A smoke fixtures must be inside smoke root")
    require(args.cache_root == smoke_root / "cache" / f"full-{args.engine}" and
            args.workspace_root == smoke_root / "hint-workspaces" and
            args.instance_root == smoke_root / "instance-stores",
            "A smoke external paths differ")
    b6h.ROOT = REPO
    b6h.OUT = smoke_root / "fixtures-97-102-115"
    b6h.RUN_OUT = smoke_root
    b6h.EXTERNAL = smoke_root
    b6h.CACHE = smoke_root / "cache"
    b6h.WORKSPACES = args.workspace_root
    b6h.STORES = args.instance_root
    b6h.RECORD_OUT = smoke_root / "cleanup-records"
    # This A-only three-request check runs entirely on the smoke SSD folder.
    # Keep the same dynamic 2x observed-peak guard with a smaller fixed floor.
    b6h.cleanup.SSD_MIN_FREE_BYTES = 64 * 1024**2
    b6h.cleanup.INTERNAL_MIN_FREE_BYTES = 64 * 1024**2
    b6h.OBSERVED_REQUEST_PEAK_BYTES = args.observed_request_peak_bytes
    b6h.OTHER_ENGINE_CACHE_GROWTH_BYTES = 0
    b6h.configure = a_configure
    b6h.verify_both_pilots = lambda: None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("v1", "v2.2"), required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--static-preflight", type=Path, required=True)
    parser.add_argument("--static-preflight-sha256", required=True)
    parser.add_argument("--first-lead-review-sha256", required=True)
    parser.add_argument("--second-lead-review-sha256", required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--instance-root", type=Path, required=True)
    parser.add_argument("--observed-request-peak-bytes", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--action", choices=("validate-only", "execute-all", "execute-one", "reconcile-cleanup"), required=True)
    parser.add_argument("--queue-order", type=int)
    args = parser.parse_args()
    try:
        stress_peak = 400 * 1024**3
        require(args.observed_request_peak_bytes == 1_073_741_824 or
                (args.output.parent == Path("/Volumes/zkfdo-jcache/n6-b6h-smoke-final") and
                 args.action == "execute-one" and args.queue_order is not None and
                 args.observed_request_peak_bytes == stress_peak),
                "A smoke observed peak is outside the fixed or space-gate profile")
        install_a_profile(args)
        return b6h.main(sys.argv[1:])
    except (OSError, ValueError, b6h.runner.RunnerError) as error:
        print(f"A smoke refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
