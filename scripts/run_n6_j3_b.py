#!/usr/bin/env python3
"""Run the J1 engine on B's pinned split snapshots.

The B specs include workspace-derived -l directories absent from some pinned
split trees. Their absolute original-source -l counterparts exist. This
versioned adapter skips only the absent workspace-derived paths while retaining
the exact order of the remaining paths; it does not change source files or
specs. B J execution is left to the lead after mem20 B has completed.
"""

from __future__ import annotations

import json
from pathlib import Path

import run_n6_j1
from n6_j3_b_requests import available_libraries


ROOT = Path(__file__).resolve().parents[1]
MEM20_STATE = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json"


def preflight_libraries(target: dict, snapshot_root: Path) -> list[str]:
    available, _missing = available_libraries(target, snapshot_root)
    return available


def main() -> int:
    run_n6_j1.preflight_libraries = preflight_libraries
    # An input-only validation is permitted before J execution, once B mem20
    # is complete. The same guard also prevents an accidental early execute.
    if not MEM20_STATE.is_file() or json.loads(MEM20_STATE.read_text()).get("status") != "completed":
        raise SystemExit("B mem20 state is not completed; B J refused")
    return run_n6_j1.main()


if __name__ == "__main__":
    raise SystemExit(main())
