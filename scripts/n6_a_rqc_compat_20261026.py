#!/usr/bin/env python3
"""Version-pinned metadata rescoring adapter; original scorer stays unchanged."""
import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
import n6_a_rqc_input_audit_20261026 as audit

PROTOCOL_SHA = "18bc531d0c863515a2fc7abc6411187161dd5b98c9fe5e481863ba075afb2ddd"
SCORER_SHA = "3344db9d8b1f18577e6e7fb5f80fd729331e05f35f0ae0510ec91960af27a20f"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", default="auto")
    p.add_argument("--engine", choices=("v1", "v2.2"), default="v2.2")
    p.add_argument("--output-root", type=Path, required=True)
    args = p.parse_args()
    audit.guard()
    for path, expected in ((Path(audit.scorer.__file__), SCORER_SHA),
                           (audit.ROOT / "docs/n5_evaluation_protocol_v1_2026-10-06.md", PROTOCOL_SHA)):
        audit.require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                      "compatibility version pin differs: " + str(path))
    # Only this process accepts the separately identified protocol version.
    # All original classification functions, engine and mapping pins are reused.
    audit.scorer.PROTOCOL_SHA = PROTOCOL_SHA
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    folder = args.output_root / (args.engine + "-" + stamp)
    sys.argv = [str(Path(audit.__file__)), "--state", args.state, "--engine", args.engine,
                "--out-dir", str(folder), "--joined-only"]
    return audit.main()


if __name__ == "__main__":
    raise SystemExit(main())
