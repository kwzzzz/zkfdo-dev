#!/usr/bin/env python3
"""Small synthetic fixtures for v5; no zkFuzz/Circom/J binaries are invoked."""
import json
from contextlib import contextmanager
from pathlib import Path
import signal
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import run_policy_a_engine_v5 as runner


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zkfdo-policy-a-v5-")
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "main.circom").write_text("pragma circom 2.0.0;\n")
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def spec(self, count=1, *, preflight=False):
        targets = [{"target_id": f"target-{i}", "source_snapshot_id": "source",
                    "entrypoint_relative": "main.circom",
                    "entrypoint_sha256": runner.legacy.sha256_file(self.source / "main.circom"),
                    "command": [sys.executable, "-c", "pass", "{entrypoint}", "{workspace}", "{seed}"]}
                   for i in range(count)]
        if preflight:
            for row in targets:
                row["preflight_compile_command"] = [sys.executable, "-c", "pass", "{entrypoint}", "{compile_output}"]
        return {"schema_version": 1, "method": "whole" if count == 1 else "split",
                "total_budget_seconds": 20, "attempt_cap_seconds": 2, "concurrency": 1,
                "initial_seed": 100, "seed_rule": "increment_per_pass",
                "seed_transport": {"kind": "placeholder"}, "require_pinned_command_tools": True,
                "require_save_output": False, "zkfuzz_output": "stderr_report",
                "pinned_files": [{"label": "python", "path": sys.executable,
                                  "sha256": runner.legacy.sha256_file(Path(sys.executable))}],
                "source_snapshots": [{"id": "source", "path": str(self.source),
                                     "tree_sha256": runner.legacy.tree_sha256(self.source),
                                     "expected_baseline_candidates": 0,
                                     "candidate_globs": ["*_counterexample.json"]}], "targets": targets}

    def fake_command(self, argv, output, seconds, **kwargs):
        self.calls.append((argv, seconds, kwargs))
        output.mkdir(parents=True)
        (output / "stdout.log").write_text("")
        (output / "stderr.log").write_text("")
        receipt = {"status": "completed", "returncode": 0, "cpu_seconds": 0.01,
                   "cleanup_seconds": 0.001, "cleanup_complete": True, "measurement_valid": True,
                   "invalid_reasons": [], "received_signals": [], "peak_process_tree_rss_bytes": 1000}
        runner.runtime.atomic_json(output / "receipt.json", receipt)
        return receipt

    def run_campaign(self, spec, **kwargs):
        return runner.run_campaign(spec, self.root / "run", max_disk_bytes=8 * 2**20,
                                   min_free_bytes=0, command_runner=self.fake_command, purpose="supervisor-test", **kwargs)

    def test_variable_split_targets_seed_passes_and_config_hooks(self):
        spec = self.spec(3)
        spec["seed_transport"] = {"kind": "mutation_settings", "argument": "--settings", "base": {"mutation_rate": .3}}
        configs = []
        def config(argv, tool):
            value = json.loads(Path(argv[-1]).read_text())
            configs.append(value)
            return {"mutation_rate": value["mutation_rate"], "tool": tool["sha256"]}
        result = self.run_campaign(spec, max_attempts=4, configuration_hook=config,
                                   reference_configuration={"mutation_rate": .3},
                                   comparison_hook=lambda reference, actual: {"equal": reference["mutation_rate"] == actual["mutation_rate"]})
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual([row["seed"] for row in result["attempts"]], [100, 100, 100, 101])
        self.assertEqual(len(configs), 4)
        self.assertEqual(len(result["configuration_comparisons"]), 4)
        self.assertIsNone(result["max_tree_rss_bytes"])
        self.assertTrue(result["measurement_valid"])
        self.assertEqual(len(list((self.root / "run/attempts").glob("*/ledger.json"))), 4)

    def test_legacy_physical_memory_cap_needs_explicit_migration(self):
        spec = self.spec()
        spec["memory_cap_bytes"] = 10 * 2**30
        result = self.run_campaign(spec)
        self.assertEqual(result["status"], "failed")
        self.assertIn("physical footprint", result["error"])
        self.assertEqual(self.calls, [])

    def test_configuration_mismatch_stops_before_fuzzer(self):
        result = self.run_campaign(self.spec(), configuration_hook=lambda argv, tool: {"x": 2},
                reference_configuration={"x": 1}, comparison_hook=lambda a, b: {"equal": False, "diff": ["x"]})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(result["configuration_comparisons"][0]["diff"], ["x"])
        self.assertTrue(json.loads((self.root / "run/attempts/000000/ledger.json").read_text())["complete"])

    def test_preflight_failure_preserves_command_and_task_receipts(self):
        fake = self.fake_command
        def fail(*args, **kwargs):
            receipt = fake(*args, **kwargs)
            receipt.update(status="command_failed", returncode=7)
            return receipt
        self.fake_command = fail
        result = self.run_campaign(self.spec(preflight=True))
        self.assertEqual(result["termination_reason"], "preflight_failed")
        self.assertEqual(len(result["commands"]), 1)
        self.assertEqual(result["commands"][0]["stage"], "preflight_compile")
        self.assertEqual(result["attempts"], [])
        self.assertTrue(json.loads((self.root / "run/ledger.json").read_text())["complete"])

    def test_exception_during_copy_preserves_partial_request(self):
        original = runner.Campaign.copy_tree
        def fail(campaign, source, destination):
            if "attempts" in destination.parts:
                raise OSError("injected copy failure")
            return original(campaign, source, destination)
        with patch.object(runner.Campaign, "copy_tree", fail):
            result = self.run_campaign(self.spec())
        self.assertEqual(result["status"], "failed")
        request = json.loads((self.root / "run/attempts/000000/ledger.json").read_text())
        self.assertEqual(request["status"], "stopped")
        self.assertIn("copy failure", request["error"])

    def test_invalid_spec_still_has_ledger(self):
        result = self.run_campaign({"schema_version": 1})
        self.assertEqual(result["status"], "failed")
        self.assertTrue((self.root / "run/ledger.json").is_file())
        self.assertTrue(result["complete"])

    def test_source_output_overlap_is_rejected_without_copy(self):
        spec = self.spec()
        result = runner.run_campaign(spec, self.source / "generated", max_disk_bytes=2**20,
                                     min_free_bytes=0, command_runner=self.fake_command, purpose="supervisor-test")
        self.assertEqual(result["status"], "failed")
        self.assertIn("disjoint", result["error"])
        self.assertEqual(self.calls, [])

    def test_candidate_preserved_and_j_runs_after_fuzz_cleanup(self):
        spec = self.spec()
        spec["judge"] = {"command": [sys.executable, "-c", "pass", "{request}", "{judge_output}"],
                         "request_template": {"source_root": "{source_root}", "component_wrapper": "{entrypoint}",
                                              "candidate": {"path": "{candidate}"}}}
        fake = self.fake_command
        def report(*args, **kwargs):
            receipt = fake(*args, **kwargs)
            output = args[1]
            if output.name == "fuzz":
                (output / "stderr.log").write_text("Counter Example:\n║ UnderConstrained (Non-Deterministic)\n║ Assignment Details:\n║ main.in = 1\n║ main.out = 2\n╚\n")
            return receipt
        self.fake_command = report
        result = self.run_campaign(spec)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual([row["stage"] for row in result["commands"]], ["fuzz", "judge"])
        request = result["attempts"][0]
        self.assertEqual(request["outcome"], "candidate")
        candidate = request["candidates"][0]
        self.assertEqual(runner.legacy.sha256_file(Path(candidate["path"])), candidate["sha256"])
        j = json.loads(Path(request["judgements"][0]["request"]).read_text())
        self.assertFalse(Path(request["judgements"][0]["request"]).is_relative_to(Path(j["source_root"])))

    def test_invalid_clock_measurement_propagates(self):
        fake = self.fake_command
        def invalid(*args, **kwargs):
            receipt = fake(*args, **kwargs)
            receipt.update(measurement_valid=False, invalid_reasons=["suspend_evidence"])
            return receipt
        self.fake_command = invalid
        result = self.run_campaign(self.spec())
        self.assertFalse(result["measurement_valid"])
        self.assertEqual(result["commands"][0]["invalid_reasons"], ["suspend_evidence"])

    def test_disk_limit_during_copy_prevents_process_dispatch(self):
        (self.source / "large.bin").write_bytes(b"x" * 100_000)
        spec = self.spec()
        result = runner.run_campaign(spec, self.root / "run", max_disk_bytes=40_000,
                                     min_free_bytes=0, command_runner=self.fake_command, purpose="supervisor-test")
        self.assertEqual(result["termination_reason"], "disk_limit")
        self.assertEqual(self.calls, [])
        self.assertTrue(result["complete"])

    def test_request_disk_limit_preserves_request_peak(self):
        (self.source / "large.bin").write_bytes(b"x" * 100_000)
        result = self.run_campaign(self.spec(), max_request_disk_bytes=40_000)
        self.assertEqual(result["termination_reason"], "disk_limit")
        self.assertEqual(self.calls, [])
        self.assertGreater(result["attempts"][0]["disk"]["peak_bytes"], 40_000)

    def test_request_budget_is_forwarded_as_work_budget(self):
        result = self.run_campaign(self.spec(), request_cap_seconds=.5)
        self.assertEqual(result["status"], "completed")
        self.assertGreater(self.calls[0][1], 0)
        self.assertLessEqual(self.calls[0][1], .5)
        self.assertNotIn("cleanup_cap_seconds", self.calls[0][2])

    def test_final_peak_rss_enforces_cap_even_without_tick(self):
        spec = self.spec()
        spec["max_tree_rss_bytes"] = 10
        result = self.run_campaign(spec)
        self.assertEqual(result["termination_reason"], "memory_limit")
        self.assertTrue(result["commands"][0]["memory_limit_exceeded"])

    def test_platform_failure_is_not_a_no_candidate_attempt(self):
        fake = self.fake_command
        def fail(*args, **kwargs):
            receipt = fake(*args, **kwargs)
            receipt.update(status="resource_monitor_failure", measurement_valid=False)
            return receipt
        self.fake_command = fail
        result = self.run_campaign(self.spec())
        self.assertEqual(result["termination_reason"], "resource_monitor_failure")
        self.assertFalse(result["measurement_valid"])
        self.assertNotEqual(result["attempts"][0].get("outcome"), "no_candidate")

    def test_final_observation_failure_stops_before_candidate_judging(self):
        fake = self.fake_command
        def invalid(*args, **kwargs):
            receipt = fake(*args, **kwargs)
            receipt.update(status='completed', measurement_valid=False,
                           invalid_reasons=['final_platform_sample_failed'])
            return receipt
        self.fake_command = invalid
        result = self.run_campaign(self.spec(2), max_attempts=2)
        self.assertEqual(result['termination_reason'], 'invalid_measurement')
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(result['measurement_valid'])

    def fake_config_module(self):
        def materialize(base, seed, tool):
            return {"trace_mutation_method": "constant_operator", **base, "seed": seed}
        def resolve(argv, tool):
            return {"binary_sha256": tool["sha256"], "mutation_config": json.loads(Path(argv[-1]).read_text()),
                    "semantic_settings": {"whitelist": ["IsZero", "Num2Bits"], "search_mode": "ga"}}
        return types.SimpleNamespace(materialize_settings=materialize, resolve_configuration=resolve,
                                     compare_w_s=lambda a, b: {"equal": a == b, "differences": [] if a == b else ["config"]})

    def test_cost_comparison_uses_peer_declared_seed_at_each_pass(self):
        spec, peer = self.spec(2), self.spec()
        for value in (spec, peer):
            value["seed_transport"] = {"kind": "mutation_settings", "argument": "--settings", "base": {}}
        with patch.dict(sys.modules, {"zkfdo_zkfuzz_config_v1": self.fake_config_module()}):
            result = runner.run_campaign(spec, self.root / "run", max_disk_bytes=8 * 2**20,
                         min_free_bytes=0, command_runner=self.fake_command, peer_spec=peer, max_attempts=3)
        self.assertEqual(result["status"], "completed", result)
        checks = result["configuration_comparisons"]
        self.assertEqual([row["expected_seed"] for row in checks], [100, 100, 101])
        self.assertTrue(all(row["equal"] and not row["peer_executed_by_this_check"] for row in checks))
        for request in result["attempts"]:
            settings = request["initial_settings"]
            self.assertEqual(settings["sha256"], request["settings_sha256_after_execution"])
            self.assertTrue(settings["materialized_full_defaults"])
            self.assertIn("trace_mutation_method", settings["initial_mutation_config"])

    def test_cost_comparison_requires_peer_before_dispatch(self):
        with patch.dict(sys.modules, {"zkfdo_zkfuzz_config_v1": self.fake_config_module()}):
            result = runner.run_campaign(self.spec(), self.root / "run", max_disk_bytes=8 * 2**20,
                         min_free_bytes=0, command_runner=self.fake_command)
        self.assertEqual(result["status"], "failed")
        self.assertIn("requires peer_spec", result["error"])
        self.assertEqual(self.calls, [])

    def test_expanded_settings_changed_by_child_are_rejected(self):
        spec = self.spec()
        spec["seed_transport"] = {"kind": "mutation_settings", "argument": "--settings", "base": {}}
        fake = self.fake_command
        def mutate(argv, *args, **kwargs):
            receipt = fake(argv, *args, **kwargs)
            Path(argv[-1]).write_text('{"seed": 999}')
            return receipt
        with patch.dict(sys.modules, {"zkfdo_zkfuzz_config_v1": self.fake_config_module()}):
            result = runner.run_campaign(spec, self.root / "run", max_disk_bytes=8 * 2**20,
                         min_free_bytes=0, command_runner=mutate, purpose="discovery")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["commands"][0]["execution_inputs_unchanged"])
        self.assertFalse(result["measurement_valid"])

    def test_preflight_compiler_uses_launch_gate_and_keeps_real_pin(self):
        spec = self.spec(preflight=True)
        spec["seed_transport"] = {"kind": "mutation_settings", "argument": "--settings", "base": {}}
        compiler = {"path": sys.executable, "sha256": runner.legacy.sha256_file(Path(sys.executable))}
        with patch.dict(sys.modules, {"zkfdo_zkfuzz_config_v1": self.fake_config_module()}):
            result = runner.run_campaign(spec, self.root / "run", max_disk_bytes=8 * 2**20,
                     min_free_bytes=0, command_runner=self.fake_command, purpose="discovery", tools={"circom": compiler})
        self.assertEqual(result["status"], "completed", result)
        command = result["commands"][0]
        self.assertEqual(command["original_argv"][0], sys.executable)
        self.assertNotEqual(command["argv"][0], sys.executable)
        self.assertEqual(command["compiler_gate"]["real_compiler"]["sha256"], compiler["sha256"])
        self.assertTrue(Path(command["compiler_gate"]["path"]).is_file())

    def test_judge_compiler_gate_supports_both_flag_forms(self):
        compiler = {"path": sys.executable, "sha256": runner.legacy.sha256_file(Path(sys.executable))}
        for embedded in (False, True):
            spec = self.spec()
            spec["seed_transport"] = {"kind": "mutation_settings", "argument": "--settings", "base": {}}
            option = ["--circom-bin=" + sys.executable] if embedded else ["--circom-bin", sys.executable]
            spec["judge"] = {"command": [sys.executable, "-c", "pass", "{request}", "{judge_output}", *option],
                             "request_template": {"source_root": "{source_root}", "candidate": "{candidate}"}}
            def report(*args, **kwargs):
                receipt = self.fake_command(*args, **kwargs)
                if args[1].name == "fuzz":
                    (args[1] / "stderr.log").write_text("Counter Example:\n║ UnderConstrained (Non-Deterministic)\n║ Assignment Details:\n║ main.out = 2\n╚\n")
                return receipt
            with patch.dict(sys.modules, {"zkfdo_zkfuzz_config_v1": self.fake_config_module()}):
                result = runner.run_campaign(spec, self.root / f"run-{embedded}", max_disk_bytes=8 * 2**20,
                         min_free_bytes=0, command_runner=report, purpose="discovery", tools={"circom": compiler})
            self.assertEqual(result["status"], "completed", result)
            command = result["commands"][-1]
            self.assertEqual(command["stage"], "judge")
            self.assertIn(command["compiler_gate"]["path"], " ".join(command["argv"]))
            self.assertNotEqual(command["original_argv"], command["argv"])

    def test_isolation_options_and_imds_are_explicitly_forwarded(self):
        isolation = {"cpus": "0-1", "memory_max_bytes": 1_000_000, "cgroup_root": "/sys/fs/cgroup/test"}
        record = {'restored': False}
        @contextmanager
        def affinity(cpus):
            self.assertEqual(cpus, '0-1')
            yield record
            record['restored'] = True
        with patch.object(runner.runtime.platform_layer, 'scoped_supervisor_affinity', affinity):
            result = self.run_campaign(self.spec(), isolation_options=isolation, include_imds=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.calls[0][2]["isolation_options"], isolation)
        self.assertTrue(self.calls[0][2]["include_imds"])
        self.assertEqual(result["peak_process_tree_rss_bytes"], 1000)
        self.assertEqual(result["attempts"][0]["peak_process_tree_rss_bytes"], 1000)
        self.assertIn("supervisor excluded", result["peak_process_tree_rss_scope"])
        self.assertTrue(result['supervisor_affinity']['restored'])
        self.assertTrue(json.loads((self.root/'run/receipt.json').read_text())['supervisor_affinity']['restored'])

    def test_affinity_restoration_failure_invalidates_saved_receipt(self):
        @contextmanager
        def affinity(_cpus):
            yield {'restored': False}
            raise runner.runtime.ObservationError('injected affinity restore failure')
        before = signal.getsignal(signal.SIGTERM)
        with patch.object(runner.runtime.platform_layer, 'scoped_supervisor_affinity', affinity):
            result = self.run_campaign(self.spec())
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['measurement_valid'])
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)
        self.assertEqual(json.loads((self.root/'run/receipt.json').read_text())['termination_reason'], 'affinity_error')

    def test_cli_isolation_options_match_platform_api(self):
        import inspect
        with patch.object(runner, 'run_campaign', return_value={'status': 'completed'}) as call:
            self.assertEqual(runner.main(['--spec', 'unused.json', '--purpose', 'discovery',
                '--max-disk-bytes', '1000000', '--cpu-affinity', '2-3',
                '--memory-max-bytes', '2000000', '--cgroup-root', '/sys/fs/cgroup/delegated']), 0)
        options = call.call_args.kwargs['isolation_options']
        bound = inspect.signature(runner.runtime.platform_layer.prepare_isolation).bind(**options)
        self.assertEqual(bound.arguments['cpus'], '2-3')

    def test_filtered_target_settings_cannot_change_before_execution(self):
        spec = self.spec()
        spec['seed_transport'] = {'kind': 'mutation_settings', 'argument': '--settings', 'base': {}}
        digest = runner.legacy.sha256_file(Path(sys.executable))
        config_path = self.root/'filter-configuration.json'
        config_path.write_text(json.dumps({'binary_sha256': digest}))
        source = {'path': str(self.source/'main.circom'), 'sha256': runner.legacy.sha256_file(self.source/'main.circom')}
        prototype = {'whitelist': ['IsZero', 'Num2Bits'], 'trace_mutation_method': 'constant_operator',
                     'search_mode': 'ga', 'binary_sha256': digest, 'eligible_for_skip': True,
                     'source_hashes': [source], 'snapshot_hashes': [source],
                     'configuration_source': {'path': str(config_path), 'sha256': runner.legacy.sha256_file(config_path)}}
        report_path = self.root/'filter.json'
        report_path.write_text(json.dumps({'schema': 'zkfdo-wrapper-filter-v2', 'enabled': True,
            'coverage_changed': True, 'skipped_target_ids': ['excluded'],
            'targets': [{**prototype, 'target_id': 'target-0'}, {**prototype, 'target_id': 'excluded'}]}))
        spec['wrapper_filter'] = {'report_path': str(report_path), 'report_sha256': runner.legacy.sha256_file(report_path),
                                  'enabled': True, 'coverage_changed': True}
        module = self.fake_config_module()
        resolve = module.resolve_configuration
        def changed(argv, tool):
            result = resolve(argv, tool)
            result['semantic_settings']['whitelist'] = []
            return result
        module.resolve_configuration = changed
        with patch.dict(sys.modules, {'zkfdo_zkfuzz_config_v1': module}):
            result = runner.run_campaign(spec, self.root/'run', max_disk_bytes=8*2**20,
                min_free_bytes=0, command_runner=self.fake_command, purpose='discovery')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('settings changed after wrapper filtering', result['error'])
        self.assertEqual(self.calls, [])

    def test_modified_filter_report_is_rejected_before_copy_or_execution(self):
        spec = self.spec()
        path = self.root/'filter.json';path.write_text('{}')
        spec['wrapper_filter'] = {'report_path': str(path), 'report_sha256': '0'*64}
        result = self.run_campaign(spec)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('filter report changed', result['error'])
        self.assertEqual(self.calls, [])

    def test_unknown_filter_configuration_cannot_bypass_mutator_comparison(self):
        campaign = object.__new__(runner.Campaign)
        campaign.spec = {'wrapper_filter': {'coverage_changed': True}}
        campaign.current = {'target_id': 'kept'}
        campaign.wrapper_filter = {'kept': {'configuration_source': {'scope': 'unknown'}}}
        changed = {'mutation_config': {'trace_mutation_method': 'naive'},
                   'semantic_settings': {'whitelist': [], 'search_mode': 'ga'}}
        with self.assertRaisesRegex(ValueError, 'regenerate the filter'):
            campaign.validate_filtered_configuration(changed)


class RealProcessTests(unittest.TestCase):
    # These two short tests invoke only the host Python through the shared runtime.
    # They are kept separate so the coordinator can run them when no engine is active.
    setUp = CampaignTests.setUp
    tearDown = CampaignTests.tearDown
    spec = CampaignTests.spec

    def test_real_timeout_keeps_cleanup_and_final_ledger(self):
        spec = self.spec()
        spec["targets"][0]["command"][2] = "import time;time.sleep(5)"
        spec["attempt_cap_seconds"] = .2
        result = runner.run_campaign(spec, self.root / "real", max_disk_bytes=4 * 2**20, min_free_bytes=0, purpose="supervisor-test")
        self.assertEqual(result["attempts"][0].get("outcome"), "timeout", result)
        self.assertTrue(result["commands"][0]["cleanup_complete"])
        self.assertGreater(result["wall_seconds"], .2)
        self.assertTrue(json.loads((self.root / "real/ledger.json").read_text())["complete"])

    def test_real_signal_propagates_and_restores_handler(self):
        spec = self.spec()
        spec["targets"][0]["command"][2] = "import os,signal,time;os.kill(os.getppid(),signal.SIGTERM);time.sleep(5)"
        before = signal.getsignal(signal.SIGTERM)
        result = runner.run_campaign(spec, self.root / "real", max_disk_bytes=4 * 2**20, min_free_bytes=0, purpose="supervisor-test")
        self.assertEqual(result["termination_reason"], "interrupted", result)
        self.assertTrue(result["commands"][0]["cleanup_complete"])
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)


if __name__ == "__main__":
    unittest.main()
