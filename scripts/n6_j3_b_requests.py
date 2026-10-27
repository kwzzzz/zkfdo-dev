#!/usr/bin/env python3
"""Plan B J requests now; materialize them only after base-input selection.

The plan is metadata only and cannot be passed to run_n6_j1.py. No candidate
JSON is parsed here. Final request files are generated from the unchanged plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path

from n6_j1_requests import (CIRCOM, CIRCOM_SHA, ENGINE, ENGINE_SHA,
                            base_for, checked_file, read_json,
                            require, sha256_file, spec_for, target_path)


ROOT = Path(__file__).resolve().parents[1]
J_ROOT = ROOT / "runs/n6-j3-2026-10-14.noindex"
QUEUE = ROOT / "runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json"
MEM20_QUEUE = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-prep/queue-b-mem20.json"
MEM20_STATE = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json"


def circom_files(source: Path) -> list[Path]:
    """List regular .circom sources below one pinned snapshot, without following links."""
    files = []
    for directory, names, filenames in os.walk(source, followlinks=False):
        names[:] = sorted(name for name in names
                          if not (Path(directory) / name).is_symlink())
        for name in sorted(filenames):
            path = Path(directory) / name
            if path.suffix == ".circom":
                require(path.is_file(), f"unreadable Circom source: {path}")
                files.append(path)
    return files


def staged_source_pair(revision: str, project_root: Path, wrapper_root: Path,
                       entrypoint: Path, wrapper: Path, staging_root: Path,
                       request_root: Path, verified: set[Path]) -> tuple[Path, Path, Path]:
    """Copy one W/S snapshot pair into a bounded, immutable B-only source tree.

    The lifting engine requires both request sources inside source_root. Its
    library_paths may remain outside that root, so their original order and
    paths are retained. Each pair has its own root to avoid copying unrelated
    S wrappers when the engine writes a hint workspace.
    """
    project_root = project_root.resolve()
    wrapper_root = wrapper_root.resolve()
    staging_root = staging_root.resolve()
    cache_volume = Path("/Volumes/zkfdo-jcache")
    if staging_root.is_relative_to(cache_volume):
        require(os.path.ismount(cache_volume), "B source staging volume is not mounted")
    require(entrypoint.is_relative_to(project_root) and
            wrapper.is_relative_to(wrapper_root), "source outside pinned snapshot")
    key = hashlib.sha256((str(project_root) + "\0" + str(wrapper_root))
                         .encode("utf-8")).hexdigest()[:16]
    source_root = staging_root / revision / key
    require(not source_root.is_relative_to(project_root) and
            not source_root.is_relative_to(wrapper_root) and
            not source_root.is_relative_to(request_root.resolve()) and
            not request_root.is_relative_to(source_root),
            "source staging overlaps a source snapshot or request output")
    staged_entrypoint = source_root / "project" / entrypoint.relative_to(project_root)
    staged_wrapper = source_root / "wrapper" / wrapper.relative_to(wrapper_root)
    if source_root in verified:
        return source_root, staged_entrypoint, staged_wrapper

    copies = []
    for label, original in (("project", project_root), ("wrapper", wrapper_root)):
        require(original.is_dir(), f"source snapshot missing: {original}")
        for source in circom_files(original):
            relative = Path(label) / source.relative_to(original)
            copies.append({"path": str(relative), "source": str(source),
                           "sha256": sha256_file(source)})
    manifest = {"schema_version": 1, "revision_id": revision,
                "project_root": str(project_root), "wrapper_root": str(wrapper_root),
                "files": copies}
    require(any(item["path"] == str(staged_entrypoint.relative_to(source_root))
                for item in copies) and
            any(item["path"] == str(staged_wrapper.relative_to(source_root))
                for item in copies), "entrypoint or wrapper absent from staged sources")
    manifest_path = source_root / "source-staging.json"
    if source_root.exists():
        require(manifest_path.is_file() and read_json(manifest_path) == manifest,
                f"source staging differs or is incomplete: {source_root}")
        actual = {str(path.relative_to(source_root)) for path in circom_files(source_root)}
        require(actual == {item["path"] for item in copies},
                f"source staging has extra or missing Circom files: {source_root}")
        for item in copies:
            staged = source_root / item["path"]
            require(staged.is_file() and sha256_file(staged) == item["sha256"],
                    f"staged source SHA-256 differs: {staged}")
    else:
        source_root.mkdir(parents=True, exist_ok=False)
        for item in copies:
            staged = source_root / item["path"]
            staged.parent.mkdir(parents=True, exist_ok=True)
            with Path(item["source"]).open("rb") as original, staged.open("xb") as target:
                shutil.copyfileobj(original, target)
            require(sha256_file(staged) == item["sha256"],
                    f"staged source SHA-256 differs: {staged}")
        with manifest_path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
    verified.add(source_root)
    return source_root, staged_entrypoint, staged_wrapper


def available_libraries(target: dict, snapshot_root: Path) -> tuple[list[str], list[str]]:
    """Omit only absent workspace paths; preserve existing -l order.

    B split snapshots carry some -l paths below their copied workspace that
    are absent in the pinned tree. The corresponding original absolute paths
    are present. Missing paths cannot resolve imports and are recorded in the
    plan; no source snapshot or frozen spec is changed.
    """
    command = target["preflight_compile_command"]
    available, missing = [], []
    for position, token in enumerate(command):
        if token != "-l":
            continue
        require(position + 1 < len(command), "dangling -l")
        raw = command[position + 1]
        path = Path(raw.replace("{workspace}", str(snapshot_root))).resolve()
        if path.is_dir():
            available.append(str(path))
        else:
            require("{workspace}" in raw,
                    f"recorded absolute library path missing: {path}")
            missing.append(str(path))
    require(bool(available), "no available B library path")
    return available, missing


def planned_rows(root: Path, inventory: dict, queue: dict,
                 request_root: Path, scope: str,
                 source_staging_root: Path | None = None) -> list[dict]:
    count = inventory.get("candidate_count")
    require(inventory.get("status") == "verified" and
            isinstance(count, int) and count >= 0,
            f"B {scope} inventory incomplete")
    require(set(inventory.get("counts", {})) == {scope} and
            sum(inventory["counts"][scope].values()) == count,
            f"B {scope} inventory count mismatch")
    if scope == "main":
        require(inventory["counts"] == {"main": {"W": 0, "S": 107}},
                "B main inventory count mismatch")
    order = {}
    for unit in queue["units"]:
        order.setdefault(unit["identifier"], len(order))
    rows = sorted(inventory["rows"], key=lambda row: (
        order[row["identifier"]], row["seed"], 0 if row["method"] == "W" else 1,
        row["attempt_index"], row["candidate_index"]))
    require(len(rows) == count and len({row["candidate_sha256"] for row in rows}) == count,
            "candidate inventory rows incomplete or repeated")
    known_units = {unit["unit_id"]: unit["identifier"] for unit in queue["units"]}
    require(all(known_units.get(row["unit_id"]) == row["identifier"] for row in rows),
            "candidate unit differs from B queue")
    spec_cache = {}
    verified_staging: set[Path] = set()
    result = []
    for sequence, row in enumerate(rows):
        revision = row["identifier"]
        w_spec = spec_for(row, "W", root, spec_cache)
        require(len(w_spec["targets"]) == 1, f"W target count differs: {revision}")
        entrypoint, entrypoint_target = target_path(
            w_spec, 0, w_spec["targets"][0]["target_id"])
        method_spec = spec_for(row, row["method"], root, spec_cache)
        wrapper, target = target_path(method_spec, row["target_index"], row["target_id"])
        snapshots = {snapshot["id"]: snapshot for snapshot in method_spec["source_snapshots"]}
        snapshot_root = Path(snapshots[target["source_snapshot_id"]]["path"])
        libraries, missing_libraries = available_libraries(target, snapshot_root)
        candidate = checked_file(Path(row["candidate_path"]), row["candidate_sha256"])
        original_entrypoint, original_wrapper = entrypoint, wrapper
        if source_staging_root is None:
            source_root = Path(os.path.commonpath((entrypoint.parent, wrapper.parent))).resolve()
        else:
            w_snapshots = {snapshot["id"]: snapshot
                           for snapshot in w_spec["source_snapshots"]}
            project_root = Path(w_snapshots[entrypoint_target["source_snapshot_id"]]["path"])
            source_root, entrypoint, wrapper = staged_source_pair(
                revision, project_root, snapshot_root, entrypoint, wrapper,
                source_staging_root, request_root, verified_staging)
        require(entrypoint.is_relative_to(source_root) and wrapper.is_relative_to(source_root),
                "wrapper or entrypoint outside source root")
        request_id = (f"j3-{scope}-{row['unit_id']}-{row['method']}"
                      f"-a{row['attempt_index'] + 1:04d}-c{row['candidate_index'] + 1:03d}")
        request_path = request_root / scope / revision / f"{request_id}.json"
        planned = {
            "scope": scope, "revision_id": revision, "unit_id": row["unit_id"],
            "queue_order": sequence, "seed": row["seed"], "method": row["method"],
            "attempt_number": row["attempt_index"] + 1,
            "candidate_index": row["candidate_index"],
            "completion_offset_seconds": row["completion_offset_seconds"],
            "target_id": row["target_id"],
            "original_target_id": row.get("original_target_id"),
            "request": str(request_path),
            "source_root": str(source_root),
            "library_paths": libraries,
            "unavailable_preflight_library_paths": missing_libraries,
            "component_wrapper": str(wrapper),
            "component_wrapper_sha256": target["entrypoint_sha256"],
            "entrypoint": str(entrypoint),
            "entrypoint_sha256": entrypoint_target["entrypoint_sha256"],
            "candidate_path": str(candidate), "candidate_sha256": row["candidate_sha256"],
        }
        if source_staging_root is not None:
            planned["original_entrypoint"] = str(original_entrypoint)
            planned["original_component_wrapper"] = str(original_wrapper)
        result.append(planned)
    return result


def write_json_new(path: Path, value: dict) -> None:
    require(not path.exists(), f"refuse to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--scope", choices=("main", "mem20"), default="main")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--request-root", type=Path)
    parser.add_argument("--plan-index", type=Path)
    parser.add_argument("--base-index", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--staging-root", "--source-staging-root",
                        dest="source_staging_root", type=Path,
                        help="B6b only: copy pinned W/S Circom sources into this new root")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    inventory_path = (args.inventory or J_ROOT /
                      ("candidate-inventory.json" if args.scope == "main" else
                       "mem20-candidate-inventory.json")).resolve()
    queue_path = (args.queue or (QUEUE if args.scope == "main" else MEM20_QUEUE)).resolve()
    request_root = (args.request_root or J_ROOT /
                    ("requests" if args.scope == "main" else "requests-mem20")).resolve()
    plan_path = (args.plan_index or J_ROOT /
                 ("request-index-pending.json" if args.scope == "main" else
                  "request-index-mem20-pending.json")).resolve()
    index_path = (args.index or J_ROOT /
                  ("request-index.json" if args.scope == "main" else
                   "request-index-mem20.json")).resolve()
    inventory = read_json(inventory_path)
    queue = read_json(queue_path)
    require(inventory.get("source_queue_sha256") == sha256_file(queue_path),
            "inventory B queue hash mismatch")
    checked_file(ENGINE, ENGINE_SHA)
    checked_file(CIRCOM, CIRCOM_SHA)
    if args.source_staging_root is not None:
        if args.base_index is None:
            require(not plan_path.exists(), "refuse to overwrite B request plan")
        else:
            require(not index_path.exists() and not request_root.exists(),
                    "refuse to overwrite B request output")
    rows = planned_rows(root, inventory, queue, request_root, args.scope,
                        args.source_staging_root)
    if args.base_index is None:
        plan = {"schema_version": 1, "status": "awaiting_base_input",
                "scope": args.scope, "request_count": len(rows),
                "inventory": str(inventory_path),
                "inventory_sha256": sha256_file(inventory_path),
                "queue": str(queue_path), "queue_sha256": sha256_file(queue_path),
                "engine": str(ENGINE), "engine_sha256": ENGINE_SHA,
                "circom": str(CIRCOM), "circom_sha256": CIRCOM_SHA,
                "requests": rows}
        write_json_new(plan_path, plan)
        print(json.dumps({"plan_index": str(plan_path), "request_count": len(rows),
                          "by_revision": dict(Counter(row["revision_id"] for row in rows))},
                         sort_keys=True))
        return
    require(MEM20_STATE.is_file() and
            read_json(MEM20_STATE).get("status") == "completed",
            "B mem20 state is not completed; final request index refused")
    plan = read_json(plan_path)
    require(plan.get("status") == "awaiting_base_input" and plan.get("requests") == rows,
            "planned B request bindings changed")
    require(plan.get("inventory_sha256") == sha256_file(inventory_path) and
            plan.get("queue_sha256") == sha256_file(queue_path), "planned input hashes changed")
    base_path = args.base_index.resolve()
    base = read_json(base_path)
    required_revisions = {row["revision_id"] for row in rows}
    require(base.get("schema") == "n6-j1-base-inputs-v1" and
            required_revisions <= set(base.get("revisions", {})),
            "B base-input index incomplete")
    require(not index_path.exists() and not request_root.exists(),
            "refuse to overwrite B request output")
    result_rows = []
    failures = Counter()
    for row in rows:
        revision = row["revision_id"]
        base_input, failure = base_for(revision, base, request_root)
        request = {
            "schema": "zkfdo-lifting-request-v1",
            "id": Path(row["request"]).stem,
            "source_root": row["source_root"],
            "library_paths": row["library_paths"],
            "component_wrapper": row["component_wrapper"],
            "entrypoint": row["entrypoint"],
            "base_input": str(base_input),
            "candidate": {"format": "zkfuzz", "path": row["candidate_path"]},
        }
        encoded = (json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        request_path = Path(row["request"])
        request_path.parent.mkdir(parents=True, exist_ok=True)
        with request_path.open("xb") as stream:
            stream.write(encoded)
        request_row = {key: value for key, value in row.items()
                       if key not in {"source_root", "library_paths", "component_wrapper", "entrypoint"}}
        request_row["request_sha256"] = hashlib.sha256(encoded).hexdigest()
        request_row["preparation_failure"] = failure
        failures[failure or "ready"] += 1
        result_rows.append(request_row)
    index = {"schema_version": 1, "status": "verified",
             "inventory": str(inventory_path), "inventory_sha256": sha256_file(inventory_path),
             "base_index": str(base_path), "base_index_sha256": sha256_file(base_path),
             "plan_index": str(plan_path), "plan_index_sha256": sha256_file(plan_path),
             "engine": str(ENGINE), "engine_sha256": ENGINE_SHA,
             "circom": str(CIRCOM), "circom_sha256": CIRCOM_SHA,
             "request_count": len(result_rows), "preparation_counts": dict(failures),
             "requests": result_rows}
    write_json_new(index_path, index)
    print(json.dumps({"index": str(index_path), "request_count": len(result_rows),
                      "preparation_counts": dict(failures)}, sort_keys=True))


if __name__ == "__main__":
    main()
