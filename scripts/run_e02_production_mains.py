#!/usr/bin/env python3
"""Run E-02 deployment-main compile and F-01 preparation measurements; never runs zkFuzz."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
import shutil
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e02_production_mains as rules  # noqa: E402
import measure_c02_preparation as legacy  # noqa: E402
import measure_f01_discovery as f01  # noqa: E402
from c03_outcomes import classify_preparation  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/e02-production-mains-2026-10-05"
E01_RUN = ROOT / "runs/e01-setup-2026-10-03/recovery-v2"
E01_RESULTS = ROOT / "docs/e01_setup_results_2026-10-03.json"
M01_RUN = ROOT / "runs/m01-2026-10-03"
PROCEDURE = ROOT / "docs/e02_production_mains_procedure_v2_2026-10-05.md"
F01_BINARY = ROOT / "runs/f01-2026-10-03/supplement-var-scope/tools/zkfDO"
CIRCOM = ROOT / "runs/c02-corpus-2026-10-02/tools/circom"
EXPECTED_ZKFDO = "f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1"
EXPECTED_CIRCOM = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
DISK_GUARD_BYTES = 35 * 1024**3


def read(path: Path):
    return json.loads(path.read_text())


def ref(path: Path):
    path = path.resolve()
    return {"path": str(path.relative_to(ROOT)), "sha256": legacy.digest(path)}


def identifier(path: Path) -> str:
    return path.parent.parent.name


def clone_for(repository: str) -> Path:
    return E01_RUN / "repositories" / repository.replace("/", "__") / "clone"


def selected_source(record: dict) -> tuple[dict, Path, Path, str | None]:
    report_ref = (record.get("discovery") or {}).get("report")
    if not report_ref:
        raise ValueError("E-01 discovery report missing")
    report_path = ROOT / report_ref["path"]
    if legacy.digest(report_path) != report_ref["sha256"]:
        raise ValueError("E-01 discovery report hash mismatch")
    report = read(report_path)
    source = Path(report["selected_entrypoint"])
    clone = clone_for(record["repository"])
    relative = str(source.resolve().relative_to(clone.resolve())) if source.resolve().is_relative_to(clone.resolve()) else None
    return report, report_path, source, relative


def build_references(clone: Path, key: str, source_relative: str | None) -> list[dict]:
    identity = rules.entrypoint_identity(key)
    needles = [value.lower() for value in (source_relative, identity, Path(identity).name) if value]
    refs = []
    for path in rules.scan_files(clone):
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            lower = line.lower()
            if any(needle in lower for needle in needles):
                refs.append({"path": str(path.relative_to(clone)), "line": number,
                             "line_sha256": __import__("hashlib").sha256(line.encode()).hexdigest()})
                if len(refs) == 20:
                    return refs
    if key.startswith("config:"):
        config = key.split(":", 2)[1]
        config_path = clone / config
        if config_path.is_file():
            refs.append({"path": config, "line": 1,
                         "line_sha256": __import__("hashlib").sha256(config_path.read_bytes()).hexdigest(),
                         "kind": "config_generated_source"})
    return refs


def population():
    paths = sorted(E01_RUN.glob("measurements/*/after/result.json"))
    if len(paths) != 329:
        raise RuntimeError(f"E-01 denominator changed: {len(paths)} != 329")
    repo_successes = {}
    records = [read(path) for path in paths]
    for record in records:
        repo_successes.setdefault(record["repository"], 0)
        repo_successes[record["repository"]] += record["compile"]["status"] == "success"
    evidence_by_repo = {}
    rejected_by_repo = {}
    for repository in sorted({record["repository"] for record in records}):
        accepted, rejected = rules.derive_library_evidence(clone_for(repository))
        evidence_by_repo[repository] = accepted
        rejected_by_repo[repository] = rejected
    rows = []
    for path, record in zip(paths, records):
        report, report_path, source, relative = selected_source(record)
        role, role_reasons = rules.classify_role(record["entrypoint_key"])
        applicable = [row for row in evidence_by_repo[record["repository"]]
                      if rules.evidence_scope(row, record["entrypoint_key"], relative)]
        derived = list(dict.fromkeys(row["path"] for row in applicable))
        libraries = list(dict.fromkeys([*report.get("library_paths", []), *derived]))
        environment = ("setup_success" if record.get("setup_status") == "success" else
                       "partial_environment_reused" if repo_successes[record["repository"]] else
                       "excluded_setup_failure")
        rows.append({
            "identifier": identifier(path), "repository": record["repository"],
            "commit_sha": record["commit_sha"], "entrypoint_key": record["entrypoint_key"],
            "entrypoint": record["entrypoint"], "entrypoint_kind": record.get("entrypoint_kind"),
            "role": role, "role_reasons": role_reasons, "build_references": build_references(
                clone_for(record["repository"]), record["entrypoint_key"], relative),
            "environment_reuse": environment, "source": str(source), "source_relative": relative,
            "source_sha256": record.get("source_sha256"), "project_root": report["project_root"],
            "e01_compile": record["compile"], "e01_preparation": record.get("preparation"),
            "e01_record": ref(path), "e01_discovery_report": ref(report_path),
            "base_library_paths": report.get("library_paths", []),
            "derived_library_evidence": applicable, "library_paths": libraries,
        })
    return rows, evidence_by_repo, rejected_by_repo


def freeze():
    if legacy.digest(F01_BINARY) != EXPECTED_ZKFDO:
        raise RuntimeError("pinned F-01 binary hash mismatch")
    if legacy.digest(CIRCOM) != EXPECTED_CIRCOM:
        raise RuntimeError("pinned Circom hash mismatch")
    RUN.mkdir(parents=True, exist_ok=True)
    tools = RUN / "tools"
    tools.mkdir(exist_ok=True)
    binary = tools / "zkfDO"
    if not binary.exists():
        shutil.copy2(F01_BINARY, binary)
    if legacy.digest(binary) != EXPECTED_ZKFDO:
        raise RuntimeError("E-02 binary copy hash mismatch")
    rows, evidence, rejected = population()
    inventory = RUN / "entrypoint-roles-and-paths-v2.json"
    inventory_data = {"schema_version": 1, "task": "E-02", "created_at": legacy.now(),
                      "denominator": len(rows), "roles": {role: sum(r["role"] == role for r in rows)
                      for role in ("deployment_main", "test_mock_harness")},
                      "repositories": {name: {"accepted_library_evidence": evidence[name],
                                               "rejected_library_literals": rejected[name]}
                                       for name in sorted(evidence)}, "entries": rows,
                      "zkfuzz_invocations": 0}
    if not inventory.exists():
        legacy.write_new(inventory, inventory_data)
    elif read(inventory) != {**inventory_data, "created_at": read(inventory)["created_at"]}:
        raise RuntimeError("frozen E-02 inventory differs")
    # V6 fixes a disjoint last-30 preparation tail before its workers start.
    lock = RUN / "procedure-lock-v6.json"
    role_counts = {role: sum(row["role"] == role for row in rows)
                   for role in ("deployment_main", "test_mock_harness")}
    lock_data = {
        "schema_version": 4, "task": "E-02", "fixed_at": legacy.now(), "owner": "miiz",
        "deadline": "2026-10-08", "procedure": ref(PROCEDURE), "e01_results": ref(E01_RESULTS),
        "inventory": ref(inventory), "supersedes_invalid_preflight_locks": [
        ref(RUN / "procedure-lock.json"), ref(RUN / "procedure-lock-v2.json"),
        ref(RUN / "procedure-lock-v3.json"), ref(RUN / "procedure-lock-v4.json"),
        ref(RUN / "procedure-lock-v5.json")],
        "population": {"all": len(rows), **role_counts}, "caps_seconds": {"compile_primary": 120,
        "compile_sensitivity": 600, "discovery": 900, "instance_capture": 600,
        "wrapper_compile": 60, "prepare_primary": 300, "prepare_sensitivity": 900, "plan": 30,
        "compile_sensitivity_selection": "every E-02 120-second deployment-main timeout"},
        "workers": {"compile_primary": 2, "compile_sensitivity": 4, "preparation_forward": 2,
        "preparation_tail": 2, "preparation_total_max": 4},
        "preparation_tail_rule": "last 30 entries of the fixed preparation selection, assigned before tail workers start",
        "tools": {"circom": ref(CIRCOM), "zkfDO_source": ref(F01_BINARY),
        "zkfDO_copy": ref(binary)}, "zkfuzz_invocations": 0,
    }
    if not lock.exists():
        legacy.write_new(lock, lock_data)
    elif read(lock) != {**lock_data, "fixed_at": read(lock)["fixed_at"]}:
        raise RuntimeError("frozen E-02 lock differs")
    return rows, binary


def compile_capture(source: Path, libraries: list[str], directory: Path, cap: int) -> dict:
    output = directory / "original"
    output.mkdir(parents=True)
    command = [str(CIRCOM), str(source), "--r1cs", "-o", str(output)]
    for library in libraries:
        command.extend(["-l", library])
    capture = legacy.run_command(command, directory / "compile-call", cap)
    result = legacy.brief(capture)
    result.update(failure_type=legacy.failure_type(capture), constraints=None)
    if capture["status"] == "success":
        artifacts = list(output.glob("*.r1cs"))
        if len(artifacts) != 1:
            result.update(status="unknown", reported_status="success",
                          failure_type="r1cs_metadata_unavailable", reason="expected exactly one R1CS")
        else:
            try:
                result.update(constraints=legacy.r1cs_count(artifacts[0]), artifact=ref(artifacts[0]))
            except (OSError, ValueError, struct.error) as error:
                result.update(status="unknown", reported_status="success",
                              failure_type="r1cs_metadata_unavailable", reason=str(error))
    return result


def compile_one(row: dict) -> dict:
    directory = RUN / "compile-measurements" / row["identifier"]
    target = directory / "result.json"
    if target.exists():
        return read(target)
    if directory.exists():
        # No result.json means the standard bounded runner failed before starting
        # Circom (for example, process inspection was unavailable). Preserve only
        # completed records; rerun this entrypoint as one atomic measurement.
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=False)
    result = {"schema_version": 1, "task": "E-02", "identifier": row["identifier"],
              "repository": row["repository"], "commit_sha": row["commit_sha"],
              "entrypoint_key": row["entrypoint_key"], "role": row["role"],
              "environment_reuse": row["environment_reuse"], "started_at": legacy.now(),
              "e01_record": row["e01_record"], "e01_compile": row["e01_compile"],
              "library_paths": row["library_paths"], "derived_library_evidence": row["derived_library_evidence"],
              "compile_120": {"status": "not_started"}, "compile_600": {"status": "not_started"},
              "zkfuzz_executions": 0}
    if row["role"] != "deployment_main":
        result["reason"] = "test_mock_harness"
    elif row["e01_compile"]["status"] == "success":
        result["reason"] = "e01_compile_success_reused"
    elif row["environment_reuse"] == "excluded_setup_failure":
        result["reason"] = "excluded_setup_failure_without_any_e01_compile_success"
    else:
        source = Path(row["source"])
        if not source.is_file() or legacy.digest(source) != row["source_sha256"]:
            result["reason"] = "fixed_source_missing_or_hash_mismatch"
        else:
            result["compile_120"] = compile_capture(source, row["library_paths"], directory / "cap-120", 120)
            if row["e01_compile"]["status"] == "timeout":
                result["compile_600"] = compile_capture(source, row["library_paths"], directory / "cap-600", 600)
    result["finished_at"] = legacy.now()
    legacy.write_new(target, result)
    return result


def run_compile(workers: int):
    rows, _ = freeze()
    deployment = [row for row in rows if row["role"] == "deployment_main"]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(compile_one, row): row for row in deployment}
        for future in as_completed(futures):
            row = futures[future]
            try:
                result = future.result()
                print(json.dumps({"id": row["identifier"], "repo": row["repository"],
                                  "old": row["e01_compile"]["status"],
                                  "cap120": result["compile_120"]["status"],
                                  "cap600": result["compile_600"]["status"]}), flush=True)
            except Exception as error:
                print(json.dumps({"id": row["identifier"],
                                  "error": f"{type(error).__name__}: {error}"}), flush=True)


def effective_new_compile(result: dict) -> dict | None:
    if result["e01_compile"]["status"] == "success":
        return None
    for key in ("compile_120", "compile_600"):
        if result.get(key, {}).get("status") == "success":
            return result[key]
    return None


def sensitivity_selection(rows: list[dict]):
    by_id = {row["identifier"]: row for row in rows if row["role"] == "deployment_main"}
    results = {path.parent.name: read(path) for path in RUN.glob("compile-measurements/*/result.json")}
    if set(results) != set(by_id):
        raise RuntimeError("compile denominator incomplete before 600-second sensitivity")
    selected = [identifier for identifier, result in sorted(results.items())
                if result["compile_120"]["status"] == "timeout"]
    data = {"schema_version": 1, "fixed_at": legacy.now(),
            "selection_rule": "every deployment main whose E-02 120-second compile status is timeout",
            "entries": selected, "count": len(selected), "zkfuzz_invocations": 0}
    target = RUN / "compile-600-selection.json"
    if not target.exists():
        legacy.write_new(target, data)
    elif read(target) != {**data, "fixed_at": read(target)["fixed_at"]}:
        raise RuntimeError("frozen 600-second sensitivity selection differs")
    return [(by_id[identifier], results[identifier]) for identifier in selected]


def sensitivity_one(item: tuple[dict, dict]):
    row, primary = item
    directory = RUN / "compile-600-sensitivity" / row["identifier"]
    target = directory / "result.json"
    if target.exists():
        return read(target)
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    result = {"schema_version": 1, "task": "E-02", "identifier": row["identifier"],
              "repository": row["repository"], "entrypoint_key": row["entrypoint_key"],
              "selection": "e02_compile_120_timeout", "compile_120_result": ref(
                  RUN / "compile-measurements" / row["identifier"] / "result.json"),
              "compile_600": {"status": "not_started"}, "started_at": legacy.now(),
              "zkfuzz_executions": 0}
    # An old-timeout case may already have a 600-second result in the primary record.
    if primary["compile_600"]["status"] != "not_started":
        result["compile_600"] = primary["compile_600"]
        result["reason"] = "primary_record_already_contains_same_600_second_measurement"
    else:
        source = Path(row["source"])
        result["compile_600"] = compile_capture(source, row["library_paths"], directory / "cap-600", 600)
    result["finished_at"] = legacy.now()
    legacy.write_new(target, result)
    return result


def run_sensitivity(workers: int):
    rows, _ = freeze()
    selected = sensitivity_selection(rows)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(sensitivity_one, item): item[0] for item in selected}
        for future in as_completed(futures):
            row = futures[future]
            try:
                result = future.result()
                print(json.dumps({"id": row["identifier"], "repo": row["repository"],
                                  "cap600": result["compile_600"]["status"]}), flush=True)
            except Exception as error:
                print(json.dumps({"id": row["identifier"],
                                  "error": f"{type(error).__name__}: {error}"}), flush=True)


def prepare_selection(rows: list[dict]):
    by_id = {row["identifier"]: row for row in rows}
    selected = []
    results = sorted(RUN.glob("compile-measurements/*/result.json"))
    expected = sum(row["role"] == "deployment_main" for row in rows)
    if len(results) != expected:
        raise RuntimeError(f"compile result denominator incomplete: {len(results)} != {expected}")
    for path in results:
        result = read(path)
        compiled = effective_new_compile(result)
        sensitivity = RUN / "compile-600-sensitivity" / result["identifier"] / "result.json"
        if compiled is None and sensitivity.is_file():
            measured = read(sensitivity)["compile_600"]
            if measured["status"] == "success":
                compiled = measured
        if compiled:
            selected.append({"identifier": result["identifier"], "reason": "new_e02_compile_success",
                             "constraints": compiled["constraints"], "row": by_id[result["identifier"]]})
    anon = next(row for row in rows if row["entrypoint_key"] ==
                "source_main:packages/circuits/src/aadhaar-verifier.circom")
    m01 = M01_RUN / "measurements" / anon["identifier"] / "result.json"
    measured = read(m01)
    if measured.get("preparation", {}).get("failure_type") != "prepare_process_timeout":
        raise RuntimeError("fixed M-01 prepare-timeout sensitivity case changed")
    selected.append({"identifier": anon["identifier"], "reason": "m01_prepare_300_timeout_sensitivity",
                     "constraints": measured["constraints"], "row": anon, "m01_record": ref(m01)})
    out = RUN / "preparation-selection.json"
    data = {"schema_version": 1, "fixed_at": legacy.now(), "selection_rule":
            "all new E-02 deployment-main compile successes plus the fixed M-01 300-second timeout deployment main",
            "entries": [{k: v for k, v in item.items() if k != "row"} for item in selected],
            "count": len(selected), "zkfuzz_invocations": 0}
    if not out.exists():
        legacy.write_new(out, data)
    elif read(out) != {**data, "fixed_at": read(out)["fixed_at"]}:
        raise RuntimeError("frozen E-02 preparation selection differs")
    return selected


def prepare_attempt(binary: Path, manifest: Path, directory: Path, cap: int) -> tuple[dict, dict | None, Path | None]:
    prepared_dir = directory / "prepared"
    capture = legacy.run_command(
        [str(binary), "experiment", "prepare", "--manifest", str(manifest), "--output", str(prepared_dir),
         "--strategy", "small-first", "--circom-bin", str(CIRCOM),
         "--zkfuzz-bin", "/nonexistent/e02-zkfuzz-forbidden",
         "--circomspect-bin", "/nonexistent/e02-analyzer-forbidden", "--tool-timeout-seconds", "60"],
        directory / "prepare-call", cap)
    manifest_data = read(manifest)
    result = legacy.brief(capture)
    result["failure_type"] = legacy.failure_type(capture)
    result["expected_targets"] = len(manifest_data["targets"])
    try:
        path = legacy.locate_report(prepared_dir, "prepared.json")
    except ValueError as error:
        result.update(status="unknown", reason=str(error))
        return result, None, None
    if capture["status"] != "success" or path is None:
        return result, None, path
    prepared = read(path)
    expected = {row["label"]: row for row in manifest_data["targets"]}
    definitions = [row.get("definition") for row in prepared.get("targets", [])]
    try:
        if len(definitions) != len(manifest_data["targets"]):
            raise ValueError("prepared target count mismatch")
        if any(not isinstance(row, dict) for row in definitions):
            raise ValueError("prepared target definition missing")
        if len({row["label"] for row in definitions}) != len(definitions):
            raise ValueError("duplicate prepared target labels")
        for definition in definitions:
            if definition["label"] not in expected:
                raise ValueError("unexpected prepared target label")
            if any(definition.get(key) != value for key, value in expected[definition["label"]].items()):
                raise ValueError("prepared target identity mismatch")
    except (KeyError, TypeError, ValueError) as error:
        result.update(status="unknown", reason=str(error), report=ref(path))
        return result, None, path
    result["report"] = ref(path)
    result["targets"] = len(prepared.get("targets", []))
    result["eligible"] = sum(bool(row.get("eligible")) for row in prepared.get("targets", []))
    result["target_outcomes"] = [{"label": row["definition"]["label"],
                                  "eligible": row.get("eligible"),
                                  "exclusion_reasons": row.get("exclusion_reasons", [])}
                                 for row in prepared.get("targets", [])]
    return result, prepared, path


def prepare_one(item: dict, binary: Path) -> dict:
    row = item["row"]
    directory = RUN / "preparation-measurements" / row["identifier"]
    target = directory / "result.json"
    if target.exists():
        return read(target)
    free_bytes = shutil.disk_usage(RUN).free
    if free_bytes < DISK_GUARD_BYTES:
        raise RuntimeError(f"disk_guard_below_35_gib: {free_bytes} bytes free")
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=False)
    result = {"schema_version": 1, "task": "E-02", "identifier": row["identifier"],
              "repository": row["repository"], "entrypoint_key": row["entrypoint_key"],
              "selection_reason": item["reason"], "constraints": item["constraints"],
              "started_at": legacy.now(), "discovery": {"status": "not_started"},
              "prepare_300": {"status": "not_started"}, "prepare_900": {"status": "not_started"},
              "plan": {"status": "not_started"}, "zkfuzz_executions": 0}
    project_root, source = Path(row["project_root"]), Path(row["source"])
    command = [str(binary), "targets", "--project", str(project_root), "--entrypoint", str(source),
               "--output", str(directory / "discovery"), "--circom-bin", str(CIRCOM),
               "--compile-timeout-seconds", "60", "--instance-capture", "--capture-timeout-seconds", "600"]
    for library in row["library_paths"]:
        command.extend(["--library-path", library])
    capture = legacy.run_command(command, directory / "discover-call", 900)
    result["discovery"] = legacy.brief(capture)
    result["discovery"]["failure_type"] = legacy.failure_type(capture)
    report_path = legacy.locate_report(directory / "discovery", "discovery.json")
    if capture["status"] != "success" or report_path is None:
        result["finished_at"] = legacy.now()
        legacy.write_new(target, result)
        return result
    discovery = read(report_path)
    result["discovery"].update(report=ref(report_path), callsites=len(discovery.get("targets", [])),
                               unique_compile_units=len(discovery.get("compile_units", [])))
    instance = discovery.get("instance_discovery") or {}
    capture_path = Path(instance["capture_path"]) if instance.get("selected") == "compiler" else None
    result["instance_capture"] = {key: instance.get(key) for key in
                                  ("selected", "capture_status", "capture_failure", "compiler_complete",
                                   "interpreter_complete", "capture_compile_seconds")}
    if capture_path:
        result["instance_capture"]["report"] = ref(capture_path)
    try:
        manifest_data = f01.manifest_for(row["repository"], row["commit_sha"], project_root, source,
                                         discovery, [Path(path) for path in row["library_paths"]], capture_path)
    except ValueError as error:
        result["preparation_reason"] = str(error)
        result["finished_at"] = legacy.now()
        legacy.write_new(target, result)
        return result
    manifest = directory / "manifest.json"
    legacy.write_new(manifest, manifest_data)
    result["manifest"] = ref(manifest)
    prepared = None
    prepared_path = None
    if item["reason"] == "new_e02_compile_success":
        result["prepare_300"], prepared, prepared_path = prepare_attempt(binary, manifest, directory / "cap-300", 300)
    if item["reason"] == "m01_prepare_300_timeout_sensitivity" or result["prepare_300"]["status"] == "timeout":
        result["prepare_900"], prepared, prepared_path = prepare_attempt(binary, manifest, directory / "cap-900", 900)
    if prepared is not None and prepared_path is not None:
        plan_capture = legacy.run_command(
            [str(binary), "experiment", "plan", "--prepared", str(prepared_path), "--strategy", "small-first",
             "--config", str(ROOT / "configs/static-ranking.json"), "--output", str(directory / "plan.json")],
            directory / "plan-call", 30)
        result["plan"] = legacy.brief(plan_capture)
        result["plan"]["failure_type"] = legacy.failure_type(plan_capture)
        if (directory / "plan.json").is_file():
            result["plan"]["report"] = ref(directory / "plan.json")
        chosen = result["prepare_900"] if result["prepare_900"]["status"] != "not_started" else result["prepare_300"]
        compact = dict(chosen)
        compact["targets"] = compact.pop("target_outcomes", [])
        result["preparation_outcome"] = classify_preparation(
            {"preparation": compact, "discovery": result["discovery"], "plan": result["plan"]},
            prepared_report=prepared, discovery_report=discovery)
    result["finished_at"] = legacy.now()
    legacy.write_new(target, result)
    return result


def run_prepare(workers: int):
    rows, binary = freeze()
    selection = prepare_selection(rows)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(prepare_one, item, binary): item for item in selection}
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
                print(json.dumps({"id": item["identifier"], "reason": item["reason"],
                                  "discovery": result["discovery"]["status"],
                                  "prepare300": result["prepare_300"]["status"],
                                  "prepare900": result["prepare_900"]["status"]}), flush=True)
            except Exception as error:
                print(json.dumps({"id": item["identifier"],
                                  "error": f"{type(error).__name__}: {error}"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "compile", "sensitivity", "prepare"))
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.stage == "freeze":
        rows, binary = freeze()
        print(json.dumps({"entries": len(rows), "deployment": sum(r["role"] == "deployment_main" for r in rows),
                          "harness": sum(r["role"] == "test_mock_harness" for r in rows),
                          "zkfDO": legacy.digest(binary)}))
    elif args.stage == "compile":
        run_compile(args.workers)
    elif args.stage == "sensitivity":
        run_sensitivity(args.workers)
    else:
        run_prepare(args.workers)


if __name__ == "__main__":
    main()
