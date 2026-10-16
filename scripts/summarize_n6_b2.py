#!/usr/bin/env python3
"""Summarize N6-B2 execution metadata without opening candidate contents."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from statistics import median


ROOT = Path(__file__).resolve().parents[1]
BASE = Path("runs/n6-b2-2026-10-09.noindex")
EXECUTE = BASE / "b-execute.noindex"
QUEUE = BASE / "pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json"
OUTPUT_JSON = EXECUTE.parent / "b-execute-summary.json"
OUTPUT_MD = Path("docs/n6_b2_execute_results_2026-10-12.md")
GATE_NAMES = (
    "prestart-gate-20261011T031337Z",
    "prestart-gate-20261011T032536Z",
)
PANIC = re.compile(r"panicked at (?P<location>[^\n]+?:\d+):\d+:\s*\n(?P<message>[^\n]+)")


def source(path: Path) -> dict:
    digest = hashlib.sha256()
    with (ROOT / path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": path.as_posix(), "sha256": digest.hexdigest()}


def read_json(path: Path) -> dict:
    return json.loads((ROOT / path).read_text())


def selected_run(state_unit: dict) -> dict:
    runs = state_unit["runs"]
    selected = [row for row in runs if row["run_number"] == state_unit["selected_run_number"]]
    if len(selected) != 1:
        raise ValueError("unit has no unique selected run")
    return selected[0]


def classify_stderr(ledger_path: Path, attempt: dict) -> tuple[str, str, dict]:
    relative = Path(attempt["stderr_path"])
    path = (ledger_path.parent / relative).resolve()
    if not path.is_relative_to((ROOT / EXECUTE).resolve()):
        raise ValueError(f"stderr outside execution tree: {path}")
    contents = path.read_text(errors="replace")
    match = PANIC.search(contents)
    if match is None:
        raise ValueError(f"engine_nonzero stderr has no recognized panic: {path}")
    location, message = match.group("location", "message")
    expected = {
        ("src/executor/symbolic_execution.rs:2391", "no entry found for key"):
            "symbolic_execution_missing_key",
        ("src/mutator/utils.rs:522",
         "not yet implemented: Support nested-arrays for template parameters"):
            "nested_array_template_parameter_unsupported",
    }
    category = expected.get((location, message))
    if category is None:
        raise ValueError(f"unrecognized engine panic at {location}: {message}")
    return category, location, source(path.relative_to(ROOT))


def load_host_health(path: Path) -> dict:
    samples = 0
    ac = Counter()
    thermal = Counter()
    levels = []
    swaps = []
    error_rows = 0
    first = last = None
    with (ROOT / path).open() as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            samples += 1
            first = first or row["sampled_at"]
            last = row["sampled_at"]
            if row.get("errors"):
                error_rows += 1
            if isinstance(row.get("memorystatus_level"), int):
                levels.append(row["memorystatus_level"])
            if isinstance(row.get("swap_used_bytes"), int):
                swaps.append(row["swap_used_bytes"])
            if "ac_power" in row:
                ac[str(row["ac_power"]).lower()] += 1
            if isinstance(row.get("thermal"), dict):
                thermal[str(row["thermal"].get("warning")).lower()] += 1
    if not samples:
        raise ValueError("no host-health samples")
    return {
        "sample_count": samples, "first_sampled_at": first, "last_sampled_at": last,
        "sample_error_rows": error_rows,
        "memorystatus_level_min": min(levels), "memorystatus_level_max": max(levels),
        "swap_used_bytes_first": swaps[0], "swap_used_bytes_last": swaps[-1],
        "swap_used_bytes_min": min(swaps), "swap_used_bytes_max": max(swaps),
        "ac_power_sample_counts": dict(sorted(ac.items())),
        "thermal_warning_sample_counts": dict(sorted(thermal.items())),
    }


def load_waits(path: Path) -> dict:
    reasons = Counter()
    units = set()
    count = 0
    with (ROOT / path).open() as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            count += 1
            units.add(row["unit_id"])
            reasons.update(row["reasons"])
    return {"sample_count": count, "unit_count": len(units),
            "reason_counts": dict(sorted(reasons.items()))}


def gate_record(name: str) -> dict:
    outer_path = BASE / "gates" / f"{name}.json"
    inner_path = BASE / "gates" / name / "start-gate.json"
    outer = read_json(outer_path)
    inner = read_json(inner_path)
    false_checks = sorted(key for key, value in outer["checks"].items() if not value)
    if outer["status"] != inner["status"] or outer["host_start_gate"]["status"] != inner["status"]:
        raise ValueError(f"gate status mismatch: {name}")
    battery = re.search(r"(\d+)%", inner["ac_power_raw"])
    return {
        "name": name, "status": outer["status"], "false_checks": false_checks,
        "host_start_gate_checks": inner["checks"],
        "power_source": "AC" if "Now drawing from 'AC Power'" in inner["ac_power_raw"] else "battery",
        "battery_percent": int(battery.group(1)) if battery else None,
        "recorded_at": outer["recorded_at"],
        "outer": source(outer_path), "host_start_gate": source(inner_path),
    }


def summarize() -> dict:
    state_path = EXECUTE / "state.json"
    state = read_json(state_path)
    queue = read_json(QUEUE)
    if state["status"] != "completed" or state["queue_sha256"] != source(QUEUE)["sha256"]:
        raise ValueError("execution state is incomplete or queue hash differs")
    units = queue["units"]
    if len(units) != 30 or len(state["units"]) != 30 or len(state["actual_start_order"]) != 30:
        raise ValueError("expected exactly 30 B execution units")
    if {row["unit_id"] for row in units} != set(state["units"]):
        raise ValueError("queue/state unit IDs differ")

    gates = [gate_record(name) for name in GATE_NAMES]
    if gates[0]["status"] != "failed" or gates[0]["false_checks"] != ["host_start_gate"]:
        raise ValueError("first gate discrepancy")
    if gates[1]["status"] != "passed" or gates[1]["false_checks"]:
        raise ValueError("second gate discrepancy")
    if datetime.fromisoformat(state["created_at"]) <= datetime.fromisoformat(gates[1]["recorded_at"]):
        raise ValueError("execution state predates passed gate")

    classifications: dict[str, dict] = {}
    unit_rows = []
    by_method = {method: {"outcomes": Counter(), "terminations": Counter(),
                          "attempt_count": 0, "process_start_count": 0,
                          "candidate_attempt_count": 0, "candidate_file_count": 0,
                          "candidate_unit_count": 0, "peak_physical_bytes": 0,
                          "campaign_wall_seconds_sum": 0.0}
                 for method in ("W", "S")}
    for unit in units:
        unit_id = unit["unit_id"]
        state_unit = state["units"][unit_id]
        selected = selected_run(state_unit)
        if state_unit["status"] != "completed_unpressured" or selected["run_kind"] != "primary":
            raise ValueError(f"unexpected unit status: {unit_id}")
        environment = selected["environment"]
        if environment["environment_pressure"]:
            raise ValueError(f"selected run under pressure: {unit_id}")
        unit_row = {
            "unit_id": unit_id, "repository": unit["repository"],
            "identifier": unit["identifier"], "seed": unit["seed"],
            "status": state_unit["status"], "run_count": len(state_unit["runs"]),
            "selected_run_number": selected["run_number"],
            "gate_wait_seconds": selected["gate_wait_seconds"],
            "environment": environment, "methods": {},
        }
        for method in ("W", "S"):
            run_result = selected["methods"][method]
            if run_result["status"] != "completed" or run_result["exit_code"] != 0:
                raise ValueError(f"selected method not successful: {unit_id} {method}")
            ledger_path = Path(run_result["ledger"])
            ledger_source = source(ledger_path)
            if ledger_source["sha256"] != run_result["ledger_sha256"]:
                raise ValueError(f"ledger hash changed: {ledger_path}")
            ledger = read_json(ledger_path)
            if ledger["status"] != "completed":
                raise ValueError(f"ledger not completed: {ledger_path}")
            attempts = ledger["attempts"]
            outcomes = Counter(attempt["outcome"] for attempt in attempts)
            if dict(outcomes) != ledger["outcome_counts"]:
                raise ValueError(f"outcome count differs: {ledger_path}")
            candidate_attempts = sum(bool(attempt.get("candidates")) for attempt in attempts)
            candidate_files = sum(len(attempt.get("candidates", [])) for attempt in attempts)
            if candidate_attempts != outcomes["candidate"]:
                raise ValueError(f"candidate outcome differs: {ledger_path}")
            for attempt in attempts:
                if attempt["outcome"] != "engine_nonzero":
                    continue
                category, location, stderr_source = classify_stderr(ledger_path, attempt)
                group = classifications.setdefault(category, {
                    "location": location, "message": None, "count": 0,
                    "by_method": Counter(), "repositories": set(), "identifiers": set(),
                    "example_stderr": stderr_source,
                })
                group["count"] += 1
                group["by_method"][method] += 1
                group["repositories"].add(unit["repository"])
                group["identifiers"].add(unit["identifier"])
            physical = ledger["aggregate_process_tree_peak_physical_memory_bytes"]
            row = {
                "status": ledger["status"], "runner_exit_code": run_result["exit_code"],
                "termination_reason": ledger["termination_reason"],
                "campaign_wall_seconds": ledger["campaign_wall_seconds"],
                "attempt_count": len(attempts),
                "process_start_count": sum(bool(a["process_started"]) for a in attempts),
                "outcome_counts": dict(sorted(outcomes.items())),
                "candidate_attempt_count": candidate_attempts,
                "candidate_file_count": candidate_files,
                "peak_physical_memory_bytes": physical,
                "peak_rss_bytes": ledger["aggregate_process_tree_peak_rss_bytes"],
                "ledger": ledger_source,
            }
            if method == "W" and outcomes["engine_nonzero"] and not outcomes["no_candidate"]:
                started = [a["process_wall_seconds"] for a in attempts
                           if a["outcome"] == "engine_nonzero" and a["process_wall_seconds"] is not None]
                row["engine_nonzero_process_wall_seconds_median"] = median(started)
                row["engine_nonzero_process_wall_seconds_min"] = min(started)
                row["engine_nonzero_process_wall_seconds_max"] = max(started)
            unit_row["methods"][method] = row
            aggregate = by_method[method]
            aggregate["outcomes"].update(outcomes)
            aggregate["terminations"][ledger["termination_reason"]] += 1
            aggregate["attempt_count"] += len(attempts)
            aggregate["process_start_count"] += row["process_start_count"]
            aggregate["candidate_attempt_count"] += candidate_attempts
            aggregate["candidate_file_count"] += candidate_files
            aggregate["candidate_unit_count"] += bool(candidate_attempts)
            aggregate["peak_physical_bytes"] = max(aggregate["peak_physical_bytes"], physical)
            aggregate["campaign_wall_seconds_sum"] += ledger["campaign_wall_seconds"]
        whole = unit_row["methods"]["W"]
        whole_outcomes = whole["outcome_counts"]
        if whole["candidate_attempt_count"]:
            raise ValueError(f"unexpected W candidate during zero-candidate classification: {unit_id}")
        mostly_panic = (whole["process_start_count"] > 0
                        and whole_outcomes.get("engine_nonzero", 0) >= 2
                        and whole_outcomes.get("engine_nonzero", 0)
                        / whole["process_start_count"] >= 0.9
                        and whole_outcomes.get("no_candidate", 0) == 0)
        unit_row["W_observation_class"] = (
            "execution_inoperable_panic" if mostly_panic else "no_candidate_observed"
        )
        unit_row["W_memory_cap_observed"] = bool(whole_outcomes.get("memory_cap", 0))
        unit_rows.append(unit_row)

    for method, aggregate in by_method.items():
        aggregate["outcome_counts"] = dict(sorted(aggregate.pop("outcomes").items()))
        aggregate["termination_reason_counts"] = dict(sorted(aggregate.pop("terminations").items()))
        aggregate["peak_physical_memory_bytes"] = aggregate.pop("peak_physical_bytes")
    for category, group in classifications.items():
        group["message"] = {
            "symbolic_execution_missing_key": "no entry found for key",
            "nested_array_template_parameter_unsupported":
                "not yet implemented: Support nested-arrays for template parameters",
        }[category]
        group["by_method"] = dict(sorted(group["by_method"].items()))
        group["repositories"] = sorted(group["repositories"])
        group["identifiers"] = sorted(group["identifiers"])

    wait_path = EXECUTE / "unit-gate-waits.jsonl"
    health_path = EXECUTE / "host-health.jsonl"
    execute_gate_path = EXECUTE / "start-gate.json"
    result = {
        "schema_version": 1, "task": "N6-B2 execute metadata summary",
        "candidate_contents_opened": False, "engine_rerun": False,
        "sources": {"queue": source(QUEUE), "state": source(state_path),
                    "host_health": source(health_path), "unit_gate_waits": source(wait_path),
                    "execute_start_gate": source(execute_gate_path)},
        "prestart_gates": gates,
        "execution_start_gate_status": read_json(execute_gate_path)["status"],
        "status": state["status"], "unit_count": len(unit_rows),
        "unit_status_counts": dict(sorted(Counter(u["status"] for u in unit_rows).items())),
        "W_observation_class_counts": dict(sorted(Counter(
            u["W_observation_class"] for u in unit_rows
        ).items())),
        "W_memory_cap_unit_count": sum(u["W_memory_cap_observed"] for u in unit_rows),
        "selected_run_count": len(unit_rows),
        "rerun_count": sum(u["run_count"] - 1 for u in unit_rows),
        "runner_exit_code_counts": dict(sorted(Counter(
            u["methods"][m]["runner_exit_code"] for u in unit_rows for m in ("W", "S")
        ).items())),
        "units": unit_rows, "methods": by_method,
        "engine_nonzero_classification": dict(sorted(classifications.items())),
        "engine_nonzero_stderr_checked": sum(x["count"] for x in classifications.values()),
        "gate_waits": {**load_waits(wait_path),
                       "selected_run_seconds_sum": sum(u["gate_wait_seconds"] for u in unit_rows),
                       "selected_run_seconds_max": max(u["gate_wait_seconds"] for u in unit_rows)},
        "host_health": load_host_health(health_path),
        "execution_window": {"started_at": state["created_at"],
                             "finished_at": state["updated_at"]},
    }
    if by_method["W"]["candidate_attempt_count"] != 0 or by_method["S"]["candidate_unit_count"] != 14:
        raise ValueError("candidate counts differ from lead's cross-check")
    if result["W_observation_class_counts"] != {
        "execution_inoperable_panic": 3, "no_candidate_observed": 27,
    } or result["W_memory_cap_unit_count"] != 6:
        raise ValueError("W display classes differ from lead's cross-check")
    if classifications["symbolic_execution_missing_key"]["by_method"] != {"S": 17, "W": 464}:
        raise ValueError("symbolic execution panic count differs from lead's cross-check")
    if classifications["nested_array_template_parameter_unsupported"]["by_method"] != {"S": 197}:
        raise ValueError("nested-array panic count differs from lead's cross-check")
    return result


def gib(value: int) -> str:
    return f"{value / 1024**3:.3f}"


def render_markdown(result: dict, json_hash: str) -> str:
    methods = result["methods"]
    waits = result["gate_waits"]
    host = result["host_health"]
    sources = result["sources"]
    lines = [
        "# N6-B2 B 본 실행 결과 (2026-10-12)", "",
        "- 담당: miiz", "- 상태: 메타데이터 집계 완료",
        "- 범위: 선택된 W·S ledger, 실행 상태, 시작 관문, 호스트 표본, 관문 대기, `engine_nonzero` stderr만 읽음. 후보 파일 내용은 열지 않았고 재실행·엔진 수정·판정 재분류는 하지 않음.",
        "- 해석: 후보 시도 수는 `ledger.attempts[].candidates`의 비어 있지 않은 항목 수다. 의미 검토나 맥락 판정 결과가 아니다.", "",
        "## 시작 관문과 완료 상태", "",
        "| 관문 | 결과 | 확인 내용 | 기록 |", "|---|---|---|---|",
    ]
    for gate in result["prestart_gates"]:
        detail = ("`host_start_gate`만 실패: AC 미연결, 배터리 85%. 실행기 시작 전 중단"
                  if gate["status"] == "failed" else "전체 통과: AC 연결, 배터리 85%")
        lines.append(f"| `{gate['name']}` | {gate['status']} | {detail} | `{gate['outer']['path']}` |")
    lines += [
        "", f"두 번째 관문 통과 뒤 실행 상태가 생성됐다. 실행기 시작 관문도 `{result['execution_start_gate_status']}`다.",
        f"30/30단위 `{next(iter(result['unit_status_counts']))}`, 선택 run 30개, 재실행 {result['rerun_count']}개, W·S 실행기 종료 코드 0은 60/60건이다.",
        f"실행 창(UTC): {result['execution_window']['started_at']} ~ {result['execution_window']['finished_at']}.", "",
        "## W·S 집계", "",
        "| 방식 | 종료 사유 | 시도 | outcome_counts | 후보 시도/파일 | 후보 단위 | 최대 동시 물리 메모리 |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for method in ("W", "S"):
        row = methods[method]
        outcomes = ", ".join(f"{key} {value}" for key, value in row["outcome_counts"].items())
        terms = ", ".join(f"{key} {value}" for key, value in row["termination_reason_counts"].items())
        lines.append(f"| {method} | {terms} | {row['attempt_count']} | {outcomes} | "
                     f"{row['candidate_attempt_count']}/{row['candidate_file_count']} | "
                     f"{row['candidate_unit_count']} | {gib(row['peak_physical_memory_bytes'])} GiB |")
    lines += [
        "", "W의 후보 0/30단위 중 rarimo 3단위는 `engine_nonzero` panic이 모든 정상 시작 시도의 거의 전부를 차지해 표에서 실행 불가로 표시한다. 나머지 27단위는 후보 0으로 표시하며, 그중 Vota·anon-aadhaar 6단위는 W `memory_cap`이 있었다. 이는 원시 outcome이나 종료 사유를 재분류한 값이 아닌 관측 설명이다. S의 후보 단위는 14/30이다.",
        "", "## 단위별 상태", "",
        "| 저장소·식별자 | seed | 상태 | W 관측 | W 시도 / memory_cap / panic | S 시도 / 후보 시도 | W/S 최대 물리 메모리 GiB |",
        "|---|---:|---|---|---:|---:|---:|",
    ]
    for unit in result["units"]:
        w, s = unit["methods"]["W"], unit["methods"]["S"]
        w_counts = w["outcome_counts"]
        w_class = ("실행 불가" if unit["W_observation_class"] == "execution_inoperable_panic"
                   else "후보 0")
        if unit["W_memory_cap_observed"]:
            w_class += " (`memory_cap` 관측)"
        lines.append(f"| {unit['repository']} `{unit['identifier'][:8]}` | {unit['seed']} | "
                     f"{unit['status']} | {w_class} | "
                     f"{w['attempt_count']} / {w_counts.get('memory_cap', 0)} / "
                     f"{w_counts.get('engine_nonzero', 0)} | {s['attempt_count']} / "
                     f"{s['candidate_attempt_count']} | {gib(w['peak_physical_memory_bytes'])} / "
                     f"{gib(s['peak_physical_memory_bytes'])} |")
    lines += ["", "## panic 분류", "",
              "`engine_nonzero` stderr 678개를 열어 panic 위치와 메시지로 분류했다. 후보 내용은 읽지 않았다.", "",
              "| 위치·메시지 | W | S | 범위 |", "|---|---:|---:|---|"]
    for group in result["engine_nonzero_classification"].values():
        repositories = f"{len(group['identifiers'])}개 대상 — " + ", ".join(group["repositories"])
        lines.append(f"| `{group['location']}` — {group['message']} | "
                     f"{group['by_method'].get('W', 0)} | {group['by_method'].get('S', 0)} | "
                     f"{repositories} |")
    lines += ["", "중첩 배열 panic의 9개 대상은 8개 저장소에 속한다. `iden3/circuits`에 서로 다른 식별자 2개가 있다."]
    rarimo = [u for u in result["units"] if u["identifier"].startswith("a8b2aa9c")]
    medians = [u["methods"]["W"]["engine_nonzero_process_wall_seconds_median"] for u in rarimo]
    lines += [
        "", f"rarimo W의 3개 seed별 panic 시도 중앙값은 {', '.join(f'{x:.2f}' for x in medians)}초다. 약 14초 뒤 매번 panic이 발생해 유효 탐색 시간이 사실상 0이었다. W의 `timeout` 또는 `deadline_before_spawn` 꼬리 시도까지 의미 있는 탐색 성공으로 해석하지 않는다.",
        "", "## 관문 대기와 호스트 표본", "",
        f"- 단위 시작 관문 대기 표본 {waits['sample_count']}개({waits['unit_count']}단위): "
        + ", ".join(f"`{k}` {v}" for k, v in waits["reason_counts"].items())
        + f". 선택 run의 관문 대기 합계 {waits['selected_run_seconds_sum']:.3f}초, 최대 {waits['selected_run_seconds_max']:.3f}초.",
        f"- 호스트 표본 {host['sample_count']}개, memorystatus 수준 {host['memorystatus_level_min']}~{host['memorystatus_level_max']}. 선택 run 30개 모두 압박 없음으로 판정됐다.",
        f"- AC 관측 {host['ac_power_sample_counts'].get('true', 0)}/{sum(host['ac_power_sample_counts'].values())}개가 연결 상태, 발열 경고 관측 {host['thermal_warning_sample_counts'].get('true', 0)}/{sum(host['thermal_warning_sample_counts'].values())}개. AC·발열은 모든 표본에 포함되지 않았다.",
        f"- 스왑 사용량 첫/끝 {gib(host['swap_used_bytes_first'])}/{gib(host['swap_used_bytes_last'])} GiB, 관측 범위 {gib(host['swap_used_bytes_min'])}~{gib(host['swap_used_bytes_max'])} GiB. 표본 오류 행 {host['sample_error_rows']}개.",
        "", "## 재현 근거", "",
        f"집계 JSON: `{OUTPUT_JSON.as_posix()}` (SHA-256 `{json_hash}`). "
        f"집계 스크립트: `scripts/summarize_n6_b2.py` (SHA-256 "
        f"`{source(Path('scripts/summarize_n6_b2.py'))['sha256']}`).",
        "", "| 입력 | SHA-256 |", "|---|---|",
    ]
    for name, row in sources.items():
        lines.append(f"| `{name}` — `{row['path']}` | `{row['sha256']}` |")
    lines += ["", "각 60개 ledger의 경로와 SHA-256은 집계 JSON의 단위별 W·S 행에 있다. 두 시작 관문의 파일 해시는 JSON의 `prestart_gates`에 있다.", ""]
    return "\n".join(lines)


def main() -> None:
    result = summarize()
    json_path = ROOT / OUTPUT_JSON
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    json_hash = source(OUTPUT_JSON)["sha256"]
    (ROOT / OUTPUT_MD).write_text(render_markdown(result, json_hash))
    print(json.dumps({"summary": OUTPUT_JSON.as_posix(), "summary_sha256": json_hash,
                      "report": OUTPUT_MD.as_posix(), "report_sha256": source(OUTPUT_MD)["sha256"],
                      "W_candidate_attempts": result["methods"]["W"]["candidate_attempt_count"],
                      "S_candidate_units": result["methods"]["S"]["candidate_unit_count"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
