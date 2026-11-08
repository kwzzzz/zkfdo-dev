#!/usr/bin/env python3
"""Small synthetic tests for the cold A S+J runner helpers."""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import n7_a_sj_cold_e2e_20261029 as runner


def fake_r1cs(path, constraints):
    n8 = 32
    header = struct.pack("<I", n8) + bytes(n8) + struct.pack("<IIIIQI", 10, 1, 2, 3, 10, constraints)
    other = b"\x00" * 7
    body = struct.pack("<IQ", 2, len(other)) + other + struct.pack("<IQ", 1, len(header)) + header
    Path(path).write_bytes(b"r1cs" + struct.pack("<II", 1, 2) + body)


class Tests(unittest.TestCase):
    def test_header_after_other_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.r1cs"
            fake_r1cs(path, 401664)
            self.assertEqual(runner.r1cs_constraints(path), 401664)

    def test_rejects_non_r1cs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.r1cs"
            path.write_bytes(b"nope" + bytes(8))
            with self.assertRaises(ValueError):
                runner.r1cs_constraints(path)

    def test_tie_break_is_name_order_within_size(self):
        def row(size, name, params=(), ident="t"):
            return {"ranking": {"size": size}, "target_id": ident,
                    "definition": {"template_name": name, "concrete_parameters": list(params)}}
        rows = [row(1, "Subtract"), row(1, "AssertBit"), row(2, "IsZero"), row(1, "AssertBit", ident="s")]
        ordered = sorted(rows, key=runner.order_key)
        self.assertEqual([(r["definition"]["template_name"], r["target_id"]) for r in ordered],
                         [("AssertBit", "s"), ("AssertBit", "t"), ("Subtract", "t"), ("IsZero", "t")])


if __name__ == "__main__":
    unittest.main()
