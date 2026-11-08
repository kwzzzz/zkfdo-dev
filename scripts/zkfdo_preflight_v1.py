#!/usr/bin/env python3
"""Read-only, revision-bound preparation asset gate; never generates inputs.

Readiness means declared assets exist, not that an input is valid. The original
honest witness, Rust R1CS and snarkjs checks remain mandatory afterwards.
Environment values, fixture contents and candidate values never enter receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

SCHEMA = "zkfdo-preparation-assets-v1"
RECEIPT_SCHEMA = "zkfdo-revision-preflight-v1"
MAX_TEXT_BYTES = 16 * 1024 * 1024
KINDS = {"environment", "executable", "file", "directory", "wasm", "json_keys", "same_main"}


class PreflightFailed(RuntimeError):
    """A preparation dependency is absent; no compiler or fuzzer may start."""


def sha256(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("expected a lowercase SHA256")
    return value


def project_path(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("asset path must be relative and stay within project")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("asset symlink escapes project")
    return candidate


def load_revision_profile(path, revision_id, expected_sha256, revision_commit=None):
    """Require a pinned catalog and an exact revision; never select by prefix."""
    path = Path(path).resolve()
    data_bytes = path.read_bytes()
    digest = hashlib.sha256(data_bytes).hexdigest()
    if digest != _sha(expected_sha256):
        raise ValueError("preparation profile SHA256 differs")
    catalog = json.loads(data_bytes)
    if catalog.get("schema") != SCHEMA:
        raise ValueError("unsupported preparation profile schema")
    profile = catalog.get("revisions", {}).get(revision_id)
    if not isinstance(profile, dict) or profile.get("revision_id") != revision_id:
        raise ValueError("revision absent from preparation profile")
    if revision_commit is not None and profile.get("revision_commit") != revision_commit:
        raise ValueError("preparation profile revision commit differs")
    return {**profile, "profile_path": str(path), "profile_sha256": digest}


def validate_profile(profile):
    if not isinstance(profile, dict) or not isinstance(profile.get("revision_id"), str) or not profile["revision_id"]:
        raise ValueError("preparation profile requires revision_id")
    requirements = profile.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("preparation profile requires nonempty requirements")
    identifiers = set()
    for requirement in requirements:
        identifier = requirement.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("asset requirement ids must be unique and nonempty")
        identifiers.add(identifier)
        kind = requirement.get("kind")
        if kind not in KINDS:
            raise ValueError("unknown asset requirement kind")
        if kind in ("environment", "executable"):
            if not isinstance(requirement.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", requirement["name"]):
                raise ValueError("asset requirement needs a simple name")
        else:
            if not isinstance(requirement.get("path"), str):
                raise ValueError("asset requirement needs a path")
        if "sha256" in requirement:
            _sha(requirement["sha256"])
        if kind == "json_keys" and (not isinstance(requirement.get("keys"), list) or
                                     any(not isinstance(key, str) for key in requirement["keys"])):
            raise ValueError("json_keys requires a list of names")
        if kind == "same_main" and not isinstance(requirement.get("entrypoint"), str):
            raise ValueError("same_main requires an entrypoint")


def _read_text(path):
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise ValueError("asset exceeds bounded static check size")
    return path.read_text()


def _main_signature(path):
    # This is a syntactic guard only. It does not replace compiler validation.
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", _read_text(path), flags=re.DOTALL)
    matches = re.findall(r"\bcomponent\s+main\s*(?:\{[^}]*\})?\s*=\s*([^;]+);", source)
    return re.sub(r"\s+", "", matches[0]) if len(matches) == 1 else None


def _check(requirement, root, environ):
    kind = requirement["kind"]
    if kind == "environment":
        return None if bool(environ.get(requirement["name"])) else "environment_missing_or_empty"
    if kind == "executable":
        dirs = [str(project_path(root, item)) for item in requirement.get("search_dirs", [])]
        search_path = os.pathsep.join([*dirs, environ.get("PATH", "")])
        return None if shutil.which(requirement["name"], path=search_path) else "executable_missing"
    path = project_path(root, requirement["path"])
    if kind == "directory":
        return None if path.is_dir() else "directory_missing"
    if not path.is_file():
        return "file_missing"
    if requirement.get("sha256") is not None and sha256(path) != requirement["sha256"]:
        return "asset_sha256_mismatch"
    if kind == "wasm":
        with path.open("rb") as handle:
            header = handle.read(128)
        if header.startswith(b"version https://git-lfs.github.com/spec/v1"):
            return "git_lfs_pointer"
        if not header.startswith(b"\x00asm\x01\x00\x00\x00"):
            return "invalid_wasm_header"
    elif kind == "json_keys":
        data = json.loads(_read_text(path))
        if not isinstance(data, dict) or set(data) != set(requirement["keys"]):
            return "main_input_keys_mismatch"
    elif kind == "same_main":
        other = project_path(root, requirement["entrypoint"])
        if not other.is_file():
            return "entrypoint_missing"
        signature = _main_signature(path)
        if signature is None or signature != _main_signature(other):
            return "main_signature_mismatch_or_unparsed"
    return None


def check_revision(profile, project_root, environ=None):
    """Check the declared preparation route once, without running project code."""
    started, cpu_started = time.monotonic(), time.process_time()
    validate_profile(profile)
    root = Path(project_root).resolve()
    environment = os.environ if environ is None else environ
    checks = []
    for requirement in profile["requirements"]:
        try:
            reason = _check(requirement, root, environment)
        except (OSError, ValueError, TypeError) as error:
            # Do not stringify parsing errors: their text can contain input data.
            reason = "asset_check_error:" + type(error).__name__
        checks.append({"id": requirement["id"], "kind": requirement["kind"],
                       "name": requirement.get("name"), "path": requirement.get("path"),
                       "status": "missing" if reason else "present", "reason": reason})
    failures = [row for row in checks if row["status"] != "present"]
    return {"schema": RECEIPT_SCHEMA, "revision_id": profile["revision_id"],
            "revision_commit": profile.get("revision_commit"), "project_root": str(root),
            "profile_path": profile.get("profile_path"), "profile_sha256": profile.get("profile_sha256"),
            "status": "preparation_assets_missing" if failures else "ready",
            "checks": checks, "failures": failures,
            "wall_seconds": time.monotonic() - started, "cpu_seconds": time.process_time() - cpu_started,
            "scope": "declared asset availability only; input provenance and honest witness validation remain required",
            "fuzzing_started": False}


def require_ready(receipt):
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("status") != "ready":
        failed = ",".join(row["id"] for row in receipt.get("failures", []))
        raise PreflightFailed("preparation_assets_missing: " + failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--revision-commit")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = load_revision_profile(args.profile, args.revision, args.profile_sha256, args.revision_commit)
    receipt = check_revision(profile, args.project)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"revision_id": args.revision, "status": receipt["status"], "receipt": str(args.output)}))
    return 0 if receipt["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
