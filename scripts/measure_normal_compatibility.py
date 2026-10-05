#!/usr/bin/env python3
"""Six fixed normal compatibility conditions; no candidate generation or fuzzing.

Preserves v1 and uses its process ledger/discovery graph reader. Boundary evidence
comes only from direct compiler symbol mappings, never from the input adapters.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("normal_preparation_v1", ROOT / "scripts/measure_normal_preparation.py")
v1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v1)
FIELD = v1.FIELD
INPUT_PLAN_SHA256 = "1814314d555c791ede7544c4ae56b225dec633ad8ecc424fce13776f831b7166"
V1_SHA256 = "3cc384a4fa6e52f048073bc1626e03b9370049d221c90090a05f181d6fa80880"
FLAGS = ["--r1cs", "--wasm", "--sym", "--inspect", "--prime", "bn128"]
ARRAY_CONTROL = '''pragma circom 2.1.6;
template VecStep(n, k) {
    signal input in[n];
    signal output out[n];
    for (var i = 0; i < n; i++) {
        out[i] <== in[i] * in[i] + k;
    }
}
template ArrayRoot() {
    signal input in[3];
    signal output out[3];
    component a = VecStep(2, 2);
    component b = VecStep(2, 2);
    component c = VecStep(3, 3);
    for (var i = 0; i < 2; i++) {
        a.in[i] <== in[i];
        b.in[i] <== in[i] + 1;
    }
    for (var i = 0; i < 3; i++) {
        c.in[i] <== in[i] + 2;
    }
    for (var i = 0; i < 2; i++) {
        out[i] <== a.out[i] + b.out[i] + c.out[i];
    }
    out[2] <== c.out[2];
}
'''


def leaf_suffixes(shape):
    if shape == ():
        return [""]
    if (len(shape) != 1 or type(shape[0]) is not int or not 1 <= shape[0] <= 8):
        raise ValueError("only scalar or one-dimensional length 1..8 is supported")
    return [f"[{i}]" for i in range(shape[0])]


def scalar(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise ValueError("expected canonical nonnegative integer field value")
    if int(value) >= FIELD:
        raise ValueError("field value out of range")
    return value


def encode_input(value, shape):
    leaf_suffixes(shape)
    if not shape:
        return scalar(value)
    if not isinstance(value, list) or len(value) != shape[0]:
        raise ValueError("normal input shape differs from declared interface")
    return [scalar(v) for v in value]


def read_signal(symbols, witness, name):
    if name not in symbols:
        return None, "missing_symbol"
    wire = symbols[name]
    if wire == -1:
        return None, "optimized_out_index_minus_one"
    if type(wire) is not int or not 0 <= wire < len(witness):
        return None, "witness_index_out_of_range"
    try:
        return scalar(witness[wire]), None
    except ValueError:
        return None, "invalid_field_value"


def compare_boundary(original_symbols, original_witness, wrapper_symbols,
                     wrapper_witness, prefix, shape):
    suffixes = leaf_suffixes(shape)
    leaves, shape_issues = [], []
    for side, symbols, base in [("original", original_symbols, prefix),
                                ("wrapper", wrapper_symbols, "main")]:
        for direction in ("in", "out"):
            stem = f"{base}.{direction}"
            expected = {stem + suffix for suffix in suffixes}
            actual = {name for name in symbols if name == stem or name.startswith(stem + "[")}
            if actual - expected:
                shape_issues.append({"side": side, "direction": direction,
                                     "reason": "unexpected_interface_symbols", "names": sorted(actual - expected)})
    for direction in ("in", "out"):
        for suffix in suffixes:
            original_name, wrapper_name = f"{prefix}.{direction}{suffix}", f"main.{direction}{suffix}"
            left, left_error = read_signal(original_symbols, original_witness, original_name)
            right, right_error = read_signal(wrapper_symbols, wrapper_witness, wrapper_name)
            reasons = [f"{side}:{error}" for side, error in [("original", left_error), ("wrapper", right_error)] if error]
            status = "unsupported" if reasons else ("matched" if left == right else "mismatched")
            leaves.append({"original_signal": original_name, "wrapper_signal": wrapper_name,
                           "status": status, "reason": ";".join(reasons) if reasons else None})
    counts = Counter(row["status"] for row in leaves)
    status = ("mismatched" if counts["mismatched"] else
              "unsupported" if counts["unsupported"] or shape_issues else "matched")
    return {"status": status, "expected_leaves": len(leaves),
            "matched_leaves": counts["matched"], "mismatched_leaves": counts["mismatched"],
            "unsupported_leaves": counts["unsupported"], "leaves": leaves, "shape_issues": shape_issues}


def adapter(case, prefix, value):
    """Declared benign test inputs, not reconstruction evidence for missing signals."""
    if case == "existing-discovery":
        allowed = {"main.rsa", "main.rsa.bigint", "main.rsa.range", "main.hash",
                   "main.bits8", "main.bits32", "main.bits256"}
        v1.require(prefix in allowed, "undeclared scalar boundary")
        return value, ()
    if case == "arithmetic-control":
        offsets = {"main.a": 0, "main.b": 1, "main.c": 2, "main.m": 3, "main.m.inner": 8}
        v1.require(prefix in offsets, "undeclared arithmetic boundary")
        return value + offsets[prefix], ()
    v1.require(case == "array-control" and prefix in {"main.a", "main.b", "main.c"},
               "undeclared array boundary")
    size, offset = {"main.a": (2, 0), "main.b": (2, 1), "main.c": (3, 2)}[prefix]
    return [v + offset for v in value[:size]], (size,)


def oracle(case, value):
    if case == "existing-discovery":
        return value
    if case == "arithmetic-control":
        return value**2 + 2 + (value + 1)**2 + 2 + (value + 2)**2 + 3 + (value + 8)**2 + 7
    return [v**2 + 2 + (v + 1)**2 + 2 + (v + 2)**2 + 3 for v in value[:2]] + [(value[2] + 2)**2 + 3]


def compile_artifact(runner, tools, source, project, optimization, folder):
    folder.mkdir(parents=True, exist_ok=False)
    command, _ = runner.run("compile", [tools["circom"], source, f"--{optimization}", *FLAGS,
                                       "-l", project, "--output", folder], folder, check=False)
    artifacts = {"r1cs": folder / f"{source.stem}.r1cs", "sym": folder / f"{source.stem}.sym",
                 "wasm": folder / f"{source.stem}_js/{source.stem}.wasm",
                 "generator": folder / f"{source.stem}_js/generate_witness.js"}
    missing = [key for key, path in artifacts.items() if not path.is_file()]
    result = {"command": command["id"], "status": "passed" if command["success"] and not missing else "failed",
              "missing_artifacts": missing, "artifacts": {k: v1.ref(p) for k, p in artifacts.items() if p.is_file()}}
    return artifacts if result["status"] == "passed" else None, result


def calculate(runner, tools, artifacts, value, shape, folder):
    result = {"calculation": "not_run", "constraint": "not_run", "export": "not_run", "evidence": {}, "reason": None}
    if artifacts is None:
        result["reason"] = "compile_failed_or_unavailable"
        return None, result
    folder.mkdir(parents=True, exist_ok=False)
    input_path, witness_path = folder / "input.json", folder / "normal.wtns"
    v1.write_json(input_path, {"in": encode_input(value, shape)})
    command, _ = runner.run("normal-calculate", [tools["node"], artifacts["generator"], artifacts["wasm"],
                                               input_path, witness_path], folder, check=False)
    result["evidence"].update({"input": v1.ref(input_path), "calculation_command": command["id"]})
    result["calculation"] = "passed" if command["success"] and witness_path.is_file() else "failed"
    if result["calculation"] != "passed":
        result["reason"] = "normal_calculation_failed"
        return None, result
    result["evidence"]["witness"] = v1.ref(witness_path)
    command, stdout = runner.run("constraint-check", [tools["snarkjs"], "wtns", "check", artifacts["r1cs"], witness_path],
                                folder, check=False)
    result["constraint"] = "passed" if command["success"] and "WITNESS IS CORRECT" in stdout.read_text() else "failed"
    result["evidence"]["constraint_command"] = command["id"]
    exported = folder / "normal-witness.json"
    command, _ = runner.run("witness-export", [tools["snarkjs"], "wtns", "export", "json", witness_path, exported], folder, check=False)
    result["evidence"]["export_command"] = command["id"]
    if not command["success"] or not exported.is_file():
        result.update({"export": "failed", "reason": "witness_export_failed"})
        return None, result
    result["evidence"]["export"] = v1.ref(exported)
    witness = json.loads(exported.read_text())
    v1.require(isinstance(witness, list) and witness and scalar(witness[0]) == "1", "missing witness constant")
    result["export"] = "passed"
    return witness, result


def run_condition(runner, tools, project, case, optimization, inputs, input_ids, folder):
    started_at, started = datetime.now(timezone.utc).isoformat(), time.perf_counter()
    record_start = len(runner.records)
    result = {"case": case, "optimization": optimization, "started_at": started_at,
              "status": "failed", "discovery_status": "not_run", "failures": [], "unsupported": [],
              "compiles": [], "compile_uses": [], "originals": [], "boundaries": [],
              "normal_validation_seconds": None, "expected_normal_calculations": None}
    prep_finished = None
    try:
        command, stdout = runner.run("discovery", [tools["zkfdo"], "targets", "--project", project,
                                    "--entrypoint", project / "main.circom", "--no-validate",
                                    "--output", folder / "discovery"], folder)
        report = json.loads(stdout.read_text())
        result["discovery"] = v1.ref(stdout)
        result["discovery_command"] = command["id"]
        result["unsupported"] = report["unsupported"]
        v1.require(report["entrypoint_status"] == "found" and not report["unsupported"], "automatic discovery incomplete")
        v1.require(report["targets"] and all(t["wrapper_status"] == "generated" for t in report["targets"]),
                   "automatic wrappers incomplete")
        paths = v1.boundary_paths(report)
        expected_boundaries = {"existing-discovery": 7, "arithmetic-control": 5, "array-control": 3}[case]
        v1.require(len(paths) == expected_boundaries, "discovered normal fixture boundary denominator changed")
        for _, prefix in paths:
            adapter(case, prefix, inputs[0])
        result.update({"discovery_status": "passed", "call_sites": len(report["targets"]),
                       "compile_units": len(report["compile_units"]), "boundary_instances": len(paths),
                       "expected_boundary_sets": len(paths) * len(inputs),
                       "expected_normal_calculations": (1 + len(paths)) * len(inputs)})
        original, compile_result = compile_artifact(runner, tools, project / "main.circom", project,
                                                    optimization, folder / "compiled-original")
        result["compiles"].append({"role": "original", **compile_result})
        artifacts, cache = {}, {}
        units = {u["key"]: u for u in report["compile_units"]}
        for index, target in enumerate(report["targets"]):
            source, unit = Path(target["generated_wrapper_path"]), units[target["compile_unit"]]
            v1.require(not unit["unresolved_includes"], "unresolved wrapper dependency")
            v1.require(target["identity"] in unit["call_site_identities"], "compile-unit membership mismatch")
            for dependency in unit["dependencies"]:
                v1.require(v1.sha(dependency["path"]) == dependency["sha256"], "source changed after discovery")
            key_data = {"wrapper_sha256": v1.sha(source), "dependencies": unit["dependencies"],
                        "compiler": v1.ref(tools["circom"]), "flags": [f"--{optimization}", *FLAGS],
                        "library_paths": [str(project)], "timeout_seconds": 60}
            cache_key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
            reused = cache_key in cache
            if reused:
                artifact, compile_result = cache[cache_key]
            else:
                artifact, compile_result = compile_artifact(runner, tools, source, project, optimization,
                                                           folder / f"compiled-wrapper-{index:02d}")
                cache[cache_key] = (artifact, compile_result)
                result["compiles"].append({"role": "wrapper", **compile_result})
            artifacts[target["identity"]] = artifact
            result["compile_uses"].append({"call_site": target["identity"], "instance_key": target["instance_key"],
                "discovery_compile_unit": unit["key"], "cache_key": cache_key, "cache_conditions": key_data,
                "reused": reused, "compile_command": compile_result["command"], "status": compile_result["status"]})
        prep_finished = time.perf_counter()
        result["preparation_seconds"] = prep_finished - started
        original_symbols = v1.symbol_indices(original["sym"]) if original else {}
        for input_index, value in enumerate(inputs):
            root_shape = (3,) if case == "array-control" else ()
            original_witness, normal = calculate(runner, tools, original, value, root_shape,
                                                folder / f"normal-{input_index}/original")
            oracle_rows = []
            if original_witness is not None:
                expected = encode_input(oracle(case, value), root_shape)
                for suffix, target_value in zip(leaf_suffixes(root_shape), expected if root_shape else [expected]):
                    actual, reason = read_signal(original_symbols, original_witness, "main.out" + suffix)
                    oracle_rows.append({"signal": "main.out" + suffix, "reason": reason,
                                        "status": "unsupported" if reason else "matched" if actual == target_value else "mismatched"})
            result["originals"].append({"input_id": input_ids[input_index], **normal, "normal_output_oracle": oracle_rows})
            for boundary_index, (target, prefix) in enumerate(paths):
                boundary_input, shape = adapter(case, prefix, value)
                artifact = artifacts[target["identity"]]
                wrapper_witness, normal = calculate(runner, tools, artifact, boundary_input, shape,
                    folder / f"normal-{input_index}/boundary-{boundary_index:02d}")
                if original_witness is None or wrapper_witness is None:
                    count = 2 * len(leaf_suffixes(shape))
                    comparison = {"status": "not_checked", "reason": "original_or_wrapper_assignment_unavailable",
                                  "expected_leaves": count, "matched_leaves": 0, "mismatched_leaves": 0,
                                  "unsupported_leaves": count, "leaves": [], "shape_issues": []}
                else:
                    comparison = compare_boundary(original_symbols, original_witness, v1.symbol_indices(artifact["sym"]),
                                                  wrapper_witness, prefix, shape)
                result["boundaries"].append({"input_id": input_ids[input_index], "call_site": target["identity"],
                    "original_prefix": prefix, "instance_key": target["instance_key"],
                    "parameters": target["concrete_parameters"], "shape": list(shape), **normal, "comparison": comparison})
        normals = result["originals"] + result["boundaries"]
        failed = (any(c["status"] == "failed" for c in result["compiles"])
                  or any(r[key] == "failed" for r in normals for key in ("calculation", "constraint", "export"))
                  or any(r["comparison"]["status"] == "mismatched" for r in result["boundaries"])
                  or any(r["status"] == "mismatched" for o in result["originals"] for r in o["normal_output_oracle"]))
        incomplete = (any(r["comparison"]["status"] != "matched" for r in result["boundaries"])
                      or any(r[key] != "passed" for r in normals for key in ("calculation", "constraint", "export")))
        result["status"] = "failed" if failed else "unsupported" if incomplete else "passed"
    except (v1.ProcessFailure, ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        result["failures"].append(str(error))
        if result["discovery_status"] != "passed":
            result["discovery_status"] = "unsupported" if result["unsupported"] else "failed"
            if result["unsupported"]:
                result["status"] = "unsupported"
    stopped = time.perf_counter()
    result["preparation_seconds"] = (prep_finished or stopped) - started
    if prep_finished is not None:
        result["normal_validation_seconds"] = stopped - prep_finished
    commands = runner.records[record_start:]
    compiles = [r for r in commands if r["stage"] == "compile"]
    normals = result["originals"] + result["boundaries"]
    result.update({"finished_at": datetime.now(timezone.utc).isoformat(),
        "compile_processes": sum(r["process_started"] for r in compiles), "compile_attempts": len(compiles),
        "compile_successes": sum(c["status"] == "passed" for c in result["compiles"]),
        "compile_wall_seconds_sum": sum(r["wall_seconds"] for r in compiles),
        "command_ids": [r["id"] for r in commands],
        "calculation_counts": dict(Counter(r["calculation"] for r in normals)),
        "constraint_counts": dict(Counter(r["constraint"] for r in normals)),
        "boundary_counts": dict(Counter(r["comparison"]["status"] for r in result["boundaries"])),
        "leaf_counts": {key: sum(r["comparison"][key] for r in result["boundaries"])
                        for key in ("expected_leaves", "matched_leaves", "mismatched_leaves", "unsupported_leaves")}})
    v1.write_json(folder / "result.json", result)
    print(json.dumps({k: result[k] for k in ("case", "optimization", "status", "compile_processes",
                      "preparation_seconds", "normal_validation_seconds", "boundary_counts")}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zkfdo", type=Path, default=ROOT / "target/debug/zkfDO")
    args = parser.parse_args()
    output = args.output.resolve()
    v1.require(output.is_relative_to(ROOT / "runs"), "raw artifacts must be under repository runs/")
    subprocess.run(["git", "check-ignore", "--quiet", str(output)], cwd=ROOT, check=True)
    v1.require(v1.sha(ROOT / "scripts/measure_normal_preparation.py") == V1_SHA256, "v1 utility changed")
    plan_path = output / "input-plan.json"
    v1.require(v1.sha(plan_path) == INPUT_PLAN_SHA256, "fixed normal input plan changed")
    plan = json.loads(plan_path.read_text())
    # Exclusive ledger creation refuses reruns/overwrites of any executed condition.
    runner = v1.Runner(output)
    provenance = output / "provenance"
    provenance.mkdir()
    for source in (Path(__file__), ROOT / "scripts/measure_normal_preparation.py", ROOT / "src/targets.rs", args.zkfdo):
        shutil.copy2(source, provenance / source.name)
    tools = {name: Path(shutil.which(name)).resolve() for name in ("circom", "node", "snarkjs")}
    tools["zkfdo"] = provenance / args.zkfdo.name
    versions = {}
    for name, path in tools.items():
        command, stdout = runner.run("version", [path, "--version"], output / "versions", check=False)
        lines = stdout.read_text().splitlines()
        versions[name] = {"file": v1.ref(path), "version_line": lines[0] if lines else None,
                          "version_command": command["id"], "version_exit_code": command["exit_code"]}
    projects = output / "projects"
    projects.mkdir()
    shutil.copytree(ROOT / "tests/fixtures/target_discovery", projects / "existing-discovery")
    shutil.copytree(ROOT / "runs/n4-1-normal-execution-2026-10-01/run-v1/projects/arithmetic-control", projects / "arithmetic-control")
    array = projects / "array-control"
    array.mkdir()
    (array / "library.circom").write_text(ARRAY_CONTROL)
    (array / "main.circom").write_text('pragma circom 2.1.6;\ninclude "library.circom";\ncomponent main = ArrayRoot();\n')
    conditions = {"version": "normal-compatibility-v1", "owner": "miiz", "created_at": datetime.now(timezone.utc).isoformat(),
        "host": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
        "input_plan": v1.ref(plan_path), "scope": v1.ref(ROOT / "reports/n4-1-normal-compatibility-2026-10-01/SCOPE.md"),
        "measurement_script": v1.ref(provenance / Path(__file__).name), "v1_utility": v1.ref(provenance / "measure_normal_preparation.py"),
        "discovery_source": v1.ref(provenance / "targets.rs"), "tools": versions,
        "source_files": [v1.ref(p) for p in sorted(projects.rglob("*.circom"))],
        "common_flags": FLAGS, "order": plan["conditions"],
        "cache": "empty application cache per condition; identical full compile key reused only within condition; OS cache not flushed",
        "normal_inputs": "three predeclared inputs per fixture; same declared boundary input adapters for O0/O1; adapters do not supply missing-symbol evidence",
        "preparation_scope": "automatic discovery/wrappers + original/wrapper compiles + dependency/cache provenance hashing",
        "normal_validation_scope": "normal calculation + constraint check + witness export + direct symbol boundary comparison and normal output oracle",
        "excluded_timing": "tool/source snapshots, versions, final manifest/report, cargo/regression checks",
        "prohibited_extensions": "no O2, inverse optimization, new project, fuzzing, candidate generation, experiment aggregate"}
    v1.write_json(output / "conditions.json", conditions)
    cases = {c["id"]: c for c in plan["cases"]}
    results = []
    for entry in plan["conditions"]:
        case, optimization = entry["case"], entry["optimization"]
        data = cases[case]
        results.append(run_condition(runner, tools, projects / case, case, optimization, data["inputs"], data["input_ids"],
                                     output / case / optimization))
    v1.write_json(output / "artifact-manifest.json", [v1.ref(p) for p in sorted(output.rglob("*")) if p.is_file()])
    summary = {"version": "normal-compatibility-v1", "conditions": v1.ref(output / "conditions.json"),
               "process_ledger": v1.ref(runner.ledger), "artifact_manifest": v1.ref(output / "artifact-manifest.json"),
               "results": results, "limitation": "fixed normal samples; no detection advantage or general semantic equivalence evidence"}
    v1.write_json(output / "summary.json", summary)
    return 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
