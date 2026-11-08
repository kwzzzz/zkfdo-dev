#!/usr/bin/env python3
"""Synthetic crossover v2: child clocks, call sites, disk peaks, actual cleanup.

v1 evidence is preserved. This version corrects instrumentation, not policy or
workload selection: the four policies, 32 MiB inputs and fixed 4 GiB child hash
remain identical. Per-operation and per-call-site timings overlap; never add
those two views together or subtract them from elapsed wall to infer speedup.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from preexp_observer_bench_v1 import LegacyMeter, POLICIES, ORDER, SIZE
from zkfdo_observer_v1 import DiskBudget, ObservationCosts
import zkfdo_platform as platform

CHILD_CODE = """import hashlib,json,time
b=b'x'*(2**20)
h=hashlib.sha256()
wall,cpu=time.monotonic(),time.process_time()
for _ in range(4096): h.update(b)
print(json.dumps({'sha256':h.hexdigest(),'payload_wall_seconds':time.monotonic()-wall,
                  'payload_cpu_seconds':time.process_time()-cpu}),flush=True)
"""


def reap(proc, *, terminate=False, grace_seconds=.5):
    """Reap the owned direct child exactly once and preserve wait4 CPU."""
    if terminate:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace_seconds
    while True:
        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            proc.returncode = os.waitstatus_to_exitcode(status)
            return usage
        if time.monotonic() >= deadline:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _, status, usage = os.wait4(proc.pid, 0)
            proc.returncode = os.waitstatus_to_exitcode(status)
            return usage
        time.sleep(.01)


def run_one(root, source, files, repetition, policy, *, child_code=CHILD_CODE):
    task = root / f'n{files}-r{repetition}-{policy}'
    request = task / 'request'
    prepared_start = time.monotonic()
    shutil.copytree(source / str(files), request)
    prepared = time.monotonic() - prepared_start
    if policy == 'v5':
        meter = LegacyMeter(task, request)
        budgets = meter.budgets
        sample_gate = meter.gate
    elif policy != 'baseline':
        meter = DiskBudget(task, 256 * 2**20, tree_interval_seconds=1,
                           free_interval_seconds=.25 if policy.startswith('free_') else 0)
        sub = DiskBudget(request, 256 * 2**20, parent=meter)
        budgets = (meter, sub)
        sample_gate = lambda force=False: meter.check(force=force)
    else:
        meter, budgets = None, ()
        sample_gate = lambda force=False: None
    sites = {}
    site_costs = ObservationCosts()

    def counters():
        if isinstance(meter, LegacyMeter):
            return sum(b.samples for b in budgets), meter.visits
        return (meter.samples, meter.visited_entries) if meter is not None else (0, 0)

    def gate(site, force=False):
        scans_before, visits_before = counters()
        row = sites.setdefault(site, {'calls': 0, 'forced_calls': 0, 'tree_traversals': 0, 'visited_entries': 0})
        row['calls'] += 1
        row['forced_calls'] += int(force)
        try:
            with site_costs.measure(site):
                sample_gate(force=force)
        finally:
            scans_after, visits_after = counters()
            row['tree_traversals'] += scans_after - scans_before
            row['visited_entries'] += visits_after - visits_before

    clock_before = platform.clock_snapshot()
    cpu_before = time.process_time()
    start = time.monotonic()
    proc, usage, child_start, child_end = None, None, None, None
    digest = hashlib.sha256()
    copy_bytes = 0
    errors = []
    status = 'completed'
    try:
        gate('before_launch', force=True)
        with (task / 'child.json').open('x') as output:
            child_start = time.monotonic()
            proc = subprocess.Popen([sys.executable, '-c', child_code], stdout=output,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
            with (source / 'large.bin').open('rb') as inp, (request / 'copy.bin').open('xb') as out:
                while block := inp.read(2**20):
                    gate('copy_before_write')
                    out.write(block)
                    copy_bytes += len(block)
                    gate('copy_after_write')
                    digest.update(block)
            gate('after_copy', force=True)
            while True:
                pid, wait_status, usage_result = os.wait4(proc.pid, os.WNOHANG)
                if pid:
                    usage = usage_result
                    proc.returncode = os.waitstatus_to_exitcode(wait_status)
                    child_end = time.monotonic()
                    break
                gate('wait_poll')
                time.sleep(.05)
            if proc.returncode != 0:
                status = 'child_failed'
    except BaseException as error:
        status = 'interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'observation_or_work_failed'
        errors.append(type(error).__name__ + ': ' + str(error))
    finally:
        cleanup_start = time.monotonic()
        if proc is not None and proc.returncode is None:
            try:
                usage = reap(proc, terminate=True)
                child_end = time.monotonic()
            except (OSError, ChildProcessError) as error:
                errors.append('cleanup:' + type(error).__name__)
        cleanup_seconds = time.monotonic() - cleanup_start
        cleanup_complete = proc is None or proc.returncode is not None
        if not cleanup_complete:
            status = 'cleanup_incomplete'
        try:
            gate('final', force=True)
        except Exception as error:
            errors.append('final_gate:' + type(error).__name__ + ': ' + str(error))
            if status == 'completed':
                status = 'final_observation_failed'
    wall = time.monotonic() - start
    parent_cpu = time.process_time() - cpu_before
    clock_delta = platform.clock_delta(clock_before, platform.clock_snapshot())
    child = None
    if proc is not None and proc.returncode == 0:
        try:
            child = json.loads((task / 'child.json').read_text())
            for key in ('payload_wall_seconds', 'payload_cpu_seconds'):
                if not isinstance(child[key], (int, float)) or not math.isfinite(child[key]) or child[key] < 0:
                    raise ValueError('invalid child duration')
            if not isinstance(child['sha256'], str) or len(child['sha256']) != 64:
                raise ValueError('invalid child hash')
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append('child_metrics:' + type(error).__name__)
            status = 'child_measurement_failed'
            child = None
    observations = meter.costs.snapshot() if meter is not None else {}
    scans, visits = counters()
    observer_wall = sum(v['wall_seconds'] for v in observations.values())
    observer_cpu = sum(v['cpu_seconds'] for v in observations.values())
    child_cpu = usage.ru_utime + usage.ru_stime if usage is not None else None
    disk = [{'scope': scope, 'max_disk_bytes': b.max_bytes, 'current_bytes': b.last_bytes,
             'peak_bytes': b.peak_bytes, 'samples': b.samples, 'stop_reason': b.tripped}
            for scope, b in zip(('task', 'request'), budgets)]
    row = dict(schema='preexp-observer-trial-v2', files=files, repetition=repetition, policy=policy,
               fixture_copy_seconds=prepared, wall_seconds=wall, parent_cpu_seconds=parent_cpu,
               child_completion_upper_bound_seconds=child_end-child_start if child_end is not None else None,
               child_payload_wall_seconds=child['payload_wall_seconds'] if child else None,
               child_payload_cpu_seconds=child['payload_cpu_seconds'] if child else None,
               child_cpu_seconds=child_cpu, total_cpu_seconds=parent_cpu+child_cpu if child_cpu is not None else None,
               observer_wall_seconds=observer_wall, observer_cpu_seconds=observer_cpu,
               observer_wall_fraction=observer_wall/wall, observations=observations,
               callsites={key: {**value, **site_costs.snapshot()[key]} for key, value in sites.items()},
               visited_entries=visits, tree_scans=scans, disk_budgets=disk,
               child_max_rss_bytes=platform.normalize_ru_maxrss(usage.ru_maxrss) if usage else None,
               artifact_sha256=digest.hexdigest(), copied_bytes=copy_bytes,
               child_sha256=child['sha256'] if child else None, child_pid=proc.pid if proc else None,
               returncode=proc.returncode if proc else None, stop_reason=status,
               cleanup_complete=cleanup_complete, cleanup_seconds=cleanup_seconds, errors=errors,
               clock_delta=clock_delta, measurement_valid=(status == 'completed' and cleanup_complete and
                   not errors and not any(clock_delta.get(k) for k in
                   ('suspend_evidence','clock_adjustment_evidence','unclassified_clock_discrepancy','capture_ambiguous'))),
               measurement_scope={'child_payload': 'child monotonic/process_time around fixed SHA loop; excludes interpreter startup',
                 'child_completion': 'parent Popen-before to wait4-after observation upper bound',
                 'observer': 'disk sampler inner costs; callsites are overlapping gate-dispatch timing and must not be added',
                 'total': 'trial through final gate, including reap/cleanup; fixture copy and receipt serialization excluded',
                 'baseline_disk': 'unmeasured; baseline intentionally has no disk observer'})
    (root / (task.name + '.json')).write_text(json.dumps(row, indent=2)+'\n')
    if cleanup_complete:
        shutil.rmtree(task)
    print(json.dumps({k: row[k] for k in ('files','repetition','policy','wall_seconds','observer_wall_seconds','measurement_valid')}), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if not root.is_relative_to((Path(__file__).resolve().parents[1]/'runs').resolve()):
        parser.error('output must be a fresh owned directory under runs/')
    root.mkdir(parents=True, exist_ok=False)
    source = root/'fixtures'
    source.mkdir()
    start = time.monotonic()
    for files in (64,4096):
        folder=source/str(files)
        folder.mkdir()
        for i in range(8):
            (folder/str(i)).mkdir()
        payload=b'x'*(SIZE//files)
        for i in range(files):
            (folder/str(i%8)/f'{i:04d}.bin').write_bytes(payload)
    (source/'large.bin').write_bytes(b'x'*SIZE)
    plan=dict(schema='preexp-observer-bench-v2', bytes_per_fixture=SIZE, file_counts=[64,4096],
              order=ORDER, policies=POLICIES, repetitions=3, fixture_seconds=time.monotonic()-start,
              revision_reason='instrumentation completeness: child self clocks, callsites, disk peaks and exception cleanup; v1 evidence preserved',
              acceptance={'artifact_and_exit_equal':True, 'new_observer_wall_fraction_target':.10,
                          'tree_detection_bound':'1 second plus traversal/poll latency; forced launch/end checks',
                          'overshoot':'no numeric hard bound without writer rate; sampled limit, not quota'},
              environment={'load_average':os.getloadavg(),'platform':sys.platform},
              cache_policy='warm; no OS cache eviction; fixed crossover order', maximum_fixture_bytes=SIZE*5+2**20,
              source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              source_dependencies=[{"path": "scripts/" + name,
                  "sha256": hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()}
                  for name in ("preexp_observer_bench_v1.py", "zkfdo_observer_v1.py",
                               "zkfdo_runtime_v1.py", "zkfdo_platform.py")],
              child_code_sha256=hashlib.sha256(CHILD_CODE.encode()).hexdigest())
    (root/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    rows=[]
    for repetition, order in enumerate(ORDER):
        for files in ((64,4096) if repetition%2==0 else (4096,64)):
            for index in order:
                row=run_one(root,source,files,repetition,POLICIES[index])
                rows.append(row)
                if not row['cleanup_complete'] or row['stop_reason'] == 'interrupted':
                    break
            if rows and (not rows[-1]['cleanup_complete'] or rows[-1]['stop_reason']=='interrupted'):
                break
        if rows and (not rows[-1]['cleanup_complete'] or rows[-1]['stop_reason']=='interrupted'):
            break
    results=dict(schema='preexp-observer-bench-results-v2',rows=rows,
                 artifacts_equal=(len(rows)==24 and len({r['artifact_sha256'] for r in rows})==1
                                  and len({r['child_sha256'] for r in rows})==1
                                  and all(r['copied_bytes']==SIZE for r in rows)),
                 all_success=len(rows)==24 and all(r['returncode']==0 and r['measurement_valid'] for r in rows))
    (root/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    shutil.rmtree(source)
    return 0 if results['all_success'] and results['artifacts_equal'] else 1


if __name__=='__main__':
    raise SystemExit(main())
