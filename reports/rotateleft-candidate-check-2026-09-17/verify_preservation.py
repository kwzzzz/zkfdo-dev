#!/usr/bin/env python3
"""Confirm that all files captured before this check retain their bytes."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = EVIDENCE / "preservation-result.json"
    if output.exists():
        raise ValueError(f"refusing to overwrite {output}")
    baseline = json.loads((EVIDENCE / "preservation-before.json").read_text())
    missing = []
    changed = []
    for relative, expected in baseline["sha256"].items():
        path = ROOT / relative
        if not path.is_file():
            missing.append(relative)
        elif sha256(path) != expected:
            changed.append(relative)
    result = {
        "schema_version": 1,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline": "preservation-before.json",
        "baseline_entries": baseline["file_count"],
        "all_baseline_files_unchanged": not missing and not changed,
        "missing": missing,
        "changed": changed,
        "scope": baseline["scope"],
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
