#!/usr/bin/env python3
"""Rebase every C-03 after-setup source entry onto the recovered checkout.

The prior after results remain immutable instrumentation history. This version
remeasures the complete fixed after inventory in ``after-v4`` and never falls
back to a source or result from the superseded checkout path.
"""

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import measure_c03_corpus as base
import c03_environment_v3 as environment
from c03_outcomes import normalize_result


RUN = base.ROOT / "runs/c03-corpus-2026-10-02/recovery-v3"


def rebase_after_inventory(document, census):
    """Change only source-main absolute paths, preserving every identity field."""
    result = copy.deepcopy(document)
    repositories = census.get("repositories")
    rows = result.get("repositories")
    if not isinstance(repositories, list) or not isinstance(rows, list):
        raise ValueError("recovery_inventory_or_census_invalid")
    by_name = {}
    for repository in repositories:
        name = repository.get("full_name") if isinstance(repository, dict) else None
        if not isinstance(name, str) or name in by_name:
            raise ValueError("duplicate_or_invalid_census_repository")
        by_name[name] = repository
    seen = set()
    count = 0
    for row in rows:
        name = row.get("full_name") if isinstance(row, dict) else None
        if not isinstance(name, str) or name in seen or name not in by_name:
            raise ValueError("duplicate_or_unmatched_inventory_repository")
        seen.add(name)
        repository = by_name[name]
        if row.get("commit_sha") != repository.get("commit_sha"):
            raise ValueError("recovery_inventory_commit_changed")
        clone = repository.get("clone_path")
        if not isinstance(clone, str):
            raise ValueError("recovery_checkout_path_missing")
        checkout = Path(clone)
        checkout = checkout if checkout.is_absolute() else base.ROOT / checkout
        checkout = checkout.resolve()
        keys = set()
        entries = row.get("entries")
        if not isinstance(entries, list):
            raise ValueError("recovery_inventory_entries_missing")
        for entry in entries:
            key = entry.get("key") if isinstance(entry, dict) else None
            if not isinstance(key, str) or key in keys:
                raise ValueError("duplicate_or_invalid_inventory_entrypoint")
            keys.add(key)
            if entry.get("kind") == "source_main":
                relative = entry.get("source_path")
                if not isinstance(relative, str):
                    raise ValueError("source_main_relative_path_missing")
                target = (checkout / relative).resolve()
                if not target.is_relative_to(checkout):
                    raise ValueError("source_main_path_outside_recovery_checkout")
                entry["path"] = str(target)
            count += 1
    if seen != set(by_name):
        raise ValueError("recovery_inventory_repository_set_changed")
    if result.get("known_entrypoint_count") != count:
        raise ValueError("recovery_inventory_entrypoint_count_changed")
    return result


def _report(result, stage):
    try:
        return base.available_report(result, stage)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["preparation"].update(status="unknown", failure_type="structural_report_reference_error",
                                     reason=type(error).__name__ + ": " + str(error))
        return None


def measure_after(repository, entry, plans):
    directory = RUN / "measurements" / base.identifier(repository, entry) / "after-v4"
    result_path = directory / "result.json"
    if result_path.exists():
        result = base.read(result_path)
        identity = (result.get("repository"), result.get("commit_sha"), result.get("entrypoint_key"),
                    result.get("entrypoint_kind"), result.get("phase"))
        expected = (repository["full_name"], repository.get("commit_sha"), entry["key"], entry["kind"], "after")
        if identity != expected:
            raise ValueError("existing_v4_measurement_identity_mismatch")
        return result
    if directory.exists():
        raise ValueError("unfinished_v4_stage_preserved: " + str(directory))
    directory.mkdir(parents=True)
    result = {"schema_version": 1, "repository": repository["full_name"],
              "commit_sha": repository.get("commit_sha"), "entrypoint_key": entry["key"],
              "entrypoint": entry["display_path"], "entrypoint_kind": entry["kind"],
              "phase": "after", "physical_result_directory": "after-v4",
              "started_at": base.legacy.now(), "settings": base.SETTINGS,
              "zkfuzz_executions": 0, "manual_interventions": 0}
    result.update(base.compile_entry(repository, entry, directory, plans, "after"))
    before = directory.parent / "before/result.json"
    setup_path = RUN / "setups" / base.slug(repository) / "setup.json"
    result["before_ref"] = base.ref(before) if before.is_file() else None
    result["setup_ref"] = base.ref(setup_path) if setup_path.is_file() else None
    result["setup_status"] = base.read(setup_path)["status"] if setup_path.is_file() else "unknown"
    result["plan"] = {"status": "not_started", "failure_type": "blocked_by_preparation"}
    result["discovery"] = {"status": "not_started", "failure_type": "entrypoint_source_missing"}
    result["preparation"] = {"status": "not_started", "failure_type": "blocked_by_discovery"}
    if result["source_sha256"]:
        adapted = dict(repository, checkout_path=str(base.checkout(repository).parent
                       if entry["kind"] == "config_generated" else base.checkout(repository)))
        try:
            base.legacy.discover_and_prepare(result, adapted, Path(entry["path"]), directory,
                                             result["library_paths"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            result["preparation"].update(status="unknown", failure_type="structural_report_adapter_error",
                                         reason=type(error).__name__ + ": " + str(error))
    prepared = _report(result, "preparation")
    discovery = _report(result, "discovery")
    result = normalize_result(result, prepared_report=prepared, discovery_report=discovery)
    result["finished_at"] = base.legacy.now()
    base.write_new(result_path, result)
    print(base.json.dumps({"phase": "after-v4", "repo": repository["full_name"],
                           "entrypoint": entry["display_path"], "compile": result["compile"]["status"],
                           "constraints": result["compile"].get("constraints"),
                           "prepare": result["preparation"]["status"]}), flush=True)
    return result


def initialize(census_path):
    base.RUN = RUN
    base.environment = environment
    prior_path = RUN / "entrypoints-after.json"
    target_path = RUN / "entrypoints-after.v4.json"
    if target_path.exists():
        target = base.read(target_path)
    else:
        target = rebase_after_inventory(base.read(prior_path), base.read(census_path))
        base.write_new(target_path, target)
    expected = rebase_after_inventory(base.read(prior_path), base.read(census_path))
    if target != expected:
        raise ValueError("fixed_v4_after_inventory_changed")
    controls = RUN / "path-controls-v4/controls.json"
    if not controls.is_file() or base.read(controls).get("status") != "passed":
        raise ValueError("v4_path_controls_not_passed")
    selection_path = RUN / "final-measurement-selection.v4.json"
    prior_records = sorted(path for path in RUN.glob("measurements/*/after/result.json"))
    prior_incomplete = sorted(path for path in RUN.glob("measurements/*/after")
                              if not (path / "result.json").is_file())
    setups = sorted(RUN.glob("setups/*/setup.json"))
    data = {"schema_version": 4, "fixed_at": base.legacy.now(),
            "reason": "Rebase frozen source-main paths to the recovered checkout and remeasure every after entry.",
            "active_after_directory": "after-v4", "after_inventory_ref": base.ref(target_path),
            "prior_after_inventory_ref": base.ref(prior_path),
            "prior_after_interruption_ref": base.ref(RUN / "after-controller-interruption.v3.json"),
            "prior_after_records": [base.ref(path) for path in prior_records],
            "prior_incomplete_after_paths": [str(path.relative_to(base.ROOT)) for path in prior_incomplete],
            "path_controls_ref": base.ref(controls), "census_ref": base.ref(census_path),
            "before_inventory_ref": base.ref(RUN / "entrypoints-before.json"),
            "setup_records": [base.ref(path) for path in setups],
            "implementations": [base.ref(Path(__file__)), base.ref(Path(base.__file__)),
                                base.ref(Path(environment.__file__))],
            "all_after_entries_remeasured": True, "selection_scope": "all_fixed_after_entries",
            "fixed_before_active_measurement": True, "workers": 2, "zkfuzz_executions": 0}
    if selection_path.exists():
        if base.read(selection_path) != data:
            # Fixed timestamps differ when reconstructing; compare all authority fields.
            existing = base.read(selection_path)
            if any(existing.get(key) != value for key, value in data.items() if key != "fixed_at"):
                raise ValueError("final_v4_measurement_selection_changed")
    else:
        base.write_new(selection_path, data)
    return target


def execute(census_path):
    inventory = initialize(census_path)
    repositories = {row["full_name"]: row for row in base.read(census_path)["repositories"]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = []
        for row in inventory["repositories"]:
            repository = repositories[row["full_name"]]
            setup = base.read(RUN / "setups" / base.slug(repository) / "setup.json")
            plans = setup.get("installation_plans", [])
            for entry in row["entries"]:
                pending.append(executor.submit(measure_after, repository, entry, plans))
        for future in as_completed(pending):
            future.result()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, default=RUN / "census.v3.json")
    parser.add_argument("--initialize-only", action="store_true")
    args = parser.parse_args()
    census = args.census.resolve()
    if args.initialize_only:
        initialize(census)
    else:
        execute(census)


if __name__ == "__main__":
    main()
