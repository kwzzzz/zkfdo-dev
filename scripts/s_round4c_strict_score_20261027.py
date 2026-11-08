#!/usr/bin/env python3
"""v2.3 result adapter for the unchanged, fixed RQ-C strict scorer.

The adapter changes only the accepted result envelope and completed-request
denominator. Instance attribution, L1 logic and 18-item mapping are imported
from the original scorer. It never invokes J or a fuzzer.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import n6_light_rqc_20261026 as original

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/s-round4-2026-10-27/round4c-main"
V23_SHA = "05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700"
V23_SCHEMA = "zkfdo-lifting-result-v2.3"
CURRENT_PROTOCOL_SHA = "18bc531d0c863515a2fc7abc6411187161dd5b98c9fe5e481863ba075afb2ddd"
SCORE_KEYS = ("denominators", "request_statuses", "bug_totals", "bugs",
              "development_pair_observations", "completed_outside_mapping_or_main")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def validate_result(value: dict) -> dict:
    if value.get("schema") != V23_SCHEMA:
        return value
    for key in ("request_id", "request_sha256", "entrypoint", "preparation", "classes"):
        require(key in value, f"v2.3 result missing {key}")
    require(isinstance(value["classes"], list), "v2.3 classes must be a list")
    for item in value["classes"]:
        for key in ("representative", "verdict", "reason", "predicates"):
            require(key in item, f"v2.3 class missing {key}")
    return {**value, "schema": "zkfdo-lifting-result-v1"}


class CompatibleReader(original.Reader):
    def read(self, name, expected=None, parse=True):
        if expected == original.PROTOCOL_SHA:
            # The preserved N5 file differs from the SHA embedded in the old
            # scorer. Audit this exact known mismatch, without editing either.
            require(sha256(Path(name).read_bytes()).hexdigest() == CURRENT_PROTOCOL_SHA,
                    "N5 protocol differs from the documented current revision")
            expected = CURRENT_PROTOCOL_SHA
        value, source = super().read(name, expected, parse)
        return (validate_result(value) if parse and isinstance(value, dict) else value), source


@contextmanager
def scorer_context():
    reader, engines = original.Reader, dict(original.ENGINES)
    try:
        original.Reader = CompatibleReader
        original.ENGINES["v2.3"] = V23_SHA
        yield
    finally:
        original.Reader = reader
        original.ENGINES.clear()
        original.ENGINES.update(engines)


def score(args: SimpleNamespace, expected_completed: int | None = None) -> dict:
    require(args.layer == "strict", "only strict scoring is supported")
    official_index = ROOT / "runs/n6-j1-2026-10-09.noindex/request-index.json"
    official_state = ROOT / "runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json"
    if args.engine != "v1" or Path(args.index) != official_index or Path(args.state) != official_state:
        validate_strict_inputs(args)
    # The original scorer's only use of layer is a historical 765-result guard.
    # Its attribution and aggregation functions remain untouched.
    adapted = SimpleNamespace(**vars(args))
    adapted.layer = "exploratory"
    with scorer_context():
        result = original.score(adapted)
    completed = result["request_statuses"].get("completed", 0)
    require(expected_completed is not None and completed == expected_completed,
            "completed-result denominator differs from pinned input")
    result["layer"] = "strict"
    result["adapter"] = {"schema": "s-round4c-strict-adapter-v1",
                         "original_scorer_sha256": sha256((ROOT / "scripts/n6_light_rqc_20261026.py").read_bytes()).hexdigest(),
                         "current_protocol_sha256": CURRENT_PROTOCOL_SHA,
                         "original_scorer_protocol_sha256": original.PROTOCOL_SHA,
                         "v23_result_schema": V23_SCHEMA,
                         "expected_completed": expected_completed}
    return result


def validate_strict_inputs(args):
    """A new result envelope does not promote constructed inputs to strict."""
    index = json.loads(Path(args.index).read_text())
    official = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
    raw = official.read_bytes()
    require(sha256(raw).hexdigest() ==
            "18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508",
            "official strict base-input index changed")
    bases = json.loads(raw)["revisions"]
    for row in index["requests"]:
        base = bases.get(row["revision_id"], {})
        require(base.get("status") == "passed", "revision has no official strict base input")
        request_raw = Path(row["request"]).read_bytes()
        require(sha256(request_raw).hexdigest() == row["request_sha256"], "request SHA changed")
        request = json.loads(request_raw)
        path = Path(request["source_root"]) / request["base_input"]
        require(sha256(path.read_bytes()).hexdigest() == base["base_input_sha256"],
                "constructed or changed input cannot enter the strict layer")


def regression() -> dict:
    args = SimpleNamespace(
        protocol=ROOT / "docs/n5_evaluation_protocol_v1_2026-10-06.md",
        targets=ROOT / "docs/n6_targets_a_2026-10-07.json",
        mapping=ROOT / "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json",
        preparation=ROOT / "runs/n6-a1-2026-10-07/preparation-units.json",
        index=ROOT / "runs/n6-j1-2026-10-09.noindex/request-index.json",
        state=ROOT / "runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json",
        joins_source=None, engine="v1", layer="strict")
    actual = score(args, 765)
    archived_path = ROOT / "docs/n6_light_rqc_strict_2026-10-26.json"
    archived_raw = archived_path.read_bytes()
    require(sha256(archived_raw).hexdigest() ==
            "0e99572bd584ad24adcb19723afd8ed838e7f23052f635a332aeda96ac917bca",
            "archived official score SHA changed")
    archived = json.loads(archived_raw)
    differences = [key for key in SCORE_KEYS if actual[key] != archived[key]]
    return {"schema": "s-round4c-strict-regression-v1", "completed": 765,
            "source": str(archived_path), "source_sha256": sha256(archived_raw).hexdigest(),
            "same_score": not differences, "differing_fields": differences,
            "actual_score_sha256": sha256(json.dumps({key: actual[key] for key in SCORE_KEYS},
                                                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def save(path: Path, value: dict) -> None:
    path = path.absolute()
    require(path.is_relative_to(OUT) and path != OUT and not path.exists(), "new 4c output required")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regress-765", action="store_true")
    for name in ("protocol", "targets", "mapping", "preparation", "index", "state", "joins-source"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--engine", choices=("v1", "v2.2", "v2.3"))
    parser.add_argument("--layer", choices=("strict",), default="strict")
    parser.add_argument("--expected-completed", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.regress_765:
        result = regression()
        require(result["same_score"], "765-result score regression differs")
    else:
        require(all(getattr(args, name) is not None for name in
                    ("protocol", "targets", "mapping", "preparation", "index", "state", "engine",
                     "expected_completed")), "all pinned scorer inputs required")
        require(args.expected_completed >= 0, "invalid completed denominator")
        result = score(args, args.expected_completed)
    save(args.output, result)
    print(json.dumps({"output": str(args.output), "same_score": result.get("same_score"),
                      "completed": result.get("completed", result.get("request_statuses", {}).get("completed"))}))


if __name__ == "__main__":
    main()
