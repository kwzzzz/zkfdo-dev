#!/usr/bin/env python3
"""Construct an active Panther renewal from its committed nonzero test scenario."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = Path(__file__).with_suffix(".lock.json")
FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
ROUNDS_PARTIAL = [56, 57, 56, 60, 60, 63, 64, 63, 60, 66, 60, 65, 70, 60, 64, 68]
SUBORDER = 2736030358979909402780800718157159386076813972158567259200215660948447373041
BASE8 = (
    5299619240641551281634865583518297030282874472190772894086521144482721001553,
    16950150798460657717958625567821834550301663161624707787222815936182638968203,
)


def load_locked_sources() -> tuple[str, dict]:
    lock = json.loads(LOCK.read_text())
    for label in ("test_source", "poseidon_constants", "panther_circom_constants", "eddsa_source"):
        path = ROOT / lock[label + "_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != lock[label + "_sha256"]:
            raise ValueError(f"pinned {label} changed")
    package = ROOT / lock["panther_circomlib_package_path"]
    if json.loads(package.read_text())["version"] != lock["panther_circomlib_version"]:
        raise ValueError("pinned Panther circomlib version changed")
    js_package = ROOT / lock["eddsa_package_path"]
    if json.loads(js_package.read_text())["version"] != lock["eddsa_package_version"]:
        raise ValueError("pinned Panther circomlibjs version changed")
    return ((ROOT / lock["test_source_path"]).read_text(),
            json.loads((ROOT / lock["poseidon_constants_path"]).read_text()))


def evaluate_literal(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.List):
        return [evaluate_literal(item) for item in node.elts]
    if isinstance(node, ast.Dict):
        return {evaluate_literal(key): evaluate_literal(value)
                for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Pow)):
        left, right = evaluate_literal(node.left), evaluate_literal(node.right)
        if not isinstance(left, int) or not isinstance(right, int) or right > 20 and isinstance(node.op, ast.Pow):
            raise ValueError("unsafe fixture arithmetic")
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left ** right
    raise ValueError(f"unsupported fixture expression: {type(node).__name__}")


def parse_committed_scenario(source: str) -> dict:
    start = source.index("const nonZeroInput = {") + len("const nonZeroInput = ")
    end = source.index("\n    };", start) + len("\n    }")
    block = source[start:end]
    block = re.sub(r"//[^\n]*", "", block)
    block = re.sub(r"\b(0x[0-9a-fA-F]+|[0-9]+)n\b", r"\1", block)
    block = re.sub(r"(?m)^(\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', block)
    result = evaluate_literal(ast.parse(block, mode="eval").body)
    if len(result) < 75 or not all(isinstance(key, str) for key in result):
        raise ValueError("unexpected committed scenario shape")
    return result


def poseidon(values: list[int], constants: dict) -> int:
    size = len(values) + 1
    c = [int(value, 0) for value in constants["C"][size - 2]]
    matrix = [[int(value, 0) for value in row] for row in constants["M"][size - 2]]
    state = [0] + [value % FIELD for value in values]
    for round_number in range(8 + ROUNDS_PARTIAL[size - 2]):
        state = [(state[i] + c[round_number * size + i]) % FIELD for i in range(size)]
        if round_number < 4 or round_number >= 4 + ROUNDS_PARTIAL[size - 2]:
            state = [pow(value, 5, FIELD) for value in state]
        else:
            state[0] = pow(state[0], 5, FIELD)
        state = [sum(matrix[i][j] * state[j] for j in range(size)) % FIELD
                 for i in range(size)]
    return state[0]


def seed_int(seed: bytes, domain: bytes, bound: int) -> int:
    return int.from_bytes(hashlib.sha256(seed + b":" + domain).digest(), "big") % bound


def point_add(first: tuple[int, int], second: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = first
    x2, y2 = second
    product = (168696 * x1 * x2 * y1 * y2) % FIELD
    x = ((x1 * y2 + x2 * y1) * pow((1 + product) % FIELD, -1, FIELD)) % FIELD
    y = ((y1 * y2 - 168700 * x1 * x2) * pow((1 - product) % FIELD, -1, FIELD)) % FIELD
    return x, y


def scalar_mul(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    result = (0, 1)
    while scalar:
        if scalar & 1:
            result = point_add(result, point)
        point = point_add(point, point)
        scalar >>= 1
    return result


def test_scalar(seed: bytes, domain: bytes) -> int:
    return 1 + seed_int(seed, domain, SUBORDER - 1)


def merkle_fold(leaf: int, siblings: list[int], indices: list[int], constants: dict) -> int:
    if len(siblings) != len(indices):
        raise ValueError("Merkle path length mismatch")
    current = leaf
    for sibling, index in zip(siblings, indices):
        if index not in (0, 1):
            raise ValueError("nonbinary Merkle index")
        current = poseidon([current, sibling] if index == 0 else [sibling, current], constants)
    return current


def note_commitment(values: dict, spend_key: tuple[int, int], amount: int,
                    expiry: int, nonce: int, create_time: int, constants: dict) -> int:
    key_hash = poseidon([
        *spend_key,
        *values["zAccountUtxoInRootSpendPubKey"],
        *values["zAccountUtxoInReadPubKey"],
        *values["zAccountUtxoInNullifierPubKey"],
    ], constants)
    return poseidon([
        key_hash, values["zAccountUtxoInMasterEOA"], values["zAccountUtxoInId"],
        amount, values["zAccountUtxoInPrpAmount"], values["zAccountUtxoInZoneId"],
        expiry, nonce, values["zAccountUtxoInTotalAmountPerTimePeriod"],
        create_time, values["zAccountUtxoInNetworkId"],
    ], constants)


def new_kyc_signature(seed: bytes, message_hash: int) -> tuple[list[int], list[int]]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("pinned EdDSA helper requires Node")
    lock = json.loads(LOCK.read_text())
    package_dir = (ROOT / lock["eddsa_package_path"]).parent.resolve()
    private_seed = hashlib.sha256(seed + b":kyc-eddsa-seed").hexdigest()
    helper = (
        "const c=require(process.argv[1]);"
        "const sk=Buffer.from(process.argv[2],'hex');"
        "const m=BigInt(process.argv[3]);"
        "const pub=c.eddsa.prv2pub(sk);"
        "const sig=c.eddsa.signPoseidon(sk,m);"
        "if(!c.eddsa.verifyPoseidon(m,sig,pub))throw Error('fresh KYC signature invalid');"
        "process.stdout.write(JSON.stringify({pub:pub.map(x=>x.toString()),"
        "sig:[sig.S,sig.R8[0],sig.R8[1]].map(x=>x.toString())}));"
    )
    process = subprocess.run(
        [node, "-e", helper, str(package_dir), private_seed, str(message_hash)],
        capture_output=True, text=True, timeout=30, check=True)
    parsed = json.loads(process.stdout)
    return [int(item) for item in parsed["pub"]], [int(item) for item in parsed["sig"]]


def decimal_strings(value):
    if isinstance(value, list):
        return [decimal_strings(item) for item in value]
    if isinstance(value, int):
        return str(value)
    raise ValueError("unexpected scenario value")


def construct(seed_text: str) -> dict:
    source, constants = load_locked_sources()
    values = parse_committed_scenario(source)
    seed = hashlib.sha256(seed_text.encode()).digest()

    root_private = test_scalar(seed, b"root-spend-key")
    root_public = scalar_mul(BASE8, root_private)
    read_public = scalar_mul(BASE8, test_scalar(seed, b"read-key"))
    nullifier_private = test_scalar(seed, b"nullifier-key")
    nullifier_public = scalar_mul(BASE8, nullifier_private)
    in_random = test_scalar(seed, b"input-spend-random")
    out_random = test_scalar(seed, b"output-spend-random")
    master_eoa = 1 + seed_int(seed, b"master-eoa", 1 << 160)
    values["zAccountUtxoInRootSpendPrivKey"] = root_private
    values["zAccountUtxoInRootSpendPubKey"] = list(root_public)
    values["zAccountUtxoInReadPubKey"] = list(read_public)
    values["zAccountUtxoInNullifierPrivKey"] = nullifier_private
    values["zAccountUtxoInNullifierPubKey"] = list(nullifier_public)
    values["zAccountUtxoInSpendKeyRandom"] = in_random
    values["zAccountUtxoOutSpendKeyRandom"] = out_random
    values["zAccountUtxoInMasterEOA"] = master_eoa
    values["kycSignedMessageSender"] = master_eoa
    values["kycSignedMessageSigner"] = master_eoa
    values["kycSignedMessageReceiver"] = 1 + seed_int(seed, b"kyc-receiver", 1 << 160)

    in_spend_public = scalar_mul(root_public, in_random)
    in_commitment = note_commitment(
        values, in_spend_public, values["zAccountUtxoInZkpAmount"],
        values["zAccountUtxoInExpiryTime"], values["zAccountUtxoInNonce"],
        values["zAccountUtxoInCreateTime"], constants)
    values["zAccountUtxoInCommitment"] = in_commitment
    values["zAccountUtxoInNullifier"] = poseidon([nullifier_private, in_commitment], constants)
    values["busMerkleRoot"] = merkle_fold(
        in_commitment, values["zAccountUtxoInPathElements"][:26],
        values["zAccountUtxoInPathIndices"][:26], constants)

    out_spend_public = scalar_mul(root_public, out_random)
    values["zAccountUtxoOutCommitment"] = note_commitment(
        values, out_spend_public, values["zAccountUtxoOutZkpAmount"],
        values["zAccountUtxoOutExpiryTime"], values["zAccountUtxoInNonce"] + 1,
        values["zAccountUtxoOutCreateTime"], constants)

    kyc_random = poseidon([out_random], constants)
    kyc_internal = poseidon([
        values["kycSignedMessageSigner"], values["kycSignedMessageChargedAmountZkp"],
        kyc_random, values["kycSignedMessageSessionId"], values["kycSignedMessageRuleId"],
    ], constants)
    signed_message = poseidon([
        values["kycSignedMessagePackageType"], values["kycSignedMessageTimestamp"],
        values["kycSignedMessageSender"], values["kycSignedMessageReceiver"], kyc_internal,
    ], constants)
    values["kycSignedMessageHash"] = signed_message
    kyc_public, kyc_signature = new_kyc_signature(seed, signed_message)
    values["kycEdDsaPubKey"] = kyc_public
    values["kycSignature"] = kyc_signature
    trust_leaf = poseidon([*kyc_public, values["kycEdDsaPubKeyExpiryTime"]], constants)
    values["trustProvidersMerkleRoot"] = merkle_fold(
        trust_leaf, values["kycPathElements"], values["kycPathIndices"], constants)

    zone_public = scalar_mul(BASE8, test_scalar(seed, b"zone-eddsa-key"))
    escrow_public = scalar_mul(BASE8, test_scalar(seed, b"zone-data-escrow-key"))
    dao_escrow_public = scalar_mul(BASE8, test_scalar(seed, b"dao-data-escrow-key"))
    values["zZoneEdDsaPubKey"] = list(zone_public)
    values["zZoneDataEscrowPubKey"] = list(escrow_public)
    values["daoDataEscrowPubKey"] = list(dao_escrow_public)
    values["zZoneSealing"] = 1
    zone_inner = poseidon([
        values["zAccountUtxoInZoneId"], *zone_public, values["zZoneOriginZoneIDs"],
        values["zZoneTargetZoneIDs"], values["zZoneNetworkIDsBitMap"],
        values["zZoneTrustProvidersMerkleTreeLeafIDsAndRulesList"],
        values["zZoneKycExpiryTime"], values["zZoneKytExpiryTime"],
        values["zZoneDepositMaxAmount"], values["zZoneWithdrawMaxAmount"],
        values["zZoneInternalMaxAmount"], values["zZoneZAccountIDsBlackList"],
        values["zZoneMaximumAmountPerTimePeriod"],
        values["zZoneTimePeriodPerMaximumAmount"],
    ], constants)
    zone_leaf = poseidon([*escrow_public, 1, zone_inner], constants)
    values["zZoneMerkleRoot"] = merkle_fold(
        zone_leaf, values["zZonePathElements"], values["zZonePathIndices"], constants)

    network_leaf = poseidon([
        1, values["zNetworkChainId"], values["zNetworkId"],
        values["zNetworkIDsBitMap"], values["forTxReward"], values["forUtxoReward"],
        values["forDepositReward"], *dao_escrow_public,
    ], constants)
    values["zNetworkTreeMerkleRoot"] = merkle_fold(
        network_leaf, values["zNetworkTreePathElements"],
        values["zNetworkTreePathIndices"], constants)
    values["staticTreeMerkleRoot"] = poseidon([
        values["zAssetMerkleRoot"], values["zAccountBlackListMerkleRoot"],
        values["zNetworkTreeMerkleRoot"], values["zZoneMerkleRoot"],
        values["trustProvidersMerkleRoot"],
    ], constants)
    values["forestMerkleRoot"] = poseidon([
        values["taxiMerkleRoot"], values["busMerkleRoot"],
        values["ferryMerkleRoot"],
    ], constants)

    salt = 1 + int.from_bytes(hashlib.sha256(seed + b":salt").digest(), "big") % (FIELD - 1)
    values["salt"] = salt
    values["saltHash"] = poseidon([salt], constants)
    values["extraInputsHash"] = 1 + seed_int(seed, b"extra-input-anchor", FIELD - 1)
    return {key: decimal_strings(value) for key, value in values.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="n6-b6-4c221df7-2026-10-18")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = construct(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        out.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
