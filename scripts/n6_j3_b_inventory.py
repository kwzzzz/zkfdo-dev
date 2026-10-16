#!/usr/bin/env python3
"""Inventory B main-run candidate metadata for J without parsing candidates.

The queue and execute root are arguments so the same reader can later inventory
the separate mem20 scope. This invocation covers only the B main scope.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from n6_j1_inventory import (campaign_candidates, checked_file,
                             git_commit_present, load_source,
                             preflight_library_paths, read_json, require,
                             selected_spec, sha256_file, write_new_json)


ROOT = Path(__file__).resolve().parents[1]
J_ROOT = Path("runs/n6-j3-2026-10-14.noindex")
QUEUE = Path("runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json")
EXECUTE = Path("runs/n6-b2-2026-10-09.noindex/b-execute.noindex")
MEM20_QUEUE = Path("runs/n6-b3-2026-10-12.noindex/mem20-prep/queue-b-mem20.json")
MEM20_EXECUTE = Path("runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex")
TARGETS = Path("docs/n6_targets_b_2026-10-06.json")
ID_MAP = Path("runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/target-id-map.json")


def original_target_ids(root: Path) -> dict[str, str]:
    mapping = read_json(root / ID_MAP)["mapping"]
    return {row["new_target_id"]: row["old_target_id"] for row in mapping}


def manifest(root: Path, source: dict, target_list: Path, scope: str) -> dict:
    targets = read_json(target_list)
    by_identifier = {row["identifier"]: row for row in targets["stage1"] + targets["stage2"]}
    rows = []
    seen = set()
    for unit in source["queue"]["units"]:
        identifier = unit["identifier"]
        if identifier in seen:
            continue
        seen.add(identifier)
        target_info = by_identifier[identifier]
        w_name, w_sha, w_spec = selected_spec(root, unit, "W")
        original_w = read_json(checked_file(root, unit["source_whole_spec"],
                                            unit["source_whole_spec_sha256"]))
        require(len(w_spec["targets"]) == 1 and len(original_w["targets"]) == 1,
                f"W target count differs: {identifier}")
        target = w_spec["targets"][0]
        original_target = original_w["targets"][0]
        snapshots = {row["id"]: row for row in w_spec["source_snapshots"]}
        original_snapshots = {row["id"]: row for row in original_w["source_snapshots"]}
        project = Path(snapshots[target["source_snapshot_id"]]["path"]).resolve()
        original_project = Path(original_snapshots[original_target["source_snapshot_id"]]["path"]).resolve()
        entrypoint = checked_file(project, target["entrypoint_relative"],
                                  target["entrypoint_sha256"])
        revision = w_spec["recorded_revision"]
        require(revision == original_w["recorded_revision"] == target_info["commit"],
                f"revision differs: {identifier}")
        require(target_info["entrypoint_key"] == f"source_main:{original_target['entrypoint_relative']}",
                f"target entrypoint differs: {identifier}")
        require(git_commit_present(original_project, revision),
                f"original Git commit missing: {identifier}")
        rows.append({
            "identifier": identifier,
            "unit_id": unit["unit_id"],
            "seed": unit["seed"],
            "phase": target_info["stage"],
            "repository": target_info["repository"],
            "constraints_from_queue": unit["constraints"],
            "revision_kind": "evaluation",
            "revision_commit": revision,
            "git_repository_path": str(original_project),
            "source_project_path": str(original_project),
            "whole_spec": w_name,
            "whole_spec_sha256": w_sha,
            "entrypoint_relative": target["entrypoint_relative"],
            "entrypoint_absolute": str(entrypoint),
            "entrypoint_sha256": target["entrypoint_sha256"],
            "project_root": str(project),
            "source_snapshot_id": target["source_snapshot_id"],
            "preflight_library_paths": preflight_library_paths(target, project),
            "item_ids": [],
            "dataset_cases": [],
        })
    expected_revisions = 10 if scope == "main" else 2
    require(len(rows) == expected_revisions,
            f"expected {expected_revisions} B {scope} revisions, got {len(rows)}")
    return {"schema_version": 1, "status": "verified", "revision_count": len(rows),
            "scope": scope, "rows": rows}


def build(root: Path, queue: Path, execute: Path, target_list: Path,
          scope: str) -> tuple[dict, dict]:
    source = load_source(root, queue, execute)
    expected_units = 30 if scope == "main" else 6
    require(len(source["queue"]["units"]) == expected_units,
            f"expected {expected_units} B {scope} units")
    original_ids = original_target_ids(root)
    seen_sha: set[str] = set()
    rows = []
    for unit in source["queue"]["units"]:
        rows.extend(campaign_candidates(root, source, unit, scope, original_ids, seen_sha))
    counts = {scope: {method: sum(row["method"] == method for row in rows)
                      for method in ("W", "S")}}
    if scope == "main":
        require(counts == {"main": {"W": 0, "S": 107}},
                f"B main candidate counts differ: {counts}")
    inventory = {"schema_version": 1, "status": "verified", "counts": counts,
                 "candidate_count": len(rows),
                 "by_identifier": dict(Counter(row["identifier"] for row in rows)),
                 "source_queue": str(queue), "source_queue_sha256": source["queue_sha256"],
                 "source_state": str(execute / "state.json"),
                 "source_state_sha256": sha256_file(execute / "state.json"),
                 "rows": rows}
    return inventory, manifest(root, source, target_list, scope)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--scope", choices=("main", "mem20"), default="main")
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--execute", type=Path)
    parser.add_argument("--targets", type=Path, default=TARGETS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--revision-output", type=Path)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    queue = (root / (args.queue or (QUEUE if args.scope == "main" else MEM20_QUEUE))).resolve()
    execute = (root / (args.execute or (EXECUTE if args.scope == "main" else MEM20_EXECUTE))).resolve()
    targets = (root / args.targets).resolve()
    inventory, revisions = build(root, queue.relative_to(root), execute.relative_to(root),
                                 targets, args.scope)
    output = (root / (args.output or J_ROOT /
                      ("candidate-inventory.json" if args.scope == "main" else
                       "mem20-candidate-inventory.json"))).resolve()
    revision_output = (root / (args.revision_output or J_ROOT /
                               ("revision-manifest.json" if args.scope == "main" else
                                "mem20-revision-manifest.json"))).resolve()
    require(output != revision_output, "inventory and revision output paths match")
    require(not output.exists() and not revision_output.exists(), "output already exists")
    write_new_json(output, inventory)
    write_new_json(revision_output, revisions)
    print(json.dumps({"inventory": str(output), "revision_manifest": str(revision_output),
                      "counts": inventory["counts"], "revisions": revisions["revision_count"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
