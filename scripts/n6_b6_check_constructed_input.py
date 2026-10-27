#!/usr/bin/env python3
"""Check a constructed input with the unchanged N6-B5 Mac-side functions.

The input is generated separately. This wrapper compiles the recorded main
under the mounted cache, checks its R1CS hash, and calls the existing honest
witness, Rust, and snarkjs validation function without changing its rules.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import time
from pathlib import Path
from unittest.mock import patch

import n6_b5_docker_base_inputs as b5


ROOT = Path(__file__).resolve().parents[1]
S_STATE = ROOT / "runs/n6-b5-2026-10-17.noindex/s-nested-execute.noindex/state.json"
A_STATE = ROOT / "runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/state.json"
B_STAGE_ROOT = ROOT / "runs/n6-b6-2026-10-18.noindex/batch1x-prep.noindex/stages"
B_STAGES = ("pilot-v2.2", "pilot-v1", "full-v2.2", "full-v1")
MOUNT = Path("/Volumes/zkfdo-jcache")


def check_heavy_idle() -> None:
    state_paths = (("S rerun", S_STATE), ("A J", A_STATE)) + tuple(
        (f"B J {stage}", B_STAGE_ROOT / stage / "state.json") for stage in B_STAGES)
    for name, state_path in state_paths:
        if not state_path.is_file():
            continue
        status = json.loads(state_path.read_text()).get("status")
        if status in {"running", "start_checking", "starting", "start_gate_running"}:
            raise RuntimeError(f"{name} active: {status}")


def child_resources() -> dict[str, int]:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "maxrss_kib": usage.ru_maxrss // (1024 if sys.platform == "darwin" else 1),
        "swaps": usage.ru_nswap,
    }


def validation_status(passed: bool, reason: str, child_audit: list[dict]) -> tuple[str, bool]:
    tool_reasons = {"node_unavailable", "honest_witness_timeout", "honest_witness_spawn_failed",
                    "rust_r1cs_timeout", "rust_r1cs_spawn_failed", "snarkjs_r1cs_timeout",
                    "snarkjs_r1cs_spawn_failed"}
    node_oom_exit = reason == "honest_witness_failed" and any(
        child["kind"] == "node_witness" and child["exit_code"] in (137, -9)
        for child in child_audit)
    return ("passed" if passed else "tool_blocked" if
            reason in tool_reasons or node_oom_exit else "failed"), node_oom_exit


def output_zero(witness: Path, output_count: int) -> bool | None:
    """Read only the public-output wires of a standard v2 .wtns file."""
    if output_count == 0:
        return None
    with witness.open("rb") as stream:
        if stream.read(4) != b"wtns" or int.from_bytes(stream.read(4), "little") != 2:
            return None
        sections = int.from_bytes(stream.read(4), "little")
        width = None
        values_offset = None
        values_length = None
        for _ in range(sections):
            kind = int.from_bytes(stream.read(4), "little")
            length = int.from_bytes(stream.read(8), "little")
            offset = stream.tell()
            if kind == 1:
                width = int.from_bytes(stream.read(4), "little")
            elif kind == 2:
                values_offset, values_length = offset, length
            stream.seek(offset + length)
        if not width or values_offset is None or values_length is None:
            return None
        if values_length < (output_count + 1) * width:
            return None
        stream.seek(values_offset + width)  # wire 0 is the constant one
        return all(not any(stream.read(width)) for _ in range(output_count))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("A", "B"), required=True)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, default=MOUNT / "n6-b6-constructed")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--r1cs-map", type=Path)
    parser.add_argument("--compile-timeout-seconds", type=float, default=3600)
    parser.add_argument("--validation-timeout-seconds", type=float, default=3600)
    parser.add_argument("--attempt-label", default="")
    args = parser.parse_args()

    if not os.path.ismount(MOUNT):
        raise SystemExit("/Volumes/zkfdo-jcache is not a mount point")
    cache_root = args.cache_root.resolve()
    if not cache_root.is_relative_to(MOUNT.resolve()):
        raise SystemExit("compile cache must be under /Volumes/zkfdo-jcache")
    check_heavy_idle()

    manifest = args.manifest or (b5.DEFAULT_B_MANIFEST if args.scope == "B" else b5.DEFAULT_A_MANIFEST)
    reference_path = args.r1cs_map or (b5.DEFAULT_B_R1CS if args.scope == "B" else b5.DEFAULT_A_R1CS)
    rows = json.loads(manifest.read_text())["rows"]
    selected = [row for row in rows if row["identifier"] == args.identifier]
    if len(selected) != 1:
        raise SystemExit("identifier not unique in recorded manifest")
    row = selected[0]
    expected = b5.reference_hashes(reference_path, args.scope).get(args.identifier, {})
    if expected.get("status") != "verified" or not b5.HEX64.fullmatch(expected.get("r1cs_sha256") or ""):
        raise SystemExit("recorded R1CS hash unavailable")

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    folder = output_root / args.identifier
    folder.mkdir(parents=True, exist_ok=True)
    cache = cache_root / args.identifier
    cache.mkdir(parents=True, exist_ok=True)
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise SystemExit("constructed input missing")
    if args.attempt_label and (not args.attempt_label.isascii() or
                               not all(character.isalnum() or character in "-_" for character in args.attempt_label)):
        raise SystemExit("attempt label must be ASCII letters, digits, hyphen, or underscore")
    suffix = f"-{args.attempt_label}" if args.attempt_label else ""
    record_path = folder / f"check{suffix}.json"
    claim_path = folder / f"check{suffix}.claim"
    validation_path = folder / f"validation{suffix}"
    if record_path.exists() or claim_path.exists() or validation_path.exists():
        raise SystemExit("existing constructed check attempt cannot be overwritten")
    claim_path.mkdir(exist_ok=False)
    record = {
        "schema": "n6-b6-constructed-check-v1",
        "scope": args.scope,
        "identifier": args.identifier,
        "manifest_sha256": b5.base.sha256(manifest),
        "r1cs_map_sha256": b5.base.sha256(reference_path),
        "input_path": str(input_path),
        "input_sha256": b5.base.sha256(input_path),
        "expected_r1cs_sha256": expected["r1cs_sha256"],
        "node_options": os.environ.get("NODE_OPTIONS", ""),
        "status": "not_started",
    }
    started = time.monotonic()
    try:
        check_heavy_idle()
        if b5.base.sha256(b5.base.CIRCOM) != b5.base.CIRCOM_SHA256:
            raise RuntimeError("fixed Circom binary changed")
        compile_resources_before = child_resources()
        artifacts, compile_record = b5.base.compile_entrypoint(
            row, cache, args.compile_timeout_seconds)
        record["compile_children_resources_before"] = compile_resources_before
        record["compile_children_resources_after"] = child_resources()
        record["compile"] = compile_record
        record["r1cs_sha256_match"] = compile_record["r1cs_sha256"] == expected["r1cs_sha256"]
        if not record["r1cs_sha256_match"]:
            raise RuntimeError("B/A recorded R1CS hash mismatch")
        shape = b5.base.read_r1cs_shape(artifacts["r1cs"])
        declarations = b5.base.main_input_declarations(
            b5.base.workspace_path(row["entrypoint_absolute"]),
            b5.base.workspace_path(row["project_root"]),
            [b5.base.workspace_path(path) for path in row["preflight_library_paths"]],
        )
        signals = b5.base.main_input_names(artifacts["sym"], declarations)
        keys = set(b5.base.input_keys(signals))
        record["main_input_count"] = len(keys)
        record["main_input_wire_count"] = len(signals)
        record["public_output_count"] = shape["outputs"]

        check_heavy_idle()
        checker = b5.base.checker_binary(cache)
        snarkjs_name = shutil.which("snarkjs")
        if snarkjs_name is None:
            raise RuntimeError("snarkjs unavailable")
        snarkjs = Path(snarkjs_name).resolve()
        record["rust_checker_sha256"] = b5.base.sha256(checker)
        record["snarkjs_sha256"] = b5.base.sha256(snarkjs)

        check_heavy_idle()
        child_audit = []
        original_run_quiet = b5.base.run_quiet

        def audited_run_quiet(command, timeout, **kwargs):
            kind = ("node_witness" if command[0] == shutil.which("node") else
                    "rust_r1cs" if command[0] == str(checker) else
                    "snarkjs_r1cs" if command[0] == str(snarkjs) else "other")
            before = child_resources()
            result = original_run_quiet(command, timeout, **kwargs)
            after = child_resources()
            child_audit.append({
                "kind": kind, "exit_code": result[0], "seconds": result[1],
                "disposition": result[2],
                "children_maxrss_before_kib": before["maxrss_kib"],
                "children_maxrss_after_kib": after["maxrss_kib"],
                "children_swaps_before": before["swaps"],
                "children_swaps_after": after["swaps"],
            })
            return result

        with patch.object(b5.base, "run_quiet", audited_run_quiet):
            passed, reason, details = b5.base.validate_input(
                input_path, keys, artifacts, checker, snarkjs,
                validation_path, args.validation_timeout_seconds)
        record["child_audit"] = child_audit
        record["validation_reason"] = reason
        status, node_oom_exit = validation_status(passed, reason, child_audit)
        record["node_oom_exit_suspected"] = node_oom_exit
        record["status"] = status
        if passed:
            record["honest_witness_sha256"] = details["witness_sha256"]
            record["validation_seconds"] = {
                key: details[key] for key in ("witness_seconds", "rust_seconds", "snarkjs_seconds")}
            try:
                record["public_outputs_all_zero"] = output_zero(
                    Path(details["witness_path"]), shape["outputs"])
            except (OSError, ValueError):
                record["public_outputs_all_zero"] = None
    except Exception as error:
        reason = str(error)
        record["status"] = "tool_blocked" if (
            isinstance(error, (OSError, TimeoutError)) or
            "timeout" in reason or "unavailable" in reason or " active: " in reason
        ) else "failed"
        record["error_class"] = type(error).__name__
        record["reason"] = reason
    finally:
        record["wall_seconds"] = time.monotonic() - started
        with record_path.open("x", encoding="utf-8") as output:
            json.dump(record, output, indent=2, ensure_ascii=False, sort_keys=True)
            output.write("\n")
    print(json.dumps({key: record.get(key) for key in
                      ("identifier", "status", "validation_reason", "reason", "r1cs_sha256_match",
                       "public_outputs_all_zero", "wall_seconds")}, sort_keys=True))
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
