#!/usr/bin/env python3
"""Audit Circom include resolution for every frozen N6-A2 execution spec."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a2-2026-10-08"
EXECUTION_LIST = RUN / "execution-list-v1.json"
OUTPUT = RUN / "include-provenance.json"
INCLUDE = re.compile(r'^\s*include\s+"([^"]+)"\s*;')
_RESOLVED: dict[str, Path] = {}
_HASHES: dict[str, str] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    key = str(path.absolute())
    if key in _HASHES:
        return _HASHES[key]
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    value = digest.hexdigest()
    _HASHES[key] = value
    return value


def resolved(path: Path) -> Path:
    key = str(path.absolute())
    if key not in _RESOLVED:
        _RESOLVED[key] = path.resolve()
    return _RESOLVED[key]


def relative_or_absolute(path: Path) -> str:
    try:
        return resolved(path).relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved(path))


def library_roots(target: dict[str, Any], workspace: Path) -> list[Path]:
    command = target.get("preflight_compile_command") or target["command"]
    roots = []
    for index, argument in enumerate(command[:-1]):
        if argument == "-l":
            roots.append(Path(command[index + 1].replace("{workspace}", str(workspace))))
    return roots


def inside(path: Path, root: Path) -> bool:
    try:
        resolved(path).relative_to(resolved(root))
        return True
    except ValueError:
        return False


def snapshot_comparisons(include_name: str, chosen: Path, workspace: Path,
                         roots: list[Path]) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for root in [workspace, *roots]:
        if not inside(root, workspace):
            continue
        candidate = root / include_name
        lexical = str(candidate.absolute())
        if lexical in seen or not candidate.is_file():
            continue
        seen.add(lexical)
        if resolved(candidate) == resolved(chosen):
            continue
        candidate_hash = sha256(candidate)
        chosen_hash = sha256(chosen)
        rows.append({
            "path": relative_or_absolute(candidate),
            "sha256": candidate_hash,
            "matches_external": candidate_hash == chosen_hash,
        })
    return rows


def audit_target(spec_path: Path, spec: dict[str, Any], target: dict[str, Any],
                 snapshots: dict[str, Path]) -> dict[str, Any]:
    workspace = snapshots[target["source_snapshot_id"]]
    entrypoint = workspace / target["entrypoint_relative"]
    roots = library_roots(target, workspace)
    queue = [entrypoint]
    visited: set[Path] = set()
    include_rows = []
    unresolved = []
    external = []
    mismatches = []
    while queue:
        source = queue.pop()
        resolved_source = resolved(source)
        if resolved_source in visited:
            continue
        visited.add(resolved_source)
        if not source.is_file():
            unresolved.append({"including_file": relative_or_absolute(source),
                               "include": None, "reason": "source_missing"})
            continue
        for line_number, line in enumerate(source.read_text(errors="replace").splitlines(), 1):
            match = INCLUDE.match(line)
            if not match:
                continue
            name = match.group(1)
            search = [source.parent / name, *[root / name for root in roots]]
            chosen = next((candidate for candidate in search if candidate.is_file()), None)
            if chosen is None:
                unresolved.append({
                    "including_file": relative_or_absolute(source),
                    "line": line_number,
                    "include": name,
                    "search_order": [relative_or_absolute(candidate) for candidate in search],
                    "reason": "include_not_found",
                })
                continue
            chosen_index = search.index(chosen)
            row = {
                "including_file": relative_or_absolute(source),
                "line": line_number,
                "include": name,
                "resolved_path": relative_or_absolute(chosen),
                "resolved_sha256": sha256(chosen),
                "resolution": "including_file_directory" if chosen_index == 0
                else f"library_root[{chosen_index - 1}]",
                "outside_workspace": not inside(chosen, workspace),
            }
            if row["outside_workspace"]:
                comparisons = snapshot_comparisons(name, chosen, workspace, roots)
                row["snapshot_copies"] = comparisons
                external.append({
                    "path": row["resolved_path"],
                    "sha256": row["resolved_sha256"],
                    "include": name,
                    "snapshot_copies": comparisons,
                })
                mismatches.extend(copy for copy in comparisons if not copy["matches_external"])
            include_rows.append(row)
            queue.append(chosen)
    return {
        "spec": spec_path.relative_to(ROOT).as_posix(),
        "spec_sha256": sha256(spec_path),
        "target_id": target["target_id"],
        "source_snapshot_id": target["source_snapshot_id"],
        "workspace_source": relative_or_absolute(workspace),
        "workspace_tree_sha256": next(
            row["tree_sha256"] for row in spec["source_snapshots"]
            if row["id"] == target["source_snapshot_id"]
        ),
        "entrypoint": relative_or_absolute(entrypoint),
        "entrypoint_sha256": sha256(entrypoint) if entrypoint.is_file() else None,
        "library_roots_in_order": [relative_or_absolute(path) for path in roots],
        "visited_file_count": len(visited),
        "include_count": len(include_rows),
        "outside_workspace_count": len(external),
        "unresolved_count": len(unresolved),
        "snapshot_mismatch_count": len(mismatches),
        "includes": include_rows,
        "outside_workspace": external,
        "unresolved": unresolved,
    }


def main() -> int:
    execution = json.loads(EXECUTION_LIST.read_text())
    spec_paths = []
    for phase in execution["ordering"]:
        queue_path = ROOT / execution["queues"][phase]["path"]
        if sha256(queue_path) != execution["queues"][phase]["sha256"]:
            raise ValueError(f"queue changed: {phase}")
        queue = json.loads(queue_path.read_text())
        for unit in queue["units"]:
            spec_paths.extend([ROOT / unit["whole_spec"], ROOT / unit["split_spec"]])
    if len(spec_paths) != execution["selected_spec_count"]:
        raise ValueError("execution spec denominator mismatch")

    specs = []
    closures: dict[str, dict[str, Any]] = {}
    external_files: dict[tuple[str, str], dict[str, Any]] = {}
    unresolved_count = mismatch_count = 0
    for spec_path in spec_paths:
        spec = json.loads(spec_path.read_text())
        snapshots = {row["id"]: Path(row["path"]) for row in spec["source_snapshots"]}
        target_refs = []
        for target in spec["targets"]:
            workspace = snapshots[target["source_snapshot_id"]]
            roots = library_roots(target, workspace)
            identity = json.dumps({
                "source_snapshot_id": target["source_snapshot_id"],
                "workspace": str(workspace.absolute()),
                "entrypoint_relative": target["entrypoint_relative"],
                "entrypoint_sha256": target["entrypoint_sha256"],
                "library_roots": [str(root.absolute()) for root in roots],
            }, sort_keys=True).encode()
            closure_id = hashlib.sha256(identity).hexdigest()
            if closure_id not in closures:
                closure = audit_target(spec_path, spec, target, snapshots)
                closure["closure_id"] = closure_id
                closures[closure_id] = closure
                unresolved_count += closure["unresolved_count"]
                mismatch_count += closure["snapshot_mismatch_count"]
                for row in closure["outside_workspace"]:
                    external_files[(row["path"], row["sha256"])] = row
            target_refs.append({"target_id": target["target_id"], "closure_id": closure_id})
        specs.append({
            "spec": spec_path.relative_to(ROOT).as_posix(),
            "spec_sha256": sha256(spec_path),
            "method": spec["method"],
            "campaign_id": spec["campaign_id"],
            "target_count": len(target_refs),
            "targets": target_refs,
        })
    result = {
        "schema_version": 1,
        "task": "N6-A2 include provenance gate",
        "created_at": now(),
        "execution_list": EXECUTION_LIST.relative_to(ROOT).as_posix(),
        "execution_list_sha256": sha256(EXECUTION_LIST),
        "resolution_policy": (
            "for every include: including-file directory first, then -l roots in command order"
        ),
        "spec_count": len(specs),
        "target_count": sum(row["target_count"] for row in specs),
        "external_unique_file_count": len(external_files),
        "unique_closure_count": len(closures),
        "unresolved_include_count": unresolved_count,
        "snapshot_copy_mismatch_count": mismatch_count,
        "status": "passed" if unresolved_count == 0 and mismatch_count == 0 else "failed",
        "external_unique_files": sorted(external_files.values(), key=lambda row: row["path"]),
        "closures": sorted(closures.values(), key=lambda row: row["closure_id"]),
        "specs": specs,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, OUTPUT)
    print(json.dumps({
        "status": result["status"],
        "spec_count": result["spec_count"],
        "target_count": result["target_count"],
        "external_unique_file_count": result["external_unique_file_count"],
        "unresolved_include_count": unresolved_count,
        "snapshot_copy_mismatch_count": mismatch_count,
        "sha256": sha256(OUTPUT),
    }, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
