#!/usr/bin/env python3
"""Hash-linked C-03 metadata census summary; never opens circuits or witnesses.

Only completed, identity-consistent censuses can be published. Preview reports
missing records without removing them from denominators. Existing outputs are
never overwritten. No external command or search engine is invoked.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ROLES = ("production", "library", "tool_benchmark", "education_example", "unknown")


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def reference(path):
    path = Path(path).resolve()
    try:
        display = path.relative_to(ROOT).as_posix()
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": digest(path)}


def _path(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def measurement_id(repository, entrypoint_key):
    return hashlib.sha256((repository.lower() + "\x00" + entrypoint_key).encode()).hexdigest()[:24]


def _count(values):
    return dict(sorted(Counter(values).items()))


def _rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def _seconds(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < float("inf") else None


def _sha(value, length=64):
    return isinstance(value, str) and len(value) == length and all(char in "0123456789abcdef" for char in value)


def _timings(values):
    known = [value for value in values if _seconds(value) is not None]
    return {"sum_seconds": sum(known), "known_count": len(known), "unknown_count": len(values) - len(known)}


def _process_starts(stages):
    return _count("started" if stage.get("process_started") is True else "not_started" if stage.get("process_started") is False else "unknown" for stage in stages)


def _failure(stage, name):
    status = stage.get("status") if isinstance(stage, dict) else None
    if status == "success":
        return None
    value = stage.get("failure_type") if isinstance(stage, dict) else None
    return value if isinstance(value, str) and value else name + "_" + (status if isinstance(status, str) else "unknown")


def _stage(stage, name):
    if not isinstance(stage, dict):
        return {"status": "missing", "failure_type": name + "_record_missing"}
    allowed = ("status", "failure_type", "failure_types", "exit_code", "process_started", "elapsed_seconds", "cap_seconds",
               "started_at", "finished_at", "constraints", "report", "artifact", "stdout", "stderr", "expected_targets", "eligible",
               "callsites", "unique_compile_units", "compiler_processes", "callsite_wrapper_statuses", "reported_status", "reported_failure_type")
    result = {key: stage[key] for key in allowed if key in stage}
    result["status"] = stage.get("status", "unknown")
    result["failure_type"] = _failure(stage, name)
    return result


def _role(row):
    value = row.get("classification")
    value = value.get("classification") if isinstance(value, dict) else value
    return value if value in ROLES else "unknown"


def _main_eligible(row):
    value = row.get("main_eligible")
    if type(value) is bool:
        return value
    return None


def _roles(entry):
    metadata = entry.get("metadata") or {}
    roles = metadata.get("path_roles", entry.get("path_roles"))
    if isinstance(roles, list) and roles:
        return roles
    parts = {part.lower() for part in Path(entry.get("display_path", "")).parts}
    found = []
    for role, labels in (("test", {"test", "tests"}), ("example", {"example", "examples", "demo", "demos"}),
                         ("vendor", {"vendor", "vendors", "node_modules", "dependencies"}), ("benchmark", {"bench", "benches", "benchmarks"})):
        if parts & labels:
            found.append(role)
    return found or ["unclassified"]


def _entry_description(entry):
    allowed = ("key", "kind", "display_path", "source_path", "expected_sha256", "failure_type")
    result = {key: entry[key] for key in allowed if key in entry}
    result["path_roles"] = _roles(entry)
    metadata = entry.get("metadata")
    if isinstance(metadata, dict):
        for key in ("config_key", "circomkit", "circuits", "source_sha256", "generation_status", "failure_type", "logical_id_sha256"):
            if key in metadata:
                result[key] = metadata[key]
    return result


def _config_pairing(before, after):
    """A generated wrapper's unchanged text is not a source/config identity."""
    if before.get("kind") != after.get("kind"):
        return "entrypoint_kind_changed"
    if before.get("kind") != "config_generated":
        return "paired"
    fingerprints = []
    for entry in (before, after):
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict) or not _sha(metadata.get("source_sha256")):
            return "config_metadata_unknown"
        config_refs = [metadata.get(key) for key in ("circomkit", "circuits")]
        if any(not isinstance(ref, dict) or not _sha(ref.get("sha256")) or not isinstance(ref.get("path"), str) for ref in config_refs):
            return "config_metadata_unknown"
        fingerprints.append((metadata["source_sha256"], entry.get("source_path"),
                             tuple((ref["path"], ref["sha256"]) for ref in config_refs)))
    if fingerprints[0][:2] != fingerprints[1][:2]:
        return "config_source_changed"
    if fingerprints[0][2] != fingerprints[1][2]:
        return "config_changed"
    return "paired"


class Audit:
    def __init__(self):
        self.errors = []
        self.checked = set()

    def error(self, code, path, **extra):
        self.errors.append({"code": code, "path": str(path), **extra})

    def load(self, path):
        path = Path(path)
        if not path.is_file():
            self.error("missing_metadata_file", path)
            return None
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError("object required")
            return value
        except (OSError, ValueError):
            self.error("invalid_metadata_json", path)
            return None

    def ref(self, ref, context):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str):
            self.error("missing_or_invalid_reference", context)
            return False
        key = (ref["path"], ref["sha256"])
        if key in self.checked:
            return True
        path = _path(ref["path"])
        # Never inspect compiled artifacts or source files to summarize metadata.
        if path.suffix in {".circom", ".r1cs", ".wtns", ".wasm"}:
            self.error("unexpected_nonmetadata_reference", context)
            return False
        if not path.is_file():
            self.error("referenced_file_missing", context, referenced_path=str(path))
            return False
        if digest(path) != ref["sha256"]:
            self.error("reference_hash_mismatch", context, referenced_path=str(path))
            return False
        self.checked.add(key)
        return True


def _inventory(document, census_names, audit, phase):
    output = {}
    if document is None:
        return output
    repos = document.get("repositories")
    if not isinstance(repos, list):
        audit.error("inventory_repository_list_missing", phase)
        return output
    for row in repos:
        if not isinstance(row, dict) or row.get("full_name") not in census_names:
            audit.error("unexpected_inventory_repository", phase)
            continue
        name = row["full_name"]
        if name in output:
            audit.error("duplicate_inventory_repository", phase, repository=name)
            continue
        entries = row.get("entries")
        if not isinstance(entries, list):
            audit.error("entry_list_missing", phase, repository=name)
            entries = []
        by_key = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or not entry["key"]:
                audit.error("invalid_entrypoint_key", phase, repository=name)
                continue
            if entry["key"] in by_key:
                audit.error("duplicate_entrypoint_key", phase, repository=name, entrypoint_key=entry["key"])
                continue
            by_key[entry["key"]] = entry
        output[name] = {"entries": by_key, "failure_type": row.get("failure_type"), "config_report_ref": row.get("config_report_ref"),
                        "config_failures": [{key: failure[key] for key in ("failure_type", "circomkit_path", "circuits_path", "config_key") if key in failure} for failure in row.get("config_failures", [])],
                        "inventory_failures": [{key: failure[key] for key in ("path", "failure_type", "exit_code") if key in failure} for failure in row.get("inventory_failures", [])]}
        if row.get("config_report_ref"):
            audit.ref(row["config_report_ref"], phase + ":" + name + ":config_report")
    for name in census_names - output.keys():
        audit.error("inventory_repository_missing", phase, repository=name)
    return output


def _measurement(path, repository, entry, phase, audit):
    row = audit.load(path)
    if row is None:
        missing = {"status": "missing", "compile": _stage(None, "compile"), "preparation": _stage(None, "preparation")}
        if phase == "after":
            missing["automatic_preparation_outcome"] = _automatic_preparation(missing)
        return missing
    identity = {"repository": repository["full_name"], "commit_sha": repository.get("commit_sha"),
                "entrypoint_key": entry["key"], "phase": phase, "entrypoint_kind": entry.get("kind")}
    for key, value in identity.items():
        if row.get(key) != value:
            audit.error("measurement_identity_mismatch", path, field=key)
    inventory_source_changed = row.get("source_sha256") is not None and row.get("source_sha256") != entry.get("expected_sha256")
    if phase == "before" and inventory_source_changed:
        audit.error("measurement_source_hash_mismatch", path)
    if row.get("source_sha256") is not None and not _sha(row["source_sha256"]):
        audit.error("invalid_measurement_source_hash", path)
    if row.get("compile", {}).get("status") == "success" and row.get("source_sha256") is None:
        audit.error("successful_compile_source_hash_missing", path)
    if row.get("zkfuzz_executions") != 0:
        audit.error("zkfuzz_zero_execution_not_established", path)
    for stage in ("compile",) if phase == "before" else ("compile", "discovery", "preparation"):
        capture = row.get(stage)
        if not isinstance(capture, dict) or not isinstance(capture.get("status"), str):
            audit.error("measurement_stage_missing", path, stage=stage)
            continue
        if capture["status"] != "success" and not capture.get("failure_type"):
            audit.error("non_success_failure_type_missing", path, stage=stage)
        for field in ("report", "stdout", "stderr"):
            if capture.get(field):
                audit.ref(capture[field], str(path) + ":" + stage + ":" + field)
    if row.get("plan"):
        plan = row["plan"]
        if plan.get("status") != "success" and not plan.get("failure_type"):
            audit.error("non_success_failure_type_missing", path, stage="plan")
        if plan.get("report"):
            audit.ref(plan["report"], str(path) + ":plan")
    for key in ("setup_ref", "before_ref"):
        if row.get(key):
            audit.ref(row[key], str(path) + ":" + key)
    answer = {"status": "recorded", "record": reference(path), **identity,
              "source_sha256": row.get("source_sha256"), "settings": row.get("settings"),
              "inventory_source_sha256": entry.get("expected_sha256"), "source_changed_since_inventory": inventory_source_changed,
              "compile": _stage(row.get("compile"), "compile")}
    if phase == "after":
        for stage in ("discovery", "preparation", "plan"):
            answer[stage] = _stage(row.get(stage), stage)
        outcome = row.get("preparation_outcome")
        if isinstance(outcome, dict):
            answer["preparation_outcome"] = {key: outcome[key] for key in
                ("status", "failure_type", "failure_types", "known_valid_units", "declared_eligible_units", "expected_units", "incomplete_evidence", "unknown_reason_codes") if key in outcome}
        answer["setup_ref"] = row.get("setup_ref")
        answer["before_ref"] = row.get("before_ref")
        answer["automatic_preparation_outcome"] = _automatic_preparation(answer)
    return answer


def _automatic_preparation(after):
    compile_stage = after["compile"]
    component = after["preparation"]
    base = {"original_compile_status": compile_stage["status"], "component_preparation_status": component["status"]}
    if compile_stage["status"] == "success":
        return {**base, "status": component["status"], "failure_type": component["failure_type"],
                "failure_types": component.get("failure_types", []) or ([component["failure_type"]] if component["failure_type"] else [])}
    status = "not_started" if compile_stage["status"] == "not_started" else "unknown" if compile_stage["status"] in {"missing", "unknown"} else "failed"
    reason = "original_compile_" + (compile_stage["failure_type"] or compile_stage["status"])
    return {**base, "status": status, "failure_type": reason, "failure_types": [reason]}


def _setup(path, audit, *, require_lockfiles=False):
    setup = audit.load(path)
    if setup is None:
        return {"status": "missing", "failure_types": ["setup_record_missing"], "steps": [], "elapsed_seconds": None}
    if setup.get("zkfuzz_invocations") != 0:
        audit.error("setup_zkfuzz_zero_not_established", path)
    if setup.get("manual_intervention_count") is None:
        audit.error("manual_intervention_count_missing", path)
    if setup.get("status") != "success" and not setup.get("failure_types"):
        audit.error("setup_failure_type_missing", path)
    steps = []
    for step in setup.get("steps", []):
        if step.get("status") != "success" and not step.get("failure_type"):
            audit.error("setup_failure_type_missing", path)
        row = {key: step[key] for key in ("phase", "status", "failure_type", "install_root", "manager", "lockfile_present", "tool") if key in step}
        capture = step.get("capture")
        if isinstance(capture, dict):
            row["capture"] = _stage(capture, "setup")
            for key in ("stdout", "stderr"):
                if capture.get(key):
                    audit.ref(capture[key], str(path) + ":" + key)
        steps.append(row)
    lockfiles = None
    lockfile_path = path.parent / "post-install-lockfiles.json"
    if require_lockfiles or lockfile_path.exists():
        errors_before = len(audit.errors)
        lockfile_data = audit.load(lockfile_path) or {}
        if lockfile_data.get("setup_ref") != reference(path):
            audit.error("post_install_setup_reference_mismatch", lockfile_path)
        plans = []
        for plan in lockfile_data.get("plans", []):
            refs = plan.get("resulting_lockfiles", [])
            for ref in refs:
                audit.ref(ref, str(lockfile_path) + ":resulting_lockfile")
            plans.append({key: plan.get(key) for key in ("install_root", "original_lockfile_present", "resulting_lockfiles")})
        lockfiles = {"record": reference(lockfile_path) if lockfile_path.is_file() else None,
                     "plans": plans, "resulting_lockfiles": sum(len(plan.get("resulting_lockfiles") or []) for plan in plans),
                     "generated_lockfiles": sum(len(plan.get("resulting_lockfiles") or []) for plan in plans if plan["original_lockfile_present"] is False),
                     "status": "verified" if len(audit.errors) == errors_before else "failed",
                     "failure_types": [row["code"] for row in audit.errors[errors_before:]]}
    return {"record": reference(path), "status": setup.get("status", "unknown"),
            "failure_types": setup.get("failure_types", []), "steps": steps,
            "elapsed_seconds": setup.get("elapsed_seconds"), "manual_intervention_count": setup.get("manual_intervention_count"),
            "post_install_lockfiles": lockfiles,
            "started_at": setup.get("started_at"), "finished_at": setup.get("finished_at")}


def _setup_cohort(repo):
    status = repo["setup"]["status"]
    return "success" if status == "success" else "failure" if status == "setup_failure" else "unknown"


def _inventory_completeness(repo):
    availability = repo["entrypoint_availability"]
    failures = repo["inventory_failures"]["after"]
    reasons = set()
    root_failure = failures.get("failure_type")
    if root_failure and root_failure not in {"no_main", "no_known_entrypoint"}:
        reasons.add(root_failure)
    for field in ("config_failures", "inventory_failures"):
        for failure in failures.get(field) or []:
            reasons.add(failure.get("failure_type") or field + "_type_unknown")
    for step in repo["setup"]["steps"]:
        if step.get("phase") in {"clone", "submodule", "tracked_circom_inventory"} and step.get("status") != "success":
            reasons.add(step.get("failure_type") or step["phase"] + "_status_unknown")
    unknown = availability["status"] == "inventory_unknown" or repo["setup"]["status"] in {"missing", "unknown"}
    if availability["status"] == "inventory_unknown":
        reasons.add("after_inventory_missing")
    if repo["setup"]["status"] in {"missing", "unknown"}:
        reasons.add("setup_inventory_coverage_unknown")
    return {"status": "incomplete" if reasons and not unknown else "unknown" if unknown else "no_recorded_failure",
            "scope": "known_entrypoints_after_setup", "known_entrypoints": availability["known_after_count"],
            "reason_codes": sorted(reasons), "complete_source_coverage_established": False}


def _full_preparation_scope(after):
    count = after.get("discovery", {}).get("unique_compile_units")
    if type(count) is not int or count < 0:
        return "unknown"
    return "root_only" if count == 0 else "with_fragments"


def _cohort(repositories):
    entries = [entry for repo in repositories for entry in repo["entries"]]
    after = [entry for entry in entries if entry["after_inventory"] is not None]
    before = [entry for entry in entries if entry["before_inventory"] is not None]
    paired = [entry for entry in entries if entry["pairing"]["status"] == "paired"]
    full_preparation = [entry["after"] for entry in after if entry["after"]["automatic_preparation_outcome"]["status"] == "success"]
    setup_manual = [repo["setup"].get("manual_intervention_count") for repo in repositories]
    collection_manual = [repo.get("manual_collection_transport_interventions") for repo in repositories]
    valid_count = lambda value: type(value) is int and value >= 0
    known_setup = sum(value for value in setup_manual if valid_count(value))
    known_collection = sum(value for value in collection_manual if valid_count(value))
    unknown_setup = sum(not valid_count(value) for value in setup_manual)
    unknown_collection = sum(not valid_count(value) for value in collection_manual)
    unknown_manual_repos = sum(not valid_count(a) or not valid_count(b) for a, b in zip(setup_manual, collection_manual))
    return {"repositories": len(repositories), "main_eligibility": _count("eligible" if repo["main_eligible"] is True else "ineligible" if repo["main_eligible"] is False else "unknown" for repo in repositories),
            "before_entrypoints": len(before), "after_entrypoints": len(after), "union_entrypoints": len(entries),
            "repositories_without_after_entrypoints": sum(not any(e["after_inventory"] for e in r["entries"]) for r in repositories),
            "repository_entrypoint_availability": _count(repo["entrypoint_availability"]["status"] for repo in repositories),
            "repository_inventory_completeness": _count(repo["inventory_completeness"]["status"] for repo in repositories),
            "before_compile_statuses": _count(entry["before"]["compile"]["status"] for entry in before),
            "after_compile_statuses": _count(entry["after"]["compile"]["status"] for entry in after),
            "after_compile_success": _rate(sum(entry["after"]["compile"]["status"] == "success" for entry in after), len(after)),
            "preparation_statuses": _count(entry["after"]["automatic_preparation_outcome"]["status"] for entry in after),
            "component_preparation_statuses": _count(entry["after"]["preparation"]["status"] for entry in after),
            "component_preparation_failure_types": _count(entry["after"]["preparation"]["failure_type"] for entry in after if entry["after"]["preparation"]["failure_type"]),
            "full_preparation_scope": {scope: sum(_full_preparation_scope(result) == scope for result in full_preparation) for scope in ("root_only", "with_fragments", "unknown")},
            "preparation_failure_types": _count(entry["after"]["automatic_preparation_outcome"]["failure_type"] for entry in after if entry["after"]["automatic_preparation_outcome"]["failure_type"]),
            "paired": {"entrypoints": len(paired),
                       "before_compile_success": _rate(sum(e["before"]["compile"]["status"] == "success" for e in paired), len(paired)),
                       "after_compile_success": _rate(sum(e["after"]["compile"]["status"] == "success" for e in paired), len(paired)),
                       "transitions": _count(e["before"]["compile"]["status"] + " -> " + e["after"]["compile"]["status"] for e in paired)},
            "pairing_statuses": _count(entry["pairing"]["status"] for entry in entries),
            "config_generated_before": sum(e["before_inventory"]["kind"] == "config_generated" for e in before),
            "config_generated_after": sum(e["after_inventory"]["kind"] == "config_generated" for e in after),
            "setup_statuses": _count(repo["setup"]["status"] for repo in repositories),
            "setup_failure_types": _count(code for repo in repositories for code in set(repo["setup"].get("failure_types", []))),
            "setup_step_failure_types": _count(code for repo in repositories for step in repo["setup"]["steps"] for code in [step.get("failure_type")] if code),
            "manual_setup_intervention_count": None if unknown_setup else known_setup,
            "manual_setup_intervention_count_unknown_repositories": unknown_setup,
            "manual_collection_transport_retry_count": None if unknown_collection else known_collection,
            "manual_collection_transport_retry_count_unknown_repositories": unknown_collection,
            "manual_intervention_count": None if unknown_manual_repos else known_setup + known_collection,
            "manual_intervention_count_known": known_setup + known_collection,
            "manual_intervention_count_unknown_repositories": unknown_manual_repos,
            "stage_process_starts": {stage: _process_starts([entry["after"].get(stage, {}) for entry in after]) for stage in ("compile", "discovery", "preparation", "plan")},
            "timings": {"setup": _timings([repo["setup"]["elapsed_seconds"] for repo in repositories]),
                        "compile_before": _timings([entry["before"]["compile"].get("elapsed_seconds") for entry in before]),
                        "compile_after": _timings([entry["after"]["compile"].get("elapsed_seconds") for entry in after]),
                        "discovery": _timings([entry["after"].get("discovery", {}).get("elapsed_seconds") for entry in after]),
                        "prepare": _timings([entry["after"]["preparation"].get("elapsed_seconds") for entry in after]),
                        "plan": _timings([entry["after"].get("plan", {}).get("elapsed_seconds") for entry in after])}}


def _transport_retries(census, audit):
    declared = census.get("manual_collection_transport_retry_count")
    ref = census.get("transport_retries")
    rows = census.get("repositories", [])
    known = [row.get("manual_collection_transport_interventions") for row in rows]
    complete = all(type(value) is int and value >= 0 for value in known)
    derived = sum(known) if complete else None
    answer = {"declared_manual_retry_count": declared, "repository_manual_retry_count": derived,
              "record": ref, "repositories": []}
    if declared is not None and declared != derived:
        audit.error("collection_transport_retry_count_mismatch", "census.manual_collection_transport_retry_count")
    if not ref:
        if declared or derived:
            audit.error("collection_transport_retry_reference_missing", "census.transport_retries")
        return answer
    if not audit.ref(ref, "census.transport_retries"):
        return answer
    record = audit.load(_path(ref["path"])) or {}
    if record.get("retry_is_manual_collection_transport_intervention") is not True:
        audit.error("collection_retry_manual_classification_missing", ref["path"])
    prior_ref = record.get("prior_census")
    prior = {}
    if audit.ref(prior_ref, str(ref["path"]) + ":prior_census"):
        prior = audit.load(_path(prior_ref["path"])) or {}
    answer["prior_census"] = prior_ref
    answer["created_at"] = record.get("created_at")
    old_by_name = {row["full_name"]: row for row in prior.get("repositories", [])}
    current_by_name = {row["full_name"]: row for row in rows}
    seen = set()
    for retry in record.get("repositories", []):
        name = retry.get("full_name")
        current = current_by_name.get(name, {})
        old = old_by_name.get(name, {})
        if name in seen or not current or not old:
            audit.error("collection_retry_repository_identity_invalid", ref["path"], repository=name)
        seen.add(name)
        if not _sha(retry.get("commit_sha"), 40) or retry.get("commit_sha") != current.get("commit_sha") or retry.get("commit_sha") != old.get("commit_sha"):
            audit.error("collection_retry_pinned_commit_mismatch", ref["path"], repository=name)
        answer["repositories"].append({"repository": name, "commit_sha": retry.get("commit_sha"),
            "prior_collection_status": old.get("collection_status"), "retry_collection_status": retry.get("collection_status"),
            "manual_collection_transport_interventions": current.get("manual_collection_transport_interventions")})
    expected_names = {row["full_name"] for row in rows if row.get("manual_collection_transport_interventions")}
    if seen != expected_names:
        audit.error("collection_retry_repository_set_mismatch", ref["path"])
    return answer


def _check_locks(run, audit):
    result = {}
    measurement_authority = None
    for name in ("procedure-lock.json", "tools/tools-lock.json", "measurement-lock.json"):
        path = run / name
        document = audit.load(path)
        if document is None:
            continue
        result[name] = {"record": reference(path)}
        if name == "procedure-lock.json":
            audit.ref({"path": document.get("procedure_path"), "sha256": document.get("sha256")}, path)
            result[name].update(frozen_at=document.get("frozen_at"), owner=document.get("owner"))
            result[name]["source_references"] = document.get("source_references", [])
            for ref in document.get("source_references", []):
                valid = audit.ref(ref, str(path) + ":source")
                if valid and Path(ref["path"]).name == "c02_corpus_results_2026-10-02.json":
                    baseline = audit.load(_path(ref["path"])) or {}
                    overall = baseline.get("overall", {})
                    result[name]["c02_baseline"] = {"record": ref, **{key: overall.get(key) for key in
                        ("entrypoint_files", "compile_success_rate", "complete_preparation_rate", "inclusion_statuses")}}
        elif name == "tools/tools-lock.json":
            ref = document.get("tools")
            if audit.ref(ref, path):
                tools = audit.load(_path(ref["path"])) or {}
                result[name]["tools"] = {}
                for label, tool in tools.items():
                    for pin in tool.get("files", []):
                        audit.ref(pin, str(path) + ":" + label)
                    result[name]["tools"][label] = {"version": tool.get("version"), "files": tool.get("files", [])}
        else:
            measurement_authority = document
            for field in ("procedure_ref", "census_ref", "inventory_before_ref"):
                audit.ref(document.get(field), str(path) + ":" + field)
            for ref in document.get("compiler_tools", []) + document.get("implementations", []):
                audit.ref(ref, path)
            if document.get("zkfuzz_executions") != 0 or document.get("workers") != 2:
                audit.error("measurement_policy_lock_mismatch", path)
            result[name].update(compiler_tools=document.get("compiler_tools"), implementations=document.get("implementations"), workers=document.get("workers"), settings=document.get("settings"))
    extension_path = run / "measurement-extension-lock.v2.json"
    if extension_path.exists():
        extension = audit.load(extension_path)
        if extension is not None:
            for field in ("census_ref", "inventory_before_ref", "measurement_v1_ref"):
                audit.ref(extension.get(field), str(extension_path) + ":" + field)
            if measurement_authority is None:
                audit.error("extension_baseline_lock_missing", extension_path)
            else:
                for field in ("census_ref", "inventory_before_ref"):
                    if extension.get(field) != measurement_authority.get(field):
                        audit.error("extension_authority_mismatch", extension_path, field=field)
                if extension.get("measurement_v1_ref", {}).get("sha256") != digest(run / "measurement-lock.json"):
                    audit.error("extension_baseline_lock_mismatch", extension_path)
            implementations = extension.get("implementations")
            if not isinstance(implementations, list) or not implementations:
                audit.error("extension_implementations_missing", extension_path)
            else:
                for pin in implementations:
                    audit.ref(pin, str(extension_path) + ":implementation")
            if (extension.get("schema_version") != 2 or extension.get("zkfuzz_executions") != 0
                    or extension.get("setup_started") is not False or extension.get("compilation_and_preparation") != "unchanged_v1"):
                audit.error("extension_policy_mismatch", extension_path)
            result["measurement-extension-lock.v2.json"] = {"record": reference(extension_path), **{key: extension.get(key) for key in
                ("fixed_at", "census_ref", "inventory_before_ref", "measurement_v1_ref", "implementations", "change", "compilation_and_preparation", "setup_started", "zkfuzz_executions")}}
    return result


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (AttributeError, ValueError, TypeError):
        return None


def _checks_freshness(run, checks, selection, result_paths, audit):
    if selection is None:
        return {"status": "not_finalized", "reason": "v4_selection_absent"}
    start_errors = len(audit.errors)
    path = run / "checks/checks.json"
    pins = checks.get("source_refs")
    if pins is None and audit.ref(checks.get("finalization_ref"), str(path) + ":finalization_ref"):
        pins = (audit.load(_path(checks["finalization_ref"]["path"])) or {}).get("source_refs")
    pins = pins if isinstance(pins, list) else []
    pinned = set()
    for pin in pins:
        if audit.ref(pin, str(path) + ":source"):
            pinned.add(_path(pin["path"]).resolve())
    required = {Path(__file__).resolve(), ROOT / "scripts/audit_c03_tool_provenance.py",
                run / "final-measurement-selection.v4.json", run / "entrypoints-after.v4.json",
                run / "actual-tool-provenance.v4.json"}
    required.update(path.resolve() for path in (ROOT / "tests").glob("c03*_test.py"))
    procedure = audit.load(run / "procedure-lock.json") or {}
    required.update(_path(ref["path"]).resolve() for ref in procedure.get("source_references", []) if Path(ref.get("path", "")).name in
                    {"c02_corpus_procedure_2026-10-02.md", "c02_corpus_results_2026-10-02.md", "c02_corpus_results_2026-10-02.json"})
    for missing in sorted(required - pinned):
        audit.error("check_current_source_reference_missing", path, required_path=str(missing))
    threshold = _timestamp(selection.get("fixed_at"))
    if threshold is None:
        audit.error("check_selection_time_missing", path)
    observed_times = []
    for result_path in result_paths:
        if result_path.parent.name != "after-v4" or not result_path.is_file():
            continue
        result = audit.load(result_path) or {}
        finished = _timestamp(result.get("finished_at"))
        observed_times.append(max(finished or 0, result_path.stat().st_mtime))
    threshold = max([threshold or 0, *observed_times])
    executed = _timestamp(checks.get("executed_at"))
    if checks.get("schema_version") != 2 or executed is None or executed < threshold:
        audit.error("checks_not_fresh_after_active_results", path)
    for command in checks.get("commands", []):
        started, finished = _timestamp(command.get("started_at")), _timestamp(command.get("finished_at"))
        if started is None or finished is None or started < threshold or finished < started or executed is None or finished > executed:
            audit.error("check_command_not_fresh_after_active_results", path, command=command.get("command"))
    return {"status": "verified" if len(audit.errors) == start_errors else "failed", "source_refs": pins,
            "finalization_ref": checks.get("finalization_ref"), "executed_at": checks.get("executed_at"),
            "required_after_utc": datetime.fromtimestamp(threshold, timezone.utc).isoformat(),
            "time_basis": "max(selection.fixed_at, active result.finished_at, active result file mtime)"}


def _checks(run, audit, *, selection=None, result_paths=()):
    path = run / "checks/checks.json"
    checks = audit.load(path)
    if checks is None:
        return {"status": "missing"}
    commands = checks.get("commands", [])
    found = set()
    rows = []
    for check in commands:
        command = check.get("command")
        if not isinstance(command, list):
            audit.error("invalid_check_command", path)
            continue
        executable = Path(command[0]).name if command else ""
        args = command[1:]
        label = None
        if executable == "cargo" and args in (["fmt"], ["fmt", "--check"]):
            label = "fmt"
        elif executable == "cargo" and args == ["clippy", "--all-targets", "--all-features", "--", "-D", "warnings"]:
            label = "clippy"
        elif executable == "cargo" and args == ["test"]:
            label = "test"
        elif executable.startswith("python") and "unittest" in args:
            label = "python"
        if type(check.get("exit_code")) is not int:
            audit.error("check_exit_code_missing", path, command=command)
        if not audit.ref(check.get("log"), str(path) + ":" + str(label)):
            continue
        if label and type(check.get("exit_code")) is int:
            found.add(label)
        row = {key: check[key] for key in ("command", "exit_code", "elapsed_seconds", "log", "started_at", "finished_at") if key in check}
        log_text = _path(check["log"]["path"]).read_text(errors="replace")
        rust_counts = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored;", log_text)
        if label == "test" and rust_counts:
            row["result_counts"] = {key: sum(int(values[index]) for values in rust_counts) for index, key in enumerate(("passed", "failed", "ignored"))}
        python_counts = re.findall(r"Ran (\d+) tests? in", log_text)
        if label == "python" and python_counts:
            row["result_counts"] = {"run": sum(map(int, python_counts))}
        rows.append(row)
    missing = sorted({"fmt", "clippy", "test", "python"} - found)
    if missing:
        audit.error("required_checks_missing", path, checks=missing)
    failed = [row["command"] for row in rows if type(row.get("exit_code")) is int and row["exit_code"] != 0]
    freshness = _checks_freshness(run, checks, selection, result_paths, audit)
    return {"status": "incomplete" if missing else "checks_failed" if failed else "passed", "freshness": freshness,
            "record": reference(path), "commands": rows, "failed_commands": failed,
            "formatter_invocation": "cargo fmt" if any(row["command"][1:] == ["fmt"] for row in rows) else
                "cargo fmt --check (read-only verification)" if any(row["command"][1:] == ["fmt", "--check"] for row in rows) else "missing"}


def _check_census_sources(census, locks, audit):
    start_errors = len(audit.errors)
    rows = census.get("repositories", [])
    if len(rows) != 80 or census.get("repository_count") != 80:
        audit.error("census_recovery_repository_count_mismatch", "census")
    procedure = locks.get("procedure-lock.json", {})
    c02_ref = procedure.get("c02_baseline", {}).get("record")
    c02 = audit.load(_path(c02_ref["path"])) if audit.ref(c02_ref, "census:C02_results") else {}
    included = [row for row in (c02 or {}).get("repositories", []) if row.get("inclusion", {}).get("status") == "included"]
    identity = lambda row: ((row.get("canonical_full_name") or row.get("full_name", "")).lower(), row.get("commit_sha"))
    expected = {identity(row) for row in included}
    observed = {identity(row) for row in rows if row.get("c02_included") is True}
    if len(included) != 65 or len(expected) != 65 or expected != observed or sum(row.get("c02_included") is True for row in rows) != 65:
        audit.error("census_C02_included_identity_mismatch", "census", expected_count=len(expected), observed_count=len(observed))
    records = {}
    for key in ("selection", "team_sheet_metadata"):
        ref = census.get(key)
        records[key] = (audit.load(_path(ref["path"])) or {}) if audit.ref(ref, "census:" + key) else {}
    selection = records["selection"]
    if selection.get("repository_count") != 80 or selection.get("c02_included_count") != 65 or selection.get("team_row_count") != 14:
        audit.error("census_selection_declared_counts_mismatch", "census.selection")
    selected_names = {row.get("full_name", "").lower() for row in selection.get("repositories", [])}
    if len(selected_names) != 80 or selected_names != {row.get("full_name", "").lower() for row in rows}:
        audit.error("census_selection_repository_set_mismatch", "census.selection")
    team = records["team_sheet_metadata"]
    teams = team.get("rows", [])
    team_keys = [row.get("sheet_item") for row in teams]
    if len(teams) != 14 or len(set(team_keys)) != 14:
        audit.error("census_team_row_count_mismatch", "census.team_sheet_metadata")
    wanted_rows = {row.get("sheet_item"): row for row in teams}
    for label, corpus in (("census", rows), ("selection", selection.get("repositories", []))):
        flattened = [(repo, team_row) for repo in corpus for team_row in repo.get("team_rows", [])]
        actual = {row.get("sheet_item"): row for _, row in flattened}
        if len(flattened) != 14 or actual != wanted_rows:
            audit.error("census_team_rows_changed", label)
        for repo, team_row in flattened:
            if repo.get("full_name", "").lower() != team_row.get("repository_key"):
                audit.error("census_team_repository_link_mismatch", label, sheet_item=team_row.get("sheet_item"))
            if label == "census" and (repo.get("team_curated") is not True or "team_curated" not in repo.get("source_memberships", [])):
                audit.error("census_team_membership_missing", label, sheet_item=team_row.get("sheet_item"))
    if sum(row.get("team_curated") is True for row in rows) != 14:
        audit.error("census_team_repository_count_mismatch", "census")
    csv_ref = team.get("source")
    whitespace = []
    if audit.ref(csv_ref, "census:team_csv"):
        with _path(csv_ref["path"]).open(newline="") as stream:
            csv_rows = list(csv.reader(stream))
        for row in teams:
            if row.get("source") != csv_ref:
                audit.error("team_row_csv_source_mismatch", "team_metadata", sheet_item=row.get("sheet_item"))
            for field, line in row.get("field_source_lines", {}).items():
                if type(line) is not int or line < 1 or line > len(csv_rows) or len(csv_rows[line - 1]) != 2:
                    audit.error("team_csv_source_line_invalid", "team_metadata", sheet_item=row.get("sheet_item"), field=field)
                    continue
                raw, declared = csv_rows[line - 1][1], row.get(field)
                if not isinstance(declared, str) or raw.strip() != declared:
                    audit.error("team_csv_value_mismatch", "team_metadata", sheet_item=row.get("sheet_item"), field=field)
                elif raw != declared:
                    whitespace.append({"sheet_item": row.get("sheet_item"), "field": field, "source_line": line, "normalization": "strip leading/trailing whitespace"})
    aliases = [{"full_name": row.get("full_name"), "canonical_full_name": row.get("canonical_full_name"), "commit_sha": row.get("commit_sha")}
               for row in included if row.get("full_name", "").lower() != (row.get("canonical_full_name") or row.get("full_name", "")).lower()]
    return {"status": "verified" if len(audit.errors) == start_errors else "failed", "repository_count": len(rows),
            "C02_included_identities": len(observed), "team_rows": len(teams), "C02_results": c02_ref,
            "selection": census.get("selection"), "team_sheet_metadata": census.get("team_sheet_metadata"), "team_csv": csv_ref,
            "identity_basis": "hash-linked canonical repository name and pinned commit; aliases preserved",
            "C02_aliases": aliases, "csv_whitespace_normalizations": whitespace}


def _check_recovery(run, census_path, inventories, audit):
    path = run / "measurement-recovery-lock.v3.json"
    if not path.exists():
        return None
    lock = audit.load(path)
    if lock is None:
        return None
    reference_fields = ("original_census_ref", "recovery_census_ref", "original_measurement_lock_ref",
                        "original_inventory_before_ref", "inventory_before_ref", "original_setup_interruption_ref", "manager_controls_ref", "clean_checkout_lock_ref")
    verified = {key: audit.ref(lock.get(key), str(path) + ":" + key) for key in reference_fields}
    for key, active in (("recovery_census_ref", census_path), ("inventory_before_ref", run / "entrypoints-before.json")):
        ref = lock.get(key)
        if not isinstance(ref, dict) or not active.is_file() or ref.get("sha256") != digest(active) or _path(ref.get("path", ".")).resolve() != active.resolve():
            audit.error("recovery_active_authority_mismatch", path, field=key)
    if (lock.get("schema_version") != 3 or lock.get("all_repository_clean_restart") is not True
            or lock.get("compilation_and_preparation") != "unchanged_v1" or lock.get("workers") != 2
            or lock.get("zkfuzz_executions") != 0 or lock.get("fixed_before_setup") is not True):
        audit.error("recovery_policy_mismatch", path)
    for pin in lock.get("implementations", []):
        audit.ref(pin, str(path) + ":implementation")
    if not lock.get("implementations"):
        audit.error("recovery_implementations_missing", path)
    current = audit.load(census_path) or {}
    old = audit.load(_path(lock["original_census_ref"]["path"])) if verified["original_census_ref"] else None
    current_rows = {row["full_name"]: row for row in current.get("repositories", [])}
    if old is not None:
        old_rows = {row["full_name"]: row for row in old.get("repositories", [])}
        if current_rows.keys() != old_rows.keys():
            audit.error("recovery_repository_denominator_changed", path)
        for name in current_rows.keys() & old_rows.keys():
            for field in ("commit_sha", "classification", "source_memberships", "main_eligible", "team_curated", "c02_included"):
                if current_rows[name].get(field) != old_rows[name].get(field):
                    audit.error("recovery_census_identity_changed", path, repository=name, field=field)
    if verified["clean_checkout_lock_ref"]:
        clean = audit.load(_path(lock["clean_checkout_lock_ref"]["path"])) or {}
        for field in ("census", "source_census", "helper", "records"):
            audit.ref(clean.get(field), str(path) + ":clean_checkout:" + field)
        if (clean.get("census") != lock.get("recovery_census_ref") or clean.get("source_census") != lock.get("original_census_ref")
                or clean.get("repository_count") != len(current_rows) or clean.get("all_80_original_pinned_commits") is not True
                or clean.get("all_80_clean_worktrees") is not True or clean.get("setup_started") is not False or clean.get("compilation_started") is not False):
            audit.error("recovery_clean_checkout_authority_mismatch", path)
    expected_baselines = {(run / "measurements" / measurement_id(name, key) / "before/result.json").resolve()
                          for name, inventory in inventories["before"].items() for key in inventory["entries"]}
    reused_paths = set()
    for row in lock.get("baseline_records", []):
        original, reused = row.get("original"), row.get("reused")
        original_ok = audit.ref(original, str(path) + ":baseline_original")
        reused_ok = audit.ref(reused, str(path) + ":baseline_reused")
        if not (original_ok and reused_ok):
            continue
        reused_path = _path(reused["path"]).resolve()
        if reused_path in reused_paths:
            audit.error("recovery_duplicate_baseline_record", path, reused_path=str(reused_path))
        reused_paths.add(reused_path)
        if original["sha256"] != reused["sha256"]:
            audit.error("recovery_baseline_bytes_changed", path, reused_path=str(reused_path))
    if reused_paths != expected_baselines:
        audit.error("recovery_baseline_denominator_mismatch", path, expected=len(expected_baselines), observed=len(reused_paths))
    expected_keys = {(name, key) for name, inventory in inventories["before"].items() for key in inventory["entries"]}
    equivalence_keys = set()
    for row in lock.get("clean_source_equivalence", []):
        key = (row.get("repository"), row.get("entrypoint_key"))
        if key in equivalence_keys or key not in expected_keys or row.get("status") != "matched" or not _sha(row.get("expected_sha256")) or row.get("current_sha256") != row.get("expected_sha256"):
            audit.error("recovery_source_equivalence_mismatch", path)
        equivalence_keys.add(key)
    if equivalence_keys != expected_keys:
        audit.error("recovery_source_equivalence_denominator_mismatch", path)
    initial_records = []
    for ref in lock.get("original_setup_records", []):
        if audit.ref(ref, str(path) + ":original_setup"):
            record = audit.load(_path(ref["path"])) or {}
            initial_records.append({"record": ref, "status": record.get("status"), "failure_types": record.get("failure_types", []),
                                    "elapsed_seconds": record.get("elapsed_seconds")})
    initial = lock.get("original_setup_summary", {})
    interrupted = lock.get("original_incomplete_setup_paths", [])
    counts = [initial.get(key) for key in ("completed_repositories", "incomplete_repositories", "not_started_repositories")]
    if (not all(type(value) is int and value >= 0 for value in counts) or sum(counts) != len(current_rows)
            or counts[0] != len(initial_records) or counts[1] != len(interrupted) or initial.get("incomplete_cost_unknown") is not bool(interrupted)):
        audit.error("recovery_original_setup_denominator_mismatch", path)
    controls = audit.load(_path(lock["manager_controls_ref"]["path"])) if verified["manager_controls_ref"] else None
    control_summary = []
    if controls is not None:
        entries = controls.get("controls", [])
        if (controls.get("passed") is not True or controls.get("offline_requested") is not True
                or controls.get("corpus_installs") != 0 or controls.get("zkfuzz_invocations") != 0
                or {row.get("manager") for row in entries} != {"pnpm", "yarn"}):
            audit.error("recovery_manager_controls_not_passed", path)
        for row in entries:
            capture = row.get("capture", {})
            markers = row.get("marker_presence", {})
            if row.get("passed") is not True or capture.get("status") != "success" or capture.get("exit_code") != 0 or any(markers.values()) or not markers:
                audit.error("recovery_manager_control_failure", path, manager=row.get("manager"))
            for key in ("stdout", "stderr"):
                if capture.get(key):
                    audit.ref(capture[key], str(path) + ":manager_control:" + key)
            control_summary.append({"manager": row.get("manager"), "version": row.get("version"), "passed": row.get("passed"),
                                    "elapsed_seconds": capture.get("elapsed_seconds"), "marker_presence": markers})
    return {"record": reference(path), "frozen_at": lock.get("frozen_at"), "reason": lock.get("reason"),
            **{key: lock.get(key) for key in reference_fields}, "implementations": lock.get("implementations", []),
            "all_repository_clean_restart": lock.get("all_repository_clean_restart"), "restarted_repository_count": len(current_rows),
            "baseline_records_reused": len(reused_paths), "clean_source_equivalence_count": len(equivalence_keys),
            "baseline_reuse": "byte_identical_records; not new pre-installation executions",
            "original_setup_summary": initial, "original_setup_records": initial_records, "original_incomplete_setup_paths": interrupted,
            "original_completed_setup_timings": _timings([row["elapsed_seconds"] for row in initial_records]),
            "manager_controls": control_summary, "initial_and_recovery_costs_are_separate": True}


def _read_selection(run, audit):
    path = run / "final-measurement-selection.v4.json"
    if not path.exists():
        return None, run / "entrypoints-after.json", "after"
    selection = audit.load(path)
    if selection is None:
        return None, run / "entrypoints-after.json", "after"
    if (selection.get("schema_version") != 4 or selection.get("active_after_directory") != "after-v4" or selection.get("all_after_entries_remeasured") is not True
            or selection.get("zkfuzz_executions") != 0 or selection.get("workers") != 2):
        audit.error("final_selection_policy_mismatch", path)
    active = run / "entrypoints-after.v4.json"
    ref = selection.get("after_inventory_ref")
    if audit.ref(ref, str(path) + ":after_inventory") and _path(ref["path"]).resolve() != active.resolve():
        audit.error("final_selection_active_inventory_path_mismatch", path)
    return selection, active, "after-v4"


def _selection_controls(controls, selection, context, audit):
    guard = controls.get("original_path_guard", {})
    compiled = controls.get("rebased_compile", {})
    compiler = controls.get("compiler", {})
    if (controls.get("status") != "passed" or controls.get("corpus_executions") != 0
            or controls.get("zkfuzz_executions") != 0 or controls.get("witness_executions") != 0
            or guard.get("status") != "not_started" or guard.get("failure_type") != "entrypoint_outside_pinned_project"
            or guard.get("process_started") is not False or compiled.get("status") != "success"
            or type(compiled.get("constraints")) is not int or compiled["constraints"] != 1
            or not _sha(compiled.get("source_sha256")) or compiler.get("version") != "2.2.3"):
        audit.error("final_selection_path_controls_not_passed", context)
    for key in ("ref", "version_invocation"):
        audit.ref(compiler.get(key), str(context) + ":compiler:" + key)
    for key in ("implementation", "control_script"):
        audit.ref(controls.get(key), str(context) + ":" + key)
    if controls.get("implementation") not in selection.get("implementations", []):
        audit.error("final_selection_path_controls_implementation_mismatch", context)
    refs = []
    for ref in controls.get("raw_refs", []):
        if isinstance(ref, dict) and isinstance(ref.get("path"), str) and Path(ref["path"]).suffix == ".circom":
            if not _sha(ref.get("sha256")) or ref["sha256"] != compiled.get("source_sha256"):
                audit.error("final_selection_path_controls_source_reference_mismatch", context)
            refs.append({**ref, "summary_verification": "hash_metadata_only; source_not_opened"})
        else:
            audit.ref(ref, str(context) + ":raw")
            refs.append(ref)
    return {"status": controls.get("status"), "original_path_guard": guard, "rebased_compile": compiled,
            "compiler": {key: compiler.get(key) for key in ("ref", "version", "version_invocation")}, "raw_refs": refs,
            "control_script": controls.get("control_script"), "implementation": controls.get("implementation"),
            "scope": "normal compilation path control; not corpus or semantic execution"}


def _check_selection(run, selection, census_path, inventories, audit):
    if selection is None:
        return None, set()
    path = run / "final-measurement-selection.v4.json"
    fields = ("after_inventory_ref", "prior_after_inventory_ref", "prior_after_interruption_ref", "path_controls_ref", "census_ref", "before_inventory_ref")
    verified = {key: audit.ref(selection.get(key), str(path) + ":" + key) for key in fields}
    for key, active in (("census_ref", census_path), ("before_inventory_ref", run / "entrypoints-before.json"),
                        ("prior_after_inventory_ref", run / "entrypoints-after.json")):
        ref = selection.get(key)
        if not isinstance(ref, dict) or not active.is_file() or ref.get("sha256") != digest(active) or _path(ref.get("path", ".")).resolve() != active.resolve():
            audit.error("final_selection_authority_mismatch", path, field=key)
    pins = selection.get("implementations", [])
    if not pins:
        audit.error("final_selection_implementations_missing", path)
    for pin in pins:
        audit.ref(pin, str(path) + ":implementation")
    controls = None
    if verified["path_controls_ref"]:
        control_document = audit.load(_path(selection["path_controls_ref"]["path"])) or {}
        controls = _selection_controls(control_document, selection, selection["path_controls_ref"]["path"], audit)
    census = audit.load(census_path) or {}
    census_rows = {row["full_name"]: row for row in census.get("repositories", [])}
    prior_document = audit.load(_path(selection["prior_after_inventory_ref"]["path"])) if verified["prior_after_inventory_ref"] else None
    previous = _inventory(prior_document, set(census_rows), audit, "historical_after")
    previous_keys = {(name, key) for name, row in previous.items() for key in row["entries"]}
    current_keys = {(name, key) for name, row in inventories["after"].items() for key in row["entries"]}
    if previous_keys != current_keys:
        audit.error("final_selection_after_denominator_changed", path)
    for name, key in previous_keys & current_keys:
        old = previous[name]["entries"][key]
        new = inventories["after"][name]["entries"][key]
        old_identity, new_identity = dict(old), dict(new)
        if old.get("kind") == "source_main" and new.get("kind") == "source_main":
            old_identity.pop("path", None); new_identity.pop("path", None)
            clone = census_rows[name].get("clone_path")
            source = new.get("source_path")
            if not isinstance(clone, str) or not isinstance(source, str) or not isinstance(new.get("path"), str):
                audit.error("final_selection_source_path_unknown", path, repository=name, entrypoint_key=key)
            else:
                checkout = _path(clone).resolve()
                expected = (checkout / source).resolve()
                if not expected.is_relative_to(checkout) or _path(new["path"]).resolve() != expected:
                    audit.error("final_selection_source_rebase_mismatch", path, repository=name, entrypoint_key=key)
        if old_identity != new_identity:
            audit.error("final_selection_entry_identity_changed", path, repository=name, entrypoint_key=key)
    expected_prior = {(run / "measurements" / measurement_id(name, key) / "after/result.json").resolve(): (name, key)
                      for name, key in previous_keys}
    historical_paths, historical_records = set(), []
    for ref in selection.get("prior_after_records", []):
        if not audit.ref(ref, str(path) + ":prior_after_record"):
            continue
        record_path = _path(ref["path"]).resolve()
        if record_path in historical_paths or record_path not in expected_prior:
            audit.error("final_selection_prior_record_identity_invalid", path, prior_path=str(record_path))
            continue
        historical_paths.add(record_path)
        name, key = expected_prior[record_path]
        record = audit.load(record_path) or {}
        expected = {"repository": name, "entrypoint_key": key, "commit_sha": census_rows[name].get("commit_sha"), "phase": "after",
                    "entrypoint_kind": previous[name]["entries"][key].get("kind"), "zkfuzz_executions": 0}
        if any(record.get(field) != value for field, value in expected.items()):
            audit.error("final_selection_prior_record_identity_mismatch", path, prior_path=str(record_path))
        historical_records.append({"record": ref, "repository": name, "entrypoint_key": key,
                                   **{stage: _stage(record.get(stage), stage) for stage in ("compile", "discovery", "preparation", "plan")}})
    actual_prior = {p.resolve() for p in (run / "measurements").glob("*/after/result.json")}
    if historical_paths != actual_prior:
        audit.error("final_selection_prior_record_index_incomplete", path, indexed=len(historical_paths), actual=len(actual_prior))
    incomplete_paths = set()
    for incomplete in selection.get("prior_incomplete_after_paths", []):
        incomplete_path = _path(incomplete).resolve()
        if incomplete_path.name == "result.json":
            incomplete_path = incomplete_path.parent
        record_path = incomplete_path / "result.json"
        if incomplete_path in incomplete_paths or record_path not in expected_prior or record_path in historical_paths:
            audit.error("final_selection_incomplete_path_invalid", path, incomplete_path=str(incomplete_path))
        incomplete_paths.add(incomplete_path)
    setup_paths = set()
    for ref in selection.get("setup_records", []):
        if audit.ref(ref, str(path) + ":reused_setup"):
            setup_path = _path(ref["path"]).resolve()
            if setup_path in setup_paths:
                audit.error("final_selection_duplicate_setup_reference", path)
            setup_paths.add(setup_path)
    expected_setups = {(run / "setups" / name.replace("/", "__") / "setup.json").resolve() for name in census_rows}
    if setup_paths != expected_setups:
        audit.error("final_selection_reused_setup_denominator_mismatch", path)
    prior = {"recorded_entrypoints": len(historical_records), "incomplete_entrypoints": len(incomplete_paths),
             "not_started_entrypoints": len(previous_keys) - len(historical_records) - len(incomplete_paths),
             "compile_statuses": _count(row["compile"]["status"] for row in historical_records),
             "compile_failure_types": _count(row["compile"]["failure_type"] for row in historical_records if row["compile"]["failure_type"]),
             "preparation_statuses": _count(row["preparation"]["status"] for row in historical_records),
             "stage_process_starts": {stage: _process_starts([row[stage] for row in historical_records]) for stage in ("compile", "discovery", "preparation", "plan")},
             "stage_timings": {stage: _timings([row[stage].get("elapsed_seconds") for row in historical_records]) for stage in ("compile", "discovery", "preparation", "plan")},
             "incomplete_cost_unknown": bool(incomplete_paths)}
    return {"record": reference(path), "schema_version": selection.get("schema_version"), "fixed_at": selection.get("fixed_at"), **{key: selection.get(key) for key in fields}, "implementations": pins,
            "path_controls": controls,
            "active_after_directory": "after-v4", "remeasured_entrypoints": len(current_keys), "reused_setup_records": selection.get("setup_records", []),
            "prior_after_records": historical_records, "prior_incomplete_after_paths": selection.get("prior_incomplete_after_paths", []),
            "prior_after_summary": prior, "history_excluded_from_active_outcomes": True, "history_and_active_costs_are_separate": True}, historical_paths


def _actual_tool_provenance(run, selection, active_result_paths, audit):
    """Verify the create-only argv audit without reopening measured source data."""
    if selection is None:
        return None
    path = run / "actual-tool-provenance.v4.json"
    start_errors = len(audit.errors)
    if not path.is_file():
        audit.error("actual_tool_provenance_record_missing", path)
        return {"status": "missing"}
    document = audit.load(path)
    if document is None:
        return {"status": "invalid"}
    if (document.get("schema_version") != 1 or document.get("task") != "C-03 actual tool provenance"
            or document.get("status") != "passed" or document.get("mismatches") != []):
        audit.error("actual_tool_provenance_status_invalid", path)
    expected_refs = {
        "selection_ref": run / "final-measurement-selection.v4.json",
        "after_inventory_ref": run / "entrypoints-after.v4.json",
        "measurement_lock_ref": run / "measurement-lock.json",
        "implementation_ref": ROOT / "scripts/audit_c03_tool_provenance.py",
    }
    for field, expected in expected_refs.items():
        ref = document.get(field)
        if not audit.ref(ref, str(path) + ":" + field):
            continue
        if _path(ref["path"]).resolve() != expected.resolve() or ref["sha256"] != digest(expected):
            audit.error("actual_tool_provenance_authority_mismatch", path, field=field)
    census_ref = document.get("census_ref")
    if audit.ref(census_ref, str(path) + ":census_ref") and census_ref != selection.get("census_ref"):
        audit.error("actual_tool_provenance_authority_mismatch", path, field="census_ref")
    coverage = document.get("coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    expected_count = len(active_result_paths)
    if (coverage.get("expected_results") != expected_count or coverage.get("audited_results") != expected_count
            or coverage.get("unexpected_active_results") != 0 or coverage.get("incomplete_active_results") != 0):
        audit.error("actual_tool_provenance_result_coverage_mismatch", path)
    stage_coverage = coverage.get("stages")
    stage_coverage = stage_coverage if isinstance(stage_coverage, dict) else {}
    for stage in ("compile", "discover", "prepare", "plan"):
        row = stage_coverage.get(stage)
        row = row if isinstance(row, dict) else {}
        expected = row.get("expected_invocations")
        observed = row.get("observed_invocations")
        skipped = row.get("not_invoked_by_stage_flow")
        data_validated = row.get("data_path_validated_invocations")
        if (row.get("status") != "passed" or type(expected) is not int or type(observed) is not int
                or type(skipped) is not int or type(data_validated) is not int
                or expected != observed or data_validated != observed or expected + skipped != expected_count
                or row.get("missing_expected_invocations") != 0 or row.get("unexpected_invocations") != 0):
            audit.error("actual_tool_provenance_stage_coverage_mismatch", path, stage=stage)

    recorded_results = set()
    result_rows = document.get("result_records")
    if not isinstance(result_rows, list):
        audit.error("actual_tool_provenance_result_index_invalid", path)
        result_rows = []
    for row in result_rows:
        if not isinstance(row, dict) or not audit.ref(row.get("record"), str(path) + ":result"):
            continue
        result_path = _path(row["record"]["path"]).resolve()
        if result_path in recorded_results:
            audit.error("actual_tool_provenance_duplicate_result", path, result_path=str(result_path))
        recorded_results.add(result_path)
    if recorded_results != {item.resolve() for item in active_result_paths}:
        audit.error("actual_tool_provenance_result_index_mismatch", path,
                    recorded=len(recorded_results), expected=expected_count)

    actual_calls = {item.resolve() for item in (run / "measurements").glob("*/after-v4/*-call/invocation.json")}
    recorded_calls = set()
    call_counts = Counter()
    tool_policy = document.get("tool_path_policy")
    tool_policy = tool_policy if isinstance(tool_policy, dict) else {}
    expected_executables = {"compile": tool_policy.get("compile_executable"),
                            "discover": tool_policy.get("structural_executable"),
                            "prepare": tool_policy.get("structural_executable"),
                            "plan": tool_policy.get("structural_executable")}
    expected_arguments = {
        "compile": {},
        "discover": {"--circom-bin": tool_policy.get("structural_circom_argument")},
        "prepare": {"--circom-bin": tool_policy.get("structural_circom_argument"),
                    "--zkfuzz-bin": (tool_policy.get("forbidden_nonexecuted_tool_arguments") or {}).get("zkfuzz"),
                    "--circomspect-bin": (tool_policy.get("forbidden_nonexecuted_tool_arguments") or {}).get("circomspect")},
        "plan": {},
    }
    call_rows = document.get("call_records")
    if not isinstance(call_rows, list):
        audit.error("actual_tool_provenance_call_index_invalid", path)
        call_rows = []
    call_directories = {"compile": "compile-call", "discover": "discover-call",
                        "prepare": "prepare-call", "plan": "plan-call"}
    for row in call_rows:
        if not isinstance(row, dict) or not audit.ref(row.get("record"), str(path) + ":call"):
            continue
        call_path = _path(row["record"]["path"]).resolve()
        if call_path in recorded_calls:
            audit.error("actual_tool_provenance_duplicate_call", path, call_path=str(call_path))
        recorded_calls.add(call_path)
        stage = row.get("stage")
        if stage not in expected_executables:
            audit.error("actual_tool_provenance_call_stage_invalid", path, stage=stage)
            continue
        if call_path.parent.name != call_directories[stage]:
            audit.error("actual_tool_provenance_call_stage_path_mismatch", path, stage=stage,
                        call_path=str(call_path))
        call_counts[stage] += 1
        if row.get("data_path_validation") != "passed":
            audit.error("actual_tool_provenance_call_data_path_not_validated", path, stage=stage)
        if (not isinstance(row.get("executable_path"), str)
                or Path(row["executable_path"]).resolve() != Path(expected_executables[stage] or ".").resolve()):
            audit.error("actual_tool_provenance_recorded_executable_mismatch", path, stage=stage)
        arguments = row.get("tool_arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        normalized = {key: str(Path(value).resolve()) if isinstance(value, str) else value for key, value in arguments.items()}
        normalized_expected = {key: str(Path(value).resolve()) if isinstance(value, str) else value
                               for key, value in expected_arguments[stage].items()}
        if normalized != normalized_expected:
            audit.error("actual_tool_provenance_recorded_tool_argument_mismatch", path, stage=stage)
    if recorded_calls != actual_calls:
        audit.error("actual_tool_provenance_call_index_mismatch", path,
                    recorded=len(recorded_calls), actual=len(actual_calls))
    for stage, row in stage_coverage.items():
        if isinstance(row, dict) and row.get("observed_invocations") != call_counts.get(stage, 0):
            audit.error("actual_tool_provenance_call_count_mismatch", path, stage=stage)

    tools = document.get("tools")
    tools = tools if isinstance(tools, dict) else {}
    references = tools.get("references")
    references = references if isinstance(references, dict) else {}
    for name in ("recovery_circom", "recovery_zkfdo", "actual_circom", "actual_zkfdo"):
        audit.ref(references.get(name), str(path) + ":tool:" + name)
    c02_lock_ref = document.get("c02_tool_lock_ref")
    c02_lock = None
    if audit.ref(c02_lock_ref, str(path) + ":c02_tool_lock"):
        actual_ref = references.get("actual_zkfdo") or {}
        actual_path = _path(actual_ref.get("path", ".")).resolve()
        expected_lock_path = actual_path.parent.parent / "tool-lock.json"
        lock_path = _path(c02_lock_ref["path"]).resolve()
        if lock_path != expected_lock_path:
            audit.error("actual_tool_provenance_c02_tool_lock_path_mismatch", path)
        c02_lock = audit.load(lock_path) or {}
    lock_pins = {}
    lock_rows = (c02_lock or {}).get("tools")
    if not isinstance(lock_rows, list):
        audit.error("actual_tool_provenance_c02_tool_lock_pin_set_mismatch", path)
        lock_rows = []
    for row in lock_rows:
        if isinstance(row, dict) and isinstance(row.get("path"), str) and isinstance(row.get("sha256"), str):
            name = Path(row["path"]).name
            if name in lock_pins:
                audit.error("actual_tool_provenance_c02_tool_lock_duplicate", path, tool=name)
            lock_pins[name] = {"path": row["path"], "sha256": row["sha256"]}
        else:
            audit.error("actual_tool_provenance_c02_tool_lock_pin_invalid", path)
    if set(lock_pins) != {"circom", "zkfDO"}:
        audit.error("actual_tool_provenance_c02_tool_lock_pin_set_mismatch", path)
    if (c02_lock or {}).get("zkfuzz_executions") != 0:
        audit.error("actual_tool_provenance_c02_tool_lock_policy_mismatch", path)
    for name, ref_key in (("circom", "actual_circom"), ("zkfDO", "actual_zkfdo")):
        pin = lock_pins.get(name) or {}
        actual = references.get(ref_key) or {}
        if (not isinstance(pin.get("path"), str) or not isinstance(actual.get("path"), str)
                or Path(pin["path"]).resolve() != _path(actual["path"]).resolve()
                or pin.get("sha256") != actual.get("sha256")):
            audit.error("actual_tool_provenance_c02_tool_lock_actual_mismatch", path, tool=name)
    if tools.get("c02_tool_lock_pins") != lock_pins:
        audit.error("actual_tool_provenance_c02_tool_lock_record_mismatch", path)
    equivalence = tools.get("actual_alias_recovery_equivalence")
    equivalence = equivalence if isinstance(equivalence, dict) else {}
    for name, recovery_key, actual_key in (("circom", "recovery_circom", "actual_circom"),
                                           ("zkfDO", "recovery_zkfdo", "actual_zkfdo")):
        row = equivalence.get(name)
        row = row if isinstance(row, dict) else {}
        if (row.get("sha256_equal") is not True or row.get("recovery_pin") != references.get(recovery_key)
                or row.get("actual_c02_alias") != references.get(actual_key)
                or (row.get("recovery_pin") or {}).get("sha256") != (row.get("actual_c02_alias") or {}).get("sha256")):
            audit.error("actual_tool_provenance_hash_equivalence_invalid", path, tool=name)
    if tools.get("all_hashes_equivalent") is not True:
        audit.error("actual_tool_provenance_hash_equivalence_invalid", path, tool="all")
    sentinel = document.get("sentinel_absence")
    sentinel = sentinel if isinstance(sentinel, dict) else {}
    sentinel_rows = sentinel.get("paths")
    sentinel_rows = sentinel_rows if isinstance(sentinel_rows, dict) else {}
    expected_sentinels = {"zkfuzz": "/nonexistent/c02-zkfuzz-forbidden",
                          "circomspect": "/nonexistent/c02-analyzer-forbidden"}
    if sentinel.get("status") != "passed" or set(sentinel_rows) != set(expected_sentinels):
        audit.error("actual_tool_provenance_sentinel_absence_invalid", path)
    for name, expected_path in expected_sentinels.items():
        row = sentinel_rows.get(name)
        row = row if isinstance(row, dict) else {}
        if (row.get("path") != expected_path or row.get("exists") is not False
                or row.get("lexists") is not False or row.get("status") != "absent"
                or os.path.lexists(expected_path)):
            audit.error("actual_tool_provenance_sentinel_absence_invalid", path, tool=name)
    if (tool_policy.get("path_divergence_status") != "distinct_paths_with_sha256_equivalent_bytes"
            or not isinstance(tool_policy.get("cause"), str)):
        audit.error("actual_tool_provenance_path_divergence_not_reported", path)
    data_policy = document.get("active_data_path_policy")
    data_policy = data_policy if isinstance(data_policy, dict) else {}
    if data_policy.get("status") != "passed":
        audit.error("actual_tool_provenance_active_data_path_policy_invalid", path)
    return {"status": "verified" if len(audit.errors) == start_errors else "failed",
            "record": reference(path), "generated_at": document.get("generated_at"),
            "audit_scope": document.get("audit_scope"), "coverage": coverage,
            "tool_path_policy": tool_policy, "tools": tools,
            "active_data_path_policy": data_policy,
            "c02_tool_lock_ref": c02_lock_ref, "sentinel_absence": sentinel,
            "census_ref": census_ref,
            "result_record_count": len(recorded_results), "call_record_count": len(recorded_calls)}


def summarize(run_dir, *, allow_incomplete=False):
    run = Path(run_dir).resolve()
    audit = Audit()
    selection, after_inventory_path, after_directory = _read_selection(run, audit)
    inventory_paths = {"before": run / "entrypoints-before.json", "after": after_inventory_path}
    inventory_documents = {phase: audit.load(path) for phase, path in inventory_paths.items()}
    linked = (inventory_documents["before"] or inventory_documents["after"] or {}).get("census_ref")
    census_path = _path(linked["path"]) if isinstance(linked, dict) and isinstance(linked.get("path"), str) else run / "census.json"
    census = audit.load(census_path) or {}
    census_rows = census.get("repositories", [])
    valid_rows = []
    names = set()
    for row in census_rows:
        if not isinstance(row, dict) or not isinstance(row.get("full_name"), str):
            audit.error("invalid_census_repository", census_path)
            continue
        name = row["full_name"]
        if name in names:
            audit.error("duplicate_census_repository", census_path, repository=name)
            continue
        names.add(name)
        valid_rows.append(row)
    inventories = {}
    inventory_refs = {}
    for phase in ("before", "after"):
        path = inventory_paths[phase]
        document = inventory_documents[phase]
        if document:
            audit.ref(document.get("census_ref"), path)
            if document.get("census_ref", {}).get("sha256") != (digest(census_path) if census_path.is_file() else None):
                audit.error("inventory_census_reference_mismatch", path)
            inventory_refs[phase] = reference(path)
        inventories[phase] = _inventory(document, names, audit, phase)
    repos = []
    expected_result_paths = set()
    active_result_paths = set()
    for row in valid_rows:
        name = row["full_name"]
        repo = {key: row[key] for key in ("full_name", "canonical_full_name", "commit_sha", "commit_committer_date", "recent_commit", "license", "eligibility_reasons", "entrypoint_condition", "collection_status", "collection_retry_reason", "manual_collection_transport_interventions", "source_memberships", "c02_included", "team_curated", "classification", "exposure_c03") if key in row}
        repo.update(main_eligible=_main_eligible(row), role=_role(row), entries=[], team_rows=[])
        for team in row.get("team_rows", []):
            repo["team_rows"].append({key: team[key] for key in ("sheet_item", "source", "source_line", "repository_url_declared", "circuit_folders_declared", "usage_evidence_declared", "circom_version_declared", "collection_time_declared", "declarations_verified") if key in team})
        before = inventories["before"].get(name, {}).get("entries", {})
        after = inventories["after"].get(name, {}).get("entries", {})
        repo["inventory_failures"] = {phase: {key: inventories[phase].get(name, {}).get(key) for key in ("failure_type", "config_failures", "inventory_failures", "config_report_ref")} for phase in ("before", "after")}
        availability = "inventory_unknown" if name not in inventories["after"] else "known_entrypoints" if after else "no_known_entrypoint"
        repo["entrypoint_availability"] = {"status": availability, "scope": "after_setup",
            "known_before_count": len(before) if name in inventories["before"] else None,
            "known_after_count": len(after) if name in inventories["after"] else None,
            "source_absence_established": False}
        if availability != "known_entrypoints":
            status = "not_started" if availability == "no_known_entrypoint" else "unknown"
            for stage in ("compile", "preparation"):
                repo["entrypoint_availability"][stage] = {"status": status, "failure_type": availability, "reason_code": availability}
        repo["setup"] = _setup(run / "setups" / name.replace("/", "__") / "setup.json", audit, require_lockfiles=selection is not None)
        repo["inventory_completeness"] = _inventory_completeness(repo)
        for key in sorted(before.keys() | after.keys()):
            entry = {"key": key, "before_inventory": _entry_description(before[key]) if key in before else None,
                     "after_inventory": _entry_description(after[key]) if key in after else None}
            for phase, inventory in (("before", before), ("after", after)):
                if key not in inventory:
                    entry[phase] = None
                    continue
                path = run / "measurements" / measurement_id(name, key) / (after_directory if phase == "after" else "before") / "result.json"
                expected_result_paths.add(path)
                if phase == "after" and after_directory == "after-v4":
                    active_result_paths.add(path)
                entry[phase] = _measurement(path, row, inventory[key], phase, audit)
            if key not in before:
                pair_status = "after_only"
            elif key not in after:
                pair_status = "before_only"
            elif entry["before"]["status"] != "recorded" or entry["after"]["status"] != "recorded":
                pair_status = "measurement_missing"
            elif not entry["before"].get("source_sha256") or not entry["after"].get("source_sha256"):
                pair_status = "source_hash_unknown"
            elif not _sha(row.get("commit_sha"), 40):
                pair_status = "commit_unknown"
            elif entry["before"]["source_sha256"] != entry["after"]["source_sha256"]:
                pair_status = "source_changed"
            elif entry["after"]["source_changed_since_inventory"]:
                pair_status = "after_inventory_source_changed"
            elif not isinstance(entry["before"].get("settings"), dict) or not entry["before"]["settings"] or not isinstance(entry["after"].get("settings"), dict) or not entry["after"]["settings"]:
                pair_status = "settings_unknown"
            elif entry["before"].get("settings") != entry["after"].get("settings"):
                pair_status = "settings_changed"
            else:
                pair_status = _config_pairing(before[key], after[key])
            entry["pairing"] = {"status": pair_status}
            repo["entries"].append(entry)
        repos.append(repo)
    final_selection, historical_paths = _check_selection(run, selection, census_path, inventories, audit)
    actual_paths = set((run / "measurements").glob("*/*/result.json"))
    for path in sorted(actual_paths - expected_result_paths - historical_paths):
        audit.error("unexpected_measurement_record", path)
    locks = _check_locks(run, audit)
    actual_tool_provenance = _actual_tool_provenance(run, selection, active_result_paths, audit)
    checks = _checks(run, audit, selection=selection, result_paths=expected_result_paths)
    census_sources = _check_census_sources(census, locks, audit) if census.get("task") == "C-03" or census.get("checkout_recovery") else {"status": "not_checked"}
    transport_retries = _transport_retries(census, audit)
    recovery = _check_recovery(run, census_path, inventories, audit)
    main = [repo for repo in repos if repo["main_eligible"] is True]
    sources = sorted({source for repo in repos for source in repo.get("source_memberships", [])})
    production_large = []
    for repo in repos:
        if repo["role"] != "production":
            continue
        for entry in repo["entries"]:
            after = entry["after"]
            if after is None:
                continue
            constraints = after["compile"].get("constraints")
            if type(constraints) is int and constraints >= 100000:
                prep = after["automatic_preparation_outcome"]
                production_large.append({"repository": repo["full_name"], "main_eligible": repo["main_eligible"], "team_curated": repo.get("team_curated", False),
                    "entrypoint_key": entry["key"], "path": entry["after_inventory"].get("display_path"),
                    "path_roles": entry["after_inventory"]["path_roles"], "constraints": constraints,
                    "compile_status": after["compile"]["status"], "preparation_status": prep["status"], "component_preparation_status": after["preparation"]["status"],
                    "failure_type": prep["failure_type"], "failure_types": prep.get("failure_types", []), "record": after.get("record")})
    result = {"schema_version": 1, "task": "C-03", "owner": "miiz", "deadline": "2026-10-07",
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "status": "incomplete" if audit.errors else "checks_failed" if checks["status"] == "checks_failed" else "complete",
              "measurement_status": "complete" if not audit.errors else "incomplete",
              "provenance": {"census": reference(census_path) if census_path.is_file() else None, "inventories": inventory_refs, "locks": locks,
                             "team_sheet_metadata": census.get("team_sheet_metadata"),
                             "classification_frozen_before_setup": census.get("classification_frozen_before_setup"),
                             "collection_transport_retries": transport_retries, "recovery": recovery, "final_measurement_selection": final_selection,
                             "actual_tool_provenance": actual_tool_provenance,
                             "census_source_validation": census_sources,
                             "lifting_preservation": {"statement": "C-03 did not edit src/candidate_review/lifting/", "pre_C03_hash_snapshot": None,
                                 "limitation": "No pre-C03 hash snapshot was recorded; finalization hashes describe current state only."}},
              "validation_errors": audit.errors, "checks": checks,
              "c02_baseline": locks.get("procedure-lock.json", {}).get("c02_baseline"),
              "overall": _cohort(repos), "main_eligible_cohort": _cohort(main),
              "team_curated_cohort": _cohort([repo for repo in repos if repo.get("team_curated")]),
              "c02_included_cohort": _cohort([repo for repo in repos if repo.get("c02_included")]),
              "by_role": {role: _cohort([repo for repo in repos if repo["role"] == role]) for role in ROLES},
              "main_by_role": {role: _cohort([repo for repo in main if repo["role"] == role]) for role in ROLES},
              "by_source": {source: _cohort([repo for repo in repos if source in repo.get("source_memberships", [])]) for source in sources},
              "by_setup_status": {status: _cohort([repo for repo in repos if _setup_cohort(repo) == status]) for status in ("success", "failure", "unknown")},
              "inventory_incompleteness": {"statuses": _count(repo["inventory_completeness"]["status"] for repo in repos),
                  "repositories": [{"repository": repo["full_name"], **repo["inventory_completeness"]} for repo in repos if repo["inventory_completeness"]["status"] != "no_recorded_failure"]},
              "production_large_entrypoints": production_large, "repositories": repos,
              "post_install_lockfiles": {"statuses": _count((repo["setup"].get("post_install_lockfiles") or {}).get("status", "unknown") for repo in repos),
                  "resulting_lockfiles": sum((repo["setup"].get("post_install_lockfiles") or {}).get("resulting_lockfiles", 0) for repo in repos),
                  "generated_lockfiles": sum((repo["setup"].get("post_install_lockfiles") or {}).get("generated_lockfiles", 0) for repo in repos),
                  "failure_types": _count(code for repo in repos for code in (repo["setup"].get("post_install_lockfiles") or {}).get("failure_types", []))},
              "cost_scope": {"reported_stage_costs": "selected final attempt; reused before/setup recorded once", "all_attempt_total": None,
                             "reason": "Incomplete prior attempts have unknown total cost; historical known costs are reported separately."},
              "limitations": ["Repository roles are README/topics/team claims, not verified deployment of every entrypoint.",
                  "Sources overlap; team_curated is also reported without the date cutoff. Unknown eligibility remains separate.",
                  "Paired comparison requires the same entrypoint key, commit, non-null source hash and compiler settings; generated mains also require matching source and configuration hashes. Failed compiles remain in the denominator.",
                  "Preparation partial means known valid units exist but whole-entrypoint requirements fail; missing evidence is unknown.",
                  "Automatic preparation additionally requires original entrypoint compilation. Raw component preparation statuses/counts remain separate and cannot make original compilation failure an automatic preparation success.",
                  "Full preparation success is split into root_only, with_fragments and unknown using the recorded discovery unique-unit count; root-only success does not establish fragment readiness.",
                  "C-02 used no dependency setup and different include rules; its counts are not installed-environment applicability or a paired setup effect.",
                  "C-03 uses a frozen environment policy including trusted Yarn Classic only. Unsupported package managers and setup failures are environment-policy limits, not necessarily zkfDO limits. Setup-conditioned cohorts are descriptive and do not replace the overall denominator.",
                  "Entrypoint counts cover enumerated sources/configurations. Configuration, submodule or tracked-inventory failures can leave additional entrypoints unenumerated; no recorded inventory failure is not proof of complete source coverage.",
                  "Compilation/preparation is structural evidence only, not semantic equivalence or defect-detection evidence.",
                  "Stage timings are observed wall sums, not a controlled speed comparison or elapsed corpus wall time.",
                  "The after-v4 compile stage used the recovery tool pin, while discovery/preparation/planning used a distinct C-02 alias path with the same recorded SHA-256 bytes; path identity was not established.",
                  "The fixed driver invokes only compilation/discovery/preparation/planning stages and no candidate or witness stage; zkFuzz zero is recorded, not an independently audited global execution count."]}
    if audit.errors and not allow_incomplete:
        raise ValueError("C-03 finalization blocked: " + json.dumps(audit.errors[:10], ensure_ascii=False))
    return result


def _cell(value):
    return str(value if value is not None else "unknown").replace("|", "\\|").replace("\n", " ")


def _percentage(rate):
    value = rate["rate"]
    return f"{rate['numerator']}/{rate['denominator']}" + (f" ({value:.1%})" if value is not None else " (산출 불가)")


def render_markdown(summary):
    lines = ["# C-03 환경 구성·설정 entrypoint 포함 준비 조사", "", "담당 miiz · 기한 2026-10-07 · 상태: " + summary["status"], "",
             "[사전 고정 절차](c03_corpus_procedure_2026-10-02.md) · [전체 기계 판독 기록](c03_corpus_results_2026-10-02.json)", "",
             "C-02의 무설치 관측을 보존하고, 자동 환경 구성 전후의 동일 entrypoint를 비교했다. 출처층은 겹치며 team_curated는 날짜 조건을 적용한 주 집계와 별도로 제시한다. 저장소의 production 분류는 모든 test/example 파일의 실서비스 사용을 뜻하지 않는다.", "",
             "## 분모와 컴파일 전후 비교", "", "| 집합 | 저장소 | 설치 전/후 entrypoint | paired | 전 성공 | 후 성공 |", "|---|---:|---:|---:|---:|---:|"]
    for label, key in (("전체", "overall"), ("기존 조건 충족 주 집계", "main_eligible_cohort"), ("team_curated 전체", "team_curated_cohort"), ("C-02 포함 집합", "c02_included_cohort")):
        row = summary[key]; pair = row["paired"]
        lines.append(f"| {label} | {row['repositories']} | {row['before_entrypoints']}/{row['after_entrypoints']} | {pair['entrypoints']} | {_percentage(pair['before_compile_success'])} | {_percentage(pair['after_compile_success'])} |")
    lines += ["", "| 성격 층 | 전체 저장소/후 entrypoint | 주 집계 저장소/후 entrypoint | paired 전 성공 | paired 후 성공 | 후 컴파일 성공(전체) | 준비 상태(전체) |", "|---|---:|---:|---:|---:|---:|---|"]
    for role in ROLES:
        row = summary["by_role"][role]; main = summary["main_by_role"][role]
        lines.append(f"| {role} | {row['repositories']}/{row['after_entrypoints']} | {main['repositories']}/{main['after_entrypoints']} | {_percentage(row['paired']['before_compile_success'])} | {_percentage(row['paired']['after_compile_success'])} | {_percentage(row['after_compile_success'])} | {_cell(row['preparation_statuses'])} |")
    lines += ["", "| 출처(중복) | 저장소 | 설치 후 entrypoint | paired 전 성공 | paired 후 성공 |", "|---|---:|---:|---:|---:|"]
    for source, row in summary["by_source"].items():
        lines.append(f"| {_cell(source)} | {row['repositories']} | {row['after_entrypoints']} | {_percentage(row['paired']['before_compile_success'])} | {_percentage(row['paired']['after_compile_success'])} |")
    baseline = summary.get("c02_baseline")
    lines += ["", "### 조건을 구분한 과거·현재 관측", "",
              "| 관측 | 환경·분모 조건 | compile 성공 |", "|---|---|---:|",
              "| C-02 과거 | 의존성 무설치·기존 include 규칙·당시 알려진 entrypoint | " + (_percentage(baseline["compile_success_rate"]) if baseline and baseline.get("compile_success_rate") else "unknown") + " |",
              "| C-03 설치 전 | C-03 include 규칙·같은 key/commit/source/config/settings의 paired 분모 | " + _percentage(summary["overall"]["paired"]["before_compile_success"]) + " |",
              "| C-03 설치 후 | 고정 자동 setup·최종 after-v4·위와 동일한 paired 분모 | " + _percentage(summary["overall"]["paired"]["after_compile_success"]) + " |", "",
              "C-02와 C-03은 수집·include·entrypoint 조건이 다르다. 이 표는 조건을 표시한 기술 통계이며 차이를 설치의 인과 효과나 일반 적용성으로 추정하지 않는다."]
    unavailable = [repo for repo in summary["repositories"] if repo["entrypoint_availability"]["status"] != "known_entrypoints"]
    if unavailable:
        lines += ["", "### 알려진 entrypoint가 없는 저장소", "",
                  "아래 저장소는 저장소 분모에 남겼다. `no_known_entrypoint`는 조사된 목록에서 알려진 main/설정 entrypoint가 없다는 뜻이며 소스에 entrypoint가 없다는 증명은 아니다. entrypoint나 실행 건수를 만들어 넣지 않았다. 설정·목록 조사 실패는 JSON의 inventory_failures에 보존했다.", "",
                  "| 저장소 | entrypoint 가용성 | 알려진 전/후 개수 | 설치 후 compile | 설치 후 preparation | 미시작/미판정 이유 |", "|---|---|---:|---|---|---|"]
        for repo in unavailable:
            availability = repo["entrypoint_availability"]
            lines.append("| " + _cell(repo["full_name"]) + " | " + availability["status"] + " | " +
                         _cell(availability["known_before_count"]) + "/" + _cell(availability["known_after_count"]) + " | " +
                         availability["compile"]["status"] + " | " + availability["preparation"]["status"] + " | " +
                         availability["compile"]["reason_code"] + " |")
    overall = summary["overall"]
    inventory = summary["inventory_incompleteness"]
    lines += ["", "### entrypoint 목록의 알려진 한계", "",
              "저장소별 목록 상태: " + _cell(inventory["statuses"]) + ". `no_recorded_failure`는 기록된 목록 실패가 없다는 뜻이며 소스 전체를 빠짐없이 열거했다는 증명이 아니다. " +
              "설정·submodule·추적 파일 목록 단계가 실패하면 아직 열거하지 못한 entrypoint가 있을 수 있다. 아래 저장소와 알려진 entrypoint는 전체 분모에 유지하며, 알 수 없는 추가 개수를 0으로 확정하지 않는다."]
    if inventory["repositories"]:
        lines += ["", "| 저장소 | 목록 상태 | 알려진 후 entrypoint | 이유 |", "|---|---|---:|---|"]
        for row in inventory["repositories"]:
            lines.append("| " + " | ".join(_cell(row[key]) for key in ("repository", "status", "known_entrypoints", "reason_codes")) + " |")
    lines += ["", "paired 제외·추가 상태: " + _cell(overall["pairing_statuses"]) + ". 성공·실패를 보고 대상을 제거하지 않았다.", "",
              "## 환경 구성·설정 생성·준비", "", "| 항목 | 결과 |", "|---|---|",
              "| 자동 setup 상태 | " + _cell(overall["setup_statuses"]) + " |",
              "| setup 실패 유형(repo별 중복 제거) | " + _cell(overall["setup_failure_types"]) + " |",
              "| setup 실패 유형(단계 occurrence) | " + _cell(overall["setup_step_failure_types"]) + " |",
              "| 설치 후 lockfile 인덱스 상태/실패 | " + _cell(summary["post_install_lockfiles"]["statuses"]) + " / " + _cell(summary["post_install_lockfiles"]["failure_types"]) + " |",
              "| 결과 lockfile 수/새 생성 수 | " + str(summary["post_install_lockfiles"]["resulting_lockfiles"]) + "/" + str(summary["post_install_lockfiles"]["generated_lockfiles"]) + " |",
              f"| config_generated 전/후 | {overall['config_generated_before']}/{overall['config_generated_after']} |",
              f"| 수동 package/include 수선 | {_cell(overall['manual_setup_intervention_count'])} (결측 {overall['manual_setup_intervention_count_unknown_repositories']} repo) |",
              f"| 수동 수집 transport 재시도 | {_cell(overall['manual_collection_transport_retry_count'])} (결측 {overall['manual_collection_transport_retry_count_unknown_repositories']} repo) |",
              f"| 전체 수동 개입 | {_cell(overall['manual_intervention_count'])} (알려진 합계 {overall['manual_intervention_count_known']}, 결측 {overall['manual_intervention_count_unknown_repositories']} repo) |",
              "| 자동 준비 상태(원본 compile 포함) | " + _cell(overall["preparation_statuses"]) + " |",
              "| 원본 기록의 컴포넌트 준비 상태 | " + _cell(overall["component_preparation_statuses"]) + " |",
              "| 완전 준비의 범위(root_only/with_fragments/unknown) | " + _cell(overall["full_preparation_scope"]) + " |",
              "| 준비 실패 유형 | " + _cell(overall["preparation_failure_types"]) + " |", "",
              "자동 완전 준비는 원본 entrypoint 컴파일 성공과 root·모든 고유 단위의 준비·wrapper 컴파일·미지원 없음·plan 성공을 모두 요구한다. 원본 컴파일이 실패하면 컴포넌트 준비가 성공/partial이어도 자동 준비 성공으로 세지 않는다. 원본 준비 상태·개수는 별도로 보존하고 automatic_preparation_outcome만 파생했다. " +
              "**partial**은 재확인된 유효 단위가 있으나 전체 요건에 명시적 실패가 있는 상태다. 유효 단위가 없으면 failed/unsupported, 증거 결측은 unknown으로 보존한다. prepare 프로세스 exit 0 자체는 준비 성공이 아니다. " +
              "완전 성공 중 discovery.unique_compile_units가 0인 root_only, 양수인 with_fragments, 개수 미확인을 별도로 센다. root_only는 조각 준비 성공의 증거로 쓰지 않는다.", "",
              "### 환경 구성 상태별 조건부 결과", "",
              "고정된 환경 정책은 신뢰한 Yarn Classic만 지원한다. 다른 Yarn 버전·package manager/lockfile 비호환과 설치 실패는 환경 구성 정책의 한계일 수 있으므로 모든 실패를 zkfDO의 한계로 해석하지 않는다. " +
              "아래는 조건부 기술 통계이며 setup 실패·미확인 저장소도 전체 집계에 남겼다. setup 성공 부분집합을 전체 적용성으로 대신하지 않는다.", "",
              "| setup 조건 | 저장소 | 알려진 후 entrypoint | 후 컴파일 성공 | 준비 상태 |", "|---|---:|---:|---:|---|"]
    for status, row in summary["by_setup_status"].items():
        lines.append(f"| {status} | {row['repositories']} | {row['after_entrypoints']} | {_percentage(row['after_compile_success'])} | {_cell(row['preparation_statuses'])} |")
    lines += ["", "## production 저장소의 제약 10만 이상", "",
              "경로 역할을 함께 표시한다. 이 목록은 저장소 성격 기준이며 개별 회로의 배포 사용을 인증하지 않는다.", "",
              "| 저장소 | 경로 | 경로 역할 | 제약 수 | 준비 | 실패 유형 |", "|---|---|---|---:|---|---|"]
    for row in summary["production_large_entrypoints"]:
        lines.append("| " + " | ".join(_cell(row[key]) for key in ("repository", "path", "path_roles", "constraints", "preparation_status", "failure_types")) + " |")
    if not summary["production_large_entrypoints"]:
        lines.append("| 해당 관측 없음 | — | — | — | — | — |")
    retries = summary.get("provenance", {}).get("collection_transport_retries", {})
    if retries.get("record"):
        retry_ref = retries["record"]
        target = "../" + retry_ref["path"] if not Path(retry_ref["path"]).is_absolute() else retry_ref["path"]
        lines += ["", "수집 transport 재시도는 " + ", ".join(_cell(row["repository"]) for row in retries.get("repositories", [])) +
                  "에 대한 동일 pinned SHA의 재시도이며 초기 실패 기록을 보존했다. package 설치·include 수선 횟수와 별도로 수동 개입에 포함한다. [재시도 기록](" +
                  target + "), SHA-256 `" + retry_ref["sha256"] + "`."]
    extension = summary.get("provenance", {}).get("locks", {}).get("measurement-extension-lock.v2.json")
    if extension:
        lines += ["", "환경 구성 v2 보완은 설치 시작 전에 별도 고정했다. 초기화된 submodule의 버전 관리 회로도 설치 root 탐색에 포함하며, v1 컴파일·준비 경로와 상한은 유지한다. 고정 시각: " +
                  _cell(extension.get("fixed_at")) + ". 확장 기록: `" + _cell(extension["record"]["path"]) + "`, SHA-256 `" + extension["record"]["sha256"] + "`. v1 기록과 구현 해시 연결은 JSON에 있다."]
    lines += ["", "## 비용·검사·해석", "", "아래 표는 선택된 최종 시도의 알려진 단계 wall 비용이다. 설치 전·환경 구성 재사용은 한 번만 표시한다. 중단된 과거 시도의 전체 비용이 알려지지 않아 **모든 시도를 합한 총비용은 unknown**이며, 과거의 알려진 비용은 아래 이력에서 따로 보고한다.", "",
              "| 단계 | 최종 선택 시도 wall 합계(초) | 시간 알려짐/결측 |", "|---|---:|---:|"]
    for stage, timing in overall["timings"].items():
        lines.append(f"| {stage} | {timing['sum_seconds']:.3f} | {timing['known_count']}/{timing['unknown_count']} |")
    recovery = summary.get("provenance", {}).get("recovery")
    if recovery:
        initial = recovery["original_setup_summary"]
        lines += ["", "### 초기 계측 오류와 전체 재시작", "",
                  "초기 pnpm CLI 옵션 거부를 발견하여 원본 실행을 중단·보존했다. 준비 결과와 관계없이 같은 " +
                  str(recovery["restarted_repository_count"]) + "개 저장소·commit·분류를 유지한 깨끗한 checkout에서 환경 구성과 설치 후 계측을 모두 다시 시작했다. " +
                  str(recovery["baseline_records_reused"]) + "개 설치 전 결과는 원본과 byte-identical인 기록을 재사용했으며 새 실행 횟수로 세지 않는다.", "",
                  "| 초기 setup 기록 | 건수/비용 |", "|---|---:|",
                  "| 기록 완료 저장소 | " + _cell(initial.get("completed_repositories")) + " |",
                  "| 중단 당시 불완전 저장소 | " + _cell(initial.get("incomplete_repositories")) + " |",
                  "| 미시작 저장소 | " + _cell(initial.get("not_started_repositories")) + " |",
                  "| 고정 중단 기록의 알려진 비용(초) | " + _cell(initial.get("known_elapsed_seconds")) + " |",
                  "| 완료 setup 기록의 wall 합계(초) | " + _cell(recovery["original_completed_setup_timings"]["sum_seconds"]) + " |", "",
                  "불완전 setup의 전체 비용은 unknown이며 위의 재시작 실행 비용과 따로 보존한다. 설치 전 기록 재사용 비용은 신규 비용으로 더하지 않는다. " +
                  "수정된 CLI는 고정 pnpm·Yarn의 오프라인 합성 대조에서 명령 성공과 스크립트 미실행을 확인했다. " +
                  "복구 고정 기록: `" + recovery["record"]["path"] + "`, SHA-256 `" + recovery["record"]["sha256"] + "`. 초기 실패·중단·재사용 연결은 JSON provenance.recovery에 있다."]
    selection = summary.get("provenance", {}).get("final_measurement_selection")
    if selection:
        prior = selection["prior_after_summary"]
        lines += ["", "### 설치 후 경로 계측 오류와 전체 재측정", "",
                  "재사용한 설치 전 목록의 source_main 절대 경로가 이전 checkout을 가리키는 계측 오류를 확인하고 해당 설치 후 실행을 중단·보존했다. " +
                  "이전 결과의 성공·실패와 관계없이 같은 " + str(selection["remeasured_entrypoints"]) + "개 after entrypoint 전체를 현재 pinned checkout 경로로 연결한 after-v4에서 재측정했다. " +
                  str(len(selection["reused_setup_records"])) + "개 환경 구성 기록은 그대로 재사용했으며 재설치하지 않았다. 위 결과표는 after-v4만 집계하고 이전 결과로 대체하지 않았다.", "",
                  "| 이전 after 계측 이력 | 건수 |", "|---|---:|",
                  "| 결과 기록 있음 | " + str(prior["recorded_entrypoints"]) + " |",
                  "| 중단 당시 불완전 | " + str(prior["incomplete_entrypoints"]) + " |",
                  "| 미시작 | " + str(prior["not_started_entrypoints"]) + " |",
                  "| 컴파일 상태 | " + _cell(prior["compile_statuses"]) + " |",
                  "| 컴파일 실패 사유 | " + _cell(prior["compile_failure_types"]) + " |", "",
                  "| 이전 after 단계 | 알려진 wall 합계(초) | 시간 알려짐/결측 | 직접 프로세스 시작 |", "|---|---:|---:|---|"]
        for stage, timing in prior["stage_timings"].items():
            lines.append(f"| {stage} | {timing['sum_seconds']:.3f} | {timing['known_count']}/{timing['unknown_count']} | {_cell(prior['stage_process_starts'][stage])} |")
        lines += ["", "이전 기록 개수는 실제 컴파일 실행 횟수와 같지 않으며 not_started도 포함한다. 이전 실행 비용은 최종 after-v4 비용과 별도로 보존하고, 불완전 실행의 전체 비용은 " +
                  ("unknown" if prior["incomplete_cost_unknown"] else "해당 기록 없음") + "이다. 설치 전 기록과 환경 구성의 재사용은 새 실행 비용으로 더하지 않았다. " +
                  "선택 고정 기록: `" + selection["record"]["path"] + "`, SHA-256 `" + selection["record"]["sha256"] + "`. 이전 결과·중단·경로 대조와 신규 목록은 JSON provenance.final_measurement_selection에 연결했다."]
    actual_tools = summary.get("provenance", {}).get("actual_tool_provenance")
    if actual_tools:
        policy = actual_tools.get("tool_path_policy", {})
        tool_rows = actual_tools.get("tools", {}).get("actual_alias_recovery_equivalence", {})
        coverage = actual_tools.get("coverage", {})
        c02_lock = actual_tools.get("c02_tool_lock_ref") or {}
        sentinel_rows = (actual_tools.get("sentinel_absence") or {}).get("paths", {})
        data_policy = actual_tools.get("active_data_path_policy") or {}
        lines += ["", "### 실제 실행 도구 경로 감사", "",
                  "after-v4의 실제 invocation을 전수 검사했다. 직접 원본 컴파일은 recovery-v3 pin을 사용했지만 discovery·prepare·plan은 C-02 tool alias를 사용했다. " +
                  "원인은 `measure_c03_corpus_v4.py`가 `base.RUN`만 바꾸고 `base.legacy.RUN`을 다시 연결하지 않은 데 있다. 두 경로는 같다고 기록하지 않으며, " +
                  "Circom과 zkfDO 각각에서 실제 alias와 recovery pin의 SHA-256이 같음을 별도 확인했다. 이 바이트 동일성은 경로 동일성이나 실행 의미의 독립 검증이 아니다.", "",
                  "| 항목 | 관측 |", "|---|---|",
                  "| 감사 상태 | " + _cell(actual_tools.get("status")) + " |",
                  "| active 결과 감사 | " + _cell(coverage.get("audited_results")) + "/" + _cell(coverage.get("expected_results")) + " |",
                  "| active 데이터 경로 감사 | " + _cell(data_policy.get("status")) + " (inventory·recovery checkout·after-v4 기준) |",
                  "| compile 실제 executable | " + _cell(policy.get("compile_executable")) + " |",
                  "| discovery/prepare/plan 실제 executable | " + _cell(policy.get("structural_executable")) + " |",
                  "| 구조 단계 실제 --circom-bin | " + _cell(policy.get("structural_circom_argument")) + " |",
                  "| Circom alias/pin SHA-256 동일 | " + _cell((tool_rows.get("circom") or {}).get("sha256_equal")) + " |",
                  "| zkfDO alias/pin SHA-256 동일 | " + _cell((tool_rows.get("zkfDO") or {}).get("sha256_equal")) + " |",
                  "| C-02 tool-lock | `" + _cell(c02_lock.get("path")) + "`, SHA-256 `" + _cell(c02_lock.get("sha256")) + "` |",
                  "| zkFuzz 차단 sentinel 부재 | " + _cell((sentinel_rows.get("zkfuzz") or {}).get("status")) + " |",
                  "| analyzer 차단 sentinel 부재 | " + _cell((sentinel_rows.get("circomspect") or {}).get("status")) + " |",
                  "| invocation 기록 | " + _cell(actual_tools.get("call_record_count")) + " |",
                  "| 감사 기록 | `" + _cell((actual_tools.get("record") or {}).get("path")) + "`, SHA-256 `" +
                  _cell((actual_tools.get("record") or {}).get("sha256")) + "` |"]
    lines += ["", "필수 검사 상태: " + summary["checks"]["status"] + ". 명령·exit code·로그 경로와 SHA-256은 JSON의 checks에 있다.", "",
              "| 검사 | exit code | 로그에서 확인한 개수 |", "|---|---:|---|"]
    for check in summary["checks"].get("commands", []):
        lines.append("| " + _cell(" ".join(check["command"])) + " | " + _cell(check["exit_code"]) + " | " + _cell(check.get("result_counts")) + " |")
    baseline = summary.get("c02_baseline")
    old_counts = ("컴파일 " + _percentage(baseline["compile_success_rate"]) + "·완전 준비 " + _percentage(baseline["complete_preparation_rate"])) if baseline and baseline.get("compile_success_rate") and baseline.get("complete_preparation_rate") else "수치 미확인"
    lines += ["", "C-02의 " + old_counts + "은 무설치·기존 include 규칙의 관측이다. C-03 설치 전 기준과도 조건이 다르므로 그 차이를 의존성 설치 효과나 zkfDO의 일반 적용성으로 해석하지 않는다.", "",
              "**고정 driver의 zkFuzz 기록 0회.** 해당 driver는 compile/discovery/prepare/plan만 호출하고 candidate·witness 단계를 호출하지 않는다. 컴퓨터 전체의 실행을 독립 감사한 0회 주장은 아니다. 알려진 entrypoint 목록의 컴파일·준비 결과이며 의미 동등성·결함 탐지 성과가 아니다. 새로운 평가 프로토콜 고정이나 N4-1 전체 완료를 뜻하지 않는다.", "",
              "## 저장소별 근거와 결과", "", "분류 근거 문장·팀의 회로 폴더/실사용 근거/Circom 버전 원문·노출 연결은 JSON에 보존했다.", "",
              "| 저장소 | 성격 | 주 조건 | 출처 | 후 entrypoint | 후 compile 성공 | 준비 상태 |", "|---|---|---|---|---:|---:|---|"]
    for repo in summary["repositories"]:
        stats = _cohort([repo])
        lines.append(f"| {_cell(repo['full_name'])} | {repo['role']} | {_cell(repo['main_eligible'])} | {_cell(repo.get('source_memberships', []))} | {stats['after_entrypoints']} | {_percentage(stats['after_compile_success'])} | {_cell(stats['preparation_statuses'])} |")
    census_sources = summary["provenance"].get("census_source_validation", {})
    lines += ["", "고정 C-02 절차·결과 및 AGENTS·팀 CSV의 검증된 원본 참조는 JSON provenance.locks의 procedure-lock.json.source_references에 보존했다. " +
              "저장소 분모의 원본 대조 상태: " + _cell(census_sources.get("status")) + ". canonical name과 commit으로 이름 변경을 연결하며 별칭은 JSON에 남겼다. " +
              "CSV 공백 정규화 예외: " + _cell(census_sources.get("csv_whitespace_normalizations", [])) + ".", "",
              "C-03은 `src/candidate_review/lifting/`을 수정하지 않았다. 다만 C-03 시작 전 해당 경로의 해시 snapshot은 없어 전후 바이트 동일성을 입증하지 않는다. finalization에 연결된 해시는 현재 상태만 나타낸다."]
    if summary["validation_errors"]:
        lines += ["", "미완료 검증 항목: " + _cell(summary["validation_errors"])]
    return "\n".join(lines) + "\n"


def write_outputs(summary, prefix):
    prefix = Path(prefix)
    json_path = prefix.with_suffix(".json")
    markdown_path = prefix.with_suffix(".md")
    if json_path.exists() or markdown_path.exists():
        raise FileExistsError("use a new version; C-03 outputs are immutable")
    selection = summary.get("provenance", {}).get("final_measurement_selection") or {}
    actual_tools = summary.get("provenance", {}).get("actual_tool_provenance") or {}
    census_sources = summary.get("provenance", {}).get("census_source_validation") or {}
    if (summary.get("status") != "complete" or summary.get("validation_errors") or summary.get("checks", {}).get("status") != "passed"
            or summary.get("checks", {}).get("freshness", {}).get("status") != "verified"
            or selection.get("schema_version") != 4 or selection.get("active_after_directory") != "after-v4"
            or actual_tools.get("status") != "verified"
            or selection.get("remeasured_entrypoints") != 3677 or summary.get("overall", {}).get("after_entrypoints") != 3677
            or summary.get("overall", {}).get("repositories") != 80 or census_sources.get("status") != "verified"):
        raise ValueError("refuse final C-03 output without complete v4 denominator, verified sources and fresh passed checks; preview only")
    text = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    markdown = render_markdown(summary)
    with json_path.open("x") as stream:
        stream.write(text)
    with markdown_path.open("x") as stream:
        stream.write(markdown)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--output-prefix", type=Path)
    args = parser.parse_args()
    if args.preview and args.output_prefix:
        parser.error("preview cannot publish files")
    summary = summarize(args.run_dir, allow_incomplete=args.preview)
    if args.output_prefix:
        write_outputs(summary, args.output_prefix)
    else:
        print(json.dumps({key: summary[key] for key in ("status", "overall", "main_eligible_cohort", "team_curated_cohort", "by_role", "validation_errors")}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
