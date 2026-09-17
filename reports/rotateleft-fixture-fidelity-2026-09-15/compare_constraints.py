#!/usr/bin/env python3
"""Compare the dev3 RotateLeft32Bits fixture with the pinned original component.

This script never reads counterexample files. It copies the already-prepared
fixture and the pinned pre-rotation-fix source into a fresh work directory,
compiles the same RotateLeft32Bits(3) wrapper on BN254, and compares every R1CS
polynomial after mapping wires by signal name.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).resolve().parent
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
ORIGINAL_REVISION = "ef9f5a5ad899d852740a26b30eabe5765673c71f"
ROTATION_FIX_REVISION = "e5e756375fc1fc8dc48667b00cdf38c79a0fdf50"
TARGET_ID = "sha256:76b7b3d1543e77a11a0d9652e29b1547a6b3783de118ac40d4c76702a5805616"
PREPARED_SHA256 = "001056ea35a687233e520624f60f439f99a84600f83da64f697d0bb0f563b952"
BACKEND_SHA256 = "ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd"
FIXTURE_ROOT = ROOT / (
    "runs/dev10-preparation/prepare-e11d82dd-e508-4b69-ab93-38dbed5345f8/"
    "targets/0002/sources"
)
FIXTURE_PINS = {
    "circuit.circom": "3c3363ed16fba47f0020ce7be9034af34c26fd4752273d7d5803163d10084fad",
    "generics.circom": "cdd4afc861b5b07de22aa90fe81f0d9142882964586e8531185ca3422c745bae",
}
ORIGINAL_SOURCE = ROOT / "runs/xorwords-original-followup-2026-09-15/fix-generics.circom"
ORIGINAL_SOURCE_RECORD = ROOT / "runs/xorwords-original-followup-2026-09-15/fix-generics-content.json"
ORIGINAL_SOURCE_SHA256 = "4dca4517b1804c8d3a6c9fa0699bb31633a117ca1f0e6df7a45d352beb94d366"
ORIGINAL_SOURCE_BLOB = "46ef6207acbd284271f27be9ccd7798e7f26603c"


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
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def decode_api_record(path):
    record = json.loads(path.read_text())
    require(record["encoding"] == "base64", f"unexpected encoding: {path}")
    encoded = "".join(record["content"].split())
    content = base64.b64decode(encoded, validate=True)
    require(len(content) == record["size"], f"size mismatch: {path}")
    require(git_blob_sha1(content) == record["sha"], f"Git blob mismatch: {path}")
    return record, content


def extract_template(source, name):
    match = re.search(rf"template\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    require(match is not None, f"template not found: {name}")
    start = match.start()
    brace = source.index("{", match.start())
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise ValueError(f"unterminated template: {name}")


def canonical_code(source):
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)
    return re.sub(r"\s+", "", source)


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


def read_symbols(path, counts, wire_labels):
    names = {0: "1"}
    for row in path.read_text().splitlines():
        fields = row.split(",")
        require(len(fields) == 4, "invalid .sym row")
        label, wire, component = map(int, fields[:3])
        name = fields[3]
        require(component == 0, "unexpected nested component id")
        require(0 < wire < counts["wires"] and wire not in names, "invalid/duplicate symbol wire")
        require(wire_labels[wire] == label, "symbol/R1CS label mismatch")
        names[wire] = name
    require(set(names) == set(range(counts["wires"])), "not every wire has a symbol")
    return names


def expanded_named_polynomial(triple, names):
    polynomial = {}
    for left_wire, left_coefficient in triple[0].items():
        for right_wire, right_coefficient in triple[1].items():
            factors = tuple(sorted(name for wire in (left_wire, right_wire)
                                   if (name := names[wire]) != "1"))
            polynomial[factors] = (
                polynomial.get(factors, 0) + left_coefficient * right_coefficient
            ) % PRIME
    for wire, coefficient in triple[2].items():
        factors = () if names[wire] == "1" else (names[wire],)
        polynomial[factors] = (polynomial.get(factors, 0) - coefficient) % PRIME
    return {monomial: coefficient for monomial, coefficient in polynomial.items() if coefficient}


def normalized(polynomial):
    require(polynomial, "empty constraint polynomial")
    first = min(polynomial, key=lambda monomial: (len(monomial), monomial))
    inverse = pow(polynomial[first], -1, PRIME)
    return {monomial: coefficient * inverse % PRIME for monomial, coefficient in polynomial.items()}


def serializable_polynomial(polynomial):
    return {" * ".join(monomial) if monomial else "1": str(coefficient)
            for monomial, coefficient in sorted(polynomial.items())}


def compile_component(source_bytes, wrapper_bytes, directory):
    directory.mkdir(parents=True)
    source_path = directory / "generics.circom"
    wrapper_path = directory / "circuit.circom"
    output = directory / "compiled"
    output.mkdir()
    source_path.write_bytes(source_bytes)
    wrapper_path.write_bytes(wrapper_bytes)
    command = [
        "circom", str(wrapper_path), "--r1cs", "--sym", "--O0", "--prime", "bn128",
        "-o", str(output),
    ]
    timer = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    elapsed = time.monotonic() - timer
    (directory / "compile.stdout.log").write_text(result.stdout)
    (directory / "compile.stderr.log").write_text(result.stderr)
    require(result.returncode == 0, f"circom failed for {directory}: {result.stderr}")
    return command, elapsed, output / "circuit.r1cs", output / "circuit.sym"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.work_dir.exists(), f"refusing to reuse work directory: {args.work_dir}")
    require(not args.output.exists(), f"refusing to overwrite result: {args.output}")
    started = utc_now()

    fixture_wrapper = (FIXTURE_ROOT / "circuit.circom").read_bytes()
    fixture_source = (FIXTURE_ROOT / "generics.circom").read_bytes()
    require(sha256_bytes(fixture_wrapper) == FIXTURE_PINS["circuit.circom"], "fixture wrapper changed")
    require(sha256_bytes(fixture_source) == FIXTURE_PINS["generics.circom"], "fixture source changed")

    prepared_path = ROOT / "runs/dev10-preparation/prepare-e11d82dd-e508-4b69-ab93-38dbed5345f8/prepared.json"
    plan_path = ROOT / "runs/dev10-plans/path-order.json"
    outcome_path = ROOT / (
        "runs/dev3-ranking-pilot-2026-09-15/rep-01-seed-2026091501/path-order/"
        "executions/execution-d825de18-7f45-4afc-8a35-a76e952cf867/outcome.json"
    )
    require(sha256(prepared_path) == PREPARED_SHA256, "prepared snapshot changed")
    plan = json.loads(plan_path.read_text())
    require(plan["prepared_sha256"] == PREPARED_SHA256, "plan does not pin prepared snapshot")
    plan_targets = [target for target in plan["targets"] if target["target_id"] == TARGET_ID]
    require(len(plan_targets) == 1, "target missing/duplicated in plan")
    require({Path(item["path"]).name: item["sha256"]
             for item in plan_targets[0]["snapshot_fingerprints"]} == FIXTURE_PINS,
            "plan fixture fingerprints differ")
    outcome = json.loads(outcome_path.read_text())
    require(outcome["plan_sha256"] == sha256(plan_path), "outcome plan hash mismatch")
    require(outcome["zkfuzz_binary_sha256"] == BACKEND_SHA256, "backend hash mismatch")
    outcome_runs = [run for run in outcome["scheduler"]["runs"] if run["target_id"] == TARGET_ID]
    require(len(outcome_runs) == 1, "target missing/duplicated in representative outcome")
    require(Path(outcome_runs[0]["result"]["target"]).resolve() == (FIXTURE_ROOT / "circuit.circom").resolve(),
            "representative execution did not use prepared fixture")

    original_record, original_api_bytes = decode_api_record(ORIGINAL_SOURCE_RECORD)
    original_bytes = ORIGINAL_SOURCE.read_bytes()
    require(original_api_bytes == original_bytes, "preserved original differs from API record")
    require(original_record["sha"] == ORIGINAL_SOURCE_BLOB, "unexpected original Git blob")
    require(sha256_bytes(original_bytes) == ORIGINAL_SOURCE_SHA256, "original source hash mismatch")

    fix_commit = json.loads((EVIDENCE / "fix-commit.json").read_text())
    require(fix_commit["sha"] == ROTATION_FIX_REVISION, "unexpected rotation fix commit")
    require([parent["sha"] for parent in fix_commit["parents"]] == [ORIGINAL_REVISION],
            "rotation fix is not a direct child of original revision")
    fixed_record, fixed_bytes = decode_api_record(EVIDENCE / "fix-generics-content.json")
    fix_file = [item for item in fix_commit["files"] if item["filename"] == "circuits/generics.circom"]
    require(len(fix_file) == 1 and fix_file[0]["sha"] == fixed_record["sha"], "fix source/diff mismatch")
    test_record, test_bytes = decode_api_record(EVIDENCE / "original-test-content.json")
    require(test_record["path"] == "circuits/tests/rotateLeft32bits.circom", "unexpected upstream test")

    original_template = extract_template(original_bytes.decode(), "RotateLeft32Bits")
    fixture_template = extract_template(fixture_source.decode(), "RotateLeft32Bits")
    fixed_template = extract_template(fixed_bytes.decode(), "RotateLeft32Bits")
    require(canonical_code(original_template) == canonical_code(fixture_template),
            "fixture template differs from pinned original")
    require(canonical_code(fixed_template) != canonical_code(original_template),
            "rotation fix did not change the template")
    upstream_test_parameters = [int(value) for value in re.findall(
        r"RotateLeft32Bits\((\d+)\)", test_bytes.decode()
    )]

    version = subprocess.run(["circom", "--version"], check=True, capture_output=True, text=True)
    fixture_command, fixture_seconds, fixture_r1cs, fixture_sym = compile_component(
        fixture_source, fixture_wrapper, args.work_dir / "fixture"
    )
    original_command, original_seconds, original_r1cs, original_sym = compile_component(
        original_bytes, fixture_wrapper, args.work_dir / "original"
    )

    fixture_counts, fixture_constraints, fixture_labels = read_r1cs(fixture_r1cs)
    original_counts, original_constraints, original_labels = read_r1cs(original_r1cs)
    fixture_names = read_symbols(fixture_sym, fixture_counts, fixture_labels)
    original_names = read_symbols(original_sym, original_counts, original_labels)
    fixture_polynomials = [normalized(expanded_named_polynomial(row, fixture_names))
                           for row in fixture_constraints]
    original_polynomials = [normalized(expanded_named_polynomial(row, original_names))
                            for row in original_constraints]
    require(len({json.dumps(serializable_polynomial(row), sort_keys=True)
                 for row in fixture_polynomials}) == len(fixture_polynomials),
            "duplicate fixture constraint polynomial")
    require(len({json.dumps(serializable_polynomial(row), sort_keys=True)
                 for row in original_polynomials}) == len(original_polynomials),
            "duplicate original constraint polynomial")

    expected = {
        "out - part1 - part2 === 0": {
            ("main.out",): 1,
            ("main.part1",): PRIME - 1,
            ("main.part2",): PRIME - 1,
        },
        "part1 / 2**3 + part2 * 2**29 - in === 0": {
            ("main.part1",): pow(8, -1, PRIME),
            ("main.part2",): 2**29,
            ("main.in",): PRIME - 1,
        },
    }
    expected = {name: normalized(polynomial) for name, polynomial in expected.items()}

    rows = []
    matched_fixture = set()
    matched_original = set()
    for name, polynomial in expected.items():
        fixture_matches = [index for index, item in enumerate(fixture_polynomials) if item == polynomial]
        original_matches = [index for index, item in enumerate(original_polynomials) if item == polynomial]
        require(len(fixture_matches) == 1 and len(original_matches) == 1,
                f"source constraint missing/duplicated: {name}")
        matched_fixture.update(fixture_matches)
        matched_original.update(original_matches)
        rows.append({
            "kind": "constraint",
            "original_location": "ef9 circuits/generics.circom:44" if name.startswith("out")
                                 else "ef9 circuits/generics.circom:45",
            "fixture_location": "prepared generics.circom:13" if name.startswith("out")
                                else "prepared generics.circom:14",
            "source_expression_at_L3": name,
            "original_r1cs_index_zero_based": original_matches[0],
            "fixture_r1cs_index_zero_based": fixture_matches[0],
            "normalized_polynomial": serializable_polynomial(polynomial),
            "classification": "same finite-field constraint",
            "input_precondition_needed_for_algebraic_equivalence": "none",
        })
    require(matched_fixture == set(range(len(fixture_polynomials))), "unmatched fixture constraint")
    require(matched_original == set(range(len(original_polynomials))), "unmatched original constraint")

    rows = [
        {
            "kind": "witness assignment, not a constraint",
            "original_location": "ef9 circuits/generics.circom:42",
            "fixture_location": "prepared generics.circom:11",
            "source_expression_at_L3": "part1 <-- (in << 3) & 0xFFFFFFFF",
            "classification": "same witness computation; generates no R1CS constraint",
            "input_precondition_needed_for_intended_bit meaning": "in is a constrained unsigned 32-bit value",
        },
        {
            "kind": "witness assignment, not a constraint",
            "original_location": "ef9 circuits/generics.circom:43",
            "fixture_location": "prepared generics.circom:12",
            "source_expression_at_L3": "part2 <-- in >> 29",
            "classification": "same witness computation; generates no R1CS constraint",
            "input_precondition_needed_for_intended_bit meaning": "in is a constrained unsigned 32-bit value",
        },
        *rows,
    ]

    report = {
        "schema_version": 1,
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
        "question": "Does the exact RotateLeft32Bits fixture executed in dev3 preserve the pinned original component constraints?",
        "verdict": "constraints_preserved_in_compared_component_scope",
        "candidate_witness_files_read": [],
        "actual_dev3_fixture": {
            "target_id": TARGET_ID,
            "template": "RotateLeft32Bits",
            "parameters": ["3"],
            "prime": "bn128",
            "compile_args": [],
            "mode": "direct",
            "prepared_sha256": PREPARED_SHA256,
            "wrapper_sha256": FIXTURE_PINS["circuit.circom"],
            "template_source_sha256": FIXTURE_PINS["generics.circom"],
            "representative_outcome": str(outcome_path.relative_to(ROOT)),
            "representative_run_id": outcome_runs[0]["result"]["run_id"],
            "zkfuzz_binary_sha256": BACKEND_SHA256,
            "all_49_outcomes_same_prepared_and_backend": True,
        },
        "original_and_fix_provenance": {
            "compared_original_revision": ORIGINAL_REVISION,
            "original_source_path": original_record["path"],
            "original_source_git_blob_sha1": ORIGINAL_SOURCE_BLOB,
            "original_source_sha256": ORIGINAL_SOURCE_SHA256,
            "rotation_fix_revision": ROTATION_FIX_REVISION,
            "fix_is_direct_child_of_original": True,
            "fixed_source_git_blob_sha1": fixed_record["sha"],
            "fixed_source_sha256": sha256_bytes(fixed_bytes),
            "fixture_template_matches_original_ignoring_comments_and_whitespace": True,
            "fixture_template_matches_fixed_ignoring_comments_and_whitespace": False,
            "exact_audit_snapshot": "unknown; the audit report does not identify a project commit hash",
            "scope_note": "ef9 is pinned both by zkbugs metadata and as the direct parent of e5; commit labels alone were not used.",
        },
        "input_and_signal_mapping": {
            "mapping": {
                "main.in": "main.in",
                "main.out": "main.out",
                "main.part1": "main.part1",
                "main.part2": "main.part2",
            },
            "parameter_mapping": "L = 3 in both compilations",
            "field_value_conversion": "none",
            "wrapper_difference_for_comparison": "none; exact dev3 wrapper bytes used with each source",
            "input_precondition": "in is an unsigned 32-bit value",
            "precondition_source": "ef9 source comment and audit finding 1",
            "enforced_by_component": False,
            "enforced_by_dev3_wrapper": False,
            "wrapper_public_annotation_effect": "marks in public; it does not add a range constraint",
            "caller_responsibility": "the caller must constrain in to 32 bits",
        },
        "constraint_comparison": {
            "compiler_version": version.stdout.strip(),
            "fixture_compile_command": fixture_command,
            "original_compile_command": original_command,
            "fixture_counts": fixture_counts,
            "original_counts": original_counts,
            "fixture_r1cs_sha256": sha256(fixture_r1cs),
            "original_r1cs_sha256": sha256(original_r1cs),
            "r1cs_bytes_identical": fixture_r1cs.read_bytes() == original_r1cs.read_bytes(),
            "fixture_sym_sha256": sha256(fixture_sym),
            "original_sym_sha256": sha256(original_sym),
            "sym_bytes_identical": fixture_sym.read_bytes() == original_sym.read_bytes(),
            "all_constraints_matched_by_signal_name_and_finite_field_polynomial": True,
            "rows": rows,
        },
        "fixed_source_static_difference": {
            "summary": "e5 changes part1's witness computation, constrains part2 with <==, and swaps the reconstruction terms; it is not the source executed in dev3.",
            "effectiveness_assessed": False,
            "audit_client_response_equivalence_assessed": False,
        },
        "upstream_context": {
            "upstream_test_path": test_record["path"],
            "upstream_test_git_blob_sha1": test_record["sha"],
            "upstream_test_parameters": upstream_test_parameters,
            "dev3_parameter_3_present_in_upstream_test": 3 in upstream_test_parameters,
            "project_entrypoint_reachability_checked": False,
        },
        "timing": {
            "fixture_compile_seconds": fixture_seconds,
            "original_compile_seconds": original_seconds,
            "classification": "fixture-fidelity review cost; no candidate validation or fuzzing",
        },
        "interpretation": {
            "component_evaluation_use": "The dev3 target is faithful for studying the constraint system of the pinned original RotateLeft32Bits(3) component.",
            "not_established": [
                "validity of any preserved RotateLeft candidate",
                "project-call reachability or project-level impact",
                "32-bit input enforcement by the component or wrapper",
                "equivalence to the exact full audit snapshot",
                "ranking performance",
            ],
        },
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
