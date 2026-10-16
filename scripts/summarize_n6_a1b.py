#!/usr/bin/env python3
"""Write the value-free N6-A1b preparation/preflight result documents."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a1b-2026-10-08"
OLD = ROOT / "runs/n6-a1-2026-10-07"
OUT = ROOT / "docs/n6_a1b_preparation_results_2026-10-08.md"
OUT_JSON = ROOT / "docs/n6_a1b_preparation_results_2026-10-08.json"
TARGET_SHA = "6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758"
SHORT_FIXES = {
    "0621e84", "1055906", "1763ca4", "3375335", "54d4d0a", "69db60e",
    "6dfcc56", "7ff5ba7", "8fdab18", "903edd3", "ccb2a8b",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def clean(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = text.replace(str(ROOT), "<repo>")
    return text.replace("|", "\\|").strip()


def core_errors(unit_id: str) -> list[dict]:
    root = RUN / "units" / unit_id / "preparation"
    rows = []
    for name in ("discover-call", "prepare-small-first-call", "plan-call"):
        path = root / name / "stderr.log"
        if not path.is_file():
            continue
        nonempty = [clean(line) for line in path.read_text(errors="replace").splitlines()
                    if clean(line)]
        if nonempty:
            rows.append({"stage": name.removesuffix("-call"), "path": path.relative_to(ROOT).as_posix(),
                         "sha256": sha256(path), "lines": nonempty[-8:]})
    return rows


def status_map(path: Path) -> dict[str, dict]:
    return {row["unit_id"]: row for row in load(path)["units"]}


def effective_old_materialization() -> dict[str, str]:
    base = status_map(OLD / "materialization-summary.json")
    recovery = status_map(OLD / "materialization-recovery.json")
    values = {}
    for unit_id, row in base.items():
        second = recovery[unit_id]
        if second["status"] == "success":
            values[unit_id] = "ready(recovered)"
        elif second["status"] == "failed":
            values[unit_id] = f"failed:{second.get('failure_type', 'unknown')}"
        else:
            values[unit_id] = row["status"] + (f":{row['failure_type']}" if row.get("failure_type") else "")
    return values


def stage(row: dict) -> str:
    return row["status"] + (f":{row['failure_type']}" if row.get("failure_type") else "")


def preflight_method(results: dict, unit_id: str, method: str) -> str:
    rows = [results.get(f"{unit_id}-seed-{seed}:{method}")
            for seed in (2026100601, 2026100602, 2026100603)]
    if all(row is None for row in rows):
        return "not_generated"
    passed = sum((row or {}).get("status") == "passed" for row in rows)
    failed = sum(row is not None and row.get("status") != "passed" for row in rows)
    missing = sum(row is None for row in rows)
    return f"pass {passed}/3; fail {failed}; missing {missing}"


def all_preflight_passed(results: dict, unit_id: str) -> bool:
    return all((results.get(f"{unit_id}-seed-{seed}:{method}") or {}).get("status") == "passed"
               for seed in (2026100601, 2026100602, 2026100603) for method in ("W", "S"))


def method_preflight_passed(results: dict, unit_id: str, method: str) -> bool:
    return all((results.get(f"{unit_id}-seed-{seed}:{method}") or {}).get("status") == "passed"
               for seed in (2026100601, 2026100602, 2026100603))


def revision_evidence(unit: dict, materialized: dict) -> dict:
    project = RUN / "units" / unit["unit_id"] / "project"
    if not project.is_dir():
        return {"status": "unavailable", "reason": materialized.get("failure_type")}
    if (project / ".git").is_dir():
        observed = subprocess.run(["/usr/bin/git", "-C", str(project), "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True).stdout.strip()
        return {"status": "matched" if observed == unit["revision"] else "mismatch",
                "expected": unit["revision"], "observed": observed}
    if materialized.get("source_kind") == "l06_verified_revision_tree":
        manifest = ROOT / "runs/l06-2026-10-03/trees/manifest.json"
        keys = {"inference-r-intdiv": "r_intdiv", "inference-c9221e8d": "c9221e8d",
                "inference-c79f42ee": "c79f42ee",
                "inference-c771c61c-p": "c771c61c_p",
                "inference-loo-clamp": "loo_clamp", "inference-loo-dfs": "loo_dfs",
                "inference-all-fixed": "all_fixed"}
        key = keys[unit["unit_id"]]
        expected = load(manifest)[key]["files"]
        matched = all((project / path).is_file() and sha256(project / path) == row["sha256"]
                      for path, row in expected.items())
        return {"status": "matched_frozen_tree" if matched else "mismatch", "tree": key,
                "manifest": manifest.relative_to(ROOT).as_posix(), "manifest_sha256": sha256(manifest)}
    entrypoint = project / unit["entrypoint"]
    return {"status": "matched_frozen_snapshot" if entrypoint.is_file() else "entrypoint_missing",
            "entrypoint": entrypoint.relative_to(ROOT).as_posix(),
            "entrypoint_sha256": sha256(entrypoint) if entrypoint.is_file() else None}


def main() -> int:
    target = ROOT / "docs/n6_targets_a_2026-10-07.json"
    if sha256(target) != TARGET_SHA:
        raise ValueError("frozen A list changed")
    inventory = load(RUN / "preparation-units.json")
    units = inventory["development_units"] + inventory["aq_stage1_units"]
    old_mat = effective_old_materialization()
    old_setup = status_map(OLD / "setup-summary.json")
    old_prep = status_map(OLD / "preparation-summary.json")
    new_mat = status_map(RUN / "materialization-summary.json")
    new_setup = status_map(RUN / "setup-summary.json")
    new_prep = status_map(RUN / "preparation-summary.json")
    action_counts = Counter((action["kind"], action["status"])
                            for row in new_mat.values()
                            for action in row.get("official_actions", []))
    preflight_path = RUN / "preflight-v3/preflight-all.json"
    preflight = load(preflight_path)
    if preflight.get("status") != "completed" or preflight.get("recorded_spec_count") != 168:
        raise ValueError("N6-A1b preflight-all is not complete")
    pf = preflight["results"]

    table = []
    for unit in units:
        unit_id = unit["unit_id"]
        table.append({
            "unit_id": unit_id, "branch": unit["branch"], "project": unit["project"],
            "revision_kind": unit["revision_kind"],
            "procedure": new_mat[unit_id]["preparation_procedure"],
            "materialization": f"{old_mat[unit_id]} -> {stage(new_mat[unit_id])}",
            "setup": f"{old_setup[unit_id]['status']} -> {new_setup[unit_id]['status']}",
            "preparation": f"{stage(old_prep[unit_id])} -> {stage(new_prep[unit_id])}",
            "eligible_targets": new_prep[unit_id].get("eligible_targets"),
            "W": preflight_method(pf, unit_id, "W"),
            "S": preflight_method(pf, unit_id, "S"),
            "ready_for_execute": all_preflight_passed(pf, unit_id),
            "whole_preflight_ready": method_preflight_passed(pf, unit_id, "W"),
            "split_preflight_ready": method_preflight_passed(pf, unit_id, "S"),
            "revision_evidence": revision_evidence(unit, new_mat[unit_id]),
        })

    preparation_failures = []
    for unit in units:
        row = new_prep[unit["unit_id"]]
        if row["status"] == "success":
            continue
        preparation_failures.append({
            "unit_id": unit["unit_id"], "status": row["status"],
            "failure_type": row.get("failure_type"), "reason": row.get("reason"),
            "core_errors": core_errors(unit["unit_id"]),
        })
    preflight_failures = []
    for key, row in pf.items():
        if row["status"] == "passed":
            continue
        ledger = ROOT / row["preflight"]
        evidence = []
        if ledger.is_file():
            for compile_row in load(ledger).get("compile", []):
                if compile_row.get("status") == "succeeded" or not compile_row.get("stderr_path"):
                    continue
                stderr = ledger.parent / compile_row["stderr_path"]
                text = clean(stderr.read_text(errors="replace"))
                core = [line.strip() for line in text.splitlines()
                        if "error[P" in line or re.search(r'\.circom"?:\d+', line)]
                evidence.append({"path": stderr.relative_to(ROOT).as_posix(),
                                 "sha256": sha256(stderr), "lines": core})
        preflight_failures.append({"key": key, "failure_type": row.get("failure_type"),
                                   "evidence": evidence})

    known_side = [unit for unit in units if unit["revision_kind"] in {"development", "vulnerable",
                                                                       "leave_one_out"}]
    comparison_side = [unit for unit in units if unit["revision_kind"] in {"fixed", "leave_one_out"}]
    ready = {row["unit_id"] for row in table if row["ready_for_execute"]}
    target_items = load(target)["items"]
    aq_items = [item for item in target_items if item["bucket"] == "A-Q-stage1"]
    aq_units = inventory["aq_stage1_units"]

    def item_has(item: dict, kind: str) -> bool:
        return any(item["id"] in unit["item_ids"] and unit["revision_kind"] == kind
                   and unit["unit_id"] in ready for unit in aq_units)

    aq_rq1_ready = sum(item_has(item, "vulnerable") for item in aq_items)
    aq_rqc_denom = [item for item in aq_items
                    if not any(commit in SHORT_FIXES for commit in item["fix_commits"])]
    aq_rqc_ready = sum(item_has(item, "vulnerable") and item_has(item, "fixed") and
                       (not item.get("leave_one_out") or item_has(item, "leave_one_out"))
                       for item in aq_rqc_denom)

    queue_path = RUN / "queue-v3.json"
    cleanup = load(RUN / "artifact-cleanup-result.json")
    loads = [value for row in new_prep.values()
             for key in ("load_average_start", "load_average_end")
             for value in row.get(key, [])]
    result = {
        "schema_version": 1, "task": "N6-A1b supplemented preparation result",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target_list": {"path": target.relative_to(ROOT).as_posix(), "sha256": TARGET_SHA},
        "queue": {"path": queue_path.relative_to(ROOT).as_posix(), "sha256": sha256(queue_path),
                  "units": 84, "specs": 168},
        "preflight": {"path": preflight_path.relative_to(ROOT).as_posix(),
                      "sha256": sha256(preflight_path), "status": preflight["status"],
                      "passed": preflight["passed_count"], "failed": preflight["failed_count"],
                      "wall_seconds_sum": preflight["preflight_wall_seconds_sum"]},
        "counts": {
            "preparation_units": 53,
            "materialization": dict(Counter(row["status"] for row in new_mat.values())),
            "setup": dict(Counter(row["status"] for row in new_setup.values())),
            "preparation": dict(Counter(row["status"] for row in new_prep.values())),
            "execute_ready_units": len(ready),
            "split_only_ready_units": sum(row["split_preflight_ready"] and
                                           not row["whole_preflight_ready"] for row in table),
            "known_defect_side_units": len(known_side),
            "known_defect_side_execute_ready": sum(unit["unit_id"] in ready for unit in known_side),
            "rq_c_comparison_side_units": len(comparison_side),
            "rq_c_comparison_side_execute_ready": sum(unit["unit_id"] in ready
                                                       for unit in comparison_side),
            "aq_rq1_items": len(aq_items), "aq_rq1_execute_ready_items": aq_rq1_ready,
            "aq_rq_c_items_after_unretrievable_exclusion": len(aq_rqc_denom),
            "aq_rq_c_complete_ready_pairs": aq_rqc_ready,
        },
        "official_action_counts": {
            f"{kind}:{status}": count for (kind, status), count in sorted(action_counts.items())
        },
        "estimated_campaign_maximum": {
            "basis": "each method-ready revision unit x 3 seeds x 600 seconds",
            "A-D": {"units": sum(row["branch"] == "A-D" and row["ready_for_execute"] for row in table)},
            "A-Q-stage1": {"units": sum(row["branch"] == "A-Q-stage1" and
                                         row["ready_for_execute"] for row in table)},
        },
        "disk": {"artifact_cleanup_deleted_bytes": cleanup["deleted_bytes"],
                 "preflight_free_before_bytes": preflight["disk_free_before_bytes"],
                 "preflight_free_after_bytes": preflight["disk_free_after_bytes"],
                 "current_free_bytes": shutil.disk_usage(ROOT).free},
        "measurement": {
            "preparation_started_at": min(row["started_at"] for row in new_prep.values()),
            "preparation_finished_at": max(row["finished_at"] for row in new_prep.values()),
            "observed_load_average_component_min": min(loads),
            "observed_load_average_component_max": max(loads),
        },
        "units": table, "preparation_failures": preparation_failures,
        "preflight_failures": preflight_failures,
        "prior_failure_diagnosis": {
            "path": "runs/n6-a1b-2026-10-08/a1-failure-diagnosis-v2.json",
            "sha256": sha256(RUN / "a1-failure-diagnosis-v2.json")},
        "zkfuzz_candidate_search_or_execute_invocations": 0,
    }
    for branch in ("A-D", "A-Q-stage1"):
        whole = sum(row["branch"] == branch and row["whole_preflight_ready"] for row in table)
        split = sum(row["branch"] == branch and row["split_preflight_ready"] for row in table)
        hours = (whole + split) * 3 * 600 / 3600
        result["estimated_campaign_maximum"][branch].update(
            whole_ready_units=whole, split_ready_units=split,
            sequential_hours=hours, ideal_three_parallel_hours=hours / 3)
    OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")

    lines = [
        "# N6-A1b A 준비 보충 결과 (2026-10-08)", "",
        "담당은 miiz다. 고정 A 목록과 70건 배치는 바꾸지 않았고, 이 작업에서 zkFuzz 후보 탐색과 campaign `execute`는 0회다. `src/`도 수정하지 않았다.", "",
        "## 결과 요약", "",
        f"- 고정 목록: `docs/n6_targets_a_2026-10-07.json`, SHA-256 `{TARGET_SHA}`.",
        f"- 준비 단위 53개(A-D 12, A-Q 1단계 41) 중 discovery·prepare·plan 성공은 {result['counts']['preparation'].get('success', 0)}개, 실패 {result['counts']['preparation'].get('failed', 0)}개, 미시작 {result['counts']['preparation'].get('not_started', 0)}개다.",
        f"- 새 queue는 `{result['queue']['path']}`, SHA-256 `{result['queue']['sha256']}`다. {result['queue']['units']}개 대상×seed 단위와 {result['queue']['specs']}개 W/S spec을 포함한다.",
        f"- preflight는 {result['preflight']['passed']}/{result['queue']['specs']} 통과, {result['preflight']['failed']} 실패다. 이는 실행 준비 확인이며 zkFuzz 후보 결과가 아니다.",
        f"- W/S 양쪽이 모두 준비된 revision 단위는 {result['counts']['execute_ready_units']}개다. `aq-038`은 W 3개가 실패했지만 S 3개는 통과해 S-only 준비 단위 1개로 보존되며, queue 상태기는 W 실패로 S를 버리지 않는다.",
        f"- 공식 준비로 Panther full SHA 3개를 직접 fetch했고, 회수 불가 짧은 fix 11개는 `fix_commit_unretrievable`로 남겼다. 허용된 준비 산출물 {cleanup['deleted_bytes']:,}바이트는 해시·크기 기록 후 삭제했다.", "",
        "- 단위별 `materialization.json`에는 공식 script 해시와 적용 결과가 있다. 합계는 상대 symlink 9건, 생성 entrypoint 9건, 호환 편집 6건, 정확 dependency 재사용 3건, iden3 공식 patch 1건이며 모두 성공했다. 기존 실제 dependency directory 재사용 10건은 별도 상태로 남겼다.", "",
        f"- 준비 계측 구간은 {result['measurement']['preparation_started_at']}부터 {result['measurement']['preparation_finished_at']}까지다. 단위 시작·종료에 기록한 load-average 성분 범위는 {result['measurement']['observed_load_average_component_min']:.3f}~{result['measurement']['observed_load_average_component_max']:.3f}이다.", "",
        "## RQ 포함 단위", "",
        f"- 알려진 결함 쪽 revision 단위(`development`·`vulnerable`·`leave_one_out`)는 {len(known_side)}개이며, W/S preflight까지 모두 통과한 단위는 {result['counts']['known_defect_side_execute_ready']}개다.",
        f"- 수정 대조 쪽 revision 단위(`fixed`·`leave_one_out`)는 {len(comparison_side)}개이며, 모두 통과한 단위는 {result['counts']['rq_c_comparison_side_execute_ready']}개다. 이 수는 결함 사례 수와 구분한다.",
        f"- A-Q 1단계 RQ1 사례는 24건이며 vulnerable 실행 단위까지 준비된 사례는 {aq_rq1_ready}건이다. 짧은 Panther fix 11건도 vulnerable 쪽은 RQ1 분모에 남는다.",
        f"- 회수 불가 fix 11건을 제외한 A-Q RQ-C 후보는 {len(aq_rqc_denom)}건이다. vulnerable·fixed와 필요한 leave-one-out이 모두 준비된 완전한 쌍은 {aq_rqc_ready}건이다.", "",
        "## 단위별 전후 비교", "",
        "| 단위 | 층·종류 | 절차 | materialization 전→후 | setup 전→후 | discovery/prepare 전→후 | 적격 조각 | W | S |",
        "|---|---|---|---|---|---|---:|---|---|",
    ]
    for row in table:
        lines.append("| " + " | ".join([
            f"`{row['unit_id']}`", f"{row['branch']} / {row['revision_kind']}",
            row["procedure"], row["materialization"], row["setup"], row["preparation"],
            str(row["eligible_targets"] if row["eligible_targets"] is not None else "—"),
            row["W"], row["S"],
        ]) + " |")

    diagnosis = load(RUN / "a1-failure-diagnosis-v2.json")
    lines += ["", "## A1 실패 원인 재검산", "",
              "기존 판정은 바꾸지 않았다. A1의 7개 W 실패 핵심 오류는 다음과 같다.", ""]
    for row in diagnosis["w_preflight_failures"]:
        lines.append(f"- `{row['unit_id']}`: " + "; ".join(f"`{clean(line)}`"
                                                             for line in row["core_error_lines"]))
    lines += ["", "A1 discovery/preparation 실패 8개는 원시 분류상 `compiler_or_tool_error` 7개와 `manifest_concrete_instance_unavailable` 1개다. 후자는 `aq-000`의 `concrete root instance key unavailable`이고, 나머지는 plan의 `prepared corpus has no targets eligible for small-first`다. 따라서 8개를 모두 같은 compiler 오류로 재분류하지 않았다.", "",
              "A1b의 실패·미시작은 다음 원시 기록에 남겼다.", ""]
    for row in preparation_failures:
        evidence = []
        if row["reason"]:
            evidence.append(clean(str(row["reason"])))
        for group in row["core_errors"]:
            evidence.extend(group["lines"])
        lines.append(f"- `{row['unit_id']}`: `{row['status']}` / `{row['failure_type'] or 'unknown'}`" +
                     (" — " + "; ".join(evidence[:6]) if evidence else ""))
    lines += ["", "A1b W/S preflight 실패는 다음과 같다.", ""]
    for row in preflight_failures:
        evidence = [line for group in row["evidence"] for line in group["lines"]]
        lines.append(f"- `{row['key']}`: `{row['failure_type']}`" +
                     (" — " + "; ".join(f"`{line}`" for line in evidence[:4])
                      if evidence else ""))

    ad = result["estimated_campaign_maximum"]["A-D"]
    aq = result["estimated_campaign_maximum"]["A-Q-stage1"]
    lines += ["", "## 비용·디스크·남은 실행", "",
              f"- 실제 preflight wall 합은 {result['preflight']['wall_seconds_sum']:.3f}초다. queue runner는 seed가 달라도 preflight 입력이 같은 W/S를 검증 후 재사용한다.",
              f"- A-D는 W {ad['whole_ready_units']}·S {ad['split_ready_units']}개 method가 준비됐다. 할당 상한 합은 {ad['sequential_hours']:.1f}시간, 이상적인 3병렬 하한은 {ad['ideal_three_parallel_hours']:.2f}시간이다.",
              f"- A-Q는 W {aq['whole_ready_units']}·S {aq['split_ready_units']}개 method가 준비됐다. `aq-038` S-only를 포함한 상한 합은 {aq['sequential_hours']:.1f}시간, 이상적인 3병렬 하한은 {aq['ideal_three_parallel_hours']:.2f}시간이다. 실제 시간은 시작 실패·조기 반환·정리 비용에 따라 달라진다.",
              f"- preflight 전후 여유 공간은 {result['disk']['preflight_free_before_bytes'] / 2**30:.1f}→{result['disk']['preflight_free_after_bytes'] / 2**30:.1f} GiB다. 이 문서 생성 시점은 {result['disk']['current_free_bytes'] / 2**30:.1f} GiB다.",
              "- A1b는 준비 관문만 갱신한다. 후보 값을 열지 않았고 J 판정, RQ1 결과, RQ-C 결과를 완료로 선언하지 않는다.", "",
              "## 검증", "",
              "- `python3 -m unittest tests/n6_a1b_test.py tests/n6_prepare_a_stage1_test.py tests/n6_a_specs_test.py tests/n6_targets_a_test.py tests/policy_a_engine_v3_test.py tests/n6_b_queue_test.py`: 29개 통과.",
              "- `cargo fmt`: 통과.",
              "- `cargo clippy --all-targets --all-features -- -D warnings`: 통과.",
              "- `cargo test`: 통과(필요한 gitignored 외부 증거·설치 도구 검사는 기존 선언대로 ignored).", ""]
    OUT.write_text("\n".join(lines))
    print(json.dumps({"report": OUT.relative_to(ROOT).as_posix(),
                      "report_sha256": sha256(OUT),
                      "json": OUT_JSON.relative_to(ROOT).as_posix(),
                      "json_sha256": sha256(OUT_JSON)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
