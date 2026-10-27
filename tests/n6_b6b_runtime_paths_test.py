#!/usr/bin/env python3
"""Value-free checks for B6b's external J artifact layout."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_b6b_runtime_paths as paths  # noqa: E402
import run_n6_j1 as runner  # noqa: E402


class RuntimePathsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.volume = self.root / "volume"
        self.volume.mkdir()
        self.external = self.volume / "n6-b6b-batch1x"
        self.external.mkdir()
        self.output = self.root / "runs" / "new-pilot"
        self.output.mkdir(parents=True)
        for name, value in (("VOLUME", self.volume), ("EXTERNAL", self.external)):
            binding = patch.object(paths, name, value)
            binding.start()
            self.addCleanup(binding.stop)
        mounted = patch.object(paths.os.path, "ismount", return_value=True)
        mounted.start()
        self.addCleanup(mounted.stop)
        free = patch.object(runner, "disk_free", return_value=runner.MIN_FREE_BYTES + 1)
        free.start()
        self.addCleanup(free.stop)

    def test_workspace_and_store_are_outside_runs(self) -> None:
        workspaces = self.external / "hint-workspaces"
        stores = self.external / "instance-stores"
        lift = self.output / "requests" / "00-000009" / "lift"
        external_output = paths.external_lift_output(lift, self.output, workspaces)
        self.assertFalse(external_output.exists())
        (external_output / "raw").mkdir(parents=True)
        (external_output / "result.json").write_text("{}\n")
        paths.publish_lift_output(external_output, lift, self.output, workspaces)
        self.assertTrue((lift / "raw").is_symlink())
        self.assertTrue((lift / "raw").resolve().is_relative_to(workspaces))
        self.assertEqual((lift / "result.json").read_text(), "{}\n")
        self.assertFalse((external_output / "result.json").exists())
        store = self.output / "revisions" / "01" / "store"
        routed = paths.external_store(store, self.output, stores)
        self.assertTrue(routed.is_relative_to(stores))
        self.assertFalse(routed.is_relative_to(self.output))

    def test_rejects_existing_workspace_and_wrong_store_root(self) -> None:
        workspaces = self.external / "hint-workspaces"
        lift = self.output / "requests" / "00-000009" / "lift"
        target = workspaces / lift.relative_to(self.output)
        target.mkdir(parents=True)
        with self.assertRaisesRegex(runner.RunnerError, "already exists"):
            paths.external_lift_output(lift, self.output, workspaces)
        with self.assertRaisesRegex(runner.RunnerError, "below runs output"):
            paths.external_store(self.root / "other" / "store", self.output,
                                 self.external / "instance-stores")

    def test_external_root_requires_mount_and_space(self) -> None:
        with patch.object(paths.os.path, "ismount", return_value=False):
            with self.assertRaisesRegex(runner.RunnerError, "not mounted"):
                paths.require_external_root(self.external / "hint-workspaces")
        with patch.object(runner, "disk_free", return_value=runner.MIN_FREE_BYTES - 1):
            with self.assertRaisesRegex(runner.RunnerError, "below 40 GiB"):
                paths.require_external_root(self.external / "hint-workspaces")

    def test_full_runner_uses_fresh_external_output_and_publishes_result(self) -> None:
        workspaces = self.external / "hint-workspaces"
        stores = self.external / "instance-stores"
        cache = self.external / "cache"
        cache.mkdir()
        attempt = self.output / "main" / "0001" / "requests" / "000009" / "attempt-0001"
        attempt.parent.mkdir(parents=True)
        original_lift, original_atomic = runner.run_lift, runner.atomic_json
        self.addCleanup(setattr, runner, "run_lift", original_lift)
        self.addCleanup(setattr, runner, "atomic_json", original_atomic)

        def fake_engine(command: list[str], stdout: Path, stderr: Path) -> dict:
            engine_output = Path(command[command.index("--output") + 1])
            self.assertFalse(engine_output.exists())
            self.assertTrue(engine_output.is_relative_to(workspaces))
            self.assertTrue(Path(command[command.index("--instance-store") + 1])
                            .is_relative_to(stores))
            (engine_output / "raw").mkdir(parents=True)
            (engine_output / "result.json").write_text("{}\n")
            stdout.write_text("")
            stderr.write_text("")
            return {"exit_code": 0, "wall_seconds": 1.0, "max_rss_bytes": 1}

        with patch.object(runner, "run_with_rusage", side_effect=fake_engine):
            paths.install_full(self.output, workspaces, stores)
            metrics = runner.run_lift({"request": str(self.root / "request.json")},
                                      attempt, cache,
                                      self.output / "main" / "0001" / "store", 1,
                                      "wait4")
        self.assertEqual(metrics["exit_code"], 0)
        self.assertEqual((attempt / "result.json").read_text(), "{}\n")
        self.assertTrue((attempt / "raw").is_symlink())


if __name__ == "__main__":
    unittest.main()
