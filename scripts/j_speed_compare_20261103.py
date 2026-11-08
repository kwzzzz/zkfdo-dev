#!/usr/bin/env python3
"""Sequential, isolated A-development J differential timing; never edits saved inputs."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runs/n7-a-sj-cold-2026-10-29-v2"
RUN_ROOT = ROOT / "runs/j-speed-2026-11-03/comparison"
BASELINE = ROOT / "runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development"
BASELINE_SHA = "05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700"
NEW_BINARY = ROOT / "runs/j-speed-2026-11-03/target/debug/zkfdo-j-v24"
TOOLS = {"circom": Path("/Users/miiz/.cargo/bin/circom"), "node": Path("/opt/homebrew/bin/node"), "snarkjs": Path("/opt/homebrew/bin/snarkjs"), "z3": Path("/opt/homebrew/bin/z3")}
ARMS = ("v23", "j1", "j4")
MIN_FREE_BYTES = 25 * 2**30
CLASS_FIELDS = ("pattern", "representative", "sites", "verdict", "reason", "inputs", "honest_generation", "deviated_generation", "rust_unsatisfied", "snarkjs", "public_inputs_equal", "outputs_differing", "deviation_sites", "assumption_predicate_verdict", "semantic_deviation_observed")
PREDICATE_FIELDS = ("component_instance", "instance", "verdict", "reason", "rust_unsatisfied", "snarkjs", "o0_o1_agree", "target_basis", "reach_inputs", "semantic_deviation_observed")


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def atomic_summary(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temporary.replace(path)


def inventory(source=SOURCE):
    return sorted(source.glob("*/judgements/*/request.json")) + sorted(source.glob("*/replay/*/request.json"))


def disk_gate(directory, minimum=MIN_FREE_BYTES):
    usage = shutil.disk_usage(directory)
    if usage.free < minimum:
        raise RuntimeError(f"disk gate: {usage.free / 2**30:.3f} GiB free < {minimum / 2**30:.3f} GiB")
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def environment(directory):
    usage = shutil.disk_usage(directory)
    return {"utc": utc(), "load_average": list(os.getloadavg()), "disk_bytes": {"total": usage.total, "used": usage.used, "free": usage.free}}


def semantic_fingerprint(result):
    """Compare claims/checks; witness identity and strategy provenance are separate."""
    preparation = result.get("preparation") or {}
    classes = []
    for item in result.get("classes", []):
        row = {key: item.get(key) for key in CLASS_FIELDS}
        row["predicates"] = [{key: pred.get(key) for key in PREDICATE_FIELDS} for pred in item.get("predicates", [])]
        classes.append(row)
    component = result.get("component") or {}
    entrypoint = result.get("entrypoint") or {}
    return {"preparation": {key: preparation.get(key) for key in ("status", "reason")}, "component_classification": result.get("component_classification"), "property": result.get("property"), "violated_condition": result.get("violated_condition"), "sites_found": result.get("sites_found"), "verdict_counts": result.get("verdict_counts"), "component_candidate_satisfies_o0": component.get("candidate_satisfies_component_o0"), "entrypoint": entrypoint, "classes": classes}


def basis_fingerprint(result):
    return [{"pattern": item.get("pattern"), "representative": item.get("representative"), "input_origin": item.get("input_origin"), "synthesis": {key: (item.get("synthesis") or {}).get(key) for key in ("b_outcome", "reached_with", "changed_inputs", "sweep_end", "cause_before_budget")}, "evidence": item.get("evidence"), "exceptions": item.get("exceptions"), "predicates": [{key: pred.get(key) for key in ("instance", "method", "evidence", "shared_from")} for pred in item.get("predicates", [])]} for item in result.get("classes", [])]


def differences(left, right, path=""):
    if type(left) is not type(right):
        return [{"path": path, "baseline": left, "new": right}]
    if isinstance(left, dict):
        result = []
        for key in sorted(left.keys() | right.keys()):
            result.extend(differences(left.get(key), right.get(key), f"{path}/{key}"))
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": path + "/length", "baseline": len(left), "new": len(right)}]
        return [change for index, (a, b) in enumerate(zip(left, right)) for change in differences(a, b, f"{path}/{index}")]
    return [] if left == right else [{"path": path, "baseline": left, "new": right}]


def compare_results(baseline, result):
    semantic = differences(semantic_fingerprint(baseline), semantic_fingerprint(result))
    basis = differences(basis_fingerprint(baseline), basis_fingerprint(result))
    return {"semantic_equal": not semantic, "semantic_differences": semantic, "basis_equal": not basis, "basis_differences": basis}


def source_snapshot(request):
    data = json.loads(request.read_text())
    roots = [Path(data["source_root"]), *map(Path, data.get("library_paths", []))]
    files = {Path(data[key]).resolve() for key in ("entrypoint", "component_wrapper", "base_input")}
    files.add(Path(data["candidate"]["path"]).resolve())
    for directory in roots:
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        files.update(path.resolve() for path in directory.rglob("*.circom") if path.is_file())
    rows = [{"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size} for path in sorted(files)]
    return {"request": str(request), "request_sha256": sha(request), "candidate_sha256": sha(data["candidate"]["path"]), "source_roots": [str(p) for p in roots], "files": rows, "files_sha256": canonical_sha(rows)}


def run_process(argv, directory):
    """wait4 the direct child once; persist metrics even if this wrapper is interrupted."""
    start_environment = environment(directory)
    parent_before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.monotonic()

    def resources(process, usage):
        parent_after = resource.getrusage(resource.RUSAGE_SELF)
        return {"returncode": process.returncode, "wall_seconds": time.monotonic() - started, "cpu_user_seconds": usage.ru_utime, "cpu_system_seconds": usage.ru_stime, "cpu_seconds": usage.ru_utime + usage.ru_stime, "cpu_scope": "wait4 direct J process plus descendants waited by J; excludes timing wrapper; interrupted descendants killed before J reaps them may be absent", "wrapper_cpu_seconds": (parent_after.ru_utime + parent_after.ru_stime) - (parent_before.ru_utime + parent_before.ru_stime), "max_rss_raw": usage.ru_maxrss, "max_rss_unit": "bytes" if sys.platform == "darwin" else "KiB", "pid": process.pid, "started": start_environment, "finished": environment(directory)}

    def terminate_signal(signum, _frame):
        raise InterruptedError(f"runner received signal {signum}")

    previous_term = signal.signal(signal.SIGTERM, terminate_signal)
    try:
        with (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
            process = subprocess.Popen([str(arg) for arg in argv], cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                save_new(directory / "child.json", {"pid": process.pid, "pgid": process.pid, "argv": [str(a) for a in argv], "started": start_environment})
                while True:
                    child, status, usage = os.wait4(process.pid, os.WNOHANG)
                    if child:
                        break
                    time.sleep(0.1)
            except BaseException as error:
                # Preserve new evidence before propagating the interruption; never rewrite old runs.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                child, status, usage = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
                save_new(directory / "interrupted.json", {"schema": "j-speed-interrupted-v1", "exception": type(error).__name__, "detail": str(error), "termination_signal": "SIGTERM", "reaped_pid": child, "resources": resources(process, usage)})
                raise
            process.returncode = os.waitstatus_to_exitcode(status)
        return resources(process, usage)
    finally:
        signal.signal(signal.SIGTERM, previous_term)


def bind_identity(run_root, label, value):
    path = run_root / (label + ".json")
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise RuntimeError(f"identity changed: {path}")
    else:
        save_new(path, value)


def refresh_index(run_root):
    rows = [json.loads(path.read_text()) for path in sorted(run_root.glob("requests/*/*/record.json"))]
    data = {"schema": "j-speed-index-v1", "updated": utc(), "rows": rows, "stopped": (run_root / "STOP.json").exists()}
    atomic_summary(run_root / "index.json", data)
    return data


def stop(run_root, details):
    if not (run_root / "STOP.json").exists():
        save_new(run_root / "STOP.json", {"utc": utc(), **details})
    refresh_index(run_root)


def run_arm(index, request, arm, run_root, new_binary=NEW_BINARY):
    if (run_root / "STOP.json").exists():
        raise RuntimeError("global STOP.json exists; no further engine runs")
    folder = run_root / "requests" / f"{index:02d}" / arm
    record_path = folder / "record.json"
    if record_path.exists():
        previous = json.loads(record_path.read_text())
        print(json.dumps({"request_index": index, "arm": arm, "status": "already_recorded", "wall_seconds": previous.get("resources", {}).get("wall_seconds")}), flush=True)
        return previous
    baseline_path = folder.parent / "v23/out/result.json"
    if arm not in ("v23", "profile") and not baseline_path.is_file():
        raise RuntimeError(f"fresh baseline required before {arm}: {baseline_path}")
    disk_gate(run_root)
    binary = BASELINE if arm == "v23" else new_binary
    binary_hash = sha(binary)
    if arm == "v23" and binary_hash != BASELINE_SHA:
        raise RuntimeError("pinned baseline binary hash changed")
    bind_identity(run_root, "binary-v23" if arm == "v23" else "binary-v24", {"path": str(binary), "sha256": binary_hash})
    tool_hashes = {name: {"path": str(path), "sha256": sha(path)} for name, path in TOOLS.items()}
    bind_identity(run_root, "tools", tool_hashes)
    snapshot = source_snapshot(request)
    bind_identity(run_root, f"request-{index:02d}-inputs", snapshot)
    folder.mkdir(parents=True, exist_ok=False)
    argv = [binary, "--request", request, "--output", folder / "out", "--cache", folder / "cache", "--instance-store", folder / "instance-store"]
    for name, path in TOOLS.items():
        argv += [f"--{name}-bin", path]
    if arm == "profile":
        argv += ["--profile-only"]
    elif arm != "v23":
        argv += ["--j-jobs", "1" if arm == "j1" else "4"]
    save_new(folder / "start.json", {"schema": "j-speed-start-v1", "utc": utc(), "request_index": index, "request": str(request), "arm": arm, "binary_sha256": binary_hash, "tools": tool_hashes, "input_snapshot_sha256": canonical_sha(snapshot), "argv": [str(a) for a in argv], "minimum_free_bytes": MIN_FREE_BYTES, "timeout": None, "cache_policy": "empty separate directory per request and arm; no cross-arm/seed reuse"})
    print(json.dumps({"request_index": index, "arm": arm, "status": "running", "pid": os.getpid(), "utc": utc()}), flush=True)
    try:
        resources = run_process(argv, folder)
    except Exception as error:
        record = {"schema": "j-speed-record-v1", "request_index": index, "request": str(request), "arm": arm, "status": "execution_error", "error": repr(error), "binary_sha256": binary_hash, "request_sha256": snapshot["request_sha256"]}
        save_new(record_path, record)
        stop(run_root, {"request_index": index, "arm": arm, "reason": "execution_error", "record": str(record_path)})
        raise
    result_path = folder / "out/result.json"
    record = {"schema": "j-speed-record-v1", "request_index": index, "request": str(request), "arm": arm, "binary_sha256": binary_hash, "request_sha256": snapshot["request_sha256"], "input_snapshot_sha256": canonical_sha(snapshot), "resources": resources, "result": str(result_path), "status": "complete"}
    if resources["returncode"] != 0 or not result_path.exists():
        record.update(status="engine_error", error="nonzero exit or missing result.json")
    else:
        try:
            result = json.loads(result_path.read_text())
            if not isinstance(result, dict) or "preparation" not in result or "classes" not in result:
                raise ValueError("result lacks preparation/classes")
        except (ValueError, OSError) as error:
            record.update(status="invalid_result", error=str(error))
            save_new(record_path, record)
            stop(run_root, {"request_index": index, "arm": arm, "reason": "invalid_result", "record": str(record_path)})
            raise RuntimeError("invalid engine result") from error
        record.update(result_sha256=sha(result_path), semantic_fingerprint=semantic_fingerprint(result), semantic_sha256=canonical_sha(semantic_fingerprint(result)), basis_sha256=canonical_sha(basis_fingerprint(result)), preparation=result.get("preparation"), verdict_counts=result.get("verdict_counts"), engine_wall_seconds=result.get("costs", {}).get("wall_seconds"))
        if arm in ("v23", "profile"):
            historical = request.parent / "out/result.json"
            record["historical_comparison"] = compare_results(json.loads(historical.read_text()), result) if historical.exists() else {"status": "historical_result_missing"}
        else:
            record["comparison"] = compare_results(json.loads(baseline_path.read_text()), result)
            if not record["comparison"]["semantic_equal"]:
                record["status"] = "semantic_mismatch"
    if arm == "profile":
        sidecar = folder / "out/j-profile.json"
        record["mode"] = "legacy_semantics_profile_only"
        record["profile_sidecar"] = {"path": str(sidecar), "exists": sidecar.exists()}
        if sidecar.exists():
            record["profile_sidecar"]["sha256"] = sha(sidecar)
        elif record["status"] == "complete":
            record.update(status="profile_sidecar_missing", error="profile-only run did not write j-profile.json")
    # Detect source mutation during a long run without placing values in the tracked report.
    after_snapshot = source_snapshot(request)
    record["inputs_unchanged"] = canonical_sha(after_snapshot) == canonical_sha(snapshot)
    if not record["inputs_unchanged"]:
        record.update(status="input_drift", error="request/dependency content changed during run")
    save_new(record_path, record)
    refresh_index(run_root)
    print(json.dumps({"request_index": index, "arm": arm, "status": record["status"], "wall_seconds": resources["wall_seconds"], "cpu_seconds": resources["cpu_seconds"], "semantic_equal": record.get("comparison", {}).get("semantic_equal"), "basis_equal": record.get("comparison", {}).get("basis_equal")}), flush=True)
    if record["status"] != "complete":
        stop(run_root, {"request_index": index, "request": str(request), "arm": arm, "reason": record["status"], "record": str(record_path)})
        raise RuntimeError(f"stopped after request {index} {arm}: {record['status']}")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="run/resume every request and arm sequentially (default)")
    parser.add_argument("--request-index", type=int)
    parser.add_argument("--arm", choices=(*ARMS, "profile"), help="profile is opt-in; default arms remain v23,j1,j4")
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--new-binary", type=Path, default=NEW_BINARY)
    parser.add_argument("--list", action="store_true", help="list saved requests without starting an engine")
    args = parser.parse_args()
    requests = inventory()
    if len(requests) != 14:
        parser.error(f"expected frozen 14-request inventory, found {len(requests)}")
    if args.list:
        print(json.dumps([{"index": i, "request": str(p), "historical_result_exists": (p.parent / "out/result.json").exists()} for i, p in enumerate(requests)], indent=2))
        return 0
    if args.all and (args.request_index is not None or args.arm is not None):
        parser.error("--all cannot be combined with a request or arm filter")
    if args.request_index is not None and not 0 <= args.request_index < len(requests):
        parser.error("invalid request index")
    run_root = args.run_root.resolve()
    if not run_root.is_relative_to((ROOT / "runs").resolve()):
        parser.error("all generated artifacts must stay under repository runs/")
    run_root.mkdir(parents=True, exist_ok=True)
    with (run_root / ".runner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("another timing runner holds the lock")
        bind_identity(run_root, "inventory", [{"index": i, "path": str(p), "sha256": sha(p)} for i, p in enumerate(requests)])
        selected = [args.request_index] if args.request_index is not None else range(len(requests))
        try:
            for index in selected:
                for arm in ([args.arm] if args.arm else ARMS):
                    run_arm(index, requests[index], arm, run_root, args.new_binary.resolve())
        except Exception as error:
            print(json.dumps({"status": "stopped", "error": str(error)}), file=sys.stderr, flush=True)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
