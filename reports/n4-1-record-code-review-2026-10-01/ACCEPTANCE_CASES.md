# N4-1 기록 경로 수정 판정 사례 (2026-10-01)

**용도.** [코드 검토](REVIEW.md) F1–F13의 수정 여부를 판정할 값 없는 합성 입력과 기대 결과다. **이 문서는 수정 완료나 검증 통과를 선언하지 않는다.** 구현 완료 보고가 오면 이 사례들을 수정본에 적용해 판정한다.

- **도출 근거.** 기대 결과는 다음 문서에서 도출했다.
  - [N3 채택 결정](../../docs/scope_decision_accepted_2026-10-01.md) `f97db998…`
  - [결정용 기록](../../docs/scope_decision_final_2026-10-01.md) §2–3 `85bda940…`
  - [N4-1 계약 검토](../n4-1-review-contract-2026-10-01/REVIEW.md) `b8691e5c…`
  - 코드 검토 `1c5fa0b1…`

  지금 수정 중인 코드는 읽지 않았다. 각 사례의 "v1" 줄은 검토 사본을 정적으로 추적한 결과다(파일 해시는 [REVIEW.md](REVIEW.md) 머리말).
- **알고리즘을 강제하지 않는다.** 첫 분기 국소화는 필수 알고리즘이 아니다. 국소화·투영은 방법을 가리지 않고, 방법 식별자와 근거 참조가 기록됐는지만 본다.
- **아래 어느 것도 의미 검증이 아니다.** 방법 이름 등록, 증거 파일 해시 일치, 구조 테스트 통과, 원인 연결의 존재. 모든 사례를 통과해도 원인 연결은 "신고된 주장"이다.

## 0. 공통 합성 자료

| 기호 | 내용 |
|---|---|
| `U1` | 요청이 선언한 실행 단위 ID |
| `R1`, `R2` | UUID 형식의 합성 run ID |
| `T1`, `T9` | target ID |
| `Ha`, `Hb`, `Hc` | 후보 해시(`a`·`b`·`c`×64). 후보 파일은 만들지도 열지도 않는다 |
| `C1`, `C2`, `C9`, `C1-alias` | 신고된 원인 라벨 |
| `I1`, `I2` | 인스턴스 키 |
| `E1`… | 의미 없는 값 없는 JSON 증거 파일. 요청 기준 경로에 실제로 만들고 해시를 맞춘다 |
| `REG` | 허용된 귀속 방법 하나(합성 ID). 위치·binding·라벨 일치 유형이 아니다 |
| `O1` | experiment-outcome 원본. 아래 목록 참조 |

`O1`의 내용:
- 필드: `outcome_id`, `plan_sha256`, `zkfuzz_binary_sha256`, `execution_mode: "ranking-separated"`, `budget_seconds_per_target: 20`, `total_budget_seconds: 60`.
- `scheduler.elapsed_seconds: 21.0`.
- run 하나: `target_id: T1`, `index: 0`, `process_start_offset_seconds: 0.1`, `completion_offset_seconds: 3.4`, `result.run_id: R1`, `status: bug_found`, `wall_time_seconds: 3.0`, `budget_seconds: 20`.
- 후보 참조: `counterexample_candidates`에 `(R1, T1, Ha)`.

**기준 관측 `OBS(id, 후보, 원인)`**
- 층과 판정: general 층, component reported-confirmed(근거 `E1`), entrypoint TCCT not-attempted.
- 국소화: localized(`I1`), 방법 ID 기록, 근거 `E2`.
- 투영: 방식별 규칙(F9)을 만족한다. split이면 해당 없음과 사유.
- 귀속: matched, 방법 `REG`, 원인 라벨, 근거 `E3`.
- 그 밖: 중복 canonical, 완료 complete, 위반 유형 output-difference와 그 근거 `E4`(F8 수정 뒤의 필드).

**B0 양성 대조.** 요청은 `O1` + 방식 split + `OBS(o1, Ha, C1)`이다.
- 기대: 가져오기가 성공하고, 원인 연결은 `{C1: [o1]}`이며, 연결에 "신고된 주장·의미 검증 unknown"이 표시된다.
- **모든 수정은 B0를 계속 통과해야 한다.** 모든 연결을 막거나 모든 요청을 거부해서 음성 사례를 통과하는 구현은 수정으로 인정하지 않는다. 허용 방법이 하나도 없어 어떤 연결도 만들 수 없는 구현도 마찬가지다.

v1에 없는 필드(위반 유형, 국소화 방법, wall 범위, 시간 기준 등)는 이름이 달라도 된다. 다만 의미가 기계적으로 구분되고, 문서에 대응 관계가 적혀 있어야 한다.

## 1. 모든 사례에 적용할 불변식

| ID | 불변식 |
|---|---|
| I1 | 원본·요청·검토 보고서 바이트는 바뀌지 않는다. 출력은 새 파일 하나이고, 거부되면 출력 파일이 생기지 않는다 |
| I2 | 원인 연결은 다음을 모두 만족할 때만 생긴다: general 층, 완료, component reported-confirmed, 허용된 귀속 방법, metadata binding true, 국소화 주장(방법·근거) 기록, 위반 유형 기록, 기록 안의 canonical 기준점(F2) |
| I3 | 한 후보 해시는 원인 키 하나에만 나타날 수 있다 |
| I4 | entrypoint TCCT·계약·legacy·프로젝트 의미 결과는 컴포넌트 원인 연결과 원인 수에 들어가지 않는다 |
| I5 | not-started·in-progress·interrupted·error·unresolved·투영/귀속 실패는 "검토 완료·미확인"(음성)으로 집계되지 않는다. complete + unresolved도 확정 판정이 아니다 |
| I6 | 원인 수는 canonical 기준점이 있는 원인 키의 수다. 후보·관측·seed·시도·호출 위치·방식의 수로 대신하지 않는다 |
| I7 | 기준이 다른 시간은 같은 열에서 비교하거나 최솟값을 내지 않는다. 근거 없는 정확 생성시각은 known이 아니다. 확인 후보가 없으면 시간은 0이 아니라 미관측이다 |
| I8 | 할당과 실제 사용을 분리하고, 실제 사용에는 시도/캠페인 범위를 붙인다. 할당−사용으로 잔여를 추정하지 않고, wall 값으로 CPU를 채우지 않는다 |
| I9 | 방법 등록·증거 해시 일치·국소화 방법 기록은 의미 검증 상태를 known으로 만들지 않는다 |
| I10 | 요청이 선언한 값과 원본에서 관측한 값은 출처로 구분된다 |
| I11 | 결과(원인 키와 구성원)는 관측의 입력 순서에 의존하지 않는다. 목록 안의 순서는 무관하다 |

## 2. 사례

### F1 — binding·위치뿐인 귀속

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F1-a | B0에서 귀속 방법만 바꾼다: `location-match`, `single-target`, `known-defect-target`, `p2-found`, `ground-truth-location`, `target-binding`, `KnownDefectSingleTarget`, `known-defect-binding-matched`, 미등록 이름 `evidence-review-v2` | 이름마다 귀속이 attributed가 아니다. 원래 방법 문자열은 보존된다. 원인 연결 `{}` | 어느 이름으로든 원인 키 생성 |
| F1-b | B0 그대로(방법 `REG`) | `{C1: [o1]}`. 의미 검증 unknown | 연결이 "검증됨"으로 표시됨 |
| F1-c | 허용 목록이 설정이나 규칙 파일이면, 위치·binding·라벨 일치 유형을 등록하려는 입력. 코드 열거형이면 해당 없음 | 거부되거나, 그 방법이 attributed를 만들지 못한다. 허용 목록의 출처(해시)가 출력에 남는다 | 등록만으로 위치 일치가 귀속이 됨 |
| F1-d | 과거 v3 보고서의 `known-defect-binding-matched` 행 | 귀속 unknown, 원본 행 보존, 연결 `{}` | 승격 |

- **v1:** F1-a에서 `binding`이 들어간 둘(`target-binding`, `known-defect-binding-matched`)과 `KnownDefectSingleTarget`은 막힌다. 나머지 여섯 이름(`location-match`, `single-target`, `known-defect-target`, `p2-found`, `ground-truth-location`, `evidence-review-v2`)은 `{C1:[o1]}`가 된다. F1-d는 통과한다.
- **수정 기준:** 귀속 여부를 철자 거부목록이 아니라 허용 방법 집합으로 판단한다. F1-a의 모든 이름이 막히고, 동시에 B0와 F1-b가 통과한다.

### F2 — 기록 안에 없는 중복 대상

**canonical 기준점 규칙:** 원인 라벨 K는, 기록 안에 eligible이고 canonical이며 귀속 라벨이 K인 관측이 있을 때만 키가 된다. `duplicate-of: K` 관측은 K에 기준점이 있을 때만 K 아래에 연결된다.

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F2-a 별칭 분리 | `OBS(o1, Ha, C1)`, 그리고 `OBS(o2, Hb, C1)`의 중복만 `duplicate-of: C1-alias`. `O1`에 `(R1, T1, Hb)` 추가 | `{C1: [o1]}`. o2는 연결 밖이고 issue("중복 대상에 기준점 없음")가 남는다 | `C1-alias` 키, 키 2개, 원인 수 2 |
| F2-b 없는 대상 | `OBS(o1, Ha, C1)`의 중복만 `duplicate-of: C9` | `{}`와 issue | `C9` 키, o1을 C1 canonical로 연결 |
| F2-c 정상 중복 | o1 canonical C1, o2(`Hb`) 귀속 C1·`duplicate-of: C1` | `{C1: [o1, o2]}`, 원인 수 1 | 키 2개, o2 누락 |
| F2-d 라벨 불일치 | o1 canonical C1, o2(`Hb`) 귀속 C2·`duplicate-of: C1`, 중복 근거 없음 | o2는 연결 밖이고 issue가 남는다. 중복 판단의 근거 참조를 따로 기록하는 구현이면 o2를 C1 아래에 둘 수 있다 | `C2` 키, 키 2개 |
| F2-e 기준점 없는 순환 | o1(`Ha`) 귀속 C1·`duplicate-of: C2`, o2(`Hb`) 귀속 C2·`duplicate-of: C1`, canonical 없음 | `{}`와 issue, 정상 종료 | 키 생성, 무한 반복이나 비정상 중단 |
| F2-f 입력 순서 | F2-c에서 o2를 o1보다 앞에 둔다 | F2-c와 같은 키·구성원 | 순서에 따라 키가 달라짐 |

- **v1:** F2-a는 `{C1:[o1], C1-alias:[o2]}`, F2-b는 `{C9:[o1]}`, F2-d는 `{C1:[o1, o2]}`, F2-e는 `{C1:[o2], C2:[o1]}`이다. F2-c와 F2-f는 통과한다.
- **수정 기준:** F2-a–f가 위 기대를 모두 만족한다. 중복 표시는 원인 키를 새로 만들지 못한다.

### F3 — unresolved가 섞인 원인 충돌

**충돌 집합:** 같은 후보 해시에서 귀속이 matched인 모든 관측의 원인 라벨(귀속 라벨과 중복 대상)을 모은다. 층·중복 상태·eligible 여부와는 무관하다. F1 정규화 뒤 binding뿐인 귀속은 matched가 아니므로 빠진다. 집합의 크기가 2 이상이면 그 후보의 모든 관측을 연결에서 뺀다.

| 사례 | 최소 입력(모두 같은 후보 `Ha`) | 기대 | 금지 |
|---|---|---|---|
| F3-a | o1 canonical C1, o2 귀속 matched C2·중복 unresolved | Ha의 관측 모두 연결 밖, Ha에 ambiguous issue, 두 행 보존 | `{C1: [o1]}` |
| F3-b | o1 general canonical C1, o2 contract 층 matched C2 | F3-a와 같음 | C1 연결 |
| F3-c | o1 canonical C1, o2 귀속 not-matched(제안 라벨 C2) | `{C1: [o1]}`, 충돌 아님 | ambiguous 처리로 C1 손실 |
| F3-d | o1 canonical C1, o2 귀속 matched C1·중복 unresolved | `{C1: [o1]}`. o2는 보존 | 키 2개, o2를 다른 원인으로 셈 |
| F3-e (후속 집계) | F3-a 기록 하나뿐인 단위 | 그 후보는 "확인·미귀속(모호)"이고, 단위 상태는 "확인·미귀속만" | C1 확인으로 집계, 단위를 "확인·귀속"으로 표시 |

- **v1:** F3-a와 F3-b는 `{C1:[o1]}`이고 issue가 없다. F3-c와 F3-d는 통과한다.
- **수정 기준:** 충돌 판단이 위 충돌 집합으로 이뤄지고, 양성 대조 F3-c·F3-d가 유지된다.

### F4 — 요청 ID와 관측 ID

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F4-a | runner-result 원본이 실제 `RunResult` 모양(`run_id: R1`, `target_id` 필드 없음)이고, 요청은 `target_id: T1` | 관측 target은 unknown("원본에 target_id 없음"). 요청의 T1은 요청 출처로 따로 기록된다. metadata binding은 true가 아니다 | 관측 target이 known T1 |
| F4-b | F4-a에 R1의 과거 보고서 행(target T1)을 더함 | 행을 가져오면 선택 근거가 "요청이 주장한 target"으로 표시되거나, 관측 ID가 없어 가져오지 않았다는 사유가 남는다 | 관측 일치처럼 표시 |
| F4-c | runner-result에 `target_id: T9`, 요청 T1 | 거부(충돌) | T1으로 기록 |
| F4-d | `O1`(`execution_mode: ranking-separated`), 요청 split | 원본의 whole/split 방식은 unknown("outcome은 방식을 기록하지 않음")이고, execution_mode는 별도 필드에 보존된다 | 방식 필드에 `ranking-separated` |
| F4-e | `O1`, 요청 `run_id: R1` | 관측 target T1(스케줄러 항목 출처), run 일치 | — |

- **v1:** F4-a는 관측 target이 known T1, F4-b는 요청 target으로 행을 선택하면서 출처를 표시하지 않는다. F4-d는 `source_method`가 known `ranking-separated`다. F4-c와 F4-e는 통과한다.
- **수정 기준:** 모든 ID·방식·반복 값이 요청 출처인지 원본 출처인지 구분된다. F4-a·b·d가 기대를 만족한다.

### F5 — P2 lane과 하네스

P2 설정의 lane 대응: `whole` → whole, `small-first`·`path-order`·`random` → split. (`risk-only`·`cost-aware`는 P2에서 제외된 전략이다.)

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F5-a | ledger `lane: path-order`, 실행 `{block: 1, found: true, found_at_seconds: 7.0, elapsed_seconds: 203.0, status: bug_found}`, 요청 whole | 거부(방식 충돌) | 성공 |
| F5-b | 같은 ledger, 요청 split·반복 1 | 성공. 후보 시간 7.0의 의미는 "정답 라벨 조각들의 완료 offset 최솟값, 캠페인 시작 기준 상한"으로, small-first·random과 같다. lane 문자열 보존 | "의미 미확인", 로그 수신 시각이라는 의미 |
| F5-c | `lane: mystery-lane`, 요청 split | 거부. 또는 성공하되 "방식이 원본으로 확인되지 않음"과 "시간 의미 미확인"을 기록 | 요청 방식이 원본으로 확인된 것처럼 기록, 완료 상한·로그 수신 의미 부여 |
| F5-d | split ledger에 `runner: direct` | 하네스 = P2 직접 실행(ledger 출처 표시) | 하네스를 zkfDO 실행으로 기록, whole lane과 같은 하네스로 기록 |
| F5-e | `found: true`, `found_at_seconds` 없음 | 시간 unknown(사유). 정답 위치 일치는 확인 성과가 아니다 | 시간 0, 확인으로 승격 |

- **v1:** F5-a는 성공한다(오류). F5-b의 시간 의미는 "unverified"다. F5-c는 성공하지만 방식이 원본으로 확인되지 않았다는 표시가 없다. F5-d는 하네스 unknown이다. F5-e는 통과한다.
- **수정 기준:** 실제 lane 값 넷이 모두 대응되고, 모르는 lane은 거부되거나 명시적으로 미확인이 된다.

### F6 — 시도/캠페인 범위의 시간과 자원

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F6-a | F5-b의 ledger(`elapsed_seconds: 203.0`) | 캠페인 범위 실제 wall 203.0. 시도 범위는 unknown("ledger는 캠페인 경과만 기록") | 시도 범위 203.0, 범위 없는 wall 203.0 |
| F6-b | `O1` | 시도 범위 wall 3.0. 캠페인 범위는 `scheduler.elapsed_seconds` 21.0을 캠페인 범위로 기록하거나 unknown | 캠페인 범위 3.0 |
| F6-c | runner-result(`wall_time_seconds: 3.0`) | 시도 범위 3.0, 캠페인 범위 unknown | 캠페인 범위 3.0 |
| F6-d | P2 whole ledger(`elapsed_seconds: 600.0`) | 캠페인 범위 600.0. 시도 범위는 "단일 프로세스 lane"이라는 근거와 함께 600.0이거나 unknown | 근거 없이 시도 = 캠페인 |
| F6-e 후보 시간 기준 | F6-c와 F6-b의 후보 시간 | runner-result의 3.0은 시도 시작(runner 진입) 기준 상한, `O1`의 3.4는 스케줄러 시작 기준 상한이다. runner-result에서는 캠페인 기준 시간이 unknown | 두 값을 같은 기준 열에 놓거나 비교 |
| F6-f 할당 | `O1` | 시도 할당 20, 캠페인 할당 60. 잔여·CPU·메모리 unknown | 잔여 = 60 − 3.0, CPU = 3.0 |
| F6-g (후속 집계) | 같은 캠페인의 A형 기록 둘. 시도 1: R1, 캠페인 offset 0.0 시작, 10.0 완료, 후보 없음. 시도 2: R2, 10.5 시작, 20.0 완료, 후보 `Ha` 확인·귀속 | 캠페인 할당은 한 번만 반영된다. `Ha`의 시간은 캠페인 기준 상한 20.0이다. 캠페인 실제 wall은 캠페인 경과 20.0이거나 unknown | 시도 할당의 합을 캠페인 할당으로 씀, 시도 기준 9.5를 캠페인 시간으로 씀, 시도 wall 합 19.5를 캠페인 wall로 씀 |

- **v1:** F6-a·b·c는 범위 표시가 없는 단일 `actual_wall_seconds`다. F6-e는 의미 문자열이 다르지만 기계적으로 읽을 기준이 없다(F13). F6-f는 통과한다. F6-g는 v1에 기능이 없다.
- **수정 기준:** 실제 사용량과 시간마다 범위·기준이 기계적으로 구분된다. F6-a–f를 만족하고, 후속 집계가 생기면 F6-g도 만족한다.

### F7 — 과거 판정의 정규화

모든 과거 행은 legacy 층에 머문다. 귀속 matched(binding)는 unknown이 되고, 원인 연결은 없다. entrypoint TCCT는 모든 scope에서 not-attempted다. project scope의 도달성은 과거 정보로만 보존한다.

| 과거 disposition | 정규화된 component(original-component·project·wrapper-only·reachability-unknown 모두) |
|---|---|
| validated(기준 모두 satisfied, 산출물 검증, 실패 제약 0) | legacy reported-confirmed. scope 원문 보존 |
| validated이지만 산출물 검증 누락 또는 실패 제약 > 0 | reported-confirmed로 올리지 않음(unresolved 또는 error) |
| rejected | rejected + 실패한 기준 ID. 입력 전제만 실패했다면 "계약 전제 불충족"으로 구분 |
| unresolved | unresolved. 완료됐지만 확정 판정이 아님 |
| review-error | error |

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F7-a | v3 값 없는 보고서 사본의 행을 `expected_scope: project`로 바꾼 합성 보고서 | 위 표대로 legacy reported-confirmed, scope `project` 보존, 연결 `{}` | component not-attempted, entrypoint TCCT나 프로젝트 의미 확인, general 층 |
| F7-b | 같은 행의 scope를 `wrapper-only`, `reachability-unknown`으로 바꿈 | 위 표대로 | 위와 같음 |
| F7-c | rejected 행. `input_preconditions`만 not-satisfied | rejected + 실패 기준 `input_preconditions`(계약 전제) | general 층 음성, 맥락 배제·오탐으로 해석, 단위 집계의 "완료·미확인" 근거로 사용 |
| F7-d | unresolved 행(속성 기준 unknown) | unresolved, 확정 아님 | 단위 집계에서 완결된 음성 |
| F7-e | review-error 행 | error | 음성 |

- **v1:** F7-a·b는 component가 not-attempted다(오류). F7-c는 실패 기준 없이 rejected다. F7-d는 unresolved + complete로 표현되며, 후속 집계에서 지켜야 한다. F7-e는 통과한다.
- **수정 기준:** 네 scope 모두 위 표를 따르고, 실패 기준이 정규화된 기록에서 읽힌다. project scope 테스트가 있다.

### F8 — 위반 유형: 출력 차이형과 abort형

유형은 output-difference, computation-abort, tool-specific-check, unknown이다. 근거 조건은 유형마다 다르며, 모두 참조일 뿐 의미 검증은 아니다.
- **output-difference:** 같은 입력에서의 정상 계산 결과에 대한 참조와, 차이가 난 컴포넌트 출력의 식별.
- **computation-abort:** 정상 계산이 abort했다는 근거 참조(인스턴스와 assertion 식별). 출력 필드는 요구하지도 채우지도 않는다.
- **tool-specific-check:** 검사 경고만으로는 일반 TCCT 위반이 아니다(결정용 기록의 별도 검사 규칙).

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F8-a | B0에서 유형 computation-abort + abort 근거 `E5`, 출력 근거 없음 | 연결 가능(신고된 주장), 유형 보존 | 출력 값을 만들어 채움 |
| F8-b | 유형 computation-abort인데 출력 차이 근거만 있음 | 연결 밖. 사유 "abort 근거 없음" | 연결 |
| F8-c | 유형 output-difference인데 정상 계산 참조가 없음 | 연결 밖 | 연결 |
| F8-d | general reported-confirmed인데 유형이 unknown이거나 없음 | 연결 밖 | 연결 |
| F8-e | `O1`의 status를 `runtime_error`나 `timeout`으로 바꿈 | 종료 사유만 기록된다. 어떤 관측에도 abort 유형이 추론되지 않는다 | 도구 오류·시간 초과를 abort로 분류 |
| F8-f | 유형 tool-specific-check | general 연결 밖(별도 집계) | general 원인 연결 |
| F8-g | 과거 행의 `violation_class` 문자열 | legacy 문자열로만 보존, general 유형은 unknown | general 유형으로 변환 |

- **v1:** 유형 필드가 없어 F8-b·c·d·f가 B0처럼 연결된다. F8-e와 F8-g는 통과한다.
- **수정 기준:** 유형 열거값과 유형별 근거 조건이 있다. F8-a는 연결되고 F8-b·c·d·f는 빠진다.

### F9 — 방식별 일관성

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F9-a | 방식 whole, localized `I1`, 투영 not-attempted | 연결 밖(unresolved 또는 issue) | 연결 |
| F9-b | whole, 투영 reported-confirmed + 근거, 투영 방법 ID 아무거나(예: `synthetic-projector`) | 연결 | 특정 투영 알고리즘이 아니라는 이유로 배제 |
| F9-c | split, 국소화 root | 거부, 또는 연결 밖 + 사유("조각에는 entrypoint root가 없음") | root 원인으로 연결 |
| F9-d | whole, root + 투영 reported-confirmed | 연결, root 표시. 같은 후보의 entrypoint TCCT 결과는 따로 유지 | 컴포넌트와 entrypoint TCCT를 합산 |
| F9-e | split, localized `I2`(조각 자신 또는 하위 인스턴스), 투영 해당 없음 + 사유 | 연결 | — |

- 투영을 국소화에 합친 설계도 허용한다. 다만 whole에서는 통째→컴포넌트 단계의 근거가 기록돼야 하고, 대응 관계가 문서에 있어야 한다.
- **v1:** F9-a와 F9-c가 연결된다(오류). F9-b·d·e는 통과한다.
- **수정 기준:** F9-a·c가 빠지고 F9-b·d·e가 연결된다. 판정 근거는 방식과 근거 기록이지 알고리즘 이름이 아니다.

### F10 — 국소화 방법과 검증 상태

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F10-a | localized, 방법 `first-divergence`, 검증 unknown | 연결 가능. 연결에 방법과 "방법 검증 unknown"이 보인다 | "검증된 국소화"로 표시 |
| F10-b | localized, 방법 `synthetic-localizer-b` | F10-a와 같은 판정 | 첫 분기가 아니라는 이유로 다르게 판정 |
| F10-c | localized인데 방법이 기록되지 않음 | 연결 밖. 사유 "국소화 방법 미기록" | 연결 |
| F10-d | 요청이 국소화 방법을 "검증됨"으로 선언하고 검증 기록 참조가 없음 | 거부되거나 검증 상태 unknown. 참조가 있으면 "검증 주장(참조)"으로만 기록 | 검증 상태 known |

- **v1:** 방법 필드가 없어 F10-a·b·c가 모두 같은 근거 없이 연결된다. 연결에 상태 표시가 없다.
- **수정 기준:** 방법 식별과 검증 상태가 연결마다 보이고, 판정은 알고리즘 종류와 무관하다.

### F11 — run/target 충돌과 보고서 중복

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F11-a | 합성 schema-1 보고서에 R1·target T9 행이 있고, 원본 `O1`은 R1→T1 | 거부. 또는 행 보존 + binding이 true가 아님 + issue("run/target 충돌") | 흔적 없이 누락 |
| F11-b | `O1`의 후보 참조에 `(R1, T9, Hc)` 추가 | 거부, 또는 후보 목록 unknown(사유) / issue. `Hc`를 T1에 연결하지 않음 | 조용한 제외, `Hc`를 T1 후보로 기록 |
| F11-c | 같은 보고서를 `review_reports`에 두 번(해시 소문자·대문자) | 중복 입력으로 거부, 또는 한 번만 반영 | 행이 두 번 들어감 |
| F11-d | 같은 보고서를 같은 표기로 두 번 | 거부(현행 유지) | — |
| F11-e | 관측의 후보 해시를 대문자 `A`×64로 씀(원본은 소문자) | 같은 후보로 처리. binding true, 충돌·연결 판단도 같은 후보로 | 다른 후보로 처리해 F3를 회피 |

- **v1:** F11-a·b는 조용히 빠진다. F11-c는 두 번 들어간다. F11-d와 F11-e는 통과한다.
- **수정 기준:** 충돌은 오류나 issue로 드러나고, 대소문자 차이로 중복이 생기지 않는다.

### F12 — 검토 행이 없는 후보와 단위 상태

단위 상태는 다섯 가지다: 확인·귀속 / 확인·미귀속만 / 완료·미확인 / 후보 없음 / 미완료. 시간 규칙은 결정용 기록 §3을 따른다.

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F12-a | `O1`의 후보 참조 `Ha`·`Hb`(합성 구조 사례), 관측은 `Ha`만(B0) | `Hb`에 명시적 상태 "검토 없음/not-started"와 사유. `Ha`는 C1에 연결 | `Hb`가 상태 출력에 없음, 음성 |
| F12-b | `O1`, 보고서·관측 없음 | 모든 후보 not-started | 상태 없음, 음성 |
| F12-c | R1을 다룬 과거 보고서가 failed(failure 있음, 행 없음) | 후보 상태 failed/interrupted + 보고서 실패 사유 | 상태 없음, 음성 |
| F12-d (후속 집계) | 같은 캠페인의 R2(완료 2.0, 후보 `Hb` 미검토)와 R1(완료 3.4, 후보 `Ha` 확인·귀속) | 단위 = 확인·귀속. 최초 확인 시간은 "상한 3.4, 선행 미검토 1건(상한 2.0)"으로 보고 | "최초 확인 3.4"를 확정값으로 보고 |
| F12-e (후속 집계) | 모든 후보가 not-started인 단위 | 미완료, 시간 미관측 | 완료·미확인, 시간 0 |
| F12-f (후속 집계) | 후보 없이 시도 상한·할당 소진으로 끝난 단위 | 후보 없음 + 종료 사유, 시간 미관측 | 완료·미확인, 시간 0 |

- **v1:** F12-a·b·c는 후보에 상태가 없다. F12-d–f는 v1에 기능이 없다.
- **수정 기준:** 원본이 연결한 모든 후보에 명시적 검토 상태가 있다. 후속 집계가 생기면 다섯 상태와 선행 미검토 규칙을 지킨다.

### F13 — 형식·위생 (선택, 낮음)

| 사례 | 최소 입력 | 기대 | 금지 |
|---|---|---|---|
| F13-a | 다른 outcome을 위해 만든 합성 보고서가 같은 R1·T1·`Ha` 행을 가짐 | 보고서와 원본의 관계는 "미확인"으로 기록된다. 보고서 요청 파일을 함께 주고 그 outcome 해시가 `O1`과 다르면 거부나 issue | 관계를 확인한 것으로 표시 |
| F13-b | 요청을 임의의 로컬 디렉터리에 둠 | 출력에 그 절대 경로가 없다(상대 경로나 입력 그대로) | 절대 로컬 경로 기록 |
| F13-c | 모든 시간·종료 값 | 기준·종료 종류가 열거값으로 있고, 원문 문자열은 따로 보존 | 기준을 얻으려면 설명 문장을 해석해야 함 |

`execution_mode`는 F4-d, P2 `runner`는 F5-d에서 다룬다.

## 3. 회귀 보존 (v1에서 이미 맞는 동작)

[REVIEW.md](REVIEW.md) §0의 "잘 지켜진 것"은 수정 뒤에도 유지돼야 한다.
- 입력 해시 불일치·파일 없음·알 수 없는 요청 필드·음수 정책 값은 거부되고 출력 파일이 생기지 않는다.
- 기존 출력 파일은 덮어쓰지 않는다.
- 음수·비유한 관측값은 거부한다.
- `execution_limit_seconds = 0`은 unknown이다.
- 과거 Matched와 P2 `found`는 승격되지 않는다(F1-d, F5-e).
- canonical 원인 둘이면 ambiguous다.
- `multi`·`failed` 국소화와 계약·legacy 층은 연결되지 않는다.
- interrupted·미검토는 음성이 아니다.
- 정확 생성시각과 정책 실행 검증은 unknown이다.
- 가져오기 출력에 전역 원인 수가 없다.

## 4. 판정 절차

1. 구현 완료 보고를 받은 뒤 수정본에 사례를 적용한다. 각 사례의 입력 파일 해시와 결과를 기록한다. 결과는 통과·실패·해당 없음(예: 후속 집계 기능 없음)·미실행으로 나눈다.
2. F#가 수정됐다고 판단하려면 다음이 모두 필요하다.
   - 그 F#의 모든 사례가 기대를 만족한다.
   - B0와 양성 사례(F1-b, F2-c, F2-f, F3-c, F3-d, F4-e, F5-b, F8-a, F9-b, F9-d, F9-e, F10-a, F10-b, F11-e, F12-a의 `Ha`)가 통과한다.
   - 모든 사례에서 I1–I11이 지켜진다.
3. v1과 수정본의 결과를 나란히 남긴다. v1 줄이 실패로 적힌 사례가 v1에서 재현되지 않으면 사례 입력부터 다시 점검한다.
4. 통과는 기록 경로의 구조 판정일 뿐이다. 의미 관문(통째·분할 후보의 같은 수준 검토, 투영·wrapper 대응, 시간 기준, A 정책 실행)은 [N4-1 계약 검토](../n4-1-review-contract-2026-10-01/REVIEW.md) §10b와 채택 결정 §4대로 남는다.
