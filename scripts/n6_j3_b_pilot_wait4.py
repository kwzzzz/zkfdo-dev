#!/usr/bin/env python3
"""Run the two B main J pilot requests with direct wait4 measurements.

Reuse the J2 pilot machinery and its stop conditions. Only the B selection
rule, B library-path normalization, and mem20 completion gate differ.
"""

from __future__ import annotations

import json
from pathlib import Path

import n6_j2_pilot as pilot
from n6_j3_b_requests import available_libraries


ROOT = Path(__file__).resolve().parents[1]
MEM20_STATE = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json"


def select_requests(index: dict, base_index: dict) -> list[dict]:
    base_revisions = base_index.get("revisions", {})
    callable_rows = [row for row in index["requests"]
                     if row["scope"] == "main" and row["method"] == "S"
                     and row["preparation_failure"] is None
                     and base_revisions.get(row["revision_id"], {}).get("status") == "passed"]
    revisions = {row["revision_id"] for row in callable_rows}
    pilot.runner.require(bool(revisions), "no callable B main S revision")
    smallest = min(revisions, key=lambda identifier:
                   (base_revisions[identifier]["constraints"], identifier))
    largest = (min(revisions - {smallest}, key=lambda identifier:
                   (-base_revisions[identifier]["constraints"], identifier))
               if len(revisions) > 1 else smallest)
    if largest == smallest:
        same = sorted((row for row in callable_rows if row["revision_id"] == largest),
                      key=lambda row: row["queue_order"])
        pilot.runner.require(len(same) >= 2,
                             "one callable revision has fewer than two S requests")
        return same[:2]
    return [min((row for row in callable_rows if row["revision_id"] == identifier),
                key=lambda row: row["queue_order"])
            for identifier in (largest, smallest)]


def preflight_libraries(target: dict, snapshot_root: Path) -> list[str]:
    available, _missing = available_libraries(target, snapshot_root)
    return available


def direct_wait4() -> dict[str, object]:
    return {"measurement_method": "wait4", "exit_code": None,
            "max_rss_bytes": None, "time_probe_failure": None}


_run_pilot = pilot.run_pilot


def run_pilot(*args, **kwargs) -> dict:
    record = _run_pilot(*args, **kwargs)
    pilot.runner.require(len(record["selection"]) == 2,
                         "B pilot selection must have exactly two requests")
    record["selection"][0]["role"] = "largest_callable_revision"
    record["selection"][1]["role"] = "smallest_callable_revision"
    record["selection_rule"] = (
        "largest and smallest callable S revisions; first queue order per revision, "
        "or first two from the sole callable revision"
    )
    output = Path(record["output"])
    pilot.runner.atomic_json(output / "pilot.json", record)
    return record


def main() -> int:
    if not MEM20_STATE.is_file() or json.loads(MEM20_STATE.read_text()).get("status") != "completed":
        raise SystemExit("B mem20 state is not completed; B J pilot refused")
    pilot.select_requests = select_requests
    pilot.probe_time_l = direct_wait4
    pilot.runner.preflight_libraries = preflight_libraries
    pilot.run_pilot = run_pilot
    return pilot.main()


if __name__ == "__main__":
    raise SystemExit(main())
