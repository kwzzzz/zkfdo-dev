#!/usr/bin/env python3
"""S-05 preparation, run before the SCOPE is fixed. Value-free with respect to the candidate.

The candidate file is hashed and sized but never parsed. This step re-checks the selection
from the raw A-02 ledger, pins the inputs, verifies fix provenance, compiles the component,
the actual fix and the production entrypoint, enumerates every Subtract instance of the
entrypoint, and validates one fixed benign entrypoint input. Outputs stay under the ignored
run directory; stdout carries only statuses, counts and hashes.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
OUT = ROOT / "runs/n4-1-a02-first-semantic-review-2026-10-02/prep-v1"
CAMPAIGN = ROOT / "runs/n4-1-policy-a-engine-2026-10-02/small-first-campaign-v1"
CANDIDATE_REL = ("attempts/000001/candidates/zkfdo-targets/"
                 "src__subtractTensor__Subtract.circom_CGijXpcMP3_counterexample.json")
CANDIDATE_SHA, CANDIDATE_SIZE = "dae6e8b397f2b25269f9711443449b73ba6ba86f4ca7a4397cf318fbfc143258", 2107
TARGET_ID = "sha256:1830b5991e7c31effb5249dccfc0f125fa1e5cc8099cfcdb5dc7d0e9bde75cb3"
FIRST_OFFSET, FIRST_COMPLETION = 1.108243333, 1.117240042
TREE = ROOT / "runs/dev-rq1-pilot-2026-09-29/inference-main/tree"
CLONE = ROOT / "runs/dev-projects/inference"
VULN_COMMIT = "d310309c141d36504b3486cebd96ed70ef3a4fdf"
FIX_COMMIT = "b8f92bdec1694138df0e069921f1aa0bdc94053e"
PINNED = {
    "docs/next_s03_context_handoff_2026-10-02.md": "fc1b5590b86d8ca6dced195f4084313b9193a73a754879fa91d3eef8af7568e5",
    "reports/n4-1-a02-first-occurrence-metadata-2026-10-02/SCOPE.md":
        "4b74d66e02716f412b2718dafbe757cee5e8612b9722a45da406c914a4915845",
    "reports/n4-1-a02-first-occurrence-metadata-2026-10-02/REPORT.md":
        "7587965225ffbc7e5d8d3dd363f49e8aec71a53a295fee4a81ffc33244ebf6c5",
    "reports/n4-1-a02-first-occurrence-metadata-2026-10-02/occurrence-inventory-v1.json":
        "344585cd7270db2dec889222eac323d5362088408d70d2d5ce22e23fd0ab48cc",
    "reports/n4-1-a02-first-occurrence-metadata-2026-10-02/evidence.json":
        "3c6cc8aca481f939b0d18c7b33639012a28495d92727975b1fea905cb25afb7e",
    "reports/n4-1-a02-first-occurrence-metadata-2026-10-02/INVENTORY.md":
        "dd222bda6b67d772cdeefb3cd17b43fd33cadeff8af7ffbdc8909616f565c47d",
    "reports/n4-1-a02-intdiv-review-2026-10-02/SCOPE.md":
        "e122217998acfcd12fb007ed7022825068b7110bdc1b4cffa1f9c6feed39ffa7",
    "reports/n4-1-a02-intdiv-review-2026-10-02/REPORT.md":
        "4d257fe5c07f1f9a99f31541214ad7fa83a3b0da675f40959b308040167ec422",
    "reports/n4-1-policy-a-engine-2026-10-02/SCOPE.md":
        "6908aeb42a746ecbc1d55d0d84e5339ee5ea52ceb09000532fef78d34c4b02fa",
    "reports/n4-1-policy-a-engine-2026-10-02/REPORT.md":
        "0c345ffaca10aed7345b978745b3e93a582cb191da57445b4cb40462b2d270a7",
    "reports/n4-1-policy-a-engine-2026-10-02/evidence-v2.json":
        "41855eae4d04b3426dd71ceff960fe7d925202d56180170a8681d0c85cfacb8e",
    "reports/n4-1-policy-a-engine-2026-10-02/small-first-spec-v1.json":
        "bc9e8f58ce99f44b13faf27fd339490b75d6e823bb5afa06b04cddaf56f709e6",
    "reports/n4-1-policy-a-engine-2026-10-02/whole-spec-v1.json":
        "62c68534d7987c5b284577b9aaf626004bd6659c2aff3a21cc974f2419b11314",
    "reports/n4-1-policy-a-engine-2026-10-02/source-manifest-v1.txt":
        "69574bb41330e20ce1716fb0203688ef965e5dd985f171409d0dc630ca0075e9",
    "scripts/run_policy_a_engine.py": "c408ccbad8cc0847bc471b7b38cde0c21d81071157c50b95ab943b16055f874d",
    "runs/n4-1-policy-a-engine-2026-10-02/small-first-campaign-v1/ledger.json":
        "8912e24976bc7d7dc414a7eddcda67007fa5aeffff989babf017d09fa0bbcb8e",
    "runs/n4-1-policy-a-engine-2026-10-02/small-first-preflight-v1/preflight.json":
        "284ff020e843e183c886131b92fd2b7c39795b2c7708538e5b4e088f03bc442e",
    "runs/n4-1-policy-a-engine-2026-10-02/whole-preflight-v1/preflight.json":
        "fd2d5698e27e82a01ab8213f3f502755df65b3b9f8f026978ab9123e0e6031a9",
    "runs/n4-1-policy-a-engine-2026-10-02/small-first-preflight-v1/compile/0001/artifacts/src__subtractTensor__Subtract.r1cs":
        "14c18b08f5697b259526002cb217552c0a08ddc236fdb357bee2f40409cfb04f",
    "runs/n4-1-policy-a-engine-2026-10-02/whole-preflight-v1/compile/0000/artifacts/circuit.r1cs":
        "39022971e46a6ea30c548f9c7a0b4f0298a71b1c1f798c19304d9b9e61917220",
    "reports/n4-1-p2-candidate-review-2026-10-02/SCOPE.md":
        "24cec8f8fbdb8747cbf68d42722994890ec2a8ef019ada4d851627c2fde7da76",
    "reports/n4-1-p2-candidate-review-2026-10-02/REPORT.md":
        "8a0110f1c419b07b0a114062bea20ce054f62329c979ef02f8fcb08bd6a3543e",
}
MANIFEST = "reports/n4-1-policy-a-engine-2026-10-02/source-manifest-v1.txt"
VULN_FILES = ["src/subtractTensor.circom", "src/circuit.circom", "src/responseTimeNormalized.circom",
              "src/responseTimeMetric.circom"]
LIBRARIES = [ROOT / ".external/zkbugs/dataset/circom/dependencies",
             ROOT / ".external/zkbugs/dataset/circom/dependencies/circomlib"]
TOOLS = {"circom": (Path("/Users/miiz/.cargo/bin/circom"),
                    "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"),
         "node": (Path("/opt/homebrew/Cellar/node/26.0.0/bin/node"),
                  "08dad0581f00a0cabf4d49ec92ca1f25fdfd01c2c18fa8e92b35f04d4c24c164"),
         "snarkjs": (Path("/opt/homebrew/lib/node_modules/snarkjs/build/cli.cjs"),
                     "6d787e37a4d1a2c6dd6032dadca09c0b3b007d4d4578bb6232a98136555d051a")}
SUBTRACT_R1CS = "14c18b08f5697b259526002cb217552c0a08ddc236fdb357bee2f40409cfb04f"
ENTRY_R1CS = "39022971e46a6ea30c548f9c7a0b4f0298a71b1c1f798c19304d9b9e61917220"
S01_FIX_SOURCE, S01_FIX_R1CS = ("c5d6aa9de7e95f09283e6b014dcbda85e16e583c3e157d7f8fdd95bb001023ba",
                                "842a28ea3c545079f8802e5593bc4d13de4e19f0f453ed432ed77929d9240ac8")
CLASSES = {
    "K1": r"main\.response_time_normalized_fn\[(\d+)\]\.subtract1",
    "K2": r"main\.response_time_normalized_fn\[(\d+)\]\.subtract2",
    "K3": r"main\.response_time_reward_metric_fn\[(\d+)\]\.scoring_function\.temp_sub\[0\]",
    "K4": r"main\.response_time_reward_metric_fn\[(\d+)\]\.scoring_function\.temp_sub\[1\]",
    "K5": r"main\.response_time_reward_metric_fn\[(\d+)\]\.subtract",
}
BATCH = 256


class Stop(Exception):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned(path, expected):
    if not Path(path).is_file() or sha(path) != expected:
        raise Stop(f"hash mismatch or missing: {Path(path).name}")
    return Path(path)


LEDGER = []


def run(stage, args, cwd, timeout=60):
    started = time.perf_counter()
    index = len(LEDGER)
    stdout, stderr = OUT / f"logs/{index:02d}-{stage}.stdout", OUT / f"logs/{index:02d}-{stage}.stderr"
    try:
        process = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
        code, out, err, timed_out = process.returncode, process.stdout, process.stderr, False
    except subprocess.TimeoutExpired as error:
        code, out, err, timed_out = None, error.stdout or "", error.stderr or "", True
    out = out if isinstance(out, str) else out.decode()
    err = err if isinstance(err, str) else err.decode()
    stdout.write_text(out)
    stderr.write_text(err)
    LEDGER.append({"index": index, "stage": stage, "args": [str(a) for a in args], "exit_code": code,
                   "timed_out": timed_out, "timeout_seconds": timeout, "wall_seconds": time.perf_counter() - started,
                   "stdout": {"path": str(stdout.relative_to(ROOT)), "sha256": sha(stdout)},
                   "stderr": {"path": str(stderr.relative_to(ROOT)), "sha256": sha(stderr)}})
    return code, out, err, timed_out


def git_object(kind, oid):
    data = subprocess.run(["git", "-C", str(CLONE), "cat-file", kind, oid], capture_output=True, check=True).stdout
    if hashlib.sha1(f"{kind} {len(data)}\0".encode() + data).hexdigest() != oid:
        raise Stop("git object hash mismatch")
    return data


def tree_entry(data, name):
    i = 0
    while i < len(data):
        space = data.index(b" ", i)
        nul = data.index(b"\0", space)
        if data[space + 1:nul].decode() == name:
            return data[nul + 1:nul + 21].hex()
        i = nul + 21
    raise Stop(f"tree entry {name} missing")


def blob_at(commit, relative):
    """Walk commit -> tree -> ... -> blob, recomputing every object id."""
    tree = git_object("commit", commit).split(b"\n", 1)[0].split()[1].decode()
    parts = relative.split("/")
    for part in parts[:-1]:
        tree = tree_entry(git_object("tree", tree), part)
    blob = tree_entry(git_object("tree", tree), parts[-1])
    return blob, git_object("blob", blob)


def r1cs_shape(path):
    data = Path(path).read_bytes()
    _, sections = struct.unpack_from("<II", data, 4)
    offset = 12
    for _ in range(sections):
        kind, size = struct.unpack_from("<IQ", data, offset)
        offset += 12
        if kind == 1:
            header = data[offset:offset + size]
        offset += size
    n8 = struct.unpack_from("<I", header, 0)[0]
    wires, outputs, pub_in, prv_in = struct.unpack_from("<IIII", header, 4 + n8)
    count = struct.unpack_from("<I", header, 4 + n8 + 24)[0]
    return {"wires": wires, "outputs": outputs, "public_inputs": pub_in, "private_inputs": prv_in,
            "constraints": count}


def read_wtns(path):
    data = Path(path).read_bytes()
    if data[:4] != b"wtns":
        raise Stop("not a wtns file")
    _, sections = struct.unpack_from("<II", data, 4)
    offset, header, body = 12, None, None
    for _ in range(sections):
        kind, size = struct.unpack_from("<IQ", data, offset)
        offset += 12
        if kind == 1:
            header = data[offset:offset + size]
        elif kind == 2:
            body = data[offset:offset + size]
        offset += size
    n8 = struct.unpack_from("<I", header, 0)[0]
    if int.from_bytes(header[4:4 + n8], "little") != PRIME:
        raise Stop("unexpected wtns prime")
    count = struct.unpack_from("<I", header, 4 + n8)[0]
    return [int.from_bytes(body[i * n8:(i + 1) * n8], "little") for i in range(count)]


def count_unsatisfied(r1cs_path, witness):
    """Stream the R1CS constraints and count those with (A.w)(B.w) != C.w mod p."""
    data = Path(r1cs_path).read_bytes()
    _, sections = struct.unpack_from("<II", data, 4)
    offset, header, body = 12, None, None
    for _ in range(sections):
        kind, size = struct.unpack_from("<IQ", data, offset)
        offset += 12
        if kind == 1:
            header = (offset, size)
        elif kind == 2:
            body = (offset, size)
        offset += size
    h = header[0]
    n8 = struct.unpack_from("<I", data, h)[0]
    if int.from_bytes(data[h + 4:h + 4 + n8], "little") != PRIME:
        raise Stop("unexpected R1CS prime")
    wires = struct.unpack_from("<I", data, h + 4 + n8)[0]
    count = struct.unpack_from("<I", data, h + 4 + n8 + 24)[0]
    if len(witness) != wires:
        raise Stop("witness length differs from R1CS wires")
    pos, bad = body[0], 0
    for _ in range(count):
        values = []
        for _ in range(3):
            terms = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            total = 0
            for _ in range(terms):
                wire = struct.unpack_from("<I", data, pos)[0]
                total += int.from_bytes(data[pos + 4:pos + 4 + n8], "little") * witness[wire]
                pos += 4 + n8
            values.append(total % PRIME)
        if values[0] * values[1] % PRIME != values[2]:
            bad += 1
    if pos != body[0] + body[1]:
        raise Stop("R1CS constraint section not fully consumed")
    return bad


def read_sym(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        _, wire, _, name = line.split(",", 3)
        if name in result:
            raise Stop("duplicate symbol name")
        result[name] = int(wire)
    return result


def snark_verdict(r1cs_path, wtns_path, stage, cwd, timeout=60):
    code, out, err, timed_out = run(stage, [TOOLS["node"][0], TOOLS["snarkjs"][0], "wtns", "check",
                                            r1cs_path, wtns_path], cwd, timeout)
    text = out + err
    if not timed_out and code == 0 and "WITNESS IS CORRECT" in text and "WITNESS IS NOT CORRECT" not in text:
        return "correct"
    if not timed_out and "WITNESS IS NOT CORRECT" in text:
        return "not_correct"
    return "error"


def compile_circuit(source, folder, stage, project, timeout=60):
    folder.mkdir(parents=True)
    args = [TOOLS["circom"][0], source, "--r1cs", "--prime", "bn128", "--output", folder, "-l", project]
    for library in LIBRARIES:
        args += ["-l", library]
    code, _, _, timed_out = run(stage, args + ["--sym", "--wasm"], source.parent, timeout)
    if code != 0 or timed_out:
        raise Stop(f"{stage} failed")
    stem = source.stem
    return {"r1cs": folder / f"{stem}.r1cs", "sym": folder / f"{stem}.sym",
            "wasm": folder / f"{stem}_js/{stem}.wasm", "generator": folder / f"{stem}_js/generate_witness.js"}


def selection_check():
    """Recompute the first parent NOT SAFE occurrence from the raw ledger; the candidate is only hashed."""
    ledger = json.loads((CAMPAIGN / "ledger.json").read_text())
    occurrences = []
    for attempt in ledger["attempts"]:
        offsets = [o["campaign_offset_seconds"] for o in attempt.get("log_observations", []) if o["kind"] == "not_safe"]
        for candidate in attempt.get("candidates", []):
            occurrences.append((min(offsets) if offsets else float("inf"), attempt["attempt_index"],
                                candidate["path"], candidate["sha256"], attempt))
    occurrences.sort(key=lambda o: o[:3])
    first, second = occurrences[0], occurrences[1]
    attempt = first[4]
    zero = ledger["attempts"][0]
    path = CAMPAIGN / CANDIDATE_REL
    workspace_copy = CAMPAIGN / "attempts/000001/workspace" / attempt["candidates"][0]["source_workspace_path"]
    inventory = json.loads((ROOT / "reports/n4-1-a02-first-occurrence-metadata-2026-10-02/"
                                   "occurrence-inventory-v1.json").read_text())
    row = inventory["occurrences"][0]
    checks = {
        "attempts": len(ledger["attempts"]),
        "occurrences": len(occurrences),
        "missing_parent_observations": sum(1 for o in occurrences if o[0] == float("inf")),
        "first_attempt": first[1], "second_attempt": second[1],
        "ties_at_first_offset": sum(1 for o in occurrences if o[0] == first[0]),
        "first_offset_matches": first[0] == FIRST_OFFSET,
        "first_completion_matches": attempt["completion_offset_seconds"] == FIRST_COMPLETION,
        "first_path_matches": first[2] == CANDIDATE_REL,
        "first_recorded_sha_matches": first[3] == CANDIDATE_SHA,
        "first_target_matches": attempt["target_id"] == TARGET_ID,
        "candidate_file_sha_matches": sha(path) == CANDIDATE_SHA,
        "candidate_file_size_matches": path.stat().st_size == CANDIDATE_SIZE,
        "workspace_copy_sha_matches": workspace_copy.is_file() and sha(workspace_copy) == CANDIDATE_SHA,
        "result_sha_matches": sha(CAMPAIGN / attempt["result"]["path"]) == attempt["result"]["sha256"],
        "attempt_zero_no_candidate": (zero["outcome"] == "no_candidate" and not zero["candidates"]
                                      and not any(o["kind"] == "not_safe" for o in zero["log_observations"])),
        "inventory_first_row_matches": (row["observed_order"] == 1 and row["attempt_index"] == 1
                                        and row["recorded_sha256"] == CANDIDATE_SHA
                                        and row["parent_log_observation_offset_seconds"] == FIRST_OFFSET
                                        and row["attempt_completion_offset_seconds"] == FIRST_COMPLETION),
    }
    timing = {key: attempt[key] for key in ("dispatch_offset_seconds", "process_start_offset_seconds",
                                            "process_end_offset_seconds", "completion_offset_seconds")}
    timing["parent_not_safe_offset_seconds"] = first[0]
    timing["internal_candidate_time_unknown_reason"] = attempt["internal_candidate_time_unknown_reason"]
    ok = (checks["first_attempt"] == 1 and checks["second_attempt"] == 8 and checks["ties_at_first_offset"] == 1
          and checks["missing_parent_observations"] == 0
          and all(v for k, v in checks.items() if k.endswith(("matches", "no_candidate"))))
    return ok, checks, timing


def base_input():
    """Fixed benign IncentiveMechansim(256, 40) input, chosen without reading the candidate."""
    scalar = {"RATE_OF_DECAY": 20000000, "RATE_OF_RECOVERY": 10000000, "FLATTENING_COEFFICIENT": 0,
              "PROOF_SIZE_THRESHOLD": 0, "PROOF_SIZE_WEIGHT": 0, "RESPONSE_TIME_WEIGHT": 30000000,
              "MAXIMUM_RESPONSE_TIME_DECIMAL": 100000000, "COMPETITION_WEIGHT": 20000000,
              "scaling": 100000000}
    vector = {"maximum_score": 100000000, "previous_score": 10000000, "verified": 1, "proof_size": 1000,
              "response_time": 30, "competition": 50000000, "maximum_response_time": 100,
              "minimum_response_time": 0, "block_number": 1, "validator_uid": 0}
    data = {k: str(v) for k, v in scalar.items()}
    data.update({k: [str(v)] * BATCH for k, v in vector.items()})
    data["miner_uid"] = [str(i) for i in range(BATCH)]
    return data


def enumerate_instances(symbols):
    children = {}
    for name in symbols:
        if name.startswith("main.") and "." in name:
            prefix, leaf = name.rsplit(".", 1)
            children.setdefault(prefix, set()).add(leaf)
    shaped = sorted(p for p, leaves in children.items() if leaves == {"a", "b", "c", "d"})
    classes = {k: [] for k in CLASSES}
    unclassified = []
    for prefix in shaped:
        matched = [k for k, pattern in CLASSES.items() if re.fullmatch(pattern, prefix)]
        if len(matched) == 1:
            classes[matched[0]].append((int(re.fullmatch(CLASSES[matched[0]], prefix).group(1)), prefix))
        else:
            unclassified.append(prefix)
    summary = {}
    for key, items in classes.items():
        indices = sorted(i for i, _ in items)
        wiring = {s: {"wired": sum(1 for _, p in items if symbols[f"{p}.{s}"] >= 0),
                      "eliminated": sum(1 for _, p in items if symbols[f"{p}.{s}"] < 0)} for s in "abcd"}
        summary[key] = {"instances": len(items), "indices_complete": indices == list(range(BATCH)),
                        "signal_wiring": wiring}
    return shaped, classes, unclassified, summary


def main():
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=False)
    subprocess.run(["git", "check-ignore", "--quiet", str(OUT)], cwd=ROOT, check=True)
    (OUT / "logs").mkdir()
    record = {"version": "a02-first-semantic-prep-v1", "candidate_parsed": False}
    for name in TOOLS:
        pinned(*TOOLS[name])
    for rel, digest in PINNED.items():
        pinned(ROOT / rel, digest)
    record["pinned_inputs"] = len(PINNED)

    ok, checks, timing = selection_check()
    record["selection"] = {"passed": ok, "checks": checks, "timing": timing}
    if not ok:
        raise Stop("selection re-check failed")

    manifest = [line.split("  ", 1) for line in (ROOT / MANIFEST).read_text().splitlines() if line.strip()]
    mismatches = [rel for digest, rel in manifest if sha(TREE / rel) != digest]
    record["clean_tree"] = {"manifest_files": len(manifest), "mismatches": len(mismatches)}
    if mismatches:
        raise Stop("clean tree differs from the A-02 manifest")
    vuln = {}
    for rel in VULN_FILES:
        blob, data = blob_at(VULN_COMMIT, rel)
        vuln[rel] = {"blob": blob, "matches_clean_tree": data == (TREE / rel).read_bytes()}
    record["vulnerable_revision_blobs"] = vuln
    if not all(v["matches_clean_tree"] for v in vuln.values()):
        raise Stop("clean tree differs from the vulnerable revision")

    blob, fixed = blob_at(FIX_COMMIT, "src/subtractTensor.circom")
    fixed_tree = OUT / "fixed-tree"
    (fixed_tree / "src").mkdir(parents=True)
    (fixed_tree / "zkfdo-targets").mkdir()
    (fixed_tree / "src/subtractTensor.circom").write_bytes(fixed)
    shutil.copy2(TREE / "zkfdo-targets/src__subtractTensor__Subtract.circom", fixed_tree / "zkfdo-targets/")
    record["fix"] = {"commit": FIX_COMMIT, "blob": blob, "source_sha256": hashlib.sha256(fixed).hexdigest(),
                     "provenance": "verified_by_git_object_chain",
                     "source_equals_s01_fix_snapshot": hashlib.sha256(fixed).hexdigest() == S01_FIX_SOURCE}

    original = compile_circuit(TREE / "zkfdo-targets/src__subtractTensor__Subtract.circom",
                               OUT / "compiled-subtract", "compile-subtract", TREE)
    if sha(original["r1cs"]) != SUBTRACT_R1CS:
        raise Stop("recompiled Subtract R1CS differs from A-02 preflight")
    fixed_art = compile_circuit(fixed_tree / "zkfdo-targets/src__subtractTensor__Subtract.circom",
                                OUT / "compiled-subtract-fixed", "compile-subtract-fixed", fixed_tree)
    record["subtract"] = {"r1cs_sha256": sha(original["r1cs"]), "shape": r1cs_shape(original["r1cs"]),
                          "sym_sha256": sha(original["sym"]), "wired_names": sorted(
                              n for n, w in read_sym(original["sym"]).items() if w >= 0),
                          "fixed_r1cs_sha256": sha(fixed_art["r1cs"]), "fixed_shape": r1cs_shape(fixed_art["r1cs"]),
                          "fixed_sym_sha256": sha(fixed_art["sym"]),
                          "fixed_r1cs_equals_s01_fixed": sha(fixed_art["r1cs"]) == S01_FIX_R1CS}

    entry = compile_circuit(TREE / "src/circuit.circom", OUT / "compiled-entry", "compile-entry", TREE, 600)
    if sha(entry["r1cs"]) != ENTRY_R1CS:
        raise Stop("recompiled entrypoint R1CS differs from A-02 whole preflight")
    symbols = read_sym(entry["sym"])
    shaped, classes, unclassified, summary = enumerate_instances(symbols)
    output_wires = r1cs_shape(entry["r1cs"])["outputs"]
    record["entry"] = {"r1cs_sha256": sha(entry["r1cs"]), "shape": r1cs_shape(entry["r1cs"]),
                       "sym_sha256": sha(entry["sym"]), "wasm_sha256": sha(entry["wasm"]),
                       "subtract_shaped_instances": len(shaped), "unclassified_instances": len(unclassified),
                       "classes": summary,
                       "main_output_names": sum(1 for n, w in symbols.items()
                                                if 1 <= w <= output_wires and n.count(".") == 1)}
    (OUT / "instances.json").write_text(json.dumps({k: [p for _, p in sorted(v)] for k, v in classes.items()},
                                                   indent=1) + "\n")

    base = OUT / "base"
    base.mkdir()
    (base / "input.json").write_text(json.dumps(base_input()) + "\n")
    code, _, err, timed_out = run("base-honest", [TOOLS["node"][0], entry["generator"], entry["wasm"],
                                                 base / "input.json", base / "witness.wtns"], base, 300)
    status = "ok" if code == 0 and not timed_out and (base / "witness.wtns").is_file() else (
        "assert_abort" if "Assert Failed" in err else "error")
    record["base"] = {"input_sha256": sha(base / "input.json"), "honest_status": status}
    if status != "ok":
        raise Stop("base input does not compute honestly")
    witness = read_wtns(base / "witness.wtns")
    d_values = [witness[symbols[f"{p}.d"]] for items in classes.values() for _, p in items]
    record["base"].update({
        "witness_sha256": sha(base / "witness.wtns"),
        "snarkjs": snark_verdict(entry["r1cs"], base / "witness.wtns", "base-check", base, 600),
        "python_unsatisfied": count_unsatisfied(entry["r1cs"], witness),
        "subtract_d_not_one": sum(1 for v in d_values if v != 1), "subtract_d_checked": len(d_values)})
    if record["base"]["snarkjs"] != "correct" or record["base"]["python_unsatisfied"] != 0:
        raise Stop("base witness is not accepted")

    record["process_wall_seconds_sum"] = sum(e["wall_seconds"] for e in LEDGER)
    record["prep_wall_seconds"] = time.perf_counter() - started
    record["processes"] = [{k: e[k] for k in ("index", "stage", "exit_code", "timed_out", "wall_seconds")}
                           for e in LEDGER]
    (OUT / "ledger.json").write_text(json.dumps(LEDGER, indent=2) + "\n")
    record["ledger_sha256"] = sha(OUT / "ledger.json")
    (OUT / "prep.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Stop as error:
        (OUT / "ledger.json").write_text(json.dumps(LEDGER, indent=2) + "\n")
        print(f"stopped: {error}")
        raise SystemExit(1)
