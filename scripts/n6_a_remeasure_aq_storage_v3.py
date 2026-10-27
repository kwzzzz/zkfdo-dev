#!/usr/bin/env python3
"""Independent, resumable storage seeding for the A aq v3 runner.

This module never deletes a file, changes the source, follows links, or refreshes
a finalized target. Execution callers own the disk gate and shared runner lock.
"""

from __future__ import annotations

from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any
import uuid

from n6_a_remeasure_aq_cleanup_v2 import _regular_ancestors

CHUNK = 1024 * 1024


class StorageError(ValueError):
    """The source, target, or immutable seed binding is unsafe or inconsistent."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise StorageError(reason)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _hash(path: Path) -> str:
    _regular_ancestors(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode), f"not a regular file: {path}")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                 (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                 f"file changed during hashing: {path}")
        return digest.hexdigest()


def _inventory(root: Path, *, hashes: bool, target: bool = False) -> dict[str, Any]:
    _regular_ancestors(root)
    files: list[dict[str, Any]] = []
    directories = []
    allocated = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        _regular_ancestors(directory)
        allocated += directory.lstat().st_blocks * 512
        directories.append(directory.relative_to(root).as_posix())
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda item: item.name)
        for child in children:
            path = Path(child.path)
            metadata = child.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                _require(not target or metadata.st_nlink == 1, f"hardlinked target file: {path}")
                row = {"path": path.relative_to(root).as_posix(), "bytes": metadata.st_size,
                       "du_bytes": metadata.st_blocks * 512}
                if hashes:
                    row["sha256"] = _hash(path)
                files.append(row)
                allocated += row["du_bytes"]
            else:
                raise StorageError(f"storage contains a symlink or special file: {path}")
    files.sort(key=lambda row: row["path"])
    directories.sort()
    names = hashlib.sha256()
    for row in files:
        names.update(row["path"].encode("utf-8", "surrogateescape") + b"\0")
    result = {"path": str(root), "file_count": len(files), "directory_count": len(directories),
              "logical_bytes": sum(row["bytes"] for row in files), "du_bytes": allocated,
              "file_list_sha256": names.hexdigest(), "files": files, "directories": directories}
    if hashes:
        result["tree_sha256"] = _digest({"directories": directories,
            "files": [{key: row[key] for key in ("path", "bytes", "sha256")} for row in files]})
    return result


def scan_allocated(source: Path) -> dict[str, Any]:
    """Read metadata only; return counts/allocated bytes without opening files."""
    result = _inventory(source, hashes=False)
    return {key: value for key, value in result.items() if key not in {"files", "directories"}}


def _publish_new(temporary: Path, path: Path) -> None:
    """Atomically rename without replacing an existing path, including a link."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        # RENAME_EXCL from the platform's sys/stdio.h.
        result = rename(os.fsencode(temporary), os.fsencode(path), 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        # AT_FDCWD and RENAME_NOREPLACE; absolute paths make cwd irrelevant.
        result = rename(-100, os.fsencode(temporary), -100, os.fsencode(path), 1)
    else:
        raise StorageError("atomic exclusive rename is unavailable on this platform")
    if result != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), str(path))


def _write_new(path: Path, value: dict[str, Any]) -> str:
    _regular_ancestors(path.parent)
    # A crash can leave an incomplete uniquely named temporary record. Keep it
    # for audit and publish a new complete record on resume; never replace it.
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    _publish_new(temporary, path)
    return _hash(path)


def _read_record(path: Path) -> dict[str, Any]:
    _regular_ancestors(path.parent)
    _require(path.is_file() and not path.is_symlink() and path.lstat().st_nlink == 1,
             f"unsafe seed record: {path}")
    return json.loads(path.read_bytes())


def _copy_file(source: Path, target: Path, expected: dict[str, Any]) -> int:
    """Verify any existing prefix and append only; an incomplete file is never erased."""
    _regular_ancestors(source.parent)
    _regular_ancestors(target.parent)
    offset = 0
    if target.exists() or target.is_symlink():
        metadata = target.lstat()
        _require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
                 f"unsafe partial target file: {target}")
        offset = metadata.st_size
        _require(offset <= expected["bytes"], f"partial target is larger than source: {target}")
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(source_fd, "rb") as incoming:
        source_stat = os.fstat(incoming.fileno())
        _require(stat.S_ISREG(source_stat.st_mode) and source_stat.st_size == expected["bytes"],
                 f"source file changed before copying: {source}")
        if offset:
            target_fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(target_fd, "rb") as existing:
                remaining = offset
                while remaining:
                    amount = min(CHUNK, remaining)
                    _require(existing.read(amount) == incoming.read(amount),
                             f"partial target prefix differs: {target}")
                    remaining -= amount
        flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_APPEND
        if not target.exists():
            flags |= os.O_CREAT | os.O_EXCL
        target_fd = os.open(target, flags, 0o600)
        with os.fdopen(target_fd, "ab") as outgoing:
            metadata = os.fstat(outgoing.fileno())
            _require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and metadata.st_size == offset,
                     f"partial target changed before append: {target}")
            for chunk in iter(lambda: incoming.read(CHUNK), b""):
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        _require(_hash(source) == expected["sha256"], f"source changed while copying: {source}")
        _require(_hash(target) == expected["sha256"], f"copied file SHA differs: {target}")
        return expected["bytes"] - offset


def clone_storage_tree(source: Path, target: Path, boundary: Path, records: Path) -> dict[str, Any]:
    """Seed one new v3 cache/store without modifying any existing source/output.

    A finalized receipt is reused without refreshing files, which may have since
    been updated by the engine. Interrupted staging files resume by prefix check.
    """
    _regular_ancestors(source)
    _regular_ancestors(boundary, absent_ok=True)
    _require(target.is_absolute() and target != boundary and target.is_relative_to(boundary),
             "seed target must be strictly inside the dedicated v3 boundary")
    _regular_ancestors(target, absent_ok=True)
    _require(source != target and not target.is_relative_to(source) and not source.is_relative_to(target),
             "seed source and target trees must be separate")
    staging = target.with_name(target.name + ".seed-v3")
    _require(staging.is_relative_to(boundary), "staging target escaped v3 boundary")
    _regular_ancestors(staging, absent_ok=True)
    _regular_ancestors(records, absent_ok=True)
    _require(not any(records == root or records.is_relative_to(root) for root in (source, target, staging)),
             "seed records must be outside source and target trees")
    token = hashlib.sha256(str(target).encode()).hexdigest()
    before_path = records / f"{token}-before.json"
    after_path = records / f"{token}-after.json"
    identity = {"source": str(source), "target": str(target), "boundary": str(boundary),
                "staging_path": str(staging)}
    if after_path.exists() or after_path.is_symlink():
        before = _read_record(before_path)
        after = _read_record(after_path)
        _require(before.get("kind") == "n6_a_aq_storage_seed_before" and
                 all(before.get(key) == value for key, value in identity.items()), "seed source binding differs")
        _require(after.get("kind") == "n6_a_aq_storage_seed_after" and
                 after.get("before_sha256") == _hash(before_path) and
                 all(after.get(key) == value for key, value in identity.items()), "seed completion binding differs")
        _regular_ancestors(target)
        current = target.lstat()
        _require(after.get("target_identity") == [current.st_dev, current.st_ino],
                 "finalized seed target was replaced")
        _inventory(target, hashes=False, target=True)
        _require(not staging.exists(), "finalized target still has staging tree")
        return {**after, "status": "reused", "after_path": str(after_path), "after_sha256": _hash(after_path)}
    if before_path.exists() or before_path.is_symlink():
        before = _read_record(before_path)
        _require(before.get("kind") == "n6_a_aq_storage_seed_before" and
                 all(before.get(key) == value for key, value in identity.items()), "seed source binding differs")
        source_inventory = _inventory(source, hashes=True)
        _require(source_inventory["tree_sha256"] == before["inventory"]["tree_sha256"],
                 "source changed since immutable seed manifest")
    else:
        _require(not target.exists() and not staging.exists(), "unowned seed target already exists")
        source_inventory = _inventory(source, hashes=True)
        records.mkdir(parents=True, exist_ok=True)
        before = {"schema_version": 1, "kind": "n6_a_aq_storage_seed_before",
                  "recorded_at": datetime.now(timezone.utc).isoformat(), **identity,
                  "inventory": source_inventory}
        _write_new(before_path, before)
    before_sha = _hash(before_path)
    copied_bytes = 0
    if not target.exists():
        staging.mkdir(parents=True, exist_ok=True)
        staged = _inventory(staging, hashes=False, target=True)
        expected = {row["path"]: row for row in source_inventory["files"]}
        _require(set(staged["directories"]) <= set(source_inventory["directories"]), "unknown staging directory")
        _require(all(row["path"] in expected and row["bytes"] <= expected[row["path"]]["bytes"]
                     for row in staged["files"]), "unknown or oversized staging file")
        for relative in source_inventory["directories"]:
            directory = staging / relative
            _regular_ancestors(directory, absent_ok=True)
            directory.mkdir(parents=True, exist_ok=True)
        for entry in source_inventory["files"]:
            copied_bytes += _copy_file(source / entry["path"], staging / entry["path"], entry)
        staged = _inventory(staging, hashes=True, target=True)
        _require(staged["tree_sha256"] == source_inventory["tree_sha256"], "staged copy SHA differs")
        _require(not target.exists() and not target.is_symlink(), "seed target appeared during copy")
        _publish_new(staging, target)
    else:
        _require(not staging.exists(), "both target and partial staging exist")
    destination = _inventory(target, hashes=True, target=True)
    _require(destination["tree_sha256"] == source_inventory["tree_sha256"], "published seed SHA differs")
    final_source = _inventory(source, hashes=True)
    _require(final_source["tree_sha256"] == source_inventory["tree_sha256"], "source changed before seed completion")
    metadata = target.lstat()
    receipt = {"schema_version": 1, "kind": "n6_a_aq_storage_seed_after", "status": "seeded",
               "recorded_at": datetime.now(timezone.utc).isoformat(), **identity,
               "before_path": str(before_path), "before_sha256": before_sha,
               "source_tree_sha256": source_inventory["tree_sha256"],
               "target_tree_sha256": destination["tree_sha256"],
               "file_count": destination["file_count"], "directory_count": destination["directory_count"],
               "file_list_sha256": destination["file_list_sha256"],
               "logical_bytes": destination["logical_bytes"],
               "source_du_bytes": source_inventory["du_bytes"], "target_du_bytes": destination["du_bytes"],
               "target_identity": [metadata.st_dev, metadata.st_ino], "copied_bytes": copied_bytes}
    after_sha = _write_new(after_path, receipt)
    return {**receipt, "after_path": str(after_path), "after_sha256": after_sha}
