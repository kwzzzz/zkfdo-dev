#!/usr/bin/env python3
"""Read-only ledger audit of the explicitly selected A development runs."""
import argparse
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runs/n7-a-sj-cold-2026-10-29-v2"
OUT = ROOT / "runs/j-speed-2026-11-03/profile-v2"
PRIOR_PROFILE = ROOT / "runs/j-speed-2026-11-03/profile/profile.json"


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def recursive_values(value, key):
    if isinstance(value, dict):
        if key in value:
            yield value[key]
        for child in value.values():
            yield from recursive_values(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from recursive_values(child, key)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--artifact-profile", type=Path, default=PRIOR_PROFILE, help="reuse prior hash inventory; do not re-read large artifacts")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite a saved profile; pass --output with a new versioned directory")
    if (args.output / "profile.json").exists():
        parser.error("profile.json exists; use a new versioned output directory")
    requests = sorted(SOURCE.glob("*/judgements/*/request.json")) + sorted(SOURCE.glob("*/replay/*/request.json"))
    totals = collections.defaultdict(lambda: {"count": 0, "seconds": 0.0, "cached": 0})
    rows = []
    for request in requests:
        data = json.loads(request.read_text())
        path = request.parent / "out/result.json"
        row = {"request": str(request.relative_to(ROOT)), "request_sha256": sha(request), "result": str(path.relative_to(ROOT)), "result_exists": path.exists()}
        refs = [Path(data[k]) for k in ("source_root", "component_wrapper", "entrypoint", "base_input")]
        refs += [Path(p) for p in data.get("library_paths", [])] + [Path(data["candidate"]["path"])]
        row["missing_dependencies"] = [str(p) for p in refs if not p.exists()]
        if path.exists():
            result = json.loads(path.read_text())
            costs = result["costs"]
            steps = costs["steps"]
            bad = sum(s["seconds"] for s in steps if s["status"] in ("not_reached", "inconclusive", "timeout"))
            synth_bad = sum(s["seconds"] for s in steps if s["stage"] == "synthesis_b" and s["status"] in ("not_reached", "inconclusive", "timeout"))
            sweeps = [s for s in steps if s["label"] == "z3 exclusion sweep"]
            ends = [value for value in recursive_values(result.get("classes", []), "sweep_end") if value is not None]
            exhausted = sum(s["seconds"] for s, end in zip(sweeps, ends) if end == "time_exhausted")
            mappings = [s["seconds"] for s in steps if s["label"] == "map diagnostic witness onto the original O0 R1CS"]
            row.update(result_sha256=sha(path), preparation=result["preparation"], wall_seconds=costs["wall_seconds"], ledger_seconds=costs["total_seconds"], unsuccessful_status_seconds=bad, synthesis_b_unsuccessful_seconds=synth_bad, exhausted_sweep_seconds=exhausted, sweep_ends=ends, sweep_seconds=[s["seconds"] for s in sweeps], map_seconds=mappings, parse_o0_seconds=[s["seconds"] for s in steps if s["label"] == "parse entrypoint O0 artifacts"], verdict_counts=result["verdict_counts"])
            classes = result.get("classes", [])
            repairs = [(c.get("synthesis") or {}).get("repair") for c in classes]
            repairs = [r for r in repairs if r]
            injections = [(c.get("synthesis") or {}).get("injection") for c in classes]
            injections = [r for r in injections if r]
            row.update(ledger_outside_seconds=costs["wall_seconds"] - costs["total_seconds"], ledger_outside_percent=100 * (1 - costs["total_seconds"] / costs["wall_seconds"]), class_count=len(classes), class_metadata=[{"verdict": c.get("verdict"), "reason": c.get("reason"), "cause_before_budget": (c.get("synthesis") or {}).get("cause_before_budget"), "b_outcome": (c.get("synthesis") or {}).get("b_outcome"), "model_comparison_missing": (c.get("synthesis") or {}).get("model_comparison_missing"), "injection_outcome": ((c.get("synthesis") or {}).get("injection") or {}).get("outcome"), "repair_outcome": ((c.get("synthesis") or {}).get("repair") or {}).get("outcome")} for c in classes], uninstrumented_candidates={"retained_noninjection_repair_records": len(repairs), "retained_noninjection_repair_iterations": sum(r["iterations"] for r in repairs), "retained_noninjection_repair_solve_records": sum(len(r["solves"]) for r in repairs), "retained_injection_records": len(injections), "retained_injection_solve_records": sum(len(r["solves"]) for r in injections), "tool_hashes_before_ledger": 3, "timings_recoverable_from_historical_data": False})
            for step in steps:
                key = (step["stage"], step["label"], step["status"])
                totals[key]["count"] += 1
                totals[key]["seconds"] += step["seconds"]
                totals[key]["cached"] += int(step["cached"])
        rows.append(row)
    seed1 = SOURCE / "2026100601"
    first = json.loads((seed1 / "judgements/0/out/result.json").read_text())
    originals = {first["entrypoint"]["r1cs_sha256"]: "O1", first["entrypoint"]["o0_r1cs_sha256"]: "O0"}
    prior = json.loads(args.artifact_profile.read_text())
    artifacts = prior["seed01_compile_artifacts"]
    aggregate = [{"stage": k[0], "label": k[1], "status": k[2], **v} for k, v in sorted(totals.items())]
    complete = [r for r in rows if r["result_exists"]]
    summary = {"request_count": len(rows), "completed_result_count": len(complete), "wall_seconds": sum(r["wall_seconds"] for r in complete), "ledger_seconds": sum(r["ledger_seconds"] for r in complete), "unsuccessful_status_seconds": sum(r["unsuccessful_status_seconds"] for r in complete), "synthesis_b_unsuccessful_seconds": sum(r["synthesis_b_unsuccessful_seconds"] for r in complete), "exhausted_sweep_seconds": sum(r["exhausted_sweep_seconds"] for r in complete), "sweep_exhaustions": sum(r["sweep_ends"].count("time_exhausted") for r in complete), "positive_budget_sweep_exhaustions": sum(end == "time_exhausted" and seconds > 1 for r in complete for end, seconds in zip(r["sweep_ends"], r["sweep_seconds"]))}
    summary["ledger_outside_seconds"] = summary["wall_seconds"] - summary["ledger_seconds"]
    summary["ledger_outside_percent"] = summary["ledger_outside_seconds"] / summary["wall_seconds"] * 100
    metadata = [c for row in complete for c in row["class_metadata"]]
    summary["class_count"] = len(metadata)
    summary["class_metadata_counts"] = {key: dict(collections.Counter(str(c[key]) if c[key] is not None else "<null>" for c in metadata)) for key in ("verdict", "reason", "cause_before_budget", "b_outcome", "model_comparison_missing", "injection_outcome", "repair_outcome")}
    summary["reason_cause_cross_counts"] = [{"reason": key[0], "cause_before_budget": key[1], "count": count} for key, count in collections.Counter((c["reason"], c["cause_before_budget"]) for c in metadata).items()]
    summary["retained_noninjection_repair_records"] = sum(row["uninstrumented_candidates"]["retained_noninjection_repair_records"] for row in complete)
    summary["retained_noninjection_repair_solve_records"] = sum(row["uninstrumented_candidates"]["retained_noninjection_repair_solve_records"] for row in complete)
    jdev_path = ROOT / "runs/j-dev-2026-10-27/classes-v1.json"
    jdev_cases_path = ROOT / "runs/j-dev-2026-10-27/cases/index.json"
    jdev = json.loads(jdev_path.read_text())
    jdev_cases = json.loads(jdev_cases_path.read_text())
    jdev_metadata = {"path": str(jdev_path.relative_to(ROOT)), "sha256": sha(jdev_path), "scope": jdev["scope"], "source_sha256": jdev["source_sha256"], "classes": len(jdev["classes"]), "source_result_paths": len({c["result_path"] for c in jdev["classes"]}), "source_request_hashes": len({c["request_sha256"] for c in jdev["classes"]}), "case_index_sha256": sha(jdev_cases_path), "selected_case_count": len(jdev_cases), "metadata_counts": {key: dict(collections.Counter(str(c[key]) if c.get(key) is not None else "<null>" for c in jdev["classes"])) for key in ("verdict", "final_reason", "cause_before_budget", "b_outcome")}, "provenance_note": "Read selected A development metadata only; did not open original aq request/candidate/result paths. Cases are selected copies, not independent runs."}
    args.output.mkdir(parents=True, exist_ok=False)
    document = {"schema": "j-time-profile-v2", "scope": "A development only; saved records, no engine rerun", "summary": summary, "requests": rows, "aggregate": aggregate, "seed01_compile_artifacts": artifacts, "artifact_hash_inventory_reused_from": {"path": str(args.artifact_profile.relative_to(ROOT)), "sha256": sha(args.artifact_profile)}, "jdev_selected_copy_metadata": jdev_metadata}
    target = args.output / "profile.json"
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    table = ["| 단계 | label | status | 횟수 | 초 | cache hit |", "|---|---|---|---:|---:|---:|"]
    table += [f"| {r['stage']} | {r['label']} | {r['status']} | {r['count']} | {r['seconds']:.6f} | {r['cached']} |" for r in aggregate]
    (args.output / "ledger_table.md").write_text("\n".join(table) + "\n")
    print(json.dumps(summary, indent=2))
    print("profile_sha256", sha(target))


if __name__ == "__main__":
    main()
