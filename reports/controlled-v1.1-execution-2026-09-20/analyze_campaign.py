#!/usr/bin/env python3
"""Apply the frozen controlled-v1 analysis to completed, adjudicated records."""

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random
import statistics


ROOT = Path("/Users/miiz/Desktop/kwzzzz_zkfr")
PROTOCOL = ROOT / "docs/controlled_v1_1_execution_protocol.md"
CAMPAIGN = ROOT / "runs/controlled-v1.1/campaigns/campaign-20260920T101530Z/campaign.json"
REVIEW = ROOT / "reports/controlled-v1.1-execution-2026-09-20/candidate-review.json"
EVALUATIONS = ROOT / "reports/controlled-v1.1-execution-2026-09-20/evaluation-index.json"
PREPARED = ROOT / "reports/controlled-v1-static-regression/evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/prepared.json"
OUTPUT = ROOT / "reports/controlled-v1.1-execution-2026-09-20/analysis.json"
HORIZON = 60.0
BOOTSTRAP_SEED = 2026100101
BOOTSTRAP_REPLICATES = 10_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def wilson(successes, total, z=1.959963984540054):
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [center - half, center + half]


def km_complete_events(times, horizon):
    require(times and all(0 <= value <= horizon for value in times), "invalid event time")
    counts = Counter(times)
    at_risk = len(times)
    survival = 1.0
    previous = 0.0
    restricted_mean = 0.0
    curve = []
    median = None
    for event_time in sorted(counts):
        restricted_mean += survival * (event_time - previous)
        events = counts[event_time]
        survival *= 1 - events / at_risk
        at_risk -= events
        curve.append({
            "time_seconds": event_time,
            "events": events,
            "survival_probability": survival,
            "mean_cumulative_unique_root_causes": 1 - survival,
        })
        if median is None and survival <= 0.5:
            median = event_time
        previous = event_time
    restricted_mean += survival * (horizon - previous)
    return {"curve": curve, "median_seconds": median, "restricted_mean_0_60_seconds": restricted_mean}


def exact_mcnemar(left, right):
    left_only = sum(a and not b for a, b in zip(left, right))
    right_only = sum(b and not a for a, b in zip(left, right))
    discordant = left_only + right_only
    if discordant == 0:
        p_value = 1.0
    else:
        lower = min(left_only, right_only)
        probability = sum(math.comb(discordant, k) for k in range(lower + 1)) / (2 ** discordant)
        p_value = min(1.0, 2 * probability)
    return {"left_only": left_only, "right_only": right_only,
            "discordant_pairs": discordant, "exact_two_sided_p_value": p_value}


def percentile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(values):
    return {
        "count": len(values),
        "sum_seconds": sum(values),
        "mean_seconds": statistics.mean(values),
        "median_seconds": statistics.median(values),
        "minimum_seconds": min(values),
        "maximum_seconds": max(values),
    }


def main():
    require(not OUTPUT.exists(), f"refusing to overwrite {OUTPUT}")
    campaign = json.loads(CAMPAIGN.read_text())
    review = json.loads(REVIEW.read_text())
    evaluations = json.loads(EVALUATIONS.read_text())
    prepared = json.loads(PREPARED.read_text())
    require(campaign["status"] == "execution_complete_adjudication_pending", "campaign incomplete")
    require(review["summary"]["unreviewed_count"] == 0 and review["summary"]["unresolved_count"] == 0,
            "adjudication incomplete")
    require(evaluations["summary"]["evaluation_count"] == 36, "evaluation count changed")

    event_by_strategy_block = defaultdict(dict)
    evaluation_seconds = defaultdict(list)
    for record in evaluations["records"]:
        require(record["confirmed_original_component_defect_count"] == 1, "unconfirmed record")
        require(record["confirmed_project_defect_count"] == 0, "unexpected project confirmation")
        require(record["completion_time_upper_bound_seconds"] <= HORIZON, "post-budget record")
        event_by_strategy_block[record["strategy"]][record["block"]] = record["completion_time_upper_bound_seconds"]
        evaluated = json.loads((ROOT / record["evaluation_path"]).read_text())
        evaluation_seconds[record["strategy"]].append(evaluated["timings"]["evaluation_seconds"])
    require(set(event_by_strategy_block) == {"risk-only", "random", "small-first"}, "strategy set changed")
    require(all(set(events) == set(range(1, 13)) for events in event_by_strategy_block.values()),
            "paired blocks incomplete")

    status_by_strategy = defaultdict(Counter)
    candidates_by_strategy = Counter()
    planning_seconds = defaultdict(list)
    scheduler_seconds = defaultdict(list)
    random_order_split = Counter()
    for block in campaign["blocks"]:
        attempt = next(item for item in block["attempts"] if item["attempt"] == block["selected_attempt"])
        for run in attempt["strategy_runs"]:
            strategy = run["strategy"]
            planning_seconds[strategy].append(run["planning_seconds"])
            scheduler_seconds[strategy].append(run["scheduler_elapsed_seconds"])
            candidates_by_strategy[strategy] += run["backend_candidate_count"]
            status_by_strategy[strategy].update(run["scheduler_run_statuses"])
            if strategy == "random":
                random_order_split["vulnerable-first" if run["target_order"][0].endswith("b91474")
                                   else "fixed-first"] += 1

    strategy_results = {}
    for strategy in ["risk-only", "random", "small-first"]:
        times = [event_by_strategy_block[strategy][block] for block in range(1, 13)]
        km = km_complete_events(times, HORIZON)
        strategy_results[strategy] = {
            "paired_block_count": 12,
            "valid_discovery_blocks": 12,
            "discovery_proportion": 1.0,
            "wilson_95_interval": wilson(12, 12),
            "unique_root_causes_per_block": [1] * 12,
            "mean_unique_root_causes_by_budget": 1.0,
            "median_unique_root_causes_by_budget": 1.0,
            "campaign_level_unique_root_causes": 1,
            "completion_time_upper_bounds_by_block_seconds": times,
            "completion_time_summary": summarize(times),
            "kaplan_meier": km,
            "backend_status_counts": dict(status_by_strategy[strategy]),
            "backend_candidate_count": candidates_by_strategy[strategy],
            "adjudication_counts": {"validated": 12, "rejected": 0,
                                    "unresolved": 0, "unreviewed": 0},
            "post_budget_completion_count": 0,
            "planning_cost": summarize(planning_seconds[strategy]),
            "scheduler_cost": summarize(scheduler_seconds[strategy]),
            "evaluation_cost": summarize(evaluation_seconds[strategy]),
        }

    comparisons = []
    raw_p_values = []
    rng = random.Random(BOOTSTRAP_SEED)
    for comparator in ["random", "small-first"]:
        left_events = [True] * 12
        right_events = [True] * 12
        mcnemar = exact_mcnemar(left_events, right_events)
        raw_p_values.append(mcnemar["exact_two_sided_p_value"])
        left_times = strategy_results["risk-only"]["completion_time_upper_bounds_by_block_seconds"]
        right_times = strategy_results[comparator]["completion_time_upper_bounds_by_block_seconds"]
        observed = statistics.mean(left_times) - statistics.mean(right_times)
        bootstrap = []
        for _ in range(BOOTSTRAP_REPLICATES):
            indices = [rng.randrange(12) for _ in range(12)]
            bootstrap.append(
                statistics.mean(left_times[index] for index in indices)
                - statistics.mean(right_times[index] for index in indices)
            )
        comparisons.append({
            "comparison": f"risk-only_vs_{comparator}",
            "paired_discovery_proportion_difference": 0.0,
            "mcnemar": mcnemar,
            "risk_only_minus_comparator_restricted_mean_seconds": observed,
            "paired_bootstrap_95_interval_seconds": [percentile(bootstrap, 0.025),
                                                       percentile(bootstrap, 0.975)],
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "bootstrap_seed": BOOTSTRAP_SEED,
        })

    # Holm adjustment for the two predeclared McNemar comparisons.
    order = sorted(range(len(raw_p_values)), key=raw_p_values.__getitem__)
    adjusted = [None] * len(raw_p_values)
    running = 0.0
    for rank, index in enumerate(order):
        candidate = min(1.0, (len(raw_p_values) - rank) * raw_p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    for item, value in zip(comparisons, adjusted):
        item["holm_adjusted_mcnemar_p_value"] = value

    campaign_start = datetime.fromisoformat(campaign["started_at_utc"])
    campaign_end = datetime.fromisoformat(campaign["finished_or_stopped_at_utc"])
    report = {
        "schema_version": 1,
        "status": "complete_all_36_runs_and_candidate_reviews",
        "protocol_path": relative(PROTOCOL),
        "protocol_sha256": sha256(PROTOCOL),
        "campaign_ledger_path": relative(CAMPAIGN),
        "campaign_ledger_sha256": sha256(CAMPAIGN),
        "candidate_review_path": relative(REVIEW),
        "candidate_review_sha256": sha256(REVIEW),
        "evaluation_index_path": relative(EVALUATIONS),
        "evaluation_index_sha256": sha256(EVALUATIONS),
        "analysis_horizon_seconds": HORIZON,
        "execution_integrity": {
            "paired_blocks": 12,
            "strategy_executions": 36,
            "valid_first_attempt_blocks": 12,
            "campaign_invalid_attempts": 0,
            "missing_plans": 0,
            "missing_outcomes": 0,
            "run_target_link_failures": 0,
            "random_order_split": dict(random_order_split),
        },
        "adjudication": {
            "backend_candidate_count": 36,
            "validated": 36,
            "rejected": 0,
            "unresolved": 0,
            "unreviewed": 0,
            "unique_original_component_root_causes_in_campaign": 1,
            "confirmed_project_defect_count": 0,
        },
        "strategy_results": strategy_results,
        "paired_comparisons": comparisons,
        "costs": {
            "shared_preparation_seconds": prepared["elapsed_seconds"],
            "campaign_wall_seconds": (campaign_end - campaign_start).total_seconds(),
            "planning_by_strategy": {key: summarize(value) for key, value in planning_seconds.items()},
            "scheduler_by_strategy": {key: summarize(value) for key, value in scheduler_seconds.items()},
            "post_hoc_candidate_review_automated_seconds": review["summary"]["post_hoc_automated_review_seconds"],
            "post_hoc_candidate_review_manual_seconds": None,
            "evaluation_by_strategy": {key: summarize(value) for key, value in evaluation_seconds.items()},
            "evaluation_driver_wall_seconds": evaluations["summary"]["post_hoc_evaluation_wall_seconds"],
        },
        "interpretation": [
            "Every strategy produced a validated original-component candidate in every block; the campaign contains one repeated root cause, not 36 independent defects.",
            "Risk-only and small-first used the same target order, so their timing difference is execution/system variation rather than evidence of a ranking-algorithm effect.",
            "Random used vulnerable-first in six blocks and fixed-first in six blocks; its aggregate timing therefore reflects the frozen order randomization in this one-pair controlled set.",
            "The result is a controlled order-effect regression for one defect pair and does not establish multi-project performance or project-context impact.",
            "Static risk scores were not counted as discoveries; all events come from linked bug_found runs and completed three-criterion reviews.",
        ],
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "status": report["status"],
        "campaign_unique_root_causes": report["adjudication"]["unique_original_component_root_causes_in_campaign"],
        "strategy_mean_completion_upper_bounds": {
            key: value["completion_time_summary"]["mean_seconds"]
            for key, value in strategy_results.items()
        },
        "comparisons": comparisons,
    }, indent=2))


if __name__ == "__main__":
    main()
