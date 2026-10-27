#!/usr/bin/env python3
"""Audited, link-safe cleanup for the A aq v2 runner's dedicated trees.

Only names and filesystem metadata are inspected. The caller supplies its locked
A boundary and durable result/metrics bindings; this module never opens evidence.
Every invocation has fresh immutable records, including recovery after a partial
deletion. The old one-off scanner supplies the link-as-link traversal policy.
"""

from __future__ import annotations

from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
from uuid import uuid4

import n6_a_aq_workspace_cleanup as legacy
from n6_b6h_cleanup import _v22_store_evidence_name


class CleanupError(ValueError):
    """A path, inventory, or deletion consistency check failed."""


def _regular_ancestors(path: Path, *, absent_ok: bool = False) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise CleanupError(f"cleanup path must be absolute and normalized: {path}")
    for part in reversed((path, *path.parents)):
        try:
            metadata = part.lstat()
        except FileNotFoundError:
            if absent_ok:
                continue
            raise CleanupError(f"cleanup ancestor is absent: {part}") from None
        if not stat.S_ISDIR(metadata.st_mode):
            raise CleanupError(f"cleanup root/ancestor is not a regular directory: {part}")


def _name_hash(names: list[str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(names):
        digest.update(name.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
    return digest.hexdigest()


def _retained_name(target: Path, relative: Path) -> bool:
    # The one-off cleans a whole request directory, while the v2 runner cleans
    # one attempt. Feed the same exact pinned matcher its expected shape.
    if re.fullmatch(r"attempt-[0-9]{4}", target.name):
        relative = Path(target.name) / relative
    return _v22_store_evidence_name(relative)


def _subset(entries: dict[str, dict[str, Any]], names: list[str]) -> dict[str, Any]:
    return {
        "file_count": sum(entries[name]["kind"] == "file" for name in names),
        "link_count": sum(entries[name]["kind"] == "link" for name in names),
        "logical_bytes": sum(entries[name]["size"] for name in names),
        "du_bytes": sum(entries[name]["blocks"] * 512 for name in names),
        "file_list_sha256": _name_hash(names),
    }


def _inventory(target: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[Path]]:
    _regular_ancestors(target.parent, absent_ok=True)
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        empty = _subset({}, [])
        return ({"path": str(target), "present": False, **empty,
                 "directory_count": 0, "retained_evidence": empty}, {}, [])
    if not stat.S_ISDIR(metadata.st_mode):
        raise CleanupError(f"cleanup target is not a regular directory: {target}")
    try:
        keep, drop, links, directories = legacy.scan(target)
    except (OSError, SystemExit) as error:
        raise CleanupError(f"workspace inventory failed: {error}") from error
    entries: dict[str, dict[str, Any]] = {}
    retained = {path for path, _ in [*keep, *drop]
                if _retained_name(target, path.relative_to(target))}
    for path in [*(path for path, _ in keep), *(path for path, _ in drop), *links]:
        _regular_ancestors(path.parent)
        current = path.lstat()
        kind = "link" if stat.S_ISLNK(current.st_mode) else "file" if stat.S_ISREG(current.st_mode) else None
        if kind is None or ((path in links) != (kind == "link")):
            raise CleanupError(f"workspace entry changed type: {path}")
        entries[path.relative_to(target).as_posix()] = {
            "kind": kind, "size": current.st_size, "blocks": current.st_blocks,
            "device": current.st_dev, "inode": current.st_ino,
            "mtime_ns": current.st_mtime_ns,
        }
    directories = [target, *directories]
    directory_bytes = 0
    for directory in directories:
        _regular_ancestors(directory)
        directory_bytes += directory.lstat().st_blocks * 512
    summary = {"path": str(target), "present": True,
               **_subset(entries, list(entries)), "directory_count": len(directories)}
    summary["du_bytes"] += directory_bytes
    summary["retained_evidence"] = _subset(
        entries, [path.relative_to(target).as_posix() for path in retained])
    return summary, entries, directories


def scan_stats(target: Path) -> dict[str, Any]:
    """Return allocated-byte totals without following or opening any link/file."""
    return _inventory(target)[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, value: dict[str, Any]) -> str:
    _regular_ancestors(path.parent)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return _sha256(path)


def cleanup_tree(target: Path, boundary: Path, records: Path,
                 binding: dict[str, Any], retain: bool) -> dict[str, Any]:
    """Delete one bounded tree after recording its inventory and durable bindings.

    ``retain=True`` preserves only regular files matching the pinned v2.2 store
    rule. Links are always unlinked themselves. ``retain=False`` also supports
    caller-authorized A revision cache/store cleanup. The runner must pass its
    locked A external root as ``boundary`` and must not call this for active work.
    """
    _regular_ancestors(boundary)
    if target == boundary or not target.is_relative_to(boundary):
        raise CleanupError("cleanup target is outside its dedicated A boundary")
    _regular_ancestors(target, absent_ok=True)
    _regular_ancestors(records, absent_ok=True)
    if records == target or records.is_relative_to(target):
        raise CleanupError("cleanup records must be outside the deleted tree")
    records.mkdir(parents=True, exist_ok=True)
    _regular_ancestors(records)
    before, entries, directories = _inventory(target)
    kept = [name for name, value in entries.items()
            if retain and value["kind"] == "file" and _retained_name(target, Path(name))]
    kept_set = set(kept)
    deleted = [name for name in entries if name not in kept_set]
    retained_summary = _subset(entries, kept)
    deleted_summary = _subset(entries, deleted)
    token = uuid4().hex
    before_path = records / f"{token}-before.json"
    before_record = {
        "schema_version": 1, "kind": "n6_a_aq_cleanup_before_delete",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "boundary": str(boundary), "binding": binding, "retain": retain,
        **before, "retained_evidence": retained_summary,
        "deleted_files": deleted_summary, "entries": entries,
    }
    before_sha = _write_new(before_path, before_record)
    again, current_entries, _ = _inventory(target)
    if again != before or current_entries != entries:
        raise CleanupError("workspace changed after its before record was saved")
    for name in sorted(deleted, key=lambda item: (entries[item]["kind"] != "link", item)):
        path = target / name
        _regular_ancestors(path.parent)
        current = path.lstat()
        expected = entries[name]
        expected_type = stat.S_ISLNK if expected["kind"] == "link" else stat.S_ISREG
        if not expected_type(current.st_mode) or (current.st_dev, current.st_ino, current.st_size,
                current.st_blocks, current.st_mtime_ns) != (
                expected["device"], expected["inode"], expected["size"],
                expected["blocks"], expected["mtime_ns"]):
            raise CleanupError(f"workspace entry changed before deletion: {path}")
        path.unlink()
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _regular_ancestors(directory)
        try:
            directory.rmdir()
        except OSError as error:
            if error.errno != errno.ENOTEMPTY:
                raise
    after, remaining, _ = _inventory(target)
    if remaining != {name: entries[name] for name in kept}:
        raise CleanupError("workspace retained files differ after deletion")
    if not kept and after["present"]:
        raise CleanupError("empty workspace remains after deletion")
    status = "retained_evidence" if kept else "deleted" if before["present"] else "absent"
    after_path = records / f"{token}-after.json"
    after_record = {
        "schema_version": 1, "kind": "n6_a_aq_cleanup_after_delete",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": status,
        "binding": binding, "before_path": str(before_path), "before_sha256": before_sha,
        "before": before, "after": after, "deleted_files": deleted_summary,
        "retained_evidence": retained_summary,
        "freed_du_bytes": max(0, before["du_bytes"] - after["du_bytes"]),
    }
    after_sha = _write_new(after_path, after_record)
    return {"status": status, **before, "before_path": str(before_path),
            "before_sha256": before_sha, "after_path": str(after_path),
            "after_sha256": after_sha, "binding": binding,
            "deleted_files": deleted_summary, "retained_evidence": retained_summary,
            "freed_du_bytes": after_record["freed_du_bytes"], "after": after}
