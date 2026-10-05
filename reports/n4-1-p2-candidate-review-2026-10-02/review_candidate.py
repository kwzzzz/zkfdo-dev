#!/usr/bin/env python3
"""S-01: review one pre-selected P2 Subtract candidate against the fixed SCOPE.

Value-free on stdout and in tracked files. Raw candidate and witness values are
read and written only under the ignored run directory. No fuzzing is performed.
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
SCOPE = (ROOT / "reports/n4-1-p2-candidate-review-2026-10-02/SCOPE.md",
         "24cec8f8fbdb8747cbf68d42722994890ec2a8ef019ada4d851627c2fde7da76")
P2 = ROOT / "runs/dev-rq1-pilot-2026-09-29/inference-main"
EXECUTION = P2 / "campaign/small-first/block-1/execution/execution-dea86966-f3b8-425b-b67c-607073d18d40"
CANDIDATE = (EXECUTION / "counterexample-candidates/0002/src__subtractTensor__Subtract.circom_VtOrmtp2AL_counterexample.json",
             "38554c0e4c67fa529044ef8516dee5812a5a28145f72137aa44ddc94a0c80a25")
OUTCOME = (EXECUTION / "outcome.json", "a84ed78074bb885c74bf22e1b1e2835b3465b4db2ccead4325269e043b3a27e0")
PLAN = (P2 / "campaign/small-first/block-1/plan.json", "b8843d8b816c6b36934556a98b78d75f711f714212015688e3b0025e76e1cc7f")
PREPARE = P2 / "prepared/small-first/prepare-099c7c89-5866-43fc-9e72-49beac54420d"
PREPARED = (PREPARE / "prepared.json", "da6b439618f1250c9d55cf6319dc6a04cc10ae251c87bbe7215cacd31b244122")
TARGET = PREPARE / "targets/0019"
VULN_SOURCE = (TARGET / "sources/src/subtractTensor.circom",
               "502ee44b70a368066fafcf09cc2d0356479f8a862bfa726bde8097c728c83cc1")
VULN_WRAPPER = (TARGET / "sources/zkfdo-targets/src__subtractTensor__Subtract.circom",
                "1665e793a060f63336a8256b48b789915897b8eeb40d65f60118dd5605068c7b")
PREPARED_R1CS = (TARGET / "structure/r1cs/src__subtractTensor__Subtract.r1cs",
                 "14c18b08f5697b259526002cb217552c0a08ddc236fdb357bee2f40409cfb04f")
FIX_SOURCE = (ROOT / "datasets/controlled-v1/subtract/fixed/subtractTensor.circom",
              "c5d6aa9de7e95f09283e6b014dcbda85e16e583c3e157d7f8fdd95bb001023ba")
FIX_WRAPPER = (ROOT / "datasets/controlled-v1/subtract/fixed/circuit.circom",
               "5160da57762a5a561cf797a44f2dd6f009126536be476cbcec0926459362e079")
RUN_ID = "5be06d85-4440-4c29-aaa9-1307c54d8ba0"
TARGET_ID = "sha256:1830b5991e7c31effb5249dccfc0f125fa1e5cc8099cfcdb5dc7d0e9bde75cb3"
LIBRARIES = [P2 / "tree", ROOT / ".external/zkbugs/dataset/circom/dependencies",
             ROOT / ".external/zkbugs/dataset/circom/dependencies/circomlib"]
TOOLS = {"circom": (Path("/Users/miiz/.cargo/bin/circom"),
                    "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"),
         "node": (Path("/opt/homebrew/Cellar/node/26.0.0/bin/node"),
                  "08dad0581f00a0cabf4d49ec92ca1f25fdfd01c2c18fa8e92b35f04d4c24c164"),
         "snarkjs": (Path("/opt/homebrew/lib/node_modules/snarkjs/build/cli.cjs"),
                     "6d787e37a4d1a2c6dd6032dadca09c0b3b007d4d4578bb6232a98136555d051a")}
SIGNALS = ["main.a", "main.b", "main.c", "main.d"]
OUT = ROOT / "runs/n4-1-p2-candidate-review-2026-10-02/run-v1"


class Stop(Exception):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned(item):
    path, expected = item
    if not Path(path).is_file() or sha(path) != expected:
        raise Stop(f"hash mismatch or missing: {Path(path).relative_to(ROOT)}")
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
    wall = time.perf_counter() - started
    stdout.write_text(out if isinstance(out, str) else out.decode())
    stderr.write_text(err if isinstance(err, str) else err.decode())
    LEDGER.append({"index": index, "stage": stage, "args": [str(a) for a in args], "exit_code": code,
                   "timed_out": timed_out, "wall_seconds": wall,
                   "stdout": {"path": str(stdout.relative_to(ROOT)), "sha256": sha(stdout)},
                   "stderr": {"path": str(stderr.relative_to(ROOT)), "sha256": sha(stderr)}})
    return code == 0 and not timed_out, (out if isinstance(out, str) else out.decode())


def read_r1cs(path):
    data = Path(path).read_bytes()
    if data[:4] != b"r1cs":
        raise Stop("not an r1cs file")
    version, sections = struct.unpack_from("<II", data, 4)
    offset, header, constraints_raw = 12, None, None
    for _ in range(sections):
        kind, size = struct.unpack_from("<IQ", data, offset)
        offset += 12
        body = data[offset:offset + size]
        offset += size
        if kind == 1:
            header = body
        elif kind == 2:
            constraints_raw = body
    n8 = struct.unpack_from("<I", header, 0)[0]
    prime = int.from_bytes(header[4:4 + n8], "little")
    wires, outputs, pub_in, prv_in = struct.unpack_from("<IIII", header, 4 + n8)
    labels, count = struct.unpack_from("<QI", header, 4 + n8 + 16)
    if prime != PRIME:
        raise Stop("unexpected R1CS prime")
    constraints, pos = [], 0
    for _ in range(count):
        triple = []
        for _ in range(3):
            terms = struct.unpack_from("<I", constraints_raw, pos)[0]
            pos += 4
            lc = []
            for _ in range(terms):
                wire = struct.unpack_from("<I", constraints_raw, pos)[0]
                coefficient = int.from_bytes(constraints_raw[pos + 4:pos + 4 + n8], "little")
                pos += 4 + n8
                if wire >= wires:
                    raise Stop("invalid wire in R1CS")
                lc.append((wire, coefficient))
            triple.append(lc)
        constraints.append(triple)
    return {"wires": wires, "outputs": outputs, "public_inputs": pub_in, "private_inputs": prv_in,
            "constraints": constraints, "n8": n8}


def evaluate(r1cs, witness):
    """Return the indices of unsatisfied constraints for a complete witness vector."""
    failed = []
    for index, (a, b, c) in enumerate(r1cs["constraints"]):
        value = lambda lc: sum(coef * witness[wire] for wire, coef in lc) % PRIME
        if value(a) * value(b) % PRIME != value(c):
            failed.append(index)
    return failed


def read_sym(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        label, wire, component, name = line.split(",", 3)
        int(label), int(component)
        if name in result:
            raise Stop(f"duplicate symbol {name}")
        result[name] = int(wire)
    return result


def write_wtns(path, values):
    n8 = 32
    header = struct.pack("<I", n8) + PRIME.to_bytes(n8, "little") + struct.pack("<I", len(values))
    body = b"".join(v.to_bytes(n8, "little") for v in values)
    data = b"wtns" + struct.pack("<II", 2, 2)
    data += struct.pack("<IQ", 1, len(header)) + header + struct.pack("<IQ", 2, len(body)) + body
    Path(path).write_bytes(data)


def vector(symbols, wires, assignment):
    """Complete witness vector from named values; every wire must be named exactly once."""
    values = {0: 1}
    for name, value in assignment.items():
        wire = symbols.get(name)
        if wire is None or wire < 0 or wire >= wires or wire in values:
            raise Stop(f"signal mapping failed for {name}")
        values[wire] = value
    if set(values) != set(range(wires)):
        raise Stop("assignment does not cover every R1CS wire")
    return [values[i] for i in range(wires)]


def snark_check(r1cs_path, wtns_path, stage, cwd):
    ok, out = run(stage, [TOOLS["node"][0], TOOLS["snarkjs"][0], "wtns", "check", r1cs_path, wtns_path], cwd)
    return ok and "WITNESS IS CORRECT" in out


def compile_circuit(wrapper, folder, stage):
    folder.mkdir(parents=True)
    args = [TOOLS["circom"][0], wrapper, "--r1cs", "--prime", "bn128", "--output", folder]
    for library in LIBRARIES:
        args += ["-l", library]
    args += ["--sym", "--wasm"]
    ok, _ = run(stage, args, wrapper.parent)
    if not ok:
        raise Stop(f"{stage} failed")
    stem = wrapper.stem
    return {"r1cs": folder / f"{stem}.r1cs", "sym": folder / f"{stem}.sym",
            "wasm": folder / f"{stem}_js/{stem}.wasm", "generator": folder / f"{stem}_js/generate_witness.js"}


def main():
    started_wall = time.time()
    started = time.perf_counter()
    pinned(SCOPE)
    OUT.mkdir(parents=True, exist_ok=False)
    subprocess.run(["git", "check-ignore", "--quiet", str(OUT)], cwd=ROOT, check=True)
    (OUT / "logs").mkdir()
    verdicts = {"binding": "not_run", "original_constraints": "not_run", "normal_difference": "not_run",
                "property_violation": "not_run", "cause_attribution": "not_run", "spec_consistency": "not_run",
                "caller_context": "unresolved_not_reviewed", "entrypoint_tcct": "unresolved_not_reviewed",
                "project_semantics": "unresolved_not_reviewed"}
    notes, evidence = [], {}
    raw = {}
    try:
        # Step 0: binding of candidate to the recorded run/target and pinned sources.
        for name, (path, _) in TOOLS.items():
            pinned(TOOLS[name])
        candidate_path, outcome_path, plan_path = pinned(CANDIDATE), pinned(OUTCOME), pinned(PLAN)
        pinned(PREPARED), pinned(VULN_SOURCE), pinned(VULN_WRAPPER), pinned(PREPARED_R1CS)
        pinned(FIX_SOURCE), pinned(FIX_WRAPPER)
        outcome = json.loads(outcome_path.read_text())
        entries = [c for c in outcome["counterexample_candidates"] if c["preserved_path"] == str(candidate_path)]
        runs = {r["result"]["run_id"]: r for r in outcome["scheduler"]["runs"] if r.get("result")}
        plan = json.loads(plan_path.read_text())
        plan_targets = {t["target_id"] for t in plan["targets"]}
        binding_ok = (len(entries) == 1 and entries[0]["sha256"] == CANDIDATE[1]
                      and entries[0]["run_id"] == RUN_ID and entries[0]["target_id"] == TARGET_ID
                      and RUN_ID in runs and runs[RUN_ID]["target_id"] == TARGET_ID
                      and runs[RUN_ID]["result"]["status"] == "bug_found" and TARGET_ID in plan_targets
                      and outcome["plan_sha256"] == PLAN[1])
        verdicts["binding"] = "passed" if binding_ok else "failed"
        if not binding_ok:
            raise Stop("candidate binding failed")

        # Recompile the pinned vulnerable snapshot and the fixed comparator.
        vuln = OUT / "vulnerable"
        (vuln / "src").mkdir(parents=True)
        (vuln / "zkfdo-targets").mkdir()
        shutil.copy2(VULN_SOURCE[0], vuln / "src/subtractTensor.circom")
        shutil.copy2(VULN_WRAPPER[0], vuln / "zkfdo-targets" / VULN_WRAPPER[0].name)
        fixed = OUT / "fixed"
        fixed.mkdir()
        shutil.copy2(FIX_SOURCE[0], fixed / "subtractTensor.circom")
        shutil.copy2(FIX_WRAPPER[0], fixed / "circuit.circom")
        v = compile_circuit(vuln / "zkfdo-targets" / VULN_WRAPPER[0].name, OUT / "compiled-vulnerable", "compile-vulnerable")
        f = compile_circuit(fixed / "circuit.circom", OUT / "compiled-fixed", "compile-fixed")
        evidence["recompiled_vulnerable_r1cs_sha256"] = sha(v["r1cs"])
        evidence["recompiled_fixed_r1cs_sha256"] = sha(f["r1cs"])
        if sha(v["r1cs"]) != PREPARED_R1CS[1]:
            raise Stop("recompiled R1CS differs from the prepared R1CS")
        r1cs, fixed_r1cs = read_r1cs(v["r1cs"]), read_r1cs(f["r1cs"])
        symbols, fixed_symbols = read_sym(v["sym"]), read_sym(f["sym"])
        evidence["vulnerable_r1cs_shape"] = {k: r1cs[k] for k in ("wires", "outputs", "public_inputs", "private_inputs")} | {"constraints": len(r1cs["constraints"])}
        evidence["fixed_r1cs_shape"] = {k: fixed_r1cs[k] for k in ("wires", "outputs", "public_inputs", "private_inputs")} | {"constraints": len(fixed_r1cs["constraints"])}

        # Step 1: the candidate's complete assignment against every original constraint.
        candidate = json.loads(candidate_path.read_text())
        evidence["candidate_top_level_keys"] = sorted(candidate)
        if "7_assignment" not in candidate:
            verdicts["original_constraints"] = "unresolved"
            raise Stop("candidate has no assignment field")
        try:
            assignment = {name: int(value) for name, value in candidate["7_assignment"].items()}
        except (TypeError, ValueError):
            verdicts["original_constraints"] = "unresolved"
            raise Stop("candidate assignment is not decimal field values")
        if sorted(assignment) != sorted(SIGNALS) or sorted(n for n in symbols if n != "one") != sorted(SIGNALS):
            verdicts["original_constraints"] = "unresolved"
            raise Stop("candidate or symbol names differ from main.a/b/c/d")
        canonical = all(0 <= x < PRIME for x in assignment.values())
        if not canonical:
            verdicts["original_constraints"] = "unresolved"
            raise Stop("non-canonical candidate value")
        cand_vector = vector(symbols, r1cs["wires"], assignment)
        python_failed = evaluate(r1cs, cand_vector)
        write_wtns(OUT / "candidate.wtns", cand_vector)
        snark_ok = snark_check(v["r1cs"], OUT / "candidate.wtns", "check-candidate-original", OUT)
        python_ok = not python_failed
        evidence["candidate_wtns_sha256"] = sha(OUT / "candidate.wtns")
        evidence["original_constraint_methods"] = {"python_r1cs_evaluator": python_ok, "snarkjs_wtns_check": snark_ok}
        if python_ok and snark_ok:
            verdicts["original_constraints"] = "passed"
        elif not python_ok and not snark_ok:
            verdicts["original_constraints"] = "failed"
            raise Stop("candidate does not satisfy the original constraints")
        else:
            verdicts["original_constraints"] = "unresolved"
            raise Stop("constraint check methods disagree")

        # Step 2: honest recomputation for the same inputs.
        a, b = assignment["main.a"], assignment["main.b"]
        honest_dir = OUT / "honest"
        honest_dir.mkdir()
        (honest_dir / "input.json").write_text(json.dumps({"a": str(a), "b": str(b)}) + "\n")
        ok, _ = run("honest-calculate", [TOOLS["node"][0], v["generator"], v["wasm"], honest_dir / "input.json",
                                         honest_dir / "honest.wtns"], honest_dir)
        if not ok or not (honest_dir / "honest.wtns").is_file():
            verdicts["normal_difference"] = "abort_or_failure"
            raise Stop("honest computation did not complete")
        honest_check = snark_check(v["r1cs"], honest_dir / "honest.wtns", "check-honest-original", honest_dir)
        ok, _ = run("honest-export", [TOOLS["node"][0], TOOLS["snarkjs"][0], "wtns", "export", "json",
                                      honest_dir / "honest.wtns", honest_dir / "honest.json"], honest_dir)
        if not ok or not honest_check:
            verdicts["normal_difference"] = "unresolved"
            raise Stop("honest witness check or export failed")
        honest_vector = [int(x) for x in json.loads((honest_dir / "honest.json").read_text())]
        honest = {name: honest_vector[symbols[name]] for name in SIGNALS}
        # Positive control for the local .wtns writer used for the candidate checks.
        write_wtns(honest_dir / "honest-rewritten.wtns", honest_vector)
        evidence["wtns_writer_control_passed"] = snark_check(v["r1cs"], honest_dir / "honest-rewritten.wtns",
                                                             "check-writer-control", honest_dir)
        if not evidence["wtns_writer_control_passed"]:
            verdicts["original_constraints"] = "unresolved"
            raise Stop("local wtns writer control failed")
        source_semantics = {"main.a": a, "main.b": b, "main.c": (a - b) % PRIME, "main.d": 1}
        evidence["honest_wtns_sha256"] = sha(honest_dir / "honest.wtns")
        evidence["honest_matches_source_semantics"] = honest == source_semantics
        if honest != source_semantics:
            verdicts["normal_difference"] = "unresolved"
            raise Stop("honest witness disagrees with source semantics")
        differing = sorted(name for name in SIGNALS if assignment[name] != honest[name])
        evidence["differing_signals"] = differing
        verdicts["normal_difference"] = "output_differs" if "main.c" in differing else "no_output_difference"

        # Separate consistency with the existing specification c = a - b mod p.
        verdicts["spec_consistency"] = "passed" if honest["main.c"] == (a - b) % PRIME else "failed"

        # Step 3: predeclared general TCCT property.
        verdicts["property_violation"] = ("violated" if verdicts["normal_difference"] == "output_differs"
                                          else "not_violated")

        # Step 4: attribution to the known unconstrained multiplier cause.
        only_d_and_c = set(differing) <= {"main.c", "main.d"} and "main.d" in differing
        inputs_differ = a != b
        fixed_names = sorted(n for n in fixed_symbols if n != "one")
        evidence["fixed_symbol_names"] = fixed_names
        if fixed_names != ["main.a", "main.b", "main.c"]:
            verdicts["cause_attribution"] = "unresolved"
            raise Stop("fixed comparator interface differs")
        fixed_candidate = vector(fixed_symbols, fixed_r1cs["wires"], {k: assignment[k] for k in fixed_names})
        fixed_honest = vector(fixed_symbols, fixed_r1cs["wires"], {k: honest[k] for k in fixed_names})
        write_wtns(OUT / "fixed-candidate.wtns", fixed_candidate)
        write_wtns(OUT / "fixed-honest.wtns", fixed_honest)
        rejection = {"python_rejects_candidate": bool(evaluate(fixed_r1cs, fixed_candidate)),
                     "snarkjs_rejects_candidate": not snark_check(f["r1cs"], OUT / "fixed-candidate.wtns", "check-candidate-fixed", OUT),
                     "python_accepts_honest": not evaluate(fixed_r1cs, fixed_honest),
                     "snarkjs_accepts_honest": snark_check(f["r1cs"], OUT / "fixed-honest.wtns", "check-honest-fixed", OUT)}
        evidence["fixed_comparator_checks"] = rejection
        evidence["attribution_conditions"] = {"difference_limited_to_d_and_c_with_d_changed": only_d_and_c,
                                              "inputs_differ": inputs_differ,
                                              "fixed_constraint_rejection_with_honest_control": all(rejection.values())}
        verdicts["cause_attribution"] = ("attributed" if verdicts["property_violation"] == "violated"
                                         and only_d_and_c and inputs_differ and all(rejection.values())
                                         else "unresolved")
        raw.update({"assignment": {k: str(v) for k, v in assignment.items()},
                    "honest": {k: str(v) for k, v in honest.items()},
                    "zkfuzz_reported_fields": {k: candidate[k] for k in candidate if k != "7_assignment"}})
    except Stop as error:
        notes.append(str(error))
    finally:
        evidence["review_tool_wall_seconds"] = time.perf_counter() - started
        evidence["review_started_at_unix"] = started_wall
        (OUT / "raw-values.json").write_text(json.dumps(raw, indent=2) + "\n")
        (OUT / "ledger.json").write_text(json.dumps(LEDGER, indent=2) + "\n")
        result = {"verdicts": verdicts, "notes": notes, "evidence": evidence,
                  "ledger": {"path": str((OUT / "ledger.json").relative_to(ROOT)), "sha256": sha(OUT / "ledger.json")},
                  "raw_values": {"path": str((OUT / "raw-values.json").relative_to(ROOT)), "sha256": sha(OUT / "raw-values.json")},
                  "process_wall_seconds_sum": sum(item["wall_seconds"] for item in LEDGER),
                  "processes": [{k: item[k] for k in ("index", "stage", "exit_code", "timed_out", "wall_seconds")} for item in LEDGER]}
        (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"verdicts": verdicts, "notes": notes,
                          "result_sha256": sha(OUT / "result.json")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
