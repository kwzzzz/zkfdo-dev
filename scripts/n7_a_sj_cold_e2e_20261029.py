#!/usr/bin/env python3
"""Cold end-to-end S+J run on the A inference original, one seed, A development only.

Copy source -> automatic split preparation -> v4 fuzzing (30 s per fragment) ->
each new candidate judged by pinned J right after it is collected -> original O0
check -> stop at the first verified entrypoint violation or at the absolute cap.
Existing runners, the engine and J are imported unchanged; only the candidate
inventory hook is wrapped at run time so J time comes out of the same deadline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import sys
import time
import traceback

from measure_f01_discovery import manifest_for
from n7_allcost_pilot_20261028 import TOOLS
import run_policy_a_engine_v4 as campaign

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/n7-a-sj-cold-2026-10-29-v2"
UNITS = ROOT / "runs/n6-a1b-2026-10-08/units"
PROJECT = UNITS / "inference-original/project"
PROJECT_TREE = "9c174729263711c93b320e90139b3f98983606c86de822c936e594b39d6700d9"
FIXED_PROJECT = UNITS / "inference-r-intdiv/project"
BASE_INPUT = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-original/selected-input.json"
O0_R1CS = "7efa0199e5da19cbdb1ca503ff35fbaaed69d8757d79a96fe159096ac44880c5"
SEEDS = (2026100601, 2026100602, 2026100603)
CAP_SECONDS = 1600.0
ATTEMPT_SECONDS = 30.0
MIN_FREE_START = 30 * 2**30
MIN_FREE_RUN = 18 * 2**30
GLOB = "**/zkfdo_report_counterexample.json"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def r1cs_constraints(path):
    """Read only the R1CS header section (type 1): m = number of constraints."""
    with Path(path).open("rb") as f:
        if f.read(4) != b"r1cs":
            raise ValueError("not an r1cs file")
        _version, sections = struct.unpack("<II", f.read(8))
        for _ in range(sections):
            kind, size = struct.unpack("<IQ", f.read(12))
            if kind != 1:
                f.seek(size, 1)
                continue
            n8 = struct.unpack("<I", f.read(4))[0]
            f.seek(n8, 1)
            n_wires, n_out, n_pub, n_prv, n_labels, m = struct.unpack("<IIIIQI", f.read(28))
            return m
    raise ValueError("r1cs header section missing")


def children_cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def order_key(row):
    # Deterministic tie-break fixed before running: size, then template name,
    # then concrete parameters, then target id.
    d = row["definition"]
    return (row["ranking"].get("size") or 0, d["template_name"],
            [str(p) for p in d.get("concrete_parameters") or []], row["target_id"])


class Run:
    def __init__(self, folder, seed, cap):
        self.folder, self.seed, self.cap = folder, seed, cap
        self.t0 = time.monotonic()
        self.cpu0 = children_cpu()
        self.deadline = self.t0 + cap
        # Sources J may copy live here; outputs (campaign, judgements) stay outside
        # so J never copies its own earlier outputs.
        self.tree = folder / "tree"
        self.stop = False
        self.seen = {}
        self.summary = {"schema": "n7-a-sj-cold-e2e-v2", "seed": seed, "cap_seconds": cap,
                        "attempt_cap_seconds": ATTEMPT_SECONDS, "status": "running",
                        "stages": [], "candidates": [], "judgements": [],
                        "first_verified": None, "unique_cause_replay": None,
                        "development_only": True}

    def offset(self):
        return time.monotonic() - self.t0

    def remaining(self):
        return self.deadline - time.monotonic()

    def guard(self):
        if self.remaining() <= 0:
            raise TimeoutError("absolute cap reached")
        if shutil.disk_usage(self.folder).free < MIN_FREE_RUN:
            raise RuntimeError("internal disk below 18 GiB")

    def record(self, name, started, cpu_started, **extra):
        row = {"stage": name, "start_offset_seconds": started, "wall_seconds": self.offset() - started,
               "children_cpu_seconds": children_cpu() - cpu_started, **extra}
        self.summary["stages"].append(row)
        save(self.folder / "result.json", self.summary)
        return row

    def run(self, name, argv, timeout=None):
        self.guard()
        logs = self.folder / "commands" / name
        logs.mkdir(parents=True)
        started, cpu = self.offset(), children_cpu()
        limit = self.remaining() if timeout is None else min(timeout, self.remaining())
        with (logs / "stdout.log").open("x") as out, (logs / "stderr.log").open("x") as err:
            try:
                proc = subprocess.run(list(map(str, argv)), stdout=out, stderr=err,
                                      timeout=max(limit, 0.001), check=False)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                code = "timeout"
        self.record(name, started, cpu, returncode=code)
        return logs, code


def prepare(run, project):
    tools = {k: str(v[0]) for k, v in TOOLS.items()}
    o0 = run.folder / "original-o0"
    o0.mkdir()
    entry = project / "src/circuit.circom"
    _, code = run.run("original_compile", [tools["circom"], entry, "--O0", "--r1cs", "--sym", "--wasm",
                                           "--output", o0, "-l", project, "-l", project / "src"])
    if code != 0:
        raise RuntimeError("original compile failed")
    r1cs = o0 / "circuit.r1cs"
    run.summary["original_o0"] = {"r1cs_sha256": sha(r1cs), "constraints": r1cs_constraints(r1cs)}
    if run.summary["original_o0"]["r1cs_sha256"] != O0_R1CS:
        raise RuntimeError("original O0 R1CS differs from the recorded original")
    js = o0 / "circuit_js"
    _, code = run.run("base_witness", [shutil.which("node"), js / "generate_witness.js", js / "circuit.wasm",
                                       BASE_INPUT, o0 / "base.wtns"])
    if code != 0:
        raise RuntimeError("base witness failed")
    logs, code = run.run("base_original_check", [shutil.which("snarkjs"), "wtns", "check", r1cs, o0 / "base.wtns"])
    if code != 0 or "WITNESS IS CORRECT" not in (logs / "stdout.log").read_text():
        raise RuntimeError("base witness not confirmed by snarkjs")
    libraries = [project, project / "src"]
    discovery = run.tree / "input/discovery"
    argv = [tools["prepare"], "targets", "--project", project, "--entrypoint", entry, "--output", discovery,
            "--circom-bin", tools["circom"], "--compile-timeout-seconds", "60",
            "--instance-capture", "--capture-timeout-seconds", "60"]
    for library in libraries:
        argv += ["--library-path", library]
    if run.run("discovery", argv)[1] != 0:
        raise RuntimeError("discovery failed")
    started, cpu = run.offset(), children_cpu()
    report_path = one(discovery, "discovery.json")
    report = json.loads(report_path.read_text())
    instance = report.get("instance_discovery") or {}
    raw = instance.get("capture_path") or (instance.get("capture") or {}).get("path")
    capture = Path(raw) if raw else None
    if capture is not None and not capture.is_absolute():
        capture = ROOT / capture
    manifest = manifest_for("inference-original", "A-development", project, entry, report, libraries, capture)
    save(run.folder / "manifest.json", manifest)
    run.record("manifest", started, cpu)
    if run.run("preparation", [tools["prepare"], "experiment", "prepare", "--manifest", run.folder / "manifest.json",
                               "--output", run.tree / "prepared", "--strategy", "small-first",
                               "--circom-bin", tools["circom"], "--tool-timeout-seconds", "60"])[1] != 0:
        raise RuntimeError("preparation failed")
    plan_path = run.folder / "split-plan.json"
    if run.run("ranking_plan", [tools["prepare"], "experiment", "plan", "--prepared", one(run.tree / "prepared", "prepared.json"),
                                "--strategy", "small-first", "--config", ROOT / "configs/static-ranking.json",
                                "--output", plan_path])[1] != 0:
        raise RuntimeError("ranking plan failed")
    return tools, o0, plan_path


def one(folder, name):
    paths = list(Path(folder).rglob(name))
    if len(paths) != 1:
        raise ValueError(f"expected one {name}, found {len(paths)}")
    return paths[0]


def build_spec(run, tools, plan_path):
    planned = sorted(json.loads(plan_path.read_text())["targets"], key=order_key)
    snapshots, targets, bindings = [], [], []
    for index, row in enumerate(planned):
        entry = Path(row["run_entrypoint"])
        snapshot = next(p for p in entry.parents if p.name == "sources")
        ident = f"target-{index:04d}"
        snapshots.append({"id": ident, "path": str(snapshot), "tree_sha256": campaign.v1.tree_sha256(snapshot),
                          "expected_baseline_candidates": 0, "candidate_globs": [GLOB]})
        targets.append({"target_id": row["target_id"], "rank": index + 1, "source_snapshot_id": ident,
                        "source_snapshot_path": str(snapshot), "entrypoint_relative": str(entry.relative_to(snapshot)),
                        "entrypoint_sha256": sha(entry),
                        "command": [tools["zkfuzz"], "{entrypoint}", "--prime", "bn128", "--search_mode", "ga", "-l", "{workspace}"],
                        "preflight_compile_command": [tools["circom"], "{entrypoint}", "--r1cs", "--sym", "--O0",
                                                      "--output", "{compile_output}", "-l", "{workspace}"]})
        bindings.append({"target_id": row["target_id"], "wrapper": str(entry), "sources": str(snapshot),
                         "template": row["definition"]["template_name"],
                         "parameters": row["definition"].get("concrete_parameters")})
    total = run.remaining()
    spec = {"schema_version": 1, "method": "split", "campaign_id": f"n7-a-sj-cold-{run.seed}",
            "total_budget_seconds": total, "attempt_cap_seconds": ATTEMPT_SECONDS, "concurrency": 1,
            "initial_seed": run.seed, "memory_cap_bytes": 10 * 2**30, "coverage_checkpoints_seconds": [total],
            "seed_rule": "increment_per_pass",
            "seed_transport": {"kind": "mutation_settings", "argument": "--path_to_mutation_setting", "base": {}},
            "preflight_compile_timeout_seconds": 60, "require_pinned_command_tools": True,
            "require_save_output": False, "zkfuzz_output": "stderr_report", "pinned_trees": [],
            "pinned_files": [{"label": n, "path": tools[n], "sha256": TOOLS[n][1]} for n in ("circom", "zkfuzz")],
            "source_snapshots": snapshots, "targets": targets}
    run.summary["split_plan_sha256"] = sha(plan_path)
    run.summary["fragment_order"] = [{"target_id": b["target_id"], "template": b["template"],
                                      "parameters": b["parameters"]} for b in bindings]
    return spec, bindings


def judge(run, tools, o0, project, bindings, target_index, candidate, digest, fixed=False):
    index = len(run.summary["judgements"]) if not fixed else f"replay-{len(list((run.folder / 'replay').glob('replay-*'))) if (run.folder / 'replay').exists() else 0}"
    folder = run.folder / ("judgements" if not fixed else "replay") / str(index)
    folder.mkdir(parents=True)
    copy = folder / "candidate.json"
    shutil.copyfile(candidate, copy)
    unit, root, binding = project, run.tree, dict(bindings[target_index])
    if fixed:
        # Separate root: only the fixed revision and the fragment's own sources, so
        # the original and fixed entrypoints never coexist under one source root.
        root = run.folder / f"replay-tree-{index}"
        unit = root / "project"
        if not root.exists():
            # The fixed unit also holds old preparation wrappers (zkfdo-targets) that the
            # original project lacks; copy only the project sources.
            shutil.copytree(FIXED_PROJECT, unit, symlinks=False,
                            ignore=shutil.ignore_patterns("zkfdo-targets", ".git"))
            shutil.copytree(binding["sources"], root / "sources", symlinks=False)
        relative = Path(binding["wrapper"]).relative_to(binding["sources"])
        binding.update(sources=str(root / "sources"), wrapper=str(root / "sources" / relative))
        # Prepared wrappers include the original project by absolute path; point the
        # copied wrapper at the fixed project so only fixed sources are compiled.
        wrapper = Path(binding["wrapper"])
        wrapper.write_text(wrapper.read_text().replace(str(run.tree / "input/project"), str(unit)))
    request = {"schema": "zkfdo-lifting-request-v1", "id": f"n7-a-cold-{run.seed}-{index}",
               # J requires every source (wrapper and entrypoint) under one root.
               "source_root": str(root),
               "library_paths": [binding["sources"], str(unit), str(unit / "src")],
               "component_wrapper": binding["wrapper"], "entrypoint": str(unit / "src/circuit.circom"),
               "base_input": str(BASE_INPUT), "candidate": {"format": "zkfuzz", "path": str(copy)}}
    save(folder / "request.json", request)
    argv = [tools["J"], "--request", folder / "request.json", "--output", folder / "out",
            "--cache", run.folder / ("j-cache" if not fixed else f"j-cache-{index}"),
            "--instance-store", run.folder / ("instance-store" if not fixed else f"instance-store-{index}")]
    for name in ("circom", "node", "snarkjs", "z3"):
        argv += [f"--{name}-bin", tools.get(name) or shutil.which(name)]
    name = f"judge-{index}" if not fixed else f"judge-{index}-fixed"
    timeout = None if not fixed else 1800
    if fixed:
        run.deadline = time.monotonic() + timeout  # replay is outside the S+J cap
    _, code = run.run(name, argv, timeout=timeout)
    row = {"candidate_sha256": digest, "target_index": target_index, "template": binding["template"],
           "parameters": binding["parameters"], "returncode": code, "fixed_revision": fixed}
    path = folder / "out/result.json"
    if code == 0 and path.exists():
        result = json.loads(path.read_text())
        prep = result.get("preparation") or {}
        entry = result.get("entrypoint") or {}
        classes = [{k: c.get(k) for k in ("pattern", "verdict", "reason", "rust_unsatisfied", "snarkjs")}
                   for c in result.get("classes", [])]
        row.update({"preparation_status": prep.get("status"), "classes": classes,
                    "result_sha256": sha(path), "o0_r1cs_sha256": entry.get("o0_r1cs_sha256")})
        if not fixed and prep.get("status") == "ok" and entry.get("o0_r1cs_sha256") != sha(o0 / "circuit.r1cs"):
            row["error"] = "J original O0 R1CS differs from the compiled original"
        row["verified_l1"] = sum(c["verdict"] == "entrypoint_violation" and c["rust_unsatisfied"] == 0
                                 and c["snarkjs"] == "correct" for c in classes) if "error" not in row else 0
    else:
        row["verified_l1"] = None
        row["status"] = "unjudged_at_deadline" if code == "timeout" else "j_failed"
    row["recorded_offset_seconds"] = run.offset()
    return row


def campaign_phase(run, tools, o0, project, spec, bindings):
    original_inventory = campaign.v1.candidate_inventory

    def inventory(root, patterns):
        found = original_inventory(root, patterns)
        try:
            target_index = int(Path(root).parent.name) % len(bindings)
            for relative, digest in sorted(found.items()):
                if digest in run.seen or run.stop:
                    continue
                run.seen[digest] = relative
                run.summary["candidates"].append({"sha256": digest, "target_index": target_index,
                                                  "collected_offset_seconds": run.offset()})
                row = judge(run, tools, o0, project, bindings, target_index, Path(root) / relative, digest)
                run.summary["judgements"].append(row)
                save(run.folder / "result.json", run.summary)
                if row.get("verified_l1") and row["recorded_offset_seconds"] <= run.cap:
                    run.summary["first_verified"] = row
                    run.stop = True
        except Exception as error:  # never let the hook break the frozen engine
            run.summary.setdefault("hook_errors", []).append(f"{type(error).__name__}: {error}")
            save(run.folder / "result.json", run.summary)
        return found

    spec_path = run.folder / "campaign-spec.json"
    save(spec_path, spec)
    with campaign.installed():
        campaign._ACTIVE_METHOD = "split"
        started, cpu = run.offset(), children_cpu()
        campaign.v1.preflight(spec_path, run.folder / "preflight")
        run.record("preflight_compile_and_copy", started, cpu)
        spec_sha = sha(spec_path)
        snaps, pf_root = campaign.v1.read_preflight(spec, spec_sha, run.folder / "preflight/preflight.json")
        campaign.v1.candidate_inventory = inventory
        started, cpu = run.offset(), children_cpu()
        try:
            result = campaign.v1.run_campaign(spec, spec_sha, snaps, pf_root, run.folder / "campaign",
                                              cancel_check=lambda: run.stop or run.remaining() <= 0)
        finally:
            campaign.v1.candidate_inventory = original_inventory
        ledger = result["ledger"]
        run.record("fuzz_and_inline_j", started, cpu, termination=ledger.get("termination_reason"),
                   attempts=len(ledger["attempts"]), ledger_sha256=sha(result["ledger_path"]),
                   fuzz_cpu_seconds_sum=ledger.get("actual_cpu_seconds_sum"))


def attribute(run, tools, o0, project, bindings, first, candidate):
    replay = judge(run, tools, o0, project, bindings, first["target_index"], candidate,
                   first["candidate_sha256"], fixed=True)
    replay["attributed_to_intdiv"] = (replay.get("verified_l1") == 0
                                      and replay.get("preparation_status") == "ok")
    run.summary.setdefault("replays", []).append(replay)
    run.summary["unique_cause_replay"] = replay
    return replay


def replay_only(folder, seed):
    """Attribution is outside the timed S+J budget, so it may be rerun alone."""
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise SystemExit("run under nice -n 19")
    run = Run(folder, seed, CAP_SECONDS)
    run.summary = json.loads((folder / "result.json").read_text())
    first = run.summary.get("first_verified")
    if not first:
        raise SystemExit("no verified cause to attribute")
    spec = json.loads((folder / "campaign-spec.json").read_text())
    bindings = [{"target_id": t["target_id"], "sources": t["source_snapshot_path"],
                 "wrapper": str(Path(t["source_snapshot_path"]) / t["entrypoint_relative"]),
                 "template": o["template"], "parameters": o["parameters"]}
                for t, o in zip(spec["targets"], run.summary["fragment_order"], strict=True)]
    tools = {k: str(v[0]) for k, v in TOOLS.items()}
    index = run.summary["judgements"].index(first)
    attribute(run, tools, folder / "original-o0", run.tree / "input/project", bindings, first,
              folder / "judgements" / str(index) / "candidate.json")
    save(folder / "result.json", run.summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True, choices=SEEDS)
    parser.add_argument("--cap", type=float, default=CAP_SECONDS)
    parser.add_argument("--output-root", type=Path, default=OUT)
    parser.add_argument("--no-replay", action="store_true")
    parser.add_argument("--replay-only", action="store_true",
                        help="rerun only the fixed-revision attribution for an existing seed folder")
    args = parser.parse_args()
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise SystemExit("run under nice -n 19")
    args.output_root = args.output_root.resolve()
    folder = args.output_root / str(args.seed)
    if args.replay_only:
        return replay_only(folder, args.seed)
    if folder.exists():
        raise SystemExit("output folder exists; refusing to overwrite")
    args.output_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(args.output_root).free < MIN_FREE_START:
        raise SystemExit("internal disk below 30 GiB; not starting")
    for name, (path, digest) in TOOLS.items():
        if sha(path) != digest:
            raise SystemExit("tool pin mismatch: " + name)
    folder.mkdir()
    run = Run(folder, args.seed, args.cap)  # clock starts right before the source copy
    run.summary["pins"] = {"base_input_sha256": sha(BASE_INPUT), "script_sha256": sha(__file__),
                           "tools": {k: v[1] for k, v in TOOLS.items()}}
    try:
        started, cpu = run.offset(), children_cpu()
        project = run.tree / "input/project"
        shutil.copytree(PROJECT, project, symlinks=False)
        if campaign.v1.tree_sha256(project) != PROJECT_TREE:
            raise RuntimeError("source copy differs from the pinned project tree")
        run.record("source_copy", started, cpu)
        tools, o0, plan_path = prepare(run, project)
        spec, bindings = build_spec(run, tools, plan_path)
        campaign_phase(run, tools, o0, project, spec, bindings)
        first = run.summary["first_verified"]
        run.summary["status"] = "verified_cause_within_cap" if first else "no_verified_cause_within_cap"
        run.summary["sj_total_seconds"] = run.offset() if not first else first["recorded_offset_seconds"]
        run.summary["sj_children_cpu_seconds"] = children_cpu() - run.cpu0
        if first and not args.no_replay:
            # Unique-cause attribution, outside the timed budget: replay the same
            # candidate against the one-line IntDiv-fixed revision.
            attribute(run, tools, o0, project, bindings, first,
                      folder / "judgements" / str(run.summary["judgements"].index(first)) / "candidate.json")
    except BaseException as error:
        run.summary["status"] = "operational_failure"
        run.summary["error"] = f"{type(error).__name__}: {error}"
        run.summary["traceback"] = traceback.format_exc()
        raise
    finally:
        run.summary["finished_offset_seconds"] = run.offset()
        save(folder / "result.json", run.summary)


if __name__ == "__main__":
    sys.exit(main())
