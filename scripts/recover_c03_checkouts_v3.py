#!/usr/bin/env python3
"""Recover every frozen C-03 checkout without copying dirty worktree files.

Only Git retrieval and metadata verification run. The source census, original
checkouts, classifications and measurement records remain untouched. Neither
submodules, package managers, compilers nor repository scripts are run here.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "1d32c68560ac2b85b47fc7dd0a77e6e634d94b52ed2e8cdae48e4cec08ac8189"
REASON = ("Clean restart of all 80 repositories at the original pinned commits after "
          "the interrupted environment-v2 setup encountered unsupported pnpm CLI flags; "
          "no repository is selected by setup outcome.")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def reference(path):
    path = Path(path)
    return {"path": relative(path), "sha256": digest(path.read_bytes())}


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def validate_source(census):
    rows = census["repositories"]
    if len(rows) != 80 or census.get("repository_count") != 80:
        raise ValueError("recovery_requires_entire_frozen_80_repository_census")
    identities = []
    for row in rows:
        canonical = row["canonical_full_name"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", canonical):
            raise ValueError("invalid_canonical_public_github_name")
        if not re.fullmatch(r"[0-9a-f]{40}", row["commit_sha"]):
            raise ValueError("recovery_requires_full_pinned_commit_sha")
        source = (ROOT / row["clone_path"]).resolve()
        source.relative_to(ROOT / "runs" / "c03-corpus-2026-10-02")
        identities.append(canonical.casefold())
    if len(set(identities)) != 80:
        raise ValueError("duplicate_canonical_repository")


def git(args, logs, label, cwd=None):
    """Run bounded Git with hooks, lazy source fetches and inherited config off."""
    logs.mkdir(parents=True, exist_ok=True)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                       GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="/usr/bin/false",
                       GIT_LFS_SKIP_SMUDGE="1", GIT_NO_LAZY_FETCH="1",
                       GIT_OPTIONAL_LOCKS="0")
    command = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
               "-c", "core.autocrlf=false", "-c", "submodule.recurse=false",
               "-c", "filter.lfs.required=false", "-c", "filter.lfs.smudge=",
               "-c", "filter.lfs.process=", "-c", "protocol.ext.allow=never"] + args
    output, error = logs / (label + ".stdout"), logs / (label + ".stderr")
    start, start_time = time.monotonic(), now()
    timed_out, launch_error = False, None
    with output.open("xb") as stdout, error.open("xb") as stderr:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=stdout,
                                       stderr=stderr, start_new_session=True)
            try:
                returncode = process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                returncode = process.wait()
        except OSError as failure:
            launch_error, returncode = str(failure), None
    record = {"command": command, "cwd": relative(cwd) if cwd else None,
              "started_at": start_time, "finished_at": now(),
              "wall_seconds": time.monotonic() - start, "returncode": returncode,
              "status": "timeout" if timed_out else "ok" if returncode == 0 else "failed",
              "launch_error": launch_error, "stdout": reference(output),
              "stderr": reference(error), "lazy_fetch_disabled": True}
    write_new(logs / (label + ".json"), record)
    return record, output.read_bytes()


def recover_one(row, destination):
    canonical, sha = row["canonical_full_name"], row["commit_sha"]
    repo_dir = destination / "repositories" / canonical.replace("/", "__")
    repo_dir.mkdir(parents=True, exist_ok=False)
    source = (ROOT / row["clone_path"]).resolve()
    logs, url = repo_dir / "git-logs", "https://github.com/" + canonical + ".git"
    result = {"canonical_full_name": canonical, "commit_sha": sha,
              "source_clone_path": row["clone_path"], "started_at": now(),
              "recovery_reason": REASON, "public_origin": url, "commands": [],
              "attempts": [], "status": "failed", "clone_path": None}

    def run(args, label, cwd=None):
        record, output = git(args, logs, label, cwd)
        result["commands"].append(record)
        return record["status"] == "ok", output.decode("utf-8", errors="replace").strip()

    def finish_checkout(clone, prefix, attempt):
        ok, origin = run(["remote", "get-url", "origin"], prefix + "-origin-before", clone)
        attempt["origin_before"] = origin if ok else None
        ok, _ = run(["remote", "set-url", "origin", url], prefix + "-normalize-origin", clone)
        if not ok:
            return False
        ok, after = run(["remote", "get-url", "origin"], prefix + "-origin-after", clone)
        attempt["origin_after"] = after if ok else None
        attempt["transport_normalization"] = "metadata_derived_public_https_for_relative_submodules"
        if not ok or after != url:
            return False
        ok, _ = run(["checkout", "--detach", "--force", sha], prefix + "-checkout", clone)
        if not ok:
            return False
        ok, head = run(["rev-parse", "HEAD"], prefix + "-head", clone)
        attempt["observed_head"] = head if ok else None
        if not ok or head != sha:
            return False
        ok, tree = run(["rev-parse", "HEAD^{tree}"], prefix + "-tree", clone)
        attempt["tree_sha"] = tree if ok else None
        if not ok:
            return False
        ok, status = run(["status", "--porcelain=v1", "--untracked-files=all",
                          "--ignore-submodules=none"], prefix + "-clean-status", clone)
        attempt["clean_worktree"] = ok and not status
        if not attempt["clean_worktree"]:
            return False
        result.update(status="ok", clone_path=relative(clone), observed_head=head,
                      tree_sha=tree, clean_worktree=True, origin_after=after)
        return True

    try:
        ok, origin = run(["remote", "get-url", "origin"], "source-origin", source)
        result["source_origin"] = origin if ok else None
        clone = repo_dir / "clone"
        attempt = {"transport": "local_no_hardlinks", "path": relative(clone)}
        result["attempts"].append(attempt)
        ok, _ = run(["clone", "--no-hardlinks", "--no-checkout", "--no-recurse-submodules",
                     str(source), str(clone)], "local-clone")
        success = ok and finish_checkout(clone, "local", attempt)
        attempt["status"] = "ok" if success else "failed"
        if not success:
            # Preserve the failed local directory and fetch only the fixed SHA.
            clone = repo_dir / "clone-public-retry"
            attempt = {"transport": "https_pinned_sha_fetch", "path": relative(clone),
                       "requested_commit_sha": sha, "head_selection": False}
            result["attempts"].append(attempt)
            ok, _ = run(["init", str(clone)], "public-init")
            if ok:
                ok, _ = run(["remote", "add", "origin", url], "public-add-origin", clone)
            if ok:
                ok, _ = run(["fetch", "--no-tags", "--depth=1", "origin", sha],
                            "public-fetch-pinned-sha", clone)
            success = ok and finish_checkout(clone, "public", attempt)
            attempt["status"] = "ok" if success else "failed"
    except (OSError, ValueError) as failure:
        result["failure_reason"] = str(failure)
    if result["status"] != "ok":
        result.setdefault("failure_reason", "clean_pinned_checkout_unavailable")
    result["finished_at"] = now()
    write_new(repo_dir / "recovery.json", result)
    result["record"] = reference(repo_dir / "recovery.json")
    return result


def derive_census(original, records, original_ref, records_ref):
    """Change only clone_path within rows; retain all original other metadata."""
    rows = {record["canonical_full_name"].casefold(): record for record in records}
    names = {row["canonical_full_name"].casefold() for row in original["repositories"]}
    if len(records) != len(names) or set(rows) != names:
        raise ValueError("recovery_must_cover_exact_original_denominator")
    census = copy.deepcopy(original)
    for row in census["repositories"]:
        recovered = rows[row["canonical_full_name"].casefold()]
        if recovered["commit_sha"] != row["commit_sha"]:
            raise ValueError("recovery_commit_changed")
        if recovered["status"] != "ok" or not recovered.get("clean_worktree"):
            raise ValueError("cannot_freeze_incomplete_recovery")
        row["clone_path"] = recovered["clone_path"]
    census["checkout_recovery"] = {
        "version": 3, "source_census": original_ref, "records": records_ref,
        "reason": REASON, "frozen_at": now(), "repository_count": len(records),
        "row_mutations": ["clone_path"], "original_metadata_preserved": True,
        "same_commit_for_every_repository": True, "all_worktrees_clean": True,
        "setup_started": False, "compilation_started": False,
        "submodules_initialized_by_recovery": False,
        "original_timestamps_describe_original_collection": True,
    }
    return census


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=ROOT / "runs/c03-corpus-2026-10-02/census.v2.json")
    parser.add_argument("--destination", type=Path,
                        default=ROOT / "runs/c03-corpus-2026-10-02/recovery-v3")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    original_ref = reference(args.source)
    if original_ref["sha256"] != SOURCE_SHA256:
        raise ValueError("source_census_hash_mismatch")
    original = json.loads(args.source.read_text())
    validate_source(original)
    destination = args.destination.resolve()
    destination.relative_to(ROOT / "runs/c03-corpus-2026-10-02")
    destination.mkdir(parents=True, exist_ok=False)
    start = now()
    write_new(destination / "recovery-start.v3.json", {
        "started_at": start, "source_census": original_ref, "reason": REASON,
        "repository_count": 80, "helper": reference(Path(__file__)),
        "per_git_command_timeout_seconds": 120, "workers": args.workers,
        "only_pinned_commit_retrieval": True, "setup_or_compilation": False})
    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(recover_one, row, destination) for row in original["repositories"]]
        for future in concurrent.futures.as_completed(futures):
            record = future.result()
            records.append(record)
            print(json.dumps({"completed": len(records), "repository": record["canonical_full_name"],
                              "status": record["status"]}), flush=True)
    records.sort(key=lambda record: record["canonical_full_name"].casefold())
    records_path = destination / "recovery-records.v3.json"
    write_new(records_path, {"started_at": start, "finished_at": now(),
                             "source_census": original_ref, "reason": REASON,
                             "repository_count": len(records), "repositories": records})
    census = derive_census(original, records, original_ref, reference(records_path))
    census_path = destination / "census.v3.json"
    write_new(census_path, census)
    write_new(destination / "recovery-lock.v3.json", {
        "frozen_at": now(), "census": reference(census_path),
        "source_census": original_ref, "helper": reference(Path(__file__)),
        "records": reference(records_path), "repository_count": 80,
        "all_80_original_pinned_commits": True, "all_80_clean_worktrees": True,
        "setup_started": False, "compilation_started": False})
    print(json.dumps({"frozen_census": reference(census_path), "repository_count": 80}), flush=True)


if __name__ == "__main__":
    main()
