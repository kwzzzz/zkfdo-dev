#!/usr/bin/env python3
"""Validate and summarize a repeated static-ranking pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


STRATEGIES = [
    "path-order",
    "random",
    "small-first",
    "legacy",
    "warning-first",
    "risk-only",
    "risk-grouped",
]
REP_RE = re.compile(r"rep-(\d+)-seed-(\d+)$")
CURVE_SECONDS = [0.05, 0.1, 0.5, 1.0, 3.0, 10.0]


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def finite(value: Any, label: str) -> float:
    number = float(value)
    require(math.isfinite(number), f"{label} must be finite")
    return number


def stats(values: list[float]) -> dict[str, Any]:
    require(bool(values), "cannot summarize an empty sample")
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "values": values,
    }


def relative(path: Path, repository: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(repository))
    except ValueError:
        return str(resolved)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--per-target-budget", type=int, default=3)
    parser.add_argument("--total-budget", type=int, default=10)
    args = parser.parse_args()

    repository = Path.cwd().resolve()
    pilot_root = args.root.resolve()
    stdout_paths = sorted(pilot_root.glob("rep-*-seed-*/*/outcome.stdout.json"))
    expected_cells = args.repetitions * len(STRATEGIES)
    require(
        len(stdout_paths) == expected_cells,
        f"expected {expected_cells} outcomes, found {len(stdout_paths)}",
    )

    rows: list[dict[str, Any]] = []
    common_target_set: tuple[str, ...] | None = None
    backend_hash: str | None = None
    prepared_hash: str | None = None
    config_hash: str | None = None
    comparison_target_set: str | None = None
    seen_cells: set[tuple[int, str]] = set()
    outcome_ids: set[str] = set()
    experiment_ids: set[str] = set()
    run_ids: set[str] = set()
    preserved_candidate_count = 0
    verified_run_log_count = 0
    verified_scheduler_summary_count = 0

    for stdout_path in stdout_paths:
        strategy = stdout_path.parent.name
        match = REP_RE.fullmatch(stdout_path.parent.parent.name)
        require(match is not None, f"invalid repetition directory: {stdout_path}")
        repetition = int(match.group(1))
        backend_seed = int(match.group(2))
        require(strategy in STRATEGIES, f"unknown strategy {strategy}")
        require(
            (repetition, strategy) not in seen_cells,
            f"duplicate cell {repetition}/{strategy}",
        )
        seen_cells.add((repetition, strategy))

        outcome = load_json(stdout_path)
        persisted_outcome_path = Path(outcome["report_path"])
        persisted_outcome = load_json(persisted_outcome_path)
        require(outcome == persisted_outcome, f"stdout/persisted outcome mismatch: {stdout_path}")
        require(outcome["outcome_id"] not in outcome_ids, "duplicate outcome ID")
        outcome_ids.add(outcome["outcome_id"])

        evaluation_path = stdout_path.parent / "evaluation.json"
        evaluation_stdout_path = stdout_path.parent / "evaluation.stdout.json"
        evaluation = load_json(evaluation_path)
        require(
            evaluation == load_json(evaluation_stdout_path),
            f"stdout/persisted evaluation mismatch: {evaluation_path}",
        )

        plan_path = Path(outcome["plan_path"])
        plan = load_json(plan_path)
        require(sha256(plan_path) == outcome["plan_sha256"], "plan SHA-256 mismatch")
        if prepared_hash is None:
            prepared_hash = plan["prepared_sha256"]
            config_hash = plan["config_sha256"]
            comparison_target_set = plan["comparison_target_set"]
        require(plan["prepared_sha256"] == prepared_hash, "prepared corpus hash mismatch")
        require(plan["config_sha256"] == config_hash, "ranking config hash mismatch")
        require(
            plan["comparison_target_set"] == comparison_target_set,
            "comparison target-set profile mismatch",
        )
        planned_ids = tuple(outcome["scheduler"]["planned_target_ids"])
        target_set = tuple(sorted(planned_ids))
        if common_target_set is None:
            common_target_set = target_set
        require(target_set == common_target_set, f"target-set mismatch: {stdout_path}")

        require(outcome["strategy"] == strategy, f"outcome strategy mismatch: {stdout_path}")
        require(evaluation["strategy"] == strategy, f"evaluation strategy mismatch: {stdout_path}")
        require(plan["strategy"] == strategy, f"plan strategy mismatch: {stdout_path}")
        require(outcome["outcome_id"] == evaluation["outcome_id"], "outcome ID mismatch")
        require(outcome["plan_id"] == evaluation["plan_id"], "plan ID mismatch")
        require(
            outcome["budget_seconds_per_target"] == args.per_target_budget,
            f"per-target budget mismatch: {stdout_path}",
        )
        require(
            outcome["total_budget_seconds"] == args.total_budget,
            f"total budget mismatch: {stdout_path}",
        )
        require(
            outcome["mutation_settings"]["effective_seed"] == backend_seed,
            f"backend seed mismatch: {stdout_path}",
        )
        require(outcome["mutation_settings"]["seed_controlled"], "uncontrolled seed")

        if backend_hash is None:
            backend_hash = outcome["zkfuzz_binary_sha256"]
        require(outcome["zkfuzz_binary_sha256"] == backend_hash, "backend hash mismatch")

        actual_ids = tuple(evaluation["actual_process_start_target_ids"])
        require(actual_ids == planned_ids, f"planned/actual order mismatch: {stdout_path}")
        require(not outcome["scheduler"]["failures"], f"runner failure: {stdout_path}")
        require(not outcome["scheduler"]["skipped"], f"unstarted target: {stdout_path}")
        experiment_id = outcome["scheduler"]["experiment_id"]
        require(experiment_id not in experiment_ids, "duplicate scheduler experiment ID")
        experiment_ids.add(experiment_id)
        scheduler_summary = Path(outcome["scheduler"]["summary_path"])
        require(scheduler_summary.is_file(), f"missing scheduler summary: {scheduler_summary}")
        verified_scheduler_summary_count += 1

        for run in outcome["scheduler"]["runs"]:
            run_id = run["result"]["run_id"]
            require(run_id not in run_ids, "duplicate backend run ID")
            run_ids.add(run_id)
            for key in ("stdout_path", "stderr_path"):
                log_path = Path(run["result"][key])
                require(log_path.is_file(), f"missing run log: {log_path}")
                verified_run_log_count += 1

        for candidate in outcome["counterexample_candidates"]:
            candidate_path = Path(candidate["preserved_path"])
            require(candidate_path.is_file(), f"missing candidate: {candidate_path}")
            require(sha256(candidate_path) == candidate["sha256"], "candidate SHA mismatch")
            preserved_candidate_count += 1

        target_labels = {
            target["target_id"]: target["definition"]["label"] for target in plan["targets"]
        }
        order_labels = [target_labels[target_id] for target_id in planned_ids]
        run_statuses = [run["result"]["status"] for run in outcome["scheduler"]["runs"]]
        target_statuses = {
            target_labels[run["target_id"]]: run["result"]["status"]
            for run in outcome["scheduler"]["runs"]
        }
        status_counts = Counter(run_statuses)
        bug_completion_times = [
            finite(run["completion_offset_seconds"], "completion offset")
            for run in outcome["scheduler"]["runs"]
            if run["result"]["status"] == "bug_found"
        ]
        first_candidate = min(bug_completion_times) if bug_completion_times else None
        candidate_curve = {
            str(boundary): sum(value <= boundary for value in bug_completion_times)
            for boundary in CURVE_SECONDS
        }

        require(
            evaluation["backend_bug_candidate_count"] == len(bug_completion_times),
            f"candidate count mismatch: {stdout_path}",
        )
        require(
            evaluation["preserved_counterexample_count"]
            == len(outcome["counterexample_candidates"]),
            f"preserved count mismatch: {stdout_path}",
        )

        rows.append(
            {
                "repetition": repetition,
                "backend_seed": backend_seed,
                "strategy": strategy,
                "ranking_seed": plan.get("ranking_seed"),
                "started_at": outcome["started_at"],
                "plan": relative(plan_path, repository),
                "outcome": relative(persisted_outcome_path, repository),
                "evaluation": relative(evaluation_path, repository),
                "planned_order": order_labels,
                "planned_order_ids": list(planned_ids),
                "scheduler_elapsed_seconds": finite(
                    outcome["scheduler"]["elapsed_seconds"], "scheduler elapsed"
                ),
                "started_target_count": len(actual_ids),
                "status_counts": dict(sorted(status_counts.items())),
                "target_statuses": target_statuses,
                "backend_bug_candidate_count": len(bug_completion_times),
                "preserved_counterexample_count": evaluation[
                    "preserved_counterexample_count"
                ],
                "reviewed_confirmation_count": evaluation["reviewed_confirmation_count"],
                "first_backend_candidate_observed_by_seconds": first_candidate,
                "backend_candidate_curve": candidate_curve,
                "confirmed_project_defect_count": evaluation[
                    "confirmed_project_defect_count"
                ],
                "first_confirmed_defect_observed_by_seconds": evaluation[
                    "first_confirmed_defect_observed_by_seconds"
                ],
            }
        )

    expected_pairs = {
        (repetition, strategy)
        for repetition in range(1, args.repetitions + 1)
        for strategy in STRATEGIES
    }
    require(seen_cells == expected_pairs, "repetition/strategy matrix is incomplete")

    execution_slots: dict[tuple[int, str], int] = {}
    for repetition in range(1, args.repetitions + 1):
        block = sorted(
            (row for row in rows if row["repetition"] == repetition),
            key=lambda row: row["started_at"],
        )
        expected_order = STRATEGIES[repetition - 1 :] + STRATEGIES[: repetition - 1]
        observed_order = [row["strategy"] for row in block]
        require(
            observed_order == expected_order,
            f"strategy execution order mismatch in repetition {repetition}",
        )
        for slot, row in enumerate(block, start=1):
            execution_slots[(repetition, row["strategy"])] = slot

    for row in rows:
        row["strategy_execution_slot"] = execution_slots[
            (row["repetition"], row["strategy"])
        ]
    rows.sort(key=lambda row: (row["repetition"], row["strategy_execution_slot"]))

    strategy_summaries: dict[str, Any] = {}
    for strategy in STRATEGIES:
        sample = sorted(
            (row for row in rows if row["strategy"] == strategy),
            key=lambda row: row["repetition"],
        )
        elapsed = [row["scheduler_elapsed_seconds"] for row in sample]
        candidates = [row["backend_bug_candidate_count"] for row in sample]
        first_candidates = [
            row["first_backend_candidate_observed_by_seconds"]
            for row in sample
            if row["first_backend_candidate_observed_by_seconds"] is not None
        ]
        aggregate_statuses: Counter[str] = Counter()
        for row in sample:
            aggregate_statuses.update(row["status_counts"])
        curve_mean = {
            str(boundary): statistics.fmean(
                row["backend_candidate_curve"][str(boundary)] for row in sample
            )
            for boundary in CURVE_SECONDS
        }
        strategy_summaries[strategy] = {
            "repetitions": len(sample),
            "ranking_seeds": [row["ranking_seed"] for row in sample],
            "execution_slots": [row["strategy_execution_slot"] for row in sample],
            "distinct_planned_orders": sorted(
                {" -> ".join(row["planned_order"]) for row in sample}
            ),
            "scheduler_elapsed_seconds": stats(elapsed),
            "backend_bug_candidate_count": stats(candidates),
            "first_backend_candidate_observed_by_seconds": (
                stats(first_candidates) if first_candidates else None
            ),
            "mean_backend_candidate_curve": curve_mean,
            "aggregate_status_counts": dict(sorted(aggregate_statuses.items())),
            "confirmed_project_defect_counts": [
                row["confirmed_project_defect_count"] for row in sample
            ],
            "first_confirmed_defect_observed_by_seconds": [
                row["first_confirmed_defect_observed_by_seconds"] for row in sample
            ],
        }

    overall_statuses: Counter[str] = Counter()
    target_statuses: dict[str, Counter[str]] = {}
    for row in rows:
        overall_statuses.update(row["status_counts"])
        for label, status in row["target_statuses"].items():
            target_statuses.setdefault(label, Counter()).update([status])

    report = {
        "schema_version": 1,
        "result_kind": "dev3_repeated_backend_candidate_order_pilot",
        "raw_root": relative(pilot_root, repository),
        "protocol": {
            "strategies": STRATEGIES,
            "repetitions": args.repetitions,
            "matrix_cell_count": expected_cells,
            "paired_backend_seeds": sorted({row["backend_seed"] for row in rows}),
            "random_ranking_seeds": [
                row["ranking_seed"] for row in rows if row["strategy"] == "random"
            ],
            "budget_seconds_per_target": args.per_target_budget,
            "total_budget_seconds": args.total_budget,
            "strategy_execution_order": "cyclic rotation; every strategy occupies each execution slot once",
            "execution_mode": "ranking-separated",
        },
        "integrity": {
            "status": "passed",
            "outcome_count": len(rows),
            "evaluation_count": len(rows),
            "common_target_count": len(common_target_set or ()),
            "common_target_ids": list(common_target_set or ()),
            "same_backend_sha256": backend_hash,
            "same_prepared_sha256": prepared_hash,
            "same_ranking_config_sha256": config_hash,
            "comparison_target_set": comparison_target_set,
            "all_stdout_matches_persisted_reports": True,
            "all_planned_orders_match_actual_process_start_orders": True,
            "all_targets_started": True,
            "runner_failure_count": 0,
            "not_started_count": 0,
            "unique_outcome_id_count": len(outcome_ids),
            "unique_scheduler_experiment_id_count": len(experiment_ids),
            "unique_backend_run_id_count": len(run_ids),
            "verified_scheduler_summary_count": verified_scheduler_summary_count,
            "verified_run_log_count": verified_run_log_count,
            "verified_preserved_candidate_count": preserved_candidate_count,
            "reviewed_confirmation_count": sum(
                row["reviewed_confirmation_count"] for row in rows
            ),
            "aggregate_status_counts": dict(sorted(overall_statuses.items())),
            "target_status_counts": {
                label: dict(sorted(counts.items()))
                for label, counts in sorted(target_statuses.items())
            },
        },
        "metric_definitions": {
            "first_backend_candidate_observed_by_seconds": "Earliest scheduler completion offset among bug_found backend runs; a completion upper bound, not exact discovery time.",
            "backend_bug_candidate_count": "Backend NOT SAFE results. Candidates are not confirmed project defects.",
            "confirmed_project_defect_count": "Only explicitly reviewed project-scope root causes; deduplicated by root-cause ID.",
            "recall_at_k": "Target-level ranking recall over three manifest-reported-positive targets; all targets are positive in this development set.",
        },
        "strategy_summaries": strategy_summaries,
        "runs": rows,
        "conclusion": {
            "confirmed_project_defect_performance": "inconclusive: evaluations were run without reviewed confirmations, so the project-scope count is zero and first-confirmed-defect time is censored",
            "risk_grouped_vs_risk_only": "algorithmically indistinguishable on this corpus because every structural complexity value is zero and both plans have the same order",
            "scope": "descriptive backend-candidate/order-throughput pilot on three direct wrappers from one project family; no statistical superiority claim",
        },
        "limitations": [
            "The corpus contains only three direct wrappers from one project family and has no independent held-out evaluation set.",
            "All three targets are manifest-reported positives, so target-level Recall@K is K/3 for every ordering and does not discriminate strategies.",
            "These evaluations contain no reviewed confirmations. A zero confirmed-project count means no candidate was promoted by evidence, not that review disproved every candidate.",
            "Four fixed strategies (small-first, warning-first, risk-only, and risk-grouped) share one identical order; all structural scores are zero.",
            "Wall-clock measurements include subprocess startup and are reported descriptively from seven repetitions.",
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
