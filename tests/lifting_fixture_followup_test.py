"""LF-02 fixed toy oracles, independent of the lifting engine's input synthesizer."""

import itertools
from pathlib import Path
import shutil
import tempfile
import unittest

from lifting_fixture_test import (
    Artifact, FIXTURES, constraint_polynomial,
    failed_constraints, normalize_polynomial, read_json, run_tool, signal_value,
)


CASES = (
    "preparation_failure_no_callsite",
    "preparation_failure_input_wire",
    "linear_inversion",
    "bitdecomp_inversion",
    "range_unreachable_intermediate",
)


class FollowupFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ("circom", "node", "snarkjs"):
            if shutil.which(tool) is None:
                raise AssertionError(f"required fixture-test tool not found: {tool}")
        if run_tool("circom", "--version").stdout.strip() != "circom compiler 2.2.3":
            raise AssertionError("fixture checks require Circom 2.2.3")
        cls.temporary = tempfile.TemporaryDirectory(prefix="zkfdo-lf02-")
        cls.addClassCleanup(cls.temporary.cleanup)
        workspace = Path(cls.temporary.name)
        cls.data = {}
        for name in CASES:
            fixture = FIXTURES / name
            context = read_json(fixture / "candidate_context.json")
            component = Artifact(fixture, "standalone", "O0", workspace / f"{name}-component")
            root = Artifact(fixture, "entrypoint", "O0", workspace / f"{name}-root")
            cls.data[name] = {
                "fixture": fixture, "context": context, "component": component, "root": root,
                "expected": read_json(fixture / "expected.json"),
                "candidate": read_json(fixture / "candidate.json"),
                "control": read_json(fixture / "control_candidate.json"),
                "base_input": read_json(fixture / "base_input.json"),
                "honest_component": component.calculate(context["component_inputs"], "same-input"),
                "honest_root": root.calculate(read_json(fixture / "base_input.json"), "control"),
            }
        print("LF-02: 10/10 O0 source conditions compiled", flush=True)

    def test_all_five_candidates_are_real_component_deviations(self):
        for name, data in self.data.items():
            with self.subTest(case=name):
                component, honest = data["component"], data["honest_component"]
                self.assertGreater(component.r1cs["nConstraints"], 0)
                candidate = component.authored_assignment(data["candidate"], "candidate")
                leaf = "main.payload.x" if name == "preparation_failure_input_wire" else "main.x"
                self.assertEqual(signal_value(component.symbols, candidate, leaf), signal_value(component.symbols, honest, leaf))
                self.assertNotEqual(signal_value(component.symbols, candidate, "main.out"), signal_value(component.symbols, honest, "main.out"))
                bad = candidate.copy()
                bad[component.symbols["main.square"]] += 1
                self.assertTrue(failed_constraints(component.r1cs, bad))
                self.assertIs(data["expected"]["candidate"]["component_r1cs_satisfied"], True)
                self.assertIs(data["expected"]["candidate"]["component_differs_from_honest"], True)

    def test_all_five_honest_controls_match_normal_calculation(self):
        for name, data in self.data.items():
            with self.subTest(case=name):
                bus = name == "preparation_failure_input_wire"
                leaf = "payload.x" if bus else "x"
                value = data["control"][f"main.{leaf}"]
                inputs = {"payload": {"x": value}} if bus else {"x": value}
                component, root = data["component"], data["root"]
                honest = component.calculate(inputs, "control")
                authored = component.authored_assignment(data["control"], "authored-control")
                self.assertEqual(authored, honest)
                top = signal_value(root.symbols, data["honest_root"], "main.out")
                if name == "preparation_failure_no_callsite":
                    self.assertEqual(top, int(data["base_input"]["z"]) + 7)
                else:
                    self.assertEqual(signal_value(root.symbols, data["honest_root"], f"main.child.{leaf}"), int(value))
                    self.assertEqual(top, signal_value(component.symbols, honest, "main.out"))
                    self.assertEqual(top, signal_value(root.symbols, data["honest_root"], "main.child.out"))
                self.assertEqual(data["expected"]["control"]["semantic_verdict"], "no_violation")

    def test_preparation_cases_distinguish_absent_site_from_unrecognized_input(self):
        absent = self.data["preparation_failure_no_callsite"]
        self.assertFalse(any(name.startswith("main.child.") for name in absent["root"].symbols))
        self.assertEqual(absent["expected"]["preparation"], {"status": "preparation_failure", "reason": "no_call_site"})
        bus = self.data["preparation_failure_input_wire"]
        self.assertGreaterEqual(bus["component"].symbols["main.payload.x"], 0)
        self.assertGreaterEqual(bus["root"].symbols["main.child.payload.x"], 0)
        self.assertEqual(bus["expected"]["preparation"], {"status": "preparation_failure", "reason": "component_inputs_unresolved"})
        # The engine stops before site discovery for a bus input; its zero
        # reported sites is not proof of an absent source callsite.
        self.assertEqual(bus["expected"]["sites_found"], 0)
        self.assertIsNone(bus["expected"]["candidate"]["entrypoint_r1cs_satisfied"])

    def test_fixed_inverse_oracles_reach_candidate_and_change_top_output(self):
        for name in ("linear_inversion", "bitdecomp_inversion"):
            with self.subTest(case=name):
                data = self.data[name]
                root, context = data["root"], data["context"]
                self.assertNotEqual(context["entrypoint_inputs"], data["base_input"])
                honest = root.calculate(context["entrypoint_inputs"], "oracle-input")
                candidate = root.authored_assignment(context["entrypoint_assignment"], "candidate")
                for leaf, value in context["entrypoint_inputs"].items():
                    self.assertEqual(signal_value(root.symbols, honest, f"main.{leaf}"), int(value))
                    self.assertEqual(signal_value(root.symbols, candidate, f"main.{leaf}"), int(value))
                for signal, value in data["candidate"].items():
                    child_signal = "main.child." + signal.removeprefix("main.")
                    self.assertEqual(signal_value(root.symbols, candidate, child_signal), int(value))
                self.assertEqual(signal_value(root.symbols, honest, "main.child.x"), int(data["candidate"]["main.x"]))
                self.assertNotEqual(signal_value(root.symbols, candidate, "main.out"), signal_value(root.symbols, honest, "main.out"))
                self.assertEqual(data["expected"]["sites"], {"main.child": "entrypoint_violation"})
                self.assertIs(data["expected"]["candidate"]["entrypoint_r1cs_satisfied"], True)

    def assert_compiled_relation(self, artifact, terms):
        prime = int(artifact.r1cs["prime"])
        actual = [constraint_polynomial(c, prime) for c in artifact.r1cs["constraints"]]
        self.assertIn(normalize_polynomial(terms, prime), actual)

    def assert_compiled_linear(self, artifact, terms):
        self.assert_compiled_relation(artifact, {
            (artifact.symbols[name],) if name else (): coeff for name, coeff in terms.items()
        })

    def assert_boolean_bits_and_reconstruction(self, artifact, width):
        reconstruction = {"main.range.in": 1}
        for index in range(width):
            name = f"main.range.bits[{index}]"
            wire = artifact.symbols[name]
            self.assert_compiled_relation(artifact, {(wire, wire): 1, (wire,): -1})
            reconstruction[name] = -(1 << index)
        self.assert_compiled_linear(artifact, reconstruction)

    def test_inverse_fixture_relations_are_present_in_actual_r1cs(self):
        linear = self.data["linear_inversion"]["root"]
        self.assert_compiled_linear(linear, {"main.intermediate": 1, "main.x": -3, "main.y": -1, "": -5})
        self.assert_compiled_linear(linear, {"main.child.x": 1, "main.intermediate": -1})
        bit = self.data["bitdecomp_inversion"]["root"]
        self.assert_boolean_bits_and_reconstruction(bit, 4)
        self.assert_compiled_linear(bit, {"main.range.in": 1, "main.x": -1})
        self.assert_compiled_linear(bit, {"main.child.x": 1, "main.intermediate": -1})
        self.assert_compiled_linear(bit, {
            "main.intermediate": 1, "main.range.bits[0]": -8,
            "main.range.bits[1]": -4, "main.range.bits[2]": -2, "main.range.bits[3]": -1,
        })

    def test_range_exclusion_proof_covers_all_public_inputs(self):
        data = self.data["range_unreachable_intermediate"]
        root = data["root"]
        self.assert_boolean_bits_and_reconstruction(root, 8)
        self.assert_compiled_linear(root, {"main.range.in": 1, "main.intermediate": -1})
        self.assert_compiled_linear(root, {"main.child.x": 1, "main.intermediate": -1})
        x, intermediate = root.symbols["main.x"], root.symbols["main.intermediate"]
        self.assert_compiled_relation(root, {(x, x): 1, (intermediate,): -1})
        prime = int(root.r1cs["prime"])
        target = int(data["candidate"]["main.x"])
        self.assertEqual(target, 300)
        possible = set()
        # The verified original-R1CS subset contains no public input x. With
        # child.x=300, the equalities force range.in=300 for every x. Since
        # 0..255 < p, none of these 256 boolean sums equals 300 in the field.
        for bits in itertools.product((0, 1), repeat=8):
            value = sum(bit << index for index, bit in enumerate(bits))
            possible.add(value)
            self.assertNotEqual((target - value) % prime, 0)
        self.assertEqual(possible, set(range(256)))
        self.assertGreater(prime, target)
        self.assertIsNone(data["context"]["entrypoint_inputs"])
        self.assertIsNone(data["context"]["entrypoint_assignment"])
        self.assertEqual(data["expected"]["sites"], {"main.child": "excluded_in_context"})
        self.assertIs(data["expected"]["candidate"]["entrypoint_r1cs_satisfied"], False)
        self.assertIsNone(data["expected"]["candidate"]["top_output_differs"])

    def test_requests_do_not_supply_the_inverse_oracle_as_base_input(self):
        for name in CASES[2:]:
            data = self.data[name]
            request = read_json(data["fixture"] / "request.json")
            self.assertEqual(request["base_input"], "base_input.json")
            self.assertEqual(request["candidate"], {"format": "named", "path": "candidate.json"})
            observed = signal_value(data["root"].symbols, data["honest_root"], "main.child.x")
            self.assertNotEqual(observed, int(data["candidate"]["main.x"]))
            pending = data["expected"].get("pending_engine")
            if name == "range_unreachable_intermediate":
                # L-03 owner decision (2026-10-02): the closed-cone z3 unsat proof is
                # promoted to excluded_in_context, so no pending snapshot remains.
                self.assertIsNone(pending)
                continue
            self.assertEqual(pending["sites"], {"main.child": "unknown"})
            reason = {
                "linear_inversion": "input_requires_inversion",
                "bitdecomp_inversion": "synthesis_local_unsat",
                "range_unreachable_intermediate": "synthesis_local_unsat",
            }[name]
            self.assertEqual(pending["reasons"], {"main.child": reason})
            self.assertEqual(pending["preparation"], {"status": "ok", "reason": None})

    def test_request_format_keeps_all_candidate_and_control_conditions(self):
        for name, data in self.data.items():
            with self.subTest(case=name):
                self.assertEqual(data["expected"]["compiler"], {
                    "version": "2.2.3", "field": "bn128",
                    "component_optimization": "O0", "entrypoint_optimization": "O0",
                })
                for filename, candidate in (("request.json", "candidate.json"), ("control_request.json", "control_candidate.json")):
                    request = read_json(data["fixture"] / filename)
                    self.assertEqual(request["schema"], "zkfdo-lifting-request-v1")
                    self.assertEqual(request["source_root"], "src")
                    self.assertEqual(request["candidate"], {"format": "named", "path": candidate})
                    self.assertEqual(request["component_wrapper"], "src/standalone.circom")
                    self.assertEqual(request["entrypoint"], "src/entrypoint.circom")
                    self.assertEqual(request["base_input"], "base_input.json")
                    for key in ("component_wrapper", "entrypoint", "base_input"):
                        self.assertTrue((data["fixture"] / request[key]).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
