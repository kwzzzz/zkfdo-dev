"""Reject unsafe promotion when replaying normal inputs from witness metadata."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "normal_boundary_replay",
    Path(__file__).resolve().parents[1] / "scripts/measure_normal_boundary_replay.py",
)
normal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(normal)

FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
PASSED = {"calculation": "passed", "constraint": "passed", "export": "passed"}


class NormalBoundaryReplayTest(unittest.TestCase):
    def setUp(self):
        self.prefix = "main.left"
        self.original_symbols = {
            "main.left.in": 1, "main.left.out": 2,
            "main.right.in": 3, "main.right.out": 4,
        }
        self.wrapper_symbols = {"main.in": 1, "main.out": 2}
        self.original_witness = ["1", "2", "99", "5", "88"]

    def read(self, symbols=None, witness=None, wrapper_symbols=None,
             prefix=None, input_count=1, status=None):
        return normal.read_inputs(
            self.original_symbols if symbols is None else symbols,
            self.original_witness if witness is None else witness,
            self.wrapper_symbols if wrapper_symbols is None else wrapper_symbols,
            self.prefix if prefix is None else prefix,
            input_count,
            PASSED if status is None else status,
        )

    def compare(self, port="out", count=1, original_symbols=None,
                original_witness=None, wrapper_symbols=None,
                wrapper_witness=None, original_status=None, wrapper_status=None):
        return normal.compare_port(
            self.original_symbols if original_symbols is None else original_symbols,
            self.original_witness if original_witness is None else original_witness,
            self.wrapper_symbols if wrapper_symbols is None else wrapper_symbols,
            ["1", "2", "99"] if wrapper_witness is None else wrapper_witness,
            self.prefix, port, count,
            PASSED if original_status is None else original_status,
            PASSED if wrapper_status is None else wrapper_status,
        )

    def test_port_inference_requires_exact_scalar_or_contiguous_vector(self):
        self.assertEqual(normal.infer_port({"main.in": 1}, "main.in", 1), [""])
        self.assertEqual(normal.infer_port(
            {"main.in[1]": 2, "main.in[0]": 1, "main.out": 3}, "main.in", 2
        ), ["[0]", "[1]"])
        malformed = [
            ({}, 1),
            ({"main.in": 1}, 2),
            ({"main.in": 1, "main.in[0]": 2}, 1),
            ({"main.in[0]": 1, "main.in[2]": 2}, 2),
            ({"main.in[1]": 1}, 1),
            ({"main.in[0][0]": 1}, 1),
            ({"main.in[0]": 1}, 2),
            ({"main.in[0]": 1, "main.in[1]": 2}, 1),
            ({"main.in[01]": 1}, 1),
            ({f"main.in[{index}]": index + 1 for index in range(9)}, 9),
        ]
        for symbols, count in malformed:
            with self.subTest(symbols=symbols, count=count), self.assertRaises(normal.Unsupported):
                normal.infer_port(symbols, "main.in", count)

    def test_reused_wrapper_reads_each_call_inputs_without_using_outputs(self):
        left, left_meta = self.read()
        right, right_meta = self.read(prefix="main.right")
        self.assertEqual(left, {"in": "2"})
        self.assertEqual(right, {"in": "5"})
        self.assertEqual(left_meta["status"], "passed")
        self.assertEqual(right_meta["status"], "passed")
        # Distinct output values 99 and 88 must never replace boundary inputs.
        self.assertNotIn(left["in"], ["99", "88"])
        self.assertNotIn(right["in"], ["99", "88"])

    def test_input_payload_follows_assignment_values_not_call_name(self):
        baseline, _ = self.read()
        renamed_symbols = {
            name.replace("main.left", "main.renamed_stage"): index
            for name, index in self.original_symbols.items()
        }
        renamed, renamed_meta = self.read(
            symbols=renamed_symbols, prefix="main.renamed_stage",
        )
        self.assertEqual(renamed, baseline)
        self.assertEqual(renamed_meta["status"], "passed")
        changed_witness = list(self.original_witness)
        changed_witness[1] = "17"
        changed, changed_meta = self.read(witness=changed_witness)
        self.assertEqual(changed, {"in": "17"})
        self.assertNotEqual(changed, baseline)
        self.assertEqual(changed_meta["status"], "passed")

    def test_array_input_payload_uses_declared_index_order(self):
        symbols = {"main.left.in[1]": 1, "main.left.in[0]": 3}
        wrapper = {"main.in[0]": 1, "main.in[1]": 2}
        payload, meta = self.read(symbols=symbols, wrapper_symbols=wrapper, input_count=2)
        self.assertEqual(payload, {"in": ["5", "2"]})
        self.assertEqual(meta["status"], "passed")

    def test_inputs_are_not_read_until_all_original_stages_pass(self):
        for stage in PASSED:
            for outcome in ("failed", "not_run", "unsupported", None):
                status = dict(PASSED)
                if outcome is None:
                    status.pop(stage)
                else:
                    status[stage] = outcome
                with self.subTest(stage=stage, outcome=outcome):
                    payload, meta = normal.read_inputs(
                        self.original_symbols, None, self.wrapper_symbols,
                        self.prefix, 1, status,
                    )
                    self.assertIsNone(payload)
                    self.assertEqual(meta["status"], "not_run")

    def test_missing_eliminated_and_out_of_range_inputs_are_unsupported(self):
        for symbols in ({}, {"main.left.in": -1}, {"main.left.in": 5}):
            with self.subTest(symbols=symbols):
                payload, meta = self.read(symbols=symbols)
                self.assertIsNone(payload)
                self.assertEqual(meta["status"], "unsupported")

    def test_one_unavailable_input_keeps_each_leaf_reason_without_partial_payload(self):
        payload, meta = self.read(
            symbols={"main.left.in[0]": 1, "main.left.in[1]": -1},
            wrapper_symbols={"main.in[0]": 1, "main.in[1]": 2},
            input_count=2,
        )
        self.assertIsNone(payload)
        self.assertEqual(meta["status"], "unsupported")
        self.assertEqual(meta["expected_leaves"], 2)
        self.assertEqual(len(meta["leaves"]), 2)
        self.assertEqual([leaf["status"] for leaf in meta["leaves"]],
                         ["passed", "unsupported"])
        for leaf in meta["leaves"]:
            self.assertIn("reason", leaf)
        self.assertTrue(meta["leaves"][1]["reason"])

    def test_shape_mismatch_does_not_emit_a_partial_or_scalar_payload(self):
        vector = {"main.left.in[0]": 1, "main.left.in[1]": 3}
        malformed_wrappers = [
            {"main.in": 1},
            {"main.in[0]": 1},
            {"main.in[0]": 1, "main.in[1]": 2, "main.in[2]": 3},
            {"main.in[0][0]": 1, "main.in[0][1]": 2},
        ]
        for wrapper in malformed_wrappers:
            with self.subTest(wrapper=wrapper):
                payload, meta = self.read(
                    symbols=vector, wrapper_symbols=wrapper, input_count=2,
                )
                self.assertIsNone(payload)
                self.assertEqual(meta["status"], "unsupported")
        payload, meta = self.read(
            symbols={"main.left.in[0]": 1}, wrapper_symbols={"main.in": 1},
        )
        self.assertIsNone(payload)
        self.assertEqual(meta["status"], "unsupported")

    def test_noncanonical_field_input_is_not_normalized_or_replayed(self):
        for value in ("-1", str(FIELD), str(FIELD + 1), "not-a-number", "01", "+1"):
            witness = list(self.original_witness)
            witness[1] = value
            with self.subTest(value=value):
                payload, meta = self.read(witness=witness)
                self.assertIsNone(payload)
                self.assertEqual(meta["status"], "unsupported")

    def test_matching_output_requires_both_witnesses_to_be_verified(self):
        for side in ("original_status", "wrapper_status"):
            for stage in PASSED:
                status = dict(PASSED)
                status[stage] = "failed"
                with self.subTest(side=side, stage=stage):
                    result = self.compare(**{side: status})
                    self.assertEqual(result["status"], "not_run")
                    self.assertEqual(result["expected_leaves"], 1)
                    self.assertEqual(result["matched_leaves"], 0)

    def test_output_mismatch_is_separate_from_successful_input_recheck(self):
        inputs = self.compare(port="in", wrapper_witness=["1", "2", "98"])
        outputs = self.compare(port="out", wrapper_witness=["1", "2", "98"])
        self.assertEqual(inputs["status"], "matched")
        self.assertEqual(inputs["matched_leaves"], 1)
        self.assertEqual(outputs["status"], "mismatched")
        self.assertEqual(outputs["mismatched_leaves"], 1)
        self.assertEqual(outputs["matched_leaves"], 0)

    def test_missing_output_keeps_full_denominator_and_prevents_match(self):
        result = self.compare(
            count=2,
            original_symbols={"main.left.out[0]": 2, "main.left.out[1]": 4},
            wrapper_symbols={"main.out[0]": 1, "main.out[1]": -1},
            wrapper_witness=["1", "99"],
        )
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["expected_leaves"], 2)
        self.assertEqual(result["matched_leaves"], 1)
        self.assertEqual(result["unsupported_leaves"], 1)

    def test_missing_output_name_does_not_hide_an_observed_output_mismatch(self):
        result = self.compare(
            count=2,
            original_symbols={"main.left.out[0]": 2},
            wrapper_symbols={"main.out[0]": 1, "main.out[1]": 2},
            wrapper_witness=["1", "98", "88"],
        )
        self.assertEqual(result["status"], "mismatched")
        self.assertEqual(result["expected_leaves"], 2)
        self.assertEqual(result["mismatched_leaves"], 1)
        self.assertEqual(result["unsupported_leaves"], 1)
        self.assertEqual(result["matched_leaves"], 0)

    def test_duplicate_symbol_name_is_rejected_before_reading_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            symbols = Path(directory) / "duplicate.sym"
            symbols.write_text("1,1,0,main.left.in\n2,2,0,main.left.in\n")
            with self.assertRaises(ValueError):
                normal.v1.symbol_indices(symbols)

    def test_interface_counts_reject_missing_and_duplicate_log_labels(self):
        lines = ["# of Private Inputs: 2", "# of Public Inputs: 1",
                 "# of Outputs: 2", "# of Wires: 9"]
        self.assertEqual(normal.interface_counts("\n".join(lines)),
                         {"input_count": 3, "output_count": 2, "wire_count": 9})
        for index in range(len(lines)):
            missing = lines[:index] + lines[index + 1:]
            duplicate = lines + [lines[index]]
            for kind, content in (("missing", missing), ("duplicate", duplicate)):
                with self.subTest(label=lines[index], kind=kind), self.assertRaises(normal.Unsupported):
                    normal.interface_counts("\n".join(content))


if __name__ == "__main__":
    unittest.main()
