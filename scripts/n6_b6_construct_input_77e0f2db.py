#!/usr/bin/env python3
"""Construct an active, single-sided LIQ_ADD from the repository's committed test vector.

The pinned test vector itself supplies all required division quotients and commitments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/project/circuits/test/vectors/private_liquidity/add_liquidity_in_range.json"
FIXTURE_SHA256 = "745a96006d1c479fa837a5b416dd95070f4f066576ec79f9bdd426a0eb2fe02d"
SEED = "n6-b6-77e0f2db-committed-fixture-v2"
SEED_FIXTURE_SHA256 = "5a0b76ba1aa4592ffc1e724210c2dc2c9b893493c3a70b887f43ee75bbfeca1e"
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", default=SEED)
    args = parser.parse_args()
    fixture_bytes = FIXTURE.read_bytes()
    assert hashlib.sha256(fixture_bytes).hexdigest() == FIXTURE_SHA256
    assert hashlib.sha256(args.seed.encode() + b":" + fixture_bytes).hexdigest() == SEED_FIXTURE_SHA256
    source = json.loads(FIXTURE.read_text())
    values = source["input"]
    assert values["token0_note_count"] == "1" and values["token1_note_count"] == "0"
    assert int(values["liquidity_delta"]) > 0 and int(values["token0_note_amount"][0]) > 0
    assert values["tag"] == str(0x4C49515F414444)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(values, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
