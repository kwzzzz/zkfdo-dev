#!/usr/bin/env python3
"""Read only the delivered j-dev JSON copies; map each case to current J code."""
import collections
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEV=ROOT/'runs/j-dev-2026-10-27'
RUN=ROOT/'runs/j-boost-2026-10-27'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    classes_path=DEV/'classes-v1.json';index_path=DEV/'cases/index.json'
    catalog=json.loads(classes_path.read_text());rows=catalog['classes']
    index=json.loads(index_path.read_text());mapped=[]
    point={
        'model_not_reproduced':['src/candidate_review/lifting/mod.rs:3157','src/candidate_review/lifting/mod.rs:3180','src/candidate_review/lifting/mod.rs:3230','src/candidate_review/lifting/mod.rs:3353','src/candidate_review/lifting/mod.rs:3395','src/candidate_review/lifting/mod.rs:3397','src/candidate_review/lifting/repair.rs:1720'],
        'unknown_cause_None':['src/candidate_review/lifting/mod.rs:3301','src/candidate_review/lifting/mod.rs:3354','src/candidate_review/lifting/mod.rs:3397'],
        'unknown_cause_synthesis_timeout':['src/candidate_review/lifting/mod.rs:3301','src/candidate_review/lifting/mod.rs:3354','src/candidate_review/lifting/mod.rs:3395'],
        'unknown_cause_cone_refuted_by_propagation_only':['src/candidate_review/lifting/mod.rs:3300','src/candidate_review/lifting/mod.rs:3356','src/candidate_review/lifting/mod.rs:3395'],
        'local_refutation':['src/candidate_review/lifting/mod.rs:3607','src/candidate_review/lifting/mod.rs:3618','src/candidate_review/lifting/mod.rs:3658','src/candidate_review/lifting/mod.rs:3663'],
    }
    groups=collections.Counter();causes=collections.Counter();b=collections.Counter();reason=collections.Counter();revision=collections.Counter();positive=collections.Counter();needs=collections.Counter()
    for r in rows:
        cause=str(r['cause_before_budget']);outcome=str(r['b_outcome']);key=(r['verdict'],r['final_reason']);
        causes[cause]+=1;b[outcome]+=1;reason[key]+=1;revision[r['revision']]+=1
        if (r['exclusion_search_seconds_site_steps'] or 0)>0:positive[key]+=1
    for entry in index:
        name=entry['case'];folder=DEV/'cases'/name
        if Path(name).name!=name or name in ('.','..') or folder.is_symlink() or not folder.is_dir():raise ValueError('case folder missing')
        obj=json.loads((folder/'class.json').read_text());c=obj['class'];req=json.loads((folder/'request.json').read_text());group=entry['group'];groups[group]+=1
        if group not in point:raise ValueError('unmapped group '+group)
        refs={'source_root':req['source_root'],'component_wrapper':req['component_wrapper'],'entrypoint':req['entrypoint'],'base_input':req['base_input'],'candidate':req['candidate']['path']}
        unavailable=[k for k,v in refs.items() if not Path(v).is_relative_to(DEV)]
        for k in unavailable:needs[k]+=1
        mapped.append({'case':name,'revision':entry['revision'],'representative':entry['representative'],
                       'group':group,'verdict':c['verdict'],'reason':c['final_reason'],'cause_before_budget':c['cause_before_budget'],'b_outcome':c['b_outcome'],
                       'current_J_code_points':point[group], 'request_copy':str(folder/'request.json'),
                       'references_outside_j_dev':unavailable,'local_case_copies_present':{key:(not (folder/filename).is_symlink() and (folder/filename).is_file()) for key,filename in [('candidate','candidate.json'),('base_input','base_input.json'),('component_wrapper','component_wrapper.circom'),('entrypoint','entrypoint.circom'),('o0_r1cs','o0.r1cs'),('o0_sym','o0.sym')]},'referenced_paths_not_opened':{k:refs[k] for k in unavailable}})
    output={'schema':'j-boost-a-audit-v4','source':{'classes':str(classes_path),'classes_sha256':sha(classes_path),'index':str(index_path),'index_sha256':sha(index_path),'built_at':catalog['built_at'],'scope':catalog['scope']},
            'class_count':len(rows),'class_revisions':dict(revision),'class_verdict_reason':{f'{k[0]}:{k[1]}':v for k,v in reason.items()},
            'cause_before_budget':dict(causes),'b_outcome':dict(b),'positive_exclusion_search_site_step_counts':{f'{k[0]}:{k[1]}':v for k,v in positive.items()},
            'cases_count':len(mapped),'case_groups':dict(groups),'outside_reference_counts':dict(needs),'cases':mapped}
    with (RUN/'a-materials-audit-v4.json').open('x') as f:f.write(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:output[k] for k in ['class_count','class_verdict_reason','cause_before_budget','b_outcome','cases_count','case_groups','outside_reference_counts']},ensure_ascii=False))
if __name__=='__main__':main()
