#!/usr/bin/env python3
"""Audit Circom include resolution for every frozen N6-B2 execution spec."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "runs/n6-a2b-2026-10-08.noindex/queue-b-v4.json"
QUEUE_SHA256 = "d39e821fd65cea1852ad6a20b88ab59e03a7c363be9022224221986716161600"
OUTPUT = ROOT / "runs/n6-b2-2026-10-09.noindex/include-provenance-v3.json"
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
    candidates = []
    # Prepared snapshots mirror paths beneath runs/. An absolute include bypasses
    # Circom's -l search, so name-based comparison alone cannot inspect its copy.
    try:
        candidates.append(workspace / resolved(chosen).relative_to(ROOT / "runs"))
    except ValueError:
        pass
    # The prepared source may store a repository's clone/ content directly at
    # workspace/, including files reached transitively from an external include.
    try:
        parts = resolved(chosen).relative_to(ROOT / "runs").parts
        for index in range(len(parts) - 2):
            if parts[index] == "repositories" and parts[index + 2] == "clone":
                candidates.append(workspace.joinpath(*parts[index + 3:]))
                break
    except ValueError:
        pass
    # Prepared sources may flatten a repository clone or a corrected project
    # directly beneath workspace, while -l still points to the outside root.
    for root in roots:
        if root.name not in ("clone", "project") or inside(root, workspace):
            continue
        try:
            candidates.append(workspace / resolved(chosen).relative_to(resolved(root)))
        except ValueError:
            continue
    # A corrected project can be external while the corresponding prepared
    # snapshot still keeps the original repository under an internal clone/.
    internal_clones = [root for root in roots if root.name == "clone"
                       and inside(root, workspace)]
    for root in roots:
        if root.name not in ("clone", "project") or inside(root, workspace):
            continue
        try:
            suffix = resolved(chosen).relative_to(resolved(root))
        except ValueError:
            continue
        candidates.extend(clone / suffix for clone in internal_clones)
    if not Path(include_name).is_absolute():
        candidates.extend(root / include_name for root in [workspace, *roots]
                          if inside(root, workspace))
    for candidate in candidates:
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


def add_external_file(files: dict[tuple[str, str], dict[str, Any]],
                      row: dict[str, Any]) -> None:
    key = (row["path"], row["sha256"])
    item = files.setdefault(key, {**row, "snapshot_copies": [], "reference_count": 0})
    item["reference_count"] += 1
    for copy in row["snapshot_copies"]:
        if copy not in item["snapshot_copies"]:
            item["snapshot_copies"].append(copy)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=QUEUE)
    parser.add_argument("--queue-sha256", default=QUEUE_SHA256)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    queue_path = args.queue.resolve()
    output = args.output.resolve()
    if sha256(queue_path) != args.queue_sha256:
        raise ValueError("frozen B queue changed")
    execution = json.loads(queue_path.read_text())
    spec_paths = []
    for unit in execution["units"]:
        for method, key in (("W", "whole_spec"), ("S", "split_spec")):
            spec_path = ROOT / unit[key]
            if sha256(spec_path) != unit[f"{key}_sha256"]:
                raise ValueError(f"{method} spec changed: {unit['unit_id']}")
            spec_paths.append(spec_path)
    if len(spec_paths) != execution["spec_count"]:
        raise ValueError("B spec denominator mismatch")

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
                    add_external_file(external_files, row)
            target_refs.append({"target_id": target["target_id"], "closure_id": closure_id})
        specs.append({
            "spec": spec_path.relative_to(ROOT).as_posix(),
            "spec_sha256": sha256(spec_path),
            "method": spec["method"],
            "campaign_id": spec["campaign_id"],
            "target_count": len(target_refs),
            "targets": target_refs,
        })
    library_root_references = [
        {
            "closure_id": closure["closure_id"],
            "target_id": closure["target_id"],
            "workspace_source": closure["workspace_source"],
            "workspace_tree_sha256": closure["workspace_tree_sha256"],
            "resolution": row["resolution"],
            "path": row["resolved_path"],
            "sha256": row["resolved_sha256"],
            "snapshot_copies": row["snapshot_copies"],
        }
        for closure in closures.values()
        for row in closure["includes"]
        if row["outside_workspace"] and row["resolution"].startswith("library_root[")
    ]
    library_root_files: dict[tuple[str, str], dict[str, Any]] = {}
    for reference in library_root_references:
        key = (reference["path"], reference["sha256"])
        item = library_root_files.setdefault(key, {
            "path": reference["path"], "sha256": reference["sha256"],
            "snapshot_copies": [], "reference_count": 0,
        })
        item["reference_count"] += 1
        for copy in reference["snapshot_copies"]:
            if copy not in item["snapshot_copies"]:
                item["snapshot_copies"].append(copy)
    library_root_missing = sum(
        not row["snapshot_copies"] for row in library_root_references
    )
    library_root_mismatches = sum(
        not copy["matches_external"] for row in library_root_references
        for copy in row["snapshot_copies"]
    )
    external_missing_references = sum(
        not row["snapshot_copies"] for closure in closures.values()
        for row in closure["outside_workspace"]
    )
    result = {
        "schema_version": 3,
        "task": "N6-B2 include provenance gate",
        "created_at": now(),
        "queue": queue_path.relative_to(ROOT).as_posix(),
        "queue_sha256": sha256(queue_path),
        "resolution_policy": (
            "for every include: including-file directory first, then -l roots in command order"
        ),
        "spec_count": len(specs),
        "target_count": sum(row["target_count"] for row in specs),
        "external_unique_file_count": len(external_files),
        "external_unique_file_without_copy_count": sum(
            not row["snapshot_copies"] for row in external_files.values()
        ),
        "external_reference_missing_copy_count": external_missing_references,
        "unique_closure_count": len(closures),
        "unresolved_include_count": unresolved_count,
        "snapshot_copy_mismatch_count": mismatch_count,
        "library_root_external_reference_count": len(library_root_references),
        "library_root_external_unique_file_count": len(library_root_files),
        "library_root_external_missing_copy_count": library_root_missing,
        "library_root_external_copy_mismatch_count": library_root_mismatches,
        "library_root_external_files": sorted(
            library_root_files.values(), key=lambda row: row["path"]
        ),
        "library_root_external_references": sorted(
            library_root_references,
            key=lambda row: (row["path"], row["closure_id"])
        ),
        "status": "passed" if unresolved_count == 0 and mismatch_count == 0
        and external_missing_references == 0 and library_root_missing == 0
        else "failed",
        "external_unique_files": sorted(external_files.values(), key=lambda row: row["path"]),
        "absolute_includes": sorted([
            {"closure_id": closure["closure_id"],
             "entrypoint": closure["entrypoint"],
             "including_file": row["including_file"],
             "line": row["line"],
             "include": row["include"],
             "resolved_path": row["resolved_path"],
             "resolved_sha256": row["resolved_sha256"],
             "outside_workspace": row["outside_workspace"]}
            for closure in closures.values()
            for row in closure["includes"] if Path(row["include"]).is_absolute()
        ], key=lambda row: (row["entrypoint"], row["including_file"], row["line"])),
        "closures": sorted(closures.values(), key=lambda row: row["closure_id"]),
        "specs": specs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, output)
    print(json.dumps({
        "status": result["status"],
        "spec_count": result["spec_count"],
        "target_count": result["target_count"],
        "external_unique_file_count": result["external_unique_file_count"],
        "external_unique_file_without_copy_count":
            result["external_unique_file_without_copy_count"],
        "external_reference_missing_copy_count": external_missing_references,
        "absolute_include_count": len(result["absolute_includes"]),
        "unresolved_include_count": unresolved_count,
        "snapshot_copy_mismatch_count": mismatch_count,
        "library_root_external_reference_count": len(library_root_references),
        "library_root_external_unique_file_count": len(library_root_files),
        "library_root_external_missing_copy_count": library_root_missing,
        "library_root_external_copy_mismatch_count": library_root_mismatches,
        "sha256": sha256(output),
    }, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
