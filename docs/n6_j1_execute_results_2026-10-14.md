# N6-J1 A 맥락 판정 전체 결과 (2026-10-14 실행, 2026-10-15 기록)

## 범위와 완전성

리드의 [N6-J3 지시](../runs/handoff/n6_j3_instruction_2026-10-14.md)(SHA-256 ad045c202f810e308bec73df2b2dbf90135e7952bd175cc514a46723840aff5a) 1절과 추가 요구를 기록한다. 고정 [N5 프로토콜](n5_evaluation_protocol_v1_2026-10-06.md)의 A J이며 새 zkFuzz 실행이나 후보 값 열람은 하지 않았다. [값 없는 전체 집계](../runs/n6-j1-2026-10-09.noindex/j-summary-final.json)(SHA-256 915b15c2b99fa900006350bf8bfa483f092d51812563111981bd3b1cbafda653)는 `n6_j1_summarize.py --require-complete`로 생성됐고 `status=complete`다. 2,926개 고정 요청 중 판정 결과 765, 기준 입력 준비 실패 2,161, 대기/실행 실패 0이며 인스턴스 조인 리비전 11개다.

이 수치는 후보 요청과 그 결과의 관측이다. 후보가 없거나 기준 입력이 없어 판정하지 못한 단위를 결함 비도달로 해석하지 않는다. L1은 N5 정의의 entrypoint TCCT 위반 또는 가정 술어 도달이고, 프로젝트 결함 원인 귀속인 L2와 구별한다.

## 실행 기록과 입력 검증

실행기는 [run_n6_j1.py](../scripts/run_n6_j1.py)를 고정 요청 index·내장 캐시·리비전별 캐시 정리 옵션으로 호출했다. [시범 v2 문서의 전체 실행 명령](n6_j2_pilot_results_2026-10-13.md)이 이 설정을 기록한다. 실제 state에는 호출 argv 자체가 없으므로 아래는 state와 실행 전 고정 명령에서 재구성한 명령이며 셸 이력의 별도 증명은 아니다.

    caffeinate -dimsu python3 scripts/run_n6_j1.py --index runs/n6-j1-2026-10-09.noindex/request-index.json --index-sha256 35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c --cache-root runs/n6-j1-2026-10-09.noindex/cache-j-execute.noindex --cleanup-cache-per-revision --action execute --output runs/n6-j1-2026-10-09.noindex/j-execute.noindex

판정은 2026-10-14 22:45:15~2026-10-15 00:20:53 KST(UTC 13:45:15~15:20:53)에 완료됐다. 경과 5,738.224초, 종료 코드 0, state `completed`다. 30개 처리 리비전(main 26, mem20 4) 중 11개는 조인됐고 19개는 `no_results`다. `inference-all-fixed`는 후보 요청이 0이므로 처리 리비전 30개에 포함되지 않지만 단위 표에는 남긴다.

집계 실행 명령:

    python3 scripts/n6_j1_summarize.py --require-complete --index runs/n6-j1-2026-10-09.noindex/request-index.json --run-output runs/n6-j1-2026-10-09.noindex/j-execute.noindex --preparation-units runs/n6-a1-2026-10-07/preparation-units.json --targets docs/n6_targets_a_2026-10-07.json --main-queue runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json --mem20-queue runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json --rq-c-map runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json --output runs/n6-j1-2026-10-09.noindex/j-summary-final.json

입력 목록 [SHA-256 목록](../runs/n6-j1-2026-10-09.noindex/j-execution-inputs.sha256)은 6/6 검증 통과했다. 주요 입력과 출력 해시는 다음과 같다.

| 입력·산출물 | SHA-256 |
| --- | --- |
| [판정 엔진](../runs/l07-2026-10-05/tools/zkfDO) | e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed |
| /Users/miiz/.cargo/bin/circom | 8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227 |
| [실행기](../scripts/run_n6_j1.py) | af23186151e1162f352d1a27f9020e3054e20bc461404791846fbb245077bd7c |
| [요청 index](../runs/n6-j1-2026-10-09.noindex/request-index.json) | 35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c |
| [기준 입력 index v3](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json) | 18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508 |
| [후보 inventory](../runs/n6-j1-2026-10-09.noindex/candidate-inventory.json) | 0d3b018107640d22f3a18cdb699dd93ee645907d3fcaf90edd96a3cd510e1547 |
| [A 준비 단위](../runs/n6-a1-2026-10-07/preparation-units.json) | 051f791f5a4f473f3afd3ae58b92fcb7bdcc112e8bb7b43066cbb59d22f903d9 |
| [A 대상](../docs/n6_targets_a_2026-10-07.json) | 6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758 |
| [A main queue](../runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json) | 2b9d7f1838048a3a776426fd26c38d47dd9363e030299e95519bb5602d612754 |
| [mem20 queue](../runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json) | 4096d515672347b51aa6cfe45a54efe1449c2edf1817ef8073c1582d5a564125 |
| [RQ-C map](../runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json) | 8ad5d43b51d5ceaab0d95dd83a229f45fdc2a2020485a21ccb3b1a43fb4aab85 |
| [실행 state](../runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json) | 6bfeb70743608235bbf9d7125f84c2aadf2fd8d9e95a461de8a9572411cb0e73 |
| [최종 요약](../runs/n6-j1-2026-10-09.noindex/j-summary-final.json) | 915b15c2b99fa900006350bf8bfa483f092d51812563111981bd3b1cbafda653 |

state의 고정 circom, 엔진, 요청 index 해시는 위 파일과 일치한다. 요약기는 결과 JSON마다 state의 SHA와 요청·후보 SHA 결합, 조인 결과 집합, 충돌 0, 전체 단위 완료를 검사한 뒤 성공했다. 이 검증은 결과 파일 메타데이터의 일관성 검증이며 판정의 의미를 독립 재증명한 것은 아니다.

## 판정 분포: 리비전 × 방법

자기 판정과 실효 술어 수는 `result.json`의 클래스 단위다. 한 요청에 여러 클래스가 있어 표의 분포 합은 완료 요청 수보다 클 수 있다. 준비 실패는 판정 클래스가 아니다. L1 수는 요청 단위이며, 같은 결함·인스턴스의 고유 개수로 세지 않는다. W는 whole, S는 split이다.

| 범위·리비전 | 방법 | 요청 | 완료 | 준비실패 | 자기 판정(클래스) | 실효 술어(클래스) | L1 요청 |
| --- | :---: | ---: | ---: | ---: | --- | --- | ---: |
| main/inference-original | W | 0 | 0 | 0 | — | — | 0 |
| main/inference-original | S | 69 | 69 | 0 | 입력도달 22, TCCT 17, 배제 55, 미판정 56 | 술어도달 36, 미판정 3 | 43 |
| main/inference-r-intdiv | W | 0 | 0 | 0 | — | — | 0 |
| main/inference-r-intdiv | S | 26 | 26 | 0 | TCCT 4, 배제 26, 미판정 20 | 술어배제 2, 미판정 15 | 3 |
| main/inference-c9221e8d | W | 0 | 0 | 0 | — | — | 0 |
| main/inference-c9221e8d | S | 15 | 15 | 0 | 배제 11, 미판정 4 | 술어배제 2, 미판정 13 | 0 |
| main/inference-c79f42ee | W | 0 | 0 | 0 | — | — | 0 |
| main/inference-c79f42ee | S | 9 | 9 | 0 | 배제 7, 미판정 2 | 술어배제 2, 미판정 7 | 0 |
| main/inference-c771c61c-p | W | 0 | 0 | 0 | — | — | 0 |
| main/inference-c771c61c-p | S | 3 | 3 | 0 | 배제 1, 미판정 2 | 미판정 3 | 0 |
| main/inference-loo-clamp | W | 0 | 0 | 0 | — | — | 0 |
| main/inference-loo-clamp | S | 6 | 6 | 0 | 배제 6 | 술어배제 2, 미판정 4 | 0 |
| main/inference-loo-dfs | W | 0 | 0 | 0 | — | — | 0 |
| main/inference-loo-dfs | S | 3 | 3 | 0 | 배제 2, 미판정 1 | 미판정 3 | 0 |
| main/banyan-vulnerable | W | 1699 | 0 | 1699 | — | — | 0 |
| main/banyan-vulnerable | S | 108 | 0 | 108 | — | — | 0 |
| main/banyan-fixed | W | 0 | 0 | 0 | — | — | 0 |
| main/banyan-fixed | S | 24 | 0 | 24 | — | — | 0 |
| main/zkemail-fpmul-vulnerable | W | 0 | 0 | 0 | — | — | 0 |
| main/zkemail-fpmul-vulnerable | S | 9 | 9 | 0 | 배제 9 | 술어배제 9 | 0 |
| main/zkemail-fpmul-fixed | W | 0 | 0 | 0 | — | — | 0 |
| main/zkemail-fpmul-fixed | S | 9 | 9 | 0 | 배제 27 | 술어배제 27 | 0 |
| main/aq-006-1680f955c185 | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-006-1680f955c185 | S | 21 | 0 | 21 | — | — | 0 |
| main/aq-007-0bb83f9eab0f | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-007-0bb83f9eab0f | S | 21 | 0 | 21 | — | — | 0 |
| main/aq-008-9c9e702d061d | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-008-9c9e702d061d | S | 21 | 0 | 21 | — | — | 0 |
| main/aq-011-93343c3cd34c | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-011-93343c3cd34c | S | 33 | 0 | 33 | — | — | 0 |
| main/aq-012-44d0df2ab46e | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-012-44d0df2ab46e | S | 24 | 0 | 24 | — | — | 0 |
| main/aq-016-0a7d49b1c135 | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-016-0a7d49b1c135 | S | 24 | 0 | 24 | — | — | 0 |
| main/aq-017-9703bbce0c43 | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-017-9703bbce0c43 | S | 21 | 0 | 21 | — | — | 0 |
| main/aq-024-6f6781246415 | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-024-6f6781246415 | S | 24 | 0 | 24 | — | — | 0 |
| main/aq-025-70328d3fd35e | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-025-70328d3fd35e | S | 27 | 0 | 27 | — | — | 0 |
| main/aq-026-2bcd7ed6110f | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-026-2bcd7ed6110f | S | 27 | 0 | 27 | — | — | 0 |
| main/aq-035-8f826c822cb8 | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-035-8f826c822cb8 | S | 12 | 12 | 0 | 배제 12 | 술어배제 12 | 0 |
| main/aq-036-6d7df64759b6 | W | 577 | 577 | 0 | 입력도달 577 | 술어도달 577 | 577 |
| main/aq-036-6d7df64759b6 | S | 27 | 27 | 0 | 입력도달 10, 미판정 17 | 술어도달 27 | 27 |
| main/aq-037-94fe3080fc18 | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-037-94fe3080fc18 | S | 6 | 0 | 6 | — | — | 0 |
| main/aq-039-0ad3923f2f5b | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-039-0ad3923f2f5b | S | 6 | 0 | 6 | — | — | 0 |
| main/aq-040-da54d3e7bc8a | W | 0 | 0 | 0 | — | — | 0 |
| main/aq-040-da54d3e7bc8a | S | 6 | 0 | 6 | — | — | 0 |
| mem20/aq-006-1680f955c185 | W | 0 | 0 | 0 | — | — | 0 |
| mem20/aq-006-1680f955c185 | S | 21 | 0 | 21 | — | — | 0 |
| mem20/aq-007-0bb83f9eab0f | W | 0 | 0 | 0 | — | — | 0 |
| mem20/aq-007-0bb83f9eab0f | S | 21 | 0 | 21 | — | — | 0 |
| mem20/aq-008-9c9e702d061d | W | 0 | 0 | 0 | — | — | 0 |
| mem20/aq-008-9c9e702d061d | S | 21 | 0 | 21 | — | — | 0 |
| mem20/aq-040-da54d3e7bc8a | W | 0 | 0 | 0 | — | — | 0 |
| mem20/aq-040-da54d3e7bc8a | S | 6 | 0 | 6 | — | — | 0 |
| main/inference-all-fixed | W | 0 | 0 | 0 | — | — | 0 |
| main/inference-all-fixed | S | 0 | 0 | 0 | — | — | 0 |

L1은 총 650개 요청(main inference-original 43, inference-r-intdiv 3, aq-036 604)에서 관측됐다. 인스턴스 도달의 입력 분류는 inference-original L1 요청 43건 중 공개 입력 변경 27, 사설만 9, 분류 없음 7(TCCT 경로), aq-036의 604건은 공개 입력 변경이다. inference-r-intdiv의 L1 3건은 TCCT 경로이며 가정 술어 도달은 아니다. 공개 입력 변경 도달의 의미는 검증자가 그 입력을 정하는 배치 조건에 달린다.

## 단위별 최초 L1과 K5a

아래 값은 고정 A 실행 기록의 후보 완료 offset 초이며 J 판정에 걸린 시간을 더한 시각이 아니다. 600†는 해당 단위·방법에서 L1이 관측되지 않아 600초에 검열됐음을 뜻한다. 준비 실패 또는 후보 0건인 단위에도 같은 기호가 쓰이므로, 이를 배제 판정으로 읽지 않는다. 각 행은 하나의 리비전 아래 seed 01/02/03의 W와 S 단위 쌍 세 개다.

| 범위·단위 | seed 01 W/S | seed 02 W/S | seed 03 W/S |
| --- | ---: | ---: | ---: |
| main/inference-original | 600† / 82.410 | 600† / 82.526 | 600† / 82.557 |
| main/inference-r-intdiv | 600† / 410.060 | 600† / 600† | 600† / 408.313 |
| main/inference-c9221e8d | 600† / 600† | 600† / 600† | 600† / 600† |
| main/inference-c79f42ee | 600† / 600† | 600† / 600† | 600† / 600† |
| main/inference-c771c61c-p | 600† / 600† | 600† / 600† | 600† / 600† |
| main/inference-loo-clamp | 600† / 600† | 600† / 600† | 600† / 600† |
| main/inference-loo-dfs | 600† / 600† | 600† / 600† | 600† / 600† |
| main/inference-all-fixed | 600† / 600† | 600† / 600† | 600† / 600† |
| main/banyan-vulnerable | 600† / 600† | 600† / 600† | 600† / 600† |
| main/banyan-fixed | 600† / 600† | 600† / 600† | 600† / 600† |
| main/zkemail-fpmul-vulnerable | 600† / 600† | 600† / 600† | 600† / 600† |
| main/zkemail-fpmul-fixed | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-006-1680f955c185 | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-007-0bb83f9eab0f | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-008-9c9e702d061d | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-011-93343c3cd34c | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-012-44d0df2ab46e | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-016-0a7d49b1c135 | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-017-9703bbce0c43 | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-024-6f6781246415 | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-025-70328d3fd35e | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-026-2bcd7ed6110f | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-035-8f826c822cb8 | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-036-6d7df64759b6 | 3.552 / 61.070 | 3.097 / 61.071 | 3.246 / 61.073 |
| main/aq-037-94fe3080fc18 | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-039-0ad3923f2f5b | 600† / 600† | 600† / 600† | 600† / 600† |
| main/aq-040-da54d3e7bc8a | 600† / 600† | 600† / 600† | 600† / 600† |
| mem20/aq-006-1680f955c185 | 600† / 600† | 600† / 600† | 600† / 600† |
| mem20/aq-007-0bb83f9eab0f | 600† / 600† | 600† / 600† | 600† / 600† |
| mem20/aq-008-9c9e702d061d | 600† / 600† | 600† / 600† | 600† / 600† |
| mem20/aq-040-da54d3e7bc8a | 600† / 600† | 600† / 600† | 600† / 600† |

고정 main 단위 쌍은 81개(D 36, Q 45)다. 요약기의 기계적 K5a는 r(S+J에서만 L1) 5, l(W에서만 L1) 0이다. r은 inference-original seed 3개와 inference-r-intdiv seed 01·03에서만 나왔다. 45개 단위 쌍(Banyan 6, A-Q 판정 불가 13리비전 × seed 3)은 S 후보가 모두 기준 입력 부재로 준비 실패했으므로 r/l=0을 양쪽의 음성 결과로 쓸 수 없다. 준비 실패 없는 쌍은 36/81이며, 공개 Q 항목의 관측된 L1 대조는 aq-036의 세 쌍에서 W와 S 모두 도달한 경우뿐이다.

## RQ-C 항목과 수정 리비전 대조

고정 70개 zkbugs 항목 중 J 선택 범위는 18개 항목·26개 항목×리비전 매핑이다. 요약기의 조인은 제출된 후보에서 나온 술어 표적만 열거한다. 따라서 매핑 경로와 일치하는 관측 인스턴스 0개는 비도달이 아니라 `관측 없음`이다. 아래 표의 취약/수정/LOO는 항목에 연결된 리비전 ID, 괄호 안은 관측된 매핑 인스턴스 수와 결과다.

| RQ-C 항목 | 취약 리비전 | 수정 리비전 | LOO |
| --- | --- | --- | --- |
| Moonsong-Labs/zksync-social-login-circuit/openzeppelin_mismatched_base64url_decoding_may_break_completeness | aq-008-9c9e702d061d (0; 관측 없음) | aq-006-1680f955c185 (0; 관측 없음) | — |
| Moonsong-Labs/zksync-social-login-circuit/openzeppelin_non_determinism_of_some_inputs | aq-008-9c9e702d061d (0; 관측 없음) | aq-007-0bb83f9eab0f (0; 관측 없음) | — |
| pantherfoundation/panther-core/veridise_babyjubjub_suborder_constraints_not_applied_correctly | aq-024-6f6781246415 (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_blacklist_states_not_representable_in_field | aq-024-6f6781246415 (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_bypassing_internal_transfer_limits_via_swaps | aq-016-0a7d49b1c135 (0; 관측 없음) | aq-012-44d0df2ab46e (0; 관측 없음) | — |
| pantherfoundation/panther-core/veridise_data_escrow_encrypted_message_wrong_input | aq-024-6f6781246415 (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_fortxreward_abstracted_away_in_reward_calc | aq-024-6f6781246415 (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_kyt_signature_verification_fails_nonzero_hash | aq-017-9703bbce0c43 (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_nullifier_verification_can_be_disabled | aq-017-9703bbce0c43 (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_unsafe_num2bits_254_blacklist_leaf | aq-024-6f6781246415 (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_zaccount_renewal_kyc_expiry_not_validated | aq-011-93343c3cd34c (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_zaccount_renewal_multiple_nullifiers_same_utxo | aq-011-93343c3cd34c (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_zone_id_inclusion_prover_bypass | aq-024-6f6781246415 (0; 관측 없음) | — | — |
| pantherfoundation/panther-core/veridise_zone_limits_bypass_zswapv1 | aq-017-9703bbce0c43 (0; 관측 없음) | — | — |
| rarimo/passport-zk-circuits/koukyosyumei_under_constrained_date_encoder | aq-026-2bcd7ed6110f (0; 관측 없음) | aq-025-70328d3fd35e (0; 관측 없음) | — |
| worm-privacy/proof-of-burn/koukyosyumei_spend_missing_range_check | aq-036-6d7df64759b6 (1; assumption_violation_reachable) | aq-035-8f826c822cb8 (1; assumption_excluded_in_context) | — |
| zkemail/zk-regex/matterlabs_email_spoofing_via_manipulated_from_header | aq-040-da54d3e7bc8a (0; 관측 없음) | aq-037-94fe3080fc18 (0; 관측 없음) | — |
| zkemail/zk-regex/matterlabs_fromaddrregex_allows_email_address_spoofing | aq-040-da54d3e7bc8a (0; 관측 없음) | aq-037-94fe3080fc18 (0; 관측 없음) | aq-039-0ad3923f2f5b (0; 관측 없음) |

실제로 양쪽 매핑 인스턴스가 관측된 항목은 proof-of-burn의 `koukyosyumei_spend_missing_range_check` 하나다. 취약 aq-036의 `main.sufficientBalanceChecker.lt`는 가정 위반 도달(공개 입력 변경), 수정 aq-035의 `main.AssertGreaterEqThan_33_921.GreaterEqThan_35_693.lt`는 맥락 배제로 기록됐다. 나머지 17개 선택 항목은 대응 리비전의 준비 실패와 `no_results` 때문에 도달 여부를 판단할 관측 인스턴스가 없다. 이 한 항목의 매핑 결과도 곧바로 고유 원인 L2의 사람 검토를 대체하지 않는다.

### 수정·변형 리비전의 판정

수정 리비전이나 패치/leave-one-out에서 나온 다른 L1을 원래 항목의 `fix_reach`로 세지 않는다. 아래 표는 각 변형의 관측 결과를 따로 유지한다.

| 리비전 | 유형 | 요청 | 완료 | 준비실패 | 자기 판정 | 실효 술어 | L1 요청 |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: |
| inference-r-intdiv | IntDiv만 수정 | 26 | 26 | 0 | TCCT 4, 배제 26, 미판정 20 | 술어배제 2, 미판정 15 | 3 |
| inference-c9221e8d | IntDiv+Subtract | 15 | 15 | 0 | 배제 11, 미판정 4 | 술어배제 2, 미판정 13 | 0 |
| inference-c79f42ee | DistanceFromScore까지 수정 | 9 | 9 | 0 | 배제 7, 미판정 2 | 술어배제 2, 미판정 7 | 0 |
| inference-c771c61c-p | Clamp 수정+순서 보정 | 3 | 3 | 0 | 배제 1, 미판정 2 | 미판정 3 | 0 |
| inference-loo-clamp | 전체 수정에서 Clamp 제외 | 6 | 6 | 0 | 배제 6 | 술어배제 2, 미판정 4 | 0 |
| inference-loo-dfs | 전체 수정에서 DistanceFromScore 제외 | 3 | 3 | 0 | 배제 2, 미판정 1 | 미판정 3 | 0 |
| inference-all-fixed | 전체 수정 | 0 | 0 | 0 | — | — | 0 |
| banyan-fixed | Banyan 수정 | 24 | 0 | 24 | — | — | 0 |
| zkemail-fpmul-fixed | zk-email 수정 | 9 | 9 | 0 | 배제 27 | 술어배제 27 | 0 |
| aq-006-1680f955c185 | A-Q 수정 | 21 | 0 | 21 | — | — | 0 |
| aq-007-0bb83f9eab0f | A-Q 수정 | 21 | 0 | 21 | — | — | 0 |
| aq-012-44d0df2ab46e | A-Q 수정 | 24 | 0 | 24 | — | — | 0 |
| aq-025-70328d3fd35e | A-Q 수정 | 27 | 0 | 27 | — | — | 0 |
| aq-035-8f826c822cb8 | A-Q 수정 | 12 | 12 | 0 | 배제 12 | 술어배제 12 | 0 |
| aq-037-94fe3080fc18 | A-Q 수정 | 6 | 0 | 6 | — | — | 0 |
| aq-039-0ad3923f2f5b | A-Q leave-one-out | 6 | 0 | 6 | — | — | 0 |

특히 inference-r-intdiv의 L1 3건은 다른 TCCT 클래스의 판정이다. 해당 리비전의 `DistanceFromScore.positive`는 이번 A J에서 unknown이므로 L-07의 인스턴스 도달을 이번 결과의 수정판 도달로 옮겨 세지 않았다. aq-035는 매핑 인스턴스 1개가 실효 배제다. Banyan-fixed와 A-Q 수정 리비전 다수는 기준 입력이 없어 비교 결과 자체가 없다.

## 판정 불가와 mem20

준비 실패 2,161건은 모두 요청 수준의 `base_input_unavailable`이다. main 2,092 = Banyan 취약·수정 1,831 + A-Q 13개 리비전 261, mem20 69다. 리비전별 수는 다음과 같다.

| 범위·리비전 | W 실패 | S 실패 | 합 | 기준 입력 상태 |
| --- | ---: | ---: | ---: | --- |
| main/banyan-vulnerable | 1699 | 108 | 1807 | base_input_unavailable |
| main/banyan-fixed | 0 | 24 | 24 | base_input_unavailable |
| main/aq-006-1680f955c185 | 0 | 21 | 21 | base_input_unavailable |
| main/aq-007-0bb83f9eab0f | 0 | 21 | 21 | base_input_unavailable |
| main/aq-008-9c9e702d061d | 0 | 21 | 21 | base_input_unavailable |
| main/aq-011-93343c3cd34c | 0 | 33 | 33 | base_input_unavailable |
| main/aq-012-44d0df2ab46e | 0 | 24 | 24 | base_input_unavailable |
| main/aq-016-0a7d49b1c135 | 0 | 24 | 24 | base_input_unavailable |
| main/aq-017-9703bbce0c43 | 0 | 21 | 21 | base_input_unavailable |
| main/aq-024-6f6781246415 | 0 | 24 | 24 | base_input_unavailable |
| main/aq-025-70328d3fd35e | 0 | 27 | 27 | base_input_unavailable |
| main/aq-026-2bcd7ed6110f | 0 | 27 | 27 | base_input_unavailable |
| main/aq-037-94fe3080fc18 | 0 | 6 | 6 | base_input_unavailable |
| main/aq-039-0ad3923f2f5b | 0 | 6 | 6 | base_input_unavailable |
| main/aq-040-da54d3e7bc8a | 0 | 6 | 6 | base_input_unavailable |
| mem20/aq-006-1680f955c185 | 0 | 21 | 21 | base_input_unavailable |
| mem20/aq-007-0bb83f9eab0f | 0 | 21 | 21 | base_input_unavailable |
| mem20/aq-008-9c9e702d061d | 0 | 21 | 21 | base_input_unavailable |
| mem20/aq-040-da54d3e7bc8a | 0 | 6 | 6 | base_input_unavailable |

기준 입력은 N5 순서 (a) zkbugs 입력, (b) L 시리즈 정직 입력, (c) 커밋 JSON, (d) 프로젝트 테스트/도구, (e) 0 입력으로 찾았으며, 위 리비전들은 어느 단계에서도 검증된 정직 witness를 얻지 못했다. 단계별 실패 원인과 설치 없이 가능한 조치, 네트워크가 필요한 별도 탐색층은 [N6-J3 기준 입력 탐색층 계획](n6_j3_exploratory_base_inputs_plan_2026-10-14.md)에 기록한다. 공식 J 결과는 이 계획으로 바뀌지 않는다.

mem20의 69건은 4개 리비전, seed 3개에서 S 요청 전부 준비 실패이고 W 후보 요청은 0이다. 따라서 mem20과 main의 맥락 판정·최초 L1 시각 차이를 비교할 수 없다. 요약기의 mem20 600초 검열은 판정 결과를 뜻하지 않는다.

## inference unknown의 엔진 중단 분류

사용자 제시 `65건`은 현재 고정 산출물의 집계 단위 어느 것과도 일치하지 않는다. inference 7개 리비전의 자기 판정 unknown은 85개 클래스(44개 후보 요청), 실효 가정 술어 unknown은 48개 클래스/요청이다. 전체 자기 unknown은 AQ-036의 17개를 더한 102개 클래스(61개 요청)다. 따라서 65를 분모로 고쳐 쓰지 않고, SHA 고정 `result.json`의 클래스·술어 메타데이터를 분리해 보고한다. 후보 값·반례 값 필드는 분석하거나 출력하지 않았다. 각 unknown의 결과 경로·SHA·중단 이유만 모은 [메타데이터 목록](../runs/n6-j1-2026-10-09.noindex/j-unknown-engine-stops-final.json)(SHA-256 `b64220ed686ce0959f48e818bfb7b56155ee5db13272585d82af5b731ed5677e`)에 자기 클래스 85행과 술어 항목 55행을 보존했다.

| 리비전 | 자기 unknown 클래스 | 예산 소진 | 이탈 생성 중단 | 제약 abort 미해결 | 실효 술어 unknown 클래스 |
| --- | ---: | ---: | ---: | ---: | ---: |
| inference-original | 56 | 38 | 18 | 0 | 3 |
| inference-r-intdiv | 20 | 8 | 10 | 2 | 15 |
| inference-c9221e8d | 4 | 2 | 0 | 2 | 13 |
| inference-c79f42ee | 2 | 2 | 0 | 0 | 7 |
| inference-c771c61c-p | 2 | 2 | 0 | 0 | 3 |
| inference-loo-clamp | 0 | 0 | 0 | 0 | 4 |
| inference-loo-dfs | 1 | 0 | 0 | 1 | 3 |

예산 소진 52개 중 역방향 탐색 `b_outcome`은 원뿔 과대 49, 모델 재현 실패 3이다. 원뿔 과대 49개에서 수리 `repair.outcome`은 cycle 24, no_progress 16, error 7, iteration_limit 2로 끝났다. 자기 unknown의 나머지 28개는 이탈 witness 생성 abort, 5개는 제약 abort 해결 실패다. 이 분류는 상위 종료 이유로 서로 배타적이다.

중간 solver 단계의 z3 unknown은 자기 unknown 클래스 29개에 포함된다(cycle 18, no_progress 9, iteration_limit 2). 이미 위 예산/수리 종료 이유에 포함된 사건이므로 별도 종료 건수로 합산하지 않는다. result.json의 술어 항목은 unknown 55개이고 모두 `predicate_search_not_reached`다. 그 내부 탐색 종료는 cycle 28, no_progress 26, error 1이며, 이 55개 중 25개에 중간 z3 unknown이 있다. 같은 요청 안에 여러 술어가 있어 자기/실효 unknown 수와 직접 더할 수 없다.

### L-07과 같은 인스턴스의 차이

[L-07 결과](lifting_l07_results_2026-10-06.md#검증-1-inference-리비전-행렬)는 A-02 개발 후보로 `DistanceFromScore.positive`가 원본·R_intdiv·c9221e8d·loo_dfs에서 공개 입력 변경으로 도달함을 확인했다. 이번 A J 조인에서는 원본의 이 인스턴스와 ResponseTimeNormalized LessThan, ScoringFunction lt가 공개 입력 변경 도달, Clamp LessThan[0]이 사설만 도달이다. R_intdiv·c9221e8d·loo_dfs의 positive는 각각 unknown이다.

같은 인스턴스라도 입력으로 제출된 후보 집합이 달랐다. L-07에서 R_intdiv·c9221e8d·loo_dfs positive 도달의 근거였던 A-02 후보 SHA와 이번 A J의 해당 리비전 positive 대상 후보 SHA는 각각 교집합이 0이다(해당 A J 요청 수 6/6/3). 이번 결과의 술어 탐색은 `predicate_search_not_reached`와 cycle/no_progress로 끝났다. L-07의 도달 증거는 그 후보 집합의 관측이고, 이번 J의 unknown은 다른 후보 집합에 대한 탐색 한계다. 두 결과를 같은 입력의 재현 실패나 수정판의 비도달 증명으로 해석하지 않는다. 새 실행은 하지 않았다.

## J 비용과 시범 추정 대조

요청 벽시계 합은 5,686.192초(1.580시간), 전체 state 경과는 5,738.224초(1.594시간)다. 가장 긴 요청은 inference-r-intdiv queue 92의 163.907초, 최대 요청 RSS는 inference-c771c61c-p queue 119의 3,657,383,936 bytes(3,487.95 MiB)다. 요청 내 컴파일 단계 합은 705.018초, 컴파일 캐시 적중 2,095회, 인스턴스 저장소 적중 257회다. 사람 검토 시간과 기존 A 준비·zkFuzz 비용은 이 J 수치에 포함하지 않는다.

실행기의 `probe_time_l()`가 `/usr/bin/time -l /usr/bin/true`에서 RSS 행을 읽어 이번 전체 실행을 `measurement_method=time-l`로 고정했다. Mac의 `maximum resident set size` 정수를 bytes로 `max_rss_bytes`에 저장한다. 이는 각 lift 직접 자식의 최대 RSS이며 전체 프로세스 트리 또는 동시 peak가 아니다. [시범 v2](n6_j2_pilot_results_2026-10-13.md)는 직접 wait4 측정이므로 두 RSS 수치는 측정 경로가 다르다.

11개 조인 리비전의 정리 manifest SHA를 모두 재확인했다. 정리 합계는 2,930파일, 58,441,171,829 bytes(54.428 GiB)이고 모두 `deleted` 상태다. 캐시 루트에는 파일이 0개다. 아래 값은 각 리비전이 끝날 때의 논리 파일 크기 합이며 동시에 존재한 총량이 아니다.

| 리비전 | 파일 | bytes | GiB | 정리 manifest SHA-256 |
| --- | ---: | ---: | ---: | --- |
| inference-original | 1723 | 20,670,081,551 | 19.251 | bb5db4d48c9b3aedab7e90c0a4d2c71e93f5c7e1d873e00372797bce44658746 |
| inference-r-intdiv | 526 | 17,184,670,331 | 16.004 | 9bd473e042db00ca254831e2f6ba31fd171bc8160668121f55e16fe152249b3d |
| inference-c9221e8d | 239 | 7,896,275,609 | 7.354 | 596802e77d265cf0714d721be479c2972f0ef91bf6c98df7d93cd40789847b9b |
| inference-c79f42ee | 148 | 5,028,239,768 | 4.683 | 191940443449ace36e37cdf65888a7458b237b3f608dc0c338df1044bbc27c48 |
| inference-c771c61c-p | 57 | 2,085,003,150 | 1.942 | 6a1e844afb17c9dcb492607f0ae7ae2271286d848e1b373d677e901fbbb66a00 |
| inference-loo-clamp | 85 | 3,006,880,214 | 2.800 | 73e967b4b469436959f35cce84cf5c2960d6ce09e1ffa7984c07356af9eaf32c |
| inference-loo-dfs | 64 | 2,361,767,583 | 2.200 | bdf5c8067fac1e161f73431bdb96fa5ccf2cd008ee0188cfdc72467216a27fab |
| zkemail-fpmul-vulnerable | 15 | 91,026,643 | 0.085 | ea3e310b3233500156a563697e0451804230266be37eb79e637c115ff56d8171 |
| zkemail-fpmul-fixed | 15 | 109,705,664 | 0.102 | bb9576d4f00ddd3d3c9c9267452e297712539e5ec2cc13aa264a2db87a19aaa2 |
| aq-035-8f826c822cb8 | 15 | 2,046,585 | 0.002 | a4a49d12e8d5690c2d8a229fb863558794747c8a4b3377e489a714b2d19acfb9 |
| aq-036-6d7df64759b6 | 43 | 5,474,731 | 0.005 | af50afb00e7a03077ffc3bd6a6e63de87b10c08c8eba93fabe2856295129bc1a |

정리 직전 캐시 기록 중 최댓값은 inference-original 20,670,081,551 bytes(19.251 GiB)다. 리비전 내부의 순간 디스크 peak는 별도 계측하지 않았다. 결과 디렉터리의 종료 시점 디스크 사용량은 11.597 GiB(`du -sk` 12,160,368 KiB)이고, 종료 시점 캐시 파일은 0개다. 시범 v2의 단순 추정은 요청 8,453초(2.35시간), 리비전별 정리 시 출력 포함 약 63.4 GiB였다. 실측 요청 합은 그 추정의 0.673배이고, 종료 출력 11.60 GiB와 가장 큰 리비전 캐시 19.25 GiB를 단순 합친 비교값은 30.85 GiB다. 이 합은 실제 동시 디스크 peak의 계측값이 아니다. 시범 추정은 후보별 재사용과 출력 편차를 반영하지 않은 용량 계획치였다.

## 해석 범위

A J의 확인은 개발 D층의 inference와 공개 Q층의 일부 결과에 집중됐다. Q층 대부분과 Banyan의 요청은 기준 입력 부재로 판정되지 않았다. worm-privacy 한 항목의 매핑 전후 대조와 inference 개발 관측을 분리해서 보고해야 한다. 650 L1 요청을 고유 결함 수로 환산하지 않으며, 도달 관측과 프로젝트 의미·원인 귀속은 후속 사람 검토가 필요하다. 이번 작업은 B J, mem20 B, 의존성 설치 또는 후보 재실행을 수행하지 않았다.

