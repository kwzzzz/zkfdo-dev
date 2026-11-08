#!/usr/bin/env python3
"""Rebuild 45 Policy B S plans from round-2 inspection plus all existing compiles.

This combines every recorded compiler success, irrespective of why it was
compiled. Unmeasured or inspection-incomplete targets remain explicitly pending.
No compiler, judge or fuzzer is invoked here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_policy_a_engine_v4 as engine
import run_policy_b_order as policy

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "runs/s-round4-2026-10-27"
BASE = ROUND / "round4d/prepared-s-v3"
OLD = ROUND / "round4c-main/s-input-bundle-v4.json"
ROUND2 = ROOT / "runs/s-inspection-improve-2026-10-27"
TAG = ROOT / "runs/s-tag-wrapper-2026-10-27"
POLICY_SHA = "edfc21d7c82353ce01a0b1a83958a7f885cd55ec4e5cb83815cc45f138319076"
PREPARED = {
    "aq-024-6f6781246415": ROOT / "runs/n6-a1b-2026-10-08/units/aq-024-6f6781246415/preparation/prepared-small-first/prepare-6d36fa6b-c11a-48a4-a5d7-1b825043f5e2/prepared.json",
    "aq-017-9703bbce0c43": ROOT / "runs/n6-a1b-2026-10-08/units/aq-017-9703bbce0c43/preparation/prepared-small-first/prepare-92649d88-3a4d-4efc-ba9a-0e167d5aeecd/prepared.json",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pin(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def read(ref: dict) -> dict:
    path = Path(ref["path"])
    if sha(path) != ref["sha256"]:
        raise ValueError("input SHA differs: " + str(path))
    return json.loads(path.read_text())


def save(path: Path, value: dict) -> dict:
    if not path.is_relative_to(ROUND / "round4d") or path.exists():
        raise ValueError("new Round4d output required: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def source_root(target: dict) -> Path:
    entry = Path(target["run_entrypoint"])
    root = next((parent for parent in entry.parents if parent.name == "sources" and
                 parent.parent.parent.name == "targets"), None)
    if root is None or not entry.is_relative_to(root):
        raise ValueError("original prepared snapshot root missing")
    return root


def compiled_inputs() -> tuple[dict, dict]:
    direct_summary = json.loads((ROUND2 / "compile-summary.json").read_text())
    tag_summary = json.loads((TAG / "compile/summary.json").read_text())
    tag_plan_path = Path(tag_summary["plan"])
    if sha(tag_plan_path) != tag_summary["plan_sha256"]:
        raise ValueError("tag plan SHA changed")
    tag_plan = json.loads(tag_plan_path.read_text())
    tag_by_key = {(t["unit"], t["label"]): t for t in tag_plan["targets"]}
    direct, tagged = {}, {}
    for row in direct_summary["all_request_timings"]:
        if row["compile_success"]:
            result = read(row["result"])
            if not result["compile_success"]:
                raise ValueError("direct compile evidence differs")
            key = row["unit"], row["label"]
            direct[key] = {"constraints": next(a["header"]["constraints"] for a in result["artifacts"]
                                                if a["path"].endswith(".r1cs")),
                           "receipt": row["result"], "wrapper": {"path": result["wrapper"],
                                                                      "sha256": result["wrapper_sha256"]}}
    for row in tag_summary["results"]:
        if not row["compile_success"]:
            raise ValueError("not all selected tag wrappers compiled")
        key = row["unit"], row["label"]
        target = tag_by_key[key]
        result = read(row["result"])
        if result["wrapper_sha256"] != target["wrapper_sha256"]:
            raise ValueError("tag wrapper SHA differs")
        tagged[key] = {"constraints": row["constraints"], "receipt": row["result"],
                       "wrapper": target["wrapper"], "fragment_spec": target["fragment_spec"],
                       "inspection_eligible": target["inspection_eligible"],
                       "defining_source_file": target["defining_source_file"]}
    if len(tagged) != 48:
        raise ValueError("48 tag wrapper denominator changed")
    return direct, tagged


def recorded_compiles(prepared: dict, prepared_path: Path) -> dict:
    """Reuse successful A1b R1CS compiles after the independent round-2 inspection."""
    receipt = pin(prepared_path)
    compiled = {}
    for target in prepared["targets"]:
        structure = target["structure"]
        if not (structure["complete"] and structure["compile_success"] and
                isinstance(structure["size"], int) and structure["size"] > 0 and
                structure["r1cs_sha256"] and structure["entrypoint"] == target["run_entrypoint"]):
            continue
        wrapper_path = Path(target["run_entrypoint"])
        wrapper_sha = next(row["sha256"] for row in target["snapshot_fingerprints"]
                           if row["path"] == str(wrapper_path))
        compiled[target["definition"]["label"]] = {
            "constraints": structure["size"], "receipt": receipt,
            "r1cs_sha256": structure["r1cs_sha256"],
            "wrapper": {"path": str(wrapper_path), "sha256": wrapper_sha},
            "defining_source_file": (target["inspection"]["root"] or {}).get("path")}
    return compiled


def free_internal() -> int:
    return shutil.disk_usage(ROUND).free


def check_internal_space(floor_gib: int) -> None:
    if free_internal() < floor_gib * 2**30:
        raise ValueError(f"Round4d internal free space below {floor_gib} GiB")


def make_extra(unit: str, target: dict, wrapper: dict, compiler: dict,
               inspection_ref: dict, audit: dict) -> tuple[dict, dict, dict, dict]:
    label = target["definition"]["label"]
    original_root = source_root(target)
    snapshot = BASE / "snapshots" / unit / label
    if snapshot.exists():
        raise ValueError("new snapshot already exists")
    check_internal_space(18)
    engine.v1.ensure_no_symlinks(original_root)
    shutil.copytree(original_root, snapshot, symlinks=True)
    relative = Path(target["run_entrypoint"]).relative_to(original_root)
    entrypoint = snapshot / relative
    source_wrapper = Path(wrapper["path"])
    if sha(source_wrapper) != wrapper["sha256"]:
        raise ValueError("compiled wrapper changed")
    if sha(entrypoint) != wrapper["sha256"]:
        shutil.copyfile(source_wrapper, entrypoint)
    snapshot_id = "s4d-" + label[:20]
    tree_sha = engine.v1.tree_sha256(snapshot)
    sample = {"id": snapshot_id, "path": str(snapshot), "tree_sha256": tree_sha,
              "candidate_globs": ["**/zkfdo_report_counterexample.json"],
              "expected_baseline_candidates": 0}
    plan_row = copy.deepcopy(target)
    plan_row["run_entrypoint"] = str(entrypoint)
    plan_row["definition"]["entrypoint"] = str(source_wrapper)
    for source, copied in zip(plan_row["source_fingerprints"], plan_row["snapshot_fingerprints"], strict=True):
        old_path = Path(copied["path"])
        copied["path"] = str(snapshot / old_path.relative_to(original_root))
        if old_path == Path(target["run_entrypoint"]):
            source["path"] = str(source_wrapper)
            source["sha256"] = wrapper["sha256"]
            copied["sha256"] = wrapper["sha256"]
    plan_row["s_round4d_round2_inspection"] = {"source": inspection_ref,
        "target_id": target["target_id"], "inspection_sha256": audit["inspection_sha256"],
        "inspection_eligible": True, "original_inspection_complete": target["inspection"]["complete"]}
    plan_row["s_round4d_compiler"] = compiler["receipt"]
    definition_source = compiler.get("defining_source_file")
    if definition_source is None:
        template = target["definition"]["template_name"]
        pattern = re.compile(r"\btemplate\s+" + re.escape(template) + r"\s*\(")
        matches = [row["path"] for row in target["source_fingerprints"]
                   if pattern.search(Path(row["path"]).read_text(errors="replace"))]
        if len(matches) != 1:
            raise ValueError("defining source ambiguous")
        definition_source = matches[0]
    return sample, plan_row, {"source_snapshot_id": snapshot_id,
        "source_snapshot_path": str(snapshot), "entrypoint_relative": str(relative),
        "entrypoint_sha256": wrapper["sha256"], "target_id": target["target_id"]}, {
        "label": label, "target_id": target["target_id"], "template": target["definition"]["template_name"],
        "defining_source_file": definition_source,
        "concrete_parameters": target["definition"]["concrete_parameters"],
        "constraints": compiler["constraints"], "eligible": True,
        "compiler_receipt": compiler["receipt"], "round2_inspection": inspection_ref}


def main() -> None:
    if os.getpriority(os.PRIO_PROCESS, 0) != 19 or sha(ROOT / "scripts/run_policy_b_order.py") != POLICY_SHA:
        raise ValueError("nice 19 and fixed Policy B required")
    if BASE.exists():
        raise ValueError("new prepared-S output required")
    check_internal_space(30)
    bundle = json.loads(OLD.read_text())
    if len(bundle["jobs"]) != 45 or len(bundle["revision_ids"]) != 15:
        raise ValueError("S denominator changed")
    direct, tagged = compiled_inputs()
    additions, table = {}, []
    BASE.mkdir(parents=True)
    for unit in bundle["revision_ids"]:
        old_job = next(j for j in bundle["jobs"] if j["revision"] == unit)
        old_meta = read(old_job["order_metadata"])
        old_ids = {t["target_id"] for t in old_meta["targets"]}
        old_labels = {t["label"] for t in old_meta["targets"]}
        rows = []
        inspection_count = len(old_ids)
        tag_entered = 0
        deferred = 0
        tag_incomplete = 0
        if unit in PREPARED:
            prepared_path = PREPARED[unit]
            prepared = json.loads(prepared_path.read_text())
            by_label = {t["definition"]["label"]: t for t in prepared["targets"]}
            old_compiled = recorded_compiles(prepared, prepared_path)
            audit_path = ROUND2 / "after" / f"{unit}.json"
            audit_raw = json.loads(audit_path.read_text())
            by_audit = {t["label"]: t for t in audit_raw["targets"]}
            inspection_ref = pin(audit_path)
            eligible = {t["label"] for t in audit_raw["targets"] if t["inspection_eligible"]}
            inspection_count = len(eligible)
            available = set(old_compiled) | {label for rev, label in set(direct) | set(tagged)
                                              if rev == unit}
            for label in sorted(eligible & available - old_labels):
                key = unit, label
                compiler = tagged.get(key) or direct.get(key) or old_compiled.get(label)
                if compiler is None:
                    raise ValueError("missing compiler evidence")
                wrapper = compiler["wrapper"]
                rows.append(make_extra(unit, by_label[label], wrapper, compiler,
                                       inspection_ref, by_audit[label]))
                tag_entered += key in tagged
            deferred = len(eligible - (old_labels | available))
            tag_incomplete = sum(1 for (rev, _), row in tagged.items()
                                 if rev == unit and not row["inspection_eligible"])
        additions[unit] = rows
        table.append({"revision": unit, "old_S_targets": len(old_ids),
                      "round2_inspection_eligible": inspection_count,
                      "improved_prepared_with_compiler_evidence": len(old_ids) + len(rows),
                      "tag_wrappers_entered": tag_entered, "final_bundle_targets": len(old_ids) + len(rows),
                      "postdeadline_compile_pending": deferred,
                      "tag_wrappers_inspection_incomplete": tag_incomplete})
    jobs = []
    for job in bundle["jobs"]:
        unit = job["revision"]
        spec = copy.deepcopy(read(job["prepared_spec"]))
        plan = copy.deepcopy(read(job["prepared_plan"]))
        meta = copy.deepcopy(read(job["order_metadata"]))
        by_id = {target["target_id"]: target for target in spec["targets"]}
        plan_by_id = {target["target_id"]: target for target in plan["targets"]}
        for snapshot, plan_row, fields, metadata in additions[unit]:
            sample = copy.deepcopy(spec["targets"][0])
            sample.update(fields)
            spec["source_snapshots"].append(snapshot)
            by_id[sample["target_id"]] = sample
            plan_by_id[plan_row["target_id"]] = copy.deepcopy(plan_row)
            meta["targets"].append(metadata)
        ordered = [row["target_id"] for row in policy.policy_b_order(meta["targets"])]
        if len(ordered) != len(by_id) or set(ordered) != set(by_id) or set(ordered) != set(plan_by_id):
            raise ValueError("Policy B / S target set differs")
        spec["targets"] = [by_id[target_id] for target_id in ordered]
        plan["targets"] = [plan_by_id[target_id] for target_id in ordered]
        folder = BASE / "jobs" / f"{unit}-seed-{job['seed']}"
        for rank, (target, row) in enumerate(zip(spec["targets"], plan["targets"], strict=True), 1):
            target["rank"] = rank
            row["rank"] = rank
        spec["campaign_id"] += "-round4d-inspected"
        plan_path = folder / "ordered-plan.json"
        plan["plan_path"] = str(plan_path)
        plan_pin = save(plan_path, plan)
        next(p for p in spec["pinned_files"] if p["label"] == "plan").update(plan_pin)
        spec_pin = save(folder / "spec.json", spec)
        meta["source_spec"] = spec_pin
        meta["source_plan"] = plan_pin
        meta_pin = save(folder / "policy-metadata.json", meta)
        engine.validate_spec_v4(spec)
        roots = {row["id"]: Path(row["path"]) for row in spec["source_snapshots"]}
        verified = engine.verify_plan_v4(spec, roots)
        if verified["status"] != "verified" or verified["target_count"] != len(ordered):
            raise ValueError("S v4 plan verification failed")
        jobs.append({**job, "prepared_spec": spec_pin, "prepared_plan": plan_pin,
                     "order_metadata": meta_pin, "plan_validation": verified,
                     "source_snapshot_count": len(spec["source_snapshots"])})
    result = {**bundle, "schema": "s-round4d-S-input-bundle-v1", "source_bundle": pin(OLD),
              "jobs": jobs, "ready_for_execution": False,
              "reason": "full improved preparation and six inspection-incomplete tag targets remain pending",
              "policy_b_script_sha256": POLICY_SHA, "table": table,
              "tag_compile_summary": pin(TAG / "compile/summary.json"),
              "round2_measurement": pin(ROUND2 / "after/measurement.json")}
    bundle_pin = save(BASE / "s-input-bundle.json", result)
    print(json.dumps({"bundle": bundle_pin, "verified": len(jobs),
                      "targets_per_seed": sum(row["final_bundle_targets"] for row in table),
                      "tag_wrappers_entered": sum(row["tag_wrappers_entered"] for row in table),
                      "pending_compile": sum(row["postdeadline_compile_pending"] for row in table)}))


if __name__ == "__main__":
    main()
