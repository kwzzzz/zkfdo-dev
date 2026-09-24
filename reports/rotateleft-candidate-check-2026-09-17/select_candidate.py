#!/usr/bin/env python3
"""Freeze the earliest preserved RotateLeft candidate without reading its values."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent
PILOT = ROOT / "runs/dev3-ranking-pilot-2026-09-15"
TARGET_ID = "sha256:76b7b3d1543e77a11a0d9652e29b1547a6b3783de118ac40d4c76702a5805616"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    selection_path = EVIDENCE / "selection.json"
    preservation_path = EVIDENCE / "preservation-before.json"
    require(not selection_path.exists(), f"refusing to overwrite {selection_path}")
    require(not preservation_path.exists(), f"refusing to overwrite {preservation_path}")

    inventory = []
    for outcome_path in sorted(PILOT.rglob("outcome.json")):
        outcome = json.loads(outcome_path.read_text())
        runs = {run["result"]["run_id"]: run for run in outcome["scheduler"]["runs"]}
        for candidate in outcome["counterexample_candidates"]:
            if candidate["target_id"] != TARGET_ID:
                continue
            run = runs[candidate["run_id"]]
            preserved = Path(candidate["preserved_path"])
            require(preserved.is_file(), f"candidate missing: {preserved}")
            require(sha256(preserved) == candidate["sha256"], f"candidate hash mismatch: {preserved}")
            inventory.append({
                "started_at": run["result"]["started_at"],
                "run_id": candidate["run_id"],
                "strategy": outcome["strategy"],
                "outcome_path": str(outcome_path),
                "candidate_path": str(preserved),
                "candidate_sha256": candidate["sha256"],
                "classification": candidate["classification"],
                "candidate_values_read_during_selection": False,
            })
    inventory.sort(key=lambda item: (item["started_at"], item["run_id"], item["candidate_path"]))
    require(len(inventory) == 21, f"unexpected RotateLeft candidate count: {len(inventory)}")

    selected = inventory[0]
    selection = {
        "schema_version": 1,
        "selected_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_policy": "Earliest runner started_at, then run_id, then preserved path; fixed before parsing candidate values.",
        "ranking_or_expected_validity_used": False,
        "target_id": TARGET_ID,
        "inventory_count": len(inventory),
        "inventory": inventory,
        "selected": selected,
    }

    excluded = EVIDENCE.resolve()
    excluded_parts = {".git", "target", "node_modules", "isolated-rerun"}
    hashes = {}
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if (not path.is_file() or path.resolve().is_relative_to(excluded)
                or excluded_parts.intersection(relative.parts)):
            continue
        hashes[str(relative)] = sha256(path)
    preservation = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "All pre-existing repository files outside this new evidence directory",
        "file_count": len(hashes),
        "sha256": hashes,
    }

    selection_path.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    preservation_path.write_text(json.dumps(preservation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"inventory_count": len(inventory), "selected": selected,
                      "preservation_file_count": len(hashes)}, indent=2))


if __name__ == "__main__":
    main()
