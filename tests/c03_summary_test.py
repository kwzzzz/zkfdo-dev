"""Metadata-only census denominators and fail-closed publication tests."""

from copy import deepcopy
import importlib.util
import csv
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("c03_summary", Path(__file__).resolve().parents[1] / "scripts/summarize_c03_corpus.py")
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / "run"
        self.run.mkdir()
        self.repo = {"full_name": "synthetic/service", "canonical_full_name": "synthetic/service", "commit_sha": "1" * 40,
                     "source_memberships": ["github_top200", "team_curated"], "c02_included": True,
                     "team_curated": True, "main_eligible": True,
                     "manual_collection_transport_interventions": 0,
                     "classification": {"classification": "production", "evidence": [{"text": "Synthetic protocol circuits.", "kind": "csv"}]},
                     "team_rows": [{"sheet_item": 1, "circuit_folders_declared": "circuits", "usage_evidence_declared": "Synthetic protocol circuits.", "circom_version_declared": "2.2.3"}]}
        self.entry = {"key": "source:circuits/main.circom", "kind": "source_main", "display_path": "circuits/main.circom",
                      "source_path": "circuits/main.circom", "path": "/not-opened/main.circom", "expected_sha256": "2" * 64,
                      "metadata": {"path_roles": ["unclassified"], "raw_source": "must not appear"}}
        self.census = {"repositories": [self.repo]}
        self.write_json(self.run / "census.json", self.census)
        self.before_inventory = {"census_ref": summary.reference(self.run / "census.json"), "repositories": [{"full_name": self.repo["full_name"], "entries": [self.entry]}]}
        self.after_inventory = deepcopy(self.before_inventory)
        self.save_inventories()
        self.measure("before", "failure", "missing_include")
        self.measure("after", "success", None, constraints=150000)
        self.write_json(self.run / "setups/synthetic__service/setup.json", {"status": "success", "zkfuzz_invocations": 0,
            "manual_intervention_count": 0, "elapsed_seconds": 1.5, "steps": [{"phase": "submodule", "status": "success", "failure_type": None}]})
        self.create_locks_and_checks()

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def save_inventories(self):
        self.write_json(self.run / "entrypoints-before.json", self.before_inventory)
        self.write_json(self.run / "entrypoints-after.json", self.after_inventory)
        lock = self.run / "measurement-lock.json"
        if lock.exists():
            data = json.loads(lock.read_text())
            data["inventory_before_ref"] = summary.reference(self.run / "entrypoints-before.json")
            self.write_json(lock, data)

    def result_path(self, phase, key=None, name=None):
        return self.run / "measurements" / summary.measurement_id(name or self.repo["full_name"], key or self.entry["key"]) / phase / "result.json"

    def measure(self, phase, status, failure, constraints=None, entry=None, repo=None):
        repo = repo or self.repo
        entry = entry or self.entry
        result = {"repository": repo["full_name"], "commit_sha": repo["commit_sha"], "entrypoint_key": entry["key"],
                  "entrypoint": entry["display_path"], "entrypoint_kind": entry["kind"], "phase": phase,
                  "source_sha256": entry["expected_sha256"], "settings": {"optimization": "O1", "prime": "bn128"}, "zkfuzz_executions": 0,
                  "compile": {"status": status, "failure_type": failure, "constraints": constraints, "elapsed_seconds": 0.5}}
        if phase == "after":
            result.update(discovery={"status": "success", "failure_type": None, "elapsed_seconds": 0.3},
                          preparation={"status": "partial", "failure_type": "partial_preparation", "failure_types": ["wrapper_compile_failed"], "elapsed_seconds": 0.2},
                          plan={"status": "success", "failure_type": None, "elapsed_seconds": 0.1})
        self.write_json(self.result_path(phase, entry["key"], repo["full_name"]), result)
        return result

    def create_locks_and_checks(self):
        procedure = self.run / "procedure.md"
        procedure.write_text("synthetic fixed procedure")
        self.write_json(self.run / "procedure-lock.json", {"procedure_path": str(procedure), "sha256": summary.digest(procedure), "source_references": []})
        self.write_json(self.run / "tools/tools.json", {})
        self.write_json(self.run / "tools/tools-lock.json", {"tools": summary.reference(self.run / "tools/tools.json")})
        self.write_json(self.run / "measurement-lock.json", {"procedure_ref": summary.reference(self.run / "procedure-lock.json"),
            "census_ref": summary.reference(self.run / "census.json"), "inventory_before_ref": summary.reference(self.run / "entrypoints-before.json"),
            "compiler_tools": [], "implementations": [], "workers": 2, "zkfuzz_executions": 0})
        commands = []
        for index, command in enumerate((["cargo", "fmt"], ["cargo", "clippy", "--all-targets", "--all-features", "--", "-D", "warnings"], ["cargo", "test"], ["python3", "-m", "unittest", "discover"])):
            log = self.run / "checks" / f"{index}.log"
            log.parent.mkdir(exist_ok=True)
            log.write_text("synthetic successful check\n")
            commands.append({"command": command, "exit_code": 0, "log": summary.reference(log), "elapsed_seconds": 0.1})
        self.write_json(self.run / "checks/checks.json", {"commands": commands})

    def test_failed_before_stays_in_paired_denominator(self):
        report = summary.summarize(self.run)
        pair = report["overall"]["paired"]
        self.assertEqual(pair["entrypoints"], 1)
        self.assertEqual(pair["before_compile_success"]["numerator"], 0)
        self.assertEqual(pair["after_compile_success"]["numerator"], 1)
        self.assertEqual(pair["transitions"], {"failure -> success": 1})

    def test_missing_measurement_blocks_publish_and_remains_in_preview_denominator(self):
        self.result_path("after").unlink()
        with self.assertRaises(ValueError):
            summary.summarize(self.run)
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertEqual(report["overall"]["after_entrypoints"], 1)
        self.assertEqual(report["overall"]["after_compile_statuses"], {"missing": 1})
        with self.assertRaises(ValueError):
            summary.write_outputs(report, self.run / "results")
        self.assertFalse((self.run / "results.json").exists())

    def test_changed_source_is_not_setup_effect(self):
        changed = deepcopy(self.entry)
        changed["expected_sha256"] = "3" * 64
        self.after_inventory["repositories"][0]["entries"] = [changed]
        self.save_inventories()
        self.measure("after", "success", None, entry=changed)
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["paired"]["entrypoints"], 0)
        self.assertEqual(report["overall"]["pairing_statuses"], {"source_changed": 1})

    def test_after_source_change_with_preserved_old_inventory_is_reportable_not_paired(self):
        path = self.result_path("after")
        data = json.loads(path.read_text()); data["source_sha256"] = "3" * 64
        self.write_json(path, data)
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["pairing_statuses"], {"source_changed": 1})
        self.assertEqual(report["overall"]["after_compile_success"]["numerator"], 1)
        after = report["repositories"][0]["entries"][0]["after"]
        self.assertEqual(after["inventory_source_sha256"], "2" * 64)
        self.assertEqual(after["source_sha256"], "3" * 64)
        self.assertTrue(after["source_changed_since_inventory"])

    def test_before_source_mismatch_still_blocks_publication(self):
        path = self.result_path("before")
        data = json.loads(path.read_text()); data["source_sha256"] = "3" * 64
        self.write_json(path, data)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def generated_pair(self):
        entry = deepcopy(self.entry)
        entry["kind"] = "config_generated"
        entry["metadata"] = {"source_sha256": "4" * 64,
                             "circomkit": {"path": "circomkit.json", "sha256": "5" * 64},
                             "circuits": {"path": "circuits.json", "sha256": "6" * 64}}
        self.before_inventory["repositories"][0]["entries"] = [deepcopy(entry)]
        self.after_inventory["repositories"][0]["entries"] = [deepcopy(entry)]
        self.save_inventories()
        for phase in ("before", "after"):
            self.measure(phase, "success", None, entry=entry)

    def test_equal_generated_wrapper_does_not_hide_changed_underlying_source(self):
        self.generated_pair()
        self.after_inventory["repositories"][0]["entries"][0]["metadata"]["source_sha256"] = "7" * 64
        self.save_inventories()
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["paired"]["entrypoints"], 0)
        self.assertEqual(report["overall"]["pairing_statuses"], {"config_source_changed": 1})

    def test_each_config_hash_is_required_even_when_wrapper_hash_unchanged(self):
        for field in ("circomkit", "circuits"):
            with self.subTest(field=field):
                self.generated_pair()
                self.after_inventory["repositories"][0]["entries"][0]["metadata"][field]["sha256"] = "8" * 64
                self.save_inventories()
                report = summary.summarize(self.run)
                self.assertEqual(report["overall"]["pairing_statuses"], {"config_changed": 1})
                self.assertEqual(report["overall"]["paired"]["entrypoints"], 0)

    def test_missing_generated_config_metadata_is_unknown_not_same(self):
        self.generated_pair()
        del self.after_inventory["repositories"][0]["entries"][0]["metadata"]["circuits"]
        self.save_inventories()
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["pairing_statuses"], {"config_metadata_unknown": 1})

    def test_matching_generated_source_and_both_configs_can_be_paired(self):
        self.generated_pair()
        self.assertEqual(summary.summarize(self.run)["overall"]["paired"]["entrypoints"], 1)

    def add_extension(self):
        implementation = self.run / "synthetic_extension.py"
        implementation.write_text("# Metadata fixture, never executed.\n")
        authority = json.loads((self.run / "measurement-lock.json").read_text())
        extension = {"schema_version": 2, "fixed_at": "2026-10-02T00:00:00Z",
                     "census_ref": authority["census_ref"], "inventory_before_ref": authority["inventory_before_ref"],
                     "measurement_v1_ref": summary.reference(self.run / "measurement-lock.json"),
                     "implementations": [summary.reference(implementation)], "compilation_and_preparation": "unchanged_v1",
                     "setup_started": False, "zkfuzz_executions": 0, "change": "synthetic setup discovery extension"}
        self.write_json(self.run / "measurement-extension-lock.v2.json", extension)
        return extension

    def test_optional_extension_lock_is_verified_and_reported_when_present(self):
        extension = self.add_extension()
        report = summary.summarize(self.run)
        recorded = report["provenance"]["locks"]["measurement-extension-lock.v2.json"]
        self.assertEqual(recorded["measurement_v1_ref"], extension["measurement_v1_ref"])
        self.assertEqual(recorded["implementations"], extension["implementations"])
        self.assertIn("measurement-extension-lock.v2.json", summary.render_markdown(report))

    def test_extension_cannot_silently_use_a_different_census(self):
        extension = self.add_extension()
        other = self.run / "other-census.json"
        self.write_json(other, {"repositories": []})
        extension["census_ref"] = summary.reference(other)
        self.write_json(self.run / "measurement-extension-lock.v2.json", extension)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_tampered_extension_implementation_blocks_finalization(self):
        self.add_extension()
        (self.run / "synthetic_extension.py").write_text("# Changed after fixing.\n")
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def add_transport_retry(self):
        prior = deepcopy(self.census)
        prior["repositories"][0]["collection_status"] = "failed"
        prior_path = self.run / "prior-census.json"
        self.write_json(prior_path, prior)
        self.census["repositories"][0].update(manual_collection_transport_interventions=1, collection_status="complete",
            collection_retry_reason="same_pinned_SHA_public_transport_after_partial_local_clone_failure")
        retry = {"prior_census": summary.reference(prior_path), "created_at": "2026-10-02T00:00:00Z",
                 "retry_is_manual_collection_transport_intervention": True,
                 "repositories": [{"full_name": self.repo["full_name"], "commit_sha": self.repo["commit_sha"], "collection_status": "complete"}]}
        retry_path = self.run / "collection-retries-v2.json"
        self.write_json(retry_path, retry)
        self.census.update(manual_collection_transport_retry_count=1, transport_retries=summary.reference(retry_path))
        self.write_json(self.run / "census.json", self.census)
        for inventory in (self.before_inventory, self.after_inventory):
            inventory["census_ref"] = summary.reference(self.run / "census.json")
        self.save_inventories(); self.create_locks_and_checks()

    def test_transport_retry_is_manual_but_not_package_or_include_repair(self):
        self.add_transport_retry()
        report = summary.summarize(self.run)
        counts = report["overall"]
        self.assertEqual(counts["manual_setup_intervention_count"], 0)
        self.assertEqual(counts["manual_collection_transport_retry_count"], 1)
        self.assertEqual(counts["manual_intervention_count"], 1)
        retry = report["provenance"]["collection_transport_retries"]
        self.assertEqual(retry["repositories"][0]["prior_collection_status"], "failed")
        self.assertEqual(retry["repositories"][0]["retry_collection_status"], "complete")
        text = summary.render_markdown(report)
        self.assertIn("수동 package/include 수선 | 0", text)
        self.assertIn("수동 수집 transport 재시도 | 1", text)
        self.assertIn("collection-retries-v2.json", text)

    def test_transport_retry_count_requires_hash_linked_record(self):
        self.add_transport_retry()
        self.census.pop("transport_retries")
        self.write_json(self.run / "census.json", self.census)
        for inventory in (self.before_inventory, self.after_inventory):
            inventory["census_ref"] = summary.reference(self.run / "census.json")
        self.save_inventories(); self.create_locks_and_checks()
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_transport_retry_cannot_claim_different_commit_as_same_pinned_sha(self):
        self.add_transport_retry()
        retry_path = self.run / "collection-retries-v2.json"
        retry = json.loads(retry_path.read_text()); retry["repositories"][0]["commit_sha"] = "9" * 40
        self.write_json(retry_path, retry)
        self.census["transport_retries"] = summary.reference(retry_path)
        self.write_json(self.run / "census.json", self.census)
        for inventory in (self.before_inventory, self.after_inventory):
            inventory["census_ref"] = summary.reference(self.run / "census.json")
        self.save_inventories(); self.create_locks_and_checks()
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def add_recovery(self):
        historical = self.run / "historical"
        historical.mkdir()
        for source, filename in ((self.run / "census.json", "census.json"),
                                 (self.run / "entrypoints-before.json", "inventory-before.json"),
                                 (self.result_path("before"), "baseline.json"),
                                 (self.run / "setups/synthetic__service/setup.json", "setup.json")):
            (historical / filename).write_bytes(source.read_bytes())
        implementation = historical / "helper.py"; implementation.write_text("# Metadata fixture only.\n")
        interruption = historical / "interruption.json"; self.write_json(interruption, {"status": "stopped"})
        records = historical / "clones.json"; self.write_json(records, {"repositories": [self.repo["full_name"]]})
        clean = {"census": summary.reference(self.run / "census.json"), "source_census": summary.reference(historical / "census.json"),
                 "helper": summary.reference(implementation), "records": summary.reference(records), "repository_count": 1,
                 "all_80_original_pinned_commits": True, "all_80_clean_worktrees": True, "setup_started": False, "compilation_started": False}
        self.write_json(self.run / "recovery-lock.v3.json", clean)
        controls = {"passed": True, "offline_requested": True, "corpus_installs": 0, "zkfuzz_invocations": 0,
                    "controls": [{"manager": manager, "version": version, "passed": True,
                                  "capture": {"status": "success", "exit_code": 0, "elapsed_seconds": 0.1},
                                  "marker_presence": {"lifecycle-ran": False, "configuration-hook-ran": False}}
                                 for manager, version in (("pnpm", "10.34.6"), ("yarn", "1.22.22"))]}
        controls_path = historical / "controls.json"; self.write_json(controls_path, controls)
        recovery = {"schema_version": 3, "frozen_at": "2026-10-02T00:00:00Z", "reason": "synthetic rejected CLI configuration",
                    "original_census_ref": summary.reference(historical / "census.json"), "recovery_census_ref": summary.reference(self.run / "census.json"),
                    "original_measurement_lock_ref": summary.reference(self.run / "measurement-lock.json"),
                    "original_inventory_before_ref": summary.reference(historical / "inventory-before.json"),
                    "inventory_before_ref": summary.reference(self.run / "entrypoints-before.json"),
                    "original_setup_interruption_ref": summary.reference(interruption),
                    "original_setup_records": [summary.reference(historical / "setup.json")], "original_incomplete_setup_paths": [],
                    "original_setup_summary": {"completed_repositories": 1, "incomplete_repositories": 0, "not_started_repositories": 0,
                                               "known_elapsed_seconds": 1.5, "incomplete_cost_unknown": False},
                    "baseline_records": [{"original": summary.reference(historical / "baseline.json"), "reused": summary.reference(self.result_path("before"))}],
                    "clean_source_equivalence": [{"repository": self.repo["full_name"], "entrypoint_key": self.entry["key"],
                        "status": "matched", "expected_sha256": "2" * 64, "current_sha256": "2" * 64}],
                    "implementations": [summary.reference(implementation)], "manager_controls_ref": summary.reference(controls_path),
                    "clean_checkout_lock_ref": summary.reference(self.run / "recovery-lock.v3.json"),
                    "all_repository_clean_restart": True, "compilation_and_preparation": "unchanged_v1", "workers": 2,
                    "zkfuzz_executions": 0, "fixed_before_setup": True}
        self.write_json(self.run / "measurement-recovery-lock.v3.json", recovery)
        return recovery

    def test_recovery_preserves_history_and_baseline_reuse_as_separate_provenance(self):
        self.add_recovery()
        report = summary.summarize(self.run)
        recovery = report["provenance"]["recovery"]
        self.assertEqual(recovery["baseline_records_reused"], 1)
        self.assertEqual(recovery["clean_source_equivalence_count"], 1)
        self.assertEqual(recovery["original_completed_setup_timings"]["sum_seconds"], 1.5)
        self.assertTrue(recovery["initial_and_recovery_costs_are_separate"])
        self.assertEqual(report["overall"]["before_entrypoints"], 1)
        self.assertEqual(report["overall"]["timings"]["setup"]["sum_seconds"], 1.5)
        text = summary.render_markdown(report)
        self.assertIn("measurement-recovery-lock.v3.json", text)
        self.assertIn("새 실행 횟수로 세지 않는다", text)

    def test_recovery_reused_record_must_be_byte_identical_to_original(self):
        recovery = self.add_recovery()
        original = self.run / "historical/baseline.json"
        data = json.loads(original.read_text()); data["compile"]["elapsed_seconds"] = 999
        self.write_json(original, data)
        recovery["baseline_records"][0]["original"] = summary.reference(original)
        self.write_json(self.run / "measurement-recovery-lock.v3.json", recovery)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_recovery_cannot_omit_baseline_or_clean_source_equivalence(self):
        recovery = self.add_recovery()
        recovery["baseline_records"] = []
        recovery["clean_source_equivalence"] = []
        self.write_json(self.run / "measurement-recovery-lock.v3.json", recovery)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_recovery_requires_successful_manager_controls_not_only_absent_markers(self):
        recovery = self.add_recovery()
        path = self.run / "historical/controls.json"
        controls = json.loads(path.read_text()); controls["controls"][0]["capture"]["exit_code"] = 1
        self.write_json(path, controls)
        recovery["manager_controls_ref"] = summary.reference(path)
        self.write_json(self.run / "measurement-recovery-lock.v3.json", recovery)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_unknown_hash_is_not_a_matching_hash(self):
        for phase in ("before", "after"):
            inventory = self.before_inventory if phase == "before" else self.after_inventory
            inventory["repositories"][0]["entries"][0]["expected_sha256"] = None
            entry = inventory["repositories"][0]["entries"][0]
            self.measure(phase, "not_started", "source_missing", entry=entry)
        self.save_inventories()
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["paired"]["entrypoints"], 0)
        self.assertEqual(report["overall"]["pairing_statuses"], {"source_hash_unknown": 1})

    def test_missing_source_does_not_turn_a_known_inventory_item_into_missing_measurement(self):
        path = self.result_path("after")
        data = json.loads(path.read_text())
        data["source_sha256"] = None
        data["compile"].update(status="not_started", failure_type="entrypoint_source_missing", constraints=None)
        self.write_json(path, data)
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["after_entrypoints"], 1)
        self.assertEqual(report["overall"]["pairing_statuses"], {"source_hash_unknown": 1})

    def test_inventory_reference_selects_fixed_versioned_census_not_old_filename(self):
        new_path = self.run / "census.v2.json"
        self.write_json(new_path, self.census)
        self.write_json(self.run / "census.json", {"repositories": []})
        for inventory in (self.before_inventory, self.after_inventory):
            inventory["census_ref"] = summary.reference(new_path)
        self.save_inventories()
        lock_path = self.run / "measurement-lock.json"
        lock = json.loads(lock_path.read_text()); lock["census_ref"] = summary.reference(new_path)
        self.write_json(lock_path, lock)
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["repositories"], 1)
        self.assertEqual(report["provenance"]["census"]["path"], str(new_path.resolve()))

    def test_inventory_config_failures_remain_in_repository_record(self):
        self.after_inventory["repositories"][0]["config_failures"] = [{"failure_type": "config_invalid_json", "circomkit_path": "circomkit.json", "failure_reason": "private diagnostic"}]
        self.save_inventories()
        report = summary.summarize(self.run)
        failure = report["repositories"][0]["inventory_failures"]["after"]["config_failures"][0]
        self.assertEqual(failure["failure_type"], "config_invalid_json")
        self.assertNotIn("failure_reason", failure)
        inventory = report["inventory_incompleteness"]
        self.assertEqual(inventory["statuses"], {"incomplete": 1})
        self.assertEqual(inventory["repositories"][0]["reason_codes"], ["config_invalid_json"])
        self.assertEqual(report["overall"]["after_entrypoints"], 1)

    def test_setup_failure_is_retained_overall_and_separate_from_success_cohort(self):
        failed = deepcopy(self.repo)
        failed["full_name"] = "synthetic/environment-blocked"
        failed["canonical_full_name"] = failed["full_name"]
        self.census["repositories"].append(failed)
        self.write_json(self.run / "census.json", self.census)
        for inventory in (self.before_inventory, self.after_inventory):
            inventory["census_ref"] = summary.reference(self.run / "census.json")
            inventory["repositories"].append({"full_name": failed["full_name"], "entries": [deepcopy(self.entry)]})
        self.save_inventories(); self.create_locks_and_checks()
        for phase in ("before", "after"):
            self.measure(phase, "failure", "missing_include", repo=failed)
        self.write_json(self.run / "setups/synthetic__environment-blocked/setup.json", {
            "status": "setup_failure", "failure_types": ["package_manager_version_unsupported"],
            "manual_intervention_count": 0, "zkfuzz_invocations": 0, "steps": [
                {"phase": "submodule", "status": "success"},
                {"phase": "tracked_circom_inventory", "status": "success"},
                {"phase": "package_install", "status": "unsupported", "failure_type": "package_manager_version_unsupported"}]})
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["repositories"], 2)
        self.assertEqual(report["overall"]["after_entrypoints"], 2)
        self.assertEqual(report["main_eligible_cohort"]["after_compile_success"]["denominator"], 2)
        success, failure, unknown = (report["by_setup_status"][key] for key in ("success", "failure", "unknown"))
        self.assertEqual((success["repositories"], success["after_entrypoints"], success["after_compile_success"]["numerator"]), (1, 1, 1))
        self.assertEqual((failure["repositories"], failure["after_entrypoints"], failure["after_compile_success"]["numerator"]), (1, 1, 0))
        self.assertEqual(failure["preparation_statuses"], {"failed": 1})
        self.assertEqual(failure["component_preparation_statuses"], {"partial": 1})
        self.assertEqual(unknown["repositories"], 0)
        self.assertEqual(report["inventory_incompleteness"]["statuses"], {"no_recorded_failure": 2})
        text = summary.render_markdown(report)
        self.assertIn("모든 실패를 zkfDO의 한계로 해석하지 않는다", text)
        self.assertIn("| failure | 1 | 1 | 0/1", text)

    def test_submodule_failure_marks_enumeration_gap_without_inventing_entries(self):
        self.write_json(self.run / "setups/synthetic__service/setup.json", {
            "status": "setup_failure", "failure_types": ["submodule_timeout"],
            "manual_intervention_count": 0, "zkfuzz_invocations": 0, "steps": [
                {"phase": "submodule", "status": "failure", "failure_type": "submodule_timeout"},
                {"phase": "tracked_circom_inventory", "status": "success"}]})
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["after_entrypoints"], 1)
        self.assertEqual(report["inventory_incompleteness"]["statuses"], {"incomplete": 1})
        row = report["inventory_incompleteness"]["repositories"][0]
        self.assertEqual(row["known_entrypoints"], 1)
        self.assertEqual(row["reason_codes"], ["submodule_timeout"])
        self.assertFalse(row["complete_source_coverage_established"])
        self.assertIn("아직 열거하지 못한 entrypoint", summary.render_markdown(report))

    def test_missing_setup_is_unknown_in_conditional_and_inventory_counts(self):
        (self.run / "setups/synthetic__service/setup.json").unlink()
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertEqual(report["overall"]["after_entrypoints"], 1)
        self.assertEqual(report["by_setup_status"]["unknown"]["after_entrypoints"], 1)
        self.assertEqual(report["inventory_incompleteness"]["statuses"], {"unknown": 1})

    def test_full_preparation_does_not_equate_root_only_or_missing_count_with_fragments(self):
        path = self.result_path("after")
        result = json.loads(path.read_text())
        result["preparation"].update(status="success", failure_type=None, failure_types=[])
        for count, expected in ((0, "root_only"), (3, "with_fragments"), (None, "unknown"), (True, "unknown"), (-1, "unknown")):
            with self.subTest(count=count):
                result["discovery"]["unique_compile_units"] = count
                self.write_json(path, result)
                report = summary.summarize(self.run)
                scopes = {key: int(key == expected) for key in ("root_only", "with_fragments", "unknown")}
                self.assertEqual(report["overall"]["full_preparation_scope"], scopes)
                self.assertEqual(report["by_setup_status"]["success"]["full_preparation_scope"], scopes)
                self.assertEqual(report["by_role"]["production"]["full_preparation_scope"], scopes)
                self.assertEqual(report["overall"]["preparation_statuses"], {"success": 1})

    def test_original_compile_failure_cannot_become_automatic_preparation_success(self):
        path = self.result_path("after")
        result = json.loads(path.read_text())
        result["compile"].update(status="failure", failure_type="missing_include")
        result["discovery"]["unique_compile_units"] = 4
        for raw_status in ("success", "partial"):
            with self.subTest(raw_status=raw_status):
                reason = None if raw_status == "success" else "partial_preparation"
                result["preparation"].update(status=raw_status, failure_type=reason)
                result["preparation_outcome"] = {"status": raw_status, "failure_type": reason, "known_valid_units": 4}
                self.write_json(path, result)
                original_bytes = path.read_bytes()
                report = summary.summarize(self.run)
                after = report["repositories"][0]["entries"][0]["after"]
                self.assertEqual(after["preparation_outcome"]["known_valid_units"], 4)
                self.assertEqual(after["preparation"]["status"], raw_status)
                self.assertEqual(after["automatic_preparation_outcome"]["status"], "failed")
                self.assertEqual(after["automatic_preparation_outcome"]["failure_type"], "original_compile_missing_include")
                self.assertEqual(report["overall"]["preparation_statuses"], {"failed": 1})
                self.assertEqual(report["overall"]["component_preparation_statuses"], {raw_status: 1})
                self.assertEqual(report["overall"]["full_preparation_scope"], {"root_only": 0, "with_fragments": 0, "unknown": 0})
                self.assertEqual(report["production_large_entrypoints"][0]["preparation_status"], "failed")
                self.assertEqual(report["production_large_entrypoints"][0]["component_preparation_status"], raw_status)
                self.assertEqual(path.read_bytes(), original_bytes)

    def test_original_compile_not_started_or_unknown_has_explicit_automatic_reason(self):
        path = self.result_path("after")
        result = json.loads(path.read_text())
        result["preparation"].update(status="success", failure_type=None)
        for compile_status, reason, automatic_status in (("not_started", "entrypoint_outside_pinned_project", "not_started"),
                                                       ("unknown", "compiler_result_unknown", "unknown")):
            with self.subTest(compile_status=compile_status):
                result["compile"].update(status=compile_status, failure_type=reason)
                self.write_json(path, result)
                report = summary.summarize(self.run)
                automatic = report["repositories"][0]["entries"][0]["after"]["automatic_preparation_outcome"]
                self.assertEqual(automatic["status"], automatic_status)
                self.assertEqual(automatic["failure_type"], "original_compile_" + reason)
                self.assertEqual(report["overall"]["component_preparation_statuses"], {"success": 1})

    def test_different_settings_are_not_paired(self):
        path = self.result_path("after")
        data = json.loads(path.read_text()); data["settings"]["optimization"] = "O0"
        self.write_json(path, data)
        self.assertEqual(summary.summarize(self.run)["overall"]["pairing_statuses"], {"settings_changed": 1})

    def test_identity_collision_cannot_merge_other_commit_or_target(self):
        path = self.result_path("after")
        data = json.loads(path.read_text()); data["commit_sha"] = "7" * 40
        self.write_json(path, data)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_duplicate_key_and_unexpected_result_are_not_silently_chosen(self):
        self.after_inventory["repositories"][0]["entries"].append(deepcopy(self.entry))
        self.save_inventories()
        extra = deepcopy(self.entry); extra["key"] = "extra"
        self.measure("after", "success", None, entry=extra)
        report = summary.summarize(self.run, allow_incomplete=True)
        codes = {error["code"] for error in report["validation_errors"]}
        self.assertIn("duplicate_entrypoint_key", codes)
        self.assertIn("unexpected_measurement_record", codes)

    def test_after_only_config_generated_is_additional_denominator(self):
        entry = deepcopy(self.entry); entry.update(key="config:new", kind="config_generated")
        self.after_inventory["repositories"][0]["entries"].append(entry)
        self.save_inventories()
        self.measure("after", "failure", "missing_include", entry=entry)
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["after_entrypoints"], 2)
        self.assertEqual(report["overall"]["paired"]["entrypoints"], 1)
        self.assertEqual(report["overall"]["config_generated_after"], 1)
        self.assertEqual(report["overall"]["pairing_statuses"]["after_only"], 1)

    def test_repo_without_main_and_unknown_eligibility_remain_present(self):
        repo = deepcopy(self.repo); repo.update(full_name="synthetic/no-main", canonical_full_name="synthetic/no-main", main_eligible=None, team_curated=False)
        self.census["repositories"].append(repo)
        self.write_json(self.run / "census.json", self.census)
        for inventory in (self.before_inventory, self.after_inventory):
            inventory["census_ref"] = summary.reference(self.run / "census.json")
            inventory["repositories"].append({"full_name": repo["full_name"], "entries": [], "failure_type": "no_main"})
        self.save_inventories(); self.create_locks_and_checks()
        self.write_json(self.run / "setups/synthetic__no-main/setup.json", {"status": "setup_failure", "failure_types": ["clone_failure"], "manual_intervention_count": 0, "zkfuzz_invocations": 0, "steps": [{"phase": "clone", "status": "failure", "failure_type": "clone_failure"}]})
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["repositories"], 2)
        self.assertEqual(report["overall"]["main_eligibility"]["unknown"], 1)
        self.assertEqual(report["overall"]["repositories_without_after_entrypoints"], 1)
        missing = next(row for row in report["repositories"] if row["full_name"] == "synthetic/no-main")
        availability = missing["entrypoint_availability"]
        self.assertEqual(availability["status"], "no_known_entrypoint")
        self.assertEqual(availability["known_before_count"], 0)
        self.assertEqual(availability["known_after_count"], 0)
        self.assertFalse(availability["source_absence_established"])
        for stage in ("compile", "preparation"):
            self.assertEqual(availability[stage]["status"], "not_started")
            self.assertEqual(availability[stage]["reason_code"], "no_known_entrypoint")
        self.assertEqual(missing["entries"], [])
        self.assertEqual(missing["inventory_failures"]["after"]["failure_type"], "no_main")
        self.assertEqual(report["overall"]["after_entrypoints"], 1)
        markdown = summary.render_markdown(report)
        self.assertIn("synthetic/no-main | no_known_entrypoint | 0/0 | not_started | not_started | no_known_entrypoint", markdown)
        self.assertIn("소스에 entrypoint가 없다는 증명은 아니다", markdown)

    def test_unavailable_after_inventory_is_not_a_confirmed_empty_inventory(self):
        self.after_inventory["repositories"] = []
        self.save_inventories()
        report = summary.summarize(self.run, allow_incomplete=True)
        availability = report["repositories"][0]["entrypoint_availability"]
        self.assertEqual(availability["status"], "inventory_unknown")
        self.assertIsNone(availability["known_after_count"])
        self.assertEqual(availability["compile"]["status"], "unknown")
        self.assertEqual(availability["compile"]["reason_code"], "inventory_unknown")

    def test_old_team_repository_measured_but_separate_from_main_cohort(self):
        self.census["repositories"][0]["main_eligible"] = False
        self.write_json(self.run / "census.json", self.census)
        for inventory in (self.before_inventory, self.after_inventory):
            inventory["census_ref"] = summary.reference(self.run / "census.json")
        self.save_inventories(); self.create_locks_and_checks()
        report = summary.summarize(self.run)
        self.assertEqual(report["main_eligible_cohort"]["repositories"], 0)
        self.assertEqual(report["team_curated_cohort"]["after_entrypoints"], 1)

    def test_source_overlap_is_not_used_as_total_repository_count(self):
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["repositories"], 1)
        self.assertEqual(sum(row["repositories"] for row in report["by_source"].values()), 2)

    def test_large_production_failures_and_partial_reasons_are_listed(self):
        report = summary.summarize(self.run)
        row = report["production_large_entrypoints"][0]
        self.assertEqual(row["constraints"], 150000)
        self.assertEqual(row["preparation_status"], "partial")
        self.assertEqual(row["failure_types"], ["wrapper_compile_failed"])
        self.assertEqual(row["path_roles"], ["unclassified"])

    def test_preparation_failure_type_cannot_remain_empty(self):
        path = self.result_path("after")
        result = json.loads(path.read_text()); result["preparation"]["failure_type"] = None
        self.write_json(path, result)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_tampered_check_log_blocks_finalization(self):
        (self.run / "checks/0.log").write_text("changed")
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_failed_executed_check_is_reported_and_does_not_hide_measurements(self):
        path = self.run / "checks/checks.json"; data = json.loads(path.read_text())
        data["commands"][2]["exit_code"] = 1; self.write_json(path, data)
        report = summary.summarize(self.run)
        self.assertEqual(report["checks"]["status"], "checks_failed")
        self.assertEqual(report["status"], "checks_failed")
        self.assertEqual(report["measurement_status"], "complete")
        self.assertEqual(report["checks"]["failed_commands"], [["cargo", "test"]])
        self.assertEqual(report["overall"]["after_entrypoints"], 1)
        with self.assertRaises(ValueError):
            summary.write_outputs(report, self.run / "results")
        self.assertIn("checks_failed", summary.render_markdown(report))

    def test_failed_readonly_format_check_is_not_claimed_as_formatter_success(self):
        path = self.run / "checks/checks.json"; data = json.loads(path.read_text())
        data["commands"][0].update(command=["cargo", "fmt", "--check"], exit_code=1)
        self.write_json(path, data)
        report = summary.summarize(self.run)
        self.assertEqual(report["checks"]["status"], "checks_failed")
        self.assertEqual(report["checks"]["formatter_invocation"], "cargo fmt --check (read-only verification)")
        self.assertEqual(report["checks"]["failed_commands"], [["cargo", "fmt", "--check"]])

    def test_unknown_exit_code_is_not_proof_that_required_check_ran(self):
        path = self.run / "checks/checks.json"; data = json.loads(path.read_text())
        data["commands"][2]["exit_code"] = None; self.write_json(path, data)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_missing_required_flags_are_not_the_required_clippy_check(self):
        path = self.run / "checks/checks.json"; data = json.loads(path.read_text())
        data["commands"][1]["command"] = ["cargo", "clippy"]
        self.write_json(path, data)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_raw_source_diagnostic_and_arbitrary_metadata_are_not_exported(self):
        path = self.result_path("after"); data = json.loads(path.read_text())
        data["preparation"]["reason"] = "private raw compiler diagnostic"
        data["candidate"] = {"must": "never appear"}; self.write_json(path, data)
        report = summary.summarize(self.run)
        text = json.dumps(report)
        self.assertNotIn("private raw compiler diagnostic", text)
        self.assertNotIn("must not appear", text)
        self.assertNotIn("never appear", text)
        self.assertIn("Synthetic protocol circuits.", text)

    def test_existing_outputs_are_preserved(self):
        report = summary.summarize(self.run)
        prefix = self.run / "results"
        prefix.with_suffix(".md").write_text("previous fixed report\n")
        before = (self.run / "results.md").read_bytes()
        with self.assertRaises(FileExistsError):
            summary.write_outputs(report, prefix)
        self.assertEqual((self.run / "results.md").read_bytes(), before)

    def add_final_selection(self):
        self.repo["clone_path"] = "/synthetic/current-checkout"
        self.write_json(self.run / "census.json", self.census)
        for inventory in (self.before_inventory, self.after_inventory):
            inventory["census_ref"] = summary.reference(self.run / "census.json")
        self.save_inventories(); self.create_locks_and_checks()
        active_inventory = deepcopy(self.after_inventory)
        active_inventory["repositories"][0]["entries"][0]["path"] = "/synthetic/current-checkout/circuits/main.circom"
        self.write_json(self.run / "entrypoints-after.v4.json", active_inventory)
        original = self.result_path("after")
        active = original.parent.parent / "after-v4/result.json"
        self.write_json(active, json.loads(original.read_text()))
        historical = json.loads(original.read_text())
        for stage in ("compile", "discovery", "preparation", "plan"):
            historical[stage].update(status="not_started", failure_type="entrypoint_outside_pinned_project", elapsed_seconds=0.0)
        self.write_json(original, historical)
        interruption = self.run / "after-controller-interruption.v3.json"
        self.write_json(interruption, {"reason": "synthetic old checkout path", "completed_after_records": 1, "zkfuzz_executions": 0})
        implementation = self.run / "synthetic_v4.py"
        implementation.write_text("# Metadata fixture, never executed.\n")
        compiler = self.run / "synthetic-circom"
        compiler.write_text("not an executable\n")
        invocation = self.run / "compiler-version-invocation.json"
        self.write_json(invocation, {"status": "success", "exit_code": 0})
        controls = self.run / "path-controls.json"
        self.write_json(controls, {"status": "passed", "zkfuzz_executions": 0, "witness_executions": 0, "corpus_executions": 0,
            "original_path_guard": {"status": "not_started", "failure_type": "entrypoint_outside_pinned_project", "process_started": False},
            "rebased_compile": {"status": "success", "constraints": 1, "source_sha256": "2" * 64},
            "compiler": {"ref": summary.reference(compiler), "version": "2.2.3", "version_invocation": summary.reference(invocation)},
            "implementation": summary.reference(implementation), "control_script": summary.reference(implementation),
            "raw_refs": [{"path": "/never-opened/control/main.circom", "sha256": "2" * 64}]})
        selection = {"schema_version": 4, "fixed_at": "2000-01-01T00:00:00+00:00", "active_after_directory": "after-v4", "all_after_entries_remeasured": True,
                     "zkfuzz_executions": 0, "workers": 2,
                     "census_ref": summary.reference(self.run / "census.json"),
                     "before_inventory_ref": summary.reference(self.run / "entrypoints-before.json"),
                     "after_inventory_ref": summary.reference(self.run / "entrypoints-after.v4.json"),
                     "prior_after_inventory_ref": summary.reference(self.run / "entrypoints-after.json"),
                     "prior_after_interruption_ref": summary.reference(interruption),
                     "path_controls_ref": summary.reference(controls),
                     "implementations": [summary.reference(implementation)],
                     "setup_records": [summary.reference(self.run / "setups/synthetic__service/setup.json")],
                     "prior_after_records": [summary.reference(original)], "prior_incomplete_after_paths": []}
        self.write_json(self.run / "final-measurement-selection.v4.json", selection)
        self.write_json(self.run / "setups/synthetic__service/post-install-lockfiles.json", {
            "setup_ref": summary.reference(self.run / "setups/synthetic__service/setup.json"), "plans": []})
        recovery_tools = self.run / "tools"
        actual_tools = self.run / "actual-c02-tools"
        recovery_tools.mkdir(exist_ok=True); actual_tools.mkdir(exist_ok=True)
        for name, content in (("circom", "synthetic-circom\n"), ("zkfDO", "synthetic-zkfdo\n")):
            (recovery_tools / name).write_text(content); (actual_tools / name).write_text(content)
        measurement_lock = json.loads((self.run / "measurement-lock.json").read_text())
        measurement_lock["compiler_tools"] = [summary.reference(recovery_tools / name) for name in ("circom", "zkfDO")]
        self.write_json(self.run / "measurement-lock.json", measurement_lock)
        refs = {"recovery_circom": summary.reference(recovery_tools / "circom"),
                "recovery_zkfdo": summary.reference(recovery_tools / "zkfDO"),
                "actual_circom": summary.reference(actual_tools / "circom"),
                "actual_zkfdo": summary.reference(actual_tools / "zkfDO")}
        stages = {stage: {"expected_invocations": 0, "observed_invocations": 0,
                          "not_invoked_by_stage_flow": 1, "missing_expected_invocations": 0,
                          "unexpected_invocations": 0, "data_path_validated_invocations": 0,
                          "status": "passed"}
                  for stage in ("compile", "discover", "prepare", "plan")}
        policy = {"compile_executable": str(recovery_tools / "circom"),
                  "structural_executable": str(actual_tools / "zkfDO"),
                  "structural_circom_argument": str(actual_tools / "circom"),
                  "recovery_zkfdo_pin_not_used_by_structural_calls": str(recovery_tools / "zkfDO"),
                  "cause": "synthetic base.legacy.RUN path split",
                  "path_divergence_status": "distinct_paths_with_sha256_equivalent_bytes",
                  "forbidden_nonexecuted_tool_arguments": {
                      "zkfuzz": "/nonexistent/c02-zkfuzz-forbidden",
                      "circomspect": "/nonexistent/c02-analyzer-forbidden"}}
        equivalence = {"circom": {"recovery_pin": refs["recovery_circom"],
                                   "actual_c02_alias": refs["actual_circom"], "sha256_equal": True},
                       "zkfDO": {"recovery_pin": refs["recovery_zkfdo"],
                                 "actual_c02_alias": refs["actual_zkfdo"], "sha256_equal": True}}
        c02_lock = self.run / "tool-lock.json"
        c02_pins = {name: {"path": str(actual_tools / name), "sha256": refs["actual_" +
                    ("zkfdo" if name == "zkfDO" else name)]["sha256"]} for name in ("circom", "zkfDO")}
        self.write_json(c02_lock, {"tools": list(c02_pins.values()), "zkfuzz_executions": 0})
        self.write_json(self.run / "actual-tool-provenance.v4.json", {
            "schema_version": 1, "task": "C-03 actual tool provenance", "status": "passed",
            "generated_at": "2026-10-02T00:00:00Z", "mismatches": [],
            "audit_scope": "synthetic metadata-only fixture",
            "selection_ref": summary.reference(self.run / "final-measurement-selection.v4.json"),
            "after_inventory_ref": summary.reference(self.run / "entrypoints-after.v4.json"),
            "measurement_lock_ref": summary.reference(self.run / "measurement-lock.json"),
            "census_ref": selection["census_ref"],
            "c02_tool_lock_ref": summary.reference(c02_lock),
            "implementation_ref": summary.reference(summary.ROOT / "scripts/audit_c03_tool_provenance.py"),
            "coverage": {"expected_results": 1, "audited_results": 1,
                         "unexpected_active_results": 0, "incomplete_active_results": 0, "stages": stages},
            "tool_path_policy": policy,
            "active_data_path_policy": {"status": "passed", "source_main": "synthetic",
                                        "config_generated": "synthetic", "outputs": "synthetic",
                                        "libraries": "synthetic", "verbs": "synthetic"},
            "tools": {"references": refs, "actual_alias_recovery_equivalence": equivalence,
                      "c02_tool_lock_pins": c02_pins,
                      "all_hashes_equivalent": True},
            "sentinel_absence": {"status": "passed", "checked_at": "2026-10-02T00:00:00Z",
                "paths": {"zkfuzz": {"path": "/nonexistent/c02-zkfuzz-forbidden", "exists": False,
                                       "lexists": False, "status": "absent"},
                          "circomspect": {"path": "/nonexistent/c02-analyzer-forbidden", "exists": False,
                                          "lexists": False, "status": "absent"}}},
            "result_records": [{"record": summary.reference(active)}], "call_records": []})
        self.refresh_final_checks()
        return selection, active

    def refresh_final_checks(self):
        path = self.run / "checks/checks.json"
        checks = json.loads(path.read_text())
        paths = [Path(summary.__file__), *sorted((summary.ROOT / "tests").glob("c03*_test.py")),
                 summary.ROOT / "scripts/audit_c03_tool_provenance.py",
                 self.run / "final-measurement-selection.v4.json", self.run / "entrypoints-after.v4.json",
                 self.run / "actual-tool-provenance.v4.json"]
        stamp = summary.datetime.now(summary.timezone.utc).isoformat()
        checks.update(schema_version=2, executed_at=stamp, source_refs=[summary.reference(item) for item in paths])
        for row in checks["commands"]:
            row.update(started_at=stamp, finished_at=stamp)
        self.write_json(path, checks)

    def test_final_selection_keeps_wrong_path_history_out_of_active_outcomes(self):
        selection, active = self.add_final_selection()
        report = summary.summarize(self.run)
        self.assertEqual(report["overall"]["after_compile_success"]["numerator"], 1)
        self.assertEqual(report["overall"]["after_compile_success"]["denominator"], 1)
        self.assertEqual(report["repositories"][0]["entries"][0]["after"]["record"], summary.reference(active))
        history = report["provenance"]["final_measurement_selection"]
        self.assertEqual(history["remeasured_entrypoints"], 1)
        self.assertEqual(history["prior_after_summary"]["compile_statuses"], {"not_started": 1})
        self.assertEqual(history["prior_after_summary"]["compile_failure_types"], {"entrypoint_outside_pinned_project": 1})
        self.assertEqual(history["prior_after_summary"]["stage_timings"]["compile"]["sum_seconds"], 0.0)
        self.assertEqual(history["reused_setup_records"], selection["setup_records"])
        text = summary.render_markdown(report)
        self.assertIn("위 결과표는 after-v4만 집계", text)
        self.assertIn("재설치하지 않았다", text)

    def test_final_preview_reports_missing_actual_tool_provenance(self):
        self.add_final_selection()
        (self.run / "actual-tool-provenance.v4.json").unlink()
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertIn("actual_tool_provenance_record_missing",
                      {row["code"] for row in report["validation_errors"]})
        with self.assertRaises(ValueError):
            summary.write_outputs(report, self.run / "final")

    def test_actual_tool_provenance_hash_links_and_path_divergence_are_reported(self):
        self.add_final_selection()
        report = summary.summarize(self.run)
        actual = report["provenance"]["actual_tool_provenance"]
        self.assertEqual(actual["status"], "verified")
        self.assertTrue(actual["tools"]["all_hashes_equivalent"])
        text = summary.render_markdown(report)
        self.assertIn("실제 실행 도구 경로 감사", text)
        self.assertIn("C-02 tool alias", text)
        self.assertIn("경로 동일성", text)
        self.assertIn("C-02 tool-lock", text)
        self.assertIn("zkFuzz 차단 sentinel 부재", text)

    def test_mutated_actual_alias_invalidates_provenance(self):
        self.add_final_selection()
        (self.run / "actual-c02-tools/zkfDO").write_text("mutated\n")
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertIn("reference_hash_mismatch", {row["code"] for row in report["validation_errors"]})

    def test_c02_tool_lock_cannot_repin_actual_alias(self):
        self.add_final_selection()
        lock_path = self.run / "tool-lock.json"
        lock = json.loads(lock_path.read_text()); lock["tools"][1]["sha256"] = "0" * 64
        self.write_json(lock_path, lock)
        provenance_path = self.run / "actual-tool-provenance.v4.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["c02_tool_lock_ref"] = summary.reference(lock_path)
        provenance["tools"]["c02_tool_lock_pins"]["zkfDO"]["sha256"] = "0" * 64
        self.write_json(provenance_path, provenance); self.refresh_final_checks()
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertIn("actual_tool_provenance_c02_tool_lock_actual_mismatch",
                      {row["code"] for row in report["validation_errors"]})

    def test_sentinel_presence_claim_cannot_be_published(self):
        self.add_final_selection()
        path = self.run / "actual-tool-provenance.v4.json"
        provenance = json.loads(path.read_text())
        provenance["sentinel_absence"]["paths"]["zkfuzz"].update(exists=True, status="present")
        self.write_json(path, provenance); self.refresh_final_checks()
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertIn("actual_tool_provenance_sentinel_absence_invalid",
                      {row["code"] for row in report["validation_errors"]})

    def test_actual_tool_provenance_hash_index_cannot_drop_active_result(self):
        self.add_final_selection()
        path = self.run / "actual-tool-provenance.v4.json"
        provenance = json.loads(path.read_text()); provenance["result_records"] = []
        self.write_json(path, provenance); self.refresh_final_checks()
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertIn("actual_tool_provenance_result_index_mismatch",
                      {row["code"] for row in report["validation_errors"]})

    def test_actual_tool_provenance_requires_passed_data_path_coverage(self):
        self.add_final_selection()
        path = self.run / "actual-tool-provenance.v4.json"
        provenance = json.loads(path.read_text())
        provenance["active_data_path_policy"]["status"] = "failed"
        provenance["coverage"]["stages"]["compile"]["data_path_validated_invocations"] = 1
        self.write_json(path, provenance); self.refresh_final_checks()
        report = summary.summarize(self.run, allow_incomplete=True)
        codes = {row["code"] for row in report["validation_errors"]}
        self.assertIn("actual_tool_provenance_active_data_path_policy_invalid", codes)
        self.assertIn("actual_tool_provenance_stage_coverage_mismatch", codes)

    def test_missing_final_after_record_does_not_fall_back_to_prior_result(self):
        _, active = self.add_final_selection()
        active.unlink()
        with self.assertRaises(ValueError):
            summary.summarize(self.run)
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertEqual(report["overall"]["after_compile_statuses"], {"missing": 1})
        self.assertEqual(report["overall"]["after_entrypoints"], 1)
        self.assertEqual(report["provenance"]["final_measurement_selection"]["prior_after_summary"]["recorded_entrypoints"], 1)

    def test_unindexed_prior_after_result_blocks_selection(self):
        selection, _ = self.add_final_selection()
        selection["prior_after_records"] = []
        self.write_json(self.run / "final-measurement-selection.v4.json", selection)
        report = summary.summarize(self.run, allow_incomplete=True)
        codes = {row["code"] for row in report["validation_errors"]}
        self.assertIn("final_selection_prior_record_index_incomplete", codes)
        self.assertIn("unexpected_measurement_record", codes)

    def test_selection_cannot_drop_after_entrypoints_or_change_source_identity(self):
        selection, _ = self.add_final_selection()
        path = self.run / "entrypoints-after.v4.json"
        inventory = json.loads(path.read_text())
        for mutate, expected in ((lambda item: item["repositories"][0]["entries"].clear(), "final_selection_after_denominator_changed"),
                                 (lambda item: item["repositories"][0]["entries"][0].update(expected_sha256="9" * 64), "final_selection_entry_identity_changed"),
                                 (lambda item: item["repositories"][0]["entries"][0].update(path="/old/checkout/main.circom"), "final_selection_source_rebase_mismatch")):
            with self.subTest(expected=expected):
                changed = deepcopy(inventory); mutate(changed)
                self.write_json(path, changed)
                selection["after_inventory_ref"] = summary.reference(path)
                self.write_json(self.run / "final-measurement-selection.v4.json", selection)
                report = summary.summarize(self.run, allow_incomplete=True)
                self.assertIn(expected, {row["code"] for row in report["validation_errors"]})

    def test_selection_requires_all_reused_setup_references(self):
        selection, _ = self.add_final_selection()
        selection["setup_records"] = []
        self.write_json(self.run / "final-measurement-selection.v4.json", selection)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_mutated_historical_result_is_not_accepted_as_frozen_history(self):
        self.add_final_selection()
        original = self.result_path("after")
        data = json.loads(original.read_text()); data["compile"]["elapsed_seconds"] = 99.0
        self.write_json(original, data)
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def test_path_control_must_show_old_path_guard_and_real_compile_success(self):
        selection, _ = self.add_final_selection()
        path = self.run / "path-controls.json"
        original = json.loads(path.read_text())
        for field, value in (("original_path_guard", {"status": "success", "process_started": True}),
                             ("rebased_compile", {"status": "not_started", "constraints": 1, "source_sha256": "2" * 64}),
                             ("corpus_executions", 1)):
            with self.subTest(field=field):
                changed = deepcopy(original); changed[field] = value
                self.write_json(path, changed)
                selection["path_controls_ref"] = summary.reference(path)
                self.write_json(self.run / "final-measurement-selection.v4.json", selection)
                report = summary.summarize(self.run, allow_incomplete=True)
                self.assertIn("final_selection_path_controls_not_passed", {row["code"] for row in report["validation_errors"]})

    def test_legacy_or_failed_checks_can_be_previewed_but_never_finalized(self):
        legacy = summary.summarize(self.run)
        with self.assertRaises(ValueError):
            summary.write_outputs(legacy, self.run / "final")
        self.add_final_selection()
        path = self.run / "checks/checks.json"
        checks = json.loads(path.read_text()); checks["commands"][2]["exit_code"] = 1
        self.write_json(path, checks)
        report = summary.summarize(self.run)
        self.assertEqual(report["checks"]["status"], "checks_failed")
        with self.assertRaises(ValueError):
            summary.write_outputs(report, self.run / "final")
        self.assertFalse((self.run / "final.json").exists())

    def test_final_selection_requires_version_four(self):
        selection, _ = self.add_final_selection()
        selection["schema_version"] = 3
        self.write_json(self.run / "final-measurement-selection.v4.json", selection)
        self.refresh_final_checks()
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertIn("final_selection_policy_mismatch", {row["code"] for row in report["validation_errors"]})

    def test_final_checks_require_current_implementation_and_all_test_hashes(self):
        self.add_final_selection()
        path = self.run / "checks/checks.json"
        checks = json.loads(path.read_text())
        checks["source_refs"] = [ref for ref in checks["source_refs"] if Path(ref["path"]).name != "c03_summary_test.py"]
        self.write_json(path, checks)
        report = summary.summarize(self.run, allow_incomplete=True)
        self.assertIn("check_current_source_reference_missing", {row["code"] for row in report["validation_errors"]})

    def test_checks_before_last_result_are_stale_even_with_passing_logs(self):
        self.add_final_selection()
        path = self.run / "checks/checks.json"
        checks = json.loads(path.read_text())
        checks["executed_at"] = "2001-01-01T00:00:00+00:00"
        for row in checks["commands"]:
            row.update(started_at=checks["executed_at"], finished_at=checks["executed_at"])
        self.write_json(path, checks)
        report = summary.summarize(self.run, allow_incomplete=True)
        codes = {row["code"] for row in report["validation_errors"]}
        self.assertIn("checks_not_fresh_after_active_results", codes)
        self.assertIn("check_command_not_fresh_after_active_results", codes)

    def test_finalization_reference_can_supply_the_source_pins(self):
        self.add_final_selection()
        path = self.run / "checks/checks.json"
        checks = json.loads(path.read_text())
        manifest = self.run / "finalization.json"
        self.write_json(manifest, {"source_refs": checks.pop("source_refs")})
        checks["finalization_ref"] = summary.reference(manifest)
        self.write_json(path, checks)
        self.assertEqual(summary.summarize(self.run)["checks"]["freshness"]["status"], "verified")

    def test_generated_lockfile_references_are_audited_not_only_setup_records(self):
        self.add_final_selection()
        lock = self.run / "generated-package-lock.json"
        self.write_json(lock, {"lockfileVersion": 3})
        manifest = self.run / "setups/synthetic__service/post-install-lockfiles.json"
        self.write_json(manifest, {"setup_ref": summary.reference(self.run / "setups/synthetic__service/setup.json"),
            "plans": [{"install_root": "synthetic", "original_lockfile_present": False, "resulting_lockfiles": [summary.reference(lock)]}]})
        report = summary.summarize(self.run)
        self.assertEqual(report["post_install_lockfiles"]["resulting_lockfiles"], 1)
        self.assertEqual(report["post_install_lockfiles"]["generated_lockfiles"], 1)
        self.write_json(lock, {"lockfileVersion": 99})
        with self.assertRaises(ValueError):
            summary.summarize(self.run)

    def census_source_fixture(self):
        rows = [{"full_name": f"synthetic/repository-{i}", "canonical_full_name": f"synthetic/repository-{i}", "commit_sha": f"{i:040x}",
                 "c02_included": i < 65, "team_curated": i < 14, "source_memberships": ["team_curated"] if i < 14 else [], "team_rows": []} for i in range(80)]
        c02_rows = [{**row, "inclusion": {"status": "included"}} for row in rows[:65]]
        c02_rows[0]["full_name"] = "historical/renamed-repository"
        c02 = self.run / "c02_corpus_results_2026-10-02.json"
        self.write_json(c02, {"repositories": c02_rows})
        csv_path = self.run / "team.csv"
        fields = ("repository_url_declared", "circuit_folders_declared", "usage_evidence_declared", "circom_version_declared", "discovery_source_declared")
        teams, raw = [], []
        for i, repo in enumerate(rows[:14]):
            values = ["https://github.com/" + repo["full_name"], "circuits", "Synthetic service", "2.2.3", "Synthetic source"]
            row = {"sheet_item": i + 1, "repository_key": repo["full_name"], "field_source_lines": {}, **dict(zip(fields, values))}
            for field, value in zip(fields, values):
                raw.append([field, " " + value if i == 9 and field == "usage_evidence_declared" else value])
                row["field_source_lines"][field] = len(raw)
            teams.append(row)
        with csv_path.open("w", newline="") as stream:
            csv.writer(stream).writerows(raw)
        for repo, team in zip(rows, teams):
            team["source"] = summary.reference(csv_path); repo["team_rows"] = [team]
        team_metadata = self.run / "team-metadata.json"
        self.write_json(team_metadata, {"source": summary.reference(csv_path), "rows": teams})
        selection = self.run / "source-selection.json"
        self.write_json(selection, {"repository_count": 80, "c02_included_count": 65, "team_row_count": 14, "repositories": rows})
        census = {"repository_count": 80, "repositories": rows, "selection": summary.reference(selection), "team_sheet_metadata": summary.reference(team_metadata)}
        locks = {"procedure-lock.json": {"c02_baseline": {"record": summary.reference(c02)}}}
        return census, locks

    def test_frozen_source_denominators_accept_recorded_rename_and_explain_csv_whitespace(self):
        census, locks = self.census_source_fixture()
        audit = summary.Audit()
        result = summary._check_census_sources(census, locks, audit)
        self.assertEqual(audit.errors, [])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["C02_included_identities"], 65)
        self.assertEqual(len(result["C02_aliases"]), 1)
        self.assertEqual(result["csv_whitespace_normalizations"][0]["sheet_item"], 10)

    def test_equal_counts_cannot_hide_replaced_C02_identity_or_missing_team_row(self):
        census, locks = self.census_source_fixture()
        census["repositories"][20]["commit_sha"] = "f" * 40
        census["repositories"][2]["team_rows"] = []
        audit = summary.Audit()
        summary._check_census_sources(census, locks, audit)
        codes = {row["code"] for row in audit.errors}
        self.assertIn("census_C02_included_identity_mismatch", codes)
        self.assertIn("census_team_rows_changed", codes)

    def test_markdown_has_conditioned_paired_tables_and_unknown_all_attempt_cost(self):
        report = summary.summarize(self.run)
        text = summary.render_markdown(report)
        self.assertIn("| 출처(중복) | 저장소 | 설치 후 entrypoint | paired 전 성공 | paired 후 성공 |", text)
        self.assertIn("| C-02 과거 | 의존성 무설치", text)
        self.assertIn("모든 시도를 합한 총비용은 unknown", text)

    def test_timing_unknown_is_not_zero_measurement(self):
        path = self.result_path("before"); data = json.loads(path.read_text())
        data["compile"]["elapsed_seconds"] = None; self.write_json(path, data)
        timing = summary.summarize(self.run)["overall"]["timings"]["compile_before"]
        self.assertEqual(timing["known_count"], 0)
        self.assertEqual(timing["unknown_count"], 1)


if __name__ == "__main__":
    unittest.main()
