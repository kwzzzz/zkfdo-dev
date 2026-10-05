#!/usr/bin/env python3
"""F-01: rerun discovery and preparation (no zkFuzz) with compiler-based instance capture.

Population: every C-03 after-v4 record of a production repository (656 entrypoints) and every
C-03 record whose preparation succeeded (881, any layer). Discovery runs with
``--instance-capture``; the manifest points every target at the capture so preparation builds
inspections from it. Caps follow C-03 (wrapper compile 60 s, prepare 300 s, plan 30 s) except
discovery, which also runs the instrumented O0 compile (capture cap 600 s, discovery 900 s).
Each record compares the new targets with the C-03 discovery report of the same entrypoint.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_c02_preparation as legacy  # noqa: E402
from c03_outcomes import classify_preparation  # noqa: E402

ROOT = legacy.ROOT
C03 = ROOT / "runs/c03-corpus-2026-10-02/recovery-v3"
C03_RESULTS = ROOT / "docs/c03_corpus_results_2026-10-02.json"
RUN = ROOT / "runs/f01-2026-10-03"
TOOLS = RUN / "tools"
# A supplement (--supplement NAME) writes to RUN/NAME/{tools,measurements} with its own lock.
OUTPUT = RUN
CIRCOM = ROOT / "runs/c02-corpus-2026-10-02/tools/circom"
DISCOVERY_CAP = 900
CAPTURE_CAP = 600
TOKEN = re.compile(r"-?\d+|\[sha256:[0-9a-f]{64}\]")


def parse_instance(key):
    """Template and parameter tokens of `source::Template(tokens)`; array tokens allowed."""
    if not key or "::" not in key:
        raise ValueError("concrete root instance key unavailable")
    call = key.rsplit("::", 1)[1]
    match = re.fullmatch(r"([A-Za-z_$][\w$]*)\((.*)\)", call)
    if not match:
        raise ValueError("concrete instance key unsupported")
    params = [part.strip() for part in match[2].split(",")] if match[2].strip() else []
    if any(not TOKEN.fullmatch(parameter) for parameter in params):
        raise ValueError("concrete instance parameter is neither an integer nor an array hash")
    return match[1], params


def manifest_for(repo_name, commit, project_root, entrypoint, discovery, libraries, capture_path):
    definitions = [("root", entrypoint, discovery.get("root_instance_key"), "original")]
    seen = set()
    for unit in discovery.get("compile_units", []):
        if unit["key"] in seen:
            raise ValueError("duplicate compile-unit key")
        seen.add(unit["key"])
        definitions.append((unit["key"], unit["wrapper_path"], unit["instance_key"], "direct"))
    targets = []
    for label, source, key, mode in definitions:
        template, parameters = parse_instance(key)
        target = {"label": label, "project": repo_name, "revision": commit,
                  "project_root": str(project_root), "entrypoint": str(source),
                  "template_name": template, "concrete_parameters": parameters, "prime": "bn128",
                  "compile_args": [item for lib in libraries for item in ("-l", str(lib))],
                  "mode": mode, "input_assumptions": "Preparation only; semantic input domain unreviewed.",
                  "known_defects": []}
        if capture_path is not None:
            target["instance_capture"] = str(capture_path)
        targets.append(target)
    return {"schema_version": 1, "name": "f01-" + hashlib.sha256(str(entrypoint).encode()).hexdigest()[:16],
            "description": "Discovery/preparation applicability only; no search.", "targets": targets,
            "exclusions": []}


def slots(report):
    """(parent key, component name, line) -> child keys; anonymous names without context."""
    result = {}
    for target in report.get("targets", []):
        name = target["origin"]["component_name"]
        if name.startswith("@anonymous:"):
            name = name.split("[", 1)[0]
        key = (target.get("parent_instance_key", ""), name, target["origin"]["line"])
        result.setdefault(key, set()).add(target.get("instance_key", ""))
    return result


def compare(old, new):
    old_slots, new_slots = slots(old), slots(new)
    differences = []
    for key in sorted(set(old_slots) | set(new_slots)):
        a, b = old_slots.get(key, set()), new_slots.get(key, set())
        if a != b:
            differences.append({"parent_instance_key": key[0], "component_name": key[1], "line": key[2],
                                "c03": sorted(a), "f01": sorted(b)})
    old_units = {unit["instance_key"] for unit in old.get("compile_units", [])}
    new_units = {unit["instance_key"] for unit in new.get("compile_units", [])}
    return {"root_equal": old.get("root_instance_key") == new.get("root_instance_key"),
            "c03_root_instance_key": old.get("root_instance_key"),
            "f01_root_instance_key": new.get("root_instance_key"),
            "slots_compared": len(set(old_slots) | set(new_slots)),
            "slot_differences": differences,
            "compile_unit_instance_keys_only_c03": sorted(old_units - new_units),
            "compile_unit_instance_keys_only_f01": sorted(new_units - old_units)}


def automatic_status(compile_status, component):
    """As summarize_c03_corpus._automatic_preparation: the component status only after a compile."""
    if compile_status == "success":
        return component
    return ("not_started" if compile_status == "not_started"
            else "unknown" if compile_status in {"missing", "unknown"} else "failed")


def population():
    roles = {row["full_name"]: row["role"] for row in json.loads(C03_RESULTS.read_text())["repositories"]}
    rows = []
    for path in sorted(C03.glob("measurements/*/after-v4/result.json")):
        record = json.loads(path.read_text())
        role = roles.get(record["repository"], "unknown")
        component = record["preparation"].get("status")
        if role != "production" and component != "success":
            continue
        rows.append({"record": path, "identifier": path.parent.parent.name, "role": role,
                     "repository": record["repository"], "commit": record["commit_sha"],
                     "entrypoint_key": record["entrypoint_key"], "compile_status": record["compile"]["status"],
                     "c03_component_status": component,
                     "c03_automatic_status": automatic_status(record["compile"]["status"], component),
                     "c03_failure_types": record["preparation"].get("failure_types", []),
                     "production": role == "production", "regression": component == "success"})
    return rows


def measure(item, tools):
    directory = OUTPUT / "measurements" / item["identifier"]
    result_path = directory / "result.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    if directory.exists():
        shutil.rmtree(directory)  # an interrupted attempt of this run; rerun it whole
    directory.mkdir(parents=True)
    record = json.loads(Path(item["record"]).read_text())
    result = {"schema_version": 1, "task": "F-01", **{k: v for k, v in item.items() if k != "record"},
              "c03_record": legacy.reference(item["record"]), "started_at": legacy.now(), "zkfuzz_executions": 0,
              "settings": {"discovery_cap_seconds": DISCOVERY_CAP, "capture_cap_seconds": CAPTURE_CAP,
                           "wrapper_compile_cap_seconds": 60, "preparation_cap_seconds": 300, "plan_cap_seconds": 30}}
    old_report_ref = (record.get("discovery") or {}).get("report")
    if not old_report_ref:
        result["discovery"] = {"status": "not_started", "failure_type": "c03_discovery_report_missing"}
        result["preparation"] = {"status": "not_started", "reason": "C-03 record has no discovery report"}
        return finish(result, item, result_path, None, None)
    old = json.loads((ROOT / old_report_ref["path"]).read_text())
    project_root = Path(old["project_root"])
    entrypoint = Path(old["selected_entrypoint"])
    libraries = [Path(path) for path in old.get("library_paths", [])]
    command = [str(tools["zkfDO"]), "targets", "--project", str(project_root), "--entrypoint", str(entrypoint),
               "--output", str(directory / "discovery"), "--circom-bin", str(CIRCOM),
               "--compile-timeout-seconds", "60", "--instance-capture",
               "--capture-timeout-seconds", str(CAPTURE_CAP)]
    for path in libraries:
        command.extend(["--library-path", str(path)])
    capture = legacy.run_command(command, directory / "discover-call", DISCOVERY_CAP)
    result["discovery"] = legacy.brief(capture)
    result["discovery"]["failure_type"] = legacy.failure_type(capture)
    report_path = legacy.locate_report(directory / "discovery", "discovery.json")
    result["preparation"] = {"status": "not_started", "reason": "discovery report unavailable"}
    if capture["status"] != "success" or report_path is None:
        return finish(result, item, result_path, None, None)
    new = json.loads(report_path.read_text())
    instance = new.get("instance_discovery") or {}
    result["discovery"].update(
        report=legacy.reference(report_path), entrypoint_status=new["entrypoint_status"],
        callsites=len(new["targets"]), unique_compile_units=len(new["compile_units"]),
        unsupported=[{key: value for key, value in row.items() if key != "construct"} for row in new["unsupported"]],
        callsite_wrapper_statuses=[row["wrapper_status"] for row in new["targets"]],
        instance_sources=sorted({row.get("instance_source") for row in new["targets"]} - {None}))
    result["instance_discovery"] = {key: instance.get(key) for key in (
        "selected", "capture_status", "capture_failure", "capture_compile_seconds", "capture_compile_attempts",
        "capture_scan_seconds", "capture_read_seconds", "capture_assemble_seconds", "interpreter_complete",
        "compiler_complete",
        "interpreter_targets", "compiler_targets", "interpreter_root_instance_key", "compiler_root_instance_key",
        "slots_compared")}
    result["instance_discovery"]["slot_differences"] = instance.get("slot_differences", [])
    result["instance_discovery"]["interpreter_unsupported_reasons"] = sorted(
        {row["reason"] for row in instance.get("interpreter_unsupported", [])})
    capture_path = Path(instance["capture_path"]) if instance.get("selected") == "compiler" else None
    if capture_path is not None:
        captured = json.loads(capture_path.read_text())
        for kind in ("diagnostic_r1cs", "diagnostic_sym"):
            if captured.get(kind):
                result["instance_discovery"][kind] = {key: captured[kind][key] for key in ("path", "sha256", "bytes")}
        result["instance_discovery"]["capture_signals"] = captured.get("capture_signals")
        result["instance_discovery"]["capture_constraints"] = captured.get("capture_constraints")
        result["instance_discovery"]["captured_instances"] = len(captured.get("instances", []))
    result["regression"] = compare(old, new)
    prepared = None
    try:
        manifest = manifest_for(item["repository"], item["commit"], project_root, entrypoint, new, libraries, capture_path)
    except ValueError as error:
        result["preparation"] = {"status": "unsupported", "reason": str(error)}
    else:
        manifest_path = directory / "manifest.json"
        legacy.write_new(manifest_path, manifest)
        prepared_dir = directory / "prepared"
        run = legacy.run_command([str(tools["zkfDO"]), "experiment", "prepare", "--manifest", str(manifest_path),
                                  "--output", str(prepared_dir), "--strategy", "small-first",
                                  "--circom-bin", str(CIRCOM), "--zkfuzz-bin", "/nonexistent/f01-zkfuzz-forbidden",
                                  "--circomspect-bin", "/nonexistent/f01-analyzer-forbidden",
                                  "--tool-timeout-seconds", "60"], directory / "prepare-call", 300)
        result["preparation"] = legacy.brief(run)
        result["preparation"].update(manifest=legacy.reference(manifest_path), failure_type=legacy.failure_type(run),
                                     expected_targets=len(manifest["targets"]))
        try:
            prepared_path = legacy.locate_report(prepared_dir, "prepared.json")
        except ValueError as error:
            prepared_path = None
            result["preparation"].update(status="unknown", reason=str(error))
        if run["status"] == "success" and prepared_path is not None:
            prepared = json.loads(prepared_path.read_text())
            try:  # same identity check as C-03 (measure_c02_preparation.complete_preparation)
                if len(prepared["targets"]) != len(manifest["targets"]):
                    raise ValueError("prepared target count mismatch")
                expected = {row["label"]: row for row in manifest["targets"]}
                definitions = [row["definition"] for row in prepared["targets"]]
                if len({row["label"] for row in definitions}) != len(definitions):
                    raise ValueError("duplicate prepared target labels")
                for definition in definitions:
                    if any(definition.get(key) != value for key, value in expected[definition["label"]].items()):
                        raise ValueError("prepared target identity mismatch")
            except (ValueError, KeyError, TypeError) as error:
                result["preparation"].update(status="unknown", reason=str(error), report=legacy.reference(prepared_path))
                prepared = None
        if prepared is not None:
            rows = []
            for target in prepared["targets"]:
                structure = target.get("structure") or {}
                if structure.get("ast_requested") or (structure.get("zkfuzz_version") or {}).get("requested"):
                    raise RuntimeError("forbidden frontend request in compile-only report")
                source = target.get("instance_inspection") or {}
                rows.append({"label": target["definition"]["label"], "eligible": target["eligible"],
                             "exclusion_reasons": target["exclusion_reasons"], "constraints": structure.get("size"),
                             "compile_seconds": (structure.get("compile") or {}).get("elapsed_seconds"),
                             "compiler_started": (structure.get("compile") or {}).get("process_started"),
                             "inspection_source": source.get("source", "interpreter"),
                             "interpreter_inspection_complete": source.get("interpreter_complete"),
                             "compiler_inspection_complete": source.get("compiler_complete"),
                             "inspection_instances_only_interpreter": len(source.get("instances_only_interpreter", [])),
                             "inspection_instances_only_compiler": len(source.get("instances_only_compiler", [])),
                             "inspection_seconds": (target.get("timings") or {}).get("inspection_seconds"),
                             "elapsed_seconds": target["elapsed_seconds"]})
            result["preparation"].update(report=legacy.reference(prepared_path), targets=rows,
                                         eligible=sum(row["eligible"] for row in rows))
            plan = legacy.run_command([str(tools["zkfDO"]), "experiment", "plan", "--prepared", str(prepared_path),
                                       "--strategy", "small-first", "--config", str(ROOT / "configs/static-ranking.json"),
                                       "--output", str(directory / "plan.json")], directory / "plan-call", 30)
            result["plan"] = legacy.brief(plan)
            if plan["status"] == "success" and not (directory / "plan.json").is_file():
                plan = dict(plan, status="unknown")
                result["plan"].update(status="unknown", reason="successful plan left no plan artifact")
            result["preparation"]["status"] = legacy.preparation_status(new, prepared, plan, len(manifest["targets"]))
            if (directory / "plan.json").exists():
                result["plan"]["report"] = legacy.reference(directory / "plan.json")
        elif run["status"] == "success" and prepared_path is None:
            result["preparation"].update(status="unknown", reason="successful prepare left no prepared report")
    return finish(result, item, result_path, prepared, new)


def finish(result, item, result_path, prepared, discovery):
    """C-03 classification (c03_outcomes.classify_preparation), so statuses compare like for like."""
    result["preparation_outcome"] = classify_preparation(result, prepared_report=prepared,
                                                         discovery_report=discovery)
    result["preparation"]["reported_status"] = result["preparation"].get("status")
    result["preparation"].update({key: result["preparation_outcome"][key]
                                  for key in ("status", "failure_type", "failure_types")})
    status = result["preparation"]["status"]
    result["f01_component_status"] = status
    result["f01_automatic_status"] = automatic_status(item["compile_status"], status)
    result["finished_at"] = legacy.now()
    legacy.write_new(result_path, result)
    return result


def lock_tools():
    tools = OUTPUT / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    binary = ROOT / "target/release/zkfDO"  # C-03 used a debug build; see the results document
    copy = tools / "zkfDO"
    lock = tools / "tool-lock.json"
    if not lock.exists():
        shutil.copy2(binary, copy)
        legacy.write_new(lock, {"created_at": legacy.now(),
                                "tools": [{"path": str(copy), "original_path": str(binary), "sha256": legacy.digest(copy)},
                                          {"path": str(CIRCOM), "sha256": legacy.digest(CIRCOM)}]})
    for tool in json.loads(lock.read_text())["tools"]:
        if legacy.digest(tool["path"]) != tool["sha256"]:
            raise RuntimeError("fixed tool changed: " + tool["path"])
    return {"zkfDO": copy}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", nargs="*", help="measurement identifiers to run")
    parser.add_argument("--supplement", help="write to RUN/<name> with a separate tool lock")
    arguments = parser.parse_args()
    global OUTPUT
    if arguments.supplement:
        if not arguments.only or not re.fullmatch(r"[a-z0-9-]+", arguments.supplement):
            raise SystemExit("a supplement needs a plain name and --only identifiers")
        OUTPUT = RUN / arguments.supplement
    tools = lock_tools()
    rows = population()
    if arguments.only:
        rows = [row for row in rows if row["identifier"] in set(arguments.only)]
    legacy.write_new(OUTPUT / f"population-{len(rows)}-{hashlib.sha256(legacy.now().encode()).hexdigest()[:8]}.json",
                     [{k: (str(v) if isinstance(v, Path) else v) for k, v in row.items()} for row in rows])
    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        futures = {pool.submit(measure, row, tools): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                result = future.result()
                print(json.dumps({"id": row["identifier"], "repo": row["repository"],
                                  "c03": row["c03_component_status"],
                                  "f01": result.get("f01_component_status", result.get("status"))}), flush=True)
            except Exception as error:  # keep going; the error is visible in the log
                print(json.dumps({"id": row["identifier"], "error": f"{type(error).__name__}: {error}"}), flush=True)


if __name__ == "__main__":
    main()
