#!/usr/bin/env python3
"""Measure the synthetic J fixture circuits before permitting the 24 J tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "runs/s-round4-2026-10-27"
COMPILER = ROOT / "runs/c02-corpus-2026-10-02/tools/circom"
COMPILER_SHA = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def constraints(path: Path) -> int:
    with path.open("rb") as stream:
        if stream.read(4) != b"r1cs":
            raise ValueError("invalid R1CS magic")
        version, sections = struct.unpack("<II", stream.read(8))
        if version != 1:
            raise ValueError("unexpected R1CS version")
        for _ in range(sections):
            kind, length = struct.unpack("<IQ", stream.read(12))
            start = stream.tell()
            if kind == 1:
                if struct.unpack("<I", stream.read(4))[0] != 32:
                    raise ValueError("unexpected prime width")
                stream.read(32 + 16 + 8)
                return struct.unpack("<I", stream.read(4))[0]
            stream.seek(start + length)
    raise ValueError("missing R1CS header")


def main() -> None:
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise ValueError("nice 19 required")
    if sha(COMPILER) != COMPILER_SHA:
        raise ValueError("compiler SHA differs")
    output = Path(sys.argv[1]).absolute()
    if not output.is_relative_to(ROUND / "round4d") or output.exists():
        raise ValueError("new Round4d output required")
    output.mkdir(parents=True)
    fixtures = sorted({*ROOT.glob("tests/fixtures/lifting/*/src/entrypoint.circom"),
                       *ROOT.glob("tests/fixtures/lifting_engine/*/src/entrypoint.circom")})
    if not fixtures:
        raise ValueError("no test circuits found")
    rows = []
    for index, source in enumerate(fixtures):
        folder = output / f"fixture-{index:03d}"
        folder.mkdir()
        argv = [str(COMPILER), str(source), "--r1cs", "--prime", "bn128", "--output", str(folder)]
        with (folder / "stdout.log").open("xb") as stdout, (folder / "stderr.log").open("xb") as stderr:
            result = subprocess.run(argv, cwd=ROOT, stdout=stdout, stderr=stderr,
                                    timeout=60, check=False)
        r1cs = folder / "entrypoint.r1cs"
        count = constraints(r1cs) if result.returncode == 0 and r1cs.is_file() else None
        rows.append({"fixture": str(source), "source_sha256": sha(source), "argv": argv,
                     "returncode": result.returncode, "constraints": count,
                     "stdout_sha256": sha(folder / "stdout.log"),
                     "stderr_sha256": sha(folder / "stderr.log")})
        if r1cs.exists():
            r1cs.unlink()
    summary = {"schema": "s-round4d-fixture-constraints-v1", "compiler_sha256": COMPILER_SHA,
               "all_at_most_1000": all(isinstance(row["constraints"], int) and
                                       row["constraints"] <= 1000 for row in rows),
               "rows": rows}
    with (output / "summary.json").open("x") as stream:
        json.dump(summary, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"count": len(rows), "max_constraints": max(
        (r["constraints"] or 0 for r in rows), default=0),
        "all_at_most_1000": summary["all_at_most_1000"]}))


if __name__ == "__main__":
    main()
