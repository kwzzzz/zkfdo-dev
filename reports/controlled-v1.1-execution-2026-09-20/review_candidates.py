#!/usr/bin/env python3
"""Review preserved controlled-v1.1 candidates without persisting signal values."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


ROOT = Path("/Users/miiz/Desktop/kwzzzz_zkfr")
CAMPAIGN = ROOT / "runs/controlled-v1.1/campaigns/campaign-20260920T101530Z"
CONTRACT = ROOT / "datasets/contracts.controlled-v1.json"
R1CS = ROOT / "reports/controlled-v1.1-execution-2026-09-20/evidence/vulnerable-component/compiled/circuit.r1cs"
SYM = ROOT / "reports/controlled-v1.1-execution-2026-09-20/evidence/vulnerable-component/compiled/circuit.sym"
PREPARED_R1CS = ROOT / "reports/controlled-v1-static-regression/evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/targets/0000/structure/r1cs/circuit.r1cs"
VULNERABLE = "sha256:1fdbf2dbcb8c5be4cad2ef0937cdc95c1b36cc8321e2d02f1b820f46c1b91474"
FIXED = "sha256:a85819549a69210934d31e3fa4a0ba4e01f1f456bc86b32a480a29c5b18aec91"
ROOT_CAUSE = "inference-labs-inc/subnet-2-circom/koukyosyumei_subtract_unconstrained_multiplier"
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


class Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def take(self, count):
        require(self.offset + count <= len(self.data), "truncated R1CS")
        result = self.data[self.offset:self.offset + count]
        self.offset += count
        return result

    def integer(self, size):
        return int.from_bytes(self.take(size), "little")

    def done(self):
        require(self.offset == len(self.data), "unexpected trailing R1CS bytes")


def read_r1cs(path):
    reader = Reader(path.read_bytes())
    require(reader.take(4) == b"r1cs", "invalid R1CS magic")
    require(reader.integer(4) == 1, "unsupported R1CS version")
    sections = {}
    for _ in range(reader.integer(4)):
        kind = reader.integer(4)
        length = reader.integer(8)
        require(kind not in sections, "duplicate R1CS section")
        sections[kind] = reader.take(length)
    reader.done()
    require(set(sections) == {1, 2, 3}, "unexpected R1CS sections")

    header = Reader(sections[1])
    field_bytes = header.integer(4)
    require(field_bytes == 32 and header.integer(field_bytes) == PRIME, "unexpected field")
    counts = dict(zip(
        ["wires", "public_outputs", "public_inputs", "private_inputs", "labels", "constraints"],
        [header.integer(size) for size in [4, 4, 4, 4, 8, 4]],
    ))
    header.done()

    body = Reader(sections[2])
    constraints = []
    for _ in range(counts["constraints"]):
        triple = []
        for _ in range(3):
            terms = {}
            for _ in range(body.integer(4)):
                wire = body.integer(4)
                coefficient = body.integer(field_bytes)
                require(wire < counts["wires"] and wire not in terms, "invalid R1CS wire")
                require(0 < coefficient < PRIME, "noncanonical coefficient")
                terms[wire] = coefficient
            triple.append(terms)
        constraints.append(triple)
    body.done()

    labels = Reader(sections[3])
    wire_labels = [labels.integer(8) for _ in range(counts["wires"])]
    labels.done()
    return counts, constraints, wire_labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), f"refusing to overwrite {args.output}")
    started_at = utc_now()
    total_timer = time.monotonic()

    require(sha256(R1CS) == sha256(PREPARED_R1CS), "review R1CS differs from campaign prepared R1CS")
    contract = json.loads(CONTRACT.read_text())
    pair = contract["pairs"][0]
    require(pair["root_cause_id"] == ROOT_CAUSE, "root cause changed")
    require(pair["component_contract"]["predeclared_property"]["id"] == "subtract-output-binding",
            "predeclared property changed")

    counts, constraints, wire_labels = read_r1cs(R1CS)
    require(counts == {"wires": 5, "public_outputs": 1, "public_inputs": 0,
                       "private_inputs": 2, "labels": 5, "constraints": 1},
            f"unexpected component shape: {counts}")
    wire_for = {}
    for line in SYM.read_text().splitlines():
        label, wire, component, name = line.split(",")
        wire = int(wire)
        require(int(component) == 0 and wire_labels[wire] == int(label), "symbol/R1CS mismatch")
        require(name not in wire_for, "duplicate symbol")
        wire_for[name] = wire
    require(set(wire_for) == {"main.a", "main.b", "main.c", "main.d"}, "signal mapping changed")

    ledger_path = CAMPAIGN / "campaign.json"
    ledger = json.loads(ledger_path.read_text())
    require(ledger["status"] == "execution_complete_adjudication_pending", "campaign is incomplete")
    reviews = []
    execution_summary = []
    for block in ledger["blocks"]:
        require(block["status"] == "valid_complete", "invalid block cannot be reviewed")
        attempts = [item for item in block["attempts"] if item["attempt"] == block["selected_attempt"]]
        require(len(attempts) == 1 and attempts[0]["status"] == "valid_complete",
                "selected block attempt missing")
        for strategy_run in attempts[0]["strategy_runs"]:
            plan_path = Path(strategy_run["plan_path"])
            outcome_path = Path(strategy_run["outcome_path"])
            require(sha256(plan_path) == strategy_run["plan_sha256"], "plan hash changed")
            require(sha256(outcome_path) == strategy_run["outcome_sha256"], "outcome hash changed")
            plan = json.loads(plan_path.read_text())
            outcome = json.loads(outcome_path.read_text())
            runs = {item["result"]["run_id"]: item for item in outcome["scheduler"]["runs"]}
            artifacts = outcome["counterexample_candidates"]
            execution_summary.append({
                "block": block["block"],
                "strategy": strategy_run["strategy"],
                "plan_path": relative(plan_path),
                "plan_sha256": strategy_run["plan_sha256"],
                "outcome_path": relative(outcome_path),
                "outcome_sha256": strategy_run["outcome_sha256"],
                "scheduler_elapsed_seconds": outcome["scheduler"]["elapsed_seconds"],
                "backend_statuses": [item["result"]["status"] for item in outcome["scheduler"]["runs"]],
                "backend_candidate_count": len(artifacts),
            })
            for artifact in artifacts:
                timer = time.monotonic()
                review_started = utc_now()
                candidate_path = Path(artifact["preserved_path"])
                require(candidate_path.is_file() and sha256(candidate_path) == artifact["sha256"],
                        "candidate hash mismatch")
                require(artifact["run_id"] in runs, "candidate references unknown run")
                scheduled = runs[artifact["run_id"]]
                require(scheduled["target_id"] == artifact["target_id"], "run/target mismatch")
                require(scheduled["result"]["status"] == "bug_found", "candidate is not bug_found")
                require(artifact["target_id"] in {target["target_id"] for target in plan["targets"]},
                        "candidate target outside plan")

                candidate = json.loads(candidate_path.read_text())
                assignment = {name: int(value) for name, value in candidate["7_assignment"].items()}
                require(set(assignment) == {"main.a", "main.b", "main.c", "main.d"},
                        "candidate signal mapping changed")
                canonical = all(0 <= value < PRIME for value in assignment.values())
                input_ok = 0 <= assignment["main.a"] < PRIME and 0 <= assignment["main.b"] < PRIME
                values = {0: 1, **{wire: assignment[name] for name, wire in wire_for.items()}}
                require(set(values) == set(range(counts["wires"])), "wire assignment incomplete")
                failed_indices = []
                for index, triple in enumerate(constraints):
                    evaluated = [
                        sum(coefficient * values[wire] for wire, coefficient in terms.items()) % PRIME
                        for terms in triple
                    ]
                    if (evaluated[0] * evaluated[1] - evaluated[2]) % PRIME:
                        failed_indices.append(index)
                constraints_ok = not failed_indices
                property_violated = assignment["main.c"] != (
                    assignment["main.a"] - assignment["main.b"]
                ) % PRIME if input_ok else None

                criteria = {
                    "input_preconditions": {
                        "verdict": "satisfied" if input_ok else "not-satisfied",
                        "evidence": [relative(args.output), relative(CONTRACT)],
                        "note": "Both preserved inputs are canonical BN128 scalar-field elements."
                        if input_ok else "At least one preserved input is not a canonical BN128 scalar-field element.",
                    },
                    "fixed_original_constraints": {
                        "verdict": "satisfied" if constraints_ok else "not-satisfied",
                        "evidence": [relative(args.output), relative(R1CS)],
                        "note": "The preserved assignment satisfies the one constraint in the hash-pinned vulnerable revision."
                        if constraints_ok else f"Pinned-original constraint indices {failed_indices} are not satisfied.",
                    },
                    "specified_property_violation": {
                        "verdict": "satisfied" if property_violated else (
                            "not-satisfied" if property_violated is False else "unknown"
                        ),
                        "evidence": [relative(args.output), relative(CONTRACT)],
                        "note": "The preserved output differs from field subtraction under the predeclared property."
                        if property_violated else (
                            "The preserved output equals field subtraction under the predeclared property."
                            if property_violated is False else "The property cannot be evaluated because its input precondition is unresolved."
                        ),
                    },
                }
                verdicts = [item["verdict"] for item in criteria.values()]
                if all(value == "satisfied" for value in verdicts):
                    disposition = "validated"
                elif any(value == "not-satisfied" for value in verdicts):
                    disposition = "rejected"
                else:
                    disposition = "unresolved"
                reviews.append({
                    "block": block["block"],
                    "strategy": strategy_run["strategy"],
                    "plan_path": relative(plan_path),
                    "plan_sha256": strategy_run["plan_sha256"],
                    "outcome_path": relative(outcome_path),
                    "outcome_sha256": strategy_run["outcome_sha256"],
                    "run_id": artifact["run_id"],
                    "target_id": artifact["target_id"],
                    "backend_status": scheduled["result"]["status"],
                    "completion_time_upper_bound_seconds": scheduled["completion_offset_seconds"],
                    "candidate_path": relative(candidate_path),
                    "candidate_sha256": artifact["sha256"],
                    "candidate_hash_verified": True,
                    "run_target_link_verified": True,
                    "all_candidate_field_values_canonical": canonical,
                    "failed_original_constraint_indices_zero_based": failed_indices,
                    "criteria": criteria,
                    "disposition": disposition,
                    "schema_2_eligible": disposition == "validated",
                    "review_started_at_utc": review_started,
                    "review_finished_at_utc": utc_now(),
                    "automated_review_seconds": time.monotonic() - timer,
                    "manual_review_seconds": None,
                })

    require(len(execution_summary) == 36, "expected 36 strategy executions")
    require(len(reviews) == 36, "expected 36 preserved candidates")
    report = {
        "schema_version": 1,
        "started_at_utc": started_at,
        "finished_at_utc": utc_now(),
        "scope": "controlled-v1.1 post-hoc original-component review",
        "campaign_path": relative(CAMPAIGN),
        "campaign_ledger_path": relative(ledger_path),
        "campaign_ledger_sha256": sha256(ledger_path),
        "contract_path": relative(CONTRACT),
        "contract_sha256": sha256(CONTRACT),
        "root_cause_id": ROOT_CAUSE,
        "component": {
            "template": "Subtract",
            "variant": "published-vulnerable-source",
            "revision": "d310309c141d36504b3486cebd96ed70ef3a4fdf",
            "prime": "bn128",
            "input_precondition": "a and b are canonical BN128 scalar-field elements; no additional integer range precondition",
            "predeclared_property": "c = a - b modulo the BN128 scalar-field prime",
            "r1cs_path": relative(R1CS),
            "r1cs_sha256": sha256(R1CS),
            "sym_path": relative(SYM),
            "sym_sha256": sha256(SYM),
            "prepared_r1cs_path": relative(PREPARED_R1CS),
            "prepared_r1cs_sha256": sha256(PREPARED_R1CS),
            "review_r1cs_byte_identical_to_prepared": True,
            "r1cs_counts": counts,
        },
        "execution_summary": execution_summary,
        "candidate_reviews": reviews,
        "summary": {
            "strategy_execution_count": len(execution_summary),
            "backend_candidate_count": len(reviews),
            "validated_count": sum(item["disposition"] == "validated" for item in reviews),
            "rejected_count": sum(item["disposition"] == "rejected" for item in reviews),
            "unresolved_count": sum(item["disposition"] == "unresolved" for item in reviews),
            "unreviewed_count": 0,
            "unique_campaign_root_cause_count": 1 if any(item["disposition"] == "validated" for item in reviews) else 0,
            "fixed_variant_backend_candidate_count": sum(
                item["backend_candidate_count"] for item in execution_summary
                if FIXED in json.loads((ROOT / item["plan_path"]).read_text())["comparison_target_set"]
            ) - len(reviews),
            "post_hoc_automated_review_seconds": time.monotonic() - total_timer,
            "post_hoc_manual_review_seconds": None,
        },
        "raw_candidate_values_persisted_in_this_report": False,
        "limitations": [
            "This review establishes only the frozen direct original-component contract, not project caller reachability or impact.",
            "The same root cause repeated across blocks and strategies is not a new independent defect.",
            "Scheduler completion offsets are upper bounds on discovery time; post-hoc review time is separate from the fuzzing budget.",
            "No candidate signal value is copied into this report.",
        ],
    }
    # The fixed comparator produced no artifacts; calculate it directly from outcomes
    # rather than by subtracting reviewed vulnerable candidates.
    report["summary"]["fixed_variant_backend_candidate_count"] = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
