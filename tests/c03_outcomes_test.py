"""Counterexamples to treating successful tool exit or eligibility as readiness."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("c03_outcomes", Path(__file__).resolve().parents[1] / "scripts/c03_outcomes.py")
outcomes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(outcomes)


def sample():
    compact = {"label": "root", "eligible": True, "exclusion_reasons": [], "constraints": 0, "compiler_started": True}
    result = {"compile": {"status": "success", "exit_code": 0},
              "preparation": {"status": "success", "exit_code": 0, "expected_targets": 1,
                              "eligible": 1, "targets": [compact], "failure_type": None},
              "discovery": {"status": "success", "exit_code": 0, "entrypoint_status": "found", "unsupported": [],
                            "unique_compile_units": 0, "callsites": 0, "callsite_wrapper_statuses": []},
              "plan": {"status": "success", "exit_code": 0, "report": {"path": "plan.json", "sha256": "0" * 64}}}
    target = {"definition": {"label": "root"}, "eligible": True, "exclusion_reasons": [],
              "inspection": {"complete": True, "unsupported": []}, "run_entrypoint": "snapshot/main.circom",
              "structure": {"complete": True, "compile_success": True, "size": 0, "errors": [],
                            "ast_requested": False, "zkfuzz_version": {"requested": False},
                            "compile": {"exit_code": 0, "success": True, "timed_out": False, "process_started": True}}}
    return result, {"targets": [target]}


class OutcomeTests(unittest.TestCase):
    def classify(self, result, report):
        return outcomes.classify_preparation(result, prepared_report=report)

    def test_zero_constraint_root_only_can_be_success_with_complete_evidence(self):
        result, report = sample()
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "success")
        self.assertEqual(answer["known_valid_units"], 1)
        self.assertIsNone(answer["failure_type"])

    def test_compact_eligible_and_exit_zero_do_not_certify_units(self):
        result, _ = sample()
        answer = outcomes.classify_preparation(result)
        self.assertEqual(answer["status"], "unknown")
        self.assertEqual(answer["declared_eligible_units"], 1)
        self.assertEqual(answer["known_valid_units"], 0)

    def test_successful_exit_with_zero_eligible_unsupported_inspection_is_not_compile_failure(self):
        result, report = sample()
        result["preparation"].update(status="failed", eligible=0)
        result["preparation"]["targets"][0]["eligible"] = False
        target = report["targets"][0]
        target.update(eligible=False, exclusion_reasons=["unsupported inspection: unsupported synthetic syntax"])
        target["inspection"].update(complete=False, unsupported=[{"reason": "synthetic syntax"}])
        result["plan"] = {"status": "failure", "exit_code": 1}
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "unsupported")
        self.assertEqual(answer["prepare_process_exit_code"], 0)
        self.assertIn("inspection_unsupported", answer["failure_types"])
        self.assertNotIn("unit_compile_failed", answer["failure_types"])

    def test_internal_compile_timeout_is_preserved_even_when_prepare_exit_zero(self):
        result, report = sample()
        result["preparation"].update(status="failed", eligible=0)
        result["preparation"]["targets"][0]["eligible"] = False
        target = report["targets"][0]
        target.update(eligible=False, exclusion_reasons=["structure: compile-r1cs failed (exit None, timed_out true): see captured output"])
        target["structure"].update(complete=False, compile_success=False, size=None)
        target["structure"]["compile"].update(success=False, timed_out=True, exit_code=None)
        result["plan"] = {"status": "failure", "exit_code": 1}
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "failed")
        self.assertIn("unit_compile_timeout", answer["failure_types"])

    def test_partial_requires_known_valid_unit_and_names_unmet_discovery_requirement(self):
        result, report = sample()
        result["preparation"]["status"] = "partial"
        result["discovery"]["unsupported"] = [{"reason": "synthetic unsupported branch"}]
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "partial")
        self.assertEqual(answer["known_valid_units"], 1)
        self.assertEqual(answer["failure_type"], "partial_preparation")
        self.assertIn("discovery_unsupported", answer["failure_types"])

    def test_missing_information_with_valid_unit_remains_unknown(self):
        result, report = sample()
        del result["discovery"]["callsite_wrapper_statuses"]
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "unknown")
        self.assertEqual(answer["known_valid_units"], 1)
        self.assertTrue(answer["incomplete_evidence"])

    def test_wrapper_failure_does_not_disappear_behind_plan_success(self):
        result, report = sample()
        result["preparation"]["status"] = "partial"
        result["discovery"].update(callsites=1, callsite_wrapper_statuses=["compile_failed"])
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "partial")
        self.assertIn("wrapper_compile_failed", answer["failure_types"])

    def test_plan_failure_and_global_error_make_ready_units_partial(self):
        result, report = sample()
        result["preparation"]["status"] = "partial"
        result["plan"] = {"status": "timeout", "exit_code": None}
        report["global_diagnostics"] = [{"severity": "error", "message": "synthetic"}]
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "partial")
        self.assertIn("plan_timeout", answer["failure_types"])
        self.assertIn("prepare_global_diagnostic", answer["failure_types"])

    def test_warning_only_diagnostic_is_not_an_error(self):
        result, report = sample()
        report["diagnostics"] = [{"severity": "warning", "message": "synthetic informational warning"}]
        self.assertEqual(self.classify(result, report)["status"], "success")

    def test_missing_plan_artifact_prevents_success(self):
        result, report = sample()
        del result["plan"]["report"]
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "unknown")
        self.assertIn("successful_plan_evidence_missing", answer["failure_types"])

    def test_report_target_count_and_duplicate_identity_fail_closed(self):
        result, report = sample()
        report["targets"].append(deepcopy(report["targets"][0]))
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "unknown")
        self.assertEqual(answer["known_valid_units"], 0)
        self.assertIn("prepared_target_identity_invalid", answer["failure_types"])

    def test_claimed_eligible_but_compile_failure_or_exclusions_is_unknown(self):
        result, report = sample()
        target = report["targets"][0]
        target["structure"]["compile"]["exit_code"] = 1
        target["exclusion_reasons"] = ["preparation failed: synthetic error"]
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "unknown")
        self.assertEqual(answer["known_valid_units"], 0)
        self.assertIn("eligible_target_has_exclusions", answer["failure_types"])

    def test_mismatched_eligibility_cannot_swap_valid_target_identity(self):
        result, report = sample()
        result["preparation"]["targets"][0]["eligible"] = False
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "unknown")
        self.assertIn("prepared_compact_eligibility_mismatch", answer["failure_types"])

    def test_forbidden_ast_request_cannot_count_as_ready(self):
        result, report = sample()
        report["targets"][0]["structure"]["ast_requested"] = True
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "unknown")
        self.assertIn("forbidden_frontend_request", answer["failure_types"])

    def test_mismatched_unit_count_is_unknown_not_a_chosen_denominator(self):
        result, report = sample()
        result["discovery"]["unique_compile_units"] = 1
        self.assertEqual(self.classify(result, report)["status"], "unknown")

    def test_raw_discovery_requires_wrapper_inventory(self):
        result, report = sample()
        discovery = {"entrypoint_status": "found", "unsupported": [], "compile_units": []}
        answer = outcomes.classify_preparation(result, prepared_report=report, discovery_report=discovery)
        self.assertEqual(answer["status"], "unknown")
        self.assertIn("wrapper_status_inventory_missing", answer["failure_types"])

    def test_diagnostics_are_categorized_and_hashed_without_source_snippets(self):
        result, report = sample()
        reason = "unsupported inspection: private synthetic source snippet"
        report["targets"][0]["exclusion_reasons"] = [reason]
        answer = self.classify(result, report)
        self.assertNotIn(reason, str(answer))
        self.assertTrue(any(row.get("reason_sha256") for row in answer["reason_evidence"]))

    def test_direct_process_failure_timeout_and_start_failure_have_types(self):
        for status in ("failure", "timeout", "interrupted", "start_failure"):
            with self.subTest(status=status):
                answer = outcomes.classify_preparation({"preparation": {"status": status}})
                self.assertEqual(answer["status"], "failed")
                self.assertTrue(answer["failure_type"])

    def test_unsupported_manifest_and_blocked_stage_are_typed(self):
        unsupported = outcomes.classify_preparation({"preparation": {"status": "unsupported", "reason": "noninteger root parameters"}})
        self.assertEqual(unsupported["status"], "unsupported")
        blocked = outcomes.classify_preparation({"preparation": {"status": "not_started", "reason": "discovery report unavailable"},
                                                "discovery": {"status": "timeout", "failure_type": "timeout"}})
        self.assertEqual(blocked["status"], "not_started")
        self.assertEqual(blocked["failure_type"], "blocked_by_discovery_timeout")

    def test_unknown_data_never_has_empty_failure_type(self):
        for result in ({}, {"preparation": None}, {"preparation": {"status": "unknown"}}, {"preparation": {"status": "unsupported"}}):
            with self.subTest(result=result):
                answer = outcomes.classify_preparation(result)
                self.assertEqual(answer["status"], "unknown")
                self.assertTrue(answer["failure_type"])

    def test_malformed_identity_and_status_metadata_fail_closed_without_crashing(self):
        result, report = sample()
        result["preparation"]["status"] = []
        report["targets"][0]["definition"]["label"] = []
        result["discovery"]["callsite_wrapper_statuses"] = [{}]
        result["discovery"]["callsites"] = 1
        answer = self.classify(result, report)
        self.assertEqual(answer["status"], "unknown")
        self.assertTrue(answer["failure_type"])

    def test_normalization_preserves_original_and_process_exit_evidence(self):
        result, report = sample()
        result["preparation"]["status"] = "partial"
        result["discovery"]["unsupported"] = [{"reason": "synthetic"}]
        result["plan"] = {"status": "failure", "exit_code": 1, "failure_type": None}
        original = deepcopy(result)
        normalized = outcomes.normalize_result(result, prepared_report=report)
        self.assertEqual(result, original)
        self.assertEqual(normalized["preparation"]["status"], "partial")
        self.assertEqual(normalized["preparation"]["exit_code"], 0)
        self.assertEqual(normalized["preparation"]["failure_type"], "partial_preparation")
        self.assertEqual(normalized["plan"]["failure_type"], "plan_failure")


if __name__ == "__main__":
    unittest.main()
