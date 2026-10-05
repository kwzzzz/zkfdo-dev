#!/usr/bin/env python3
"""Summarize C-02 metadata only; never opens circuits, candidates or compiled artifacts.

An explicit final census selects metadata revisions. Measurement revisions must form
one hash-linked supersedes chain. Output files are created only with --output-prefix,
and only after every included entrypoint file has a measurement record.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("github_top200", "zkbugs", "sok_2026")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path, root):
    root = Path(root).resolve()
    path = Path(path).resolve()
    return {"path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
            "sha256": sha256(path)}


def load(path):
    return json.loads(Path(path).read_text())


def checked_path(link, root):
    root = Path(root).resolve()
    path = (root / link["path"]).resolve()
    if not path.is_relative_to(root) or sha256(path) != link["sha256"]:
        raise ValueError("reference escapes repository or hash mismatch")
    return path


def version_chain(path, root, identity_fields):
    """Newest to oldest; neither filename order nor success selects a revision."""
    path = Path(path).resolve()
    chain, seen = [], set()
    while True:
        if path in seen:
            raise ValueError("cyclic supersedes chain")
        seen.add(path)
        value = load(path)
        if chain and any(value.get(key) != chain[0][1].get(key) for key in identity_fields):
            raise ValueError("superseded record has different execution identity")
        chain.append((reference(path, root), value))
        if not value.get("supersedes"):
            return chain
        previous = checked_path(value["supersedes"], root)
        if previous.parent != path.parent:
            raise ValueError("supersedes must stay inside the same record directory")
        path = previous


def measurements(run, root):
    output = {}
    for directory in sorted((run / "measurements").glob("*")):
        paths = [p.resolve() for p in directory.glob("result*.json")
                 if re.fullmatch(r"result(?:-v[0-9]+)?\.json", p.name)]
        if not paths:
            continue
        replaced = set()
        for path in paths:
            link = load(path).get("supersedes")
            if link:
                previous = checked_path(link, root)
                if previous not in paths:
                    raise ValueError("supersedes refers to a non-measurement record")
                replaced.add(previous)
        heads = set(paths) - replaced
        if len(heads) != 1:
            raise ValueError("measurement revisions lack one explicit supersedes head")
        chain = version_chain(heads.pop(), root,
                              ("repository", "commit_sha", "entrypoint", "source_sha256"))
        if len(chain) != len(paths):
            raise ValueError("measurement revision chain omits a record")
        selected = chain[0][1]
        key = (selected["repository"].casefold(), selected["entrypoint"])
        if key in output:
            raise ValueError("duplicate measurement identity in different directories")
        output[key] = chain
    return output


def reason_class(reason):
    text = str(reason).lower()
    for label, patterns in (
        ("controller_interruption", ("controller-interrupted", "controller stopped", "discovery interrupted")),
        ("missing_include", ("include resolution", "not found", "cannot find", "could not be found", "unresolved include")),
        ("unsupported_syntax", ("unsupported inspection", "unsupported syntax", "not supported", "unsupported")),
        ("concrete_parameters_unavailable", ("concrete root instance", "concrete instance", "noninteger concrete")),
        ("compiler_timeout", ("timed_out true", "timeout", "timed out", "exceeded")),
        ("compiler_unavailable", ("failed to spawn", "compiler unavailable")),
        ("compile_failure", ("compilation", "compile", "structure:")),
        ("duplicate_target", ("duplicate executable", "duplicate target")),
        ("source_snapshot_failure", ("snapshot", "fingerprint")),
        ("report_path_adapter_error", ("uuid subdirectory",)),
        ("discovery_report_unavailable", ("discovery report unavailable",)),
    ):
        if any(pattern in text for pattern in patterns):
            return label
    return "reported_preparation_exclusion"


def reason_metadata(reason):
    # Parser diagnostics can quote source expressions. Keep a class and digest;
    # exact original diagnostic stays in the linked raw metadata record.
    return {"reason_class": reason_class(reason), "reason_subtype": reason_subtype(reason),
            "reason_sha256": hashlib.sha256(str(reason).encode()).hexdigest()}


def reason_subtype(reason):
    """Stable src/targets.rs diagnostic literals, never their source operands."""
    text = str(reason).lower()
    for subtype, literals in (
        ("compile_time_variable_array", ("compile-time variable arrays are unsupported by this mvp",)),
        ("unresolved_compile_time_value", ("unknown compile-time value ",)),
        ("definition_include_closure_contains_main", ("the target source include closure already declares component main",)),
        ("unsupported_component_index", ("component array index is not concrete", "component array index must be non-negative",
                                          "component array index is outside the concrete length", "component array index is unbalanced",
                                          "scalar component cannot be assigned through an array index")),
        ("unsupported_component_array", ("component array length", "component array declaration is unbalanced",
                                          "duplicate component array declarations", "direct component array initialization is unsupported",
                                          "component array assignment has no concrete declaration")),
        ("unsupported_template_parameters", ("template parameters are not concrete", "template parameter list is missing",
                                              "template call parameter list", "empty template argument")),
        ("component_in_while_loop", ("component instantiation inside while loops is unsupported",)),
        ("component_reassignment", ("binding/component reassignment affecting target resolution",
                                      "component is assigned more than once in the concrete expansion")),
        ("unresolved_template_definition", ("template definition is not reachable from the project entrypoint",)),
        ("ambiguous_template_definition", ("multiple reachable definitions use the same template name", "template name is ambiguous")),
        ("unsupported_compile_time_expression", ("compile-time variable is not supported", "unsupported expression token ")),
        ("unresolved_compile_time_condition", ("compile-time condition is not concrete",)),
        ("unsupported_compile_time_loop", ("loop initial value is not concrete", "compile-time for ")),
        ("target_expansion_limit", ("total target expansion exceeded the inspection limit", "instantiation depth exceeded the mvp limit")),
    ):
        if any(literal in text for literal in literals):
            return subtype
    if re.search(r"template expects \d+ parameters but \d+ were supplied", text):
        return "template_parameter_arity"
    return "other_or_unclassified"


def capture(value):
    allowed = ("status", "failure_type", "elapsed_seconds", "cap_seconds", "exit_code",
               "process_started", "started_at", "finished_at", "stdout", "stderr", "report", "interruption")
    result = {key: value[key] for key in allowed if key in value}
    if value.get("reason"):
        result.update(reason_metadata(value["reason"]))
    return result


def stage_attempts(chain):
    """Keep superseded attempts; shared immutable log references identify reuse.

    Matching duration/status alone never establishes reuse. A stage without log
    identity is retained as a separate observation with uncertain identity.
    """
    attempts = {stage: {} for stage in ("compile", "discovery", "preparation", "plan")}
    for link, record in reversed(chain):
        for stage, unique in attempts.items():
            value = record.get(stage, {})
            if not value or value.get("status") in ("not_started", "unsupported"):
                continue
            logs = {name: value[name] for name in ("stdout", "stderr") if isinstance(value.get(name), dict)
                    and value[name].get("path") and value[name].get("sha256")}
            identity = logs if len(logs) == 2 else {"record": link, "stage": stage}
            key = json.dumps(identity, sort_keys=True)
            if key in unique:
                previous = unique[key]
                # Parsing after execution can enrich status/metadata. The actual
                # elapsed interval and process-start observation cannot change.
                for field in ("elapsed_seconds", "process_started"):
                    if previous.get(field) != value.get(field):
                        raise ValueError("reused stage log identity has conflicting execution metadata")
                previous["record_references"].append(link)
            else:
                unique[key] = {**capture(value), "record_references": [link],
                               "identity_status": "log_references" if len(logs) == 2 else "unknown"}
    return {stage: list(unique.values()) for stage, unique in attempts.items()}


def preparation_state(result):
    prepared = result.get("preparation", {})
    reported = prepared.get("status", "not_started")
    if reported != "success":
        return reported
    targets = prepared.get("targets")
    discovery = result.get("discovery", {})
    expected = prepared.get("expected_targets")
    wrappers = discovery.get("callsite_wrapper_statuses")
    complete = (isinstance(expected, int) and expected > 0 and isinstance(targets, list)
                and len(targets) == expected and prepared.get("eligible") == expected
                and all(target.get("eligible") is True for target in targets)
                and discovery.get("entrypoint_status") == "found"
                and discovery.get("unsupported") == [] and isinstance(wrappers, list)
                and len(wrappers) == discovery.get("callsites")
                and all(status == "compile_succeeded" for status in wrappers)
                and expected == discovery.get("unique_compile_units", -2) + 1
                and result.get("plan", {}).get("status") == "success")
    return "success" if complete else "incomplete_report"


def refine_compile_failure(value, record_reference, root):
    """Classify exact compiler error codes from hash-verified raw logs only."""
    result = {"status": "not_applicable", "original_failure_type": value.get("failure_type"),
              "refined_failure_type": None, "rule": "circom-error-code-p1014-v1", "logs": []}
    if value.get("status") != "failure":
        return result
    if not all(isinstance(value.get(stream), dict) and value[stream].get("path")
               and value[stream].get("sha256") for stream in ("stdout", "stderr")):
        result["status"] = "unavailable_missing_log_references"
        return result
    root = Path(root).resolve()
    directory = (root / record_reference["path"]).resolve().parent
    codes = set()
    for stream in ("stdout", "stderr"):
        link = value[stream]
        path = (root / link["path"]).resolve()
        if not path.is_relative_to(directory) or path.name != stream + ".log":
            raise ValueError("compiler refinement may read only this measurement's raw compiler logs")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != link["sha256"]:
            raise ValueError("compiler log hash mismatch during failure refinement")
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", data.decode("utf-8", errors="replace"))
        codes.update(re.findall(r"(?m)^\s*error\[([A-Z][0-9]+)\]", text))
        result["logs"].append({"stream": stream, "path": link["path"], "sha256": link["sha256"]})
    result["diagnostic_codes"] = sorted(codes)
    if "P1014" in codes:
        result.update(status="refined", refined_failure_type="missing_include")
    else:
        result["status"] = "verified_original_class_retained"
    return result


def measurement_summary(chain, root=ROOT):
    link, data = chain[0]
    compile_data = data.get("compile", {})
    compiled = capture(compile_data)
    compiled["status"] = compile_data.get("status", "not_started")
    compiled["failure_refinement"] = refine_compile_failure(compile_data, link, root)
    compiled["failure_type_refined"] = compiled["failure_refinement"]["refined_failure_type"]
    count = compile_data.get("constraints")
    if count is not None and (type(count) is not int or count < 0):
        raise ValueError("invalid constraint count")
    compiled["constraints"] = count if compiled["status"] == "success" else None
    compiled["count_unknown_reason"] = (compile_data.get("count_unknown_reason", "count_not_reported")
                                        if count is None else None)
    if compile_data.get("artifact"):
        compiled["artifact"] = compile_data["artifact"]
    discovery_data = data.get("discovery", {})
    discovery = capture(discovery_data)
    for key in ("entrypoint_status", "callsites", "unique_compile_units", "compiler_processes",
                "callsite_wrapper_statuses"):
        discovery[key] = discovery_data.get(key)
    discovery["unsupported"] = [
        {**{key: item[key] for key in ("source_path", "line") if key in item},
         **reason_metadata(item.get("reason", "unknown"))}
        for item in discovery_data.get("unsupported", [])]
    discovery["wrapper_failure_diagnostics"] = []
    statuses = discovery_data.get("callsite_wrapper_statuses")
    discovery["wrapper_failure_diagnostics_status"] = "unknown_callsite_statuses_missing" if statuses is None else "no_wrapper_failure"
    statuses = statuses or []
    if any(status != "compile_succeeded" for status in statuses):
        discovery["wrapper_failure_diagnostics_status"] = "unknown_discovery_report_missing"
    if any(status != "compile_succeeded" for status in statuses) and discovery_data.get("report"):
        report_link = discovery_data["report"]
        report_path = (root / report_link["path"]).resolve()
        record_directory = (root / link["path"]).resolve().parent
        if report_path.name != "discovery.json" or not report_path.is_relative_to(record_directory):
            raise ValueError("wrapper reasons require this measurement's linked discovery metadata")
        checked_path(report_link, root)
        report = load(report_path)
        if len(report.get("targets", [])) != discovery_data.get("callsites"):
            raise ValueError("linked discovery callsite denominator mismatch")
        if [target.get("wrapper_status") for target in report["targets"]] != statuses:
            raise ValueError("linked discovery wrapper statuses differ from measurement")
        discovery["wrapper_failure_diagnostics_status"] = "recorded"
        for target in report["targets"]:
            if target.get("wrapper_status") != "compile_succeeded":
                reason = (reason_metadata(target["failure_reason"]) if target.get("failure_reason") else
                          {"reason_class": "unknown", "reason_subtype": "unknown_missing_reason", "reason_sha256": None})
                discovery["wrapper_failure_diagnostics"].append({
                    "callsite_identity_sha256": hashlib.sha256(str(target.get("identity")).encode()).hexdigest(),
                    "source_path": target.get("source_path"),
                    "wrapper_status": target.get("wrapper_status"),
                    **reason})
    prepared = data.get("preparation", {})
    preparation = capture(prepared)
    preparation.update(status=preparation_state(data), reported_status=prepared.get("status", "not_started"))
    if prepared.get("reason"):
        preparation.update(reason_metadata(prepared["reason"]))
    for key in ("manifest", "expected_targets", "eligible"):
        preparation[key] = prepared.get(key)
    preparation["targets"] = [
        {**{key: item.get(key) for key in ("label", "eligible", "constraints", "compile_seconds",
                                          "compiler_started", "elapsed_seconds")},
         "exclusion_reasons": [reason_metadata(reason) for reason in item.get("exclusion_reasons", [])]}
        for item in prepared.get("targets", [])]
    history = [{"reference": old_link,
                "preparation_status": old.get("preparation", {}).get("status", "not_started"),
                "preparation_reason": reason_metadata(old.get("preparation", {}).get("reason", "unknown")),
                "stages": {stage: capture(old.get(stage, {}))
                           for stage in ("compile", "discovery", "preparation", "plan")}}
               for old_link, old in chain[1:]]
    return {"status": "recorded", "reference": link, "history": history,
            "implementation_repair": bool(data.get("repair")),
            "repair_reruns": {stage: data.get("repair", {}).get("rerun_" + stage)
                              for stage in ("compile", "discovery")},
            "repair_reason": reason_metadata(data["repair"]["reason"]) if data.get("repair") else None,
            "commit_sha": data.get("commit_sha"), "source_sha256": data.get("source_sha256"),
            "settings": {key: data.get("settings", {}).get(key) for key in ("optimization", "prime")},
            "library_paths": data.get("library_paths", []),
            "manual_interventions": data.get("manual_interventions"),
            "zkfuzz_executions": data.get("zkfuzz_executions"),
            "compile": compiled, "discovery": discovery, "preparation": preparation,
            "plan": capture(data.get("plan", {})), "stage_attempts": stage_attempts(chain)}


def fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def numeric_summary(values, denominator):
    known = [value for value in values if value is not None]
    return {"known": len(known), "unknown": denominator - len(known),
            "minimum": min(known) if known else None,
            "median": statistics.median(known) if known else None,
            "maximum": max(known) if known else None,
            "sum": sum(known) if known else None}


def source_summary(run, root):
    catalog = load(run / "catalog_sources.json")
    pages = []
    for path in sorted(run.glob("github-search-page-*-network.meta.json")):
        data = load(path)
        response = {key: data[key] for key in ("path", "sha256")}
        checked_path(response, root)
        query = parse_qs(urlparse(data["url"]).query)
        pages.append({"metadata": reference(path, root), "response": response,
                      "queried_at": data.get("queried_at"), "http_status": data.get("http_status"),
                      "query_url": data["url"], "query": query.get("q", [None])[0],
                      "sort": query.get("sort", [None])[0], "order": query.get("order", [None])[0],
                      "page": query.get("page", [None])[0], "per_page": query.get("per_page", [None])[0],
                      "total_count": data.get("total_count"), "incomplete_results": data.get("incomplete_results")})
    datasets = []
    for source in catalog.get("sources", []):
        item = {key: source.get(key) for key in ("source", "dataset_repository", "dataset_revision",
                                               "status", "project_count", "circom_project_count",
                                               "metadata_row_count", "circom_metadata_row_count")}
        item["retrievals"] = []
        for retrieval in source.get("retrievals", []):
            value = {key: retrieval.get(key) for key in ("url", "started_at", "finished_at", "status")}
            if retrieval.get("path") and retrieval.get("sha256"):
                link = {key: retrieval[key] for key in ("path", "sha256")}
                checked_path(link, root)
                value["response"] = link
            item["retrievals"].append(value)
        datasets.append(item)
    return {"github_search_pages": pages, "datasets": datasets,
            "catalog_reference": reference(run / "catalog_sources.json", root)}


def check_summary(run, root):
    """Only a pinned log plus recorded exit zero can establish a passed check."""
    manifest = run / "checks/checks.json"
    records, references = [], []
    if manifest.is_file():
        data = load(manifest)
        records.extend(data if isinstance(data, list) else data.get("checks", []))
        references.append(reference(manifest, root))
    python_paths = [path.resolve() for path in run.glob("python-tests.check*.json")
                    if re.fullmatch(r"python-tests\.check(?:-v[0-9]+)?\.json", path.name)]
    python_history = []
    if python_paths:
        replaced = set()
        for path in python_paths:
            supersedes = load(path).get("supersedes")
            if supersedes:
                previous = checked_path(supersedes, root)
                if previous not in python_paths:
                    raise ValueError("Python check supersedes is outside the check record set")
                replaced.add(previous)
        heads = set(python_paths) - replaced
        if len(heads) != 1:
            raise ValueError("Python check records lack one explicit supersedes head")
        chain = version_chain(heads.pop(), root, ("command",))
        if len(chain) != len(python_paths):
            raise ValueError("Python check supersedes chain omits a record")
        records.append(chain[0][1])
        references.append(chain[0][0])
        python_history = [link for link, _ in chain[1:]]
    checks = []
    expected = {
        ("cargo", "fmt"): "cargo_fmt",
        ("cargo", "clippy", "--all-targets", "--all-features", "--", "-D", "warnings"): "cargo_clippy",
        ("cargo", "test"): "cargo_test"}
    python_log = run / "python-tests.log"
    for record in records:
        command = record.get("command", [])
        name = expected.get(tuple(command)) if isinstance(command, list) else None
        if (not name and isinstance(command, list) and command
                and Path(command[0]).name.startswith("python")
                and (root / record.get("path", "")).resolve().parent == run.resolve()
                and re.fullmatch(r"python-tests(?:-v[0-9]+)?\.log", Path(record.get("path", "")).name)):
            name = "python_metadata_tests"
        if not name:
            continue
        item = {"name": name, "status": "unverified", "exit_code": record.get("exit_code"),
                "started_at": record.get("started_at"), "elapsed_seconds": record.get("elapsed_seconds")}
        if not record.get("path") or not record.get("sha256"):
            item["reason"] = "hash_pinned_log_missing"
            checks.append(item)
            continue
        link = {key: record[key] for key in ("path", "sha256")}
        path = (root / link["path"]).resolve()
        if (name.startswith("cargo_") and not path.is_relative_to((run / "checks").resolve())) or path.suffix != ".log":
            raise ValueError("check summary may read only check logs")
        checked_path(link, root)
        text = path.read_text(errors="replace")
        item["log"] = link
        if record.get("exit_code") != 0:
            item.update(status="failed" if record.get("exit_code") is not None else "unverified",
                        reason="recorded_process_exit_not_zero")
        elif name == "cargo_test":
            summaries = re.findall(r"(?m)^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;", text)
            item["counts"] = {"passed": sum(int(row[1]) for row in summaries),
                              "failed": sum(int(row[2]) for row in summaries),
                              "ignored": sum(int(row[3]) for row in summaries), "test_binaries": len(summaries)}
            item["status"] = "passed" if summaries and all(row[0] == "ok" and int(row[2]) == 0 for row in summaries) else "unverified"
            if item["status"] != "passed":
                item["reason"] = "test_summary_missing_or_inconsistent"
        elif name == "python_metadata_tests":
            ran = re.findall(r"(?m)^Ran (\d+) tests? in [0-9.]+s\s*$", text)
            ok = re.findall(r"(?m)^OK(?: \(skipped=\d+\))?\s*$", text)
            item["counts"] = {"ran": sum(map(int, ran)), "suites": len(ran)}
            item["status"] = "passed" if ran and len(ran) == len(ok) and not re.search(r"(?m)^FAILED\b", text) else "unverified"
            if item["status"] != "passed":
                item["reason"] = "python_summary_missing_or_inconsistent"
        else:
            item["status"] = "passed"
        checks.append(item)
    if python_log.is_file() and not any(item["name"] == "python_metadata_tests" for item in checks):
        checks.append({"name": "python_metadata_tests", "status": "unverified",
                       "reason": "log_exists_but_exit_and_pinned_hash_metadata_missing",
                       "log": reference(python_log, root)})
    return {"metadata_references": references, "previous_python_check_references": python_history, "checks": checks,
            "scope": "recorded check executions; counts are not inferred from implementation or file presence"}


def inventory_composition(repositories):
    included = [repo for repo in repositories if repo["inclusion"]["status"] == "included"]
    # Repository identities locate known benchmark/data collections. This is a
    # grouping caveat, not an exclusion rule or a claim that every path has a
    # benchmark marker (these repositories also contain src/ and demo files).
    collections = {"armankolozyan/ccc-check", "dangduongminhnhat/circheck", "zksecurity/zkbugs"}
    selected = [{"repository": repo["full_name"], "entrypoint_files": len(repo["entrypoints"])}
                for repo in included if repo["full_name"].casefold() in collections]
    entries = [entry for repo in included for entry in repo["entrypoints"]]
    count = sum(row["entrypoint_files"] for row in selected)
    return {"known_entrypoint_files": len(entries),
            "path_role_counts_overlapping": dict(Counter(role for entry in entries for role in set(entry["path_roles"]))),
            "identified_collection_repositories": selected,
            "identified_collection_file_fraction": fraction(count, len(entries)),
            "interpretation": "Known main file paths, not independent production circuits. Collection counts group repository identities, not proof of each path's purpose. Unclassified paths do not imply production."}


def group_summary(repos):
    included = [repo for repo in repos if repo["inclusion"]["status"] == "included"]
    entries = [entry for repo in included for entry in repo["entrypoints"]]
    compile_statuses = Counter(entry["measurement"]["compile"]["status"] for entry in entries)
    preparation_statuses = Counter(entry["measurement"]["preparation"]["status"] for entry in entries)
    discovery_statuses = Counter(entry["measurement"].get("discovery", {}).get("status", "not_started") for entry in entries)
    plan_statuses = Counter(entry["measurement"].get("plan", {}).get("status", "not_started") for entry in entries)
    recorded = [entry["measurement"] for entry in entries if entry["measurement"]["status"] == "recorded"]
    counts = [entry["measurement"]["compile"].get("constraints") for entry in entries]
    known_counts = [value for value in counts if value is not None]
    failures = Counter(entry["measurement"]["compile"].get("failure_type_refined")
                       or entry["measurement"]["compile"].get("failure_type") or "reason_unknown"
                       for entry in entries if entry["measurement"]["compile"]["status"]
                       not in ("success", "not_started"))
    original_failures = Counter(entry["measurement"]["compile"].get("failure_type") or "reason_unknown"
                               for entry in entries if entry["measurement"]["compile"]["status"]
                               not in ("success", "not_started"))
    prep_failures = Counter()
    prep_subtypes, discovery_subtypes, wrapper_subtypes = Counter(), Counter(), Counter()
    for value in recorded:
        discovery_subtypes.update(item["reason_subtype"] for item in value["discovery"]["unsupported"])
        wrapper_subtypes.update(item["reason_subtype"] for item in value["discovery"]["wrapper_failure_diagnostics"])
        if value["preparation"].get("reason_class"):
            prep_failures[value["preparation"]["reason_class"]] += 1
            prep_subtypes[value["preparation"]["reason_subtype"]] += 1
        for target in value["preparation"]["targets"]:
            prep_failures.update(reason["reason_class"] for reason in target["exclusion_reasons"])
            prep_subtypes.update(reason["reason_subtype"] for reason in target["exclusion_reasons"])
    def repo_success(kind, quantifier):
        return sum(bool(repo["entrypoints"]) and quantifier(
            entry["measurement"][kind]["status"] == "success" for entry in repo["entrypoints"])
                   for repo in included)
    attempt_accounting = {}
    for stage in ("compile", "discovery", "preparation", "plan"):
        attempts = [attempt for value in recorded for attempt in value["stage_attempts"][stage]]
        timing = numeric_summary([attempt.get("elapsed_seconds") for attempt in attempts], len(attempts))
        unidentified = sum(attempt["identity_status"] == "unknown" for attempt in attempts)
        attempt_accounting[stage] = {
            "recorded_attempts": len(attempts),
            "status_counts": dict(Counter(attempt.get("status", "unknown") for attempt in attempts)),
            "processes_started": sum(attempt.get("process_started") is True for attempt in attempts),
            "process_started_unknown": sum(attempt.get("process_started") is None for attempt in attempts),
            "identity_unknown": unidentified,
            "elapsed_seconds": timing,
            "total_elapsed_seconds": timing["sum"] if not timing["unknown"] and not unidentified else None,
            "total_unknown_reason": "unknown_elapsed_or_attempt_identity" if timing["unknown"] or unidentified else None}
    return {"repositories": len(repos), "inclusion_statuses": dict(Counter(
                repo["inclusion"]["status"] for repo in repos)),
            "entrypoint_files": len(entries),
            "main_declarations": sum(entry["main_declaration_count"] for entry in entries),
            "inventory_incomplete_repositories": sum(repo["entrypoint_inventory"].get("status") != "complete"
                                                      for repo in included),
            "compile_statuses": dict(compile_statuses), "preparation_statuses": dict(preparation_statuses),
            "discovery_statuses": dict(discovery_statuses), "plan_statuses": dict(plan_statuses),
            "compile_success_rate": fraction(compile_statuses["success"], len(entries)),
            "complete_preparation_rate": fraction(preparation_statuses["success"], len(entries)),
            "repository_compile_any": fraction(repo_success("compile", any), len(included)),
            "repository_compile_all_known_entrypoints": fraction(repo_success("compile", all), len(included)),
            "repository_preparation_any": fraction(repo_success("preparation", any), len(included)),
            "repository_preparation_all_known_entrypoints": fraction(repo_success("preparation", all), len(included)),
            "compile_failure_types": dict(failures), "compile_failure_types_original": dict(original_failures),
            "compiler_failure_refined_count": sum(value["compile"]["failure_refinement"]["status"] == "refined"
                                                 for value in recorded),
            "preparation_reason_occurrences": dict(prep_failures),
            "diagnostic_subtype_occurrences": {"discovery": dict(discovery_subtypes),
                                                "wrapper_callsites": dict(wrapper_subtypes),
                                                "preparation": dict(prep_subtypes)},
            "discovery_counts": {name: numeric_summary(
                [entry["measurement"].get("discovery", {}).get(name) for entry in entries], len(entries))
                for name in ("callsites", "unique_compile_units", "compiler_processes")},
            "wrapper_callsite_statuses": dict(Counter(status for value in recorded
                for status in (value["discovery"].get("callsite_wrapper_statuses") or []))),
            "constraint_counts": {**numeric_summary(counts, len(entries)),
                "bins": {"zero": sum(value == 0 for value in known_counts),
                         "1_to_999": sum(1 <= value < 1000 for value in known_counts),
                         "1000_to_99999": sum(1000 <= value < 100000 for value in known_counts),
                         "at_least_100000": sum(value >= 100000 for value in known_counts)},
                "at_least_100000_of_known": fraction(sum(value >= 100000 for value in known_counts), len(known_counts))},
            "timing_seconds": {stage: numeric_summary(
                [entry["measurement"].get(stage, {}).get("elapsed_seconds") for entry in entries], len(entries))
                for stage in ("compile", "discovery", "preparation", "plan")},
            "timing_seconds_scope": "selected_revision_only; superseded_nonreused_attempt_costs_are_in_all_recorded_stage_attempts",
            "all_recorded_stage_attempts": attempt_accounting,
            "manual_interventions": {
                "repository_recorded_count": sum(repo["manual_intervention_count"] or 0 for repo in repos),
                "repository_unknown_count": sum(repo["manual_intervention_count"] is None for repo in repos),
                "measurement_recorded_count": sum(value["manual_interventions"] or 0 for value in recorded),
                "measurement_unknown_count": len(entries) - sum(value["manual_interventions"] is not None for value in recorded)},
            "implementation_repaired_entrypoints": sum(value["implementation_repair"] for value in recorded),
            "discovery_rerun_entrypoints": sum(value["repair_reruns"]["discovery"] is True for value in recorded),
            "controller_interrupted_entrypoints": sum(any(attempt.get("status") == "interrupted"
                for attempt in value["stage_attempts"]["discovery"]) for value in recorded),
            "zkfuzz_recorded_executions": sum(value["zkfuzz_executions"] or 0 for value in recorded),
            "zkfuzz_unknown_measurements": len(entries) - sum(value["zkfuzz_executions"] is not None for value in recorded)}


def build_summary(run, census_path, root=ROOT):
    root, run = root.resolve(), run.resolve()
    census = load(census_path)
    seeds_path = run / "repository-census-inputs.json"
    seeds = load(seeds_path)
    expected = {row["full_name"].casefold() for row in seeds["repositories"]}
    seed_by_name = {row["full_name"].casefold(): row for row in seeds["repositories"]}
    if len(expected) != seeds["count"]:
        raise ValueError("duplicate census input identities")
    rows = census["repositories"]
    if {row["full_name"].casefold() for row in rows} != expected or len(rows) != len(expected):
        raise ValueError("final census does not preserve the complete input repository denominator")
    measured = measurements(run, root)
    used, repositories = set(), []
    for row in sorted(rows, key=lambda row: row["full_name"].casefold()):
        seed = seed_by_name[row["full_name"].casefold()]
        if set(row["source_memberships"]) != set(seed["source_memberships"]):
            raise ValueError("source memberships differ from frozen census input")
        metadata_path = (root / row["metadata_path"]).resolve()
        chain = version_chain(metadata_path, root, ("full_name", "commit_sha"))
        if chain[0][1] != row:
            raise ValueError("census row differs from selected metadata file")
        grouped = defaultdict(list)
        for entry in row.get("entrypoints", []):
            grouped[entry["path"]].append(entry)
        entries = []
        for path, declarations in sorted(grouped.items()):
            hashes = {item["sha256"] for item in declarations}
            if len(hashes) != 1:
                raise ValueError("one entrypoint path has conflicting source hashes")
            key = (row["full_name"].casefold(), path)
            if key in measured:
                chosen = measured[key][0][1]
                if chosen.get("commit_sha") != row["commit_sha"] or chosen.get("source_sha256") not in hashes:
                    raise ValueError("measurement revision/source differs from selected census")
                value = measurement_summary(measured[key], root)
                used.add(key)
            else:
                value = {"status": "not_started", "reason": "measurement_record_absent",
                         "compile": {"status": "not_started", "constraints": None},
                         "preparation": {"status": "not_started"}}
            entries.append({"path": path, "sha256": next(iter(hashes)),
                            "main_declaration_count": len(declarations),
                            "main_lines": [item["line"] for item in declarations],
                            "path_roles": sorted({role for item in declarations for role in item.get("path_roles", [])}),
                            "measurement": value})
        license_data = row.get("license", {})
        repository = {key: row.get(key) for key in (
            "full_name", "canonical_full_name", "canonical_redirect", "clone_path", "commit_sha",
            "commit_committer_date", "recent_commit", "source_memberships", "circom_source_memberships",
            "github_ranks", "exposure", "lineage", "inclusion", "manual_intervention_count")}
        repository.update(metadata=chain[0][0], metadata_history=[item[0] for item in chain[1:]],
                          entrypoints=entries, entrypoint_inventory=row.get("entrypoint_inventory", {}),
                          uninitialized_submodule_paths=row.get("uninitialized_submodule_paths", []),
                          license={"status": license_data.get("status", "unknown"),
                                   "reason": license_data.get("reason"),
                                   "evidence": [{key: item[key] for key in ("kind", "path", "sha256", "spdx_id", "nonempty")
                                                 if key in item} for item in license_data.get("evidence", [])]})
        repository["c02_source_preparation_exposure"] = {
            "status": "recorded" if row.get("source_preparation_exposure") else "not_recorded",
            "timestamp": row.get("source_preparation_exposure", {}).get("timestamp"),
            "preexisting_stratum_restored_after_c02": False}
        # Inventory errors are diagnostics, not source text. Preserve classifications
        # and paths without copying arbitrary parser messages into shared output.
        inventory = dict(repository["entrypoint_inventory"])
        inventory["errors"] = [{"path": error.get("path"), **reason_metadata(error.get("reason", "unknown"))}
                               for error in inventory.get("errors", [])]
        repository["entrypoint_inventory"] = inventory
        repositories.append(repository)
    extra = [{"repository": key[0], "entrypoint": key[1], "reference": measured[key][0][0],
              "reason": "measurement_not_in_selected_entrypoint_inventory"} for key in sorted(set(measured) - used)]
    overall = group_summary(repositories)
    missing = sum(entry["measurement"]["status"] == "not_started" for repo in repositories
                  if repo["inclusion"]["status"] == "included" for entry in repo["entrypoints"])
    provenance_paths = [Path(census_path), seeds_path, run / "catalog_sources.json",
                        run / "procedure-lock.json", run / "tool-lock.json",
                        root / "docs/c02_corpus_procedure_2026-10-02.md"]
    provenance_paths += [path for path in sorted(run.glob("github-search-*.json")) if path.is_file()]
    provenance_paths += [path for path in sorted(run.glob("measurement-driver*lock*.json")) if path.is_file()]
    if (run / "controller-interruption.json").is_file():
        provenance_paths.append(run / "controller-interruption.json")
    tool_lock = load(run / "tool-lock.json")
    strata = sorted({repo["exposure"]["stratum"] for repo in repositories})
    return {"schema_version": 1, "task": "C-02", "owner": "miiz", "deadline": "2026-10-10",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "complete_known_inventory" if not missing and not extra else "incomplete",
            "missing_measurement_count": missing, "unexpected_measurements": extra,
            "provenance": [reference(path, root) for path in provenance_paths],
            "source_queries": source_summary(run, root), "checks": check_summary(run, root),
            "inventory_composition": inventory_composition(repositories),
            "tools": {key: tool_lock.get(key) for key in ("circom_version", "strategy", "optimization", "prime", "tools")},
            "summary_implementation": reference(Path(__file__), root),
            "overall": overall,
            "by_source": {source: group_summary([repo for repo in repositories if source in repo["source_memberships"]])
                          for source in SOURCES},
            "by_exposure": {stratum: group_summary([repo for repo in repositories if repo["exposure"]["stratum"] == stratum])
                            for stratum in strata},
            "by_source_and_exposure": {source: {stratum: group_summary([
                repo for repo in repositories if source in repo["source_memberships"]
                and repo["exposure"]["stratum"] == stratum]) for stratum in strata} for source in SOURCES},
            "canonical_repository_count": len({repo["canonical_full_name"].casefold() for repo in repositories}),
            "repositories": repositories,
            "limitations": [
                "Source layers overlap; their repository or entrypoint counts must not be summed as independent units.",
                "Unexposed_by_lists is absence from checked exposure lists, not a verified absence of every prior exposure; C-02 source/preparation exposure is new exposure.",
                "Entrypoint denominators count distinct files; repeated main declarations in one file remain recorded and are compiled once.",
                "Incomplete inventories and uninitialized submodules leave additional entrypoints unknown; all-known-entrypoint rates do not certify full repository coverage.",
                "Only compiler/discovery/prepare/plan metadata is summarized; no witness, candidate, R1CS relation, defect verdict or fuzz search is read or executed.",
                "Preparation includes wrapper validation and repeated R1CS compilation; measured stage times are not independent or performance comparisons.",
                "Selected-revision stage times omit superseded nonreused attempts; all_recorded_stage_attempts retains them and deduplicates only identical immutable log references. Unknown interruption wall time leaves the total unknown.",
                "Repairs select the unique hash-linked revision chain, preserve older failures and reuse original compilation/discovery; no result-quality selection.",
                "Failure distributions count preparation reason occurrences and can contain multiple reasons per entrypoint; unknown counts are never zero-imputed."]}


def rate_text(value):
    rate = value["rate"]
    return f'{value["numerator"]}/{value["denominator"]}' + (f' ({rate:.1%})' if rate is not None else ' (unknown)')


def markdown(summary):
    def link(reference_value, label="기록"):
        path = reference_value["path"]
        target = path if Path(path).is_absolute() else "../" + path
        return f"[{label}](<{target}>)"

    def number(value):
        return "unknown" if value is None else f"{value:,.3f}" if isinstance(value, float) else f"{value:,}"

    overall = summary["overall"]
    lines = ["# C-02 평가 후보 자동 준비 조사", "", "담당: miiz · 기한: 2026-10-10 · 준비 적용성 조사, zkFuzz 미실행.", "",
             "[선정 절차](c02_corpus_procedure_2026-10-02.md) · [기계 판독 결과](c02_corpus_results_2026-10-02.json)", "",
             "| 출처 | 고정 쿼리·목록 범위 | 검색·조회 시각 UTC | revision / 근거 |", "|---|---|---|---|"]
    for page in summary["source_queries"]["github_search_pages"]:
        query = f'{page["query"]}; sort={page["sort"]}; order={page["order"]}; per_page={page["per_page"]}; page={page["page"]}'
        lines.append(f'| GitHub top200 | `{query}` | {page["queried_at"]} | {link(page["metadata"], "검색 메타데이터")} |')
    for source in summary["source_queries"]["datasets"]:
        dates = ", ".join(retrieval["started_at"] for retrieval in source["retrievals"] if retrieval.get("started_at"))
        lines.append(f'| {source["source"]} | 전체 DSL 프로젝트 목록 ({source["project_count"]} repo; Circom {source["circom_project_count"]}) | {dates or "unknown"} | `{source["dataset_revision"]}`; {link(summary["source_queries"]["catalog_reference"], "목록 근거")} |')
    lines += ["", "출처층은 중복된다. 비율의 분모는 포함 저장소에서 확인한 고유 entrypoint 파일 전부이며, 미시작·실패도 남긴다.", "",
              "| 층 | 저장소 | 포함/제외/불명 | entrypoint 파일 | 컴파일 성공 | 완전 자동 준비 |", "|---|---:|---|---:|---|---|"]
    groups = [("전체", summary["overall"]), *summary["by_source"].items(), *summary["by_exposure"].items()]
    for label, group in groups:
        counts = group["inclusion_statuses"]
        lines.append(f'| {label} | {group["repositories"]} | {counts.get("included", 0)}/{counts.get("excluded", 0)}/{counts.get("unknown", 0)} | {group["entrypoint_files"]} | {rate_text(group["compile_success_rate"])} | {rate_text(group["complete_preparation_rate"])} |')
    lines += ["", f'상태: `{summary["status"]}`. 미기록 entrypoint {summary["missing_measurement_count"]}개. '
              f'구현 오류 후 hash 연결 수정 {overall["implementation_repaired_entrypoints"]}개; 원본 컴파일을 재사용하고 탐색 재실행 여부와 v1 기록을 보존한다.', "",
              f'Controller 중단 이력 {overall["controller_interrupted_entrypoints"]}개; discovery 재실행 {overall["discovery_rerun_entrypoints"]}개. '
              '중단·실패 시도도 all_recorded_stage_attempts에 포함하며, 미측정 중단 wall을 0으로 대체하거나 재실행 이전 비용을 삭제하지 않는다.', "",
              f'저장소별 컴파일 하나 이상: {rate_text(overall["repository_compile_any"])}; 알려진 파일 모두: {rate_text(overall["repository_compile_all_known_entrypoints"])}. '
              f'자동 준비 하나 이상: {rate_text(overall["repository_preparation_any"])}; 알려진 파일 모두: {rate_text(overall["repository_preparation_all_known_entrypoints"])}.', "",
              "| 단계 | 성공 | 부분 | 실패 | timeout | 중단 | 미시작 | 미지원 | 기타·불완전 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for label, key in (("원본 컴파일", "compile_statuses"), ("자동 탐색", "discovery_statuses"),
                       ("자동 준비", "preparation_statuses"), ("계획 생성", "plan_statuses")):
        counts = overall[key]
        known = {"success", "partial", "failure", "failed", "timeout", "interrupted", "not_started", "unsupported"}
        lines.append(f'| {label} | {counts.get("success", 0)} | {counts.get("partial", 0)} | '
                     f'{counts.get("failure", 0) + counts.get("failed", 0)} | {counts.get("timeout", 0)} | '
                     f'{counts.get("interrupted", 0)} | {counts.get("not_started", 0)} | {counts.get("unsupported", 0)} | '
                     f'{sum(count for status, count in counts.items() if status not in known)} |')
    constraints = overall["constraint_counts"]
    lines += ["", "| 원본 제약 수 | entrypoint 파일 수 |", "|---|---:|"]
    for label, key in (("0", "zero"), ("1–999", "1_to_999"), ("1,000–99,999", "1000_to_99999"), ("≥100,000", "at_least_100000")):
        lines.append(f'| {label} | {constraints["bins"][key]} |')
    lines += [f'| unknown | {constraints["unknown"]} |', "",
              f'관측 {constraints["known"]}개에서 최소/중앙/최대: {number(constraints["minimum"])}/{number(constraints["median"])}/{number(constraints["maximum"])}. '
              '컴파일 실패·미시작·수치 결측은 0 제약으로 바꾸지 않는다.', "",
              "| 단계의 기록된 시도 | 시도 수 | wall 알려짐/불명 | 알려진 wall 합(초) | 전체 시도 wall 합(초) |", "|---|---:|---|---:|---:|"]
    for stage, value in overall["all_recorded_stage_attempts"].items():
        timing = value["elapsed_seconds"]
        lines.append(f'| {stage} | {value["recorded_attempts"]} | {timing["known"]}/{timing["unknown"]} | {number(timing["sum"])} | {number(value["total_elapsed_seconds"])} |')
    lines += ["", "시도 wall의 합은 병렬·중첩 실행이 있는 조사 전체 wall이 아니다. 동일 원본 로그를 재사용한 항목은 한 번만 세고, 재실행과 과거 중단 비용은 보존한다. 미측정 비용이 있으면 전체 시도 합은 unknown이다.", "",
              "| 원본 컴파일 실패 유형 | 보정 후 건수 | 원래 분류 건수 |", "|---|---:|---:|"]
    for failure in sorted(set(overall["compile_failure_types"]) | set(overall["compile_failure_types_original"])):
        lines.append(f'| {failure} | {overall["compile_failure_types"].get(failure, 0)} | {overall["compile_failure_types_original"].get(failure, 0)} |')
    lines += ["", f'오류 코드 P1014의 missing_include 보정 {overall["compiler_failure_refined_count"]}건. 원래 분류와 해시 검증된 compiler 로그 참조를 함께 보존한다. 로그·소스 문구는 공유 결과에 복사하지 않는다.', "",
              "| 미지원·준비 진단 세부 유형 | 탐색 진단 발생 | wrapper 호출 위치 진단 발생 | 준비 진단 발생 |", "|---|---:|---:|---:|"]
    subtypes = overall["diagnostic_subtype_occurrences"]
    for subtype in sorted(set().union(*(set(counts) for counts in subtypes.values()))):
        lines.append(f'| {subtype} | {subtypes["discovery"].get(subtype, 0)} | {subtypes["wrapper_callsites"].get(subtype, 0)} | {subtypes["preparation"].get(subtype, 0)} |')
    lines += ["", "세부 유형은 저장된 진단 발생 횟수다. 한 entrypoint에 여러 진단이 있거나 탐색·준비 층에 같은 사유가 반복될 수 있으므로 독립 실패 수로 합산하지 않는다. 사유 결측은 unknown으로 보존하며 소스 식·식별자·값을 공유하지 않는다.", "",
              "| 수동 개입 집계 | 기록된 건수 | 개입 수 미확인 기록 |", "|---|---:|---:|"]
    interventions = overall["manual_interventions"]
    for label, prefix in (("저장소 준비", "repository"), ("entrypoint 측정", "measurement")):
        lines.append(f'| {label} | {interventions[prefix + "_recorded_count"]} | {interventions[prefix + "_unknown_count"]} |')
    composition = summary["inventory_composition"]
    collections = ", ".join(f'{item["repository"]} {item["entrypoint_files"]}' for item in composition["identified_collection_repositories"])
    roles = ", ".join(f'{role} {count}' for role, count in sorted(composition["path_role_counts_overlapping"].items()))
    lines += ["", f'분모 {composition["known_entrypoint_files"]}개는 알려진 main 파일 경로이며 독립 production 회로 수가 아니다. '
              f'확인한 benchmark/dataset 저장소 묶음({collections or "없음"})의 파일 비중은 {rate_text(composition["identified_collection_file_fraction"])}다. '
              '이 묶음은 저장소 기준으로, 모든 경로의 용도를 개별 확정한 것은 아니다.', "",
              f'경로 역할: {roles or "unknown"}. 역할 표시는 서로 중복되며 unclassified를 production으로 해석하지 않는다. '
              f'포함 저장소 중 inventory 불완전 {overall["inventory_incomplete_repositories"]}개는 추가 main의 수가 unknown이다. '
              '목록상 미노출은 모든 과거 노출 부재의 인증이 아니며, 이번 소스·준비 노출을 되돌리지 않는다.', "",
              "| 검사 | 기록 상태 | 확인된 결과 | 근거 |", "|---|---|---|---|"]
    if not summary["checks"]["checks"]:
        lines.append("| 필수 검사 | unverified | 해시·종료 상태가 연결된 검사 기록 없음 | — |")
    for check in summary["checks"]["checks"]:
        counts = check.get("counts", {})
        detail = (f'{counts["passed"]} passed / {counts["failed"]} failed / {counts["ignored"]} ignored'
                  if "passed" in counts else f'{counts["ran"]} tests / {counts["suites"]} suites'
                  if "ran" in counts else check.get("reason", f'exit {check.get("exit_code", "unknown")}'))
        lines.append(f'| {check["name"]} | {check["status"]} | {detail} | {link(check["log"], "로그") if check.get("log") else "—"} |')
    lines += ["", '| 저장소 | 출처 | 노출층 | 포함 상태/사유 | entrypoint 파일 | compile | prepare | SHA |',
              '|---|---|---|---|---:|---|---|---|']
    for repo in summary["repositories"]:
        stats = group_summary([repo])
        reasons = ", ".join(repo["inclusion"].get("reasons", []))
        row = (f'| {repo["full_name"]} | {", ".join(repo["source_memberships"])} | {repo["exposure"]["stratum"]} | '
               f'{repo["inclusion"]["status"]}{": " + reasons if reasons else ""} | {len(repo["entrypoints"])} | '
               f'{rate_text(stats["compile_success_rate"])} | {rate_text(stats["complete_preparation_rate"])} | '
               f'{repo["commit_sha"] or "unknown"} |')
        lines.append(row.replace("\n", " "))
    lines += ["", "미지원·불명은 결함 음성이나 일반적인 의미 동등성 근거가 아니다. N4-1 전체와 N5는 이 조사로 완료되지 않는다.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=ROOT / "runs/c02-corpus-2026-10-02")
    parser.add_argument("--census", type=Path, required=True, help="explicit final repositories[-vN].json")
    parser.add_argument("--output-prefix", type=Path, help="explicit new output stem; existing files are refused")
    args = parser.parse_args()
    summary = build_summary(args.run_root, args.census)
    if args.output_prefix:
        if summary["status"] != "complete_known_inventory":
            raise SystemExit("shared output refused: census measurements are incomplete")
        paths = [args.output_prefix.with_suffix(suffix) for suffix in (".json", ".md")]
        if any(path.exists() for path in paths):
            raise SystemExit("shared output already exists; use a new versioned output prefix")
        for path, text in zip(paths, (json.dumps(summary, ensure_ascii=False, indent=2) + "\n", markdown(summary))):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x") as handle:
                handle.write(text)
    print(json.dumps({key: summary[key] for key in ("status", "missing_measurement_count", "overall")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
