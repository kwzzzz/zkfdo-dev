import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from zkfdo_compile_gate_v1 import create_gate
from zkfdo_runtime_v1 import DiskBudget


class CompileGateTests(unittest.TestCase):
    def test_compile_boundary_blocks_next_compile_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            compiler = root / 'fake compiler'
            compiler.write_text('#!/bin/sh\nprintf called >> "$1"\n')
            compiler.chmod(0o700)
            entry = {'path': str(compiler), 'sha256': hashlib.sha256(compiler.read_bytes()).hexdigest()}
            work = root / 'work'; work.mkdir()
            gate = create_gate(root / 'gate', entry, (DiskBudget(work, 4096),), time.monotonic()+10)
            marker = root / 'marker'
            result = subprocess.run([str(gate), str(marker)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            (work / 'large').write_bytes(b'x'*5000)
            result = subprocess.run([str(gate), str(marker)], capture_output=True)
            self.assertEqual(result.returncode, 125, result.stderr)
            self.assertEqual(marker.read_text(), 'called')
            self.assertEqual((work / 'large').stat().st_size, 5000)
            records = [json.loads(p.read_text()) for p in (root/'gate').glob('launch-*.json')]
            self.assertEqual(sorted(r['status'] for r in records), ['blocked', 'dispatching'])

    def test_deadline_and_compiler_replacement_are_fail_closed(self):
        for change in ('deadline', 'compiler'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                compiler = root/'compiler';compiler.write_text('#!/bin/sh\nexit 0\n');compiler.chmod(0o700)
                entry = {'path': str(compiler), 'sha256': hashlib.sha256(compiler.read_bytes()).hexdigest()}
                gate = create_gate(root/'gate', entry, (), time.monotonic()+(-1 if change=='deadline' else 10))
                if change == 'compiler':
                    compiler.write_text('#!/bin/sh\nexit 1\n')
                result = subprocess.run([str(gate)], capture_output=True)
                self.assertEqual(result.returncode, 125, result.stderr)


if __name__ == '__main__':
    unittest.main()
