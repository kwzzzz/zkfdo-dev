"""Source-only tests for the corrected B6e E2 duplicate criterion."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_b6e_e2_equivalence as audit  # noqa: E402


def source_pair(original_count: int, staged_count: int,
                failures: list[str]) -> dict[str, object]:
    duplicates = {"T": original_count} if original_count > 1 else {}
    staged_duplicates = {"T": staged_count} if staged_count > 1 else {}
    return {"pair_id": "r-p", "revision_id": "r", "queue_orders": [0, 1],
            "e1_status": "pass", "e2_status": "pass" if not failures else "fail",
            "failures": failures, "main_template": "T",
            "original_main_template_file_count": original_count,
            "staged_main_template_file_count": staged_count,
            "original_duplicate_template_names": duplicates,
            "staged_duplicate_template_names": staged_duplicates}


def mapped_files(n: int, sha: str = "a" * 64) -> list[dict[str, str]]:
    return [{"original": f"/original/{i}.circom",
             "staged": f"/unit/{i}.circom",
             "original_sha256": sha, "staged_sha256": sha}
            for i in range(n)]


class E2CriterionTest(unittest.TestCase):
    def test_unique_main_passes(self) -> None:
        row = audit.classify_b_pair(source_pair(1, 1, []), [])
        self.assertEqual(row["status"], "pass")
        self.assertFalse(row["original_duplicate"])

    def test_original_duplicate_with_one_to_one_equal_bytes_passes(self) -> None:
        old = source_pair(2, 2, [audit.OLD_MAIN_COUNT_FAILURE])
        row = audit.classify_b_pair(old, mapped_files(2))
        self.assertEqual(row["status"], "pass", row["reasons"])
        self.assertTrue(row["original_duplicate"])

    def test_new_duplicate_fails(self) -> None:
        old = source_pair(1, 2, [audit.OLD_MAIN_COUNT_FAILURE,
                                 "duplicate template name counts differ"])
        self.assertEqual(audit.classify_b_pair(old, [])["status"], "fail")

    def test_duplicate_changed_bytes_fails(self) -> None:
        old = source_pair(2, 2, [audit.OLD_MAIN_COUNT_FAILURE])
        files = mapped_files(2)
        files[1]["staged_sha256"] = "b" * 64
        row = audit.classify_b_pair(old, files)
        self.assertEqual(row["status"], "fail")
        self.assertIn("main declaration source bytes differ", row["reasons"])

    def test_duplicate_mapping_alias_fails(self) -> None:
        old = source_pair(2, 2, [audit.OLD_MAIN_COUNT_FAILURE])
        files = mapped_files(2)
        files[1]["staged"] = files[0]["staged"]
        row = audit.classify_b_pair(old, files)
        self.assertEqual(row["status"], "fail")

    def test_other_old_e2_failure_still_fails(self) -> None:
        old = source_pair(2, 2, [audit.OLD_MAIN_COUNT_FAILURE,
                                 "template declaration files differ for T"])
        self.assertEqual(audit.classify_b_pair(old, mapped_files(2))["status"], "fail")

    def test_e1_failure_still_fails(self) -> None:
        old = source_pair(2, 2, [audit.OLD_MAIN_COUNT_FAILURE])
        old["e1_status"] = "fail"
        self.assertEqual(audit.classify_b_pair(old, mapped_files(2))["status"], "fail")


if __name__ == "__main__":
    unittest.main()
