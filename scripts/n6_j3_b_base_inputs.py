#!/usr/bin/env python3
"""Apply the unchanged J1 (a)-(e) selector to ten B main revisions.

Run only after B mem20 state.json reports completed. No dependency installation
or candidate parsing is performed by this script.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from n6_j1_base_inputs import (CIRCOM, CIRCOM_SHA256, checker_binary,
                               dump_json, l_series_inputs, select_one, sha256)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "runs/n6-j3-2026-10-14.noindex/revision-manifest.json"
DEFAULT_OUTPUT = ROOT / "runs/n6-j3-2026-10-14.noindex/base-inputs"
MEM20_STATE = ROOT / "runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("main", "mem20"), default="main")
    parser.add_argument("--revision-manifest", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--compile-timeout-seconds", type=float, default=1800)
    parser.add_argument("--validation-timeout-seconds", type=float, default=600)
    parser.add_argument("--identifier", help="one revision for bounded restart")
    args = parser.parse_args()
    if not MEM20_STATE.is_file() or json.loads(MEM20_STATE.read_text()).get("status") != "completed":
        raise SystemExit("B mem20 state is not completed; base-input collection refused")
    manifest = (args.revision_manifest or
                (DEFAULT_MANIFEST if args.scope == "main" else
                 DEFAULT_MANIFEST.parent / "mem20-revision-manifest.json")).resolve()
    output = (args.output_root or
              (DEFAULT_OUTPUT if args.scope == "main" else
               DEFAULT_OUTPUT.parent / "base-inputs-mem20")).resolve()
    if sha256(CIRCOM) != CIRCOM_SHA256:
        raise SystemExit("fixed circom hash mismatch")
    rows = json.loads(manifest.read_text())["rows"]
    expected_revisions = 10 if args.scope == "main" else 2
    if len(rows) != expected_revisions or len({row["identifier"] for row in rows}) != expected_revisions:
        raise SystemExit(f"B {args.scope} revision manifest must have {expected_revisions} distinct rows")
    if args.identifier and args.identifier not in {row["identifier"] for row in rows}:
        raise SystemExit("identifier absent from B main revision manifest")
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
        if index.get("revision_manifest_sha256") != sha256(manifest):
            raise SystemExit("revision manifest hash changed")
    else:
        index = {"schema": "n6-j1-base-inputs-v1", "scope": f"B-{args.scope}",
                 "revision_manifest_path": str(manifest),
                 "revision_manifest_sha256": sha256(manifest),
                 "circom_sha256": CIRCOM_SHA256, "revisions": {}}
    l_inputs = l_series_inputs()
    checker = checker_binary(output)
    snarkjs_name = shutil.which("snarkjs")
    if not snarkjs_name:
        raise SystemExit("snarkjs unavailable")
    snarkjs = Path(snarkjs_name).resolve()
    index["rust_checker_path"] = str(checker)
    index["rust_checker_sha256"] = sha256(checker)
    index["snarkjs_path"] = str(snarkjs)
    index["snarkjs_sha256"] = sha256(snarkjs)
    dump_json(index_path, index)
    for row in rows:
        identifier = row["identifier"]
        if args.identifier and identifier != args.identifier:
            continue
        if identifier in index["revisions"]:
            continue
        try:
            result = select_one(row, output, checker, snarkjs, l_inputs,
                                args.compile_timeout_seconds, args.validation_timeout_seconds)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            result = {"identifier": identifier, "status": "base_input_unavailable",
                      "selected_stage": None, "original_rule_stage": "base_input_unavailable",
                      "base_input_path": None, "base_input_sha256": None,
                      "failed_attempts": [{"stage": "preparation", "reason": str(error)}]}
            dump_json(output / identifier / "selection.json", result)
        index["revisions"][identifier] = result
        dump_json(index_path, index)
        print(identifier, result["status"], result.get("selected_stage"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
