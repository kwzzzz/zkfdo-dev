#!/usr/bin/env python3
"""Synthetic adapter checks: no saved run data or judging process is accessed."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import n6_a_rqc_input_audit_20261026 as audit


class MemoryFiles:
    """A deliberately closed file map; unknown reads fail instead of reaching disk."""

    def __init__(self, entries=None, times=None, symlinks=()):
        self.data = {Path(k): (v if isinstance(v, bytes) else json.dumps(v).encode())
                     for k, v in (entries or {}).items()}
        self.times = {Path(k): v for k, v in (times or {}).items()}
        self.symlinks = {Path(p) for p in symlinks}
        self.directories = set()
        self.reads = []

    def resolve(self, path, **_kwargs):
        return path if path.is_absolute() else Path('/synthetic') / path

    def read(self, path):
        self.reads.append(path)
        if path not in self.data:
            raise AssertionError('unexpected synthetic read: ' + str(path))
        return self.data[path]

    def stat(self, path, **_kwargs):
        if path not in self.data:
            raise FileNotFoundError(path)
        return SimpleNamespace(st_size=len(self.data[path]), st_mtime_ns=self.times.get(path, 0))

    def mkdir(self, path, *args, **kwargs):
        self.directories.add(path)

    def open(self, path, mode, *args, **kwargs):
        if mode != 'xb' or path in self.data:
            raise AssertionError('unexpected synthetic write mode/path')
        files = self
        class Writer(io.BytesIO):
            def close(self):
                if not self.closed:
                    files.data[path] = self.getvalue()
                super().close()
        return Writer()

    def install(self, case):
        methods = {
            'resolve': lambda p, *a, **kw: self.resolve(p, **kw),
            'read_bytes': lambda p: self.read(p),
            'stat': lambda p, **kw: self.stat(p, **kw),
            'is_file': lambda p: p in self.data,
            'is_symlink': lambda p: p in self.symlinks,
            'exists': lambda p: p in self.data or p in self.directories,
            'mkdir': lambda p, *a, **kw: self.mkdir(p, *a, **kw),
            'open': lambda p, mode, *a, **kw: self.open(p, mode, *a, **kw),
        }
        for name, fn in methods.items():
            case.enterContext(patch.object(Path, name, fn))


def raw_state(version='v2', engine='v2.2', joined=False):
    requests = {
        '1': {'status': 'completed', 'result_path': '/synthetic/aq-exec/results/1-result.json',
              'result_sha256': 'result-1-sha', 'request_sha256': 'request-1-sha'},
        '2': {'status': 'completed', 'result_path': '/synthetic/aq-exec/results/2-result.json',
              'result_sha256': 'result-2-sha', 'request_sha256': 'request-2-sha'},
        '3': {'status': 'failed', 'history': [{'status': 'failed', 'reason': 'synthetic'}]},
        '4': {'status': 'running'},
    }
    group = {'scope': 'main', 'revision': 'aq-synthetic'}
    join = {'schema': 'zkfdo-instance-verdicts-v1', 'conflicts': 0,
            'instances': [], 'results': ['results/1-result.json']}
    if joined:
        group['join'] = {'path': '/synthetic/aq-exec/joins/group.json',
                         'sha256': hashlib.sha256(json.dumps(join).encode()).hexdigest()}
    raw = {'schema': 'n6-a-remeasure-aq-execute-' + version,
           'config': {'index_sha256': {engine: 'index-sha'},
                      'engine_sha256': {engine: 'engine-sha'}},
           'engines': {engine: {'requests': requests, 'groups': {'main:aq-synthetic': group}}}}
    return raw, join


class StateSelectionTests(unittest.TestCase):
    root = Path('/synthetic/aq-exec')

    def files(self, names, times=None, symlinks=()):
        files = MemoryFiles({self.root / name: {} for name in names},
                            {self.root / k: v for k, v in (times or {}).items()},
                            [self.root / x for x in symlinks])
        files.install(self)
        return files

    def test_newest_modification_wins_even_if_v3_exists(self):
        self.files(['state.json', 'state-v2.json', 'state-v3.json'],
                   {'state.json': 1, 'state-v2.json': 30, 'state-v3.json': 20})
        self.assertEqual(audit.select_state(self.root), self.root / 'state-v2.json')

    def test_equal_timestamps_prefer_v3(self):
        self.files(['state.json', 'state-v2.json', 'state-v3.json'])
        self.assertEqual(audit.select_state(self.root), self.root / 'state-v3.json')

    def test_equal_timestamps_prefer_v2_when_v3_missing(self):
        self.files(['state.json', 'state-v2.json'])
        self.assertEqual(audit.select_state(self.root), self.root / 'state-v2.json')

    def test_only_legacy_present(self):
        self.files(['state.json'])
        self.assertEqual(audit.select_state(self.root), self.root / 'state.json')

    def test_missing_states_fail_closed(self):
        self.files(['unrelated-state.json'])
        with self.assertRaisesRegex(ValueError, 'no known state file'):
            audit.select_state(self.root)

    def test_symlink_state_not_selected(self):
        self.files(['state-v2.json', 'state-v3.json'],
                   {'state-v2.json': 10, 'state-v3.json': 20}, ['state-v3.json'])
        self.assertEqual(audit.select_state(self.root), self.root / 'state-v2.json')


class AdapterTests(unittest.TestCase):
    def run_adapter(self, raw, join=None, joined_only=True):
        engine = next(iter(raw['engines']))
        source = Path('/synthetic/aq-exec/state-' + raw['schema'].rsplit('-', 1)[1] + '.json')
        if raw['schema'].endswith('-v1'):
            source = Path('/synthetic/aq-exec/state.json')
        folder = Path('/synthetic/output/check')
        entries = {source: raw, Path(audit.__file__): b'synthetic-auditor-script'}
        if join is not None:
            entries[Path('/synthetic/aq-exec/joins/group.json')] = join
        files = MemoryFiles(entries)
        files.install(self)
        self.enterContext(patch.object(audit, 'ROOT', Path('/synthetic')))
        self.enterContext(patch.object(audit, 'AQ', Path('/synthetic/aq-exec')))
        self.enterContext(patch.object(audit, 'guard'))
        args = ['audit', '--state', str(source), '--engine', engine, '--out-dir', str(folder)]
        if joined_only:
            args.append('--joined-only')
        self.enterContext(patch.object(sys, 'argv', args))
        self.enterContext(patch('sys.stdout', new_callable=io.StringIO))
        captured = {}
        def score(args):
            snapshot = json.loads(files.data[args.state])
            captured['state'] = copy.deepcopy(snapshot)
            captured['args'] = args
            counts = {}
            for value in snapshot['requests'].values():
                counts[value['status']] = counts.get(value['status'], 0) + 1
            return {'request_statuses': counts}
        self.enterContext(patch.object(audit.scorer, 'score', score))
        self.assertEqual(audit.main(), 0)
        receipt = json.loads(files.data[folder / 'audit-receipt.json'])
        return files, captured, receipt

    def test_v2_normalizes_to_expected_existing_layout(self):
        raw, _ = raw_state('v2')
        original = copy.deepcopy(raw)
        files, captured, receipt = self.run_adapter(raw, joined_only=False)
        converted = copy.deepcopy(raw)
        converted['schema'] = 'n6-a-remeasure-aq-execute-v1'
        expected = audit.scorer.normalize_state(converted, 'v2.2')
        self.assertEqual(captured['state'], expected)
        self.assertEqual(raw, original)
        self.assertEqual(receipt['reflected_completed_requests'], 2)
        self.assertFalse(receipt['judging_executed'])

    def test_v3_normalizes_to_expected_existing_layout(self):
        raw, _ = raw_state('v3')
        _, captured, receipt = self.run_adapter(raw, joined_only=False)
        converted = copy.deepcopy(raw)
        converted['schema'] = 'n6-a-remeasure-aq-execute-v1'
        self.assertEqual(captured['state'], audit.scorer.normalize_state(converted, 'v2.2'))
        self.assertEqual(receipt['state_schema'], 'n6-a-remeasure-aq-execute-v3')

    def test_v1_engine_selection_is_preserved(self):
        raw, _ = raw_state('v3', engine='v1')
        _, captured, receipt = self.run_adapter(raw, joined_only=False)
        self.assertEqual(captured['args'].engine, 'v1')
        self.assertEqual(receipt['source_completed_requests'], 2)
        self.assertEqual(captured['state']['engine_sha256'], 'engine-sha')

    def test_unjoined_completed_requests_are_held_without_reading_results(self):
        raw, _ = raw_state()
        files, captured, receipt = self.run_adapter(raw)
        self.assertEqual(receipt['held_requests'], 2)
        self.assertEqual(receipt['reflected_completed_requests'], 0)
        self.assertEqual(captured['state']['requests']['1']['status'], 'audit_pending_join')
        self.assertEqual(captured['state']['requests']['3']['status'], 'failed')
        self.assertEqual(captured['state']['requests']['4']['status'], 'running')
        self.assertTrue(all('result.json' not in str(p) for p in files.reads))

    def test_relative_join_results_rebase_to_original_state_parent(self):
        raw, join = raw_state(joined=True)
        files, captured, receipt = self.run_adapter(raw, join)
        group = captured['state']['revisions']['main:aq-synthetic']
        rewritten = json.loads(files.data[Path(group['instances_path'])])
        self.assertEqual(rewritten['results'], ['/synthetic/aq-exec/results/1-result.json'])
        self.assertEqual(group['instances_sha256'], hashlib.sha256(files.data[Path(group['instances_path'])]).hexdigest())
        self.assertEqual(receipt['held_requests'], 1)
        self.assertEqual(receipt['reflected_completed_requests'], 1)
        self.assertEqual(captured['state']['requests']['1']['status'], 'completed')
        self.assertEqual(captured['state']['requests']['2']['status'], 'audit_pending_join')

    def test_join_source_hash_is_checked(self):
        raw, join = raw_state(joined=True)
        join['results'].append('tampered-result.json')
        with self.assertRaisesRegex(ValueError, 'source SHA mismatch'):
            self.run_adapter(raw, join)


class GuardTests(unittest.TestCase):
    def test_normal_priority_rejected(self):
        with patch.object(audit.os, 'getpriority', return_value=0):
            with self.assertRaisesRegex(ValueError, 'nice 19 required'):
                audit.guard()

    def test_below_disk_floor_rejected(self):
        with patch.object(audit.os, 'getpriority', return_value=19), \
             patch.object(audit.shutil, 'disk_usage', return_value=SimpleNamespace(free=15*1024**3-1)):
            with self.assertRaisesRegex(ValueError, 'disk below 15 GiB'):
                audit.guard()

    def test_exact_disk_floor_allowed(self):
        with patch.object(audit.os, 'getpriority', return_value=19), \
             patch.object(audit.shutil, 'disk_usage', return_value=SimpleNamespace(free=15*1024**3)):
            audit.guard()


if __name__ == '__main__':
    if os.getpriority(os.PRIO_PROCESS, 0) < 19:
        raise SystemExit('nice 19 required')
    if shutil.disk_usage(Path(__file__).resolve().parents[1]).free < 15*1024**3:
        raise SystemExit('disk below 15 GiB')
    unittest.main()
