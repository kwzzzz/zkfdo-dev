#!/usr/bin/env python3
"""Human-run B6d wait4 format pilot for the original queue 9 and 25 pair.

The B5 format checks and fixed engine are unchanged. This adapter supplies
B6d's unit/index/equivalence gates and external hint workspace paths. It is
prepared but not executed during preparation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import n6_b5_format_pilot as original
import n6_b6d_j_runner as b6d
import n6_b6b_runtime_paths as paths
import n6_j3_b_pilot_wait4 as selection
import run_n6_j1 as runner


def run_pilot(args: argparse.Namespace) -> None:
    index = b6d.configure(args.engine, args.index, args.index_sha256,
                          args.static_preflight, args.static_preflight_sha256,
                          args.first_lead_review_sha256,
                          args.second_lead_review_sha256)
    base = b6d.b6.base_index()
    chosen = selection.select_requests(index, base)
    runner.require([row["queue_order"] for row in chosen] == [9, 25] and
                   all(row["preparation_failure"] is None for row in chosen),
                   "B6d pilot is not original max/min queue 9 and 25")
    expected = {"schema_version": 1,
                "requests": original.selected_ids(chosen)}
    runner.checked_sha(args.selection, args.selection_sha256,
                       "B6d pilot selection")
    runner.require(json.loads(args.selection.read_text()) == expected,
                   "B6d pilot selection differs from original rule")
    runner.require(args.cache_root == b6d.CACHE / f"pilot-{args.engine}" and
                   args.output == b6d.OUT / f"pilot-{args.engine}.noindex" and
                   args.workspace_root == b6d.WORKSPACES and
                   args.instance_root == b6d.STORES,
                   "B6d pilot paths differ from prepared new paths")
    paths.EXTERNAL = b6d.EXTERNAL
    workspace_root = paths.require_external_root(args.workspace_root)
    instance_root = paths.require_external_root(args.instance_root)
    paths.require_external_root(args.cache_root.parent)
    runner.require(not args.output.exists() and not args.cache_root.exists(),
                   "B6d pilot output/cache already exists")

    def run_lift(row: dict[str, Any], run_dir: Path, cache: Path,
                 store: Path) -> dict[str, Any]:
        runner.checked_sha(runner.ENGINE, runner.ENGINE_SHA256,
                           "locked B6d pilot engine")
        runner.check_disk(workspace_root, instance_root)
        run_dir.mkdir(parents=True, exist_ok=False)
        target = run_dir / "lift"
        external_output = paths.external_lift_output(target, args.output,
                                                     workspace_root)
        routed_store = paths.external_store(store, args.output, instance_root)
        command = [str(runner.ENGINE), "experiment", "lift",
                   "--request", row["request"], "--cache", str(cache),
                   "--circom-bin", str(runner.CIRCOM),
                   "--instance-store", str(routed_store),
                   "--output", str(external_output)]
        try:
            metrics = original.run_quiet_wait4(command, run_dir / "lift.stderr.log")
        finally:
            if external_output.is_dir():
                paths.publish_lift_output(external_output, target,
                                          args.output, workspace_root)
            elif not target.exists():
                target.mkdir(parents=True, exist_ok=False)
        result_path = target / "result.json"
        return {**metrics,
                "result_path": str(result_path) if result_path.is_file() else None}

    original.run_lift = run_lift
    original.run_format_pilot(args.index, args.index_sha256,
                              b6d.b6.BASE, runner.sha256(b6d.b6.BASE),
                              args.selection, args.cache_root, args.output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("v1", "v2.2"), required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--static-preflight", type=Path, required=True)
    parser.add_argument("--static-preflight-sha256", required=True)
    parser.add_argument("--first-lead-review-sha256", required=True)
    parser.add_argument("--second-lead-review-sha256", required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--instance-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--action", choices=("execute",), required=True)
    args = parser.parse_args(argv)
    try:
        run_pilot(args)
        print("pilot: exit_code=0 format_ok=1", flush=True)
        return 0
    except (OSError, ValueError, runner.RunnerError, json.JSONDecodeError) as error:
        print(f"pilot: exit_code=2 format_ok=0 ({error})", file=sys.stderr,
              flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
