"""Closed-set checks of five toy fixtures, not a general lifting implementation.

All compiler products and generated assignments live in a TemporaryDirectory.
Missing tools/version mismatches are failures, never successful skipped checks.
"""

import copy
import itertools
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lifting"
CASES = (
    "entrypoint_violation",
    "compatible_no_top_violation_observed",
    "excluded_in_context",
    "unknown",
    "preparation_failure",
)
BN254 = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def read_json(path):
    return json.loads(path.read_text())


def run_tool(*args, expect_success=True):
    result = subprocess.run(
        [str(arg) for arg in args], capture_output=True, text=True, timeout=60,
        check=False,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"tool failed ({result.returncode}): {args}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def read_symbols(path):
    symbols = {}
    for line in path.read_text().splitlines():
        _, wire, _, name = line.split(",", 3)
        if name in symbols:
            raise ValueError(f"ambiguous symbol: {name}")
        symbols[name] = int(wire)
    return symbols


def signal_value(symbols, witness, name):
    if name not in symbols:
        raise ValueError(f"missing symbol: {name}")
    index = symbols[name]
    if index < 0:
        raise ValueError(f"eliminated symbol: {name}")
    if index >= len(witness):
        raise ValueError(f"invalid wire index: {name}")
    return witness[index]


def validate_witness(r1cs, witness):
    prime = int(r1cs["prime"])
    if len(witness) != r1cs["nVars"] or not witness or witness[0] != 1:
        raise ValueError("wrong witness length or constant wire")
    if any(type(value) is not int or not 0 <= value < prime for value in witness):
        raise ValueError("noncanonical field element")


def assignment_from_names(r1cs, symbols, values):
    # Use a complete, authored assignment. Never fill holes from an honest
    # witness or infer aliases/eliminated signals from source expressions.
    witness = [None] * r1cs["nVars"]
    witness[0] = 1
    for name, value in values.items():
        if name not in symbols:
            raise ValueError(f"missing symbol: {name}")
        index = symbols[name]
        if index < 0:
            raise ValueError(f"eliminated symbol: {name}")
        if index >= len(witness):
            raise ValueError(f"invalid wire index: {name}")
        if not isinstance(value, str) or not value.isdecimal():
            raise ValueError(f"expected decimal string: {name}")
        value = int(value)
        if witness[index] is not None and witness[index] != value:
            raise ValueError(f"conflicting aliases: {name}")
        witness[index] = value
    if None in witness:
        raise ValueError("incomplete assignment")
    validate_witness(r1cs, witness)
    return witness


def failed_constraints(r1cs, witness):
    validate_witness(r1cs, witness)
    prime = int(r1cs["prime"])

    def evaluate(terms):
        return sum(int(coeff) * witness[int(wire)] for wire, coeff in terms.items()) % prime

    return [
        index
        for index, (a, b, c) in enumerate(r1cs["constraints"])
        if (evaluate(a) * evaluate(b) - evaluate(c)) % prime != 0
    ]


def constraint_polynomial(constraint, prime):
    """Normalize a tiny test relation up to nonzero field scaling."""
    a, b, c = constraint
    terms = {}
    for left, left_coeff in a.items():
        for right, right_coeff in b.items():
            monomial = tuple(sorted(wire for wire in (int(left), int(right)) if wire != 0))
            terms[monomial] = terms.get(monomial, 0) + int(left_coeff) * int(right_coeff)
    for wire, coeff in c.items():
        monomial = (int(wire),) if int(wire) != 0 else ()
        terms[monomial] = terms.get(monomial, 0) - int(coeff)
    return normalize_polynomial(terms, prime)


def normalize_polynomial(terms, prime):
    terms = {key: value % prime for key, value in terms.items() if value % prime}
    if not terms:
        return {}
    scale = pow(terms[min(terms)], -1, prime)
    return {key: value * scale % prime for key, value in terms.items()}


def write_toy_wtns(path, r1cs, witness):
    """Serialize only these fixed toy assignments for a second snarkjs check."""
    validate_witness(r1cs, witness)
    width = 32
    header = (
        struct.pack("<I", width)
        + int(r1cs["prime"]).to_bytes(width, "little")
        + struct.pack("<I", len(witness))
    )
    body = b"".join(value.to_bytes(width, "little") for value in witness)
    path.write_bytes(
        b"wtns" + struct.pack("<II", 2, 2)
        + struct.pack("<IQ", 1, len(header)) + header
        + struct.pack("<IQ", 2, len(body)) + body
    )


class Artifact:
    def __init__(self, fixture, stem, optimization, output):
        output.mkdir()
        self.output = output
        self.stem = stem
        run_tool(
            "circom", fixture / "src" / f"{stem}.circom", "--r1cs", "--wasm", "--sym",
            f"--{optimization}", "--prime", "bn128", "-o", output,
        )
        self.r1cs_path = output / f"{stem}.r1cs"
        json_path = output / "r1cs.json"
        run_tool("snarkjs", "r1cs", "export", "json", self.r1cs_path, json_path)
        self.r1cs = read_json(json_path)
        self.symbols = read_symbols(output / f"{stem}.sym")
        if int(self.r1cs["prime"]) != BN254:
            raise AssertionError("unexpected compiler field")
        if len(self.r1cs["constraints"]) != self.r1cs["nConstraints"]:
            raise AssertionError("incomplete exported R1CS")

    def calculate(self, inputs, label, expect_success=True):
        input_path = self.output / f"{label}.input.json"
        input_path.write_text(json.dumps(inputs))
        witness_path = self.output / f"{label}.wtns"
        js_dir = self.output / f"{self.stem}_js"
        result = run_tool(
            "node", js_dir / "generate_witness.js", js_dir / f"{self.stem}.wasm",
            input_path, witness_path, expect_success=expect_success,
        )
        if not expect_success:
            return result
        run_tool("snarkjs", "wtns", "check", self.r1cs_path, witness_path)
        json_path = self.output / f"{label}.witness.json"
        run_tool("snarkjs", "wtns", "export", "json", witness_path, json_path)
        witness = [int(value) for value in read_json(json_path)]
        if failed_constraints(self.r1cs, witness):
            raise AssertionError("honest witness failed local full-R1CS check")
        return witness

    def authored_assignment(self, values, label):
        witness = assignment_from_names(self.r1cs, self.symbols, values)
        if failed_constraints(self.r1cs, witness):
            raise AssertionError("authored toy witness failed full-R1CS check")
        path = self.output / f"{label}.wtns"
        write_toy_wtns(path, self.r1cs, witness)
        run_tool("snarkjs", "wtns", "check", self.r1cs_path, path)
        return witness


class LiftingFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ("circom", "node", "snarkjs"):
            if shutil.which(tool) is None:
                raise AssertionError(f"required fixture-test tool not found: {tool}")
        version = run_tool("circom", "--version").stdout.strip()
        if version != "circom compiler 2.2.3":
            raise AssertionError(f"requires Circom 2.2.3, got: {version}")
        cls.temporary = tempfile.TemporaryDirectory(prefix="zkfdo-lifting-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.workspace = Path(cls.temporary.name)
        cls.data = {}
        for name in CASES:
            fixture = FIXTURES / name
            expected = read_json(fixture / "expected.json")
            candidate = read_json(fixture / "candidate_context.json")
            candidate["component_assignment"] = read_json(fixture / "candidate.json")
            control = read_json(fixture / "control.json")
            options = expected["compiler"]
            component = Artifact(
                fixture, "standalone", options["component_optimization"],
                cls.workspace / f"{name}-component",
            )
            entrypoint = Artifact(
                fixture, "entrypoint", options["entrypoint_optimization"],
                cls.workspace / f"{name}-entrypoint",
            )
            honest_component = component.calculate(candidate["component_inputs"], "same-input")
            honest_entrypoint = entrypoint.calculate(control["entrypoint_inputs"], "control")
            cls.data[name] = {
                "expected": expected, "candidate": candidate, "control": control,
                "component": component, "entrypoint": entrypoint,
                "honest_component": honest_component, "honest_entrypoint": honest_entrypoint,
            }
        print("Circom 2.2.3: 10/10 fixture source conditions compiled", flush=True)

    def test_component_candidates_satisfy_full_r1cs_and_differ_from_same_input(self):
        for name, data in self.data.items():
            with self.subTest(case=name):
                component = data["component"]
                self.assertGreater(component.r1cs["nConstraints"], 0)
                candidate = component.authored_assignment(
                    data["candidate"]["component_assignment"], "candidate",
                )
                value = lambda w, s: signal_value(component.symbols, w, f"main.{s}")
                honest = data["honest_component"]
                self.assertEqual(value(candidate, "x"), value(honest, "x"))
                self.assertNotEqual(value(candidate, "out"), value(honest, "out"))
                bad_square = candidate.copy()
                bad_square[component.symbols["main.square"]] += 1
                self.assertTrue(failed_constraints(component.r1cs, bad_square))

    def test_all_honest_controls_have_matching_independent_outputs(self):
        for name, data in self.data.items():
            with self.subTest(case=name):
                root, root_witness = data["entrypoint"], data["honest_entrypoint"]
                if name == "preparation_failure":
                    # The public input is known, but do not call this a successful
                    # reconstruction of the eliminated callsite symbol.
                    child_input = data["control"]["entrypoint_inputs"]["x"]
                else:
                    child_input = str(signal_value(root.symbols, root_witness, "main.child.x"))
                component = data["component"]
                child_witness = component.calculate({"x": child_input}, "control")
                child_output = signal_value(component.symbols, child_witness, "main.out")
                if name != "preparation_failure":
                    self.assertEqual(
                        signal_value(root.symbols, root_witness, "main.child.out"), child_output,
                    )
                expected_top = 2 * int(child_input) if name == CASES[1] else child_output
                self.assertEqual(signal_value(root.symbols, root_witness, "main.out"), expected_top)
                self.assertEqual(data["expected"]["control"]["semantic_verdict"], "no_violation")

    def test_root_violation_and_masked_difference_have_distinct_outcomes(self):
        for name, top_differs in ((CASES[0], True), (CASES[1], False)):
            with self.subTest(case=name):
                data = self.data[name]
                root = data["entrypoint"]
                candidate = root.authored_assignment(
                    data["candidate"]["entrypoint_assignment"], "candidate",
                )
                honest = data["honest_entrypoint"]
                self.assertEqual(data["candidate"]["entrypoint_inputs"], data["control"]["entrypoint_inputs"])
                self.assertEqual(
                    signal_value(root.symbols, candidate, "main.x"),
                    signal_value(root.symbols, honest, "main.x"),
                )
                self.assert_candidate_boundary_matches(data, candidate)
                self.assertNotEqual(
                    signal_value(root.symbols, candidate, "main.child.out"),
                    signal_value(root.symbols, honest, "main.child.out"),
                )
                self.assertEqual(
                    signal_value(root.symbols, candidate, "main.out")
                    != signal_value(root.symbols, honest, "main.out"), top_differs,
                )
                self.assertIs(data["expected"]["candidate"]["entrypoint_r1cs_satisfied"], True)
                self.assertIs(data["expected"]["candidate"]["top_output_differs"], top_differs)

    def test_range_exclusion_is_not_just_witness_generation_failure(self):
        data = self.data["excluded_in_context"]
        root = data["entrypoint"]
        input_value = int(data["candidate"]["component_inputs"]["x"])
        self.assertEqual(input_value, 8)
        prime = int(root.r1cs["prime"])
        self.assertGreater(prime, input_value)
        # Verify that the compiled relation really contains the boolean
        # and reconstruction constraints before relying on enumeration.
        polynomials = [constraint_polynomial(c, prime) for c in root.r1cs["constraints"]]
        bit_wires = [root.symbols[f"main.range.bits[{index}]"] for index in range(3)]
        for wire in bit_wires:
            self.assertIn(normalize_polynomial({(wire, wire): 1, (wire,): -1}, prime), polynomials)
        reconstruction = {(root.symbols["main.range.in"],): 1}
        reconstruction.update({(wire,): -(1 << index) for index, wire in enumerate(bit_wires)})
        self.assertIn(normalize_polynomial(reconstruction, prime), polynomials)
        for left, right in (("main.range.in", "main.x"), ("main.child.x", "main.x")):
            connection = {(root.symbols[left],): 1, (root.symbols[right],): -1}
            self.assertIn(normalize_polynomial(connection, prime), polynomials)
        # The verified boolean constraints restrict bits to {0,1}; enumerate
        # every possible assignment of those bits. The remaining toy wires
        # are fixed by the candidate and direct connections.
        possible_sums = set()
        for bits in itertools.product((0, 1), repeat=3):
            values = copy.deepcopy(data["candidate"]["entrypoint_assignment"])
            for index, bit in enumerate(bits):
                values[f"main.range.bits[{index}]"] = str(bit)
            possible_sums.add(sum(bit << index for index, bit in enumerate(bits)))
            witness = assignment_from_names(root.r1cs, root.symbols, values)
            self.assert_candidate_boundary_matches(data, witness)
            self.assertTrue(failed_constraints(root.r1cs, witness))
            # Positive case per bit pattern prevents unrelated malformed
            # assignments from being mistaken for a range exclusion proof.
            inside = sum(bit << index for index, bit in enumerate(bits))
            values.update({
                "main.x": str(inside), "main.range.in": str(inside),
                "main.child.x": str(inside), "main.child.square": str(inside * inside),
                "main.child.out": str(inside + 1), "main.out": str(inside + 1),
            })
            valid = assignment_from_names(root.r1cs, root.symbols, values)
            self.assertEqual(failed_constraints(root.r1cs, valid), [])
        self.assertEqual(possible_sums, set(range(8)))
        self.assertNotIn(input_value, possible_sums)
        result = root.calculate(data["candidate"]["entrypoint_inputs"], "out-of-range", False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Assert Failed", result.stderr)
        self.assertIs(data["expected"]["candidate"]["entrypoint_r1cs_satisfied"], False)
        self.assertIsNone(data["expected"]["candidate"]["top_output_differs"])

    def assert_candidate_boundary_matches(self, data, root_witness):
        symbols = data["entrypoint"].symbols
        self.assertEqual(
            signal_value(symbols, root_witness, "main.x"),
            int(data["candidate"]["entrypoint_inputs"]["x"]),
        )
        for name, value in data["candidate"]["component_assignment"].items():
            suffix = name.removeprefix("main.")
            self.assertEqual(signal_value(symbols, root_witness, f"main.child.{suffix}"), int(value))

    def test_unknown_keeps_absent_preimage_unresolved(self):
        data = self.data["unknown"]
        candidate, expected = data["candidate"], data["expected"]
        self.assertIsNone(candidate["entrypoint_inputs"])
        self.assertIsNone(candidate["entrypoint_assignment"])
        self.assertEqual(expected["support_profile"]["input_linking"], "forward_hash_only")
        self.assertIs(expected["support_profile"]["hash_inversion"], False)
        root, honest = data["entrypoint"], data["honest_entrypoint"]
        digest = signal_value(root.symbols, honest, "main.hash.out")
        self.assertEqual(digest, signal_value(root.symbols, honest, "main.child.x"))
        self.assertNotEqual(digest, int(candidate["component_inputs"]["x"]))
        self.assertEqual(expected["candidate"]["verdict"], "unknown")
        self.assertIsNone(expected["candidate"]["entrypoint_r1cs_satisfied"])
        self.assertIsNone(expected["candidate"]["top_output_differs"])

    def test_optimized_boundary_is_failure_even_for_honest_control(self):
        data = self.data["preparation_failure"]
        root = data["entrypoint"]
        self.assertEqual(root.symbols["main.child.x"], -1)
        for boundary in data["expected"]["mapping"]["required_boundary_signals"]:
            self.assertIn(f"main.child.{boundary}", root.symbols)
        with self.assertRaisesRegex(ValueError, "eliminated symbol: main.child.x"):
            signal_value(root.symbols, data["honest_entrypoint"], "main.child.x")
        self.assertEqual(data["expected"]["control"]["lifting_verdict"], "preparation_failure")
        self.assertIsNone(data["expected"]["candidate"]["entrypoint_r1cs_satisfied"])
        self.assertIsNone(data["expected"]["candidate"]["top_output_differs"])
        # Same source, explicit different compiler condition: O0 restores
        # direct observation for the honest control, not the O1 candidate.
        o0 = Artifact(FIXTURES / "preparation_failure", "entrypoint", "O0", self.workspace / "prep-o0-control")
        honest = o0.calculate(data["control"]["entrypoint_inputs"], "control")
        self.assertEqual(signal_value(o0.symbols, honest, "main.child.x"), 3)
        self.assertEqual(signal_value(o0.symbols, honest, "main.child.out"), signal_value(o0.symbols, honest, "main.out"))

    def test_fixture_metadata_pins_conditions_without_upgrading_unknowns(self):
        self.assertTrue(all((FIXTURES / name).is_dir() for name in CASES))
        for name, data in self.data.items():
            with self.subTest(case=name):
                expected = data["expected"]
                for key in ("candidate", "control", "expected"):
                    self.assertEqual(data[key]["schema_version"], 1)
                self.assertEqual(expected["case_id"], name)
                self.assertEqual(expected["candidate"]["verdict"], name)
                self.assertTrue(expected["candidate"]["reason"].strip())
                self.assertNotIn("\n", expected["candidate"]["reason"])
                self.assertEqual(expected["compiler"], {
                    "version": "2.2.3", "field": "bn128", "component_optimization": "O0",
                    "entrypoint_optimization": "O1" if name == "preparation_failure" else "O0",
                })
                self.assertIs(expected["candidate"]["component_r1cs_satisfied"], True)
                self.assertIs(expected["candidate"]["component_differs_from_honest"], True)
                self.assertEqual(expected["mapping"], {
                    "component_prefix": "main", "entrypoint_prefix": "main.child",
                    "required_boundary_signals": ["x", "out"],
                })
                self.assertEqual(data["control"]["selected_call_path"], "main.child")
                expected_control = "preparation_failure" if name == "preparation_failure" else CASES[1]
                self.assertEqual(expected["control"]["lifting_verdict"], expected_control)

    def test_request_format_and_honest_named_controls(self):
        for name, data in self.data.items():
            with self.subTest(case=name):
                fixture = FIXTURES / name
                self.assertEqual(read_json(fixture / "base_input.json"), data["control"]["entrypoint_inputs"])
                component = data["component"]
                control = component.authored_assignment(read_json(fixture / "control_candidate.json"), "named-control")
                expected_input = read_json(fixture / "control_candidate.json")["main.x"]
                if name == "preparation_failure":
                    self.assertEqual(expected_input, data["control"]["entrypoint_inputs"]["x"])
                else:
                    self.assertEqual(int(expected_input), signal_value(
                        data["entrypoint"].symbols, data["honest_entrypoint"], "main.child.x",
                    ))
                honest = component.calculate({"x": expected_input}, "named-control-honest")
                self.assertEqual(control, honest)
                self.assertEqual(data["expected"]["sites"], {"main.child": name})
                self.assertEqual(data["expected"]["sites_found"], 1)
                control_verdict = "preparation_failure" if name == "preparation_failure" else CASES[1]
                self.assertEqual(data["expected"]["control"]["sites"], {"main.child": control_verdict})
                self.assertEqual(data["expected"]["control"]["sites_found"], 1)
                if name == "preparation_failure":
                    self.assertFalse((fixture / "request.json").exists())
                    self.assertEqual(data["expected"]["request_status"], "unsupported_by_request_v1")
                    continue
                for request_name, candidate_name in (("request.json", "candidate.json"), ("control_request.json", "control_candidate.json")):
                    request = read_json(fixture / request_name)
                    self.assertEqual(request["schema"], "zkfdo-lifting-request-v1")
                    self.assertEqual(request["source_root"], "src")
                    self.assertEqual(request["library_paths"], [])
                    self.assertEqual(request["candidate"], {"format": "named", "path": candidate_name})
                    self.assertEqual(request["component_wrapper"], "src/standalone.circom")
                    self.assertEqual(request["entrypoint"], "src/entrypoint.circom")
                    self.assertEqual(request["base_input"], "base_input.json")
                    for key in ("component_wrapper", "entrypoint", "base_input"):
                        self.assertTrue((fixture / request[key]).is_file())


class AssignmentGuardRegressions(unittest.TestCase):
    def setUp(self):
        self.r1cs = {"prime": "17", "nVars": 3, "constraints": [[{"1": "1"}, {"1": "1"}, {"2": "1"}]]}
        self.symbols = {"main.x": 1, "main.square": 2}

    def test_missing_assignment_cannot_be_filled_from_honest_witness(self):
        with self.assertRaisesRegex(ValueError, "incomplete assignment"):
            assignment_from_names(self.r1cs, self.symbols, {"main.x": "3"})

    def test_conflicting_aliases_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "conflicting aliases"):
            assignment_from_names(self.r1cs, {**self.symbols, "main.alias": 1}, {
                "main.x": "3", "main.square": "9", "main.alias": "4",
            })

    def test_noncanonical_values_and_invalid_constant_are_rejected(self):
        for witness in ([1, 20, 9], [1, -14, 9], [0, 3, 9], [1, True, 1]):
            with self.subTest(witness=witness), self.assertRaises(ValueError):
                failed_constraints(self.r1cs, witness)

    def test_eliminated_and_missing_symbols_do_not_alias_to_another_wire(self):
        for name, symbols in (("main.absent", self.symbols), ("main.removed", {"main.removed": -1})):
            with self.subTest(name=name), self.assertRaises(ValueError):
                signal_value(symbols, [1, 3, 9], name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                assignment_from_names(self.r1cs, symbols, {name: "3"})

    def test_constraint_checker_rejects_wrong_relation(self):
        self.assertEqual(failed_constraints(self.r1cs, [1, 3, 9]), [])
        self.assertEqual(failed_constraints(self.r1cs, [1, 3, 10]), [0])
        self.assertEqual(failed_constraints(self.r1cs, [1, 5, 8]), [])

    def test_duplicate_symbol_rows_are_ambiguous(self):
        with tempfile.TemporaryDirectory(prefix="zkfdo-lifting-symbols-") as directory:
            path = Path(directory) / "ambiguous.sym"
            path.write_text("1,1,0,main.x\n2,2,0,main.x\n")
            with self.assertRaisesRegex(ValueError, "ambiguous symbol"):
                read_symbols(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
