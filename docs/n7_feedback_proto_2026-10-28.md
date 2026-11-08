# N7 J→S 되먹임 작은 시제품: 합성 개발 시험

2026-10-28. **합성 회로의 연결·반증 시험이다. 대형 Circom의 이득, A/B 성과, ScaleCirc 대비 우위를 뜻하지 않는다.** 기존 실행기·고정 평가·J 바이너리는 수정하지 않았다.

## 무엇을 만들고 검증했나

[실행기](../scripts/j_feedback_proto_20261028.py)는 각 군에 동일 seed와 30초 **총 벽시계 상한**을 준다. 부모의 `probe.x = main.x + 2`에서 Probe의 비유일성은 입력 5에 열리고, Probe 출력은 최상위 출력에 쓰이지 않는다. 별도 Target은 `target.x = main.x`, `t = x² − 9`이며 `t=0`에서 출력 비유일성이 열린다. 기준 최상위 입력은 1이다. Probe에서 S가 찾은 **부품 입력 5**를 J가 원본 맥락에서 확인하고 **최상위 입력 3**을 합성했다(`synthesized_a`, 2라운드, `outputs_equal`, Rust 실패 0·snarkjs correct). 따라서 첫 후보 자체의 재생은 아니다.

세 군 모두 Probe 준비·S·J를 실행한다. 이후 **기본**은 자유 Target S+J, **정상 입력**은 최상위 입력 1로 고정한 Target S+J, **피드백**은 J가 검증한 최상위 입력 3으로 고정한 Target S+J를 실행한다. 래퍼에서 나온 후보의 `main.child.*`를 원래 Target의 `main.*`로 복원해 **원본 부모**에서 J로 다시 판정한다([후보 변환](../scripts/j_feedback_proto_20261028.py#L156), [J 게이트](../scripts/j_feedback_proto_20261028.py#L200)). 모든 준비·컴파일·S·J·변환 시간은 군별 30초 한도 안에 있다. 실행은 순차적이었다.

고정 zkFuzz에는 호출별 상관된 입력 벡터 corpus 인자가 없다. 이 구현은 입력을 상수로 고정한 **제한 입력 절제 시험**이다. 일반 GA 시드 주입이나 새 탐색 스케줄러를 구현했다고 부르지 않는다. 기본 Target O0은 2제약, 값 고정 래퍼는 4제약, 부모 O0은 7제약이다.

## 같은 상한의 세 seed

| seed 끝자리 | 기본: Target 판정·초 | 정상 입력 1: Target 판정·초 | J 피드백 3: Target 판정·초 | 원본에서 추가된 고유 원인 |
|---|---|---|---|---:|
| 01 | `entrypoint_violation/output_differs` · 8.596 | 후보 없음 · 4.346 | `entrypoint_violation/output_differs` · 8.610 | 0 |
| 02 | 같은 판정 · 8.571 | 후보 없음 · 4.334 | 같은 판정 · 8.580 | 0 |
| 03 | 같은 판정 · 8.590 | 후보 없음 · 4.351 | 같은 판정 · 8.628 | 0 |

기본 군은 seed 01에서 필드의 `−3`에 해당하는 값, 다른 두 seed에서 3을 찾았다. 피드백 군은 모두 3을 찾았다. **세 번 모두 기본 S+J가 같은 Target 원인을 이미 검출했으므로 J 피드백의 추가 탐지는 0이다.** 정상 입력 1 군의 후보 0은 피드백의 우위를 뜻하지 않는다. 자유 탐색보다 입력을 제한했기 때문이다. 실제 평균 벽시계는 기본 8.586초, 정상 입력 4.344초, 피드백 8.606초다. 동일한 것은 **최대 허용 시간**이며 실제 소비 시간은 다르므로 속도 우위도 주장하지 않는다.

Target 양성 클래스는 3 seed·두 양성 군 모두 `main.target`, Rust 불만족 0, snarkjs `correct`, 최상위 출력 차이 1이다. 같은 J 실행의 `main.probe: unknown/injection_not_applied`는 **다른 호출 위치**의 결과라 Target 양성으로 세지 않았다. [독립 O0 재검사](../runs/j-feedback-2026-10-28/computed-seed1/o0-audit/receipt.json)는 seed 01의 원본 O0 R1CS SHA `cb9f7ee8…`에 대해 정상 입력 1·3과 Probe/Target 이탈 witness를 생성하여 전부 snarkjs 원본 검사에 통과시켰다. 나머지 두 seed는 J의 원본 검사 영수증만 확인했다.

재현: `python3 scripts/j_feedback_proto_20261028.py --output runs/j-feedback-2026-10-28/<새폴더> --cap 30 --target-form square --probe-offset 2 --seed 2026102801`. 출력 폴더가 이미 있으면 덮어쓰지 않고 중단한다. [seed 01](../runs/j-feedback-2026-10-28/computed-seed1/receipt.json) SHA `10e78e97…`, [02](../runs/j-feedback-2026-10-28/computed-seed2/receipt.json) `38c37f9a…`, [03](../runs/j-feedback-2026-10-28/computed-seed3/receipt.json) `1570dced…`. 이후 오류 처리만 강화한 최종 실행기(SHA `ca770827…`)의 [seed 01 재실행](../runs/j-feedback-2026-10-28/computed-final-v2-seed1/receipt.json)(SHA `0b3fd0e8…`)도 세 판정이 같았다. 고정 J SHA는 `05649971…`이다. `nice -n 19`는 실행했지만 이 샌드박스의 setpriority 권한이 없어 우선순위 변경은 적용되지 않았다.

## 스스로 반박한 결론과 대형 회로 관문

이 합성 회로는 7제약이며 Target 조건도 소스에 보인다. J가 `5 → 3`을 합성했다는 구현 증거는 남지만, 이 toy로 “대형 회로에서 더 찾는다”거나 “ScaleCirc를 넘었다”고 추론할 수 없다. 상수 고정 래퍼는 원래 조각보다 입력 공간을 좁힌다. 자유 탐색이 동일 원인을 찾았으므로 더 정교한 toy를 사후 제작해 양성을 얻어도 방법 근거가 약하다. **여기서 toy 튜닝을 멈춘다.**

대형 회로의 강점은 별도 [A inference 원본 동일 입력 O0 반례 쌍과 W 연장 관측](n5_next_gate_2026-10-28.md)에 이미 있다. 그러나 그 A 회로는 결과를 본 뒤 골랐고, S+J 시간은 준비·검토를 뺀 하한이다. 다음 판단은 (1) **고정 N5의 대형 A/B 대상**에서 전체 W와 S+J의 완전한 총비용·검증된 고유 원인·미판정 분모를 맞추고, (2) J 피드백을 재시험한다면 **사전 선정 A의 계산된 입력 호출 집합**에서 실제 원본에 도달하는 추가 원인을 정상 벡터 동일 개수 군과 비교하는 것이다. 대형 원본에서 추가 양성 0이면 seed 되먹임을 논문 방법 기여로 내세우지 않는다. 독립 B는 개발·튜닝에 쓰지 않는다.

기존 반론 중 “현실적인 벡터 자체의 효과와 J 라벨의 효과를 분리하라”는 점은 여전히 유효하다. 전달할 질문은 다음과 같다: **“J가 계산된 부품 입력 5에서 최상위 입력 3을 합성한 합성 시험을 구현했지만, 동일 30초 상한 3 seed에서 자유 S+J도 같은 Target 원인을 모두 찾았다. 이때 피드백을 계속 개발할 실증 관문이 있는가? 단순 seed·CEGAR·ScaleCirc 전파와 구별되는 정보를 원본의 큰 회로에서 무엇으로 측정해야 하는가?”**

검사: `python3 -m py_compile`, `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` 통과. Rust 변경은 없다.

**확인한 것:** J의 `synthesized_a` 입력 3, 고정 래퍼의 정확한 입력 3, 세 seed의 Target 원본 판정과 시간, seed 01의 독립 O0 검사, 추가 고유 원인 0. **추정한 것:** 대형 A/B에서 피드백의 효과와 ScaleCirc 대비 차이. 현재는 미검증이다.
