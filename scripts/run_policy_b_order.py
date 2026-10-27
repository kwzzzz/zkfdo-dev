#!/usr/bin/env python3
"""Deterministic Policy B ordering of prepared metadata; never launches a process.

Input: {"schema_version": 1, "unit": "...", "targets": [{"label": "...",
"target_id": "...", "template": "...", "defining_source_file": "...",
"constraints": 12, "eligible": true, "concrete_parameters": ["2"]}]}.
Only eligible rows with known nonnegative total constraint counts are ordered.
No bug mapping, candidate data, result score, or observed attempt duration is an
ordering input. The CLI writes only a new file in runs/s-tag-wrapper-2026-10-27.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "runs/s-tag-wrapper-2026-10-27"
BUDGET_SECONDS = 600
ATTEMPT_CAP_SECONDS = 30
POLICY_VERSION = "B-template-source-round-robin-v1"
POLICY_TEXT = (
    "정책 B: (템플릿 이름, 정의 소스 파일)로 그룹을 만든다. "
    "그룹 안 인스턴스는 (전체 제약 수, target_id, label) 오름차순이다. "
    "각 라운드에서 모든 남은 그룹의 다음 인스턴스를 하나씩 방문한 뒤 다음 라운드로 간다. "
    "매 라운드 그룹 순서는 자체 소스 우선, third-party 다음이며, 같은 분류에서는 "
    "(그룹의 최소 전체 제약 수, 템플릿 이름, 정의 소스 파일) 오름차순이다. "
    "정의 소스의 디렉터리 요소가 node_modules 또는 circomlib이면 third-party다. "
    "그 밖의 vendor 이름만으로 third-party로 분류하지 않는다. "
    "모든 인스턴스를 한 번 방문한 뒤 같은 전체 순서를 반복한다. "
    "총예산 600초, 시도 상한 30초, 남은 예산이 양수이면 min(30초, 남은 예산)을 할당한다. "
    "결함 이름·RQ-C 위치·후보·판정·관측 시간은 순서에 사용하지 않는다. "
    "준비 적격이 아니거나 제약 수가 없는 대상은 가용성 집합에서 제외하며 값을 추측하지 않는다."
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def guard():
    require(os.getpriority(os.PRIO_PROCESS, 0) >= 19, "nice 19 required")
    if shutil.disk_usage(ROOT).free < 15 * 1024**3:
        raise RuntimeError("PAUSE_LOW_DISK: stop new work; coordinator rechecks in 5 minutes")


def checked_path(name, output=False):
    p = Path(name).resolve()
    require(p.is_relative_to(ROOT), "path outside repository")
    require(not any(x.startswith(("n6-b6", "h1-", "n6-a-remeasure-2026-10-25"))
                    for x in p.parts), "protected input/output path")
    if output:
        require(p.is_relative_to(OUTPUT_ROOT) and p != OUTPUT_ROOT, "output outside new task directory")
        require(not p.exists(), "output already exists")
    return p


def read_json(name, expected=None):
    guard()
    p = checked_path(name)
    require(p.stat().st_size <= 64 * 1024**2, "metadata file exceeds 64 MiB")
    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    require(expected is None or digest == expected, "input SHA-256 mismatch: " + str(p))
    return json.loads(data), {"path": str(p), "sha256": digest}


def write_json(name, data):
    guard()
    p = checked_path(name, output=True)
    encoded = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    require(len(encoded) <= 2_000_000, "output exceeds 2 MB")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("xb") as stream:
        stream.write(encoded)
    return {"path": str(p), "sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded)}


def source_class(source):
    require(isinstance(source, str) and source and "\\" not in source, "source must be a POSIX path")
    path = PurePosixPath(source)
    require(str(path) == source and ".." not in path.parts, "source path must be normalized")
    return "third_party" if any(p in {"node_modules", "circomlib"} for p in path.parts[:-1]) else "own"


def group_key(row):
    return row["template"], row["defining_source_file"]


def checked_targets(rows):
    require(isinstance(rows, list), "targets must be a list")
    result, labels = [], set()
    for row in rows:
        require(isinstance(row, dict), "target must be an object")
        for key in ("label", "target_id", "template", "defining_source_file"):
            require(isinstance(row.get(key), str) and bool(row[key]), "missing target " + key)
        require(row["label"] not in labels, "duplicate target label")
        labels.add(row["label"])
        source_class(row["defining_source_file"])
        require(type(row.get("eligible")) is bool, "eligible must be boolean")
        if row["eligible"]:
            size = row.get("constraints")
            require(type(size) is int and size >= 0, "eligible target needs a nonnegative constraint count")
            result.append(row)
    return result


def instantiation_key(row):
    return row["constraints"], row["target_id"], row["label"]


def policy_a_order(rows):
    """Existing flat small-first key: src/static_rank.rs:214-217."""
    return sorted(checked_targets(rows), key=instantiation_key)


def policy_b_order(rows):
    groups = {}
    for row in checked_targets(rows):
        groups.setdefault(group_key(row), []).append(row)
    for values in groups.values():
        values.sort(key=instantiation_key)
    keys = sorted(groups, key=lambda key: (
        source_class(key[1]) != "own", groups[key][0]["constraints"], key[0], key[1]))
    ordered = []
    for round_index in range(max((len(group) for group in groups.values()), default=0)):
        for key in keys:
            if round_index < len(groups[key]):
                ordered.append(groups[key][round_index])
    return ordered


def order_document(document):
    require(document.get("schema_version") == 1, "unsupported metadata schema")
    rows = policy_b_order(document["targets"])
    rounds = {}
    order = []
    for rank, row in enumerate(rows, 1):
        key = group_key(row)
        rounds[key] = rounds.get(key, 0) + 1
        order.append({key: row[key] for key in (
            "label", "target_id", "template", "defining_source_file", "constraints")} | {
                "rank": rank, "group_round": rounds[key],
                "source_class": source_class(row["defining_source_file"])})
    return {"schema_version": 1, "kind": "policy_b_order_only", "unit": document.get("unit"),
            "policy_version": POLICY_VERSION, "policy_text": POLICY_TEXT,
            "budget_seconds": BUDGET_SECONDS, "attempt_cap_seconds": ATTEMPT_CAP_SECONDS,
            "ordered_targets": len(order), "groups": len(rounds), "order": order,
            "engine_invocations": 0, "fuzz_invocations": 0}


class PolicyTests(unittest.TestCase):
    @staticmethod
    def target(label, template="T", source="circuits/own.circom", size=1, eligible=True):
        return {"label": label, "target_id": label, "template": template,
                "defining_source_file": source, "constraints": size, "eligible": eligible}

    def test_round_robin_before_second_instantiation(self):
        rows = [self.target("a1", size=1), self.target("a2", size=2),
                self.target("b1", "B", size=20), self.target("b2", "B", size=30)]
        self.assertEqual([r["label"] for r in policy_b_order(rows)], ["a1", "b1", "a2", "b2"])

    def test_source_class_precedes_size_within_every_round(self):
        rows = [self.target("v1", "V", "x/node_modules/lib/a.circom", 0),
                self.target("v2", "V", "x/node_modules/lib/a.circom", 1),
                self.target("o1", "O", size=100), self.target("o2", "O", size=200)]
        self.assertEqual([r["label"] for r in policy_b_order(rows)], ["o1", "v1", "o2", "v2"])

    def test_generic_vendor_is_own_but_exact_circomlib_directory_is_third_party(self):
        self.assertEqual(source_class("vendor/local/a.circom"), "own")
        self.assertEqual(source_class("vendor/circomlib/a.circom"), "third_party")
        self.assertEqual(source_class("circuits/circomlib.circom"), "own")
        self.assertEqual(source_class("circomlib_custom/a.circom"), "own")

    def test_group_identity_includes_defining_source(self):
        rows = [self.target("a1", source="a.circom"), self.target("a2", source="a.circom", size=2),
                self.target("b1", source="b.circom", size=50)]
        self.assertEqual([r["label"] for r in policy_b_order(rows)], ["a1", "b1", "a2"])

    def test_group_minimum_is_fixed_for_later_rounds(self):
        rows = [self.target("a1", "A", size=1), self.target("a2", "A", size=500),
                self.target("b1", "B", size=2), self.target("b2", "B", size=3)]
        self.assertEqual([r["label"] for r in policy_b_order(rows)], ["a1", "b1", "a2", "b2"])

    def test_deterministic_ties_and_no_input_mutation(self):
        rows = [self.target("z", "B"), self.target("y", "A"), self.target("x", "A")]
        before = copy.deepcopy(rows)
        self.assertEqual(policy_b_order(rows), policy_b_order(list(reversed(rows))))
        self.assertEqual(rows, before)
        self.assertEqual([r["label"] for r in policy_b_order(rows)], ["x", "z", "y"])

    def test_bug_annotations_and_times_have_no_effect(self):
        rows = [self.target("a", "A", size=2), self.target("b", "B", size=1)]
        expected = [r["label"] for r in policy_b_order(rows)]
        rows[0].update(rq_c_bug=True, candidate_count=999, judging="L1", seconds=0.01)
        self.assertEqual([r["label"] for r in policy_b_order(rows)], expected)

    def test_missing_size_and_duplicate_labels_fail_closed(self):
        with self.assertRaises(ValueError): policy_b_order([self.target("a", size=None)])
        with self.assertRaises(ValueError): policy_b_order([self.target("a"), self.target("a")])
        self.assertEqual(policy_b_order([self.target("a", size=None, eligible=False)]), [])
        with self.assertRaises(ValueError): source_class("circuits/../a.circom")

    def test_policy_a_flat_small_first(self):
        rows = [self.target("c", "A", size=1), self.target("a", "B", size=2), self.target("b", "C", size=1)]
        self.assertEqual([r["label"] for r in policy_a_order(rows)], ["b", "c", "a"])


def self_test():
    result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(PolicyTests))
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}))
    if not result.wasSuccessful():
        for _, message in result.failures + result.errors:
            print(message)
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("self-test", "order"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    guard()
    if args.action == "self-test":
        return self_test()
    require(args.input and args.output, "order requires --input and --output")
    document, source = read_json(args.input)
    result = order_document(document)
    result.update(input=source, policy_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    print(json.dumps(write_json(args.output, result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
