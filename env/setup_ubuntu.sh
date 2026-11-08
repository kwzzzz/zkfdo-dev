#!/usr/bin/env bash
# Unexecuted Ubuntu installation draft. This task checks bash -n only.
set -euo pipefail
if [[ "${1:-}" == "--help" || "${1:-}" == "--plan" ]]; then
  printf '%s\n' 'Usage: setup_ubuntu.sh --apply /absolute/path/to/setup-pins.json' \
    'No default pins. See env/README.md. No fuzzing, J requests or AWS actions.'
  exit 0
fi
if [[ "$#" -ne 2 || "$1" != "--apply" || "$2" != /* ]]; then
  printf '%s\n' 'BLOCKED: --apply and a complete absolute pin-file path are required.' >&2
  exit 2
fi
command -v python3 >/dev/null || { printf '%s\n' 'Bootstrap Python 3.12+ required.' >&2; exit 2; }
exec python3 - "$2" <<'PY'
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def literal(value, label):
    require(isinstance(value, str) and value.strip() == value and value and
            not any(x in value.lower() for x in ("todo", "latest", "<", ">", "*")),
            label + ": exact value required")
    return value


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "SHA256 required")
    return value


def absolute(value, exists=True):
    path = Path(literal(value, "path"))
    require(path.is_absolute() and (not exists or path.exists()), "absolute existing path required")
    return path


def relative(value):
    path = PurePosixPath(literal(value, "relative path"))
    require(not path.is_absolute() and ".." not in path.parts and str(path) != ".", "unsafe relative path")
    return path


def pinned_file(entry):
    path = absolute(entry["path"])
    require(path.is_file() and not path.is_symlink() and digest(path) == sha(entry["sha256"]), "pinned file mismatch: " + str(path))
    return path


def version_spec(entry):
    require(entry["version_args"] in (["--version"], ["-V"], ["-vV"], ["-version"]), "version-only argv required")
    literal(entry["version_output_contains"], "version output")
    require(type(entry["version_exit_code"]) is int, "version exit code required")


def download_pin(entry, host, prefix):
    url = urllib.parse.urlparse(literal(entry["url"], "download URL"))
    require(url.scheme == "https" and url.hostname == host and url.path.startswith(prefix)
            and not url.username and not url.query, "pinned official HTTPS archive URL required")
    sha(entry["sha256"])


def main():
    require(sys.version_info >= (3, 12), "Bootstrap Python 3.12+ required for safe tar extraction")
    pins_path = Path(sys.argv[1])
    pins = json.loads(pins_path.read_text())
    require(pins["schema"] == "zkfdo-ubuntu-setup-pins-v1", "unknown pin schema")
    require(platform.system() == "Linux", "Ubuntu Linux required")
    release = platform.freedesktop_os_release()
    require(release.get("ID") == "ubuntu" and release.get("VERSION_ID") ==
            literal(pins["ubuntu_release"], "Ubuntu release"), "Ubuntu release mismatch")
    require(platform.machine() == literal(pins["architecture"], "architecture"), "architecture mismatch")
    work = absolute(pins["workspace"], exists=False)
    require(not work.exists() and work.parent.is_dir() and not work.parent.is_symlink(), "fresh workspace required")
    require(type(pins["min_free_bytes"]) is int and pins["min_free_bytes"] > 0 and
            shutil.disk_usage(work.parent).free >= pins["min_free_bytes"], "free space gate failed")

    # All required inputs and local source hashes precede downloads/apt/builds.
    packages = pins["apt_packages"]
    needed = {"ca-certificates", "git", "curl", "build-essential", "pkg-config",
              "libssl-dev", "cmake", "python3", "python3-venv"}
    require(isinstance(packages, dict) and needed <= packages.keys(), "pinned apt prerequisites required")
    for name, value in packages.items():
        require(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name), "invalid package name")
        require(re.fullmatch(r"[A-Za-z0-9:.+~_-]+", literal(value, name)), "exact apt version required")
    python = pins["python"]
    python_path = absolute(python["path"], exists=False)
    version_spec(python)
    rust = pins["rust"]
    require(re.fullmatch(r"\d+\.\d+\.\d+", literal(rust["toolchain"], "Rust release")), "exact Rust release required")
    target = literal(rust["target"], "Rust target")
    require({"x86_64": "x86_64-unknown-linux-gnu", "aarch64": "aarch64-unknown-linux-gnu"}.get(pins["architecture"]) == target, "Rust target mismatch")
    download_pin(rust["rustup_init"], "static.rust-lang.org", "/rustup/archive/")
    for key in ("rustc", "cargo"):
        version_spec(rust[key])
    node = pins["node"]
    node_version = literal(node["version"], "Node version")
    require(re.fullmatch(r"\d+\.\d+\.\d+", node_version), "exact Node version required")
    download_pin(node, "nodejs.org", "/dist/v" + node_version + "/")
    node_root = str(relative(node["archive_root"]))
    node_arch = {"x86_64": "x64", "aarch64": "arm64"}[pins["architecture"]]
    require(node_root == "node-v" + node_version + "-linux-" + node_arch, "Node architecture/root mismatch")
    literal(node["npm_version"], "npm version")
    snark = pins["snarkjs"]
    require(re.fullmatch(r"\d+\.\d+\.\d+", literal(snark["version"], "snarkjs version")), "exact snarkjs version required")
    package_path = pinned_file(snark["package_json"])
    lock_path = pinned_file(snark["package_lock"])
    package, lock = json.loads(package_path.read_text()), json.loads(lock_path.read_text())
    require(package.get("dependencies") == {"snarkjs": snark["version"]} and not package.get("devDependencies")
            and not package.get("scripts"), "exact snarkjs-only root dependency required")
    require(lock.get("lockfileVersion") in (2, 3) and lock.get("packages", {}).get("", {}).get("dependencies")
            == package["dependencies"], "npm lock mismatch")
    for name, item in lock["packages"].items():
        if name:
            require(str(item.get("integrity", "")).startswith("sha512-") and
                    str(item.get("resolved", "")).startswith("https://registry.npmjs.org/"), "npm lock integrity missing: " + name)
    version_spec(snark)

    plans = {}
    source_tools = pins["source_tools"]
    require({"prepare", "J", "circom", "zkfuzz", "z3"} <= source_tools.keys() <=
            {"prepare", "J", "J_v24", "circom", "zkfuzz", "z3"}, "source_tools missing/unknown keys")
    for key, entry in source_tools.items():
        source = absolute(entry["source_dir"]).resolve()
        manifest = json.loads(pinned_file(entry["source_manifest"]).read_text())
        require(manifest.get("schema") == "zkfdo-source-files-v1" and manifest.get("files"), key + ": source file manifest required")
        require(entry.get("source_commit") is not None or entry.get("source_commit_reason"), key + ": explain unknown commit")
        literal(entry["build_profile"], key + " build profile")
        files = []
        for item in manifest["files"]:
            rel = str(relative(item["path"]))
            path = source / rel
            require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source), key + ": source file missing/escape")
            require(digest(path) == sha(item["sha256"]), key + ": source hash mismatch: " + rel)
            files.append((path, rel, item["sha256"]))
        require(len({x[1] for x in files}) == len(files), key + ": duplicate source path")
        commands = entry["build_commands"]
        require(isinstance(commands, list) and commands, key + ": exact build argv required")
        for command in commands:
            require(isinstance(command, list) and command and all(isinstance(x, str) and x for x in command), "argv arrays required")
            require(command[0] in ("cargo", "cmake", "make", "ninja", "python3", "bash"), "unsupported build executable")
            for argument in command:
                literal(argument, key + " build argument")
            require(command[0] != "ninja" or "ninja-build" in packages, "pin ninja-build before using ninja")
        if key != "z3":
            require(entry["build_profile"] in ("dev", "release"), key + ": explicit dev/release required")
            cargo_commands = [cmd for cmd in commands if cmd[:2] == ["cargo", "build"]]
            require(cargo_commands, key + ": cargo build required")
            for command in cargo_commands:
                require("--locked" in command and "--profile" in command and
                        command[command.index("--profile") + 1:command.index("--profile") + 2] == [entry["build_profile"]],
                        key + ": cargo build --locked --profile matching build_profile required")
            require("Cargo.lock" in {x[1] for x in files}, key + ": pinned Cargo.lock required")
        relative(entry["artifact_path"])
        version_spec(entry)
        plans[key] = (entry, files)
    sudo = [] if os.geteuid() == 0 else ["sudo", "-n"]
    require(not sudo or shutil.which("sudo"), "root or noninteractive sudo required")

    work.mkdir(mode=0o700)
    receipt = {"schema": "zkfdo-ubuntu-install-observation-v1", "status": "started",
               "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "pins_sha256": digest(pins_path), "os_release": release,
               "architecture": platform.machine(), "commands": [], "tools": {}}
    env = dict(os.environ)
    env.update(CARGO_HOME=str(work / "cargo"), RUSTUP_HOME=str(work / "rustup"),
               RUSTUP_TOOLCHAIN=rust["toolchain"], CARGO_INCREMENTAL="0", CARGO_BUILD_JOBS="1")
    for key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "CARGO_TARGET_DIR"):
        env.pop(key, None)

    def run(argv, cwd=None, expected=0):
        result = subprocess.run(argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        receipt["commands"].append({"argv": list(map(str, argv)), "cwd": str(cwd) if cwd else None,
                                    "exit_code": result.returncode, "output": result.stdout})
        require(result.returncode == expected, "command failed: " + str(argv))
        return result.stdout

    def observe(key, path, spec):
        output = run([str(path), *spec["version_args"]], expected=spec["version_exit_code"])
        require(spec["version_output_contains"] in output, key + ": version mismatch")
        receipt["tools"][key] = {"path": str(path.resolve()), "sha256": digest(path), "version_output": output}

    def fetch(entry, path):
        with urllib.request.urlopen(entry["url"], timeout=60) as response, path.open("xb") as output:
            shutil.copyfileobj(response, output)
        require(digest(path) == entry["sha256"], "download hash mismatch: " + str(path))

    try:
        # Hash-verified downloads precede host package changes. No curl|sh.
        rustup, node_archive = work / "rustup-init", work / "node-archive.tar.xz"
        fetch(rust["rustup_init"], rustup)
        fetch(node, node_archive)
        if sudo:
            run([*sudo, "true"])
        run([*sudo, "apt-get", "update"])
        exact_packages = [name + "=" + version for name, version in packages.items()]
        for name in exact_packages:
            run(["apt-cache", "show", name])
        run([*sudo, "apt-get", "install", "-y", "--no-install-recommends", *exact_packages])
        observe("python", python_path, python)
        rustup.chmod(0o700)
        run([str(rustup), "-y", "--no-modify-path", "--profile", "minimal",
             "--default-host", target, "--default-toolchain", rust["toolchain"]])
        env["PATH"] = str(work / "cargo/bin") + os.pathsep + env.get("PATH", "/usr/bin:/bin")
        toolchain = work / "rustup/toolchains" / (rust["toolchain"] + "-" + target) / "bin"
        for key in ("rustc", "cargo"):
            observe(key, toolchain / key, rust[key])
        node_parent = work / "node"
        node_parent.mkdir()
        with tarfile.open(node_archive, "r:*") as archive:
            require(all(PurePosixPath(m.name).parts and PurePosixPath(m.name).parts[0] == node_root
                        for m in archive.getmembers()), "unexpected Node archive root")
            archive.extractall(node_parent, filter="data")
        node_bin = node_parent / node_root / "bin"
        env["PATH"] = str(node_bin) + os.pathsep + env["PATH"]
        observe("node", node_bin / "node", {"version_args": ["--version"], "version_exit_code": 0,
                                          "version_output_contains": "v" + node_version})
        require(run([str(node_bin / "npm"), "--version"]).strip() == node["npm_version"], "npm version mismatch")
        npm_root = work / "snarkjs"
        npm_root.mkdir()
        shutil.copy2(package_path, npm_root / "package.json")
        shutil.copy2(lock_path, npm_root / "package-lock.json")
        run([str(node_bin / "npm"), "ci", "--ignore-scripts", "--no-audit", "--no-fund"], npm_root)
        observe("snarkjs", npm_root / "node_modules/.bin/snarkjs", snark)
        for key, (entry, files) in plans.items():
            source_copy = work / "sources" / key
            source_copy.mkdir(parents=True)
            for path, rel, expected_hash in files:
                destination = source_copy / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                require(digest(destination) == expected_hash, key + ": source changed while copying")
            # Only manifest-listed files enter each isolated build; originals stay unchanged.
            env["CARGO_TARGET_DIR"] = str(source_copy / "target")
            for command in entry["build_commands"]:
                actual = [str(python_path) if command[0] == "python3" else command[0], *command[1:]]
                run(actual, source_copy)
            artifact = source_copy / entry["artifact_path"]
            require(artifact.resolve().is_relative_to(source_copy), key + ": artifact path escaped")
            observe(key, artifact, entry)
            receipt["tools"][key].update(source_manifest_sha256=entry["source_manifest"]["sha256"],
                                         source_commit=entry.get("source_commit"), build_commands=entry["build_commands"],
                                         build_profile=entry["build_profile"])
        receipt["status"] = "installed_pending_fixture_and_manifest_review"
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        receipt["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (work / "install-observation.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print("Install receipt:", work / "install-observation.json")
    print("Linux fixtures and a new measured manifest remain required. No fuzzing/J/AWS job was run.")


try:
    main()
except (KeyError, ValueError, OSError) as error:
    print("BLOCKED/FAILED:", error, file=sys.stderr)
    sys.exit(2)
PY

