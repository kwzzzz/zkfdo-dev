import importlib.util
from pathlib import Path
import signal
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("e02_guard", ROOT / "scripts/guard_e02_runner_overlap.py")
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class E02RunnerGuardTest(unittest.TestCase):
    def test_only_main_descendants_are_paused_and_tail_is_untouched(self):
        rows = {
            10: {"parent": 1, "command": "authorized main"},
            11: {"parent": 10, "command": "compiler"},
            12: {"parent": 11, "command": "compiler child"},
            20: {"parent": 1, "command": "tail"},
            21: {"parent": 20, "command": "tail compiler"},
        }
        with patch.object(GUARD, "processes", return_value=rows), patch.object(GUARD.os, "kill") as kill:
            stopped = GUARD.pause_tree(10, "authorized main")
        self.assertEqual(stopped, [10, 11, 12])
        self.assertEqual([call.args for call in kill.call_args_list],
                         [(10, signal.SIGSTOP), (11, signal.SIGSTOP), (12, signal.SIGSTOP)])

    def test_reused_pid_with_different_command_is_not_signalled(self):
        rows = {10: {"parent": 1, "command": "unrelated process"}}
        with patch.object(GUARD, "processes", return_value=rows), patch.object(GUARD.os, "kill") as kill:
            self.assertEqual(GUARD.pause_tree(10, "authorized main"), [])
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
