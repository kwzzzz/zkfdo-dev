#!/usr/bin/env python3
"""Lossless disk reduction for finished run directories: identical regular files are replaced by
APFS clones (copy-on-write) of one representative, so every path keeps the same bytes and
SHA-256 and a later write to one copy never changes another. Nothing is deleted.

Default is a dry run. --apply writes the record (path, SHA-256, bytes, clone source) with
exclusive creation first, then replaces each duplicate through a temporary clone and rename,
and re-hashes it. Only regular files of at least --min-bytes are considered; links are never
followed. Use only on directories no process is writing.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import ctypes
import ctypes.util
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def clone(source, target):
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    temporary = f"{target}.dedup-tmp"
    if libc.clonefile(os.fsencode(source), os.fsencode(temporary), 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), temporary)
    os.replace(temporary, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path, help="directories under runs/")
    parser.add_argument("--min-bytes", type=int, default=64 * 1024)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    runs = (ROOT / "runs").resolve()
    roots = [(ROOT / root).resolve() for root in arguments.roots]
    if any(not root.is_dir() or not root.is_relative_to(runs) or root == runs for root in roots):
        raise SystemExit("roots must be directories inside runs/")
    groups = defaultdict(list)
    inodes = set()
    for root in roots:
        for directory, subdirectories, files in os.walk(root, followlinks=False):
            subdirectories.sort()
            for name in sorted(files):
                path = os.path.join(directory, name)
                if os.path.islink(path) or name.endswith(".dedup-tmp"):
                    continue
                status = os.stat(path)
                if status.st_size < arguments.min_bytes or (status.st_dev, status.st_ino) in inodes:
                    continue
                inodes.add((status.st_dev, status.st_ino))
                groups[(status.st_size, digest(path))].append(path)
    rows = []
    for (size, sha256), paths in groups.items():
        source, *duplicates = sorted(paths)
        rows += [{"path": os.path.relpath(path, ROOT), "sha256": sha256, "bytes": size,
                  "clone_of": os.path.relpath(source, ROOT)} for path in duplicates]
    summary = {"roots": [os.path.relpath(root, ROOT) for root in roots], "min_bytes": arguments.min_bytes,
               "files_scanned": sum(len(paths) for paths in groups.values()),
               "duplicates": len(rows), "duplicate_bytes": sum(row["bytes"] for row in rows)}
    print(json.dumps(summary))
    if not arguments.apply:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = runs / f"dedup-clone-{stamp}.json"
    with record.open("x") as handle:
        json.dump({"schema_version": 1, "created_at": stamp, "method": "APFS clonefile, then rename over the duplicate",
                   **summary, "replaced": rows}, handle)
        handle.write("\n")
    for row in rows:
        target, source = ROOT / row["path"], ROOT / row["clone_of"]
        clone(source, target)
        if os.path.getsize(target) != row["bytes"] or digest(target) != row["sha256"]:
            raise RuntimeError("clone differs from the recorded file: " + row["path"])
    print(json.dumps({"record": os.path.relpath(record, ROOT), "replaced": len(rows)}))


if __name__ == "__main__":
    main()
