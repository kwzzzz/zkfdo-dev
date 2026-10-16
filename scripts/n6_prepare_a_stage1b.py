#!/usr/bin/env python3
"""Reprepare the frozen N6-A stage-1 units with the zkbugs setup rules.

This program materializes source trees and runs discovery/prepare/plan only.
It never invokes zkFuzz or the Policy A campaign execute path.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e01_environment  # noqa: E402
import n6_prepare_a_stage1 as a1  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a1b-2026-10-08"
OLD_RUN = ROOT / "runs/n6-a1-2026-10-07"
TARGETS = ROOT / "docs/n6_targets_a_2026-10-07.json"
TARGETS_SHA = "6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758"
OFFICIAL = ROOT / ".external/zkbugs/scripts/download_sources.sh"
PATCHES = ROOT / ".external/zkbugs/scripts/patches"
CIRCOMLIB = ROOT / ".external/zkbugs/dataset/circom/dependencies/circomlib"
ZKFDO = ROOT / "runs/f01-2026-10-03/supplement-var-scope/tools/zkfDO"
ZKFDO_SHA = "f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1"
MIN_FREE = 40 * 1024**3
SHORT_PANTHER_FIXES = {
    "0621e84", "1055906", "1763ca4", "3375335", "54d4d0a", "69db60e",
    "6dfcc56", "7ff5ba7", "8fdab18", "903edd3", "ccb2a8b",
}
PANTHER_FULL_COMMITS = {
    "b464348b33155a5877f67c085c7206dc29ad7cb7",
    "06a818632053719b56ace37ef12c9b31904af1e2",
    "39b770de49db47fcea361cf515b61e43dff36b65",
}
L06_TREES = {
    "inference-r-intdiv": "r_intdiv",
    "inference-c9221e8d": "c9221e8d",
    "inference-c79f42ee": "c79f42ee",
    "inference-c771c61c-p": "c771c61c_p",
    "inference-loo-clamp": "loo_clamp",
    "inference-loo-dfs": "loo_dfs",
    "inference-all-fixed": "all_fixed",
}
GENERATED = a1.GENERATED_ORIGINALS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def lexical_rel(path: Path) -> str:
    return path.absolute().relative_to(ROOT).as_posix()


def write_once(path: Path, value: object) -> None:
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text() != text:
            raise ValueError(f"refusing to replace record: {path}")
        return
    path.write_text(text)


def capture(argv: list[str], cwd: Path, directory: Path, timeout: int = 1800) -> dict:
    record_path = directory / "invocation.json"
    if record_path.is_file():
        recorded = json.loads(record_path.read_text())
        if recorded["argv"] != argv:
            raise ValueError(f"recorded command mismatch: {directory}")
        return recorded
    directory.mkdir(parents=True, exist_ok=False)
    started_at = now()
    started = time.monotonic()
    load_before = list(os.getloadavg())
    with (directory / "stdout.log").open("wb") as stdout, \
            (directory / "stderr.log").open("wb") as stderr:
        try:
            proc = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout,
                                  stderr=stderr, timeout=timeout, check=False,
                                  env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
            status = "success" if proc.returncode == 0 else "failure"
            code = proc.returncode
        except subprocess.TimeoutExpired:
            status, code = "timeout", None
    record = {
        "argv": argv, "started_at": started_at, "finished_at": now(),
        "elapsed_seconds": time.monotonic() - started, "status": status,
        "exit_code": code, "load_average_before": load_before,
        "load_average_after": list(os.getloadavg()),
        "stdout": {"path": rel(directory / "stdout.log"),
                   "sha256": sha256(directory / "stdout.log")},
        "stderr": {"path": rel(directory / "stderr.log"),
                   "sha256": sha256(directory / "stderr.log")},
    }
    write_once(record_path, record)
    return record


def disk_guard() -> None:
    if shutil.disk_usage(ROOT).free < MIN_FREE:
        raise RuntimeError("disk_guard_below_40_GiB")


def load_inventory() -> dict:
    return json.loads((RUN / "preparation-units.json").read_text())


def inventory() -> None:
    if sha256(TARGETS) != TARGETS_SHA or sha256(ZKFDO) != ZKFDO_SHA:
        raise ValueError("frozen target list or F-01 binary changed")
    old = json.loads((OLD_RUN / "preparation-units.json").read_text())
    if old["counts"]["development_units"] != 12 or old["counts"]["aq_stage1_units"] != 41:
        raise ValueError("A-D/A-Q denominator changed")
    value = dict(old)
    value.update({
        "schema_version": 2,
        "task": "N6-A1b frozen preparation-unit inventory",
        "created_at": now(),
        "source_inventory": {"path": rel(OLD_RUN / "preparation-units.json"),
                             "sha256": sha256(OLD_RUN / "preparation-units.json")},
        "supplement_policy": "N5 A preparation supplement 2026-10-08",
        "zkfuzz_invocations": 0,
    })
    write_once(RUN / "preparation-units.json", value)
    print(json.dumps(value["counts"], indent=2))


def copy_apfs(source: Path, destination: Path, log: Path) -> dict:
    disk_guard()
    return capture(["/bin/cp", "-cR", str(source), str(destination)], ROOT, log, 1800)


def acquire_panther() -> None:
    destination = RUN / "repositories/pantherfoundation__panther-core/base"
    root = destination.parent
    result_path = root / "acquisition.json"
    if result_path.is_file():
        print(result_path.read_text())
        return
    source = ROOT / "runs/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone"
    result = {
        "schema_version": 1, "task": "N6-A1b Panther full-SHA acquisition",
        "started_at": now(), "load_average_start": list(os.getloadavg()),
        "free_bytes_start": shutil.disk_usage(ROOT).free,
        "source": rel(source), "requested_full_shas": sorted(PANTHER_FULL_COMMITS),
        "short_fix_commits_not_requested": sorted(SHORT_PANTHER_FIXES),
        "zkfuzz_invocations": 0,
    }
    result["copy"] = copy_apfs(source, destination, root / "copy-call")
    fetches = []
    if result["copy"]["status"] == "success":
        for commit in sorted(PANTHER_FULL_COMMITS):
            present = subprocess.run(
                ["/usr/bin/git", "-C", str(destination), "cat-file", "-e", f"{commit}^{{commit}}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
            if present:
                fetches.append({"commit": commit, "status": "already_present"})
                continue
            call = capture(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "fetch",
                            "--no-tags", "origin", commit], destination,
                           root / f"fetch-{commit[:12]}", 1800)
            fetches.append({"commit": commit, "status": call["status"], "call": call})
    unresolved = [commit for commit in PANTHER_FULL_COMMITS if subprocess.run(
        ["/usr/bin/git", "-C", str(destination), "cat-file", "-e", f"{commit}^{{commit}}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode != 0]
    result.update({"fetches": fetches, "unresolved_full_shas": sorted(unresolved),
                   "status": "success" if not unresolved else "missing_full_sha",
                   "finished_at": now(), "load_average_end": list(os.getloadavg()),
                   "free_bytes_end": shutil.disk_usage(ROOT).free})
    write_once(result_path, result)
    print(json.dumps({"status": result["status"], "unresolved": unresolved}, indent=2))


def record_panther_recovery() -> None:
    base = RUN / "repositories/pantherfoundation__panther-core/base"
    rows = []
    for commit in sorted(PANTHER_FULL_COMMITS):
        proc = subprocess.run(
            ["/usr/bin/git", "-C", str(base), "cat-file", "-e", f"{commit}^{{commit}}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        rows.append({"commit": commit, "status": "present" if proc.returncode == 0 else "missing"})
    value = {
        "schema_version": 1, "task": "N6-A1b Panther direct-fetch recovery",
        "created_at": now(), "method": "git fetch origin <full-sha>",
        "reason": "initial sandboxed fetch could not resolve github.com; authorized retry succeeded",
        "initial_record": {"path": rel(base.parent / "acquisition.json"),
                           "sha256": sha256(base.parent / "acquisition.json")},
        "commits": rows, "status": "success" if all(row["status"] == "present" for row in rows)
        else "missing_full_sha", "zkfuzz_invocations": 0,
    }
    write_once(base.parent / "acquisition-recovery.json", value)
    print(json.dumps(value, indent=2))


def unit_by_id(unit_id: str) -> dict:
    inv = load_inventory()
    return next(row for row in inv["development_units"] + inv["aq_stage1_units"]
                if row["unit_id"] == unit_id)


def old_project(unit_id: str) -> Path:
    return OLD_RUN / "units" / unit_id / "project"


def symlink_relative(target: Path, link: Path) -> dict:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        if link.is_symlink() and link.resolve() == target.resolve():
            pass
        elif link.is_dir() and not link.is_symlink():
            return {"kind": "dependency_directory_reused", "path": lexical_rel(link),
                    "target": rel(target), "status": "existing_real_directory"}
        else:
            link.unlink()
            link.symlink_to(os.path.relpath(target, link.parent))
    else:
        link.symlink_to(os.path.relpath(target, link.parent))
    return {"kind": "official_relative_symlink", "path": lexical_rel(link),
            "target": rel(target), "link_text": os.readlink(link), "status": "success"}


def generated_file(project: Path, path: str, content: str) -> dict:
    output = project / path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    return {"kind": "official_generated_entrypoint", "path": rel(output),
            "sha256": sha256(output), "status": "success"}


def mutate_lines(path: Path, remove: list[str] | None = None,
                 comment_component_main: bool = False) -> dict:
    if not path.is_file():
        return {"kind": "official_compatibility_edit", "path": str(path),
                "status": "source_missing"}
    before = sha256(path)
    lines = path.read_text().splitlines(keepends=True)
    if remove:
        lines = [line for line in lines if line.strip() not in remove]
    if comment_component_main:
        lines = ["// " + line if line.startswith("component main") else line for line in lines]
    path.write_text("".join(lines))
    return {"kind": "official_compatibility_edit", "path": rel(path),
            "before_sha256": before, "sha256": sha256(path), "status": "success"}


def apply_official_patch(project: Path, patch: Path, log_root: Path) -> dict:
    before = capture(["/usr/bin/git", "apply", "--check", str(patch)], project,
                     log_root / "patch-check", 120)
    if before["status"] == "success":
        applied = capture(["/usr/bin/git", "apply", str(patch)], project,
                          log_root / "patch-apply", 120)
        status = applied["status"]
    else:
        reverse = capture(["/usr/bin/git", "apply", "--reverse", "--check", str(patch)],
                          project, log_root / "patch-reverse-check", 120)
        applied = None
        status = "already_applied" if reverse["status"] == "success" else "failure"
    return {"kind": "official_patch", "path": rel(patch), "sha256": sha256(patch),
            "status": status, "check": before, "apply": applied}


def official_actions(unit: dict, project: Path, log_root: Path) -> tuple[list[dict], list[str]]:
    project_name = unit["project"]
    revision = unit["revision"]
    actions: list[dict] = []
    failures: list[str] = []

    def add(action: dict) -> None:
        actions.append(action)
        if action.get("status") in {"failure", "source_missing"}:
            failures.append(f"{action['kind']}:{action.get('path')}")

    if project_name == "pantherfoundation/panther-core":
        add(symlink_relative(CIRCOMLIB / "circuits",
                             project / "circuits/node_modules/circomlib/circuits"))
    elif project_name == "Arianee/arianee-sdk":
        add(symlink_relative(CIRCOMLIB / "circuits",
            project / "packages/privacy-circuits/src/node_modules/circomlib/circuits"))
        for file in (
            "packages/privacy-circuits/src/circom/creditVerifier/creditVerifier.circom",
            "packages/privacy-circuits/src/circom/ownershipVerifier/ownershipVerifier.circom",
        ):
            add(mutate_lines(project / file, comment_component_main=True))
        content = GENERATED[(project_name, unit["entrypoint"])]
        add(generated_file(project, unit["entrypoint"], content))
    elif project_name == "aptos-labs/keyless-zk-proofs":
        add(symlink_relative(CIRCOMLIB, project / "circomlib"))
        add(generated_file(project, unit["entrypoint"],
                           GENERATED[(project_name, unit["entrypoint"])]))
    elif project_name == "siv-org/verifiable-private-overrides":
        add(generated_file(project, unit["entrypoint"],
                           GENERATED[(project_name, unit["entrypoint"])]))
    elif project_name == "worm-privacy/proof-of-burn":
        circomlib = project / "circuits/circomlib"
        if circomlib.is_dir() and not circomlib.is_symlink() and not any(circomlib.iterdir()):
            circomlib.rmdir()
        add(symlink_relative(CIRCOMLIB, circomlib))
        add(mutate_lines(project / "circuits/spend.circom", remove=[
            'include "./utils/padding.circom";',
            'include "./utils/hashbytes.circom";',
        ]))
    elif project_name == "zkemail/zk-regex":
        add(symlink_relative(project / "packages/circom",
            project / "node_modules/@zk-email/zk-regex-circom"))
    elif project_name == "tangle-network/protocol-solidity":
        add(symlink_relative(CIRCOMLIB / "circuits",
                             project / "node_modules/circomlib/circuits"))
    elif project_name == "iden3/circomlib" and revision.startswith("324b8bf8cc"):
        add(apply_official_patch(project, PATCHES / "iden3_circomlib_324b8bf8cc.patch", log_root))
    elif project_name == "Moonsong-Labs/zksync-social-login-circuit":
        sentinel_a = project / "node_modules/@zk-email/circuits/lib/base64.circom"
        sentinel_b = project / "node_modules/circomlib/circuits/bitify.circom"
        status = "success" if sentinel_a.is_file() and sentinel_b.is_file() else "failure"
        add({"kind": "official_exact_dependency_reuse", "status": status,
             "packages": ["@zk-email/circuits@6.3.2", "circomlib@2.0.5"],
             "sentinels": [{"path": rel(path), "sha256": sha256(path) if path.is_file() else None}
                           for path in (sentinel_a, sentinel_b)]})
    elif project_name == "banyancomputer/hot-proofs-blake3-circom":
        add(symlink_relative(CIRCOMLIB, project / "circomlib"))

    return actions, failures


def source_for(unit: dict) -> tuple[Path | None, str]:
    unit_id = unit["unit_id"]
    if unit_id in L06_TREES:
        return ROOT / "runs/l06-2026-10-03/trees" / L06_TREES[unit_id], \
            "l06_verified_revision_tree"
    if unit["project"] == "pantherfoundation/panther-core":
        if unit["revision"] in SHORT_PANTHER_FIXES:
            return None, "fix_commit_unretrievable"
        return RUN / "repositories/pantherfoundation__panther-core/base", \
            "zkbugs_full_sha_direct_fetch"
    source = old_project(unit_id)
    return (source if source.is_dir() else None), "a1_exact_revision_apfs_reuse"


def materialize_one(unit: dict) -> dict:
    unit_dir = RUN / "units" / unit["unit_id"]
    result_path = unit_dir / "materialization.json"
    if result_path.is_file():
        return json.loads(result_path.read_text())
    unit_dir.mkdir(parents=True, exist_ok=True)
    source, source_kind = source_for(unit)
    result = {
        "schema_version": 1, "task": "N6-A1b materialization/setup",
        "unit_id": unit["unit_id"], "branch": unit["branch"],
        "project": unit["project"], "revision": unit["revision"],
        "revision_kind": unit.get("revision_kind"),
        "entrypoint_recorded": unit["entrypoint"],
        "preparation_procedure": ("development_frozen_revision" if unit["branch"] == "A-D"
                                  else "zkbugs_official"),
        "source_kind": source_kind, "started_at": now(),
        "load_average_start": list(os.getloadavg()),
        "free_bytes_start": shutil.disk_usage(ROOT).free,
        "official_script": {"path": rel(OFFICIAL), "sha256": sha256(OFFICIAL)},
        "zkfuzz_invocations": 0,
    }
    if source_kind == "fix_commit_unretrievable":
        result.update({"status": "not_started", "setup_status": "not_started",
                       "failure_type": "fix_commit_unretrievable",
                       "rq1_inclusion": "paired_vulnerable_revision_only",
                       "rq_c_inclusion": False,
                       "reason": "short SHA is not resolvable by full-SHA direct fetch",
                       "finished_at": now()})
        write_once(result_path, result)
        return result
    if unit["unit_id"] == "aq-028-b9b2613fdfa4":
        result.update({"status": "not_started", "setup_status": "not_started",
                       "failure_type": "leave_one_out_patch_unavailable",
                       "reason": "A1 scoped location had no overlapping fix hunk",
                       "finished_at": now()})
        write_once(result_path, result)
        return result
    if source is None or not source.is_dir():
        result.update({"status": "not_started", "setup_status": "not_started",
                       "failure_type": "source_snapshot_missing", "finished_at": now()})
        write_once(result_path, result)
        return result
    project = unit_dir / "project"
    result["copy"] = copy_apfs(source, project, unit_dir / "copy-call")
    if result["copy"]["status"] != "success":
        result.update({"status": "failed", "setup_status": "not_started",
                       "failure_type": "apfs_copy_failed", "finished_at": now()})
        write_once(result_path, result)
        return result
    if source_kind == "zkbugs_full_sha_direct_fetch":
        result["checkout"] = capture([
            "/usr/bin/git", "-c", "core.hooksPath=/dev/null", "checkout", "--detach",
            unit["revision"],
        ], project, unit_dir / "checkout-call", 180)
        if result["checkout"]["status"] != "success":
            result.update({"status": "failed", "setup_status": "not_started",
                           "failure_type": "checkout_failed", "finished_at": now()})
            write_once(result_path, result)
            return result
    if unit.get("entrypoint_kind") == "original_is_direct":
        case_source = ROOT / unit["dataset_cases"][0] / "circuit.circom"
        copy = unit_dir / "original-is-direct/circuit.circom"
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(case_source, copy)
        result["original_is_direct"] = {"source": rel(case_source),
                                         "source_sha256": sha256(case_source),
                                         "copy": rel(copy), "copy_sha256": sha256(copy)}
    actions, failures = official_actions(unit, project, unit_dir / "official-actions")
    result["official_actions"] = actions
    result["official_failures"] = failures
    entrypoint = project / unit["entrypoint"]
    if unit.get("entrypoint_kind") == "original_is_direct":
        entrypoint = unit_dir / "original-is-direct/circuit.circom"
    fallback = None
    if failures:
        tools = json.loads((ROOT / "runs/e01-setup-2026-10-03/tools/tools.json").read_text())
        fallback_root = unit_dir / "e01-fallback"
        fallback = e01_environment.run_setup(
            project, [entrypoint], fallback_root, tools,
            caps={"submodule": 180, "install": 600, "inventory": 120})
        result["preparation_procedure"] = "zkbugs_official_then_e01_fallback"
    result["e01_fallback"] = fallback
    setup_ok = not failures or (fallback or {}).get("status") == "success"
    result["entrypoint"] = {"path": rel(entrypoint) if entrypoint.is_file() else unit["entrypoint"],
                            "exists": entrypoint.is_file(),
                            "sha256": sha256(entrypoint) if entrypoint.is_file() else None}
    result["setup_status"] = "success" if setup_ok else "setup_failure"
    result["dependencies"] = {
        "status": "zkbugs_official_rules_applied" if setup_ok else "official_and_fallback_failed",
        "node_modules_present": any(path.is_dir() for path in project.rglob("node_modules")),
        "lockfiles": a1.lockfiles(project),
    }
    failure = None
    if not setup_ok:
        failure = "setup_failure"
    elif not entrypoint.is_file():
        failure = "original_entrypoint_missing"
    result.update({"status": "ready_for_discovery" if failure is None else "failed",
                   "failure_type": failure, "finished_at": now(),
                   "load_average_end": list(os.getloadavg()),
                   "free_bytes_end": shutil.disk_usage(ROOT).free})
    write_once(result_path, result)
    return result


def materialize_setup() -> None:
    inv = load_inventory()
    rows = []
    for unit in inv["development_units"] + inv["aq_stage1_units"]:
        disk_guard()
        rows.append(materialize_one(unit))
    summary = {
        "schema_version": 1, "task": "N6-A1b materialization and official setup summary",
        "created_at": now(), "zkfuzz_invocations": 0, "units": rows,
        "counts": dict(Counter(row["status"] for row in rows)),
        "setup_counts": dict(Counter(row["setup_status"] for row in rows)),
        "free_bytes_end": shutil.disk_usage(ROOT).free,
        "load_average_end": list(os.getloadavg()),
    }
    write_once(RUN / "materialization-summary.json", summary)
    recovery = {
        "schema_version": 1, "task": "N6-A1b materialization recovery (not applicable)",
        "created_at": now(), "zkfuzz_invocations": 0,
        "units": [{"unit_id": row["unit_id"], "status": "not_needed",
                   "previous_status": row["status"]} for row in rows],
        "counts": {"not_needed": len(rows)},
    }
    write_once(RUN / "materialization-recovery.json", recovery)
    setup_rows = [{
        "unit_id": row["unit_id"], "project": row["project"],
        "status": row["setup_status"],
        "failure_types": [row["failure_type"]] if row.get("failure_type") else [],
        "elapsed_seconds": sum(action.get("elapsed_seconds", 0)
                               for action in row.get("official_actions", [])),
        "setup_record": rel(RUN / "units" / row["unit_id"] / "materialization.json"),
        "preparation_procedure": row["preparation_procedure"],
        "load_average": row.get("load_average_end"),
    } for row in rows]
    setup = {
        "schema_version": 1, "task": "N6-A1b official setup",
        "created_at": now(), "zkfuzz_invocations": 0, "units": setup_rows,
        "counts": dict(Counter(row["status"] for row in setup_rows)),
        "elapsed_seconds_sum": sum(row["elapsed_seconds"] for row in setup_rows),
    }
    write_once(RUN / "setup-summary.json", setup)
    print(json.dumps({"materialization": summary["counts"], "setup": setup["counts"]}, indent=2))


def diagnose_a1() -> None:
    units = ["inference-loo-clamp", "inference-loo-dfs", "inference-all-fixed",
             "aq-036-6d7df64759b6", "aq-037-94fe3080fc18",
             "aq-038-4e5dcd2256b8", "aq-039-0ad3923f2f5b"]
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    rows = []
    for unit_id in units:
        path = OLD_RUN / "preflight-v2/preflight" / f"{unit_id}-seed-2026100601/W/preflight.json"
        ledger = json.loads(path.read_text())
        compile_row = next(row for row in ledger.get("compile", []) if row.get("status") != "success")
        stderr = path.parent / compile_row["stderr_path"]
        text = ansi.sub("", stderr.read_text(errors="replace"))
        core = [line.strip() for line in text.splitlines()
                if "error[P" in line or re.search(r'\.circom"?:\d+', line)
                or "not found" in line]
        rows.append({"unit_id": unit_id, "source_preflight": rel(path),
                     "source_preflight_sha256": sha256(path), "core_error_lines": core[:8]})
    preparation = json.loads((OLD_RUN / "preparation-summary.json").read_text())
    discovery_rows = []
    for row in preparation["units"]:
        if row.get("failure_type") not in {"compiler_or_tool_error",
                                            "manifest_concrete_instance_unavailable"}:
            continue
        unit_dir = OLD_RUN / "units" / row["unit_id"] / "preparation"
        candidates = [unit_dir / "discover-call/stderr.log",
                      unit_dir / "prepare-small-first-call/stderr.log",
                      unit_dir / "plan-call/stderr.log"]
        evidence = []
        for path in candidates:
            if path.is_file():
                lines = ansi.sub("", path.read_text(errors="replace")).splitlines()
                core = [line.strip() for line in lines if line.strip()][-6:]
                evidence.append({"path": rel(path), "sha256": sha256(path),
                                 "core_error_lines": core})
        discovery_rows.append({"unit_id": row["unit_id"],
                               "failure_type": row["failure_type"],
                               "reason": row.get("reason"), "stderr": evidence})
    result = {"schema_version": 1, "task": "N6-A1b prior failure diagnosis",
              "created_at": now(), "zkfuzz_invocations": 0,
              "w_preflight_failures": rows, "discovery_failures": discovery_rows}
    write_once(RUN / "a1-failure-diagnosis-v2.json", result)
    print(json.dumps({"W": len(rows), "discovery": len(discovery_rows)}, indent=2))


def discover_prepare() -> None:
    # Reuse the frozen F-01 discovery/prepare/plan implementation against only the
    # new run root.  The wrapper record below states the A1b provenance explicitly.
    setup_path = RUN / "setup-summary.json"
    setup = json.loads(setup_path.read_text())
    materialized = {row["unit_id"]: row for row in
                    json.loads((RUN / "materialization-summary.json").read_text())["units"]}
    corrected = False
    for row in setup["units"]:
        source = materialized[row["unit_id"]]
        if source["status"] != "ready_for_discovery" and row["status"] == "success":
            row.update(status="not_started", failure_types=[source.get("failure_type") or
                                                             source["status"]])
            corrected = True
    if corrected:
        setup["counts"] = dict(Counter(row["status"] for row in setup["units"]))
        original = RUN / "setup-summary-v1.json"
        if not original.exists():
            setup_path.rename(original)
        write_once(setup_path, setup)
        write_once(RUN / "setup-summary-correction.json", {
            "schema_version": 1, "task": "N6-A1b setup summary status correction",
            "created_at": now(), "reason": "setup success does not override missing Original entrypoint",
            "preserved_original": {"path": rel(original), "sha256": sha256(original)},
            "corrected": {"path": rel(setup_path), "sha256": sha256(setup_path)},
            "zkfuzz_invocations": 0,
        })
    original_run = a1.RUN
    try:
        a1.RUN = RUN
        a1.discover_prepare()
    finally:
        a1.RUN = original_run
    summary = RUN / "preparation-summary.json"
    wrapper = {"schema_version": 1, "task": "N6-A1b discovery/preparation provenance",
               "created_at": now(), "implementation": rel(Path(a1.__file__)),
               "implementation_sha256": sha256(Path(a1.__file__)),
               "result": {"path": rel(summary), "sha256": sha256(summary)},
               "zkfuzz_invocations": 0,
               "note": "F-01 target discovery, experiment prepare, and plan only; no zkFuzz command"}
    write_once(RUN / "preparation-provenance.json", wrapper)


def cleanup() -> None:
    original_run = a1.RUN
    try:
        a1.RUN = RUN
        a1.cleanup_artifacts()
    finally:
        a1.RUN = original_run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["inventory", "acquire-panther",
                                          "record-panther-recovery", "materialize-setup",
                                          "diagnose-a1", "discover-prepare", "cleanup"])
    args = parser.parse_args()
    {
        "inventory": inventory,
        "acquire-panther": acquire_panther,
        "record-panther-recovery": record_panther_recovery,
        "materialize-setup": materialize_setup,
        "diagnose-a1": diagnose_a1,
        "discover-prepare": discover_prepare,
        "cleanup": cleanup,
    }[args.phase]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
