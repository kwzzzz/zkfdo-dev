#!/usr/bin/env python3
"""Reproduce the Tangle property gap without adding it to controlled-v2 metrics."""

from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "runs/tangle-diagnostic-2026-09-22"
REPORT_ROOT = ROOT / "reports/tangle-diagnostic-2026-09-22"
OUTPUT = REPORT_ROOT / "diagnosis.json"
VULNERABLE = ROOT / "datasets/controlled-v2/tangle-set-membership/vulnerable/project"
FIXED = ROOT / "datasets/controlled-v2/tangle-set-membership/fixed/project"
ZKFUZZ = ROOT / ".external/zkFuzz/target/release/zkfuzz"
CIRCOM = Path("/Users/miiz/.cargo/bin/circom")
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def run(command, stdout_path, stderr_path, timeout):
    started = utc_now()
    timer = time.monotonic()
    timed_out = False
    exit_code = None
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            completed = subprocess.run(
                command, cwd=ROOT, stdout=stdout, stderr=stderr,
                timeout=timeout, check=False,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    return {
        "command": [str(item) for item in command],
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
        "wall_seconds": time.monotonic() - timer,
        "timeout_seconds": timeout,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "stdout_path": relative(stdout_path),
        "stdout_sha256": sha256(stdout_path),
        "stderr_path": relative(stderr_path),
        "stderr_sha256": sha256(stderr_path),
    }


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
        sections[kind] = reader.take(length)
    reader.done()

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
                terms[wire] = coefficient
            triple.append(terms)
        constraints.append(triple)
    body.done()
    labels = Reader(sections[3])
    wire_labels = [labels.integer(8) for _ in range(counts["wires"])]
    labels.done()
    return counts, constraints, wire_labels


def read_symbols(path, wire_labels):
    names = {}
    for line in path.read_text().splitlines():
        label_text, wire_text, _component, name = line.split(",", 3)
        label = int(label_text)
        wire = int(wire_text)
        if wire >= 0:
            require(wire_labels[wire] == label, "symbol/R1CS mismatch")
            names[name] = wire
    return names


def evaluate(constraints, values):
    failures = []
    for index, triple in enumerate(constraints):
        evaluated = [
            sum(coefficient * values[wire] for wire, coefficient in terms.items()) % PRIME
            for terms in triple
        ]
        if (evaluated[0] * evaluated[1] - evaluated[2]) % PRIME:
            failures.append(index)
    return failures


def assignment_for(element, members, vulnerable):
    diffs = [(value - element) % PRIME for value in members]
    products = [element if vulnerable else 1]
    for difference in diffs:
        products.append(products[-1] * difference % PRIME)
    result = {"main.element": element}
    result.update({f"main.set[{index}]": value for index, value in enumerate(members)})
    result.update({f"main.diffs[{index}]": value for index, value in enumerate(diffs)})
    result.update({f"main.product[{index}]": value for index, value in enumerate(products)})
    return result


def compile_component(source_root, output_root):
    output_root.mkdir(parents=True)
    stdout = output_root / "compile.stdout.log"
    stderr = output_root / "compile.stderr.log"
    invocation = run([
        CIRCOM, source_root / "circuit.circom", "--r1cs", "--sym",
        "--prime", "bn128", "--output", output_root,
    ], stdout, stderr, 60)
    require(invocation["exit_code"] == 0 and not invocation["timed_out"], "Circom compile failed")
    r1cs = output_root / "circuit.r1cs"
    sym = output_root / "circuit.sym"
    require(r1cs.is_file() and sym.is_file(), "compile artifacts missing")
    invocation.update({
        "r1cs_path": relative(r1cs),
        "r1cs_sha256": sha256(r1cs),
        "sym_path": relative(sym),
        "sym_sha256": sha256(sym),
    })
    return invocation, r1cs, sym


def fuzz_diagnostic(name, mode, seed, generations, population, timeout, source_base):
    directory = RUN_ROOT / "diagnostic-runs" / name
    directory.mkdir(parents=True)
    source = directory / "source"
    shutil.copytree(source_base, source, symlinks=True)
    command = [ZKFUZZ, source / "circuit.circom", "--prime", "bn128", "--search_mode", mode,
               "--save_output"]
    config_path = None
    if mode == "ga":
        config = {"seed": seed, "max_generations": generations}
        if population is not None:
            config.update({
                "input_population_size": population,
                "random_value_ranges": [["0", "2"]],
                "random_value_probs": [1.0],
                "binary_mode_prob": 1.0,
            })
        config_path = directory / "mutation-settings.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n")
        command += ["--path_to_mutation_setting", config_path]
    invocation = run(command, directory / "stdout.log", directory / "stderr.log", timeout)
    candidates = sorted(source.glob("*counterexample*.json"))
    preserved = []
    for candidate in candidates:
        destination = directory / "raw-candidates" / candidate.name
        destination.parent.mkdir(exist_ok=True)
        candidate.replace(destination)
        preserved.append({"path": relative(destination), "sha256": sha256(destination)})
    text = ANSI.sub("", (directory / "stdout.log").read_text(errors="replace") + "\n" +
                    (directory / "stderr.log").read_text(errors="replace"))
    def capture(pattern):
        match = re.search(pattern, text)
        return int(match.group(1)) if match else None
    invocation.update({
        "name": name,
        "search_mode": mode,
        "seed": seed,
        "max_generations": generations,
        "input_population_size_override": population,
        "config_path": relative(config_path) if config_path else None,
        "config_sha256": sha256(config_path) if config_path else None,
        "trace_constraint_count_reported": capture(r"#Trace Constraints\s*:\s*(\d+)"),
        "side_constraint_count_reported": capture(r"#Side Constraints\s*:\s*(\d+)"),
        "input_variable_count_reported": capture(r"#Input Variables\s*:\s*(\d+)"),
        "mutation_candidate_count_reported": capture(r"#Mutation Candidate\s*:\s*(\d+)"),
        "quick_total_iterations": capture(r"Total iterations:\s*(\d+)"),
        "quick_verification_result": (
            "well-constrained" if re.search(r"Verification result:.*WellConstrained", text)
            else None
        ),
        "last_generation": capture(r"Generation\s+(\d+)\s*/"),
        "backend_candidate_count": len(preserved),
        "raw_candidates": preserved,
        "raw_candidate_values_in_summary": False,
    })
    return invocation


def main():
    require(not RUN_ROOT.exists(), f"refusing to overwrite {RUN_ROOT}")
    require(not OUTPUT.exists(), f"refusing to overwrite {OUTPUT}")
    RUN_ROOT.mkdir(parents=True)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    source_root = RUN_ROOT / "sources"
    shutil.copytree(VULNERABLE, source_root / "vulnerable", symlinks=True)
    shutil.copytree(FIXED, source_root / "fixed", symlinks=True)

    vulnerable_compile, vulnerable_r1cs, vulnerable_sym = compile_component(
        source_root / "vulnerable", RUN_ROOT / "compiled/vulnerable")
    fixed_compile, fixed_r1cs, fixed_sym = compile_component(
        source_root / "fixed", RUN_ROOT / "compiled/fixed")
    v_counts, v_constraints, v_labels = read_r1cs(vulnerable_r1cs)
    f_counts, f_constraints, f_labels = read_r1cs(fixed_r1cs)
    v_names = read_symbols(vulnerable_sym, v_labels)
    f_names = read_symbols(fixed_sym, f_labels)
    require(set(v_names) == set(f_names), "source variants have different signal mappings")

    binary_checked = 0
    vulnerable_property_witnesses = 0
    fixed_property_witnesses = 0
    vulnerable_constraint_failures = 0
    fixed_constraint_failures = 0
    for element, *members in itertools.product([0, 1], repeat=4):
        binary_checked += 1
        property_violated = element not in members
        vulnerable_assignment = assignment_for(element, members, True)
        fixed_assignment = assignment_for(element, members, False)
        vulnerable_values = {0: 1, **{wire: vulnerable_assignment[name] for name, wire in v_names.items()}}
        fixed_values = {0: 1, **{wire: fixed_assignment[name] for name, wire in f_names.items()}}
        v_failures = evaluate(v_constraints, vulnerable_values)
        f_failures = evaluate(f_constraints, fixed_values)
        vulnerable_constraint_failures += bool(v_failures)
        fixed_constraint_failures += bool(f_failures)
        if property_violated and not v_failures:
            vulnerable_property_witnesses += 1
        if property_violated and not f_failures:
            fixed_property_witnesses += 1

    diagnostics = [
        fuzz_diagnostic("quick-binary-enumeration", "quick", None, None, None, 30,
                        source_root / "vulnerable"),
        fuzz_diagnostic("ga-v2-seed-500", "ga", 2026092001, 500, None, 30,
                        source_root / "vulnerable"),
        fuzz_diagnostic("ga-binary-focused-5000", "ga", 2026092201, 5000, 128, 120,
                        source_root / "vulnerable"),
    ]
    report = {
        "schema_version": 1,
        "created_at_utc": utc_now(),
        "scope": "Tangle SetMembership development diagnostic; excluded from controlled-v2 and v3 performance metrics",
        "classification": "zkFuzz-expression-search-limit",
        "classification_detail": "The input is expressible and an assignment satisfying the vulnerable R1CS while violating membership exists, but zkFuzz's TCCT oracle compares symbolic execution with side constraints and has no external membership-property oracle.",
        "tools": {
            "zkfuzz": {"path": relative(ZKFUZZ), "sha256": sha256(ZKFUZZ)},
            "circom": {"path": str(CIRCOM), "sha256": sha256(CIRCOM)},
        },
        "sources": {
            "vulnerable_revision": "848d073bb17f0aaffc6d39f594cc59efedeaec89",
            "fixed_revision": "eeb4fc7a4883d513e3fe3adbe2c447133ccd39f2",
            "vulnerable_source_sha256": sha256(VULNERABLE / "circuits/set/membership.circom"),
            "fixed_source_sha256": sha256(FIXED / "circuits/set/membership.circom"),
            "wrapper_sha256": sha256(VULNERABLE / "circuit.circom"),
            "copied_sources_under_ignored_run_tree": True,
        },
        "contract": {
            "input_preconditions": "element and three set entries are canonical BN128 field elements",
            "property": "every satisfying assignment has element equal to at least one set entry",
            "vulnerable_expression": "element * product(set[i] - element) = 0",
            "fixed_expression": "product(set[i] - element) = 0",
        },
        "compile": {"vulnerable": vulnerable_compile, "fixed": fixed_compile},
        "oracle": {
            "method": "exhaustive {0,1}^4 input-domain enumeration plus full compiled-R1CS evaluation",
            "input_assignments_checked": binary_checked,
            "vulnerable_property_violating_satisfying_assignment_count": vulnerable_property_witnesses,
            "fixed_property_violating_satisfying_assignment_count": fixed_property_witnesses,
            "vulnerable_assignments_with_constraint_failure_count": vulnerable_constraint_failures,
            "fixed_assignments_with_constraint_failure_count": fixed_constraint_failures,
            "raw_assignment_values_persisted": False,
            "vulnerable_r1cs_counts": v_counts,
            "fixed_r1cs_counts": f_counts,
        },
        "diagnostic_runs": diagnostics,
        "summary": {
            "diagnostic_run_count": len(diagnostics),
            "backend_candidate_count": sum(item["backend_candidate_count"] for item in diagnostics),
            "all_runs_completed_without_candidate": all(
                not item["timed_out"] and item["exit_code"] == 0 and
                item["backend_candidate_count"] == 0 for item in diagnostics
            ),
            "completed_or_budget_exhausted_without_candidate": all(
                (item["timed_out"] or item["exit_code"] == 0) and
                item["backend_candidate_count"] == 0 for item in diagnostics
            ),
            "controlled_v2_metrics_modified": False,
            "ranking_weights_modified": False,
            "zkfdo_implementation_defect_found": False,
        },
        "limitations": [
            "The diagnostic classifies the current zkFuzz TCCT oracle boundary; it does not prove that no future property-aware extension can detect the defect.",
            "The GA runs supplement the exhaustive quick-mode oracle-boundary check and are not performance trials.",
            "Raw logs and any raw candidates stay below the ignored runs directory.",
        ],
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"classification": report["classification"], **report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
