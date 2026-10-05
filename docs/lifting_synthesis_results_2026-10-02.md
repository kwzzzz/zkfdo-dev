# L-02 결과: 역방향 입력 합성과 L-01 보완

2026-10-02 · 담당 miiz · 기한 2026-10-12. 판정 정의는 [L-01 기준](lifting_feasibility_2026-10-02.md)을 그대로 쓴다. 실행 근거(요청·결과 경로, SHA-256, 엔진 소스·도구 해시, 구성 입력 해시)는 기계가 쓴 [evidence JSON](lifting_synthesis_evidence_2026-10-02.json)에 있다. 원시 값은 ignored `runs/l02-synthesis-2026-10-02/`에만 있다.

**구현.** `src/candidate_review/lifting/`에 다음을 추가했다.
- `synth.rs`: (a) 구체 역전파, (b) 시간 상한 z3 국소 풀이.
- 보완 3건과 (c) 재검증 연결.
- z3 5.1.0(Homebrew)은 유한체 이론이 없어서, `(A·B − C) mod p = 0`·변수 ∈ [0, p) 정수 인코딩을 쓴다.

**합성 절차.**
- **(a) 구체 역전파:** 목표 wire에서 O0 제약 그래프를 따라 자유 public 입력까지 최단 경로를 최대 6개 찾는다. 경로 밖 wire는 현재 정직한 값에 고정하고, 각 제약을 다음 wire에 대한 선형식으로 푼다. 시도는 최대 12회, 3라운드다.
- **(b) 국소 풀이:** 목표 주변 깊이 6, 미지수 300·제약 600 이하의 원뿔을 푼다. 값싼 boolean·선형 반증을 먼저 하고, 그다음 z3를 20초 상한으로 부른다.
- **(c) 재검증:** 제안된 입력은 O0 정직 계산이 위치 입력을 재현해야 통과한다. 정직 계산이 중단되면 다시 쓴 생성기로 확인한다. 통과한 입력은 L-01 전체 경로(전체 witness, 두 검사기, 정직한 계산 비교)를 다시 거친다. 합성 실패는 `unknown`이다.

## L-01 보완 3건

| 항목 | 결과 |
|---|---|
| 1. 반증 범위 | `excluded_in_context`는 위치 입력이 모두 entrypoint 입력이나 상수에 직접 묶일 때만 낸다. 그 밖의 반증 성공은 `unknown`·`reference_input_refuted`다. 판정 함수 단위 회귀를 추가했다. 이번 평가에서 `reference_input_refuted`는 0건이다. 합성 입력은 O0 정직 계산을 통과한 입력이므로 같은 public 입력의 반증이 성립할 수 없어, 이 경로는 사실상 방어용이다. |
| 1의 부수 수정 | 반증이 public 입력만 고정하고 private 입력을 빠뜨리던 L-01 결함을 고쳤다. 또 후보가 정한 위치 신호 값도 고정한다. 원본(O1)에서 그 신호가 사라졌으면 O0 R1CS로 다시 시도하고 근거에 기준을 적는다. 회귀 `tests/lifting_engine_regression_test.rs`를 추가했다. |
| 2. O0 상수 근거 | 상수 배제는 원본(O1) 등식 색인으로 교차 확인한다. A-02의 상수 배제 17건은 모두 O1에서 해당 신호가 상수로 대체돼 wire가 없다. 그래서 교차 확인이 불가능하며, 근거 문자열과 `exclusion_basis = o0_only_signal_eliminated_in_o1`에 O0 기준임을 적었다. O1에서 확인된 건은 0이다. |
| 3. 비이탈 후보 분리 | 정직한 컴포넌트 계산과 차이가 0인 후보는 승격 전에 `not_tcct_deviation`으로 끝나며 판정 분포에서 빠진다. A-02 18/31, Banyan 36/36, zk-email 9/9(서로 다른 후보 3), fixture 대조군 8건이 여기에 해당한다. 모두 zkFuzz `UnexpectedInput` 라벨이었지만, 분류는 라벨이 아니라 엔진의 이탈 검사로 했다. |

## A-02 31건: L-01 대비

class 단위다. 비이탈 18건은 L-02에서 분포 밖으로 빠졌다(L-01에서 excluded 5·unknown 13이었다).

| | 후보(분포 안) | class | entrypoint_violation | excluded_in_context | unknown | 미판정률 |
|---|---:|---:|---:|---:|---:|---:|
| L-01 (31건 전체) | 31 | 62 | 8 | 22 | 32 | 51.6% |
| L-01 (TCCT 이탈 13건만) | 13 | 44 | 8 | 17 | 19 | 43.2% |
| **L-02** | 13 | 44 | **9** | 17 | **18** | **40.9%** |

- **변화 1건:** attempt 29 `IntDiv(40)`의 `response_time_normalized_fn[*].division`.
  - (a)가 `maximum_response_time[0]`, `response_time[0]`을 합성했고, 정직한 O0 계산이 두 위치 입력을 재현했다.
  - L-01 경로에서 Rust·snarkjs 모두 만족했고 출력 1개가 달랐다(`entrypoint_violation`). hint가 발동한 위치는 1곳이다.
- **abort형 위반 4건:** attempt 43·64의 `Subtract()` K1·K2는 L-01과 같다.
- 원인 귀속이 아니며, 새 고유 원인으로 세지 않는다.

**미판정 사유 분포.**

| 사유 | L-01 | L-02 |
|---|---:|---:|
| `input_requires_inversion` | 19 | 0 |
| `synthesis_reference_aborted` | — | 16 |
| `synthesis_model_not_reproduced` | — | 2 |

- `synthesis_reference_aborted` 16건(`Subtract` K5 4, `IntDiv` 12): 후보의 큰 필드 값이 공유 public 입력(`scaling`)에 직접 들어간다. 그 결과 정직한 계산과 다시 쓴 생성기가 모두 위치와 무관한 `LessThan` 범위 검사에서 중단돼 출발점이 없다.
- `synthesis_model_not_reproduced` 2건(`division` 2): (a)의 제안 입력은 범위 검사로 중단됐다. (b)는 허브를 고정한 17변수 원뿔에서 모델을 찾았지만, 정직 계산이 목표값을 재현하지 않았다.

**단계별 비용(초, 31건 합계, entrypoint 컴파일 cache 공유).**

| 위치 탐색 | 컴파일 | 합성 (a) | 합성 (b) | witness | 검사 | 합계 |
|---:|---:|---:|---:|---:|---:|---:|
| 18.18 | 70.02 | 6.63 | 0.83 | 4.52 | 18.25 | 118.44 |

- 미판정 위치에 쓴 비용은 18.32초다. 내역은 컴파일 11.96(합성 대비 다시 쓴 O0 컴파일), (a) 5.53, (b) 0.83이다.
- 요청당 최대 16.2초(cache 없는 S-05는 16.5초), 중앙값 0.13초다.
- (a)는 후보당 최대 1.95초, (b)는 최대 0.49초다. 60초 중단 기준에 해당한 후보는 0건이다.
- L-01 대비 컴파일이 늘어난 이유는, 중간값 입력이 있는 후보마다 다시 쓴 O0 생성기를 미리 컴파일하기 때문이다.

## 두 번째 개발 자료

사용자 지시에 따라 후보 셋을 모두 적용했다. 새 zkFuzz 실행은 없다.

| 자료 | 후보 | 결과 |
|---|---|---|
| Banyan v2 (`Blake3NovaTreePath_CheckDepth`, production `Blake3Nova(0)`, O0 70,139 wire) | 보존 JSON 36 | 36/36 `not_tcct_deviation`. 기준 입력은 후보를 열기 전에 만들어 정직 계산·snarkjs로 확인했다(`7c48527c…`). 승격 대상이 없어 entrypoint 단계는 실행되지 않았다 |
| zk-email P2 (`BigLessThan(121,17)`, test harness `rsa-test`) | 로그에서 복원한 9(서로 다름 3). 변환기는 zkFuzz 텍스트 형식 기준이다 | 3/3 `not_tcct_deviation`. entrypoint 단계에 가지 않아 RSA 기준 입력은 만들지 않았다(placeholder로 실행했고 판정에 쓰이지 않음) |
| Decoder v3 (`Decoder(4)`) | 보존 JSON 1 (NonDeterministic) | 프로젝트 entrypoint가 없다. circomlib의 유일한 호출자 `Multiplexer(1, 4)`를 `runs/` 사본에 entry로 두었다(라이브러리 호출자 맥락). **`excluded_in_context`**: 이탈 생성이 `dec.success === 1`에서 중단됐다. 모든 입력과 후보 위치 신호 4개를 고정한 원본 제약 9개에 해가 없다. 0.32초 |

**해석.** 두 번째 프로젝트 자료에는 TCCT 이탈 후보가 사실상 없다. 그래서 같은 코드가 다른 프로젝트에서 동작한다는 근거는 다음에 한정된다.
- 컴포넌트 단계: 컴파일, 이탈 검사.
- 라이브러리 호출자 맥락 1건.

entrypoint 합성의 일반성은 이번 자료로 보이지 않았다.

## fixture

fixture 작업(LF-01/LF-02) 요청 18건 중 17건이 목표와 일치한다.

- `linear_inversion`·`bitdecomp_inversion`: (a) 합성 후 `entrypoint_violation`.
- `unknown`(ToyHash): (b)가 역상을 찾아 재검증 후 `entrypoint_violation`이 됐다. LF-02 fixture 작업에서 `expected.engine-v2.json`으로 갱신했다.
- 대조군 8건: `not_tcct_deviation`(`expected.control-v2.json`).
- 준비 실패 3건: 일치.
- **남은 1건은 PENDING**이다. `range_unreachable_intermediate`는 원뿔 반증이 모든 entrypoint 입력에 대해 성립한다(`synthesis_cone_unsat`, 닫힌 원뿔: 후보가 정한 값만 고정). 그러나 "합성 실패는 배제 아님" 지시에 따라 `unknown`으로 두었다. **`excluded_in_context`로 승격할지는 miiz 결정 사항**이다. 승격하면 코드 한 줄을 바꾼다.

## 특수 규칙·추가한 일반 규칙·막힌 곳

**후보·프로젝트별 특수 규칙: 없음.** 추가한 규칙은 모두 회로 구조에서 나온다.
1. 경로 탐색은 호출 위치 내부 wire와 직접 묶인 입력을 지나가지 않는다.
2. 원뿔에서 위치 내부 제약을 뺀다.
3. 차수 32 초과 허브 wire를 기준값에 고정한다. 이때 원뿔은 "닫히지 않음"으로 표시하고, `unsat`을 모든 입력에 대한 근거로 쓰지 않는다.
4. 정직 계산이 중단되면 다시 쓴 O0 생성기로 도달을 확인한다.
5. 다른 위치 이탈은 hint 키(위치 입력이 후보 입력과 같음) 일치로 센다. L-01의 하류 전파 과대 계수를 수정했다.
6. 반증에 private 입력과 후보 위치 신호를 고정하고, O0로 다시 시도한다.
7. 소스 복사에서 심볼릭 링크를 재현하고, 원본으로 쓰지 않도록 막는다.

**막힌 곳.**
- 후보 값 자체가 공유 입력을 통해 다른 계산을 중단시키는 경우(16건)는 다른 입력 전체를 탐색해야 하므로 범위 밖이다.
- R1CS 역전파와 국소 풀이는 제약 없는 hint를 볼 수 없다. 예: `IntDiv.out <-- quot`. 그래서 국소 모델이 실제 계산에서 재현되지 않는다(2건). `Subtract` K5처럼 이런 hint를 거쳐야 하는 경로도 막힌다.
- z3에는 유한체 이론이 없다. 이번 원뿔은 작아서 문제가 없었지만, 큰 비선형 원뿔에서는 시간 초과 위험이 있다.
- 두 번째 프로젝트 자료에 TCCT 이탈 후보가 없어 entrypoint 단계의 일반성은 미확인이다.

## 필수 검사

`cargo fmt` 통과, `cargo clippy --all-targets --all-features -- -D warnings` 통과, `cargo test` **316 통과 · 0 실패 · 22 ignored**. lifting 엔진 fixture 테스트는 17 일치·1 PENDING·0 불일치다.
