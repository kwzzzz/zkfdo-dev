#!/usr/bin/env python3
"""S-04: review the second A-02 candidate occurrence, IntDiv(40), against the fixed SCOPE.

Layers: A general TCCT (component), B specification/fix, C zkFuzz label, D single
cause attribution, E context (recorded, not judged). Stdout and tracked files are
value-free; raw values stay under the ignored run directory. No fuzzing.
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
SCOPE = (ROOT / "reports/n4-1-a02-intdiv-review-2026-10-02/SCOPE.md",
         "e122217998acfcd12fb007ed7022825068b7110bdc1b4cffa1f9c6feed39ffa7")
CAMPAIGN = ROOT / "runs/n4-1-policy-a-engine-2026-10-02/small-first-campaign-v1"
LEDGER_FILE = (CAMPAIGN / "ledger.json", "8912e24976bc7d7dc414a7eddcda67007fa5aeffff989babf017d09fa0bbcb8e")
CANDIDATE_REL = "attempts/000008/candidates/zkfdo-targets/src__integerDivision__IntDiv_40.circom_5vPZul9Pul_counterexample.json"
CANDIDATE = (CAMPAIGN / CANDIDATE_REL, "f5a346327427a1b3a288fc099f8fbcd0635f8b4c289b57bd5f22fa0a1f08a143")
RESULT = (CAMPAIGN / "attempts/000008/result.json", "4d8b4fe0dff5602bade02aa95496902694166dd73ef56476024abbf38bcbe97f")
TARGET_ID = "sha256:0afd371f7b994556bc894a5773e85b63e668c56dce8b1dee0dd78e2faffc23a2"
EXPECTED_OFFSET, EXPECTED_COMPLETION = 77.99670775, 78.005990458
TREE = ROOT / "runs/dev-rq1-pilot-2026-09-29/inference-main/tree"
SOURCES = {"src/integerDivision.circom": "325e1432bc19d11ec15709836e01eb5ec7a337c9a3c71467ed6dee08b01c467d",
           "src/clampTensor.circom": "ed11afa8196cee110703715dceb345233cecfb7a0bffea11cd3835234e7c08bf",
           "zkfdo-targets/src__integerDivision__IntDiv_40.circom": "8f498bbe02b2b280cfc5a9bb77a8cdfc7f2034c992ec9700aab092d10dac69e1"}
ORIGINAL_R1CS = "1bcdc3ea0ca994a1efcb37631d09fb47efccacbaf331f09becb48aa87e7c3c5d"
CLONE = ROOT / "runs/dev-projects/inference"
FIX_COMMIT = "b8f92bdec1694138df0e069921f1aa0bdc94053e"
FIX_BLOBS = {"integerDivision.circom": ("7e90e2da5dc1985c12b54cc8bbc1e7acb2093413",
                                        "7ea9ab0edb813324b42c8132e5ddff224d62752f7730a5f56bbc32ada1e7adfa"),
             "clampTensor.circom": ("f4fbf7f7845fc4a9a7f6978f658b293cbc617108",
                                    "8aafab37043d81658e61965e2fea720a3f138379c3f84887fd96432e9c6a3d9f")}
LIBRARIES = [ROOT / ".external/zkbugs/dataset/circom/dependencies",
             ROOT / ".external/zkbugs/dataset/circom/dependencies/circomlib"]
TOOLS = {"circom": (Path("/Users/miiz/.cargo/bin/circom"),
                    "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"),
         "node": (Path("/opt/homebrew/Cellar/node/26.0.0/bin/node"),
                  "08dad0581f00a0cabf4d49ec92ca1f25fdfd01c2c18fa8e92b35f04d4c24c164"),
         "snarkjs": (Path("/opt/homebrew/lib/node_modules/snarkjs/build/cli.cjs"),
                     "6d787e37a4d1a2c6dd6032dadca09c0b3b007d4d4578bb6232a98136555d051a")}
INPUTS = ["main.in[0]", "main.in[1]"]
RANGE_SIGNALS = ["main.quot", "main.rem", "main.in[1]"]
DIRECT = {"main.in[0]", "main.in[1]", "main.out", "main.quot", "main.rem", "main.is_non_zero", "main.rem_is_valid"}
OUT = ROOT / "runs/n4-1-a02-intdiv-review-2026-10-02/run-v1"


class Stop(Exception):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned(path, expected):
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


def compile_circuit(wrapper, folder, stage, project):
    folder.mkdir(parents=True)
    args = [TOOLS["circom"][0], wrapper, "--r1cs", "--prime", "bn128", "--output", folder, "-l", project]
    for library in LIBRARIES:
        args += ["-l", library]
    code, _, _, timed_out = run(stage, args + ["--sym", "--wasm"], wrapper.parent)
    if code != 0 or timed_out:
        raise Stop(f"{stage} failed")
    stem = wrapper.stem
    return {"r1cs": folder / f"{stem}.r1cs", "sym": folder / f"{stem}.sym",
            "wasm": folder / f"{stem}_js/{stem}.wasm", "generator": folder / f"{stem}_js/generate_witness.js"}


def calculate(artifacts, inputs, folder, stage):
    """Return (status, witness_path, stderr) with status ok, assert_abort or error."""
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


def selection_check():
    """Recompute the parent NOT SAFE order from the raw ledger without reading candidate values."""
    ledger = json.loads(pinned(*LEDGER_FILE).read_text())
    occurrences = []
    for attempt in ledger["attempts"]:
        offsets = [o["campaign_offset_seconds"] for o in attempt.get("log_observations", []) if o["kind"] == "not_safe"]
        for candidate in attempt.get("candidates", []):
            occurrences.append((min(offsets) if offsets else float("inf"), attempt["attempt_index"],
                                candidate["path"], candidate["sha256"], attempt))
    occurrences.sort(key=lambda o: o[:3])
    second = occurrences[1]
    attempt = second[4]
    checks = {"occurrences": len(occurrences), "first_attempt": occurrences[0][1], "second_attempt": second[1],
              "second_offset_matches": second[0] == EXPECTED_OFFSET,
              "second_completion_matches": attempt["completion_offset_seconds"] == EXPECTED_COMPLETION,
              "second_path_matches": second[2] == CANDIDATE_REL, "second_sha_matches": second[3] == CANDIDATE[1],
              "second_target_matches": attempt["target_id"] == TARGET_ID,
              "ties_at_second_offset": sum(1 for o in occurrences if o[0] == second[0]),
              "result_sha_matches": attempt["result"]["sha256"] == RESULT[1]}
    ok = (checks["first_attempt"] == 1 and checks["second_attempt"] == 8 and checks["ties_at_second_offset"] == 1
          and all(v for k, v in checks.items() if k.endswith("matches")))
    return ok, checks


def main():
    started = time.perf_counter()
    pinned(*SCOPE)
    OUT.mkdir(parents=True, exist_ok=False)
    subprocess.run(["git", "check-ignore", "--quiet", str(OUT)], cwd=ROOT, check=True)
    (OUT / "logs").mkdir()
    verdicts = {name: "not_run" for name in (
        "selection_and_binding", "fix_provenance", "fixed_compile", "A1_original_constraints",
        "A2_honest_relation", "A3_general_tcct_property", "B1_range", "B2_fix_relation", "C_tool_label",
        "D_single_cause_attribution")}
    verdicts.update({"E_caller_context": "unresolved_not_reviewed", "E_entrypoint_tcct": "unresolved_not_reviewed",
                     "E_project_semantics": "unresolved_not_reviewed"})
    notes, evidence, raw = [], {}, {}
    try:
        for name in TOOLS:
            pinned(*TOOLS[name])
        ok, checks = selection_check()
        evidence["selection_checks"] = checks
        pinned(*CANDIDATE), pinned(*RESULT)
        verdicts["selection_and_binding"] = "passed" if ok else "failed"
        if not ok:
            raise Stop("selection or binding check failed")

        # Original snapshot and fixed sources from the verified fix commit objects.
        original = OUT / "original"
        for rel, digest in SOURCES.items():
            pinned(TREE / rel, digest)
            (original / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(TREE / rel, original / rel)
        fixed = OUT / "fixed"
        try:
            tree = git_object("commit", FIX_COMMIT).split(b"\n")[0].split()[1].decode()
            src = git_object("tree", tree_entry(git_object("tree", tree), "src"))
            (fixed / "src").mkdir(parents=True)
            provenance_ok = True
            for name, (blob, digest) in FIX_BLOBS.items():
                if tree_entry(src, name) != blob:
                    provenance_ok = False
                data = git_object("blob", blob)
                (fixed / "src" / name).write_bytes(data)
                provenance_ok &= hashlib.sha256(data).hexdigest() == digest
        except (Stop, subprocess.CalledProcessError, ValueError):
            provenance_ok = False
        verdicts["fix_provenance"] = "verified_by_git_object_chain" if provenance_ok else "unverified"
        (fixed / "zkfdo-targets").mkdir(parents=True, exist_ok=True)
        wrapper_rel = "zkfdo-targets/src__integerDivision__IntDiv_40.circom"
        shutil.copy2(original / wrapper_rel, fixed / wrapper_rel)

        v = compile_circuit(original / wrapper_rel, OUT / "compiled-original", "compile-original", original)
        evidence["recompiled_original_r1cs_sha256"] = sha(v["r1cs"])
        if sha(v["r1cs"]) != ORIGINAL_R1CS:
            raise Stop("recompiled R1CS differs from the A-02/P2 R1CS")
        r1cs, symbols = read_r1cs(v["r1cs"]), read_sym(v["sym"])
        evidence["original_r1cs_shape"] = {k: r1cs[k] for k in ("wires", "outputs", "public_inputs", "private_inputs")} | {"constraints": len(r1cs["constraints"])}
        f = None
        if provenance_ok:
            try:
                f = compile_circuit(fixed / wrapper_rel, OUT / "compiled-fixed", "compile-fixed", fixed)
                verdicts["fixed_compile"] = "passed"
            except Stop:
                log = (OUT / f"logs/{LEDGER[-1]['index']:02d}-compile-fixed.stderr").read_text()
                verdicts["fixed_compile"] = "failed"
                evidence["fixed_compile_error"] = {"T3001": "T3001" in log, "mentions_temp_max": "temp_max" in log,
                                                   "exit_code": LEDGER[-1]["exit_code"]}
        else:
            verdicts["fixed_compile"] = "not_run_provenance_unverified"

        candidate = json.loads(pinned(*CANDIDATE).read_text())
        evidence["candidate_top_level_keys"] = sorted(candidate)
        flag = candidate.get("5_flag")
        verdicts["C_tool_label"] = (flag.get("1_type") if isinstance(flag, dict) and isinstance(flag.get("1_type"), str)
                                    else "label_unavailable")
        evidence["tool_flag_keys"] = sorted(flag) if isinstance(flag, dict) else None
        try:
            assignment = {name: int(value) for name, value in candidate["7_assignment"].items()}
        except (KeyError, TypeError, ValueError):
            verdicts["A1_original_constraints"] = "unresolved"
            raise Stop("candidate assignment missing or not decimal field values")

        # A1: complete witness for every wire of the pinned original R1CS.
        wired = {name: wire for name, wire in symbols.items() if wire >= 0}
        missing = sorted(name for name in wired if name not in assignment)
        values, alias_conflict = {0: 1}, False
        for name, wire in wired.items():
            if name in assignment:
                if wire in values and values[wire] != assignment[name]:
                    alias_conflict = True
                values.setdefault(wire, assignment[name])
        canonical = all(0 <= x < PRIME for x in assignment.values())
        evidence["symbol_counts"] = {"wired_names": len(wired), "eliminated_names": len(symbols) - len(wired),
                                     "candidate_names": len(assignment),
                                     "candidate_only_names": len(set(assignment) - set(symbols)),
                                     "wired_names_missing_in_candidate": len(missing)}
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
        verdicts["A1_original_constraints"] = ("passed" if not python_failed and snark == "correct" else
                                               "failed" if python_failed and snark == "not_correct" else "unresolved")

        # A2: honest computation for the same inputs.
        inputs = {"in": [str(assignment[n]) for n in INPUTS]}
        status, witness, err = calculate(v, inputs, OUT / "honest-original", "honest-original")
        evidence["A2_honest_status"] = status
        differing = None
        if status == "assert_abort":
            verdicts["A2_honest_relation"] = "abort"
            evidence["A2_abort_mentions"] = sorted(t for t in ("Num2Bits", "LessThan", "IntDiv", "IsZero", "AssertBit")
                                                   if t in err)
        elif status == "error":
            verdicts["A2_honest_relation"] = "unresolved"
        else:
            honest_check = snark_verdict(v["r1cs"], witness, "check-honest-original", OUT / "honest-original")
            honest = export(witness, OUT / "honest-original", "export-honest-original")
            write_wtns(OUT / "honest-original/rewritten.wtns", honest)
            writer = snark_verdict(v["r1cs"], OUT / "honest-original/rewritten.wtns", "check-writer-control",
                                   OUT / "honest-original")
            evidence["A2_honest_snarkjs"], evidence["wtns_writer_control"] = honest_check, writer
            evidence["honest_wtns_sha256"] = sha(witness)
            if honest_check != "correct" or writer != "correct":
                verdicts["A2_honest_relation"] = "unresolved"
                if writer != "correct":
                    verdicts["A1_original_constraints"] = "unresolved"
            else:
                differing = sorted(name for name, wire in wired.items() if values[wire] != honest[wire])
                evidence["A2_differing_wired_signals"] = differing
                # Wire numbering places outputs first, so it is not a computation order;
                # a first divergence is named only when exactly one signal differs.
                evidence["A2_first_divergence"] = (differing[0] if len(differing) == 1 else
                                                   "none" if not differing else "multiple_unordered")
                evidence["A2_differing_direct"] = [n for n in differing if n in DIRECT]
                evidence["A2_differing_nested"] = [n for n in differing if n not in DIRECT]
                verdicts["A2_honest_relation"] = ("output_differs" if "main.out" in differing else
                                                  "identical" if not differing else "internal_differs_output_same")
                raw["honest_interface"] = {n: str(honest[wired[n]]) for n in INPUTS + ["main.out", "main.quot", "main.rem"]
                                           if n in wired}

        # A3: general TCCT property.
        a1, a2 = verdicts["A1_original_constraints"], verdicts["A2_honest_relation"]
        verdicts["A3_general_tcct_property"] = (
            "not_violated_candidate_fails_constraints" if a1 == "failed" else
            "unresolved" if a1 != "passed" or a2 in ("unresolved", "not_run") else
            "violated" if a2 in ("output_differs", "abort") else "not_violated")

        # B1: specification ranges from the fix (names only).
        present = {n: assignment[n] for n in RANGE_SIGNALS if n in assignment}
        out_of_range = sorted(n for n, x in present.items() if x >= 2 ** BITS)
        evidence["B1_out_of_range_signals"] = out_of_range
        verdicts["B1_range"] = ("out_of_range" if out_of_range else
                                "within_range" if len(present) == len(RANGE_SIGNALS) else "unresolved")

        # B2/D: relation to the fix and single-cause attribution (only when A3 is violated).
        fix = {}
        if f is not None:
            fixed_symbols = read_sym(f["sym"])
            fixed_r1cs = read_r1cs(f["r1cs"])
            out_wire, quot_wire = fixed_symbols.get("main.out"), fixed_symbols.get("main.quot")
            if out_wire is None or quot_wire is None:
                relation = "unresolved_names"
            elif out_wire >= 0 and out_wire == quot_wire:
                relation = "same_wire"
            elif out_wire < 0 or quot_wire < 0:
                relation = "one_eliminated"
            else:
                relation = "separate_wires"
            fix["out_quot_relation"] = relation
            fix["fixed_r1cs_sha256"] = sha(f["r1cs"])
            fix["fixed_r1cs_shape"] = {k: fixed_r1cs[k] for k in ("wires", "outputs", "public_inputs", "private_inputs")} | {"constraints": len(fixed_r1cs["constraints"])}
            f_status, f_witness, f_err = calculate(f, inputs, OUT / "honest-fixed", "honest-fixed")
            fix["fixed_honest_status"] = f_status
            fix["fixed_honest_check"] = (snark_verdict(f["r1cs"], f_witness, "check-honest-fixed", OUT / "honest-fixed")
                                         if f_status == "ok" else "not_run")
            if f_status == "assert_abort":
                fix["fixed_abort_mentions"] = sorted(t for t in ("Num2Bits", "LessThan", "IntDiv", "IsZero") if t in f_err)
            cand_out_ne_quot = "main.out" in assignment and "main.quot" in assignment and assignment["main.out"] != assignment["main.quot"]
            fix["candidate_out_differs_from_candidate_quot"] = cand_out_ne_quot
            if relation == "separate_wires" and f_status == "ok":
                f_honest = export(f_witness, OUT / "honest-fixed", "export-honest-fixed")
                f_wired = {n: w for n, w in fixed_symbols.items() if w >= 0}
                hybrid = list(f_honest)
                for name, wire in f_wired.items():
                    if name in assignment:
                        hybrid[wire] = assignment[name]
                failed = unsatisfied(fixed_r1cs, hybrid)
                involves_out = [i for i in failed
                                if any(w == out_wire for lc in fixed_r1cs["constraints"][i] for w, _ in lc)]
                fix["hybrid_unsatisfied_constraints"] = len(failed)
                fix["hybrid_unsatisfied_involving_out"] = len(involves_out)
                rejects_via_out = bool(failed) and len(involves_out) == len(failed)
            else:
                rejects_via_out = relation in ("same_wire", "one_eliminated") and cand_out_ne_quot
            fix["rejects_candidate_via_out_equals_quot"] = rejects_via_out
            verdicts["B2_fix_relation"] = ("rejects_via_out_equals_quot" if rejects_via_out else "unresolved")
        else:
            verdicts["B2_fix_relation"] = "unresolved_no_fixed_artifact"
        evidence["fix"] = fix

        if verdicts["A3_general_tcct_property"] != "violated":
            verdicts["D_single_cause_attribution"] = "not_applicable"
        else:
            single = (differing == ["main.out"] and verdicts["B1_range"] == "within_range"
                      and fix.get("rejects_candidate_via_out_equals_quot") is True
                      and fix.get("fixed_honest_check") == "correct"
                      and verdicts["fix_provenance"].startswith("verified"))
            verdicts["D_single_cause_attribution"] = ("attributed_out_assigned_but_unconstrained" if single
                                                      else "unresolved_multiple_or_unclear")
        raw.update({"candidate_interface": {n: str(assignment[n]) for n in INPUTS + ["main.out", "main.quot", "main.rem"]
                                            if n in assignment}, "zkfuzz_flag": flag})
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
