#!/usr/bin/env python3
"""Create per-outcome schema-2 confirmations and stored evaluations."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time


ROOT = Path("/Users/miiz/Desktop/kwzzzz_zkfr")
BINARY = ROOT / "runs/controlled-v1.1/frozen-tools/zkfDO-9a8bb031-debug"
REVIEW = ROOT / "reports/controlled-v1.1-execution-2026-09-20/candidate-review.json"
CONTRACT = ROOT / "datasets/contracts.controlled-v1.json"
R1CS = ROOT / "reports/controlled-v1.1-execution-2026-09-20/evidence/vulnerable-component/compiled/circuit.r1cs"
OUTPUT = ROOT / "reports/controlled-v1.1-execution-2026-09-20/evaluation-index.json"
ROOT_CAUSE = "inference-labs-inc/subnet-2-circom/koukyosyumei_subtract_unconstrained_multiplier"
BINARY_SHA256 = "e3472909d3d8de4411ee20a9574a822b9c262e7aff935c9bf38eac8f31a16960"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def main():
    require(not OUTPUT.exists(), f"refusing to overwrite {OUTPUT}")
    require(sha256(BINARY) == BINARY_SHA256, "frozen zkfDO binary changed")
    review = json.loads(REVIEW.read_text())
    require(review["summary"]["validated_count"] == 36, "adjudication is incomplete")
    by_outcome = {}
    for item in review["candidate_reviews"]:
        require(item["disposition"] == "validated" and item["schema_2_eligible"],
                "nonvalidated candidate cannot become a confirmation")
        require(item["outcome_path"] not in by_outcome, "multiple candidates for one outcome")
        by_outcome[item["outcome_path"]] = item

    records = []
    started_at = utc_now()
    timer = time.monotonic()
    for execution in review["execution_summary"]:
        outcome_rel = execution["outcome_path"]
        require(outcome_rel in by_outcome, "outcome has no validated candidate")
        item = by_outcome[outcome_rel]
        plan_path = ROOT / item["plan_path"]
        outcome_path = ROOT / outcome_rel
        strategy_dir = plan_path.parent
        confirmation_path = strategy_dir / "confirmation.schema2.json"
        evaluation_path = strategy_dir / "evaluation.json"
        stdout_path = strategy_dir / "evaluate.stdout.json"
        stderr_path = strategy_dir / "evaluate.stderr.log"
        for path in [confirmation_path, evaluation_path, stdout_path, stderr_path]:
            require(not path.exists(), f"refusing to overwrite {path}")

        criteria = {}
        for name, criterion in item["criteria"].items():
            require(criterion["verdict"] == "satisfied", f"criterion is not satisfied: {name}")
            criteria[name] = {
                "verdict": "satisfied",
                "evidence": [str(REVIEW), str(CONTRACT), str(R1CS)],
                "note": criterion["note"],
            }
        confirmation = {
            "schema_version": 2,
            "confirmations": [{
                "run_id": item["run_id"],
                "target_id": item["target_id"],
                "root_cause_id": ROOT_CAUSE,
                "scope": "original-component",
                "evidence_origin": "backend-execution",
                "original_component_review": criteria,
                "evidence": [str(REVIEW), str(CONTRACT), str(R1CS)],
                "note": "Validated against the frozen direct Subtract vulnerable component; project reachability and impact are not claimed.",
            }],
        }
        confirmation_path.write_text(json.dumps(confirmation, indent=2) + "\n")
        command = [str(BINARY), "experiment", "evaluate", "--plan", str(plan_path),
                   "--outcome", str(outcome_path), "--confirmations", str(confirmation_path),
                   "--output", str(evaluation_path)]
        invocation_started = utc_now()
        invocation_timer = time.monotonic()
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            completed = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, check=False)
        wall_seconds = time.monotonic() - invocation_timer
        require(completed.returncode == 0 and evaluation_path.is_file(), "evaluation failed")
        evaluated = json.loads(evaluation_path.read_text())
        require(evaluated["confirmed_original_component_defect_count"] == 1,
                "validated component defect was not counted")
        require(evaluated["confirmed_project_defect_count"] == 0,
                "component finding was incorrectly promoted to project scope")
        require(evaluated["reviewed_confirmation_count"] == 1,
                "unexpected confirmation count")
        require(evaluated["first_confirmed_original_component_defect_observed_by_seconds"] ==
                item["completion_time_upper_bound_seconds"], "completion upper bound mismatch")
        records.append({
            "block": item["block"],
            "strategy": item["strategy"],
            "run_id": item["run_id"],
            "target_id": item["target_id"],
            "plan_path": item["plan_path"],
            "plan_sha256": item["plan_sha256"],
            "outcome_path": item["outcome_path"],
            "outcome_sha256": item["outcome_sha256"],
            "confirmation_path": relative(confirmation_path),
            "confirmation_sha256": sha256(confirmation_path),
            "evaluation_path": relative(evaluation_path),
            "evaluation_sha256": sha256(evaluation_path),
            "evaluation_stdout_path": relative(stdout_path),
            "evaluation_stderr_path": relative(stderr_path),
            "evaluation_exit_code": completed.returncode,
            "evaluation_started_at_utc": invocation_started,
            "evaluation_wall_seconds": wall_seconds,
            "completion_time_upper_bound_seconds": item["completion_time_upper_bound_seconds"],
            "confirmed_original_component_defect_count": 1,
            "confirmed_project_defect_count": 0,
        })

    require(len(records) == 36, "expected 36 stored evaluations")
    index = {
        "schema_version": 1,
        "started_at_utc": started_at,
        "finished_at_utc": utc_now(),
        "binary_path": relative(BINARY),
        "binary_sha256": sha256(BINARY),
        "candidate_review_path": relative(REVIEW),
        "candidate_review_sha256": sha256(REVIEW),
        "status": "all_36_outcomes_evaluated_with_completed_adjudication",
        "records": records,
        "summary": {
            "evaluation_count": len(records),
            "schema_2_confirmation_count": len(records),
            "confirmed_original_component_records": len(records),
            "confirmed_project_records": 0,
            "post_hoc_evaluation_wall_seconds": time.monotonic() - timer,
        },
        "limitations": [
            "Repeated records share one root cause and do not represent 36 independent defects.",
            "Completion times are scheduler upper bounds rather than exact discovery timestamps.",
            "Schema validation checks links and declared reviews; the independent candidate-review evidence supplies the substantive checks.",
        ],
    }
    OUTPUT.write_text(json.dumps(index, indent=2) + "\n")
    print(json.dumps(index["summary"], indent=2))


if __name__ == "__main__":
    main()
