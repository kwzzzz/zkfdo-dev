import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import zkfdo_compile_gate_v2 as gate


class CompileGateV2Tests(unittest.TestCase):
    def test_deadline_crossed_during_durable_receipt_blocks_dispatch(self):
        with tempfile.TemporaryDirectory(prefix='zkfdo-gate-final-') as directory:
            root = Path(directory).resolve()
            compiler = root / 'compiler'
            compiler.write_text('#!/bin/sh\nexit 0\n')
            state = root / 'config.json'
            state.write_text(json.dumps({'compiler': str(compiler), 'compiler_sha256': 'a' * 64,
                'compiler_stat': gate.signature(compiler), 'deadline_monotonic': 10,
                'disk_budgets': []}))
            with patch.object(gate.time, 'monotonic', side_effect=[9, 11]), patch.object(gate.os, 'execv') as dispatch:
                result = gate.main(['--state', str(state), '--', '--version'])
            self.assertEqual(result, 125)
            dispatch.assert_not_called()
            receipt = json.loads(next(root.glob('launch-*.json')).read_text())
            self.assertEqual(receipt['status'], 'blocked')
            self.assertIn('deadline', receipt['error'])


if __name__ == '__main__':
    unittest.main()
