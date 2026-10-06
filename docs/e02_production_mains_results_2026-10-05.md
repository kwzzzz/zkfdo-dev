# E-02 대형 배포 main 컴파일·준비 결과 (2026-10-05)

담당: miiz. 상태: complete. zkFuzz 실행: 0회.

## 범위와 역할 분류

사전 고정한 경로 규칙으로 E-01의 329개 entrypoint를 배포 main 177개와 test/mock 하네스 152개로 나눴다. 모든 항목은 성공 여부와 무관하게 JSON 분모에 남겼다.

| 저장소 | 전체 | 배포 main | test/mock | E-01 compile | E-02 120초 | E-02 600초 | 새 compile 성공 | E-01 준비 | E-02 준비 측정 | 최종 준비 |
|---|---:|---:|---:|---|---|---|---:|---|---:|---|
| Galactica-corp/galactica-monorepo | 25 | 25 | 0 | success 25 | not_started 25 | not_started 25 | 0 | partial 17, success 3, unsupported 5 | 0 | - |
| anon-aadhaar/anon-aadhaar | 3 | 1 | 2 | success 1 | not_started 1 | not_started 1 | 0 | unsupported 1 | 1 | success 1 |
| celo-org/self | 79 | 38 | 41 | failure 38 | not_started 38 | not_started 38 | 0 | failed 38 | 0 | - |
| proofcarryingdata/zupass | 16 | 11 | 5 | failure 9, success 2 | not_started 2, success 9 | not_started 11 | 9 | partial 11 | 9 | success 9 |
| selfxyz/self | 141 | 88 | 53 | failure 85, success 1, timeout 2 | not_started 1, success 4, timeout 83 | not_started 5, success 82, timeout 1 | 86 | failed 83, partial 5 | 86 | partial 55, timeout 31 |
| semaphore-protocol/semaphore | 1 | 1 | 0 | failure 1 | success 1 | not_started 1 | 1 | failed 1 | 1 | success 1 |
| stealthdrop/stealthdrop | 3 | 3 | 0 | failure 3 | not_started 3 | not_started 3 | 0 | failed 3 | 0 | - |
| zkemail/zk-email-verify | 21 | 0 | 21 | - | - | - | 0 | - | 0 | - |
| zkp2p/zkp2p-v1-monorepo | 40 | 10 | 30 | timeout 10 | timeout 10 | success 4, timeout 6 | 4 | failed 10 | 4 | failed 1, timeout 3 |

실제 옵션은 E-01과 같은 기본 O1, 절차 문서의 O0는 표기 오류. 고정 문서·원본 명령·로그는 그대로 보존했다. 진단 캡처의 O0와 구분한다. 시간은 동시 실행 부하가 있는 관측값이다.

## 검수 보완: discovery timeout과 부분 준비

공유 JSON의 경로는 이 저장소 root 기준 상대 경로로 통일했다. 생성기는 미변환 절대 경로가 남으면 출력 전에 실패한다. 원시 측정 기록·판정·고정 절차는 변경하지 않았다.

discovery timeout 33건 모두 `instance-capture.json`이 존재하고 캡처 상태가 `captured`이다. 캡처 컴파일은 132.464–485.477초에 끝났으며, 이후 wrapper 생성·확인 컴파일 단계에서 discovery의 900초 예산을 소진했다. 캡처 실패나 원본 main 컴파일 실패로 해석하지 않는다. 중단 시점에 남은 wrapper는 항목당 307–803개다. 이는 생성된 `wrappers/*/target.circom` 수이며 전체 예정 조각 수나 컴파일 성공 수가 아니다. 확인 컴파일 로그 수를 별도로 표시하며, 종료 직전 진행 중 컴파일은 로그가 남지 않을 수 있다. 900초에서 캡처 컴파일 합계를 뺀 시간을 순수 wrapper 컴파일 시간으로 간주하지 않는다 (소스 스캔·캡처 읽기·조립·wrapper 생성 비용도 포함).

아래 캡처 시간은 `compile_seconds`의 재시도 합계이며 마지막 성공 시도 하나의 시간과 구분한다. 각 행의 원시 result·capture 경로와 SHA-256은 JSON의 `discovery_timeout_analysis.rows`에 있다. 최종 timeout 34건 중 나머지 1건(`e992d1360a21d0321cc229a9`)은 discovery 성공 후 prepare 300/900초 모두 timeout으로, 이 discovery 표에 합치지 않는다.

| 저장소 | entrypoint | 캡처 compile 합계(초) | 캡처 시도 | 생성 wrapper | 확인 compile 로그 |
|---|---|---:|---:|---:|---:|
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_ecdsa_secp384r1.circom` | 298.720 | 2 | 498 | 498 |
| selfxyz/self | `source_main:circuits/circuits/dsc/instances/dsc_sha256_ecdsa_secp384r1.circom` | 256.084 | 2 | 385 | 385 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha256_sha256_sha256_ecdsa_brainpoolP256r1.circom` | 341.022 | 2 | 543 | 543 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha512_sha512_sha512_ecdsa_brainpoolP512r1.circom` | 472.843 | 2 | 432 | 432 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha384_sha384_sha384_ecdsa_secp384r1.circom` | 349.804 | 2 | 399 | 399 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha1_sha1_sha1_ecdsa_secp256r1.circom` | 286.737 | 2 | 727 | 727 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha256_sha224_sha224_ecdsa_secp224r1.circom` | 282.539 | 2 | 539 | 539 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_ecdsa_brainpoolP256r1.circom` | 144.403 | 2 | 512 | 512 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha256_sha256_sha256_ecdsa_secp256r1.circom` | 132.464 | 2 | 581 | 581 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha384_sha384_sha384_ecdsa_brainpoolP512r1.circom` | 354.175 | 2 | 399 | 399 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha256_sha256_sha256_ecdsa_secp384r1.circom` | 250.342 | 2 | 579 | 579 |
| selfxyz/self | `source_main:circuits/circuits/dsc/instances/dsc_sha384_ecdsa_brainpoolP512r1.circom` | 306.189 | 2 | 320 | 320 |
| zkp2p/zkp2p-v1-monorepo | `source_main:circuits-circom/circuits/namecheap/namecheap_push.circom` | 152.847 | 1 | 333 | 333 |
| selfxyz/self | `source_main:circuits/circuits/dsc/instances/dsc_sha384_ecdsa_brainpoolP384r1.circom` | 171.033 | 2 | 333 | 333 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha256_sha256_sha256_ecdsa_brainpoolP384r1.circom` | 240.609 | 2 | 570 | 570 |
| selfxyz/self | `source_main:circuits/circuits/dsc/instances/dsc_sha256_ecdsa_brainpoolP256r1.circom` | 191.437 | 2 | 423 | 423 |
| zkp2p/zkp2p-v1-monorepo | `source_main:circuits-circom/circuits/garanti/garanti_send.circom` | 340.317 | 1 | 307 | 307 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha512_sha512_sha512_ecdsa_secp521r1.circom` | 234.132 | 2 | 484 | 484 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha384_sha384_sha384_ecdsa_secp384r1.circom` | 176.235 | 2 | 484 | 484 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha1_sha1_sha1_ecdsa_secp256r1.circom` | 400.183 | 2 | 760 | 760 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha224_sha224_sha224_ecdsa_brainpoolP224r1.circom` | 285.753 | 2 | 468 | 468 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha512_sha512_sha512_ecdsa_secp521r1.circom` | 454.159 | 2 | 432 | 432 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha512_sha512_sha512_ecdsa_brainpoolP512r1.circom` | 485.477 | 2 | 433 | 433 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_ecdsa_brainpoolP384r1.circom` | 448.518 | 2 | 463 | 463 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha256_sha256_sha224_ecdsa_secp224r1.circom` | 370.014 | 2 | 618 | 618 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha1_sha1_sha1_ecdsa_brainpoolP224r1.circom` | 194.595 | 2 | 803 | 803 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha256_sha224_sha224_ecdsa_secp224r1.circom` | 184.190 | 2 | 486 | 486 |
| zkp2p/zkp2p-v1-monorepo | `source_main:circuits-circom/circuits/paylah/paylah_registration.circom` | 216.847 | 1 | 340 | 340 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha256_sha256_sha224_ecdsa_secp224r1.circom` | 228.544 | 2 | 583 | 583 |
| selfxyz/self | `source_main:circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_ecdsa_secp256r1.circom` | 164.099 | 2 | 512 | 512 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha384_sha384_sha384_ecdsa_brainpoolP512r1.circom` | 296.963 | 2 | 470 | 470 |
| selfxyz/self | `source_main:circuits/circuits/register/instances/register_sha224_sha224_sha224_ecdsa_brainpoolP224r1.circom` | 178.959 | 2 | 552 | 552 |
| selfxyz/self | `source_main:circuits/circuits/dsc/instances/dsc_sha256_ecdsa_secp521r1.circom` | 311.647 | 2 | 409 | 409 |

부분 준비 55건의 **조각 유효 비율은 중앙값 97.674%, 최소 84.068%, 최대 100.000%**다. 각 entrypoint의 `unit_outcomes`에서 root를 제외한 전체 조각을 분모로, `verified_prepared=true`인 조각을 분자로 계산한 뒤 entrypoint별 비율을 동일 가중 집계했다. 후보 수·호출 위치 수나 단순 `reported_eligible` 비율이 아니다. **root 단위 준비 실패는 50/55건**이다. 조각 유효 비율 100%여도 root 실패 때문에 partial일 수 있다. 항목별 분자·분모·root 사유는 JSON의 `partial_preparation_analysis.rows`에 보존했다.


## 제약 10만 이상 배포 main

prepare 300/900 열은 프로세스 종료 상태이다. 최종 준비 열은 보존된 보고서에서 재검증한 상태로, 프로세스 success여도 일부 조각이나 원본 준비가 불완전하면 partial/failed일 수 있다.

| 저장소 | entrypoint | 제약 | compile 근거 | 120초 | 600초 | discovery | prepare 300 | prepare 900 | plan | 최종 준비 | 남은 사유 |
|---|---|---:|---|---|---|---|---|---|---|---|---|
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_rsapss_3_32_3072.circom` | 2072473 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsapss_65537_32_2048.circom` | 1592331 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_ecdsa_secp384r1.circom` | 4944906 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_ecdsa_secp384r1.circom` | 5416205 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register/instances/register_sha384_sha384_sha384_rsapss_65537_48_2048.circom` | 3070915 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_rsa_130689_4096.circom` | 1595309 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_rsapss_65537_32_3072.circom` | 1868951 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_ecdsa_brainpoolP256r1.circom` | 2474482 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_rsa_56611_4096.circom` | 1559593 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha512_sha512_sha512_ecdsa_brainpoolP512r1.circom` | 9888635 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha384_sha384_sha384_ecdsa_secp384r1.circom` | 6000245 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha1_sha1_sha1_ecdsa_secp256r1.circom` | 2254161 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha224_sha224_ecdsa_secp224r1.circom` | 2922749 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsa_65537_4096.circom` | 981146 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_ecdsa_brainpoolP256r1.circom` | 2474650 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha384_sha384_sha384_rsapss_65537_48_2048.circom` | 3071083 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_rsapss_65537_64_2048.circom` | 1592163 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha512_sha512_sha512_rsapss_65537_64_2048.circom` | 3084088 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_rsapss_65537_32_3072.circom` | 2340418 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_ecdsa_secp256r1.circom` | 2474482 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha384_sha384_sha384_ecdsa_brainpoolP512r1.circom` | 9702491 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_ecdsa_secp384r1.circom` | 4944738 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha384_ecdsa_brainpoolP512r1.circom` | 10657426 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsapss_3_32_2048.circom` | 1324386 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_rsapss_65537_32_4096.circom` | 2145741 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| zkp2p/zkp2p-v1-monorepo | `circuits-circom/circuits/namecheap/namecheap_push.circom` | 4768741 | compile_600 | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha384_ecdsa_brainpoolP384r1.circom` | 6955180 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_ecdsa_brainpoolP384r1.circom` | 4944738 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_rsa_65537_4096.circom` | 980978 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_ecdsa_brainpoolP256r1.circom` | 2945949 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha1_sha1_sha1_rsa_65537_4096.circom` | 760721 | compile_600_sensitivity | timeout | success | success | success | not_started | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha1_sha256_sha256_rsa_65537_4096.circom` | 837869 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha1_sha1_sha1_rsa_65537_4096.circom` | 760553 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_ecdsa_secp256r1.circom` | 2945949 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| anon-aadhaar/anon-aadhaar | `packages/circuits/src/aadhaar-verifier.circom` | 1115080 | e01_reused | not_started | not_started | success | not_started | success | success | success | - |
| selfxyz/self | `circuits/circuits/disclose/vc_and_disclose.circom` | 145731 | compile_120 | success | not_started | success | success | not_started | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha512_ecdsa_secp521r1.circom` | 11090103 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsapss_65537_64_2048.circom` | 1592331 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha1_ecdsa_secp256r1.circom` | 2912861 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_ecdsa_brainpoolP384r1.circom` | 5416205 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_rsa_107903_4096.circom` | 1631025 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_rsa_65537_4096.circom` | 1452445 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha512_sha512_sha512_rsa_65537_4096.circom` | 2222667 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_rsa_3_4096.circom` | 713033 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha1_sha1_sha1_rsa_64321_4096.circom` | 867701 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha384_sha384_sha384_ecdsa_brainpoolP384r1.circom` | 6000245 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/disclose/vc_and_disclose_kyc.circom` | 102406 | compile_120 | success | not_started | success | success | not_started | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha1_sha1_rsa_65537_4096.circom` | 901280 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha1_sha1_sha1_ecdsa_brainpoolP224r1.circom` | 2399632 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha512_ecdsa_brainpoolP512r1.circom` | 10668692 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha512_rsapss_65537_64_4096.circom` | 4563183 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha512_sha512_sha512_rsapss_65537_64_2048.circom` | 3083920 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha1_sha256_sha256_rsa_65537_4096.circom` | 838037 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha512_rsa_65537_4096.circom` | 3002556 | compile_600_sensitivity | timeout | success | success | success | not_started | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_aadhaar.circom` | 1222046 | compile_600 | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha1_ecdsa_brainpoolP256r1.circom` | 2912861 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha1_rsa_65537_4096.circom` | 1419421 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| zkp2p/zkp2p-v1-monorepo | `circuits-circom/circuits/garanti/garanti_send.circom` | 7613413 | compile_600 | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha512_sha512_sha512_ecdsa_secp521r1.circom` | 10310214 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/disclose/vc_and_disclose_id.circom` | 106209 | compile_120 | success | not_started | success | success | not_started | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_rsapss_65537_32_2048.circom` | 1592163 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha512_sha512_sha256_rsapss_65537_32_2048.circom` | 2610115 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_rsa_122125_4096.circom` | 1595309 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha384_sha384_sha384_ecdsa_secp384r1.circom` | 6000077 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsa_3_4096.circom` | 713201 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha1_sha1_sha1_ecdsa_secp256r1.circom` | 2253993 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha224_sha224_sha224_ecdsa_brainpoolP224r1.circom` | 2922913 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| zkp2p/zkp2p-v1-monorepo | `circuits-circom/circuits/garanti/garanti_registration.circom` | 6293444 | compile_600 | timeout | success | success | success | not_started | failure | failed | no_eligible_prepared_units |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_rsapss_65537_32_3072.circom` | 1869119 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha512_sha512_sha512_ecdsa_secp521r1.circom` | 10310046 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha512_sha512_sha512_ecdsa_brainpoolP512r1.circom` | 9888803 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_ecdsa_brainpoolP384r1.circom` | 4944906 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha224_ecdsa_secp224r1.circom` | 2768433 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha512_sha512_sha256_rsa_65537_4096.circom` | 1998930 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha256_sha256_sha256_rsapss_3_32_2048.circom` | 1324218 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_rsapss_65537_32_4096.circom` | 2617208 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha512_sha512_sha256_rsapss_65537_32_2048.circom` | 2609947 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha1_sha1_sha1_ecdsa_brainpoolP224r1.circom` | 2399464 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha224_sha224_ecdsa_secp224r1.circom` | 2922917 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register/instances/register_sha512_sha512_sha256_rsa_65537_4096.circom` | 1998762 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| zkp2p/zkp2p-v1-monorepo | `circuits-circom/circuits/paylah/paylah_registration.circom` | 4296665 | compile_600 | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha224_ecdsa_secp224r1.circom` | 2768601 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha384_rsapss_65537_48_3072.circom` | 4375620 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha512_sha512_sha512_rsa_65537_4096.circom` | 2222499 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register_id/instances/register_id_sha256_sha256_sha256_ecdsa_secp256r1.circom` | 2474650 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha384_ecdsa_secp384r1.circom` | 6955180 | compile_600_sensitivity | timeout | success | success | timeout | success | success | partial | partial_preparation |
| selfxyz/self | `circuits/circuits/register/instances/register_sha384_sha384_sha384_ecdsa_brainpoolP384r1.circom` | 6000077 | compile_600_sensitivity | timeout | success | success | timeout | timeout | not_started | timeout | prepare_900_timeout |
| selfxyz/self | `circuits/circuits/register/instances/register_sha384_sha384_sha384_ecdsa_brainpoolP512r1.circom` | 9702323 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/register/instances/register_sha224_sha224_sha224_ecdsa_brainpoolP224r1.circom` | 2922745 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |
| selfxyz/self | `circuits/circuits/dsc/instances/dsc_sha256_ecdsa_secp521r1.circom` | 9539862 | compile_600_sensitivity | timeout | success | timeout | not_started | not_started | not_started | timeout | discovery_timeout |

## 자동 라이브러리 경로

`package.json`, 셸, circomkit, hardhat, Makefile 계열 파일의 literal `-l`/include만 정적으로 읽었다. 설정 파일 디렉터리·가장 가까운 package root·저장소 root에 대해 실제로 존재하는 checkout 내부 디렉터리만 적용했다. entrypoint별 근거 파일·줄·literal·anchor와 적용 경로는 결과 JSON에 있다. 변수·glob·부재 경로는 추측하지 않았다.

## 비용과 정리

- compile_120: 11227.213초 (stage wall 합계)
- compile_600: 6220.041초 (stage wall 합계)
- compile_600_sensitivity: 18317.404초 (stage wall 합계)
- discovery: 59476.296초 (stage wall 합계)
- plan: 637.453초 (stage wall 합계)
- prepare_300: 16628.636초 (stage wall 합계)
- prepare_900: 23936.013초 (stage wall 합계)
- 정리: 179934개, 215685229526바이트 삭제
- 캡처 확인 부족으로 전체 보존한 항목: 1개. 근거는 정리 원장에 있다.

## 검사와 주장 한계

측정 중 필수 검사는 1회 실행했고 반복하지 않았다. 전체 host load average는 `2026-10-05T19:50:36.266800+00:00`부터 10초 간격으로 관측했다. 그 이전 부하는 unknown이며 이후 표본으로 소급하지 않았다. 아래 값은 준비 timeout 종료 시각에서 ±30초 이내 가장 가까운 표본이며 인과관계나 CPU 사용률을 뜻하지 않는다.

| 300초 timeout 항목 | 종료시각 UTC | 실측 초 | load 1/5/15분 | 표본 시각 차이(초) | 구간 내 최대 1분 load | 검사 중첩 |
|---|---|---:|---|---:|---|---|
| `033aaee54ddfdc6bb31dfdc6` | 2026-10-05T18:23:31.909428+00:00 | 300.26877295796294 | unknown | None | None | 없음 |
| `03f8cf2308c583bf7053faf1` | 2026-10-05T18:25:11.412342+00:00 | 300.1548635830404 | unknown | None | None | 없음 |
| `0ba6d38e4ef073f15343c36f` | 2026-10-05T19:04:54.299535+00:00 | 300.2324376660399 | unknown | None | None | 없음 |
| `0c0bfd9c9c7f4b01f154c062` | 2026-10-05T19:05:47.991262+00:00 | 300.27338558388874 | unknown | None | None | 없음 |
| `12635f5b4c03e4034f0c5772` | 2026-10-05T19:30:38.355667+00:00 | 300.31946354091633 | unknown | None | None | 없음 |
| `17e998628fd8b8d306d2e0ae` | 2026-10-05T19:46:58.319276+00:00 | 300.3749958749395 | unknown | None | None | cargo clippy --all-targets --all-features -- -D warnings, cargo test |
| `261dac47a72aec2b3d896e5a` | 2026-10-05T20:26:04.574206+00:00 | 300.20513920800295 | 13.24/16.45/17.24 | -3.388132 | 23.73583984375 | 없음 |
| `2f82ff130583e8b49d94486a` | 2026-10-05T20:48:07.363729+00:00 | 300.2912190830102 | 16.44/15.27/15.62 | -3.902622 | 17.69970703125 | 없음 |
| `30cfe1e677dfd34434a23633` | 2026-10-05T20:55:09.090811+00:00 | 300.27127654105425 | 12.93/14.09/14.96 | 4.914339 | 17.42333984375 | 없음 |
| `340c1bae08fb02421c9f0e25` | 2026-10-05T21:09:23.724704+00:00 | 300.39996529195923 | 13.52/13.95/14.26 | 1.853125 | 18.115234375 | 없음 |
| `3675fbbf9bc09a3a0bd79db8` | 2026-10-05T21:19:10.397757+00:00 | 300.16916145803407 | 15.61/16.97/15.96 | -4.036957 | 23.3193359375 | 없음 |
| `4459456e6d7e98304d6be7eb` | 2026-10-05T22:03:02.551218+00:00 | 300.21869745803997 | 17.68/13.26/12.78 | -1.401127 | 18.83935546875 | 없음 |
| `4ba27a8202ea746ec6a51fac` | 2026-10-05T22:10:35.478829+00:00 | 300.1619100420503 | 13.48/15.18/14.29 | -3.851097 | 22.1943359375 | 없음 |
| `560810ce48aa7cc329f5f54e` | 2026-10-05T22:45:22.844157+00:00 | 300.227313957992 | 16.72/14.18/13.43 | 1.833181 | 19.0283203125 | 없음 |
| `592d0cadd8913033eb634dba` | 2026-10-05T23:06:30.739012+00:00 | 300.1953299168963 | 8.58/11.00/12.31 | -4.336057 | 14.95361328125 | 없음 |
| `5a787bb652598bf9a41d0aed` | 2026-10-05T23:15:34.345632+00:00 | 300.21925054094754 | 12.92/11.92/12.41 | 2.612988 | 14.2763671875 | 없음 |
| `5edbf37a391cbba50c57f990` | 2026-10-05T23:26:21.214240+00:00 | 300.13416454195976 | 11.31/11.05/11.61 | -3.674675 | 12.86865234375 | 없음 |
| `61232cfca281f5cc8b3cb8dc` | 2026-10-05T23:40:37.219923+00:00 | 300.23592191701755 | 15.75/13.40/12.23 | 1.196664 | 22.7626953125 | 없음 |
| `6b84f6c71c656a9985f1ba3d` | 2026-10-05T23:47:48.846611+00:00 | 300.1362232080428 | 12.02/12.89/12.53 | 0.03167 | 18.033203125 | 없음 |
| `6cfed982cf5c5a85ee3c69a0` | 2026-10-06T00:06:02.677582+00:00 | 300.1173421670683 | 7.50/10.71/11.98 | -2.665396 | 15.001953125 | 없음 |
| `7363bafb0b6181fd53e91895` | 2026-10-06T00:09:58.125136+00:00 | 300.1702354999725 | 11.60/10.80/11.65 | 2.135138 | 12.9130859375 | 없음 |
| `7382e4c8c32eb4bf5eb7f60f` | 2026-10-06T00:26:55.775884+00:00 | 300.1248272500234 | 11.50/12.79/12.40 | -4.398854 | 16.96484375 | 없음 |
| `75bbb6863d33e29f7c6ca66b` | 2026-10-06T00:33:32.785510+00:00 | 300.13547791703604 | 13.79/13.09/12.61 | -0.930926 | 15.50537109375 | 없음 |
| `7aad0c6d04c3db1e4469597a` | 2026-10-06T00:42:53.776209+00:00 | 300.18329933297355 | 12.54/15.37/14.46 | -1.300103 | 26.61572265625 | 없음 |
| `7cd9bb3aeac4aaba586971ec` | 2026-10-06T00:49:47.204316+00:00 | 300.1970779999392 | 12.62/13.00/13.56 | -4.396889 | 19.53955078125 | 없음 |
| `7e3a4e278daeec243cc0eea4` | 2026-10-06T00:59:06.060724+00:00 | 300.1490052919835 | 19.55/15.24/14.23 | -2.577833 | 21.7392578125 | 없음 |
| `7fffba7903b97e73ada2034e` | 2026-10-06T01:14:12.584603+00:00 | 300.28296016703825 | 12.50/11.62/12.23 | 1.827363 | 13.447265625 | 없음 |
| `84302f8db878ba8d17c952cd` | 2026-10-06T01:19:35.534338+00:00 | 300.2320453750435 | 15.40/12.57/12.32 | -0.884905 | 17.57080078125 | 없음 |
| `84662c52e2b16680f8cfef6c` | 2026-10-06T01:41:59.711899+00:00 | 300.12958708405495 | 10.65/13.96/14.18 | -3.792291 | 21.65625 | 없음 |
| `86655f477a919c332f50b4a8` | 2026-10-06T01:44:09.947513+00:00 | 300.1408235830022 | 15.09/13.96/14.10 | -3.948465 | 15.79638671875 | 없음 |
| `8885da5d2871ec3cd4cb546a` | 2026-10-06T02:05:06.929475+00:00 | 300.17263141600415 | 17.87/13.93/13.44 | 0.464654 | 18.91015625 | 없음 |
| `8a7ca1d4b826e891988995b9` | 2026-10-06T02:06:55.819940+00:00 | 300.1552819579374 | 11.77/12.95/13.11 | 1.731343 | 18.91015625 | 없음 |
| `8ad5744b32ffd9ce7f7a9d6a` | 2026-10-06T02:23:12.847627+00:00 | 300.1838600829942 | 9.43/10.66/11.61 | -4.267655 | 14.900390625 | 없음 |
| `8c059cd14f1e535534a3de21` | 2026-10-06T02:33:33.120250+00:00 | 300.22610558301676 | 14.39/12.62/11.98 | -3.848623 | 16.34521484375 | 없음 |
| `94fcde252e20f3dcbd0f6192` | 2026-10-06T02:48:46.490692+00:00 | 300.21348108397797 | 11.23/12.13/11.80 | 3.880395 | 17.54052734375 | 없음 |
| `960bab7e8bfa09226faabfa7` | 2026-10-06T02:52:09.398599+00:00 | 300.14336779201403 | 11.35/11.33/11.49 | 1.175433 | 17.54052734375 | 없음 |
| `9dedfd04d29534bcf602678b` | 2026-10-06T03:28:22.297274+00:00 | 300.1526942499913 | 11.06/12.24/12.20 | 0.783007 | 15.8818359375 | 없음 |
| `a11d8df71d6f35a4990af89a` | 2026-10-06T03:29:28.154331+00:00 | 300.21795037505217 | 28.05/15.85/13.49 | -4.878034 | 28.04736328125 | 없음 |
| `a138964361e9e791d9fb8a11` | 2026-10-06T03:46:31.063029+00:00 | 300.22691616695374 | 16.33/15.12/14.46 | 3.415367 | 18.3623046875 | 없음 |
| `a97b5303aac4ce1483d4249e` | 2026-10-05T18:56:06.450465+00:00 | 300.26676174998283 | unknown | None | None | 없음 |
| `bd102320e9d6e6a290bc8f22` | 2026-10-05T19:23:49.811629+00:00 | 300.3116230419837 | unknown | None | None | 없음 |
| `c998b8b35bb3439933702dbe` | 2026-10-05T20:06:04.337472+00:00 | 300.2051725840429 | 23.09/17.59/17.18 | 4.450495 | 24.77587890625 | 없음 |
| `cbaeae4ed92a9d959a7e7009` | 2026-10-05T20:18:46.423191+00:00 | 300.2561359159881 | 17.44/18.00/17.53 | 4.01723 | 25.740234375 | 없음 |
| `ccdb2948715caf29e315c2de` | 2026-10-05T20:31:17.916467+00:00 | 300.18113525002263 | 18.77/17.28/17.30 | 3.851901 | 22.8984375 | 없음 |
| `cec46d605e795c0bc14340a7` | 2026-10-05T20:41:25.283141+00:00 | 300.2342824579682 | 15.07/15.71/16.16 | -2.639168 | 21.76513671875 | 없음 |
| `d2d807fafc0d23f1e6ae15bf` | 2026-10-05T21:08:38.692944+00:00 | 300.16961170895956 | 12.14/13.71/14.19 | -3.203326 | 20.4931640625 | 없음 |
| `dcc4c28bf163556fa1879a69` | 2026-10-05T21:36:12.315235+00:00 | 300.4523834170541 | 11.26/12.66/14.58 | -3.801423 | 13.10205078125 | 없음 |
| `e39703c8086479907f4d4561` | 2026-10-05T21:48:19.611047+00:00 | 300.32193562504835 | 12.58/12.06/13.09 | 0.003983 | 16.841796875 | 없음 |
| `e5595955c702d72ee8dfc266` | 2026-10-05T22:14:38.177214+00:00 | 300.1699129169574 | 14.21/14.80/14.35 | 3.694289 | 15.8828125 | 없음 |
| `e992d1360a21d0321cc229a9` | 2026-10-05T22:17:40.718397+00:00 | 300.1708080410026 | 15.52/16.63/15.31 | 1.326761 | 24.216796875 | 없음 |

- `cargo fmt`: passed
- `cargo clippy --all-targets --all-features -- -D warnings`: passed
- `cargo test`: passed
- `python3 -m unittest tests/e02_incremental_cleanup_test.py tests/e02_measurement_test.py tests/e02_production_mains_test.py`: passed

2026-10-06 검수 보완 후 필수 검사: passed. `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`의 추가 실행 기록은 `runs/e02-production-mains-2026-10-05/review-correction-2026-10-06/checks.json`에 있으며, 기존 측정 중 검사 기록과 분리했다.

이 결과는 고정 commit의 배포 main compile과 구조적 준비 적용성만 측정한다. zkFuzz를 실행하지 않았고 결함 탐지 성능이나 일반적 의미 동등성을 입증하지 않는다.
