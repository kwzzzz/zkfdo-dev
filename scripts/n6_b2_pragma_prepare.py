#!/usr/bin/env python3
"""Prepare a versioned N6-B parser correction; never execute a campaign.

Stages are explicit: sources, equivalence, specs, parser-check, and
preflight-queue. The source stage requires the recorded B P1003 parser result.
Compiled R1CS pairs use temporary directories under ignored runs/ and are
removed after byte comparison; hashes and failure evidence remain.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import difflib
import filecmp
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = "77e0f2db173d0c1812de503a"
SOURCE_QUEUE = ROOT / "runs/n6-a2b-2026-10-08.noindex/queue-b-v4.json"
SOURCE_QUEUE_SHA256 = "d39e821fd65cea1852ad6a20b88ab59e03a7c363be9022224221986716161600"
OUTPUT = ROOT / "runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a"
ENGINE = ROOT / "scripts/run_policy_a_engine_v4.py"
QUEUE_RUNNER = ROOT / "scripts/run_n6_v4_3_queue.py"
CIRCOM_SHA256 = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
OLD_PRAGMA = b"pragma circom 2.2.3;"
NEW_PRAGMA = b"pragma circom 2.2.1;"
INCLUDE = re.compile(rb'(?m)^\s*include\s+"([^"\r\n]+)"\s*;')
SEEDS = (2026100601, 2026100602, 2026100603)
PARSER_MODULE = ROOT / "scripts/n6_b2_parser_acceptance.py"
PARSER_CALIBRATION = ROOT / "runs/n6-b2-2026-10-09.noindex/parser-marker-control.json"
P1003_LEDGER = ROOT / "runs/n6-b2-2026-10-09.noindex/parser-probe-high-version-W.jsonl"
PARSER_VERSION = (2, 2, 1)
PRAGMA_VERSION = re.compile(rb"(?m)^\s*pragma\s+circom\s+(\d+)\.(\d+)\.(\d+)\s*;")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def save(path: Path, value: Any, *, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                        dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def checked_json(path: Path, expected_hash: str) -> dict[str, Any]:
    if not path.is_file() or sha256(path) != expected_hash:
        raise ValueError(f"input SHA-256 mismatch: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def tree_sha256(root: Path) -> str:
    """Match the Policy-A source snapshot tree hash."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            kind, payload = b"L", os.readlink(path).encode()
        elif path.is_dir():
            kind, payload = b"D", b""
        elif path.is_file():
            kind, payload = b"F", bytes.fromhex(sha256(path))
        else:
            raise ValueError(f"unexpected source node: {path}")
        digest.update(kind + len(name).to_bytes(8, "big") + name)
        digest.update(len(payload).to_bytes(8, "big") + payload)
    return digest.hexdigest()


def source_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any],
                             dict[str, Any], dict[str, Any]]:
    queue = checked_json(SOURCE_QUEUE, SOURCE_QUEUE_SHA256)
    if queue.get("branch") != "B" or len(queue.get("units", [])) != 30:
        raise ValueError("unexpected B queue denominator")
    units = [unit for unit in queue["units"] if unit.get("identifier") == IDENTIFIER]
    if len(units) != 3 or tuple(unit["seed"] for unit in units) != SEEDS:
        raise ValueError("target unit seeds/order changed")
    first = units[0]
    whole = checked_json(ROOT / first["whole_spec"], first["whole_spec_sha256"])
    split = checked_json(ROOT / first["split_spec"], first["split_spec_sha256"])
    if (len(whole["targets"]) != 1 or len(whole["source_snapshots"]) != 1
            or len(split["targets"]) != 305 or len(split["source_snapshots"]) != 305):
        raise ValueError("target W/S denominator changed")
    if any(target["source_snapshot_id"] != snapshot["id"] for target, snapshot in
           zip(split["targets"], split["source_snapshots"], strict=True)):
        raise ValueError("split target/snapshot order differs")
    plan_pin = next(row for row in split["pinned_files"] if row["label"] == "plan")
    plan = checked_json(Path(plan_pin["path"]), plan_pin["sha256"])
    if (len(plan["targets"]) != 305 or any(a["target_id"] != b["target_id"]
            for a, b in zip(plan["targets"], split["targets"], strict=True))):
        raise ValueError("plan/spec target order differs")
    for unit in units[1:]:
        s = checked_json(ROOT / unit["split_spec"], unit["split_spec_sha256"])
        w = checked_json(ROOT / unit["whole_spec"], unit["whole_spec_sha256"])
        if ([target["target_id"] for target in s["targets"]] !=
                [target["target_id"] for target in split["targets"]]
                or w["targets"][0]["entrypoint_sha256"] !=
                whole["targets"][0]["entrypoint_sha256"]):
            raise ValueError("seed specs use different sources")
    return queue, units, whole, split, plan


def pragma_replacement(data: bytes) -> tuple[bytes, int]:
    changed = 0
    lines = []
    for line in data.splitlines(keepends=True):
        content = line.rstrip(b"\r\n")
        if content == OLD_PRAGMA:
            line = NEW_PRAGMA + line[len(content):]
            changed += 1
        lines.append(line)
    result = b"".join(lines)
    for before, after in zip(data.splitlines(keepends=True),
                             result.splitlines(keepends=True), strict=True):
        if before != after and (before.rstrip(b"\r\n") != OLD_PRAGMA
                                or after.rstrip(b"\r\n") != NEW_PRAGMA):
            raise AssertionError("pragma replacement changed unrelated bytes")
    return result, changed


def include_replacement(data: bytes, old_project: Path,
                        new_project: Path) -> tuple[bytes, int, list[dict[str, str]]]:
    hits = []
    for match in INCLUDE.finditer(data):
        original = Path(match.group(1).decode())
        if original.is_absolute() and original.is_relative_to(old_project):
            corrected = new_project / original.relative_to(old_project)
            if not original.is_file() or not corrected.is_file():
                raise ValueError(f"include source/copy missing: {original} -> {corrected}")
            hits.append((match.start(1), match.end(1), original, corrected))
    result = data
    for start, end, _original, corrected in reversed(hits):
        result = result[:start] + str(corrected).encode() + result[end:]
    return result, len(hits), [{"old": str(old), "new": str(new)}
                               for _start, _end, old, new in hits]


def one_line_diff(before: bytes, after: bytes, source: Path, destination: Path) -> str:
    old_lines = before.decode().splitlines(keepends=True)
    new_lines = after.decode().splitlines(keepends=True)
    changed = sum(left != right for left, right in zip(old_lines, new_lines, strict=True))
    if changed != 1:
        raise ValueError(f"expected exactly one changed line: {destination}; got {changed}")
    return "".join(difflib.unified_diff(
        old_lines, new_lines, fromfile=rel(source), tofile=rel(destination), n=2))


def apfs_clone(source: Path, destination: Path, expected_tree: str) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    if tree_sha256(source) != expected_tree:
        raise ValueError(f"source tree hash changed: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["cp", "-cR", str(source), str(destination)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"APFS clone failed: {result.stderr.strip()}")
    if tree_sha256(destination) != expected_tree:
        raise ValueError(f"APFS clone differs from source: {destination}")


def confirmed_p1003(ledger_path: Path, whole_spec_sha: str,
                    entrypoint_sha: str) -> dict[str, Any]:
    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    if not rows or rows[0].get("kind") != "header" or rows[0].get(
            "queue_sha256") != SOURCE_QUEUE_SHA256:
        raise ValueError("original parser ledger does not bind the frozen B queue")
    matches = [row for row in rows[1:]
               if row.get("kind") == "target" and row.get("identifier") == IDENTIFIER
               and row.get("method") == "W"]
    if len(matches) != 1:
        raise ValueError("P1003 evidence must contain exactly one target W row")
    row = matches[0]
    if (row.get("spec_sha256") != whole_spec_sha
            or row.get("entrypoint_sha256") != entrypoint_sha
            or row.get("status") != "parser_error"
            or row.get("error_codes") != ["P1003"]):
        raise ValueError("P1003 evidence does not match the original W spec")
    return {"path": rel(ledger_path), "sha256": sha256(ledger_path),
            "status": row["status"], "error_codes": row["error_codes"],
            "entrypoint_sha256": entrypoint_sha,
            "spec_sha256": whole_spec_sha}


def stage_sources(output: Path, p1003_ledger: Path = P1003_LEDGER) -> dict[str, Any]:
    _queue, units, whole, split, _plan = source_inputs()
    p1003 = confirmed_p1003(p1003_ledger, units[0]["whole_spec_sha256"],
                            whole["targets"][0]["entrypoint_sha256"])
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"versioned output is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    old_project = Path(whole["source_snapshots"][0]["path"])
    new_project = output / "project"
    apfs_clone(old_project, new_project, whole["source_snapshots"][0]["tree_sha256"])
    changed_files = []
    diffs = []

    def patch_tree(source_root: Path, copied_root: Path) -> int:
        count = 0
        for source in sorted(source_root.rglob("*.circom")):
            if not source.is_file() or source.is_symlink():
                continue
            destination = copied_root / source.relative_to(source_root)
            before = source.read_bytes()
            after, replacements = pragma_replacement(before)
            if not replacements:
                continue
            if replacements != 1:
                raise ValueError(f"more than one pragma line in {source}")
            destination.write_bytes(after)
            diffs.append(one_line_diff(before, after, source, destination))
            changed_files.append({"kind": "pragma", "original": rel(source),
                                  "corrected": rel(destination),
                                  "original_sha256": sha256(source),
                                  "corrected_sha256": sha256(destination)})
            count += 1
        return count

    project_pragmas = patch_tree(old_project, new_project)
    if project_pragmas != 14:
        raise ValueError(f"project pragma denominator changed: {project_pragmas}")
    snapshot_pragmas = 0
    wrapper_rewrites = 0
    direct_wrappers = 0
    snapshots = []
    target_rows = []
    for target, original_snapshot in zip(split["targets"], split["source_snapshots"], strict=True):
        source = Path(original_snapshot["path"])
        destination = output / "snapshots" / original_snapshot["id"]
        apfs_clone(source, destination, original_snapshot["tree_sha256"])
        snapshot_pragmas += patch_tree(source, destination)
        original_wrapper = source / target["entrypoint_relative"]
        corrected_wrapper = destination / target["entrypoint_relative"]
        before = corrected_wrapper.read_bytes()
        after, count, includes = include_replacement(before, old_project, new_project)
        if count == 1:
            corrected_wrapper.write_bytes(after)
            diffs.append(one_line_diff(before, after, original_wrapper, corrected_wrapper))
            changed_files.append({"kind": "wrapper_include", "original": rel(original_wrapper),
                                  "corrected": rel(corrected_wrapper),
                                  "original_sha256": sha256(original_wrapper),
                                  "pre_include_sha256": hashlib.sha256(before).hexdigest(),
                                  "corrected_sha256": sha256(corrected_wrapper),
                                  "includes": includes})
            wrapper_rewrites += 1
        elif count == 0:
            direct_wrappers += 1
            if corrected_wrapper.read_bytes() == original_wrapper.read_bytes():
                raise ValueError("direct wrapper has neither include nor pragma correction")
        else:
            raise ValueError(f"multiple project absolute includes: {original_wrapper}")
        snapshots.append({"id": original_snapshot["id"], "source": rel(source),
                          "source_tree_sha256": original_snapshot["tree_sha256"],
                          "corrected": rel(destination),
                          "corrected_tree_sha256": tree_sha256(destination)})
        target_rows.append({"rank": target["rank"], "old_target_id": target["target_id"],
                            "original_wrapper": rel(original_wrapper),
                            "corrected_wrapper": rel(corrected_wrapper),
                            "original_wrapper_sha256": sha256(original_wrapper),
                            "corrected_wrapper_sha256": sha256(corrected_wrapper),
                            "absolute_include_rewrites": count})
    if wrapper_rewrites != 304 or direct_wrappers != 1:
        raise ValueError("wrapper absolute-include denominator changed")
    if snapshot_pragmas != 145:
        raise ValueError(f"snapshot pragma denominator changed: {snapshot_pragmas}")
    remaining = []
    for snapshot in snapshots:
        for source in (ROOT / snapshot["corrected"]).rglob("*.circom"):
            if not source.is_file() or source.is_symlink():
                continue
            for match in INCLUDE.finditer(source.read_bytes()):
                if match.group(1).decode().startswith(str(old_project) + "/"):
                    remaining.append(rel(source))
    if remaining:
        raise ValueError(f"old absolute project includes remain: {remaining[:5]}")
    diff_path = output / "source-diff.patch"
    diff_path.write_text("".join(diffs), encoding="utf-8")
    evidence = {"schema_version": 1, "kind": "n6_b2_pragma_source_correction",
                "status": "staged", "created_at": now(),
                "source_queue_sha256": SOURCE_QUEUE_SHA256,
                "p1003_evidence": p1003,
                "old_pragma": OLD_PRAGMA.decode(), "new_pragma": NEW_PRAGMA.decode(),
                "original_project": rel(old_project), "original_project_tree_sha256":
                whole["source_snapshots"][0]["tree_sha256"],
                "corrected_project": rel(new_project),
                "corrected_project_tree_sha256": tree_sha256(new_project),
                "project_pragma_files": project_pragmas,
                "snapshot_pragma_files": snapshot_pragmas,
                "wrapper_include_rewrites": wrapper_rewrites,
                "direct_wrapper_count": direct_wrappers,
                "remaining_old_absolute_includes": len(remaining),
                "source_diff": rel(diff_path), "source_diff_sha256": sha256(diff_path),
                "changed_files": changed_files, "snapshots": snapshots,
                "targets": target_rows, "candidate_contents_opened": False,
                "campaign_executed": False}
    save(output / "source-evidence.json", evidence)
    return evidence


def load_staged(output: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any],
                                       dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    queue, units, whole, split, plan = source_inputs()
    evidence = json.loads((output / "source-evidence.json").read_text(encoding="utf-8"))
    if evidence.get("status") != "staged" or len(evidence.get("targets", [])) != 305:
        raise ValueError("versioned source stage did not complete")
    p1003 = evidence["p1003_evidence"]
    if sha256(ROOT / p1003["path"]) != p1003["sha256"]:
        raise ValueError("original P1003 parser evidence changed")
    if sha256(ROOT / evidence["source_diff"]) != evidence["source_diff_sha256"]:
        raise ValueError("source diff changed")
    if tree_sha256(ROOT / evidence["corrected_project"]) != \
            evidence["corrected_project_tree_sha256"]:
        raise ValueError("corrected project changed")
    for row in evidence["snapshots"]:
        if tree_sha256(ROOT / row["corrected"]) != row["corrected_tree_sha256"]:
            raise ValueError(f"corrected snapshot changed: {row['id']}")
    return queue, whole, split, plan, evidence, units


def render_compile_command(target: dict[str, Any], entrypoint: Path, workspace: Path,
                           compile_output: Path, old_project: Path,
                           corrected_project: Path | None) -> list[str]:
    rendered = []
    for token in target["preflight_compile_command"]:
        token = (token.replace("{entrypoint}", str(entrypoint))
                      .replace("{workspace}", str(workspace))
                      .replace("{compile_output}", str(compile_output)))
        if corrected_project is not None and (token == str(old_project)
                                              or token.startswith(str(old_project) + "/")):
            token = str(corrected_project) + token[len(str(old_project)):]
        rendered.append(token)
    return rendered


def compile_r1cs(target: dict[str, Any], entrypoint: Path, workspace: Path,
                  output: Path, old_project: Path,
                  corrected_project: Path | None) -> dict[str, Any]:
    output.mkdir(parents=True)
    command = render_compile_command(target, entrypoint, workspace, output,
                                     old_project, corrected_project)
    if sha256(Path(command[0])) != CIRCOM_SHA256:
        raise ValueError("pinned circom binary changed")
    result = subprocess.run(command, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=600, check=False)
    r1cs = list(output.glob("*.r1cs"))
    row = {"exit_code": result.returncode, "r1cs_count": len(r1cs),
           "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
           "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
           "r1cs_sha256": sha256(r1cs[0]) if len(r1cs) == 1 else None,
           "r1cs_bytes": r1cs[0].stat().st_size if len(r1cs) == 1 else None}
    if result.returncode or len(r1cs) != 1:
        raise RuntimeError(f"R1CS compilation failed: {entrypoint}; exit={result.returncode}; "
                           f"files={len(r1cs)}; stderr={result.stderr[-1200:]}")
    return row


def prove_equivalence(output: Path) -> dict[str, Any]:
    _queue, whole, split, _plan, evidence, _units = load_staged(output)
    proof_path = output / "r1cs-equivalence.json"
    if proof_path.exists():
        raise FileExistsError(proof_path)
    old_project = ROOT / evidence["original_project"]
    new_project = ROOT / evidence["corrected_project"]
    pairs = [("W", whole["targets"][0], old_project,
              old_project / whole["targets"][0]["entrypoint_relative"],
              new_project, new_project / whole["targets"][0]["entrypoint_relative"])]
    for target, old_snapshot, new_snapshot in zip(
            split["targets"], split["source_snapshots"], evidence["snapshots"], strict=True):
        original = ROOT / new_snapshot["source"]
        corrected = ROOT / new_snapshot["corrected"]
        pairs.append(("S", target, original, original / target["entrypoint_relative"],
                      corrected, corrected / target["entrypoint_relative"]))
    proof = {"schema_version": 1, "kind": "n6_b2_pragma_r1cs_equivalence",
             "status": "in_progress", "created_at": now(),
             "circom_sha256": CIRCOM_SHA256, "expected_pairs": len(pairs),
             "pairs": [], "candidate_contents_opened": False,
             "campaign_executed": False}
    save(proof_path, proof)
    for method, target, old_workspace, old_entrypoint, new_workspace, new_entrypoint in pairs:
        row = {"method": method, "rank": target.get("rank"),
               "old_target_id": target["target_id"], "original_entrypoint": rel(old_entrypoint),
               "corrected_entrypoint": rel(new_entrypoint)}
        try:
            with tempfile.TemporaryDirectory(prefix="r1cs-pair-", dir=output) as temporary:
                temporary_root = Path(temporary)
                original_output = temporary_root / "original"
                corrected_output = temporary_root / "corrected"
                row["original"] = compile_r1cs(target, old_entrypoint, old_workspace,
                                                original_output, old_project, None)
                row["corrected"] = compile_r1cs(target, new_entrypoint, new_workspace,
                                                 corrected_output, old_project, new_project)
                original_r1cs = next(original_output.glob("*.r1cs"))
                corrected_r1cs = next(corrected_output.glob("*.r1cs"))
                row["byte_equal"] = filecmp.cmp(original_r1cs, corrected_r1cs, shallow=False)
                if not row["byte_equal"]:
                    raise ValueError(f"R1CS bytes differ: {method} {target['target_id']}")
            proof["pairs"].append(row)
            save(proof_path, proof, overwrite=True)
        except Exception as error:
            row["error"] = f"{type(error).__name__}: {error}"
            proof["pairs"].append(row)
            proof["status"] = "failed"
            proof["failed_target_id"] = target["target_id"]
            proof["failed_method"] = method
            save(proof_path, proof, overwrite=True)
            raise
    proof["status"] = "passed"
    save(proof_path, proof, overwrite=True)
    return proof


def stable_target_id(target: dict[str, Any]) -> str:
    """Mirror src/corpus.rs stable_target_id using original logical paths."""
    definition = target["definition"]
    inspection = target["inspection"]
    project = Path(inspection["project_root"])
    entrypoint = Path(inspection["entrypoint"])
    root = inspection["root"]

    def logical(value: str) -> str:
        path = Path(value)
        if path == entrypoint and path != Path(root["path"]):
            return "@entrypoint"
        if path == entrypoint and not path.is_relative_to(project):
            return "@external-entrypoint-root"
        return path.relative_to(project).as_posix()

    if set(inspection["dependency_paths"]) != {
            row["path"] for row in target["source_fingerprints"]}:
        raise ValueError("source identity dependency denominator differs")
    sources = sorted((logical(row["path"]), row["sha256"])
                     for row in target["source_fingerprints"])
    args = definition["compile_args"].copy()
    index = 0
    while index < len(args):
        if args[index] != "-l":
            index += 1
            continue
        index += 1
        while index < len(args) and not args[index].startswith("-"):
            path = Path(args[index])
            if path == project:
                args[index] = "@project-root/"
            elif path.is_relative_to(project):
                args[index] = str(Path("@project-root") / path.relative_to(project))
            index += 1
    descriptor = {
        "identity_version": 1,
        "project": definition["project"],
        "revision": definition["revision"],
        "root_source": logical(root["path"]),
        "root_template": root["template_name"],
        "parameters": root["concrete_parameters"],
        "sources": sources,
        "prime": definition["prime"],
        "compile_args": args,
        "mode": definition["mode"],
        "input_assumptions": definition["input_assumptions"],
    }
    if definition.get("input_contract") is not None:
        descriptor["input_contract"] = definition["input_contract"]
    canonical = json.dumps(descriptor, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def remap_paths(value: Any, old_project: Path, new_project: Path,
                old_wrapper: Path, new_wrapper: Path,
                old_snapshot: Path, new_snapshot: Path) -> Any:
    if isinstance(value, str):
        if value == str(old_wrapper):
            return str(new_wrapper)
        for original, corrected in ((old_project, new_project),
                                    (old_snapshot, new_snapshot)):
            if value == str(original) or value.startswith(str(original) + "/"):
                return str(corrected) + value[len(str(original)):]
        return value
    if isinstance(value, list):
        return [remap_paths(item, old_project, new_project, old_wrapper,
                            new_wrapper, old_snapshot, new_snapshot) for item in value]
    if isinstance(value, dict):
        return {key: remap_paths(item, old_project, new_project, old_wrapper,
                                 new_wrapper, old_snapshot, new_snapshot)
                for key, item in value.items()}
    return value


def build_plan(plan: dict[str, Any], split: dict[str, Any], evidence: dict[str, Any],
               output: Path) -> tuple[Path, list[dict[str, Any]]]:
    old_project = ROOT / evidence["original_project"]
    new_project = ROOT / evidence["corrected_project"]
    new_plan = deepcopy(plan)
    mapping = []
    for planned, target, snapshot_row in zip(
            new_plan["targets"], split["targets"], evidence["snapshots"], strict=True):
        old_id = planned["target_id"]
        if old_id != target["target_id"] or stable_target_id(planned) != old_id:
            raise ValueError(f"original target ID cannot be reproduced: {old_id}")
        old_snapshot = ROOT / snapshot_row["source"]
        new_snapshot = ROOT / snapshot_row["corrected"]
        old_wrapper = Path(planned["definition"]["entrypoint"])
        new_wrapper = new_snapshot / target["entrypoint_relative"]
        mapped = remap_paths(planned, old_project, new_project, old_wrapper,
                             new_wrapper, old_snapshot, new_snapshot)
        planned.clear()
        planned.update(mapped)
        planned["run_entrypoint"] = str(new_wrapper)
        for fingerprint in planned["source_fingerprints"]:
            source = Path(fingerprint["path"])
            if not source.is_file():
                raise ValueError(f"mapped source is missing: {source}")
            fingerprint["sha256"] = sha256(source)
        for fingerprint in planned["snapshot_fingerprints"]:
            source = Path(fingerprint["path"])
            if not source.is_file():
                raise ValueError(f"mapped snapshot source is missing: {source}")
            fingerprint["sha256"] = sha256(source)
        if sorted(row["sha256"] for row in planned["source_fingerprints"]) != sorted(
                row["sha256"] for row in planned["snapshot_fingerprints"]):
            raise ValueError(f"source/snapshot hashes differ: {old_id}")
        new_id = stable_target_id(planned)
        planned["target_id"] = new_id
        planned["ranking"]["target_id"] = new_id
        mapping.append({"rank": target["rank"], "old_target_id": old_id,
                        "new_target_id": new_id, "wrapper": rel(new_wrapper),
                        "wrapper_sha256": sha256(new_wrapper)})
    if len(mapping) != 305 or len({row["new_target_id"] for row in mapping}) != 305:
        raise ValueError("corrected target ID denominator/uniqueness differs")
    source_plan_path = Path(next(row["path"] for row in split["pinned_files"]
                                 if row["label"] == "plan"))
    new_plan["pragma_correction"] = {
        "source_plan": rel(source_plan_path),
        "source_plan_sha256": sha256(source_plan_path),
        "source_evidence": rel(output / "source-evidence.json"),
        "source_evidence_sha256": sha256(output / "source-evidence.json"),
        "r1cs_equivalence": rel(output / "r1cs-equivalence.json"),
        "r1cs_equivalence_sha256": sha256(output / "r1cs-equivalence.json"),
    }
    plan_path = output / "plan-pragma.json"
    save(plan_path, new_plan)
    save(output / "target-id-map.json", {"schema_version": 1, "status": "passed",
                                         "target_count": len(mapping), "mapping": mapping})
    return plan_path, mapping


def replace_project_path(value: Any, old_project: Path, new_project: Path) -> Any:
    if isinstance(value, str):
        if value == str(old_project) or value.startswith(str(old_project) + "/"):
            return str(new_project) + value[len(str(old_project)):]
        return value
    if isinstance(value, list):
        return [replace_project_path(item, old_project, new_project) for item in value]
    if isinstance(value, dict):
        return {key: replace_project_path(item, old_project, new_project)
                for key, item in value.items()}
    return value


def spec_differences(before: Any, after: Any, at: str = "") -> list[str]:
    if type(before) is not type(after):
        return [at]
    if isinstance(before, dict):
        return [path for key in sorted(set(before) | set(after))
                for path in spec_differences(before.get(key), after.get(key),
                                             f"{at}.{key}" if at else key)]
    if isinstance(before, list):
        if len(before) != len(after):
            return [at]
        return [path for index, (left, right) in enumerate(zip(before, after, strict=True))
                for path in spec_differences(left, right, f"{at}[{index}]")]
    return [] if before == after else [at]


def build_specs(output: Path) -> dict[str, Any]:
    _queue, whole, split, plan, evidence, units = load_staged(output)
    proof = json.loads((output / "r1cs-equivalence.json").read_text(encoding="utf-8"))
    if proof.get("status") != "passed" or len(proof.get("pairs", [])) != 306 or not all(
            row.get("byte_equal") is True for row in proof["pairs"]):
        raise ValueError("all W/S byte-equivalence proofs are required")
    plan_path, mapping = build_plan(plan, split, evidence, output)
    old_project = ROOT / evidence["original_project"]
    new_project = ROOT / evidence["corrected_project"]
    new_hashes = {row["old_target_id"]: row["new_target_id"] for row in mapping}
    snapshots = {row["id"]: row for row in evidence["snapshots"]}
    snapshot_hashes = {row["id"]: row["corrected_tree_sha256"]
                       for row in evidence["snapshots"]}
    project_tree_hash = evidence["corrected_project_tree_sha256"]
    rows = []
    for unit in units:
        for method, name in (("W", "whole"), ("S", "split")):
            original_path = ROOT / unit[f"{name}_spec"]
            original = checked_json(original_path, unit[f"{name}_spec_sha256"])
            spec = deepcopy(original)
            for snapshot in spec["source_snapshots"]:
                corrected = (new_project if method == "W"
                             else ROOT / snapshots[snapshot["id"]]["corrected"])
                snapshot["path"] = str(corrected)
                snapshot["tree_sha256"] = (project_tree_hash if method == "W" else
                                           snapshot_hashes[snapshot["id"]])
            for target in spec["targets"]:
                if method == "W":
                    target["entrypoint_sha256"] = sha256(
                        new_project / target["entrypoint_relative"])
                else:
                    old_id = target["target_id"]
                    target["target_id"] = new_hashes[old_id]
                    corrected = ROOT / snapshots[target["source_snapshot_id"]]["corrected"]
                    target["source_snapshot_path"] = str(corrected)
                    target["entrypoint_sha256"] = sha256(
                        corrected / target["entrypoint_relative"])
                for key in ("command", "preflight_compile_command",
                            "recorded_library_paths", "appended_original_library_paths"):
                    if key in target:
                        target[key] = replace_project_path(target[key], old_project, new_project)
            if method == "S":
                pin = next(row for row in spec["pinned_files"] if row["label"] == "plan")
                pin.update(path=str(plan_path), sha256=sha256(plan_path))
            destination = output / "specs" / f"{unit['unit_id']}-{method}.json"
            save(destination, spec)
            differences = spec_differences(original, spec)
            rows.append({"unit_id": unit["unit_id"], "method": method,
                         "source_spec": rel(original_path),
                         "source_spec_sha256": sha256(original_path),
                         "corrected_spec": rel(destination),
                         "corrected_spec_sha256": sha256(destination),
                         "difference_paths": differences})
    manifest = {"schema_version": 1, "kind": "n6_b2_pragma_specs",
                "status": "prepared_not_executed", "created_at": now(),
                "spec_count": len(rows), "target_id_map": rel(output / "target-id-map.json"),
                "target_id_map_sha256": sha256(output / "target-id-map.json"),
                "plan": rel(plan_path), "plan_sha256": sha256(plan_path),
                "rows": rows, "campaign_executed": False}
    if len(rows) != 6:
        raise ValueError("corrected spec denominator differs")
    save(output / "spec-manifest.json", manifest)
    return manifest


def load_parser_module():
    spec = importlib.util.spec_from_file_location("n6_b2_corrected_parser_probe", PARSER_MODULE)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load pinned parser probe module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scan_corrected_pragmas(roots: list[Path]) -> dict[str, Any]:
    """Conservative static proof: every Circom file in corrected trees is accepted."""
    versions: dict[str, int] = {}
    high = []
    files = 0
    for root in roots:
        for path in sorted(root.rglob("*.circom")):
            if not path.is_file():
                continue
            files += 1
            for match in PRAGMA_VERSION.finditer(path.read_bytes()):
                version = tuple(int(part) for part in match.groups())
                spelling = ".".join(str(part) for part in version)
                versions[spelling] = versions.get(spelling, 0) + 1
                if version > PARSER_VERSION:
                    high.append({"file": rel(path), "version": spelling})
    return {"status": "passed" if not high else "failed",
            "parser_version": ".".join(str(part) for part in PARSER_VERSION),
            "source_tree_count": len(roots), "circom_file_count": files,
            "pragma_version_counts": dict(sorted(versions.items())),
            "files_exceeding_parser": high}


def corrected_parser_plan(output: Path, manifest: dict[str, Any],
                          units: list[dict[str, Any]], parser_module) -> list[dict[str, Any]]:
    if manifest.get("status") != "prepared_not_executed" or manifest.get("spec_count") != 6:
        raise ValueError("six corrected specs are required before parser re-probe")
    by_key = {(row["unit_id"], row["method"]): row for row in manifest["rows"]}
    if len(by_key) != 6:
        raise ValueError("corrected spec keys are not unique")
    plan = []
    for method in ("W", "S"):
        identities = []
        representative = None
        representative_row = None
        for unit in units:
            row = by_key[unit["unit_id"], method]
            spec_path = ROOT / row["corrected_spec"]
            spec = checked_json(spec_path, row["corrected_spec_sha256"])
            identities.append(parser_module.identity_sha256(spec))
            if representative is None:
                representative, representative_row = spec, row
        if len(set(identities)) != 1:
            raise ValueError(f"corrected {method} parser sources or commands differ across seeds")
        assert representative is not None and representative_row is not None
        snapshots = {snapshot["id"]: Path(snapshot["path"])
                     for snapshot in representative["source_snapshots"]}
        for index, target in enumerate(representative["targets"]):
            workspace = snapshots[target["source_snapshot_id"]]
            entrypoint = workspace / target["entrypoint_relative"]
            if not entrypoint.is_file() or sha256(entrypoint) != target["entrypoint_sha256"]:
                raise ValueError(f"corrected parser entrypoint changed: {method}:{index}")
            command = [token.replace("{workspace}", str(workspace)).replace(
                "{entrypoint}", str(entrypoint)) for token in target["command"]]
            if (not command or Path(command[0]) != parser_module.ZKFUZZ
                    or "{" in " ".join(command)):
                raise ValueError(f"unsupported corrected parser command: {method}:{index}")
            plan.append({"method": method, "target_index": index,
                         "target_id": target["target_id"],
                         "spec": representative_row["corrected_spec"],
                         "spec_sha256": representative_row["corrected_spec_sha256"],
                         "entrypoint_sha256": target["entrypoint_sha256"],
                         "command": command})
    if len(plan) != 306 or [row["method"] for row in plan].count("W") != 1:
        raise ValueError("corrected parser target denominator differs")
    return plan


def parser_result_allowed(result: dict[str, Any], static_status: str) -> bool:
    return (result.get("status") == "accepted" or
            (result.get("status") == "parse_unconfirmed" and static_status == "passed"))


def parser_ledger_complete(ledger: dict[str, Any], manifest_sha: str,
                           static_sha: str) -> bool:
    rows = ledger.get("targets", [])
    return (ledger.get("status") == "passed"
            and ledger.get("expected_target_count") == 306
            and len(rows) == 306
            and ledger.get("spec_manifest_sha256") == manifest_sha
            and ledger.get("static_pragma_sha256") == static_sha
            and ledger.get("accepted_count") == sum(
                row.get("status") == "accepted" for row in rows)
            and ledger.get("parse_unconfirmed_count") == sum(
                row.get("status") == "parse_unconfirmed" for row in rows)
            and all(parser_result_allowed(row, row.get("static_pragma_status"))
                    for row in rows))


def corrected_parser_check(output: Path, calibration: Path,
                           ledger_path: Path | None = None) -> dict[str, Any]:
    _queue, _whole, _split, _plan, evidence, units = load_staged(output)
    manifest_path = output / "spec-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parser_module = load_parser_module()
    if sha256(parser_module.ZKFUZZ) != parser_module.ZKFUZZ_SHA256:
        raise ValueError("pinned zkFuzz changed")
    calibration_data = json.loads(calibration.read_text(encoding="utf-8"))
    if (calibration_data.get("status") != "passed"
            or calibration_data.get("marker") != parser_module.MARKER.decode("ascii")
            or calibration_data.get("zkfuzz_sha256") != parser_module.ZKFUZZ_SHA256):
        raise ValueError("parser control marker has not been established")
    roots = [ROOT / evidence["corrected_project"]]
    roots.extend(ROOT / row["corrected"] for row in evidence["snapshots"])
    static_path = output / "parser-static-corrected.json"
    static = scan_corrected_pragmas(roots)
    static.update({"schema_version": 1, "kind": "n6_b2_pragma_corrected_static",
                   "created_at": now(), "source_evidence_sha256":
                   sha256(output / "source-evidence.json")})
    if static_path.exists():
        if json.loads(static_path.read_text(encoding="utf-8")) != static:
            # created_at varies; compare only the deterministic evidence fields.
            old = json.loads(static_path.read_text(encoding="utf-8"))
            if {key: value for key, value in old.items() if key != "created_at"} != {
                    key: value for key, value in static.items() if key != "created_at"}:
                raise ValueError("corrected static pragma evidence changed")
    else:
        save(static_path, static)
    if static["status"] != "passed":
        raise ValueError("corrected source still requires a pragma above zkFuzz parser 2.2.1")
    plan = corrected_parser_plan(output, manifest, units, parser_module)
    plan_sha = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")
                                     ).encode()).hexdigest()
    ledger_path = (ledger_path or output / "parser-check.json").resolve()
    if ledger_path.parent != output.resolve() or ledger_path.suffix != ".json":
        raise ValueError("parser ledger must be a JSON file directly inside versioned output")
    expected_header = {"schema_version": 1, "kind": "n6_b2_pragma_corrected_parser_check",
                       "spec_manifest_sha256": sha256(manifest_path),
                       "static_pragma": rel(static_path),
                       "static_pragma_sha256": sha256(static_path),
                       "calibration": rel(calibration),
                       "calibration_sha256": sha256(calibration),
                       "zkfuzz_sha256": parser_module.ZKFUZZ_SHA256,
                       "plan_sha256": plan_sha, "expected_target_count": 306,
                       "max_seconds_per_target": parser_module.MAX_SECONDS,
                       "physical_cap_bytes": parser_module.CAP_BYTES,
                       "campaign_executed": False}
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        for key, value in expected_header.items():
            if ledger.get(key) != value:
                raise ValueError(f"parser ledger input changed: {key}")
        if ledger.get("status") == "passed":
            if not parser_ledger_complete(ledger, sha256(manifest_path), sha256(static_path)):
                raise ValueError("completed parser ledger is inconsistent")
            return ledger
        if ledger.get("status") != "in_progress":
            raise ValueError("failed parser ledger needs investigation")
        if len(ledger.get("targets", [])) > len(plan):
            raise ValueError("parser ledger has more rows than the plan")
        for index, row in enumerate(ledger["targets"]):
            planned = plan[index]
            if (row.get("method") != planned["method"]
                    or row.get("target_id") != planned["target_id"]
                    or row.get("target_index") != planned["target_index"]
                    or row.get("spec_sha256") != planned["spec_sha256"]
                    or row.get("entrypoint_sha256") != planned["entrypoint_sha256"]
                    or not parser_result_allowed(row, static["status"])):
                raise ValueError("parser ledger cannot be safely resumed")
        if (ledger.get("accepted_count") != sum(
                row.get("status") == "accepted" for row in ledger["targets"])
                or ledger.get("parse_unconfirmed_count") != sum(
                    row.get("status") == "parse_unconfirmed" for row in ledger["targets"])):
            raise ValueError("parser ledger status counts changed")
    else:
        ledger = {**expected_header, "status": "in_progress", "created_at": now(),
                  "targets": [], "accepted_count": 0, "parse_unconfirmed_count": 0}
        save(ledger_path, ledger)
    for index in range(len(ledger["targets"]), len(plan)):
        target = plan[index]
        result = parser_module.run_probe(target["command"], temporary_root=output)
        row = {key: value for key, value in target.items() if key != "command"}
        row.update(result)
        row["static_pragma_status"] = static["status"]
        ledger["targets"].append(row)
        if result["status"] == "accepted":
            ledger["accepted_count"] += 1
        elif result["status"] == "parse_unconfirmed":
            ledger["parse_unconfirmed_count"] += 1
        if not parser_result_allowed(result, static["status"]):
            ledger["status"] = "failed"
            ledger["failed_target_index"] = index
            save(ledger_path, ledger, overwrite=True)
            raise ValueError(f"corrected parser probe failed: {target['method']}:{index}:"
                             f"{result['status']}")
        save(ledger_path, ledger, overwrite=True)
    ledger["status"] = "passed"
    save(ledger_path, ledger, overwrite=True)
    if not parser_ledger_complete(ledger, sha256(manifest_path), sha256(static_path)):
        raise ValueError("completed parser ledger is inconsistent")
    return ledger


def preflight_queue(output: Path, parser_ledger: Path | None = None) -> dict[str, Any]:
    queue, units, _whole, _split, _plan = source_inputs()
    manifest = json.loads((output / "spec-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "prepared_not_executed" or manifest.get("spec_count") != 6:
        raise ValueError("corrected specs are not complete")
    parser_check_path = (parser_ledger or output / "parser-check.json").resolve()
    if parser_check_path.parent != output.resolve() or parser_check_path.suffix != ".json":
        raise ValueError("parser ledger must be a JSON file directly inside versioned output")
    parser_check = json.loads(parser_check_path.read_text(encoding="utf-8"))
    static_path = output / "parser-static-corrected.json"
    static_record = json.loads(static_path.read_text(encoding="utf-8"))
    if (static_record.get("status") != "passed"
            or parser_check.get("static_pragma") != rel(static_path)
            or not parser_ledger_complete(parser_check,
                                          sha256(output / "spec-manifest.json"),
                                          sha256(static_path))):
        raise ValueError("corrected parser acceptance evidence is incomplete")
    manifest_rows = {(row["unit_id"], row["method"]): row for row in manifest["rows"]}
    source_proof_ref = queue["preflight_reuse"]
    original_proof = checked_json(ROOT / source_proof_ref["path"], source_proof_ref["sha256"])
    proof_rows = deepcopy(original_proof["rows"])
    corrected_units = []
    for source_unit in units:
        unit = deepcopy(source_unit)
        for method, name in (("W", "whole"), ("S", "split")):
            row = manifest_rows[unit["unit_id"], method]
            spec_path = ROOT / row["corrected_spec"]
            if sha256(spec_path) != row["corrected_spec_sha256"]:
                raise ValueError(f"corrected spec changed: {spec_path}")
            preflight_output = output / "preflight" / unit["unit_id"] / method
            ledger_path = preflight_output / "preflight.json"
            if not preflight_output.exists():
                result = subprocess.run(
                    [sys.executable, str(ENGINE), "preflight", "--spec", str(spec_path),
                     "--output", str(preflight_output)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, check=False)
                if result.returncode or not ledger_path.is_file():
                    raise RuntimeError(f"fresh preflight failed: {unit['unit_id']}:{method}; "
                                       f"exit={result.returncode}; stderr={result.stderr[-1200:]}")
            elif not ledger_path.is_file():
                raise ValueError(f"existing preflight output is incomplete: {preflight_output}")
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            if ledger.get("status") != "passed" or ledger.get("spec_sha256") != sha256(spec_path):
                raise ValueError(f"fresh preflight did not pass: {unit['unit_id']}:{method}")
            unit[f"{name}_spec"] = rel(spec_path)
            unit[f"{name}_spec_sha256"] = sha256(spec_path)
            proof_rows[f"{unit['unit_id']}:{method}"] = {
                "status": "passed", "preflight_kind": "fresh_parser_correction",
                "source_spec": rel(spec_path), "source_spec_sha256": sha256(spec_path),
                "destination_spec": rel(spec_path),
                "destination_spec_sha256": sha256(spec_path),
                "source_preflight": rel(ledger_path),
                "source_preflight_sha256": sha256(ledger_path),
                "destination_preflight": rel(ledger_path),
                "destination_preflight_sha256": sha256(ledger_path),
            }
        corrected_units.append(unit)
    if len(proof_rows) != 60:
        raise ValueError("final preflight denominator differs")
    proof = {"schema_version": 1, "kind": "n6_b2_parser_correction_preflight_proof",
             "status": "passed", "created_at": now(), "required_spec_count": 60,
             "recorded_spec_count": len(proof_rows), "source_queue": rel(SOURCE_QUEUE),
             "source_queue_sha256": SOURCE_QUEUE_SHA256,
             "corrected_parser_check": rel(parser_check_path),
             "corrected_parser_check_sha256": sha256(parser_check_path),
             "rows": proof_rows}
    proof_path = output / "preflight-proof.json"
    save(proof_path, proof)
    by_id = {unit["unit_id"]: unit for unit in corrected_units}
    final = deepcopy(queue)
    final["task"] = "N6-B Policy-A v4 execute, versioned pragma correction"
    final["created_at"] = now()
    final["units"] = [by_id.get(unit["unit_id"], unit) for unit in queue["units"]]
    final["preflight_reuse"] = {"path": rel(proof_path), "sha256": sha256(proof_path)}
    final["source_queues"] = [{"path": rel(SOURCE_QUEUE), "sha256": SOURCE_QUEUE_SHA256}]
    final_path = output / "queue-b-pragma.json"
    save(final_path, final)
    validation = subprocess.run(
        [sys.executable, str(QUEUE_RUNNER), "--queue", str(final_path),
         "--action", "validate-only"], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if validation.returncode:
        raise RuntimeError(f"v4.3 validate-only failed: {validation.stderr[-1200:]}")
    response = json.loads(validation.stdout)
    if (response.get("status") != "valid"
            or response.get("queue_sha256") != sha256(final_path)):
        raise ValueError("v4.3 validation response disagrees with queue")
    result = {"schema_version": 1, "kind": "n6_b2_pragma_final_queue",
              "status": "prepared_not_executed", "created_at": now(),
              "queue": rel(final_path), "queue_sha256": sha256(final_path),
              "unit_count": 30, "spec_count": 60, "corrected_unit_count": 3,
              "corrected_spec_count": 6, "preflight_proof": rel(proof_path),
              "preflight_proof_sha256": sha256(proof_path),
              "corrected_parser_check": rel(parser_check_path),
              "corrected_parser_check_sha256": sha256(parser_check_path),
              "validate_only": response, "campaign_executed": False}
    save(output / "final-queue.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True,
                        choices=("sources", "equivalence", "specs", "parser-check",
                                 "preflight-queue"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--calibration", type=Path, default=PARSER_CALIBRATION)
    parser.add_argument("--p1003-ledger", type=Path, default=P1003_LEDGER)
    parser.add_argument("--parser-ledger", type=Path,
                        help="versioned corrected parser ledger; used by parser-check and preflight-queue")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT.resolve() / "runs"):
        raise ValueError("versioned output must be under ignored runs/")
    if args.action == "sources":
        result = stage_sources(output, args.p1003_ledger.resolve())
        summary = {"status": result["status"],
                   "project_pragma_files": result["project_pragma_files"],
                   "snapshot_pragma_files": result["snapshot_pragma_files"],
                   "wrapper_include_rewrites": result["wrapper_include_rewrites"]}
    elif args.action == "equivalence":
        result = prove_equivalence(output)
        summary = {"status": result["status"], "pairs": len(result["pairs"])}
    elif args.action == "specs":
        result = build_specs(output)
        summary = {"status": result["status"], "spec_count": result["spec_count"]}
    elif args.action == "parser-check":
        result = corrected_parser_check(output, args.calibration.resolve(),
                                        args.parser_ledger)
        summary = {"status": result["status"], "targets": len(result["targets"]),
                   "accepted": result["accepted_count"],
                   "parse_unconfirmed": result["parse_unconfirmed_count"]}
    else:
        result = preflight_queue(output, args.parser_ledger)
        summary = {"status": result["status"], "queue": result["queue"],
                   "queue_sha256": result["queue_sha256"]}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
