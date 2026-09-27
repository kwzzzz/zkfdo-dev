#!/usr/bin/env python3
"""Development ranking pilot under a scarce time budget (T4c follow-up).

Each variant is the inference project with exactly one qualified injected fault. Every unique
concrete instance reachable from the project entrypoint is a target with a direct wrapper in
one directory, named by source path, template and parameters, so that path order follows
source order. The configuration in pilot-config.json is fixed before any run.

Stages: prepare, run, review, summarize. Raw runs stay under the ignored run directory.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = ROOT / "runs/dev-ranking-pilot-2026-09-27"
CONFIG = json.loads((HERE / "pilot-config.json").read_text())
BIN = RUNS / "bin/zkfDO"
VERIFIER = RUNS / "bin/zkfdo-relation-verifier"
CANDIDATE_ADAPTER = b"zkfDO candidate adapter zkfuzz-counterexample-v1 schema 1\n"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(from_dir, path):
    return os.path.relpath(Path(path).resolve(), Path(from_dir).resolve())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def run(arguments, **kwargs):
    completed = subprocess.run([str(a) for a in arguments], capture_output=True, text=True, **kwargs)
    if completed.returncode != 0:
        raise SystemExit(f"command failed: {arguments}\n{completed.stderr[-3000:]}")
    return completed.stdout


def wrapper_name(source_rel, template, parameters):
    stem = str(source_rel).removesuffix(".circom").replace("/", "__")
    suffix = "_".join(parameters)
    return f"{stem}__{template}{'_' + suffix if suffix else ''}.circom"


def variant_paths(variant):
    base = RUNS / variant["id"]
    report = HERE / variant["id"]
    return base, report


def prepare(variant):
    base, report = variant_paths(variant)
    source_plan = json.loads((ROOT / variant["injection_plan"]).read_text())
    source_dir = (ROOT / variant["injection_plan"]).parent
    target = source_plan["target"]
    parameters = [p["value_decimal"] for p in target["concrete_parameters"]]
    wrapper_rel = Path(CONFIG["wrapper_directory"]) / wrapper_name(
        target["source_path"], target["template"], parameters
    )

    # 1. Requalify the injection with the campaign wrapper location.
    plan = dict(source_plan)
    for key in ("common_input",):
        plan[key] = relative(report, source_dir / source_plan[key])
    plan["project"] = dict(source_plan["project"])
    plan["project"]["checkout"] = relative(report, source_dir / source_plan["project"]["checkout"])
    plan["contract"] = json.loads(json.dumps(source_plan["contract"]))
    plan["contract"]["predicate"]["path"] = relative(
        report, source_dir / source_plan["contract"]["predicate"]["path"]
    )
    plan["workspace"] = relative(report, base / "injection")
    plan["output"] = "injection"
    plan["wrapper_path"] = str(wrapper_rel)
    write_json(report / "injection-plan.json", plan)
    run([BIN, "experiment", "inject", "--plan", report / "injection-plan.json",
         "--relation-verifier-bin", VERIFIER])
    injection = report / "injection"
    manifest_ref = injection / "engine-source-manifest.json"
    run([BIN, "experiment", "review", "--request", injection / "request.json",
         "--output", injection / "qualification",
         "--source-revision", f"worktree-engine-manifest:{sha256(manifest_ref)}",
         "--engine-source-manifest", manifest_ref])
    qualification = json.loads((injection / "qualification/review-report.json").read_text())
    verdict = qualification["reviews"][0]["ground_truth_qualification"]
    if verdict != "qualified":
        raise SystemExit(f"{variant['id']} injection is {verdict}")

    # 2. Every unique instance reachable from the entrypoint becomes a target.
    mutant = (base / "injection/mutant").resolve()
    discovery = json.loads(next((base / "injection/discovery-mutant").rglob("discovery.json")).read_text())
    if discovery["unsupported"]:
        raise SystemExit("mutant discovery is incomplete")
    instances = {}
    keys = [discovery["root_instance_key"]] + [t["instance_key"] for t in discovery["targets"]]
    for key in keys:
        source, call = key.rsplit("::", 1)
        template, arguments = call[:-1].split("(", 1)
        params = [a for a in arguments.split(", ") if a]
        instances[key] = (Path(source).resolve().relative_to(mutant), template, params)
    spec = json.loads((injection / "spec.json").read_text())
    contract = plan["contract"]
    targets = []
    for key in sorted(instances):
        source_rel, template, params = instances[key]
        wrapper = Path(CONFIG["wrapper_directory"]) / wrapper_name(source_rel, template, params)
        wrapper_path = mutant / wrapper
        include = os.path.relpath(mutant / source_rel, wrapper_path.parent)
        text = (f"pragma circom 2.1.6;\n\ninclude \"{include}\";\n\n"
                f"component main = {template}({', '.join(params)});\n")
        injected = key == spec["target_binding"]["instance_key"]
        if injected:
            if wrapper_path.read_text() != text:
                raise SystemExit("injected wrapper differs from the campaign wrapper scheme")
        else:
            wrapper_path.parent.mkdir(parents=True, exist_ok=True)
            wrapper_path.write_text(text)
        targets.append({
            "label": f"{variant['id']} {source_rel}::{template}({', '.join(params)})",
            "project": plan["project"]["name"],
            "revision": plan["project"]["revision"],
            "project_root": relative(report, mutant),
            "entrypoint": relative(report, wrapper_path),
            "template_name": template,
            "concrete_parameters": params,
            "prime": "bn128",
            "compile_args": [],
            "mode": "direct",
            "input_assumptions": contract["input_contract_statement"] if injected
            else CONFIG["noninjected_input_assumptions"],
            "input_contract": contract["input_contract"] if injected else {"kind": "field_only"},
            "known_defects": [],
        })
    manifest = {
        "schema_version": 2,
        "name": f"dev-ranking-pilot-{variant['id']}",
        "description": "Development ranking pilot variant with one qualified injected fault.",
        "targets": targets,
        "exclusions": [],
    }
    write_json(report / "manifest.json", manifest)

    # 3. Prepare once per variant with the pinned tools.
    tools = CONFIG["tools"]
    prepared_dir = base / "prepared"
    run([BIN, "experiment", "prepare", "--manifest", report / "manifest.json",
         "--output", prepared_dir,
         "--circom-bin", tools["circom"], "--zkfuzz-bin", tools["zkfuzz"],
         "--circomspect-bin", ROOT / tools["circomspect"],
         "--analyzer-version", tools["circomspect_version"],
         "--analyzer-revision", tools["circomspect_revision"],
         "--tool-timeout-seconds", str(CONFIG["tool_timeout_seconds"])])
    prepared_path = next(prepared_dir.rglob("prepared*.json"))
    prepared = json.loads(prepared_path.read_text())
    eligible = [t for t in prepared["targets"] if t["eligible"]]
    injected_ids = [t["target_id"] for t in prepared["targets"]
                    if t["target_id"] == spec["target_binding"]["target_id"]]
    summary = {
        "variant": variant["id"],
        "targets": len(prepared["targets"]),
        "eligible": len(eligible),
        "excluded": {t["target_id"]: t["exclusion_reasons"] for t in prepared["targets"] if not t["eligible"]},
        "injected_target_bound": len(injected_ids) == 1,
        "prepared": relative(ROOT, prepared_path),
        "prepared_sha256": sha256(prepared_path),
    }
    write_json(report / "prepare-summary.json", summary)
    print(json.dumps(summary, indent=2))


def campaign(variant):
    base, report = variant_paths(variant)
    prepared = ROOT / json.loads((report / "prepare-summary.json").read_text())["prepared"]
    spec = json.loads((report / "injection/spec.json").read_text())
    injected_id = spec["target_binding"]["target_id"]
    ledger_path = report / "campaign-ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
        "schema_version": 1, "variant": variant["id"], "executions": []}
    done = {(entry["block"], entry["strategy"]) for entry in ledger["executions"]}
    strategies = CONFIG["strategies"]
    tools = CONFIG["tools"]
    for block in CONFIG["blocks"]:
        number = block["block"]
        shift = (number - 1) % len(strategies)
        for strategy in strategies[shift:] + strategies[:shift]:
            if (number, strategy) in done:
                continue
            directory = base / "campaign" / f"block-{number}" / strategy
            if directory.exists():
                raise SystemExit(f"refusing to reuse {directory}")
            directory.mkdir(parents=True)
            plan_path = directory / "plan.json"
            arguments = [BIN, "experiment", "plan", "--prepared", prepared,
                         "--strategy", strategy, "--output", plan_path]
            if strategy == "random":
                arguments += ["--ranking-seed", block["random_ranking_seed"]]
            run(arguments, cwd=ROOT)
            plan = json.loads(plan_path.read_text())
            order = [target["target_id"] for target in plan["targets"]]
            run([BIN, "experiment", "run", "--plan", plan_path, "--zkfuzz-bin", tools["zkfuzz"],
                 "--budget-seconds", CONFIG["budget_seconds_per_target"],
                 "--total-budget-seconds", CONFIG["total_budget_seconds"],
                 "--zkfuzz-seed", block["zkfuzz_seed"], "--output", directory / "execution"],
                cwd=ROOT)
            outcome_path = next((directory / "execution").glob("execution-*/outcome.json"))
            outcome = json.loads(outcome_path.read_text())
            scheduler = outcome["scheduler"]
            started = [entry for entry in scheduler["runs"] if entry["result"] is not None]
            injected_runs = [entry for entry in started if entry["target_id"] == injected_id]
            ledger["executions"].append({
                "block": number,
                "strategy": strategy,
                "zkfuzz_seed": block["zkfuzz_seed"],
                "random_ranking_seed": block["random_ranking_seed"] if strategy == "random" else None,
                "plan": {"path": relative(ROOT, plan_path), "sha256": sha256(plan_path)},
                "outcome": {"path": relative(ROOT, outcome_path), "sha256": sha256(outcome_path)},
                "planned_targets": len(order),
                "injected_planned_rank": order.index(injected_id) + 1 if injected_id in order else None,
                "started_targets": len(started) + len(scheduler["failures"]),
                "skipped_targets": len(scheduler["skipped"]),
                "injected_status": injected_runs[0]["result"]["status"] if injected_runs else "not-started",
                "candidate_count": len(outcome["counterexample_candidates"]),
                "elapsed_seconds": scheduler["elapsed_seconds"],
            })
            write_json(ledger_path, ledger)
            print(variant["id"], number, strategy, ledger["executions"][-1]["injected_status"], flush=True)


def review(variant):
    base, report = variant_paths(variant)
    injection = report / "injection"
    ledger = json.loads((report / "campaign-ledger.json").read_text())
    spec_path = injection / "spec.json"
    spec = json.loads(spec_path.read_text())
    index_path = injection / "qualification/ground-truth-index.json"
    engine = (ROOT / "src/candidate_review/engine.rs").read_bytes()
    request_path = report / "backend-request.json"
    request = {
        "schema_version": 1,
        "request_id": f"pilot-{variant['id']}-backend",
        "kind": "backend-candidates",
        "review_specs": [{"path": relative(report, spec_path), "sha256": sha256(spec_path)}],
        "executions": [{
            "execution_id": f"{variant['id']}-block-{entry['block']}-{entry['strategy']}",
            "campaign_coordinates": {"block": entry["block"], "strategy": entry["strategy"]},
            "plan": {"path": relative(report, ROOT / entry["plan"]["path"]), "sha256": entry["plan"]["sha256"]},
            "outcome": {"path": relative(report, ROOT / entry["outcome"]["path"]), "sha256": entry["outcome"]["sha256"]},
        } for entry in sorted(ledger["executions"], key=lambda e: (e["block"], e["strategy"]))],
        "candidate_adapter": {
            "id": "zkfuzz-counterexample-v1",
            "implementation_sha256": hashlib.sha256(engine + b"\0" + CANDIDATE_ADAPTER).hexdigest(),
        },
        "candidate_policy": "all-outcome-candidates",
        "unmatched_candidate_policy": "record-unreviewed",
        "qualification_bundles": [{
            "injection_id": spec["injection_ground_truth"]["injection_id"],
            "path": relative(report, index_path),
            "sha256": sha256(index_path),
        }],
    }
    write_json(request_path, request)
    manifest = injection / "engine-source-manifest.json"
    run([BIN, "experiment", "review", "--request", request_path,
         "--output", report / "backend-review",
         "--source-revision", f"worktree-engine-manifest:{sha256(manifest)}",
         "--engine-source-manifest", manifest], cwd=ROOT)
    result = json.loads((report / "backend-review/review-report.json").read_text())
    print(variant["id"], result["status"], json.dumps(result["summary"]))


def summarize():
    rows = []
    for variant in CONFIG["variants"]:
        base, report = variant_paths(variant)
        ledger = json.loads((report / "campaign-ledger.json").read_text())
        backend = json.loads((report / "backend-review/review-report.json").read_text())
        bundle = json.loads((report / "backend-review/bundle-index.json").read_text())
        detected = {}
        for review_row in backend["reviews"]:
            if review_row["disposition"] == "validated" and review_row["cause_attribution"]["verdict"] == "matched":
                detected.setdefault(review_row["binding"]["execution_id"], []).append(review_row)
        evaluations = {row["execution_id"]: row for row in bundle["execution_evaluations"]}
        for entry in ledger["executions"]:
            execution_id = f"{variant['id']}-block-{entry['block']}-{entry['strategy']}"
            evaluation_ref = evaluations.get(execution_id, {}).get("evaluator_output")
            first = None
            if evaluation_ref:
                evaluation = json.loads(((report / "backend-review") / evaluation_ref["path"]).read_text())
                first = evaluation.get("first_confirmed_original_component_defect_observed_by_seconds")
            rows.append({
                "variant": variant["id"],
                "block": entry["block"],
                "strategy": entry["strategy"],
                "planned_targets": entry["planned_targets"],
                "injected_planned_rank": entry["injected_planned_rank"],
                "started_targets": entry["started_targets"],
                "injected_status": entry["injected_status"],
                "detected": execution_id in detected,
                "detection_upper_bound_seconds": first,
            })
    by_strategy = {}
    for strategy in CONFIG["strategies"]:
        selected = [row for row in rows if row["strategy"] == strategy]
        times = [row["detection_upper_bound_seconds"] for row in selected if row["detected"]]
        by_strategy[strategy] = {
            "executions": len(selected),
            "detected": sum(row["detected"] for row in selected),
            "mean_planned_rank": sum(row["injected_planned_rank"] for row in selected) / len(selected),
            "mean_started_targets": sum(row["started_targets"] for row in selected) / len(selected),
            "median_detection_upper_bound_seconds": sorted(times)[len(times) // 2] if times else None,
        }
    write_json(HERE / "results.json", {"schema_version": 1, "rows": rows, "by_strategy": by_strategy})
    print(json.dumps(by_strategy, indent=2))


def main():
    stage, *names = sys.argv[1:]
    if stage == "summarize":
        summarize()
        return
    variants = [v for v in CONFIG["variants"] if not names or v["id"] in names]
    for variant in variants:
        {"prepare": prepare, "run": campaign, "review": review}[stage](variant)


if __name__ == "__main__":
    main()
