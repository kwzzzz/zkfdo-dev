#!/usr/bin/env python3
"""One long W (whole-circuit zkFuzz) run on the A inference original, A development only.

Reuses the recorded 1,236 s W spec (same binary, settings, seed rule), changing only
the budget and campaign id. The absolute cap includes preparation; a candidate is
judged by pinned J (whole entrypoint as the component) inside the same cap.
The frozen v4 engine is driven through its own CLI; nothing in it is modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback

from n7_a_sj_cold_e2e_20261029 import (BASE_INPUT, O0_R1CS, PROJECT, PROJECT_TREE, ROOT, TOOLS,
                                       Run, children_cpu, r1cs_constraints, save, sha)
import run_policy_a_engine_v4 as campaign

TEMPLATE = ROOT / "runs/n5-equal-cost-2026-10-28/w-2026100601-1236-spec.json"
TEMPLATE_SHA = None  # recorded, not enforced: the file is a frozen record
OUT = ROOT / "runs/n7-a-w-long-2026-10-29"
CAP_SECONDS = 4800.0
SEED = 2026100601
MIN_FREE_RUN = 18 * 2**30
SWAP_GROWTH_LIMIT = 4 * 2**30  # thrash guard: swap use growth over the run start


def swap_used_bytes():
    text = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    match = re.search(r"used = ([0-9.]+)M", text)
    return int(float(match.group(1)) * 2**20) if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap", type=float, default=CAP_SECONDS)
    parser.add_argument("--run-name", default=str(SEED), help="new output folder name under the W-long root")
    args = parser.parse_args()
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise SystemExit("run under nice -n 19")
    folder = OUT / args.run_name
    if folder.exists():
        raise SystemExit("output folder exists; refusing to overwrite")
    OUT.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(OUT).free < 30 * 2**30:
        raise SystemExit("internal disk below 30 GiB; not starting")
    for name, (path, digest) in TOOLS.items():
        if sha(path) != digest:
            raise SystemExit("tool pin mismatch: " + name)
    folder.mkdir()
    run = Run(folder, SEED, args.cap)
    run.summary.update({"schema": "n7-a-w-long-v1", "method": "W", "template_spec": str(TEMPLATE),
                        "template_spec_sha256": sha(TEMPLATE), "script_sha256": sha(__file__),
                        "swap_used_start_bytes": swap_used_bytes(), "guard_events": []})
    cancel = folder / "cancel"
    stop_watch = threading.Event()

    def watch():
        # Disk and swap guards plus first-candidate detection, every 5 s.
        start_swap = run.summary["swap_used_start_bytes"] or 0
        while not stop_watch.wait(5):
            free = shutil.disk_usage(folder).free
            swap = swap_used_bytes() or 0
            reason = ("disk_below_18GiB" if free < MIN_FREE_RUN else
                      "swap_growth_thrash" if swap - start_swap > SWAP_GROWTH_LIMIT else None)
            found = list((folder / "campaign").glob("attempts/*/candidates/**/zkfdo_report_counterexample.json"))
            if found and "first_candidate_offset_seconds" not in run.summary:
                run.summary["first_candidate_offset_seconds"] = run.offset()
                reason = reason or "candidate_found_stop_search_for_judging"
            if reason:
                run.summary["guard_events"].append({"reason": reason, "offset_seconds": run.offset(),
                                                    "free_bytes": free, "swap_used_bytes": swap})
                cancel.touch()
                return

    try:
        started, cpu = run.offset(), children_cpu()
        tree = folder / "tree/project"
        shutil.copytree(PROJECT, tree, symlinks=False)
        if campaign.v1.tree_sha256(tree) != PROJECT_TREE:
            raise RuntimeError("source copy differs from the pinned project tree")
        run.record("source_copy", started, cpu)
        o0 = folder / "original-o0"
        o0.mkdir()
        tools = {k: str(v[0]) for k, v in TOOLS.items()}
        entry = tree / "src/circuit.circom"
        if run.run("original_compile", [tools["circom"], entry, "--O0", "--r1cs", "--sym", "--wasm",
                                        "--output", o0, "-l", tree, "-l", tree / "src"])[1] != 0:
            raise RuntimeError("original compile failed")
        run.summary["original_o0"] = {"r1cs_sha256": sha(o0 / "circuit.r1cs"),
                                      "constraints": r1cs_constraints(o0 / "circuit.r1cs")}
        if run.summary["original_o0"]["r1cs_sha256"] != O0_R1CS:
            raise RuntimeError("original O0 R1CS differs from the recorded original")
        js = o0 / "circuit_js"
        if run.run("base_witness", [shutil.which("node"), js / "generate_witness.js", js / "circuit.wasm",
                                    BASE_INPUT, o0 / "base.wtns"])[1] != 0:
            raise RuntimeError("base witness failed")
        logs, code = run.run("base_original_check", [shutil.which("snarkjs"), "wtns", "check",
                                                     o0 / "circuit.r1cs", o0 / "base.wtns"])
        if code != 0 or "WITNESS IS CORRECT" not in (logs / "stdout.log").read_text():
            raise RuntimeError("base witness not confirmed by snarkjs")
        spec = json.loads(TEMPLATE.read_text())
        total = int(run.remaining())
        spec.update({"campaign_id": f"n7-a-w-long-{SEED}-{int(args.cap)}", "total_budget_seconds": total,
                     "attempt_cap_seconds": total,
                     "coverage_checkpoints_seconds": sorted({600, 1236, total})})
        spec_path = folder / "spec.json"
        save(spec_path, spec)
        engine = [sys.executable, "-B", ROOT / "scripts/run_policy_a_engine_v4.py"]
        if run.run("preflight", engine + ["preflight", "--spec", spec_path, "--output", folder / "preflight"])[1] != 0:
            raise RuntimeError("engine preflight failed")
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        _, code = run.run("whole_campaign", engine + ["run", "--spec", spec_path, "--preflight", folder / "preflight/preflight.json",
                                                      "--output", folder / "campaign", "--cancel-file", cancel])
        stop_watch.set()
        ledger = json.loads((folder / "campaign/ledger.json").read_text())
        attempts = ledger["attempts"]
        run.summary["campaign"] = {
            "returncode": code, "termination_reason": ledger.get("termination_reason"),
            "attempts": len(attempts), "ledger_sha256": sha(folder / "campaign/ledger.json"),
            "last_generation": [a.get("last_generation") for a in attempts],
            "peak_physical_memory_bytes": ledger.get("aggregate_process_tree_peak_physical_memory_bytes"),
            "fuzz_cpu_seconds_sum": ledger.get("actual_cpu_seconds_sum"),
            "candidates": [c for a in attempts for c in a.get("candidates", [])]}
        thrash = [e for e in run.summary["guard_events"] if e["reason"] != "candidate_found_stop_search_for_judging"]
        if thrash:
            run.summary["status"] = "invalid_guard_stop"
            return
        candidates = run.summary["campaign"]["candidates"]
        for index, cand in enumerate(candidates):
            if cand.get("duplicate_of"):
                continue
            judged = folder / "judgements" / str(index)
            judged.mkdir(parents=True)
            shutil.copyfile(folder / "campaign" / cand["path"], judged / "candidate.json")
            request = {"schema": "zkfdo-lifting-request-v1", "id": f"n7-a-w-long-{index}",
                       "source_root": str(folder / "tree"), "library_paths": [str(tree), str(tree / "src")],
                       "component_wrapper": str(entry), "entrypoint": str(entry), "base_input": str(BASE_INPUT),
                       "candidate": {"format": "zkfuzz", "path": str(judged / "candidate.json")}}
            save(judged / "request.json", request)
            argv = [tools["J"], "--request", judged / "request.json", "--output", judged / "out",
                    "--cache", folder / "j-cache", "--instance-store", folder / "instance-store"]
            for name in ("circom", "node", "snarkjs", "z3"):
                argv += [f"--{name}-bin", tools.get(name) or shutil.which(name)]
            _, code = run.run(f"judge-{index}", argv)
            row = {"candidate_sha256": cand["sha256"], "returncode": code, "recorded_offset_seconds": run.offset()}
            path = judged / "out/result.json"
            if code == 0 and path.exists():
                result = json.loads(path.read_text())
                classes = [{k: c.get(k) for k in ("pattern", "verdict", "reason", "rust_unsatisfied", "snarkjs")}
                           for c in result.get("classes", [])]
                row.update(preparation_status=(result.get("preparation") or {}).get("status"), classes=classes,
                           verified_l1=sum(c["verdict"] == "entrypoint_violation" and c["rust_unsatisfied"] == 0
                                           and c["snarkjs"] == "correct" for c in classes))
            else:
                row.update(verified_l1=None, status="unjudged_at_deadline" if code == "timeout" else "j_failed")
            run.summary["judgements"].append(row)
            if row.get("verified_l1"):
                run.summary["first_verified"] = row
                break
        run.summary["status"] = ("verified_cause_within_cap" if run.summary["first_verified"] else
                                 "candidate_without_verified_cause" if candidates else "no_candidate_within_cap")
        run.summary["children_cpu_seconds"] = children_cpu() - run.cpu0
    except BaseException as error:
        run.summary["status"] = "operational_failure"
        run.summary["error"] = f"{type(error).__name__}: {error}"
        run.summary["traceback"] = traceback.format_exc()
        raise
    finally:
        stop_watch.set()
        run.summary["swap_used_end_bytes"] = swap_used_bytes()
        run.summary["disk_free_end_bytes"] = shutil.disk_usage(folder).free
        run.summary["finished_offset_seconds"] = run.offset()
        save(folder / "result.json", run.summary)


if __name__ == "__main__":
    sys.exit(main())
