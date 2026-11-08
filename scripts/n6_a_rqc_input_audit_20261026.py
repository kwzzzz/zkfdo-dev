#!/usr/bin/env python3
"""Read-only current-state RQ-C dry run; no runner imports or score printing."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import n6_light_rqc_20261026 as scorer

ROOT = Path(__file__).resolve().parents[1]
AQ = ROOT / "runs/n6-a-remeasure-2026-10-25.noindex/aq-exec"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def guard():
    require(os.getpriority(os.PRIO_PROCESS, 0) >= 19, "nice 19 required")
    require(shutil.disk_usage(ROOT).free >= 15 * 1024**3, "disk below 15 GiB")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def select_state(directory):
    choices = [directory / name for name in ("state.json", "state-v2.json", "state-v3.json", "state-v3_1.json", "state-v3_2.json")]
    available = [path for path in choices if path.is_file() and not path.is_symlink()]
    require(bool(available), "no known state file")
    return max(available, key=lambda p: (p.stat().st_mtime_ns, choices.index(p)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", default="auto")
    p.add_argument("--engine", choices=("v1", "v2.2"), default="v2.2")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--joined-only", action="store_true", help="hold unfinished joins; never fabricate a join")
    args = p.parse_args()
    guard()
    out = args.out_dir.resolve()
    require(not out.is_relative_to(AQ) and not any(x.startswith("n6-b6") for x in out.parts), "unsafe output")
    require(not out.exists(), "choose a new output directory")
    out.mkdir(parents=True)
    sources = []
    def read(path, expected=None):
        guard()
        path = Path(path).resolve()
        require(path.is_relative_to(ROOT), "input outside repository")
        require(not any(x.startswith(("n6-b6", "h1-")) for x in path.parts), "unrelated B/H1 input")
        require(path.stat().st_size < 32*1024**2, "oversized metadata")
        data = path.read_bytes()
        require(expected is None or sha(data) == expected, "source SHA mismatch: " + str(path))
        receipt = {"path": str(path), "sha256": sha(data)}
        if receipt not in sources:
            sources.append(receipt)
        return json.loads(data)
    def write(name, value):
        guard()
        data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        require(len(data) <= 2_000_000, "output too large")
        path = out / name
        with path.open("xb") as stream:
            stream.write(data)
        return path, sha(data)
    state_path = select_state(AQ) if args.state == "auto" else Path(args.state).resolve()
    require(state_path in {AQ / x for x in ("state.json", "state-v2.json", "state-v3.json", "state-v3_1.json", "state-v3_2.json")}, "unexpected state path")
    raw = read(state_path)
    require(raw.get("schema") in {"n6-a-remeasure-aq-execute-v1", "n6-a-remeasure-aq-execute-v2", "n6-a-remeasure-aq-execute-v3"}, "unknown state schema")
    compatible = copy.deepcopy(raw)
    compatible["schema"] = "n6-a-remeasure-aq-execute-v1"
    state = scorer.normalize_state(compatible, args.engine)
    joined_paths = set()
    for number, rev in enumerate(state["revisions"].values()):
        if not rev.get("instances_path"):
            continue
        join = read(rev["instances_path"], rev["instances_sha256"])
        join["results"] = [str((state_path.parent / x).resolve()) for x in join["results"]]
        joined_paths.update(join["results"])
        path, digest = write(f"join-{number:04d}.json", join)
        rev.update(instances_path=str(path), instances_sha256=digest)
    for event in state["requests"].values():
        if event["status"] == "completed":
            require(Path(event["result_path"]).is_absolute(), "completed result_path must be absolute")
    completed = sum(x["status"] == "completed" for x in state["requests"].values())
    held = 0
    if args.joined_only:
        for event in state["requests"].values():
            if event["status"] == "completed" and str(Path(event["result_path"]).resolve()) not in joined_paths:
                event["status"] = "audit_pending_join"
                held += 1
    snapshot, _ = write("normalized-state.json", state)
    score_args = argparse.Namespace(protocol=ROOT / "docs/n5_evaluation_protocol_v1_2026-10-06.md",
        targets=ROOT / "docs/n6_targets_a_2026-10-07.json",
        mapping=ROOT / "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json",
        preparation=ROOT / "runs/n6-a1-2026-10-07/preparation-units.json",
        index=ROOT / f"runs/n6-a-remeasure-2026-10-25.noindex/prepared-aq/request-index-{args.engine}.json",
        state=snapshot, engine=args.engine, layer="exploratory", joins_source=None,
        output=out / "score.json")
    read_receipts = []
    original_reader = scorer.Reader
    class AuditReader(original_reader):
        def read(self, name, expected=None, parse=True):
            guard()
            path = Path(name).resolve()
            require(path.is_relative_to(ROOT) or path.is_relative_to(out), "unexpected scorer input")
            require(not any(x.startswith(("n6-b6", "h1-")) for x in path.parts), "unrelated scorer input")
            require(path.stat().st_size < 32*1024**2, "oversized scorer metadata")
            data = path.read_bytes()
            digest = sha(data)
            receipt = {"path": str(path), "sha256": digest}
            if receipt not in read_receipts:
                read_receipts.append(receipt)
            require(expected is None or digest == expected, "SHA mismatch: " + str(path))
            key = (str(path), digest)
            if key not in self.ids:
                self.ids[key] = len(self.sources)
                self.sources.append(receipt)
            return (json.loads(data) if parse else data), self.ids[key]
    scorer.Reader = AuditReader
    started = time.monotonic()
    status, error, reflected = "success", None, 0
    try:
        result = scorer.score(score_args)
        reflected = result["request_statuses"].get("completed", 0)
        write("score.json", result)
    except (OSError, ValueError, KeyError, TypeError) as failure:
        status, error = "failed", str(failure)
    finally:
        scorer.Reader = original_reader
    command = [sys.executable, "-B", str(Path(scorer.__file__).resolve())]
    for key in ("protocol", "targets", "mapping", "preparation", "index", "state", "engine", "layer", "output"):
        command.extend(["--" + key, str(getattr(score_args, key))])
    receipt = {"status": status, "reason": error, "source_state": sources[0], "state_schema": raw["schema"],
        "engine": args.engine, "source_completed_requests": completed, "held_requests": held,
        "reflected_completed_requests": reflected, "score_produced": status == "success",
        "result_files_read": sum(Path(x["path"]).name.endswith("result.json") for x in read_receipts),
        "seconds": time.monotonic()-started, "sources": sources + read_receipts,
        "equivalent_scorer_command": command, "joined_only": args.joined_only,
        "script_sha256": sha(Path(__file__).read_bytes()), "protocol_pin": scorer.PROTOCOL_SHA,
        "judging_executed": False}
    path, digest = write("audit-receipt.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key not in {"sources", "equivalent_scorer_command"}}, ensure_ascii=False))
    print("audit_receipt", path, digest)
    return 0 if status == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
