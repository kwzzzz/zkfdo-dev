#!/usr/bin/env python3
"""Check one preserved Add32Bits assignment against the unmodified pre-fix R1CS.

The script decodes hash-pinned GitHub API records, compiles the upstream test
entrypoint in a new work directory, maps the preserved assignment without
changing any value, and evaluates every compiled constraint.  It does not run
zkFuzz or generate a witness.  Exit 0 means that the check completed; the JSON
verdict says whether the exact assignment was accepted or rejected.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
PRE_FIX_REVISION = "9f98e3aaa95e629515883e0cc6e6cfe6aef6d622"
ADD_FIX_REVISION = "4551ca64c9fe536b7b9b7498a1feb1ecdc847474"
SELECTION = EVIDENCE / "selection.json"
CANDIDATE_SHA256 = "acd36135a4c3324ce2da705079c694d7cd6925e064135a5cc18a8d312815860c"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256(path):
    return sha256_bytes(path.read_bytes())


def git_blob_sha1(data):
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def load_api_source(name, expected_path, tree_entries):
    record_path = EVIDENCE / name
    record = json.loads(record_path.read_text())
    require(record["encoding"] == "base64", f"unexpected encoding: {name}")
    require(record["path"] == expected_path, f"unexpected source path: {name}")
    encoded = "".join(record["content"].split())
    content = base64.b64decode(encoded, validate=True)
    require(len(content) == record["size"], f"source size mismatch: {name}")
    require(git_blob_sha1(content) == record["sha"], f"Git blob mismatch: {name}")
    require(tree_entries.get(expected_path) == record["sha"], f"source not in pinned tree: {name}")
    return record, content


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
        section_type = reader.integer(4)
        length = reader.integer(8)
        require(section_type not in sections, "duplicate R1CS section")
        sections[section_type] = reader.take(length)
    reader.done()
    require(set(sections) == {1, 2, 3}, "unexpected R1CS section set")

    header = Reader(sections[1])
    field_bytes = header.integer(4)
    require(field_bytes == 32, "unexpected field width")
    require(header.integer(field_bytes) == PRIME, "unexpected field prime")
    counts = dict(zip(
        ["wires", "public_outputs", "public_inputs", "private_inputs", "labels", "constraints"],
        [header.integer(size) for size in [4, 4, 4, 4, 8, 4]],
    ))
    header.done()

    constraints_reader = Reader(sections[2])
    constraints = []
    for _ in range(counts["constraints"]):
        triple = []
        for _ in range(3):
            terms = {}
            for _ in range(constraints_reader.integer(4)):
                wire = constraints_reader.integer(4)
                coefficient = constraints_reader.integer(field_bytes)
                require(wire < counts["wires"] and wire not in terms, "invalid R1CS wire")
                require(0 < coefficient < PRIME, "noncanonical coefficient")
                terms[wire] = coefficient
            triple.append(terms)
        constraints.append(triple)
    constraints_reader.done()

    labels_reader = Reader(sections[3])
    wire_labels = [labels_reader.integer(8) for _ in range(counts["wires"])]
    labels_reader.done()
    require(wire_labels[0] == 0, "constant wire has unexpected label")
    return counts, constraints, wire_labels


def expanded_polynomial(triple):
    polynomial = {}
    for left_wire, left_coefficient in triple[0].items():
        for right_wire, right_coefficient in triple[1].items():
            monomial = tuple(sorted(wire for wire in (left_wire, right_wire) if wire != 0))
            polynomial[monomial] = (
                polynomial.get(monomial, 0) + left_coefficient * right_coefficient
            ) % PRIME
    for wire, coefficient in triple[2].items():
        monomial = () if wire == 0 else (wire,)
        polynomial[monomial] = (polynomial.get(monomial, 0) - coefficient) % PRIME
    return {monomial: coefficient for monomial, coefficient in polynomial.items() if coefficient}


def normalized(polynomial):
    first = min(polynomial, key=lambda monomial: (len(monomial), monomial))
    inverse = pow(polynomial[first], -1, PRIME)
    return {monomial: coefficient * inverse % PRIME for monomial, coefficient in polynomial.items()}


def source_polynomials(wire_for):
    tmp = wire_for["main.tmp"]
    out = wire_for["main.out"]
    a = wire_for["main.a"]
    b = wire_for["main.b"]
    return {
        "tmp * (tmp - 1) === 0": {(tmp, tmp): 1, (tmp,): PRIME - 1},
        "out === a + b - tmp * 2**32": {
            (out,): 1,
            (a,): PRIME - 1,
            (b,): PRIME - 1,
            (tmp,): 2**32,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.work_dir.exists(), f"refusing to reuse work directory: {args.work_dir}")
    require(not args.output.exists(), f"refusing to overwrite result: {args.output}")
    started_at = utc_now()
    total_timer = time.monotonic()

    selection = json.loads(SELECTION.read_text())
    selected = selection["selected"]
    candidate_path = Path(selected["candidate_path"])
    require(selected["run_id"] == "d67912ec-19b0-40d0-ac96-d8e40dc9d2c5", "selection changed")
    require(selected["candidate_sha256"] == CANDIDATE_SHA256, "selected hash changed")
    require(sha256(candidate_path) == CANDIDATE_SHA256, "candidate hash mismatch")

    pre_commit = json.loads((EVIDENCE / "pre-add-commit.json").read_text())
    fix_commit = json.loads((EVIDENCE / "add-fix-commit.json").read_text())
    tree_commit_query = json.loads((EVIDENCE / "pre-add-tree.json").read_text())
    tree = json.loads((EVIDENCE / "pre-add-tree-object.json").read_text())
    require(pre_commit["sha"] == PRE_FIX_REVISION, "unexpected pre-fix commit")
    require(pre_commit["commit"]["tree"]["sha"] == tree["sha"], "commit/tree mismatch")
    require(tree_commit_query["tree"] == tree["tree"], "commit-ish and tree-object entries differ")
    require(fix_commit["sha"] == ADD_FIX_REVISION, "unexpected addition-fix commit")
    require([parent["sha"] for parent in fix_commit["parents"]] == [PRE_FIX_REVISION],
            "addition fix is not a direct child of pre-fix revision")
    tree_entries = {entry["path"]: entry["sha"] for entry in tree["tree"] if entry["type"] == "blob"}
    source_record, source = load_api_source(
        "pre-add-generics-content.json", "circuits/generics.circom", tree_entries
    )
    test_record, test = load_api_source(
        "pre-add-test-content.json", "circuits/tests/add32bits.circom", tree_entries
    )

    source_dir = args.work_dir / "circuits"
    test_dir = source_dir / "tests"
    compiled_dir = args.work_dir / "compiled"
    test_dir.mkdir(parents=True)
    compiled_dir.mkdir()
    source_path = source_dir / "generics.circom"
    test_path = test_dir / "add32bits.circom"
    source_path.write_bytes(source)
    test_path.write_bytes(test)

    version = subprocess.run(["circom", "--version"], check=True, capture_output=True, text=True)
    command = [
        "circom", str(test_path), "--r1cs", "--sym", "--O0", "--prime", "bn128",
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
    require(set(assignment) == {"main.a", "main.b", "main.out", "main.tmp"},
            "candidate signal set changed")
    require(all(0 <= value < PRIME for value in assignment.values()), "noncanonical candidate value")

    r1cs_path = compiled_dir / "add32bits.r1cs"
    sym_path = compiled_dir / "add32bits.sym"
    counts, constraints, wire_labels = read_r1cs(r1cs_path)
    require(counts == {"wires": 5, "public_outputs": 1, "public_inputs": 0,
                       "private_inputs": 2, "labels": 5, "constraints": 2},
            f"unexpected circuit shape: {counts}")
    wire_for = {}
    for row in sym_path.read_text().splitlines():
        fields = row.split(",")
        require(len(fields) == 4, "invalid .sym row")
        label, wire, component = map(int, fields[:3])
        name = fields[3]
        require(name in assignment and name not in wire_for, f"unmapped/duplicate symbol: {name}")
        require(component == 0 and wire_labels[wire] == label, "symbol/R1CS mismatch")
        wire_for[name] = wire
    require(set(wire_for) == set(assignment), "candidate mapping is incomplete")
    values = {0: 1, **{wire: assignment[name] for name, wire in wire_for.items()}}
    require(set(values) == set(range(counts["wires"])), "not every wire has an exact value")

    expected_polynomials = {name: normalized(poly) for name, poly in source_polynomials(wire_for).items()}
    constraint_rows = []
    matched = set()
    failures = []
    for index, triple in enumerate(constraints):
        polynomial = normalized(expanded_polynomial(triple))
        matches = [name for name, expected in expected_polynomials.items() if polynomial == expected]
        require(len(matches) == 1, f"constraint {index} does not uniquely match source")
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
        constraint_rows.append(row)
        if residual:
            failures.append(row)
    require(matched == set(expected_polynomials), "not every source constraint matched")

    a, b, actual = assignment["main.a"], assignment["main.b"], assignment["main.out"]
    expected = (a + b) % 2**32
    input_precondition_satisfied = 0 <= a < 2**32 and 0 <= b < 2**32
    require(int(candidate["5_flag"]["2_expected_output"]["value"]) == expected,
            "candidate expected output differs from documented property")
    property_violated = actual != expected
    evaluation_seconds = time.monotonic() - evaluation_timer

    report = {
        "schema_version": 1,
        "started_at_utc": started_at,
        "finished_at_utc": utc_now(),
        "scope": "one already-preserved Add32Bits candidate; no fuzzing or witness generation",
        "verdict": "exact_candidate_rejected_by_original_component" if failures else (
            "original_component_counterexample_verified" if property_violated else "no_property_violation"
        ),
        "count_as_valid_original_component_defect": (
            input_precondition_satisfied and not failures and property_violated
        ),
        "selection": selected,
        "provenance": {
            "pre_addition_fix_revision": PRE_FIX_REVISION,
            "addition_fix_revision": ADD_FIX_REVISION,
            "addition_fix_direct_parent_verified": True,
            "pre_fix_tree": tree["sha"],
            "commit_query_tree_top_level_sha": tree_commit_query["sha"],
            "commit_query_note": "The commit-ish tree query returned the queried commit at top level; entries were checked against the actual tree-object response.",
            "source_api_record": str((EVIDENCE / "pre-add-generics-content.json").relative_to(ROOT)),
            "source_path": source_record["path"],
            "source_git_blob_sha1": source_record["sha"],
            "source_sha256": sha256_bytes(source),
            "upstream_test_path": test_record["path"],
            "upstream_test_git_blob_sha1": test_record["sha"],
            "upstream_test_sha256": sha256_bytes(test),
            "exact_audit_snapshot": "unknown; the report has no project commit hash",
        },
        "component": {
            "template": "Add32Bits",
            "parameters": [],
            "dependencies": ["circuits/generics.circom"],
            "entrypoint": "unchanged upstream circuits/tests/add32bits.circom",
            "added_connections_or_constraints": [],
            "compiler_version": version.stdout.strip(),
            "compile_command": command,
            "compile_exit_code": compiled.returncode,
            "r1cs_sha256": sha256(r1cs_path),
            "sym_sha256": sha256(sym_path),
            "r1cs_counts": counts,
            "all_compiled_constraints_matched_to_source": True,
        },
        "candidate_mapping": {
            "mapping": "identity: main.{a,b,out,tmp} to the same four original component signals",
            "field_value_conversion": "none",
            "unmapped_wires": [],
            "defaulted_wires": [],
            "assignment": {name: str(value) for name, value in assignment.items()},
            "candidate_sha256": CANDIDATE_SHA256,
            "candidate_backend_execution_time": candidate["3_execution_time"],
            "candidate_generation": candidate["8_auxiliary_result"]["mutation_test_log"]["generation"],
            "candidate_seed": candidate["8_auxiliary_result"]["mutation_test_log"]["random_seed"],
        },
        "input_precondition": {
            "definition": "a and b are each unsigned 32-bit values",
            "sources": [
                "pre-fix source comment: Add two 32-bit integers",
                "audit report finding 0: two assumed-to-be-32-bit values",
            ],
            "satisfied": input_precondition_satisfied,
        },
        "property": {
            "definition": "out = (a + b) mod 2**32",
            "source": "pre-fix source comments and audit report finding 0",
            "expected_output": str(expected),
            "actual_output": str(actual),
            "violated": property_violated,
        },
        "constraint_evaluation": {
            "all_constraints": constraint_rows,
            "satisfied_constraints": counts["constraints"] - len(failures),
            "failed_constraints": failures,
            "candidate_satisfies_original_component": not failures,
        },
        "timing": {
            "automated_compile_seconds": compile_seconds,
            "automated_post_compile_evaluation_seconds": evaluation_seconds,
            "automated_check_total_seconds": time.monotonic() - total_timer,
            "classification": "post-hoc validation cost; excluded from the historical search budget",
        },
        "limits": [
            "Rejection applies only to this exact assignment.",
            "No other Add32Bits candidate was inspected after selection.",
            "Original-component or project safety is not established.",
            "Project entrypoint reachability and full-project witness/proof validity were not checked.",
            "The exact full audit snapshot and historical compiler artifacts remain unknown.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
