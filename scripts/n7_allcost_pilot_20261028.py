#!/usr/bin/env python3
"""Synthetic operations pilot for inclusive W/S+J time accounting, not efficacy.

Reuse automatic discovery/preparation, the v4 campaign engine and pinned J.
No feedback, historical verdict reuse, B inputs, or original protocol changes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from measure_f01_discovery import manifest_for
from n7_allcost_supervisor_20261028 import run_bounded
import run_policy_a_engine_v4 as campaign
from s_round4_synthetic_20261027 import parse_r1cs

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/n7-allcost-2026-10-28"
FIXTURES = ("entrypoint_violation", "compatible_no_top_violation_observed")
TOOLS = {
    "prepare": (ROOT / "runs/f01-2026-10-03/supplement-var-scope/tools/zkfDO",
                "f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1"),
    "J": (ROOT / "runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development",
          "05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700"),
    "circom": (Path.home() / ".cargo/bin/circom",
               "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"),
    "zkfuzz": (Path.home() / ".cargo/bin/zkfuzz",
               "ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd"),
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pin(path):
    path = Path(path).absolute()
    return {"path": str(path), "sha256": sha(path)}


def owned(path):
    path = Path(path).absolute()
    if path == OUT or not path.resolve().is_relative_to(OUT.resolve()):
        raise ValueError("output outside N7 all-cost directory")
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink output forbidden")
    return path


def save(path, data, *, new=False):
    path = owned(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if new:
        with path.open("x") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)


def validate_pins(plan):
    for ref in plan["pins"]:
        if sha(ref["path"]) != ref["sha256"]:
            raise ValueError("pin changed: " + ref["path"])


def make_plan(path, seconds):
    if not 20 <= seconds <= 120:
        raise ValueError("operations pilot cap must be 20..120 seconds per arm")
    tools = {}
    for name, (tool, expected) in TOOLS.items():
        if sha(tool) != expected:
            raise ValueError("installed tool differs: " + name)
        tools[name] = pin(tool)
    for name in ("node", "snarkjs", "z3"):
        tool = shutil.which(name)
        if tool is None:
            raise ValueError("missing installed tool: " + name)
        tools[name] = pin(tool)
    files = [Path(__file__), ROOT / "scripts/n7_allcost_supervisor_20261028.py",
             ROOT / "configs/static-ranking.json",
             ROOT / "docs/n7_allcost_pilot_protocol_v3_2026-10-28.md"]
    # Pin actual locally imported repository modules, without walking runs/.
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if name and Path(name).resolve().is_relative_to(ROOT / "scripts"):
            files.append(Path(name))
    for fixture in FIXTURES:
        base = ROOT / "tests/fixtures/lifting" / fixture
        files.extend(base / name for name in ("src/component.circom", "src/entrypoint.circom",
                                              "src/standalone.circom", "base_input.json"))
    jobs = []
    for fixture in FIXTURES:
        for i, seed in enumerate((2026102801, 2026102802, 2026102803)):
            for method in (("W", "S") if i % 2 == 0 else ("S", "W")):
                jobs.append({"fixture": fixture, "seed": seed, "method": method})
    plan = {"schema": "n7-inclusive-operations-pilot-v2", "created_at": datetime.now(timezone.utc).isoformat(),
            "scope": "synthetic operations only; not an efficacy comparison or an N5 amendment",
            "total_seconds_per_arm": seconds, "search_cutoff_fraction": 0.5,
            "split_attempt_seconds": 3, "max_attempts_per_arm": 2,
            "constraints_max": 1000, "jobs": jobs,
            "tools": tools, "pins": [pin(p) for p in sorted(set(files))] + list(tools.values()),
            "source_transform": "new copies only: pragma circom 2.2.3 -> 2.2.1",
            "candidate_order": "persisted attempt completion, target index, candidate SHA",
            "cache": "new method/fixture/seed application caches; OS cache uncontrolled",
            "cost_boundary": "installed tools and explicit source+base input supplied; source copy through original validation and result persistence included",
            "human_review_person_seconds": None,
            "idle_search_budget_reallocation": False,
            "efficacy_claim_allowed": False}
    save(path, plan, new=True)
    return pin(path)


class Arm:
    def __init__(self, folder, plan, job):
        self.folder, self.plan, self.job = folder, plan, job
        self.t0 = float(os.environ["N7_ARM_T0_MONOTONIC"])
        self.deadline = float(os.environ["N7_ARM_DEADLINE_MONOTONIC"])
        self.cutoff = self.t0 + (self.deadline - self.t0) * plan["search_cutoff_fraction"]
        self.events = folder / "events.jsonl"
        self.summary = {"job": job, "stages": [], "candidates": [], "judgements": [],
                        "status": "running", "original_constraints": None,
                        "human_review_person_seconds": None, "confirmed_unique_causes": None}

    def offset(self):
        return time.monotonic() - self.t0

    def check(self):
        if time.monotonic() >= self.deadline:
            raise TimeoutError("inclusive deadline reached")
        if shutil.disk_usage(self.folder).free < 20 * 2**30:
            raise RuntimeError("internal disk below 20 GiB: no new stage")

    def event(self, value):
        value = {**value, "observed_offset_seconds": self.offset()}
        with self.events.open("a") as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return self.offset()

    @contextmanager
    def stage(self, name):
        self.check()
        started = self.offset()
        self.event({"event": "stage_started", "stage": name})
        try:
            yield
        finally:
            row = {"stage": name, "start_offset_seconds": started,
                   "finish_offset_seconds": self.offset()}
            row["wall_seconds"] = row["finish_offset_seconds"] - started
            self.summary["stages"].append(row)
            self.event({"event": "stage_finished", **row})
            save(self.folder / "result.json", self.summary)

    def command(self, name, argv):
        with self.stage(name):
            logs = self.folder / "commands" / name
            logs.mkdir(parents=True, exist_ok=False)
            save(logs / "argv.json", list(map(str, argv)), new=True)
            with (logs / "stdout.log").open("x") as out, (logs / "stderr.log").open("x") as err:
                proc = subprocess.run(list(map(str, argv)), stdout=out, stderr=err, check=False)
            if proc.returncode:
                raise RuntimeError(f"{name}: exit {proc.returncode}")
            return logs

    def tool(self, name):
        return self.plan["tools"][name]["path"]


def one_report(folder, filename):
    # Only freshly owned output is traversed.
    folder = owned(folder)
    paths = list(folder.rglob(filename))
    if len(paths) != 1:
        raise ValueError(f"expected one {filename}, found {len(paths)}")
    return paths[0]


def spec_for_arm(arm, source, plan_path):
    split = arm.job["method"] == "S"
    if split:
        planned = json.loads(plan_path.read_text())["targets"]
    else:
        planned = [{"target_id": "whole", "rank": 1,
                    "run_entrypoint": str(source / "entrypoint.circom")}]
    snapshots, targets, bindings = [], [], []
    for index, row in enumerate(planned):
        entry = Path(row["run_entrypoint"])
        snapshot = next(p for p in entry.parents if p.name == "sources") if split else source
        ident = f"target-{index:04d}"
        snapshots.append({"id": ident, "path": str(snapshot), "tree_sha256": campaign.v1.tree_sha256(snapshot),
                          "expected_baseline_candidates": 0, "candidate_globs": ["**/zkfdo_report_counterexample.json"]})
        targets.append({"target_id": row["target_id"], "rank": index + 1, "source_snapshot_id": ident,
                        "source_snapshot_path": str(snapshot), "entrypoint_relative": str(entry.relative_to(snapshot)),
                        "entrypoint_sha256": sha(entry),
                        "command": [arm.tool("zkfuzz"), "{entrypoint}", "--prime", "bn128", "--search_mode", "ga", "-l", "{workspace}"],
                        "preflight_compile_command": [arm.tool("circom"), "{entrypoint}", "--r1cs", "--sym", "--O0", "--output", "{compile_output}", "-l", "{workspace}"]})
        bindings.append({"wrapper": row["definition"]["entrypoint"] if split else str(entry),
                         "target_id": row["target_id"]})
    total = arm.plan["total_seconds_per_arm"] * arm.plan["search_cutoff_fraction"]
    spec = {"schema_version": 1, "method": "split" if split else "whole",
            "campaign_id": arm.folder.name, "total_budget_seconds": total,
            "attempt_cap_seconds": min(arm.plan["split_attempt_seconds"], total) if split else total,
            "concurrency": 1, "initial_seed": arm.job["seed"], "memory_cap_bytes": 10 * 2**30,
            "coverage_checkpoints_seconds": [total], "seed_rule": "increment_per_pass",
            "seed_transport": {"kind": "mutation_settings", "argument": "--path_to_mutation_setting", "base": {}},
            "preflight_compile_timeout_seconds": 30, "require_pinned_command_tools": True,
            "require_save_output": False, "zkfuzz_output": "stderr_report", "pinned_trees": [],
            "pinned_files": [{"label": name, **arm.plan["tools"][name]} for name in ("circom", "zkfuzz")],
            "source_snapshots": snapshots, "targets": targets}
    if split:
        spec["pinned_files"].append({"label": "plan", **pin(plan_path)})
        spec["external_include_files"] = [item for row in planned for item in row["source_fingerprints"]]
    return spec, bindings


def worker(plan_path, job_index, folder):
    plan = json.loads(plan_path.read_text())
    job = plan["jobs"][job_index]
    folder.mkdir(parents=True, exist_ok=False)
    arm = Arm(folder, plan, job)
    try:
        with arm.stage("source_copy_and_pin_check"):
            validate_pins(plan)
            if os.getpriority(os.PRIO_PROCESS, 0) != 19:
                raise RuntimeError("worker requires nice 19")
            source = folder / "input/project"
            source.mkdir(parents=True)
            fixture = ROOT / "tests/fixtures/lifting" / job["fixture"]
            for name in ("component.circom", "entrypoint.circom", "standalone.circom"):
                raw = (fixture / "src" / name).read_text()
                (source / name).write_text(raw.replace("pragma circom 2.2.3;", "pragma circom 2.2.1;"))
            base = folder / "base-input.json"
            shutil.copyfile(fixture / "base_input.json", base)
            arm.summary["copied_sources"] = [pin(source / name) for name in ("component.circom", "entrypoint.circom", "standalone.circom")]
        compiled = folder / "original-o0"
        compiled.mkdir()
        arm.command("original_compile", [arm.tool("circom"), source / "entrypoint.circom", "--O0", "--r1cs", "--sym", "--wasm", "--output", compiled])
        with arm.stage("original_constraint_bound"):
            count = parse_r1cs((compiled / "entrypoint.r1cs").read_bytes())["shape"]["constraints"]
            arm.summary["original_constraints"] = count
            if count > plan["constraints_max"]:
                raise ValueError("synthetic constraint cap exceeded")
        wasm = compiled / "entrypoint_js"
        arm.command("base_witness", [arm.tool("node"), wasm / "generate_witness.js", wasm / "entrypoint.wasm", base, compiled / "base.wtns"])
        logs = arm.command("base_original_check", [arm.tool("snarkjs"), "wtns", "check", compiled / "entrypoint.r1cs", compiled / "base.wtns"])
        if "WITNESS IS CORRECT" not in (logs / "stdout.log").read_text():
            raise RuntimeError("base witness not confirmed by snarkjs")
        plan_path_local = None
        if job["method"] == "S":
            arm.command("discovery", [arm.tool("prepare"), "targets", "--project", source, "--entrypoint", source / "entrypoint.circom", "--output", folder / "input/discovery", "--circom-bin", arm.tool("circom"), "--compile-timeout-seconds", "30", "--instance-capture", "--capture-timeout-seconds", "30", "--library-path", source])
            with arm.stage("manifest_generation"):
                report = json.loads(one_report(folder / "input/discovery", "discovery.json").read_text())
                ref = (report.get("instance_discovery") or {}).get("capture")
                capture = Path(ref["path"]) if ref else None
                if capture is not None and not capture.is_absolute():
                    capture = ROOT / capture
                manifest = manifest_for("synthetic-operations", "synthetic", source,
                                        source / "entrypoint.circom", report, [source], capture)
                save(folder / "manifest.json", manifest, new=True)
            arm.command("preparation", [arm.tool("prepare"), "experiment", "prepare", "--manifest", folder / "manifest.json", "--output", folder / "prepared", "--strategy", "small-first", "--circom-bin", arm.tool("circom"), "--tool-timeout-seconds", "30"])
            prepared = one_report(folder / "prepared", "prepared.json")
            plan_path_local = folder / "split-plan.json"
            arm.command("ranking_plan", [arm.tool("prepare"), "experiment", "plan", "--prepared", prepared, "--strategy", "small-first", "--config", ROOT / "configs/static-ranking.json", "--output", plan_path_local])
        with arm.stage("campaign_spec_generation"):
            spec, bindings = spec_for_arm(arm, source, plan_path_local)
            save(folder / "campaign-spec.json", spec, new=True)
        with campaign.installed():
            campaign._ACTIVE_METHOD = spec["method"]
            with arm.stage("preflight_compile_and_copy"):
                campaign.v1.preflight(folder / "campaign-spec.json", folder / "preflight")
            if time.monotonic() >= arm.cutoff:
                arm.summary["status"] = "preparation_exhausted_search_window"
                return
            with arm.stage("fuzz_campaign"):
                spec_sha = sha(folder / "campaign-spec.json")
                snapshots, pf_root = campaign.v1.read_preflight(spec, spec_sha, folder / "preflight/preflight.json")
                run = campaign.v1.run_campaign(spec, spec_sha, snapshots, pf_root, folder / "campaign",
                                               cancel_check=lambda: time.monotonic() >= arm.cutoff,
                                               max_attempts=arm.plan["max_attempts_per_arm"])
                ledger = run["ledger"]
                if ledger["status"] == "incomplete" or any("candidates" not in item for item in ledger["attempts"]):
                    raise RuntimeError(f"campaign infrastructure incomplete: {ledger.get('fatal_error')}")
                campaign_origin_upper = arm.offset() - ledger["campaign_wall_seconds"]
        with arm.stage("candidate_inventory_and_requests"):
            candidates = []
            for attempt in ledger["attempts"]:
                index = attempt["target_index"]
                if attempt["target_id"] != bindings[index]["target_id"]:
                    raise ValueError("target binding mismatch")
                for candidate in attempt["candidates"]:
                    path = (folder / "campaign" / candidate["path"]).resolve()
                    if not path.is_relative_to(folder / "campaign") or sha(path) != candidate["sha256"]:
                        raise ValueError("candidate path/hash mismatch")
                    # Completion is a persisted upper bound, not exact discovery time.
                    available = campaign_origin_upper + attempt["completion_offset_seconds"]
                    candidates.append({"path": str(path), "sha256": candidate["sha256"],
                                       "target_index": index, "available_offset_seconds": available,
                                       "before_search_cutoff": available <= arm.cutoff - arm.t0})
            candidates.sort(key=lambda r: (r["available_offset_seconds"], r["target_index"], r["sha256"]))
            arm.summary["candidates"] = candidates
            arm.summary["prepared_targets"] = len(bindings)
            for index, row in enumerate(candidates):
                request = {"schema": "zkfdo-lifting-request-v1", "id": f"n7-{job_index}-{index}",
                           "source_root": str(folder / "input"), "library_paths": [str(source)],
                           "component_wrapper": bindings[row["target_index"]]["wrapper"],
                           "entrypoint": str(source / "entrypoint.circom"), "base_input": str(base),
                           "candidate": {"format": "zkfuzz", "path": row["path"]}}
                request_path = folder / "requests" / f"{index:04d}.json"
                save(request_path, request, new=True)
                row["request"] = pin(request_path)
        for index, row in enumerate(arm.summary["candidates"]):
            if not row["before_search_cutoff"]:
                continue
            arm.check()
            result_dir = folder / "judgements" / f"{index:04d}"
            command = [arm.tool("J"), "--request", row["request"]["path"], "--output", result_dir,
                       "--cache", folder / "j-cache", "--instance-store", folder / "instance-store"]
            for name in ("circom", "node", "snarkjs", "z3"):
                command += [f"--{name}-bin", arm.tool(name)]
            arm.command(f"judge-{index:04d}", command)
            with arm.stage(f"validate-result-{index:04d}"):
                path = result_dir / "result.json"
                result = json.loads(path.read_text())
                if result["request_sha256"] != row["request"]["sha256"]:
                    raise ValueError("J request hash mismatch")
                if result["candidate_sha256"] != row["sha256"]:
                    raise ValueError("J candidate hash mismatch")
                preparation = result.get("preparation") or {}
                entrypoint = result.get("entrypoint") or {}
                if preparation.get("status") == "ok" and entrypoint.get("o0_r1cs_sha256") != sha(compiled / "entrypoint.r1cs"):
                    raise ValueError("J original O0 R1CS differs from the compiled original")
                classes = [{k: item.get(k) for k in ("pattern", "verdict", "reason", "rust_unsatisfied", "snarkjs", "honest_generation", "deviated_generation")}
                           for item in result.get("classes", [])]
                j_status = "checked" if preparation.get("status") == "ok" and classes else "incomplete"
                l1 = (sum(item["verdict"] == "entrypoint_violation" and
                          item["rust_unsatisfied"] == 0 and item["snarkjs"] == "correct" for item in classes)
                      if j_status == "checked" else None)
                judged = {"candidate_sha256": row["sha256"], "result": pin(path), "classes": classes,
                          "preparation": preparation, "entrypoint": entrypoint, "j_status": j_status,
                          "validated_l1_classes": l1}
                arm.summary["judgements"].append(judged)
                # The complete evidence is fsynced in events.jsonl before the
                # durability clock is read. result.json is a derived index.
                durable = arm.event({"event": "judgement_evidence_durable", **judged})
                judged["durably_recorded_offset_seconds"] = durable
                judged["within_total_budget"] = durable < arm.deadline - arm.t0
        eligible = [c for c in arm.summary["candidates"] if c["before_search_cutoff"]]
        arm.summary["status"] = ("no_in_budget_candidate" if not eligible else
                                 "completed" if all(j["j_status"] == "checked" for j in arm.summary["judgements"])
                                 else "incomplete_j_preparation")
    except Exception as error:
        arm.summary["status"] = "error"
        arm.summary["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        arm.summary["worker_result_offset_seconds"] = arm.offset()
        save(folder / "result.json", arm.summary)


def semantic_gate(folder, row, limit):
    """Check the frozen synthetic operations expectations, not method efficacy."""
    job = row["job"]
    worker = row.get("worker") or {}
    errors = []
    if not row["cleanup_complete"] or row["status"] not in ("completed", "timeout"):
        errors.append("supervision_or_cleanup_incomplete")
    count = worker.get("original_constraints")
    if not isinstance(count, int) or not 1 <= count <= 1000:
        errors.append("original_constraint_bound_missing")
    stages = {item["stage"] for item in worker.get("stages", [])}
    if not {"base_original_check", "fuzz_campaign", "candidate_inventory_and_requests"}.issubset(stages):
        errors.append("required_stages_incomplete")
    if job["method"] == "S" and (worker.get("prepared_targets") or 0) < 1:
        errors.append("automatic_split_targets_missing")
    ledger_path = folder / "work/campaign/ledger.json"
    if not ledger_path.is_file():
        errors.append("campaign_ledger_missing")
    else:
        try:
            ledger = json.loads(ledger_path.read_text())
        except (OSError, json.JSONDecodeError):
            errors.append("campaign_ledger_incomplete")
        else:
            if ledger.get("status") == "incomplete" or ledger.get("fatal_error") or any(
                    "candidates" not in item for item in ledger.get("attempts", [])):
                errors.append("campaign_ledger_incomplete")

    candidates = [c for c in worker.get("candidates", []) if c.get("before_search_cutoff")]
    judgements = worker.get("judgements", [])
    events_path = folder / "work/events.jsonl"
    try:
        events = ([json.loads(line) for line in events_path.read_text().splitlines()]
                  if events_path.is_file() else [])
    except (OSError, json.JSONDecodeError):
        events = []
        errors.append("durable_event_log_incomplete")
    durable = [event for event in events if event.get("event") == "judgement_evidence_durable"]
    if len(durable) != len(judgements):
        errors.append("durable_event_index_count_mismatch")
    for event, judged in zip(durable, judgements):
        offset = judged.get("durably_recorded_offset_seconds")
        if (event.get("candidate_sha256") != judged.get("candidate_sha256") or
                event.get("result") != judged.get("result") or
                not isinstance(offset, (int, float)) or
                event["observed_offset_seconds"] > offset or
                judged.get("within_total_budget") != (offset < limit)):
            errors.append("durable_event_index_value_mismatch")
        result = judged.get("result") or {}
        if not Path(result.get("path", "")).is_file() or sha(result["path"]) != result.get("sha256"):
            errors.append("J_result_hash_mismatch")
    within = [j for j in judgements if j.get("within_total_budget") and j.get("j_status") == "checked"]
    l1 = sum(j.get("validated_l1_classes") or 0 for j in within)
    if job["fixture"] == "entrypoint_violation":
        if not candidates:
            errors.append("positive_natural_candidate_missing")
        if l1 < 1:
            errors.append("positive_original_L1_missing")
    elif job["method"] == "S":
        if not candidates:
            errors.append("negative_split_natural_candidate_missing")
        if not within:
            errors.append("negative_split_J_missing")
        for judged in within:
            if (judged.get("validated_l1_classes") != 0 or
                    any(c.get("reason") != "outputs_equal" or c.get("rust_unsatisfied") != 0 or
                        c.get("snarkjs") != "correct" for c in judged.get("classes", []))):
                errors.append("negative_split_not_verified_non_L1")
    elif candidates:
        if not within:
            errors.append("negative_whole_candidate_unjudged")
        if l1:
            errors.append("negative_whole_unexpected_L1")
    if worker.get("status") in ("error", "incomplete_j_preparation", "preparation_exhausted_search_window"):
        errors.append("worker_incomplete")
    return {"passed": not errors, "errors": sorted(set(errors)), "eligible_natural_candidates": len(candidates),
            "within_budget_checked_judgements": len(within), "within_budget_validated_l1_classes": l1,
            "durable_judgements": len(durable), "indexed_judgements": len(judgements)}


def execute(plan_path, output):
    plan = json.loads(plan_path.read_text())
    if plan["schema"] != "n7-inclusive-operations-pilot-v2" or plan["efficacy_claim_allowed"]:
        raise ValueError("synthetic operations plan required")
    validate_pins(plan)
    output = owned(output)
    output.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(output).free < 30 * 2**30:
        raise RuntimeError("internal disk start gate: 30 GiB required")
    receipt = {"plan": pin(plan_path), "status": "running", "arms": [], "efficacy_claim_allowed": False}
    with (OUT / "execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for index, job in enumerate(plan["jobs"]):
            folder = output / f"{index:02d}-{job['fixture']}-{job['seed']}-{job['method']}"
            tmp = folder / "tmp"
            tmp.mkdir(parents=True)
            started = time.monotonic()
            run = run_bounded([sys.executable, "-B", str(Path(__file__).resolve()), "worker",
                               "--plan", str(plan_path), "--index", str(index), "--output", str(folder / "work")],
                              folder / "supervision", plan["total_seconds_per_arm"],
                              env={"PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(tmp), "RAYON_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
            row = {"job": job, "supervision": pin(folder / "supervision/receipt.json"),
                   "status": run["status"], "cleanup_complete": run["cleanup_complete"],
                   "inclusive_call_wall_seconds": time.monotonic() - started,
                   "peak_process_tree_rss_bytes": run["peak_process_tree_rss_bytes"]}
            result = folder / "work/result.json"
            if result.is_file():
                row["worker"] = json.loads(result.read_text())
            row["semantic_gate"] = semantic_gate(folder, row, plan["total_seconds_per_arm"])
            receipt["arms"].append(row)
            save(output / "summary.json", receipt)
            print(json.dumps({"finished_arm": index, "job": job, "status": run["status"],
                              "worker_status": row.get("worker", {}).get("status"), "cleanup_complete": run["cleanup_complete"]}), flush=True)
            if not run["cleanup_complete"] or run["status"] not in ("completed", "timeout"):
                receipt["status"] = "stopped_at_failed_operations_gate"
                break
        else:
            receipt["status"] = ("operations_gate_passed" if all(
                arm["semantic_gate"]["passed"] for arm in receipt["arms"]) else "operations_gate_failed")
        save(output / "summary.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    item = sub.add_parser("plan")
    item.add_argument("--output", type=Path, required=True)
    item.add_argument("--seconds", type=float, default=30)
    item = sub.add_parser("run")
    item.add_argument("--plan", type=Path, required=True)
    item.add_argument("--output", type=Path, required=True)
    item = sub.add_parser("worker")
    item.add_argument("--plan", type=Path, required=True)
    item.add_argument("--index", type=int, required=True)
    item.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "plan":
        print(json.dumps(make_plan(args.output, args.seconds)))
    elif args.action == "run":
        execute(args.plan.resolve(), args.output)
    else:
        worker(args.plan.resolve(), args.index, owned(args.output))


if __name__ == "__main__":
    main()
