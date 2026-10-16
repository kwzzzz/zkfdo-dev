#!/usr/bin/env python3
"""Create one immutable J request per inventoried A candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
J_ROOT = ROOT / "runs/n6-j1-2026-10-09.noindex"
ENGINE = ROOT / "runs/l07-2026-10-05/tools/zkfDO"
CIRCOM = Path("/Users/miiz/.cargo/bin/circom")
ENGINE_SHA = "e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed"
CIRCOM_SHA = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"


class RequestError(RuntimeError):
    """A fixed input or request path is inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RequestError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), f"expected object: {path}")
    return data


def checked_file(path: Path, sha: str) -> Path:
    require(path.is_file(), f"missing file: {path}")
    require(sha256_file(path) == sha, f"SHA-256 mismatch: {path}")
    return path.resolve()


def spec_for(row: dict[str, Any], method: str, root: Path,
             cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    stem = "whole" if method == "W" else "split"
    name, sha = row[f"{stem}_spec"], row[f"{stem}_spec_sha256"]
    if name not in cache:
        cache[name] = read_json(checked_file(root / name, sha))
    require(sha256_file(root / name) == sha, f"spec changed: {name}")
    return cache[name]


def target_path(spec: dict[str, Any], target_index: int, target_id: str) -> tuple[Path, dict[str, Any]]:
    targets = spec["targets"]
    require(0 <= target_index < len(targets), "target index outside spec")
    target = targets[target_index]
    require(target["target_id"] == target_id, f"target id changed: {target_id}")
    snapshots = {s["id"]: s for s in spec["source_snapshots"]}
    snapshot_root = Path(snapshots[target["source_snapshot_id"]]["path"])
    path = checked_file(snapshot_root / target["entrypoint_relative"],
                        target["entrypoint_sha256"])
    return path, target


def library_paths(target: dict[str, Any], snapshot_root: Path) -> list[str]:
    """Keep the target preflight -l order, resolving its workspace to that target's snapshot."""
    command = target["preflight_compile_command"]
    values: list[str] = []
    for i, token in enumerate(command):
        if token == "-l":
            require(i + 1 < len(command), "dangling -l")
            raw = command[i + 1].replace("{workspace}", str(snapshot_root))
            path = Path(raw).resolve()
            require(path.is_dir(), f"missing library path: {path}")
            values.append(str(path))
    require(bool(values), "preflight library paths missing")
    return values


def base_for(revision: str, base_index: dict[str, Any], output_root: Path) -> tuple[Path, str | None]:
    revisions = base_index["revisions"]
    require(revision in revisions, f"revision absent from base index: {revision}")
    row = revisions[revision]
    if row["status"] == "passed":
        base = Path(row["base_input_path"]).resolve()
        checked_file(base, row["base_input_sha256"])
        return base, None
    require(row["status"] == "base_input_unavailable",
            f"unexpected base status: {revision}: {row['status']}")
    return output_root / "unavailable-base-input" / f"{revision}.json", "base_input_unavailable"


def build(root: Path, inventory_path: Path, base_index_path: Path,
          request_root: Path, index_path: Path) -> tuple[dict[str, Any], list[tuple[Path, dict[str, Any]]]]:
    inventory = read_json(inventory_path)
    require(inventory.get("status") == "verified" and inventory.get("candidate_count") == 2926,
            "candidate inventory not verified at expected count")
    require(inventory.get("counts") == {"main": {"W": 2276, "S": 581},
                                        "mem20": {"W": 0, "S": 69}},
            "candidate inventory count mismatch")
    base_index = read_json(base_index_path)
    require(len(base_index.get("revisions", {})) == 27, "base index revision count mismatch")
    checked_file(ENGINE, ENGINE_SHA)
    checked_file(CIRCOM, CIRCOM_SHA)
    require(not index_path.exists() and not request_root.exists(), "refuse to overwrite J requests")
    spec_cache: dict[str, dict[str, Any]] = {}
    queue = read_json(root / "runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json")
    main_units = queue["units"]
    mem_queue = read_json(root / "runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json")
    mem_units = mem_queue["units"]
    revision_order: dict[tuple[str, str], int] = {}
    revision_counts = {"main": 0, "mem20": 0}
    for lane, units in (("main", main_units), ("mem20", mem_units)):
        for unit in units:
            key = (lane, unit["identifier"])
            if key not in revision_order:
                revision_order[key] = revision_counts[lane]
                revision_counts[lane] += 1
    known_units = {(lane, unit["unit_id"]): unit["identifier"]
                   for lane, units in (("main", main_units), ("mem20", mem_units))
                   for unit in units}
    rows = sorted(inventory["rows"], key=lambda r: (
        0 if r["lane"] == "main" else 1,
        revision_order[(r["lane"], r["identifier"])], r["seed"],
        0 if r["method"] == "W" else 1,
        r["attempt_index"], r["candidate_index"]))
    require(all(known_units.get((r["lane"], r["unit_id"])) == r["identifier"] for r in rows),
            "candidate unit differs from A queue")
    require(len(rows) == 2926 and len({r["candidate_sha256"] for r in rows}) == len(rows),
            "candidate inventory rows incomplete or repeated")
    index_rows: list[dict[str, Any]] = []
    files: list[tuple[Path, dict[str, Any]]] = []
    failures = Counter()
    for sequence, row in enumerate(rows):
        method = row["method"]
        lane = row["lane"]
        revision = row["identifier"]
        w_spec = spec_for(row, "W", root, spec_cache)
        w_target = w_spec["targets"][0]
        entrypoint, entrypoint_target = target_path(w_spec, 0, w_target["target_id"])
        method_spec = spec_for(row, method, root, spec_cache)
        wrapper, target = target_path(method_spec, row["target_index"], row["target_id"])
        snapshots = {s["id"]: s for s in method_spec["source_snapshots"]}
        snapshot_root = Path(snapshots[target["source_snapshot_id"]]["path"])
        libraries = library_paths(target, snapshot_root)
        source_root = Path(os.path.commonpath((entrypoint.parent, wrapper.parent))).resolve()
        require(entrypoint.is_relative_to(source_root) and wrapper.is_relative_to(source_root),
                "wrapper or entrypoint outside source_root")
        candidate = checked_file(Path(row["candidate_path"]), row["candidate_sha256"])
        base, failure = base_for(revision, base_index, request_root)
        failures[failure or "ready"] += 1
        request_id = (f"j1-{lane}-{row['unit_id']}-{method}"
                      f"-a{row['attempt_index'] + 1:04d}-c{row['candidate_index'] + 1:03d}")
        request_path = request_root / lane / revision / f"{request_id}.json"
        request = {
            "schema": "zkfdo-lifting-request-v1",
            "id": request_id,
            "source_root": str(source_root),
            "library_paths": libraries,
            "component_wrapper": str(wrapper),
            "entrypoint": str(entrypoint),
            "base_input": str(base),
            "candidate": {"format": "zkfuzz", "path": str(candidate)},
        }
        encoded = (json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        request_sha = hashlib.sha256(encoded).hexdigest()
        index_rows.append({
            "scope": lane,
            "revision_id": revision,
            "unit_id": row["unit_id"],
            "queue_order": sequence,
            "seed": row["seed"],
            "method": method,
            "attempt_number": row["attempt_index"] + 1,
            "candidate_index": row["candidate_index"],
            "completion_offset_seconds": row["completion_offset_seconds"],
            "target_id": row["target_id"],
            "original_target_id": row.get("original_target_id"),
            "request": str(request_path),
            "request_sha256": request_sha,
            "component_wrapper_sha256": target["entrypoint_sha256"],
            "entrypoint_sha256": entrypoint_target["entrypoint_sha256"],
            "candidate_path": str(candidate),
            "candidate_sha256": row["candidate_sha256"],
            "preparation_failure": failure,
        })
        files.append((request_path, request))
    index = {
        "schema_version": 1,
        "status": "verified",
        "inventory": str(inventory_path),
        "inventory_sha256": sha256_file(inventory_path),
        "base_index": str(base_index_path),
        "base_index_sha256": sha256_file(base_index_path),
        "engine": str(ENGINE),
        "engine_sha256": ENGINE_SHA,
        "circom": str(CIRCOM),
        "circom_sha256": CIRCOM_SHA,
        "request_count": len(index_rows),
        "preparation_counts": dict(failures),
        "requests": index_rows,
    }
    return index, files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--inventory", type=Path, default=J_ROOT / "candidate-inventory.json")
    parser.add_argument("--base-index", type=Path, default=J_ROOT / "base-inputs/index.json")
    parser.add_argument("--request-root", type=Path, default=J_ROOT / "requests")
    parser.add_argument("--index", type=Path, default=J_ROOT / "request-index.json")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    index, files = build(root, args.inventory.resolve(), args.base_index.resolve(),
                         args.request_root.resolve(), args.index.resolve())
    for len_written, (path, value) in enumerate(files):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        require(sha256_file(path) == index["requests"][len_written]["request_sha256"],
                f"written request hash mismatch: {path}")
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("x", encoding="utf-8") as stream:
        json.dump(index, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"index": str(args.index), "count": index["request_count"],
                      "preparation_counts": index["preparation_counts"]}, sort_keys=True))


if __name__ == "__main__":
    main()
