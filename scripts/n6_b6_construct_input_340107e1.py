#!/usr/bin/env python3
"""Construct a deterministic active first-batch MACI tally for Vota."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = Path(__file__).with_suffix(".lock.json")
FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
ROUNDS_PARTIAL = [56, 57, 56, 60, 60, 63, 64, 63, 60, 66, 60, 65, 70, 60, 64, 68]
TREE_ARITY = 5
DEPTH = 3
BATCH_SIZE = TREE_ARITY ** DEPTH
MAX_VOTES = 10 ** 24
SUBORDER = 2736030358979909402780800718157159386076813972158567259200215660948447373041
BASE8 = (
    5299619240641551281634865583518297030282874472190772894086521144482721001553,
    16950150798460657717958625567821834550301663161624707787222815936182638968203,
)


def seed_int(seed: bytes, domain: bytes, bound: int) -> int:
    return int.from_bytes(hashlib.sha256(seed + b":" + domain).digest(), "big") % bound


def load_constants() -> dict:
    lock = json.loads(LOCK.read_text())
    for label in ("poseidon_constants", "vota_circom_constants"):
        path = ROOT / lock[label + "_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != lock[label + "_sha256"]:
            raise ValueError(f"pinned {label} changed")
    package = ROOT / lock["vota_circomlib_package_path"]
    if json.loads(package.read_text())["version"] != lock["vota_circomlib_version"]:
        raise ValueError("pinned Vota circomlib version changed")
    return json.loads((ROOT / lock["poseidon_constants_path"]).read_text())


def poseidon(values: list[int], constants: dict) -> int:
    size = len(values) + 1
    c = [int(value, 0) for value in constants["C"][size - 2]]
    matrix = [[int(value, 0) for value in row] for row in constants["M"][size - 2]]
    rounds = 8 + ROUNDS_PARTIAL[size - 2]
    state = [0] + [value % FIELD for value in values]
    for round_number in range(rounds):
        state = [(state[i] + c[round_number * size + i]) % FIELD for i in range(size)]
        if round_number < 4 or round_number >= 4 + ROUNDS_PARTIAL[size - 2]:
            state = [pow(value, 5, FIELD) for value in state]
        else:
            state[0] = pow(state[0], 5, FIELD)
        state = [sum(matrix[i][j] * state[j] for j in range(size)) % FIELD
                 for i in range(size)]
    return state[0]


def quin_root(values: list[int], constants: dict) -> int:
    level = values
    while len(level) > 1:
        if len(level) % TREE_ARITY:
            raise ValueError("quinary tree shape invalid")
        level = [poseidon(level[i:i + TREE_ARITY], constants)
                 for i in range(0, len(level), TREE_ARITY)]
    return level[0]


def point_add(first: tuple[int, int], second: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = first
    x2, y2 = second
    product = (168696 * x1 * x2 * y1 * y2) % FIELD
    x = ((x1 * y2 + x2 * y1) * pow((1 + product) % FIELD, -1, FIELD)) % FIELD
    y = ((y1 * y2 - 168700 * x1 * x2) * pow((1 - product) % FIELD, -1, FIELD)) % FIELD
    return x, y


def public_key(seed: bytes, voter: int) -> tuple[int, int]:
    scalar = 1 + seed_int(seed, f"voter-key-{voter}".encode(), SUBORDER - 1)
    result = (0, 1)
    point = BASE8
    while scalar:
        if scalar & 1:
            result = point_add(result, point)
        point = point_add(point, point)
        scalar >>= 1
    return result


def construct(seed_text: str) -> dict:
    seed = hashlib.sha256(seed_text.encode()).digest()
    constants = load_constants()
    votes = [[0] * BATCH_SIZE for _ in range(BATCH_SIZE)]
    state_leaves = [[0] * 5 for _ in range(BATCH_SIZE)]
    for voter in range(3):
        option = 1 + seed_int(seed, f"vote-option-{voter}".encode(), 16)
        weight = 1 + seed_int(seed, f"vote-weight-{voter}".encode(), 4)
        votes[voter][option] = weight
        x, y = public_key(seed, voter)
        state_leaves[voter] = [
            x,
            y,
            5 + seed_int(seed, f"credits-{voter}".encode(), 100),
            quin_root(votes[voter], constants),
            voter + 1,
        ]

    state_subroot = quin_root([poseidon(leaf, constants) for leaf in state_leaves], constants)
    state_root = state_subroot
    for _ in range(3):
        state_root = poseidon([state_root, 0, 0, 0, 0], constants)
    state_salt = 1 + seed_int(seed, b"state-salt", 1 << 120)
    state_commitment = poseidon([state_root, state_salt], constants)

    new_results = [sum(votes[voter][option] * (votes[voter][option] + MAX_VOTES)
                       for voter in range(BATCH_SIZE))
                   for option in range(BATCH_SIZE)]
    new_salt = 1 + seed_int(seed, b"new-results-salt", 1 << 120)
    new_tally_commitment = poseidon([quin_root(new_results, constants), new_salt], constants)
    packed_values = 3 << 32  # numSignUps=3, batchNum=0
    preimage = [packed_values, state_commitment, 0, new_tally_commitment]
    input_hash = int.from_bytes(hashlib.sha256(b"".join(
        value.to_bytes(32, "big") for value in preimage)).digest(), "big") % FIELD
    return {
        "stateRoot": str(state_root),
        "stateSalt": str(state_salt),
        "packedVals": str(packed_values),
        "stateCommitment": str(state_commitment),
        "currentTallyCommitment": "0",
        "newTallyCommitment": str(new_tally_commitment),
        "inputHash": str(input_hash),
        "stateLeaf": [[str(value) for value in leaf] for leaf in state_leaves],
        "statePathElements": [["0"] * 4 for _ in range(3)],
        "votes": [[str(value) for value in row] for row in votes],
        "currentResults": ["0"] * BATCH_SIZE,
        "currentResultsRootSalt": "0",
        "newResultsRootSalt": str(new_salt),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="n6-b6-340107e1-2026-10-18")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = construct(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        out.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
