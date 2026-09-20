#!/usr/bin/env python3
"""Run the frozen controlled-v2 paired campaign without reading candidate values."""

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
PROTOCOL = ROOT / "docs/controlled_v2_execution_protocol.md"
MANIFEST = ROOT / "datasets/manifest.controlled-v2.json"
CONTRACTS = ROOT / "datasets/contracts.controlled-v2.json"
PREPARED = ROOT / "reports/controlled-v2-preparation-2026-09-20/evidence/accepted-preparation/prepare-6cc01794-1fcf-404d-b577-5c208e94a7cd/prepared.json"
CONFIG = ROOT / "configs/static-ranking.json"
ZKFUZZ = ROOT / ".external/zkFuzz/target/release/zkfuzz"
CIRCOM = Path("/Users/miiz/.cargo/bin/circom")
CIRCOMSPECT = ROOT / ".external/circomspect/target/release/circomspect"
BINARY = ROOT / "runs/controlled-v1.1/frozen-tools/zkfDO-9a8bb031-debug"
OUTPUT_ROOT = ROOT / "runs/controlled-v2/campaigns"
IMPLEMENTATION_COMMIT = "9a8bb0319a8b4e127f73be5f1fa279eafb9156db"
IMPLEMENTATION_TREE = "4215bea47d73115dd8c5663a5df538803828a746"
BINARY_SHA256 = "e3472909d3d8de4411ee20a9574a822b9c262e7aff935c9bf38eac8f31a16960"

TV = "sha256:39ece08d569693c46d9896a351d6ccd4228b5e9f1b4debb10b2346d4ae0eded5"
TF = "sha256:46bff69377a67f20a7dd7f5fd4070fa92f97c88cb5d267d40a6fff6b2803e377"
BV = "sha256:b99bf2694b89536d1c7ca1ef97933456981930df93e7bfc08d0b61149a7bc496"
BF = "sha256:c7216c1efd7084100b27458fdbf6f4a00d7f9ddb13c09ee485d4bcbfaa0c5a5c"
TARGETS = {TV, TF, BV, BF}
FIXED_ORDERS = {
    "risk-only": [BV, BF, TV, TF],
    "small-first": [TV, TF, BV, BF],
}
EXPECTED_HASHES = {
    PROTOCOL: "4835c9bb340e34a436c71c4e86a91e6ff2c17f9dbd05747852d635ef0f894b76",
    MANIFEST: "758180ae4827f53adbaa35d8075566a3f3eb3a090be221dbd5183527657c70b7",
    CONTRACTS: "a9f0d595dfee347f0d54a9c2b253ea4da84ae74c76d39cb108ad1151dd2152a0",
    PREPARED: "967135b38000ee09b1d82aa15cf1bbbdb354fbecf437692e77a9e440f99dd504",
    CONFIG: "8fed87764b001245d600307f7ba7d8453e88e3b977afda656014eac83ea32d26",
    ZKFUZZ: "ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd",
    CIRCOM: "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227",
    CIRCOMSPECT: "6acebb5f1c00fd3823e96388cb322cd29bd516f8bacecf855fee5652431c3590",
    BINARY: BINARY_SHA256,
}

# execution seed, random ranking seed, random target order, balanced strategy execution order
BLOCKS = [
    (2026092001, 2026094001, [BF, TF, BV, TV], ("risk-only", "random", "small-first")),
    (2026092002, 2026094002, [TV, BV, BF, TF], ("random", "small-first", "risk-only")),
    (2026092003, 2026094003, [BF, BV, TV, TF], ("small-first", "risk-only", "random")),
    (2026092004, 2026094004, [BF, TF, TV, BV], ("risk-only", "random", "small-first")),
    (2026092005, 2026094005, [TF, BV, TV, BF], ("random", "small-first", "risk-only")),
    (2026092006, 2026094006, [TV, BF, BV, TF], ("small-first", "risk-only", "random")),
    (2026092007, 2026094007, [TF, BV, TV, BF], ("risk-only", "random", "small-first")),
    (2026092008, 2026094008, [BV, BF, TF, TV], ("random", "small-first", "risk-only")),
    (2026092009, 2026094009, [TV, BF, BV, TF], ("small-first", "risk-only", "random")),
    (2026092010, 2026094010, [TV, TF, BV, BF], ("risk-only", "random", "small-first")),
    (2026092011, 2026094011, [TF, TV, BV, BF], ("random", "small-first", "risk-only")),
    (2026092012, 2026094012, [BV, TV, BF, TF], ("small-first", "risk-only", "random")),
]


class CampaignInvalid(RuntimeError):
    pass


class ObservedExecutionFailure(RuntimeError):
    """A backend invocation was attempted and must never be replaced by a retry."""


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
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def environment():
    hashes = {}
    for frozen_path, expected in EXPECTED_HASHES.items():
        check(frozen_path.is_file(), f"missing frozen input/tool: {frozen_path}")
        actual = sha256(frozen_path)
        check(actual == expected, f"hash mismatch: {frozen_path}: {actual}, expected {expected}")
        hashes[str(frozen_path)] = actual

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
    check(len(eligible) == 4, "prepared set must have exactly four eligible targets")
    check({target["target_id"] for target in eligible} == TARGETS, "prepared target IDs changed")
    for target in eligible:
        check(target["structure"]["compile_success"] is True, "prepared target did not compile")
        check(target["semantic"]["complete"] is True, "prepared semantic analysis is incomplete")
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
    check(outcome["budget_seconds_per_target"] == 30 and outcome["total_budget_seconds"] == 120,
          "outcome budget mismatch")
    check(outcome["zkfuzz_binary_sha256"] == EXPECTED_HASHES[ZKFUZZ], "outcome zkFuzz hash mismatch")
    check(outcome["mutation_settings"]["effective_seed"] == execution_seed,
          "outcome execution seed mismatch")
    expected_ids = [target["target_id"] for target in plan["targets"]]
    scheduler = outcome["scheduler"]
    check(scheduler["planned_target_ids"] == expected_ids, "scheduler target order mismatch")
    check(scheduler["budget_seconds_per_target"] == 30 and scheduler["total_budget_seconds"] == 120,
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


def run_strategy(attempt_dir, position, strategy, execution_seed, ranking_seed, random_order):
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
    expected_ids = random_order if strategy == "random" else FIXED_ORDERS[strategy]
    check(actual_ids == expected_ids, f"plan order changed for {strategy}")
    check(plan["strategy"] == strategy and plan["prepared_sha256"] == EXPECTED_HASHES[PREPARED]
          and plan["config_sha256"] == EXPECTED_HASHES[CONFIG], "plan metadata changed")
    check(plan["ranking_seed"] == (ranking_seed if strategy == "random" else None),
          "ranking seed changed")
    check(plan["exclusions"] == [] and len(plan["targets"]) == 4, "plan target set changed")

    run_root = strategy_dir / "raw"
    run_root.mkdir()
    run_args = [str(BINARY), "experiment", "run", "--plan", str(plan_path),
                "--zkfuzz-bin", str(ZKFUZZ), "--budget-seconds", "30",
                "--total-budget-seconds", "120", "--zkfuzz-seed", str(execution_seed),
                "--output", str(run_root)]
    run_invocation = invoke(run_args, strategy_dir / "run.stdout.json", strategy_dir / "run.stderr.log")
    outcomes = list(run_root.glob("execution-*/outcome.json"))
    if run_invocation["exit_code"] != 0 or len(outcomes) != 1:
        raise ObservedExecutionFailure(
            f"backend execution was attempted for {strategy}; exit={run_invocation['exit_code']}, "
            f"outcomes={len(outcomes)}; no retry is permitted")
    outcome_path = outcomes[0]
    outcome = json.loads(outcome_path.read_text())
    try:
        validate_outcome(outcome_path, outcome, plan_path, plan, strategy, execution_seed)
    except CampaignInvalid as error:
        raise ObservedExecutionFailure(
            f"saved backend outcome failed linkage validation for {strategy}; "
            f"no retry is permitted: {error}") from error
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
                      random_order, order):
    attempt_dir = block_dir / f"attempt-{attempt_number:02d}"
    attempt_dir.mkdir()
    record = {"attempt": attempt_number, "started_at_utc": utc_now(),
              "status": "in_progress", "environment": None, "strategy_runs": []}
    try:
        record["environment"] = environment()
        save_json(attempt_dir / "environment.json", record["environment"])
        for position, strategy in enumerate(order, 1):
            environment()
            result = run_strategy(attempt_dir, position, strategy, execution_seed,
                                  ranking_seed, random_order)
            record["strategy_runs"].append(result)
            save_json(block_dir / "block.json", record)
            print(f"block {block_number:02d}/12 attempt {attempt_number} {strategy}: "
                  f"{result['scheduler_run_statuses']}", flush=True)
        record["status"] = "valid_complete"
        record["finished_at_utc"] = utc_now()
        save_json(block_dir / "block.json", record)
        return True, record
    except ObservedExecutionFailure:
        record["status"] = "observed_execution_failure_no_retry"
        record["finished_at_utc"] = utc_now()
        save_json(block_dir / f"attempt-{attempt_number:02d}-execution-failure.json", record)
        raise
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
        "protocol_path": str(PROTOCOL),
        "protocol_sha256": EXPECTED_HASHES[PROTOCOL],
        "manifest_path": str(MANIFEST),
        "manifest_sha256": EXPECTED_HASHES[MANIFEST],
        "contracts_path": str(CONTRACTS),
        "contracts_sha256": EXPECTED_HASHES[CONTRACTS],
        "prepared_path": str(PREPARED),
        "prepared_sha256": EXPECTED_HASHES[PREPARED],
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
        for number, (execution_seed, ranking_seed, random_order, order) in enumerate(BLOCKS, 1):
            block_dir = campaign_dir / f"block-{number:02d}"
            block_dir.mkdir()
            block_record = {
                "block": number,
                "execution_seed": execution_seed,
                "random_ranking_seed": ranking_seed,
                "random_target_order": random_order,
                "strategy_order": list(order),
                "attempts": [],
                "status": "in_progress",
            }
            ledger["blocks"].append(block_record)
            save_json(ledger_path, ledger)
            valid = False
            for attempt_number in (1, 2):
                valid, attempt = run_block_attempt(block_dir, attempt_number, number, execution_seed,
                                                   ranking_seed, random_order, order)
                block_record["attempts"].append(attempt)
                save_json(ledger_path, ledger)
                if valid:
                    break
                if attempt_number == 1:
                    print(f"block {number:02d}: campaign-invalid; retrying whole block once", flush=True)
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
