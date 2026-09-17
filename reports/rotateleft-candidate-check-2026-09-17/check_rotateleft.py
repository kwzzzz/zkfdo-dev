#!/usr/bin/env python3
"""Validate one preselected RotateLeft candidate against the pinned component."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent
FIDELITY = ROOT / "reports/rotateleft-fixture-fidelity-2026-09-15"
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
ROTATION = 3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    require(field_bytes == 32, "unexpected field width")
    require(header.integer(field_bytes) == PRIME, "unexpected field prime")
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


def named_polynomial(triple, names):
    polynomial = {}
    for left_wire, left_coefficient in triple[0].items():
        for right_wire, right_coefficient in triple[1].items():
            factors = tuple(sorted(
                names[wire] for wire in (left_wire, right_wire) if names[wire] != "1"
            ))
            polynomial[factors] = (
                polynomial.get(factors, 0) + left_coefficient * right_coefficient
            ) % PRIME
    for wire, coefficient in triple[2].items():
        factors = () if names[wire] == "1" else (names[wire],)
        polynomial[factors] = (polynomial.get(factors, 0) - coefficient) % PRIME
    return {key: value for key, value in polynomial.items() if value}


def normalized(polynomial):
    require(polynomial, "empty source/constraint polynomial")
    first = min(polynomial, key=lambda term: (len(term), term))
    inverse = pow(polynomial[first], -1, PRIME)
    return {key: value * inverse % PRIME for key, value in polynomial.items()}


def source_polynomials():
    inverse = pow(2 ** ROTATION, -1, PRIME)
    return {
        "out - part1 - part2 === 0": {
            ("main.out",): 1,
            ("main.part1",): PRIME - 1,
            ("main.part2",): PRIME - 1,
        },
        "part1 / 2**3 + part2 * 2**29 - in === 0": {
            ("main.part1",): inverse,
            ("main.part2",): 2 ** (32 - ROTATION),
            ("main.in",): PRIME - 1,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.work_dir.exists(), f"refusing to reuse {args.work_dir}")
    require(not args.output.exists(), f"refusing to overwrite {args.output}")
    started_at = utc_now()
    total_timer = time.monotonic()

    selection = json.loads((EVIDENCE / "selection.json").read_text())
    selected = selection["selected"]
    require(selection["inventory_count"] == 21, "selection inventory changed")
    require(selected["candidate_values_read_during_selection"] is False,
            "candidate was not fixed before value review")
    candidate_path = Path(selected["candidate_path"])
    require(sha256(candidate_path) == selected["candidate_sha256"], "candidate hash mismatch")

    fidelity = json.loads((FIDELITY / "comparison.json").read_text())
    require(fidelity["verdict"] == "constraints_preserved_in_compared_component_scope",
            "fixture fidelity was not established")
    require(fidelity["actual_dev3_fixture"]["target_id"] == selection["target_id"],
            "selected target differs from fidelity target")
    require(fidelity["actual_dev3_fixture"]["parameters"] == ["3"], "unexpected parameter")
    require(fidelity["actual_dev3_fixture"]["prime"] == "bn128", "unexpected prime")

    source = FIDELITY / "component-check/original/generics.circom"
    wrapper = FIDELITY / "component-check/original/circuit.circom"
    require(sha256(source) == fidelity["original_and_fix_provenance"]["original_source_sha256"],
            "pinned original source changed")
    require(sha256(wrapper) == fidelity["actual_dev3_fixture"]["wrapper_sha256"],
            "exact dev3 wrapper changed")

    source_dir = args.work_dir
    compiled_dir = source_dir / "compiled"
    source_dir.mkdir(parents=True)
    compiled_dir.mkdir()
    source_copy = source_dir / "generics.circom"
    wrapper_copy = source_dir / "circuit.circom"
    source_copy.write_bytes(source.read_bytes())
    wrapper_copy.write_bytes(wrapper.read_bytes())
    require(sha256(source_copy) == sha256(source), "source copy changed")
    require(sha256(wrapper_copy) == sha256(wrapper), "wrapper copy changed")

    version = subprocess.run(["circom", "--version"], check=True, capture_output=True, text=True)
    command = [
        "circom", str(wrapper_copy), "--r1cs", "--sym", "--O0", "--prime", "bn128",
        "-o", str(compiled_dir),
    ]
    compile_timer = time.monotonic()
    compiled = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    compile_seconds = time.monotonic() - compile_timer
    (args.work_dir / "compile.stdout.log").write_text(compiled.stdout)
    (args.work_dir / "compile.stderr.log").write_text(compiled.stderr)
    require(compiled.returncode == 0, f"circom failed: {compiled.stderr}")

    evaluation_timer = time.monotonic()
    candidate = json.loads(candidate_path.read_text())
    assignment = {name: int(value) for name, value in candidate["7_assignment"].items()}
    require(set(assignment) == {"main.L", "main.in", "main.out", "main.part1", "main.part2"},
            "unexpected candidate signal set")
    require(assignment["main.L"] == ROTATION, "candidate parameter differs")
    require(all(0 <= value < PRIME for name, value in assignment.items() if name != "main.L"),
            "noncanonical candidate signal")

    r1cs_path = compiled_dir / "circuit.r1cs"
    sym_path = compiled_dir / "circuit.sym"
    counts, constraints, wire_labels = read_r1cs(r1cs_path)
    require(counts == {"wires": 5, "public_outputs": 1, "public_inputs": 1,
                       "private_inputs": 0, "labels": 5, "constraints": 2},
            f"unexpected component shape: {counts}")
    names = {0: "1"}
    wire_for = {}
    for line in sym_path.read_text().splitlines():
        label, wire, component, name = line.split(",")
        wire = int(wire)
        require(int(component) == 0 and wire_labels[wire] == int(label), "symbol/R1CS mismatch")
        require(name in assignment and name != "main.L" and name not in wire_for,
                f"unmapped/duplicate symbol: {name}")
        names[wire] = name
        wire_for[name] = wire
    require(set(wire_for) == {"main.in", "main.out", "main.part1", "main.part2"},
            "signal mapping incomplete")
    values = {0: 1, **{wire: assignment[name] for name, wire in wire_for.items()}}
    require(set(values) == set(range(counts["wires"])), "not every wire has a value")

    expected_source = {name: normalized(poly) for name, poly in source_polynomials().items()}
    rows = []
    matched = set()
    failures = []
    for index, triple in enumerate(constraints):
        polynomial = normalized(named_polynomial(triple, names))
        matches = [name for name, expected in expected_source.items() if polynomial == expected]
        require(len(matches) == 1, f"constraint {index} does not match source uniquely")
        source_constraint = matches[0]
        require(source_constraint not in matched, "source constraint matched twice")
        matched.add(source_constraint)
        evaluated = [
            sum(coefficient * values[wire] for wire, coefficient in terms.items()) % PRIME
            for terms in triple
        ]
        residual = (evaluated[0] * evaluated[1] - evaluated[2]) % PRIME
        row = {
            "constraint_index_zero_based": index,
            "source_constraint": source_constraint,
            "A": str(evaluated[0]),
            "B": str(evaluated[1]),
            "C": str(evaluated[2]),
            "A_times_B_minus_C_mod_p": str(residual),
            "satisfied": residual == 0,
        }
        rows.append(row)
        if residual:
            failures.append(row)
    require(matched == set(expected_source), "not every source constraint was matched")

    input_value = assignment["main.in"]
    actual_output = assignment["main.out"]
    input_precondition_satisfied = 0 <= input_value < 2 ** 32
    expected_output = (
        ((input_value << ROTATION) & 0xFFFFFFFF) | (input_value >> (32 - ROTATION))
        if input_precondition_satisfied else None
    )
    property_violated = (
        actual_output != expected_output if input_precondition_satisfied else None
    )
    recorded_expected = int(candidate["5_flag"]["2_expected_output"]["value"])
    candidate_satisfies_original = not failures
    count_as_valid = bool(
        input_precondition_satisfied and candidate_satisfies_original and property_violated
    )
    if not input_precondition_satisfied:
        verdict = "input_precondition_failed"
    elif failures:
        verdict = "exact_candidate_rejected_by_original_component"
    elif property_violated:
        verdict = "original_component_counterexample_verified"
    else:
        verdict = "no_property_violation"

    report = {
        "schema_version": 1,
        "started_at_utc": started_at,
        "finished_at_utc": utc_now(),
        "scope": "one preselected preserved RotateLeft32Bits(3) candidate",
        "verdict": verdict,
        "count_as_valid_original_component_defect": count_as_valid,
        "selection": selected,
        "fidelity_evidence": {
            "comparison_path": str((FIDELITY / "comparison.json").relative_to(ROOT)),
            "verdict": fidelity["verdict"],
            "original_revision": fidelity["original_and_fix_provenance"]["compared_original_revision"],
            "prepared_sha256": fidelity["actual_dev3_fixture"]["prepared_sha256"],
            "fixture_and_original_r1cs_identical": fidelity["constraint_comparison"]["r1cs_bytes_identical"],
        },
        "component": {
            "template": "RotateLeft32Bits",
            "parameters": [ROTATION],
            "prime": "bn128",
            "compiler_version": version.stdout.strip(),
            "compile_command": command,
            "compile_exit_code": compiled.returncode,
            "r1cs_sha256": sha256(r1cs_path),
            "sym_sha256": sha256(sym_path),
            "r1cs_counts": counts,
            "all_compiled_constraints_matched_to_source": True,
        },
        "candidate_mapping": {
            "mapping": "identity for main.{in,out,part1,part2}; main.L is checked as template metadata",
            "field_value_conversion": "none",
            "unmapped_r1cs_wires": [],
            "defaulted_r1cs_wires": [],
            "assignment": {name: str(value) for name, value in assignment.items()},
            "candidate_sha256": selected["candidate_sha256"],
            "candidate_seed": candidate["8_auxiliary_result"]["mutation_test_log"]["random_seed"],
            "candidate_generation": candidate["8_auxiliary_result"]["mutation_test_log"]["generation"],
            "candidate_backend_execution_time": candidate["3_execution_time"],
        },
        "input_precondition": {
            "definition": "0 <= in < 2**32",
            "input": str(input_value),
            "satisfied": input_precondition_satisfied,
            "enforced_by_component_or_dev3_wrapper": False,
        },
        "property": {
            "definition": "out = ((in << 3) & 0xffffffff) | (in >> 29) for unsigned 32-bit in",
            "applicable": input_precondition_satisfied,
            "expected_output": str(expected_output) if expected_output is not None else None,
            "candidate_recorded_expected_output": str(recorded_expected),
            "candidate_expected_matches_property": (
                recorded_expected == expected_output if expected_output is not None else None
            ),
            "actual_output": str(actual_output),
            "violated": property_violated,
        },
        "constraint_evaluation": {
            "all_constraints": rows,
            "satisfied_constraints": counts["constraints"] - len(failures),
            "failed_constraints": failures,
            "candidate_satisfies_original_component": candidate_satisfies_original,
        },
        "timing": {
            "automated_compile_seconds": compile_seconds,
            "automated_post_compile_evaluation_seconds": time.monotonic() - evaluation_timer,
            "automated_check_total_seconds": time.monotonic() - total_timer,
            "classification": "post-hoc validation cost; excluded from historical search budget",
        },
        "interpretation": {
            "component_metric_count": 1 if count_as_valid else 0,
            "project_context_metric_count": 0,
            "limits": [
                "Only this exact preselected candidate was evaluated.",
                "Input-precondition failure does not establish component or project safety.",
                "No other RotateLeft candidate or project caller was inspected.",
                "The result does not establish ranking performance.",
            ],
        },
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
