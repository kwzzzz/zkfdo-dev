#!/usr/bin/env python3
"""Route B6b hint files and instance stores to the external J volume.

The fixed engine still receives its ordinary request arguments. It requires a
new output directory, so its temporary output is placed on the external J
volume; after exit, result.json is copied to runs/ while raw/ stays external.
The instance store stays external and the runner state stays under runs/.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

import run_n6_j1 as runner


VOLUME = Path("/Volumes/zkfdo-jcache")
EXTERNAL = VOLUME / "n6-b6b-batch1x"


def require_external_root(path: Path) -> Path:
    runner.require(os.path.ismount(VOLUME), "B6b J volume is not mounted")
    resolved = path.resolve()
    runner.require(resolved.is_relative_to(EXTERNAL) and resolved != EXTERNAL,
                   "B6b J path is outside the dedicated external folder")
    resolved.mkdir(parents=True, exist_ok=True)
    runner.require(resolved.is_dir(), "B6b J external directory unavailable")
    runner.require(runner.disk_free(resolved) >= runner.MIN_FREE_BYTES,
                   "B6b J external disk free below 40 GiB")
    return resolved


def external_lift_output(output_dir: Path, output_root: Path,
                         workspace_root: Path) -> Path:
    """Give the fixed engine a new external output path.

    The engine refuses an existing --output directory, so an advance symlink
    from the runs tree cannot work. Its raw/ tree is created at this path.
    """
    runner.require(not output_dir.exists() and output_dir.is_relative_to(output_root),
                   "B6b lift output must be new and below runs output")
    relative = output_dir.relative_to(output_root)
    require_external_root(workspace_root)
    external_output = workspace_root / relative
    runner.require(not external_output.exists(), "B6b hint workspace already exists")
    external_output.parent.mkdir(parents=True, exist_ok=True)
    return external_output


def publish_lift_output(external_output: Path, output_dir: Path,
                        output_root: Path, workspace_root: Path) -> None:
    """Copy the small result into runs and leave the raw workspace external."""
    runner.require(output_dir.is_relative_to(output_root) and
                   external_output == workspace_root / output_dir.relative_to(output_root) and
                   not output_dir.exists(), "B6b lift publishing path differs")
    runner.require(external_output.is_dir(), "B6b external lift output missing")
    output_dir.mkdir(parents=True, exist_ok=False)
    result = external_output / "result.json"
    if result.is_file():
        with result.open("rb") as source, (output_dir / "result.json").open("xb") as target:
            shutil.copyfileobj(source, target)
        runner.require(runner.sha256(result) == runner.sha256(output_dir / "result.json"),
                       "B6b copied result SHA-256 differs")
        result.unlink()
    raw = external_output / "raw"
    if raw.is_dir():
        (output_dir / "raw").symlink_to(raw, target_is_directory=True)


def external_store(store: Path, output_root: Path, instance_root: Path) -> Path:
    runner.require(store.is_relative_to(output_root),
                   "B6b instance store is not below runs output")
    require_external_root(instance_root)
    selected = instance_root / store.relative_to(output_root)
    runner.require(selected.resolve().is_relative_to(instance_root),
                   "B6b instance store escaped external root")
    selected.parent.mkdir(parents=True, exist_ok=True)
    return selected


def install_full(output_root: Path, workspace_root: Path,
                 instance_root: Path) -> None:
    """Patch the existing J runner's I/O routes, leaving its decisions intact."""
    output_root = output_root.resolve()
    workspace_root = require_external_root(workspace_root)
    instance_root = require_external_root(instance_root)
    original_atomic_json = runner.atomic_json

    def state_with_external_store(path: Path, value: dict[str, Any]) -> None:
        if path == output_root / "state.json":
            for revision in value.get("revisions", {}).values():
                recorded = revision.get("instance_store")
                if isinstance(recorded, str):
                    old = Path(recorded)
                    if old.is_relative_to(output_root):
                        revision["instance_store"] = str(
                            instance_root / old.relative_to(output_root))
        original_atomic_json(path, value)

    def run_lift(row: dict[str, Any], output_dir: Path, cache: Path,
                 store: Path, attempt: int, measurement_method: str) -> dict[str, Any]:
        runner.require(measurement_method in {"time-l", "wait4"},
                       "unknown measurement method")
        runner.check_disk(workspace_root, instance_root)
        external_output = external_lift_output(output_dir, output_root, workspace_root)
        routed_store = external_store(store, output_root, instance_root)
        prefix = output_dir.parent / f"attempt-{attempt:04d}"
        stdout_path = Path(str(prefix) + ".stdout.log")
        stderr_path = Path(str(prefix) + ".stderr.log")
        command = [str(runner.ENGINE), "experiment", "lift",
                   "--request", row["request"], "--output", str(external_output),
                   "--cache", str(cache), "--circom-bin", str(runner.CIRCOM),
                   "--instance-store", str(routed_store)]
        try:
            if measurement_method == "wait4":
                metrics = runner.run_with_rusage(command, stdout_path, stderr_path)
            else:
                started = time.monotonic()
                with stdout_path.open("x") as stdout, stderr_path.open("x") as stderr:
                    process = subprocess.run([str(runner.TIME_BIN), "-l", *command],
                                             stdout=stdout, stderr=stderr, check=False)
                metrics = {"exit_code": process.returncode,
                           "wall_seconds": time.monotonic() - started,
                           "max_rss_bytes": runner.max_rss_bytes(stderr_path)}
        finally:
            if external_output.is_dir():
                publish_lift_output(external_output, output_dir, output_root,
                                    workspace_root)
            elif not output_dir.exists():
                output_dir.mkdir(parents=True, exist_ok=False)
        return {**metrics, "measurement_method": measurement_method,
                "stdout_path": str(stdout_path), "stderr_path": str(stderr_path)}

    runner.atomic_json = state_with_external_store
    runner.run_lift = run_lift
