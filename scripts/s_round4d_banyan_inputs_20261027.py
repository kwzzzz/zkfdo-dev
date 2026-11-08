#!/usr/bin/env python3
"""Audit the permitted Banyan aggregate copy without opening judgement folders."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / "runs/s-round4-2026-10-27/inputs/aggregate-0001.json"
OUT = ROOT / "runs/s-round4-2026-10-27/round4d/banyan-input-audit-v1.json"
EXPECTED = "82b91a1c525167667a7ec80dc6555839a5e7af7ca1acad14db81e0607066c683"


def main() -> None:
    if OUT.exists():
        raise ValueError("new audit output required")
    raw = COPY.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise ValueError("permitted Banyan copy SHA differs")
    aggregate = json.loads(raw)
    rows = [r for r in aggregate["rows"] if r["engine"] == "v2.2" and r["method"] == "S"]
    by_revision = {r["revision"]: r["completed"] for r in rows}
    if by_revision != {"banyan-fixed": 24, "banyan-vulnerable": 108}:
        raise ValueError("Banyan replay denominator differs")
    joins = [r for r in aggregate["joins"] if r["engine"] == "v2.2"]
    if len(joins) != 2:
        raise ValueError("two v2.2 join references required")
    missing = [r["path"] for r in joins]
    requirements = [
        "132 individual v2.2 completed request JSON files and their result JSON files, with exact path/SHA bindings",
        "132 candidate files, base input files, component wrappers, entrypoints and full pinned source closures",
        "132 original fragment specs and pinned source closures for v2.3 view conversion",
        "per-request queue order, revision, recorded wall seconds, request/result SHA and input pins",
    ]
    result = {"schema": "s-round4d-banyan-input-audit-v1",
              "aggregate_copy": {"path": str(COPY), "sha256": EXPECTED},
              "v2_2_S_sample": by_revision,
              "exact_join_paths_in_judgement_folder_not_opened": missing,
              "required_per_request_material_absent_from_aggregate": requirements,
              "destination_for_mac_copy": str(COPY.parent),
              "may_execute_replay": False,
              "reason": "aggregate has counts and join pointers, not 132 request/result/input/source records"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"sample": by_revision, "missing_join_paths": len(missing),
                      "may_execute_replay": False, "output": str(OUT)}))


if __name__ == "__main__":
    main()
