#!/usr/bin/env python3
"""Check one preserved assignment against the unmodified historical XorWords R1CS.

Run from the repository root after acquiring the two hash-pinned source files.
This compiles the historical test entrypoint; it never generates a new witness,
changes the candidate, or runs the fuzzer. Exit 0 means the check completed,
including when the preserved candidate is rejected (see the JSON verdict).
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "runs/xorwords-original-followup-2026-09-15"
BUILD = RAW / "component-check"
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
SOURCE_PINS = {
    "parent-generics.circom": "226c80d4906c973275b239ae1e73f4762e96a58d1f2aba77c298c1938aa4f938",
    "parent-xor32bits.circom": "a6817a0be88b01c05cd370980ab9ab7bc342989ca028b72563337d0b8b3a95d8",
}
CANDIDATE = ROOT / "experiments/evidence/xorwords-2026-09-15/original/counterexample.json"
CANDIDATE_SHA256 = "6dbcbffe3b707ddb75f763aec08aead29c76639d096d6b1def8a8e0de6bb78a8"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

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
    require(reader.integer(4) == 1, "only R1CS version 1 is supported")
    sections = {}
    for _ in range(reader.integer(4)):
        section, length = reader.integer(4), reader.integer(8)
        require(section not in sections, "duplicate R1CS section")
        sections[section] = reader.take(length)
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
    require(counts == {"wires": 100, "public_outputs": 1, "public_inputs": 0,
                       "private_inputs": 2, "labels": 100, "constraints": 35},
            "unexpected circuit shape; re-check source/compiler before using this script")
    constraints_reader = Reader(sections[2])
    constraints = []
    for _ in range(counts["constraints"]):
        triple = []
        for _ in range(3):
            terms = {}
            for _ in range(constraints_reader.integer(4)):
                wire = constraints_reader.integer(4)
                coefficient = constraints_reader.integer(field_bytes)
                require(wire < counts["wires"] and wire not in terms, "invalid/duplicate wire")
                require(0 < coefficient < PRIME, "noncanonical coefficient")
                terms[wire] = coefficient
            triple.append(terms)
        constraints.append(triple)
    constraints_reader.done()
    labels_reader = Reader(sections[3])
    wire_labels = [labels_reader.integer(8) for _ in range(counts["wires"])]
    labels_reader.done()
    require(wire_labels[0] == 0, "constant wire has unexpected label")
    require(len(set(wire_labels)) == counts["wires"], "duplicate wire labels")
    require(all(label < counts["labels"] for label in wire_labels), "invalid label")
    return counts, constraints, wire_labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        help="write a new report to this path; existing files are refused")
    args = parser.parse_args()
    if args.output is not None:
        require(not args.output.exists(), f"refusing to overwrite report: {args.output}")
    require(sha256(CANDIDATE) == CANDIDATE_SHA256, "preserved candidate hash mismatch")
    destinations = ["circuits/generics.circom", "circuits/tests/xor32bits.circom"]
    for (name, expected), destination in zip(SOURCE_PINS.items(), destinations):
        source = RAW / name
        require(sha256(source) == expected, f"source hash mismatch: {source}")
        target = BUILD / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        require(sha256(target) == expected, "source copy changed")
    compiled = BUILD / "compiled"
    compiled.mkdir(exist_ok=True)
    command = ["circom", str((BUILD / destinations[1]).relative_to(ROOT)),
               "--r1cs", "--sym", "--O0", "--prime", "bn128", "-o", str(compiled.relative_to(ROOT))]
    version = subprocess.run(["circom", "--version"], check=True, capture_output=True, text=True)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (BUILD / "compile.stdout.log").write_text(result.stdout)
    (BUILD / "compile.stderr.log").write_text(result.stderr)
    require(result.returncode == 0, f"circom failed: {result.stderr}")

    candidate = json.loads(CANDIDATE.read_text())
    assignment = {name: int(value) for name, value in candidate["7_assignment"].items()}
    require(all(0 <= value < PRIME for value in assignment.values()), "noncanonical assignment")
    source_for = {f"main.{name}[0]": f"main.{name}" for name in ["a", "b", "out"]}
    for source, target in [("a_bits", "abits"), ("b_bits", "bbits"), ("xor_bits", "xors")]:
        for bit in range(32):
            source_for[f"main.{target}[{31 - bit}]"] = f"main.xor.{source}[{bit}]"
    aliases = {f"main.xor.{name}": f"main.{name}" for name in ["a", "b", "out"]}
    require(set(assignment) == set(source_for.values()) | set(aliases), "unmapped candidate signal")
    for alias, name in aliases.items():
        require(assignment[alias] == assignment[name], f"inconsistent alias: {alias}")

    r1cs_path, sym_path = compiled / "xor32bits.r1cs", compiled / "xor32bits.sym"
    counts, constraints, wire_labels = read_r1cs(r1cs_path)
    wire_for, values = {}, {0: 1}
    for line in sym_path.read_text().splitlines():
        fields = line.split(",")
        require(len(fields) == 4, "invalid .sym row")
        label, wire, component = map(int, fields[:3])
        name = fields[3]
        require(name in source_for and name not in wire_for, f"unmapped/duplicate symbol: {name}")
        require(0 < wire < counts["wires"] and wire not in values, "invalid/duplicate symbol wire")
        require(component == 0 and wire_labels[wire] == label, "symbol/R1CS label mismatch")
        wire_for[name] = wire
        values[wire] = assignment[source_for[name]]
    require(set(wire_for) == set(source_for), "some mapped signals are absent from .sym")
    require(set(values) == set(range(counts["wires"])), "some wires have no assigned value")

    failures, source_residuals = [], {}
    for name, bits in [("a", "abits"), ("b", "bbits")]:
        input_wire = wire_for[f"main.{name}[0]"]
        a_terms = {input_wire: 1}
        for index in range(32):
            a_terms[wire_for[f"main.{bits}[{index}]"]] = (-2 ** (31 - index)) % PRIME
        expected = [a_terms, {input_wire: 1}, {}]
        indices = [index for index, triple in enumerate(constraints) if triple == expected]
        require(len(indices) == 1, "original input-reconstruction constraint not found exactly")
        source_residuals[indices[0]] = f"({name}[0] - sum({bits}[j] * 2**(31-j))) * {name}[0] === 0"

    for index, triple in enumerate(constraints):
        evaluated = [sum(coefficient * values[wire] for wire, coefficient in terms.items()) % PRIME
                     for terms in triple]
        residual = (evaluated[0] * evaluated[1] - evaluated[2]) % PRIME
        if residual:
            failures.append({"constraint_index_zero_based": index,
                             "original_constraint": source_residuals.get(index, "unclassified"),
                             "A": str(evaluated[0]), "B": str(evaluated[1]), "C": str(evaluated[2]),
                             "A_times_B_minus_C_mod_p": str(residual)})

    report = {
        "scope": "one preserved fixture assignment against unmodified historical XorWords(1, 32)",
        "project_revision": "4551ca64c9fe536b7b9b7498a1feb1ecdc847474",
        "candidate_path": str(CANDIDATE.relative_to(ROOT)), "candidate_sha256": CANDIDATE_SHA256,
        "source_sha256": SOURCE_PINS,
        "compiler_version": version.stdout.strip(), "compile_command": command, "compile_exit_code": result.returncode,
        "r1cs_sha256": sha256(r1cs_path), "sym_sha256": sha256(sym_path),
        "source_or_constraint_changes": [], "added_harness_constraints": [],
        "entrypoint": "upstream circuits/tests/xor32bits.circom: component main = XorWords(1, 32)",
        "mapping": {"scalar": "main.{a,b,out} -> main.{a,b,out}[0]",
                    "bits": "main.xor.{a_bits,b_bits,xor_bits}[k] -> main.{abits,bbits,xors}[31-k]",
                    "reason": "fixture traverses low-to-high bits; original traverses high-to-low bits",
                    "checked_redundant_aliases": aliases, "field_value_conversion": "identity"},
        "mapped_named_signals": len(wire_for), "assigned_constant_wire": "wire 0 = 1",
        "unmapped_wires": [], "defaulted_wires": [],
        "nonzero_mapped_assignment": {name: str(values[wire]) for name, wire in wire_for.items() if values[wire]},
        "expected_fixture_output": candidate["5_flag"]["2_expected_output"],
        "r1cs_counts": counts, "satisfied_constraints": counts["constraints"] - len(failures),
        "failed_constraints": failures, "candidate_satisfies_original_component": not failures,
        "project_entrypoint_reachability": "not established by this component check",
        "interpretation": "Rejection applies to this exact assignment; it does not establish original-component or project safety.",
    }
    serialized = json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        with args.output.open("x") as handle:
            handle.write(serialized)
    print(serialized, end="")


if __name__ == "__main__":
    main()
