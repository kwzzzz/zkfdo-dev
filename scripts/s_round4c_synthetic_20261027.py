#!/usr/bin/env python3
"""Small forwarding-view check and six-second tagged S smoke test, owned outputs only."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys

import run_policy_a_engine_v4 as s_engine
import s_round4c_monitor_20261027 as monitor
import s_round4c_postdeadline_20261027 as post
import s_round4c_view_replay_20261027 as converter
import s_round4b_postdeadline_20261027 as old
import s_round4_synthetic_20261027 as r1cs
import s_tag_wrapper_prototype_20261027 as prototype
import s_round4c_pipeline_20261027 as pipeline


def pin(path):
    return {"path": str(path), "sha256": post.sha(path)}


def save(path, value):
    return post.write_new(path, value)


def j_run(request, output, label):
    engine = post.ROUND / "round4b/bin/zkfDO-v2.3-development"
    post.require(post.sha(engine) == "05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700", "engine SHA changed")
    args = [str(engine), "--request", str(request), "--output", str(output / "result"),
            "--cache", str(output / "cache"), "--instance-store", str(output / "store")]
    for name in ("circom", "node", "snarkjs", "z3"):
        tool = shutil.which(name)
        post.require(tool is not None, "installed tool missing")
        args += ["--" + name + "-bin", tool]
    run = monitor.run(args, label, 180)
    post.require(run["status"] == "completed", "synthetic J failed")
    return json.loads((output / "result/result.json").read_text())


def forwarding(folder):
    original = post.ROUND / "round4b/synthetic-final/legacy"
    request = json.loads((original / "request.json").read_text())
    row = {"request": pin(original / "request.json"), "candidate": pin(original / "candidate.json"),
           "source_closure": [pin(original / "target-source.circom"), pin(original / "entry.circom")]}
    result = converter.convert(row, folder)
    compiled = folder / "compile"
    compiled.mkdir()
    compiler = shutil.which("circom")
    run = monitor.run([compiler, result["wrapper"]["path"], "--r1cs", "--sym", "--O0",
                       "--output", str(compiled)], "4c-forward-" + folder.parent.name + "-compile", 60)
    post.require(run["status"] == "completed", "forward wrapper compile failed")
    constraints = r1cs.parse_r1cs((compiled / "forward.r1cs").read_bytes())["shape"]["constraints"]
    post.require(constraints <= 1000, "synthetic J constraint bound")
    actual = j_run(Path(result["request"]["path"]), folder / "judge", "4c-forward-" + folder.parent.name + "-J")
    expected = json.loads((original / "j-output/result.json").read_text())
    same = old.verdict(actual) == old.verdict(expected)
    save(folder / "comparison.json", {"same_kind_and_reason": same, "constraints": constraints,
        "baseline": pin(original / "j-output/result.json"), "converted": result,
        "result": pin(folder / "judge/result/result.json")})
    post.require(same, "forwarding replay changed verdict")
    return {"passed": same, "constraints": constraints}


def make_s_spec(folder):
    folder.mkdir(parents=True)
    snapshot = folder / "snapshot"
    snapshot.mkdir()
    source = snapshot / "component.circom"
    source.write_text('pragma circom 2.1.6;\ntemplate Tagged() {\n signal input {binary} x;\n signal output y;\n y <-- x*x + 7;\n}\n')
    wrapper, tags, info = prototype.render_prototype(source, source.read_text(), "Tagged", [], {source: source.read_text()})
    post.require(wrapper is not None, str(info))
    (snapshot / "target.circom").write_text(wrapper)
    (snapshot / "entry.circom").write_text('''pragma circom 2.1.6;
include "component.circom";
template Whole() {
 signal input x;
 signal output y;
 signal output keep;
 signal {binary} bridge;
 component child = Tagged();
 bridge <== x;
 child.x <== bridge;
 y <== child.y;
 keep <== x*x;
}
component main = Whole();
''')
    fingerprints = [pin(source), pin(snapshot / "target.circom"), pin(snapshot / "entry.circom")]
    target_id = "synthetic-tagged"
    plan = save(folder / "plan.json", {"targets": [{"target_id": target_id,
        "source_fingerprints": fingerprints, "snapshot_fingerprints": fingerprints}]})
    compiler, fuzzer = shutil.which("circom"), shutil.which("zkfuzz")
    post.require(compiler and fuzzer, "installed S tools unavailable")
    spec = {"schema_version": 1, "method": "split", "campaign_id": "round4c-synthetic-tagged",
        "project": "synthetic", "recorded_revision": "synthetic", "total_budget_seconds": 6,
        "attempt_cap_seconds": 6, "concurrency": 1, "initial_seed": 2026100601,
        "memory_cap_bytes": 10 * post.GIB, "coverage_checkpoints_seconds": [6],
        "execution_sequence": "whole_then_split", "seed_rule": "increment_per_pass",
        "seed_transport": {"argument": "--path_to_mutation_setting", "base": {}, "kind": "mutation_settings"},
        "preflight_compile_timeout_seconds": 30, "require_pinned_command_tools": True,
        "require_save_output": False, "zkfuzz_output": "stderr_report", "pinned_trees": [],
        "external_include_files": [pin(source)],
        "pinned_files": [{"label": "plan", **plan}, {"label": "circom", **pin(Path(compiler))},
                         {"label": "zkfuzz", **pin(Path(fuzzer))}],
        "source_snapshots": [{"id": "synthetic", "path": str(snapshot),
             "tree_sha256": s_engine.v1.tree_sha256(snapshot), "expected_baseline_candidates": 0,
             "candidate_globs": ["**/zkfdo_report_counterexample.json"]}],
        "targets": [{"target_id": target_id, "rank": 1, "source_snapshot_id": "synthetic",
             "source_snapshot_path": str(snapshot), "entrypoint_relative": "target.circom",
             "entrypoint_sha256": post.sha(snapshot / "target.circom"),
             "command": [fuzzer, "{entrypoint}", "--prime", "bn128", "--search_mode", "ga", "-l", "{workspace}"],
             "preflight_compile_command": [compiler, "{entrypoint}", "--r1cs", "--sym", "--O0", "--output", "{compile_output}", "-l", "{workspace}"]}]}
    with s_engine.installed():
        s_engine.v1.validate_spec(spec)
        s_engine.verify_plan_v4(spec, {"synthetic": snapshot})
    return save(folder / "spec.json", spec), tags


def s_child(spec, preflight, output, preparation):
    # The unchanged v4 runner accepts an explicit output root for both stages.
    import signal
    cancelled = False
    def stop(_signal, _frame):
        nonlocal cancelled
        cancelled = True
    signal.signal(signal.SIGTERM, stop)
    with s_engine.installed():
        if preparation:
            s_engine._ACTIVE_METHOD = "split"
            original = s_engine.v1.spawn_and_measure
            s_engine.v1.spawn_and_measure = lambda command, directory, end, start, cancel: original(
                command, directory, end, start, lambda: cancelled or cancel())
            result = s_engine.v1.preflight(Path(spec), Path(output))
        else:
            value, digest = s_engine.v1.load_spec(Path(spec))
            snapshots, root = s_engine.v1.read_preflight(value, digest, Path(preflight))
            result = s_engine.v1.run_campaign(value, digest, snapshots, root, Path(output), cancel_check=lambda: cancelled)
    post.require(result["ledger"]["status"] in ("passed", "completed"), "synthetic S stage failed")


def finish_s_j(folder):
    base = folder / "S"
    snapshot = base / "snapshot"
    completion = base / "J-connection"
    completion.mkdir()
    entry = snapshot / "entry.circom"
    post.require(entry.is_file(), "entrypoint must exist before the S snapshot is hashed")
    original = save(completion / "original-fragment.json", {"synthetic_only": True, "template": "Tagged", "arguments": []})
    view = save(completion / "view.json", {"schema": "zkfdo-component-view-v1",
        "target_prefix": "main.__s_tag_target", "target_template": "Tagged",
        "target_source": str(snapshot / "component.circom"), "target_source_sha256": post.sha(snapshot / "component.circom"),
        "wrapper_sha256": post.sha(snapshot / "target.circom"), "original_fragment_spec": original["path"],
        "original_fragment_spec_sha256": original["sha256"], "concrete_arguments": [],
        "attached_without_enforcement": [{"input": "x", "tag": "binary", "value": None}]})
    base_input = save(completion / "base-input.json", {"x": "2"})
    template = save(completion / "request-template.json", {"schema": "zkfdo-lifting-request-v2.3",
        "source_root": str(snapshot), "component_wrapper": str(snapshot / "target.circom"),
        "entrypoint": str(entry), "base_input": base_input["path"],
        "component_view": {"spec": view["path"], "sha256": view["sha256"]}})
    contexts = save(completion / "contexts.json", {"targets": [{"revision": "synthetic", "target_id": "synthetic-tagged",
        "request_template": template, "component_wrapper_sha256": post.sha(snapshot / "target.circom"),
        "entrypoint_sha256": post.sha(entry), "input_layer": "synthetic",
        "inputs": [pin(snapshot / "target.circom"), pin(snapshot / "component.circom"), pin(entry), base_input]}]})
    inventory = save(completion / "historical.json", {"complete": True, "rows": []})
    summary = save(completion / "S-summary.json", {"runs": [{"revision": "synthetic", "seed": 2026100601,
        "campaign": str(base / "campaign"), "spec": str(base / "spec.json")}]})
    requests = pipeline.build_new_j({"J_contexts": contexts, "old_candidate_inventory": inventory}, summary, completion / "requests")
    rows = post.read_pin(requests)[1]["requests"]
    post.require(rows, "six-second synthetic S produced no candidate; no injected substitute")
    compiled = completion / "compile"
    compiled.mkdir()
    run = monitor.run([shutil.which("circom"), str(entry), "--r1cs", "--O0", "--output", str(compiled)],
                      "4c-" + folder.name + "-S-J-entry", 60)
    post.require(run["status"] == "completed", "synthetic entrypoint compile failed")
    constraints = r1cs.parse_r1cs((compiled / "entry.r1cs").read_bytes())["shape"]["constraints"]
    post.require(constraints <= 1000, "synthetic entrypoint bound")
    result = j_run(Path(rows[0]["request"]["path"]), completion / "judge", "4c-" + folder.name + "-S-real-candidate-J")
    passed = result.get("preparation", {}).get("status") == "ok" and result.get("sites_found", 0) > 0
    save(completion / "completion.json", {"S_to_new_J_complete": passed, "candidate_selection": "first ledger occurrence",
        "request_count": len(rows), "judged_count": 1, "constraints": constraints, "J_inputs": requests,
        "result": pin(completion / "judge/result/result.json"), "preparation": result.get("preparation")})
    post.require(passed, "actual synthetic S candidate did not enter v2.3 view judging")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("_preflight", "_campaign"):
        s_child(*sys.argv[2:], preparation=sys.argv[1] == "_preflight")
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--output", required=True)
        parser.add_argument("--finish-existing-s", action="store_true")
        args = parser.parse_args()
        folder = post.checked_output(args.output)
        if args.finish_existing_s:
            finish_s_j(folder)
            raise SystemExit(0)
        folder.mkdir(parents=True, exist_ok=False)
        forward = forwarding(folder / "forwarding")
        spec, tags = make_s_spec(folder / "S")
        command = [sys.executable, "-B", str(Path(__file__).resolve())]
        pre = monitor.run(command + ["_preflight", spec["path"], "unused", str(folder / "S/preflight")], "4c-" + folder.name + "-S-preflight", 60)
        post.require(pre["status"] == "completed", "synthetic S preflight failed")
        # Count before permitting even the six-second synthetic fuzzer.
        artifacts = list((folder / "S/preflight/compile").rglob("*.r1cs"))
        post.require(artifacts and all(r1cs.parse_r1cs(p.read_bytes())["shape"]["constraints"] <= 1000 for p in artifacts), "synthetic S constraint bound")
        run = monitor.run(command + ["_campaign", spec["path"], str(folder / "S/preflight/preflight.json"), str(folder / "S/campaign")], "4c-" + folder.name + "-S-six-seconds", 30)
        ledger_path = folder / "S/campaign/ledger.json"
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
        candidates = [c for a in ledger.get("attempts", []) for c in a.get("candidates", [])]
        save(folder / "summary.json", {"forwarding": forward, "S_run": run,
            "S_ledger": pin(ledger_path) if ledger_path.exists() else None, "candidate_count": len(candidates),
            "S_to_new_J_complete": False, "candidate_to_J": "pending actual candidate conversion", "tags": tags})
        finish_s_j(folder)
