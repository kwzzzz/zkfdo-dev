# J 시간 프로파일 — 2026-11-03

1부 측정 기록. 최초 집계는 Rust 코드 변경·J 재실행 전에 기존 **A inference 개발 자료**만 읽었다. 사용자 정정 후 외부 반박 검토(로컬 `runs/` 보관 기록)를 대조한 기록 보완까지는 기존 JSON·코드·개발 메타데이터만 읽었다. 이후 아래 **추가 실측**은 별도 계측판으로 실행했으며 역사 기록의 소급 분해와 구분한다. N5 held-out 접근·실행은 없다. 기존 판정·프로토콜·캐시는 수정하지 않았다. 집계기는 `scripts/j_time_profile_20261103.py`, 최초 근거 `runs/j-speed-2026-11-03/profile/profile.json`은 보존했고 보완 근거는 `runs/j-speed-2026-11-03/profile-v2/profile.json`이다.

## 최우선 항목: ledger 밖 606.404초(28.54%)

완료 J 12건의 **wall 2,124.988604초 − ledger 1,518.585068초 = 606.403536초**다. 이 차이가 첫 번째 프로파일링 대상이다. `not_reached`나 `inconclusive`보다 먼저 미계측 작업의 범위를 나누어야 한다. 기존 기록으로 **요청별 차이는 정확히 계산할 수 있지만, 이 606.404초를 세부 작업별 초로 분배할 수는 없다.** 추가 timer 없이 추정치를 측정값처럼 쓰지 않는다.

| 요청 | ledger 밖 초 | 해당 요청 wall 대비 | 남은 repair 기록 / solve 기록 수 |
|---|---:|---:|---:|
| 2026100601/judgements/0 | 42.221579 | 24.49% | 3 / 7 |
| 2026100602/judgements/0 | 85.280880 | 25.07% | 3 / 30 |
| 2026100602/judgements/1 | 131.581339 | 35.37% | 5 / 60 |
| 2026100603/judgements/0 | 45.426452 | 46.28% | 2 / 9 |
| 2026100601/replay/replay | 0.409604 | 87.95% | 0 / 0 |
| 2026100601/replay/replay-0 | 결과 없음 | 산정 불가 | 산정 불가 |
| 2026100601/replay/replay-1 | 0.409273 | 85.58% | 0 / 0 |
| 2026100601/replay/replay-2 | 0.409776 | 85.97% | 0 / 0 |
| 2026100601/replay/replay-3 | 0.409142 | 84.65% | 0 / 0 |
| 2026100601/replay/replay-4 | 결과 없음 | 산정 불가 | 산정 불가 |
| 2026100601/replay/replay-5 | 183.844238 | 21.32% | 3 / 78 |
| 2026100602/replay/replay-0 | 0.407715 | 84.08% | 0 / 0 |
| 2026100602/replay/replay-1 | 0.410410 | 85.69% | 0 / 0 |
| 2026100603/replay/replay-0 | 115.593127 | 41.73% | 3 / 28 |

원본 judgements 4건은 304.510251초, replay 8완료 건은 301.893285초가 ledger 밖이다. 표의 repair는 `synthesis.repair`에 남은 **19개 수리 기록·212개 SolveRecord**이며 시간이나 독립 사례 수가 아니다. hint injection 안의 solve는 별도로 207개이며 해당 주입의 잔여 timer에 포함될 수 있어 미계측 시간에 더하지 않는다. 실제 계산 전 오류·누락·덮어쓴 기록까지 포함한 모든 호출의 완전한 수라고 주장하지 않는다.

아래 줄 번호는 변경 전 작업 트리 사본 `runs/j-speed-2026-11-03/source-before/{mod,repair}.rs` 기준이다. 이 사본은 10-29 바이너리의 완전한 소스 재현본이라는 뜻은 아니며, 현재 최적화 변경과 구분해 timer 범위를 확인하는 근거로 사용했다.

| 단계 후보 | timer가 놓치는 작업의 코드 근거 | 역사 기록에서 분리 가능한 시간 |
|---|---|---|
| 요청 준비 | `mod.rs:396–425`: wall 시작 뒤 request 파싱·실행파일 해석·도구 3개 SHA 계산, ledger 생성은 그 뒤. 12요청에 도구 해시 확인 36회 | 미상. 준비 조기 종료 6건의 차이 합 2.456초도 해시만의 비용으로 단정 불가 |
| hinted 원본 동일성 | `mod.rs:936–947`: compile timer 밖 R1CS·SYM 전체 읽기/바이트 비교와 SYM 동등성 검사 | 미상 |
| 수리·반례 generator 동일성 | `repair.rs:1298–1316,1343–1351`: 매 variant/comparator의 R1CS 전체 읽기·SYM 읽기/분해/동등성 | 미상. mapping 256.724초와 다른 호출이므로 그 시간으로 대체 불가 |
| 수리 원뿔 구성·Z3·모델 적용 | `repair.rs:1765–1936`의 `solve_region/run_z3`는 개별 ledger timer 없음. 호출부 `mod.rs:2200,3384`도 enclosing remainder 없음 | 미상. 반면 `mod.rs:3256–3274`의 hint injection 경로는 enclosing remainder가 있으므로 내부 작업을 밖 비용에 중복 포함하면 안 됨 |
| 컴파일 준비·workspace | `repair.rs:2184–2234`: cache key·디렉터리 정리·source/library 복사 후 compiler 호출. compiler timer는 `mod.rs:3720–3742`의 subprocess만 포함 | 미상. 최상위 `write hint workspace` ledger 행은 이미 계측됐으므로 제외 |
| witness 읽기·파싱 | `mod.rs:3956–3966`: generator 실행 시간을 기록한 **후** `read_wtns` 호출 | 미상. enclosing timer가 있는 호출에서는 이미 상위 잔여에 포함될 수 있음 |
| 나머지 준비·자료구조 해제 | source 텍스트 처리·입력/증거 I/O·객체 정리 등 개별 timer 없는 코드 | 미상. 이름만 붙인 잔여를 원인별 실측으로 쓰지 않음 |

`mod.rs:504–514`에서 wall을 확정한 뒤 최종 JSON 직렬화·쓰기를 한다. **그 출력 쓰기 시간은 위 606.404초에 포함되지 않는다.** 새 외부 wall/CPU에는 포함해야 한다. 반대로 O0 artifact parse 22.080초와 diagnostic mapping 256.724초는 이미 ledger에 있으므로 이 차이와 더해 별도 병목으로 세는 방식은 가능하나, 차이의 원인으로 재분류하면 중복이다.

후속 계측은 위 항목을 각각 구분하고 상위/하위 timer 중복을 제거해야 한다. 현재 자료로 특정 작업이 606초 대부분이라는 결론이나 제거 가능한 시간이라는 결론은 낼 수 없다.

## 범위와 시간

`runs/n7-a-sj-cold-2026-10-29-v2` 세 seed의 judgements와 replay에서 저장 요청 **14건**, 완료 `result.json` **12건**을 찾았다. seed 01의 `replay-0`, `replay-4`는 결과가 없으므로 시간 분모에 넣지 않는다. 모든 요청의 참조 파일·라이브러리 경로는 현재 존재한다. 고정 리비전 replay 및 준비 실패도 그대로 포함한다.

| seed / 요청 | J wall (초) | ledger 합 (초) | not_reached·inconclusive·timeout (초) | O0 파싱 횟수 / 초 | diagnostic mapping 횟수 / 초 |
|---|---:|---:|---:|---:|---:|
| 2026100601/judgements/0 | 172.388 | 130.166 | 57.079 | 1 / 2.430 | 6 / 12.870 |
| 2026100602/judgements/0 | 340.144 | 254.863 | 121.711 | 1 / 2.316 | 18 / 50.072 |
| 2026100602/judgements/1 | 371.969 | 240.388 | 112.118 | 1 / 2.407 | 19 / 44.567 |
| 2026100603/judgements/0 | 98.161 | 52.734 | 13.484 | 1 / 2.246 | 3 / 6.231 |
| 2026100601/replay/replay | 0.466 | 0.056 | 0.000 | 0 / 0.000 | 0 / 0.000 |
| 2026100601/replay/replay-0 | 결과 없음 | — | — | — | — |
| 2026100601/replay/replay-1 | 0.478 | 0.069 | 0.000 | 0 / 0.000 | 0 / 0.000 |
| 2026100601/replay/replay-2 | 0.477 | 0.067 | 0.000 | 0 / 0.000 | 0 / 0.000 |
| 2026100601/replay/replay-3 | 0.483 | 0.074 | 0.000 | 0 / 0.000 | 0 / 0.000 |
| 2026100601/replay/replay-4 | 결과 없음 | — | — | — | — |
| 2026100601/replay/replay-5 | 862.468 | 678.624 | 420.252 | 1 / 6.405 | 13 / 93.977 |
| 2026100602/replay/replay-0 | 0.485 | 0.077 | 0.000 | 0 / 0.000 | 0 / 0.000 |
| 2026100602/replay/replay-1 | 0.479 | 0.069 | 0.000 | 0 / 0.000 | 0 / 0.000 |
| 2026100603/replay/replay-0 | 276.991 | 161.398 | 23.954 | 1 / 6.275 | 7 / 49.007 |

전체 J wall은 **2,124.989초**, ledger는 **1,518.585초**다. ledger 미포착 구간 606.404초를 임의로 전략에 배분하지 않았다. 명시된 세 실패 상태의 합은 748.599초(**wall의 35.23%**). 이 중 synthesis_b는 747.429초다. `z3 exclusion sweep`은 상한 소진도 ledger에 `done`으로 쓰므로, 클래스의 `sweep_end=time_exhausted`와 연결한 99.776초를 추가하면 848.375초(**39.92%**)다. synthesis_b만 같은 방식으로 계산하면 847.205초(**39.87%**). `small closed cone proposal/time_exhausted` 3회는 이미 남은 예산 0인 호출로 합 0.000002초다. 반올림에 영향은 없다.

`Ledger::record_remainder`(`src/candidate_review/lifting/mod.rs:334`)는 내포된 단계 시간을 빼므로 `hint injection/not_reached` 638.301초는 **주입 전체 시간이 아닌 잔여 시간**이다. 아래 표는 저장 ledger를 그대로 합쳤으며 이 잔여값과 하위단계를 중복 계상하지 않는다. 실패한 전체 주입의 포괄 비용은 이 값보다 크다.

## 미판정 원인: 표면 reason과 선행 실패를 구분

분모는 완료 결과 12개에 실린 **클래스 31개**다(원본 4요청 21클래스 + 본 판정까지 진행한 fixed replay 2요청 10클래스). 나머지 6완료 요청은 준비 실패/조기 중단으로 클래스가 0이며, 결과 없는 2요청은 포함하지 않는다. 원본·fixed replay를 독립 탐지 성과로 합산하지 않는다.

| 클래스 verdict / 원문 reason | 클래스 수 | cause_before_budget |
|---|---:|---|
| entrypoint_violation / output_differs | 4 | null |
| excluded_in_context / constant_input_mismatch | 11 | null |
| excluded_in_context / closed_cone_unsat | 1 | null |
| compatible_no_top_violation_observed / outputs_equal | 1 | null |
| unknown / budget_exhausted | 8 | **8개 모두 abort_on_constraint_unresolved** |
| unknown / deviated_generation_aborted | 6 | null |

`unknown`은 14/31(45.16%), `budget_exhausted`는 8/31(25.81%)이지만 **그 8개는 단순 CPU 시간 부족이라는 뜻이 아니다.** 기록된 `cause_before_budget=synthesis_timeout`은 0개다. `b_outcome`은 model_not_reproduced 5, cone_too_large 3, sweep_unsat 1, null 22다. `model_comparison_missing=true`는 6개다. 주입 기록 6개는 iteration_limit 4·error 2이고 수리 기록 19개는 reached 5·iteration_limit 10·no_progress 3·error 1이다. 단계별 상태는 겹칠 수 있어 이를 새로운 클래스 수처럼 더하지 않는다.

변경 전 사본 `mod.rs:3355–3403`은 선행 cause를 정한 뒤 budget이 소진되면 `cause_before_budget`를 저장하고 표면 reason을 `budget_exhausted`로 바꾼다. 따라서 timeout을 줄였다는 사실만으로 기존 의미 문제·모델 미재현·수리 반복 상한이 해결됐다고 해석하지 않는다.

### j-dev는 선택된 개발 사본

`runs/j-dev-2026-10-27/classes-v1.json`의 scope와 `build_dev.py:31–33,67–78,104,129–143`을 대조했다. **aq v3_1/v3_2 완료 기록에서 aq-024를 제외하고 unknown·local_constraint_refutation 클래스를 고른 메타데이터 및 파일 사본**이다. 신규 엔진 실행이 아니다. 원래 aq 결과·후보 경로는 문자열로만 집계했으며 원본 데이터에 재접근하거나 실행하지 않았다.

현재 선택 메타데이터는 source result 경로/요청 해시 각 **39개**, 클래스 **957개**(unknown 783 + local_constraint_refutation 174), 그중 사례 사본 **127개**다. 이 127은 신규 요청 실행 127회가 아니다. classes의 표면 reason은 budget_exhausted 710·local_constraint_refutation 174·injection_not_applied 42·synthesis_model_not_reproduced 18·synthesis_timeout 13이다. 선행 cause는 synthesis_timeout 493·cone_refuted_by_propagation_only 127·synthesis_model_not_reproduced 90·null 247이다. 이 선택 집합의 unknown 비율을 전체 aq/J 실패율이나 cold 31클래스와 직접 비교하지 않는다.

`docs/j_boost_step2_2026-10-27.md:41–60`의 957/127 및 원인 수와 일치했다. classes-v1 및 case index SHA와 내장된 aq v3_1/v3_2 출처 SHA는 profile-v2 JSON에 보존했다. 전체 aq 원본의 재집계나 독립 성능 검증을 한 것은 아니다.

## 20초 상한과 실행 순서

이 절의 `mod.rs` 줄 번호는 `runs/j-speed-2026-11-03/source-before/mod.rs` 기준이다. `synth.rs`는 최종 코드에서 줄 번호를 다시 확인한 `runs/j-speed-2026-11-03/source-final-v1/src/candidate_review/lifting/synth.rs` 기준이며, 계측 scope만 추가됐고 아래 상한과 예산 규칙은 바뀌지 않았다.

- `synth.rs:41–45`: joint solver 20초, sweep branch 5초, **후보 전체(모든 site 공유) sweep 20초**. `mod.rs:1035`에서 후보 예산을 초기화한다. `mod.rs:3074–3087`의 small proposal도 같은 예산에서 차감한다.
- `synth.rs:477–499`: 남은 시간 0이면 exhausted, branch에 `min(5초, remaining)`을 전달한다(최소 100ms 및 루프 비용 때문에 엄밀한 20.000초 종료 보장은 아님). `mod.rs:3315–3343`에서 남은 예산 차감·종료 이유 기록.
- sweep 9호출 중 **8회 time_exhausted**: 실제 약 20초 소비 5회(19.911–19.999초), 이미 예산이 0인 후속 site 3회. 나머지 1회는 seed 03 judgement의 0.186초 proof_found다. seed 01의 19.998534초는 상한 소진이 맞다.
- 순서: bit 범위 전파(`mod.rs:2986–3071`) → joint cone 구성 또는 small proposal(`3074–3110`) → joint Z3 또는 small 결과 사용(`3113–3160`) → 모델의 최상위 입력 적용·witness 재생(`3186–3215`) → hint injection/repair(`3217–3300`) → exclusion sweep(`3312–3355`). 범위 모순, cone UNSAT, 재생 도달, 주입 도달이면 즉시 반환해 뒤 전략을 건너뛴다.
- 각 전략은 완전히 독립이 아니다. small proposal과 sweep이 예산을 공유하고, hint injection은 선행 모델·trial·override를 사용한다. 병렬 옵션은 이 의존성 및 우선순위·예산 소비를 보존해야 한다.

## O0 재파싱 가설 확인

**동일 O0 R1CS를 diagnostic mapping마다 다시 파싱한다는 가설은 코드와 맞지 않는다.** 원본 O0는 준비가 성공한 6요청에서 요청당 1회, 총 22.080초 파싱됐다. timer는 R1CS와 SYM 읽기·파싱을 합친 값이며 순수 R1CS 파싱 시간을 따로 분리할 수 없다. original 4요청은 회당 2.246–2.430초, fixed replay 2요청은 6.275–6.405초다. O1은 따로 요청당 1회, component는 완료 기록 12건에서 각각 1회 읽는다(`mod.rs:585, 830–838, 1144–1147`).

`repair.rs:1424–1446`의 mapping은 이미 파싱한 `self.view.r1cs`를 사용한다. 반복하는 것은 양쪽 SYM 텍스트 읽기와 `sym_equivalence`, 원본 O0 전체 제약 평가, 실패 인스턴스 묶기다. `sym_equivalence`(`repair.rs:2265`)는 매 줄·신호 경로를 다시 분해한다. 66회 합 **256.724초**, seed 01 judgement는 6회 12.870초(회당 1.965–2.305초). 이 timer만으로 SYM 검사와 제약 평가의 비용을 나눌 수는 없다. 이번 원본 O0 파일은 SHA `7efa0199e5da19cbdb1ca503ff35fbaaed69d8757d79a96fe159096ac44880c5`, **50,161,856 bytes(47.84 MiB)**다. 더 큰 fixed replay와 구분한다.

따라서 최신 사용자 조건에 맞춘 개선 후보는 **매번 SYM 전체를 읽고 모든 행을 비교하되, 같은 행의 불필요한 토큰 분해를 줄이는 것**과 **원본 전체 제약의 정확한 모듈러 산술을 빠르게 계산하는 것**이다. SYM 비교나 원본 전체 제약 검사는 생략하지 않으며, 판정 간·요청 내부의 비교 결과 캐시로 대체하지 않는다.

## seed 01의 컴파일 32행 확인

compile 단계 32행은 **컴파일 요청 31회 + `write hint workspace` 1회**다. 실제 compiler 실행 21회, cache hit 10회다. 실제 실행은 component 1 + original O0/O1 2 + 수정본 18회다. 수정본 18개 R1CS를 직접 SHA-256으로 비교했다.

| 수정 산출물 | 실제 컴파일 | 같은 R1CS cache hit | 합계 호출 |
|---|---:|---:|---:|
| 원본 O0와 동일(힌트 등 generator 수정) | 8 | 9 | 17 |
| 원본 O1과 동일 | 5 | 0 | 5 |
| 원본과 다른 diagnostic 제약 삭제본 | 5 | 1 | 6 |
| 수정본 합 | 18 | 10 | 28 |

즉 원본과 같은 R1CS인 수정 호출은 **22회(실제 컴파일 13회 + cache hit 9회)**다. 여기에 원본 자체 2회와 component 1회를 더하면 31회다. cache hit는 ledger의 search/diagnostic 순서로 round 0(주입 generator와 같은 소스)과 이후 check-blanking round를 구분했다. 7개 diagnostic hit 중 6개는 round 0, 1개는 이전에 만든 check-blanking 사본이다. R1CS 해시 일치만으로 임의 소스 수정의 안전성을 일반화하지 않으며 wasm만 컴파일하는 새 경로는 수정 유형과 SYM 매핑도 보증해야 한다.

모든 artifact 경로·바이트 수·해시와 요청/결과 해시는 상세 JSON에 남겼다. 원본 O1 R1CS는 `39022971e46a6ea30c548f9c7a0b4f0298a71b1c1f798c19304d9b9e61917220`이다. 기존 캐시를 새 arm이나 seed에 넘기지 않는다.

## 단계 × label × status 합계

단위 초. 원문 label·status를 보존한다. 횟수에는 cache hit와 0초 호출도 포함된다.

| 단계 | label | status | 횟수 | 초 | cache hit |
|---|---|---|---:|---:|---:|
| check | local refutation | inconclusive | 6 | 1.170057 | 0 |
| check | rust r1cs evaluation | ok | 5 | 2.051845 | 0 |
| check | snarkjs wtns check | correct | 5 | 5.027692 | 0 |
| compile | compile circuit.circom | ok | 6 | 15.445406 | 0 |
| compile | compile circuit.circom --O0 | ok | 6 | 8.819665 | 0 |
| compile | compile comparator generator | ok | 5 | 7.976300 | 0 |
| compile | compile diagnostic copy --O0 | ok | 85 | 122.116485 | 0 |
| compile | compile diagnostic copy --O0 (cache hit) | ok | 81 | 0.000000 | 81 |
| compile | compile hinted entrypoint | ok | 6 | 15.935057 | 0 |
| compile | compile hinted entrypoint --O0 | ok | 1 | 1.032210 | 0 |
| compile | compile hinted entrypoint --O0 (cache hit) | ok | 5 | 0.000000 | 5 |
| compile | compile injected generator | ok | 5 | 7.951524 | 0 |
| compile | compile injected generator --O0 | ok | 62 | 87.054303 | 0 |
| compile | compile injected generator --O0 (cache hit) | ok | 16 | 0.000000 | 16 |
| compile | compile target.circom --O0 | ok | 12 | 0.172190 | 0 |
| compile | write hint workspace | ok | 6 | 0.174953 | 0 |
| repair | diagnostic witness | aborted | 59 | 3.357847 | 0 |
| repair | diagnostic witness | ok | 44 | 24.243336 | 0 |
| repair | index O0 constraints | ok | 5 | 2.375833 | 0 |
| repair | index signal roles | ok | 5 | 7.450415 | 0 |
| repair | map diagnostic witness onto the original O0 R1CS | ok | 44 | 170.482602 | 0 |
| repair | search O0 witness | aborted | 45 | 2.658436 | 0 |
| repair | search O0 witness | ok | 7 | 2.149557 | 0 |
| site_discovery | bind site inputs | ok | 31 | 0.000659 | 0 |
| site_discovery | component deviation | ok | 12 | 0.000869 | 0 |
| site_discovery | component honest witness | ok | 12 | 0.585123 | 0 |
| site_discovery | enumerate call sites | ok | 6 | 0.274175 | 0 |
| site_discovery | group site classes | ok | 6 | 0.043317 | 0 |
| site_discovery | index equality bindings | ok | 6 | 12.249676 | 0 |
| site_discovery | index original equalities | ok | 6 | 5.430406 | 0 |
| site_discovery | parse component artifacts | ok | 12 | 0.004032 | 0 |
| site_discovery | parse entrypoint O0 artifacts | ok | 6 | 22.080032 | 0 |
| site_discovery | parse entrypoint artifacts | ok | 6 | 19.170270 | 0 |
| site_discovery | plan hint rewrites | failed | 6 | 0.000649 | 0 |
| site_discovery | plan hint rewrites | ok | 6 | 0.000478 | 0 |
| site_discovery | source closure | ok | 12 | 0.062363 | 0 |
| synthesis_a | find constraint paths | ok | 2 | 0.000191 | 0 |
| synthesis_a | index O0 constraints | ok | 1 | 0.299183 | 0 |
| synthesis_a | synthesis hinted O0 witness (honest aborted) | aborted | 10 | 0.546729 | 0 |
| synthesis_a | synthesis honest O0 witness | aborted | 10 | 0.574212 | 0 |
| synthesis_a | synthesis honest O0 witness | ok | 3 | 0.502970 | 0 |
| synthesis_b | bit-decomposition range propagation | inconclusive | 9 | 109.127774 | 0 |
| synthesis_b | diagnostic witness | aborted | 41 | 2.608796 | 0 |
| synthesis_b | diagnostic witness | ok | 22 | 22.184336 | 0 |
| synthesis_b | hint injection | not_reached | 6 | 638.301055 | 0 |
| synthesis_b | index signal roles | ok | 1 | 0.933100 | 0 |
| synthesis_b | map diagnostic witness onto the original O0 R1CS | ok | 22 | 86.240931 | 0 |
| synthesis_b | search O0 witness | aborted | 24 | 1.526312 | 0 |
| synthesis_b | search O0 witness | ok | 2 | 0.952014 | 0 |
| synthesis_b | small closed cone proposal | finished | 6 | 0.610986 | 0 |
| synthesis_b | small closed cone proposal | time_exhausted | 3 | 0.000002 | 0 |
| synthesis_b | synthesis hinted O0 witness (honest aborted) | aborted | 6 | 0.331100 | 0 |
| synthesis_b | synthesis honest O0 witness | aborted | 6 | 0.308607 | 0 |
| synthesis_b | z3 exclusion sweep | done | 9 | 99.961316 | 0 |
| synthesis_b | z3 joint closed cone | done | 6 | 0.000002 | 0 |
| witness | entrypoint deviated O0 witness | ok | 1 | 0.221138 | 0 |
| witness | entrypoint deviated witness | aborted | 11 | 0.604435 | 0 |
| witness | entrypoint honest witness | aborted | 2 | 0.205103 | 0 |
| witness | entrypoint honest witness | ok | 9 | 2.273652 | 0 |
| witness | repaired comparator witness | ok | 5 | 1.378904 | 0 |
| witness | repaired deviated witness | ok | 5 | 1.344457 | 0 |

## 재검증 입력과 기준 도구

기준 바이너리: `runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development`, 고정 SHA-256 `05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700`. 기존 실행기는 `scripts/n7_a_sj_cold_e2e_20261029.py:273–278`의 명령을 사용했다. 도구는 `/Users/miiz/.cargo/bin/circom`, `/opt/homebrew/bin/node`, `/opt/homebrew/bin/snarkjs`, `/opt/homebrew/bin/z3`다. 12완료 요청 1 arm의 기존 wall 합은 약 35.4분이므로 3 arm은 기존 속도 기준 약 106분이며, 결과 없는 2요청의 비용은 여기에 포함되지 않았다. 재실행은 개별 요청·arm별 빈 캐시와 별도 출력에서 순차 수행해야 한다.

이 집계는 최적화의 개발 근거다. 성능 개선이나 W 대비 동일 총비용 우위의 검증 결과가 아니다.

최초 JSON SHA-256: `e1576abf6f3a3b7d632f1481d76dd8f712e1cf055d392b0cec7448b8ed4a812c`. 보완 profile-v2 JSON SHA-256: `a616e44e5bfce841ddf2826b32bb3d2ca5edb6fa3c0352be14142d8d2d1cbcbc`.

## 추가 실측 1 — legacy 계측 전용, seed 01 judgement 0

2026-11-03 20:24–20:27 KST에 root 작업에서 실행한 첫 요청의 `--profile-only` 결과를 읽었다. 실행 경로는 `runs/j-speed-2026-11-03/profile-runtime-v1/requests/00/profile/`이고 모드는 `legacy_measurement_only`다. 기존 12결과를 대체하지 않으며, 최적화의 속도 개선 시험도 아니다.

외부 실행기의 monotonic 경과 **174.160488초**, wait4 CPU **170.609220초**. 엔진 wall 174.059690초, 기존 형식 ledger 130.898713초, 차이 **43.160977초**다. 과거 동일 요청과 판정·클래스·witness 검사뿐 아니라 전략·증거 해시를 포함한 비교도 `semantic_equal=true`, `basis_equal=true`였고 입력 snapshot은 실행 전후 같았다. 이는 **이 요청 1건의 계측 재현 확인**이다.

새 timer가 분리한 diagnostic mapping 6회의 구성은 다음과 같다. 이 표 안에서는 서로 겹치지 않도록 중첩 작업의 inclusive 값을 사용했다.

| mapping 구성 | 초 |
|---|---:|
| SYM 동등성 | 9.289453 |
| 원본 전체 제약 검사 | 3.653361 |
| SYM 읽기 | 0.047390 |
| 실패 인스턴스 묶기 | 0.033149 |
| 그 밖의 mapping 제어 | 0.000126 |
| mapping 전체 6회 | **13.023479** |

전체 요청의 별도 주요 timer는 아래와 같다. 이 표는 각 label의 **exclusive** 시간이며, 위 mapping 표와는 교차 중복이 있으므로 두 표를 더하지 않는다.

| label | 호출 수 | exclusive 초 |
|---|---:|---:|
| solver.subprocess | 229 | 42.748437 |
| sym.full_comparison | 21 | 35.312352 |
| compile_process | 21 | 22.795784 |
| file_hash | 76 | 19.529619 |
| repair.plan_rewrites | 16 | 14.969548 |
| wtns_read_parse | 17 | 3.212544 |
| workspace_copy | 18 | 0.680542 |
| r1cs_bytes_read_compare | 15 | 0.179428 |

SYM 전체 비교 21회 35.312초 중 mapping 내부는 9.289초다. 나머지 26.023초를 곧바로 ledger 밖 시간이라고 부를 수는 없다. hint injection 등의 상위 remainder에 포함된 호출도 있기 때문이다. 같은 이유로 파일 해시 19.530초나 rewrite 계획 14.970초를 차이 43.161초에 단순 배분하지 않는다. 이 실측1의 flat label 합계는 작업별 비용을 보여주지만 **기존 ledger와 교차하는 구간의 합집합 정보가 없어 당시 43.161초의 정확한 귀속은 미완료**였다. 아래 실측2는 별도 새 실행에 합집합 계측을 추가한 결과다. 이 새 관측으로 과거 606.404초를 소급 분배하지 않는다.

mapping에는 R1CS 재파싱이 없다. 이 요청에서는 SYM 동등성 검사 9.289초가 전체 제약 평가 3.653초보다 컸음을 실측으로 구분했다. 전체 SYM 비교와 전체 제약 검증을 매번 수행하면서, 같은 SYM 행의 토큰 분해와 정확한 제약 산술의 계산 비용을 줄일 개발 근거가 된다.

근거 해시: `out/j-profile.json` **f5ab8524f154edc8526e77bee749e869e8ea535b0de06c2291a4d1a14830bc73**, `record.json` **7d9d9b8e212250ce6a35366cdbf62f79d6289732a57d1fabb521d798e51d05cb**, `out/result.json` **95107e7a62830fe3996f7feed4203a6480200e26f8d9d691e46b13e8222c49a6**. 계측 바이너리 SHA **b31750531710e3b7f255f7aaeb926e943625b97c6cf921fd593ea9ef6f22f4dc**. 이 실행의 원기록은 보존한다.

## 추가 실측 2 — 새 legacy 구간의 ledger 밖 비용 귀속

2026-11-03 20:42–20:44 KST, 동일한 seed 01 judgement 0을 **계측 전용 legacy 모드**로 다시 실행한 원기록 `runs/j-speed-2026-11-03/profile-runtime-v2/requests/00/profile/`을 분석했다. 실행 전 고정한 바이너리는 `runs/j-speed-2026-11-03/bin/zkfdo-j-v24-v1`이고 SHA-256은 `b40e5439faf1db13e07d2ee35647c8cbb95787864db18a5586991b7986e7a524`다. 이 절은 **새 실행 1건**의 분해이며 과거 12결과의 606.404초를 소급 분해한 결과가 아니다.

외부 monotonic 경과 **172.993700초**, CPU **170.080797초**. 기존 결과와의 `semantic_equal` 및 `basis_equal`은 모두 true이고 입력 snapshot도 유지됐다. 새 계측의 legacy wall은 **172.390745125초**, 기존 형식 ledger 합은 **129.971356331초**로 산술 차이는 **42.419388794초**다. 외부 경과와 legacy wall의 차이는 서로 다른 측정 범위이며, sidecar 작성·계측 집계 등 legacy window 뒤 비용을 포함하므로 최적화 이득으로 세지 않는다.

새 `legacy_coverage`는 enclosing timer와 하위 ledger 구간을 **합집합**으로 합치고 정확한 legacy wall 시작·끝으로 잘라냈다. 덮인 구간은 **129.971357831초**, 덮이지 않은 구간은 **42.419387294초**다. 산술 차이와의 차이는 **1.5µs**이고 label 귀속 잔차는 약 **2.13×10⁻¹⁴초**다. ledger 구간의 끝은 record 호출 시각으로 복원하므로 timer 종료→record 사이 오버헤드만큼 경계 근사가 있다. `coverage_interval_sum_seconds=194.480220289`는 중첩 구간을 합친 값이므로 ledger 합이나 wall로 사용하면 안 된다.

| 이 새 실행의 ledger 밖 작업 | 초 | uncovered 대비 |
|---|---:|---:|
| sym.full_comparison | 15.812840 | 37.28% |
| file_hash | 14.026105 | 33.07% |
| repair.plan_rewrites | 9.152641 | 21.58% |
| wtns_read_parse | 1.596860 | 3.76% |
| solver.subprocess | 0.813849 | 1.92% |
| workspace_copy | 0.320668 | 0.76% |
| artifact_handle_release | 0.283693 | 0.67% |
| r1cs_bytes_read_compare | 0.119766 | 0.28% |
| sym_read | 0.073898 | 0.17% |
| context_cleanup | 0.051533 | 0.12% |
| 나머지 label 합 | 0.167535 | 0.39% |
| 합계 | **42.419387** | **100%** |

상위 세 작업(SYM 비교·파일 해시·rewrite 계획)이 이 새 실행의 ledger 밖 시간 **91.92%**다. 전체 SYM 비교 35.125초 중 ledger 밖은 15.813초이며, 파일 해시 19.447초 중 14.026초, rewrite 계획 14.687초 중 9.153초다. 이처럼 전체 label 시간을 통째로 ledger 밖에 넣으면 중복되며, 실제 Z3 subprocess 42.802초 중 ledger 밖은 0.814초뿐이다.

대표적인 호출 경로도 확인했다. 아래는 `request → lift_impl → preparation_and_unassigned` 공통 앞부분을 생략한 **uncovered path** 값이며, 서로 다른 호출 맥락을 구분한다. 전체 JSON 경로와 나머지 경로는 sidecar에 보존돼 있다.

| 호출 경로 | ledger 밖 초 |
|---|---:|
| `file_hash` | 6.897138 |
| `class_control → repair.search → repair.iterations → repair.variant → repair.variant_invariants → sym.full_comparison` | 6.764450 |
| `class_control → repair.search → repair.iterations → repair.finish → repair.plan_rewrites` | 5.494535 |
| `class_control → repair.search → repair.iterations → repair.finish → repair.comparator_invariants → sym.full_comparison` | 3.834314 |
| `class_control → repair.search → repair.iterations → repair.finish → repair.variant → repair.variant_invariants → sym.full_comparison` | 3.815255 |
| `class_control → repair.search → repair.iterations → repair.plan_rewrites` | 3.658106 |

진단 mapping 6회는 합 13.116153초(SYM 비교 9.372694초, 전체 제약 검사 3.666215초, SYM 읽기 0.043522초, 실패 묶기 0.033362초, 기타 0.000360초)였고 거의 전부 기존 ledger가 덮었다. `mapping.*`를 위 42.419초의 주요 원인으로 다시 넣지 않는다. R1CS 파싱과 원본 전체 제약 확인은 유지하며, 최신 사용자 조건대로 **전체 SYM 비교도 매번 수행한다**. 이 분해는 같은 행의 불필요한 토큰 분해와 정확한 산술 비용을 줄이는 개발 근거이며, 해시·rewrite 계획 시간이 모두 제거 가능하다는 뜻은 아니다.

- `out/j-profile.json` SHA-256: `e546c5ae2072ad1b81ff26028cc89a5b32be87a9e2ae2b6996fa1e10a10bd365`
- `record.json` SHA-256: `3435d49a5b8f3f8b9b764f80d1d63dd08f84210c0936049aee2a38c3df701715`
- `out/result.json` SHA-256: `bc278bfe31b5ecc5abda87c72b00acd27c73800f462a4a6e8bc32a49568fc9d2`
