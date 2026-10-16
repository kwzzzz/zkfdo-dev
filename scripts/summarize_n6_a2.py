#!/usr/bin/env python3
"""Summarize completed N6-A2 ledgers without reading candidate file contents."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a2-2026-10-08"
EXECUTION_LIST = RUN / "execution-list-v1.json"
CONTROLLER = RUN / "controller-state.json"
PMSET = RUN / "pmset-summary.json"
OUTPUT_JSON = ROOT / "docs/n6_a2_execute_results_2026-10-08.json"
OUTPUT_MD = ROOT / "docs/n6_a2_execute_results_2026-10-08.md"
CHECKS = RUN / "checks-final/checks.json"
FAILURE_OUTCOMES = {
    "spawn_error", "engine_nonzero", "finished_unknown", "resource_monitor_failure",
    "candidate_file_without_not_safe_log",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def finite(values: list[Any]) -> list[float]:
    return [float(value) for value in values
            if isinstance(value, (int, float)) and math.isfinite(float(value))]


def first_signal(attempts: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    observations = []
    completion_bounds = []
    for attempt in attempts:
        if attempt.get("candidates"):
            if attempt.get("completion_offset_seconds") is not None:
                completion_bounds.append(attempt["completion_offset_seconds"])
        for observation in attempt.get("log_observations", []):
            if observation.get("kind") == "not_safe":
                observations.append(observation["campaign_offset_seconds"])
    return (min(observations) if observations else None,
            min(completion_bounds) if completion_bounds else None)


def method_row(phase: str, unit: dict[str, Any], method: str,
               state_row: dict[str, Any]) -> dict[str, Any]:
    result = state_row[method]
    if not isinstance(result, dict) or not result.get("ledger"):
        raise ValueError(f"completed method has no ledger: {unit['unit_id']} {method}")
    ledger_path = ROOT / result["ledger"]
    if sha256(ledger_path) != result["ledger_sha256"]:
        raise ValueError(f"ledger hash changed: {ledger_path}")
    ledger = json.loads(ledger_path.read_text())
    attempts = ledger["attempts"]
    outcomes = Counter(attempt.get("outcome") for attempt in attempts)
    signal_offset, completion_bound = first_signal(attempts)
    candidate_attempts = sum(bool(attempt.get("candidates")) or
                             attempt.get("outcome") in {"candidate", "candidate_file_without_not_safe_log"}
                             for attempt in attempts)
    candidate_files = sum(len(attempt.get("candidates", [])) for attempt in attempts)
    not_safe = sum(observation.get("kind") == "not_safe" for attempt in attempts
                   for observation in attempt.get("log_observations", []))
    cleanup = [attempt.get("workspace_cleanup") for attempt in attempts]
    cleanup_deleted = sum(isinstance(row, dict) and row.get("status") == "deleted"
                          for row in cleanup)
    checkpoint = ledger.get("coverage_checkpoints", {}).get("600") or {}
    return {
        "phase": phase,
        "unit_id": unit["unit_id"],
        "identifier": unit["identifier"],
        "repository": unit["repository"],
        "seed": unit["seed"],
        "method": method,
        "status": ledger.get("status"),
        "termination_reason": ledger.get("termination_reason"),
        "fatal_error": ledger.get("fatal_error"),
        "campaign_wall_seconds": ledger.get("campaign_wall_seconds"),
        "attempt_count": len(attempts),
        "process_start_count": sum(bool(row.get("process_started")) for row in attempts),
        "outcome_counts": dict(sorted(outcomes.items())),
        "candidate_attempt_count": candidate_attempts,
        "candidate_file_count": candidate_files,
        "not_safe_observation_count": not_safe,
        "first_signal_observed_offset_seconds": signal_offset,
        "first_candidate_completion_upper_bound_seconds": completion_bound,
        "first_signal_time_meaning": (
            "parent observation offset of first stderr not_safe marker; candidate file completion is a separate upper bound"
        ),
        "memory_cap_count": outcomes["memory_cap"],
        "timeout_count": outcomes["timeout"],
        "failure_count": sum(outcomes[name] for name in FAILURE_OUTCOMES),
        "maximum_process_tree_rss_bytes": ledger.get("aggregate_process_tree_peak_memory_bytes"),
        "actual_cpu_seconds_sum": ledger.get("actual_cpu_seconds_sum"),
        "coverage_600": {
            "attempted_targets": checkpoint.get("attempted_targets"),
            "eligible_targets": checkpoint.get("eligible_targets"),
            "coverage": checkpoint.get("coverage"),
            "status": checkpoint.get("status"),
        },
        "workspace_cleanup": {
            "attempts_with_deleted_workspace": cleanup_deleted,
            "attempt_count": len(attempts),
            "deleted_bytes": sum((row or {}).get("bytes", 0) for row in cleanup
                                 if isinstance(row, dict)),
            "complete": cleanup_deleted == len(attempts),
        },
        "ledger": ledger_path.relative_to(ROOT).as_posix(),
        "ledger_sha256": result["ledger_sha256"],
    }


def load_samples(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_summary() -> dict[str, Any]:
    execution = json.loads(EXECUTION_LIST.read_text())
    controller = json.loads(CONTROLLER.read_text())
    if controller.get("status") != "completed":
        raise ValueError("N6-A2 controller is not complete")
    pmset = json.loads(PMSET.read_text())
    if pmset.get("status") != "passed" or pmset.get("sleep_event_count") != 0:
        raise ValueError("N6-A2 sleep audit did not pass")
    methods = []
    samples = []
    phase_records = {}
    for phase in execution["ordering"]:
        queue_path = ROOT / execution["queues"][phase]["path"]
        queue = json.loads(queue_path.read_text())
        output = RUN / "execute" / phase.lower()
        state_path = output / "state.json"
        state = json.loads(state_path.read_text())
        if state.get("status") != "completed":
            raise ValueError(f"phase is not complete: {phase}")
        if len(state.get("actual_start_order", [])) != len(queue["units"]):
            raise ValueError(f"phase start denominator differs: {phase}")
        for unit in queue["units"]:
            state_row = state["units"][unit["unit_id"]]
            if state_row.get("status") != "completed":
                raise ValueError(f"unit is incomplete: {unit['unit_id']}")
            methods.extend(method_row(phase, unit, method, state_row)
                           for method in ("W", "S"))
        phase_samples = load_samples(output / "host-load.jsonl")
        samples.extend(phase_samples)
        phase_records[phase] = {
            "queue": queue_path.relative_to(ROOT).as_posix(),
            "queue_sha256": sha256(queue_path),
            "state": state_path.relative_to(ROOT).as_posix(),
            "state_sha256": sha256(state_path),
            "unit_count": len(queue["units"]),
            "load_sample_count": len(phase_samples),
        }
    if len(methods) != execution["selected_spec_count"]:
        raise ValueError("method result denominator differs from execution list")
    load_columns = list(zip(*(row["load_average_1_5_15_minutes"] for row in samples), strict=True)) \
        if samples else [[], [], []]
    disk_values = [row["free_disk_bytes"] for row in samples]
    checks = json.loads(CHECKS.read_text()) if CHECKS.is_file() else None
    result = {
        "schema_version": 1,
        "task": "N6-A2 execute results",
        "generated_at": now(),
        "status": "completed",
        "candidate_contents_opened": False,
        "context_judgment_performed": False,
        "human_review_performed": False,
        "source": {
            "execution_list": EXECUTION_LIST.relative_to(ROOT).as_posix(),
            "execution_list_sha256": sha256(EXECUTION_LIST),
            "controller": CONTROLLER.relative_to(ROOT).as_posix(),
            "controller_sha256": sha256(CONTROLLER),
            "pmset": PMSET.relative_to(ROOT).as_posix(),
            "pmset_sha256": sha256(PMSET),
        },
        "denominator": {
            "selected_units": execution["selected_unit_count"],
            "method_seed_rows": len(methods),
            "excluded_identifier": execution["excluded"]["identifier"],
            "excluded_units": 3,
            "excluded_method_seed_rows": 6,
        },
        "phases": phase_records,
        "methods": methods,
        "aggregate": {
            "campaign_wall_seconds_sum": sum(row["campaign_wall_seconds"] or 0 for row in methods),
            "actual_cpu_seconds_sum": sum(row["actual_cpu_seconds_sum"] or 0 for row in methods),
            "attempt_count": sum(row["attempt_count"] for row in methods),
            "candidate_attempt_count": sum(row["candidate_attempt_count"] for row in methods),
            "candidate_file_count": sum(row["candidate_file_count"] for row in methods),
            "not_safe_observation_count": sum(row["not_safe_observation_count"] for row in methods),
            "memory_cap_count": sum(row["memory_cap_count"] for row in methods),
            "timeout_count": sum(row["timeout_count"] for row in methods),
            "failure_count": sum(row["failure_count"] for row in methods),
            "maximum_process_tree_rss_bytes": max(
                finite([row["maximum_process_tree_rss_bytes"] for row in methods]), default=None),
            "workspace_cleanup_complete": all(row["workspace_cleanup"]["complete"] for row in methods),
            "workspace_deleted_bytes": sum(row["workspace_cleanup"]["deleted_bytes"] for row in methods),
        },
        "host": {
            "load_sample_count": len(samples),
            "load_average_min_1_5_15": [min(column) for column in load_columns] if samples else None,
            "load_average_max_1_5_15": [max(column) for column in load_columns] if samples else None,
            "free_disk_bytes_min": min(disk_values) if disk_values else None,
            "free_disk_bytes_max": max(disk_values) if disk_values else None,
            "disk_free_before_bytes": controller["phases"]["A-D"]["disk_free_before_bytes"],
            "disk_free_after_bytes": controller["phases"]["A-Q"]["disk_free_after_bytes"],
            "sleep_event_count": pmset["sleep_event_count"],
        },
        "checks": checks,
    }
    return result


def fmt_seconds(value: Any) -> str:
    return "unknown" if value is None else f"{float(value):.6f}"


def render_markdown(result: dict[str, Any]) -> str:
    aggregate = result["aggregate"]
    host = result["host"]
    lines = [
        "# N6-A2 A 실행 결과",
        "",
        "- 담당: miiz",
        "- 상태: 완료",
        "- 실행: A-D 완료 후 A-Q, 단위 안 W 다음 S, 동시 단위 3",
        "- 판정 범위: campaign metadata 집계만 수행. 후보 파일 내용, 맥락 판정(J), 사람 검토는 수행하지 않음",
        "",
        "## 전체 결과",
        "",
        "| 항목 | 값 |",
        "|---|---:|",
        f"| 실행 단위 | {result['denominator']['selected_units']} |",
        f"| 방식·seed 행 | {result['denominator']['method_seed_rows']} |",
        f"| 시도 | {aggregate['attempt_count']} |",
        f"| 후보 신호가 있는 시도 | {aggregate['candidate_attempt_count']} |",
        f"| 보존 후보 파일 참조 | {aggregate['candidate_file_count']} |",
        f"| `not_safe` 관측 | {aggregate['not_safe_observation_count']} |",
        f"| memory cap | {aggregate['memory_cap_count']} |",
        f"| timeout | {aggregate['timeout_count']} |",
        f"| 실행 실패 | {aggregate['failure_count']} |",
        f"| 최대 process-tree RSS | {aggregate['maximum_process_tree_rss_bytes']} bytes |",
        f"| sleep | {host['sleep_event_count']} |",
        "",
        "`aq-038-4e5dcd2256b8`은 손상된 leave-one-out patch 때문에 W·S와 seed 3개, 즉 6개 방식·seed 행을 실행 전에 제외했다. 고정 A 목록과 70건 배치는 유지된다.",
        "",
        "## 단위·방식·seed별 결과",
        "",
        "| 단계 | 단위 | seed | 방식 | 종료 | 시도 | 600초 조각 커버리지 | 후보 신호 시도 | 최초 `not_safe` 관측(s) | 후보 완료 상한(s) | memory cap | timeout | 실패 | 최대 RSS(bytes) |",
        "|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["methods"]:
        coverage = row["coverage_600"]["coverage"]
        lines.append(
            f"| {row['phase']} | `{row['identifier']}` | {row['seed']} | {row['method']} | "
            f"{row['termination_reason']} | {row['attempt_count']} | "
            f"{'unknown' if coverage is None else f'{coverage:.6f}'} | "
            f"{row['candidate_attempt_count']} | {fmt_seconds(row['first_signal_observed_offset_seconds'])} | "
            f"{fmt_seconds(row['first_candidate_completion_upper_bound_seconds'])} | "
            f"{row['memory_cap_count']} | {row['timeout_count']} | {row['failure_count']} | "
            f"{row['maximum_process_tree_rss_bytes']} |"
        )
    lines += [
        "",
        "## 시간·자원·정리",
        "",
        f"campaign wall 합계는 {aggregate['campaign_wall_seconds_sum']:.3f}초, wait4 CPU 합계는 {aggregate['actual_cpu_seconds_sum']:.3f}초다. "
        f"10초 간격 host load {host['load_sample_count']}개에서 1/5/15분 최소는 `{host['load_average_min_1_5_15']}`, 최대는 `{host['load_average_max_1_5_15']}`였다. "
        f"디스크 여유 최소는 {host['free_disk_bytes_min']} bytes, 실행 시작은 {host['disk_free_before_bytes']} bytes, 종료는 {host['disk_free_after_bytes']} bytes였다.",
        "",
        f"모든 시도 workspace 정리 완료 여부는 `{aggregate['workspace_cleanup_complete']}`이며, 정리된 workspace의 논리 크기 합은 {aggregate['workspace_deleted_bytes']} bytes다. 후보 파일·zkFuzz 로그·시도 결과·ledger는 보존했다. pmset 차이에서 sleep은 0회였다.",
        "",
        "## 시간 의미와 주장 한계",
        "",
        "최초 신호 시각은 parent가 stderr의 `not_safe` 표식을 관측한 campaign offset이다. 후보 파일이 보존된 시도의 완료 offset은 별도 상한이며 정확한 후보 생성시각으로 바꾸지 않았다. candidate signal은 확인된 결함 수나 고유 원인 수가 아니다. 새 후보에 과거 판정을 복사하지 않았고 후보 값, R1CS 의미, 호출 맥락, entrypoint TCCT는 아직 검토하지 않았다.",
        "",
        "## 검증",
        "",
    ]
    checks = result.get("checks")
    if checks:
        for name, row in checks["commands"].items():
            lines.append(f"- `{name}`: exit {row['exit_code']}")
    else:
        lines.append("- 최종 필수 검사는 아직 기록되지 않음")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    result = load_summary()
    atomic_json(OUTPUT_JSON, result)
    temporary = OUTPUT_MD.with_suffix(".md.tmp")
    temporary.write_text(render_markdown(result))
    os.replace(temporary, OUTPUT_MD)
    print(json.dumps({"json": OUTPUT_JSON.relative_to(ROOT).as_posix(),
                      "json_sha256": sha256(OUTPUT_JSON),
                      "markdown": OUTPUT_MD.relative_to(ROOT).as_posix(),
                      "markdown_sha256": sha256(OUTPUT_MD),
                      "method_rows": len(result["methods"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
