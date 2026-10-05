#!/usr/bin/env python3
"""Freeze the C-03 repository census and roles before any environment setup.

Only Git retrieval, repository metadata, introductory README sentences, licensing,
main declarations and declarative Circomkit metadata are inspected. No repository
program, package manager, compiler, witness, fuzzer, or preparation result runs.
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
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c03_curation as curation
import c03_config_entrypoints as config_entries
from collect_c02_repositories import main_declarations, path_roles, license_evidence


ROOT = Path(__file__).resolve().parents[1]
PROCEDURE_SHA = "638bb972b6bf390dc0660b965c1848dfb3fed89a101759dd971646f09dfe8108"
CONFIG_ADDITIONS = {"zk-kit/zk-kit.circom", "privacy-scaling-explorations/maci",
                    "semaphore-protocol/semaphore", "siv-org/verifiable-private-overrides"}
CUTOFF = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def rel(path):
    return str(Path(path).resolve().relative_to(ROOT))


def ref(path):
    path = Path(path)
    return {"path": rel(path), "sha256": digest(path.read_bytes())}


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def git(args, logs, label, cwd=None):
    logs.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               GIT_ASKPASS="/usr/bin/false", GIT_LFS_SKIP_SMUDGE="1")
    command = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
               "-c", "submodule.recurse=false", "-c", "filter.lfs.required=false",
               "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process="] + args
    stdout_path, stderr_path = logs / (label + ".stdout"), logs / (label + ".stderr")
    started_at, started = now(), time.monotonic()
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        timeout = False
        try:
            code = process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            timeout = True
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
    record = {"command": command, "cwd": rel(cwd) if cwd else None,
              "started_at": started_at, "finished_at": now(), "wall_seconds": time.monotonic() - started,
              "returncode": code, "status": "timeout" if timeout else "ok" if code == 0 else "failed",
              "stdout": ref(stdout_path), "stderr": ref(stderr_path)}
    write_new(logs / (label + ".json"), record)
    return record, stdout_path.read_bytes()


def retrieve_repository(name, logs):
    url = "https://api.github.com/repos/" + name
    record = {"url": url, "started_at": now()}
    metadata = {}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "c03-metadata-census",
                                                       "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            record["resolved_url"] = response.url
        path = logs / "github-repository.json"
        with path.open("xb") as handle:
            handle.write(raw)
        metadata = json.loads(raw)
        record.update(status="ok", **ref(path))
    except (OSError, ValueError) as error:
        record.update(status="unknown", reason=str(error))
    record["finished_at"] = now()
    write_new(logs / "github-repository-retrieval.json", record)
    return metadata, record


def _existing_api(row):
    api_ref = row.get("repository_api") or {}
    if api_ref.get("path"):
        path = ROOT / api_ref["path"]
        if path.is_file():
            return json.loads(path.read_text()), ref(path)
    search = row.get("search_source") or {}
    if search.get("path"):
        path = ROOT / search["path"]
        if path.is_file():
            data = json.loads(path.read_text())
            item = next((item for item in data.get("items", [])
                         if item["full_name"].casefold() == row["full_name"].casefold()), {})
            if item:
                return item, ref(path)
    return {}, None


def make_selection(c02, sheet):
    """Preserve all selected records; aliases merge only verified identity."""
    selected = {}
    for old in c02["repositories"]:
        key = curation.normalize_github_repo(old.get("canonical_full_name") or old["full_name"])
        config_addition = bool(set(curation.identity_links(old)["identity_aliases"]) & CONFIG_ADDITIONS)
        if old.get("inclusion", {}).get("status") == "included" or config_addition:
            selected[key] = {"full_name": old.get("canonical_full_name") or old["full_name"],
                             "c02": copy.deepcopy(old), "team_rows": [],
                             "c02_included": old.get("inclusion", {}).get("status") == "included",
                             "config_addition": config_addition}
    for team in sheet:
        key = team["repository_key"]
        if key is None:
            key = "missing/team-item-" + str(team["sheet_item"])
        matches = [old for old in c02["repositories"]
                   if team["repository_key"] in curation.identity_links(old)["identity_aliases"]]
        if len(matches) > 1:
            raise ValueError("ambiguous_team_repository_identity")
        old = matches[0] if matches else None
        if old:
            key = curation.normalize_github_repo(old.get("canonical_full_name") or old["full_name"])
        seed = selected.setdefault(key, {"full_name": old.get("canonical_full_name") or old["full_name"] if old
                                       else team["repository_url_declared"].rstrip("/").split("github.com/")[-1],
                                       "c02": copy.deepcopy(old), "team_rows": [],
                                       "c02_included": False, "config_addition": False})
        seed["team_rows"].append(copy.deepcopy(team))
    return [selected[key] for key in sorted(selected)]


def introductory_evidence(clone, tree, api, api_source, team_rows):
    """Select purpose statements before usage/install/example sections.

    This does not keyword-vote over dependency lists or full README bodies.
    At most the first two substantive introduction sentences are retained.
    """
    evidence = []
    candidates = []
    readmes = sorted(path for path in tree if len(Path(path).parts) == 1
                     and Path(path).name.lower() in {"readme.md", "readme", "readme.rst", "readme.txt"})
    for name in readmes[:1]:
        path = clone / name
        if path.is_symlink() or not path.is_file():
            continue
        raw = path.read_bytes()
        fenced = False
        for number, original in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if number > 130 or len(candidates) >= 2:
                break
            line = original.strip()
            if line.startswith("```") or line.startswith("~~~"):
                fenced = not fenced
                continue
            if fenced:
                continue
            if re.match(r"^#{1,6}\s+", line):
                if re.search(r"install|usage|quick.?start|example|demo|build|test|contribut|package|audit|licen[sc]e|develop|setup", line, re.I):
                    break
                continue
            if (not line or line.startswith(("<", "![", "[![", "- ", "* ", "| --", "<!--"))
                    or line.count("|") > 3 or len(line.split()) < 7):
                continue
            line = line.strip("| ")
            if "shields.io" in line or re.match(r"^\[[^]]+\]\([^)]*\)$", line):
                continue
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line)
            for sentence in sentences:
                if 7 <= len(sentence.split()) <= 85 and len(sentence) <= 700:
                    candidates.append(curation.make_evidence(sentence, "readme", rel(path), digest(raw), number))
                    if len(candidates) >= 2:
                        break
    evidence.extend(candidates)
    description = api.get("description")
    if description and api_source and not candidates:
        evidence.append(curation.make_evidence(description.replace("\n", " ").replace("\r", " "),
                                               "description", api_source["path"], api_source["sha256"]))
    # Team use claims supplement identity and intent, while ambiguity is preserved.
    for row in team_rows:
        text = row.get("usage_evidence_declared")
        if text:
            evidence.append(curation.make_evidence(text, "csv", row["source"]["path"], row["source"]["sha256"],
                                                   row["field_source_lines"].get("usage_evidence_declared")))
    result = curation.classify_repository(evidence)
    result["selection_rule"] = "first_two_substantive_intro_sentences_before_operational_sections; description_if_no_intro; team_claims"
    result["topics_declared"] = list(api.get("topics", []))
    result["topics_source"] = api_source
    return result


def parse_tree(raw):
    tree = {}
    for entry in raw.split(b"\0"):
        if entry:
            head, path = entry.split(b"\t", 1)
            mode, kind, object_id = head.decode().split()
            tree[path.decode("utf-8", errors="surrogateescape")] = {
                "mode": mode, "kind": kind, "git_object": object_id}
    return tree


def census_one(seed, base, catalog):
    folder = base / "repositories" / seed["full_name"].replace("/", "__")
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "curation.json"
    if output.exists():
        existing = json.loads(output.read_text())
        if existing.get("procedure_sha256") != PROCEDURE_SHA:
            raise ValueError("existing_curation_procedure_mismatch")
        return existing
    clone, logs = folder / "clone", folder / "collection-logs"
    logs.mkdir(exist_ok=True)
    old = seed["c02"]
    row = {"schema_version": 1, "owner": "miiz", "procedure_sha256": PROCEDURE_SHA,
           "full_name": seed["full_name"], "url": "https://github.com/" + seed["full_name"],
           "source_memberships": list(old.get("source_memberships", [])) if old else [],
           "source_spellings": list(old.get("source_spellings", [old["full_name"]])) if old else [seed["full_name"]],
           "c02_included": seed["c02_included"], "config_addition": seed["config_addition"],
           "team_curated": bool(seed["team_rows"]), "team_rows": seed["team_rows"],
           "clone_path": rel(clone), "started_at": now(), "commands": [], "collection_errors": [],
           "commit_sha": old.get("commit_sha") if old else None, "entrypoints": [],
           "config_inventory": {"entries": [], "failures": []},
           "license": {"status": "unknown"}, "recent_commit": None,
           "classification": curation.classify_repository([]), "main_eligible": None,
           "preparation_results_accessed": False, "repository_programs_executed": 0}
    if seed["team_rows"]:
        row["source_memberships"].append("team_curated")
    if seed["config_addition"]:
        row["source_memberships"].append("c02_config_addition")
    row["source_memberships"] = list(dict.fromkeys(row["source_memberships"]))
    if old:
        row["c02_metadata_source"] = ref(ROOT / old["metadata_path"])
        row["c02_entrypoints"] = copy.deepcopy(old.get("entrypoints", []))
        row["c02_source_commit_sha"] = old.get("commit_sha")
        api, api_source = _existing_api(old)
        row["canonical_full_name"] = old.get("canonical_full_name") or old["full_name"]
        row["canonical_resolution"] = old.get("canonical_resolution", "unknown")
        row["lineage"] = copy.deepcopy(old.get("lineage", {}))
    else:
        api, retrieval = retrieve_repository(seed["full_name"], logs)
        api_source = {k: retrieval[k] for k in ("path", "sha256")} if retrieval.get("path") else None
        row["repository_api"] = retrieval
        row["canonical_full_name"] = api.get("full_name") or seed["full_name"]
        row["canonical_resolution"] = "github_metadata" if api else "unknown"
        row["lineage"] = {k: api.get(k) for k in ("fork", "archived", "default_branch")}
        row["lineage"].update({k: (api.get(k) or {}).get("full_name") for k in ("parent", "source")})
    row["metadata_api_source"] = api_source
    row["canonical_redirect"] = row["full_name"].casefold() != row["canonical_full_name"].casefold()
    if old and row["lineage"].get("fork") and not row["lineage"].get("parent"):
        fresh, retrieval = retrieve_repository(row["canonical_full_name"], logs)
        row["lineage_refresh"] = retrieval
        if fresh:
            row["lineage"].update({k: (fresh.get(k) or {}).get("full_name") for k in ("parent", "source")})
    row["exposure_c03"] = curation.compare_exposure(
        row, catalog["projects"], catalog["development_exposure"]["projects"])
    row["prior_exposure_c02"] = copy.deepcopy(old.get("exposure", {})) if old else None
    try:
        if clone.exists():
            raise FileExistsError("partial_clone_exists_preserve_failed_attempt_use_new_version")
        if old and (ROOT / old["clone_path"] / ".git").exists():
            args = ["clone", "--no-hardlinks", "--no-checkout", "--no-recurse-submodules",
                    str(ROOT / old["clone_path"]), str(clone)]
            row["clone_origin"] = "isolated_local_c02_object_copy"
        else:
            args = ["clone", "--depth", "1", "--no-checkout", "--single-branch", "--no-tags",
                    "--no-recurse-submodules", "https://github.com/" + row["canonical_full_name"] + ".git", str(clone)]
            row["clone_origin"] = "public_default_head"
        record, _ = git(args, logs, "clone")
        row["commands"].append(record)
        if record["status"] != "ok":
            raise RuntimeError("clone_" + record["status"])
        # A local partial clone must fetch missing blobs into C-03, not C-02.
        record, _ = git(["remote", "set-url", "origin", "https://github.com/" + row["canonical_full_name"] + ".git"],
                        logs, "origin", clone)
        row["commands"].append(record)
        sha = row["commit_sha"] or "HEAD"
        record, raw = git(["show", "-s", "--format=%H%n%cI", sha], logs, "head", clone)
        row["commands"].append(record)
        if record["status"] != "ok":
            raise RuntimeError("head_" + record["status"])
        sha, date = raw.decode().strip().splitlines()[:2]
        if row["commit_sha"] and row["commit_sha"] != sha:
            raise RuntimeError("pinned_c02_commit_mismatch")
        row["commit_sha"], row["commit_committer_date"] = sha, date
        row["recent_commit"] = dt.datetime.fromisoformat(date) >= CUTOFF
        record, _ = git(["checkout", "--detach", sha], logs, "checkout", clone)
        row["commands"].append(record)
        if record["status"] != "ok":
            raise RuntimeError("checkout_" + record["status"])
        record, raw = git(["ls-tree", "-rz", sha], logs, "tree", clone)
        row["commands"].append(record)
        if record["status"] != "ok":
            raise RuntimeError("tree_" + record["status"])
        tree = parse_tree(raw)
        row["uninitialized_submodule_paths"] = [p for p, info in tree.items() if info["kind"] == "commit"]
        row["license"] = license_evidence(clone, tree, api.get("license"))
        row["classification"] = introductory_evidence(clone, tree, api, api_source, seed["team_rows"])
        errors, mains, versions = [], [], set()
        for path, info in tree.items():
            if not path.endswith(".circom"):
                continue
            source = clone / path
            if info["mode"] == "120000" or source.is_symlink():
                errors.append({"path": path, "reason": "circom_symlink_not_followed"})
                continue
            try:
                raw = source.read_bytes()
                content = raw.decode("utf-8")
                # Declaration inventory only; no semantic interpretation or execution.
                for match in re.finditer(r"\bpragma\s+circom\s+([0-9]+\.[0-9]+\.[0-9]+)\s*;", content):
                    versions.add(match.group(1))
                for declaration in main_declarations(content):
                    mains.append({"path": path, **declaration, "sha256": digest(raw),
                                  "git_blob": info["git_object"], "path_roles": path_roles(path),
                                  "entrypoint_kind": "original"})
            except (OSError, UnicodeError, ValueError) as error:
                errors.append({"path": path, "reason": str(error)})
        by_path = {entry["path"]: entry for entry in mains}
        for known in row.get("c02_entrypoints", []):
            if known["path"] not in by_path:
                retained = copy.deepcopy(known)
                retained.update(entrypoint_kind="original", current_inventory_verification="unknown")
                mains.append(retained)
                errors.append({"path": known["path"], "reason": "c02_entrypoint_retained_but_not_redetected"})
        row["entrypoints"] = sorted(mains, key=lambda entry: (entry["path"], entry.get("line", 0)))
        row["pragma_versions_declared"] = sorted(versions)
        row["circom_file_count"] = sum(path.endswith(".circom") for path in tree)
        row["entrypoint_inventory"] = {"status": "incomplete" if errors or row["uninitialized_submodule_paths"] else "complete",
                                       "errors": errors, "scope": "tracked_files_before_submodule_setup",
                                       "entrypoint_count": len(mains)}
        row["config_inventory"] = config_entries.discover_config_entrypoints(clone)
        ready = sum(entry.get("generation_status") == "ready" for entry in row["config_inventory"]["entries"])
        row["config_ready_count"] = ready
        row["entrypoint_condition"] = bool(mains or ready)
        row["main_eligible"] = bool(row["recent_commit"] and row["license"]["status"] == "declared"
                                    and row["entrypoint_condition"])
        row["eligibility_reasons"] = ([] if row["recent_commit"] else ["date_before_2025_01_01"]) + (
            [] if row["license"]["status"] == "declared" else ["license_" + row["license"]["status"]]) + (
            [] if row["entrypoint_condition"] else ["no_original_or_ready_config_entrypoint"])
        row["collection_status"] = "complete"
        row["c03_metadata_exposure"] = {"observed_at": now(),
            "scope": "pinned_checkout; introductory_README; root_license; main_pragma_declarations; declarative_JSON_metadata"}
    except (OSError, ValueError, RuntimeError) as error:
        row["collection_status"] = "failed"
        row["collection_errors"].append({"reason": str(error)})
        row["eligibility_reasons"] = ["collection_failure_eligibility_unknown"]
        if seed["team_rows"]:
            row["classification"] = introductory_evidence(clone, {}, api, api_source, seed["team_rows"])
    row["finished_at"] = now()
    row["metadata_path"] = rel(output)
    write_new(output, row)
    print(json.dumps({"repository": row["full_name"], "status": row["collection_status"],
                      "original_mains": len(row["entrypoints"]), "config_ready": row.get("config_ready_count"),
                      "role": row["classification"]["classification"], "main_eligible": row["main_eligible"]}), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "runs/c03-corpus-2026-10-02")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    base = args.base.resolve()
    if not 1 <= args.workers <= 4:
        raise ValueError("collection_workers_must_be_1_to_4")
    lock = json.loads((base / "procedure-lock.json").read_text())
    if lock["sha256"] != PROCEDURE_SHA or digest((ROOT / lock["procedure_path"]).read_bytes()) != PROCEDURE_SHA:
        raise ValueError("frozen_procedure_hash_mismatch")
    if (base / "census.json").exists() or (base / "curation-lock.json").exists():
        raise FileExistsError("preserve_frozen_census_use_new_version")
    c02_path = ROOT / "runs/c02-corpus-2026-10-02/repositories-v2.json"
    catalog_path = ROOT / "runs/c02-corpus-2026-10-02/catalog_sources.json"
    sheet_path = ROOT / "runs/team-sheet/sheet.csv"
    c02, catalog = json.loads(c02_path.read_text()), json.loads(catalog_path.read_text())
    raw = sheet_path.read_bytes()
    sheet = curation.parse_team_sheet(raw.decode("utf-8-sig"), rel(sheet_path), digest(raw))
    started_at = now()
    sheet_metadata = {"source": ref(sheet_path), "observed_at": started_at,
                      "copy_mtime_utc": dt.datetime.fromtimestamp(sheet_path.stat().st_mtime, dt.timezone.utc).isoformat(),
                      "original_sheet_collection_time": None, "original_sheet_collection_time_status": "unknown",
                      "rows": sheet, "c02_overlap": curation.sheet_overlap(sheet, c02["repositories"])}
    if not (base / "team-sheet-metadata.json").exists():
        write_new(base / "team-sheet-metadata.json", sheet_metadata)
    seeds = make_selection(c02, sheet)
    selection = {"schema_version": 1, "procedure_sha256": PROCEDURE_SHA, "selected_at": started_at,
                 "sources": [ref(c02_path), ref(catalog_path), ref(sheet_path)],
                 "repository_count": len(seeds), "c02_included_count": sum(s["c02_included"] for s in seeds),
                 "team_row_count": len(sheet), "team_repository_count": sum(bool(s["team_rows"]) for s in seeds),
                 "config_addition_count": sum(s["config_addition"] for s in seeds),
                 "repositories": [{k: s[k] for k in ("full_name", "c02_included", "config_addition", "team_rows")}
                                  for s in seeds]}
    if not (base / "selection.json").exists():
        write_new(base / "selection.json", selection)
    if len(seeds) != 80 or selection["c02_included_count"] != 65 or len(sheet) != 14:
        raise ValueError("unexpected_selection_denominator_stop_before_collection")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(census_one, seed, base, catalog) for seed in seeds]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["full_name"].casefold())
    canonical_groups = {}
    for row in results:
        key = row["canonical_full_name"].casefold()
        canonical_groups.setdefault(key, []).append(row["full_name"])
    aggregate = {"schema_version": 1, "task": "C-03", "owner": "miiz", "procedure_sha256": PROCEDURE_SHA,
                 "started_at": started_at, "finished_at": now(), "selection": ref(base / "selection.json"),
                 "team_sheet_metadata": ref(base / "team-sheet-metadata.json"), "repository_count": len(results),
                 "canonical_repository_count": len(canonical_groups), "canonical_groups": canonical_groups,
                 "classification_frozen_before_setup": True, "setup_started": False,
                 "compilation_started": False, "zkfuzz_invocations": 0,
                 "source_exposure_criteria": "metadata_list_matches_do_not_establish_never_exposed",
                 "repositories": results}
    write_new(base / "census.json", aggregate)
    write_new(base / "curation-lock.json", {"schema_version": 1, "frozen_at": now(),
              "procedure_sha256": PROCEDURE_SHA, "census": ref(base / "census.json"),
              "collector": ref(Path(__file__)), "curation_rules": ref(Path(__file__).with_name("c03_curation.py")),
              "repository_count": len(results), "classification_complete_before_setup": True,
              "setup_started": False, "compilation_started": False})
    print(json.dumps({"census": rel(base / "census.json"), "repositories": len(results),
                      "canonical_repositories": len(canonical_groups), "frozen": True}), flush=True)


if __name__ == "__main__":
    main()
