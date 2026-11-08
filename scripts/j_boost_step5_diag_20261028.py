#!/usr/bin/env python3
"""Step-5 diagnostic only. Writes exclusively this run's step5 tree and report.
No imports of previous runners, no image access, no Rust build, no background jobs.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runs/j-boost-2026-10-27/step5'
PLAN = ROOT / 'runs/j-boost-2026-10-27/step4/plan-v6_1.json'
KEY = 'aq-026-2bcd7ed6110f-q002200'
LEDGER = ROOT / f'runs/j-boost-2026-10-27/step4/execution/plan-v6_1/{KEY}/direct/attempt-0001/j-boost.json'
IDS = ('071', '073', '079', '080')
TOOLS = {'circom': str(Path.home()/'.cargo/bin/circom'), 'node': '/opt/homebrew/bin/node', 'snarkjs': '/opt/homebrew/bin/snarkjs', 'z3': '/opt/homebrew/bin/z3'}
P = 21888242871839275222246405745257275088548364400416034343698204186575808495617
STOP = False


def stamp(): return datetime.now(timezone.utc).isoformat()
def load(p): return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()
def write(p, data):
    p=Path(p)
    if not p.absolute().is_relative_to(OUT): raise ValueError('write outside step5')
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def textfile(p, s):
    p=Path(p)
    if not p.absolute().is_relative_to(OUT): raise ValueError('write outside step5')
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(s)
def tick():
    b=load(OUT/'budget.json')
    if STOP or time.time() >= b['deadline_epoch']: raise TimeoutError('total wall cap or interruption')
    d=os.statvfs(OUT)
    if d.f_bavail*d.f_frsize < 18*2**30: raise RuntimeError('internal_free_below_18GiB')
    return b

def run(argv, folder, cap=600, solver=False):
    """One synchronous child group; wall bound includes parsing and model printing."""
    b=tick(); cap=min(float(cap),b['deadline_epoch']-time.time())
    if solver: cap=min(cap,b['solver_cap_seconds']-b['solver_seconds'])
    if cap<=0: raise TimeoutError('solver or wall budget exhausted')
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    if (folder/'receipt.json').exists(): raise RuntimeError('refuse overwrite process record')
    env=dict(os.environ); env.update(TMPDIR=str(OUT/'tmp'),PYTHONDONTWRITEBYTECODE='1')
    (OUT/'tmp').mkdir(exist_ok=True)
    start=time.monotonic(); pid=None; status='completed'; peak=0
    with (folder/'stdout.log').open('wb') as out,(folder/'stderr.log').open('wb') as err:
        proc=subprocess.Popen(argv,cwd=OUT,stdout=out,stderr=err,env=env,start_new_session=True)
        pid=proc.pid; nextbeat=start
        try:
            while proc.poll() is None:
                elapsed=time.monotonic()-start
                if elapsed>=cap or STOP or time.time()>=b['deadline_epoch']:
                    status='timeout' if not STOP else 'interrupted'
                    os.killpg(pid,signal.SIGTERM)
                    try: proc.wait(timeout=2)
                    except subprocess.TimeoutExpired: os.killpg(pid,signal.SIGKILL); proc.wait()
                    break
                if time.monotonic()>=nextbeat:
                    write(OUT/'heartbeat.json',{'time':stamp(),'pid':os.getpid(),'child':pid,'stage':str(folder.relative_to(OUT)),'elapsed_seconds':elapsed,'solver_seconds_before':b['solver_seconds']})
                    tick(); print(json.dumps({'stage':str(folder.relative_to(OUT)),'elapsed':round(elapsed,1)},ensure_ascii=False),flush=True)
                    nextbeat=time.monotonic()+30
                time.sleep(.2)
        except BaseException:
            if proc.poll() is None:
                os.killpg(pid,signal.SIGKILL);proc.wait()
            raise
    elapsed=time.monotonic()-start
    if solver:
        b=load(OUT/'budget.json'); b['solver_seconds']+=elapsed; write(OUT/'budget.json',b)
    receipt={'argv':list(map(str,argv)),'started_at_epoch':time.time()-elapsed,'finished_at':stamp(),'seconds':elapsed,'cap_seconds':cap,'status':status,'returncode':proc.returncode,'nice':os.getpriority(os.PRIO_PROCESS,0),'solver':solver}
    write(folder/'receipt.json',receipt)
    return receipt


def sections(path,magic):
    data=Path(path).read_bytes(); assert data[:4]==magic
    version,n=struct.unpack_from('<II',data,4); pos=12; sec={}
    for _ in range(n):
        kind,length=struct.unpack_from('<IQ',data,pos);pos+=12
        assert kind not in sec and pos+length<=len(data)
        sec[kind]=data[pos:pos+length];pos+=length
    assert pos==len(data)
    return version,sec

class R1CS:
    def __init__(self,path):
        self.path=Path(path); version,s=sections(path,b'r1cs'); assert version==1
        h=s[1]; self.width=struct.unpack_from('<I',h)[0]; self.p=int.from_bytes(h[4:4+self.width],'little')
        self.n,self.outputs,self.public,self.private,self.labels,self.count=struct.unpack_from('<IIIIQI',h,4+self.width)
        assert self.p==P and len(h)==self.width+32
        data=s[2];pos=0;self.constraints=[]
        for i in range(self.count):
            cs=[]
            for _ in range(3):
                n=struct.unpack_from('<I',data,pos)[0];pos+=4;ts=[]
                for _ in range(n):
                    w=struct.unpack_from('<I',data,pos)[0];pos+=4
                    c=int.from_bytes(data[pos:pos+self.width],'little');pos+=self.width
                    assert w<self.n and 0<=c<self.p;ts.append((w,c))
                cs.append(ts)
            self.constraints.append(cs)
            if i%10000==0: tick()
        assert pos==len(data)
    def check(self,values,sym):
        start=time.monotonic()
        if len(values)!=self.n or values[0]!=1 or any(not 0<=v<self.p for v in values): return {'ok':False,'reason':'shape_or_noncanonical','seconds':time.monotonic()-start}
        first=None;failed=0
        for i,cs in enumerate(self.constraints):
            abc=[sum(c*values[w] for w,c in ts)%self.p for ts in cs]
            residual=(abc[0]*abc[1]-abc[2])%self.p
            if residual:
                failed+=1
                if first is None: first=self.decode(i,sym,values)|{'evaluated_abc':list(map(str,abc)),'residual':str(residual)}
            if i%10000==0: tick()
        return {'ok':failed==0,'constraints_checked':self.count,'failed_count':failed,'first_failure':first,'seconds':time.monotonic()-start}
    def decode(self,i,sym,values=None):
        inv=defaultdict(list)
        for n,w in sym.items():
            if w>=0:inv[w].append(n)
        return {'index':i,'index_base':0,'equation':'A * B - C = 0 (mod p)','terms':{letter:[{'wire':w,'coefficient':str(c),'signed_coefficient':str(c if c<=self.p//2 else c-self.p),'names':inv[w] if w else ['1'],'value':str(values[w]) if values is not None else None} for w,c in ts] for letter,ts in zip('ABC',self.constraints[i])}}

def symread(path):
    result={}
    for line in Path(path).read_text().splitlines():
        a,w,t,n=line.split(',',3); w=int(w)
        assert n not in result or result[n]==w;result[n]=w
    return result

def wread(path):
    v,s=sections(path,b'wtns'); assert v==2
    width=struct.unpack_from('<I',s[1])[0];p=int.from_bytes(s[1][4:4+width],'little');n=struct.unpack_from('<I',s[1],4+width)[0]
    assert p==P and len(s[2])==n*width
    return [int.from_bytes(s[2][i*width:(i+1)*width],'little') for i in range(n)]

def wwrite(path,values):
    path=Path(path);assert path.absolute().is_relative_to(OUT)
    head=struct.pack('<I',32)+P.to_bytes(32,'little')+struct.pack('<I',len(values))
    body=b''.join(v.to_bytes(32,'little') for v in values)
    path.write_bytes(b'wtns'+struct.pack('<II',2,2)+struct.pack('<IQ',1,len(head))+head+struct.pack('<IQ',2,len(body))+body)

def map_values(values,sa,sb,n):
    buckets=defaultdict(set)
    for name,w in sb.items():
        if w<0:continue
        if name not in sa or sa[name]<0: raise ValueError('mapping_missing:'+name)
        buckets[w].add(values[sa[name]])
    mapped=[1]
    for w in range(1,n):
        if len(buckets[w])!=1: raise ValueError('mapping_absent_or_alias_conflict:'+str(w))
        mapped.append(next(iter(buckets[w])))
    return mapped

def flatten(obj,prefix=''):
    out={}
    if isinstance(obj,dict):
        for k,v in obj.items():out.update(flatten(v,prefix+'.'+k if prefix else k))
    elif isinstance(obj,list):
        for i,v in enumerate(obj):out.update(flatten(v,f'{prefix}[{i}]'))
    else:out[prefix]=int(obj)
    return out

def fill_shape(obj,flat,prefix=''):
    if isinstance(obj,dict): return {k:fill_shape(v,flat,prefix+'.'+k if prefix else k) for k,v in obj.items()}
    if isinstance(obj,list): return [fill_shape(v,flat,f'{prefix}[{i}]') for i,v in enumerate(obj)]
    return str(flat[prefix])

def request(): return next(r for r in load(PLAN)['requests'] if r['key']==KEY)
def representative(case): return next(c['representative'] for c in request()['cases'] if c['id'].startswith(case+'-'))
def art(opt):return OUT/f'original-{opt}'
def circuit(opt):return art(opt)/'queryIdentity.r1cs'
def symbols(opt):return art(opt)/'queryIdentity.sym'
def models():return R1CS(circuit('O0')),symread(symbols('O0')),R1CS(circuit('O1')),symread(symbols('O1'))
def H(d,m,y):return sum(k*(256*(z//10)+(z%10)+12336) for k,z in zip((1,2**16,2**32),(d,m,y)))%P

def compile_circuit(entry,project,target,opt='O0',sanity=2):
    target.mkdir(parents=True,exist_ok=True)
    cmd=[TOOLS['circom'],str(entry),'--'+opt,'--r1cs','--sym','--wasm','--sanity_check',str(sanity),'-o',str(target),'-l',str(project/'node_modules'),'-l',str(project),'-l',str(project/'circuits/identityManagement')]
    result=run(cmd,target/'compile',600)
    if result['returncode']!=0:raise RuntimeError('compile failed: '+str(target))
    return result

def gen(opt,input_path,target,check=True):
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    if isinstance(opt,str):folder=art(opt);stem='queryIdentity'
    else:folder,stem=opt
    driver=folder/f'{stem}_js/generate_witness.js'
    if not check:
        driver=OUT/'unchecked-witness.cjs'
        if not driver.exists():
            textfile(driver, "const fs=require('fs');(async()=>{const wc=await require(process.argv[2])(fs.readFileSync(process.argv[3]));wc.sanityCheck=false;const data=await wc.calculateWTNSBin(JSON.parse(fs.readFileSync(process.argv[4],'utf8')),false);fs.writeFileSync(process.argv[5],data);})().catch(e=>{console.error(e);process.exit(1)});\n")
        argv=[TOOLS['node'],str(driver),str(folder/f'{stem}_js/witness_calculator.js'),str(folder/f'{stem}_js/{stem}.wasm'),str(input_path),str(target/'witness.wtns')]
    else: argv=[TOOLS['node'],str(driver),str(folder/f'{stem}_js/{stem}.wasm'),str(input_path),str(target/'witness.wtns')]
    return run(argv,target/'generate',120)

def snark(opt,witness,target):
    r=run([TOOLS['snarkjs'],'wtns','check',str(circuit(opt)),str(witness)],target,120)
    log=(target/'stdout.log').read_text(errors='replace')+(target/'stderr.log').read_text(errors='replace')
    return {'ok':r['returncode']==0 and 'WITNESS IS CORRECT' in log,'seconds':r['seconds'],'receipt':str(target/'receipt.json')}

def aligned(errorlog,different=None):
    if different is not None:return {'reason':'output_differs' if different else 'outputs_equal','violation':different}
    genuine=all(x in errorlog for x in ('Error: Assert Failed.','Error in template','line:'))
    infra=any(x in errorlog for x in ('ENOENT','MODULE_NOT_FOUND','SyntaxError','out of memory','Not all inputs have been set','Signal not found','Too many values','Not enough values'))
    return {'reason':'honest_aborted' if genuine and not infra else 'unknown','violation':True if genuine and not infra else None,'detail':errorlog[-2500:]}

def verify(values,folder,site,kind,pins=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    r0,s0,r1,s1=models(); result={}
    path0=folder/'candidate-o0.wtns';wwrite(path0,values)
    result['o0']=r0.check(values,s0)
    try:
        v1=map_values(values,s0,s1,r1.n);path1=folder/'candidate-o1.wtns';wwrite(path1,v1)
        result['o1']=r1.check(v1,s1)
    except ValueError as e:
        v1=None;result['o1']={'ok':False,'reason':str(e)}
    # Keep independent checker evidence even for a rejected probe.
    result['snarkjs_o0']=snark('O0',path0,folder/'snarkjs-o0')
    if v1 is not None:result['snarkjs_o1']=snark('O1',path1,folder/'snarkjs-o1')
    base=load(OUT/'base_input.json');contract=flatten(base)
    actual={k:values[s0['main.'+k]] for k in contract}
    mismatches=[{'name':k,'expected':str(contract[k]),'actual':str(v)} for k,v in actual.items() if v!=contract[k]]
    result['contract']={'matches':not mismatches,'mismatches':mismatches}
    d,m,y=[values[s0[site+'.'+z]] for z in ('day','month','year')];e=values[s0[site+'.encoded']]
    result['violation']={'actual_date':list(map(str,(d,m,y))),'encoded':str(e),'honest_encoded':str(H(d,m,y)),'V':e!=H(d,m,y),'date_in_range':1<=d<=31 and 1<=m<=12 and 0<=y<=99,'hints_digit_ranges':all(0<=values[s0[site+'.'+z+suffix]]<10 for z in ('day','month','year') for suffix in ('Decimals','Rest'))}
    result['exact_pins_match']=all(values[int(w)]==int(v) for w,v in (pins or {}).items())
    valid=result['o0']['ok'] and result['o1']['ok'] and result['snarkjs_o0']['ok'] and result.get('snarkjs_o1',{}).get('ok',False)
    if valid:
        inp=folder/'main-input.json';write(inp,fill_shape(base,actual))
        rr=gen('O0',inp,folder/'honest')
        log=(folder/'honest/generate/stderr.log').read_text(errors='replace')+(folder/'honest/generate/stdout.log').read_text(errors='replace')
        if rr['status']=='completed' and rr['returncode']==0:
            honest=wread(folder/'honest/witness.wtns');hc=r0.check(honest,s0);result['honest_check']=hc
            sameinput=all(honest[s0['main.'+k]]==v for k,v in actual.items())
            result['aligned']=aligned('',honest[1:1+r0.outputs]!=values[1:1+r0.outputs]) if hc['ok'] and sameinput else {'reason':'unknown','violation':None,'detail':'honest_invalid_or_input_mismatch'}
        else:result['aligned']=aligned(log) if rr['status']=='completed' else {'reason':'unknown','violation':None,'detail':rr['status']}
    else:result['aligned']={'reason':'unknown','violation':None,'detail':'original_witness_invalid_or_checker_unresolved'}
    target=(result['exact_pins_match'] if kind=='Q1' else result['violation']['V'])
    if kind in ('Q3','probe'):target=target and not mismatches
    result['verified_sat']=bool(valid and target and result['aligned']['reason']!='unknown')
    result['l1']=bool(result['verified_sat'] and result['aligned']['violation'])
    result['witness_sha256']=sha(path0)
    write(folder/'verification.json',result);return result


def prepare():
    row=request(); project=Path(row['project']); target=OUT/'source'
    rec={'started':stamp(),'source':[],'protected':{},'tools':{},'representatives':{c:representative(c) for c in IDS}}
    for key in ['docs/j_boost_step4_2026-10-27.md','runs/j-boost-2026-10-27/debate/d3_step5_critique.md','runs/j-boost-2026-10-27/debate/d1_singular_sets.md',str(LEDGER.relative_to(ROOT)),str(PLAN.relative_to(ROOT))]:rec['protected'][key]=sha(ROOT/key)
    for name,expected in row['source_sha256'].items():
        src=Path(name)
        if not src.is_relative_to(project):continue
        assert sha(src)==expected,('source hash changed',name)
        dest=target/src.relative_to(project);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(src.read_bytes())
        rec['source'].append({'original':str(src),'copy':str(dest),'sha256':expected})
    for key,dest in [('base_input_copy','base_input.json'),('candidate_copy','candidate.json')]:
        src=Path(row[key]);assert sha(src)==row['input_sha256'][str(src)]
        (OUT/dest).write_bytes(src.read_bytes())
    for tool,cmd in TOOLS.items():
        rr=run([cmd,'--help' if tool=='snarkjs' else '-version' if tool=='z3' else '--version'],OUT/'tools'/tool,30)
        log=(OUT/'tools'/tool/'stdout.log').read_text(errors='replace')+(OUT/'tools'/tool/'stderr.log').read_text(errors='replace')
        rec['tools'][tool]={'path':cmd,'sha256':sha(cmd),'version_lines':log.splitlines()[:3]}
    rec['step4_tool_sha256']=load(PLAN)['tool_sha256'];write(OUT/'preparation.json',rec)
    entry=target/Path(row['entrypoint']).relative_to(project)
    for opt in ('O0','O1'):
        compile_circuit(entry,target,art(opt),opt)
        expected=row['expected_entrypoint']['o0_r1cs_sha256' if opt=='O0' else 'r1cs_sha256']
        assert sha(circuit(opt))==expected,('original R1CS mismatch',opt)
    r0,s0,r1,s1=models()
    stats={'O0':{'constraints':r0.count,'wires':r0.n,'public_outputs':r0.outputs,'r1cs_sha256':sha(circuit('O0')),'sym_sha256':sha(symbols('O0'))},'O1':{'constraints':r1.count,'wires':r1.n,'public_outputs':r1.outputs,'r1cs_sha256':sha(circuit('O1')),'sym_sha256':sha(symbols('O1'))}}
    write(OUT/'circuit-stats.json',stats)
    gen('O0',OUT/'base_input.json',OUT/'base-O0');gen('O1',OUT/'base_input.json',OUT/'base-O1')
    values=wread(OUT/'base-O0/witness.wtns');v1=wread(OUT/'base-O1/witness.wtns')
    checks={'O0':r0.check(values,s0),'O1':r1.check(v1,s1),'snarkjs_O0':snark('O0',OUT/'base-O0/witness.wtns',OUT/'base-check-O0'),'snarkjs_O1':snark('O1',OUT/'base-O1/witness.wtns',OUT/'base-check-O1'),'model_mapping_equal':map_values(values,s0,s1,r1.n)==v1,'dates':{c:{z:str(values[s0[representative(c)+'.'+z]]) for z in ('day','month','year','encoded')} for c in IDS}}
    write(OUT/'base-checks.json',checks)
    assert checks['O0']['ok'] and checks['O1']['ok'] and checks['model_mapping_equal']
    flat=flatten(load(OUT/'base_input.json')); first=1+r0.outputs
    assert set(s0['main.'+n] for n in flat)==set(range(first,first+r0.public+r0.private))
    write(OUT/'contract.json',{'definition':'all main inputs equal the step-4 base input; not an application-validity specification','base_input_sha256':sha(OUT/'base_input.json'),'count':len(flat),'pins':[{'name':'main.'+n,'wire':s0['main.'+n],'value':str(v)} for n,v in sorted(flat.items())]})
    rows=load(LEDGER)['records']; attempts=[x for x in rows if x.get('method')=='constraint_witness']
    audit={'source_ledger_sha256':sha(LEDGER),'attempts':len(attempts),'origins':dict(Counter(x.get('origin') for x in attempts)),'distinct_models':'not_recoverable','per_wire_provenance':'not_recoverable','past_residual_values':'not_recoverable','query_membership':'not_recoverable','reason':'failed query/start/model vectors were not preserved; no access to former image workspaces','representatives':{}}
    for c in IDS:
        aa=[x for x in attempts if x['site']==representative(c)]; selected={}
        for x in aa:
            origin=x['origin']
            if origin not in selected:
                i=x['failure_diagnostic']['constraint']['first_failed_constraint_index'];selected[origin]={'step4_record':x,'recompiled_constraint':r0.decode(i,s0)}
        audit['representatives'][c]={'attempts':len(aa),'origin_counts':dict(Counter(x['origin'] for x in aa)),'first_per_origin':selected}
    write(OUT/'step0-audit.json',audit)
    semantics()
    print(json.dumps({'prepared':True,'stats':stats,'dates':checks['dates']},ensure_ascii=False),flush=True)


def semantics():
    src=OUT/'semantics/source';src.mkdir(parents=True,exist_ok=True)
    code='pragma circom 2.1.6;\ntemplate Semantics(){signal input z[5];signal output q[5];signal output r[5];for(var i=0;i<5;i++){q[i] <-- z[i] \\ 10;r[i] <-- z[i] % 10;q[i]*10+r[i] === z[i];}}\ncomponent main = Semantics();\n'
    entry=src/'semantics.circom';textfile(entry,code);folder=OUT/'semantics/build';compile_circuit(entry,OUT/'source',folder)
    inp=OUT/'semantics/input.json';numbers=[9,10,19,20,P-1];write(inp,{'z':list(map(str,numbers))})
    gen((folder,'semantics'),inp,OUT/'semantics/run');vs=wread(OUT/'semantics/run/witness.wtns');ss=symread(folder/'semantics.sym')
    rows=[{'z':str(z),'actual_q':str(vs[ss[f'main.q[{i}]']]),'actual_r':str(vs[ss[f'main.r[{i}]']]),'expected_q':str(z//10),'expected_r':str(z%10),'matches':(vs[ss[f'main.q[{i}]']],vs[ss[f'main.r[{i}]']])==divmod(z,10)} for i,z in enumerate(numbers)]
    write(OUT/'semantics/results.json',{'rows':rows,'all_match':all(x['matches'] for x in rows),'circom_sha256':sha(TOOLS['circom']),'wasm_sha256':sha(folder/'semantics_js/semantics.wasm'),'generator_sha256':sha(folder/'semantics_js/witness_calculator.js')})
    assert all(x['matches'] for x in rows)


def template_span(text,name):
    match=re.search(r'\btemplate\s+'+re.escape(name)+r'\s*\([^)]*\)\s*\{',text);assert match,name
    start=match.start();pos=match.end();depth=1
    while depth:
        if text[pos]=='{':depth+=1
        elif text[pos]=='}':depth-=1
        pos+=1
    return start,pos

def probe(case):
    site=representative(case);folder=OUT/'probes'/case;folder.mkdir(parents=True,exist_ok=True)
    r0,s0,r1,s1=models();base=wread(OUT/'base-O0/witness.wtns')
    d,m,y=[base[s0[site+'.'+n]] for n in ('day','month','year')]; X=base[s0[site+'.encoded']]
    alt=[2 if d==1 else 1,m if 1<=m<=12 else 1,y if 0<=y<=99 else 0]
    e0=sum(k*(z+12336) for k,z in zip((1,2**16,2**32),alt))%P
    qm,qy=alt[1]//10,alt[2]//10;qd=((X-e0)*pow(246,-1,P)-2**16*qm-2**32*qy)%P
    hints={}
    for zname,z,q in zip(('day','month','year'),alt,(qd,qm,qy)):
        hints[zname+'Decimals']=q;hints[zname+'Rest']=(z-10*q)%P
    write(folder/'probe-plan.json',{'label':'existence probe, template-specific, not a method','site':site,'base_date':list(map(str,(d,m,y))),'alternative_date':list(map(str,alt)),'alternative_date_in_range':True,'dateEncoded':str(X),'target_hints':{k:str(v) for k,v in hints.items()},'scope':'ONLY six target DateEncoder hints; DateDecoder hints stay honest','limitation':'alternative date is used to construct q/r, but cannot be installed into DateEncoder input wires by modifying its hints alone; parent DateDecoder hints are outside authorized injection scope'})
    source=folder/'source';manifest=load(OUT/'preparation.json')['source'];texts={}
    for item in manifest:
        rel=Path(item['copy']).relative_to(OUT/'source');texts[rel]=Path(item['copy']).read_text()
    names={}
    for rel,text in texts.items():
        for name in re.findall(r'\btemplate\s+(\w+)\s*\(',text):names[name]=rel
    def clone(name,path):
        rel=names[name];original=texts[rel];a,b=template_span(original,name);body=original[a:b];newname=name+'_Step5_'+case+'_'+str(len(path))
        body=re.sub(r'\btemplate\s+'+re.escape(name)+r'\b','template '+newname,body,count=1)
        if path:
            comp=path[0];pattern=r'(\bcomponent\s+'+re.escape(comp)+r'\s*=\s*)(\w+)(\s*\()';match=re.search(pattern,body);assert match,(name,comp)
            sub=clone(match.group(2),path[1:]);body=body[:match.start(2)]+sub+body[match.end(2):]
        else:
            assert name=='DateEncoder'
            for sig,val in hints.items():
                body,n=re.subn(r'(\bsignal\s+'+re.escape(sig)+r'\s*<--\s*)[^;]+;',lambda m:m.group(1)+str(val)+';',body);assert n==1
        texts[rel]+='\n'+body+'\n';return newname
    newroot=clone('QueryIdentity',site.split('.')[1:]);entryrel=Path(request()['entrypoint']).relative_to(request()['project'])
    texts[entryrel]=texts[entryrel].replace('= QueryIdentity(80);','= '+newroot+'(80);')
    for rel,text in texts.items():textfile(source/rel,text)
    build=folder/'build'
    if not (build/'compile/receipt.json').exists():compile_circuit(source/entryrel,source,build,sanity=0)
    injected=R1CS(build/'queryIdentity.r1cs');ss=symread(build/'queryIdentity.sym')
    assert sha(build/'queryIdentity.r1cs')==sha(circuit('O0')),'probe changed constraints'
    if not (folder/'run-no-sanity/generate/receipt.json').exists():gen((build,'queryIdentity'),OUT/'base_input.json',folder/'run-no-sanity',check=False)
    generated=(folder/'run-no-sanity/witness.wtns').exists()
    if generated:
        values=map_values(wread(folder/'run-no-sanity/witness.wtns'),ss,s0,r0.n)
    else:
        # A separately labelled rejection diagnostic, never a successful forward probe.
        # Child inputs and its encoded boundary remain unchanged. Evaluate only the
        # child's arithmetic assignments; other values retain the honest base witness.
        values=list(base)
        for k,v in hints.items():values[s0[site+'.'+k]]=v
        for z in ('day','month','year'):
            values[s0[site+'.'+z+'Encoded']]=(256*hints[z+'Decimals']+hints[z+'Rest']+12336)%P
        values[s0[site+'.encoded']]=(values[s0[site+'.dayEncoded']]+2**16*values[s0[site+'.monthEncoded']]+2**32*values[s0[site+'.yearEncoded']])%P
        assert values[s0[site+'.encoded']]==X
        write(folder/'diagnostic-construction.json',{'kind':'algebraic rejection diagnostic; not a completed forward probe','generator_completed':False,'changed_wires':[w for w,(a,b) in enumerate(zip(base,values)) if a!=b],'downstream_execution':'generator stopped at child constraint; no claim of completed downstream recomputation','untouched_parent_date':list(map(str,(d,m,y)))})
    assert all(values[s0[site+'.'+k]]==v for k,v in hints.items()),'injection not applied'
    result=verify(values,folder/'verify',site,'probe')
    result.update(label='existence probe, template-specific, not a method',case=case,probe_scope_conflict=True,generator_completed=generated,probe_status='completed' if generated else 'blocked_scope_and_constraint_assert')
    write(folder/'result.json',result);print(json.dumps({'probe':case,'verified_sat':result['verified_sat'],'first_failure':result['o0'].get('first_failure',{}).get('index')},ensure_ascii=False),flush=True)


def smt_num(n):return str(n) if n>=0 else f'(- {-n})'
def lc_expr(ts):
    terms=[]
    for w,c in ts:
        c=c if c<=P//2 else c-P
        term='1' if w==0 else 'w'+str(w)
        terms.append(smt_num(c) if w==0 else term if c==1 else f'(- {term})' if c==-1 else f'(* {smt_num(c)} {term})')
    return '0' if not terms else terms[0] if len(terms)==1 else '(+ '+' '.join(terms)+')'


def constraint_expr(cs):
    # Exact rewrites over canonical representatives of this prime field.
    maps=[]
    for terms in cs:
        out=defaultdict(int)
        for w,c in terms:out[w]=(out[w]+c)%P
        maps.append({w:c for w,c in out.items() if c})
    a,b,c=maps
    linear=None
    if not any(w for w in a):
        linear=defaultdict(int,{w:(a.get(0,0)*v)%P for w,v in b.items()})
    elif not any(w for w in b):
        linear=defaultdict(int,{w:(b.get(0,0)*v)%P for w,v in a.items()})
    if linear is not None:
        for w,v in c.items():linear[w]=(linear[w]-v)%P
        const=linear.pop(0,0); terms=[(w,v) for w,v in linear.items() if v]
        if not terms:return ('true' if const==0 else 'false'),'constant'
        if len(terms)==1:
            w,v=terms[0];return f'(= w{w} {(-const*pow(v,-1,P))%P})','linear_single'
        if len(terms)==2 and const==0 and (terms[0][1]+terms[1][1])%P==0:
            return f'(= w{terms[0][0]} w{terms[1][0]})','alias'
    variables=(set(a)|set(b)|set(c))-{0}
    if len(variables)==1:
        w=next(iter(variables));alpha=a.get(w,0)*b.get(w,0)%P
        beta=(a.get(w,0)*b.get(0,0)+b.get(w,0)*a.get(0,0)-c.get(w,0))%P
        gamma=(a.get(0,0)*b.get(0,0)-c.get(0,0))%P
        if alpha and (alpha+beta)%P==0 and gamma==0:
            return f'(or (= w{w} 0) (= w{w} 1))','boolean'
    aa,bb,cc=map(lc_expr,cs)
    return f'(= (mod (- (* {aa} {bb}) {cc}) {P}) 0)','field_equation'

def query(case,kind):
    assert kind in ('Q1','Q3','Q2');folder=OUT/'queries'/case/kind;folder.mkdir(parents=True,exist_ok=True)
    if (folder/'result.json').exists():return load(folder/'result.json')
    r0,s0,_,_=models();site=representative(case);pins={};named=[]
    if kind=='Q1':
        for name,value in load(OUT/'candidate.json')['7_assignment'].items():
            mapped=site+name[4:];w=s0[mapped];v=int(value);assert w>=0 and 0<=v<P
            assert w not in pins or pins[w]==v;pins[w]=v;named.append({'name':mapped,'wire':w,'value':str(v)})
    elif kind=='Q3':
        for item in load(OUT/'contract.json')['pins']:pins[item['wire']]=int(item['value']);named.append(item)
    scope={'kind':kind,'case':case,'site':site,'formula':{'Q1':'F and exact full S assignment; all other wires free','Q3':'F and V and C(all main inputs equal step4 base)','Q2':'F and V; no main-input contract'}[kind],'pins':named,'O0_constraints_used':r0.count,'O0_sha256':sha(circuit('O0')),'normal_helpers':'separate integer t/u; z=10*t+u, 0<=u<10; E differs from honest H modulo p','original_qr':'only original field constraints; no added digit bounds'}
    start=time.monotonic();path=folder/'query.smt2'
    with path.open('w') as f:
        f.write('(set-logic QF_NIA)\n(set-option :produce-models true)\n(set-option :timeout 590000)\n(set-option :smt.random_seed 0)\n(set-option :sat.random_seed 0)\n')
        for w in range(1,r0.n):f.write(f'(declare-const w{w} Int)\n(assert (and (<= 0 w{w}) (< w{w} {P})))\n')
        rewrites=Counter()
        for i,cs in enumerate(r0.constraints):
            expression,rewrite=constraint_expr(cs);rewrites[rewrite]+=1
            f.write(f'; O0 constraint {i}\n(assert {expression})\n')
            if i%10000==0:tick()
        for w,v in pins.items():f.write(f'(assert (= w{w} {v}))\n')
        if kind!='Q1':
            terms=[]
            for z,k in zip(('day','month','year'),(1,2**16,2**32)):
                w=s0[site+'.'+z]
                f.write(f'(declare-const honest_t_{z} Int)\n(declare-const honest_u_{z} Int)\n(assert (and (<= 0 honest_t_{z}) (<= 0 honest_u_{z}) (< honest_u_{z} 10) (= w{w} (+ (* 10 honest_t_{z}) honest_u_{z}))))\n')
                terms.append(f'(* {k} (+ (* 256 honest_t_{z}) honest_u_{z} 12336))')
            f.write(f'(assert (not (= w{s0[site+".encoded"]} (mod (+ '+ ' '.join(terms)+f') {P}))))\n')
        f.write('(check-sat)\n(get-info :reason-unknown)\n(get-value ('+' '.join('w'+str(w) for w in range(1,r0.n))+'))\n')
    scope['exact_rewrites']=dict(rewrites)
    scope['query_sha256']=sha(path);scope['generation_seconds']=time.monotonic()-start;write(folder/'scope.json',scope)
    rr=run([TOOLS['z3'],'-smt2',str(path)],folder/'solver',600,solver=True)
    stdout=(folder/'solver/stdout.log').read_text(errors='replace');stderr=(folder/'solver/stderr.log').read_text(errors='replace')
    result={'kind':kind,'case':case,'scope':scope,'solver':rr,'raw_outcome':next((x.strip() for x in stdout.splitlines() if x.strip() in ('sat','unsat','unknown')),None),'verified_sat':False,'stderr_tail':stderr[-3000:]}
    if result['raw_outcome']=='sat':
        pairs=re.findall(r'\(w(\d+)\s+(-?\d+|\(-\s+\d+\))\)',stdout);vals={int(w):int(v) if not v.startswith('(') else -int(re.search(r'\d+',v).group()) for w,v in pairs}
        write(folder/'model.json',{str(w):str(v) for w,v in vals.items()})
        if set(vals)==set(range(1,r0.n)):
            result['verification']=verify([1]+[vals[w] for w in range(1,r0.n)],folder/'verify',site,kind,pins if kind=='Q1' else None)
            result['verified_sat']=result['verification']['verified_sat']
        else:result['model_error']='incomplete_model'
    result['outcome']='SAT_verified' if result['verified_sat'] else 'UNSAT' if result['raw_outcome']=='unsat' and rr['status']=='completed' else 'unknown'
    write(folder/'result.json',result);print(json.dumps({'query':case+' '+kind,'outcome':result['outcome'],'seconds':rr['seconds']},ensure_ascii=False),flush=True)
    return result


def main():
    global STOP
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','probe','queries','query']);p.add_argument('--case',choices=IDS);p.add_argument('--kind',choices=['Q1','Q3','Q2']);args=p.parse_args()
    if os.getpriority(os.PRIO_PROCESS,0)!=19:raise RuntimeError('nice 19 required')
    def stopped(sig,frame):
        global STOP
        STOP=True
    signal.signal(signal.SIGTERM,stopped);signal.signal(signal.SIGINT,stopped)
    if args.action=='prepare':prepare()
    elif args.action=='probe':
        for case in ((args.case,) if args.case else IDS):probe(case)
    elif args.action=='query':query(args.case,args.kind)
    else:
        for kind in ('Q1','Q3','Q2'):
            for case in IDS:
                if load(OUT/'budget.json')['solver_seconds']>=7200:break
                query(case,kind)
    print(json.dumps({'finished_action':args.action,'budget':load(OUT/'budget.json')},ensure_ascii=False),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as e:
        if OUT.exists():write(OUT/('error-'+datetime.now(timezone.utc).strftime('%H%M%S')+'.json'),{'type':type(e).__name__,'message':str(e)})
        raise
