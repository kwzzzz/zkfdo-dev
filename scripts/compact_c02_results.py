#!/usr/bin/env python3
"""Count-preserving projection of four repeated C-02 diagnostic arrays only.

Default: read-only size estimate. --write first preserves the exact input using
exclusive creation, verifies its hash, then atomically installs a new projection.
Circuits, candidates, witnesses, source files and referenced artifacts are not read.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
PROJECTION_VERSION = "c02-diagnostic-occurrence-counts-v1"
REASON_FIELDS = {"reason_class", "reason_subtype", "reason_sha256"}
IGNORED_DIAGNOSTIC_FIELDS = {
    "unsupported": {"source_path", "line"},
    "wrapper_failure_diagnostics": {"source_path", "callsite_identity_sha256"},
    "exclusion_reasons": set(),
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def path_text(path):
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def array_kind(path):
    if len(path) < 7 or path[0] != "repositories" or path[2] != "entrypoints" or path[4] != "measurement":
        return None
    if len(path) == 7 and path[5] == "discovery" and path[6] in {
            "unsupported", "callsite_wrapper_statuses", "wrapper_failure_diagnostics"}:
        return path[6]
    if len(path) == 9 and path[5:7] == ("preparation", "targets") and path[8] == "exclusion_reasons":
        return "exclusion_reasons"
    return None


def pointer(path):
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in path)


def canonical_fingerprint(data):
    """Every field except the four projection slots and explicit version header."""
    hasher = hashlib.sha256()

    def visit(value, path=()):
        if array_kind(path):
            hasher.update(b"<count-projection-slot>")
        elif isinstance(value, dict):
            hasher.update(b"{")
            for key in sorted(value):
                if not path and key in ("schema_version", "diagnostic_projection"):
                    continue
                hasher.update(json.dumps(key, ensure_ascii=False).encode())
                hasher.update(b":")
                visit(value[key], path + (key,))
                hasher.update(b",")
            hasher.update(b"}")
        elif isinstance(value, list):
            hasher.update(b"[")
            for index, child in enumerate(value):
                visit(child, path + (index,))
                hasher.update(b",")
            hasher.update(b"]")
        else:
            hasher.update(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())

    visit(data)
    return hasher.hexdigest()


def project_array(rows, path, kind):
    if not isinstance(rows, list):
        # Legacy unknown metadata is null, not an empty array or zero count.
        if rows is None:
            return rows
        raise ValueError(f"unexpected projection slot type: {pointer(path)}")
    if len(rows) < 4:
        return rows
    counts = Counter()
    for row in rows:
        if kind == "callsite_wrapper_statuses":
            if not isinstance(row, str):
                raise ValueError("wrapper status occurrence must be a string")
            group = {"wrapper_status": row}
        else:
            keep = REASON_FIELDS | ({"wrapper_status"} if kind == "wrapper_failure_diagnostics" else set())
            if not isinstance(row, dict) or set(row) - keep - IGNORED_DIAGNOSTIC_FIELDS[kind]:
                raise ValueError(f"unrecognized diagnostic fields: {pointer(path)}")
            group = {key: row[key] for key in sorted(keep) if key in row}
        counts[json.dumps(group, sort_keys=True, ensure_ascii=False, allow_nan=False)] += 1
    groups = [{**json.loads(key), "occurrences": count} for key, count in sorted(counts.items())]
    if sum(row["occurrences"] for row in groups) != len(rows):
        raise ValueError("diagnostic occurrence count was not conserved")
    return {"representation": PROJECTION_VERSION, "total_occurrences": len(rows), "groups": groups,
            "expanded_json_pointer": pointer(path),
            "measurement_reference_pointer": pointer(path[:5] + ("reference",)),
            "scope": "diagnostic_occurrences_not_independent_failures_candidates_or_causes"}


def project(data, expanded_reference):
    if data.get("schema_version") != 1 or "diagnostic_projection" in data:
        raise ValueError("only the original C-02 schema 1 summary can be projected")
    before = canonical_fingerprint(data)
    array_totals, projected_totals, groups, slots = Counter(), Counter(), Counter(), Counter()

    def visit(value, path=()):
        kind = array_kind(path)
        if kind:
            if isinstance(value, list):
                array_totals[kind] += len(value)
            result = project_array(value, path, kind)
            if result is not value:
                projected_totals[kind] += len(value)
                groups[kind] += len(result["groups"])
                slots[kind] += 1
            return result
        if isinstance(value, dict):
            for key in list(value):
                value[key] = visit(value[key], path + (key,))
        elif isinstance(value, list):
            for index in range(len(value)):
                value[index] = visit(value[index], path + (index,))
        return value

    visit(data)
    after = canonical_fingerprint(data)
    if before != after:
        raise ValueError("a non-diagnostic field changed during projection")
    data["schema_version"] = SCHEMA_VERSION
    data["diagnostic_projection"] = {
        "version": PROJECTION_VERSION, "expanded_source": expanded_reference,
        "expanded_schema_version": 1, "retained_fields_sha256": before,
        "verification": "canonical fingerprint of all fields outside the four diagnostic slots is unchanged",
        "array_occurrences_before": dict(array_totals), "projected_occurrences": dict(projected_totals),
        "projected_group_count": dict(groups), "projected_array_count": dict(slots),
        "minimum_array_length": 4,
        "grouping": {"unsupported": sorted(REASON_FIELDS),
                     "wrapper_failure_diagnostics": sorted(REASON_FIELDS | {"wrapper_status"}),
                     "exclusion_reasons": sorted(REASON_FIELDS),
                     "callsite_wrapper_statuses": ["wrapper_status"]},
        "details_in_expanded_source": ["original array order", "per-occurrence source paths and lines",
                                       "per-occurrence callsite identity digests"],
        "limitations": ["This is lossless for occurrence counts and all non-diagnostic fields, not a reversible compression of diagnostic order/locations without the preserved expanded source.",
                        "Diagnostic occurrences may repeat across callsites, preparation targets, and layers; counts are not independent failed entrypoints, candidates, or root causes.",
                        "All entrypoint states, numeric results, histories, measurement references, source/exposure aggregates and preparation target records remain unchanged."]}
    return data


def encoded_chunks(data):
    # Shared JSON is machine-readable; the preserved expanded source retains
    # original formatting. Avoid megabytes of indentation in the projection.
    return json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False).iterencode(data)


def run(input_path, output_path, raw_path, write=False):
    input_path, output_path, raw_path = (Path(path).resolve() for path in (input_path, output_path, raw_path))
    if raw_path in (input_path, output_path):
        raise ValueError("raw preservation must use a separate path")
    if output_path.exists() and output_path != input_path:
        raise ValueError("new output exists; refuse overwrite")
    if raw_path.exists():
        raise ValueError("raw preservation path exists; refuse overwrite")
    original_hash = digest(input_path)
    original_bytes = input_path.stat().st_size
    parse_path = input_path
    if write:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with input_path.open("rb") as source, raw_path.open("xb") as preserved:
            shutil.copyfileobj(source, preserved, 1024 * 1024)
            preserved.flush()
            os.fsync(preserved.fileno())
        if digest(raw_path) != original_hash or digest(input_path) != original_hash:
            raise ValueError("input changed while preserving expanded JSON; no projection installed")
        parse_path = raw_path
    with parse_path.open() as handle:
        data = json.load(handle)
    project(data, {"path": path_text(raw_path), "sha256": original_hash, "bytes": original_bytes})
    encoded_bytes = 1
    if write:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_path.parent,
                                             prefix=".c02-compact-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                for chunk in encoded_chunks(data):
                    handle.write(chunk)
                    encoded_bytes += len(chunk.encode("utf-8"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if digest(input_path) != original_hash:
                raise ValueError("input changed before atomic replacement")
            if output_path != input_path and output_path.exists():
                raise ValueError("new output appeared before installation")
            os.replace(temporary, output_path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    else:
        encoded_bytes += sum(len(chunk.encode("utf-8")) for chunk in encoded_chunks(data))
    return {"status": "written" if write else "dry_run_no_files_changed", "input_bytes": original_bytes,
            "projected_bytes": encoded_bytes, "schema_version": SCHEMA_VERSION,
            "input_sha256": original_hash, "projection": data["diagnostic_projection"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-preserved", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.output, args.raw_preserved, args.write), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
