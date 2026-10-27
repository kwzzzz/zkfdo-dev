#!/usr/bin/env python3
"""Prepare explicit v2.3 view sidecars, with no compiler, judge or fuzzer execution.

Input plan: targets with label, template, arguments, source {path,sha256},
sources [{path,sha256}], original_wrapper {path,sha256}, fragment_spec {path,sha256}.
The source closure is explicit; no directory traversal is used.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import os

import s_tag_wrapper_prototype_20261027 as prototype

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs/s-round4-2026-10-27"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, output=False):
    p = Path(path).absolute()
    if p.is_relative_to(ROOT / "target"):
        raise ValueError("old target is not an input")
    if any(part.startswith(("n6-a-remeasure-2026-10-25", "n6-b6", "h1-")) for part in p.parts):
        raise ValueError("protected path")
    if not p.resolve().is_relative_to(OUT if output else ROOT):
        raise ValueError("path outside allowed root")
    return p


def read_ref(ref):
    p = checked(ref["path"])
    raw = p.read_bytes()
    if sha(raw) != ref["sha256"]:
        raise ValueError("input SHA mismatch: " + str(p))
    return p, raw


def save(path, value):
    p = checked(path, True)
    raw = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    with p.open("xb") as f:
        f.write(raw)
    return {"path": str(p), "sha256": sha(raw)}


def prepare(row, folder):
    source, source_raw = read_ref(row["source"])
    sources = {p: raw.decode() for p, raw in (read_ref(ref) for ref in row["sources"])}
    if sources.get(source) != source_raw.decode():
        raise ValueError("target source absent from explicit closure")
    _, original = read_ref(row["original_wrapper"])
    _, fragment = read_ref(row["fragment_spec"])
    wrapper, tags, evidence = prototype.render_prototype(source, source_raw.decode(), row["template"], row["arguments"], sources)
    if wrapper is None:
        raise ValueError(evidence["generation_refusal"])
    legacy = prototype.legacy_wrapper(source, row["template"], row["arguments"]).encode()
    if original != legacy:
        raise ValueError("original wrapper differs from frozen legacy rendering")
    if not tags and wrapper.encode() != original:
        raise ValueError("untagged wrapper bytes changed")
    folder = checked(folder, True)
    folder.mkdir(parents=True, exist_ok=False)
    saved_wrapper = save(folder / "target.circom", wrapper.encode())
    saved_fragment = save(folder / "original-fragment-spec.json", fragment)
    view = None
    if tags:
        view = save(folder / "component-view.json", {
            "schema": "zkfdo-component-view-v1", "target_prefix": "main.__s_tag_target",
            "target_template": row["template"], "target_source": str(source),
            "target_source_sha256": sha(source_raw), "wrapper_sha256": saved_wrapper["sha256"],
            "original_fragment_spec": saved_fragment["path"], "original_fragment_spec_sha256": saved_fragment["sha256"],
            "concrete_arguments": row["arguments"],
            "attached_without_enforcement": [{"input": tag["input"], "tag": item["name"], "value": item["value"]}
                                               for tag in tags for item in tag["tags"]]})
    return {"label": row["label"], "template": row["template"], "wrapper": saved_wrapper,
            "original_fragment_spec": saved_fragment, "component_view": view,
            "untagged_byte_preserved": not tags, "tags_attached_without_enforcement": tags}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise ValueError("nice 19 required")
    plan = json.loads(checked(a.plan).read_text())
    folder = checked(a.output, True)
    folder.mkdir(parents=True, exist_ok=False)
    rows = [prepare(row, folder / str(i)) for i, row in enumerate(plan["targets"])]
    print(json.dumps(save(folder / "prepared-views.json", {"targets": rows}), ensure_ascii=False))


if __name__ == "__main__":
    main()
