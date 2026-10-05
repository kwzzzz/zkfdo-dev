# A-01 한정 실행 범위

2026-10-02 · 담당 miiz · `policy-a-model-scope-v1`. [요청 인계](../../docs/next_policy_a_handoff_2026-10-02.md)의 일부만 수행한다. **실제 결함 후보를 반복 생성·재현하는 엔진 연결과 P2 zkFuzz 캠페인은 수행하지 않는다.** A-01 전체 완료 또는 실제 엔진에서 Policy A가 검증됐다는 기록을 만들지 않는다. 기존 실행 명령·형식·고정 자료·검토 담당 파일은 보존한다.

## 실행 전 고정한 대상과 정책

| 구분 | 대상 | 예산·시도 상한 | 실제 실행 여부 |
|---|---|---|---|
| 요청된 P2 통째 | 기존 `inference-main` 한 단위 | 요청값 600초 / 30초 | 미실행. 새 엔진 연결 없음 |
| 요청된 P2 분할 | 기존 small-first block-1 metadata의 21개 ID 전부 | 요청값 600초 / 30초 | 21개 모두 미시작. 후보 수·CPU·메모리는 unknown |
| 결정적 whole 모델 | opaque label 1개 | 가상 600,000ms / 30,000ms | 모델만 실행 |
| 결정적 split 모델 | opaque label 21개 | 동일한 가상 600,000ms / 30,000ms | 모델만 실행 |
| 실패 모델 | 취소·저장 실패·회수 실패·시계 무진전 각 1개 | 같은 가상 예산, 아래 중단 규칙 | 모델만 실행 |
| 실사용 자원 probe | 입력/외부 명령을 받지 않는 고정 산술 자식 1개 | 200,000개 정수 제곱 합, 후손 생성 없음 | 로컬 CPU·RSS·wall 측정. 캠페인과 별도 |

P2 분모는 [미실행 목록](../../runs/n4-1-policy-a-2026-10-02/model-v1/requested-engine-not-run.json)에 기존 순서·ID·metadata 출처 hash만 남긴다. 소스·후보 값은 열지 않고 새 준비·컴파일·퍼징도 하지 않는다. whole/split 모델 label은 이 실제 타깃을 실행하는 adapter가 아니다.

사전 모델 입력은 [preregistered-model.json](../../runs/n4-1-policy-a-2026-10-02/model-v1/preregistered-model.json), SHA-256 `19683399f3cd3dca7c280f2114ffec9ae3202df3cd3b7717a245050b2db892a0`다. 모델 순서는 whole → split → 취소 → 저장 실패 → 회수 실패 → 무진전이다.

- seed는 `2026100201, 2026100202, 2026100203` 순환이다. 타깃은 시도 번호 modulo 타깃 수, seed는 타깃 목록 한 바퀴마다 다음 값으로 간다. 결과 label·사후 검토는 순서나 종료 규칙을 바꾸지 않는다. seed 0은 거부한다.
- 모델 결과 순환은 synthetic candidate(1ms) → no-candidate(1,000ms) → timeout(요청 40,000ms) → 시작 실패다. 매 시도 startup 2ms·cleanup 3ms를 모델 비용으로 더한다. candidate marker는 같은 문자열을 반복하며 원인/결함 수로 해석하지 않는다.
- 동일 `simulate` 경로에 label 1개 또는 21개만 전달한다. 총예산은 타깃 수로 복제하지 않는다. 한 시도 예약은 `min(30,000ms, 남은 예산)`, 사용하지 않은 예약은 반환한다. 예약 합계는 캠페인 총할당과 다르다.
- 모델의 기준점은 **가상 첫 dispatch**다. 실제 엔진의 첫 OS 프로세스 시작과 같은 시각이라고 주장하지 않는다. startup·child span·cleanup을 debit하고 cleanup이 마감을 넘기면 초과를 남긴 뒤 새 시도를 시작하지 않는다.
- 총예산·취소·128회 사전 시도 상한으로 끝낸다. 취소 모델은 가상 250ms, 저장 실패는 시도 0, 회수 실패는 첫 시작 시도, 무진전은 0ms 이벤트로 고정한다. 회수/저장 실패나 시계 무진전은 불완전 종료이며 성공으로 세지 않는다.
- 모델 CPU/RSS는 `null`과 ‘OS 프로세스 없음’ 사유를 둔다. probe만 `wait4` 직접 자식 CPU와 peak RSS를 측정하며 Darwin은 byte, Linux는 KiB→byte 변환이다. 지원하지 않는 단위·없는 RSS는 unknown이다. 이 probe는 엔진 프로세스 트리·timeout/cancel 강제 종료·자원 동등성을 검증하지 않는다.

## 도구·코드 고정

| 항목 | SHA-256 |
|---|---|
| Python 3.14.7 실행 파일 | `87d4df53fd91304be5bac391fb204643c36b7df2023c04a0953bcbc7d4fdf634` |
| 새 `scripts/policy_a_budget_model.py` | `7740c8bbebfba507a950023df24e4ab6e103d2326bbeceee0108af75aef3a185` |
| NB-01 label/table 독립성 회귀 | `6e7286905ca8a0fc33280e9f610802b9872cd7859a0fa0623223f2a1704b11e9` |

모델 캠페인·probe 실행 전 conditions.json에 위 도구·코드·범위·입력 hash를 재기록한다. 전체 엔진 도구 hash는 기존 P2 metadata의 과거 기록일 뿐 새 실행 증거로 쓰지 않는다. 실제 zkFuzz seed·작동 시간·결함 수를 생성하거나 추정하지 않는다.

## 검사·종료 기준

NB-01에는 정확히 한 개의 추가 합성 회귀로 fixture label/사전 경로표 접근을 금지하면서 원래 `read_inputs`를 검사한다. 이전 45경계 실행·코드·고정 보고서는 보존한다. 예산 모델 회귀와 필수 fmt·지정 clippy·cargo test를 수행한다. 모델/실측/미실행을 분리한 REPORT와 값 없는 evidence를 남기면 이 한정 작업을 종료한다. 실제 P2 캠페인이 남으므로 A-01은 부분 완료·실행 미완료다.

N4-1 전체 미완료·N4-2 미착수·N5 미고정을 유지한다. N4-1 상한 12시간의 과거 사용시간은 unknown이며 가상 600초를 실제 소요나 잔여 작업시간으로 환산하지 않는다. commit/push/PR은 하지 않는다.
