#!/usr/bin/env python3
"""Bounded normal arithmetic experiment; no candidate search or defect reproduction.

Only the repository's benign discovery fixture and the arithmetic control below
are selectable. Raw inputs, assignments and compiler artifacts stay under runs/.
The original process ledger, not experiment aggregate, supplies measurements.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
FLAGS = ["--O0", "--r1cs", "--wasm", "--sym", "--inspect", "--prime", "bn128"]
INPUTS = [0, 2, 7]
ORDER = [(1, "per-call"), (1, "per-unit"), (2, "per-unit"), (2, "per-call")]
CONTROL = '''pragma circom 2.1.6;
template Step(k) {
    signal input in;
    signal output out;
    out <== in * in + k;
}
template Branch(n) {
    signal input in;
    signal output out;
    component inner = Step(2);
    inner.in <== in + n;
    out <== inner.out + n;
}
template Root() {
    signal input in;
    signal output out;
    component a = Step(2);
    component b = Step(2);
    component c = Step(3);
    component m = Branch(5);
    a.in <== in;
    b.in <== in + 1;
    c.in <== in + 2;
    m.in <== in + 3;
    out <== a.out + b.out + c.out + m.out;
}
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(path):
    p = Path(path).resolve()
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def ref(path):
    return {"path": relative(path), "sha256": sha(path)}


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def require(condition, message):
    if not condition:
        raise ValueError(message)


class ProcessFailure(RuntimeError):
    def __init__(self, record):
        self.record = record
        super().__init__(f"{record['stage']} failed: exit={record['exit_code']}, "
                         f"timeout={record['timed_out']}; {record['stderr']['path']}")


class Runner:
    def __init__(self, output):
        self.output = output
        self.records = []
        self.ledger = output / "commands.jsonl"
        self.ledger.touch(exist_ok=False)

    def run(self, stage, argv, folder, timeout=60, check=True):
        folder.mkdir(parents=True, exist_ok=True)
        identifier = f"{len(self.records):04d}-{stage}"
        stdout = folder / f"{identifier}.stdout.log"
        stderr = folder / f"{identifier}.stderr.log"
        started = time.perf_counter()
        record = {"id": identifier, "stage": stage, "argv": [str(x) for x in argv],
                  "cwd": str(ROOT), "started_at": datetime.now(timezone.utc).isoformat(),
                  "timeout_seconds": timeout, "process_started": False,
                  "timed_out": False, "exit_code": None, "error": None}
        with stdout.open("xb") as out, stderr.open("xb") as err:
            try:
                process = subprocess.Popen(record["argv"], cwd=ROOT, stdout=out, stderr=err,
                                           start_new_session=True)
                record["process_started"] = True
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    record["timed_out"] = True
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                record["exit_code"] = process.returncode
            except OSError as error:
                record["error"] = str(error)
        record["wall_seconds"] = time.perf_counter() - started
        record["stdout"] = ref(stdout)
        record["stderr"] = ref(stderr)
        record["success"] = record["exit_code"] == 0 and not record["timed_out"]
        self.records.append(record)
        with self.ledger.open("a") as stream:
            stream.write(json.dumps(record) + "\n")
            stream.flush()
        if check and not record["success"]:
            raise ProcessFailure(record)
        return record, stdout


def symbol_indices(path):
    result = {}
    for line in path.read_text().splitlines():
        label, wire, component, name = line.split(",", 3)
        int(label), int(component)  # malformed compiler output must not be guessed.
        require(name not in result, f"duplicate symbol {name}")
        result[name] = int(wire)
    return result


def value_at(symbols, witness, name):
    require(name in symbols, f"unmapped signal {name}")
    wire = symbols[name]
    require(0 <= wire < len(witness), f"eliminated/out-of-range signal {name}: {wire}")
    value = int(witness[wire])
    require(0 <= value < FIELD, f"noncanonical field value for {name}")
    return value


def boundary_paths(report):
    """Expand configuration-key edges into call paths; never equate a key with a call."""
    edges = {}
    for target in report["targets"]:
        edges.setdefault(target["parent_instance_key"], []).append(target)
    result = []

    def walk(key, prefix, ancestors):
        require(key not in ancestors, "cycle in discovered instance graph")
        for target in edges.get(key, []):
            component = target["origin"]["component_name"]
            require(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*(?:\[\d+\])*", component),
                    f"unsupported boundary name {component}")
            path = prefix + "." + component
            result.append((target, path))
            require(len(result) <= 100, "normal-control boundary cap exceeded")
            walk(target["instance_key"], path, ancestors | {key})

    walk(report["root_instance_key"], "main", set())
    require({t["identity"] for t, _ in result} == {t["identity"] for t in report["targets"]},
            "discovery has unreachable call sites")
    require(len({p for _, p in result}) == len(result), "ambiguous call path")
    return result


def compile_artifact(runner, circom, source, project, folder):
    folder.mkdir(parents=True, exist_ok=False)
    command, _ = runner.run("compile", [circom, source, *FLAGS, "-l", project,
                                          "--output", folder], folder)
    stem = source.stem
    artifacts = {"r1cs": folder / f"{stem}.r1cs", "sym": folder / f"{stem}.sym",
                 "wasm": folder / f"{stem}_js" / f"{stem}.wasm",
                 "generator": folder / f"{stem}_js" / "generate_witness.js"}
    require(all(p.is_file() for p in artifacts.values()), "compiler did not produce required artifacts")
    return artifacts, command


def calculate(runner, node, snarkjs, artifact, input_value, folder):
    folder.mkdir(parents=True, exist_ok=False)
    input_path = folder / "input.json"
    write_json(input_path, {"in": str(input_value)})
    witness_path = folder / "normal.wtns"
    runner.run("normal-calculate", [node, artifact["generator"], artifact["wasm"],
                                     input_path, witness_path], folder)
    check, stdout = runner.run("constraint-check", [snarkjs, "wtns", "check",
                                                     artifact["r1cs"], witness_path], folder)
    require("WITNESS IS CORRECT" in stdout.read_text(), "checker did not explicitly confirm the witness")
    exported = folder / "normal-witness.json"
    runner.run("witness-export", [snarkjs, "wtns", "export", "json", witness_path, exported], folder)
    witness = json.loads(exported.read_text())
    require(witness and int(witness[0]) == 1, "missing witness constant")
    return witness, {"input": ref(input_path), "witness": ref(witness_path),
                     "export": ref(exported), "constraint_check_command": check["id"]}


def run_arm(runner, tools, project, case, repetition, mode, arm_dir):
    result = {"case": case, "repetition": repetition, "mode": mode,
              "status": "failed", "blocked_stage": "discovery", "failures": [],
              "boundaries": [], "originals": [], "compile_uses": []}
    record_start = len(runner.records)
    prepare_start = time.perf_counter()
    prepared = False
    try:
        _, stdout = runner.run("discovery", [tools["zkfdo"], "targets", "--project", project,
                              "--entrypoint", project / "main.circom", "--no-validate",
                              "--output", arm_dir / "discovery"], arm_dir)
        report = json.loads(stdout.read_text())
        result["discovery"] = ref(stdout)
        result["discovery_id"] = report["discovery_id"]
        require(report["entrypoint_status"] == "found" and not report["unsupported"],
                "automatic discovery incomplete/unsupported")
        require(report["targets"] and all(t["wrapper_status"] == "generated" for t in report["targets"]),
                "automatic wrapper generation incomplete")
        result["call_sites"] = len(report["targets"])
        result["compile_units"] = len(report["compile_units"])
        paths = boundary_paths(report)
        result["boundary_instances"] = len(paths)
        result["blocked_stage"] = "original-compile"
        original, original_compile = compile_artifact(runner, tools["circom"], project / "main.circom",
                                                        project, arm_dir / "compiled-original")
        result["original_compile_command"] = original_compile["id"]
        artifacts = {}
        units = {u["key"]: u for u in report["compile_units"]}
        cache = {}
        result["blocked_stage"] = "wrapper-compile"
        for index, target in enumerate(report["targets"]):
            source = Path(target["generated_wrapper_path"])
            unit = units[target["compile_unit"]]
            require(not unit["unresolved_includes"], "unresolved wrapper dependency")
            require(target["identity"] in unit["call_site_identities"], "compile-unit membership mismatch")
            for dependency in unit["dependencies"]:
                require(sha(dependency["path"]) == dependency["sha256"], "source changed after discovery")
            key_data = {"wrapper_sha256": sha(source), "dependencies": unit["dependencies"],
                        "compiler": ref(tools["circom"]), "flags": FLAGS,
                        "library_paths": [str(project)], "timeout_seconds": 60}
            cache_key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
            reused = mode == "per-unit" and cache_key in cache
            if reused:
                artifact, command = cache[cache_key]
            else:
                artifact, command = compile_artifact(runner, tools["circom"], source, project,
                                                       arm_dir / f"compiled-wrapper-{index:02d}")
                cache[cache_key] = (artifact, command)
            artifacts[target["identity"]] = artifact
            result["compile_uses"].append({"call_site": target["identity"],
                "instance_key": target["instance_key"], "discovery_compile_unit": unit["key"],
                "artifact_cache_key": cache_key, "cache_conditions": key_data,
                "reused": reused, "compile_command": command["id"],
                "artifacts": {k: ref(v) for k, v in artifact.items()}})
        result["preparation_seconds"] = time.perf_counter() - prepare_start
        prepared = True
        result["blocked_stage"] = "normal-calculation-and-boundary-comparison"
        normal_start = time.perf_counter()
        original_symbols = symbol_indices(original["sym"])
        for input_index, input_value in enumerate(INPUTS):
            witness, evidence = calculate(runner, tools["node"], tools["snarkjs"], original,
                                           input_value, arm_dir / f"normal-{input_index}" / "original")
            expected = input_value if case == "existing-discovery" else (
                input_value**2 + 2 + (input_value+1)**2 + 2 + (input_value+2)**2 + 3 + (input_value+8)**2 + 7)
            require(value_at(original_symbols, witness, "main.in") == input_value, "original input mismatch")
            require(value_at(original_symbols, witness, "main.out") == expected % FIELD, "normal arithmetic oracle mismatch")
            result["originals"].append({"input_index": input_index, "constraint_satisfied": True,
                                       "normal_oracle_matched": True, "evidence": evidence})
            for boundary_index, (target, prefix) in enumerate(paths):
                artifact = artifacts[target["identity"]]
                input_boundary = value_at(original_symbols, witness, prefix + ".in")
                expected_boundary = value_at(original_symbols, witness, prefix + ".out")
                wrapper, evidence = calculate(runner, tools["node"], tools["snarkjs"], artifact,
                    input_boundary, arm_dir / f"normal-{input_index}" / f"boundary-{boundary_index:02d}")
                symbols = symbol_indices(artifact["sym"])
                matched = (value_at(symbols, wrapper, "main.in") == input_boundary
                           and value_at(symbols, wrapper, "main.out") == expected_boundary)
                result["boundaries"].append({"input_index": input_index, "call_site": target["identity"],
                    "original_prefix": prefix, "wrapper_prefix": "main", "instance_key": target["instance_key"],
                    "parameters": target["concrete_parameters"], "constraint_satisfied": True,
                    "input_output_matched": matched, "evidence": evidence})
                require(matched, f"normal boundary mismatch at {prefix}")
        result["normal_check_seconds"] = time.perf_counter() - normal_start
        result["status"] = "passed"
        result["blocked_stage"] = None
    except (ProcessFailure, ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        result["failures"].append(str(error))
        if not prepared:
            result["preparation_seconds"] = time.perf_counter() - prepare_start
    commands = runner.records[record_start:]
    compiles = [r for r in commands if r["stage"] == "compile"]
    result.update({"compile_attempts": len(compiles),
                   "compile_processes": sum(r["process_started"] for r in compiles),
                   "compile_successes": sum(r["success"] for r in compiles),
                   "compile_failures": sum(not r["success"] for r in compiles),
                   "compile_wall_seconds_sum": sum(r["wall_seconds"] for r in compiles),
                   "discovery_wall_seconds": sum(r["wall_seconds"] for r in commands if r["stage"] == "discovery"),
                   "command_ids": [r["id"] for r in commands]})
    write_json(arm_dir / "result.json", result)
    print(json.dumps({k: result[k] for k in ["case", "repetition", "mode", "status", "compile_processes", "preparation_seconds"]}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zkfdo", type=Path, default=ROOT / "target/debug/zkfDO")
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.is_relative_to(ROOT / "runs"), "raw experiment output must be under repository runs/")
    require(not output.exists(), "refusing to overwrite an experiment")
    subprocess.run(["git", "check-ignore", "--quiet", str(output)], cwd=ROOT, check=True)
    output.mkdir(parents=True)
    runner = Runner(output)
    tools = {name: Path(shutil.which(name)).resolve() for name in ["circom", "node", "snarkjs"]}
    tools["zkfdo"] = args.zkfdo.resolve()
    versions = {}
    for name, path in tools.items():
        capture, stdout = runner.run("version", [path, "--version"], output / "versions", check=False)
        versions[name] = {"file": ref(path), "version_line": stdout.read_text().splitlines()[0],
                          "version_command": capture["id"]}
    projects = output / "projects"
    projects.mkdir()
    existing = projects / "existing-discovery"
    shutil.copytree(ROOT / "tests/fixtures/target_discovery", existing)
    control = projects / "arithmetic-control"
    control.mkdir()
    (control / "library.circom").write_text(CONTROL)
    (control / "main.circom").write_text('pragma circom 2.1.6;\ninclude "library.circom";\ncomponent main = Root();\n')
    conditions = {"version": "normal-preparation-v1", "owner": "miiz", "created_at": datetime.now(timezone.utc).isoformat(),
        "host": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
        "script": ref(__file__), "discovery_source": ref(ROOT / "src/targets.rs"),
        "tools": versions, "flags": FLAGS, "normal_input_count": len(INPUTS),
        "order": ORDER, "cache": "empty per arm; compile reuse within arm only; OS cache not flushed",
        "source_files": [ref(p) for p in sorted(projects.rglob("*.circom"))],
        "preparation_boundary": "discovery+automatic wrappers, original artifact compile, wrapper artifact compile and provenance hashing; excludes normal calculation/check/export/comparison",
        "comparison": "same current discovery and wrapper generation; actual artifact compile per call site versus per complete cache key; not historical binary comparison",
        "execution": "sequential normal inputs only; no fuzzing, mutations, defect reproduction or experiment aggregate"}
    write_json(output / "conditions.json", conditions)
    arms = []
    for project in [existing, control]:
        for repetition, mode in ORDER:
            arm_dir = output / project.name / f"repeat-{repetition}-{mode}"
            arms.append(run_arm(runner, tools, project, project.name, repetition, mode, arm_dir))
    manifest = [ref(p) for p in sorted(output.rglob("*")) if p.is_file()]
    write_json(output / "artifact-manifest.json", manifest)
    summary = {"conditions": ref(output / "conditions.json"), "process_ledger": ref(runner.ledger),
               "artifact_manifest": ref(output / "artifact-manifest.json"),
               "arms": arms, "all_passed": all(a["status"] == "passed" for a in arms),
               "limitation": "normal arithmetic samples only; no detection advantage or universal semantic equivalence claim"}
    write_json(output / "summary.json", summary)
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
