#!/usr/bin/env python3
"""Run the frozen controlled-v1.1 campaign without inspecting candidate values."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time


ROOT = Path("/Users/miiz/Desktop/kwzzzz_zkfr")
PROTOCOL_V1 = ROOT / "docs/controlled_v1_evaluation_protocol.md"
PROTOCOL_V11 = ROOT / "docs/controlled_v1_1_execution_protocol.md"
PREPARED = ROOT / "reports/controlled-v1-static-regression/evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/prepared.json"
CONFIG = ROOT / "configs/static-ranking.json"
ZKFUZZ = ROOT / ".external/zkFuzz/target/release/zkfuzz"
BINARY = ROOT / "runs/controlled-v1.1/frozen-tools/zkfDO-9a8bb031-debug"
OUTPUT_ROOT = ROOT / "runs/controlled-v1.1/campaigns"
IMPLEMENTATION_COMMIT = "9a8bb0319a8b4e127f73be5f1fa279eafb9156db"
IMPLEMENTATION_TREE = "4215bea47d73115dd8c5663a5df538803828a746"
BINARY_SHA256 = "e3472909d3d8de4411ee20a9574a822b9c262e7aff935c9bf38eac8f31a16960"
VULNERABLE = "sha256:1fdbf2dbcb8c5be4cad2ef0937cdc95c1b36cc8321e2d02f1b820f46c1b91474"
FIXED = "sha256:a85819549a69210934d31e3fa4a0ba4e01f1f456bc86b32a480a29c5b18aec91"

EXPECTED_HASHES = {
    PROTOCOL_V1: "0552be5557315ecdf1e929ed9b37120d96e3f77004e6d64219675268563665b9",
    PROTOCOL_V11: "a41ef6f9e75c536477d4f87510a2d043a0a5982b920a8f60519c38d9bcf8dff2",
    ROOT / "datasets/manifest.controlled-v1.json": "ec27dc5f088d85ae63e4f5a8397a4d3e9ad01c390af24498d1fc56c47a0931e8",
    ROOT / "datasets/contracts.controlled-v1.json": "d954de5fe6d8adbeb010f307119b9b3a0207d80b900ed9365d53a16a0f293f9a",
    PREPARED: "ab180da1918e275d541866b9476728898805df551a9c1457978f62b43c2ebaa1",
    CONFIG: "8fed87764b001245d600307f7ba7d8453e88e3b977afda656014eac83ea32d26",
    ZKFUZZ: "ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd",
    Path("/Users/miiz/.cargo/bin/circom"): "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227",
    ROOT / ".external/circomspect/target/release/circomspect": "6acebb5f1c00fd3823e96388cb322cd29bd516f8bacecf855fee5652431c3590",
    ROOT / "datasets/controlled-v1/subtract/vulnerable/circuit.circom": "5160da57762a5a561cf797a44f2dd6f009126536be476cbcec0926459362e079",
    ROOT / "datasets/controlled-v1/subtract/vulnerable/subtractTensor.circom": "502ee44b70a368066fafcf09cc2d0356479f8a862bfa726bde8097c728c83cc1",
    ROOT / "datasets/controlled-v1/subtract/fixed/circuit.circom": "5160da57762a5a561cf797a44f2dd6f009126536be476cbcec0926459362e079",
    ROOT / "datasets/controlled-v1/subtract/fixed/subtractTensor.circom": "c5d6aa9de7e95f09283e6b014dcbda85e16e583c3e157d7f8fdd95bb001023ba",
    BINARY: BINARY_SHA256,
}

# execution seed, random ranking seed, random first target, strategy order
BLOCKS = [
    (2026091901, 2026092901, FIXED, ("risk-only", "random", "small-first")),
    (2026091902, 2026092902, FIXED, ("random", "small-first", "risk-only")),
    (2026091903, 2026092903, FIXED, ("small-first", "risk-only", "random")),
    (2026091904, 2026092904, FIXED, ("risk-only", "random", "small-first")),
    (2026091905, 2026092905, VULNERABLE, ("random", "small-first", "risk-only")),
    (2026091906, 2026092906, VULNERABLE, ("small-first", "risk-only", "random")),
    (2026091907, 2026092907, FIXED, ("risk-only", "random", "small-first")),
    (2026091908, 2026092908, VULNERABLE, ("random", "small-first", "risk-only")),
    (2026091909, 2026092909, VULNERABLE, ("small-first", "risk-only", "random")),
    (2026091910, 2026092910, FIXED, ("risk-only", "random", "small-first")),
    (2026091911, 2026092911, VULNERABLE, ("random", "small-first", "risk-only")),
    (2026091912, 2026092913, VULNERABLE, ("small-first", "risk-only", "random")),
]


class CampaignInvalid(RuntimeError):
    """A preflight/driver condition invalidates the whole paired block."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_text(args, cwd=ROOT):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def check(condition, message):
    if not condition:
        raise CampaignInvalid(message)


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def environment():
    hashes = {}
    for path, expected in EXPECTED_HASHES.items():
        check(path.is_file(), f"missing frozen input/tool: {path}")
        actual = sha256(path)
        check(actual == expected, f"hash mismatch: {path}: {actual}, expected {expected}")
        hashes[str(path)] = actual

    check(command_text(["git", "rev-parse", IMPLEMENTATION_COMMIT + "^{commit}"]) == IMPLEMENTATION_COMMIT,
          "pinned implementation commit unavailable")
    check(command_text(["git", "rev-parse", IMPLEMENTATION_COMMIT + "^{tree}"]) == IMPLEMENTATION_TREE,
          "pinned implementation tree changed")
    check(command_text(["git", "-C", str(ROOT / ".external/zkFuzz"), "rev-parse", "HEAD"]) ==
          "072bf1fbbd1c9ecad58d4f6d2204c3b96e7fec17", "zkFuzz revision changed")
    check(command_text(["git", "-C", str(ROOT / ".external/circomspect"), "rev-parse", "HEAD"]) ==
          "ece9efe0a21e6c422a43ab6f2e1c0ce99678013b", "Circomspect revision changed")

    prepared = json.loads(PREPARED.read_text())
    eligible = [target for target in prepared["targets"] if target["eligible"]]
    check(prepared["profile_strategy"] is None, "prepared set is not common-profile")
    check(len(eligible) == 2, "prepared set must have exactly two eligible targets")
    check({target["target_id"] for target in eligible} == {VULNERABLE, FIXED}, "prepared target IDs changed")
    for target in eligible:
        check(target["structure"]["compile_success"] is True, "prepared target did not compile")
        for fingerprint in target["source_fingerprints"] + target["snapshot_fingerprints"]:
            path = Path(fingerprint["path"])
            check(path.is_file() and sha256(path) == fingerprint["sha256"],
                  f"source/snapshot changed: {path}")
        check(Path(target["run_entrypoint"]).is_file(), "prepared run entrypoint unavailable")

    hardware = json.loads(command_text(["system_profiler", "SPHardwareDataType", "-json"]))["SPHardwareDataType"][0]
    device = {key: hardware.get(key) for key in
              ("machine_model", "chip_type", "number_processors", "physical_memory")}
    check(device == {"machine_model": "Mac17,2", "chip_type": "Apple M5",
                     "number_processors": "proc 10:4:6", "physical_memory": "24 GB"},
          "hardware changed")
    check(platform.system() == "Darwin" and platform.machine() == "arm64", "architecture changed")
    os_version = command_text(["sw_vers", "-productVersion"])
    os_build = command_text(["sw_vers", "-buildVersion"])
    check((os_version, os_build, platform.release()) == ("26.2", "25C56", "25.2.0"), "OS changed")
    battery = command_text(["pmset", "-g", "batt"])
    check("Now drawing from 'AC Power'" in battery, "AC power unavailable")
    power = command_text(["pmset", "-g", "custom"])
    ac_section = power.split("AC Power:", 1)[1].split("Battery Power:", 1)[0]
    check(re.search(r"(?m)^\s*lowpowermode\s+0\s*$", ac_section) is not None,
          "AC low power mode enabled")
    disk_free = os.statvfs(OUTPUT_ROOT.parent).f_bavail * os.statvfs(OUTPUT_ROOT.parent).f_frsize
    check(disk_free >= 5 * 1024**3, "less than 5 GiB free space")

    return {
        "checked_at_utc": utc_now(),
        "repository_head": command_text(["git", "rev-parse", "HEAD"]),
        "implementation_commit": IMPLEMENTATION_COMMIT,
        "implementation_tree": IMPLEMENTATION_TREE,
        "working_tree_status": command_text(["git", "status", "--short"]),
        "hashes": hashes,
        "device": device,
        "os_version": os_version,
        "os_build": os_build,
        "darwin_release": platform.release(),
        "architecture": platform.machine(),
        "ac_power": True,
        "ac_low_power_mode": False,
        "disk_free_bytes": disk_free,
        "personal_hardware_identifiers_recorded": False,
    }


def invoke(args, stdout_path, stderr_path):
    started = utc_now()
    timer = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        completed = subprocess.run(args, cwd=ROOT, stdout=stdout, stderr=stderr, check=False)
    return {
        "command": [str(item) for item in args],
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
        "wall_seconds": time.monotonic() - timer,
        "exit_code": completed.returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def validate_outcome(outcome_path, outcome, plan_path, plan, strategy, execution_seed):
    check(Path(outcome["plan_path"]).resolve() == plan_path.resolve(), "outcome plan path mismatch")
    check(outcome["plan_id"] == plan["plan_id"], "outcome plan ID mismatch")
    check(outcome["plan_sha256"] == sha256(plan_path), "outcome plan hash mismatch")
    check(outcome["strategy"] == strategy, "outcome strategy mismatch")
    check(outcome["budget_seconds_per_target"] == 30 and outcome["total_budget_seconds"] == 60,
          "outcome budget mismatch")
    check(outcome["zkfuzz_binary_sha256"] == EXPECTED_HASHES[ZKFUZZ], "outcome zkFuzz hash mismatch")
    check(outcome["mutation_settings"]["effective_seed"] == execution_seed,
          "outcome execution seed mismatch")
    expected_ids = [target["target_id"] for target in plan["targets"]]
    scheduler = outcome["scheduler"]
    check(scheduler["planned_target_ids"] == expected_ids, "scheduler target order mismatch")
    check(scheduler["budget_seconds_per_target"] == 30 and scheduler["total_budget_seconds"] == 60,
          "scheduler budget mismatch")
    run_ids = {}
    for scheduled in scheduler["runs"]:
        run_id = scheduled["result"]["run_id"]
        check(run_id not in run_ids, "duplicate scheduler run ID")
        check(scheduled["target_id"] in expected_ids, "scheduler run target outside plan")
        run_ids[run_id] = scheduled
    for artifact in outcome["counterexample_candidates"]:
        check(artifact["run_id"] in run_ids, "candidate references unknown run")
        scheduled = run_ids[artifact["run_id"]]
        check(scheduled["target_id"] == artifact["target_id"], "candidate run/target mismatch")
        check(scheduled["result"]["status"] == "bug_found", "candidate linked to non-bug_found run")
        preserved = Path(artifact["preserved_path"])
        check(preserved.is_file() and sha256(preserved) == artifact["sha256"],
              "preserved candidate hash mismatch")
    check(Path(outcome["report_path"]).resolve() == outcome_path.resolve(), "outcome report path mismatch")


def run_strategy(attempt_dir, position, strategy, execution_seed, ranking_seed, random_first):
    strategy_dir = attempt_dir / f"{position:02d}-{strategy}"
    strategy_dir.mkdir()
    plan_path = strategy_dir / "plan.json"
    plan_args = [str(BINARY), "experiment", "plan", "--prepared", str(PREPARED),
                 "--strategy", strategy, "--config", str(CONFIG), "--output", str(plan_path)]
    if strategy == "random":
        plan_args += ["--ranking-seed", str(ranking_seed)]
    plan_invocation = invoke(plan_args, strategy_dir / "plan.stdout.json", strategy_dir / "plan.stderr.log")
    check(plan_invocation["exit_code"] == 0 and plan_path.is_file(), f"plan failed for {strategy}")
    plan = json.loads(plan_path.read_text())
    actual_ids = [item["target_id"] for item in plan["targets"]]
    expected_first = random_first if strategy == "random" else VULNERABLE
    expected_ids = [expected_first, FIXED if expected_first == VULNERABLE else VULNERABLE]
    check(actual_ids == expected_ids, f"plan order changed for {strategy}")
    check(plan["strategy"] == strategy and plan["prepared_sha256"] == EXPECTED_HASHES[PREPARED]
          and plan["config_sha256"] == EXPECTED_HASHES[CONFIG], "plan metadata changed")
    check(plan["ranking_seed"] == (ranking_seed if strategy == "random" else None),
          "ranking seed changed")
    check(plan["exclusions"] == [] and len(plan["targets"]) == 2, "plan target set changed")

    run_root = strategy_dir / "raw"
    run_root.mkdir()
    run_args = [str(BINARY), "experiment", "run", "--plan", str(plan_path),
                "--zkfuzz-bin", str(ZKFUZZ), "--budget-seconds", "30",
                "--total-budget-seconds", "60", "--zkfuzz-seed", str(execution_seed),
                "--output", str(run_root)]
    run_invocation = invoke(run_args, strategy_dir / "run.stdout.json", strategy_dir / "run.stderr.log")
    outcomes = list(run_root.glob("execution-*/outcome.json"))
    check(run_invocation["exit_code"] == 0 and len(outcomes) == 1,
          f"one valid outcome was not produced for {strategy}")
    outcome_path = outcomes[0]
    outcome = json.loads(outcome_path.read_text())
    validate_outcome(outcome_path, outcome, plan_path, plan, strategy, execution_seed)
    summaries = sorted(run_root.glob("execution-*/**/summary.json"))
    return {
        "position": position,
        "strategy": strategy,
        "ranking_seed": ranking_seed if strategy == "random" else None,
        "execution_seed": execution_seed,
        "plan_path": str(plan_path),
        "plan_sha256": sha256(plan_path),
        "plan_id": plan["plan_id"],
        "target_order": actual_ids,
        "planning_seconds": plan["planning_elapsed_seconds"],
        "plan_invocation": plan_invocation,
        "run_invocation": run_invocation,
        "outcome_path": str(outcome_path),
        "outcome_sha256": sha256(outcome_path),
        "scheduler_summary_files": [{"path": str(path), "sha256": sha256(path)} for path in summaries],
        "scheduler_elapsed_seconds": outcome["scheduler"]["elapsed_seconds"],
        "scheduler_run_statuses": [item["result"]["status"] for item in outcome["scheduler"]["runs"]],
        "scheduler_failure_count": len(outcome["scheduler"]["failures"]),
        "not_started_count": len(outcome["scheduler"]["skipped"]),
        "backend_candidate_count": len(outcome["counterexample_candidates"]),
        "status": "outcome_saved_and_link_verified",
    }


def run_block_attempt(block_dir, attempt_number, block_number, execution_seed, ranking_seed,
                      random_first, order, ledger_path, ledger):
    attempt_dir = block_dir / f"attempt-{attempt_number:02d}"
    attempt_dir.mkdir()
    record = {
        "attempt": attempt_number,
        "started_at_utc": utc_now(),
        "status": "in_progress",
        "environment": None,
        "strategy_runs": [],
    }
    try:
        record["environment"] = environment()
        save_json(attempt_dir / "environment.json", record["environment"])
        for position, strategy in enumerate(order, 1):
            # A changed frozen input or environment invalidates the paired block,
            # while statuses inside a structurally valid outcome do not.
            environment()
            result = run_strategy(attempt_dir, position, strategy, execution_seed,
                                  ranking_seed, random_first)
            record["strategy_runs"].append(result)
            save_json(block_dir / "block.json", record)
            save_json(ledger_path, ledger)
            print(f"block {block_number:02d}/12 attempt {attempt_number} {strategy}: "
                  f"{result['scheduler_run_statuses']}", flush=True)
        record["status"] = "valid_complete"
        record["finished_at_utc"] = utc_now()
        save_json(block_dir / "block.json", record)
        return True, record
    except Exception as error:
        record["status"] = "campaign_invalid"
        record["invalid_reason"] = str(error)
        record["finished_at_utc"] = utc_now()
        save_json(block_dir / f"attempt-{attempt_number:02d}-invalid.json", record)
        return False, record


def campaign():
    initial_environment = environment()
    campaign_dir = OUTPUT_ROOT / ("campaign-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    campaign_dir.mkdir(parents=True, exist_ok=False)
    ledger_path = campaign_dir / "campaign.json"
    ledger = {
        "schema_version": 1,
        "protocol_v1": str(PROTOCOL_V1),
        "protocol_v1_sha256": EXPECTED_HASHES[PROTOCOL_V1],
        "protocol_v1_1": str(PROTOCOL_V11),
        "protocol_v1_1_sha256": EXPECTED_HASHES[PROTOCOL_V11],
        "driver_path": str(Path(__file__).resolve()),
        "driver_sha256": sha256(Path(__file__).resolve()),
        "binary_path": str(BINARY),
        "binary_sha256": BINARY_SHA256,
        "status": "in_progress",
        "started_at_utc": utc_now(),
        "initial_environment": initial_environment,
        "blocks": [],
    }
    save_json(ledger_path, ledger)
    try:
        for number, (execution_seed, ranking_seed, random_first, order) in enumerate(BLOCKS, 1):
            block_dir = campaign_dir / f"block-{number:02d}"
            block_dir.mkdir()
            block_record = {
                "block": number,
                "execution_seed": execution_seed,
                "random_ranking_seed": ranking_seed,
                "random_first_target": random_first,
                "strategy_order": list(order),
                "attempts": [],
                "status": "in_progress",
            }
            ledger["blocks"].append(block_record)
            save_json(ledger_path, ledger)
            valid = False
            for attempt_number in (1, 2):
                valid, attempt = run_block_attempt(block_dir, attempt_number, number,
                                                   execution_seed, ranking_seed, random_first,
                                                   order, ledger_path, ledger)
                block_record["attempts"].append(attempt)
                save_json(ledger_path, ledger)
                if valid:
                    break
                if attempt_number == 1:
                    print(f"block {number:02d}: campaign-invalid; retrying whole block once",
                          flush=True)
            if not valid:
                block_record["status"] = "invalid_twice_campaign_stopped"
                raise CampaignInvalid(f"block {number} was campaign-invalid twice")
            block_record["status"] = "valid_complete"
            block_record["selected_attempt"] = attempt["attempt"]
            block_record["finished_at_utc"] = utc_now()
            save_json(ledger_path, ledger)
        ledger["status"] = "execution_complete_adjudication_pending"
    except Exception as error:
        ledger["status"] = "stopped_preflight_or_driver_error"
        ledger["stop_reason"] = str(error)
        raise
    finally:
        ledger["finished_or_stopped_at_utc"] = utc_now()
        save_json(ledger_path, ledger)
    print(f"Campaign records: {campaign_dir}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="required acknowledgment to start all 36 runs")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required")
    campaign()
