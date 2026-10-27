#!/usr/bin/env python3
"""Bind B6d unit copies to the frozen B source specifications.

Only source paths and hashes are inspected here. Candidate file contents and
J result fields are outside this module's scope.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import run_n6_j1 as runner


ORIGINAL_VALIDATE_SOURCE_BINDINGS = runner.validate_source_bindings
EXPECTED_SCHEMA = "n6-b6d-unit-staging-v1"


def _absolute_path(value: Any, label: str) -> Path:
    runner.require(isinstance(value, str) and Path(value).is_absolute(),
                   f"{label} is not an absolute path")
    path = Path(value)
    runner.require(path.resolve() == path, f"{label} is redirected: {path}")
    return path


def _regular_file(path: Path, label: str) -> None:
    runner.require(path.is_file() and not path.is_symlink(),
                   f"{label} is missing or linked: {path}")


def _pair_rows(manifest: dict[str, Any], staging_root: Path) -> dict[int, dict[str, Any]]:
    pairs = manifest.get("pairs")
    runner.require(manifest.get("schema_version") == 1 and
                   manifest.get("schema") == EXPECTED_SCHEMA and
                   manifest.get("request_count") == 107 and
                   manifest.get("pair_count") == 17 and
                   isinstance(pairs, list) and len(pairs) == 17,
                   "B6d unit manifest envelope invalid")
    by_queue: dict[int, dict[str, Any]] = {}
    pair_ids: set[str] = set()
    for pair in pairs:
        runner.require(isinstance(pair, dict), "B6d unit pair invalid")
        pair_id = pair.get("pair_id")
        runner.require(isinstance(pair_id, str) and pair_id and pair_id not in pair_ids,
                       "B6d unit pair ID duplicate or missing")
        pair_ids.add(pair_id)
        unit = _absolute_path(pair.get("source_root"), "B6d unit source root")
        runner.require(unit.parent == staging_root and unit.is_dir() and
                       not unit.is_symlink(), "B6d unit is outside its staging root")
        runner.require(_absolute_path(pair.get("project_root"), "B6d project root") ==
                       unit / "project" and
                       _absolute_path(pair.get("preparation_root"), "B6d preparation root") ==
                       unit / "preparation", "B6d unit layout differs")
        orders = pair.get("queue_orders")
        runner.require(isinstance(orders, list) and orders and
                       all(type(order) is int and 0 <= order < 107 for order in orders),
                       "B6d pair queue orders invalid")
        for order in orders:
            runner.require(order not in by_queue, "B6d queue assigned to two units")
            by_queue[order] = pair
    runner.require(set(by_queue) == set(range(107)),
                   "B6d unit manifest does not cover 107 requests")
    return by_queue


def _validate_pair_files(pair: dict[str, Any]) -> None:
    """Hash every unit file once, rejecting source symlinks and missing files."""
    root = _absolute_path(pair["source_root"], "B6d unit")
    project = root / "project"
    preparation = root / "preparation"
    wrapper = _absolute_path(pair.get("wrapper"), "B6d staged wrapper")
    entrypoint = _absolute_path(pair.get("entrypoint"), "B6d staged entrypoint")
    runner.require(wrapper.is_relative_to(preparation) and
                   entrypoint.is_relative_to(project),
                   "B6d W/S paths are outside project/preparation")
    for path, sha, label in ((wrapper, pair.get("wrapper_sha256"), "B6d wrapper"),
                             (entrypoint, pair.get("entrypoint_sha256"), "B6d entrypoint")):
        _regular_file(path, label)
        runner.checked_sha(path, sha, label)
    original_wrapper = _absolute_path(pair.get("original_wrapper"), "original wrapper")
    original_entry = _absolute_path(pair.get("original_entrypoint"), "original entrypoint")
    for path, sha, label in ((original_wrapper, pair.get("original_wrapper_sha256"),
                              "frozen wrapper"),
                             (original_entry, pair.get("entrypoint_sha256"),
                              "frozen entrypoint")):
        _regular_file(path, label)
        runner.checked_sha(path, sha, label)
    clone_root = _absolute_path(pair.get("original_clone_root"), "original clone")
    original_libraries = pair.get("original_library_paths")
    staged_libraries = pair.get("library_paths")
    runner.require(isinstance(original_libraries, list) and
                   isinstance(staged_libraries, list) and original_libraries and
                   len(original_libraries) == len(staged_libraries),
                   "B6d ordered library lists differ")
    for original_text, staged_text in zip(original_libraries, staged_libraries):
        original = _absolute_path(original_text, "original -l")
        staged = _absolute_path(staged_text, "staged -l")
        runner.require(original.is_dir() and staged.is_dir(),
                       "B6d -l directory missing")
        expected = project / original.relative_to(clone_root) if original.is_relative_to(
            clone_root) else original
        runner.require(staged == expected,
                       "B6d -l order or original-clone relocation differs")
    files = pair.get("project_files")
    runner.require(isinstance(files, list) and files,
                   "B6d project file manifest missing")
    listed: set[Path] = set()
    for item in files:
        runner.require(isinstance(item, dict), "B6d project file row invalid")
        rel_text = item.get("path")
        runner.require(isinstance(rel_text, str) and rel_text and
                       not Path(rel_text).is_absolute() and ".." not in Path(rel_text).parts,
                       "B6d project file relative path invalid")
        rel = Path(rel_text)
        runner.require(rel not in listed, "B6d project file listed twice")
        listed.add(rel)
        staged_file = project / rel
        original_file = clone_root / rel
        _regular_file(staged_file, "B6d project file")
        _regular_file(original_file, "original project file")
        runner.checked_sha(staged_file, item.get("staged_sha256", ""),
                           "B6d project file")
        runner.checked_sha(original_file, item.get("original_sha256", ""),
                           "original project file")
    runner.require(entrypoint.relative_to(project) in listed,
                   "B6d entrypoint omitted from project file manifest")
    actual: set[Path] = set()
    for directory, dirs, names in os.walk(project, followlinks=False):
        for name in dirs:
            runner.require(not (Path(directory) / name).is_symlink(),
                           "B6d project directory is a symlink")
        for name in names:
            path = Path(directory) / name
            _regular_file(path, "B6d project file")
            actual.add(path.relative_to(project))
    runner.require(actual == listed, "B6d unit project file set changed")


def validate_staged_source_bindings(index_rows: list[dict[str, Any]],
                                    inventory: dict[str, Any],
                                    requests: list[dict[str, Any]],
                                    staging_root: Path,
                                    manifest: dict[str, Any]) -> None:
    """Verify original spec pins and the staged unit path mapping."""
    root = staging_root.resolve()
    runner.require(root.is_dir() and not root.is_symlink(),
                   "B6d unit staging root missing or linked")
    runner.require(len(index_rows) == len(requests) == 107,
                   "B6d source validation requires 107 rows")
    by_queue = _pair_rows(manifest, root)
    original_rows: list[dict[str, Any]] = []
    original_requests: list[dict[str, Any]] = []
    checked_pairs: set[str] = set()
    for position, (row, request) in enumerate(zip(index_rows, requests)):
        pair = by_queue[position]
        runner.require(row.get("queue_order") == position and
                       row.get("revision_id") == pair.get("revision_id"),
                       "B6d request/pair revision or order mismatch")
        original_entry = _absolute_path(row.get("original_entrypoint"),
                                        "B6d original entrypoint")
        original_wrapper = _absolute_path(row.get("original_component_wrapper"),
                                          "B6d original wrapper")
        original_sha = row.get("original_component_wrapper_sha256")
        runner.require(isinstance(original_sha, str) and len(original_sha) == 64 and
                       original_entry == _absolute_path(pair.get("original_entrypoint"),
                                                       "pair original entrypoint") and
                       original_wrapper == _absolute_path(pair.get("original_wrapper"),
                                                         "pair original wrapper") and
                       original_sha == pair.get("original_wrapper_sha256"),
                       "B6d original W/S binding differs")
        old_libraries = row.get("original_library_paths")
        runner.require(old_libraries == pair.get("original_library_paths"),
                       "B6d original library list differs")
        old_root = Path(os.path.commonpath((original_entry.parent,
                                           original_wrapper.parent))).resolve()
        original_rows.append({**row, "component_wrapper_sha256": original_sha})
        original_requests.append({**request, "source_root": str(old_root),
                                  "entrypoint": str(original_entry),
                                  "component_wrapper": str(original_wrapper),
                                  "library_paths": old_libraries})
        runner.require(request.get("source_root") == pair.get("source_root") and
                       request.get("entrypoint") == pair.get("entrypoint") and
                       request.get("component_wrapper") == pair.get("wrapper") and
                       request.get("library_paths") == pair.get("library_paths") and
                       row.get("component_wrapper_sha256") == pair.get("wrapper_sha256") and
                       row.get("entrypoint_sha256") == pair.get("entrypoint_sha256"),
                       "B6d staged W/S binding differs")
        pair_id = pair["pair_id"]
        if pair_id not in checked_pairs:
            _validate_pair_files(pair)
            checked_pairs.add(pair_id)
    ORIGINAL_VALIDATE_SOURCE_BINDINGS(original_rows, inventory, original_requests)


def install(staging_root: Path, manifest_path: Path, manifest_sha256: str) -> dict[str, Any]:
    runner.checked_sha(manifest_path, manifest_sha256, "B6d unit manifest")
    manifest = json.loads(manifest_path.read_text())
    runner.require(isinstance(manifest, dict), "B6d unit manifest is not an object")
    runner.validate_source_bindings = lambda rows, inventory, requests: (
        validate_staged_source_bindings(rows, inventory, requests,
                                        staging_root, manifest))
    return manifest
