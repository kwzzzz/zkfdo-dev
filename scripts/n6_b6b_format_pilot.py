#!/usr/bin/env python3
"""Run the unchanged B5 format gate with B6b external workspace paths.

Only miiz runs this entry point after the new request and static preparation
gates. The result-shape and instance-shape checks are imported unchanged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import n6_b5_format_pilot as original
import n6_b6b_j_adapter as adapter
import n6_b6b_runtime_paths as paths
import n6_j3_b_pilot_wait4 as b_selection
import run_n6_j1 as runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--base-index", type=Path, required=True)
    parser.add_argument("--base-index-sha256", required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--instance-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--action", choices=("execute",), required=True)
    args = parser.parse_args(argv)
    engine = adapter.engine_for_prepared_index(args.index)
    adapter.guarded_execution(engine, args.index, full=False)
    adapter.verify_execution_paths(
        "pilot", engine, staging_root=adapter.DEFAULT_STAGING_ROOT,
        workspace_root=args.workspace_root, instance_root=args.instance_root,
        cache_root=args.cache_root, output=args.output)
    expected_engine = (adapter.b5.ENGINE_V22 if engine == "v2.2" else
                       adapter.b5.ENGINE_V1)
    expected_sha = (adapter.b5.ENGINE_V22_SHA if engine == "v2.2" else
                    adapter.b5.ENGINE_V1_SHA)
    runner.require(runner.ENGINE == expected_engine and
                   runner.ENGINE_SHA256 == expected_sha,
                   "B6b pilot engine differs from its prepared request index")
    output = args.output.resolve()
    workspace_root = paths.require_external_root(args.workspace_root)
    instance_root = paths.require_external_root(args.instance_root)
    # The unchanged B5 gate creates this directory exclusively after checking
    # that it does not exist. Check its parent without creating the cache root.
    paths.require_external_root(args.cache_root.parent)
    runner.preflight_libraries = b_selection.preflight_libraries

    def run_lift(row: dict[str, Any], run_dir: Path, cache: Path,
                 store: Path) -> dict[str, Any]:
        runner.checked_sha(runner.ENGINE, runner.ENGINE_SHA256, "locked J engine")
        runner.check_disk(workspace_root, instance_root)
        run_dir.mkdir(parents=True, exist_ok=False)
        target = run_dir / "lift"
        external_output = paths.external_lift_output(target, output, workspace_root)
        routed_store = paths.external_store(store, output, instance_root)
        command = [str(runner.ENGINE), "experiment", "lift",
                   "--request", row["request"], "--cache", str(cache),
                   "--circom-bin", str(runner.CIRCOM),
                   "--instance-store", str(routed_store),
                   "--output", str(external_output)]
        try:
            metrics = original.run_quiet_wait4(command, run_dir / "lift.stderr.log")
        finally:
            if external_output.is_dir():
                paths.publish_lift_output(external_output, target, output, workspace_root)
            elif not target.exists():
                target.mkdir(parents=True, exist_ok=False)
        result_path = target / "result.json"
        return {**metrics,
                "result_path": str(result_path) if result_path.is_file() else None}

    original.run_lift = run_lift
    try:
        original.run_format_pilot(
            args.index.resolve(), args.index_sha256,
            args.base_index.resolve(), args.base_index_sha256,
            args.selection.resolve(), args.cache_root.resolve(), output)
        print("pilot: exit_code=0 format_ok=1", flush=True)
        return 0
    except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError):
        print("pilot: exit_code=2 format_ok=0", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
