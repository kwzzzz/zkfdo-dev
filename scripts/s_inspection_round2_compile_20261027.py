#!/usr/bin/env python3
"""Select and compile A development wrappers only; never run judging or fuzzing."""
from __future__ import annotations
import argparse
import fcntl
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import shutil
import signal
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runs/s-inspection-improve-2026-10-27/compile-check"
SUMMARY = ROOT / "runs/n6-a1b-2026-10-08/preparation-summary.json"
MAPPING = ROOT / "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json"
UNITS = ("aq-024-6f6781246415", "aq-017-9703bbce0c43")
EXAMPLE_TEMPLATES = {"ZAccountBlackListLeafInclusionProver", "DataEscrowElGamalEncryption",
                     "RewardsExtended", "ZoneIdInclusionProver", "BabyJubJubSubOrderTag"}
SEED = 20261027
GIB = 1024**3
BN128 = "21888242871839275222246405745257275088548364400416034343698204186575808495617"


def now():
    return datetime.now(timezone.utc).isoformat()


def guard():
    if os.getpriority(os.PRIO_PROCESS, 0) < 19:
        raise RuntimeError("nice 19 required")
    if shutil.disk_usage(ROOT).free < 15 * GIB:
        raise RuntimeError("internal disk below 15 GiB; stopped")


def safe_path(value):
    p = Path(value)
    p = p if p.is_absolute() else ROOT / p
    p = p.resolve()
    if ("n6-a-remeasure-2026-10-25.noindex" in p.parts or
            str(p).startswith("/Volumes/zkfdo-jcache") or
            any(part.startswith(("n6-b6", "h1-")) for part in p.parts)):
        raise ValueError("forbidden path")
    return p


def output_path(value):
    p = safe_path(value)
    if p != OUTPUT:
        raise ValueError(f"outputs must use exactly {OUTPUT}")
    return p


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with safe_path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path, expected=None):
    guard()
    p = safe_path(path)
    raw = p.read_bytes()
    actual = digest_bytes(raw)
    if expected is not None and actual != expected:
        raise ValueError(f"input SHA mismatch: {p}")
    return json.loads(raw), {"path": str(p), "sha256": actual}


def write_new(path, value, stop_receipt=False):
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if stop_receipt:
        # A bounded final status is the report required when the disk gate stops work.
        if os.getpriority(os.PRIO_PROCESS, 0) < 19 or len(content.encode()) > 256 * 1024:
            raise RuntimeError("invalid bounded stop receipt")
    else:
        guard()
    p = safe_path(path)
    if not p.is_relative_to(OUTPUT):
        raise ValueError("write outside compile-check output")
    with p.open("x") as f:
        f.write(content)


def load_measurement(path):
    data, source = read_json(path)
    rows, sources = {}, [source]
    for unit in data["units"]:
        if unit["unit"] not in UNITS:
            continue
        result, source = read_json(unit["output"], unit["sha256"])
        sources.append(source)
        selected = result["targets"]
        by_label = {row["label"]: row for row in selected}
        if len(by_label) != len(selected):
            raise ValueError("duplicate measurement target")
        rows[unit["unit"]] = by_label
    if set(rows) != set(UNITS):
        raise ValueError("measurement must contain both requested aq units")
    return rows, sources


def choose_rows(before, after, round1, templates, sample_count=50, seed=SEED):
    if set(before) != set(after) or set(round1) != set(after):
        raise ValueError("inspection target labels changed")
    forced = [label for label, row in after.items() if row["template"] in templates]
    pool = [label for label, row in after.items()
            if row["inspection_eligible"] and not round1[label]["inspection_eligible"] and label not in forced]
    key = lambda label: (after[label].get("target_id", ""), label)
    forced.sort(key=key)
    pool.sort(key=key)
    sample = random.Random(seed).sample(pool, min(sample_count, len(pool)))
    sample.sort(key=key)
    result = []
    for label in forced + sample:
        result.append({"label": label, "selection_kind": "required_template" if label in forced else "fixed_seed_sample",
                       "inspection_before": before[label]["inspection_eligible"],
                       "inspection_round1": round1[label]["inspection_eligible"],
                       "inspection_after": after[label]["inspection_eligible"],
                       "newly_passing_vs_original": not before[label]["inspection_eligible"] and after[label]["inspection_eligible"],
                       "newly_passing_in_round1": not before[label]["inspection_eligible"] and round1[label]["inspection_eligible"],
                       "newly_passing_only_round2": not round1[label]["inspection_eligible"] and after[label]["inspection_eligible"]})
    return result, {"forced": len(forced), "sample": len(sample), "sample_requested": sample_count,
                    "sample_shortfall": max(0, sample_count - len(pool)), "newly_passing_pool_excluding_forced": len(pool),
                    "sampling_basis": "round 2 inspection passes and round 1 inspection fails; required-template targets excluded"}


def validate_compile_args(args):
    # The selected A manifests use only library search paths. Refuse any output,
    # executable, optimization or prime override instead of silently changing it.
    result = []
    i = 0
    while i < len(args):
        if args[i] != "-l":
            raise ValueError(f"unsupported compile argument: {args[i]}")
        result.append("-l")
        i += 1
        start = i
        while i < len(args) and not args[i].startswith("-"):
            result.append(str(safe_path(args[i])))
            i += 1
        if i == start:
            raise ValueError("missing library directory")
    return result


def compile_argv(compiler, definition, artifacts):
    if definition["prime"] != "bn128":
        raise ValueError("this development compile check requires explicit bn128")
    return [str(compiler), str(safe_path(definition["entrypoint"])), "--r1cs", "--prime",
            definition["prime"], "--output", str(artifacts), *validate_compile_args(definition.get("compile_args", []))]


def select(args):
    output = output_path(args.output)
    if output.exists():
        raise ValueError("selection output directory must be new")
    before, before_sources = load_measurement(args.before)
    after, after_sources = load_measurement(args.after)
    round1, round1_sources = load_measurement(args.round1)
    prepared_summary, summary_source = read_json(args.prepared_summary)
    mapping, map_source = read_json(args.mapping)
    by_prepared = {row["unit_id"]: row for row in prepared_summary["units"]}
    by_map = {row["revision_id"]: row for row in mapping["revisions"]}
    selected, unit_summaries, source_inputs, prepared_sources = [], [], {}, []
    compiler_refs = {}
    for unit in UNITS:
        guard()
        raw, source = read_json(by_prepared[unit]["prepared_report"]["path"], by_prepared[unit]["prepared_report"]["sha256"])
        prepared_sources.append(source)
        definitions = {row["definition"]["label"]: row for row in raw["targets"]}
        if set(definitions) != set(after[unit]):
            raise ValueError("prepared/inspection target labels differ")
        direct = {name for item in by_map[unit]["items"] for name in item["templates"]}
        templates = direct | EXAMPLE_TEMPLATES
        chosen, counts = choose_rows(before[unit], after[unit], round1[unit], templates, args.sample_count, args.seed)
        if counts["sample_shortfall"]:
            raise ValueError(f"round-2-only sample shortfall for {unit}: requested 50, eligible pool {counts['newly_passing_pool_excluding_forced']}; no selection written and no fallback to the original baseline")
        compiler = by_prepared[unit]["condition"]["circom"]
        compiler_path = safe_path(compiler["path"])
        if compiler_path.name != "circom" or digest(compiler_path) != compiler["sha256"]:
            raise ValueError("recorded Circom compiler path or SHA differs")
        compiler_refs[str(compiler_path)] = compiler["sha256"]
        for choice in chosen:
            old = definitions[choice["label"]]
            definition = old["definition"]
            wrapper = safe_path(definition["entrypoint"])
            wrapper_sha = digest(wrapper)
            if wrapper_sha != after[unit][choice["label"]]["existing_wrapper_sha256"]:
                raise ValueError("wrapper changed after inspection")
            validate_compile_args(definition.get("compile_args", []))
            for item in old["source_fingerprints"]:
                key = str(safe_path(item["path"]))
                if key in source_inputs and source_inputs[key] != item["sha256"]:
                    raise ValueError("source fingerprint conflict")
                source_inputs[key] = item["sha256"]
            source_inputs[str(wrapper)] = wrapper_sha
            selected.append({"unit": unit, **choice, "template": definition["template_name"],
                             "mapping_role": "direct_rq_c" if definition["template_name"] in direct else "requested_additional_template" if choice["selection_kind"] == "required_template" else "sample",
                             "definition": definition, "wrapper_sha256": wrapper_sha,
                             "compiler": str(compiler_path), "compiler_sha256": compiler["sha256"],
                             "prepared_source": source, "inspection_target_id": after[unit][choice["label"]].get("target_id")})
        unit_summaries.append({"unit": unit, **counts, "direct_mapping_templates": sorted(direct),
                               "additional_requested_templates": sorted(EXAMPLE_TEMPLATES - direct),
                               "missing_required_templates": sorted(templates - {row["template"] for row in after[unit].values()}),
                               "round2_only_in_sample": sum(row["newly_passing_only_round2"] for row in chosen if row["selection_kind"] == "fixed_seed_sample")})
        del raw, definitions
    guard()
    output.mkdir(parents=True, exist_ok=False)
    plan = {"schema_version": 1, "kind": "a_development_fragment_compile_selection", "created_at": now(),
            "seed": args.seed, "sample_per_unit": args.sample_count, "cpu_contention": True,
            "inspection_sources": {"before": before_sources, "round1": round1_sources, "after": after_sources},
            "prepared_summary": summary_source, "prepared_sources": prepared_sources, "mapping": map_source,
            "source_inputs": [{"path": key, "sha256": value} for key, value in sorted(source_inputs.items())],
            "compilers": [{"path": key, "sha256": value} for key, value in sorted(compiler_refs.items())],
            "units": unit_summaries, "targets": selected,
            "compile_basis": "src/structure.rs:238-253; same R1CS/prime/library arguments, original source wrapper, compiler SHA pinned; no AST, judging or fuzz calls",
            "environment": {"cwd": str(ROOT), "inherit_environment": True, "overrides": {"RAYON_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}},
            "limitations": ["Required templates are compiled even when inspection is still incomplete.",
                            "The fixed-seed sample contains exactly 50 round-2-only gains per unit. A shortfall aborts selection; the pool is never expanded to original-baseline gains. Original-baseline and round-1 provenance flags remain recorded."]}
    write_new(output / "selection.json", plan)
    print(json.dumps({"selection": str(output / "selection.json"), "sha256": digest(output / "selection.json"),
                      "targets": len(selected), "units": unit_summaries}, ensure_ascii=False))


def r1cs_header(stream, size):
    if stream.read(4) != b"r1cs":
        raise ValueError("R1CS magic differs")
    version, sections = struct.unpack("<II", stream.read(8))
    if version != 1 or not 1 <= sections <= 64:
        raise ValueError("unsupported R1CS version/section count")
    found = None
    for _ in range(sections):
        section, length = struct.unpack("<IQ", stream.read(12))
        end = stream.tell() + length
        if end > size:
            raise ValueError("truncated R1CS section")
        if section == 1:
            if found is not None:
                raise ValueError("duplicate R1CS header")
            field_size = struct.unpack("<I", stream.read(4))[0]
            if not 1 <= field_size <= 128 or length != field_size + 32:
                raise ValueError("invalid R1CS field/header length")
            prime_bytes = stream.read(field_size)
            wires, public_outputs, public_inputs, private_inputs = struct.unpack("<IIII", stream.read(16))
            labels = struct.unpack("<Q", stream.read(8))[0]
            constraints = struct.unpack("<I", stream.read(4))[0]
            found = {"version": version, "sections": sections, "field_bytes": field_size,
                     "prime": str(int.from_bytes(prime_bytes, "little")), "wires": wires,
                     "public_outputs": public_outputs, "public_inputs": public_inputs, "private_inputs": private_inputs,
                     "labels": labels, "constraints": constraints}
        stream.seek(end)
    if found is None:
        raise ValueError("R1CS header missing")
    return found


def bounded_log(path, limit=12000):
    with path.open("rb") as f:
        raw = f.read(limit)
    text = raw.decode("utf-8", errors="replace")
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def artifact_metadata(path, artifact_root):
    if path.is_symlink() or path.resolve().parent != artifact_root.resolve() or not artifact_root.resolve().is_relative_to(OUTPUT):
        raise ValueError("artifact is outside this run's exact artifact directory")
    if not path.is_file():
        return None
    value = {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}
    if path.suffix == ".r1cs":
        try:
            with path.open("rb") as f:
                value["header"] = r1cs_header(f, value["bytes"])
        except (ValueError, struct.error) as error:
            value["header_error"] = str(error)
    return value


PENDING_STOPS = {"internal_disk_below_15_GiB", "total_runtime_limit", "interrupted", "monitoring_error"}


def stop_own_child(process):
    # Only the process group created by this invocation with start_new_session.
    if process.poll() is not None:
        process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)


def monitor_child(process, paths, stdout, stderr, request_tick, run_tick, timeout, runtime, artifact_mib):
    stop_reason, error, peak = None, None, 0
    try:
        while process.poll() is None:
            elapsed = time.monotonic() - request_tick
            observed = sum(p.stat().st_size for p in paths if p.is_file())
            peak = max(peak, observed)
            if shutil.disk_usage(ROOT).free < 15 * GIB:
                stop_reason = "internal_disk_below_15_GiB"
            elif elapsed >= timeout:
                stop_reason = "compile_timeout"
            elif time.monotonic() - run_tick >= runtime:
                stop_reason = "total_runtime_limit"
            elif observed > artifact_mib * 1024**2:
                stop_reason = "artifact_size_limit"
            elif sum(p.stat().st_size for p in (stdout, stderr)) > 2 * 1024**2:
                stop_reason = "log_size_limit"
            if stop_reason:
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_reason, error = "interrupted", "KeyboardInterrupt"
    except BaseException as failure:
        stop_reason, error = "monitoring_error", f"{type(failure).__name__}: {str(failure)[:2000]}"
    finally:
        # Covers normal completion, disk/time limits and every monitoring exception.
        stop_own_child(process)
    return {"returncode": process.returncode, "stop_reason": stop_reason, "monitoring_error": error,
            "peak_artifact_bytes_observed": peak, "own_child_reaped": True}


def validate_receipt_bindings(receipt, target, selection, directory):
    expected = {"unit": target["unit"], "label": target["label"], "template": target["template"],
                "compiler_sha256": target["compiler_sha256"], "wrapper_sha256": target["wrapper_sha256"],
                "wrapper": str(safe_path(target["definition"]["entrypoint"])), "selection": selection,
                "argv": compile_argv(target["compiler"], target["definition"], directory / "artifacts")}
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError(f"existing receipt binding differs: {key}")
    status = receipt.get("completion_status")
    if status is None:
        status = "pending" if receipt.get("stop_reason") in PENDING_STOPS or receipt.get("spawn_error") else "completed"
    if status not in {"completed", "pending"}:
        raise ValueError("unknown receipt completion status")
    if status == "completed" and type(receipt.get("returncode")) is not int:
        raise ValueError("completed receipt has no process exit code")
    return status


def receipt_reference(path, receipt):
    return {"path": str(path), "sha256": digest(path), "unit": receipt["unit"], "label": receipt["label"],
            "template": receipt["template"], "compile_success": receipt["compile_success"],
            "returncode": receipt["returncode"], "stop_reason": receipt.get("stop_reason"),
            "completion_status": receipt.get("completion_status", "completed"), "elapsed_seconds": receipt["elapsed_seconds"]}


def existing_target_result(base, target, selection):
    completed, checked = None, []
    candidates = [base / "result.json"] if (base / "result.json").is_file() else []
    if (base / "invocation.json").is_file() and not candidates:
        raise ValueError("legacy invocation has no termination receipt; refusing to assume its compiler stopped")
    number = 1
    while (base / f"attempt-{number:04}").exists():
        directory = base / f"attempt-{number:04}"
        if (directory / "result.json").is_file():
            candidates.append(directory / "result.json")
        elif (directory / "invocation.json").is_file():
            raise ValueError("invocation has no termination receipt; refusing to assume its compiler stopped")
        number += 1
        if number > 1000:
            raise ValueError("too many request attempts")
    for path in candidates:
        receipt, _ = read_json(path)
        status = validate_receipt_bindings(receipt, target, selection, path.parent)
        for field in ("stdout", "stderr"):
            log = receipt[field]
            expected_path = path.parent / f"{field}.log"
            if safe_path(log["path"]) != expected_path or digest(expected_path) != log["sha256"]:
                raise ValueError("existing compiler log path or SHA differs")
            if expected_path.stat().st_size != log["bytes"]:
                raise ValueError("existing compiler log size differs")
        reference = receipt_reference(path, receipt)
        reference["completion_status"] = status
        checked.append(reference)
        if status == "completed":
            if completed is not None:
                raise ValueError("multiple completed receipts for one selected target")
            completed = reference
    return completed, checked, number


def execute_target(args, target, selection, directory, run_tick):
    directory.mkdir()
    artifacts = directory / "artifacts"
    artifacts.mkdir()
    wrapper = safe_path(target["definition"]["entrypoint"])
    paths = [artifacts / f"{wrapper.stem}.r1cs", artifacts / f"{wrapper.stem}.sym"]
    stdout, stderr = directory / "stdout.log", directory / "stderr.log"
    command = compile_argv(target["compiler"], target["definition"], artifacts)
    invocation = {"unit": target["unit"], "label": target["label"], "template": target["template"],
                  "selection_kind": target["selection_kind"], "mapping_role": target["mapping_role"],
                  "selection": selection, "argv": command, "cwd": str(ROOT), "compiler_sha256": target["compiler_sha256"],
                  "wrapper": str(wrapper), "wrapper_sha256": target["wrapper_sha256"], "start_utc": now(),
                  "nice": 19, "cpu_contention": True, "free_bytes_start": shutil.disk_usage(ROOT).free,
                  "environment_overrides": {"RAYON_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
                  "timeout_seconds": args.timeout_seconds,
                  "newly_passing_vs_original": target["newly_passing_vs_original"],
                  "newly_passing_in_round1": target["newly_passing_in_round1"],
                  "newly_passing_only_round2": target["newly_passing_only_round2"]}
    write_new(directory / "invocation.json", invocation)
    request_tick, spawn_error, process = time.monotonic(), None, None
    monitored = {"returncode": None, "stop_reason": None, "monitoring_error": None,
                 "peak_artifact_bytes_observed": 0, "own_child_reaped": True}
    environment = os.environ.copy()
    environment.update(invocation["environment_overrides"])
    with stdout.open("xb") as out, stderr.open("xb") as err:
        try:
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=out, stderr=err, start_new_session=True)
            monitored = monitor_child(process, paths, stdout, stderr, request_tick, run_tick,
                                      args.timeout_seconds, args.max_runtime_seconds, args.max_artifact_mib)
        except KeyboardInterrupt:
            monitored.update(stop_reason="interrupted", monitoring_error="KeyboardInterrupt")
        except OSError as failure:
            spawn_error = str(failure)[:2000]
        except BaseException as failure:
            monitored.update(stop_reason="monitoring_error", monitoring_error=f"{type(failure).__name__}: {str(failure)[:2000]}")
        finally:
            # This outer finally also covers exceptions between Popen and monitor_child.
            if process is not None:
                stop_own_child(process)
                monitored["returncode"] = process.returncode
                monitored["own_child_reaped"] = True
    receipt = {**invocation, **monitored, "end_utc": now(), "elapsed_seconds": time.monotonic() - request_tick,
               "spawn_error": spawn_error, "free_bytes_end": shutil.disk_usage(ROOT).free,
               "stdout": {"path": str(stdout), "sha256": digest(stdout), "bytes": stdout.stat().st_size},
               "stderr": {"path": str(stderr), "sha256": digest(stderr), "bytes": stderr.stat().st_size},
               "compiler_error": None, "artifacts": [], "artifact_errors": []}
    if monitored["returncode"] != 0 or monitored["stop_reason"]:
        receipt["compiler_error"] = spawn_error or monitored["monitoring_error"] or (bounded_log(stderr) + "\n" + bounded_log(stdout)).strip()
    for artifact in paths:
        try:
            info = artifact_metadata(artifact, artifacts)
            if info is not None:
                artifact.unlink()
                info["removed_after_metadata_capture"] = True
                receipt["artifacts"].append(info)
        except Exception as failure:
            receipt["artifact_errors"].append(f"{artifact.name}: {type(failure).__name__}: {str(failure)[:1000]}")
    r1cs = next((item for item in receipt["artifacts"] if item["path"].endswith(".r1cs")), None)
    receipt["compile_success"] = (monitored["returncode"] == 0 and monitored["stop_reason"] is None and r1cs is not None
                                  and r1cs.get("header", {}).get("prime") == BN128 and not receipt["artifact_errors"])
    if monitored["returncode"] == 0 and not receipt["compile_success"]:
        receipt["compiler_error"] = "compiler returned success without a readable R1CS header for the requested bn128 field"
    receipt["completion_status"] = "pending" if spawn_error or monitored["stop_reason"] in PENDING_STOPS else "completed"
    write_new(directory / "result.json", receipt, stop_receipt=True)
    return receipt_reference(directory / "result.json", receipt), receipt


def run(args):
    output = output_path(args.output)
    if not output.is_dir():
        raise ValueError("select must finish before run")
    # The lock contains no process identity and is never used to inspect or signal a prior process.
    if (output / "runner.lock").is_symlink():
        raise ValueError("runner lock must not be a symlink")
    with (output / "runner.lock").open("ab") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as failure:
            raise RuntimeError("another compile-check invocation holds this output lock") from failure
        try:
            run_locked(args)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_locked(args):
    output = output_path(args.output)
    plan, plan_source = read_json(output / "selection.json")
    if not 1 <= args.timeout_seconds <= 120 or not 1 <= args.max_runtime_seconds <= 3600:
        raise ValueError("compile timeout must be <=120 seconds and total runtime <=3600 seconds")
    if not 1 <= args.max_artifact_mib <= 1024:
        raise ValueError("artifact bound must be <=1024 MiB")
    for item in plan["compilers"]:
        if safe_path(item["path"]).name != "circom" or digest(item["path"]) != item["sha256"]:
            raise ValueError("compiler SHA differs from selection")
    for group in plan["inspection_sources"].values():
        for item in group:
            if digest(item["path"]) != item["sha256"]:
                raise ValueError("inspection input changed since selection")
    for item in [plan["prepared_summary"], plan["mapping"], *plan["prepared_sources"]]:
        if digest(item["path"]) != item["sha256"]:
            raise ValueError("metadata changed since selection")
    source_stats = {}
    for item in plan["source_inputs"]:
        p = safe_path(item["path"])
        if digest(p) != item["sha256"]:
            raise ValueError(f"source changed since preparation: {p}")
        stat = p.stat()
        source_stats[str(p)] = (stat.st_size, stat.st_mtime_ns, item["sha256"])
    results_dir = output / "results"
    results_dir.mkdir(exist_ok=True)
    attempts = output / "attempts"
    attempts.mkdir(exist_ok=True)
    attempt_number = 1
    while (attempts / f"{attempt_number:04}").exists():
        attempt_number += 1
        if attempt_number > 1000:
            raise ValueError("too many run attempts")
    attempt_directory = attempts / f"{attempt_number:04}"
    attempt_directory.mkdir()
    started, tick, stopped = now(), time.monotonic(), None
    completed, previous_receipts, next_attempts = {}, [], {}
    for number, target in enumerate(plan["targets"]):
        base = results_dir / f"{number:04}-{target['unit']}"
        prior, checked, next_attempt = existing_target_result(base, target, plan_source)
        previous_receipts.extend(checked)
        next_attempts[number] = next_attempt
        if prior:
            completed[number] = prior
    reused = len(completed)
    write_new(attempt_directory / "start.json", {"start_utc": started, "selection": plan_source,
              "attempt": attempt_number, "cpu_contention": True, "nice": 19,
              "reused_completed": reused, "pending": len(plan["targets"]) - reused,
              "validated_previous_receipts": previous_receipts})
    current_receipts, run_error = [], None
    try:
        for number, target in enumerate(plan["targets"]):
            if number in completed:
                continue
            try:
                guard()
            except RuntimeError as failure:
                stopped = str(failure)
                break
            if time.monotonic() - tick >= args.max_runtime_seconds:
                stopped = "total_runtime_limit"
                break
            for name, (size, mtime, expected) in source_stats.items():
                stat = Path(name).stat()
                if (stat.st_size, stat.st_mtime_ns) != (size, mtime) and digest(name) != expected:
                    raise ValueError("source changed during compilation checks")
            if digest(target["definition"]["entrypoint"]) != target["wrapper_sha256"]:
                raise ValueError("wrapper changed during compilation checks")
            base = results_dir / f"{number:04}-{target['unit']}"
            base.mkdir(exist_ok=True)
            directory = base / f"attempt-{next_attempts[number]:04}"
            reference, receipt = execute_target(args, target, plan_source, directory, tick)
            current_receipts.append(reference)
            if reference["completion_status"] == "completed":
                completed[number] = reference
            print(json.dumps({"completed": len(completed), "total": len(plan["targets"]), "unit": target["unit"],
                              "template": target["template"], "compile_success": receipt["compile_success"],
                              "returncode": receipt["returncode"], "completion_status": receipt["completion_status"],
                              "elapsed_seconds": receipt["elapsed_seconds"]}), flush=True)
            if reference["completion_status"] == "pending" or receipt["stop_reason"] == "log_size_limit":
                stopped = receipt["stop_reason"] or "compiler_spawn_failure"
                break
    except KeyboardInterrupt:
        stopped, run_error = "interrupted", "KeyboardInterrupt outside an active compiler"
    except BaseException as failure:
        stopped, run_error = "runner_error", f"{type(failure).__name__}: {str(failure)[:2000]}"
    all_completed = [completed[index] for index in sorted(completed)]
    result = {"schema_version": 2, "kind": "a_development_fragment_compile_checks", "selection": plan_source,
              "attempt": attempt_number, "start_utc": started, "end_utc": now(), "elapsed_seconds": time.monotonic() - tick,
              "cpu_contention": True, "nice": 19, "compiler_parallelism": 1,
              "requested": len(plan["targets"]), "completed": len(all_completed), "pending": len(plan["targets"]) - len(all_completed),
              "reused_completed": reused, "attempted_this_run": len(current_receipts),
              "passed": sum(row["compile_success"] for row in all_completed),
              "failed": sum(not row["compile_success"] for row in all_completed), "stopped": stopped, "runner_error": run_error,
              "results": all_completed, "current_attempt_receipts": current_receipts,
              "resume_policy": "Completed receipts, including compile timeouts, are hash/binding verified and skipped. Only pending targets run again in new attempt directories.",
              "scope": "R1CS compilation only; no judging, fuzzing, AST extraction, or original-source changes",
              "artifact_policy": "Only this attempt's R1CS/sym files are removed after SHA/header capture; all prior receipts and logs remain unchanged."}
    summary = output / f"summary-attempt-{attempt_number:04}.json"
    write_new(summary, result, stop_receipt=True)
    if not (output / "summary.json").exists():
        write_new(output / "summary.json", result, stop_receipt=True)
    write_new(attempt_directory / "result.json", {"start_utc": started, "end_utc": result["end_utc"],
              "cpu_contention": True, "selection": plan_source, "summary": {"path": str(summary), "sha256": digest(summary)},
              "completed": result["completed"], "pending": result["pending"], "stopped": stopped,
              "attempted_this_run": len(current_receipts), "reused_completed": reused}, stop_receipt=True)
    print(json.dumps({"summary": str(summary), "sha256": digest(summary), "completed": result["completed"],
                      "passed": result["passed"], "failed": result["failed"], "pending": result["pending"], "stopped": stopped}))
    if stopped or result["pending"]:
        raise SystemExit(130 if stopped == "interrupted" else 2)


def self_test():
    import unittest
    class Checks(unittest.TestCase):
        def fixtures(self):
            old = {str(i): {"template": "T" if i < 3 else "Other", "inspection_eligible": False, "target_id": f"id{i:03}"} for i in range(120)}
            new = {key: {**row, "inspection_eligible": True} for key, row in old.items()}
            first = {key: {**row, "inspection_eligible": int(key) % 2 == 0} for key, row in old.items()}
            return old, new, first
        def test_deterministic_sample(self):
            old,new,first=self.fixtures()
            a,counts=choose_rows(old,new,first,{"T"})
            b,_=choose_rows(dict(reversed(list(old.items()))),dict(reversed(list(new.items()))),first,{"T"})
            self.assertEqual(a,b); self.assertEqual(counts["sample"],50)
        def test_forced_not_sampled(self):
            a,_=choose_rows(*self.fixtures(),{"T"})
            self.assertEqual(len(a),len({r["label"] for r in a})); self.assertEqual(sum(r["selection_kind"]=="required_template" for r in a),3)
        def test_sample_is_only_newly_passing_since_round1(self):
            old,new,first=self.fixtures()
            rows,counts=choose_rows(old,new,first,{'T'})
            sample=[row for row in rows if row['selection_kind']=='fixed_seed_sample']
            self.assertEqual(len(sample),50)
            self.assertTrue(all(not first[row['label']]['inspection_eligible'] for row in sample))
            self.assertTrue(all(row['newly_passing_only_round2'] for row in sample))
        def test_round2_only_marked(self):
            a,_=choose_rows(*self.fixtures(),{"T"})
            for row in a:self.assertEqual(row["newly_passing_only_round2"],int(row["label"])%2==1)
        def test_forced_incomplete_still_selected(self):
            old,new,first=self.fixtures();new['0']['inspection_eligible']=False
            a,_=choose_rows(old,new,first,{"T"});self.assertIn('0',[r['label'] for r in a])
        def test_shortfall_explicit(self):
            old,new,first=self.fixtures()
            for key in list(old)[5:]:old.pop(key);new.pop(key);first.pop(key)
            a,c=choose_rows(old,new,first,{"T"});self.assertEqual(c['sample_shortfall'],49);self.assertEqual(len(a),4)
        def test_missing_target_rejected(self):
            old,new,first=self.fixtures();new.pop('0')
            with self.assertRaises(ValueError):choose_rows(old,new,first,{"T"})
        def test_no_output_override(self):
            for args in [['--output','/tmp'],['-o','/tmp'],['--prime','goldilocks'],['--wasm'],['-l']]:
                with self.assertRaises(ValueError):validate_compile_args(args)
        def test_forbidden_input(self):
            for name in ['runs/n6-a-remeasure-2026-10-25.noindex/state.json','/Volumes/zkfdo-jcache/entry','runs/n6-b6g-any/data']:
                with self.assertRaises(ValueError):safe_path(name)
        def test_fixed_output(self):
            with self.assertRaises(ValueError):output_path(ROOT/'runs/elsewhere')
        def test_r1cs_header(self):
            body=struct.pack('<I',32)+(17).to_bytes(32,'little')+struct.pack('<IIIIQI',20,1,2,3,40,50)
            data=b'r1cs'+struct.pack('<II',1,1)+struct.pack('<IQ',1,len(body))+body
            got=r1cs_header(io.BytesIO(data),len(data));self.assertEqual(got['constraints'],50);self.assertEqual(got['wires'],20)
        def test_r1cs_truncation(self):
            data=b'r1cs'+struct.pack('<II',1,1)+struct.pack('<IQ',1,64)
            with self.assertRaises(ValueError):r1cs_header(io.BytesIO(data),len(data))
        def test_unknown_prime_rejected(self):
            with self.assertRaises(ValueError):
                compile_argv('/circom', {'prime':'goldilocks','entrypoint':'fixture.circom'}, OUTPUT/'artifacts')
        def test_artifact_cannot_escape(self):
            with self.assertRaises(ValueError):
                artifact_metadata(ROOT/'Cargo.toml', OUTPUT/'artifacts')
        def test_missing_r1cs_header(self):
            data=b'r1cs'+struct.pack('<II',1,1)+struct.pack('<IQ',2,0)
            with self.assertRaises(ValueError):r1cs_header(io.BytesIO(data),len(data))
        def test_existing_eligible_not_random_sampled(self):
            old,new,first=self.fixtures();old['79']['inspection_eligible']=True;first['79']['inspection_eligible']=True
            rows,_=choose_rows(old,new,first,{'T'})
            self.assertNotIn('79',[row['label'] for row in rows])
        def receipt_fixture(self, stop_reason=None, status="completed"):
            directory=OUTPUT/'results'/'0000-unit'
            target={'unit':'unit','label':'label','template':'T','compiler_sha256':'compiler-sha',
                    'wrapper_sha256':'wrapper-sha','compiler':'/circom',
                    'definition':{'entrypoint':str(ROOT/'fixture.circom'),'prime':'bn128','compile_args':[]}}
            selection={'path':str(OUTPUT/'selection.json'),'sha256':'selection-sha'}
            receipt={'unit':'unit','label':'label','template':'T','compiler_sha256':'compiler-sha',
                     'wrapper_sha256':'wrapper-sha','wrapper':str(ROOT/'fixture.circom'),'selection':selection,
                     'argv':compile_argv('/circom',target['definition'],directory/'artifacts'),
                     'returncode':-15 if stop_reason else 0,'stop_reason':stop_reason,'completion_status':status,
                     'compile_success':stop_reason is None,'elapsed_seconds':1.0,
                     'stdout':{'path':str(directory/'stdout.log'),'sha256':'log-sha','bytes':0},
                     'stderr':{'path':str(directory/'stderr.log'),'sha256':'log-sha','bytes':0}}
            return directory,target,selection,receipt
        def test_resume_receipt_bindings(self):
            directory,target,selection,receipt=self.receipt_fixture()
            self.assertEqual(validate_receipt_bindings(receipt,target,selection,directory),'completed')
            for key in ('unit','label','template','wrapper','wrapper_sha256','compiler_sha256','selection','argv'):
                changed={**receipt,key:'changed'}
                with self.assertRaises(ValueError):validate_receipt_bindings(changed,target,selection,directory)
        def test_timeout_is_terminal_not_retried(self):
            directory,target,selection,receipt=self.receipt_fixture('compile_timeout')
            self.assertEqual(validate_receipt_bindings(receipt,target,selection,directory),'completed')
        def test_interrupted_request_remains_pending(self):
            directory,target,selection,receipt=self.receipt_fixture('interrupted','pending')
            self.assertEqual(validate_receipt_bindings(receipt,target,selection,directory),'pending')
        def test_completed_receipt_without_exit_rejected(self):
            directory,target,selection,receipt=self.receipt_fixture();receipt['returncode']=None
            with self.assertRaises(ValueError):validate_receipt_bindings(receipt,target,selection,directory)
        def test_resume_skips_verified_completed_request(self):
            from unittest import mock
            from types import SimpleNamespace
            directory,target,selection,receipt=self.receipt_fixture('compile_timeout')
            path=directory/'result.json'
            with mock.patch.object(Path,'is_file',lambda p:p==path),mock.patch.object(Path,'exists',lambda p:False),mock.patch.object(Path,'stat',lambda p:SimpleNamespace(st_size=0)),mock.patch.dict(globals(),{'read_json':lambda p:(receipt,{}),'digest':lambda p:'log-sha'}):
                complete,checked,next_attempt=existing_target_result(directory,target,selection)
            self.assertIsNotNone(complete);self.assertEqual(len(checked),1);self.assertEqual(next_attempt,1)
        def test_resume_rejects_changed_log(self):
            from unittest import mock
            from types import SimpleNamespace
            directory,target,selection,receipt=self.receipt_fixture()
            path=directory/'result.json'
            with mock.patch.object(Path,'is_file',lambda p:p==path),mock.patch.object(Path,'exists',lambda p:False),mock.patch.object(Path,'stat',lambda p:SimpleNamespace(st_size=0)),mock.patch.dict(globals(),{'read_json':lambda p:(receipt,{}),'digest':lambda p:'changed'}):
                with self.assertRaises(ValueError):existing_target_result(directory,target,selection)
        def monitor_fixture(self, exception=None):
            class Process:
                pid=314159
                returncode=None
                first=True
                def poll(self):
                    if self.first and exception:
                        self.first=False
                        raise exception
                    return self.returncode
                def wait(self,timeout=None):
                    self.returncode=-15
                    return self.returncode
            return Process()
        def test_keyboard_interrupt_reaps_only_owned_child(self):
            from unittest import mock
            process=self.monitor_fixture(KeyboardInterrupt())
            with mock.patch.object(os,'killpg') as killed:
                result=monitor_child(process,[],Path('/unused-out'),Path('/unused-err'),0,0,60,1800,512)
            self.assertEqual(result['stop_reason'],'interrupted');self.assertTrue(result['own_child_reaped'])
            killed.assert_called_once_with(process.pid,signal.SIGTERM)
        def test_monitoring_error_reaps_only_owned_child(self):
            from unittest import mock
            process=self.monitor_fixture()
            with mock.patch.object(os,'killpg') as killed,mock.patch.object(shutil,'disk_usage',side_effect=OSError('synthetic monitor failure')):
                result=monitor_child(process,[],Path('/unused-out'),Path('/unused-err'),0,0,60,1800,512)
            self.assertEqual(result['stop_reason'],'monitoring_error');self.assertTrue(result['own_child_reaped'])
            killed.assert_called_once_with(process.pid,signal.SIGTERM)
        def test_compile_command(self):
            definition={'prime':'bn128','entrypoint':str(ROOT/'fixture.circom'),'compile_args':['-l',str(ROOT)]}
            command=compile_argv('/circom',definition,OUTPUT/'artifact')
            self.assertEqual(command[2:5],['--r1cs','--prime','bn128']);self.assertNotIn('--sym',command)
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    if not result.wasSuccessful():raise SystemExit(1)


def main():
    guard()
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('select');s.add_argument('--before',required=True);s.add_argument('--round1',required=True);s.add_argument('--after',required=True)
    s.add_argument('--prepared-summary',default=str(SUMMARY));s.add_argument('--mapping',default=str(MAPPING));s.add_argument('--output',default=str(OUTPUT))
    s.add_argument('--sample-count',type=int,default=50);s.add_argument('--seed',type=int,default=SEED)
    r=sub.add_parser('run');r.add_argument('--output',default=str(OUTPUT));r.add_argument('--timeout-seconds',type=int,default=60)
    r.add_argument('--max-runtime-seconds',type=int,default=1800);r.add_argument('--max-artifact-mib',type=int,default=512)
    sub.add_parser('self-test');args=p.parse_args()
    if args.command=='select' and (args.sample_count!=50 or args.seed!=SEED):p.error('this check freezes 50 samples per unit and seed 20261027')
    {'select':select,'run':run,'self-test':lambda _:self_test()}[args.command](args)


if __name__=='__main__':main()
