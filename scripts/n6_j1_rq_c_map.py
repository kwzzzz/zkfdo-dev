#!/usr/bin/env python3
"""Pin A-Q defect templates to captured entrypoint instance paths.

Only preparation metadata and Circom source bytes are read. Candidate and base
input files are never opened. Large instance captures are parsed incrementally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json"
PREPARATION = ROOT / "runs/n6-a1-2026-10-07/preparation-units.json"
TARGETS = ROOT / "docs/n6_targets_a_2026-10-07.json"
CAPTURE_ROOT = ROOT / "runs/n6-a1b-2026-10-08/units"
PRAGMA_ROOT = ROOT / "runs/n6-a3-2026-10-08.noindex/pragma"
DEFAULT_OUTPUT = ROOT / "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json"
TEMPLATE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
PRAGMA = re.compile(r"^\s*pragma\s+circom\s+\d+\.\d+\.\d+\s*;\s*$")
JQ_FILTER = (
    'select(length == 2 and '
    '(((.[0]|length)==1 and (.[0][0]=="schema" or .[0][0]=="status" '
    'or .[0][0]=="entrypoint" or .[0][0]=="project_root")) or '
    '((.[0]|length)==3 and .[0][0]=="instances" and '
    '(.[0][2]=="path" or .[0][2]=="template_name")))) | [.[0], .[1]]'
)


class MappingError(RuntimeError):
    """A source binding is inconsistent, so the mapping cannot be trusted."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise MappingError(reason)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def absolute(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def read_json(path: Path, expected_sha: str | None = None) -> dict[str, Any]:
    require(path.is_file(), f"missing JSON: {path}")
    if expected_sha is not None:
        require(sha256(path) == expected_sha, f"JSON SHA mismatch: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def function_templates(function: object) -> list[str]:
    if not isinstance(function, str):
        return []
    parts = [part.strip() for part in function.split("/")]
    return parts if parts and all(TEMPLATE.fullmatch(part) for part in parts) else []


def stream_capture(path: Path, wanted: set[str]) -> tuple[dict[str, str], dict[str, list[str]], int]:
    """Select only path/template_name scalars while jq streams the capture."""
    process = subprocess.Popen(
        ["jq", "--stream", "-c", JQ_FILTER, str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    require(process.stdout is not None and process.stderr is not None, "jq pipes unavailable")
    header: dict[str, str] = {}
    selected: dict[str, list[str]] = defaultdict(list)
    current_index: int | None = None
    current: dict[str, str] = {}
    count = 0

    def finish() -> None:
        nonlocal count
        if current_index is None:
            return
        require(set(current) == {"path", "template_name"},
                f"incomplete captured instance {current_index}: {path}")
        instance_path, template = current["path"], current["template_name"]
        require(instance_path == "main" or instance_path.startswith("main."),
                f"invalid instance path {current_index}: {path}")
        if template in wanted:
            selected[template].append(instance_path)
        count += 1

    try:
        for line in process.stdout:
            key, value = json.loads(line)
            require(isinstance(value, str), f"non-string capture scalar: {path}")
            if len(key) == 1:
                require(key[0] not in header, f"duplicate capture header: {path}")
                header[key[0]] = value
                continue
            index, field = key[1], key[2]
            require(isinstance(index, int), f"invalid instance index: {path}")
            if index != current_index:
                finish()
                require(current_index is None or index == current_index + 1,
                        f"instance index gap: {path}")
                current_index, current = index, {}
            require(field not in current, f"duplicate instance field: {path}")
            current[field] = value
        finish()
        stderr = process.stderr.read()
        require(process.wait() == 0, f"jq capture parse failed: {path}: {stderr[:200]}")
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
    require(header.get("schema") == "zkfdo-instance-capture-v1"
            and header.get("status") == "captured", f"capture not complete: {path}")
    for template, paths in selected.items():
        require(len(paths) == len(set(paths)), f"duplicate {template} paths: {path}")
    return header, selected, count


def pragma_normalized(path: Path) -> list[str]:
    lines = path.read_text().splitlines()
    return ["pragma circom <version>;" if PRAGMA.fullmatch(line) else line for line in lines]


def pragma_binding(identifier: str, original: Path, corrected: Path,
                   original_sha: str, corrected_sha: str,
                   report: dict[str, Any], proof: dict[str, Any]) -> None:
    require(identifier in {"aq-035-8f826c822cb8", "aq-036-6d7df64759b6"},
            f"unexpected corrected entrypoint: {identifier}")
    require(sha256(original) == original_sha and sha256(corrected) == corrected_sha,
            f"corrected entrypoint SHA mismatch: {identifier}")
    require(pragma_normalized(original) == pragma_normalized(corrected),
            f"entrypoint differs beyond pragma: {identifier}")
    changes = [row for row in report["changed_files"]
               if absolute(row["original_path"]) == original
               and absolute(row["corrected_path"]) == corrected]
    require(len(changes) == 1 and changes[0]["changed_lines"] == 1
            and changes[0]["original_sha256"] == original_sha
            and changes[0]["corrected_sha256"] == corrected_sha,
            f"pragma source change evidence missing: {identifier}")
    project_rows = [row for row in report["changed_files"]
                    if f"/{identifier}/project/" in row["original_path"]]
    require(project_rows and all(row["changed_lines"] == 1
                                 and pragma_normalized(absolute(row["original_path"]))
                                 == pragma_normalized(absolute(row["corrected_path"]))
                                 for row in project_rows),
            f"project changes exceed pragma-only correction: {identifier}")
    proofs = [row for row in proof["results"] if row["id"] == identifier]
    require(proof.get("status") == "passed" and len(proofs) == 1 and proofs[0]["equal"] is True,
            f"W R1CS equivalence missing: {identifier}")


def build_map(manifest_path: Path, preparation_path: Path, targets_path: Path,
              capture_root: Path, pragma_root: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    preparation = read_json(preparation_path)
    targets = read_json(targets_path)
    selected = {row["identifier"]: row for row in manifest["rows"]}
    prep_rows = {row["unit_id"]: row for row in preparation["aq_stage1_units"]}
    target_rows = {row["id"]: row for row in targets["items"]}
    correction = read_json(pragma_root / "source-changes.json")
    correction_proof = read_json(pragma_root / "r1cs-equivalence.json")
    rows = []
    for identifier, manifest_row in selected.items():
        if identifier not in prep_rows:
            continue
        prep = prep_rows[identifier]
        spec_path = absolute(manifest_row["whole_spec"])
        spec = read_json(spec_path, manifest_row["whole_spec_sha256"])
        require(spec["method"] == "whole" and len(spec["targets"]) == 1
                and len(spec["source_snapshots"]) == 1,
                f"invalid W spec: {identifier}")
        snapshot = spec["source_snapshots"][0]
        target = spec["targets"][0]
        entrypoint = absolute(manifest_row["entrypoint_absolute"])
        require((absolute(snapshot["path"]) / target["entrypoint_relative"]).resolve() == entrypoint
                and target["entrypoint_sha256"] == manifest_row["entrypoint_sha256"]
                and sha256(entrypoint) == manifest_row["entrypoint_sha256"],
                f"W entrypoint binding mismatch: {identifier}")
        captures = sorted((capture_root / identifier / "preparation/discovery").glob(
            "*/instance-capture.json"))
        require(len(captures) == 1, f"expected one source capture: {identifier}")
        capture_path = captures[0].resolve()
        discovery = read_json(capture_path.parent / "discovery.json")
        discovered = discovery["instance_discovery"]
        require(discovered.get("capture_status") == "captured"
                and absolute(discovered["capture_path"]) == capture_path,
                f"discovery capture binding mismatch: {identifier}")
        item_specs = []
        wanted: set[str] = set()
        for item_id in prep["item_ids"]:
            function = (target_rows[item_id].get("location") or {}).get("Function")
            templates = function_templates(function)
            wanted.update(templates)
            item_specs.append((item_id, function, templates))
        capture_sha = sha256(capture_path)
        header, paths_by_template, total_instances = stream_capture(capture_path, wanted)
        original = absolute(header["entrypoint"])
        original_sha = sha256(original)
        require(absolute(header["project_root"]) == absolute(discovery["project_root"]),
                f"capture project binding mismatch: {identifier}")
        if original == entrypoint:
            require(original_sha == manifest_row["entrypoint_sha256"],
                    f"capture W entrypoint SHA mismatch: {identifier}")
            basis = "same_entrypoint_sha256"
        else:
            pragma_binding(identifier, original, entrypoint, original_sha,
                           manifest_row["entrypoint_sha256"], correction, correction_proof)
            basis = "pragma_equivalent"
        items = []
        for item_id, function, templates in item_specs:
            paths = sorted({path for name in templates for path in paths_by_template.get(name, [])})
            missing = [name for name in templates if not paths_by_template.get(name)]
            status = ("unresolved_mapping" if not templates or not paths else
                      "partial_mapping" if missing else "mapped")
            items.append({"item_id": item_id, "location_function": function,
                          "templates": templates, "status": status,
                          "missing_templates": missing, "instance_paths": paths,
                          "instance_path_count": len(paths)})
        rows.append({"revision_id": identifier, "entrypoint_path": str(entrypoint),
                     "entrypoint_sha256": manifest_row["entrypoint_sha256"],
                     "whole_spec": str(spec_path),
                     "whole_spec_sha256": manifest_row["whole_spec_sha256"],
                     "capture_path": str(capture_path), "capture_sha256": capture_sha,
                     "capture_entrypoint": str(original),
                     "capture_entrypoint_sha256": original_sha,
                     "discovery_path": str(capture_path.parent / "discovery.json"),
                     "discovery_sha256": sha256(capture_path.parent / "discovery.json"),
                     "mapping_basis": basis, "captured_instance_count": total_instances,
                     "items": items})
    return {"schema_version": 1, "status": "verified", "mapping_scope": "selected_aq_revisions",
            "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path),
            "preparation_units": str(preparation_path),
            "preparation_units_sha256": sha256(preparation_path),
            "targets": str(targets_path), "targets_sha256": sha256(targets_path),
            "pragma_source_changes": str(pragma_root / "source-changes.json"),
            "pragma_source_changes_sha256": sha256(pragma_root / "source-changes.json"),
            "pragma_r1cs_equivalence": str(pragma_root / "r1cs-equivalence.json"),
            "pragma_r1cs_equivalence_sha256": sha256(pragma_root / "r1cs-equivalence.json"),
            "revision_count": len(rows), "item_mapping_count": sum(len(r["items"]) for r in rows),
            "revisions": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--preparation-units", type=Path, default=PREPARATION)
    parser.add_argument("--targets", type=Path, default=TARGETS)
    parser.add_argument("--capture-root", type=Path, default=CAPTURE_ROOT)
    parser.add_argument("--pragma-root", type=Path, default=PRAGMA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    require(not output.exists(), f"refuse to overwrite mapping: {output}")
    mapping = build_map(args.manifest.resolve(), args.preparation_units.resolve(),
                        args.targets.resolve(), args.capture_root.resolve(),
                        args.pragma_root.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(mapping, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"output": str(output), "revision_count": mapping["revision_count"],
                      "item_mapping_count": mapping["item_mapping_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
