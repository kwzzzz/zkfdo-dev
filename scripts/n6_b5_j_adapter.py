#!/usr/bin/env python3
"""Bind B's completed mem20 retry and the selected frozen J binary.

This adapter only supplies the completion record and engine path to the
existing request generator and validation runner, and to B5's format-only
pilot. It does not change request rows, source checks, selection, or verdict
logic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_STATE = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json"
ORIGINAL_SHA = "5160fda628e9a920d8a0f7717b31fc05ad88326a371780908803d187b2ddfc7c"
RETRY_STATE = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-retry.noindex/state.json"
RETRY_SHA = "70043643377bc489760b092bf96881747fc5bf5a318648ee69c236fd25a9a16a"
ENGINE_V1 = ROOT / "runs/l07-2026-10-05/tools/zkfDO"
ENGINE_V1_SHA = "e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed"
ENGINE_V22 = ROOT / "runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2"
ENGINE_V22_SHA = "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_mem20() -> None:
    if sha256(ORIGINAL_STATE) != ORIGINAL_SHA:
        raise ValueError("original mem20 state hash changed")
    if json.loads(ORIGINAL_STATE.read_text()).get("status") != "stopped_between_units":
        raise ValueError("original mem20 state status changed")
    if sha256(RETRY_STATE) != RETRY_SHA:
        raise ValueError("mem20 retry completion hash changed")
    if json.loads(RETRY_STATE.read_text()).get("status") != "completed":
        raise ValueError("mem20 retry is not completed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("requests", "validate", "pilot"), required=True)
    parser.add_argument("--engine", choices=("v1", "v2.2"), default="v1")
    args, rest = parser.parse_known_args(argv)
    verify_mem20()
    import run_n6_j1 as runner

    if runner.ENGINE != ENGINE_V1 or runner.ENGINE_SHA256 != ENGINE_V1_SHA:
        raise ValueError("v1 runner lock differs from N5")
    runner.checked_sha(ENGINE_V1, ENGINE_V1_SHA, "v1 J binary")
    if args.engine == "v2.2":
        runner.checked_sha(ENGINE_V22, ENGINE_V22_SHA, "v2.2 J binary")
        runner.ENGINE = ENGINE_V22
        runner.ENGINE_SHA256 = ENGINE_V22_SHA
    sys.argv = [sys.argv[0], *rest]
    if args.stage == "requests":
        if args.engine != "v1":
            raise ValueError("request generator emits the v1 index before the v2.2 overlay")
        import n6_j3_b_requests as requests

        requests.MEM20_STATE = RETRY_STATE
        requests.main()
        return 0
    if args.stage == "validate":
        import run_n6_j3_b as b_runner

        b_runner.MEM20_STATE = RETRY_STATE
        return b_runner.main()
    import n6_b5_format_pilot as b_pilot

    return b_pilot.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"B5 J adapter failed: {error}", file=sys.stderr)
        raise SystemExit(2) from error
