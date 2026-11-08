#!/usr/bin/env python3
"""Post-aq command runner. This file is prepared only; no measurement was run today."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/j-boost-2026-10-27'
GIB=2**30

def free_bytes():
    s=os.statvfs('/')
    return s.f_bavail*s.f_frsize

def within(path,root):
    return Path(path).resolve().is_relative_to(root.resolve())

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--aq-stopped',action='store_true',help='explicit operator attestation before execution')
    args=p.parse_args()
    if not args.aq_stopped:raise SystemExit('aq-stopped attestation required')
    if os.getpriority(os.PRIO_PROCESS,0)!=19:raise SystemExit('nice 19 required')
    plan=args.plan.resolve(strict=True);out=args.output.absolute()
    if not within(plan,RUN) or out.exists() or not within(out,RUN):raise SystemExit('plan/output must be fresh under j-boost')
    commands=json.loads(plan.read_text())['commands']
    old=ROOT/'runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development'
    new=RUN/'cargo-target/debug/zkfdo-j-v23'
    seed=plan.parent/'z3-seeded'
    allowed={str(old),str(new),str(seed)}
    for c in commands:
        if not c['argv'] or c['argv'][0] not in allowed:raise SystemExit('unexpected command')
        if not 1<=int(c['external_wall_cap_seconds'])<=10800:raise SystemExit('wall cap invalid')
        if c['arm']!='local_refutation_recheck':
            if hashlib.sha256(Path(c['argv'][0]).read_bytes()).hexdigest()!=c['engine_sha256']:
                raise SystemExit('engine SHA differs from prepared plan')
            a=c['argv'];d=dict(zip(a[1::2],a[2::2]))
            for flag in ('--output','--cache','--instance-store'):
                if flag not in d or not within(d[flag],RUN):raise SystemExit('output escaped j-boost')
            if '--request' not in d or not within(d['--request'],ROOT/'runs/j-dev-2026-10-27'):raise SystemExit('request escaped j-dev')
            if hashlib.sha256(Path(d['--request']).read_bytes()).hexdigest()!=c['request_sha256']:
                raise SystemExit('request SHA differs from prepared plan')
    out.mkdir(parents=True);tmp=out/'tmp';tmp.mkdir()
    env=dict(os.environ,TMPDIR=str(tmp),PYTHONDONTWRITEBYTECODE='1',RAYON_NUM_THREADS='1',OMP_NUM_THREADS='1')
    for index,c in enumerate(commands):
        folder=out/f'command-{index:04d}';folder.mkdir()
        if free_bytes()<20*GIB:raise SystemExit('internal disk below 20 GiB before command')
        started=time.monotonic();status='running'
        with (folder/'stdout.log').open('xb') as stdout,(folder/'stderr-time.log').open('xb') as stderr:
            process=subprocess.Popen(['/usr/bin/time','-l',*c['argv']],cwd=ROOT,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
            while process.poll() is None:
                if free_bytes()<18*GIB:status='internal_18GiB_stop'
                elif time.monotonic()-started>=c['external_wall_cap_seconds']:status='wall_cap'
                if status!='running':
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL)
                    break
                time.sleep(1)
            code=process.wait()
        if status=='running':status='completed' if code==0 else 'failed'
        timing=(folder/'stderr-time.log').read_text(errors='replace')
        match=re.search(r'(\d+)\s+maximum resident set size',timing)
        row={'case':c['case'],'arm':c['arm'],'seed':c.get('seed'),'status':status,'returncode':code,
             'wall_seconds':time.monotonic()-started,'wall_cap_seconds':c['external_wall_cap_seconds'],
             'max_rss_bytes':int(match.group(1)) if match else None,'argv':c['argv']}
        with (folder/'result.json').open('x') as receipt:receipt.write(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'case':row['case'],'arm':row['arm'],'status':status}),flush=True)
        if status!='completed':raise SystemExit('measurement stopped; inspect per-command receipt')
if __name__=='__main__':main()
