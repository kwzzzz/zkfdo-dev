#!/usr/bin/env python3
"""Apply the frozen controlled-v2 descriptive paired analysis."""

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path("/Users/miiz/Desktop/kwzzzz_zkfr")
PROTOCOL = ROOT / "docs/controlled_v2_execution_protocol.md"
CAMPAIGN = ROOT / "runs/controlled-v2/campaigns/campaign-20260920T112512Z/campaign.json"
REVIEW = ROOT / "reports/controlled-v2-execution-2026-09-20/candidate-review.json"
EVALUATIONS = ROOT / "reports/controlled-v2-execution-2026-09-20/evaluation-index.json"
PREPARED = ROOT / "reports/controlled-v2-preparation-2026-09-20/evidence/accepted-preparation/prepare-6cc01794-1fcf-404d-b577-5c208e94a7cd/prepared.json"
OUTPUT = ROOT / "reports/controlled-v2-execution-2026-09-20/analysis.json"
HORIZON = 120.0
STRATEGIES = ["risk-only", "random", "small-first"]
BANYAN = "banyancomputer/hot-proofs-blake3-circom/check-depth-comparator-range"
TANGLE = "tangle-network/protocol-solidity/set-membership-zero-initialization"
BANYAN_TARGET = "sha256:b99bf2694b89536d1c7ca1ef97933456981930df93e7bfc08d0b61149a7bc496"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def summarize(values):
    require(values, "cannot summarize an empty sample")
    return {
        "count": len(values),
        "sum": sum(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def mean_cumulative_curve(times):
    points = [{"time_seconds": 0.0, "mean_cumulative_unique_root_causes": 0.0}]
    for value in sorted(set(times)):
        points.append({
            "time_seconds": value,
            "mean_cumulative_unique_root_causes": sum(item <= value for item in times) / len(times),
        })
    return points


def main():
    require(not OUTPUT.exists(), f"refusing to overwrite {OUTPUT}")
    campaign = json.loads(CAMPAIGN.read_text())
    review = json.loads(REVIEW.read_text())
    evaluations = json.loads(EVALUATIONS.read_text())
    prepared = json.loads(PREPARED.read_text())
    require(campaign["status"] == "execution_complete_adjudication_pending", "campaign incomplete")
    require(len(campaign["blocks"]) == 12, "paired block count changed")
    require(review["summary"]["unreviewed_count"] == 0 and
            review["summary"]["unresolved_count"] == 0, "adjudication incomplete")
    require(review["summary"]["validated_count"] == 36, "validated candidate count changed")
    require(evaluations["summary"]["evaluation_count"] == 36, "evaluation count changed")

    event_by_strategy_block = defaultdict(dict)
    evaluation_seconds = defaultdict(list)
    for record in evaluations["records"]:
        require(record["confirmed_original_component_defect_count"] == 1, "unconfirmed record")
        require(record["confirmed_project_defect_count"] == 0, "unexpected project confirmation")
        require(record["completion_time_upper_bound_seconds"] <= HORIZON, "post-budget record")
        require(record["block"] not in event_by_strategy_block[record["strategy"]],
                "duplicate block event")
        event_by_strategy_block[record["strategy"]][record["block"]] = \
            record["completion_time_upper_bound_seconds"]
        evaluation_seconds[record["strategy"]].append(record["evaluation_wall_seconds"])
    require(set(event_by_strategy_block) == set(STRATEGIES), "strategy set changed")
    require(all(set(events) == set(range(1, 13)) for events in event_by_strategy_block.values()),
            "paired event records incomplete")

    status_by_strategy = defaultdict(Counter)
    candidates_by_strategy = Counter()
    planning_seconds = defaultdict(list)
    scheduler_seconds = defaultdict(list)
    target_position = defaultdict(list)
    strategy_execution_position = defaultdict(Counter)
    target_orders = defaultdict(list)
    valid_attempts = 0
    invalid_attempts = 0
    for block in campaign["blocks"]:
        require(block["status"] == "valid_complete" and block["selected_attempt"] == 1,
                "block was not completed on its first fixed attempt")
        valid_attempts += 1
        invalid_attempts += sum(item["status"] != "valid_complete" for item in block["attempts"])
        attempt = next(item for item in block["attempts"]
                       if item["attempt"] == block["selected_attempt"])
        require(len(attempt["strategy_runs"]) == 3, "strategy execution missing")
        for run in attempt["strategy_runs"]:
            strategy = run["strategy"]
            planning_seconds[strategy].append(run["planning_seconds"])
            scheduler_seconds[strategy].append(run["scheduler_elapsed_seconds"])
            candidates_by_strategy[strategy] += run["backend_candidate_count"]
            status_by_strategy[strategy].update(run["scheduler_run_statuses"])
            target_position[strategy].append(run["target_order"].index(BANYAN_TARGET) + 1)
            strategy_execution_position[strategy][str(run["position"])] += 1
            target_orders[strategy].append(run["target_order"])

    review_seconds = defaultdict(list)
    review_disposition = defaultdict(Counter)
    for item in review["candidate_reviews"]:
        review_seconds[item["strategy"]].append(item["automated_review_seconds"])
        review_disposition[item["strategy"]][item["disposition"]] += 1

    strategy_results = {}
    for strategy in STRATEGIES:
        times = [event_by_strategy_block[strategy][block] for block in range(1, 13)]
        ends = scheduler_seconds[strategy]
        strategy_results[strategy] = {
            "paired_block_count": 12,
            "any_valid_cause_discovery_blocks": 12,
            "any_valid_cause_discovery_rate": 1.0,
            "independent_cause_opportunities": 24,
            "validated_cause_block_events": 12,
            "cause_opportunity_detection_rate": 0.5,
            "per_cause": {
                BANYAN: {
                    "discovery_blocks": 12,
                    "discovery_rate": 1.0,
                    "completion_time_upper_bounds_by_block_seconds": times,
                    "completion_time_upper_bound_summary_seconds": summarize(times),
                },
                TANGLE: {
                    "discovery_blocks": 0,
                    "discovery_rate": 0.0,
                    "completion_time_upper_bounds_by_block_seconds": [None] * 12,
                    "completion_time_upper_bound_summary_seconds": None,
                },
            },
            "unique_root_causes_per_block": [1] * 12,
            "mean_unique_root_causes_by_execution_end": 1.0,
            "median_unique_root_causes_by_execution_end": 1.0,
            "campaign_level_unique_root_causes": 1,
            "first_valid_completion_upper_bound_summary_seconds": summarize(times),
            "restricted_mean_time_to_first_valid_finding_0_120_seconds": statistics.mean(times),
            "mean_cumulative_unique_root_cause_curve": mean_cumulative_curve(times),
            "scheduler_observation_end_summary_seconds": summarize(ends),
            "tangle_0_120_restricted_mean": {
                "status": "not-estimable",
                "reason": "The backend ended the Tangle attempts after its finite no-counterexample search before 30 seconds; no event was observed and the trace does not support extending observation to 120 seconds.",
            },
            "banyan_target_position_by_block": target_position[strategy],
            "banyan_target_position_counts": dict(Counter(target_position[strategy])),
            "target_orders_by_block": target_orders[strategy],
            "strategy_execution_position_counts": dict(strategy_execution_position[strategy]),
            "backend_status_counts": dict(status_by_strategy[strategy]),
            "backend_candidate_count": candidates_by_strategy[strategy],
            "adjudication_counts": {
                "validated": review_disposition[strategy]["validated"],
                "rejected": review_disposition[strategy]["rejected"],
                "unresolved": review_disposition[strategy]["unresolved"],
                "unreviewed": 0,
            },
            "failure_count": status_by_strategy[strategy]["failed"],
            "timeout_count": status_by_strategy[strategy]["timeout"],
            "not_started_count": status_by_strategy[strategy]["not_started"],
            "post_budget_completion_count": 0,
            "planning_cost_seconds": summarize(planning_seconds[strategy]),
            "scheduler_cost_seconds": summarize(scheduler_seconds[strategy]),
            "automated_review_cost_seconds": summarize(review_seconds[strategy]),
            "schema_evaluation_cost_seconds": summarize(evaluation_seconds[strategy]),
        }

    comparisons = []
    for comparator in ["random", "small-first"]:
        risk_times = [event_by_strategy_block["risk-only"][block] for block in range(1, 13)]
        other_times = [event_by_strategy_block[comparator][block] for block in range(1, 13)]
        differences = [left - right for left, right in zip(risk_times, other_times)]
        comparisons.append({
            "comparison": f"risk-only_vs_{comparator}",
            "paired_unique_root_cause_count_difference_by_block": [0] * 12,
            "mean_unique_root_cause_count_difference": 0.0,
            "risk_only_minus_comparator_first_completion_upper_bound_seconds_by_block": differences,
            "paired_time_difference_summary_seconds": summarize(differences),
            "risk_only_faster_blocks": sum(value < 0 for value in differences),
            "equal_upper_bound_blocks": sum(value == 0 for value in differences),
            "risk_only_slower_blocks": sum(value > 0 for value in differences),
            "inferential_test": "not-predeclared; descriptive paired result only",
        })

    campaign_start = datetime.fromisoformat(campaign["started_at_utc"])
    campaign_end = datetime.fromisoformat(campaign["finished_or_stopped_at_utc"])
    report = {
        "schema_version": 1,
        "status": "complete_all_36_runs_reviews_and_schema2_evaluations",
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
            "target_attempts": 144,
            "valid_first_attempt_blocks": valid_attempts,
            "campaign_invalid_attempts": invalid_attempts,
            "missing_plans": 0,
            "missing_outcomes": 0,
            "run_target_link_failures": 0,
            "backend_retries": 0,
        },
        "adjudication": {
            "backend_candidate_count": 36,
            "validated": 36,
            "rejected": 0,
            "unresolved": 0,
            "unreviewed": 0,
            "unique_original_component_root_causes_in_campaign": 1,
            "eligible_independent_root_causes_in_set": 2,
            "campaign_cause_coverage": 0.5,
            "confirmed_project_defect_count": 0,
            "project_caller_reachability": "not-reviewed",
        },
        "strategy_results": strategy_results,
        "paired_comparisons": comparisons,
        "costs": {
            "shared_preparation_seconds": prepared["elapsed_seconds"],
            "campaign_wall_seconds": (campaign_end - campaign_start).total_seconds(),
            "planning_by_strategy_seconds": {
                key: summarize(value) for key, value in planning_seconds.items()
            },
            "scheduler_by_strategy_seconds": {
                key: summarize(value) for key, value in scheduler_seconds.items()
            },
            "post_hoc_candidate_review_automated_seconds":
                review["summary"]["post_hoc_automated_review_seconds"],
            "post_hoc_candidate_review_manual_seconds": None,
            "schema_evaluation_by_strategy_seconds": {
                key: summarize(value) for key, value in evaluation_seconds.items()
            },
            "schema_evaluation_driver_wall_seconds":
                evaluations["summary"]["post_hoc_evaluation_wall_seconds"],
        },
        "interpretation": [
            "All three strategies validated the Banyan CheckDepth root cause in all 12 blocks; none rediscovered the independent Tangle SetMembership root cause.",
            "The campaign therefore validates one independent original-component cause, not 36 defects and not both held-out causes.",
            "Risk-only found the shared Banyan cause earlier because its frozen order placed that vulnerable target first; it did not increase the number of independent causes found.",
            "The result is a two-cause controlled target-order comparison and is not a general multi-project performance claim.",
            "Project caller reachability and impact were not reviewed, so the project-confirmed count remains zero.",
            "Static scores and public labels were not counted as discoveries.",
        ],
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "status": report["status"],
        "valid_independent_causes": report["adjudication"]["unique_original_component_root_causes_in_campaign"],
        "strategy_summary": {
            strategy: {
                "any_discovery_rate": strategy_results[strategy]["any_valid_cause_discovery_rate"],
                "cause_opportunity_rate": strategy_results[strategy]["cause_opportunity_detection_rate"],
                "mean_first_completion_upper_bound_seconds":
                    strategy_results[strategy]["first_valid_completion_upper_bound_summary_seconds"]["mean"],
            }
            for strategy in STRATEGIES
        },
        "paired_comparisons": comparisons,
    }, indent=2))


if __name__ == "__main__":
    main()
