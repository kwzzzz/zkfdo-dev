"""Count call sites versus unique target instances in the preserved T6a discovery reports.

Reads runs/t6a-discovery-diagnostic-2026-09-24/{diag2,compile}/*/discovery.json (ignored local
evidence) and prints the supplementary JSON. The key is (source_path, template_name,
concrete_parameters). Within one project every discovery used the same checkout, project root
and library path, so one source file resolves its includes identically for every entrypoint.
The key does not merge caller context: callers may constrain inputs differently.
"""

import hashlib
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs" / "t6a-discovery-diagnostic-2026-09-24"
PROJECTS = ["zkemail", "moonsong", "rarimo", "self", "bigint", "inference"]


def key(target):
    return (target["source_path"], target["template_name"], tuple(target["concrete_parameters"]))


def project_of(report):
    entrypoint = report["selected_entrypoint"]
    return next(name for name in PROJECTS if f"/{name}/vulnerable/" in entrypoint)


def load(subdir):
    paths = sorted((RUNS / subdir).glob("*/discovery.json"))
    return paths, [json.loads(path.read_text()) for path in paths]


def manifest_sha256(paths):
    lines = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(RUNS)}\n"
        for path in paths
    )
    return hashlib.sha256(lines.encode()).hexdigest()


def main():
    diag_paths, diag = load("diag2")
    compile_paths, compiled = load("compile")
    projects = {}
    for name in PROJECTS:
        reports = [report for report in diag if project_of(report) == name]
        per_entrypoint = [len({key(t) for t in report["targets"]}) for report in reports]
        nonzero = [count for count in per_entrypoint if count]
        call_sites = sum(len(report["targets"]) for report in reports)
        per_entrypoint_sum = sum(per_entrypoint)
        union = len({key(t) for report in reports for t in report["targets"]})
        projects[name] = {
            "entrypoints": len(reports),
            "call_sites": call_sites,
            "unique_per_entrypoint_median_nonzero": statistics.median_low(nonzero) if nonzero else 0,
            "unique_per_entrypoint_max": max(per_entrypoint, default=0),
            "unique_per_entrypoint_sum": per_entrypoint_sum,
            "unique_in_project": union,
            "call_sites_per_unique_within_entrypoint": round(call_sites / per_entrypoint_sum, 1)
            if per_entrypoint_sum
            else None,
            "call_sites_per_unique_in_project": round(call_sites / union, 1) if union else None,
        }
    compile_sample = [
        {
            "entrypoint": pathlib.Path(report["selected_entrypoint"]).name,
            "call_sites": len(report["targets"]),
            "unique": len({key(t) for t in report["targets"]}),
            "wrapper_compilations": sum(1 for t in report["targets"] if t.get("compile")),
            "compile_succeeded": sum(
                1 for t in report["targets"] if t["wrapper_status"] == "compile_succeeded"
            ),
        }
        for report in compiled
    ]
    json.dump(
        {
            "schema_version": 1,
            "date": "2026-09-26",
            "key": ["source_path", "template_name", "concrete_parameters"],
            "diagnosis_reports": len(diag_paths),
            "diagnosis_compiled_wrappers": any(r.get("compile_timeout_seconds") for r in diag),
            "diagnosis_manifest_sha256": manifest_sha256(diag_paths),
            "compile_manifest_sha256": manifest_sha256(compile_paths),
            "projects": projects,
            "compile_sample": compile_sample,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
