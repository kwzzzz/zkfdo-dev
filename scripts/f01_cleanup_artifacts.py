#!/usr/bin/env python3
"""Record and remove F-01 compiled artifacts (.r1cs/.wasm/.cpp/.dat/.o), or with
--diagnostic-copies every entry of the instrumented source copies (`diagnostic-copy` trees), or
with --tree every entry of the named directories (for example compile caches).

Only entries under runs/f01-2026-10-03 are considered. Artifacts are regular files; links are
never followed. In the copies, links are recorded by their target and removed as links. Clones,
node_modules, JSON, logs and runs/c02-corpus-2026-10-02/tools are outside this directory or
have other suffixes and are never touched. Default is a dry run; --delete first writes the
record (path, SHA-256, bytes) with exclusive creation, then removes exactly the recorded files.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/f01-2026-10-03"
SUFFIXES = {".r1cs", ".wasm", ".cpp", ".dat", ".o"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def artifacts():
    for directory, subdirectories, files in os.walk(RUN, followlinks=False):
        subdirectories.sort()
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix in SUFFIXES and not path.is_symlink() and path.is_file():
                yield path


def copy_trees():
    """`diagnostic-copy` directories under RUN, not entered through links."""
    for directory, subdirectories, _ in os.walk(RUN, followlinks=False):
        if Path(directory).name == "diagnostic-copy":
            subdirectories.clear()
            yield Path(directory)


def copy_entries(trees):
    """Every file and link of the trees; links are recorded by target, never followed."""
    for tree in trees:
        for directory, subdirectories, files in os.walk(tree, followlinks=False):
            subdirectories.sort()
            for name in sorted(files) + sorted(d for d in subdirectories if (Path(directory) / d).is_symlink()):
                yield Path(directory) / name


def describe(path):
    if path.is_symlink():
        return {"path": str(path.relative_to(ROOT)), "link": os.readlink(path)}
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path), "bytes": path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--diagnostic-copies", action="store_true")
    parser.add_argument("--root", type=Path, help="run directory under runs/ (default: the F-01 run)")
    parser.add_argument("--tree", type=Path, action="append", default=[],
                        help="directory under the root to remove whole (repeatable)")
    arguments = parser.parse_args()
    global RUN
    if arguments.root is not None:
        root = (ROOT / arguments.root).resolve()
        if not root.is_relative_to((ROOT / "runs").resolve()) or not root.is_dir():
            raise SystemExit("--root must be an existing directory under runs/")
        RUN = root
    named = [(ROOT / tree).resolve() for tree in arguments.tree]
    if any(not tree.is_dir() or tree == RUN.resolve() or not tree.is_relative_to(RUN.resolve()) for tree in named):
        raise SystemExit("--tree must name directories inside the root")
    whole = arguments.diagnostic_copies or bool(named)
    trees = sorted(copy_trees()) if arguments.diagnostic_copies else sorted(named)
    paths = list(copy_entries(trees)) if whole else list(artifacts())
    rows = [describe(path) for path in paths]
    summary = {"files": sum("sha256" in row for row in rows), "links": sum("link" in row for row in rows),
               "bytes": sum(row.get("bytes", 0) for row in rows),
               "by_suffix": dict(sorted(Counter(Path(row["path"]).suffix for row in rows).items()))}
    if whole:
        summary["trees"] = len(trees)
    print(json.dumps(summary))
    if not arguments.delete:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    kind = "diagnostic-copies" if arguments.diagnostic_copies else "tree" if named else "artifact"
    record = RUN / f"{kind}-cleanup-{stamp}.json"
    selection = ({"selection": "every entry under directories named diagnostic-copy" if arguments.diagnostic_copies
                  else "every entry under the named directories",
                  "trees": [str(tree.relative_to(ROOT)) for tree in trees]}
                 if whole else {"suffixes": sorted(SUFFIXES)})
    with record.open("x") as handle:
        # The copies have ~1.9M entries: their record is compact JSON with the same fields.
        json.dump({"schema_version": 1, "task": "F-01", "created_at": stamp, **selection,
                   **summary, "artifacts": rows}, handle, indent=None if whole else 1)
        handle.write("\n")
    run = RUN.resolve()
    for path in paths:
        if not path.parent.resolve().is_relative_to(run):
            raise RuntimeError("refuse to remove " + str(path))
        path.unlink()
    for tree in trees:  # now only empty directories remain
        if not tree.resolve().is_relative_to(run):
            raise RuntimeError("refuse to remove " + str(tree))
        for directory, _, _ in sorted(os.walk(tree, followlinks=False), key=lambda row: -len(row[0])):
            os.rmdir(directory)
    print(json.dumps({"record": str(record.relative_to(ROOT)), "removed": len(paths), "trees": len(trees)}))


if __name__ == "__main__":
    main()
