#!/usr/bin/env python3
"""Read-only two-pass scheduling over the unchanged v2 mapped classification.

For each engine, visit the approved first seven revisions once for mapped
requests (A), then again for unmapped requests (B), then the remaining six in
their full v2 order. Empty B segments remain explicit so revision finalization
and retained-evidence cleanup never happen prematurely at the end of A.
"""

from __future__ import annotations

from typing import Any

import n6_a_remeasure_aq_order_v2 as previous
from n6_a_remeasure_aq_execute_v2 import DEFAULT_REVISIONS

ENGINES = previous.ENGINES
PRIORITY_REVISIONS = DEFAULT_REVISIONS[:7]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _selection(revisions: list[str]) -> list[str]:
    _require(isinstance(revisions, (list, tuple)) and bool(revisions), "missing revision selection")
    _require(all(isinstance(revision, str) for revision in revisions) and
             len(revisions) == len(set(revisions)) and set(revisions) <= set(DEFAULT_REVISIONS),
             "provide unique approved aq revisions")
    selected = set(revisions)
    return [revision for revision in DEFAULT_REVISIONS if revision in selected]


def _segment_definitions(revisions: list[str]) -> list[dict[str, Any]]:
    selected = _selection(revisions)
    priority = [revision for revision in selected if revision in PRIORITY_REVISIONS]
    rest = [revision for revision in selected if revision not in PRIORITY_REVISIONS]
    return [{"engine": engine, "revision": revision, "pass": pass_name,
             "segment_id": f"{engine}/{pass_name}/{revision}",
             "final_for_revision": pass_name != "A", "requests": []}
            for engine in ENGINES
            for pass_name, group in (("A", priority), ("B", priority), ("rest", rest))
            for revision in group]


def computed_order(indexes: dict[str, dict[str, Any]], revisions: list[str],
                   mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the v3 order, preserving every v2 mapped flag and metadata field.

    Selection filters the approved revision order; it cannot reorder it.
    ``segment_is_final`` describes the whole segment (B/rest), not the final
    request within it. Use ``segments_for(result, revisions)`` to retain empty
    segments, including revisions with no requests at all.
    """
    selected = _selection(revisions)
    baseline = previous.computed_order(indexes, selected, mapping)
    by_revision = {(engine, revision): [] for engine in ENGINES for revision in selected}
    for row in baseline:
        _require(type(row.get("mapped")) is bool, "v2 mapped flag is not boolean")
        key = (row.get("engine"), row.get("revision"))
        _require(key in by_revision, "v2 order contains an unselected engine/revision")
        by_revision[key].append(row)
    result = []
    for segment in _segment_definitions(selected):
        pass_name = segment["pass"]
        rows = by_revision[(segment["engine"], segment["revision"])]
        if pass_name != "rest":
            rows = [row for row in rows if row["mapped"] == (pass_name == "A")]
        for row in rows:
            result.append({**row, "pass": pass_name, "segment_id": segment["segment_id"],
                           "segment_is_final": segment["final_for_revision"]})
    _require(len(result) == len(baseline), "v3 order lost or duplicated a request")
    # Also rejects a malformed inherited order before its schedule can be used.
    segments_for(result, selected)
    return result


def segments_for(order: list[dict[str, Any]], revisions: list[str] | None = None
                 ) -> list[dict[str, Any]]:
    """Group a complete v3 order into explicit ordered A/B/rest segments.

    ``revisions`` is optional only when every selected revision has at least
    one request. Supplying it preserves wholly empty revisions too. Priority
    revisions always have A and B segments, even when either request list is
    empty; B is their sole final segment. No files are read or modified here.
    """
    _require(isinstance(order, list), "v3 order must be a list")
    if revisions is None:
        present = {row.get("revision") for row in order if isinstance(row, dict)}
        _require(len(present - set(DEFAULT_REVISIONS)) == 0, "unknown revision in v3 order")
        if not present:
            _require(not order, "malformed empty v3 order")
            return []
        revisions = [revision for revision in DEFAULT_REVISIONS if revision in present]
    segments = _segment_definitions(revisions)
    by_id = {segment["segment_id"]: (position, segment)
             for position, segment in enumerate(segments)}
    previous_position = -1
    seen = set()
    for row in order:
        _require(isinstance(row, dict), "malformed v3 order row")
        segment_id = row.get("segment_id")
        _require(isinstance(segment_id, str) and segment_id in by_id,
                 "unknown segment in v3 order")
        position, segment = by_id[segment_id]
        _require(position >= previous_position, "v3 segments are out of order")
        previous_position = position
        _require(all(row.get(key) == segment[key] for key in ("engine", "revision", "pass")) and
                 type(row.get("segment_is_final")) is bool and
                 row["segment_is_final"] == segment["final_for_revision"],
                 "v3 segment metadata differs")
        mapped = row.get("mapped")
        _require(type(mapped) is bool and
                 (segment["pass"] == "rest" or mapped == (segment["pass"] == "A")),
                 "mapped flag differs from v3 pass")
        queue = row.get("queue_order")
        _require(type(queue) is int and queue >= 0, "invalid v3 queue_order")
        identity = (row["engine"], queue)
        _require(identity not in seen, "duplicated v3 request")
        seen.add(identity)
        segment["requests"].append(row)
    return segments
