#!/usr/bin/env python3
"""Ensure the B6b pilot wrapper preserves the B5 new-cache gate."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_b5_format_pilot as original  # noqa: E402
import n6_b6b_format_pilot as pilot  # noqa: E402
import n6_b6b_runtime_paths as paths  # noqa: E402
import run_n6_j1 as runner  # noqa: E402


class FormatPilotTest(unittest.TestCase):
    def test_cache_root_is_still_new_when_original_gate_runs(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        external = root / "external"
        external.mkdir()
        cache = external / "cache" / "pilot-v2.2"
        cache.parent.mkdir()
        output = root / "runs" / "pilot-v2.2.noindex"
        output.parent.mkdir()
        observed: list[bool] = []

        def fake_gate(*args: object) -> None:
            observed.append(not cache.exists())

        argv = ["--index", str(root / "index.json"),
                "--index-sha256", "a" * 64,
                "--base-index", str(root / "base.json"),
                "--base-index-sha256", "b" * 64,
                "--selection", str(root / "selection.json"),
                "--cache-root", str(cache),
                "--workspace-root", str(external / "hint-workspaces"),
                "--instance-root", str(external / "instance-stores"),
                "--output", str(output), "--action", "execute"]
        original_lift = original.run_lift
        original_libraries = runner.preflight_libraries
        self.addCleanup(setattr, original, "run_lift", original_lift)
        self.addCleanup(setattr, runner, "preflight_libraries", original_libraries)
        with patch.object(paths, "require_external_root", side_effect=lambda p: p), \
                patch.object(pilot.adapter, "engine_for_prepared_index", return_value="v1"), \
                patch.object(pilot.adapter, "guarded_execution"), \
                patch.object(pilot.adapter, "verify_execution_paths"), \
                patch.object(original, "run_format_pilot", side_effect=fake_gate):
            self.assertEqual(pilot.main(argv), 0)
        self.assertEqual(observed, [True])


if __name__ == "__main__":
    unittest.main()
