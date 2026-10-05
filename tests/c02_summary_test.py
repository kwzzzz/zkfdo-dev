"""Negative denominator/versioning checks; synthetic metadata only, no tool execution."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).resolve().parents[1] / "scripts/summarize_c02_corpus.py"
SPEC = importlib.util.spec_from_file_location("c02_summary", PATH)
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def measurement(status="success", constraints=0):
    return {"repository": "example/toy", "commit_sha": "a" * 40,
            "entrypoint": "main.circom", "source_sha256": "b" * 64,
            "manual_interventions": 0, "zkfuzz_executions": 0,
            "compile": {"status": status, "constraints": constraints, "elapsed_seconds": 1.0},
            "discovery": {"status": "success", "entrypoint_status": "found", "callsites": 2,
                          "unique_compile_units": 1, "compiler_processes": 1,
                          "callsite_wrapper_statuses": ["compile_succeeded"] * 2,
                          "unsupported": [], "elapsed_seconds": 2.0},
            "preparation": {"status": "success", "expected_targets": 2, "eligible": 2,
                            "targets": [{"label": "root", "eligible": True},
                                        {"label": "unit", "eligible": True}], "elapsed_seconds": 3.0},
            "plan": {"status": "success", "elapsed_seconds": 0.1}}


def repo(entries):
    return {"full_name": "example/toy", "inclusion": {"status": "included", "reasons": []},
            "entrypoints": entries, "entrypoint_inventory": {"status": "complete"},
            "manual_intervention_count": 0}


def entry(result=None, declarations=1):
    value = SUMMARY.measurement_summary([({"path": "synthetic/result.json", "sha256": "c" * 64}, result)]) if result else {
        "status": "not_started", "compile": {"status": "not_started", "constraints": None},
        "preparation": {"status": "not_started"}}
    return {"main_declaration_count": declarations, "measurement": value}


class SummaryDenominators(unittest.TestCase):
    def test_parser_subtypes_distinguish_arrays_unknown_values_and_fallback_without_source(self):
        examples = (
            ("compile-time variable arrays are unsupported by this MVP", "compile_time_variable_array"),
            ("compile-time variable is not supported: unknown compile-time value SECRET_IDENTIFIER", "unresolved_compile_time_value"),
            ("component array index must be non-negative", "unsupported_component_index"),
            ("template parameters are not concrete: unsupported expression SECRET_EXPR", "unsupported_template_parameters"),
            ("the target source include closure already declares component main", "definition_include_closure_contains_main"),
            ("unknown future parser diagnostic SECRET_UNKNOWN", "other_or_unclassified"),
        )
        for reason, subtype in examples:
            with self.subTest(subtype=subtype):
                value = SUMMARY.reason_metadata(reason)
                self.assertEqual(value["reason_subtype"], subtype)
                self.assertEqual(value["reason_class"], SUMMARY.reason_class(reason))
                self.assertNotIn("SECRET_", json.dumps(value))
                self.assertEqual(len(value["reason_sha256"]), 64)

    def test_missing_measurement_stays_in_denominator_and_is_not_zero_constraints(self):
        data = SUMMARY.group_summary([repo([entry(measurement()), entry()])])
        self.assertEqual(data["compile_success_rate"], {"numerator": 1, "denominator": 2, "rate": 0.5})
        self.assertEqual(data["constraint_counts"]["known"], 1)
        self.assertEqual(data["constraint_counts"]["unknown"], 1)
        self.assertEqual(data["constraint_counts"]["bins"]["zero"], 1)
        self.assertEqual(data["repository_compile_any"]["numerator"], 1)
        self.assertEqual(data["repository_compile_all_known_entrypoints"]["numerator"], 0)
        self.assertEqual(data["manual_interventions"]["measurement_unknown_count"], 1)

    def test_partial_or_missing_proof_cannot_be_complete_preparation(self):
        for mutate in (
            lambda value: value["preparation"].update(status="partial"),
            lambda value: value["preparation"].update(eligible=1),
            lambda value: value["discovery"].update(unsupported=[{"reason": "unsupported syntax"}]),
            lambda value: value["discovery"].pop("entrypoint_status"),
            lambda value: value["discovery"].update(callsite_wrapper_statuses=[]),
            lambda value: value["plan"].update(status="failure"),
        ):
            value = measurement()
            mutate(value)
            self.assertNotEqual(SUMMARY.preparation_state(value), "success")
            result = SUMMARY.group_summary([repo([entry(value)])])
            self.assertEqual(result["complete_preparation_rate"]["numerator"], 0)

    def test_constraint_threshold_missing_and_failed_counts(self):
        values = [measurement(constraints=count) for count in (0, 99999, 100000, None)]
        values.append(measurement(status="failure", constraints=1000000))
        data = SUMMARY.group_summary([repo([entry(value) for value in values])])
        self.assertEqual(data["constraint_counts"]["known"], 3)
        self.assertEqual(data["constraint_counts"]["unknown"], 2)
        self.assertEqual(data["constraint_counts"]["bins"]["at_least_100000"], 1)
        self.assertEqual(data["compile_success_rate"]["numerator"], 4)

    def test_declared_main_count_is_not_file_compile_denominator(self):
        data = SUMMARY.group_summary([repo([entry(measurement(), declarations=2)])])
        self.assertEqual(data["entrypoint_files"], 1)
        self.assertEqual(data["main_declarations"], 2)
        self.assertEqual(data["compile_success_rate"]["denominator"], 1)

    def test_excluded_repo_does_not_enter_compile_denominator(self):
        excluded = repo([entry()])
        excluded["inclusion"] = {"status": "excluded", "reasons": ["date"]}
        result = SUMMARY.group_summary([excluded])
        self.assertEqual(result["repositories"], 1)
        self.assertEqual(result["compile_success_rate"]["denominator"], 0)
        self.assertIsNone(result["constraint_counts"]["minimum"])

    def test_raw_source_diagnostics_are_not_copied_and_missing_report_is_not_proven_adapter_bug(self):
        value = measurement()
        value["discovery"]["unsupported"] = [{"source_path": "toy.circom", "line": 1,
                                             "construct": "MUST_NOT_COPY_SOURCE", "reason": "MUST_NOT_COPY_SOURCE"}]
        value["preparation"]["status"] = "not_started"
        value["preparation"]["reason"] = "discovery report unavailable"
        result = entry(value)["measurement"]
        self.assertNotIn("MUST_NOT_COPY_SOURCE", json.dumps(result))
        self.assertFalse(result["implementation_repair"])
        self.assertEqual(result["preparation"]["reason_class"], "discovery_report_unavailable")


class VersionSelection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "runs/c02"
        self.first = self.run / "measurements/unit/result.json"
        write(self.first, measurement())

    def test_worse_linked_repair_is_selected_over_successful_original(self):
        value = measurement(status="failure", constraints=None)
        value["supersedes"] = SUMMARY.reference(self.first, self.root)
        value["repair"] = {"reason": "adapter previously missed UUID subdirectory"}
        value["preparation"]["status"] = "failed"
        write(self.first.with_name("result-v2.json"), value)
        chain = SUMMARY.measurements(self.run, self.root)[("example/toy", "main.circom")]
        self.assertEqual(chain[0][1]["compile"]["status"], "failure")
        self.assertEqual(len(chain), 2)
        brief = SUMMARY.measurement_summary(chain)
        self.assertTrue(brief["implementation_repair"])
        self.assertEqual(len(brief["history"]), 1)

    def test_unlinked_versions_are_not_chosen_by_filename_or_quality(self):
        write(self.first.with_name("result-v2.json"), measurement(status="failure"))
        with self.assertRaisesRegex(ValueError, "one explicit supersedes"):
            SUMMARY.measurements(self.run, self.root)

    def test_hash_mismatch_or_different_commit_rejected(self):
        for change_identity in (False, True):
            value = measurement()
            value["supersedes"] = SUMMARY.reference(self.first, self.root)
            if change_identity:
                value["commit_sha"] = "f" * 40
            else:
                value["supersedes"]["sha256"] = "0" * 64
            write(self.first.with_name("result-v2.json"), value)
            with self.assertRaises(ValueError):
                SUMMARY.measurements(self.run, self.root)

    def test_interrupted_rerun_keeps_unknown_old_cost_and_reused_compile_once(self):
        original = measurement()
        for stage in ("compile", "discovery"):
            original[stage].update(process_started=True,
                stdout={"path": f"old/{stage}/stdout", "sha256": "1" * 64},
                stderr={"path": f"old/{stage}/stderr", "sha256": "2" * 64})
        original["discovery"].update(status="interrupted", elapsed_seconds=None,
            interruption={"path": "controller-interruption.json", "sha256": "3" * 64})
        original["preparation"] = {"status": "not_started"}
        original.pop("plan")
        write(self.first, original)
        repaired = measurement()
        repaired["compile"] = copy.deepcopy(original["compile"])
        repaired["discovery"].update(elapsed_seconds=5.0, process_started=True,
            stdout={"path": "repair/discovery/stdout", "sha256": "4" * 64},
            stderr={"path": "repair/discovery/stderr", "sha256": "5" * 64})
        repaired["supersedes"] = SUMMARY.reference(self.first, self.root)
        repaired["repair"] = {"reason": "resume controller-interrupted discovery", "rerun_discovery": True,
                              "rerun_compile": False}
        write(self.first.with_name("result-v2.json"), repaired)
        chain = SUMMARY.measurements(self.run, self.root)[("example/toy", "main.circom")]
        brief = SUMMARY.measurement_summary(chain)
        result = SUMMARY.group_summary([repo([{"main_declaration_count": 1, "measurement": brief}])])
        attempts = result["all_recorded_stage_attempts"]
        self.assertEqual(attempts["compile"]["recorded_attempts"], 1)
        self.assertEqual(attempts["discovery"]["recorded_attempts"], 2)
        self.assertEqual(attempts["discovery"]["status_counts"], {"interrupted": 1, "success": 1})
        self.assertEqual(attempts["discovery"]["elapsed_seconds"]["sum"], 5.0)
        self.assertEqual(attempts["discovery"]["elapsed_seconds"]["unknown"], 1)
        self.assertIsNone(attempts["discovery"]["total_elapsed_seconds"])
        self.assertEqual(result["discovery_rerun_entrypoints"], 1)
        self.assertEqual(result["controller_interrupted_entrypoints"], 1)
        self.assertEqual(brief["history"][0]["stages"]["discovery"]["interruption"], original["discovery"]["interruption"])

    def test_wrapper_reason_reads_only_linked_metadata_and_preserves_missing_reason(self):
        value = measurement()
        value["discovery"]["callsite_wrapper_statuses"] = ["unsupported", "unsupported"]
        report = self.first.parent / "discovery/id/discovery.json"
        write(report, {"targets": [
            {"identity": "SECRET_CALLSITE_VALUES", "source_path": "library.circom", "wrapper_status": "unsupported",
             "failure_reason": "the target source include closure already declares component main"},
            {"identity": "OTHER_SECRET_VALUES", "source_path": "other.circom", "wrapper_status": "unsupported",
             "failure_reason": None}]})
        value["discovery"]["report"] = SUMMARY.reference(report, self.root)
        brief = SUMMARY.measurement_summary([(SUMMARY.reference(self.first, self.root), value)], self.root)
        diagnostics = brief["discovery"]["wrapper_failure_diagnostics"]
        self.assertEqual([row["reason_subtype"] for row in diagnostics],
                         ["definition_include_closure_contains_main", "unknown_missing_reason"])
        self.assertIsNone(diagnostics[1]["reason_sha256"])
        self.assertNotIn("SECRET_", json.dumps(diagnostics))
        report.write_text(report.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            SUMMARY.measurement_summary([(SUMMARY.reference(self.first, self.root), value)], self.root)


class CompleteSummary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "runs/c02"
        self.meta = self.run / "repositories/example__toy/metadata.json"
        row = {**repo([]), "canonical_full_name": "example/toy", "commit_sha": "a" * 40,
               "source_memberships": ["github_top200", "zkbugs", "sok_2026"],
               "exposure": {"stratum": "known_bug_listed"},
               "license": {"status": "declared", "evidence": [
                   {"kind": "root_readme_statement", "path": "README.md", "sha256": "e" * 64,
                    "statement": "MUST_NOT_APPEAR_LICENSE_SOURCE_TEXT"}]},
               "entrypoints": [{"path": "main.circom", "line": line, "sha256": "b" * 64} for line in (1, 9)],
               "metadata_path": str(self.meta.relative_to(self.root))}
        write(self.meta, row)
        self.census = self.run / "repositories.json"
        write(self.census, {"repositories": [row]})
        write(self.run / "repository-census-inputs.json", {"count": 1, "repositories": [row]})
        write(self.run / "catalog_sources.json", {})
        write(self.run / "procedure-lock.json", {})
        write(self.run / "tool-lock.json", {})
        write(self.root / "docs/c02_corpus_procedure_2026-10-02.md", {})
        write(self.run / "measurements/unit/result.json", measurement())

    def test_overlap_repeated_main_and_license_source_are_preserved_or_filtered_correctly(self):
        result = SUMMARY.build_summary(self.run, self.census, self.root)
        self.assertEqual(result["overall"]["repositories"], 1)
        self.assertEqual(result["overall"]["entrypoint_files"], 1)
        self.assertEqual(result["overall"]["main_declarations"], 2)
        self.assertEqual(sum(group["repositories"] for group in result["by_source"].values()), 3)
        self.assertNotIn("MUST_NOT_APPEAR", json.dumps(result))
        self.assertEqual(result["status"], "complete_known_inventory")

    def test_omitted_census_repo_and_changed_source_membership_rejected(self):
        original = json.loads(self.census.read_text())
        write(self.census, {"repositories": []})
        with self.assertRaisesRegex(ValueError, "denominator"):
            SUMMARY.build_summary(self.run, self.census, self.root)
        changed = copy.deepcopy(original)
        changed["repositories"][0]["source_memberships"] = ["github_top200"]
        write(self.census, changed)
        with self.assertRaisesRegex(ValueError, "source memberships"):
            SUMMARY.build_summary(self.run, self.census, self.root)

    def test_markdown_uses_compact_tables_and_all_repository_rows(self):
        result = SUMMARY.build_summary(self.run, self.census, self.root)
        text = SUMMARY.markdown(result)
        self.assertIn("| 원본 제약 수 | entrypoint 파일 수 |", text)
        self.assertIn("| 0 | 1 |", text)
        self.assertIn("| unknown | 0 |", text)
        self.assertIn("| 단계 | 성공 | 부분 | 실패 |", text)
        self.assertIn("조사 전체 wall이 아니다", text)
        self.assertIn("| example/toy |", text)
        self.assertNotIn('"bins":', text)

    def test_source_query_time_revision_and_reference_are_available(self):
        response = self.run / "github-search-page-1-network.json"
        write(response, {"items": [], "total_count": 200})
        metadata = {"url": "https://api.github.com/search/repositories?q=language%3ACircom&sort=stars&order=desc&per_page=100&page=1",
                    "queried_at": "2026-10-02T01:02:03Z", "http_status": 200,
                    **SUMMARY.reference(response, self.root)}
        write(self.run / "github-search-page-1-network.meta.json", metadata)
        catalog = {"sources": [{"source": "zkbugs", "dataset_repository": "example/dataset",
                                "dataset_revision": "d" * 40, "project_count": 1,
                                "circom_project_count": 1, "retrievals": []}]}
        write(self.run / "catalog_sources.json", catalog)
        value = SUMMARY.build_summary(self.run, self.census, self.root)
        self.assertEqual(value["source_queries"]["github_search_pages"][0]["query"], "language:Circom")
        text = SUMMARY.markdown(value)
        self.assertIn("2026-10-02T01:02:03Z", text)
        self.assertIn("d" * 40, text)
        self.assertIn("github-search-page-1-network.meta.json", text)

    def test_collection_and_role_counts_use_paths_not_fixed_counts(self):
        collection = repo([])
        collection["full_name"] = "ArmanKolozyan/CCC-Check"
        collection["entrypoints"] = [{"path_roles": ["test", "vendor_or_dependency"]},
                                    {"path_roles": ["unclassified"]}]
        other = repo([{"path_roles": ["example"]}])
        result = SUMMARY.inventory_composition([collection, other])
        self.assertEqual(result["known_entrypoint_files"], 3)
        self.assertEqual(result["identified_collection_file_fraction"]["numerator"], 2)
        self.assertEqual(sum(result["path_role_counts_overlapping"].values()), 4)


class VerifiedChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.run = self.root / "runs/c02"
        self.logs = self.run / "checks"
        self.logs.mkdir(parents=True)

    def test_exit_hash_and_log_summaries_are_all_required(self):
        log = self.logs / "3-test.log"
        log.write_text("test result: ok. 7 passed; 0 failed; 1 ignored; 0 measured;\n"
                       "test result: ok. 2 passed; 0 failed; 3 ignored; 0 measured;\n")
        write(self.logs / "checks.json", [{"command": ["cargo", "test"], "exit_code": 0,
                                          **SUMMARY.reference(log, self.root)}])
        python_log = self.run / "python-tests.log"
        python_log.write_text("Ran 12 tests in 0.010s\n\nOK\n")
        write(self.run / "python-tests.check.json", {"command": ["python3", "-m", "unittest"],
              "exit_code": 0, **SUMMARY.reference(python_log, self.root)})
        checks = SUMMARY.check_summary(self.run, self.root)["checks"]
        self.assertEqual([check["status"] for check in checks], ["passed", "passed"])
        self.assertEqual(checks[0]["counts"], {"passed": 9, "failed": 0, "ignored": 4, "test_binaries": 2})
        self.assertEqual(checks[1]["counts"]["ran"], 12)
        log.write_text(log.read_text() + "changed")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            SUMMARY.check_summary(self.run, self.root)

    def test_python_ok_without_exit_and_hash_metadata_is_unverified(self):
        (self.run / "python-tests.log").write_text("Ran 99 tests in 0.1s\n\nOK\n")
        check = SUMMARY.check_summary(self.run, self.root)["checks"][0]
        self.assertEqual(check["status"], "unverified")
        self.assertNotIn("counts", check)

    def test_zero_exit_without_test_summary_and_nonzero_exit_are_not_passes(self):
        for exit_code in (0, 1):
            log = self.logs / "test.log"
            log.write_text("no test summary\n")
            write(self.logs / "checks.json", [{"command": ["cargo", "test"], "exit_code": exit_code,
                                              **SUMMARY.reference(log, self.root)}])
            check = SUMMARY.check_summary(self.run, self.root)["checks"][0]
            self.assertNotEqual(check["status"], "passed")

    def test_linked_python_check_selects_lower_count_revision_and_preserves_previous_reference(self):
        old_log = self.run / "python-tests.log"
        old_log.write_text("Ran 99 tests in 0.1s\n\nOK\n")
        old = self.run / "python-tests.check.json"
        command = ["python3", "-m", "unittest"]
        write(old, {"command": command, "exit_code": 0, **SUMMARY.reference(old_log, self.root)})
        new_log = self.run / "python-tests-v3.log"
        new_log.write_text("Ran 2 tests in 0.1s\n\nOK\n")
        write(self.run / "python-tests.check-v2.json", {"command": command, "exit_code": 0,
              **SUMMARY.reference(new_log, self.root), "supersedes": SUMMARY.reference(old, self.root)})
        result = SUMMARY.check_summary(self.run, self.root)
        self.assertEqual(result["checks"][0]["counts"]["ran"], 2)
        self.assertEqual(result["checks"][0]["log"]["path"], str(new_log.relative_to(self.root)))
        self.assertEqual(result["previous_python_check_references"], [SUMMARY.reference(old, self.root)])

    def test_python_check_fork_hash_mismatch_and_changed_command_are_rejected(self):
        for problem in ("fork", "hash", "command"):
            with self.subTest(problem=problem):
                run = self.run / problem
                run.mkdir()
                log = run / "python-tests.log"
                log.write_text("Ran 1 test in 0.1s\n\nOK\n")
                old = run / "python-tests.check.json"
                command = ["python3", "-m", "unittest"]
                write(old, {"command": command, "exit_code": 0, **SUMMARY.reference(log, self.root)})
                current = {"command": command, "exit_code": 0, **SUMMARY.reference(log, self.root),
                           "supersedes": SUMMARY.reference(old, self.root)}
                if problem == "hash":
                    current["supersedes"]["sha256"] = "0" * 64
                elif problem == "command":
                    current["command"] = ["python3", "different_suite.py"]
                write(run / "python-tests.check-v2.json", current)
                if problem == "fork":
                    write(run / "python-tests.check-v3.json", current)
                with self.assertRaises(ValueError):
                    SUMMARY.check_summary(run, self.root)


class CompilerFailureRefinement(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.result_path = self.root / "measurements/unit/result.json"
        self.compiler = self.result_path.parent / "compile"
        self.compiler.mkdir(parents=True)
        self.stdout = self.compiler / "stdout.log"
        self.stderr = self.compiler / "stderr.log"
        self.stdout.write_text("")
        self.stderr.write_text("\x1b[31merror[P1014]\x1b[0m: The file SECRET_SOURCE_PATH to be included has not been found\n")
        self.value = {"status": "failure", "failure_type": "compiler_or_tool_error",
                      "stdout": SUMMARY.reference(self.stdout, self.root),
                      "stderr": SUMMARY.reference(self.stderr, self.root)}
        self.record = {"path": str(self.result_path.relative_to(self.root)), "sha256": "0" * 64}

    def test_p1014_is_refined_without_erasing_original_or_copying_source(self):
        value = SUMMARY.refine_compile_failure(self.value, self.record, self.root)
        self.assertEqual(value["original_failure_type"], "compiler_or_tool_error")
        self.assertEqual(value["refined_failure_type"], "missing_include")
        self.assertEqual(value["diagnostic_codes"], ["P1014"])
        self.assertEqual(len(value["logs"]), 2)
        self.assertNotIn("SECRET_SOURCE_PATH", json.dumps(value))

    def test_hash_mismatch_prevents_diagnostic_refinement(self):
        self.stderr.write_text("changed after recorded hash")
        with self.assertRaisesRegex(ValueError, "compiler log hash mismatch"):
            SUMMARY.refine_compile_failure(self.value, self.record, self.root)

    def test_source_or_unknown_error_text_does_not_trigger_p1014_rule(self):
        self.stderr.write_text('error[T9999]: unknown\n 42 | signal error[P1014];\n')
        self.value["stderr"] = SUMMARY.reference(self.stderr, self.root)
        value = SUMMARY.refine_compile_failure(self.value, self.record, self.root)
        self.assertIsNone(value["refined_failure_type"])
        self.assertEqual(value["status"], "verified_original_class_retained")
        self.assertEqual(value["diagnostic_codes"], ["T9999"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
