#!/usr/bin/env python3
"""Inventory one J revision cache; delete it only with an explicit --delete."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


MARKER = "n6-j1-cache-owner.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cache_directory(cache_root: Path, scope: str, ordinal: int) -> Path:
    if scope not in {"main", "mem20"} or ordinal < 1:
        raise ValueError("invalid J scope or revision ordinal")
    if not cache_root.is_absolute():
        raise ValueError("--cache-root must be absolute")
    root = cache_root.resolve()
    if not root.is_dir():
        raise ValueError("cache root does not exist")
    path = root / scope / f"{ordinal:04d}"
    if path.is_symlink() or path.resolve() != path or not path.is_relative_to(root):
        raise ValueError("unsafe revision cache path")
    return path


def marker_value(scope: str, ordinal: int, revision_id: str,
                 index_sha256: str) -> dict[str, Any]:
    return {"schema_version": 1, "kind": "n6_j1_revision_cache",
            "scope": scope, "revision_ordinal": ordinal,
            "revision_id": revision_id, "request_index_sha256": index_sha256}


def initialize_cache(cache_root: Path, scope: str, ordinal: int,
                     revision_id: str, index_sha256: str) -> Path:
    path = cache_directory(cache_root, scope, ordinal)
    expected = marker_value(scope, ordinal, revision_id, index_sha256)
    if path.exists():
        marker = path / MARKER
        if not marker.is_file() or json.loads(marker.read_text()) != expected:
            raise ValueError(f"cache exists without matching owner marker: {path}")
    else:
        path.mkdir(parents=True)
        marker = path / MARKER
        with marker.open("x") as stream:
            json.dump(expected, stream, sort_keys=True)
            stream.write("\n")
    return path


def inventory(path: Path) -> tuple[list[dict[str, Any]], list[Path]]:
    rows: list[dict[str, Any]] = []
    directories: list[Path] = []
    for directory, subdirs, files in os.walk(path, topdown=True, followlinks=False):
        current = Path(directory)
        directories.append(current)
        for name in sorted(subdirs + files):
            item = current / name
            if item.is_symlink():
                raise ValueError(f"cache contains symlink: {item}")
        subdirs.sort()
        for name in sorted(files):
            item = current / name
            if not item.is_file():
                raise ValueError(f"cache contains non-file: {item}")
            rows.append({"path": item.relative_to(path).as_posix(),
                         "sha256": sha256(item), "bytes": item.stat().st_size})
    return rows, sorted(directories, key=lambda item: len(item.parts), reverse=True)


def cleanup_revision(cache_root: Path, output_root: Path, scope: str, ordinal: int,
                     revision_id: str, index_sha256: str, *, delete: bool = False,
                     manifest_path: Path | None = None) -> dict[str, Any]:
    path = cache_directory(cache_root, scope, ordinal)
    if not path.is_dir():
        raise ValueError(f"revision cache missing: {path}")
    expected = marker_value(scope, ordinal, revision_id, index_sha256)
    if json.loads((path / MARKER).read_text()) != expected:
        raise ValueError("revision cache owner marker mismatch")
    output = output_root.resolve()
    if not output.is_dir() or output == path or output.is_relative_to(path):
        raise ValueError("output must be a separate existing directory")
    rows, directories = inventory(path)
    record = {"schema_version": 1, "kind": "n6_j1_cache_cleanup",
              "recorded_at": datetime.now(timezone.utc).isoformat(),
              "scope": scope, "revision_ordinal": ordinal,
              "revision_id": revision_id, "request_index_sha256": index_sha256,
              "cache_path": str(path), "file_count": len(rows),
              "bytes": sum(row["bytes"] for row in rows), "files": rows,
              "content_key_namespace": str(path),
              "content_keys": sorted({row["path"].split("/", 1)[0] for row in rows
                                      if re.fullmatch(r"[0-9a-f]{64}",
                                                      row["path"].split("/", 1)[0])})}
    if not delete:
        return {"status": "dry_run", "file_count": record["file_count"],
                "bytes": record["bytes"], "cache_path": record["cache_path"]}
    if manifest_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest_path = output / "cache-cleanup" / f"{scope}-{ordinal:04d}-{stamp}.json"
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to(output) or manifest_path.exists():
        raise ValueError("cleanup manifest must be a new path under output")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("x") as stream:
        json.dump(record, stream, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    for row in rows:
        (path / row["path"]).unlink()
    for directory in directories:
        directory.rmdir()
    return {"status": "deleted", "file_count": record["file_count"],
            "bytes": record["bytes"], "cache_path": record["cache_path"],
            "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--scope", choices=("main", "mem20"), required=True)
    parser.add_argument("--revision-ordinal", type=int, required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args(argv)
    result = cleanup_revision(args.cache_root, args.output_root, args.scope,
                              args.revision_ordinal, args.revision_id,
                              args.index_sha256, delete=args.delete)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
