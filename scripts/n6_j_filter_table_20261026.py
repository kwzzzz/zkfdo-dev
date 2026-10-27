#!/usr/bin/env python3
"""Read only fixed-control S/J metadata; keep every aq judgment pending."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import time

from n6_a_size_cost_fuzz_20261026 import collect_fuzz
from n6_a_size_cost_sizes_20261026 import collect_sizes
from n6_a_size_cost_j_20261026 import summarize_j

ROOT = Path(__file__).resolve().parents[1]
AQ = "runs/n6-a-remeasure-2026-10-25.noindex/aq-exec"
STATE_NAMES = ("state.json", "state-v2.json", "state-v3.json", "state-v3_1.json")
DEFAULTS = {
    "mapping": "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json",
    "main_queue": "runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json",
    "main_state": "runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/state.json",
    "pragma_queue": "runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json",
    "pragma_state": "runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/state.json",
    "size_reuse": "runs/n6-a2b-2026-10-08.noindex/preflight-reuse-a-v4.json",
    "strict_index": "runs/n6-j1-2026-10-09.noindex/request-index.json",
    "strict_state": "runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json",
    "banyan_index_v22": "runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v2.2.json",
    "banyan_state_v22": "runs/n6-a-remeasure-2026-10-25.noindex/j-v2.2/state.json",
    "banyan_index_v1": "runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v1.json",
    "banyan_state_v1": "runs/n6-a-remeasure-2026-10-25.noindex/j-v1/state.json",
    "banyan_joins": "runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json",
    "aq_state_dir": AQ,
    "aq_state": "auto",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Reader:
    """Known files only, no directory walking or candidate/witness/result aq reads."""
    def __init__(self, root=ROOT, max_seconds=180):
        self.root = Path(root).resolve()
        self.started = time.monotonic()
        self.max_seconds = max_seconds
        self.sources = {}
        self.cache = {}
        self.guard()

    def guard(self):
        require(os.getpriority(os.PRIO_PROCESS, 0) >= 19, "nice 19 required")
        require(shutil.disk_usage(self.root).free >= 15 * 1024**3, "disk below 15 GiB")
        require(time.monotonic() - self.started <= self.max_seconds, "analysis time limit")

    def abspath(self, value):
        path = Path(value)
        path = (path if path.is_absolute() else self.root / path).resolve()
        require(path.is_relative_to(self.root), "input outside repository")
        rel = path.relative_to(self.root)
        require(not any(part.startswith(("n6-b6", "h1-")) for part in rel.parts), "B/H1 input denied")
        require(not any(part == "candidates" or part.startswith("witness") for part in rel.parts),
                "raw candidate/witness input denied")
        if "aq-exec" in rel.parts:
            require(path == self.root / AQ or (path.parent == self.root / AQ and path.name in STATE_NAMES),
                    "only aq state format/path metadata may be read")
        return path

    def raw(self, value, expected=None):
        self.guard()
        path = self.abspath(value)
        if path in self.cache:
            data = self.cache[path]
        else:
            require(path.stat().st_size <= 128 * 1024**2, "metadata input too large")
            data = path.read_bytes()
            if len(data) <= 2 * 1024**2:
                self.cache[path] = data
        digest = hashlib.sha256(data).hexdigest()
        require(expected is None or digest == expected, f"SHA-256 mismatch: {path}")
        self.sources[str(path)] = {"path": str(path), "sha256": digest, "bytes": len(data)}
        self.guard()
        return data

    def json(self, value, expected=None):
        return json.loads(self.raw(value, expected))

    def text(self, value, expected=None):
        return self.raw(value, expected).decode("utf-8")

    def digest(self, value):
        key = str(self.abspath(value))
        if key not in self.sources:
            self.raw(value)
        return self.sources[key]["sha256"]


def select_aq_state(reader, directory, choice="auto"):
    directory = reader.abspath(directory)
    require(directory == reader.root / AQ, "aq state directory must be the approved directory")
    if choice != "auto":
        unresolved = Path(choice) if Path(choice).is_absolute() else reader.root / choice
        require(not unresolved.is_symlink(), "aq state symlink denied")
        path = reader.abspath(choice)
        require(path.parent == directory and path.name in STATE_NAMES, "invalid aq state selection")
        return path
    available = []
    for generation, name in enumerate(STATE_NAMES):
        path = directory / name
        require(not path.is_symlink(), "aq state symlink denied")
        if path.is_file():
            available.append((path.stat().st_mtime_ns, generation, path))
    require(bool(available), "no aq state file exists")
    return max(available)[2]


def aq_format(reader, directory, choice):
    path = select_aq_state(reader, directory, choice)
    state = reader.json(path)
    require(str(state.get("schema", "")).startswith("n6-a-remeasure-aq-execute-v"),
            "unexpected aq state schema")
    require(isinstance(state.get("engines"), dict), "aq engine dictionary missing")
    # Deliberately do not iterate requests or open their result/score files.
    return {"path": str(path), "sha256": reader.digest(path), "schema": state["schema"],
            "selection": "latest modification time; newer generation breaks exact ties"}


def fixed_revisions(reader, mapping):
    preparation = reader.json(mapping["preparation_units"], mapping["preparation_units_sha256"])
    reader.json(mapping["targets"], mapping["targets_sha256"])
    units = {unit["unit_id"]: unit for group in ("aq_stage1_units", "development_units")
             for unit in preparation[group]}
    selected = [r["revision_id"] for r in mapping["revisions"]
                if units[r["revision_id"]]["revision_kind"] == "fixed"]
    require(len(selected) == len(set(selected)), "duplicate fixed revision")
    require(units["banyan-fixed"]["revision_kind"] == "fixed", "banyan is not fixed")
    return selected + ["banyan-fixed"]


def signature(source, template, parameters):
    require(isinstance(source, str) and isinstance(template, str), "invalid wrapper identity")
    require(all(isinstance(p, str) and re.fullmatch(r"-?\d+", p) for p in parameters),
            "unsupported wrapper parameters")
    return str(Path(source).resolve()), template, tuple(parameters)


def potential_locations(reader, revision_map, fuzz_row):
    """Count candidate-producing wrapper identities compatible with mapped roots.

    This is scheduling metadata, not proof of the actual violating instance.
    """
    if revision_map is None or revision_map.get("mapping_basis") == "pragma_equivalent":
        # A corrected wrapper may have a different byte identity from discovery.
        # Do not infer instance correspondence across that rewrite here.
        return None
    if reader.abspath(revision_map["capture_path"]).stat().st_size > 128 * 1024**2:
        # Leave oversized location metadata unclassified while judging runs.
        return None
    discovery = reader.json(revision_map["discovery_path"], revision_map["discovery_sha256"])
    targets = discovery["targets"]
    by_suffix = {}
    for target in targets:
        wrapper = target.get("generated_wrapper_path")
        if not wrapper:
            continue
        marker = "/preparation/discovery/"
        require(marker in wrapper, "unrecognized generated wrapper path")
        suffix = "preparation/discovery/" + wrapper.split(marker, 1)[1]
        by_suffix.setdefault(suffix, []).append(target)
    wanted = Counter()
    for seed in fuzz_row["S"]["per_seed"]:
        spec = reader.json(seed["spec_path"], seed["spec_sha256"])
        ledger = reader.json(seed["ledger_path"], seed["ledger_sha256"])
        for attempt in ledger["attempts"]:
            count = len(attempt["candidates"])
            if not count:
                continue
            target = spec["targets"][attempt["target_index"]]
            require(target["target_id"] == attempt["target_id"], "candidate target mismatch")
            text = reader.text(Path(target["source_snapshot_path"]) / target["entrypoint_relative"],
                               target["entrypoint_sha256"])
            masked = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)
            mains = re.findall(r"component\s+main(?:\s*\{[^}]*\})?\s*=\s*(\w+)\s*\(([^)]*)\)\s*;", masked)
            require(len(mains) == 1, "wrapper main identity missing")
            name, arguments = mains[0]
            parameters = tuple(p.strip() for p in arguments.split(",")) if arguments.strip() else ()
            matches = by_suffix.get(target["entrypoint_relative"], [])
            require(bool(matches), "wrapper absent from pinned discovery")
            signatures = {signature(m["source_path"], m["template_name"], m["concrete_parameters"])
                          for m in matches}
            require(len(signatures) == 1, "ambiguous wrapper signature")
            identity = next(iter(signatures))
            require(identity[1:] == (name, parameters), "wrapper/discovery differs")
            for match in matches:
                reader.raw(match["generated_wrapper_path"], target["entrypoint_sha256"])
            wanted[identity] += count
    capture = reader.json(revision_map["capture_path"], revision_map["capture_sha256"])
    require(capture["status"] == "captured" and
            capture["entrypoint"] == discovery["selected_entrypoint"], "capture binding differs")
    roots = {path for item in revision_map["items"] for path in item["instance_paths"]}
    seen, matched = set(), set()
    for instance in capture["instances"]:
        args = instance.get("arguments", [])
        if not all(isinstance(arg, dict) and arg.get("kind") == "scalar" for arg in args):
            continue
        identity = signature(instance["source_path"], instance["template_name"], [a["value"] for a in args])
        if identity not in wanted:
            continue
        seen.add(identity)
        paths = instance["path"]
        paths = [paths] if isinstance(paths, str) else paths
        require(isinstance(paths, list), "invalid captured instance path")
        if any(site == root or site.startswith(root + ".") or site.startswith(root + "[")
               for site in paths for root in roots):
            matched.add(identity)
    require(seen == set(wanted), "candidate wrapper missing from captured instances")
    return sum(wanted[identity] for identity in matched)


def banyan_j(reader, index_path, state_path, mapping, engine, layer, aggregate=None):
    index = reader.json(index_path)
    state = reader.json(state_path)
    require(state["request_index_sha256"] == reader.digest(index_path), "J index binding differs")
    require(state["engine_sha256"] == index["engine_sha256"], "J engine binding differs")
    rows = [row for row in index["requests"]
            if row["scope"] == "main" and row["revision_id"] == "banyan-fixed" and row["method"] == "S"]
    numbers = {str(row["queue_order"]) for row in rows}
    events = {key: value for key, value in state["requests"].items() if key in numbers}
    filtered_index = {**index, "requests": rows, "request_count": len(rows)}
    filtered_state = {**state, "requests": events}
    receipts = [{"path": row["instances_path"], "sha256": row["instances_sha256"]}
                for row in state.get("revisions", {}).values()
                if row.get("scope") == "main" and row.get("revision_id") == "banyan-fixed"
                and row.get("instances_path")]
    if aggregate:
        receipts += [row for row in aggregate["joins"]
                     if row["engine"] == engine and row.get("scope", "main") == "main" and row["revision"] == "banyan-fixed"]
    require(len(receipts) <= 1, "duplicate fixed-control join")
    joins = {}
    for receipt in receipts:
        join = reader.json(receipt["path"], receipt["sha256"])
        actual = {str(reader.abspath(reader.abspath(state_path).parent / name)) for name in join["results"]}
        expected = {str(reader.abspath(event["result_path"])) for event in events.values()
                    if event.get("status") == "completed"}
        require(actual == expected, "join result coverage differs")
        joins[("main", "banyan-fixed")] = {**join, "_resolved_result_paths": sorted(actual)}
    result = summarize_j(filtered_index, filtered_state, joins, mapping, reader.json,
                         engine=engine, layer=layer)
    row = next(row for row in result["revision_methods"] if row["method"] == "S")
    return row, [receipt["path"] for receipt in receipts]


def source_link(reader, path, label=None):
    relative = reader.abspath(path).relative_to(reader.root).as_posix()
    return f"[{label or relative}](../{relative})"


def render(reader, args, revisions, fuzz, sizes, mapping, locations, judgments, aq):
    lines = ["1번 결과: 문제 있음 — 자동 RQ-C 프로토콜 해시 불일치([별도 래퍼 검증 완료](n6_a_rqc_input_audit_2026-10-26.md)).",
             "", "# J가 걸러 낸 고친 버전의 S 후보", "",
             f"기준 시각: {datetime.now(timezone.utc).isoformat()}. 후보 단위는 공식 main의 seed별 발견 기록이며 값은 열지 않았다. "
             "중복 제거한 버그 수가 아니다. aq의 엄격·탐색 J 점수는 모두 대기로 유지한다.", "",
             "대상은 동결 RQ-C 매핑에 있는 revision_kind=fixed의 6개 리비전과 banyan-fixed, 총 7개다 "
             f"({source_link(reader, args.mapping)}, {source_link(reader, mapping['preparation_units'])}). "
             "leave_one_out은 fixed가 아니므로 제외했다.", "",
             "| 리비전 | 고친 버전 | 전체 제약 | S 후보 / 대응 가능 생성템플릿 후보 | 엄격 J: L1/배제/모름 | 탐색 v2.2: L1/배제/모름 | 탐색 v1: L1/배제/모름 | S만 거짓 경보 | S+J 거짓 경보: 엄격 / v2.2 / v1 |",
             "|---|---|---:|---|---|---|---|---:|---|"]
    evidence = []
    for number, revision in enumerate(revisions, 1):
        count = fuzz[revision]["S"]["candidates"]
        ref = f"[F{number:02d}](#f{number:02d})"
        cref = f"[C{number:02d}](#c{number:02d})"
        location = (("매핑 없음" if revision == "banyan-fixed" else "미확정")
                    if locations[revision] is None else f"{locations[revision]} [M](#m)")
        if revision.startswith("aq-"):
            strict = v22 = v1 = "대기"
            false_after = "대기 / 대기 / 대기"
        else:
            strict_row = judgments["strict"][0]
            strict = (f"—/—/—; 준비 실패 {strict_row['statuses'].get('preparation_failure', 0)} [J0](#j0)"
                      if strict_row['statuses'].get('completed', 0) == 0 else
                      f"{strict_row['L1_requests']}/{strict_row['excluded_requests']}/{strict_row['unknown_requests']} [J0](#j0)")
            def cell(engine, key):
                row = judgments[engine][0]
                return f"{row['L1_requests']}/{row['excluded_requests']}/{row['unknown_requests']} [{key}](#{key.lower()})"
            v22, v1 = cell("v2.2", "J2"), cell("v1", "J1")
            false_after = f"미판정 [J0](#j0) / {judgments['v2.2'][0]['L1_requests']} [J2](#j2) / {judgments['v1'][0]['L1_requests']} [J1](#j1)"
        lines.append(f"| {revision} | 예 [M](#m) | {sizes[revision]['constraints']:,} {cref} | {count} {ref} / {location} | {strict} | {v22} | {v1} | {count} {ref} | {false_after} |")
        evidence.extend([f'<a id="f{number:02d}"></a> **F{number:02d} — {revision} 후보**: ' +
                         "; ".join(source_link(reader, path) for path in fuzz[revision]["S"]["ledger_paths"]),
                         f'<a id="c{number:02d}"></a> **C{number:02d} — 제약 수**: ' +
                         "; ".join(source_link(reader, path) for path in sorted({r["stdout_path"] for r in sizes[revision]["seed_records"]}))])
    lines += ["", "`대응 가능 생성템플릿 후보`는 고정된 source·template·parameter가 버그 위치 인스턴스 또는 그 하위와 대응 가능한 후보 수다. "
              "한 템플릿이 여러 인스턴스에 쓰일 수 있으므로 실제 위반이 버그 위치에서 일어났다는 뜻은 아니다. "
              "실제 버그 위치별 후보 수는 미확정으로 남긴다. aq-035는 pragma 수정 후 wrapper 바이트가 다르고, aq-037의 capture는 가벼운 분석의 128 MiB 입력 한도를 넘어서 대응 수를 확정하지 않았다 "
              "([기존 위치 규칙](../scripts/n6_a_remeasure_aq_order_v2.py):146–200, 271–280; "
              f"[이번 수집기](../scripts/n6_j_filter_table_20261026.py):{potential_locations.__code__.co_firstlineno}).", "",
              "보수적 선택: ‘거짓 경보’는 요청대로 고친 대조군의 S 후보 수와 L1 요청 수를 비교하는 지표다. "
              "고친 버전에 별개 버그가 없다는 독립 증명은 아니므로 실제 거짓 양성률로 일반화하지 않는다. "
              "엄격 banyan은 준비 실패를 배제·모름이나 L1=0으로 바꾸지 않았다. "
              "탐색층의 구성 입력 결과를 엄격층에 합치지 않았다.", "",
              "## 원본 확인", "",
              "banyan-fixed의 탐색층은 두 엔진 각각 S 후보 24개와 완료 요청 24개가 대응하고, 각각 L1 0·배제 24·모름 0이다 "
              "([F07](#f07), [J2](#j2), [J1](#j1)). result SHA-256, request SHA-256, state/index 엔진 해시, "
              "join의 전체 결과 경로 집합을 다시 확인했다. 엄격층은 24개 전부 준비 실패다 ([J0](#j0)) "
              f"([영수증 확인 코드](../scripts/n6_j_filter_table_20261026.py):{banyan_j.__code__.co_firstlineno}; "
              "[판정 분류](../scripts/n6_a_size_cost_j_20261026.py):98–136).", "",
              "aq 상태는 존재하는 지정 파일 3개의 수정 시각 중 최신을 골랐다(동률이면 높은 버전). 선택: " +
              source_link(reader, aq["path"]) + f"; 형식 `{aq['schema']}`; SHA-256 `{aq['sha256']}`. "
              "상태 형식·경로만 확인하고 요청 점수나 결과 파일은 읽지 않았다. 재실행해도 현재 요청의 점수 비공개 원칙을 유지한다 "
              f"([선택 코드](../scripts/n6_j_filter_table_20261026.py):{select_aq_state.__code__.co_firstlineno}, "
              f"[형식 확인](../scripts/n6_j_filter_table_20261026.py):{aq_format.__code__.co_firstlineno}).", "",
              "## 근거", "", '<a id="m"></a> **M — 고친 버전·위치 매핑**: ' +
              source_link(reader, args.mapping) + "; " + source_link(reader, mapping["preparation_units"]) +
              "; " + source_link(reader, mapping["targets"]), ""]
    lines += [part for line in evidence for part in (line, "")]
    for key, engine, index, state in (("J0", "strict", args.strict_index, args.strict_state),
                                    ("J2", "v2.2", args.banyan_index_v22, args.banyan_state_v22),
                                    ("J1", "v1", args.banyan_index_v1, args.banyan_state_v1)):
        paths = [index, state] + judgments[engine][1]
        if engine != "strict":
            paths.append(args.banyan_joins)
        lines += [f'<a id="{key.lower()}"></a> **{key} — banyan-fixed**: ' +
                  "; ".join(source_link(reader, path) for path in paths), ""]
    lines += ["## 다시 실행", "", "새 실행기·엔진을 돌리지 않는 읽기 전용 집계 명령이다. 기존 입력 경로는 모두 인자로 바꿀 수 있다.", "", "```sh"]
    command = ["nice", "-n", "19", "python3", "-B", str(Path(__file__).resolve()), "--root", str(reader.root)]
    for key in DEFAULTS:
        command += ["--" + key.replace("_", "-"), str(getattr(args, key))]
    command += ["--output", str(reader.abspath(args.output)), "--max-seconds", str(args.max_seconds)]
    lines += [shlex.join(command), "```", "",
              "합성 검사(실제 상태·판정 입력을 열지 않음):", "", "```sh",
              shlex.join(["nice", "-n", "19", "python3", "-B", str(Path(__file__).resolve()), "--self-test"]),
              "```", "", "## SHA-256", "",
              "새 스크립트: `" + reader.digest(Path(__file__)) + "`. 보고서 자체의 SHA-256은 재실행 시 표준 출력에 기록한다 "
              "(자기 해시를 본문에 포함하면 해시가 다시 달라지므로 본문에서 제외).", "",
              "| 주요 입력 | SHA-256 |", "|---|---|"]
    keys = [args.mapping, mapping["preparation_units"], mapping["targets"], args.main_queue, args.main_state,
            args.pragma_queue, args.pragma_state, args.strict_index, args.strict_state,
            args.banyan_index_v22, args.banyan_state_v22, args.banyan_index_v1, args.banyan_state_v1,
            args.banyan_joins]
    for path in keys:
        lines.append(f"| {source_link(reader, path)} | `{reader.digest(path)}` |")
    manifest = [{"path": str(Path(path).relative_to(reader.root)), "sha256": item["sha256"]}
                for path, item in sorted(reader.sources.items()) if "/scripts/" not in path]
    lines += ["", f"읽은 입력 목록의 경로·해시 정렬 JSON SHA-256: `{hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}`.", "",
              "## 확인한 것", "",
              "- 고친 버전 범위, 세 seed의 S 후보, 기존 컴파일 stdout의 비선형+선형 제약 합을 원본에서 다시 셌다 ([M](#m), F01–F07, C01–C07).",
              "- banyan-fixed의 탐색층 배제와 엄격층 준비 실패를 해시·경로 연결까지 확인했다 ([J0](#j0), [J2](#j2), [J1](#j1)).",
              "- aq 상태 파일은 최신 수정 시각으로 자동 선택한다. aq 점수, 후보 값, 실행 중인 프로세스는 확인·변경하지 않았다.", "",
              "## 추정한 것", "",
              "- 고친 대조군의 후보를 거짓 경보로 보는 것은 이 표의 비교 정의이며 독립적인 무버그 증명은 아니다.",
              "- 대응 가능한 생성템플릿 수로 실제 위반 위치를 확정하지 않았다. aq 판정 결과는 모두 대기다.", ""]
    return "\n".join(lines)



def self_test():
    """Synthetic paths only; never read live states or judgments."""
    import tempfile
    tests = 0
    with tempfile.TemporaryDirectory(prefix="n6-j-filter-check-") as directory:
        root = Path(directory)
        folder = root / AQ
        folder.mkdir(parents=True)
        reader = Reader(root)
        for index, name in enumerate(STATE_NAMES):
            path = folder / name
            path.write_text(json.dumps({"schema": "n6-a-remeasure-aq-execute-v" + str(index + 1), "engines": {}}))
            os.utime(path, ns=(100 + index, 100 + index))
        require(select_aq_state(reader, AQ).name == "state-v3_1.json", "newest v3_1 selection failed")
        tests += 1
        (folder / "state-v3_1.json").unlink()  # remaining checks keep the three earlier generations
        require(select_aq_state(reader, AQ).name == "state-v3.json", "newest selection failed")
        tests += 1
        os.utime(folder / "state-v2.json", ns=(200, 200))
        require(select_aq_state(reader, AQ).name == "state-v2.json", "mtime selection failed")
        tests += 1
        os.utime(folder / "state-v3.json", ns=(200, 200))
        require(select_aq_state(reader, AQ).name == "state-v3.json", "tie generation selection failed")
        tests += 1
        require(select_aq_state(reader, AQ, str(folder / "state.json")).name == "state.json", "explicit selection failed")
        tests += 1
        snapshot = aq_format(reader, AQ, "auto")
        require(set(snapshot) == {"path", "sha256", "schema", "selection"}, "aq score leaked")
        tests += 1
        for forbidden in (AQ + "/rqc/result.json", AQ + "/requests/1/result.json", "runs/n6-b6h/x.json", "runs/h1-test/x.json", "runs/a/candidates/x.json"):
            try:
                reader.abspath(forbidden)
            except ValueError:
                tests += 1
            else:
                raise AssertionError("forbidden read accepted")
        (folder / "state-v3.json").unlink()
        (folder / "state-v3.json").symlink_to(folder / "state-v2.json")
        try:
            select_aq_state(reader, AQ)
        except ValueError:
            tests += 1
        else:
            raise AssertionError("state symlink accepted")
        file = root / "metadata.json"
        file.write_text("{}")
        try:
            reader.json(file, "0" * 64)
        except ValueError:
            tests += 1
        else:
            raise AssertionError("wrong SHA accepted")
    print(json.dumps({"status": "passed", "synthetic_checks": tests, "live_inputs_read": False}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    for key, value in DEFAULTS.items():
        parser.add_argument("--" + key.replace("_", "-"), default=value)
    parser.add_argument("--output", default="docs/n6_j_filter_table_2026-10-26.md")
    parser.add_argument("--max-seconds", type=int, default=180)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        reader = Reader(args.root, args.max_seconds)
        if args.self_test:
            return self_test()
        mapping = reader.json(args.mapping, "8ad5d43b51d5ceaab0d95dd83a229f45fdc2a2020485a21ccb3b1a43fb4aab85")
        revisions = fixed_revisions(reader, mapping)
        fuzz = {row["revision"]: row for row in collect_fuzz(args.main_queue, args.main_state,
                args.pragma_queue, args.pragma_state, reader)}
        sizes = collect_sizes(args.main_queue, args.size_reuse, reader, pragma_queue_path=args.pragma_queue)
        mapped = {row["revision_id"]: row for row in mapping["revisions"]}
        locations = {revision: potential_locations(reader, mapped.get(revision), fuzz[revision])
                     for revision in revisions}
        aq = aq_format(reader, args.aq_state_dir, args.aq_state)
        aggregate = reader.json(args.banyan_joins)
        judgments = {"strict": banyan_j(reader, args.strict_index, args.strict_state, mapping, "v1", "strict")}
        for engine, suffix in (("v2.2", "v22"), ("v1", "v1")):
            judgments[engine] = banyan_j(reader, getattr(args, "banyan_index_" + suffix),
                getattr(args, "banyan_state_" + suffix), mapping, engine, "exploratory", aggregate)
            row = judgments[engine][0]
            require(row["requests"] == fuzz["banyan-fixed"]["S"]["candidates"] and
                    row["statuses"] == {"completed": row["requests"]}, "banyan fixed coverage differs")
        unresolved = Path(args.output) if Path(args.output).is_absolute() else reader.root / args.output
        require(not unresolved.is_symlink(), "report symlink denied")
        output = reader.abspath(args.output)
        require(output.parent == reader.root / "docs" and not output.is_symlink(), "output must be docs")
        content = render(reader, args, revisions, fuzz, sizes, mapping, locations, judgments, aq).encode()
        require(len(content) < 1024**2, "report exceeds small output limit")
        reader.guard()
        with output.open("wb") as stream:
            stream.write(content)
        print(json.dumps({"status": "complete", "output": str(output), "report_sha256": hashlib.sha256(content).hexdigest(),
            "script_sha256": reader.digest(Path(__file__)), "bytes": len(content), "revisions": len(revisions),
            "aq_state_path": aq["path"], "aq_scores": "withheld", "seconds": round(time.monotonic() - reader.started, 3)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "stopped", "reason": str(error), "judging_executed": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
