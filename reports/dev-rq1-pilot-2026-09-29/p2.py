#!/usr/bin/env python3
"""Development RQ1 pilot: whole-entrypoint zkFuzz against decomposed pieces on known real bugs.

Every case was already used in development, so this is not an independent evaluation. The
configuration in pilot-config.json is fixed before any zkFuzz run on these cases.

Stages: prepare (copy the project, write one wrapper per unique reachable instance, prepare
one corpus per strategy), run (whole runs and decomposed campaigns), summarize.
Raw logs, candidates and compiled artifacts stay under the ignored run directory.
"""

import hashlib
import json
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = ROOT / "runs/dev-rq1-pilot-2026-09-29"
CONFIG = json.loads((HERE / "pilot-config.json").read_text())
BIN = RUNS / "bin/zkfDO"
DEP = ROOT / ".external/zkbugs/dataset/circom/dependencies"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(from_dir, path):
    return os.path.relpath(Path(path).resolve(), Path(from_dir).resolve())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def run(arguments, **kwargs):
    completed = subprocess.run([str(a) for a in arguments], capture_output=True, text=True, **kwargs)
    if completed.returncode != 0:
        raise SystemExit(f"command failed: {arguments}\n{completed.stderr[-3000:]}")
    return completed.stdout


def case_paths(case):
    return RUNS / case["id"], HERE / case["id"]


def libraries(case, tree):
    paths = [tree / entry for entry in case["tree_libraries"]] + [DEP, DEP / "circomlib"]
    return [path for path in paths if path.is_dir()]


def wrapper_name(source_rel, template, parameters):
    stem = str(source_rel).removesuffix(".circom").replace("/", "__")
    suffix = "_".join(parameters)
    return f"{stem}__{template}{'_' + suffix if suffix else ''}.circom"


def prepare(case):
    base, report = case_paths(case)
    tree = base / "tree"
    if tree.exists():
        raise SystemExit(f"refusing to reuse {tree}")
    tree.mkdir(parents=True)
    checkout = ROOT / case["checkout"]
    head = run(["git", "-C", checkout, "rev-parse", "HEAD"]).strip()
    if head != case["revision"]:
        raise SystemExit(f"{case['id']} checkout is at {head}, expected {case['revision']}")
    archive = subprocess.run(["git", "-C", str(checkout), "archive", "HEAD"], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
    for extra in case.get("copy_untracked", []):
        run(["cp", "-R", checkout / extra, tree / extra])
    libs = libraries(case, tree)

    discovery_dir = base / "discovery"
    arguments = [BIN, "targets", "-p", tree, "-o", discovery_dir,
                 "--entrypoint", tree / case["entrypoint"], "--compile-timeout-seconds", "300"]
    for path in libs:
        arguments += ["--library-path", path]
    run(arguments)
    discovery = json.loads(next(discovery_dir.rglob("discovery.json")).read_text())
    instances = {}
    library_instances = set()
    for target in discovery["targets"]:
        key = target["instance_key"]
        source, call = key.rsplit("::", 1)
        if not Path(source).resolve().is_relative_to(tree.resolve()):
            # Library-owned templates run inside the project pieces that use them.
            library_instances.add(key)
            continue
        template, parameters = call[:-1].split("(", 1)
        instances[key] = (Path(source).resolve().relative_to(tree.resolve()), template,
                          [p for p in parameters.split(", ") if p])
    manifest_targets = []
    for key in sorted(instances):
        source_rel, template, parameters = instances[key]
        wrapper = tree / CONFIG["wrapper_directory"] / wrapper_name(source_rel, template, parameters)
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        include = os.path.relpath(tree / source_rel, wrapper.parent)
        wrapper.write_text(f"pragma circom 2.0.0;\n\ninclude \"{include}\";\n\n"
                           f"component main = {template}({', '.join(parameters)});\n")
        compile_args = []
        for path in libs:
            compile_args += ["-l", rel(report, path)]
        manifest_targets.append({
            "label": f"{case['id']} {source_rel}::{template}({', '.join(parameters)})",
            "project": case["project"],
            "revision": case["revision"],
            "project_root": rel(report, tree),
            "entrypoint": rel(report, wrapper),
            "template_name": template,
            "concrete_parameters": parameters,
            "prime": "bn128",
            "compile_args": compile_args,
            "mode": "direct",
            "input_assumptions": "Development pilot piece without a specified input contract.",
            "input_contract": {"kind": "field_only"},
            "known_defects": [],
        })
    write_json(report / "manifest.json", {
        "schema_version": 2,
        "name": f"dev-rq1-pilot-{case['id']}",
        "description": "Unique instances reachable from the case entrypoint; development pilot.",
        "targets": manifest_targets,
        "exclusions": [],
    })
    summary = {"case": case["id"], "entrypoint": case["entrypoint"],
               "discovery_complete": not discovery["unsupported"],
               "unsupported_constructs": len(discovery["unsupported"]),
               "call_sites": len(discovery["targets"]), "unique_pieces": len(instances),
               "library_instances_not_pieces": len(library_instances),
               "ground_truth_pieces": sorted(k.rsplit("::", 1)[1] for k in instances
                                             if k.rsplit("::", 1)[1].split("(")[0] in case["ground_truth_templates"]),
               "prepared": {}}
    tools = CONFIG["tools"]
    for strategy in CONFIG["strategies"]:
        out = base / "prepared" / strategy
        run([BIN, "experiment", "prepare", "--manifest", report / "manifest.json", "--output", out,
             "--strategy", strategy, "--circom-bin", tools["circom"], "--zkfuzz-bin", tools["zkfuzz"],
             "--tool-timeout-seconds", str(CONFIG["tool_timeout_seconds"])])
        prepared_path = next(out.rglob("prepared*.json"))
        prepared = json.loads(prepared_path.read_text())
        eligible = [t for t in prepared["targets"] if t["eligible"]]
        summary["prepared"][strategy] = {
            "path": rel(ROOT, prepared_path), "sha256": sha256(prepared_path),
            "eligible": len(eligible), "total": len(prepared["targets"]),
            "eligible_ground_truth": sorted(
                "{}({})".format(t["definition"]["template_name"], ", ".join(t["definition"]["concrete_parameters"]))
                for t in eligible if t["definition"]["template_name"] in case["ground_truth_templates"]),
            "excluded": {t["definition"]["label"].split(" ", 1)[1]: sorted(set(t["exclusion_reasons"]))[:3]
                         for t in prepared["targets"] if not t["eligible"]},
        }
    write_json(report / "prepare-summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "prepared"}, indent=1))
    for strategy, value in summary["prepared"].items():
        print(strategy, value["eligible"], "/", value["total"], "ground truth eligible:", value["eligible_ground_truth"])


def whole_run(case, seed, out_dir):
    """zkFuzz on the case entrypoint with the fixed seed and limit."""
    base, _ = case_paths(case)
    tree = base / "tree"
    return zkfuzz_process(tree / case["entrypoint"], libraries(case, tree), seed,
                          CONFIG["whole_budget_seconds"], out_dir)


def zkfuzz_process(circuit, libs, seed, limit, out_dir):
    """One zkFuzz process with the fixed seed and limit; records generation timing."""
    out_dir.mkdir(parents=True, exist_ok=False)
    settings = out_dir / "mutation-settings.json"
    settings.write_text(json.dumps({"seed": seed}) + "\n")
    arguments = [CONFIG["tools"]["zkfuzz"], str(circuit), "--path_to_mutation_setting", str(settings)]
    for path in libs:
        arguments += ["-l", str(path)]
    events = []
    start = time.time()
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               cwd=out_dir, start_new_session=True)

    def reader():
        buffer = b""
        while True:
            chunk = process.stdout.read1(65536)
            if not chunk:
                break
            buffer += chunk
            parts = re.split(rb"[\r\n]", buffer)
            buffer = parts.pop()
            for part in parts:
                text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", part.decode(errors="replace")).strip()
                if text:
                    events.append((round(time.time() - start, 3), text))

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    status = "finished"
    while process.poll() is None:
        if time.time() - start > limit:
            os.killpg(process.pid, signal.SIGKILL)
            status = "timeout"
            break
        time.sleep(0.5)
    process.wait()
    thread.join(timeout=10)
    (out_dir / "zkfuzz.log").write_text("".join(f"{t:10.3f} {e}\n" for t, e in events))
    generations = [(t, int(m.group(1))) for t, e in events for m in [re.search(r"Generation:\s*(\d+)/", e)] if m]
    verdict = [e for _, e in events if "Verification" in e]
    found = any("NOT SAFE" in e for e in verdict)
    found_at = next((t for t, e in events if "NOT SAFE" in e), None)
    return {"status": status if not found else "bug_found", "elapsed_seconds": round(time.time() - start, 3),
            "found": found, "found_at_seconds": found_at,
            "generations_completed": generations[-1][1] + 1 if generations else 0,
            "first_generation_seconds": generations[0][0] if generations else None,
            "verification": verdict[-1:], "log": rel(ROOT, out_dir / "zkfuzz.log")}


def campaign(case, lane):
    base, report = case_paths(case)
    summary = json.loads((report / "prepare-summary.json").read_text())
    ledger_path = report / f"ledger-{lane}.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
        "schema_version": 1, "case": case["id"], "lane": lane, "executions": []}
    done = {entry["block"] for entry in ledger["executions"]}
    for block in CONFIG["blocks"]:
        number = block["block"]
        if number in done:
            continue
        directory = base / "campaign" / lane / f"block-{number}"
        if lane != "whole" and case["split_runner"] == "direct":
            ledger["executions"].append(direct_split(case, lane, block, directory))
        elif lane == "whole":
            result = whole_run(case, block["zkfuzz_seed"], directory)
            ledger["executions"].append({"block": number, "zkfuzz_seed": block["zkfuzz_seed"], **result})
        else:
            if directory.exists():
                raise SystemExit(f"refusing to reuse {directory}")
            directory.mkdir(parents=True)
            prepared = ROOT / summary["prepared"][lane]["path"]
            plan_path = directory / "plan.json"
            arguments = [BIN, "experiment", "plan", "--prepared", prepared, "--strategy", lane,
                         "--output", plan_path]
            if lane == "random":
                arguments += ["--ranking-seed", block["random_ranking_seed"]]
            run(arguments, cwd=ROOT)
            plan = json.loads(plan_path.read_text())
            run([BIN, "experiment", "run", "--plan", plan_path, "--zkfuzz-bin", CONFIG["tools"]["zkfuzz"],
                 "--budget-seconds", CONFIG["piece_budget_seconds"],
                 "--total-budget-seconds", CONFIG["split_budget_seconds"],
                 "--zkfuzz-seed", block["zkfuzz_seed"], "--output", directory / "execution"], cwd=ROOT)
            outcome_path = next((directory / "execution").glob("execution-*/outcome.json"))
            outcome = json.loads(outcome_path.read_text())
            names = {t["target_id"]: t["definition"]["template_name"] for t in plan["targets"]}
            labels = {t["target_id"]: "{}({})".format(t["definition"]["template_name"],
                                                     ", ".join(t["definition"]["concrete_parameters"]))
                      for t in plan["targets"]}
            order = [t["target_id"] for t in plan["targets"]]
            runs = [r for r in outcome["scheduler"]["runs"] if r["result"]]
            truth = {}
            for scheduled in runs:
                label = labels[scheduled["target_id"]]
                if names[scheduled["target_id"]] in case["ground_truth_templates"]:
                    truth[label] = {"rank": order.index(scheduled["target_id"]) + 1,
                                    "status": scheduled["result"]["status"],
                                    "completed_at_seconds": round(scheduled["completion_offset_seconds"], 3),
                                    "wall_seconds": round(scheduled["result"]["wall_time_seconds"], 3)}
            for target_id in order:
                label = labels[target_id]
                if names[target_id] in case["ground_truth_templates"] and label not in truth:
                    truth[label] = {"rank": order.index(target_id) + 1, "status": "not-started"}
            found_times = [v["completed_at_seconds"] for v in truth.values() if v["status"] == "bug_found"]
            ledger["executions"].append({
                "block": number, "zkfuzz_seed": block["zkfuzz_seed"],
                "random_ranking_seed": block["random_ranking_seed"] if lane == "random" else None,
                "plan": {"path": rel(ROOT, plan_path), "sha256": sha256(plan_path)},
                "outcome": {"path": rel(ROOT, outcome_path), "sha256": sha256(outcome_path)},
                "pieces_planned": len(order),
                "pieces_started": len(runs) + len(outcome["scheduler"]["failures"]),
                "elapsed_seconds": round(outcome["scheduler"]["elapsed_seconds"], 3),
                "ground_truth": truth,
                "found": bool(found_times),
                "found_at_seconds": min(found_times) if found_times else None,
                "candidate_pieces": sorted({labels[c["target_id"]] for c in outcome["counterexample_candidates"]}),
            })
        write_json(ledger_path, ledger)
        last = ledger["executions"][-1]
        print(case["id"], lane, number, "found" if last["found"] else "not found", last.get("found_at_seconds"),
              flush=True)


def direct_split(case, strategy, block, directory):
    """Run the project pieces one at a time with zkFuzz directly, for cases whose pieces the
    zkfDO preparation cannot yet fingerprint. Orders: path-order by wrapper path, small-first by
    compiled constraint count, random by a seeded shuffle of the path-sorted list."""
    base, report = case_paths(case)
    tree = base / "tree"
    manifest = json.loads((report / "manifest.json").read_text())
    pieces = []
    for target in manifest["targets"]:
        wrapper = (report / target["entrypoint"]).resolve()
        label = "{}({})".format(target["template_name"], ", ".join(target["concrete_parameters"]))
        pieces.append({"wrapper": wrapper, "label": label, "template": target["template_name"]})
    pieces.sort(key=lambda piece: str(piece["wrapper"]))
    if strategy == "small-first":
        sizes = json.loads((report / "piece-sizes.json").read_text())
        pieces.sort(key=lambda piece: (sizes[piece["label"]], str(piece["wrapper"])))
    elif strategy == "random":
        random.Random(block["random_ranking_seed"]).shuffle(pieces)
    libs = libraries(case, tree)
    budget = CONFIG["split_budget_seconds"]
    start = time.time()
    runs, truth = [], {}
    for rank, piece in enumerate(pieces, 1):
        remaining = budget - (time.time() - start)
        if remaining <= 0:
            break
        result = zkfuzz_process(piece["wrapper"], libs, block["zkfuzz_seed"],
                                min(CONFIG["piece_budget_seconds"], remaining),
                                directory / f"{rank:02d}-{piece['wrapper'].stem}")
        completed = round(time.time() - start, 3)
        runs.append({"rank": rank, "piece": piece["label"], "status": result["status"],
                     "completed_at_seconds": completed, "generations_completed": result["generations_completed"]})
        if piece["template"] in case["ground_truth_templates"]:
            truth[piece["label"]] = {"rank": rank, "status": result["status"], "completed_at_seconds": completed}
    for rank, piece in enumerate(pieces, 1):
        if piece["template"] in case["ground_truth_templates"] and piece["label"] not in truth:
            truth[piece["label"]] = {"rank": rank, "status": "not-started"}
    found = [v["completed_at_seconds"] for v in truth.values() if v["status"] == "bug_found"]
    return {"block": block["block"], "zkfuzz_seed": block["zkfuzz_seed"],
            "random_ranking_seed": block["random_ranking_seed"] if strategy == "random" else None,
            "runner": "direct", "pieces_planned": len(pieces), "pieces_started": len(runs),
            "elapsed_seconds": round(time.time() - start, 3), "runs": runs, "ground_truth": truth,
            "found": bool(found), "found_at_seconds": min(found) if found else None}


def piece_sizes(case):
    """Compiled constraint counts of the project pieces, for small-first in the direct runner."""
    base, report = case_paths(case)
    tree = base / "tree"
    manifest = json.loads((report / "manifest.json").read_text())
    sizes = {}
    for target in manifest["targets"]:
        wrapper = (report / target["entrypoint"]).resolve()
        out = base / "sizes" / wrapper.stem
        out.mkdir(parents=True, exist_ok=True)
        arguments = [CONFIG["tools"]["circom"], str(wrapper), "--r1cs", "-o", str(out)]
        for path in libraries(case, tree):
            arguments += ["-l", str(path)]
        text = run(arguments)
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
        non_linear = int(re.search(r"non-linear constraints: (\d+)", text).group(1))
        linear = int(re.search(r"(?<!non-)linear constraints: (\d+)", text).group(1))
        sizes["{}({})".format(target["template_name"], ", ".join(target["concrete_parameters"]))] = non_linear + linear
    write_json(report / "piece-sizes.json", sizes)
    print(json.dumps(sizes, indent=1))


def summarize():
    rows = []
    for case in CONFIG["cases"]:
        _, report = case_paths(case)
        for lane in ["whole"] + CONFIG["strategies"]:
            path = report / f"ledger-{lane}.json"
            if not path.exists():
                continue
            for entry in json.loads(path.read_text())["executions"]:
                rows.append({"case": case["id"], "lane": lane, "block": entry["block"],
                             "found": entry["found"], "found_at_seconds": entry.get("found_at_seconds"),
                             "generations_completed": entry.get("generations_completed"),
                             "pieces_started": entry.get("pieces_started"),
                             "pieces_planned": entry.get("pieces_planned"),
                             "ground_truth": entry.get("ground_truth")})
    write_json(HERE / "results.json", {"schema_version": 1, "rows": rows})
    for row in rows:
        print(row["case"], row["lane"], row["block"], row["found"], row["found_at_seconds"],
              row["generations_completed"], row["pieces_started"], row["pieces_planned"])


def main():
    stage, *names = sys.argv[1:]
    if stage == "summarize":
        summarize()
        return
    lanes = [name for name in names if name == "whole" or name in CONFIG["strategies"]]
    case_names = [name for name in names if name not in lanes]
    cases = [c for c in CONFIG["cases"] if not case_names or c["id"] in case_names]
    for case in cases:
        if stage == "prepare":
            prepare(case)
        elif stage == "sizes":
            piece_sizes(case)
        elif stage == "run":
            for lane in lanes or ["whole"] + CONFIG["strategies"]:
                campaign(case, lane)


if __name__ == "__main__":
    main()
