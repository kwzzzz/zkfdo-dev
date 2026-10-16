#!/usr/bin/env python3
"""Create N6-B1's non-evaluation 60-second inference W/S trial specs."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/n6-2026-10-06/development-trial/specs-v6"
PLAN = ROOT / "runs/dev-rq1-pilot-2026-09-29/inference-main/campaign/small-first/block-1/plan.json"
TREE = ROOT / "runs/dev-rq1-pilot-2026-09-29/inference-main/tree"
ZKFUZZ = Path("/Users/miiz/.cargo/bin/zkfuzz")
CIRCOM = Path("/Users/miiz/.cargo/bin/circom")
DEPENDENCIES = ROOT / ".external/zkbugs/dataset/circom/dependencies"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_sha(root):
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            kind, payload = b"L", path.readlink().as_posix().encode()
        elif path.is_dir():
            kind, payload = b"D", b""
        else:
            kind, payload = b"F", bytes.fromhex(sha(path))
        digest.update(kind + len(name).to_bytes(8, "big") + name)
        digest.update(len(payload).to_bytes(8, "big") + payload)
    return digest.hexdigest()


def source_root(entrypoint):
    return next(parent for parent in Path(entrypoint).parents if parent.name == "sources")


def command(entrypoint, compile_mode=False):
    command = [str(CIRCOM if compile_mode else ZKFUZZ), entrypoint]
    if compile_mode:
        command += ["--r1cs", "--output", "{compile_output}"]
    else:
        command += ["--search_mode", "ga"]
    command += ["--prime", "bn128", "-l", "{workspace}", "-l", str(DEPENDENCIES),
                "-l", str(DEPENDENCIES / "circomlib")]
    return command


def spec(method, snapshots, targets):
    runner = ROOT / "scripts/run_policy_a_engine_v3.py"
    return {"schema_version": 1, "campaign_id": f"N6-B1-development-inference-{method}-60s",
            "method": method, "project": "inference-labs-inc/subnet-2-circom",
            "recorded_revision": "d310309c141d36504b3486cebd96ed70ef3a4fdf",
            "execution_sequence": "whole_then_split", "total_budget_seconds": 60,
            "attempt_cap_seconds": 60 if method == "whole" else 30,
            "initial_seed": 2026100601, "seed_rule": "increment_per_pass", "concurrency": 1,
            "memory_cap_bytes": 10 * 1024**3, "require_save_output": False,
            "zkfuzz_output": "stderr_report", "require_pinned_command_tools": True,
            "preflight_compile_timeout_seconds": 600, "source_snapshots": snapshots,
            "seed_transport": {"kind": "mutation_settings",
                               "argument": "--path_to_mutation_setting", "base": {}},
            "pinned_files": [
                {"label": "plan", "path": str(PLAN), "sha256": sha(PLAN)},
                {"label": "zkfuzz", "path": str(ZKFUZZ), "sha256": sha(ZKFUZZ)},
                {"label": "circom", "path": str(CIRCOM), "sha256": sha(CIRCOM)},
                {"label": "runner-v3", "path": str(runner), "sha256": sha(runner)}],
            "pinned_trees": [{"label": "zkbugs-circom-dependencies", "path": str(DEPENDENCIES),
                              "tree_sha256": tree_sha(DEPENDENCIES)}],
            "targets": targets, "review_policy": "development trial; candidates unopened"}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def main():
    plan = json.loads(PLAN.read_text())
    whole_snapshot = [{"id": "whole", "path": str(TREE), "tree_sha256": tree_sha(TREE),
                       "candidate_globs": ["**/zkfdo_report_counterexample.json"],
                       "expected_baseline_candidates": 0}]
    entrypoint = TREE / "src/circuit.circom"
    whole_target = [{"target_id": "inference-main", "source_snapshot_id": "whole",
                     "entrypoint_relative": "src/circuit.circom", "entrypoint_sha256": sha(entrypoint),
                     "command": command("{entrypoint}"),
                     "preflight_compile_command": command("{entrypoint}", True)}]
    snapshots, targets = [], []
    for index, row in enumerate(plan["targets"]):
        entrypoint = Path(row["run_entrypoint"])
        root = source_root(entrypoint)
        identifier = f"split-{index:02d}"
        snapshots.append({"id": identifier, "path": str(root), "tree_sha256": tree_sha(root),
                          "candidate_globs": ["**/zkfdo_report_counterexample.json"],
                          "expected_baseline_candidates": 0})
        targets.append({"target_id": row["target_id"], "rank": row["rank"],
                        "source_snapshot_id": identifier, "source_snapshot_path": str(root),
                        "entrypoint_relative": entrypoint.relative_to(root).as_posix(),
                        "entrypoint_sha256": sha(entrypoint), "command": command("{entrypoint}"),
                        "preflight_compile_command": command("{entrypoint}", True)})
    write(OUT / "whole.json", spec("whole", whole_snapshot, whole_target))
    write(OUT / "split.json", spec("split", snapshots, targets))
    print(json.dumps({"whole": sha(OUT / "whole.json"), "split": sha(OUT / "split.json")}))


if __name__ == "__main__":
    main()
