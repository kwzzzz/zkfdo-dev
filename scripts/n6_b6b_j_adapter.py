#!/usr/bin/env python3
"""Use B6b staged sources with the unchanged B5 J adapter and format pilot."""

from __future__ import annotations

import argparse
from pathlib import Path

import n6_b5_j_adapter as b5
import n6_b6b_j_source_bindings as staged
import run_n6_j1 as runner


DEFAULT_STAGING_ROOT = Path("/Volumes/zkfdo-jcache/n6-b6b-batch1x/source-staging")


def engine_for_prepared_index(index: Path) -> str:
    import n6_b6b_batch1x_prepare as prep

    selected = index.resolve()
    if selected == prep.INDEX_V1.resolve():
        return "v1"
    if selected == prep.INDEX_V22.resolve():
        return "v2.2"
    raise ValueError("B6b J index is not the prepared version")


def guarded_execution(engine: str, index: Path, *, full: bool) -> None:
    """Require completed value-free B6b gates even for a direct adapter call."""
    import n6_b6b_batch1x_prepare as prep

    expected_index = prep.INDEX_V22 if engine == "v2.2" else prep.INDEX_V1
    prep.require(index.resolve() == expected_index.resolve(),
                 "B6b J index is not the prepared version")
    prep.verify_preflight_gate()
    index_stage = "index-recovered" if prep.state_path("index-recovered").is_file() else "index"
    for name in (index_stage, "validate-v2.2", "validate-v1", "pilot-selection"):
        state = prep.read_json(prep.state_path(name))
        prep.require(state.get("status") == "completed" and state.get("exit_code") == 0,
                     f"B6b {name} gate is incomplete")
        if name == index_stage:
            current = prep.index_summary()
            prep.require(all(state.get(key) == value for key, value in current.items()),
                         "B6b request index gate changed")
        elif name == "validate-v2.2":
            prep.verify_validate(state, prep.INDEX_V22)
        elif name == "validate-v1":
            prep.verify_validate(state, prep.INDEX_V1)
        else:
            prep.verify_selection(state)
    prep.verify_static_gate()
    prep.r1cs_gate()
    if full:
        for pilot_engine, pilot_index in (("v2.2", prep.INDEX_V22),
                                          ("v1", prep.INDEX_V1)):
            state = prep.read_json(prep.state_path(f"pilot-{pilot_engine}"))
            prep.require(state.get("status") == "completed" and
                         state.get("exit_code") == 0,
                         "both B6b format pilots must pass before full J")
            prep.verify_pilot(state, pilot_engine, pilot_index)


def verify_execution_paths(stage: str, engine: str, *, staging_root: Path,
                           workspace_root: Path | None, instance_root: Path | None,
                           cache_root: Path | None, output: Path | None) -> None:
    """Bind a direct J call to the paths covered by the static preflight."""
    import n6_b6b_batch1x_prepare as prep

    label = "pilot" if stage == "pilot" else "full"
    expected = {
        "source staging": prep.STAGING,
        "hint workspace": prep.WORKSPACES,
        "instance store": prep.STORES,
        "cache": prep.CACHE / f"{label}-{engine}",
        "output": prep.OUT / f"{label}-{engine}.noindex",
    }
    supplied = {"source staging": staging_root, "hint workspace": workspace_root,
                "instance store": instance_root, "cache": cache_root,
                "output": output}
    for name, path in supplied.items():
        target = expected[name]
        prep.require(path is not None and path.is_absolute() and
                     path.resolve() == target and target.resolve() == target,
                     f"B6b {name} differs from the prepared {label} path")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-staging-root", type=Path,
                        default=DEFAULT_STAGING_ROOT)
    parser.add_argument("--stage", choices=("requests", "validate", "pilot"), required=True)
    parser.add_argument("--engine", choices=("v1", "v2.2"), default="v1")
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--instance-root", type=Path)
    args, rest = parser.parse_known_args(argv)
    staged.install(args.source_staging_root)
    forwarded = ["--stage", args.stage, "--engine", args.engine, *rest]
    if args.stage == "requests":
        forwarded.extend(("--source-staging-root", str(args.source_staging_root)))
    if args.stage != "pilot":
        if args.stage == "validate":
            execution = argparse.ArgumentParser(add_help=False)
            execution.add_argument("--action", choices=("validate-only", "execute"))
            execution.add_argument("--output", type=Path)
            execution.add_argument("--index", type=Path)
            execution.add_argument("--cache-root", type=Path)
            execution_args, _unknown = execution.parse_known_args(rest)
            if execution_args.action == "execute":
                if (execution_args.output is None or args.workspace_root is None or
                        args.instance_root is None or execution_args.index is None):
                    raise ValueError("B6b full J requires output, workspace and instance roots")
                guarded_execution(args.engine, execution_args.index, full=True)
                verify_execution_paths(
                    "full", args.engine, staging_root=args.source_staging_root,
                    workspace_root=args.workspace_root, instance_root=args.instance_root,
                    cache_root=execution_args.cache_root, output=execution_args.output)
                import n6_b6b_runtime_paths as paths

                paths.install_full(execution_args.output, args.workspace_root,
                                   args.instance_root)
        return b5.main(forwarded)
    b5.verify_mem20()
    if runner.ENGINE != b5.ENGINE_V1 or runner.ENGINE_SHA256 != b5.ENGINE_V1_SHA:
        raise ValueError("v1 runner lock differs from N5")
    runner.checked_sha(b5.ENGINE_V1, b5.ENGINE_V1_SHA, "v1 J binary")
    if args.engine == "v2.2":
        runner.checked_sha(b5.ENGINE_V22, b5.ENGINE_V22_SHA, "v2.2 J binary")
        runner.ENGINE = b5.ENGINE_V22
        runner.ENGINE_SHA256 = b5.ENGINE_V22_SHA
    import n6_b6b_format_pilot as pilot

    if args.workspace_root is None or args.instance_root is None:
        raise ValueError("B6b pilot requires workspace and instance roots")
    pilot_args = argparse.ArgumentParser(add_help=False)
    pilot_args.add_argument("--index", type=Path, required=True)
    pilot_args.add_argument("--cache-root", type=Path, required=True)
    pilot_args.add_argument("--output", type=Path, required=True)
    parsed, _unknown = pilot_args.parse_known_args(rest)
    guarded_execution(args.engine, parsed.index, full=False)
    verify_execution_paths(
        "pilot", args.engine, staging_root=args.source_staging_root,
        workspace_root=args.workspace_root, instance_root=args.instance_root,
        cache_root=parsed.cache_root, output=parsed.output)
    return pilot.main([*rest, "--workspace-root", str(args.workspace_root),
                       "--instance-root", str(args.instance_root)])


if __name__ == "__main__":
    raise SystemExit(main())
