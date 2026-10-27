#!/usr/bin/env python3
"""Construct a deterministic fresh RSA-PSS/SHA-256 signature input."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


SMALL_PRIMES = (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109)
EXPONENT = 3
CHUNK_BITS = 64
CHUNKS = 32
EM_LEN = 256


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
            power = power * power % value
            if power == value - 1:
                break
        else:
            return False
    return True


def prime_from_seed(seed: bytes, domain: bytes) -> int:
    for counter in range(100000):
        raw = hashlib.shake_256(seed + domain + counter.to_bytes(4, "big")).digest(128)
        candidate = int.from_bytes(raw, "big") | (1 << 1023) | 1
        if math.gcd(candidate - 1, EXPONENT) == 1 and probable_prime(candidate):
            return candidate
    raise RuntimeError("seed-derived RSA prime search exhausted")


def mgf1(seed: bytes, count: int) -> bytes:
    result = bytearray()
    for counter in range((count + 31) // 32):
        result.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
    return bytes(result[:count])


def pss_encode(message_hash: bytes, salt: bytes) -> bytes:
    if len(message_hash) != 32 or len(salt) != 32:
        raise ValueError("RSA-PSS digest and salt must be 32 bytes")
    hashed = hashlib.sha256(b"\x00" * 8 + message_hash + salt).digest()
    padding = b"\x00" * (EM_LEN - 32 - 32 - 2)
    data_block = padding + b"\x01" + salt
    masked = bytes(a ^ b for a, b in zip(data_block, mgf1(hashed, len(data_block))))
    masked = bytes([masked[0] & 0x7f]) + masked[1:]
    encoded = masked + hashed + b"\xbc"
    if len(encoded) != EM_LEN:
        raise AssertionError("PSS encoded message length changed")
    return encoded


def words(value: int) -> list[str]:
    return [str((value >> (CHUNK_BITS * index)) & ((1 << CHUNK_BITS) - 1))
            for index in range(CHUNKS)]


def bits_msb(data: bytes) -> list[int]:
    return [(byte >> (7 - offset)) & 1 for byte in data for offset in range(8)]


def construct(seed_text: str) -> dict:
    seed = hashlib.sha256(seed_text.encode()).digest()
    first = prime_from_seed(seed, b"rsa-pss-p")
    second = prime_from_seed(seed, b"rsa-pss-q")
    if first == second:
        raise ValueError("seed-derived primes collided")
    modulus = first * second
    if modulus.bit_length() != CHUNK_BITS * CHUNKS:
        raise ValueError("seed-derived modulus must be exactly 2048 bits")
    private_exponent = pow(EXPONENT, -1, (first - 1) * (second - 1))
    message = hashlib.sha256(seed + b":passport-synthetic-message").digest()
    message_hash = hashlib.sha256(message).digest()
    salt = hashlib.sha256(seed + b":rsa-pss-salt").digest()
    encoded = int.from_bytes(pss_encode(message_hash, salt), "big")
    signature = pow(encoded, private_exponent, modulus)
    if pow(signature, EXPONENT, modulus) != encoded:
        raise AssertionError("fresh RSA-PSS signature does not verify")
    return {
        "pubkey": words(modulus),
        "signature": words(signature),
        "hashed": bits_msb(message_hash),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="n6-b6-a8b2aa9c-2026-10-18")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = construct(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        out.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
