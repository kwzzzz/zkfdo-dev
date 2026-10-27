#!/usr/bin/env python3
"""Re-render the complete recorded untagged cohort; no compiler or execution."""
import hashlib,json,sys
from pathlib import Path
import s_round4b_monitor_20261027 as m
import s_tag_wrapper_prototype_20261027 as p

def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
    source=m.ROOT/"runs/s-tag-wrapper-2026-10-27/prototype-v2/inventory.json"
    raw=source.read_bytes();data=json.loads(raw)
    pins={r["path"]:r["sha256"] for r in data["input_files"]};cache={};results=[]
    for row in data["targets"]:
        if not row["inspection_eligible"] or row["tag_inventory_status"]!="classified" or row.get("tag_declarations"):continue
        wrapper=Path(row["original_wrapper_path"]).read_bytes()
        if sha(wrapper)!=row["original_wrapper_sha256"]:raise ValueError("original wrapper changed")
        path,template,args=p.original_call(wrapper.decode());key=str(path)
        if key not in cache:
            raw=path.read_bytes()
            if sha(raw)!=pins[key]:raise ValueError("defining source changed")
            cache[key]=raw.decode()
        rendered,tags,_=p.render_prototype(path,cache[key],template,args,{path:cache[key]})
        ok=not tags and rendered is not None and rendered.encode()==wrapper
        results.append({"unit":row["unit"],"label":row["label"],"passed":ok,"sha256":sha(wrapper)})
        if not ok:break
    passed=len(results)==1870 and all(r["passed"] for r in results)
    m.write_new(sys.argv[1],{"passed":passed,"checked":len(results),"source":str(source),"source_sha256":sha(source.read_bytes()),"rows":results})
    print(json.dumps({"checked":len(results),"passed":passed}));raise SystemExit(0 if passed else 2)
if __name__=="__main__":main()
