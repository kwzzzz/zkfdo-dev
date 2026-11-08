#!/usr/bin/env python3
"""Prepare the fixed 45 Policy B S specs without compiling or fuzzing."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import time

import run_policy_a_engine_v4 as engine
import run_policy_b_order as policy
import s_round4c_prepare_policy_20261027 as evidence

ROOT, OUT = evidence.ROOT, evidence.OUT
BASE = OUT / "prepared-s-v1"
SOURCE = OUT / "s-input-bundle-v2.json"
GIB = 2**30
require, read, save, pin, sha = (evidence.require, evidence.read, evidence.save,
                                evidence.pin, evidence.sha)


def available() -> int:
    info = os.statvfs(ROOT)
    return info.f_bavail * info.f_frsize


def remap(path: str, paths: dict[Path, Path]) -> str:
    source = Path(path)
    for old, new in paths.items():
        if source == old or source.is_relative_to(old):
            return str(new / source.relative_to(old))
    return path


def clone_revision(job: dict) -> tuple[dict[Path, Path], int]:
    spec = read(Path(job["source_spec"]["path"]), job["source_spec"]["sha256"])
    snapshots = spec["source_snapshots"]
    require(len(snapshots) == job["source_snapshot_count"], "snapshot denominator changed")
    mapping = {}
    bytes_total = 0
    for row in snapshots:
        source = Path(row["path"])
        dest = BASE / "snapshots" / job["revision"] / row["id"]
        require(source.is_dir() and source.resolve().is_relative_to(ROOT) and
                not dest.exists(), "invalid source/new snapshot")
        engine.v1.ensure_no_symlinks(source)
        require(engine.v1.tree_sha256(source) == row["tree_sha256"],
                "source snapshot tree SHA changed")
        shutil.copytree(source, dest, symlinks=True)
        require(engine.v1.tree_sha256(dest) == row["tree_sha256"],
                "copied snapshot differs")
        mapping[source] = dest
        bytes_total += sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    return mapping, bytes_total


def prepare_job(job: dict, mapping: dict[Path, Path]) -> dict:
    source = read(Path(job["source_spec"]["path"]), job["source_spec"]["sha256"])
    meta = read(Path(job["order_metadata"]["path"]), job["order_metadata"]["sha256"])
    require(meta["source_spec"] == job["source_spec"], "metadata/source spec differs")
    ordered_ids = [row["target_id"] for row in policy.policy_b_order(meta["targets"])]
    require(len(ordered_ids) == len(source["targets"]) == len(set(ordered_ids)),
            "Policy B target denominator changed")
    spec = copy.deepcopy(source)
    by_id = {target["target_id"]: target for target in spec["targets"]}
    require(set(by_id) == set(ordered_ids), "Policy B target set differs")
    spec["targets"] = [by_id[target_id] for target_id in ordered_ids]
    spec["campaign_id"] += "-round4c-policy-b"
    for rank, target in enumerate(spec["targets"], 1):
        target["rank"] = rank
        target["source_snapshot_path"] = remap(target["source_snapshot_path"], mapping)
        require(Path(target["source_snapshot_path"]).is_relative_to(BASE / "snapshots"),
                "target still points to an old snapshot")
    for row in spec["source_snapshots"]:
        row["path"] = remap(row["path"], mapping)
        require(Path(row["path"]).is_relative_to(BASE / "snapshots"),
                "spec still points to an old snapshot")
    for row in spec["external_include_files"]:
        row["path"] = remap(row["path"], mapping)
    plan_pin = next(p for p in spec["pinned_files"] if p["label"] == "plan")
    source_plan = read(Path(plan_pin["path"]), plan_pin["sha256"])
    plan = copy.deepcopy(source_plan)
    plan_by_id = {target["target_id"]: target for target in plan["targets"]}
    require(set(plan_by_id) == set(ordered_ids), "pinned plan target set changed")
    plan["targets"] = [plan_by_id[target_id] for target_id in ordered_ids]
    for rank, row in enumerate(plan["targets"], 1):
        row["rank"] = rank
        for fingerprint in row["snapshot_fingerprints"]:
            fingerprint["path"] = remap(fingerprint["path"], mapping)
    folder = BASE / "jobs" / f"{job['revision']}-seed-{job['seed']}"
    plan_path = folder / "ordered-plan.json"
    plan["plan_path"] = str(plan_path)
    new_plan = save(plan_path, plan)
    plan_pin.update(new_plan)
    spec_path = folder / "spec.json"
    new_spec = save(spec_path, spec)
    # Exact v4 validation, including the plan's fingerprint against the copied
    # snapshot, is read-only and has no compiler/fuzzer invocation.
    engine.validate_spec_v4(spec)
    roots = {row["id"]: Path(row["path"]) for row in spec["source_snapshots"]}
    verification = engine.verify_plan_v4(spec, roots)
    require(verification["status"] == "verified" and
            verification["target_count"] == len(spec["targets"]),
            "v4 plan validation failed")
    return {**job, "prepared_spec": new_spec, "prepared_plan": new_plan,
            "status": "prepared and v4 plan verified", "plan_validation": verification}


def main() -> None:
    require(not BASE.exists(), "prepared-s-v1 already exists; never overwrite")
    require(available() >= 30 * GIB, "30 GiB free required before snapshot preparation")
    start = time.monotonic()
    before = available()
    bundle = read(SOURCE)
    require(bundle["metadata_ready"] is True and len(bundle["jobs"]) == 45,
            "fixed metadata bundle incomplete")
    mapping_by_revision = {}
    copied_bytes = 0
    jobs = []
    for job in bundle["jobs"]:
        revision = job["revision"]
        if revision not in mapping_by_revision:
            mapping_by_revision[revision], size = clone_revision(job)
            copied_bytes += size
        jobs.append(prepare_job(job, mapping_by_revision[revision]))
        require(available() >= 20 * GIB, "internal free space fell below 20 GiB")
    result = {**bundle, "schema": "s-round4c-S-input-bundle-v3",
              "source_bundle": pin(SOURCE), "jobs": jobs, "ready_for_execution": True,
              "source_snapshots_copied": sum(len(paths) for paths in mapping_by_revision.values()),
              "copied_file_bytes": copied_bytes,
              "preparation_elapsed_seconds": time.monotonic() - start,
              "internal_free_before_bytes": before, "internal_free_after_bytes": available()}
    receipt = save(OUT / "s-input-bundle-v3.json", result)
    print(json.dumps({"bundle": receipt, "jobs": len(jobs),
                      "copied_source_bytes": copied_bytes,
                      "elapsed_seconds": result["preparation_elapsed_seconds"]}))


if __name__ == "__main__":
    main()
