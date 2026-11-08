#!/usr/bin/env python3
"""Bounded synthetic observer crossover; no circuit or candidate inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

from zkfdo_observer_v1 import DiskBudget, ObservationCosts
import zkfdo_runtime_v1 as legacy
import zkfdo_platform as platform

POLICIES = ('baseline', 'v5', 'tree_1s', 'free_250ms_tree_1s')
ORDER = ((0, 1, 2, 3), (3, 2, 1, 0), (1, 3, 0, 2))
SIZE = 32 * 2**20


class LegacyMeter:
    def __init__(self, task, request):
        self.budgets = (legacy.DiskBudget(task, 256 * 2**20), legacy.DiskBudget(request, 256 * 2**20))
        self.costs = ObservationCosts()
        self.visits = 0

    def gate(self, force=False):
        original = os.scandir
        owner = self
        def counted(path):
            # v1 materializes scandir with list; preserve that exact traversal.
            with original(path) as iterator:
                for entry in iterator:
                    owner.visits += 1
                    yield entry
        os.scandir = counted
        try:
            with self.costs.measure('tree_and_free'):
                for budget in self.budgets:
                    budget.check()
        finally:
            os.scandir = original


def run_one(root, source, files, repetition, policy):
    task = root / f'n{files}-r{repetition}-{policy}'
    request = task / 'request'
    before = time.monotonic()
    shutil.copytree(source / str(files), request)
    prepared = time.monotonic() - before
    if policy == 'v5':
        meter = LegacyMeter(task, request)
        gate = meter.gate
    elif policy != 'baseline':
        meter = DiskBudget(task, 256 * 2**20, tree_interval_seconds=1,
                           free_interval_seconds=.25 if policy.startswith('free_') else 0)
        DiskBudget(request, 256 * 2**20, parent=meter)
        gate = lambda force=False: meter.check(force=force)
    else:
        meter = None
        gate = lambda force=False: None
    clock_before = platform.clock_snapshot()
    cpu_before = time.process_time()
    start = time.monotonic()
    gate(force=True)
    # Fixed CPU work: 4 GiB SHA-256; result independent of observer schedule.
    child_code = "import hashlib; b=b'x'*(2**20); h=hashlib.sha256(); [h.update(b) for _ in range(4096)]; print(h.hexdigest())"
    with (task / 'child.txt').open('w') as output:
        child_start = time.monotonic()
        proc = subprocess.Popen([sys.executable, '-c', child_code], stdout=output)
        digest = hashlib.sha256()
        with (source / 'large.bin').open('rb') as inp, (request / 'copy.bin').open('wb') as out:
            while block := inp.read(2**20):
                gate()
                out.write(block)
                gate()
                digest.update(block)
        gate(force=True)
        while True:
            pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
            if pid:
                proc.returncode = os.waitstatus_to_exitcode(status)
                break
            gate()
            time.sleep(.05)
        child_wall = time.monotonic() - child_start
    gate(force=True)
    wall = time.monotonic() - start
    parent_cpu = time.process_time() - cpu_before
    clock_delta = platform.clock_delta(clock_before, platform.clock_snapshot())
    if isinstance(meter, LegacyMeter):
        observations = meter.costs.snapshot()
        visits = meter.visits
        scans = sum(b.samples for b in meter.budgets)
    elif meter is not None:
        observations = meter.costs.snapshot()
        visits, scans = meter.visited_entries, meter.samples
    else:
        observations, visits, scans = {}, 0, 0
    observer_wall = sum(v['wall_seconds'] for v in observations.values())
    observer_cpu = sum(v['cpu_seconds'] for v in observations.values())
    row = dict(files=files, repetition=repetition, policy=policy, fixture_copy_seconds=prepared,
               wall_seconds=wall, parent_cpu_seconds=parent_cpu,
               child_wall_seconds=child_wall, child_cpu_seconds=usage.ru_utime+usage.ru_stime,
               total_cpu_seconds=parent_cpu+usage.ru_utime+usage.ru_stime,
               observer_wall_seconds=observer_wall, observer_cpu_seconds=observer_cpu,
               observer_wall_fraction=observer_wall/wall, observations=observations,
               visited_entries=visits, tree_scans=scans,
               child_max_rss_bytes=platform.normalize_ru_maxrss(usage.ru_maxrss),
               artifact_sha256=digest.hexdigest(), child_sha256=(task/'child.txt').read_text().strip(),
               returncode=proc.returncode, stop_reason='completed', cleanup_complete=True,
               clock_delta=clock_delta, measurement_valid=not any(clock_delta.get(k) for k in
                 ('suspend_evidence','clock_adjustment_evidence','unclassified_clock_discrepancy','capture_ambiguous')))
    (root / (task.name + '.json')).write_text(json.dumps(row, indent=2)+'\n')
    shutil.rmtree(task)  # Owned synthetic data only; receipts survive.
    print(json.dumps({k: row[k] for k in ('files','repetition','policy','wall_seconds','observer_wall_seconds','measurement_valid')}), flush=True)
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    root=args.output.resolve()
    if not root.is_relative_to((Path(__file__).resolve().parents[1]/'runs').resolve()):
        parser.error('output must be a fresh owned directory under runs/')
    root.mkdir(parents=True, exist_ok=False)
    source=root/'fixtures'; source.mkdir()
    start=time.monotonic()
    for files in (64,4096):
        folder=source/str(files); folder.mkdir()
        for i in range(8): (folder/str(i)).mkdir()
        payload=b'x'*(SIZE//files)
        for i in range(files): (folder/str(i%8)/f'{i:04d}.bin').write_bytes(payload)
    (source/'large.bin').write_bytes(b'x'*SIZE)
    plan=dict(schema='preexp-observer-bench-v1', bytes_per_fixture=SIZE, file_counts=[64,4096],
              order=ORDER, policies=POLICIES, repetitions=3, fixture_seconds=time.monotonic()-start,
              acceptance={'artifact_and_exit_equal':True, 'new_observer_wall_fraction_target':.10,
                          'tree_detection_bound':'1 second plus traversal/poll latency; forced launch/end checks',
                          'overshoot':'no numeric hard bound without writer rate; sampled limit, not quota'},
              environment={'load_average':os.getloadavg(),'platform':sys.platform},
              cache_policy='warm; no OS cache eviction; fixed crossover order', maximum_fixture_bytes=SIZE*5)
    (root/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    rows=[]
    for repetition, order in enumerate(ORDER):
        for files in ((64,4096) if repetition%2==0 else (4096,64)):
            for index in order: rows.append(run_one(root,source,files,repetition,POLICIES[index]))
    results=dict(schema='preexp-observer-bench-results-v1',rows=rows,
                 artifacts_equal=len({r['artifact_sha256'] for r in rows})==1 and len({r['child_sha256'] for r in rows})==1,
                 all_success=all(r['returncode']==0 and r['measurement_valid'] for r in rows))
    (root/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    shutil.rmtree(source)
    return 0 if results['all_success'] and results['artifacts_equal'] else 1


if __name__=='__main__': raise SystemExit(main())
