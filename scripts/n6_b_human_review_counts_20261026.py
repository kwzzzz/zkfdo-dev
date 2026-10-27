#!/usr/bin/env python3
"""Read saved B batch-1 receipts; count N5 amendment 4.3 without running J.

No candidate or witness files are opened. Only explicit metadata references in
indexes, states and the saved paired-result gate are followed. No B file is
written. Output contains identifiers, classifications, counts and evidence
references, never candidate, witness or signal values.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
GATE = "runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json"
INDEX_ROOT = "runs/n6-b6e-2026-10-20.noindex"
STATE_ROOT = "runs/n6-b6g-2026-10-23.noindex"
INDEX_HASHES = {"v1": "08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c",
                "v2.2": "2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39"}
TERMINAL = {"completed", "preparation_failure", "inspection_failure"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Reader:
    def __init__(self, root):
        self.root = root.resolve()
        self.started = time.monotonic()
        self.sources = {}
        self.guard()

    def guard(self):
        require(os.getpriority(os.PRIO_PROCESS, 0) >= 19, "nice 19 is required")
        require(shutil.disk_usage(self.root).free >= 15 * 1024**3,
                "internal free space is below 15 GiB")
        require(time.monotonic() - self.started <= 180, "read budget exceeded")

    def path(self, path):
        path = Path(path)
        path = (self.root / path).resolve() if not path.is_absolute() else path.resolve()
        require(path.is_relative_to(self.root), "input outside repository")
        parts = [p.lower() for p in path.parts]
        require("aq-exec" not in parts and not any(p.startswith("h1") or "hunting" in p for p in parts),
                "input outside B metadata scope")
        require(not any("candidate" in p or "witness" in p for p in parts),
                "raw candidate or witness input prohibited")
        return path

    def read(self, path, expected=None):
        self.guard()
        path = self.path(path)
        require(path.stat().st_size <= 16 * 1024**2, "metadata input exceeds limit")
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        require(expected is None or sha == expected, "input SHA-256 mismatch")
        text = raw.decode("utf-8")
        relative = str(path.relative_to(self.root))
        self.sources[relative] = {"path": relative, "sha256": sha, "bytes": len(raw)}
        return json.loads(text), text

    def reference(self, path, text, marker=None):
        path = self.path(path)
        lines = text.splitlines()
        line = next((i for i, s in enumerate(lines, 1) if marker and marker in s), 1)
        relative = str(path.relative_to(self.root))
        return {"path": relative, "line": line, "sha256": self.sources[relative]["sha256"]}


def class_flags(own, effective):
    l1 = own == "entrypoint_violation" or effective == "assumption_violation_reachable"
    excluded = own == "excluded_in_context" or effective == "assumption_excluded_in_context"
    require(not (l1 and excluded), "conflicting class verdicts")
    return l1, excluded


def request_flags(classes):
    l1 = any(c["l1"] for c in classes)
    return l1, any(c["excluded"] for c in classes) and not l1


def recount(reader, args):
    gate, gate_text = reader.read(args.gate)
    require(gate.get("kind") == "n6_b6h_deadline_pair_result_gate" and gate.get("status") == "passed",
            "saved paired gate missing")
    indexes, states, state_paths, all_classes, flags, meta = {}, {}, {}, {}, {}, {}
    for engine, arg in (("v1", "v1"), ("v2.2", "v22")):
        state_path = reader.path(getattr(args, arg + "_state"))
        index_path = reader.path(getattr(args, arg + "_index"))
        state, state_text = reader.read(state_path)
        index, index_text = reader.read(index_path, getattr(args, arg + "_index_sha256"))
        require(state.get("request_index_sha256") == reader.sources[str(index_path.relative_to(reader.root))]["sha256"],
                "state/index binding differs")
        require(state.get("engine_sha256") == index.get("engine_sha256"), "engine binding differs")
        rows = {r["queue_order"]: r for r in index["requests"]}
        require(len(rows) == index["request_count"] and set(rows) == set(range(len(rows))),
                "index coverage differs")
        require(all(r.get("scope") == "main" for r in rows.values()), "non-main B request")
        events = {int(k): v for k, v in state["requests"].items()}
        require(set(events) <= set(rows) and all(e.get("status") in TERMINAL for e in events.values()),
                "nonterminal or unexpected B state request")
        completed = {k for k, e in events.items() if e["status"] == "completed"}
        effective, joined_paths = {}, set()
        for receipt in gate["paired_joins"][engine]:
            joined, joined_text = reader.read(receipt["path"], receipt["sha256"])
            require(joined.get("schema") == "zkfdo-instance-verdicts-v1" and joined.get("conflicts") == 0,
                    "saved join schema or conflict differs")
            require(len(joined["results"]) == receipt["request_count"], "join count differs")
            for relative in joined["results"]:
                p = reader.path(state_path.parent / relative)
                require(p.is_relative_to(state_path.parent), "join result escaped engine output")
                require(p not in joined_paths, "result appears in multiple joins")
                joined_paths.add(p)
            for c in joined["classes"]:
                key = c["request_id"], c["representative"]
                require(key not in effective, "duplicate effective class")
                effective[key] = c["effective"]
        expected_paths = {reader.path(events[k]["result_path"]) for k in completed}
        require(joined_paths == expected_paths, "saved joins do not cover all completed B results")
        all_classes[engine], flags[engine] = {}, {}
        for order in sorted(completed):
            event, row = events[order], rows[order]
            result_path = reader.path(event["result_path"])
            require(result_path.is_relative_to(state_path.parent), "result escaped engine output")
            result, text = reader.read(result_path, event["result_sha256"])
            require(result.get("schema") == "zkfdo-lifting-result-v1", "result schema differs")
            require(result.get("request_sha256") == event.get("request_sha256") == row.get("request_sha256"),
                    "result request binding differs")
            request_id = result["request_id"]
            classes = []
            for class_index, c in enumerate(result["classes"]):
                representative = c["representative"]
                key = order, representative
                require(key not in all_classes[engine], "duplicate request/class representative")
                shared = effective.get((request_id, representative))
                l1, excluded = class_flags(c["verdict"], shared)
                record = {"queue_order": order, "request_id": request_id,
                          "revision_id": row["revision_id"], "class_index": class_index,
                          "representative": representative, "own_verdict": c["verdict"],
                          "reason": c.get("reason"), "effective_verdict": shared,
                          "l1": l1, "excluded": excluded,
                          "source": reader.reference(result_path, text,
                                      '\"representative\": ' + json.dumps(representative))}
                all_classes[engine][key] = record
                classes.append(record)
            flags[engine][order] = request_flags(classes)
        indexes[engine], states[engine], state_paths[engine] = rows, events, state_path
        statuses = Counter(e["status"] for e in events.values())
        meta[engine] = {"planned_requests": len(rows), "terminal_requests": len(events),
                        "completed_results": len(completed), "unfinished_requests": len(rows) - len(events),
                        "statuses": dict(sorted(statuses.items())),
                        "l1_requests": sum(l1 for l1, _ in flags[engine].values()),
                        "l1_classes": sum(c["l1"] for c in all_classes[engine].values()),
                        "result_classes": len(all_classes[engine]),
                        "state_source": reader.reference(state_path, state_text, '\"requests\":'),
                        "index_source": reader.reference(index_path, index_text, '\"request_count\":')}
        require(gate["engines"][engine]["finished"] == len(events) and
                gate["engines"][engine]["unfinished"] == len(rows) - len(events),
                "saved gate/state denominator differs")
    require(set(indexes["v1"]) == set(indexes["v2.2"]), "engine indexes differ")
    for order in indexes["v1"]:
        require(all(indexes["v1"][order][k] == indexes["v2.2"][order][k]
                    for k in ("revision_id", "scope", "method", "candidate_sha256")),
                "engine row identity differs")
    require(set(flags["v1"]) == set(flags["v2.2"]), "completed engine subsets differ")
    require(set(all_classes["v1"]) == set(all_classes["v2.2"]), "engine class identities differ")
    paired = len(flags["v1"])
    require(paired == gate["paired_judged_requests"], "paired completed count differs")
    differences, v22_only, l1_items = [], [], []
    comparisons = Counter()
    for order in sorted(flags["v1"]):
        l1a, exa = flags["v1"][order]
        l1b, exb = flags["v2.2"][order]
        comparisons["a_v1_only_l1"] += l1a and not l1b
        comparisons["b_v2_2_only_l1"] += l1b and not l1a
        conflict = (exa and l1b) or (exb and l1a)
        comparisons["c_excluded_vs_l1"] += conflict
        if conflict:
            differences.append({"queue_order": order, "v1": {"l1": l1a, "excluded": exa},
                                "v2.2": {"l1": l1b, "excluded": exb}})
    require(dict(comparisons) == gate["comparisons"], "recomputed request comparisons differ")
    for key in sorted(all_classes["v1"]):
        a, b = all_classes["v1"][key], all_classes["v2.2"][key]
        require(a["request_id"] == b["request_id"], "engine request identity differs")
        if a["l1"] or b["l1"]:
            l1_items.append({"v1": a, "v2.2": b})
        if b["excluded"] and not a["excluded"]:
            v22_only.append({"v1": a, "v2.2": b})
    return {"schema": "n6-b-human-review-counts-v1", "generated_at": datetime.now(timezone.utc).isoformat(),
            "layer": "exploratory_constructed_input_batch1_interim", "engines": meta,
            "paired_judged_requests": paired,
            "scope_4_3": {"l1_union_requests": len({c["v1"]["queue_order"] for c in l1_items}),
                           "l1_union_classes": len(l1_items),
                           "excluded_vs_l1_requests": len(differences),
                           "v22_only_excluded_requests": len({c["v2.2"]["queue_order"] for c in v22_only}),
                           "v22_only_excluded_classes": len(v22_only)},
            "l1_items": l1_items, "excluded_vs_l1_items": differences,
            "v22_only_excluded_items": v22_only,
            "saved_gate_source": reader.reference(args.gate, gate_text, '\"comparisons\":'),
            "input_sources": sorted(reader.sources.values(), key=lambda s: s["path"]),
            "elapsed_seconds": time.monotonic() - reader.started,
            "nice": os.getpriority(os.PRIO_PROCESS, 0),
            "internal_free_bytes": shutil.disk_usage(reader.root).free,
            "limitations": ["Only the saved, mutually completed batch-1 interim subset is judged; 63 unfinished requests per engine are not negative results.",
                            "Existing saved paired joins are hash-checked and reused; J and lift-instances are not executed.",
                            "Class correspondence uses queue order and exact representative; unmatched classes fail closed."]}


def render_report(report, args, output_sha, independent, independent_sha):
    def ref(source):
        return f"`{source['path']}:{source['line']}`"
    count = report["scope_4_3"]
    gate = ref(report["saved_gate_source"])
    states = " · ".join(ref(report["engines"][e]["state_source"]) for e in ("v2.2", "v1"))
    counts_ref = f"`{args.output.resolve()}` (`scope_4_3`, `engines`, 전체 원본 SHA 목록 `input_sources`)"
    status = independent.get("status", "미실행(독립 확인 기록 없음)") if independent else "미실행(독립 확인 기록 없음)"
    task1 = args.task1_report
    lines = [f"1번 결과: **문제 있음 — 자동 RQ-C 프로토콜 해시 불일치(별도 래퍼 검증 완료)**. [{task1}](../{task1})", "",
             "# B 사람 검토 자료 — N5 개정 4절 3항 (2026-10-26)", "",
             "담당: miiz·리드. 구성 입력 탐색층 B 1묶음의 공간 중단 시점 중간 결과다. 사람 검토 칸은 판정·서명 없이 비워 두었다.", "",
             f"기준은 `docs/n5_amendment_b_judging_2026-10-17.md:34`, `:70`, `:111`, `:135`다. 집계 근거는 {counts_ref}; 저장된 쌍 관문 {gate}, 상태 {states}와 연결된 결과·공유 판정의 해시를 다시 확인했다.", "",
             "| 재집계 범위 | 수 | 근거 |", "|---|---:|---|",
             f"| B의 모든 L1 합집합 | {count['l1_union_requests']}요청 / {count['l1_union_classes']}클래스 | {counts_ref}; {states} |",
             f"| 2절 4항 (다): 한 엔진 배제·다른 엔진 L1 | {count['excluded_vs_l1_requests']}요청 | {gate}; {counts_ref} |",
             f"| v2.2에서만 나온 배제 | {count['v22_only_excluded_requests']}요청 / {count['v22_only_excluded_classes']}클래스 | 아래 결과 파일; {counts_ref} |", ""]
    for engine in ("v2.2", "v1"):
        e = report["engines"][engine]
        lines.append(f"- {engine}: 계획 {e['planned_requests']}건 중 완료 결과 {e['completed_results']}건·준비 실패 {e['statuses'].get('preparation_failure', 0)}건·미완료 {e['unfinished_requests']}건, 완료 결과의 클래스 {e['result_classes']}개. 근거: {ref(e['index_source'])}, {ref(e['state_source'])}, {counts_ref}.")
    lines += ["", "보수적 선택: 미완료·준비 실패를 음성 판정으로 세지 않고, 두 엔진의 완료 요청·클래스 대응과 저장된 공유 판정 범위가 정확히 같을 때만 비교했다. 엔진이나 집계 실행기는 재실행하지 않았다. 분류 규칙 근거는 `scripts/n6_b6h_result_gate.py:122`–`:137`이며, 저장된 유효 판정을 재사용했다.", "",
              "| 항목 | 근거 파일·줄 | 기계 판정 | 독립 확인 결과 | 사람 검토 |", "|---|---|---|---|---|"]
    if not report["l1_items"]:
        lines.append(f"| 모든 L1 | {states}; {counts_ref} | 해당 없음 | 원본 결과·저장된 공유 판정 재집계 일치 | |")
    if not report["excluded_vs_l1_items"]:
        lines.append(f"| 2절 4항 (다) | {gate}; {counts_ref} | 해당 없음 | 원본 재집계와 저장된 관문 일치 | |")
    for item in report["v22_only_excluded_items"]:
        a, b = item["v1"], item["v2.2"]
        lines.append(f"| 리비전 `{b['revision_id']}` · 요청 {b['queue_order']} · 클래스 {b['class_index']} | {ref(b['source'])}; {ref(a['source'])}; `docs/n6_b6h_review_v22_only_exclusion_2026-10-25.md:9` | v2.2 `{b['own_verdict']}` (`{b['reason']}`); v1 `{a['own_verdict']}` (`{a['reason']}`) | {status} · `{args.independent_check}` | |")
    if independent:
        solver_text = (f"{independent['solver_result']}; 시간 {independent['solver_seconds']}초"
                       if independent.get("solver_result") is not None
                       else "미실행; 시간 —")
        lines += ["", f"현재 독립 확인: `{status}`, 원뿔 파일 존재 `{independent.get('cone_exists')}`, 부모 경로 존재 `{independent.get('query_parent_exists')}`. 명시 경로는 `{independent.get('cone_path')}`이며 근거는 `{args.independent_check}`다. 독립 솔버: {solver_text}."]
    lines += ["", "기존 독립 z3 재실행 완료 기록은 docs의 `n6_b*`·`n6_light*`·`n5*` 문서 검색에서 찾지 못했다. 이는 해당 문서 범위의 확인이며 다른 위치의 기록 존재까지 부정하지 않는다.", "", "독립 확인 범위: 기존 검토 문서 `docs/n6_b6h_review_v22_only_exclusion_2026-10-25.md:19`의 62제약·69미지 원뿔, `:21`의 고정 사이트 신호 4개다. `:23`은 원래 SMT2 삭제를 기록한다. 이번 확인은 남은 명시 경로와 설치된 Python z3만 대상으로 하며, J 재실행·재컴파일·설치를 하지 않았다. 값은 출력하지 않았다.", "",
              "다시 실행(저장소 루트):", "", "```sh",
              "nice -n 19 python3 -B scripts/n6_b_cone_independent_check_20261026.py --output /private/tmp/n6_b_cone_independent_check_20261026.json",
              "nice -n 19 python3 -B scripts/n6_b_human_review_counts_20261026.py \\",
              "  --gate runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json \\",
              "  --v1-index runs/n6-b6e-2026-10-20.noindex/request-index-v1.json \\",
              "  --v22-index runs/n6-b6e-2026-10-20.noindex/request-index-v2.2.json \\",
              "  --v1-state runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/state.json \\",
              "  --v22-state runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/state.json \\",
              f"  --independent-check {args.independent_check} \\",
              f"  --output {args.output} \\",
              f"  --report {args.report}", "```", "",
              "새 파일 SHA-256(이 보고서 자체 해시는 최종 전달문에서 별도 제시):", "", "| 파일 | SHA-256 |", "|---|---|"]
    for path in [Path(__file__), args.root / "scripts/n6_b_cone_independent_check_20261026.py"]:
        if path.is_file():
            lines.append(f"| `{path.relative_to(args.root.resolve())}` | `{hashlib.sha256(path.read_bytes()).hexdigest()}` |")
    lines.append(f"| `{args.output.resolve()}` | `{output_sha}` |")
    if independent_sha:
        lines.append(f"| `{args.independent_check.resolve()}` | `{independent_sha}` |")
    lines += ["", "**확인한 것**: 위 범위의 기계 판정과 경로·SHA 연결을 기존 결과로 다시 확인했다. 후보·witness 파일, 실행 중 aq, 전환 스크립트와 B 원본은 수정하지 않았다.", "",
              "**추정한 것**: 독립 풀이가 실행되지 않았으므로 저장된 UNSAT을 독립 확인으로 대체하지 않았다. 원뿔의 원래 O1 적용과 실제 배포 공격 가능성은 사람 검토에 남긴다. 미완료 요청에 대한 결과는 추정하지 않았다.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--gate", default=GATE)
    for engine, option in (("v1", "v1"), ("v2.2", "v22")):
        parser.add_argument("--" + option + "-index", default=f"{INDEX_ROOT}/request-index-{engine}.json")
        parser.add_argument("--" + option + "-index-sha256", default=INDEX_HASHES[engine])
        parser.add_argument("--" + option + "-state", default=f"{STATE_ROOT}/full-{engine}.noindex/state.json")
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/n6_b_human_review_counts_20261026.json"))
    parser.add_argument("--independent-check", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--task1-report", default="docs/n6_a_rqc_input_audit_2026-10-26.md")
    args = parser.parse_args(argv)
    try:
        reader = Reader(args.root)
        output = args.output.resolve()
        parts = [p.lower() for p in output.parts]
        require("aq-exec" not in parts and not any(p.startswith("n6-b") or p.startswith("h1") for p in parts),
                "output inside protected run path")
        require(output != Path(__file__).resolve() and output.suffix == ".json", "output must be JSON")
        report = recount(reader, args)
        reader.guard()
        require(str(output) not in {str(reader.root / p) for p in reader.sources}, "output overlaps input")
        content = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        require(len(content.encode()) <= 1024**2, "output exceeds 1 MiB")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
        if args.report:
            reader.guard()
            report_path = args.report.resolve()
            require(report_path.is_relative_to(reader.root / "docs") and report_path.suffix == ".md",
                    "report must be local docs Markdown")
            independent, independent_sha = None, None
            if args.independent_check:
                independent_path = args.independent_check.resolve()
                require("aq-exec" not in independent_path.parts and
                        not any(p.startswith("n6-b") or p.startswith("h1") for p in independent_path.parts),
                        "independent receipt in protected input path")
                require(independent_path.stat().st_size <= 1024**2, "independent receipt exceeds limit")
                raw = independent_path.read_bytes()
                independent_sha = hashlib.sha256(raw).hexdigest()
                independent = json.loads(raw)
            markdown = render_report(report, args, hashlib.sha256(content.encode()).hexdigest(),
                                     independent, independent_sha)
            require(len(markdown.encode()) <= 1024**2, "report exceeds 1 MiB")
            report_path.write_text(markdown)
        print(json.dumps({"status": "passed", "output": str(output),
                          "output_sha256": hashlib.sha256(content.encode()).hexdigest(),
                          "scope_4_3": report["scope_4_3"],
                          "paired_judged_requests": report["paired_judged_requests"],
                          "elapsed_seconds": report["elapsed_seconds"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print("B review metadata validation failed; no candidate values emitted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
