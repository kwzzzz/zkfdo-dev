# N4-1 오프라인 메타데이터 집계 v1

**버전 `N4-1-aggregate-v1`, 2026-10-01, 담당 miiz.** 이번 후속 지시는 `experiment record`가 만든 기록의 오프라인 집계와 합성 검증을 허용한다. [N3 채택 기록](scope_decision_accepted_2026-10-01.md)과 [기록 v1 설명](evidence_record_v1.md)은 당시 버전 그대로 보존한다. 이 문서는 구현·검사 결과와 변경된 읽기 규칙을 기록하며, 평가 프로토콜이나 의미 판정을 고정하지 않는다. **N3 완료, N4 진행 중, N4-1 전체 관문 미통과, N4-2 미착수, N5 미고정**이다.

## 1. 구현과 사용

```text
zkfDO experiment record --request import-request.json --output new-record.json
zkfDO experiment aggregate --request aggregate-request.json --output new-aggregate.json
```

집계기는 요청과 요청에 나열된 **해시 고정 evidence record JSON만** 읽는다. 중첩된 source/report/evidence/candidate/circuit/witness/predicate 참조는 열거나 실행하지 않는다. 새 출력은 `create_new`로 작성하며 기존 파일·심볼릭 링크를 덮어쓰지 않는다. 입력 해시 불일치, 지원하지 않는 버전, 잘못된 형식은 출력 전에 실패한다. 반복 실행기·새 후보 생성·퍼징 기능은 추가하지 않았다.

| 코드 | 역할 |
|---|---|
| [aggregate.rs](../src/evidence_record/aggregate.rs) | 입력 검증, 그룹/완전성/원인 등록부 재검사, 새 파일 출력 |
| [aggregate_schema.rs](../src/evidence_record/aggregate_schema.rs) | 집계 요청·출력 v1과 record v2 확장 |
| [aggregate_time.rs](../src/evidence_record/aggregate_time.rs) | 명시적으로 후보와 연결된 시각만 기준별 집계 |
| [mod.rs](../src/evidence_record/mod.rs), [legacy.rs](../src/evidence_record/legacy.rs) | importer 호환성, 코드 검토 F1–F5·F7·F9·F11과 독립 검증 N1·N4–N6 보정 |
| [집계 테스트](../tests/evidence_aggregate_test.rs), [기록 테스트](../tests/evidence_record_test.rs) | 값 없는 메타데이터 반례와 CLI 검증 |

집계 출력은 **입력 기록이 보고한 결과의 집계**다. `confirmed`·`attributed`·`registered_causes`는 도구가 원인 의미나 증거 내용을 새로 인증했다는 뜻이 아니다. 확인 조건에 필요한 형식·연결·참조가 있는지 검사하며, 증거 파일의 존재·내용·유형별 의미·귀속 타당성은 이 범위에서 검증하지 않는다.

## 2. 버전과 입력 선언

기존 `ImportRequest`/`EvidenceRecord` v1을 계속 읽고 v1 요청은 v1으로 쓴다. v1에는 `aggregation_metadata`가 없으며, 기존 자유 문자열 inventory와 후보에 연결되지 않은 시간을 완전성·정확 시각의 근거로 쓰지 않는다. v2 요청/기록은 `aggregation_metadata`가 필수다. v1에 확장을 붙이거나 v2에서 생략하면 거부한다. 알려지지 않은 필드·버전을 조용히 무시하지 않는다. 기존 v1 파일을 수정해 v2로 만드는 작업은 하지 않았다. 새로운 주석/증거를 추가하려면 새 요청·새 record ID·새 출력 파일로 남긴다.

| v2 확장 | 의미와 한계 |
|---|---|
| `candidate_inventory` | `complete`, `reason`, `evidence`로 해당 기록의 후보 목록 완전성 선언. complete에는 근거 참조 필요. 선언 자체를 의미 인증하지 않음 |
| `review_inventory[]` | 검토 층과 예상 `observation_id` 전체 목록, 완전성 근거. 예상/실제 목록이 다르면 불완전. 목록 완전과 판정 완료는 다름 |
| `candidate_times[]` | 후보 hash·run·target·campaign·clock·origin·basis·seconds·근거의 명시적 연결. `basis_verified`도 입력이 보고한 상태 |
| `review_semantics[]` | 관측별 violation kind, 유형별 증거, 국소화 방법·검증 상태·근거. 생략한 항목은 집계 출력에서 unknown과 이유로 표시 |

`violation_kind`는 output-difference / computation-abort / tool-specific-check 또는 unknown이다. 출력 차이형의 근거는 같은 입력의 정상 계산·출력 비교, abort형은 정상 계산이 중단된 위치/조건과 해당 증거, 도구별 검사는 고정된 검사 기준을 가리켜야 한다. 집계기가 이를 실행하거나 내용으로 판별하지 않는다. 유형·국소화 방법·참조가 빠지면 컴포넌트의 신고된 양성은 보존해도 귀속 성과로 집계하지 않는다. general 층 귀속은 output-difference·computation-abort만 인정한다. tool-specific-check는 general 층에서 확인 보고로 남지만 원인으로 세지 않으며, importer도 general 원인 링크를 만들지 않고 관측 ID로 issue를 남긴다. `localization_method_validated=unknown`을 성공으로 바꾸지 않는다. 검증 기록을 가리킬 필드가 없으므로 `known(true)`는 import와 집계에서 거부하고, false·unknown은 출력에 그대로 남긴다.

집계 요청 v1은 다음 구조다. 실행 가능한 비보안 예시는 테스트 헬퍼에 있다.

```json
{
  "schema_version": 1,
  "records": [{"path": "record.json", "sha256": "64자리 실제 메타데이터 해시"}],
  "campaigns": [],
  "cause_registry": []
}
```

`campaigns`에는 실행 단위·방식·known campaign·known repetition, 예정된 record ID **전체**, complete/reason/evidence를 둔다. 없는 예정 기록을 성공한 기록으로 대체하지 않는다. `cause_registry`에는 `(scope_id, cause_id)`, 허용 실행 단위·소스 버전, record/observation으로 한정된 members와 등록 근거를 둔다. 빈 근거, 범위 밖 구성원, 없는 기록/관측, 중복 키는 오류다. 여러 등록 키가 한 후보에 경쟁하면 ambiguous다. scope ID는 별도의 원인 이름공간으로 읽는다(§4의 원인 수 규칙). 새로운 별칭 판단이나 다중 원인 독립 입증은 수행하지 않는다.

## 3. 그룹, 상태, 완전성

실행 단위·whole/split·캠페인·반복·검토 층별로 분리한다. 같은 ID라도 설정·소스/도구 버전·정책·실행 설정이 다르면 별도 그룹과 `conflicts`를 남긴다. unknown campaign/repetition은 기록별로 격리하며, 핵심 단위 정체성이 결측인 경우도 합쳐 완전한 캠페인이라고 부르지 않는다. metadata SHA, outcome ID, plan ID와 파일 schema version은 관측 컨테이너 식별자여서 실행 설정 키에서 제외하지만 원본 출처에는 보존한다. plan hash와 backend/설정 해시는 충돌 검사에 남긴다.

같은 `record_id`를 여러 입력으로 주면 오류다. 같은 파일의 재입력이나 충돌하는 버전 중 하나를 선택하지 않는다. 후보 출현은 여기서 **record ID + 후보 hash**로 정의한다. 같은 기록 내부의 동일 hash 참조는 한 출현에 연결하고, 원래 참조 목록과 모든 review ID는 보존한다. 실제 생성 이벤트의 개수를 복원하는 기능은 아니다. 같은 그룹에서 한 기록이 확인하고 다른 기록이 기각한 후보 hash는 어느 기록도 고르지 않는다. 그 hash의 출현을 모두 미해결로 두고 확인·기각 기록 ID를 사유에 남긴다. 같은 run을 새 record ID로 다시 주석한 경우도 같다.

| `state` | 의미 |
|---|---|
| `confirmed-attributed` | 해당 층에서 연결·검토·투영·귀속 조건을 충족한다고 보고된 출현이 하나 이상 있음 |
| `confirmed-unattributed-only` | 확인 보고는 있지만 컴포넌트 원인 귀속 조건은 충족하지 못함. entrypoint TCCT는 별도 층에 이 상태로 보존 |
| `not-confirmed-complete` | 선언된 후보·캠페인·검토 목록이 완전하고 모든 해당 출현이 최종 미확인 판정 |
| `no-candidate` | 근거 있는 완전한 목록과 캠페인에서 후보가 없고, 모든 기록이 탐색을 마쳤으며(아래 실행 상태), 검토 목록/고아 관측 충돌이 없음 |
| `unknown-incomplete` | 위 조건이 충족되지 않음. 미판정·중단·오류·결측·목록 누락 포함 |

**실행 상태.** 후보 목록 완전성은 선언만으로 성립하지 않는다. 그룹의 모든 기록이 탐색을 마친 실행이어야 한다: `no_counterexample`, `timeout`, 또는 후보 참조가 1개 이상인 `bug_found`. 컴파일·실행·파싱·spawn 오류, `finished`, 그 밖의 상태나 unknown 상태, 참조 없는 `bug_found`, 후보 목록을 확정하지 못한 outcome 기록이 있으면 `candidate_inventory_complete=false`와 `기록 ID: 사유`를 낸다. 실패 시도의 재시도·제외 규칙은 N5에서 정하므로, 그 전에는 실패 시도가 있는 캠페인도 불완전이다. importer는 참조 없는 `bug_found` outcome의 inventory를 unknown으로 두고, 그런 기록의 v2 complete 선언을 거부한다.

존재 여부 양성과 `unresolved_occurrences`, `review_results_complete=false`, `cause_count_complete=false`는 공존할 수 있다. `complete + unresolved`는 음성이 아니다. 확인과 기각의 상충은 한 기록 안이든 기록 사이든 양성 보고의 존재와 불완전 사유를 함께 남기며 유리한 판정을 골라 완결시키지 않는다. 보존 보고서의 중단·오류·미검토 이력은 새 완전성 선언으로 지우지 않는다. 실제 비용은 `record_contexts`에 관측 범위와 함께 남기며, 이 집계는 시도 wall과 캠페인 wall을 합산하지 않는다.

## 4. 원인과 시간 집계

`component_cause_links`는 합산하지 않는다. run/target/hash binding, 검토 층, 완료/확인 상태, 투영·국소화, 귀속 방법 허용목록, 유형별/국소화 메타데이터, 중복 대상과 등록 범위를 관측에서 다시 검사한다. binding-only·과거 Matched·P2 found는 확인 원인으로 승격하지 않는다. split의 `Root`는 entrypoint main 주장으로 보존하되 컴포넌트 확인에 넣지 않으며 명시적인 인스턴스 국소화가 필요하다.

원인 집계에는 범위가 있는 등록 키와 근거가 필요하다. 최상위 등록 목록은 층별 출처 연결 목록이며 평가 전체의 원인 총수가 아니다. 기록별 유효 귀속이 있어도 등록부가 없으면 존재 여부는 양성이지만 원인 총수는 unknown이다. 미판정/귀속 실패/누락 등록이 있으면 등록된 부분 목록을 보여 주되 총수로 바꾸지 않는다. 같은 후보에 다른 원인 또는 서로 다른 scope 키가 경쟁하면 층(general·contract·legacy)과 기록을 가리지 않고 ambiguous로 남긴다. 층별로 다른 원인 귀속을 허용하는 규칙은 정하지 않았다. 한 그룹에서 센 원인이 둘 이상의 scope에서 오면, 같은 단위·버전에 scope가 겹쳐 scope 사이의 구별이 성립하지 않으므로 원인 수를 unknown으로 두고 ambiguous 사유를 남긴다. 한 scope 안의 서로 다른 cause ID는 등록부 선언대로 센다. canonical에 연결되지 않는 duplicate, 임의 별칭, cycle, 서로 다른 원인의 observation duplicate도 원인 성과에 넣지 않는다. general/contract/legacy/entrypoint TCCT 층은 분리되며 등록 목록에도 층을 표기한다. 후보·출현·spec 개수는 고유 원인 수가 아니다.

| 시간 결과 | 조건과 해석 |
|---|---|
| `exact-first` | 정확 생성시각으로 보고된 후보 연결, 동일 campaign/clock/origin/basis, 완전한 대상·검토 목록과 선행 미판정 부재. 사람의 검토 완료시각이 아님 |
| `completion-upper-bound` | 호환되는 완료 offset 근거만 있을 때 첫 확인 대상 생성시각의 상한. 정확 생성시각으로 전환하지 않음 |
| `observed-minimum` | 로그 관측 최솟값 또는 목록/선행 판정 미완결로 최초를 확정할 수 없는 연결값. `series.blockers`에 이유 유지 |
| `unavailable` | 유효한 후보별 시간 연결 없음 또는 호환되지 않는 여러 기준. 다른 기준의 series는 보존하고 하나를 선택하지 않음 |

기존 v1 `candidate_times`가 하나뿐이어도 후보에 임의로 붙이지 않는다. 잘못된 run/target/hash/campaign 연결, 미검증 basis는 사용하지 않는다. 정확 시각에서 엄격하게 더 늦다고 연결된 미판정은 앞선 결과를 뒤집지 않지만, 연결이 없거나 같거나 앞선 미판정은 최초 확정을 막는다. 완료 상한은 미판정 후보가 더 늦게 생성됐음을 증명하지 못한다. 로그 관측은 항상 observed-minimum이다. 시각의 수학적 최소와 최초 확인 성과는 다른 주장이다.

## 5. 코드 검토 반영

[검토 보고서](../reports/n4-1-record-code-review-2026-10-01/REVIEW.md)는 수정하지 않았다. 검토는 이전 v1 snapshot을 대상으로 하므로 현재 수정 위치와 회귀 테스트에서 각 의견을 다시 확인했다. 보고서 SHA-256은 `1c5fa0b16d3b417bfe53dea69fba8929fd289829410ecf8caee2793eb5823348`이다. [계약 검토](../reports/n4-1-review-contract-2026-10-01/REVIEW.md)도 보존했다.

| 의견 | 현재 반영 여부와 범위 |
|---|---|
| F1 | 반영. 귀속 방법은 manual-cause-review / fixed-constraint-rejection 허용목록. importer는 미등록 방법을 unknown으로 정규화하고 집계도 재검사. 이름만으로 의미 인증하지 않음 |
| F2 | 반영. 같은 기록의 eligible canonical·같은 cause ID만 duplicate 대상 허용. orphan/cycle/별칭/다른 원인 연결 배제. 기록 간 연결은 별도 등록부 필요 |
| F3 | 반영. 중복 상태와 무관한 matched 주장과 등록 scope 충돌을 ambiguity에 포함 |
| F4 | 반영. runner 요청 target은 `source.target_id`에 남고 원본에 없는 관측 target은 unknown. 요청을 관측으로 복사하지 않음 |
| F5 | 반영. P2 whole/path-order/small-first/random만 허용하고 요청 방식과 대조. 집계도 이전 기록의 알려진 lane 불일치 재검사 |
| F6 | 집계 형식에 반영. `record_contexts.actual_wall_scope`로 runner/outcome 시도, P2 split 캠페인, P2 whole 관측을 구분. v1 원필드를 소급 변경하거나 범위가 다른 wall을 합산하지 않음 |
| F7 | 반영. 모든 과거 scope의 disposition·scope·실패 criterion·violation class를 legacy reason과 원본에 보존. general/entrypoint로 승격하지 않음 |
| F8 | v2와 집계에 반영. 위반 유형·유형별 증거 참조, 결측 unknown 및 귀속 집계 제한. 증거 내용 검사와 정상/abort 의미 검증은 남음 |
| F9 | 반영. whole/split 모두 확인된 투영 요구, split+entrypoint Root는 원인 연결/컴포넌트 확인에서 제외하며 원본 유지 |
| F10 | v2와 집계에 반영. 국소화 방법·검증 상태·근거, 없는 값 unknown. 첫 분기 투영의 타당성이 입증됐다는 문장은 쓰지 않음 |
| F11 | 반영. 동일 run/다른 target 충돌, report hash 대소문자 중복 거부. 집계의 record ID 중복·설정 충돌도 별도 처리 |
| F12 | 반영. 검토 행 없는 후보를 층별 unresolved occurrence로 출력 |
| F13 및 원문 증거 해시 재검사 제안 | 일부 반영/보류. 요청·입력 경로와 해시·원본 source 관계를 출력에 유지하고 새 시간 basis는 열거형. 과거 source_method/종료 문자열은 원문으로 보존하며 일반적인 문자열 의미 추론은 하지 않음. raw 증거 파일 열기·재해시는 이번 사용자 범위와 충돌하므로 하지 않음. P2 direct runner 추가 추출과 경로 이식성, source-report의 독립적인 관계 인증은 남음 |

## 6. 독립 검증 오류 수정

[독립 검증 보고서](../reports/n4-1-aggregate-verification-2026-10-01/REVIEW.md)가 재현한 오프라인 집계 오류 N1–N7을 2026-10-01에 수정했다. 보고서와 그 판정은 수정하지 않았다(SHA-256 `9b74e46dd1e3b364bbcaa4ce9763656a6a1f2fadad346452ed27349ceb0b4a0d`). 아래 "수정 전"은 보고서가 검토한 snapshot과 같은 소스의 결과다.

| 항목 | 수정 위치 | 바뀐 규칙 | 합성 재현: 수정 전 → 수정 후 |
|---|---|---|---|
| N1 실행 실패·참조 누락 | `aggregate.rs`의 `inventory_blocker`·`missing_candidate_refs`와 `group()` 후보 목록 완전성, `legacy.rs` outcome 분기, `mod.rs` import 끝 | §3 실행 상태 | 참조 없는 `bug_found`(A1): `no-candidate`·원인 수 known 0 → import 거부, 같은 상태를 담은 v2 기록은 `unknown-incomplete`. `compile_error`·`runtime_error`·`spawn_error`(A2): `no-candidate`·0 → `unknown-incomplete`·unknown. `no_counterexample`·`timeout`은 `no-candidate` 유지 |
| N2 기록 간 상충 | `aggregate.rs` `group()`의 기록 간 판정 비교 | §3. 같은 그룹·같은 후보 hash의 확인과 기각이 다른 기록에 있으면 해당 출현 모두 미해결, 확인 존재는 유지 | A3: 검토·원인 수 완결, known 1 → 둘 다 불완전, unknown. 상태 `confirmed-attributed` 유지. 판정이 같은 두 기록은 완결·known 1 유지 |
| N3 겹치는 scope | `aggregate.rs` `group()` 원인 집계 | §4. 센 원인이 둘 이상의 scope에서 오면 원인 수 unknown과 ambiguous 사유 | A4: known 2 → unknown. 같은 cause ID와 서로 다른 cause ID 모두. 한 scope 안의 서로 다른 cause ID 둘은 known 2 |
| N4 도구별 검사 | `aggregate.rs` `basic_attribution`·`kind_attributable`, `mod.rs` 링크 적격성 | §2. general 층 귀속은 출력 차이·계산 abort만 | A5: `confirmed-attributed`·known 1 → `confirmed-unattributed-only`·unknown, 출현 사유 기록. computation-abort·output-difference는 귀속 유지 |
| N5 층간 귀속 충돌 | `aggregate.rs` `group()` 주장 집합, `mod.rs` `candidate_causes` | §4. 한 후보의 matched 주장은 층과 무관하게 ambiguity에 포함 | A6: importer 링크 `{C1:[o1]}`·집계 known 1 → 링크 없음과 후보 hash issue, 집계 미귀속·unknown. 두 층이 같은 원인이면 귀속 유지 |
| N6 가져오지 못한 과거 행 | `mod.rs` 보고서 행 처리 | 같은 run이지만 관측 target이 없어 가져오지 못한 행이 있으면 `legacy-review-rows-not-imported:<보고서 SHA>` issue | I4: issue 없음 → issue. 행은 계속 가져오지 않고 보고서 원문만 보존 |
| N7 국소화 검증 주장 | `aggregate.rs` `validate_aggregation_metadata` | §2. `known(true)` 거부 | A7: 출력에 known true → import·집계 거부 |

**회귀 테스트.** 집계 7개와 기록 5개를 추가했다.

| 항목 | 테스트 |
|---|---|
| N1 | `failed_unknown_or_reference_less_runs_are_not_completed_absence`, `a_failed_attempt_keeps_its_campaign_incomplete`, `bug_found_without_a_candidate_reference_is_a_missing_inventory` |
| N2 | `records_that_confirm_and_reject_one_candidate_stay_unresolved` |
| N3 | `overlapping_registry_scopes_do_not_count_causes_as_distinct` |
| N4 | `tool_specific_checks_are_not_counted_as_general_tcct_causes`, `tool_specific_check_is_kept_but_not_linked_as_a_general_cause` |
| N5 | `cause_claims_on_one_candidate_conflict_across_component_layers`, `cause_claims_conflicting_across_component_layers_are_ambiguous` |
| N6 | `runner_result_reports_review_rows_it_cannot_bind_to_an_observed_target` |
| N7 | `a_validated_localization_claim_without_a_validation_record_is_rejected`, `validated_localization_claim_needs_a_validation_record` |

기존 `no_candidate_requires_record_and_campaign_inventory_evidence`는 참조 없는 `bug_found` 기록을 `no-candidate`로 기대했다. 이는 N1의 오류 동작이므로 기록 상태를 `no_counterexample`로 바꿨다. 다른 기존 테스트의 기대는 바꾸지 않았다.

**검사.**

- 새 회귀 12개는 수정 전 소스(snapshot의 `aggregate.rs`·`mod.rs`·`legacy.rs`)에서 모두 실패하고 수정 후 통과한다. 기존 기록·집계 테스트 61개는 양쪽에서 통과한다.
- 검증 harness를 수정 후 binary로 다시 실행했다. 결과가 바뀐 사례는 A1–A7, I3의 층간 변형, I4, I5, A2 상태 변형이다. A8–A10, 양성 대조 B0, I1, I2, A3 변형은 그대로다. 결과와 로그는 ignored `runs/n4-1-aggregate-fix-2026-10-01/`에 있다.
- `cargo fmt`와 `cargo clippy --all-targets --all-features -- -D warnings` 통과. `cargo test`: **297 통과, 0 실패, 22 ignored**. ignored 검사는 실행하지 않았다.
- 실제 회로·후보·witness·predicate는 열거나 실행하지 않았다.

**보수적으로 처리한 미정 규칙.** 다음은 miiz가 정할 규칙이며, 정하기 전까지 완결을 주장하지 않는 쪽으로 구현했다.

- 같은 후보를 다시 주석할 때의 우선순위(새 기록이 이전 기록을 대체하는지). 그 전에는 상충을 미해결로 둔다.
- 층별로 다른 원인 귀속을 허용할지. 그 전에는 ambiguous다.
- 실패 시도의 재시도·제외(N5 고정 사항). 그 전에는 실패 시도가 있는 캠페인을 불완전으로 둔다.
- 겹치는 scope는 등록부 단계에서 거부하지 않고, 해당 그룹의 원인 수만 unknown으로 둔다.

이 수정은 오프라인 기록·집계의 구조 수정이다. **N4-1 의미 관문 통과가 아니며**, §7의 구조·의미 관문은 그대로 남는다.

## 7. 검증과 남은 관문

아래는 최초 구현 때의 검사 결과다. N1–N7 수정 후 결과는 §6에 있다. 값 없는 합성 참조는 실제 후보·회로·witness·predicate 파일이 없는 경로를 사용하므로 중첩 참조 열기를 검출한다. 실제 결함 재현 fixture는 추가하지 않았다. 검사 로그는 로컬 `/private/tmp/n4-aggregate-*.log`에 남겼다.

- `cargo fmt`: 완료.
- `cargo clippy --all-targets --all-features -- -D warnings`: 통과.
- `cargo test`: **285 통과, 0 실패, 22 ignored**. 기존 실제 산출물/설치 도구가 필요한 ignored 검사는 실행하지 않았다.
- 관련 테스트는 기록 통합 32개, 집계 통합 29개, 기존 legacy 단위 4개다. 이번에는 importer 회귀 16개와 집계 29개를 추가했다. ID/정책 충돌, unknown 반복, 불완전 빈 목록, 미검토/complete+unresolved, 양성과 미판정 공존, 중복·scope 충돌·binding-only·귀속 실패, 서로 다른 시계/basis, 선행 미판정, 입력 해시·새 파일·CLI를 확인했다.
- 초기 검사에서 관측 컨테이너의 metadata SHA가 실행 설정으로 들어가 별도 run을 잘못 분리한 문제를 수정했다. v2 선택 필드 생략의 직렬화 호환성도 수정하고 전체 검사를 다시 통과했다. 투영 기각/미시도 또는 국소화 결측이 최종 기각 상태와 공존할 때도 완결 음성이 되지 않도록 별도 회귀를 추가했다. 이 검증은 원인 의미나 A 실행 공정성의 검증이 아니다.
- 현재 안내 문서 7개의 로컬 링크·앵커 102개, 보존 대상 6개 파일의 SHA-256, `git diff --check`와 새 파일의 공백을 확인했다. N3 채택 문서·결정용 원문, 기록 v1 가이드, 두 N4-1 검토 보고서는 수정하지 않았다. commit/push/PR은 수행하지 않았다.

**이번 구조 범위:** 버전 호환, 그룹 충돌, unknown 반복 격리, 후보·검토·캠페인 완전성, 다중 상태, 등록 원인과 중복, 시간 기준/선행 미판정, 원본 보존·새 출력·CLI를 합성 메타데이터로 검증한다. 계약 §10a 전체 완료를 뜻하지 않는다. 실제 수집 경로에서 완전성/후보 시간/원인 등록 근거를 빠짐없이 기록하는 연결 검증, A안 반복·잔여/종료 정책과 실제 자원 계측, 원시 후보 T1 복원은 남는다. 이번에는 실행기를 구현하거나 새 실행을 시작하지 않았다.

**의미 관문:** 통째·분할에 같은 수준의 정상 계산/abort/전제·고정 제약 검토, 투영·국소화·원인 귀속과 다중 원인 독립 입증, wrapper 의미 보존, 시간 계측 기준 및 검토/비용의 공정성 검증은 남는다. metadata에 근거 경로가 있다는 사실과 구조 테스트 통과로 이 관문을 통과시키지 않는다. **N4-1 전체 완료 및 A안 실행 검증 완료를 선언하지 않는다.** N4-2나 평가 후보 퍼징으로 자동 확장하지 않는다.
