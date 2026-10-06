"""Builds the N6 branch-B target list from fixed preparation records (N5 v1 §3).

Reads only E-02 and F-01 preparation records; no zkFuzz result exists for these targets.
Pool: deployment_main by the E-02 path rule, original constraints >= 100,000, final
preparation success or partial, plan.json present. Stage 1: per repository the smallest
entrypoints by constraints (tie: entrypoint key), taken round-robin over repositories in
case-insensitive name order until 10 targets, at most 2 per repository. Stage 2: the rest.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e02_production_mains import classify_role  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "n6_targets_b_2026-10-06.json"
THRESHOLD = 100_000
STAGE1_MAX, PER_REPO = 10, 2
ZKBUGS = ROOT / ".external" / "zkbugs" / "dataset" / "circom"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def zkbugs_project(repository: str) -> bool:
    return (ZKBUGS / repository).is_dir()


def e02_pool() -> list[dict]:
    data = json.loads((ROOT / "docs/e02_production_mains_results_2026-10-05.json").read_text())
    rows = []
    for e in data["deployment_entrypoints"]:
        if e["preparation_final_status"] not in ("success", "partial"):
            continue
        if (e["constraints"] or 0) < THRESHOLD:
            continue
        directory = ROOT / "runs/e02-production-mains-2026-10-05/preparation-measurements" / e["identifier"]
        rows.append({"source": "E-02", "identifier": e["identifier"], "repository": e["repository"],
                     "commit": e["commit_sha"], "entrypoint_key": e["entrypoint_key"],
                     "constraints": e["constraints"], "preparation_status": e["preparation_final_status"],
                     "measurement_dir": directory})
    return rows


def f01_pool() -> list[dict]:
    data = json.loads((ROOT / "docs/f01_discovery_evidence_2026-10-03.json").read_text())
    rows = []
    for e in data["large_entrypoints"]:
        if e["f01_status"] not in ("success", "partial") or e["constraints"] < THRESHOLD:
            continue
        directory = ROOT / "runs/f01-2026-10-03/measurements" / e["identifier"]
        result = json.loads((directory / "result.json").read_text())
        rows.append({"source": "F-01", "identifier": e["identifier"], "repository": e["repository"],
                     "commit": result["commit"], "entrypoint_key": result["entrypoint_key"],
                     "constraints": e["constraints"], "preparation_status": e["f01_status"],
                     "measurement_dir": directory})
    return rows


def main():
    pool, excluded = [], []
    for row in e02_pool() + f01_pool():
        role, _ = classify_role(row["entrypoint_key"])
        plan = row["measurement_dir"] / "plan.json"
        reason = None if role == "deployment_main" else "role_" + role
        if reason is None and not plan.is_file():
            reason = "plan_missing"
        record = {k: v for k, v in row.items() if k != "measurement_dir"}
        record["measurement_dir"] = rel(row["measurement_dir"])
        record["zkbugs_project"] = zkbugs_project(row["repository"])
        if reason:
            excluded.append(record | {"reason": reason})
            continue
        record["plan"] = {"path": rel(plan), "sha256": sha(plan)}
        pool.append(record)
    pool.sort(key=lambda r: (r["repository"].lower(), r["constraints"], r["entrypoint_key"]))
    by_repo: dict[str, list[dict]] = {}
    for row in pool:
        by_repo.setdefault(row["repository"], []).append(row)
    order = sorted(by_repo, key=str.lower)
    stage1 = []
    for depth in range(PER_REPO):
        for repo in order:
            if len(stage1) < STAGE1_MAX and depth < len(by_repo[repo]):
                stage1.append(by_repo[repo][depth])
    chosen = {r["identifier"] for r in stage1}
    data = {
        "schema_version": 1,
        "task": "N6 branch B target list",
        "protocol": "docs/n5_evaluation_protocol_v1_2026-10-06.md",
        "rule": {"role": "deployment_main (E-02 path rule)", "min_constraints": THRESHOLD,
                 "preparation": ["success", "partial"], "stage1_max": STAGE1_MAX, "per_repository": PER_REPO,
                 "stage1_order": "round-robin over repositories in case-insensitive name order; within a "
                                 "repository by constraints then entrypoint key",
                 "clarification": "N5 v1 did not say how to cap at 10 when more than 5 repositories "
                                  "qualify; this round-robin was fixed before any branch-B zkFuzz run"},
        "zkfuzz_results_seen": False,
        "stage1": [r | {"stage": 1} for r in stage1],
        "stage2": [r | {"stage": 2} for r in pool if r["identifier"] not in chosen],
        "excluded": excluded,
        "counts": {"pool": len(pool), "stage1": len(stage1), "stage2": len(pool) - len(stage1),
                   "excluded": len(excluded), "repositories": len(order)},
    }
    text = json.dumps(data, indent=1, ensure_ascii=False)
    assert "/Users/" not in text, "absolute path left in target list"
    if OUT.exists() and OUT.read_text() != text + "\n":
        raise SystemExit(f"{OUT} exists with different content; create a new version instead")
    OUT.write_text(text + "\n")
    print(rel(OUT), sha(OUT), data["counts"])
    for r in stage1:
        print(f"  {r['repository']:<40} {r['constraints']:>9} {r['preparation_status']:<8} {r['entrypoint_key']}")


if __name__ == "__main__":
    main()
