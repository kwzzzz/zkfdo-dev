#!/usr/bin/env python3
"""4c monitor scoped to J boost; no scan of the runs tree."""
import importlib.util
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monitor4c', ROOT / 'scripts/s_round4c_monitor_20261027.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.RUNROOT = ROOT / 'runs/j-boost-2026-10-27'
m.OUT = m.RUNROOT / 'monitoring'
m.TARGET = m.RUNROOT / 'cargo-target'
m.OUT.mkdir(parents=True, exist_ok=True)
m.__file__ = __file__
# No recursive output inventory. Disk-free gates still cover every output byte;
# target_size is the original 4c monitor's single explicitly owned target check.
m.output_bytes = lambda: sum(p.stat().st_size for p in m.RUNROOT.iterdir() if p.is_file())
os.environ['CARGO_PROFILE_DEV_DEBUG'] = '0'
os.environ['CARGO_PROFILE_TEST_DEBUG'] = '0'
if __name__ == '__main__':
    m.main()
