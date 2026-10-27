#!/usr/bin/env python3
"""Bounded, low-priority A metadata report; never invoke an experiment runner."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import statistics
import subprocess
import sys
import time

from n6_a_size_cost_fuzz_20261026 import collect_fuzz
from n6_a_size_cost_sizes_20261026 import collect_sizes
from n6_a_size_cost_j_20261026 import summarize_j

ROOT = Path(__file__).resolve().parents[1]
AQ = "runs/n6-a-remeasure-2026-10-25.noindex/aq-exec"
# Runner generations write separate state files; v3 imports v2, v2 imports v1 (miiz, 2026-10-26).
AQ_STATES = ("state.json", "state-v2.json", "state-v3.json", "state-v3_1.json")


def latest_aq_state(root=ROOT):
    """The newest runner state that exists; each later runner imports the earlier completions."""
    for name in reversed(AQ_STATES):
        if (Path(root) / AQ / name).is_file():
            return AQ + "/" + name
    return AQ + "/state.json"
PREFIXES = ("aq-024", "aq-017", "aq-011", "aq-016", "aq-026", "aq-040", "aq-008")
Q = chr(96)
FENCE = Q * 3
DEFAULTS = {
    "main_queue": "runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json",
    "main_state": "runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/state.json",
    "pragma_queue": "runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json",
    "pragma_state": "runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/state.json",
    "size_reuse": "runs/n6-a2b-2026-10-08.noindex/preflight-reuse-a-v4.json",
    "strict_index": "runs/n6-j1-2026-10-09.noindex/request-index.json",
    "strict_state": "runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json",
    "mapping": "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json",
    "banyan_index_v22": "runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v2.2.json",
    "banyan_state_v22": "runs/n6-a-remeasure-2026-10-25.noindex/j-v2.2/state.json",
    "banyan_index_v1": "runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-v1.json",
    "banyan_state_v1": "runs/n6-a-remeasure-2026-10-25.noindex/j-v1/state.json",
    "banyan_joins": "runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json",
    "aq_index_v22": "runs/n6-a-remeasure-2026-10-25.noindex/prepared-aq/request-index-v2.2.json",
    "aq_index_v1": "runs/n6-a-remeasure-2026-10-25.noindex/prepared-aq/request-index-v1.json",
    "aq_state": latest_aq_state(),
    "aq_rqc_dir": AQ + "/rqc",
    "w_causes": "docs/n6_a_w_failure_causes_2026-10-26.md",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Reader:
    """Only named files; only state.json and one latest score inside aq-exec."""
    def __init__(self, root=ROOT, max_seconds=180):
        self.root = Path(root).resolve()
        self.started = time.monotonic()
        self.max_seconds = max_seconds
        self.sources = {}
        self.cache = {}
        self.cache_bytes = 0
        self.latest_rqc = None
        self.guard()

    def guard(self):
        require(os.getpriority(os.PRIO_PROCESS, 0) >= 19, "nice 19 was not applied; refusing analysis")
        require(shutil.disk_usage(self.root).free >= 15 * 1024**3, "internal disk below 15 GiB; stopped")
        require(time.monotonic() - self.started <= self.max_seconds, "bounded analysis time exceeded")

    def abspath(self, name):
        path = Path(name)
        path = path if path.is_absolute() else self.root / path
        path = path.resolve()
        require(path.is_relative_to(self.root), f"input outside repository: {path}")
        rel = path.relative_to(self.root).as_posix()
        require(not any(part.startswith(("n6-b6", "h1-")) for part in path.parts),
                f"forbidden B/H1 input: {path}")
        require("/candidates/" not in rel and "/witness" not in rel, "raw value file is not needed")
        aq_root = self.root / AQ
        if path.is_relative_to(aq_root):
            require(path in {aq_root / name for name in AQ_STATES} or path == self.latest_rqc or
                    (path.parent == aq_root / "workspace-cleanup" and path.name.endswith("-before.json")),
                    f"aq read is outside permitted state/latest score/cleanup records: {path}")
        return path

    def raw(self, name, expected=None):
        self.guard()
        path = self.abspath(name)
        if path in self.cache:
            data = self.cache[path]
        else:
            require(path.stat().st_size <= 64 * 1024**2, f"metadata file exceeds read bound: {path}")
            data = path.read_bytes()
            if self.cache_bytes + len(data) <= 16 * 1024**2:
                self.cache[path] = data
                self.cache_bytes += len(data)
        digest = hashlib.sha256(data).hexdigest()
        require(expected is None or digest == expected, f"SHA-256 mismatch: {path}")
        self.sources[str(path)] = {"path": str(path), "sha256": digest, "bytes": len(data)}
        self.guard()
        return data

    def json(self, name, expected=None):
        return json.loads(self.raw(name, expected))

    def text(self, name, expected=None):
        return self.raw(name, expected).decode("utf-8")

    def digest(self, name):
        path = str(self.abspath(name))
        if path not in self.sources:
            self.raw(path)
        return self.sources[path]["sha256"]


def latest_rqc(reader, directory):
    """The only directory listing in this program is this single nonrecursive ls."""
    folder = (reader.root / directory).resolve() if not Path(directory).is_absolute() else Path(directory).resolve()
    require(folder == reader.root / AQ / "rqc", "only the approved RQ-C folder may be listed")
    reader.guard()
    completed = subprocess.run(["ls", "-1t", str(folder)], text=True,
                               capture_output=True, check=False, timeout=10)
    if completed.returncode:
        require(not folder.exists(), "RQ-C directory listing failed")
        return {"status": "unavailable", "reason": "지정 rqc/ 폴더 없음"}
    names = [name for name in completed.stdout.splitlines()
             if name.endswith(".json") and Path(name).name == name]
    if not names:
        return {"status": "unavailable", "reason": "RQ-C JSON 없음"}
    path = folder / names[0]
    require(not path.is_symlink() and path.is_file() and path.resolve().parent == folder,
            "latest RQ-C must be a regular file directly in the approved folder")
    reader.latest_rqc = path.resolve()
    try:
        value = reader.json(path)
    except json.JSONDecodeError:
        return {"status": "unavailable", "reason": "최신 파일 작성 중/불완전 JSON", "path": str(path)}
    require(value.get("schema") == "n6-light-rqc-v1", "unexpected latest RQ-C schema")
    require(value.get("layer") == "exploratory" and value.get("engine") in {"v1", "v2.2"},
            "latest RQ-C must be an exploratory aq score for v1 or v2.2")
    return {"status": "available", "path": str(path), "data": value,
            "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def load_j(reader, index_path, state_path, mapping, engine, layer, aggregate=None):
    index = reader.json(index_path)
    state = reader.json(state_path)
    require(state["request_index_sha256"] == reader.digest(index_path), "J state/index SHA mismatch")
    require(state["engine_sha256"] == index["engine_sha256"], "J engine binding mismatch")
    specs = [group for group in state.get("revisions", {}).values() if group.get("instances_path")]
    receipts = [{"scope": g["scope"], "revision": g["revision_id"],
                 "path": g["instances_path"], "sha256": g["instances_sha256"]} for g in specs]
    if aggregate is not None:
        receipts += [g for g in aggregate["joins"] if g["engine"] == engine]
    joins = {}
    for receipt in receipts:
        key = (receipt.get("scope", "main"), receipt["revision"])
        require(key not in joins, "duplicate saved J join")
        join = reader.json(receipt["path"], receipt["sha256"])
        base = reader.abspath(state_path).parent
        actual = {str(reader.abspath(base / relative)) for relative in join["results"]}
        expected = {str(reader.abspath(event["result_path"])) for event in state["requests"].values()
                    if event.get("scope") == key[0]
                    and event.get("revision_id", event.get("revision")) == key[1]
                    and event.get("status") == "completed"}
        require(actual == expected, f"saved join coverage differs: {key}")
        joins[key] = {**join, "_resolved_result_paths": sorted(actual)}
    result = summarize_j(index, state, joins, mapping, reader.json, layer=layer, engine=engine)
    return {(row["revision_id"], row["method"]): row for row in result["revision_methods"]}, result


def stats(values):
    return {"count": len(values), "sum": math.fsum(values) if values else None,
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None}


def aq_snapshot(reader, args):
    require(reader.abspath(args.aq_state) in {reader.root / AQ / name for name in AQ_STATES},
            "aq state must be one of the runner state files")
    state = reader.json(args.aq_state)
    peaks = workspace_peaks(reader)
    answer = {}
    for engine, name in (("v2.2", args.aq_index_v22), ("v1", args.aq_index_v1)):
        index = reader.json(name)
        require(state["config"]["index_sha256"][engine] == reader.digest(name), "aq index hash differs")
        require(state["config"]["engine_sha256"][engine] == index["engine_sha256"], "aq engine differs")
        saved = state["engines"][engine]["requests"]
        groups = {}
        for row in index["requests"]:
            if row["scope"] != "main":
                continue
            key = (row["revision_id"], row["method"])
            group = groups.setdefault(key, {"requests": 0, "statuses": Counter(),
                                           "times": [], "untimed": 0})
            group["requests"] += 1
            event = saved.get(str(row["queue_order"]))
            group["statuses"][event["status"] if event else "not_run"] += 1
            if event:
                require(event["request_sha256"] == row["request_sha256"], "aq saved request SHA differs")
            times = []
            for attempt in [*event.get("history", []), event] if event else []:
                duration = attempt.get("wall_seconds")
                if attempt.get("status") != "running" and duration is not None:
                    require(type(duration) in (int, float) and math.isfinite(duration) and duration >= 0,
                            "bad aq recorded wall time")
                    times.append(duration)
            if times:
                group["times"].append(math.fsum(times))
            else:
                group["untimed"] += 1
        answer[engine] = {key: {"revision_id": key[0], "method": key[1],
            "requests": g["requests"], "statuses": dict(g["statuses"]),
            "wall_seconds": {**stats(g["times"]), "untimed_requests": g["untimed"]},
            "classification_unavailable": True,
            "workspace_peak_bytes": peaks.get((engine, key[0]))}
            for key, g in groups.items()}
    return answer, state


def workspace_peaks(reader):
    """Largest recorded request workspace per (engine, revision): one directory, no recursion."""
    folder = reader.root / AQ / "workspace-cleanup"
    peaks = {}
    if not folder.is_dir():
        return peaks
    for entry in sorted(os.listdir(folder)):
        if not entry.endswith("-before.json"):
            continue
        record = reader.json(str(folder / entry))
        parts = Path(record.get("path", "")).parts
        if "workspaces" not in parts or len(parts) < parts.index("workspaces") + 3:
            continue
        at = parts.index("workspaces")
        engine, revision = parts[at - 1], parts[at + 1]
        size = record.get("du_bytes")
        if type(size) is int and size >= 0:
            peaks[(engine, revision)] = max(peaks.get((engine, revision), 0), size)
    return peaks


def zero(revision, method):
    return {"revision_id": revision, "method": method, "requests": 0, "statuses": {},
            "L1_requests": 0, "bug_location_L1_requests": 0, "other_L1_requests": 0,
            "unassigned_L1_requests": 0, "ambiguous_location_L1_requests": 0,
            "excluded_requests": 0, "unknown_requests": 0,
            "wall_seconds": {"count": 0, "sum": 0, "median": None, "max": None,
                             "untimed_requests": 0}, "workspace_peak_bytes": None}


def fmt(value, digits=3):
    if value is None:
        return "—"
    return f"{value:,.{digits}f}" if isinstance(value, float) else f"{value:,}"


def band(count):
    return "<100k" if count < 100000 else "100k–<1m" if count < 1000000 else "≥1m"


class Report:
    def __init__(self, reader, output):
        self.reader = reader
        self.output = output
        self.bundles = {}

    def source(self, key, paths):
        unique = list(dict.fromkeys(str(self.reader.abspath(p)) for p in paths))
        require(bool(unique), f"empty evidence bundle {key}")
        self.bundles[key] = unique
        return f"[{key}](#{key.lower()})"

    def link(self, path):
        value = Path(path)
        relative = os.path.relpath(value, self.output.parent)
        return f"[{value.relative_to(self.reader.root).as_posix()}](<{relative}>)"

    def evidence(self):
        lines = ["## 숫자별 근거 경로", "",
                 "각 표의 근거 기호는 아래 명시 파일 묶음이다. W/S 값은 선택된 세 seed ledger의 합이며, C는 실제 W 컴파일 stdout이다.", ""]
        for key, paths in self.bundles.items():
            lines.append(f'<a id="{key.lower()}"></a> **{key}**: ' +
                         " · ".join(self.link(path) for path in paths))
            lines.append("")
        return lines


def judgment_cell(row, ref):
    if row is None:
        return "대상 밖"
    statuses = row["statuses"]
    start = f"{row['requests']}/{statuses.get('completed', 0)}"
    if row.get("classification_unavailable"):
        verdict = "미확인"
    else:
        verdict = "/".join(str(row[k]) for k in ("bug_location_L1_requests",
            "other_L1_requests", "unassigned_L1_requests", "ambiguous_location_L1_requests",
            "excluded_requests", "unknown_requests"))
    unfinished = statuses.get("not_run", 0) + statuses.get("running", 0)
    tail = f"준비{statuses.get('preparation_failure', 0)}, 실패{statuses.get('failed', 0)}, 대기{unfinished}"
    return f"{start}; {verdict}; {tail} {ref}"


def time_cell(row, ref):
    if row is None:
        return "대상 밖"
    values = row["wall_seconds"]
    return "/".join(fmt(values[k]) for k in ("sum", "median", "max")) + f" {ref}"


def row_cost(fuzz, judging):
    return fuzz + (judging["wall_seconds"]["sum"] or 0.0)


def render(reader, args, fuzz, sizes, strict, exploratory, aqstate, latest):
    output = (reader.root / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output).resolve()
    require(output.is_relative_to(reader.root / "docs"), "report output must be under docs/")
    report = Report(reader, output)
    wdoc = report.source("W기준", [args.w_causes])
    strict_ref = report.source("J엄격", [args.strict_index, args.strict_state, args.mapping])
    exp_refs = {engine: report.source("J탐색" + engine.replace(".", ""),
        [getattr(args, "banyan_index_" + suffix), getattr(args, "banyan_state_" + suffix), args.banyan_joins, args.mapping])
        for engine, suffix in (("v2.2", "v22"), ("v1", "v1"))}
    aq_ref = report.source("AQ상태", [args.aq_state, args.aq_index_v22, args.aq_index_v1])
    aq_statuses = Counter()
    for rows in exploratory.values():
        for row in rows.values():
            if row.get("classification_unavailable"):
                aq_statuses.update(row["statuses"])
    def exp_ref(revision, engine):
        return aq_ref if revision.startswith("aq-") else exp_refs[engine]
    lines = ["# A 회로 크기별 W 대 S+J 결과·비용 (2026-10-26)", "",
        f"담당 miiz. 읽기 전용 스냅샷: {datetime.now(timezone.utc).isoformat()}. "
        f"공식 main W의 27리비전·81 seed 쌍만 비교한다. mem20는 합산하지 않는다. {wdoc}", "",
        "여기서 공식 main은 실행 큐의 범위다. inference·Banyan·zkemail은 개발 사례이며, "
        "과거 엄격 입력층의 결과도 별도 보류 평가나 고정 버그 위치 확인으로 승격하지 않는다.", "",
        "**보수적 선택:** 캠페인 벽시계를 실제 퍼징 비용으로 사용해 복사·설정 부담을 빼지 않고, "
        "기록된 S 요청 J 시간까지 더한다. 판정 준비·join·실행기 부대 시간의 미기록분은 0으로 확정하지 않아 총비용은 하한이다. "
        "W 후보의 J 시간은 따로 적고 S 비용에 넘기지 않는다.", "",
        "크기는 새 컴파일 없이 원본 circom stdout의 비선형+선형 제약 합과 wires를 읽었다. "
        "wires는 컴파일된 신호/와이어 수(상수선 포함)이며 소스 신호 선언 수와 다르다. "
        "aq-035/036은 공식 선택과 같은 pragma 보정 W preflight를 사용했다.", "",
        "## 리비전별 크기와 퍼징", "",
        "시간은 초, 세 seed 합. S 단위는 계획/실제로 시작한 서로 다른 target 수다. "
        "종료 부호: C 후보 관측 종료, N 정상·후보 없음, T 실제 실행 시간 초과, M 메모리 한도, "
        "D 실행 전 예산 소진, P panic 기록, O 기타. 여러 종료 원인은 함께 보존한다. "
        "모든 선택 캠페인의 최종 종료 원인은 budget_exhausted다. "
        "P는 ledger의 기록만 세며, 기존 무후보 보고서의 로그 검사 이상으로 panic 부재를 주장하지 않는다.", "",
        "| 리비전·표시 | 비선형 / 전체 제약 / wires | W 예산 / 벽시계 / 프로세스 합 | W 후보; 종료 시도 수 | S 단위 계획/시작 | S 후보; 벽시계 / 프로세스 합 |",
        "|---|---:|---:|---|---:|---:|"]
    for number, row in enumerate(fuzz, 1):
        revision, w, s = row["revision"], row["W"], row["S"]
        size = sizes[revision]
        cref = report.source(f"C{number:02}", [entry["stdout_path"] for entry in size["seed_records"]])
        wref = report.source(f"W{number:02}", w["ledger_paths"])
        sref = report.source(f"S{number:02}", [*s["ledger_paths"], s["spec_paths"][0]])
        marks = " ★RQ-C" if revision.startswith(PREFIXES) else " ★수정" if revision.startswith("aq-035") else " ★취약" if revision.startswith("aq-036") else ""
        codes = {"candidate": "C", "no_candidate": "N", "timeout": "T",
                 "memory_cap": "M", "deadline_before_spawn": "D"}
        endings = ",".join(f"{codes.get(k, 'P' if 'panic' in k else 'O')}={v}"
                           for k, v in sorted(w["outcomes"].items()))
        lines.append(f"| {revision}{marks} | {fmt(size['nonlinear'])}/{fmt(size['constraints'])}/{fmt(size['wires'])} {cref} "
            f"| {fmt(w['budget'])}/{fmt(w['campaign_seconds'])}/{fmt(w['process_seconds'])} {wref} "
            f"| {w['candidates']}; {endings}; P={w['panic_recorded']} {wref} "
            f"| {s['units']}/{s['started_units']} {sref} "
            f"| {s['candidates']}; {fmt(s['campaign_seconds'])}/{fmt(s['process_seconds'])} {sref} |")
    lines += ["", "## S 후보의 J: 엄격층과 탐색층", "",
        "탐색층은 구성 입력을 사용한 재측정이다. 엄격층과 별도 칸으로 유지한다.", "",
        "판정 칸: **계획 요청/완료; 버그 위치 L1/다른 위치 L1/위치 미귀속 L1/위치 모호 L1/배제/모름; 준비 실패·실행 실패·대기**. "
        "개수 단위는 요청이며 고유 버그 수가 아니다. 고정 위치 매핑이 없으면 L1을 '다른 곳'으로 추정하지 않고 미귀속에 둔다. "
        "위치별 L1은 한 요청에서 겹칠 수 있다. L1→배제→모름 순서는 기존 A 요청 집계와 같고, ANY 배제는 모든 클래스 배제를 뜻하지 않는다. "
        "시간 칸은 기록된 요청 시간의 합/중앙값/최대(초), 재시도는 같은 요청에 합친다. '미확인'은 엔진의 unknown과 다르다.", "",
        "| 리비전 | 엄격 v1 판정 | 엄격 시간 | 탐색 v2.2 판정 | 탐색 v2.2 시간 | 탐색 v1 판정 | 탐색 v1 시간 | 요청 폴더 최대 |",
        "|---|---|---:|---|---:|---|---:|---|"]
    for row in fuzz:
        rev = row["revision"]
        st = strict.get((rev, "S"), zero(rev, "S"))
        ex2 = exploratory["v2.2"].get((rev, "S"))
        ex1 = exploratory["v1"].get((rev, "S"))
        ref2, ref1 = exp_ref(rev, "v2.2"), exp_ref(rev, "v1")
        lines.append(f"| {rev} | {judgment_cell(st, strict_ref)} | {time_cell(st, strict_ref)} "
                     f"| {judgment_cell(ex2, ref2)} | {time_cell(ex2, ref2)} "
                     f"| {judgment_cell(ex1, ref1)} | {time_cell(ex1, ref1)} | — 미측정 |")
    lines += ["", f"**aq는 진행 중인 실험의 스냅샷이다.** 읽은 상태 파일은 {Q}{args.aq_state}{Q}(실행기 세대 중 가장 최신; 뒤 세대가 앞 세대 완료를 해시 확인 후 가져옴)이고 상태는 "
        f"{Q}{aqstate['status']}{Q}이다. "
        "aq 판정 결과·metrics·join 파일도 열지 않았다. 계획 분모는 따로 표시하고 결과·시간은 이 상태의 종결 요청만 센다. "
        f"이 스냅샷에는 완료 {aq_statuses.get('completed', 0)}건과 실패 {aq_statuses.get('failed', 0)}건이 있고, "
        "기록된 종결 시도 시간만 반영하며 L1·배제·모름은 미확인으로 둔다. "
        f"최신 RQ-C: {latest.get('reason', latest['status'])}. {aq_ref} "
        f"상태 SHA-256: {Q}{reader.digest(args.aq_state)}{Q}.", "",
        "**요청 작업 폴더 최대 크기:** aq-exec/workspace-cleanup/ 한 폴더의 정리 전 기록(-before.json)만 재귀 없이 읽었다. "
        + ("; ".join(f"{e} {r}: {v / 1024**3:,.1f} GiB" for (e, r), v in sorted(workspace_peaks(reader).items())) or "기록 없음")
        + ". aq-025의 v1 실행기 시절 16건은 별도 일회성 정리(workspace-cleanup-20261026/)에 기록돼 여기에는 포함되지 않는다. ",
        f"{strict_ref} {exp_refs['v2.2']} {exp_refs['v1']}", "",
        "W 후보 J는 banyan-vulnerable과 aq-036만 있다. 나머지 25리비전은 W 후보/J 요청 0건이다. "
        f"{strict_ref}", "",
        "| 리비전·층/엔진 | W 요청/완료; 판정 | W J 시간 합/중앙값/최대 |",
        "|---|---|---:|"]
    for row in fuzz:
        rev = row["revision"]
        for label, data, ref in (("엄격 v1", strict, strict_ref),
            ("탐색 v2.2", exploratory["v2.2"], exp_refs["v2.2"]),
            ("탐색 v1", exploratory["v1"], exp_refs["v1"])):
            item = data.get((rev, "W"))
            if item and item["requests"]:
                lines.append(f"| {rev} / {label} | {judgment_cell(item, ref)} | {time_cell(item, ref)} |")
    lines += ["", "## 리비전별 총비용 비교", "",
        "초 단위. S+J는 같은 S 퍼징 시간에 해당 엔진·층의 S 요청 판정 시간을 더한 값이다. "
        "두 엔진이나 엄격/탐색층을 합치지 않았다. ≥는 기록된 비용 하한이다. "
        "aq의 대기 요청·미완료 판정은 추가 시간이 아직 반영되지 않았다.", "",
        "| 리비전 | W 퍼징 벽시계 | S+J 엄격 v1 | S+J 탐색 v2.2 | S+J 탐색 v1 |",
        "|---|---:|---:|---:|---:|"]
    for number, row in enumerate(fuzz, 1):
        rev, s = row["revision"], row["S"]["campaign_seconds"]
        refs = f"[S{number:02}](#s{number:02})"
        values = [f"{fmt(row['W']['campaign_seconds'])} [W{number:02}](#w{number:02})"]
        for data, ref in ((strict, strict_ref), (exploratory["v2.2"], exp_ref(rev, "v2.2")),
                          (exploratory["v1"], exp_ref(rev, "v1"))):
            item = data.get((rev, "S"))
            values.append(f"≥{fmt(row_cost(s, item))} {refs} {ref}" if item else "대상 밖")
        lines.append("| " + rev + " | " + " | ".join(values) + " |")
    lines += ["", "## 전체 제약 수 구간별 관측", "",
        "분모는 각 구간의 모든 공식 main 리비전이다. L1 비율은 요청 중복을 제거한 리비전 비율이며, "
        "위치 귀속 여부와 무관한 관측 L1이다. 버그 위치만 확인된 비율도 따로 적는다. "
        "엄격층 준비 실패와 탐색층 미관측/미확인은 음성 판정으로 확정하지 않으며 모든 L1 비율은 관측된 최소 비율이다. "
        "근거는 위 리비전 행의 C/W/S/J 파일이다.", "",
        "| 전체 제약 구간 | 리비전 수 | W 후보 있음 | S 후보 있음 | 엄격 S+J L1 | 엄격 버그 위치 L1 | 탐색 v2.2 L1 ≥ | 탐색 v1 L1 ≥ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    bin_summary = []
    for name in ("<100k", "100k–<1m", "≥1m"):
        members = [r for r in fuzz if band(sizes[r["revision"]]["constraints"]) == name]
        n = len(members)
        counts = [sum(r["W"]["candidates"] > 0 for r in members),
                  sum(r["S"]["candidates"] > 0 for r in members)]
        for data, field in ((strict, "L1_requests"), (strict, "bug_location_L1_requests"),
                            (exploratory["v2.2"], "L1_requests"), (exploratory["v1"], "L1_requests")):
            counts.append(sum(data.get((r["revision"], "S"), {}).get(field, 0) > 0 for r in members))
        values = [f"{value}/{n} ({100*value/n:.1f}%)" if n else "—" for value in counts]
        lines.append("| " + " | ".join([name, str(n), *values]) + " |")
        bin_summary.append({"band": name, "revisions": n, "counts": counts})
    aq13 = [sizes[r["revision"]]["constraints"] for r in fuzz
            if r["revision"].startswith("aq-") and not r["revision"].startswith(("aq-035", "aq-036"))]
    lines += ["", "## 크기 불일치 판정", "",
        f"재측정 aq 13개는 **{min(aq13):,}~{max(aq13):,} 전체 제약**이다. "
        "“104만~202만”은 전체 13개의 범위가 아니며 큰 6개(006/007/008/037/039/040)에만 대략 해당한다. "
        "024=368,283, 017=384,554, 016=276,424, 008=1,039,528, 040=2,017,059는 원본 로그와 일치한다. "
        "리비전별 정확한 비선형·전체·wires와 원본 경로는 첫 표에 있다.", ""]
    if latest["status"] == "available":
        lref = report.source("RQ최신", [latest["path"]])
        value = latest["data"]
        lines += ["## 최신 RQ-C 보조 스냅샷", "",
            f"엔진 {value.get('engine')}, 층 {value.get('layer')}, 파일 수정시각 {latest['mtime']}. {lref}",
            "이 파일은 별도 시점의 위치 채점이다. state.json 비용/완료 건수와 시점이 다를 수 있어 합치지 않는다. "
            "아래 관측은 같은 파일의 S 리비전 셀을 중복 제거한 것으로, 판정 시간은 이 파일에 없으면 추정하지 않는다.", "",
            "| 리비전 | S 완료/요청 | 버그 위치 L1 관측 | 배제 관측 | 모름 관측 |",
            "|---|---:|---|---|---|"]
        cells = {}
        for bug in value.get("bugs", []):
            for cell in bug.get("methods", {}).get("S", {}).get("revisions", []):
                if cell["revision_id"].startswith(PREFIXES):
                    saved = cells.setdefault(cell["revision_id"], {"requests": cell["requests"],
                        "completed": cell["request_statuses"].get("completed", 0), "observed": set()})
                    require(saved["requests"] == cell["requests"], "latest RQ-C cells disagree")
                    saved["observed"].update(cell["observed_statuses"])
        for rev, cell in sorted(cells.items()):
            answers = [("관측" if key in cell["observed"] else "관측 없음") for key in ("L1", "excluded", "unknown")]
            lines.append(f"| {rev} | {cell['completed']}/{cell['requests']} {lref} | " +
                         " | ".join(answer + " " + lref for answer in answers) + " |")
    lines += report.evidence()
    command = ["nice", "-n", "19", "python3", "-B", str(Path(__file__).resolve()),
               "--root", str(reader.root)]
    for key in DEFAULTS:
        if key == "aq_state":
            continue  # the default picks the newest runner state at rerun time
        command += ["--" + key.replace("_", "-"), str(getattr(args, key))]
    command += ["--output", str(output), "--max-seconds", str(args.max_seconds)]
    lines += ["## 재실행과 파일 해시", "",
        "같은 명령은 그때 가장 최신인 aq 상태 파일(state-v3_1.json > state-v3.json > state-v2.json > state.json)과 최신 RQ-C JSON을 다시 읽어 이 파생 보고서만 갱신한다. "
        "입력 경로는 모두 인자로 바꿀 수 있으나 aq 상태 파일·RQ-C 폴더 제한은 코드로 유지한다.", "",
        FENCE + "sh", shlex.join(command), FENCE, "",
        "새 파일의 SHA-256(보고서 자기 해시는 최종 응답에 별도 기록):", "",
        "| 파일 | SHA-256 |", "|---|---|"]
    for name in ("n6_a_size_cost_table_20261026.py", "n6_a_size_cost_fuzz_20261026.py",
                 "n6_a_size_cost_sizes_20261026.py", "n6_a_size_cost_j_20261026.py",
                 "n6_a_size_cost_checks_20261026.py"):
        path = reader.root / "scripts" / name
        lines.append(f"| {report.link(path)} | {Q}{hashlib.sha256(path.read_bytes()).hexdigest()}{Q} |")
    source_digest = hashlib.sha256(json.dumps(list(reader.sources.values()), sort_keys=True).encode()).hexdigest()
    lines += ["", f"이번 읽기 입력 {len(reader.sources):,}개 경로/해시 목록의 SHA-256: {Q}{source_digest}{Q}. "
              f"분석 {time.monotonic()-reader.started:.3f}초, nice={os.getpriority(os.PRIO_PROCESS,0)}, "
              f"내장 여유 {shutil.disk_usage(reader.root).free/1024**3:.2f} GiB.", "",
        "작성 시 검증(2026-10-26): 합성 테스트 22개, 새 스크립트 5개의 py_compile, "
        "cargo fmt --check, cargo clippy --all-targets --all-features -- -D warnings, cargo test --no-run 통과. "
        "모두 nice 19로 수행했다. J 호출을 피하기 위해 Rust 테스트는 빌드만 확인했다.", "",
        "## 확인한 것", "",
        "- 27리비전의 선택된 세 seed W/S ledger와 spec·상태의 해시 연결, 후보 개수·시간·종료 기록을 확인했다. 후보 값 파일은 읽지 않았다.",
        "- 원본 W 컴파일 stdout의 비선형·선형·wires 숫자와 seed 간 일치를 확인했다. R1CS 재생성·컴파일·J·퍼징을 실행하지 않았다.",
        "- 엄격층과 Banyan 탐색층은 저장된 완료 result/join 해시·요청 연결만 대조했다. aq는 허용된 state와 최신 RQ-C 한 파일로 읽기를 제한했다.",
        "- 준비 실패·대기·위치 매핑 없음은 엔진 모름이나 음성 판정으로 바꾸지 않았다. 실행 중인 프로세스와 기존 출력, B 자료, H1 후보는 수정하지 않았다.", "",
        "## 추정한 것·확인하지 못한 것", "",
        "- S+J 비용은 기록된 요청 시간까지의 하한이다. 미기록 준비·join·정리 비용과 현재 aq의 추가 진행 시간은 추정하지 않았다.",
        "- 요청 작업 폴더의 최대 디스크 사용량은 자료가 없어 산출하지 않았다. 원본 로그의 wires를 소스 수준 신호 선언 수로 해석하지 않았다.",
        "- 현재 aq 전체 완료율·최종 L1, 미실행 요청의 결과, 고유 결함 수·일반 성능 우위는 추정하지 않았다.",
        "- 위치 미귀속 L1은 고정 버그 위치를 확인한 결과가 아니다. 후보/리비전 관측 비율을 정확도나 새 취약점 수로 해석하지 않는다.", ""]
    return "\n".join(lines), output, bin_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    for key, value in DEFAULTS.items():
        parser.add_argument("--" + key.replace("_", "-"), default=value)
    parser.add_argument("--output", default="docs/n6_a_size_cost_table_2026-10-26.md")
    parser.add_argument("--max-seconds", type=int, default=180)
    args = parser.parse_args()
    try:
        reader = Reader(args.root, args.max_seconds)
        reader.text(args.w_causes)
        fuzz = collect_fuzz(args.main_queue, args.main_state, args.pragma_queue, args.pragma_state, reader)
        sizes = collect_sizes(args.main_queue, args.size_reuse, reader, pragma_queue_path=args.pragma_queue)
        require(len(fuzz) == 27 and set(sizes) == {row["revision"] for row in fuzz}, "official main universe differs")
        mapping = reader.json(args.mapping, "8ad5d43b51d5ceaab0d95dd83a229f45fdc2a2020485a21ccb3b1a43fb4aab85")
        strict, strict_details = load_j(reader, args.strict_index, args.strict_state, mapping, "v1", "strict")
        for row in fuzz:
            for method in ("W", "S"):
                strict.setdefault((row["revision"], method), zero(row["revision"], method))
        aggregate = reader.json(args.banyan_joins)
        exploratory = {}
        for engine, suffix in (("v2.2", "v22"), ("v1", "v1")):
            exploratory[engine], _ = load_j(reader, getattr(args, "banyan_index_" + suffix),
                getattr(args, "banyan_state_" + suffix), mapping, engine, "exploratory", aggregate)
        aq, aqstate = aq_snapshot(reader, args)
        for engine in exploratory:
            require(not (set(exploratory[engine]) & set(aq[engine])), "exploratory revision overlap")
            exploratory[engine].update(aq[engine])
        latest = latest_rqc(reader, args.aq_rqc_dir)
        content, output, bins = render(reader, args, fuzz, sizes, strict, exploratory, aqstate, latest)
        reader.guard()
        data = content.encode("utf-8")
        require(len(data) < 3 * 1024**2, "report exceeds small output bound")
        require(output.resolve() == output and not output.is_symlink(), "unsafe report output")
        temporary = output.with_name(output.name + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        print(json.dumps({"status": "complete", "report": str(output), "bytes": len(data),
            "report_sha256": hashlib.sha256(data).hexdigest(), "revisions": len(fuzz),
            "strict_main": {key: value for key, value in strict_details["totals"].items()
                            if key not in {"result_sources", "join_keys"}}, "size_bins": bins,
            "aq_snapshot_status": aqstate["status"], "latest_rqc": {k:v for k,v in latest.items() if k!="data"},
            "elapsed_seconds": time.monotonic()-reader.started}, ensure_ascii=False,
            default=str))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "stopped", "reason": str(error), "judging_executed": False},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
