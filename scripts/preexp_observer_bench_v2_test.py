import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import preexp_observer_bench_v2 as bench


class ObserverBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='observer-bench-test-')
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'fixtures'
        (self.source / '1').mkdir(parents=True)
        (self.source / '1' / 'small').write_bytes(b'x' * 16)
        (self.source / 'large.bin').write_bytes(b'x' * 16)

    def tearDown(self):
        self.temporary.cleanup()

    def test_observer_failure_after_spawn_terminates_and_reaps_child(self):
        original = bench.DiskBudget.check
        calls = 0

        def fail_during_copy(budget, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('injected observer failure')
            return original(budget, **kwargs)

        with patch.object(bench.DiskBudget, 'check', fail_during_copy):
            row = bench.run_one(self.root, self.source, 1, 0, 'tree_1s',
                                child_code='import time;time.sleep(30)')
        self.assertEqual(row['stop_reason'], 'observation_or_work_failed')
        self.assertTrue(row['cleanup_complete'])
        self.assertFalse(row['measurement_valid'])
        self.assertIsNotNone(row['returncode'])
        with self.assertRaises(ProcessLookupError):
            os.kill(row['child_pid'], 0)
        saved = json.loads((self.root/'n1-r0-tree_1s.json').read_text())
        self.assertTrue(saved['cleanup_complete'])
        self.assertEqual({b['scope'] for b in saved['disk_budgets']}, {'task','request'})

    def test_child_payload_clock_is_separate_from_parent_wait_upper_bound(self):
        code = """import time,json
w,c=time.monotonic(),time.process_time()
time.sleep(.025)
print(json.dumps({'sha256':'a'*64,'payload_wall_seconds':time.monotonic()-w,
                  'payload_cpu_seconds':time.process_time()-c}),flush=True)
"""
        row = bench.run_one(self.root, self.source, 1, 0, 'baseline', child_code=code)
        self.assertTrue(row['measurement_valid'])
        self.assertGreaterEqual(row['child_payload_wall_seconds'], .025)
        self.assertGreater(row['child_completion_upper_bound_seconds'], row['child_payload_wall_seconds'])
        self.assertEqual(row['tree_scans'], 0)
        self.assertEqual(row['disk_budgets'], [])
        self.assertEqual(row['callsites']['copy_before_write']['calls'], 1)
        self.assertEqual(row['callsites']['final']['forced_calls'], 1)


if __name__ == '__main__':
    unittest.main()
