#!/usr/bin/env python3
"""Value-free B6b hint-copy preparation checks for the fixed v1/v2.2 engines.

Fixed engine source: v2.2 `src/candidate_review/lifting/mod.rs:810-821,
3851-3931`; v1 `mod.rs:804-815,3610-3690`. If edits are planned, each
engine copies source_root and every library tree below its hint workspace.
Neither engine offers a preparation-only lift mode. This checks filesystem
conditions for that copy without opening candidates or running J.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any


DEFAULT_STAGING_ROOT = Path("/Volumes/zkfdo-jcache/n6-b6b-batch1x/source-staging")
DEFAULT_MAX_CIRCOM_FILES = 2_000
DEFAULT_MAX_CIRCOM_BYTES = 64 * 1024 * 1024
MAX_WALK_DIRECTORIES = 20_000
MAX_WALK_ENTRIES = 250_000
ENGINES = ("v1", "v2.2")


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def inspect_tree(root: Path, max_files: int, max_bytes: int) -> dict[str, Any]:
    """Walk one named staging tree only; stop on links, special files or caps."""
    result: dict[str, Any] = {"circom_files": 0, "circom_bytes": 0,
                              "directories": 0, "entries": 0,
                              "scan_complete": False, "failure": None}
    if not root.is_dir() or root.is_symlink():
        result["failure"] = "source_root_missing_or_symlink"
        return result
    pending = [root]
    while pending:
        directory = pending.pop()
        result["directories"] += 1
        if result["directories"] > MAX_WALK_DIRECTORIES:
            result["failure"] = "directory_scan_cap_exceeded"
            return result
        try:
            with os.scandir(directory) as scan:
                for entry in scan:
                    result["entries"] += 1
                    if result["entries"] > MAX_WALK_ENTRIES:
                        result["failure"] = "entry_scan_cap_exceeded"
                        return result
                    try:
                        mode = entry.stat(follow_symlinks=False).st_mode
                    except OSError:
                        result["failure"] = "source_entry_unreadable"
                        return result
                    if stat.S_ISLNK(mode):
                        result["failure"] = "source_tree_symlink"
                        return result
                    if stat.S_ISDIR(mode):
                        pending.append(Path(entry.path))
                        continue
                    if not stat.S_ISREG(mode):
                        result["failure"] = "source_tree_special_file"
                        return result
                    if Path(entry.name).suffix == ".circom":
                        result["circom_files"] += 1
                        result["circom_bytes"] += entry.stat(follow_symlinks=False).st_size
                        if result["circom_files"] > max_files:
                            result["failure"] = "circom_file_cap_exceeded"
                            return result
                        if result["circom_bytes"] > max_bytes:
                            result["failure"] = "circom_byte_cap_exceeded"
                            return result
        except OSError:
            result["failure"] = "source_tree_unreadable"
            return result
    result["scan_complete"] = True
    if result["circom_files"] == 0:
        result["failure"] = "no_circom_sources"
    return result


def _path(value: Any) -> Path | None:
    if not isinstance(value, str) or not Path(value).is_absolute():
        return None
    return Path(value).resolve()


def check_request(request: dict[str, Any], *, staging_root: Path,
                  workspace_root: Path, instance_root: Path, cache_root: Path,
                  max_files: int, max_bytes: int,
                  tree_cache: dict[Path, dict[str, Any]]) -> dict[str, Any]:
    """Use only request source and library paths, never its candidate field."""
    problems: list[str] = []
    root = _path(request.get("source_root"))
    if root is None or not root.is_relative_to(staging_root):
        return {"status": "preparation_failed", "reasons": ["source_root_outside_staging"],
                "circom_files": None, "circom_bytes": None, "scan_complete": False}
    for name, path in (("workspace", workspace_root), ("instance", instance_root),
                       ("cache", cache_root)):
        if overlaps(root, path):
            problems.append(f"{name}_overlaps_source_root")
    libraries = request.get("library_paths")
    if not isinstance(libraries, list) or not libraries:
        problems.append("library_paths_missing")
    else:
        for value in libraries:
            library = _path(value)
            if library is None or not library.is_dir():
                problems.append("library_path_missing")
                continue
            for name, path in (("workspace", workspace_root),
                               ("instance", instance_root), ("cache", cache_root)):
                if overlaps(library, path):
                    problems.append(f"{name}_overlaps_library")
    for name in ("entrypoint", "component_wrapper"):
        source = _path(request.get(name))
        if source is None or not source.is_file() or not source.is_relative_to(root):
            problems.append(f"{name}_outside_source_root")
    if root not in tree_cache:
        tree_cache[root] = inspect_tree(root, max_files, max_bytes)
    tree = tree_cache[root]
    if tree["failure"] is not None:
        problems.append(tree["failure"])
    return {"status": "passed" if not problems else "preparation_failed",
            "reasons": sorted(set(problems)),
            "circom_files": tree["circom_files"],
            "circom_bytes": tree["circom_bytes"],
            "scan_complete": tree["scan_complete"]}


def inspect_index(index_path: Path, *, staging_root: Path, workspace_root: Path,
                  instance_root: Path, cache_root: Path,
                  max_files: int = DEFAULT_MAX_CIRCOM_FILES,
                  max_bytes: int = DEFAULT_MAX_CIRCOM_BYTES) -> dict[str, Any]:
    """Return per-engine/revision summaries and row ordinals without J results."""
    if max_files < 1 or max_bytes < 1:
        raise ValueError("source limits must be positive")
    staging_root = staging_root.resolve()
    roots = {"workspace": workspace_root, "instance": instance_root,
             "cache": cache_root}
    for name, path in roots.items():
        if not path.is_absolute():
            raise ValueError(f"{name} root must be absolute")
        roots[name] = path.resolve()
    if len(set(roots.values())) != 3:
        raise ValueError("workspace, instance and cache roots must differ")
    index = json.loads(index_path.read_text())
    rows = index.get("requests")
    if not isinstance(rows, list) or index.get("request_count") != len(rows):
        raise ValueError("request index count invalid")
    tree_cache: dict[Path, dict[str, Any]] = {}
    row_checks = []
    summaries: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"requests": 0, "passed": 0, "failed": 0, "failure_reasons": Counter()})
    for position, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("queue_order") != position or not isinstance(
                row.get("revision_id"), str):
            raise ValueError("request row order or revision invalid")
        request_path = _path(row.get("request"))
        if request_path is None or not request_path.is_file() or digest(request_path) != row.get(
                "request_sha256"):
            checked = {"status": "preparation_failed",
                       "reasons": ["request_file_missing_or_hash_changed"],
                       "circom_files": None, "circom_bytes": None,
                       "scan_complete": False}
        else:
            try:
                request = json.loads(request_path.read_text())
            except (OSError, ValueError):
                request = None
            if not isinstance(request, dict):
                checked = {"status": "preparation_failed",
                           "reasons": ["request_document_invalid"],
                           "circom_files": None, "circom_bytes": None,
                           "scan_complete": False}
            else:
                checked = check_request(request, staging_root=staging_root,
                                        workspace_root=roots["workspace"],
                                        instance_root=roots["instance"],
                                        cache_root=roots["cache"], max_files=max_files,
                                        max_bytes=max_bytes, tree_cache=tree_cache)
        row_checks.append({"queue_order": position, "revision_id": row["revision_id"],
                           **checked})
        summary = summaries[row["revision_id"]]
        summary["requests"] += 1
        if checked["status"] == "passed":
            summary["passed"] += 1
        else:
            summary["failed"] += 1
            summary["failure_reasons"].update(checked["reasons"])
    by_revision = {revision: {**summary,
                              "failure_reasons": dict(sorted(summary["failure_reasons"].items()))}
                   for revision, summary in sorted(summaries.items())}
    return {"schema_version": 1, "kind": "n6_b6b_static_hint_copy_preflight",
            "index_path": str(index_path.resolve()), "index_sha256": digest(index_path),
            "request_count": len(rows), "limits": {
                "circom_files": max_files, "circom_bytes": max_bytes,
                "walk_directories": MAX_WALK_DIRECTORIES,
                "walk_entries": MAX_WALK_ENTRIES},
            "source_root_count": len(tree_cache),
            "per_engine": {engine: {"by_revision": by_revision,
                                    "passed": sum(item["passed"] for item in by_revision.values()),
                                    "failed": sum(item["failed"] for item in by_revision.values())}
                           for engine in ENGINES},
            "row_checks": row_checks,
            "all_passed": all(item["status"] == "passed" for item in row_checks)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--source-staging-root", type=Path, default=DEFAULT_STAGING_ROOT)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--instance-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--max-circom-files", type=int, default=DEFAULT_MAX_CIRCOM_FILES)
    parser.add_argument("--max-circom-bytes", type=int, default=DEFAULT_MAX_CIRCOM_BYTES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inspect_index(args.index, staging_root=args.source_staging_root,
                           workspace_root=args.workspace_root,
                           instance_root=args.instance_root,
                           cache_root=args.cache_root,
                           max_files=args.max_circom_files,
                           max_bytes=args.max_circom_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"request_count": report["request_count"],
                      "source_root_count": report["source_root_count"],
                      "all_passed": report["all_passed"],
                      "passed": report["per_engine"]["v1"]["passed"],
                      "failed": report["per_engine"]["v1"]["failed"]}, sort_keys=True))
    return 0 if report["all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
