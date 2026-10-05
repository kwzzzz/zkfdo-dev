#!/usr/bin/env python3
"""M-01: remeasure E-01 compile successes with the pinned final F-01 discovery binary.

This driver reuses E-01 setup and compile metadata.  It runs only target discovery with
compiler instance capture, experiment preparation, and planning.  It never installs a
dependency, recompiles an original entrypoint as a separate stage, or invokes zkFuzz.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_f01_discovery as f01  # noqa: E402
from c03_outcomes import classify_preparation  # noqa: E402

legacy = f01.legacy
ROOT = legacy.ROOT
E01_RUN = ROOT / "runs/e01-setup-2026-10-03/recovery-v2"
E01_RESULTS = ROOT / "docs/e01_setup_results_2026-10-03.json"
F01_BINARY = ROOT / "runs/f01-2026-10-03/supplement-var-scope/tools/zkfDO"
RUN = ROOT / "runs/m01-2026-10-03"
TOOLS = RUN / "tools"
CIRCOM = ROOT / "runs/c02-corpus-2026-10-02/tools/circom"
EXPECTED_ZKFDO = "f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1"
EXPECTED_CIRCOM = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
DISCOVERY_CAP = 900
CAPTURE_CAP = 600


def population():
    rows = []
    for path in sorted(E01_RUN.glob("measurements/*/after/result.json")):
        record = json.loads(path.read_text())
        if (record.get("compile") or {}).get("status") != "success":
            continue
        report = (record.get("discovery") or {}).get("report")
        rows.append({
            "record": path,
            "identifier": path.parent.parent.name,
            "repository": record["repository"],
            "commit": record["commit_sha"],
            "entrypoint_key": record["entrypoint_key"],
            "entrypoint": record["entrypoint"],
            "constraints": record["compile"]["constraints"],
            "source_sha256": record["source_sha256"],
            "e01_component_status": record["preparation"]["status"],
            "e01_failure_types": record["preparation"].get("failure_types", []),
            "e01_discovery_report": report,
        })
    if len(rows) != 125:
        raise RuntimeError(f"E-01 compile-success denominator changed: {len(rows)} != 125")
    if len({row["identifier"] for row in rows}) != len(rows):
        raise RuntimeError("duplicate E-01 measurement identifier")
    if sum(row["constraints"] >= 100_000 for row in rows) != 49:
        raise RuntimeError("E-01 large-entrypoint denominator changed")
    return rows


def reference_checked(path):
    path = Path(path)
    if not path.is_file():
        raise RuntimeError("required input is missing: " + str(path))
    return legacy.reference(path)


def validate_item(item):
    record = json.loads(item["record"].read_text())
    report_ref = item["e01_discovery_report"]
    if not report_ref:
        raise RuntimeError(item["identifier"] + ": E-01 discovery report missing")
    report_path = ROOT / report_ref["path"]
    if legacy.digest(report_path) != report_ref["sha256"]:
        raise RuntimeError(item["identifier"] + ": E-01 discovery report hash mismatch")
    report = json.loads(report_path.read_text())
    project_root = Path(report["project_root"])
    entrypoint = Path(report["selected_entrypoint"])
    required_root = (E01_RUN / "repositories").resolve()
    if not project_root.resolve().is_relative_to(required_root):
        raise RuntimeError(item["identifier"] + ": project root is outside E-01 clones")
    if "runs/f01-2026-10-03" in str(entrypoint):
        raise RuntimeError(item["identifier"] + ": F-01 diagnostic source is forbidden")
    if legacy.digest(entrypoint) != record["source_sha256"]:
        raise RuntimeError(item["identifier"] + ": entrypoint source hash mismatch")
    return record, report, project_root, entrypoint


def freeze():
    rows = population()
    if legacy.digest(F01_BINARY) != EXPECTED_ZKFDO:
        raise RuntimeError("pinned F-01 binary hash mismatch")
    if legacy.digest(CIRCOM) != EXPECTED_CIRCOM:
        raise RuntimeError("pinned circom hash mismatch")
    TOOLS.mkdir(parents=True, exist_ok=True)
    copy = TOOLS / "zkfDO"
    if not copy.exists():
        shutil.copy2(F01_BINARY, copy)
    if legacy.digest(copy) != EXPECTED_ZKFDO:
        raise RuntimeError("M-01 binary copy hash mismatch")
    lock_path = RUN / "procedure-lock.json"
    entries = []
    for item in rows:
        record, report, project_root, entrypoint = validate_item(item)
        entries.append({
            "identifier": item["identifier"], "repository": item["repository"],
            "commit_sha": item["commit"], "entrypoint_key": item["entrypoint_key"],
            "entrypoint": item["entrypoint"], "constraints": item["constraints"],
            "source_sha256": item["source_sha256"],
            "e01_component_status": item["e01_component_status"],
            "e01_record": reference_checked(item["record"]),
            "e01_discovery_report": reference_checked(ROOT / item["e01_discovery_report"]["path"]),
            "project_root": str(project_root), "selected_entrypoint": str(entrypoint),
            "library_paths": report.get("library_paths", []),
        })
    document = {
        "schema_version": 1, "task": "M-01", "created_at": legacy.now(), "owner": "miiz",
        "deadline": "2026-10-05", "population": {"entrypoints": 125, "large_at_least_100k": 49},
        "selection": "all E-01 after/recovery-v2 records whose original compile status is success",
        "stages": ["target_discovery_with_instance_capture", "experiment_prepare", "experiment_plan"],
        "excluded_stages": ["dependency_setup", "original_entrypoint_compile", "zkfuzz"],
        "caps_seconds": {"discovery": DISCOVERY_CAP, "instance_capture": CAPTURE_CAP,
                         "wrapper_compile": 60, "prepare": 300, "internal_tool": 60, "plan": 30},
        "tools": {"zkfDO_source": reference_checked(F01_BINARY), "zkfDO_copy": reference_checked(copy),
                  "circom": reference_checked(CIRCOM)},
        "inputs": {"e01_results": reference_checked(E01_RESULTS), "entries": entries},
        "icloud_window_check": {
            "window_kst": "2026-10-03 19:30--20:16",
            "e01_measurement_window_kst": "2026-10-03 13:43--16:35",
            "overlap": False, "path_loss_errors": 0,
        },
        "zkfuzz_invocations": 0,
    }
    if lock_path.exists():
        old = json.loads(lock_path.read_text())
        comparable = dict(document)
        comparable["created_at"] = old.get("created_at")
        if old != comparable:
            raise RuntimeError("existing M-01 procedure lock differs")
    else:
        legacy.write_new(lock_path, document)
    return {"zkfDO": copy}, rows


def finish(result, item, result_path, prepared, discovery):
    outcome = classify_preparation(result, prepared_report=prepared, discovery_report=discovery)
    result["preparation_outcome"] = outcome
    result["preparation"]["reported_status"] = result["preparation"].get("status")
    result["preparation"].update({key: outcome[key] for key in ("status", "failure_type", "failure_types")})
    result["m01_component_status"] = result["preparation"]["status"]
    result["finished_at"] = legacy.now()
    legacy.write_new(result_path, result)
    return result


def measure(item, tools):
    directory = RUN / "measurements" / item["identifier"]
    result_path = directory / "result.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    _, old, project_root, entrypoint = validate_item(item)
    libraries = [Path(path) for path in old.get("library_paths", [])]
    result = {
        "schema_version": 1, "task": "M-01", "identifier": item["identifier"],
        "repository": item["repository"], "commit": item["commit"],
        "entrypoint_key": item["entrypoint_key"], "entrypoint": item["entrypoint"],
        "constraints": item["constraints"], "source_sha256": item["source_sha256"],
        "e01_component_status": item["e01_component_status"],
        "e01_failure_types": item["e01_failure_types"],
        "e01_record": reference_checked(item["record"]), "started_at": legacy.now(),
        "zkfuzz_executions": 0,
        "settings": {"discovery_cap_seconds": DISCOVERY_CAP, "capture_cap_seconds": CAPTURE_CAP,
                     "wrapper_compile_cap_seconds": 60, "preparation_cap_seconds": 300,
                     "plan_cap_seconds": 30, "original_compile_reused": True},
    }
    command = [str(tools["zkfDO"]), "targets", "--project", str(project_root),
               "--entrypoint", str(entrypoint), "--output", str(directory / "discovery"),
               "--circom-bin", str(CIRCOM), "--compile-timeout-seconds", "60", "--instance-capture",
               "--capture-timeout-seconds", str(CAPTURE_CAP)]
    for path in libraries:
        command.extend(["--library-path", str(path)])
    capture = legacy.run_command(command, directory / "discover-call", DISCOVERY_CAP)
    result["discovery"] = legacy.brief(capture)
    result["discovery"]["failure_type"] = legacy.failure_type(capture)
    result["preparation"] = {"status": "not_started", "reason": "discovery report unavailable"}
    report_path = legacy.locate_report(directory / "discovery", "discovery.json")
    if capture["status"] != "success" or report_path is None:
        return finish(result, item, result_path, None, None)
    new = json.loads(report_path.read_text())
    instance = new.get("instance_discovery") or {}
    result["discovery"].update(
        report=legacy.reference(report_path), entrypoint_status=new["entrypoint_status"],
        callsites=len(new["targets"]), unique_compile_units=len(new["compile_units"]),
        unsupported=[{k: v for k, v in row.items() if k != "construct"} for row in new["unsupported"]],
        callsite_wrapper_statuses=[row["wrapper_status"] for row in new["targets"]],
        instance_sources=sorted({row.get("instance_source") for row in new["targets"]} - {None}),
    )
    fields = ("selected", "capture_status", "capture_failure", "capture_compile_seconds",
              "capture_compile_attempts", "capture_scan_seconds", "capture_read_seconds",
              "capture_assemble_seconds", "interpreter_complete", "compiler_complete",
              "interpreter_targets", "compiler_targets", "interpreter_root_instance_key",
              "compiler_root_instance_key", "slots_compared")
    result["instance_discovery"] = {key: instance.get(key) for key in fields}
    result["instance_discovery"]["slot_differences"] = instance.get("slot_differences", [])
    result["instance_discovery"]["interpreter_unsupported_reasons"] = sorted(
        {row["reason"] for row in instance.get("interpreter_unsupported", [])})
    capture_path = Path(instance["capture_path"]) if instance.get("selected") == "compiler" else None
    if capture_path is not None:
        captured = json.loads(capture_path.read_text())
        result["instance_discovery"]["capture_report"] = legacy.reference(capture_path)
        for kind in ("diagnostic_r1cs", "diagnostic_sym"):
            if captured.get(kind):
                result["instance_discovery"][kind] = {
                    key: captured[kind][key] for key in ("path", "sha256", "bytes")}
        result["instance_discovery"].update(
            capture_signals=captured.get("capture_signals"),
            capture_constraints=captured.get("capture_constraints"),
            captured_instances=len(captured.get("instances", [])),
        )
    result["regression"] = f01.compare(old, new)
    prepared = None
    try:
        manifest = f01.manifest_for(item["repository"], item["commit"], project_root, entrypoint,
                                    new, libraries, capture_path)
    except ValueError as error:
        result["preparation"] = {"status": "unsupported", "reason": str(error)}
    else:
        manifest_path = directory / "manifest.json"
        legacy.write_new(manifest_path, manifest)
        prepared_dir = directory / "prepared"
        run = legacy.run_command(
            [str(tools["zkfDO"]), "experiment", "prepare", "--manifest", str(manifest_path),
             "--output", str(prepared_dir), "--strategy", "small-first", "--circom-bin", str(CIRCOM),
             "--zkfuzz-bin", "/nonexistent/m01-zkfuzz-forbidden",
             "--circomspect-bin", "/nonexistent/m01-analyzer-forbidden", "--tool-timeout-seconds", "60"],
            directory / "prepare-call", 300)
        result["preparation"] = legacy.brief(run)
        result["preparation"].update(manifest=legacy.reference(manifest_path),
                                     failure_type=legacy.failure_type(run), expected_targets=len(manifest["targets"]))
        prepared_path = None
        try:
            prepared_path = legacy.locate_report(prepared_dir, "prepared.json")
        except ValueError as error:
            result["preparation"].update(status="unknown", reason=str(error))
        if run["status"] == "success" and prepared_path is not None:
            prepared = json.loads(prepared_path.read_text())
            expected = {row["label"]: row for row in manifest["targets"]}
            definitions = [row["definition"] for row in prepared["targets"]]
            try:
                if len(definitions) != len(manifest["targets"]):
                    raise ValueError("prepared target count mismatch")
                if len({row["label"] for row in definitions}) != len(definitions):
                    raise ValueError("duplicate prepared target labels")
                for definition in definitions:
                    if any(definition.get(key) != value for key, value in expected[definition["label"]].items()):
                        raise ValueError("prepared target identity mismatch")
            except (ValueError, KeyError, TypeError) as error:
                result["preparation"].update(status="unknown", reason=str(error),
                                             report=legacy.reference(prepared_path))
                prepared = None
        if prepared is not None:
            targets = []
            for target in prepared["targets"]:
                structure = target.get("structure") or {}
                if structure.get("ast_requested") or (structure.get("zkfuzz_version") or {}).get("requested"):
                    raise RuntimeError("forbidden frontend request in compile-only report")
                source = target.get("instance_inspection") or {}
                targets.append({
                    "label": target["definition"]["label"], "eligible": target["eligible"],
                    "exclusion_reasons": target["exclusion_reasons"], "constraints": structure.get("size"),
                    "compile_seconds": (structure.get("compile") or {}).get("elapsed_seconds"),
                    "compiler_started": (structure.get("compile") or {}).get("process_started"),
                    "inspection_source": source.get("source", "interpreter"),
                    "interpreter_inspection_complete": source.get("interpreter_complete"),
                    "compiler_inspection_complete": source.get("compiler_complete"),
                    "inspection_instances_only_interpreter": len(source.get("instances_only_interpreter", [])),
                    "inspection_instances_only_compiler": len(source.get("instances_only_compiler", [])),
                    "inspection_seconds": (target.get("timings") or {}).get("inspection_seconds"),
                    "elapsed_seconds": target["elapsed_seconds"],
                })
            result["preparation"].update(report=legacy.reference(prepared_path), targets=targets,
                                         eligible=sum(row["eligible"] for row in targets))
            plan = legacy.run_command(
                [str(tools["zkfDO"]), "experiment", "plan", "--prepared", str(prepared_path),
                 "--strategy", "small-first", "--config", str(ROOT / "configs/static-ranking.json"),
                 "--output", str(directory / "plan.json")], directory / "plan-call", 30)
            result["plan"] = legacy.brief(plan)
            if plan["status"] == "success" and not (directory / "plan.json").is_file():
                result["plan"].update(status="unknown", reason="successful plan left no plan artifact")
            if (directory / "plan.json").exists():
                result["plan"]["report"] = legacy.reference(directory / "plan.json")
            result["preparation"]["status"] = legacy.preparation_status(
                new, prepared, plan, len(manifest["targets"]))
        elif run["status"] == "success" and prepared_path is None:
            result["preparation"].update(status="unknown", reason="successful prepare left no prepared report")
    return finish(result, item, result_path, prepared, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--freeze-only", action="store_true")
    args = parser.parse_args()
    tools, rows = freeze()
    if args.freeze_only:
        print(json.dumps({"population": len(rows), "tool": legacy.digest(tools["zkfDO"])}))
        return
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(measure, row, tools): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                result = future.result()
                print(json.dumps({"id": row["identifier"], "repo": row["repository"],
                                  "e01": row["e01_component_status"],
                                  "m01": result.get("m01_component_status")}), flush=True)
            except Exception as error:
                print(json.dumps({"id": row["identifier"],
                                  "error": f"{type(error).__name__}: {error}"}), flush=True)


if __name__ == "__main__":
    main()
