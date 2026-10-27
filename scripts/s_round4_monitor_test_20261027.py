#!/usr/bin/env python3
"""Safety checks without a compiler, judge, or signals to real processes."""
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import s_round4_monitor_20261027 as monitor


class Checks(unittest.TestCase):
    def test_foreign_parent_is_never_signalled(self):
        folder = MagicMock()
        child = folder.__truediv__.return_value
        child.exists.return_value = True
        child.read_text.return_value = json.dumps({"pid": 999998, "ppid": 999997})
        process = MagicMock(pid=999996)
        with patch.object(monitor.os, "killpg") as kill:
            with self.assertRaisesRegex(RuntimeError, "ownership"):
                monitor.stop_owned(process, folder)
            kill.assert_not_called()

    def test_only_recorded_child_group_is_signalled(self):
        folder = MagicMock()
        child = folder.__truediv__.return_value
        child.exists.return_value = True
        child.read_text.return_value = json.dumps({"pid": 999998, "ppid": 999996})
        process = MagicMock(pid=999996)
        with patch.object(monitor.os, "killpg") as kill:
            monitor.stop_owned(process, folder)
            kill.assert_called_once_with(999998, monitor.signal.SIGTERM)
        process.terminate.assert_not_called()

    def test_missing_target_measurement_blocks_cargo(self):
        with patch.object(monitor, "capture", return_value={"returncode": 1, "stderr": "Operation not permitted"}):
            with self.assertRaisesRegex(RuntimeError, "cargo refused"):
                monitor.target_size()

    def test_protected_or_external_output_rejected(self):
        for path in [Path("/tmp/compile"), monitor.ROOT / "runs/n6-a-remeasure-2026-10-25.noindex/x"]:
            with self.assertRaises(ValueError):
                monitor.owned(path)

    def test_compiler_sample_below_cache_floor_blocks_start(self):
        with patch.object(monitor.os, "getpriority", return_value=19), \
             patch.object(monitor, "free_bytes", side_effect=[21 * monitor.GIB, 581 * monitor.GIB]):
            with self.assertRaisesRegex(RuntimeError, "582 GiB"):
                monitor.gate()


if __name__ == "__main__":
    unittest.main()
