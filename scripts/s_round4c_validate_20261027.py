#!/usr/bin/env python3
"""Round 4c development checks; all 24 judging tests are excluded from execution."""
import argparse
import json
from pathlib import Path
import sys
import s_round4c_monitor_20261027 as monitor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-prefix", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    reference = monitor.ROOT / "runs/s-inspection-improve-2026-10-27/cargo-command-reference.json"
    names = json.loads(reference.read_text())["skipped_J_tests"]
    if len(names) != 24 or len(set(names)) != 24:
        raise ValueError("J exclusion inventory differs")
    test = ["cargo", "test", "--offline", "--locked", "-j", "1", "--", "--test-threads=1"]
    for name in names:
        test += ["--skip", name]
    checks = [("python", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "scripts", "-p", "s_round4c*test_20261027.py"], False),
              ("fmt", ["cargo", "fmt", "--all", "--", "--check"], False),
              ("clippy", ["cargo", "clippy", "--offline", "--locked", "-j", "1", "--all-targets", "--all-features", "--", "-D", "warnings"], True),
              ("test", test, True)]
    rows = []
    for label, command, cargo in checks:
        row = monitor.run(command, args.label_prefix + "-" + label, 900, cargo)
        rows.append(row)
        if row["status"] != "completed":
            break
    passed = len(rows) == len(checks) and all(r["status"] == "completed" for r in rows)
    print(json.dumps(monitor.write_new(Path(args.output), {"passed": passed, "checks": rows,
                                                           "excluded_J_tests": names})))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
