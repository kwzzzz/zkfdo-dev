# 공통 증거·검토 기록 v1 — N4-1 구현 범위

기준: [N3 채택 결정](scope_decision_accepted_2026-10-01.md). **오프라인 기록 경로 구현이며 N4-1 비교 가능성 관문 통과는 아니다.** 주 기여 가설·평가 프로토콜·과거 판정을 변경하지 않는다.

## 사용과 입출력

```text
zkfDO experiment record --request import-request.json --output new-record.json
```

기존 값 없는 JSON 메타데이터와 검토 보고서를 읽어 **새 파일 하나**를 쓴다. 출력 부모 디렉터리는 이미 존재해야 하며 기존 파일·심볼릭 링크를 덮어쓰지 않는다. 요청과 입력의 해시를 기록하고 입력 SHA-256 불일치는 거부한다. 후보·witness·회로·실행 파일·predicate·중첩 증거 참조는 열거나 실행하지 않는다. 검토 엔진을 다시 실행하는 명령도 아니다.

스키마는 [schema.rs](../src/evidence_record/schema.rs), 변환은 [legacy.rs](../src/evidence_record/legacy.rs), 연결·검증·출력은 [mod.rs](../src/evidence_record/mod.rs)에 있다. 실행 가능한 비보안 JSON 예시는 [테스트](../tests/evidence_record_test.rs)의 `request`, `observation`, `outcome` 헬퍼다. 회로나 실제 결함 재현 fixture는 추가하지 않았다.

| 요청 필드 | 의미 |
|---|---|
| `schema_version`, `record_id` | 현재 1, 새 기록 식별자 |
| `context` | 명시적 실행 단위·whole/split·반복·프로젝트·소스 버전·entrypoint·설정 해시·도구 버전. 방법이나 독립성을 기존 라벨에서 추정하지 않음 |
| `policy_intent` | A 설계, 단위 wall 할당·시도 제한·CPU/메모리 제한·seed 순서 참조. 아직 정하지 않은 값은 unknown |
| `source` | 아래 형식의 파일 경로·SHA-256 및 선택 키 |
| `review_reports` | 기존 schema-1 `backend-candidates` 검토 보고서의 경로·SHA-256 목록. 원본 scope·판정·inventory·중단·오류·미검토 목록을 보존 |
| `review_observations` | 기존 형식에 없는 층·국소화·TCCT·귀속·중복·중단의 명시적 메타데이터 관측. 원시 후보 값은 넣지 않음 |

결측 표기는 `{"state":"unknown","reason":"not measured"}`, 알려진 값은 `{"state":"known","value":3.0}`이다. 이유 없는 unknown, 음수/비유한 측정값, 알 수 없는 요청 필드, 잘못된 해시 형식은 거부한다. 알려진 원인/판정은 **입력 기록이 주장한 것**이며 importer가 의미를 검증했다는 뜻이 아니다.

| `source.format` | 선택 키와 읽는 범위 | 주의 |
|---|---|---|
| `runner-result` | `file`, 명시적 `target_id`; 저장된 RunResult 메타데이터 | 후보 파일 inventory가 없으므로 run 일치만으로 후보 연결을 확정하지 않음 |
| `experiment-outcome` | `file`, `run_id`; 정확히 하나의 scheduler run과 run/target에 연결된 후보 참조 | 호출의 계획 순번은 `source_plan_index`다. 실제 시도 순번으로 바꾸지 않음 |
| `p2-ledger` | `file`, `execution_index`; 해당 row와 lane/block | whole 또는 알려진 split lane과 요청 방식·반복의 충돌은 거부. `found`를 확인 성과로 바꾸지 않음 |

부분적인 legacy 메타데이터는 읽을 수 없는 필드별 이유를 남긴다. 지원하지 않는 schema 값이나 잘못된 자료형은 오류다. `execution_limit_seconds=0`은 과거 기본값일 수 있어 실제 0초 제한으로 해석하지 않는다. 요청이 선언한 단위/방법/버전과 입력에서 관측한 ID·버전은 분리한다. 단위 키의 정확성·독립성·버전 의미를 이 명령이 인증하지 않는다.

## 시간·자원·정책

`execution`은 campaign/run/target·계획 순번·seed·원본 버전 참조, 실제 wall·할당·종료 관측을 구분한다. 실제 시도/바퀴 순번, CPU·메모리·idle, 캠페인 종료, 시도 시작 잔여 할당을 읽을 수 없으면 unknown이다. wall을 CPU로 복사하거나 `할당-wall`로 A안의 잔여 예산을 추정하지 않는다.

`policy_intent`와 고정된 `policy_rules`는 A안의 공통 단위 할당, 조각별 예산 복제 금지, 후보/사후 판정에 독립적인 반복·잔여 처리, 재시작 비용·환경 장애·seed 규칙의 필요를 표현한다. **`policy_execution_verified`는 unknown**이다. 과거 실행이 A안을 구현했다는 의미가 아니며 반복 실행기·후보 생성 기능은 없다. 향후 실제 실행 계측에서 얻을 종료·잔여 값도 이번 importer가 만들어 내지 않는다.

후보 시간은 `candidate_times`에 수치·의미·기준점을 함께 둔다.

- RunResult: runner 완료시간 상한.
- ExperimentOutcome: scheduler 시작 기준 run 완료·결과 저장 뒤 offset 상한.
- P2 whole: `NOT SAFE` 로그 줄 수신 시각.
- P2 split: 지정 정답 위치들의 완료 offset 최솟값. 모든 후보에 대한 최초 시간이 아니다.

어느 값도 정확한 생성시각·사람의 확인시각으로 승격하지 않는다. `exact_candidate_time`은 unknown이다. 기준이 다른 값을 합산하거나 ‘최초 확인’ 지표를 계산하지 않는다. 선행 미검토 확인 및 같은 시간 기준의 집계는 후속 평가 절차의 의무로 남는다.

별도 `process_start_offset`은 읽을 수 있는 spawn 호출 offset과 runner/scheduler 기준점을 보존한다. OS exec나 엔진 시작 시각이 아니며 후보 시간에 더해 정확 생성시각을 만들지 않는다.

## 판정·귀속·중복

`component`, `entrypoint_tcct`, `projection`, `attribution`, `completion`을 각각 보존한다. `component_layer`는 general/contract/legacy-unspecified로 구분한다. 국소화는 localized/root/multi/failed/not-attempted이고 양쪽 방식에 같은 기록 조건을 적용한다. 이는 국소화를 수행하는 알고리즘이 아니다. 원인별 호출 위치·신호 대응·원본 제약 검증은 여전히 필요하다.

기존 `BackendReview`의 component 판정은 기존 기준의 **reported-confirmed**로만 옮긴다. 새 general TCCT 성과로 승격하지 않는다. `Project` scope도 entrypoint TCCT나 프로젝트 의미 확인으로 자동 전환하지 않는다. 원본 row는 `legacy_review`, 원본 report는 `preserved_review_reports`에 남는다.

기존 `KnownDefectSingleTarget`의 `known-defect-binding-matched`는 타깃 binding만 확인한다([엔진](../src/candidate_review/engine.rs), [검토 M1](../reports/n4-1-review-contract-2026-10-01/REVIEW.md)). 기존 Matched와 제안 원인 ID는 원본에 보존하되 새 귀속은 unknown이다. 원인 증거 방법이 없는 다른 legacy Matched도 승격하지 않는다. 명시 관측의 binding-only 방법 역시 unknown으로 정규화하며 원래 요청은 경로·해시로 추적한다.

`metadata_binding`은 run·target·후보 해시가 입력 메타데이터에 연결됐다는 뜻이다. 후보 내용을 재검증하거나 원인을 귀속한 결과가 아니다. 불일치·결측 관측도 남기고 원인 연결에서 제외한다.

`component_cause_links`는 **이 기록 내부의 조건을 갖춘 신고된 원인별 관측 ID 목록**이다. 전체 평가 고유 원인 수가 아니다. general·완료·컴포넌트 확인·증거 기반 귀속·국소화·metadata binding과 원인 중복 구분을 모두 요구한다. 계약/legacy 층, TCCT만 확인, 투영·귀속 실패, 중단은 섞지 않는다.

- 같은 원인의 여러 관측은 한 키 아래 모두 남긴다. `duplicate_of`는 관측 연결, `cause_deduplication`은 원인의 canonical/duplicate-of/unresolved 구분이다.
- 같은 후보가 여러 원인에 연결되면 `aggregation_issues`에 ambiguous를 남기고 모두 원인 연결에서 제외한다. 원인별 별도 입증이 필요한 다중 원인 예외는 이번에 자동 판정하지 않는다.
- 미판정·중단·오류를 음성이나 원인 하나로 바꾸지 않는다. 단위 성공/실패 이진 집계나 전체 cause count를 출력하지 않는다. 기록 간 중복 제거·원인 등록부·단위별 다중 상태 집계는 별도의 고정 규칙이 필요하다.

## 병렬 검토 반영과 남은 관문

[N4-1 계약 검토](../reports/n4-1-review-contract-2026-10-01/REVIEW.md)는 읽고 보존했다. 추가 검토 보고서로 대체하지 않았다.

| 의견 | 이번 반영·범위 |
|---|---|
| M1 binding/귀속 분리 | legacy와 명시 binding-only를 새 귀속 성과에서 제외. 원본 판정 보존 회귀 포함 |
| M2 대칭 국소화 | 두 방식 모두 같은 metadata 조건. 실제 국소화·신호 대응 알고리즘/실행은 미구현 |
| M3 다중 원인·중복 | 원인별 관측 연결과 ambiguous 보존. 원인별 별도 입증 예외는 자동 계산하지 않음 |
| M4 시간 기준 | 의미·기준점 분리, 정확 생성시각/최초 확인 집계 보류. 후보 원문의 T1은 읽지 않음 |
| M5 검토/결과 분리 | 층별 assessment와 별도 completion, 전체 inventory·중단 보존. 보고서의 5상태 **단위 집계기**는 이번 구현에 포함하지 않음 |
| M6 자원·종료 | A 설계 의도와 과거 관측 분리. 읽지 못한 실제 자원·시도/캠페인 종료·잔여는 unknown. F17의 실제 반복 실행·잔여 계측은 사용자 승인 범위 밖 |
| M7 과거 의미 | 원본 불변·hash pin, legacy 층·Project와 P2 시간 의미 보존 |
| M8 구조/의미 관문 | 아래처럼 별도 보고. 구조 테스트 통과를 통째 후보 의미 검증 성공으로 쓰지 않음 |

검토 §10a의 모든 필드·F1–F20·단위 집계까지 완성했다고 선언하지 않는다. 이번에 구현한 **메타데이터 가져오기·연결 경로**의 구조 검증과 §10a 전체는 범위가 다르다. F17의 실행 정책 검증, 일반 TCCT 판정, 첫 분기 국소화, wrapper 의미 대응, 실제 통째·분할 후보 검토는 이 작업으로 수행하지 않는다. 원시 후보 필드(T1·결과 플래그·출력)의 추가 추출도 포함하지 않았다.

**N4-1 전체 관문은 미통과다.** 남은 조건은 같은 수준의 통째/분할 후보 의미 검토와 원인 귀속, 투영·wrapper 대응 근거, 하네스 시간 기준 검증, A 정책의 양쪽 구현·실제 자원/잔여 계측이다. 새 실행은 별도 범위 결정이 필요하다. N4-2로 자동 확장하지 않으며 N5 미고정·평가 후보 퍼징 금지를 유지한다. 필수 검사와 최신 진행 상태는 [계획](plan_revision_2026-10-01.md#7-진행-표)에 남긴다.
