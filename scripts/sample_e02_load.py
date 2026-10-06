#!/usr/bin/env python3
"""Sample host load averages during the already running E-02 measurements."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/e02-production-mains-2026-10-05"


def main():
    path = RUN / "host-load-samples-2026-10-06.jsonl"
    selection = json.loads((RUN / "preparation-selection.json").read_text())["entries"]
    ids = [row["identifier"] for row in selection]
    with path.open("x") as stream:
        while True:
            completed = sum((RUN / "preparation-measurements" / key / "result.json").is_file() for key in ids)
            record = {
                "sampled_at": datetime.now(timezone.utc).isoformat(),
                "monotonic_seconds": time.monotonic(),
                "load_average_1_5_15_minutes": list(os.getloadavg()),
                "logical_cpus": os.cpu_count(),
                "preparation_results_present": completed,
                "measurement_denominator": len(ids),
                "scope": "whole host runnable/uninterruptible load; not per-entrypoint CPU usage",
            }
            stream.write(json.dumps(record) + "\n")
            stream.flush()
            if completed == len(ids):
                break
            time.sleep(10)


if __name__ == "__main__":
    main()
