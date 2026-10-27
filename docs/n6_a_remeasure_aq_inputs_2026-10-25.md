# A 재측정 2: aq 13개 구성 기준 입력 (2026-10-25)

**13/13 입력 검사 통과, 두 엔진별 330요청 index 준비 완료. aq J 실행 0회.** 담당 miiz. 표본 선택과 J 실행은 이번 작업에 포함하지 않는다.

miiz의 2026-10-25 승인, [N5 개정 8절](n5_amendment_b_judging_2026-10-17.md#8-탐색층-구성-기준-입력) 2–4·7항 및 같은 날 A 재측정 기록 2건을 적용했다. A 개발/탐색층이며 엄격층 공식 결과나 독립 평가와 합치지 않는다.

승인된 요청 수 순서대로 작업했다. **통과(4/4)**는 맥 정직 witness 생성, Rust·snarkjs 원본 R1CS 만족, 기록 R1CS SHA 일치를 뜻한다. 작업 초는 리비전별 `work-start/end.json` 구간(공통 준비·최종 검증 제외), 검사 초는 최종 canonical 검사 전체 시간이다. 전부 3시간 이내이며 `판정 불가(탐색층)`는 0개다. 요청 수는 회로 크기와 후보 수의 영향을 받는다.

| 리비전 | 제약 수 | 요청 수/엔진 | 상태 | 작업 초 | 검사 초 | J 추정 초/요청 v2.2 / v1 |
|---|---:|---:|---|---:|---:|---:|
| aq-006-1680f955c185 | 1,110,996 | 42 | 통과(4/4) | 122.52 | 42.86 | ≈198 / ≈195 |
| aq-007-0bb83f9eab0f | 1,081,440 | 42 | 통과(4/4) | 49.91 | 46.91 | ≈193 / ≈190 |
| aq-008-9c9e702d061d | 1,039,528 | 42 | 통과(4/4) | 38.21 | 36.91 | ≈185 / ≈183 |
| aq-011-93343c3cd34c | 104,771 | 33 | 통과(4/4) | 79.79 | 6.70 | ≈23 / ≈15 |
| aq-025-70328d3fd35e | 55,066 | 27 | 통과(4/4) | 112.43 | 3.37 | ≈12 / ≈8 |
| aq-026-2bcd7ed6110f | 54,442 | 27 | 통과(4/4) | 3.87 | 3.20 | ≈12 / ≈8 |
| aq-012-44d0df2ab46e | 276,422 | 24 | 통과(4/4) | 182.41 | 12.04 | ≈59 / ≈39 |
| aq-016-0a7d49b1c135 | 276,424 | 24 | 통과(4/4) | 60.20 | 12.05 | ≈59 / ≈39 |
| aq-024-6f6781246415 | 368,283 | 24 | 통과(4/4) | 315.34 | 14.30 | ≈79 / ≈52 |
| aq-017-9703bbce0c43 | 384,554 | 21 | 통과(4/4) | 72.73 | 14.44 | ≈83 / ≈54 |
| aq-040-da54d3e7bc8a | 2,017,059 | 12 | 통과(4/4) | 218.77 | 43.23 | ≈359 / ≈354 |
| aq-037-94fe3080fc18 | 1,667,456 | 6 | 통과(4/4) | 128.74 | 40.72 | ≈297 / ≈293 |
| aq-039-0ad3923f2f5b | 1,655,168 | 6 | 통과(4/4) | 154.98 | 43.33 | ≈295 / ≈291 |

입력·출처·검사·시간 기록: `runs/n6-a-remeasure-2026-10-25.noindex/inputs/<rev>/`. 큰 컴파일·witness·Rust 캐시: `/Volumes/zkfdo-jcache/n6-a-remeasure-aq/`. 아래 SHA는 최종 `input.json`을 검사·출처 기록과 대조한 값이다.

| 리비전 | 입력 SHA-256 |
|---|---|
| aq-006-1680f955c185 | `1306d1490fde47ab71a3ce72c9c37f57dc2b8022d6abae7ddcd3d629b8daf5d5` |
| aq-007-0bb83f9eab0f | `cb6400035658e009aa68f563b51459e10ffa3d031ff2ceb95475bc9bd352e7b7` |
| aq-008-9c9e702d061d | `0feb3d19f9e13c977aef45a10fb65af57e68794393fab9512db9671532f8d1f8` |
| aq-011-93343c3cd34c | `cc8ccc2e563c60ceafabd26bcedb7d18933cac0b732f9ca42a078ab6fdcccc22` |
| aq-025-70328d3fd35e | `64b682ae859f3870931cc4192319a1842ab9c1386595d1d5d110b352807cf1de` |
| aq-026-2bcd7ed6110f | `c88e50147ebb3ee221c240aca3fe68d4795b1898874a7b4b45980a56e4fc9162` |
| aq-012-44d0df2ab46e | `5ad467c4e76decb3a0882eb10c197ddd1b6cf2ced00d8369a7e3e6908c9ad1ae` |
| aq-016-0a7d49b1c135 | `b91d881aa99c5ae966930c6afaea03bd5b9cd839937a581baff77150ef2a46b5` |
| aq-024-6f6781246415 | `cab37e5c0d8a102580b32d2f713a6b71555d3c2bf034a576842d806d0890ce27` |
| aq-017-9703bbce0c43 | `7dab8471550d0fbdc911ce7a432e1ac855a1115c068dccee8aa82d6507114d0a` |
| aq-040-da54d3e7bc8a | `4ce29bfd9932417a45686cc326e82d2541df916d0b4576c02620d621dd7315c2` |
| aq-037-94fe3080fc18 | `a7c9785954e54664485359a15a93d2404a83071410c80ecdcd336def092824e6` |
| aq-039-0ad3923f2f5b | `eec7f3d030bdbc145970f84b0e0e879d9a00386a2a0f61fd414c2b04a4e04b52` |

동일 프로젝트의 입력 구성 형식·라이브러리를 공유하는 4개 계열로 생성기를 묶었다. 각 리비전의 기록 소스·entrypoint·원본 R1CS는 별도로 확인했다.

- **ZKsync 006·007·008:** 기록된 JWT 입력 라이브러리와 고정 seed의 새 RSA 시험 키·합성 JWT·서명. 커밋 대조 및 공개 런타임 의존성 해시 기록을 최종 재확인했다.
- **Panther 011·012·016·024·017:** 011은 새 시험 키로 활성 renewal의 서명·commitment·Merkle root를 재계산했다. 나머지 4개는 저장소의 0거래 시험 시나리오로 필요한 계정·UTXO·escrow 키와 암호문을 새로 계산했다. 012·016은 scalar/HMAC 방식, 024·017은 이전 point 암호문 방식이다. 0 금액·membership root·비활성 KYT와 024·017의 입력 계정 없음 표식(spend-key 0)을 유지하므로 활성 비영 거래 전체를 포괄하지 않는다.
- **rarimo QueryIdentity 025·026:** 같은 QueryIdentity·DG1·identity/SMT 소스를 공유한다. 합성 MRZ·새 시험 identity scalar·한 잎 SMT로 구성하고 모든 query selector를 활성화했다. 실제 여권·발급자 인증의 증거는 아니다.
- **zkemail regex 040·037·039:** 같은 FromAddrRegex 계열에서 고정 seed의 합성 발신자 헤더와 1,024바이트 padding을 사용했다. 테스트는 소스 참고만 했으며 생성 회로를 다시 쓰는 저장소 테스트는 실행하지 않았다. 039의 기록된 leave-one-out 소스 차이는 별도 출처 기록과 원본 R1CS SHA로 묶었다.

aq-024 첫 trial은 정직 witness 검사에서 이전 버전의 입력 계정 조건 차이로 실패했다. 원본 시험의 계정 없음 표식을 보존한 trial 2와 최종 입력은 통과했으며 실패 입력·기록도 보존했다. 생성 단계에서 후보·요청 행·ledger 후보 필드·J 출력은 읽지 않았다. 기존 비밀 값·패키지 설치·B 데이터 접근·다른 실행 프로세스 조작은 없었다.

**시간은 추정치다.** [시간 근거 v2](../runs/n6-a-remeasure-2026-10-25.noindex/verification/aq-time-estimates-v2.json)의 식은 `대상 제약 수 / 참조 제약 수 × 기존 A 평균 wall_seconds`다. 13개에는 직접 관측이 없어 JWT-RSA·regex는 `zkemail-fpmul-fixed`, Panther·QueryIdentity는 회로 크기 대용인 `inference-original`을 썼다. regex와 RSA는 알고리즘도 달라 근거가 특히 약하다. 두 지정 A state의 허용 timing 필드만 사용했으며 원본 SHA·대체 참조 민감도를 JSON에 기록했다.

참조 평균(v2.2 / v1): RSA fixed 9요청 34.02 / 33.52초, inference-original 69요청 42.14 / 27.65초. aq-035(3,250제약·12요청)는 0.294 / 0.216초, aq-036(2,900제약·604요청)은 2.327 / 2.239초이며 각 엔진 17건이 60초 이상이었다. 비슷한 제약 수에서도 시간이 크게 달라 선형 환산은 실측·상한·신뢰구간이 아니다.

**330요청 전부를 선택한다면** v2.2 약 11.1시간 + v1 약 10.2시간, 두 엔진 합계 **약 21.3시간**으로 추정한다. 컴파일·탐색·캐시·메모리·실행기 대기 때문에 실제 경과시간은 더 길어질 수 있다. 표본은 miiz가 별도로 선택한다.

**Prepare:** 새 `n6_a_remeasure_aq.py --action prepare --revisions …`만 실행했다. 엔진별 main 261·mem20 69요청의 기록된 범위를 그대로 보존했다. 입력 13개의 모든 관문을 확인한 뒤 고정 요청을 자동 복사해 `base_input`만 연결하고 요청 ID·순서·나머지 필드를 대조했다. 후보 payload·inventory 내용·J 출력은 열지 않았다. 기존 banyan 스크립트·출력과 공식 A index는 보존했다. 첫 prepare의 main 전용 검사 조건은 새 스크립트에서 보정하고 중단 기록·입력 감사 v1을 보존한 채 v2로 연결했다.

| 준비 산출물 | 요청 수 | SHA-256 |
|---|---:|---|
| [request-index-v1.json](../runs/n6-a-remeasure-2026-10-25.noindex/prepared-aq/request-index-v1.json) | 330 | `4f60f8dbd5fa4af0054f002d2bb2bcdc6a8d19ffdd094de17d81355d7fd58cec` |
| [request-index-v2.2.json](../runs/n6-a-remeasure-2026-10-25.noindex/prepared-aq/request-index-v2.2.json) | 330 | `1d0ea66aa677ad319dea34034af771fddc6fe19a57dddf2360f0ddb5aabc6f72` |
| [plan.json](../runs/n6-a-remeasure-2026-10-25.noindex/prepared-aq/plan.json) | 합계 660 | `72358f45c78b459928c6f9ed6adbf1eeef51fd4a29cf4036fb5a8b5c194afd70` |

**검증:** 최종 공유 생성기로 13/13 입력 바이트를 재현했고 새 스크립트 8개 `py_compile`이 통과했다. `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` 통과(376 passed, 24 ignored, 실패 0). 검사 함수는 기존 checker를 그대로 사용하고 A 전용 경로·시간 제한 어댑터를 두었다. 생성 시점 Panther·regex 스크립트 사본과 고정 출처 기록은 각 입력 폴더에 보존했다.

| 새 스크립트 | 최종 SHA-256 |
|---|---|
| [scripts/n6_a_check_aq_input.py](../scripts/n6_a_check_aq_input.py) | `51933346352b1bf7b923f104ec86b5941af7cb81bf42a041214b4673f85cdd91` |
| [scripts/n6_a_construct_input_from_addr.py](../scripts/n6_a_construct_input_from_addr.py) | `cf30746697295d30d2e2e47a5a93d5efcb5830075bdb797c68205638a5ac3322` |
| [scripts/n6_a_construct_input_panther.py](../scripts/n6_a_construct_input_panther.py) | `3468ae500fd94f980584b174e4e13965442d0d878e55cc20f3c561726dfc61ee` |
| [scripts/n6_a_construct_input_query_identity.py](../scripts/n6_a_construct_input_query_identity.py) | `4dc1bf368d3c33dc9e1e1126ab3a919c83b97037c51ec430804123ad53911414` |
| [scripts/n6_a_construct_input_zksync.py](../scripts/n6_a_construct_input_zksync.py) | `9687b07864fa3e5c1916e4ef46570df9ef3743c7ee03f6291d18189a3a0a15df` |
| [scripts/n6_a_panther_escrow.py](../scripts/n6_a_panther_escrow.py) | `63e4d11f2bd61da6f6119a0016c9246e0776808e23323c1499fcba769e3d6703` |
| [scripts/n6_a_panther_escrow_legacy.py](../scripts/n6_a_panther_escrow_legacy.py) | `6dac53abfb07fbefe05fed8d571ab8352c340932dbe544f5a11f5c03f661054a` |
| [scripts/n6_a_remeasure_aq.py](../scripts/n6_a_remeasure_aq.py) | `967a1e5b5e0d3ba5d36d958fbe760f9dfc5e03e87e0c06d3724381612c2d1f01` |

최종 [입력 감사 v2](../runs/n6-a-remeasure-2026-10-25.noindex/verification/input-audit-v2.json) SHA-256 `05c7f2d79603e538f183c9bd05e5f513058edd51cc31edfc4a791b0eda6960f7`. 시간 근거 v2 SHA-256 `32b5fcc8e173864e30cda9a792ea9eab4ccd71525b5e8e2f31f0543f82f6f3c2`. [Cargo 검사 기록](../runs/n6-a-remeasure-2026-10-25.noindex/verification/cargo-checks.json)에 명령·로그 해시를 보존했다.
