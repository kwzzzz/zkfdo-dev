#!/usr/bin/env python3
"""Construct recorded A Panther scenarios with fresh deterministic test keys.

Renewal uses its committed active scenario; swap/transaction use their committed
zero-transaction scenarios with explicit branch-coverage limitations.
Only the recorded A unit's committed test scenario and source are read.
The existing arithmetic helper is imported without invoking its lock loader,
constructor or signature helper; no lock or B data is read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from n6_b6_construct_input_4c221df7 import (
    BASE8, FIELD, SUBORDER, decimal_strings, merkle_fold, note_commitment,
    parse_committed_scenario, poseidon, scalar_mul, seed_int, test_scalar,
)

ROOT = Path(__file__).resolve().parents[1]
REVISIONS = ("aq-011-93343c3cd34c", "aq-012-44d0df2ab46e", "aq-016-0a7d49b1c135", "aq-024-6f6781246415", "aq-017-9703bbce0c43")
SEED = "20261025-a-remeasure-panther-active-renewal-v1"
MANIFEST = ROOT / "runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_for(revision: str) -> Path:
    if revision not in REVISIONS:
        raise ValueError("unsupported A revision")
    return ROOT / "runs/n6-a1b-2026-10-08/units" / revision / "project"


def load_sources(revision: str) -> tuple[str, dict, dict]:
    project = project_for(revision)
    record = next(row for row in json.loads(MANIFEST.read_text())["rows"]
                  if row["identifier"] == revision)
    commit = record["revision_commit"]
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project,
                                   env=env, text=True).strip()
    if head != commit:
        raise ValueError("A source HEAD differs from recorded commit")
    if revision == "aq-011-93343c3cd34c":
        test_name = "ZAccountRenewalNonZeroInputWitnessGeneration.test.ts"
    elif revision == "aq-024-6f6781246415":
        test_name = "DepositOnlyZeroInputWitnessGeneration.test.ts"
    else:
        test_name = "ZSwapZeroInputWitnessGeneration.test.ts"
    test = project / "circuits/test" / test_name
    main = project / record["entrypoint_relative"]
    if sha256(main) != record["entrypoint_sha256"]:
        raise ValueError("A entrypoint differs from recorded SHA256")
    pending = [main]
    closure = set()
    while pending:
        path = pending.pop().resolve()
        if path in closure:
            continue
        closure.add(path)
        for include in re.findall(r'include\s+"([^"]+)"\s*;', path.read_text()):
            pending.append(path.parent / include)
    audited = closure | {test, project / "circuits/package.json"}
    if revision != REVISIONS[0]:
        audited.add(project / "crypto/src/panther/escrow.ts")
    files = sorted(audited)
    source_records = []
    for path in files:
        relative = path.relative_to(project).as_posix()
        entry = {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
        if "node_modules" not in path.parts:
            recorded = subprocess.check_output(["git", "show", f"{commit}:{relative}"],
                                               cwd=project, env=env)
            if path.read_bytes() != recorded:
                raise ValueError(f"source differs from recorded commit: {relative}")
            entry["matches_recorded_commit"] = True
        source_records.append(entry)
    package = project / "node_modules/circomlibjs"
    if json.loads((package / "package.json").read_text())["version"] != "0.0.8":
        raise ValueError("unexpected installed circomlibjs version")
    for relative in ["package.json", "src/poseidon_constants.json", "src/eddsa.js"]:
        path = package / relative
        source_records.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(path)})
    helper = ROOT / "scripts/n6_b6_construct_input_4c221df7.py"
    source_records.append({"path": str(helper.relative_to(ROOT)), "sha256": sha256(helper),
                           "use": "pure arithmetic/parser helpers only; no lock loader"})
    provenance = {"revision": revision, "recorded_commit": commit, "observed_head": head,
                  "manifest_sha256": sha256(MANIFEST), "sources": source_records,
                  "scenario": "active committed nonzero renewal with freshly derived test keys; all affected commitments, signatures and Merkle roots recomputed",
                  "kyc_hash": "recorded Poseidon(7): package,timestamp,sender,receiver,session,rule,signer",
                  "scope": "A input construction only; no candidates, request rows or J outputs"}
    return test.read_text(), json.loads((package / "src/poseidon_constants.json").read_text()), provenance


def new_kyc_signature(revision: str, seed: bytes, message_hash: int) -> tuple[list[int], list[int]]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("existing Node unavailable; no install attempted")
    package = project_for(revision) / "node_modules/circomlibjs"
    helper = (
        "const fs=require('node:fs');const p=JSON.parse(fs.readFileSync(0,'utf8'));"
        "const c=require(p.package);const sk=Buffer.from(p.seed,'hex');const m=BigInt(p.message);"
        "const pub=c.eddsa.prv2pub(sk);const sig=c.eddsa.signPoseidon(sk,m);"
        "if(!c.eddsa.verifyPoseidon(m,sig,pub))throw Error('fresh KYC signature invalid');"
        "process.stdout.write(JSON.stringify({pub:pub.map(x=>x.toString()),"
        "sig:[sig.S,sig.R8[0],sig.R8[1]].map(x=>x.toString())}));"
    )
    result = subprocess.run([node, "-e", helper],
        input=json.dumps({"package": str(package),
                          "seed": hashlib.sha256(seed + b":kyc-eddsa-seed").hexdigest(),
                          "message": str(message_hash)}),
        capture_output=True, text=True, timeout=30, check=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": "/tmp"})
    parsed = json.loads(result.stdout)
    return [int(item) for item in parsed["pub"]], [int(item) for item in parsed["sig"]]


def construct_renewal(revision: str, seed_text: str) -> tuple[dict, dict]:
    source, constants, provenance = load_sources(revision)
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

    signed_message = poseidon([
        values["kycSignedMessagePackageType"], values["kycSignedMessageTimestamp"],
        values["kycSignedMessageSender"], values["kycSignedMessageReceiver"],
        values["kycSignedMessageSessionId"], values["kycSignedMessageRuleId"],
        values["kycSignedMessageSigner"],
    ], constants)
    values["kycSignedMessageHash"] = signed_message
    kyc_public, kyc_signature = new_kyc_signature(revision, seed, signed_message)
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
    return {key: decimal_strings(value) for key, value in values.items()}, provenance


def construct_swap_zero(revision: str, seed_text: str) -> tuple[dict, dict]:
    """Use the recorded no-op transaction scenario, with freshly generated keys.

    Membership and KYT branches retain the zero fixture's disabled state; the
    unconditional account/key/escrow computations still use honest fresh values.
    This intentionally does not claim coverage of an active nonzero swap.
    """
    legacy_escrow = revision in ("aq-024-6f6781246415", "aq-017-9703bbce0c43")
    if legacy_escrow:
        from n6_a_panther_escrow_legacy import update_escrow_legacy as update_escrow
    else:
        from n6_a_panther_escrow import update_escrow

    source, constants, provenance = load_sources(revision)
    values = parse_committed_scenario(source.replace("const zeroInput = {", "const nonZeroInput = {"))
    # The committed fixture encodes its blacklist bitset as a decimal string.
    values["zZoneZAccountIDsBlackList"] = int(values["zZoneZAccountIDsBlackList"])
    seed = hashlib.sha256(seed_text.encode()).digest()
    root_private = test_scalar(seed, b"root-spend-key")
    root_public = scalar_mul(BASE8, root_private)
    read_private = test_scalar(seed, b"read-key")
    nullifier_private = test_scalar(seed, b"nullifier-key")
    values["zAccountUtxoInRootSpendPubKey"] = list(root_public)
    values["zAccountUtxoInReadPrivKey"] = read_private
    values["zAccountUtxoInReadPubKey"] = list(scalar_mul(BASE8, read_private))
    values["zAccountUtxoInNullifierPrivKey"] = nullifier_private
    values["zAccountUtxoInNullifierPubKey"] = list(scalar_mul(BASE8, nullifier_private))
    values["zAccountUtxoInSpendPrivKey"] = (root_private * test_scalar(seed, b"account-input-random")) % SUBORDER
    if legacy_escrow:
        # This recorded version enables the input-account nullifier check with
        # the spend scalar, so preserve the fixture's absent-account sentinel.
        values["zAccountUtxoInSpendPrivKey"] = 0
    values["zAccountUtxoInMasterEOA"] = 1 + seed_int(seed, b"master-eoa", (1 << 160) - 1)
    values["utxoInSpendKeyRandom"] = [test_scalar(seed, f"utxo-input-random-{i}".encode()) for i in range(2)]
    values["utxoInSpendPrivKey"] = [(root_private * random) % SUBORDER for random in values["utxoInSpendKeyRandom"]]
    values["utxoOutRootSpendPubKey"] = [list(root_public), list(root_public)]
    values["utxoOutSpendPubKeyRandom"] = [test_scalar(seed, f"utxo-output-random-{i}".encode()) for i in range(2)]
    values["zAccountUtxoOutSpendKeyRandom"] = test_scalar(seed, b"account-output-random")
    values["kytEdDsaPubKey"] = list(scalar_mul(BASE8, test_scalar(seed, b"inactive-kyt-key")))
    escrow = update_escrow(values, constants, seed)
    values["zAccountUtxoOutCommitment"] = note_commitment(
        values, scalar_mul(root_public, values["zAccountUtxoOutSpendKeyRandom"]),
        values["zAccountUtxoOutZkpAmount"], values["zAccountUtxoInExpiryTime"],
        values["zAccountUtxoInNonce"] + 1, values["utxoOutCreateTime"], constants)
    values["salt"] = 1 + seed_int(seed, b"salt", FIELD - 1)
    values["saltHash"] = poseidon([values["salt"]], constants)
    values["extraInputsHash"] = 1 + seed_int(seed, b"extra-input-anchor", FIELD - 1)
    provenance.update({
        "scenario": f"recorded zero-transaction {'ZTransaction' if revision == 'aq-024-6f6781246415' else 'ZSwap'} fixture with fresh deterministic account, UTXO and escrow test keys",
        "limitation": "zero amounts; original zero membership roots and inactive KYT signatures/hashes retained; no active nonzero-transaction coverage claimed",
        "kyc_hash": "not applicable; KYT signatures inactive in committed zero fixture",
        "escrow": escrow,
    })
    if legacy_escrow:
        provenance["absent_input_account"] = "recorded zero spend-key sentinel retained; all required output/account read/nullifier/UTXO/escrow test keys are freshly derived"
    helper = ROOT / ("scripts/n6_a_panther_escrow_legacy.py" if legacy_escrow else "scripts/n6_a_panther_escrow.py")
    provenance["sources"].append({"path": str(helper.relative_to(ROOT)), "sha256": sha256(helper)})
    return {key: decimal_strings(value) for key, value in values.items()}, provenance


def construct(revision: str, seed_text: str) -> tuple[dict, dict]:
    if revision == "aq-011-93343c3cd34c":
        return construct_renewal(revision, seed_text)
    return construct_swap_zero(revision, seed_text)



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, choices=REVISIONS)
    parser.add_argument("--seed", default=SEED)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sidecar = args.output.with_suffix(".provenance.json")
    if args.output.exists() or sidecar.exists():
        raise SystemExit("refusing to overwrite input or provenance")
    started = time.monotonic()
    seed = f"{args.seed}:{args.revision}"
    result, provenance = construct(args.revision, seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        out.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    provenance.update({"seed": seed, "input_sha256": sha256(args.output),
                       "generator_sha256": sha256(Path(__file__)),
                       "construction_wall_seconds": time.monotonic() - started})
    with sidecar.open("x") as out:
        out.write(json.dumps(provenance, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"revision": args.revision, "input": str(args.output),
                      "sha256": provenance["input_sha256"],
                      "seconds": provenance["construction_wall_seconds"]}))


if __name__ == "__main__":
    main()
