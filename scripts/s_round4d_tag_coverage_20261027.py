#!/usr/bin/env python3
"""Account for every compiled tag wrapper against the rebuilt S bundle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "runs/s-round4-2026-10-27/round4d"
TAG = ROOT / "runs/s-tag-wrapper-2026-10-27"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    summary_path = TAG / "compile/summary.json"
    summary = json.loads(summary_path.read_text())
    planned_path = Path(summary["plan"])
    if sha(planned_path) != summary["plan_sha256"]:
        raise ValueError("tag plan SHA changed")
    planned = json.loads(planned_path.read_text())
    tags = {(r["unit"], r["label"]): r for r in planned["targets"]}
    bundle_path = ROUND / "prepared-s-v3/s-input-bundle.json"
    bundle = json.loads(bundle_path.read_text())
    covered = {}
    for job in bundle["jobs"][::3]:
        plan = json.loads(Path(job["prepared_plan"]["path"]).read_text())
        for target in plan["targets"]:
            label = target["definition"]["label"]
            key = job["revision"], label
            if key in tags:
                covered[key] = target["target_id"]
    rows = []
    for result in summary["results"]:
        key = result["unit"], result["label"]
        target = tags[key]
        if not result["compile_success"] or sha(Path(target["wrapper"]["path"])) != target["wrapper"]["sha256"]:
            raise ValueError("tag compile/wrapper evidence changed")
        status = "entered_S" if key in covered else "inspection_incomplete"
        if status == "entered_S" and not target["inspection_eligible"]:
            raise ValueError("inspection-incomplete tag target entered S")
        if status == "inspection_incomplete" and target["inspection_eligible"]:
            raise ValueError("eligible compiled tag wrapper omitted")
        rows.append({"revision": key[0], "label": key[1], "target_id": target["round2_target_id"],
                     "status": status, "inspection_eligible": target["inspection_eligible"],
                     "constraints": result["constraints"], "wrapper": target["wrapper"],
                     "compile_result": result["result"]})
    if len(rows) != 48 or sum(r["status"] == "entered_S" for r in rows) != 42:
        raise ValueError("48/42 tag denominator changed")
    output = ROUND / "tag-wrapper-coverage-v2.json"
    if output.exists():
        raise ValueError("new output required")
    output.write_text(json.dumps({"schema": "s-round4d-tag-wrapper-coverage-v2",
        "source_summary": {"path": str(summary_path), "sha256": sha(summary_path)},
        "S_bundle": {"path": str(bundle_path), "sha256": sha(bundle_path)},
        "compiled": 48, "entered_S": 42, "inspection_incomplete": 6, "rows": rows},
        ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"compiled": 48, "entered_S": 42, "inspection_incomplete": 6,
                      "output": str(output)}))


if __name__ == "__main__":
    main()
