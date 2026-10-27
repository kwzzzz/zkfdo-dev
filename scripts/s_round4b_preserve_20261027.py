#!/usr/bin/env python3
"""Reinspect explicit recorded cohorts; no directory discovery, compiler or J."""
import json, hashlib, subprocess, sys
from pathlib import Path
import s_round4b_monitor_20261027 as m
from s_inspection_measure_20261026 import compare_rows

def load(p, expected=None):
    p=Path(p); raw=p.read_bytes()
    if expected and hashlib.sha256(raw).hexdigest()!=expected:raise ValueError("SHA mismatch: "+str(p))
    return json.loads(raw)

def main():
    out=m.owned(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
    binary=m.TARGET/"debug/examples/s_inspection_audit"
    summaries=[m.ROOT/"runs/s-inspection-improve-2026-10-27/preserve-after/measurement.json",m.ROOT/"runs/s-inspection-improve-2026-10-27/after/measurement.json"]
    results=[];protected=set()
    for group,summary in enumerate(summaries):
        for item in load(summary)["units"]:
            m.gate(); old=load(item["output"],item["sha256"])
            source=Path(old["prepared_path"]);load(source,old["prepared_sha256"])
            target=out/(str(group)+"-"+item["unit"]+".json")
            run=subprocess.run([str(binary),str(source),str(target)],check=False)
            if run.returncode:raise RuntimeError("inspection failed")
            new=load(target); diff=compare_rows(old["targets"],new["targets"])
            for row in old["targets"]:
                if row["inspection_eligible"] or row["old_eligible"]:protected.add((item["unit"],row["label"]))
            result={"unit":item["unit"],"baseline":item["output"],"baseline_sha256":item["sha256"],"output":str(target),"output_sha256":hashlib.sha256(target.read_bytes()).hexdigest(),**diff}
            results.append(result)
            print(json.dumps({"unit":item["unit"],"protected":diff["protected_targets"],"status":diff["status"]}),flush=True)
            if diff["status"]!="passed":break
    passed=len(results)==18 and all(r["status"]=="passed" for r in results)
    m.write_new(out/"summary.json",{"passed":passed,"unique_protected":len(protected),"comparisons":results})
    raise SystemExit(0 if passed else 2)
if __name__=="__main__":main()
