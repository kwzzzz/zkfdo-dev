#!/usr/bin/env python3
"""Read-only preflight; never starts judging, fuzzing, compilation, or cleanup.

Supply measured peak and ALL retained reserves explicitly. Unknown inputs block
readiness. This script does not read the active aq directory or cache contents.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEADLINE = datetime(2026, 10, 28, 15, tzinfo=timezone.utc)
GIB = 2**30


def required_bytes(peak, retained):
    if type(peak) is not int or type(retained) is not int or peak < 0 or retained < 0:
        raise ValueError("nonnegative measured byte counts required")
    return (6 * max(peak, 60 * GIB) + 4) // 5 + retained


def checked_engine(path):
    p = Path(path).resolve()
    allowed = p.is_relative_to(ROOT) or p.is_relative_to((ROOT / "target").resolve())
    if not allowed or any(x.startswith(("n6-a-remeasure-2026-10-25", "n6-b6", "h1-")) for x in p.parts):
        raise ValueError("engine must be an explicit unprotected repository file")
    return p


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def command(argv):
    p = subprocess.run(argv, capture_output=True, text=True, check=False)
    return {"argv": argv, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def disk(path):
    result = command(["/bin/df", "-k", path])
    if result["returncode"] == 0:
        result["available_bytes"] = int(result["stdout"].splitlines()[-1].split()[3]) * 1024
    return result


def heavy_processes(text):
    # No signals; report only PID and matched program class, not arbitrary arguments.
    matches = []
    patterns = [r"\bcargo\b", r"\bcircom\b", r"\bzkfDO(?:-v[\d.]+)?\b", r"\bzkfuzz\b",
                r"\bz3\b", r"n6_a_remeasure_aq_execute", r"run_policy_[ab]_", r"s_round4_monitor"]
    for line in text.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) < 3 or not fields[0].isdigit() or not fields[1].isdigit():
            continue
        pid, parent, text = int(fields[0]), int(fields[1]), fields[2]
        if pid == os.getpid():
            continue
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                matches.append({"pid": pid, "parent_pid": parent, "program_class": match.group(0)})
                break
    return matches


def inspect(args):
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise ValueError("nice 19 required")
    now = datetime.now(timezone.utc)
    blockers = []
    if now < DEADLINE:
        blockers.append("judging freeze deadline not reached")
    internal = disk("/")
    cache = disk("/Volumes/zkfdo-jcache")
    external = disk(str(ROOT / "target"))
    mounted = os.path.ismount("/Volumes/zkfdo-jcache")
    if not mounted:
        blockers.append("judging image is not mounted")
    if internal.get("available_bytes", 0) < 20 * GIB:
        blockers.append("internal free below task gate 20 GiB (executor floor 15 GiB)")
    required = None
    if args.peak_bytes is None or args.retained_bytes is None:
        blockers.append("measured peak/all retained reserves missing; do not assume zero")
    else:
        required = required_bytes(args.peak_bytes, args.retained_bytes)
        if cache.get("available_bytes", 0) < max(required, 582 * GIB):
            blockers.append("cache below 1.2 x peak + retained or conservative 582 GiB floor")
    process = command(["/bin/ps", "-axo", "pid=,ppid=,args="])
    heavy = heavy_processes(process["stdout"])
    if process["returncode"] or heavy:
        blockers.append("competing heavy process found or process inventory unavailable")
    sizes = command(["/usr/bin/du", "-sk", str(ROOT / "target") + "/"])
    if sizes["returncode"]:
        blockers.append("existing target allocation cannot be measured")
    engines = []
    if not args.engine:
        blockers.append("no explicitly pinned engine")
    for name, expected in args.engine:
        row = {"path": name, "expected_sha256": expected}
        try:
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError("invalid engine SHA-256")
            row["actual_sha256"] = digest(checked_engine(name))
            row["match"] = row["actual_sha256"] == expected
        except (OSError, ValueError) as error:
            row.update(match=False, error=str(error))
        if not row["match"]:
            blockers.append("engine hash unavailable or mismatched")
        engines.append(row)
    return {"utc": now.isoformat(), "read_only": True, "ready": not blockers, "blockers": blockers,
            "required_cache_bytes": required, "image_mounted": mounted, "internal": internal,
            "cache_df_only": cache, "target_filesystem": external, "target_du": sizes,
            "heavy_processes": heavy, "process_inventory_returncode": process["returncode"], "engines": engines}


class Checks(unittest.TestCase):
    def test_gate_rounds_up_and_reserves(self):
        self.assertEqual(required_bytes(100 * GIB, 7), 120 * GIB + 7)
        self.assertEqual(required_bytes(100 * GIB + 1, 7), 120 * GIB + 9)

    def test_initial_peak_floor(self):
        self.assertEqual(required_bytes(0, 0), 72 * GIB)

    def test_unknown_or_negative_refused(self):
        for peak in (-1, None, 0.5):
            with self.assertRaises(ValueError):
                required_bytes(peak, 0)

    def test_process_detection(self):
        rows = heavy_processes("999999 2 circom file.circom\n999998 2 python n6_a_remeasure_aq_execute_v3_1.py\n999997 2 text-editor")
        self.assertEqual([r["pid"] for r in rows], [999999, 999998])

    def test_protected_engine_refused(self):
        with self.assertRaises(ValueError):
            checked_engine(ROOT / "runs/n6-a-remeasure-2026-10-25.noindex/fake")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--peak-bytes", type=int)
    p.add_argument("--retained-bytes", type=int)
    p.add_argument("--engine", nargs=2, action="append", metavar=("PATH", "SHA256"))
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        return 0 if result.wasSuccessful() else 1
    result = inspect(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
