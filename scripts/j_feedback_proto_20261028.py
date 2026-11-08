#!/usr/bin/env python3
"""Development-only J→S restricted-input prototype on a tiny synthetic circuit.

This runner deliberately does not claim an exact zkFuzz input-corpus hook. It
holds a child input constant in a generated wrapper, unwraps S's candidate,
and judges it against the unmodified component and original parent with J.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from s_round4_synthetic_20261027 import parse_r1cs


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "runs/j-feedback-2026-10-28/prototype"
J = ROOT / "runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development"
J_SHA = "05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700"
SEED = 2026102801
CAP = 30.0
FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def run(command: list[str], folder: Path, deadline: float) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    remaining = deadline - start
    if remaining <= 0:
        return {"status": "budget_exhausted", "seconds": 0.0, "command": command}
    with (folder / "stdout.log").open("w") as stdout, (folder / "stderr.log").open("w") as stderr:
        proc = subprocess.Popen(["nice", "-n", "19", *command], stdout=stdout,
                                stderr=stderr, start_new_session=True)
        try:
            code = proc.wait(timeout=remaining)
            status = "ok" if code == 0 else f"exit_{code}"
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            status = "timeout"
    return {"status": status, "seconds": time.monotonic() - start, "command": command}


def source_files(folder: Path, target_form: str, probe_offset: int) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    component = folder / "components.circom"
    target_value = 5 - probe_offset
    target_gate = (f"x - {target_value}" if target_form == "direct"
                   else f"x * x - {target_value * target_value}")
    component.write_text("""pragma circom 2.2.1;
template Probe() {
  signal input x;
  signal output out;
  signal t;
  t <== x - 5;
  out <-- x + 1;
  (out - x - 1) * t === 0;
}
template Target() {
  signal input x;
  signal output out;
  signal t;
  t <== GATE;
  out <-- x + 2;
  (out - x - 2) * t === 0;
}
""".replace("GATE", target_gate))
    probe = folder / "probe.circom"
    probe.write_text('pragma circom 2.2.1;\ninclude "components.circom";\ncomponent main {public [x]} = Probe();\n')
    target = folder / "target.circom"
    target.write_text('pragma circom 2.2.1;\ninclude "components.circom";\ncomponent main {public [x]} = Target();\n')
    entry = folder / "entry.circom"
    entry.write_text("""pragma circom 2.2.1;
include "components.circom";
template Top() {
  signal input x;
  signal output out;
  component probe = Probe();
  component target = Target();
  probe.x <== x + OFFSET;
  target.x <== x;
  out <== target.out;
}
component main {public [x]} = Top();
""".replace("OFFSET", str(probe_offset)))
    return {"component": component, "probe": probe, "target": target, "entry": entry}


def fixed_wrapper(folder: Path, value: int) -> Path:
    path = folder / f"target-fixed-{value}.circom"
    path.write_text(f"""pragma circom 2.2.1;
include "components.circom";
template FixedTarget() {{
  signal output out;
  component child = Target();
  child.x <== {value};
  out <== child.out;
}}
component main = FixedTarget();
""")
    return path


def compile_o0(source: Path, folder: Path, deadline: float) -> tuple[dict, int | None]:
    result = run([shutil.which("circom") or "circom", str(source), "--r1cs", "--sym",
                  "--O0", "--output", str(folder)], folder / "command", deadline)
    if result["status"] != "ok":
        raise RuntimeError(f"compile failed: {source} ({result['status']})")
    r1cs = folder / f"{source.stem}.r1cs"
    count = parse_r1cs(r1cs.read_bytes())["shape"]["constraints"] if r1cs.is_file() else None
    if count is not None and count > 1000:
        raise RuntimeError("synthetic circuit exceeds 1000 O0 constraints")
    return result, count


def candidate_files(source: Path) -> list[Path]:
    return sorted(source.parent.glob(source.name + "_*counterexample.json"))


def s_run(source: Path, folder: Path, deadline: float,
          seed: int) -> tuple[dict, Path | None]:
    setting = folder / "settings.json"
    write_json(setting, {"seed": seed, "program_population_size": 4,
                         "input_population_size": 4, "max_generations": 100})
    result = run([str(Path.home() / ".cargo/bin/zkfuzz"), str(source), "--prime", "bn128",
                  "--search_mode", "ga", "--path_to_mutation_setting", str(setting),
                  "--save_output"], folder, deadline)
    candidates = candidate_files(source)
    if len(candidates) > 1:
        raise RuntimeError(f"ambiguous S candidate order: {source}")
    if result["status"] != "ok":
        raise RuntimeError(f"S failed: {source} ({result['status']})")
    return result, candidates[0] if candidates else None


def unwrap_candidate(candidate: Path, target: str, value: int | None) -> dict[str, str]:
    assignment = json.loads(candidate.read_text())["7_assignment"]
    if value is None:
        mapped = {k: str(v) for k, v in assignment.items() if k.startswith("main.")}
    else:
        mapped = {"main.x": str(value)}
        mapped.update({("main." + k[len("main.child."):]): str(v)
                       for k, v in assignment.items() if k.startswith("main.child.")})
    if not {"main.x", "main.out"}.issubset(mapped):
        raise RuntimeError(f"{target}: S assignment lacks child x/out")
    if value is not None and int(mapped["main.x"]) != value:
        raise RuntimeError("fixed wrapper did not pass exact child input")
    return mapped


def j_run(source: dict[str, Path], target: str, assignment: dict[str, str],
          folder: Path, deadline: float, base_x: int) -> tuple[dict, dict | None]:
    candidate = folder / "candidate.json"
    write_json(candidate, assignment)
    base_input = folder / "base-input.json"
    write_json(base_input, {"x": str(base_x)})
    request = folder / "request.json"
    write_json(request, {"schema": "zkfdo-lifting-request-v1",
                         "id": f"n7-{target}-{folder.parent.name}",
                         "source_root": str(source["component"].parent),
                         "library_paths": [],
                         "component_wrapper": str(source[target]),
                         "entrypoint": str(source["entry"]),
                         "base_input": str(base_input),
                         "candidate": {"format": "named", "path": str(candidate)}})
    command = [str(J), "--request", str(request), "--output", str(folder / "result"),
               "--cache", str(folder / "cache"), "--instance-store", str(folder / "store")]
    for tool in ("circom", "node", "snarkjs", "z3"):
        found = shutil.which(tool)
        if not found:
            raise RuntimeError(f"missing {tool}")
        command += [f"--{tool}-bin", found]
    result = run(command, folder / "command", deadline)
    if result["status"] != "ok":
        raise RuntimeError(f"J failed: {target} ({result['status']})")
    output = folder / "result/result.json"
    return result, json.loads(output.read_text()) if output.is_file() else None


def validated_input(j: dict | None, folder: Path, candidate: dict[str, str],
                    probe_offset: int) -> int | None:
    if not j or j.get("preparation", {}).get("status") != "ok":
        return None
    for item in j.get("classes", []):
        if (item.get("pattern") == "main.probe" and
                item.get("verdict") in ("compatible_no_top_violation_observed",
                                        "entrypoint_violation") and
                item.get("honest_generation") == "ok" and
                item.get("deviated_generation") == "ok" and
                item.get("rust_unsatisfied") == 0 and
                item.get("snarkjs") == "correct"):
            raw = folder / "result/raw/site-000/input.json"
            if raw.is_file():
                top_input = json.loads(raw.read_text())
                x = int(top_input["x"])
                if (x + probe_offset) % FIELD == int(candidate["main.x"]) % FIELD:
                    return x
    return None


def arm(name: str, root: Path, cap: float,
        target_form: str, seed: int, probe_offset: int) -> dict:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    deadline = start + cap
    local = source_files(folder / "src", target_form, probe_offset)
    base_x = 3 - probe_offset
    stages: dict[str, object] = {}
    stages["probe_compile"], probe_count = compile_o0(local["probe"], folder / "probe-compile", deadline)
    stages["entry_compile"], entry_count = compile_o0(local["entry"], folder / "entry-compile", deadline)
    stages["probe_s"], probe_candidate = s_run(local["probe"], folder / "probe-s", deadline, seed)
    probe_value = None
    probe_j = None
    if probe_candidate:
        probe_assignment = unwrap_candidate(probe_candidate, "probe", None)
        stages["probe_j"], probe_j = j_run(local, "probe", probe_assignment,
                                           folder / "probe-j", deadline, base_x)
        probe_value = validated_input(probe_j, folder / "probe-j",
                                      probe_assignment, probe_offset)
    if name == "baseline":
        target_source = local["target"]
        fixed = None
    elif name == "honest":
        fixed = base_x
        target_source = fixed_wrapper(local["component"].parent, fixed)
    else:
        fixed = probe_value
        target_source = fixed_wrapper(local["component"].parent, fixed) if fixed is not None else None
    target_j = None
    target_candidate = None
    target_count = None
    if target_source is not None:
        stages["target_compile"], target_count = compile_o0(target_source, folder / "target-compile", deadline)
        stages["target_s"], target_candidate = s_run(target_source, folder / "target-s", deadline, seed)
        if target_candidate:
            assignment = unwrap_candidate(target_candidate, "target", fixed)
            stages["target_j"], target_j = j_run(local, "target", assignment,
                                                 folder / "target-j", deadline, base_x)
    result = {
        "arm": name, "cap_seconds": cap, "wall_seconds": time.monotonic() - start,
        "same_seed": seed, "probe_offset": probe_offset, "base_x": base_x,
        "probe_o0_constraints": probe_count,
        "target_o0_constraints": target_count, "entry_o0_constraints": entry_count,
        "probe_candidate": str(probe_candidate) if probe_candidate else None,
        "probe_j_verdicts": [x.get("verdict") for x in probe_j.get("classes", [])] if probe_j else [],
        "probe_j_validated_x": probe_value, "target_fixed_x": fixed,
        "target_candidate": str(target_candidate) if target_candidate else None,
        "target_j_verdicts": [x.get("verdict") for x in target_j.get("classes", [])] if target_j else [],
        "target_j_reasons": [x.get("reason") for x in target_j.get("classes", [])] if target_j else [],
        "target_j_original_check": [
            {"rust_unsatisfied": x.get("rust_unsatisfied"), "snarkjs": x.get("snarkjs")}
            for x in target_j.get("classes", [])
        ] if target_j else [],
        "stages": stages,
    }
    write_json(folder / "receipt.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cap", type=float, default=CAP)
    parser.add_argument("--target-form", choices=("direct", "square"), default="square")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--probe-offset", type=int, choices=(0, 2), default=2)
    args = parser.parse_args()
    if digest(J) != J_SHA:
        raise RuntimeError("pinned J binary changed")
    if args.output.exists():
        raise RuntimeError("output exists; use a new directory")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    source = source_files(args.output / "src", args.target_form, args.probe_offset)
    overall = {"schema": "n7-feedback-prototype-v1", "kind": "synthetic_restricted_input_ablation",
               "tools": {k: {"path": str(v), "sha256": digest(v)} for k, v in
                         {"j": J, "zkfuzz": Path.home() / ".cargo/bin/zkfuzz",
                          **{n: Path(shutil.which(n) or n) for n in ("circom", "node", "snarkjs", "z3")}}.items()},
               "source_sha256": {k: digest(v) for k, v in source.items()},
               "target_form": args.target_form,
               "probe_offset": args.probe_offset,
               "arms": []}
    write_json(args.output / "receipt.json", overall)
    for name in ("baseline", "honest", "feedback"):
        result = arm(name, args.output, args.cap, args.target_form,
                     args.seed, args.probe_offset)
        overall["arms"].append(result)
        write_json(args.output / "receipt.json", overall)
    print(json.dumps({"output": str(args.output), "arms": [
        {k: a[k] for k in ("arm", "wall_seconds", "probe_j_validated_x", "target_fixed_x",
                           "target_j_verdicts", "target_j_reasons")}
        for a in overall["arms"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
