#!/usr/bin/env python3
"""Construct synthetic FromAddrRegex input from a recorded A source unit.

The fixed public seed chooses an address under example.test. Construction uses
the recorded tests' ordinary ``from:address\r\n`` scenario and their ASCII,
zero-right-padding convention; it does not execute tests or regenerate source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a-remeasure-2026-10-25.noindex"
MANIFEST = ROOT / "runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json"
MANIFEST_SHA = "f059fe7d6aa21234168b7867537f069ec980c45c2c025184cbc12e169f687441"
BASE_INDEX = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json"
BASE_INDEX_SHA = "18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508"
SEED = "20261025-a-remeasure-from-addr-synthetic-v1"
REVISIONS = {
    "aq-040-da54d3e7bc8a": {
        "commit": "531575345558ba938675d725bd54df45c866ef74",
        "entrypoint": "packages/circom/tests/circuits/test_from_addr_regex.circom",
        "entrypoint_sha256": "f5e6379e1fcf2125b83a40334b873b40559069044a3485bfd0c6da1c9f0c391f",
        "r1cs_sha256": "a973556172236a9c7bf2c394901186857f4eb30fcf96feca2f95622d3678a05a",
        "constraints": 2017059,
        "msg_bytes": 1024,
    },
    "aq-037-94fe3080fc18": {
        "commit": "7002a2179e076449b84e3e7e8ba94e88d0a2dc2f",
        "entrypoint": "packages/circom/tests/circuits/test_from_addr_regex.circom",
        "entrypoint_sha256": "48690e551e0eda83b948ad80c17aca948d573c3a19c8334fd151a73792ac3815",
        "r1cs_sha256": "9cb209201539cbb82f0c795471390e6ef5845529c12269d76b44b4c28d273066",
        "constraints": 1667456,
        "msg_bytes": 1024,
        "name_reference": "packages/circom/circuits/common/reversed_bracket.json",
    },
    "aq-039-0ad3923f2f5b": {
        "commit": "7002a2179e076449b84e3e7e8ba94e88d0a2dc2f",
        "entrypoint": "packages/circom/tests/circuits/test_from_addr_regex.circom",
        "entrypoint_sha256": "48690e551e0eda83b948ad80c17aca948d573c3a19c8334fd151a73792ac3815",
        "r1cs_sha256": "f89f10fe240a1581f368d612e5f1cba8e35caab3a51333d450d1a50c32183bb9",
        "constraints": 1655168,
        "msg_bytes": 1024,
        "name_reference": "packages/circom/circuits/common/reversed_bracket.json",
        "revision_kind": "leave_one_out",
        "allowed_source_patches": {
            "packages/circom/circuits/common/from_all_regex.circom": {
                "recorded_commit_sha256": "5440e55583bf408650b7b74d92641b7a50cb55859611be85e80f3993802676c4",
                "designated_unit_sha256": "ecae22d106caa818fa269ca52b52490ed963a8949aa057bc2f95c2980d719683",
                "description": "Recorded leave-one-out unit deletes only the byte-range-check declaration and its two statements",
                "deleted_lines": [
                    "\tsignal in_range_checks[msg_bytes];\n",
                    "\t\tin_range_checks[i] <== LessThan(8)([msg[i], 255]);\n",
                    "\t\tin_range_checks[i] === 1;\n",
                ],
            },
        },
    },
}
REFERENCE_SOURCES = (
    "packages/circom/tests/from_addr.test.js",
    "packages/circom/circuits/common/from_all.json",
    "packages/circom/circuits/common/email_addr.json",
    "packages/circom/circuits/common/email_addr_with_name.json",
    "packages/apis/src/padding.rs",
    "packages/circom/package.json",
    "package.json",
)
INCLUDE = re.compile(r'\binclude\s+"([^"\n]+)"\s*;')


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def display_path(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def source_record(path: Path, project: Path, commit: str, allowed_patches: dict | None = None) -> dict:
    resolved = path.resolve(strict=True)
    current = resolved.read_bytes()
    digest = hashlib.sha256(current).hexdigest()
    record = {"path": display_path(path), "resolved_path": display_path(resolved), "sha256": digest}
    if resolved.is_relative_to(project) and "node_modules" not in resolved.relative_to(project).parts:
        relative = str(resolved.relative_to(project))
        command = subprocess.run(
            ["git", "-C", str(project), "show", f"{commit}:{relative}"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"},
        )
        committed_digest = hashlib.sha256(command.stdout).hexdigest()
        patch = (allowed_patches or {}).get(relative)
        if patch is not None:
            if committed_digest != patch["recorded_commit_sha256"] or digest != patch["designated_unit_sha256"]:
                raise RuntimeError(f"recorded ablation source hash differs: {relative}")
            patched = command.stdout
            for line in patch["deleted_lines"]:
                encoded = line.encode("utf8")
                if patched.count(encoded) != 1:
                    raise RuntimeError(f"recorded ablation deletion is not unique: {relative}")
                patched = patched.replace(encoded, b"", 1)
            if patched != current:
                raise RuntimeError(f"unit source has differences beyond recorded ablation: {relative}")
            record.update({"recorded_commit_equal": False, "recorded_commit_sha256": committed_digest,
                           "recorded_ablation": patch, "exact_recorded_ablation_verified": True})
        elif committed_digest != digest:
            raise RuntimeError(f"unit source differs from recorded commit: {relative}")
        else:
            record["recorded_commit_equal"] = True
    else:
        record["public_dependency"] = True
    return record


def audit_sources(revision: str) -> dict:
    config = REVISIONS[revision]
    project = ROOT / "runs/n6-a1b-2026-10-08/units" / revision / "project"
    if sha256(MANIFEST) != MANIFEST_SHA or sha256(BASE_INDEX) != BASE_INDEX_SHA:
        raise RuntimeError("recorded A source/base index hash changed")
    rows = [row for row in json.loads(MANIFEST.read_text())["rows"] if row.get("identifier") == revision]
    if len(rows) != 1:
        raise RuntimeError("recorded revision does not have exactly one source manifest row")
    row = rows[0]
    if row["revision_commit"] != config["commit"] or Path(row["project_root"]) != project or \
            Path(row["git_repository_path"]) != project or row["entrypoint_relative"] != config["entrypoint"] or \
            row["entrypoint_sha256"] != config["entrypoint_sha256"]:
        raise RuntimeError("recorded commit/project/entrypoint binding differs")
    if "revision_kind" in config and row["revision_kind"] != config["revision_kind"]:
        raise RuntimeError("recorded unit kind differs")
    base = json.loads(BASE_INDEX.read_text())["revisions"][revision]
    if base["compile"]["r1cs_sha256"] != config["r1cs_sha256"] or base["constraints"] != config["constraints"]:
        raise RuntimeError("recorded R1CS binding differs")
    entrypoint = project / config["entrypoint"]
    if sha256(entrypoint) != config["entrypoint_sha256"]:
        raise RuntimeError("designated unit entrypoint hash differs")
    if not re.search(rf'component\s+main\s*=\s*FromAddrRegex\({config["msg_bytes"]}\)\s*;', entrypoint.read_text()):
        raise RuntimeError("designated entrypoint input size differs")
    libraries = list(dict.fromkeys(Path(path) for path in row["preflight_library_paths"]))
    dependency_root = ROOT / ".external/zkbugs/dataset/circom/dependencies/circomlib"
    allowed_roots = (project.resolve(), dependency_root.resolve())
    sources, seen, edges = [], set(), []

    def visit(path: Path) -> None:
        resolved = path.resolve(strict=True)
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            raise RuntimeError("include resolved outside designated project/public library")
        if resolved in seen:
            return
        seen.add(resolved)
        sources.append(source_record(path, project, config["commit"], config.get("allowed_source_patches")))
        for include in INCLUDE.findall(resolved.read_text()):
            candidates = [resolved.parent / include] + [library / include for library in libraries]
            target = next((candidate for candidate in candidates if candidate.is_file()), None)
            if target is None:
                raise RuntimeError(f"recorded include unavailable: {include}")
            edges.append({"source": display_path(resolved), "include": include,
                          "resolved_path": display_path(target.resolve())})
            visit(target)

    visit(entrypoint)
    reference_paths = [config.get("name_reference", relative)
                       if relative.endswith("/email_addr_with_name.json") else relative
                       for relative in REFERENCE_SOURCES]
    references = [source_record(project / relative, project, config["commit"], config.get("allowed_source_patches"))
                  for relative in reference_paths]
    for relative in config.get("allowed_source_patches", {}):
        if (project / relative).resolve() not in seen:
            raise RuntimeError("recorded ablation is not in the designated entrypoint include closure")
    dependencies = {}
    for path in seen:
        if not path.is_relative_to(project) or "node_modules" in path.relative_to(project).parts:
            folder = path.parent
            while any(folder.is_relative_to(root) for root in allowed_roots):
                package = folder / "package.json"
                if package.is_file():
                    metadata = json.loads(package.read_text())
                    if metadata.get("name") and metadata.get("version"):
                        dependencies[str(package)] = {"path": display_path(package), "sha256": sha256(package),
                                                      "name": metadata["name"], "version": metadata["version"]}
                        break
                folder = folder.parent
    locks = []
    for name in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml"):
        lock = project / name
        if lock.is_file():
            locks.append({"path": display_path(lock), "sha256": sha256(lock)})
    return {"recorded_commit": config["commit"], "manifest_sha256": MANIFEST_SHA,
            "base_input_index_sha256": BASE_INDEX_SHA, "entrypoint": config["entrypoint"],
            "entrypoint_sha256": config["entrypoint_sha256"], "recorded_r1cs_sha256": config["r1cs_sha256"],
            "recorded_constraints": config["constraints"], "library_paths": [str(path) for path in libraries],
            "source_closure": sorted(sources, key=lambda item: item["resolved_path"]),
            "include_edges": edges, "reference_sources": references,
            "public_dependencies": [dependencies[key] for key in sorted(dependencies)], "lockfiles": locks}


def construct(revision: str) -> tuple[dict, dict]:
    if revision not in REVISIONS:
        raise ValueError("revision has not been authorized for this generator")
    audit = audit_sources(revision)
    seed = f"{SEED}:{revision}"
    address = "synthetic-" + hashlib.sha256(seed.encode("ascii")).hexdigest()[:16] + "@example.test"
    message = ("from:" + address + "\r\n").encode("ascii")
    size = REVISIONS[revision]["msg_bytes"]
    if len(message) > size:
        raise RuntimeError("synthetic header exceeds the designated entrypoint input size")
    value = {"msg": list(message) + [0] * (size - len(message))}
    if audit_sources(revision) != audit:
        raise RuntimeError("recorded source or dependency changed during construction")
    return value, {"schema": "n6-a-from-addr-construction-v1", "revision": revision, "seed": seed,
                   **audit, "construction": "Synthetic ASCII from header, followed by zero bytes to msg[1024]",
                   "scenario": "from field at start, address without a display name", "expected_regex_output": 1,
                   "message_bytes": len(message), "padded_message_bytes": size,
                   "synthetic_data_only": True, "existing_secrets_read": False, "keys_or_signatures_required": False,
                   "repository_tests_executed": False,
                   "shared_family_reason": "FromAddrRegex family; each authorized revision is separately bound to its designated entrypoint, include closure and recorded R1CS"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", choices=tuple(REVISIONS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = RUN / "inputs" / args.revision
    output = args.output.resolve()
    if output.parent != directory or args.output.is_symlink() or \
            re.fullmatch(r"input(?:-trial-[0-9]{2})?\.json", output.name) is None:
        raise SystemExit("output must be this revision's A-run input.json or input-trial-NN.json")
    provenance_path = output.with_suffix(".provenance.json")
    if output.exists() or provenance_path.exists():
        raise SystemExit("refusing to overwrite input or provenance")
    started = time.monotonic()
    value, provenance = construct(args.revision)
    directory.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    provenance.update({"input_path": str(output), "input_sha256": sha256(output),
                       "generator_path": display_path(Path(__file__).resolve()), "generator_sha256": sha256(Path(__file__)),
                       "construction_wall_seconds": time.monotonic() - started})
    with provenance_path.open("x") as stream:
        json.dump(provenance, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"revision": args.revision, "input_sha256": provenance["input_sha256"],
                      "generator_sha256": provenance["generator_sha256"],
                      "construction_wall_seconds": provenance["construction_wall_seconds"]}))


if __name__ == "__main__":
    main()
