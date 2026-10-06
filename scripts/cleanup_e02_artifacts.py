#!/usr/bin/env python3
"""Finalize the append-only E-02 incremental cleanup record."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import e02_incremental_cleanup as cleanup  # noqa: E402


RUN = ROOT / "runs/e02-production-mains-2026-10-05"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def expected_batches() -> set[str]:
    expected = set()
    for stage in cleanup.STAGES[:2]:
        expected.update(
            f"{stage}/{path.parent.name}" for path in (RUN / stage).glob("*/result.json")
        )
    selection = read(RUN / "preparation-selection.json")
    expected.update(
        f"preparation-measurements/{row['identifier']}" for row in selection["entries"]
    )
    preparation_results = {
        path.parent.name for path in (RUN / "preparation-measurements").glob("*/result.json")
    }
    selected = {row["identifier"] for row in selection["entries"]}
    if preparation_results != selected:
        raise RuntimeError(
            f"preparation denominator incomplete: {len(preparation_results)}/{len(selected)}"
        )
    return expected


def verify_no_residual_artifacts(cleaned: set[str]) -> None:
    residual = []
    for batch in sorted(cleaned):
        stage, identifier = batch.split("/", 1)
        files, diagnostics, _ = cleanup.inventory(RUN / stage / identifier)
        if files or diagnostics:
            residual.append({
                "batch": batch,
                "files": [row["path"] for row in files[:5]],
                "diagnostic_copies": [cleanup.relative(path) for path in diagnostics[:5]],
            })
    if residual:
        raise RuntimeError("completed entries retain cleanup artifacts: " + json.dumps(residual[:3]))


def main() -> None:
    if (RUN / "deleted-artifacts.json").exists():
        raise FileExistsError("final E-02 cleanup record already exists")
    cleanup.run_once()
    expected = expected_batches()
    state = read(cleanup.STATE)
    completed = state["completed_batches"]
    blocked = state.get("blocked_batches", {})
    missing = sorted(expected - set(completed) - set(blocked))
    skipped = {key: row["skipped"] for key, row in completed.items() if row["skipped"]}
    if missing or skipped:
        raise RuntimeError(f"incremental cleanup incomplete: missing={missing[:5]}, skipped={skipped}")
    verify_no_residual_artifacts(expected & set(completed))
    stage_counts = Counter(key.split("/", 1)[0] for key in expected)
    final = {
        "schema_version": 1,
        "task": "E-02",
        "status": "complete",
        "method": "per-entrypoint append-only inventory, hash verification, and immediate deletion after result.json",
        "ledger": {"path": cleanup.relative(cleanup.LEDGER), "sha256": digest(cleanup.LEDGER)},
        "state": {"path": cleanup.relative(cleanup.STATE), "sha256": digest(cleanup.STATE)},
        "completed_batches": len(expected),
        "deleted_batches": len(expected & set(completed)),
        "preserved_unverified_batches": [blocked[key] for key in sorted(expected & set(blocked))],
        "stage_batches": dict(sorted(stage_counts.items())),
        "deleted_files": sum(completed[key]["deleted_files"] for key in expected if key in completed),
        "deleted_bytes": sum(completed[key]["deleted_bytes"] for key in expected if key in completed),
        "skipped": [],
        "preserved": [
            ".circom sources and generated wrapper sources",
            ".sym",
            "JSON including instance-capture.json and instance-args.json",
            "logs",
            "original clones and original node_modules",
            "fixed tool binaries",
        ],
        "zkfuzz_invocations": 0,
    }
    target = RUN / "deleted-artifacts.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(final, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(final))


if __name__ == "__main__":
    main()
