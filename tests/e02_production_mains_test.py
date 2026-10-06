import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("e02", ROOT / "scripts/e02_production_mains.py")
E02 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E02)


class E02RulesTest(unittest.TestCase):
    def test_role_rule_is_path_based_and_keeps_denominator(self):
        cases = {
            "source_main:circuits/main.circom": "deployment_main",
            "source_main:circuits/tests/main.circom": "test_mock_harness",
            "source_main:circuits/payment_mock.circom": "test_mock_harness",
            "config:pkg/circomkit.json:production": "deployment_main",
            "config:pkg/circomkit.json:example-proof": "test_mock_harness",
        }
        self.assertEqual({key: E02.classify_role(key)[0] for key in cases}, cases)

    def test_static_paths_resolve_with_general_anchors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "circuits/node_modules/circomlib/circuits").mkdir(parents=True)
            (root / "circuits/scripts/build").mkdir(parents=True)
            (root / "circuits/package.json").write_text('{}\n')
            (root / "circuits/scripts/build/build.sh").write_text(
                'circom x.circom \\\n+  -l "circuits/node_modules/circomlib/circuits"\n'
            )
            (root / "node_modules/circomlib/circuits").mkdir(parents=True)
            (root / "pkg").mkdir()
            (root / "pkg/circomkit.json").write_text(json.dumps({
                "include": ["../node_modules", "../node_modules/circomlib/circuits"]
            }))
            accepted, _ = E02.derive_library_evidence(root)
            paths = {row["path"] for row in accepted}
            self.assertIn(str((root / "circuits/node_modules/circomlib/circuits").resolve()), paths)
            self.assertIn(str((root / "node_modules/circomlib/circuits").resolve()), paths)

    def test_variables_and_missing_directories_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "build.sh").write_text('circom x.circom -l "$LIB" -l missing\n')
            accepted, rejected = E02.derive_library_evidence(root)
            self.assertEqual(accepted, [])
            self.assertTrue(any(row["reason"] == "nonliteral_or_absolute" for row in rejected))
            self.assertTrue(any(row["reason"] == "no_existing_directory_under_checkout" for row in rejected))


if __name__ == "__main__":
    unittest.main()
