# controlled-v4 독립 평가 후보 조사

조사일: 2026-09-26

상태: **완료 — 최소 구성 미달**

고정한 기준을 zkbugs Circom 70건 전체에 적용했지만, 주 평가에 넣을 수 있는 원인은 **0건, 프로젝트는 0개**였다. 사전에 정한 확장 두 가지도 결과를 늘리지 못했다. 따라서 목표였던 원인 5개·프로젝트 3개를 충족하지 못했으며, 이 결과로 controlled-v4 평가 프로토콜을 고정하거나 실행해서는 안 된다.

## 고정 입력과 금지 사항

- 후보: zkbugs `a0eed744ba1a816acaa2fae597f4e79b4fd01aea`의 Circom 70건
- 선정 기준: `docs/heldout_selection_rubric.md`, SHA-256 `12ba462acf05fc59143a8da19aec1a891780a7a82ad2971e3c49fccd0fd4d2fb`
- 개발 제외 목록: SHA-256 `ae1157e00ca4593d21202a5de275c061e3cf9aaaafe08e376707969c35e359d7`
- 조사용 zkfDO: SHA-256 `750ecb0365a2cc1bedd6cf90e7540f04efd3887aae1c750aefe76d9170ca1bba`
- Circom 2.2.3: SHA-256 `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227`
- zkFuzz 2.2.1: SHA-256 `ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd`

후보에는 zkFuzz를 실행하지 않았다. 위험점수, Circomspect 경고, 순위, `experiment prepare`, `experiment plan`도 보지 않았다. 고정한 소스와 도구를 바꾸지 않았고 설치 lifecycle script를 실행하지 않았다. 조사 전 보존한 로컬 백업에도 접근하지 않았다.

## 주 기준 결과

| 단계 | 도달 | 탈락 | 통과 | 주된 사유 |
|---:|---:|---:|---:|---|
| 0 | 70 | 41 | 29 | 개발에 노출된 원인 22건 또는 프로젝트 전체 제외 19건 |
| 1 | 29 | 13 | 16 | under-constrained가 아님 6건, Fix Commit 없음 7건 |
| 2 | 16 | 11 | 5 | 패치 확보·공식성·해당 제약 변경 조건 실패 |
| 3 | 5 | 3 | 2 | production entrypoint 근거 없음 |
| 4 | 2 | 2 | 0 | 고정 컴파일러·탐색 도구로 처리 불가 |
| 5 | 0 | 0 | 0 | 도달한 사례 없음 |
| 6 | 0 | 0 | 0 | 도달한 사례 없음 |

### 2단계

16건 중 5건이 통과했다: worm-privacy 1건, zk-regex 2건, zkopru 2건이다.

11건은 다음 이유로 탈락했다.

- panther-core 7건은 zkbugs의 축약 Fix Commit을 공개 canonical 저장소에서 전체 SHA로 풀거나 받을 수 없었다.
- panther-core 1건은 과거 병합된 PR에서 실제 제약 변경을 확인했지만, 현재는 닫힌 PR ref에서만 도달 가능했다. 고정된 2단계 규칙에 따라 `proposed`로 분류해 탈락시켰다. 여기서 `proposed`는 현재 도달 경로에 대한 조사용 분류이며, 과거 병합 메타데이터가 없다는 뜻은 아니다.
- Arianee 1건의 제약 변경 커밋은 canonical 브랜치와 tag 어디에서도 도달할 수 없었다.
- darkforest-v0.3 1건의 기록된 패치는 원래 프로젝트가 아니라 별도 `darkforest-eth/circuits` 저장소에 있었다.
- MACI 1건은 기록된 endpoint가 공식 이력에 있기는 하지만, zkbugs가 지목한 `ResultCommitmentVerifier`의 핵심 제약은 그대로였다. 중간 이력의 `TallyVotes` caller-side 완화는 감사 보고서에서도 부분 해결로 분류됐고, 기록된 Fix Commit 자체는 다른 `ProcessMessages` 문제를 수정한다.

zk-regex의 기록된 Fix Commit 자체는 main 파일을 지우는 커밋이다. 두 원인의 실제 제약 변경은 그 endpoint 이전의 공식 커밋 `81d0299e…`와 `77541563…`에 있으며 endpoint에는 두 변경이 모두 포함된다. 이 점은 직접 diff와 endpoint 상태를 구분해 기록했다.

### 3단계

- Worm의 `circuits/spend.circom`에는 `component main`이 있지만, 취약 revision의 Makefile과 README는 `circuits/proof_of_burn.circom`만 실제 산출물로 연결한다. 파일 이름과 main 선언만으로 production 사용을 추정하지 않아 탈락시켰다.
- zk-regex의 main 35개는 모두 `packages/circom/tests/circuits/` 아래였다. 빌드·CI·문서에도 두 결함 템플릿을 production 산출물로 연결하는 근거가 없어 2건 모두 탈락했다.
- zkopru의 `zk_transaction_{1..4}_{1..4}.circom` 16개는 빌드 스크립트와 key loader가 실제 회로·키 산출물로 연결하므로 2건 모두 통과했다.

### 4단계

zkopru는 취약 revision의 Yarn v1 lockfile과 당시 최신 Yarn Classic 1.22.10을 사용했다. 설치 script를 차단한 상태에서, 첫 `git://` 전송 실패 뒤 lockfile·저장소·고정 ref를 바꾸지 않는 command-scoped HTTPS 전송 치환으로 설치를 마쳤다.

그러나 production entrypoint 16개 모두 공유 파일의 Circom 0.5 구문 `signal private input` 때문에 고정 Circom 2.2.3에서 P1008/P1012로 실패했다. 고정 zkfDO 탐색도 16개 모두 incomplete였고, 총 792개의 unsupported 기록과 target 0개를 냈다. 이 0은 관측 하한일 뿐이므로 `N_p`는 **0이 아니라 미정(null)**으로 기록했다. 소스 변환이나 도구 수정은 조사 중 금지돼 있어 두 원인 모두 `tool-unsupported`로 탈락했다.

## 사전 고정 확장

주 결과가 원인 5개·프로젝트 3개보다 부족하다는 사실을 먼저 기록한 뒤, 기준 문서에 정한 순서대로 확장했다.

### 확장 1: 열린 제안 패치

Fix Commit이 비어 있던 7건을 다시 보되, 현재 공개된 열린 PR이 해당 원인의 제약 패치를 실제로 제안하는 경우만 허용했다. 통과는 0건이었다.

| 사례 | 결과 | 근거 |
|---|---|---|
| Arianee OwnershipVerifier | 제외 | 열린 PR 6개가 모두 의존성 갱신 |
| RLN self-slashing | 제외 | 열린 #14는 해시 교체이며 문서화된 self-slashing 완화가 아님 |
| iden3 unsafe Num2Bits | 제외 | 일치하는 #131은 2024-04-17 병합·종료; 현재 열린 PR은 비관련 |
| Spartan PubKeyMembership | 제외 | 현재 열린 관련 제약 패치 없음 |
| Spartan EfficientECDSA | 제외 | 열린 인접 변경은 include 추가·미사용 변수 삭제뿐이며 `s`를 제약하지 않음 |
| Spartan K | 제외 | `mul.circom`의 `K`를 고치는 열린 PR 없음 |
| Semaphore zero leaf | 제외 | 열린 PR 31개 중 Circom 경로 변경 0건; 유사 PR은 TypeScript만 변경 |

### 확장 2: 최소 `N_p` 6에서 4로 완화

수치 기준만 완화할 수 있는 프로젝트가 없었다. zkopru의 `N_p`는 4~5가 아니라 incomplete discovery 때문에 미정이므로 이 확장으로 살릴 수 없다. 추가 원인과 프로젝트는 모두 0건이다.

## 결론과 범위

최종 결과는 원인 **0/5**, 프로젝트 **0/3**이다. 이는 퍼저가 결함을 찾지 못했다는 결과가 아니다. 후보가 oracle·입력 계약 단계에 도달하기 전에 provenance, production 연결, 또는 고정 도구 호환성에서 모두 탈락했다. 특히 zkopru의 관측 target 0개를 실제 타깃 수 0으로 해석하면 안 된다.

이 결과를 보고 기준을 사후 완화하거나 소스를 Circom 2로 변환하지 않았다. 다음 연구 단계로 가려면 다른 후보 출처를 **새 기준 버전에 사전 고정**하고 새 독립 후보 풀로 다시 시작하거나, 이번에 드러난 legacy Circom 지원을 별도 개발 자료로 해결한 뒤 새로운 기준 버전과 새 독립 후보 풀로 다시 시작해야 한다.

## 기록 파일

| 파일 | SHA-256 |
|---|---|
| [stage01.json](stage01.json) | `31c3ad3915fb61bfe3e7f4702ce72f810c0ce1b8e44e4111c9b95e718d978231` |
| [stage02.json](stage02.json) | `b7b0bee3b2ab669c8e9cffb662159bee108097ee6440923e2effef148fba7df8` |
| [stage03.json](stage03.json) | `f4a47f4aedc73ce2defda06293563109d7ae4121df6690288d8d13a0512bdfd7` |
| [stage04.json](stage04.json) | `c69af859b07e442ac59fcf9e43cd18a3b6637a2f2c1e8e7536d94ee6cee9bb92` |
| [extension01.json](extension01.json) | `8f9d444e1e0f6355dbc08b9f2f0f5c7b01f14c82f42cec5eff939692aac40314` |
| [extension02.json](extension02.json) | `06f10cd80b3d5be56e79a3a797bb6f731b0b119784cec26cb65b29398c049b34` |
| [survey.json](survey.json) | `eb5788b755994ba052726c9e5bd4b4f7c801d7db816607c3fbbaa0ce6fcf226c` |

원시 clone, 설치·컴파일 로그, discovery JSON, GitHub API 응답과 PR diff는 ignored `runs/heldout-survey-2026-09-26/` 아래에 보존했다. 여러 PR diff는 저장 디렉터리와 함께 해시 가능한 tar 파일로 묶었고, tracked 단계 기록에는 보존 파일의 SHA-256을 적었다.

## 70건 전체 판정

아래 단계는 처음 탈락한 단계다. [survey.json](survey.json)의 `primary_cases`에는 요약이 있고, `candidate_detail_resolution`이 `first_failed_stage`와 `zkbugs_case`로 해시 고정된 단계별 상세 기록을 찾는 방법을 명시한다.

| zkbugs 사례 | 단계 | 사유 코드 |
|---|---:|---|
| `0xbok/circom-bigint/veridise_missing_range_checks_in_bigmod` | 0 | `development-root-cause` |
| `Arianee/arianee-sdk/veridise_creditnoteproofs_can_be_stolen` | 2 | `unreachable-recorded-patch` |
| `Arianee/arianee-sdk/veridise_ownershipproofs_could_identify_issuers` | 1 | `missing-fix-commit` |
| `Moonsong-Labs/zksync-social-login-circuit/openzeppelin_mismatched_base64url_decoding_may_break_completeness` | 0 | `development-project` |
| `Moonsong-Labs/zksync-social-login-circuit/openzeppelin_non_determinism_of_some_inputs` | 0 | `development-root-cause` |
| `Rate-Limiting-Nullifier/circom-rln/veridise_spammers_may_slash_themselves` | 1 | `missing-fix-commit` |
| `Unirep/Unirep/veridise_missing_range_checks_on_comparison_circuits` | 0 | `development-root-cause` |
| `Unirep/Unirep/veridise_underconstrained_circuit_allows_invalid_comparison` | 0 | `development-root-cause` |
| `aptos-labs/keyless-zk-proofs/koukyosyumei_unconstrained_base64_decoded_len` | 0 | `development-root-cause` |
| `banyancomputer/hot-proofs-blake3-circom/koukyosyumei_checkdepth_comparator_overflow` | 0 | `development-root-cause` |
| `darkforest-eth/darkforest-v0.3/daira_hopwood_darkforest_v0_3_missing_bit_length_check` | 2 | `external-successor-patch` |
| `iden3/circomlib/kobi_gurkan_mimc_hash_assigned_but_not_constrained` | 0 | `development-root-cause` |
| `iden3/circomlib/veridise_decoder_accepting_bogus_output_signal` | 0 | `development-root-cause` |
| `iden3/circomlib/veridise_underconstrained_outputs_in_bitElementMulAny` | 0 | `development-project` |
| `iden3/circomlib/veridise_underconstrained_outputs_in_window4` | 0 | `development-project` |
| `iden3/circomlib/veridise_underconstrained_outputs_in_windowmulfix` | 0 | `development-project` |
| `iden3/circomlib/veridise_underconstrained_points_in_edwards2Montgomery` | 0 | `development-project` |
| `iden3/circomlib/veridise_underconstrained_points_in_montgomery2Edwards` | 0 | `development-project` |
| `iden3/circomlib/veridise_underconstrained_points_in_montgomeryAdd` | 0 | `development-project` |
| `iden3/circomlib/veridise_underconstrained_points_in_montgomeryDouble` | 0 | `development-project` |
| `iden3/circuits/trailofbits_unsafe_use_of_num2bits_in_multiple_circuits` | 1 | `missing-fix-commit` |
| `inference-labs-inc/subnet-2-circom/koukyosyumei_clamp_comparator_overflow` | 0 | `development-root-cause` |
| `inference-labs-inc/subnet-2-circom/koukyosyumei_subtract_unconstrained_multiplier` | 0 | `development-root-cause` |
| `pantherfoundation/panther-core/veridise_babyjubjub_suborder_constraints_not_applied_correctly` | 2 | `patch-commit-unavailable` |
| `pantherfoundation/panther-core/veridise_blacklist_states_not_representable_in_field` | 1 | `metadata-type-ineligible` |
| `pantherfoundation/panther-core/veridise_bypassing_internal_transfer_limits_via_swaps` | 2 | `proposed-patch` |
| `pantherfoundation/panther-core/veridise_data_escrow_encrypted_message_wrong_input` | 1 | `metadata-type-ineligible` |
| `pantherfoundation/panther-core/veridise_fortxreward_abstracted_away_in_reward_calc` | 1 | `metadata-type-ineligible` |
| `pantherfoundation/panther-core/veridise_kyt_signature_verification_fails_nonzero_hash` | 1 | `metadata-type-ineligible` |
| `pantherfoundation/panther-core/veridise_nullifier_verification_can_be_disabled` | 2 | `patch-commit-unavailable` |
| `pantherfoundation/panther-core/veridise_unsafe_num2bits_254_blacklist_leaf` | 2 | `patch-commit-unavailable` |
| `pantherfoundation/panther-core/veridise_zaccount_renewal_kyc_expiry_not_validated` | 2 | `patch-commit-unavailable` |
| `pantherfoundation/panther-core/veridise_zaccount_renewal_multiple_nullifiers_same_utxo` | 2 | `patch-commit-unavailable` |
| `pantherfoundation/panther-core/veridise_zone_id_inclusion_prover_bypass` | 2 | `patch-commit-unavailable` |
| `pantherfoundation/panther-core/veridise_zone_limits_bypass_zswapv1` | 2 | `patch-commit-unavailable` |
| `personaelabs/spartan-ecdsa/yacademy_Knowledge_of_any_member_signature_allow_to_generate_proof_of_membership` | 1 | `missing-fix-commit` |
| `personaelabs/spartan-ecdsa/yacademy_input_signal_s_is_not_constrained_in_eff_ecdsa_circom` | 1 | `missing-fix-commit` |
| `personaelabs/spartan-ecdsa/yacademy_under_constrained_circuits_compromising_the_soundness_of_the_system` | 1 | `missing-fix-commit` |
| `privacy-scaling-explorations/maci/hashcloak_data_are_not_fully_verified_during_state_update` | 2 | `affected-template-constraints-unchanged` |
| `rarimo/passport-zk-circuits/koukyosyumei_under_constrained_date_encoder` | 0 | `development-root-cause` |
| `reclaimprotocol/circom-chacha20/zksecurity_Unsound_Addition_Gadget` | 0 | `development-root-cause` |
| `reclaimprotocol/circom-chacha20/zksecurity_Unsound_XOR_gadget` | 0 | `development-root-cause` |
| `reclaimprotocol/circom-chacha20/zksecurity_unsound_left_rotation` | 0 | `development-root-cause` |
| `selfxyz/self/zksecurity_an_attacker_can_craft_a_fake_non_inclusion_proof_for_a_given_key_due_to_an_aliasing_bug_in_the_smt_verifier` | 0 | `development-root-cause` |
| `selfxyz/self/zksecurity_big_integer_zero_check_is_not_sound` | 0 | `development-project` |
| `selfxyz/self/zksecurity_exclusion_check_of_forbidden_countries_is_unsound_and_incomplete_due_to_incorrect_indexing` | 0 | `development-project` |
| `selfxyz/self/zksecurity_forbidden_country_check_bypass_via_packed_byte_overflow` | 0 | `development-project` |
| `selfxyz/self/zksecurity_missing_boolean_constraints_in_the_merkle_tree_path_leads_to_an_attacker_being_able_to_craft_a_fake_merkle_proof_for_an_arbitrary_leaf` | 0 | `development-root-cause` |
| `selfxyz/self/zksecurity_missing_byte_range_checks_allows_packed_data_pollution` | 0 | `development-project` |
| `selfxyz/self/zksecurity_second_pre_image_attacks_on_packbytesandposeidon_may_be_used_to_register_arbitrary_passports_and_dsc_certificates` | 0 | `development-project` |
| `selfxyz/self/zksecurity_the_registration_and_disclosure_circuits_lack_range_checks_for_the_input_indices` | 0 | `development-project` |
| `semaphore-protocol/semaphore/veridise_no_zero_value_validation` | 1 | `missing-fix-commit` |
| `sismo-core/hydra-s2-zkps/veridise_private_information_leakage` | 1 | `metadata-type-ineligible` |
| `siv-org/verifiable-private-overrides/koukyosyumei_emitifinrange_lessthan_overflow` | 0 | `development-project` |
| `siv-org/verifiable-private-overrides/koukyosyumei_extractstringfrompoint_shiftedfirstbyte_unconstrained` | 0 | `development-root-cause` |
| `succinctlabs/telepathy-circuits/trailofbits_incorrect_handling_of_point_doubling_can_allow_signature_forgery` | 0 | `development-project` |
| `succinctlabs/telepathy-circuits/trailofbits_prover_can_lock_user_funds_by_including_ill-formed_bigints_in_public_key_commitment` | 0 | `development-project` |
| `succinctlabs/telepathy-circuits/trailofbits_prover_can_lock_user_funds_by_supplying_non-reduced_Y_values_to_G1BigIntToSignFlag` | 0 | `development-project` |
| `succinctlabs/telepathy-circuits/veridise_arrayxor_is_under_constrained` | 0 | `development-root-cause` |
| `succinctlabs/telepathy-circuits/veridise_template_CoreVerifyPubkeyG1_does_not_perform_input_validation_simplified` | 0 | `development-root-cause` |
| `succinctlabs/telepathy-circuits/veridise_zero_padding_for_sha256_in_ExpandMessageXMD_is_vulnerable_to_an_overflow` | 0 | `development-project` |
| `tangle-network/protocol-solidity/veridise_incorrect_initialization_in_membership_circuits` | 0 | `development-root-cause` |
| `worm-privacy/proof-of-burn/koukyosyumei_spend_missing_range_check` | 3 | `entrypoint-unverified` |
| `zkemail/ether-email-auth/matterlabs_emailauth_fails_with_overlapping_invitation_code_regex` | 1 | `metadata-type-ineligible` |
| `zkemail/zk-email-verify/matterlabs_underconstrained_fpmul_circuit` | 0 | `development-root-cause` |
| `zkemail/zk-email-verify/zksecurity_sha256_templates_return_zero_on_arbitrary_inputs` | 0 | `development-root-cause` |
| `zkemail/zk-regex/matterlabs_email_spoofing_via_manipulated_from_header` | 3 | `entrypoint-unverified` |
| `zkemail/zk-regex/matterlabs_fromaddrregex_allows_email_address_spoofing` | 3 | `entrypoint-unverified` |
| `zkopru-network/zkopru/leastauthority_Circuit_Does_Not_Check_the_ERC_20_Sum_Correctly_` | 4 | `tool-unsupported` |
| `zkopru-network/zkopru/leastauthority_previously_correct_ownership_proof_disabled_via_code_changes` | 4 | `tool-unsupported` |
