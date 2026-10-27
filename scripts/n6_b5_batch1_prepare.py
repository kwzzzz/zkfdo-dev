#!/usr/bin/env python3
"""Prepare B batch 1 through two format-only J pilots; never print verdicts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import sys
from typing import Any

import n6_j3_b_pilot_wait4 as b_pilot
import n6_j1_requests as requests
import run_n6_j1 as runner
from n6_b5_j_adapter import (ENGINE_V1, ENGINE_V1_SHA, ENGINE_V22,
                             ENGINE_V22_SHA, verify_mem20)


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-b5-2026-10-17.noindex"
OUT = RUN / "batch1-prep.noindex"
MANIFEST = ROOT / "runs/n6-j3-2026-10-14.noindex/revision-manifest.json"
INVENTORY = ROOT / "runs/n6-j3-2026-10-14.noindex/candidate-inventory.json"
QUEUE = ROOT / "runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json"
R1CS_MAP = RUN / "b-r1cs-reference-v2.json"
TOOLS = RUN / "install-tools.json"
COLLECTOR = ROOT / "scripts/n6_b5_docker_base_inputs.py"
ADAPTER = ROOT / "scripts/n6_b5_j_adapter.py"
FORMAT_PILOT = ROOT / "scripts/n6_b5_format_pilot.py"
COLLECTOR_SHA = "dd1a51bee722f7ca4868f3e9ec42982a12bf6e00c362c87cdb8175fbe55a440b"
TOOLS_SHA = "0daf78af39e06dddb1776cf1f4b1ffd875a26054e2cd4d5c39c8f52560de4688"
R1CS_MAP_SHA = "b1e3e893ef7163f1918fb9a144bf368b2a0fb20b85cd975366da32352391a79b"
BASE = RUN / "b-base-inputs/index.json"
PLAN = OUT / "request-index-pending.json"
INDEX_V1 = OUT / "request-index-v1.json"
INDEX_V22 = OUT / "request-index-v2.2.json"
REQUESTS = OUT / "requests"
SELECTION = OUT / "pilot-selection.json"
ENTRYPOINTS = OUT / "entrypoint-classification.json"
MIN_FREE = runner.MIN_FREE_BYTES


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


class StageFailure(RuntimeError):
    def __init__(self, details: dict[str, Any]):
        super().__init__("stage failed; attempt evidence saved")
        self.details = details


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_new(path: Path, value: Any) -> str:
    require(not path.exists(), f"refuse to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return sha256(path)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(name: str) -> Path:
    return OUT / "stages" / name / "state.json"


def save_state(name: str, value: dict[str, Any]) -> None:
    path = state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def stage(name: str, action, verify_completed) -> dict[str, Any]:
    path = state_path(name)
    if path.exists():
        previous = read_json(path)
        if previous.get("status") == "completed":
            try:
                require(previous.get("exit_code") == 0,
                        f"completed {name} stage has a nonzero exit code")
                verify_completed(previous)
            except Exception:
                print(f"{name}: exit_code=1 format_ok=0; completed state recheck failed",
                      flush=True)
                raise
            print(f"{name}: exit_code=0 format_ok=1 (saved)", flush=True)
            return previous
        history = path.parent / "prior-attempts"
        history.mkdir(exist_ok=True)
        attempt = len(list(history.glob("state-*.json"))) + 1
        path.replace(history / f"state-{attempt:03d}.json")
    state: dict[str, Any] = {"schema_version": 1, "stage": name,
                             "status": "running", "started_at": stamp()}
    save_state(name, state)
    try:
        details = action() or {}
        state.update(details)
        state["status"] = "completed"
        state["exit_code"] = 0
        state["completed_at"] = stamp()
        save_state(name, state)
        print(f"{name}: exit_code=0 format_ok=1", flush=True)
        return state
    except Exception as error:
        if isinstance(error, StageFailure):
            state.update(error.details)
        state["status"] = "failed"
        state["exit_code"] = 1
        state["error_type"] = type(error.__cause__ or error).__name__
        state["completed_at"] = stamp()
        save_state(name, state)
        print(f"{name}: exit_code=1 format_ok=0; review {path}", flush=True)
        raise


def logged_command(name: str, command: list[str]) -> int:
    directory = OUT / "stages" / name
    directory.mkdir(parents=True, exist_ok=True)
    attempt = len(list(directory.glob("command-*.log"))) + 1
    log = directory / f"command-{attempt:03d}.log"
    with log.open("x") as stream:
        process = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                 check=False)
    return process.returncode


def preflight(cache_parent: Path) -> dict[str, Any]:
    verify_mem20()
    require(cache_parent.is_absolute() and cache_parent.is_dir(),
            "cache parent must be an existing absolute directory")
    require(not cache_parent.is_relative_to(OUT) and not OUT.is_relative_to(cache_parent),
            "cache parent and B output must be separate")
    require(not cache_parent.is_relative_to(ROOT) and
            os.stat(cache_parent).st_dev != os.stat(ROOT).st_dev,
            "J cache parent must be on a separate external volume")
    checked = {}
    for label, path in (("repository", ROOT), ("cache", cache_parent)):
        free = shutil.disk_usage(path).free
        checked[label] = free
        require(free >= MIN_FREE,
                f"{label} below 40 GiB; review old ignored runs caches or unused Docker "
                "build cache/images and retry; this command deletes nothing")
    require(runner.ENGINE == ENGINE_V1 and runner.ENGINE_SHA256 == ENGINE_V1_SHA and
            sha256(ENGINE_V1) == ENGINE_V1_SHA, "N5 v1 engine lock mismatch")
    require(sha256(ENGINE_V22) == ENGINE_V22_SHA, "v2.2 engine hash mismatch")
    require(sha256(runner.CIRCOM) == runner.CIRCOM_SHA256, "circom hash mismatch")
    require(all(path.is_file() for path in (MANIFEST, INVENTORY, QUEUE, R1CS_MAP,
                                             TOOLS, COLLECTOR, ADAPTER, FORMAT_PILOT)),
            "required B preparation input missing")
    require(sha256(COLLECTOR) == COLLECTOR_SHA and sha256(TOOLS) == TOOLS_SHA and
            sha256(R1CS_MAP) == R1CS_MAP_SHA,
            "B collector, install tools, or fuzz R1CS reference changed")
    rc = logged_command("preflight", ["docker", "info"])
    require(rc == 0, "Docker Desktop unavailable; turn it on and run the same command")
    df_rc = logged_command("preflight-docker-df", ["docker", "system", "df"])
    require(df_rc == 0, "docker system df failed; inspect its stage log")
    return {"disk_free_bytes": checked, "docker_info_exit_code": rc,
            "docker_system_df_exit_code": df_rc,
            "v1_engine_sha256": runner.ENGINE_SHA256,
            "v2_2_engine_sha256": ENGINE_V22_SHA,
            "collector_sha256": COLLECTOR_SHA,
            "install_tools_sha256": TOOLS_SHA,
            "b_r1cs_reference_sha256": R1CS_MAP_SHA,
            "orchestrator_sha256": sha256(Path(__file__)),
            "adapter_sha256": sha256(ADAPTER),
            "format_pilot_sha256": sha256(FORMAT_PILOT)}


def verify_preflight_completed(saved: dict[str, Any], cache_parent: Path) -> None:
    current = preflight(cache_parent)
    stable = ("v1_engine_sha256", "v2_2_engine_sha256", "collector_sha256",
              "install_tools_sha256", "b_r1cs_reference_sha256",
              "orchestrator_sha256", "adapter_sha256", "format_pilot_sha256")
    require(all(saved.get(key) == current[key] for key in stable),
            "completed preflight source or tool hash changed")
    require(saved.get("docker_info_exit_code") == 0 and
            saved.get("docker_system_df_exit_code") == 0,
            "completed preflight lacks successful Docker checks")


def collect_base_inputs() -> dict[str, Any]:
    require(shutil.disk_usage(ROOT).free >= MIN_FREE,
            "less than 40 GiB before B collection; review old ignored runs caches or "
            "unused Docker build cache/images; this command deletes nothing")
    command = [sys.executable, str(COLLECTOR), "--scope", "B",
               "--manifest", str(MANIFEST), "--r1cs-map", str(R1CS_MAP),
               "--tools", str(TOOLS), "--output-root", str(BASE.parent)]
    rc = logged_command("base-inputs", command)
    require(rc == 0, "B base-input collector stopped; inspect its stage log")
    return base_input_summary()


def base_input_summary() -> dict[str, Any]:
    index = read_json(BASE)
    manifest = read_json(MANIFEST)
    revisions = index.get("revisions")
    ids = {row["identifier"] for row in manifest["rows"]}
    require(index.get("schema") == "n6-j1-base-inputs-v1" and
            isinstance(revisions, dict) and set(revisions) == ids and len(ids) == 10,
            "B base-input index must cover all 10 revisions")
    require(index.get("manifest_sha256") == sha256(MANIFEST) and
            index.get("r1cs_map_sha256") == sha256(R1CS_MAP) and
            index.get("tools_sha256") == sha256(TOOLS),
            "B base-input index input hash changed")
    for record in revisions.values():
        require(record.get("status") in {"passed", "base_input_unavailable"},
                "invalid B base-input status")
        if record["status"] == "passed":
            path = Path(record["base_input_path"])
            require(path.is_file() and sha256(path) == record["base_input_sha256"],
                    "B base-input hash mismatch")
        else:
            require(record.get("base_input_path") is None and
                    record.get("base_input_sha256") is None,
                    "unavailable B base input unexpectedly has a path")
    return {"index": str(BASE), "index_sha256": sha256(BASE),
            "revision_count": len(revisions)}


def verify_base_completed(saved: dict[str, Any]) -> None:
    current = base_input_summary()
    require(all(saved.get(key) == value for key, value in current.items()),
            "completed B base-input stage hash or count changed")


def git_output(repository: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repository), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout


def tracked_blobs(repository: Path, commit: str) -> dict[str, int]:
    """List only paths and sizes in the recorded revision, not the runs tree."""
    require(re.fullmatch(r"[0-9a-fA-F]{40}", commit) is not None,
            "invalid recorded revision commit")
    top = Path(git_output(repository, "rev-parse", "--show-toplevel").decode().strip())
    require(top.resolve() == repository.resolve(),
            "recorded revision repository path is not its Git root")
    result: dict[str, int] = {}
    for entry in git_output(repository, "ls-tree", "-r", "-z", "-l", commit).split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, _object_id, size = metadata.split()
        if kind != b"blob" or size == b"-":
            continue
        try:
            path = name.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if mode not in {b"100644", b"100755"}:
            continue
        result[path] = int(size)
    return result


def reference_documents(blobs: dict[str, int], relative: Path) -> list[str]:
    """Select likely build/deploy evidence from tracked revision paths only."""
    ancestors = {"."}
    current = Path(".")
    for part in relative.parts[:-1]:
        current = current / part
        ancestors.add(current.as_posix())
    blocked = {"runs", "node_modules", "vendor", "dist", "test", "tests",
               "mock", "mocks", "example", "examples", "fixtures"}
    extensions = {".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs",
                  ".ts", ".tsx", ".py", ".json", ".yml", ".yaml"}
    chosen = []
    for raw, size in blobs.items():
        if size > 2_000_000:
            continue
        path = Path(raw)
        if any(part.casefold() in blocked for part in path.parts[:-1]):
            continue
        name = path.name.casefold()
        if name.startswith("readme") and path.parent.as_posix() in ancestors:
            chosen.append(raw)
        elif name == "package.json" or name in {"makefile", "gnumakefile", "justfile"}:
            chosen.append(raw)
        elif (path.suffix.casefold() in extensions and
              not re.search(r"test|mock|example|fixture", name, re.I) and any(
                re.search(r"build|deploy|verifier|compile", part, re.I)
                for part in path.parts)):
            chosen.append(raw)
    return sorted(set(chosen))


def line_references_main(line: str, document: str, relative: Path) -> bool:
    full = relative.as_posix()
    boundary = r"[\w./-]"
    if re.search(rf"(?<!{boundary}){re.escape(full)}(?!{boundary})", line, re.I):
        return True
    same_directory = Path(document).parent == relative.parent
    if same_directory and re.search(
            rf"(?<!{boundary}){re.escape(relative.name)}(?!{boundary})", line, re.I):
        return True
    for match in re.finditer(r"(?<![\w])(?:\.{1,2}/)*[\w./@-]+\.circom", line, re.I):
        mentioned = match.group()
        for base in ("", Path(document).parent.as_posix()):
            if posixpath.normpath(posixpath.join(base, mentioned)) == full:
                return True
    return False


def direct_reference(repository: Path, commit: str,
                     relative: Path) -> dict[str, Any] | None:
    blobs = tracked_blobs(repository, commit)
    require(relative.as_posix() in blobs,
            "entrypoint is missing from recorded revision")
    for raw in reference_documents(blobs, relative):
        blob = git_output(repository, "show", f"{commit}:{raw}")
        require(len(blob) == blobs[raw], "recorded Git blob size changed")
        text = blob.decode("utf-8", errors="replace")
        if Path(raw).name == "package.json":
            try:
                scripts = json.loads(text).get("scripts", {})
            except ValueError:
                continue
            if not isinstance(scripts, dict):
                continue
            valid = [command for name, command in scripts.items()
                     if isinstance(command, str) and
                     re.search(r"build|deploy|verifier|compile", name, re.I) and
                     not re.search(r"test|mock|example", name, re.I)]
            if not valid:
                continue
            lines = ((number, line) for number, line in enumerate(text.splitlines(), 1)
                     if any(command in line for command in valid))
        else:
            lines = enumerate(text.splitlines(), 1)
        for line_number, line in lines:
            if line_references_main(line, raw, relative):
                return {"file": str(repository / raw), "file_relative": raw,
                        "line": line_number,
                        "file_sha256": hashlib.sha256(blob).hexdigest(),
                        "revision_commit": commit, "source": "recorded_git_revision"}
    return None


def source_relationship(recorded: bytes, snapshot: bytes) -> str:
    if recorded == snapshot:
        return "byte_identical"
    recorded_lines = recorded.splitlines(keepends=True)
    snapshot_lines = snapshot.splitlines(keepends=True)
    changed = [(before, after) for before, after in zip(recorded_lines, snapshot_lines)
               if before != after]
    pragma = rb"\s*pragma\s+circom\s+[0-9]+(?:\.[0-9]+)*\s*;\s*"
    if (len(recorded_lines) == len(snapshot_lines) and len(changed) == 1 and
            re.fullmatch(pragma, changed[0][0]) and
            re.fullmatch(pragma, changed[0][1])):
        return "pragma_only"
    return "other_source_difference"


def classify_entrypoints() -> dict[str, Any]:
    rows = []
    for item in read_json(MANIFEST)["rows"]:
        root = Path(item["project_root"]).resolve()
        relative = Path(item["entrypoint_relative"])
        require(not relative.is_absolute() and ".." not in relative.parts,
                "entrypoint path escapes project")
        entrypoint = root / relative
        require(entrypoint.is_file() and sha256(entrypoint) == item["entrypoint_sha256"],
                "entrypoint SHA mismatch")
        harness_directory = any(part.casefold() in {
            "test", "tests", "mock", "mocks", "example", "examples", "fixtures"
        } for part in relative.parts[:-1])
        repository = Path(item["git_repository_path"]).resolve()
        commit = item["revision_commit"]
        rule = "test_mock_example_harness" if harness_directory else "unknown_defaults_to_harness"
        evidence = None
        recorded_main_sha = None
        relationship = "recorded_revision_unavailable"
        try:
            recorded_main = git_output(repository, "show", f"{commit}:{relative.as_posix()}")
            recorded_main_sha = hashlib.sha256(recorded_main).hexdigest()
            relationship = source_relationship(recorded_main, entrypoint.read_bytes())
            if (recorded_main_sha != item["entrypoint_sha256"] and
                    relationship != "pragma_only"):
                rule = "snapshot_main_differs_from_recorded_revision_defaults_to_harness"
            elif not harness_directory:
                evidence = direct_reference(repository, commit, relative)
                if evidence:
                    rule = ("direct_reference_in_recorded_revision_pragma_only" if
                            relationship == "pragma_only" else
                            "direct_reference_in_recorded_revision")
        except (OSError, subprocess.CalledProcessError, ValueError):
            rule = "recorded_revision_unavailable_defaults_to_harness"
        rows.append({"revision_id": item["identifier"],
                     "main_file": str(entrypoint),
                     "snapshot_main_sha256": item["entrypoint_sha256"],
                     "recorded_main_sha256": recorded_main_sha,
                     "source_relationship": relationship,
                     "git_repository_path": str(repository),
                     "revision_commit": commit,
                     "classification": "deployed" if evidence else "harness",
                     "evidence": evidence,
                     "rule": rule})
    require(len(rows) == 10, "entrypoint classification count mismatch")
    expected = {"schema_version": 1, "rows": rows}
    digest = sha256(ENTRYPOINTS) if ENTRYPOINTS.exists() and read_json(ENTRYPOINTS) == expected \
        else write_new(ENTRYPOINTS, expected)
    return {"table": str(ENTRYPOINTS), "table_sha256": digest, "row_count": len(rows)}


def verify_entrypoints_completed(saved: dict[str, Any]) -> None:
    require(ENTRYPOINTS.is_file(), "completed entrypoint table is missing")
    current = classify_entrypoints()
    require(all(saved.get(key) == value for key, value in current.items()),
            "completed entrypoint table or classification evidence changed")


def adapter_command(stage_name: str, engine: str, *args: str) -> list[str]:
    return [sys.executable, str(ADAPTER), "--stage", stage_name,
            "--engine", engine, *args]


def make_engine_overlay(v1_index: Path, v22_index: Path,
                        v22_engine: Path, v22_sha: str) -> str:
    index = read_json(v1_index)
    require(index.get("engine") == str(runner.ENGINE) and
            index.get("engine_sha256") == runner.ENGINE_SHA256,
            "v1 request index engine lock differs")
    require(sha256(v22_engine) == v22_sha, "v2.2 engine hash mismatch")
    overlay = {**index, "engine": str(v22_engine), "engine_sha256": v22_sha}
    digest = sha256(v22_index) if v22_index.exists() and read_json(v22_index) == overlay \
        else write_new(v22_index, overlay)
    require(read_json(v22_index)["requests"] == index["requests"],
            "engine overlay changed request rows")
    return digest


def plan_and_index() -> dict[str, Any]:
    common = ("--scope", "main", "--inventory", str(INVENTORY),
              "--queue", str(QUEUE), "--request-root", str(REQUESTS),
              "--plan-index", str(PLAN), "--index", str(INDEX_V1))
    if not PLAN.exists():
        rc = logged_command("index-plan", adapter_command("requests", "v1", *common))
        require(rc == 0, "B request plan failed; inspect index-plan log")
    plan = read_json(PLAN)
    require(plan.get("request_count") == 107 and
            len(plan.get("requests", [])) == 107, "B plan is not 107 requests")
    if not INDEX_V1.exists():
        if REQUESTS.exists():
            history = OUT / "prior-attempts"
            history.mkdir(exist_ok=True)
            attempt = len(list(history.glob("partial-requests-*"))) + 1
            REQUESTS.replace(history / f"partial-requests-{attempt:03d}")
        rc = logged_command("index-finalize", adapter_command(
            "requests", "v1", *common, "--base-index", str(BASE)))
        require(rc == 0, "B request finalization failed; inspect index-finalize log")
    index = read_json(INDEX_V1)
    rows = index.get("requests")
    require(index.get("status") == "verified" and index.get("request_count") == 107 and
            isinstance(rows, list) and len(rows) == 107, "final B index is not 107 requests")
    require(all(row.get("method") == "S" for row in rows) and
            len({row["request"] for row in rows}) == 107,
            "B first-run request methods or IDs differ")
    v22_hash = make_engine_overlay(INDEX_V1, INDEX_V22, ENGINE_V22, ENGINE_V22_SHA)
    base = read_json(BASE)
    selected = b_pilot.select_requests(index, base)
    require(len(selected) == 2 and all(row["preparation_failure"] is None for row in selected),
            "two callable S pilot requests are required")
    selected_ids = [{"request_id": Path(row["request"]).stem,
                     "queue_order": row["queue_order"],
                     "revision_id": row["revision_id"]}
                    for row in selected]
    selected = {"schema_version": 1, "requests": selected_ids}
    selected_hash = sha256(SELECTION) if SELECTION.exists() and read_json(SELECTION) == selected \
        else write_new(SELECTION, selected)
    summary = index_summary()
    require(summary["v2_2_index_sha256"] == v22_hash and
            summary["pilot_selection_sha256"] == selected_hash,
            "B index artifact changed during finalization")
    return summary


def index_summary() -> dict[str, Any]:
    require(all(path.is_file() for path in (PLAN, INDEX_V1, INDEX_V22, SELECTION)),
            "completed B index artifact missing")
    plan = read_json(PLAN)
    v1 = read_json(INDEX_V1)
    v22 = read_json(INDEX_V22)
    rows = v1.get("requests")
    require(plan.get("status") == "awaiting_base_input" and
            plan.get("request_count") == 107 and
            len(plan.get("requests", [])) == 107 and
            plan.get("inventory_sha256") == sha256(INVENTORY) and
            plan.get("queue_sha256") == sha256(QUEUE) and
            plan.get("engine") == str(ENGINE_V1) and
            plan.get("engine_sha256") == ENGINE_V1_SHA,
            "completed B request plan changed")
    require(v1.get("status") == "verified" and v1.get("request_count") == 107 and
            isinstance(rows, list) and len(rows) == 107 and
            v1.get("plan_index_sha256") == sha256(PLAN) and
            v1.get("base_index_sha256") == sha256(BASE) and
            v1.get("inventory_sha256") == sha256(INVENTORY) and
            v1.get("engine") == str(ENGINE_V1) and
            v1.get("engine_sha256") == ENGINE_V1_SHA and
            all(row.get("method") == "S" for row in rows),
            "completed B v1 index changed")
    require(v22 == {**v1, "engine": str(ENGINE_V22),
                    "engine_sha256": ENGINE_V22_SHA},
            "completed B v2.2 engine overlay changed request rows")
    require(len({row["request"] for row in rows}) == 107 and
            all(Path(row["request"]).is_relative_to(REQUESTS) and
                sha256(Path(row["request"])) == row["request_sha256"] and
                sha256(Path(row["candidate_path"])) == row["candidate_sha256"]
                for row in rows), "completed B request or candidate hash changed")
    base = read_json(BASE)
    selected = b_pilot.select_requests(v1, base)
    require(read_json(SELECTION) == {"schema_version": 1, "requests": [
        {"request_id": Path(row["request"]).stem,
         "queue_order": row["queue_order"],
         "revision_id": row["revision_id"]} for row in selected]},
        "completed pilot selection changed")
    return {"request_count": 107,
            "request_generator_sha256": sha256(Path(requests.__file__)),
            "plan_sha256": sha256(PLAN), "v1_index_sha256": sha256(INDEX_V1),
            "v2_2_index_sha256": sha256(INDEX_V22),
            "pilot_selection_sha256": sha256(SELECTION)}


def verify_index_completed(saved: dict[str, Any]) -> None:
    current = index_summary()
    require(all(saved.get(key) == value for key, value in current.items()),
            "completed B index or request generator hash changed")


def validate_index(engine: str, index: Path, cache_parent: Path) -> dict[str, Any]:
    rc = logged_command(f"validate-{engine}", adapter_command(
        "validate", engine, "--index", str(index),
        "--index-sha256", sha256(index), "--cache-root", str(cache_parent),
        "--action", "validate-only"))
    require(rc == 0, f"{engine} validate-only failed; inspect its stage log")
    return {"index": str(index), "index_sha256": sha256(index), "validation_exit_code": rc}


def verify_validate_completed(saved: dict[str, Any], engine: str, index: Path,
                              cache_parent: Path) -> None:
    current = validate_index(engine, index, cache_parent)
    require(all(saved.get(key) == value for key, value in current.items()),
            f"completed {engine} validate-only evidence changed")


def pilot_format(output: Path, index: Path) -> dict[str, Any]:
    state = read_json(output / "state.json")
    index_document = read_json(index)
    rows = {row["queue_order"]: row for row in index_document["requests"]}
    requests_state = state.get("requests")
    require(state.get("kind") == "n6_b5_format_only_pilot_state" and
            state.get("status") == "passed" and
            state.get("request_index_sha256") == sha256(index) and
            state.get("base_index_sha256") == sha256(BASE) and
            state.get("selection_sha256") == sha256(SELECTION) and
            state.get("engine_sha256") == index_document["engine_sha256"] and
            isinstance(requests_state, dict) and
            len(requests_state) == 2, "pilot did not complete two requests")
    for record in requests_state.values():
        require(record.get("status") == "completed" and record.get("exit_code") == 0 and
                record.get("format_ok") is True and
                type(record.get("max_rss_bytes")) is int and record["max_rss_bytes"] > 0,
                "pilot request exit/measurement invalid")
        row = rows[record["queue_order"]]
        path = Path(record["result_path"])
        require(path.is_file() and sha256(path) == record["result_sha256"],
                "pilot result file/hash invalid")
        require(record["request_sha256"] == row["request_sha256"],
                "pilot request binding invalid")
        # The B5 format pilot checked result structure, request/candidate
        # hashes, preparation and tool status before joining. This outer gate
        # rechecks artifact hashes without opening result verdict fields.
    revisions = state.get("revisions")
    require(isinstance(revisions, dict) and revisions and
            all(row.get("status") == "joined" and
                row.get("format_ok") is True and row.get("exit_code") == 0 and
                Path(row["instances_path"]).is_file() and
                sha256(Path(row["instances_path"])) == row["instances_sha256"]
                for row in revisions.values()), "pilot instance join structure invalid")
    return {"completed_request_count": 2, "format_ok": True,
            "state_sha256": sha256(output / "state.json")}


def pilot_paths(engine: str, cache_parent: Path) -> tuple[int, Path, Path]:
    history = state_path(f"pilot-{engine}").parent / "prior-attempts"
    attempt = len(list(history.glob("state-*.json"))) + 1
    while True:
        cache = cache_parent / f"b5-batch1-{engine}-attempt-{attempt:03d}-cache"
        output = OUT / f"pilot-{engine}-attempt-{attempt:03d}.noindex"
        if not cache.exists() and not output.exists():
            return attempt, cache, output
        attempt += 1


def pilot(engine: str, index: Path, cache_parent: Path) -> dict[str, Any]:
    attempt, cache, output = pilot_paths(engine, cache_parent)
    rc: int | None = None
    try:
        require(shutil.disk_usage(ROOT).free >= MIN_FREE and
                shutil.disk_usage(cache_parent).free >= MIN_FREE,
                "less than 40 GiB before J pilot; review old ignored runs caches or "
                "unused Docker build cache/images; this command deletes nothing")
        rc = logged_command(f"pilot-{engine}", adapter_command(
            "pilot", engine, "--index", str(index), "--index-sha256", sha256(index),
            "--base-index", str(BASE), "--base-index-sha256", sha256(BASE),
            "--selection", str(SELECTION),
            "--cache-root", str(cache), "--output", str(output), "--action", "execute"))
        require(rc == 0, f"{engine} pilot command failed; inspect its stage log")
        return {"engine": engine, "attempt_number": attempt,
                "cache_root": str(cache), "output": str(output),
                "pilot_exit_code": rc, **pilot_format(output, index)}
    except Exception as error:
        partial = output / "state.json"
        raise StageFailure({"engine": engine, "attempt_number": attempt,
                            "cache_root": str(cache), "output": str(output),
                            "pilot_exit_code": rc,
                            "partial_state_sha256": sha256(partial) if partial.is_file() else None
                            }) from error


def verify_pilot_completed(saved: dict[str, Any], engine: str, index: Path,
                           cache_parent: Path) -> None:
    attempt = saved.get("attempt_number")
    require(type(attempt) is int and attempt > 0, "completed pilot attempt missing")
    output = OUT / f"pilot-{engine}-attempt-{attempt:03d}.noindex"
    cache = cache_parent / f"b5-batch1-{engine}-attempt-{attempt:03d}-cache"
    require(saved.get("output") == str(output) and
            saved.get("cache_root") == str(cache) and cache.is_dir(),
            "completed pilot output/cache binding changed")
    current = {"engine": engine, "attempt_number": attempt,
               "cache_root": str(cache), "output": str(output),
               "pilot_exit_code": 0, **pilot_format(output, index)}
    require(all(saved.get(key) == value for key, value in current.items()),
            f"completed {engine} pilot output or format evidence changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-parent", type=Path,
                        help="Existing absolute directory for separate J pilot caches")
    args = parser.parse_args()
    cache_input = args.cache_parent
    if cache_input is None:
        cache_input = Path(input("J cache parent (existing absolute directory): ").strip())
    require(cache_input.is_absolute(), "J cache parent must be absolute")
    cache_parent = cache_input.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    stage("preflight", lambda: preflight(cache_parent),
          lambda saved: verify_preflight_completed(saved, cache_parent))
    stage("base-inputs", collect_base_inputs, verify_base_completed)
    stage("entrypoints", classify_entrypoints, verify_entrypoints_completed)
    stage("index", plan_and_index, verify_index_completed)
    stage("validate-v2.2", lambda: validate_index("v2.2", INDEX_V22, cache_parent),
          lambda saved: verify_validate_completed(saved, "v2.2", INDEX_V22, cache_parent))
    stage("validate-v1", lambda: validate_index("v1", INDEX_V1, cache_parent),
          lambda saved: verify_validate_completed(saved, "v1", INDEX_V1, cache_parent))
    stage("pilot-v2.2", lambda: pilot("v2.2", INDEX_V22, cache_parent),
          lambda saved: verify_pilot_completed(saved, "v2.2", INDEX_V22, cache_parent))
    stage("pilot-v1", lambda: pilot("v1", INDEX_V1, cache_parent),
          lambda saved: verify_pilot_completed(saved, "v1", INDEX_V1, cache_parent))
    print("B batch 1 preparation ended after two format checks; exit_code=0", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"B batch 1 preparation stopped: {type(error).__name__}; "
              f"review stage state/logs under {OUT}", file=sys.stderr)
        raise SystemExit(2) from error
