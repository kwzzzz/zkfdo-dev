#!/usr/bin/env python3
"""Development-mapping auxiliary analysis: where the J1 S-only L1 classes of the inference units sit.

Reads the official J1 index/state and result files only (no engine run). Maps each L1 class of the
S requests in inference-original and inference-r-intdiv to the two zkbugs items of the project:
Clamp (src/clampTensor.circom:38-67, comparator overflow) and Subtract
(src/subtractTensor.circom:3-10, unconstrained multiplier). Instance names come from the source:
calculatedScoreFraction.circom:16 `clamp = Clamp(b)`, responseTimeNormalized.circom:23/27
`subtract1/subtract2 = Subtract()`. Not part of the official RQ-C mapping.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "runs/n6-j1-2026-10-09.noindex/request-index.json"
STATE = ROOT / "runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json"
REVISIONS = ("inference-original", "inference-r-intdiv")


def label(kind: str, path: str) -> str:
    if kind == "TCCT" and re.search(r"\.subtract\d*$", path):
        return "Subtract item (TCCT at a Subtract instance)"
    if kind == "predicate" and ".clamp." in path:
        return "Clamp item (assumption predicate at the Clamp LessThan)"
    return "outside both items"


def main() -> int:
    index = {str(row["queue_order"]): row for row in json.loads(INDEX.read_text())["requests"]}
    state = json.loads(STATE.read_text())["requests"]
    per_seed: dict[str, set[str]] = defaultdict(set)
    classes: Counter = Counter()
    for key, entry in state.items():
        row = index[key]
        if entry.get("status") != "completed" or row["revision_id"] not in REVISIONS or row["method"] != "S":
            continue
        result = json.loads(Path(entry["result_path"]).read_text())
        for item in result["classes"]:
            found = []
            if item["verdict"] == "entrypoint_violation":
                found.append(("TCCT", item["representative"]))
            for predicate in item.get("predicates", []):
                if predicate.get("verdict") == "assumption_violation_reachable":
                    found.append(("predicate", predicate.get("instance") or ""))
            for kind, path in found:
                generic = re.sub(r"\[\d+\]", "[]", path)
                name = label(kind, path)
                classes[(row["revision_id"], kind, generic, name)] += 1
                per_seed[f"{row['revision_id']} seed {row['seed']}"].add(name)
    report = {"classes": [{"revision": r, "kind": k, "location": l, "item": n, "count": c}
                          for (r, k, l, n), c in sorted(classes.items())],
              "per_seed_items": {k: sorted(v) for k, v in sorted(per_seed.items())}}
    json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
