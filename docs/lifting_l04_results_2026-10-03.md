# L-04 결과: 탐색 예산, 위반 조건 대응, 비트 분해 범위, hint 주입

2026-10-03 · 담당 miiz · 기한 2026-10-07. 판정 정의는 [L-01 기준](lifting_feasibility_2026-10-02.md)과 [L-03 결과](lifting_assumption_results_2026-10-02.md)의 두 속성을 따른다. 실행 근거(요청·결과 경로, SHA-256, 엔진 소스·바이너리·도구 해시, 단계별 판정, zkFuzz 소스 위치, zk-email `component main` 목록)는 기계가 쓴 [evidence JSON](lifting_l04_evidence_2026-10-03.json)에 있다. 원시 값은 ignored `runs/l04-2026-10-02/`에만 있다. 새 zkFuzz 실행은 없다.

## 단계별 결과

| 단계 | 결과 | 회귀 |
|---|---|---|
| 0. (b) 배제 탐색 후보당 20초 | 구현. A-02 판정 1건이 바뀌었다(#27 excluded → unknown). | `exclusion_sweep_stops_when_the_candidate_budget_is_spent` |
| 1. zkFuzz `pos` 대응 | **대응 불가.** 조사 결과만 보고하고 멈췄다. | — |
| 2. 결과 위반 관측 | 1단계가 불가해서 지시대로 생략했다. 표에는 `not_evaluated`로 적는다. | — |
| 3. 비트 분해 구간 전파 | 구현. A-02 제약 abort 22건은 그대로 미판정이다. abort 인스턴스 특정은 0/22다. zk-email 9건과 range fixture는 이제 이 방법으로 배제된다. | `decomposition_range_refutes_…`(단위), `bit_decomposition_range_excludes_out_of_range_intermediate` |
| 4. hint 주입 | 구현. 모델 재현 실패 8건 중 3건이 도달했다. | `hint_injection_reaches_a_site_the_honest_hints_never_compute` |
| 5. zk-email 서비스 entrypoint | **막힘.** 같은 리비전에 서비스 `component main`이 없다. | — |

후보·프로젝트·템플릿 이름에 따른 분기는 넣지 않았다. 중단 기준에 대한 판단은 0단계 끝에 적는다.

## 0단계: 후보당 배제 탐색 예산

- 한 후보의 모든 위치가 가지 원뿔 배제 탐색에 쓰는 시간을 합쳐 20초로 묶었다.
- 예산을 다 쓴 뒤 남은 미판정 위치는 `unknown`(`budget_exhausted`)이다. 예산이 없었다면 붙었을 사유는 `synthesis.cause_before_budget`에 남긴다.
- 결합 원뿔 z3 한 번(최대 20초), 비트 분해 전파, hint 주입 컴파일은 이 예산 밖이다. 그래서 (b) 단계 합계는 20초를 넘을 수 있다(아래 비용 표).

**같은 엔진에서 상한만 넣었을 때 A-02 판정 분포**(L-03 결과 대 0단계 checkpoint):

| 속성 | L-03 | 상한 후 |
|---|---|---|
| TCCT 13건 class 44 | violation 9 · excluded 17 · unknown 18 | violation 9 · excluded 17 · unknown 18 |
| 입력 가정 18건 | reachable 0 · excluded 6 · unknown 12 | reachable 0 · excluded **5** · unknown **13** |

- **바뀐 1건:** #27 attempt 57 `ResponseTimeNormalized(40)`이다.
  - L-03에서는 가지 원뿔 탐색 29초째에 닫힌 원뿔 unsat을 찾아 배제됐다.
  - 상한 후에는 그 전에 예산이 끝나 `budget_exhausted`가 됐다(원래 사유 `abort_on_constraint_unresolved`).
- 나머지 미판정 22건은 판정이 그대로다. 사유 이름만 `budget_exhausted`로 바뀌었고, 원래 사유는 `cause_before_budget`에 그대로 남았다.
- **(b) 비용:** 합계가 919.1초에서 283.3초로 줄었다. 후보당 최대는 160.7초에서 20.3초로 줄었다.
- **중단 기준("대부분의 후보가 상한 소진"):** 예산을 다 쓴 후보는 14/31(45%)이다. 과반이 아니어서 계속했다. 14건은 정확히 미해결 위치를 가진 후보다. 해결되지 않는 위치는 거의 모두 예산을 끝까지 쓴다는 뜻이므로 기준에 가깝다.

## 1단계: zkFuzz `"5_flag"."2_violated_condition"."pos"` 조사

후보 JSON 67개(A-02 31, Banyan 36)의 `4_git_hash_of_zkfuzz`는 모두 `072bf1fb…`이다. `.external/zkFuzz`의 HEAD도 같은 커밋이다.

| 확인한 것 | 소스 위치 |
|---|---|
| JSON에는 `pos` 정수 하나만 쓴다. 조건 문자열은 사람이 읽는 출력에만 찍힌다. | `src/mutator/utils.rs:51-52`, `:75-76` |
| 기본 탐색 경로에서 `pos`는 `original_program_failure_pos`다. `emulate_symbolic_trace`가 `symbolic_trace`를 처음부터 실행하다 처음 실패한 원소의 index다. | `src/mutator/mutation_test_trace_fitness_fn.rs:91`, `:114-118`, `src/mutator/utils.rs:465-` |
| `symbolic_trace`는 대상 템플릿을 기호 실행하며 메모리에 쌓은 목록이다. 템플릿 인자 대입(`:180`), 하위 컴포넌트 trace 이어 붙이기(`:818-819`), 제약·대입(`:1350`), assert(`:1381`)에 zkFuzz가 스스로 넣는 의미 조건(예: `generate_lessthan_constraint`, `symbolic_value.rs:1044`)이 섞인다. 저장되지 않는다. | `src/executor/symbolic_execution.rs` |
| 소스 위치(`meta.elem_id`)는 전수 탐색 경로의 `violated_condition`에서만 쓴다. | `symbolic_execution.rs:1365`, `utils.rs:1291-1295` |

- **결론:** `pos`는 소스 줄도 R1CS 제약 index도 아니다. 저장되지 않은 zkFuzz 내부 trace의 위치다.
  - 되살리려면 같은 템플릿에 zkFuzz 기호 실행을 다시 돌려야 한다. 이번 지시("새 zkFuzz 실행 없음")에 어긋난다.
  - 되살려도 trace 원소는 zkFuzz 내부 이름으로 된 식이다. R1CS wire로 옮기는 규칙은 정의돼 있지 않다.
- 그래서 대응 규칙이 불명확하다고 판단했다. 2단계도 생략했다.
- **참고(구현하지 않음):** zk-email 후보는 로그에서 복원해서, 조건 문자열이 남아 있다. 예: `(BoolOr (BoolAnd (Eq 1 main.lt[11].out) (Lt main.lt[11].in[0] main.lt[11].in[1])) (BoolAnd (Eq 0 …) (GEq …)))`.
  - 이것은 `LessThan`의 정수 의미 조건이고, 컴포넌트 안 신호 이름으로 돼 있다.
  - A-02와 Banyan은 `-o` JSON만 있어 이 문자열이 없다. 한 자료에만 쓰이는 규칙이 되므로 만들지 않았다.
  - N5 동결 후 zkFuzz를 실행할 때 조건 문자열도 함께 저장하면 이 단계를 다시 열 수 있다.

## 3단계: 비트 분해 구간 전파

**구현(`src/candidate_review/lifting/bitrange.rs`).** 순서는 다음과 같다.
1. O0 등식 대표 단위로, 해가 {0, 1}뿐인 단일 변수 제약을 찾아 boolean wire로 표시한다.
2. `x = Σ c_i·b_i + e` 꼴의 선형 제약을 분해로 인식한다.
3. 고정 값에서 시작해 다음을 반복한다: 강제 값 전파, 분해의 정수 구간 검사, wrap이 없는 선형 구간 전파.

비트를 열거하지 않으므로 L-03의 `MAX_BOOLEANS` 16 제한이 없다. 모순이 나오면 근거에 분해의 제약 index와 인스턴스 경로를 적고, `excluded_in_context`(`exclusion_method = bit_decomposition_interval`)로 판정한다. 고정 값은 결정 1과 같다(후보 위치 입력과 그에 직접 묶인 입력). TCCT 후보는 지시대로 위치 출력도 고정한다.

**선행 연구.** 이 기법은 새것이 아니다. 제약에서 신호 값 범위를 건전하게 과대근사하는 방법은 CCC-Check(Kolozyan et al., IEEE S&P 2026, ePrint 2025/2120)가 이미 했다. 여기서는 맥락 판정의 한 단계로 썼을 뿐이다.

**결과.**
- **range fixture:** `range_unreachable_intermediate`(8비트, 후보 300)의 배제 방법이 `z3+propagation`에서 `bit_decomposition_interval`로 바뀌었다. 반대 대조 `range_in_bounds`(200)는 여전히 배제되지 않는다.
- **zk-email 9건:** 9/9 배제로, 결과는 L-03과 같다. 근거만 바뀌었다.
  - 이제는 `main.signatureRangeCheck[0]`(6건) 또는 `[4]`(3건)의 121비트 분해(O0 제약 165013, 165501)에서 모순이 나온다.
  - L-03의 근거는 `RSAPad` 안 `modulus` 쪽 `Num2Bits(121)`였다.
  - 두 근거 모두 사람 근거(P2 README 54행: 호출자가 `signature`와 `modulus`를 `Num2Bits(n)`로 먼저 검사)에 들어 있다.
- **A-02 제약 abort 22건: 변화가 없다.**
  - 22건 모두 `LessThan(40)` 안 `Num2Bits(41)` 19행(`lc1 === in`)에서 중단된다. 이 회로에서 `LessThan`은 `IntDiv`, clamp, `ResponseTimeNormalized`, `ResponseTimeMetric`, `MetricNormalized`에 쓰인다.
  - **인스턴스 특정 0/22:** 기준 입력을 모두 고정해도 전파가 `IntDiv`의 hint에서 멈춘다.
    - `out <-- quot`는 제약이 없다. `quot`과 `rem`은 `in[0] === quot*in[1] + rem` 하나로만 묶인다.
    - 그래서 그 하류 `LessThan`에 들어가는 값이 R1CS만으로는 정해지지 않는다. 생성기 오류는 템플릿과 줄만 알려 준다.
  - **배제 증명은 기대하기 어렵다(검증 안 함):** 범위 밖인 것은 정직한 hint가 고른 값이다. R1CS는 hint 값을 다르게 고르는 해를 허용할 수 있다(예: 제약 없는 `IntDiv.out`).
  - 도달시키려면 4단계 주입이 중단된 `LessThan`까지 포함한 모델을 써야 한다. 그러나 위치 입력이 허브 입력(`scaling` 등)에 묶여, 결합 원뿔이 크기 상한에 걸린다(`b_outcome = cone_too_large`).

## 4단계: 모델 재현 실패에 대한 hint 주입

**구현.** z3 모델을 entrypoint 입력에 넣었는데 생성기가 목표를 재현하지 못하는 경우의 처리다.
1. 모델과 실제 witness가 다른 wire 가운데 `<--`로 대입되는 wire를 찾는다.
2. 그 문장을 L-01 hint 생성기 방식으로 다시 쓴다: 해당 템플릿 인스턴스의 입력이 모델 값과 같으면 모델 값을 돌려준다.
3. 다시 쓴 entrypoint는 O0·O1 R1CS와 `.sym`이 원본과 같아야 한다.
4. 주입 생성기로 목표에 도달하면, 그 witness는 원본 R1CS에서 Rust와 snarkjs 두 검사기를 모두 통과해야 판정에 쓰인다.

예외 목록에 `hint_injection: N rewritten statements in M instances outside the site`를 남긴다. 주입 생성기가 중단되면 중단 템플릿·줄·종류를 기록한다.

**결과(L-03의 모델 재현 실패 8건).**

| label | 속성 | 건수 | L-04 |
|---|---|---:|---|
| `DistanceFromScore(40)` | 입력 가정 | 3 | **`assumption_input_reachable`** 3. 문장 1개를 다시 썼고, 위치 밖 인스턴스 5곳에 영향이 있다. 두 검사기 모두 통과했다(Rust 불만족 0, snarkjs correct). |
| `ScoringFunction(40)` | 입력 가정 | 3 | `unknown`(`synthesis_model_not_reproduced`). 주입 생성기가 `Num2Bits_5` 19행(제약)에서 중단됐다. |
| `IntDiv(40)` `…division` | TCCT | 2 | `unknown`(`budget_exhausted`, 원래 사유 `synthesis_model_not_reproduced`). 주입 생성기가 중단됐다: attempt 8은 `Num2Bits_5` 19행, attempt 50은 `IntDiv_7` 29행(`1 === rem_is_valid`). 모두 제약이다. |

- 중단된 5건은 모두 범위 검사 제약에서 멈췄다. 모델은 풀이한 원뿔 안 제약은 만족하지만, 주입 생성기가 계산한 전체 witness는 그 밖의 범위 검사를 어긴다. 어느 인스턴스인지는 생성기 오류로는 특정되지 않는다. 두 번의 실행에서 중단 위치가 같았다.
- `DistanceFromScore` 3건은 사람 정답이 없는 A-02 항목이다. 도달은 입력 가정 위반이 맥락에서 가능하다는 뜻일 뿐, 결함 판정이 아니다.

## 5단계: zk-email 서비스 entrypoint

- **대상:** 같은 리비전은 zkbugs `matterlabs_underconstrained_fpmul_circuit`의 `zkemail/zk-email-verify@fc994976…`이다. 내려받은 것은 전체 monorepo이고, 패키지는 `circuits`, `contracts`, `helpers`, `rust-verifier`다.
- **`packages/circuits`:** `@zk-email/circuits` 6.1.5 라이브러리다. scripts는 `publish`와 `test`(jest)뿐이다. `email-verifier.circom`은 `EmailVerifier` 템플릿만 정의하고 `component main`이 없다.
- **`component main` 12개:** 모두 `packages/circuits/tests/test-circuits/` 아래 테스트 회로다(목록은 evidence JSON).
- **결론:** 이 리비전에는 테스트가 아닌 서비스 entrypoint가 없다. 지시대로 임의 호출자를 만들지 않았고, 의존성(`yarn.lock`)도 설치하지 않았다. 기준 입력 단계까지 가지 않았다.
- **가능한 다음 길(miiz 결정):**
  - (가) 같은 리비전의 `email-verifier-test.circom`처럼 `EmailVerifier`를 감싼 테스트 main을 쓴다. 의존성 설치와 DKIM 예제로 기준 입력을 만들어야 한다.
  - (나) `EmailVerifier`를 실제 main으로 쓰는 하류 앱 저장소를 정해 리비전을 고정한다.

## 보고 표

**후보 값 기준 판정 대 가정 술어 판정.** 가정 술어 판정은 1단계가 불가해서 모두 `not_evaluated`다.

| 자료 | 속성 | 후보 값 기준 판정 | 가정 술어 판정 |
|---|---|---|---|
| Banyan v2 36건 | 입력 가정 | `assumption_input_reachable` 36 | not_evaluated |
| zk-email P2 9건, 테스트 entrypoint `rsa-test` | 입력 가정 | `excluded_in_context` 9 (`bit_decomposition_interval`) | not_evaluated |
| zk-email 서비스 entrypoint | — | 막힘(entrypoint 없음) | 막힘 |
| A-02 입력 가정 18건 | 입력 가정 | reachable 3 · excluded 5 · unknown 10 | not_evaluated |
| A-02 TCCT 13건(class 44) | TCCT | violation 9 · excluded 17 · unknown 18 | 해당 없음 |

**사람 정답과 지시의 기대.**

| 자료 | 사람 정답 | 지시의 기대 | 이번 결과 |
|---|---|---|---|
| Banyan | 실제 결함 | 도달과 결과 위반 | 도달 36/36(L-03과 같음). 결과 위반은 2단계 생략으로 **미평가**. |
| zk-email | 맥락 오탐 | 가정 전체 배제 | 후보 값 기준 배제 9/9. 가정 전체(술어) 배제는 1단계 불가로 **미평가**. 서비스 entrypoint 재판정은 막힘. |

**결과 위반 관측 여부.** 모든 입력 가정 class가 `not_evaluated`다(2단계 생략). TCCT 속성의 `entrypoint_violation`(출력 다름 5, 정직 계산 중단 4)은 L-01 정의의 출력 비교다. 정수 의미 기대값과 비교한 것이 아니다.

**미판정 원인별 before/after(A-02).**

| L-03 원인 | L-03 | L-04 |
|---|---:|---|
| 제약 abort(`Num2Bits` in `LessThan`, 미해결) | 22 (TCCT 16, 입력 가정 6) | 22 모두 `unknown`(`budget_exhausted`, 원래 사유 유지). 배제 0, 도달 0, 인스턴스 특정 0 |
| 모델 재현 실패 | 8 (TCCT 2, 입력 가정 6) | 도달 3(hint 주입), 미판정 5(주입 생성기가 범위 검사 제약에서 중단) |
| (L-03 배제) #27 `IntDiv` 제수 0 abort(`0 === is_non_zero`) | excluded 1 | `unknown`(`budget_exhausted`), 0단계 상한 때문 |
| **A-02 미판정 class 합계** | **30** | **28** |

**후보당 비용 분포(초).** 단계 열은 합계다. 최소·중앙·p90·최대는 요청 하나의 합계다. 관문은 cache 없이 실행했다.

| 자료 | 요청 | 위치 탐색 | 컴파일 | (a) | (b) | witness | 검사 | 합계 | 최소 | 중앙 | p90 | 최대 | (b) 최대 | (b) ≥ 19초 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A-02 31건 (L-03) | 31 | 29.32 | 62.02 | 10.70 | 919.09 | 2.61 | 10.91 | 1034.66 | 0.7 | 5.4 | 51.2 | 168.7 | 160.7 | 14 |
| A-02 31건 (0단계 상한만) | 31 | 31.58 | 73.73 | 8.88 | 283.33 | 3.05 | 12.85 | 413.42 | 0.8 | 6.7 | 29.4 | 31.2 | 20.3 | 14 |
| **A-02 31건 (L-04)** | 31 | 36.28 | 109.45 | 10.72 | 318.55 | 4.37 | 20.97 | 500.33 | 0.9 | 9.7 | 32.7 | 39.5 | 26.1 | 14 |
| Banyan 36건 | 36 | 6.82 | 2.23 | 9.04 | 0.00 | 8.26 | 17.72 | 44.06 | 0.9 | 1.1 | 1.5 | 2.5 | 0.0 | 0 |
| zk-email 9건 (rsa-test) | 9 | 4.87 | 4.07 | 1.40 | 2.51 | 0.00 | 0.00 | 12.85 | 0.9 | 1.0 | 4.7 | 4.7 | 0.3 | 0 |
| fixture 18건 | 18 | 1.07 | 1.05 | 1.36 | 0.11 | 1.56 | 3.98 | 9.13 | 0.0 | 0.6 | 1.0 | 1.3 | 0.1 | 0 |
| 관문 S-05·S-04 (cold) | 2 | 2.82 | 21.15 | 2.96 | 47.59 | 1.00 | 3.91 | 79.43 | 34.8 | 44.6 | 44.6 | 44.6 | 26.5 | 2 |

- **A-02:** 합계가 1034.7초에서 500.3초로, 요청당 최대가 168.7초에서 39.5초로 줄었다.
- **(b) 최대 26.1초:** 20초 예산 밖 항목 때문이다. 결합 원뿔 z3, 비트 분해 전파(위치 31곳 합 28.5초, 위치당 최대 1.9초), hint 주입이 여기에 든다.
- **컴파일 증가:** 0단계 대비 35.7초가 늘었다. 그중 21.3초가 hint 주입 컴파일이다. O0는 8회, 도달한 3건은 O1도 3회 컴파일했다. 나머지는 실행 사이의 변동이다.
- **zk-email:** (b)가 L-03의 14.70초에서 2.51초로 줄었다. z3 가지 탐색 대신 비트 분해 전파가 바로 모순을 찾는다.

## 그 밖의 변경

- **비용 집계 오류 수정:** hint 주입 단계 시간에 안쪽 컴파일과 witness 시간이 한 번 더 들어가 있었다. 바깥 단계에는 나머지만 기록하도록 고쳤다(단위 회귀 `an_enclosing_step_does_not_count_its_nested_steps_twice`). 주입 생성기 중단 위치도 결과에 남기게 한 뒤, 모든 평가를 최종 바이너리로 다시 돌렸다. 첫 실행과 비교한 96개 요청 모두 판정과 사유가 같았다. 위 표는 최종 실행 값이다.
- **템플릿 대응 보강:** 같은 신호 집합을 가진 템플릿이 여럿이면 부모의 인스턴스화 문장(`name = T(`)으로 고른다. 4단계에서 위치 밖 hint 문장을 다시 쓸 템플릿을 정할 때 필요했다(`ScoringFunction`). 단위 회귀는 `instantiation_statements_name_the_template`이다.
- **관문:** S-05(cold cache)는 K1·K2 위반, K3·K4 배제, K5 미판정으로 L-03과 같다. K5 사유만 `budget_exhausted`가 됐다. S-04는 1 배제와 5 미판정으로 같다.
- **fixture 18건:** L-03 대비 바뀐 것은 `range_unreachable_intermediate`의 배제 방법 하나다(`z3+propagation` → `bit_decomposition_interval`). 판정은 모두 같다.

## 막힌 곳

- **위반 조건 대응(1단계):** zkFuzz가 위반 조건을 저장하지 않는다. 다음 zkFuzz 실행에서 조건 문자열을 함께 남기지 않으면 가정 술어 판정과 결과 위반 관측을 할 수 없다.
- **hint 출력에 걸린 제약 abort(22건):** R1CS 전파로는 hint 값이 정해지지 않아 abort 인스턴스를 특정하지 못한다. 배제 증명도 기대하기 어렵다. 도달하려면 허브 입력이 낀 큰 원뿔의 모델이 필요한데, 크기 상한에 걸린다.
- **원뿔 국소 모델(5건):** 모델은 원뿔 안 제약만 보장한다. 주입 생성기가 계산한 전체 witness가 다른 범위 검사를 어기면 중단된다.
- **예산:** 미해결 위치는 거의 모두 20초를 다 쓴다(14/31 후보). 상한이 #27의 배제 증명 1건을 잃게 했다.
- **zk-email 서비스 entrypoint:** 위 5단계와 같다.

## 필수 검사

`cargo fmt` 통과, `cargo clippy --all-targets --all-features -- -D warnings` 통과, `cargo test` **324 통과 · 0 실패 · 22 ignored**.
- lifting 엔진 fixture는 18/18 목표 일치, PENDING 0, 불일치 0이다.
- 새 회귀는 다음과 같다.
  - 0단계: `exclusion_sweep_stops_when_the_candidate_budget_is_spent`
  - 3단계: `decomposition_range_refutes_an_out_of_range_value_and_accepts_an_in_range_one`, `bit_decomposition_range_excludes_out_of_range_intermediate`
  - 4단계: `hint_injection_reaches_a_site_the_honest_hints_never_compute`. 새 fixture `tests/fixtures/lifting_engine/hint_injection`을 쓴다.
  - 비용 집계: `an_enclosing_step_does_not_count_its_nested_steps_twice`
- fixture 형식 문서 [FORMAT.md](../tests/fixtures/lifting/FORMAT.md)에 "Engine changes in L-04" 절을 추가했다.
