#!/usr/bin/env python3
"""v2.1 must return exactly what v2 returns; only link membership uses a set."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_a_remeasure_aq_cleanup_v2 as v2  # noqa: E402
import n6_a_remeasure_aq_cleanup_v2_1 as v21  # noqa: E402


def build(root: Path) -> Path:
    target = root / "002200" / "attempt-0001"
    for i in range(30):
        d = target / f"d{i % 4}" / f"s{i % 3}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"f{i}.json").write_text("x" * i)
        if i % 5 == 0:
            os.symlink(d / f"f{i}.json", d / f"l{i}")
    os.symlink(target / "d0", target / "dirlink")
    os.symlink(target / "missing", target / "dangling")
    return target


class Equivalence(unittest.TestCase):
    def test_inventory_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = build(Path(tmp).resolve())
            self.assertEqual(v2._inventory(target), v21._inventory(target))
            self.assertEqual(v2.scan_stats(target), v21.scan_stats(target))

    def test_absent_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp).resolve() / "nope"
            self.assertEqual(v2._inventory(missing), v21._inventory(missing))

    def test_only_membership_line_differs(self):
        here = Path(__file__).resolve().parents[1] / "scripts"
        old = (here / "n6_a_remeasure_aq_cleanup_v2.py").read_text().splitlines()
        new = (here / "n6_a_remeasure_aq_cleanup_v2_1.py").read_text().splitlines()
        changed = [line for line in new if line not in old]
        self.assertEqual(len(changed), 3, changed)


if __name__ == "__main__":
    unittest.main()
