import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import n6_j4b_regression_v2 as regression

class ResumeGates(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.output = self.base / 'output'
        self.output.mkdir()
        self.stop = self.base / 'STOP.json'
        self.lists = {'exclusion_50': {'requests': [{'request_id': 'r', 'exclusion_kind': '자기 배제만'}]},
                      'l1_zero_revisions': []}
        self.index = self.base / 'index.json'
        self.index.write_text(json.dumps({'requests': []}))

    def run_fake(self, fake):
        with patch.object(regression.runner, 'execute', side_effect=fake), \
             patch.object(regression.runner, 'successful_result_issue', return_value=None):
            return regression.execute_guarded(self.index, 'hash', self.base, self.output, self.lists, self.stop)

    def test_resumed_result_stops_before_another_request(self):
        def fake(*args, **kwargs):
            regression.runner.successful_result_issue({}, {}, {'request_id': 'r', 'classes': [{'verdict': 'entrypoint_violation'}]})
            self.fail('resumed forbidden L1 was allowed to continue')
        with self.assertRaises(regression.RegressionStop):
            self.run_fake(fake)
        self.assertTrue(self.stop.exists())

    def test_preexisting_join_is_checked_before_any_engine_call(self):
        joined = self.output / 'instances.json'
        joined.write_text(json.dumps({'classes': [{'request_id': 'r', 'effective': 'assumption_violation_reachable'}]}))
        (self.output / 'state.json').write_text(json.dumps({'revisions': {'main/0001': {
            'status': 'joined', 'instances_path': str(joined)}}}))
        with patch.object(regression.runner, 'execute') as execute:
            with self.assertRaises(regression.RegressionStop):
                regression.execute_guarded(self.index, 'hash', self.base, self.output, self.lists, self.stop)
            execute.assert_not_called()
        self.assertTrue(self.stop.exists())

    def test_shared_join_upgrade_is_guarded_before_saving_state(self):
        joined = self.output / 'joined.json'
        joined.write_text(json.dumps({'classes': [{'request_id': 'r', 'effective': 'assumption_violation_reachable'}]}))
        def fake(*args, **kwargs):
            regression.runner.atomic_json(self.output / 'state.json', {'revisions': {'main/0001': {
                'status': 'joined', 'instances_path': str(joined)}}})
            self.fail('joined upgrade bypassed guard')
        with self.assertRaises(regression.RegressionStop):
            self.run_fake(fake)
        self.assertFalse((self.output / 'state.json').exists())


class ResultShape(unittest.TestCase):
    def test_missing_or_wrong_request_id_and_empty_classes_are_not_negative_results(self):
        lists = {'completed_requests': [{'request': '/request.json', 'request_id': 'r'}]}
        row = {'request': '/request.json'}
        for result in [{'request_id': 'other', 'classes': [{'verdict': 'unknown'}]},
                       {'request_id': 'r', 'classes': []}]:
            with self.assertRaises(regression.runner.RunnerError):
                regression.check_binding(row, result, lists)


class ActualRunnerIntegration(unittest.TestCase):
    def setUp(self):
        from n6_j1_runner_test import JRunnerTest
        self.fixture = JRunnerTest('test_order_revision_isolation_and_resume')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.index, self.sha = self.fixture.make_index([('main','revision-a','S',1,None), ('main','revision-a','S',2,None)])
        rows = json.loads(self.index.read_text())['requests']
        self.lists = {'completed_requests': [{'request':row['request'], 'request_id':f'request-{i}'} for i,row in enumerate(rows)],
            'exclusion_50': {'requests':[{'request_id':'request-0','exclusion_kind':'자기 배제만'}]}, 'l1_zero_revisions':[]}
        self.stop = self.fixture.root / 'STOP.json'
        self.calls = []

    def lift(self, *args):
        metrics = self.fixture.fake_lift(self.calls, *args)
        result = args[1] / 'result.json'
        value = json.loads(result.read_text())
        value.update({'request_id':f"request-{args[0]['queue_order']}", 'classes':[{'verdict':'unknown'}]})
        result.write_text(json.dumps(value))
        return metrics

    def run_real(self, lift=None):
        with patch.object(regression.runner,'run_lift', side_effect=lift or self.lift), \
             patch.object(regression.runner,'join_instances', side_effect=lambda *a:self.fixture.fake_join([], *a)), \
             patch.object(regression.runner,'disk_free', return_value=100*1024**3):
            return regression.execute_guarded(self.index,self.sha,self.fixture.cache,self.fixture.output,self.lists,self.stop)

    def test_real_resume_checks_existing_request_without_running_an_engine(self):
        state = self.run_real()
        first = Path(state['requests']['0']['result_path'])
        value = json.loads(first.read_text())
        value['classes'][0]['verdict'] = 'entrypoint_violation'
        first.write_text(json.dumps(value))
        self.calls.clear()
        with self.assertRaises(regression.RegressionStop):
            self.run_real()
        self.assertEqual(self.calls, [])
        self.assertTrue(self.stop.exists())

    def test_fresh_forbidden_l1_stops_before_second_request(self):
        def bad(*args):
            metrics = self.lift(*args)
            result = args[1] / 'result.json'
            value = json.loads(result.read_text())
            value['classes'][0]['verdict']='entrypoint_violation'
            result.write_text(json.dumps(value))
            return metrics
        with self.assertRaises(regression.RegressionStop):
            self.run_real(bad)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.stop.exists())


if __name__ == '__main__':
    unittest.main()
