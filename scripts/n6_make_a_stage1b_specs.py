#!/usr/bin/env python3
"""Generate frozen N6-A1b W/S specs after supplemented preparation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import n6_prepare_b_stage1 as bspec  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a1b-2026-10-08"
PREPARATION = RUN / "preparation-summary.json"
SPECS = RUN / "specs-v2"
QUEUE = RUN / "queue-v3.json"
SEEDS = [2026100601, 2026100602, 2026100603]
ZKFUZZ = Path("/Users/miiz/.cargo/bin/zkfuzz")
CIRCOM = Path("/Users/miiz/.cargo/bin/circom")
ZKFUZZ_SHA = "ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd"
CIRCOM_SHA = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"


def sha256(path: Path) -> str:
    return bspec.sha256(path)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists() and path.read_text() != text:
        raise ValueError(f"refusing to change frozen generated file: {path}")
    path.write_text(text)


def mapped(path: Path, project: Path, workspace: str) -> str:
    try:
        relative = path.resolve().relative_to(project.resolve())
        return workspace if not relative.parts else f"{workspace}/{relative.as_posix()}"
    except ValueError:
        return str(path.resolve())


def base_spec(result: dict, plan: Path, seed: int, method: str,
              snapshots: list[dict], targets: list[dict], external: list[dict]) -> dict:
    runner = ROOT / "scripts/run_policy_a_engine_v3.py"
    return {
        "schema_version": 1,
        "campaign_id": f"N6-A1b-{result['unit_id']}-seed-{seed}-{method}",
        "method": method, "project": result["project"], "recorded_revision": result["revision"],
        "execution_sequence": "whole_then_split", "total_budget_seconds": 600,
        "attempt_cap_seconds": 600 if method == "whole" else 30,
        "initial_seed": seed, "seed_rule": "increment_per_pass", "concurrency": 1,
        "memory_cap_bytes": 10 * 1024**3, "require_save_output": False,
        "zkfuzz_output": "stderr_report", "require_pinned_command_tools": True,
        "preflight_compile_timeout_seconds": 600,
        "source_snapshots": snapshots,
        "seed_transport": {"kind": "mutation_settings", "argument": "--path_to_mutation_setting",
                           "base": {}},
        "pinned_files": [
            {"label": "plan", "path": str(plan), "sha256": sha256(plan)},
            {"label": "zkfuzz", "path": str(ZKFUZZ), "sha256": ZKFUZZ_SHA},
            {"label": "circom", "path": str(CIRCOM), "sha256": CIRCOM_SHA},
            {"label": "runner-v3", "path": str(runner), "sha256": sha256(runner)},
        ],
        "pinned_trees": [], "targets": targets, "external_include_files": external,
        "review_policy": "candidate values unopened; location/hash/report are not defect verdicts",
        "coverage_checkpoints_seconds": [600],
    }


def external_files(plan_data: dict, project: Path) -> list[dict]:
    rows: dict[str, str] = {}
    for target in plan_data["targets"]:
        for fingerprint in target.get("source_fingerprints", []):
            path = Path(fingerprint["path"])
            try:
                path.resolve().relative_to(project.resolve())
            except ValueError:
                rows[str(path.resolve())] = fingerprint["sha256"]
    return [{"path": path, "sha256": digest} for path, digest in sorted(rows.items())]


def create(result: dict, seed: int, cache: dict[Path, str]) -> tuple[Path, Path]:
    prep = RUN / "units" / result["unit_id"] / "preparation"
    plan_path = prep / "plan.json"
    plan = json.loads(plan_path.read_text())
    project = RUN / "units" / result["unit_id"] / "project"
    entrypoint = ROOT / result["condition"]["entrypoint"]
    libraries = [ROOT / path for path in result["condition"]["library_paths"]]
    if project not in cache:
        cache[project] = bspec.tree_sha256(project)
    workspace_libraries = list(dict.fromkeys(
        ["{workspace}"] + [mapped(path, project, "{workspace}") for path in libraries]))
    original_libraries = list(dict.fromkeys(str(path.resolve()) for path in libraries))
    # The original roots intentionally remain after the workspace roots even
    # when an external path appears in both groups.  B-v7 established this
    # order for snapshots whose dependency closure is outside the copy.
    whole_libraries = workspace_libraries + original_libraries
    whole_snapshot = {"id": "whole-project", "path": str(project), "tree_sha256": cache[project],
                      "candidate_globs": ["**/zkfdo_report_counterexample.json"],
                      "expected_baseline_candidates": 0}
    whole_target = {"target_id": result["unit_id"] + ":whole",
                    "source_snapshot_id": "whole-project",
                    "entrypoint_relative": entrypoint.relative_to(project).as_posix(),
                    "entrypoint_sha256": sha256(entrypoint),
                    "recorded_library_paths": [str(path) for path in libraries],
                    "command": bspec.command("{entrypoint}", whole_libraries),
                    "preflight_compile_command": bspec.compile_command("{entrypoint}", whole_libraries)}
    split_snapshots, split_targets = [], []
    for index, target in enumerate(plan["targets"]):
        entry = Path(target["run_entrypoint"])
        snapshot = bspec.sources_root(entry)
        if snapshot not in cache:
            cache[snapshot] = bspec.tree_sha256(snapshot)
        sid = f"split-{index:04d}"
        args = target["definition"].get("compile_args", [])
        recorded = [Path(args[i + 1]) for i, value in enumerate(args)
                    if value == "-l" and i + 1 < len(args)]
        split_libraries = ["{workspace}"]
        for library in recorded:
            try:
                relative = library.resolve().relative_to(snapshot.resolve())
                split_libraries.append("{workspace}" if not relative.parts else
                                       f"{{workspace}}/{relative.as_posix()}")
            except ValueError:
                split_libraries.append(str(library.resolve()))
        # Keep the workspace mapping first, then append the original compile_args
        # roots in their recorded order.  This is the B-v7 closure rule that
        # prevents a copied snapshot from silently losing an external include.
        workspace_libraries = list(dict.fromkeys(split_libraries))
        original_libraries = list(dict.fromkeys(str(path.resolve()) for path in recorded))
        split_libraries = workspace_libraries + original_libraries
        split_snapshots.append({"id": sid, "path": str(snapshot), "tree_sha256": cache[snapshot],
                                "candidate_globs": ["**/zkfdo_report_counterexample.json"],
                                "expected_baseline_candidates": 0})
        split_targets.append({"target_id": target["target_id"], "rank": target["rank"],
                              "source_snapshot_id": sid,
                              "source_snapshot_path": str(snapshot),
                              "entrypoint_relative": entry.relative_to(snapshot).as_posix(),
                              "entrypoint_sha256": sha256(entry),
                              "recorded_library_paths": [str(path) for path in recorded],
                              "command": bspec.command("{entrypoint}", split_libraries),
                              "preflight_compile_command": bspec.compile_command(
                                  "{entrypoint}", split_libraries)})
    outside = external_files(plan, project)
    stem = f"{result['unit_id']}-seed-{seed}"
    whole_path, split_path = SPECS / f"{stem}-W.json", SPECS / f"{stem}-S.json"
    write_json(whole_path, base_spec(result, plan_path, seed, "whole", [whole_snapshot],
                                     [whole_target], outside))
    write_json(split_path, base_spec(result, plan_path, seed, "split", split_snapshots,
                                     split_targets, outside))
    return whole_path, split_path


def main() -> int:
    if sha256(ZKFUZZ) != ZKFUZZ_SHA or sha256(CIRCOM) != CIRCOM_SHA:
        raise ValueError("pinned execution tool changed")
    prepared = json.loads(PREPARATION.read_text())
    successful = [row for row in prepared["units"] if row["status"] == "success"]
    cache: dict[Path, str] = {}
    units = []
    for seed in SEEDS:
        for index, row in enumerate(successful):
            whole, split = create(row, seed, cache)
            units.append({"unit_id": f"{row['unit_id']}-seed-{seed}", "identifier": row["unit_id"],
                          "target_index": index, "repository": row["project"], "seed": seed,
                          "resource_class": "normal", "whole_spec": whole.relative_to(ROOT).as_posix(),
                          "whole_spec_sha256": sha256(whole),
                          "split_spec": split.relative_to(ROOT).as_posix(),
                          "split_spec_sha256": sha256(split)})
    queue_runner = ROOT / "scripts/run_n6_a1b_queue.py"
    queue = {"schema_version": 2, "task": "N6-A1b supplemented stage1 queue",
             "status": "preflight_pending",
             "version": 3, "concurrency": 3, "minimum_free_disk_gib": 40,
             "load_sample_seconds": 10,
             "unit_count": len(units), "preflight_spec_count": len(units) * 2,
             "preflight_policy": "all specs recorded before any execute; this task stops after preflight",
             "preflight_execution": {"execute_methods": ["W", "S"],
                                     "seed_reuse_methods": ["W", "S"]},
             "unit_order": "seed order, then successful preparation-summary order; W then S",
             "queue_runner": {"path": queue_runner.relative_to(ROOT).as_posix(),
                              "sha256": sha256(queue_runner)},
             "target_list": {"path": "docs/n6_targets_a_2026-10-07.json",
                             "sha256": "6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758"},
             "units": units}
    write_json(QUEUE, queue)
    print(json.dumps({"successful_preparation_units": len(successful), "queue_units": len(units),
                      "specs": len(units) * 2, "queue": QUEUE.relative_to(ROOT).as_posix(),
                      "queue_sha256": sha256(QUEUE)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
