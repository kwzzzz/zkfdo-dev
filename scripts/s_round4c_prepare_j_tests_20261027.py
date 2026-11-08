#!/usr/bin/env python3
"""Copy 24 regression assertions into a new crate, changing only execution paths."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

import s_round4c_postdeadline_20261027 as post


def prepare(folder):
    folder = post.checked_output(folder)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "tests").mkdir()
    (folder / "src/bin").mkdir(parents=True)
    names = json.loads((post.ROOT / "runs/s-inspection-improve-2026-10-27/cargo-command-reference.json").read_text())["skipped_J_tests"]
    evidence, found = [], set()
    for filename in ("lifting_engine_test.rs", "lifting_engine_regression_test.rs"):
        source = post.ROOT / "tests" / filename
        text = source.read_text()
        tests = re.findall(r"#\[test\]\s*fn\s+(\w+)\(", text)
        found.update(set(tests) & set(names))
        replacements = [
            ('env!("CARGO_MANIFEST_DIR")', json.dumps(str(post.ROOT))),
            ('Command::cargo_bin("zkfDO")', 'round4c_command()'),
            ('let base = root.join("runs/n6-j4c-2026-10-17.noindex");',
             'let base = std::path::PathBuf::from(std::env::var_os("S_ROUND4C_TEST_TMP").unwrap());'),
            ('fs::read_dir(&store)', 'fs::read_dir(store.join("j-v2.3"))'),
            ('fs::read_dir(store)', 'fs::read_dir(store.join("j-v2.3"))'),
        ]
        counts = []
        for old, new in replacements:
            counts.append({"before": old, "after": new, "count": text.count(old)})
            text = text.replace(old, new)
        text += '''
fn round4c_command() -> std::io::Result<assert_cmd::Command> {
    Ok(assert_cmd::Command::new(std::env::var_os("S_ROUND4C_TEST_BRIDGE").unwrap()))
}
'''
        path = folder / "tests" / filename
        path.write_text(text)
        evidence.append({"source": str(source), "source_sha256": post.sha(source),
                         "generated": str(path), "generated_sha256": post.sha(path),
                         "replacements": counts})
    post.require(found == set(names) and len(names) == 24, "24-test inventory changed")
    manifest = '''[package]
name = "s-round4c-j-tests"
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
'''.replace("REPOSITORY", json.dumps(str(post.ROOT)))
    (folder / "Cargo.toml").write_text(manifest)
    # This auxiliary command only joins already-saved results. It never invokes lift.
    (folder / "src/bin/s-round4c-join.rs").write_text('''use std::path::PathBuf;
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
    # Keep the repository's dependency versions; Cargo may add only the new root
    # package to this copy under --offline. The repository lock is never changed.
    (folder / "Cargo.lock").write_bytes((post.ROOT / "Cargo.lock").read_bytes())
    return post.write_new(folder / "preparation.json", {
        "schema": "s-round4c-j-tests-v1", "test_names": names, "test_count": len(names),
        "manifest": {"path": str(folder / "Cargo.toml"), "sha256": post.sha(folder / "Cargo.toml")},
        "sources": evidence, "executed": False,
        "mechanical_changes": "fixture root, binary dispatch, owned temporary root, explicit v2.3 store namespace; assertions unchanged"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    print(json.dumps(prepare(parser.parse_args().output)))
