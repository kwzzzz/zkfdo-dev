# L-05 결과: 깨진 조건 복원, 가정 술어 판정, 실패 인스턴스 특정, DistanceFromScore 확인, 실행기 조건 문자열 연결

2026-10-03 · 담당 miiz · 기한 2026-10-06. 판정 정의는 [L-01 기준](lifting_feasibility_2026-10-02.md), [L-03 결과](lifting_assumption_results_2026-10-02.md), [L-04 결과](lifting_l04_results_2026-10-03.md)를 따른다. 값 없는 근거(요청·결과 경로와 SHA-256, 엔진 소스·바이너리 해시, 클래스별 판정, 국소화·수리 기록, 비용)는 [evidence JSON](lifting_l05_evidence_2026-10-03.json)에 있다. 원시 값은 ignored `runs/l05-2026-10-03/`에만 있다. **새 zkFuzz 실행은 없다.** 후보·프로젝트별 규칙은 넣지 않았다. 템플릿 이름은 zkFuzz 오라클 정의대로 `LessThan` 하나만 쓴다.

## 요약

| 단계 | 결과 |
|---|---|
| 1. 깨진 조건 복원 | 입력 가정 후보 63건(A-02 18, Banyan 36, zk-email 9) 모두 `LessThan` 정수 비교 조건이 깨졌다. assert 실패와 `condition_not_reconstructed`는 0건이다. zk-email 9건은 모두 로그의 조건 인스턴스가 우리가 찾은 깨진 인스턴스 중 **마지막** 인스턴스와 같다. |
| 2. 가정 술어 판정 | Banyan 36/36 `assumption_violation_reachable`. zk-email 9/9 `assumption_excluded_in_context`(깨진 인스턴스 69개 모두 배제). A-02 18건은 도달 17, 미판정 1이다. 후보 값 기준 판정과 다른 경우는 6건이다(아래). |
| 3. 실패 인스턴스 특정·수리 | 대상 28 클래스 중 27에서 실패 인스턴스를 원본 O0 제약 index로 특정했다. 수리로 판정이 바뀐 클래스는 10개다(입력 가정 도달 8, TCCT 위반 1, TCCT 양립 1). A-02 미판정 클래스는 28 → 18이다. |
| 4. DistanceFromScore 3건 | 3건 모두 `positive`(LessThan)가 깨졌다. 반사실 실행에서 2건은 최상위 `new_score[0]`이 달라지고, 1건(`verified = 0`)은 달라지지 않는다. 수정본(`b8f92bde`)은 3건 모두 거부한다. 원인은 알려진 목록의 위치가 아니다. Clamp 항목 설명에 "같은 패턴"으로만 언급되고, 같은 PR의 별도 commit `79f42ee`가 고쳤다. |
| 5. 실행기 조건 문자열 연결 | zkFuzz는 `--save_output`을 쓰면 조건 문자열을 출력하지 않는다. v1 실행기는 그대로 두고, 해시 고정 v2 래퍼와 보고서 파서를 추가했다(실행 없음). |

## 검수 판단에 대한 정정 두 가지

- **깨진 조건은 처음이 아니라 마지막 실패 원소다.** `emulate_symbolic_trace`(`src/mutator/utils.rs:465-772`)는 실패할 때마다 `failure_pos = i`를 덮어쓰고 멈추지 않는다(`:771`에서 반환). zk-email 로그 9건이 모두 깨진 인스턴스 중 마지막 것(`lt[16]` 또는 `lt[11]`)을 가리키는 것과 맞다.
- **inference의 알려진 결함 항목은 Subtract와 Clamp다.** zkbugs의 inference 항목은 `koukyosyumei_subtract_unconstrained_multiplier`(Subtract)와 `koukyosyumei_clamp_comparator_overflow`(Clamp) 두 개다. 독립된 IntDiv 항목은 없다. IntDiv의 `out <-- quot`는 Subtract 항목 설명에 같은 패턴으로 적혀 있다. Clamp 항목 설명은 DistanceFromScore, IntDiv, MetricNormalized, ScoringFunction, ResponseTimeNormalized에도 같은 비교기 넘침 패턴이 있다고 적는다.

## 1단계: 깨진 조건 복원 (`src/candidate_review/lifting/condition.rs`)

- **방법:** 컴포넌트의 각 인스턴스에서 템플릿 이름을 정한다. 신호 집합, circom의 `main`·익명 컴포넌트 이름, 부모의 인스턴스화 문장을 쓴다. 이름이 `LessThan`인 인스턴스마다 후보 값(없으면 정직한 컴포넌트 witness)으로 zkFuzz 조건을 계산한다: `(out == 1 && in[0] < in[1]) || (out == 0 && in[0] >= in[1])`. 입력은 [0, p)의 정수로 비교한다(`symbolic_value.rs:1000`). 깨진 것이 없으면 정직한 컴포넌트 계산이 중단됐는지(assert) 본다. 둘 다 아니면 `condition_not_reconstructed`다.
- **결과:** A-02 18건 중 17건은 깨진 인스턴스가 1개, #15 Clamp는 2개(`LessThan[0]`, `LessThan[1]`)다. Banyan은 30건이 `check_parent`·`exceed_depth.lt` 2개, 6건이 1개다. zk-email은 3개 후보가 각각 10·6·7개다. 템플릿 미결정 인스턴스는 0이다.
- **zk-email 조건 대조:** 로그 조건 문자열의 인스턴스(`main.lt[16]` 6건, `main.lt[11]` 3건)는 9/9 우리가 찾은 깨진 집합에 있다. 9/9 모두 자연 순서상 마지막 깨진 인스턴스다.

## 2단계: 가정 술어 판정 (`predicate.rs`, 탐색은 `repair.rs`)

술어는 대응하는 entrypoint 인스턴스에서 `out`이 정수 비교 결과와 다르다는 것이다. 인스턴스마다 다음 순서로 판정한다.

1. 클래스가 후보 값으로 도달했으면 같은 생성기·입력의 O0 witness에서 술어를 계산한다. 이 O0 witness는 두 검사기를 통과한 O1 witness와 O1의 모든 wire에서 같아야 한다.
2. **배제:** 인스턴스 주변 O0 제약(깊이 0, 다음 깊이 1)을 고정값 없이 둔다. 모든 witness가 만족하는 범위 사실(비트 분해 구간, boolean 클래스, 상수)만 더해 z3가 unsat을 내면 `assumption_excluded_in_context`다. 제약의 부분집합에 함의된 사실만 더했으므로 unsat은 전체 회로의 해가 없다는 증명이다.
3. **탐색:** 기준 입력에서 시작한다. 인스턴스 영역과 상류 경로의 hint·자유 입력을 z3로 풀고, hint를 주입하고, 중단이 나면 3단계로 수리한다. 찾은 witness는 원본 O1 R1CS에서 두 검사기를 통과하고 O0/O1이 일치해야 한다.

| 자료 | 깨진 조건 | 후보 값 기준 판정 | 가정 술어 판정 | semantic_deviation_observed |
|---|---|---|---|---|
| Banyan 36 | `LessThan` | `assumption_input_reachable` 36 | `assumption_violation_reachable` 36 (66 인스턴스, 모두 후보 witness) | 36 |
| zk-email 9 (rsa-test) | `LessThan` | `excluded_in_context` 9 | `assumption_excluded_in_context` 9 (69 인스턴스 모두 z3+범위 사실, 깊이 0) | 0 |
| A-02 18 | `LessThan` | 도달 11 · 배제 5 · 미판정 2 | 도달 17 · 미판정 1 | 17 |

**후보 값 기준과 다른 경우(모두 A-02):**

| 후보 | 후보 값 기준 | 가정 술어 | 방법 |
|---|---|---|---|
| #5·#15·#25 `Clamp(40)` | 배제(`constant_input_mismatch`: `min`이 상수 0) | 도달 | 탐색 + hint 주입. #15는 `LessThan[0]`만 도달하고 `LessThan[1]`은 미판정이다. |
| #6·#16 `CalculatedScoreFraction(40)` | 배제(`constant_input_mismatch`) | 도달 | 탐색 + hint 주입 |
| #27 `ResponseTimeNormalized(40)` | 미판정(`budget_exhausted`, 3단계 수리 중 IntDiv 제수 0에서 막힘) | 도달 | 탐색 + hint 주입 |

#26 `CalculatedScoreFraction(40)`는 두 기준 모두 미판정이다(수리 `cycle`, 탐색 `no_progress`).

**사람 정답과의 대조:** Banyan(실제 결함)은 기대대로 의미 위반 도달 36/36이다. zk-email(맥락 오탐)은 기대대로 가정 전체 배제 9/9이고, 근거는 호출자의 `Num2Bits(121)` 범위 검사(signature·modulus)다. 두 자료 모두 개발 자료이고 사람 정답을 이미 알고 있었다.

**해석상 주의:** A-02의 도달 witness는 대부분 `IntDiv` 31행 `out <-- quot`(제약 없는 hint)에 값을 주입해 얻었다(아래 3단계 표). 원본 R1CS로는 유효한 witness다. 그러나 알려진 IntDiv 결함과 독립된 근거는 아니다. 프로젝트 결함이나 원인 귀속 판정이 아니다.

## 3단계: 실패 인스턴스 특정과 수리 (`repair.rs`)

- **진단용 사본:** 생성기가 중단된 `===`·`assert` 문장을 줄 번호를 유지한 채 공백으로 지운다. 다시 중단되면 반복한다(최대 6). 사본 witness는 `.sym`으로 신호가 원본 O0와 줄마다 같은지 확인한 뒤 원본 O0 R1CS에 그대로 대입해 계산한다. 만족하지 않는 제약 index의 공통 인스턴스가 실패 인스턴스다. 사본은 위치를 찾는 데만 쓴다.
- **작은 원뿔:** 실패 인스턴스의 제약, 그 입력을 대입하는 연결, 경계에서 가장 가까운 `<--` hint까지의 상류 경로를 하나의 원뿔로 잡는다. 상류 판단은 circom 신호 의미(입력은 부모만 대입한다)로 한다. 원뿔 밖 wire는 현재 값으로 고정한다. hint 잎은 그 값을 쓰는 제약(예: boolean 검사)으로 닫는다. z3가 낸 hint 값을 L-04 방식으로 주입하고(인스턴스 입력을 키로 씀) 반복한다(최대 6회, 같은 상태가 다시 나오면 `cycle`).
- **배제에 쓰지 않음:** 수리 원뿔의 unsat은 후보가 정하지 않은 값을 고정한 결과다. 원래 제약과 동치인 인코딩이 아니므로 배제로 세지 않는다.

**실패 인스턴스 특정:** 대상 28 클래스(L-04의 제약 abort 22 + #27 1 + hint 주입 중단 5) 중 **27**에서 특정했다. 대표 실패 인스턴스 패턴은 다음과 같다.
- `calculated_score_fraction_comp[*].clamp.LessThan[*].toBits`(O0 제약 11835 등): 거의 모든 사례
- `distance_from_score_fn[*].positive.toBits`(59444)
- `response_time_reward_metric_fn[*].int_div` 계열(`IntDiv` 29행 `1 === rem_is_valid`)
- `int_div[*]`·`int_div_2[*]`·`int_div_3[*]`의 `LessThan_28_512.toBits`

특정하지 못한 1건은 #27의 기준 입력이다. 이 입력은 `0 === is_non_zero`(IntDiv 제수 0 검사)에서 중단된다. 그 검사를 지우면 다음 문장 `in[0] \ in[1]`이 wasm `RuntimeError: divide by zero`로 멈추고, circom은 템플릿·줄을 남기지 않는다. 따라서 사본을 더 진행할 수 없다(circom 제약). #22 `division`의 주입 탐색도 같은 이유로 멈췄다.

**미판정 원인별 before/after (A-02):**

| L-04 원인 | L-04 | L-05 |
|---|---:|---|
| 제약 abort(입력 가정 6 + #27) | 7 | 도달 5(#7·#10·#17·#20·#30), 미판정 2(#26 `cycle`, #27 제수 0) |
| 제약 abort(TCCT) | 16 | 위반 1(#2 `int_div_3[0]`, `honest_aborted`), 양립 1(#22 `int_div_3[0]`, `outputs_equal`), 미판정 14 |
| 모델 재현 실패(입력 가정 `ScoringFunction`) | 3 | 도달 3(#9·#19·#29, 주입 생성기 중단을 특정·수리) |
| 모델 재현 실패(TCCT `IntDiv` `division`) | 2 | 미판정 2(#2 `iteration_limit`, #22 제수 0) |
| **A-02 미판정 class 합계** | **28** | **18** |

- **TCCT 위반 1건의 해석:** 비교 기준은 같은 주입에서 후보의 위치 hint만 뺀 생성기이고, 이 생성기가 중단됐다. L-01 정의의 `honest_aborted`이지만, 수리 주입이 들어간 정직 계산이라는 점을 함께 적는다.
- **TCCT 미판정 14건:** 직접 입력이 허브(`scaling` 등)에 묶여 있다. 중단 수리와 목표 값 수리가 서로를 되돌려 `no_progress`·`cycle`·`iteration_limit`로 끝났다. 둘을 한 번에 푸는 결합 질의는 z3가 `unknown`이다(10초, 별도 확인 120초에서도 `unknown`).
- **다시 쓴 문장:** hint 주입으로 도달한 A-02 13 클래스(L-04와 같은 DistanceFromScore 3, 이번에 바뀐 10)는 `IntDiv` 31행 `out`(`out <-- quot`)과 `Num2Bits` 12행 `out`(비트 hint)만 다시 썼다. DistanceFromScore 3건은 `IntDiv` 31행만 썼다.

**`.sym` 확인 규칙 변경:** circom은 익명 컴포넌트를 `Template_<줄>_<파일 바이트 위치>`로 부른다. 같은 파일 앞쪽 문장을 길게 다시 쓰면 이름만 바뀐다. L-04에서는 이 경우가 없었다. 이제 다시 쓴 생성기는 R1CS가 바이트 단위로 같고, `.sym`은 줄마다 label·wire·component가 같으며 이름은 익명 위치의 일관된 1:1 변경만 허용한다(`hinted_sym_anonymous_renames`). 변경 전 규칙에서 실패한 L-04 요청은 0건이었다.

## 4단계: A-02 DistanceFromScore 도달 3건

| 후보 | 깨진 조건 | 반사실(해당 인스턴스만 정수 비교로) | 원래 생성기(같은 입력) | 수정본(`b8f92bde`)의 정직 계산 |
|---|---|---|---|---|
| #3 attempt 9 | `positive`: out 0, 정수 비교 참 | `new_score[0]` 1개 다름 | 정상 종료, 출력 256개가 도달 witness와 다름 | 중단(`Num2Bits` 19행) |
| #13 attempt 30 | `positive`: out 1, 정수 비교 거짓 | `new_score[0]` 1개 다름 | 같음 | 같음 |
| #23 attempt 51 | `positive`: out 1, 정수 비교 거짓 | 다른 출력 없음(`verified[0] = 0`이라 `Where`가 `isPos`를 쓰지 않는 쪽을 고름) | 같음 | 같음 |

- **반사실 실행:** 도달한 생성기의 사본에서 `LessThan`의 `out`만 바꾼다. 그 인스턴스의 입력값일 때만 정수 비교값을 돌려주는 진단용 사본이다(R1CS가 달라 영향 측정에만 쓴다). 같은 입력으로 계산해 공개 출력 1,024개를 비교했다.
- **원래 생성기와의 차이 256개:** 도달 witness가 `int_div[*].out`에 주입한 값 때문이다. 기준 입력의 256개 배치가 같아서 주입 키가 모두 맞는다. LessThan 하나의 효과와는 다르다.
- **원인 확인(소스·수정 이력):**
  - 수정 PR #2(merge `b8f92bde`)에는 `79f42ee fix DistanceFromScore` commit이 따로 있다. 이 commit은 `previous_score`·`maximum_score`를 `LessThan` 앞에서 `Num2Bits(b)`로 검사한다.
  - 수정본은 세 후보의 입력을 모두 거부한다. 같은 입력에서 취약본의 정직 계산은 정상 종료한다.
  - 도달 witness의 `maximum_score` 값은 제약 없는 `IntDiv.out`(같은 PR의 `9221e8d fix IntDiv`가 고침)에 주입해 얻었다.
- **판단:** DistanceFromScore는 zkbugs 항목의 위치(Subtract, Clamp)가 아니다. Clamp 항목 설명에 같은 패턴으로 이름만 나온다. 지시대로 **알려진 목록에 없는 후보**로만 표시하고 프로젝트 결함 판정은 하지 않는다.

## 5단계: 실행기 조건 문자열 연결 (실행 없음)

- **원인:** `--save_output`이면 zkFuzz는 JSON만 쓴다(`main.rs:396-433`). 이때 `2_violated_condition`에는 `pos`만 있다(`utils.rs:75-76`). 조건 문자열이 든 사람용 보고서(`utils.rs:51`, `main.rs:435`)는 출력하지 않는다. A-02 실행기(v1)는 stdout·stderr를 항상 저장했지만 `--save_output`을 요구해 문자열이 남지 않았다.
- **`scripts/zkfuzz_report.py`:** stderr 보고서에서 유형, 조건 문자열, 할당(소수로 환원)을 읽는다. 엔진이 읽는 zkFuzz 키 구조(`7_assignment`)의 후보 JSON을 쓰고, 조건 문자열과 로그 경로·SHA-256 링크를 함께 남긴다. 기존 P2 zk-email 로그로 확인했다: L-02 변환 후보와 할당이 같다.
- **`scripts/run_policy_a_engine_v2.py`:** v1(A-02 SCOPE가 SHA-256을 고정, 변경 없음)을 불러 쓴다. `"zkfuzz_output": "stderr_report"` 모드에서는 `--save_output`을 금지한다. 각 attempt 뒤 stderr 보고서를 작업 공간의 `zkfdo_report_counterexample.json`으로 바꿔 v1 후보 보존 경로로 넘긴다. 값 없는 `report_link.json`도 남긴다. 기본 모드는 v1과 같고 "문자열 없음"을 기록한다.
- **회귀:** `tests/zkfuzz_report_test.py` 7개(합성 보고서 2종, 무보고서·깨진 보고서, 실제 로그 대조, v2 연결·save_output 모드·모드 검증).

## 비용 (초)

요청 하나의 합계. A-02 외 자료는 실행 중 A-02 사례 하나의 재실행이 겹쳐 CPU 경합이 있었다.

| 자료 | 요청 | 합계 | 최소 | 중앙 | p90 | 최대 | 주요 단계 |
|---|---:|---:|---:|---:|---:|---:|---|
| A-02 (L-04) | 31 | 500.3 | 0.9 | 9.7 | 32.7 | 39.5 | (b) 318.6 · compile 109.5 |
| **A-02 (L-05)** | 31 | 1255.5 | 4.1 | 22.5 | 66.0 | 177.0 | compile 584.9 · (b) 371.7 · repair 115.5 · predicate 50.3 |
| Banyan | 36 | 96.6 | 2.0 | 2.6 | 3.1 | 4.0 | predicate 40.3 |
| zk-email (rsa-test) | 9 | 20.2 | 1.6 | 1.7 | 6.0 | 6.0 | predicate 5.7 |
| fixture | 25 | 46.8 | 0.0 | 1.1 | 2.0 | 25.5 | |
| 관문 S-05·S-04 (cold) | 2 | 281.7 | 76.8 | 204.9 | 204.9 | 204.9 | compile 155.4 |

- **A-02 증가분:** 대부분 진단 사본과 주입 생성기의 컴파일이다. 사본 1회는 inference entrypoint O0 컴파일 약 3초다. 1단계는 요청당 0.01초 미만이다. zk-email 배제는 인스턴스당 0.1초 안팎이다.
- **관문:** S-05는 L-04와 같다(K1·K2 위반, K3·K4 배제, K5 미판정). S-04는 `int_div_3[0]`이 미판정에서 위반(`honest_aborted`, 수리)으로 바뀌었다.

## 막힌 곳

- **IntDiv 제수 0:** 검사를 지운 사본은 wasm 0 나눗셈으로 멈추고 circom이 위치를 남기지 않는다. 2 클래스에서 특정과 수리가 멈췄다.
- **허브 입력 TCCT:** 중단 수리와 목표 수리가 수렴하지 않는다(14 클래스). 결합 질의는 z3 `unknown`이다.
- **도달 witness의 의존:** A-02 도달은 알려진 `IntDiv.out` 무제약 hint에 기대고 있다. 이것을 넘어서는 근거(예: 수정된 IntDiv 위에서의 재판정)는 이번 범위가 아니다.
- **zk-email 서비스 entrypoint:** 지시대로 이번에 하지 않았다(C-03 이후).

## 필수 검사

`cargo fmt` 통과, `cargo clippy --all-targets --all-features -- -D warnings` 통과, `cargo test` **333 통과 · 0 실패 · 22 ignored**(L-04의 324에 새 회귀 9개 추가). 로그는 `runs/l05-2026-10-03/cargo_test.log`에 있다.
- **Python:**
  - `tests/zkfuzz_report_test.py` 7 통과
  - `tests/lifting_fixture_test.py`·`tests/lifting_fixture_followup_test.py` 통과
  - `tests/policy_a_engine_test.py`(v1) 7 통과. 평가 실행과 겹친 실행에서 1회 시간 의존 실패가 있었고, 부하가 없을 때 다시 돌려 통과했다. v1 파일은 바뀌지 않았다(SHA-256 `c408cc…`).
- **fixture:** 기존 21개 요청의 판정은 L-04와 같다. 새 fixture 4개는 설계한 판정과 같다.

## 새 회귀

- **엔진 단위:**
  - `condition` 2개(정수 비교 조건, 자연 순서)
  - `source` 1개(검사 문장 위치)
  - `repair` 2개(경로 분할·공백 치환, `.sym` 익명 위치 동치)
- **엔진 통합(`tests/lifting_engine_regression_test.rs`):** 새 fixture 4종으로 4개 테스트를 추가했다. fixture 후보는 `make_candidates.py`가 정직한 컴포넌트 witness로 만든다.
  - `caller_range_checks_exclude_the_broken_comparison`
  - `unchecked_inputs_reach_the_broken_comparison`
  - `predicate_search_reaches_a_violation_the_candidate_values_cannot`
  - `an_aborting_range_check_is_located_and_repaired`
- **Python:** `tests/zkfuzz_report_test.py` 7개.
- **문서:** [FORMAT.md](../tests/fixtures/lifting/FORMAT.md)에 "Engine changes in L-05" 절을 추가했다.
