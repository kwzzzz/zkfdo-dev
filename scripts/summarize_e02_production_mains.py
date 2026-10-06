#!/usr/bin/env python3
"""Summarize E-02 metadata after measurement and cleanup; contains no circuit values."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
import mmap
from pathlib import Path
import re
from statistics import median


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/e02-production-mains-2026-10-05"
INVENTORY = RUN / "entrypoint-roles-and-paths-v2.json"
LOCK = RUN / "procedure-lock-v6.json"
OUT_JSON = ROOT / "docs/e02_production_mains_results_2026-10-05.json"
OUT_MD = ROOT / "docs/e02_production_mains_results_2026-10-05.md"


def read(path):
    return json.loads(Path(path).read_text())


def reference(path):
    import hashlib
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve().relative_to(ROOT)), "sha256": digest.hexdigest()}


def assert_no_absolute_paths(value):
    """Fail closed on absolute paths, including paths embedded in command text."""
    if isinstance(value, dict):
        for key, child in value.items():
            assert_no_absolute_paths(key)
            assert_no_absolute_paths(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_absolute_paths(child)
    elif isinstance(value, str):
        # A URL is not a local file path; file:// is intentionally not exempted.
        without_urls = re.sub(r'https?://[^\s]+', '', value)
        if value.strip() == "/" or "file://" in value or re.search(
                r'''(?:^|[\s"'=(:])(?:/[^\s]|[A-Za-z]:[\\/]|\\\\)''', without_urls):
            raise ValueError("absolute path remains in shared result")


def repository_relative(value):
    """Normalize only this checkout; unknown external roots must not be hidden."""
    if isinstance(value, dict):
        result = {repository_relative(key): repository_relative(child)
                  for key, child in value.items()}
        if len(result) != len(value):
            raise ValueError("path normalization would merge dictionary keys")
    elif isinstance(value, list):
        result = [repository_relative(child) for child in value]
    elif isinstance(value, str):
        result = "." if value == str(ROOT) else value.replace(str(ROOT) + "/", "")
    else:
        result = value
    assert_no_absolute_paths(result)
    return result


def capture_compile_metadata(path):
    """Read only unique metadata keys of the pinned capture schema, without loading arrays.

    Ambiguous/absent keys fail rather than selecting a nested or guessed value.
    Memory mapping and bounded decoding keep large parameter arrays out of Python objects.
    """
    keys = ("schema", "status", "compile", "compile_seconds", "compile_attempts")
    pattern = re.compile(rb'"(' + b"|".join(k.encode() for k in keys) + rb')"\s*:')
    found = {}
    with Path(path).open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for match in pattern.finditer(data):
            key = match[1].decode()
            if key in found:
                raise ValueError("ambiguous capture metadata key: " + key)
            found[key] = json.JSONDecoder().raw_decode(
                data[match.end():match.end() + 65536].decode().lstrip())[0]
    if set(found) != set(keys) or found["schema"] != "zkfdo-instance-capture-v1":
        raise ValueError("missing metadata or unsupported capture schema")
    return found


def timeout_analysis(preparations):
    rows = []
    for identifier, result in sorted(preparations.items()):
        if result.get("discovery", {}).get("status") != "timeout":
            continue
        folder = RUN / "preparation-measurements" / identifier
        captures = list(folder.glob("discovery/*/instance-capture.json"))
        if len(captures) != 1:
            raise ValueError("missing or ambiguous timeout capture: " + identifier)
        capture = captures[0]
        metadata = capture_compile_metadata(capture)
        compile_record = metadata["compile"] or {}
        if metadata["status"] != "captured" or not compile_record.get("success"):
            raise ValueError("timeout did not follow successful capture: " + identifier)
        wrappers = sorted((capture.parent / "wrappers").glob("*/target.circom"))
        logs = [p.parent / "circom.stdout.log" for p in wrappers
                if (p.parent / "circom.stdout.log").is_file()]
        rows.append({"identifier": identifier, "repository": result["repository"],
                     "entrypoint_key": result["entrypoint_key"],
                     "result": reference(folder / "result.json"),
                     "instance_capture": reference(capture), "capture_status": metadata["status"],
                     "capture_compile_seconds": metadata["compile_seconds"],
                     "capture_compile_attempts": metadata["compile_attempts"],
                     "last_capture_compile_seconds": compile_record["elapsed_seconds"],
                     "capture_finished_at": compile_record["finished_at"],
                     "discovery_finished_at": result["discovery"]["finished_at"],
                     "discovery_elapsed_seconds": result["discovery"]["elapsed_seconds"],
                     "generated_wrappers": len(wrappers),
                     "wrapper_compiler_log_count": len(logs)})
    return {"count": len(rows), "wrapper_count_definition":
            "Retained wrappers/*/target.circom count at timeout; not completed or successful compilations, nor a complete planned denominator.",
            "capture_time_definition": "compile_seconds: sum of diagnostic capture compilation attempts, excluding scan/read/assembly.",
            "rows": rows}


def partial_analysis(preparations):
    rows = []
    for identifier, result in sorted(preparations.items()):
        outcome = result.get("preparation_outcome") or {}
        if outcome.get("status") != "partial":
            continue
        units = outcome["unit_outcomes"]
        roots = [u for u in units if u["label"] == "root"]
        fragments = [u for u in units if u["label"] != "root"]
        if (len(roots) != 1 or not fragments or len(units) != outcome["expected_units"]
                or len({u["label"] for u in units}) != len(units)):
            raise ValueError("incomplete or ambiguous partial denominator: " + identifier)
        valid = sum(u["verified_prepared"] is True for u in fragments)
        rows.append({"identifier": identifier, "repository": result["repository"],
                     "entrypoint_key": result["entrypoint_key"],
                     "fragment_units": len(fragments), "verified_valid_fragments": valid,
                     "valid_fragment_ratio": valid / len(fragments),
                     "root_verified_prepared": roots[0]["verified_prepared"],
                     "root_reason_codes": roots[0]["reason_codes"],
                     "incomplete_evidence": outcome["incomplete_evidence"]})
    ratios = [row["valid_fragment_ratio"] for row in rows]
    return {"count": len(rows), "ratio_definition":
            "Per-entrypoint verified_prepared non-root units / all non-root unit_outcomes; unweighted entrypoint statistics.",
            "median": median(ratios) if ratios else None,
            "min": min(ratios, default=None), "max": max(ratios, default=None),
            "root_not_prepared": sum(row["root_verified_prepared"] is False for row in rows),
            "rows": rows}


def counter(values):
    return dict(sorted(Counter(values).items()))


def load_context(preparations):
    path = RUN / "host-load-samples-2026-10-06.jsonl"
    samples = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                sample = json.loads(line)
                samples.append((datetime.fromisoformat(sample["sampled_at"]), sample))
            except (ValueError, KeyError):
                continue
    checks_path = RUN / "checks-2026-10-06/results.json"
    checks = read(checks_path).get("records", []) if checks_path.exists() else []
    heavy = []
    for row in checks:
        if row["argv"][:2] not in (["cargo", "test"], ["cargo", "clippy"]):
            continue
        start = datetime.fromisoformat(row["started_at"])
        end = start + timedelta(seconds=row["elapsed_seconds"])
        heavy.append({"argv": row["argv"], "started_at": start.isoformat(),
                      "finished_at": end.isoformat(), "log": row["log"]})
    rows = []
    for identifier, result in sorted(preparations.items()):
        stage = result.get("prepare_300") or {}
        if stage.get("status") != "timeout":
            continue
        start_text, end_text = stage.get("started_at"), stage.get("finished_at")
        start = datetime.fromisoformat(start_text) if start_text else None
        end = datetime.fromisoformat(end_text) if end_text else None
        window = [(t, s) for t, s in samples if start and end and start <= t <= end]
        nearest = min(samples, key=lambda pair: abs((pair[0] - end).total_seconds())) if end and samples else None
        near = nearest if nearest and abs((nearest[0] - end).total_seconds()) <= 30 else None
        overlapping = [row for row in heavy if start and end
                       and datetime.fromisoformat(row["started_at"]) < end
                       and datetime.fromisoformat(row["finished_at"]) > start]
        rows.append({"identifier": identifier, "repository": result["repository"],
                     "entrypoint_key": result["entrypoint_key"], "started_at": start_text,
                     "finished_at": end_text, "cap_seconds": 300,
                     "elapsed_seconds": stage.get("elapsed_seconds"),
                     "load_near_finish": near[1] if near else None,
                     "load_sample_delta_seconds": (near[0] - end).total_seconds() if near else None,
                     "load_unknown_reason": None if near else "no_observed_sample_within_30_seconds_of_finish",
                     "interval_samples": len(window),
                     "interval_max_load_1m": max((s["load_average_1_5_15_minutes"][0] for _, s in window), default=None),
                     "sampling_covers_whole_interval": bool(start and end and samples and samples[0][0] <= start and samples[-1][0] >= end),
                     "overlapping_heavy_checks": overlapping})
    return {"sample_record": reference(path) if path.exists() else None,
            "sampling_started_at": samples[0][1]["sampled_at"] if samples else None,
            "sample_interval_seconds": 10, "host_scope": "whole host load average, not per-process CPU",
            "historical_load_before_sampling": "unknown; no retrospective reconstruction",
            "heavy_checks": heavy, "prepare_300_timeouts": rows}


def chosen_compile(result, sensitivity=None):
    for name in ("compile_120", "compile_600"):
        if result.get(name, {}).get("status") == "success":
            return name, result[name]
    if sensitivity and sensitivity.get("compile_600", {}).get("status") == "success":
        return "compile_600_sensitivity", sensitivity["compile_600"]
    if result["e01_compile"]["status"] == "success":
        return "e01_reused", result["e01_compile"]
    return None, None


def preparation_status(result):
    outcome = result.get("preparation_outcome") or {}
    if outcome.get("status"):
        return outcome["status"], "preparation_outcome"
    for name in ("prepare_900", "prepare_300"):
        row = result.get(name, {})
        if row.get("status") == "success":
            return "unknown", name + "_without_verified_outcome"
    discovery_status = result.get("discovery", {}).get("status")
    if discovery_status not in {None, "success"}:
        return discovery_status, "discovery"
    if result.get("prepare_900", {}).get("status") not in {None, "not_started"}:
        return result["prepare_900"]["status"], "prepare_900"
    return result.get("prepare_300", {}).get("status", "not_started"), "prepare_300"


def remaining_reason(measured, prep, compiled, cap600):
    if prep:
        outcome = prep.get("preparation_outcome") or {}
        if outcome.get("status") == "success":
            return None
        if outcome.get("failure_type"):
            return outcome["failure_type"]
        for name in ("discovery", "prepare_900", "prepare_300", "plan"):
            stage = prep.get(name) or {}
            if stage.get("status") not in {None, "success", "not_started"}:
                return name + "_" + (stage.get("failure_type") or stage["status"])
        if prep.get("preparation_reason"):
            return "manifest_generation_failed"
        return "preparation_verification_incomplete"
    if compiled is None:
        return measured.get("reason") or cap600.get("failure_type") or cap600.get("status")
    return None


def build():
    inventory = read(INVENTORY)
    lock = read(LOCK)
    entries = inventory["entries"]
    deployments = {row["identifier"]: row for row in entries if row["role"] == "deployment_main"}
    compile_paths = sorted(RUN.glob("compile-measurements/*/result.json"))
    compile_results = {read(path)["identifier"]: read(path) for path in compile_paths}
    if set(compile_results) != set(deployments):
        missing = sorted(set(deployments) - set(compile_results))
        raise RuntimeError(f"deployment compile denominator incomplete: {len(compile_results)}/{len(deployments)}; missing={missing[:3]}")
    prep_paths = sorted(RUN.glob("preparation-measurements/*/result.json"))
    prep_results = {read(path)["identifier"]: read(path) for path in prep_paths}
    sensitivity_paths = sorted(RUN.glob("compile-600-sensitivity/*/result.json"))
    sensitivity_results = {read(path)["identifier"]: read(path) for path in sensitivity_paths}
    selection = read(RUN / "preparation-selection.json")
    expected_prep = {row["identifier"] for row in selection["entries"]}
    if set(prep_results) != expected_prep:
        raise RuntimeError(f"preparation denominator incomplete: {len(prep_results)}/{len(expected_prep)}")

    per_repo = []
    for repository in sorted({row["repository"] for row in entries}):
        all_rows = [row for row in entries if row["repository"] == repository]
        deploy = [row for row in all_rows if row["role"] == "deployment_main"]
        comp = [compile_results[row["identifier"]] for row in deploy]
        prep = [prep_results[row["identifier"]] for row in deploy if row["identifier"] in prep_results]
        per_repo.append({
            "repository": repository, "entrypoints": len(all_rows),
            "deployment_main": len(deploy), "test_mock_harness": len(all_rows) - len(deploy),
            "environment_reuse": counter(row["environment_reuse"] for row in deploy),
            "e01_compile": counter(row["e01_compile"]["status"] for row in deploy),
            "e01_failure_types": counter(row["e01_compile"].get("failure_type") or "none" for row in deploy),
            "e01_preparation": counter((row.get("e01_preparation") or {}).get("status", "not_started") for row in deploy),
            "e02_compile_120": counter(row["compile_120"]["status"] for row in comp),
            "e02_compile_600": counter((sensitivity_results.get(row["identifier"], row)
                                         ["compile_600"]["status"]) for row in comp),
            "new_compile_successes": sum(chosen_compile(
                row, read(RUN / "compile-600-sensitivity" / row["identifier"] / "result.json")
                if (RUN / "compile-600-sensitivity" / row["identifier"] / "result.json").is_file() else None
            )[0] in {"compile_120", "compile_600", "compile_600_sensitivity"} for row in comp),
            "preparation_measured": len(prep),
            "preparation_final": counter(preparation_status(row)[0] for row in prep),
        })

    detailed = []
    large = []
    for identifier, row in sorted(deployments.items()):
        measured = compile_results[identifier]
        sensitivity_path = RUN / "compile-600-sensitivity" / identifier / "result.json"
        sensitivity = read(sensitivity_path) if sensitivity_path.is_file() else None
        source, compiled = chosen_compile(measured, sensitivity)
        cap600 = sensitivity["compile_600"] if sensitivity else measured["compile_600"]
        constraints = compiled.get("constraints") if compiled else None
        prep = prep_results.get(identifier)
        detail = {
            "identifier": identifier, "repository": row["repository"],
            "commit_sha": row["commit_sha"], "entrypoint_key": row["entrypoint_key"],
            "entrypoint": row["entrypoint"], "environment_reuse": row["environment_reuse"],
            "role": row["role"], "role_reasons": row["role_reasons"],
            "e01_preparation_status": (row.get("e01_preparation") or {}).get("status", "not_started"),
            "e01_preparation_failure_type": (row.get("e01_preparation") or {}).get("failure_type"),
            "e01_compile_status": row["e01_compile"]["status"],
            "e01_compile_failure_type": row["e01_compile"].get("failure_type"),
            "e02_compile_120_status": measured["compile_120"]["status"],
            "e02_compile_120_failure_type": measured["compile_120"].get("failure_type"),
            "e02_compile_600_status": cap600["status"],
            "e02_compile_600_failure_type": cap600.get("failure_type"),
            "constraint_source": source, "constraints": constraints,
            "applied_library_paths": row["library_paths"],
            "derived_library_evidence": row["derived_library_evidence"],
            "build_references": row["build_references"],
            "compile_result": reference(RUN / "compile-measurements" / identifier / "result.json"),
            "preparation_selection_reason": prep.get("selection_reason") if prep else None,
            "discovery_status": prep.get("discovery", {}).get("status") if prep else "not_measured",
            "prepare_300_status": prep.get("prepare_300", {}).get("status") if prep else "not_measured",
            "prepare_900_status": prep.get("prepare_900", {}).get("status") if prep else "not_measured",
            "plan_status": prep.get("plan", {}).get("status") if prep else "not_measured",
            "preparation_final_status": preparation_status(prep)[0] if prep else "not_measured",
            "preparation_failure_types": (prep.get("preparation_outcome") or {}).get("failure_types", []) if prep else [],
            "remaining_reason": remaining_reason(measured, prep, compiled, cap600),
        }
        if prep:
            detail["preparation_result"] = reference(RUN / "preparation-measurements" / identifier / "result.json")
            detail["instance_capture"] = prep.get("instance_capture") or {"status": "not_reported"}
            detail["callsites"] = prep.get("discovery", {}).get("callsites")
            detail["unique_compile_units"] = prep.get("discovery", {}).get("unique_compile_units")
            outcome = prep.get("preparation_outcome") or {}
            detail["expected_units"] = outcome.get("expected_units")
            detail["known_valid_units"] = outcome.get("known_valid_units")
            detail["incomplete_evidence"] = outcome.get("incomplete_evidence")
        detailed.append(detail)
        if constraints is not None and constraints >= 100_000:
            large.append(detail)

    stage_seconds = defaultdict(float)
    for row in compile_results.values():
        for stage in ("compile_120", "compile_600"):
            value = row.get(stage, {}).get("elapsed_seconds")
            if value is not None:
                stage_seconds[stage] += value
    for row in prep_results.values():
        for stage in ("discovery", "prepare_300", "prepare_900", "plan"):
            value = row.get(stage, {}).get("elapsed_seconds")
            if value is not None:
                stage_seconds[stage] += value
    for path in RUN.glob("compile-600-sensitivity/*/result.json"):
        row = read(path)
        # Avoid double-counting old-timeout results copied from the primary record.
        if row.get("reason") != "primary_record_already_contains_same_600_second_measurement":
            value = row.get("compile_600", {}).get("elapsed_seconds")
            if value is not None:
                stage_seconds["compile_600_sensitivity"] += value
    cleanup_path = RUN / "deleted-artifacts.json"
    cleanup = read(cleanup_path) if cleanup_path.exists() else {"status": "pending"}
    checks_path = RUN / "checks.json"
    checks = read(checks_path) if checks_path.exists() else {"status": "pending"}
    result = {
        "schema_version": 1, "task": "E-02", "owner": "miiz", "deadline": "2026-10-08",
        "status": "complete" if cleanup.get("status") == "complete" and checks.get("status") == "passed" else "measurement_complete",
        "zkfuzz_invocations": 0, "procedure": reference(ROOT / "docs/e02_production_mains_procedure_v2_2026-10-05.md"),
        "lock": reference(LOCK), "inventory": reference(INVENTORY),
        "scope": {"entrypoints": len(entries), **inventory["roles"],
                  "preparation_selection": len(expected_prep)},
        "repositories": per_repo, "deployment_entrypoints": detailed,
        "entrypoint_roles": [{key: row[key] for key in ("identifier", "repository", "entrypoint_key", "role", "role_reasons", "build_references")} for row in entries],
        "actual_compile_options": {"original": "--r1cs without explicit optimization flag; circom 2.2.3 default O1", "diagnostic_capture": "O0 as implemented by the pinned F-01 binary"},
        "procedure_deviations": ["실제 옵션은 E-01과 같은 기본 O1, 절차 문서의 O0는 표기 오류. 원본 명령·고정 절차는 보존하며 진단 캡처 O0와 구분한다."],
        "large_deployment_entrypoints": large, "large_threshold_constraints": 100_000,
        "cost_seconds_sum_of_stage_wall": dict(sorted(stage_seconds.items())),
        "measurement_load": load_context(prep_results),
        "cleanup": cleanup, "checks": checks,
        "discovery_timeout_analysis": timeout_analysis(prep_results),
        "partial_preparation_analysis": partial_analysis(prep_results),
        "claims": [
            "Results measure fixed-commit deployment-main compilation and structural preparation only.",
            "No zkFuzz search ran; results do not establish defect detection or semantic equivalence.",
            "Concurrent stage-wall sums are workload totals, not elapsed experiment wall time.",
        ],
    }
    correction_checks = RUN / "review-correction-2026-10-06/checks.json"
    if correction_checks.is_file():
        result["review_correction_checks"] = {"record": reference(correction_checks),
                                               "status": read(correction_checks)["status"]}
    return repository_relative(result)


def render(data):
    lines = [
        "# E-02 대형 배포 main 컴파일·준비 결과 (2026-10-05)", "",
        "담당: miiz. 상태: " + data["status"] + ". zkFuzz 실행: 0회.", "",
        "## 범위와 역할 분류", "",
        f"사전 고정한 경로 규칙으로 E-01의 {data['scope']['entrypoints']}개 entrypoint를 배포 main "
        f"{data['scope']['deployment_main']}개와 test/mock 하네스 {data['scope']['test_mock_harness']}개로 나눴다. "
        "모든 항목은 성공 여부와 무관하게 JSON 분모에 남겼다.", "",
        "| 저장소 | 전체 | 배포 main | test/mock | E-01 compile | E-02 120초 | E-02 600초 | 새 compile 성공 | E-01 준비 | E-02 준비 측정 | 최종 준비 |",
        "|---|---:|---:|---:|---|---|---|---:|---|---:|---|",
    ]
    for row in data["repositories"]:
        fmt = lambda value: ", ".join(f"{k} {v}" for k, v in value.items()) or "-"
        lines.append(f"| {row['repository']} | {row['entrypoints']} | {row['deployment_main']} | "
                     f"{row['test_mock_harness']} | {fmt(row['e01_compile'])} | {fmt(row['e02_compile_120'])} | "
                     f"{fmt(row['e02_compile_600'])} | {row['new_compile_successes']} | "
                     f"{fmt(row['e01_preparation'])} | {row['preparation_measured']} | {fmt(row['preparation_final'])} |")
    lines += ["", "실제 옵션은 E-01과 같은 기본 O1, 절차 문서의 O0는 표기 오류. "
              "고정 문서·원본 명령·로그는 그대로 보존했다. "
              "진단 캡처의 O0와 구분한다. 시간은 동시 실행 부하가 있는 관측값이다.", ""]
    timeout = data["discovery_timeout_analysis"]
    partial = data["partial_preparation_analysis"]
    capture_times = [row["capture_compile_seconds"] for row in timeout["rows"]]
    wrapper_counts = [row["generated_wrappers"] for row in timeout["rows"]]
    lines += ["## 검수 보완: discovery timeout과 부분 준비", "",
              "공유 JSON의 경로는 이 저장소 root 기준 상대 경로로 통일했다. 생성기는 미변환 절대 경로가 "
              "남으면 출력 전에 실패한다. 원시 측정 기록·판정·고정 절차는 변경하지 않았다.", ""]
    if capture_times:
        lines += [f"discovery timeout {timeout['count']}건 모두 `instance-capture.json`이 존재하고 "
                  f"캡처 상태가 `captured`이다. 캡처 컴파일은 {min(capture_times):.3f}–{max(capture_times):.3f}초에 "
                  "끝났으며, 이후 wrapper 생성·확인 컴파일 단계에서 discovery의 900초 예산을 소진했다. "
                  "캡처 실패나 원본 main 컴파일 실패로 해석하지 않는다. "
                  f"중단 시점에 남은 wrapper는 항목당 {min(wrapper_counts)}–{max(wrapper_counts)}개다. "
                  "이는 생성된 `wrappers/*/target.circom` 수이며 전체 예정 조각 수나 컴파일 성공 수가 아니다. "
                  "확인 컴파일 로그 수를 별도로 표시하며, 종료 직전 진행 중 컴파일은 로그가 남지 않을 수 있다. "
                  "900초에서 캡처 컴파일 합계를 뺀 시간을 순수 wrapper 컴파일 시간으로 간주하지 않는다 "
                  "(소스 스캔·캡처 읽기·조립·wrapper 생성 비용도 포함).", "",
                  "아래 캡처 시간은 `compile_seconds`의 재시도 합계이며 마지막 성공 시도 하나의 시간과 구분한다. "
                  "각 행의 원시 result·capture 경로와 SHA-256은 JSON의 `discovery_timeout_analysis.rows`에 있다. "
                  "최종 timeout 34건 중 나머지 1건(`e992d1360a21d0321cc229a9`)은 discovery 성공 후 "
                  "prepare 300/900초 모두 timeout으로, 이 discovery 표에 합치지 않는다.", "",
                  "| 저장소 | entrypoint | 캡처 compile 합계(초) | 캡처 시도 | 생성 wrapper | 확인 compile 로그 |",
                  "|---|---|---:|---:|---:|---:|"]
        for row in timeout["rows"]:
            lines.append(f"| {row['repository']} | `{row['entrypoint_key']}` | "
                         f"{row['capture_compile_seconds']:.3f} | {row['capture_compile_attempts']} | "
                         f"{row['generated_wrappers']} | {row['wrapper_compiler_log_count']} |")
    if partial["count"]:
        lines += ["", f"부분 준비 {partial['count']}건의 **조각 유효 비율은 중앙값 {partial['median']:.3%}, "
                  f"최소 {partial['min']:.3%}, 최대 {partial['max']:.3%}**다. "
                  "각 entrypoint의 `unit_outcomes`에서 root를 제외한 전체 조각을 분모로, "
                  "`verified_prepared=true`인 조각을 분자로 계산한 뒤 entrypoint별 비율을 동일 가중 집계했다. "
                  "후보 수·호출 위치 수나 단순 `reported_eligible` 비율이 아니다. "
                  f"**root 단위 준비 실패는 {partial['root_not_prepared']}/{partial['count']}건**이다. "
                  "조각 유효 비율 100%여도 root 실패 때문에 partial일 수 있다. "
                  "항목별 분자·분모·root 사유는 JSON의 `partial_preparation_analysis.rows`에 보존했다.", ""]
    lines += ["", "## 제약 10만 이상 배포 main", "",
              "prepare 300/900 열은 프로세스 종료 상태이다. 최종 준비 열은 보존된 보고서에서 재검증한 상태로, "
              "프로세스 success여도 일부 조각이나 원본 준비가 불완전하면 partial/failed일 수 있다.", "",
              "| 저장소 | entrypoint | 제약 | compile 근거 | 120초 | 600초 | discovery | prepare 300 | prepare 900 | plan | 최종 준비 | 남은 사유 |",
              "|---|---|---:|---|---|---|---|---|---|---|---|---|"]
    for row in data["large_deployment_entrypoints"]:
        lines.append(f"| {row['repository']} | `{row['entrypoint']}` | {row['constraints']} | "
                     f"{row['constraint_source']} | {row['e02_compile_120_status']} | "
                     f"{row['e02_compile_600_status']} | {row['discovery_status']} | "
                     f"{row['prepare_300_status']} | {row['prepare_900_status']} | {row['plan_status']} | {row['preparation_final_status']} | "
                     f"{row['remaining_reason'] or '-'} |")
    if not data["large_deployment_entrypoints"]:
        lines.append("| - | - | - | - | - | - | - | - | - | - | - | 측정된 10만 이상 항목 없음 |")
    lines += ["", "## 자동 라이브러리 경로", "",
              "`package.json`, 셸, circomkit, hardhat, Makefile 계열 파일의 literal `-l`/include만 정적으로 읽었다. "
              "설정 파일 디렉터리·가장 가까운 package root·저장소 root에 대해 실제로 존재하는 checkout 내부 디렉터리만 적용했다. "
              "entrypoint별 근거 파일·줄·literal·anchor와 적용 경로는 결과 JSON에 있다. 변수·glob·부재 경로는 추측하지 않았다.", "",
              "## 비용과 정리", ""]
    for stage, seconds in data["cost_seconds_sum_of_stage_wall"].items():
        lines.append(f"- {stage}: {seconds:.3f}초 (stage wall 합계)")
    cleanup = data["cleanup"]
    if cleanup.get("status") == "complete":
        lines.append(f"- 정리: {cleanup['deleted_files']}개, {cleanup['deleted_bytes']}바이트 삭제")
        lines.append(f"- 캡처 확인 부족으로 전체 보존한 항목: {len(cleanup.get('preserved_unverified_batches', []))}개. 근거는 정리 원장에 있다.")
    else:
        lines.append("- 정리: pending")
    lines += ["", "## 검사와 주장 한계", ""]
    load = data["measurement_load"]
    lines += ["측정 중 필수 검사는 1회 실행했고 반복하지 않았다. 전체 host load average는 "
              f"`{load['sampling_started_at']}`부터 10초 간격으로 관측했다. "
              "그 이전 부하는 unknown이며 이후 표본으로 소급하지 않았다. "
              "아래 값은 준비 timeout 종료 시각에서 ±30초 이내 가장 가까운 표본이며 인과관계나 CPU 사용률을 뜻하지 않는다.", "",
              "| 300초 timeout 항목 | 종료시각 UTC | 실측 초 | load 1/5/15분 | 표본 시각 차이(초) | 구간 내 최대 1분 load | 검사 중첩 |",
              "|---|---|---:|---|---:|---|---|"]
    for row in load["prepare_300_timeouts"]:
        sample = row["load_near_finish"]
        values = "/".join(f"{value:.2f}" for value in sample["load_average_1_5_15_minutes"]) if sample else "unknown"
        checks_overlap = ", ".join(" ".join(check["argv"]) for check in row["overlapping_heavy_checks"]) or "없음"
        lines.append(f"| `{row['identifier']}` | {row['finished_at']} | {row['elapsed_seconds']} | {values} | "
                     f"{row['load_sample_delta_seconds']} | {row['interval_max_load_1m']} | {checks_overlap} |")
    lines += [""]
    checks = data["checks"]
    if checks.get("status") == "passed":
        for name, value in checks.get("commands", {}).items():
            lines.append(f"- `{name}`: {value}")
    else:
        lines.append("- 필수 검사: pending")
    correction = data.get("review_correction_checks")
    if correction:
        lines += ["", f"2026-10-06 검수 보완 후 필수 검사: {correction['status']}. "
                  "`cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`의 "
                  f"추가 실행 기록은 `{correction['record']['path']}`에 있으며, 기존 측정 중 검사 기록과 분리했다."]
    lines += ["", "이 결과는 고정 commit의 배포 main compile과 구조적 준비 적용성만 측정한다. "
              "zkFuzz를 실행하지 않았고 결함 탐지 성능이나 일반적 의미 동등성을 입증하지 않는다.", ""]
    return "\n".join(lines)


def main():
    data = build()
    assert_no_absolute_paths(data)
    markdown = render(data)
    OUT_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    OUT_MD.write_text(markdown)
    print(json.dumps({"status": data["status"], "deployment": data["scope"]["deployment_main"],
                      "large": len(data["large_deployment_entrypoints"]),
                      "preparation": data["scope"]["preparation_selection"]}))


if __name__ == "__main__":
    main()
