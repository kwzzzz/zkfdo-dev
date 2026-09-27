#!/usr/bin/env python3
"""Build deterministic common-review specs and requests for the preserved v1.1-v3 cases."""

import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
PROVENANCE = HERE / "provenance"
PRIME = "21888242871839275222246405745257275088548364400416034343698204186575808495617"
CIRCOM_SHA256 = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
ENGINE_SOURCE = ROOT / "src/candidate_review/engine.rs"
ADAPTER_SHA256 = hashlib.sha256(
    ENGINE_SOURCE.read_bytes()
    + b"\0"
    + b"zkfDO candidate adapter zkfuzz-counterexample-v1 schema 1\n"
).hexdigest()


CASES = {
    "v1.1": {
        "target_id": "sha256:1fdbf2dbcb8c5be4cad2ef0937cdc95c1b36cc8321e2d02f1b820f46c1b91474",
        "root_cause_id": "inference-labs-inc/subnet-2-circom/koukyosyumei_subtract_unconstrained_multiplier",
        "review_spec_id": "regression/v1.1/subtract",
        "contract": "datasets/contracts.controlled-v1.json",
        "pair_index": 0,
        "source": "datasets/controlled-v1/subtract/vulnerable/subtractTensor.circom",
        "r1cs": "reports/controlled-v1.1-execution-2026-09-20/evidence/vulnerable-component/compiled/circuit.r1cs",
        "sym": "reports/controlled-v1.1-execution-2026-09-20/evidence/vulnerable-component/compiled/circuit.sym",
        "predicate": "reports/candidate-review-regression-2026-09-27/predicates/subtract.py",
        "shape": {"wires": 5, "labels": 5, "public_outputs": 1, "public_inputs": 0, "private_inputs": 2, "constraints": 1},
        "inputs": ["main.a", "main.b"],
        "property_signals": ["main.c"],
        "parameters": [],
        "input_statement": "a and b are canonical BN128 field elements.",
        "property_statement": "The constrained subtraction output equals a minus b modulo the field.",
        "violation_classes": ["subtraction-output-mismatch"],
        "records": "reports/controlled-v1.1-execution-2026-09-20/evidence/records",
    },
    "v2": {
        "target_id": "sha256:b99bf2694b89536d1c7ca1ef97933456981930df93e7bfc08d0b61149a7bc496",
        "root_cause_id": "banyancomputer/hot-proofs-blake3-circom/check-depth-comparator-range",
        "review_spec_id": "regression/v2/banyan-check-depth",
        "contract": "datasets/contracts.controlled-v2.json",
        "pair_index": 1,
        "source": "datasets/controlled-v2/banyan-check-depth/vulnerable/project/source/circuits/blake3_nova.circom",
        "r1cs": "reports/controlled-v2-execution-2026-09-20/evidence/banyan-vulnerable-compiled/circuit.r1cs",
        "sym": "reports/controlled-v2-execution-2026-09-20/evidence/banyan-vulnerable-compiled/circuit.sym",
        "predicate": "reports/candidate-review-regression-2026-09-27/predicates/banyan.py",
        "shape": {"wires": 29, "labels": 40, "public_outputs": 2, "public_inputs": 0, "private_inputs": 2, "constraints": 29},
        "inputs": ["main.depth", "main.leaf_depth"],
        "property_signals": ["main.is_parent", "main.is_root"],
        "parameters": [],
        "input_statement": "depth and leaf_depth are canonical BN128 field elements.",
        "property_statement": "Inputs are 8-bit and satisfy the declared depth, order, root, and parent relations.",
        "violation_classes": ["in-range-order-or-output-relation", "input-outside-required-8-bit-component-domain"],
        "records": "reports/controlled-v2-execution-2026-09-20/evidence/records",
    },
    "v3": {
        "target_id": "sha256:593ebf069393e830a57a6cf4f611cee14562ae6b351e218495ea86b38530fd21",
        "root_cause_id": "iden3/circomlib/decoder-unconstrained-one-hot-output",
        "review_spec_id": "regression/v3/decoder",
        "contract": "datasets/contracts.controlled-v3-development.json",
        "pair_index": 0,
        "source": "datasets/controlled-v3/circomlib-decoder/vulnerable/project/circuits/multiplexer.circom",
        "r1cs": "runs/controlled-v3-development/pilot-2026-09-23/review-decoder-r1cs/circuit.r1cs",
        "sym": "runs/controlled-v3-development/pilot-2026-09-23/review-decoder-r1cs/circuit.sym",
        "predicate": "reports/candidate-review-regression-2026-09-27/predicates/decoder.py",
        "shape": {"wires": 7, "labels": 7, "public_outputs": 5, "public_inputs": 0, "private_inputs": 1, "constraints": 6},
        "inputs": ["main.inp"],
        "property_signals": ["main.out[0]", "main.out[1]", "main.out[2]", "main.out[3]", "main.success"],
        "parameters": [{"position": 0, "name": "w", "kind": "integer", "value_decimal": "4"}],
        "input_statement": "inp is a canonical BN128 field element.",
        "property_statement": "The outputs are the one-hot decoding of inp and success is their field sum.",
        "violation_classes": ["one-hot-output-equivalence", "success-sum"],
        "plan": "reports/controlled-v3-preflight-2026-09-23/evidence/plan.json",
        "outcome": "reports/controlled-v3-pilot-2026-09-23/evidence/outcome.json",
    },
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(declaring_file, target):
    return os.path.relpath(Path(target).resolve(), Path(declaring_file).resolve().parent)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=False) + "\n"
    if path.exists() and path.read_text() == encoded:
        return
    path.write_text(encoded)


def source_manifest(case_name, plan, target):
    destination = PROVENANCE / f"{case_name}-source-closure.json"
    files = []
    for fingerprint in sorted(target["source_fingerprints"], key=lambda item: item["path"]):
        path = Path(fingerprint["path"])
        if digest(path) != fingerprint["sha256"]:
            raise ValueError(f"source fingerprint changed: {path}")
        files.append({
            "path": relative(destination, path),
            "size": path.stat().st_size,
            "sha256": fingerprint["sha256"],
        })
    write_json(destination, {"schema_version": 1, "files": files})
    return destination


def allowed_results():
    return [
        {"criterion": "input_preconditions", "verdict": "satisfied", "reason_code": "contract-satisfied", "note": "The predeclared input contract is satisfied."},
        {"criterion": "input_preconditions", "verdict": "not-satisfied", "reason_code": "input-noncanonical", "note": "At least one declared input is not a canonical field element."},
        {"criterion": "specified_property_violation", "verdict": "satisfied", "reason_code": "property-violated", "note": "The predeclared property is violated."},
        {"criterion": "specified_property_violation", "verdict": "not-satisfied", "reason_code": "property-holds", "note": "The predeclared property holds for this assignment."},
        {"criterion": "specified_property_violation", "verdict": "unknown", "reason_code": "input-precondition-unresolved", "note": "The property cannot be interpreted because its input precondition is unresolved."},
    ]


def plan_outcome_pairs(case_name, case):
    if case_name == "v3":
        return [(None, ROOT / case["plan"], ROOT / case["outcome"])]
    result = []
    for plan_path in sorted((ROOT / case["records"]).glob("block-*/attempt-01/*/plan.json")):
        block = int(plan_path.parents[2].name.removeprefix("block-"))
        result.append((block, plan_path, plan_path.with_name("outcome.json")))
    if len(result) != 36:
        raise ValueError(f"{case_name} expected 36 plan/outcome pairs, found {len(result)}")
    return result


def build_case(case_name, case):
    pairs = plan_outcome_pairs(case_name, case)
    representative_plan = json.loads(pairs[0][1].read_text())
    target = next(item for item in representative_plan["targets"] if item["target_id"] == case["target_id"])
    contract_path = ROOT / case["contract"]
    contract = json.loads(contract_path.read_text())
    pair = contract["pairs"][case["pair_index"]]
    variant = next(item for item in pair["variants"] if item["role"] == "published-vulnerable-source")
    if variant["source_sha256"] != digest(ROOT / case["source"]):
        raise ValueError(f"{case_name} source changed")
    closure = source_manifest(case_name, representative_plan, target)
    spec_path = INPUTS / f"{case_name}-spec.json"
    spec = {
        "schema_version": 1,
        "review_spec_id": case["review_spec_id"],
        "root_cause_id": case["root_cause_id"],
        "subject_kind": "published-vulnerable-source",
        "expected_scope": "original-component",
        "target_binding": {
            "target_id": case["target_id"],
            "instance_key": None,
            "template": target["definition"]["template_name"],
            "concrete_parameters": case["parameters"],
            "source_path": relative(spec_path, ROOT / case["source"]),
            "source_sha256": digest(ROOT / case["source"]),
            "source_closure_manifest_path": relative(spec_path, closure),
            "source_closure_manifest_sha256": digest(closure),
        },
        "field": {"name": "bn128", "modulus_decimal": PRIME, "assignment_encoding": "canonical-field-elements"},
        "compiled_subject": {
            "r1cs_path": relative(spec_path, ROOT / case["r1cs"]),
            "r1cs_sha256": digest(ROOT / case["r1cs"]),
            "sym_path": relative(spec_path, ROOT / case["sym"]),
            "sym_sha256": digest(ROOT / case["sym"]),
            "expected_shape": case["shape"],
        },
        "compiler": {
            "version": "2.2.3",
            "binary_sha256": CIRCOM_SHA256,
            "arguments": target["definition"]["compile_args"],
            "library_manifest_path": relative(spec_path, closure),
            "library_manifest_sha256": digest(closure),
        },
        "contract": {
            "definition_path": relative(spec_path, contract_path),
            "definition_sha256": digest(contract_path),
            "input_contract_id": f"{case_name}-preserved-input-contract",
            "property_id": f"{case_name}-preserved-property",
            "input_contract_statement": case["input_statement"],
            "property_statement": case["property_statement"],
            "input_signal_names": case["inputs"],
            "property_signal_names": case["property_signals"],
            "predicate": {
                "api_version": 1,
                "path": relative(spec_path, ROOT / case["predicate"]),
                "sha256": digest(ROOT / case["predicate"]),
                "entrypoint": "evaluate",
                "config": {},
                "allowed_results": allowed_results(),
                "allowed_violation_classes": case["violation_classes"],
            },
        },
        "attribution": {
            "method": "known-defect-single-target",
            "evidence_path": relative(spec_path, contract_path),
            "evidence_sha256": digest(contract_path),
        },
        "production_reachability": {
            "verdict": "unknown",
            "entrypoint_target_id": None,
            "instance_key": None,
            "evidence_path": None,
            "evidence_sha256": None,
            "verifier_manifest_path": None,
            "verifier_manifest_sha256": None,
        },
        "injection_ground_truth": None,
    }
    write_json(spec_path, spec)

    request_path = INPUTS / f"{case_name}-request.json"
    executions = []
    for block, plan_path, outcome_path in pairs:
        plan = json.loads(plan_path.read_text())
        strategy = plan["strategy"]
        execution_id = f"{case_name}-{strategy}" if block is None else f"{case_name}-block-{block:02d}-{strategy}"
        executions.append({
            "execution_id": execution_id,
            "campaign_coordinates": None if block is None else {"block": block, "strategy": strategy},
            "plan": {"path": relative(request_path, plan_path), "sha256": digest(plan_path)},
            "outcome": {"path": relative(request_path, outcome_path), "sha256": digest(outcome_path)},
        })
    request = {
        "schema_version": 1,
        "request_id": f"candidate-review-regression-{case_name}",
        "kind": "backend-candidates",
        "review_specs": [{"path": relative(request_path, spec_path), "sha256": digest(spec_path)}],
        "executions": executions,
        "candidate_adapter": {"id": "zkfuzz-counterexample-v1", "implementation_sha256": ADAPTER_SHA256},
        "candidate_policy": "all-outcome-candidates",
        "unmatched_candidate_policy": "record-unreviewed",
        "qualification_bundles": [],
    }
    write_json(request_path, request)


def build_engine_manifest():
    destination = PROVENANCE / "engine-source-manifest.json"
    paths = [
        ROOT / "Cargo.toml",
        ROOT / "Cargo.lock",
        ROOT / "src/candidate_review/mod.rs",
        ROOT / "src/candidate_review/schema.rs",
        ROOT / "src/candidate_review/r1cs.rs",
        ROOT / "src/candidate_review/predicate.rs",
        ROOT / "src/candidate_review/subprocess.rs",
        ROOT / "src/candidate_review/engine.rs",
        ROOT / "src/structure.rs",
        ROOT / "src/targets.rs",
        ROOT / "src/experiment.rs",
        ROOT / "src/cli.rs",
        Path(__file__).resolve(),
    ]
    files = sorted(({
        "path": relative(destination, path),
        "size": path.stat().st_size,
        "sha256": digest(path),
    } for path in paths), key=lambda entry: entry["path"])
    write_json(destination, {"schema_version": 1, "files": files})


def main():
    for case_name, case in CASES.items():
        build_case(case_name, case)
    build_engine_manifest()
    print(json.dumps({"cases": sorted(CASES), "adapter_sha256": ADAPTER_SHA256}))


if __name__ == "__main__":
    main()
