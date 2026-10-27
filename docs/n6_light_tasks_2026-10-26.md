# N6 경량 분석 세 가지 (2026-10-26)

상태: 완료. 담당: miiz. B 배제 집계 → 고정 소스의 입력 의존성 확인 → 기존 결과의 RQ-C 채점 순서로 수행했다. 기존 엔진·실행기·프로토콜·실행 기록·판정 파일은 수정하지 않았다. 새 퍼징, J, `lift-instances`, 판정 실행기, 외부 연락·업로드는 실행하지 않았다. 사냥 후보와 aq 탐색층 판정은 열지 않았다. `runs/`는 재귀 탐색하지 않고 문서·index·state·join에 명시된 파일만 직접 읽었다.

시작 시 내장 여유는 24.751 GiB였다(`shutil.disk_usage` 읽기 전 확인). 마감 시 내장 여유는 24.739 GiB였다. 새 집계기는 매 파일 읽기 전에 15 GiB 기준을 검사한다. 출력은 판정·식별자·경로·해시·건수뿐이며 후보·입력·witness 값은 저장하지 않는다.

## 1. B 1묶음 배제의 증명 종류

### 범위와 집계 단위

저장된 관문 `runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json`의 `status=passed`를 확인했다. 이 관문의 범위는 전체 107요청 중 엔진별 종료 44, 양쪽 판정 가능 27, 준비 실패로 양쪽 판정 불가 17, 공간 부족으로 미완료 63이다. **350/349는 판정 가능한 27요청에서 나온 클래스 수이며 전체 107요청의 완료 결과가 아니다.** 숫자 근거: [저장된 관문](../runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json).

단위는 `(request_id, representative)`다. 같은 회로 인스턴스의 반복 후보를 고유 버그 수로 바꾸지 않았다. 각 엔진의 state가 가리키는 result 27개와 관문이 가리키는 join 4개를 읽고 SHA-256을 대조했다. 총 result 54개·join 8개가 일치했다. 자기 판정 클래스는 엔진마다 461개이며, v2.2는 배제 350·unknown 111, v1은 배제 349·unknown 112다. 저장된 공유 술어 클래스 6개는 모두 unknown이고 추가 배제는 없다. 근거: [B 집계 JSON의 engines/results·joins·class_verdicts](n6_light_exclusions_2026-10-26.json), 각 원본 경로·해시는 그 JSON에 있다.

### 증명별·엔진별

| reason / exclusion_basis / exclusion_method | v2.2 클래스 | v1 클래스 | 근거 파일 |
|---|---:|---:|---|
| `closed_cone_unsat / o0_closed_cone / bit_decomposition_interval` | 249 | 249 | [B 집계 proof_counts](n6_light_exclusions_2026-10-26.json) |
| `closed_cone_unsat / o0_closed_cone / z3+propagation` | 38 | 37 | [B 집계 proof_counts](n6_light_exclusions_2026-10-26.json) |
| `constant_input_mismatch / o0_only_signal_eliminated_in_o1 / 미기록` | 27 | 27 | [B 집계 proof_counts](n6_light_exclusions_2026-10-26.json) |
| `local_constraint_refutation / 미기록 / 미기록` | 36 | 36 | [B 집계 proof_counts](n6_light_exclusions_2026-10-26.json) |
| **합계** | **350** | **349** | [B 집계 excluded_total·expected_total](n6_light_exclusions_2026-10-26.json) |

`z3+propagation`은 z3 unsat과 전파 근거가 함께 기록된 종류다. 전파만의 모순을 z3 증명으로 다시 이름 붙이지 않았다. 상수 불일치의 27개는 모두 **O0 근거이며 O1에서 신호가 제거된 경우**다. 이 분석으로 O1 증명을 새로 추가한 것은 아니다. 숫자·원문 필드 근거: [B 집계 excluded_classes](n6_light_exclusions_2026-10-26.json).

### 리비전별

| 리비전 | 엔진 | 비트 범위 | z3+propagation | 상수 불일치 | local refutation | 배제 합 | 근거 파일 |
|---|---|---:|---:|---:|---:|---:|---|
| `340107e1f1d8b0a45656cffa` | v2.2 | 1 | 0 | 3 | 0 | 4 | [B 집계 by_revision](n6_light_exclusions_2026-10-26.json) |
| 동일 | v1 | 1 | 0 | 3 | 0 | 4 | [B 집계 by_revision](n6_light_exclusions_2026-10-26.json) |
| `b5b5cf5dacdeebd430b519f8` | v2.2 | 47 | 9 | 6 | 0 | 62 | [B 집계 by_revision](n6_light_exclusions_2026-10-26.json) |
| 동일 | v1 | 47 | 9 | 6 | 0 | 62 | [B 집계 by_revision](n6_light_exclusions_2026-10-26.json) |
| `4c221df76273c0d7cf18048c` | v2.2 | 201 | 29 | 18 | 36 | 284 | [B 집계 by_revision](n6_light_exclusions_2026-10-26.json) |
| 동일 | v1 | 201 | 28 | 18 | 36 | 283 | [B 집계 by_revision](n6_light_exclusions_2026-10-26.json) |
| `a8b2aa9c2857e79c017805bb` | 각각 | 0 | 0 | 0 | 0 | 0 | [B 집계 by_revision](n6_light_exclusions_2026-10-26.json); 판정 가능 결과 있음 |
| `6079a717f929aaf04a04e329` | 각각 | — | — | — | — | 판정 없음 | [B 집계 revision_status_counts](n6_light_exclusions_2026-10-26.json); 준비 실패만 있음 |

`local_constraint_refutation` 비율은 배제 클래스 분모에서 **v2.2 36/350 = 10.2857%, v1 36/349 = 10.3152%**다([B 집계 local_fraction·local_percent](n6_light_exclusions_2026-10-26.json)). 전부 `4c221df7…`의 queue 25·27·29·31·33·35에서 각각 6개다(같은 JSON의 `excluded_classes`). 이 종류는 구성 입력의 실제 값을 고정한 반박이며, 정확한 값 사용 범위는 다음 절에 적었다.

차이 1개는 queue 25의 `main.BabyJubJubSubGroupPointTag_198_9493.eMul.m2e[0]`다. [v2.2 result](../runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/main/0004/requests/000025/attempt-0001/result.json)는 `z3+propagation` 배제, [v1 result](../runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/main/0004/requests/000025/attempt-0001/result.json)는 `budget_exhausted` unknown이다. 기존 [사람 검토 자료](n6_b6h_review_v22_only_exclusion_2026-10-25.md)의 구분과 일치한다. 재판정은 하지 않았다.

보수적 선택: `exclusion_basis/method`가 없는 local refutation은 소스 설명만 병기하고, 결과에 없던 z3·O0/O1 증명 라벨을 만들어 채우지 않았다.

## 2. 기준 입력 없이 배제가 가능한가 — 코드만 확인

검토 커밋은 **`8065e2b7e165ef3f4c1523f240f5d34ecaefdb22`**다. 아래 파일:줄은 이 커밋의 `src/candidate_review/lifting/` 기준이다. 증명식의 값 의존성과 그 증명에 도달하는 실행 흐름의 값 의존성을 구분했다.

| 배제 경로 | 기준 입력 파일 값 / 키 구조 사용 | 코드 근거 |
|---|---|---|
| `conflicting_input_binding` | 증명은 기준 입력 값·키를 직접 읽지 않는다. 동일 입력으로 묶인 **후보 값**끼리 충돌하는지 O0 동등류·심볼로 검사한다. | `mod.rs:1635-1641`, `1655-1656`, `1670-1688`, `1731-1734` |
| `constant_input_mismatch` | 증명은 기준 입력 값·키를 읽지 않는다. 회로 상수와 후보 값을 비교하고 가능한 O1 대응만 교차 확인한다. | `mod.rs:1691-1720`, `1745-1764` |
| `o0_closed_cone` z3 unsat — joint/small branch | 증명에 고정하는 값은 후보가 결정한 직접 입력·중간 입력·TCCT 입출력이다. 기준 입력 값은 SMT 고정값에 넣지 않는다. 입력 키·배열 구조는 구성 입력 갱신에 필요하고 선행 계산은 값을 사용한다. | `mod.rs:1902-1907`, `1923-1929`, `2782-2802`, `2991-2999`, `3013-3032`; `synth.rs:298-328`, `362-368`, `396-434` |
| `o0_closed_cone` z3 unsat — sweep | 같은 후보 유래 `fixed_values`만 증명에 사용한다. 선행 실행의 값 의존성은 남는다. | `mod.rs:3163-3168`, `3194-3196`; `synth.rs:453-499` |
| `o0_closed_cone / bit_decomposition_interval` | 후보 유래 고정값과 회로가 함의하는 범위를 사용한다. 기준 입력 값으로 abort 위치를 찾는 별도 진단 전파는 배제 반환 경로가 아니다. | 배제 `mod.rs:2900-2943`, `bitrange.rs:157-179`; 진단 `mod.rs:2871-2899` |
| `local_constraint_refutation` — O1 우선/O0 fallback | **실제 값 필요.** 기준 입력을 복제하고 후보와 직접 결합된 잎만 덮어쓴 구성 입력의 모든 main 입력값을 고정한다. 구현은 공개뿐 아니라 사설 입력도 포함한다. 후보가 덮어쓰지 않은 기준 입력 값이 남을 수 있다. | 구성 `mod.rs:1896-1907`; O1/O0 `3366-3413`; `public_inputs + private_inputs` 고정 `3472-3480`; 후보 추가 `3487-3507`; 배제/unknown 분기 `3510-3522`; `refute.rs:93-128`, `204-228` |
| `assumption_excluded_in_context / predicate_cone_unsat` | 증명 자체는 기준 입력 값·키와 후보 값을 고정하지 않는다. 위반 술어와 O0 부분 제약 및 회로가 함의하는 범위 사실로 unsat을 증명한다. 별도 도달 탐색은 기준 입력 값을 쓴다. | `predicate.rs:13-16`, `135-169`, `390-415`, `988-1015`; 별도 탐색 `479-487`; `repair.rs:524-595` |
| 술어 배제 재사용·집계 | 새 증명은 아니다. **캐시 키에는 기준 입력의 값까지 직렬화한 해시가 들어간다.** 결과 집계 자체는 판정 문자열을 사용한다. | 키 `mod.rs:910-918`; 재사용 `predicate.rs:370-387`, `675-714`; 집계 `815-828`, `instances.rs:157-170` |

**결론은 (나): 일부 경로만 값이 필요하다.** 배제 증명 자체에서 `local_constraint_refutation`은 구성 입력의 실제 값을 사용한다. 나머지 binding·상수·closed cone·비트 범위·가정 술어 배제 증명은 기준 입력 값을 고정하지 않는다. “기준 입력 값 불필요”는 “후보 값도 불필요”를 뜻하지 않는다.

현재 엔진을 입력 파일 없이 그대로 실행할 수 있다는 뜻도 아니다. 공통 준비는 먼저 기준 입력을 읽고 JSON으로 해석한다(`mod.rs:509-515`). 합성은 실제 구성 입력으로 기준 계산부터 시도하며, assert나 다른 abort이면 closed-cone 단계 전에 unknown이 될 수 있다(`mod.rs:2612-2626`, `2665-2687`). **키 구조만 유지해 값을 바꿔도 전체 실행 결과가 항상 같다고 보장할 수 없다.**

보수적 선택: `refutation_verdict`는 각 site 입력의 직접 결합/상수 여부만 확인하고 모든 main 입력이 후보로 덮였는지는 별도로 검사하지 않는다(`mod.rs:3514-3519`). 이번 작업은 코드 읽기만 했으므로 기존 local 배제의 건전성을 새로 확정하거나 부정하지 않고 값 의존 경로로 기록했다.

## 3. RQ-C 오프라인 채점

### 고정 정의·매핑과 집계 규칙

[N5 프로토콜](n5_evaluation_protocol_v1_2026-10-06.md)의 SHA-256은 **`ad6cf87b80223436db35d8a43c30659075fbc05423f1ade93f8fd8b830fad3e7`**로 요청값과 일치한다. 정의 근거는 같은 파일 `:18`, L1 정의 `:78`, 같은 수준·입력 분류 `:81`, 수정 전·후 및 연쇄/LOO 규칙 `:85-89`다. W의 후보에도 저장된 J 판정을 적용해 같은 확인 수준으로 비교한다.

- 고정 분모 70항목, 수정 커밋 있는 항목 50개는 [대상 목록](n6_targets_a_2026-10-07.json)에 그대로 보존했다. 고정 J 매핑은 18항목·26행이며, 취약 18 + 수정 7 + LOO 1이다. 나머지 52항목도 출력 JSON에 남긴다. 근거: [고정 매핑](../runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json), [준비 단위](../runs/n6-a1-2026-10-07/preparation-units.json), [엄격층 채점 denominators·bugs](n6_light_rqc_strict_2026-10-26.json).
- 버그별 단위는 고정 `item_id`다. seed·후보·클래스가 반복돼도 방법별로 한 번만 센다. 위치는 고정 매핑의 템플릿 인스턴스와 그 하위 경로를 사용하며, 부모 TCCT를 매핑된 자식 결함으로 귀속하지 않는다. 실제 읽은 index의 entrypoint SHA가 고정 매핑과 다르면 중단한다. 구현: `scripts/n6_light_rqc_20261026.py`의 `under`, `classify_class`, `attribute_class`, `score`.
- 저장된 join을 해시 검증해 읽으며 새 J나 join 명령을 실행하지 않는다. 결과의 entrypoint 해시·request 해시·join 결과 경로 집합도 대조한다. 술어의 any-reach/all-excluded/otherwise-unknown 규칙은 고정 `instances.rs:151-170`과 같다.
- 후보 없음·준비 실패·미실행·매핑 없음은 엔진 unknown이나 배제로 바꾸지 않는다. 여러 요청에서 서로 다른 상태가 관측되면 모두 보존하고, 프로토콜에 없는 단일 우선순위로 합치지 않는다.
- 하나의 실제 관측 위치가 여러 버그에 동시에 대응하면 `definition_outside: ambiguous_bug_location`에 보존하고 공식 확인으로 승격하지 않는다. 고정 템플릿 매핑을 새 신호 매핑으로 바꾸지 않는다. 이유: 같은 넓은 템플릿의 서로 다른 버그에 같은 L1을 자동 귀속하는 규칙은 N5에 없다.

### A 엄격층 — 공식 완료 결과

공식 v1 index의 **2,926요청 = 완료 765 + 준비 실패 2,161**을 확인했다. 완료 result 765개와 저장된 revision join 11개를 해시 대조했다. 이 중 고정 위치 매핑에 해당하는 완료 요청은 616개이고 나머지 개발 자료의 완료 149개는 고정 18/26 매핑 밖으로 따로 보존했다. 숫자와 원본 파일별 경로·SHA: [엄격층 채점 request_statuses·completed_outside_mapping_or_main·sources](n6_light_rqc_strict_2026-10-26.json); 원본 [공식 state](../runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json), [공식 index](../runs/n6-j1-2026-10-09.noindex/request-index.json). mem20 보완층은 main에 합산하지 않는다.

아래는 고정 J 매핑에 선택된 **18버그**의 버그별 집계다. 배제는 관측 후보/술어의 배제이며 템플릿 전체의 안전 판정이 아니다.

| 방식 | 취약 L1 | 취약 관측 없음 | 수정 배제 | 수정 unknown | 수정 L1 | 수정 관측 없음 | 수정 매핑 없음 | 근거 파일 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| W | 1 | 17 | 0 | 0 | 0 | 7 | 11 | [엄격층 bug_totals.W](n6_light_rqc_strict_2026-10-26.json) |
| S+J | 1 | 17 | 1 | 0 | 0 | 6 | 11 | [엄격층 bug_totals.S](n6_light_rqc_strict_2026-10-26.json) |

현재 관측에서 복수 상태·위치 귀속 모호성은 모두 0이다(같은 파일 `mixed_definition_outside`, `ambiguous_location_definition_outside`). 선택 18개 밖의 52개를 음성으로 간주하지 않았다. 수정 후 실제 판정이 관측된 버그에 한정한 unknown 비율은 S+J **0/1**, W는 분모 **0**이라 산출 불가다. 이는 전체 50개 수정 커밋 쌍의 정확도나 미판정률이 아니다. 근거: [엄격층 bugs·bug_totals](n6_light_rqc_strict_2026-10-26.json).

관측된 버그는 `worm-privacy/proof-of-burn/koukyosyumei_spend_missing_range_check`다.

| 리비전 | W | S+J | 도달 분류 | 근거 파일 |
|---|---|---|---|---|
| 취약 `aq-036-6d7df64759b6` | 577요청 → 버그 L1 1 | 27요청 → 버그 L1 1 | `public_inputs_changed` | [엄격층 해당 item의 methods/revisions](n6_light_rqc_strict_2026-10-26.json) |
| 수정 `aq-035-8f826c822cb8` | 0요청 → 관측 없음 | 12요청 → 버그 배제 1 | 도달 없음 | [엄격층 해당 item의 methods/revisions](n6_light_rqc_strict_2026-10-26.json) |

템플릿 매핑 `Spend → main`에 더해 실제 수정 위치도 소스로 대조했다. 취약 [spend.circom](../runs/n6-a3-2026-10-08.noindex/pragma/aq-036-6d7df64759b6/project/circuits/spend.circom):41-44는 `sufficientBalanceChecker = GreaterEqThan(252)`에 `balance`와 `withdrawnBalance`를 연결한다. 수정 [spend.circom](../runs/n6-a3-2026-10-08.noindex/pragma/aq-035-8f826c822cb8/project/circuits/spend.circom):33은 `AssertGreaterEqThan(maxAmountBits)(balance, withdrawnBalance)`로 변경되며, 같은 프로젝트 [utils/assert.circom](../runs/n6-a3-2026-10-08.noindex/pragma/aq-035-8f826c822cb8/project/circuits/utils/assert.circom):30-36은 양쪽 입력 범위를 검사한다. 저장된 관측 인스턴스는 취약 `main.sufficientBalanceChecker.lt`, 수정 `main.AssertGreaterEqThan_33_921.GreaterEqThan_35_693.lt`다([엄격층 observed_instances](n6_light_rqc_strict_2026-10-26.json)). 이는 현재 관측의 보조 위치 근거이며 고정 매핑 수정은 아니다.

W queue 2235와 S queue 2442 각각의 저장된 predicate에는 `method=candidate_witness`, `shared_from=null`인 도달 근거가 있다. 따라서 현재 두 방법의 버그 확인은 방법 간 공유만으로 만들어진 것이 아니다. 각 result 경로·SHA는 [엄격층 sources](n6_light_rqc_strict_2026-10-26.json)에 있다. 공개 입력 변경 도달을 실제 공격 가능성이나 새 취약점 제보로 해석하지 않았다.

### A 탐색층 — Banyan 개발 세트

Banyan은 고정 70항목에 포함돼 있지만 고정 18항목·26행 매핑은 `selected_aq_revisions`만 다루므로 해당 매핑 밖이다. 항목 ID는 `banyancomputer/hot-proofs-blake3-circom/koukyosyumei_checkdepth_comparator_overflow`다([대상 목록](n6_targets_a_2026-10-07.json), [고정 매핑](../runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json)). 새 공식 위치 매핑을 추정해 더하지 않고 **개발 쌍 한 건의 관측**으로 따로 보고한다.

| 엔진 | 방식 | 취약 버전 | 수정 버전 | 근거 파일 |
|---|---|---|---|---|
| v2.2 | W | 1,699요청, 개발 사례 L1 1 | 0요청, 관측 없음 | [Banyan v2.2 development_pair_observations](n6_light_rqc_banyan_v2.2_2026-10-26.json) |
| v2.2 | S+J | 108요청, 개발 사례 L1 1 | 24요청, 개발 사례 배제 1 | [Banyan v2.2 development_pair_observations](n6_light_rqc_banyan_v2.2_2026-10-26.json) |
| v1 | W | 1,699요청, 개발 사례 L1 1 | 0요청, 관측 없음 | [Banyan v1 development_pair_observations](n6_light_rqc_banyan_v1_2026-10-26.json) |
| v1 | S+J | 108요청, 개발 사례 L1 1 | 24요청, 개발 사례 배제 1 | [Banyan v1 development_pair_observations](n6_light_rqc_banyan_v1_2026-10-26.json) |

엔진별 완료 1,831건, 합계 3,662개 result와 저장 join 4개를 대조했다. L1 도달 분류는 `private_only`다. 숫자·해시 근거: 위 두 채점 JSON의 `request_statuses`, `sources`, `development_pair_observations`; 원본 [Banyan aggregate](../runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json). 배제는 구성 입력 기준이며 엄격층 버그 수에 더하지 않는다. `formal_bug_score=null`로 저장했다. 독립 평가가 아니라 개발 세트다.

### 정의 밖·미관측을 다루는 방식

| 항목 | 처리와 이유 | 근거 |
|---|---|---|
| 고정 J 매핑 밖의 개발 자료 | 전체 70행은 유지하되 공식 bug score에 새 위치 연결을 추가하지 않는다. Banyan은 별도 개발 쌍 요약이다. | 고정 매핑 `mapping_scope`; 채점 JSON `completed_outside_mapping_or_main` |
| 수정본 후보 없음, 준비 실패, 미실행 | 관측 없음으로 남긴다. 엔진 unknown이나 배제가 아니다. | 채점 JSON의 요청 상태·`no_observation` |
| 같은 위치가 여러 item에 대응 | 실제 그런 관측이 생기면 `ambiguous_bug_location`으로 별도 보존한다. | 새 스크립트 `attribute_class`; 현재 해당 관측 없음 |
| 여러 요청에서 L1·배제·unknown 혼재 | 버그당 각 관측 여부만 보존하고 혼재 표시를 둔다. 임의 우선순위로 완전 배제/미판정을 결정하지 않는다. | 새 스크립트 `aggregate_cells` |
| 수정 전·후 대응과 원인 귀속 | 현재 결과는 위치에 대응한 L1/배제 관측이다. L2 사람 검토·새 고유 원인 인증을 자동 수행하지 않는다. | N5 `:78-89` |
| 최초 확인 시각 | 저장된 후보 완료 오프셋은 보조 필드만 제공한다. 이를 J 확인 완료시각으로 이름 바꾸지 않는다. | 채점 JSON `first_l1_candidate_observed_seconds`, `time_limitation` |
| aq 탐색층 | 이번에는 열람·채점하지 않았다. 향후 저장된 index/state/join만 받아 같은 코드로 채점한다. | 새 스크립트 CLI 및 `normalize_state` |

### 재실행 방법

새 채점 스크립트는 `--index`, `--state`, `--engine`, `--layer`를 받는다. 공식/Banyan state와 기존 aq 실행기의 중첩 `engines → requests/groups` state 형식을 지원한다. aq 형식 지원은 실행기 소스(`scripts/n6_a_remeasure_aq_execute.py:188-214`, `318-366`)와 합성 자료로만 검사했다. aq 실제 결과를 열지는 않았다. 저장된 join이 없거나 해시·고정 매핑이 다르면 중단하며 새 join을 생성하지 않는다.

아래 명령의 `NEW_OUTPUT.json`은 아직 없는 새 출력 경로로 정한다. 같은 출력을 덮어쓰지 않는다. aq는 완료된 저장 state가 생긴 뒤에만 실행할 예시다.

```sh
python3 -B scripts/n6_light_rqc_20261026.py \
  --protocol docs/n5_evaluation_protocol_v1_2026-10-06.md \
  --targets docs/n6_targets_a_2026-10-07.json \
  --mapping runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json \
  --preparation runs/n6-a1-2026-10-07/preparation-units.json \
  --index runs/n6-a-remeasure-2026-10-25.noindex/prepared-aq/request-index-v2.2.json \
  --state runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/state.json \
  --engine v2.2 --layer exploratory --output NEW_OUTPUT.json
```

공식 엄격층은 index를 `runs/n6-j1-2026-10-09.noindex/request-index.json`, state를 `runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json`, engine/layer를 `v1/strict`로 바꾼다. Banyan은 `runs/n6-a-remeasure-2026-10-25.noindex/prepared/request-index-<engine>.json`과 `j-<engine>/state.json`을 쓰고 `--joins-source runs/n6-a-remeasure-2026-10-25.noindex/aggregates/aggregate-0001.json`을 추가한다. v1/v2.2는 각각 별도 출력으로 보존한다.

B 배제 집계 재현 명령:

```sh
python3 -B scripts/n6_light_exclusions_20261026.py \
  --gate runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json \
  --v22-state runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/state.json \
  --v1-state runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/state.json \
  --output NEW_B_OUTPUT.json
```

## 검증과 제한

`python3 -B scripts/n6_light_analysis_checks_20261026.py`의 합성 검사 12개가 통과했다. 부분 술어 배제와 unknown의 혼재, 부모 TCCT의 잘못된 자식 귀속, 유사 접두사, 다른 인스턴스 공유, 관측 없음, 반복 중복 제거, 복수 상태 보존, SHA 불일치 거부, 향후 aq state 형식, 여러 버그의 동일 위치 귀속을 검사한다. 실제 J·퍼징은 호출하지 않는다.

`cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`가 통과했다. Cargo는 offline·동시 빌드 1로 기존 빌드 캐시를 사용했다. `cargo test --no-run`도 통과했다. **전체 `cargo test`는 실행하지 않았다.** `tests/lifting_engine_test.rs:180-182` 등이 실제 `experiment lift`를 호출하므로 이번의 “J 엔진·판정 실행 금지”를 우선했다. 따라서 Rust 테스트 전체 통과로 보고하지 않는다. 새 Python 스크립트의 합성 검사와 저장된 실데이터 집계만 실행했다.

## 새 파일 SHA-256

아래 표의 해시는 최종 파일 바이트 기준이다. 자기 해시를 파일 안에 넣으면 파일 바이트가 다시 바뀌므로, 이 보고서 자체의 SHA-256은 완료 응답에 별도로 기록한다.

| 새 파일 | SHA-256 |
|---|---|
| [scripts/n6_light_exclusions_20261026.py](../scripts/n6_light_exclusions_20261026.py) | `bf5e8dd62e204b24e73585d89e875cc495fd00f46eda9e47856d9670cc44910d` |
| [scripts/n6_light_rqc_20261026.py](../scripts/n6_light_rqc_20261026.py) | `3344db9d8b1f18577e6e7fb5f80fd729331e05f35f0ae0510ec91960af27a20f` |
| [scripts/n6_light_analysis_checks_20261026.py](../scripts/n6_light_analysis_checks_20261026.py) | `790a166f730419a35d4d08b05be0d150969b17ab4cf25749f84cb28c680031b9` |
| [docs/n6_light_exclusions_2026-10-26.json](n6_light_exclusions_2026-10-26.json) | `c5ce2a98caea74aa4285978883e3816633499031bca83564102c7a4b0a4de27b` |
| [docs/n6_light_rqc_strict_2026-10-26.json](n6_light_rqc_strict_2026-10-26.json) | `0e99572bd584ad24adcb19723afd8ed838e7f23052f635a332aeda96ac917bca` |
| [docs/n6_light_rqc_banyan_v2.2_2026-10-26.json](n6_light_rqc_banyan_v2.2_2026-10-26.json) | `1f780cbc1bb67a6d3819bc0818337dbc10497b9e32c37bdac1e149299bca7274` |
| [docs/n6_light_rqc_banyan_v1_2026-10-26.json](n6_light_rqc_banyan_v1_2026-10-26.json) | `3a6459d3aae36127f2b6921de32745fb19dc380b9a77532b19167e8a8b524a4e` |

## 확인한 것

- 저장된 B result/joins의 해시와 배제 합계 350/349, 증명별·리비전별 분포, local refutation의 비율을 확인했다. 근거: [B 집계 JSON](n6_light_exclusions_2026-10-26.json).
- 고정 v2.2 소스에서 배제 경로별 값의 출처와 공통 입력 요구를 확인했다. 코드 결론은 (나)이며 실제 증명식과 앞선 실행의 의존성을 구분했다.
- 공식 완료 765건을 고정 70항목·18선택·26매핑에 대조했고, W/S 각각 같은 버그의 수정 전 L1 한 건 및 S 수정 후 배제 한 건을 확인했다. 근거: [엄격층 채점](n6_light_rqc_strict_2026-10-26.json).
- Banyan은 별도 개발 쌍으로 두 엔진의 관측을 확인했다. 공식 매핑 밖이라는 제한을 유지했다. 근거: [v2.2](n6_light_rqc_banyan_v2.2_2026-10-26.json), [v1](n6_light_rqc_banyan_v1_2026-10-26.json).
- 새 실행·재판정·제보 없이 저장된 자료만 집계했고, 기존 고정 파일을 덮어쓰지 않았다.

## 추정한 것·아직 확인하지 않은 것

- B local refutation에서 실제 어떤 기준 입력값이 후보 치환 뒤 남았는지, 그 값을 바꾸면 판정이 달라지는지는 확인하지 않았다. 코드상 값 의존성과 개별 판정의 오류는 같은 주장이 아니다.
- 입력 파일 없이 증명 단계만 분리했을 때의 실제 실행 결과는 측정하지 않았다. 다른 값으로 같은 키 구조를 주었을 때 전체 결과가 같다는 보장도 하지 않는다.
- aq 탐색층 결과와 성능·정확도는 추정하지 않았다. 향후 state 호환성은 코드 구조와 합성 자료로만 확인했다.
- 관측 없음·매핑 없음·준비 실패를 음성 정답으로 추정하지 않았으며, 현재 제한된 관측에서 일반 정확도·새 취약점·L2 원인 귀속을 주장하지 않는다.
