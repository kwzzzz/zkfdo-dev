#!/usr/bin/env python3
"""Construct synthetic QueryIdentity inputs for the recorded aq-025/026 sources.

Both revisions have the same QueryIdentity, DG1 extraction, identity-state and
sparse-Merkle formulas. No passport, private key, candidate or J data is read.
Only synthetic MRZ text, a newly derived public-seed test identity scalar, and
the installed public circomlibjs implementation are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a-remeasure-2026-10-25.noindex"
MANIFEST = ROOT / "runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json"
MANIFEST_SHA = "f059fe7d6aa21234168b7867537f069ec980c45c2c025184cbc12e169f687441"
COMMITS = {
    "aq-025-70328d3fd35e": "bbbe14c71c08be20a55f29bb2159261f0b32be0f",
    "aq-026-2bcd7ed6110f": "9143bc77eb2bdbd174eaa61b25b11adb5ee99f61",
}
SEED = "20261025-a-remeasure-query-identity-synthetic-v1"
SOURCE_PATHS = (
    "circuits/identityManagement/queryIdentity.circom",
    "circuits/identityManagement/circuits/queryIdentity.circom",
    "circuits/identityManagement/circuits/dg1DataExtractor.circom",
    "circuits/identityManagement/circuits/identityStateVerifier.circom",
    "circuits/identityManagement/circuits/citizenshipCheck.circom",
    "circuits/merkleTree/SMTVerifier.circom",
    "circuits/dateUtilities/dateComparisonEncoded.circom",
    "circuits/dateUtilities/dateComparisonEncodedNormalized.circom",
    "circuits/dateUtilities/dateDecoder.circom",
    "circuits/dateUtilities/dateEncoder.circom",
    "circuits/dateUtilities/dateComparison.circom",
    "package.json",
)

JS = r"""
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const p = JSON.parse(fs.readFileSync(0, 'utf8'));
  const lib = require(path.join(p.project, 'node_modules/circomlibjs/build/main.cjs'));
  const poseidon = await lib.buildPoseidonReference();
  const babyjub = await lib.buildBabyjub();
  const hash = xs => poseidon.F.toObject(poseidon(xs.map(BigInt)));
  const sk = BigInt(p.input.skIdentity);
  const pk = babyjub.mulPointEscalar(babyjub.Base8, sk);
  if (!babyjub.inCurve(pk) || !babyjub.inSubgroup(pk)) throw new Error('test identity point invalid');
  const pkHash = hash(pk.map(x => babyjub.F.toObject(x)));
  const treeKey = hash([p.input.pkPassportHash, pkHash]);
  // QueryIdentity feeds each ordered 186-bit DG1 slice straight into Bits2Num.
  const chunks = [];
  for (let i = 0; i < 4; ++i) {
    let chunk = 0n;
    for (let j = 0; j < 186; ++j) chunk += BigInt(p.input.dg1[186*i+j]) << BigInt(j);
    chunks.push(chunk);
  }
  const dgCommit = hash([...chunks, hash([sk])]);
  const treeValue = hash([dgCommit, p.input.identityCounter, p.input.timestamp]);
  // With every sibling zero, SMTLevIns selects level zero: one-leaf SMT root.
  p.input.idStateRoot = hash([treeKey, treeValue, 1n]).toString();
  process.stdout.write(JSON.stringify({input:p.input,
    loaded_modules:Object.keys(require.cache).sort(),
    formula_checks:{identity_point_on_curve:true, identity_point_in_subgroup:true,
      dg1_bits:p.input.dg1.length, merkle_siblings:p.input.idStateSiblings.length}}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def derive(seed: str, label: str, count: int) -> bytes:
    return hashlib.shake_256(f"{seed}:{label}".encode()).digest(count)


def mrz_check(text: str) -> str:
    def value(char: str) -> int:
        return 0 if char == "<" else int(char) if char.isdigit() else ord(char) - ord("A") + 10
    return str(sum(value(char) * (7, 3, 1)[i % 3] for i, char in enumerate(text)) % 10)


def synthetic_dg1() -> bytes:
    line1 = "P<USA" + "EXAMPLE<<SYNTHETIC<TEST".ljust(39, "<")
    document, birth, expiration, optional = "TST000001", "900101", "350101", "<" * 14
    line2 = (document + mrz_check(document) + "USA" + birth + mrz_check(birth) + "F" +
             expiration + mrz_check(expiration) + optional + mrz_check(optional))
    line2 += mrz_check(line2[:10] + line2[13:20] + line2[21:43])
    if len(line1) != 44 or len(line2) != 44:
        raise RuntimeError("synthetic TD3 MRZ length invalid")
    result = bytes.fromhex("615b5f1f58") + (line1 + line2).encode("ascii")
    if len(result) != 93 or result[62:68] != birth.encode() or result[70:76] != expiration.encode():
        raise RuntimeError("synthetic DG1 date offsets differ from recorded extractor")
    return result


def encoded_date(text: str) -> str:
    if len(text) != 6 or not text.isascii() or not text.isdigit():
        raise RuntimeError("date must be six ASCII digits")
    return str(int.from_bytes(text.encode("ascii"), "big"))


def audit_sources(revision: str, project: Path) -> list[dict]:
    if sha256(MANIFEST) != MANIFEST_SHA:
        raise RuntimeError("recorded A revision manifest changed")
    rows = json.loads(MANIFEST.read_text())["rows"]
    rows = [row for row in rows if row.get("identifier") == revision]
    if len(rows) != 1 or rows[0].get("revision_commit") != COMMITS[revision] or \
            Path(rows[0]["project_root"]) != project or Path(rows[0]["git_repository_path"]) != project:
        raise RuntimeError("recorded source commit/project binding differs")
    sources = []
    for relative in SOURCE_PATHS:
        path = project / relative
        committed = subprocess.run(["git", "-C", str(project), "show", f"{COMMITS[revision]}:{relative}"],
                                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        current_sha = sha256(path)
        if hashlib.sha256(committed.stdout).hexdigest() != current_sha:
            raise RuntimeError(f"unit source differs from recorded commit: {relative}")
        sources.append({"path": str(path.relative_to(ROOT)), "sha256": current_sha,
                        "recorded_commit_equal": True})
    return sources


def dependency_records(project: Path, loaded: list[str]) -> dict:
    modules, packages = [], {}
    for name in loaded:
        path = Path(name)
        if not path.is_file() or "node_modules" not in path.parts:
            raise RuntimeError("unexpected non-library Node module loaded")
        modules.append({"path": str(path), "sha256": sha256(path)})
        folder = path.parent
        while folder != folder.parent and "node_modules" in folder.parts:
            manifest = folder / "package.json"
            if manifest.is_file():
                metadata = json.loads(manifest.read_text())
                if metadata.get("name") and metadata.get("version"):
                    packages[str(manifest)] = {"path": str(manifest), "sha256": sha256(manifest),
                                               "name": metadata["name"], "version": metadata["version"]}
                    break
            folder = folder.parent
    locks = []
    for filename in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml"):
        path = project / filename
        if path.is_file():
            locks.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(path)})
    return {"loaded_modules": modules, "packages": [packages[k] for k in sorted(packages)],
            "installed_lockfiles": locks}


def construct(revision: str) -> tuple[dict, dict]:
    project = ROOT / "runs/n6-a1b-2026-10-08/units" / revision / "project"
    sources = audit_sources(revision, project)
    seed = f"{SEED}:{revision}"
    field = lambda label: str(1 + int.from_bytes(derive(seed, label, 31), "big"))
    dg1 = synthetic_dg1()
    value = {
        "dg1": [str((byte >> shift) & 1) for byte in dg1 for shift in range(7, -1, -1)],
        "skIdentity": field("fresh-test-identity-scalar"),
        "pkPassportHash": field("synthetic-passport-public-key-hash"),
        "eventID": field("synthetic-event-id"), "eventData": field("synthetic-event-data"),
        "selector": str((1 << 16) - 1), "currentDate": encoded_date("261025"),
        "timestamp": "1760000000", "timestampLowerbound": "1750000000", "timestampUpperbound": "1770000000",
        "identityCounter": "1", "identityCounterLowerbound": "0", "identityCounterUpperbound": "2",
        "birthDateLowerbound": encoded_date("800101"), "birthDateUpperbound": encoded_date("000101"),
        "expirationDateLowerbound": encoded_date("300101"), "expirationDateUpperbound": encoded_date("400101"),
        "citizenshipMask": "0", "idStateSiblings": ["0"] * 80,
    }
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("existing Node unavailable; no install attempted")
    call = subprocess.run([node, "--eval", JS], input=json.dumps({"project": str(project), "input": value}),
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=project,
                          env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": "/tmp"}, timeout=120)
    if call.returncode:
        raise RuntimeError(f"public library construction failed: {call.stderr[-3000:]}")
    result = json.loads(call.stdout)
    if audit_sources(revision, project) != sources:
        raise RuntimeError("recorded sources changed during construction")
    dependencies = dependency_records(project, result["loaded_modules"])
    return result["input"], {
        "schema": "n6-a-query-identity-construction-v1", "revision": revision, "seed": seed,
        "recorded_commit": COMMITS[revision], "manifest_sha256": MANIFEST_SHA, "sources": sources,
        "dependencies": dependencies, "node_path": str(Path(node).resolve()), "node_sha256": sha256(Path(node)),
        "construction": "Synthetic TD3 MRZ, seeded fresh test identity scalar, public circomlibjs BabyJub/Poseidon, one-leaf sparse Merkle tree",
        "shared_family_reason": "aq-025/026 QueryIdentity, DG1 extractor, identity verifier, SMT verifier and citizenship source bodies are identical",
        "synthetic_data_only": True, "existing_secrets_read": False, "signatures_required": False,
        "test_private_scalar_source": "public fixed seed; included only in ignored constructed input",
        "selector_semantics": "disclose fields and enable date/timestamp/counter comparisons (bits 0..15); empty citizenship blacklist",
        "dg1_bit_order": "MSB-first within bytes; each 186-bit Poseidon chunk uses Bits2Num little-endian interpretation",
        "merkle_formula": "Poseidon(Poseidon(pkPassportHash, Poseidon(BabyJub.Base8 * skIdentity)), Poseidon(dgCommit, identityCounter, timestamp), 1)",
        "formula_checks": result["formula_checks"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, choices=tuple(COMMITS))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output != RUN / "inputs" / args.revision / "input.json" or args.output.is_symlink():
        raise SystemExit("output must be the canonical revision input.json in this A run")
    provenance_path = output.with_suffix(".provenance.json")
    if output.exists() or provenance_path.exists():
        raise SystemExit("refusing to overwrite input or provenance")
    started = time.monotonic()
    value, provenance = construct(args.revision)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    provenance.update({"input_path": str(output), "input_sha256": sha256(output),
                       "generator_path": str(Path(__file__).resolve().relative_to(ROOT)),
                       "generator_sha256": sha256(Path(__file__)),
                       "construction_wall_seconds": time.monotonic() - started})
    with provenance_path.open("x") as stream:
        json.dump(provenance, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"revision": args.revision, "input_sha256": provenance["input_sha256"],
                      "construction_wall_seconds": provenance["construction_wall_seconds"]}))


if __name__ == "__main__":
    main()
