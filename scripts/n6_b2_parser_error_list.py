#!/usr/bin/env python3
"""Extract error codes and target IDs from the completed high-version B probes."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-b2-2026-10-09.noindex"
LEDGERS = (
    RUN / "parser-probe-high-version-W.jsonl",
    RUN / "parser-probe-high-version-S.jsonl",
    RUN / "parser-probe-high-version-S-continuation-2.jsonl",
)
OUTPUT = RUN / "parser-high-version-p-errors.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    rows = []
    manifests = []
    for path in LEDGERS:
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        if not lines or lines[0]["kind"] != "header":
            raise ValueError(f"probe header missing: {path}")
        rows.extend(lines[1:])
        manifests.append({"path": path.relative_to(ROOT).as_posix(),
                          "sha256": sha256(path), "completed_count": len(lines) - 1})
    whole = [row for row in rows if row["method"] == "W"]
    split = [row for row in rows if row["method"] == "S"]
    if (len(whole) != 1 or len(split) != 305
            or {row["target_index"] for row in split} != set(range(305))):
        raise ValueError("high-version W/S probe denominator differs")
    if not all(row["process_group_empty"] and row["temporary_workspace_deleted"]
               for row in rows):
        raise ValueError("probe cleanup is incomplete")
    errors = [
        {"method": row["method"], "target_index": row["target_index"],
         "target_id": row["target_id"], "error_codes": row["error_codes"],
         "entrypoint_sha256": row["entrypoint_sha256"],
         "spec_sha256": row["spec_sha256"]}
        for row in rows if row["status"] == "parser_error"
    ]
    result = {"schema_version": 1, "identifier": whole[0]["identifier"],
              "status": "complete", "ledger_manifests": manifests,
              "whole_count": len(whole), "split_count": len(split),
              "status_counts": {f"{method}:{status}": count for (method, status), count
                                in sorted(Counter((row["method"], row["status"])
                                                  for row in rows).items())},
              "error_count": len(errors), "errors": errors}
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"error_count": len(errors),
                      "codes": dict(Counter(code for row in errors
                                            for code in row["error_codes"])),
                      "sha256": sha256(OUTPUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
