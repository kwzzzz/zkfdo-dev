#!/usr/bin/env python3
"""Source-only filter tests; no compiler, fuzzer or J processes."""
import copy
import json
import platform
from pathlib import Path
import shutil
import tempfile
import sys
import types
import unittest
from unittest.mock import patch

import prepare_targets_v2 as preparation


class WrapperFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zkfdo-wrapper-filter-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def target(self, source, name="IsZero"):
        project = self.root / "project.circom"
        project.write_text(source)
        wrapper = self.root / "wrapper.circom"
        wrapper.write_text(f'include "{project}";\ncomponent main = {name}();\n')
        snapshot = self.root / "snapshot"
        snapshot.mkdir(exist_ok=True)
        for path in (project, wrapper):
            shutil.copyfile(path, snapshot / path.name)
        definitions = preparation.definitions(project, source)
        scopes = [{"path": str(project), "template_name": row["name"], "start_line": row["start_line"], "end_line": row["end_line"]}
                  for row in definitions if row["kind"] == "template"]
        root = {"path": str(project), "template_name": name, "concrete_parameters": []}
        return {"target_id": "target-1", "definition": {"template_name": name, "concrete_parameters": []},
                "run_entrypoint": str(snapshot / wrapper.name),
                "inspection": {"complete": True, "unsupported": [], "root": root, "instances": [root],
                               "scopes": scopes, "dependency_paths": [str(project), str(wrapper)]},
                "source_fingerprints": [{"path": str(path), "sha256": preparation.sha(path)} for path in (project, wrapper)],
                "snapshot_fingerprints": [{"path": str(snapshot / path.name), "sha256": preparation.sha(snapshot / path.name)} for path in (project, wrapper)]}

    def test_whitelisted_hint_is_eligible(self):
        target = self.target("template IsZero() { signal output out; out <-- 0; }\n")
        row = preparation.classify_target(target)
        self.assertTrue(row["eligible_for_skip"], row)
        self.assertEqual(row["hint_site_count"], 1)

    def test_transitive_whitelisted_hints_keep_less_than_oracle_risk(self):
        source = """template AssertBit() { signal input in; in * (in - 1) === 0; }
template Num2Bits(n) { assert(n < 254); signal input in; signal output out[n];
for (var i = 0; i < n; i++) { out[i] <-- (in >> i) & 1; AssertBit()(out[i]); } }
template LessThan(n) { signal input in[2]; signal output out; component b = Num2Bits(n+1); out <== b.out[n]; }
"""
        row = preparation.classify_target(self.target(source, "LessThan"))
        self.assertTrue(row["eligible_for_skip"], row)
        self.assertTrue(row["less_than_oracle_present"])
        self.assertEqual(row["hint_sites"][0]["template"], "Num2Bits")
        self.assertTrue(row["assertion_sites"])

    def test_non_whitelisted_transitive_hint_keeps_target(self):
        source = "template Unsafe() { signal output out; out <-- 1; }\ntemplate IsZero() { component c = Unsafe(); }\n"
        row = preparation.classify_target(self.target(source))
        self.assertFalse(row["eligible_for_skip"])
        self.assertEqual(row["reason"], "non_whitelisted_hint_site")

    def test_no_hint_vacuity_is_rejected(self):
        target = self.target("template IsZero() { signal output out; out <== 0; }\n")
        row = preparation.classify_target(target)
        self.assertFalse(row["eligible_for_skip"])
        self.assertEqual(row["reason"], "no_hint_sites")

    def test_comments_and_escaped_strings_are_not_hint_sites(self):
        source = '/* <-- fake(); */\ntemplate IsZero() { log("escaped \\\" <-- fake()"); // -->\n signal output out; out <== 0; }\n'
        row = preparation.classify_target(self.target(source))
        self.assertEqual(row["reason"], "no_hint_sites", row)

    def test_function_rhs_hint_remains_mutable_even_in_whitelist(self):
        source = "function f(a) { return a; }\ntemplate IsZero() { signal output out; out <-- f(1); }\n"
        row = preparation.classify_target(self.target(source))
        self.assertFalse(row["eligible_for_skip"])
        self.assertIn("hint_rhs", row["uncertainty"])

    def test_unresolved_call_keeps_target(self):
        source = "template IsZero() { signal output out; out <-- 0; component c = Missing(); }\n"
        row = preparation.classify_target(self.target(source))
        self.assertFalse(row["eligible_for_skip"])
        self.assertIn("unresolved_call", row["uncertainty"])

    def test_unused_definition_does_not_enter_call_closure(self):
        source = "template Unsafe() { signal output out; out <-- 1; }\ntemplate IsZero() { signal output out; out <-- 0; }\n"
        row = preparation.classify_target(self.target(source))
        self.assertTrue(row["eligible_for_skip"], row)
        self.assertEqual([item["name"] for item in row["visited_definitions"]], ["IsZero"])

    def test_naive_mutator_does_not_use_whitelist_rule(self):
        target = self.target("template IsZero() { signal output out; out <-- 0; }\n")
        row = preparation.classify_target(target, trace_mutation_method="naive")
        self.assertFalse(row["eligible_for_skip"])
        self.assertEqual(row["uncertainty"], "unsupported_mutation_configuration")

    def test_modified_source_or_snapshot_is_kept(self):
        target = self.target("template IsZero() { signal output out; out <-- 0; }\n")
        Path(target["snapshot_fingerprints"][0]["path"]).write_text("changed")
        row = preparation.classify_target(target)
        self.assertFalse(row["eligible_for_skip"])
        self.assertEqual(row["uncertainty"], "source_changed_after_preparation")

    def test_incomplete_inspection_and_wrong_scope_are_kept(self):
        target = self.target("template IsZero() { signal output out; out <-- 0; }\n")
        bad = copy.deepcopy(target)
        bad["inspection"]["complete"] = False
        self.assertFalse(preparation.classify_target(bad)["eligible_for_skip"])
        target["inspection"]["scopes"][0]["end_line"] += 1
        self.assertEqual(preparation.classify_target(target)["uncertainty"], "prepared_scope_mismatch")

    def test_right_arrow_hints_and_function_rhs_are_recognized(self):
        target = self.target("template IsZero() { signal output out; 0 --> out; }\n")
        self.assertTrue(preparation.classify_target(target)["eligible_for_skip"])
        target = self.target("function f(x) { return x; }\ntemplate IsZero() { signal output out; f(0) --> out; }\n")
        self.assertFalse(preparation.classify_target(target)["eligible_for_skip"])

    def test_default_off_preserves_targets_and_frozen_input(self):
        target = self.target("template IsZero() { signal output out; out <-- 0; }\n")
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"schema_version": 1, "targets": [target]}))
        before = plan.read_bytes()
        report = preparation.prepare_plan(plan, self.root / "off")
        self.assertFalse(report["enabled"])
        self.assertEqual(report["kept_target_count"], 1)
        enabled = preparation.prepare_plan(plan, self.root / "on", skip_unmutable_wrappers=True)
        self.assertEqual(enabled["kept_target_count"], 0)
        self.assertTrue(enabled["coverage_changed"])
        self.assertFalse(enabled["preparation_savings_claimed"])
        self.assertEqual(plan.read_bytes(), before)

    def test_duplicate_or_recursive_definition_is_kept(self):
        target = self.target("template IsZero() { signal output out; out <-- 0; }\ntemplate IsZero() { }\n")
        self.assertFalse(preparation.classify_target(target)["eligible_for_skip"])
        target = self.target("template IsZero() { signal output out; out <-- 0; component child = IsZero(); }\n")
        self.assertEqual(preparation.classify_target(target)["uncertainty"], "recursive_call_closure")

    def test_wrapper_main_is_bound_to_the_inspected_template(self):
        source = "template IsZero() { signal output out; out <-- 0; }\ntemplate Unsafe() { signal output out; out <-- 1; }\n"
        target = self.target(source)
        wrapper = Path(target["run_entrypoint"])
        original = Path(target["source_fingerprints"][1]["path"])
        text = wrapper.read_text().replace("main = IsZero()", "main = Unsafe()")
        for path, fingerprints in ((wrapper, target["snapshot_fingerprints"]), (original, target["source_fingerprints"])):
            path.write_text(text)
            next(row for row in fingerprints if row["path"] == str(path))["sha256"] = preparation.sha(path)
        row = preparation.classify_target(target)
        self.assertFalse(row["eligible_for_skip"])
        self.assertEqual(row["uncertainty"], "wrapper_main_differs_from_inspected_root")

    def test_duplicate_target_id_cannot_remove_a_different_row(self):
        target = self.target("template IsZero() { signal output out; out <-- 0; }\n")
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"targets": [target, copy.deepcopy(target)]}))
        with self.assertRaisesRegex(ValueError, "unique"):
            preparation.prepare_plan(plan, self.root / "out", skip_unmutable_wrappers=True)

    def test_campaign_id_cannot_rebind_another_executable(self):
        target = self.target("template IsZero() { signal output out; out <-- 0; }\n")
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"targets": [target]}))
        spec = self.root / "spec.json"
        spec.write_text(json.dumps({"targets": [{"target_id": "target-1", "source_snapshot_id": "source",
            "entrypoint_relative": "project.circom", "entrypoint_sha256": preparation.sha(self.root / "project.circom")}],
            "source_snapshots": [{"id": "source", "path": str(self.root / "snapshot")}]}))
        with self.assertRaisesRegex(ValueError, "executable wrapper differs"):
            preparation.prepare_plan(plan, self.root / "out", skip_unmutable_wrappers=True, campaign_spec=spec)

    def test_portable_manifest_filter_updates_plan_pin_and_passes_v5_plan_validation(self):
        import run_policy_a_engine_v5 as runner
        import zkfdo_tools_v1 as tools
        source = "template IsZero() { signal output out; out <-- 0; }\ntemplate NoHint() { signal output out; out <== 0; }\n"
        first = self.target(source)
        second = copy.deepcopy(first)
        second["target_id"] = "target-2"
        second["definition"].update(template_name="NoHint", project_root=str(self.root), entrypoint=str(self.root / "nohint.circom"))
        first["definition"].update(project_root=str(self.root), entrypoint=str(self.root / "wrapper.circom"))
        second["inspection"]["root"]["template_name"] = "NoHint"
        second["inspection"]["instances"] = [second["inspection"]["root"]]
        original = self.root / "nohint.circom"
        original.write_text(f'include "{self.root / "project.circom"}";\ncomponent main = NoHint();\n')
        snapshot = self.root / "snapshot"
        shutil.copyfile(original, snapshot / original.name)
        second["run_entrypoint"] = str(snapshot / original.name)
        second["inspection"]["dependency_paths"] = [str(self.root / "project.circom"), str(original)]
        second["source_fingerprints"][1] = {"path": str(original), "sha256": preparation.sha(original)}
        second["snapshot_fingerprints"][1] = {"path": str(snapshot / original.name), "sha256": preparation.sha(snapshot / original.name)}
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"schema_version": 1, "targets": [first, second]}))
        spec = {"method": "split", "initial_seed": 123, "seed_transport": {"kind": "mutation_settings", "argument": "--path_to_mutation_setting", "base": {}},
                "source_snapshots": [{"id": "source", "path": str(snapshot)}],
                "pinned_files": [{"label": "plan", "path": str(plan), "sha256": preparation.sha(plan)}], "targets": []}
        for row in (second, first):
            spec["targets"].append({"target_id": row["target_id"], "source_snapshot_id": "source",
                "entrypoint_relative": Path(row["run_entrypoint"]).name,
                "entrypoint_sha256": preparation.sha(row["run_entrypoint"]),
                "command": ["{zkfuzz}", "{entrypoint}", "-l", "{workspace}"]})
        spec_path = self.root / "spec.json"
        spec_path.write_text(json.dumps(spec))
        manifest = self.root / "tools.json"
        binary_sha = preparation.sha(sys.executable)
        manifest.write_text(json.dumps({"schema": "zkfdo-tools-v1", "status": "ready", "platform": tools.platform_name(),
            "architecture": platform.machine(), "tools": {"zkfuzz": {"path": sys.executable, "sha256": binary_sha,
                "version": "synthetic-test", "source_commit": "synthetic", "build_command": "test-only"}}}))
        def resolve(argv, tool):
            return {"binary_sha256": tool["sha256"], "mutation_config": json.loads(Path(argv[-1]).read_text()),
                    "semantic_settings": {"whitelist": ["IsZero", "Num2Bits"], "search_mode": "ga"}}
        fake = types.SimpleNamespace(materialize_settings=lambda base, seed, tool: {"trace_mutation_method": "constant_operator", **base, "seed": seed},
                                     resolve_configuration=resolve)
        with patch.dict(sys.modules, {"zkfdo_zkfuzz_config_v1": fake}):
            report = preparation.prepare_plan(plan, self.root / "out", skip_unmutable_wrappers=True,
                                              campaign_spec=spec_path, tools_manifest=manifest)
        self.assertEqual(report["kept_target_count"], 1, report)
        filtered = json.loads((self.root / "out/campaign-spec.json").read_text())
        self.assertEqual([row["target_id"] for row in filtered["targets"]], ["target-2"])
        self.assertEqual(filtered["wrapper_filter"]["configuration_by_target"]["target-1"]["binary_sha256"], binary_sha)
        runner.legacy.verify_pins(filtered)
        checked = runner.legacy.verify_plan(filtered, {"source": snapshot})
        self.assertEqual(checked["status"], "verified")
        self.assertEqual(checked["target_count"], 1)


if __name__ == "__main__":
    unittest.main()
