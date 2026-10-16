import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class N6PrepareAStage1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "scripts/n6_prepare_a_stage1.py"
        spec = importlib.util.spec_from_file_location("n6_prepare_a_stage1", path)
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.module)
        cls.inventory = cls.module.unit_inventory()

    def test_inventory_deduplicates_labels_but_keeps_links(self):
        units = self.inventory["aq_stage1_units"]
        keys = {(row["project"].lower(), row["revision"], row["entrypoint"],
                 row["entrypoint_kind"], row["revision_kind"],
                 tuple(row["item_ids"]) if row["revision_kind"] == "leave_one_out" else None)
                for row in units}
        self.assertEqual(len(keys), len(units))
        self.assertTrue(any(len(row["item_ids"]) > 1 for row in units))

    def test_leave_one_out_units_retain_scope_and_vulnerable_revision(self):
        rows = [row for row in self.inventory["aq_stage1_units"]
                if row["revision_kind"] == "leave_one_out"]
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["vulnerable_revision"])
            self.assertTrue(row["leave_one_out"]["planned_diff_scope"]["path"])

    def test_no_fuzz_and_fixed_tool_hash(self):
        self.assertEqual(self.inventory["zkfuzz_invocations"], 0)
        self.assertEqual(self.module.sha256(self.module.ZKFDO), self.module.ZKFDO_SHA)


if __name__ == "__main__":
    unittest.main()
