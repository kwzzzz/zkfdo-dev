#!/usr/bin/env python3
"""Pure escrow construction for recorded A Panther ZSwap (two in/two out).

Formulas follow aq-012's circuits/circuits/templates/
dataEscrowElGamalEncryption.circom and crypto/src/panther/escrow.ts. In particular,
the scalar serializer uses offsets 204/220 for the two input origin zones; some
source comments say 235, while the actual next offset is 236. The point payloads
contain X coordinates only. This module performs no file or environment reads.

The imported module's pure arithmetic definitions have no import-time reads;
its lock loader, input constructor and signature helper are never invoked.
"""

from __future__ import annotations

from n6_b6_construct_input_4c221df7 import BASE8, FIELD, poseidon, scalar_mul, test_scalar


def _uint(value: int, width: int) -> int:
    result = int(value)
    if not 0 <= result < 1 << width:
        raise ValueError(f"escrow scalar outside uint{width}")
    return result


def _bits(values: list, width: int) -> int:
    if len(values) != width:
        raise ValueError("escrow bit-array length differs from recorded ZSwap shape")
    return sum(_uint(value, 1) << index for index, value in enumerate(values))


def serialize_escrow(values: dict) -> list[int]:
    """Recorded DataEscrowSerializer(2,2,32), then the two output key X values."""
    pairs = (
        "utxoInMerkleTreeSelector", "utxoInPathIndices", "utxoInOriginZoneId",
        "utxoOutTargetZoneId", "utxoInAmount", "utxoOutAmount", "utxoOutRootSpendPubKey",
    )
    if any(len(values[name]) != 2 for name in pairs):
        raise ValueError("escrow helper requires exactly two input/output UTXOs")
    if any(len(point) != 2 for point in values["utxoOutRootSpendPubKey"]):
        raise ValueError("escrow output key must have two coordinates")
    first = (_uint(values["utxoZAsset"][0], 64) +
             (_uint(values["zAccountUtxoInId"], 24) << 64) +
             (_uint(values["zAccountUtxoInZoneId"], 16) << 88) +
             (_uint(values["zAccountUtxoInNonce"], 32) << 104))
    for index in range(2):
        first += _bits(values["utxoInMerkleTreeSelector"][index], 2) << (136 + 2 * index)
        first += _bits(values["utxoInPathIndices"][index], 32) << (140 + 32 * index)
        first += _uint(values["utxoInOriginZoneId"][index], 16) << (204 + 16 * index)
    second = sum(_uint(values["utxoOutTargetZoneId"][index], 16) << (16 * index)
                 for index in range(2))
    second += sum(_uint(values["utxoInAmount"][index], 64) << (32 + 64 * index)
                  for index in range(2))
    third = sum(_uint(values["utxoOutAmount"][index], 64) << (64 * index)
                for index in range(2))
    result = [first, second, third] + [int(point[0]) for point in values["utxoOutRootSpendPubKey"]]
    if any(not 0 <= item < FIELD for item in result):
        raise ValueError("escrow plaintext outside SNARK field")
    return result


def encrypt_messages(messages: list[int], public_key: tuple[int, int],
                     ephemeral_random: int, constants: dict) -> dict:
    """Source-defined additive Poseidon encryption and envelope MAC."""
    if not 0 < len(messages) < 14 or any(not 0 <= value < FIELD for value in messages):
        raise ValueError("invalid escrow plaintext shape/range")
    ephemeral_public = scalar_mul(BASE8, ephemeral_random)
    shared_public = scalar_mul(public_key, ephemeral_random)
    key_seed = poseidon(list(shared_public), constants)
    ciphertext = [(value + poseidon([key_seed, index], constants)) % FIELD
                  for index, value in enumerate(messages)]
    mac_key = poseidon([key_seed, len(ciphertext)], constants)
    inner_mac = poseidon([mac_key, *ciphertext], constants)
    return {"ephemeral_public": list(ephemeral_public), "ciphertext": ciphertext,
            "ciphertext_hash": poseidon(ciphertext, constants),
            "hmac": poseidon([mac_key, inner_mac], constants)}


def update_escrow(values: dict, constants: dict, seed: bytes) -> dict:
    """Mutate constructed values with fresh test keys and all escrow bindings.

    Call after output root keys, amounts, account fields and paths are finalized,
    and before deriving UTXO commitments/nullifiers and affected tree roots.
    The caller owns any KYT signatures and source/provenance auditing.
    """
    if not isinstance(seed, bytes) or len(seed) != 32:
        raise ValueError("escrow construction requires a fixed 32-byte seed")
    recipient_fields = {"data": "dataEscrowPubKey", "dao": "daoDataEscrowPubKey",
                        "zone": "zZoneEdDsaPubKey"}
    prefixes = {"data": "dataEscrow", "dao": "daoDataEscrow", "zone": "zZoneDataEscrow"}
    public_keys = {}
    for domain, field in recipient_fields.items():
        private = test_scalar(seed, f"escrow-{domain}-recipient-key".encode("ascii"))
        public_keys[domain] = scalar_mul(BASE8, private)
        values[field] = list(public_keys[domain])
    values["utxoInDataEscrowPubKey"] = [list(public_keys["data"]) for _ in range(2)]

    messages = serialize_escrow(values)
    main_result = None
    for domain in ("data", "dao", "zone"):
        prefix = prefixes[domain]
        random = test_scalar(seed, f"escrow-{domain}-ephemeral-random".encode("ascii"))
        plaintext = messages if domain == "data" else [main_result["ephemeral_public"][0]]
        result = encrypt_messages(plaintext, public_keys[domain], random, constants)
        values[prefix + "EphemeralRandom"] = random
        values[prefix + "EphemeralPubKeyAx"] = result["ephemeral_public"][0]
        values[prefix + "EphemeralPubKeyAy"] = result["ephemeral_public"][1]
        values[prefix + "EncryptedMessage"] = result["ciphertext"]
        values[prefix + "EncryptedMessageHmac"] = result["hmac"]
        if domain == "data":
            main_result = result
    if int(values.get("kytSignedMessageDataEscrowHash", 0)) != 0:
        values["kytSignedMessageDataEscrowHash"] = main_result["ciphertext_hash"]
    return {"fresh_recipient_keys": list(recipient_fields.values()),
            "fresh_ephemeral_domains": [f"escrow-{domain}-ephemeral-random" for domain in prefixes],
            "plaintext_sizes": {"data": 5, "dao": 1, "zone": 1},
            "encryption": "ECDH on BabyJub Base8; C[i]=(M[i]+Poseidon(kSeed,i)) mod FIELD",
            "hmac": "Poseidon(kMac,Poseidon(kMac,C...)); kMac=Poseidon(kSeed,len(C))",
            "synthetic_test_keys_only": True,
            "kyc_kyt_signatures_generated": False}
