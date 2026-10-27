#!/usr/bin/env python3
# Models a funded account spending a nonzero amount while retaining funds;
# the salts are deterministic test values and no real key or balance is used.
"""Construct an independent ordinary Spend input from source examples."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def offset(seed: str, label: str, span: int) -> int:
    digest = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % span


def construct(seed: str) -> dict[str, int]:
    return {
        "balance": 1000 + offset(seed, "balance", 501),
        "salt": 123456 + offset(seed, "salt", 10000),
        "withdrawnBalance": 200 + offset(seed, "withdrawal", 101),
        "remainingCoinSalt": 234567 + offset(seed, "remaining-salt", 10000),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default="20261018-a-spend")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(construct(args.seed), sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
