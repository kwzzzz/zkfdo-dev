#!/usr/bin/env python3
"""Check frozen N6-B sources against the pinned zkFuzz parser before campaign execution.

The control and B probes only inspect fixed lifecycle markers and stderr error codes.
All other process output, including any candidate output, is discarded with the temporary
working directory. No campaign spec is executed by this program.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-b2-2026-10-09.noindex"
QUEUE = ROOT / "runs/n6-a2b-2026-10-08.noindex/queue-b-v4.json"
QUEUE_SHA256 = "d39e821fd65cea1852ad6a20b88ab59e03a7c363be9022224221986716161600"
ZKFUZZ = Path("/Users/miiz/.cargo/bin/zkfuzz")
ZKFUZZ_SHA256 = "ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd"
ENGINE_SHA256 = "ff36c6db0a7475064c388a9bd0b0a1845863329f1fe2e2b40f06dec641fa9451"
MARKER = b"Gathering Trace/Side Constraints..."
MARKER_SOURCE = ROOT / ".external/zkFuzz/src/main.rs"
CONTROL = ROOT / "tests/fixtures/target_discovery/main.circom"
CAP_BYTES = 10 * 1024**3
MAX_SECONDS = 120.0
POLL_SECONDS = 0.05
MEMORY_SAMPLE_SECONDS = 1.0
ERROR_CODE = re.compile(rb"error\[([A-Za-z0-9_]+)\]")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


queue_runner = load_module("n6_b2_parser_queue_v42", ROOT / "scripts/run_n6_v4_2_queue.py")
engine = queue_runner.engine


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def spec_parser_identity(spec: dict[str, Any]) -> dict[str, Any]:
    """Fields that determine each parser source and command, regardless of seed."""
    return {key: spec[key] for key in (
        "source_snapshots", "targets", "pinned_files", "pinned_trees"
    )}


def identity_sha256(spec: dict[str, Any]) -> str:
    encoded = json.dumps(spec_parser_identity(spec), sort_keys=True,
                         separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def verified_plan() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if sha256(QUEUE) != QUEUE_SHA256:
        raise ValueError("frozen B queue hash changed")
    if sha256(ZKFUZZ) != ZKFUZZ_SHA256:
        raise ValueError("frozen zkFuzz hash changed")
    if sha256(ROOT / "scripts/run_policy_a_engine_v4.py") != ENGINE_SHA256:
        raise ValueError("frozen Policy-A engine v4 hash changed")
    frozen = queue_runner.load_queue(QUEUE)
    proof = queue_runner.load_preflight_rows(frozen)
    if frozen["branch"] != "B" or len(frozen["units"]) != 30 or len(proof) != 60:
        raise ValueError("B queue denominator changed")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for unit in frozen["units"]:
        for method in ("W", "S"):
            spec_path = queue_runner.spec_for(unit, method)
            spec = json.loads(spec_path.read_text())
            expected_method = "whole" if method == "W" else "split"
            if spec["method"] != expected_method:
                raise ValueError(f"method mismatch: {spec_path}")
            groups.setdefault((unit["identifier"], method), []).append({
                "unit_id": unit["unit_id"],
                "seed": unit["seed"],
                "spec_path": spec_path.relative_to(ROOT).as_posix(),
                "spec_sha256": sha256(spec_path),
                "identity_sha256": identity_sha256(spec),
                "spec": spec,
            })
    if len(groups) != 20:
        raise ValueError("expected 10 B targets with W and S specs")
    checks = []
    plan = []
    for (identifier, method), rows in groups.items():
        rows.sort(key=lambda row: row["seed"])
        if [row["seed"] for row in rows] != frozen["budget_policy"]["seeds"]:
            raise ValueError(f"seed set changed for {identifier}:{method}")
        if len({row["identity_sha256"] for row in rows}) != 1:
            raise ValueError(f"parser source or command differs across seeds: {identifier}:{method}")
        chosen = rows[0]
        spec = chosen["spec"]
        snapshots = {row["id"]: Path(row["path"]) for row in spec["source_snapshots"]}
        checks.append({
            "identifier": identifier, "method": method,
            "target_count": len(spec["targets"]),
            "seed_spec_sha256": [row["spec_sha256"] for row in rows],
            "parser_identity_sha256": chosen["identity_sha256"],
            "equal_across_three_seeds": True,
        })
        for target_index, target in enumerate(spec["targets"]):
            workspace = snapshots[target["source_snapshot_id"]]
            entrypoint = workspace / target["entrypoint_relative"]
            if not entrypoint.is_file() or sha256(entrypoint) != target["entrypoint_sha256"]:
                raise ValueError(f"entrypoint source changed: {identifier}:{method}:{target_index}")
            command = [arg.replace("{workspace}", str(workspace)).replace(
                "{entrypoint}", str(entrypoint)) for arg in target["command"]]
            if "{" in " ".join(command) or Path(command[0]) != ZKFUZZ:
                raise ValueError(f"unsupported parser command: {identifier}:{method}:{target_index}")
            plan.append({
                "identifier": identifier, "method": method,
                "unit_id": chosen["unit_id"], "representative_seed": chosen["seed"],
                "spec_path": chosen["spec_path"],
                "spec_sha256": chosen["spec_sha256"],
                "target_index": target_index, "target_id": target["target_id"],
                "entrypoint": str(entrypoint),
                "entrypoint_sha256": target["entrypoint_sha256"],
                "command": command,
            })
    if len(plan) != 3393:
        raise ValueError(f"B parser target denominator changed: {len(plan)}")
    proof_record = {
        "schema_version": 1,
        "created_at": now(),
        "queue": QUEUE.relative_to(ROOT).as_posix(),
        "queue_sha256": QUEUE_SHA256,
        "preflight_reuse": frozen["preflight_reuse"],
        "preflight_row_count": len(proof),
        "spec_count": 60,
        "group_count": len(groups),
        "representative_seed": frozen["budget_policy"]["seeds"][0],
        "representative_probe_count": len(plan),
        "source_command_equality": checks,
        "status": "passed",
    }
    return proof_record, plan


def scan_chunk(stream_name: str, old_tail: bytes, chunk: bytes,
               marker: bytes = MARKER) -> tuple[bytes, bool, bool, list[str]]:
    combined = old_tail + chunk
    marker_seen = marker in combined
    error_seen = stream_name == "stderr" and b"error[" in combined.lower()
    codes = ([item.decode("ascii") for item in ERROR_CODE.findall(combined)]
             if stream_name == "stderr" else [])
    return combined[-max(len(marker), 128):], marker_seen, error_seen, codes


def run_probe(command: list[str], *, max_seconds: float = MAX_SECONDS,
              memory_sampler: Callable[[int], dict[str, Any] | None] =
              engine.process_group_memory_bytes,
              temporary_root: Path = RUN) -> dict[str, Any]:
    """Run one parser check; never save or inspect raw output or generated files."""
    if max_seconds <= 0 or max_seconds > MAX_SECONDS:
        raise ValueError("parser check cap must be in (0, 120] seconds")
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="parser-probe-", dir=temporary_root) as temporary:
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=temporary, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        assert process.stdout is not None and process.stderr is not None
        descriptors = {process.stdout: "stdout", process.stderr: "stderr"}
        tails = {"stdout": b"", "stderr": b""}
        marker_seen = False
        error_seen = False
        codes: set[str] = set()
        termination = "unknown"
        peak_physical = 0
        next_memory_sample = started
        cleanup_permission_denied = False
        try:
            while True:
                elapsed = time.monotonic() - started
                if elapsed >= max_seconds:
                    termination = "time_limit"
                    break
                current = time.monotonic()
                if process.poll() is None and current >= next_memory_sample:
                    sample = memory_sampler(process.pid)
                    if sample is None:
                        if process.poll() is None:
                            termination = "monitor_failure"
                            break
                    else:
                        peak_physical = max(peak_physical,
                                            int(sample["physical_memory_bytes"]))
                        if peak_physical > CAP_BYTES:
                            termination = "memory_cap"
                            break
                    next_memory_sample = current + MEMORY_SAMPLE_SECONDS
                if process.poll() is not None:
                    # Drain the remaining pipe bytes to catch an error emitted just before exit.
                    timeout = 0.0
                else:
                    timeout = min(POLL_SECONDS, max_seconds - elapsed)
                if descriptors:
                    ready, _, _ = select.select(list(descriptors), [], [], timeout)
                    for descriptor in ready:
                        chunk = os.read(descriptor.fileno(), 65536)
                        if not chunk:
                            descriptors.pop(descriptor)
                            continue
                        name = "stdout" if descriptor is process.stdout else "stderr"
                        tails[name], marker, error, found_codes = scan_chunk(
                            name, tails[name], chunk)
                        marker_seen |= marker
                        error_seen |= error
                        codes.update(found_codes)
                if error_seen:
                    termination = "stderr_error"
                    break
                if marker_seen:
                    termination = "parse_marker"
                    break
                if process.poll() is not None and not descriptors:
                    termination = "natural_exit"
                    break
        finally:
            direct_child_exited = process.poll() is not None
            try:
                if not direct_child_exited or engine.v1.process_group_exists(process.pid):
                    engine.v1.kill_group(process.pid)
            except PermissionError:
                cleanup_permission_denied = True
                if process.poll() is None:
                    process.kill()
            process.wait(timeout=10)
            if not engine.v1.verify_group_empty(process.pid):
                raise RuntimeError("parser probe process group remained live")
            if direct_child_exited:
                # A fast P error can exit between the group-existence check and killpg.
                # A reaped direct child and an empty group still satisfy cleanup.
                cleanup_permission_denied = False
            process.stdout.close()
            process.stderr.close()
        elapsed = time.monotonic() - started
        p_codes = sorted(code for code in codes if code.startswith("P"))
        if cleanup_permission_denied:
            status = "cleanup_permission_denied"
        elif error_seen:
            status = "parser_error" if p_codes else "other_error"
        elif termination == "parse_marker":
            status = "accepted"
        elif termination == "monitor_failure":
            status = "resource_monitor_failure"
        elif termination == "memory_cap":
            status = "memory_cap"
        else:
            status = "parse_unconfirmed"
        return {
            "status": status,
            "error_codes": sorted(codes),
            "termination": termination,
            "elapsed_seconds": round(elapsed, 6),
            "exit_code": process.returncode,
            "peak_physical_memory_bytes": peak_physical,
            "process_group_empty": True,
            "temporary_workspace_deleted": True,
            "cleanup_permission_denied": cleanup_permission_denied,
        }


def calibration_record() -> dict[str, Any]:
    if sha256(ZKFUZZ) != ZKFUZZ_SHA256:
        raise ValueError("frozen zkFuzz hash changed")
    command = [str(ZKFUZZ), str(CONTROL), "--prime", "bn128", "--search_mode", "ga",
               "-l", str(CONTROL.parent)]
    result = run_probe(command, max_seconds=8.0)
    source_text = MARKER_SOURCE.read_text()
    marker_lines = [number for number, line in enumerate(source_text.splitlines(), 1)
                    if "Gathering Trace/Side Constraints..." in line]
    if len(marker_lines) != 1:
        raise ValueError("marker location in frozen zkFuzz source changed")
    return {
        "schema_version": 1,
        "created_at": now(),
        "zkfuzz_sha256": ZKFUZZ_SHA256,
        "control_source": CONTROL.relative_to(ROOT).as_posix(),
        "control_source_sha256": sha256(CONTROL),
        "marker": MARKER.decode("ascii"),
        "marker_source": MARKER_SOURCE.relative_to(ROOT).as_posix(),
        "marker_source_sha256": sha256(MARKER_SOURCE),
        "marker_source_line": marker_lines[0],
        "marker_meaning": "emitted after parse_project and type_analysis_user::analyse_project",
        "control": result,
        "status": "passed" if result["status"] == "accepted" else "failed",
    }


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_plan(plan: list[dict[str, Any]], output: Path, *, identifier: str | None,
             exclude_identifier: str | None, method: str | None, start_index: int,
             calibration: Path, proof: Path) -> int:
    calibration_record_data = json.loads(calibration.read_text())
    if (calibration_record_data.get("status") != "passed"
            or calibration_record_data.get("marker") != MARKER.decode("ascii")
            or calibration_record_data.get("zkfuzz_sha256") != ZKFUZZ_SHA256):
        raise ValueError("parser control marker has not been established")
    proof_data = json.loads(proof.read_text())
    if proof_data.get("status") != "passed" or proof_data.get("queue_sha256") != QUEUE_SHA256:
        raise ValueError("source and command equality proof is absent")
    chosen_all = [row for row in plan
                  if (identifier is None or row["identifier"] == identifier)
                  and (exclude_identifier is None or row["identifier"] != exclude_identifier)
                  and (method is None or row["method"] == method)]
    if start_index < 0 or start_index >= len(chosen_all):
        raise ValueError("start index is outside selected parser targets")
    chosen = chosen_all[start_index:]
    if not chosen:
        raise ValueError("no parser targets selected")
    if output.exists():
        raise FileExistsError(f"parser ledger already exists: {output}")
    append_jsonl(output, {
        "kind": "header", "created_at": now(),
        "queue_sha256": QUEUE_SHA256,
        "proof_sha256": sha256(proof),
        "calibration_sha256": sha256(calibration),
        "identifier_filter": identifier,
        "exclude_identifier_filter": exclude_identifier,
        "method_filter": method,
        "start_index": start_index,
        "original_selected_target_count": len(chosen_all),
        "selected_target_count": len(chosen),
        "max_seconds_per_target": MAX_SECONDS,
        "physical_cap_bytes": CAP_BYTES,
        "zkfuzz_sha256": ZKFUZZ_SHA256,
    })
    for index, target in enumerate(chosen, start_index):
        result = run_probe(target["command"])
        append_jsonl(output, {
            "kind": "target", "index": index,
            "identifier": target["identifier"],
            "method": target["method"],
            "unit_id": target["unit_id"],
            "representative_seed": target["representative_seed"],
            "spec_path": target["spec_path"],
            "spec_sha256": target["spec_sha256"],
            "target_index": target["target_index"],
            "target_id": target["target_id"],
            "entrypoint_sha256": target["entrypoint_sha256"],
            **result,
        })
        if result["status"] in {"resource_monitor_failure", "memory_cap", "other_error",
                                "cleanup_permission_denied"}:
            return 2
        if result["status"] == "parser_error" and result["error_codes"] != ["P1003"]:
            return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("verify", "calibrate", "probe"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identifier", help="limit probe action to one frozen B target")
    parser.add_argument("--exclude-identifier", help="exclude one already checked B target")
    parser.add_argument("--method", choices=("W", "S"), help="limit probe action to one method")
    parser.add_argument("--start-index", type=int, default=0,
                        help="zero-based index after identifier/method filtering, for a new continuation ledger")
    parser.add_argument("--proof", type=Path, default=RUN / "parser-source-equivalence.json")
    parser.add_argument("--calibration", type=Path, default=RUN / "parser-marker-control.json")
    args = parser.parse_args()
    if args.action != "probe" and (args.identifier or args.exclude_identifier
                                   or args.method or args.start_index):
        parser.error("probe filters apply only to probe")
    if args.identifier and args.exclude_identifier:
        parser.error("use either --identifier or --exclude-identifier")
    if args.action == "verify":
        proof, _plan = verified_plan()
        write_json(args.output, proof)
        print(json.dumps({"status": proof["status"], "specs": proof["spec_count"],
                          "probes": proof["representative_probe_count"],
                          "sha256": sha256(args.output)}))
        return 0
    if args.action == "calibrate":
        control = calibration_record()
        write_json(args.output, control)
        print(json.dumps({"status": control["status"], "marker": control["marker"],
                          "control": control["control"], "sha256": sha256(args.output)}))
        return 0 if control["status"] == "passed" else 2
    _proof, plan = verified_plan()
    return run_plan(plan, args.output, identifier=args.identifier,
                    exclude_identifier=args.exclude_identifier, method=args.method,
                    start_index=args.start_index,
                    calibration=args.calibration, proof=args.proof)


if __name__ == "__main__":
    raise SystemExit(main())
