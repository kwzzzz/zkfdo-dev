#!/usr/bin/env python3
"""Use the unchanged 4c internal-only monitor with new 4d receipt paths."""
from __future__ import annotations

from pathlib import Path

import s_round4c_monitor_20261027 as monitor

monitor.OUT = monitor.RUNROOT / "round4d/monitoring"
monitor.OUT.mkdir(parents=True, exist_ok=True)
monitor.__file__ = str(Path(__file__).resolve())


if __name__ == "__main__":
    monitor.main()
