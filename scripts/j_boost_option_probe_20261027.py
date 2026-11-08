#!/usr/bin/env python3
"""Small, bounded option smoke test; fixture count verified by 4d probe."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/j-boost-2026-10-27'
OLD=ROOT/'runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development'
NEW=RUN/'cargo-target/debug/zkfdo-j-v23'
REQUEST=ROOT/'tests/fixtures/lifting_engine/hint_injection/request.json'
if os.getpriority(os.PRIO_PROCESS,0)!=19:raise SystemExit('nice 19 required')
probe=json.loads((RUN/'fixture-probe-v1/summary.json').read_text())
assert probe['all_at_most_1000'] and any(r['fixture'].endswith('hint_injection/src/entrypoint.circom') and r['constraints']<=1000 for r in probe['rows'])
rows=[]
for arm,engine,extra in [('old',OLD,[]),('fair',NEW,['--class-sweep-budget-seconds','20','--injection-diagnostics']),('direct',NEW,['--class-sweep-budget-seconds','20','--constraint-witness'])]:
    output=RUN/f'option-probe-{arm}'
    if output.exists():raise SystemExit('probe output already exists')
    argv=[str(engine),'--request',str(REQUEST),'--output',str(output),'--cache',str(RUN/f'option-probe-{arm}-cache'),'--instance-store',str(RUN/f'option-probe-{arm}-store')]
    for tool in ['circom','node','snarkjs','z3']:
        found=shutil.which(tool)
        if not found:raise SystemExit('missing '+tool)
        argv += ['--'+tool+'-bin',found]
    argv += extra
    completed=subprocess.run(argv,cwd=ROOT,check=False,capture_output=True,text=True,timeout=300)
    row={'arm':arm,'returncode':completed.returncode,'stdout':completed.stdout[-500:],'stderr':completed.stderr[-500:],'engine_sha256':hashlib.sha256(engine.read_bytes()).hexdigest()}
    if completed.returncode or not (output/'result.json').exists():
        rows.append(row);break
    result=json.loads((output/'result.json').read_text());row['preparation']=result['preparation'];row['classes']=[(x['representative'],x['verdict'],x['reason']) for x in result['classes']]
    sidecar=output/'j-boost.json';row['sidecar_exists']=sidecar.exists()
    if sidecar.exists():
        data=json.loads(sidecar.read_text());row['budget_rows']=[r for r in data['records'] if r.get('kind')=='class_budget'];row['injection_diagnostics']=sum(r.get('kind')=='injection_diagnostic' for r in data['records'])
    rows.append(row)
summary={'fixture':str(REQUEST),'rows':rows,'same_old_verdict':len(rows)==3 and all(r['returncode']==0 for r in rows) and rows[0]['preparation']==rows[1]['preparation']==rows[2]['preparation'] and rows[0]['classes']==rows[1]['classes']==rows[2]['classes'],'old_no_sidecar':len(rows)==3 and not rows[0]['sidecar_exists']}
with (RUN/'option-probe-summary.json').open('x') as f:f.write(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'same_old_verdict':summary['same_old_verdict'],'old_no_sidecar':summary['old_no_sidecar'],'rows':len(rows)}))
if not summary['same_old_verdict'] or not summary['old_no_sidecar']:raise SystemExit(2)
