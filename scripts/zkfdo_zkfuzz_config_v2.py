#!/usr/bin/env python3
"""Resolve platform-bound zkFuzz profiles without launching a process (v2).

The returned mutation_config is the configuration supplied to the engine. A
candidate's post-adaptation runtime configuration must be recorded separately.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import platform
import sys
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_PROFILE_PATH = ROOT / "configs/zkfuzz_defaults_2.2.1_v1.json"
UINT_FIELDS = {
    "seed", "program_population_size", "input_population_size", "max_generations",
    "num_eliminated_individuals", "max_num_mutation_points", "input_update_interval",
    "input_generation_max_iteration", "binary_mode_search_level",
}
FLOAT_FIELDS = {
    "mutation_rate", "crossover_rate", "operator_mutation_rate", "runtime_mutation_rate",
    "input_generation_crossover_rate", "input_generation_mutation_rate",
    "input_generation_singlepoint_mutation_rate", "binary_mode_prob",
    "binary_mode_warmup_round", "zero_div_attempt_prob", "statement_deletion_prob",
    "add_random_const_prob",
}
BOOL_FIELDS = {
    "dissable_runtime_mutation_for_hash_check",
    "dissable_heuristic_for_invalid_array_subscript", "save_fitness_scores",
}
STRING_FIELDS = {"input_initialization_method", "trace_mutation_method", "fitness_function"}
FIELDS = UINT_FIELDS | FLOAT_FIELDS | BOOL_FIELDS | STRING_FIELDS | {
    "random_value_ranges", "random_value_probs",
}
VALUE_OPTIONS = {
    "--prime", "--debug_prime", "--heuristics_range", "--search_mode",
    "--path_to_mutation_setting", "--path_to_whitelist", "-l",
}
FLAG_OPTIONS = {
    "--constraint_assert_dissabled", "--lessthan_dissabled", "--print_ast",
    "--print_stats", "--print_stats_csv", "--symbolic_template_params", "--save_output",
}
PRIMES = {"bn128", "bls12381", "goldilocks", "grumpkin", "pallas", "vesta", "secq256r1"}
SEARCH_MODES = {"ga", "quick", "full", "heuristics", "off"}


class ConfigurationError(ValueError):
    """Configuration cannot be established before execution."""


def _read(path):
    path = Path(path)
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise ConfigurationError(f"cannot read configuration evidence: {path}: {exc}") from exc
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ConfigurationError(f"configuration evidence changed while reading: {path}")
    return raw, hashlib.sha256(raw).hexdigest()


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ConfigurationError(f"non-JSON numeric constant: {value}")


def _json_file(path):
    raw, digest = _read(path)
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_pairs,
                          parse_constant=_invalid_constant)
    except (ValueError, UnicodeError) as exc:
        raise ConfigurationError(f"invalid settings JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"settings JSON must be an object: {path}")
    return data, digest


def _path(value, base):
    p = Path(value).expanduser()
    return (p if p.is_absolute() else base / p).resolve()


def _reference(ref):
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise ConfigurationError("missing profile evidence reference")
    path = _path(ref["path"], ROOT)
    _, actual = _read(path)
    if actual != ref.get("sha256"):
        raise ConfigurationError(f"profile evidence SHA256 differs: {path}")


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _validate_mutation(config):
    if not isinstance(config, dict) or set(config) != FIELDS:
        raise ConfigurationError("mutation config must contain exactly the 29 supported fields")
    result = copy.deepcopy(config)
    for key in UINT_FIELDS:
        if type(result[key]) is not int or not 0 <= result[key] <= 2**64 - 1:
            raise ConfigurationError(f"{key} must be a 64-bit unsigned integer")
    for key in FLOAT_FIELDS:
        if not _finite_number(result[key]):
            raise ConfigurationError(f"{key} must be a finite number")
        result[key] = float(result[key])
    for key in BOOL_FIELDS:
        if type(result[key]) is not bool:
            raise ConfigurationError(f"{key} must be a boolean")
    for key in STRING_FIELDS:
        if not isinstance(result[key], str):
            raise ConfigurationError(f"{key} must be a string")
    allowed_methods = {
        "input_initialization_method": {"random", "fitness", "coverage"},
        "trace_mutation_method": {"naive", "constant", "constant_operator",
                                  "constant_operator_add", "constant_operator_delete"},
        "fitness_function": {"error", "const"},
    }
    for key, supported in allowed_methods.items():
        if result[key] not in supported:
            raise ConfigurationError(f"unsupported {key}: {result[key]!r}")
    ranges = result["random_value_ranges"]
    if not isinstance(ranges, list):
        raise ConfigurationError("random_value_ranges must be a list of decimal-string pairs")
    for pair in ranges:
        if (not isinstance(pair, list) or len(pair) != 2
                or any(not isinstance(v, str) or re.fullmatch(r"[+-]?[0-9]+", v) is None for v in pair)):
            raise ConfigurationError("random_value_ranges must contain decimal-string pairs")
        pair[:] = [str(int(value)) for value in pair]
    probs = result["random_value_probs"]
    if not isinstance(probs, list) or any(not _finite_number(v) for v in probs):
        raise ConfigurationError("random_value_probs must be a list of finite numbers")
    result["random_value_probs"] = [float(v) for v in probs]
    return result


def _architecture(value):
    aliases = {"aarch64": "arm64", "amd64": "x86_64"}
    text = str(value).lower()
    return aliases.get(text, text)


def _validate_platform_profile(profile, path):
    if profile["schema"] == "zkfuzz-defaults-v1":
        # The preserved Mac profile predates platform fields. Its compatibility
        # path is deliberately restricted; a copied Linux profile needs v2.
        if (sys.platform != "darwin" or _architecture(platform.machine()) != "arm64"
                or path != DEFAULTS_PROFILE_PATH.resolve()):
            raise ConfigurationError("legacy defaults profile is only valid at its original Darwin arm64 path")
        return
    if profile.get("platform") != sys.platform:
        raise ConfigurationError("defaults profile platform differs from execution host")
    if _architecture(profile.get("architecture")) != _architecture(platform.machine()):
        raise ConfigurationError("defaults profile architecture differs from execution host")


def _validate_paired_probe(profile, binary_sha):
    attestation = profile["attestation"]
    if attestation.get("binary_sha256") != binary_sha:
        raise ConfigurationError("paired-probe attestation binary SHA256 differs")
    probe, _ = _json_file(_path(attestation["paired_probe"]["path"], ROOT))
    if probe.get("schema") != "zkfuzz-settings-paired-probe-v2":
        raise ConfigurationError("platform profile requires a v2 paired-probe receipt")
    if (probe.get("platform") != profile["platform"]
            or _architecture(probe.get("architecture")) != _architecture(profile["architecture"])
            or probe.get("binary_sha256") != binary_sha):
        raise ConfigurationError("paired-probe platform or binary binding differs")
    expected = {"5_flag", "6_target_output", "7_assignment", "runtime_config"}
    checks = probe.get("checks")
    if (probe.get("equivalent") is not True or not isinstance(checks, dict)
            or set(checks) != expected or any(v is not True for v in checks.values())):
        raise ConfigurationError("paired-probe equivalence checks did not pass")
    observations = probe.get("observations")
    settings = probe.get("settings")
    if not isinstance(observations, list) or len(observations) != 2:
        raise ConfigurationError("paired-probe requires two runtime observations")
    if not isinstance(settings, list) or len(settings) != 2:
        raise ConfigurationError("paired-probe requires seed-only and expanded settings")
    observed_values = []
    for ref in observations:
        _reference(ref)
        observation, _ = _json_file(_path(ref["path"], ROOT))
        if ((observation.get("binary") or {}).get("sha256") != binary_sha
                or observation.get("status") != "completed"
                or observation.get("measurement_valid") is not True
                or observation.get("cleanup_complete") is not True):
            raise ConfigurationError("paired-probe observation is invalid or from another binary")
        candidates = observation.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ConfigurationError("paired-probe requires one synthetic candidate per arm")
        candidate_ref = candidates[0]
        _reference(candidate_ref)
        candidate, _ = _json_file(_path(candidate_ref["path"], ROOT))
        fields = ("5_flag", "6_target_output", "7_assignment")
        if any(key not in candidate for key in fields):
            raise ConfigurationError("paired-probe candidate lacks comparison fields")
        runtime_config = _validate_mutation(candidate_ref.get("mutation_config"))
        observed_values.append(({key: candidate[key] for key in fields}, runtime_config))
    if observed_values[0] != observed_values[1]:
        raise ConfigurationError("paired-probe observations differ despite the receipt")
    supplied = []
    for ref in settings:
        _reference(ref)
        values, _ = _json_file(_path(ref["path"], ROOT))
        supplied.append(values)
    if set(supplied[0]) != {"seed"} or set(supplied[1]) != FIELDS:
        raise ConfigurationError("paired-probe settings must be seed-only then all 29 fields")
    seed = supplied[0]["seed"]
    if type(seed) is not int or not 1 <= seed <= 2**64 - 1:
        raise ConfigurationError("paired-probe seed must be a nonzero u64")
    expected_config = {**profile["mutation_config"], "seed": seed}
    if supplied[1] != expected_config:
        raise ConfigurationError("paired-probe expanded settings differ from profile defaults")


def _profile(tool_entry, defaults_profile_path):
    selected = defaults_profile_path or tool_entry.get("defaults_profile_path")
    if selected is None:
        if sys.platform != "darwin":
            raise ConfigurationError("platform-specific defaults_profile_path is required")
        selected = DEFAULTS_PROFILE_PATH
    path = _path(selected, ROOT)
    profile, digest = _json_file(path)
    if profile.get("schema") not in {"zkfuzz-defaults-v1", "zkfuzz-defaults-v2"} or profile.get("status") != "ready":
        raise ConfigurationError("zkFuzz defaults profile is not ready; binary probe is required")
    expected_profile_sha = tool_entry.get("defaults_profile_sha256")
    if expected_profile_sha is not None and digest != expected_profile_sha:
        raise ConfigurationError("defaults profile SHA256 differs from manifest")
    _validate_platform_profile(profile, path)
    binary_sha = tool_entry.get("sha256")
    if not isinstance(binary_sha, str) or re.fullmatch(r"[0-9a-f]{64}", binary_sha) is None:
        raise ConfigurationError("missing pinned zkFuzz binary SHA256")
    if profile.get("binary_sha256") != binary_sha:
        raise ConfigurationError("defaults profile is for a different zkFuzz binary")
    if not isinstance(tool_entry.get("path"), str) or not tool_entry["path"]:
        raise ConfigurationError("missing pinned zkFuzz executable path")
    binary_path = _path(tool_entry["path"], ROOT)
    _, actual = _read(binary_path)
    if actual != binary_sha:
        raise ConfigurationError("zkFuzz executable SHA256 differs")
    attestation = profile.get("attestation", {})
    if not isinstance(attestation, dict) or attestation.get("status") != "passed":
        raise ConfigurationError("defaults profile has no passed paired-probe attestation")
    _reference(attestation.get("paired_probe"))
    sources = profile.get("source_files")
    if not isinstance(sources, list) or len(sources) != 3:
        raise ConfigurationError("defaults profile must pin main, input_user and mutation_config sources")
    for ref in sources:
        _reference(ref)
    defaults = _validate_mutation(profile.get("mutation_config"))
    if profile["schema"] == "zkfuzz-defaults-v2":
        _validate_paired_probe(profile, binary_sha)
    whitelist = profile.get("default_whitelist")
    if not isinstance(whitelist, list) or any(not isinstance(x, str) for x in whitelist):
        raise ConfigurationError("invalid default whitelist profile")
    semantic = profile.get("semantic_defaults")
    if not isinstance(semantic, dict) or set(semantic) != {"prime", "debug_prime", "heuristics_range", "search_mode"}:
        raise ConfigurationError("incomplete semantic defaults profile")
    return profile, defaults, {"path": str(path), "sha256": digest,
                               "binary_sha256": binary_sha, "attestation": attestation}


def _merge(defaults, base):
    if not isinstance(base, dict):
        raise ConfigurationError("base mutation settings must be an object")
    unknown = set(base) - FIELDS
    if unknown:
        raise ConfigurationError(f"unsupported mutation settings: {sorted(unknown)}")
    return _validate_mutation({**copy.deepcopy(defaults), **base})


def materialize_settings(base, seed, tool_entry, *, defaults_profile_path=None):
    """Expand source-pinned defaults and base values; override only the pass seed.

    The caller writes this complete dictionary to a new JSON file and records its
    hash before passing that actual file to resolve_configuration and zkFuzz.
    """
    _, defaults, _ = _profile(tool_entry, defaults_profile_path)
    if type(seed) is not int or not 1 <= seed <= 2**64 - 1:
        raise ConfigurationError("reproducible pass seed must be a nonzero u64")
    # Validate the supplied base before overriding seed, including its type.
    merged = _merge(defaults, base)
    merged["seed"] = seed
    return merged


def _parse(argv):
    if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(x, str) or "\0" in x for x in argv):
        raise ConfigurationError("argv must be nonempty strings without NUL")
    values, flags, libraries, positional = {}, set(), [], []
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "--":
            positional.extend(argv[i + 1:])
            break
        option, equal, inline = token.partition("=")
        if option in VALUE_OPTIONS:
            if option != "-l" and option in values:
                raise ConfigurationError(f"duplicate option: {option}")
            if equal:
                if option == "-l":
                    raise ConfigurationError("use -l PATH; compact short options are unsupported")
                value = inline
            else:
                i += 1
                if i >= len(argv) or argv[i].startswith("-"):
                    raise ConfigurationError(f"missing value for {option}")
                value = argv[i]
            if not value:
                raise ConfigurationError(f"empty value for {option}")
            if option == "-l":
                libraries.append(value)
            else:
                values[option] = value
        elif token in FLAG_OPTIONS:
            if token in flags:
                raise ConfigurationError(f"duplicate option: {token}")
            flags.add(token)
        elif token.startswith("-"):
            raise ConfigurationError(f"unsupported or unknown zkFuzz option: {token}")
        else:
            positional.append(token)
        i += 1
    if len(positional) > 1:
        raise ConfigurationError("zkFuzz accepts only one circuit input path")
    return values, flags, libraries, positional[0] if positional else "./circuit.circom"


def _rust_lines(raw):
    """Match BufRead.lines(): only LF/CRLF delimiters, with spaces preserved."""
    text = raw.decode("utf-8")
    if not text:
        return []
    lines = text.split("\n")
    ended = text.endswith("\n")
    if ended:
        lines.pop()
    return [line[:-1] if (i < len(lines) - 1 or ended) and line.endswith("\r") else line
            for i, line in enumerate(lines)]


def resolve_configuration(argv, tool_entry, *, defaults_profile_path=None):
    profile, defaults, profile_ref = _profile(tool_entry, defaults_profile_path)
    values, flags, libraries, circuit = _parse(argv)
    cwd = _path(tool_entry.get("cwd", Path.cwd()), ROOT)
    binary_path = _path(tool_entry["path"], ROOT)
    if _path(argv[0], cwd) != binary_path:
        raise ConfigurationError("argv executable differs from pinned zkFuzz tool")
    settings_name = values.get("--path_to_mutation_setting", "none")
    settings_ref = None
    settings_path = _path(settings_name, cwd)
    # Unlike whitelist's sentinel, load_config_from_json attempts File::open("none").
    if settings_name == "none" and not settings_path.exists():
        config = copy.deepcopy(defaults)
    else:
        base, settings_sha = _json_file(settings_path)
        config = _merge(defaults, base)
        settings_ref = {"path": str(settings_path), "sha256": settings_sha,
                        "provided_fields": sorted(base), "all_29_fields_explicit": set(base) == FIELDS}
    if config["seed"] == 0:
        raise ConfigurationError("seed 0 selects an arbitrary runtime seed; reproducible mode refuses it")
    semantic = copy.deepcopy(profile["semantic_defaults"])
    for key in semantic:
        if "--" + key in values:
            semantic[key] = values["--" + key]
    if semantic["prime"] not in PRIMES or semantic["search_mode"] not in SEARCH_MODES:
        raise ConfigurationError("unsupported prime or search_mode")
    for key in ("debug_prime", "heuristics_range"):
        value = semantic[key]
        if not isinstance(value, str) or re.fullmatch(r"[+-]?[0-9]+", value) is None:
            raise ConfigurationError(f"{key} must be an explicit decimal integer")
        semantic[key] = str(int(value))
    whitelist_name = values.get("--path_to_whitelist", "none")
    whitelist_ref = None
    lines = profile["default_whitelist"]
    if whitelist_name != "none":
        whitelist_path = _path(whitelist_name, cwd)
        raw, whitelist_sha = _read(whitelist_path)
        try:
            lines = _rust_lines(raw)
        except UnicodeError as exc:
            raise ConfigurationError(f"whitelist is not UTF-8: {whitelist_path}") from exc
        whitelist_ref = {"path": str(whitelist_path), "sha256": whitelist_sha, "lines": lines}
    semantic.update({
        "whitelist": sorted(set(lines)),
        "static_checks": {"unused_outputs": semantic["search_mode"] != "off",
                          "lessthan": "--lessthan_dissabled" not in flags,
                          "constraint_asserts": "--constraint_assert_dissabled" not in flags},
        "flags": {name[2:]: name in flags for name in sorted(FLAG_OPTIONS)},
        "mutation_config_active": semantic["search_mode"] == "ga",
    })
    return {
        "schema": "zkfuzz-effective-config-v1", "argv": list(argv),
        "binary_sha256": tool_entry["sha256"], "mutation_config": config,
        "semantic_settings": semantic,
        "execution_paths": {"cwd": str(cwd), "input_program": str(_path(circuit, cwd)),
                            "link_libraries": [str(_path(p, cwd)) for p in libraries]},
        "provenance": {"defaults_profile": profile_ref, "mutation_settings_file": settings_ref,
                       "whitelist_file": whitelist_ref,
                       "configuration_stage": "initial input configuration, not post-adaptation runtime state",
                       "runtime_mutation_config": None,
                       "runtime_mutation_config_reason": "No candidate runtime observation was supplied. The engine may adapt ranges/probabilities and binary_mode_prob during execution.",
                       "comparison_excludes": ["argv transport paths", "input_program", "link_libraries", "file locations"]},
    }


def compare_w_s(left, right):
    """Compare complete input settings, including the actual per-pass seed."""
    for value in (left, right):
        if value.get("schema") != "zkfuzz-effective-config-v1":
            raise ConfigurationError("comparison requires resolved zkFuzz configurations")
        _validate_mutation(value.get("mutation_config"))
        if not isinstance(value.get("semantic_settings"), dict) or not value.get("binary_sha256"):
            raise ConfigurationError("comparison configuration is incomplete")
    differences = []

    def walk(path, a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a or key not in b:
                    differences.append({"field": f"{path}.{key}", "left": a.get(key), "right": b.get(key)})
                else:
                    walk(f"{path}.{key}", a[key], b[key])
        elif a != b:
            differences.append({"field": path, "left": a, "right": b})

    for key in ("binary_sha256", "mutation_config", "semantic_settings"):
        walk(key, left[key], right[key])
    return {"equal": not differences, "differences": differences}
