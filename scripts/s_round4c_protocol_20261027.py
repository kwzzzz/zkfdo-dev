#!/usr/bin/env python3
"""Pinned, read-only scoring/cost helpers for the Round 4c addendum. No engine calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runs/s-round4-2026-10-27/round4c'
REG = OUT / 'preregistration.json'
REG_SHA = 'cca4323573abfc130ef760c26e3595d24269beb1158f8790c44f20659faf5dd9'
DEADLINE = datetime(2026, 10, 28, 15, tzinfo=timezone.utc)


def require(value, message):
    if not value:
        raise ValueError(message)


def safe_path(value):
    p = Path(value).absolute()
    require('..' not in p.parts, 'parent traversal forbidden')
    require(p.is_relative_to(ROOT), 'repository paths only')
    require(not any(x.startswith(('n6-a-remeasure-', 'n6-b6', 'h1-')) for x in p.parts),
            'protected path; use an authorized summary outside active data')
    require(not p.is_relative_to(ROOT / 'target'), 'old target forbidden')
    require(p.resolve().is_relative_to(ROOT), 'external symlink forbidden')
    return p


def pin(value):
    p = safe_path(value)
    return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def read(ref):
    require(pin(ref['path'])['sha256'] == ref['sha256'], 'SHA mismatch: ' + ref['path'])
    return json.loads(safe_path(ref['path']).read_text())


def save(path, data):
    p = safe_path(path)
    require(p.is_relative_to(OUT), 'new 4c outputs only')
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return pin(p)


def registration():
    r = read({'path': str(REG), 'sha256': REG_SHA})
    for source in r['sources'].values():
        require(pin(source['path'])['sha256'] == source['sha256'], 'frozen reference changed')
    return r


def strict_rows(score, reg):
    require(score['schema'] == 'n6-light-rqc-v1' and score['layer'] == 'strict',
            'exploratory scores cannot enter the conclusion')
    require(score['denominators']['selected_items'] == 18 and
            score['denominators']['mapping_rows'] == 26, 'fixed denominator changed')
    source = score['sources'][score['definitions']['mapping_source']]
    require(source['sha256'] == reg['sources']['mapping']['sha256'], 'mapping changed')
    rows = [b for b in score['bugs'] if b['selected_for_fixed_mapping']]
    require(len(rows) == 18 and {b['item_id'] for b in rows} == set(reg['item_ids']),
            'fixed item set changed')
    require(all(not b['development'] for b in rows), 'development case in comparison')
    return {b['item_id']: b for b in rows}


def l1_revisions(bug, method):
    observation = bug['methods'][method]['vulnerable']
    require(type(observation['L1_observed']) is bool, 'invalid L1 flag')
    if not observation['L1_observed']:
        return set()
    require(not observation['definition_outside_ambiguous_location'] and
            not observation['mixed_statuses_definition_outside'], 'ambiguous/mixed strict score')
    rows = bug['methods'][method]['revisions']
    revisions = {r['revision_id'] for r in rows
                 if r['kind'] == 'vulnerable' and 'L1' in r['observed_statuses']}
    require(bool(revisions), 'L1 lacks a vulnerable revision')
    return revisions


def new_discoveries(baseline, current, reg):
    old, new = strict_rows(baseline, reg), strict_rows(current, reg)
    return {item: sorted(l1_revisions(b, 'S')) for item, b in new.items()
            if l1_revisions(b, 'S') and not l1_revisions(old[item], 'W')}


def conclusion(new, equal_w_items, completed, s_complete):
    # Absence of a finished comparison is never evidence of a W miss.
    if not s_complete:
        return '대기: S+J 미완료'
    if not new:
        return '탐지 효용 미확인'
    needed = {r for rs in new.values() for r in rs}
    if not needed <= set(completed):
        return '대기: 같은 총시간 W 또는 후보 확인 미완료'
    return '탐지 효용 있음' if set(new) - set(equal_w_items) else '같은 시간이면 차이 없음'


def cost_totals(costs, revisions, seeds, loader=read):
    require(costs['schema'] == 's-round4c-cost-receipts-v1', 'cost schema')
    require(costs.get('complete') is True, 'complete preparation/S/J cost inventory required')
    require(len(costs['revisions']) == len({r['revision'] for r in costs['revisions']}),
            'duplicate cost revision')
    by_revision = {r['revision']: r for r in costs['revisions']}
    start = costs.get('execution_start')
    earliest = DEADLINE
    if start:
        receipt = loader(start)
        require(receipt.get('aq_final_verified') is True and
                receipt.get('aq_process_absent') is True, 'unverified execution start')
        earliest = datetime.fromisoformat(receipt['start_utc'])
        require(earliest.tzinfo is not None and
                (earliest >= DEADLINE or receipt.get('aq_stopped_by_miiz') is True),
                'early execution start lacks miiz stop flag')
    totals, seen, all_intervals = {}, set(), []
    for revision in sorted(revisions):
        r = by_revision[revision]
        require(r.get('complete') is True and r.get('J_complete') is True, 'unfinished S+J costs')
        require(type(r['new_candidates']) is int and r['new_candidates'] >= 0, 'candidate count')
        phases = Counter()
        fuzz_seeds, components = set(), Counter()
        for stage in r['stages']:
            phase = stage['phase']
            require(phase in ('preparation', 'fuzz', 'J'), 'unrecognized cost phase')
            key = stage['receipt']['sha256']
            require(key not in seen, 'duplicate receipt; shared preparation is counted once')
            seen.add(key)
            receipt = loader(stage['receipt'])
            start = datetime.fromisoformat(receipt['start_utc'])
            end = datetime.fromisoformat(receipt['end_utc'])
            require(start.tzinfo is not None and end.tzinfo is not None and end > start,
                    'invalid stage interval')
            require(start >= earliest, 'historical work cannot replace this execution S+J costs')
            delta = end - start
            ns = ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1000
            # Failed attempts still cost time; unfinished/partial records are refused.
            require(receipt['status'] in ('completed', 'failed', 'timeout', 'memory_limit',
                                         '중단(내장)', 'output_limit', 'cargo_target_8GiB_limit'),
                    'unfinished/unknown receipt status')
            all_intervals.append((start, end))
            phases[phase] += 1
            components[phase] += ns
            if phase == 'fuzz':
                require(stage['seed'] in seeds, 'wrong seed')
                fuzz_seeds.add(stage['seed'])
        require(phases['preparation'] > 0 and fuzz_seeds == set(seeds), 'missing prep or seed')
        require(phases['J'] > 0 or r['new_candidates'] == 0, 'J time omitted')
        totals[revision] = {'total_ns': sum(components.values()), 'phase_ns': dict(components)}
    intervals = sorted(all_intervals)
    require(all(a[1] <= b[0] for a, b in zip(intervals, intervals[1:])),
            'overlapping receipts: double counting or nonsequential work')
    return totals


def guarantee(reason, basis='', method=''):
    if reason == 'local_constraint_refutation':
        return 'constructed_input_only'
    if reason in ('closed_cone_unsat', 'constant_input_mismatch', 'predicate_cone_unsat'):
        return 'input_independent'
    # New codes are not silently classified from an English substring.
    return 'unclassified'


def recount_b(summary):
    rows = []
    for engine, data in summary['engines'].items():
        counts, proofs, seen = Counter(), Counter(), set()
        for row in data['excluded_classes']:
            key = (row['request_id'], row['class_index_zero_based'])
            require(key not in seen, 'duplicate class occurrence')
            seen.add(key)
            parts = row['proof_type'].split(' | ')
            require(len(parts) == 3, 'unknown proof format')
            counts[guarantee(*parts)] += 1
            proofs[row['proof_type']] += 1
        require(dict(proofs) == data['proof_counts'], 'class rows and proof totals disagree')
        require(len(seen) == data['expected_total'], 'summary coverage mismatch')
        rows.append({'engine': engine, 'unit': 'request-class occurrence',
                     'input_independent': counts['input_independent'],
                     'constructed_input_only': counts['constructed_input_only'],
                     'unclassified': counts['unclassified'], 'proof_counts': dict(proofs),
                     'completed_requests': data['status_counts']['completed']})
    return rows


def recount_banyan(summary):
    rows = []
    for r in summary['development_pair_observations']:
        if r['revision_id'] != 'banyan-fixed' or r['method'] != 'S':
            continue
        require(r['request_statuses'] == {'completed': r['requests']}, 'partial banyan summary')
        # This summary contains generic outcome flags, not class reason codes.
        rows.append({'engine': summary['engine'], 'revision': 'banyan-fixed', 'method': 'S',
                     'unit': 'request', 'completed_requests': r['requests'],
                     'input_independent': None, 'constructed_input_only': None,
                     'reason_code_unavailable_requests': r['requests'],
                     'status': 'blocked: summary has no proof reason; protected aggregate unread'})
    require(len(rows) == 1, 'banyan fixed S denominator changed')
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recount', action='store_true')
    p.add_argument('--output', required=True)
    a = p.parse_args()
    require(a.recount, 'choose --recount')
    registration()
    refs = [pin('docs/n6_light_exclusions_2026-10-26.json')] + [
        pin(f'docs/n6_light_rqc_banyan_{e}_2026-10-26.json') for e in ('v2.2', 'v1')]
    result = {'schema': 's-round4c-guarantees-v1', 'preregistration_sha256': REG_SHA,
              'sources': refs, 'B': recount_b(read(refs[0])),
              'banyan': sum((recount_banyan(read(r)) for r in refs[1:]), []),
              'aq': 'deferred until deadline; no active state read'}
    print(json.dumps(save(a.output, result), ensure_ascii=False))


if __name__ == '__main__':
    main()
