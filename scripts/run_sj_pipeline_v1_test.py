#!/usr/bin/env python3
"""Lightweight checks for the generic S to J pipeline."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import signal
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPTS))

import run_sj_pipeline_v1 as sj  # noqa: E402
import zkfdo_tools_v1 as tools_v1  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.project = root / "project"
        self.output = root / "output"
        self.marker = root / "tool-started.txt"
        self.stub = root / "stub.sh"
        self.j_stub = root / "j-v28.sh"
        self.manifest = root / "tools.json"
        self.entrypoint = self.project / "main.circom"
        self.base_input = self.project / "input.json"
        self.project.mkdir()
        self.entrypoint.write_text(
            "pragma circom 2.2.3;\n"
            "template Main() { signal input x; signal output y; y <== x; }\n"
            "component main = Main();\n"
        )
        self.base_input.write_text('{"x":"1"}\n')
        self.stub.write_text(f"#!/bin/sh\nprintf 'started\\n' >> '{self.marker}'\nexit 0\n")
        self.stub.chmod(0o755)
        self.j_stub.write_text(
            f"#!/bin/sh\n"
            "if [ \"${1:-}\" = --version ]; then\n"
            "  printf 'zkfdo-j-v28 0.1.0\\n'\n"
            "  exit 0\n"
            "fi\n"
            f"printf 'started\\n' >> '{self.marker}'\n"
            "exit 0\n")
        self.j_stub.chmod(0o755)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "Test User"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.project), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "fixture"], check=True)
        entry = {"path": str(self.stub), "sha256": digest(self.stub), "version": "1",
                 "source_commit": None, "build_command": None}
        names = [*sj.REQUIRED_TOOLS, "J_v28"]
        j_entry = {**entry, "path": str(self.j_stub), "sha256": digest(self.j_stub)}
        value = {"schema": "zkfdo-tools-v1", "platform": tools_v1.platform_name(),
                 "architecture": platform.machine(), "status": "ready",
                 "tools": {name: {**(j_entry if name == "J_v28" else entry),
                                   "role": "J v2.8" if name == "J_v28" else name}
                           for name in names}}
        self.manifest.write_text(json.dumps(value))

    def argv(self, *extra: str) -> list[str]:
        return ["--entrypoint", str(self.entrypoint), "--base-input", str(self.base_input),
                "--project-root", str(self.project), "--tools-manifest", str(self.manifest),
                "--out", str(self.output), "--corpus-layer", "development",
                "--min-free-gib", "0.001", *extra]

    def pipeline(self, *extra: str) -> sj.Pipeline:
        args = sj.parser().parse_args(self.argv(*extra))
        sj.validate_args(args)
        normalized = sj.normalize_inputs(args.entrypoint, args.base_input, args.project_root,
                                         args.library_path)
        tools, j_name = sj.load_tools(args.tools_manifest)
        identity = sj.pipeline_identity(args, normalized, tools, j_name)
        return sj.Pipeline(args, normalized, tools, j_name, identity)


def configure_synthetic_j(pipeline: sj.Pipeline, count: int) -> tuple[list[dict[str, object]], str]:
    candidates: list[dict[str, object]] = []
    for index in range(count):
        path = pipeline.output / f"candidate-{index}.json"
        path.write_text(json.dumps({"candidate": index}) + "\n")
        candidates.append({"target_id": f"target-{index}", "path": str(path),
                           "sha256": sj.sha256(path), "order": index})
    inventory = {
        "schema": "zkfdo-sj-candidate-inventory-v1",
        "order_policy": "first_unique_candidates_in_campaign_ledger_order",
        "order_basis": ["S attempt order", "candidate order within attempt"],
        "preserved": candidates, "representatives": candidates,
        "merged_duplicates": [], "diagnostic_limit": pipeline.args.j_candidates,
    }
    pipeline.candidate_inventory = types.MethodType(
        lambda _this, _outputs: inventory, pipeline)
    pipeline._binding_map = types.MethodType(
        lambda _this, _preparation: {
            f"target-{index}": {} for index in range(count)}, pipeline)
    pipeline._pre_j_identity = types.MethodType(
        lambda _this, _binding, request_id: {
            "schema": "fixture-pre-j-v1", "request_id": request_id}, pipeline)
    pipeline._j_request = types.MethodType(
        lambda _this, candidate, _binding, request_id: {
            "schema": "zkfdo-lifting-request-v1", "id": request_id,
            "candidate_sha256": candidate["sha256"],
        }, pipeline)
    pipeline._validate_probe_contract = types.MethodType(
        lambda _this, *_args: {"status": "validated"}, pipeline)
    baseline_sha = "a" * 64
    pipeline.ledger["stages"]["baseline"] = {
        "outputs": {"r1cs": {"sha256": baseline_sha}}}
    return candidates, baseline_sha


def synthetic_resume_worker(root_text: str, extra_seconds: float = 0.0,
                            candidate_limit: int | None = None) -> dict[str, object]:
    root = Path(root_text).resolve()
    output = root / "output"
    argv = [
        "--entrypoint", str(root / "project/main.circom"),
        "--base-input", str(root / "project/input.json"),
        "--project-root", str(root / "project"),
        "--tools-manifest", str(root / "tools.json"),
        "--out", str(output), "--corpus-layer", "development",
        "--min-free-gib", "0.001", "--run-min-free-gib", "0.001",
        "--j-request-seconds", "1", "--j-total-seconds", "2",
        "--j-extra-total-seconds", str(extra_seconds),
    ]
    if candidate_limit is not None:
        argv.extend(["--j-candidates", str(candidate_limit)])
    args = sj.parser().parse_args(argv)
    sj.validate_args(args)
    with sj.OutputLock(output):
        normalized = sj.normalize_inputs(
            args.entrypoint, args.base_input, args.project_root, args.library_path)
        tools, j_name = sj.load_tools(args.tools_manifest)
        pipeline = sj.Pipeline(
            args, normalized, tools, j_name,
            sj.pipeline_identity(args, normalized, tools, j_name))
        candidates, baseline_sha = configure_synthetic_j(pipeline, 5)
        pipeline.register_budget_allocation()
        pipeline.reconcile_interrupted_consumption()
        calls = root / "synthetic-j-calls.jsonl"

        def run(_stage: str, label: str, argv_value: list[object], *_args: object,
                **_kwargs: object) -> dict[str, object]:
            with calls.open("a") as output_log:
                output_log.write(label + "\n")
            request_path = Path(argv_value[2])
            request_output = Path(argv_value[4])
            request_output.mkdir()
            index = int(label.split("-")[1])
            request_sha = sj.sha256(request_path)
            sj.atomic_json(request_output / "result.json", {
                "schema": "zkfdo-lifting-result-v2.8", "request_id": label,
                "request_sha256": request_sha,
                "candidate_sha256": candidates[index]["sha256"],
                "entrypoint": {"o0_r1cs_sha256": baseline_sha},
                "classes": [], "verdict_counts": {},
            })
            sj.atomic_json(request_output / "site-signal-probe.json", {
                "schema": "zkfdo-site-signal-probe-v1", "enabled": True,
                "request_sha256": request_sha,
                "candidate_sha256": candidates[index]["sha256"],
            })
            return {"status": "completed", "returncode": 0, "wall_seconds": 1.0,
                    "cpu_seconds": 0.0,
                    "argv_sha256": sj.value_sha(sj.command_view(argv_value))}

        def postcheck(_this: sj.Pipeline, record: dict[str, object],
                      checkpoint: object) -> dict[str, object]:
            record["postcheck"] = {
                "wall_seconds": 0.0, "cpu_seconds": 0.0,
                "status": "completed", "terminal_status": "no_eligible_pairs",
            }
            record["cache_cleanup"] = {
                "status": "already_absent", "path": str(Path(record["directory"]) / "cache")}
            checkpoint()
            return {"status": "completed",
                    "check": {"terminal_status": "no_eligible_pairs"}}

        pipeline.runner.run = run
        pipeline._postcheck_request = types.MethodType(postcheck, pipeline)
        outputs = pipeline.j_requests_stage({}, {})
        pipeline.ledger["status"] = outputs["pipeline_status"]
        pipeline.checkpoint()
        summary_candidates = pipeline.build_summary()["candidates"]
        pipeline.write_summary()
        call_labels = calls.read_text().splitlines() if calls.exists() else []
        result = {
            "pipeline_status": outputs["pipeline_status"],
            "candidate_status": outputs["candidate_status"],
            "states": [row["state"] for row in pipeline.ledger["candidate_states"]],
            "call_count": len(call_labels),
            "call_labels": call_labels,
            "budget": pipeline.ledger["budget_accounting"]["j"],
            "diagnostic_limit": outputs["diagnostic_candidate_limit"],
            "order_policy": outputs["order_policy"],
            "order_basis": outputs["order_basis"],
            "summary_candidates": summary_candidates,
            "summary_markdown": (pipeline.output / "summary.md").read_text(),
        }
    print(json.dumps(result, sort_keys=True))
    return result


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temporary.name).resolve())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def resume_process(self, extra_seconds: float = 0.0,
                       candidate_limit: int | None = None) -> dict[str, object]:
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(SCRIPTS)!r}); "
            "import run_sj_pipeline_v1_test as t; "
            "t.synthetic_resume_worker(sys.argv[1], float(sys.argv[2]), "
            "None if sys.argv[3] == 'none' else int(sys.argv[3]))")
        process = subprocess.run(
            [sys.executable, "-B", "-c", code, str(self.fixture.root),
             str(extra_seconds), "none" if candidate_limit is None else str(candidate_limit)],
            cwd=sj.ROOT, capture_output=True, text=True, timeout=30, check=True)
        return json.loads(process.stdout.splitlines()[-1])

    def test_dry_run_never_starts_tool(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = sj.main(self.fixture.argv("--dry-run"))
        self.assertEqual(status, 0)
        self.assertFalse(self.fixture.marker.exists())
        ledger = json.loads((self.fixture.output / "ledger.json").read_text())
        plan = json.loads((self.fixture.output / "dry-run.json").read_text())
        self.assertFalse(ledger["engine_started"])
        self.assertFalse(plan["engine_started"])
        baseline = [row for row in plan["commands"] if row["stage"] == "baseline"]
        self.assertEqual([row["label"] for row in baseline],
                         ["compile", "honest_witness", "rust_check", "snarkjs_check"])
        self.assertEqual(len([row for row in plan["commands"]
                              if row["stage"] == "preflight"]), 4)
        self.assertIsNone(plan["budgets"]["j_candidate_limit"])
        self.assertEqual(plan["budgets"]["probe_request_seconds"], 900)
        self.assertEqual(plan["j"]["jobs"], 1)
        self.assertEqual(plan["tools_manifest"]["path"], str(self.fixture.manifest.resolve()))
        self.assertEqual(plan["tools_manifest"]["sha256"], digest(self.fixture.manifest))
        self.assertEqual(plan["j"]["path"], str(self.fixture.j_stub.resolve()))
        self.assertEqual(plan["j"]["sha256"], digest(self.fixture.j_stub))
        self.assertTrue(plan["j"]["probe_enabled"])
        self.assertEqual(plan["j"]["probe_classes"], "unresolved")
        self.assertIn("zkfdo-j-v28", plan["j"]["verified_version_output"])
        self.assertEqual([row["label"] for row in plan["actions"][-3:]], [
            "preserve_original_r1cs_and_sym", "remove_request_cache_after_checks",
            "write_terminal_tables"])
        self.assertEqual([row["phase"] for row in ledger["stages"]["preflight"]
                          ["planning_costs"]["phases"]], [
                              "input_and_revision_preflight", "tools_manifest", "identity"])
        s_templates = {row["label"]: row for row in plan["commands"]
                       if row["stage"] == "s_campaign"
                       and row["kind"] == "subprocess_template"}
        self.assertTrue(s_templates["fragment_preflight_compile"]["directory_template"]
                        .endswith("/preflight/${target_index_4d}/process"))
        self.assertTrue(s_templates["fragment_fuzz"]["directory_template"]
                        .endswith("/attempts/${attempt_index_6d}/fuzz"))
        self.assertEqual(s_templates["fragment_fuzz"]["timeout_policy"]["rule"],
                         "min(command_cap_seconds, remaining_s_total_seconds)")
        self.assertIn("selected_candidates", plan["paths"])
        self.assertIn("candidate_report_template", plan["paths"]["s_campaign"])
        self.assertTrue({"result", "probe", "cache_cleanup"} <=
                        plan["paths"]["j_request_template"].keys())
        postcheck = next(row for row in plan["commands"]
                         if row["stage"] == "postcheck")
        self.assertIn("comparator_or_deviated_wtns", postcheck["deferred_paths"])
        j_command = next(row for row in plan["commands"]
                         if row["stage"] == "j_requests")
        self.assertEqual(j_command["timeout_policy"]["budget_scope"],
                         "J subprocess wall including process-group cleanup")

    def test_initial_seed_must_be_nonzero_u64(self) -> None:
        for value in ("0", str(2**64)):
            with self.subTest(value=value):
                args = sj.parser().parse_args(self.fixture.argv("--initial-seed", value))
                with self.assertRaisesRegex(ValueError, "nonzero u64"):
                    sj.validate_args(args)

    def test_relative_manifest_uses_loaded_canonical_path(self) -> None:
        relative = Path(os.path.relpath(self.fixture.manifest, sj.ROOT))
        argv = self.fixture.argv()
        argv[argv.index(str(self.fixture.manifest))] = str(relative)
        args = sj.parser().parse_args(argv)
        sj.validate_args(args)
        normalized = sj.normalize_inputs(args.entrypoint, args.base_input, args.project_root,
                                         args.library_path)
        elsewhere = Path(self.temporary.name) / "elsewhere"
        elsewhere.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(elsewhere)
            tools, j_name = sj.load_tools(args.tools_manifest)
            identity = sj.pipeline_identity(args, normalized, tools, j_name)
            pipeline = sj.Pipeline(args, normalized, tools, j_name, identity)
            plan = pipeline.dry_run()
        finally:
            os.chdir(previous)
        expected = str(self.fixture.manifest.resolve())
        self.assertEqual(identity["tools_manifest"]["path"], expected)
        call = next(row for row in plan["commands"] if row.get("label") == "policy_v5_1")
        self.assertEqual(call["keyword_arguments"]["tools_manifest_path"], expected)

    def test_identity_hashes_indirect_runner_modules(self) -> None:
        names = {path.name for path in sj.local_module_closure(sj.REUSED_MODULE_ROOTS)}
        self.assertTrue({
            "c03_outcomes.py", "measure_c02_preparation.py",
            "zkfdo_runtime_v2.py", "zkfdo_preflight_v1.py", "zkfuzz_report.py",
            "zkfdo_platform.py", "zkfdo_observer_v1.py", "zkfdo_runtime_v1.py",
            "zkfdo_zkfuzz_config_v2.py", "zkfdo_compile_gate_v2.py",
        } <= names)

    def test_stage_order_uses_stub_commands(self) -> None:
        pipeline = self.fixture.pipeline()
        observed: list[str] = []

        def stage(name: str, output: dict[str, object]):
            def call(this: sj.Pipeline, *_args: object) -> dict[str, object]:
                with sj.stage_attempt(this, name) as row:
                    self.assertIsNotNone(row)
                    attempt = Path(row["directory"])
                    command = this.runner.run(name, "stub", [self.fixture.stub], attempt / "command", 5)
                    self.assertEqual(command["status"], "completed")
                    row["outputs"] = output
                    observed.append(name)
                    return output
            return types.MethodType(call, pipeline)

        pipeline.preflight_stage = stage("preflight", {})
        pipeline.baseline_stage = stage("baseline", {})
        pipeline.preparation_stage = stage("preparation", {"bindings": []})
        pipeline.s_campaign_stage = stage("s_campaign", {})
        pipeline.j_requests_stage = stage("j_requests", {"requests": [], "selected_count": 0})
        pipeline.postcheck_stage = stage("postcheck", {"validated_counterexamples": []})

        def summary(this: sj.Pipeline) -> dict[str, str]:
            with sj.stage_attempt(this, "summary") as row:
                paths = {"summary_json": str(this.output / "summary.json"),
                         "summary_markdown": str(this.output / "summary.md")}
                row["outputs"] = paths
                observed.append("summary")
            this.write_summary()
            return paths

        pipeline.summary_stage = types.MethodType(summary, pipeline)
        self.assertTrue(pipeline.run())
        self.assertEqual(observed, list(sj.STAGES))
        self.assertEqual(self.fixture.marker.read_text().splitlines(), ["started"] * 6)

    def test_failure_has_terminal_record(self) -> None:
        pipeline = self.fixture.pipeline()

        def preflight(this: sj.Pipeline) -> dict[str, object]:
            with sj.stage_attempt(this, "preflight") as row:
                row["outputs"] = {}
                return {}

        def baseline(this: sj.Pipeline) -> dict[str, object]:
            with sj.stage_attempt(this, "baseline"):
                raise sj.PipelineError("baseline_input_invalid", "fixture failure")

        pipeline.preflight_stage = types.MethodType(preflight, pipeline)
        pipeline.baseline_stage = types.MethodType(baseline, pipeline)
        self.assertFalse(pipeline.run())
        ledger = json.loads((self.fixture.output / "ledger.json").read_text())
        self.assertEqual(ledger["stages"]["baseline"]["terminal_status"], "baseline_input_invalid")
        self.assertEqual(ledger["stages"]["preparation"]["terminal_status"], "not_observed")
        self.assertTrue(ledger["complete"])
        self.assertTrue((self.fixture.output / "summary.json").is_file())

    def test_terminal_failure_requires_new_output_suffix(self) -> None:
        pipeline = self.fixture.pipeline()
        fail_once = {"value": True}

        def preflight(this: sj.Pipeline) -> dict[str, object]:
            with sj.stage_attempt(this, "preflight") as row:
                if fail_once["value"]:
                    fail_once["value"] = False
                    raise sj.PipelineError("fixture_failure", "first attempt")
                row["outputs"] = {}
                return {}

        def stage(name: str, outputs: dict[str, object]):
            def call(this: sj.Pipeline, *_args: object) -> dict[str, object]:
                with sj.stage_attempt(this, name) as row:
                    row["outputs"] = outputs
                    return outputs
            return types.MethodType(call, pipeline)

        pipeline.preflight_stage = types.MethodType(preflight, pipeline)
        pipeline.baseline_stage = stage("baseline", {})
        pipeline.preparation_stage = stage("preparation", {"bindings": []})
        pipeline.s_campaign_stage = stage("s_campaign", {})
        pipeline.j_requests_stage = stage(
            "j_requests", {"requests": [], "selected_count": 0})
        pipeline.postcheck_stage = stage(
            "postcheck", {"checks": [], "validated_counterexamples": []})
        self.assertFalse(pipeline.run())
        self.assertEqual(pipeline.ledger["stages"]["summary"]["status"],
                         "reported_after_failure")
        with self.assertRaises(sj.PipelineError) as caught:
            self.fixture.pipeline()
        self.assertEqual(caught.exception.status, "terminal_output_immutable")

    def test_baseline_compile_failure_is_invalid_input(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.preflight_stage()
        pipeline.runner.run = lambda *_args, **_kwargs: {"status": "command_failed"}
        with self.assertRaises(sj.PipelineError) as caught:
            pipeline.baseline_stage()
        self.assertEqual(caught.exception.status, "baseline_input_invalid")
        self.assertEqual(pipeline.ledger["stages"]["baseline"]["terminal_status"],
                         "baseline_input_invalid")

    def test_startup_failure_has_terminal_record(self) -> None:
        self.fixture.base_input.write_text("{broken\n")
        with redirect_stderr(io.StringIO()):
            status = sj.main(self.fixture.argv())
        self.assertEqual(status, 2)
        ledger = json.loads((self.fixture.output / "ledger.json").read_text())
        summary = json.loads((self.fixture.output / "summary.json").read_text())
        identity = json.loads((self.fixture.output / "identity.json").read_text())
        self.assertFalse(ledger["engine_started"])
        self.assertEqual(ledger["stages"]["preflight"]["status"], "failed")
        self.assertEqual(ledger["stages"]["preflight"]["terminal_status"],
                         "input_preflight_failed")
        self.assertEqual(summary["safety_conclusion"], "not_made")
        self.assertEqual(summary["candidates"]["total"], 0)
        self.assertEqual(summary["candidates"]["judged"], 0)
        self.assertEqual(summary["candidates"]["pending_not_run"], 0)
        self.assertEqual(identity["schema"], "zkfdo-sj-startup-failure-identity-v1")
        self.assertFalse(self.fixture.marker.exists())

    def test_changed_identity_is_rejected(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(sj.main(self.fixture.argv("--dry-run")), 0)
        self.fixture.base_input.write_text('{"x":"2"}\n')
        stderr = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            status = sj.main(self.fixture.argv("--dry-run"))
        self.assertEqual(status, 2)
        self.assertIn("identity differs", stderr.getvalue())
        self.assertFalse(self.fixture.marker.exists())

    def test_downstream_stage_rejects_changed_upstream_identity(self) -> None:
        pipeline = self.fixture.pipeline()
        with sj.stage_attempt(pipeline, "preparation") as row:
            row["outputs"] = {"version": 1}
        with sj.stage_attempt(pipeline, "s_campaign") as row:
            first = row["attempt"]
            row["outputs"] = {"version": 1}
        with self.assertRaises(sj.PipelineError) as caught:
            pipeline.ledger["stages"]["preparation"]["outputs"] = {"version": 2}
            pipeline.archive_stage_record(
                "preparation", pipeline.ledger["stages"]["preparation"], recovered=True)
        self.assertEqual(caught.exception.status, "attempt_history_mismatch")
        self.assertEqual(pipeline.ledger["stages"]["s_campaign"]["attempt"], first)

    def test_summary_marks_unobserved_and_output_identical(self) -> None:
        pipeline = self.fixture.pipeline()
        result_path = pipeline.output / "fixture-result.json"
        probe_path = pipeline.output / "fixture-probe.json"
        result_path.write_text(json.dumps({"preparation": {"status": "ok"},
                                           "classes": [{"verdict": "unknown"}],
                                           "verdict_counts": {"unknown": 1}}))
        probe_path.write_text(json.dumps({"status": "complete", "classes": [
            {"attempts": [{"status": "verified_output_identical"}]}
        ]}))
        pipeline.ledger["stages"]["s_campaign"] = {
            "status": "completed", "terminal_status": "completed", "wall_seconds": 0,
            "cpu_seconds": 0, "outputs": {"termination_reason": "budget_exhausted"}}
        pipeline.ledger["stages"]["j_requests"] = {
            "status": "completed", "terminal_status": "completed", "wall_seconds": 0,
            "cpu_seconds": 0, "outputs": {"selected_count": 2, "requests": [
                {"request_id": "candidate-00", "status": "budget_exhausted",
                 "terminal_status": "not_observed", "reason": "request budget",
                 "candidate": {"sha256": "0" * 64}},
                {"request_id": "candidate-01", "status": "completed",
                 "terminal_status": "completed", "candidate": {"sha256": "1" * 64},
                 "result": {"path": str(result_path),
                            "sha256": sj.sha256(result_path)},
                 "probe": {"path": str(probe_path),
                           "sha256": sj.sha256(probe_path)}}
            ]}}
        pipeline.ledger["stages"]["postcheck"] = {
            "status": "completed", "terminal_status": "completed", "wall_seconds": 0,
            "cpu_seconds": 0, "outputs": {"validated_counterexamples": []}}
        summary = pipeline.build_summary()
        self.assertEqual(summary["safety_conclusion"], "not_made")
        self.assertEqual(summary["validated_counterexample"], [])
        self.assertTrue(any(row["status"] == "not_observed" for row in summary["not_observed"]))
        pipeline.write_summary()
        markdown = (pipeline.output / "summary.md").read_text()
        for heading in ("## J requests", "## J classes", "## Probe results",
                        "## Validated counterexamples", "## Not observed and limited",
                        "## Limitations"):
            self.assertIn(heading, markdown)
        self.assertIn("candidate-01", markdown)
        self.assertIn("verified_output_identical", markdown)
        self.assertTrue(any(row["status"] == "limited_observation"
                            for row in summary["not_observed"]))
        self.assertEqual(summary["j"]["requests"][1]["classes"][0]["verdict"], "unknown")
        self.assertEqual(summary["j"]["requests"][1]["probe"]["classes"][0]["attempts"][0]["status"],
                         "verified_output_identical")
        self.assertEqual(summary["j"]["requests"][1]["postcheck"]["terminal_status"],
                         "not_observed")

    def test_summary_records_unreadable_completed_result_as_unobserved(self) -> None:
        pipeline = self.fixture.pipeline()
        result = pipeline.output / "result.json"
        probe = pipeline.output / "probe.json"
        result.write_text('{"classes": []}\n')
        probe.write_text('{"status": "complete", "classes": []}\n')
        result_sha = sj.sha256(result)
        result.write_text('{"changed": true}\n')
        request = {
            "request_id": "candidate-00", "status": "completed",
            "terminal_status": "validated", "candidate": {"sha256": "1" * 64},
            "result": {"path": str(result), "sha256": result_sha},
            "probe": {"path": str(probe), "sha256": sj.sha256(probe)},
        }
        pipeline.ledger["stages"]["j_requests"] = {
            "status": "completed", "terminal_status": "completed",
            "wall_seconds": 0, "cpu_seconds": 0,
            "outputs": {"selected_count": 1, "requests": [request]},
        }
        pipeline.ledger["stages"]["postcheck"] = {
            "status": "completed", "terminal_status": "completed",
            "wall_seconds": 0, "cpu_seconds": 0,
            "outputs": {"checks": [{"request_id": "candidate-00",
                                      "terminal_status": "validated", "pairs": []}],
                        "validated_counterexamples": []},
        }
        summary = pipeline.build_summary()
        self.assertTrue(any(row["scope"] == "candidate-00:result_summary"
                            and row["status"] == "not_observed"
                            for row in summary["not_observed"]))

    def test_summary_stage_binds_written_artifacts(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.ledger.update(status="completed", complete=True)
        with patch.object(sj.time, "monotonic",
                          side_effect=[10.0, 12.5, 12.5, 13.0]):
            outputs = pipeline.summary_stage()
        record = pipeline.ledger["stages"]["summary"]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["wall_seconds"], 2.5)
        summary = json.loads((pipeline.output / "summary.json").read_text())
        summary_row = next(row for row in summary["stages"] if row["stage"] == "summary")
        self.assertEqual(summary_row["status"], "completed")
        self.assertEqual(summary_row["wall_seconds"], 2.5)
        self.assertEqual(summary_row["wall_seconds"], record["wall_seconds"])
        self.assertEqual(summary_row["cost_scope"], "through_initial_durable_render")
        pipeline.validate_completed_stage("summary", record)
        Path(outputs["summary_markdown"]["path"]).write_text("changed\n")
        with self.assertRaises(sj.PipelineError):
            pipeline.validate_completed_stage("summary", record)

    def test_summary_failure_records_standard_stage_cost(self) -> None:
        pipeline = self.fixture.pipeline()
        with patch.object(pipeline, "write_summary", side_effect=OSError("fixture")), \
                patch.object(sj.time, "monotonic", side_effect=[5.0, 7.0]):
            with self.assertRaises(OSError):
                pipeline.summary_stage()
        record = pipeline.ledger["stages"]["summary"]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["wall_seconds"], 2.0)
        self.assertEqual(record["observed_wall_seconds"], 2.0)
        self.assertEqual(record["cost_scope"], "through_failure")

    def test_duplicate_candidates_do_not_trigger_selection_cap(self) -> None:
        pipeline = self.fixture.pipeline()
        campaign = pipeline.output / "campaign-ledger.json"
        sj.atomic_json(campaign, {"attempts": [{"candidates": [
            {"sha256": "1" * 64, "duplicate_of": None},
            {"sha256": "1" * 64, "duplicate_of": "first"},
        ]}]})
        pipeline.ledger["stages"]["s_campaign"] = {
            "status": "completed", "terminal_status": "completed", "wall_seconds": 0,
            "cpu_seconds": 0, "outputs": {
                "campaign_ledger": {"path": str(campaign), "sha256": sj.sha256(campaign)}}}
        pipeline.ledger["stages"]["j_requests"] = {
            "status": "completed", "terminal_status": "completed", "wall_seconds": 0,
            "cpu_seconds": 0, "outputs": {"selected_count": 1, "requests": []}}
        pipeline.ledger["stages"]["postcheck"] = {
            "status": "completed", "terminal_status": "completed", "wall_seconds": 0,
            "cpu_seconds": 0, "outputs": {"validated_counterexamples": []}}
        summary = pipeline.build_summary()
        self.assertEqual(summary["candidates"]["preserved"], 2)
        self.assertEqual(summary["candidates"]["eligible_unique"], 1)
        self.assertFalse(any(row["scope"] == "J candidates after selection limit"
                             for row in summary["not_observed"]))

    def test_all_candidates_resume_in_new_process_with_explicit_extra_budget(self) -> None:
        first = self.resume_process()
        self.assertEqual(first["pipeline_status"], "partial:candidates_pending")
        self.assertEqual(first["candidate_status"], {
            "total": 5, "judged": 2, "in_progress_interrupted": 0,
            "pending_not_run": 3})
        self.assertEqual(first["states"], ["judged", "judged", "pending_not_run",
                                            "pending_not_run", "pending_not_run"])
        self.assertEqual(first["call_count"], 2)
        self.assertEqual(first["call_labels"], [
            "candidate-000000-attempt-0001", "candidate-000001-attempt-0001"])
        self.assertIsNone(first["diagnostic_limit"])
        self.assertEqual(first["order_policy"],
                         "first_unique_candidates_in_campaign_ledger_order")
        self.assertEqual(first["order_basis"],
                         ["S attempt order", "candidate order within attempt"])
        self.assertEqual(first["summary_candidates"]["total"], 5)
        self.assertEqual(first["summary_candidates"]["judged"], 2)
        self.assertEqual(first["summary_candidates"]["pending_not_run"], 3)
        self.assertIn("total `5`, judged `2`, pending not run `3`",
                      first["summary_markdown"])

        without_grant = self.resume_process()
        self.assertEqual(without_grant["pipeline_status"], "partial:candidates_pending")
        self.assertEqual(without_grant["call_count"], 2)
        self.assertEqual(without_grant["call_labels"], first["call_labels"])
        self.assertEqual(without_grant["budget"]["allocated_seconds"], 2.0)
        self.assertEqual(without_grant["budget"]["consumed_seconds"], 2.0)

        resumed = self.resume_process(3.0)
        self.assertEqual(resumed["pipeline_status"], "completed")
        self.assertEqual(resumed["candidate_status"], {
            "total": 5, "judged": 5, "in_progress_interrupted": 0,
            "pending_not_run": 0})
        self.assertEqual(resumed["call_count"], 5)
        self.assertEqual(resumed["call_labels"], [
            "candidate-000000-attempt-0001", "candidate-000001-attempt-0001",
            "candidate-000002-attempt-0001", "candidate-000003-attempt-0001",
            "candidate-000004-attempt-0001"])
        self.assertEqual(resumed["budget"]["allocated_seconds"], 5.0)
        self.assertEqual(resumed["budget"]["consumed_seconds"], 5.0)
        extra = [event for event in resumed["budget"]["events"]
                 if event["kind"] == "extra_allocation"]
        self.assertEqual([event["seconds"] for event in extra], [3.0])
        ledger = json.loads((self.fixture.output / "ledger.json").read_text())
        self.assertEqual([len(row["attempts"]) for row in ledger["candidate_states"]],
                         [1, 1, 1, 1, 1])

    def test_diagnostic_candidate_limit_is_visible_and_leaves_pending(self) -> None:
        limited = self.resume_process(1.0, candidate_limit=3)
        self.assertEqual(limited["pipeline_status"], "partial:candidates_pending")
        self.assertEqual(limited["diagnostic_limit"], 3)
        self.assertEqual(limited["candidate_status"], {
            "total": 5, "judged": 3, "in_progress_interrupted": 0,
            "pending_not_run": 2})
        ledger = json.loads((self.fixture.output / "ledger.json").read_text())
        inventory = json.loads((self.fixture.output / "candidate-ledger/inventory.json").read_text())
        self.assertEqual(inventory["diagnostic_limit"], 3)
        self.assertTrue(ledger["stages"]["j_requests"]["outputs"]["diagnostic_limit_active"])
        self.assertEqual(limited["summary_candidates"]["selection_limit"], 3)
        self.assertTrue(limited["summary_candidates"]["diagnostic_limit_active"])
        self.assertIn("Diagnostic candidate limit: `3`", limited["summary_markdown"])

    def test_disk_gate_stops_below_threshold(self) -> None:
        def usage(_path: Path) -> tuple[int, int, int]:
            return 100, 91, 9

        with self.assertRaises(sj.PipelineError) as caught:
            sj.disk_gate(self.fixture.output, 10, usage=usage)
        self.assertEqual(caught.exception.status, "insufficient_disk")

    def test_periodic_disk_monitor_stops_a_running_process(self) -> None:
        checks = 0

        def usage(_path: Path) -> tuple[int, int, int]:
            nonlocal checks
            checks += 1
            return (100, 1, 99) if checks == 1 else (100, 99, 1)

        runner = sj.CommandRunner({"commands": []}, lambda: None)
        row = runner.run(
            "fixture", "disk-floor", [sys.executable, "-c", "import time; time.sleep(60)"],
            self.fixture.root / "disk-command", 5, disk_path=self.fixture.root,
            minimum_free_bytes=50, disk_interval_seconds=0.01, disk_usage=usage)
        self.assertEqual(row["status"], "disk_floor")
        self.assertGreaterEqual(checks, 2)
        self.assertTrue(row["termination"]["term_sent"])
        self.assertTrue(row["termination"]["group_gone"])
        self.assertLess(row["wall_seconds"], 5)

    def test_j_disk_gate_stops_before_launch_and_keeps_candidate_pending(self) -> None:
        pipeline = self.fixture.pipeline("--j-total-seconds", "2", "--j-request-seconds", "1")
        configure_synthetic_j(pipeline, 1)
        pipeline.runner.run = lambda *_args, **_kwargs: self.fail("J must not start below disk floor")
        with patch.object(
                sj, "disk_gate",
                side_effect=sj.PipelineError("insufficient_disk", "fixture disk floor")):
            outputs = pipeline.j_requests_stage({}, {})
        request = outputs["requests"][0]
        self.assertEqual(request["terminal_status"], "insufficient_disk")
        self.assertEqual(request["cache_cleanup"]["status"], "retained_for_recovery")
        self.assertEqual(pipeline.ledger["candidate_states"][0]["state"],
                         "pending_not_run")
        self.assertEqual(outputs["pipeline_status"], "partial:candidates_pending")

    def test_nested_library_and_j_request_shape(self) -> None:
        nested = self.fixture.project / "src"
        nested.mkdir()
        args = sj.parser().parse_args(self.fixture.argv("--library-path", str(nested)))
        sj.validate_args(args)
        normalized = sj.normalize_inputs(args.entrypoint, args.base_input, args.project_root,
                                         args.library_path)
        tools, j_name = sj.load_tools(args.tools_manifest)
        pipeline = sj.Pipeline(args, normalized, tools, j_name,
                               sj.pipeline_identity(args, normalized, tools, j_name))
        pipeline.write_source_snapshot()
        self.assertIn(pipeline.project / "src", pipeline.library_paths)
        self.assertTrue((pipeline.project / "src").is_dir())
        prepared = pipeline.source_root / "prepared-0001" / "sources"
        wrapper = prepared / "target.circom"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("component main = Main();\n")
        candidate = pipeline.output / "candidate.json"
        candidate.write_text("{}\n")
        request = pipeline._j_request(
            {"path": str(candidate)},
            {"wrapper": str(wrapper), "sources": str(prepared),
             "wrapper_sha256": sj.sha256(wrapper),
             "sources_tree_sha256": sj.policy_v1.tree_sha256(prepared)},
            "candidate-00")
        self.assertEqual(request["candidate"], {"format": "zkfuzz", "path": str(candidate)})
        self.assertEqual(request["library_paths"][0], str(prepared))

    def test_prepared_source_root_ignores_project_sources_directory(self) -> None:
        pipeline = self.fixture.pipeline()
        prepared = pipeline.source_root / "prepared-0001"
        outer = prepared / "targets/0001/sources"
        entrypoint = outer / "project/sources/nested/target.circom"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("component main = Main();\n")
        self.assertEqual(pipeline._prepared_sources(entrypoint, prepared), outer)

    def test_dry_run_cannot_replace_started_ledger(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.ledger.update(status="running", engine_started=True)
        pipeline.checkpoint()
        before = (pipeline.output / "ledger.json").read_bytes()
        with self.assertRaises(sj.PipelineError) as caught:
            pipeline.dry_run()
        self.assertEqual(caught.exception.status, "resume_state_conflict")
        self.assertEqual((pipeline.output / "ledger.json").read_bytes(), before)

    def test_source_snapshot_change_rejects_completed_resume(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.write_source_snapshot()
        pipeline.entrypoint.write_text("changed\n")
        with self.assertRaises(sj.PipelineError) as caught:
            pipeline.validate_completed_stage("preflight", {"outputs": {}})
        self.assertEqual(caught.exception.status, "resume_identity_mismatch")

    def test_source_manifest_and_extra_file_are_rejected(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.preflight_stage()
        record = pipeline.ledger["stages"]["preflight"]
        manifest_path = pipeline.output / "work/source-manifest.json"
        original = manifest_path.read_bytes()
        manifest = json.loads(original)
        manifest["files"] = []
        manifest["closure_sha256"] = "0" * 64
        sj.atomic_json(manifest_path, manifest)
        with self.assertRaises(sj.PipelineError):
            pipeline.validate_completed_stage("preflight", record)
        manifest_path.write_bytes(original)
        extra = pipeline.project / "extra.circom"
        extra.write_text("component main = Main();\n")
        with self.assertRaises(sj.PipelineError):
            pipeline.validate_completed_stage("preflight", record)
        extra.unlink()
        generated = pipeline.source_root / "prepared-0001/generated.txt"
        generated.parent.mkdir()
        generated.write_text("allowed sibling\n")
        pipeline.validate_completed_stage("preflight", record)

    def test_completed_preflight_rechecks_disk_gate(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.preflight_stage()
        failure = sj.PipelineError("insufficient_disk", "fixture disk gate")
        with patch.object(sj, "disk_gate", side_effect=failure):
            with self.assertRaises(sj.PipelineError):
                pipeline.preflight_stage()
        record = pipeline.ledger["stages"]["preflight"]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["terminal_status"], "completed")
        self.assertEqual(record["resume_disk_gate"]["status"], "failed")
        self.assertEqual(record["resume_disk_gate"]["terminal_status"], "insufficient_disk")

    def test_completed_summary_output_is_immutable(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.preflight_stage()
        pipeline.ledger.update(status="completed", complete=True)
        pipeline.summary_stage()
        before = json.loads((pipeline.output / "summary.json").read_text())
        self.assertEqual(before["pipeline_status"], "completed")
        with self.assertRaises(sj.PipelineError) as caught:
            self.fixture.pipeline()
        self.assertEqual(caught.exception.status, "terminal_output_immutable")
        after = json.loads((pipeline.output / "summary.json").read_text())
        self.assertEqual(after, before)

    def test_terminal_summary_is_not_rewritten(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.ledger.update(status="completed", complete=True)
        pipeline.summary_stage()
        victim = Path(self.temporary.name) / "victim.txt"
        victim.write_text("keep\n")
        markdown = pipeline.output / "summary.md"
        markdown.unlink()
        markdown.symlink_to(victim)

        pipeline.preflight_stage = types.MethodType(lambda _this: {}, pipeline)
        pipeline.baseline_stage = types.MethodType(lambda _this: {}, pipeline)
        pipeline.preparation_stage = types.MethodType(
            lambda _this: {"bindings": []}, pipeline)
        pipeline.s_campaign_stage = types.MethodType(
            lambda _this, _preparation: {"continue_to_j": True}, pipeline)
        pipeline.j_requests_stage = types.MethodType(
            lambda _this, _preparation, _s: {"requests": [], "selected_count": 0},
            pipeline)
        pipeline.postcheck_stage = types.MethodType(
            lambda _this, _j: {"checks": [], "validated_counterexamples": []},
            pipeline)

        with self.assertRaises(sj.PipelineError) as caught:
            pipeline.run()
        self.assertEqual(caught.exception.status, "terminal_output_immutable")
        self.assertEqual(victim.read_text(), "keep\n")
        self.assertTrue(markdown.is_symlink())

    def test_preflight_cost_includes_startup_normalization(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.startup_preflight = {
            "wall_seconds": 1.25, "cpu_seconds": 0.5,
            "phases": [{"phase": "input_and_revision_preflight",
                        "wall_seconds": 1.25, "cpu_seconds": 0.5}],
        }
        pipeline.preflight_stage()
        record = pipeline.ledger["stages"]["preflight"]
        self.assertGreaterEqual(record["wall_seconds"], 1.25)
        self.assertGreaterEqual(record["cpu_seconds"], 0.5)
        self.assertEqual(record["outputs"]["startup_preflight"],
                         pipeline.startup_preflight)

    def test_preserved_original_is_cache_cleanup_fallback(self) -> None:
        pipeline = self.fixture.pipeline()
        r1cs_bytes, sym_bytes = b"r1cs-fixture", b"sym-fixture"
        r1cs_sha = hashlib.sha256(r1cs_bytes).hexdigest()
        sym_sha = hashlib.sha256(sym_bytes).hexdigest()
        preserved = pipeline.output / "originals" / f"{r1cs_sha}-{sym_sha}"
        preserved.mkdir(parents=True)
        (preserved / "original.r1cs").write_bytes(r1cs_bytes)
        (preserved / "original.sym").write_bytes(sym_bytes)
        sj.atomic_json(preserved / "identity.json", {"schema": "zkfdo-sj-original-v1"})
        stage_root = pipeline.output / "stage-records/j_requests/attempts/0001"
        request_root = stage_root / "requests/00"
        request_root.mkdir(parents=True)
        pipeline.ledger["stages"]["j_requests"] = {"directory": str(stage_root)}
        request = {"index": 0, "directory": str(request_root)}
        found = pipeline._original_artifacts(
            request,
            {"entrypoint": {"r1cs_sha256": r1cs_sha, "sym_sha256": sym_sha}},
            {"original": {"original_r1cs": str(request_root / "cache/missing.r1cs"),
                          "original_sym": str(request_root / "cache/missing.sym")}})
        self.assertEqual(found["r1cs"]["sha256"], r1cs_sha)
        self.assertEqual(found["sym"]["sha256"], sym_sha)
        receipt = {"status": "removed", "path": str(request_root / "cache"),
                   "bytes_before": 10, "utc": sj.utc()}
        sj.atomic_json(request_root / "cache-cleanup.json", receipt)
        record: dict[str, object] = {}
        pipeline._cleanup_cache(request, record)
        self.assertEqual(record["cache_cleanup"]["resume_status"], "already_absent")
        checked = {**request, "cache_cleanup": record["cache_cleanup"]}
        pipeline._validate_cache_state(checked)
        (request_root / "cache").mkdir()
        with self.assertRaises(sj.PipelineError):
            pipeline._validate_cache_state(checked)
        (request_root / "cache").rmdir()
        (request_root / "cache-cleanup.json").write_text("{}\n")
        with self.assertRaises(sj.PipelineError):
            pipeline._validate_cache_state(checked)

    def test_original_storage_separates_equal_r1cs_with_different_sym(self) -> None:
        pipeline = self.fixture.pipeline()
        stage_root = pipeline.output / "stage-records/j_requests/attempts/0001"
        requests_root = stage_root / "requests"
        requests_root.mkdir(parents=True)
        pipeline.ledger["stages"]["j_requests"] = {"directory": str(stage_root)}
        preserved = []
        r1cs_bytes = b"same-r1cs"
        for index, sym_bytes in enumerate((b"first-sym", b"second-sym")):
            request_root = requests_root / f"{index:02d}"
            cache = request_root / "cache"
            cache.mkdir(parents=True)
            r1cs = cache / "original.r1cs"
            sym = cache / "original.sym"
            r1cs.write_bytes(r1cs_bytes)
            sym.write_bytes(sym_bytes)
            result = {"entrypoint": {"r1cs_sha256": sj.sha256(r1cs),
                                      "sym_sha256": sj.sha256(sym)}}
            probe = {"original": {"original_r1cs": str(r1cs), "original_sym": str(sym)}}
            preserved.append(pipeline._original_artifacts(
                {"index": index, "directory": str(request_root)}, result, probe))
        self.assertEqual(preserved[0]["r1cs"]["sha256"], preserved[1]["r1cs"]["sha256"])
        self.assertNotEqual(preserved[0]["sym"]["sha256"], preserved[1]["sym"]["sha256"])
        self.assertNotEqual(Path(preserved[0]["r1cs"]["path"]).parent,
                            Path(preserved[1]["r1cs"]["path"]).parent)

    def test_original_preservation_ignores_interrupted_temporary_copy(self) -> None:
        source = self.fixture.root / "source.r1cs"
        destination = self.fixture.output / "originals/set/original.r1cs"
        source.write_bytes(b"r1cs-fixture")
        destination.parent.mkdir(parents=True)
        stale = destination.with_name(destination.name + ".tmp")
        stale.write_bytes(b"interrupted-copy")

        receipt = sj.copy_verified(source, destination, sj.sha256(source))

        self.assertEqual(receipt["sha256"], sj.sha256(destination))
        self.assertEqual(destination.read_bytes(), source.read_bytes())
        self.assertEqual(stale.read_bytes(), b"interrupted-copy")
        self.assertEqual(
            list(destination.parent.glob(destination.name + ".tmp-*")), [])

    def test_postcheck_continues_after_pair_failure_and_retains_cache(self) -> None:
        pipeline = self.fixture.pipeline()
        stage_root = pipeline.output / "stage-records/j_requests/attempts/0001"
        request_root = stage_root / "requests/00"
        output = request_root / "out"
        cache = request_root / "cache"
        cache.mkdir(parents=True)
        (cache / "compile.tmp").write_text("temporary\n")
        output.mkdir()
        result_path = output / "result.json"
        probe_path = output / "site-signal-probe.json"
        result_path.write_text("{}\n")
        probe_path.write_text("{}\n")
        pipeline.ledger["stages"]["j_requests"] = {"directory": str(stage_root)}
        request = {
            "index": 0, "request_id": "candidate-00", "status": "completed",
            "terminal_status": "completed", "directory": str(request_root),
            "candidate": {"sha256": "1" * 64},
            "result": {"path": str(result_path), "sha256": sj.sha256(result_path)},
            "probe": {"path": str(probe_path), "sha256": sj.sha256(probe_path)},
        }
        r1cs = pipeline.output / "original.r1cs"
        sym = pipeline.output / "original.sym"
        r1cs.write_text("fixture\n")
        sym.write_text("fixture\n")
        pipeline._original_artifacts = types.MethodType(
            lambda _this, *_args: {
                "r1cs": {"path": str(r1cs), "sha256": sj.sha256(r1cs)},
                "sym": {"path": str(sym), "sha256": sj.sha256(sym)},
            }, pipeline)
        pairs = [
            {"kind": "entrypoint_violation", "class_index": 0, "label": "first",
             "comparator": output / "first-left.wtns", "deviated": output / "first-right.wtns",
             "expected_output_difference": True},
            {"kind": "entrypoint_violation", "class_index": 1, "label": "second",
             "comparator": output / "second-left.wtns", "deviated": output / "second-right.wtns",
             "expected_output_difference": True},
        ]
        for pair in pairs:
            pair["comparator"].write_text("left\n")
            pair["deviated"].write_text("right\n")
        pipeline._bound_pairs = types.MethodType(lambda _this, *_args: pairs, pipeline)
        seen: list[str] = []

        def check(_this: sj.Pipeline, _attempt: Path, label: str, _r1cs: Path,
                  comparator: Path, deviated: Path, *_args: object) -> dict[str, object]:
            seen.append(label)
            if label == "first":
                raise ValueError("fixture pair failure")
            return {
                "status": "validated", "passed": True,
                "comparator_check": {"witness": {
                    "path": str(comparator), "sha256": sj.sha256(comparator)}},
                "deviated_check": {"witness": {
                    "path": str(deviated), "sha256": sj.sha256(deviated)}},
                "comparison": {"same_full_input": True, "outputs_differ": True},
            }

        pipeline._check_pair = types.MethodType(check, pipeline)
        request_postcheck = pipeline._postcheck_request(request, pipeline.checkpoint)
        request["terminal_status"] = request_postcheck["check"]["terminal_status"]
        outputs = pipeline.postcheck_stage({"requests": [request]})
        self.assertEqual(seen, ["first", "second"])
        self.assertEqual(outputs["checks"][0]["pairs"][0]["status"],
                         "external_check_failed")
        self.assertEqual(outputs["checks"][0]["pairs"][1]["status"], "validated")
        self.assertEqual(outputs["checks"][0]["terminal_status"], "external_check_failed")
        self.assertEqual(outputs["validated_count"], 1)
        self.assertTrue(cache.exists())
        self.assertEqual(request["cache_cleanup"]["status"], "retained_for_recovery")

    def test_nonempty_unowned_output_is_rejected(self) -> None:
        self.fixture.output.mkdir()
        (self.fixture.output / "keep.txt").write_text("keep\n")
        with self.assertRaises(sj.PipelineError) as caught:
            self.fixture.pipeline()
        self.assertEqual(caught.exception.status, "output_ownership_failed")
        self.assertEqual((self.fixture.output / "keep.txt").read_text(), "keep\n")

    def test_cache_cleanup_rejects_symlinked_request_root(self) -> None:
        pipeline = self.fixture.pipeline()
        stage_root = pipeline.output / "stage-records/j_requests/attempts/0001"
        requests_root = stage_root / "requests"
        requests_root.mkdir(parents=True)
        outside = Path(self.temporary.name) / "outside"
        cache = outside / "cache"
        cache.mkdir(parents=True)
        victim = cache / "keep.txt"
        victim.write_text("keep\n")
        (requests_root / "00").symlink_to(outside, target_is_directory=True)
        pipeline.ledger["stages"]["j_requests"] = {"directory": str(stage_root)}
        request = {"index": 0, "directory": str(requests_root / "00")}
        with self.assertRaises(sj.PipelineError):
            pipeline._cleanup_cache(request, {})
        self.assertEqual(victim.read_text(), "keep\n")
        self.assertFalse((outside / "cache-cleanup.json").exists())

    def test_timeout_stops_real_child_and_grandchild_with_kill(self) -> None:
        ledger: dict[str, object] = {"commands": []}
        runner = sj.CommandRunner(ledger, lambda: None)
        pid_path = self.fixture.root / "processes.txt"
        child_code = (
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(60)")
        parent_code = (
            "import os,signal,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]]); "
            "open(sys.argv[1],'w').write(f'{os.getpid()} {child.pid}'); "
            "time.sleep(60)")
        with patch.object(sj, "PROCESS_TERM_GRACE_SECONDS", 0.1), \
                patch.object(sj, "PROCESS_KILL_GRACE_SECONDS", 2.0):
            row = runner.run(
                "fixture", "timeout",
                [sys.executable, "-c", parent_code, str(pid_path), child_code],
                self.fixture.root / "command", 0.3)
        self.assertEqual(row["status"], "timeout")
        self.assertTrue(row["termination"]["term_sent"])
        self.assertTrue(row["termination"]["kill_sent"])
        self.assertTrue(row["termination"]["group_gone"])
        pids = [int(value) for value in pid_path.read_text().split()]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            alive = []
            for pid in pids:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                alive.append(pid)
            if not alive:
                break
            time.sleep(0.02)
        self.assertEqual(alive, [])

    def test_j_request_checkpoint_survives_interrupt(self) -> None:
        pipeline = self.fixture.pipeline()
        configure_synthetic_j(pipeline, 1)

        def interrupt(*_args: object, **_kwargs: object) -> dict[str, object]:
            saved = json.loads((pipeline.output / "ledger.json").read_text())
            self.assertEqual(len(saved["stages"]["j_requests"]["outputs"]["requests"]), 1)
            raise KeyboardInterrupt()

        pipeline.runner.run = interrupt
        with self.assertRaises(KeyboardInterrupt):
            pipeline.j_requests_stage({}, {})
        saved = json.loads((pipeline.output / "ledger.json").read_text())
        request = saved["stages"]["j_requests"]["outputs"]["requests"][0]
        self.assertEqual(request["terminal_status"], "j_request_interrupted")
        self.assertEqual(request["cache_cleanup"]["status"], "retained_for_recovery")
        self.assertEqual(saved["candidate_states"][0]["state"], "in_progress_interrupted")

    def test_postcheck_cost_is_durable_before_outer_accounting(self) -> None:
        pipeline = self.fixture.pipeline("--j-total-seconds", "2", "--j-request-seconds", "1")
        candidates, baseline_sha = configure_synthetic_j(pipeline, 1)

        def run(_stage: str, label: str, argv_value: list[object], *_args: object,
                **_kwargs: object) -> dict[str, object]:
            request_path = Path(argv_value[2])
            output = Path(argv_value[4])
            output.mkdir()
            request_sha = sj.sha256(request_path)
            sj.atomic_json(output / "result.json", {
                "schema": "zkfdo-lifting-result-v2.8", "request_id": label,
                "request_sha256": request_sha,
                "candidate_sha256": candidates[0]["sha256"],
                "entrypoint": {"o0_r1cs_sha256": baseline_sha},
                "classes": [], "verdict_counts": {},
            })
            sj.atomic_json(output / "site-signal-probe.json", {
                "schema": "zkfdo-site-signal-probe-v1", "enabled": True,
                "request_sha256": request_sha,
                "candidate_sha256": candidates[0]["sha256"],
                "classes": [],
            })
            return {"status": "completed", "returncode": 0,
                    "wall_seconds": 0.25, "cpu_seconds": 0.0,
                    "argv_sha256": "a" * 64}

        def interrupt_postcheck(_this: sj.Pipeline, record: dict[str, object],
                                checkpoint: object) -> dict[str, object]:
            record["postcheck"] = {
                "wall_seconds": 12.0, "cpu_seconds": 3.0,
                "status": "completed", "terminal_status": "no_eligible_pairs",
            }
            checkpoint()
            raise KeyboardInterrupt()

        pipeline.runner.run = run
        pipeline._postcheck_request = types.MethodType(interrupt_postcheck, pipeline)
        with self.assertRaises(KeyboardInterrupt):
            pipeline.j_requests_stage({}, {})
        saved = json.loads((pipeline.output / "ledger.json").read_text())
        costs = saved["stages"]["j_requests"]["outputs"]["request_postcheck_costs"]
        self.assertEqual(costs, {"wall_seconds": 12.0, "cpu_seconds": 3.0})

    def test_supervisor_signal_between_commands_keeps_output_resumable(self) -> None:
        pipeline = self.fixture.pipeline()

        def interrupt(_this: sj.Pipeline) -> dict[str, object]:
            signal.raise_signal(signal.SIGINT)
            self.fail("signal handler must interrupt the stage")

        pipeline.preflight_stage = types.MethodType(interrupt, pipeline)
        self.assertFalse(pipeline.run())
        self.assertEqual(pipeline.ledger["status"], "partial:interrupted")
        self.assertFalse(pipeline.ledger["complete"])
        self.assertIn("SupervisorSignal", pipeline.ledger["error"])

    def test_reconcile_closes_running_request_and_partial_state_initialization(self) -> None:
        pipeline = self.fixture.pipeline("--j-total-seconds", "2", "--j-request-seconds", "1")
        candidates, _baseline_sha = configure_synthetic_j(pipeline, 2)
        states = pipeline.initialize_candidate_states(candidates[:1])
        request_root = (
            pipeline.output / "stage-records/j_requests/attempts/0001/requests/000000-0001")
        request_root.mkdir(parents=True)
        request = {
            "index": 0, "request_attempt": 1,
            "request_id": "candidate-000000-attempt-0001",
            "directory": str(request_root),
            "stage_attempt_directory": str(request_root.parents[1]),
            "status": "running", "terminal_status": "in_progress_interrupted",
        }
        states[0].setdefault("attempts", []).append(request)
        pipeline.ledger["commands"].append({
            "label": request["request_id"], "status": "running",
            "wall_seconds": 0.4, "start_epoch_seconds": time.time(),
            "timeout_seconds": 1.0, "argv_sha256": "a" * 64,
        })
        pipeline.reconcile_interrupted_consumption()
        self.assertEqual(request["status"], "interrupted")
        self.assertEqual(request["terminal_status"], "recovered_interrupted_request")
        self.assertAlmostEqual(request["budget_charge"]["seconds"], 0.4, places=1)
        self.assertEqual(request["cache_cleanup"]["status"], "retained_for_recovery")
        self.assertTrue(Path(request["terminal_receipt"]["path"]).is_file())
        self.assertEqual(states[0]["state"], "in_progress_interrupted")
        resumed = pipeline.initialize_candidate_states(candidates)
        self.assertEqual(len(resumed), 2)
        self.assertEqual(resumed[1]["state"], "pending_not_run")

    def test_orphan_budget_receipt_is_recovered_without_regrant(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.register_budget_allocation()
        event = {
            "schema": "zkfdo-sj-budget-event-v1", "kind": "consumption",
            "budget": "j", "utc": sj.utc(), "seconds": 0.75,
            "charge_id": "j-request:interrupted-request",
            "scope": "interrupted-request", "cumulative_consumed_seconds": 0.75,
            "reference": {"fixture": True},
        }
        pipeline._immutable_event("budget-events", event)
        recovered = self.fixture.pipeline()
        self.assertEqual(recovered.ledger["budget_accounting"]["j"]["consumed_seconds"], 0.75)
        self.assertEqual(len(recovered.ledger["budget_accounting"]["j"]["events"]), 2)
        recovered.register_budget_allocation()
        self.assertEqual(recovered.ledger["budget_accounting"]["j"]["allocated_seconds"],
                         recovered.args.j_total_seconds)

    def test_orphan_request_charge_reconnects_without_duplicate(self) -> None:
        pipeline = self.fixture.pipeline("--j-total-seconds", "2", "--j-request-seconds", "1")
        pipeline.register_budget_allocation()
        candidates, _baseline = configure_synthetic_j(pipeline, 1)
        state = pipeline.initialize_candidate_states(candidates)[0]
        request_root = (
            pipeline.output / "stage-records/j_requests/attempts/0001/requests/000000-0001")
        request_root.mkdir(parents=True)
        request_id = "candidate-000000-attempt-0001"
        request = {
            "index": 0, "request_attempt": 1, "request_id": request_id,
            "candidate": candidates[0], "directory": str(request_root),
            "stage_attempt_directory": str(request_root.parents[1]),
            "status": "running", "terminal_status": "in_progress_interrupted",
        }
        state.setdefault("attempts", []).append(request)
        pipeline.ledger["commands"].append({
            "label": request_id, "status": "running", "wall_seconds": 0.75,
            "start_epoch_seconds": time.time(), "timeout_seconds": 1.0,
            "argv_sha256": "a" * 64,
        })
        pipeline.checkpoint()
        pipeline._immutable_event("budget-events", {
            "schema": "zkfdo-sj-budget-event-v1", "kind": "consumption",
            "budget": "j", "utc": sj.utc(), "seconds": 0.75,
            "charge_id": f"j-request:{request_id}", "scope": request_id,
            "cumulative_consumed_seconds": 0.75,
            "reference": {"command_argv_sha256": "a" * 64},
        })
        recovered = self.fixture.pipeline(
            "--j-total-seconds", "2", "--j-request-seconds", "1")
        recovered.reconcile_interrupted_consumption()
        accounting = recovered.ledger["budget_accounting"]["j"]
        self.assertEqual(accounting["consumed_seconds"], 0.75)
        self.assertEqual(len([event for event in accounting["events"]
                              if event["kind"] == "consumption"]), 1)
        saved_request = recovered.ledger["candidate_states"][0]["attempts"][0]
        self.assertEqual(saved_request["budget_charge"]["charge_id"],
                         f"j-request:{request_id}")

    def test_orphan_s_charge_reconnects_without_duplicate(self) -> None:
        pipeline = self.fixture.pipeline("--s-budget-seconds", "2")
        pipeline.register_budget_allocation()
        pipeline.ledger["stages"]["s_campaign"] = {
            "stage": "s_campaign", "status": "running", "attempt": "0001",
            "started_epoch_seconds": time.time(),
        }
        pipeline.checkpoint()
        pipeline._immutable_event("budget-events", {
            "schema": "zkfdo-sj-budget-event-v1", "kind": "consumption",
            "budget": "s", "utc": sj.utc(), "seconds": 0.5,
            "charge_id": "s-stage:0001", "scope": "s_campaign",
            "cumulative_consumed_seconds": 0.5,
            "reference": {"stage_attempt": "0001"},
        })
        recovered = self.fixture.pipeline("--s-budget-seconds", "2")
        recovered.reconcile_interrupted_consumption()
        accounting = recovered.ledger["budget_accounting"]["s"]
        self.assertEqual(accounting["consumed_seconds"], 0.5)
        self.assertEqual(len([event for event in accounting["events"]
                              if event["kind"] == "consumption"]), 1)
        self.assertEqual(
            recovered.ledger["stages"]["s_campaign"]["budget_charge"]["charge_id"],
            "s-stage:0001")

    def test_orphan_extra_allocation_is_not_granted_twice(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.register_budget_allocation()
        base = pipeline.args.j_total_seconds
        pipeline._immutable_event("budget-events", {
            "schema": "zkfdo-sj-budget-event-v1", "kind": "extra_allocation",
            "budget": "j", "utc": sj.utc(), "seconds": 3.0,
            "cumulative_allocated_seconds": base + 3.0,
        })
        recovered = self.fixture.pipeline("--j-extra-total-seconds", "3")
        recovered.register_budget_allocation()
        accounting = recovered.ledger["budget_accounting"]["j"]
        self.assertEqual(accounting["allocated_seconds"], base + 3.0)
        self.assertEqual(len([event for event in accounting["events"]
                              if event["kind"] == "extra_allocation"]), 1)

    def test_orphan_stage_receipt_restores_completed_attempt(self) -> None:
        pipeline = self.fixture.pipeline()
        with sj.stage_attempt(pipeline, "preflight") as row:
            row["outputs"] = {"fixture": "complete"}
        ledger = json.loads((pipeline.output / "ledger.json").read_text())
        completed = ledger["stages"]["preflight"]
        ledger["stages"]["preflight"] = {
            key: completed[key] for key in (
                "stage", "status", "identity_sha256", "attempt", "directory",
                "started_utc", "started_epoch_seconds", "wall_seconds", "cpu_seconds")
        }
        ledger["stages"]["preflight"]["status"] = "running"
        ledger["stage_attempt_history"]["preflight"] = []
        sj.atomic_json(pipeline.output / "ledger.json", ledger)
        recovered = self.fixture.pipeline()
        self.assertEqual(recovered.ledger["stages"]["preflight"]["status"], "completed")
        self.assertEqual(recovered.ledger["stages"]["preflight"]["outputs"],
                         {"fixture": "complete"})
        self.assertEqual(len(recovered.ledger["stage_attempt_history"]["preflight"]), 1)

    def test_orphan_request_and_candidate_receipts_restore_terminal_state(self) -> None:
        pipeline = self.fixture.pipeline()
        candidates, _baseline_sha = configure_synthetic_j(pipeline, 1)
        state = pipeline.initialize_candidate_states(candidates)[0]
        request_root = (
            pipeline.output / "stage-records/j_requests/attempts/0001/requests/000000-0001")
        request_root.mkdir(parents=True)
        request = {
            "index": 0, "request_attempt": 1,
            "request_id": "candidate-000000-attempt-0001",
            "candidate": candidates[0], "directory": str(request_root),
            "stage_attempt_directory": str(request_root.parents[1]),
            "status": "failed", "terminal_status": "fixture_terminal",
            "reason": "fixture", "finished_utc": sj.utc(),
            "cache_cleanup": {"status": "retained_for_recovery"},
        }
        state.setdefault("attempts", []).append(request)
        state["latest_request"] = request
        pipeline._write_request_receipt(request)
        terminal_reference = request.pop("terminal_receipt")
        state_before = dict(state)
        terminal_event = pipeline.candidate_event(
            state, "judged", "fixture_terminal", request_id=request["request_id"],
            request_attempt=1, request_receipt=terminal_reference, reason="fixture")
        state.clear()
        state.update(state_before)
        state["attempts"] = [request]
        state["latest_request"] = request
        pipeline.checkpoint()
        pipeline.reconcile_interrupted_consumption()
        self.assertEqual(request["terminal_receipt"], terminal_reference)
        self.assertEqual(state["state"], "judged")
        self.assertEqual(state["terminal_status"], "fixture_terminal")
        self.assertEqual(state["events"][-1]["receipt"], terminal_event["receipt"])

    def test_completed_request_postchecks_before_next_request_interrupt(self) -> None:
        pipeline = self.fixture.pipeline()
        candidates, baseline_sha = configure_synthetic_j(pipeline, 2)
        events: list[str] = []

        def run(_stage: str, label: str, argv: list[object], *_args: object,
                **_kwargs: object) -> dict[str, object]:
            events.append("run-" + label)
            request_path = Path(argv[2])
            request_root = request_path.parent
            cache = request_root / "cache"
            cache.mkdir()
            (cache / "compile.tmp").write_text("temporary\n")
            if label.startswith("candidate-000001"):
                raise KeyboardInterrupt()
            output = request_root / "out"
            output.mkdir()
            request_sha = sj.sha256(request_path)
            sj.atomic_json(output / "result.json", {
                "schema": "zkfdo-lifting-result-v2.8", "request_id": label,
                "request_sha256": request_sha, "candidate_sha256": candidates[0]["sha256"],
                "entrypoint": {"o0_r1cs_sha256": baseline_sha},
            })
            sj.atomic_json(output / "site-signal-probe.json", {
                "schema": "zkfdo-site-signal-probe-v1", "enabled": True,
                "request_sha256": request_sha, "candidate_sha256": candidates[0]["sha256"],
            })
            return {"status": "completed", "returncode": 0, "wall_seconds": 0,
                    "cpu_seconds": 0, "argv_sha256": "0" * 64}

        def postcheck(this: sj.Pipeline, record: dict[str, object],
                      checkpoint: object) -> dict[str, object]:
            events.append("postcheck-" + str(record["request_id"]))
            this._cleanup_cache(record, record)
            record["postcheck"] = {"wall_seconds": 0.0, "cpu_seconds": 0.0,
                                   "status": "completed", "terminal_status": "validated"}
            checkpoint()
            return {"status": "completed", "check": {"terminal_status": "validated"}}

        pipeline.runner.run = run
        pipeline._postcheck_request = types.MethodType(postcheck, pipeline)
        with self.assertRaises(KeyboardInterrupt):
            pipeline.j_requests_stage({}, {})
        saved = json.loads((pipeline.output / "ledger.json").read_text())
        requests = saved["stages"]["j_requests"]["outputs"]["requests"]
        self.assertEqual(events, ["run-candidate-000000-attempt-0001",
                                  "postcheck-candidate-000000-attempt-0001",
                                  "run-candidate-000001-attempt-0001"])
        self.assertEqual(requests[0]["terminal_status"], "validated")
        self.assertEqual(requests[0]["cache_cleanup"]["status"], "removed")
        self.assertFalse((Path(requests[0]["directory"]) / "cache").exists())
        self.assertEqual(requests[1]["terminal_status"], "j_request_interrupted")
        self.assertEqual(requests[1]["cache_cleanup"]["status"], "retained_for_recovery")
        self.assertTrue((Path(requests[1]["directory"]) / "cache").is_dir())

    def test_j_total_budget_counts_commands_not_postchecks(self) -> None:
        pipeline = self.fixture.pipeline(
            "--j-request-seconds", "3", "--j-total-seconds", "4")
        candidates, baseline_sha = configure_synthetic_j(pipeline, 2)
        timeouts: list[float] = []

        def run(_stage: str, label: str, argv: list[object], _directory: Path,
                timeout: float, **_kwargs: object) -> dict[str, object]:
            timeouts.append(timeout)
            request_path = Path(argv[2])
            output = Path(argv[4])
            output.mkdir()
            request_sha = sj.sha256(request_path)
            candidate = candidates[int(label.split("-")[1])]
            sj.atomic_json(output / "result.json", {
                "schema": "zkfdo-lifting-result-v2.8", "request_id": label,
                "request_sha256": request_sha,
                "candidate_sha256": candidate["sha256"],
                "entrypoint": {"o0_r1cs_sha256": baseline_sha},
            })
            sj.atomic_json(output / "site-signal-probe.json", {
                "schema": "zkfdo-site-signal-probe-v1", "enabled": True,
                "request_sha256": request_sha,
                "candidate_sha256": candidate["sha256"],
            })
            return {"status": "completed", "returncode": 0,
                    "wall_seconds": timeout, "cpu_seconds": 0,
                    "argv_sha256": "0" * 64}

        def postcheck(this: sj.Pipeline, record: dict[str, object],
                      checkpoint: object) -> dict[str, object]:
            this._cleanup_cache(record, record)
            record["postcheck"] = {
                "wall_seconds": 100.0, "cpu_seconds": 0.0,
                "status": "completed", "terminal_status": "validated",
            }
            checkpoint()
            return {"status": "completed",
                    "check": {"terminal_status": "validated"}}

        pipeline.runner.run = run
        pipeline._postcheck_request = types.MethodType(postcheck, pipeline)
        outputs = pipeline.j_requests_stage({}, {})
        self.assertEqual(timeouts, [3.0, 1.0])
        self.assertEqual(outputs["j_command_wall_seconds"], 4.0)
        self.assertEqual(outputs["j_budget_remaining_seconds"], 0.0)
        self.assertEqual(outputs["request_postcheck_costs"]["wall_seconds"], 200.0)

    def test_o0_mismatch_is_terminal_and_keeps_cache(self) -> None:
        pipeline = self.fixture.pipeline("--j-total-seconds", "2", "--j-request-seconds", "1")
        candidates, _baseline_sha = configure_synthetic_j(pipeline, 1)

        def run(_stage: str, label: str, argv_value: list[object], *_args: object,
                **_kwargs: object) -> dict[str, object]:
            request_path = Path(argv_value[2])
            request_root = request_path.parent
            cache = request_root / "cache"
            cache.mkdir()
            (cache / "compile.tmp").write_text("preserve\n")
            output = Path(argv_value[4])
            output.mkdir()
            sj.atomic_json(output / "result.json", {
                "schema": "zkfdo-lifting-result-v2.8", "request_id": label,
                "request_sha256": sj.sha256(request_path),
                "candidate_sha256": candidates[0]["sha256"],
                "entrypoint": {"o0_r1cs_sha256": "b" * 64},
            })
            return {"status": "completed", "returncode": 0, "wall_seconds": 0.25,
                    "cpu_seconds": 0.0, "argv_sha256": "c" * 64}

        pipeline.runner.run = run
        pipeline._postcheck_request = types.MethodType(
            lambda *_args: self.fail("mismatched O0 evidence must not reach postcheck"), pipeline)
        outputs = pipeline.j_requests_stage({}, {})
        request = outputs["requests"][0]
        self.assertEqual(request["terminal_status"], "o0_r1cs_identity_mismatch")
        self.assertEqual(request["cache_cleanup"]["status"], "retained_for_recovery")
        self.assertTrue((Path(request["directory"]) / "cache/compile.tmp").is_file())
        self.assertEqual(pipeline.ledger["candidate_states"][0]["state"], "judged")

    def test_completed_command_with_missing_result_is_evidence_failure(self) -> None:
        pipeline = self.fixture.pipeline("--j-total-seconds", "2", "--j-request-seconds", "1")
        configure_synthetic_j(pipeline, 1)

        def run(_stage: str, _label: str, argv_value: list[object], *_args: object,
                **_kwargs: object) -> dict[str, object]:
            request_root = Path(argv_value[2]).parent
            cache = request_root / "cache"
            cache.mkdir()
            (cache / "compile.tmp").write_text("preserve\n")
            Path(argv_value[4]).mkdir()
            return {"status": "completed", "returncode": 0, "wall_seconds": 0.25,
                    "cpu_seconds": 0.0, "argv_sha256": "c" * 64}

        pipeline.runner.run = run
        outputs = pipeline.j_requests_stage({}, {})
        request = outputs["requests"][0]
        self.assertEqual(request["terminal_status"], "j_result_missing")
        self.assertIn("command completed", request["reason"])
        self.assertEqual(request["cache_cleanup"]["status"], "retained_for_recovery")
        self.assertTrue((Path(request["directory"]) / "cache/compile.tmp").is_file())

    def test_missing_comparator_sha_is_rejected_before_external_check(self) -> None:
        pipeline = self.fixture.pipeline()
        evidence = pipeline.output / "evidence"
        evidence.mkdir()
        r1cs = evidence / "original.r1cs"
        comparator = evidence / "honest.wtns"
        deviated = evidence / "deviated.wtns"
        for path in (r1cs, comparator, deviated):
            path.write_bytes(path.name.encode())
        with self.assertRaises(sj.PipelineError) as caught:
            pipeline._check_pair(
                evidence / "checks", "pair", r1cs, comparator, deviated, True,
                None, sj.sha256(deviated), evidence)
        self.assertEqual(caught.exception.status, "evidence_identity_failed")

    def test_pair_evidence_binds_comparator_at_j_completion(self) -> None:
        pipeline = self.fixture.pipeline()
        stage = pipeline.output / "stage-records/j_requests/attempts/0001"
        request_root = stage / "requests/000000-0001"
        output = request_root / "out"
        raw = output / "raw/site-000"
        raw.mkdir(parents=True)
        comparator = raw / "honest.wtns"
        deviated = raw / "deviated.wtns"
        comparator.write_bytes(b"honest")
        deviated.write_bytes(b"deviated")
        pipeline.ledger["stages"]["j_requests"] = {"directory": str(stage)}
        request = {
            "index": 0, "request_attempt": 1,
            "request_id": "candidate-000000-attempt-0001",
            "stage_attempt_directory": str(stage), "directory": str(request_root),
        }
        result = {"classes": [{
            "verdict": "entrypoint_violation",
            "evidence": {"deviated_wtns_sha256": sj.sha256(deviated)},
        }]}
        request["pair_evidence"] = pipeline._bind_pair_evidence(
            request, output, result, {"classes": []})
        pair = pipeline._bound_pairs(request)[0]
        self.assertEqual(pair["comparator_sha256"], sj.sha256(comparator))
        comparator.write_bytes(b"replaced")
        with self.assertRaises(sj.PipelineError) as caught:
            pipeline._check_pair(
                request_root / "checks", pair["label"], self.fixture.entrypoint,
                pair["comparator"], pair["deviated"], True,
                pair["comparator_sha256"], pair["deviated_sha256"], request_root)
        self.assertEqual(caught.exception.status, "evidence_identity_failed")

    def test_candidate_request_cap_is_cumulative_across_attempts(self) -> None:
        pipeline = self.fixture.pipeline("--j-total-seconds", "2", "--j-request-seconds", "1")
        candidates, _baseline_sha = configure_synthetic_j(pipeline, 1)
        states = pipeline.initialize_candidate_states(candidates)
        prior_charge = pipeline.charge_budget(
            "j", 0.75, "prior-attempt", charge_id="j-request:prior-attempt")
        states[0].setdefault("attempts", []).append({
            "request_id": "candidate-000000-attempt-0001",
            "request_attempt": 1, "status": "interrupted",
            "terminal_status": "j_disk_floor", "budget_charge": prior_charge,
        })
        pipeline.candidate_event(states[0], "in_progress_interrupted", "j_disk_floor")
        timeouts: list[float] = []

        def timeout(_stage: str, _label: str, _argv: list[object], _directory: Path,
                    seconds: float, **_kwargs: object) -> dict[str, object]:
            timeouts.append(seconds)
            return {"status": "timeout", "returncode": -9, "wall_seconds": seconds,
                    "cpu_seconds": 0.0, "argv_sha256": "a" * 64}

        pipeline.runner.run = timeout
        outputs = pipeline.j_requests_stage({}, {})
        self.assertEqual(timeouts, [0.25])
        self.assertEqual(states[0]["state"], "judged")
        self.assertEqual(states[0]["terminal_status"], "j_timeout")
        self.assertEqual(outputs["pipeline_status"], "completed")

    def test_preservation_failure_keeps_request_cache(self) -> None:
        pipeline = self.fixture.pipeline()
        stage = pipeline.output / "stage-records/j_requests/attempts/0001"
        request_root = stage / "requests/000000-0001"
        output = request_root / "out"
        cache = request_root / "cache"
        output.mkdir(parents=True)
        cache.mkdir()
        (cache / "compile.tmp").write_text("keep\n")
        result_path = output / "result.json"
        probe_path = output / "site-signal-probe.json"
        sj.atomic_json(result_path, {})
        sj.atomic_json(probe_path, {})
        pipeline.ledger["stages"]["j_requests"] = {"directory": str(stage)}
        request = {
            "index": 0, "request_attempt": 1, "request_id": "candidate-000000-attempt-0001",
            "stage_attempt_directory": str(stage), "directory": str(request_root),
            "status": "completed", "candidate": {"sha256": "1" * 64},
            "result": {"path": str(result_path), "sha256": sj.sha256(result_path)},
            "probe": {"path": str(probe_path), "sha256": sj.sha256(probe_path)},
        }
        pipeline._original_artifacts = types.MethodType(
            lambda *_args: (_ for _ in ()).throw(
                sj.PipelineError("original_artifacts_missing", "fixture")), pipeline)
        checked = pipeline._postcheck_request(request, pipeline.checkpoint)
        self.assertEqual(checked["check"]["terminal_status"], "original_artifacts_missing")
        self.assertEqual(request["cache_cleanup"]["status"], "retained_for_recovery")
        self.assertTrue((cache / "compile.tmp").is_file())

    def test_no_eligible_pairs_has_distinct_terminal_status(self) -> None:
        pipeline = self.fixture.pipeline()
        stage = pipeline.output / "stage-records/j_requests/attempts/0001"
        request_root = stage / "requests/000000-0001"
        output = request_root / "out"
        cache = request_root / "cache"
        output.mkdir(parents=True)
        cache.mkdir()
        result_path = output / "result.json"
        probe_path = output / "site-signal-probe.json"
        sj.atomic_json(result_path, {"classes": []})
        sj.atomic_json(probe_path, {"classes": []})
        r1cs = pipeline.output / "preserved.r1cs"
        sym = pipeline.output / "preserved.sym"
        r1cs.write_bytes(b"r1cs")
        sym.write_bytes(b"sym")
        pipeline.ledger["stages"]["j_requests"] = {"directory": str(stage)}
        request = {
            "index": 0, "request_attempt": 1, "request_id": "candidate-000000-attempt-0001",
            "stage_attempt_directory": str(stage), "directory": str(request_root),
            "status": "completed", "candidate": {"sha256": "1" * 64},
            "result": {"path": str(result_path), "sha256": sj.sha256(result_path)},
            "probe": {"path": str(probe_path), "sha256": sj.sha256(probe_path)},
        }
        pipeline._original_artifacts = types.MethodType(
            lambda *_args: {
                "r1cs": {"path": str(r1cs), "sha256": sj.sha256(r1cs)},
                "sym": {"path": str(sym), "sha256": sj.sha256(sym)},
            }, pipeline)
        pipeline._bound_pairs = types.MethodType(lambda _this, *_args: [], pipeline)
        checked = pipeline._postcheck_request(request, pipeline.checkpoint)
        self.assertEqual(checked["check"]["terminal_status"], "no_eligible_pairs")
        self.assertEqual(request["cache_cleanup"]["status"], "removed")
        self.assertFalse(cache.exists())

    def test_output_lock_rejects_concurrent_process_and_records_owner(self) -> None:
        lock = sj.OutputLock(self.fixture.output).acquire()
        try:
            owner = json.loads((self.fixture.output / ".sj-pipeline.lock").read_text())
            self.assertEqual(owner["status"], "active")
            self.assertEqual(owner["pid"], os.getpid())
            code = (
                "import sys; "
                f"sys.path.insert(0, {str(SCRIPTS)!r}); "
                "import run_sj_pipeline_v1 as s; "
                "\ntry:\n s.OutputLock(s.Path(sys.argv[1])).acquire()\n"
                "except s.PipelineError as e:\n print(e.status)\n sys.exit(0)\n"
                "sys.exit(3)")
            second = subprocess.run(
                [sys.executable, "-B", "-c", code, str(self.fixture.output)],
                cwd=sj.ROOT, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout.strip(), "output_locked")
        finally:
            lock.release()
        history = self.fixture.output / ".sj-pipeline-lock-history"
        self.assertTrue(any(history.glob("*.json")))

    def test_output_lock_does_not_follow_lock_symlink(self) -> None:
        self.fixture.output.mkdir()
        outside = self.fixture.root / "outside-lock-target"
        outside.write_text("unchanged\n")
        (self.fixture.output / ".sj-pipeline.lock").symlink_to(outside)
        with self.assertRaises(sj.PipelineError) as caught:
            sj.OutputLock(self.fixture.output).acquire()
        self.assertEqual(caught.exception.status, "output_ownership_failed")
        self.assertEqual(outside.read_text(), "unchanged\n")

    def test_executable_sha_is_rechecked_immediately_before_launch(self) -> None:
        expected = sj.sha256(self.fixture.stub)
        ledger: dict[str, object] = {"commands": []}
        runner = sj.CommandRunner(
            ledger, lambda: None, {str(self.fixture.stub.resolve()): expected})
        self.fixture.stub.write_text("#!/bin/sh\nexit 9\n")
        self.fixture.stub.chmod(0o755)
        with self.assertRaises(sj.PipelineError) as caught:
            runner.run("fixture", "changed", [self.fixture.stub],
                       self.fixture.root / "changed-command", 1)
        self.assertEqual(caught.exception.status, "executable_identity_failed")
        self.assertFalse(self.fixture.marker.exists())
        self.assertFalse(ledger["commands"][0]["executable"]["verified"])

    def test_nested_j_executable_sha_is_rechecked_before_request(self) -> None:
        pipeline = self.fixture.pipeline()
        self.fixture.stub.write_text("#!/bin/sh\nexit 7\n")
        self.fixture.stub.chmod(0o755)
        with self.assertRaises(sj.PipelineError) as caught:
            pipeline.verify_tool_identities(("circom", "node", "snarkjs", "z3"))
        self.assertEqual(caught.exception.status, "executable_identity_failed")

    def test_j_selection_rejects_sha_or_version_mismatch(self) -> None:
        wrong_version = self.fixture.root / "j-wrong-version.sh"
        wrong_version.write_text("#!/bin/sh\nprintf 'zkfdo-j-v27 0.1.0\\n'\n")
        wrong_version.chmod(0o755)
        with self.assertRaises(ValueError):
            sj.select_j_tool({"J_v28": {
                "path": str(wrong_version), "sha256": sj.sha256(wrong_version)}})
        with self.assertRaises(ValueError):
            sj.select_j_tool({"J_v28": {
                "path": str(self.fixture.j_stub), "sha256": "0" * 64}})

    def test_real_prepare_wrapper_absolute_include_is_pinned_or_rejected(self) -> None:
        fixture = sj.ROOT / (
            "runs/n7-a-sj-cold-2026-10-29-v2/2026100601/tree/prepared/"
            "prepare-fb6f4184-d77b-4939-99e9-81edd5e215a2/targets/0013/sources/"
            "discovery/b84f2974-89af-4716-a8e5-fc722ecb67fb/wrappers/0012-Subtract/"
            "target.circom")
        self.assertTrue(fixture.is_file())
        original = fixture.read_text()
        literal = sj.INCLUDE.search(sj.strip_comments(original)).group(1)
        target = Path(literal)
        self.assertTrue(target.is_absolute() and target.is_file())
        pinned = self.fixture.root / "absolute-include-fixture"
        wrapper = pinned / "prepared/wrappers/target.circom"
        included = pinned / "project/src/subtractTensor.circom"
        wrapper.parent.mkdir(parents=True)
        included.parent.mkdir(parents=True)
        included.write_bytes(target.read_bytes())
        wrapper.write_text(original.replace(literal, str(included)))
        layout = sj.source_closure_layout(wrapper, [wrapper.parent, included.parent], pinned)
        self.assertEqual(layout["absolute_include_count"], 1)
        self.assertTrue(Path(layout["includes"][0]["resolved"]).is_relative_to(pinned))
        outside_wrapper = pinned / "prepared/wrappers/outside.circom"
        outside_wrapper.write_text(original)
        with self.assertRaises(sj.PipelineError) as caught:
            sj.source_closure_layout(outside_wrapper, [outside_wrapper.parent], pinned)
        self.assertEqual(caught.exception.status, "unsupported:include_layout")

    def test_pre_j_check_rejects_changed_normalized_input(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.write_source_snapshot()
        pipeline.base_input.write_text('{"x":"2"}\n')
        with self.assertRaises(sj.PipelineError) as caught:
            pipeline._pre_j_identity({}, "candidate-000000-attempt-0001")
        self.assertEqual(caught.exception.status, "base_input_identity_failed")

    def test_probe_contract_checks_identity_policy_and_class_fields(self) -> None:
        pipeline = self.fixture.pipeline()
        pipeline.write_source_snapshot()
        request_sha = "1" * 64
        candidate = {"sha256": "2" * 64}
        r1cs_sha, sym_sha = "3" * 64, "4" * 64
        base_sha = sj.sha256(pipeline.base_input)
        shared = {
            "request_sha256": request_sha, "candidate_sha256": candidate["sha256"],
            "budget_seconds": 900, "value_policy": sj.PROBE_VALUE_POLICY,
            "contract": sj.PROBE_CONTRACT, "predicate": sj.PROBE_PREDICATE,
            "base_input_sha256": base_sha,
        }
        result = {"entrypoint": {"r1cs_sha256": r1cs_sha, "sym_sha256": sym_sha},
                  "classes": [{"pattern": "main.t[*]", "representative": "main.t[0]",
                               "verdict": "unknown"}]}
        probe = {
            "schema": "zkfdo-site-signal-probe-v1", "enabled": True,
            "budget_seconds": 900, "classes_policy": "unknown_or_excluded_in_context",
            "value_policy": sj.PROBE_VALUE_POLICY, "contract": sj.PROBE_CONTRACT,
            "repair_attempts": 0, "request_sha256": request_sha,
            "candidate_sha256": candidate["sha256"], "identity": dict(shared),
            "original": {"original_r1cs_sha256": r1cs_sha,
                         "original_sym_sha256": sym_sha},
            "classes": [{
                "class_index": 0, "pattern": "main.t[*]", "representative": "main.t[0]",
                "existing_verdict": "unknown", "identity": dict(shared),
                "attempts": [{"repair_attempts": 0, "status": "condition_unmet",
                              "identity": dict(shared)}],
            }],
        }
        self.assertEqual(
            pipeline._validate_probe_contract(request_sha, candidate, result, probe)["status"],
            "validated")
        mutations = [
            lambda value: value.__setitem__("budget_seconds", 899),
            lambda value: value.__setitem__("classes_policy", "all"),
            lambda value: value["identity"].__setitem__("base_input_sha256", "5" * 64),
            lambda value: value["original"].__setitem__("original_r1cs_sha256", "5" * 64),
            lambda value: value["original"].__setitem__("original_sym_sha256", "5" * 64),
            lambda value: value.__setitem__("contract", "different"),
            lambda value: value.__setitem__("value_policy", "different"),
            lambda value: value["classes"][0].__setitem__("class_index", 1),
            lambda value: value["classes"][0].__setitem__("pattern", "different"),
            lambda value: value["classes"][0]["identity"].__setitem__(
                "base_input_sha256", "5" * 64),
            lambda value: value["classes"][0]["attempts"][0].__setitem__("repair_attempts", 1),
            lambda value: value.__setitem__("classes", []),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate.__code__.co_firstlineno):
                changed = json.loads(json.dumps(probe))
                mutate(changed)
                with self.assertRaises(sj.PipelineError):
                    pipeline._validate_probe_contract(request_sha, candidate, result, changed)

        positive = json.loads(json.dumps(probe))
        attempt = positive["classes"][0]["attempts"][0]
        attempt["status"] = "positive"
        attempt["evidence"] = {
            "comparator_wtns_sha256": "6" * 64,
            "deviated_wtns_sha256": "7" * 64,
            "original_r1cs_sha256": r1cs_sha,
            "original_sym_sha256": sym_sha,
        }
        self.assertEqual(
            pipeline._validate_probe_contract(request_sha, candidate, result, positive)["status"],
            "validated")
        for missing in ("comparator_wtns_sha256", "deviated_wtns_sha256"):
            with self.subTest(missing=missing):
                changed = json.loads(json.dumps(positive))
                del changed["classes"][0]["attempts"][0]["evidence"][missing]
                with self.assertRaises(sj.PipelineError):
                    pipeline._validate_probe_contract(request_sha, candidate, result, changed)

    def test_corpus_layer_is_required_and_output_symlink_ancestor_is_rejected(self) -> None:
        argv = self.fixture.argv()
        index = argv.index("--corpus-layer")
        del argv[index:index + 2]
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            sj.parser().parse_args(argv)
        argv = self.fixture.argv()
        argv[argv.index("development")] = "evaluation"
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            sj.parser().parse_args(argv)
        real = self.fixture.root / "real-output-parent"
        real.mkdir()
        linked = self.fixture.root / "linked-output-parent"
        linked.symlink_to(real, target_is_directory=True)
        with self.assertRaises(sj.PipelineError) as caught:
            sj.OutputLock(linked / "run").acquire()
        self.assertEqual(caught.exception.status, "output_ownership_failed")

    def test_pair_comparison_uses_full_input_and_top_output(self) -> None:
        r1cs = Path(self.temporary.name) / "small.r1cs"
        left = Path(self.temporary.name) / "left.wtns"
        right = Path(self.temporary.name) / "right.wtns"
        width, prime, wires = 4, 97, 6
        header = (struct.pack("<I", width) + prime.to_bytes(width, "little")
                  + struct.pack("<IIIIQI", wires, 1, 1, 1, wires, 0))
        r1cs.write_bytes(b"r1cs" + struct.pack("<II", 1, 1)
                         + struct.pack("<IQ", 1, len(header)) + header)

        def witness(path: Path, values: list[int]) -> None:
            wtns_header = (struct.pack("<I", width) + prime.to_bytes(width, "little")
                           + struct.pack("<I", len(values)))
            data = b"".join(value.to_bytes(width, "little") for value in values)
            path.write_bytes(b"wtns" + struct.pack("<II", 2, 2)
                             + struct.pack("<IQ", 1, len(wtns_header)) + wtns_header
                             + struct.pack("<IQ", 2, len(data)) + data)

        witness(left, [1, 5, 7, 8, 0, 0])
        witness(right, [1, 6, 7, 8, 9, 10])
        compared = sj.compare_pair(r1cs, left, right)
        self.assertTrue(compared["same_full_input"])
        self.assertTrue(compared["outputs_differ"])
        self.assertEqual(compared["differing_output_wires"], [1])


if __name__ == "__main__":
    unittest.main()
