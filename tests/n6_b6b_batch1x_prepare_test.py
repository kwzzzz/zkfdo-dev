"""Synthetic, value-free checks for the B6b prepare and future pilot gates."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_b6b_batch1x_prepare as batch  # noqa: E402
import n6_b6b_j_adapter as adapter  # noqa: E402


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


class Batch1xPrepareTest(unittest.TestCase):
    def test_stage_reuses_completed_artifact_without_action(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(batch, "OUT", Path(temporary)):
                first = batch.stage("one", lambda: {"proof": "ok"}, lambda _: None)
                self.assertEqual(first["status"], "completed")
                again = batch.stage("one", lambda: self.fail("reran stage"),
                                    lambda saved: self.assertEqual(saved["proof"], "ok"))
                self.assertEqual(again["exit_code"], 0)

    def test_failed_stage_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(batch, "OUT", Path(temporary)):
                with self.assertRaisesRegex(ValueError, "stopped"):
                    batch.stage("failed", lambda: (_ for _ in ()).throw(ValueError("stopped")),
                                lambda _: None)
                saved = batch.read_json(batch.state_path("failed"))
                self.assertEqual(saved["status"], "failed")
                with self.assertRaisesRegex(ValueError, "preserve"):
                    batch.stage("failed", lambda: self.fail("reran"), lambda _: None)

    def test_static_failure_blocks_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = root / "index.json"
            report = root / "static.json"
            failed_index = root / "preparation-failed.json"
            rows = [{"queue_order": order, "revision_id": "revision",
                     "preparation_failure": None} for order in range(107)]
            checks = [{"queue_order": order, "revision_id": "revision",
                       "status": "preparation_failed" if order == 25 else "passed",
                       "reasons": ["workspace_overlaps_source_root"] if order == 25 else []}
                      for order in range(107)]
            write(index, {"status": "verified", "request_count": 107,
                          "preparation_counts": {"ready": 107}, "requests": rows})
            write(report, {"index_path": str(index.resolve()),
                           "index_sha256": batch.sha256(index),
                           "request_count": 107,
                           "per_engine": {"v1": {"passed": 106},
                                          "v2.2": {"passed": 106}},
                           "row_checks": checks,
                           "all_passed": False})
            with mock.patch.object(batch, "INDEX_V1", index), \
                    mock.patch.object(batch, "STATIC", report), \
                    mock.patch.object(batch, "STATIC_REVISED", root / "static-revised.json"), \
                    mock.patch.object(batch, "static_stage_name", return_value="static"), \
                    mock.patch.object(batch, "INDEX_FAILED", failed_index):
                with self.assertRaisesRegex(ValueError, "static preparation failure"):
                    batch.static_preflight()
                annotated = batch.read_json(failed_index)
                self.assertEqual(annotated["status"], "preparation_failed")
                self.assertEqual(len(annotated["requests"]), 107)
                self.assertIsNone(annotated["requests"][24]["preparation_failure"])
                self.assertIn("workspace_overlaps_source_root",
                              annotated["requests"][25]["preparation_failure"])
                self.assertEqual(annotated["preparation_counts"],
                                 {"ready": 106, "preparation_failed": 1})

    def test_static_command_routes_three_external_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = root / "index.json"
            report = root / "static.json"
            write(index, {"requests": []})

            def fake_command(_stage: str, command: list[str]) -> int:
                self.assertIn("--source-staging-root", command)
                self.assertIn("--workspace-root", command)
                self.assertIn("--instance-root", command)
                self.assertIn("--cache-root", command)
                write(report, {"index_path": str(index.resolve()),
                               "index_sha256": batch.sha256(index),
                               "request_count": 107,
                               "per_engine": {"v1": {"passed": 107},
                                              "v2.2": {"passed": 107}},
                               "all_passed": True})
                return 0

            with mock.patch.object(batch, "INDEX_V1", index), \
                    mock.patch.object(batch, "STATIC", report), \
                    mock.patch.object(batch, "STATIC_REVISED", root / "static-revised.json"), \
                    mock.patch.object(batch, "static_stage_name", return_value="static"), \
                    mock.patch.object(batch, "INDEX_FAILED", root / "failed.json"), \
                    mock.patch.object(batch, "logged_command", fake_command):
                self.assertTrue(batch.static_preflight()["all_passed"])

    def test_pilot_command_is_explicit_and_routes_external_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = root / "index.json"
            write(index, {"requests": []})
            cache = root / "cache"
            output = root / "pilot.noindex"
            with mock.patch.object(batch, "OUT", root), \
                    mock.patch.object(batch, "CACHE", cache), \
                    mock.patch.object(batch, "INDEX_V1", index), \
                    mock.patch.object(batch, "STATIC", root / "static.json"), \
                    mock.patch.object(batch.b6, "base_index", return_value={}), \
                    mock.patch.object(batch.b6, "review_gate", return_value=set()), \
                    mock.patch.object(batch, "verify_static_gate"), \
                    mock.patch.object(batch, "r1cs_gate", return_value={}), \
                    mock.patch.object(batch, "logged_command", return_value=0) as command, \
                    mock.patch.object(batch, "pilot_state", return_value={
                        "output": str(output), "state_sha256": "x"}):
                result = batch.pilot("v1", index)
                self.assertEqual(result["engine"], "v1")
                args = command.call_args.args[1]
                self.assertEqual(args[args.index("--stage") + 1], "pilot")
                self.assertEqual(args[args.index("--workspace-root") + 1],
                                 str(batch.WORKSPACES))
                self.assertEqual(args[args.index("--instance-root") + 1],
                                 str(batch.STORES))
                self.assertEqual(args[args.index("--action") + 1], "execute")

    def test_full_command_routes_external_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = root / "index.json"
            write(index, {"requests": []})
            with mock.patch.object(batch, "OUT", root), \
                    mock.patch.object(batch, "CACHE", root), \
                    mock.patch.object(batch, "INDEX_V1", index), \
                    mock.patch.object(batch, "INDEX_FAILED", root / "failed.json"), \
                    mock.patch.object(batch.b6, "base_index", return_value={}), \
                    mock.patch.object(batch.b6, "results_review_gate"), \
                    mock.patch.object(batch, "r1cs_gate", return_value={}), \
                    mock.patch.object(batch, "verify_static_gate"), \
                    mock.patch.object(batch, "logged_command", return_value=0) as command, \
                    mock.patch.object(batch, "full_state", return_value={
                        "output": str(root / "full-v1.noindex"), "request_count": 107}):
                result = batch.full("v1", index)
                self.assertEqual(result["engine"], "v1")
                args = command.call_args.args[1]
                self.assertEqual(args[args.index("--stage") + 1], "validate")
                self.assertEqual(args[args.index("--workspace-root") + 1],
                                 str(batch.WORKSPACES))
                self.assertEqual(args[args.index("--instance-root") + 1],
                                 str(batch.STORES))
                self.assertEqual(args[args.index("--action") + 1], "execute")

    def test_full_adapter_installs_external_runtime_before_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "full.noindex"
            index = root / "index.json"
            workspace = root / "workspaces"
            instances = root / "stores"
            args = ["--stage", "validate", "--engine", "v1",
                    "--workspace-root", str(workspace), "--instance-root", str(instances),
                    "--cache-root", str(root / "cache"),
                    "--action", "execute", "--output", str(output),
                    "--index", str(index)]
            with mock.patch.object(adapter.staged, "install"), \
                    mock.patch.object(adapter, "guarded_execution") as guard, \
                    mock.patch.object(adapter, "verify_execution_paths"), \
                    mock.patch.object(adapter.b5, "main", return_value=0) as b5_main, \
                    mock.patch("n6_b6b_runtime_paths.install_full") as install:
                self.assertEqual(adapter.main(args), 0)
                guard.assert_called_once_with("v1", index, full=True)
                install.assert_called_once_with(output, workspace, instances)
                forwarded = b5_main.call_args.args[0]
                self.assertNotIn("--workspace-root", forwarded)
                self.assertNotIn("--instance-root", forwarded)

    def test_direct_full_adapter_stops_before_runtime_when_gate_fails(self) -> None:
        args = ["--stage", "validate", "--engine", "v1",
                "--workspace-root", "/tmp/workspaces", "--instance-root", "/tmp/stores",
                "--action", "execute", "--output", "/tmp/full.noindex",
                "--index", "/tmp/index.json"]
        with mock.patch.object(adapter.staged, "install"), \
                mock.patch.object(adapter, "guarded_execution",
                                  side_effect=ValueError("gate incomplete")), \
                mock.patch.object(adapter.b5, "main") as b5_main, \
                mock.patch("n6_b6b_runtime_paths.install_full") as install:
            with self.assertRaisesRegex(ValueError, "gate incomplete"):
                adapter.main(args)
            b5_main.assert_not_called()
            install.assert_not_called()

    def test_direct_adapter_requires_preflighted_j_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            expected = {"staging_root": root / "external/source-staging",
                        "workspace_root": root / "external/hint-workspaces",
                        "instance_root": root / "external/instance-stores",
                        "cache_root": root / "external/cache/pilot-v1",
                        "output": root / "runs/pilot-v1.noindex"}
            with mock.patch.object(batch, "STAGING", expected["staging_root"]), \
                    mock.patch.object(batch, "WORKSPACES", expected["workspace_root"]), \
                    mock.patch.object(batch, "STORES", expected["instance_root"]), \
                    mock.patch.object(batch, "CACHE", root / "external/cache"), \
                    mock.patch.object(batch, "OUT", root / "runs"):
                adapter.verify_execution_paths("pilot", "v1", **expected)
                wrong = {**expected,
                         "workspace_root": expected["staging_root"] / "inside-source"}
                with self.assertRaisesRegex(ValueError, "hint workspace differs"):
                    adapter.verify_execution_paths("pilot", "v1", **wrong)
                wrong = {**expected,
                         "cache_root": expected["staging_root"] / "cache"}
                with self.assertRaisesRegex(ValueError, "cache differs"):
                    adapter.verify_execution_paths("pilot", "v1", **wrong)


if __name__ == "__main__":
    unittest.main()
