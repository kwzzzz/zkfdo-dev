#!/usr/bin/env python3
"""Join preserved A-Q preparation failures to fresh read-only asset checks."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import zkfdo_preflight_v1 as preflight

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "configs/preparation_assets_aq_v1.json"
BASE_INPUTS = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
REVISIONS = ROOT / "runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json"
SUMMARY = ROOT / "runs/n6-j1-2026-10-09.noindex/j-summary-final.json"
PINS = {
    BASE_INPUTS: "18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508",
    REVISIONS: "f059fe7d6aa21234168b7867537f069ec980c45c2c025184cbc12e169f687441",
    SUMMARY: "915b15c2b99fa900006350bf8bfa483f092d51812563111981bd3b1cbafda653",
}


def run_audit(profile_path=PROFILE):
    inputs = {}
    for path, expected in PINS.items():
        if preflight.sha256(path) != expected:
            raise ValueError("preserved audit source SHA256 differs: " + str(path))
        inputs[path] = json.loads(path.read_text())
    catalog = json.loads(profile_path.read_text())
    profile_sha = preflight.sha256(profile_path)
    revisions = {row["identifier"]: row for row in inputs[REVISIONS]["rows"]}
    historical = inputs[BASE_INPUTS]["revisions"]
    candidates = inputs[SUMMARY]["candidates"]
    counts = Counter(row["revision_id"] for row in candidates
                     if row["revision_id"].startswith("aq-") and row.get("scope") == "main"
                     and row.get("method") == "S" and row.get("status") == "preparation_failure"
                     and row.get("preparation_failure") == "base_input_unavailable")
    if len(counts) != 13 or sum(counts.values()) != 261:
        raise ValueError("preserved A-Q failure population differs from 13 revisions / 261 requests")
    if set(catalog["revisions"]) != set(counts):
        raise ValueError("profile revision population differs from preserved failures")
    rows, groups = [], {}
    for revision in sorted(counts):
        source = revisions[revision]
        profile = preflight.load_revision_profile(profile_path, revision, profile_sha, source["revision_commit"])
        receipt = preflight.check_revision(profile, source["project_root"])
        failed = receipt["status"] != "ready"
        preserved = historical[revision]
        if preserved["status"] != "base_input_unavailable":
            raise ValueError("historical revision status differs")
        group = profile["group"]
        aggregate = groups.setdefault(group, {"revisions": 0, "historical_failures": 0,
                                               "currently_blocked_revisions": 0, "early_detectable_requests": 0})
        aggregate["revisions"] += 1
        aggregate["historical_failures"] += counts[revision]
        aggregate["currently_blocked_revisions"] += int(failed)
        aggregate["early_detectable_requests"] += counts[revision] if failed else 0
        rows.append({"revision_id": revision, "group": group,
                     "historical_preparation_failures": counts[revision],
                     "historical_status": preserved["status"],
                     "historical_error_kinds": sorted({r["error_kind"] for r in preserved.get("project_test_execution", [])
                                                        if r.get("error_kind")}),
                     "early_detectable_requests": counts[revision] if failed else 0,
                     "current_preflight": receipt})
    return {"schema": "zkfdo-preflight-retrospective-v1", "generated_utc": datetime.now(timezone.utc).isoformat(),
            "sources": [{"path": str(path.relative_to(ROOT)), "sha256": digest} for path, digest in PINS.items()],
            "profile": {"path": str(profile_path), "sha256": profile_sha},
            "historical_failures": sum(counts.values()),
            "early_detectable_requests": sum(row["early_detectable_requests"] for row in rows),
            "groups": groups, "revisions": rows,
            "interpretation": "Fresh local asset checks joined by revision to preserved preparation-failure metadata; "
                              "not a replay of the historical environment, measured time saving, recovered input, or new verdict. "
                              "No historical failure is removed and no fixture/environment value is synthesized.",
            "fuzzing_runs": 0, "judge_runs": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=PROFILE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_audit(args.profile.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps({key: result[key] for key in ("historical_failures", "early_detectable_requests", "groups")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
