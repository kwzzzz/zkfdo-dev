#!/usr/bin/env python3
"""Finalize E-02 only after its existing runners and evidence writers finish."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/e02-production-mains-2026-10-05"


def read(path):
    return json.loads(path.read_text())


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    selection = read(RUN / "preparation-selection.json")
    identifiers = {row["identifier"] for row in selection["entries"]}
    event_log = RUN / "runner-overlap-guard.jsonl"
    previous = None
    while True:
        events = [json.loads(line) for line in event_log.read_text().splitlines() if line.strip()]
        if any(row["event"] in {"pause_required", "paused_no_automatic_resume"} for row in events):
            print("E-02 finalization stopped: runner guard requires human review; all files retained", flush=True)
            return
        results = {p.parent.name for p in (RUN / "preparation-measurements").glob("*/result.json")}
        state = read(RUN / "incremental-cleanup-state.json")
        cleaned = set(state["completed_batches"]) | set(state.get("blocked_batches", {}))
        cleanup_ready = all("preparation-measurements/" + key in cleaned for key in identifiers)
        runners_exited = bool(events and events[-1]["event"] == "runners_exited")
        progress = (len(results), cleanup_ready, runners_exited)
        if progress != previous:
            print(json.dumps({"completed_results": len(results), "denominator": len(identifiers),
                              "cleanup_decisions_complete": cleanup_ready,
                              "existing_runners_exited": runners_exited}), flush=True)
            previous = progress
        if runners_exited and results != identifiers:
            raise RuntimeError("runners exited with missing result records; preserve and report missing entries")
        if results == identifiers and cleanup_ready and runners_exited:
            break
        time.sleep(20)

    # Give the load sampler and cleanup watcher one interval to finish their
    # final append. This does not restart any measurement or heavy check.
    time.sleep(15)
    if read(RUN / "checks.json")["status"] != "passed":
        raise RuntimeError("required checks did not pass; do not mark E-02 complete")
    out_json = ROOT / "docs/e02_production_mains_results_2026-10-05.json"
    out_md = out_json.with_suffix(".md")
    if out_json.exists() or out_md.exists():
        raise FileExistsError("result version already exists; preserve it instead of overwriting")
    subprocess.run(["python3", "scripts/cleanup_e02_artifacts.py"], cwd=ROOT, check=True)
    subprocess.run(["python3", "scripts/summarize_e02_production_mains.py"], cwd=ROOT, check=True)
    result = read(out_json)
    if result["status"] != "complete" or result["scope"]["preparation_selection"] != len(identifiers):
        raise RuntimeError("final result validation failed; leave plan in progress")
    completed_date = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    new_compile = sum(row["new_compile_successes"] for row in result["repositories"])
    large_count = len(result["large_deployment_entrypoints"])
    preserved = len(result["cleanup"].get("preserved_unverified_batches", []))
    plan = ROOT / "docs/plan_revision_2026-10-01.md"
    # Read immediately before the narrow owner-row update. Do not touch other
    # tasks, frozen protocols, or any source file.
    current = plan.read_text()
    matching = re.findall(r"^\| E-02 \|.*$", current, flags=re.MULTILINE)
    if len(matching) != 1 or "| miiz |" not in matching[0]:
        raise RuntimeError("E-02 owner row changed; results retained without plan edit")
    row = (
        f"| E-02 | 완료 — 배포 main 컴파일·준비 측정 ({completed_date}, 기한 2026-10-08) | miiz | "
        "[결과](e02_production_mains_results_2026-10-05.md)·[JSON](e02_production_mains_results_2026-10-05.json). "
        f"329개 역할 분모(배포 main 177·test/mock 152), 새 원본 compile 성공 {new_compile}개, "
        f"준비 {len(identifiers)}개 측정·제약 10만 이상 배포 main {large_count}개 개별 보고. "
        "원본 옵션은 E-01과 같은 기본 O1이며 절차 O0는 표기 오류로 명시. "
        "120/600초 compile·300/900초 prepare와 실제 준비 상태를 분리하고 host load·필수 검사 중첩을 기록. "
        f"검증된 생성 산출물만 원장 기록 후 정리, 캡처 확인 부족 {preserved}개는 전체 보존. "
        "필수 검사 통과·zkFuzz 0회. 구조 준비 조사이며 N4-1 전체·N5 완료 아님 |"
    )
    plan.write_text(current.replace(matching[0], row, 1))
    write_new(RUN / "completion.json", {
        "task": "E-02", "owner": "miiz", "completed_at": datetime.now(timezone.utc).isoformat(),
        "result_json": {"path": str(out_json.relative_to(ROOT)), "sha256": hashlib.sha256(out_json.read_bytes()).hexdigest()},
        "result_markdown": {"path": str(out_md.relative_to(ROOT)), "sha256": hashlib.sha256(out_md.read_bytes()).hexdigest()},
        "heavy_checks_repeated": False, "zkfuzz_invocations": 0,
    })
    print("E-02 local reports, safe-cleanup evidence and owner row finalized", flush=True)


if __name__ == "__main__":
    main()
