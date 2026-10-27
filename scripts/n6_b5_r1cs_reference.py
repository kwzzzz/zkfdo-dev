#!/usr/bin/env python3
"""Trace B whole-circuit R1CS hashes to recorded preflight artifacts.

This reads queue and preflight metadata only; it never opens fuzz candidates.
Missing deleted artifacts remain unavailable rather than being recomputed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from n6_j1_base_inputs import ROOT, dump_json, sha256

QUEUE = ROOT / "runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json"
PROOF = ROOT / "runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/preflight-proof.json"


def within_root(value: str, root: Path) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("preflight path escapes repository")
    return path


def preflight_artifact(preflight_path: Path, root: Path) -> tuple[str | None, str | None]:
    if not preflight_path.is_file():
        return None, "preflight_missing"
    record = json.loads(preflight_path.read_text())
    rows = record.get("compile", [])
    if len(rows) != 1 or rows[0].get("status") != "succeeded":
        return None, "whole_preflight_not_succeeded"
    row = rows[0]
    recorded = row.get("r1cs_sha256")
    if isinstance(recorded, str) and len(recorded) == 64:
        return recorded, "recorded_preflight_hash"
    stdout = row.get("stdout_path")
    if not isinstance(stdout, str):
        return None, "preflight_compile_path_missing"
    # The compile row records stdout inside the exact compile invocation.
    # Inspect only that invocation's sibling artifact directory.
    compile_dir = within_root(str(preflight_path.parent / stdout), root).parent
    artifacts = compile_dir / "artifacts"
    if not artifacts.is_dir():
        return None, "preflight_artifacts_missing"
    r1cs = sorted(artifacts.glob("*.r1cs"))
    if len(r1cs) == 1:
        return sha256(r1cs[0]), str(r1cs[0])
    if len(r1cs) > 1:
        return None, "preflight_r1cs_count_not_one"
    # Historical preflight cleanup retained exact artifact paths and SHA-256s.
    # The compile directory is obtained from the recorded stdout path above.
    invocation_root = compile_dir.parent.parent
    plan_path = invocation_root / "artifact-deletion-plan.json"
    cleanup_path = invocation_root / "artifact-cleanup.json"
    if not plan_path.is_file() or not cleanup_path.is_file():
        return None, "preflight_r1cs_deleted_without_hash"
    plan = json.loads(plan_path.read_text())
    cleanup = json.loads(cleanup_path.read_text())
    if cleanup.get("status") != "completed" or cleanup.get("deletion_plan_sha256") != sha256(plan_path):
        return None, "preflight_cleanup_evidence_invalid"
    entries = [item for item in plan.get("artifacts", [])
               if Path(item.get("path", "")).suffix == ".r1cs"
               and within_root(str(invocation_root / item["path"]), root).parent == artifacts]
    if len(entries) != 1:
        return None, "preflight_deleted_r1cs_count_not_one"
    digest = entries[0].get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        return None, "preflight_deleted_r1cs_hash_missing"
    return digest, f"{plan_path}::{entries[0]['path']}"


def build_map(queue_path: Path, proof_path: Path, root: Path) -> dict:
    queue = json.loads(queue_path.read_text())
    proof = json.loads(proof_path.read_text())
    if proof.get("status") != "passed" or len(queue.get("units", [])) != 30:
        raise ValueError("B queue/preflight proof not complete")
    source_queue = within_root(proof["source_queue"], root)
    if proof.get("source_queue_sha256") != sha256(source_queue):
        raise ValueError("preflight proof source queue hash mismatch")
    revisions: dict[str, dict] = {}
    for unit in queue["units"]:
        identifier = unit["identifier"]
        key = unit["unit_id"] + ":W"
        evidence = proof["rows"].get(key)
        if not isinstance(evidence, dict) or evidence.get("status") != "passed":
            raise ValueError(f"W preflight proof missing: {key}")
        if evidence.get("destination_spec_sha256") != unit["whole_spec_sha256"]:
            raise ValueError(f"final W spec differs from preflight proof: {key}")
        sources = []
        hashes = []
        for kind in ("destination", "source"):
            path = within_root(evidence[f"{kind}_preflight"], root)
            if sha256(path) != evidence[f"{kind}_preflight_sha256"]:
                raise ValueError(f"preflight hash mismatch: {path}")
            digest, source = preflight_artifact(path, root)
            sources.append({"preflight_path": str(path), "preflight_sha256": sha256(path),
                            "r1cs_path_or_status": source, "r1cs_sha256": digest})
            if digest:
                hashes.append(digest)
        if len(set(hashes)) > 1:
            raise ValueError(f"conflicting R1CS hashes: {key}")
        row = revisions.setdefault(identifier, {"unit_hashes": {}, "evidence": []})
        row["unit_hashes"][unit["unit_id"]] = hashes[0] if hashes else None
        row["evidence"].append({"unit_id": unit["unit_id"], "sources": sources})
    if len(revisions) != 10:
        raise ValueError("B revision count differs from 10")
    for row in revisions.values():
        hashes = list(row["unit_hashes"].values())
        distinct = set(hashes)
        row["status"] = "verified" if len(hashes) == 3 and None not in distinct and len(distinct) == 1 else "unavailable"
        row["r1cs_sha256"] = hashes[0] if row["status"] == "verified" else None
    return {"schema": "n6-b5-r1cs-reference-v1", "queue_path": str(queue_path),
            "queue_sha256": sha256(queue_path), "proof_path": str(proof_path),
            "proof_sha256": sha256(proof_path), "revisions": revisions}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=QUEUE)
    parser.add_argument("--proof", type=Path, default=PROOF)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("R1CS map already exists")
    result = build_map(args.queue.resolve(), args.proof.resolve(), ROOT)
    dump_json(args.output, result)
    print(json.dumps({"output": str(args.output), "sha256": sha256(args.output),
                      "verified_revisions": sum(x["status"] == "verified" for x in result["revisions"].values()),
                      "unavailable_revisions": sum(x["status"] == "unavailable" for x in result["revisions"].values())}))


if __name__ == "__main__":
    main()
