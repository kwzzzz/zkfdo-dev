#!/usr/bin/env python3
"""Check/replay one preserved SMT cone without a J engine or value output."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RESULT = "runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/main/0004/requests/000025/attempt-0001/result.json"
RESULT_SHA = "42bbdd1156a7f13d137915b63a63dc141d7cfb982dfb8f4c80e16465a871b075"


def guard():
    if os.getpriority(os.PRIO_PROCESS, 0) < 19 or shutil.disk_usage(ROOT).free < 15*1024**3:
        raise ValueError("nice 19 and 15 GiB free required")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--result", type=Path, default=ROOT / RESULT)
    p.add_argument("--review-doc", type=Path, default=ROOT / "docs/n6_b6h_review_v22_only_exclusion_2026-10-25.md")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    guard()
    output = args.output.resolve()
    if any(part.startswith("n6-b6") or part == "aq-exec" for part in output.parts):
        raise ValueError("output must remain outside B and aq-exec")
    raw = args.result.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RESULT_SHA:
        raise ValueError("designated request result SHA differs")
    result = json.loads(raw)
    item = result["classes"][6]
    if item["synthesis"]["b_cone_constraints"] != 62 or len(item["evidence"]["exclusion_fixed_wires"].split(",")) != 4:
        raise ValueError("designated cone metadata differs")
    queries = {call["query"] for call in result["costs"]["solver_calls"]
               if "/site-006/synthesis/cone" in call.get("query", "")}
    if len(queries) != 1:
        raise ValueError("ambiguous preserved cone path")
    query = Path(next(iter(queries)))
    cone = query.with_suffix(".smt2")
    available = importlib.util.find_spec("z3") is not None
    doc = args.review_doc.read_bytes()
    status, answer, seconds = "미실행(z3 없음)", None, None
    if available and not cone.is_file():
        status = "미실행(원뿔 파일 없음)"
    elif available:
        guard()
        if cone.stat().st_size > 4*1024**2:
            raise ValueError("preserved cone exceeds bounded input size")
        import z3
        z3.set_param("parallel.enable", False)
        solver = z3.Solver()
        solver.set(threads=1, timeout=1_800_000)
        solver.add(z3.parse_smt2_file(str(cone)))
        started = time.monotonic()
        answer = str(solver.check())
        seconds = time.monotonic() - started
        guard()
        status = "실행 완료"
    receipt = {"status": status, "solver_result": answer, "solver_seconds": seconds,
        "python": sys.executable, "z3_available": available, "threads": 1, "timeout_seconds": 1800,
        "source_result": {"path": str(args.result.resolve()), "sha256": RESULT_SHA},
        "review_doc": {"path": str(args.review_doc.resolve()), "sha256": hashlib.sha256(doc).hexdigest()},
        "class_index": 6, "cone_constraints": 62, "fixed_wire_count": 4,
        "query_prefix": str(query), "query_parent_exists": query.parent.is_dir(),
        "cone_path": str(cone), "cone_exists": cone.is_file(),
        "cone_sha256": hashlib.sha256(cone.read_bytes()).hexdigest() if cone.is_file() else None,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "judging_executed": False, "values_printed": False}
    guard()
    data = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode()
    if len(data) > 100_000:
        raise ValueError("output too large")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print(json.dumps({"status": status, "solver_result": answer, "solver_seconds": seconds,
                      "cone_exists": receipt["cone_exists"], "output": str(output),
                      "sha256": hashlib.sha256(data).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
