#!/usr/bin/env python3
"""Run cargo test on the dedicated target, deferring the 24 J tests to their bounded harness."""
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/j-boost-2026-10-27'
if os.getpriority(os.PRIO_PROCESS,0)!=19:raise SystemExit('nice 19 required')
names=json.loads((ROOT/'runs/s-inspection-improve-2026-10-27/cargo-command-reference.json').read_text())['skipped_J_tests']
if len(names)!=24 or len(set(names))!=24 or any(not x.isidentifier() for x in names):raise SystemExit('24-test inventory invalid')
argv=[sys.executable,'-B',str(ROOT/'scripts/j_boost_monitor_20261027.py'),'--label','cargo-test-gate-final','--cargo','--timeout','10800','--','cargo','test','--offline','-j','1','--','--test-threads=1',*(x for n in names for x in ('--skip',n))]
result=subprocess.run(argv,cwd=ROOT,check=False)
(RUN/'cargo-test-invocation.json').write_text(json.dumps({'argv':argv,'returncode':result.returncode,'skipped_24_run_separately':names},indent=2)+'\n')
raise SystemExit(result.returncode)
