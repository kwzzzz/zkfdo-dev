#!/usr/bin/env python3
"""Run only the fixed, disjoint last-30 E-02 preparation entries."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_e02_production_mains as e02  # noqa: E402


def main():
    rows, binary = e02.freeze()
    selection = e02.prepare_selection(rows)
    tail = selection[-30:]
    target = e02.RUN / "preparation-tail-selection.json"
    data = {"schema_version": 1, "fixed_at": e02.legacy.now(),
            "rule": "last 30 entries of the fixed preparation selection",
            "source_selection": e02.ref(e02.RUN / "preparation-selection.json"),
            "entries": [item["identifier"] for item in tail], "count": len(tail),
            "workers": 2, "zkfuzz_invocations": 0}
    if not target.exists():
        e02.legacy.write_new(target, data)
    elif e02.read(target) != {**data, "fixed_at": e02.read(target)["fixed_at"]}:
        raise RuntimeError("frozen preparation tail differs")
    # The forward workers need at least ~70 long-running entries before reaching
    # this tail; fail instead of removing any directory if the assignment overlaps.
    conflicts = [item["identifier"] for item in tail
                 if (e02.RUN / "preparation-measurements" / item["identifier"]).exists()]
    if conflicts:
        raise RuntimeError("tail assignment already started elsewhere: " + ",".join(conflicts))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(e02.prepare_one, item, binary): item for item in tail}
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
                print(json.dumps({"id": item["identifier"], "tail": True,
                                  "discovery": result["discovery"]["status"],
                                  "prepare300": result["prepare_300"]["status"],
                                  "prepare900": result["prepare_900"]["status"]}), flush=True)
            except Exception as error:
                print(json.dumps({"id": item["identifier"],
                                  "error": f"{type(error).__name__}: {error}"}), flush=True)


if __name__ == "__main__":
    main()
