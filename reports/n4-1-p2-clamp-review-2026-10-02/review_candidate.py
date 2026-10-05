#!/usr/bin/env python3
"""S-02: review one pre-selected P2 Clamp(40) candidate against the fixed SCOPE.

Layers are judged separately: A general TCCT, B range/defect specification, and
C the zkFuzz tool label. Stdout and tracked files are value-free; raw values
stay under the ignored run directory. No fuzzing is performed.
"""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
BITS = 40
SCOPE = (ROOT / "reports/n4-1-p2-clamp-review-2026-10-02/SCOPE.md",
         "4aaea7a2c263ab12f35cfa20c7c45379efff038a4179d982c8f50c7c967db6ce")
P2 = ROOT / "runs/dev-rq1-pilot-2026-09-29/inference-main"
EXECUTION = P2 / "campaign/small-first/block-1/execution/execution-dea86966-f3b8-425b-b67c-607073d18d40"
CANDIDATE = (EXECUTION / "counterexample-candidates/0014/src__clampTensor__Clamp_40.circom_TDjO5oZz4N_counterexample.json",
             "3a04372930ff052952f54b72615c27751dfab3737596f0e95d2d17d16c80b02d")
OUTCOME = (EXECUTION / "outcome.json", "a84ed78074bb885c74bf22e1b1e2835b3465b4db2ccead4325269e043b3a27e0")
PLAN = (P2 / "campaign/small-first/block-1/plan.json", "b8843d8b816c6b36934556a98b78d75f711f714212015688e3b0025e76e1cc7f")
PREPARE = P2 / "prepared/small-first/prepare-099c7c89-5866-43fc-9e72-49beac54420d"
PREPARED = (PREPARE / "prepared.json", "da6b439618f1250c9d55cf6319dc6a04cc10ae251c87bbe7215cacd31b244122")
TARGET = PREPARE / "targets/0002"
VULN_SOURCE = (TARGET / "sources/src/clampTensor.circom",
               "ed11afa8196cee110703715dceb345233cecfb7a0bffea11cd3835234e7c08bf")
VULN_WRAPPER = (TARGET / "sources/zkfdo-targets/src__clampTensor__Clamp_40.circom",
                "76f18863588cca5e3fe579f580a7ca36bc39ab11158539cc84b8f5bbbccdced4")
PREPARED_R1CS = (TARGET / "structure/r1cs/src__clampTensor__Clamp_40.r1cs",
                 "7a3f2b61a51f52860e522348457acb13863f86fd8de00ae604749380ea671d56")
SNAPSHOT = ROOT / "runs/controlled-v3-preflight/excluded-source-snapshots/inference-clamp/fixed/project"
FIX_SOURCE = (SNAPSHOT / "src/clampTensor.circom",
              "8aafab37043d81658e61965e2fea720a3f138379c3f84887fd96432e9c6a3d9f")
FIX_WRAPPER = (SNAPSHOT / "circuit.circom", "353fe9ba8f435b037dd6927a5df12f2580d71bffd9a5b6e238408cfc4bef22e2")
CONTROL_INPUT = (ROOT / ".external/zkbugs/dataset/circom/inference-labs-inc/subnet-2-circom/koukyosyumei_clamp_comparator_overflow/direct_input.json",
                 "2a2786562640d559874f6221bfc06c682d558b2ac8f653a534876b6e58ee451c")
CLONE = ROOT / "runs/dev-projects/inference"
FIX_COMMIT, FIX_BLOB = "b8f92bdec1694138df0e069921f1aa0bdc94053e", "f4fbf7f7845fc4a9a7f6978f658b293cbc617108"
VULN_COMMIT, VULN_BLOB = "d310309c141d36504b3486cebd96ed70ef3a4fdf", "2f758f6dd1e5eee162f0ae5a8cdcfa2b4be9522a"
RUN_ID = "1b96a0fa-e320-4d55-a88f-b47c050cb016"
TARGET_ID = "sha256:d59fef915c37c148f4c3c6bc3e06a901e47fb771af21c13d959c404db12a2a51"
LIBRARIES = [P2 / "tree", ROOT / ".external/zkbugs/dataset/circom/dependencies",
             ROOT / ".external/zkbugs/dataset/circom/dependencies/circomlib"]
TOOLS = {"circom": (Path("/Users/miiz/.cargo/bin/circom"),
                    "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"),
         "node": (Path("/opt/homebrew/Cellar/node/26.0.0/bin/node"),
                  "08dad0581f00a0cabf4d49ec92ca1f25fdfd01c2c18fa8e92b35f04d4c24c164"),
         "snarkjs": (Path("/opt/homebrew/lib/node_modules/snarkjs/build/cli.cjs"),
                     "6d787e37a4d1a2c6dd6032dadca09c0b3b007d4d4578bb6232a98136555d051a")}
INPUTS = ["main.val", "main.min", "main.max"]
RANGE_SIGNALS = ["main.val", "main.min", "main.max", "main.temp_max"]
# run-v1 stopped before reading the candidate because a fixed-source compile
# failure ended the whole review; run-v2 isolates that failure to layer B3.
OUT = ROOT / "runs/n4-1-p2-clamp-review-2026-10-02/run-v2"


class Stop(Exception):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned(item):
    path, expected = item
    if not Path(path).is_file() or sha(path) != expected:
        raise Stop(f"hash mismatch or missing: {Path(path).name}")
    return Path(path)


LEDGER = []


def run(stage, args, cwd):
    started = time.perf_counter()
    index = len(LEDGER)
    stdout, stderr = OUT / f"logs/{index:02d}-{stage}.stdout", OUT / f"logs/{index:02d}-{stage}.stderr"
    try:
        process = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True, timeout=60)
        code, out, err, timed_out = process.returncode, process.stdout, process.stderr, False
    except subprocess.TimeoutExpired as error:
        code, out, err, timed_out = None, error.stdout or "", error.stderr or "", True
    out = out if isinstance(out, str) else out.decode()
    err = err if isinstance(err, str) else err.decode()
    stdout.write_text(out)
    stderr.write_text(err)
    LEDGER.append({"index": index, "stage": stage, "args": [str(a) for a in args], "exit_code": code,
                   "timed_out": timed_out, "wall_seconds": time.perf_counter() - started,
                   "stdout": {"path": str(stdout.relative_to(ROOT)), "sha256": sha(stdout)},
                   "stderr": {"path": str(stderr.relative_to(ROOT)), "sha256": sha(stderr)}})
    return code, out, err, timed_out


def git_object(kind, oid):
    data = subprocess.run(["git", "-C", str(CLONE), "cat-file", kind, oid], capture_output=True, check=True).stdout
    if hashlib.sha1(f"{kind} {len(data)}\0".encode() + data).hexdigest() != oid:
        raise Stop(f"git object hash mismatch for {kind}")
    return data


def tree_entry(data, name):
    i = 0
    while i < len(data):
        space, nul = data.index(b" ", i), data.index(b"\0", data.index(b" ", i))
        if data[space + 1:nul].decode() == name:
            return data[nul + 1:nul + 21].hex()
        i = nul + 21
    raise Stop(f"tree entry {name} missing")


def blob_from_commit(commit):
    tree = git_object("commit", commit).split(b"\n")[0].split()[1].decode()
    src = tree_entry(git_object("tree", tree), "src")
    blob = tree_entry(git_object("tree", src), "clampTensor.circom")
    return blob, git_object("blob", blob)


def read_r1cs(path):
    data = Path(path).read_bytes()
    if data[:4] != b"r1cs":
        raise Stop("not an r1cs file")
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
        raise Stop("unexpected R1CS prime")
    wires, outputs, pub_in, prv_in = struct.unpack_from("<IIII", header, 4 + n8)
    _, count = struct.unpack_from("<QI", header, 4 + n8 + 16)
    constraints, pos = [], 0
    for _ in range(count):
        triple = []
        for _ in range(3):
            terms = struct.unpack_from("<I", body, pos)[0]
            pos += 4
            lc = []
            for _ in range(terms):
                wire = struct.unpack_from("<I", body, pos)[0]
                lc.append((wire, int.from_bytes(body[pos + 4:pos + 4 + n8], "little")))
                pos += 4 + n8
                if wire >= wires:
                    raise Stop("invalid wire in R1CS")
            triple.append(lc)
        constraints.append(triple)
    return {"wires": wires, "outputs": outputs, "public_inputs": pub_in, "private_inputs": prv_in,
            "constraints": constraints}


def unsatisfied(r1cs, witness):
    value = lambda lc: sum(coef * witness[wire] for wire, coef in lc) % PRIME
    return [i for i, (a, b, c) in enumerate(r1cs["constraints"]) if value(a) * value(b) % PRIME != value(c)]


def read_sym(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        label, wire, component, name = line.split(",", 3)
        int(label), int(component)
        if name in result:
            raise Stop("duplicate symbol name")
        result[name] = int(wire)
    return result


def write_wtns(path, values):
    header = struct.pack("<I", 32) + PRIME.to_bytes(32, "little") + struct.pack("<I", len(values))
    body = b"".join(v.to_bytes(32, "little") for v in values)
    Path(path).write_bytes(b"wtns" + struct.pack("<II", 2, 2) + struct.pack("<IQ", 1, len(header)) + header
                           + struct.pack("<IQ", 2, len(body)) + body)


def snark_verdict(r1cs_path, wtns_path, stage, cwd):
    """Only explicit diagnostics count: correct, not_correct, otherwise error."""
    code, out, err, timed_out = run(stage, [TOOLS["node"][0], TOOLS["snarkjs"][0], "wtns", "check",
                                            r1cs_path, wtns_path], cwd)
    text = out + err
    if not timed_out and code == 0 and "WITNESS IS CORRECT" in text and "WITNESS IS NOT CORRECT" not in text:
        return "correct"
    if not timed_out and "WITNESS IS NOT CORRECT" in text:
        return "not_correct"
    return "error"


def compile_circuit(wrapper, folder, stage):
    folder.mkdir(parents=True)
    args = [TOOLS["circom"][0], wrapper, "--r1cs", "--prime", "bn128", "--output", folder]
    for library in LIBRARIES:
        args += ["-l", library]
    code, _, _, timed_out = run(stage, args + ["--sym", "--wasm"], wrapper.parent)
    if code != 0 or timed_out:
        raise Stop(f"{stage} failed")
    stem = wrapper.stem
    return {"r1cs": folder / f"{stem}.r1cs", "sym": folder / f"{stem}.sym",
            "wasm": folder / f"{stem}_js/{stem}.wasm", "generator": folder / f"{stem}_js/generate_witness.js"}


def calculate(artifacts, inputs, folder, stage):
    """Return (status, witness_path, stderr): status is ok, assert_abort or error."""
    folder.mkdir(parents=True)
    (folder / "input.json").write_text(json.dumps(inputs) + "\n")
    code, _, err, timed_out = run(stage, [TOOLS["node"][0], artifacts["generator"], artifacts["wasm"],
                                          folder / "input.json", folder / "witness.wtns"], folder)
    if code == 0 and not timed_out and (folder / "witness.wtns").is_file():
        return "ok", folder / "witness.wtns", err
    if not timed_out and "Assert Failed" in err:
        return "assert_abort", None, err
    return "error", None, err


def export(witness, folder, stage):
    code, _, _, timed_out = run(stage, [TOOLS["node"][0], TOOLS["snarkjs"][0], "wtns", "export", "json",
                                        witness, folder / "witness.json"], folder)
    if code != 0 or timed_out:
        raise Stop(f"{stage} failed")
    return [int(x) for x in json.loads((folder / "witness.json").read_text())]


def main():
    started = time.perf_counter()
    pinned(SCOPE)
    OUT.mkdir(parents=True, exist_ok=False)
    subprocess.run(["git", "check-ignore", "--quiet", str(OUT)], cwd=ROOT, check=True)
    (OUT / "logs").mkdir()
    verdicts = {name: "not_run" for name in (
        "binding", "fix_provenance", "A1_original_constraints", "A2_honest_relation", "A3_general_tcct_property",
        "A4_general_tcct_attribution", "B1_range", "B2_intended_order", "B3_fixed_rejection",
        "B4_range_spec_attribution", "C_tool_label")}
    verdicts.update({"caller_context": "unresolved_not_reviewed", "entrypoint_tcct": "unresolved_not_reviewed",
                     "project_semantics": "unresolved_not_reviewed"})
    notes, evidence, raw = [], {}, {}
    try:
        for name in TOOLS:
            pinned(TOOLS[name])
        candidate_path, outcome_path, plan_path = pinned(CANDIDATE), pinned(OUTCOME), pinned(PLAN)
        for item in (PREPARED, VULN_SOURCE, VULN_WRAPPER, PREPARED_R1CS, FIX_SOURCE, FIX_WRAPPER, CONTROL_INPUT):
            pinned(item)
        outcome = json.loads(outcome_path.read_text())
        entries = [c for c in outcome["counterexample_candidates"] if c["preserved_path"] == str(candidate_path)]
        runs = {r["result"]["run_id"]: r for r in outcome["scheduler"]["runs"] if r.get("result")}
        plan_targets = {t["target_id"] for t in json.loads(plan_path.read_text())["targets"]}
        binding_ok = (len(entries) == 1 and entries[0]["sha256"] == CANDIDATE[1]
                      and entries[0]["run_id"] == RUN_ID and entries[0]["target_id"] == TARGET_ID
                      and RUN_ID in runs and runs[RUN_ID]["target_id"] == TARGET_ID
                      and runs[RUN_ID]["result"]["status"] == "bug_found" and TARGET_ID in plan_targets
                      and outcome["plan_sha256"] == PLAN[1])
        verdicts["binding"] = "passed" if binding_ok else "failed"
        if not binding_ok:
            raise Stop("candidate binding failed")

        # Fix provenance: recompute the git object chain of the fix commit in the local clone.
        try:
            fix_blob, fix_bytes = blob_from_commit(FIX_COMMIT)
            vuln_blob, vuln_bytes = blob_from_commit(VULN_COMMIT)
            provenance_ok = (fix_blob == FIX_BLOB and fix_bytes == FIX_SOURCE[0].read_bytes()
                             and vuln_blob == VULN_BLOB and vuln_bytes == VULN_SOURCE[0].read_bytes())
        except (Stop, subprocess.CalledProcessError, ValueError):
            provenance_ok = False
        verdicts["fix_provenance"] = "verified_by_git_object_chain" if provenance_ok else "unverified"

        vuln = OUT / "vulnerable"
        (vuln / "src").mkdir(parents=True)
        (vuln / "zkfdo-targets").mkdir()
        shutil.copy2(VULN_SOURCE[0], vuln / "src/clampTensor.circom")
        shutil.copy2(VULN_WRAPPER[0], vuln / "zkfdo-targets" / VULN_WRAPPER[0].name)
        fixed = OUT / "fixed"
        (fixed / "src").mkdir(parents=True)
        shutil.copy2(FIX_SOURCE[0], fixed / "src/clampTensor.circom")
        shutil.copy2(FIX_WRAPPER[0], fixed / "circuit.circom")
        v = compile_circuit(vuln / "zkfdo-targets" / VULN_WRAPPER[0].name, OUT / "compiled-vulnerable", "compile-vulnerable")
        evidence["recompiled_vulnerable_r1cs_sha256"] = sha(v["r1cs"])
        if sha(v["r1cs"]) != PREPARED_R1CS[1]:
            raise Stop("recompiled R1CS differs from the prepared R1CS")
        r1cs, symbols = read_r1cs(v["r1cs"]), read_sym(v["sym"])
        evidence["vulnerable_r1cs_shape"] = {k: r1cs[k] for k in ("wires", "outputs", "public_inputs", "private_inputs")} | {"constraints": len(r1cs["constraints"])}
        # A fixed-source compile failure only affects layer B3 (SCOPE section 4).
        try:
            f = compile_circuit(fixed / "circuit.circom", OUT / "compiled-fixed", "compile-fixed")
            evidence["recompiled_fixed_r1cs_sha256"] = sha(f["r1cs"])
            fixed_r1cs = read_r1cs(f["r1cs"])
            evidence["fixed_r1cs_shape"] = {k: fixed_r1cs[k] for k in ("wires", "outputs", "public_inputs", "private_inputs")} | {"constraints": len(fixed_r1cs["constraints"])}
            evidence["fixed_compile"] = "passed"
        except Stop:
            f = None
            log = (OUT / f"logs/{LEDGER[-1]['index']:02d}-compile-fixed.stderr").read_text()
            evidence["fixed_compile"] = {"status": "failed", "exit_code": LEDGER[-1]["exit_code"],
                                         "error_code_T3001": "T3001" in log,
                                         "uninitialized_signal_temp_max": "not initialized" in log and "temp_max" in log}

        candidate = json.loads(candidate_path.read_text())
        evidence["candidate_top_level_keys"] = sorted(candidate)
        flag = candidate.get("5_flag")
        verdicts["C_tool_label"] = (flag.get("1_type") if isinstance(flag, dict) and isinstance(flag.get("1_type"), str)
                                    else "label_unavailable")
        evidence["tool_flag_keys"] = sorted(flag) if isinstance(flag, dict) else None
        if "7_assignment" not in candidate:
            verdicts["A1_original_constraints"] = "unresolved"
            raise Stop("candidate has no assignment field")
        try:
            assignment = {name: int(value) for name, value in candidate["7_assignment"].items()}
        except (TypeError, ValueError):
            verdicts["A1_original_constraints"] = "unresolved"
            raise Stop("candidate assignment is not decimal field values")

        # A1: complete witness from the candidate for every wire of the pinned original R1CS.
        wired = {name: wire for name, wire in symbols.items() if wire >= 0}
        eliminated = sorted(name for name, wire in symbols.items() if wire < 0)
        missing = sorted(name for name in wired if name not in assignment)
        evidence["symbol_counts"] = {"wired_names": len(wired), "eliminated_names": len(eliminated),
                                     "candidate_names": len(assignment), "candidate_only_names": len(set(assignment) - set(symbols)),
                                     "wired_names_missing_in_candidate": len(missing)}
        values, alias_conflict = {0: 1}, False
        for name, wire in wired.items():
            if name in assignment:
                if wire in values and values[wire] != assignment[name]:
                    alias_conflict = True
                values.setdefault(wire, assignment[name])
        canonical = all(0 <= x < PRIME for x in assignment.values())
        if missing or alias_conflict or not canonical or set(values) != set(range(r1cs["wires"])):
            verdicts["A1_original_constraints"] = "unresolved"
            evidence["A1_mapping_problem"] = {"missing_wired_names": missing[:20], "alias_conflict": alias_conflict,
                                              "canonical": canonical}
            raise Stop("candidate does not map to a complete canonical witness")
        cand_vector = [values[i] for i in range(r1cs["wires"])]
        python_failed = unsatisfied(r1cs, cand_vector)
        write_wtns(OUT / "candidate.wtns", cand_vector)
        snark = snark_verdict(v["r1cs"], OUT / "candidate.wtns", "check-candidate-original", OUT)
        evidence["candidate_wtns_sha256"] = sha(OUT / "candidate.wtns")
        evidence["A1_methods"] = {"python_unsatisfied_constraints": len(python_failed), "snarkjs": snark}
        if not python_failed and snark == "correct":
            verdicts["A1_original_constraints"] = "passed"
        elif python_failed and snark == "not_correct":
            verdicts["A1_original_constraints"] = "failed"
        else:
            verdicts["A1_original_constraints"] = "unresolved"

        # A2: honest computation for the same inputs on the pinned original.
        inputs = {name.split(".", 1)[1]: str(assignment[name]) for name in INPUTS}
        status, witness, err = calculate(v, inputs, OUT / "honest-original", "honest-original")
        evidence["A2_honest_status"] = status
        if status == "assert_abort":
            verdicts["A2_honest_relation"] = "abort"
            evidence["A2_abort_template_mentions"] = sorted({t for t in ("Num2Bits", "LessThan", "Clamp", "AssertBit") if t in err})
        elif status == "error":
            verdicts["A2_honest_relation"] = "unresolved"
        else:
            honest_check = snark_verdict(v["r1cs"], witness, "check-honest-original", OUT / "honest-original")
            honest = export(witness, OUT / "honest-original", "export-honest-original")
            # Positive control for the local .wtns writer.
            write_wtns(OUT / "honest-original/rewritten.wtns", honest)
            evidence["wtns_writer_control"] = snark_verdict(v["r1cs"], OUT / "honest-original/rewritten.wtns",
                                                            "check-writer-control", OUT / "honest-original")
            evidence["A2_honest_snarkjs"] = honest_check
            if honest_check != "correct" or evidence["wtns_writer_control"] != "correct":
                verdicts["A2_honest_relation"] = "unresolved"
                if evidence["wtns_writer_control"] != "correct":
                    verdicts["A1_original_constraints"] = "unresolved"
            else:
                differing = sorted(name for name, wire in wired.items() if values[wire] != honest[wire])
                evidence["A2_differing_wired_signals"] = differing
                evidence["A2_differing_count"] = len(differing)
                verdicts["A2_honest_relation"] = "output_differs" if "main.out" in differing else (
                    "identical" if not differing else "internal_differs_output_same")
                raw["honest_interface"] = {n: str(honest[wired[n]]) for n in INPUTS + ["main.out"] if n in wired}

        # A3/A4: general TCCT property and attribution.
        if verdicts["A1_original_constraints"] == "failed":
            verdicts["A3_general_tcct_property"] = "not_violated_candidate_fails_constraints"
            verdicts["A4_general_tcct_attribution"] = "not_applicable"
        elif verdicts["A1_original_constraints"] != "passed" or verdicts["A2_honest_relation"] in ("unresolved", "not_run"):
            verdicts["A3_general_tcct_property"] = "unresolved"
            verdicts["A4_general_tcct_attribution"] = "unresolved"
        elif verdicts["A2_honest_relation"] in ("output_differs", "abort"):
            verdicts["A3_general_tcct_property"] = "violated"
            verdicts["A4_general_tcct_attribution"] = "unresolved_needs_rule"
        else:
            verdicts["A3_general_tcct_property"] = "not_violated"
            verdicts["A4_general_tcct_attribution"] = "not_applicable"

        # B1/B2: range and intended unsigned ordering (specification layer).
        present = {n: assignment[n] for n in RANGE_SIGNALS if n in assignment}
        out_of_range = sorted(n for n, x in present.items() if x >= 2 ** BITS)
        evidence["B1_checked_signals"] = sorted(present)
        evidence["B1_out_of_range_signals"] = out_of_range
        verdicts["B1_range"] = ("out_of_range" if out_of_range else
                                "within_range" if len(present) == len(RANGE_SIGNALS) else "unresolved")
        if all(n in assignment for n in INPUTS + ["main.out"]):
            val, low, high = (assignment[n] for n in INPUTS)
            intended = min(max(val, low), high)
            verdicts["B2_intended_order"] = "differs" if assignment["main.out"] != intended else "matches"
        else:
            verdicts["B2_intended_order"] = "unresolved"

        # B3: fixed-version rejection with the actual diagnostic and an in-range control.
        input_out_of_range = [n for n in out_of_range if n in INPUTS]
        control = json.loads(CONTROL_INPUT[0].read_text())
        control_in_range = all(0 <= int(control[k]) < 2 ** BITS for k in ("val", "min", "max"))
        if f is None:
            # No executable fixed artifact: the source-level range argument is recorded only.
            evidence["B3"] = {"arithmetic_unsat_inputs_by_source_reading": input_out_of_range,
                              "fixed_witness_status": "not_run_fixed_compile_failed",
                              "control_in_range": control_in_range, "control_witness_and_check": "not_run"}
            verdicts["B3_fixed_rejection"] = "unresolved_fixed_compile_failed"
        else:
            status, _, err = calculate(f, inputs, OUT / "fixed-candidate", "fixed-candidate")
            c_status, c_witness, _ = calculate(f, control, OUT / "fixed-control", "fixed-control")
            control_ok = c_status == "ok" and snark_verdict(f["r1cs"], c_witness, "check-fixed-control",
                                                             OUT / "fixed-control") == "correct"
            fixed_rejects = status == "assert_abort" and "Num2Bits" in err
            evidence["B3"] = {"arithmetic_unsat_inputs": input_out_of_range, "fixed_witness_status": status,
                              "fixed_assert_mentions_Num2Bits": "Num2Bits" in err, "control_in_range": control_in_range,
                              "control_witness_and_check": control_ok}
            if input_out_of_range and fixed_rejects and control_in_range and control_ok:
                verdicts["B3_fixed_rejection"] = ("confirmed" if verdicts["fix_provenance"].startswith("verified")
                                                  else "auxiliary_only_provenance_unverified")
            elif not out_of_range:
                verdicts["B3_fixed_rejection"] = "not_applicable_within_range"
            else:
                verdicts["B3_fixed_rejection"] = "unresolved"

        # B4: attribution at the range/specification layer only.
        verdicts["B4_range_spec_attribution"] = (
            "attributed_range_spec_layer" if verdicts["A1_original_constraints"] == "passed"
            and verdicts["B1_range"] == "out_of_range" and verdicts["B3_fixed_rejection"] == "confirmed"
            else "unresolved")
        raw.update({"candidate_interface": {n: str(assignment[n]) for n in INPUTS + ["main.out", "main.temp_max"]
                                            if n in assignment},
                    "zkfuzz_flag": flag})
    except Stop as error:
        notes.append(str(error))
    finally:
        (OUT / "raw-values.json").write_text(json.dumps(raw, indent=2) + "\n")
        (OUT / "ledger.json").write_text(json.dumps(LEDGER, indent=2) + "\n")
        result = {"verdicts": verdicts, "notes": notes, "evidence": evidence,
                  "ledger": {"path": str((OUT / "ledger.json").relative_to(ROOT)), "sha256": sha(OUT / "ledger.json")},
                  "raw_values": {"path": str((OUT / "raw-values.json").relative_to(ROOT)), "sha256": sha(OUT / "raw-values.json")},
                  "review_tool_wall_seconds": time.perf_counter() - started,
                  "process_wall_seconds_sum": sum(item["wall_seconds"] for item in LEDGER),
                  "processes": [{k: item[k] for k in ("index", "stage", "exit_code", "timed_out", "wall_seconds")}
                                for item in LEDGER]}
        (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"verdicts": verdicts, "notes": notes, "result_sha256": sha(OUT / "result.json")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
