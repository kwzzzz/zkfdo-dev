#!/usr/bin/env python3
"""Count saved B exclusions; follow explicit state/gate references only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import shutil


def checked(path: Path, expected: str | None = None):
    if shutil.disk_usage(Path.cwd()).free < 15 * 1024**3:
        raise ValueError("internal disk below 15 GiB")
    data = path.read_bytes()
    digest = sha256(data).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f"SHA mismatch: {path}")
    return json.loads(data), {"path": str(path), "sha256": digest}


def summarize(gate_path: Path, states: dict[str, Path]):
    gate, gate_ref = checked(gate_path)
    if gate.get("status") != "passed":
        raise ValueError("saved gate did not pass")
    answer = {"schema": "n6-light-exclusions-v1", "gate": gate_ref, "engines": {}}
    for engine, state_path in states.items():
        state, state_ref = checked(state_path)
        effective, joined_paths, refs = {}, set(), []
        for artifact in gate["paired_joins"][engine]:
            join, ref = checked(Path(artifact["path"]), artifact["sha256"])
            if join.get("conflicts") != 0:
                raise ValueError("saved join conflict")
            refs.append(ref)
            joined_paths.update(str(state_path.parent / name) for name in join["results"])
            for row in join["classes"]:
                key = (row["request_id"], row["representative"])
                if key in effective:
                    raise ValueError("duplicate joined class")
                effective[key] = row["effective"]
        counts, verdicts = Counter(), Counter()
        by_revision = defaultdict(Counter)
        revision_statuses = defaultdict(Counter)
        classes, results = [], []
        statuses = Counter(row["status"] for row in state["requests"].values())
        for row in sorted(state["requests"].values(), key=lambda r: r["queue_order"]):
            revision_statuses[row["revision_id"]][row["status"]] += 1
            by_revision[row["revision_id"]]
            if row["status"] != "completed":
                continue
            result, ref = checked(Path(row["result_path"]), row["result_sha256"])
            if result["request_sha256"] != row["request_sha256"]:
                raise ValueError("request binding mismatch")
            if str(Path(row["result_path"]).resolve()) not in {
                str(Path(name).resolve()) for name in joined_paths
            }:
                raise ValueError("completed result outside passed paired gate")
            results.append(ref)
            for i, item in enumerate(result["classes"]):
                verdicts[item["verdict"]] += 1
                shared = effective.get((result["request_id"], item["representative"]))
                if shared == "assumption_excluded_in_context":
                    raise ValueError("predicate exclusion needs a separate proof classifier")
                if item["verdict"] != "excluded_in_context":
                    continue
                evidence = item.get("evidence", {})
                category = " | ".join((item["reason"], evidence.get("exclusion_basis", "unspecified"),
                                       evidence.get("exclusion_method", "unspecified")))
                counts[category] += 1
                by_revision[row["revision_id"]][category] += 1
                classes.append({"request_id": result["request_id"], "revision_id": row["revision_id"],
                                "class_index_zero_based": i, "proof_type": category,
                                "result_path": ref["path"], "result_sha256": ref["sha256"]})
        expected = {"v2.2": 350, "v1": 349}[engine]
        if len(classes) != expected:
            raise ValueError(f"exclusion total mismatch: {engine} {len(classes)} != {expected}")
        local = sum(n for name, n in counts.items() if name.startswith("local_constraint_refutation |"))
        answer["engines"][engine] = {
            "state": state_ref, "status_counts": dict(statuses), "joins": refs,
            "results": results, "class_verdicts": dict(verdicts),
            "excluded_total": len(classes), "expected_total": expected,
            "proof_counts": dict(sorted(counts.items())),
            "by_revision": {rev: dict(sorted(c.items())) for rev, c in sorted(by_revision.items())},
            "revision_status_counts": {rev: dict(c) for rev, c in sorted(revision_statuses.items())},
            "local_count": local, "local_fraction": f"{local}/{len(classes)}",
            "local_percent": 100 * local / len(classes), "excluded_classes": classes}
    return answer


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gate", type=Path, required=True)
    p.add_argument("--v22-state", type=Path, required=True)
    p.add_argument("--v1-state", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error("output already exists; choose a new version")
    result = summarize(args.gate, {"v2.2": args.v22_state, "v1": args.v1_state})
    data = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if len(data.encode()) > 2_000_000:
        p.error("output exceeds 2 MB")
    args.output.write_text(data)
    print(json.dumps({engine: {k: v[k] for k in ("excluded_total", "local_count", "local_percent")}
                      for engine, v in result["engines"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
