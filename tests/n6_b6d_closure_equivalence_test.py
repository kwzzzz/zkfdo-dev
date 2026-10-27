"""Small source-only checks for the B6d closure-equivalence audit."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_b6d_closure_equivalence as audit  # noqa: E402


class ClosureEquivalenceTest(unittest.TestCase):
    def test_request_projection_does_not_open_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = root / "request.json"
            request.write_text(json.dumps({
                "source_root": str(root),
                "component_wrapper": str(root / "wrapper.circom"),
                "entrypoint": str(root / "entry.circom"),
                "library_paths": [str(root / "lib")],
                "candidate": str(root / "nonexistent-candidate.json"),
            }), encoding="utf-8")
            projected = audit.source_request(request)
            self.assertEqual(set(projected), {
                "source_root", "component_wrapper", "entrypoint", "library_paths"})

    def test_template_scan_ignores_comments_strings_and_inner_body(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.circom"
            source.write_text('''/* template Comment() {} */
                template Outer() {
                    var text = "template String() {}";
                    function inner() { var template = 1; }
                }
                template custom Real(n) { signal input in; }
            ''', encoding="utf-8")
            self.assertEqual(audit.template_names(source), ["Outer", "Real"])

    def test_main_template_name_matches_fixed_engine_rule(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "wrapper.circom"
            source.write_text('''// component main = Wrong();
                template T() { signal input in; }
                component main = T();
            ''', encoding="utf-8")
            self.assertEqual(audit.main_template_name(source), "T")

    def test_template_name_declarations_are_counted_per_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "first.circom"
            second = root / "second.circom"
            first.write_text("template T() {}\ntemplate T() {}\n", encoding="utf-8")
            second.write_text("template T() {}\ntemplate U() {}\n", encoding="utf-8")
            self.assertEqual(audit.declarations([str(first), str(second)], {}), {
                "T": [str(first), str(second)], "U": [str(second)]})

    def test_include_rewrite_preserves_all_other_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clone = root / "clone"
            project = root / "unit/project"
            clone.mkdir()
            project.mkdir(parents=True)
            (clone / "dependency.circom").write_text("template D() {}\n", encoding="utf-8")
            (project / "dependency.circom").write_text("template D() {}\n", encoding="utf-8")
            old = root / "old.circom"
            new = root / "new.circom"
            old.write_text(f'include "{clone / "dependency.circom"}";\n'
                           'component main = D();\n', encoding="utf-8")
            new.write_text(f'include "{project / "dependency.circom"}";\n'
                           'component main = D();\n', encoding="utf-8")
            pair = {"original_clone_root": str(clone), "project_root": str(project)}
            self.assertEqual(audit.include_only_change(old, new, pair), [1])
            new.write_text(f'include "{project / "dependency.circom"}";\n'
                           'component main = U();\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-include byte difference"):
                audit.include_only_change(old, new, pair)

    def test_source_pair_rejects_duplicate_main_template_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clone = root / "clone"
            project = root / "unit/project"
            old_prep = root / "old-preparation"
            new_prep = root / "unit/preparation"
            for directory in (clone, project, old_prep, new_prep):
                directory.mkdir(parents=True)
            old_entry = clone / "entry.circom"
            new_entry = project / "entry.circom"
            old_wrapper = old_prep / "wrapper.circom"
            new_wrapper = new_prep / "wrapper.circom"
            for path in (old_entry, new_entry):
                path.write_text("template T() {}\n", encoding="utf-8")
            for path in (old_wrapper, new_wrapper):
                path.write_text("template T() {}\ncomponent main = T();\n",
                                encoding="utf-8")
            pair = {"pair_id": "pair", "revision_id": "revision", "queue_orders": [1],
                    "source_root": str(root / "unit"),
                    "original_clone_root": str(clone), "project_root": str(project),
                    "original_preparation_root": str(old_prep),
                    "preparation_root": str(new_prep), "external_library_paths": [],
                    "original_wrapper": str(old_wrapper), "wrapper": str(new_wrapper)}
            old_request = {"component_wrapper": str(old_wrapper)}
            new_request = {"component_wrapper": str(new_wrapper)}
            old_answer = {"error": None, "wrapper": [str(old_wrapper)],
                          "entrypoint": [str(old_entry)],
                          "union": [str(old_wrapper), str(old_entry)]}
            new_answer = {"error": None, "wrapper": [str(new_wrapper)],
                          "entrypoint": [str(new_entry)],
                          "union": [str(new_wrapper), str(new_entry)]}
            result = audit.compare_source_pair(old_request, new_request, pair,
                                               old_answer, new_answer, {})
            self.assertEqual(result["e1_status"], "pass", result["failures"])
            self.assertEqual(result["e2_status"], "fail")
            self.assertEqual(result["original_main_template_file_count"], 2)


if __name__ == "__main__":
    unittest.main()
