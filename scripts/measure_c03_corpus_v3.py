#!/usr/bin/env python3
"""Clean all-repository C-03 setup restart after the pnpm invocation defect.

The fixed v1 pre-installation measurements are reused without changing bytes.
All repository commits and selection metadata remain fixed. Both setup history
and the corrected command's offline controls remain linked in the new lock.
"""

import argparse
import copy
from pathlib import Path
import shutil

import measure_c03_corpus as base
import c03_environment_v3 as environment
import c03_environment_v2 as coverage

ORIGINAL = base.ROOT / "runs/c03-corpus-2026-10-02"
RECOVERY = ORIGINAL / "recovery-v3"


def copied(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if base.legacy.digest(source) != base.legacy.digest(destination):
            raise ValueError("reused_metadata_identity_changed")
    else:
        with destination.open("xb") as output, source.open("rb") as original:
            shutil.copyfileobj(original, output)


def identical_selection(original, recovered):
    left = {r["full_name"]: r for r in original["repositories"]}
    right = {r["full_name"]: r for r in recovered["repositories"]}
    if left.keys() != right.keys() or len(left) != len(original["repositories"]) or len(right) != len(recovered["repositories"]):
        raise ValueError("recovery_repository_set_changed")
    for name, row in left.items():
        before, after = copy.deepcopy(row), copy.deepcopy(right[name])
        before.pop("clone_path", None)
        after.pop("clone_path", None)
        if before != after:
            raise ValueError("recovery_metadata_changed: " + name)
    return right


def initialize(census):
    lock_path = RECOVERY / "measurement-recovery-lock.v3.json"
    if lock_path.exists():
        lock = base.read(lock_path)
        if lock["recovery_census_ref"] != base.ref(census):
            raise ValueError("recovery_census_changed")
        for pin in lock["implementations"]:
            if base.legacy.digest(base.ROOT / pin["path"]) != pin["sha256"]:
                raise ValueError("recovery_implementation_changed")
        base.ensure_tools(census, RECOVERY / "entrypoints-before.json")
        return
    if (RECOVERY / "setups").exists():
        raise ValueError("recovery_must_be_pinned_before_setup")
    old_census = ORIGINAL / "census.v2.json"
    repos = identical_selection(base.read(old_census), base.read(census))
    original_inventory = ORIGINAL / "entrypoints-before.json"
    before = copy.deepcopy(base.read(original_inventory))
    before["census_ref"] = base.ref(census)
    before["baseline_inventory_source_ref"] = base.ref(original_inventory)
    baseline_records = []
    equivalence = []
    for repository in before["repositories"]:
        repo = repos[repository["full_name"]]
        checkout = base.checkout(repo)
        for entry in repository["entries"]:
            identifier = base.identifier(repo, entry)
            old_result = ORIGINAL / "measurements" / identifier / "before/result.json"
            new_result = RECOVERY / "measurements" / identifier / "before/result.json"
            copied(old_result, new_result)
            baseline_records.append({"original": base.ref(old_result), "reused": base.ref(new_result)})
            relative = entry.get("source_path")
            source = checkout / relative if checkout and relative else None
            expected = entry.get("metadata", {}).get("source_sha256") if entry["kind"] == "config_generated" else base.read(old_result).get("source_sha256")
            current = base.legacy.digest(source) if source and source.is_file() else None
            status = "matched" if expected and current == expected else "missing" if current is None else "mismatch"
            equivalence.append({"repository": repo["full_name"], "entrypoint_key": entry["key"],
                                "source_path": relative, "expected_sha256": expected,
                                "current_sha256": current, "status": status})
            if status != "matched":
                raise ValueError("clean_recovery_source_not_identical: " + repo["full_name"] + ":" + entry["key"])
    target_inventory = RECOVERY / "entrypoints-before.json"
    if target_inventory.exists():
        if base.read(target_inventory) != before:
            raise ValueError("reused_inventory_changed")
    else:
        base.write_new(target_inventory, before)
    for relative in ("procedure-lock.json", "tools/tools.json", "tools/tools-lock.json"):
        copied(ORIGINAL / relative, RECOVERY / relative)
    base.ensure_tools(census, target_inventory)
    setup_dirs = sorted(path for path in (ORIGINAL / "setups").iterdir() if path.is_dir())
    complete = [path / "setup.json" for path in setup_dirs if (path / "setup.json").is_file()]
    incomplete = [path for path in setup_dirs if not (path / "setup.json").is_file()]
    controls = ORIGINAL / "manager-cli-controls-v3-2/controls.json"
    files = [Path(__file__), Path(environment.__file__), Path(coverage.__file__)]
    base.write_new(lock_path, {
        "schema_version": 3, "frozen_at": base.legacy.now(),
        "reason": "Pinned pnpm rejected two unnamespaced config options; all repositories restart clean with corrected, offline-validated CLI.",
        "original_census_ref": base.ref(old_census), "recovery_census_ref": base.ref(census),
        "clean_checkout_lock_ref": base.ref(RECOVERY / "recovery-lock.v3.json"),
        "original_measurement_lock_ref": base.ref(ORIGINAL / "measurement-lock.json"),
        "original_inventory_before_ref": base.ref(original_inventory), "inventory_before_ref": base.ref(target_inventory),
        "original_setup_interruption_ref": base.ref(ORIGINAL / "setup-controller-interruption.v2.json"),
        "original_setup_records": [base.ref(path) for path in complete],
        "original_incomplete_setup_paths": [str(path.relative_to(base.ROOT)) for path in incomplete],
        "original_setup_summary": {"completed_repositories": len(complete), "incomplete_repositories": len(incomplete),
            "not_started_repositories": len(repos) - len(setup_dirs),
            "known_elapsed_seconds": sum(base.read(path).get("elapsed_seconds", 0) for path in complete),
            "incomplete_cost_unknown": bool(incomplete)},
        "baseline_records": baseline_records, "clean_source_equivalence": equivalence,
        "implementations": [base.ref(path) for path in files], "manager_controls_ref": base.ref(controls),
        "all_repository_clean_restart": True, "compilation_and_preparation": "unchanged_v1",
        "workers": 2, "zkfuzz_executions": 0, "fixed_before_setup": True})


def execute(census, phase):
    base.RUN = RECOVERY
    initialize(census)
    base.environment = environment
    if phase != "initialize":
        base.execute(census, phase)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, default=RECOVERY / "census.v3.json")
    parser.add_argument("--phase", choices=("initialize", "setup", "after"), required=True)
    args = parser.parse_args()
    execute(args.census.resolve(), args.phase)


if __name__ == "__main__":
    main()
