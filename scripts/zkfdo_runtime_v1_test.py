#!/usr/bin/env python3
"""Small process fixtures, never run zkFuzz or candidate judging."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import zkfdo_runtime_v1 as runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zkfdo-runtime-test-")
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def test_atomic_replace_preserves_previous_json_on_failure(self):
        path = self.root / "receipt.json"
        runtime.atomic_json(path, {"old": True})
        with patch.object(runtime.os, "replace", side_effect=OSError("injected rename error")):
            with self.assertRaises(OSError):
                runtime.atomic_json(path, {"new": True})
        self.assertEqual(json.loads(path.read_text()), {"old": True})
        self.assertFalse(list(self.root.glob(".*.tmp")))

    def test_success_and_exit_failure_have_final_ledger(self):
        for code in (0, 7):
            out = self.root / str(code)
            receipt = runtime.run_command([sys.executable, "-c", f"raise SystemExit({code})"], out, 2)
            self.assertEqual(receipt["returncode"], code)
            self.assertTrue(receipt["cleanup_complete"])
            self.assertTrue(json.loads((out / "ledger.json").read_text())["complete"])

    def test_same_outer_inner_budget_reaps_detached_fuzzer_and_keeps_ledgers(self):
        # The old topology: campaign -> a new-session fuzzer, with equal budgets.
        worker = self.root / "worker.py"
        worker.write_text(
            "import json,os,signal,subprocess,sys,time\n"
            "from pathlib import Path\n"
            "p=Path(sys.argv[1]); child=subprocess.Popen([sys.executable,'-c',"
            "'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'],start_new_session=True)\n"
            "(p/'fuzzer.pid').write_text(str(child.pid))\n"
            "def save(status):\n"
            " t=p/'worker-ledger.tmp';t.write_text(json.dumps({'status':status}));os.replace(t,p/'worker-ledger.json')\n"
            "def stop(*_):\n"
            " save('interrupted');raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM,stop);save('running');time.sleep(.6);save('complete');child.wait()\n"
        )
        receipt = runtime.run_command([sys.executable, str(worker), str(self.root)], self.root / "run", .6,
                                      cleanup_grace_seconds=.15, cleanup_cap_seconds=3)
        self.assertEqual(receipt["status"], "timeout")
        self.assertTrue(receipt["cleanup_complete"], receipt)
        self.assertEqual(receipt["remaining_processes"], [])
        pid = int((self.root / "fuzzer.pid").read_text())
        rows = runtime.process_snapshot()
        self.assertFalse(pid in rows and not rows[pid]["state"].startswith("Z"))
        self.assertIn(json.loads((self.root / "worker-ledger.json").read_text())["status"], ("interrupted", "complete"))
        self.assertTrue(json.loads((self.root / "run/ledger.json").read_text())["complete"])

    def test_signal_to_supervisor_preserves_receipt_and_reaps_group(self):
        out = self.root / "signal"
        p = subprocess.Popen([sys.executable, "-B", runtime.__file__, "--output", str(out), "--seconds", "20",
                              "--max-disk-bytes", str(16 * 2**20), "--min-free-bytes", "0",
                              "--", sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                path = out / "receipt.json"
                if path.exists() and json.loads(path.read_text())["status"] == "running":
                    break
                time.sleep(.02)
            else:
                self.fail("supervisor did not reach running state")
            p.send_signal(signal.SIGTERM)
            p.communicate(timeout=5)
            r = json.loads((out / "receipt.json").read_text())
            self.assertEqual(r["status"], "interrupted")
            self.assertIn(signal.SIGTERM, r["received_signals"])
            self.assertTrue(r["cleanup_complete"])
        finally:
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=5)

    def test_monitor_exception_still_cleans_up(self):
        def fail(_receipt):
            raise RuntimeError("injected observer failure")
        receipt = runtime.run_command([sys.executable, "-c", "import time;time.sleep(60)"],
                                      self.root / "failure", 2, tick=fail)
        self.assertEqual(receipt["status"], "supervisor_error")
        self.assertTrue(receipt["cleanup_complete"])

    def test_isolation_is_applied_before_exec_and_final_oom_is_not_success(self):
        marker = self.root / 'executed'
        test = self
        class Isolation:
            configuration = {'enabled': True}
            def attach(self, _pid):
                test.assertFalse(marker.exists())
                return {'status': 'attached'}
            def sample(self):
                return {'enabled': True, 'remaining_pids': [], 'cpu_seconds': .125,
                        'memory_events': {'max': 1, 'oom': 1, 'oom_kill': 1}}
            def finalize(self):
                return {'cleanup_complete': True, 'sample': self.sample()}
            def kill(self):
                return {'status': 'kill_requested'}
        with patch.object(runtime.platform_layer, 'prepare_isolation', return_value=Isolation()):
            result = runtime.run_command([sys.executable, '-c',
                'from pathlib import Path;import sys;Path(sys.argv[1]).write_text("ran")', str(marker)],
                self.root/'isolated', 2)
        self.assertTrue(marker.exists())
        self.assertEqual(result['status'], 'memory_limit')
        self.assertEqual(result['cpu_seconds'], .125)
        self.assertTrue(result['cleanup_complete'])

    def test_isolation_sample_and_kill_failures_do_not_skip_detached_group_cleanup(self):
        # Bind the detached child's identity while its parent still exists, then
        # let the direct child exit. Only the owned detached group remains live.
        pid_file = self.root / "detached.pid"
        ready = self.root / "detached.ready"
        release = self.root / "parent.release"
        worker = self.root / "detach-worker.py"
        child_program = ("import signal,sys,time;from pathlib import Path;"
                         "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                         "Path(sys.argv[1]).touch();time.sleep(10)")
        worker.write_text(
            "import subprocess,sys,time\nfrom pathlib import Path\n"
            f"child=subprocess.Popen([sys.executable,'-c',{child_program!r},{str(ready)!r}],start_new_session=True)\n"
            f"Path({str(pid_file)!r}).write_text(str(child.pid))\n"
            f"release=Path({str(release)!r});end=time.monotonic()+3\n"
            "while not release.exists() and time.monotonic()<end: time.sleep(.01)\n"
        )
        latest = {}
        child_identity = None
        def snapshot():
            nonlocal latest, child_identity
            latest = runtime.process_snapshot()
            if pid_file.exists() and ready.exists():
                pid = int(pid_file.read_text())
                if pid in latest and latest[pid]["pgid"] == pid:
                    child_identity = runtime.identity(latest[pid])
                    release.touch()
            return latest
        class Isolation:
            configuration = {"enabled": True, "source": "injected fixture"}
            pid = None
            kill_calls = 0
            def attach(self, pid):
                self.pid = pid
                return {"status": "attached"}
            def sample(self):
                row = latest.get(self.pid)
                if child_identity is not None and (row is None or row["state"].startswith("Z")):
                    raise runtime.ObservationError("injected cgroup sample failure after parent exit")
                return {"enabled": True, "remaining_pids": []}
            def kill(self):
                self.kill_calls += 1
                raise runtime.ObservationError("injected cgroup.kill unavailable")
            def finalize(self):
                raise runtime.ObservationError("injected final cgroup observation unavailable")
        isolation = Isolation()
        try:
            with patch.object(runtime.platform_layer, "prepare_isolation", return_value=isolation):
                receipt = runtime.run_command([sys.executable, str(worker)], self.root / "isolation-errors", 2,
                    snapshot=snapshot, cleanup_grace_seconds=.1, cleanup_cap_seconds=.6, poll_seconds=.02)
            self.assertIsNotNone(child_identity, receipt)
            child_pid = child_identity[0]
            self.assertGreater(isolation.kill_calls, 0, receipt)
            self.assertTrue(any(row["pgid"] == child_pid and row["signal"] == signal.SIGKILL
                                for row in receipt["signals_sent"]), receipt)
            self.assertEqual(receipt["remaining_processes"], [])
            self.assertTrue(any("isolation cleanup sample" in error for error in receipt["observation_errors"]))
            self.assertTrue(any("isolation cleanup kill" in error for error in receipt["observation_errors"]))
            # Process cleanup succeeds, but failed cgroup observation stays invalid.
            self.assertFalse(receipt["cleanup_complete"])
            self.assertFalse(receipt["measurement_valid"])
            rows = runtime.process_snapshot()
            self.assertFalse(child_pid in rows and not rows[child_pid]["state"].startswith("Z"))
            self.assertTrue(json.loads((self.root / "isolation-errors/ledger.json").read_text())["complete"])
        finally:
            # A regressed implementation must not leave this fixture running.
            if child_identity is not None:
                row = runtime.process_snapshot().get(child_identity[0])
                if row and runtime.identity(row) == child_identity and not row["state"].startswith("Z"):
                    try:
                        os.killpg(row["pgid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_disk_overflow_on_short_lived_command_is_not_reported_as_success(self):
        budget = runtime.DiskBudget(self.root/'job', 32 * 1024)
        target = self.root/'job'/'payload'
        result = runtime.run_command([sys.executable, '-c',
            'from pathlib import Path;import sys;Path(sys.argv[1]).write_bytes(b"x"*65536)', str(target)],
            self.root/'job'/'process', 2, disk_budgets=(budget,))
        self.assertEqual(result['status'], 'disk_limit')
        self.assertEqual(target.stat().st_size, 65536)
        self.assertTrue(result['cleanup_complete'])

    def test_persistence_failure_does_not_skip_process_cleanup(self):
        original = runtime.atomic_json
        broken = False
        def tick(_):
            nonlocal broken
            broken = True
            raise RuntimeError("begin shutdown while storage is unavailable")
        def write(path, data):
            if broken:
                raise OSError("injected ENOSPC")
            original(path, data)
        with patch.object(runtime, "atomic_json", side_effect=write):
            receipt = runtime.run_command([sys.executable, "-c", "import time;time.sleep(60)"],
                                          self.root / "write-error", 2, tick=tick)
        self.assertEqual(receipt["status"], "persistence_failed")
        self.assertTrue(receipt["cleanup_complete"])
        self.assertTrue(receipt["persistence_errors"])

    def test_disk_limit_keeps_files_and_blocks_next_compile(self):
        job = self.root / "job"
        job.mkdir()
        budget = runtime.DiskBudget(job, 32 * 1024)
        payload = job / "payload"
        program = "from pathlib import Path;import time;Path(%r).write_bytes(b'x'*131072);time.sleep(60)" % str(payload)
        first = runtime.run_command([sys.executable, "-c", program], job / "first", 2, disk_budgets=(budget,))
        self.assertEqual(first["status"], "disk_limit", first)
        self.assertTrue(first["cleanup_complete"])
        self.assertTrue(payload.exists())
        self.assertGreaterEqual(first["disk_budgets"][0]["peak_bytes"], 131072)
        marker = job / "second-compiler-started"
        second = runtime.run_command([sys.executable, "-c", "from pathlib import Path;Path(%r).touch()" % str(marker)],
                                     job / "second", 2, disk_budgets=(budget,))
        self.assertEqual(second["status"], "disk_limit")
        self.assertNotIn("pid", second)
        self.assertFalse(marker.exists())

    def test_task_and_request_disk_caps_are_both_recorded(self):
        request = self.root / "request"
        request.mkdir()
        (request / "data").write_bytes(b"x" * 1024)
        task = runtime.DiskBudget(self.root, 100000)
        one = runtime.DiskBudget(request, 100)
        r = runtime.run_command([sys.executable, "-c", "pass"], request / "run", 1, disk_budgets=(task, one))
        self.assertEqual(r["status"], "disk_limit")
        self.assertEqual(len(r["disk_budgets"]), 2)
        self.assertIsNone(r["disk_budgets"][0]["stop_reason"])
        self.assertEqual(r["disk_budgets"][1]["stop_reason"], "max_disk_bytes_exceeded")

    def test_whole_runs_scan_is_refused(self):
        with self.assertRaises(ValueError):
            runtime.DiskBudget(self.root / "runs", 1024)

    def test_sleep_observation_invalidates_and_cleans_child(self):
        original = runtime.platform_layer.clock_snapshot
        calls = 0
        def clock():
            nonlocal calls
            calls += 1
            result = original()
            if calls > 1:
                result["suspend_aware_ns"] += 5_000_000_000
                result["realtime_ns"] += 5_000_000_000
            return result
        with patch.object(runtime.platform_layer, "clock_snapshot", side_effect=clock):
            r = runtime.run_command([sys.executable, "-c", "import time;time.sleep(60)"], self.root / "sleep", 2)
        self.assertEqual(r["status"], "invalid_sleep", r)
        self.assertFalse(r["measurement_valid"])
        self.assertTrue(r["cleanup_complete"])

    def test_missing_swap_is_error_not_zero(self):
        with patch.object(runtime.platform_layer, "memory_snapshot", side_effect=runtime.ObservationError("missing swap")):
            r = runtime.run_command([sys.executable, "-c", "pass"], self.root / "swap", 2)
        self.assertEqual(r["status"], "resource_monitor_failure")
        self.assertFalse(r["measurement_valid"])
        self.assertNotIn("pid", r)
        self.assertNotIn("memory_before", r)


if __name__ == "__main__":
    unittest.main()
