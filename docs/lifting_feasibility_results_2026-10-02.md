# L-01 결과: 자동 맥락 확인(승격) 가능성

2026-10-02 · 담당 miiz · 기준: [lifting_feasibility_2026-10-02.md](lifting_feasibility_2026-10-02.md). 실행 근거(요청·결과 경로, SHA-256, 엔진 소스·도구 해시)는 기계가 쓴 [evidence JSON](lifting_feasibility_evidence_2026-10-02.json)에 있다. 원시 witness·입력·hint 소스는 ignored `runs/l01-lifting-2026-10-02/`에만 있다.

**구현.** `zkfDO experiment lift`(`src/candidate_review/lifting/`)는 기존 `r1cs.rs` 파서·평가기와 `subprocess.rs`를 재사용하고, snarkjs는 두 번째 검사기로만 쓴다. 절차는 다음과 같다.

1. 후보와 정직한 컴포넌트 witness의 차이를 구한다.
2. 차이 신호를 대입하는 `<--` 문만 다시 쓴다. 대상 템플릿은 선언 신호 집합으로 찾고, 템플릿 입력값이 후보 값과 같을 때만 후보 값을 내도록 조건을 건다. 다시 쓴 entrypoint의 R1CS·`.sym`이 원본과 바이트 단위로 같아야 진행한다.
3. 호출 위치는 신호 이름 집합이 컴포넌트와 같은 인스턴스로 찾는다.
4. 각 입력은 O0 R1CS의 `x − y = 0` 등식 사슬로 entrypoint 입력, 상수, 중간값 중 하나에 대응시킨다.
5. 정직한 계산과 다시 쓴 생성기로 같은 입력의 witness를 만들고, 원본 R1CS를 Rust와 snarkjs로 따로 검사한다.

판정 단위는 (후보 × 기준 입력 B0 × 호출 위치 class)다. class는 index를 `*`로 바꾼 경로와 입력 대응 모양이 같은 위치의 묶음이며, 가장 작은 index만 평가한다.

## 관문

| 관문 | 결과 |
|---|---|
| S-05 재현 | **통과.** 1,280개 위치, class 5개. K1·K2는 `entrypoint_violation`이다(Rust 불만족 0/196,096, snarkjs CORRECT, 출력 차이 1개, 이탈 위치 1곳). K3·K4는 `excluded_in_context`(상수 불일치), K5는 `unknown`(중간값 역산 필요)이다. 다섯 종류 모두 S-05 수기 판정 E2·E3와 일치하고 후보별 규칙은 없다 |
| S-04 처리 | 같은 코드로 처리했다. 1,536개 위치, class 6개. `IntDiv(40)`의 `in[0]`이 모든 위치에서 회로 내부 중간값이라 5개 class는 `unknown`(`input_requires_inversion`)이고, 1개 class는 상수 제수 불일치로 `excluded_in_context`다. entrypoint 위반은 관측되지 않았다(위반 없음 판정이 아님) |
| 합성 fixture (LF-01) | 요청이 있는 4종과 정직 대조 4종, 총 **8/8 일치**. `preparation_failure` fixture는 요청 파일이 없다. 이 fixture는 "O1에서 사라진 `main.child.x`를 exact-symbol로 대응할 수 없음"을 전제하지만, 이 엔진은 대응에 O0를 쓰므로 그 전제가 성립하지 않는다. 임시 요청으로 실행하면 `entrypoint_violation`이 나온다. **fixture 5/5 기준은 미충족**이며, 다른 준비 실패 유형(호출 위치 없음, `-->` 대입 등)으로 교체해야 한다 |

전체 판정: **S-05·S-04 조건 충족, fixture 조건 4/5(1종 전제 불일치).** 확장은 비용이 작아 그대로 진행했다. 관문 미완 상태에서 넓힌 결과이므로 참고 자료로만 쓴다.

## 결과표

비용 단위는 초다. 단계는 위치 탐색 / 컴파일 / 실패 시도 / witness 계산 / 검사 순이다. 31건은 entrypoint 컴파일 cache를 공유하므로 각 label의 첫 실행에만 entrypoint O1·O0 컴파일이 들어간다. **dev**는 후보가 정직한 컴포넌트 계산과 다른 신호 수다. 0이면 zkFuzz `UnexpectedInput` 유형으로, 컴포넌트 TCCT 이탈이 아니다(S-02와 같은 상황).

| 대상 | dev | 위치 / class | 판정(class 수) | 단계별 비용 | 합계 | 예외 |
|---|---:|---|---|---|---:|---|
| fixture `entrypoint_violation` (+대조) | 1 (0) | 1 / 1 | violation (대조: compatible) | — | 0.53 (0.45) | — |
| fixture `compatible_no_top_violation_observed` (+대조) | 1 (0) | 1 / 1 | compatible (대조: compatible) | — | 0.50 (0.39) | O1에서 사라진 신호는 O0 생성기로 주입을 확인 |
| fixture `excluded_in_context` (+대조) | 1 (0) | 1 / 1 | excluded, 국소 반증 (대조: compatible) | — | 0.20 (0.37) | — |
| fixture `unknown` (+대조) | 1 (0) | 1 / 1 | unknown, 역산 필요 (대조: compatible) | — | 0.16 (0.45) | 대조는 기준 입력의 정직한 계산이 중간 입력에 도달함을 확인 |
| fixture `preparation_failure` | — | — | 미실행(요청 없음) | — | — | 전제 불일치(위 관문 참고) |
| S-05 후보 (cache 없음) | 2 | 1,280 / 5 | violation 2 · excluded 2 · unknown 1 | 0.71 / 4.44 / 0.06 / 0.62 / 2.27 | 8.10 | — |
| S-04 후보 (cache 없음) | 1 | 1,536 / 6 | excluded 1 · unknown 5 | 0.64 / 4.15 / 0.36 / 0 / 0 | 5.16 | — |
| #3 att9 `DistanceFromScore(40)` | 0 | 256 / 1 | unknown 1 (역산) | 0.65 / 2.59 / 0.17 / 0 / 0 | 3.41 | — |
| #4 att12 `IntDiv(80)` | 1 | 256 / 1 | excluded 1 (상수) | 0.64 / 4.15 / 0 / 0 / 0 | 4.79 | — |
| #5 att13 `Clamp(40)` | 0 | 256 / 1 | excluded 1 (상수) | 0.63 / 2.50 / 0 / 0 / 0 | 3.13 | — |
| #6 att14 `CalculatedScoreFraction(40)` | 0 | 256 / 1 | excluded 1 (상수) | 0.63 / 2.49 / 0 / 0 / 0 | 3.12 | — |
| #7 att15 `ResponseTimeNormalized(40)` | 0 | 256 / 1 | unknown 1 (생성 중단, 반증 실패) | 0.63 / 2.55 / 0.13 / 0 / 0 | 3.31 | 정직·이탈 계산 모두 중단 |
| #8 att18 `IntDiv(120)` | 1 | 256 / 1 | excluded 1 (상수) | 0.66 / 4.23 / 0 / 0 / 0 | 4.89 | — |
| #9 att19 `ScoringFunction(40)` | 0 | 256 / 1 | unknown 1 (역산) | 0.62 / 2.50 / 0.16 / 0 / 0 | 3.29 | 후보에 신호 2개 누락, 컴포넌트 검사 미판정 |
| #10 att20 `ResponseTimeMetric(40)` | 0 | 256 / 1 | unknown 1 (역산) | 0.64 / 2.50 / 0.06 / 0 / 0 | 3.20 | 위와 같음 |
| 반복 21건(#11–31) | 0–2 | 같은 label과 같음 | violation 6 · excluded 15 · unknown 22 | 합계 13.83 / 15.50 / 2.03 / 1.41 / 6.46 | 39.24 | #21·#31 `Subtract()`: 정직한 계산이 `Num2Bits` 제약에서 중단되고 후보 witness는 두 검사기 모두 만족 → `entrypoint_violation`(abort형) K1·K2 각 2. #26은 같은 label의 다른 반복과 달리 상수 불일치가 없어 `unknown` |

**판정별 건수(class 단위).**
- 관문 2건과 미검토 label 8종의 첫 후보(10건, class 19개): violation 2, excluded 7, unknown 10, compatible 0, preparation_failure 0.
- 31건 전체(class 62개): violation 8(출력 차이 4, abort형 4. 모두 `Subtract()` 3건의 K1·K2), excluded 22(전부 상수 불일치), unknown 32(역산 필요 29, 생성 중단 3), compatible 0, preparation_failure 0.
- 처리율: 31/31 실행 완료. 확정 판정(violation·excluded) 30/62, 미판정 32/62(51.6%).

**비용.**
- 31건 합계 81.55초: 위치 탐색 20.30 / 컴파일 47.55 / 실패 시도 3.00 / witness 2.02 / 검사 8.68.
- 후보당 최대 7.88초, 중앙값 2.45초다. cache 없는 S-05는 8.10초로, 600초 중단 기준과 거리가 멀다.
- 사람 검토 시간은 포함하지 않는다.

## 특수 규칙·설계 변경·막힌 곳

- **후보별·템플릿 이름별 분기: 없음.** 템플릿 대응은 선언 신호 집합으로 한다. 동률일 때만 circom의 `main`/`Template_line_col` 명명 규칙을 쓴다.
- **관문 작업 중 추가한 일반 규칙**(모두 구조에서 나옴):
  1. 입력 대응 모양으로 class를 나눈다(K3·K4 분리).
  2. 정직한 후보는 원본 생성기로 평가한다.
  3. O1에서 사라진 hint 신호는 O0 생성기로 주입을 확인한다.
  4. 정직한 계산이 중간 입력에 이미 도달하면 통과시킨다.
  5. 주입 확인은 사이트 wire 값이 후보 값과 같은지로 본다.
  6. **국소 반증:** 원본 제약 부분집합(깊이 4, 제약 256·미지수 96·boolean 16 이하)에 public 입력을 고정하고 boolean 분기와 선형 전파를 한다. 부분집합에 해가 없으면 `excluded_in_context`다. 실패는 아무것도 증명하지 않는다.
- **막힌 곳:**
  - 위치 입력이 회로 내부 중간값이면 입력을 만들지 못한다(31건 중 29 class). 이번 미판정의 대부분이며, 역산·탐색 없이는 넘을 수 없다.
  - 이탈 생성이 중단되고 국소 반증도 실패한 경우는 `unknown`이다(3).
  - class당 대표 index 하나와 고정 기준 입력 B0 하나만 평가했다. 다른 index·입력의 결과는 없다.
  - 상수 배제의 근거는 O0 R1CS의 등식이다. 원본(O1)과 같은 해집합이지만 다른 파일이다.
  - 이 엔진에는 "O1 신호 소실" 준비 실패가 생기지 않는다(O0 대응). 정의 5의 해당 항목은 이 설계에서 거의 발생하지 않는다.
- **해석 한계:** 배치 결과는 원인 귀속이 아니다. #21·#31의 abort형 위반을 포함한 `Subtract()` 반복 6개 class를 새 원인으로 세지 않는다. dev 0 후보의 `excluded`·`unknown`은 정직한 값에 대한 맥락 판정이며 TCCT 결과가 아니다. 프로젝트 의미는 판정하지 않았다.

## 필수 검사

`cargo fmt` 통과, `cargo clippy --all-targets --all-features -- -D warnings` 통과, `cargo test` **306 통과 · 0 실패 · 22 ignored**. 새 엔진 fixture 회귀 `tests/lifting_engine_test.rs`와 LF-01 fixture 작업의 `tests/lifting_fixtures_test.rs`를 포함한다. 단위 회귀는 wtns, Circom 스캐너, 이름·class·입력 구성, 3비트 국소 반증을 다룬다.
