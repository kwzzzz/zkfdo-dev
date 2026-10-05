"""One metadata-only regression for NB-01 input-source independence."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "normal_boundary_replay_label_independence",
    Path(__file__).resolve().parents[1] / "scripts/measure_normal_boundary_replay.py",
)
normal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(normal)


class FixtureWithReadGuard(dict):
    """Allow scope bookkeeping, but forbid consulting labels during input reads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.in_input_reader = False
        self.reads = []

    def __getitem__(self, key):
        self.reads.append((self.in_input_reader, key))
        if self.in_input_reader and key in {"id", "expected_call_paths"}:
            raise AssertionError("input reader consulted fixture label or declared paths")
        return super().__getitem__(key)

    def get(self, key, default=None):
        return self[key] if key in self else default


class NormalBoundaryReplayLabelIndependenceTest(unittest.TestCase):
    def test_fixture_label_and_declared_paths_do_not_supply_boundary_inputs(self):
        # The names, indices, assignments and actual discovery paths stay fixed.
        # Only fixture metadata changes between cases. run_case gets the same
        # declared set in a different order; during the actual input read even
        # the declared entries are replaced with unrelated poison metadata.
        original_symbols = {
            "main.left.in": 1, "main.left.out": 2,
            "main.right.in": 3, "main.right.out": 4,
        }
        original_witness = ["1", "2", "7", "5", "9"]
        wrapper_symbols = {"main.in": 1, "main.out": 2}
        targets = [{
            "identity": name, "parent_instance_key": "root", "instance_key": "leaf",
            "origin": {"component_name": name}, "wrapper_status": "generated",
            "concrete_parameters": [], "compile_unit": "shared-wrapper",
            "generated_wrapper_path": "/synthetic/wrapper.circom",
        } for name in ("left", "right")]
        discovery = {
            "entrypoint_status": "found", "unsupported": [], "root_instance_key": "root",
            "targets": targets,
            "compile_units": [{"key": "shared-wrapper", "unresolved_includes": [],
                               "dependencies": [], "call_site_identities": ["left", "right"]}],
        }
        stdout = SimpleNamespace(read_text=lambda: json.dumps(discovery))
        interface = {"status": "passed", "reason": None, "input_count": 1,
                     "output_count": 1, "wire_count": 3, "in_shape": [], "out_shape": []}
        original_artifact = {"sym": Path("/synthetic/original.sym")}
        wrapper_artifact = {"sym": Path("/synthetic/wrapper.sym")}
        supplied = {"2": ["1", "2", "7"], "5": ["1", "5", "9"]}
        real_read_inputs = normal.read_inputs
        observed = []

        def prepare(_runner, _tools, source, _project, _folder):
            is_original = source.name == "main.circom"
            return ({"artifact": original_artifact if is_original else wrapper_artifact,
                     "symbols": original_symbols if is_original else wrapper_symbols,
                     "interface": interface}, {"status": "passed", "command": "synthetic"})

        def calculate(_runner, _tools, artifact, value, _shape, _folder):
            # Fixed metadata stubs: no calculator, compiler, witness file or engine.
            witness = original_witness if artifact is original_artifact else supplied[value]
            return witness, {"calculation": "passed", "constraint": "passed",
                             "export": "passed", "evidence": {}, "reason": None}

        for label, declared_paths in (
            ("fixture-alpha", ["main.left", "main.right"]),
            ("unrelated-fixture-label", ["main.right", "main.left"]),
        ):
            fixture = FixtureWithReadGuard({
                "id": label, "expected_call_paths": declared_paths,
                "expected_original_inputs": 1, "expected_boundary_sets": 2,
                "input_ids": ["one-normal-input"], "inputs": ["0"],
            })
            captured = {}
            runner = SimpleNamespace(records=[])

            def discovery_only(stage, *_args, **_kwargs):
                self.assertEqual(stage, "discovery")
                return {}, stdout

            def guarded_reader(*args):
                self.assertIs(args[0], original_symbols)
                self.assertIs(args[1], original_witness)
                self.assertIs(args[2], wrapper_symbols)
                self.assertIn(args[3], ("main.left", "main.right"))
                saved_metadata = {key: dict.__getitem__(fixture, key)
                                  for key in ("id", "expected_call_paths")}
                dict.__setitem__(fixture, "id", "reader-only-" + label)
                dict.__setitem__(fixture, "expected_call_paths", ["main.unrelated_" + label])
                fixture.in_input_reader = True
                try:
                    captured[args[3]] = real_read_inputs(*args)
                    return captured[args[3]]
                finally:
                    fixture.in_input_reader = False
                    for key, value in saved_metadata.items():
                        dict.__setitem__(fixture, key, value)

            runner.run = discovery_only
            with patch.object(normal, "prepare_artifact", side_effect=prepare), \
                    patch.object(normal.nc, "calculate", side_effect=calculate), \
                    patch.object(normal, "read_inputs", side_effect=guarded_reader), \
                    patch.object(normal, "data", fixture, create=True), \
                    patch.object(normal.v1, "sha", return_value="a" * 64), \
                    patch.object(normal.v1, "ref", return_value={"path": "synthetic", "sha256": "a" * 64}), \
                    patch.object(normal.v1, "write_json"), \
                    patch.object(normal.subprocess, "run", side_effect=AssertionError("process forbidden")), \
                    patch("builtins.print"):
                result = normal.run_case(
                    runner, {"zkfdo": Path("/synthetic/tool"), "circom": Path("/synthetic/compiler")},
                    Path("/synthetic/project"), fixture, Path("/synthetic/output"),
                )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(set(captured), {"main.left", "main.right"})
            self.assertEqual(captured["main.left"][0], {"in": "2"})
            self.assertEqual(captured["main.right"][0], {"in": "5"})
            self.assertFalse(any(during and key in {"id", "expected_call_paths"}
                                 for during, key in fixture.reads))
            # The declared table is still used outside read_inputs to preserve
            # the denominator. This does not claim run_case ignores that table.
            self.assertIn((False, "expected_call_paths"), fixture.reads)
            observed.append(captured)

        self.assertEqual(observed[0], observed[1])


if __name__ == "__main__":
    unittest.main()
