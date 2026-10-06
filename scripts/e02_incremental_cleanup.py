#!/usr/bin/env python3
"""Incrementally record and remove artifacts from completed E-02 entries."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/e02-production-mains-2026-10-05"
LEDGER = RUN / "incremental-cleanup-ledger.jsonl"
STATE = RUN / "incremental-cleanup-state.json"
SUFFIXES = {".r1cs", ".wasm", ".cpp", ".dat", ".o"}
STAGES = ("compile-measurements", "compile-600-sensitivity", "preparation-measurements")
PROTECTED_DIRECTORIES = {"clone", "node_modules", "tools", ".git"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def file_record(path: Path) -> dict:
    stat = path.lstat()
    if path.is_symlink():
        target = os.readlink(path)
        return {
            "path": relative(path),
            "bytes": stat.st_size,
            "sha256": hashlib.sha256(target.encode()).hexdigest(),
            "sha256_kind": "symlink_target_text",
            "link_target": target,
        }
    return {
        "path": relative(path),
        "bytes": stat.st_size,
        "sha256": digest_file(path),
        "sha256_kind": "file_content",
    }


def append_ledger(record: dict) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_state() -> dict:
    if not STATE.exists():
        return {"schema_version": 1, "task": "E-02", "completed_batches": {}, "blocked_batches": {}}
    state = json.loads(STATE.read_text())
    state.setdefault("completed_batches", {})
    state.setdefault("blocked_batches", {})
    return state


def write_state(state: dict) -> None:
    state["updated_at"] = now()
    temporary = STATE.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, STATE)


def walk_tree(root: Path):
    """Walk without following links and without descending into diagnostic copies."""
    for directory, names, files in os.walk(root, followlinks=False):
        current = Path(directory)
        links = [name for name in names if (current / name).is_symlink()]
        diagnostics = [name for name in names if name == "diagnostic-copy" and name not in links]
        names[:] = [name for name in names if name not in diagnostics
                    and name not in links and name not in PROTECTED_DIRECTORIES]
        yield current, diagnostics, links, files


def find_diagnostics(root: Path) -> list[Path]:
    found = []
    for current, diagnostics, _, _ in walk_tree(root):
        found.extend(current / name for name in diagnostics)
    return sorted(found)


def valid_json(path: Path) -> bool:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(value, (dict, list)) and bool(value)


def capture_verification(entry: Path, diagnostics: list[Path]) -> dict:
    rows = []
    for diagnostic in diagnostics:
        related_captures = []
        related_arguments = []
        # The capture tool writes both persisted value files beside the
        # instance-capture directory. Walk only this diagnostic copy's direct
        # ancestor chain and accept the closest pair, never a sibling callsite.
        for ancestor in (diagnostic.parent, *diagnostic.parents):
            if ancestor == entry.parent or not ancestor.is_relative_to(entry):
                break
            capture = ancestor / "instance-capture.json"
            arguments = ancestor / "instance-args.json"
            if valid_json(capture) and valid_json(arguments):
                related_captures = [capture]
                related_arguments = [arguments]
                break
        rows.append({
            "diagnostic_copy": relative(diagnostic),
            "instance_capture": [file_record(path) for path in sorted(set(related_captures))],
            "instance_args": [file_record(path) for path in sorted(set(related_arguments))],
            "verified": bool(related_captures and related_arguments),
        })
    return {"entries": rows, "verified": all(row["verified"] for row in rows)}


def diagnostic_members(root: Path) -> list[Path]:
    members = []
    for directory, names, files in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in names:
            path = current / name
            if path.is_symlink():
                members.append(path)
        for name in files:
            members.append(current / name)
    return sorted(set(members))


def inventory(entry: Path) -> tuple[list[dict], list[Path], dict]:
    diagnostics = find_diagnostics(entry)
    verification = capture_verification(entry, diagnostics)
    if not verification["verified"]:
        missing = [row["diagnostic_copy"] for row in verification["entries"] if not row["verified"]]
        raise RuntimeError("capture values not persisted before diagnostic cleanup: " + ", ".join(missing))
    diagnostic_paths = {path for root in diagnostics for path in diagnostic_members(root)}
    compiled = set()
    for current, _, links, files in walk_tree(entry):
        for name in [*links, *files]:
            path = current / name
            if path.suffix not in SUFFIXES:
                continue
            if PROTECTED_DIRECTORIES.intersection(path.relative_to(entry).parts):
                continue
            compiled.add(path)
    paths = sorted(compiled | diagnostic_paths)
    return [file_record(path) for path in paths], diagnostics, verification


def verify(row: dict) -> bool:
    path = ROOT / row["path"]
    if not path.exists() and not path.is_symlink():
        return False
    if path.lstat().st_size != row["bytes"]:
        return False
    if row["sha256_kind"] == "symlink_target_text":
        return path.is_symlink() and hashlib.sha256(os.readlink(path).encode()).hexdigest() == row["sha256"]
    return path.is_file() and not path.is_symlink() and digest_file(path) == row["sha256"]


def completed_entries():
    for stage in STAGES:
        directory = RUN / stage
        if not directory.exists():
            continue
        for result in sorted(directory.glob("*/result.json")):
            if result.is_symlink() or result.parent.is_symlink() or directory.is_symlink():
                continue
            # Publication is not atomic in the existing measurement writer.
            # A partially written JSON must never trigger cleanup.
            try:
                if not isinstance(json.loads(result.read_text()), dict):
                    continue
            except (OSError, json.JSONDecodeError):
                continue
            yield stage, result.parent, result


def clean_entry(stage: str, entry: Path, result: Path, state: dict) -> dict | None:
    if stage not in STAGES or entry.parent != RUN / stage or result != entry / "result.json":
        raise ValueError("cleanup entry is outside the permitted measurement stage")
    if entry.is_symlink() or result.is_symlink():
        raise ValueError("linked measurement entry must be preserved")
    if not isinstance(json.loads(result.read_text()), dict):
        raise ValueError("completed result must be a JSON object")
    key = f"{stage}/{entry.name}"
    if key in state["completed_batches"]:
        return None
    result_record = file_record(result)
    files, diagnostics, verification = inventory(entry)
    batch = {
        "schema_version": 1,
        "event": "recorded_before_deletion",
        "recorded_at": now(),
        "batch": key,
        "completed_result": result_record,
        "capture_verification": verification,
        "diagnostic_copies": [relative(path) for path in diagnostics],
        "files": files,
        "file_count": len(files),
        "bytes": sum(row["bytes"] for row in files),
        "zkfuzz_invocations": 0,
    }
    append_ledger(batch)
    if not verify(result_record):
        raise RuntimeError("result changed during inventory; all artifacts preserved")
    by_path = {ROOT / row["path"]: row for row in files}
    diagnostic_members_set = {path for root in diagnostics for path in diagnostic_members(root)}
    skipped = []
    deleted = []
    for path, row in by_path.items():
        if path in diagnostic_members_set:
            continue
        if not verify(row):
            skipped.append({"path": row["path"], "reason": "size_or_hash_changed_after_record"})
            continue
        path.unlink()
        deleted.append(row)
    for diagnostic in diagnostics:
        members = diagnostic_members(diagnostic)
        if all(path in by_path and verify(by_path[path]) for path in members):
            deleted.extend(by_path[path] for path in members)
            shutil.rmtree(diagnostic)
        else:
            skipped.append({"path": relative(diagnostic), "reason": "diagnostic_member_changed_after_record"})
    completion = {
        "schema_version": 1,
        "event": "deletion_completed",
        "recorded_at": now(),
        "batch": key,
        "deleted_files": len(deleted),
        "deleted_bytes": sum(row["bytes"] for row in deleted),
        "skipped": skipped,
        "preserved": [".sym", "JSON", "logs", "original clones", "original node_modules", "fixed binaries"],
        "zkfuzz_invocations": 0,
    }
    append_ledger(completion)
    state["completed_batches"][key] = completion
    write_state(state)
    print(json.dumps(completion), flush=True)
    return completion


def run_once() -> dict:
    state = load_state()
    cleaned = 0
    deleted_bytes = 0
    errors = []
    for stage, entry, result in completed_entries():
        key = f"{stage}/{entry.name}"
        result_sha256 = digest_file(result)
        blocked = state["blocked_batches"].get(key)
        if blocked and blocked.get("result_sha256") == result_sha256:
            continue
        try:
            completion = clean_entry(stage, entry, result, state)
            if completion:
                cleaned += 1
                deleted_bytes += completion["deleted_bytes"]
        except Exception as error:  # preserve the entry and keep cleaning independent completed entries
            errors.append({"batch": key, "error": f"{type(error).__name__}: {error}"})
            preservation = {
                "schema_version": 1,
                "event": "deletion_blocked_and_artifacts_preserved",
                "recorded_at": now(),
                "batch": key,
                "result_sha256": result_sha256,
                "reason": errors[-1]["error"],
                "zkfuzz_invocations": 0,
            }
            append_ledger(preservation)
            state["blocked_batches"][key] = preservation
            write_state(state)
            print(json.dumps(errors[-1]), flush=True)
    return {"cleaned_batches": cleaned, "deleted_bytes": deleted_bytes, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=10)
    parser.add_argument("--expected-preparation-results", type=int, default=101)
    args = parser.parse_args()
    while True:
        run_once()
        completed = len(list((RUN / "preparation-measurements").glob("*/result.json")))
        if not args.watch or completed >= args.expected_preparation_results:
            break
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
