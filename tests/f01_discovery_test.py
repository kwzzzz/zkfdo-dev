"""F-01 measurement helpers; no external project, compiler, or fuzzer."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "f01", Path(__file__).resolve().parents[1] / "scripts/measure_f01_discovery.py")
f01 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(f01)

HASH = "[sha256:" + "ab" * 32 + "]"


def target(parent, name, line, key):
    return {"origin": {"component_name": name, "line": line}, "parent_instance_key": parent,
            "instance_key": key}


class InstanceKeyTests(unittest.TestCase):
    def test_signed_scalars_and_array_hashes_are_concrete(self):
        self.assertEqual(f01.parse_instance(f"lib.circom::Mix(3, -2, {HASH})"), ("Mix", ["3", "-2", HASH]))
        self.assertEqual(f01.parse_instance("lib.circom::Leaf()"), ("Leaf", []))

    def test_symbolic_or_malformed_parameters_are_rejected(self):
        for key in ("lib.circom::Mix(n)", "lib.circom::Mix([sha256:12])", None, "Mix(1)"):
            with self.assertRaises(ValueError):
                f01.parse_instance(key)

    def test_manifest_points_targets_at_the_capture_only_when_selected(self):
        discovery = {"root_instance_key": "main.circom::Main(2)",
                     "compile_units": [{"key": "u1", "wrapper_path": "/w/target.circom",
                                        "instance_key": f"lib.circom::Leaf({HASH})"}]}
        args = ("synthetic/example", "0" * 40, Path("/p"), Path("/p/main.circom"), discovery, [Path("/p/lib")])
        with_capture = f01.manifest_for(*args, Path("/c/instance-capture.json"))
        self.assertEqual([row["instance_capture"] for row in with_capture["targets"]],
                         ["/c/instance-capture.json"] * 2)
        self.assertEqual(with_capture["targets"][1]["concrete_parameters"], [HASH])
        without = f01.manifest_for(*args, None)
        self.assertTrue(all("instance_capture" not in row for row in without["targets"]))


class ComparisonTests(unittest.TestCase):
    def test_anonymous_binding_context_is_ignored_and_differences_are_listed(self):
        old = {"root_instance_key": "m::Main()", "compile_units": [{"instance_key": "l::A(1)"}],
               "targets": [target("m::Main()", "@anonymous:4:10[i=0]", 4, "l::A(1)"),
                           target("m::Main()", "@anonymous:4:10[i=1]", 4, "l::A(1)"),
                           target("m::Main()", "c", 7, "l::B(2)")]}
        new = {"root_instance_key": "m::Main()", "compile_units": [{"instance_key": "l::A(1)"}],
               "targets": [target("m::Main()", "@anonymous:4:10", 4, "l::A(1)"),
                           target("m::Main()", "c", 7, "l::B(3)"),
                           target("m::Main()", "d", 9, "l::C()")]}
        result = f01.compare(old, new)
        self.assertTrue(result["root_equal"])
        self.assertEqual(result["slots_compared"], 3)
        self.assertEqual([(row["component_name"], row["c03"], row["f01"]) for row in result["slot_differences"]],
                         [("c", ["l::B(2)"], ["l::B(3)"]), ("d", [], ["l::C()"])])

    def test_automatic_status_follows_the_c03_rule(self):
        self.assertEqual(f01.automatic_status("success", "partial"), "partial")
        self.assertEqual(f01.automatic_status("failure", "success"), "failed")
        self.assertEqual(f01.automatic_status("timeout", "success"), "failed")
        self.assertEqual(f01.automatic_status("not_started", "failed"), "not_started")
        self.assertEqual(f01.automatic_status("missing", "failed"), "unknown")


if __name__ == "__main__":
    unittest.main()
