#!/usr/bin/env python3
"""Prepare or run A v2 with the unchanged J runner and locked regression gates."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
from pathlib import Path
import run_n6_j1 as runner

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'runs/n6-j4-2026-10-15.noindex/reaudit-v2.noindex'
LISTS = ROOT / 'docs/n6_j4b_regression_lists_2026-10-16.json'
LIST_SHA = 'dd54296714dd1f7114770ad59314d6b7aceef2b091a5c6a71767e71f9ccc4290'
INDEX = ROOT / 'runs/n6-j1-2026-10-09.noindex/request-index.json'
INDEX_SHA = '35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c'

class RegressionStop(RuntimeError):
    pass

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path: Path) -> dict:
    return json.loads(path.read_text())

def l1(result: dict) -> bool:
    return any(c.get('verdict') == 'entrypoint_violation' or
               c.get('assumption_predicate_verdict') == 'assumption_violation_reachable' or
               any(p.get('verdict') == 'assumption_violation_reachable' for p in c.get('predicates', []))
               for c in result.get('classes', []))

def check_result(result: dict, lists: dict) -> None:
    if not l1(result):
        return
    request = result.get('request_id')
    excluded = {r['request_id']: r for r in lists['exclusion_50']['requests']}
    fixed = {r['request_id'] for revision in lists['l1_zero_revisions'] for r in revision['requests']}
    if request in excluded or request in fixed:
        kind = excluded.get(request, {}).get('exclusion_kind', '전체 수정판')
        raise RegressionStop(f'L1 stop: {request} ({kind})')

def check_binding(row: dict, result: dict, lists: dict) -> None:
    if 'completed_requests' in lists:
        expected = {item['request']: item['request_id'] for item in lists['completed_requests']}
        request_id = expected.get(row.get('request'))
        runner.require(request_id is not None and result.get('request_id') == request_id,
                       'regression result request ID binding mismatch')
        classes = result.get('classes')
        allowed = {'entrypoint_violation', 'assumption_input_reachable', 'compatible_no_top_violation_observed',
                   'excluded_in_context', 'unknown', 'preparation_failure'}
        runner.require(isinstance(classes, list) and bool(classes) and
                       all(isinstance(row, dict) and row.get('verdict') in allowed for row in classes),
                       'regression result missing or invalid class judgments')


def runtime_tools() -> dict:
    found = {}
    for name in ('node', 'snarkjs', 'z3'):
        resolved = shutil.which(name)
        runner.require(resolved is not None, f'missing locked tool: {name}')
        path = Path(resolved).resolve()
        found[name] = {'path': str(path), 'sha256': digest(path)}
    return found


def check_join(joined: dict, lists: dict) -> None:
    for row in joined.get('classes', []):
        if row.get('effective') == 'assumption_violation_reachable':
            check_result({'request_id': row['request_id'], 'classes': [
                {'assumption_predicate_verdict': 'assumption_violation_reachable'}]}, lists)


def execute_guarded(index: Path, index_sha: str, cache: Path, output: Path,
                    lists: dict, stop: Path) -> dict:
    """Guard fresh results, resumed results, and both new and persisted joins."""
    runner.require(not stop.exists(), 'regression stopped; lead review required')
    original_lift = runner.run_lift
    original_join = runner.join_instances
    original_issue = runner.successful_result_issue
    original_atomic = runner.atomic_json
    state_path = output / 'state.json'
    checked_joins: set[tuple[str, str]] = set()
    def inspect_join(path: Path):
        runner.require(path.resolve().is_relative_to(output.resolve()), 'instance join outside this v2 output')
        if path.is_file():
            key = (str(path), digest(path))
            if key not in checked_joins:
                check_join(read(path), lists)
                checked_joins.add(key)
    def inspect_state(state: dict):
        for revision in state.get('revisions', {}).values():
            if revision.get('status') == 'joined' and revision.get('instances_path'):
                inspect_join(Path(revision['instances_path']))
    def guarded_issue(row, metrics, result):
        issue = original_issue(row, metrics, result)
        if issue is None:
            check_binding(row, result, lists)
            check_result(result, lists)
        return issue
    def guarded_lift(*args):
        metrics = original_lift(*args)
        path = args[1] / 'result.json'
        if metrics['exit_code'] == 0 and path.is_file():
            result = read(path)
            check_binding(args[0], result, lists)
            check_result(result, lists)
        return metrics
    def guarded_join(*args):
        metrics = original_join(*args)
        if metrics['exit_code'] == 0:
            inspect_join(args[2])
        return metrics
    def guarded_atomic(path, value):
        if path == state_path:
            inspect_state(value)
        original_atomic(path, value)
    try:
        # Only exact index/state paths are inspected; no recursive output walk.
        if state_path.is_file():
            inspect_state(read(state_path))
        for scope, ordinal, _revision, _rows in runner.groups(read(index)['requests']):
            inspect_join(output / scope / f'{ordinal:04d}' / 'instances.json')
        runner.run_lift, runner.join_instances = guarded_lift, guarded_join
        runner.successful_result_issue, runner.atomic_json = guarded_issue, guarded_atomic
        return runner.execute(index, index_sha, cache, output, cleanup_cache_per_revision=True)
    except RegressionStop as error:
        original_atomic(stop, {'status': 'regression_stopped', 'reason': str(error)})
        raise
    finally:
        runner.run_lift, runner.join_instances = original_lift, original_join
        runner.successful_result_issue, runner.atomic_json = original_issue, original_atomic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--engine-sha256', required=True)
    parser.add_argument('--action', choices=['prepare', 'execute'], required=True)
    args = parser.parse_args()
    runner.require(digest(LISTS) == LIST_SHA, 'regression lists SHA mismatch')
    runner.require(digest(INDEX) == INDEX_SHA, 'v1 index SHA mismatch')
    runner.require(args.engine.is_absolute() and digest(args.engine) == args.engine_sha256, 'v2 engine SHA mismatch')
    lists = read(LISTS)
    runner.require(lists['status'] == 'fixed_before_implementation', 'lists not fixed')
    new_index = BASE / 'request-index-v2.json'
    cache = BASE / 'cache.noindex'
    output = BASE / 'j-execute.noindex'
    stop = BASE / 'REGRESSION_STOP.json'
    if args.action == 'prepare':
        runner.require(not BASE.exists(), 'v2 base already exists; do not overwrite')
        index = read(INDEX)
        index['engine'] = str(args.engine)
        index['engine_sha256'] = args.engine_sha256
        index['v2_origin_index_sha256'] = INDEX_SHA
        index['regression_lists_sha256'] = LIST_SHA
        BASE.mkdir(parents=True)
        cache.mkdir()
        runner.atomic_json(new_index, index)
        runner.atomic_json(BASE / 'lock.json', {'engine':str(args.engine), 'engine_sha256':args.engine_sha256,
            'index_sha256':digest(new_index), 'lists_sha256':LIST_SHA,
            'runner_sha256':digest(Path(runner.__file__)), 'wrapper_sha256':digest(Path(__file__)),
            'cache_helper_sha256':digest(ROOT / 'scripts/n6_j1_cache_cleanup.py'),
            'source_helper_sha256':digest(ROOT / 'scripts/run_policy_a_engine.py'), 'runtime_tools':runtime_tools()})
        print(json.dumps({'status':'prepared_not_executed','index_sha256':digest(new_index)}))
        return 0
    runner.require(not stop.exists(), 'regression stopped; lead review required')
    lock = read(BASE / 'lock.json')
    runner.require(lock == {'engine':str(args.engine), 'engine_sha256':args.engine_sha256,
        'index_sha256':digest(new_index), 'lists_sha256':LIST_SHA,
        'runner_sha256':digest(Path(runner.__file__)), 'wrapper_sha256':digest(Path(__file__)),
            'cache_helper_sha256':digest(ROOT / 'scripts/n6_j1_cache_cleanup.py'),
            'source_helper_sha256':digest(ROOT / 'scripts/run_policy_a_engine.py'), 'runtime_tools':runtime_tools()}, 'v2 lock mismatch')
    runner.ENGINE = args.engine
    runner.ENGINE_SHA256 = args.engine_sha256
    try:
        state = execute_guarded(new_index.resolve(), lock['index_sha256'], cache, output, lists, stop)
    except RegressionStop as error:
        print(str(error))
        return 4
    print(json.dumps({'status':state['status'], 'output':str(output)}))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
