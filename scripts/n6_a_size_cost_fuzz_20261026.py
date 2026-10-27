#!/usr/bin/env python3
"""Read official A campaign metadata through an injected read-only reader.

No engine, subprocess, candidate file, directory enumeration, or file write is
used here. Campaign wall and process wall remain separate measurements.
"""

from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
from typing import Any


PRAGMA_REVISIONS = {"aq-035-8f826c822cb8", "aq-036-6d7df64759b6"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _seconds(value: Any, label: str) -> float:
    _require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
             f"invalid nonnegative seconds: {label}")
    return float(value)


def _source(queue_path: Any, state_path: Any, reader: Any) -> dict[str, Any]:
    state_path = reader.abspath(state_path)
    queue_path = reader.abspath(queue_path)
    state = reader.json(state_path)
    _require(state.get("schema_version") == 4 and state.get("status") == "completed",
             f"official source state is not completed schema 4: {state_path}")
    queue = reader.json(queue_path, state["queue_sha256"])
    _require(queue.get("schema_version") == 4 and isinstance(queue.get("units"), list),
             f"invalid official queue: {queue_path}")
    units = queue["units"]
    by_id = {unit["unit_id"]: unit for unit in units}
    _require(len(by_id) == len(units) == queue.get("unit_count"),
             f"queue unit count or duplicate identity: {queue_path}")
    _require(set(by_id) == set(state.get("units", {})),
             f"queue/state unit identities differ: {state_path}")
    return {"units": units, "by_id": by_id, "state": state,
            "queue_path": str(queue_path), "state_path": str(state_path)}


def _selected(unit_state: dict[str, Any], unit_id: str) -> dict[str, Any]:
    _require(unit_state.get("status") in {"completed_unpressured", "completed_unpressured_retry"},
             f"unit is not completed without pressure: {unit_id}")
    runs = unit_state.get("runs")
    _require(isinstance(runs, list), f"missing source runs: {unit_id}")
    numbers = [run.get("run_number") for run in runs]
    _require(all(type(number) is int and number > 0 for number in numbers)
             and len(numbers) == len(set(numbers)), f"invalid source run numbers: {unit_id}")
    available = [run for run in runs
                 if run.get("environment", {}).get("environment_pressure") is False]
    _require(bool(available), f"no unpressured source run: {unit_id}")
    selected = max(available, key=lambda run: run["run_number"])
    _require(unit_state.get("selected_run_number") == selected["run_number"],
             f"selected run is not the last unpressured run: {unit_id}")
    return selected


def _method_metadata(unit: dict[str, Any], selected: dict[str, Any], method: str,
                     source: dict[str, Any], reader: Any) -> dict[str, Any]:
    stem, name, cap = ("whole", "whole", 600) if method == "W" else ("split", "split", 30)
    key = f"{stem}_spec" if f"{stem}_spec" in unit else f"source_{stem}_spec"
    spec_path = reader.abspath(unit[key])
    spec_sha = unit[f"{key}_sha256"]
    spec = reader.json(spec_path, spec_sha)
    _require(spec.get("schema_version") == 1 and spec.get("method") == name,
             f"invalid official spec identity: {spec_path}")
    _require(spec.get("initial_seed") == unit["seed"], f"spec seed differs: {spec_path}")
    _require(spec.get("total_budget_seconds") == 600 and spec.get("attempt_cap_seconds") == cap,
             f"official A budget differs: {spec_path}")
    receipt = selected.get("methods", {}).get(method)
    _require(isinstance(receipt, dict) and receipt.get("status") == "completed"
             and receipt.get("exit_code") == 0, f"source method incomplete: {unit['unit_id']}/{method}")
    ledger_path = reader.abspath(receipt["ledger"])
    _require(ledger_path.is_relative_to(Path(source["state_path"]).parent)
             and ledger_path.parts[-3:] == (method, "campaign", "ledger.json"),
             f"ledger outside selected source/method: {ledger_path}")
    ledger = reader.json(ledger_path, receipt["ledger_sha256"])
    _require(ledger.get("schema_version") == 1 and ledger.get("kind") == "policy_a_actual_campaign"
             and ledger.get("method") == name and ledger.get("status") == "completed",
             f"invalid completed campaign identity: {ledger_path}")
    _require(ledger.get("spec_sha256") == spec_sha
             and ledger.get("initial_seed") == unit["seed"]
             and ledger.get("campaign_id") == spec.get("campaign_id")
             and ledger.get("total_budget_seconds") == spec["total_budget_seconds"]
             and ledger.get("attempt_cap_seconds") == spec["attempt_cap_seconds"],
             f"ledger/spec binding differs: {ledger_path}")
    targets, attempts = spec.get("targets"), ledger.get("attempts")
    _require(isinstance(targets, list) and isinstance(attempts, list),
             f"targets/attempts missing: {ledger_path}")
    target_ids = [target["target_id"] for target in targets]
    _require(all(isinstance(target, str) and target for target in target_ids)
             and len(target_ids) == len(set(target_ids)), f"invalid target identities: {spec_path}")
    _require(method != "W" or len(target_ids) == 1, f"W must have one target: {spec_path}")
    outcomes: Counter[str] = Counter()
    exits: Counter[str] = Counter()
    seen_attempts: set[int] = set()
    started_targets: set[str] = set()
    candidates = started = candidate_exit_zero = candidate_nonzero = normal_no_candidate = 0
    for attempt in attempts:
        index, target_index = attempt.get("attempt_index"), attempt.get("target_index")
        _require(type(index) is int and index >= 0 and index not in seen_attempts,
                 f"invalid/duplicate attempt index: {ledger_path}")
        seen_attempts.add(index)
        _require(type(target_index) is int and 0 <= target_index < len(target_ids)
                 and attempt.get("target_id") == target_ids[target_index],
                 f"attempt target differs from spec: {ledger_path}")
        found = attempt.get("candidates")
        _require(isinstance(found, list) and all(isinstance(item, dict)
                 and item.get("duplicate_of") is None for item in found),
                 f"invalid or duplicate candidate metadata: {ledger_path}")
        outcome = attempt.get("outcome")
        _require(isinstance(outcome, str) and bool(outcome), f"missing attempt outcome: {ledger_path}")
        _require(type(attempt.get("process_started")) is bool, f"missing process-start flag: {ledger_path}")
        candidates += len(found)
        outcomes[outcome] += 1
        exits[str(attempt.get("exit_code"))] += 1
        if attempt["process_started"]:
            started += 1
            started_targets.add(attempt["target_id"])
        if outcome == "candidate":
            candidate_exit_zero += int(attempt.get("exit_code") == 0)
            candidate_nonzero += int(attempt.get("exit_code") != 0)
        normal_no_candidate += int(outcome == "no_candidate" and attempt.get("exit_code") == 0
                                   and attempt["process_started"])
    _require(outcomes == Counter(ledger.get("outcome_counts", {})),
             f"ledger outcome totals differ from attempts: {ledger_path}")
    termination = ledger.get("termination_reason")
    _require(isinstance(termination, str) and bool(termination),
             f"missing campaign termination reason: {ledger_path}")
    return {"unit_id": unit["unit_id"], "seed": unit["seed"], "run_number": selected["run_number"],
            "queue_path": source["queue_path"], "state_path": source["state_path"],
            "spec_path": str(spec_path), "spec_sha256": spec_sha,
            "ledger_path": str(ledger_path), "ledger_sha256": receipt["ledger_sha256"],
            "budget": _seconds(ledger["total_budget_seconds"], "budget"),
            "attempt_cap_seconds": cap,
            "campaign_seconds": _seconds(ledger["campaign_wall_seconds"], "campaign wall"),
            "process_seconds": _seconds(ledger["process_wall_seconds_sum"], "process wall"),
            "candidates": candidates, "attempts": len(attempts), "started_attempts": started,
            "outcomes": dict(outcomes), "exit_codes": dict(exits), "termination_reason": termination,
            "candidate_exit_zero_attempts": candidate_exit_zero,
            "candidate_nonzero_attempts": candidate_nonzero,
            "normal_no_candidate_attempts": normal_no_candidate,
            "units": len(target_ids), "started_units": len(started_targets),
            "target_ids": target_ids, "started_target_ids": sorted(started_targets)}


def collect_fuzz(main_queue_path: Any, main_state_path: Any, pragma_queue_path: Any,
                 pragma_state_path: Any, reader: Any) -> list[dict[str, Any]]:
    """Collect every official main revision in first-occurrence queue order.

    ``reader`` supplies ``abspath`` and hash-verifying ``json(path, expected)``.
    Only exact queue/state-linked spec and ledger paths are opened. S ``units``
    is the declared target union across seeds; ``started_units`` is the observed
    started target union. ``unit_seed_count`` preserves the repeated seed count.
    """
    main = _source(main_queue_path, main_state_path, reader)
    pragma = _source(pragma_queue_path, pragma_state_path, reader)
    expected_replacements = {unit["unit_id"] for unit in main["units"]
                             if unit["identifier"] in PRAGMA_REVISIONS}
    _require(set(pragma["by_id"]) == expected_replacements,
             "pragma queue must replace exactly the official aq-035/036 units")
    grouped: dict[str, dict[str, Any]] = {}
    for original in main["units"]:
        revision = original["identifier"]
        source = pragma if revision in PRAGMA_REVISIONS else main
        unit = source["by_id"][original["unit_id"]]
        _require(all(unit.get(key) == original.get(key) for key in ("unit_id", "identifier", "seed")),
                 "corrected unit identity differs from main queue")
        selected = _selected(source["state"]["units"][unit["unit_id"]], unit["unit_id"])
        row = grouped.setdefault(revision, {"revision": revision, "W": [], "S": []})
        for method in ("W", "S"):
            row[method].append(_method_metadata(unit, selected, method, source, reader))
    result = []
    for revision, raw in grouped.items():
        row: dict[str, Any] = {"revision": revision}
        for method in ("W", "S"):
            entries = raw[method]
            seeds = [entry["seed"] for entry in entries]
            _require(len(seeds) == len(set(seeds)), f"duplicate revision/seed: {revision}/{method}")
            target_sets = [set(entry["target_ids"]) for entry in entries]
            _require(all(targets == target_sets[0] for targets in target_sets),
                     f"declared targets differ across seeds: {revision}/{method}")
            outcomes = sum((Counter(entry["outcomes"]) for entry in entries), Counter())
            totals = {key: sum(entry[key] for entry in entries) for key in (
                "budget", "campaign_seconds", "process_seconds", "candidates", "attempts",
                "started_attempts", "candidate_exit_zero_attempts", "candidate_nonzero_attempts",
                "normal_no_candidate_attempts")}
            row[method] = {**totals, "seed_count": len(seeds), "initial_seeds": seeds,
                "attempt_cap_seconds": entries[0]["attempt_cap_seconds"], "outcomes": dict(outcomes),
                "exit_codes": dict(sum((Counter(entry["exit_codes"]) for entry in entries), Counter())),
                "termination_reasons": dict(Counter(entry["termination_reason"] for entry in entries)),
                "units": len(target_sets[0]),
                "started_units": len({target for entry in entries for target in entry["started_target_ids"]}),
                "unit_seed_count": sum(entry["units"] for entry in entries),
                "started_unit_seed_count": sum(entry["started_units"] for entry in entries),
                "ledger_paths": [entry["ledger_path"] for entry in entries],
                "spec_paths": [entry["spec_path"] for entry in entries],
                "panic_recorded": outcomes.get("panic", 0),
                "panic_basis": "ledger outcome only; logs not reinspected", "per_seed": entries}
        row["whole_spec_refs"] = [{"path": entry["spec_path"], "sha256": entry["spec_sha256"]}
                                  for entry in raw["W"]]
        result.append(row)
    return result
