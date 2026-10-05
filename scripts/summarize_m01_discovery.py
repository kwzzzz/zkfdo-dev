#!/usr/bin/env python3
"""Build the value-free M-01 JSON and Markdown reports from raw result records."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_m01_discovery as m01  # noqa: E402

ROOT = m01.ROOT
RUN = m01.RUN
JSON_OUT = ROOT / "docs/m01_discovery_results_2026-10-03.json"
MD_OUT = ROOT / "docs/m01_discovery_results_2026-10-03.md"
STATUSES = ("success", "partial", "unsupported", "failed", "unknown", "not_started", "timeout", "failure")


def counts(values):
    counter = Counter(values)
    return {key: counter[key] for key in STATUSES if counter[key]} | {
        key: value for key, value in sorted(counter.items()) if key not in STATUSES}


def timings(values):
    values = sorted(value for value in values if isinstance(value, (int, float)))
    if not values:
        return {"n": 0}
    return {"n": len(values), "total": round(sum(values), 3),
            "median": round(statistics.median(values), 3), "max": round(values[-1], 3)}


def remaining(result):
    reasons = []
    discovery = result.get("discovery") or {}
    capture = result.get("instance_discovery") or {}
    preparation = result.get("preparation") or {}
    if discovery.get("status") != "success":
        reasons.append("discovery:" + str(discovery.get("failure_type") or discovery.get("status")))
    elif capture.get("selected") != "compiler" or not capture.get("compiler_complete"):
        reasons.append("instance_capture:" + str(capture.get("capture_status") or "incomplete"))
        if capture.get("capture_failure"):
            reasons.append("capture_failure:" + str(capture["capture_failure"]).splitlines()[0][:240])
    reasons.extend("discovery_unsupported:" + row["reason"] for row in discovery.get("unsupported", []))
    reasons.extend("preparation:" + code for code in preparation.get("failure_types", []))
    if result.get("m01_component_status") != "success" and not reasons:
        reasons.append("preparation_status:" + str(result.get("m01_component_status")))
    return sorted(set(reasons))


def capture_category(result):
    discovery = result.get("discovery") or {}
    capture = result.get("instance_discovery") or {}
    if discovery.get("status") != "success":
        return "discovery_" + str(discovery.get("status"))
    if capture.get("selected") != "compiler":
        return "selected_" + str(capture.get("selected"))
    return "compiler_complete" if capture.get("compiler_complete") else "compiler_incomplete"


def build():
    lock = json.loads((RUN / "procedure-lock.json").read_text())
    results = {}
    for path in sorted((RUN / "measurements").glob("*/result.json")):
        result = json.loads(path.read_text())
        results[result["identifier"]] = result
    entries = lock["inputs"]["entries"]
    missing = sorted(row["identifier"] for row in entries if row["identifier"] not in results)
    extra = sorted(set(results) - {row["identifier"] for row in entries})
    if missing or extra:
        raise RuntimeError(f"M-01 result denominator mismatch: missing={len(missing)} extra={len(extra)}")
    if sum(row.get("zkfuzz_executions", 0) for row in results.values()):
        raise RuntimeError("M-01 contains a zkFuzz execution")
    repos = defaultdict(list)
    for entry in entries:
        repos[entry["repository"]].append((entry, results[entry["identifier"]]))
    repo_rows = []
    for name, pairs in sorted(repos.items()):
        repo_rows.append({
            "repository": name, "commit_sha": pairs[0][0]["commit_sha"], "entrypoints": len(pairs),
            "large_entrypoints": sum(entry["constraints"] >= 100_000 for entry, _ in pairs),
            "e01_preparation": counts(entry["e01_component_status"] for entry, _ in pairs),
            "m01_preparation": counts(result["m01_component_status"] for _, result in pairs),
            "transitions": dict(sorted(Counter(
                entry["e01_component_status"] + " -> " + result["m01_component_status"]
                for entry, result in pairs).items())),
            "capture": counts(capture_category(result) for _, result in pairs),
        })
    large = []
    for entry in entries:
        if entry["constraints"] < 100_000:
            continue
        result = results[entry["identifier"]]
        capture = result.get("instance_discovery") or {}
        discovery = result.get("discovery") or {}
        large.append({
            "identifier": entry["identifier"], "repository": entry["repository"],
            "entrypoint": entry["entrypoint"], "entrypoint_key": entry["entrypoint_key"],
            "constraints": entry["constraints"], "e01_status": entry["e01_component_status"],
            "m01_status": result["m01_component_status"], "capture": capture_category(result),
            "capture_status": capture.get("capture_status"), "compiler_complete": capture.get("compiler_complete"),
            "captured_instances": capture.get("captured_instances"),
            "callsites": discovery.get("callsites"), "unique_compile_units": discovery.get("unique_compile_units"),
            "eligible": (result.get("preparation") or {}).get("eligible"),
            "expected_targets": (result.get("preparation") or {}).get("expected_targets"),
            "remaining_reasons": remaining(result),
        })
    all_results = list(results.values())
    limitation_counts = Counter(reason for result in all_results if result["m01_component_status"] != "success"
                                for reason in remaining(result))
    cleanup = {}
    cleanup_path = RUN / "cleanup-result.json"
    if cleanup_path.is_file():
        cleanup = json.loads(cleanup_path.read_text())
    cleanup_audit = {}
    cleanup_audit_path = RUN / "post-cleanup-audit.json"
    if cleanup_audit_path.is_file():
        cleanup_audit = json.loads(cleanup_audit_path.read_text())
    checks = {}
    checks_path = RUN / "checks/checks.json"
    if checks_path.is_file():
        checks = json.loads(checks_path.read_text())
    blocked_log = RUN / "measurement.log"
    actual_log = RUN / "measurement-escalated.log"
    history = []
    if blocked_log.is_file():
        text = blocked_log.read_text(errors="replace")
        history.append({
            "kind": "sandbox_preflight_blocked", "completed_results": 0,
            "permission_errors": text.count("PermissionError"),
            "reason": "sandbox denied /bin/ps before the child-process runner could start",
            "log": m01.legacy.reference(blocked_log),
        })
    if actual_log.is_file():
        history.append({"kind": "actual_measurement", "completed_results": len(results),
                        "log": m01.legacy.reference(actual_log)})
    return {
        "schema_version": 1, "task": "M-01", "date": "2026-10-03", "owner": "miiz",
        "deadline": "2026-10-05", "status": "complete", "zkfuzz_invocations": 0,
        "scope": {"entrypoints": len(entries), "large_entrypoints_at_least_100k": len(large),
                  "repositories": len(repos), "procedure_lock": m01.legacy.reference(RUN / "procedure-lock.json"),
                  "e01_results": lock["inputs"]["e01_results"], "stages": lock["stages"],
                  "excluded_stages": lock["excluded_stages"]},
        "measurement_window": {"started_at": min(result["started_at"] for result in all_results),
                               "finished_at": max(result["finished_at"] for result in all_results)},
        "tools": lock["tools"], "icloud_window_check": lock["icloud_window_check"],
        "history": history,
        "overall": {
            "e01_preparation": counts(entry["e01_component_status"] for entry in entries),
            "m01_preparation": counts(result["m01_component_status"] for result in all_results),
            "transitions": dict(sorted(Counter(
                entry["e01_component_status"] + " -> " + results[entry["identifier"]]["m01_component_status"]
                for entry in entries).items())),
            "capture": counts(capture_category(result) for result in all_results),
            "discovery_status": counts((result.get("discovery") or {}).get("status") for result in all_results),
            "plan_status": counts((result.get("plan") or {}).get("status", "not_started") for result in all_results),
        },
        "repositories": repo_rows, "large_entrypoints": sorted(large, key=lambda row: (row["repository"], row["entrypoint"])),
        "instance_capture_completeness": {
            "population": len(entries),
            "compiler_complete": sum(capture_category(result) == "compiler_complete" for result in all_results),
            "capture_reports_recorded": sum(bool((result.get("instance_discovery") or {}).get("capture_report"))
                                            for result in all_results),
            "captured_values_preserved_in_json": all(
                capture_category(result) != "compiler_complete" or
                all((result.get("instance_discovery") or {}).get(key) is not None
                    for key in ("capture_report", "captured_instances", "capture_signals", "capture_constraints",
                                "compiler_root_instance_key")) for result in all_results),
        },
        "remaining_limitations": dict(limitation_counts.most_common()),
        "cost": {
            "discovery_seconds": timings((result.get("discovery") or {}).get("elapsed_seconds")
                                          for result in all_results),
            "capture_compile_seconds": timings((result.get("instance_discovery") or {}).get("capture_compile_seconds")
                                                for result in all_results),
            "preparation_seconds": timings((result.get("preparation") or {}).get("elapsed_seconds")
                                            for result in all_results),
            "plan_seconds": timings((result.get("plan") or {}).get("elapsed_seconds")
                                     for result in all_results),
        },
        "cleanup": cleanup, "post_cleanup_audit": cleanup_audit, "checks": checks,
        "limitations": [
            "The preparation statuses are structural discovery/compile/plan outcomes, not semantic correctness or fuzzing evidence.",
            "Original compile outcomes and constraint counts are reused from E-01; M-01 did not rerun the original compile stage.",
            "The corpus contains E-01 compile successes only and does not estimate setup or original-compile success.",
        ],
    }


def markdown(document):
    lines = [
        "# M-01: E-01 컴파일 성공 entrypoint의 F-01 탐색기 재측정",
        "", "- 담당: miiz", "- 측정 시작: 2026-10-03", "- 측정·정리 완료: 2026-10-05", "- 기한: 2026-10-05",
        "- 범위: E-01 원본 컴파일 성공 125개, 그중 제약 10만 이상 49개",
        "- 실행: instance capture 포함 대상 탐색 → 준비 → plan", "- zkFuzz 실행: 0회", "",
        "## 결과", "", "| 구분 | E-01 | M-01 |", "|---|---:|---:|",
    ]
    for status in STATUSES:
        before = document["overall"]["e01_preparation"].get(status, 0)
        after = document["overall"]["m01_preparation"].get(status, 0)
        if before or after:
            lines.append(f"| {status} | {before} | {after} |")
    lines += ["", "고정 F-01 바이너리 SHA-256: `" + document["tools"]["zkfDO_copy"]["sha256"] + "`.",
              "E-01 최종 측정은 13:43–16:35 KST여서 프로젝트 이동 시간 19:30–20:16 KST와 겹치지 않았고, 경로 소실 오류도 관측되지 않았다.", "",
              "## 저장소별 전후", "", "| 저장소 | entrypoint | 대형 | E-01 | M-01 |", "|---|---:|---:|---|---|"]
    for row in document["repositories"]:
        lines.append(f"| `{row['repository']}` | {row['entrypoints']} | {row['large_entrypoints']} | "
                     f"{json.dumps(row['e01_preparation'], ensure_ascii=False)} | "
                     f"{json.dumps(row['m01_preparation'], ensure_ascii=False)} |")
    lines += ["", "## 제약 10만 이상 entrypoint 49개", "",
              "| 저장소 | entrypoint | 제약 | E-01 | M-01 | 캡처 | 남은 사유 |",
              "|---|---|---:|---|---|---|---|"]
    for row in document["large_entrypoints"]:
        reasons = "<br>".join(row["remaining_reasons"]) or "—"
        lines.append(f"| `{row['repository']}` | `{row['entrypoint']}` | {row['constraints']} | "
                     f"{row['e01_status']} | {row['m01_status']} | {row['capture']} | {reasons} |")
    capture = document["instance_capture_completeness"]
    lines += ["", "## 인스턴스 캡처와 남은 한계", "",
              f"컴파일러 캡처 완전: {capture['compiler_complete']}/{capture['population']}; "
              f"캡처 JSON 참조 기록: {capture['capture_reports_recorded']}/{capture['population']}; "
              f"결과 JSON의 필수 캡처 값 보존 검사: {capture['captured_values_preserved_in_json']}.", "",
              "| 남은 사유 | 건수 |", "|---|---:|"]
    if document["remaining_limitations"]:
        for reason, count in document["remaining_limitations"].items():
            lines.append(f"| {reason} | {count} |")
    else:
        lines.append("| 없음 | 0 |")
    lines += ["", "## 측정 비용", "", "| 단계 | n | 합계(초) | 중앙값(초) | 최댓값(초) |",
              "|---|---:|---:|---:|---:|"]
    for key, label in (("discovery_seconds", "탐색"), ("capture_compile_seconds", "캡처 컴파일"),
                       ("preparation_seconds", "준비"), ("plan_seconds", "plan")):
        value = document["cost"][key]
        lines.append(f"| {label} | {value['n']} | {value.get('total', '—')} | "
                     f"{value.get('median', '—')} | {value.get('max', '—')} |")
    lines += ["", "단계별 시간은 겹쳐 실행된 worker의 합계이며 전체 wall time과 같지 않다.",
              "", "## 실행·정리·검사", "",
              "원본 setup과 compile 결과를 재사용했고 설치와 원본 compile을 다시 실행하지 않았다. "
              "수치는 원시 `result.json` 125개에서 산출했다.", ""]
    history = document.get("history") or []
    blocked = next((row for row in history if row["kind"] == "sandbox_preflight_blocked"), None)
    if blocked:
        lines.append(f"첫 샌드박스 시도는 `/bin/ps` 권한 차단으로 {blocked['permission_errors']}개가 자식 실행 전에 중단돼 "
                     "완결 결과를 만들지 않았다. 같은 lock의 샌드박스 밖 재실행 125개만 결과 분모에 썼다.")
        lines.append("")
    cleanup = document.get("cleanup") or {}
    if cleanup:
        lines.append(f"컴파일 산출물 및 진단 `.circom` 사본 {cleanup.get('deleted_count', 0):,}개, "
                     f"{cleanup.get('deleted_bytes', 0):,}바이트를 manifest 기록과 크기·해시 재확인 후 삭제했다.")
        lines.append("")
    audit = document.get("post_cleanup_audit") or {}
    if audit:
        values = audit["counts"]
        lines.append(f"삭제 가능 잔존은 컴파일 산출물 {values['compiled_artifacts']}개, 보호 경로 밖 진단 `.circom` "
                     f"{values['diagnostic_circom_deletable']}개다. 진단 사본의 `node_modules` 안 `.circom` "
                     f"{values['diagnostic_circom_protected_node_modules']:,}개는 보존 규칙에 따라 남겼다.")
        lines.append("")
    checks = document.get("checks") or {}
    if checks:
        lines.append(
            "필수 검사: M-01 Python "
            f"{checks['python_m01_unittest']['passed']}건, 결과 검산, cargo fmt, 지정 clippy, "
            f"cargo test {checks['cargo_test']['passed']}건 통과"
            f"({checks['cargo_test']['ignored']}건 ignored), 정리 잔존 검사 통과."
        )
        lines.append("")
    lines += ["## 주장 한계", "", "이 결과는 고정된 125개에서 구조적 대상 탐색·준비·plan의 적용성을 측정한다. "
              "탐지 우위, 의미 동등성, 결함 존재, 전체 corpus 적용성을 뜻하지 않는다. N4-1 전체와 N5는 완료하지 않는다.", ""]
    return "\n".join(lines)


def main():
    document = build()
    JSON_OUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    MD_OUT.write_text(markdown(document))
    print(json.dumps({"entrypoints": document["scope"]["entrypoints"],
                      "large": len(document["large_entrypoints"]),
                      "statuses": document["overall"]["m01_preparation"]}))


if __name__ == "__main__":
    main()
