# L-06 결과: IntDiv 의존 분리, 수정 커밋 대조, 수리 컴파일 캐시

2026-10-03 시작·2026-10-05 완료 · 담당 miiz · 기한 2026-10-06. 판정 정의는 [L-01 기준](lifting_feasibility_2026-10-02.md)과 [L-05 결과](lifting_l05_results_2026-10-03.md)를 따른다. 값 없는 근거(리비전·diff 해시, 컴포넌트 동일성, 리비전별 판정, 원본 정직 실행 확인, 재실행 비교, 비용, 산출물 정리 기록)는 [evidence JSON](lifting_l06_evidence_2026-10-05.json)에 있다. 원시 값은 ignored `runs/l06-2026-10-03/`에만 있다. **새 zkFuzz 실행은 없다.** 후보·프로젝트별 규칙은 넣지 않았다. 모든 판정은 A-02의 같은 후보 파일과 기준 입력을 쓴다.

## 요약

| 항목 | 결과 |
|---|---|
| 리비전 | IntDiv만 고친 커밋은 없다(`9221e8d`는 Subtract 수정 포함). 원본 `d310309`에 `9221e8d`의 IntDiv 변경만 적용한 개발용 패치를 R_intdiv로 썼다. **Clamp 수정은 `771c61c`이고 `79f42ee`는 DistanceFromScore 수정이다**(지시문 정정). `771c61c`는 circom 2.2.3에서 컴파일되지 않아 `024227f`의 순서 수정만 얹었다. |
| Clamp 3건·CalculatedScoreFraction 2건 | L-05의 가정 술어 도달은 모두 `IntDiv.out` 무제약 hint 주입 경유였다. R_intdiv부터 모든 리비전에서 **미판정**이다. 소스 기준 수동 증명: IntDiv가 고쳐지면 `Clamp.LessThan[0]`의 깨진 조건은 성립할 수 없다(아래). 엔진은 이를 증명하지 못해 미판정으로 남겼다. |
| DistanceFromScore #13 | R_intdiv, `9221e8d`(Subtract+IntDiv 수정), `loo_dfs`(PR의 다른 수정 전부)에서 **hint 주입 없이 도달**(두 검사기 통과). 같은 입력은 원본 회로의 정직한 생성기에서도 조건을 깨고 snarkjs를 통과한다. 바뀐 값은 **공개 입력** `previous_score[0]`, `maximum_score[0]`이다. DistanceFromScore를 고친 모든 리비전에서 3건 모두 후보 배제. |
| 수정본 대조 | 수정본에서 도달한 후보는 0건이다. 단 수정본에서는 후보가 고친 컴포넌트를 통과하지 못해(정직 생성 중단) 깨진 조건을 복원하지 못하고, 가정 술어 판정이 빠진다. 대조는 "후보 배제"까지만 보인다. |
| 수리 컴파일 캐시 | 진단 사본·주입 생성기·비교 생성기 컴파일을 내용 키로 캐시. A-02 31건 재실행 판정이 L-05와 31/31 같다(캐시 없음·있음 모두). 같은 조건의 첫 실행 대비 캐시 실행의 컴파일 시간 811초 → 197초. 벽시계는 동시 부하로 L-05와 비교할 수 없다. |
| 필수 검사 | `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test --no-fail-fast` 344 통과·0 실패·22 ignored, 관련 Python 테스트 통과 |

## 리비전 (`runs/dev-projects/inference`, git으로 확인)

수정 PR #2의 순서: `d310309`(원본, A-02 tree와 16 파일 동일) → `b389892` Subtract → `9221e8d` IntDiv → `79f42ee` DistanceFromScore → `771c61c` Clamp → `09ca7dd` MetricNormalized → `7217b0e` ResponseTimeNormalized → `b67ae0e` ScoringFunction(responseTimeMetric) → `270bc49`·`4d9012d`(파일 정리·템플릿 이름 오타) → merge `b8f92bd`. 이후 `024227f`가 Clamp 검사 순서를 고치고 main을 `(1024,40)`으로 바꿨다.

| 이름 | 기반 | 덮어쓴 파일 | 원본 대비 바뀐 파일 | 목적 |
|---|---|---|---|---|
| R_intdiv | `d310309` | `integerDivision.circom` ← `9221e8d` | IntDiv | IntDiv 의존 분리(지시) |
| `c9221e8d` | `9221e8d` | – | IntDiv, Subtract | Subtract hint 의존까지 분리 |
| `c79f42ee` | `79f42ee` | – | + DistanceFromScore | DistanceFromScore 수정본 대조 |
| `c771c61c` | `771c61c` | – | + Clamp | Clamp 수정본 대조(컴파일 실패, T3001: `temp_max` 대입 전 검사) |
| `c771c61c_p` | `771c61c` | `clampTensor.circom` ← `024227f` | 같음 | Clamp 수정본 대조(순서만 수정, main은 원본 `(256,40)`) |
| `loo_clamp` | `b8f92bd` | `clampTensor.circom` ← 원본 | PR 전체 − Clamp | Clamp 단독 도달성(리드 판단으로 추가) |
| `loo_dfs` | `b8f92bd` | `clampTensor` ← `024227f`, `distanceFromScore` ← 원본 | PR 전체 − DistanceFromScore | DistanceFromScore 단독 도달성(추가) |
| `all_fixed` | `b8f92bd` | `clampTensor` ← `024227f` | PR 전체 | 전체 수정본 대조(추가) |

각 리비전 diff는 `runs/l06-2026-10-03/trees/<이름>.diff`(해시는 evidence). R_intdiv의 diff는 IntDiv의 `Num2Bits(n)` 세 줄과 `out <-- quot` → `out <== quot`뿐이다.

**컴포넌트 동일성:** 후보 wrapper(`Clamp(40)`, `DistanceFromScore(40)`, `CalculatedScoreFraction(40)`)를 각 리비전에서 O1·O0로 컴파일해 R1CS·`.sym` 해시를 원본과 비교했다. R_intdiv와 `c9221e8d`에서는 셋 다 같아 제외한 후보가 없다. `c79f42ee`는 DistanceFromScore만, Clamp 수정을 포함한 리비전은 셋 다 바뀐다(CalculatedScoreFraction은 Clamp를 쓴다). `loo_clamp`에서 Clamp·CalculatedScoreFraction은 원본과 같다.

## 1. 판정 비교 (후보 값 판정 / 가정 술어 판정)

`ⓘ`는 도달 근거에 `IntDiv` 31행(`out <-- quot`) hint 주입이 들어간 경우, `(무주입)`은 hint 주입 없이 정직한 생성기로 도달한 경우다. `–`는 가정 술어를 판정하지 못한 경우다(아래 엔진 한계 2). #15는 `LessThan[0]`/`LessThan[1]` 두 인스턴스다. CalculatedScoreFraction #26은 지시의 2건(#6·#16, L-05 도달)에 더해 같은 라벨의 나머지 1건을 함께 돌렸다.

| 후보 | 원본 (L-05) | R_intdiv | `c9221e8d` | `c79f42ee` | `c771c61c_p` | `loo_clamp` | `loo_dfs` | `all_fixed` |
|---|---|---|---|---|---|---|---|---|
| #3 DistanceFromScore(40) | 도달 / 도달 ⓘ | 배제 / 미판정 | 배제 / 미판정 | 배제 / – | 배제 / – | 배제 / – | 배제 / 미판정 | 배제 / – |
| #13 DistanceFromScore(40) | 도달 / 도달 ⓘ | 도달 / 도달 (무주입) | 도달 / 도달 (무주입) | 배제 / – | 배제 / – | 배제 / – | 도달 / 도달 (무주입) | 배제 / – |
| #23 DistanceFromScore(40) | 도달 / 도달 ⓘ | 미판정 / 미판정 | 미판정 / 미판정 | 배제 / – | 배제 / – | 배제 / – | 미판정 / 미판정 | 배제 / – |
| #5 Clamp(40) | 배제 / 도달 ⓘ | 배제 / 미판정 | 배제 / 미판정 | 배제 / 미판정 | 배제 / – | 배제 / 미판정 | 배제 / – | 배제 / – |
| #15 Clamp(40) | 배제 / 도달·미판정 ⓘ | 배제 / 미판정·미판정 | 배제 / 미판정·미판정 | 배제 / 미판정·미판정 | 배제 / – | 배제 / 미판정·미판정 | 배제 / – | 배제 / – |
| #25 Clamp(40) | 배제 / 도달 ⓘ | 배제 / 미판정 | 배제 / 미판정 | 배제 / 미판정 | 배제 / – | 배제 / 미판정 | 배제 / – | 배제 / – |
| #6 CalculatedScoreFraction(40) | 배제 / 도달 ⓘ | 배제 / 미판정 | 배제 / 미판정 | 배제 / 미판정 | 배제 / – | 배제 / 미판정 | 배제 / – | 배제 / – |
| #16 CalculatedScoreFraction(40) | 배제 / 도달 ⓘ | 배제 / 미판정 | 배제 / 미판정 | 배제 / 미판정 | 배제 / – | 배제 / 미판정 | 배제 / – | 배제 / – |
| #26 CalculatedScoreFraction(40) | 미판정 / 미판정 | 배제 / 미판정 | 배제 / 미판정 | 배제 / 미판정 | 배제 / – | 배제 / 미판정 | 배제 / – | 배제 / – |

수정본(`c79f42ee`, `c771c61c_p`, `all_fixed`)에서 도달한 후보는 없다. 후보 값 배제 근거는 DistanceFromScore가 새 `Num2Bits(40)` 범위와의 모순(닫힌 원뿔), Clamp·CalculatedScoreFraction이 L-05와 같은 상수 불일치(`min = 0`)다.

### hint 의존

- 원본의 도달 8건은 모두 `IntDiv` 31행 hint 주입을 거쳤다. DistanceFromScore는 후보 입력 합성(`synthesized_b_hint_injection`) 단계에서, Clamp·CalculatedScoreFraction은 가정 술어 탐색 단계에서다(`Num2Bits` 12행과 함께).
- IntDiv를 고친 뒤의 도달(DistanceFromScore #13)은 hint 주입이 없다(`synthesized_a`, 정직한 생성기).

### Clamp: IntDiv 결함 없이는 깨질 수 없다 (수동 증명, 엔진은 미판정)

`CalculatedScoreFraction`에서 Clamp의 `val = total = response_time_reward_metric + 0 + competition_weighted`, `min = 0`이다(`src/calculatedScoreFraction.circom`, `src/circuit.circom` 86–106행). L-05에서 도달한 인스턴스는 `Clamp.LessThan[0]`(`in = [val, min]`)이다.

1. R_intdiv의 `IntDiv(n)`은 `Num2Bits(n)(quot)`와 `out <== quot`를 가지므로 출력은 [0, 2^n)이다(`src/integerDivision.circom` 26–35행).
2. `competition_weighted = IntDiv(40).out`(`circuit.circom` 96–99행), `response_time_reward_metric = ResponseTimeMetric(40).out = IntDiv(40).out`(`responseTimeMetric.circom` 마지막 4행). 따라서 `total ∈ [0, 2^41)`이고, 체에서 감싸 돌지 않는다.
3. `LessThan(40)`은 `Num2Bits(41)(2^40 + total − 0)`를 요구한다(`clampTensor.circom` 27–36행; `Num2Bits`는 비트 boolean과 가중합 = 입력을 강제). 이는 `total < 2^40`일 때만 만족되고, 그때 `out = 1 − bit40 = 0`이다.
4. 정수 비교 `total < 0`은 항상 거짓이므로 `out = 0`과 일치한다. 깨진 조건(`out = 1`)은 어떤 유효 witness에서도 나오지 않는다.

즉 이 entrypoint에서 Clamp 비교기 넘침은 IntDiv의 무제약 출력이 있어야만 터진다. zkbugs의 Clamp 항목은 컴포넌트 단위로는 실제 결함이지만, 이 회로에서는 **IntDiv 결함에 연쇄된 결함**이다. 엔진은 두 IntDiv 출력의 범위를 덧셈을 거쳐 전파하지 못해 미판정으로 남겼다(건전하지만 불완전). 이 증명은 수동이며 기계 검증 기록이 아니다.

### DistanceFromScore: IntDiv와 무관하게 도달, 단 공개 입력 조건

- R_intdiv·`c9221e8d`·`loo_dfs`의 #13 도달 witness는 원본 O1 R1CS를 Rust 평가와 snarkjs로 모두 만족하고, O0/O1이 일치하며, `main.distance_from_score_fn[0].positive`의 출력이 정수 비교와 다르다.
- 같은 입력(`input_sha256 cb589bb9…`)을 **원본** 회로의 정직한 생성기(O1·O0, L-05 캐시 빌드)에 넣으면 중단 없이 생성되고, `previous_score = p−1`, `maximum_score = 4`에서 `LessThan.out = 1`(정수로는 거짓)이다. 두 witness 모두 snarkjs `WITNESS IS CORRECT`. 따라서 L-05의 IntDiv 주입 경로는 필요 조건이 아니었다.
- 이 도달은 최상위 **공개 입력** `previous_score[0]`(= p−1)과 `maximum_score[0]`을 바꿔 얻는다(`component main {public [...]}`에 둘 다 있다). 사설 witness만으로 얻는 도달이 아니므로, 공개 입력을 검증자가 정하는 배치에서는 공격이 아니다. 프로젝트는 `79f42ee`에서 두 입력을 회로 안 `Num2Bits(b)`로 검사하도록 고쳤다.

### 엔진 한계 (둘 다 미판정·누락 방향, 건전성 문제는 아님)

1. **같은 인스턴스, 다른 판정:** #3·#23의 가정 술어는 #13이 도달을 보인 같은 인스턴스(`main.distance_from_score_fn[0].positive`)인데 미판정이다. 가정 술어는 정의상 (entrypoint, 인스턴스)의 성질인데, 지금은 후보마다 탐색 출발점이 달라 결과가 갈린다.
2. **수정본에서 술어 누락:** 고친 컴포넌트에서는 후보 입력으로 정직 생성이 중단되어(`honest_generation = aborted`) 깨진 조건을 복원하지 못하고, `violated_condition`이 비어 술어를 판정하지 않는다. 수정본 대조가 "후보 배제"에 그치고 술어 배제 증명까지 가지 못한다.

## 2. 수리 컴파일 캐시 (`src/candidate_review/lifting/repair.rs`)

`compile_edits`(진단 사본, 주입 생성기 O0·O1, 비교 생성기)가 `--cache`가 있을 때 `<cache>/edits/<key>`에 빌드를 두고 재사용한다. 키는 compiler 해시, O0 여부, entrypoint 상대 경로, 소스 루트·라이브러리 경로, 닫힘의 모든 소스 내용 해시, 정렬한 edit 목록이다. 같은 키면 같은 컴파일이다. 회귀 테스트 `repair_compiles_are_reused_from_the_cache`(`tests/lifting_engine_regression_test.rs`)는 같은 요청을 두 번 돌려 두 번째의 수리 컴파일이 모두 캐시 적중이고, 결과가 비용을 빼고 같음을 확인한다.

| A-02 31건 | L-05 | L-06 첫 실행(빈 캐시) | L-06 캐시 실행 |
|---|---:|---:|---:|
| 판정이 L-05와 같음 | – | 31/31 | 31/31 |
| 컴파일 시간 합 | 585초 | 811초 | **197초** |
| 캐시 적중(컴파일 단계) | 42 | 132 | 287 |
| 진단 사본 O0 (적중/전체) | 0/150 | 75/148 | 125/135 |
| 주입 생성기 O0 (적중/전체) | 0/93 | 12/92 | 80/88 |
| 벽시계 합 | 1,594초 | 2,359초 | 1,691초 |

- **벽시계는 비교할 수 없다.** 측정 중 같은 기계에서 M-01과 다른 작업이 돌았고(load average 26–42, 10코어), 컴파일이 아닌 단계(합성·수리·검사·술어)도 L-05보다 1.1–2.3배 느렸다. 같은 부하 조건의 첫 실행 대비 캐시 실행에서 컴파일 시간이 76% 줄었다.
- 캐시 실행의 남은 미적중은 z3 모델 값이 실행마다 달라 주입 edit가 바뀐 경우다(판정은 같다). 캐시하지 않은 hint entrypoint 컴파일(O1 13회·O0 7회, 119초)이 남은 컴파일 시간의 대부분이다.

## 3. 산출물 정리

측정 뒤 `runs/l06-2026-10-03/`의 `.r1cs`·`.wasm` 1,054개(27.2 GB)를 경로·SHA-256·크기로 `runs/l06-2026-10-03/artifact-cleanup-20261004T160745Z.json`에 기록하고 지웠다. 후보·결과·입력·로그·witness(`.wtns` 529개)·`.sym`·작업 소스 사본은 남겼다. L-05 캐시 빌드(원본 정직 실행 확인에 읽기 전용으로 사용)는 손대지 않았다.

## 측정 중 사고와 편차

- **대조 실행 중복:** `c771c61c_p` 실행 대기 프로세스가 의도와 달리 두 개 살아 있어 같은 출력·캐시 폴더에 동시에 실행됐다. 그 결과(로그 `run-c771c61c_p-raced.log`, 시간 `walls-c771c61c_p-raced.json`)는 버리고 출력·캐시를 지운 뒤 단독으로 다시 돌렸다. 표의 `c771c61c_p` 열은 단독 실행이다(판정은 중복 실행 때와 같았다).
- **추가 리비전:** `c9221e8d`·`loo_clamp`·`loo_dfs`·`all_fixed`는 지시에 없던 대조다. R_intdiv에는 같은 PR에서 나중에 고친 결함(ResponseTimeNormalized·ScoringFunction)이 남아 있어, 미판정을 독립성 판단에 쓰려면 다른 결함을 모두 고친 leave-one-out이 필요했다.
- **바이너리:** `runs/l06-2026-10-03/tools/zkfDO`(SHA-256 `d43fd5f7…`). M-01이 쓰는 `runs/f01-2026-10-03/supplement-var-scope/tools/zkfDO`는 건드리지 않았다.

## 필수 검사

`cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings` 통과. `cargo test`는 첫 실행에서 `ordered_scheduler_test::nonzero_exit_does_not_become_success_from_summary_text`가 2초 제한의 셸 스크립트를 부하(load 36–40) 때문에 `Timeout`으로 판정해 실패했다. 단독 재실행 8/8 통과, `cargo test --no-fail-fast` 전체 344 통과·0 실패·22 ignored(`runs/l06-2026-10-03/cargo-test-2.log`). Python `tests/lifting_fixture_followup_test.py`(8, `PYTHONPATH=tests`)·`zkfuzz_report_test.py`·`f01_discovery_test.py` 통과.
