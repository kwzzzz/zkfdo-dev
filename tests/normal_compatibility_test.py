"""Normal metadata counterexamples: do not promote partial boundary agreement."""

import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "normal_compatibility",
    Path(__file__).resolve().parents[1] / "scripts/measure_normal_compatibility.py",
)
normal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(normal)


def array_symbols(prefix):
    return {
        f"{prefix}.in[0]": 1,
        f"{prefix}.in[1]": 2,
        f"{prefix}.out[0]": 3,
        f"{prefix}.out[1]": 4,
    }


class NormalCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.prefix = "main.left"
        self.original_symbols = array_symbols(self.prefix)
        self.wrapper_symbols = array_symbols("main")
        self.witness = ["1", "2", "3", "4", "6"]

    def compare(self, original_symbols=None, original_witness=None,
                wrapper_symbols=None, wrapper_witness=None, shape=(2,)):
        return normal.compare_boundary(
            self.original_symbols if original_symbols is None else original_symbols,
            self.witness if original_witness is None else original_witness,
            self.wrapper_symbols if wrapper_symbols is None else wrapper_symbols,
            self.witness if wrapper_witness is None else wrapper_witness,
            self.prefix,
            shape,
        )

    def test_only_declared_small_scalar_or_vector_shapes_are_supported(self):
        self.assertEqual(normal.leaf_suffixes(()), [""])
        self.assertEqual(normal.leaf_suffixes((2,)), ["[0]", "[1]"])
        self.assertEqual(len(normal.leaf_suffixes((8,))), 8)
        for shape in ((0,), (-1,), (9,), (2, 2), ("2",), (True,)):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                normal.leaf_suffixes(shape)

    def test_encoding_preserves_shape_and_rejects_guessed_or_ragged_inputs(self):
        self.assertEqual(normal.encode_input("3", ()), "3")
        self.assertEqual(normal.encode_input(["2", "3"], (2,)), ["2", "3"])
        malformed = [
            (["3"], ()),
            ("3", (2,)),
            (["3"], (2,)),
            (["2", "3", "4"], (2,)),
            ([["2"], ["3"]], (2,)),
            (["2", ["3"]], (2,)),
        ]
        for value, shape in malformed:
            with self.subTest(value=value, shape=shape), self.assertRaises(ValueError):
                normal.encode_input(value, shape)

    def test_field_input_encoding_rejects_noncanonical_values(self):
        # Ordinary arithmetic inputs, with no circuit execution or mutation.
        for value in ("-1", "01", "+1", " 1", "1 ", "1.0", True, 1.0,
                      str(normal.FIELD), str(normal.FIELD + 1)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normal.encode_input(value, ())

    def test_all_declared_input_and_output_leaves_are_required_for_match(self):
        result = self.compare()
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["expected_leaves"], 4)
        self.assertEqual(result["matched_leaves"], 4)
        self.assertEqual(result["mismatched_leaves"], 0)
        self.assertEqual(result["unsupported_leaves"], 0)
        self.assertEqual(len(result["leaves"]), 4)

    def test_optimized_out_input_is_not_replaced_by_zero_or_output_agreement(self):
        symbols = dict(self.original_symbols)
        symbols[f"{self.prefix}.in[0]"] = -1
        result = self.compare(original_symbols=symbols)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["expected_leaves"], 4)
        self.assertEqual(result["matched_leaves"], 3)
        self.assertEqual(result["unsupported_leaves"], 1)
        self.assertTrue(any(leaf.get("reason") for leaf in result["leaves"]))

    def test_missing_or_out_of_range_mapping_preserves_the_denominator(self):
        missing = dict(self.wrapper_symbols)
        missing.pop("main.out[1]")
        out_of_range = dict(self.wrapper_symbols)
        out_of_range["main.out[1]"] = len(self.witness)
        for symbols in (missing, out_of_range):
            with self.subTest(symbols=symbols):
                result = self.compare(wrapper_symbols=symbols)
                self.assertEqual(result["status"], "unsupported")
                self.assertEqual(result["expected_leaves"], 4)
                self.assertEqual(result["matched_leaves"], 3)
                self.assertEqual(result["unsupported_leaves"], 1)

    def test_extra_array_index_cannot_be_silently_excluded(self):
        symbols = dict(self.wrapper_symbols)
        symbols["main.out[2]"] = 3
        result = self.compare(wrapper_symbols=symbols)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["expected_leaves"], 4)

    def test_scalar_spelling_cannot_stand_in_for_an_array_element(self):
        symbols = dict(self.wrapper_symbols)
        symbols.pop("main.in[0]")
        symbols["main.in"] = 1
        result = self.compare(wrapper_symbols=symbols)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["expected_leaves"], 4)

    def test_normal_value_disagreement_is_not_reported_as_unsupported_or_match(self):
        witness = list(self.witness)
        witness[4] = "7"
        result = self.compare(wrapper_witness=witness)
        self.assertEqual(result["status"], "mismatched")
        self.assertEqual(result["expected_leaves"], 4)
        self.assertEqual(result["matched_leaves"], 3)
        self.assertEqual(result["mismatched_leaves"], 1)
        self.assertEqual(result["unsupported_leaves"], 0)


if __name__ == "__main__":
    unittest.main()
