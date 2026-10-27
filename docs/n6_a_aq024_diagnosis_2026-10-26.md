# aq-024 1단계 진단 (2026-10-26, 읽기 전용)

A 탐색층, v2.2 결과로 진단했다. 판정·실행기·채점기·매핑·채점 규칙은 바꾸지 않았고, nice 19로 읽기만 했다. 후보 값과 witness 값은 열지 않았다.

**정정:** 앞선 보고에서 aq-024의 매핑 버그를 7개라고 했지만, 고정 매핑(`runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json`)에서 aq-024 항목은 **6개**다.

## ① 버그 위치 대 S 후보 위치

### 위치 요청 15건이 실제로 어디를 건드렸나

- 위치 요청은 2145, 2147–2149, 2151, 2153, 2155–2157, 2159, 2161, 2163–2165, 2167이다.
- 15건 모두 매핑 근거가 `wrapper_source_template_parameters`다. 조각 템플릿(circomlib의 `EscalarMulFix`, `Montgomery2Edwards`, `Edwards2Montgomery` 내부 덧셈기·비트 분해 등)이 `main.zTransactionV1.zSwapV1.dataEscrow.dataEscrow` 아래에서도 쓰일 수 있어서 "위치 요청"으로 표시됐다.
- 실제 판정 클래스의 대표 사이트는 여러 곳에 퍼져 있다.
  - `main.zTransactionV1.BabyJubJubSubGroupPointTag…`
  - `…ExternalTagArray`
  - `…dataEscrow.daoDataEscrow.ephemeralPubKeyBuilder…mulFix…`
  - `…dataEscrow.dataEscrow.drv_mG[].mulFix…`
- 즉 S 후보는 버그 템플릿 자체가 아니다. 버그 템플릿이 내부에서 쓰는 범용 circomlib 부품의 위반이다.

### 버그별 대조

| 버그(항목) | 버그 위치(매핑 템플릿·인스턴스) | S 조각 대상 여부(준비 단계) | S 후보·관측 | 위치 관측 결과와 이유 |
|---|---|---|---|---|
| veridise_babyjubjub_suborder_constraints_not_applied | `BabyJubJubSubOrderTag` / `…BabyJubJubSubOrderTagArray_*.p[*]` (22개) | 적격 5개. seed마다 3개를 시작했고 2개는 예산 소진으로 시작하지 못함 | 시작한 대상의 zkFuzz 결과는 모두 후보 없음(seed마다 3회) | **관측 없음.** S가 그 위치에서 반례를 찾지 못했다. 대표 사이트의 `BabyJubJubSubGroupPointTag`는 이름이 비슷한 다른 템플릿이다. → 기타(퍼징 미검출·일부 예산 소진) |
| veridise_blacklist_states_not_representable_in_field | `ZAccountBlackListLeafInclusionProver` / `…zSwapV1.zAccountBlackListInlcusionProver` | **부적격**(2개): "compile-time variable is not supported(`var ACTIVE = Active()`)", "compile-r1cs failed" | 조각 없음 | **관측 없음.** 우리 조각 생성기가 이 템플릿을 조각으로 만들지 못했다. → 기타(S 준비 미지원) |
| veridise_unsafe_num2bits_254_blacklist_leaf | 위와 같은 템플릿·인스턴스 | 위와 같음 | 조각 없음 | **관측 없음.** → 기타(S 준비 미지원) |
| veridise_data_escrow_encrypted_message_wrong_input | `DataEscrowElGamalEncryption` / `…zSwapV1.dataEscrow.dataEscrow` | **부적격**(2개): "`var BASE8[2]` 미지원", "binding/component reassignment" | 그 템플릿 하위의 circomlib 부품 위반이 대표 사이트로 관측됨 | **관측 있음(배제·unknown).** 관측된 것은 버그(잘못된 입력 연결)가 아니라 하위 스칼라 곱 부품의 TCCT 위반이다. 접두사(하위 경로) 규칙상 그 위치의 관측으로 집계됐다. → 접두사 매핑과 버그 정의가 다름 |
| veridise_fortxreward_abstracted_away_in_reward_calc | `RewardsExtended` / `…zSwapV1.rewards` | **부적격**(1개): "compile-time variable is not supported(`var ACTIVE`)" | 조각 없음 | **관측 없음.** → 기타(S 준비 미지원) |
| veridise_zone_id_inclusion_prover_bypass | `ZoneIdInclusionProver` / `…utxoIn/OutZoneIdInclusionProver[*]` (4개) | **부적격**(1개): "binding/component reassignment" | 조각 없음 | **관측 없음.** → 기타(S 준비 미지원) |

근거:

- 준비 결과: `runs/n6-a1b-2026-10-08/units/aq-024-6f6781246415/preparation/prepared-small-first/prepare-6d36fa6b-…/prepared.json`. 대상 975개 중 적격 179개이고, 각 대상의 `exclusion_reasons`가 들어 있다.
- 퍼징 spec: `runs/n6-a2b-2026-10-08.noindex/specs-v4/a/aq-024-…-S-v4.json`
- 퍼징 ledger: `runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/units/aq-024-…-seed-*/runs/*/S/campaign/ledger.json`. 결과 수만 셌다.
- 판정 결과: `aq-exec/state-v3_1.json`이 가리키는 result.json의 클래스 대표 사이트와 판정 필드

## ② data escrow 위치의 배제는 어떤 증명인가

- 버그 위치(`…zSwapV1.dataEscrow.dataEscrow` 하위)에서 관측된 클래스는 요청 15건을 합쳐 204개다.
  - 닫힌 원뿔 z3 unsat(`o0_closed_cone`): 143
  - 상수 불일치(`o0_only_signal_eliminated_in_o1`): 12
  - unknown(`budget_exhausted`): 49
- **국소 반박(`local_constraint_refutation`)은 0개다.** 그래서 구성 입력 키에 기댄 배제는 없다. 두 증명 종류 모두 기준 입력 값을 고정하지 않는다.
- 클래스는 `drv_mG[].mulFix.m2e[]`, `…segments[].cm2e`, `…segments[].e2m` 같은 범용 부품 사이트다. 그래서 이 배제는 "그 부품 위반 값이 앱에서 일어날 수 없다"는 뜻이다. 버그(암호문 입력이 잘못 연결됨)가 없다는 뜻이 아니다.

## 결론

- aq-024에서 S+J가 버그를 확인하지 못한 주된 원인은 J가 아니라 S 쪽이다.
  - 6개 중 4개 버그의 템플릿을 우리 조각 생성기가 지원하지 못해서 조각이 없다. 미지원 사유는 compile-time 변수, 배열 상수, 컴포넌트 재할당, 컴파일 실패다.
  - 1개(babyjubjub)는 조각은 있었지만 zkFuzz가 반례를 내지 못했고, 일부 대상은 예산 소진으로 시작하지 못했다.
  - 1개(data escrow)는 하위 부품 위반만 관측돼 배제됐다.
- W는 같은 리비전에서 후보가 0이다.
- 이 진단은 조각 준비 단계(F-01 discovery·inspection)의 지원 범위가 RQ-C 결과를 크게 제한한다는 근거다.

## 같이 고친 분석 스크립트 (판정·채점 규칙 불변)

| 파일 | 변경 | 새 SHA-256 |
|---|---|---|
| `scripts/n6_a_size_cost_table_20261026.py` | aq 상태 후보에 `state-v3_1.json` 추가(가장 최신 세대를 우선) | `416aeb5a8cbb1d745756cc497f872ef563ed4795d6cb846f6798b9766b8124f5` |
| `scripts/n6_a_size_cost_checks_20261026.py` | 위에 맞춘 허용 경로 검사(22개 통과) | `34ad79ea4ae2986ea17c0afb671c93e61b8849db0f5ebad602684487c2bc224f` |
| `scripts/n6_j_filter_table_20261026.py` | 상태 후보에 `state-v3_1.json` 추가, 자체 검사에 v3_1 선택 확인 추가(13개 통과) | `424e296adffe948c98486987db92a556966db0b8ebcaf44b253d8f85bd055abc` |

aq에서 `entrypoint_compile_failed`는 아직 0건이다(state-v3_1 기준). 지금까지의 실패는 `candidate_missing_signals` 5건과 `lift_exit_1` 1건(디스크 고갈 때의 2185)이다.

## 추가: RQ-C 18개 버그의 zkbugs 재현·회로·심각도 (읽기 전용)

출처는 `.external/zkbugs/dataset/circom/<항목>/zkbugs_config.json`과 `circuit.circom`이다. 18개 모두 `Reproduced: False`다. zkbugs의 `zkbugs_positive_test.sh`는 정직 증명 생성·검증만 하고, 공격 재현은 하지 않는다. 18개 모두 zkbugs 회로의 main은 프로젝트 main 전체가 아니라, 취약 템플릿을 직접 감싼 테스트용 회로다(예: `component main = DateEncoder();`, `Base64Decode(3)`, `Wrapper(...)`). 심각도는 config의 Bug ID에 적힌 것만 옮겼다. 감사 보고서 본문은 열지 않았다.

| 버그 | Impact | Root Cause | 재현(Reproduced) | zkbugs 회로 | 심각도 표기 |
|---|---|---|---|---|---|
| openzeppelin_mismatched_base64url_decoding_may_break_completeness | Completeness | Misimplementation of a Specification | False | 템플릿 직접 main(테스트용) | Medium |
| openzeppelin_non_determinism_of_some_inputs | Soundness | Missing Input Constraints | False | 템플릿 직접 main(테스트용) | Medium |
| veridise_babyjubjub_suborder_constraints_not_applied_correctly | Soundness | Missing Input Constraints | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-001) |
| veridise_blacklist_states_not_representable_in_field | Completeness | Arithmetic Field Issues | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-009) |
| veridise_bypassing_internal_transfer_limits_via_swaps | Soundness | Wrong Translation of Logic into Constraints | False | 템플릿 직접 main(테스트용) | 설정에 없음(V-PAN-VUL-001) |
| veridise_data_escrow_encrypted_message_wrong_input | Soundness | Other Programming Errors | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-021) |
| veridise_fortxreward_abstracted_away_in_reward_calc | Soundness | Wrong Translation of Logic into Constraints | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-020) |
| veridise_kyt_signature_verification_fails_nonzero_hash | Completeness | Wrong Translation of Logic into Constraints | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-019) |
| veridise_nullifier_verification_can_be_disabled | Soundness | Circuit Design Issue | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-004) |
| veridise_unsafe_num2bits_254_blacklist_leaf | Soundness | Missing Input Constraints | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-010) |
| veridise_zaccount_renewal_kyc_expiry_not_validated | Soundness | Missing Input Constraints | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-017) |
| veridise_zaccount_renewal_multiple_nullifiers_same_utxo | Soundness | Missing Input Constraints | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-002) |
| veridise_zone_id_inclusion_prover_bypass | Soundness | Missing Input Constraints | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-015) |
| veridise_zone_limits_bypass_zswapv1 | Soundness | Wrong Translation of Logic into Constraints | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(V-PAN-VUL-016) |
| koukyosyumei_under_constrained_date_encoder | Soundness | Missing Input Constraints | False | 템플릿 직접 main(테스트용) | 설정에 없음(#60) |
| koukyosyumei_spend_missing_range_check | Soundness | Missing Input Constraints | False | 템플릿 직접 래퍼(테스트용) | 설정에 없음(#1) |
| matterlabs_email_spoofing_via_manipulated_from_header | Soundness | Misimplementation of a Specification | False | 템플릿 직접 main(테스트용) | 설정에 없음(#1 Email spoofing via manipulated From header) |
| matterlabs_fromaddrregex_allows_email_address_spoofing | Soundness | Wrong Translation of Logic into Constraints | False | 템플릿 직접 main(테스트용) | 설정에 없음(#2 FromAddrRegex circuit allows for email address spoofing) |

분류:

- Impact = Completeness: 3개. 건전성(soundness) 오라클로는 정의상 잡히지 않는다.
- Root Cause = Missing Input Constraints: 8개. 제약 부족 계열이라 TCCT 오라클이 겨냥하는 종류다.
- 나머지 7개: 논리 번역 오류, 명세 구현 오류, 설계, 기타 프로그래밍 오류. 제약은 일관되지만 의미가 틀린 경우가 있어서, TCCT 위반으로 나타나지 않을 수 있다.
