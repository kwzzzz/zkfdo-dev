#!/usr/bin/env python3
"""Validate B6b staged sources against the frozen W/S source specifications.

The original J runner requires source_root to be the common parent of the
original W and S files. B6b preserves those source bindings, then checks the
new, bounded copy used by each request. This module changes no engine behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

import run_n6_j1 as runner


ORIGINAL_VALIDATE_SOURCE_BINDINGS = runner.validate_source_bindings
KEY = re.compile(r"[0-9a-f]{16}\Z")


def _circom_files(root: Path) -> list[Path]:
    files = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if not (Path(directory) / name).is_symlink())
        for name in sorted(filenames):
            path = Path(directory) / name
            if path.suffix == ".circom":
                runner.require(path.is_file(), "staged Circom source unreadable")
                files.append(path)
    return files


def _verify_staged_tree(source_root: Path, revision: str,
                        w_root: Path, method_root: Path) -> None:
    expected_files = []
    for label, original_root in (("project", w_root), ("wrapper", method_root)):
        for original in _circom_files(original_root):
            relative = Path(label) / original.relative_to(original_root)
            digest = runner.sha256(original)
            staged = source_root / relative
            runner.require(staged.is_file() and not staged.is_symlink() and
                           staged.resolve() == staged and runner.sha256(staged) == digest,
                           "B6b staged Circom tree differs from frozen source")
            expected_files.append({"path": str(relative), "source": str(original),
                                   "sha256": digest})
    actual_files = _circom_files(source_root)
    runner.require({str(path.relative_to(source_root)) for path in actual_files} ==
                   {item["path"] for item in expected_files},
                   "B6b staged Circom file set differs from frozen source")
    manifest = {"schema_version": 1, "revision_id": revision,
                "project_root": str(w_root), "wrapper_root": str(method_root),
                "files": expected_files}
    manifest_path = source_root / "source-staging.json"
    runner.require(manifest_path.is_file() and not manifest_path.is_symlink() and
                   json.loads(manifest_path.read_text()) == manifest,
                   "B6b source staging manifest differs")


def _snapshot_root(spec: dict[str, Any], target: dict[str, Any]) -> Path:
    snapshots = spec.get("source_snapshots")
    runner.require(isinstance(snapshots, list), "staged source snapshots missing")
    matches = [item for item in snapshots if isinstance(item, dict) and
               item.get("id") == target.get("source_snapshot_id")]
    runner.require(len(matches) == 1 and isinstance(matches[0].get("path"), str),
                   "staged source snapshot ambiguous")
    return Path(matches[0]["path"]).resolve()


def _staged_file(source_root: Path, part: str, original: Path,
                 snapshot_root: Path) -> Path:
    runner.require(original.is_relative_to(snapshot_root),
                   "original source outside its frozen snapshot")
    expected = source_root / part / original.relative_to(snapshot_root)
    runner.require(expected.is_file() and expected.resolve() == expected,
                   "staged source file missing or redirected")
    return expected


def validate_staged_source_bindings(index_rows: list[dict[str, Any]],
                                    inventory: dict[str, Any],
                                    requests: list[dict[str, Any]],
                                    staging_root: Path) -> None:
    """Check original provenance and exact staged W/S paths without candidate values."""
    staging_root = staging_root.resolve()
    runner.require(staging_root.is_dir(), "B6b source staging root missing")
    runner.require(len(index_rows) == len(requests), "B6b request count differs")

    # Reconstruct the frozen paths only for the existing source-binding gate.
    # It still verifies W/S specs, their target IDs, library order, and every
    # original snapshot tree SHA-256; no verdict or candidate field is read here.
    original_requests = []
    for row, request in zip(index_rows, requests):
        entry_text = row.get("original_entrypoint")
        wrapper_text = row.get("original_component_wrapper")
        runner.require(isinstance(entry_text, str) and Path(entry_text).is_absolute() and
                       isinstance(wrapper_text, str) and Path(wrapper_text).is_absolute(),
                       "B6b original source path metadata missing")
        original_entry = Path(entry_text).resolve()
        original_wrapper = Path(wrapper_text).resolve()
        original_root = Path(os.path.commonpath((original_entry.parent,
                                                 original_wrapper.parent))).resolve()
        original_requests.append({**request, "source_root": str(original_root),
                                  "entrypoint": str(original_entry),
                                  "component_wrapper": str(original_wrapper)})
    ORIGINAL_VALIDATE_SOURCE_BINDINGS(index_rows, inventory, original_requests)

    source_rows = inventory["rows"]
    by_candidate = {item["candidate_sha256"]: item for item in source_rows}
    spec_cache: dict[Path, tuple[str, dict[str, Any]]] = {}
    verified_pairs: set[Path] = set()
    for row, request in zip(index_rows, requests):
        source = by_candidate[row["candidate_sha256"]]
        w_spec = runner.checked_spec(source["whole_spec"], source["whole_spec_sha256"],
                                     spec_cache)
        method_spec = (w_spec if row["method"] == "W" else
                       runner.checked_spec(source["split_spec"], source["split_spec_sha256"],
                                           spec_cache))
        w_target = w_spec["targets"][0]
        target = method_spec["targets"][source["target_index"]]
        w_root = _snapshot_root(w_spec, w_target)
        method_root = _snapshot_root(method_spec, target)
        pair_key = hashlib.sha256((str(w_root) + "\0" + str(method_root)).encode(
            "utf-8")).hexdigest()[:16]
        runner.require(KEY.fullmatch(pair_key) is not None, "invalid B6b source pair key")
        expected_root = staging_root / row["revision_id"] / pair_key
        supplied_root = Path(request.get("source_root", ""))
        runner.require(supplied_root.is_absolute() and supplied_root.is_dir() and
                       supplied_root.resolve() == expected_root and
                       not expected_root.is_relative_to(w_root) and
                       not expected_root.is_relative_to(method_root),
                       "B6b source root is not the bounded staged pair")
        original_entry = Path(row["original_entrypoint"]).resolve()
        original_wrapper = Path(row["original_component_wrapper"]).resolve()
        expected_entry = _staged_file(expected_root, "project", original_entry, w_root)
        expected_wrapper = _staged_file(expected_root, "wrapper", original_wrapper,
                                        method_root)
        runner.require(Path(request.get("entrypoint", "")).is_absolute() and
                       Path(request["entrypoint"]).resolve() == expected_entry and
                       Path(request.get("component_wrapper", "")).is_absolute() and
                       Path(request["component_wrapper"]).resolve() == expected_wrapper,
                       "B6b request does not name its staged W/S files")
        runner.checked_sha(original_entry, row["entrypoint_sha256"],
                           "frozen W entrypoint")
        runner.checked_sha(original_wrapper, row["component_wrapper_sha256"],
                           "frozen S wrapper")
        runner.checked_sha(expected_entry, row["entrypoint_sha256"],
                           "staged W entrypoint")
        runner.checked_sha(expected_wrapper, row["component_wrapper_sha256"],
                           "staged S wrapper")
        if expected_root not in verified_pairs:
            _verify_staged_tree(expected_root, row["revision_id"], w_root, method_root)
            verified_pairs.add(expected_root)


def install(staging_root: Path) -> None:
    """Install B6b's source gate for the existing validate-only/pilot runners."""
    runner.validate_source_bindings = lambda rows, inventory, requests: (
        validate_staged_source_bindings(rows, inventory, requests, staging_root))
