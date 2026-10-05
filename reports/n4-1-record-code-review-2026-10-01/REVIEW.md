# N4-1 evidence_record v1 코드 검토 (2026-10-01)

**상태: 검토 완료(정적 읽기).** 공통 증거·검토 기록 경로 v1이 [N4-1 계약 검토](../n4-1-review-contract-2026-10-01/REVIEW.md)와 [N3 채택 결정](../../docs/scope_decision_accepted_2026-10-01.md)을 지키는지 확인했다. 실험, 회로, 원시 후보, witness는 열거나 실행하지 않았다. 테스트·CLI도 실행하지 않았다. 아래 동작은 코드 경로를 추적해 확인한 것이다. 소스, 테스트, 기존 문서, 계획 상태표는 수정하지 않았다.

## 검토 대상 고정

2026-10-01T09:32:08Z에 아래 파일을 ignored `runs/n4-1-record-code-review-2026-10-01/snapshot/`에 복사해 고정했다(`SHA256SUMS` 포함). 기준 commit은 `77fe85c`다. 09:39:48Z에 다시 비교했을 때 작업 트리도 같았다. **이 해시 밖의 후속 구현(집계 기능 등)은 검토하지 않았다.** 아래의 행 번호는 이 사본 기준이다.

| 파일 | SHA-256 |
|---|---|
| `src/evidence_record/schema.rs` | `ad8be32fff0a7f527daab1628ae5d9197df941386bf8e66ec98b38272b688649` |
| `src/evidence_record/legacy.rs` | `d997679ea795afb8307b4a46930f35bdf88f44ae0e2bab05f64c61ecc6e8018f` |
| `src/evidence_record/mod.rs` | `3f0bc790b441f420a72b91d03b50987eafabb75df41fc0528b00531b8e76d969` |
| `tests/evidence_record_test.rs` | `1226c8f781d4d660a0ebbb0ac7ecfb839f48996d89933658f6516c7853bd592e` |
| `src/cli.rs` | `00623862d5f68c3bb086c3b4a801197b831b8610156fd242feb096640f1d1405` |
| `src/lib.rs` | `2bdb9d08ca87b1771c175a5a4787163beaca0004463813d8bf3202ab8c384174` |
| `docs/evidence_record_v1.md` | `a880cc3165c0dac722f2eca5fcb8fefdfad0622461037208c477c83b82905441` |
| `docs/scope_decision_accepted_2026-10-01.md` | `f97db998b4449b1055f922cd7cc78056e236a5f14d2bfd75351c3f816cf76018` |

`src/cli.rs`·`src/lib.rs`는 HEAD 대비 `experiment record` 명령과 `pub mod evidence_record` 추가만 바뀌었다(diff 해시 `43a31a1a…`). 둘 다 문서와 일치한다.

## 0. 종합 판단

**중대한 문제가 있다.** 원인 연결 출력(`component_cause_links`)에서 위치·binding뿐인 주장이 원인으로 들어갈 수 있고(F1), 중복 표시 하나로 원인 키가 새로 생기거나 바뀔 수 있다(F2). 후속 집계가 이 출력을 쓰기 전에 고쳐야 한다. 그 밖에 중간 6건(F3–F8)과 낮음 5건(F9–F13, F13은 작은 항목 묶음)이 있다.

다음은 잘 지켜졌다. 입력 해시 고정과 불일치 거부, 새 파일 쓰기(`create_new`), 과거 `Matched` 비승격, 계약·과거 층 제외, `multi`·`failed` 국소화 제외, canonical 원인 2개의 ambiguous 처리, 미검토·중단의 비음성화, P2 `found`의 비승격, 정확 생성시각 unknown, 0초 제한 비해석, 음수 거부, 정책 의도와 관측의 분리, 전역 원인 수 미출력이다.

N4-1 관문 판단은 바뀌지 않는다. 기록 경로의 구조 관문도 F1–F5를 고치기 전에는 깨끗하지 않고, 의미 관문은 문서대로 미통과다.

| 확인 항목 | 결과 |
|---|---|
| 1. 해시·run·target·후보 연결 | 부분 충족. 후보 연결은 원본 메타데이터를 요구한다. runner-result의 target은 요청의 주장만으로 known이 된다(F4) |
| 2. binding-only·과거 Matched·P2 found | 과거 Matched와 P2 found는 승격되지 않는다. 명시 관측의 binding 판정은 이름 거부목록이라 우회된다(F1) |
| 3. Project scope·계약 조건부 | 상향 전환은 없다. 과거 Project 등은 컴포넌트 판정이 "시도 안 함"으로 내려가 의미가 손실된다(F7) |
| 4. 중단·오류·미판정·귀속 실패 | 음성으로 바뀌지 않는다. 검토 행이 없는 후보는 상태가 명시되지 않는다(F12) |
| 5. 중복·spec 중첩·다중 원인·ID 충돌 | canonical 충돌과 spec 중첩은 막는다. `duplicate-of`(F2)와 unresolved 중복(F3) 경로가 샌다 |
| 6. 시간·할당·실제 사용·정책 | 시간 의미는 분리됐다. 실제 wall의 범위(시도/캠페인)가 섞인다(F6) |
| 7. 보존·검증·변환·CLI | 입력 보존과 새 파일 쓰기는 문서와 일치한다. 요청/관측 분리(F4), P2 lane 목록(F5), 과거 scope 변환(F7)이 문서와 어긋난다 |

## 1. 구현 오류

### F1 — 높음. binding-only 판정이 이름 거부목록이어서 위치·binding 주장이 원인 연결에 들어간다

- **위치:** `mod.rs:133–142`, `mod.rs:427–434`(`binding_only`), `mod.rs:449`(`eligible`).
- **조건:** 요청 관측의 귀속이 `matched`이고 방법 이름이 `location-match`, `single-target`, `known-defect-target`, `p2-found`, `ground-truth-location` 등이다. 나머지 조건(general 층, reported-confirmed, localized, complete, canonical, metadata binding)이 충족된다.
- **잘못되는 결과:** `binding_only()`는 이름에 `binding`이 들어 있거나 정확히 `knowndefectsingletarget`일 때만 참이다. 그래서 위 이름들은 통과하고 원인 키가 만들어진다. 계약 M1과 "위치 일치만으로 주 성과에 넣지 않는다"를 어긴다. P2 결과를 관측으로 옮길 때 이런 이름을 쓰는 일은 충분히 있을 수 있다.
- **최소 수정:** 허용목록으로 바꾼다. 귀속 방법을 닫힌 열거형이나 등록된 방법 ID로 받고, 나머지는 `AttributionState::Unknown`으로 정규화한다. 위 이름들로 회귀 테스트를 넣는다.

### F2 — 높음. `duplicate-of` 표시가 원인 키를 새로 만들거나 다른 키로 보낸다

- **위치:** `mod.rs:461–470`(`canonical_cause`, 특히 467), `mod.rs:158–190`.
- **조건 A:** 관측 1(후보 a)은 canonical이고 귀속 C1이다. 관측 2(후보 b)는 귀속 C1이지만 `duplicate-of: C1-alias`다.
- **조건 B:** 관측 하나가 귀속 C1, `duplicate-of: C9`이고, 기록 안에 C9의 canonical 관측이 없다.
- **잘못되는 결과:** A에서는 `{C1:[1], C1-alias:[2]}`로 원인 키가 둘이 된다. B에서는 중복 표시만으로 C9 키가 생긴다. 다중 원인 점검(158–173)도 바뀐 ID를 쓰므로 충돌을 잡지 못한다. 기존 테스트(284–334)는 canonical이 같은 기록에 있는 경우만 다룬다.
- **최소 수정:** `duplicate-of`의 대상은 같은 기록 안에 eligible한 canonical 관측이 있는 원인이어야 한다. 아니면 그 관측을 unresolved로 두고 `aggregation_issues`에 남긴다. 귀속 ID와 대상 ID가 다르면 별칭 근거 없이는 연결하지 않는다.

### F3 — 중간. 중복이 unresolved인 귀속은 다중 원인 점검을 피해 간다

- **위치:** `mod.rs:158–173`.
- **조건:** 같은 후보 해시에 eligible 관측이 둘 있다. 하나는 canonical C1, 다른 하나는 `matched` C2이고 중복은 `unresolved`다.
- **잘못되는 결과:** 첫 단계가 eligible이면서 canonical ID가 있는 행만 모으므로 C2는 들어가지 않는다. 그래서 그 후보가 ambiguous로 표시되지 않고 C1에 연결된다. 원인별 독립 근거 없는 복수 귀속을 인정하지 않는다는 원칙과 문서 64행("같은 후보가 여러 원인에 연결되면 ambiguous")에 어긋난다.
- **최소 수정:** ambiguity 집합을 중복 상태와 무관하게 만든다. 적어도 general 층의 `matched` 귀속 전부에서 `proposed_cause_id`와 중복 대상 ID를 모은다. 층이 다른 `matched` 주장이 충돌해도 issue로 남기는 편이 보수적이다.

### F4 — 중간. runner-result는 요청의 target_id를 관측값으로 기록한다

- **위치:** `legacy.rs:20–28`(22 `check_id`, 24 덮어쓰기), `mod.rs:59–64`. 문서 `evidence_record_v1.md:32`.
- **조건:** `runner-result`를 원본으로 쓴다. 실제 `RunResult`에는 `target_id` 필드가 없다(테스트 fixture 25–36행도 없다). 요청은 `target_id: "T"`를 준다.
- **잘못되는 결과:** `check_id`는 원본에 필드가 없으면 그냥 통과하고, 24행이 `execution.target_id = known("T")`로 덮어쓴다. 원본이 말하지 않은 정체성이 관측값처럼 기록되고, 과거 검토 행의 선택(59–64)도 이 주장으로 정해진다. 이 형식은 후보 목록이 비어 있어 원인 연결까지 가지는 않는다. 그러나 "요청이 선언한 ID와 입력에서 관측한 ID를 분리한다"는 문서 원칙에 어긋나고, 후속 집계가 이 필드를 믿으면 오연결이 생긴다. 테스트(165–209)는 이 출처를 확인하지 않는다.
- **최소 수정:** 관측 target은 `unknown("RunResult does not record target_id")`로 두고 `requested_target_id`를 따로 기록한다. 과거 행 선택이 요청 주장에 기댔다면 선택 근거를 표시한다.

### F5 — 중간. 실제 P2 lane `path-order`를 인식하지 못해 방식 충돌을 거부하지 않는다

- **위치:** `legacy.rs:169–180`, `205–219`. 문서 `evidence_record_v1.md:30`.
- **조건:** P2 ledger의 lane이 `path-order`다. 실제 P2 ledger 8개 중 2개가 그렇다(inference·zk-email). 요청의 `context.method`는 `whole`이다.
- **잘못되는 결과:** lane이 알려진 목록에 없으므로 방식 점검을 건너뛴다. 분할 실행이 통째 실행으로 기록되고, 그 lane의 완료 상한 시간은 "의미 미확인"으로 내려간다. 목록에는 P2에 없던 `risk-only`가 들어 있다.
- **최소 수정:** `path-order`를 split에 넣고, 모르는 lane은 오류로 처리한다(실패 시 닫힘). 실제 lane 값 넷으로 회귀 테스트를 넣는다.

### F6 — 중간. `actual_wall_seconds`의 범위가 형식마다 다르다

- **위치:** `schema.rs:242`. `legacy.rs:141`(runner·outcome: run 하나의 wall), `legacy.rs:196`(P2: ledger `elapsed_seconds`).
- **조건:** P2 분할 ledger의 `elapsed_seconds`는 조각 전체 캠페인의 경과시간이다(zkfDO lane은 `scheduler.elapsed_seconds`, direct lane은 캠페인 시작부터). P2 통째는 프로세스 하나의 경과다. outcome·runner는 시도 하나의 wall이다.
- **잘못되는 결과:** 같은 필드가 시도 범위와 캠페인 범위를 섞어 담는다. 할당은 `allocated_attempt_seconds`와 `allocated_campaign_seconds`로 나눴으면서 실제 사용은 나누지 않아, 형식이 다른 기록끼리 자원 비교를 하면 범위가 어긋난다.
- **최소 수정:** `actual_attempt_wall_seconds`와 `actual_campaign_wall_seconds`로 나누거나, `TimingObservation`처럼 범위와 기준점을 붙인다.

### F7 — 중간. 과거 scope·판정 기준의 의미가 정규화 과정에서 손실된다

- **위치:** `mod.rs:524–548`(특히 524–528), `539`. 문서 `evidence_record_v1.md:55`.
- **조건 1:** 과거 `BackendReview`의 `expected_scope`가 `project`, `wrapper-only`, `reachability-unknown`이고 `disposition`이 `validated`다.
- **결과 1:** 과거 엔진은 이 scope들에서도 공통 판정 기준을 평가했다(`project`는 그에 더해 production 도달성도 검증). 그런데 정규화된 `component`는 "not-attempted"로 기록된다. 상향 전환은 없지만 사실과 다르고, 문서 55행("component 판정은 reported-confirmed로만 옮긴다")과도 어긋난다. 실제 데이터 테스트(600–649)는 `original-component`만 다룬다.
- **조건 2:** 과거 `rejected`가 입력 전제(계약) 불충족 때문에 나온 행이다.
- **결과 2:** 정규화된 `component.state = rejected`에 어느 기준이 실패했는지가 없다. 전제 위반을 무조건 부적격으로 읽게 만들 수 있다. 실패 기준은 원본 행에만 있다.
- **최소 수정:** 모든 scope에서 `disposition`을 legacy 층 상태로 옮기고, 과거 scope와 실패 기준 ID를 reason이나 필드로 남긴다. Project scope 테스트를 추가한다.

### F8 — 중간. 출력 차이형과 abort형을 구분할 필드가 없다

- **위치:** `schema.rs:193–214`(`ReviewObservation`).
- **조건:** 정상 계산이 abort한 후보와 출력이 다른 후보가 모두 general reported-confirmed로 들어온다.
- **잘못되는 결과:** 두 유형의 증거 조건(abort형은 정상 계산이 어디서 abort했는지, 출력형은 같은 입력의 정상 출력)을 기록하거나 강제할 수 없다. 과거 `violation_class`도 원본 행에만 있다. 이전 계약의 보정 사항("정상 종료형과 abort형의 증거 조건은 다르다")을 담을 자리가 없고, 문서에 미구현으로 적혀 있지도 않다.
- **최소 수정:** `violation_kind`(output-difference, computation-abort, tool-specific-check, unknown)와 유형별 증거 참조를 둔다. general reported-confirmed에는 유형을 known으로 요구한다. 과거 `violation_class`는 legacy 문자열로만 옮긴다.

### F9 — 낮음. 방식별 일관성 점검이 없다

- **위치:** `mod.rs:441–454`.
- **조건:** `whole` 관측이 `localized`인데 `projection`은 `not-attempted`다. 또는 `split` 관측이 `root`를 주장한다.
- **결과:** 두 경우 모두 eligible이다. 통째 후보의 컴포넌트 연결 근거가 없거나, 조각에는 없는 root가 원인으로 연결된다.
- **최소 수정:** `context.method`를 참조해 모순된 조합을 거부하거나 unresolved로 둔다. 특정 투영 알고리즘을 강제할 필요는 없고, 근거가 기록됐는지만 본다.

### F10 — 낮음. 국소화 방법과 검증 상태가 기록되지 않는다

- **위치:** `schema.rs:163–183`.
- **결과:** 원인 연결은 `localized`·`root` 주장에 기대는데, 그 주장이 미검증 가설(첫 분기 투영)에서 나왔는지 기록에 없다.
- **최소 수정:** `localization.method`와 `method_validated`(현재 unknown)를 두고, 연결마다 그 상태를 보인다.

### F11 — 낮음. run과 target이 충돌해도 조용히 건너뛰고, 같은 보고서가 두 번 들어갈 수 있다

- **위치:** `mod.rs:60–64`, `legacy.rs:257–259`, `mod.rs:89–92`·`550–553`, `mod.rs:258`.
- **조건:** run_id는 같고 target_id가 다른 과거 행이나 후보 항목이 있다. 또는 같은 보고서를 16진수 대소문자만 다르게 두 번 넣는다.
- **결과:** 충돌이 보고되지 않고 사라진다. 같은 보고서는 해시 비교가 대소문자 무시이고 관측 ID는 입력한 그대로 쓰므로 두 번 들어간다. 과거 행이라 원인 연결은 생기지 않지만 검토 행 수가 두 배가 된다.
- **최소 수정:** run이 같은데 target이 다르면 오류나 issue로 남긴다. 해시를 소문자로 정규화한 뒤 ID를 만들고 중복을 거부한다.

### F12 — 낮음. 검토 행이 없는 후보는 상태가 명시되지 않는다

- **위치:** `mod.rs:37–151`.
- **조건:** outcome의 후보가 어떤 보고서나 관측에도 나오지 않는다.
- **결과:** `execution.candidates`에만 있고 검토 상태가 없다. 후속 집계가 이를 "후보 없음"이나 음성으로 읽을 위험이 있다.
- **최소 수정:** 그런 후보마다 `not-started` 관측을 만들거나, 미검토 목록을 출력한다.

### F13 — 낮음. 그 밖의 형식·위생 문제

- **보고서와 원본의 관계 미확인.** 보고서와 원본은 run_id(UUID)와 target만으로 연결되고, 보고서가 이 outcome에서 나왔는지는 대조하지 않는다. 우연한 충돌 가능성은 낮지만 "관계 미확인"을 기록하는 편이 좋다.
- **절대 경로.** `mod.rs:23`·`194`가 요청 경로를 절대 경로로 기록해 로컬 디렉터리가 출력에 남는다. 다른 참조는 상대 경로다.
- **범주가 자유 문자열.** `termination_reason`과 시간 `meaning`·`origin`이 자유 문자열이라(`schema.rs:216–221`, `249`) 후속 집계가 문자열을 해석해야 한다.
- **필드 의미 혼동.** outcome의 `execution_mode`(`ranking-separated`)가 `source_method`에 들어간다(`legacy.rs:95`).
- **하네스 정보 누락.** P2 ledger의 `runner: direct`를 읽지 않아 하네스가 unknown으로 남는다.

## 2. 문서에 명시된 미구현 범위(오류 아님)와 남는 위험

문서 65·76–84행이 미구현을 명시한 것은 다음과 같다. 단위 5상태 집계, 기록 간 원인 등록부·중복 제거, 후보 원문의 T1 추출, A 정책의 실행·자원·잔여 계측, 일반 TCCT 판정, 국소화 알고리즘, wrapper 의미 대응, 통째·분할 후보의 의미 검토. 이것들은 unknown이나 limitations로 정직하게 처리돼 있다.

**남는 위험.** 증거 참조를 열거나 다시 해시하지 않는다는 점은 문서에 명시돼 있다(`limitations` 5번째). 그러나 그 결과, 요청 관측의 증거·국소화·귀속 근거가 존재하지 않는 파일이어도 원인 연결이 만들어진다. 요청 관측의 층·방법·판정도 모두 신고된 주장이다. 후속 집계는 연결마다 출처(과거 엔진인지 요청 관측인지)와 증거 검증 상태를 보이고, 검증되지 않은 연결을 확인된 원인으로 세지 않아야 한다. 요청 기준 경로의 증거는 `read_pinned`로 해시를 확인하는 것이 가장 작은 보강이다.

## 3. 테스트 공백

기존 테스트(통합 16개, 모듈 단위 4개)에는 위 오류를 잡는 사례가 없다. 이번 검토에서 테스트를 실행하지는 않았다. 추가할 비보안 합성 사례는 다음과 같다.
- F1의 방법 이름 변형.
- F2의 `duplicate-of` 별칭·대상 부재.
- F3의 unresolved 중복 + canonical 충돌.
- F4의 실제 `RunResult` 모양(target_id 없음)에서 target 출처 확인.
- F5의 `path-order`.
- F6의 P2 분할과 outcome의 wall 범위.
- F7의 `project` scope와 전제 실패 `rejected` 행.
- F11의 run/target 충돌과 대소문자만 다른 보고서 중복.
- F12의 검토 행 없는 후보.

## 4. 이전 계약 보정의 유지

| 보정 | 판단 |
|---|---|
| 정상 종료형과 abort형의 증거 조건 구분 | 미지원(F8) |
| complete + unresolved는 확정 판정이 아님 | 표현은 가능하고 v1에 음성 집계가 없어 지켜진다. 후속 집계도 이를 확정으로 쓰면 안 된다 |
| 첫 분기 국소화는 미검증 방법 가설 | 문서에는 명시돼 있다. 기록에는 방법·검증 상태가 없다(F10) |
| 동등한 증거 기준 ≠ 특정 알고리즘 강제 | 지켜진다. 두 방식에 같은 기록 조건만 요구하고 알고리즘은 강제하지 않는다 |
| 원인별 독립 근거 없는 복수 귀속 불인정 | 부분적. `multi` 제외와 canonical 충돌은 막지만, F2·F3 경로가 샌다 |
| 구조 테스트 ≠ 의미 검증 | 지켜진다. 문서·limitations·관문 설명에 명시돼 있다 |

## 5. 핵심 필수 의견

1. **F1:** 귀속 방법을 허용목록으로 바꾸고, 목록 밖의 방법은 unknown으로 둔다.
2. **F2:** `duplicate-of`는 같은 기록 안의 canonical 원인만 가리킬 수 있게 한다. 그렇지 않으면 unresolved로 두고 issue로 남긴다.
3. **F3:** 다중 원인 점검을 중복 상태와 무관하게, 모든 general `matched` 귀속에 적용한다.
4. **F4·F5:** 요청이 주장한 ID와 관측한 ID를 분리하고, 모르는 P2 lane은 실패시킨다.
5. **F6·F7·F8:** 실제 wall의 범위, 과거 scope·실패 기준, 위반 유형을 기록 형식에 넣는다.
6. 후속 집계는 이 수정 전의 `component_cause_links`를 원인 수의 근거로 쓰지 않는다. 고친 뒤에도 연결은 신고된 주장이며, 의미 관문(통째·분할 후보의 같은 수준 검토)을 대신하지 않는다.
