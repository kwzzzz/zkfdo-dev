"""Run the preserved synthetic campaign contract against v5.1 as well."""
import json
import sys
from unittest.mock import patch
import run_policy_a_engine_v5_test as previous
import run_policy_a_engine_v5_1 as runner


class CampaignV51Tests(previous.CampaignTests):
    def setUp(self):
        self.runner_patch = patch.object(previous, 'runner', runner)
        self.runner_patch.start()
        self.addCleanup(self.runner_patch.stop)
        super().setUp()

    def fake_config_module(self):
        module = super().fake_config_module()
        binding = patch.dict(sys.modules, {"zkfdo_zkfuzz_config_v2": module})
        binding.start()
        self.addCleanup(binding.stop)
        return module

    def spec(self, count=1, *, preflight=False):
        spec = super().spec(count, preflight=preflight)
        profile = self.root / 'preparation-assets.json'
        profile.write_text(json.dumps({'schema': 'zkfdo-preparation-assets-v1', 'revisions': {
            'synthetic-revision': {'revision_id': 'synthetic-revision', 'revision_commit': 'a' * 40,
                'requirements': [{'id': 'entrypoint', 'kind': 'file', 'path': 'main.circom',
                                  'sha256': runner.legacy.sha256_file(self.source / 'main.circom')}]}}}))
        spec['revision_preflights'] = [{'source_snapshot_id': 'source', 'revision_id': 'synthetic-revision',
            'revision_commit': 'a' * 40, 'profile_path': str(profile),
            'profile_sha256': runner.legacy.sha256_file(profile)}]
        return spec

    def test_missing_preflight_input_fails_before_any_command(self):
        spec = self.spec(preflight=True)
        ref = spec['revision_preflights'][0]
        profile = self.root / 'preparation-assets.json'
        catalog = json.loads(profile.read_text())
        catalog['revisions']['synthetic-revision']['requirements'].append(
            {'id': 'original-input', 'kind': 'file', 'path': 'missing-input.json'})
        profile.write_text(json.dumps(catalog))
        ref['profile_sha256'] = runner.legacy.sha256_file(profile)
        result = self.run_campaign(spec)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.calls, [])
        self.assertEqual(result['commands'], [])
        self.assertEqual(result['attempts'], [])
        self.assertEqual(result['revision_preflight']['status'], 'failed')
        receipt = json.loads((self.root / 'run/revision-preflight/0000.json').read_text())
        self.assertEqual(receipt['status'], 'preparation_assets_missing')
        self.assertEqual(receipt['failures'][0]['id'], 'original-input')

    def test_missing_preflight_snapshot_coverage_fails_before_any_command(self):
        spec = self.spec(preflight=True)
        spec['source_snapshots'].append({**spec['source_snapshots'][0], 'id': 'uncovered-source'})
        result = runner.run_campaign(spec, self.root / 'run', max_disk_bytes=8 * 2**20,
            min_free_bytes=0, command_runner=self.fake_command, purpose='discovery')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('coverage differs', result['error'])
        self.assertEqual(self.calls, [])
        self.assertEqual(result['commands'], [])
        self.assertEqual(result['attempts'], [])

    def test_request_only_overflow_in_final_sample_stops_campaign(self):
        original = runner.runtime.DiskBudget.sample

        def late_write(budget, **kwargs):
            if budget.parent is not None:
                (budget.root / 'late-output').write_bytes(b'x' * (budget.max_bytes + 1))
            return original(budget, **kwargs)

        with patch.object(runner.runtime.DiskBudget, 'sample', late_write):
            result = self.run_campaign(self.spec(), max_request_disk_bytes=2**20,
                                       tree_interval_seconds=100)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['termination_reason'], 'disk_limit')
        self.assertLess(result['disk']['current_bytes'], result['disk']['max_disk_bytes'])
        request = result['attempts'][0]
        self.assertEqual(request['status'], 'stopped')
        self.assertEqual(request['disk']['stop_reason'], 'max_disk_bytes_exceeded')
        saved = json.loads((self.root / 'run/attempts/000000/receipt.json').read_text())
        self.assertEqual(saved['status'], 'stopped')

    def test_request_clock_invalidity_survives_final_checkpoint(self):
        with patch.object(runner.runtime.platform_layer, 'clock_delta', return_value={'suspend_evidence': True}):
            result = self.run_campaign(self.spec())
        request = result['attempts'][0]
        self.assertIn('suspend_evidence', request['invalid_reasons'])
        self.assertFalse(request['measurement_valid'])
        saved = json.loads((self.root / 'run/attempts/000000/receipt.json').read_text())
        self.assertFalse(saved['measurement_valid'])

    def test_final_request_disk_observation_failure_cannot_finish_successfully(self):
        original = runner.runtime.DiskBudget.sample

        def fail_final(budget, **kwargs):
            if budget.parent is not None:
                raise runner.runtime.ObservationError('injected final request scan failure')
            return original(budget, **kwargs)

        with patch.object(runner.runtime.DiskBudget, 'sample', fail_final):
            result = self.run_campaign(self.spec(), max_request_disk_bytes=2**20)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['termination_reason'], 'request_disk_observation_failed')
        self.assertFalse(result['measurement_valid'])
        request = result['attempts'][0]
        self.assertFalse(request['measurement_valid'])
        self.assertIn('request_disk_observation_failed', request['invalid_reasons'])
