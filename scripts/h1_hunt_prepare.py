#!/usr/bin/env python3
"""H1 exploratory hunting: prepare W/S zkFuzz campaign specs for new targets (no fuzzing).

Reuses the E-02 preparation (zkfDO targets -> F-01 manifest -> experiment prepare -> plan) and
the N6-B spec builder, with the nested-array-fixed zkFuzz binary from N6-B5. These targets are
outside the frozen N5 lists. Work files live under runs/h1-hunt-2026-10-25.noindex/work.
Actions: prepare, specs, preflight.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import n6_prepare_b_stage1 as b1  # noqa: E402
import run_e02_production_mains as e02  # noqa: E402

HUNT = ROOT / "runs/h1-hunt-2026-10-25.noindex"
WORK = HUNT / "work"
CLONES = ROOT / "runs/h1-candidates-2026-10-25/clones"
CIRCOMLIB = ROOT / ("runs/c03-corpus-2026-10-02/recovery-v3/repositories/"
                    "0xbow-io__privacy-pools-core/clone/node_modules/circomlib")
LIBROOT = ROOT / "runs/h1-candidates-2026-10-25/libroot"
ZKFUZZ = ROOT / "runs/n6-b5-2026-10-17.noindex/zkfuzz-nested-target/release/zkfuzz"
ZKFUZZ_SHA = "f4d992e707c4227de99467adf38bae3ad98573ec5ababe09e391429d7c2542f0"
BUDGET = 1800
SPLIT_SEEDS = [2026102501, 2026102502]
WHOLE_SEEDS = [2026102501]
RUNNER = ROOT / "scripts/run_policy_a_engine_v4.py"
# Preflight and campaign outputs stay on the internal disk: the runner clones snapshots with
# clonefile, which fails across volumes.
OUTPUTS = HUNT / "outputs"

MOROS = CLONES / "HoomanBuilds_moros"
EDEC = CLONES / "ethstorage_zk-decoder"
TARGETS = [
    ("moros-batch", "HoomanBuilds/moros", MOROS, "contracts/shielded-collateral-vault/circuits/batch.circom",
     [CIRCOMLIB / "circuits", MOROS / "contracts/shielded-collateral-vault/circuits", LIBROOT / "node_modules"]),
    ("moros-exit-match", "HoomanBuilds/moros", MOROS,
     "contracts/shielded-collateral-vault/circuits/exit_match.circom",
     [CIRCOMLIB / "circuits", MOROS / "contracts/shielded-collateral-vault/circuits", LIBROOT / "node_modules"]),
    ("moros-transfer-four", "HoomanBuilds/moros", MOROS, "contracts/payment-circuits/transfer_four.circom",
     [CIRCOMLIB / "circuits", MOROS / "contracts/payment-circuits", LIBROOT / "node_modules"]),
    ("edec-blob-poseidon-2", "ethstorage/zk-decoder", EDEC, "circom/circuits/blob_poseidon_2.circom",
     [EDEC / "circom/circuits", EDEC / "circom/node_modules"]),
    ("edec-blob-poseidon", "ethstorage/zk-decoder", EDEC, "circom/circuits/blob_poseidon.circom",
     [EDEC / "circom/circuits", EDEC / "circom/node_modules"]),
]


def commit(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


def prepare() -> None:
    e02.RUN = WORK
    # The internal disk is shared; stop below 22 GiB instead of the E-02 35 GiB guard.
    e02.DISK_GUARD_BYTES = 22 * 1024**3
    binary = WORK / "tools/zkfDO"
    if not binary.exists():
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(e02.F01_BINARY.read_bytes())
        binary.chmod(0o755)
    if e02.legacy.digest(binary) != e02.EXPECTED_ZKFDO or e02.legacy.digest(e02.CIRCOM) != e02.EXPECTED_CIRCOM:
        raise RuntimeError("pinned zkfDO or circom hash mismatch")
    for identifier, repository, project, main, libraries in TARGETS:
        row = {"identifier": identifier, "repository": repository, "entrypoint_key": f"source_main:{main}",
               "project_root": str(project), "source": str(project / main),
               "library_paths": [str(path) for path in libraries], "commit_sha": commit(project)}
        result = e02.prepare_one({"row": row, "reason": "new_e02_compile_success", "constraints": None}, binary)
        print(json.dumps({"id": identifier, "discovery": result["discovery"]["status"],
                          "prepare300": result["prepare_300"]["status"],
                          "prepare900": result["prepare_900"]["status"],
                          "plan": result["plan"]["status"]}), flush=True)


def specs() -> None:
    b1.SPECS = HUNT / "specs"
    b1.ZKFUZZ, b1.ZKFUZZ_SHA = ZKFUZZ, ZKFUZZ_SHA
    original = b1.base_spec

    def hunt_spec(item, plan_path, seed, method, snapshots, targets):
        spec = original(item, plan_path, seed, method, snapshots, targets)
        spec["campaign_id"] = f"H1-hunt-{item['identifier']}-seed-{seed}-{method}"
        spec["total_budget_seconds"] = BUDGET
        spec["attempt_cap_seconds"] = BUDGET if method == "whole" else 30
        spec["coverage_checkpoints_seconds"] = [600, BUDGET]
        return spec

    b1.base_spec = hunt_spec
    cache: dict[Path, str] = {}
    units = []
    for identifier, repository, project, main, _ in TARGETS:
        plan = WORK / "preparation-measurements" / identifier / "plan.json"
        if not plan.is_file():
            print(json.dumps({"id": identifier, "skipped": "no plan"}), flush=True)
            continue
        item = {"identifier": identifier, "repository": repository, "commit": commit(project),
                "entrypoint_key": f"source_main:{main}",
                "plan": {"path": str(plan.relative_to(ROOT)), "sha256": b1.sha256(plan)}}
        for seed in sorted(set(SPLIT_SEEDS) | set(WHOLE_SEEDS)):
            stem = b1.SPECS / f"{identifier}-seed-{seed}"
            whole, split = Path(f"{stem}-W.json"), Path(f"{stem}-S.json")
            if not (whole.exists() and split.exists()):
                whole, split = b1.create_specs(item, seed, cache)
                patch_whole(whole)
            if seed in SPLIT_SEEDS:
                units.append({"id": f"{identifier}-seed-{seed}-S", "spec": str(split.relative_to(ROOT)),
                              "sha256": b1.sha256(split)})
            if seed in WHOLE_SEEDS:
                units.append({"id": f"{identifier}-seed-{seed}-W", "spec": str(whole.relative_to(ROOT)),
                              "sha256": b1.sha256(whole)})
    (HUNT / "units.json").write_text(json.dumps(units, indent=1) + "\n")
    print(json.dumps({"units": len(units)}), flush=True)


def patch_whole(path: Path) -> None:
    """Append the recorded absolute library paths to the whole-circuit target.

    The B builder maps every -l below runs/ onto the whole-project snapshot, which is right for
    E-02 prepared sources but not for libraries outside the cloned project (local circomlib).
    Split targets already append the absolute list; the whole target gets the same suffix.
    """
    spec = json.loads(path.read_text())
    for target in spec["targets"]:
        extra = []
        for library in target["recorded_library_paths"]:
            extra += ["-l", library]
        for key in ("command", "preflight_compile_command"):
            if not target[key][-len(extra):] == extra:
                target[key] = target[key] + extra
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def preflight() -> None:
    units = json.loads((HUNT / "units.json").read_text())
    for unit in units:
        base = OUTPUTS / "preflight" / unit["id"]
        out = base / "out"
        if out.exists():
            continue
        base.mkdir(parents=True, exist_ok=True)
        run = subprocess.run([sys.executable, str(RUNNER), "preflight", "--spec", str(ROOT / unit["spec"]),
                              "--output", str(out)], capture_output=True, text=True)
        (base / "call.log").write_text(run.stdout + run.stderr)
        print(json.dumps({"id": unit["id"], "exit": run.returncode,
                          "tail": (run.stdout + run.stderr).strip().splitlines()[-1:]}), flush=True)


def run(concurrency: int = 2, min_free_gib: int = 15, only: str | None = None) -> None:
    """Run every preflighted unit, largest target first, at most `concurrency` at a time."""
    import shutil
    import time
    order = [identifier for identifier, *_ in TARGETS]
    units = json.loads((HUNT / "units.json").read_text())
    units.sort(key=lambda unit: (order.index(next(i for i in order if unit["id"].startswith(i + "-seed"))),
                                 unit["id"].endswith("-S"), unit["id"]))
    active: list[tuple[str, subprocess.Popen]] = []
    pending = [unit for unit in units if not (OUTPUTS / "runs" / unit["id"] / "out").exists()
               and (only is None or unit["id"].startswith(only))]
    while pending or active:
        active = [(name, proc) for name, proc in active if proc.poll() is None]
        free = shutil.disk_usage(ROOT).free / 1024**3
        if pending and len(active) < concurrency and free >= min_free_gib:
            unit = pending.pop(0)
            base = OUTPUTS / "runs" / unit["id"]
            base.mkdir(parents=True, exist_ok=True)
            log = (base / "call.log").open("w")
            proc = subprocess.Popen([sys.executable, str(RUNNER), "run", "--spec", str(ROOT / unit["spec"]),
                                     "--preflight", str(OUTPUTS / "preflight" / unit["id"] / "out" / "preflight.json"),
                                     "--output", str(base / "out")], stdout=log, stderr=subprocess.STDOUT)
            active.append((unit["id"], proc))
            print(json.dumps({"started": unit["id"], "free_gib": round(free, 1), "at": time.strftime("%H:%M")}),
                  flush=True)
            continue
        if pending and free < min_free_gib and not active:
            print(json.dumps({"stopped": "internal disk below guard", "free_gib": round(free, 1)}), flush=True)
            return
        time.sleep(20)
    print(json.dumps({"finished": len(units)}), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("prepare", "specs", "preflight", "run"), required=True)
    parser.add_argument("--only", help="run: unit id prefix")
    args = parser.parse_args()
    if args.action == "run":
        run(only=args.only)
    else:
        {"prepare": prepare, "specs": specs, "preflight": preflight}[args.action]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
