# M-01: E-01 컴파일 성공 entrypoint의 F-01 탐색기 재측정

- 담당: miiz
- 측정 시작: 2026-10-03
- 측정·정리 완료: 2026-10-05
- 기한: 2026-10-05
- 범위: E-01 원본 컴파일 성공 125개, 그중 제약 10만 이상 49개
- 실행: instance capture 포함 대상 탐색 → 준비 → plan
- zkFuzz 실행: 0회

## 결과

| 구분 | E-01 | M-01 |
|---|---:|---:|
| success | 18 | 97 |
| partial | 86 | 22 |
| unsupported | 18 | 0 |
| failed | 3 | 6 |

고정 F-01 바이너리 SHA-256: `f8c9f64defd3993ebd845279bc0a245857e23a1ae759ce175e94f369cdd9f4c1`.
E-01 최종 측정은 13:43–16:35 KST여서 프로젝트 이동 시간 19:30–20:16 KST와 겹치지 않았고, 경로 소실 오류도 관측되지 않았다.

## 저장소별 전후

| 저장소 | entrypoint | 대형 | E-01 | M-01 |
|---|---:|---:|---|---|
| `Galactica-corp/galactica-monorepo` | 25 | 0 | {"success": 3, "partial": 17, "unsupported": 5} | {"success": 23, "partial": 1, "failed": 1} |
| `anon-aadhaar/anon-aadhaar` | 3 | 2 | {"partial": 2, "unsupported": 1} | {"success": 2, "failed": 1} |
| `proofcarryingdata/zupass` | 5 | 0 | {"success": 3, "partial": 2} | {"success": 4, "partial": 1} |
| `selfxyz/self` | 42 | 32 | {"success": 6, "partial": 35, "unsupported": 1} | {"success": 22, "partial": 18, "failed": 2} |
| `zkemail/zk-email-verify` | 21 | 8 | {"success": 6, "partial": 5, "unsupported": 7, "failed": 3} | {"success": 17, "partial": 2, "failed": 2} |
| `zkp2p/zkp2p-v1-monorepo` | 29 | 7 | {"partial": 25, "unsupported": 4} | {"success": 29} |

## 제약 10만 이상 entrypoint 49개

| 저장소 | entrypoint | 제약 | E-01 | M-01 | 캡처 | 남은 사유 |
|---|---|---:|---|---|---|---|
| `anon-aadhaar/anon-aadhaar` | `packages/circuits/src/aadhaar-verifier.circom` | 1115080 | unsupported | failed | compiler_complete | preparation:prepare_process_timeout |
| `anon-aadhaar/anon-aadhaar` | `packages/circuits/test/circuits/extractor-test.circom` | 129004 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/ecdsa/test_brainpoolP224r1.circom` | 1992814 | partial | failed | compiler_complete | preparation:prepare_process_timeout |
| `selfxyz/self` | `circuits/circuits/tests/utils/ecdsa/test_brainpoolP256r1.circom` | 1847135 | partial | failed | compiler_complete | preparation:prepare_process_timeout |
| `selfxyz/self` | `circuits/circuits/tests/utils/extractQrData_tester.circom` | 205382 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha1_64321_4096.circom` | 429973 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha1_65537_2048.circom` | 322825 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha224_65537_2048.circom` | 322777 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_107903_4096.circom` | 501341 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_122125_4096.circom` | 465625 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_130689_4096.circom` | 465625 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_56611_4096.circom` | 429909 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_65537_2048.circom` | 322761 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_65537_3072.circom` | 322761 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha256_65537_4096.circom` | 322761 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsa/test_rsa_sha512_65537_4096.circom` | 322633 | partial | success | compiler_complete | — |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_2048_32.circom` | 666076 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_2048_64.circom` | 666076 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_3072_32.circom` | 942864 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_3072_64.circom` | 942864 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed<br>preparation:wrapper_compile_timed_out |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_4096_32.circom` | 1219654 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_3_4096_64.circom` | 1219654 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:unit_compile_timeout<br>preparation:wrapper_compile_failed<br>preparation:wrapper_compile_timed_out |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_2048_32.circom` | 933946 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_2048_64.circom` | 933946 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_3072_32.circom` | 1210734 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed<br>preparation:wrapper_compile_timed_out |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_3072_64.circom` | 1210734 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:unit_compile_timeout<br>preparation:wrapper_compile_failed<br>preparation:wrapper_compile_timed_out |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_4096_32.circom` | 1487524 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha256_65537_4096_64.circom` | 1487524 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:unit_compile_timeout<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha384_3_3072_48.circom` | 1439092 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha384_3_4096_48.circom` | 1961825 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:unit_compile_timeout<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha384_65537_3072_48.circom` | 1706962 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:unit_compile_timeout<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha384_65537_4096_48.circom` | 2229695 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:unit_compile_timeout<br>preparation:wrapper_compile_failed<br>preparation:wrapper_compile_timed_out |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha512_3_2048_64.circom` | 916184 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `selfxyz/self` | `circuits/circuits/tests/utils/rsapss/test_rsapss_sha512_3_4096_64.circom` | 1615390 | partial | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:wrapper_compile_failed |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/count-substring-occurrences-test.circom` | 526335 | unsupported | success | compiler_complete | — |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-no-body-test.circom` | 535950 | unsupported | success | compiler_complete | — |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-test.circom` | 1570377 | failed | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:unit_compile_timeout |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-with-body-mask-test.circom` | 1571913 | failed | partial | compiler_complete | preparation:compiled_size_or_compile_unavailable<br>preparation:compiled_size_unavailable<br>preparation:unit_compile_failed<br>preparation:unit_compile_timeout |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-with-header-mask-test.circom` | 1571657 | unsupported | failed | compiler_complete | preparation:prepare_process_timeout |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/email-verifier-with-soft-line-breaks-test.circom` | 2399785 | failed | failed | compiler_complete | preparation:prepare_process_timeout |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/rsa-test.circom` | 190945 | partial | success | compiler_complete | — |
| `zkemail/zk-email-verify` | `packages/circuits/tests/test-circuits/sha-test.circom` | 333524 | unsupported | success | compiler_complete | — |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/common-v2/test/mocks/test_body_hash_regex_v2.circom` | 145247 | partial | success | compiler_complete | — |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/common-v2/test/mocks/test_body_suffix_hasher.circom` | 168823 | unsupported | success | compiler_complete | — |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/garanti/test/mocks/test_garanti_payer_details.circom` | 204950 | partial | success | compiler_complete | — |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/namecheap/test/mocks/test_namecheap_transfer_details.circom` | 302282 | partial | success | compiler_complete | — |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/paylah/test/mocks/test_paylah_payment_details.circom` | 122342 | partial | success | compiler_complete | — |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/venmo/test/mocks/test_venmo_actor_id.circom` | 402551 | partial | success | compiler_complete | — |
| `zkp2p/zkp2p-v1-monorepo` | `circuits-circom/circuits/venmo/test/mocks/test_venmo_send_id.circom` | 404271 | partial | success | compiler_complete | — |

## 인스턴스 캡처와 남은 한계

컴파일러 캡처 완전: 125/125; 캡처 JSON 참조 기록: 125/125; 결과 JSON의 필수 캡처 값 보존 검사: True.

| 남은 사유 | 건수 |
|---|---:|
| preparation:compiled_size_or_compile_unavailable | 20 |
| preparation:compiled_size_unavailable | 20 |
| preparation:unit_compile_failed | 20 |
| preparation:wrapper_compile_failed | 18 |
| preparation:unit_compile_timeout | 8 |
| preparation:prepare_process_timeout | 6 |
| preparation:wrapper_compile_timed_out | 5 |
| preparation:wrapper_unsupported | 1 |
| preparation:plan_timeout | 1 |

## 측정 비용

| 단계 | n | 합계(초) | 중앙값(초) | 최댓값(초) |
|---|---:|---:|---:|---:|
| 탐색 | 125 | 9535.845 | 32.981 | 857.461 |
| 캡처 컴파일 | 125 | 1993.91 | 5.017 | 206.988 |
| 준비 | 125 | 8328.42 | 25.752 | 301.017 |
| plan | 119 | 314.2 | 0.183 | 31.145 |

단계별 시간은 겹쳐 실행된 worker의 합계이며 전체 wall time과 같지 않다.

## 실행·정리·검사

원본 setup과 compile 결과를 재사용했고 설치와 원본 compile을 다시 실행하지 않았다. 수치는 원시 `result.json` 125개에서 산출했다.

첫 샌드박스 시도는 `/bin/ps` 권한 차단으로 125개가 자식 실행 전에 중단돼 완결 결과를 만들지 않았다. 같은 lock의 샌드박스 밖 재실행 125개만 결과 분모에 썼다.

컴파일 산출물 및 진단 `.circom` 사본 25,033개, 32,673,355,992바이트를 manifest 기록과 크기·해시 재확인 후 삭제했다.

삭제 가능 잔존은 컴파일 산출물 0개, 보호 경로 밖 진단 `.circom` 0개다. 진단 사본의 `node_modules` 안 `.circom` 66,481개는 보존 규칙에 따라 남겼다.

필수 검사: M-01 Python 5건, 결과 검산, cargo fmt, 지정 clippy, cargo test 344건 통과(22건 ignored), 정리 잔존 검사 통과.

## 주장 한계

이 결과는 고정된 125개에서 구조적 대상 탐색·준비·plan의 적용성을 측정한다. 탐지 우위, 의미 동등성, 결함 존재, 전체 corpus 적용성을 뜻하지 않는다. N4-1 전체와 N5는 완료하지 않는다.
