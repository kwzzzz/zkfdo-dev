#!/usr/bin/env python3
"""Write the value-free N6-A1 preparation report from ignored run records."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/n6-a1-2026-10-07"
OUT = ROOT / "docs/n6_a1_preparation_results_2026-10-07.md"


def load(path: str):
    return json.loads((ROOT / path).read_text())


def sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def esc(value) -> str:
    return str(value if value not in (None, "") else "unknown").replace("|", "\\|").replace("\n", " ")


def main() -> int:
    targets = load("docs/n6_targets_a_2026-10-07.json")
    units = load("runs/n6-a1-2026-10-07/preparation-units.json")
    material = load("runs/n6-a1-2026-10-07/materialization-summary.json")
    recovery = {row["unit_id"]: row for row in
                load("runs/n6-a1-2026-10-07/materialization-recovery.json")["units"]}
    setup = {row["unit_id"]: row for row in load("runs/n6-a1-2026-10-07/setup-summary.json")["units"]}
    preparation = load("runs/n6-a1-2026-10-07/preparation-summary.json")
    prep = {row["unit_id"]: row for row in preparation["units"]}
    queue = load("runs/n6-a1-2026-10-07/queue-v2.json")
    preflight = load("runs/n6-a1-2026-10-07/preflight-v2/preflight-all.json")
    cleanup = load("runs/n6-a1-2026-10-07/artifact-cleanup-result.json")
    cleanup_plan = load("runs/n6-a1-2026-10-07/artifact-cleanup-plan.json")
    first = [row for row in queue["units"] if row["seed"] == 2026100601]
    branches = {row["unit_id"]: row["branch"] for row in
                units["development_units"] + units["aq_stage1_units"]}
    pair_counts = Counter((branches[row["identifier"]],
                           preflight["results"][row["unit_id"] + ":W"]["status"],
                           preflight["results"][row["unit_id"] + ":S"]["status"])
                          for row in first)
    kinds = Counter(row["original_entrypoint_kind"] for row in targets["items"])
    effective_material = Counter()
    material_by_id = {row["unit_id"]: row for row in material["units"]}
    for row in material["units"]:
        recovered = recovery.get(row["unit_id"], {})
        if row["status"] == "ready_for_setup_or_discovery" or recovered.get("status") == "success":
            effective_material["ready"] += 1
        else:
            effective_material[recovered.get("failure_type") or row.get("failure_type") or row["status"]] += 1
    lines = [
        "# N6-A1 알려진 결함 정답 대조 대상 목록·준비 결과 (2026-10-07)", "",
        "담당은 miiz다. 이 작업은 대상 목록, revision 준비, discovery·prepare·plan, W/S preflight까지만 수행했다. zkFuzz 후보 탐색과 캠페인 `execute`는 수행하지 않았고 후보 파일도 열지 않았다.", "",
        "## 고정 목록", "",
        f"- 대상 목록: `docs/n6_targets_a_2026-10-07.json`, SHA-256 `{sha('docs/n6_targets_a_2026-10-07.json')}`",
        f"- 전체 70건: A-D {targets['counts']['A-D']}, A-Q 1단계 {targets['counts']['A-Q-stage1']}, A-Q 2단계 {targets['counts']['A-Q-stage2']}, 수정 전 전용 {targets['counts']['vulnerable_only']}.",
        f"- Fix Commit 있음 50건, 없음 20건. 공유 fix 5그룹, leave-one-out 표시 11건이다.",
        f"- Original 종류: project_main {kinds['project_main']}, project_test {kinds['project_test']}, original_is_direct {kinds['original_is_direct']}, zkbugs_thin {kinds['zkbugs_thin']}.",
        "- `Direct Entrypoint`는 참고 메타데이터로만 기록했고 실행 대체에 쓰지 않았다.", "",
        "## 준비 결과", "",
        f"목록의 라벨 중복을 실행 단위 규칙으로 제거한 결과 A-D 12개, A-Q 1단계 41개, 합계 53개 revision 단위였다. materialization은 ready {effective_material['ready']}, source commit unavailable {effective_material['source_commit_unavailable']}, 분리 불가능 leave-one-out {effective_material['leave_one_out_patch_unavailable']}, fixed revision의 Original 경로 부재 {effective_material['original_entrypoint_missing']}였다.", "",
        f"setup은 성공 {sum(row['status']=='success' for row in setup.values())}, 실패 {sum(row['status']=='setup_failure' for row in setup.values())}, 미시작 {sum(row['status']=='not_started' for row in setup.values())}였다. 실패 유형은 package install command 2, lockfile mismatch 2, pnpm version 미기재 3, submodule command 1이다.", "",
        f"discovery·prepare·plan은 성공 {preparation['counts']['success']}, 실패 {preparation['counts']['failed']}, 미시작 {preparation['counts']['not_started']}였다. 성공 단위에서 discovery 대상 {preparation['targets']['discovered']:,}개, prepared {preparation['targets']['prepared']:,}개, 적격 조각 {preparation['targets']['eligible']:,}개를 기록했다. 실패는 compiler/tool error 7개와 concrete root instance 미확정 1개다.", "",
        "Panther 16개 단위는 고정 목록의 vulnerable/fix commit이 현재 원격 ref에서도 해석되지 않아 `source_commit_unavailable`로 남겼다. 이를 다른 revision이나 Direct wrapper로 바꾸지 않았다. SIV `EmitIfInRange` leave-one-out은 공유 fix가 해당 템플릿 위치의 독립 hunk로 존재하지 않아 `leave_one_out_patch_unavailable`로 남겼다. Tangle fixed revision에서는 기록된 Original test 경로가 사라져 대체 경로를 선택하지 않았다.", "",
        "외부 library search root는 7개 성공 단위에서 `.external/zkbugs/dataset/circom/dependencies/circomlib` 하나뿐이었다. plan의 source fingerprint에는 그 root에서 실제로 채택된 외부 파일이 없었고, 원본 project와 생성 wrapper/source snapshot은 spec에 tree/file hash로 고정했다.", "",
        "## spec·preflight", "",
        f"- 최종 queue: `runs/n6-a1-2026-10-07/queue-v2.json`, SHA-256 `{sha('runs/n6-a1-2026-10-07/queue-v2.json')}`.",
        f"- 최종 preflight: `runs/n6-a1-2026-10-07/preflight-v2/preflight-all.json`, SHA-256 `{sha('runs/n6-a1-2026-10-07/preflight-v2/preflight-all.json')}`.",
        f"- 성공한 준비 단위 19개 × seed 3 × W/S = 114 spec이다. T=600초, S 시도 상한 30초, seed는 2026100601/02/03이다.",
        f"- 114개 기록 중 통과 {preflight['passed_count']}, 실패 {preflight['failed_count']}. seed 독립 재사용 {sum(row.get('source')=='reused_seed_independent' for row in preflight['results'].values())}, 실제 preflight 실행 {sum(row.get('source')=='executed' for row in preflight['results'].values())}이다.",
        f"- 고유 단위 첫 seed 기준 W/S 모두 통과: A-D {pair_counts[('A-D','passed','passed')]}/12, A-Q 1단계 {pair_counts[('A-Q-stage1','passed','passed')]}/41. 준비 성공 단위의 S는 19/19 통과했고 W는 12/19 통과했다.",
        "- v1은 S spec의 `source_snapshot_path` 누락을 검출해 보존하고 폐기했다. 최종 v2는 그 필드만 보완했다. W의 실제 컴파일 실패 7개는 승격하거나 숨기지 않았다.", "",
        "## 실행 시간 예상", "",
        "한 revision 단위는 seed 3개 × (W 600초 + S 600초) = 최대 1시간의 캠페인 wall을 쓴다. 동시 단위 3개라면 전체 고정 분모의 이론적 상한은 A-D 12개 약 4시간, A-Q 1단계 41개 약 13시간 40분이다. 현재 W/S preflight를 모두 통과한 단위만 놓으면 A-D 9개 약 3시간, A-Q 1단계 3개 약 1시간이다. 준비·판정·재시작 비용은 이 계산에 포함하지 않는다.", "",
        "## 측정 편차·정리", "",
        "첫 inference 준비에서 공통 프로필이 AST 통계를 요청해 zkFuzz를 후보 탐색이 아닌 `--version`으로 22회 호출했다. 이를 발견하자 중단했고 원시 기록을 보존했다. 후보 탐색·퍼징·캠페인 실행은 0회다. 최종 small-first 준비 경로는 AST와 zkFuzz version 요청이 0회다.", "",
        f"setup 명령 누적 wall은 {load('runs/n6-a1-2026-10-07/setup-summary.json')['elapsed_seconds_sum']:.3f}초였고, discovery·prepare·plan 명령 누적 wall은 {sum(sum((row.get(stage) or {}).get('elapsed_seconds', 0) for row in preparation['units']) for stage in ('discovery', 'prepare', 'plan')):.3f}초였다. preflight v2 전체 wall은 {preflight['invocation_wall_seconds']:.3f}초였다. 단계별 시작·종료 시각과 load average는 ignored run JSON에 있다.",
        "materialization 중 1분 load average가 최대 28.120까지 올라간 구간은 `aq-038`~`aq-040` 복제·checkout 구간(2026-10-06 19:56:41~19:56:51 UTC)이었다. setup 최대는 23.848, discovery·prepare·plan 최대는 12.871이었다. 이 부하 관측은 결과 상태를 재분류하는 근거로 쓰지 않았다.",
        f"cleanup 전에 capture 값이 있는 진단 사본만 삭제했다. 파일 {cleanup['deleted_files']:,}개, {cleanup['deleted_bytes'] / 1024**3:.3f} GiB를 해시·크기 기록 후 삭제했다. capture/args가 모두 없던 진단 사본 {len(cleanup_plan['preserved_diagnostics'])}개는 보존했다. 첫 materialization 직전 여유 {material['units'][0]['free_bytes_start'] / 1024**3:.3f} GiB에서 cleanup 직후 {cleanup['free_bytes_after'] / 1024**3:.3f} GiB로 순 {((material['units'][0]['free_bytes_start'] - cleanup['free_bytes_after']) / 1024**3):.3f} GiB 감소했다.", "",
        "## 70건 배치", "",
        "| ID | 프로젝트 | 칸 | Original 종류 | Original entrypoint | setup 성공 | LOO | 누락·미확인 |", "|---|---|---|---|---|---:|---:|---|",
    ]
    for row in targets["items"]:
        lines.append("| " + " | ".join([
            esc(row["id"]), esc(row["project"]), esc(row["bucket"]),
            esc(row["original_entrypoint_kind"]), f"`{esc(row['original_entrypoint'])}`",
            "yes" if row["setup_success"] else "no", "yes" if row["leave_one_out"] else "no",
            esc(", ".join(row["missing_or_unknown"]) if row["missing_or_unknown"] else "없음"),
        ]) + " |")
    lines += [
        "",
        "## leave-one-out 준비",
        "",
        "아래는 이번 1단계에 실제로 들어온 leave-one-out revision 단위다. 목록의 leave-one-out 표시 11건 중 A-Q 2단계 항목은 이번 준비 대상이 아니며, 동일 트리·entrypoint 중복은 실행 단위에서 합쳤다.",
        "",
        "| 단위 | 범위 | diff SHA-256 | materialization | spec |",
        "|---|---|---|---|---|",
    ]
    for unit in units["development_units"] + units["aq_stage1_units"]:
        if unit["revision_kind"] != "leave_one_out":
            continue
        old = material_by_id[unit["unit_id"]]
        recovered = recovery.get(unit["unit_id"], {})
        status = "ready" if old["status"] == "ready_for_setup_or_discovery" or recovered.get("status") == "success" else (recovered.get("failure_type") or old.get("failure_type") or old["status"])
        if "diff" in unit:
            scope = unit["diff"]["path"]
            diff_sha = unit["diff"]["sha256"]
        else:
            detail = unit["leave_one_out"]
            planned = detail["planned_diff_scope"]
            scope = f"{planned['path']}:{planned['line']} ({planned['function']})"
            patch_path = RUN / "units" / unit["unit_id"] / "leave-one-out.patch"
            diff_sha = hashlib.sha256(patch_path.read_bytes()).hexdigest() if patch_path.exists() else "unavailable"
        spec_state = "W/S 생성" if unit["unit_id"] in {row["identifier"] for row in first} else "미생성"
        lines.append("| " + " | ".join([esc(unit["unit_id"]), esc(scope), f"`{diff_sha}`" if diff_sha != "unavailable" else "unavailable", esc(status), spec_state]) + " |")

    lines += ["", "## revision 단위", "",
              "| 단위 | 갈래 | 프로젝트 | revision 종류 | materialization | setup | prepare/plan | 발견 | 준비 | 적격 | 외부 include root | W | S | 실패 사유 |",
              "|---|---|---|---|---|---|---|---:|---:|---:|---|---|---|---|"]
    first_by_id = {row["identifier"]: row for row in first}
    for unit in units["development_units"] + units["aq_stage1_units"]:
        old = material_by_id[unit["unit_id"]]
        recovered = recovery.get(unit["unit_id"], {})
        mat = "ready" if old["status"] == "ready_for_setup_or_discovery" or recovered.get("status") == "success" else \
            (recovered.get("failure_type") or old.get("failure_type") or old["status"])
        queued = first_by_id.get(unit["unit_id"])
        w = preflight["results"][queued["unit_id"] + ":W"]["status"] if queued else "not_created"
        s = preflight["results"][queued["unit_id"] + ":S"]["status"] if queued else "not_created"
        setup_row = setup.get(unit["unit_id"], {})
        prep_row = prep.get(unit["unit_id"], {})
        external_roots = [path for path in prep_row.get("condition", {}).get("library_paths", []) if path.startswith(".external/")]
        if mat != "ready":
            reason = mat
        elif setup_row.get("status") != "success":
            reason = ",".join(setup_row.get("failure_types", [])) or setup_row.get("failure_type") or setup_row.get("status") or "setup_not_started"
        elif prep_row.get("status") != "success":
            reason = prep_row.get("failure_type") or prep_row.get("status") or "prepare_not_started"
        elif w != "passed":
            reason = "W:" + preflight["results"][queued["unit_id"] + ":W"].get("failure_type", "preflight_failed")
        elif s != "passed":
            reason = "S:" + preflight["results"][queued["unit_id"] + ":S"].get("failure_type", "preflight_failed")
        else:
            reason = "없음"
        lines.append("| " + " | ".join([
            esc(unit["unit_id"]), esc(unit["branch"]), esc(unit["project"]), esc(unit["revision_kind"]),
            esc(mat), esc(setup_row.get("status", "not_started")),
            esc(prep_row.get("status", "not_started")),
            esc(prep_row.get("discovered_targets", "-")), esc(prep_row.get("prepared_targets", "-")),
            esc(prep_row.get("eligible_targets", "-")), esc(", ".join(external_roots) if external_roots else "없음"),
            w, s, esc(reason),
        ]) + " |")
    lines += [
        "",
        "## 검사",
        "",
        "- `python3 -m unittest tests/n6_targets_a_test.py tests/n6_prepare_a_stage1_test.py tests/n6_a_specs_test.py tests/n6_b_queue_test.py tests/policy_a_engine_v3_test.py`: 24/24 통과.",
        "- `cargo fmt`: 통과.",
        "- `cargo clippy --all-targets --all-features -- -D warnings`: 통과.",
        "- `cargo test`: 348 통과, 22 ignored, 실패 0.",
        "",
    ]
    text = "\n".join(lines)
    if "/Users/" in text:
        raise ValueError("absolute local path leaked into shared report")
    OUT.write_text(text)
    print(f"{OUT.relative_to(ROOT)} {hashlib.sha256(OUT.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
