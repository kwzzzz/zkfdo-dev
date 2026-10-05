#!/usr/bin/env python3
"""C-03 paired compilation and structural preparation; no search/witness paths.

The fixed C-02 compiler/frontend are reused. Source checkouts, setup, immutable
stage results, generated mains and raw outputs all live in the C-03 run directory.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import json
from pathlib import Path
import shutil
import subprocess
import struct

import measure_c02_preparation as legacy
from collect_c02_repositories import main_declarations, path_roles
import c03_config_entrypoints as config
import c03_environment as environment
from c03_outcomes import normalize_result

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/c03-corpus-2026-10-02"
SETTINGS = {"optimization": "compiler_default_O1", "prime": "bn128",
            "compiler_version": "2.2.3", "original_cap_seconds": 120,
            "discovery_cap_seconds": 300, "preparation_cap_seconds": 300,
            "internal_tool_cap_seconds": 60, "plan_cap_seconds": 30}


def ref(path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(ROOT)), "sha256": legacy.digest(path)}


def read(path):
    return json.loads(Path(path).read_text())


def verified(reference):
    path = ROOT / reference["path"]
    if legacy.digest(path) != reference["sha256"]:
        raise ValueError("reference_hash_mismatch: " + str(path))
    return read(path)


def write_new(path, data):
    legacy.write_new(Path(path), data)


def slug(repo):
    return repo["full_name"].replace("/", "__")


def identifier(repo, entry):
    return __import__("hashlib").sha256((repo["full_name"].lower() + "\0" + entry["key"]).encode()).hexdigest()[:24]


def checkout(repo):
    path = repo.get("clone_path")
    return (ROOT / path).resolve() if path else None


def original_entry(repo, item):
    relative = item["path"] if isinstance(item, dict) else item
    base = checkout(repo)
    return {"key": "source_main:" + relative, "kind": "source_main", "display_path": relative,
            "source_path": relative, "path": str(base / relative) if base else None,
            "expected_sha256": item.get("sha256") if isinstance(item, dict) else None,
            "path_roles": path_roles(relative), "metadata": item if isinstance(item, dict) else {"path": relative}}


def generated_entry(entry):
    identity = entry.get("circomkit_path", entry.get("circuits_path", "unknown")) + ":" + entry.get("config_key", "unknown")
    return {"key": "config:" + identity, "kind": "config_generated", "display_path": "config:" + identity,
            "path": entry.get("path"), "source_path": entry.get("source_path"),
            "expected_sha256": entry.get("sha256"), "path_roles": path_roles(entry.get("source_path", identity)),
            "failure_type": entry.get("failure_type"), "metadata": entry}


def inventory_one(repo, phase, prior=None):
    base = checkout(repo)
    entries = {entry["key"]: copy.deepcopy(entry) for entry in (prior or {}).get("entries", [])}
    if not prior:
        entries = {entry["key"]: entry for entry in (original_entry(repo, item) for item in repo.get("entrypoints", []))}
    row = {"full_name": repo["full_name"], "commit_sha": repo.get("commit_sha"),
           "entries": [], "config_failures": [], "inventory_failures": []}
    if not base or not base.is_dir():
        row.update(entries=list(entries.values()), failure_type="checkout_unavailable")
        return row
    if phase == "after":
        # Only tracked files, including initialized pinned submodules; newly
        # downloaded dependency examples never expand the entrypoint denominator.
        try:
            listing = subprocess.run(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                                      "ls-files", "--recurse-submodules", "-z"], cwd=base, capture_output=True,
                                     check=False, timeout=120)
            if listing.returncode:
                row["inventory_failures"].append({"failure_type": "tracked_inventory_command_failed", "exit_code": listing.returncode})
            else:
                for relative in listing.stdout.decode(errors="surrogateescape").split("\0"):
                    if not relative.endswith(".circom") or "source_main:" + relative in entries:
                        continue
                    source = base / relative
                    try:
                        if not source.resolve().is_relative_to(base) or not source.is_file():
                            raise ValueError("tracked_source_unavailable_or_external")
                        declarations = main_declarations(source.read_text(errors="replace"))
                        if declarations:
                            item = {"path": relative, "sha256": legacy.digest(source), "main_declarations": declarations}
                            entry = original_entry(repo, item)
                            entry["discovered_after_setup"] = True
                            entries[entry["key"]] = entry
                    except (OSError, ValueError) as error:
                        row["inventory_failures"].append({"path": relative, "failure_type": "tracked_source_inspection_failed", "reason": str(error)})
        except (OSError, subprocess.TimeoutExpired) as error:
            row["inventory_failures"].append({"failure_type": "tracked_inventory_unavailable", "reason": str(error)})
    generated_dir = base.parent / ("config-generated-" + phase)
    report_path = base.parent / ("config-generation-" + phase + ".json")
    if report_path.exists():
        generated = read(report_path)
    else:
        generated = config.generate_config_entrypoints(base, generated_dir)
        write_new(report_path, generated)
    row["config_report_ref"] = ref(report_path)
    row["config_failures"] = generated["failures"]
    for item in generated["entries"]:
        entry = generated_entry(item)
        if prior and entry["key"] not in entries:
            entry["discovered_after_setup"] = True
        entries[entry["key"]] = entry
    row["entries"] = [entries[key] for key in sorted(entries)]
    return row


def make_inventory(census_path, phase):
    target = RUN / ("entrypoints-" + phase + ".json")
    if target.exists():
        data = read(target)
        if data["census_ref"] != ref(census_path):
            raise ValueError("inventory_census_changed")
        return data
    census = read(census_path)
    prior = {r["full_name"]: r for r in read(RUN / "entrypoints-before.json")["repositories"]} if phase == "after" else {}
    rows = [inventory_one(repo, phase, prior.get(repo["full_name"])) for repo in census["repositories"]]
    data = {"schema_version": 1, "created_at": legacy.now(), "phase": phase,
            "census_ref": ref(census_path), "repositories": rows,
            "known_entrypoint_count": sum(len(row["entries"]) for row in rows), "zkfuzz_executions": 0}
    write_new(target, data)
    return data


def library_paths(repo, entry, plans):
    base = checkout(repo)
    relative = entry.get("source_path") or "."
    planned = environment.include_paths(base, relative, plans)
    if entry.get("path") and entry["kind"] == "config_generated":
        planned.append(str(Path(entry["path"]).parent))
    planned = list(dict.fromkeys(planned))
    return planned, [path for path in planned if Path(path).is_dir()]


def classification(capture):
    if capture["status"] == "success":
        return None
    if capture["status"] != "failure":
        return capture["status"]
    logs = "\n".join((ROOT / capture[key]["path"]).read_text(errors="replace") for key in ("stdout", "stderr"))
    if "P1014" in logs or "P1010" in logs and "include" in logs.lower():
        return "missing_include"
    return legacy.failure_type(capture) or "compiler_or_tool_error"


def compile_entry(repo, entry, directory, plans, phase="before"):
    path = Path(entry["path"]) if entry.get("path") else None
    if path is None or not path.is_file():
        return {"compile": {"status": "not_started", "failure_type": entry.get("failure_type") or "entrypoint_source_missing",
                            "process_started": False, "constraints": None, "elapsed_seconds": None},
                "source_sha256": None, "library_paths": [], "planned_library_paths": []}
    base = checkout(repo)
    if not path.resolve().is_relative_to(base.parent if entry["kind"] == "config_generated" else base):
        return {"compile": {"status": "not_started", "failure_type": "entrypoint_outside_pinned_project",
                            "process_started": False, "constraints": None, "elapsed_seconds": None},
                "source_sha256": None, "library_paths": [], "planned_library_paths": []}
    source_hash = legacy.digest(path)
    expected = entry.get("expected_sha256")
    if phase == "before" and expected and source_hash != expected:
        return {"compile": {"status": "not_started", "failure_type": "baseline_source_hash_mismatch",
                            "process_started": False, "constraints": None, "elapsed_seconds": None},
                "source_sha256": source_hash, "expected_source_sha256": expected,
                "library_paths": [], "planned_library_paths": []}
    planned, libraries = library_paths(repo, entry, plans)
    destination = directory / "original"
    destination.mkdir()
    command = [str(RUN / "tools/circom"), str(path), "--r1cs", "-o", str(destination)]
    for library in libraries:
        command.extend(["-l", library])
    capture = legacy.run_command(command, directory / "compile-call", 120)
    compiled = legacy.brief(capture)
    compiled.update(failure_type=classification(capture), constraints=None)
    if capture["status"] == "success":
        try:
            artifacts = list(destination.glob("*.r1cs"))
            if len(artifacts) != 1:
                raise ValueError("expected_exactly_one_r1cs")
            compiled.update(constraints=legacy.r1cs_count(artifacts[0]), artifact=ref(artifacts[0]))
        except (OSError, ValueError, struct.error) as error:
            compiled.update(status="unknown", reported_status="success", failure_type="r1cs_metadata_unavailable", reason=str(error))
    return {"compile": compiled, "source_sha256": source_hash, "expected_source_sha256": expected,
            "source_matches_inventory": source_hash == expected if expected else None,
            "planned_library_paths": planned, "library_paths": libraries}


def available_report(result, stage):
    reference = result.get(stage, {}).get("report")
    return verified(reference) if reference else None


def measure(repo, entry, phase, plans):
    directory = RUN / "measurements" / identifier(repo, entry) / phase
    result_path = directory / "result.json"
    if result_path.exists():
        result = read(result_path)
        if result["entrypoint_key"] != entry["key"] or result["commit_sha"] != repo.get("commit_sha"):
            raise ValueError("existing_measurement_identity_mismatch")
        return result
    if directory.exists():
        raise ValueError("unfinished_stage_preserved: " + str(directory))
    directory.mkdir(parents=True)
    result = {"schema_version": 1, "repository": repo["full_name"], "commit_sha": repo.get("commit_sha"),
              "entrypoint_key": entry["key"], "entrypoint": entry["display_path"],
              "entrypoint_kind": entry["kind"], "phase": phase, "started_at": legacy.now(),
              "settings": SETTINGS, "zkfuzz_executions": 0, "manual_interventions": 0}
    result.update(compile_entry(repo, entry, directory, plans, phase))
    if phase == "after":
        before = directory.parent / "before/result.json"
        result["before_ref"] = ref(before) if before.is_file() else None
        setup_path = RUN / "setups" / slug(repo) / "setup.json"
        result["setup_ref"] = ref(setup_path) if setup_path.is_file() else None
        result["setup_status"] = read(setup_path)["status"] if setup_path.is_file() else "unknown"
        result["plan"] = {"status": "not_started", "failure_type": "blocked_by_preparation"}
        result["discovery"] = {"status": "not_started", "failure_type": "entrypoint_source_missing"}
        result["preparation"] = {"status": "not_started", "failure_type": "blocked_by_discovery"}
        if result["source_sha256"]:
            adapted = dict(repo, checkout_path=str(checkout(repo).parent if entry["kind"] == "config_generated" else checkout(repo)))
            try:
                legacy.discover_and_prepare(result, adapted, Path(entry["path"]), directory, result["library_paths"])
            except (OSError, ValueError, KeyError, TypeError) as error:
                result["preparation"].update(status="unknown", failure_type="structural_report_adapter_error",
                                             reason=type(error).__name__ + ": " + str(error))
        try:
            prepared = available_report(result, "preparation")
            discovery = available_report(result, "discovery")
        except (OSError, ValueError, KeyError, TypeError) as error:
            result["preparation"].update(status="unknown", failure_type="structural_report_reference_error",
                                         reason=type(error).__name__ + ": " + str(error))
            prepared, discovery = None, None
        result = normalize_result(result, prepared_report=prepared, discovery_report=discovery)
    result["finished_at"] = legacy.now()
    write_new(result_path, result)
    print(json.dumps({"phase": phase, "repo": repo["full_name"], "entrypoint": entry["display_path"],
                      "compile": result["compile"]["status"], "constraints": result["compile"].get("constraints"),
                      "prepare": result.get("preparation", {}).get("status")}), flush=True)
    return result


def setup_one(repo, inventory, tools):
    directory = RUN / "setups" / slug(repo)
    final = directory / "setup.json"
    if final.exists():
        return read(final)
    base = checkout(repo)
    if not base or not base.is_dir():
        directory.mkdir(parents=True, exist_ok=False)
        result = {"schema_version": 1, "status": "setup_failure", "failure_types": ["checkout_unavailable"],
                  "steps": [], "manual_intervention_count": 0, "zkfuzz_invocations": 0,
                  "automatic_setup": True, "installation_plans": []}
        write_new(final, result)
        return result
    circuit_paths = [entry["source_path"] for entry in inventory["entries"] if entry.get("source_path")]
    result = environment.run_setup(base, circuit_paths, directory, tools, {"submodule": 180, "install": 600})
    post = []
    for plan in result.get("installation_plans", []):
        if not plan.get("install_root"):
            continue
        root = Path(plan["install_root"])
        post.append({"install_root": str(root), "original_lockfile_present": plan.get("lockfile_present"),
                     "resulting_lockfiles": [ref(root / name) for name in environment.LOCKS if (root / name).is_file()]})
    write_new(directory / "post-install-lockfiles.json", {"schema_version": 1, "setup_ref": ref(final), "plans": post})
    print(json.dumps({"phase": "setup", "repo": repo["full_name"], "status": result["status"],
                      "failure_types": result["failure_types"]}), flush=True)
    return result


def ensure_tools(census_path, before_inventory):
    lock_path = RUN / "measurement-lock.json"
    procedure = read(RUN / "procedure-lock.json")
    if legacy.digest(ROOT / procedure["procedure_path"]) != procedure["sha256"]:
        raise ValueError("fixed_procedure_changed")
    if lock_path.exists():
        lock = read(lock_path)
        for item in lock["compiler_tools"] + lock["implementations"]:
            if legacy.digest(ROOT / item["path"]) != item["sha256"]:
                raise ValueError("fixed_tool_or_implementation_changed: " + item["path"])
        if lock["census_ref"] != ref(census_path) or lock["inventory_before_ref"] != ref(before_inventory):
            raise ValueError("fixed_census_or_inventory_changed")
        return
    compiler_tools = []
    for name in ("circom", "zkfDO"):
        origin = ROOT / "runs/c02-corpus-2026-10-02/tools" / name
        destination = RUN / "tools" / name
        if destination.exists():
            if legacy.digest(origin) != legacy.digest(destination):
                raise ValueError("tool_copy_conflict")
        else:
            shutil.copy2(origin, destination)
        compiler_tools.append(ref(destination))
    files = [Path(__file__), ROOT / "scripts/measure_c02_preparation.py", ROOT / "scripts/collect_c02_repositories.py",
             ROOT / "scripts/c03_environment.py", ROOT / "scripts/c03_config_entrypoints.py", ROOT / "scripts/c03_outcomes.py"]
    write_new(lock_path, {"schema_version": 1, "created_at": legacy.now(), "procedure_ref": ref(RUN / "procedure-lock.json"),
                         "census_ref": ref(census_path), "inventory_before_ref": ref(before_inventory),
                         "compiler_tools": compiler_tools, "implementations": [ref(path) for path in files],
                         "workers": 2, "zkfuzz_executions": 0, "settings": SETTINGS,
                         "package_tools_ref": ref(RUN / "tools/tools.json")})


def execute(census_path, phase):
    global RUN
    legacy.RUN = RUN  # Reuse the fixed, read-only C-02 structural adapter in C-03 output directories.
    census = read(census_path)
    before = make_inventory(census_path, "before")
    ensure_tools(census_path, RUN / "entrypoints-before.json")
    repos = {repo["full_name"]: repo for repo in census["repositories"]}
    if phase == "inventory":
        return
    if phase in ("before", "all"):
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = []
            for row in before["repositories"]:
                repo = repos[row["full_name"]]
                paths = [entry["source_path"] for entry in row["entries"] if entry.get("source_path")]
                plans = environment.plan_installations(checkout(repo), paths) if checkout(repo) and checkout(repo).is_dir() else []
                for entry in row["entries"]:
                    pending.append(executor.submit(measure, repo, entry, "before", plans))
            for future in as_completed(pending):
                future.result()
    if phase in ("setup", "all"):
        # Prevent installation from changing the paired baseline while it is being measured.
        for row in before["repositories"]:
            for entry in row["entries"]:
                if not (RUN / "measurements" / identifier(repos[row["full_name"]], entry) / "before/result.json").exists():
                    raise ValueError("setup_requires_complete_baseline")
        tools = read(RUN / "tools/tools.json")
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = [executor.submit(setup_one, repos[row["full_name"]], row, tools) for row in before["repositories"]]
            for future in as_completed(pending):
                future.result()
    if phase in ("after", "all"):
        if any(not (RUN / "setups" / slug(repo) / "setup.json").exists() for repo in repos.values()):
            raise ValueError("post_measurement_requires_recorded_setup_for_all_repositories")
        after = make_inventory(census_path, "after")
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = []
            for row in after["repositories"]:
                repo = repos[row["full_name"]]
                setup = read(RUN / "setups" / slug(repo) / "setup.json")
                for entry in row["entries"]:
                    pending.append(executor.submit(measure, repo, entry, "after", setup.get("installation_plans", [])))
            for future in as_completed(pending):
                future.result()


def main():
    global RUN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, default=RUN)
    parser.add_argument("--phase", choices=("inventory", "before", "setup", "after", "all"), default="all")
    args = parser.parse_args()
    RUN = args.run_dir.resolve()
    execute(args.census.resolve(), args.phase)


if __name__ == "__main__":
    main()
