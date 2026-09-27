#!/usr/bin/env python3
"""Review the frozen Decoder pilot candidate without publishing signal values."""

import hashlib
import json
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "datasets/contracts.controlled-v3-development.json"
PREPARED = ROOT / "reports/controlled-v3-preflight-2026-09-23/evidence/prepared.json"
PLAN = ROOT / "reports/controlled-v3-preflight-2026-09-23/evidence/plan.json"
OUTCOME = ROOT / "runs/controlled-v3-development/pilot-2026-09-23/execution/execution-aa47e6bc-8901-443b-b921-7e7d0f664464/outcome.json"
REVIEW_R1CS = ROOT / "runs/controlled-v3-development/pilot-2026-09-23/review-decoder-r1cs/circuit.r1cs"
REVIEW_SYM = ROOT / "runs/controlled-v3-development/pilot-2026-09-23/review-decoder-r1cs/circuit.sym"
OUTPUT = ROOT / "reports/controlled-v3-pilot-2026-09-23/candidate-review.json"
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
TARGET = "sha256:593ebf069393e830a57a6cf4f611cee14562ae6b351e218495ea86b38530fd21"
CAUSE = "iden3/circomlib/decoder-unconstrained-one-hot-output"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return str(path.resolve().relative_to(ROOT))


class Reader:
    def __init__(self, data):
        self.data = data
        self.position = 0

    def take(self, length):
        require(self.position + length <= len(self.data), "truncated R1CS")
        value = self.data[self.position:self.position + length]
        self.position += length
        return value

    def integer(self, length):
        return int.from_bytes(self.take(length), "little")

    def done(self):
        require(self.position == len(self.data), "trailing R1CS data")


def read_r1cs(path):
    source = Reader(path.read_bytes())
    require(source.take(4) == b"r1cs", "invalid R1CS magic")
    require(source.integer(4) == 1, "unexpected R1CS version")
    sections = {}
    for _ in range(source.integer(4)):
        kind = source.integer(4)
        length = source.integer(8)
        require(kind not in sections, "duplicate R1CS section")
        sections[kind] = source.take(length)
    source.done()
    require(set(sections) == {1, 2, 3}, "unexpected R1CS sections")

    header = Reader(sections[1])
    field_bytes = header.integer(4)
    require(field_bytes == 32 and header.integer(field_bytes) == PRIME, "unexpected R1CS field")
    counts = dict(zip(
        ["wires", "public_outputs", "public_inputs", "private_inputs", "labels", "constraints"],
        [header.integer(width) for width in [4, 4, 4, 4, 8, 4]],
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
                require(0 < coefficient < PRIME, "invalid R1CS coefficient")
                terms[wire] = coefficient
            triple.append(terms)
        constraints.append(triple)
    body.done()

    labels = Reader(sections[3])
    wire_labels = [labels.integer(8) for _ in range(counts["wires"])]
    labels.done()
    return counts, constraints, wire_labels


def main():
    require(not OUTPUT.exists(), "refusing to overwrite the review record")
    started = time.monotonic()
    contract = json.loads(CONTRACT.read_text())
    prepared = json.loads(PREPARED.read_text())
    plan = json.loads(PLAN.read_text())
    outcome = json.loads(OUTCOME.read_text())
    pair = next(pair for pair in contract["pairs"] if pair["root_cause_id"] == CAUSE)
    vulnerable = next(variant for variant in pair["variants"] if variant["role"] == "published-vulnerable-source")
    require(vulnerable["target_id"] == TARGET, "review target differs from frozen contract")
    require(outcome["plan_sha256"] == digest(PLAN) and outcome["plan_id"] == plan["plan_id"],
            "plan/outcome link changed")
    require(outcome["mutation_settings"]["effective_seed"] == 2026092301,
            "execution seed changed")
    require(outcome["budget_seconds_per_target"] == 30 and outcome["total_budget_seconds"] == 120,
            "execution budget changed")
    require([item["target_id"] for item in outcome["scheduler"]["runs"]] ==
            [item["target_id"] for item in plan["targets"]], "target order changed")
    require(len(outcome["counterexample_candidates"]) == 1,
            "pilot has a different number of candidates; inspect it separately")

    frozen = next(item for item in prepared["targets"] if item["target_id"] == TARGET)
    prepared_r1cs = Path(frozen["structure"]["r1cs_path"])
    require(digest(prepared_r1cs) == digest(REVIEW_R1CS),
            "review R1CS differs from the prepared original R1CS")
    require(digest(ROOT / vulnerable["source_path"]) == vulnerable["source_sha256"],
            "original source changed")
    counts, constraints, labels = read_r1cs(REVIEW_R1CS)
    require(counts == {"wires": 7, "public_outputs": 5, "public_inputs": 0,
                       "private_inputs": 1, "labels": 7, "constraints": 6},
            "unexpected Decoder R1CS shape")

    names_to_wires = {}
    for line in REVIEW_SYM.read_text().splitlines():
        label_text, wire_text, _component_text, name = line.split(",", 3)
        label, wire = int(label_text), int(wire_text)
        require(name not in names_to_wires and 0 < wire < counts["wires"],
                "invalid symbol mapping")
        require(labels[wire] == label, "symbol/R1CS label mismatch")
        names_to_wires[name] = wire
    require(set(names_to_wires.values()) == set(range(1, counts["wires"])),
            "symbol mapping does not cover all nonconstant R1CS wires")
    signal_names = {"main.inp", "main.success", *(f"main.out[{index}]" for index in range(4))}
    require(set(names_to_wires) == signal_names, "Decoder signal mapping changed")

    artifact = outcome["counterexample_candidates"][0]
    candidate_path = Path(artifact["preserved_path"])
    require(candidate_path.is_file() and digest(candidate_path) == artifact["sha256"],
            "candidate hash mismatch")
    runs = {item["result"]["run_id"]: item for item in outcome["scheduler"]["runs"]}
    require(artifact["run_id"] in runs and artifact["target_id"] == TARGET,
            "candidate run or target mismatch")
    linked = runs[artifact["run_id"]]
    require(linked["target_id"] == TARGET and linked["result"]["status"] == "bug_found",
            "candidate has no matching backend finding")
    require(TARGET in {item["target_id"] for item in plan["targets"]},
            "candidate target is absent from the saved plan")

    candidate = json.loads(candidate_path.read_text())
    require(candidate["0_target_path"] == frozen["run_entrypoint"] and
            candidate["1_main_template"] == "Decoder", "candidate source identity changed")
    assignment = {name: int(value) for name, value in candidate["7_assignment"].items()}
    require(set(assignment) == signal_names | {"main.w"} and assignment["main.w"] == 4,
            "candidate signal mapping or concrete parameter changed")
    values = {0: 1, **{wire: assignment[name] for name, wire in names_to_wires.items()}}
    require(set(values) == set(range(counts["wires"])), "incomplete wire assignment")
    canonical_signals = all(0 <= assignment[name] < PRIME for name in signal_names)
    input_ok = 0 <= assignment["main.inp"] < PRIME
    failed = []
    for index, triple in enumerate(constraints):
        a, b, c = [sum(coefficient * values[wire] for wire, coefficient in terms.items()) % PRIME
                   for terms in triple]
        if (a * b - c) % PRIME:
            failed.append(index)
    constraints_ok = canonical_signals and not failed
    if input_ok and canonical_signals:
        outputs_match = all(assignment[f"main.out[{index}]"] ==
                            int(assignment["main.inp"] == index) for index in range(4))
        success_matches = assignment["main.success"] == (
            sum(assignment[f"main.out[{index}]"] for index in range(4)) % PRIME
        )
        property_violated = not (outputs_match and success_matches)
        violation_class = (
            "one-hot-output-equivalence" if not outputs_match else
            "success-sum" if not success_matches else "none"
        )
    else:
        property_violated = None
        violation_class = "unresolved-noncanonical-input-or-signal"

    def verdict(value):
        return "satisfied" if value is True else "not-satisfied" if value is False else "unknown"

    criteria = {
        "input_preconditions": {"verdict": verdict(input_ok), "contract": "canonical BN128 inp"},
        "fixed_original_constraints": {
            "verdict": verdict(constraints_ok),
            "checked_constraint_count": len(constraints),
            "failed_constraint_count": len(failed),
            "canonical_signal_values": canonical_signals,
        },
        "specified_property_violation": {
            "verdict": verdict(property_violated),
            "violation_class": violation_class,
        },
    }
    verdicts = [item["verdict"] for item in criteria.values()]
    disposition = ("validated" if all(value == "satisfied" for value in verdicts) else
                   "rejected" if "not-satisfied" in verdicts else "unresolved")
    report = {
        "schema_version": 1,
        "scope": "controlled-v3 development Decoder original-component review",
        "plan_path": relative(PLAN),
        "plan_sha256": digest(PLAN),
        "outcome_path": relative(OUTCOME),
        "outcome_sha256": digest(OUTCOME),
        "contract_path": relative(CONTRACT),
        "contract_sha256": digest(CONTRACT),
        "prepared_r1cs_path": relative(prepared_r1cs),
        "prepared_r1cs_sha256": digest(prepared_r1cs),
        "review_r1cs_path": relative(REVIEW_R1CS),
        "review_r1cs_byte_identical_to_prepared": True,
        "review_sym_path": relative(REVIEW_SYM),
        "review_sym_sha256": digest(REVIEW_SYM),
        "r1cs_counts": counts,
        "candidate_count": 1,
        "reviews": [{
            "target_id": TARGET,
            "run_id": artifact["run_id"],
            "backend_status": linked["result"]["status"],
            "completion_time_upper_bound_seconds": linked["completion_offset_seconds"],
            "candidate_path": relative(candidate_path),
            "candidate_sha256": artifact["sha256"],
            "candidate_hash_verified": True,
            "run_target_link_verified": True,
            "criteria": criteria,
            "disposition": disposition,
            "root_cause_id": CAUSE if disposition == "validated" else None,
            "schema_2_eligible": disposition == "validated",
        }],
        "validated_count": int(disposition == "validated"),
        "rejected_count": int(disposition == "rejected"),
        "unresolved_count": int(disposition == "unresolved"),
        "automated_review_seconds": time.monotonic() - started,
        "manual_review_seconds": None,
        "raw_signal_values_published": False,
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"disposition": disposition, "candidate_count": 1,
                      "checked_constraints": len(constraints),
                      "failed_constraints": len(failed),
                      "property_violation_class": violation_class}))


if __name__ == "__main__":
    main()
