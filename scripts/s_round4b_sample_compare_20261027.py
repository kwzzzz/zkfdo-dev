#!/usr/bin/env python3
"""Compile-only comparison of small real wrappers. No candidates or judging."""
import argparse
import hashlib
import json
from pathlib import Path

import s_round4b_monitor_20261027 as monitor
import s_round4_synthetic_20261027 as check
import s_tag_wrapper_prototype_20261027 as prototype

ROOT = monitor.ROOT
COMPILER = ROOT / "runs/c02-corpus-2026-10-02/tools/circom"
COMPILER_SHA = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
PRIME = check.PRIME


def canonical(data, symbols, prefix):
    parent = list(range(data["shape"]["wires"]))
    def root(w):
        while parent[w] != w:
            parent[w] = parent[parent[w]]
            w = parent[w]
        return w
    for triple in data["constraints"]:
        linear = check.linear_constraint(triple)
        if linear is not None and len(linear) == 2 and 0 not in linear:
            (a,x),(b,y) = linear.items()
            if (x+y) % PRIME == 0:
                parent[root(b)] = root(a)
    aliases = {}
    for name, wire in symbols.items():
        if name.startswith(prefix) and wire >= 0:
            aliases.setdefault(root(wire), set()).add("main."+name[len(prefix):])
    names = {w: min(values) for w, values in aliases.items()}
    names[root(0)] = "$one"
    if set(root(w) for w in range(data["shape"]["wires"])) - set(names):
        raise ValueError("unmapped internal wire")
    polynomials = []
    for a,b,c in data["constraints"]:
        if len(a)*len(b)>1_000_000:
            raise ValueError("polynomial expansion cap")
        poly = {}
        for wa,va in a.items():
            for wb,vb in b.items():
                key = tuple(sorted(n for n in (names[root(wa)],names[root(wb)]) if n != "$one"))
                poly[key]=(poly.get(key,0)+va*vb)%PRIME
        for w,v in c.items():
            key=() if names[root(w)]=="$one" else (names[root(w)],)
            poly[key]=(poly.get(key,0)-v)%PRIME
        terms=sorted((k,v) for k,v in poly.items() if v)
        if terms:
            scale=pow(terms[0][1],-1,PRIME)
            polynomials.append(tuple((k,v*scale%PRIME) for k,v in terms))
    roles={}; first=1
    for role in ("public_outputs","public_inputs","private_inputs"):
        leaves=[]
        for w in range(first,first+data["shape"][role]):
            direct=[n for n,wire in symbols.items() if wire==w and n.startswith("main.") and "." not in n[5:]]
            if len(direct)!=1:raise ValueError("ambiguous IO role")
            leaves.append(direct[0])
        roles[role]=sorted(leaves);first+=data["shape"][role]
    return {"polynomials":sorted(polynomials),"aliases":sorted(sorted(v) for v in aliases.values()),"roles":roles}


def strip_input_tags(source, template):
    definitions=[d for d in prototype.definitions(source) if d["name"]==template]
    if len(definitions)!=1:raise ValueError("ambiguous template")
    body=definitions[0]["body"]; edits=[]
    for i in range(len(body)-2):
        if [t.text for t in body[i:i+3]]==["signal","input","{"]:
            end=prototype.match(body,i+2,"{","}")
            edits.append((body[i+2].start,body[end].end))
    changed=source
    for a,b in reversed(edits): changed=changed[:a]+''.join('\n' if c=='\n' else ' ' for c in changed[a:b])+changed[b:]
    if not edits:raise ValueError("sample has no tagged inputs")
    return changed,edits


def compile_one(source, folder, args, label):
    folder.mkdir()
    run=monitor.run([str(COMPILER),str(source),"--r1cs","--sym","--O0","--prime","bn128","--output",str(folder),*args],label,120)
    sp=folder/(source.stem+".sym"); rp=folder/(source.stem+".r1cs")
    if run["returncode"]!=0:
        return None,run
    data=check.parse_r1cs(rp.read_bytes())
    if data["shape"]["constraints"]>10000:raise ValueError("sample O0 constraints exceed 10,000")
    symbols=check.parse_symbols(sp.read_bytes(),data)
    monitor.write_new(folder/"artifacts.json",{"r1cs":{"path":str(rp),"sha256":hashlib.sha256(rp.read_bytes()).hexdigest()},
        "removed_sym":{"path":str(sp),"sha256":hashlib.sha256(sp.read_bytes()).hexdigest()},"shape":data["shape"]})
    sp.unlink()
    return (data,symbols),run


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",required=True);a=p.parse_args()
    if hashlib.sha256(COMPILER.read_bytes()).hexdigest()!=COMPILER_SHA:raise ValueError("compiler SHA mismatch")
    monitor.gate();base=monitor.owned(a.output);base.mkdir(parents=True,exist_ok=False)
    plan=json.loads((ROOT/"runs/s-tag-wrapper-2026-10-27/prototype-v2/planned.json").read_text())
    summary=json.loads((ROOT/"runs/s-tag-wrapper-2026-10-27/compile/summary.json").read_text())
    rows={(r["unit"],r["label"]):r for r in plan["targets"]}
    # Selection is frozen by size then template, without loading any RQ-C mapping.
    selected=[];seen=set()
    for r in sorted(summary["results"],key=lambda r:(r["constraints"],r["template"],r["unit"])):
        if not 0<r["constraints"]<=10000:continue
        if len(seen)<3 or r["template"] in seen:
            seen.add(r["template"]);selected.append(r)
    monitor.write_new(base/"selection.json",{"rule":"three smallest distinct templates with positive recorded constraints <= 10000, both units", "selected":selected})
    results=[]
    for i,item in enumerate(selected):
        row=rows[(item["unit"],item["label"])]; folder=base/str(i);folder.mkdir()
        source=Path(row["defining_source_file"]); wrapper=Path(row["wrapper"]["path"])
        if hashlib.sha256(wrapper.read_bytes()).hexdigest()!=row["wrapper"]["sha256"]:raise ValueError("wrapper SHA mismatch")
        reference,edits=strip_input_tags(source.read_text(),row["template"])
        refsource=folder/"reference-source.circom"; refsource.write_text(reference)
        refmain=folder/"reference.circom";refmain.write_text(prototype.legacy_wrapper(refsource,row["template"],row["concrete_parameters"]))
        args=row["definition"]["compile_args"]+["-l",str(source.parent)]
        ref,rr=compile_one(refmain,folder/"reference",args,f"b-sample-{base.name}-{i}-ref")
        bridge,br=compile_one(wrapper,folder/"bridge",args,f"b-sample-{base.name}-{i}-bridge")
        result={"unit":row["unit"],"template":row["template"],"recorded_constraints":item["constraints"],
            "source":str(source),"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"tag_only_edits":edits,
            "reference_compile":rr["receipt"],"bridge_compile":br["receipt"],"passed":False}
        if ref and bridge:
            rv=canonical(*ref,"main."); bv=canonical(*bridge,"main.__s_tag_target.")
            result.update(passed=rv==bv,reference_polynomials=len(rv["polynomials"]),bridge_polynomials=len(bv["polynomials"]),
                          reference_sha256=hashlib.sha256(json.dumps(rv,sort_keys=True).encode()).hexdigest(),
                          bridge_sha256=hashlib.sha256(json.dumps(bv,sort_keys=True).encode()).hexdigest())
        else:result["reason"]="compile_failed; not counted as equivalence"
        results.append(result);monitor.write_new(folder/"comparison.json",result)
        if ref and bridge and not result["passed"]:
            break
    monitor.write_new(base/"summary.json",{"passed":len(results)==len(selected) and all(r["passed"] for r in results),"results":results})
    print(json.dumps({"samples":len(results),"passed":sum(r["passed"] for r in results),"output":str(base)},ensure_ascii=False))
    raise SystemExit(0 if len(results)==len(selected) and all(r["passed"] for r in results) else 2)


if __name__=="__main__":main()
