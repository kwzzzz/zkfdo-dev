# A-01 부분 구현 결과: 비보안용 예산 모델과 계측

2026-10-02 · 담당 miiz · `policy-a-model-result-v1`. **A-01 전체는 미완료다.** 실제 결함 후보를 반복 생성·재현하는 zkFuzz 엔진 연결과 P2 캠페인은 제공 범위에서 제외했다. 이것은 준비 오류·엔진 실패·탐지 음성 결과가 아니다. 요청된 실제 실행을 결정적 모델 결과로 대체해 성공 처리하지 않았다.

[실행 전 범위](SCOPE.md) · [값 없는 근거](evidence.json) · [원시 모델/계측 요약](../../runs/n4-1-policy-a-2026-10-02/model-v1/summary.json).

## 요청된 실제 실행의 상태

| 방식 | 사전 대상 분모 | 요청 총예산 / 시도 상한 | 실제 시작 | 결과 |
|---|---:|---|---:|---|
| P2 inference-main 통째 | 1 | 600초 / 30초 | 0 | 미실행 |
| P2 inference-main small-first 분할 | 21 | 600초 / 30초 | 0 | 21개 모두 미시작 |

[전체 미시작 목록](../../runs/n4-1-policy-a-2026-10-02/model-v1/requested-engine-not-run.json)은 기존 P2 small-first block-1 plan의 ID와 순서를 보존한다. 실제 attempt는 0개다. 후보 수·CPU·메모리는 미측정/null이며 ‘후보 없음’, 확인된 결함 0건 또는 자원 동등성으로 해석하지 않는다. 새 소스 조사·준비·컴파일·후보 열람·퍼징은 하지 않았다. 기존 P2 파일과 병렬 S-01 검토 파일은 수정하지 않았다.

## 실제 구현한 부분

새 [policy_a_budget_model.py](../../scripts/policy_a_budget_model.py)는 외부 명령이나 대상 파일을 실행하는 adapter가 없는 순수 정수 시간 모델이다. 단일 label과 21 label 모두 같은 `simulate` 경로를 사용한다. 하나의 총예산, 잔여 예산으로 제한한 시도 예약, 조기 반환의 미사용 예약 반환, 고정 타깃/seed 순환, startup·cleanup debit, 마감·취소·시도 상한, 회수/저장 실패와 시계 무진전 중단을 기록한다. 예약 합계와 캠페인 총할당을 구분하고 같은 synthetic marker도 시도별로 보존한다.

기존 `experiment run`은 타깃별 한 시도와 ordered scheduler에 연결되고, `runner`는 wall·spawn offset을 보존하지만 CPU/RSS는 기록하지 않는다. `experiment record`의 A안은 정책 의도이며 실행 검증 완료가 아니다. 이 기존 명령·형식·Rust 코드·offline record/aggregate는 변경하지 않았다. **실제 엔진에서 통째/분할의 공통 반복 실행 경로를 구현한 것으로 주장하지 않는다.**

## 결정적 모델 검증

아래 시간은 **가상 ms**다. 실제 600초 캠페인을 실행한 기록이 아니다. seed는 순서 검사용 metadata이며 결과는 사전 synthetic event 순환이 정한다.

| 모델 | 가상 시도 수 | 종료 | 가상 사용(ms) | 가상 잔여(ms) | 가상 초과(ms) |
|---|---:|---|---:|---:|---:|
| 단일 label 모델 | 79 | budget_exhausted | 600003 | 0 | 3 |
| 21 label 모델 | 79 | budget_exhausted | 600003 | 0 | 3 |
| 취소 모델 | 2 | cancelled | 253 | 599747 | 0 |
| 저장 실패 모델 | 1 | persistence_failed | 6 | 599994 | 0 |
| 회수 실패 모델 | 1 | reap_failed | 6 | 599994 | 0 |
| 무진전 모델 | 1 | clock_stalled | 0 | 600000 | 0 |

단일/21 label 모델 모두 synthetic candidate 20회, no-candidate 20회, timeout 20회, start-failed 19회를 보존했다. 조기 marker 뒤에도 진행하며 마지막 cleanup 3ms를 숨기지 않았다. 모델에서 21 label은 모두 가상 시작됐지만 실제 P2 21개는 모두 미시작이다. 전체 모델에서 `사용 + 잔여 = 총할당 + 초과`, 시도 debit 합계 = 캠페인 사용을 검산했다.

순수 모델의 기준점은 가상 dispatch다. 사용자 요청의 실제 첫 프로세스 시작 기준·저장/OS 스케줄링·엔진 자식 회수 의미를 입증하지 않는다. timeout·cancel·reap/save failure 모델 통과도 실제 프로세스 트리의 종료 처리를 검증한 것이 아니다. 실제 파일 저장은 create-new·flush·fsync이며 실패 시 성공 반환하지 않는다.

## 별도 정상 자식의 실측

외부 명령·대상 파일을 받지 않는 고정 정수 산술 자식 1개만 실제 실행했다. 후손 프로세스는 만들지 않았다. `wait4`의 직접 자식 CPU·peak RSS와 부모의 monotonic 시작 호출→회수 wall을 기록했다.

- wall **0.012709375초**, child user+system CPU **0.004551초**, peak RSS **2,588,672 bytes**. exit 0·회수 성공.
- Darwin의 `ru_maxrss` byte 단위를 사용했다. 없는 값/지원하지 않는 단위는 null과 이유를 쓰도록 했다.
- 모델 CPU/RSS는 전부 unknown이다. 이 한 자식의 수치를 가상 시도나 실제 엔진 캠페인에 배분하지 않는다. 동일 할당이 동일 CPU/메모리 사용을 뜻하지 않는다.

## NB-01 보완과 필수 검사

[라벨/경로표 독립성 회귀](../../tests/normal_boundary_replay_label_independence_test.py)를 **정확히 1개** 추가했다. 실제 `run_case`의 discovery/compiler/calculator/파일출력은 합성 stub으로 두고, 원래 `read_inputs`만 실행한다. 같은 symbol·witness·실제 prefix·wrapper interface를 유지하면서 fixture label과 사전 경로표를 독성 값으로 바꾸고 해당 입력 함수에서의 접근을 차단했다. payload·metadata는 동일했다. 분모 검증에서 경로표를 읽는 의도된 사용까지 금지한 것은 아니다. NB-01 45경계 실험은 반복하지 않았고 기존 코드·테스트·보고서는 보존했다.

[예산 모델 회귀](../../tests/policy_a_budget_model_test.py) 10개가 통과했다. 1대21 공통예산, 후보 뒤 계속, 중복 marker, 조기 반환, 잔여 clip·cleanup 초과, 재시작 비용, 취소, 시작 실패, 회수/저장 실패, 무진전, 고정 순서·seed와 잘못된 입력 거부를 확인했다.

- `cargo fmt` 및 `cargo clippy --all-targets --all-features -- -D warnings` 통과.
- `cargo test`: **297 passed, 0 failed, 22 ignored**.
- Python 정상 회귀 **29 passed**(기존 28+신규 NB 1), 예산 모델 **10 passed**. 총 39개.
- 시작 baseline의 **708개 보존 파일** hash가 유지됐다. N3 채택 기록·NB-01 고정 자료·기존 엔진/집계 코드·P2 설정·인계 원문을 포함한다. 실제 실행한 새 코드와 SCOPE hash는 conditions에 있다.

[검사 원문](../../runs/n4-1-policy-a-2026-10-02/validation-v1/results.json) · [예산·보존 검산](../../runs/n4-1-policy-a-2026-10-02/validation-v1/accounting-and-preservation.json).

## 남은 관문과 상태

A-01은 **모델·한정 계측·NB 회귀 부분 완료, 실제 엔진 연결·캠페인 미실행**이다. 실제 첫 프로세스 시작 기준의 공통 총예산, 엔진 프로세스 트리 CPU/RSS, timeout/cancel/회수/저장 처리, 통째/21조각의 실사용 비교는 남는다. 실제 엔진 공정성·탐지 우위·확인된 원인 수·같은 수준 의미 검토를 주장할 근거는 생기지 않았다. 병렬 과거 후보 검토를 새 후보 판정으로 복사하지 않는다.

N4-1 전체 미완료·N4-2 미착수·N5 미고정을 유지한다. 과거 active-work 시간은 unknown이며 가상 600초나 짧은 probe를 사람의 사용시간·잔여 상한으로 환산하지 않는다. 실제 결함 반복 생성 캠페인을 후속으로 자동 실행하지 않는다. commit/push/PR은 하지 않았다.

## 주요 참조 해시

- [policy_a_budget_model.py](../../scripts/policy_a_budget_model.py): `7740c8bbebfba507a950023df24e4ab6e103d2326bbeceee0108af75aef3a185`
- [normal_boundary_replay_label_independence_test.py](../../tests/normal_boundary_replay_label_independence_test.py): `6e7286905ca8a0fc33280e9f610802b9872cd7859a0fa0623223f2a1704b11e9`
- [policy_a_budget_model_test.py](../../tests/policy_a_budget_model_test.py): `0f5f62f9d8e10f21a710e68c46788408b0eb6cf3a574ee9d7e5087bcbf0a4f5c`
- [SCOPE.md](../../reports/n4-1-policy-a-2026-10-02/SCOPE.md): `8090662ac1ac99b5cf12603abe54da7b2d3a143c29f7d9176620693b430bf9a4`
- [summary.json](../../runs/n4-1-policy-a-2026-10-02/model-v1/summary.json): `9a611bb064b685b126bf11edd7bb066c1245fa31696192d4cd77a8a245e89485`
- [evidence.json](../../reports/n4-1-policy-a-2026-10-02/evidence.json): `5c7c246778ae534c983d43011287e57ec46e57182714d7a3acf8443b4fbb508e`
