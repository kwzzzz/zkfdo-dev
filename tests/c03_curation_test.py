"""Pure C-03 metadata regressions; no preparation or repository execution."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/c03_curation.py"
SPEC = importlib.util.spec_from_file_location("c03_curation", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SHA = "a" * 64

COLLECTION_SPEC = importlib.util.spec_from_file_location(
    "c03_collection", MODULE_PATH.with_name("collect_c03_corpus.py"))
COLLECTION = importlib.util.module_from_spec(COLLECTION_SPEC)
COLLECTION_SPEC.loader.exec_module(COLLECTION)
REVIEW_SPEC = importlib.util.spec_from_file_location(
    "c03_role_review", MODULE_PATH.with_name("review_c03_curation.py"))
REVIEW = importlib.util.module_from_spec(REVIEW_SPEC)
REVIEW_SPEC.loader.exec_module(REVIEW)


class CurationTests(unittest.TestCase):
    def evidence(self, text, kind="readme"):
        return MODULE.make_evidence(text, kind, "metadata/README.md", SHA, 3)

    def test_sheet_excludes_example_preserves_claims_and_no_collection_date(self):
        text = ('항목,예시\n저장소 URL,https://github.com/org/repo\n,\n'
                '항목,1\n저장소 URL,http://github.com/Owner/Repo\n'
                '회로 폴더 위치,"circuits, test/mocks"\n'
                '실제 쓰이는 근거 (있으면 링크),배포는 안돼있는듯\n'
                'circom 버전 (pragma 한 줄만 보면 됨),"2.0.0, 2.1.5 혼합"\n'
                '찾은 곳,GitHub\n')
        rows = MODULE.parse_team_sheet(text, "runs/team-sheet/sheet.csv", SHA)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["repository_key"], "owner/repo")
        self.assertEqual(rows[0]["circom_version_declared"], "2.0.0, 2.1.5 혼합")
        self.assertEqual(rows[0]["field_source_lines"]["usage_evidence_declared"], 7)
        self.assertIsNone(rows[0]["collection_time_declared"])
        self.assertFalse(rows[0]["declarations_verified"])

    def test_missing_url_and_duplicate_repo_rows_stay_in_denominator(self):
        text = ('항목,1\n저장소 URL,https://github.com/a/b\n'
                '항목,2\n저장소 URL,https://github.com/A/B\n'
                '항목,3\n회로 폴더 위치,circuits\n')
        rows = MODULE.parse_team_sheet(text, "sheet.csv", SHA)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["duplicate_of_sheet_item"], 1)
        self.assertIsNone(rows[2]["repository_key"])
        self.assertIn("repository_url_declared", rows[2]["missing_fields"])

    def test_duplicate_fields_or_item_numbers_are_not_silently_overwritten(self):
        for text in ("항목,1\n저장소 URL,a/b\n저장소 URL,a/c\n",
                     "항목,1\n저장소 URL,a/b\n항목,1\n저장소 URL,a/c\n"):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                MODULE.parse_team_sheet(text, "sheet.csv", SHA)

    def test_repository_urls_are_not_readme_urls_or_foreign_hosts(self):
        for name in ("https://github.com.evil/a/b", "https://github.com/a/b/blob/main/README.md",
                     "https://github.com@evil/a/b", "a/b/c", "../repo"):
            with self.assertRaises(ValueError):
                MODULE.normalize_github_repo(name)
        self.assertEqual(MODULE.normalize_github_repo("https://github.com/A/B.git/"), "a/b")

    def test_verified_rename_matches_and_fork_is_not_identity(self):
        records = [{"full_name": "old/repo", "canonical_full_name": "new/repo",
                    "canonical_resolution": "github_metadata", "source_spellings": ["old/repo"],
                    "lineage": {"fork": True, "parent": "parent/repo"}}]
        rows = [{"sheet_item": i, "repository_key": key} for i, key in
                enumerate(["old/repo", "new/repo", "parent/repo"], 1)]
        result = MODULE.sheet_overlap(rows, records)
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["rows"][2]["status"], "not_listed")
        self.assertEqual(result["rows"][2]["listed_forks_of_sheet_repository"], ["old/repo"])

    def test_unverified_canonical_name_cannot_create_overlap(self):
        record = {"full_name": "old/repo", "canonical_full_name": "other/repo"}
        result = MODULE.sheet_overlap([{"sheet_item": 1, "repository_key": "other/repo"}], [record])
        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(MODULE.identity_links(record)["unverified_spellings"], ["other/repo"])

    def test_ambiguous_canonical_matches_not_counted_as_one(self):
        records = [{"full_name": "owner/repo"}, {"full_name": "OWNER/REPO"}]
        result = MODULE.sheet_overlap([{"sheet_item": 1, "repository_key": "owner/repo"}], records)
        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["ambiguous_count"], 1)

    def test_preparation_labels_do_not_affect_overlap_or_exposure(self):
        base = {"full_name": "owner/repo"}
        rows = [{"sheet_item": 1, "repository_key": "owner/repo"}]
        altered = dict(base, inclusion={"status": "excluded"}, preparation={"status": "failed"})
        self.assertEqual(MODULE.sheet_overlap(rows, [base]), MODULE.sheet_overlap(rows, [altered]))
        self.assertEqual(MODULE.compare_exposure(base, ["owner/repo"]),
                         MODULE.compare_exposure(altered, ["owner/repo"]))

    def test_exposure_alias_parent_and_organization_have_distinct_meanings(self):
        metadata = {"full_name": "old/repo", "canonical_full_name": "new/repo",
                    "canonical_resolution": "github_metadata",
                    "lineage": {"fork": True, "parent": {"full_name": "known/parent"}}}
        result = MODULE.compare_exposure(metadata,
                                         [{"full_name": "new/repo"}, {"full_name": "known/parent"},
                                          {"full_name": "old/unrelated"}], ["known/parent"])
        self.assertTrue(result["known_bug_listed_direct_or_alias"])
        self.assertTrue(result["fork_family_exposure_match"])
        self.assertFalse(result["development_used_direct_or_alias"])
        self.assertEqual(len(result["catalog_matches"]), 2)
        self.assertFalse(result["never_exposed_claim"])

    def test_roles_need_evidence_and_do_not_verify_deployment(self):
        expectations = {"This is a circuit library.": "library",
                        "This is a benchmark for circuit compilers.": "tool_benchmark",
                        "This is an educational example.": "education_example",
                        "These circuits are used by the payment protocol.": "production"}
        for text, category in expectations.items():
            result = MODULE.classify_repository([self.evidence(text)])
            self.assertEqual(result["classification"], category)
            self.assertFalse(result["production_use_verified"])
            self.assertEqual(result["evidence"][0]["source_sha256"], SHA)

    def test_topics_and_function_description_are_not_production_evidence(self):
        for evidence in ([self.evidence("production library", "topics")],
                         [self.evidence("Verifies ed25519 digital signatures.")], []):
            self.assertEqual(MODULE.classify_repository(evidence)["classification"], "unknown")

    def test_conflicting_roles_preserved_as_unknown(self):
        result = MODULE.classify_repository([self.evidence("This is a library."),
                                             self.evidence("This is an educational example.")])
        self.assertEqual(result["classification"], "unknown")
        self.assertEqual(result["matched_categories"], ["education_example", "library"])

    def test_proposed_or_negated_deployment_is_not_production(self):
        for text in ("This can be deployed on mainnet.", "This is not deployed in production.",
                     "프로토콜 공식 회로이나 배포는 안돼있는듯"):
            result = MODULE.classify_repository([self.evidence(text, "csv")])
            self.assertEqual(result["classification"], "unknown")

    def test_negated_roles_are_not_positive_evidence(self):
        for text in ("This is not a library.", "This is not a benchmark.",
                     "This is not an educational project."):
            self.assertEqual(MODULE.classify_repository([self.evidence(text)])["classification"], "unknown")

    def test_csv_claims_keep_lower_evidence_level(self):
        result = MODULE.classify_repository([self.evidence("ZK 개발 라이브러리", "csv")])
        self.assertEqual(result["classification"], "library")
        self.assertEqual(result["evidence_level"], "csv_claim_only")

    def test_provenance_required_and_no_multiline_payload(self):
        for sha in ("", "a" * 63, "x" * 64):
            with self.assertRaisesRegex(ValueError, "sha256"):
                MODULE.make_evidence("This is a library.", "readme", "README.md", sha)
        with self.assertRaisesRegex(ValueError, "one_metadata_sentence"):
            self.evidence("Sentence one.\nSentence two.")


class SelectionTests(unittest.TestCase):
    def test_config_addition_matches_confirmed_maci_rename(self):
        old = {"full_name": "privacy-scaling-explorations/maci",
               "canonical_full_name": "privacy-ethereum/maci",
               "canonical_resolution": "github_metadata", "source_spellings": [],
               "inclusion": {"status": "excluded"}}
        selected = COLLECTION.make_selection({"repositories": [old]}, [])
        self.assertEqual(len(selected), 1)
        self.assertTrue(selected[0]["config_addition"])
        self.assertEqual(selected[0]["full_name"], "privacy-ethereum/maci")

    def test_team_retains_old_date_excluded_repository_and_sha(self):
        old = {"full_name": "team/old", "canonical_full_name": "team/old",
               "inclusion": {"status": "excluded", "reasons": ["old_date"]},
               "commit_sha": "b" * 40}
        sheet = [{"sheet_item": 1, "repository_key": "team/old",
                  "repository_url_declared": "https://github.com/team/old"}]
        selected = COLLECTION.make_selection({"repositories": [old]}, sheet)
        self.assertEqual(len(selected), 1)
        self.assertFalse(selected[0]["c02_included"])
        self.assertEqual(selected[0]["c02"]["commit_sha"], "b" * 40)
        self.assertEqual(selected[0]["team_rows"], sheet)

    def test_team_membership_does_not_duplicate_included_repository(self):
        old = {"full_name": "team/shared", "inclusion": {"status": "included"}}
        sheet = [{"sheet_item": 1, "repository_key": "team/shared",
                  "repository_url_declared": "http://github.com/team/shared"}]
        selected = COLLECTION.make_selection({"repositories": [old]}, sheet)
        self.assertEqual(len(selected), 1)
        self.assertTrue(selected[0]["c02_included"])
        self.assertEqual(len(selected[0]["team_rows"]), 1)

    def test_tree_metadata_retains_submodule_and_symlink_modes(self):
        raw = (b"160000 commit " + b"a" * 40 + b"\tdependency\0"
               b"120000 blob " + b"b" * 40 + b"\talias.circom\0")
        tree = COLLECTION.parse_tree(raw)
        self.assertEqual(tree["dependency"]["kind"], "commit")
        self.assertEqual(tree["alias.circom"]["mode"], "120000")


class PurposeReviewTests(unittest.TestCase):
    def test_wrapped_purpose_sentence_does_not_include_next_bullet_or_html(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "README.md"
            source.write_text("This application sends\nprivate messages.\n</p>\n- A dependency is a library.\n")
            with patch.object(REVIEW.collection, "ROOT", root):
                evidence = REVIEW.paragraph_sentence(source, 1)
            self.assertEqual(evidence["text"], "This application sends private messages.")
            self.assertEqual(evidence["line"], 1)

    def test_purpose_review_never_certifies_deployment(self):
        row = {"classification": {"classification": "unknown"}}
        evidence = MODULE.make_evidence("This is a voting protocol.", "readme", "README.md", SHA, 1)
        REVIEW.apply_review(row, "production", evidence, "protocol purpose")
        self.assertFalse(row["classification"]["production_use_verified"])
        self.assertFalse(row["classification"]["preparation_results_accessed"])
        self.assertEqual(row["classification"]["evidence"], [evidence])


if __name__ == "__main__":
    unittest.main()
