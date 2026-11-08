#!/usr/bin/env python3
"""Build fixed Policy B inputs from SHA-pinned, completed S preflight records.

This only reads the 45 explicitly listed S specs, their pinned plans, and the
two documented preflight summaries. It does not compile, fuzz, inspect
candidate results, or use RQ-C annotations for ordering.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import run_policy_b_order as policy

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/s-round4-2026-10-27/round4c-main"
BUNDLE = OUT / "s-input-bundle-v1.json"
A1B = ROOT / "runs/n6-a1b-2026-10-08/preflight-v3/preflight-all.json"
A3B = ROOT / "runs/n6-a3-2026-10-08.noindex/pragma-b/preflight-proof-v2.json"
COUNTS = re.compile(r"^\s*(non-linear|linear) constraints:\s*(\d+)\s*$", re.M)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pin(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def read(path: Path, expected: str | None = None) -> dict:
    require(path.is_file() and path.resolve().is_relative_to(ROOT), f"missing input: {path}")
    require(expected is None or sha(path) == expected, f"input SHA changed: {path}")
    return json.loads(path.read_text())


def save(path: Path, data: dict) -> dict:
    require(path.is_relative_to(OUT) and not path.exists(), f"new Round4 output required: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def source_for(job: dict, summary: dict, pragma: dict) -> tuple[Path, str]:
    key = f"{job['revision']}-seed-{job['seed']}:S"
    if job["revision"].startswith(("aq-035-", "aq-036-")):
        row = pragma["rows"][key]
        require(row["status"] == "passed" and row["destination_spec_sha256"] ==
                job["source_spec"]["sha256"], "pragma preflight/spec mismatch")
        return ROOT / row["destination_preflight"], row["destination_preflight_sha256"]
    row = summary["results"][key]
    require(row["status"] == "passed", "source preflight did not pass")
    # A1b prepared the same target IDs used by the later pinned v4 S specs;
    # exact target-set equality is checked below before using any counts.
    return ROOT / row["preflight"], row["preflight_sha256"]


def constraint_count(stdout: Path) -> int:
    data = stdout.read_text(errors="replace")
    counts = COUNTS.findall(data)
    require(len(counts) == 2 and {name for name, _ in counts} == {"linear", "non-linear"},
            f"ambiguous compiler constraint totals: {stdout}")
    return sum(int(number) for _, number in counts)


def metadata(job: dict, summary: dict, pragma: dict) -> dict:
    spec_path = Path(job["source_spec"]["path"])
    spec = read(spec_path, job["source_spec"]["sha256"])
    require(spec["method"] == "split" and spec["initial_seed"] == job["seed"] and
            spec["total_budget_seconds"] == 600 and spec["attempt_cap_seconds"] == 30,
            "fixed S controls changed")
    plan_ref = next(p for p in spec["pinned_files"] if p["label"] == "plan")
    plan_path = Path(plan_ref["path"])
    plan = read(plan_path, plan_ref["sha256"])
    by_id = {t["target_id"]: t for t in plan["targets"]}
    require(len(by_id) == len(plan["targets"]), "duplicate plan target")
    preflight_path, preflight_sha = source_for(job, summary, pragma)
    preflight = read(preflight_path, preflight_sha)
    require(preflight["status"] == "passed", "preflight did not pass")
    compiled = {c["target_id"]: c for c in preflight["compile"]}
    spec_ids = {t["target_id"] for t in spec["targets"]}
    require(len(spec_ids) == len(spec["targets"]) and spec_ids == set(by_id) == set(compiled),
            "preflight/plan/spec target set differs")
    rows = []
    for target in spec["targets"]:
        target_id = target["target_id"]
        result = compiled[target_id]
        require(result["status"] == "succeeded" and result["exit_code"] == 0,
                "target lacks successful compiler evidence")
        definition = by_id[target_id]["definition"]
        inspection = by_id[target_id]["inspection"]
        matches = {instance["path"] for instance in inspection["instances"]
                   if instance["template_name"] == definition["template_name"] and
                   instance["concrete_parameters"] == definition["concrete_parameters"]}
        require(inspection["complete"] is True and len(matches) == 1,
                "defining source is ambiguous")
        stdout = preflight_path.parent / result["stdout_path"]
        require(stdout.is_file() and stdout.resolve().is_relative_to(ROOT), "compiler log missing")
        rows.append({"label": definition["label"], "target_id": target_id,
                     "template": definition["template_name"],
                     "defining_source_file": next(iter(matches)),
                     "concrete_parameters": definition["concrete_parameters"],
                     "constraints": constraint_count(stdout), "eligible": True,
                     "compiler_stdout_sha256": sha(stdout)})
    require(len({r["label"] for r in rows}) == len(rows), "duplicate Policy B label")
    policy.policy_b_order(rows)
    return {"schema_version": 1, "unit": job["revision"], "targets": rows,
            "source_spec": job["source_spec"], "source_plan": pin(plan_path),
            "source_preflight": {"path": str(preflight_path), "sha256": preflight_sha},
            "policy_script_sha256": sha(ROOT / "scripts/run_policy_b_order.py")}


def main() -> None:
    bundle = read(BUNDLE)
    summary, pragma = read(A1B), read(A3B)
    require(len(bundle["jobs"]) == 45 and len(bundle["revision_ids"]) == 15,
            "fixed 15×3 bundle changed")
    first_by_revision = {}
    jobs = []
    for job in bundle["jobs"]:
        value = metadata(job, summary, pragma)
        revision = job["revision"]
        core = [{key: item[key] for key in ("label", "target_id", "template",
                                             "defining_source_file", "concrete_parameters",
                                             "constraints", "eligible")}
                for item in value["targets"]]
        if revision not in first_by_revision:
            first_by_revision[revision] = core
        else:
            require(first_by_revision[revision] == core,
                    "seed-specific Policy B metadata differs within revision")
        ref = save(OUT / "policy-metadata-v2" /
                   f"{revision}-seed-{job['seed']}.json", value)
        jobs.append({**job, "order_metadata": ref})
    result = {**bundle, "schema": "s-round4c-S-input-bundle-v2",
              "source_bundle": pin(BUNDLE), "policy_b_script_sha256": sha(ROOT / "scripts/run_policy_b_order.py"),
              "jobs": jobs, "metadata_ready": True, "ready_for_execution": False,
              "remaining": "new Round4 source snapshots/prepared specs and measured disk peak"}
    receipt = save(OUT / "s-input-bundle-v2.json", result)
    print(json.dumps({"bundle": receipt, "revisions": len(first_by_revision),
                      "jobs": len(jobs), "targets_per_seed":
                      sum(len(rows) for rows in first_by_revision.values())}))


if __name__ == "__main__":
    main()
