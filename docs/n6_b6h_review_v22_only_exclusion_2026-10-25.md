# B6h 사람 검토 자료: v2.2에서만 나온 배제 1클래스 (2026-10-25)

상태: 검토 자료(판정 아님). 담당: miiz·리드. 근거: N5 개정 4절 3항. 후보 값과 witness 값은 적지 않는다. 내부 기록이며 발표·공유 자료에는 4절 4항에 따라 프로젝트 이름을 쓰지 않는다.

## 대상

| 항목 | 값 |
|---|---|
| 리비전 | `4c221df7` (panther-core `0b078c83`, main `circuits/circuits/mainZAccountRenewalV1.circom`, 분류표 기준 배포) |
| 요청 | queue_order 25, `j3-main-4c221df76273c0d7cf18048c-seed-2026100601-S-a0091-c001` |
| 클래스 | 6번, 패턴 `main.BabyJubJubSubGroupPointTag_198_9493.eMul.m2e[*]`, 대표 `...eMul.m2e[0]`, 사이트 1 |
| 후보 성격 | TCCT 이탈(`tcct_deviation`). 컴포넌트에서 이탈 신호 1개(hint 신호). 다시 쓴 문장은 circomlib `Montgomery2Edwards`(`node_modules/circomlib/circuits/montgomery.circom:53`)의 `out` |
| v2.2 결과 | `excluded_in_context`, reason `closed_cone_unsat`. 결과 파일 `runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/main/0004/requests/000025/attempt-0001/result.json` |
| v1 결과 | `unknown`, reason `budget_exhausted`. 결과 파일 `runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/main/0004/requests/000025/attempt-0001/result.json` |

## 증명 종류

- 종류: 닫힌 원뿔 z3 unsat(`exclusion_basis = o0_closed_cone`, `exclusion_method = z3+propagation`).
- 범위: entrypoint O0 R1CS의 제약 62개, 미지 wire 69개(joint cone).
  - 제약 번호: 17637–17642, 17655–17660, 18398–18399, 21920–21921, 21928–21929, 21937–21938, 21953–21958, 22477–22482, 22484–22487, 22491–22492, 22495–22498, 22505–22506, 22508–22513, 24986–24997.
- 고정한 값: 후보가 정하는 사이트 신호 4개뿐이다. `eMul.m2e[0].in[0]`, `in[1]`, `out[0]`, `out[1]`. 사이트 입력 둘은 entrypoint 입력에 직접 묶이지 않은 중간 신호다(`kind = intermediate`). 기준 입력 값은 고정하지 않는다.
- 의미: 이 entrypoint의 어떤 witness도 m2e[0]에서 후보의 입·출력 값을 가질 수 없다는 증명이다(O0 R1CS 기준). 정의와 근거는 고정 v2.2 소스 `lifting/mod.rs:2782-2840`이다.
- 재확인 방법: 위 제약 62개를 O0 R1CS에서 꺼내고, 고정값 4개를 넣어 z3로 다시 푼다. 원래 smt2 파일은 요청별 작업 폴더 정리로 지워졌다.

## 관련 템플릿과 신호

- 프로젝트 템플릿: `circuits/circuits/templates/utils.circom:943-975` `BabyJubJubSubGroupPointTag(isActive)`.
  - `BabyCheck`로 점이 곡선 위에 있는지 확인한다.
  - 부분군 위수를 `Num2Bits(253)`로 비트 분해하고 `EscalarMulAny(253)`로 스칼라 곱을 한다.
  - `eMul.out[0] === 0`, `eMul.out[1] === 1`(항등원)을 강제한다.
- 이탈 지점: circomlib `EscalarMulAny` 안의 `m2e[0]`(`Montgomery2Edwards`). `out`이 `<--`로 계산되고, 나눗셈 분모가 0인 입력에서 제약이 약해지는 것으로 알려진 패턴이다.
- 검토 질문: 원뿔이 포함한 제약(곡선 검사, 이어지는 덧셈 체인, 마지막 항등원 등식)이 후보의 m2e[0] 값을 실제로 막는가? 그리고 O0에서 성립한 증명이 원래 O1 R1CS에도 그대로 적용되는가?

## v1이 unknown인 이유

- 두 엔진의 합성 기록은 같은 원뿔(제약 62, 미지 69)을 만들었다. 합성 a는 1라운드 6회 시도, 경로 6개를 찾았다.
- v1: `b_outcome = propagation_only`, `cause_before_budget = cone_refuted_by_propagation_only`, `sweep_branches = 0`.
  - 값 전파(`refute::refute_subset`)는 이 원뿔에서 모순을 찾았다.
  - 하지만 z3가 20초 안에 unsat을 내지 않아 증명으로 인정하지 않았다(v1 `synth.rs:371-376`: z3 unsat만 `Unsat`, 전파만 성공하면 `PropagationOnly`).
  - 그 뒤 탐색 예산을 다 써서 `budget_exhausted`로 끝났다.
- v2.2: 같은 원뿔에서 z3가 unsat을 냈다(`b_outcome = unsat`, 전파 모순도 함께 기록).
  - 두 엔진의 z3 제한은 같은 20초다(`synth.rs` `SOLVER_TIMEOUT`).
  - v2.2는 z3 호출을 `solver::run`으로 바꿨다(`git diff cb40e3e 8065e2b -- src/candidate_review/lifting/synth.rs`).
  - v1의 z3 출력(timeout인지 unknown인지)은 작업 폴더 정리로 남아 있지 않아 확인할 수 없다.
- 해석: 두 엔진 모두 같은 원뿔에서 전파 모순을 찾았다. 차이는 z3가 시간 안에 unsat을 확인했는지뿐이다. 판정 충돌(L1 대 배제)은 아니다.
