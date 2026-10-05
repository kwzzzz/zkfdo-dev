#!/usr/bin/env python3
"""Read-only Circomkit JSON discovery and deterministic C-03 main generation.

No repository program, package manager, compiler, witness or search engine runs
here. All paths are resolved inside the pinned checkout. Generated files belong
in the caller's ignored run directory, never in the checkout.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SKIP_DIRECTORIES = {".git", "node_modules", ".yarn", ".pnpm-store"}
MAX_JSON_BYTES = 8 * 1024 * 1024


class ConfigFailure(ValueError):
    def __init__(self, failure_type, reason):
        super().__init__(reason)
        self.failure_type = failure_type


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _failure(failure_type, reason, **identity):
    return {**identity, "generation_status": "failure", "failure_type": failure_type,
            "failure_reason": reason}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigFailure("config_duplicate_json_key", "duplicate JSON object key")
        result[key] = value
    return result


def _json(path):
    if not path.is_file():
        raise ConfigFailure("config_missing_file", "referenced JSON file is absent")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ConfigFailure("config_size_limit", "JSON file exceeds the fixed 8 MiB limit")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        if isinstance(error, ConfigFailure):
            raise
        raise ConfigFailure("config_invalid_json", "file is not strict JSON") from error


def _inside(root, base, value, kind):
    if not isinstance(value, str) or not value or any(c in value for c in ('\x00', '\n', '\r', '"', '\\')):
        raise ConfigFailure("config_invalid_path", f"{kind} is not a supported path string")
    if Path(value).is_absolute():
        raise ConfigFailure("config_path_outside_checkout", f"{kind} must be checkout-relative")
    path = base / value
    try:
        path.resolve().relative_to(root)
    except (ValueError, RuntimeError) as error:
        raise ConfigFailure("config_path_outside_checkout", f"{kind} escapes the checkout") from error
    return path.resolve()


def _ref(root, path):
    return {"path": path.relative_to(root).as_posix(), "sha256": digest(path)}


def _literal(value, depth=0):
    if depth > 16:
        raise ConfigFailure("config_unsupported_params", "parameter array nesting exceeds 16")
    if type(value) is int:
        return str(value)
    if isinstance(value, list) and value:
        return "[" + ", ".join(_literal(item, depth + 1) for item in value) + "]"
    raise ConfigFailure("config_unsupported_params", "parameters require integer literals or nonempty integer arrays")


def _identifier(value, kind):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ConfigFailure("config_invalid_identifier", f"{kind} is not a Circom identifier")
    return value


def _public(spec):
    if "public" in spec and "pubs" in spec and spec["public"] != spec["pubs"]:
        raise ConfigFailure("config_ambiguous_public", "public and pubs fields disagree")
    values = spec.get("public", spec.get("pubs", []))
    if not isinstance(values, list):
        raise ConfigFailure("config_invalid_public", "public/pub(s) must be an identifier list")
    for value in values:
        _identifier(value, "public signal")
    if len(values) != len(set(values)):
        raise ConfigFailure("config_ambiguous_public", "public signal list has duplicates")
    return values


def _config_paths(root):
    found = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRECTORIES and not (Path(directory) / d).is_symlink())
        for name in sorted(set(files) & {"circomkit.json", "circuits.json"}):
            found.append(Path(directory) / name)
    return sorted(found)


def discover_config_entrypoints(repo_root):
    """Inventory all JSON-declared entries, preserving each malformed entry.

    ``entries`` is the generation denominator. ``failures`` covers configuration
    files whose entry count is unknowable. Output status does not assert that a
    main compiles, nor that its configuration's optimization/prime is adopted.
    """
    root = Path(repo_root).resolve()
    paths = _config_paths(root)
    output = {"schema_version": 1, "config_files": [], "entries": [], "failures": [],
              "repository_programs_executed": 0}
    claimed = set()
    contexts = []
    for path in paths:
        if path.name != "circomkit.json":
            continue
        identity = {"circomkit_path": path.relative_to(root).as_posix()}
        try:
            path = _inside(root, root, identity["circomkit_path"], "circomkit")
            kit = _json(path)
            identity["circomkit"] = _ref(root, path)
            output["config_files"].append(identity["circomkit"])
            if not isinstance(kit, dict):
                raise ConfigFailure("config_invalid_shape", "circomkit root must be an object")
            circuits_path = _inside(root, path.parent, kit.get("circuits", "./circuits.json"), "circuits")
            claimed.add(circuits_path)
            circuit_dir = _inside(root, path.parent, kit.get("dirCircuits", "./circuits"), "dirCircuits")
            circuits = _json(circuits_path)
            identity["circuits"] = _ref(root, circuits_path)
            output["config_files"].append(identity["circuits"])
            if not isinstance(circuits, dict):
                raise ConfigFailure("config_invalid_shape", "circuits root must be a named-entry object")
            contexts.append((identity, kit, circuits, circuit_dir))
        except (ConfigFailure, OSError) as error:
            output["failures"].append(_failure(getattr(error, "failure_type", "config_read_failure"), str(error), **identity))
    for path in paths:
        if path.name == "circuits.json" and path.resolve() not in claimed:
            output["failures"].append(_failure("config_without_circomkit_context",
                "no circomkit JSON names this file; base directory is not guessed",
                circuits_path=path.relative_to(root).as_posix()))
    for identity, kit, circuits, circuit_dir in contexts:
        for name, spec in sorted(circuits.items()):
            entry = {**identity, "config_key": name, "entrypoint_kind": "config_generated",
                     "config_defaults_applied": [key for key in ("circuits", "dirCircuits") if key not in kit],
                     "declared_compile_settings": {key: kit[key] for key in ("version", "prime", "optimization") if key in kit},
                     "compiler_settings_source": "C-03 procedure, not circomkit compile settings"}
            try:
                if not isinstance(spec, dict):
                    raise ConfigFailure("config_invalid_entry", "circuit definition must be an object")
                template = _identifier(spec.get("template"), "template")
                params = spec.get("params", [])
                if not isinstance(params, list):
                    raise ConfigFailure("config_unsupported_params", "params must be a list")
                literal_params = [_literal(value) for value in params]
                public = _public(spec)
                value = spec.get("file")
                if not isinstance(value, str) or not value:
                    raise ConfigFailure("config_missing_source", "circuit definition has no file")
                source = _inside(root, circuit_dir, value if value.endswith(".circom") else value + ".circom", "file")
                if not source.is_file():
                    raise ConfigFailure("config_missing_source", "declared Circom source does not exist")
                entry.update({"source_path": source.relative_to(root).as_posix(), "source_sha256": digest(source),
                              "circuit_directory": circuit_dir.relative_to(root).as_posix(), "template": template,
                              "params": params, "literal_params": literal_params, "public": public,
                              "generation_status": "ready", "failure_type": None, "failure_reason": None})
            except (ConfigFailure, OSError) as error:
                entry.update(_failure(getattr(error, "failure_type", "config_read_failure"), str(error)))
            output["entries"].append(entry)
    return output


def generate_config_entrypoints(repo_root, output_dir):
    """Write a new directory of deterministic mains; never overwrite any file.

    Returned entry ``path`` is absolute for the compilation caller. Its SHA-256,
    source/config hashes, logical key and original public ordering are retained.
    """
    root = Path(repo_root).resolve()
    directory = Path(output_dir).resolve()
    if directory == root or root in directory.parents:
        raise ValueError("generated entrypoints must not modify the pinned checkout")
    if directory.exists():
        raise FileExistsError("use a new generation output directory")
    result = discover_config_entrypoints(root)
    directory.mkdir(parents=True)
    for entry in result["entries"]:
        if entry["generation_status"] != "ready":
            continue
        logical_id = entry["circomkit_path"] + "\x00" + entry["config_key"]
        identifier = hashlib.sha256(logical_id.encode()).hexdigest()
        wrapper = directory / f"config-{identifier}.circom"
        source = root / entry["source_path"]
        include = os.path.relpath(source, directory).replace(os.sep, "/")
        if any(c in include for c in ('"', "\n", "\r", "\\")):
            entry.update(_failure("config_invalid_generated_include", "output location cannot be expressed as a Circom include"))
            continue
        public = " {public [" + ", ".join(entry["public"]) + "]}" if entry["public"] else ""
        content = ("pragma circom 2.2.3;\n" + f'include "{include}";\n' +
                   f"component main{public} = {entry['template']}({', '.join(entry['literal_params'])});\n")
        with wrapper.open("x", encoding="utf-8") as handle:
            handle.write(content)
        entry.update({"generation_status": "generated", "path": str(wrapper), "sha256": digest(wrapper),
                      "logical_id_sha256": identifier})
    result["generated_count"] = sum(entry["generation_status"] == "generated" for entry in result["entries"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = (generate_config_entrypoints(args.repo_root, args.output_dir) if args.output_dir
              else discover_config_entrypoints(args.repo_root))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
