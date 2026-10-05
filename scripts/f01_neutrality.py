#!/usr/bin/env python3
"""F-01 neutrality evidence: the capture statements must not change the original circuit.

For each representative circuit, `zkfDO capture --verify-neutrality` compiles the diagnostic
copy and the original at O0 and checks that removing the capture signals and the constraints
that mention them from the diagnostic R1CS leaves the original R1CS, constraint by constraint.
C-03 entrypoints take their project root, entrypoint and library paths from the C-03
discovery report. Results go under runs/f01-2026-10-03/neutrality; compiled artifacts there are
recorded and removed by the F-01 cleanup.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_f01_discovery as f01  # noqa: E402

ROOT = f01.ROOT
OUT = f01.RUN / "neutrality"
CIRCOMLIB = ROOT / ".external/zkbugs/dataset/circom/dependencies/circomlib/circuits"
LOCAL = {
    "fixture-instance-capture": (ROOT / "tests/fixtures/instance_capture", "main.circom", []),
    "fixture-target-discovery": (ROOT / "tests/fixtures/target_discovery", "main.circom", []),
    "probe-small": (f01.RUN / "probe/small", "small.circom", []),
    "probe-poseidon2": (f01.RUN / "probe/poseidon", "p2.circom", [CIRCOMLIB]),
}


def c03_inputs(identifier):
    record = json.loads((f01.C03 / "measurements" / identifier / "after-v4/result.json").read_text())
    report = json.loads((ROOT / record["discovery"]["report"]["path"]).read_text())
    return (Path(report["project_root"]), Path(report["selected_entrypoint"]),
            [Path(path) for path in report.get("library_paths", [])], record["repository"], record["entrypoint_key"])


def run(name, project, entrypoint, libraries, tools, cap):
    output = OUT / name
    if (OUT / f"{name}.json").exists():
        return json.loads((OUT / f"{name}.json").read_text())
    command = [str(tools["zkfDO"]), "capture", "--project", str(project), "--entrypoint", str(entrypoint),
               "--output", str(output / "capture"), "--circom-bin", str(f01.CIRCOM),
               "--timeout-seconds", str(cap), "--verify-neutrality"]
    for library in libraries:
        command.extend(["--library-path", str(library)])
    call = f01.legacy.run_command(command, output / "call", cap * 2 + 600)
    row = {"name": name, "entrypoint": str(entrypoint), "call": f01.legacy.brief(call)}
    report_path = output / "capture/capture-report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text())
        capture = json.loads(Path(report["capture_path"]).read_text())
        row.update(status=report["status"], complete=report["complete"], instances=report["instances"],
                   unsupported=report["unsupported"], capture_compile_seconds=report["compile_seconds"],
                   original_compile_seconds=(report.get("original_compile") or {}).get("elapsed_seconds"),
                   neutrality=report["neutrality"], capture_signals=capture["capture_signals"],
                   capture_constraints=capture["capture_constraints"],
                   diagnostic_r1cs=capture["diagnostic_r1cs"], report=f01.legacy.reference(report_path))
    f01.legacy.write_new(OUT / f"{name}.json", row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c03", nargs="*", default=[], help="C-03 measurement identifiers")
    parser.add_argument("--cap", type=int, default=f01.CAPTURE_CAP)
    arguments = parser.parse_args()
    tools = f01.lock_tools()
    rows = []
    for name, (project, entrypoint, libraries) in LOCAL.items():
        rows.append(run(name, project, project / entrypoint, libraries, tools, arguments.cap))
    for identifier in arguments.c03:
        project, entrypoint, libraries, repository, key = c03_inputs(identifier)
        row = run("c03-" + identifier, project, entrypoint, libraries, tools, arguments.cap)
        row.update(repository=repository, entrypoint_key=key)
        rows.append(row)
    for row in rows:
        neutrality = row.get("neutrality") or {}
        print(json.dumps({"name": row["name"], "status": row.get("status"), "complete": row.get("complete"),
                          "identical": neutrality.get("identical"),
                          "original": neutrality.get("original_constraints"),
                          "removed": neutrality.get("capture_constraints_removed")}), flush=True)


if __name__ == "__main__":
    main()
