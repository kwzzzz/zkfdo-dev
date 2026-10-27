#!/usr/bin/env python3
"""Delete only approved B6h external cleanup targets after metadata recording.

The target tree is inventoried by names and stat metadata; no target file is
opened. The CLI never traverses runs/ and never accepts an A calibration root.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import n6_b6h_cleanup as cleanup


ROOT = Path(__file__).resolve().parents[1]
VOLUME = Path("/Volumes/zkfdo-jcache")
APPROVAL_ROOT = ROOT / "runs/n6-b6h-2026-10-24.noindex"
RECORD_OUT = APPROVAL_ROOT / "cleanup-records"
B6G = VOLUME / "n6-b6g-batch1x"
FULL = "full-v2.2.noindex"
FIRST_39 = B6G / "hint-workspaces" / FULL / "main/0005/requests/000039"
CACHE_39 = B6G / "cache/full-v2.2/main/0005"
START_39 = datetime(2026, 10, 24, 1, 19, 45,
                    tzinfo=timezone(timedelta(hours=9))).timestamp()
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

LEGACY = {
    VOLUME / f"n6-{label}-batch1x" / subdir: (
        "legacy_cache" if subdir == "cache" else "legacy_workspace")
    for label in ("b6b", "b6e", "b6f")
    for subdir in ("cache", "hint-workspaces")
}
LEGACY[VOLUME / "n6-b6-batch1x/pilot-v2.2"] = "legacy_cache"


def _dynamic_entry(path: Path, category: str,
                   approvals: dict[tuple[str, str], dict[str, Any]]) -> None:
    item = approvals.get((str(path), category))
    if item is None:
        raise cleanup.CleanupError("target is absent from the pinned approval listing")
    recorded_birth = item.get("birthtime_unix")
    if category == "abandoned_cache" and type(recorded_birth) not in (int, float):
        raise cleanup.CleanupError("cache fragment approval lacks exact birthtime")
    if category == "revision_store" and path.exists() and \
            type(recorded_birth) not in (int, float):
        raise cleanup.CleanupError("existing revision store approval lacks exact birthtime")
    if recorded_birth is not None:
        if type(recorded_birth) not in (int, float) or not path.exists() or \
                path.lstat().st_birthtime != recorded_birth:
            raise cleanup.CleanupError("target birthtime differs from approval listing")


def approved(path: Path, category: str,
             approvals: dict[tuple[str, str], dict[str, Any]]) -> None:
    if not path.is_absolute() or ".." in path.parts or \
            not path.is_relative_to(VOLUME) or "n6-b6-acal" in path.parts:
        raise cleanup.CleanupError("cleanup path is not an approved external absolute path")
    if path in LEGACY and category == LEGACY[path]:
        return
    if path == FIRST_39 and category == "abandoned_workspace":
        return
    for ordinal in range(1, 5):
        revision = f"main/{ordinal:04d}"
        if (category == "revision_cache" and path ==
                B6G / "cache/full-v2.2" / revision):
            return
        if (category == "revision_store" and path ==
                B6G / "instance-stores" / FULL / revision / "store"):
            _dynamic_entry(path, category, approvals)
            return
    if category == "selective_request_workspace" and path in {
        B6G / "hint-workspaces" / FULL / "main/0005/requests/000037",
        B6G / "hint-workspaces" / FULL / "main/0005/requests/000038",
    }:
        _dynamic_entry(path, "request_workspace", approvals)
        item = approvals[(str(path), "request_workspace")]
        if type(item.get("birthtime_unix")) not in (int, float):
            raise cleanup.CleanupError("selective request approval lacks exact birthtime")
        summary, _, _ = cleanup.inventory(VOLUME, path)
        if (item.get("precleanup_file_count") != summary["file_count"] or
                item.get("precleanup_file_list_sha256") != summary["file_list_sha256"] or
                item.get("precleanup_du_kib") != summary["du_bytes"] // 1024):
            raise cleanup.CleanupError("selective request metadata differs from approval")
        return
    completed_root = B6G / "hint-workspaces" / FULL
    try:
        relative = path.relative_to(completed_root)
    except ValueError:
        relative = None
    if category == "request_workspace" and relative is not None:
        parts = relative.parts
        if (len(parts) == 4 and parts[0] == "main" and
                parts[1] in {f"{i:04d}" for i in range(1, 6)} and
                parts[2] == "requests" and re.fullmatch(r"\d{6}", parts[3]) and
                0 <= int(parts[3]) <= 36):
            _dynamic_entry(path, category, approvals)
            return
    if category == "abandoned_cache":
        try:
            pieces = path.relative_to(CACHE_39).parts
        except ValueError:
            pieces = ()
        if ((len(pieces) == 1 and HEX64.fullmatch(pieces[0])) or
                (len(pieces) == 2 and pieces[0] == "edits" and
                 HEX64.fullmatch(pieces[1]))):
            _dynamic_entry(path, category, approvals)
            if path.lstat().st_birthtime < START_39:
                raise cleanup.CleanupError("cache fragment predates request 39")
            return
    raise cleanup.CleanupError("target is not in the B6h deletion allowlist")


def load_approvals(path: Path | None, expected_sha: str | None) -> dict[tuple[str, str], dict[str, Any]]:
    if path is None:
        if expected_sha is not None:
            raise cleanup.CleanupError("approval SHA supplied without listing")
        return {}
    if not path.is_absolute() or not path.is_file() or path.is_symlink() or \
            not path.is_relative_to(APPROVAL_ROOT):
        raise cleanup.CleanupError("approval listing must be a new B6h runs/ file")
    if expected_sha is None or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise cleanup.CleanupError("approval listing requires its SHA-256")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise cleanup.CleanupError("approval listing SHA-256 differs")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != 1 or \
            value.get("kind") != "n6_b6h_approved_external_targets" or \
            not isinstance(value.get("targets"), list):
        raise cleanup.CleanupError("approval listing schema differs")
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for item in value["targets"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or \
                not isinstance(item.get("category"), str):
            raise cleanup.CleanupError("approval listing row malformed")
        key = (item["path"], item["category"])
        if key in rows:
            raise cleanup.CleanupError("duplicate approval listing target")
        rows[key] = item
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--category", choices=(
        "legacy_cache", "legacy_workspace", "request_workspace",
        "revision_cache", "revision_store", "abandoned_workspace",
        "abandoned_cache", "selective_request_workspace"), required=True)
    parser.add_argument("--approved-targets", type=Path)
    parser.add_argument("--approved-targets-sha256")
    args = parser.parse_args(argv)
    try:
        if not os.path.ismount(VOLUME):
            raise cleanup.CleanupError("zkfdo-jcache must be mounted")
        approvals = load_approvals(args.approved_targets,
                                   args.approved_targets_sha256)
        approved(args.target, args.category, approvals)
        identity = {"source": "n6_b6h_cleanup_cli",
                    "approved_targets_sha256": args.approved_targets_sha256}
        if args.category == "selective_request_workspace":
            result = cleanup.cleanup_request_workspace(
                VOLUME, args.target, RECORD_OUT, identity,
                preserve_v22_evidence=True)
        else:
            result = cleanup.cleanup_tree(
                VOLUME, args.target, RECORD_OUT, args.category, identity)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"B6h cleanup refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
