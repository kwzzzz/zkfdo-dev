"""Guard against accepting an ambiguous or missing normal boundary mapping."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "normal_preparation", Path(__file__).resolve().parents[1] / "scripts/measure_normal_preparation.py"
)
normal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(normal)


def edge(identity, parent, child, component):
    return {"identity": identity, "parent_instance_key": parent,
            "instance_key": child, "origin": {"component_name": component}}


class NormalBoundaryTest(unittest.TestCase):
    def test_reused_configuration_keeps_distinct_dynamic_call_paths(self):
        report = {"root_instance_key": "root", "targets": [
            edge("left", "root", "mid-2", "left"),
            edge("right", "root", "mid-2", "right"),
            edge("inner", "mid-2", "leaf-2", "inner"),
        ]}
        paths = normal.boundary_paths(report)
        inner = [path for target, path in paths if target["identity"] == "inner"]
        self.assertEqual(inner, ["main.left.inner", "main.right.inner"])
        self.assertEqual(len(paths), 4)

    def test_orphan_cycle_and_ambiguous_paths_are_not_silently_skipped(self):
        malformed = [
            [edge("orphan", "missing", "leaf", "x")],
            [edge("cycle", "root", "root", "x")],
            [edge("a", "root", "leaf-2", "x"), edge("b", "root", "leaf-3", "x")],
        ]
        for targets in malformed:
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                normal.boundary_paths({"root_instance_key": "root", "targets": targets})

    def test_missing_eliminated_and_invalid_symbols_do_not_match_zero(self):
        for symbols, name in [({}, "main.out"), ({"main.out": -1}, "main.out"),
                              ({"main.out": 3}, "main.out")]:
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                normal.value_at(symbols, ["1", "0"], name)
        with self.assertRaises(ValueError):
            normal.value_at({"main.out": 1}, ["1", str(normal.FIELD)], "main.out")

    def test_duplicate_symbols_and_existing_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ambiguous.sym"
            path.write_text("1,1,0,main.in\n2,2,0,main.in\n")
            with self.assertRaises(ValueError):
                normal.symbol_indices(path)
            output = Path(directory) / "preserved.json"
            normal.write_json(output, {"preserved": True})
            previous = output.read_bytes()
            with self.assertRaises(FileExistsError):
                normal.write_json(output, {"preserved": False})
            self.assertEqual(output.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
