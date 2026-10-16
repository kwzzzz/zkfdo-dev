#!/usr/bin/env python3
"""Inventory A candidate metadata for J without parsing candidate contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MAIN_QUEUE = Path("runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json")
MAIN_RUN = Path("runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex")
PRAGMA_QUEUE = Path("runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json")
PRAGMA_RUN = Path("runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex")
MEM20_QUEUE = Path("runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json")
MEM20_RUN = Path("runs/n6-a3-2026-10-08.noindex/mem20-execute-2.noindex")
TARGET_ID_MAP = Path("runs/n6-a3-2026-10-08.noindex/pragma-b/target-id-map.json")
PREPARATION_UNITS = Path("runs/n6-a1-2026-10-07/preparation-units.json")
TARGETS_A = Path("docs/n6_targets_a_2026-10-07.json")
DEFAULT_OUTPUT = Path("runs/n6-j1-2026-10-09.noindex/candidate-inventory.json")
DEFAULT_REVISIONS = Path("runs/n6-j1-2026-10-09.noindex/revision-manifest.json")
EXPECTED = {"main": {"W": 2276, "S": 581}, "mem20": {"W": 0, "S": 69}}
PRAGMA_IDENTIFIERS = {"aq-035-8f826c822cb8", "aq-036-6d7df64759b6"}


class InventoryError(RuntimeError):
    """A source or metadata inconsistency requiring a stop."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryError(message)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_file(root: Path, path_text: str, expected_sha: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = root / path
    require(path.is_file(), f"missing file: {path}")
    require(sha256_file(path) == expected_sha, f"SHA-256 mismatch: {path}")
    return path


def select_unpressured_run(unit_state: dict[str, Any]) -> dict[str, Any]:
    runs = unit_state.get("runs")
    require(isinstance(runs, list), "missing unit runs")
    available = [run for run in runs if run.get("environment", {}).get("environment_pressure") is False]
    require(bool(available), "unit has no unpressured run")
    selected = max(available, key=lambda run: run["run_number"])
    require(unit_state.get("selected_run_number") == selected["run_number"],
            "state selected_run_number differs from last unpressured run")
    require(unit_state.get("status") in {"completed_unpressured", "completed_unpressured_retry"},
            "unit state is not completed unpressured")
    return selected


def load_source(root: Path, queue_name: Path, run_name: Path) -> dict[str, Any]:
    queue_path = root / queue_name
    run_root = root / run_name
    queue = read_json(queue_path)
    state = read_json(run_root / "state.json")
    queue_sha = sha256_file(queue_path)
    require(state.get("queue_sha256") == queue_sha, f"state queue SHA mismatch: {run_name}")
    require(state.get("status") == "completed", f"run not completed: {run_name}")
    units = queue.get("units")
    require(isinstance(units, list), f"queue units invalid: {queue_name}")
    by_id = {unit["unit_id"]: unit for unit in units}
    require(len(by_id) == len(units), f"duplicate queue unit_id: {queue_name}")
    require(set(by_id) == set(state.get("units", {})), f"queue/state units differ: {run_name}")
    return {"queue_name": queue_name, "queue_sha256": queue_sha, "queue": queue,
            "units": by_id, "state": state, "run_root": run_root}


def selected_spec(root: Path, unit: dict[str, Any], method: str) -> tuple[str, str, dict[str, Any]]:
    stem = "whole" if method == "W" else "split"
    key = f"{stem}_spec" if f"{stem}_spec" in unit else f"source_{stem}_spec"
    spec_name = unit[key]
    spec_sha = unit[f"{key}_sha256"]
    spec = read_json(checked_file(root, spec_name, spec_sha))
    require(spec.get("method") == ("whole" if method == "W" else "split"),
            f"spec method mismatch: {spec_name}")
    return spec_name, spec_sha, spec


def map_original_ids(root: Path) -> dict[str, str]:
    mapping = read_json(root / TARGET_ID_MAP).get("mapping")
    require(isinstance(mapping, list), "target-id mapping missing")
    result: dict[str, str] = {}
    for row in mapping:
        new_id, old_id = row["new_target_id"], row["old_target_id"]
        require(new_id not in result, "duplicate corrected target id")
        result[new_id] = old_id
    return result


def campaign_candidates(root: Path, source: dict[str, Any], unit: dict[str, Any],
                        lane: str, original_ids: dict[str, str],
                        seen_sha: set[str]) -> list[dict[str, Any]]:
    unit_id = unit["unit_id"]
    unit_state = source["state"]["units"][unit_id]
    selected_run = select_unpressured_run(unit_state)
    rows: list[dict[str, Any]] = []
    spec_details = {method: selected_spec(root, unit, method) for method in ("W", "S")}
    for method in ("W", "S"):
        spec_name, spec_sha, spec = spec_details[method]
        method_state = selected_run.get("methods", {}).get(method)
        require(isinstance(method_state, dict) and method_state.get("status") == "completed",
                f"selected method incomplete: {unit_id}/{method}")
        ledger_name, ledger_sha = method_state["ledger"], method_state["ledger_sha256"]
        ledger_path = checked_file(root, ledger_name, ledger_sha)
        require(ledger_path.is_relative_to(source["run_root"]), f"ledger outside run: {ledger_name}")
        require(ledger_path.parts[-3:] == (method, "campaign", "ledger.json"),
                f"ledger method path mismatch: {ledger_name}")
        ledger = read_json(ledger_path)
        require(ledger.get("spec_sha256") == spec_sha
                and ledger.get("method") == ("whole" if method == "W" else "split"),
                f"ledger/spec mismatch: {ledger_name}")
        require(ledger.get("status") == "completed", f"ledger incomplete: {ledger_name}")
        targets = spec.get("targets")
        attempts = ledger.get("attempts")
        require(isinstance(targets, list) and isinstance(attempts, list),
                f"targets/attempts malformed: {ledger_name}")
        attempt_indices: set[int] = set()
        for attempt in attempts:
            attempt_index = attempt.get("attempt_index")
            require(isinstance(attempt_index, int) and attempt_index >= 0 and attempt_index not in attempt_indices,
                    f"invalid or duplicate attempt index: {ledger_name}")
            attempt_indices.add(attempt_index)
            target_index = attempt.get("target_index")
            target_id = attempt.get("target_id")
            require(isinstance(target_index, int) and 0 <= target_index < len(targets),
                    f"target index outside spec: {ledger_name}")
            target = targets[target_index]
            require(target_id == target.get("target_id"), f"target id differs from spec: {ledger_name}")
            completion = attempt.get("completion_offset_seconds")
            require(isinstance(completion, (int, float)) and completion >= 0,
                    f"invalid completion offset: {ledger_name}")
            candidates = attempt.get("candidates")
            require(isinstance(candidates, list), f"candidates malformed: {ledger_name}")
            for candidate_index, candidate in enumerate(candidates):
                require(candidate.get("duplicate_of") is None, f"duplicate candidate: {ledger_name}")
                relative = Path(candidate["path"])
                require(not relative.is_absolute(), f"absolute candidate path in ledger: {ledger_name}")
                candidate_path = (ledger_path.parent / relative).resolve(strict=True)
                require(candidate_path.is_relative_to(ledger_path.parent.resolve()),
                        f"candidate path leaves campaign: {ledger_name}")
                candidate_sha = candidate["sha256"]
                require(sha256_file(candidate_path) == candidate_sha,
                        f"candidate SHA mismatch: {candidate_path}")
                require(candidate_sha not in seen_sha, f"candidate SHA repeats: {candidate_path}")
                seen_sha.add(candidate_sha)
                row = {
                    "lane": lane,
                    "identifier": unit["identifier"],
                    "unit_id": unit_id,
                    "seed": unit["seed"],
                    "method": method,
                    "attempt_index": attempt_index,
                    "candidate_index": candidate_index,
                    "completion_offset_seconds": completion,
                    "target_id": target_id,
                    "target_index": target_index,
                    "source_snapshot_id": target["source_snapshot_id"],
                    "candidate_path": str(candidate_path),
                    "candidate_sha256": candidate_sha,
                    "selected_queue": str(source["queue_name"]),
                    "selected_queue_sha256": source["queue_sha256"],
                    "whole_spec": spec_details["W"][0],
                    "whole_spec_sha256": spec_details["W"][1],
                    "split_spec": spec_details["S"][0],
                    "split_spec_sha256": spec_details["S"][1],
                    "selected_run_number": selected_run["run_number"],
                    "ledger": ledger_name,
                    "ledger_sha256": ledger_sha,
                }
                if target_id in original_ids:
                    row["original_target_id"] = original_ids[target_id]
                rows.append(row)
    return rows


def git_commit_present(path: Path, revision: str) -> bool:
    if not (path / ".git").exists():
        return False
    result = subprocess.run(["git", "-C", str(path), "cat-file", "-t", revision],
                            capture_output=True, text=True, check=False, timeout=10)
    require(result.returncode == 0 and result.stdout.strip() == "commit",
            f"recorded Git commit missing: {path} {revision}")
    return True


def preflight_library_paths(target: dict[str, Any], snapshot_path: Path) -> list[str]:
    command = target.get("preflight_compile_command")
    require(isinstance(command, list), "preflight compile command missing")
    libraries: list[str] = []
    for index, arg in enumerate(command):
        if arg == "-l":
            require(index + 1 < len(command), "dangling -l in preflight command")
            value = command[index + 1].replace("{workspace}", str(snapshot_path))
            libraries.append(str(Path(value).resolve()))
    require(bool(libraries), "preflight library paths missing")
    return libraries


def revision_manifest(root: Path, main_source: dict[str, Any],
                      pragma_source: dict[str, Any]) -> dict[str, Any]:
    preparation = read_json(root / PREPARATION_UNITS)
    target_list = read_json(root / TARGETS_A)
    prep_by_id = {row["unit_id"]: row for row in
                  preparation["development_units"] + preparation["aq_stage1_units"]}
    target_by_id = {row["id"]: row for row in target_list["items"]}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for original_unit in main_source["queue"]["units"]:
        identifier = original_unit["identifier"]
        if identifier in seen:
            continue
        seen.add(identifier)
        selected_unit = (pragma_source if identifier in PRAGMA_IDENTIFIERS else main_source)["units"][original_unit["unit_id"]]
        w_name, w_sha, w_spec = selected_spec(root, selected_unit, "W")
        original_w = selected_spec(root, original_unit, "W")[2]
        target = w_spec["targets"][0]
        snapshots = {item["id"]: item for item in w_spec["source_snapshots"]}
        snapshot = snapshots[target["source_snapshot_id"]]
        project_root = Path(snapshot["path"]).resolve()
        entrypoint = project_root / target["entrypoint_relative"]
        require(entrypoint.is_file(), f"W entrypoint missing: {entrypoint}")
        require(sha256_file(entrypoint) == target["entrypoint_sha256"],
                f"W entrypoint SHA mismatch: {entrypoint}")
        original_target = original_w["targets"][0]
        original_snapshots = {item["id"]: item for item in original_w["source_snapshots"]}
        original_project = Path(original_snapshots[original_target["source_snapshot_id"]]["path"]).resolve()
        revision = w_spec["recorded_revision"]
        require(original_w["recorded_revision"] == revision, f"revision differs: {identifier}")
        prep = prep_by_id[identifier]
        require(prep["revision"] == revision, f"preparation revision differs: {identifier}")
        source_project = (root / prep["source"]).resolve() if "source" in prep else original_project
        git_path = original_project if (original_project / ".git").exists() else source_project
        git_verified = git_commit_present(git_path, revision)
        item_ids = prep.get("item_ids", [])
        cases = []
        for item_id in item_ids:
            source_item = target_by_id[item_id]
            original_input = source_item["original_input"]
            cases.append({"item_id": item_id, "dataset_case": source_item["dataset_case"],
                          "original_input_path": original_input.get("path"),
                          "original_input_sha256": original_input.get("sha256"),
                          "original_input_exists": original_input.get("exists")})
        rows.append({
            "identifier": identifier,
            "unit_id": selected_unit["unit_id"],
            "seed": selected_unit["seed"],
            "phase": selected_unit["phase"],
            "revision_kind": prep["revision_kind"],
            "revision_commit": revision,
            "git_repository_path": str(git_path) if git_verified else None,
            "source_project_path": str(source_project),
            "whole_spec": w_name,
            "whole_spec_sha256": w_sha,
            "entrypoint_relative": target["entrypoint_relative"],
            "entrypoint_absolute": str(entrypoint),
            "entrypoint_sha256": target["entrypoint_sha256"],
            "project_root": str(project_root),
            "source_snapshot_id": target["source_snapshot_id"],
            "preflight_library_paths": preflight_library_paths(target, project_root),
            "item_ids": item_ids,
            "dataset_cases": cases,
        })
    require(len(rows) == 27, f"expected 27 revisions, found {len(rows)}")
    return {"schema_version": 1, "status": "verified", "revision_count": len(rows), "rows": rows}


def build(root: Path, expected: dict[str, dict[str, int]] = EXPECTED) -> tuple[dict[str, Any], dict[str, Any]]:
    main = load_source(root, MAIN_QUEUE, MAIN_RUN)
    pragma = load_source(root, PRAGMA_QUEUE, PRAGMA_RUN)
    mem20 = load_source(root, MEM20_QUEUE, MEM20_RUN)
    require(len(main["queue"]["units"]) == 81 and len(pragma["queue"]["units"]) == 6
            and len(mem20["queue"]["units"]) == 12, "unexpected queue unit counts")
    require({u["identifier"] for u in pragma["queue"]["units"]} == PRAGMA_IDENTIFIERS,
            "pragma queue targets differ")
    original_ids = map_original_ids(root)
    seen_sha: set[str] = set()
    rows: list[dict[str, Any]] = []
    for unit in main["queue"]["units"]:
        source = pragma if unit["identifier"] in PRAGMA_IDENTIFIERS else main
        rows.extend(campaign_candidates(root, source, source["units"][unit["unit_id"]],
                                        "main", original_ids, seen_sha))
    for unit in mem20["queue"]["units"]:
        rows.extend(campaign_candidates(root, mem20, unit, "mem20", original_ids, seen_sha))
    counts = {lane: {method: sum(row["lane"] == lane and row["method"] == method for row in rows)
                     for method in ("W", "S")} for lane in ("main", "mem20")}
    require(counts == expected, f"candidate counts differ: {counts} != {expected}")
    require(len(seen_sha) == len(rows), "candidate SHA values not globally unique")
    by_identifier = {lane: dict(Counter(row["identifier"] for row in rows if row["lane"] == lane))
                     for lane in ("main", "mem20")}
    inventory = {"schema_version": 1, "status": "verified", "counts": counts,
                 "candidate_count": len(rows), "by_identifier": by_identifier, "rows": rows}
    revisions = revision_manifest(root, main, pragma)
    return inventory, revisions


def write_new_json(path: Path, value: dict[str, Any]) -> None:
    require(not path.exists(), f"refuse to overwrite existing evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--revision-output", type=Path, default=DEFAULT_REVISIONS)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    inventory, revisions = build(root)
    output = args.output if args.output.is_absolute() else root / args.output
    revision_output = (args.revision_output if args.revision_output.is_absolute()
                       else root / args.revision_output)
    require(output != revision_output, "inventory and revision output paths match")
    require(not output.exists() and not revision_output.exists(), "output already exists")
    write_new_json(output, inventory)
    write_new_json(revision_output, revisions)
    print(json.dumps({"inventory": str(output), "revision_manifest": str(revision_output),
                      "counts": inventory["counts"], "revisions": revisions["revision_count"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
