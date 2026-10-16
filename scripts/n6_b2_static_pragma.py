#!/usr/bin/env python3
"""Record pragma requirements in every B include closure without running zkFuzz."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "runs/n6-b2-2026-10-09.noindex/include-provenance.json"
OUTPUT = ROOT / "runs/n6-b2-2026-10-09.noindex/parser-static-pragma.json"
PRAGMA = re.compile(r"^\s*pragma\s+circom\s+(\d+)\.(\d+)\.(\d+)\s*;", re.MULTILINE)
MAX_PARSER_VERSION = (2, 2, 1)


def file_requirements(path: Path) -> list[str]:
    return [".".join(match.groups()) for match in PRAGMA.finditer(path.read_text(errors="replace"))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provenance", type=Path, default=PROVENANCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    provenance = args.provenance.resolve()
    output = args.output.resolve()
    source = json.loads(provenance.read_text())
    if source["status"] != "passed" or source["spec_count"] != 60:
        raise ValueError("B include provenance is not accepted")
    file_versions: dict[str, list[str]] = {}
    closures = {}
    for closure in source["closures"]:
        files = {closure["entrypoint"]}
        files.update(row["resolved_path"] for row in closure["includes"])
        rows = []
        for name in sorted(files):
            if name not in file_versions:
                file_versions[name] = file_requirements(ROOT / name)
            for version in file_versions[name]:
                rows.append({"file": name, "version": version,
                             "exceeds_parser": tuple(map(int, version.split("."))) > MAX_PARSER_VERSION})
        closures[closure["closure_id"]] = {
            "closure_id": closure["closure_id"],
            "entrypoint": closure["entrypoint"],
            "pragma_versions": sorted({row["version"] for row in rows}),
            "files_exceeding_parser": [row for row in rows if row["exceeds_parser"]],
        }
    specs = []
    for spec in source["specs"]:
        versions = Counter()
        high = set()
        for target in spec["targets"]:
            row = closures[target["closure_id"]]
            versions.update(row["pragma_versions"])
            high.update(item["file"] for item in row["files_exceeding_parser"])
        specs.append({"spec": spec["spec"], "method": spec["method"],
                      "target_count": spec["target_count"],
                      "pragma_version_target_counts": dict(sorted(versions.items())),
                      "files_exceeding_parser": sorted(high)})
    result = {
        "schema_version": 1,
        "source": str(provenance.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(provenance.read_bytes()).hexdigest(),
        "parser_version": "2.2.1",
        "file_count": len(file_versions),
        "unique_closure_count": len(closures),
        "spec_count": len(specs),
        "unique_files_exceeding_parser": sorted({
            item["file"] for row in closures.values() for item in row["files_exceeding_parser"]
        }),
        "closures": list(closures.values()),
        "specs": specs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"spec_count": len(specs), "unique_closure_count": len(closures),
                      "unique_files_exceeding_parser": len(result["unique_files_exceeding_parser"]),
                      "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
