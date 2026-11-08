#!/usr/bin/env python3
"""Two-class synthetic budget comparison, verified 4 original constraints."""
import json
import os
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/j-boost-2026-10-27'
if os.getpriority(os.PRIO_PROCESS,0)!=19:raise SystemExit('nice 19 required')
request=RUN/'multi-class-fixture-v1/request.json'
rows=[]
for arm,engine,extra in [('shared',ROOT/'runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development',[]),('per_class',RUN/'cargo-target/debug/zkfdo-j-v23',['--class-sweep-budget-seconds','20'])]:
    folder=RUN/f'multi-class-{arm}-result'
    if folder.exists():raise SystemExit('already exists: '+str(folder))
    command=[str(engine),'--request',str(request),'--output',str(folder),'--cache',str(RUN/f'multi-class-{arm}-cache'),'--instance-store',str(RUN/f'multi-class-{arm}-store')]
    for tool in ['circom','node','snarkjs','z3']:
        value=shutil.which(tool)
        if value is None:raise SystemExit('tool missing '+tool)
        command += ['--'+tool+'-bin',value]
    result=subprocess.run([*command,*extra],cwd=ROOT,capture_output=True,text=True,timeout=300,check=False)
    row={'arm':arm,'returncode':result.returncode,'stderr':result.stderr[-1000:]}
    if result.returncode==0:
        report=json.loads((folder/'result.json').read_text())
        row['classes']=[{'site':x['representative'],'verdict':x['verdict'],'reason':x['reason']} for x in report['classes']]
        sidecar=folder/'j-boost.json'
        row['budgets']=[r for r in json.loads(sidecar.read_text())['records'] if r.get('kind')=='class_budget'] if sidecar.exists() else []
    rows.append(row)
with (RUN/'multi-class-budget-summary.json').open('x') as f:f.write(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
print(json.dumps([{'arm':r['arm'],'returncode':r['returncode'],'classes':len(r.get('classes',[])),'budget_rows':len(r.get('budgets',[]))} for r in rows]))
if not all(r['returncode']==0 for r in rows) or len(rows[0]['classes'])!=2 or len(rows[1]['budgets'])!=2:raise SystemExit(2)
