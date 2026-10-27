#!/usr/bin/env python3
"""A-only constructed input checks; no candidate or judging data access.

The existing checker functions are unchanged. Only the unrelated B-state
guard and storage destinations are adapted. All large artifacts stay on SSD.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a-remeasure-2026-10-25.noindex"
CACHE = Path("/Volumes/zkfdo-jcache/n6-a-remeasure-aq")
MANIFEST = ROOT / "runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json"
REFERENCE = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
MANIFEST_SHA = "f059fe7d6aa21234168b7867537f069ec980c45c2c025184cbc12e169f687441"
REFERENCE_SHA = "18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508"
WORK_CAP_SECONDS = 10800
REVISIONS = (
    "aq-006-1680f955c185", "aq-007-0bb83f9eab0f", "aq-008-9c9e702d061d",
    "aq-011-93343c3cd34c", "aq-025-70328d3fd35e", "aq-026-2bcd7ed6110f",
    "aq-012-44d0df2ab46e", "aq-016-0a7d49b1c135", "aq-024-6f6781246415",
    "aq-017-9703bbce0c43", "aq-040-da54d3e7bc8a", "aq-037-94fe3080fc18",
    "aq-039-0ad3923f2f5b",
)


class WorkBudget:
    """Track this check against the revision's remaining wall-time budget."""

    def __init__(self, elapsed: float):
        if not math.isfinite(elapsed) or elapsed < 0:
            raise RuntimeError("invalid revision work-start time")
        self.initial_elapsed = elapsed
        self.started = time.monotonic()
        self.deadline = self.started + WORK_CAP_SECONDS - elapsed
        self.timeout(WORK_CAP_SECONDS)

    def timeout(self, maximum: float) -> float:
        remaining = self.deadline - time.monotonic()
        # The unchanged run_quiet function rounds child timeouts up to one second.
        # Do not launch a new child if that minimum cannot fit the work budget.
        if remaining < 1:
            raise RuntimeError("revision 3-hour work cap reached")
        return min(maximum, remaining)

    def elapsed(self) -> float:
        return self.initial_elapsed + time.monotonic() - self.started


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fixed_json(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def begin(revision: str) -> dict:
    folder = RUN / "inputs" / revision
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "work-start.json"
    if not path.exists():
        fixed_json(path, {"revision_id": revision, "budget_seconds": WORK_CAP_SECONDS,
                          "started_at": datetime.now(timezone.utc).isoformat()})
    return json.loads(path.read_text())


def check(revision: str, input_name: str, label: str) -> int:
    import n6_b6_check_constructed_input as checker

    started = begin(revision)
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started["started_at"])).total_seconds()
    budget = WorkBudget(elapsed)
    if digest(MANIFEST) != MANIFEST_SHA or digest(REFERENCE) != REFERENCE_SHA:
        raise RuntimeError("recorded A metadata changed")
    folder = RUN / "inputs" / revision
    input_path = folder / input_name
    if input_path.parent != folder or input_path.is_symlink() or not input_path.is_file():
        raise RuntimeError("input must be a regular file directly in revision folder")
    suffix = f"-{label}" if label else ""
    external_validation = CACHE / "input-checks" / revision / f"validation{suffix}"

    def storage_guard() -> None:
        budget.timeout(WORK_CAP_SECONDS)
        if not os.path.ismount(CACHE.parent) or CACHE.resolve() != CACHE:
            raise RuntimeError("A-only external cache unavailable or redirected")
        if folder.resolve() != folder or not folder.is_relative_to(RUN):
            raise RuntimeError("A input destination redirected")

    original_validate = checker.b5.base.validate_input
    original_binary = checker.b5.base.checker_binary
    original_run_quiet = checker.b5.base.run_quiet

    def bounded_run_quiet(command, timeout, **kwargs):
        return original_run_quiet(command, budget.timeout(timeout), **kwargs)

    def external_validate(path, keys, artifacts, binary, snarkjs, attempt_dir, timeout):
        if external_validation.exists():
            raise RuntimeError("existing external validation attempt cannot be overwritten")
        return original_validate(path, keys, artifacts, binary, snarkjs,
                                 external_validation, budget.timeout(timeout))

    def shared_binary(_output):
        original_run = checker.b5.base.subprocess.run

        def bounded_build(command, **kwargs):
            kwargs["timeout"] = budget.timeout(kwargs.get("timeout", 1800))
            return original_run(command, **kwargs)

        with patch.object(checker.b5.base.subprocess, "run", bounded_build):
            return original_binary(CACHE / "shared-checker")

    arguments = [str(Path(checker.__file__)), "--scope", "A", "--identifier", revision,
                 "--input", str(input_path), "--output-root", str(RUN / "inputs"),
                 "--cache-root", str(CACHE / "input-checks"),
                 "--manifest", str(MANIFEST), "--r1cs-map", str(REFERENCE),
                 "--compile-timeout-seconds", str(budget.timeout(1800)),
                 "--validation-timeout-seconds", str(budget.timeout(3600)),
                 "--attempt-label", label]
    storage_guard()
    fixed_json(folder / f"checker-adapter{suffix}.json", {
        "schema": "n6-a-aq-checker-adapter-v1", "revision_id": revision,
        "checker_script_sha256": digest(Path(checker.__file__)),
        "adapter_script_sha256": digest(Path(__file__)),
        "scope": "A", "cache_root": str(CACHE),
        "validation_path": str(external_validation),
        "changes": ["B state guard replaced by A storage guard",
                    "validation output path on external SSD", "shared external Rust build target",
                    "shared monotonic revision deadline for each child and final acceptance"],
        "validation_functions_unchanged": True, "cargo_offline": True,
        "elapsed_work_before_check_seconds": elapsed, "work_cap_seconds": WORK_CAP_SECONDS,
    })
    with patch.object(checker, "check_heavy_idle", storage_guard), \
            patch.object(checker.b5.base, "validate_input", external_validate), \
            patch.object(checker.b5.base, "checker_binary", shared_binary), \
            patch.object(checker.b5.base, "run_quiet", bounded_run_quiet), \
            patch.object(sys, "argv", arguments), \
            patch.dict(os.environ, {"CARGO_NET_OFFLINE": "true"}):
        result = checker.main()
    check_sha = digest(folder / f"check{suffix}.json")
    finished = datetime.now(timezone.utc)
    total_elapsed = max(budget.elapsed(),
                        (finished - datetime.fromisoformat(started["started_at"])).total_seconds())
    within_work_cap = total_elapsed <= WORK_CAP_SECONDS
    adapter_result = result if within_work_cap else 1
    fixed_json(folder / f"work-end{suffix}.json", {
        "revision_id": revision, "finished_at": finished.isoformat(),
        "elapsed_work_seconds": total_elapsed, "within_work_cap": within_work_cap,
        "check_sha256": check_sha, "checker_exit_code": result,
        "adapter_exit_code": adapter_result,
    })
    return adapter_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", choices=REVISIONS, required=True)
    parser.add_argument("--action", choices=("begin", "check"), required=True)
    parser.add_argument("--input-name", default="input.json")
    parser.add_argument("--attempt-label", default="")
    args = parser.parse_args()
    if args.action == "begin":
        print(json.dumps(begin(args.revision)))
        return 0
    if args.attempt_label and not all(c.isascii() and (c.isalnum() or c in "-_")
                                      for c in args.attempt_label):
        parser.error("attempt label must contain ASCII letters, digits, hyphen or underscore")
    return check(args.revision, args.input_name, args.attempt_label)


if __name__ == "__main__":
    raise SystemExit(main())
