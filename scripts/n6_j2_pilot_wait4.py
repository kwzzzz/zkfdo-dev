#!/usr/bin/env python3
"""Run N6-J2 pilot v2 with direct wait4 rusage for every lift request."""

from __future__ import annotations

import n6_j2_pilot as pilot


def direct_wait4() -> dict[str, object]:
    return {"measurement_method": "wait4", "exit_code": None,
            "max_rss_bytes": None, "time_probe_failure": None}


pilot.probe_time_l = direct_wait4


if __name__ == "__main__":
    raise SystemExit(pilot.main())
