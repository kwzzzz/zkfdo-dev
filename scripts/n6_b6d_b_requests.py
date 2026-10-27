#!/usr/bin/env python3
"""Build B6d A-shaped source units and gated request indexes without J execution.

Only source and request path/hash metadata is read. Candidate, witness, and
judgement files are never opened. All outputs are new and created exclusively.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from n6_j1_requests import CIRCOM, CIRCOM_SHA, sha256_file


ROOT = Path(__file__).resolve().parents[1]
VOLUME = Path("/Volumes/zkfdo-jcache")
EXTERNAL = VOLUME / "n6-b6d-batch1x"
UNITS = EXTERNAL / "units"
R1CS_CACHE = EXTERNAL / "r1cs-equivalence"
OUT = ROOT / "runs/n6-b6d-2026-10-20.noindex"
MANIFEST = OUT / "unit-staging-manifest.json"
R1CS_EVIDENCE = OUT / "r1cs-equivalence.json"
SOURCE_COPY_AUDIT = OUT / "source-copy-audit.json"
GATE = OUT / "equivalence-gate-v1.json"
PLAN_OUT = OUT / "request-index-pending.json"
INDEX_OUT = OUT / "request-index-v1.json"
INDEX_V22_OUT = OUT / "request-index-v2.2.json"
REQUEST_ROOT = OUT / "requests"
B6B = ROOT / "runs/n6-b6b-2026-10-19.noindex"
SOURCE_PLAN = B6B / "batch1x-prep.noindex/request-index-pending.json"
SOURCE_INDEX = B6B / "batch1x-prep.noindex/request-index-v1.json"
SOURCE_INDEX_V22 = B6B / "batch1x-prep.noindex/request-index-v2.2.json"
ORIGINAL_R1CS = B6B / "r1cs-comparison.json"
A_INDEX = ROOT / "runs/n6-j1-2026-10-09.noindex/request-index.json"
A_CLOSURE = OUT / "a-closure-audit-v2.json"
B_CLOSURE = OUT / "b-closure-equivalence-v1.json"
SOURCE_INDEX_SHA = "1bfcb71d728fe77ccdec0e8897a5a085ea9d286ed658ea160f6cc9fe1fe83b65"
SOURCE_INDEX_V22_SHA = "b611e949b2b15e43afda188511e3308864849542682932d1db0e159970262ba5"
ORIGINAL_R1CS_SHA = "d1a6b0fc8d8f3fa46663a7ef651f36d3405302ff3a422ed661c893c65ab59ace"
EXPECTED_REQUESTS = 107
EXPECTED_PAIRS = 17
MIN_FREE_BYTES = 40 * 1024**3
INCLUDE = re.compile(rb'\binclude\s*"([^"\r\n]+)"\s*;')


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def write_new(path: Path, value: dict[str, Any]) -> str:
    require(not path.exists(), f"refuse to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return sha256_file(path)


def source_rows() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    require(sha256_file(SOURCE_INDEX) == SOURCE_INDEX_SHA,
            "B6b request index SHA changed")
    plan = read_json(SOURCE_PLAN)
    index = read_json(SOURCE_INDEX)
    planned = plan.get("requests")
    rows = index.get("requests")
    require(plan.get("request_count") == EXPECTED_REQUESTS and
            index.get("request_count") == EXPECTED_REQUESTS and
            isinstance(planned, list) and len(planned) == EXPECTED_REQUESTS and
            isinstance(rows, list) and len(rows) == EXPECTED_REQUESTS and
            plan.get("status") == "awaiting_base_input" and
            index.get("status") == "verified" and
            index.get("plan_index_sha256") == sha256_file(SOURCE_PLAN),
            "B6b source plan/index invalid")
    by_request = {row["request"]: row for row in planned}
    require(len(by_request) == EXPECTED_REQUESTS,
            "B6b source request paths repeated")
    joined = []
    for offset, row in enumerate(rows):
        require(row.get("queue_order") == offset and
                row.get("request") in by_request and
                row.get("preparation_failure") is None,
                "B6b request order or readiness changed")
        planned_row = by_request[row["request"]]
        require(row["revision_id"] == planned_row["revision_id"] and
                row["component_wrapper_sha256"] ==
                planned_row["component_wrapper_sha256"] and
                row["original_component_wrapper"] ==
                planned_row["original_component_wrapper"],
                "B6b index and plan source binding differ")
        joined.append(planned_row)
    return plan, index, joined


def clone_root(entrypoint: Path, b6b_source_root: Path) -> Path:
    source_manifest = read_json(b6b_source_root / "source-staging.json")
    root = Path(source_manifest["project_root"]).resolve()
    require(root.name == "clone" and entrypoint.resolve().is_relative_to(root),
            "original entrypoint outside clone")
    return root


def project_circom_files(root: Path) -> list[Path]:
    """Inspect only one index-named clone, as B6b did, without following links."""
    result = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names
                          if not (Path(directory) / name).is_symlink())
        for name in sorted(filenames):
            path = Path(directory) / name
            if path.suffix == ".circom":
                require(path.is_file(), f"clone Circom file unreadable: {path}")
                result.append(path)
    return result


def rewrite_includes(data: bytes, *, clone: Path, project: Path,
                     original: Path, staged: Path) -> tuple[bytes, list[dict[str, Any]]]:
    """Change only absolute include target bytes that canonically name the clone."""
    edits = []
    for match in INCLUDE.finditer(data):
        raw = os.fsdecode(match.group(1))
        target = Path(raw)
        if not target.is_absolute():
            continue
        canonical = target.resolve()
        if not canonical.is_relative_to(clone):
            continue
        require(canonical.is_file(), f"absolute include target absent: {target}")
        mapped = project / canonical.relative_to(clone)
        replacement = os.fsencode(str(mapped))
        line = data.count(b"\n", 0, match.start()) + 1
        edits.append({"scope": "wrapper" if staged.is_relative_to(project.parent / "preparation")
                      else "project", "original_file": str(original),
                      "staged_file": str(staged), "line": line,
                      "original_include": raw, "staged_include": str(mapped),
                      "span": (match.start(1), match.end(1), replacement)})
    output = data
    for edit in reversed(edits):
        start, end, replacement = edit["span"]
        output = output[:start] + replacement + output[end:]
    for edit in edits:
        del edit["span"]
    original_lines = data.splitlines(keepends=True)
    staged_lines = output.splitlines(keepends=True)
    require(len(original_lines) == len(staged_lines), "include rewrite changed line count")
    edited_lines = {edit["line"] for edit in edits}
    for line, (before, after) in enumerate(zip(original_lines, staged_lines), start=1):
        if line not in edited_lines:
            require(before == after, "non-include source bytes changed")
        else:
            require(INCLUDE.search(before) is not None and
                    INCLUDE.search(after) is not None,
                    "include rewrite changed non-include line")
    return output, edits


def pair_specs(joined: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: dict[str, dict[str, Any]] = {}
    for row in joined:
        old_root = Path(row["source_root"]).resolve()
        source_manifest = read_json(old_root / "source-staging.json")
        clone = clone_root(Path(row["original_entrypoint"]), old_root)
        preparation_source = Path(source_manifest["wrapper_root"]).resolve()
        original_wrapper = Path(row["original_component_wrapper"]).resolve()
        require(original_wrapper.is_relative_to(preparation_source),
                "wrapper outside preparation snapshot")
        pair_key = old_root.name
        pair_id = f"{row['revision_id']}-{pair_key}"
        unit = UNITS / pair_id
        project = unit / "project"
        preparation = unit / "preparation"
        wrapper = preparation / original_wrapper.relative_to(preparation_source)
        entrypoint = project / Path(row["original_entrypoint"]).resolve().relative_to(clone)
        old_libraries = list(row["library_paths"])
        libraries = []
        external = []
        for old in old_libraries:
            path = Path(old).resolve()
            require(path.is_dir(), f"original library missing: {path}")
            if path.is_relative_to(clone):
                libraries.append(str(project / path.relative_to(clone)))
            else:
                libraries.append(str(path))
                external.append(str(path))
        spec = {"pair_id": pair_id, "revision_id": row["revision_id"],
                "queue_orders": [], "source_root": str(unit),
                "original_clone_root": str(clone), "project_root": str(project),
                "original_preparation_root": str(preparation_source),
                "preparation_root": str(preparation),
                "original_entrypoint": row["original_entrypoint"],
                "entrypoint": str(entrypoint),
                "original_wrapper": row["original_component_wrapper"],
                "wrapper": str(wrapper),
                "original_library_paths": old_libraries,
                "library_paths": libraries,
                "external_library_paths": external,
                "original_wrapper_sha256": row["component_wrapper_sha256"],
                "entrypoint_sha256": row["entrypoint_sha256"]}
        if pair_id not in pairs:
            pairs[pair_id] = spec
        else:
            require(pairs[pair_id] == spec or
                    {k: v for k, v in pairs[pair_id].items() if k != "queue_orders"} ==
                    {k: v for k, v in spec.items() if k != "queue_orders"},
                    "pair binding differs among requests")
        pairs[pair_id]["queue_orders"].append(row["queue_order"])
    require(len(pairs) == EXPECTED_PAIRS and
            sorted(order for pair in pairs.values() for order in pair["queue_orders"]) ==
            list(range(EXPECTED_REQUESTS)), "17 pairs do not cover all 107 requests")
    return sorted(pairs.values(), key=lambda pair: min(pair["queue_orders"]))


def stage() -> dict[str, Any]:
    require(os.path.ismount(VOLUME), "external B6d volume is not mounted")
    require(not MANIFEST.exists() and not UNITS.exists(),
            "refuse to overwrite B6d source units or manifest")
    require(shutil.disk_usage(VOLUME).free >= MIN_FREE_BYTES,
            "external volume below runner free-space minimum")
    _, _, joined = source_rows()
    specs = pair_specs(joined)
    require(all(not Path(pair["source_root"]).exists() for pair in specs),
            "B6d unit path already exists")
    UNITS.mkdir(parents=True, exist_ok=False)
    for pair in specs:
        clone = Path(pair["original_clone_root"])
        project = Path(pair["project_root"])
        unit = Path(pair["source_root"])
        wrapper = Path(pair["wrapper"])
        unit.mkdir(parents=True, exist_ok=False)
        project.mkdir(exist_ok=False)
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        project_files = []
        rewrites = []
        for source in project_circom_files(clone):
            relative = source.relative_to(clone)
            staged = project / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            source_data = source.read_bytes()
            staged_data, edits = rewrite_includes(
                source_data, clone=clone, project=project,
                original=source, staged=staged)
            with staged.open("xb") as stream:
                stream.write(staged_data)
            original_sha = hashlib.sha256(source_data).hexdigest()
            staged_sha = hashlib.sha256(staged_data).hexdigest()
            require(sha256_file(staged) == staged_sha,
                    "project copy SHA changed during write")
            project_files.append({"path": str(relative),
                                  "original_sha256": original_sha,
                                  "staged_sha256": staged_sha})
            rewrites.extend(edits)
        original_wrapper = Path(pair["original_wrapper"])
        original_data = original_wrapper.read_bytes()
        require(hashlib.sha256(original_data).hexdigest() ==
                pair["original_wrapper_sha256"],
                "original wrapper SHA differs from B6b source plan")
        staged_data, edits = rewrite_includes(
            original_data, clone=clone, project=project,
            original=original_wrapper, staged=wrapper)
        require(len(edits) == 1, "S wrapper does not have one clone absolute include")
        with wrapper.open("xb") as stream:
            stream.write(staged_data)
        pair["wrapper_sha256"] = sha256_file(wrapper)
        rewrites.extend(edits)
        pair["project_files"] = project_files
        pair["include_rewrites"] = rewrites
        require(sha256_file(Path(pair["entrypoint"])) == pair["entrypoint_sha256"],
                "entrypoint project copy differs")
        require(all(Path(path).is_dir() for path in pair["library_paths"]),
                "relocated library path missing")
        pair["circom_file_count"] = len(project_files) + 1
        pair["circom_byte_count"] = sum((project / item["path"]).stat().st_size
                                        for item in project_files) + wrapper.stat().st_size
    a_index = read_json(A_INDEX)
    a_row = a_index["requests"][0]
    a_request = read_json(Path(a_row["request"]))
    a_unit = Path(a_request["source_root"])
    require(a_unit.name == a_row["revision_id"] and
            Path(a_request["entrypoint"]).is_relative_to(a_unit / "project") and
            Path(a_request["component_wrapper"]).is_relative_to(
                a_unit / "preparation"), "A unit example layout differs")
    manifest = {"schema": "n6-b6d-unit-staging-v1", "schema_version": 1,
                "request_count": EXPECTED_REQUESTS, "pair_count": EXPECTED_PAIRS,
                "a_unit_reference": {"index": str(A_INDEX),
                                     "index_sha256": sha256_file(A_INDEX),
                                     "source_root": str(a_unit),
                                     "project_root": str(a_unit / "project"),
                                     "preparation_root": str(a_unit / "preparation")},
                "source_plan": str(SOURCE_PLAN),
                "source_plan_sha256": sha256_file(SOURCE_PLAN),
                "source_index": str(SOURCE_INDEX),
                "source_index_sha256": SOURCE_INDEX_SHA,
                "units_root": str(UNITS), "pairs": specs}
    write_new(MANIFEST, manifest)
    return manifest


def verify_stage(manifest: dict[str, Any]) -> dict[str, Any]:
    require(manifest.get("schema") == "n6-b6d-unit-staging-v1" and
            manifest.get("request_count") == EXPECTED_REQUESTS and
            manifest.get("pair_count") == EXPECTED_PAIRS and
            manifest.get("source_index_sha256") == SOURCE_INDEX_SHA and
            len(manifest.get("pairs", [])) == EXPECTED_PAIRS,
            "B6d staging manifest invalid")
    project_changed = []
    wrapper_changed = []
    file_count = 0
    for pair in manifest["pairs"]:
        unit = Path(pair["source_root"])
        clone = Path(pair["original_clone_root"])
        project = Path(pair["project_root"])
        wrapper = Path(pair["wrapper"])
        require(unit.is_relative_to(UNITS) and unit.is_dir() and
                wrapper.is_file() and not wrapper.is_symlink(),
                "unit or wrapper invalid")
        expected = {str(Path("project") / item["path"])
                    for item in pair["project_files"]}
        expected.add(str(wrapper.relative_to(unit)))
        actual = set()
        for directory, names, filenames in os.walk(unit, followlinks=False):
            require(all(not (Path(directory) / name).is_symlink() for name in names),
                    "unit directory symlink forbidden")
            for name in filenames:
                path = Path(directory) / name
                require(path.is_file() and not path.is_symlink(),
                        "unit file symlink or special file forbidden")
                actual.add(str(path.relative_to(unit)))
        require(actual == expected, "unit file set differs from manifest")
        for item in pair["project_files"]:
            source = clone / item["path"]
            staged = project / item["path"]
            require(source.is_file() and staged.is_file() and
                    sha256_file(source) == item["original_sha256"] and
                    sha256_file(staged) == item["staged_sha256"],
                    "project file SHA differs from manifest")
            if item["original_sha256"] != item["staged_sha256"]:
                project_changed.append(str(staged))
            file_count += 1
        require(sha256_file(Path(pair["original_wrapper"])) ==
                pair["original_wrapper_sha256"] and
                sha256_file(wrapper) == pair["wrapper_sha256"],
                "S wrapper SHA differs from manifest")
        wrapper_changed.append(str(wrapper))
        require(len([edit for edit in pair["include_rewrites"]
                     if edit["scope"] == "wrapper"]) == 1,
                "wrapper rewrite count differs")
        require(all(Path(path).is_dir() for path in pair["library_paths"]),
                "unit library directory missing")
    return {"e4_passed": True, "project_file_count": file_count,
            "project_changed_files": project_changed,
            "wrapper_changed_files": wrapper_changed}


def component_command(wrapper: Path, output: Path, unit: Path,
                      libraries: list[str]) -> list[str]:
    command = [str(CIRCOM), str(wrapper), "--r1cs", "--sym", "--prime", "bn128",
               "-o", str(output), "-l", str(unit)]
    for library in libraries:
        command.extend(("-l", library))
    return command + ["--wasm", "--O0"]


def sandbox_profile(clone: Path, cache: Path) -> tuple[Path | None, str]:
    executable = shutil.which("sandbox-exec")
    if not executable:
        return None, "sandbox-exec unavailable"
    profile = cache / "sandbox.sb"
    require(not profile.exists(), "sandbox profile already exists")
    # The process can use its compiler/runtime files, but not the old clone.
    profile.write_text('(version 1)\n(allow default)\n'
                       f'(deny file-read* (subpath "{clone}"))\n', encoding="utf-8")
    trial = subprocess.run([executable, "-f", str(profile), "/usr/bin/true"],
                           capture_output=True, check=False, timeout=10)
    if trial.returncode:
        return (None, "sandbox-exec profile unavailable: " +
                trial.stderr.decode(errors="replace")[:200])
    return profile, "sandbox-exec clone read denied"


def r1cs_equivalence() -> dict[str, Any]:
    require(MANIFEST.is_file() and not R1CS_EVIDENCE.exists() and
            not R1CS_CACHE.exists(), "B6d R1CS evidence/cache already exists")
    require(os.path.ismount(VOLUME) and
            shutil.disk_usage(VOLUME).free >= MIN_FREE_BYTES,
            "external cache volume unavailable or below minimum")
    require(CIRCOM.is_file() and sha256_file(CIRCOM) == CIRCOM_SHA,
            "fixed Circom SHA changed")
    require(sha256_file(ORIGINAL_R1CS) == ORIGINAL_R1CS_SHA,
            "B6b original R1CS evidence SHA changed")
    manifest = read_json(MANIFEST)
    e4 = verify_stage(manifest)
    original = read_json(ORIGINAL_R1CS)
    original_pairs = {f"{row['revision_id']}-{row['stage_key']}": row
                      for row in original["pairs"]}
    require(original.get("status") == "matched" and
            len(original_pairs) == EXPECTED_PAIRS,
            "B6b original R1CS comparisons incomplete")
    R1CS_CACHE.mkdir(parents=True, exist_ok=False)
    pairs = []
    all_matched = True
    for pair in manifest["pairs"]:
        pair_id = pair["pair_id"]
        require(pair_id in original_pairs, "B6d pair absent from original R1CS")
        cache = R1CS_CACHE / pair_id
        cache.mkdir(exist_ok=False)
        clone = Path(pair["original_clone_root"])
        profile, sandbox_note = sandbox_profile(clone, cache)
        output = cache / "compiled"
        output.mkdir(exist_ok=False)
        command = component_command(Path(pair["wrapper"]), output,
                                    Path(pair["source_root"]), pair["library_paths"])
        if profile:
            command = [shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec",
                       "-f", str(profile), *command]
        started = time.monotonic()
        with (cache / "compile.log").open("x") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                    check=False, timeout=600)
        r1cs = output / f"{Path(pair['wrapper']).stem}.r1cs"
        staged_sha = sha256_file(r1cs) if r1cs.is_file() else None
        original_sha = original_pairs[pair_id]["original"]["r1cs_sha256"]
        match = result.returncode == 0 and staged_sha == original_sha
        pairs.append({"pair_id": pair_id, "revision_id": pair["revision_id"],
                      "queue_orders": pair["queue_orders"],
                      "original_r1cs_sha256": original_sha,
                      "staged_r1cs_sha256": staged_sha, "match": match,
                      "compile_exit_code": result.returncode,
                      "wall_seconds": round(time.monotonic() - started, 3),
                      "sandbox": sandbox_note,
                      "compile_log": str(cache / "compile.log"),
                      "compile_log_sha256": sha256_file(cache / "compile.log")})
        all_matched &= match
        if not match:
            break
    report = {"schema": "n6-b6d-r1cs-equivalence-v1", "schema_version": 1,
              "request_count": EXPECTED_REQUESTS, "pair_count": EXPECTED_PAIRS,
              "unit_manifest": str(MANIFEST),
              "unit_manifest_sha256": sha256_file(MANIFEST),
              "original_r1cs_evidence": str(ORIGINAL_R1CS),
              "original_r1cs_evidence_sha256": ORIGINAL_R1CS_SHA,
              "circom": str(CIRCOM), "circom_sha256": CIRCOM_SHA,
              "compile_flags": ["--r1cs", "--sym", "--prime", "bn128",
                                "-l source_root", "-l library_paths", "--wasm", "--O0"],
              "e3_passed": all_matched and len(pairs) == EXPECTED_PAIRS,
              "e4_passed": e4["e4_passed"], "e4": e4, "pairs": pairs}
    write_new(R1CS_EVIDENCE, report)
    return report


def source_copy_audit() -> dict[str, Any]:
    """Record non-Circom include references and check sandbox deny rules."""
    require(MANIFEST.is_file() and R1CS_EVIDENCE.is_file() and
            not SOURCE_COPY_AUDIT.exists(), "source copy audit inputs/output invalid")
    manifest = read_json(MANIFEST)
    references = []
    source_symlinks = []
    seen: set[Path] = set()
    for pair in manifest["pairs"]:
        clone = Path(pair["original_clone_root"])
        if clone in seen:
            continue
        seen.add(clone)
        for item in pair["project_files"]:
            source = clone / item["path"]
            if source.is_symlink():
                source_symlinks.append(str(source))
            data = source.read_bytes()
            for match in INCLUDE.finditer(data):
                target = os.fsdecode(match.group(1))
                if Path(target).suffix == ".circom":
                    continue
                candidate = (source.parent / target).resolve()
                references.append({"source": str(source),
                                   "line": data.count(b"\n", 0, match.start()) + 1,
                                   "include": target,
                                   "same_directory_target_exists": candidate.is_file()})
    denial_tests = []
    for pair in manifest["pairs"]:
        profile = R1CS_CACHE / pair["pair_id"] / "sandbox.sb"
        if not profile.is_file():
            denial_tests.append({"pair_id": pair["pair_id"],
                                 "status": "sandbox_unavailable"})
            continue
        completed = subprocess.run(
            ["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/cat",
             pair["original_entrypoint"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            check=False, timeout=10)
        denial_tests.append({"pair_id": pair["pair_id"],
                             "status": ("denied" if completed.returncode != 0 and
                                        b"Operation not permitted" in completed.stderr else
                                        "not_denied"),
                             "exit_code": completed.returncode})
    report = {"schema": "n6-b6d-source-copy-audit-v1", "schema_version": 1,
              "manifest_sha256": sha256_file(MANIFEST),
              "clone_count": len(seen),
              "project_source_symlink_count": len(source_symlinks),
              "project_source_symlinks": source_symlinks,
              "non_circom_include_reference_count": len(references),
              "non_circom_include_references": references,
              "sandbox_denial_tests": denial_tests,
              "sandbox_denied_count": sum(x["status"] == "denied"
                                          for x in denial_tests),
              "limitation": "No OS file-open trace; fixed engine source and Circom "
                            "compiles establish the read set used here."}
    write_new(SOURCE_COPY_AUDIT, report)
    return report


def final_index(gate_path: Path) -> dict[str, Any]:
    require(not PLAN_OUT.exists() and not INDEX_OUT.exists() and
            not INDEX_V22_OUT.exists() and
            not REQUEST_ROOT.exists(), "B6d request output already exists")
    require(gate_path.is_file() and MANIFEST.is_file() and R1CS_EVIDENCE.is_file(),
            "B6d equivalence evidence missing")
    gate = read_json(gate_path)
    manifest = read_json(MANIFEST)
    r1cs = read_json(R1CS_EVIDENCE)
    require(gate.get("schema_version") == 1 and gate.get("status") == "passed" and
            gate.get("request_count") == EXPECTED_REQUESTS and
            gate.get("pair_count") == EXPECTED_PAIRS and
            all(gate.get(name) == "passed" for name in ("e1", "e2", "e3", "e4")),
            "E1-E4 gate has not passed")
    for key, expected in (("source_index_sha256", SOURCE_INDEX_SHA),
                          ("unit_manifest_sha256", sha256_file(MANIFEST)),
                          ("r1cs_equivalence_sha256", sha256_file(R1CS_EVIDENCE))):
        require(gate.get(key) == expected, f"gate binding differs: {key}")
    for key, path_key, expected in (
            ("b_closure_audit_sha256", "b_closure_audit", B_CLOSURE),
            ("a_closure_audit_sha256", "a_closure_audit", A_CLOSURE)):
        audit = Path(gate.get(path_key, ""))
        require(audit == expected and audit.is_file() and
                sha256_file(audit) == gate.get(key),
                f"gate audit binding differs: {key}")
    a_audit = read_json(A_CLOSURE)
    b_audit = read_json(B_CLOSURE)
    a = a_audit.get("a", {})
    b = b_audit.get("b", {})
    require(a.get("status") == "pass" and
            a.get("request_count") == 2926 and
            a.get("revision_count") == 26 and
            b.get("e1", {}).get("status") == "pass" and
            b.get("e2", {}).get("status") == "pass" and
            b.get("request_count") == EXPECTED_REQUESTS and
            b.get("pair_count") == EXPECTED_PAIRS and
            b_audit.get("staging_manifest_sha256") == sha256_file(MANIFEST) and
            b_audit.get("original_b_index_sha256") == SOURCE_INDEX_SHA,
            "linked A/B closure audits have not passed")
    require(r1cs.get("e3_passed") is True and r1cs.get("e4_passed") is True and
            r1cs.get("unit_manifest_sha256") == sha256_file(MANIFEST),
            "R1CS/E4 evidence has not passed")
    require(sha256_file(SOURCE_INDEX_V22) == SOURCE_INDEX_V22_SHA,
            "B6b v2.2 source index SHA changed")
    source_v22 = read_json(SOURCE_INDEX_V22)
    require(source_v22 == {**read_json(SOURCE_INDEX),
                            "engine": source_v22.get("engine"),
                            "engine_sha256": source_v22.get("engine_sha256")} and
            source_v22.get("engine_sha256") ==
            "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835",
            "B6b v2.2 overlay differs beyond engine")
    require(verify_stage(manifest)["e4_passed"], "unit byte audit failed")
    source_plan, source_index, joined = source_rows()
    by_order = {order: pair for pair in manifest["pairs"]
                for order in pair["queue_orders"]}
    require(len(by_order) == EXPECTED_REQUESTS, "B6d pair coverage invalid")
    base = read_json(Path(source_index["base_index"]))
    require(sha256_file(Path(source_index["base_index"])) ==
            source_index["base_index_sha256"], "constructed input index SHA changed")
    new_plan_rows = []
    new_rows = []
    request_payloads = []
    for old_row, old_plan in zip(source_index["requests"], joined):
        pair = by_order[old_row["queue_order"]]
        request_id = Path(old_row["request"]).stem
        request_path = (REQUEST_ROOT / old_row["scope"] /
                        old_row["revision_id"] / f"{request_id}.json")
        old_request = read_json(Path(old_row["request"]))
        require(old_request.get("id") == request_id and
                old_request.get("candidate", {}).get("path") ==
                old_plan["candidate_path"] and
                old_request.get("source_root") == old_plan["source_root"] and
                old_request.get("component_wrapper") == old_plan["component_wrapper"] and
                old_request.get("entrypoint") == old_plan["entrypoint"] and
                old_request.get("library_paths") == old_plan["library_paths"],
                "B6b request path binding changed")
        new_request = {**old_request, "source_root": pair["source_root"],
                       "component_wrapper": pair["wrapper"],
                       "entrypoint": pair["entrypoint"],
                       "library_paths": pair["library_paths"]}
        encoded = (json.dumps(new_request, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n").encode()
        request_payloads.append((request_path, encoded))
        new_plan_rows.append({**old_plan, "request": str(request_path),
                              "source_root": pair["source_root"],
                              "component_wrapper": pair["wrapper"],
                              "component_wrapper_sha256": pair["wrapper_sha256"],
                              "original_component_wrapper_sha256":
                              pair["original_wrapper_sha256"],
                              "entrypoint": pair["entrypoint"],
                              "library_paths": pair["library_paths"],
                              "original_library_paths": pair["original_library_paths"]})
        base_revision = base["revisions"][old_row["revision_id"]]
        require(old_request.get("base_input") == base_revision["base_input_path"],
                "constructed input path changed")
        new_rows.append({**old_row, "request": str(request_path),
                         "request_sha256": hashlib.sha256(encoded).hexdigest(),
                         "original_request": old_row["request"],
                         "original_request_sha256": old_row["request_sha256"],
                         "component_wrapper_sha256": pair["wrapper_sha256"],
                         "original_component_wrapper_sha256":
                         pair["original_wrapper_sha256"],
                         "original_library_paths": pair["original_library_paths"],
                         "base_input_sha256": base_revision["base_input_sha256"]})
        require(new_rows[-1]["candidate_sha256"] == old_row["candidate_sha256"],
                "candidate SHA changed")
    plan = {**source_plan, "requests": new_plan_rows,
            "source_plan": str(SOURCE_PLAN),
            "source_plan_sha256": sha256_file(SOURCE_PLAN),
            "unit_manifest": str(MANIFEST),
            "unit_manifest_sha256": sha256_file(MANIFEST),
            "equivalence_gate": str(gate_path),
            "equivalence_gate_sha256": sha256_file(gate_path)}
    index = {**source_index, "requests": new_rows,
             "plan_index": str(PLAN_OUT),
             "source_index": str(SOURCE_INDEX),
             "source_index_sha256": SOURCE_INDEX_SHA,
             "unit_manifest": str(MANIFEST),
             "unit_manifest_sha256": sha256_file(MANIFEST),
             "equivalence_gate": str(gate_path),
             "equivalence_gate_sha256": sha256_file(gate_path)}
    # Build all metadata and verify every original path before creating outputs.
    REQUEST_ROOT.mkdir(parents=True, exist_ok=False)
    for path, data in request_payloads:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    plan_sha = write_new(PLAN_OUT, plan)
    index["plan_index_sha256"] = plan_sha
    write_new(INDEX_OUT, index)
    write_new(INDEX_V22_OUT, {**index, "engine": source_v22["engine"],
                              "engine_sha256": source_v22["engine_sha256"]})
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "r1cs", "source-audit",
                                           "finalize-index"))
    parser.add_argument("--gate", type=Path, default=GATE)
    args = parser.parse_args()
    if args.action == "stage":
        result = stage()
        print(json.dumps({"status": "staged", "pairs": len(result["pairs"]),
                          "manifest": str(MANIFEST),
                          "manifest_sha256": sha256_file(MANIFEST)}, sort_keys=True))
    elif args.action == "r1cs":
        result = r1cs_equivalence()
        print(json.dumps({"e3_passed": result["e3_passed"],
                          "e4_passed": result["e4_passed"],
                          "pairs": len(result["pairs"]),
                          "evidence": str(R1CS_EVIDENCE)}, sort_keys=True))
        return 0 if result["e3_passed"] and result["e4_passed"] else 2
    elif args.action == "source-audit":
        result = source_copy_audit()
        print(json.dumps({"clone_count": result["clone_count"],
                          "non_circom_include_reference_count":
                          result["non_circom_include_reference_count"],
                          "sandbox_denied_count": result["sandbox_denied_count"],
                          "output": str(SOURCE_COPY_AUDIT)}, sort_keys=True))
    else:
        result = final_index(args.gate.resolve())
        print(json.dumps({"status": result["status"],
                          "request_count": result["request_count"],
                          "index": str(INDEX_OUT),
                          "index_sha256": sha256_file(INDEX_OUT),
                          "v2_2_index": str(INDEX_V22_OUT),
                          "v2_2_index_sha256": sha256_file(INDEX_V22_OUT)},
                         sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
