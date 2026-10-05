# N4-1 기록·집계 독립 검증 (2026-10-01)

**결론: 수정 후 수용.** 현재 오프라인 기록·집계 범위에서, 이전 코드 검토의 F1·F2·F4·F5·F7·F9·F11·F12는 수정됐고 F6·F10은 집계 단계에서 반영됐다. 그러나 다음 두 가지 중대한 오류가 있다.
- **N1:** 실행 실패나 후보 참조 누락을 "후보 없음·완결"로 만든다.
- **N2:** 같은 run에 대한 기록 간 상충 판정을 숨기고 원인 수를 완결로 낸다.

중간 오류 셋(N3–N5)과 함께 이것들을 고치기 전에는 이 범위를 수용하지 않는다. 이 판단은 N4-1 전체 관문, 의미 관문, A안 실행 공정성의 통과가 아니다.

- **검토 대상 고정:** 2026-10-01T10:04:32Z에 대상 파일을 ignored `runs/n4-1-aggregate-verification-2026-10-01/snapshot/`에 복사하고 `SHA256SUMS`를 남겼다. 10:16:29Z에 다시 비교했을 때 13개 파일 모두 같았다. 이전 v1 사본(`runs/n4-1-record-code-review-2026-10-01/snapshot/`)과는 구분한다.
- **실행 범위:** 코드·기존 문서·계획표는 수정하지 않았다. 실제 회로·후보·witness·predicate는 열거나 실행하지 않았고, ignored 검사도 켜지 않았다.

| 파일 | SHA-256 (검토본) |
|---|---|
| `src/evidence_record/aggregate.rs` | `170b6d2550b4d6c0838c396ec8028950a388f12a3f79d9fc8b7fa6821261cdd2` |
| `src/evidence_record/aggregate_schema.rs` | `35a4f6aaa6e3cfd0fb65af2efdd572d1e46c6fc7cd33a1106982fb672c921318` |
| `src/evidence_record/aggregate_time.rs` | `9ec0c6004616b82c9971432d3e954a7efb725125afe4262a30081c6733dccada` |
| `src/evidence_record/legacy.rs` | `40da5695af888a19a7c54575b3bd917ea55aa69fb63b72a95ce35222b2f17f9f` |
| `src/evidence_record/mod.rs` | `aa42e0de6fbeddb6d833afbd9db6b657ed3289632871167f54d35eacd775aa80` |
| `src/evidence_record/schema.rs` | `b0716db0e7ac185be15b7494e126bb7e5b0fff087628724b7e6e50d4c727ec23` |
| `tests/evidence_record_test.rs` | `c39c4fb1d68178cf80fe38f6b8d6f3aa81dafc96adb219989dc82623fc5f14b6` |
| `tests/evidence_aggregate_test.rs` | `6158986c97b1e582a6f37ff8f8bd96b2c4b75a761122594e3a315245be983c9d` |
| `src/cli.rs` / `src/lib.rs` | `2db8cf44…` / `2bdb9d08…` |
| `docs/evidence_aggregate_v1.md` | `0a345bc997f363fa53a5354d90c108ee2c24e5c50839f9a87033a4b65cd51bdb` |
| `docs/evidence_record_v1.md` | `a880cc31…`(v1 검토 때와 같음) |

## 1. 실행한 검사

| 검사 | 결과 |
|---|---|
| `cargo test --test evidence_record_test` | 32 통과, 0 실패 |
| `cargo test --test evidence_aggregate_test` | 29 통과, 0 실패 |
| `cargo test --lib evidence_record` | 4 통과(legacy 단위) |
| 합성 메타데이터 CLI 검사 | 검토본과 같은 소스로 빌드된 바이너리 사본(`227921c4…`)으로 `experiment record`·`experiment aggregate`를 실행. 입력은 값 없는 JSON뿐이고, 후보·증거 경로는 이름표다. 스크립트와 결과는 ignored `runs/n4-1-aggregate-verification-2026-10-01/work/`(`harness.py`, `harness2.py`, `results*.json`). 아래 사례 이름은 그 결과의 키다 |

전체 `cargo test`·clippy·fmt는 다시 실행하지 않았다. 구현 기록의 전체 285 통과는 이번에 재확인한 결과가 아니다. I4 사례는 기존 테스트처럼 값 없는 v3 보고서 사본의 binding만 바꿔 썼다.

## 2. 이전 F1–F13 수정 확인

| ID | 판정 | 근거(코드·회귀 테스트·합성 사례) |
|---|---|---|
| F1 binding-only | **수정됨** | `mod.rs:477` 허용목록(`manual-cause-review`, `fixed-constraint-rejection`). 집계 `aggregate.rs:275`가 다시 검사한다. I1: 위치·binding·미등록 이름 9개(대소문자 변형 포함)는 모두 귀속 unknown·연결 없음. B0: 허용 방법 둘은 연결됨 |
| F2 중복 대상 | **수정됨** | `mod.rs:505–` `invalid_duplicate_links`, 집계 `valid_duplicate`. I2: 별칭 → `{C1:[o1]}`, 없는 대상 → `{}`, 라벨 불일치 → o2 제외, 순환 → `{}`, 순서를 바꿔도 같은 구성원 |
| F3 unresolved 충돌 | **부분 수정** | general 층 안에서는 수정됐다(`mod.rs:182–196`, I3 `unresolved_dedup` → `{}` + issue). 층을 넘는 충돌은 남는다(N5) |
| F4 요청/관측 ID | **수정됨, 사유 기록은 남음** | `legacy.rs` runner 분기에서 관측 target을 unknown으로 두고, 요청 target은 `source.target_id`에만 남긴다. 회귀 `runner_request_target_remains_a_request_claim…`. 같은 run의 과거 행을 조용히 빼는 문제는 N6 |
| F5 P2 lane | **수정됨** | `path-order` 추가, 모르는 lane은 거부, 집계 단계에서 다시 검사(`aggregate.rs:214–224`). 회귀 `p2_known_lanes…` |
| F6 wall 범위 | **집계에 반영** | `record_contexts.actual_wall_scope`가 runner/outcome은 시도, P2 split은 캠페인, P2 whole은 프로세스로 구분한다. record의 원래 필드는 범위 표시 없이 보존한다. 이를 확인하는 테스트는 없다 |
| F7 과거 판정 | **수정됨** | 모든 scope에서 disposition을 옮기고, reason에 scope·실패 기준·`violation_class`를 남긴다(`mod.rs` `from_legacy`). 회귀 `legacy_scopes…`, `legacy_precondition_rejection…` |
| F8 위반 유형 | **부분 수정** | v2 `review_semantics.violation_kind`와 근거가 귀속의 필수 조건이 됐다. 그러나 증거 목록이 하나뿐이라 유형별 근거 조건은 표현하지 못하고(문서에 명시된 한계), `tool-specific-check`가 general 원인으로 세어진다(N4) |
| F9 방식별 일관성 | **수정됨** | 두 방식 모두 투영 reported-confirmed를 요구하고, split의 Root는 제외한다(`mod.rs:484–`, `aggregate.rs:260–268`). 판정 사례의 F9-e·B0는 split 투영을 "해당 없음"으로 허용했는데, 계약 검토 §3의 대칭 요구에 비춰 그 기대가 느슨했다. 구현이 맞으며, 판정 사례의 그 기대는 이 보고서로 대체한다 |
| F10 국소화 방법 | **수정됨, 낮은 문제 하나** | 방법·검증 상태·근거를 기록하고 방법 결측 시 귀속에서 뺀다. 검증 상태 known(true)가 근거 없이 그대로 출력된다(N7) |
| F11 충돌·중복 | **수정됨** | 같은 run·다른 target이면 거부(`mod.rs:58–` 등). 보고서 해시를 대소문자 무시로 비교해 중복을 거부(`validate_request`). 회귀 `duplicate_report_hash_case…`, `same_run_with_conflicting_target…` |
| F12 검토 없는 후보 | **집계에 반영** | 그 층에 검토가 없는 후보는 unresolved 출현이 된다(`aggregate.rs:744–747`). 반대 방향의 결함은 N1(후보 참조가 없는데 "후보 없음") |
| F13 형식·위생 | **명시된 범위 밖(오류 아님)** | v2 시간 basis는 열거형이 됐다. 다음은 문서 §5에 "남음"으로 명시돼 있다: 절대 경로(`mod.rs:25`, `aggregate.rs:394`·`549`), P2 `runner` 미추출, 보고서-원본 관계 미인증, 종료 문자열 원문 보존 |

## 3. 새로 발견한 오류

### N1 — 높음(수용 차단). 실행 실패·후보 참조 누락이 "후보 없음·완결"이 된다

- **위치:** `aggregate.rs:635–639`(후보 목록 완전성 = 선언만 확인), `842–850`(NoCandidate, NotConfirmedComplete 판정). `legacy.rs:282`(참조가 없어도 inventory를 known으로 둠).
- **최소 조건(A1):** `O1` outcome의 run `R1`이 `status: bug_found`인데 `counterexample_candidates: []`다. v2 기록은 후보·검토 목록 complete를 선언하고(증거 참조 포함), 캠페인 선언도 complete다.
- **기대:** zkfDO에서 `bug_found`는 반례가 나왔다는 뜻이므로, 참조가 없으면 목록 누락이다. 상태는 `unknown-incomplete`와 사유여야 하고, 원인 수는 unknown이어야 한다.
- **실제:** `state: no-candidate`, `review_results_complete: true`, `cause_count_complete: true`, `distinct_cause_count: known 0`, reasons 없음. importer도 이 run의 `candidate_inventory`를 known("…selected…")으로 기록한다(I5).
- **같은 결함(A2):** `compile_error`, `runtime_error`, `spawn_error`로 끝나 후보가 없는 run도 모두 `no-candidate`·0·사유 없음이다. 탐색이 실행되지 않은 실패를 탐색 완료·후보 없음과 섞으므로, 결정용 기록 §3의 "준비 실패·조기 종료·검토 중단 구별"에 어긋난다. `timeout`·`no_counterexample`의 `no-candidate`는 정당하다.
- **수정 방향:** 그룹의 모든 기록에 대해 다음을 확인해야 `no-candidate`·`not-confirmed-complete`를 낼 수 있다. 종료가 탐색 완료형(`no_counterexample`, 시도·할당 한도)일 것, 그리고 `bug_found`이면 후보 참조가 1개 이상일 것. 아니면 `unknown-incomplete`와 사유를 낸다. importer는 `bug_found`인데 참조가 없으면 inventory를 unknown으로 두고, v2의 complete 선언을 거부한다.

### N2 — 높음(수용 차단). 같은 run을 담은 기록 사이의 상충 판정이 숨겨진다

- **위치:** `aggregate.rs:712–743`(출현 키 = 기록 ID + 후보 해시), `818–821`(확인·기각 상충을 출현 하나 안에서만 검사), `430–447`(충돌 검사가 같은 run의 중복 기록을 보지 않음).
- **최소 조건(A3):** 같은 `O1`·run `R1`·후보 `Ha`로 기록 둘을 만든다.
  - 기록 `x`: 확인·귀속 C1(등록됨).
  - 기록 `y`: 같은 후보의 component rejected(투영·국소화 확인, 검토 complete).
  - 캠페인 선언은 `[x, y]` complete. 문서 §2가 권하는 "새 주석은 새 record ID로" 흐름 그대로다.
- **기대:** 같은 후보에 대한 확인과 기각이 공존하므로 양성 존재와 함께 미해결 사유를 남긴다. `review_results_complete`와 `cause_count_complete`는 false여야 한다.
- **실제:** `confirmed-attributed`, `review_results_complete: true`, `cause_count_complete: true`, `distinct_cause_count: known 1`, conflicts 없음. y의 검토가 unresolved인 변형은 올바르게 불완전으로 나온다(A3_variants).
- **수정 방향:** 그룹 안에서 상충 판단을 `(run_id, target_id, 후보 해시)` 기준으로 기록을 넘어 한다. 같은 run을 여러 기록이 담으면 issue로 남긴다. 우선순위 규칙이 고정되기 전에는 완결을 주장하지 않는다.

### N3 — 중간(수용 차단). 같은 원인 ID를 겹치는 scope로 두 번 등록하면 원인 수가 부푼다

- **위치:** `aggregate.rs:576–622`(`validate_registry`가 `(scope_id, cause_id)` 중복만 거부, 586행), `786`(원인 키 = scope + cause), `883`(완결 원인 수 = 등록 키 수).
- **최소 조건(A4):** 한 기록에서 후보 `Ha`(o1)와 `Hb`(o2)가 모두 C1로 귀속된다. 등록부는 `(S1, C1)`에 o1, `(S2, C1)`에 o2이고, 두 등록 모두 같은 단위 U1·버전을 범위로 둔다.
- **기대:** 같은 단위·버전에 같은 원인 ID가 두 scope로 등록된 것은 범위 중복이다. 거부하거나, 원인 수를 unknown으로 두고 ambiguous를 남겨야 한다.
- **실제:** `cause_count_complete: true`, `distinct_cause_count: known 2`. 기존 회귀 `the_same_candidate_cannot_gain_two_causes_from_different_registry_scopes`는 같은 후보만 다루므로 이 경우를 잡지 못한다.
- **수정 방향:** 같은 `cause_id`의 등록들 사이에서 실행 단위·소스 버전 범위가 겹치면 등록부 오류로 거부한다(또는 그 그룹의 원인 수를 unknown으로 둔다).

### N4 — 중간(수용 차단). `tool-specific-check`가 general 층 원인으로 세어진다

- **위치:** `aggregate.rs:269–286`(`basic_attribution`이 위반 유형이 known이기만 하면 통과, 280행).
- **최소 조건(A5):** general 층 확인·귀속 C1, `violation_kind: tool-specific-check`, 등록 C1.
- **기대:** general 층은 사전 정의한 일반 TCCT 기준(출력 차이·계산 abort)의 층이다(결정용 기록 §3). 도구별 검사 경고만으로는 일반 TCCT 위반이 아니다(초안 §5 표의 별도 검사 규칙). general 원인 수에 넣지 않거나 별도 층·미귀속으로 둔다.
- **실제:** `confirmed-attributed`, `distinct_cause_count: known 1`.
- **수정 방향:** general 층 귀속은 유형 `output-difference`·`computation-abort`로 제한한다. `tool-specific-check`는 확인·미귀속으로 두고 사유를 남긴다. 유형별 테스트를 추가한다.

### N5 — 중간(수용 차단). 층을 넘는 귀속 충돌이 ambiguity에서 빠진다

- **위치:** `mod.rs:182–196`(importer 충돌 집합이 general만), `aggregate.rs:688–711`(그룹 층에 해당하는 관측만).
- **최소 조건(A6/I3):** 같은 후보 `Ha`에 general 관측 matched C1과 contract 관측 matched C2가 있다.
- **기대:** 한 후보를 서로 다른 원인으로 귀속한 주장이 공존한다. 원인별 독립 근거가 없는 복수 귀속은 인정하지 않으므로 ambiguous로 처리해야 한다(판정 사례 F3-b).
- **실제:** importer 연결 `{C1:[o1]}`·issue 없음, 집계는 general `distinct_cause_count: known 1`.
- **수정 방향:** 충돌 집합을 컴포넌트 층(general·contract) 전체의 matched 주장으로 만든다. 층별로 원인을 달리 귀속하는 것을 허용하려면 그 규칙을 miiz가 정하고 문서에 남긴다.

### N6 — 낮음. runner-result 기록에서 같은 run의 과거 검토 행이 사유 없이 빠진다

- **위치:** `mod.rs:66–`(관측 target이 unknown이면 `continue`).
- **조건(I4):** runner-result 원본(target 없음), 같은 run `R1`의 값 없는 과거 보고서 행.
- **실제:** `reviews: 0`, `aggregation_issues: {}`, 사유 문구 없음. 보고서 원문만 보존된다.
- **수정:** "관측 target이 없어 이 run의 과거 행을 가져오지 않음"을 issue나 limitation으로 남긴다.

### N7 — 낮음. 국소화 방법의 "검증됨"이 근거 없이 known으로 출력된다

- **위치:** `aggregate.rs:138–145`(방법에는 근거를 요구하지만 검증 상태에는 요구하지 않음), `aggregate_schema.rs:75`.
- **조건(A7):** `localization_method_validated: known(true)`, 검증 기록 참조 없음.
- **실제:** 출력에 known true가 그대로 나온다. 전역 limitations 문구에만 "reported claim"이라고 적혀 있다.
- **수정:** true에는 검증 기록 참조를 요구하거나, 값을 "claimed"로 구분한다.

### N8 — 낮음(정책). 추적 문서에 AI 도구 이름이 있다

`docs/evidence_aggregate_v1.md:81`의 절 제목과 앵커, `reports/START_HERE.md:51`, `docs/plan_revision_2026-10-01.md:86`. AGENTS.md는 문서에 AI 귀속 표기를 금지한다. 코드 오류는 아니지만 commit 전에 중립 표현으로 바꿔야 한다. 앵커가 바뀌므로 링크도 함께 고친다.

## 4. 확인한 정상 동작

- **우선순위 2:** 집계기는 `component_cause_links`를 읽지 않는다. binding(저장값과 재계산값 모두), 층, 완료, 투영·국소화, 허용 방법, 유형·국소화 메타데이터, 중복 대상, 등록 범위를 관측에서 다시 검사한다(`aggregate.rs:239–329`).
- **우선순위 3:** 같은 단위·캠페인에서 정책이 다르면 `identity-policy-conflict`가 나고 두 기록은 따로 남으며 완결이 아니다(A10). campaign·repetition·정체성이 unknown이면 기록별로 격리된다(회귀). record ID 중복은 오류다.
- **우선순위 4:** complete + unresolved, 중단, 오류, 투영이 없는 기각은 음성이 아니다(회귀와 A3_variants). 기록 안의 확인·기각 상충은 미해결로 남는다.
- **우선순위 5:** 별칭, 없는 대상, 순환, 라벨 불일치는 원인을 만들지 않는다(I2, 회귀). 같은 후보의 scope 경쟁은 ambiguous다.
- **우선순위 6:** 정확 시각에서 앞선 미판정이 있으면 observed-minimum이고, 뒤에 있으면 exact-first다(A8). 완료 상한은 미판정이 있으면 observed-minimum, 없으면 completion-upper-bound다(A9). 기준이 다른 frame끼리는 최솟값을 내지 않는다. v1의 연결되지 않은 시간은 쓰지 않는다(회귀).
- **우선순위 7:** v1을 읽을 수 있다. v2에는 `aggregation_metadata`가 필수다. 원본 바이트를 보존하고 새 파일로만 쓰며(회귀), 중첩 참조는 `validate_ref`만 하고 열지 않는다.
- **우선순위 8:** 출력 limitations와 문서 §1은 "보고된 주장의 집계"임을 밝힌다. N7은 필드 수준에서 그 구분이 흐려지는 예외다.

## 5. 명시된 미구현 사항과 수용 차단 오류의 구분

**문서에 명시된 미구현(이번 수용 판단을 막지 않음).**
- 증거 내용 검사와 정상/abort 의미 검증, 유형별 근거 슬롯.
- 실제 수집 경로의 완전성·후보 시간·등록 근거 연결.
- A안 반복·잔여·종료와 실제 자원 계측.
- T1 복원.
- P2 `runner` 추출, 경로 이식성(절대 경로), 보고서-원본 관계 인증.
- 원래 증거 파일의 열람·재해시.

**수용을 막는 오류.** N1–N5. 고친 뒤 확인할 회귀는 다음과 같다. 현재 테스트에 없는 항목이다.
- N1: A1·A2(오류 상태 포함).
- N2: A3.
- N3: A4.
- N4: A5와 `computation-abort` 양성 대조.
- N5: A6.
- 기존에 빠진 것: `actual_wall_scope` 값 확인.

N6–N8은 수용 전 정리를 권한다. 특히 N8은 commit 전에 필요하다.

**표현 제한.** 수정·재검증 뒤에도 이 결과는 "오프라인 기록·집계의 구조 검증"이다. 다음은 남는다: N4-1 전체 관문, 같은 수준의 통째/분할 의미 검토, 투영·wrapper 대응, A안 실행 공정성. START_HERE와 계획표의 "합성 검증 완료" 문구는 이 보고서의 N1–N5가 해소될 때까지 "독립 검증에서 수정 필요"로 읽어야 한다.
