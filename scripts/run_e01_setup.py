#!/usr/bin/env python3
"""Run fixed E-01 setup extension and structural measurements; never runs zkFuzz."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

import e01_environment as environment
import measure_c03_corpus as base


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/e01-setup-2026-10-03"
C03_RUN = ROOT / "runs/c03-corpus-2026-10-02/recovery-v3"
C03_RESULTS = ROOT / "docs/c03_corpus_results_2026-10-02.json"
C03_CENSUS = C03_RUN / "census.v3.json"
PROCEDURE = ROOT / "docs/e01_setup_procedure_2026-10-03.md"
TARGETS = (
    "anon-aadhaar/anon-aadhaar", "celo-org/self", "Galactica-corp/galactica-monorepo",
    "proofcarryingdata/zupass", "selfxyz/self", "semaphore-protocol/semaphore",
    "stealthdrop/stealthdrop", "zkemail/zk-email-verify", "zkp2p/zkp2p-v1-monorepo",
)
PACKAGES = (
    ("@yarnpkg/cli-dist", "3.2.1", "yarn@3.2.1", "package/bin/yarn.js"),
    ("@yarnpkg/cli-dist", "3.2.3", "yarn@3.2.3", "package/bin/yarn.js"),
    ("@yarnpkg/cli-dist", "3.6.3", "yarn@3.6.3", "package/bin/yarn.js"),
    ("@yarnpkg/cli-dist", "4.1.0", "yarn@4.1.0", "package/bin/yarn.js"),
    ("@yarnpkg/cli-dist", "4.3.1", "yarn@4.3.1", "package/bin/yarn.js"),
    ("@yarnpkg/cli-dist", "4.5.0", "yarn@4.5.0", "package/bin/yarn.js"),
    ("pnpm", "11.12.0", "pnpm@11.12.0", "package/bin/pnpm.cjs"),
)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def ref(path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}


def read(path):
    return json.loads(Path(path).read_text())


def slug(name):
    return name.replace("/", "__")


def selected_repositories():
    rows = {row["full_name"]: row for row in read(C03_CENSUS)["repositories"]}
    if set(rows).issuperset(TARGETS) is False:
        raise ValueError("fixed_target_missing_from_c03_census")
    selected = []
    for name in TARGETS:
        row = copy.deepcopy(rows[name])
        row["c03_clone_path"] = row["clone_path"]
        row["clone_path"] = str((RUN / "repositories" / slug(name) / "clone").relative_to(ROOT))
        selected.append(row)
    return selected


def run_capture(command, directory, cwd=None, timeout=600):
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        try:
            result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout,
                                    stderr=stderr, timeout=timeout, check=False,
                                    env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "LANG": "C.UTF-8",
                                         "GIT_TERMINAL_PROMPT": "0", "npm_config_ignore_scripts": "true"})
            status, code = ("success" if result.returncode == 0 else "failure"), result.returncode
        except subprocess.TimeoutExpired:
            status, code = "timeout", None
    capture = {"argv": list(map(str, command)), "status": status, "exit_code": code,
               "elapsed_seconds": time.monotonic() - started, "stdout": ref(directory / "stdout.log"),
               "stderr": ref(directory / "stderr.log"), "finished_at": now()}
    write_new(directory / "invocation.json", capture)
    return capture


def attempt_directory(base):
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = base.with_name(base.name + "-attempt-" + str(index))
        if not candidate.exists():
            return candidate
        index += 1


def safe_extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:gz") as packed:
        for member in packed.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()) or member.issym() or member.islnk():
                raise ValueError("unsafe_package_archive_member")
        packed.extractall(destination, filter="data")


def acquire_tools():
    target = RUN / "tools/tools.json"
    if target.exists():
        return read(target)
    c03_tools = read(ROOT / "runs/c03-corpus-2026-10-02/tools/tools.json")
    tools = {"npm": c03_tools["npm"], "git": c03_tools["git"],
             "yarn_classic": c03_tools["yarn"]}
    downloads = RUN / "tools/downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    acquisitions = []
    npm = c03_tools["npm"]["argv"]
    node_path = Path(npm[0])
    for package, version, key, executable_relative in PACKAGES:
        label = key.replace("@", "-")
        capture = run_capture(npm + ["pack", package + "@" + version, "--ignore-scripts", "--json",
                                     "--registry=https://registry.npmjs.org", "--pack-destination", str(downloads)],
                              attempt_directory(RUN / "tools" / ("pack-" + label)), timeout=180)
        if capture["status"] != "success":
            raise RuntimeError("package_tool_acquisition_failed:" + key)
        listing = json.loads((ROOT / capture["stdout"]["path"]).read_text())
        archive = downloads / listing[0]["filename"]
        destination = RUN / "tools" / label
        safe_extract(archive, destination)
        executable = destination / executable_relative
        version_capture = run_capture([str(node_path), str(executable), "--version"],
                                      RUN / "tools" / ("version-" + label), timeout=30)
        actual = (ROOT / version_capture["stdout"]["path"]).read_text().strip()
        if version_capture["status"] != "success" or actual != version:
            raise ValueError("package_tool_version_mismatch:" + key + ":" + actual)
        tools[key] = {"argv": [str(node_path), str(executable)], "version": version,
                      "files": [{"path": str(node_path), "sha256": digest(node_path)},
                                {"path": str(executable), "sha256": digest(executable)}],
                      "registry_package": package, "archive": ref(archive)}
        acquisitions.append({"package": package, "version": version, "tool_key": key,
                             "archive": ref(archive), "executable": ref(executable),
                             "pack_capture": capture, "version_capture": version_capture})
    write_new(target, tools)
    write_new(RUN / "tools/tool-acquisitions.json", {"schema_version": 1, "created_at": now(),
              "project_code_executed": False, "ignore_scripts": True,
              "zkfuzz_invocations": 0, "acquisitions": acquisitions, "tools_ref": ref(target)})
    return tools


def clone_targets(repositories):
    records = []
    for repository in repositories:
        destination = ROOT / repository["clone_path"]
        source = ROOT / repository["c03_clone_path"]
        record_path = destination.parent / "clone-record.json"
        if record_path.exists():
            records.append(read(record_path))
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        clone = run_capture(["/usr/bin/git", "clone", "--no-local", "--no-checkout", str(source), str(destination)],
                            destination.parent / "clone-call", timeout=600)
        if clone["status"] != "success":
            raise RuntimeError("local_clone_failed:" + repository["full_name"])
        checkout = run_capture(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "checkout", "--detach",
                                repository["commit_sha"]], destination.parent / "checkout-call", cwd=destination, timeout=120)
        head = subprocess.run(["/usr/bin/git", "rev-parse", "HEAD"], cwd=destination,
                              capture_output=True, text=True, check=True).stdout.strip()
        if checkout["status"] != "success" or head != repository["commit_sha"]:
            raise ValueError("fixed_commit_checkout_failed:" + repository["full_name"])
        record = {"repository": repository["full_name"], "commit_sha": repository["commit_sha"],
                  "source_clone": str(source.relative_to(ROOT)), "destination": repository["clone_path"],
                  "clone": clone, "checkout": checkout, "verified_head": head}
        write_new(record_path, record)
        records.append(record)
    return records


def initialize():
    if (RUN / "procedure-lock.json").exists():
        raise FileExistsError("E-01 is already initialized")
    RUN.mkdir(parents=True, exist_ok=True)
    tools = acquire_tools()
    repositories = selected_repositories()
    clone_records = clone_targets(repositories)
    census = {"schema_version": 1, "task": "E-01", "created_at": now(),
              "source_census_ref": ref(C03_CENSUS), "repositories": repositories,
              "repository_count": len(repositories), "zkfuzz_invocations": 0}
    write_new(RUN / "census.json", census)
    for name in ("circom", "zkFDO"):
        shutil.copy2(ROOT / "runs/c02-corpus-2026-10-02/tools" / name, RUN / "tools" / name)
    base.RUN = RUN
    base.legacy.RUN = RUN
    base.environment = environment
    inventory = base.make_inventory(RUN / "census.json", "before")
    expected = {row["full_name"]: {entry["key"] for entry in row["entries"]}
                for row in read(C03_RESULTS)["repositories"] if row["full_name"] in TARGETS}
    actual = {row["full_name"]: {entry["key"] for entry in row["entries"]}
              for row in inventory["repositories"]}
    if actual != expected:
        raise ValueError("e01_entrypoint_denominator_differs_from_c03")
    implementation_paths = [Path(__file__), Path(environment.__file__), Path(base.__file__),
                            ROOT / "scripts/measure_c02_preparation.py"]
    lock = {"schema_version": 1, "fixed_at": now(), "owner": "miiz", "deadline": "2026-10-07",
            "procedure_ref": ref(PROCEDURE), "c03_results_ref": ref(C03_RESULTS),
            "c03_census_ref": ref(C03_CENSUS), "census_ref": ref(RUN / "census.json"),
            "inventory_ref": ref(RUN / "entrypoints-before.json"),
            "target_commits": {row["full_name"]: row["commit_sha"] for row in repositories},
            "entrypoint_count": sum(len(row["entries"]) for row in inventory["repositories"]),
            "tool_ref": ref(RUN / "tools/tools.json"),
            "compiler_tools": [ref(RUN / "tools/circom"), ref(RUN / "tools/zkFDO")],
            "implementations": [ref(path) for path in implementation_paths],
            "clone_records": clone_records, "caps_seconds": {"submodule": 180, "install": 600,
                "compile": 120, "discovery": 300, "prepare": 300, "internal": 60, "plan": 30},
            "workers": 2, "zkfuzz_invocations": 0}
    write_new(RUN / "procedure-lock.json", lock)
    print(json.dumps({"repositories": len(repositories), "entrypoints": lock["entrypoint_count"],
                      "tools": len(tools), "lock": str((RUN / "procedure-lock.json").relative_to(ROOT))}))


def verify_lock():
    lock = read(RUN / "procedure-lock.json")
    for reference in [lock["procedure_ref"], lock["c03_results_ref"], lock["c03_census_ref"],
                      lock["census_ref"], lock["inventory_ref"], lock["tool_ref"],
                      *lock["compiler_tools"], *lock["implementations"]]:
        if digest(ROOT / reference["path"]) != reference["sha256"]:
            raise ValueError("e01_lock_reference_changed:" + reference["path"])
    return lock


def setup():
    verify_lock()
    base.RUN = RUN
    base.legacy.RUN = RUN
    base.environment = environment
    census = read(RUN / "census.json")
    inventory = read(RUN / "entrypoints-before.json")
    repositories = {row["full_name"]: row for row in census["repositories"]}
    tools = read(RUN / "tools/tools.json")
    for row in inventory["repositories"]:
        base.setup_one(repositories[row["full_name"]], row, tools)


def measure():
    verify_lock()
    base.RUN = RUN
    base.legacy.RUN = RUN
    base.environment = environment
    census_path = RUN / "census.json"
    census = read(census_path)
    repositories = {row["full_name"]: row for row in census["repositories"]}
    after = base.make_inventory(census_path, "after")
    expected = {row["full_name"]: {entry["key"] for entry in row["entries"]}
                for row in read(C03_RESULTS)["repositories"] if row["full_name"] in TARGETS}
    actual = {row["full_name"]: {entry["key"] for entry in row["entries"]} for row in after["repositories"]}
    if actual != expected:
        raise ValueError("post_setup_entrypoint_denominator_differs_from_c03")
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = []
        for row in after["repositories"]:
            repository = repositories[row["full_name"]]
            setup_record = read(RUN / "setups" / slug(row["full_name"]) / "setup.json")
            for entry in row["entries"]:
                pending.append(executor.submit(base.measure, repository, entry, "after",
                                               setup_record.get("installation_plans", [])))
        for future in as_completed(pending):
            future.result()


def main():
    global RUN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("initialize", "setup", "measure"))
    parser.add_argument("--run-dir", type=Path, default=RUN)
    args = parser.parse_args()
    RUN = args.run_dir.resolve()
    {"initialize": initialize, "setup": setup, "measure": measure}[args.phase]()


if __name__ == "__main__":
    main()
