#!/usr/bin/env python3
"""Check owned disk budgets immediately before each external Circom invocation.

This is a launch guard, not a filesystem quota. An already running compilation
can overshoot; the supervising process also samples and stops the whole tree.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import time
import uuid

from zkfdo_runtime_v1 import DiskBudget, atomic_json
from zkfdo_tools_v1 import verify_tool


def signature(path):
    stat = Path(path).stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def create_gate(directory, compiler_entry, disk_budgets, deadline):
    """Return a fresh launcher, pinned to a verified compiler and owned budgets."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    verify_tool(compiler_entry)
    compiler = str(Path(compiler_entry['path']).resolve())
    state = {'schema': 'zkfdo-compile-gate-v1', 'compiler': compiler,
             'compiler_sha256': compiler_entry['sha256'],
             'compiler_stat': signature(compiler), 'deadline_monotonic': deadline,
             'disk_budgets': [{'root': str(b.root), 'max_bytes': b.max_bytes,
                              'min_free_bytes': b.min_free_bytes} for b in disk_budgets]}
    atomic_json(directory / 'config.json', state)
    launcher = directory / 'circom'
    command = [sys.executable, '-B', str(Path(__file__).resolve()),
               '--state', str(directory / 'config.json'), '--']
    launcher.write_text('#!/bin/sh\nexec ' + ' '.join(map(shlex.quote, command)) + ' "$@"\n')
    launcher.chmod(0o700)
    return launcher


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    arguments = args.command[1:] if args.command[:1] == ['--'] else args.command
    state = json.loads(args.state.read_text())
    record = {'schema': 'zkfdo-compile-launch-v1', 'pid': os.getpid(),
              'argv': [state['compiler'], *arguments], 'started_utc_ns': time.time_ns(),
              'compiler_sha256': state['compiler_sha256'], 'status': 'checking'}
    receipt = args.state.parent / ('launch-' + uuid.uuid4().hex + '.json')
    try:
        if signature(state['compiler']) != state['compiler_stat']:
            raise RuntimeError('verified compiler changed before launch')
        if time.monotonic() >= state['deadline_monotonic']:
            raise RuntimeError('work deadline reached before compilation')
        record['disk_budgets'] = []
        for spec in state['disk_budgets']:
            budget = DiskBudget(**spec)
            record['disk_budgets'].append(budget.sample())
        if any(row['stop_reason'] for row in record['disk_budgets']):
            raise RuntimeError('disk budget reached before compilation')
        record['status'] = 'dispatching'
        atomic_json(receipt, record)
        os.execv(state['compiler'], record['argv'])
    except (OSError, RuntimeError, ValueError) as error:
        record.update(status='blocked', error=f'{type(error).__name__}: {error}')
        atomic_json(receipt, record)
        print(record['error'], file=sys.stderr)
        return 125


if __name__ == '__main__':
    raise SystemExit(main())
