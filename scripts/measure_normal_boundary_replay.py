#!/usr/bin/env python3
"""NB-01: fixed O0 normal boundary replay from verified original assignments."""
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
SPEC = importlib.util.spec_from_file_location("normal_compatibility_v1", ROOT / "scripts/measure_normal_compatibility.py")
nc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nc)
v1 = nc.v1
PLAN_HASH = "e3e1a8990019295b38ed0ade1809a24db6918a6131ff5db7f1912e60d98649a2"
NC_HASH = "19356ce37130e8c4927f49eb7de639617b424889c6313d1ce4367504bda04448"


class Unsupported(ValueError):
    pass


def verified(status):
    return all(status.get(k) == "passed" for k in ("calculation", "constraint", "export"))


def infer_port(symbols, stem, count):
    if type(count) is not int or not 1 <= count <= 8:
        raise Unsupported("port_count_outside_1_to_8")
    names = {name for name in symbols if name == stem or name.startswith(stem + "[") or name.startswith(stem + ".")}
    if names == {stem} and count == 1:
        return [""]
    suffixes = [f"[{i}]" for i in range(count)]
    if names != {stem + suffix for suffix in suffixes}:
        raise Unsupported(f"missing_extra_or_ambiguous_port_shape:{stem}")
    return suffixes


def read_inputs(original_symbols, original_witness, wrapper_symbols, prefix, input_count, original_status):
    meta = {"status": "not_run", "reason": "original_assignment_not_verified", "expected_leaves": input_count,
            "shape": None, "leaves": []}
    if not verified(original_status):
        return None, meta
    try:
        suffixes = infer_port(wrapper_symbols, "main.in", input_count)
        if infer_port(original_symbols, prefix + ".in", input_count) != suffixes:
            raise Unsupported("original_wrapper_input_shape_mismatch")
        values = []
        for suffix in suffixes:
            name = prefix + ".in" + suffix
            value, reason = nc.read_signal(original_symbols, original_witness, name)
            target_wire = wrapper_symbols["main.in" + suffix]
            if type(target_wire) is not int or target_wire < 0:
                reason = (reason + ";" if reason else "") + "wrapper_input_index_unavailable"
            values.append(value)
            meta["leaves"].append({"source_signal": name, "source_wire": original_symbols[name],
                                   "destination_input": "in" + suffix,
                                   "status": "unsupported" if reason else "passed", "reason": reason})
        if any(leaf["status"] != "passed" for leaf in meta["leaves"]):
            raise Unsupported("one_or_more_input_leaves_unavailable")
        meta.update({"status": "passed", "reason": None, "shape": [] if suffixes == [""] else [input_count]})
        return {"in": values[0] if suffixes == [""] else values}, meta
    except Unsupported as error:
        meta.update({"status": "unsupported", "reason": str(error)})
        return None, meta


def compare_port(original_symbols, original_witness, wrapper_symbols, wrapper_witness,
                 prefix, port, count, original_status, wrapper_status):
    result = {"status": "not_run", "reason": "both_assignments_must_be_verified", "expected_leaves": count,
              "matched_leaves": 0, "mismatched_leaves": 0, "unsupported_leaves": 0, "leaves": []}
    if not verified(original_status) or not verified(wrapper_status):
        return result
    try:
        if port not in ("in", "out"):
            raise Unsupported("unsupported_port")
        suffixes = infer_port(wrapper_symbols, "main." + port, count)
    except Unsupported as error:
        result.update({"status": "unsupported", "reason": str(error), "unsupported_leaves": count})
        return result
    shape_reason = None
    try:
        if infer_port(original_symbols, prefix + "." + port, count) != suffixes:
            shape_reason = "original_wrapper_port_shape_mismatch"
    except Unsupported as error:
        shape_reason = str(error)
    for suffix in suffixes:
        left_name, right_name = f"{prefix}.{port}{suffix}", f"main.{port}{suffix}"
        left, le = nc.read_signal(original_symbols, original_witness, left_name)
        right, re_ = nc.read_signal(wrapper_symbols, wrapper_witness, right_name)
        reasons = [f"{side}:{reason}" for side, reason in (("original", le), ("wrapper", re_)) if reason]
        state = "unsupported" if reasons else "matched" if left == right else "mismatched"
        result[state + "_leaves"] += 1
        result["leaves"].append({"original_signal": left_name, "wrapper_signal": right_name,
                                 "status": state, "reason": ";".join(reasons) if reasons else None})
    result.update({"status": "mismatched" if result["mismatched_leaves"] else
                  "unsupported" if result["unsupported_leaves"] or shape_reason else "matched", "reason": shape_reason})
    return result


def interface_counts(text):
    """Read only the installed snarkjs info labels; do not parse/rewrite R1CS."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    result = {}
    for label in ("Private Inputs", "Public Inputs", "Outputs", "Wires"):
        matches = re.findall(r"# of " + label + r": ([0-9]+)\s*$", plain, re.MULTILINE)
        if len(matches) != 1:
            raise Unsupported("missing_or_ambiguous_r1cs_info:" + label)
        result[label] = int(matches[0])
    return {"input_count": result["Private Inputs"] + result["Public Inputs"],
            "output_count": result["Outputs"], "wire_count": result["Wires"]}


def prepare_artifact(runner, tools, source, project, folder):
    artifact, compilation = nc.compile_artifact(runner, tools, source, project, "O0", folder)
    prepared = {"artifact": artifact, "symbols": {}, "interface": {"status": "not_run", "reason": "compile_failed"}}
    if artifact is not None:
        command, stdout = runner.run("interface-info", [tools["snarkjs"], "r1cs", "info", artifact["r1cs"]], folder, check=False)
        prepared["interface"] = {"status": "failed", "reason": "r1cs_info_failed", "command": command["id"]}
        if command["success"]:
            try:
                counts = interface_counts(stdout.read_text())
                symbols = v1.symbol_indices(artifact["sym"])
                shapes = {}
                for port, key in (("in", "input_count"), ("out", "output_count")):
                    suffixes = infer_port(symbols, "main." + port, counts[key])
                    shapes[port + "_shape"] = [] if suffixes == [""] else [counts[key]]
                    if any(not 0 <= symbols[f"main.{port}{suffix}"] < counts["wire_count"] for suffix in suffixes):
                        raise Unsupported("wrapper_port_index_unavailable")
                prepared.update({"symbols": symbols, "interface": {"status": "passed", "reason": None,
                                  "command": command["id"], "sym": v1.ref(artifact["sym"]), **counts, **shapes}})
            except (ValueError, OSError) as error:
                prepared["interface"].update({"status": "unsupported", "reason": str(error)})
    return prepared, compilation


def not_run(reason):
    return {"calculation": "not_run", "constraint": "not_run", "export": "not_run", "evidence": {}, "reason": reason}


def run_case(runner, tools, project, data, folder):
    before, started = len(runner.records), time.perf_counter()
    result = {"case": data["id"], "optimization": "O0", "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "unsupported", "discovery_status": "not_run", "reason": None,
              "original_denominator": data["expected_original_inputs"], "boundary_denominator": data["expected_boundary_sets"],
              "originals": [], "boundaries": [], "compiles": [], "compile_uses": [],
              "timings": {k: 0.0 for k in ("preparation", "original_calculation_check_export", "input_link",
                                          "wrapper_calculation_check_export", "comparison")}}
    for input_id in data["input_ids"]:
        result["originals"].append({"input_id": input_id, **not_run("preparation_not_complete")})
        for prefix in data["expected_call_paths"]:
            result["boundaries"].append({"input_id": input_id, "original_prefix": prefix, "discovery": "not_run",
                "input_link": {"status": "not_run", "reason": "preparation_not_complete"},
                "wrapper": not_run("input_not_linked"), "input_recheck": {"status": "not_run", "reason": "wrapper_not_verified"},
                "output_comparison": {"status": "not_run", "reason": "wrapper_not_verified"}})
    try:
        _, stdout = runner.run("discovery", [tools["zkfdo"], "targets", "--project", project,
                              "--entrypoint", project / "main.circom", "--no-validate", "--output", folder / "discovery"], folder)
        report = json.loads(stdout.read_text())
        result["discovery_record"] = v1.ref(stdout)
        if report["entrypoint_status"] != "found" or report["unsupported"]:
            raise Unsupported("automatic_discovery_incomplete:" + json.dumps(report["unsupported"]))
        if not all(t["wrapper_status"] == "generated" for t in report["targets"]):
            raise Unsupported("automatic_wrapper_generation_incomplete")
        paths = v1.boundary_paths(report)
        if {p for _, p in paths} != set(data["expected_call_paths"]):
            raise Unsupported("discovered_call_path_denominator_changed")
        by_path = {p: t for t, p in paths}
        result.update({"discovery_status": "passed", "call_sites": len(report["targets"]),
                       "compile_units": len(report["compile_units"]), "call_paths": len(paths)})
        for b in result["boundaries"]:
            target = by_path[b["original_prefix"]]
            b.update({"discovery": "passed", "call_site": target["identity"], "instance_key": target["instance_key"],
                      "parameters": target["concrete_parameters"]})
        original, compilation = prepare_artifact(runner, tools, project / "main.circom", project, folder / "compiled-original")
        result["compiles"].append({"role": "original", **compilation, "interface": original["interface"]})
        units = {u["key"]: u for u in report["compile_units"]}
        artifacts, cache = {}, {}
        for index, target in enumerate(report["targets"]):
            source, unit = Path(target["generated_wrapper_path"]), units[target["compile_unit"]]
            if unit["unresolved_includes"] or target["identity"] not in unit["call_site_identities"]:
                raise Unsupported("incomplete_compile_unit_binding")
            for dependency in unit["dependencies"]:
                v1.require(v1.sha(dependency["path"]) == dependency["sha256"], "dependency_changed")
            key_data = {"wrapper": v1.sha(source), "dependencies": unit["dependencies"],
                        "compiler": v1.ref(tools["circom"]), "flags": ["--O0", *nc.FLAGS],
                        "library_paths": [str(project)], "timeout_seconds": 60}
            key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
            reused = key in cache
            if not reused:
                prepared, compilation = prepare_artifact(runner, tools, source, project, folder / f"compiled-wrapper-{index:02d}")
                cache[key] = prepared, compilation
                result["compiles"].append({"role": "wrapper", **compilation, "interface": prepared["interface"]})
            prepared, compilation = cache[key]
            artifacts[target["identity"]] = prepared
            result["compile_uses"].append({"call_site": target["identity"], "compile_unit": unit["key"],
                "cache_key": key, "cache_conditions": key_data, "reused": reused, "compile_command": compilation["command"]})
        result["timings"]["preparation"] = time.perf_counter() - started
        for index, (input_id, value) in enumerate(zip(data["input_ids"], data["inputs"])):
            begin = time.perf_counter()
            if original["interface"]["status"] != "passed":
                witness, normal = None, not_run("original_interface_unavailable:" + str(original["interface"]["reason"]))
            else:
                witness, normal = nc.calculate(runner, tools, original["artifact"], value,
                                               tuple(original["interface"]["in_shape"]), folder / f"normal-{index}/original")
            result["timings"]["original_calculation_check_export"] += time.perf_counter() - begin
            result["originals"][index].update(normal)
            for boundary_index, b in enumerate(r for r in result["boundaries"] if r["input_id"] == input_id):
                target = by_path[b["original_prefix"]]
                prepared = artifacts[target["identity"]]
                interface = prepared["interface"]
                b["interface"] = interface
                if interface["status"] != "passed":
                    b["input_link"] = {"status": "not_run", "reason": "wrapper_interface_unavailable:" + str(interface["reason"])}
                    continue
                begin = time.perf_counter()
                payload, link = read_inputs(original["symbols"], witness, prepared["symbols"], b["original_prefix"],
                                            interface["input_count"], normal)
                link["source_assignment"] = normal["evidence"].get("export")
                link["source_witness"] = normal["evidence"].get("witness")
                link["source_constraint_command"] = normal["evidence"].get("constraint_command")
                link["source_sym"] = v1.ref(original["artifact"]["sym"]) if original["artifact"] else None
                b["input_link"] = link
                result["timings"]["input_link"] += time.perf_counter() - begin
                if payload is None:
                    b["wrapper"]["reason"] = "input_link_" + link["status"] + ":" + str(link["reason"])
                    continue
                begin = time.perf_counter()
                wrapper, wrapper_normal = nc.calculate(runner, tools, prepared["artifact"], payload["in"],
                    tuple(link["shape"]), folder / f"normal-{index}/boundary-{boundary_index:02d}")
                b["wrapper"] = wrapper_normal
                link["destination_input"] = wrapper_normal["evidence"].get("input")
                result["timings"]["wrapper_calculation_check_export"] += time.perf_counter() - begin
                begin = time.perf_counter()
                for port, key, count_key in (("in", "input_recheck", "input_count"), ("out", "output_comparison", "output_count")):
                    b[key] = compare_port(original["symbols"], witness, prepared["symbols"], wrapper,
                                           b["original_prefix"], port, interface[count_key], normal, wrapper_normal)
                result["timings"]["comparison"] += time.perf_counter() - begin
        normals = result["originals"] + [b["wrapper"] for b in result["boundaries"]]
        failed = (any(c["status"] == "failed" or c["interface"]["status"] == "failed" for c in result["compiles"])
                  or any(n[k] == "failed" for n in normals for k in ("calculation", "constraint", "export"))
                  or any(b[k]["status"] == "mismatched" for b in result["boundaries"] for k in ("input_recheck", "output_comparison")))
        complete = (all(verified(n) for n in normals)
                    and all(b["input_link"]["status"] == "passed" and b["input_recheck"]["status"] == "matched"
                            and b["output_comparison"]["status"] == "matched" for b in result["boundaries"]))
        result["status"] = "failed" if failed else "passed" if complete else "unsupported"
    except (ValueError, OSError, KeyError, v1.ProcessFailure) as error:
        result["reason"] = str(error)
        result["status"] = "failed" if isinstance(error, (OSError, v1.ProcessFailure)) else "unsupported"
        if result["discovery_status"] == "not_run":
            result["discovery_status"] = result["status"]
        if result["timings"]["preparation"] == 0:
            result["timings"]["preparation"] = time.perf_counter() - started
        for row in result["originals"]:
            if row["reason"] == "preparation_not_complete":
                row["reason"] = result["reason"]
        for b in result["boundaries"]:
            if b["input_link"]["reason"] == "preparation_not_complete":
                b["input_link"]["reason"] = result["reason"]
    commands = runner.records[before:]
    result.update({"finished_at": datetime.now(timezone.utc).isoformat(), "case_wall_seconds": time.perf_counter() - started,
        "command_ids": [r["id"] for r in commands],
        "compile_processes": sum(r["stage"] == "compile" and r["process_started"] for r in commands),
        "compile_successes": sum(c["status"] == "passed" for c in result["compiles"]),
        "original_calculation_counts": dict(Counter(o["calculation"] for o in result["originals"])),
        "original_constraint_counts": dict(Counter(o["constraint"] for o in result["originals"])),
        "wrapper_calculation_counts": dict(Counter(b["wrapper"]["calculation"] for b in result["boundaries"])),
        "wrapper_constraint_counts": dict(Counter(b["wrapper"]["constraint"] for b in result["boundaries"])),
        **{k + "_counts": dict(Counter(b[k]["status"] for b in result["boundaries"]))
           for k in ("input_link", "input_recheck", "output_comparison")}})
    v1.write_json(folder / "result.json", result)
    print(json.dumps({k: result[k] for k in ("case", "status", "compile_processes", "input_link_counts",
                                           "output_comparison_counts", "timings")}), flush=True)
    return result


def forbidden_manual_adapter(*_args, **_kwargs):
    raise RuntimeError("manual_fixture_formula_forbidden_in_NB01")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zkfdo", type=Path, default=ROOT / "target/debug/zkfDO")
    args = parser.parse_args()
    output = args.output.resolve()
    v1.require(output.is_relative_to(ROOT / "runs"), "raw_output_must_be_under_runs")
    subprocess.run(["git", "check-ignore", "--quiet", str(output)], cwd=ROOT, check=True)
    v1.require(v1.sha(output / "input-plan.json") == PLAN_HASH, "input_plan_changed")
    v1.require(v1.sha(ROOT / "scripts/measure_normal_compatibility.py") == NC_HASH, "NC01_code_changed")
    v1.require(v1.sha(ROOT / "scripts/measure_normal_preparation.py") == nc.V1_SHA256, "v1_code_changed")
    plan = json.loads((output / "input-plan.json").read_text())
    runner = v1.Runner(output)
    provenance = output / "provenance"
    provenance.mkdir()
    for p in (Path(__file__), ROOT / "scripts/measure_normal_compatibility.py", ROOT / "scripts/measure_normal_preparation.py",
              ROOT / "src/targets.rs", args.zkfdo):
        shutil.copy2(p, provenance / p.name)
    tools = {name: Path(shutil.which(name)).resolve() for name in ("circom", "node", "snarkjs")}
    tools["zkfdo"] = provenance / args.zkfdo.name
    versions = {}
    for name, path in tools.items():
        command, stdout = runner.run("version", [path, "--version"], output / "versions", check=False)
        lines = stdout.read_text().splitlines()
        versions[name] = {"file": v1.ref(path), "version_line": lines[0] if lines else None,
                          "command": command["id"], "exit_code": command["exit_code"]}
    projects = output / "projects"
    projects.mkdir()
    for data in plan["cases"]:
        for source in data["source_files"]:
            v1.require(v1.sha(ROOT / source["path"]) == source["sha256"], "source_changed")
        shutil.copytree(ROOT / data["source"], projects / data["id"])
    nc.adapter = forbidden_manual_adapter
    nc.oracle = forbidden_manual_adapter
    conditions = {"version": "normal-boundary-replay-v1", "id": "NB-01", "owner": "miiz",
        "created_at": datetime.now(timezone.utc).isoformat(), "input_plan": v1.ref(output / "input-plan.json"),
        "scope": v1.ref(ROOT / "reports/n4-1-normal-boundary-replay-2026-10-02/SCOPE.md"),
        "script": v1.ref(provenance / Path(__file__).name), "tools": versions,
        "code_dependencies": [v1.ref(provenance / name) for name in ("measure_normal_compatibility.py", "measure_normal_preparation.py", "targets.rs")],
        "source_files": [v1.ref(p) for p in sorted(projects.rglob("*.circom"))],
        "flags": ["--O0", *nc.FLAGS], "host": platform.platform(), "python": platform.python_version(),
        "original_denominator": 9, "boundary_denominator": 45,
        "input_source": "verified original witness export at discovered call path .in only",
        "manual_adapter_and_oracle_runtime_guards": True,
        "wrapper_output_source": "fresh normal calculator process and separate full witness check",
        "cache": "empty per fixture; full compile key reused within fixture; separate assignments per call/input; OS cache not flushed",
        "timing_scope": "preparation; original calculation/check/export; input linking; wrapper calculation/check/export; comparison. Snapshot/version/final manifest/tests/report excluded.",
        "execution": "three fixed O0 fixtures, three existing inputs each, once. No experiment aggregate."}
    v1.write_json(output / "conditions.json", conditions)
    results = [run_case(runner, tools, projects / data["id"], data, output / data["id"]) for data in plan["cases"]]
    v1.write_json(output / "artifact-manifest.json", [v1.ref(p) for p in sorted(output.rglob("*")) if p.is_file()])
    v1.write_json(output / "summary.json", {"version": "normal-boundary-replay-v1", "results": results,
        "conditions": v1.ref(output / "conditions.json"), "process_ledger": v1.ref(runner.ledger),
        "manifest": v1.ref(output / "artifact-manifest.json"),
        "limitation": "normal replay of existing development samples; not universal semantic equivalence or candidate projection"})
    return 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
