#!/usr/bin/env python3
"""Prepare commands and exact-candidate recheck queries; never execute J or z3.

Input is the supplied cases/index.json list, or a fully bound cases.json object,
under runs/j-dev-2026-10-27/cases/. The object form is:
{"cases":[{"id":...,"revision":...,"request":absolute_path,
 "cause":"model_not_reproduced"|... ,"local_refutation":false,
 "r1cs":absolute_O0_path,"sym":absolute_O0_path,"candidate":absolute_named_json,
 "site":"main.child","contract_inputs":{}}]}
R1CS/SYM/candidate/site are required only for local-refutation cases.
All paths must be copies in j-dev; no protected aq/cache path is opened.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import struct

ROOT=Path(__file__).resolve().parents[1]
DEV=ROOT/'runs/j-dev-2026-10-27'
RUN=ROOT/'runs/j-boost-2026-10-27'
OLD=ROOT/'runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development'
NEW=RUN/'cargo-target/debug/zkfdo-j-v23'

def permitted(path):
    # Reject an external path lexically before resolving or stat-ing it. This matters
    # because request JSONs retain references to the protected aq workspace.
    lexical=Path(os.path.abspath(path))
    try:relative=lexical.relative_to(DEV)
    except ValueError:raise ValueError('case input must be copied into j-dev: '+str(lexical)) from None
    cursor=DEV
    for part in relative.parts:
        cursor=cursor/part
        if cursor.is_symlink():raise ValueError('symlink in j-dev case input: '+str(cursor))
    return lexical.resolve(strict=True)

def validate_request_closure(request):
    data=json.loads(request.read_text());base=request.parent
    paths=[data['source_root'],data['component_wrapper'],data['entrypoint'],data['base_input'],data['candidate']['path'],*data.get('library_paths',[])]
    view=data.get('component_view')
    if view:
        spec=permitted(base/view['spec']);paths.append(view['spec'])
        detail=json.loads(spec.read_text())
        paths += [detail['target_source'],detail['original_fragment_spec']]
    for value in paths:permitted(base/value)

def read_r1cs(path):
    data=path.read_bytes();at=12; sections={}
    if data[:4]!=b'r1cs' or struct.unpack_from('<I',data,4)[0]!=1:raise ValueError('R1CS format')
    for _ in range(struct.unpack_from('<I',data,8)[0]):
        kind,length=struct.unpack_from('<IQ',data,at);at+=12;sections[kind]=data[at:at+length];at+=length
    h=sections[1];width=struct.unpack_from('<I',h)[0];prime=int.from_bytes(h[4:4+width],'little')
    wires,outputs,public,private,labels,count=struct.unpack_from('<IIIIQI',h,4+width)
    constraints=[];data=sections[2];at=0
    for _ in range(count):
        triple=[]
        for _ in range(3):
            n=struct.unpack_from('<I',data,at)[0];at+=4;terms=[]
            for _ in range(n):
                wire=struct.unpack_from('<I',data,at)[0];at+=4
                coef=int.from_bytes(data[at:at+width],'little');at+=width
                if wire>=wires or coef>=prime:raise ValueError('invalid R1CS term')
                terms.append((wire,coef))
            triple.append(terms)
        constraints.append(triple)
    if at!=len(data):raise ValueError('R1CS constraint length')
    return prime,wires,outputs,public,private,constraints

def recheck(case, output, seed, seconds):
    rpath=permitted(case['r1cs']);spath=permitted(case['sym']);cpath=permitted(case['candidate'])
    prime,wires,outputs,public,private,constraints=read_r1cs(rpath)
    symbols={line.split(',')[3]:int(line.split(',')[1]) for line in spath.read_text().splitlines() if line}
    candidate=json.loads(cpath.read_text());pins={};named=[]
    for name,text in candidate.items():
        if not name.startswith('main.'):raise ValueError('named candidate required')
        target=case['site']+name[4:];wire=symbols.get(target,-1);v=int(text)
        if not 0<=wire<wires or not 0<=v<prime:raise ValueError('candidate mapping missing/noncanonical')
        if wire in pins and pins[wire]!=v:raise ValueError('candidate aliases disagree')
        pins[wire]=v;named.append({'signal':target,'wire':wire,'value':str(v),'source':'exact_candidate'})
    for name,text in case.get('contract_inputs',{}).items():
        wire=symbols.get(name,-1);v=int(text)
        if not 1+outputs<=wire<1+outputs+public+private or not 0<=v<prime:raise ValueError('contract input invalid')
        if wire in pins and pins[wire]!=v:raise ValueError('contract conflicts with candidate')
        pins[wire]=v;named.append({'signal':name,'wire':wire,'value':str(v),'source':'explicit_contract'})
    def lc(terms):
        xs=[str(c) if w==0 else f'(* {c} w{w})' for w,c in terms]
        return '0' if not xs else xs[0] if len(xs)==1 else '(+ '+' '.join(xs)+')'
    lines=[f'(set-option :timeout {seconds*1000})',f'(set-option :smt.random_seed {seed})',f'(set-option :sat.random_seed {seed})']
    for w in range(1,wires):lines += [f'(declare-const w{w} Int)',f'(assert (and (<= 0 w{w}) (< w{w} {prime})))']
    for a,b,c in constraints:lines.append(f'(assert (= (mod (- (* {lc(a)} {lc(b)}) {lc(c)}) {prime}) 0))')
    for w,v in pins.items():
        if w==0:
            if v!=1:raise ValueError('wire zero')
        else:lines.append(f'(assert (= w{w} {v}))')
    lines += ['(check-sat)']
    query=output/'recheck.smt2';query.write_text('\n'.join(lines)+'\n')
    scope={'kind':'exact_candidate_recheck','pins':named,'other_main_inputs':'free','constraints':'all_original_O0','unsat_scope':'exact candidate under explicit contract only','sat_meaning':'recheck_not_refuted; not verified reachability','source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [rpath,spath,cpath]},'query_sha256':hashlib.sha256(query.read_bytes()).hexdigest()}
    (output/'recheck-scope.json').write_text(json.dumps(scope,indent=2)+'\n')
    return query

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cases',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=0);p.add_argument('--class-budget-seconds',type=int,default=20)
    args=p.parse_args();raw=json.loads(permitted(args.cases).read_text());out=Path(os.path.abspath(args.output))
    if isinstance(raw,list):
        cases=[]
        for item in raw:
            folder=permitted(args.cases.parent/item['case'])
            detail=json.loads(permitted(folder/'class.json').read_text())['class']
            group=item['group']
            cases.append({'id':item['case'],'revision':item['revision'],'request':str(permitted(folder/'request.json')),
                          'cause':'model_not_reproduced' if group=='model_not_reproduced' else detail['cause_before_budget'],
                          'local_refutation':group=='local_refutation',
                          **({'r1cs':str(folder/'o0.r1cs'),'sym':str(folder/'o0.sym'),
                              'candidate':str(folder/'candidate.json'),'site':item['representative']}
                             if group=='local_refutation' else {})})
    else:
        cases=raw['cases']
    if not out.is_relative_to(RUN) or out.exists():raise ValueError('fresh output under j-boost required')
    # Fail before creating any plan when the delivered request still points outside
    # its approved development copy or the local recheck inputs are absent.
    for c in cases:
        request=permitted(c['request']);validate_request_closure(request)
        if c.get('local_refutation'):
            for key in ('r1cs','sym','candidate'):permitted(c[key])
    tools={x:shutil.which(x) for x in ['circom','node','snarkjs','z3']}
    if not all(tools.values()):raise ValueError('required installed tool missing')
    out.mkdir(parents=True)
    z3=out/'z3-seeded';z3.write_text('#!/usr/bin/env python3\nimport os,sys\np='+repr(tools['z3'])+'\nos.execv(p,[p,"smt.random_seed='+str(args.seed)+'","sat.random_seed='+str(args.seed)+'",*sys.argv[1:]])\n');z3.chmod(0o755)
    estimates=json.loads((RUN/'aq-copy-estimates.json').read_text())['rows'];commands=[]
    for i,c in enumerate(sorted(cases,key=lambda c:(c['revision'],c['id']))):
        request=permitted(c['request']);estimate=estimates.get(c['revision'])
        if not estimate:raise ValueError('unmeasured revision: '+c['revision'])
        folder=out/f'case-{i:04d}';folder.mkdir();arms=[('current',OLD,[]),('fair',NEW,['--class-sweep-budget-seconds',str(args.class_budget_seconds)])]
        if c.get('cause') in ['model_not_reproduced','synthesis_model_not_reproduced']:
            arms.append(('direct',NEW,['--class-sweep-budget-seconds',str(args.class_budget_seconds),'--constraint-witness']))
        for name,engine,extra in arms:
            argv=[str(engine),'--request',str(request),'--output',str(folder/name),'--cache',str(folder/(name+'-cache')),'--instance-store',str(folder/(name+'-store'))]
            for tool in ['circom','node','snarkjs']:argv += ['--'+tool+'-bin',tools[tool]]
            argv += ['--z3-bin',str(z3),*extra]
            commands.append({'case':c['id'],'arm':name,'seed':args.seed,'expected_seconds':estimate['expected_seconds_per_new_request'],'external_wall_cap_seconds':estimate['cap_seconds_per_new_request'],'argv':argv,'shell':shlex.join(argv),'request_sha256':hashlib.sha256(request.read_bytes()).hexdigest(),'engine_sha256':hashlib.sha256(engine.read_bytes()).hexdigest()})
        if c.get('local_refutation'):
            query=recheck(c,folder,args.seed,estimate['expected_seconds_per_new_request'])
            argv=[str(z3),'-smt2',str(query)];commands.append({'case':c['id'],'arm':'local_refutation_recheck','argv':argv,'shell':shlex.join(argv),'external_wall_cap_seconds':estimate['cap_seconds_per_new_request']})
    (out/'commands.json').write_text(json.dumps({'execution':'not run; requires aq stopped and per-arm wall/disk monitoring','commands':commands},indent=2)+'\n')
    print(json.dumps({'prepared':len(commands),'executed':0,'output':str(out)}))
if __name__=='__main__':main()
