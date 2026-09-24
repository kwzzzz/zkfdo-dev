# controlled-v1.1 execution protocol

고정일: 2026-09-20

상태: **실행 전 프로토콜 고정 완료 / plan 0회 / zkFuzz 실행 0회 / 성능 분석 미실행**

이 문서는 [`controlled_v1_evaluation_protocol.md`](controlled_v1_evaluation_protocol.md)의 실행 파일 식별 정보만 교체하는 실행 프로토콜이다. 원 프로토콜의 SHA-256은 `0552be5557315ecdf1e929ed9b37120d96e3f77004e6d64219675268563665b9`이다. 여기에 명시하지 않은 대상, 전략, 반복 수, block 순서, seed, 예산, 후보 판정 기준, 시간 처리와 통계 분석은 원 프로토콜을 그대로 적용한다.

기존 controlled-v1은 고정 실행 파일 `83c5e1ca1d9f4abed46c01b567fa0d8345c5133897f3ee73041f93339020a6d0`을 회수하지 못해 plan과 zkFuzz 실행이 각각 0회인 상태로 보존한다. 2026-09-20에 저장소와 관련 `/private/tmp` 경로에서 후보 파일 616개를 한 번 통합 검사했지만 해당 해시를 찾지 못했다. 이 결과는 [`controlled-v1 실행 전 점검`](../reports/controlled-v1-execution-preflight-2026-09-19/REPORT.md)의 중단 판정을 변경하지 않는다.

## v1.1에서 교체한 실행 파일 식별 정보

| 항목 | 고정 값 |
|---|---|
| zkfDO 구현 커밋 | `9a8bb0319a8b4e127f73be5f1fa279eafb9156db` |
| Git tree | `4215bea47d73115dd8c5663a5df538803828a746` |
| 고정 실행 파일 | `runs/controlled-v1.1/frozen-tools/zkfDO-9a8bb031-debug` |
| 실행 파일 SHA-256 | `e3472909d3d8de4411ee20a9574a822b9c262e7aff935c9bf38eac8f31a16960` |
| 실행 파일 크기 | `18,453,704` bytes |
| 빌드 명령 | `cargo build --locked --bin zkfDO` |
| 빌드 profile | Cargo `dev` (`unoptimized + debuginfo`) |
| Cargo.lock SHA-256 | `bcd85f7856728263ebf4f1e784cd47e9d87ce76d1c2cb7d15bbc4686a393c7a2` |
| rustc | `1.94.1 (e408947bf 2026-03-25)`, `aarch64-apple-darwin` |
| cargo | `1.94.1 (29ea6fb6a 2026-03-24)` |

실행 파일은 위 커밋의 `git archive`로 만든 격리 소스 트리에서 빌드한 뒤 위 보관 경로로 복사했다. campaign 시작 전과 각 block 시작 전 이 경로와 해시를 다시 확인한다. 다른 zkfDO 실행 파일로 만든 plan, outcome 또는 evaluation은 v1.1 표본에 포함하지 않는다.

## 변경하지 않는 고정 조건

- 대상: `manifest.controlled-v1.json`의 Subtract 취약 원본과 수정 비교본 두 target
- 전략: `risk-only`, `random`, `small-first`
- 반복: 12 paired block, 전략별 12회, 총 36회
- 전략 실행 순서와 seed: 원 프로토콜의 12개 block 표 그대로
- 예산: target당 30초, 전략 실행당 총 60초
- prepared report, ranking config, zkFuzz·Circom·Circomspect 버전과 해시: 원 프로토콜 그대로
- 유효 발견: 같은 plan/outcome의 `bug_found` run/target 연결과 입력 전제, 고정 원본 전체 제약, 사전 정의 속성 위반이 모두 `satisfied`인 schema 2 검토 기록
- 분석: 완료시간 상한, 예산 경계, 미검토·조기 종료·failure 처리, 중복 제거, paired 분석을 원 프로토콜 그대로 적용

정적 위험점수 `2` 대 `0`, 공개 known defect, 후보 파일의 존재는 실행 발견으로 집계하지 않는다. backend 무발견, timeout, failure와 `not_started`는 결과이며 유리한 실행으로 교체하지 않는다.

## campaign-invalid 처리

실행 전 해시 불일치, target 또는 plan 검증 실패, 전원 상실, OS 재시작, 저장 공간 고갈처럼 backend 결과와 독립적인 사전 환경 중단만 campaign-invalid다. 해당 block의 기존 기록과 사유를 보존한 뒤 같은 세 seed와 전략 순서로 block 전체를 한 번만 다시 수행한다. 두 번째도 invalid면 campaign을 중단하고 다른 seed로 대체하지 않는다.

backend가 반환한 timeout, 비정상 종료, runner failure, `not_started`, 무발견, 또는 유효하지 않은 후보는 campaign-invalid가 아니다. 이런 결과가 있어도 해당 전략만 재실행하거나 block을 교체하지 않는다. plan과 outcome은 plan ID, plan SHA-256, strategy, seed, 예산, target 순서와 zkFuzz 해시를 대조한 뒤 ledger에 연결한다.

## 실행 후 판정 경계

36회가 모두 실제 종료된 뒤에만 전략별 발견 수·완료시간 상한·곡선과 paired 비교를 계산한다. `bug_found` 후보는 원시 값을 보고서나 대화에 복사하지 않고 별도 사후 검토에서 세 기준을 각각 기록한다. 검토가 끝나지 않은 후보가 있으면 `unreviewed`, 불명확한 기준이 있으면 `unresolved`로 보존하고 원 프로토콜에 따라 최종 전략 비교와 유의성 분석을 보류한다. 검토 시간은 60초 fuzzing 예산과 분리한다.

이 프로토콜은 실행 파일 식별 정보를 제외한 원 프로토콜의 조건을 변경하지 않는다. 실행 결과를 본 뒤 source, ranking 규칙, 가중치, 반복 수, seed, 예산 또는 분석법을 바꾸지 않는다.
