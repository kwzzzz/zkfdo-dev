#!/usr/bin/env python3
"""Select and verify N6-J1 honest base inputs, one revision at a time.

The fixed N5 order is zkbugs input, matching L-series input, committed JSON,
unchanged project test/input tool, then all zero. Input values are written only
under the ignored output directory and are never included in the index or logs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json"
DEFAULT_OUTPUT = ROOT / "runs/n6-j1-2026-10-09.noindex/base-inputs"
CIRCOM = Path("/Users/miiz/.cargo/bin/circom")
CIRCOM_SHA256 = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
CAPTURE = ROOT / "scripts/n6_j1_capture.cjs"
CHECKER_TEST = "n6_j1_r1cs_check"
STAGES = ("a_zkbugs", "b_l_series", "c_committed_json", "d_project_test", "e_zero")
SIGNAL_NAME = re.compile(r"^main\.([A-Za-z_][A-Za-z_0-9]*)((?:\[\d+\])*)$")
INDEX_PART = re.compile(r"\[(\d+)\]")
MAIN_CALL = re.compile(
    r"\bcomponent\s+main\s*(?:\{[^}]*\}\s*)?=\s*"
    r"([A-Za-z_][A-Za-z_0-9]*\s*\([^;]*?\))\s*;",
    re.DOTALL,
)
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "lib"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def dump_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(data, output, indent=2, ensure_ascii=False, sort_keys=True)
        output.write("\n")
    os.replace(temporary, path)


def workspace_path(path: str | Path) -> Path:
    value = Path(path)
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


def read_r1cs_shape(path: Path) -> dict[str, int]:
    """Read only the R1CS header, enough to identify main input wires."""
    with path.open("rb") as source:
        if source.read(4) != b"r1cs":
            raise ValueError("r1cs_magic")
        version, count = struct.unpack("<II", source.read(8))
        if version != 1 or count != 3:
            raise ValueError("r1cs_version_or_sections")
        header = None
        for _ in range(count):
            kind, length = struct.unpack("<IQ", source.read(12))
            if kind == 1:
                header = source.read(length)
            else:
                source.seek(length, 1)
    if header is None:
        raise ValueError("r1cs_header_missing")
    width = struct.unpack_from("<I", header, 0)[0]
    offset = 4 + width
    if width == 0 or offset + 28 != len(header):
        raise ValueError("r1cs_header_invalid")
    wires, outputs, public, private = struct.unpack_from("<IIII", header, offset)
    labels = struct.unpack_from("<Q", header, offset + 16)[0]
    constraints = struct.unpack_from("<I", header, offset + 24)[0]
    if 1 + outputs + public + private > wires:
        raise ValueError("r1cs_input_range_invalid")
    return {"wires": wires, "outputs": outputs, "public_inputs": public,
            "private_inputs": private, "labels": labels, "constraints": constraints}


def main_input_names(sym: Path, declared_roots: set[str]) -> list[str]:
    if not declared_roots:
        raise ValueError("main_input_declarations_missing")
    names = set()
    with sym.open(encoding="utf-8") as source:
        for line in source:
            fields = line.rstrip("\n").split(",", 3)
            if len(fields) != 4:
                raise ValueError("sym_format")
            match = SIGNAL_NAME.fullmatch(fields[3])
            if match and match.group(1) in declared_roots:
                names.add(fields[3])
    missing = declared_roots - set(input_keys(list(names)))
    if missing:
        raise ValueError("main_input_symbol_missing")
    return sorted(names)


def prior_main_input_names(sym: Path, shape: dict[str, int]) -> list[str]:
    """Historical wire-range assumption, retained only for static diagnostics."""
    first = 1 + shape["outputs"]
    last = first + shape["public_inputs"] + shape["private_inputs"]
    names: dict[int, list[str]] = {}
    with sym.open(encoding="utf-8") as source:
        for line in source:
            fields = line.rstrip("\n").split(",", 3)
            if len(fields) != 4:
                raise ValueError("sym_format")
            wire = int(fields[1])
            if first <= wire < last and SIGNAL_NAME.fullmatch(fields[3]):
                names.setdefault(wire, []).append(fields[3])
    result = []
    for wire in range(first, last):
        options = sorted(names.get(wire, []))
        if not options:
            raise ValueError("main_input_symbol_missing")
        result.append(options[0])
    return result


def input_keys(names: list[str]) -> list[str]:
    return sorted({SIGNAL_NAME.fullmatch(name).group(1) for name in names})


def zero_input(names: list[str]) -> dict[str, object]:
    """Build an exact, rectangular all-zero object from direct main input names."""
    paths: dict[str, set[tuple[int, ...]]] = {}
    for name in names:
        match = SIGNAL_NAME.fullmatch(name)
        if match is None:
            raise ValueError("main_input_symbol_invalid")
        paths.setdefault(match.group(1), set()).add(
            tuple(int(value) for value in INDEX_PART.findall(match.group(2)))
        )

    def build(indices: set[tuple[int, ...]]) -> object:
        if indices == {()}:
            return 0
        if () in indices or not indices:
            raise ValueError("main_input_shape_mixed")
        highest = max(index[0] for index in indices)
        result = []
        for number in range(highest + 1):
            child = {index[1:] for index in indices if index[0] == number}
            if not child:
                raise ValueError("main_input_shape_sparse")
            result.append(build(child))
        return result

    return {key: build(indices) for key, indices in sorted(paths.items())}


def project_family(path: Path) -> str | None:
    name = str(path).lower()
    for family, aliases in (
        ("inference", ("inference", "subnet-2-circom")),
        ("banyan", ("banyan", "hot-proofs-blake3-circom")),
        ("zkemail", ("zkemail", "zk-email-verify")),
    ):
        if any(alias in name for alias in aliases):
            return family
    return None


def l_series_inputs() -> dict[tuple[str, str], list[Path]]:
    """Index L-series inputs by both source project family and entrypoint path."""
    found: dict[tuple[str, str], list[Path]] = {}
    request_paths = []
    for group in sorted(ROOT.glob("runs/l[0-9][0-9]*")):
        request_paths.extend(group.glob("**/requests/*.json"))
        request_paths.extend(group.glob("**/requests/*/*.json"))
    for request_path in sorted(set(request_paths)):
        if request_path.name == "index.json":
            continue
        try:
            request = json.loads(request_path.read_text())
            if request.get("schema") != "zkfdo-lifting-request-v1":
                continue
            base = request_path.parent
            source_root = (base / request["source_root"]).resolve()
            entrypoint = (base / request["entrypoint"]).resolve()
            relative = entrypoint.relative_to(source_root).as_posix()
            family = project_family(source_root)
            if family is None:
                continue
            input_path = (base / request["base_input"]).resolve()
            if input_path.is_file():
                found.setdefault((family, relative), []).append(input_path)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    for key, paths in found.items():
        dedup: dict[str, Path] = {}
        for path in paths:
            dedup.setdefault(sha256(path), path)
        found[key] = list(dedup.values())
    return found


def committed_json_paths(row: dict) -> tuple[list[Path], str | None]:
    project = workspace_path(row["project_root"])
    repository_value = row.get("git_repository_path") or row.get("source_project_path")
    if not repository_value:
        return [], "committed_json_provenance_unavailable"
    repository = workspace_path(repository_value)
    revision = row.get("revision_commit")
    if not revision or not (repository / ".git").exists():
        return [], "committed_json_git_unavailable"
    command = ["git", "-C", str(repository), "ls-tree", "-r", "--name-only", revision]
    listing = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if listing.returncode:
        return [], "committed_json_git_list_failed"
    paths = []
    for relative in sorted(listing.stdout.splitlines()):
        candidate = Path(relative)
        if candidate.suffix.lower() != ".json" or "node_modules" in candidate.parts:
            continue
        snapshot = project / candidate
        if not snapshot.is_file():
            continue
        # A source snapshot can contain generated edits. Only byte-identical
        # files from the recorded commit count as committed candidates.
        committed = subprocess.run(
            ["git", "-C", str(repository), "show", f"{revision}:{relative}"],
            capture_output=True, timeout=60,
        )
        if committed.returncode or hashlib.sha256(committed.stdout).hexdigest() != sha256(snapshot):
            continue
        paths.append(snapshot)
    return paths, None


def checker_binary(output: Path) -> Path:
    environment = os.environ.copy()
    environment["CARGO_TARGET_DIR"] = str(output / "rust-checker-target")
    build = subprocess.run(
        ["cargo", "test", "--test", CHECKER_TEST, "--no-run", "--message-format=json"],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=1800,
    )
    if build.returncode:
        raise RuntimeError("rust_checker_build_failed")
    executables = []
    for line in build.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("reason") == "compiler-artifact" and event.get("target", {}).get("name") == CHECKER_TEST:
            executables.append(event.get("executable"))
    if not executables or not executables[-1]:
        raise RuntimeError("rust_checker_executable_missing")
    return Path(executables[-1]).resolve()


def run_quiet(command: list[str], timeout: float, *, cwd: Path | None = None,
              env: dict[str, str] | None = None) -> tuple[int | None, float, str]:
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=max(1, timeout))
        return result.returncode, time.monotonic() - started, "completed"
    except subprocess.TimeoutExpired:
        return None, time.monotonic() - started, "timeout"
    except OSError:
        return None, time.monotonic() - started, "spawn_failed"


def project_error_kind(output: bytes) -> str:
    """Classify a test failure without retaining or reporting its output."""
    if b"ReferenceError: require is not defined" in output:
        return "node_esm_cjs_loader"
    if b"ERR_MODULE_NOT_FOUND" in output or b"MODULE_NOT_FOUND" in output or b"Cannot find module" in output:
        return "module_missing"
    if b"ERR_UNKNOWN_FILE_EXTENSION" in output:
        return "node_file_loader"
    if b"CompileError" in output:
        return "wasm_compile"
    if b"TS7016" in output or b"error TS" in output:
        return "typescript_build"
    if b"RAW_JWT" in output or b"JWK_MODULOUS" in output or b"BLINDING_FACTOR" in output:
        return "project_environment_missing"
    if b"yarn" in output and b"not found" in output:
        return "project_package_manager_unavailable"
    if b"ENOTFOUND" in output or b"ECONNREFUSED" in output or b"npm ERR! code ENOTCACHED" in output:
        return "network_or_install_required"
    for name in ("ReferenceError", "TypeError", "SyntaxError", "AssertionError", "Error"):
        if name.encode() in output:
            return name
    return "unclassified_failure"


def run_project_quiet(command: list[str], timeout: float, *, cwd: Path,
                      env: dict[str, str]) -> tuple[int | None, float, str, str | None]:
    started = time.monotonic()
    if timeout <= 0:
        return None, 0.0, "timeout", None
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
        except OSError as error:
            return None, time.monotonic() - started, "spawn_failed", f"os_errno_{error.errno}"
        try:
            code = process.wait(timeout=max(1, timeout))
            disposition = "completed"
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            code, disposition = None, "timeout"
        stdout.seek(0)
        stderr.seek(0)
        # Only a bounded in-memory diagnostic scan; both temporary files are
        # discarded and no original test output enters the selection index.
        output = stdout.read(1 << 20) + stderr.read(1 << 20)
    error_kind = project_error_kind(output) if disposition == "completed" and code else None
    return code, time.monotonic() - started, disposition, error_kind


def validate_input(path: Path, keys: set[str], artifacts: dict[str, Path], checker: Path,
                   snarkjs: Path, attempt_dir: Path, timeout: float) -> tuple[bool, str, dict]:
    started = time.monotonic()
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False, "input_json_invalid", {}
    if not isinstance(value, dict) or set(value) != keys:
        return False, "main_input_keys_mismatch", {}
    attempt_dir.mkdir(parents=True, exist_ok=True)
    witness = attempt_dir / "honest.wtns"
    node = shutil.which("node")
    if node is None:
        return False, "node_unavailable", {}
    command = [node, str(artifacts["generator"]), str(artifacts["wasm"]),
               str(path), str(witness)]
    code, witness_seconds, disposition = run_quiet(command, timeout)
    if disposition != "completed" or code != 0 or not witness.is_file():
        return False, "honest_witness_" + (disposition if disposition != "completed" else "failed"), {}
    environment = os.environ.copy()
    environment["N6_J1_R1CS"] = str(artifacts["r1cs"])
    environment["N6_J1_WTNS"] = str(witness)
    remaining = max(1, timeout - (time.monotonic() - started))
    rust_code, rust_seconds, rust_disposition = run_quiet(
        [str(checker), "check_current_witness", "--exact", "--ignored"], remaining, env=environment,
    )
    if rust_disposition != "completed" or rust_code != 0:
        return False, "rust_r1cs_" + (rust_disposition if rust_disposition != "completed" else "failed"), {}
    remaining = max(1, timeout - (time.monotonic() - started))
    snark_code, snark_seconds, snark_disposition = run_quiet(
        [str(snarkjs), "wtns", "check", str(artifacts["r1cs"]), str(witness)], remaining,
    )
    if snark_disposition != "completed" or snark_code != 0:
        return False, "snarkjs_r1cs_" + (snark_disposition if snark_disposition != "completed" else "failed"), {}
    return True, "passed", {"witness_path": str(witness), "witness_sha256": sha256(witness),
                            "witness_seconds": witness_seconds, "rust_seconds": rust_seconds,
                            "snarkjs_seconds": snark_seconds}


def main_call_signature(source: Path) -> str | None:
    try:
        content = source.read_text(errors="ignore")
    except OSError:
        return None
    content = re.sub(r"/\*.*?\*/|//[^\n]*", "", content, flags=re.DOTALL)
    match = MAIN_CALL.search(content)
    return re.sub(r"\s+", "", match.group(1)) if match else None


def source_files(root: Path, suffixes: set[str]) -> list[Path]:
    files = []
    skipped = SKIP_DIRS - ({"lib"} if suffixes == {".circom"} else set())
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = sorted(name for name in subdirs if name not in skipped)
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix.lower() in suffixes and path.is_file():
                files.append(path)
    return files


def main_input_declarations(entrypoint: Path, project: Path,
                            libraries: list[Path]) -> set[str]:
    signature = main_call_signature(entrypoint)
    if not signature or "(" not in signature:
        raise ValueError("main_call_missing")
    template = signature.split("(", 1)[0]
    pattern = re.compile(r"\btemplate\s+" + re.escape(template) + r"\s*\([^;{]*\)\s*\{", re.DOTALL)
    candidates = source_files(project, {".circom"})
    for library in libraries:
        if library.is_dir() and not library.is_relative_to(project):
            candidates.extend(source_files(library, {".circom"}))
    found = []
    for source in sorted(set(candidates)):
        content = re.sub(r"/\*.*?\*/|//[^\n]*", "", source.read_text(errors="ignore"), flags=re.DOTALL)
        match = pattern.search(content)
        if not match:
            continue
        start = match.end()
        depth = 1
        cursor = start
        while cursor < len(content) and depth:
            depth += (content[cursor] == "{") - (content[cursor] == "}")
            cursor += 1
        if depth:
            raise ValueError("main_template_body_unclosed")
        body = content[start:cursor - 1]
        declarations = set(re.findall(r"\bsignal\s+input\s+([A-Za-z_][A-Za-z_0-9]*)", body))
        found.append(declarations)
    if not found:
        raise ValueError("main_template_declaration_missing")
    if any(declarations != found[0] for declarations in found[1:]):
        raise ValueError("main_template_declaration_ambiguous")
    return found[0]


def equivalent_main_names(project: Path, entrypoint: Path) -> set[str]:
    same_main_names = {entrypoint.name}
    signature = main_call_signature(entrypoint)
    if signature:
        for circuit in source_files(project, {".circom"}):
            if main_call_signature(circuit) == signature:
                same_main_names.add(circuit.name)
    return same_main_names


def matching_project_files(project: Path, entrypoint: Path) -> list[Path]:
    """Find unchanged files referencing the entrypoint or an identical main call."""
    matching = []
    same_main_names = equivalent_main_names(project, entrypoint)
    for path in source_files(project, {".js", ".ts", ".mjs", ".cjs"}):
        relative = path.relative_to(project)
        if not any(part.lower() in {"test", "tests", "tooling", "tools"} for part in relative.parts[:-1]):
            continue
        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue
        witness_call = any(token in content for token in ("calculateWitness", "wtns.calculate"))
        input_tool = "inputCommand" in content and "input <file>" in content
        if (any(name in content for name in same_main_names) and witness_call) or input_tool:
            matching.append(path)
    return sorted(matching)


def test_command(project: Path, test_file: Path, entrypoint_relative: str) -> tuple[list[str] | None, Path]:
    relative = test_file.relative_to(project)
    if test_file.name == "cli.ts" and "inputCommand" in test_file.read_text(errors="ignore"):
        executable = project / "node_modules/.bin/tsx"
        return ([str(executable), str(relative), "input", entrypoint_relative]
                if executable.exists() else None), project
    package_dir = next((parent for parent in test_file.parents if (parent / "package.json").exists()
                        and parent.is_relative_to(project)), project)
    local_bin = package_dir / "node_modules/.bin"
    root_bin = project / "node_modules/.bin"
    if test_file.suffix == ".ts":
        mocha = local_bin / "mocha" if (local_bin / "mocha").exists() else root_bin / "mocha"
        if not mocha.exists():
            return None, package_dir
        package = json.loads((package_dir / "package.json").read_text())
        if package.get("name") == "@panther-core/circuits":
            compiled = package_dir / "lib" / test_file.relative_to(package_dir / "test").with_suffix(".js")
            return [str(mocha), "--no-config", str(compiled), "--timeout", "60000"], package_dir
        return [str(mocha), "--require", "ts-node/register/transpile-only", str(test_file)], package_dir
    jest = local_bin / "jest" if (local_bin / "jest").exists() else root_bin / "jest"
    if test_file.name.endswith(".test.js") and jest.exists():
        return [str(jest), "--runInBand", "--runTestsByPath", str(test_file)], package_dir
    mocha = local_bin / "mocha" if (local_bin / "mocha").exists() else root_bin / "mocha"
    return ([str(mocha), str(test_file)] if mocha.exists() else None), package_dir


def project_test_setup(project: Path, original_test: Path, entrypoint: Path,
                       artifacts: dict[str, Path], output: Path, deadline: float,
                       environment: dict[str, str], *, perform_build: bool = True) -> tuple[list[dict], dict | None]:
    """Run the original local build script without changing project files."""
    setup = []
    package = project / "circuits/package.json"
    if not package.is_file() or original_test.relative_to(project).parts[0] != "circuits":
        return setup, None
    package_data = json.loads(package.read_text())
    if package_data.get("name") != "@panther-core/circuits":
        return setup, None
    if perform_build:
        npm = shutil.which("npm")
        if npm is None:
            return setup, {"stage": "d_project_test", "reason": "project_build_runner_unavailable"}
        for subproject in ("crypto", "circuits"):
            package_path = project / subproject / "package.json"
            if not package_path.is_file():
                return setup, {"stage": "d_project_test", "reason": "project_build_package_missing",
                               "package_path": str(package_path)}
            command = [npm, "run", "build"]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return setup, {"stage": "d_project_test", "reason": "project_test_30min_exceeded"}
            code, seconds, disposition, error_kind = run_project_quiet(
                command, remaining, cwd=package_path.parent, env=environment,
            )
            setup.append({"kind": "original_project_build", "package_path": str(package_path),
                          "package_sha256": sha256(package_path), "command": command,
                          "exit_code": code, "disposition": disposition,
                          "error_kind": error_kind, "seconds": seconds})
            if disposition != "completed" or code != 0:
                return setup, {"stage": "d_project_test", "reason": "project_build_failed",
                               "package_path": str(package_path), "exit_code": code,
                               "disposition": disposition, "error_kind": error_kind}
    test_source = original_test.read_text(errors="ignore")
    expected_main = main_call_signature(entrypoint)
    matched_sources = []
    for literal in re.findall(r"['\"]([^'\"]+\.circom)['\"]", test_source):
        candidate = (project / "circuits" / literal).resolve()
        if candidate.is_file() and main_call_signature(candidate) == expected_main:
            matched_sources.append(candidate)
    if not matched_sources:
        return setup, {"stage": "d_project_test", "reason": "project_test_same_main_unverified"}
    setup.append({"kind": "same_main_test_reference", "test_path": str(original_test),
                  "test_sha256": sha256(original_test), "referenced_circuit_path": str(matched_sources[0]),
                  "referenced_circuit_sha256": sha256(matched_sources[0]),
                  "entrypoint_sha256": sha256(entrypoint), "same_main_signature": True})
    return setup, None


def project_test_selection(row: dict, output: Path, deadline: float,
                           validate, artifacts: dict[str, Path]) -> tuple[tuple[Path, dict] | None,
                                                                           list[dict], list[dict]]:
    source = workspace_path(row["project_root"])
    original_entrypoint = workspace_path(row["entrypoint_absolute"])
    allowed_circuit_names = equivalent_main_names(source, original_entrypoint)
    allowed_stems = {Path(name).stem for name in allowed_circuit_names}
    files = matching_project_files(source, original_entrypoint)
    failures = []
    execution = []
    if not files:
        return None, [{"stage": "d_project_test", "reason": "matching_test_or_tool_missing"}], execution
    staging = output / "project-test-staging"
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, [{"stage": "d_project_test", "reason": "project_test_30min_exceeded"}], execution
        # APFS clone keeps the original revision and original test files unchanged.
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            copy = subprocess.run(["cp", "-cR", str(source) + "/.", str(staging)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=max(1, remaining))
        except subprocess.TimeoutExpired:
            return None, [{"stage": "d_project_test", "reason": "project_test_30min_exceeded",
                           "test_path": str(files[0])}], execution
        if copy.returncode:
            return None, [{"stage": "d_project_test", "reason": "project_stage_copy_failed",
                           "test_path": str(files[0]), "exit_code": copy.returncode}], execution
        fixed_bin = output / "fixed-circom-bin"
        fixed_bin.mkdir(exist_ok=True)
        link = fixed_bin / "circom"
        if not link.exists():
            link.symlink_to(CIRCOM)
        environment = os.environ.copy()
        environment["PATH"] = str(fixed_bin) + os.pathsep + environment.get("PATH", "")
        environment["npm_config_offline"] = "true"
        environment["YARN_ENABLE_NETWORK"] = "0"
        environment["COREPACK_ENABLE_NETWORK"] = "0"
        staged_entrypoint = staging / original_entrypoint.relative_to(source)
        setup, setup_error = project_test_setup(
            staging, staging / files[0].relative_to(source), staged_entrypoint,
            artifacts, output, deadline, environment,
        )
        execution.extend(setup)
        if setup_error is not None and setup_error["reason"] != "project_test_same_main_unverified":
            failures.append(setup_error)
            return None, failures, execution
        for ordinal, original_test in enumerate(files, 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failures.append({"stage": "d_project_test", "reason": "project_test_30min_exceeded"})
                break
            test_file = staging / original_test.relative_to(source)
            if ordinal == 1 and setup_error is not None:
                failures.append({**setup_error, "test_path": str(original_test)})
                continue
            if ordinal > 1:
                file_setup, file_error = project_test_setup(
                    staging, test_file, staged_entrypoint, artifacts,
                    output, deadline, environment, perform_build=False,
                )
                execution.extend(file_setup)
                if file_error is not None:
                    failures.append({**file_error, "test_path": str(original_test)})
                    continue
            entrypoint_relative = original_entrypoint.relative_to(source).as_posix()
            command, cwd = test_command(staging, test_file, entrypoint_relative)
            if command is None:
                failures.append({"stage": "d_project_test", "reason": "project_test_runner_unavailable",
                                 "test_path": str(original_test)})
                continue
            capture_file = output / "project-test-captures" / f"{ordinal:04d}.jsonl"
            capture_file.parent.mkdir(parents=True, exist_ok=True)
            test_environment = environment.copy()
            test_environment["NODE_OPTIONS"] = (test_environment.get("NODE_OPTIONS", "") +
                                                 f" --require={CAPTURE}").strip()
            test_environment["N6_J1_CAPTURE_PATH"] = str(capture_file)
            test_environment["N6_J1_CAPTURE_WRITES"] = "1" if test_file.name == "cli.ts" else "0"
            code, seconds, disposition, error_kind = run_project_quiet(
                command, deadline - time.monotonic(), cwd=cwd, env=test_environment,
            )
            execution.append({"kind": "original_test_or_input_tool", "test_path": str(original_test),
                              "test_sha256": sha256(original_test), "command": command,
                              "cwd": str(cwd), "exit_code": code, "disposition": disposition,
                              "error_kind": error_kind, "seconds": seconds,
                              "capture_path": str(capture_file) if capture_file.is_file() else None,
                              "capture_sha256": sha256(capture_file) if capture_file.is_file() else None})
            if disposition != "completed" or code != 0:
                reason = ("project_test_30min_exceeded" if disposition == "timeout" else
                          "project_test_spawn_failed" if disposition == "spawn_failed" else
                          "project_test_exit_nonzero")
                failures.append({"stage": "d_project_test", "reason": reason,
                                 "test_path": str(original_test), "seconds": seconds,
                                 "exit_code": code, "disposition": disposition,
                                 "error_kind": error_kind})
                if disposition == "timeout":
                    break
                continue
            if not capture_file.is_file():
                failures.append({"stage": "d_project_test", "reason": "project_test_no_input_capture",
                                 "test_path": str(original_test), "seconds": seconds})
                continue
            for line_number, line in enumerate(capture_file.read_text().splitlines(), 1):
                try:
                    capture = json.loads(line)
                    candidate = capture["input"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                if not isinstance(candidate, dict):
                    continue
                source_name = str(capture.get("source", ""))
                if capture.get("kind") == "calculateWitness":
                    if Path(source_name).name not in allowed_circuit_names:
                        continue
                elif capture.get("kind") == "wtns.calculate":
                    if not any(stem in Path(source_name).name for stem in allowed_stems):
                        continue
                elif capture.get("kind") != "input-tool-output":
                    continue
                candidate_file = output / "project-test-inputs" / f"{ordinal:04d}-{line_number:04d}.json"
                dump_json(candidate_file, candidate)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failures.append({"stage": "d_project_test", "reason": "project_test_30min_exceeded"})
                    return None, failures, execution
                passed, reason, details = validate(candidate_file, remaining)
                if passed:
                    return (candidate_file, details), failures, execution
                failures.append({"stage": "d_project_test", "reason": reason,
                                 "source_path": str(candidate_file)})
        return None, failures, execution
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def compile_entrypoint(row: dict, output: Path, timeout: float) -> tuple[dict[str, Path], dict]:
    entrypoint = workspace_path(row["entrypoint_absolute"])
    if not entrypoint.is_file() or sha256(entrypoint) != row["entrypoint_sha256"]:
        raise RuntimeError("entrypoint_hash_mismatch")
    folder = output / "compiled"
    folder.mkdir(parents=True, exist_ok=True)
    command = [str(CIRCOM), str(entrypoint), "--r1cs", "--sym", "--wasm", "-o", str(folder)]
    for path in row["preflight_library_paths"]:
        command.extend(["-l", str(workspace_path(path))])
    code, seconds, disposition = run_quiet(command, timeout)
    if disposition != "completed" or code != 0:
        raise RuntimeError("entrypoint_compile_" + (disposition if disposition != "completed" else "failed"))
    stem = entrypoint.stem
    artifacts = {"r1cs": folder / f"{stem}.r1cs", "sym": folder / f"{stem}.sym",
                 "wasm": folder / f"{stem}_js/{stem}.wasm",
                 "generator": folder / f"{stem}_js/generate_witness.js"}
    if not all(path.is_file() for path in artifacts.values()):
        raise RuntimeError("entrypoint_compile_artifacts_missing")
    return artifacts, {"seconds": seconds, "r1cs_sha256": sha256(artifacts["r1cs"]),
                       "sym_sha256": sha256(artifacts["sym"]), "wasm_sha256": sha256(artifacts["wasm"])}


def resolve_candidates(row: dict, stage: str, l_inputs: dict[tuple[str, str], list[Path]],
                       output: Path) -> tuple[list[Path], list[dict]]:
    failures = []
    if stage == "a_zkbugs":
        paths = []
        for case in row.get("dataset_cases", []):
            path_value = case.get("original_input_path")
            if not path_value:
                failures.append({"stage": stage, "reason": "zkbugs_input_missing",
                                 "item_id": case.get("item_id")})
                continue
            path = workspace_path(path_value)
            expected = case.get("original_input_sha256")
            if not path.is_file():
                failures.append({"stage": stage, "reason": "zkbugs_input_missing", "source_path": str(path)})
            elif expected and sha256(path) != expected:
                failures.append({"stage": stage, "reason": "zkbugs_input_hash_mismatch", "source_path": str(path)})
            else:
                paths.append(path)
        if not paths and not failures:
            failures.append({"stage": stage, "reason": "zkbugs_item_unavailable"})
        return paths, failures
    if stage == "b_l_series":
        family = project_family(workspace_path(row["project_root"]))
        paths = l_inputs.get((family, row["entrypoint_relative"]), []) if family else []
        return paths, ([] if paths else [{"stage": stage, "reason": "matching_l_series_input_missing"}])
    if stage == "c_committed_json":
        paths, error = committed_json_paths(row)
        return paths, ([{"stage": stage, "reason": error}] if error else
                       ([] if paths else [{"stage": stage, "reason": "matching_committed_json_missing"}]))
    if stage == "d_project_test":
        raise RuntimeError("project tests require sequential validation")
    if stage == "e_zero":
        raise RuntimeError("zero input needs parsed main signals")
    raise ValueError(stage)


def select_one(row: dict, output: Path, checker: Path, snarkjs: Path,
               l_inputs: dict[tuple[str, str], list[Path]], compile_timeout: float,
               validation_timeout: float) -> dict:
    started = time.monotonic()
    identifier = row["identifier"]
    folder = output / identifier
    folder.mkdir(parents=True, exist_ok=True)
    record: dict = {"identifier": identifier, "status": "base_input_unavailable",
                    "selected_stage": None, "original_rule_stage": None,
                    "base_input_path": None, "base_input_sha256": None,
                    "failed_attempts": [], "stages": list(STAGES)}
    artifacts, compile_metadata = compile_entrypoint(row, folder, compile_timeout)
    shape = read_r1cs_shape(artifacts["r1cs"])
    declarations = main_input_declarations(
        workspace_path(row["entrypoint_absolute"]), workspace_path(row["project_root"]),
        [workspace_path(path) for path in row["preflight_library_paths"]],
    )
    signals = main_input_names(artifacts["sym"], declarations)
    keys = set(input_keys(signals))
    record["compile"] = compile_metadata
    record["main_input_count"] = len(keys)
    record["main_input_wire_count"] = len(signals)
    record["constraints"] = shape["constraints"]
    zero = folder / "zero-input.json"
    dump_json(zero, zero_input(signals))
    selected = None
    original_rule = None
    attempt_number = 0
    for stage in STAGES:
        if selected is not None and stage != "e_zero":
            continue
        if stage == "e_zero" and original_rule is not None:
            break
        if stage == "d_project_test":
            def validate_project_candidate(path: Path, remaining: float):
                nonlocal attempt_number
                attempt_number += 1
                attempt_dir = folder / "attempts" / f"{attempt_number:04d}"
                passed, reason, details = validate_input(
                    path, keys, artifacts, checker, snarkjs, attempt_dir,
                    min(validation_timeout, remaining),
                )
                if not passed:
                    shutil.rmtree(attempt_dir, ignore_errors=True)
                return passed, reason, details

            picked, failures, execution = project_test_selection(
                row, folder, time.monotonic() + 1800, validate_project_candidate, artifacts,
            )
            record["failed_attempts"].extend(failures)
            record["project_test_execution"] = execution
            if picked is not None:
                selected = (stage, picked[0], picked[1])
            continue
        if stage == "e_zero":
            candidates, failures = [zero], []
        else:
            candidates, failures = resolve_candidates(row, stage, l_inputs, folder)
        record["failed_attempts"].extend(failures)
        for candidate in candidates:
            attempt_number += 1
            attempt_dir = folder / "attempts" / f"{attempt_number:04d}"
            passed, reason, details = validate_input(candidate, keys, artifacts, checker, snarkjs,
                                                      attempt_dir, validation_timeout)
            if not passed:
                record["failed_attempts"].append({"stage": stage, "reason": reason,
                                                   "source_path": str(candidate)})
                shutil.rmtree(attempt_dir, ignore_errors=True)
                continue
            if selected is None:
                selected = (stage, candidate, details)
            if original_rule is None and stage != "d_project_test":
                original_rule = stage
            # The first passing candidate in the fixed order is final.
            break
        if selected is not None and stage != "d_project_test":
            break
    if selected is not None:
        stage, path, details = selected
        destination = folder / "selected-input.json"
        shutil.copyfile(path, destination) if path != destination else None
        record.update({"status": "passed", "selected_stage": stage,
                       "base_input_path": str(destination), "base_input_sha256": sha256(destination),
                       "selected_source_path": str(path), "selected_source_sha256": sha256(path),
                       "honest_witness_path": details["witness_path"],
                       "honest_witness_sha256": details["witness_sha256"],
                       "validation_seconds": {key: details[key] for key in
                                              ("witness_seconds", "rust_seconds", "snarkjs_seconds")}})
    record["original_rule_stage"] = original_rule or "base_input_unavailable"
    if selected is not None and selected[0] == "b_l_series":
        record["l_series_match"] = {
            "project_family": project_family(workspace_path(row["project_root"])),
            "entrypoint_relative": row["entrypoint_relative"],
            "source_base_input_path": str(selected[1]),
            "source_base_input_sha256": sha256(selected[1]),
        }
    record["wall_seconds"] = time.monotonic() - started
    # Compilation is reproducible from the pinned source and tool. Keep its
    # hashes above, while retaining only input and honest witness artifacts.
    shutil.rmtree(folder / "compiled")
    dump_json(folder / "selection.json", record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--compile-timeout-seconds", type=float, default=1800)
    parser.add_argument("--validation-timeout-seconds", type=float, default=600)
    parser.add_argument("--identifier", help="one revision for bounded restart")
    args = parser.parse_args()
    manifest = args.revision_manifest.resolve()
    output = args.output_root.resolve()
    if sha256(CIRCOM) != CIRCOM_SHA256:
        raise SystemExit("fixed circom hash mismatch")
    rows = json.loads(manifest.read_text())["rows"]
    if len(rows) != 27 or len({row["identifier"] for row in rows}) != 27:
        raise SystemExit("revision manifest must have 27 distinct rows")
    if args.identifier and args.identifier not in {row["identifier"] for row in rows}:
        raise SystemExit("identifier absent from revision manifest")
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
        if index.get("revision_manifest_sha256") != sha256(manifest):
            raise SystemExit("revision manifest hash changed")
    else:
        index = {"schema": "n6-j1-base-inputs-v1", "revision_manifest_path": str(manifest),
                 "revision_manifest_sha256": sha256(manifest), "circom_sha256": CIRCOM_SHA256,
                 "revisions": {}}
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
