# L-07 결과: 가정 술어를 (entrypoint, 인스턴스) 단위로 판정

2026-10-05 시작·2026-10-06 완료 · 담당 miiz · 기한 2026-10-08. 판정 정의는 [L-05 결과](lifting_l05_results_2026-10-03.md)와 [L-06 결과](lifting_l06_results_2026-10-05.md)를 따른다. 값 없는 근거(엔진·스크립트·fixture 해시, 그룹별 인스턴스 판정, 판정 변화 전체 목록과 원인, 비용, 산출물 정리 기록)는 [evidence JSON](lifting_l07_evidence_2026-10-06.json)에 있다. 원시 값은 ignored `runs/l07-2026-10-05/`에만 있다. **새 zkFuzz 실행은 없다.** 후보·프로젝트별 규칙은 넣지 않았다.

## 요약

| 항목 | 결과 |
|---|---|
| 인스턴스 단위 판정 | 같은 entrypoint의 같은 `LessThan` 인스턴스 판정을 저장소(`--instance-store`)로 요청 간에 공유하고, `experiment lift-instances`가 결과 묶음에서 실행 순서와 무관하게 인스턴스 판정을 합친다. 141회 판정에서 **충돌(같은 인스턴스가 도달이면서 배제) 0건**. |
| 후보 없는 술어 판정 | 후보가 고친 컴포넌트를 통과하지 못해도 컴포넌트의 `LessThan` 인스턴스를 모두 판정한다. 수정본에서 술어가 빠지던 경우(L-06의 `–`)가 모두 **배제 증명**이 됐다. |
| 도달 근거 분류 | 도달 witness의 최상위 입력을 기준 입력과 비교해 공개/사설로 나눈다. Banyan 실제 결함 2 인스턴스는 **사설만**, inference DistanceFromScore는 **공개 입력 변경**, inference Clamp(원본)은 IntDiv hint 경유 **사설만**. |
| 범위 전파 | bit 분해 구간을 선형 제약으로 전파(나머지 연산이 없을 때만). L-06에서 수동으로 증명한 "IntDiv 수정 시 Clamp `LessThan[0]` 위반 불가"를 엔진이 증명한다(R_intdiv 등 4개 리비전). 범위 전파 자체는 선행 기술(CCC-Check)이고 기여가 아니다. |
| 회귀 | A-02 31건·Banyan 36건·zk-email 9건의 클래스 판정(후보 값·가정 술어)은 L-05와 **하나도 바뀌지 않았다.** 바뀐 것은 inference 리비전 행렬뿐이고 전부 미판정/판정 없음 → 도달·배제다. |
| hint entrypoint 캐시 | 수리 컴파일과 같은 내용 키(`<cache>/edits/<key>`)로 hint entrypoint O1·O0 컴파일도 재사용한다. |
| 필수 검사 | `cargo fmt`, `cargo clippy -D warnings`, `cargo test` 348 통과·22 ignored, 관련 Python 테스트 통과 |

## 구현

- **`src/candidate_review/lifting/predicate.rs`:**
  - `judge`가 대상 인스턴스 목록을 받는다.
  - 순서: (1) 후보 자신의 도달 witness → (1b) 인스턴스 저장소 → (2) 배제(닫힌 원뿔 + 범위 사실) → (3) 탐색.
  - 증명된 판정(두 검사기를 통과한 도달, 또는 배제)만 저장소에 쓴다. 저장소 키는 (entrypoint O1 R1CS·O1 sym·O0 R1CS 해시, 인스턴스, 조건 종류)다.
  - 이미 저장된 판정과 반대 판정이 나오면 덮어쓰지 않고 `instance_store_conflict`를 남긴다.
  - (1)을 저장소보다 먼저 보므로, 저장된 배제와 후보 witness의 도달이 부딪히면 드러난다.
- **도달 분류(`reach_inputs`):** 기준 입력과 도달 입력을 펼쳐 체 원소로 비교한다. 공개 입력은 R1CS 배치(출력 다음 `nPubIn`개 wire)의 이름이다. 분류는 `private_only` / `public_inputs_changed`다. 관찰된 witness의 분류이며, "공개 입력이 꼭 필요하다"는 증명은 아니다.
- **범위 전파(`propagate_linear`):**
  - 같음 클래스로 묶은 선형 제약 `Σc·x + k = 0`에서 계수가 ±1인 클래스를 나머지의 정수식으로 놓는다.
  - 그 구간이 [0, p) 안이면 mod p 감김이 없으므로 구간을 좁힌다(최대 8회 반복).
  - 배제 근거에 사용한 선형 제약 번호(`linear_propagation_constraints_used`)를 남긴다.
- **`src/candidate_review/lifting/mod.rs`:**
  - 술어 대상은 후보가 깨뜨린 인스턴스, 없으면(후보가 컴포넌트에서 중단되거나 깨뜨린 것이 없으면) 컴포넌트의 `LessThan` 인스턴스 전부다(`target_basis`).
  - hint entrypoint 컴파일은 `edits_key`로 캐시한다.
- **`src/candidate_review/lifting/instances.rs`(새 파일) + `experiment lift-instances`:**
  - 인스턴스별 판정: 도달 하나라도 있으면 도달, 배제 증명이 있으면 배제, 둘 다면 `conflict`, 아니면 미판정.
  - 클래스별 실효 판정(`effective`)을 함께 낸다.
- **`condition.rs`:** `lessthan_instances`를 분리했다.
- **테스트:** `tests/lifting_engine_regression_test.rs`에 4개를 추가했다(범위 전파, 고친 컴포넌트의 비교기 판정, 공개/사설 분류, 저장소 공유와 `lift-instances`). fixture는 `tests/fixtures/lifting_engine/{lessthan_propagation, lessthan_fixed_component, lessthan_private}`(합성, 프로젝트 무관)다. 범위 전파 fixture는 L-06 바이너리에서 미판정, L-07 바이너리에서 배제임을 확인했다.

## 검증 1: inference 리비전 행렬 (인스턴스 단위)

리비전은 [L-06](lifting_l06_results_2026-10-05.md)과 같다. 원본(A-02), R_intdiv(IntDiv만), `c9221e8d`(+Subtract), `c79f42ee`(+DistanceFromScore), `c771c61c_p`(+Clamp, 순서 수정), `loo_clamp`(PR 전체 − Clamp), `loo_dfs`(PR 전체 − DistanceFromScore), `all_fixed`(PR 전체)다.

| 인스턴스 | 원본 | R_intdiv | c9221e8d | c79f42ee | c771c61c_p | loo_clamp | loo_dfs | all_fixed |
|---|---|---|---|---|---|---|---|---|
| DistanceFromScore `positive` | 도달 (공개 입력) | 도달 (공개 입력) | 도달 (공개 입력) | 배제 | 배제 | 배제 | 도달 (공개 입력) | 배제 |
| Clamp `LessThan[0]` | 도달 (사설만) | 배제 | 배제 | 배제 | 배제 | 배제 | 배제 | 배제 |
| Clamp `LessThan[1]` | 미판정 | 미판정 | 미판정 | 미판정 | 배제 | 미판정 | 배제 | 배제 |

- **DistanceFromScore:** 해당 수정이 없는 리비전에서는 모두 도달하고, 수정이 있는 리비전에서는 모두 배제 증명이다. 수정 커밋 전·후 대조가 인스턴스 단위로 정확히 갈린다.
- **Clamp `LessThan[0]`:** 원본에서만 도달한다(IntDiv hint 주입, 공개 입력 변경 없음). IntDiv를 고친 모든 리비전에서 배제가 증명된다. **Clamp만 고치지 않은 `loo_clamp`에서도 배제**이므로, 이 회로에서 Clamp 결함은 IntDiv 결함에 연쇄돼야만 터진다는 L-06의 수동 증명을 엔진이 확인한다.
- **Clamp `LessThan[1]`:** Clamp를 고친 리비전에서 배제다. 고치지 않은 리비전에서는 미판정이다(도달도 배제도 못 함).

**클래스 판정 변화(L-06 대비, 52건, 전부 미판정/판정 없음 → 도달·배제, 반대 방향 0):**

| 원인 | 건수 | 내용 |
|---|---:|---|
| 후보 없는 술어 판정 + 범위 전파 | 30 | 수정본에서 `–`(술어 없음) → 배제 |
| 범위 전파 (저장소 공유 포함) | 16 | Clamp·CalculatedScoreFraction `LessThan[0]` 미판정 → 배제(IntDiv 수정 리비전) |
| 인스턴스 공유 | 6 | DistanceFromScore #23 미판정 → 도달(저장소), #3 실효 판정 미판정 → 도달(합치기; #13보다 먼저 실행돼 자기 판정은 미판정) |

정확한 행별 목록은 evidence JSON의 `changes`에 있다(52행, 원인 표시 포함; 위 건수는 원인이 겹치는 행을 주 원인으로 셌다).

## 검증 2: A-02·Banyan·zk-email

| 자료 | 클래스 | 판정 변화 | 고유 인스턴스 | 인스턴스 판정 | 도달 분류 |
|---|---:|---:|---:|---|---|
| A-02 31건 | 62 | 0 | 5 | 도달 4, 미판정 1 | 사설만 1 (Clamp `LessThan[0]`, IntDiv hint), 공개 입력 3 (DistanceFromScore `positive`, ResponseTimeNormalized `LessThan`, ScoringFunction `lt`) |
| Banyan 36건 | 36 | 0 | 2 | 도달 2 | 사설만 2 (`check_depth.check_parent`, `check_depth.exceed_depth.lt`) |
| zk-email 9건 | 9 | 0 | 13 | 배제 13 | – |

- 세 자료 모두 클래스 판정(후보 값·가정 술어)이 L-05와 같다. 충돌 0.
- **Banyan 실제 결함은 공개 입력을 바꾸지 않고 사설 witness만으로 도달한다.** 위협 모델과 무관하게 증명자가 만들 수 있는 위반이다.
- **inference의 공개 입력 도달 3 인스턴스는 검증자가 공개 입력을 정하는 배치에서는 공격이 아니다.** Clamp `LessThan[0]`의 사설 도달은 IntDiv의 무제약 출력(알려진 결함) 경유다.

## 비용

| 그룹 | 판정 | 벽시계 합 | 컴파일 시간 | 컴파일 캐시 적중 | 저장소 적중 |
|---|---:|---:|---:|---:|---:|
| A-02 | 31 | 1,345초 | 375초 | 133 | 5 |
| Banyan | 36 | 110초 | 3초 | 70 | 0 |
| zk-email | 9 | 108초 | 7초 | 16 | 56 |
| inference 리비전 7개 | 63 | 2,168초 | 1,002초 | 94 | 57 |

- A-02 벽시계는 L-05 1,594초, L-06 캐시 실행 1,691초였다. 이번 실행도 같은 기계에서 다른 작업과 동시에 돌았다(load 13–30). 시간은 참고용이다.
- 저장소 적중은 이미 증명된 인스턴스의 배제·탐색을 건너뛴 횟수다(zk-email은 같은 인스턴스가 후보마다 반복된다).

## 한계

- **공개/사설 분류는 관찰된 witness의 분류다.** "공개 입력 변경 필요"를 증명하려면 공개 입력을 기준값에 고정한 탐색·배제가 필요하다(미구현).
- **Clamp `LessThan[1]`과 A-02의 미판정 1 인스턴스는 그대로다.** 도달 탐색과 배제 원뿔이 모두 닿지 못한다.
- **저장소 공유는 실행 순서에 따라 먼저 실행된 요청의 자기 판정을 바꾸지 않는다.** 순서와 무관한 최종 판정은 `lift-instances`의 인스턴스 표와 클래스 실효 판정이다.

## 산출물 정리

캐시 폴더 10개를 통째로(2,240 파일, 44.6 GB) `runs/l07-2026-10-05/tree-cleanup-20261005T151210Z.json`에 경로·SHA-256·크기를 기록한 뒤 지웠다. 나머지 `.r1cs`·`.wasm` 278개(12 MB)는 `artifact-cleanup-20261005T151215Z.json`에 기록 후 지웠다. 후보·결과·입력·로그·witness(`.wtns` 448개)·인스턴스 저장소(36개)는 남겼다. 바이너리는 `runs/l07-2026-10-05/tools/zkfDO`(SHA-256 `e5cb0184…`)다.

## 필수 검사

`cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings` 통과. `cargo test --no-fail-fast` 348 통과·0 실패·22 ignored(`runs/l07-2026-10-05/cargo-test.log`). Python `tests/lifting_fixture_followup_test.py`(`PYTHONPATH=tests`)·`zkfuzz_report_test.py`·`f01_discovery_test.py` 통과.
