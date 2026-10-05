#!/usr/bin/env python3
"""C-02 compile/discovery census. Never invokes a search or candidate-review path.

Inputs are the frozen procedure/tool locks and collected repository metadata.
Every entrypoint gets its own immutable result; resume skips existing results.
Raw tool stdout/stderr and generated artifacts stay under ignored runs/.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/c02-corpus-2026-10-02"


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def reference(path):
    path = Path(path)
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}


def write_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def session_members(session_id):
    # Compiler children create their own process groups, but inherit our new session.
    # Require process inspection before launching anything; group-only cleanup is unsafe.
    listing = subprocess.check_output(["/bin/ps", "-axo", "pid="], text=True, stderr=subprocess.PIPE)
    members = []
    for token in listing.split():
        pid = int(token)
        try:
            if os.getsid(pid) == session_id:
                members.append(pid)
        except ProcessLookupError:
            pass
    return members


def cleanup_session(session_id):
    if session_id == os.getsid(0):
        raise ValueError("refuse to clean caller session")
    killed = set()
    for _ in range(10):
        members = session_members(session_id)
        if not members:
            return sorted(killed)
        for pid in members:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.add(pid)
            except ProcessLookupError:
                pass
        time.sleep(0.05)
    # Zombies cannot execute and are reaped by their parent/init; report all signaled PIDs.
    return sorted(killed)


def run_command(argv, directory, cap, cwd=ROOT):
    """Bound parent and descendants; preserve even unsuccessful raw output."""
    session_members(os.getsid(0))  # Fail before launch if process inspection is forbidden.
    directory.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    result = {"argv": list(map(str, argv)), "started_at": now(), "cap_seconds": cap,
              "status": "start_failure", "exit_code": None, "process_started": False}
    with (directory / "stdout.log").open("wb") as out, (directory / "stderr.log").open("wb") as err:
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdout=out, stderr=err,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
            result["process_started"] = True
            try:
                result["exit_code"] = process.wait(timeout=cap)
                result["status"] = "success" if process.returncode == 0 else "failure"
            except subprocess.TimeoutExpired:
                result["cleanup_signaled_pids"] = cleanup_session(process.pid)
                result["exit_code"] = process.wait()
                result["status"] = "timeout"
            cleanup_start = time.monotonic()
            result["post_exit_cleanup_signaled_pids"] = cleanup_session(process.pid)
            result["post_exit_cleanup_seconds"] = time.monotonic() - cleanup_start
        except OSError as error:
            result["reason"] = str(error)
    result.update(finished_at=now(), elapsed_seconds=time.monotonic() - start)
    result["stdout"] = reference(directory / "stdout.log")
    result["stderr"] = reference(directory / "stderr.log")
    write_new(directory / "invocation.json", result)
    return result


def brief(capture):
    return {key: value for key, value in capture.items() if key != "argv"}


def failure_type(capture):
    if capture["status"] != "failure":
        return None if capture["status"] == "success" else capture["status"]
    text = "\n".join((ROOT / capture[key]["path"]).read_text(errors="replace")
                     for key in ("stdout", "stderr"))
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text).lower()
    for label, patterns in [
        ("missing_include", ["could not be found", "cannot find", "could not open", "no such file", "include resolution"]),
        ("compiler_version", ["compiler version", "circom version", "pragma circom"]),
        ("non_quadratic", ["non quadratic", "non-quadratic"]),
        ("syntax_or_parse", ["unrecognized token", "unexpected token", "parse error"]),
        ("assertion_or_type", ["assert", "typing error", "type error", "invalid assignment", "uninitialized"]),
    ]:
        if any(pattern in text for pattern in patterns):
            return label
    return "compiler_or_tool_error"


def r1cs_count(path):
    """Read only the R1CS header, not witness values or constraint expressions."""
    with Path(path).open("rb") as handle:
        if handle.read(4) != b"r1cs":
            raise ValueError("invalid R1CS magic")
        version, sections = struct.unpack("<II", handle.read(8))
        if version != 1:
            raise ValueError("unsupported R1CS version")
        for _ in range(sections):
            kind, length = struct.unpack("<IQ", handle.read(12))
            if kind == 1:
                field_bytes = struct.unpack("<I", handle.read(4))[0]
                if length != field_bytes + 32:
                    raise ValueError("invalid R1CS header length")
                handle.seek(field_bytes + 24, 1)
                return struct.unpack("<I", handle.read(4))[0]
            handle.seek(length, 1)
    raise ValueError("R1CS header missing")


def parse_instance(key):
    if not key or "::" not in key:
        raise ValueError("concrete root instance key unavailable")
    call = key.rsplit("::", 1)[1]
    match = re.fullmatch(r"([A-Za-z_$][\w$]*)\((.*)\)", call)
    if not match:
        raise ValueError("concrete instance key unsupported")
    # The existing discovery engine emits concrete signed integer parameters.
    params = [part.strip() for part in match[2].split(",")] if match[2].strip() else []
    if any(not re.fullmatch(r"-?\d+", parameter) for parameter in params):
        raise ValueError("noninteger concrete instance parameter unsupported; no guessing")
    return match[1], params


def manifest_for(repo, entrypoint, discovery, libraries):
    definitions = [("root", entrypoint, discovery.get("root_instance_key"), "original")]
    seen = set()
    for unit in discovery.get("compile_units", []):
        if unit["key"] in seen:
            raise ValueError("duplicate compile-unit key")
        seen.add(unit["key"])
        definitions.append((unit["key"], unit["wrapper_path"], unit["instance_key"], "direct"))
    targets = []
    for label, source, key, mode in definitions:
        template, parameters = parse_instance(key)
        targets.append({"label": label, "project": repo["full_name"], "revision": repo["commit_sha"],
                        "project_root": repo["checkout_path"], "entrypoint": str(source),
                        "template_name": template, "concrete_parameters": parameters, "prime": "bn128",
                        "compile_args": [item for lib in libraries for item in ("-l", str(lib))],
                        "mode": mode, "input_assumptions": "Preparation only; semantic input domain unreviewed.",
                        "known_defects": []})
    return {"schema_version": 1, "name": "c02-" + hashlib.sha256(str(entrypoint).encode()).hexdigest()[:16],
            "description": "Compile/discovery applicability only; no search.", "targets": targets, "exclusions": []}


def preparation_status(discovery, prepared, plan, expected_targets):
    if prepared is None:
        return "failed"
    eligible = sum(target["eligible"] for target in prepared["targets"])
    all_wrappers = all(target["wrapper_status"] == "compile_succeeded"
                       for target in discovery.get("targets", []))
    complete = (plan["status"] == "success" and eligible == expected_targets
                and len(prepared["targets"]) == expected_targets and expected_targets > 0
                and not discovery.get("unsupported") and all_wrappers
                and discovery.get("entrypoint_status") == "found")
    return "success" if complete else "partial" if eligible else "failed"


def locate_report(directory, name):
    paths = list(Path(directory).rglob(name))
    if len(paths) > 1:
        raise ValueError("ambiguous generated report paths; refuse arbitrary selection")
    return paths[0] if paths else None


def complete_preparation(result, repo, entrypoint, discovery_path, directory, libraries):
    compiler = RUN / "tools/circom"
    frontend = RUN / "tools/zkfDO"
    discovery = json.loads(discovery_path.read_text())
    result["discovery"].update(report=reference(discovery_path),
                               entrypoint_status=discovery["entrypoint_status"],
                               callsites=len(discovery["targets"]), unique_compile_units=len(discovery["compile_units"]),
                               compiler_processes=discovery["compile_process_count"],
                               unsupported=[{key: value for key, value in row.items() if key != "construct"}
                                            for row in discovery["unsupported"]],
                               callsite_wrapper_statuses=[row["wrapper_status"] for row in discovery["targets"]])
    try:
        manifest = manifest_for(repo, entrypoint, discovery, libraries)
    except ValueError as error:
        result["preparation"] = {"status": "unsupported", "reason": str(error)}
    else:
        manifest_path = directory / "manifest.json"
        write_new(manifest_path, manifest)
        prepared_dir = directory / "prepared"
        capture = run_command([str(frontend), "experiment", "prepare", "--manifest", str(manifest_path),
                               "--output", str(prepared_dir), "--strategy", "small-first",
                               "--circom-bin", str(compiler), "--zkfuzz-bin", "/nonexistent/c02-zkfuzz-forbidden",
                               "--circomspect-bin", "/nonexistent/c02-analyzer-forbidden",
                               "--tool-timeout-seconds", "60"], directory / "prepare-call", 300)
        result["preparation"] = brief(capture)
        result["preparation"].update(manifest=reference(manifest_path), failure_type=failure_type(capture),
                                     expected_targets=len(manifest["targets"]))
        try:
            prepared_path = locate_report(prepared_dir, "prepared.json")
        except ValueError as error:
            result["preparation"].update(status="unknown", reason=str(error))
            return
        if capture["status"] == "success" and prepared_path is None:
            result["preparation"].update(status="unknown", reason="successful prepare left no prepared report")
            return
        if capture["status"] == "success" and prepared_path is not None:
            try:
                prepared = json.loads(prepared_path.read_text())
                actual = prepared["targets"]
                if len(actual) != len(manifest["targets"]):
                    raise ValueError("prepared target count mismatch")
                expected = {item["label"]: item for item in manifest["targets"]}
                definitions = [item["definition"] for item in actual]
                if len({item["label"] for item in definitions}) != len(definitions):
                    raise ValueError("duplicate prepared target labels")
                for definition in definitions:
                    original = expected[definition["label"]]
                    if any(definition.get(key) != value for key, value in original.items()):
                        raise ValueError("prepared target identity mismatch")
            except (ValueError, KeyError, TypeError) as error:
                result["preparation"].update(status="unknown", reason=str(error), report=reference(prepared_path))
                return
            targets = []
            for target in prepared["targets"]:
                structure = target.get("structure") or {}
                if structure.get("ast_requested") or (structure.get("zkfuzz_version") or {}).get("requested"):
                    raise RuntimeError("forbidden frontend request in compile-only report")
                targets.append({"label": target["definition"]["label"], "eligible": target["eligible"],
                                "exclusion_reasons": target["exclusion_reasons"], "constraints": structure.get("size"),
                                "compile_seconds": (structure.get("compile") or {}).get("elapsed_seconds"),
                                "compiler_started": (structure.get("compile") or {}).get("process_started"),
                                "elapsed_seconds": target["elapsed_seconds"]})
            result["preparation"].update(report=reference(prepared_path), targets=targets,
                                         eligible=sum(row["eligible"] for row in targets))
            plan = run_command([str(frontend), "experiment", "plan", "--prepared", str(prepared_path),
                                "--strategy", "small-first", "--config", str(ROOT / "configs/static-ranking.json"),
                                "--output", str(directory / "plan.json")], directory / "plan-call", 30)
            result["plan"] = brief(plan)
            if plan["status"] == "success" and not (directory / "plan.json").is_file():
                plan = dict(plan, status="unknown")
                result["plan"].update(status="unknown", reason="successful plan left no plan artifact")
            result["preparation"]["status"] = preparation_status(discovery, prepared, plan, len(manifest["targets"]))
            if (directory / "plan.json").exists():
                result["plan"]["report"] = reference(directory / "plan.json")


def discover_and_prepare(result, repo, entrypoint, directory, libraries):
    compiler = RUN / "tools/circom"
    frontend = RUN / "tools/zkfDO"
    checkout = Path(repo["checkout_path"])
    discovery_dir = directory / "discovery"
    command = [str(frontend), "targets", "--project", str(checkout), "--entrypoint", str(entrypoint),
               "--output", str(discovery_dir), "--circom-bin", str(compiler), "--compile-timeout-seconds", "60"]
    for path in libraries:
        command.extend(["--library-path", str(path)])
    capture = run_command(command, directory / "discover-call", 300)
    result["discovery"] = brief(capture)
    result["discovery"]["failure_type"] = failure_type(capture)
    discovery_path = locate_report(discovery_dir, "discovery.json")
    result["preparation"] = {"status": "not_started", "reason": "discovery report unavailable"}
    if capture["status"] == "success" and discovery_path is not None:
        complete_preparation(result, repo, entrypoint, discovery_path, directory, libraries)


def measure(repo, item):
    relative = item["path"] if isinstance(item, dict) else item
    checkout = Path(repo["checkout_path"])
    entrypoint = checkout / relative
    identifier = hashlib.sha256((repo["full_name"].lower() + "\0" + relative).encode()).hexdigest()[:24]
    directory = RUN / "measurements" / identifier
    result_path = directory / "result.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    if directory.exists():
        raise RuntimeError(f"unfinished measurement preserved; do not silently retry: {directory}")
    directory.mkdir(parents=True)
    result = {"schema_version": 1, "repository": repo["full_name"], "commit_sha": repo["commit_sha"],
              "entrypoint": relative, "source_sha256": digest(entrypoint), "started_at": now(),
              "manual_interventions": 0, "zkfuzz_executions": 0,
              "settings": {"optimization": "compiler_default_O1", "prime": "bn128"}}
    compiler = RUN / "tools/circom"
    frontend = RUN / "tools/zkfDO"
    libraries = [path for path in [checkout, checkout / "node_modules", checkout / "node_modules/circomlib/circuits"] if path.is_dir()]
    result["library_paths"] = list(map(str, libraries))
    original = directory / "original"
    original.mkdir()
    command = [str(compiler), str(entrypoint), "--r1cs", "-o", str(original)]
    for path in libraries:
        command.extend(["-l", str(path)])
    capture = run_command(command, directory / "compile", 120)
    result["compile"] = brief(capture)
    result["compile"]["failure_type"] = failure_type(capture)
    result["compile"]["constraints"] = None
    if capture["status"] == "success":
        try:
            artifacts = list(original.glob("*.r1cs"))
            if len(artifacts) != 1:
                raise ValueError("successful compiler did not leave exactly one R1CS")
            result["compile"].update(constraints=r1cs_count(artifacts[0]), artifact=reference(artifacts[0]))
        except (OSError, ValueError, struct.error) as error:
            result["compile"]["count_unknown_reason"] = str(error)
    discover_and_prepare(result, repo, entrypoint, directory, libraries)
    result["finished_at"] = now()
    write_new(result_path, result)
    print(json.dumps({"repo": repo["full_name"], "entrypoint": relative, "compile": result["compile"]["status"],
                      "constraints": result["compile"]["constraints"], "prepare": result["preparation"]["status"]}), flush=True)
    return result


def repair(repo, item):
    """Continue the uniformly missing prepare stage without rerunning earlier tools."""
    relative = item["path"] if isinstance(item, dict) else item
    identifier = hashlib.sha256((repo["full_name"].lower() + "\0" + relative).encode()).hexdigest()[:24]
    directory = RUN / "measurements" / identifier
    original_path = directory / "result.json"
    result_path = directory / "result-v2.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    if not original_path.exists():
        return measure(repo, item)
    result = json.loads(original_path.read_text())
    if result["preparation"]["status"] != "not_started" or result["discovery"]["status"] not in ("success", "interrupted"):
        return result
    discovery_path = locate_report(directory / "discovery", "discovery.json")
    if discovery_path is None and result["discovery"]["status"] != "interrupted":
        return result
    entrypoint = Path(repo["checkout_path"]) / relative
    if result["commit_sha"] != repo["commit_sha"] or digest(entrypoint) != result["source_sha256"]:
        raise ValueError("source identity changed; cannot continue old preparation")
    result["supersedes"] = reference(original_path)
    result["repair"] = {"reason": "adapter previously missed UUID subdirectory; reuse compiler/discovery records and start missing preparation only",
                        "started_at": now(), "rerun_compile": False, "rerun_discovery": False}
    new_directory = directory / "repair-v2"
    new_directory.mkdir(exist_ok=False)
    if result["discovery"]["status"] == "interrupted":
        result["repair"]["reason"] = "Resume both controller-interrupted discovery stages uniformly after session cleanup fix; reuse successful original compile"
        result["repair"]["rerun_discovery"] = True
        discover_and_prepare(result, repo, entrypoint, new_directory, result["library_paths"])
    else:
        complete_preparation(result, repo, entrypoint, discovery_path, new_directory, result["library_paths"])
    result["finished_at"] = now()
    write_new(result_path, result)
    print(json.dumps({"repo": repo["full_name"], "entrypoint": relative, "repair": True,
                      "prepare": result["preparation"]["status"]}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repositories", type=Path, help="collected repository JSON or directory with --watch")
    parser.add_argument("--watch", action="store_true", help="consume atomic per-repository metadata while collection runs")
    parser.add_argument("--repair", action="store_true", help="continue uniformly missing preparation using preserved earlier invocations")
    args = parser.parse_args()
    lock = json.loads((RUN / "tool-lock.json").read_text())
    for tool in lock["tools"]:
        if digest(tool["path"]) != tool["sha256"]:
            raise RuntimeError("fixed tool changed")
    procedure = json.loads((RUN / "procedure-lock.json").read_text())
    if digest(ROOT / procedure["procedure_path"]) != procedure["sha256"]:
        raise RuntimeError("fixed procedure changed")
    def normalized(repo):
        result = dict(repo)
        result["checkout_path"] = str((ROOT / repo["clone_path"]).resolve())
        result["inclusion_status"] = repo["inclusion"]["status"]
        return result

    submitted = set()
    pending = set()
    with ThreadPoolExecutor(max_workers=2) as executor:
        while True:
            if args.watch:
                repos = [json.loads(path.read_text()) for path in sorted(args.repositories.glob("*/metadata.json"))]
                collection_complete = (RUN / "repositories.json").exists()
            else:
                repos = json.loads(args.repositories.read_text())
                if isinstance(repos, dict):
                    repos = repos["repositories"]
                collection_complete = True
            for source_repo in repos:
                repo = normalized(source_repo)
                if repo["inclusion_status"] != "included":
                    continue
                for item in repo["entrypoints"]:
                    key = (repo["full_name"].lower(), item["path"])
                    if key not in submitted:
                        submitted.add(key)
                        pending.add(executor.submit(repair if args.repair else measure, repo, item))
            if pending:
                completed, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                for future in completed:
                    future.result()
            elif collection_complete:
                break
            else:
                time.sleep(1)


if __name__ == "__main__":
    main()
