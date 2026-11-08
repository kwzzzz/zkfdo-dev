#!/usr/bin/env python3
"""Pure tests: no subprocess, engine, compilation, or corpus candidate access."""
import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import s_round4c_protocol_20261027 as p
import s_round4c_sequence_20261027 as s


class CriteriaTests(unittest.TestCase):
    def test_no_new(self):
        self.assertEqual(p.conclusion({}, set(), set(), True), '탐지 효용 미확인')

    def test_incomplete_s(self):
        self.assertTrue(p.conclusion({}, set(), set(), False).startswith('대기'))

    def test_incomplete_w_not_negative(self):
        self.assertTrue(p.conclusion({'bug': ['aq']}, set(), set(), True).startswith('대기'))

    def test_new_w_miss(self):
        self.assertEqual(p.conclusion({'bug': ['aq']}, set(), {'aq'}, True), '탐지 효용 있음')

    def test_equal_time(self):
        self.assertEqual(p.conclusion({'bug': ['aq']}, {'bug'}, {'aq'}, True), '같은 시간이면 차이 없음')

    def test_mixed_new_items(self):
        self.assertEqual(p.conclusion({'a': ['r'], 'b': ['r']}, {'a'}, {'r'}, True), '탐지 효용 있음')

    def test_future_deadline(self):
        with self.assertRaisesRegex(ValueError, 'deadline'):
            s.previous.deadline(datetime(2026, 10, 27, tzinfo=timezone.utc))

    def test_optional_last_manual(self):
        self.assertEqual(s.stages()[-1]['stage'], 'W-all-15-optional')
        self.assertFalse(s.stages()[-1]['automatic'])

    def test_strict_only(self):
        with self.assertRaisesRegex(ValueError, 'exploratory'):
            p.strict_rows({'schema': 'n6-light-rqc-v1', 'layer': 'exploratory'}, {})

    def test_ambiguous_rejected(self):
        b = {'methods': {'S': {'vulnerable': {'L1_observed': True,
             'definition_outside_ambiguous_location': True, 'mixed_statuses_definition_outside': False}}}}
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            p.l1_revisions(b, 'S')


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.spec = {'method': 'whole', 'targets': [{'entrypoint': 'same'}], 'initial_seed': 1,
                     'concurrency': 1, 'memory_cap_bytes': 10 * 2**30, 'campaign_id': 'old',
                     'total_budget_seconds': 600, 'attempt_cap_seconds': 600,
                     'coverage_checkpoints_seconds': [600], 'command': ['unchanged']}

    def test_equal_three_seeds_no_rounding(self):
        budgets = []
        for seed in (1, 2, 3):
            old = dict(self.spec, initial_seed=seed)
            new = s.w_spec(old, seed, 1_000_000_001)
            budgets.append(new['total_budget_seconds'])
            self.assertEqual(new['attempt_cap_seconds'], budgets[-1])
            self.assertEqual(new['memory_cap_bytes'], old['memory_cap_bytes'])
            for k in set(old) - {'campaign_id', 'total_budget_seconds', 'attempt_cap_seconds', 'coverage_checkpoints_seconds'}:
                self.assertEqual(old[k], new[k])
        self.assertEqual(len(set(budgets)), 1)

    def test_seed_mismatch(self):
        with self.assertRaisesRegex(ValueError, 'seed'):
            s.w_spec(self.spec, 99, 100)

    def test_invalid_cost(self):
        for n in (0, -1, 0.5, True):
            with self.assertRaises(ValueError):
                s.w_spec(self.spec, 1, n)

    def fixture(self):
        receipts, stages = {}, []
        for i, phase in enumerate(('preparation', 'fuzz', 'fuzz', 'fuzz', 'J')):
            receipts[str(i)] = {'start_utc': f'2026-10-29T00:00:0{i}+00:00',
                                'end_utc': f'2026-10-29T00:00:0{i+1}+00:00', 'status': 'completed'}
            stages.append({'phase': phase, 'seed': i if phase == 'fuzz' else None,
                           'receipt': {'sha256': str(i), 'path': str(i)}})
        costs = {'schema': 's-round4c-cost-receipts-v1', 'complete': True,
                 'revisions': [{'revision': 'r', 'complete': True, 'J_complete': True,
                                'new_candidates': 1, 'stages': stages}]}
        return costs, receipts

    def test_all_costs_included(self):
        c, r = self.fixture()
        out = p.cost_totals(c, ['r'], [1, 2, 3], lambda ref: r[ref['path']])
        self.assertEqual(out['r']['total_ns'], 5_000_000_000)
        self.assertEqual(out['r']['phase_ns']['fuzz'], 3_000_000_000)

    def test_duplicate_shared_prep_rejected(self):
        c, r = self.fixture()
        c['revisions'][0]['stages'].append(c['revisions'][0]['stages'][0])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            p.cost_totals(c, ['r'], [1, 2, 3], lambda ref: r[ref['path']])

    def test_overlap_rejected(self):
        c, r = self.fixture()
        r['0']['end_utc'] = '2026-10-29T00:00:02+00:00'
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            p.cost_totals(c, ['r'], [1, 2, 3], lambda ref: r[ref['path']])

    def test_missing_j_rejected(self):
        c, r = self.fixture()
        c['revisions'][0]['stages'].pop()
        with self.assertRaisesRegex(ValueError, 'J time'):
            p.cost_totals(c, ['r'], [1, 2, 3], lambda ref: r[ref['path']])

    def test_failed_attempt_time_retained(self):
        c, r = self.fixture()
        r['0']['status'] = 'failed'
        self.assertEqual(p.cost_totals(c, ['r'], [1, 2, 3], lambda ref: r[ref['path']])['r']['total_ns'], 5_000_000_000)

    def test_disk_interruption_time_retained(self):
        c, r = self.fixture()
        r['0']['status'] = '중단(내장)'
        self.assertEqual(p.cost_totals(c, ['r'], [1, 2, 3], lambda ref: r[ref['path']])['r']['total_ns'], 5_000_000_000)

    def test_historical_cost_rejected(self):
        c, r = self.fixture()
        r['0']['start_utc'] = '2026-10-27T00:00:00+00:00'
        r['0']['end_utc'] = '2026-10-27T00:00:01+00:00'
        with self.assertRaisesRegex(ValueError, 'historical'):
            p.cost_totals(c, ['r'], [1, 2, 3], lambda ref: r[ref['path']])

    def test_no_j_for_no_new_candidates(self):
        c, r = self.fixture()
        c['revisions'][0]['new_candidates'] = 0
        c['revisions'][0]['stages'].pop()
        self.assertEqual(p.cost_totals(c, ['r'], [1, 2, 3], lambda ref: r[ref['path']])['r']['total_ns'], 4_000_000_000)


class ProofTests(unittest.TestCase):
    def test_known_proof_codes(self):
        for r in ('closed_cone_unsat', 'constant_input_mismatch', 'predicate_cone_unsat'):
            self.assertEqual(p.guarantee(r), 'input_independent')
        self.assertEqual(p.guarantee('closed_cone_unsat', 'o0_closed_cone', 'bit_decomposition_interval'), 'input_independent')
        self.assertEqual(p.guarantee('local_constraint_refutation'), 'constructed_input_only')
        self.assertEqual(p.guarantee('excluded_in_context'), 'unclassified')

    def test_banyan_does_not_guess(self):
        row = {'revision_id': 'banyan-fixed', 'method': 'S', 'requests': 24,
               'request_statuses': {'completed': 24}, 'excluded_observed_once': True}
        result = p.recount_banyan({'engine': 'v2.2', 'development_pair_observations': [row]})[0]
        self.assertIsNone(result['input_independent'])
        self.assertIsNone(result['constructed_input_only'])

    def test_protected_path(self):
        for name in ('runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json',
                     'runs/n6-b6h-2026-10-24.noindex/x.json', 'docs/../target/x'):
            with self.assertRaises(ValueError):
                p.safe_path(p.ROOT / name)


class PlanTests(unittest.TestCase):
    def test_new_items_use_strict_vulnerable_only(self):
        def bug(item, w=False, split=False):
            methods = {}
            for name, l1 in [('W', w), ('S', split)]:
                methods[name] = {'vulnerable': {'L1_observed': l1,
                    'definition_outside_ambiguous_location': False,
                    'mixed_statuses_definition_outside': False},
                    'revisions': [{'revision_id': 'aq-' + item, 'kind': 'vulnerable',
                                   'observed_statuses': ['L1'] if l1 else []}]}
            return {'methods': methods}
        old = {'a': bug('a', w=True), 'b': bug('b'), 'c': bug('c')}
        current = {'a': bug('a', split=True), 'b': bug('b', split=True), 'c': bug('c')}
        with patch.object(p, 'strict_rows', side_effect=[old, current]):
            self.assertEqual(p.new_discoveries({}, {}, {}), {'b': ['aq-b']})

    def test_required_plan_selects_only_new_revision(self):
        spec = {'method': 'whole', 'targets': [{}], 'initial_seed': 1, 'concurrency': 1,
                'memory_cap_bytes': 1024, 'campaign_id': 'frozen'}
        queue = {'units': [{'identifier': r, 'seed': seed, 'whole_spec': f'{r}-{seed}',
                            'whole_spec_sha256': f'{r}-{seed}'}
                           for r in ['r0', 'r1'] for seed in [1, 2, 3]]}
        reg = {'revision_ids': ['r0', 'r1'], 'seeds': [1, 2, 3],
               'sources': {'baseline_strict': {'path': 'base'}, 'queue': {'path': 'queue'}}}
        def load(ref):
            if ref['path'] == 'queue':
                return queue
            if ref['path'] in ('base', 'costs'):
                return {}
            return dict(spec, initial_seed=int(ref['path'][-1]))
        with patch.object(s, 'audited_score', return_value={}), patch.object(s, 'read', side_effect=load), \
                patch.object(p, 'new_discoveries', return_value={'bug': ['r1']}), \
                patch.object(p, 'cost_totals', return_value={'r1': {'total_ns': 6_000_000_000}}):
            plan = s.make_w_plan({'costs': {'path': 'costs'}}, reg)
        self.assertEqual([(j['revision'], j['seed']) for j in plan['jobs']], [('r1', 1), ('r1', 2), ('r1', 3)])
        self.assertEqual({j['budget_seconds'] for j in plan['jobs']}, {2.0})

    def test_b_class_proof_rows_crosscheck(self):
        proof = 'closed_cone_unsat | o0_closed_cone | bit_decomposition_interval'
        row = {'request_id': 'r', 'class_index_zero_based': 0, 'proof_type': proof}
        d = {'engines': {'v': {'excluded_classes': [row], 'proof_counts': {proof: 1},
                              'expected_total': 1, 'status_counts': {'completed': 1}}}}
        self.assertEqual(p.recount_b(d)[0]['input_independent'], 1)
        d['engines']['v']['excluded_classes'].append(copy.deepcopy(row))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            p.recount_b(d)


if __name__ == '__main__':
    unittest.main()
