#!/usr/bin/env python3
"""Policy-A engine v2: the v1 engine (unchanged, hash-pinned by the A-02 SCOPE) plus a mode
that keeps zkFuzz's violated-condition string and links it to the candidate.

zkFuzz prints the condition string only in its stderr report, which it skips when it writes a
JSON candidate (`--save_output`); see `zkfuzz_report.py`. With `"zkfuzz_output":
"stderr_report"` in the spec, commands must not request `--save_output`. After each attempt the
report in the attempt's stderr log (always saved by v1) becomes `zkfdo_report_counterexample.json`
in the attempt workspace, where v1's candidate inventory preserves it like any other candidate.
The file carries the condition text and the log's path and SHA-256; `report_link.json` in the
attempt directory records the link without values. The default mode (`"save_output"`) behaves
exactly like v1 and records that the condition text is unavailable.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Callable

HERE = Path(__file__).resolve().parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v1 = _load("run_policy_a_engine", "run_policy_a_engine.py")
report = _load("zkfuzz_report", "zkfuzz_report.py")

REPORT_NAME = "zkfdo_report_counterexample.json"
MODES = {"save_output", "stderr_report"}


def validate_report_mode(spec: Any) -> None:
    mode = spec.get("zkfuzz_output", "save_output") if isinstance(spec, dict) else None
    if mode not in MODES:
        raise v1.SpecError(f"zkfuzz_output must be one of {sorted(MODES)}")
    if mode != "stderr_report":
        return
    if spec.get("require_save_output", True) is not False:
        raise v1.SpecError("stderr_report mode needs require_save_output: false")
    for target in spec.get("targets", []):
        if "--save_output" in target.get("command", []):
            raise v1.SpecError(
                f"target {target.get('id')} requests --save_output, which suppresses the report"
            )
    for snapshot in spec.get("source_snapshots", []):
        patterns = snapshot.get("candidate_globs") or []
        if not any(fnmatch.fnmatch(REPORT_NAME, Path(pattern).name) for pattern in patterns):
            raise v1.SpecError(
                f"source snapshot {snapshot.get('id')} candidate_globs must match {REPORT_NAME}"
            )


def with_report_mode(validate: Callable[[Any], None]) -> Callable[[Any], None]:
    def validate_spec(spec: Any) -> None:
        validate(spec)
        validate_report_mode(spec)

    return validate_spec


def link_report(execution: dict[str, Any], attempt_dir: Path) -> dict[str, Any]:
    """Converts the attempt's stderr report (if any) and writes `report_link.json`."""
    stderr = Path(execution["stderr_path"])
    link: dict[str, Any] = {
        "schema": "zkfdo-zkfuzz-report-link-v1",
        "stderr_path": stderr.name,
        "stderr_sha256": hashlib.sha256(stderr.read_bytes()).hexdigest() if stderr.exists() else None,
        "workspace_candidate": None,
        "type": None,
        "violated_condition_sha256": None,
        "status": "no_report",
    }
    if stderr.exists():
        try:
            value = report.convert(stderr, attempt_dir / "workspace" / REPORT_NAME, attempt_dir)
        except report.ReportError as error:
            link["status"] = f"report_unparsed: {error}"
            value = None
        if value is not None:
            link.update(
                {
                    "workspace_candidate": REPORT_NAME,
                    "type": value["5_flag"]["1_type"],
                    "violated_condition_sha256": value["zkfdo_report_link"][
                        "violated_condition_sha256"
                    ],
                    "status": "linked",
                }
            )
    v1.atomic_write(attempt_dir / "report_link.json", link)
    return link


def with_report_capture(spawn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def spawn_and_measure(command, attempt_dir, *arguments, **keywords):
        execution = spawn(command, attempt_dir, *arguments, **keywords)
        if "--save_output" in command:
            v1.atomic_write(
                Path(attempt_dir) / "report_link.json",
                {
                    "schema": "zkfdo-zkfuzz-report-link-v1",
                    "status": "unavailable_with_save_output",
                },
            )
        else:
            link_report(execution, Path(attempt_dir))
        return execution

    return spawn_and_measure


def install() -> None:
    v1.validate_spec = with_report_mode(v1.validate_spec)
    v1.spawn_and_measure = with_report_capture(v1.spawn_and_measure)


def main(argv: list[str] | None = None) -> int:
    install()
    return v1.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
