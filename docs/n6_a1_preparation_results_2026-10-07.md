# N6-A1 알려진 결함 정답 대조 대상 목록·준비 결과 (2026-10-07)

담당은 miiz다. 이 작업은 대상 목록, revision 준비, discovery·prepare·plan, W/S preflight까지만 수행했다. zkFuzz 후보 탐색과 캠페인 `execute`는 수행하지 않았고 후보 파일도 열지 않았다.

## 고정 목록

- 대상 목록: `docs/n6_targets_a_2026-10-07.json`, SHA-256 `6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758`
- 전체 70건: A-D 5, A-Q 1단계 24, A-Q 2단계 21, 수정 전 전용 20.
- Fix Commit 있음 50건, 없음 20건. 공유 fix 5그룹, leave-one-out 표시 11건이다.
- Original 종류: project_main 47, project_test 7, original_is_direct 14, zkbugs_thin 2.
- `Direct Entrypoint`는 참고 메타데이터로만 기록했고 실행 대체에 쓰지 않았다.

## 준비 결과

목록의 라벨 중복을 실행 단위 규칙으로 제거한 결과 A-D 12개, A-Q 1단계 41개, 합계 53개 revision 단위였다. materialization은 ready 35, source commit unavailable 16, 분리 불가능 leave-one-out 1, fixed revision의 Original 경로 부재 1였다.

setup은 성공 27, 실패 8, 미시작 18였다. 실패 유형은 package install command 2, lockfile mismatch 2, pnpm version 미기재 3, submodule command 1이다.

discovery·prepare·plan은 성공 19, 실패 8, 미시작 26였다. 성공 단위에서 discovery 대상 91,343개, prepared 999개, 적격 조각 357개를 기록했다. 실패는 compiler/tool error 7개와 concrete root instance 미확정 1개다.

Panther 16개 단위는 고정 목록의 vulnerable/fix commit이 현재 원격 ref에서도 해석되지 않아 `source_commit_unavailable`로 남겼다. 이를 다른 revision이나 Direct wrapper로 바꾸지 않았다. SIV `EmitIfInRange` leave-one-out은 공유 fix가 해당 템플릿 위치의 독립 hunk로 존재하지 않아 `leave_one_out_patch_unavailable`로 남겼다. Tangle fixed revision에서는 기록된 Original test 경로가 사라져 대체 경로를 선택하지 않았다.

외부 library search root는 7개 성공 단위에서 `.external/zkbugs/dataset/circom/dependencies/circomlib` 하나뿐이었다. plan의 source fingerprint에는 그 root에서 실제로 채택된 외부 파일이 없었고, 원본 project와 생성 wrapper/source snapshot은 spec에 tree/file hash로 고정했다.

## spec·preflight

- 최종 queue: `runs/n6-a1-2026-10-07/queue-v2.json`, SHA-256 `d99c8a626526f695492994c519e0870ac6156a7293dbeb69c8e6aff0c14639a6`.
- 최종 preflight: `runs/n6-a1-2026-10-07/preflight-v2/preflight-all.json`, SHA-256 `02d51e2e124931035fb8d9580302d14588056be504888743823efe9c7c2fa54c`.
- 성공한 준비 단위 19개 × seed 3 × W/S = 114 spec이다. T=600초, S 시도 상한 30초, seed는 2026100601/02/03이다.
- 114개 기록 중 통과 93, 실패 21. seed 독립 재사용 76, 실제 preflight 실행 38이다.
- 고유 단위 첫 seed 기준 W/S 모두 통과: A-D 9/12, A-Q 1단계 3/41. 준비 성공 단위의 S는 19/19 통과했고 W는 12/19 통과했다.
- v1은 S spec의 `source_snapshot_path` 누락을 검출해 보존하고 폐기했다. 최종 v2는 그 필드만 보완했다. W의 실제 컴파일 실패 7개는 승격하거나 숨기지 않았다.

## 실행 시간 예상

한 revision 단위는 seed 3개 × (W 600초 + S 600초) = 최대 1시간의 캠페인 wall을 쓴다. 동시 단위 3개라면 전체 고정 분모의 이론적 상한은 A-D 12개 약 4시간, A-Q 1단계 41개 약 13시간 40분이다. 현재 W/S preflight를 모두 통과한 단위만 놓으면 A-D 9개 약 3시간, A-Q 1단계 3개 약 1시간이다. 준비·판정·재시작 비용은 이 계산에 포함하지 않는다.

## 측정 편차·정리

첫 inference 준비에서 공통 프로필이 AST 통계를 요청해 zkFuzz를 후보 탐색이 아닌 `--version`으로 22회 호출했다. 이를 발견하자 중단했고 원시 기록을 보존했다. 후보 탐색·퍼징·캠페인 실행은 0회다. 최종 small-first 준비 경로는 AST와 zkFuzz version 요청이 0회다.

setup 명령 누적 wall은 129.558초였고, discovery·prepare·plan 명령 누적 wall은 335.230초였다. preflight v2 전체 wall은 573.195초였다. 단계별 시작·종료 시각과 load average는 ignored run JSON에 있다.
materialization 중 1분 load average가 최대 28.120까지 올라간 구간은 `aq-038`~`aq-040` 복제·checkout 구간(2026-10-06 19:56:41~19:56:51 UTC)이었다. setup 최대는 23.848, discovery·prepare·plan 최대는 12.871이었다. 이 부하 관측은 결과 상태를 재분류하는 근거로 쓰지 않았다.
cleanup 전에 capture 값이 있는 진단 사본만 삭제했다. 파일 2,675개, 2.633 GiB를 해시·크기 기록 후 삭제했다. capture/args가 모두 없던 진단 사본 30개는 보존했다. 첫 materialization 직전 여유 214.325 GiB에서 cleanup 직후 204.710 GiB로 순 9.615 GiB 감소했다.

## 70건 배치

| ID | 프로젝트 | 칸 | Original 종류 | Original entrypoint | setup 성공 | LOO | 누락·미확인 |
|---|---|---|---|---|---:|---:|---|
| 0xbok/circom-bigint/veridise-V-BIGINT-COD-001 | 0xbok/circom-bigint | A-Q-stage2 | project_test | `test/circuits/test_bigmod_22.circom` | no | no | 없음 |
| Arianee/arianee-sdk/veridise_creditnoteproofs_can_be_stolen | Arianee/arianee-sdk | A-Q-stage1 | project_main | `packages/privacy-circuits/src/circom/creditVerifier/generated/creditVerifier_main.circom` | yes | no | original_input_missing_locally |
| Arianee/arianee-sdk/veridise_ownershipproofs_could_identify_issuers | Arianee/arianee-sdk | vulnerable_only | project_main | `packages/privacy-circuits/src/circom/ownershipVerifier/generated/ownershipVerifier_main.circom` | yes | no | original_input_missing_locally |
| Moonsong-Labs/zksync-social-login-circuit/openzeppelin_mismatched_base64url_decoding_may_break_completeness | Moonsong-Labs/zksync-social-login-circuit | A-Q-stage1 | project_main | `jwt-tx-validation.circom` | yes | no | original_input_missing_locally |
| Moonsong-Labs/zksync-social-login-circuit/openzeppelin_non_determinism_of_some_inputs | Moonsong-Labs/zksync-social-login-circuit | A-Q-stage1 | project_main | `jwt-tx-validation.circom` | yes | no | original_input_missing_locally |
| Rate-Limiting-Nullifier/circom-rln/veridise_spammers_may_slash_themselves | Rate-Limiting-Nullifier/circom-rln | vulnerable_only | project_main | `circuits/withdraw.circom` | no | no | 없음 |
| Unirep/Unirep/veridise-V-UNI-VUL-002 | Unirep/Unirep | A-Q-stage2 | project_main | `packages/circuits/generated/epochKeyLite.circom` | no | no | 없음 |
| Unirep/Unirep/veridise-V-UNI-VUL-001 | Unirep/Unirep | A-Q-stage2 | project_main | `packages/circuits/generated/bigComparators.circom` | no | no | 없음 |
| aptos-labs/keyless-zk-proofs/koukyosyumei_unconstrained_base64_decoded_len | aptos-labs/keyless-zk-proofs | A-Q-stage1 | zkbugs_thin | `circuit/templates/generated/base64_decoded_length_main.circom` | yes | no | original_input_missing_locally |
| banyancomputer/hot-proofs-blake3-circom/koukyosyumei_checkdepth_comparator_overflow | banyancomputer/hot-proofs-blake3-circom | A-D | zkbugs_thin | `circuits/main/check_depth_main.circom` | yes | no | 없음 |
| darkforest-eth/darkforest-v0.3/Daira-Hopwood-Missing-Bit-Length-Check | darkforest-eth/darkforest-v0.3 | A-Q-stage2 | project_main | `circuits/init/circuit.circom` | no | no | 없음 |
| iden3/circomlib/Kobi-Gurkan-MiMC-Hash-Assigned-but-not-Constrained | iden3/circomlib | A-Q-stage1 | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| iden3/circomlib/veridise-V-CIRCOMLIB-VUL-001 | iden3/circomlib | vulnerable_only | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| iden3/circomlib/veridise-V-CIRCOMLIB-VUL-006 | iden3/circomlib | vulnerable_only | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| iden3/circomlib/veridise-V-CIRCOMLIB-VUL-007 | iden3/circomlib | vulnerable_only | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| iden3/circomlib/veridise-V-CIRCOMLIB-VUL-008 | iden3/circomlib | vulnerable_only | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| iden3/circomlib/veridise-V-CIRCOMLIB-VUL-002 | iden3/circomlib | vulnerable_only | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| iden3/circomlib/veridise-V-CIRCOMLIB-VUL-003 | iden3/circomlib | vulnerable_only | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| iden3/circomlib/veridise-V-CIRCOMLIB-VUL-004 | iden3/circomlib | vulnerable_only | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| iden3/circomlib/veridise-V-CIRCOMLIB-VUL-005 | iden3/circomlib | vulnerable_only | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| iden3/circuits/trailofbits_unsafe_use_of_num2bits_in_multiple_circuits | iden3/circuits | vulnerable_only | original_is_direct | `$BUG_DIR/circuit.circom` | yes | no | 없음 |
| inference-labs-inc/subnet-2-circom/koukyosyumei_clamp_comparator_overflow | inference-labs-inc/subnet-2-circom | A-D | project_main | `src/generated/clamp_main.circom` | no | yes | 없음 |
| inference-labs-inc/subnet-2-circom/koukyosyumei_subtract_unconstrained_multiplier | inference-labs-inc/subnet-2-circom | A-D | project_main | `src/generated/subtract_main.circom` | no | yes | 없음 |
| pantherfoundation/panther-core/veridise_babyjubjub_suborder_constraints_not_applied_correctly | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZTransactionV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_blacklist_states_not_representable_in_field | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZTransactionV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_bypassing_internal_transfer_limits_via_swaps | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZSwapV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_data_escrow_encrypted_message_wrong_input | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZTransactionV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_fortxreward_abstracted_away_in_reward_calc | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZTransactionV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_kyt_signature_verification_fails_nonzero_hash | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZSwapV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_nullifier_verification_can_be_disabled | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZSwapV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_unsafe_num2bits_254_blacklist_leaf | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZTransactionV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_zaccount_renewal_kyc_expiry_not_validated | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZAccountRenewalV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_zaccount_renewal_multiple_nullifiers_same_utxo | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZAccountRenewalV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_zone_id_inclusion_prover_bypass | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZTransactionV1.circom` | yes | no | original_input_missing_locally |
| pantherfoundation/panther-core/veridise_zone_limits_bypass_zswapv1 | pantherfoundation/panther-core | A-Q-stage1 | project_main | `circuits/circuits/mainZSwapV1.circom` | yes | no | original_input_missing_locally |
| personaelabs/spartan-ecdsa/yacademy_Knowledge_of_any_member_signature_allow_to_generate_proof_of_membership | personaelabs/spartan-ecdsa | vulnerable_only | project_main | `packages/circuits/instances/pubkey_membership.circom` | no | no | original_input_missing_locally |
| personaelabs/spartan-ecdsa/yacademy-high-01 | personaelabs/spartan-ecdsa | vulnerable_only | project_main | `packages/circuits/instances/pubkey_membership.circom` | no | no | 없음 |
| personaelabs/spartan-ecdsa/yacademy-high-03 | personaelabs/spartan-ecdsa | vulnerable_only | project_main | `packages/circuits/instances/pubkey_membership.circom` | no | no | 없음 |
| privacy-scaling-explorations/maci/hashcloak_Data_are_not_fully_verified_during_state_update | privacy-scaling-explorations/maci | A-Q-stage2 | original_is_direct | `$BUG_DIR/circuit.circom` | no | no | 없음 |
| rarimo/passport-zk-circuits/koukyosyumei_under_constrained_date_encoder | rarimo/passport-zk-circuits | A-Q-stage1 | project_main | `circuits/identityManagement/queryIdentity.circom` | yes | no | original_input_missing_locally |
| reclaimprotocol/circom-chacha20/zksecurity_Unsound_Addition_Gadget | reclaimprotocol/circom-chacha20 | A-Q-stage2 | original_is_direct | `$BUG_DIR/circuit.circom` | no | no | original_input_missing_locally |
| reclaimprotocol/circom-chacha20/zksecurity_Unsound_XOR_gadget | reclaimprotocol/circom-chacha20 | A-Q-stage2 | original_is_direct | `$BUG_DIR/circuit.circom` | no | no | original_input_missing_locally |
| reclaimprotocol/circom-chacha20/zksecurity-1 | reclaimprotocol/circom-chacha20 | A-Q-stage2 | original_is_direct | `$BUG_DIR/circuit.circom` | no | no | 없음 |
| selfxyz/self/zksecurity_an_attacker_can_craft_a_fake_non_inclusion_proof_for_a_given_key_due_to_an_aliasing_bug_in_the_smt_verifier | selfxyz/self | A-Q-stage2 | project_main | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsa_65537_4096.circom` | no | no | 없음 |
| selfxyz/self/zksecurity_big_integer_zero_check_is_not_sound | selfxyz/self | vulnerable_only | project_main | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsa_65537_4096.circom` | no | no | 없음 |
| selfxyz/self/zksecurity_exclusion_check_of_forbidden_countries_is_unsound_and_incomplete_due_to_incorrect_indexing | selfxyz/self | vulnerable_only | project_main | `circuits/circuits/disclose/vc_and_disclose.circom` | no | no | 없음 |
| selfxyz/self/zksecurity_forbidden_country_check_bypass_via_packed_byte_overflow | selfxyz/self | A-Q-stage2 | project_main | `circuits/circuits/disclose/generated/vc_and_disclose_aadhaar_main.circom` | no | no | 없음 |
| selfxyz/self/zksecurity_missing_boolean_constraints_in_the_merkle_tree_path_leads_to_an_attacker_being_able_to_craft_a_fake_merkle_proof_for_an_arbitrary_leaf | selfxyz/self | A-Q-stage2 | project_main | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsa_65537_4096.circom` | no | no | 없음 |
| selfxyz/self/zksecurity_missing_byte_range_checks_allows_packed_data_pollution | selfxyz/self | A-Q-stage2 | project_main | `circuits/circuits/disclose/generated/vc_and_disclose_aadhaar_main.circom` | no | no | 없음 |
| selfxyz/self/zksecurity_second_pre_image_attacks_on_packbytesandposeidon_may_be_used_to_register_arbitrary_passports_and_dsc_certificates | selfxyz/self | vulnerable_only | project_main | `circuits/circuits/disclose/vc_and_disclose.circom` | no | no | 없음 |
| selfxyz/self/zksecurity_the_registration_and_disclosure_circuits_lack_range_checks_for_the_input_indices | selfxyz/self | A-Q-stage2 | project_main | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsa_65537_4096.circom` | no | no | 없음 |
| semaphore-protocol/semaphore/veridise-V-SEM-VUL-001 | semaphore-protocol/semaphore | vulnerable_only | project_main | `packages/circuits/generated/semaphore_main.circom` | yes | no | 없음 |
| sismo-core/hydra-s2-zkps/veridise_private_information_leakage | sismo-core/hydra-s2-zkps | vulnerable_only | project_main | `circuits/generated/hydra-s2_main.circom` | no | no | original_input_missing_locally |
| siv-org/verifiable-private-overrides/koukyosyumei_emitifinrange_lessthan_overflow | siv-org/verifiable-private-overrides | A-Q-stage1 | project_main | `circuits/generated/emit_if_in_range_main.circom` | yes | yes | 없음 |
| siv-org/verifiable-private-overrides/koukyosyumei_extractstringfrompoint_shiftedfirstbyte_unconstrained | siv-org/verifiable-private-overrides | A-Q-stage1 | project_main | `circuits/generated/extract_string_from_point_main.circom` | yes | yes | 없음 |
| succinctlabs/telepathy-contracts | succinctlabs/telepathy-circuits | vulnerable_only | project_main | `circuits/step.circom` | no | no | 없음 |
| succinctlabs/telepathy-circuits/trailofbits-succinct-1 | succinctlabs/telepathy-circuits | A-Q-stage2 | project_main | `circuits/step.circom` | no | yes | 없음 |
| succinctlabs/telepathy-circuits/trailofbits-succinct-2 | succinctlabs/telepathy-circuits | A-Q-stage2 | project_main | `circuits/step.circom` | no | yes | 없음 |
| succinctlabs/telepathy-circuits/veridise-V-SUC-VUL-001 | succinctlabs/telepathy-circuits | A-Q-stage2 | project_main | `circuits/step.circom` | no | yes | 없음 |
| succinctlabs/telepathy-circuits/veridise-V-SUC-VUL-002-simplified | succinctlabs/telepathy-circuits | A-Q-stage2 | project_main | `circuits/step.circom` | no | yes | 없음 |
| succinctlabs/telepathy-circuits/veridise-V-SUC-VUL-003 | succinctlabs/telepathy-circuits | A-Q-stage2 | project_main | `circuits/step.circom` | no | yes | 없음 |
| tangle-network/protocol-solidity/veridise_incorrect_initialization_in_membership_circuits | tangle-network/protocol-solidity | A-Q-stage1 | project_test | `circuits/test/poseidon_vanchor_2_2.circom` | yes | no | 없음 |
| worm-privacy/proof-of-burn/koukyosyumei_spend_missing_range_check | worm-privacy/proof-of-burn | A-Q-stage1 | project_main | `circuits/spend.circom` | yes | no | 없음 |
| zkemail/ether-email-auth/matterlabs_emailauth_fails_with_overlapping_invitation_code_regex | zkemail/ether-email-auth | A-Q-stage2 | project_main | `packages/circuits/src/email_auth.circom` | no | no | original_input_missing_locally |
| zkemail/zk-email-verify/matterlabs_underconstrained_fpmul_circuit | zkemail/zk-email-verify | A-D | project_test | `packages/circuits/tests/test-circuits/rsa-test.circom` | yes | no | original_input_missing_locally |
| zkemail/zk-email-verify/zksecurity_sha256_templates_return_zero_on_arbitrary_inputs | zkemail/zk-email-verify | A-D | project_test | `packages/circuits/tests/test-circuits/sha-test.circom` | yes | no | 없음 |
| zkemail/zk-regex/matterlabs_email_spoofing_via_manipulated_from_header | zkemail/zk-regex | A-Q-stage1 | project_test | `packages/circom/tests/circuits/test_from_addr_regex.circom` | yes | yes | original_input_missing_locally |
| zkemail/zk-regex/matterlabs_fromaddrregex_allows_email_address_spoofing | zkemail/zk-regex | A-Q-stage1 | project_test | `packages/circom/tests/circuits/test_from_addr_regex.circom` | yes | yes | original_input_missing_locally |
| zkopru-network/zkopru/leastauthority_Circuit_Does_Not_Check_the_ERC-20_Sum_Correctly_ | zkopru-network/zkopru | A-Q-stage2 | project_main | `packages/circuits/impls/zk_transaction_1_1.circom` | no | no | original_input_missing_locally |
| zkopru-network/zkopru/leastauthority-previously-correct-ownership-proof-disabled-via-code-changes | zkopru-network/zkopru | A-Q-stage2 | project_test | `packages/circuits/tester/ownership_proof.test.circom` | no | no | 없음 |

## leave-one-out 준비

아래는 이번 1단계에 실제로 들어온 leave-one-out revision 단위다. 목록의 leave-one-out 표시 11건 중 A-Q 2단계 항목은 이번 준비 대상이 아니며, 동일 트리·entrypoint 중복은 실행 단위에서 합쳤다.

| 단위 | 범위 | diff SHA-256 | materialization | spec |
|---|---|---|---|---|
| inference-loo-clamp | runs/l06-2026-10-03/trees/loo_clamp.diff | `0446e86cf5415a7af4cc51d5df3a7dbbd69115f926688d691c9599fd35d42b35` | ready | W/S 생성 |
| inference-loo-dfs | runs/l06-2026-10-03/trees/loo_dfs.diff | `c58c09a5e213db989b79c1da98c7745a84bffb5cf28aebc40ce719d1cb8a4ca4` | ready | W/S 생성 |
| aq-028-b9b2613fdfa4 | circuits/ExtractStringFromPoint.circom:31-39 (EmitIfInRange) | unavailable | leave_one_out_patch_unavailable | 미생성 |
| aq-031-2191c2696b01 | circuits/ExtractStringFromPoint.circom:19 (ExtractStringFromPoint) | `cbb89d16f02293753cacf9db581e9554e56f2a815d15702697478304ee29e78d` | ready | 미생성 |
| aq-038-4e5dcd2256b8 | packages/circom/circuits/common/email_addr_with_name_regex.circom:6-190 (EmailAddrWithNameRegex) | `5f30c3390b1086d9670594cabbfb1820ca8944832d36d2220c3e32430ce035f5` | ready | W/S 생성 |
| aq-039-0ad3923f2f5b | packages/circom/circuits/common/from_all_regex.circom:6-110 (FromAllRegex) | `8e4d600bb3be8826596fde0cb58464b17336cdd4aa31964d1618cf4ad468c003` | ready | W/S 생성 |

## revision 단위

| 단위 | 갈래 | 프로젝트 | revision 종류 | materialization | setup | prepare/plan | 발견 | 준비 | 적격 | 외부 include root | W | S | 실패 사유 |
|---|---|---|---|---|---|---|---:|---:|---:|---|---|---|---|
| inference-original | A-D | inference-labs-inc/subnet-2-circom | development | ready | success | success | 2336 | 22 | 22 | 없음 | passed | passed | 없음 |
| inference-r-intdiv | A-D | inference-labs-inc/subnet-2-circom | development | ready | success | success | 2348 | 25 | 25 | 없음 | passed | passed | 없음 |
| inference-c9221e8d | A-D | inference-labs-inc/subnet-2-circom | development | ready | success | success | 2348 | 25 | 25 | 없음 | passed | passed | 없음 |
| inference-c79f42ee | A-D | inference-labs-inc/subnet-2-circom | development | ready | success | success | 2350 | 25 | 25 | 없음 | passed | passed | 없음 |
| inference-c771c61c-p | A-D | inference-labs-inc/subnet-2-circom | development | ready | success | success | 2354 | 25 | 25 | 없음 | passed | passed | 없음 |
| inference-loo-clamp | A-D | inference-labs-inc/subnet-2-circom | leave_one_out | ready | success | success | 2829 | 25 | 21 | 없음 | failed | passed | W:preflight_status_failed |
| inference-loo-dfs | A-D | inference-labs-inc/subnet-2-circom | leave_one_out | ready | success | success | 2831 | 25 | 21 | 없음 | failed | passed | W:preflight_status_failed |
| inference-all-fixed | A-D | inference-labs-inc/subnet-2-circom | fixed | ready | success | success | 2833 | 25 | 21 | 없음 | failed | passed | W:preflight_status_failed |
| banyan-vulnerable | A-D | banyancomputer/hot-proofs-blake3-circom | development | ready | success | success | 6 | 6 | 6 | 없음 | passed | passed | 없음 |
| banyan-fixed | A-D | banyancomputer/hot-proofs-blake3-circom | fixed | ready | success | success | 8 | 7 | 7 | 없음 | passed | passed | 없음 |
| zkemail-fpmul-vulnerable | A-D | zkemail/zk-email-verify | development | ready | success | success | 444 | 15 | 11 | 없음 | passed | passed | 없음 |
| zkemail-fpmul-fixed | A-D | zkemail/zk-email-verify | fixed | ready | success | success | 445 | 15 | 11 | 없음 | passed | passed | 없음 |
| aq-000-a6b97aeaa1ae | A-Q-stage1 | aptos-labs/keyless-zk-proofs | fixed | ready | success | failed | - | - | - | .external/zkbugs/dataset/circom/dependencies/circomlib | not_created | not_created | manifest_concrete_instance_unavailable |
| aq-001-b32aa7daaea0 | A-Q-stage1 | aptos-labs/keyless-zk-proofs | vulnerable | ready | success | failed | 0 | 1 | 0 | .external/zkbugs/dataset/circom/dependencies/circomlib | not_created | not_created | compiler_or_tool_error |
| aq-002-923e08e670de | A-Q-stage1 | Arianee/arianee-sdk | fixed | ready | setup_failure | not_started | - | - | - | 없음 | not_created | not_created | package_install_command_failed |
| aq-003-626254249e88 | A-Q-stage1 | Arianee/arianee-sdk | vulnerable | ready | setup_failure | not_started | - | - | - | 없음 | not_created | not_created | package_install_command_failed |
| aq-004-803378d79dea | A-Q-stage1 | iden3/circomlib | fixed | ready | setup_failure | not_started | - | - | - | 없음 | not_created | not_created | package_install_lockfile_mismatch |
| aq-005-b689893c025f | A-Q-stage1 | iden3/circomlib | vulnerable | ready | setup_failure | not_started | - | - | - | 없음 | not_created | not_created | package_install_lockfile_mismatch |
| aq-006-1680f955c185 | A-Q-stage1 | Moonsong-Labs/zksync-social-login-circuit | fixed | ready | setup_failure | not_started | - | - | - | 없음 | not_created | not_created | pnpm_version_not_declared |
| aq-007-0bb83f9eab0f | A-Q-stage1 | Moonsong-Labs/zksync-social-login-circuit | fixed | ready | setup_failure | not_started | - | - | - | 없음 | not_created | not_created | pnpm_version_not_declared |
| aq-008-9c9e702d061d | A-Q-stage1 | Moonsong-Labs/zksync-social-login-circuit | vulnerable | ready | setup_failure | not_started | - | - | - | 없음 | not_created | not_created | pnpm_version_not_declared |
| aq-009-aefcab68a248 | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-010-f35ff2e9e262 | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-011-93343c3cd34c | A-Q-stage1 | pantherfoundation/panther-core | vulnerable | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-012-44d0df2ab46e | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-013-dd5954ac38b1 | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-014-5427d7292faa | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-015-7bec6b38ea36 | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-016-0a7d49b1c135 | A-Q-stage1 | pantherfoundation/panther-core | vulnerable | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-017-9703bbce0c43 | A-Q-stage1 | pantherfoundation/panther-core | vulnerable | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-018-e39e4e77138c | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-019-90637f07f72b | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-020-f217a8d648bc | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-021-12898764f632 | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-022-1f2e2842f6ed | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-023-e609ecb8edce | A-Q-stage1 | pantherfoundation/panther-core | fixed | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-024-6f6781246415 | A-Q-stage1 | pantherfoundation/panther-core | vulnerable | source_commit_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | source_commit_unavailable |
| aq-025-70328d3fd35e | A-Q-stage1 | rarimo/passport-zk-circuits | fixed | ready | success | success | 1728 | 337 | 44 | .external/zkbugs/dataset/circom/dependencies/circomlib | passed | passed | 없음 |
| aq-026-2bcd7ed6110f | A-Q-stage1 | rarimo/passport-zk-circuits | vulnerable | ready | success | success | 1721 | 335 | 42 | .external/zkbugs/dataset/circom/dependencies/circomlib | passed | passed | 없음 |
| aq-027-a847471783dc | A-Q-stage1 | siv-org/verifiable-private-overrides | fixed | ready | success | failed | 0 | 1 | 0 | .external/zkbugs/dataset/circom/dependencies/circomlib | not_created | not_created | compiler_or_tool_error |
| aq-028-b9b2613fdfa4 | A-Q-stage1 | siv-org/verifiable-private-overrides | leave_one_out | leave_one_out_patch_unavailable | not_started | not_started | - | - | - | 없음 | not_created | not_created | leave_one_out_patch_unavailable |
| aq-029-886c1c02fb66 | A-Q-stage1 | siv-org/verifiable-private-overrides | vulnerable | ready | success | failed | 0 | 1 | 0 | .external/zkbugs/dataset/circom/dependencies/circomlib | not_created | not_created | compiler_or_tool_error |
| aq-030-f6334f2145b4 | A-Q-stage1 | siv-org/verifiable-private-overrides | fixed | ready | success | failed | 32 | 3 | 0 | .external/zkbugs/dataset/circom/dependencies/circomlib | not_created | not_created | compiler_or_tool_error |
| aq-031-2191c2696b01 | A-Q-stage1 | siv-org/verifiable-private-overrides | leave_one_out | ready | success | failed | 31 | 2 | 0 | .external/zkbugs/dataset/circom/dependencies/circomlib | not_created | not_created | compiler_or_tool_error |
| aq-032-01439be37566 | A-Q-stage1 | siv-org/verifiable-private-overrides | vulnerable | ready | success | failed | 31 | 2 | 0 | .external/zkbugs/dataset/circom/dependencies/circomlib | not_created | not_created | compiler_or_tool_error |
| aq-033-f4e0cd04d538 | A-Q-stage1 | tangle-network/protocol-solidity | fixed | original_entrypoint_missing | not_started | not_started | - | - | - | 없음 | not_created | not_created | original_entrypoint_missing |
| aq-034-8d1c03d49b12 | A-Q-stage1 | tangle-network/protocol-solidity | vulnerable | ready | setup_failure | not_started | - | - | - | 없음 | not_created | not_created | submodule_command_failed |
| aq-035-8f826c822cb8 | A-Q-stage1 | worm-privacy/proof-of-burn | fixed | ready | success | success | 12 | 10 | 6 | .external/zkbugs/dataset/circom/dependencies/circomlib | passed | passed | 없음 |
| aq-036-6d7df64759b6 | A-Q-stage1 | worm-privacy/proof-of-burn | vulnerable | ready | success | success | 6 | 6 | 3 | .external/zkbugs/dataset/circom/dependencies/circomlib | failed | passed | W:preflight_status_failed |
| aq-037-94fe3080fc18 | A-Q-stage1 | zkemail/zk-regex | fixed | ready | success | success | 22558 | 20 | 14 | .external/zkbugs/dataset/circom/dependencies/circomlib | failed | passed | W:preflight_status_failed |
| aq-038-4e5dcd2256b8 | A-Q-stage1 | zkemail/zk-regex | leave_one_out | ready | success | success | 22558 | 20 | 14 | .external/zkbugs/dataset/circom/dependencies/circomlib | failed | passed | W:preflight_status_failed |
| aq-039-0ad3923f2f5b | A-Q-stage1 | zkemail/zk-regex | leave_one_out | ready | success | success | 21534 | 20 | 14 | .external/zkbugs/dataset/circom/dependencies/circomlib | failed | passed | W:preflight_status_failed |
| aq-040-da54d3e7bc8a | A-Q-stage1 | zkemail/zk-regex | vulnerable | ready | success | failed | 0 | 1 | 0 | .external/zkbugs/dataset/circom/dependencies/circomlib | not_created | not_created | compiler_or_tool_error |

## 검사

- `python3 -m unittest tests/n6_targets_a_test.py tests/n6_prepare_a_stage1_test.py tests/n6_a_specs_test.py tests/n6_b_queue_test.py tests/policy_a_engine_v3_test.py`: 24/24 통과.
- `cargo fmt`: 통과.
- `cargo clippy --all-targets --all-features -- -D warnings`: 통과.
- `cargo test`: 348 통과, 22 ignored, 실패 0.
