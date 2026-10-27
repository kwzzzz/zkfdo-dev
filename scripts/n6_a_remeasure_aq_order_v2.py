#!/usr/bin/env python3
"""Read-only ordering helpers for the approved A aq v2 runner.

The prepared S requests name shared wrappers, not a unique failing instance.
Resolve those wrappers through the RQ-C map's hash-pinned discovery/capture
metadata and retain *all* matching source/template/parameter instance paths.
This is scheduling metadata; it does not claim an engine verdict or identify a
unique failing site. Candidate payload files are never opened.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

ENGINES = ("v2.2", "v1")
SITE_PREVIEW_LIMIT = 5
_SITE = re.compile(r"main(?:\[\d+\])*(?:\.[A-Za-z_$][A-Za-z0-9_$]*(?:\[\d+\])*)*")
_SHA = re.compile(r"[0-9a-f]{64}")
_MAIN = re.compile(r"\bcomponent\s+main\s*(?:\{[^}]*\})?\s*=\s*"
                   r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^()]*)\)\s*;")
_COMMENT = re.compile(r"^\s*//\s*(?:zkfdo[-_ ]?)?(?:instance_path|instance|site)\s*:\s*(.*?)\s*$",
                      re.MULTILINE)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _paths(value: Any, label: str) -> list[str]:
    values = [value] if isinstance(value, str) else value
    _require(isinstance(values, list) and bool(values), f"missing or malformed {label}")
    _require(all(isinstance(site, str) and _SITE.fullmatch(site) for site in values),
             f"missing or malformed {label}")
    return sorted(set(values))


def under(site: str, root: str) -> bool:
    """A component boundary matters: main.a is not a prefix of main.ab."""
    return site == root or site.startswith(root + ".") or site.startswith(root + "[")


def request_site(row: dict[str, Any], request: dict[str, Any]) -> list[str]:
    """Extract explicit site metadata; an S request with no identity fails closed.

    ``component_wrapper_metadata`` may be populated by the read-only resolver
    below. Values under ``candidate`` are not consulted or opened.
    """
    found: list[list[str]] = []
    for source in (row, request):
        for key in ("site", "sites", "instance", "instance_path", "instance_paths", "candidate_site"):
            if key in source:
                found.append(_paths(source[key], key))
    if found:
        _require(all(sites == found[0] for sites in found), "conflicting explicit request sites")
        return found[0]
    metadata = request.get("component_wrapper_metadata")
    if metadata is not None:
        _require(isinstance(metadata, dict), "malformed component wrapper metadata")
        for key in ("sites", "instance_paths", "site", "instance_path"):
            if key in metadata:
                return _paths(metadata[key], "component wrapper sites")
        raise ValueError("missing component wrapper sites")
    if row.get("method") == "W":
        return ["main"]
    raise ValueError("missing S request site or component wrapper identity")


def _checked_bytes(path: Path, digest: str, label: str) -> bytes:
    _require(isinstance(digest, str) and _SHA.fullmatch(digest) is not None,
             f"invalid {label} SHA-256")
    data = path.read_bytes()
    _require(hashlib.sha256(data).hexdigest() == digest, f"{label} SHA-256 mismatch: {path}")
    return data


def _checked_json(path: str, digest: str, label: str) -> dict[str, Any]:
    document = json.loads(_checked_bytes(Path(path), digest, label))
    _require(isinstance(document, dict), f"malformed {label}: {path}")
    return document


def _wrapper(row: dict[str, Any], request: dict[str, Any]) -> tuple[Path, str, tuple[str, ...], list[str]]:
    value = request.get("component_wrapper")
    _require(isinstance(value, str) and bool(value), "missing S component wrapper")
    path = Path(value)
    source = _checked_bytes(path, row.get("component_wrapper_sha256"), "component wrapper").decode()
    comments = _COMMENT.findall(source)
    sites = _paths(comments, "wrapper instance comments") if comments else []
    # Metadata is never inferred from a template-looking token in a comment.
    masked = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
    mains = _MAIN.findall(masked)
    _require(len(mains) == 1, f"missing or malformed S wrapper main identity: {path}")
    name, arguments = mains[0]
    parameters = tuple(value.strip() for value in arguments.split(",")) if arguments.strip() else ()
    _require(all(re.fullmatch(r"-?\d+", value) for value in parameters),
             f"unsupported S wrapper parameter identity: {path}")
    return path, name, parameters, sites


@lru_cache(maxsize=4096)
def _source_key(source: str) -> str:
    return str(Path(source).resolve())


def _signature(source: str, template: str, parameters: list[str] | tuple[str, ...]) -> tuple:
    _require(isinstance(source, str) and bool(source) and isinstance(template, str) and bool(template),
             "malformed wrapper source/template metadata")
    _require(isinstance(parameters, (list, tuple)) and all(isinstance(x, str) for x in parameters),
             "malformed wrapper parameter metadata")
    return _source_key(source), template, tuple(parameters)


def _resolve_wrappers(rows: list[dict[str, Any]], requests: dict[int, dict[str, Any]],
                      mapped_revision: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    resolved: dict[int, dict[str, Any]] = {}
    missing: list[tuple[dict[str, Any], Path, str, tuple[str, ...]]] = []
    for row in rows:
        queue = row["queue_order"]
        request = requests[queue]
        try:
            sites = request_site(row, request)
        except ValueError as error:
            if str(error) != "missing S request site or component wrapper identity":
                raise
        else:
            resolved[queue] = {"sites": sites, "site_basis": "explicit_request_metadata"
                               if row.get("method") != "W" else "whole_entrypoint"}
            continue
        path, name, parameters, comments = _wrapper(row, request)
        if comments:
            resolved[queue] = {"sites": comments, "site_basis": "wrapper_instance_comments"}
        elif mapped_revision is None:
            # No RQ-C roots can match. Still verify the S wrapper's hash and identity.
            resolved[queue] = {"sites": [], "site_basis": "wrapper_identity_no_rqc_revision",
                               "wrapper_identity": {"template": name, "parameters": list(parameters)}}
        else:
            missing.append((row, path, name, parameters))
    if not missing:
        return resolved
    assert mapped_revision is not None
    discovery = _checked_json(mapped_revision["discovery_path"], mapped_revision["discovery_sha256"],
                              "RQ-C discovery metadata")
    targets = discovery.get("targets")
    _require(isinstance(targets, list), "missing wrapper discovery targets")
    by_path: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        if isinstance(target, dict) and isinstance(target.get("generated_wrapper_path"), str):
            by_path.setdefault(target["generated_wrapper_path"], []).append(target)
    requested: dict[int, tuple] = {}
    original_checked: set[tuple[str, str]] = set()
    for row, path, name, parameters in missing:
        request = requests[row["queue_order"]]
        _require(discovery.get("selected_entrypoint") == request.get("entrypoint"),
                 "wrapper discovery entrypoint differs from request")
        # Prepared copies retain the exact original path beneath their sources root.
        marker = "/sources/"
        original = (str(Path(request["source_root"]) / str(path).split(marker, 1)[1])
                    if marker in str(path) else str(path))
        matches = by_path.get(original, [])
        _require(bool(matches), f"S wrapper missing from pinned discovery metadata: {path}")
        signatures = {_signature(t.get("source_path"), t.get("template_name"),
                                 t.get("concrete_parameters")) for t in matches}
        _require(len(signatures) == 1, f"ambiguous S wrapper discovery identity: {path}")
        signature = next(iter(signatures))
        _require(signature[1:] == (name, parameters), f"S wrapper/discovery identity differs: {path}")
        pin = (original, row["component_wrapper_sha256"])
        if pin not in original_checked:
            _checked_bytes(Path(original), pin[1], "original component wrapper")
            original_checked.add(pin)
        requested[row["queue_order"]] = signature
    capture = _checked_json(mapped_revision["capture_path"], mapped_revision["capture_sha256"],
                            "RQ-C capture metadata")
    _require(capture.get("status") == "captured" and isinstance(capture.get("instances"), list),
             "invalid RQ-C instance capture metadata")
    _require(capture.get("entrypoint") == discovery.get("selected_entrypoint"),
             "capture/discovery entrypoint differs")
    selected: dict[tuple, list[str]] = {signature: [] for signature in requested.values()}
    for instance in capture["instances"]:
        arguments = instance.get("arguments", [])
        if not all(isinstance(arg, dict) and arg.get("kind") == "scalar" for arg in arguments):
            continue
        signature = _signature(instance.get("source_path"), instance.get("template_name"),
                               [arg.get("value") for arg in arguments])
        if signature in selected:
            selected[signature].extend(_paths(instance.get("path"), "captured wrapper instance"))
    evidence = {key: mapped_revision[key] for key in
                ("discovery_path", "discovery_sha256", "capture_path", "capture_sha256")}
    for queue, signature in requested.items():
        sites = sorted(set(selected[signature]))
        _require(bool(sites), f"S wrapper identity has no captured instance: queue {queue}")
        resolved[queue] = {"sites": sites, "site_basis": "wrapper_source_template_parameters",
                           "multiple_sites": len(sites) > 1, "site_metadata": evidence,
                           "wrapper_identity": {"source_path": signature[0], "template": signature[1],
                                                "parameters": list(signature[2])}}
    return resolved


def computed_order(indexes: dict[str, dict[str, Any]], revisions: list[str],
                   mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Return engine-major stable partitions without modifying any input or file.

    Full site lists can contain thousands of locations per shared wrapper. Output
    therefore records their count, SHA-256 of compact UTF-8 JSON, and a five-site
    preview. ``mapped`` and ``mapped_roots`` use the complete site list.
    """
    _require(bool(revisions) and len(revisions) == len(set(revisions)), "invalid revision order")
    records = mapping.get("revisions")
    _require(isinstance(records, list), "missing RQ-C mapping revisions")
    by_revision: dict[str, dict[str, Any]] = {}
    roots: dict[str, list[str]] = {}
    for record in records:
        revision = record.get("revision_id")
        _require(isinstance(revision, str) and revision not in by_revision,
                 "invalid or duplicated RQ-C mapping revision")
        _require(isinstance(record.get("items"), list), "missing RQ-C mapping items")
        by_revision[revision] = record
        roots[revision] = []
        for item in record["items"]:
            paths = item.get("instance_paths")
            _require(isinstance(paths, list), "missing RQ-C instance_paths")
            if paths:
                roots[revision].extend(_paths(paths, "RQ-C instance paths"))
    result: list[dict[str, Any]] = []
    identity_cache: dict[tuple, dict[str, Any]] = {}
    compact_cache: dict[tuple, dict[str, Any]] = {}
    for engine in ENGINES:
        _require(engine in indexes and isinstance(indexes[engine].get("requests"), list),
                 f"missing engine request index: {engine}")
        index_rows = indexes[engine]["requests"]
        queues = [row.get("queue_order") for row in index_rows]
        _require(all(type(queue) is int and queue >= 0 for queue in queues) and
                 len(queues) == len(set(queues)), f"invalid or duplicated queues: {engine}")
        for revision in revisions:
            # Keep index sequence exactly, including within the mapped/rest partitions.
            rows = [row for row in index_rows if row.get("revision_id") == revision]
            requests = {row["queue_order"]: _checked_json(row["request"], row["request_sha256"],
                                                         "prepared request") for row in rows}
            cached: dict[int, dict[str, Any]] = {}
            keys: dict[int, tuple] = {}
            missing = []
            for row in rows:
                request = requests[row["queue_order"]]
                # Inputs differ by engine, but these structural fields do not.
                key = (revision, row.get("method"), row.get("component_wrapper_sha256"),
                       json.dumps({k: v for k, v in request.items()
                                   if k not in ("base_input", "candidate", "id")}, sort_keys=True),
                       json.dumps({k: row[k] for k in ("site", "sites", "instance", "instance_path",
                                                      "instance_paths", "candidate_site") if k in row},
                                  sort_keys=True))
                if key in identity_cache:
                    cached[row["queue_order"]] = identity_cache[key]
                else:
                    missing.append(row)
                keys[row["queue_order"]] = key
            resolved = _resolve_wrappers(missing, requests, by_revision.get(revision))
            revision_order = []
            for row in rows:
                queue = row["queue_order"]
                metadata = cached.get(queue, resolved.get(queue))
                assert metadata is not None
                key = keys[queue]
                identity_cache[key] = metadata
                if key not in compact_cache:
                    sites = metadata["sites"]
                    matched = sorted({root for root in roots.get(revision, [])
                                      if any(under(site, root) for site in sites)})
                    compact_cache[key] = {k: v for k, v in metadata.items() if k != "sites"}
                    compact_cache[key].update({"site_count": len(sites),
                        "sites_sha256": hashlib.sha256(json.dumps(sites, ensure_ascii=False,
                            separators=(",", ":")).encode()).hexdigest(),
                        "sites_preview": sites[:SITE_PREVIEW_LIMIT],
                        "sites_preview_truncated": len(sites) > SITE_PREVIEW_LIMIT,
                        "mapped_roots": matched, "mapped": bool(matched),
                        "multiple_sites": len(sites) > 1})
                revision_order.append({"engine": engine, "revision": revision, "queue_order": queue,
                                       "request_sha256": row["request_sha256"], **compact_cache[key]})
            result.extend([row for row in revision_order if row["mapped"]])
            result.extend([row for row in revision_order if not row["mapped"]])
    return result
