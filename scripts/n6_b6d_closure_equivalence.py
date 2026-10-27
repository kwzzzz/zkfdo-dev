#!/usr/bin/env python3
"""Read-only N6-B6d include-closure and template-name equivalence audit.

The closure comes from the fixed engine's public targets::discovery_dependency_paths,
not from a second implementation of Circom include resolution.  Only source paths
and source text are read.  Request JSON is projected onto four path fields; no
candidate, witness, or judgment result is opened.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXED_ENGINE_COMMIT = "8065e2b7e165ef3f4c1523f240f5d34ecaefdb22"
HELPER_ROOT = ROOT / "runs/n6-b6d-2026-10-20.noindex/closure-helper"
HELPER_SOURCE = r'''use std::io::{self, BufRead};
use std::path::PathBuf;
use serde::{Deserialize, Serialize};
use zkfdo::targets::discovery_dependency_paths;

#[derive(Deserialize)]
struct Query {
    source_root: PathBuf,
    component_wrapper: PathBuf,
    entrypoint: PathBuf,
    library_paths: Vec<PathBuf>,
}
#[derive(Serialize)]
struct Answer {
    wrapper: Option<Vec<PathBuf>>,
    entrypoint: Option<Vec<PathBuf>>,
    error: Option<String>,
}
fn main() {
    for line in io::stdin().lock().lines() {
        let answer = match line {
            Ok(line) => match serde_json::from_str::<Query>(&line) {
                Ok(query) => {
                    let wrapper = discovery_dependency_paths(
                        &query.component_wrapper, &query.source_root, &query.library_paths);
                    let entrypoint = discovery_dependency_paths(
                        &query.entrypoint, &query.source_root, &query.library_paths);
                    match (wrapper, entrypoint) {
                        (Ok(wrapper), Ok(entrypoint)) => Answer {
                            wrapper: Some(wrapper), entrypoint: Some(entrypoint), error: None,
                        },
                        (Err(error), _) | (_, Err(error)) => Answer {
                            wrapper: None, entrypoint: None, error: Some(format!("{error:#}")),
                        },
                    }
                }
                Err(error) => Answer {
                    wrapper: None, entrypoint: None, error: Some(error.to_string()),
                },
            },
            Err(error) => Answer {
                wrapper: None, entrypoint: None, error: Some(error.to_string()),
            },
        };
        println!("{}", serde_json::to_string(&answer).expect("serialize answer"));
    }
}
'''
HELPER_TOML = '''[package]
name = "n6_b6d_closure_helper"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
zkfdo = { path = "../../../../" }
'''


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON object required: {path}")
    return data


def source_request(path: Path) -> dict[str, Any]:
    """Project an index request onto the only fields this audit may use."""
    data = read_json(path)
    result = {key: data[key] for key in (
        "source_root", "component_wrapper", "entrypoint", "library_paths")}
    if not isinstance(result["library_paths"], list):
        raise ValueError(f"library_paths must be a list: {path}")
    return result


def request_key(request: dict[str, Any]) -> tuple[str, str, str, tuple[str, ...]]:
    return (request["source_root"], request["component_wrapper"],
            request["entrypoint"], tuple(request["library_paths"]))


def helper_binary() -> Path:
    """Build a tiny caller of the fixed public closure function in ignored runs/."""
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            check=True, capture_output=True, text=True).stdout.strip()
    if commit != FIXED_ENGINE_COMMIT:
        raise ValueError(f"fixed engine commit changed: {commit}")
    cargo = HELPER_ROOT / "Cargo.toml"
    source = HELPER_ROOT / "src/main.rs"
    binary = HELPER_ROOT / "n6_b6d_closure_helper"
    expected_toml = HELPER_TOML.replace('path = "../../../../"',
                                        f'path = "{ROOT}"')
    if binary.is_file():
        if not cargo.is_file() or not source.is_file() or (
                cargo.read_text() != expected_toml or source.read_text() != HELPER_SOURCE):
            raise ValueError("existing closure helper source differs")
        return binary
    if HELPER_ROOT.exists():
        raise ValueError("incomplete existing closure helper; refusing to overwrite")
    (HELPER_ROOT / "src").mkdir(parents=True, exist_ok=False)
    cargo.write_text(expected_toml, encoding="utf-8")
    source.write_text(HELPER_SOURCE, encoding="utf-8")
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = str(ROOT / "target")
    subprocess.run(["cargo", "build", "--offline", "--manifest-path", str(cargo)],
                   cwd=ROOT, env=env, check=True)
    built = ROOT / "target/debug/n6_b6d_closure_helper"
    if not built.is_file():
        raise ValueError("closure helper binary missing after cargo build")
    with built.open("rb") as reader, binary.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    binary.chmod(0o755)
    return binary


def fixed_closures(requests: list[dict[str, Any]], binary: Path) -> list[dict[str, Any]]:
    payload = "".join(json.dumps(request, sort_keys=True) + "\n" for request in requests)
    result = subprocess.run([str(binary)], input=payload, capture_output=True,
                            text=True, check=True)
    lines = result.stdout.splitlines()
    if len(lines) != len(requests):
        raise ValueError(f"closure helper returned {len(lines)} for {len(requests)} requests")
    answers = [json.loads(line) for line in lines]
    for answer in answers:
        if answer["error"] is None:
            for field in ("wrapper", "entrypoint"):
                answer[field] = [str(Path(path).resolve(strict=True))
                                 for path in answer[field]]
            answer["union"] = sorted(set(answer["wrapper"]) | set(answer["entrypoint"]))
    return answers


def mask_source(source: str) -> str:
    """Mirror lifting/source.rs::mask for ASCII syntax and preserve offsets."""
    data = bytearray(source.encode("utf-8"))
    index = 0
    while index < len(data):
        if data[index:index + 2] == b"//":
            while index < len(data) and data[index] != 10:
                data[index] = 32
                index += 1
        elif data[index:index + 2] == b"/*":
            while index < len(data) and data[index:index + 2] != b"*/":
                if data[index] != 10:
                    data[index] = 32
                index += 1
            for _ in range(2):
                if index < len(data):
                    data[index] = 32
                    index += 1
        elif data[index] == 34:
            data[index] = 32
            index += 1
            while index < len(data) and data[index] != 34:
                if data[index] != 10:
                    data[index] = 32
                index += 1
            if index < len(data):
                data[index] = 32
                index += 1
        else:
            index += 1
    return data.decode("utf-8", errors="replace")


def template_names(path: Path) -> list[str]:
    """Mirror lifting/source.rs::parse_templates name and body boundaries."""
    masked = mask_source(path.read_text(encoding="utf-8"))
    names: list[str] = []
    cursor = 0
    keyword = re.compile(r"(?<![A-Za-z0-9_$])template(?![A-Za-z0-9_$])")
    ident = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
    while found := keyword.search(masked, cursor):
        position = found.end()
        while position < len(masked) and masked[position].isspace():
            position += 1
        while (modifier := ident.match(masked, position)) and modifier.group() in (
                "custom", "parallel"):
            position = modifier.end()
            while position < len(masked) and masked[position].isspace():
                position += 1
        name = ident.match(masked, position)
        if not name:
            cursor = found.start() + 1
            continue
        position = name.end()
        while position < len(masked) and masked[position].isspace():
            position += 1
        if position >= len(masked) or masked[position] != "(":
            cursor = found.start() + 1
            continue
        header_end = balanced_end(masked, position, "(", ")")
        position = header_end + 1
        while position < len(masked) and masked[position].isspace():
            position += 1
        if position >= len(masked) or masked[position] != "{":
            raise ValueError(f"template {name.group()} body absent: {path}")
        body_end = balanced_end(masked, position, "{", "}")
        names.append(name.group())
        cursor = body_end + 1
    return names


def balanced_end(source: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    for index in range(start, len(source)):
        if source[index] == opening:
            depth += 1
        elif source[index] == closing:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unbalanced {opening}{closing} at {start}")


def main_template_name(wrapper: Path) -> str | None:
    masked = mask_source(wrapper.read_text(encoding="utf-8"))
    start = masked.find("component main")
    if start < 0:
        return None
    rest = masked[start:]
    equals = rest.find("=")
    if equals < 0:
        return None
    name = re.match(r"[A-Za-z0-9_$]+", rest[equals + 1:].lstrip())
    return name.group() if name else None


def declarations(paths: list[str], cache: dict[str, list[str]]) -> dict[str, list[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for raw in paths:
        if raw not in cache:
            cache[raw] = template_names(Path(raw))
        for name in cache[raw]:
            found[name].add(raw)
    return {name: sorted(files) for name, files in sorted(found.items())}


def inspect_a(index_path: Path, binary: Path) -> dict[str, Any]:
    index = read_json(index_path)
    rows = index["requests"]
    if index["request_count"] != len(rows):
        raise ValueError("A request count mismatch")
    unique: dict[tuple[str, str, str, tuple[str, ...]], dict[str, Any]] = {}
    by_revision: dict[str, Counter[str]] = defaultdict(Counter)
    pair_revisions: dict[tuple[str, str, str, tuple[str, ...]], set[str]] = defaultdict(set)
    pair_invoked: Counter[tuple[str, str, str, tuple[str, ...]]] = Counter()
    for row in rows:
        request = source_request(Path(row["request"]))
        key = request_key(request)
        unique.setdefault(key, request)
        pair_revisions[key].add(row["revision_id"])
        by_revision[row["revision_id"]]["requests"] += 1
        if row.get("preparation_failure") is None:
            by_revision[row["revision_id"]]["engine_invoked"] += 1
            pair_invoked[key] += 1
        else:
            by_revision[row["revision_id"]]["premarked"] += 1
    keys = list(unique)
    answers = fixed_closures(list(unique.values()), binary)
    cache: dict[str, list[str]] = {}
    pair_reports = []
    for key, request, answer in zip(keys, unique.values(), answers, strict=True):
        revisions = sorted(pair_revisions[key])
        pair_id = hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]
        if answer["error"] is None:
            names = declarations(answer["union"], cache)
            main = main_template_name(Path(request["component_wrapper"]))
            main_files = names.get(main, []) if main is not None else []
            duplicates = {name: len(files) for name, files in names.items()
                          if len(files) > 1}
            if len(main_files) == 1:
                state = "ok"
            elif pair_invoked[key]:
                state = "main_template_not_unique"
            else:
                state = "premarked_main_template_not_unique"
            report = {"pair_id": pair_id, "revisions": revisions, "status": state,
                      "engine_invoked_request_count": pair_invoked[key],
                      "wrapper_count": len(answer["wrapper"]),
                      "entrypoint_count": len(answer["entrypoint"]),
                      "union_count": len(answer["union"]),
                      "main_template": main, "main_template_file_count": len(main_files),
                      "main_template_files": main_files,
                      "duplicate_template_names": duplicates}
        else:
            report = {"pair_id": pair_id, "revisions": revisions,
                      "status": "closure_error" if pair_invoked[key] else "premarked_closure_error",
                      "engine_invoked_request_count": pair_invoked[key],
                      "detail": answer["error"]}
        pair_reports.append(report)
        for revision in revisions:
            by_revision[revision]["pairs"] += 1
            by_revision[revision][report["status"]] += 1
    statuses_not_reached = {"premarked_main_template_not_unique", "premarked_closure_error"}
    status = "pass" if all(p["status"] == "ok" or p["status"] in statuses_not_reached
                           for p in pair_reports) else "fail"
    return {"status": status, "request_count": len(rows), "revision_count": len(by_revision),
            "unique_pair_count": len(unique), "revisions": {
                name: dict(sorted(counts.items())) for name, counts in sorted(by_revision.items())},
            "pairs": pair_reports, "template_parser_source": "src/candidate_review/lifting/source.rs:79-125",
            "closure_source": "src/targets.rs:989-1035,2923-2967,3015-3043"}


def inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def mapped_path(original: Path, pair: dict[str, Any]) -> Path:
    """Map one original canonical source to its sole regular-file unit copy."""
    original = original.resolve(strict=True)
    clone = Path(pair["original_clone_root"]).resolve(strict=True)
    project = Path(pair["project_root"]).resolve(strict=True)
    preparation_original = Path(pair["original_preparation_root"]).resolve(strict=True)
    preparation = Path(pair["preparation_root"]).resolve(strict=True)
    if original == Path(pair["original_wrapper"]).resolve(strict=True):
        return Path(pair["wrapper"]).resolve(strict=True)
    if inside(original, clone):
        return (project / original.relative_to(clone)).resolve(strict=True)
    for allowed in pair.get("external_library_paths", []):
        if inside(original, Path(allowed).resolve(strict=True)):
            return original
    if inside(original, preparation_original):
        return (preparation / original.relative_to(preparation_original)).resolve(strict=True)
    raise ValueError(f"source outside clone, preparation, and external -l: {original}")


INCLUDE_LINE = re.compile(r'^(?P<prefix>[^\n]*\binclude\s*")'
                          r'(?P<literal>[^"\n]+)(?P<suffix>"[^\n]*)$')


def include_only_change(original: Path, staged: Path, pair: dict[str, Any]) -> list[int]:
    """Check byte-exact lines except clone-absolute include literals.

    Returns changed one-based line numbers.  A relative include, spacing change,
    line ending change, or a path outside the original clone is not accepted.
    """
    before = original.read_bytes().splitlines(keepends=True)
    after = staged.read_bytes().splitlines(keepends=True)
    if len(before) != len(after):
        raise ValueError("line count changed")
    clone = Path(pair["original_clone_root"]).resolve(strict=True)
    project = Path(pair["project_root"]).resolve(strict=True)
    changed = []
    for number, (old_line, new_line) in enumerate(zip(before, after, strict=True), 1):
        if old_line == new_line:
            continue
        old_text = old_line.decode("utf-8")
        new_text = new_line.decode("utf-8")
        old_ending = old_text[len(old_text.rstrip("\r\n")):]
        new_ending = new_text[len(new_text.rstrip("\r\n")):]
        old = INCLUDE_LINE.fullmatch(old_text.rstrip("\r\n"))
        new = INCLUDE_LINE.fullmatch(new_text.rstrip("\r\n"))
        if not old or not new or old.group("prefix") != new.group("prefix") or (
                old.group("suffix") != new.group("suffix")) or old_ending != new_ending:
            raise ValueError(f"non-include byte difference at line {number}")
        original_literal = Path(old.group("literal"))
        if not original_literal.is_absolute():
            raise ValueError(f"relative include changed at line {number}")
        original_target = original_literal.resolve(strict=True)
        if not inside(original_target, clone):
            raise ValueError(f"non-clone absolute include changed at line {number}")
        expected = project / original_target.relative_to(clone)
        if Path(new.group("literal")).resolve(strict=True) != expected.resolve(strict=True):
            raise ValueError(f"include target mismatch at line {number}")
        changed.append(number)
    if not changed:
        raise ValueError("content SHA changed without a changed include line")
    return changed


def compare_source_pair(original_request: dict[str, Any], staged_request: dict[str, Any],
                        pair: dict[str, Any], original_answer: dict[str, Any],
                        staged_answer: dict[str, Any],
                        template_cache: dict[str, list[str]]) -> dict[str, Any]:
    """Return E1/E2 evidence for one of the 17 source pairs."""
    result: dict[str, Any] = {"pair_id": pair["pair_id"],
                              "revision_id": pair["revision_id"],
                              "queue_orders": sorted(pair["queue_orders"])}
    failures: list[str] = []
    if original_answer["error"] is not None:
        failures.append(f"original_closure: {original_answer['error']}")
    if staged_answer["error"] is not None:
        failures.append(f"staged_closure: {staged_answer['error']}")
    if failures:
        result.update({"e1_status": "fail", "e2_status": "fail", "failures": failures})
        return result

    original_paths = [Path(path).resolve(strict=True) for path in original_answer["union"]]
    staged_paths = {str(Path(path).resolve(strict=True)) for path in staged_answer["union"]}
    mapped: dict[str, str] = {}
    files = []
    for original in original_paths:
        try:
            staged = mapped_path(original, pair)
            mapped[str(original)] = str(staged)
            old_sha = sha256_file(original)
            new_sha = sha256_file(staged)
            change_lines = [] if old_sha == new_sha else include_only_change(original, staged, pair)
            files.append({"original": str(original), "staged": str(staged),
                          "original_sha256": old_sha, "staged_sha256": new_sha,
                          "include_rewrite_lines": change_lines})
        except (OSError, ValueError) as error:
            failures.append(f"path_or_bytes: {original}: {error}")
    if len(original_paths) != len(staged_paths):
        failures.append(f"closure_count: {len(original_paths)} -> {len(staged_paths)}")
    if len(set(mapped.values())) != len(mapped):
        failures.append("original paths map to duplicate staged canonical paths")
    if set(mapped.values()) != staged_paths:
        failures.append("staged closure differs from mapped original closure")
    unit = Path(pair["source_root"]).resolve(strict=True)
    external_roots = [Path(path).resolve(strict=True)
                      for path in pair.get("external_library_paths", [])]
    outside = sorted(path for path in staged_paths if not inside(Path(path), unit))
    not_exception = [path for path in outside if not any(
        inside(Path(path), external) for external in external_roots)]
    if not_exception:
        failures.append(f"staged closure escapes unit without -l exception: {not_exception}")
    result.update({"original_wrapper_count": len(original_answer["wrapper"]),
                   "original_entrypoint_count": len(original_answer["entrypoint"]),
                   "original_union_count": len(original_paths),
                   "staged_wrapper_count": len(staged_answer["wrapper"]),
                   "staged_entrypoint_count": len(staged_answer["entrypoint"]),
                   "staged_union_count": len(staged_paths),
                   "staged_outside_unit": outside,
                   "files": files})
    result["e1_status"] = "pass" if not failures else "fail"

    original_names = declarations([str(path) for path in original_paths], template_cache)
    staged_names = declarations(sorted(staged_paths), template_cache)
    original_main = main_template_name(Path(original_request["component_wrapper"]))
    staged_main = main_template_name(Path(staged_request["component_wrapper"]))
    original_duplicate = {name: len(paths) for name, paths in original_names.items()
                          if len(paths) > 1}
    staged_duplicate = {name: len(paths) for name, paths in staged_names.items()
                        if len(paths) > 1}
    if original_main is None or original_main != staged_main:
        failures.append(f"main template name differs: {original_main} -> {staged_main}")
    if len(original_names.get(original_main, [])) != 1 or (
            len(staged_names.get(staged_main, [])) != 1):
        failures.append("main template file count is not one in both closures")
    if original_duplicate != staged_duplicate:
        failures.append("duplicate template name counts differ")
    for name, originals in original_names.items():
        corresponding = {mapped.get(path) for path in originals}
        if None in corresponding or corresponding != set(staged_names.get(name, [])):
            failures.append(f"template declaration files differ for {name}")
    if set(original_names) != set(staged_names):
        failures.append("template name sets differ")
    result.update({"main_template": original_main,
                   "original_main_template_file_count": len(original_names.get(original_main, [])),
                   "staged_main_template_file_count": len(staged_names.get(staged_main, [])),
                   "original_duplicate_template_names": original_duplicate,
                   "staged_duplicate_template_names": staged_duplicate,
                   "template_name_count": len(original_names),
                   "e2_status": "pass" if not failures else "fail", "failures": failures})
    return result


def inspect_b(original_index_path: Path, manifest_path: Path,
              binary: Path) -> dict[str, Any]:
    index = read_json(original_index_path)
    manifest = read_json(manifest_path)
    rows = index["requests"]
    pairs = manifest["pairs"]
    if len(rows) != index["request_count"] or len(rows) != 107 or len(pairs) != 17:
        raise ValueError("B index/manifest count differs from 107 requests and 17 pairs")
    queue = {row["queue_order"]: row for row in rows}
    if len(queue) != 107:
        raise ValueError("duplicate B queue order")
    covered = [order for pair in pairs for order in pair["queue_orders"]]
    if sorted(covered) != sorted(queue):
        raise ValueError("manifest queue orders do not cover B index exactly")
    originals = []
    staged = []
    for pair in pairs:
        first = source_request(Path(queue[pair["queue_orders"][0]]["request"]))
        for order in pair["queue_orders"]:
            other = source_request(Path(queue[order]["request"]))
            if request_key(other) != request_key(first):
                raise ValueError(f"pair {pair['pair_id']} mixes source requests")
            if queue[order]["revision_id"] != pair["revision_id"]:
                raise ValueError(f"pair {pair['pair_id']} mixes revisions")
        for old_key, field in (("original_wrapper", "component_wrapper"),
                               ("original_entrypoint", "entrypoint"),
                               ("original_library_paths", "library_paths")):
            if pair[old_key] != first[field]:
                raise ValueError(f"pair {pair['pair_id']} {old_key} differs from B6 index")
        new = {"source_root": pair["source_root"],
               "component_wrapper": pair["wrapper"],
               "entrypoint": pair["entrypoint"],
               "library_paths": pair["library_paths"]}
        originals.append(first)
        staged.append(new)
    answers = fixed_closures(originals + staged, binary)
    old_answers = answers[:len(pairs)]
    new_answers = answers[len(pairs):]
    template_cache: dict[str, list[str]] = {}
    reports = [compare_source_pair(old, new, pair, old_answer, new_answer,
                                   template_cache)
               for old, new, pair, old_answer, new_answer in zip(
                   originals, staged, pairs, old_answers, new_answers, strict=True)]
    per_revision: dict[str, Counter[str]] = defaultdict(Counter)
    for report in reports:
        counts = per_revision[report["revision_id"]]
        counts["pairs"] += 1
        counts["requests"] += len(report["queue_orders"])
        counts[f"e1_{report['e1_status']}"] += 1
        counts[f"e2_{report['e2_status']}"] += 1
    return {"request_count": len(rows), "pair_count": len(pairs),
            "e1": {"status": "pass" if all(r["e1_status"] == "pass" for r in reports)
                   else "fail"},
            "e2": {"status": "pass" if all(r["e2_status"] == "pass" for r in reports)
                   else "fail"},
            "revisions": {name: dict(sorted(counts.items())) for name, counts
                          in sorted(per_revision.items())},
            "pairs": reports}


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a-index", type=Path)
    parser.add_argument("--original-b-index", type=Path)
    parser.add_argument("--staging-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"output already exists: {args.output}")
    binary = helper_binary()
    if args.a_index is None and (args.original_b_index is None or
                                 args.staging_manifest is None):
        raise ValueError("--a-index or both B inputs are required")
    report = {"schema_version": 1, "kind": "n6_b6d_closure_equivalence",
              "fixed_engine_commit": FIXED_ENGINE_COMMIT,
              "helper_source_sha256": sha256_file(HELPER_ROOT / "src/main.rs"),
              "helper_binary_sha256": sha256_file(binary)}
    if args.a_index is not None:
        report.update({"a_index": str(args.a_index.resolve()),
                       "a_index_sha256": sha256_file(args.a_index),
                       "a": inspect_a(args.a_index, binary)})
    if args.original_b_index is not None and args.staging_manifest is not None:
        report.update({"original_b_index": str(args.original_b_index.resolve()),
                       "original_b_index_sha256": sha256_file(args.original_b_index),
                       "staging_manifest": str(args.staging_manifest.resolve()),
                       "staging_manifest_sha256": sha256_file(args.staging_manifest),
                       "b": inspect_b(args.original_b_index, args.staging_manifest, binary)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    statuses = []
    if "a" in report:
        statuses.append(report["a"]["status"])
    if "b" in report:
        statuses.extend((report["b"]["e1"]["status"],
                         report["b"]["e2"]["status"]))
    status = "pass" if all(item == "pass" for item in statuses) else "fail"
    print(json.dumps({"output": str(args.output), "status": status,
                      "a_revisions": report.get("a", {}).get("revision_count"),
                      "b_pairs": report.get("b", {}).get("pair_count")}, sort_keys=True))
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(cli())
