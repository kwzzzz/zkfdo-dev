#!/usr/bin/env python3
"""Construct fixed-seed synthetic JWT inputs using each recorded ZKsync library.

The three revisions are the same project, with versioned input names/nonce
encoding handled by their own lib/ implementation. RSA-2048 test keys are
generated anew in memory from the public seed; no existing key, JWT, candidate,
request, or judging output is read. These predictable keys are test-only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
REVISIONS = (
    "aq-006-1680f955c185",
    "aq-007-0bb83f9eab0f",
    "aq-008-9c9e702d061d",
)
SEED = "20261025-a-remeasure-zksync-synthetic-jwt-v1"

# Only the recorded project's lib/ is imported. In particular, tooling/cli.ts
# imports environment/network tooling and is deliberately not used.
JS = r"""
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
(async () => {
  const p = JSON.parse(fs.readFileSync(0, 'utf8'));
  const lib = await import(pathToFileURL(p.project + '/lib/index.ts').href);
  if (p.action === 'nonce') {
    process.stdout.write(JSON.stringify({nonce: lib.createNonce(p.content, BigInt(p.blinding))}));
  } else if (p.action === 'input') {
    const input = new lib.JwtTxValidationInputs(p.jwt, p.modulus, p.salt, p.content, BigInt(p.blinding));
    process.stdout.write(JSON.stringify(input.toObject()));
  } else {
    throw new Error('unknown operation');
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive(seed: str, label: str, count: int) -> bytes:
    return hashlib.shake_256(f"{seed}:{label}".encode()).digest(count)


def probable_prime(value: int) -> bool:
    """Trial division followed by 64 independently hash-derived MR rounds."""
    for divisor in range(3, 1000, 2):
        if value % divisor == 0:
            return False
    odd, power = value - 1, 0
    while odd % 2 == 0:
        odd //= 2
        power += 1
    encoded = value.to_bytes(128, "big")
    for round_index in range(64):
        material = hashlib.shake_256(encoded + round_index.to_bytes(4, "big")).digest(128)
        base = 2 + int.from_bytes(material, "big") % (value - 3)
        test = pow(base, odd, value)
        if test in (1, value - 1):
            continue
        for _ in range(power - 1):
            test = pow(test, 2, value)
            if test == value - 1:
                break
        else:
            return False
    return True


def test_prime(seed: str, label: str) -> int:
    # Both top bits are set so the product is always exactly 2048 bits.
    for counter in range(100000):
        value = int.from_bytes(derive(seed, f"rsa-{label}-{counter}", 128), "big")
        value |= (3 << 1022) | 1
        if math.gcd(value - 1, 65537) == 1 and probable_prime(value):
            return value
    raise RuntimeError("fixed RSA test-prime search exhausted")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def library_call(project: Path, arguments: dict[str, str]) -> dict:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("existing Node executable unavailable; no install attempted")
    loader = project / "node_modules/tsx/dist/loader.mjs"
    if not loader.is_file():
        raise RuntimeError("recorded project tsx unavailable; no install attempted")
    # Avoid inherited NODE_OPTIONS and project environment files. The imported
    # library does not load dotenv or perform requests.
    result = subprocess.run(
        [node, "--import", str(loader), "--eval", JS],
        input=json.dumps({"project": str(project), **arguments}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=project,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": "/tmp"},
        check=False,
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(f"recorded library failed: {result.stderr[-4000:]}")
    return json.loads(result.stdout)


def construct(revision: str, seed: str = SEED) -> tuple[dict, dict]:
    project = ROOT / "runs/n6-a1b-2026-10-08/units" / revision / "project"
    selected_seed = f"{seed}:{revision}"
    content = "0x" + derive(selected_seed, "synthetic-transaction-content-hash", 32).hex()
    salt = "0x" + derive(selected_seed, "salt", 16).hex()
    blinding = str(int.from_bytes(derive(selected_seed, "blinding", 16), "big"))
    common = {"content": content, "salt": salt, "blinding": blinding}
    nonce = library_call(project, {"action": "nonce", **common})["nonce"]
    header = {"alg": "RS256", "typ": "JWT", "kid": "public-synthetic-test-key"}
    payload = {
        "iss": "https://issuer.example",
        "aud": "synthetic-test-client",
        "sub": "synthetic-test-user",
        "nonce": nonce,
    }
    message = ".".join(
        b64url(json.dumps(item, separators=(",", ":")).encode("ascii"))
        for item in (header, payload)
    )
    first, second = test_prime(selected_seed, "p"), test_prime(selected_seed, "q")
    if first == second:
        raise RuntimeError("deterministic test primes unexpectedly equal")
    modulus = first * second
    private_exponent = pow(65537, -1, math.lcm(first - 1, second - 1))
    # EMSA-PKCS1-v1_5 encoding for SHA-256, matching RSAVerifier65537.
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420")
    digest_info += hashlib.sha256(message.encode("ascii")).digest()
    encoded = b"\x00\x01" + b"\xff" * (256 - len(digest_info) - 3) + b"\x00" + digest_info
    encoded_int = int.from_bytes(encoded, "big")
    signature = pow(encoded_int, private_exponent, modulus)
    if pow(signature, 65537, modulus) != encoded_int:
        raise RuntimeError("generated RSA signature failed the public verification equation")
    result = library_call(
        project,
        {
            "action": "input",
            **common,
            "jwt": message + "." + b64url(signature.to_bytes(256, "big")),
            "modulus": b64url(modulus.to_bytes(256, "big")),
        },
    )
    sources = [project / "jwt-tx-validation.circom", project / "package.json"]
    sources += sorted((project / "lib").glob("*.ts"))
    sources += sorted((project / "utils").glob("*.circom"))
    sources += [project / "node_modules/tsx/dist/loader.mjs"]
    provenance = {
        "revision": revision,
        "seed": selected_seed,
        "construction": "recorded lib.createNonce and lib.JwtTxValidationInputs; synthetic JWT; newly derived RSA-2048 test key",
        "rsa_public_exponent": 65537,
        "rsa_modulus_bits": modulus.bit_length(),
        "rsa_signature_equation_passed": True,
        "rsa_prime_validation": "trial division through 999; 64 SHAKE256-derived Miller-Rabin rounds",
        "private_key_persisted": False,
        "sources": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sources],
    }
    return result, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, choices=REVISIONS)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", default=SEED)
    args = parser.parse_args()
    provenance_path = args.output.with_suffix(".provenance.json")
    if args.output.exists() or provenance_path.exists():
        raise SystemExit("refusing to overwrite an input or provenance record")
    started = time.monotonic()
    result, provenance = construct(args.revision, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    provenance.update({
        "input_path": str(args.output.resolve()),
        "input_sha256": sha256(args.output),
        "generator_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "generator_sha256": sha256(Path(__file__)),
        "construction_wall_seconds": time.monotonic() - started,
    })
    with provenance_path.open("x") as stream:
        stream.write(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"input": str(args.output), "sha256": provenance["input_sha256"], "seconds": provenance["construction_wall_seconds"]}))


if __name__ == "__main__":
    main()
