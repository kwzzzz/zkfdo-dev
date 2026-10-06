#!/usr/bin/env python3
"""Pure E-02 role classification and static Circom library-path extraction."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re


HARNESS_COMPONENTS = {
    "test", "tests", "__tests__", "test-circuits", "mock", "mocks",
    "fixture", "fixtures", "benchmark", "bench", "example", "examples",
}
SCAN_NAMES = {"package.json", "circomkit.json", "Makefile"}
SCAN_SUFFIXES = {".sh", ".mk", ".yml", ".yaml"}
LIBRARY_OPTION = re.compile(
    r"(?:^|\s)(?:-l|--library|--library-path)(?:\s+|=)(?P<quote>['\"]?)(?P<value>[^\s'\"\\]+)(?P=quote)"
)
UNSAFE_LITERAL = re.compile(r"[$`*?{}\[\]()]")


def entrypoint_identity(entrypoint_key: str) -> str:
    """Return the path/name portion used by the frozen role rule."""
    if entrypoint_key.startswith("source_main:"):
        return entrypoint_key.split(":", 1)[1]
    if entrypoint_key.startswith("config:"):
        return entrypoint_key.split(":", 1)[1]
    return entrypoint_key


def classify_role(entrypoint_key: str) -> tuple[str, list[str]]:
    identity = entrypoint_identity(entrypoint_key).lower().replace("\\", "/")
    parts = [part for part in identity.split("/") if part]
    reasons: list[str] = []
    for part in parts[:-1]:
        if part in HARNESS_COMPONENTS:
            reasons.append("path_component:" + part)
    filename = parts[-1] if parts else identity
    stem = filename.rsplit(".", 1)[0] if ":" not in filename else filename
    tokens = [token for token in re.split(r"[-_.:]", stem) if token]
    for token in tokens:
        if token in {"test", "mock", "fixture", "example"}:
            reasons.append("filename_token:" + token)
    if "_tester" in stem:
        reasons.append("filename_substring:_tester")
    reasons = list(dict.fromkeys(reasons))
    return ("test_mock_harness" if reasons else "deployment_main", reasons)


def scan_files(root: Path) -> list[Path]:
    """Select only frozen static build/config formats, without entering dependencies."""
    root = root.resolve()
    result: list[Path] = []
    # A source-controlled directory named `build` may contain build scripts (as in
    # circuits/scripts/build), so only dependency/VCS/generated-only trees are pruned.
    ignored = {".git", "node_modules", "dist", "target", "artifacts", "output"}
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in ignored)
        base = Path(directory)
        for name in sorted(files):
            path = base / name
            hardhat = name.lower().startswith("hardhat") and path.suffix in {".js", ".ts", ".json"}
            if name in SCAN_NAMES or path.suffix in SCAN_SUFFIXES or hardhat:
                result.append(path)
    return result


def nearest_package_root(path: Path, repository_root: Path) -> Path | None:
    current = path.parent
    root = repository_root.resolve()
    while current.resolve().is_relative_to(root):
        if (current / "package.json").is_file():
            return current
        if current.resolve() == root:
            break
        current = current.parent
    return None


def _json_include_literals(path: Path) -> list[tuple[int, str, str]]:
    if path.name != "circomkit.json":
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    values = data.get("include")
    if not isinstance(values, list):
        return []
    lines = path.read_text(errors="replace").splitlines()
    found = []
    for value in values:
        if not isinstance(value, str):
            continue
        line = next((number for number, text in enumerate(lines, 1) if json.dumps(value) in text), 1)
        found.append((line, value, "circomkit_include"))
    return found


def literal_candidates(path: Path) -> list[tuple[int, str, str]]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    found = _json_include_literals(path)
    logical = ""
    start = 1
    for number, line in enumerate(text.splitlines(), 1):
        if not logical:
            start = number
        logical += " " + line.strip()
        if line.rstrip().endswith("\\"):
            continue
        for match in LIBRARY_OPTION.finditer(logical):
            found.append((start, match.group("value"), "circom_option"))
        logical = ""
    if logical:
        for match in LIBRARY_OPTION.finditer(logical):
            found.append((start, match.group("value"), "circom_option"))
    return list(dict.fromkeys(found))


def derive_library_evidence(repository_root: Path) -> tuple[list[dict], list[dict]]:
    """Resolve literals against three general anchors; retain rejected literals."""
    root = repository_root.resolve()
    accepted: list[dict] = []
    rejected: list[dict] = []
    for source in scan_files(root):
        package_root = nearest_package_root(source, root)
        anchors = [("config_directory", source.parent)]
        if package_root is not None:
            anchors.append(("nearest_package_root", package_root))
        anchors.append(("repository_root", root))
        anchors = list(dict.fromkeys((name, path.resolve()) for name, path in anchors))
        for line, literal, source_kind in literal_candidates(source):
            base = {"source": str(source.relative_to(root)), "line": line,
                    "literal": literal, "source_kind": source_kind}
            if not literal or UNSAFE_LITERAL.search(literal) or Path(literal).is_absolute():
                rejected.append({**base, "reason": "nonliteral_or_absolute"})
                continue
            matches = []
            for anchor_kind, anchor in anchors:
                candidate = (anchor / literal).resolve()
                if candidate.is_relative_to(root) and candidate.is_dir():
                    matches.append((anchor_kind, candidate))
            if not matches:
                rejected.append({**base, "reason": "no_existing_directory_under_checkout"})
                continue
            for anchor_kind, candidate in matches:
                accepted.append({**base, "anchor": anchor_kind, "path": str(candidate)})
    unique = {}
    for row in accepted:
        key = (row["source"], row["line"], row["literal"], row["anchor"], row["path"])
        unique[key] = row
    return sorted(unique.values(), key=lambda row: tuple(str(row[k]) for k in ("source", "line", "literal", "anchor", "path"))), rejected


def evidence_scope(evidence: dict, entrypoint_key: str, source_relative: str | None) -> bool:
    """Apply an extracted path within its package/config scope or an explicit reference."""
    build_file = Path(evidence["source"])
    identity = entrypoint_identity(entrypoint_key).replace("\\", "/")
    source = (source_relative or identity).replace("\\", "/")
    # circomkit include belongs to exactly the config whose key names it.
    if evidence["source_kind"] == "circomkit_include":
        return entrypoint_key.startswith("config:" + evidence["source"] + ":")
    # The resolved library path itself and the entrypoint commonly share a package root.
    scope_parts = Path(evidence["source"]).parts
    if "package.json" == build_file.name:
        scope = build_file.parent.as_posix().strip(".")
    else:
        # nearest package root cannot be reconstructed here; accept the first path component
        # for non-root build files. The driver records this conservative scope explicitly.
        scope = scope_parts[0] if len(scope_parts) > 1 else ""
    return not scope or source == scope or source.startswith(scope.rstrip("/") + "/")
