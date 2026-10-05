"""Metadata census regressions: prevent fabricated mains and silent denominator loss."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts/collect_c02_repositories.py'
SPEC = importlib.util.spec_from_file_location('c02_collection', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CollectionTests(unittest.TestCase):
    def test_comments_strings_and_public_main(self):
        source = '''// component main = Fake();
/* component main = AlsoFake(); */
include "component main = PathText();";
component /* metadata */ main { public [x] } = Real(8);
'''
        self.assertEqual(MODULE.main_declarations(source), [{'line': 4, 'template': 'Real'}])

    def test_unterminated_comment_keeps_inventory_unknown(self):
        with self.assertRaisesRegex(ValueError, 'unterminated_block_comment'):
            MODULE.main_declarations('/* component main = Fake();')

    def test_multiple_main_declarations_not_silently_merged(self):
        declarations = MODULE.main_declarations('component main=First();\ncomponent main=Second();')
        self.assertEqual([d['template'] for d in declarations], ['First', 'Second'])

    def test_noassertion_alone_is_not_license_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = MODULE.license_evidence(Path(temporary), {}, {'spdx_id': 'NOASSERTION'})
        self.assertEqual(result['status'], 'unknown')

    def test_nested_license_does_not_license_entire_repo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'vendor').mkdir()
            (root / 'vendor/LICENSE').write_text('MIT')
            result = MODULE.license_evidence(root, {'vendor/LICENSE': {}}, None)
        self.assertEqual(result['status'], 'absent')

    def test_explicit_root_readme_declaration_qualifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'README.md').write_text('This project is licensed under the MIT license.\n')
            result = MODULE.license_evidence(root, {'README.md': {}}, None)
        self.assertEqual(result['status'], 'declared')

    def test_unrelated_dependency_license_does_not_qualify(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'README.md').write_text('A dependency is licensed under MIT.\n')
            result = MODULE.license_evidence(root, {'README.md': {}}, None)
        self.assertEqual(result['status'], 'unknown')

    def test_known_main_qualifies_despite_unknown_other_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            p = root / 'metadata.json'
            row = self.row()
            row['entrypoints'] = [{'path': 'main.circom'}]
            row['entrypoint_inventory'] = {'status': 'incomplete', 'errors': [{'reason': 'symlink'}]}
            p.write_text(json.dumps(row))
            with patch.object(MODULE, 'ROOT', root):
                result = MODULE.refined_metadata(row, p)
            self.assertEqual(result['inclusion']['status'], 'included')
            self.assertEqual(result['entrypoint_inventory']['status'], 'incomplete')
            self.assertEqual(json.loads(p.read_text()), row)

    def test_submodule_absence_not_complete_no_main(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            p = root / 'metadata.json'
            row = self.row()
            row['inclusion'] = {'status': 'excluded', 'reasons': ['no_component_main_declaration']}
            row['uninitialized_submodule_paths'] = ['circuits']
            p.write_text(json.dumps(row))
            with patch.object(MODULE, 'ROOT', root):
                result = MODULE.refined_metadata(row, p)
            self.assertEqual(result['inclusion']['status'], 'unknown')
            self.assertTrue(result['entrypoint_inventory']['potential_unenumerated_submodule_entrypoints'])

    def test_casefold_merge_preserves_rank_and_every_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / 'raw'
            base.mkdir()
            for page in (1, 2):
                items = [{'full_name': f'owner/repo{page}_{index}',
                          'html_url': f'https://github.com/owner/repo{page}_{index}'} for index in range(100)]
                if page == 1:
                    items[0] = {'full_name': 'Owner/Shared', 'html_url': 'https://github.com/Owner/Shared'}
                (base / f'github-search-page-{page}-network.json').write_text(
                    json.dumps({'items': items, 'incomplete_results': False}))
            catalog = {'projects': [{'full_name': 'owner/shared', 'url': 'https://github.com/owner/shared',
                                     'source_memberships': ['zkbugs', 'sok_2026'],
                                     'circom_source_memberships': ['zkbugs', 'sok_2026']}],
                       'development_exposure': {'projects': [{'full_name': 'OWNER/SHARED'}],
                                                'prior_exposure_metadata': [], 'uncertain_families': []}}
            (base / 'catalog_sources.json').write_text(json.dumps(catalog))
            with patch.object(MODULE, 'ROOT', root):
                result = MODULE.merge_sources(base)
            self.assertEqual(len(result), 200)
            shared = next(row for row in result if row['full_name'] == 'Owner/Shared')
            self.assertEqual(set(shared['source_memberships']), {'github_top200', 'zkbugs', 'sok_2026'})
            self.assertEqual(shared['github_ranks'], [1])
            self.assertTrue(shared['exposure']['development_used'])
            self.assertTrue(shared['exposure']['known_bug_listed'])

    def test_incomplete_search_does_not_shrink_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'catalog_sources.json').write_text('{}')
            (root / 'github-search-page-1-network.json').write_text(
                json.dumps({'items': [], 'incomplete_results': True}))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                MODULE.merge_sources(root)

    @staticmethod
    def row():
        return {'entrypoints': [], 'entrypoint_inventory': {'status': 'complete'}, 'recent_commit': True,
                'commit_sha': 'a' * 40, 'errors': [], 'license': {'status': 'declared'},
                'inclusion': {'status': 'unknown', 'reasons': ['entrypoint_inventory_incomplete']}}


if __name__ == '__main__':
    unittest.main()
