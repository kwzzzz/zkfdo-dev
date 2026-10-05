# C-01 정상 경계 재사용 준비 점검 범위

2026-10-02 · 담당 miiz · `c01-normal-boundary-readiness-v1` · 고정 시각 `2026-10-02T03:50:07.945074+00:00`

**부분 범위: 기존 NB-01 정상 경계 구현의 지원 범위와 합성 회귀 점검. 요청된 production 호출 위치 매핑은 미수행.**

[인계](../../docs/next_s03_context_handoff_2026-10-02.md)는 C-01의 상세 호출·신호 대응을 후속 S-05의 알려진 결함 후보 entrypoint 투영에 연결한다. 실제 대상의 결함 후보를 production 실행에 연결하는 상세 대응표·경계 재실행 경로는 제공하지 않는 수행 제한을 적용한다. 이 제한은 사용자 미승인이나 컴파일 오류·자료 결측 때문이 아니다. C-01 전체 완료로 기록하지 않는다.

## 실행 전에 고정하는 안전한 작업

- 기존 NB-01 SCOPE/REPORT/evidence와 정상 경계 구현·회귀를 읽고 구현의 실제 지원 범위를 확인한다.
- 기존 비보안용 합성 회귀 두 파일만 실행한다: `tests/normal_boundary_replay_test.py`, `tests/normal_boundary_replay_label_independence_test.py`.
- 이 회귀는 합성 symbol/assignment와 mock을 사용한다. 실제 P2 production 소스·plan·SYM·witness, 후보 JSON, S-05 파일은 열지 않는다. 정상 fixture 45경계 전체 재실행도 포함하지 않는다.
- 프로세스 실행 전 코드·테스트·관련 문서 SHA-256을 고정하고, 실행 로그와 wall·종료 상태를 새 ignored `runs/`에 기록한다.
- 코드·테스트·고정 기록은 변경하지 않는다. 계획은 C-01 행만 갱신한다. 코드 변경이 없으므로 cargo 필수 검사를 이번 작업에서 실행한 것으로 주장하지 않는다.

## 분모와 상태 규칙

| 항목 | 취급 |
|---|---|
| 요청된 template 구성 | `Subtract()`와 `IntDiv(40)` 두 구성. 두 구성 수를 호출 위치 수로 바꾸지 않음 |
| production의 전체 호출 위치 | unknown — 대상별 열거 미수행; 0개·완전성 확인으로 기록하지 않음 |
| production 정상 입력·검증 witness 가용성 | unknown — 해당 자료 내용·provenance 확인을 시도하지 않음; 부재로 단정하지 않음 |
| production 정상 경계 성공/실패/미지원 | not_run — 실제 시도 없음; 성공률을 계산하지 않음 |
| 정상 fixture 과거 분모 | NB-01 보고서의 원본 입력 9, 고유 호출 위치 15, 경계 45를 기존 결과로만 인용 |
| 후보 맥락·도달성·entrypoint TCCT | 미판정. 정상 회귀 통과로 후보 투영을 입증하지 않음 |

## 중단·완료 기준

두 합성 회귀의 결과와 구현의 지원 경계·생산 대상에 아직 적용하지 못한 부분을 값 없는 REPORT에 남기면 이번 부분 작업을 종료한다. 실패는 원문 로그에 남기며 범용 매핑 구현·다른 사례·최적화 복원·후속 후보 실행으로 확대하지 않는다. 실제 후보 값·새 퍼징·후보 재현·held-out 실행·commit/push/PR은 없다. N4-1 전체와 N5 상태는 바꾸지 않는다.

## 보존 참조

아래 SHA-256은 이번 회귀 전에 계산했다. 실제 production 소스·도구 binary hash를 검증한 표가 아니다. A-02 및 NB-01의 기존 원본/도구 hash는 각 고정 문서의 당시 provenance로만 보존한다.

| 저장소 상대 경로 | SHA-256 |
|---|---|
| `AGENTS.md` | `b0db6aa11075f472931c495f8db3f9156e4e64a153e66ac374777acd38f78f02` |
| `docs/next_s03_context_handoff_2026-10-02.md` | `fc1b5590b86d8ca6dced195f4084313b9193a73a754879fa91d3eef8af7568e5` |
| `reports/n4-1-policy-a-engine-2026-10-02/SCOPE.md` | `6908aeb42a746ecbc1d55d0d84e5339ee5ea52ceb09000532fef78d34c4b02fa` |
| `reports/n4-1-policy-a-engine-2026-10-02/REPORT.md` | `0c345ffaca10aed7345b978745b3e93a582cb191da57445b4cb40462b2d270a7` |
| `reports/n4-1-normal-boundary-replay-2026-10-02/SCOPE.md` | `63b6307c9c48f2311e9f23eead5e4d28dd42cdd4f0603f0ef74cc06c25105443` |
| `reports/n4-1-normal-boundary-replay-2026-10-02/REPORT.md` | `cc70c99ed3c3a9bf1eb392d666328e6ef7ba7cfcb96f3919d346561752659d7a` |
| `reports/n4-1-normal-boundary-replay-2026-10-02/evidence.json` | `5530c0bc14254a3d30256d6596abcdb34781f931acbac5f3a3fc1f99422fe72e` |
| `scripts/measure_normal_boundary_replay.py` | `eb6b9ef5182c075f4d7ce42084858e190349f0a16c40eb4057e4888c9c14ba5e` |
| `scripts/measure_normal_compatibility.py` | `19356ce37130e8c4927f49eb7de639617b424889c6313d1ce4367504bda04448` |
| `scripts/measure_normal_preparation.py` | `3cc384a4fa6e52f048073bc1626e03b9370049d221c90090a05f181d6fa80880` |
| `tests/normal_boundary_replay_test.py` | `9ae974f2ed43d2692119d1779a3ad0f85edec8d77508ebcd6e5ea2568eaa938e` |
| `tests/normal_boundary_replay_label_independence_test.py` | `6e7286905ca8a0fc33280e9f610802b9872cd7859a0fa0623223f2a1704b11e9` |
