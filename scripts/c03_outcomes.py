"""Conservative C-03 preparation outcomes from already-read tool metadata.

No source, compiler artifact, witness, log or candidate is opened. Callers must
verify the report references before passing decoded JSON. Process exit success
and preparation success remain separate; this is not a semantic certification.
"""

from copy import deepcopy
import hashlib


def _integer(value):
    return type(value) is int and value >= 0


def _code(value, fallback):
    return value if isinstance(value, str) and value.strip() else fallback


def exclusion_code(reason):
    """Return stable categories without retaining raw source-bearing diagnostics."""
    if not isinstance(reason, str):
        return "invalid_exclusion_reason"
    if reason.startswith("unsupported inspection:"):
        return "inspection_unsupported"
    if reason == "entrypoint inspection is incomplete":
        return "inspection_incomplete"
    if "compile-r1cs failed" in reason:
        return "unit_compile_timeout" if "timed_out true" in reason else "unit_compile_failed"
    if reason == "compilation or compiled size is unavailable":
        return "compiled_size_or_compile_unavailable"
    if reason.startswith("duplicate executable target identity"):
        return "duplicate_target_identity"
    if reason == "parsed root template is unavailable":
        return "root_template_unavailable"
    if reason.startswith("manifest "):
        return "manifest_target_mismatch"
    if reason.startswith("structure preparation failed:"):
        return "target_structure_failed"
    if reason.startswith("preparation failed:"):
        return "target_preparation_failed"
    return "target_excluded_other"


def classify_preparation(result, *, prepared_report=None, discovery_report=None):
    """Classify compact measurement plus optional, hash-verified raw reports.

    A raw prepared report is required to verify successful units. A compact
    report's ``eligible`` count alone never proves compilation or inspection.
    ``unknown`` can coexist with known valid units; ``partial`` requires a
    known failed whole-preparation requirement, rather than missing evidence.
    """
    preparation = result.get("preparation")
    discovery = result.get("discovery")
    plan = result.get("plan")
    preparation = preparation if isinstance(preparation, dict) else {}
    discovery = discovery if isinstance(discovery, dict) else {}
    plan = plan if isinstance(plan, dict) else {}
    reported = preparation.get("status")
    if not isinstance(reported, str):
        reported = None
    issues = []
    unknown = []
    evidence = []
    declared = None
    valid = 0
    expected = preparation.get("expected_targets")
    unit_outcomes = []

    def add(code, field, *, uncertain=False, label=None, raw_reason=None):
        destination = unknown if uncertain else issues
        if code not in destination:
            destination.append(code)
        row = {"code": code, "field": field}
        if label is not None:
            row["label"] = label
        if isinstance(raw_reason, str):
            row["reason_sha256"] = hashlib.sha256(raw_reason.encode()).hexdigest()
        if row not in evidence:
            evidence.append(row)

    def finish(status, primary=None):
        codes = sorted(set(issues + unknown))
        if status != "success" and not codes:
            codes = ["preparation_evidence_unavailable"]
        return {"schema_version": 1, "status": status,
                "failure_type": None if status == "success" else primary or codes[0],
                "failure_types": codes, "reason_codes": codes,
                "reported_status": reported, "reported_failure_type": preparation.get("failure_type"),
                "prepare_process_exit_code": preparation.get("exit_code"),
                "declared_eligible_units": declared, "known_valid_units": valid,
                "expected_units": expected if _integer(expected) else None,
                "incomplete_evidence": bool(unknown), "unknown_reason_codes": sorted(set(unknown)),
                "unit_outcomes": unit_outcomes, "reason_evidence": evidence,
                "meaning": "reported preparation metadata only; no semantic certification"}

    if reported == "not_started":
        dependency = _code(discovery.get("failure_type"), _code(discovery.get("status"), "unknown"))
        add("blocked_by_discovery_" + dependency, "discovery.status")
        if not preparation.get("reason"):
            add("preparation_not_started_reason_missing", "preparation.reason", uncertain=True)
        return finish("not_started", "blocked_by_discovery_" + dependency)
    if reported == "unsupported" and prepared_report is None:
        add("manifest_generation_unsupported", "preparation.reason", raw_reason=preparation.get("reason"))
        if not preparation.get("reason"):
            add("unsupported_reason_missing", "preparation.reason", uncertain=True)
            return finish("unknown", "unsupported_reason_missing")
        return finish("unsupported", "manifest_generation_unsupported")
    if reported in {"failure", "timeout", "interrupted", "start_failure"} and prepared_report is None:
        code = "prepare_process_" + _code(preparation.get("failure_type"), reported)
        add(code, "preparation.status")
        return finish("failed", code)
    if reported not in {"success", "partial", "failed", "unknown", "failure", "timeout", "interrupted", "start_failure"}:
        add("preparation_status_missing_or_invalid", "preparation.status", uncertain=True)
    if preparation.get("exit_code") != 0:
        if preparation.get("exit_code") is None and reported not in {"failure", "timeout", "interrupted", "start_failure"}:
            add("prepare_process_exit_unknown", "preparation.exit_code", uncertain=True)
        else:
            add("prepare_process_not_successful", "preparation.exit_code")
    if not _integer(expected) or expected == 0:
        add("expected_target_count_missing_or_invalid", "preparation.expected_targets", uncertain=True)

    compact_targets = preparation.get("targets")
    compact_labels = None
    if isinstance(compact_targets, list) and all(isinstance(row, dict) for row in compact_targets):
        if all(type(row.get("eligible")) is bool for row in compact_targets):
            declared = sum(row["eligible"] for row in compact_targets)
        compact_labels = [row.get("label") for row in compact_targets]
        if any(not isinstance(label, str) for label in compact_labels) or len(set(compact_labels)) != len(compact_labels):
            compact_labels = None
            add("compact_target_identity_invalid", "preparation.targets", uncertain=True)
        if declared is not None and preparation.get("eligible") != declared:
            add("eligible_count_mismatch", "preparation.eligible", uncertain=True)
    else:
        add("compact_targets_missing_or_invalid", "preparation.targets", uncertain=True)

    if not isinstance(prepared_report, dict):
        add("prepared_report_not_available", "preparation.report", uncertain=True)
        return finish("unknown", "prepared_report_not_available")
    targets = prepared_report.get("targets")
    if not isinstance(targets, list) or not all(isinstance(target, dict) for target in targets):
        add("prepared_targets_missing_or_invalid", "prepared.targets", uncertain=True)
        return finish("unknown", "prepared_targets_missing_or_invalid")
    labels = [(row.get("definition") or {}).get("label") if isinstance(row.get("definition"), dict) else None for row in targets]
    identities_good = all(isinstance(label, str) for label in labels) and len(set(labels)) == len(labels)
    if not identities_good:
        add("prepared_target_identity_invalid", "prepared.targets", uncertain=True)
    if compact_labels is None or sorted(labels, key=str) != sorted(compact_labels):
        identities_good = False
        add("prepared_compact_target_identity_mismatch", "prepared.targets", uncertain=True)
    if _integer(expected) and len(targets) != expected:
        add("prepared_target_count_mismatch", "prepared.targets", uncertain=True)
    if "root" not in labels:
        add("root_target_missing", "prepared.targets", uncertain=True)
    if any(type(row.get("eligible")) is not bool for row in targets):
        add("prepared_eligibility_missing", "prepared.targets", uncertain=True)
    else:
        actual_declared = sum(row["eligible"] for row in targets)
        if declared is not None and actual_declared != declared:
            add("prepared_compact_eligibility_mismatch", "prepared.targets", uncertain=True)
        declared = actual_declared
    compact_by_label = {row.get("label"): row for row in compact_targets} if compact_labels else {}
    for index, target in enumerate(targets):
        label = labels[index]
        local_codes = []
        local_unknown = []

        def unit_issue(code, field, *, uncertain=False, raw_reason=None):
            (local_unknown if uncertain else local_codes).append(code)
            add(code, field, uncertain=uncertain, label=label, raw_reason=raw_reason)

        eligible = target.get("eligible")
        compact = compact_by_label.get(label) if isinstance(label, str) else None
        if compact is not None and compact.get("eligible") != eligible:
            unit_issue("prepared_compact_eligibility_mismatch", "prepared.targets.eligible", uncertain=True)
        exclusions = target.get("exclusion_reasons")
        if not isinstance(exclusions, list):
            unit_issue("target_exclusions_missing", "prepared.targets.exclusion_reasons", uncertain=True)
            exclusions = []
        for reason in exclusions:
            unit_issue(exclusion_code(reason), "prepared.targets.exclusion_reasons", raw_reason=reason)
        if eligible is True and exclusions:
            unit_issue("eligible_target_has_exclusions", "prepared.targets.eligible", uncertain=True)
        if eligible is False and not exclusions:
            unit_issue("ineligible_target_reason_missing", "prepared.targets.exclusion_reasons", uncertain=True)
        inspection = target.get("inspection")
        if not isinstance(inspection, dict) or type(inspection.get("complete")) is not bool:
            unit_issue("inspection_completion_unknown", "prepared.targets.inspection", uncertain=True)
        elif inspection["complete"] is False:
            unit_issue("inspection_unsupported" if inspection.get("unsupported") else "inspection_incomplete", "prepared.targets.inspection.complete")
        elif not isinstance(inspection.get("unsupported"), list):
            unit_issue("inspection_unsupported_inventory_missing", "prepared.targets.inspection.unsupported", uncertain=True)
        elif inspection["unsupported"]:
            unit_issue("inspection_completion_conflict", "prepared.targets.inspection.unsupported", uncertain=True)
        structure = target.get("structure")
        if not isinstance(structure, dict):
            if eligible is True:
                unit_issue("unit_structure_missing", "prepared.targets.structure", uncertain=True)
            elif not exclusions:
                unit_issue("unit_structure_missing", "prepared.targets.structure", uncertain=True)
            structure = {}
        if eligible is True or structure:
            version = structure.get("zkfuzz_version")
            version = version if isinstance(version, dict) else {}
            if structure.get("ast_requested") is True or version.get("requested") is True:
                unit_issue("forbidden_frontend_request", "prepared.targets.structure", uncertain=True)
            elif eligible is True and (structure.get("ast_requested") is not False or version.get("requested") is not False):
                unit_issue("frontend_request_metadata_missing", "prepared.targets.structure", uncertain=True)
            if eligible is True and structure.get("complete") is not True:
                unit_issue("eligible_structure_completion_unknown", "prepared.targets.structure.complete", uncertain=True)
            if eligible is True and (not isinstance(structure.get("errors"), list) or structure["errors"]):
                unit_issue("eligible_structure_errors_unknown_or_present", "prepared.targets.structure.errors", uncertain=True)
            if not _integer(structure.get("size")):
                unit_issue("compiled_size_unavailable", "prepared.targets.structure.size", uncertain=eligible is True)
            if type(structure.get("compile_success")) is not bool:
                unit_issue("unit_compile_success_unknown", "prepared.targets.structure.compile_success", uncertain=True)
            elif not structure["compile_success"]:
                unit_issue("unit_compile_failed", "prepared.targets.structure.compile_success")
            capture = structure.get("compile")
            if not isinstance(capture, dict):
                unit_issue("unit_compile_capture_missing", "prepared.targets.structure.compile", uncertain=eligible is True)
            else:
                if capture.get("timed_out") is True:
                    unit_issue("unit_compile_timeout", "prepared.targets.structure.compile.timed_out")
                if capture.get("process_started") is False:
                    unit_issue("unit_compiler_not_started", "prepared.targets.structure.compile.process_started")
                if eligible is True and (capture.get("success") is not True or capture.get("exit_code") != 0 or capture.get("timed_out") is not False or capture.get("process_started") is not True):
                    unit_issue("eligible_unit_compile_not_verified", "prepared.targets.structure.compile", uncertain=True)
        if eligible is True and (not isinstance(target.get("run_entrypoint"), str) or not target["run_entrypoint"]):
            unit_issue("executable_snapshot_missing", "prepared.targets.run_entrypoint", uncertain=True)
        verified = eligible is True and not local_codes and not local_unknown and identities_good
        valid += int(verified)
        unit_outcomes.append({"label": label, "reported_eligible": eligible, "verified_prepared": verified,
                              "reason_codes": sorted(set(local_codes + local_unknown)), "incomplete_evidence": bool(local_unknown)})

    for key in ("global_diagnostics", "diagnostics", "errors"):
        diagnostics = prepared_report.get(key, [])
        if not isinstance(diagnostics, list):
            add("prepare_global_diagnostics_invalid", "prepared." + key, uncertain=True)
        else:
            for diagnostic in diagnostics:
                if isinstance(diagnostic, dict) and diagnostic.get("severity") in ("info", "warning", "note"):
                    continue
                add("prepare_global_diagnostic", "prepared." + key)

    if discovery.get("status") != "success" or discovery.get("exit_code") != 0:
        add("discovery_process_not_successful", "discovery.status", uncertain=discovery.get("status") is None)
    discovered = discovery_report if isinstance(discovery_report, dict) else discovery
    entrypoint_status = discovered.get("entrypoint_status")
    if entrypoint_status != "found":
        add("entrypoint_" + _code(entrypoint_status, "status_unknown"), "discovery.entrypoint_status", uncertain=entrypoint_status is None)
    unsupported = discovered.get("unsupported")
    if not isinstance(unsupported, list):
        add("discovery_unsupported_inventory_missing", "discovery.unsupported", uncertain=True)
    elif unsupported:
        add("discovery_unsupported", "discovery.unsupported")
    if isinstance(discovery_report, dict):
        found_targets = discovery_report.get("targets")
        units = discovery_report.get("compile_units")
        wrappers = [row.get("wrapper_status") for row in found_targets] if isinstance(found_targets, list) and all(isinstance(row, dict) for row in found_targets) else None
        unit_count = len(units) if isinstance(units, list) else None
    else:
        wrappers = discovery.get("callsite_wrapper_statuses")
        unit_count = discovery.get("unique_compile_units")
        if isinstance(wrappers, list) and discovery.get("callsites") != len(wrappers):
            add("callsite_inventory_count_mismatch", "discovery.callsites", uncertain=True)
    if not _integer(unit_count) or (_integer(expected) and expected != unit_count + 1):
        add("compile_unit_count_mismatch_or_missing", "discovery.compile_units", uncertain=True)
    if not isinstance(wrappers, list):
        add("wrapper_status_inventory_missing", "discovery.targets", uncertain=True)
    else:
        for status in wrappers:
            if status != "compile_succeeded":
                known = isinstance(status, str) and status in {"not_generated", "generated", "compile_failed", "compile_timed_out", "compiler_unavailable", "unsupported"}
                add("wrapper_" + _code(status, "status_unknown"), "discovery.targets.wrapper_status", uncertain=not known)
    if plan.get("status") != "success":
        add("plan_" + _code(plan.get("status"), "missing"), "plan.status", uncertain=not plan)
    elif plan.get("exit_code") != 0 or not isinstance(plan.get("report"), dict):
        add("successful_plan_evidence_missing", "plan.report", uncertain=True)
    if reported == "unknown":
        add("reported_preparation_unknown", "preparation.reason", uncertain=True, raw_reason=preparation.get("reason"))
    if unknown:
        return finish("unknown", "incomplete_preparation_evidence")
    if valid > 0:
        if not issues and valid == expected:
            if reported != "success":
                add("reported_preparation_status_conflict", "preparation.status", uncertain=True)
                return finish("unknown", "reported_preparation_status_conflict")
            return finish("success")
        return finish("partial", "partial_preparation")
    unsupported_only = {"inspection_unsupported", "inspection_incomplete", "root_template_unavailable", "discovery_unsupported",
                        "wrapper_unsupported", "wrapper_not_generated", "plan_failure", "plan_not_started", "entrypoint_missing", "entrypoint_multiple"}
    if issues and set(issues) <= unsupported_only:
        return finish("unsupported", "no_eligible_units_due_to_unsupported_inspection")
    return finish("failed", "no_eligible_prepared_units")


def normalize_result(result, *, prepared_report=None, discovery_report=None):
    """Return a new record; never mutate the original measurement or reports."""
    normalized = deepcopy(result)
    normalized["preparation_outcome"] = classify_preparation(result, prepared_report=prepared_report, discovery_report=discovery_report)
    for stage in ("compile", "compile_before", "compile_after", "discovery", "plan"):
        capture = normalized.get(stage)
        if not isinstance(capture, dict):
            continue
        status = capture.get("status")
        if status == "success":
            capture["failure_type"] = None
        else:
            capture["failure_type"] = _code(capture.get("failure_type"), stage + "_" + _code(status, "status_unknown"))
    preparation = normalized.setdefault("preparation", {})
    if not isinstance(preparation, dict):
        preparation = {}
        normalized["preparation"] = preparation
    preparation["reported_status"] = preparation.get("status")
    preparation["reported_failure_type"] = preparation.get("failure_type")
    preparation.update({key: normalized["preparation_outcome"][key] for key in ("status", "failure_type", "failure_types")})
    return normalized
