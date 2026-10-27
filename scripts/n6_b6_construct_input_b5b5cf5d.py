#!/usr/bin/env python3
# Model an issued, unrevoked nonmerklized iden3 claim proven by a live MTP path.
# New seed-derived BabyJub test keys form the user and issuer identities.
"""Construct a deterministic credentialAtomicQueryV3 offchain input."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = Path(__file__).with_suffix(".lock.json")
FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
SUBORDER = 2736030358979909402780800718157159386076813972158567259200215660948447373041
BASE8 = (
    5299619240641551281634865583518297030282874472190772894086521144482721001553,
    16950150798460657717958625567821834550301663161624707787222815936182638968203,
)
AUTH_SCHEMA = 80551937543569765027552589160822318028
CREDENTIAL_SCHEMA = 180410020913331409885634153623124536270
ROUNDS_PARTIAL = [56, 57, 56, 60, 60, 63, 64, 63, 60, 66, 60, 65, 70, 60, 64, 68]


def seed_int(seed: bytes, domain: bytes) -> int:
    return int.from_bytes(hashlib.sha256(seed + b":" + domain).digest(), "little")


def load_poseidon_constants() -> dict:
    lock = json.loads(LOCK.read_text())
    path = ROOT / lock["poseidon_constants_path"]
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != lock["poseidon_constants_sha256"]:
        raise ValueError("pinned Poseidon constants changed")
    package = ROOT / lock["package_json_path"]
    if json.loads(package.read_text())["version"] != lock["package_version"]:
        raise ValueError("pinned circomlibjs version changed")
    return json.loads(raw)


def poseidon(values: list[int], constants: dict) -> int:
    size = len(values) + 1
    if not 2 <= size <= 17:
        raise ValueError("unsupported Poseidon arity")
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


def point_add(first: tuple[int, int], second: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = first
    x2, y2 = second
    product = (168696 * x1 * x2 * y1 * y2) % FIELD
    x = ((x1 * y2 + x2 * y1) * pow((1 + product) % FIELD, -1, FIELD)) % FIELD
    y = ((y1 * y2 - 168700 * x1 * x2) * pow((1 - product) % FIELD, -1, FIELD)) % FIELD
    return x, y


def public_key(seed: bytes, domain: bytes) -> tuple[int, int]:
    scalar = 1 + seed_int(seed, domain) % (SUBORDER - 1)
    result = (0, 1)
    point = BASE8
    while scalar:
        if scalar & 1:
            result = point_add(result, point)
        point = point_add(point, point)
        scalar >>= 1
    return result


def claim_hi_hv(claim: list[int], constants: dict) -> tuple[int, int]:
    return poseidon(claim[:4], constants), poseidon(claim[4:], constants)


def leaf_hash(hi: int, hv: int, constants: dict) -> int:
    return poseidon([hi, hv, 1], constants)


def auth_claim(seed: bytes, domain: bytes, constants: dict) -> list[int]:
    x, y = public_key(seed, domain)
    revocation_nonce = poseidon([x], constants) & ((1 << 64) - 1)
    return [AUTH_SCHEMA, 0, x, y, revocation_nonce, 0, 0, 0]


def identity_id(state: int) -> int:
    # idUtils.circom: genesis is state bits 40..253; checksum sums 29 bytes.
    typ = 0x1202  # iden3 / Polygon / Mumbai, as in the repository's test DID
    genesis = (state >> 40) & ((1 << 216) - 1)
    payload = typ.to_bytes(2, "little") + genesis.to_bytes(27, "little")
    checksum = sum(payload)
    return int.from_bytes(payload + checksum.to_bytes(2, "little"), "little")


def construct(seed_text: str) -> dict:
    seed = hashlib.sha256(seed_text.encode("utf-8")).digest()
    constants = load_poseidon_constants()

    user_auth = auth_claim(seed, b"user-auth-key", constants)
    user_hi, user_hv = claim_hi_hv(user_auth, constants)
    user_root = leaf_hash(user_hi, user_hv, constants)
    user_state = poseidon([user_root, 0, 0], constants)
    user_id = identity_id(user_state)

    # Subject is in index slot 1; expiration and revocation checks are active.
    header = CREDENTIAL_SCHEMA + ((2 | (1 << 3)) << 128)
    expiration = 2030000000
    revocation_nonce = 1 + seed_int(seed, b"claim-revocation") % (1 << 32)
    claim = [header, user_id, 10, 0,
             revocation_nonce + (expiration << 64), 0, 0, 0]
    claim_hi, claim_hv = claim_hi_hv(claim, constants)
    claim_leaf = leaf_hash(claim_hi, claim_hv, constants)

    # Start from a seed-derived issuer auth claim, with a different lowest SMT
    # key bit. The resulting two-leaf proof has one real sibling at level 0.
    for number in range(128):
        issuer_auth = auth_claim(seed, f"issuer-auth-key-{number}".encode(), constants)
        issuer_auth_hi, issuer_auth_hv = claim_hi_hv(issuer_auth, constants)
        if (issuer_auth_hi ^ claim_hi) & 1:
            break
    else:
        raise ValueError("issuer auth and credential SMT keys did not diverge")
    issuer_auth_leaf = leaf_hash(issuer_auth_hi, issuer_auth_hv, constants)
    issuer_genesis_root = issuer_auth_leaf
    issuer_genesis_state = poseidon([issuer_genesis_root, 0, 0], constants)
    issuer_id = identity_id(issuer_genesis_state)
    if claim_hi & 1:
        issuer_claims_root = poseidon([issuer_auth_leaf, claim_leaf], constants)
    else:
        issuer_claims_root = poseidon([claim_leaf, issuer_auth_leaf], constants)
    issuer_state = poseidon([issuer_claims_root, 0, 0], constants)
    inclusion_path = [str(issuer_auth_leaf)] + ["0"] * 39
    empty40 = ["0"] * 40
    empty32 = ["0"] * 32
    value = ["10"] + ["0"] * 63
    verifier_id = 1 + seed_int(seed, b"verifier-id") % (1 << 200)
    return {
        "proofType": "2", "requestID": "23", "userGenesisID": str(user_id),
        "profileNonce": "0", "claimSubjectProfileNonce": "0",
        "issuerID": str(issuer_id), "isRevocationChecked": 1,
        "issuerClaimNonRevMtp": empty40,
        "issuerClaimNonRevMtpNoAux": "1", "issuerClaimNonRevMtpAuxHi": "0",
        "issuerClaimNonRevMtpAuxHv": "0",
        "issuerClaimNonRevClaimsTreeRoot": str(issuer_claims_root),
        "issuerClaimNonRevRevTreeRoot": "0", "issuerClaimNonRevRootsTreeRoot": "0",
        "issuerClaimNonRevState": str(issuer_state),
        "timestamp": "1642074362", "claimSchema": str(CREDENTIAL_SCHEMA),
        "claimPathMtp": empty32, "claimPathMtpNoAux": "0",
        "claimPathMtpAuxHi": "0", "claimPathMtpAuxHv": "0",
        "claimPathKey": "0", "claimPathValue": "0", "slotIndex": 2,
        "operator": 1, "value": value, "valueArraySize": 1,
        "issuerClaim": [str(item) for item in claim],
        "issuerClaimMtp": inclusion_path,
        "issuerClaimClaimsTreeRoot": str(issuer_claims_root),
        "issuerClaimRevTreeRoot": "0", "issuerClaimRootsTreeRoot": "0",
        "issuerClaimIdenState": str(issuer_state),
        "issuerAuthClaim": ["0"] * 8, "issuerAuthClaimMtp": empty40,
        "issuerAuthClaimsTreeRoot": "0", "issuerAuthRevTreeRoot": "0",
        "issuerAuthRootsTreeRoot": "0", "issuerAuthState": "0",
        "issuerAuthClaimNonRevMtp": empty40,
        "issuerAuthClaimNonRevMtpNoAux": "1", "issuerAuthClaimNonRevMtpAuxHi": "0",
        "issuerAuthClaimNonRevMtpAuxHv": "0",
        "issuerClaimSignatureR8x": "0", "issuerClaimSignatureR8y": "0",
        "issuerClaimSignatureS": "0", "linkNonce": "6321",
        "verifierID": str(verifier_id), "nullifierSessionID": "123",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="n6-b6-b5b5cf5d-2026-10-18")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = construct(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
