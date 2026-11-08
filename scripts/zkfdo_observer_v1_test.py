import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from zkfdo_observer_v1 import DiskBudget, BudgetExceeded, ObservationError, ObservationCosts


class ObserverTests(unittest.TestCase):
    def test_request_receipt_inherits_effective_parent_intervals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request = root / 'request'
            request.mkdir()
            task = DiskBudget(root, 100, tree_interval_seconds=100,
                              free_interval_seconds=.25)
            sub = DiskBudget(request, 50, parent=task)
            row = sub.sample()
            self.assertEqual(row['tree_interval_seconds'], 100)
            self.assertEqual(row['free_interval_seconds'], .25)
            self.assertEqual(task.samples, 1)

    def test_helper_cpu_is_opt_in_and_separate_from_parent_cpu(self):
        costs = ObservationCosts()
        usage = [SimpleNamespace(ru_utime=1.0, ru_stime=.5),
                 SimpleNamespace(ru_utime=3.0, ru_stime=1.0)]
        with patch('zkfdo_observer_v1.resource.getrusage', side_effect=usage) as measured:
            with costs.measure('memory_snapshot', helper_children=True):
                pass
            with costs.measure('reap'):
                pass
        self.assertEqual(measured.call_count, 2)
        row = costs.snapshot()['memory_snapshot']
        self.assertEqual(row['helper_cpu_seconds'], 2.5)
        self.assertEqual(row['cpu_seconds'], row['parent_cpu_seconds'] + 2.5)
        self.assertEqual(costs.snapshot()['reap']['helper_cpu_seconds'], 0)

    def test_shared_walk_preserves_independent_hardlink_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request = root / 'request'
            request.mkdir()
            (root / 'outside').write_bytes(b'x' * 10)
            os.link(root / 'outside', request / 'inside')
            task = DiskBudget(root, 100)
            sub = DiskBudget(request, 100, parent=task)
            row = task.sample()
            self.assertEqual(row['current_bytes'], 10)
            self.assertEqual(row['request']['current_bytes'], 10)
            sub.check()
            self.assertEqual(task.samples, 1)
            self.assertEqual(task.costs.rows['tree']['calls'], 1)

    def test_interval_and_forced_final_detect_short_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            budget = DiskBudget(root, 10, tree_interval_seconds=100)
            budget.check()
            (root / 'file').write_bytes(b'x' * 11)
            budget.check()
            self.assertEqual(budget.samples, 1)
            with self.assertRaises(BudgetExceeded):
                budget.check(force=True)

    def test_request_overflow_and_fast_free_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subdir = root / 'request'
            subdir.mkdir()
            budget = DiskBudget(root, 100)
            DiskBudget(subdir, 5, parent=budget)
            (subdir / 'file').write_bytes(b'123456')
            with self.assertRaisesRegex(BudgetExceeded, 'request_'):
                budget.check()
            fresh = DiskBudget(root, 100, min_free_bytes=1)
            fake = type('Space', (), {'f_bavail': 0, 'f_frsize': 4096})()
            with patch('zkfdo_observer_v1.os.statvfs', return_value=fake):
                with self.assertRaisesRegex(BudgetExceeded, 'minimum_free'):
                    fresh.check()

    def test_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'link').symlink_to('/tmp')
            with self.assertRaises(ObservationError):
                DiskBudget(root, 100).check()


if __name__ == '__main__':
    unittest.main()
