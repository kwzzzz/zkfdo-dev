#!/usr/bin/env python3
"""Platform tool manifests and explicit output-root configuration."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def platform_name():
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    raise ValueError(f"unsupported platform: {sys.platform}")


def runs_root() -> Path:
    raw = Path(os.environ.get("ZKFDO_RUNS", str(ROOT / "runs"))).expanduser()
    return (raw if raw.is_absolute() else ROOT / raw).resolve()


def output_path(value: str | Path | None, default_id: str) -> Path:
    root = runs_root()
    if value is None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", default_id):
            raise ValueError("default job id must be a simple directory name")
        path = root / "policy-a-v5" / default_id
    else:
        raw = Path(value).expanduser()
        path = raw if raw.is_absolute() else root / raw
    path = path.resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("output must be a task subdirectory of ZKFDO_RUNS")
    return path


def sha256(path: str | Path) -> str:
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError(f"file changed while hashing: {path}")
    return digest.hexdigest()


def verify_tool(tool: dict) -> dict:
    path = Path(tool["path"])
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"tool is not an executable file: {path}")
    actual = sha256(path)
    if actual != tool["sha256"]:
        raise ValueError(f"tool SHA256 differs: {path}")
    return {**tool, "sha256_verified": True}


def load_manifest(path=None, *, required=(), verify=True) -> dict:
    if path is None:
        path = os.environ.get("ZKFDO_TOOLS_MANIFEST", str(ROOT / "configs" / f"tools.{platform_name()}.json"))
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    data = json.loads(path.read_text())
    if data.get("schema") != "zkfdo-tools-v1":
        raise ValueError("unsupported tools manifest schema")
    if data.get("status") == "template":
        raise ValueError("tools manifest is an unfilled template; build and attest tools first")
    if data.get("status") not in {"measured", "ready"}:
        raise ValueError("tools manifest status must be measured or ready")
    if data.get("platform") != platform_name():
        raise ValueError("tool manifest platform differs from execution host")
    aliases = {"aarch64": "arm64", "amd64": "x86_64"}
    expected = aliases.get(str(data.get("architecture")).lower(), str(data.get("architecture")).lower())
    actual = aliases.get(platform.machine().lower(), platform.machine().lower())
    if expected != actual:
        raise ValueError("tool manifest architecture differs from execution host")
    entries = data.get("tools")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("tool manifest tools must be nonempty")
    if set(required) - entries.keys():
        raise ValueError(f"tool manifest missing required tools: {sorted(set(required) - entries.keys())}")
    result = {**data, "manifest_path": str(path), "manifest_sha256": sha256(path), "tools": {}}
    for name, entry in entries.items():
        if not isinstance(entry, dict) or not {"path", "sha256", "version", "source_commit", "build_command"} <= entry.keys():
            raise ValueError(f"missing provenance fields for tool: {name}")
        if not isinstance(entry["path"], str) or not entry["path"]:
            raise ValueError(f"missing tool path: {name}")
        if not isinstance(entry["version"], str) or not entry["version"]:
            raise ValueError(f"missing tool version: {name}")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError(f"invalid tool SHA256: {name}")
        tool_path = Path(entry["path"]).expanduser()
        if not tool_path.is_absolute():
            tool_path = ROOT / tool_path
        row = {**entry, "path": str(tool_path.resolve())}
        result["tools"][name] = verify_tool(row) if verify else row
    return result
