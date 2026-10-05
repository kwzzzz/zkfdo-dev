#!/usr/bin/env python3
"""Manifest and remove only M-01 compiled artifacts and diagnostic-copy .circom files."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/m01-2026-10-03"
RESULTS = ROOT / "docs/m01_discovery_results_2026-10-03.json"
MANIFEST = RUN / "deleted-artifacts.json"
OUTCOME = RUN / "cleanup-result.json"
COMPILED = {".r1cs", ".wasm", ".cpp", ".dat", ".o"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def candidates():
    for directory, subdirectories, files in os.walk(RUN, followlinks=False):
        subdirectories.sort()
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(RUN)
            if "clone" in relative.parts or "node_modules" in relative.parts:
                continue
            compiled = path.suffix in COMPILED
            diagnostic_source = path.suffix == ".circom" and "diagnostic-copy" in relative.parts
            if compiled or diagnostic_source:
                yield path, "compiled_artifact" if compiled else "diagnostic_circom_copy"


def describe(path, kind):
    stat = path.stat()
    row = {"path": str(path.relative_to(ROOT)), "kind": kind, "sha256": digest(path),
           "bytes": stat.st_size, "symlink": path.is_symlink()}
    if path.is_symlink():
        row["link_target"] = os.readlink(path)
    return row


def validate_results():
    document = json.loads(RESULTS.read_text())
    capture = document["instance_capture_completeness"]
    if document["scope"]["entrypoints"] != 125 or len(document["large_entrypoints"]) != 49:
        raise RuntimeError("result document has an incomplete denominator")
    if not capture["captured_values_preserved_in_json"]:
        raise RuntimeError("capture values have not been preserved in JSON")
    raw = list((RUN / "measurements").glob("*/result.json"))
    if len(raw) != 125:
        raise RuntimeError("raw result denominator is incomplete")
    for path in raw:
        result = json.loads(path.read_text())
        capture = result.get("instance_discovery") or {}
        if capture.get("selected") == "compiler" and capture.get("compiler_complete"):
            for key in ("capture_report", "captured_instances", "capture_signals", "capture_constraints",
                        "compiler_root_instance_key"):
                if capture.get(key) is None:
                    raise RuntimeError(f"{path}: missing captured value {key}")
            report = ROOT / capture["capture_report"]["path"]
            if not report.is_file() or digest(report) != capture["capture_report"]["sha256"]:
                raise RuntimeError(f"{path}: capture report is missing or changed")
    return document


def main():
    document = validate_results()
    paths = [(path, kind) for path, kind in candidates()]
    rows = [describe(path, kind) for path, kind in paths]
    manifest = {
        "schema_version": 1, "task": "M-01", "created_at": datetime.now(timezone.utc).isoformat(),
        "selection": {"run_root": str(RUN.relative_to(ROOT)), "compiled_suffixes": sorted(COMPILED),
                      "diagnostic_source": "*.circom below a directory named diagnostic-copy"},
        "preconditions": {"result_entrypoints": document["scope"]["entrypoints"],
                          "large_entrypoints": len(document["large_entrypoints"]),
                          "captured_values_preserved_in_json": True},
        "files": len(rows), "bytes": sum(row["bytes"] for row in rows), "artifacts": rows,
    }
    with MANIFEST.open("x") as handle:
        json.dump(manifest, handle, indent=1)
        handle.write("\n")
    deleted = []
    skipped = []
    run = RUN.resolve()
    for row, (path, kind) in zip(rows, paths):
        if not path.parent.resolve().is_relative_to(run):
            skipped.append({"path": row["path"], "reason": "outside_run"})
            continue
        try:
            current = describe(path, kind)
        except FileNotFoundError:
            skipped.append({"path": row["path"], "reason": "missing_after_manifest"})
            continue
        keys = ("path", "kind", "sha256", "bytes", "symlink", "link_target")
        if any(current.get(key) != row.get(key) for key in keys):
            skipped.append({"path": row["path"], "reason": "changed_after_manifest"})
            continue
        path.unlink()
        deleted.append(row)
    outcome = {
        "schema_version": 1, "task": "M-01", "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest": {"path": str(MANIFEST.relative_to(ROOT)), "sha256": digest(MANIFEST)},
        "deleted_count": len(deleted), "deleted_bytes": sum(row["bytes"] for row in deleted),
        "deleted_by_kind": dict(sorted(__import__("collections").Counter(
            row["kind"] for row in deleted).items())),
        "skipped_count": len(skipped), "skipped": skipped,
        "preserved": ["clone", "node_modules", ".json", ".log", ".sym", "tools/zkfDO"],
    }
    with OUTCOME.open("x") as handle:
        json.dump(outcome, handle, indent=2)
        handle.write("\n")
    print(json.dumps(outcome))


if __name__ == "__main__":
    main()
