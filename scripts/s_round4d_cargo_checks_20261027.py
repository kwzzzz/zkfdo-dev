#!/usr/bin/env python3
"""Run required Rust checks with the 4c monitor, preserving the 4d S snapshots.

The 4c predeadline monitor has a 2 GB aggregate-output cap. Rebuilt S bundles
are moved temporarily outside Round4 and restored in a finally block. Only
owned 4d prepared bundle directories are moved; no older run or target is changed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "runs/s-round4-2026-10-27"
PREPARED_DIRS = [ROUND / f"round4d/prepared-s-{version}" for version in ("v2", "v3")]
TEMP = Path("/private/tmp/s_round4d_prepared_during_cargo_checks_v3_20261027")
MONITOR = ROOT / "scripts/s_round4d_monitor_20261027.py"
OUT = ROUND / "round4d/cargo-checks-v3"


def main() -> None:
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise ValueError("nice 19 required")
    if any(not source.is_dir() for source in PREPARED_DIRS) or TEMP.exists() or OUT.exists():
        raise ValueError("fresh cargo check workspace required")
    if any(source.stat().st_dev != TEMP.parent.stat().st_dev for source in PREPARED_DIRS):
        raise ValueError("bundle parking must stay on the same filesystem")
    OUT.mkdir(parents=True)
    reference = json.loads((ROOT / "runs/s-inspection-improve-2026-10-27/cargo-command-reference.json").read_text())
    skips = reference["skipped_J_tests"]
    if len(skips) != 24:
        raise ValueError("historical J test skip denominator changed")
    jobs = [
        ("4d-final-fmt-v3", 300, False, ["cargo", "fmt", "--all", "--", "--check"]),
        ("4d-final-clippy-v3", 1800, True,
         ["cargo", "clippy", "--offline", "-j", "1", "--all-targets", "--all-features", "--", "-D", "warnings"]),
        ("4d-final-cargo-test-v3", 1800, True,
         ["cargo", "test", "--offline", "-j", "1", "--", *(value for name in skips for value in ("--skip", name))]),
    ]
    rows = []
    TEMP.mkdir()
    parked = []
    try:
        for source in PREPARED_DIRS:
            destination = TEMP / source.name
            source.rename(destination)
            parked.append((source, destination))
        for label, timeout, cargo, command in jobs:
            argv = [sys.executable, "-B", str(MONITOR), "--label", label,
                    "--timeout", str(timeout), *(["--cargo"] if cargo else []), "--", *command]
            result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
            rows.append({"label": label, "argv": command, "returncode": result.returncode,
                         "stdout": result.stdout[-3000:], "stderr": result.stderr[-3000:]})
            print(json.dumps({"label": label, "returncode": result.returncode}), flush=True)
            if result.returncode:
                break
    finally:
        for source, destination in reversed(parked):
            if destination.exists() and not source.exists():
                destination.rename(source)
        if TEMP.exists() and not any(TEMP.iterdir()):
            TEMP.rmdir()
    (OUT / "summary.json").write_text(json.dumps({"schema": "s-round4d-cargo-checks-v3",
        "prepared_bundles_restored": all(source.is_dir() for source in PREPARED_DIRS) and not TEMP.exists(), "rows": rows,
        "all_passed": len(rows) == len(jobs) and all(r["returncode"] == 0 for r in rows)},
        ensure_ascii=False, indent=2) + "\n")
    if len(rows) != len(jobs) or any(r["returncode"] for r in rows):
        raise RuntimeError("Rust checks incomplete; snapshots restored")


if __name__ == "__main__":
    main()
