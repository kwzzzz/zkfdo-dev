"""L-05 step 5: zkFuzz stderr reports become linked candidates; the v2 runner keeps v1."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


report = load("zkfuzz_report", "zkfuzz_report.py")
v2 = load("run_policy_a_engine_v2", "run_policy_a_engine_v2.py")

P = report.BN254
CONDITION = (
    "(BoolOr (BoolAnd (Eq 1 main.c.out) (Lt main.c.in[0] main.c.in[1])) "
    "(BoolAnd (Eq 0 main.c.out) (GEq main.c.in[0] main.c.in[1])))"
)
UNEXPECTED = f"""\x1b[32mWelcome to the zkFuzz\x1b[0m
\x1b[31m╔══════════════════════════════════════════════════════════════╗\x1b[0m
\x1b[31m║\x1b[0m🚨 Counter Example:                                           \x1b[31m║\x1b[0m
\x1b[31m║\x1b[0m    \x1b[1;31m🧟 UnderConstrained (Unexpected-Input) 🧟\x1b[0m
\x1b[31m║\x1b[0m           Violated Condition:\x1b[0m {CONDITION}
\x1b[31m║\x1b[0m    \x1b[1;34m🔍 Assignment Details:\x1b[0m
\x1b[31m║\x1b[0m           ➡️ \x1b[35mmain.a\x1b[0m = \x1b[93m-1\x1b[0m
\x1b[31m║\x1b[0m           ➡️ main.c.in[0] = -1
\x1b[31m║\x1b[0m           ➡️ main.c.out = 1
\x1b[31m╚══════════════════════════════════════════════════════════════╝\x1b[0m
 ├─ Prime Number      : {P}
 ├─ Verification      : 💥 NOT SAFE 💥
"""
NONDETERMINISTIC = """║🚨 Counter Example:
║    🔥 UnderConstrained (Non-Deterministic) 🔥
║           ➡️ `main.out` is expected to be `7`
║    🔍 Assignment Details:
║           ➡️ main.out = 8
║           ➡️ main.x = 3
╚══
"""


class ReportTest(unittest.TestCase):
    def test_unexpected_input_keeps_the_condition_and_reduces_values(self):
        parsed = report.parse(UNEXPECTED)
        self.assertEqual(parsed["type"], "UnderConstrained-UnexpectedInput")
        self.assertEqual(parsed["violated_condition"], CONDITION)
        self.assertEqual(parsed["assignment"]["main.a"], str(P - 1))
        self.assertEqual(parsed["assignment"]["main.c.out"], "1")

    def test_non_deterministic_output_is_not_taken_as_an_assignment(self):
        parsed = report.parse(NONDETERMINISTIC)
        self.assertEqual(parsed["type"], "UnderConstrained-NonDeterministic")
        self.assertIsNone(parsed["violated_condition"])
        self.assertEqual(parsed["expected_output"], {"name": "main.out", "value": "7"})
        self.assertEqual(parsed["assignment"], {"main.out": "8", "main.x": "3"})

    def test_no_report_and_broken_report(self):
        self.assertIsNone(report.parse("Verification: No Counter Example Found\n"))
        with self.assertRaises(report.ReportError):
            report.parse("║🚨 Counter Example:\n║    🔍 Assignment Details:\n║  ➡️ main.a = x\n╚")

    def test_existing_p2_logs_match_their_l02_conversion(self):
        index = ROOT / "runs/l03-assumption-2026-10-02/zkemail/requests/index.json"
        if not index.exists():
            self.skipTest("ignored run data is not present")
        for row in json.loads(index.read_text())[:3]:
            request = ROOT / row["request"]
            candidate = json.loads(
                (request.parent / json.loads(request.read_text())["candidate"]["path"]).read_text()
            )
            parsed = report.parse((ROOT / row["log"]).read_text(encoding="utf-8"))
            self.assertEqual(parsed["assignment"], candidate)
            self.assertIn("main.lt[", parsed["violated_condition"])


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.attempt = Path(self.temporary.name) / "000001"
        (self.attempt / "workspace").mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def spawn(self, text):
        def original(command, attempt_dir, *arguments):
            stderr = Path(attempt_dir) / "stderr.log"
            stderr.write_text(text, encoding="utf-8")
            return {"stderr_path": stderr, "outcome": "candidate"}

        return v2.with_report_capture(original)

    def test_report_becomes_a_preserved_candidate_with_its_condition(self):
        self.spawn(UNEXPECTED)(["zkfuzz", "c.circom"], self.attempt)
        found = v2.v1.candidate_inventory(self.attempt / "workspace", ["**/*_counterexample.json"])
        self.assertEqual(list(found), [v2.REPORT_NAME])
        candidate = json.loads((self.attempt / "workspace" / v2.REPORT_NAME).read_text())
        self.assertEqual(candidate["5_flag"]["2_violated_condition"]["text"], CONDITION)
        self.assertEqual(candidate["7_assignment"]["main.a"], str(P - 1))
        link = json.loads((self.attempt / "report_link.json").read_text())
        self.assertEqual(link["status"], "linked")
        self.assertEqual(link["stderr_sha256"], candidate["zkfdo_report_link"]["log_sha256"])
        self.assertEqual(
            link["violated_condition_sha256"], hashlib.sha256(CONDITION.encode()).hexdigest()
        )
        self.assertNotIn("main.a", json.dumps(link))

    def test_save_output_mode_records_that_the_text_is_unavailable(self):
        self.spawn(UNEXPECTED)(["zkfuzz", "c.circom", "--save_output"], self.attempt)
        self.assertFalse((self.attempt / "workspace" / v2.REPORT_NAME).exists())
        link = json.loads((self.attempt / "report_link.json").read_text())
        self.assertEqual(link["status"], "unavailable_with_save_output")

    def test_stderr_report_mode_rejects_save_output_and_unmatched_globs(self):
        spec = {
            "zkfuzz_output": "stderr_report",
            "require_save_output": False,
            "targets": [{"id": "t", "command": ["zkfuzz", "{entrypoint}"]}],
            "source_snapshots": [{"id": "s", "candidate_globs": ["**/*_counterexample.json"]}],
        }
        v2.validate_report_mode(spec)
        for change in (
            {"require_save_output": True},
            {"targets": [{"id": "t", "command": ["zkfuzz", "--save_output"]}]},
            {"source_snapshots": [{"id": "s", "candidate_globs": ["**/*.wtns"]}]},
            {"zkfuzz_output": "other"},
        ):
            with self.assertRaises(v2.v1.SpecError):
                v2.validate_report_mode({**spec, **change})
        v2.validate_report_mode({})


if __name__ == "__main__":
    unittest.main()
