import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/n6_j1_base_inputs.py"
SPEC = importlib.util.spec_from_file_location("n6_j1_base_inputs", SCRIPT)
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)


class BaseInputSelectionTests(unittest.TestCase):
    def test_zero_input_uses_direct_main_array_dimensions(self):
        names = ["main.scalar", "main.matrix[0][0]", "main.matrix[0][1]",
                 "main.matrix[1][0]", "main.matrix[1][1]"]
        self.assertEqual(base.input_keys(names), ["matrix", "scalar"])
        self.assertEqual(base.zero_input(names), {"matrix": [[0, 0], [0, 0]], "scalar": 0})
        with self.assertRaisesRegex(ValueError, "sparse"):
            base.zero_input(["main.a[0]", "main.a[2]"])

    def test_reads_only_r1cs_header_and_direct_main_symbols(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            prime = bytes([3]) + bytes(31)
            header = struct.pack("<I", 32) + prime + struct.pack("<IIIIQI", 5, 1, 1, 2, 5, 0)
            with (folder / "main.r1cs").open("wb") as output:
                output.write(b"r1cs" + struct.pack("<II", 1, 3))
                for kind, payload in [(1, header), (2, b""), (3, b"" * 40)]:
                    output.write(struct.pack("<IQ", kind, len(payload)) + payload)
            (folder / "main.sym").write_text(
                "0,0,0,main.one\n1,1,0,main.out\n2,2,0,main.in[0]\n"
                "3,3,0,main.in[1]\n4,4,0,main.scalar\n"
            )
            shape = base.read_r1cs_shape(folder / "main.r1cs")
            self.assertEqual(shape["outputs"], 1)
            self.assertEqual(shape["private_inputs"], 2)
            self.assertEqual(base.main_input_names(folder / "main.sym", {"in", "scalar"}),
                             ["main.in[0]", "main.in[1]", "main.scalar"])

    def test_direct_main_inputs_allow_internal_input_wires(self):
        with tempfile.TemporaryDirectory() as temporary:
            symbol = Path(temporary) / "main.sym"
            symbol.write_text("0,0,0,main.value[0]\n1,1,0,main.value[1]\n"
                              "2,2,0,main.Child.internalInput\n")
            self.assertEqual(base.main_input_names(symbol, {"value"}),
                             ["main.value[0]", "main.value[1]"])
            with self.assertRaisesRegex(ValueError, "missing"):
                base.main_input_names(symbol, {"value", "other"})

    def test_same_main_call_is_admitted_without_matching_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "test").mkdir()
            primary = folder / "main.circom"
            primary.write_text("component main { public [x] } = Example(7, 8);\n")
            (folder / "alternative.circom").write_text(
                "// same main\ncomponent main = Example(7,8);\n"
            )
            (folder / "test/example.test.js").write_text(
                'const source = "alternative.circom"; circuit.calculateWitness(input);\n'
            )
            (folder / "test/other.test.js").write_text(
                'const source = "other.circom"; circuit.calculateWitness(input);\n'
            )
            matches = base.matching_project_files(folder, primary)
            self.assertEqual([path.name for path in matches], ["example.test.js"])

    def test_project_test_advances_after_first_captured_input_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "project"
            (source / "test").mkdir(parents=True)
            entrypoint = source / "main.circom"
            entrypoint.write_text("component main = Example();\n")
            for name in ("a.test.js", "b.test.js"):
                (source / "test" / name).write_text(
                    'const source = "main.circom"; circuit.calculateWitness(input);\n'
                )
            row = {"project_root": str(source), "entrypoint_absolute": str(entrypoint)}
            validation_calls = []

            def fake_validate(path, _remaining):
                validation_calls.append(path.name)
                if len(validation_calls) == 1:
                    return False, "main_input_keys_mismatch", {}
                return True, "passed", {"witness_sha256": "a" * 64}

            def fake_copy(command, **_kwargs):
                staging = Path(command[-1])
                for original in source.rglob("*"):
                    relative = original.relative_to(source)
                    if original.is_dir():
                        (staging / relative).mkdir(parents=True, exist_ok=True)
                    else:
                        (staging / relative).parent.mkdir(parents=True, exist_ok=True)
                        (staging / relative).write_bytes(original.read_bytes())
                return mock.Mock(returncode=0)

            def fake_run(_command, _timeout, **kwargs):
                capture = Path(kwargs["env"]["N6_J1_CAPTURE_PATH"])
                capture.write_text(json.dumps({"kind": "calculateWitness",
                                               "source": str(kwargs["cwd"] / "main.circom"),
                                               "input": {"x": len(validation_calls)}}) + "\n")
                return 0, 0.01, "completed", None

            with mock.patch.object(base.subprocess, "run", side_effect=fake_copy), \
                    mock.patch.object(base, "test_command", return_value=(["test"], source)), \
                    mock.patch.object(base, "project_test_setup", return_value=([], None)), \
                    mock.patch.object(base, "run_project_quiet", side_effect=fake_run):
                picked, failures, _execution = base.project_test_selection(
                    row, folder / "output", base.time.monotonic() + 10, fake_validate, {}
                )
            self.assertIsNotNone(picked)
            self.assertEqual(len(validation_calls), 2)
            self.assertEqual(failures[0]["reason"], "main_input_keys_mismatch")
            self.assertFalse((folder / "output/project-test-staging").exists())

    def test_committed_json_without_git_provenance_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, reason = base.committed_json_paths({"project_root": temporary})
            self.assertEqual(paths, [])
            self.assertEqual(reason, "committed_json_provenance_unavailable")

    def test_missing_zkbugs_path_and_l_series_family(self):
        row = {"dataset_cases": [{"item_id": "one", "original_input_path": None}],
               "entrypoint_relative": "src/circuit.circom",
               "project_root": "/tmp/aq-001/project"}
        paths, reasons = base.resolve_candidates(row, "a_zkbugs", {}, Path("/tmp"))
        self.assertEqual(paths, [])
        self.assertEqual(reasons[0]["reason"], "zkbugs_input_missing")
        inputs = {("inference", "src/circuit.circom"): [Path("/tmp/input.json")]}
        paths, reasons = base.resolve_candidates(row, "b_l_series", inputs, Path("/tmp"))
        self.assertEqual(paths, [])
        self.assertEqual(reasons[0]["reason"], "matching_l_series_input_missing")


if __name__ == "__main__":
    unittest.main()
