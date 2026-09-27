#!/usr/bin/env python3
"""Cross-check value-free common-review outputs against the frozen v1.1-v3 records.

The default tracked-evidence mode verifies every reference that resolves to a Git-tracked
file and skips references to ignored or external local evidence (raw candidates, compiled
artifacts, the preserved executable, the predicate interpreter). It also leaves the current
engine sources unchecked, because the reports bind the recorded source snapshot rather than
the working tree. `--require-local-evidence` additionally requires every such reference to
exist with its recorded hash and the working tree to equal the recorded engine snapshot.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS = HERE / "results"
EXPECTED = {
    "v1.1": {
        "pairs": 36,
        "executions": 72,
        "candidates": 36,
        "root": "inference-labs-inc/subnet-2-circom/koukyosyumei_subtract_unconstrained_multiplier",
        "class": "subtraction-output-mismatch",
        "frozen_review": "reports/controlled-v1.1-execution-2026-09-20/candidate-review.json",
        "frozen_evaluation": "reports/controlled-v1.1-execution-2026-09-20/evaluation-index.json",
    },
    "v2": {
        "pairs": 36,
        "executions": 144,
        "candidates": 36,
        "root": "banyancomputer/hot-proofs-blake3-circom/check-depth-comparator-range",
        "class": "input-outside-required-8-bit-component-domain",
        "frozen_review": "reports/controlled-v2-execution-2026-09-20/candidate-review.json",
        "frozen_evaluation": "reports/controlled-v2-execution-2026-09-20/evaluation-index.json",
    },
    "v3": {
        "pairs": 1,
        "executions": 4,
        "candidates": 1,
        "root": "iden3/circomlib/decoder-unconstrained-one-hot-output",
        "class": "one-hot-output-equivalence",
        "frozen_review": "reports/controlled-v3-pilot-2026-09-23/candidate-review.json",
        "frozen_evaluation": "reports/controlled-v3-pilot-2026-09-23/evaluation.json",
        "frozen_evidence": "reports/controlled-v3-pilot-2026-09-23/evidence.json",
    },
}

# These are keys used by raw zkFuzz candidates or in-memory predicate inputs. Paths,
# hashes, verdicts, constraint indices, and value-free notes are intentionally allowed.
FORBIDDEN_VALUE_KEYS = {
    "0_target_path",
    "1_main_template",
    "2_search_mode",
    "3_execution_time",
    "4_git_hash_of_zkfuzz",
    "5_flag",
    "6_target_output",
    "7_assignment",
    "8_auxiliary_result",
    "assignment",
    "assignment_values",
    "clean_reference_signals",
    "eliminated_signals",
    "field_modulus_decimal",
    "fixed_signals",
    "predicate_config",
    "signal_values",
    "value_decimal",
    "wire_signals",
    "witness",
}
REPORT_CRITERIA = {
    "assignment_encoding",
    "input_preconditions",
    "fixed_target_constraints",
    "specified_property_violation",
}
SEMANTIC_IGNORED_KEYS = {
    "path",
    "automated_review_seconds",
    "note",
    "semantic_result_sha256",
}
SEMANTIC_NUMERIC_INDEX_KEYS = {
    "failed_target_constraint_indices",
    "failed_clean_constraint_indices",
    "checked_clean_constraint_indices",
}
SEMANTIC_CANONICAL_SET_KEYS = {
    "fixed_signal_names",
    "evidence",
}
EVALUATOR_NONSEMANTIC_FIELDS = {"report_path", "timings"}
CANDIDATE_ADAPTER_DESCRIPTOR = b"zkfDO candidate adapter zkfuzz-counterexample-v1 schema 1\n"
REQUIRED_ENGINE_SOURCES = (
    "src/candidate_review/engine.rs",
    "src/experiment.rs",
    "src/candidate_review/predicate.rs",
    "src/candidate_review/r1cs.rs",
    "src/candidate_review/schema.rs",
    "src/candidate_review/subprocess.rs",
    "src/structure.rs",
    "src/targets.rs",
)


class Evidence:
    """Which references must be present and hash-identical in the current checkout."""

    def __init__(self, require_local):
        self.require_local = require_local
        self.tracked = None if require_local else tracked_files()
        self.skipped = set()

    @property
    def mode(self):
        return "local-evidence" if self.require_local else "tracked-evidence"

    def must_verify(self, target):
        if self.require_local or target in self.tracked:
            return True
        self.skipped.add(target)
        return False


def tracked_files():
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    return {
        (ROOT / os.fsdecode(entry)).resolve()
        for entry in listing.split(b"\0")
        if entry
    }


EVIDENCE = None


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def equal(actual, expected, context):
    require(actual == expected, f"{context}: expected {expected!r}, got {actual!r}")


def resolve_reference(declaring_file, reference):
    target = (declaring_file.parent / reference["path"]).resolve()
    if EVIDENCE.must_verify(target):
        require(target.is_file(), f"missing referenced file: {target}")
        equal(digest(target), reference["sha256"], f"SHA-256 for {target}")
    return target


def reference_identity(declaring_file, reference):
    return (str(resolve_reference(declaring_file, reference)), reference["sha256"])


def resolve_root_record(path, sha256, context):
    target = (ROOT / path).resolve()
    if EVIDENCE.must_verify(target):
        require(target.is_file(), f"{context} is missing: {target}")
        equal(digest(target), sha256, f"{context} SHA-256")
    return target


def verify_criterion_references(report_path, criterion, context):
    if criterion is None:
        return
    for index, evidence in enumerate(criterion["evidence"]):
        resolve_reference(report_path, evidence)


def verify_review_references(report_path, report):
    if report["failure"] is not None:
        for evidence in report["failure"]["evidence"]:
            resolve_reference(report_path, evidence)
    for unreviewed in report["unreviewed_candidates"]:
        resolve_reference(report_path, unreviewed["candidate"])
    for review_index, review in enumerate(report["reviews"]):
        context = f"review {review_index}"
        if review["candidate"] is not None:
            resolve_reference(report_path, review["candidate"])
        resolve_reference(
            report_path,
            {
                "path": review["review_spec"]["path"],
                "sha256": review["review_spec"]["sha256"],
            },
        )
        if "assignments" in review:
            resolve_reference(report_path, review["assignments"]["disturbance"])
            resolve_reference(report_path, review["assignments"]["clean_reference"])
        for name, criterion in review["criteria"].items():
            verify_criterion_references(
                report_path,
                criterion,
                f"{context} criterion {name}",
            )
        for name, criterion in review.get("qualification_criteria", {}).items():
            verify_criterion_references(
                report_path,
                criterion,
                f"{context} qualification criterion {name}",
            )
        for evidence in review["cause_attribution"]["evidence"]:
            resolve_reference(report_path, evidence)


def verify_directory_manifest(path, check_files=True):
    manifest = load(path)
    equal(set(manifest), {"schema_version", "files"}, f"directory manifest fields for {path}")
    equal(manifest["schema_version"], 1, f"directory manifest schema for {path}")
    require(manifest["files"], f"empty directory manifest: {path}")
    logical_paths = []
    entries = {}
    for entry in manifest["files"]:
        equal(set(entry), {"path", "size", "sha256"}, f"directory manifest entry fields for {path}")
        logical = entry["path"]
        require(isinstance(logical, str) and logical, f"invalid logical path in {path}")
        require(not Path(logical).is_absolute(), f"absolute logical path in {path}: {logical}")
        require(type(entry["size"]) is int and entry["size"] >= 0, f"invalid size in {path}: {logical}")
        require(
            isinstance(entry["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
            f"invalid SHA-256 in {path}: {logical}",
        )
        logical_paths.append(logical)
        target = (path.parent / logical).resolve()
        require(target not in entries, f"duplicate resolved manifest file: {target}")
        entries[target] = entry["sha256"]
        if not check_files:
            continue
        require(target.is_file(), f"missing manifest file: {target}")
        equal(target.stat().st_size, entry["size"], f"size for {target}")
        equal(digest(target), entry["sha256"], f"SHA-256 for {target}")
    equal(logical_paths, sorted(set(logical_paths)), f"sorted unique manifest paths for {path}")
    return entries


def verify_required_engine_sources(engine_files):
    for relative_source in REQUIRED_ENGINE_SOURCES:
        source = (ROOT / relative_source).resolve()
        require(source in engine_files, f"engine source manifest omits {relative_source}")
        equal(
            engine_files[source],
            digest(source),
            f"engine source manifest binds current {relative_source}",
        )


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def semanticize(value):
    if isinstance(value, list):
        return [semanticize(entry) for entry in value]
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key in SEMANTIC_IGNORED_KEYS:
                continue
            semantic = semanticize(child)
            if key in SEMANTIC_NUMERIC_INDEX_KEYS and isinstance(semantic, list):
                require(
                    all(type(entry) is int and entry >= 0 for entry in semantic),
                    f"{key} must contain nonnegative integers",
                )
                semantic = sorted(set(semantic))
            elif key in SEMANTIC_CANONICAL_SET_KEYS and isinstance(semantic, list):
                by_encoding = {canonical_json(entry): entry for entry in semantic}
                semantic = [by_encoding[encoding] for encoding in sorted(by_encoding)]
            result[key] = semantic
        return result
    require(not isinstance(value, float), "semantic projection unexpectedly contains a float")
    return value


def semantic_result_sha256(report):
    projection = {
        "schema_version": 1,
        "kind": report["kind"],
        "request_sha256": report["review_request"]["sha256"],
        "spec_sha256s": sorted(reference["sha256"] for reference in report["review_specs"]),
        "engine": {
            "source_manifest_sha256": report["engine"]["source_manifest_sha256"],
            "executable_sha256": report["engine"]["executable_sha256"],
            "predicate_runner_sha256": report["engine"]["predicate_runner_sha256"],
        },
        "adapters": sorted(
            report["adapters"],
            key=lambda adapter: (adapter["id"], adapter["implementation_sha256"]),
        ),
        "candidate_inventory": semanticize(report["candidate_inventory"]),
        "executions": semanticize(report["executions"]),
        "candidate_errors": semanticize(report["candidate_errors"]),
        "unreviewed_candidates": semanticize(report["unreviewed_candidates"]),
        "reviews": semanticize(report["reviews"]),
    }
    return hashlib.sha256(canonical_json(projection).encode()).hexdigest()


def verify_semanticize_ordering():
    equal(
        semanticize(
            {
                "failed_target_constraint_indices": [10, 2, 10],
                "evidence": [
                    {"path": "z", "sha256": "b"},
                    {"path": "a", "sha256": "a"},
                    {"path": "duplicate", "sha256": "a"},
                ],
            }
        ),
        {
            "failed_target_constraint_indices": [2, 10],
            "evidence": [{"sha256": "a"}, {"sha256": "b"}],
        },
        "semantic projection ordering self-check",
    )


def verify_report_bindings(bundle_path, bundle, request_path, request, report_path, report):
    equal(report["report_id"], request["request_id"], "report/request id")
    equal(report["kind"], request["kind"], "report/request kind")
    equal(report["review_request"], bundle["review_request"], "bundle/report request reference")
    equal(report["review_specs"], bundle["review_specs"], "bundle/report spec references")

    bundle_specs = {
        reference_identity(bundle_path, reference) for reference in bundle["review_specs"]
    }
    request_specs = {
        reference_identity(request_path, reference) for reference in request["review_specs"]
    }
    report_specs = {
        reference_identity(report_path, reference) for reference in report["review_specs"]
    }
    equal(request_specs, bundle_specs, "request/bundle resolved spec references")
    equal(report_specs, bundle_specs, "report/bundle resolved spec references")

    engine = report["engine"]
    equal(engine["version"], "candidate-review-schema1", "review engine version")
    engine_manifest_path = resolve_reference(
        report_path,
        {
            "path": engine["source_manifest_path"],
            "sha256": engine["source_manifest_sha256"],
        },
    )
    # The manifest records the engine snapshot that produced these reports. Only local-evidence
    # mode compares that snapshot with the working tree, which may have moved on since.
    engine_files = verify_directory_manifest(
        engine_manifest_path,
        check_files=EVIDENCE.require_local,
    )
    engine_source = (ROOT / "src/candidate_review/engine.rs").resolve()
    for relative_source in REQUIRED_ENGINE_SOURCES:
        require(
            (ROOT / relative_source).resolve() in engine_files,
            f"engine source manifest omits {relative_source}",
        )
    if EVIDENCE.require_local:
        verify_required_engine_sources(engine_files)
    resolve_reference(
        report_path,
        {
            "path": engine["executable_path"],
            "sha256": engine["executable_sha256"],
        },
    )
    resolve_reference(
        report_path,
        {
            "path": engine["predicate_runner_path"],
            "sha256": engine["predicate_runner_sha256"],
        },
    )
    equal(
        engine["source_revision"],
        f"worktree-engine-manifest:{engine['source_manifest_sha256']}",
        "engine source revision binding",
    )

    equal(request["candidate_adapter"]["id"], "zkfuzz-counterexample-v1", "request adapter id")
    equal(report["adapters"], [request["candidate_adapter"]], "report candidate adapters")
    if EVIDENCE.require_local:
        expected_adapter = {
            "id": "zkfuzz-counterexample-v1",
            "implementation_sha256": hashlib.sha256(
                engine_source.read_bytes() + b"\0" + CANDIDATE_ADAPTER_DESCRIPTOR
            ).hexdigest(),
        }
        equal(request["candidate_adapter"], expected_adapter, "request candidate adapter")
    equal(
        semantic_result_sha256(report),
        report["semantic_result_sha256"],
        "report semantic result SHA-256",
    )
    verify_review_references(report_path, report)


def coordinate_key(coordinates):
    if coordinates is None:
        return None
    return (coordinates["block"], coordinates["strategy"])


def keyed(rows, key, context):
    result = {}
    for row in rows:
        value = key(row)
        require(value not in result, f"duplicate {context}: {value!r}")
        result[value] = row
    return result


def walk_for_raw_values(
    value,
    source,
    forbidden_exact_values=(),
    forbidden_substrings=(),
    json_path="$",
):
    if isinstance(value, dict):
        for key, child in value.items():
            require(
                key not in FORBIDDEN_VALUE_KEYS,
                f"raw-value key {key!r} persisted in {source} at {json_path}",
            )
            walk_for_raw_values(
                child,
                source,
                forbidden_exact_values,
                forbidden_substrings,
                f"{json_path}.{key}",
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_for_raw_values(
                child,
                source,
                forbidden_exact_values,
                forbidden_substrings,
                f"{json_path}[{index}]",
            )
    elif isinstance(value, str):
        require(
            value not in forbidden_exact_values,
            f"raw assignment value persisted in {source} at {json_path}",
        )
        for fragment in forbidden_substrings:
            require(
                fragment not in value,
                f"raw assignment value persisted in {source} at {json_path}",
            )
    elif type(value) is int:
        require(
            str(value) not in forbidden_substrings,
            f"raw assignment value persisted in {source} at {json_path}",
        )


def candidate_value_guard(report_path, report):
    exact_values = set()
    for review in report["reviews"]:
        candidate = review["candidate"]
        if candidate is None:
            continue
        candidate_path = resolve_reference(report_path, candidate)
        if not EVIDENCE.must_verify(candidate_path):
            continue
        raw = load(candidate_path)
        assignment = raw.get("7_assignment")
        require(isinstance(assignment, dict), f"candidate lacks assignment object: {candidate_path}")
        for value in assignment.values():
            require(
                isinstance(value, (str, int)) and not isinstance(value, bool),
                f"candidate assignment contains a nonscalar value: {candidate_path}",
            )
            text = str(value)
            exact_values.add(text)
    distinctive_substrings = {value for value in exact_values if len(value) >= 8}
    return exact_values, distinctive_substrings


def verify_raw_value_guard():
    for value, exact_values, substrings in [
        ({"note": "7"}, {"7"}, set()),
        ({"note": "prefix-12345678-suffix"}, {"12345678"}, {"12345678"}),
    ]:
        try:
            walk_for_raw_values(value, "raw-value-self-check", exact_values, substrings)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"raw-value self-check accepted {value!r}")

    # Short assignment values are rejected as exact strings, but ordinary numeric
    # schema counts cannot be distinguished from raw 0/1 values and remain allowed.
    walk_for_raw_values({"count": 1}, "raw-value-self-check", {"1"}, set())
    walk_for_raw_values({"note": "prefix-7"}, "raw-value-self-check", {"7"}, set())


def verify_provenance_negative_checks():
    for check, context in [
        (lambda: verify_required_engine_sources({}), "missing engine source"),
        (
            lambda: resolve_reference(
                Path(__file__).resolve(),
                {"path": Path(__file__).name, "sha256": "0" * 64},
            ),
            "bad internal FileRef hash",
        ),
        (
            lambda: resolve_root_record(
                str(Path(__file__).resolve().relative_to(ROOT)),
                "0" * 64,
                "bad frozen record",
            ),
            "bad frozen record hash",
        ),
    ]:
        try:
            check()
        except AssertionError:
            pass
        else:
            raise AssertionError(f"provenance self-check accepted {context}")


def load_frozen_pairs(case, expected):
    review_path = ROOT / expected["frozen_review"]
    evaluation_path = ROOT / expected["frozen_evaluation"]

    if case == "v3":
        evidence_path = ROOT / expected["frozen_evidence"]
        evidence = load(evidence_path)
        evidence_records = {}
        for index, record in enumerate(evidence["records"]):
            target = resolve_root_record(
                record["path"],
                record["sha256"],
                f"v3 frozen evidence record {index}",
            )
            require(target not in evidence_records, f"duplicate v3 evidence target: {target}")
            evidence_records[target] = record["sha256"]
        require(review_path.resolve() in evidence_records, "v3 evidence omits candidate review")
        require(evaluation_path.resolve() in evidence_records, "v3 evidence omits evaluation")
        frozen_review = load(review_path)
        frozen_evaluation = load(evaluation_path)
        equal(frozen_review["candidate_count"], 1, "v3 frozen candidate count")
        equal(len(frozen_review["reviews"]), 1, "v3 frozen review count")
        review_row = dict(frozen_review["reviews"][0])
        review_row["plan_sha256"] = frozen_review["plan_sha256"]
        review_row["outcome_sha256"] = frozen_review["outcome_sha256"]
        equal(review_row["root_cause_id"], expected["root"], "v3 frozen root cause")
        return {None: {"review": review_row, "evaluation": frozen_evaluation}}

    frozen_evaluation = load(evaluation_path)
    bound_review_path = resolve_root_record(
        frozen_evaluation["candidate_review_path"],
        frozen_evaluation["candidate_review_sha256"],
        f"{case} frozen candidate review",
    )
    equal(bound_review_path, review_path.resolve(), f"{case} frozen review path binding")
    frozen_review = load(review_path)
    equal(frozen_review["root_cause_id"], expected["root"], f"{case} frozen root cause")
    review_rows = keyed(
        frozen_review["candidate_reviews"],
        lambda row: (row["block"], row["strategy"]),
        f"{case} frozen review coordinate",
    )
    evaluation_rows = keyed(
        frozen_evaluation["records"],
        lambda row: (row["block"], row["strategy"]),
        f"{case} frozen evaluation coordinate",
    )
    equal(set(review_rows), set(evaluation_rows), f"{case} frozen coordinate inventory")
    equal(len(review_rows), expected["pairs"], f"{case} frozen pair count")

    pairs = {}
    for coordinates, review_row in review_rows.items():
        evaluation_row = evaluation_rows[coordinates]
        for artifact in ("plan", "outcome", "confirmation", "evaluation"):
            resolve_root_record(
                evaluation_row[f"{artifact}_path"],
                evaluation_row[f"{artifact}_sha256"],
                f"{case} frozen {coordinates} {artifact}",
            )
        for field in ("run_id", "target_id", "completion_time_upper_bound_seconds"):
            equal(
                review_row[field],
                evaluation_row[field],
                f"{case} frozen {coordinates} {field}",
            )
        for field in ("plan_sha256", "outcome_sha256"):
            equal(
                review_row[field],
                evaluation_row[field],
                f"{case} frozen {coordinates} {field}",
            )
        # The per-pair evaluator outputs were kept under ignored runs/; the tracked index pins
        # their hashes. Without them only the tracked review and index fields are compared.
        evaluation_output_path = (ROOT / evaluation_row["evaluation_path"]).resolve()
        pairs[coordinates] = {
            "review": review_row,
            "evaluation": (
                load(evaluation_output_path)
                if EVIDENCE.must_verify(evaluation_output_path)
                else None
            ),
            "evaluation_record": evaluation_row,
        }
    return pairs


def compare_frozen_review(case, generated, frozen, expected, context):
    binding = generated["binding"]
    for field in ("run_id", "target_id"):
        equal(binding[field], frozen[field], f"{context} frozen review {field}")
    equal(generated["candidate"]["sha256"], frozen["candidate_sha256"], f"{context} candidate hash")
    equal(generated["disposition"], frozen["disposition"], f"{context} disposition")
    equal(generated["disposition"], "validated", f"{context} validated disposition")
    equal(generated["root_cause_id"], expected["root"], f"{context} root cause")
    equal(generated["expected_scope"], "original-component", f"{context} scope")
    equal(generated["violation_class"], expected["class"], f"{context} violation class")
    equal(set(generated["criteria"]), REPORT_CRITERIA, f"{context} report criteria")
    for generated_name, frozen_name in (
        ("input_preconditions", "input_preconditions"),
        ("fixed_target_constraints", "fixed_original_constraints"),
        ("specified_property_violation", "specified_property_violation"),
    ):
        equal(
            generated["criteria"][generated_name]["verdict"],
            frozen["criteria"][frozen_name]["verdict"],
            f"{context} {generated_name} verdict",
        )
        equal(
            generated["criteria"][generated_name]["verdict"],
            "satisfied",
            f"{context} satisfied {generated_name}",
        )
    equal(
        generated["criteria"]["assignment_encoding"]["verdict"],
        "satisfied",
        f"{context} canonical assignment encoding",
    )
    equal(generated["cause_attribution"]["verdict"], "matched", f"{context} attribution")
    equal(generated["failed_target_constraint_count"], 0, f"{context} failed constraints")
    equal(generated["failed_target_constraint_indices"], [], f"{context} failed indices")
    require(generated["confirmation_eligible"] is True, f"{context} is not confirmation eligible")

    if case == "v2":
        equal(
            frozen["property_violation_class"],
            expected["class"],
            f"{context} frozen violation class",
        )
    elif case == "v3":
        equal(
            frozen["criteria"]["specified_property_violation"]["violation_class"],
            expected["class"],
            f"{context} frozen violation class",
        )


def verify_outcome_rows(execution_id, outcome, report_rows, context):
    scheduler_runs = outcome["scheduler"]["runs"]
    candidates = Counter(
        (candidate["run_id"], candidate["target_id"])
        for candidate in outcome["counterexample_candidates"]
    )
    rows_by_index = keyed(report_rows, lambda row: row["plan_index"], f"{context} plan index")
    equal(len(rows_by_index), len(scheduler_runs), f"{context} execution row count")

    candidate_rows = 0
    for scheduler_run in scheduler_runs:
        index = scheduler_run["index"]
        require(index in rows_by_index, f"{context} is missing plan index {index}")
        row = rows_by_index[index]
        result = scheduler_run["result"]
        require(result is not None, f"{context} unexpectedly contains an unstarted run")
        equal(row["execution_id"], execution_id, f"{context} execution id")
        equal(row["run_id"], result["run_id"], f"{context} run {index} id")
        equal(row["target_id"], scheduler_run["target_id"], f"{context} run {index} target")
        equal(row["backend_status"], result["status"], f"{context} run {index} status")
        candidate_count = candidates[(result["run_id"], scheduler_run["target_id"])]
        equal(row["candidate_count"], candidate_count, f"{context} run {index} candidate count")
        if candidate_count:
            equal(row["candidate_status"], "candidate-present", f"{context} run {index} candidate status")
            equal(result["status"], "bug_found", f"{context} candidate backend status")
            candidate_rows += 1
        else:
            equal(row["candidate_status"], "no-candidate", f"{context} run {index} no-candidate status")
            require(result["status"] != "bug_found", f"{context} bug_found row has no candidate")
    equal(candidate_rows, 1, f"{context} candidate-bearing row count")
    return len(scheduler_runs) - candidate_rows


def relative_projection_path(source_parent, source_path, destination_parent):
    target = (source_parent / source_path).resolve()
    return os.path.relpath(target, destination_parent.resolve())


def projected_confirmation_criterion(report_path, confirmation_path, criterion):
    equal(criterion["verdict"], "satisfied", "report criterion projected to confirmation")
    require(criterion["evidence"], "report criterion projected without evidence")
    require(criterion["note"].strip(), "report criterion projected without a note")
    evidence = sorted(
        {
            relative_projection_path(
                report_path.parent,
                reference["path"],
                confirmation_path.parent,
            )
            for reference in criterion["evidence"]
        }
    )
    return {
        "verdict": "satisfied",
        "evidence": evidence,
        "note": criterion["note"],
    }


def verify_confirmation(
    confirmation,
    confirmation_path,
    report_path,
    generated_review,
    frozen,
    expected,
    context,
):
    equal(confirmation["schema_version"], 2, f"{context} confirmation schema")
    equal(len(confirmation["confirmations"]), 1, f"{context} confirmation count")
    row = confirmation["confirmations"][0]
    binding = generated_review["binding"]
    criteria = generated_review["criteria"]
    original_component_review = {
        "input_preconditions": projected_confirmation_criterion(
            report_path,
            confirmation_path,
            criteria["input_preconditions"],
        ),
        "fixed_original_constraints": projected_confirmation_criterion(
            report_path,
            confirmation_path,
            criteria["fixed_target_constraints"],
        ),
        "specified_property_violation": projected_confirmation_criterion(
            report_path,
            confirmation_path,
            criteria["specified_property_violation"],
        ),
    }
    spec_path = (report_path.parent / generated_review["review_spec"]["path"]).resolve()
    expected_row = {
        "run_id": binding["run_id"],
        "target_id": binding["target_id"],
        "root_cause_id": expected["root"],
        "scope": "original-component",
        "evidence_origin": "backend-execution",
        "original_component_review": original_component_review,
        "evidence": [
            os.path.relpath(report_path.resolve(), confirmation_path.parent.resolve()),
            os.path.relpath(spec_path, confirmation_path.parent.resolve()),
        ],
        "note": "Automated review validated the fixed candidate contract and cause binding.",
    }
    equal(row, expected_row, f"{context} exact confirmation projection")
    for field in ("run_id", "target_id"):
        equal(row[field], frozen[field], f"{context} frozen confirmation {field}")


def verify_evaluation(evaluation, plan, outcome, frozen, expected, context):
    frozen_evaluation = frozen["evaluation"]
    frozen_review = frozen["review"]
    equal(evaluation["schema_version"], 2, f"{context} evaluator schema")
    equal(evaluation["plan_id"], plan["plan_id"], f"{context} evaluator plan id")
    equal(evaluation["outcome_id"], outcome["outcome_id"], f"{context} evaluator outcome id")
    equal(evaluation["strategy"], plan["strategy"], f"{context} evaluator strategy")
    equal(evaluation["reviewed_confirmation_count"], 1, f"{context} reviewed confirmation count")
    equal(evaluation["confirmed_original_component_defect_count"], 1, f"{context} component count")
    equal(evaluation["confirmed_project_defect_count"], 0, f"{context} project count")
    equal(
        evaluation["confirmed_original_component_root_causes"],
        [expected["root"]],
        f"{context} evaluator root causes",
    )
    equal(evaluation["confirmed_project_root_causes"], [], f"{context} evaluator project roots")
    equal(len(evaluation["original_component_detection_curve"]), 1, f"{context} component curve size")
    curve = evaluation["original_component_detection_curve"][0]
    frozen_time = frozen_review["completion_time_upper_bound_seconds"]
    for field in ("run_id", "target_id"):
        equal(curve[field], frozen_review[field], f"{context} curve {field}")
    equal(curve["root_cause_id"], expected["root"], f"{context} curve root")
    equal(curve["observed_by_seconds"], frozen_time, f"{context} curve time")
    equal(curve["cumulative_confirmed_original_component_defects"], 1, f"{context} curve cumulative count")
    equal(
        evaluation["first_confirmed_original_component_defect_observed_by_seconds"],
        frozen_time,
        f"{context} first component time",
    )
    equal(evaluation["first_confirmed_defect_observed_by_seconds"], None, f"{context} first project time")

    if frozen_evaluation is not None:
        equal(set(evaluation), set(frozen_evaluation), f"{context} frozen evaluator fields")
        equal(frozen_evaluation["schema_version"], 2, f"{context} frozen evaluator schema")
        semantic_fields = set(frozen_evaluation) - EVALUATOR_NONSEMANTIC_FIELDS - {"schema_version"}
        for field in sorted(semantic_fields):
            equal(evaluation[field], frozen_evaluation[field], f"{context} frozen evaluator {field}")

    expected_statuses = Counter(
        run["result"]["status"] for run in outcome["scheduler"]["runs"] if run["result"] is not None
    )
    for status, count in expected_statuses.items():
        equal(evaluation["status_counts"].get(status), count, f"{context} status count {status}")
    equal(sum(evaluation["status_counts"].values()), len(outcome["scheduler"]["runs"]), f"{context} total statuses")


def verify_case(case, expected):
    directory = RESULTS / case
    bundle_path = directory / "bundle-index.json"
    bundle = load(bundle_path)
    equal(bundle["schema_version"], 1, f"{case} bundle schema")
    equal(bundle["kind"], "backend-review-bundle", f"{case} bundle kind")
    equal(len(bundle["review_specs"]), 1, f"{case} review spec count")
    for reference in bundle["review_specs"]:
        resolve_reference(bundle_path, reference)
    request_path = resolve_reference(bundle_path, bundle["review_request"])
    report_path = resolve_reference(bundle_path, bundle["review_report"])
    equal(report_path, (directory / "review-report.json").resolve(), f"{case} report path")
    request = load(request_path)
    report = load(report_path)
    verify_report_bindings(bundle_path, bundle, request_path, request, report_path, report)
    frozen_pairs = load_frozen_pairs(case, expected)

    equal(report["status"], "complete", f"{case} report status")
    require(report["raw_values_persisted"] is False, f"{case} reports raw values persisted")
    equal(
        report["candidate_inventory"],
        {
            "outcome_candidate_count": expected["candidates"],
            "matched_candidate_count": expected["candidates"],
            "unmatched_candidate_count": 0,
            "candidate_error_count": 0,
            "review_pair_count": expected["candidates"],
            "terminal_review_pair_count": expected["candidates"],
            "complete": True,
        },
        f"{case} candidate inventory",
    )
    equal(len(report["executions"]), expected["executions"], f"{case} execution row count")
    equal(
        report["summary"],
        {
            "validated": expected["candidates"],
            "rejected": 0,
            "unresolved": 0,
            "review_error": 0,
            "unreviewed_candidates": 0,
            "attributed_validated": expected["candidates"],
            "unique_validated_root_causes": 1,
        },
        f"{case} review summary",
    )

    request_by_id = keyed(request["executions"], lambda row: row["execution_id"], f"{case} request execution")
    reviews_by_id = keyed(report["reviews"], lambda row: row["binding"]["execution_id"], f"{case} review execution")
    report_rows_by_id = defaultdict(list)
    for row in report["executions"]:
        report_rows_by_id[row["execution_id"]].append(row)
    bundle_by_id = keyed(bundle["execution_evaluations"], lambda row: row["execution_id"], f"{case} bundle execution")
    campaign = bundle["campaign_summary"]
    campaign_by_id = keyed(campaign["by_execution"], lambda row: row["execution_id"], f"{case} campaign execution")
    execution_ids = set(request_by_id)
    equal(set(reviews_by_id), execution_ids, f"{case} review execution inventory")
    equal(set(report_rows_by_id), execution_ids, f"{case} report-row execution inventory")
    equal(set(bundle_by_id), execution_ids, f"{case} evaluator execution inventory")
    equal(set(campaign_by_id), execution_ids, f"{case} campaign execution inventory")
    equal(len(execution_ids), expected["pairs"], f"{case} execution pair count")

    expected_files = {bundle_path.resolve(), report_path}
    consumed_frozen = set()
    noncandidate_rows = 0
    for execution_id in sorted(execution_ids):
        context = f"{case} {execution_id}"
        request_execution = request_by_id[execution_id]
        campaign_row = campaign_by_id[execution_id]
        equal(
            request_execution["campaign_coordinates"],
            campaign_row["campaign_coordinates"],
            f"{context} campaign coordinates",
        )
        coordinates = coordinate_key(campaign_row["campaign_coordinates"])
        require(coordinates in frozen_pairs, f"{context} has no frozen pair at {coordinates!r}")
        require(coordinates not in consumed_frozen, f"{context} reuses frozen pair {coordinates!r}")
        consumed_frozen.add(coordinates)
        frozen = frozen_pairs[coordinates]

        plan_path = resolve_reference(request_path, request_execution["plan"])
        outcome_path = resolve_reference(request_path, request_execution["outcome"])
        plan = load(plan_path)
        outcome = load(outcome_path)
        frozen_review = frozen["review"]
        for name, reference in (("plan", request_execution["plan"]), ("outcome", request_execution["outcome"])):
            equal(reference["sha256"], frozen_review[f"{name}_sha256"], f"{context} frozen {name} hash")

        generated_review = reviews_by_id[execution_id]
        compare_frozen_review(case, generated_review, frozen_review, expected, context)
        noncandidate_rows += verify_outcome_rows(
            execution_id,
            outcome,
            report_rows_by_id[execution_id],
            context,
        )
        binding = generated_review["binding"]
        candidate_row = next(
            row
            for row in report_rows_by_id[execution_id]
            if row["plan_index"] == binding["plan_index"]
        )
        for field in ("run_id", "target_id"):
            equal(candidate_row[field], binding[field], f"{context} candidate row {field}")
        equal(candidate_row["candidate_status"], "candidate-present", f"{context} candidate row status")

        bundle_execution = bundle_by_id[execution_id]
        confirmation_path = resolve_reference(bundle_path, bundle_execution["confirmation"])
        evaluation_path = resolve_reference(bundle_path, bundle_execution["evaluator_output"])
        expected_files.update((confirmation_path, evaluation_path))
        verify_confirmation(
            load(confirmation_path),
            confirmation_path,
            report_path,
            generated_review,
            frozen_review,
            expected,
            context,
        )
        verify_evaluation(load(evaluation_path), plan, outcome, frozen, expected, context)
        equal(
            campaign_row["validated_attributed_root_cause_ids"],
            [expected["root"]],
            f"{context} campaign roots",
        )

    equal(consumed_frozen, set(frozen_pairs), f"{case} consumed frozen pairs")
    equal(noncandidate_rows, expected["executions"] - expected["candidates"], f"{case} non-candidate rows")
    equal(campaign["pair_count"], expected["pairs"], f"{case} campaign pair count")
    equal(campaign["unique_validated_root_cause_ids"], [expected["root"]], f"{case} deduplicated roots")
    equal(campaign["unique_validated_root_cause_count"], 1, f"{case} deduplicated root count")

    actual_files = {path.resolve() for path in directory.rglob("*") if path.is_file()}
    equal(actual_files, expected_files, f"{case} result file inventory")
    forbidden_exact_values, forbidden_substrings = candidate_value_guard(report_path, report)
    for path in sorted(actual_files):
        equal(path.suffix, ".json", f"{case} result file type for {path}")
        walk_for_raw_values(
            load(path),
            path,
            forbidden_exact_values,
            forbidden_substrings,
        )

    return {
        "case": case,
        "pairs": expected["pairs"],
        "execution_rows": expected["executions"],
        "validated": expected["candidates"],
        "noncandidate_rows": noncandidate_rows,
        "unique_root_causes": 1,
    }


def main():
    global EVIDENCE
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--require-local-evidence",
        action="store_true",
        help="also require ignored raw evidence, the preserved executable, and the recorded "
        "engine source snapshot",
    )
    arguments = parser.parse_args()
    EVIDENCE = Evidence(arguments.require_local_evidence)
    verify_semanticize_ordering()
    verify_raw_value_guard()
    verify_provenance_negative_checks()
    cases = [verify_case(case, expected) for case, expected in EXPECTED.items()]
    totals = {
        "pairs": sum(row["pairs"] for row in cases),
        "execution_rows": sum(row["execution_rows"] for row in cases),
        "validated": sum(row["validated"] for row in cases),
        "noncandidate_rows": sum(row["noncandidate_rows"] for row in cases),
    }
    print(
        json.dumps(
            {
                "status": "pass",
                "mode": EVIDENCE.mode,
                "local_references_skipped": len(EVIDENCE.skipped),
                "cases": cases,
                "totals": totals,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
