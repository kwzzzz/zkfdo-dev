#!/usr/bin/env python3
"""Pure point-cipher escrow construction for the recorded aq-024 ZTransaction.

Its DataEscrowPaddingPointSize_Fn is zero. Nine uint64 plaintexts are mapped to
BabyJub Base8 points and followed by two output root-spend public-key points.
The recorded source, rather than its older comments, defines the shared-key
chain as r_next = low252(Poseidon(shared)), shared = r * recipient_public.
The main hiding point uses a DOUBLE hash: low252(Poseidon(Poseidon(shared0))).
DAO/zone point ciphertexts have no hiding point and no HMAC. This module performs
no file/environment reads and never invokes the arithmetic helper's lock loader.
"""

from __future__ import annotations

from n6_b6_construct_input_4c221df7 import BASE8, point_add, poseidon, scalar_mul, test_scalar


MASK252 = (1 << 252) - 1


def _uint(value: int, width: int) -> int:
    result = int(value)
    if not 0 <= result < 1 << width:
        raise ValueError(f"legacy escrow value outside uint{width}")
    return result


def _bits(values: list, width: int) -> int:
    if len(values) != width:
        raise ValueError("legacy escrow bit-array shape differs")
    return sum(_uint(value, 1) << index for index, value in enumerate(values))


def serialize_escrow_legacy(values: dict) -> list[int]:
    """Recorded DataEscrowSerializer(2,2,32): nine separate uint64 words."""
    pairs = ("utxoInMerkleTreeSelector", "utxoInPathIndices", "utxoInOriginZoneId",
             "utxoOutTargetZoneId", "utxoInAmount", "utxoOutAmount")
    if any(len(values[field]) != 2 for field in pairs):
        raise ValueError("legacy escrow requires two input/output UTXOs")
    asset = values["utxoZAsset"]
    if isinstance(asset, list):
        asset = asset[0]
    packed_account = _uint(values["zAccountUtxoInZoneId"], 16)
    packed_account += _uint(values["zAccountUtxoInId"], 24) << 16
    for index in range(2):
        packed_account += _bits(values["utxoInMerkleTreeSelector"][index], 2) << (40 + 2 * index)
    result = [_uint(asset, 64), packed_account, _uint(values["zAccountUtxoInNonce"], 32)]
    result += [_uint(value, 64) for value in values["utxoInAmount"]]
    result += [_uint(value, 64) for value in values["utxoOutAmount"]]
    for index in range(2):
        result.append(_uint(values["utxoOutTargetZoneId"][index], 16) +
                      (_uint(values["utxoInOriginZoneId"][index], 16) << 16) +
                      (_bits(values["utxoInPathIndices"][index], 32) << 32))
    return result


def multi_poseidon(values: list[int], constants: dict) -> int:
    """Source MultiPoseidon: recursively split at floor(n/2) above 15 inputs."""
    if not values:
        raise ValueError("MultiPoseidon requires at least one input")
    if len(values) <= 15:
        return poseidon(values, constants)
    middle = len(values) // 2
    return poseidon([multi_poseidon(values[:middle], constants),
                     multi_poseidon(values[middle:], constants)], constants)


def encrypt_legacy(scalars: list[int], points: list[tuple[int, int]],
                   public_key: tuple[int, int], ephemeral_random: int,
                   constants: dict) -> dict:
    """Recorded main ciphertext with zero padding; return both coordinates."""
    if not scalars or not points:
        raise ValueError("legacy main escrow requires scalar and point messages")
    messages = [scalar_mul(BASE8, _uint(value, 64)) for value in scalars] + list(points)
    random = ephemeral_random
    shared = []
    for _ in messages:
        point = scalar_mul(public_key, random)
        shared.append(point)
        random = poseidon(list(point), constants) & MASK252
    hiding_scalar = poseidon([poseidon(list(shared[0]), constants)], constants) & MASK252
    hiding_point = scalar_mul(public_key, hiding_scalar)
    ciphertext = [point_add(point_add(message, secret), hiding_point)
                  for message, secret in zip(messages, shared, strict=True)]
    return {"ephemeral_public": scalar_mul(BASE8, ephemeral_random), "ciphertext": ciphertext,
            "ciphertext_hash": multi_poseidon([value for point in ciphertext for value in point], constants)}


def update_escrow_legacy(values: dict, constants: dict, seed: bytes) -> dict:
    """Mutate fresh-key legacy escrow fields after the parent finalizes amounts.

    Call before input commitments/nullifiers or roots dependent on recipient
    keys. The caller owns source auditing and any KYT signature recalculation.
    """
    if not isinstance(seed, bytes) or len(seed) != 32:
        raise ValueError("legacy escrow requires a fixed 32-byte seed")
    if len(values["utxoOutRootSpendPubKey"]) != 2 or any(
            len(point) != 2 for point in values["utxoOutRootSpendPubKey"]):
        raise ValueError("legacy escrow requires two output root public keys")
    recipients = {"data": "dataEscrowPubKey", "dao": "daoDataEscrowPubKey",
                  "zone": "zZoneEdDsaPubKey"}
    prefixes = {"data": "dataEscrow", "dao": "daoDataEscrow", "zone": "zZoneDataEscrow"}
    public_keys, randoms = {}, {}
    for domain, field in recipients.items():
        private = test_scalar(seed, f"legacy-escrow-{domain}-recipient-key".encode("ascii"))
        public_keys[domain] = scalar_mul(BASE8, private)
        values[field] = list(public_keys[domain])
        randoms[domain] = test_scalar(seed, f"legacy-escrow-{domain}-ephemeral-random".encode("ascii"))
    values["utxoInDataEscrowPubKey"] = [list(public_keys["data"]) for _ in range(2)]
    result = encrypt_legacy(serialize_escrow_legacy(values),
                            [tuple(map(int, point)) for point in values["utxoOutRootSpendPubKey"]],
                            public_keys["data"], randoms["data"], constants)
    for domain, prefix in prefixes.items():
        if domain == "data":
            ephemeral, ciphertext = result["ephemeral_public"], result["ciphertext"]
        else:
            ephemeral = scalar_mul(BASE8, randoms[domain])
            shared = scalar_mul(public_keys[domain], randoms[domain])
            ciphertext = [point_add(result["ephemeral_public"], shared)]
        values[prefix + "EphemeralRandom"] = randoms[domain]
        values[prefix + "EphemeralPubKeyAx"] = ephemeral[0]
        values[prefix + "EphemeralPubKeyAy"] = ephemeral[1]
        values[prefix + "EncryptedMessageAx"] = [point[0] for point in ciphertext]
        values[prefix + "EncryptedMessageAy"] = [point[1] for point in ciphertext]
    if int(values.get("kytSignedMessageDataEscrowHash", 0)) != 0:
        values["kytSignedMessageDataEscrowHash"] = result["ciphertext_hash"]
    return {"fresh_recipient_keys": list(recipients.values()), "synthetic_test_keys_only": True,
            "ciphertext_points": {"data": 11, "dao": 1, "zone": 1}, "padding_points": 0,
            "scalar_plaintexts": 9, "point_plaintexts": 2, "hmac_used": False,
            "shared_key_chain": "shared[i]=r[i]*recipient; r[i+1]=low252(Poseidon(shared[i]))",
            "main_hiding_point": "low252(Poseidon([Poseidon(shared[0])]))*recipient",
            "main_ciphertext": "scalar*Base8 (or plaintext point) + shared[i] + hidingPoint",
            "dao_zone_ciphertext": "main ephemeral point + own ECDH shared point",
            "ciphertext_hash": "MultiPoseidon(interleaved X,Y); recursive floor-half split above 15 inputs"}
