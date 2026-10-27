#!/usr/bin/env python3
"""Post-deadline replay / Policy B S / new-candidate J. Never runs W or frozen J.

All stages need a SHA-pinned JSON plan, a new output directory and --execute.
No execution is possible before 2026-10-28T15:00:00Z. See report for contracts.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, os, signal, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
import s_round4b_monitor_20261027 as monitor
import run_policy_b_order as policy

ROOT=monitor.ROOT
DEADLINE=datetime(2026,10,28,15,tzinfo=timezone.utc)
POLICY_SHA="edfc21d7c82353ce01a0b1a83958a7f885cd55ec4e5cb83815cc45f138319076"
SEEDS=(2026100601,2026100602,2026100603)

def require(ok, message):
    if not ok:raise ValueError(message)

def path(value):
    p=Path(value).absolute()
    require(not any(x.startswith(("n6-a-remeasure-2026-10-25","n6-b6","h1-")) for x in p.parts),"protected path")
    require(p.is_relative_to(ROOT) and not p.is_relative_to(ROOT/"target"),"outside repository or old target")
    require(p.resolve().is_relative_to(ROOT),"external link")
    return p

def digest(p):
    h=hashlib.sha256()
    with path(p).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def ref(value):
    p=path(value["path"])
    require(digest(p)==value["sha256"],"SHA mismatch: "+str(p))
    return p

def document(value):return json.loads(ref(value).read_text())
def save(p,v):return monitor.write_new(p,v)

def deadline(now=None):
    require((now or datetime.now(timezone.utc))>=DEADLINE,"deadline not reached; no execution")

def availability(peak,retained):
    require(type(peak) is int and peak>0 and type(retained) is int and retained>=0,"measured positive peak and retained bytes required")
    monitor.gate()
    needed=max(20*monitor.GIB,(6*peak+4)//5+retained)
    require(monitor.free_bytes()>=needed,"internal 1.2 x peak + retained gate")
    ps=subprocess.run(["/bin/ps","-axo","pid=,comm=,args="],capture_output=True,text=True,check=True).stdout
    for line in ps.splitlines():
        fields=line.strip().split(None,2)
        if len(fields)<3 or int(fields[0]) in (os.getpid(),os.getppid()):continue
        executable=Path(fields[1]).name;args=fields[2]
        if executable in {"circom","cargo","zkFuzz","zkfDO","zkfdo-j-v23","zkfDO-v2.3-development"} or any(name in args for name in ("n6_a_remeasure_aq_execute_","n6_a_remeasure_aq_switch","run_n6_v4_queue.py")):
            raise ValueError("another heavy run remains active; no process was touched")

def engine_command(plan,request,output):
    engine=ref(plan["engine"])
    require(engine.is_relative_to(monitor.RUNROOT),"new engine must stay in Round4")
    args=[str(engine),"--request",str(request),"--output",str(output),"--cache",str(output.parent/"cache"),"--instance-store",str(output.parent/"instance-store")]
    for flag in ("circom","node","snarkjs","z3"):
        tool=plan["tools"][flag];p=Path(tool["path"])
        require(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==tool["sha256"],"tool SHA mismatch")
        args += ["--"+flag+"-bin",str(p)]
    return args

def verdict(result):
    """Compare scientific outcomes, excluding cache paths, timings and engine IDs."""
    return {"preparation":result.get("preparation"),"classification":result.get("component_classification"),
            "verdict_counts":result.get("verdict_counts"),"sites_found":result.get("sites_found"),
            "classes":sorted((r.get("pattern"),r.get("representative"),r.get("sites"),r.get("verdict"),r.get("reason"),r.get("assumption_predicate_verdict")) for r in result.get("classes",[]))}

def run_j(plan,row,folder,label):
    pinned={ref(item).resolve() for item in row["inputs"]}
    request=ref(row["request"]);value=json.loads(request.read_text())
    require(Path(value["source_root"]).is_absolute(),"absolute request source_root required")
    # Existing requests are read in place, preserving their relative-path semantics.
    for item in [value.get(k) for k in ("component_wrapper","entrypoint","base_input")]+[value["candidate"]["path"]]:
        if item:require(path(Path(value["source_root"])/item).resolve() in pinned,"request input missing from pins")
    if "component_view" in value:
        viewref=value["component_view"];vp=request.parent/viewref["spec"]
        require(digest(vp)==viewref["sha256"],"view SHA mismatch")
    availability(row["peak_bytes"],row["retained_bytes"])
    folder.mkdir(parents=True,exist_ok=False)
    run=monitor.run(engine_command(plan,request,folder/"result"),label,row.get("timeout_seconds",10800))
    require(run["status"]=="completed","J process failed; stop batch")
    result=json.loads((folder/"result/result.json").read_text())
    cleanup_generated(folder)
    return result,run

def cleanup_generated(folder):
    """Only newly owned generated files; retain R1CS, JSON, logs and source."""
    folder=monitor.owned(folder);removed=[]
    for p in sorted(folder.rglob("*"),key=lambda p:len(p.parts),reverse=True):
        require(not p.is_symlink(),"unexpected symlink in generated output")
        if p.is_file() and (p.suffix in (".sym",".wasm") or any(x.endswith(("_js","_cpp")) for x in p.relative_to(folder).parts)):
            removed.append({"path":str(p),"sha256":digest(p),"bytes":p.stat().st_size});p.unlink()
        elif p.is_dir() and p.name.endswith(("_js","_cpp")) and not any(p.iterdir()):p.rmdir()
    save(folder/"generated-cleanup.json",{"removed":removed})

def replay(plan,out):
    rows=[]
    require(plan["baseline_engine_sha256"]=="c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835","baseline must identify frozen v2.2")
    require(bool(plan["requests"]),"nonempty completed request sample required")
    for i,row in enumerate(plan["requests"]):
        old=document(row["completed_result"])
        require(old.get("preparation",{}).get("status")=="ok","sample must be completed")
        request=document(row["request"])
        require("component_view" not in request and request["schema"]=="zkfdo-lifting-request-v1","replay uses unchanged legacy requests")
        require(old.get("request_sha256")==row["request"]["sha256"],"baseline/request SHA mismatch")
        new,run=run_j(plan,row,out/str(i),f"post-{out.name}-replay-{i}")
        equal=verdict(old)==verdict(new)
        rows.append({"request":row["request"],"baseline":row["completed_result"],"same_verdict":equal,"monitor":run["receipt"]})
        save(out/(str(i)+"-comparison.json"),rows[-1])
        require(equal,"verdict difference; later requests stopped")
    save(out/"summary.json",{"stage":"replay","passed":True,"requests":rows})

def selected_revisions(manifest):
    rows=[r for r in manifest["rows"] if r["phase"]=="A-Q"]
    require(len(rows)==15 and len({r["identifier"] for r in rows})==15,"frozen A-Q manifest denominator changed")
    return [r["identifier"] for r in rows]

def reorder(spec,metadata):
    spec=copy.deepcopy(spec)
    require(spec["method"]=="split" and spec["total_budget_seconds"]==600 and spec["attempt_cap_seconds"]==30,"only S with frozen 600/30 budget")
    ordered=policy.policy_b_order(metadata["targets"])
    targets={r["target_id"]:r for r in spec["targets"]}
    ids=[r["target_id"] for r in ordered]
    require(len(ids)==len(set(ids)) and set(ids)==set(targets),"prepared target set/order metadata mismatch")
    spec["targets"]=[targets[i] for i in ids]
    return spec,ids

def campaign_child(spec_path, preflight, output, preparation=False):
    """Use the old runner's cancellation hook to stop its own detached descendants."""
    deadline()
    import run_policy_a_engine_v4 as engine
    cancelled=False;last_check=0.;disk_low=False
    def stop(_signal,_frame):
        nonlocal cancelled
        cancelled=True
    signal.signal(signal.SIGTERM,stop)
    def cancel():
        nonlocal last_check,disk_low
        if time.monotonic()-last_check>=1:
            last_check=time.monotonic();disk_low=monitor.free_bytes()<18*monitor.GIB
        return cancelled or disk_low
    with engine.installed():
        if preparation:
            engine._ACTIVE_METHOD="split"
            original=engine.v1.spawn_and_measure
            def guarded(command, directory, end, start, original_cancel):
                return original(command,directory,end,start,lambda:cancel() or original_cancel())
            engine.v1.spawn_and_measure=guarded
            result=engine.v1.preflight(Path(spec_path),monitor.owned(output))
            require(result["ledger"]["status"]!="failed","S preflight failed")
            return
        spec,sha=engine.v1.load_spec(Path(spec_path))
        snapshots,root=engine.v1.read_preflight(spec,sha,Path(preflight))
        result=engine.v1.run_campaign(spec,sha,snapshots,root,monitor.owned(output),cancel_check=cancel)
    require(result["ledger"]["status"]=="completed","S stopped or failed")

def fuzz(plan,out):
    # The new prepared specs are inputs: preparation/compilation is outside S's 600s.
    # They must come from Round4, including the tag adapter sidecars where needed.
    require(digest(ROOT/"scripts/run_policy_b_order.py")==POLICY_SHA,"fixed policy changed")
    manifest=document(plan["revision_manifest"]);revisions=selected_revisions(manifest)
    queue=document(plan["queue"])
    keys={(u["identifier"],u["seed"]) for u in queue["units"] if u["identifier"] in revisions}
    require(keys=={(r,s) for r in revisions for s in SEEDS},"existing queue does not cover frozen manifest seeds")
    jobs=plan["jobs"]
    require(len(jobs)==len(keys) and {(j["revision"],j["seed"]) for j in jobs}==keys,"job bundle must cover exactly all manifest revisions and seeds")
    runner=ref(plan["s_runner"])
    require(runner==ROOT/"scripts/run_policy_a_engine_v4.py","use unchanged S v4 execution mechanics")
    rows=[]
    for i,j in enumerate(jobs):
        availability(j["peak_bytes"],j["retained_bytes"])
        specpath=ref(j["prepared_spec"]);require(specpath.is_relative_to(monitor.RUNROOT),"new prepared spec required")
        spec,ids=reorder(document(j["prepared_spec"]),document(j["order_metadata"]))
        require(spec["initial_seed"]==j["seed"] and spec["concurrency"]==1,"seed/concurrency mismatch")
        require(spec["memory_cap_bytes"]==10*monitor.GIB,"original S memory cap must stay 10 GiB")
        for snap in spec["source_snapshots"]:require(path(snap["path"]).is_relative_to(monitor.RUNROOT),"new prepared source snapshot required")
        folder=out/str(i);folder.mkdir()
        for pin in spec.get("pinned_files",[]):
            if pin["label"]=="plan":
                old=document(pin);byid={r["target_id"]:r for r in old["targets"]}
                require(set(byid)==set(ids),"pinned plan target mismatch")
                old["targets"]=[byid[t] for t in ids];new=save(folder/"ordered-plan.json",old);pin.update(new)
        save(folder/"spec.json",spec)
        command=[sys.executable,"-B",str(Path(__file__).resolve())]
        # Each preflight and campaign runs separately; the runner retains its original
        # 10 GiB physical-memory cap, cleanup, seed transport and 600s deadline.
        r=monitor.run(command+["_preflight",str(folder/"spec.json"),"unused",str(folder/"preflight")],f"post-{out.name}-preflight-{i}",10800)
        require(r["status"]=="completed","S preflight failed")
        if (folder/"preflight/compile").exists():cleanup_generated(folder/"preflight/compile")
        r=monitor.run([sys.executable,"-B",str(Path(__file__).resolve()),"_campaign",str(folder/"spec.json"),str(folder/"preflight/preflight.json"),str(folder/"campaign")],f"post-{out.name}-S-{i}",900)
        require(r["status"]=="completed","S campaign failed")
        rows.append({"revision":j["revision"],"seed":j["seed"],"policy_sha256":POLICY_SHA,"spec":str(folder/"spec.json"),"campaign":str(folder/"campaign"),"monitor":r["receipt"]})
        save(folder/"binding.json",rows[-1])
    save(out/"summary.json",{"stage":"S-policy-B","runs":rows,"W_runs":0})

def new_candidates(plan,out):
    old=document(plan["old_candidate_inventory"])
    require(old.get("complete") is True,"complete old candidate hash inventory required")
    seen=set(old["sha256"]);rows=[]
    require(isinstance(plan["requests"],list),"new candidate requests must be a list")
    for i,row in enumerate(plan["requests"]):
        candidate=ref(row["candidate"])
        require(candidate.is_relative_to(monitor.RUNROOT),"only newly produced local candidates")
        value=document(row["request"])
        base=Path(value["source_root"])
        require((base/value["candidate"]["path"]).resolve()==candidate.resolve(),"request/candidate binding mismatch")
        ledger=document(row["S_ledger"])
        hashes={c["sha256"] for a in ledger["attempts"] for c in a.get("candidates",[])}
        sha=row["candidate"]["sha256"];require(sha in hashes,"candidate absent from pinned new S ledger")
        if sha in seen:
            rows.append({"sha256":sha,"status":"old_or_duplicate_skipped"});continue
        seen.add(sha)
        result,run=run_j(plan,row,out/str(i),f"post-{out.name}-new-J-{i}")
        rows.append({"sha256":sha,"status":"completed","monitor":run["receipt"],"verdict_counts":result.get("verdict_counts")})
    save(out/"summary.json",{"stage":"new-candidates-only","requests":rows})

def main():
    if len(sys.argv)>1 and sys.argv[1] in ("_campaign","_preflight"):
        campaign_child(*sys.argv[2:],preparation=sys.argv[1]=="_preflight");return
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage",choices=("replay","S","new-J"));p.add_argument("--plan",required=True);p.add_argument("--plan-sha256",required=True);p.add_argument("--output",required=True);p.add_argument("--execute",action="store_true")
    a=p.parse_args();require(a.execute,"write/execute is opt-in; --execute required");deadline()
    require(os.getpriority(os.PRIO_PROCESS,0)==19,"nice 19 required")
    plan=document({"path":a.plan,"sha256":a.plan_sha256});out=monitor.owned(a.output);out.mkdir(parents=True,exist_ok=False)
    {"replay":replay,"S":fuzz,"new-J":new_candidates}[a.stage](plan,out)
if __name__=="__main__":main()
