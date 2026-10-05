#!/usr/bin/env python3
"""Audit the executables recorded by every selected C-03 after-v4 call.

The audit reads JSON metadata and hashes executable files.  It does not open
Circom sources, compiler artifacts, candidates, or witnesses.  A record is
created only after the fixed active denominator is complete and every command
uses the stage-specific path policy documented below.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGES = {
    "compile": ("compile", "compile-call"),
    "discover": ("discovery", "discover-call"),
    "prepare": ("preparation", "prepare-call"),
    "plan": ("plan", "plan-call"),
}
TOOL_FLAGS = ("--circom-bin", "--zkfuzz-bin", "--circomspect-bin")
FORBIDDEN_ZKFUZZ = "/nonexistent/c02-zkfuzz-forbidden"
FORBIDDEN_ANALYZER = "/nonexistent/c02-analyzer-forbidden"


class ProvenanceError(ValueError):
    """A fail-closed provenance audit failure with machine-readable causes."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(json.dumps(errors[:20], ensure_ascii=False))


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def reference(path, repository_root=ROOT):
    path = Path(path).resolve()
    try:
        display = path.relative_to(Path(repository_root).resolve()).as_posix()
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": digest(path)}


def measurement_id(repository, entrypoint_key):
    value = repository.lower() + "\x00" + entrypoint_key
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _load(path, errors, code):
    path = Path(path)
    if not path.is_file():
        errors.append({"code": code, "path": str(path)})
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        errors.append({"code": code, "path": str(path), "reason": type(error).__name__})
        return None
    if not isinstance(value, dict):
        errors.append({"code": code, "path": str(path), "reason": "object_required"})
        return None
    return value


def _resolve_ref(ref, repository_root, errors, context):
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str):
        errors.append({"code": "invalid_reference", "path": context})
        return None
    path = Path(ref["path"])
    path = path if path.is_absolute() else Path(repository_root) / path
    path = path.resolve()
    if not path.is_file():
        errors.append({"code": "referenced_file_missing", "path": context, "referenced_path": str(path)})
        return None
    if digest(path) != ref["sha256"]:
        errors.append({"code": "reference_hash_mismatch", "path": context, "referenced_path": str(path)})
        return None
    return path


def _flag_values(argv, errors, context):
    values = {}
    for index, argument in enumerate(argv):
        if not isinstance(argument, str) or not argument.startswith("--") or not argument.endswith("-bin"):
            continue
        if argument in values:
            errors.append({"code": "duplicate_tool_argument", "path": context, "argument": argument})
            continue
        if index + 1 >= len(argv) or not isinstance(argv[index + 1], str):
            errors.append({"code": "tool_argument_value_missing", "path": context, "argument": argument})
            continue
        values[argument] = argv[index + 1]
    return values


def _canonical_path(value):
    return str(Path(value).resolve()) if isinstance(value, str) else value


def _metadata_ref_path(ref, repository_root):
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        return None
    path = Path(ref["path"])
    return (path if path.is_absolute() else Path(repository_root) / path).resolve()


def _clean_absolute_path(value, expected):
    if not isinstance(value, str):
        return False
    path = Path(value)
    return path.is_absolute() and ".." not in path.parts and path.resolve() == Path(expected).resolve()


def _paths_within(values, roots):
    roots = [Path(root).resolve() for root in roots]
    for value in values:
        if not isinstance(value, str) or not Path(value).is_absolute() or ".." in Path(value).parts:
            return False
        resolved = Path(value).resolve()
        if not any(resolved.is_relative_to(root) for root in roots):
            return False
    return True


def _validate_data_argv(stage, argv, *, result, entry, checkout, active_directory,
                        repository_root, errors, context):
    """Match the complete fixed argv, including all source and output paths."""
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return False
    checkout = Path(checkout).resolve()
    active_directory = Path(active_directory).resolve()
    entry_path = Path(entry.get("path", "")).resolve()
    source_path = entry.get("source_path")
    kind = entry.get("kind")
    recovery_repositories = active_directory.parents[2] / "repositories"
    if not checkout.is_relative_to(recovery_repositories) or checkout.name != "clone":
        errors.append({"code": "recovery_checkout_contract_mismatch", "path": context})
    if kind == "source_main":
        relative = Path(source_path) if isinstance(source_path, str) else None
        valid_entry = (relative is not None and not relative.is_absolute() and ".." not in relative.parts
                       and entry_path == (checkout / relative).resolve() and entry_path.is_relative_to(checkout))
        project = checkout
        allowed_library_roots = [checkout]
    elif kind == "config_generated":
        generated = checkout.parent / "config-generated-after"
        metadata = entry.get("metadata")
        metadata_path = Path(metadata.get("path", "")).resolve() if isinstance(metadata, dict) else None
        valid_entry = (entry_path.is_relative_to(generated) and entry_path.parent == generated
                       and metadata_path == entry_path)
        project = checkout.parent
        allowed_library_roots = [checkout, generated]
    else:
        valid_entry = False
        project = checkout
        allowed_library_roots = [checkout]
    if not valid_entry:
        errors.append({"code": "active_entrypoint_path_contract_mismatch", "path": context, "kind": kind})
    libraries = result.get("library_paths")
    if (not isinstance(libraries, list) or not all(isinstance(item, str) for item in libraries)
            or len(libraries) != len(set(libraries)) or not _paths_within(libraries, allowed_library_roots)):
        errors.append({"code": "active_library_path_contract_mismatch", "path": context})
        libraries = libraries if isinstance(libraries, list) and all(isinstance(item, str) for item in libraries) else []

    executable = argv[0] if argv else ""
    if stage == "compile":
        expected = [executable, str(entry_path), "--r1cs", "-o", str(active_directory / "original")]
        expected.extend(item for library in libraries for item in ("-l", library))
    elif stage == "discover":
        expected = [executable, "targets", "--project", str(project), "--entrypoint", str(entry_path),
                    "--output", str(active_directory / "discovery"), "--circom-bin",
                    str((Path(repository_root) / "runs/c02-corpus-2026-10-02/tools/circom").resolve()),
                    "--compile-timeout-seconds", "60"]
        expected.extend(item for library in libraries for item in ("--library-path", library))
    elif stage == "prepare":
        manifest = active_directory / "manifest.json"
        if _metadata_ref_path((result.get("preparation") or {}).get("manifest"), repository_root) != manifest:
            errors.append({"code": "active_manifest_reference_mismatch", "path": context})
        expected = [executable, "experiment", "prepare", "--manifest", str(manifest),
                    "--output", str(active_directory / "prepared"), "--strategy", "small-first",
                    "--circom-bin", str((Path(repository_root) / "runs/c02-corpus-2026-10-02/tools/circom").resolve()),
                    "--zkfuzz-bin", FORBIDDEN_ZKFUZZ, "--circomspect-bin", FORBIDDEN_ANALYZER,
                    "--tool-timeout-seconds", "60"]
    else:
        prepared = _metadata_ref_path((result.get("preparation") or {}).get("report"), repository_root)
        prepared_root = active_directory / "prepared"
        if (prepared is None or prepared.name != "prepared.json" or not prepared.is_relative_to(prepared_root)
                or prepared.parent == prepared_root):
            errors.append({"code": "active_prepared_reference_mismatch", "path": context})
            prepared = prepared_root / "invalid-prepared-reference/prepared.json"
        plan_output = active_directory / "plan.json"
        plan_ref = _metadata_ref_path((result.get("plan") or {}).get("report"), repository_root)
        if plan_ref is not None and plan_ref != plan_output:
            errors.append({"code": "active_plan_reference_mismatch", "path": context})
        expected = [executable, "experiment", "plan", "--prepared", str(prepared),
                    "--strategy", "small-first", "--config", str(Path(repository_root) / "configs/static-ranking.json"),
                    "--output", str(plan_output)]
    path_positions = [index for index, value in enumerate(expected) if index and value.startswith("/")]
    exact = len(argv) == len(expected)
    for index, value in enumerate(expected):
        if index >= len(argv):
            exact = False
        elif index in path_positions:
            exact &= _clean_absolute_path(argv[index], value)
        else:
            exact &= argv[index] == value
    if not exact:
        errors.append({"code": "active_data_path_or_argument_mismatch", "path": context, "stage": stage})
    return exact and valid_entry


def _capture_expected(stage, result):
    capture = result.get(STAGES[stage][0])
    capture = capture if isinstance(capture, dict) else {}
    if stage in {"compile", "discover"}:
        return isinstance(result.get("source_sha256"), str) and bool(result["source_sha256"])
    markers = ("stdout", "stderr", "started_at", "finished_at", "cap_seconds", "exit_code", "elapsed_seconds")
    if any(key in capture for key in markers):
        return True
    return stage == "plan" and capture.get("status") not in {None, "not_started"}


def _capture_matches(stage, result, invocation, errors, context):
    capture = result.get(STAGES[stage][0])
    if not isinstance(capture, dict):
        errors.append({"code": "result_stage_missing", "path": context, "stage": stage})
        return
    # Preparation.status is deliberately normalized after the child exits.
    comparable = ("started_at", "finished_at", "cap_seconds", "exit_code", "process_started",
                  "elapsed_seconds", "stdout", "stderr", "post_exit_cleanup_seconds",
                  "post_exit_cleanup_signaled_pids", "cleanup_signaled_pids")
    for key in comparable:
        if key in capture and capture.get(key) != invocation.get(key):
            errors.append({"code": "invocation_result_capture_mismatch", "path": context,
                           "stage": stage, "field": key})


def _validate_argv(stage, argv, paths, errors, context):
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        errors.append({"code": "invocation_argv_invalid", "path": context, "stage": stage})
        return {}
    recovery_circom = str(paths["recovery_circom"])
    actual_circom = str(paths["actual_circom"])
    actual_zkfdo = str(paths["actual_zkfdo"])
    if stage == "compile":
        expected_head = [recovery_circom]
        expected_flags = {}
        shape_ok = "--r1cs" in argv
    elif stage == "discover":
        expected_head = [actual_zkfdo, "targets"]
        expected_flags = {"--circom-bin": actual_circom}
        shape_ok = True
    elif stage == "prepare":
        expected_head = [actual_zkfdo, "experiment", "prepare"]
        expected_flags = {"--circom-bin": actual_circom, "--zkfuzz-bin": FORBIDDEN_ZKFUZZ,
                          "--circomspect-bin": FORBIDDEN_ANALYZER}
        shape_ok = True
    else:
        expected_head = [actual_zkfdo, "experiment", "plan"]
        expected_flags = {}
        shape_ok = True
    head_matches = (len(argv) >= len(expected_head)
                    and _canonical_path(argv[0]) == _canonical_path(expected_head[0])
                    and argv[1:len(expected_head)] == expected_head[1:])
    if not head_matches or not shape_ok:
        errors.append({"code": "stage_executable_or_subcommand_mismatch", "path": context,
                       "stage": stage, "observed_head": argv[:len(expected_head)]})
    flags = _flag_values(argv, errors, context)
    normalized_flags = {key: _canonical_path(value) for key, value in flags.items()}
    normalized_expected = {key: _canonical_path(value) for key, value in expected_flags.items()}
    if normalized_flags != normalized_expected:
        errors.append({"code": "stage_tool_argument_mismatch", "path": context, "stage": stage,
                       "observed": flags, "expected": expected_flags})
    known_tools = {_canonical_path(str(value)) for value in paths.values()}
    allowed_indices = {0}
    for flag in expected_flags:
        if flag in argv:
            allowed_indices.add(argv.index(flag) + 1)
    for index, argument in enumerate(argv):
        if _canonical_path(argument) in known_tools and index not in allowed_indices:
            errors.append({"code": "tool_path_in_unexpected_position", "path": context,
                           "stage": stage, "index": index, "tool_path": argument})
    return flags


def audit(run_dir, *, repository_root=ROOT):
    """Return a passed audit document or raise without creating an output."""
    run = Path(run_dir).resolve()
    repository_root = Path(repository_root).resolve()
    errors = []
    selection_path = run / "final-measurement-selection.v4.json"
    inventory_path = run / "entrypoints-after.v4.json"
    measurement_lock_path = run / "measurement-lock.json"
    selection = _load(selection_path, errors, "selection_missing_or_invalid")
    inventory = _load(inventory_path, errors, "after_inventory_missing_or_invalid")
    measurement_lock = _load(measurement_lock_path, errors, "measurement_lock_missing_or_invalid")
    if errors:
        raise ProvenanceError(errors)
    if (selection.get("schema_version") != 4 or selection.get("active_after_directory") != "after-v4"
            or selection.get("all_after_entries_remeasured") is not True):
        errors.append({"code": "selection_policy_mismatch", "path": str(selection_path)})
    expected_inventory_ref = reference(inventory_path, repository_root)
    if selection.get("after_inventory_ref") != expected_inventory_ref:
        errors.append({"code": "selection_inventory_reference_mismatch", "path": str(selection_path)})
    census_path = _resolve_ref(selection.get("census_ref"), repository_root, errors,
                               str(selection_path) + ":census_ref")
    census = _load(census_path, errors, "census_missing_or_invalid") if census_path is not None else None
    census_rows = {}
    census_repository_rows = (census or {}).get("repositories")
    if not isinstance(census_repository_rows, list):
        errors.append({"code": "census_repository_list_invalid", "path": str(census_path)})
        census_repository_rows = []
    for row in census_repository_rows:
        if not isinstance(row, dict) or not isinstance(row.get("full_name"), str) or row["full_name"] in census_rows:
            errors.append({"code": "census_repository_identity_invalid", "path": str(census_path)})
            continue
        census_rows[row["full_name"]] = row

    recovery_circom = (run / "tools/circom").resolve()
    recovery_zkfdo = (run / "tools/zkfDO").resolve()
    actual_circom = (repository_root / "runs/c02-corpus-2026-10-02/tools/circom").resolve()
    actual_zkfdo = (repository_root / "runs/c02-corpus-2026-10-02/tools/zkfDO").resolve()
    c02_tool_lock_path = (repository_root / "runs/c02-corpus-2026-10-02/tool-lock.json").resolve()
    paths = {"recovery_circom": recovery_circom, "recovery_zkfdo": recovery_zkfdo,
             "actual_circom": actual_circom, "actual_zkfdo": actual_zkfdo}
    tool_refs = {}
    for name, path in paths.items():
        if not path.is_file():
            errors.append({"code": "tool_file_missing", "path": str(path), "tool": name})
        else:
            tool_refs[name] = reference(path, repository_root)
    equivalence = {}
    for name in ("circom", "zkfDO"):
        recovery = tool_refs.get("recovery_" + ("zkfdo" if name == "zkfDO" else name))
        actual = tool_refs.get("actual_" + ("zkfdo" if name == "zkfDO" else name))
        equivalent = bool(recovery and actual and recovery["sha256"] == actual["sha256"])
        equivalence[name] = {"recovery_pin": recovery, "actual_c02_alias": actual,
                             "sha256_equal": equivalent}
        if not equivalent:
            errors.append({"code": "actual_alias_recovery_hash_mismatch", "path": name})
    c02_tool_lock = _load(c02_tool_lock_path, errors, "c02_tool_lock_missing_or_invalid")
    c02_pins = {}
    if c02_tool_lock is not None:
        rows = c02_tool_lock.get("tools")
        if not isinstance(rows, list):
            errors.append({"code": "c02_tool_lock_tool_list_invalid", "path": str(c02_tool_lock_path)})
            rows = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str) or not isinstance(row.get("sha256"), str):
                errors.append({"code": "c02_tool_lock_pin_invalid", "path": str(c02_tool_lock_path)})
                continue
            name = Path(row["path"]).name
            if name not in {"circom", "zkfDO"} or name in c02_pins:
                errors.append({"code": "c02_tool_lock_pin_invalid", "path": str(c02_tool_lock_path), "tool": name})
                continue
            c02_pins[name] = {"path": row["path"], "sha256": row["sha256"]}
        for name, ref_key, actual_path in (("circom", "actual_circom", actual_circom),
                                           ("zkfDO", "actual_zkfdo", actual_zkfdo)):
            pin = c02_pins.get(name)
            actual = tool_refs.get(ref_key)
            if (not pin or Path(pin["path"]).resolve() != actual_path or not actual
                    or pin["sha256"] != actual["sha256"]):
                errors.append({"code": "c02_tool_lock_actual_alias_mismatch", "path": str(c02_tool_lock_path),
                               "tool": name})
        if set(c02_pins) != {"circom", "zkfDO"}:
            errors.append({"code": "c02_tool_lock_pin_set_mismatch", "path": str(c02_tool_lock_path)})
        if c02_tool_lock.get("zkfuzz_executions") != 0:
            errors.append({"code": "c02_tool_lock_policy_mismatch", "path": str(c02_tool_lock_path)})
    sentinel_absence = {}
    for name, value in (("zkfuzz", FORBIDDEN_ZKFUZZ), ("circomspect", FORBIDDEN_ANALYZER)):
        exists = Path(value).exists()
        lexists = os.path.lexists(value)
        sentinel_absence[name] = {"path": value, "exists": exists, "lexists": lexists,
                                  "status": "absent" if not exists and not lexists else "present"}
        if exists or lexists:
            errors.append({"code": "forbidden_tool_sentinel_exists", "path": value, "tool": name})
    pinned = {}
    for ref in measurement_lock.get("compiler_tools", []):
        path = _resolve_ref(ref, repository_root, errors, str(measurement_lock_path) + ":compiler_tools")
        if path is not None:
            pinned[path.name] = ref
    for name, path in (("circom", recovery_circom), ("zkfDO", recovery_zkfdo)):
        if pinned.get(name) != tool_refs.get("recovery_" + ("zkfdo" if name == "zkfDO" else name)):
            errors.append({"code": "measurement_lock_recovery_tool_mismatch", "path": name})

    rows = inventory.get("repositories")
    if not isinstance(rows, list):
        errors.append({"code": "after_inventory_repository_list_missing", "path": str(inventory_path)})
        rows = []
    expected = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("full_name"), str) or not isinstance(row.get("entries"), list):
            errors.append({"code": "after_inventory_repository_invalid", "path": str(inventory_path)})
            continue
        for entry in row["entries"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or not isinstance(entry.get("kind"), str):
                errors.append({"code": "after_inventory_entry_invalid", "path": str(inventory_path),
                               "repository": row.get("full_name")})
                continue
            identifier = measurement_id(row["full_name"], entry["key"])
            if identifier in expected:
                errors.append({"code": "measurement_identifier_collision", "path": identifier})
                continue
            expected[identifier] = (row, entry)
    if inventory.get("known_entrypoint_count") != len(expected):
        errors.append({"code": "after_inventory_declared_count_mismatch", "path": str(inventory_path),
                       "declared": inventory.get("known_entrypoint_count"), "observed": len(expected)})

    measurements = run / "measurements"
    active_directories = {path.parent.name: path for path in measurements.glob("*/after-v4") if path.is_dir()}
    expected_ids = set(expected)
    incomplete = sorted(identifier for identifier, path in active_directories.items() if not (path / "result.json").is_file())
    missing = sorted(expected_ids - {identifier for identifier, path in active_directories.items()
                                     if (path / "result.json").is_file()})
    unexpected = sorted(set(active_directories) - expected_ids)
    if incomplete:
        errors.append({"code": "active_measurement_incomplete", "path": str(measurements), "count": len(incomplete),
                       "measurement_ids": incomplete[:20]})
    if missing:
        errors.append({"code": "active_result_missing", "path": str(measurements), "count": len(missing),
                       "measurement_ids": missing[:20]})
    if unexpected:
        errors.append({"code": "unexpected_active_measurement", "path": str(measurements), "count": len(unexpected),
                       "measurement_ids": unexpected[:20]})
    # Refuse before opening a moving, incomplete denominator.
    if incomplete or missing or unexpected:
        raise ProvenanceError(errors)

    result_records = []
    call_records = []
    coverage = {stage: Counter() for stage in STAGES}
    allowed_call_directories = {value[1] for value in STAGES.values()}
    for identifier in sorted(expected):
        repository, entry = expected[identifier]
        directory = measurements / identifier / "after-v4"
        result_path = directory / "result.json"
        result = _load(result_path, errors, "active_result_invalid")
        if result is None:
            continue
        identity = {"repository": repository["full_name"], "commit_sha": repository.get("commit_sha"),
                    "entrypoint_key": entry["key"], "entrypoint_kind": entry["kind"], "phase": "after"}
        for field, value in identity.items():
            if result.get(field) != value:
                errors.append({"code": "active_result_identity_mismatch", "path": str(result_path), "field": field})
        if result.get("physical_result_directory") not in (None, "after-v4"):
            errors.append({"code": "active_result_directory_marker_mismatch", "path": str(result_path)})
        census_repository = census_rows.get(repository["full_name"])
        checkout = None
        if (not isinstance(census_repository, dict) or census_repository.get("commit_sha") != repository.get("commit_sha")
                or not isinstance(census_repository.get("clone_path"), str)):
            errors.append({"code": "active_census_repository_mismatch", "path": str(result_path)})
        else:
            checkout_path = Path(census_repository["clone_path"])
            checkout = (checkout_path if checkout_path.is_absolute() else repository_root / checkout_path).resolve()
        result_records.append({"measurement_id": identifier, **identity,
                               "record": reference(result_path, repository_root)})
        for call_dir in directory.glob("*-call"):
            if call_dir.name not in allowed_call_directories:
                errors.append({"code": "unexpected_call_directory", "path": str(call_dir)})
            elif not (call_dir / "invocation.json").is_file():
                errors.append({"code": "call_invocation_record_missing", "path": str(call_dir)})
        for stage, (_, call_name) in STAGES.items():
            invocation_path = directory / call_name / "invocation.json"
            expected_call = _capture_expected(stage, result)
            observed_call = invocation_path.is_file()
            coverage[stage]["expected_invocations"] += int(expected_call)
            coverage[stage]["not_invoked_by_stage_flow"] += int(not expected_call)
            coverage[stage]["observed_invocations"] += int(observed_call)
            if expected_call and not observed_call:
                coverage[stage]["missing_expected_invocations"] += 1
                errors.append({"code": "expected_invocation_missing", "path": str(invocation_path), "stage": stage})
                continue
            if observed_call and not expected_call:
                coverage[stage]["unexpected_invocations"] += 1
                errors.append({"code": "unexpected_invocation_present", "path": str(invocation_path), "stage": stage})
            if not observed_call:
                continue
            invocation = _load(invocation_path, errors, "invocation_invalid")
            if invocation is None:
                continue
            _capture_matches(stage, result, invocation, errors, str(invocation_path))
            flags = _validate_argv(stage, invocation.get("argv"), paths, errors, str(invocation_path))
            data_ok = False
            if checkout is not None:
                data_ok = _validate_data_argv(stage, invocation.get("argv"), result=result, entry=entry,
                                              checkout=checkout, active_directory=directory,
                                              repository_root=repository_root, errors=errors,
                                              context=str(invocation_path))
            coverage[stage]["data_path_validated_invocations"] += int(data_ok)
            call_records.append({"measurement_id": identifier, "repository": repository["full_name"],
                                 "entrypoint_key": entry["key"], "stage": stage,
                                 "record": reference(invocation_path, repository_root),
                                 "executable_path": invocation.get("argv", [None])[0] if invocation.get("argv") else None,
                                 "tool_arguments": flags,
                                 "data_path_validation": "passed" if data_ok else "failed"})

    if errors:
        raise ProvenanceError(errors)
    stage_coverage = {}
    for stage, counts in coverage.items():
        stage_coverage[stage] = {key: counts.get(key, 0) for key in
                                 ("expected_invocations", "observed_invocations", "not_invoked_by_stage_flow",
                                  "missing_expected_invocations", "unexpected_invocations",
                                  "data_path_validated_invocations")}
        stage_coverage[stage]["status"] = "passed"
    return {
        "schema_version": 1,
        "task": "C-03 actual tool provenance",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "audit_scope": "metadata invocation argv and executable bytes; no circuit, artifact, candidate, or witness opened",
        "selection_ref": reference(selection_path, repository_root),
        "after_inventory_ref": reference(inventory_path, repository_root),
        "measurement_lock_ref": reference(measurement_lock_path, repository_root),
        "census_ref": reference(census_path, repository_root),
        "c02_tool_lock_ref": reference(c02_tool_lock_path, repository_root),
        "implementation_ref": reference(Path(__file__), repository_root),
        "coverage": {"expected_results": len(expected), "audited_results": len(result_records),
                     "unexpected_active_results": 0, "incomplete_active_results": 0,
                     "stages": stage_coverage},
        "tool_path_policy": {
            "compile_executable": str(recovery_circom),
            "structural_executable": str(actual_zkfdo),
            "structural_circom_argument": str(actual_circom),
            "recovery_zkfdo_pin_not_used_by_structural_calls": str(recovery_zkfdo),
            "cause": "measure_c03_corpus_v4 changed base.RUN but did not rebind base.legacy.RUN",
            "path_divergence_status": "distinct_paths_with_sha256_equivalent_bytes",
            "forbidden_nonexecuted_tool_arguments": {
                "zkfuzz": FORBIDDEN_ZKFUZZ, "circomspect": FORBIDDEN_ANALYZER},
        },
        "active_data_path_policy": {
            "status": "passed",
            "source_main": "inventory path must equal recovery checkout/source_path",
            "config_generated": "inventory and metadata path must identify a direct child of recovery config-generated-after",
            "outputs": "compile/discovery/prepare/plan outputs must remain below the matching after-v4 directory",
            "libraries": "exact result.library_paths sequence, confined to recovery checkout or generated-source directory",
            "verbs": "targets, experiment prepare, and experiment plan only",
        },
        "tools": {"references": tool_refs, "actual_alias_recovery_equivalence": equivalence,
                  "c02_tool_lock_pins": c02_pins,
                  "all_hashes_equivalent": all(row["sha256_equal"] for row in equivalence.values())},
        "sentinel_absence": {"status": "passed", "checked_at": datetime.now(timezone.utc).isoformat(),
                             "paths": sentinel_absence},
        "result_records": result_records,
        "call_records": call_records,
        "mismatches": [],
    }


def write_new(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.run_dir / "actual-tool-provenance.v4.json"
    try:
        document = audit(args.run_dir)
        write_new(output, document)
    except ProvenanceError as error:
        raise SystemExit("C-03 tool provenance audit refused output: " + str(error)) from None


if __name__ == "__main__":
    main()
