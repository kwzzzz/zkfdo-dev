#!/usr/bin/env python3
"""Metadata-only inventory, guarded cleanup, and disk thresholds for B6h J.

No file content beneath an external work, cache, or store root is read here.
The SHA-256 identifies sorted relative file names separated by NUL bytes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
import errno
from pathlib import Path
import shutil
import stat
from typing import Any
from uuid import uuid4


GIB = 1024**3
SSD_MIN_FREE_BYTES = 40 * GIB
INTERNAL_MIN_FREE_BYTES = 20 * GIB


class CleanupError(ValueError):
    """An inventory, path lock, or deletion safety check failed."""


class DiskGuardStop(CleanupError):
    """The next request cannot start with the measured free space."""


def disk_guard(output: Path, cache_root: Path, workspace_root: Path,
               instance_root: Path, observed_request_peak_bytes: int,
               retained_evidence_du_bytes: int = 0,
               other_engine_cache_growth_bytes: int = 0) -> dict[str, int]:
    if type(observed_request_peak_bytes) is not int or observed_request_peak_bytes <= 0:
        raise CleanupError("observed request peak must be a positive byte count")
    if type(retained_evidence_du_bytes) is not int or retained_evidence_du_bytes < 0:
        raise CleanupError("retained evidence reserve must be a nonnegative byte count")
    if type(other_engine_cache_growth_bytes) is not int or \
            other_engine_cache_growth_bytes < 0:
        raise CleanupError("other engine cache reserve must be a nonnegative byte count")
    required_ssd = max(2 * (observed_request_peak_bytes +
                            retained_evidence_du_bytes +
                            other_engine_cache_growth_bytes),
                       SSD_MIN_FREE_BYTES)
    free = {
        "output_free_bytes": shutil.disk_usage(output).free,
        "cache_free_bytes": shutil.disk_usage(cache_root).free,
        "workspace_free_bytes": shutil.disk_usage(workspace_root).free,
        "instance_free_bytes": shutil.disk_usage(instance_root).free,
        "required_ssd_free_bytes": required_ssd,
        "required_internal_free_bytes": INTERNAL_MIN_FREE_BYTES,
        "observed_request_peak_bytes": observed_request_peak_bytes,
        "retained_evidence_du_bytes": retained_evidence_du_bytes,
        "other_engine_cache_growth_bytes": other_engine_cache_growth_bytes,
    }
    if free["output_free_bytes"] < INTERNAL_MIN_FREE_BYTES:
        raise DiskGuardStop(f"internal disk below 20 GiB before next request: {free}")
    if min(free[key] for key in ("cache_free_bytes", "workspace_free_bytes",
                                 "instance_free_bytes")) < required_ssd:
        raise DiskGuardStop(f"SSD below request peak reserve before next request: {free}")
    return free


def _target(root: Path, candidate: Path) -> Path:
    if not root.is_absolute() or not candidate.is_absolute() or candidate == root or \
            not candidate.is_relative_to(root):
        raise CleanupError("cleanup target is outside its dedicated external root")
    current = candidate
    while current != root:
        if current.is_symlink():
            raise CleanupError("cleanup path contains a symlink")
        current = current.parent
    if root.is_symlink():
        raise CleanupError("cleanup root is a symlink")
    # Resolve only after rejecting links on the path. The inventory rejects
    # links at every descendant and never follows them.
    if not root.is_dir() or not candidate.is_dir() or \
            not candidate.resolve().is_relative_to(root.resolve()):
        raise CleanupError("cleanup target is missing or escaped its root")
    return candidate


def inventory(root: Path, target: Path) -> tuple[dict[str, Any], list[Path], list[Path]]:
    """Record names and filesystem metadata only; never open any target file."""
    target = _target(root, target)
    files: list[Path] = []
    directories: list[Path] = []
    listing: list[str] = []
    allocated = 0
    logical = 0
    pending = [target]
    while pending:
        directory = pending.pop()
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise CleanupError("cleanup tree changed while being inventoried")
        allocated += metadata.st_blocks * 512
        directories.append(directory)
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for child in children:
            path = Path(child.path)
            entry = child.stat(follow_symlinks=False)
            if stat.S_ISDIR(entry.st_mode):
                pending.append(path)
            elif stat.S_ISREG(entry.st_mode):
                files.append(path)
                logical += entry.st_size
                allocated += entry.st_blocks * 512
                listing.append(path.relative_to(target).as_posix())
            else:
                raise CleanupError("cleanup tree contains a link or special file")
    digest = hashlib.sha256()
    for name in sorted(listing):
        digest.update(name.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
    summary = {"path": str(target), "file_count": len(files),
               "directory_count": len(directories), "logical_bytes": logical,
               "du_bytes": allocated, "file_list_sha256": digest.hexdigest()}
    return summary, files, directories



_SITE = re.compile(r"site-[0-9]{3,}\Z")
_PREDICATE = re.compile(r"predicate-[0-9]{2,}\Z")
_ATTEMPT = re.compile(r"attempt-[0-9]{4}\Z")
_PREDICATE_EVIDENCE = frozenset({
    "class-o0.wtns", "found-input.json", "found.wtns",
    "exclusion-0.smt2", "exclusion-0.z3.log",
    "exclusion-1.smt2", "exclusion-1.z3.log",
})


def _v22_store_evidence_name(relative: Path) -> bool:
    """Exact names that the pinned v2.2 store_write can put in evidence_files."""
    parts = relative.parts
    if len(parts) < 4 or not _ATTEMPT.fullmatch(parts[0]) or parts[1] != "raw" or \
            not _SITE.fullmatch(parts[2]):
        return False
    if len(parts) == 4:
        return parts[3] in {"input.json", "honest.wtns"}
    return (len(parts) == 5 and _PREDICATE.fullmatch(parts[3]) is not None and
            parts[4] in _PREDICATE_EVIDENCE)


def _file_subset_summary(target: Path, files: list[Path]) -> dict[str, Any]:
    """Name hash and stat totals for selected regular files, without file reads."""
    digest = hashlib.sha256()
    logical = allocated = 0
    for path in sorted(files, key=lambda item: item.relative_to(target).as_posix()):
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise CleanupError("cleanup selected file changed type")
        relative = path.relative_to(target).as_posix()
        digest.update(relative.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        logical += metadata.st_size
        allocated += metadata.st_blocks * 512
    return {"file_count": len(files), "logical_bytes": logical,
            "du_bytes": allocated, "file_list_sha256": digest.hexdigest()}


def verify_retained_workspace(root: Path, target: Path,
                              expected: dict[str, Any]) -> None:
    """On resume, require that only the recorded v2.2 evidence remains."""
    if not isinstance(expected, dict):
        raise CleanupError("retained evidence summary is absent")
    _, files, _ = inventory(root, target)
    if not all(_v22_store_evidence_name(path.relative_to(target)) for path in files) or \
            _file_subset_summary(target, files) != expected:
        raise CleanupError("retained v2.2 evidence changed after cleanup")


def cleanup_request_workspace(root: Path, target: Path, record_root: Path,
                              identity: dict[str, Any],
                              *, preserve_v22_evidence: bool) -> dict[str, Any]:
    """Remove request bytes, retaining v2.2 store evidence at original paths."""
    if not preserve_v22_evidence:
        return cleanup_tree(root, target, record_root, "request_workspace", identity)
    if not record_root.is_absolute() or record_root.is_symlink():
        raise CleanupError("cleanup record root must be an absolute regular directory")
    record_root.mkdir(parents=True, exist_ok=True)
    if not target.exists() and not target.is_symlink():
        return {"status": "absent", "path": str(target), "du_bytes": 0,
                "file_count": 0, "file_list_sha256": None,
                "retained_evidence": _file_subset_summary(target, [])}
    summary, files, directories = inventory(root, target)
    retained = [path for path in files
                if _v22_store_evidence_name(path.relative_to(target))]
    retained_set = set(retained)
    to_delete = [path for path in files if path not in retained_set]
    retained_summary = _file_subset_summary(target, retained)
    deleted_summary = _file_subset_summary(target, to_delete)
    token = uuid4().hex
    manifest = record_root / "request_workspace" / f"{token}.json"
    _write_new_json(manifest, {
        "schema_version": 1, "kind": "n6_b6h_external_cleanup_before_delete",
        "category": "request_workspace",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity, **summary,
        "deleted_files": deleted_summary,
        "retained_evidence": retained_summary,
    })
    again, again_files, _ = inventory(root, target)
    if again != summary or \
            _file_subset_summary(target, [path for path in again_files
                                          if _v22_store_evidence_name(path.relative_to(target))]) != retained_summary or \
            _file_subset_summary(target, [path for path in again_files
                                          if not _v22_store_evidence_name(path.relative_to(target))]) != deleted_summary:
        raise CleanupError("request workspace changed after manifest was recorded")
    for path in sorted(to_delete, key=lambda item: item.as_posix(), reverse=True):
        if not stat.S_ISREG(path.lstat().st_mode):
            raise CleanupError("cleanup file changed before deletion")
        path.unlink()
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError as error:
            if error.errno != errno.ENOTEMPTY:
                raise
    if retained:
        verify_retained_workspace(root, target, retained_summary)
        status = "retained_evidence"
    else:
        if target.exists() or target.is_symlink():
            raise CleanupError("request workspace remains after full deletion")
        status = "deleted"
    completion = record_root / "request_workspace" / f"{token}-deleted.json"
    _write_new_json(completion, {
        "schema_version": 1, "kind": "n6_b6h_external_cleanup_deleted",
        "category": "request_workspace",
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest), "status": status,
        "deleted_files": deleted_summary,
        "retained_evidence": retained_summary,
        **summary,
    })
    return {"status": status, "manifest": str(manifest),
            "completion": str(completion), **summary,
            "deleted_files": deleted_summary,
            "retained_evidence": retained_summary}


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def cleanup_tree(root: Path, target: Path, record_root: Path, category: str,
                 identity: dict[str, Any]) -> dict[str, Any]:
    """Write a durable runs/ manifest, recheck metadata, then remove one tree."""
    if category not in {"request_workspace", "revision_cache", "revision_store",
                        "abandoned_workspace", "abandoned_cache",
                        "legacy_cache", "legacy_workspace", "revision_evidence"}:
        raise CleanupError("unrecognized cleanup category")
    if not record_root.is_absolute() or record_root.is_symlink():
        raise CleanupError("cleanup record root must be an absolute regular directory")
    record_root.mkdir(parents=True, exist_ok=True)
    if not target.exists() and not target.is_symlink():
        return {"status": "absent", "path": str(target), "du_bytes": 0,
                "file_count": 0, "file_list_sha256": None}
    summary, files, directories = inventory(root, target)
    token = uuid4().hex
    manifest = record_root / category / f"{token}.json"
    _write_new_json(manifest, {
        "schema_version": 1, "kind": "n6_b6h_external_cleanup_before_delete",
        "category": category, "recorded_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity, **summary,
    })
    again, _, _ = inventory(root, target)
    if again != summary:
        raise CleanupError("cleanup target changed after manifest was recorded")
    for path in sorted(files, key=lambda item: item.as_posix(), reverse=True):
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise CleanupError("cleanup file changed before deletion")
        path.unlink()
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        path.rmdir()
    completion = record_root / category / f"{token}-deleted.json"
    _write_new_json(completion, {
        "schema_version": 1, "kind": "n6_b6h_external_cleanup_deleted",
        "category": category, "deleted_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest), **summary,
    })
    return {"status": "deleted", "manifest": str(manifest),
            "completion": str(completion), **summary}
