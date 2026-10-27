#!/usr/bin/env python3
"""Compile generated prototype wrappers serially, retaining bounded evidence only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time
from s_tag_wrapper_run_20261027 import ROOT, OUT, gate, now, record
COMPILER = ROOT / "runs/c02-corpus-2026-10-02/tools/circom"
COMPILER_SHA = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""): h.update(block)
    return h.hexdigest()
def read_header(path):
    with path.open("rb") as f:
        if f.read(4) != b"r1cs": raise ValueError("bad R1CS magic")
        version, count = struct.unpack("<II", f.read(8))
        if version != 1: raise ValueError("unsupported R1CS version")
        for _ in range(count):
            kind, length = struct.unpack("<IQ", f.read(12))
            start=f.tell()
            if kind == 1:
                width=struct.unpack("<I",f.read(4))[0]
                if width != 32: raise ValueError("unexpected field width")
                prime=int.from_bytes(f.read(width),"little")
                if prime != 21888242871839275222246405745257275088548364400416034343698204186575808495617: raise ValueError("unexpected field")
                wires, outputs, public, private = struct.unpack("<IIII",f.read(16))
                labels=struct.unpack("<Q",f.read(8))[0]
                constraints=struct.unpack("<I",f.read(4))[0]
                return dict(wires=wires,public_outputs=outputs,public_inputs=public,private_inputs=private,labels=labels,constraints=constraints)
            f.seek(start+length)
    raise ValueError("R1CS header missing")
def compiler_args(definition):
    if definition.get("prime") != "bn128": raise ValueError("explicit bn128 required")
    values=definition.get("compile_args",[]); result=[]; i=0
    while i<len(values):
        if values[i]!="-l" or i+1==len(values): raise ValueError("only original -l options permitted")
        result += ["-l",str(Path(values[i+1]).resolve())];i+=2
    return result

def run_one(target, folder, timeout):
    gate();folder.mkdir(parents=True,exist_ok=False)
    wrapper=Path(target["wrapper_path"]).resolve()
    if not wrapper.is_relative_to(OUT) or digest(wrapper)!=target["wrapper_sha256"]:raise ValueError("new wrapper binding mismatch")
    argv=[str(COMPILER),str(wrapper),"--r1cs","--sym","--prime","bn128","--output",str(folder),*compiler_args(target["definition"])]
    row={"unit":target["unit"],"label":target["label"],"template":target["template"],"wrapper":str(wrapper),"wrapper_sha256":digest(wrapper),"argv":argv,"compiler_sha256":COMPILER_SHA,"start_utc":now(),"cpu_contention":True,"nice":os.getpriority(os.PRIO_PROCESS,0),"timeout_seconds":timeout}
    started=time.monotonic();stdout=folder/'stdout.log';stderr=folder/'stderr.log'
    try:
        with stdout.open('xb') as out,stderr.open('xb') as err:
            result=subprocess.run(argv,cwd=ROOT,env=dict(os.environ,RAYON_NUM_THREADS='1',OMP_NUM_THREADS='1'),stdout=out,stderr=err,timeout=timeout,check=False)
            row['returncode']=result.returncode
    except subprocess.TimeoutExpired:row.update(returncode=124,error='compile timeout')
    row.update(end_utc=now(),elapsed_seconds=time.monotonic()-started,free_bytes_end=__import__('shutil').disk_usage(ROOT).free)
    r1cs=folder/(wrapper.stem+'.r1cs');sym=folder/(wrapper.stem+'.sym');row['compile_success']=row['returncode']==0 and r1cs.is_file()
    row['artifacts']=[]
    for f in [r1cs,sym]:
        if f.is_file():
            info={'path':str(f),'bytes':f.stat().st_size,'sha256':digest(f)}
            if f==r1cs and row['compile_success']:
                try:row['r1cs_header']=read_header(f)
                except (ValueError,struct.error) as error:row.update(compile_success=False,error=str(error))
            if f==sym:
                count=0;examples=[]
                with f.open() as stream:
                    for line in stream:
                        count+=1
                        if len(examples)<8:examples.append(line.rstrip())
                row['symbol_lines']=count;row['symbol_examples']=examples
            row['artifacts'].append(info)
            f.unlink() # Only this invocation's new R1CS/sym; logs and receipts stay.
    row['stdout']={'path':str(stdout),'sha256':digest(stdout)};row['stderr']={'path':str(stderr),'sha256':digest(stderr)}
    row['compiler_diagnostic']=stderr.read_text(errors='replace')[:16000]
    receipt=folder/'result.json';receipt.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
    record('records',{'kind':'circom','record_path':str(receipt),**{k:row[k] for k in ['unit','label','template','argv','start_utc','end_utc','cpu_contention','nice','returncode','elapsed_seconds']}})
    return row,{'path':str(receipt),'sha256':digest(receipt)}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--timeout',type=int,default=60);args=p.parse_args();gate()
    output=args.output.resolve()
    if not output.is_relative_to(OUT) or output.exists():raise ValueError('fresh output in prototype folder required')
    if digest(COMPILER)!=COMPILER_SHA:raise ValueError('compiler SHA differs')
    plan=json.loads(args.plan.read_text());output.mkdir(parents=True)
    summary={'started_at':now(),'plan':str(args.plan.resolve()),'plan_sha256':digest(args.plan),'results':[],'stopped':None,'refused':[]}
    try:
        for i,target in enumerate(plan['targets']):
            if target['status']!='generated':summary['refused'].append(target);continue
            row,ref=run_one(target,output/f'{i:04d}',args.timeout)
            summary['results'].append({'unit':target['unit'],'label':target['label'],'template':target['template'],'compile_success':row['compile_success'],'constraints':row.get('r1cs_header',{}).get('constraints'),'result':ref})
            print(json.dumps(summary['results'][-1],ensure_ascii=False),flush=True)
    except (OSError,ValueError,RuntimeError) as error:summary['stopped']=str(error)
    summary.update(finished_at=now(),passed=sum(r['compile_success'] for r in summary['results']),failed=sum(not r['compile_success'] for r in summary['results']))
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k not in ['results','refused']},ensure_ascii=False),flush=True)
    raise SystemExit(2 if summary['stopped'] else 0)
if __name__=='__main__':main()
