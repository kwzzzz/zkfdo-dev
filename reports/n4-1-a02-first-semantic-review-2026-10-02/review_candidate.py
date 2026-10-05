#!/usr/bin/env python3
"""S-05: review the first A-02 candidate occurrence, Subtract(), against the fixed SCOPE.

Layers: A general TCCT (component), B actual fix, C zkFuzz label, D single-cause attribution,
S same cause as S-01, E call-site reachability and entrypoint projection, T first confirmed
target time. Stdout and tracked files are value-free; raw values, projection inputs and the
value-bearing hint generator stay under the ignored run directory. No fuzzing or search.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCOPE = (HERE / "SCOPE.md", "20444675ca7cd0299ea5b706728e3da129e9525a8b8d22ee7f8a8358c42748bf")
PREP_SCRIPT = (HERE / "prepare_context.py", "9f8d6bae912e4477924b6b2034402fe9287d349f531d409400296bd51792099a")
PREP_DIR = ROOT / "runs/n4-1-a02-first-semantic-review-2026-10-02/prep-v1"
PREP_RECORD = (PREP_DIR / "prep.json", "362ef99bd1a3c29fbaa53e5f58cf03f30c7d29d1e03e4e739e331824bc1dc8d3")
BASE_INPUT = (PREP_DIR / "base/input.json", "13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca")
OUT = ROOT / "runs/n4-1-a02-first-semantic-review-2026-10-02/run-v1"
WRAPPER = "zkfdo-targets/src__subtractTensor__Subtract.circom"
SOURCE_ORDER = ["main.a", "main.b", "main.d", "main.c"]
S01 = {"vulnerable_r1cs": "14c18b08f5697b259526002cb217552c0a08ddc236fdb357bee2f40409cfb04f",
       "source": "502ee44b70a368066fafcf09cc2d0356479f8a862bfa726bde8097c728c83cc1",
       "fix_source": "c5d6aa9de7e95f09283e6b014dcbda85e16e583c3e157d7f8fdd95bb001023ba",
       "fixed_r1cs": "842a28ea3c545079f8802e5593bc4d13de4e19f0f453ed432ed77929d9240ac8"}
CONSTANT = 50000000
HINT = "    d <-- 1;\n"
PROJECTIONS = {"K1": ("main.response_time_normalized_fn[0].subtract1", ["response_time", "minimum_response_time"]),
               "K2": ("main.response_time_normalized_fn[0].subtract2", ["maximum_response_time", "minimum_response_time"])}
S04_ATTEMPT = 8


class Stop(Exception):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned(path, expected):
    if not Path(path).is_file() or sha(path) != expected:
        raise Stop(f"hash mismatch or missing: {Path(path).name}")
    return Path(path)


for item in (SCOPE, PREP_SCRIPT, PREP_RECORD, BASE_INPUT):
    pinned(*item)
sys.path.insert(0, str(HERE))
import prepare_context as prep  # noqa: E402  (pinned above)

PRIME, TOOLS, TREE = prep.PRIME, prep.TOOLS, prep.TREE
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


def snark_verdict(r1cs_path, wtns_path, stage, cwd, timeout=60):
    """Only explicit diagnostics count: correct, not_correct, otherwise error."""
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
    for library in prep.LIBRARIES:
        args += ["-l", library]
    code, _, _, timed_out = run(stage, args + ["--sym", "--wasm"], source.parent, timeout)
    if code != 0 or timed_out:
        raise Stop(f"{stage} failed")
    stem = source.stem
    return {"r1cs": folder / f"{stem}.r1cs", "sym": folder / f"{stem}.sym",
            "wasm": folder / f"{stem}_js/{stem}.wasm", "generator": folder / f"{stem}_js/generate_witness.js"}


def calculate(artifacts, inputs, folder, stage, timeout=60):
    """Return (status, witness vector or None, abort trace) with status ok, assert_abort or error."""
    folder.mkdir(parents=True)
    (folder / "input.json").write_text(json.dumps(inputs) + "\n")
    code, _, err, timed_out = run(stage, [TOOLS["node"][0], artifacts["generator"], artifacts["wasm"],
                                          folder / "input.json", folder / "witness.wtns"], folder, timeout)
    trace = re.findall(r"Error in template (\S+) line: (\d+)", err)
    if code == 0 and not timed_out and (folder / "witness.wtns").is_file():
        return "ok", prep.read_wtns(folder / "witness.wtns"), trace
    return ("assert_abort" if not timed_out and "Assert Failed" in err else "error"), None, trace


def write_wtns(path, values):
    header = struct.pack("<I", 32) + PRIME.to_bytes(32, "little") + struct.pack("<I", len(values))
    body = b"".join(v.to_bytes(32, "little") for v in values)
    Path(path).write_bytes(b"wtns" + struct.pack("<II", 2, 2) + struct.pack("<IQ", 1, len(header)) + header
                           + struct.pack("<IQ", 2, len(body)) + body)


def vector_from(symbols, assignment, wires):
    """Strict mapping: every wired name present, aliases agree, canonical values, full coverage."""
    values, missing, conflict = {0: 1}, [], False
    for name, wire in symbols.items():
        if wire < 0:
            continue
        if name not in assignment:
            missing.append(name)
            continue
        if wire in values and values[wire] != assignment[name]:
            conflict = True
        values.setdefault(wire, assignment[name])
    canonical = all(0 <= assignment[n] < PRIME for n in symbols if n in assignment)
    if missing or conflict or not canonical or set(values) != set(range(wires)):
        return None, {"missing_wired_names": len(missing), "alias_conflict": conflict, "canonical": canonical}
    return [values[i] for i in range(wires)], None


def check_both(r1cs, vector, wtns_path, stage, cwd, timeout=60):
    write_wtns(wtns_path, vector)
    return {"python_unsatisfied": prep.count_unsatisfied(r1cs, vector),
            "snarkjs": snark_verdict(r1cs, wtns_path, stage, cwd, timeout), "wtns_sha256": sha(wtns_path)}


def first_bounds(ledger, attempt_index):
    attempt = ledger["attempts"][attempt_index]
    offsets = [o["campaign_offset_seconds"] for o in attempt["log_observations"] if o["kind"] == "not_safe"]
    return {"attempt": attempt_index, "lower_bound_process_start": attempt["process_start_offset_seconds"],
            "observation_upper_bound_parent_not_safe": min(offsets),
            "file_existence_upper_bound_completion": attempt["completion_offset_seconds"]}


def main():
    started = time.perf_counter()
    prep_record = json.loads(PREP_RECORD[0].read_text())
    OUT.mkdir(parents=True, exist_ok=False)
    subprocess.run(["git", "check-ignore", "--quiet", str(OUT)], cwd=ROOT, check=True)
    (OUT / "logs").mkdir()
    names = ["selection_and_binding", "recompile_matches_prep", "A1_original_constraints", "A2_honest_relation",
             "A3_general_tcct_property", "B1_fix_rejects_candidate", "B2_fix_accepts_honest_control",
             "B3_fix_honest_computation", "C_tool_label", "D_single_cause_attribution", "S_same_cause_as_S01",
             "E2_reachability", "E3_projection", "E4_entrypoint_tcct", "E5_project_semantics", "T_first_confirmed_time"]
    verdicts = {n: "not_run" for n in names}
    verdicts["E5_project_semantics"] = "unresolved_not_judged"
    notes, evidence, raw = [], {}, {}
    try:
        for name in TOOLS:
            pinned(*TOOLS[name])
        ok, checks, timing = prep.selection_check()
        evidence["selection_checks"], evidence["attempt1_timing"] = checks, timing
        verdicts["selection_and_binding"] = "passed" if ok else "failed"
        if not ok:
            raise Stop("selection re-check failed")

        # Recompile everything and compare with the value-free preparation record.
        sub = compile_circuit(TREE / WRAPPER, OUT / "compiled-subtract", "compile-subtract", TREE)
        blob, fixed_bytes = prep.blob_at(prep.FIX_COMMIT, "src/subtractTensor.circom")
        fixed_tree = OUT / "fixed-tree"
        (fixed_tree / "src").mkdir(parents=True)
        (fixed_tree / "zkfdo-targets").mkdir()
        (fixed_tree / "src/subtractTensor.circom").write_bytes(fixed_bytes)
        shutil.copy2(TREE / WRAPPER, fixed_tree / "zkfdo-targets/")
        fix = compile_circuit(fixed_tree / WRAPPER, OUT / "compiled-subtract-fixed", "compile-subtract-fixed", fixed_tree)
        entry = compile_circuit(TREE / "src/circuit.circom", OUT / "compiled-entry", "compile-entry", TREE, 600)
        matches = {"subtract_r1cs": sha(sub["r1cs"]) == prep_record["subtract"]["r1cs_sha256"] == S01["vulnerable_r1cs"],
                   "subtract_sym": sha(sub["sym"]) == prep_record["subtract"]["sym_sha256"],
                   "fix_blob": blob == prep_record["fix"]["blob"],
                   "fix_source": hashlib.sha256(fixed_bytes).hexdigest() == prep_record["fix"]["source_sha256"],
                   "fixed_r1cs": sha(fix["r1cs"]) == prep_record["subtract"]["fixed_r1cs_sha256"],
                   "fixed_sym": sha(fix["sym"]) == prep_record["subtract"]["fixed_sym_sha256"],
                   "entry_r1cs": sha(entry["r1cs"]) == prep_record["entry"]["r1cs_sha256"],
                   "entry_sym": sha(entry["sym"]) == prep_record["entry"]["sym_sha256"],
                   "entry_wasm": sha(entry["wasm"]) == prep_record["entry"]["wasm_sha256"]}
        evidence["recompile_matches"] = matches
        verdicts["recompile_matches_prep"] = "passed" if all(matches.values()) else "failed"
        if not all(matches.values()):
            raise Stop("recompiled artifacts differ from the preparation record")

        # Candidate (first time its contents are read).
        candidate = json.loads(pinned(prep.CAMPAIGN / prep.CANDIDATE_REL, prep.CANDIDATE_SHA).read_text())
        evidence["candidate_top_level_keys"] = sorted(candidate)
        flag = candidate.get("5_flag")
        verdicts["C_tool_label"] = (flag.get("1_type") if isinstance(flag, dict) and isinstance(flag.get("1_type"), str)
                                    else "label_unavailable")
        raw["zkfuzz_flag"] = flag
        try:
            assignment = {name: int(value) for name, value in candidate["7_assignment"].items()}
        except (KeyError, TypeError, ValueError):
            verdicts["A1_original_constraints"] = "unresolved"
            raise Stop("candidate assignment missing or not decimal field values")
        raw["candidate"] = {n: str(assignment[n]) for n in SOURCE_ORDER if n in assignment}

        # A1: two independent checks of the original component R1CS.
        symbols = prep.read_sym(sub["sym"])
        shape = prep.r1cs_shape(sub["r1cs"])
        cand_vector, problem = vector_from(symbols, assignment, shape["wires"])
        evidence["symbol_counts"] = {"wired_names": sum(1 for w in symbols.values() if w >= 0),
                                     "candidate_names": len(assignment),
                                     "candidate_only_names": len(set(assignment) - set(symbols))}
        if cand_vector is None:
            verdicts["A1_original_constraints"] = "unresolved"
            evidence["A1_mapping_problem"] = problem
            raise Stop("candidate does not map to a complete canonical witness")
        a1 = check_both(sub["r1cs"], cand_vector, OUT / "candidate.wtns", "check-candidate", OUT)
        evidence["A1_methods"] = a1
        verdicts["A1_original_constraints"] = (
            "passed" if a1["python_unsatisfied"] == 0 and a1["snarkjs"] == "correct" else
            "failed" if a1["python_unsatisfied"] > 0 and a1["snarkjs"] == "not_correct" else "unresolved")

        # A2: honest computation of the same inputs, compared wire by wire.
        a, b = assignment["main.a"], assignment["main.b"]
        status, honest, trace = calculate(sub, {"a": str(a), "b": str(b)}, OUT / "honest", "honest-original")
        evidence["A2_honest_status"] = status
        differing = None
        if status == "assert_abort":
            verdicts["A2_honest_relation"] = "abort"
            evidence["A2_abort_trace"] = trace
        elif status != "ok":
            verdicts["A2_honest_relation"] = "unresolved"
        else:
            honest_check = snark_verdict(sub["r1cs"], OUT / "honest/witness.wtns", "check-honest", OUT / "honest")
            write_wtns(OUT / "honest/rewritten.wtns", honest)
            writer = snark_verdict(sub["r1cs"], OUT / "honest/rewritten.wtns", "check-writer-control", OUT / "honest")
            evidence.update({"A2_honest_snarkjs": honest_check, "wtns_writer_control": writer,
                             "honest_wtns_sha256": sha(OUT / "honest/witness.wtns"),
                             "A2_honest_python_unsatisfied": prep.count_unsatisfied(sub["r1cs"], honest)})
            if honest_check != "correct" or writer != "correct":
                verdicts["A2_honest_relation"] = "unresolved"
                if writer != "correct":
                    verdicts["A1_original_constraints"] = "unresolved"
            else:
                differing = [n for n in SOURCE_ORDER if symbols[n] >= 0
                             and cand_vector[symbols[n]] != honest[symbols[n]]]
                evidence["A2_differing_wired_signals"] = differing
                evidence["A2_first_divergence_source_order"] = differing[0] if differing else "none"
                verdicts["A2_honest_relation"] = ("output_differs" if "main.c" in differing else
                                                  "identical" if not differing else "internal_differs_output_same")
                raw["honest"] = {n: str(honest[symbols[n]]) for n in SOURCE_ORDER}
        a1v, a2v = verdicts["A1_original_constraints"], verdicts["A2_honest_relation"]
        verdicts["A3_general_tcct_property"] = (
            "not_violated_candidate_fails_constraints" if a1v == "failed" else
            "unresolved" if a1v != "passed" or a2v in ("unresolved", "not_run") else
            "violated" if a2v in ("output_differs", "abort") else "explicit_not_applicable")

        # B: the actual fix (provenance verified by the git object chain).
        fsym = prep.read_sym(fix["sym"])
        fwires = prep.r1cs_shape(fix["r1cs"])["wires"]
        fcand, fproblem = vector_from(fsym, assignment, fwires)
        if fcand is None:
            verdicts["B1_fix_rejects_candidate"] = "unresolved"
            evidence["B1_mapping_problem"] = fproblem
        else:
            b1 = check_both(fix["r1cs"], fcand, OUT / "fixed-candidate.wtns", "check-fixed-candidate", OUT)
            evidence["B1_methods"] = b1
            verdicts["B1_fix_rejects_candidate"] = (
                "rejected_both_methods" if b1["python_unsatisfied"] > 0 and b1["snarkjs"] == "not_correct" else
                "accepted_both_methods" if b1["python_unsatisfied"] == 0 and b1["snarkjs"] == "correct" else "unresolved")
        if differing is not None:
            honest_named = {n: honest[symbols[n]] for n in SOURCE_ORDER}
            fhonest, _ = vector_from(fsym, honest_named, fwires)
            b2 = check_both(fix["r1cs"], fhonest, OUT / "fixed-honest-control.wtns", "check-fixed-honest-control", OUT)
            evidence["B2_methods"] = b2
            verdicts["B2_fix_accepts_honest_control"] = (
                "accepted_both_methods" if b2["python_unsatisfied"] == 0 and b2["snarkjs"] == "correct" else
                "unresolved")
            fstatus, fvector, ftrace = calculate(fix, {"a": str(a), "b": str(b)}, OUT / "fixed-honest", "fixed-honest")
            evidence["B3_status"], evidence["B3_abort_trace"] = fstatus, ftrace
            verdicts["B3_fix_honest_computation"] = (
                "ok_output_equals_original_honest" if fstatus == "ok" and fvector[fsym["main.c"]] == honest_named["main.c"]
                else "ok_output_differs" if fstatus == "ok" else fstatus)

        # D: single-cause attribution rule fixed in SCOPE section 4.
        if verdicts["A3_general_tcct_property"] != "violated":
            verdicts["D_single_cause_attribution"] = "not_applicable"
        else:
            single = (differing == ["main.d", "main.c"] and a != b
                      and verdicts["B1_fix_rejects_candidate"] == "rejected_both_methods"
                      and verdicts["B2_fix_accepts_honest_control"] == "accepted_both_methods"
                      and verdicts["B3_fix_honest_computation"] == "ok_output_equals_original_honest"
                      and prep_record["fix"]["provenance"] == "verified_by_git_object_chain")
            verdicts["D_single_cause_attribution"] = ("attributed_subtract_unconstrained_multiplier_d" if single
                                                      else "unresolved")
        # S: same cause as S-01, from artifacts S-01 recorded and this candidate's own evidence.
        if verdicts["D_single_cause_attribution"].startswith("attributed"):
            same = {"s1_same_r1cs_bytes": sha(sub["r1cs"]) == S01["vulnerable_r1cs"],
                    "s2_same_source_site": sha(TREE / "src/subtractTensor.circom") == S01["source"],
                    "s3_same_difference_and_first_divergence": differing == ["main.d", "main.c"],
                    "s4_same_fix_rejects_and_accepts_control": (
                        hashlib.sha256(fixed_bytes).hexdigest() == S01["fix_source"]
                        and sha(fix["r1cs"]) == S01["fixed_r1cs"])}
            evidence["S_criteria"] = same
            verdicts["S_same_cause_as_S01"] = ("same_site_cause_evidence" if all(same.values()) else "unresolved")
        else:
            verdicts["S_same_cause_as_S01"] = "not_applicable"

        # E: call sites. Only for a violating component.
        if verdicts["A3_general_tcct_property"] == "violated":
            reach = {"K1": "input_level_reachable_public_inputs", "K2": "input_level_reachable_public_inputs",
                     "K3": ("unreachable_constant_b" if b != CONSTANT else "unresolved_needs_inversion"),
                     "K4": ("unreachable_constant_a" if a != CONSTANT else "unresolved_needs_inversion"),
                     "K5": "unresolved_needs_inversion"}
            verdicts["E2_reachability"] = reach
            try:
                projection = project(entry, assignment, evidence, raw)
            except Stop as error:
                # A projection failure leaves E3/E4 unresolved without stopping T.
                projection = {k: "projection_failed_setup" for k in PROJECTIONS}
                notes.append(f"E3: {error}")
            verdicts["E3_projection"] = projection
            success = [k for k, v in projection.items() if v.startswith("tcct_")]
            verdicts["E4_entrypoint_tcct"] = ("violated_via_" + "+".join(success) if success else "unresolved")
        else:
            for key in ("E2_reachability", "E3_projection", "E4_entrypoint_tcct"):
                verdicts[key] = "not_applicable"

        # T: observation bounds for the first confirmed target.
        ledger = json.loads((prep.CAMPAIGN / "ledger.json").read_text())
        a3 = verdicts["A3_general_tcct_property"]
        s04 = first_bounds(ledger, S04_ATTEMPT)
        preceding = sorted(att["attempt_index"] for att in ledger["attempts"] if att["candidates"]
                           and min(o["campaign_offset_seconds"] for o in att["log_observations"] if o["kind"] == "not_safe")
                           < s04["observation_upper_bound_parent_not_safe"])
        evidence["T_occurrences_before_S04"] = preceding
        if preceding == [1] and a3 in ("violated", "explicit_not_applicable"):
            evidence["T_bounds"] = first_bounds(ledger, 1) if a3 == "violated" else s04
            verdicts["T_first_confirmed_time"] = "computed_attempt_1" if a3 == "violated" else "computed_attempt_8"
        else:
            verdicts["T_first_confirmed_time"] = "not_computed"
    except Stop as error:
        notes.append(str(error))
    finally:
        (OUT / "raw-values.json").write_text(json.dumps(raw, indent=2) + "\n")
        (OUT / "ledger.json").write_text(json.dumps(LEDGER, indent=2) + "\n")
        result = {"verdicts": verdicts, "notes": notes, "evidence": evidence,
                  "ledger": {"path": str((OUT / "ledger.json").relative_to(ROOT)), "sha256": sha(OUT / "ledger.json")},
                  "raw_values": {"path": str((OUT / "raw-values.json").relative_to(ROOT)),
                                 "sha256": sha(OUT / "raw-values.json")},
                  "review_tool_wall_seconds": time.perf_counter() - started,
                  "process_wall_seconds_sum": sum(item["wall_seconds"] for item in LEDGER),
                  "processes": [{k: item[k] for k in ("index", "stage", "exit_code", "timed_out", "wall_seconds")}
                                for item in LEDGER]}
        (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"verdicts": verdicts, "notes": notes, "result_sha256": sha(OUT / "result.json")}, indent=2))
    return 0


def project(entry, assignment, evidence, raw):
    """E3: one fixed single-site projection per directly fed call site (K1, K2 at index 0)."""
    a, b, c, d = (assignment[n] for n in ("main.a", "main.b", "main.c", "main.d"))
    symbols = prep.read_sym(entry["sym"])
    shape = prep.r1cs_shape(entry["r1cs"])
    _, classes, _, _ = prep.enumerate_instances(symbols)
    d_wires = {p: symbols[f"{p}.d"] for items in classes.values() for _, p in items}
    folder = OUT / "projection"
    tree = folder / "hint-tree"
    shutil.copytree(TREE, tree)
    source = (tree / "src/subtractTensor.circom").read_text()
    if source.count(HINT) != 1:
        raise Stop("hint line not found exactly once")
    (tree / "src/subtractTensor.circom").write_text(source.replace(HINT, f"    d <-- (a == {a} && b == {b}) ? {d} : 1;\n"))
    hinted = compile_circuit(tree / "src/circuit.circom", folder / "compiled-hint", "compile-hint-entry", tree, 600)
    equivalent = sha(hinted["r1cs"]) == sha(entry["r1cs"]) and sha(hinted["sym"]) == sha(entry["sym"])
    evidence["E3_hint_generator"] = {"r1cs_identical": sha(hinted["r1cs"]) == sha(entry["r1cs"]),
                                     "sym_identical": sha(hinted["sym"]) == sha(entry["sym"]),
                                     "hint_source_sha256": sha(tree / "src/subtractTensor.circom")}
    base = json.loads(BASE_INPUT[0].read_text())
    outputs = range(1, shape["outputs"] + 1)
    public = range(shape["outputs"] + 1, shape["outputs"] + 1 + shape["public_inputs"])
    verdicts, details = {}, {}
    for key, (target, fields) in PROJECTIONS.items():
        x = copy.deepcopy(base)
        x[fields[0]][0], x[fields[1]][0] = str(a), str(b)
        here = folder / key
        here.mkdir()
        h_status, honest, h_trace = calculate(entry, x, here / "honest", f"{key}-honest", 600)
        info = {"honest_status": h_status, "honest_abort_trace": h_trace}
        if h_status == "ok":
            info["honest_snarkjs"] = snark_verdict(entry["r1cs"], here / "honest/witness.wtns", f"{key}-check-honest",
                                                   here, 600)
        if not equivalent:
            verdicts[key], details[key] = "projection_failed_generator_not_equivalent", info
            continue
        w_status, deviated, w_trace = calculate(hinted, x, here / "deviated", f"{key}-deviated", 600)
        info.update({"deviated_status": w_status, "deviated_abort_trace": w_trace})
        if w_status != "ok":
            verdicts[key], details[key] = "projection_failed_deviated_" + w_status, info
            continue
        moved = [p for p, wire in d_wires.items() if deviated[wire] != 1]
        info.update({
            "deviated_python_unsatisfied": prep.count_unsatisfied(entry["r1cs"], deviated),
            "deviated_snarkjs": snark_verdict(entry["r1cs"], here / "deviated/witness.wtns", f"{key}-check-deviated",
                                              here, 600),
            "deviated_instances": len(moved), "deviated_instance_is_target": moved == [target],
            "target_d_equals_candidate": deviated[d_wires[target]] == d,
            "target_c_equals_candidate": (deviated[symbols[f"{target}.c"]] == c if symbols[f"{target}.c"] >= 0
                                          else "c_eliminated_implied_by_constraint"),
            "fed_inputs_equal_candidate": (deviated[symbols[f"main.{fields[0]}[0]"]] == a
                                           and deviated[symbols[f"main.{fields[1]}[0]"]] == b)})
        valid = (info["deviated_python_unsatisfied"] == 0 and info["deviated_snarkjs"] == "correct"
                 and info["deviated_instance_is_target"] and info["target_d_equals_candidate"]
                 and info["target_c_equals_candidate"] is not False and info["fed_inputs_equal_candidate"])
        if h_status == "ok":
            info["public_inputs_identical"] = all(honest[i] == deviated[i] for i in public)
            changed = [i for i in outputs if honest[i] != deviated[i]]
            info["differing_outputs"] = len(changed)
            info["differing_wires"] = sum(1 for i in range(shape["wires"]) if honest[i] != deviated[i])
            raw.setdefault("projection", {})[key] = {"differing_output_wires": changed[:16]}
        if not valid:
            verdict = "projection_failed_checks"
        elif h_status == "ok" and info.get("honest_snarkjs") == "correct" and info["public_inputs_identical"]:
            verdict = "tcct_output_difference" if info["differing_outputs"] else "projected_outputs_identical"
        elif h_status == "assert_abort":
            verdict = "tcct_abort_type"
        else:
            verdict = "projection_failed_honest_unresolved"
        verdicts[key], details[key] = verdict, info
    evidence["E3_details"] = details
    return verdicts


if __name__ == "__main__":
    sys.exit(main())
