#!/usr/bin/env python3
"""Verify preserved artifacts and the direct-fixture witness without rerunning fuzzing."""

import hashlib
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise SystemExit(message)


root = Path(__file__).resolve().parent
listed = set()
for line in (root / "SHA256SUMS").read_text().splitlines():
    expected, name = line.split("  ", 1)
    require(name not in listed, f"Duplicate checksum entry: {name}")
    listed.add(name)
    actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
    require(actual == expected, f"Checksum mismatch: {name}")

actual_files = {
    str(path.relative_to(root))
    for path in root.rglob("*")
    if path.is_file() and path.name != "SHA256SUMS"
}
require(listed == actual_files, "Checksum file inventory differs from archive")
original = json.loads((root / "original/counterexample.json").read_text())
replay = json.loads((root / "reproduction/counterexample.json").read_text())
for key in ("1_main_template", "2_search_mode", "4_git_hash_of_zkfuzz", "5_flag", "7_assignment"):
    require(original[key] == replay[key], f"Reproduction differs at {key}")
require(original["8_auxiliary_result"]["mutation_test_config"] == replay["8_auxiliary_result"]["mutation_test_config"], "Resolved mutation configuration differs")
for result in (original, replay):
    progress = result["8_auxiliary_result"]["mutation_test_log"]
    require(progress["random_seed"] == 424242, "Seed differs")
    require(progress["generation"] == 0, "Generation differs")
require(json.loads((root / "mutation-settings.json").read_text()) == {"seed": 424242}, "Settings differ")

p = 21888242871839275222246405745257275088548364400416034343698204186575808495617
assignment = {name: int(value) for name, value in original["7_assignment"].items()}
a = [assignment[f"main.xor.a_bits[{i}]"] for i in range(32)]
b = [assignment[f"main.xor.b_bits[{i}]"] for i in range(32)]
x = [assignment[f"main.xor.xor_bits[{i}]"] for i in range(32)]
require(assignment["main.a"] == assignment["main.xor.a"] == 6, "Input a differs")
require(assignment["main.b"] == assignment["main.xor.b"] == 1, "Input b differs")
require(all((ai + bi - 2 * ai * bi - xi) % p == 0 for ai, bi, xi in zip(a, b, x)), "XOR relation fails")
packed = lambda values: sum(value * (1 << i) for i, value in enumerate(values)) % p
require(packed(x) == assignment["main.xor.out"] == assignment["main.out"] == p - 17179770361, "Output packing differs")
require(int(original["5_flag"]["2_expected_output"]["value"]) == (6 ^ 1) == 7, "Expected XOR differs")
require(packed(a) == p - 17179869178 and packed(b) == 98817, "Input decomposition differs")
require(a[28] == p - 64 and b[14] == 6, "Non-Boolean witness differs")
require((6 - packed(a)) * 6 % p == 103079215104, "Audit-style a residual differs")
require((1 - packed(b)) % p == p - 98816, "Audit-style b residual differs")
print(f"Verified {len(listed)} checksums; candidate assignment, flag, seed and generation match.")
print("Direct-fixture witness equations hold; expected XOR = 7; out = p - 17179770361.")
print("Scope: wrapper-only. Original-project source, reachability and proof are unverified.")
