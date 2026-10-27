#!/usr/bin/env python3
"""Use the B6h pair scheduler on a locked, three-request A fixture.

The two stress modes keep the same pair CLI flags: an A-only clock override
tests the cutoff, and a larger peak bound tests the real SSD guard. Neither
mode changes an engine or its request, candidate, or judgement rules.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import n6_b6h_build_a_smoke as fixture
import n6_b6h_j_runner as b6h
import n6_b6h_pair_runner as pair
import n6_b6h_smoke_a_runner as a_runner


REPO = Path(__file__).resolve().parents[1]
ROOT = Path("/Volumes/zkfdo-jcache/n6-b6h-smoke-final")
FIXTURES = ROOT / "fixtures-97-102-115"
NORMAL_PEAK = 1_073_741_824
SPACE_PEAK = 400 * 1024**3
AFTER_CUTOFF_ENV = "N6_B6H_A_CLOCK_AFTER_CUTOFF"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def configure(args: argparse.Namespace) -> None:
    require(args.observed_request_peak_bytes in {NORMAL_PEAK, SPACE_PEAK},
            "A pair peak is outside the locked profiles")
    if args.observed_request_peak_bytes == SPACE_PEAK:
        require(args.action == "execute-pairs", "space profile requires execution")
    clock_override = os.environ.get(AFTER_CUTOFF_ENV)
    require(clock_override in {None, "1"}, "A pair clock override invalid")
    if clock_override == "1":
        require(args.action == "execute-pairs" and
                args.observed_request_peak_bytes == NORMAL_PEAK,
                "A pair cutoff test requires ordinary pending work")
        pair.utc_now = lambda: datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)

    manifest_path = FIXTURES / "fixture-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("schema") == "n6-b6h-a-smoke-fixtures-v1" and
            manifest.get("original_queue_orders") == list(fixture.ORDERS),
            "A pair fixture manifest differs")
    b6h.ROOT = REPO
    for engine, index_sha, static_sha in (
        ("v1", args.v1_index_sha256, args.v1_static_preflight_sha256),
        ("v2.2", args.v2_2_index_sha256, args.v2_2_static_preflight_sha256),
    ):
        item = manifest["engines"][engine]
        require(item["index_path"] == str(FIXTURES / f"request-index-{engine}.json") and
                item["index_sha256"] == index_sha and
                item["static_preflight_path"] == str(FIXTURES / f"static-preflight-{engine}.json") and
                item["static_preflight_sha256"] == static_sha,
                f"A pair {engine} fixture CLI SHA/path differs")
        a_runner.a_configure(
            engine, Path(item["index_path"]), index_sha,
            Path(item["static_preflight_path"]), static_sha,
            args.first_lead_review_sha256, args.second_lead_review_sha256)

    b6h.OUT = FIXTURES
    b6h.RUN_OUT = ROOT
    b6h.EXTERNAL = ROOT
    b6h.CACHE = ROOT / "cache"
    b6h.WORKSPACES = ROOT / "hint-workspaces"
    b6h.STORES = ROOT / "instance-stores"
    b6h.RECORD_OUT = ROOT / "cleanup-records"
    b6h.OBSERVED_REQUEST_PEAK_BYTES = args.observed_request_peak_bytes
    b6h.OTHER_ENGINE_CACHE_GROWTH_BYTES = 0
    pair.REQUEST_COUNT = 3
    pair.PAIR_ROOT = ROOT
    pair.ORDER_PATH = ROOT / "pair-order-v1.json"
    pair.STATE_PATH = ROOT / "pair-state-v1.json"

    original_command = pair.engine_command

    def a_command(command_args: argparse.Namespace, engine: str) -> list[str]:
        command = original_command(command_args, engine)
        require(Path(command[1]).name == "n6_b6h_j_runner.py",
                "A pair delegated command changed")
        command[1] = str(REPO / "scripts/n6_b6h_smoke_a_runner.py")
        static_index = command.index("--static-preflight") + 1
        command[static_index] = str(FIXTURES / f"static-preflight-{engine}.json")
        return command

    pair.engine_command = a_command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("prepare-order", "execute-pairs"), required=True)
    parser.add_argument("--v1-index-sha256", required=True)
    parser.add_argument("--v2-2-index-sha256", required=True)
    parser.add_argument("--v1-static-preflight-sha256", required=True)
    parser.add_argument("--v2-2-static-preflight-sha256", required=True)
    parser.add_argument("--first-lead-review-sha256", required=True)
    parser.add_argument("--second-lead-review-sha256", required=True)
    parser.add_argument("--observed-request-peak-bytes", type=int, required=True)
    parser.add_argument("--no-new-request-after", required=True)
    parser.add_argument("--order-sha256")
    args = parser.parse_args()
    try:
        configure(args)
        return pair.main(sys.argv[1:])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"A pair smoke refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
