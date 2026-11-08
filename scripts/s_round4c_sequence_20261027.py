#!/usr/bin/env python3
"""Round 4c order and equal-total-time W, gated by the final aq state."""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

import s_round4c_protocol_20261027 as protocol
import s_round4b_postdeadline_20261027 as previous
import s_round4c_postdeadline_20261027 as post

require = protocol.require
read = protocol.read
save = protocol.save
monitor = post.PostMonitor({})


def stages():
    return [
        {'order': 1, 'stage': 'preflight/replay', 'action': 'Verify immutable engine/input hashes and completed v2.2 sample replay using new v2.3; any difference stops.'},
        {'order': 2, 'stage': 'prepare', 'action': 'Prepare fixed 15-revision inputs; record each revision preparation wall time, including wrapper compile.'},
        {'order': 3, 'stage': 'S-policy-B', 'action': 'Same 3 seeds, 600 s/seed, 30 s attempt cap; fixed Policy B; no W in this stage.'},
        {'order': 4, 'stage': 'new-J/strict-score', 'action': 'Judge only new candidates; retain old results; separate strict/exploratory and proof guarantees; finish all S/J costs.'},
        {'order': 5, 'stage': 'W-required', 'action': 'Only revisions with new strict L1 relative to original W; (preparation + S + J)/3 per original seed; original W memory cap.'},
        {'order': 6, 'stage': 'W-confirm/conclude', 'action': 'Confirm W candidates with same strict L1 rules, separately report confirmation cost; incomplete comparison remains pending; recount aq guarantees now.'},
        {'order': 7, 'stage': 'W-all-15-optional', 'automatic': False,
         'action': 'Last stage only. Separate human invocation with --optional-all-15-human-start; never auto-chain. Cannot replace required-comparison outcomes.'},
    ]


def audited_score(bundle, reg):
    score = read(bundle['score'])
    audit = read(bundle['strict_input_audit'])
    require(audit.get('passed') is True and audit.get('complete') is True and
            audit.get('layer') == 'strict' and audit.get('constructed_inputs_used') is False and
            audit.get('score_sha256') == bundle['score']['sha256'],
            'complete, SHA-bound strict input audit required; exploratory is not strict')
    protocol.strict_rows(score, reg)
    return score


def w_spec(original, seed, total_ns):
    require(original['method'] == 'whole' and len(original['targets']) == 1,
            'whole-circuit W spec required')
    require(original['initial_seed'] == seed and original['concurrency'] == 1,
            'original seed/concurrency mismatch')
    require(type(original['memory_cap_bytes']) is int and original['memory_cap_bytes'] > 0,
            'original memory cap missing')
    require(type(total_ns) is int and total_ns > 0, 'positive measured S+J cost required')
    spec = copy.deepcopy(original)
    seconds = total_ns / 3_000_000_000
    require(math.isfinite(seconds) and seconds > 0, 'invalid budget')
    spec['total_budget_seconds'] = seconds
    spec['attempt_cap_seconds'] = seconds
    spec['coverage_checkpoints_seconds'] = [seconds]
    spec['campaign_id'] += '-round4c-equal-time'
    return spec


def make_w_plan(bundle, reg, all_15=False):
    score = audited_score(bundle, reg)
    baseline = read(reg['sources']['baseline_strict'])
    new = protocol.new_discoveries(baseline, score, reg)
    selected = set(reg['revision_ids']) if all_15 else {r for rs in new.values() for r in rs}
    require(selected <= set(reg['revision_ids']), 'revision outside fixed manifest')
    totals = protocol.cost_totals(read(bundle['costs']), selected, reg['seeds'])
    queue = read(reg['sources']['queue'])
    units = {(u['identifier'], u['seed']): u for u in queue['units']}
    jobs = []
    for revision in reg['revision_ids']:
        if revision not in selected:
            continue
        for seed in reg['seeds']:
            unit = units[revision, seed]
            ref = {'path': unit['whole_spec'], 'sha256': unit['whole_spec_sha256']}
            spec = w_spec(read(ref), seed, totals[revision]['total_ns'])
            jobs.append({'revision': revision, 'seed': seed, 'original_W_spec': ref,
                         'S_plus_J_ns': totals[revision]['total_ns'],
                         'budget_ns_numerator': totals[revision]['total_ns'], 'budget_ns_denominator': 3,
                         'budget_seconds': spec['total_budget_seconds'],
                         'memory_cap_bytes': spec['memory_cap_bytes']})
    return {'schema': 's-round4c-W-plan-v1', 'preregistration_sha256': protocol.REG_SHA,
            'selection': 'optional-all-15' if all_15 else 'required-new-L1-only',
            'input_bundle': bundle, 'new_strict_L1_items': new, 'revision_costs': totals,
            'jobs': jobs, 'fuzz_budget_seconds': sum(x['total_ns'] for x in totals.values()) / 1e9,
            'additional_time': 'W preparation/cleanup and strict W candidate confirmation, measured separately',
            'disk_estimate': 'unknown until a SHA-pinned measured peak/retained resource plan is supplied; execution refuses missing values'}


def child(spec_path, preflight, output, preparation):
    post.quiet_host()
    require(post.sha(post.AQ_STATE) == os.environ.get('S_ROUND4C_AQ_START_SHA256'),
            'W child has no matching aq start state')
    post.validate_aq_state(json.loads(post.AQ_STATE.read_text()),
                           aq_stopped_by_miiz=os.environ.get('S_ROUND4C_AQ_STOPPED_BY_MIIZ') == '1')
    require(os.getpriority(os.PRIO_PROCESS, 0) == 19, 'nice 19 required')
    import run_policy_a_engine_v4 as engine
    cancelled = False
    last_check = 0.0
    low = False

    def stop(_signal, _frame):
        nonlocal cancelled
        cancelled = True

    def cancel():
        nonlocal last_check, low
        if time.monotonic() - last_check >= 1:
            last_check = time.monotonic()
            low = monitor.free_bytes() < 18 * monitor.GIB
        return cancelled or low

    signal.signal(signal.SIGTERM, stop)
    output = protocol.safe_path(output)
    require(output.is_relative_to(protocol.OUT), 'owned W output only')
    with engine.installed():
        if preparation:
            engine._ACTIVE_METHOD = 'whole'
            original = engine.v1.spawn_and_measure

            def guarded(command, directory, end, start, original_cancel):
                return original(command, directory, end, start,
                                lambda: cancel() or original_cancel())

            engine.v1.spawn_and_measure = guarded
            result = engine.v1.preflight(Path(spec_path), output)
            require(result['ledger']['status'] == 'passed', 'W compile/preflight failed')
        else:
            spec, sha = engine.v1.load_spec(Path(spec_path))
            snapshots, root = engine.v1.read_preflight(spec, sha, Path(preflight))
            result = engine.v1.run_campaign(spec, sha, snapshots, root, output, cancel_check=cancel)
            require(result['ledger']['status'] == 'completed', 'W unfinished; no negative conclusion')


def execute_w(plan, resources, out, optional=False, completed_required=None):
    post.quiet_host()
    require(post.sha(post.AQ_STATE) == os.environ.get('S_ROUND4C_AQ_START_SHA256'),
            'W execution has no matching aq start state')
    post.validate_aq_state(json.loads(post.AQ_STATE.read_text()),
                           aq_stopped_by_miiz=os.environ.get('S_ROUND4C_AQ_STOPPED_BY_MIIZ') == '1')
    reg = protocol.registration()
    require(plan == make_w_plan(plan['input_bundle'], reg,
                               all_15=plan['selection'] == 'optional-all-15'), 'W plan changed')
    if plan['selection'] == 'optional-all-15':
        require(optional and completed_required is not None, 'separate human start required')
        done = read(completed_required)
        require(done.get('complete') is True and done.get('selection') == 'required-new-L1-only' and
                done.get('preregistration_sha256') == protocol.REG_SHA,
                'required comparison must finish first')
    else:
        require(not optional, 'optional flag on required stage')
    require(resources['schema'] == 's-round4c-W-resources-v1', 'resource schema')
    rows = resources['jobs']
    by_key = {(r['revision'], r['seed']): r for r in rows}
    require(len(rows) == len(by_key) and set(by_key) ==
            {(j['revision'], j['seed']) for j in plan['jobs']}, 'resource coverage mismatch')
    out = protocol.safe_path(out)
    require(out.is_relative_to(protocol.OUT), '4c output only')
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for i, job in enumerate(plan['jobs']):
        resource = by_key[job['revision'], job['seed']]
        # Verify the evidence file as well as the declared measured values.
        evidence = read(resource['measurement'])
        require(evidence['peak_bytes'] == resource['peak_bytes'] and
                evidence['retained_bytes'] == resource['retained_bytes'], 'resource evidence mismatch')
        post.internal_gate(resource['peak_bytes'], resource['retained_bytes'])
        folder = out / str(i)
        folder.mkdir()
        spec = w_spec(read(job['original_W_spec']), job['seed'], job['S_plus_J_ns'])
        save(folder / 'spec.json', spec)
        command = [sys.executable, '-B', str(Path(__file__).resolve())]
        pre_label = f'4c-{out.name}-W-preflight-{i}'
        run_label = f'4c-{out.name}-W-{i}'
        monitor.limits[pre_label] = resource['expected_preflight_seconds']
        monitor.limits[run_label] = math.ceil(job['budget_seconds']) + resource['expected_overhead_seconds']
        pre = monitor.run(command + ['_preflight', str(folder / 'spec.json'), 'unused', str(folder / 'preflight')],
                          pre_label)
        require(pre['status'] == 'completed', 'W preparation stopped')
        run = monitor.run(command + ['_campaign', str(folder / 'spec.json'), str(folder / 'preflight/preflight.json'),
                                    str(folder / 'campaign')], run_label)
        require(run['status'] == 'completed', 'W stopped; comparison incomplete')
        ledger = protocol.pin(folder / 'campaign/ledger.json')
        result = {'revision': job['revision'], 'seed': job['seed'], 'budget_seconds': job['budget_seconds'],
                  'memory_cap_bytes': job['memory_cap_bytes'], 'ledger': ledger,
                  'spec': str(folder / 'spec.json'), 'campaign': str(folder / 'campaign'),
                  'preparation_monitor': pre['receipt'], 'campaign_monitor': run['receipt']}
        results.append(result)
        save(folder / 'binding.json', result)
    return save(out / 'summary.json', {'schema': 's-round4c-W-runs-v1', 'selection': plan['selection'],
                               'plan': plan, 'jobs': results, 'fuzz_complete': True,
                               'strict_candidate_confirmation_complete': False})


def finish_comparison(bundle, reg):
    current = audited_score(bundle['S'], reg)
    new = protocol.new_discoveries(read(reg['sources']['baseline_strict']), current, reg)
    if not new:
        return {'complete': True, 'selection': 'required-new-L1-only',
                'preregistration_sha256': protocol.REG_SHA, 'new_items': {},
                'conclusion': '탐지 효용 미확인', 'sources': bundle}
    equal = audited_score(bundle['W'], reg)
    runs = read(bundle['W_runs'])
    require(runs['schema'] == 's-round4c-W-runs-v1' and
            runs['selection'] == 'required-new-L1-only' and runs['fuzz_complete'] is True,
            'required W execution receipt missing')
    plan = runs['plan']
    require(plan == make_w_plan(plan['input_bundle'], reg), 'executed W plan is inconsistent')
    require(plan['input_bundle']['score'] == bundle['S']['score'], 'W matched a different S result')
    expected = {(j['revision'], j['seed']): j for j in plan['jobs']}
    actual = {(j['revision'], j['seed']): j for j in runs['jobs']}
    require(len(actual) == len(runs['jobs']) and set(actual) == set(expected), 'W seed coverage missing')
    for key, job in actual.items():
        planned = expected[key]
        ledger = read(job['ledger'])
        require(ledger['status'] == 'completed' and ledger['method'] == 'whole' and
                ledger['total_budget_seconds'] == planned['budget_seconds'] and
                ledger['memory_cap_bytes'] == planned['memory_cap_bytes'], 'W controls/status differ')
    audit = read(bundle['W']['strict_input_audit'])
    require(audit.get('W_runs_sha256') == bundle['W_runs']['sha256'] and
            audit.get('all_candidate_confirmations_finished') is True,
            'W strict confirmation coverage not linked to completed campaigns')
    equal_items = {item for item, b in protocol.strict_rows(equal, reg).items()
                   if protocol.l1_revisions(b, 'W')}
    completed = {revision for revision, _ in actual}
    return {'complete': True, 'selection': 'required-new-L1-only',
            'preregistration_sha256': protocol.REG_SHA, 'new_items': new,
            'equal_W_observed_items': sorted(equal_items & set(new)),
            'equal_W_unobserved_items': sorted(set(new) - equal_items),
            'conclusion': protocol.conclusion(new, equal_items, completed, True), 'sources': bundle}


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ('_preflight', '_campaign'):
        require(len(sys.argv) == 5, 'child arguments')
        child(*sys.argv[2:], preparation=sys.argv[1] == '_preflight')
        return
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('sequence', 'plan-w', 'run-w', 'conclude'))
    p.add_argument('--input'); p.add_argument('--input-sha256'); p.add_argument('--output', required=True)
    p.add_argument('--resources'); p.add_argument('--resources-sha256')
    p.add_argument('--all-15', action='store_true')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--aq-stopped-by-miiz', action='store_true')
    p.add_argument('--optional-all-15-human-start', action='store_true')
    p.add_argument('--completed-required'); p.add_argument('--completed-required-sha256')
    a = p.parse_args()
    require(os.getpriority(os.PRIO_PROCESS, 0) == 19, 'nice 19 required')
    reg = protocol.registration()
    if a.action == 'sequence':
        save(a.output, {'preregistration_sha256': protocol.REG_SHA, 'steps': stages(),
                        'scope': '4c execution gates and fixed equal-total-time W comparison'})
        return
    post.quiet_host()
    state_sha = post.sha(post.AQ_STATE)
    state = json.loads(post.AQ_STATE.read_text())
    post.validate_aq_state(state, aq_stopped_by_miiz=a.aq_stopped_by_miiz)
    require(post.sha(post.AQ_STATE) == state_sha, 'aq state changed during start check')
    post.quiet_host()
    os.environ['S_ROUND4C_AQ_START_SHA256'] = state_sha
    if a.aq_stopped_by_miiz:
        os.environ['S_ROUND4C_AQ_STOPPED_BY_MIIZ'] = '1'
    require(a.input and a.input_sha256, 'SHA-pinned input required')
    data = read({'path': a.input, 'sha256': a.input_sha256})
    if a.action == 'conclude':
        save(a.output, finish_comparison(data, reg))
        return
    if a.action == 'plan-w':
        save(a.output, make_w_plan(data, reg, all_15=a.all_15))
        return
    require(a.execute, '--execute required')
    require(a.resources and a.resources_sha256, 'measured resource plan required')
    complete = ({'path': a.completed_required, 'sha256': a.completed_required_sha256}
                if a.completed_required and a.completed_required_sha256 else None)
    execute_w(data, read({'path': a.resources, 'sha256': a.resources_sha256}), a.output,
              optional=a.optional_all_15_human_start, completed_required=complete)


if __name__ == '__main__':
    main()
