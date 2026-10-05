# L-03 결과: 입력 가정 위반 후보의 맥락 도달성

2026-10-02 · 담당 miiz · 기한 2026-10-09. 판정 정의는 [L-01 기준](lifting_feasibility_2026-10-02.md)과 L-03 지시를 따른다. 실행 근거(요청·결과 경로, SHA-256, 엔진 소스·도구·구성 입력 해시, 사람 정답 표시)는 기계가 쓴 [evidence JSON](lifting_assumption_evidence_2026-10-02.json)에 있다. 원시 값은 ignored `runs/l03-assumption-2026-10-02/`에만 있다. 새 zkFuzz 실행은 없다.

## 결정 반영

| 결정 | 반영 |
|---|---|
| 1. 닫힌 원뿔 UNSAT 승격 | 고정 값이 후보의 위치 입력값과 그에 직접 묶인 entrypoint 입력뿐인 원뿔에서 z3가 unsat을 반환할 때만 `excluded_in_context`(`closed_cone_unsat`)로 올린다. z3 unknown·timeout, 그리고 값싼 전파만으로 반증된 경우는 `unknown`이다. 근거에는 다음을 남긴다: O0 기준(`exclusion_basis = o0_closed_cone`), 제약 index, 고정 wire 이름, 풀이 방법(`z3` 또는 `z3+propagation`). |
| 1의 구현 세부 | 차수 32 초과 허브 wire는 기준값에 고정하지 않고 자유 변수로 두되 확장하지 않는다(완화이므로 unsat이 그대로 증명이다). 해집합이 정확히 {0, 1}인 단일 미지수 제약에는 같은 해의 범위 단언을 덧붙여 z3를 돕는다. 큰 결합 원뿔이 결론을 못 내면, 위치 입력마다 제약 가지별 작은 닫힌 원뿔을 시도한다(가지당 5초, 위치당 40초). |
| 1의 fixture | `range_unreachable_intermediate`의 pending 블록을 지웠다. 이제 `sites` 기대값(`excluded_in_context`)으로 통과하며 방법은 `z3+propagation`이다. 반대 대조 회귀 `range_in_bounds`(같은 회로, 범위 안 값 200)를 추가했다. 결과는 `unknown`(z3 시간 초과)이고 배제되지 않는다. |
| 2. Decoder | `Multiplexer(1, 4)` 호출자 결과(`excluded_in_context`)는 메커니즘 시연으로만 기록한다. 프로젝트 근거로 세지 않는다. |

## 두 번째 속성의 구현

- 컴포넌트에서 정직한 계산과 차이가 0인 후보(`component_classification = not_tcct_deviation`)도 이제 분리로 끝나지 않는다. `property = input_assumption`으로 위치 탐색, 직접 바인딩, 역산 (a)/(b), 전체 witness 검증을 거친다.
- 판정은 출력 비교 없이 한다.
  - 정직한 witness가 원본 R1CS를 Rust·snarkjs 두 방법 모두로 만족하고, 원본에 wire가 남은 위치 신호가 후보 값과 같으면 `assumption_input_reachable`이다. 이것은 프로젝트 결함 판정이 아니다.
  - 증명이 있으면 `excluded_in_context`, 나머지는 `unknown` 또는 `preparation_failure`다.
- 두 속성은 결과 JSON의 `property` 필드로 갈리며, 아래 표에서도 따로 센다.
- **abort 분류:** 합성 출발점의 정직한 계산이 중단되면 생성기 오류의 템플릿·줄을 소스에서 찾는다.
  - `===` 줄(R1CS 제약)이면 그 주변을 닫힌 원뿔로 다시 푼다. 증명이 없으면 `abort_on_constraint_unresolved`다.
  - `assert`만 있는 줄이면 `abort_on_unconstrained_check`(`unknown`)다.
  - 같은 이름의 템플릿이 여럿이면 모든 정의가 같은 종류일 때만 분류한다.

## 사람 정답과의 대조

| 자료 | 사람 정답 | 기대 | 엔진 결과 | 일치 | 근거 |
|---|---|---|---|---|---|
| Banyan v2 `Blake3NovaTreePath_CheckDepth` 36건 ([controlled-v2 REPORT](../reports/controlled-v2-execution-2026-09-20/REPORT.md) 9행) | 실제 결함 | `assumption_input_reachable` | 36/36 `assumption_input_reachable` | **일치** | production entrypoint `Blake3Nova(0)`(circomkit 생성 main)에서 위치 입력 `depth`·`leaf_depth`가 public 입력에 직접 묶인다. 후보 값을 넣은 정직한 witness가 두 검사기로 원본 제약을 만족하고, 위치 신호 25개가 후보 값과 같다. 기준 입력은 L-02에서 후보를 열기 전에 고정한 것(`7c48527c…`)이다. |
| zk-email P2 `BigLessThan(121,17)` 9건(로그 복원, 서로 다른 후보 3) ([P2 README](../reports/dev-rq1-pilot-2026-09-29/README.md) 54행) | 맥락 오탐 | `excluded_in_context` | 9/9 `excluded_in_context` | **일치** | 위치 입력이 `signature[i]`·`modulus[i]`에 직접 묶인다. RSA 기준 입력(`rsa.test.ts`의 1024비트 예제를 121비트 17청크로 분할, `866c61aa…`)에 후보 값을 넣으면 정직한 계산이 `Num2Bits` 38행 `lc1 === in`(제약)에서 중단된다. 이어진 가지 원뿔에서 z3가 unsat을 냈다: 후보 3종이 각각 `modulus[1]`, `modulus[0]`, `modulus[3]` 한 limb만 고정했고, RSAPad 안의 `Num2Bits(121)`가 근거다. 사람 근거(호출자의 Num2Bits 범위 검사)와 같은 메커니즘이다. 사람 근거가 함께 든 `signature` 쪽 검사는 이번 증명에 쓰이지 않았다. |

## A-02 31건: 두 속성

| 속성 | 후보 | class | 위반/도달 | excluded | unknown |
|---|---:|---:|---:|---:|---:|
| TCCT (`tcct_deviation`) | 13 | 44 | `entrypoint_violation` 9 | 17 | 18 |
| 입력 가정 (`not_tcct_deviation`) | 18 | 18 | `assumption_input_reachable` 0 | 6 | 12 |

- **TCCT 속성:** 분포는 L-02와 같다. 미판정 사유가 바뀌었다.
  - 이전의 `synthesis_reference_aborted` 16건이 이번에는 모두 제약 abort로 분류됐다(`abort_on_constraint_unresolved` 16). 원뿔은 크기 상한에 걸렸다.
  - `synthesis_model_not_reproduced`는 2건이다.
- **입력 가정 속성(label별, 각 3건):**

| label | 결과 |
|---|---|
| `Clamp(40)` | excluded 3 (`clamp.min` 상수 불일치, O0 기준) |
| `CalculatedScoreFraction(40)` | excluded 2 (상수), unknown 1 (제약 abort, 미해결) |
| `ResponseTimeNormalized(40)` | excluded 1 (닫힌 원뿔: 후보의 `scaling` 값 하나로 `scaling`을 제수로 쓰는 다른 `IntDiv`가 성립하지 않는다), unknown 2 (제약 abort) |
| `ResponseTimeMetric(40)` | unknown 3 (제약 abort) |
| `DistanceFromScore(40)` | unknown 3 (모델 재현 실패) |
| `ScoringFunction(40)` | unknown 3 (모델 재현 실패) |

- **P2 README의 사전 분류와 다르다.** README는 이 계열을 "실제 회로에서도 일어날 수 있는 것으로 보임(경로별 정밀 검토 전)"이라고 적었다(검증된 정답 아님). 엔진은 도달 0, 배제 6, 미판정 12를 냈다.
  - `CalculatedScoreFraction` 2건은 위치 입력 `proof_size_reward_metric`이 entrypoint에서 상수 0에 묶여, 후보 값으로는 그 위치에 갈 수 없다.
  - README의 판단은 entrypoint 입력에 범위 검사가 없다는 점만 봤다. 상수 바인딩은 다루지 않았다.
  - 엔진을 이 사전 분류에 맞추지 않았다.

**abort 분류 건수.**

| | 제약(`===`) | assert만 | 미분류 |
|---|---:|---:|---:|
| A-02 출발점 abort | 23 (TCCT 16, 입력 가정 7) | 0 | 0 |
| A-02 모델 입력 abort | 2 | 0 | 0 |
| zk-email 출발점 abort | 9 | 0 | 0 |

- `abort_on_unconstrained_check`는 0건이다.
- A-02 제약 abort는 모두 `Num2Bits`의 `lc === in`(`LessThan` 내부)이다. 그중 1건은 배제로 해결됐고 나머지는 미해결이다.

## 단계별 비용(초)

| 자료 | 위치 탐색 | 컴파일 | (a) | (b) | witness | 검사 | 합계 | 요청당 최대 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A-02 31건 | 29.32 | 62.02 | 10.70 | **919.09** | 2.61 | 10.91 | 1034.66 | 168.7 |
| Banyan 36건 | 7.28 | 1.93 | 9.75 | 0 | 8.95 | 20.85 | 48.75 | 2.0 |
| zk-email 9건 | 3.62 | 4.08 | 0.96 | 14.70 | 0 | 0 | 23.35 | 6.0 |
| fixture 18건 | 0.92 | 0.79 | 0.91 | 0.42 | 1.24 | 2.70 | 6.98 | 0.9 |

**중단 기준 해당.**
- A-02에서 (b)가 후보당 60초를 넘은 후보가 3/31이다(`IntDiv(40)` 3건, 160초 안팎). 40초 근처에서 끝난 후보도 11건이다.
- 원인은 미판정 위치마다 가지 원뿔 탐색이 예산 40초를 다 쓰는 데 있다. 결합 원뿔 z3는 8회 합 0.4초뿐이고, 탐색 31회가 917초다. 미판정 위치의 비용은 906초다.
- 지시에 따라 탐색 예산을 다시 맞추지 않고 보고한다. 후보당 (b) 총예산 상한을 두는 방안이 있다. 판정 수는 바뀌지 않을 가능성이 크지만 확인은 하지 않았다.

## 막힌 곳

- **허브 입력이 고정된 위치:** 위치 입력이 `scaling` 같은 허브 입력에 직접 묶이면, 결합 원뿔이 즉시 크기 상한을 넘는다. 가지 원뿔 수백 개도 시간 안에 결론을 내지 못한다.
- **하류 abort:** 중단이 위치 출력의 하류에서 일어나는 경우, 고정 값을 위치 입력으로만 제한한 결정 1의 규칙 아래에서는 위치 내부를 지나는 하류 제약이 원뿔에 들어갈 수 없다. 제약 abort가 미해결로 남는 주요 원인이다.
- **abort 위치:** 생성기 오류는 템플릿·줄만 알려 준다. 어느 인스턴스(R1CS 제약 index)인지는 알 수 없어, 그 제약만 골라 원뿔에 넣지 못하고 가지 탐색에 의존한다.
- **z3 비선형 mod p:** z3는 mod p 제곱근 같은 비선형 역산을 하지 못한다. 반대 대조의 196(= 14²)도 실제로는 도달 가능하지만 `unknown`이다.

## 필수 검사

`cargo fmt` 통과, `cargo clippy --all-targets --all-features -- -D warnings` 통과, `cargo test` **318 통과 · 0 실패 · 22 ignored**.
- lifting 엔진 fixture는 18/18 목표 일치, PENDING 0이다.
- 새 회귀: `range_in_bounds` 반대 대조, abort 분류 단위 테스트.
- LF-02 fixture 작업의 후속 Python 검사는 지운 pending 블록에 맞게 한 곳을 고쳤다. 대조군 기대값은 `expected.control-v3.json`으로 추가했고 v2는 보존한다.
