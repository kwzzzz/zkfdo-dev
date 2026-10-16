#!/usr/bin/env python3
"""Prepare the frozen N6-A stage-1 inventory without running zkFuzz."""

from __future__ import annotations

import argparse
from collections import defaultdict
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
import measure_c02_preparation as legacy  # noqa: E402
import measure_f01_discovery as f01  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "docs/n6_targets_a_2026-10-07.json"
TARGETS_SHA = "6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758"
RUN = ROOT / "runs/n6-a1-2026-10-07"
ZKFDO = ROOT / "runs/f01-2026-10-03/supplement-var-scope/tools/zkfDO"
ZKFDO_SHA = "f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1"
MIN_FREE = 40 * 1024**3


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


def write_once(path: Path, value: object) -> None:
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text() != text:
            raise ValueError(f"refusing to replace record: {rel(path)}")
        return
    path.write_text(text)


def load_average() -> list[float]:
    return list(os.getloadavg())


def free_bytes() -> int:
    return shutil.disk_usage(ROOT).free


def source_clone(project: str) -> Path | None:
    slug = project.replace("/", "__")
    candidates = [
        ROOT / f"runs/e01-setup-2026-10-03/repositories/{slug}/clone",
        ROOT / f"runs/c03-corpus-2026-10-02/recovery-v3/repositories/{slug}/clone",
    ]
    return next((path for path in candidates if (path / ".git").exists()), None)


def unit_inventory() -> dict:
    if sha256(TARGETS) != TARGETS_SHA or sha256(ZKFDO) != ZKFDO_SHA:
        raise ValueError("frozen N6-A list or F-01 binary changed")
    data = json.loads(TARGETS.read_text())
    units: dict[tuple, dict] = {}
    for item in data["items"]:
        if item["bucket"] != "A-Q-stage1":
            continue
        variants = [("vulnerable", item["vulnerable_commit"])]
        variants += [("fixed", commit) for commit in item["fix_commits"]]
        for variant, revision in variants:
            key = (item["project"].lower(), revision, item["original_entrypoint"],
                   item["original_entrypoint_kind"], variant)
            unit = units.setdefault(key, {
                "branch": "A-Q-stage1", "project": item["project"], "revision_kind": variant,
                "revision": revision, "entrypoint": item["original_entrypoint"],
                "entrypoint_kind": item["original_entrypoint_kind"], "item_ids": [],
                "dataset_cases": [], "leave_one_out": None,
            })
            unit["item_ids"].append(item["id"])
            unit["dataset_cases"].append(item["dataset_case"])
        loo = item.get("leave_one_out")
        if loo:
            revision = item["fix_commits"][0]
            key = (item["project"].lower(), revision, item["original_entrypoint"],
                   item["original_entrypoint_kind"], "leave_one_out", item["id"])
            units[key] = {
                "branch": "A-Q-stage1", "project": item["project"],
                "revision_kind": "leave_one_out", "revision": revision,
                "vulnerable_revision": item["vulnerable_commit"],
                "entrypoint": item["original_entrypoint"],
                "entrypoint_kind": item["original_entrypoint_kind"],
                "item_ids": [item["id"]], "dataset_cases": [item["dataset_case"]],
                "leave_one_out": loo,
            }
    rows = []
    for index, unit in enumerate(sorted(units.values(), key=lambda row: (
            row["project"].lower(), row["entrypoint"], row["revision_kind"], row["revision"],
            row["item_ids"]))):
        unit["unit_id"] = f"aq-{index:03d}-{hashlib.sha256(json.dumps(unit, sort_keys=True).encode()).hexdigest()[:12]}"
        unit["item_ids"].sort()
        unit["dataset_cases"].sort()
        rows.append(unit)
    development = []
    for unit in data["development_units"]:
        row = dict(unit)
        row["branch"] = "A-D"
        row["revision_kind"] = ("leave_one_out" if "loo" in row["unit_id"] else
                                "fixed" if row["unit_id"].endswith("fixed") else "development")
        development.append(row)
    required: dict[str, set[str]] = defaultdict(set)
    for unit in rows:
        required[unit["project"]].add(unit["revision"])
        if unit.get("vulnerable_revision"):
            required[unit["project"]].add(unit["vulnerable_revision"])
    return {
        "schema_version": 1, "task": "N6-A1 preparation-unit inventory",
        "created_at": now(), "zkfuzz_invocations": 0,
        "target_list": {"path": rel(TARGETS), "sha256": TARGETS_SHA},
        "deduplication_key": "project, revision-or-patch-tree, Original entrypoint, execution settings",
        "development_units": development, "aq_stage1_units": rows,
        "counts": {"development_units": len(development), "aq_stage1_units": len(rows),
                   "all_preparation_units": len(development) + len(rows),
                   "aq_projects": len(required)},
        "required_commits": {project: sorted(commits) for project, commits in sorted(required.items())},
    }


def inventory() -> None:
    value = unit_inventory()
    write_once(RUN / "preparation-units.json", value)
    print(json.dumps(value["counts"], indent=2))


def capture(command: list[str], cwd: Path, log_dir: Path, timeout: int = 900) -> dict:
    if (log_dir / "invocation.json").is_file():
        recorded = json.loads((log_dir / "invocation.json").read_text())
        if recorded.get("argv") != command:
            raise ValueError(f"recorded command mismatch: {rel(log_dir)}")
        return recorded
    log_dir.mkdir(parents=True, exist_ok=False)
    started_at, started = now(), time.monotonic()
    before_load = load_average()
    with (log_dir / "stdout.log").open("wb") as stdout, (log_dir / "stderr.log").open("wb") as stderr:
        try:
            result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout,
                                    stderr=stderr, timeout=timeout, check=False,
                                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
            status = "success" if result.returncode == 0 else "failure"
            code = result.returncode
        except subprocess.TimeoutExpired:
            status, code = "timeout", None
    record = {"argv": command, "started_at": started_at, "finished_at": now(),
              "elapsed_seconds": time.monotonic() - started, "status": status,
              "exit_code": code, "load_average_before": before_load,
              "load_average_after": load_average(),
              "stdout": {"path": rel(log_dir / "stdout.log"), "sha256": sha256(log_dir / "stdout.log")},
              "stderr": {"path": rel(log_dir / "stderr.log"), "sha256": sha256(log_dir / "stderr.log")}}
    write_once(log_dir / "invocation.json", record)
    return record


def acquire() -> None:
    units = json.loads((RUN / "preparation-units.json").read_text())
    records = []
    for project, commits in units["required_commits"].items():
        if free_bytes() < MIN_FREE:
            raise RuntimeError("disk_guard_below_40_GiB")
        source = source_clone(project)
        repo_dir = RUN / "repositories" / project.replace("/", "__")
        base = repo_dir / "base"
        record_path = repo_dir / "acquisition.json"
        if record_path.exists():
            records.append(json.loads(record_path.read_text()))
            continue
        repo_dir.mkdir(parents=True, exist_ok=True)
        record = {"project": project, "started_at": now(), "load_average_start": load_average(),
                  "free_bytes_start": free_bytes(), "required_commits": commits,
                  "source_clone": rel(source) if source else None, "copy": None, "fetch": None}
        if source is None:
            record.update(status="source_clone_missing", finished_at=now())
            write_once(record_path, record)
            records.append(record)
            continue
        copy = capture(["/bin/cp", "-cR", str(source), str(base)], ROOT, repo_dir / "copy-call", 1800)
        record["copy"] = copy
        if copy["status"] != "success":
            record.update(status="apfs_copy_failed", finished_at=now())
            write_once(record_path, record)
            records.append(record)
            continue
        missing = [commit for commit in commits if subprocess.run(
            ["/usr/bin/git", "-C", str(base), "cat-file", "-e", f"{commit}^{{commit}}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0]
        if missing:
            fetch = capture(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "fetch", "--no-tags",
                             "origin", *missing], base, repo_dir / "fetch-call", 1800)
            record["fetch"] = fetch
        unresolved = [commit for commit in commits if subprocess.run(
            ["/usr/bin/git", "-C", str(base), "cat-file", "-e", f"{commit}^{{commit}}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0]
        record.update(status="success" if not unresolved else "missing_commit",
                      unresolved_commits=unresolved, finished_at=now(),
                      load_average_end=load_average(), free_bytes_end=free_bytes())
        write_once(record_path, record)
        records.append(record)
    summary = {"schema_version": 1, "task": "N6-A1 repository acquisition",
               "created_at": now(), "zkfuzz_invocations": 0,
               "projects": records, "counts": dict(sorted(defaultdict(int, {
                   status: sum(row["status"] == status for row in records)
                   for status in {row["status"] for row in records}}).items()))}
    write_once(RUN / "acquisition-summary.json", summary)
    print(json.dumps(summary["counts"], indent=2))


def recover_missing() -> None:
    """Retry unresolved abbreviated commits by fetching the recorded remote refs."""
    summary = json.loads((RUN / "acquisition-summary.json").read_text())
    recovered = []
    for row in summary["projects"]:
        unresolved = row.get("unresolved_commits", [])
        if not unresolved:
            recovered.append({"project": row["project"], "status": "not_needed",
                              "unresolved_commits": []})
            continue
        base = RUN / "repositories" / row["project"].replace("/", "__") / "base"
        call = capture(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "fetch", "--no-tags",
                        "origin"], base, base.parent / "fetch-recovery-call", 1800)
        remaining = [commit for commit in unresolved if subprocess.run(
            ["/usr/bin/git", "-C", str(base), "cat-file", "-e", f"{commit}^{{commit}}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0]
        recovered.append({"project": row["project"], "status": "success" if not remaining else
                          "missing_commit", "initial_unresolved_commits": unresolved,
                          "unresolved_commits": remaining, "fetch": call})
    result = {"schema_version": 1, "task": "N6-A1 acquisition recovery",
              "created_at": now(), "zkfuzz_invocations": 0, "projects": recovered,
              "counts": {status: sum(row["status"] == status for row in recovered)
                         for status in sorted({row["status"] for row in recovered})}}
    write_once(RUN / "acquisition-recovery.json", result)
    print(json.dumps(result["counts"], indent=2))


def lockfiles(root: Path) -> dict[str, str]:
    names = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"}
    return {path.relative_to(root).as_posix(): sha256(path) for path in sorted(root.rglob("*"))
            if path.is_file() and path.name in names and "node_modules" not in path.parts}


def select_loo_patch(project: Path, vulnerable: str, fixed: str, scope: dict,
                     output: Path) -> dict:
    source = subprocess.run(["/usr/bin/git", "-C", str(project), "diff", "--no-ext-diff",
                             "--unified=0", vulnerable, fixed, "--", scope["path"]],
                            capture_output=True, text=True, check=False)
    if source.returncode != 0:
        return {"status": "diff_failure", "stderr": source.stderr.strip()}
    lines = source.stdout.splitlines(keepends=True)
    prefix, hunks, current = [], [], None
    for line in lines:
        if line.startswith("@@ "):
            current = [line]
            hunks.append(current)
        elif current is None:
            prefix.append(line)
        else:
            current.append(line)
    match = re.match(r"(\d+)(?:-(\d+))?", str(scope.get("line") or ""))
    if not match:
        return {"status": "location_line_unparseable"}
    wanted_start, wanted_end = int(match.group(1)), int(match.group(2) or match.group(1))
    chosen = []
    headers = []
    for hunk in hunks:
        header = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", hunk[0])
        if not header:
            continue
        old_start, old_count = int(header.group(1)), int(header.group(2) or "1")
        old_end = old_start + max(old_count, 1) - 1
        if old_start <= wanted_end and wanted_start <= old_end:
            chosen.extend(hunk)
            headers.append(hunk[0].strip())
    if not chosen:
        return {"status": "no_overlapping_fix_hunk", "available_hunks":
                [hunk[0].strip() for hunk in hunks]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(prefix + chosen))
    applied = subprocess.run(["/usr/bin/git", "-C", str(project), "apply", "--reverse", str(output)],
                             capture_output=True, text=True, check=False)
    return {"status": "success" if applied.returncode == 0 else "apply_failure",
            "path": rel(output), "sha256": sha256(output), "selected_hunks": headers,
            "stderr": applied.stderr.strip() or None}


def materialize_aq(unit: dict, acquisition: dict) -> dict:
    directory = RUN / "units" / unit["unit_id"]
    result_path = directory / "materialization.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    started_at = now()
    project = directory / "project"
    result = {"unit_id": unit["unit_id"], "branch": "A-Q-stage1", "project": unit["project"],
              "revision": unit["revision"], "revision_kind": unit["revision_kind"],
              "entrypoint_recorded": unit["entrypoint"], "started_at": started_at,
              "load_average_start": load_average(), "free_bytes_start": free_bytes(),
              "zkfuzz_invocations": 0}
    state = acquisition.get(unit["project"])
    if not state or state["status"] != "success":
        result.update(status="not_started", failure_type="source_commit_unavailable",
                      detail=(state or {}).get("unresolved_commits", []), finished_at=now())
        write_once(result_path, result)
        return result
    if free_bytes() < MIN_FREE:
        raise RuntimeError("disk_guard_below_40_GiB")
    base = RUN / "repositories" / unit["project"].replace("/", "__") / "base"
    copy = capture(["/bin/cp", "-cR", str(base), str(project)], ROOT, directory / "copy-call", 1800)
    result["copy"] = copy
    if copy["status"] != "success":
        result.update(status="failed", failure_type="apfs_copy_failed", finished_at=now())
        write_once(result_path, result)
        return result
    base_locks = lockfiles(base)
    checkout = capture(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "checkout", "--detach",
                        unit["revision"]], project, directory / "checkout-call", 180)
    result["checkout"] = checkout
    if checkout["status"] != "success":
        result.update(status="failed", failure_type="checkout_failed", finished_at=now())
        write_once(result_path, result)
        return result
    if unit["revision_kind"] == "leave_one_out":
        result["leave_one_out"] = select_loo_patch(
            project, unit["vulnerable_revision"], unit["revision"],
            unit["leave_one_out"]["planned_diff_scope"], directory / "leave-one-out.patch")
        if result["leave_one_out"]["status"] != "success":
            result.update(status="failed", failure_type="leave_one_out_patch_failed", finished_at=now())
            write_once(result_path, result)
            return result
    entrypoint = project / unit["entrypoint"]
    if unit["entrypoint_kind"] == "original_is_direct":
        case = ROOT / unit["dataset_cases"][0]
        entrypoint = directory / "original-is-direct" / "circuit.circom"
        entrypoint.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(case / "circuit.circom", entrypoint)
        result["original_direct_source"] = {"path": rel(case / "circuit.circom"),
                                            "sha256": sha256(case / "circuit.circom")}
    revision_locks = lockfiles(project)
    has_node_modules = any(path.is_dir() for path in project.rglob("node_modules"))
    result["dependencies"] = {"base_lockfiles": base_locks, "revision_lockfiles": revision_locks,
                              "lockfiles_equal": base_locks == revision_locks,
                              "node_modules_present": has_node_modules,
                              "status": "reused_apfs" if base_locks == revision_locks and has_node_modules
                              else "setup_required"}
    result["entrypoint"] = {"path": rel(entrypoint) if entrypoint.exists() else str(entrypoint.relative_to(project)),
                            "exists": entrypoint.is_file(),
                            "sha256": sha256(entrypoint) if entrypoint.is_file() else None}
    result.update(status="ready_for_setup_or_discovery" if entrypoint.is_file() else "failed",
                  failure_type=None if entrypoint.is_file() else "original_entrypoint_missing",
                  finished_at=now(), load_average_end=load_average(), free_bytes_end=free_bytes())
    write_once(result_path, result)
    return result


def materialize_development(unit: dict) -> dict:
    directory = RUN / "units" / unit["unit_id"]
    result_path = directory / "materialization.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    directory.mkdir(parents=True, exist_ok=True)
    project = directory / "project"
    result = {"unit_id": unit["unit_id"], "branch": "A-D", "project": unit["project"],
              "revision": unit["revision"], "entrypoint_recorded": unit["entrypoint"],
              "started_at": now(), "zkfuzz_invocations": 0,
              "load_average_start": load_average(), "free_bytes_start": free_bytes()}
    source = ROOT / unit["source"]
    copy = capture(["/bin/cp", "-cR", str(source), str(project)], ROOT, directory / "copy-call", 1800)
    result["copy"] = copy
    if copy["status"] != "success":
        result.update(status="failed", failure_type="apfs_copy_failed", finished_at=now())
        write_once(result_path, result)
        return result
    if (project / ".git").exists():
        base = "d310309c141d36504b3486cebd96ed70ef3a4fdf" if unit.get("revision_tree") else unit["revision"]
        checkout = capture(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "checkout", "--detach", base],
                           project, directory / "checkout-call", 180)
        result["checkout"] = checkout
        if checkout["status"] != "success":
            result.update(status="failed", failure_type="checkout_failed", finished_at=now())
            write_once(result_path, result)
            return result
        if unit.get("diff"):
            patch = ROOT / unit["diff"]["path"]
            applied = capture(["/usr/bin/git", "apply", str(patch)], project,
                              directory / "tree-patch-call", 120)
            result["tree_patch"] = applied
            if applied["status"] != "success":
                result.update(status="failed", failure_type="revision_tree_patch_failed", finished_at=now())
                write_once(result_path, result)
                return result
    entrypoint = project / unit["entrypoint"]
    result["entrypoint"] = {"path": rel(entrypoint) if entrypoint.exists() else unit["entrypoint"],
                            "exists": entrypoint.is_file(),
                            "sha256": sha256(entrypoint) if entrypoint.is_file() else None}
    result["dependencies"] = {"status": "source_snapshot", "lockfiles": lockfiles(project),
                              "node_modules_present": any(path.is_dir() for path in project.rglob("node_modules"))}
    result.update(status="ready_for_setup_or_discovery" if entrypoint.is_file() else "failed",
                  failure_type=None if entrypoint.is_file() else "original_entrypoint_missing",
                  finished_at=now(), load_average_end=load_average(), free_bytes_end=free_bytes())
    write_once(result_path, result)
    return result


def materialize() -> None:
    inventory_data = json.loads((RUN / "preparation-units.json").read_text())
    acquisition_data = json.loads((RUN / "acquisition-summary.json").read_text())
    recovery_path = RUN / "acquisition-recovery.json"
    recovered = {row["project"]: row for row in json.loads(recovery_path.read_text())["projects"]} \
        if recovery_path.exists() else {}
    acquisitions = {}
    for row in acquisition_data["projects"]:
        state = dict(row)
        if recovered.get(row["project"], {}).get("status") == "success":
            state["status"], state["unresolved_commits"] = "success", []
        acquisitions[row["project"]] = state
    results = [materialize_development(unit) for unit in inventory_data["development_units"]]
    results += [materialize_aq(unit, acquisitions) for unit in inventory_data["aq_stage1_units"]]
    counts = {status: sum(row["status"] == status for row in results)
              for status in sorted({row["status"] for row in results})}
    summary = {"schema_version": 1, "task": "N6-A1 revision materialization",
               "created_at": now(), "zkfuzz_invocations": 0, "units": results, "counts": counts,
               "free_bytes_end": free_bytes(), "load_average_end": load_average()}
    write_once(RUN / "materialization-summary.json", summary)
    print(json.dumps(counts, indent=2))


GENERATED_ORIGINALS = {
    ("aptos-labs/keyless-zk-proofs", "circuit/templates/generated/base64_decoded_length_main.circom"):
        'pragma circom 2.1.3;\ninclude "../helpers/misc.circom";\ncomponent main = Base64DecodedLength(8);\n',
    ("siv-org/verifiable-private-overrides", "circuits/generated/extract_string_from_point_main.circom"):
        'pragma circom 2.2.2;\ninclude "../ExtractStringFromPoint.circom";\ncomponent main = ExtractStringFromPoint();\n',
    ("siv-org/verifiable-private-overrides", "circuits/generated/emit_if_in_range_main.circom"):
        'pragma circom 2.2.2;\ninclude "../ExtractStringFromPoint.circom";\ncomponent main = EmitIfInRange(5);\n',
    ("Arianee/arianee-sdk", "packages/privacy-circuits/src/circom/creditVerifier/generated/creditVerifier_main.circom"):
        'pragma circom 2.1.8;\ninclude "../creditVerifier.circom";\ncomponent main { public [pubRoot, pubCreditType, pubNullifierHash] } = CreditVerifier(30);\n',
}


def recover_materialization() -> None:
    summary = json.loads((RUN / "materialization-summary.json").read_text())
    generator = ROOT / ".external/zkbugs/scripts/download_sources.sh"
    recovered = []
    for old in summary["units"]:
        if old["status"] in ("ready_for_setup_or_discovery", "not_started"):
            recovered.append({"unit_id": old["unit_id"], "status": "not_needed",
                              "previous_status": old["status"]})
            continue
        directory = RUN / "units" / old["unit_id"]
        project = directory / "project"
        if "entrypoint_recorded" not in old and old.get("branch") == "A-D":
            target_data = json.loads(TARGETS.read_text())
            development = next(row for row in target_data["development_units"]
                               if row["unit_id"] == old["unit_id"])
            old["entrypoint_recorded"] = development["entrypoint"]
        record = {"unit_id": old["unit_id"], "previous_failure_type": old.get("failure_type"),
                  "started_at": now(), "zkfuzz_invocations": 0, "actions": []}
        if old.get("failure_type") == "revision_tree_patch_failed":
            target_data = json.loads(TARGETS.read_text())
            unit = next(row for row in target_data["development_units"]
                        if row["unit_id"] == old["unit_id"])
            old["entrypoint_recorded"] = unit["entrypoint"]
            patch = ROOT / unit["diff"]["path"]
            action = capture(["/usr/bin/patch", "-p1", "--forward", "--input", str(patch)], project,
                             directory / "tree-patch-recovery-call", 120)
            record["actions"].append({"kind": "l06_patch_utility", "capture": action})
        elif old.get("failure_type") == "checkout_failed" and old["project"] == "zkemail/zk-email-verify":
            action = capture(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "fetch", "--no-tags",
                              "origin", old["revision"]], project,
                             directory / "checkout-fetch-recovery-call", 1800)
            record["actions"].append({"kind": "fetch_missing_promisor_object", "capture": action})
            if action["status"] == "success":
                checkout = capture(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "checkout",
                                    "--detach", old["revision"]], project,
                                   directory / "checkout-recovery-call", 180)
                record["actions"].append({"kind": "checkout", "capture": checkout})
        elif old.get("failure_type") == "leave_one_out_patch_failed" and \
                (old.get("leave_one_out") or {}).get("path"):
            patch = ROOT / old["leave_one_out"]["path"]
            action = capture(["/usr/bin/git", "apply", "--reverse", "--unidiff-zero", str(patch)],
                             project, directory / "leave-one-out-recovery-call", 120)
            record["actions"].append({"kind": "scoped_reverse_patch_unidiff_zero", "capture": action})
        key = (old["project"], old["entrypoint_recorded"])
        if key in GENERATED_ORIGINALS:
            entrypoint = project / old["entrypoint_recorded"]
            entrypoint.parent.mkdir(parents=True, exist_ok=True)
            entrypoint.write_text(GENERATED_ORIGINALS[key])
            record["actions"].append({"kind": "zkbugs_standard_generated_original",
                                      "generator": {"path": rel(generator), "sha256": sha256(generator)},
                                      "path": rel(entrypoint), "sha256": sha256(entrypoint)})
        entrypoint = project / old.get("entrypoint_recorded", "")
        action_failed = any(action.get("capture", {}).get("status") != "success"
                            for action in record["actions"] if "capture" in action)
        missing_loo_patch = (old.get("failure_type") == "leave_one_out_patch_failed" and
                             not (old.get("leave_one_out") or {}).get("path"))
        record.update(status="success" if entrypoint.is_file() and not action_failed else "failed",
                      failure_type=None if entrypoint.is_file() and not action_failed else
                      ("original_entrypoint_missing" if not entrypoint.is_file() else "recovery_action_failed"),
                      entrypoint={"path": rel(entrypoint) if entrypoint.is_file() else
                                  old.get("entrypoint_recorded"), "exists": entrypoint.is_file(),
                                  "sha256": sha256(entrypoint) if entrypoint.is_file() else None},
                      finished_at=now())
        if missing_loo_patch:
            record.update(status="failed", failure_type="leave_one_out_patch_unavailable")
        recovered.append(record)
    result = {"schema_version": 1, "task": "N6-A1 materialization recovery",
              "created_at": now(), "zkfuzz_invocations": 0, "units": recovered,
              "counts": {status: sum(row["status"] == status for row in recovered)
                         for status in sorted({row["status"] for row in recovered})}}
    write_once(RUN / "materialization-recovery.json", result)
    print(json.dumps(result["counts"], indent=2))


def effective_units() -> list[tuple[dict, dict | None]]:
    original = json.loads((RUN / "materialization-summary.json").read_text())["units"]
    recovery = {row["unit_id"]: row for row in
                json.loads((RUN / "materialization-recovery.json").read_text())["units"]}
    return [(row, recovery.get(row["unit_id"])) for row in original]


def setup_units() -> None:
    tools = json.loads((ROOT / "runs/e01-setup-2026-10-03/tools/tools.json").read_text())
    results = []
    for original, recovery in effective_units():
        ready = original["status"] == "ready_for_setup_or_discovery" or \
            (recovery or {}).get("status") == "success"
        if not ready:
            results.append({"unit_id": original["unit_id"], "status": "not_started",
                            "reason": (recovery or original).get("failure_type") or original["status"]})
            continue
        project = RUN / "units" / original["unit_id"] / "project"
        entrypoint = project / original.get("entrypoint_recorded", "")
        if not original.get("entrypoint_recorded"):
            target_data = json.loads(TARGETS.read_text())
            development = next(row for row in target_data["development_units"]
                               if row["unit_id"] == original["unit_id"])
            entrypoint = project / development["entrypoint"]
        dependencies = original.get("dependencies") or {}
        node_modules = any(path.is_dir() for path in project.rglob("node_modules"))
        must_install = dependencies.get("status") == "setup_required" or \
            (original["project"] == "zkemail/zk-email-verify" and not node_modules)
        raw = RUN / "units" / original["unit_id"] / "setup"
        if must_install and not (raw / "setup.json").exists():
            if free_bytes() < MIN_FREE:
                raise RuntimeError("disk_guard_below_40_GiB")
            result = e01_environment.run_setup(project, [entrypoint], raw, tools,
                                               caps={"submodule": 180, "install": 600,
                                                     "inventory": 120})
        elif (raw / "setup.json").exists():
            result = json.loads((raw / "setup.json").read_text())
        else:
            result = {"status": "success", "failure_types": [], "elapsed_seconds": 0.0,
                      "reuse": "apfs_node_modules_and_unchanged_lockfiles" if node_modules else
                      "no_package_setup_required"}
        results.append({"unit_id": original["unit_id"], "project": original["project"],
                        "status": result["status"], "failure_types": result.get("failure_types", []),
                        "elapsed_seconds": result.get("elapsed_seconds", 0.0),
                        "setup_record": rel(raw / "setup.json") if (raw / "setup.json").is_file() else None,
                        "reuse": result.get("reuse"), "load_average": load_average()})
    summary = {"schema_version": 1, "task": "N6-A1 setup", "created_at": now(),
               "zkfuzz_invocations": 0, "units": results,
               "counts": {status: sum(row["status"] == status for row in results)
                          for status in sorted({row["status"] for row in results})},
               "elapsed_seconds_sum": sum(row.get("elapsed_seconds", 0) for row in results)}
    write_once(RUN / "setup-summary.json", summary)
    print(json.dumps(summary["counts"], indent=2))


def unit_definition(unit_id: str) -> dict:
    inventory_data = json.loads((RUN / "preparation-units.json").read_text())
    for row in inventory_data["development_units"] + inventory_data["aq_stage1_units"]:
        if row["unit_id"] == unit_id:
            return row
    raise KeyError(unit_id)


def libraries_for(unit: dict, project: Path, entrypoint: Path) -> list[Path]:
    libraries = [project]
    if unit.get("branch") == "A-Q-stage1":
        case = ROOT / unit["dataset_cases"][0]
        text = (case / "zkbugs_vars.sh").read_text(errors="replace")
        match = re.search(r"CIRCOM_LINK_FLAGS=\(([^\n]*)\)", text)
        if match:
            for token in re.findall(r'-l\s+"([^"]+)"', match.group(1)):
                if token == "$CODEBASE_PATH":
                    path = project
                elif token == "$CIRCOMLIB_PATH":
                    assignment = shell_assignment(text, "CIRCOMLIB_PATH") or ""
                    path = project if "$CODEBASE_PATH" in assignment else \
                        ROOT / ".external/zkbugs/dataset/circom/dependencies/circomlib"
                else:
                    continue
                libraries.append(path)
    for candidate in (project / "node_modules", entrypoint.parent, project / "circomlib"):
        if candidate.exists():
            libraries.append(candidate)
    return list(dict.fromkeys(path.resolve() for path in libraries))


def shell_assignment(text: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}=(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def discover_prepare() -> None:
    setup = {row["unit_id"]: row for row in json.loads((RUN / "setup-summary.json").read_text())["units"]}
    circom = ROOT / "runs/c02-corpus-2026-10-02/tools/circom"
    results = []
    for unit_id, setup_row in setup.items():
        directory = RUN / "units" / unit_id / "preparation"
        result_path = directory / "result.json"
        if result_path.exists():
            results.append(json.loads(result_path.read_text()))
            continue
        unit = unit_definition(unit_id)
        result = {"schema_version": 1, "task": "N6-A1 discovery/preparation", "unit_id": unit_id,
                  "project": unit["project"], "revision": unit["revision"],
                  "started_at": now(), "load_average_start": load_average(),
                  "free_bytes_start": free_bytes(), "zkfuzz_invocations": 0,
                  "setup_status": setup_row["status"]}
        if setup_row["status"] != "success":
            result.update(status="not_started", failure_type="setup_not_success", finished_at=now())
            write_once(result_path, result)
            results.append(result)
            continue
        if free_bytes() < MIN_FREE:
            raise RuntimeError("disk_guard_below_40_GiB")
        project = RUN / "units" / unit_id / "project"
        entrypoint = project / unit["entrypoint"]
        if unit.get("entrypoint_kind") == "original_is_direct":
            source = RUN / "units" / unit_id / "original-is-direct/circuit.circom"
            entrypoint = project / ".zkbugs-original/circuit.circom"
            entrypoint.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, entrypoint)
            result["original_is_direct_copy"] = {"source": rel(source), "source_sha256": sha256(source),
                                                  "path": rel(entrypoint), "sha256": sha256(entrypoint)}
        libraries = libraries_for(unit, project, entrypoint)
        result["condition"] = {"entrypoint": rel(entrypoint),
                               "entrypoint_sha256": sha256(entrypoint),
                               "library_paths": [rel(path) for path in libraries],
                               "circom": {"path": rel(circom), "sha256": sha256(circom)},
                               "zkfDO": {"path": rel(ZKFDO), "sha256": sha256(ZKFDO)}}
        discovery_dir = directory / "discovery"
        command = [str(ZKFDO), "targets", "--project", str(project), "--entrypoint", str(entrypoint),
                   "--output", str(discovery_dir), "--circom-bin", str(circom),
                   "--compile-timeout-seconds", "60", "--instance-capture",
                   "--capture-timeout-seconds", "600"]
        for library in libraries:
            command += ["--library-path", str(library)]
        discover_call = directory / "discover-call"
        if (discover_call / "invocation.json").is_file():
            discovery = json.loads((discover_call / "invocation.json").read_text())
            if discovery.get("argv") != command:
                raise ValueError(f"recorded discovery command mismatch: {unit_id}")
        else:
            discovery = legacy.run_command(command, discover_call, 900)
        result["discovery"] = legacy.brief(discovery)
        report_path = legacy.locate_report(discovery_dir, "discovery.json") if discovery_dir.exists() else None
        if discovery["status"] != "success" or report_path is None:
            result.update(status="failed", failure_type=legacy.failure_type(discovery) or
                          "discovery_report_missing", finished_at=now())
            write_once(result_path, result)
            results.append(result)
            continue
        report = json.loads(report_path.read_text())
        capture_ref = (report.get("instance_discovery") or {}).get("capture")
        capture_path = ROOT / capture_ref["path"] if isinstance(capture_ref, dict) and capture_ref.get("path") else None
        try:
            manifest = f01.manifest_for(unit["project"], unit["revision"], project, entrypoint, report,
                                        libraries, capture_path)
        except (ValueError, KeyError, TypeError) as error:
            result.update(status="failed", failure_type="manifest_concrete_instance_unavailable",
                          reason=str(error), discovery_report={"path": rel(report_path),
                                                               "sha256": sha256(report_path)},
                          finished_at=now())
            write_once(result_path, result)
            results.append(result)
            continue
        manifest_path = directory / "manifest.json"
        write_once(manifest_path, manifest)
        prepared_dir = directory / "prepared-small-first"
        prepare_command = [str(ZKFDO), "experiment", "prepare", "--manifest", str(manifest_path),
                           "--output", str(prepared_dir), "--strategy", "small-first",
                           "--circom-bin", str(circom), "--tool-timeout-seconds", "60"]
        prepare_call_dir = directory / "prepare-small-first-call"
        if (prepare_call_dir / "invocation.json").is_file():
            prepared_call = json.loads((prepare_call_dir / "invocation.json").read_text())
            if prepared_call.get("argv") != prepare_command:
                raise ValueError(f"recorded prepare command mismatch: {unit_id}")
        else:
            prepared_call = legacy.run_command(prepare_command, prepare_call_dir, 300)
        result["prepare"] = legacy.brief(prepared_call)
        prepared_path = legacy.locate_report(prepared_dir, "prepared.json") if prepared_dir.exists() else None
        if prepared_call["status"] != "success" or prepared_path is None:
            result.update(status="failed", failure_type=legacy.failure_type(prepared_call) or
                          "prepared_report_missing", finished_at=now())
            write_once(result_path, result)
            results.append(result)
            continue
        prepared = json.loads(prepared_path.read_text())
        if any((target.get("structure") or {}).get("ast_requested") or
               ((target.get("structure") or {}).get("zkfuzz_version") or {}).get("requested")
               for target in prepared["targets"]):
            raise RuntimeError("forbidden zkFuzz frontend request in N6-A1 preparation")
        plan_path = directory / "plan.json"
        plan_call = legacy.run_command([str(ZKFDO), "experiment", "plan", "--prepared", str(prepared_path),
                                        "--strategy", "small-first", "--config",
                                        str(ROOT / "configs/static-ranking.json"), "--output", str(plan_path)],
                                       directory / "plan-call", 30)
        result["plan"] = legacy.brief(plan_call)
        eligible = sum(bool(target.get("eligible")) for target in prepared["targets"])
        result.update(status="success" if plan_call["status"] == "success" and plan_path.is_file() else "failed",
                      failure_type=None if plan_call["status"] == "success" and plan_path.is_file() else
                      (legacy.failure_type(plan_call) or "plan_missing"),
                      discovery_report={"path": rel(report_path), "sha256": sha256(report_path)},
                      prepared_report={"path": rel(prepared_path), "sha256": sha256(prepared_path)},
                      plan_report={"path": rel(plan_path), "sha256": sha256(plan_path)} if plan_path.is_file() else None,
                      discovered_targets=len(report.get("targets", [])),
                      prepared_targets=len(prepared["targets"]), eligible_targets=eligible,
                      finished_at=now(), load_average_end=load_average(), free_bytes_end=free_bytes())
        write_once(result_path, result)
        results.append(result)
    summary = {"schema_version": 1, "task": "N6-A1 discovery/preparation summary",
               "created_at": now(), "zkfuzz_invocations": 0, "units": results,
               "counts": {status: sum(row["status"] == status for row in results)
                          for status in sorted({row["status"] for row in results})},
               "targets": {"discovered": sum(row.get("discovered_targets", 0) for row in results),
                           "prepared": sum(row.get("prepared_targets", 0) for row in results),
                           "eligible": sum(row.get("eligible_targets", 0) for row in results)}}
    write_once(RUN / "preparation-summary.json", summary)
    print(json.dumps({"counts": summary["counts"], "targets": summary["targets"]}, indent=2))


def cleanup_artifacts() -> None:
    plan_path = RUN / "artifact-cleanup-plan.json"
    result_path = RUN / "artifact-cleanup-result.json"
    if result_path.exists():
        print(result_path.read_text())
        return
    suffixes = {".r1cs", ".wasm", ".cpp", ".dat", ".o"}
    targets: dict[Path, dict] = {}
    diagnostic_dirs = []
    preserved_diagnostics = []
    for path in sorted((RUN / "units").glob("*/preparation/**/instance-capture/diagnostic-copy")) + \
            sorted((RUN / "units").glob("*/preparation/**/instance-capture/diagnostic-build")):
        capture_root = path.parent.parent
        capture = capture_root / "instance-capture.json"
        arguments = capture_root / "instance-args.json"
        if not capture.is_file() or not arguments.is_file():
            preserved_diagnostics.append({"path": rel(path),
                                          "reason": "instance_capture_or_args_missing"})
            continue
        diagnostic_dirs.append(path)
        for item in path.rglob("*"):
            if item.is_symlink():
                targets[item] = {"path": rel(item), "kind": "symlink", "target": str(item.readlink())}
            elif item.is_file():
                targets[item] = {"path": rel(item), "kind": "file", "bytes": item.stat().st_size,
                                 "sha256": sha256(item)}
    for path in (RUN / "units").glob("*/preparation/**/*"):
        if path.is_file() and not path.is_symlink() and path.suffix in suffixes:
            targets.setdefault(path, {"path": rel(path), "kind": "file", "bytes": path.stat().st_size,
                                      "sha256": sha256(path)})
    plan = {"schema_version": 1, "task": "N6-A1 artifact cleanup", "recorded_at": now(),
            "capture_values_verified": True, "extensions": sorted(suffixes),
            "diagnostic_directories": [rel(path) for path in diagnostic_dirs],
            "preserved_diagnostics": preserved_diagnostics,
            "entries": [targets[path] for path in sorted(targets)],
            "file_count": sum(row["kind"] == "file" for row in targets.values()),
            "file_bytes": sum(row.get("bytes", 0) for row in targets.values())}
    write_once(plan_path, plan)
    deleted_files = deleted_bytes = 0
    for path, row in targets.items():
        if not path.exists() and not path.is_symlink():
            continue
        if row["kind"] == "file":
            if path.stat().st_size != row["bytes"] or sha256(path) != row["sha256"]:
                raise ValueError(f"cleanup target changed: {rel(path)}")
            deleted_files += 1
            deleted_bytes += row["bytes"]
        elif str(path.readlink()) != row["target"]:
            raise ValueError(f"cleanup symlink changed: {rel(path)}")
        path.unlink()
    for directory in sorted(diagnostic_dirs, key=lambda path: len(path.parts), reverse=True):
        if directory.exists():
            shutil.rmtree(directory)
    result = {"schema_version": 1, "task": "N6-A1 artifact cleanup result",
              "finished_at": now(), "plan": {"path": rel(plan_path), "sha256": sha256(plan_path)},
              "deleted_files": deleted_files, "deleted_bytes": deleted_bytes,
              "free_bytes_after": free_bytes(), "zkfuzz_invocations": 0}
    write_once(result_path, result)
    print(json.dumps(result, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("inventory", "acquire", "recover-missing", "materialize",
                                          "recover-materialization", "setup", "discover-prepare",
                                          "cleanup-artifacts"))
    args = parser.parse_args()
    if args.phase == "inventory":
        inventory()
    elif args.phase == "acquire":
        acquire()
    elif args.phase == "recover-missing":
        recover_missing()
    elif args.phase == "materialize":
        materialize()
    elif args.phase == "recover-materialization":
        recover_materialization()
    elif args.phase == "setup":
        setup_units()
    elif args.phase == "discover-prepare":
        discover_prepare()
    else:
        cleanup_artifacts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
