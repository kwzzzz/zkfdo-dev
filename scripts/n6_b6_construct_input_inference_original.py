#!/usr/bin/env python3
# Models an active 256-validator scoring batch with ordinary nonzero scores,
# competition, proof sizes, and response times inside each validator's range.
"""Construct an independent input for the development IncentiveMechansim main."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def offset(seed: str, slot: int, label: str, span: int) -> int:
    digest = hashlib.sha256(f"{seed}:{slot}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % span


def construct(seed: str) -> dict[str, object]:
    count = 256
    minimum = [400 + offset(seed, i, "minimum", 201) for i in range(count)]
    maximum = [minimum[i] + 1500 + offset(seed, i, "window", 501) for i in range(count)]
    response = [minimum[i] + 500 + offset(seed, i, "response", 501) for i in range(count)]
    return {
        "RATE_OF_DECAY": 5_000_000,
        "RATE_OF_RECOVERY": 8_000_000,
        "FLATTENING_COEFFICIENT": 1_000_000,
        "PROOF_SIZE_THRESHOLD": 1_000_000,
        "PROOF_SIZE_WEIGHT": 15_000_000,
        "RESPONSE_TIME_WEIGHT": 30_000_000,
        "MAXIMUM_RESPONSE_TIME_DECIMAL": 100_000_000,
        "COMPETITION_WEIGHT": 20_000_000,
        "maximum_score": [100_000_000] * count,
        "previous_score": [45_000_000 + offset(seed, i, "score", 10_000_001) for i in range(count)],
        "verified": [1] * count,
        "proof_size": [750_000 + offset(seed, i, "proof_size", 500_001) for i in range(count)],
        "response_time": response,
        "competition": [20_000_000 + offset(seed, i, "competition", 30_000_001) for i in range(count)],
        "maximum_response_time": maximum,
        "minimum_response_time": minimum,
        "block_number": [20_000_000 + i for i in range(count)],
        "validator_uid": [i + 1 for i in range(count)],
        "miner_uid": [10_000 + i for i in range(count)],
        "scaling": 100_000_000,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default="20261018-a-inference-original")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(construct(args.seed), sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
