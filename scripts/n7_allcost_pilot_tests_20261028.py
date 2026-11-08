#!/usr/bin/env python3
"""Meaningful process-ownership/deadline guards for the synthetic N7 supervisor."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from n7_allcost_supervisor_20261028 import run_bounded
from n7_allcost_pilot_20261028 import owned, save


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = owned(args.output)
    folder.mkdir(parents=True, exist_ok=False)
    results = []
    normal = run_bounded([sys.executable, "-c", "import os; assert os.getpriority(os.PRIO_PROCESS,0)==19; print('ok')"], folder / "normal", 5)
    assert normal["status"] == "completed" and normal["cleanup_complete"], normal
    results.append({"test": "normal_completion_and_nice", "passed": True})
    # An unrelated sibling must survive while a detached owned grandchild dies.
    sibling = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        marker = folder / "detached-pid.json"
        code = ("import subprocess,sys,time,json; "
                "p=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'],start_new_session=True); "
                f"open({str(marker)!r},'w').write(json.dumps({{'pid':p.pid}})); time.sleep(60)")
        timed = run_bounded([sys.executable, "-c", code], folder / "timeout", 2)
        assert timed["status"] == "timeout" and timed["cleanup_complete"], timed
        assert marker.is_file(), "detached child did not start"
        child = json.loads(marker.read_text())["pid"]
        assert any(p["pid"] == child for p in timed["owned_processes"]), "detached child unobserved"
        assert any(p["pid"] == child and p["signal"] == 9 for p in timed["signals_sent"]), "TERM-resistant child was not killed"
        assert sibling.poll() is None, "unrelated sibling was killed"
        results.append({"test": "deadline_detached_descendant_and_sibling_isolation", "passed": True,
                        "wall_seconds": timed["wall_seconds"], "tail_seconds": timed["tail_seconds"]})
    finally:
        sibling.terminate()
        sibling.wait(timeout=5)
    memory = run_bounded([sys.executable, "-c", "raise RuntimeError('must not be released')"], folder / "memory", 5, memory_cap_bytes=1)
    assert memory["status"] == "memory_limit" and memory["cleanup_complete"], memory
    results.append({"test": "memory_guard_before_payload", "passed": True})
    disk = run_bounded([sys.executable, "-c", "raise RuntimeError('must not run')"], folder / "disk", 5, min_free_bytes=2**60)
    assert disk["status"] == "disk_limit" and "pid" not in disk, disk
    results.append({"test": "disk_guard_before_spawn", "passed": True})
    try:
        run_bounded([sys.executable, "-c", "pass"], folder.parents[1] / "../outside-n7-forbidden", 5)
    except ValueError:
        results.append({"test": "output_escape_rejected", "passed": True})
    else:
        raise AssertionError("output escape accepted")
    save(folder / "summary.json", {"tests": results, "passed": len(results)}, new=True)
    print(json.dumps({"passed": len(results), "output": str(folder)}), flush=True)


if __name__ == "__main__":
    main()
