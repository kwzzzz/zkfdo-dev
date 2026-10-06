#!/usr/bin/env python3
"""Notify the local user after E-02 reports are finalized or a guard pauses it."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/e02-production-mains-2026-10-05"


def main():
    receipt = RUN / "local-notification.json"
    if receipt.exists():
        raise FileExistsError("notification receipt exists; do not notify twice")
    print("Waiting for E-02 completion.json; local macOS notification enabled", flush=True)
    while True:
        if (RUN / "completion.json").exists():
            title = "E-02 완료"
            message = "101개 준비 측정과 결과 문서·계획 표 갱신이 끝났습니다. docs/e02_production_mains_results_2026-10-05.md를 확인하세요."
            outcome = "complete"
            break
        guard = RUN / "runner-overlap-guard.jsonl"
        if guard.exists():
            events = []
            for line in guard.read_text().splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
            if any(row.get("event") == "paused_no_automatic_resume" for row in events):
                title = "E-02 일시정지"
                message = "디스크 또는 실행 구간 충돌 가드가 측정을 일시정지했습니다. 기존 파일은 보존됐으며 확인이 필요합니다."
                outcome = "guard_paused"
                break
        time.sleep(20)
    # Static local notification text contains no circuit inputs or candidates.
    script = f'display notification {json.dumps(message, ensure_ascii=False)} with title {json.dumps(title, ensure_ascii=False)} sound name "Glass"'
    result = subprocess.run(["/usr/bin/osascript", "-e", script], text=True, capture_output=True)
    with receipt.open("x") as stream:
        json.dump({"recorded_at": datetime.now(timezone.utc).isoformat(),
                   "outcome": outcome, "notification_command_exit_code": result.returncode,
                   "stderr": result.stderr, "delivery_note": "OS command acceptance only; user viewing is not observable"},
                  stream, ensure_ascii=False, indent=2)
    print(json.dumps({"outcome": outcome, "notification_command_exit_code": result.returncode}), flush=True)


if __name__ == "__main__":
    main()
