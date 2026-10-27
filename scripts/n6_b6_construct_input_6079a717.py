#!/usr/bin/env python3
# Model a test Aadhaar QR document signed by a new, seed-derived RSA test key.
# Reveal its normal identity fields and retain a nonempty signed QR payload.
"""Construct deterministic, synthetic Aadhaar QR verifier input."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QR_FIXTURE = (ROOT / "runs/e01-setup-2026-10-03/recovery-v2/repositories/"
              "anon-aadhaar__anon-aadhaar/clone/packages/circuits/assets/dataInput.json")
SHA256_DER = bytes.fromhex("3031300d060960864801650304020105000420")
SMALL_PRIMES = (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109)


def probable_prime(value: int) -> bool:
    if value < 2 or any(value % prime == 0 for prime in SMALL_PRIMES):
        return False
    odd = value - 1
    exponent = 0
    while odd % 2 == 0:
        odd //= 2
        exponent += 1
    for base in SMALL_PRIMES:
        power = pow(base, odd, value)
        if power in (1, value - 1):
            continue
        for _ in range(exponent - 1):
            power = (power * power) % value
            if power == value - 1:
                break
        else:
            return False
    return True


def prime_from_seed(seed: bytes, domain: bytes) -> int:
    for counter in range(100000):
        raw = hashlib.shake_256(seed + domain + counter.to_bytes(4, "big")).digest(128)
        candidate = int.from_bytes(raw, "big") | (1 << 1023) | 1
        if math.gcd(candidate - 1, 65537) == 1 and probable_prime(candidate):
            return candidate
    raise RuntimeError("seed-derived RSA prime search exhausted")


def words(number: int) -> list[str]:
    mask = (1 << 121) - 1
    return [str((number >> (121 * index)) & mask) for index in range(17)]


def signed_payload() -> bytes:
    fixture = json.loads(QR_FIXTURE.read_text())
    qr_number = int(fixture["testQRData"])
    compressed = qr_number.to_bytes((qr_number.bit_length() + 7) // 8, "big")
    decompressed = zlib.decompress(compressed)
    if len(decompressed) <= 256:
        raise ValueError("committed test QR data has no signed payload")
    return decompressed[:-256]


def construct(seed: str) -> dict:
    data = signed_payload()
    if not 0 < len(data) <= 1472:
        raise ValueError("signed QR payload does not fit circuit")
    delimiter_indices = [index for index, byte in enumerate(data) if byte == 255][:18]
    if len(delimiter_indices) != 18:
        raise ValueError("committed QR sample lacks eighteen field delimiters")

    seed_digest = hashlib.sha256(seed.encode("utf-8")).digest()
    p = prime_from_seed(seed_digest, b"rsa-p")
    q = prime_from_seed(seed_digest, b"rsa-q")
    if p == q:
        raise ValueError("seed-derived RSA primes collided")
    modulus = p * q
    private_exponent = pow(65537, -1, (p - 1) * (q - 1))
    digest = hashlib.sha256(data).digest()
    padding = b"\x00\x01" + b"\xff" * (256 - 3 - len(SHA256_DER) - len(digest))
    encoded = int.from_bytes(padding + b"\x00" + SHA256_DER + digest, "big")
    signature = pow(encoded, private_exponent, modulus)
    if pow(signature, 65537, modulus) != encoded:
        raise AssertionError("new test signature does not verify")

    bit_length = len(data) * 8
    padded = data + b"\x80"
    padded += b"\x00" * ((56 - len(padded) % 64) % 64)
    padded += bit_length.to_bytes(8, "big")
    padded_length = len(padded)
    padded += b"\x00" * (1536 - padded_length)
    if len(padded) != 1536:
        raise ValueError("QR SHA padding exceeds circuit maximum")
    return {
        "qrDataPadded": list(padded),
        "qrDataPaddedLength": padded_length,
        "delimiterIndices": delimiter_indices,
        "signature": words(signature),
        "pubKey": words(modulus),
        "nullifierSeed": 12345678,
        "signalHash": 1001,
        "revealAgeAbove18": 1,
        "revealGender": 1,
        "revealPinCode": 1,
        "revealState": 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="n6-b6-6079a717-2026-10-18")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = construct(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
