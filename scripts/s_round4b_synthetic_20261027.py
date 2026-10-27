#!/usr/bin/env python3
"""Only tiny, newly generated synthetic circuits; never loads an aq/B request."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

import s_tag_wrapper_prototype_20261027 as prototype
import s_round4_synthetic_20261027 as r1cs_reader
import s_round4b_monitor_20261027 as monitor

ROOT = monitor.ROOT
COMPILER = ROOT / "runs/c02-corpus-2026-10-02/tools/circom"
COMPILER_SHA = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"


def save(path, value):
    raw = value.encode() if isinstance(value, str) else (json.dumps(value, indent=2) + "\n").encode()
    with path.open("xb") as f:
        f.write(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def execute_case(base, name, engine):
    folder = base / name
    folder.mkdir()
    tcct, legacy = name == "tcct", name == "legacy"
    tag = "" if legacy else "{binary} "
    rule = "y[i] <-- x[i]*x[i]+7;" if tcct else "y[i] <== x[i]*x[i]+7;"
    source = folder / "target-source.circom"
    save(source, "pragma circom 2.1.6;\ntemplate Tagged(n) {\n" +
         f" signal input {tag}x[n];\n signal output y[n];\n for (var i=0;i<n;i++) {{ {rule} }}\n}}\n")
    original = save(folder / "original-fragment-spec.json", {"template": "Tagged", "arguments": ["2"], "synthetic_only": True})
    text, tags, _ = prototype.render_prototype(source, source.read_text(), "Tagged", ["2"], {source: source.read_text()})
    if text is None:
        raise ValueError("synthetic wrapper refused")
    wrapper = save(folder / "target.circom", text)
    context_constraint = "signal output keep[2]; for (var i=0;i<2;i++) { keep[i] <== x[i]*x[i]; }" if tcct else ""
    entry = save(folder / "entry.circom", f'''pragma circom 2.1.6;
include "{source.name}";
template Whole() {{
 signal input x[2];
 signal output y[2];
 signal {{binary}} bridge[2];
 component a = Tagged(2);
 for (var i=0;i<2;i++) {{ bridge[i] <== x[i]; a.x[i] <== bridge[i]; }}
 for (var i=0;i<2;i++) {{ y[i] <== a.y[i]; }}
 {context_constraint}
}}
component main = Whole();
''')
    compiled = folder / "compile"
    compiled.mkdir()
    row = monitor.run([str(COMPILER), wrapper["path"], "--r1cs", "--sym", "--O0", "--output", str(compiled)], "b-syn-"+base.name+"-"+name+"-compile", 90)
    if row["returncode"] != 0:
        raise RuntimeError("synthetic compile failed")
    r = r1cs_reader.parse_r1cs((compiled / "target.r1cs").read_bytes())
    if r["shape"]["constraints"] > 1000:
        raise ValueError("synthetic exceeds 1,000 constraints; judging refused")
    symbols = r1cs_reader.parse_symbols((compiled / "target.sym").read_bytes(), r)
    assignment = {}
    for key in symbols:
        index = int(re.search(r"\[(\d+)\]$", key)[1])
        assignment[key] = str((index+2)**2 + 7 + (1 if tcct else 0)) if re.search(r"\.y\[", key) else str(index+2)
    candidate = save(folder / "candidate.json", assignment)
    inp = save(folder / "base-input.json", {"x": ["2", "3"]})
    request = {"schema": "zkfdo-lifting-request-v1" if legacy else "zkfdo-lifting-request-v2.3", "id": "round4b-synthetic-"+name,
               "source_root": str(folder), "component_wrapper": wrapper["path"], "entrypoint": entry["path"],
               "base_input": inp["path"], "candidate": {"format": "named", "path": candidate["path"]}}
    if not legacy:
        spec = save(folder / "view.json", {"schema": "zkfdo-component-view-v1", "target_prefix": "main.__s_tag_target",
            "target_template": "Tagged", "target_source": str(source), "target_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "wrapper_sha256": wrapper["sha256"], "original_fragment_spec": original["path"], "original_fragment_spec_sha256": original["sha256"],
            "concrete_arguments": ["2"], "attached_without_enforcement": [{"input": "x", "tag": "binary", "value": None}]})
        request["component_view"] = {"spec": spec["path"], "sha256": spec["sha256"]}
    req = save(folder / "request.json", request)
    output = folder / "j-output"
    argv = [str(engine), "--request", req["path"], "--output", str(output), "--cache", str(folder/"cache"),
            "--instance-store", str(folder/"instance-store"), "--circom-bin", str(COMPILER),
            "--node-bin", shutil.which("node"), "--snarkjs-bin", shutil.which("snarkjs"), "--z3-bin", shutil.which("z3")]
    if any(x is None for x in argv):
        raise ValueError("required installed synthetic tool absent")
    run = monitor.run(argv, "b-syn-"+base.name+"-"+name+"-j-v23", 180)
    result = json.loads((output / "result.json").read_text()) if (output / "result.json").exists() else {}
    expected_schema = "zkfdo-lifting-result-v1" if legacy else "zkfdo-lifting-result-v2.3"
    passed = (run["returncode"] == 0 and result.get("schema") == expected_schema and
              result.get("preparation", {}).get("status") == "ok" and result.get("sites_found", 0) >= 1 and
              result.get("component", {}).get("candidate_satisfies_component_o0") is True)
    if tcct:
        passed = passed and result.get("verdict_counts", {}).get("entrypoint_violation", 0) >= 1
    # Only this invocation's generated symbols and witness-generator directories.
    removed = []
    for p in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if p.is_symlink():
            raise ValueError("unexpected synthetic artifact symlink")
        if p.is_file() and (p.suffix in (".sym", ".wasm") or any(x.endswith(("_js", "_cpp")) for x in p.parts)):
            removed.append({"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size})
            p.unlink()
        elif p.is_dir() and p.name.endswith(("_js", "_cpp")) and not any(p.iterdir()):
            p.rmdir()
    receipt = {"name": name, "passed": bool(passed), "constraints": r["shape"]["constraints"], "view_present": not legacy,
               "schema": result.get("schema"), "preparation": result.get("preparation"), "sites_found": result.get("sites_found"),
               "verdict_counts": result.get("verdict_counts"), "monitor": run["receipt"], "removed_owned_artifacts": removed}
    save(folder / "check.json", receipt)
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--engine", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    engine = monitor.owned(a.engine)
    if not engine.is_relative_to(monitor.RUNROOT):
        raise ValueError("only the new local engine is allowed")
    if hashlib.sha256(COMPILER.read_bytes()).hexdigest() != COMPILER_SHA:
        raise ValueError("compiler SHA mismatch")
    monitor.gate()
    base = monitor.owned(a.output)
    base.mkdir(parents=True, exist_ok=False)
    rows = []
    for name in ("view", "legacy", "tcct"):
        rows.append(execute_case(base, name, engine))
        if not rows[-1]["passed"]:
            break
    passed = len(rows) == 3 and all(r["passed"] for r in rows)
    print(json.dumps(save(base/"summary.json", {"passed": passed, "cases": rows}), ensure_ascii=False))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
