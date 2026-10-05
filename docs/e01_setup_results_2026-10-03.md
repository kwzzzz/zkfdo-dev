# E-01 C-03 setup 실패 저장소 자동 환경 구성 확장 결과

담당 miiz · 완료 2026-10-03 · zkFuzz 0회.

## 결과 요약

- C-03 production setup 실패 **9개 저장소·329 entrypoint 전부**를 동일 commit·동일 key로 재측정했다.
- setup은 C-03 0/9에서 E-01 **6/9**로 늘었다.
- 같은 entrypoint의 compile 성공은 C-03 **6/329**에서 E-01 **125/329**로 늘었다. timeout 17, failure 187다.
- 준비 결과는 success 18, partial 123, unsupported 19, failed 169다. partial/unsupported는 성공으로 합치지 않았다.
- 성공적으로 컴파일되어 제약 수를 읽은 10만 이상 entrypoint는 **49개**다. compile failure/timeout의 제약 수는 unknown이다.
- 컴파일 산출물 2,361개, 21,342,872,854바이트를 manifest 기록 후 삭제했고 건너뜀은 0개다.

## 저장소별 결과

| 저장소 | setup C-03 → E-01 | E-01 실패 유형 | compile 성공 C-03 → E-01 / 분모 | E-01 준비 success / partial / unsupported / failed |
|---|---:|---|---:|---:|
| `Galactica-corp/galactica-monorepo` | setup_failure → success | — | 3 → 25 / 25 | 3 / 17 / 5 / 0 |
| `anon-aadhaar/anon-aadhaar` | setup_failure → success | — | 0 → 3 / 3 | 0 / 2 / 1 / 0 |
| `celo-org/self` | setup_failure → setup_failure | package_install_lockfile_mismatch | 0 → 0 / 79 | 0 / 12 / 0 / 67 |
| `proofcarryingdata/zupass` | setup_failure → success | — | 3 → 5 / 16 | 3 / 11 / 0 / 2 |
| `selfxyz/self` | setup_failure → setup_failure | package_install_authentication, submodule_command_failed | 0 → 42 / 141 | 6 / 51 / 1 / 83 |
| `semaphore-protocol/semaphore` | setup_failure → success | — | 0 → 0 / 1 | 0 / 0 / 0 / 1 |
| `stealthdrop/stealthdrop` | setup_failure → setup_failure | package_install_artifact_not_found | 0 → 0 / 3 | 0 / 0 / 0 / 3 |
| `zkemail/zk-email-verify` | setup_failure → success | — | 0 → 21 / 21 | 6 / 5 / 7 / 3 |
| `zkp2p/zkp2p-v1-monorepo` | setup_failure → success | — | 0 → 29 / 40 | 0 / 25 / 5 / 10 |

Celo는 immutable lockfile의 builtin patch hash 변경 요구로 실패했고, selfxyz는 HTTPS submodule 치환 후에도 비공개 접근 인증이 필요했으며, Stealthdrop은 고정 외부 tarball 404로 실패했다. 저장소별 수동 lock/source 수선이나 자격 증명 주입은 하지 않았다.

## 제약 10만 이상 entrypoint

| 저장소 | entrypoint | 제약 | 준비 | 준비 실패 유형 |
|---|---|---:|---|---|
| `anon-aadhaar/anon-aadhaar` | `packages/circuits/src/aadhaar-verifier.circom` | 1,115,080 | unsupported | no_eligible_units_due_to_unsupported_inspection |
| `anon-aadhaar/anon-aadhaar` | `packages/circuits/test/circuits/extractor-test.circom` | 129,004 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/ecdsa/test_brainpoolP224r1.circom` | 1,992,814 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/ecdsa/test_brainpoolP256r1.circom` | 1,847,135 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/extractQrData_tester.circom` | 205,382 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha1_64321_4096.circom` | 429,973 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha1_65537_2048.circom` | 322,825 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha224_65537_2048.circom` | 322,777 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_107903_4096.circom` | 501,341 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_122125_4096.circom` | 465,625 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_130689_4096.circom` | 465,625 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_56611_4096.circom` | 429,909 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_65537_2048.circom` | 322,761 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_65537_3072.circom` | 322,761 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_65537_4096.circom` | 322,761 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha512_65537_4096.circom` | 322,633 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_2048_32.circom` | 666,076 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_2048_64.circom` | 666,076 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_3072_32.circom` | 942,864 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_3072_64.circom` | 942,864 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_4096_32.circom` | 1,219,654 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_4096_64.circom` | 1,219,654 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_2048_32.circom` | 933,946 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_2048_64.circom` | 933,946 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_3072_32.circom` | 1,210,734 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_3072_64.circom` | 1,210,734 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_4096_32.circom` | 1,487,524 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_4096_64.circom` | 1,487,524 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha384_3_3072_48.circom` | 1,439,092 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha384_3_4096_48.circom` | 1,961,825 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha384_65537_3072_48.circom` | 1,706,962 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha384_65537_4096_48.circom` | 2,229,695 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha512_3_2048_64.circom` | 916,184 | partial | partial_preparation |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha512_3_4096_64.circom` | 1,615,390 | partial | partial_preparation |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/count-substring-occurrences-test.circom` | 526,335 | unsupported | no_eligible_units_due_to_unsupported_inspection |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-no-body-test.circom` | 535,950 | unsupported | no_eligible_units_due_to_unsupported_inspection |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-test.circom` | 1,570,377 | failed | no_eligible_prepared_units |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-with-body-mask-test.circom` | 1,571,913 | failed | no_eligible_prepared_units |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-with-header-mask-test.circom` | 1,571,657 | unsupported | no_eligible_units_due_to_unsupported_inspection |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-with-soft-line-breaks-test.circom` | 2,399,785 | failed | no_eligible_prepared_units |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/rsa-test.circom` | 190,945 | partial | partial_preparation |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/sha-test.circom` | 333,524 | unsupported | no_eligible_units_due_to_unsupported_inspection |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/common-v2/test/mocks/test_body_hash_regex_v2.circom` | 145,247 | partial | partial_preparation |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/common-v2/test/mocks/test_body_suffix_hasher.circom` | 168,823 | unsupported | no_eligible_units_due_to_unsupported_inspection |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/garanti/test/mocks/test_garanti_payer_details.circom` | 204,950 | partial | partial_preparation |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/namecheap/test/mocks/test_namecheap_transfer_details.circom` | 302,282 | partial | partial_preparation |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/paylah/test/mocks/test_paylah_payment_details.circom` | 122,342 | partial | partial_preparation |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/venmo/test/mocks/test_venmo_actor_id.circom` | 402,551 | partial | partial_preparation |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/venmo/test/mocks/test_venmo_send_id.circom` | 404,271 | partial | partial_preparation |

## 검사

Python E-01 회귀 3건, 결과 identity·분모 검사, 보호 경로 밖 컴파일 산출물 잔존 0건을 확인했다. `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 모두 통과했다. Cargo test의 로컬 fixture·외부 도구 의존 항목은 기존과 같이 ignored이며 실패는 0건이다.

## 비용·정리·한계

기록된 단계 시간 합계는 compile 3980.402초, discovery 4185.112초, preparation 12337.583초, plan 47.390초다. 동시 실행 때문에 합계는 campaign wall과 같지 않다.

초기 v1 setup은 Berry에 Classic 전용 환경 설정이 전달된 결함으로 1/9 성공했다. 원본은 보존하고 보정 구현·새 lock·깨끗한 checkout의 recovery-v2를 9개 전체에 적용했다. 측정 시작 시 `/bin/ps` 샌드박스 차단으로 생성된 값 없는 329개 디렉터리도 별도 이력으로 보존했다.

이 결과는 환경 구성과 구조 준비 적용성 조사다. setup 성공은 완전 준비나 의미 호환성을 뜻하지 않으며, 탐지 성능·결함 수·의미 동등성의 근거가 아니다. C-03 고정 결과는 수정하지 않았다.
