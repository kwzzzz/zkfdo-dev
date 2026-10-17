import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import n6_j4b_regression as regression

class Gates(unittest.TestCase):
    def test_self_only_guard_is_not_bypassed_by_independent_predicate(self):
        row = {'request_id': 'r', 'revision_id': 'inference-original', 'exclusion_kind': '자기 배제만'}
        result = {'request_id': 'r', 'classes': [{'verdict': 'excluded_in_context', 'assumption_predicate_verdict': 'assumption_violation_reachable'}]}
        with self.assertRaises(regression.RegressionStop):
            regression.check_result(result, {'exclusion_50': {'requests': [row]}, 'l1_zero_revisions': []})
        result['classes'][0]['assumption_predicate_verdict'] = 'unknown'
        regression.check_result(result, {'exclusion_50': {'requests': [row]}, 'l1_zero_revisions': []})

    def test_partial_fix_is_reportable_but_not_a_zero_guard(self):
        regression.check_result({'request_id':'p','classes':[{'verdict':'entrypoint_violation'}]},
            {'exclusion_50':{'requests':[]},'l1_zero_revisions':[{'requests':[]}]})

if __name__ == '__main__':
    unittest.main()
