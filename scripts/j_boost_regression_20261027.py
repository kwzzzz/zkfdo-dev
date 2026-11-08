#!/usr/bin/env python3
"""Adapt the unchanged 4d 24-assertion harness into the J boost output root."""
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/j-boost-2026-10-27'
OLD=ROOT/'scripts/s_round4d_j_tests_20261027.py'
ENGINE=RUN/'cargo-target/debug/zkfdo-j-v23'

def prepare():
    destination=RUN/'harness-driver.py'
    raw=OLD.read_text()
    raw=raw.replace('ROOT = Path(__file__).resolve().parents[1]', 'ROOT = Path('+repr(str(ROOT))+')')
    raw=raw.replace('runs/s-round4-2026-10-27/round4d','runs/j-boost-2026-10-27')
    raw=raw.replace('runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development','runs/j-boost-2026-10-27/cargo-target/debug/zkfdo-j-v23')
    raw=raw.replace('runs/s-round4-2026-10-27/cargo-target','runs/j-boost-2026-10-27/cargo-target')
    raw=raw.replace('05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700',hashlib.sha256(ENGINE.read_bytes()).hexdigest())
    with destination.open('x') as f:f.write(raw)
    destination.chmod(0o755)
    probe=RUN/'fixture-probe-v1/summary.json';probe.parent.mkdir()
    original=ROOT/'runs/s-round4-2026-10-27/round4d/fixture-probe-v1/summary.json'
    data=json.loads(original.read_text())
    assert data['all_at_most_1000']
    # Verify the fixture source hashes still match the old <=1000 measurements.
    for row in data['rows']:
        assert hashlib.sha256(Path(row['fixture']).read_bytes()).hexdigest()==row['source_sha256']
    probe.write_bytes(original.read_bytes())
    (RUN/'harness-adaptation.json').write_text(json.dumps({'source':str(OLD),'source_sha256':hashlib.sha256(OLD.read_bytes()).hexdigest(),'driver_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'fixture_probe_sha256':hashlib.sha256(original.read_bytes()).hexdigest()},indent=2)+'\n')
    os.execv(sys.executable,[sys.executable,'-B',str(destination),'prepare','--output',str(RUN/'j-tests-v1')])

if __name__=='__main__':prepare()
