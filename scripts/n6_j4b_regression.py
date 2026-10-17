#!/usr/bin/env python3
"""Prepare or run A v2 with the unchanged J runner and locked regression gates."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import run_n6_j1 as runner

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'runs/n6-j4-2026-10-15.noindex'
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
            'runner_sha256':digest(Path(runner.__file__)), 'wrapper_sha256':digest(Path(__file__))})
        print(json.dumps({'status':'prepared_not_executed','index_sha256':digest(new_index)}))
        return 0
    runner.require(not stop.exists(), 'regression stopped; lead review required')
    lock = read(BASE / 'lock.json')
    runner.require(lock == {'engine':str(args.engine), 'engine_sha256':args.engine_sha256,
        'index_sha256':digest(new_index), 'lists_sha256':LIST_SHA,
        'runner_sha256':digest(Path(runner.__file__)), 'wrapper_sha256':digest(Path(__file__))}, 'v2 lock mismatch')
    runner.ENGINE = args.engine
    runner.ENGINE_SHA256 = args.engine_sha256
    original_lift, original_join = runner.run_lift, runner.join_instances
    def guarded_lift(*call_args):
        metrics = original_lift(*call_args)
        path = call_args[1] / 'result.json'
        if metrics['exit_code'] == 0 and path.is_file():
            check_result(read(path), lists)
        return metrics
    def guarded_join(*call_args):
        metrics = original_join(*call_args)
        if metrics['exit_code'] == 0:
            joined = read(call_args[2])
            # The join's effective reach can upgrade an earlier excluded request.
            for row in joined.get('classes', []):
                if row.get('effective') == 'assumption_violation_reachable':
                    check_result({'request_id':row['request_id'], 'classes':[
                        {'assumption_predicate_verdict':'assumption_violation_reachable'}]}, lists)
        return metrics
    runner.run_lift, runner.join_instances = guarded_lift, guarded_join
    try:
        state = runner.execute(new_index.resolve(), lock['index_sha256'], cache, output, cleanup_cache_per_revision=True)
    except RegressionStop as error:
        runner.atomic_json(stop, {'status':'regression_stopped','reason':str(error)})
        print(str(error))
        return 4
    print(json.dumps({'status':state['status'], 'output':str(output)}))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
