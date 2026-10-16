#!/usr/bin/env python3
"""Generate N6-B stage-1 v7 specs and two-stage queue without running zkFuzz."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "docs/n6_targets_b_2026-10-06.json"
RUN = ROOT / "runs/n6-2026-10-06"
SPECS = RUN / "specs-v7"
SEEDS = [2026100601, 2026100602, 2026100603]
ZKFUZZ = Path("/Users/miiz/.cargo/bin/zkfuzz")
CIRCOM = Path("/Users/miiz/.cargo/bin/circom")
ZKFUZZ_SHA = "ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd"
CIRCOM_SHA = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            kind, payload = b"L", path.readlink().as_posix().encode()
        elif path.is_dir():
            kind, payload = b"D", b""
        elif path.is_file():
            kind, payload = b"F", bytes.fromhex(sha256(path))
        else:
            raise ValueError(f"unsupported source node: {path}")
        digest.update(kind + len(relative).to_bytes(8, "big") + relative)
        digest.update(len(payload).to_bytes(8, "big") + payload)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists() and path.read_text() != data:
        raise ValueError(f"refusing to change frozen generated file: {path}")
    path.write_text(data)


def sources_root(entrypoint: Path) -> Path:
    for parent in entrypoint.parents:
        if parent.name == "sources":
            return parent
    raise ValueError(f"prepared entrypoint is not below sources/: {entrypoint}")


def mapped_library_argument(path: Path, workspace: str, snapshot: Path,
                            project_root: Path | None) -> str:
    if project_root is not None:
        try:
            relative = path.relative_to(project_root)
            return workspace if not relative.parts else f"{workspace}/{relative.as_posix()}"
        except ValueError:
            pass
    try:
        relative = path.relative_to(ROOT / "runs")
    except ValueError:
        try:
            relative = path.relative_to(ROOT)
        except ValueError as error:
            raise ValueError(f"library path is outside the recorded workspace: {path}") from error
    # Preserve the full recorded -l list. A target snapshot intentionally contains only its
    # dependency closure, so an unused recorded directory may be absent while the original
    # search-order entry remains part of the execution condition.
    return f"{workspace}/{relative.as_posix()}"


def command(entrypoint: str, libraries: list[str]) -> list[str]:
    argv = [str(ZKFUZZ), entrypoint, "--prime", "bn128", "--search_mode", "ga"]
    for library in libraries:
        argv += ["-l", library]
    return argv


def compile_command(entrypoint: str, libraries: list[str]) -> list[str]:
    argv = [str(CIRCOM), entrypoint, "--r1cs", "--prime", "bn128",
            "--output", "{compile_output}"]
    for library in libraries:
        argv += ["-l", library]
    return argv


def base_spec(item: dict[str, Any], plan_path: Path, seed: int, method: str,
              snapshots: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, Any]:
    runner = ROOT / "scripts/run_policy_a_engine_v3.py"
    return {
        "schema_version": 1,
        "campaign_id": f"N6-B-stage1-{item['identifier']}-seed-{seed}-{method}",
        "method": method, "project": item["repository"], "recorded_revision": item["commit"],
        "execution_sequence": "whole_then_split", "total_budget_seconds": 3600,
        "attempt_cap_seconds": 3600 if method == "whole" else 30,
        "initial_seed": seed, "seed_rule": "increment_per_pass", "concurrency": 1,
        "memory_cap_bytes": 10 * 1024**3, "require_save_output": False,
        "zkfuzz_output": "stderr_report", "require_pinned_command_tools": True,
        "preflight_compile_timeout_seconds": 600,
        "source_snapshots": snapshots, "seed_transport": {
            "kind": "mutation_settings", "argument": "--path_to_mutation_setting", "base": {}},
        "pinned_files": [
            {"label": "plan", "path": str(plan_path), "sha256": sha256(plan_path)},
            {"label": "zkfuzz", "path": str(ZKFUZZ), "sha256": ZKFUZZ_SHA},
            {"label": "circom", "path": str(CIRCOM), "sha256": CIRCOM_SHA},
            {"label": "runner-v3", "path": str(runner), "sha256": sha256(runner)},
        ],
        "pinned_trees": [], "targets": targets,
        "review_policy": "candidate values unopened; location/hash/report are not defect verdicts",
        "coverage_checkpoints_seconds": [600, 3600],
    }


def create_specs(item: dict[str, Any], seed: int, cache: dict[Path, str]) -> tuple[Path, Path]:
    plan_path = ROOT / item["plan"]["path"]
    if sha256(plan_path) != item["plan"]["sha256"]:
        raise ValueError(f"plan hash changed: {plan_path}")
    plan = json.loads(plan_path.read_text())
    if not plan["targets"]:
        raise ValueError(f"empty eligible plan: {item['identifier']}")
    project_root = Path(plan["targets"][0]["definition"]["project_root"])
    relative_entrypoint = item["entrypoint_key"].removeprefix("source_main:")
    whole_entrypoint = project_root / relative_entrypoint
    if not whole_entrypoint.is_file():
        raise ValueError(f"whole entrypoint absent: {whole_entrypoint}")
    compile_args = plan["targets"][0]["definition"].get("compile_args", [])
    recorded_libraries = [Path(compile_args[index + 1]) for index, value in enumerate(compile_args)
                          if value == "-l" and index + 1 < len(compile_args)]
    whole_libraries = [mapped_library_argument(path, "{workspace}", project_root, project_root)
                       for path in recorded_libraries]
    if "{workspace}" not in whole_libraries:
        whole_libraries.insert(0, "{workspace}")
    if project_root not in cache:
        cache[project_root] = tree_sha256(project_root)
    whole_snapshot = {"id": "whole-project", "path": str(project_root),
                      "tree_sha256": cache[project_root],
                      "candidate_globs": ["**/zkfdo_report_counterexample.json"],
                      "expected_baseline_candidates": 0}
    whole_target = {"target_id": item["identifier"] + ":whole", "source_snapshot_id": "whole-project",
                    "entrypoint_relative": relative_entrypoint,
                    "entrypoint_sha256": sha256(whole_entrypoint),
                    "recorded_library_paths": [str(path) for path in recorded_libraries],
                    "command": command("{entrypoint}", whole_libraries),
                    "preflight_compile_command": compile_command("{entrypoint}", whole_libraries)}

    split_snapshots, split_targets = [], []
    for index, planned in enumerate(plan["targets"]):
        entrypoint = Path(planned["run_entrypoint"])
        snapshot = sources_root(entrypoint)
        snapshot_id = f"split-{index:04d}"
        if snapshot not in cache:
            cache[snapshot] = tree_sha256(snapshot)
        target_compile_args = planned["definition"].get("compile_args", [])
        target_recorded_libraries = [
            Path(target_compile_args[arg_index + 1])
            for arg_index, value in enumerate(target_compile_args)
            if value == "-l" and arg_index + 1 < len(target_compile_args)
        ]
        workspace_libraries = [mapped_library_argument(path, "{workspace}", snapshot, None)
                               for path in target_recorded_libraries]
        if "{workspace}" not in workspace_libraries:
            workspace_libraries.insert(0, "{workspace}")
        # v7 preserves the v6 workspace search list as an exact prefix, then appends the
        # preparation plan's original absolute -l list in its recorded order.  Root-unit
        # snapshots can contain a dependency while losing the original library-root layout.
        libraries = workspace_libraries + [str(path) for path in target_recorded_libraries]
        split_snapshots.append({"id": snapshot_id, "path": str(snapshot),
                                "tree_sha256": cache[snapshot],
                                "candidate_globs": ["**/zkfdo_report_counterexample.json"],
                                "expected_baseline_candidates": 0})
        split_targets.append({"target_id": planned["target_id"], "rank": planned["rank"],
                              "source_snapshot_id": snapshot_id,
                              "source_snapshot_path": str(snapshot),
                              "entrypoint_relative": entrypoint.relative_to(snapshot).as_posix(),
                              "entrypoint_sha256": sha256(entrypoint),
                              "recorded_library_paths": [str(path)
                                                         for path in target_recorded_libraries],
                              "workspace_library_paths": workspace_libraries,
                              "appended_original_library_paths": [
                                  str(path) for path in target_recorded_libraries],
                              "command": command("{entrypoint}", libraries),
                              "preflight_compile_command": compile_command("{entrypoint}", libraries)})
    stem = f"{item['identifier']}-seed-{seed}"
    whole_path, split_path = SPECS / f"{stem}-W.json", SPECS / f"{stem}-S.json"
    write_json(whole_path, base_spec(item, plan_path, seed, "whole", [whole_snapshot], [whole_target]))
    write_json(split_path, base_spec(item, plan_path, seed, "split", split_snapshots, split_targets))
    return whole_path, split_path


def main() -> int:
    data = json.loads(TARGETS.read_text())
    expected = "853eef3b91698ea4f6c8e9189e0bfb765b697d7f6a505800cb7e42644d07dca6"
    if sha256(TARGETS) != expected or len(data["stage1"]) != 10:
        raise ValueError("frozen B target list changed")
    if sha256(ZKFUZZ) != ZKFUZZ_SHA or sha256(CIRCOM) != CIRCOM_SHA:
        raise ValueError("pinned execution tools changed")
    cache: dict[Path, str] = {}
    units = []
    # Fixed round-robin by seed, then frozen stage-1 order. The explicit resource class is also
    # enforced by the queue runner, so duration variation cannot overlap the two very-large units.
    for seed in SEEDS:
        for target_index, item in enumerate(data["stage1"]):
            whole, split = create_specs(item, seed, cache)
            units.append({"unit_id": f"{item['identifier']}-seed-{seed}",
                          "target_index": target_index, "identifier": item["identifier"],
                          "repository": item["repository"], "entrypoint_key": item["entrypoint_key"],
                          "constraints": item["constraints"], "seed": seed,
                          "resource_class": "million_plus" if item["constraints"] >= 1_000_000 else "normal",
                          "whole_spec": str(whole.relative_to(ROOT)),
                          "whole_spec_sha256": sha256(whole),
                          "split_spec": str(split.relative_to(ROOT)),
                          "split_spec_sha256": sha256(split)})
    queue_runner = ROOT / "scripts/run_n6_b_queue.py"
    v6_queue = RUN / "queue-v6.json"
    v6_summary = RUN / "stage1-v6/preflight-all.json"
    queue = {"schema_version": 2, "task": "N6-B stage1 queue", "status": "preflight_pending",
             "concurrency": 3, "minimum_free_disk_gib": 35, "load_sample_seconds": 10,
             "preflight_spec_count": 60,
             "preflight_policy": "all 60 spec preflights must be recorded before execute; execute never compiles preflight artifacts",
             "preflight_execution": {
                 "execute_methods": ["S"], "seed_reuse_methods": [],
                 "exact_reuse": {"method": "W",
                                 "source_queue": str(v6_queue.relative_to(ROOT)),
                                 "source_queue_sha256": sha256(v6_queue),
                                 "source_summary": str(v6_summary.relative_to(ROOT)),
                                 "source_summary_sha256": sha256(v6_summary)}},
             "unit_order": "seed order, then frozen stage1 order; W then S within unit",
             "large_unit_rule": "at most one million_plus unit runs; skip a waiting million_plus unit and start the next normal unit",
             "queue_runner": {"path": str(queue_runner.relative_to(ROOT)),
                              "sha256": sha256(queue_runner)},
             "target_list": {"path": str(TARGETS.relative_to(ROOT)), "sha256": expected},
             "units": units}
    write_json(RUN / "queue-v7.json", queue)
    print(json.dumps({"units": len(units), "specs": len(units) * 2,
                      "queue": str(RUN / "queue-v7.json"), "tree_hashes": len(cache)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
