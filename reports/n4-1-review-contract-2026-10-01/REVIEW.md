# N4-1 판정·증거 연결 계약 검토 (2026-10-01)

**상태: 검토 완료(읽기 전용).** 대상은 [결정용 기록](../../docs/scope_decision_final_2026-10-01.md) §4의 1단계(비교 가능성)에서 만드는 통째·분할 공통 기록과 검토 연결이다. 기준은 결정용 기록 §2–4, [평가 설계](../../docs/evaluation_plan_2026-10-01.md) §3–4, [문제 정의](../../docs/problem_statement.md)의 판정 표, [N3 검토](../n3-scope-review-2026-10-01/REVIEW.md) F4·F5다.

- 코드 관찰은 커밋 `77fe85c`(HEAD)의 정적 읽기다. 실행, 컴파일, 퍼징, 재현은 하지 않았고, 원시 후보·witness·취약 사례 소스도 열지 않았다. P2 보고서의 값 없는 ledger 필드명만 확인했다.
- 아래 필드 이름은 대조용 제안이다. 구현의 이름이 달라도 의미가 1:1로 대응하면 된다.

## 0. 핵심 필수 의견

1. **binding 일치는 원인 귀속이 아니다.** 현재 `backend_attribution`의 `KnownDefectSingleTarget`은 후보가 spec의 대상 타깃에서 나오기만 하면 무조건 `Matched`다. `backend_summary`의 고유 원인 수도 이 값으로 센다. 새 경로는 `binding_match`와 원인 귀속을 분리하고, binding만 있는 결과는 귀속 미완료로 둬야 한다.
2. **분기 국소화는 두 방식에 똑같이 적용한다.** 분할 조각도 하위 인스턴스를 포함하므로, 조각 후보의 원인이 하위 템플릿에 있을 수 있다. 같은 국소화·귀속 규칙을 적용하지 않으면 상위·하위 조각이 같은 원인을 두 번 센다(P2 inference에서 같은 원인이 여러 조각에 반복됨). 통째 후보에만 투영 의무를 지우는 것도 비대칭이다.
3. **후보 하나는 기본적으로 원인 하나까지만 기여한다.** 한 타깃에 spec이 둘 이상 묶이면 후보 하나가 원인 둘로 세어질 수 있다. 원인별 근거가 없으면 `ambiguous`로 둔다.
4. **시간에는 기준 태그가 필수다.** P2의 기록에서 통째 lane의 `found_at_seconds`는 "NOT SAFE" 로그 줄을 읽은 벽시계 시각이고, 분할 lane은 완료 offset 상한이다. 기준이 다른 시간을 같은 열로 비교하지 않는다.
5. **검토 상태와 검토 결과를 분리한다.** 미시작·중단·오류·투영 실패·귀속 실패는 음성이 아니다. 단위별 "하나 이상 확인"은 값이 셋 이상인 상태로 둔다.
6. **할당, 실제 사용, 종료 사유를 분리하고 정책 식별자(A/B)를 남긴다.** CPU·메모리를 재지 않았으면 `unknown(not-measured)`로 둔다.
7. **과거 기록의 의미를 보존한다.** 기존 `ConfirmationScope::Project`는 "컴포넌트 검토 + production 도달성"이다. entrypoint TCCT나 프로젝트 의미 확인으로 옮기지 않는다. P2의 `found`는 위치 일치다.
8. **관문을 둘로 나눈다.** 기록 경로(구조) 통과는 N4-1 통과가 아니다. 지금 자료로는 의미 관문을 통과할 수 없다(10절).

## 1. 현재 형식에서 확인한 사실 (HEAD `77fe85c`)

| 항목 | 현재 동작 | 새 계약에서의 의미 |
|---|---|---|
| 원인 귀속 | `KnownDefectSingleTarget` → 조건 없이 `Matched`(`known-defect-binding-matched`) | 타깃 binding 일치. 원인 귀속 근거 아님 |
| 고유 원인 수 | `Validated`이고 `Matched`인 review의 `root_cause_id` 집합 크기 | 후보 1개 × spec 여러 개 → 중복 집계 가능 |
| 후보 binding | 후보의 `1_main_template` = plan 타깃 템플릿 = spec 템플릿이어야 함 | 통째 후보는 entrypoint 자체만 대상. 하위 인스턴스 투영 경로 없음 |
| 검토 진입 | zkfDO plan·outcome 필요 | P2 통째 lane(`p2.py` 직접 실행)은 검토 경로에 들어갈 수 없음 |
| 속성 predicate | 사례별 Python predicate(입력 전제·속성 위반) | 일반 TCCT(같은 입력 정상 계산과의 차이)는 미구현 |
| 후보 시간 | `3_execution_time`을 비어 있지 않은 문자열로만 확인 | Rust `Duration` Debug 문자열. 초 단위 해석·기준 연결 없음 |
| run 시간 | `process_start_offset_seconds`(spawn 호출 시점, OS exec 아님), `completion_offset_seconds`(결과 저장 뒤), `started_at`·`finished_at`·`wall_time_seconds` | 탐지 곡선은 완료 offset을 `observed_by_seconds` 상한으로 씀 |
| 자원 | 벽시계만 기록 | CPU·메모리·동시성 없음 |
| 종료 | `RunStatus`: `bug_found`, `no_counterexample`, `timeout`, `compile/runtime/parse/spawn_error`, `unknown` | 시도 순번, 잔여 할당, 캠페인 종료 사유, 환경/방법 실패 구분 없음 |
| 검토 결과 | `Disposition`: `validated`·`rejected`·`unresolved`·`review-error`. `unreviewed_candidates`에는 사유가 있음 | 검토 상태(미시작·중단)와 결과가 한 축에 섞임 |
| 범위 | `ConfirmationScope`: `project`·`original-component`·`wrapper-only`·`reachability-unknown`. `project` = 컴포넌트 검토 + production 도달성 검증 | 새 entrypoint TCCT·프로젝트 의미 층과 다른 뜻 |
| 검토 비용 | `automated_review_seconds` | 검토 완료시각·수동 검토 시간 없음 |
| P2 ledger | 형식 셋(통째 `p2.py`, inference 분할 zkfDO, zk-email 분할 `p2.py`). `found`는 정답 위치 조각의 `bug_found` | 하네스가 다름. 위치 일치·미검토 |

## 2. 필수 기록 항목과 의미

### 2.1 연결 키

| 키 | 의미 | 주의 |
|---|---|---|
| `unit_id` | 프로젝트 + 재현 가능한 소스 버전 + entrypoint + 실행을 바꾸는 설정의 해시 | `family_id`는 별도 열. 라벨·predicate·seed·방식 차이로 새 단위를 만들지 않음 |
| `method` | `whole` 또는 `split` | |
| `campaign_id`, `attempt_id`, `attempt_index`, `round_index` | 단위·방식별 캠페인과 그 안의 프로세스 시도. 분할은 바퀴 순번 포함 | A 정책의 반복을 표현 |
| `target_id`, `instance_key` | 시도의 대상(통째는 entrypoint, 분할은 조각) | 조각은 호출 맥락이 없는 인스턴스 |
| `candidate_id`, `occurrence_id` | 후보 파일의 내용 해시, 그리고 시도별 출현 | 같은 내용이 여러 번 나오면 출현을 모두 보존 |
| `review_id`, `layer` | 후보 × 층(아래 2.4)의 검토 | |
| `cause_id` | 원인 등록부의 키 | 후보·출현과 다대일 |
| `call_path` | 국소화된 인스턴스의 root부터의 경로(통째), 또는 해당 인스턴스의 호출 위치 목록 참조(분할) | 이후 맥락 판정용. 지금은 연결만 |

### 2.2 시도 기록

- **버전:** zkFuzz 바이너리 해시와 후보의 `4_git_hash_of_zkfuzz`(없거나 `unknown`이면 그대로 기록), 컴파일러 해시와 인자, 소스 버전 ID, plan·outcome 해시, 하네스 ID와 버전.
- **정책:** `policy_id`(A 또는 B와 규칙 파일 해시), seed 순서와 이번 seed, 순위 seed.
- **할당:** 단위 총할당, 시도 상한, 시도 시작 시점의 잔여 할당.
- **실제 사용:** 벽시계, CPU user/system, 최대 RSS, 같은 호스트의 동시 실행 수. 재지 않은 값은 `unknown(not-measured)`로 두고 0으로 채우지 않는다.
- **시도 종료:** `candidate-returned`, `generations-exhausted`, `attempt-limit`, `allocation-exhausted`(잔여 할당 때문에 잘림), `tool-error`(원래 상태 유지), `environment-error`, `unknown(reason)`. 원래 `RunStatus`도 함께 보존한다.
- **캠페인 종료:** `allocation-exhausted`, `attempt-cap`, `plan-exhausted`(B의 한 바퀴 완료), `aborted(reason)`. 미사용 할당 = 총할당 − 캠페인 경과시간(시도와 그 사이 하네스 오버헤드 포함). 계산하지 못하면 이유를 남긴다.

### 2.3 후보와 출현

- 원래 파일 경로와 해시, 보존 사본 해시, 시도 링크, 방식, 단위.
- zkFuzz 결과 플래그(`5_flag`)와 차이 난 출력(`6_target_output`) 원문. 해석은 검토 층에서 한다.
- 시간 필드는 6절의 기준 태그와 함께 둔다.

### 2.4 검토 (후보 × 층)

| 필드 | 값 | 의미 |
|---|---|---|
| `layer` | `component-general`(주), `component-contract`, `entrypoint-tcct`, `project-semantic` | 층마다 별도 기록. 층끼리 합치지 않음 |
| `review_state` | `not-started`, `in-progress`, `complete`, `aborted(reason)`, `review-error(reason)` | 상태 축 |
| `review_outcome` | `confirmed`, `not-confirmed`, `unresolved` | `complete`일 때만 값이 있음 |
| `localization` | `localized(instance_key)`, `multi(instance_keys)`, `root`, `failed(reason)`, `not-attempted` | 양쪽 방식에 같은 절차(5·7절) |
| `criteria` | 고정 제약 전체, 입력 도메인(일반 층은 고정 인터페이스), 속성(출력 차이 또는 정상 계산 abort) 각각 `satisfied`·`not-satisfied`·`unknown`과 근거 | 기존 `CommonCriteria`와 대응 |
| `binding_match` | `true`·`false`·`unknown` | 귀속 근거가 아님 |
| `attribution` | `attributed(cause_id, method, evidence)`, `unattributed(reason)`, `ambiguous(cause_ids)`, `not-attempted` | `method`가 binding뿐이면 `attributed` 불가 |
| `overlap` | 같은 후보의 다른 층 검토 ID | 결정용 기록 §3의 연결키 |
| 시간·비용 | `review_started_at`, `review_completed_at`(UTC), 자동 검토 초, 수동 검토 초 | 생성 시각과 섞지 않음 |

기존 `Disposition`은 `validated`→`complete`+`confirmed`, `rejected`→`complete`+`not-confirmed`, `unresolved`→`complete`+`unresolved`, `review-error`→`review-error`로 옮긴다. 이것은 그 review의 층(대개 사례별 계약)에 대한 결과로만 옮기며, 일반 층의 결과로 승격하지 않는다.

### 2.5 원인 등록부

`cause_id`, `kind`(`known`: 사전 등록·메타데이터 참조 / `additional`: 일반 규칙), 템플릿·인스턴스 링크, 출현 목록(후보·검토·방식·단위·`call_path`), `dedupe`(`canonical`, `duplicate-of(cause_id)`, `unresolved-duplicate`), `root_only`(root 템플릿 원인 여부).

## 3. 결과 수준을 인정하는 조건 (두 방식에 같은 최소 증거)

| 수준 | 인정 조건 | 그것만으로는 부족한 것 |
|---|---|---|
| 후보 | 파일 해시, 시도 링크, 방식, zkFuzz 버전, 시도 종료 기록 | — |
| 컴포넌트 확인(일반 층) | ① 후보와 시도의 연결 검증 ② 같은 입력의 정상 계산(고정 생성기)과 그 정상 witness의 고정 제약 만족 ③ 분기 국소화 결과가 `localized`이고 신호 대응이 검증됨 ④ 그 인스턴스의 고정 제약 전체 만족 ⑤ 그 인스턴스 입력은 정상값과 같고 출력이 다르거나, 정상 계산이 그 인스턴스에서 의미상 abort ⑥ 입력 도메인은 고정 인터페이스 | zkFuzz의 `NOT SAFE`, `bug_found`, `RunStatus`, 타깃 binding, 정답 위치 일치 |
| 원인 귀속 | 컴포넌트 확인 + 사전 귀속 절차의 근거(위치는 보조, 수정판 제약이 그 후보를 거부하는지, 같은 절차의 수동 확인) + 단일 원인 | `binding_match`만, 위치만, 같은 경고 이름 |
| entrypoint TCCT 확인 | entrypoint의 고정 제약 전체 만족 + 같은 entrypoint 입력에서 정상 계산과 공개 출력이 다르거나 abort + entrypoint 역할 기록 | 분할 후보에는 상향 확인 전까지 해당 없음 |
| 프로젝트 의미 | 사전 정의한 프로젝트 속성의 위반(사전 범위의 수동 사례연구) | entrypoint TCCT 확인만 |

분할 후보도 ③을 거친다. 조각 안에서 처음 갈라지는 인스턴스가 조각 자신이면 그 조각 템플릿이 대상이고, 하위 인스턴스면 그 하위 템플릿이 대상이다.

## 4. 상태 전이와 집계

**허용 전이.** `not-started → in-progress → {complete, aborted, review-error}`. 같은 후보·층을 다시 검토하면 새 `review_id`와 새 버전 기록을 만든다. 이전 기록은 덮어쓰지 않는다. `unattributed → attributed`는 새 근거가 있을 때만, 새 기록으로 한다.

**금지 전이.** `aborted`·`not-started`·`review-error` → `not-confirmed`. `unresolved` → `not-confirmed`. `localization failed` → `not-confirmed`. 근거 없이 `ambiguous` → 한 원인으로 확정. 다른 층의 결과로 이 층의 결과를 채우는 것.

**허용 집계** (방식·단위별, 분모 포함)

| 집계 | 정의 |
|---|---|
| 컴포넌트 확인 고유 원인 | `component-general`·`complete`·`confirmed`·`attributed`(binding만은 제외)·`dedupe = canonical`인 `cause_id`의 수 |
| 확인·미귀속 | 컴포넌트 확인이지만 `unattributed`·`ambiguous`인 후보 수. 별도 표 |
| entrypoint TCCT 확인·미귀속 | 별도 수. 컴포넌트 원인 수에 더하지 않음 |
| 미완료 | 국소화 실패·귀속 실패·검토 상태별 수와 사유 |
| 단위의 하나 이상 확인 | `confirmed-attributed` / `confirmed-unattributed-only` / `not-confirmed-complete`(모든 후보 검토 완료) / `no-candidate`(종료 사유 포함) / `unknown-incomplete` |
| 최초 확인 시간 | 확인·귀속 후보의 같은 기준 시각 중 최솟값. 그보다 이른(같은 기준) 후보가 모두 `complete`일 때만 "최초". 아니면 "시각 t, 선행 미검토 k건" |

**금지 집계.** 층끼리 합산. 후보 수나 출현 수를 원인 수로 사용. 한 원인을 호출 위치·조각·방식·seed·시도마다 다시 세기. binding 일치를 귀속으로 세기. 과거 `Project` 범위를 새 층으로 옮기기. `bug_found`·P2의 `found`를 확인으로 세기. 기준이 다른 시간을 같은 열로 비교하기. 미판정 후보 수를 원인 수 상한으로 쓰기. entrypoint TCCT 미귀속 결과를 컴포넌트 원인 수에 더한 민감도 집계(결정용 기록 §3).

## 5. 과대 집계를 막는 규칙

- **중복:** 원인 수준에서 중복을 제거하되 출현은 모두 남긴다. 중복 여부가 불명확하면 `unresolved-duplicate`로 두고 확정 고유 수에 넣지 않는다.
- **다중 원인:** 처음 갈라지는 인스턴스가 둘 이상이면 `multi`다. 각 인스턴스에 ③–⑤를 따로 통과하는 근거가 있을 때만 각각 원인으로 센다. 그렇지 않으면 미귀속이다. 한 타깃에 spec이 여럿 묶였는데 원인별 근거가 없으면 `ambiguous`다.
- **root:** 국소화가 root(entrypoint main)에 닿으면 `root`로 표시하고, 원인 등록부에 `root_only = true`를 남긴다. 이 경우 컴포넌트 층과 entrypoint TCCT 층이 같은 대상을 보지만 합산하지 않는다. 분할에는 root 조각이 없으므로 이 원인은 쌍대 비교에서 분할 손실 후보로 표시만 하고 제외하지 않는다.
- **abort형:** 정상 계산이 어느 인스턴스의 어떤 `assert`에서 abort했는지 정상 실행 근거가 필요하다. 도구 crash, timeout, `runtime-error`를 의미상 abort로 세지 않는다. 출력이 없는 후보에 출력을 채우지 않는다.
- **계약 조건부:** 전제 위반은 `component-contract` 층의 `not-confirmed`(사유: 전제 위반)일 뿐이다. 일반 층의 결과를 바꾸지 않고, 맥락 배제나 오탐을 뜻하지 않는다.
- **known/additional:** 같은 국소화·귀속·검토 상한을 적용한다. additional은 일반 규칙으로만 확인하고, 사후 새 명세가 필요하면 탐색층으로 분리한다.

## 6. 시간의 의미

| 기호 | 의미 | 출처 | 기준점 |
|---|---|---|---|
| T1 | zkFuzz 엔진 경과시간. `start()` 진입부터 반례 저장 직전까지(파싱 시간 포함) | 후보의 `3_execution_time`(Rust `Duration` Debug 문자열) | 그 프로세스 |
| T2 | 하네스의 spawn 호출 offset(OS exec 시각 아님) | `process_start_offset_seconds` | 하네스 캠페인 시작 |
| T3 | 시도 완료 offset(결과 저장 뒤). 그 시도의 모든 후보에 대한 상한 | `completion_offset_seconds` | 하네스 캠페인 시작 |
| T4 | 검토 완료시각(UTC)과 검토 시간 | 새 필드 | 벽시계 |
| L | 과거 로그 관측시각. P2 통째 lane은 "NOT SAFE" 줄을 읽은 시각, `time.time()` 기준 | P2 ledger | 그 프로세스, 벽시계 |

- **후보 생성시각을 T2+T1로 쓰는 조건:** T1 원문을 보존하고 초로 해석했으며, 후보 파일이 그 시도의 출력임을 해시와 경로로 확인했고, spawn에서 `start()` 진입까지의 지연을 기록하거나 상한을 명시한 경우. 하나라도 빠지면 T3 상한을 쓰고 `basis = attempt-completion-upper-bound`로 둔다.
- 모든 시간 열에는 `basis` ∈ {`spawn+engine-elapsed`, `attempt-completion-upper-bound`, `legacy-log-observation`, `unknown`}과 `basis_verified`를 붙인다.
- 방식끼리 비교할 때는 같은 기준만 쓴다. 한쪽에 T1이 없으면 둘 다 T3로 비교하거나, 두 기준의 결과를 따로 보고한다.
- A 정책의 단위 시간은 캠페인 시작부터의 offset이다. 시도 사이의 하네스 오버헤드를 포함한다.
- T4를 발견시간으로 쓰지 않는다. 미관측을 0으로 쓰지 않는다. 선행 미검토 후보가 있으면 "최초"라고 하지 않는다.

## 7. 투영과 wrapper 의미 보존에 아직 필요한 증거

구현이 있다는 사실만으로 다음을 인정하지 않는다. 결정용 기록 §2는 첫 분기 투영을 검토 방법의 **가설**로 둔다.

- **P1 정상 계산.** 같은 입력으로 고정 생성기를 실행해 얻은 정상 witness가 고정 제약을 만족해야 한다. 만족하지 않으면 그 단위는 과잉 제약 의심·`unknown`이다.
- **P2 신호 대응.** zkFuzz 심볼 이름 ↔ SYM ↔ wire 대응의 범위(대응됨, 최적화로 제거됨, 대응 없음 개수). 경계 신호가 하나라도 대응되지 않으면 국소화는 `failed`다.
- **P3 인스턴스 순서.** 탐색의 `instance_key`·`parent_instance_key` 트리가 컴파일된 SYM의 컴포넌트 계층과 일치해야 한다. 탐색이 불완전하면 `failed(discovery-incomplete)`다.
- **P4 검사할 제약 집합.** 인스턴스의 확인에 어떤 제약을 쓰는지 고정한다. entrypoint R1CS에는 제약마다 소속 인스턴스가 기록되지 않는다. 참조 신호로 추정할 수는 있지만 최적화 뒤에는 정확하지 않을 수 있다. 그래서 같은 템플릿·인자의 wrapper R1CS에 이름을 바꿔 대입하는 방식이 현실적이다. 그러려면 아래 W1–W3가 필요하다.
- **P5 절차 자체의 검증.** 정답 인스턴스가 구성상 알려진 비보안용 합성 회로에서 국소화가 맞는지, `multi`·제거 신호·root에서 올바르게 실패하는지 확인한다.
- **W1 동일성.** 템플릿 소스 해시, 구체 인자, include closure 해시, 컴파일러 해시와 인자가 wrapper 컴파일과 entrypoint 컴파일에서 같다는 기록.
- **W2 인터페이스.** 입출력 신호 이름, 배열 모양, 순서의 일치.
- **W3 제약·계산의 일관성.** 국소화된 인스턴스의 문맥 내 정상값이 wrapper R1CS를 만족하고, 같은 입력으로 wrapper를 정상 계산하면 문맥 내 정상 출력이 재현돼야 한다. 실패하면 그 인스턴스는 `unknown(context-specialized)`이다. 최적화가 호출자의 상수를 인스턴스 안으로 전파했을 수 있다.
- **W4 주장 범위.** 검사한 인스턴스와 입력에서의 관계만 주장한다. 호출자 제약 보존이나 모든 입력에 대한 동등성은 주장하지 않는다.

P1·W3는 정상 계산(witness 생성)을 실행해야 한다. 퍼징은 아니지만 결정용 기록 §4의 "새 개발 실행"에 해당하므로 대상·범위를 착수 기록에 남겨야 한다.

## 8. 비보안용 합성 fixture로 확인할 오류 사례

값 없는 JSON 기록과, 필요하면 결함과 무관한 장난감 회로만 쓴다. 실제 결함 재현 자료는 만들지 않는다.

| ID | 입력 | 기대 동작 |
|---|---|---|
| F1 | 통째·분할 시도, 후보, 검토가 모두 있는 정상 연결 | 모든 키가 일관되게 연결 |
| F2 | seed, T1, CPU 등이 빠진 기록 | `unknown(reason)`. 0으로 채우지 않음 |
| F3 | HEAD 형식의 과거 outcome·review 기록 | 읽기만 하며 원본 해시가 변하지 않음. 새 필드는 `unknown(legacy-format)` |
| F4 | 같은 내용의 후보가 두 시도에서 나옴 | 후보 1개, 출현 2개 |
| F5 | 두 seed 또는 상·하위 조각에서 같은 원인 | 원인 1개, 출현 2개 |
| F6 | 한 타깃에 spec 두 개, 후보 하나 | `ambiguous`. 원인 2개로 세지 않음 |
| F7 | `KnownDefectSingleTarget` binding만 있는 확인 | `binding_match = true`, 귀속은 `not-attempted`. 고유 원인 수에 미포함 |
| F8 | 통째는 T1이 있고 분할은 T3만 있음 | 비교 시 기준 불일치 표시. 공통 기준으로만 비교 |
| F9 | t=5 후보 미검토, t=9 후보 확인 | "t=9, 선행 미검토 1건". 최초로 표시하지 않음 |
| F10 | 통째 후보의 신호 대응 누락 | `localization failed(reason)`. `not-confirmed` 아님. entrypoint TCCT 층은 따로 기록 가능 |
| F11 | 컴포넌트 확인 뒤 귀속 실패 | 확인·미귀속 표에만 들어감 |
| F12 | 검토 상한 도달·worker 중단 | `aborted`·`review-error`. 단위 이진값은 `unknown-incomplete` |
| F13 | 분기 인스턴스 둘 | `multi`. 원인별 근거 없이는 미귀속 |
| F14 | 분기가 root에만 있음 | `root`, `root_only = true`. 분할 쪽 손실 후보로 표시 |
| F15 | `runtime-error`로 끝난 시도 | 의미상 abort로 세지 않음 |
| F16 | 계약 층에서 전제 위반 | 계약 층 `not-confirmed(전제 위반)`. 일반 층은 변하지 않음 |
| F17 | A 정책: 시도 셋, 마지막 시도가 잔여 할당으로 잘림 | `allocation-exhausted`, 미사용 할당 계산. B 정책 기록은 `plan-exhausted`와 미사용 할당 |
| F18 | 과거 `ConfirmationScope::Project` 기록 | 새 층으로 옮기지 않고 원래 의미로 보존 |
| F19 | 후보의 zkFuzz revision이 `unknown` | 버리지 않고 `unknown`과 이유를 기록 |
| F20 | P2형 ledger(`found`, `found_at_seconds`) | `location_match`, `basis = legacy-log-observation` 또는 상한. 확인으로 세지 않음 |

## 9. 구조 테스트만으로 입증할 수 없는 것

- 첫 분기 인스턴스가 실제 원인이라는 것, 국소화의 정확도.
- wrapper와 문맥 내 인스턴스의 의미 동등성.
- T1과 하네스 시계의 정렬, 후보 생성시각의 정확도.
- A 정책의 공정성, 두 방식의 실제 자원 사용 동등성.
- 일반 TCCT 기준이 알려진 원인을 포착하는지, 귀속 절차의 정확도.
- 두 lane이 같은 하네스로 같은 조건에서 실행됐다는 사실(P2는 아님).
- 통째 후보가 같은 수준까지 검토될 수 있다는 사실. 현재 자료에는 통째 후보가 없다.

## 10. N4-1 관문

**10a 기록 경로 관문(구조).** 지금 통과할 수 있다. 조건은 다음과 같다.
1. 2절의 기록과 열거값이 구현되고, 모든 결측에 `unknown(reason)`이 남는다.
2. HEAD 형식의 outcome·review 기록과 P2형 ledger를 원본 수정 없이 읽는다(읽기 전후 해시가 같음).
3. F1–F20 테스트가 통과한다.
4. 4절의 금지 집계를 코드가 거부한다.
5. `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 통과한다.

**10b 의미 관문.** 현재 자료로는 통과할 수 없다. 필요한 것은 다음과 같다.
1. 개발 자료의 통째 후보 1건 이상. 새 개발 실행 착수 기록이 필요하다.
2. 일반 TCCT 판정(정상 재계산) 구현과 합성 회로 검증.
3. 그 통째 후보와 분할 후보 1건 이상이 같은 경로로 P1–P5와 W1–W3를 거쳐 같은 수준까지 판정됨.
4. 두 lane의 시간 기준 검증. 안 되면 두 lane 모두 T3 상한.
5. A 정책이 같은 하네스에서 두 lane에 동작하고, 할당과 실제 사용이 기록됨.

**지금 자료로 확인할 수 있는 것.** v1–v3 검토 기록을 새 경로로 읽기(binding 귀속 표시, `Disposition` 변환, T2·T3 존재, T1 원문 보존). P2 ledger 세 형식의 읽기(하네스 차이, 위치 일치, 시간 기준 차이 표시). P2 분할 후보는 엔진 검토 기록이 없으므로 일반 층을 `not-started`로 둔다. 2026-09-30의 소스 기반 분류는 검토 결과가 아니라 과거 주석으로만 연결한다.

**남는 것.** 10b 전체. 기록 경로가 통과해도 비교 가능성 관문(K1)은 판단할 수 없다. 10a 통과를 "통째 후보의 의미 검증 성공"이나 "N4-1 통과"로 표현하지 않는다.

## 11. 필수 수정과 선택 개선

**필수**
- **M1.** `binding_match`와 원인 귀속을 분리한다. binding만 있는 확인은 고유 원인 수에서 뺀다(0·1절, F7).
- **M2.** 분기 국소화와 귀속을 두 방식에 같은 절차로 적용한다(3·5절, F5).
- **M3.** 후보 하나는 원인 하나까지 기여한다. 다중 원인은 원인별 근거가 있을 때만 센다. spec이 여럿이면 `ambiguous`(F6·F13).
- **M4.** 모든 시간에 기준 태그를 붙이고, 최초 시간은 선행 미검토 규칙을 따른다(6절, F8·F9·F20).
- **M5.** 검토 상태와 결과를 분리하고, 단위 이진값은 다섯 상태로 둔다(2.4·4절, F12).
- **M6.** 할당·실제 사용·시도 종료·캠페인 종료·정책 ID를 분리한다(2.2절, F17).
- **M7.** 과거 형식은 읽기 전용 어댑터로 읽는다. 과거 범위와 `found`의 의미를 보존한다(F3·F18·F20).
- **M8.** 10a와 10b를 따로 보고한다. 10a만으로 N4-1 통과라고 하지 않는다.

**선택**
- **O1.** 검토 기록에 방식 가림 여부(`reviewer_blind`)를 둔다. 결정용 기록 §1의 O4 보류와 충돌하지 않도록 필드만 둔다.
- **O2.** T1 해석기의 버전과 단위 표를 기록한다.
- **O3.** 정상 재계산·국소화의 자동 비용을 검토 비용에 따로 넣는다.
- **O4.** `call_path`와 호출 위치 목록을 지금부터 연결해, 3단계 맥락 판정에서 다시 만들지 않게 한다.
