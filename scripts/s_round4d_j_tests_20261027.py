#!/usr/bin/env python3
"""Copy the 24 historical J assertions and dispatch their old CLI through v2.3."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "runs/s-round4-2026-10-27/round4d"
ENGINE = ROOT / "runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development"
ENGINE_SHA = "05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(path: str | Path) -> Path:
    value = Path(path).absolute()
    if ".." in value.parts or not value.resolve().is_relative_to(ROUND):
        raise ValueError("test output must remain in Round4d")
    return value


def prepare(folder: Path) -> None:
    folder = checked(folder)
    if folder.exists():
        raise ValueError("new test harness directory required")
    (folder / "tests").mkdir(parents=True)
    (folder / "src/bin").mkdir(parents=True)
    inventory = ROOT / "runs/s-inspection-improve-2026-10-27/cargo-command-reference.json"
    names = json.loads(inventory.read_text())["skipped_J_tests"]
    if len(names) != 24 or len(set(names)) != 24:
        raise ValueError("24-test inventory changed")
    source_rows, found = [], set()
    for filename in ("lifting_engine_test.rs", "lifting_engine_regression_test.rs"):
        source = ROOT / "tests" / filename
        raw = source.read_text()
        found.update(set(re.findall(r"#\[test\]\s*fn\s+(\w+)\(", raw)) & set(names))
        replacements = (
            ('env!("CARGO_MANIFEST_DIR")', json.dumps(str(ROOT))),
            ('Command::cargo_bin("zkfDO")', 'round4d_command()'),
            ('let base = root.join("runs/n6-j4c-2026-10-17.noindex");',
             'let base = std::path::PathBuf::from(std::env::var_os("S_ROUND4D_TEST_TMP").unwrap());'),
            ('fs::read_dir(&store)', 'fs::read_dir(store.join("j-v2.3"))'),
            ('fs::read_dir(store)', 'fs::read_dir(store.join("j-v2.3"))'),
            ('cache.join("edits")', 'cache.join("j-v2.3").join("edits")'),
        )
        for old, new in replacements:
            raw = raw.replace(old, new)
        raw += '''
fn round4d_command() -> std::io::Result<assert_cmd::Command> {
    Ok(assert_cmd::Command::new(std::env::var_os("S_ROUND4D_TEST_BRIDGE").unwrap()))
}
'''
        dest = folder / "tests" / filename
        dest.write_text(raw)
        source_rows.append({"source": str(source), "source_sha256": sha(source),
                            "generated": str(dest), "generated_sha256": sha(dest)})
    if found != set(names):
        raise ValueError("24 test names not covered")
    manifest = '''[package]
name = "s-round4d-j-tests"
version = "0.1.0"
edition = "2021"

[workspace]

[dependencies]
zkfdo = { path = REPOSITORY }
anyhow = "1.0"

[dev-dependencies]
assert_cmd = "=2.2.2"
serde_json = "1.0"
tempfile = "3.12"
'''.replace("REPOSITORY", json.dumps(str(ROOT)))
    (folder / "Cargo.toml").write_text(manifest)
    (folder / "Cargo.lock").write_bytes((ROOT / "Cargo.lock").read_bytes())
    (folder / "src/bin/s-round4d-join.rs").write_text('''use std::path::PathBuf;
fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    anyhow::ensure!(args.first().map(String::as_str) == Some("--result"), "--result required");
    let at = args.iter().position(|x| x == "--output").ok_or_else(|| anyhow::anyhow!("--output required"))?;
    anyhow::ensure!(at > 1 && at + 2 == args.len(), "invalid join arguments");
    let inputs: Vec<PathBuf> = args[1..at].iter().map(PathBuf::from).collect();
    zkfdo::candidate_review::lifting::instances::write(&inputs, &PathBuf::from(&args[at + 1]))?;
    Ok(())
}
''')
    info = {"schema": "s-round4d-j-tests-v1", "test_names": names,
            "source_rows": source_rows, "manifest_sha256": sha(folder / "Cargo.toml"),
            "inventory_sha256": sha(inventory), "engine_sha256": ENGINE_SHA,
            "fixture_probe": str(ROUND / "fixture-probe-v1/summary.json")}
    (folder / "preparation.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"harness": str(folder), "tests": len(names)}))


def bridge(argv: list[str]) -> None:
    if sha(ENGINE) != ENGINE_SHA:
        raise ValueError("v2.3 engine SHA changed")
    if not argv or argv[0] != "experiment" or len(argv) < 2:
        raise ValueError("only historical experiment CLI supported")
    action, rest = argv[1], argv[2:]
    if action == "lift-instances":
        join = Path(os.environ["S_ROUND4D_JOIN"]).absolute()
        if not join.resolve().is_relative_to(ROOT / "runs/s-round4-2026-10-27/cargo-target"):
            raise ValueError("join helper outside dedicated cargo target")
        os.execv(str(join), [str(join), *rest])
    if action != "lift" or len(rest) % 2:
        raise ValueError("only historical lift flag pairs supported")
    flags = dict(zip(rest[::2], rest[1::2]))
    if len(flags) * 2 != len(rest) or "--request" not in flags or "--output" not in flags:
        raise ValueError("incomplete or repeated historical J arguments")
    allowed = {"--request", "--output", "--cache", "--instance-store", "--circom-bin",
               "--node-bin", "--snarkjs-bin", "--z3-bin"}
    if set(flags) - allowed:
        raise ValueError("unexpected historical J flag")
    temp = checked(os.environ["S_ROUND4D_TEST_TMP"])
    output = Path(flags["--output"]).absolute()
    if not output.resolve().is_relative_to(temp):
        raise ValueError("J output escaped temporary root")
    for flag, suffix in (("--cache", "cache"), ("--instance-store", "store")):
        flags[flag] = str(checked(flags.get(flag, str(output.parent / (output.name + "-" + suffix)))))
    for name in ("circom", "node", "snarkjs", "z3"):
        flag = "--" + name + "-bin"
        if flag not in flags:
            tool = shutil.which(name)
            if not tool:
                raise ValueError("missing existing tool: " + name)
            flags[flag] = tool
        else:
            checked(flags[flag])
    command = [str(ENGINE), *(item for pair in flags.items() for item in pair)]
    os.execv(command[0], command)


def run_tests(folder: Path, output: Path) -> None:
    folder, output = checked(folder), checked(output)
    probe = json.loads((ROUND / "fixture-probe-v1/summary.json").read_text())
    if not probe["all_at_most_1000"]:
        raise ValueError("J test fixture exceeds 1000 constraints")
    if output.exists():
        raise ValueError("new test output required")
    output.mkdir(parents=True)
    temporary = output / "temporary"
    temporary.mkdir()
    info = json.loads((folder / "preparation.json").read_text())
    suffix = folder.name.removeprefix("j-tests-")
    build_log = Path(os.environ.get("S_ROUND4D_BUILD_LOG", str(ROOT / (
        "runs/s-round4-2026-10-27/round4c/monitoring/monitor/"
        f"4d-jharness-build-{suffix}-1/stdout.log"))))
    binaries = {}
    for line in build_log.read_text().splitlines():
        try:
            artifact = json.loads(line)
        except ValueError:
            continue
        if artifact.get("reason") == "compiler-artifact" and artifact.get("executable"):
            binaries[(artifact["target"]["name"], artifact["profile"]["test"])] = artifact["executable"]
    join = binaries[("s-round4d-join", False)]
    environment = dict(os.environ, TMPDIR=str(temporary), S_ROUND4D_TEST_TMP=str(temporary),
                       S_ROUND4D_TEST_BRIDGE=str(Path(__file__).resolve()), S_ROUND4D_JOIN=join,
                       RAYON_NUM_THREADS="1", OMP_NUM_THREADS="1")
    rows = []
    for index, name in enumerate(info["test_names"]):
        source = next(row for row in info["source_rows"] if "fn " + name + "(" in
                      Path(row["generated"]).read_text())
        binary = binaries[(Path(source["generated"]).stem, True)]
        argv = [binary, name, "--exact", "--test-threads=1"]
        case = output / f"case-{index:02d}"
        case.mkdir()
        with (case / "stdout.log").open("xb") as stdout, (case / "stderr.log").open("xb") as stderr:
            try:
                completed = subprocess.run(argv, cwd=ROOT, env=environment, stdout=stdout,
                                           stderr=stderr, timeout=300, check=False)
                status, code = "completed", completed.returncode
            except subprocess.TimeoutExpired:
                status, code = "timeout", None
        passed = code == 0 and "1 passed; 0 failed" in (case / "stdout.log").read_text()
        rows.append({"name": name, "argv": argv, "status": status, "returncode": code,
                     "passed": passed, "stdout_sha256": sha(case / "stdout.log"),
                     "stderr_sha256": sha(case / "stderr.log")})
        print(json.dumps({"name": name, "passed": passed}), flush=True)
    receipt = {"schema": "s-round4d-24-J-tests-v1", "engine_sha256": ENGINE_SHA,
               "fixture_max_constraints": max(r["constraints"] for r in probe["rows"]),
               "passed": sum(r["passed"] for r in rows), "failed": sum(not r["passed"] for r in rows),
               "rows": rows}
    (output / "summary.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    if receipt["failed"]:
        raise RuntimeError(f"{receipt['failed']} of 24 J tests failed")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "experiment":
        bridge(sys.argv[1:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--output", type=Path, required=True)
    r = sub.add_parser("run-tests")
    r.add_argument("--harness", type=Path, required=True)
    r.add_argument("--output", type=Path, required=True)
    b = sub.add_parser("bridge")
    b.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output)
    elif args.command == "run-tests":
        run_tests(args.harness, args.output)
    else:
        bridge(args.args)


if __name__ == "__main__":
    main()
