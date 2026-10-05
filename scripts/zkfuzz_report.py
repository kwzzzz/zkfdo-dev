#!/usr/bin/env python3
"""Turns zkFuzz's human-readable counterexample report into a candidate JSON that keeps the
violated-condition string, linked to the log it came from.

zkFuzz 072bf1f writes either a JSON file (`--save_output`, `main.rs:396-433`) whose
`5_flag.2_violated_condition` holds only an internal trace position (`utils.rs:75-76`), or,
without `--save_output`, the report on stderr (`main.rs:435`, `utils.rs:130-196`), whose flag
line carries the condition string (`utils.rs:51`). The two are exclusive, so a runner that
wants the string runs zkFuzz without `--save_output` and converts the report with this
module. The output uses the same keys the lifting engine reads (`7_assignment`).

Values are printed as signed integers; they are stored reduced modulo the field prime.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

BN254 = 21888242871839275222246405745257275088548364400416034343698204186575808495617
SCHEMA = "zkfdo-zkfuzz-report-candidate-v1"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TYPES = {
    "Unexpected-Input": "UnderConstrained-UnexpectedInput",
    "Non-Deterministic": "UnderConstrained-NonDeterministic",
    "Unused-Output": "UnderConstrained-UnusedOutput",
}


class ReportError(ValueError):
    pass


def _strip(line: str) -> str:
    line = ANSI.sub("", line)
    # Box drawing and an optional runner prefix (for example a timestamp) before it.
    if "║" in line:
        line = line.split("║", 1)[1]
    return line.strip()


def parse(text: str) -> dict[str, Any] | None:
    """The counterexample in a zkFuzz stderr report, or None when there is none."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if "Counter Example:" in line), None)
    if start is None:
        return None
    prime = BN254
    for line in lines:
        match = re.search(r"Prime Number\s*:\s*(\d+)", ANSI.sub("", line))
        if match:
            prime = int(match.group(1))
    flag_type = None
    condition = None
    expected = None
    assignment: dict[str, str] = {}
    in_assignment = False
    for raw in lines[start + 1 :]:
        if "╚" in raw:
            break
        line = _strip(raw)
        if not line:
            continue
        if "Assignment Details:" in line:
            in_assignment = True
            continue
        if not in_assignment:
            if flag_type is None:
                kind = re.search(r"UnderConstrained \(([^)]+)\)", line)
                if kind:
                    flag_type = TYPES.get(kind.group(1), f"UnderConstrained-{kind.group(1)}")
                elif "OverConstrained" in line:
                    flag_type = "OverConstrained"
            found = re.search(r"Violated Condition:\s*(.*)$", line)
            if found:
                condition = found.group(1).strip()
            found = re.search(r"`([^`]+)` is expected to be `([^`]+)`", line)
            if found:
                expected = {"name": found.group(1), "value": str(int(found.group(2)) % prime)}
            continue
        found = re.match(r"(?:➡️\s*)?(\S+) = (-?\d+)$", line)
        if not found:
            raise ReportError(f"unparsed assignment line: {line[:80]}")
        name, value = found.group(1), int(found.group(2)) % prime
        if assignment.get(name, str(value)) != str(value):
            raise ReportError(f"conflicting values for {name}")
        assignment[name] = str(value)
    if flag_type is None:
        raise ReportError("the report names no counterexample type")
    if not assignment:
        raise ReportError("the report has no assignment")
    return {
        "type": flag_type,
        "violated_condition": condition,
        "expected_output": expected,
        "assignment": assignment,
        "prime": str(prime),
    }


def candidate(report: dict[str, Any], log: Path, log_root: Path) -> dict[str, Any]:
    """A candidate JSON (zkFuzz key layout) with the condition and a link to its log."""
    flag: dict[str, Any] = {"1_type": report["type"]}
    if report["type"] == "UnderConstrained-UnexpectedInput":
        flag["2_violated_condition"] = {"pos": None, "text": report["violated_condition"]}
    if report["expected_output"] is not None:
        flag["2_expected_output"] = report["expected_output"]
    condition = report["violated_condition"]
    return {
        "schema": SCHEMA,
        "5_flag": flag,
        "7_assignment": report["assignment"],
        "zkfdo_report_link": {
            "log": log.resolve().relative_to(log_root.resolve()).as_posix(),
            "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            "violated_condition_sha256": (
                hashlib.sha256(condition.encode()).hexdigest() if condition else None
            ),
            "values": "reduced modulo the prime printed in the report summary",
        },
    }


def convert(log: Path, destination: Path, log_root: Path) -> dict[str, Any] | None:
    """Writes the candidate for `log` to `destination`; None (nothing written) without one."""
    report = parse(log.read_text(encoding="utf-8", errors="replace"))
    if report is None:
        return None
    value = candidate(report, log, log_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return value


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--log-root", type=Path, default=Path("."))
    arguments = parser.parse_args()
    result = convert(arguments.log, arguments.destination, arguments.log_root)
    print("no counterexample" if result is None else result["5_flag"]["1_type"])
