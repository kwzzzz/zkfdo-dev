# 합성 맥락 판정 fixture — LF-01 이력 / LF-02 후속

담당 miiz · LF-02 시작 2026-10-02 · 기한 2026-10-06. 외부 프로젝트와 무관한 작은 회로의 고정 후보·정직한 대조군이다. 실제 후보·평가 자료·zkFuzz는 사용하지 않는다. 출력 제약을 의도적으로 빠뜨린 컴포넌트의 후보를 사용하며 비자명한 `square = x*x` 제약도 검사한다.

| LF-02 새 fixture | 목표 판정 | 현재 엔진 관측과 한계 |
|---|---|---|
| [preparation_failure_no_callsite](preparation_failure_no_callsite/expected.json) | `preparation_failure` | `no_call_site`: entrypoint에 해당 컴포넌트 호출 없음 |
| [preparation_failure_input_wire](preparation_failure_input_wire/expected.json) | `preparation_failure` | `component_inputs_unresolved`: bus 입력의 O0 wire는 존재하지만 `main.payload.x`를 직접 입력으로 식별하지 못함 |
| [linear_inversion](linear_inversion/expected.json) | `entrypoint_violation` | 선형식 역산 후 전체 제약·출력 차이 확인 |
| [bitdecomp_inversion](bitdecomp_inversion/expected.json) | `entrypoint_violation` | 비트 분해·재조합의 역산 후 전체 제약·출력 차이 확인 |
| [range_unreachable_intermediate](range_unreachable_intermediate/expected.json) | `excluded_in_context` | 아직 `unknown`(국소 역산 UNSAT); 별도 원본 제약 부분집합 증명으로 전역 도달 불가 확인 |

**기대값의 근거.** 선형식과 4비트 역순 재조합은 검증용 구체 입력에서 원본 R1CS를 만족하는 전체 후보 할당과 동일 입력의 정직한 출력 차이를 검사한다. 이 구체 입력은 `candidate_context.json`에만 있고, 엔진의 `base_input.json`은 후보 중간값에 도달하지 않는다. 따라서 fixture oracle을 엔진에 주어 역산 성공으로 처리하지 않는다. 역산 해의 유일성도 요구하지 않는다.

범위 사례는 실제 O0 R1CS의 8개 boolean 제약·합식·중간값/호출 입력 연결을 확인한다. 후보 입력 300은 가능한 bit 합 0..255의 256개 조합 모두와 모순된다. 이 부분집합에는 공개 입력의 값을 고정하는 가정이 없어 **모든 공개 입력에 대한 배제**가 정당하다. 엔진의 제한된 국소 풀이가 UNSAT라고 반환한 사실만으로 이 증명을 대신하지 않는다. 엔진이 증명이나 구체 witness를 확보하지 못하면 `unknown`을 유지하는 것이 정당하다.

**정직한 대조군.** 새 5종 모두 컴포넌트·entrypoint 정상 계산과 제약 만족을 독립 검사한다. bus 이외의 4종은 현재 엔진에서 `not_tcct_deviation / component_equals_honest`로 조기 분리된다. bus 대조군은 입력 식별 단계에서 같은 준비 실패가 난다. 준비 실패와 위반 없음을 다른 층으로 기록하며, bus의 `sites_found: 0`은 열거 전 중단 결과다. 실제 소스에는 `main.child` 한 곳이 있다.

**이력 보존.** 기존 [O1 preparation_failure](preparation_failure/expected.json)의 파일은 그대로 둔다. O1에서의 직접 symbol 소실은 실제지만, O0로 대응하는 엔진의 준비 실패 근거는 아니다. 이 fixture는 현 엔진 준비 실패 관문에서 제외된 이력이다. 기존 [출력 위반](entrypoint_violation/expected.json)·[최상위 영향 없음](compatible_no_top_violation_observed/expected.json)·[직접 범위 배제](excluded_in_context/expected.json)·[비선형 연결](unknown/expected.json)도 보존한다. 정직한 대조군의 새 비이탈 상태는 각 `expected.control-v2.json`에 기록하여 기존 판정을 덮어쓰지 않는다. 역산 지원 엔진은 기존 비선형 `ToyHash`에서도 구체 입력과 출력 차이를 찾았다. 그 기대값은 `unknown/expected.engine-v2.json`에 별도로 남긴다. 종전 `unknown`은 정방향 프로필의 한계였고 역상 부재가 아니었다. `ToyHash`는 비암호학적 stub이며 암호학적 역산 난이도의 근거가 아니다.

**형식과 재실행.** [FORMAT.md](FORMAT.md)의 named candidate/request 형식을 따른다. `src/`에는 정의·standalone·entrypoint, JSON에는 합성 할당·정상 입력·기대 판정을 둔다. 생성 witness와 컴파일 산출물은 테스트 임시 디렉터리 또는 ignored `runs/`에만 둔다. PATH에 Circom **2.2.3**, Node.js, snarkjs, Python 3.9 이상이 필요하며 도구 누락은 실패다. 역산 지원 엔진의 결과 비교에는 Z3도 필요하며 확인 환경은 Z3 5.1.0이다. 컴포넌트 진위·독립 oracle 검사 자체는 Z3를 사용하지 않는다.

```sh
cargo test --test lifting_fixtures_test
cargo test --test lifting_engine_test -- --nocapture
```

엔진 검사는 목표 `sites`/준비 상태/사유를 우선 비교한다. 역산 3종에 한해 `pending_engine`에 명시한 정확한 미판정 상태를 PENDING으로 별도 집계한다. 범위 사례의 사유 이름은 병렬 버전에서 실제 관측한 `synthesis_local_unsat`·`synthesis_cone_unsat` 두 가지를 명시한다. 다른 오류나 준비 실패를 대신 허용하지 않으며, 대조군에는 PENDING 예외가 없다. 빈 site 목록도 준비 사유가 다르면 실패한다. PENDING이 남은 테스트 실행 통과는 해당 목표의 달성을 뜻하지 않는다.

LF-02 완료(2026-10-02): 신규 O0 컴파일 **10/10**, 후보 진위·정상 대조군 각각 **5/5**, 후속 Python **8개**·기존 **14개** 통과. 후보는 전체 컴포넌트 R1CS를 로컬 평가와 `snarkjs wtns check`로 모두 만족하면서 동일 입력의 정직한 계산과 달랐다. 엔진 요청은 기존 포함 **18건 중 목표 일치 17·PENDING 1**, 임의 불일치 0이다. 범위 사례의 엔진 목표는 미달이며 fixture의 독립 배제 증명과 혼합하지 않는다. `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` 모두 통과했다(**Rust 315 통과·22 ignored**, fixture 검사 생략 없음). Python 검사는 Rust 통합 검사 안에서도 실행되므로 수를 합산하지 않는다. 원시 검증 로그는 ignored `runs/lf02-validation-_ge_ub_m/`에 있다.

LF-01 이력: 후보·정상 대조군 각각 5/5, 기본 컴파일 10조건과 별도 O0 대조 1조건, Python 14개 및 당시 Rust 304 통과·22 ignored. 이번 완료는 fixture와 검증 자료에 한정하며 엔진 기능·L-02 전체·N4-1 전체·N5 완료나 실제 프로젝트 일반화의 근거가 아니다.
