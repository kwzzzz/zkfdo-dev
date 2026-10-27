#!/usr/bin/env python3
"""Collect recorded A whole-circuit sizes through explicit metadata references.

No discovery, directory enumeration, circuit execution, R1CS body reads, or
direct filesystem reads occur here. The caller supplies a reader implementing
json(path, expected=None), text(path, expected=None), and abspath(path), and is
responsible for its nice-19, disk-space and allowed-path checks.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_COUNT = re.compile(r"^\s*(non-linear constraints|linear constraints|wires):\s*(\d+)\s*$", re.M)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def parse_counts(text: str) -> dict[str, int]:
    matches = _COUNT.findall(_ANSI.sub("", text))
    _require(len(matches) == 3 and len({name for name, _ in matches}) == 3,
             "compiler stdout must contain exactly one nonlinear, linear and wires count")
    values = {name: int(value) for name, value in matches}
    return {"nonlinear": values["non-linear constraints"], "linear": values["linear constraints"],
            "constraints": values["non-linear constraints"] + values["linear constraints"],
            "wires": values["wires"]}


def _path(reader: Any, value: str | Path) -> Path:
    return Path(reader.abspath(value))


def _queue_sizes(queue_path: str | Path, proof_path: str | Path | None, reader: Any,
                 method: str) -> dict[str, dict[str, Any]]:
    queue_path = _path(reader, queue_path)
    queue = reader.json(queue_path)
    _require(queue.get("branch") == "A" and queue.get("schema_version") == 4,
             "expected an A schema-4 queue")
    binding = queue.get("preflight_reuse")
    _require(isinstance(binding, dict) and isinstance(binding.get("sha256"), str),
             "queue has no pinned preflight proof")
    pinned_proof = _path(reader, binding["path"])
    _require(proof_path is None or _path(reader, proof_path) == pinned_proof,
             "preflight proof path differs from queue binding")
    proof = reader.json(pinned_proof, binding["sha256"])
    _require(proof.get("schema_version") == 1 and proof.get("status") == "passed" and
             isinstance(proof.get("rows"), dict), "invalid preflight proof")
    units = queue.get("units")
    _require(isinstance(units, list) and bool(units) and queue.get("unit_count") == len(units),
             "queue unit denominator differs")
    result: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, int]] = set()
    log_cache: dict[Path, dict[str, int]] = {}
    for unit in units:
        revision, seed = unit.get("identifier"), unit.get("seed")
        _require(isinstance(revision, str) and bool(revision) and type(seed) is int,
                 "missing revision/seed identity")
        _require((revision, seed) not in seen, "duplicated revision/seed")
        seen.add((revision, seed))
        row = proof["rows"].get(unit["unit_id"] + ":W")
        _require(isinstance(row, dict) and row.get("status") == "passed",
                 f"missing or failed W preflight proof: {unit['unit_id']}")
        spec_path = _path(reader, unit["whole_spec"])
        _require(_path(reader, row["destination_spec"]) == spec_path and
                 row["destination_spec_sha256"] == unit["whole_spec_sha256"],
                 "W spec/proof binding differs")
        spec = reader.json(spec_path, unit["whole_spec_sha256"])
        _require(spec.get("schema_version") == 1 and isinstance(spec.get("targets"), list)
                 and len(spec["targets"]) == 1, "W spec must contain one schema-1 target")
        ledger_path = _path(reader, row["destination_preflight"])
        ledger = reader.json(ledger_path, row["destination_preflight_sha256"])
        _require(ledger.get("schema_version") == 1 and ledger.get("kind") == "policy_a_preflight"
                 and ledger.get("status") == "passed", "W preflight did not pass")
        _require(_path(reader, ledger["spec_path"]) == spec_path and
                 ledger.get("spec_sha256") == unit["whole_spec_sha256"],
                 "W preflight/spec hash binding differs")
        compiles = ledger.get("compile")
        _require(isinstance(compiles, list) and len(compiles) == 1,
                 "W preflight must record exactly one compile target")
        compile_record = compiles[0]
        _require(compile_record.get("status") == "succeeded" and compile_record.get("exit_code") == 0
                 and compile_record.get("target_id") == spec["targets"][0].get("target_id"),
                 "W compile failed or target identity differs")
        stdout = compile_record.get("stdout_path")
        _require(isinstance(stdout, str) and bool(stdout), "W compile stdout path is missing")
        log_path = _path(reader, ledger_path.parent / stdout)
        if log_path not in log_cache:
            log_cache[log_path] = parse_counts(reader.text(log_path))
        counts = log_cache[log_path]
        source_paths = [str(path) for path in
                        (queue_path, pinned_proof, spec_path, ledger_path, log_path)]
        if revision not in result:
            result[revision] = {**counts, "source_paths": [], "method": method,
                                "seeds": [], "seed_records": [],
                                "schemas": {"queue": 4, "preflight_proof": 1,
                                            "whole_spec": 1, "preflight": 1, "stdout": "compiler_text"}}
        record = result[revision]
        _require(all(record[name] == value for name, value in counts.items()),
                 f"W circuit counts differ across seeds: {revision}")
        record["source_paths"].extend(source_paths)
        record["seeds"].append(seed)
        record["seed_records"].append({"seed": seed, "unit_id": unit["unit_id"],
            "spec_path": str(spec_path), "spec_sha256": unit["whole_spec_sha256"],
            "preflight_path": str(ledger_path), "preflight_sha256": row["destination_preflight_sha256"],
            "stdout_path": str(log_path), "entrypoint_relative": spec["targets"][0].get("entrypoint_relative"),
            "compile_reused": bool(compile_record.get("reuse_claim"))})
    expected_seeds = {seed for _, seed in seen}
    for revision, record in result.items():
        _require(set(record["seeds"]) == expected_seeds,
                 f"revision does not contain every queue seed: {revision}")
        record["source_paths"] = sorted(set(record["source_paths"]))
        record["seeds"].sort()
    return result


def collect_sizes(main_queue_path: str | Path, reuse_path: str | Path, reader: Any,
                  pragma_queue_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Read every pinned main W seed record, optionally overlay selected pragma W.

    With the official inputs this verifies 81 original W preflights and, when
    pragma_queue_path is supplied, six selected A3 W preflights for aq-035/036.
    The selected compiled counts take precedence. Equality of counts is reported
    separately and is never presented as equality of compiled artifacts.
    """
    result = _queue_sizes(main_queue_path, reuse_path, reader,
                          "official_main_W_preflight_stdout")
    if pragma_queue_path is not None:
        selected = _queue_sizes(pragma_queue_path, None, reader,
                                "selected_pragma_W_preflight_stdout")
        for revision, record in selected.items():
            _require(revision in result, f"selected pragma revision absent from main queue: {revision}")
            previous = result[revision]
            _require(record["seeds"] == previous["seeds"], "selected pragma seed set differs")
            record["original_main_W_counts"] = {name: previous[name]
                                                  for name in ("nonlinear", "linear", "constraints", "wires")}
            record["original_main_W_source_paths"] = previous["source_paths"]
            record["selected_counts_agree_with_original_main_W"] = all(
                record[name] == value for name, value in record["original_main_W_counts"].items())
            record["artifact_identity_claimed"] = False
            result[revision] = record
    return result
