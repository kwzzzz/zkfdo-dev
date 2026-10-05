# C-03 환경 구성·설정 entrypoint 포함 준비 조사

담당 miiz · 기한 2026-10-07 · 상태: complete

[사전 고정 절차](c03_corpus_procedure_2026-10-02.md) · [전체 기계 판독 기록](c03_corpus_results_2026-10-02.json)

C-02의 무설치 관측을 보존하고, 자동 환경 구성 전후의 동일 entrypoint를 비교했다. 출처층은 겹치며 team_curated는 날짜 조건을 적용한 주 집계와 별도로 제시한다. 저장소의 production 분류는 모든 test/example 파일의 실서비스 사용을 뜻하지 않는다.

## 분모와 컴파일 전후 비교

| 집합 | 저장소 | 설치 전/후 entrypoint | paired | 전 성공 | 후 성공 |
|---|---:|---:|---:|---:|---:|
| 전체 | 80 | 3629/3677 | 3629 | 2308/3629 (63.6%) | 2470/3629 (68.1%) |
| 기존 조건 충족 주 집계 | 75 | 3588/3636 | 3588 | 2303/3588 (64.2%) | 2445/3588 (68.1%) |
| team_curated 전체 | 14 | 190/190 | 190 | 16/190 (8.4%) | 38/190 (20.0%) |
| C-02 포함 집합 | 65 | 3470/3518 | 3470 | 2297/3470 (66.2%) | 2437/3470 (70.2%) |

| 성격 층 | 전체 저장소/후 entrypoint | 주 집계 저장소/후 entrypoint | paired 전 성공 | paired 후 성공 | 후 컴파일 성공(전체) | 준비 상태(전체) |
|---|---:|---:|---:|---:|---:|---|
| production | 26/656 | 25/656 | 97/656 (14.8%) | 174/656 (26.5%) | 174/656 (26.5%) | {'failed': 483, 'partial': 71, 'success': 44, 'unsupported': 58} |
| library | 10/377 | 9/372 | 280/377 (74.3%) | 292/377 (77.5%) | 292/377 (77.5%) | {'failed': 91, 'partial': 66, 'success': 128, 'unsupported': 92} |
| tool_benchmark | 13/2223 | 13/2223 | 1802/2223 (81.1%) | 1828/2223 (82.2%) | 1828/2223 (82.2%) | {'failed': 409, 'partial': 622, 'success': 658, 'unsupported': 534} |
| education_example | 7/81 | 6/73 | 43/81 (53.1%) | 54/81 (66.7%) | 54/81 (66.7%) | {'failed': 28, 'partial': 10, 'success': 28, 'unsupported': 15} |
| unknown | 24/340 | 22/312 | 86/292 (29.5%) | 122/292 (41.8%) | 170/340 (50.0%) | {'failed': 178, 'partial': 63, 'success': 23, 'unsupported': 76} |

| 출처(중복) | 저장소 | 설치 후 entrypoint | paired 전 성공 | paired 후 성공 |
|---|---:|---:|---:|---:|
| c02_config_addition | 4 | 31 | 0/31 (0.0%) | 0/31 (0.0%) |
| github_top200 | 55 | 3296 | 2294/3296 (69.6%) | 2348/3296 (71.2%) |
| sok_2026 | 19 | 469 | 69/421 (16.4%) | 155/421 (36.8%) |
| team_curated | 14 | 190 | 16/190 (8.4%) | 38/190 (20.0%) |
| zkbugs | 19 | 469 | 69/421 (16.4%) | 155/421 (36.8%) |

### 조건을 구분한 과거·현재 관측

| 관측 | 환경·분모 조건 | compile 성공 |
|---|---|---:|
| C-02 과거 | 의존성 무설치·기존 include 규칙·당시 알려진 entrypoint | 2296/3470 (66.2%) |
| C-03 설치 전 | C-03 include 규칙·같은 key/commit/source/config/settings의 paired 분모 | 2308/3629 (63.6%) |
| C-03 설치 후 | 고정 자동 setup·최종 after-v4·위와 동일한 paired 분모 | 2470/3629 (68.1%) |

C-02와 C-03은 수집·include·entrypoint 조건이 다르다. 이 표는 조건을 표시한 기술 통계이며 차이를 설치의 인과 효과나 일반 적용성으로 추정하지 않는다.

### 알려진 entrypoint가 없는 저장소

아래 저장소는 저장소 분모에 남겼다. `no_known_entrypoint`는 조사된 목록에서 알려진 main/설정 entrypoint가 없다는 뜻이며 소스에 entrypoint가 없다는 증명은 아니다. entrypoint나 실행 건수를 만들어 넣지 않았다. 설정·목록 조사 실패는 JSON의 inventory_failures에 보존했다.

| 저장소 | entrypoint 가용성 | 알려진 전/후 개수 | 설치 후 compile | 설치 후 preparation | 미시작/미판정 이유 |
|---|---|---:|---|---|---|
| Hinkal-Protocol/Hinkal-Contracts-Circuits | no_known_entrypoint | 0/0 | not_started | not_started | no_known_entrypoint |

### entrypoint 목록의 알려진 한계

저장소별 목록 상태: {'incomplete': 9, 'no_recorded_failure': 71}. `no_recorded_failure`는 기록된 목록 실패가 없다는 뜻이며 소스 전체를 빠짐없이 열거했다는 증명이 아니다. 설정·submodule·추적 파일 목록 단계가 실패하면 아직 열거하지 못한 entrypoint가 있을 수 있다. 아래 저장소와 알려진 entrypoint는 전체 분모에 유지하며, 알 수 없는 추가 개수를 0으로 확정하지 않는다.

| 저장소 | 목록 상태 | 알려진 후 entrypoint | 이유 |
|---|---|---:|---|
| banyancomputer/hot-proofs-blake3-circom | incomplete | 4 | ['config_without_circomkit_context'] |
| erhant/circom101 | incomplete | 43 | ['config_without_circomkit_context'] |
| holyaustin/Filecoin-Forge | incomplete | 5 | ['submodule_command_failed'] |
| selfxyz/self | incomplete | 141 | ['submodule_unsupported_protocol'] |
| tiktok-privacy-innovation/trustless-attestation-verification-circom | incomplete | 4 | ['config_missing_file'] |
| vacp2p/research | incomplete | 5 | ['submodule_command_failed'] |
| worm-privacy/proof-of-burn | incomplete | 50 | ['config_missing_file'] |
| zkFHE/circomlib-fhe | incomplete | 42 | ['submodule_command_failed'] |
| zksecurity/zkbugs | incomplete | 113 | ['submodule_command_failed'] |

paired 제외·추가 상태: {'after_only': 48, 'paired': 3629}. 성공·실패를 보고 대상을 제거하지 않았다.

## 환경 구성·설정 생성·준비

| 항목 | 결과 |
|---|---|
| 자동 setup 상태 | {'setup_failure': 20, 'success': 60} |
| setup 실패 유형(repo별 중복 제거) | {'ambiguous_lockfiles': 1, 'invalid_package_metadata': 1, 'lockfile_without_package_json': 2, 'package_install_command_failed': 1, 'package_install_engine_version': 1, 'package_install_lockfile_mismatch': 2, 'package_install_network': 1, 'submodule_command_failed': 4, 'submodule_unsupported_protocol': 1, 'unsupported_yarn_modern': 10} |
| setup 실패 유형(단계 occurrence) | {'ambiguous_lockfiles': 4, 'invalid_package_metadata': 65, 'lockfile_without_package_json': 3, 'package_install_command_failed': 1, 'package_install_engine_version': 1, 'package_install_lockfile_mismatch': 2, 'package_install_network': 1, 'submodule_command_failed': 4, 'submodule_unsupported_protocol': 1, 'unsupported_yarn_modern': 16} |
| 설치 후 lockfile 인덱스 상태/실패 | {'verified': 80} / {} |
| 결과 lockfile 수/새 생성 수 | 114/37 |
| config_generated 전/후 | 42/42 |
| 수동 package/include 수선 | 0 (결측 0 repo) |
| 수동 수집 transport 재시도 | 2 (결측 0 repo) |
| 전체 수동 개입 | 2 (알려진 합계 2, 결측 0 repo) |
| 자동 준비 상태(원본 compile 포함) | {'failed': 1189, 'partial': 832, 'success': 881, 'unsupported': 775} |
| 원본 기록의 컴포넌트 준비 상태 | {'failed': 833, 'partial': 942, 'success': 881, 'unsupported': 1021} |
| 완전 준비의 범위(root_only/with_fragments/unknown) | {'root_only': 460, 'with_fragments': 421, 'unknown': 0} |
| 준비 실패 유형 | {'manifest_generation_unsupported': 81, 'no_eligible_prepared_units': 30, 'no_eligible_units_due_to_unsupported_inspection': 694, 'original_compile_assertion_or_type': 32, 'original_compile_compiler_or_tool_error': 181, 'original_compile_compiler_version': 12, 'original_compile_missing_include': 888, 'original_compile_non_quadratic': 20, 'original_compile_timeout': 26, 'partial_preparation': 832} |

자동 완전 준비는 원본 entrypoint 컴파일 성공과 root·모든 고유 단위의 준비·wrapper 컴파일·미지원 없음·plan 성공을 모두 요구한다. 원본 컴파일이 실패하면 컴포넌트 준비가 성공/partial이어도 자동 준비 성공으로 세지 않는다. 원본 준비 상태·개수는 별도로 보존하고 automatic_preparation_outcome만 파생했다. **partial**은 재확인된 유효 단위가 있으나 전체 요건에 명시적 실패가 있는 상태다. 유효 단위가 없으면 failed/unsupported, 증거 결측은 unknown으로 보존한다. prepare 프로세스 exit 0 자체는 준비 성공이 아니다. 완전 성공 중 discovery.unique_compile_units가 0인 root_only, 양수인 with_fragments, 개수 미확인을 별도로 센다. root_only는 조각 준비 성공의 증거로 쓰지 않는다.

### 환경 구성 상태별 조건부 결과

고정된 환경 정책은 신뢰한 Yarn Classic만 지원한다. 다른 Yarn 버전·package manager/lockfile 비호환과 설치 실패는 환경 구성 정책의 한계일 수 있으므로 모든 실패를 zkfDO의 한계로 해석하지 않는다. 아래는 조건부 기술 통계이며 setup 실패·미확인 저장소도 전체 집계에 남겼다. setup 성공 부분집합을 전체 적용성으로 대신하지 않는다.

| setup 조건 | 저장소 | 알려진 후 entrypoint | 후 컴파일 성공 | 준비 상태 |
|---|---:|---:|---:|---|
| success | 60 | 2284 | 1834/2284 (80.3%) | {'failed': 475, 'partial': 608, 'success': 635, 'unsupported': 566} |
| failure | 20 | 1393 | 684/1393 (49.1%) | {'failed': 714, 'partial': 224, 'success': 246, 'unsupported': 209} |
| unknown | 0 | 0 | 0/0 (산출 불가) | {} |

## production 저장소의 제약 10만 이상

경로 역할을 함께 표시한다. 이 목록은 저장소 성격 기준이며 개별 회로의 배포 사용을 인증하지 않는다.

| 저장소 | 경로 | 경로 역할 | 제약 수 | 준비 | 실패 유형 |
|---|---|---|---:|---|---|
| DoraFactory/Vota-Circuits | circuits/maci/power/prod/tally.circom | ['unclassified'] | 4802568 | failed | ['compiled_size_or_compile_unavailable', 'compiled_size_unavailable', 'discovery_unsupported', 'inspection_unsupported', 'plan_failure', 'unit_compile_failed', 'unit_compile_timeout'] |
| iden3/circuits | circuits/credentialAtomicQueryV3.circom | ['unclassified'] | 114758 | partial | ['compiled_size_or_compile_unavailable', 'compiled_size_unavailable', 'discovery_unsupported', 'inspection_unsupported', 'unit_compile_failed', 'wrapper_compile_failed'] |
| iden3/circuits | circuits/credentialAtomicQueryV3OnChain-16-16-64-16-32.circom | ['unclassified'] | 135876 | unsupported | ['discovery_unsupported', 'inspection_unsupported', 'plan_failure'] |
| iden3/circuits | circuits/credentialAtomicQueryV3OnChain.circom | ['unclassified'] | 225612 | unsupported | ['discovery_unsupported', 'inspection_unsupported', 'plan_failure'] |
| iden3/circuits | circuits/credentialAtomicQueryV3Universal.circom | ['unclassified'] | 129263 | unsupported | ['discovery_unsupported', 'inspection_unsupported', 'plan_failure'] |
| iden3/circuits | circuits/linkedMultiQuery.circom | ['unclassified'] | 381182 | unsupported | ['discovery_unsupported', 'inspection_unsupported', 'plan_failure'] |
| iden3/circuits | circuits/linkedMultiQuery3.circom | ['unclassified'] | 116498 | unsupported | ['discovery_unsupported', 'inspection_unsupported', 'plan_failure'] |
| iden3/circuits | circuits/linkedMultiQuery5.circom | ['unclassified'] | 192122 | unsupported | ['discovery_unsupported', 'inspection_unsupported', 'plan_failure'] |
| pantherfoundation/panther-core | circuits/circuits/mainZAccountRenewalV1.circom | ['unclassified'] | 111270 | partial | ['compiled_size_or_compile_unavailable', 'compiled_size_unavailable', 'discovery_unsupported', 'inspection_unsupported', 'unit_compile_failed', 'wrapper_compile_failed'] |
| pantherfoundation/panther-core | circuits/circuits/mainZSwapV1.circom | ['unclassified'] | 276422 | unsupported | ['discovery_unsupported', 'inspection_unsupported', 'plan_failure'] |
| pantherfoundation/panther-core | circuits/circuits/mainZTransactionV1.circom | ['unclassified'] | 260153 | unsupported | ['discovery_unsupported', 'inspection_unsupported', 'plan_failure'] |
| rarimo/passport-zk-circuits | circuits/lib/circuits/ec/m.circom | ['unclassified'] | 815996 | unsupported | ['manifest_generation_unsupported'] |
| rarimo/passport-zk-circuits | circuits/lib/circuits/eth/m.circom | ['unclassified'] | 240360 | partial | ['discovery_unsupported', 'inspection_unsupported'] |
| rarimo/passport-zk-circuits | circuits/lib/circuits/signatures/m.circom | ['unclassified'] | 733264 | partial | ['compiled_size_or_compile_unavailable', 'compiled_size_unavailable', 'discovery_unsupported', 'inspection_unsupported', 'unit_compile_failed', 'unit_compile_timeout', 'wrapper_compile_failed'] |
| tanctl/zylith-old | circuits/private_liquidity.circom | ['unclassified'] | 311639 | partial | ['compiled_size_or_compile_unavailable', 'compiled_size_unavailable', 'discovery_unsupported', 'inspection_unsupported', 'unit_compile_failed', 'wrapper_compile_failed', 'wrapper_unsupported'] |
| tanctl/zylith-old | circuits/private_swap_exact_out_one_for_zero.circom | ['unclassified'] | 2411961 | partial | ['compiled_size_or_compile_unavailable', 'compiled_size_unavailable', 'discovery_unsupported', 'inspection_unsupported', 'unit_compile_failed', 'wrapper_compile_failed'] |
| tanctl/zylith-old | circuits/private_swap_exact_out_zero_for_one.circom | ['unclassified'] | 2411945 | partial | ['compiled_size_or_compile_unavailable', 'compiled_size_unavailable', 'discovery_unsupported', 'inspection_unsupported', 'unit_compile_failed', 'wrapper_compile_failed'] |
| tanctl/zylith-old | circuits/private_swap_one_for_zero.circom | ['unclassified'] | 2409993 | partial | ['compiled_size_or_compile_unavailable', 'compiled_size_unavailable', 'discovery_unsupported', 'inspection_unsupported', 'unit_compile_failed', 'wrapper_compile_failed'] |
| tanctl/zylith-old | circuits/private_swap_zero_for_one.circom | ['unclassified'] | 2409977 | partial | ['compiled_size_or_compile_unavailable', 'compiled_size_unavailable', 'discovery_unsupported', 'inspection_unsupported', 'unit_compile_failed', 'wrapper_compile_failed'] |
| tanctl/zylith-old | circuits/test/fixtures/clmm_step_wrapper.circom | ['test'] | 129393 | success | [] |
| tangle-network/protocol-solidity | circuits/main/poseidon_vanchor_16_2.circom | ['unclassified'] | 290196 | unsupported | ['manifest_generation_unsupported'] |
| tangle-network/protocol-solidity | circuits/main/poseidon_vanchor_16_8.circom | ['unclassified'] | 290388 | unsupported | ['manifest_generation_unsupported'] |
| tangle-network/protocol-solidity | circuits/main/vanchor_forest_16_2.circom | ['unclassified'] | 331892 | unsupported | ['manifest_generation_unsupported'] |
| tangle-network/protocol-solidity | circuits/main/vanchor_forest_16_8.circom | ['unclassified'] | 332084 | unsupported | ['manifest_generation_unsupported'] |
| Zellic/zkerc20 | circuits/circuit.circom | ['unclassified'] | 331643 | partial | ['discovery_unsupported', 'inspection_unsupported'] |

수집 transport 재시도는 FlynnSC/zk-hunt, Railgun-Privacy/circuits-ppoi에 대한 동일 pinned SHA의 재시도이며 초기 실패 기록을 보존했다. package 설치·include 수선 횟수와 별도로 수동 개입에 포함한다. [재시도 기록](../runs/c03-corpus-2026-10-02/collection-retries-v2.json), SHA-256 `84dd31d349ba899f3e89086a7709705d4649907a66ef9656eeddd7eaecb14851`.

## 비용·검사·해석

아래 표는 선택된 최종 시도의 알려진 단계 wall 비용이다. 설치 전·환경 구성 재사용은 한 번만 표시한다. 중단된 과거 시도의 전체 비용이 알려지지 않아 **모든 시도를 합한 총비용은 unknown**이며, 과거의 알려진 비용은 아래 이력에서 따로 보고한다.

| 단계 | 최종 선택 시도 wall 합계(초) | 시간 알려짐/결측 |
|---|---:|---:|
| setup | 1446.095 | 80/0 |
| compile_before | 4676.772 | 3629/0 |
| compile_after | 9535.051 | 3677/0 |
| discovery | 10682.142 | 3677/0 |
| prepare | 24812.495 | 3350/327 |
| plan | 455.985 | 3350/327 |

### 초기 계측 오류와 전체 재시작

초기 pnpm CLI 옵션 거부를 발견하여 원본 실행을 중단·보존했다. 준비 결과와 관계없이 같은 80개 저장소·commit·분류를 유지한 깨끗한 checkout에서 환경 구성과 설치 후 계측을 모두 다시 시작했다. 3629개 설치 전 결과는 원본과 byte-identical인 기록을 재사용했으며 새 실행 횟수로 세지 않는다.

| 초기 setup 기록 | 건수/비용 |
|---|---:|
| 기록 완료 저장소 | 17 |
| 중단 당시 불완전 저장소 | 2 |
| 미시작 저장소 | 61 |
| 고정 중단 기록의 알려진 비용(초) | 396.64991579117486 |
| 완료 setup 기록의 wall 합계(초) | 396.64991579117486 |

불완전 setup의 전체 비용은 unknown이며 위의 재시작 실행 비용과 따로 보존한다. 설치 전 기록 재사용 비용은 신규 비용으로 더하지 않는다. 수정된 CLI는 고정 pnpm·Yarn의 오프라인 합성 대조에서 명령 성공과 스크립트 미실행을 확인했다. 복구 고정 기록: `runs/c03-corpus-2026-10-02/recovery-v3/measurement-recovery-lock.v3.json`, SHA-256 `aaf040340d4a32366f43c24b19989a052bc217e8287eb7b7936ee8f873b61b59`. 초기 실패·중단·재사용 연결은 JSON provenance.recovery에 있다.

### 설치 후 경로 계측 오류와 전체 재측정

재사용한 설치 전 목록의 source_main 절대 경로가 이전 checkout을 가리키는 계측 오류를 확인하고 해당 설치 후 실행을 중단·보존했다. 이전 결과의 성공·실패와 관계없이 같은 3677개 after entrypoint 전체를 현재 pinned checkout 경로로 연결한 after-v4에서 재측정했다. 80개 환경 구성 기록은 그대로 재사용했으며 재설치하지 않았다. 위 결과표는 after-v4만 집계하고 이전 결과로 대체하지 않았다.

| 이전 after 계측 이력 | 건수 |
|---|---:|
| 결과 기록 있음 | 3676 |
| 중단 당시 불완전 | 1 |
| 미시작 | 0 |
| 컴파일 상태 | {'failure': 40, 'not_started': 3587, 'success': 49} |
| 컴파일 실패 사유 | {'compiler_or_tool_error': 1, 'entrypoint_outside_pinned_project': 3587, 'missing_include': 39} |

| 이전 after 단계 | 알려진 wall 합계(초) | 시간 알려짐/결측 | 직접 프로세스 시작 |
|---|---:|---:|---|
| compile | 15.978 | 89/3587 | {'not_started': 3587, 'started': 89} |
| discovery | 142.836 | 89/3587 | {'started': 89, 'unknown': 3587} |
| preparation | 266.106 | 88/3588 | {'started': 88, 'unknown': 3588} |
| plan | 4.447 | 88/3588 | {'started': 88, 'unknown': 3588} |

이전 기록 개수는 실제 컴파일 실행 횟수와 같지 않으며 not_started도 포함한다. 이전 실행 비용은 최종 after-v4 비용과 별도로 보존하고, 불완전 실행의 전체 비용은 unknown이다. 설치 전 기록과 환경 구성의 재사용은 새 실행 비용으로 더하지 않았다. 선택 고정 기록: `runs/c03-corpus-2026-10-02/recovery-v3/final-measurement-selection.v4.json`, SHA-256 `37a5294a198e2099a36c64f0324b732476cc281fdb1507d6d0ecd5315d9849dd`. 이전 결과·중단·경로 대조와 신규 목록은 JSON provenance.final_measurement_selection에 연결했다.

### 실제 실행 도구 경로 감사

after-v4의 실제 invocation을 전수 검사했다. 직접 원본 컴파일은 recovery-v3 pin을 사용했지만 discovery·prepare·plan은 C-02 tool alias를 사용했다. 원인은 `measure_c03_corpus_v4.py`가 `base.RUN`만 바꾸고 `base.legacy.RUN`을 다시 연결하지 않은 데 있다. 두 경로는 같다고 기록하지 않으며, Circom과 zkfDO 각각에서 실제 alias와 recovery pin의 SHA-256이 같음을 별도 확인했다. 이 바이트 동일성은 경로 동일성이나 실행 의미의 독립 검증이 아니다.

| 항목 | 관측 |
|---|---|
| 감사 상태 | verified |
| active 결과 감사 | 3677/3677 |
| active 데이터 경로 감사 | passed (inventory·recovery checkout·after-v4 기준) |
| compile 실제 executable | /Users/miiz/Desktop/kwzzzz_zkfr/runs/c03-corpus-2026-10-02/recovery-v3/tools/circom |
| discovery/prepare/plan 실제 executable | /Users/miiz/Desktop/kwzzzz_zkfr/runs/c02-corpus-2026-10-02/tools/zkfDO |
| 구조 단계 실제 --circom-bin | /Users/miiz/Desktop/kwzzzz_zkfr/runs/c02-corpus-2026-10-02/tools/circom |
| Circom alias/pin SHA-256 동일 | True |
| zkfDO alias/pin SHA-256 동일 | True |
| C-02 tool-lock | `runs/c02-corpus-2026-10-02/tool-lock.json`, SHA-256 `3c6f9d202d5ab9786b35a0363a585f0950813f3f6161bfec4da0f205efb2551f` |
| zkFuzz 차단 sentinel 부재 | absent |
| analyzer 차단 sentinel 부재 | absent |
| invocation 기록 | 14054 |
| 감사 기록 | `runs/c03-corpus-2026-10-02/recovery-v3/actual-tool-provenance.v4.json`, SHA-256 `85da3a14b5d240e3d50d76599b5c9f331db0716d0a03ce3917e3a3a796648ded` |

필수 검사 상태: passed. 명령·exit code·로그 경로와 SHA-256은 JSON의 checks에 있다.

| 검사 | exit code | 로그에서 확인한 개수 |
|---|---:|---|
| cargo fmt | 0 | unknown |
| cargo clippy --all-targets --all-features -- -D warnings | 0 | unknown |
| cargo test | 0 | {'passed': 333, 'failed': 0, 'ignored': 22} |
| python3 -m unittest discover -s tests -p c03*_test.py | 0 | {'run': 213} |

C-02의 컴파일 2296/3470 (66.2%)·완전 준비 845/3470 (24.4%)은 무설치·기존 include 규칙의 관측이다. C-03 설치 전 기준과도 조건이 다르므로 그 차이를 의존성 설치 효과나 zkfDO의 일반 적용성으로 해석하지 않는다.

**고정 driver의 zkFuzz 기록 0회.** 해당 driver는 compile/discovery/prepare/plan만 호출하고 candidate·witness 단계를 호출하지 않는다. 컴퓨터 전체의 실행을 독립 감사한 0회 주장은 아니다. 알려진 entrypoint 목록의 컴파일·준비 결과이며 의미 동등성·결함 탐지 성과가 아니다. 새로운 평가 프로토콜 고정이나 N4-1 전체 완료를 뜻하지 않는다.

## 저장소별 근거와 결과

분류 근거 문장·팀의 회로 폴더/실사용 근거/Circom 버전 원문·노출 연결은 JSON에 보존했다.

| 저장소 | 성격 | 주 조건 | 출처 | 후 entrypoint | 후 compile 성공 | 준비 상태 |
|---|---|---|---|---:|---:|---|
| 0xbow-io/privacy-pools-core | production | True | ['team_curated'] | 2 | 1/2 (50.0%) | {'failed': 1, 'unsupported': 1} |
| 0xja-eth/inft-zkp-scheme-starter-kit | unknown | True | ['github_top200'] | 4 | 4/4 (100.0%) | {'partial': 2, 'unsupported': 2} |
| 0xPolygon/zkevm-proverjs | tool_benchmark | True | ['zkbugs', 'sok_2026'] | 2 | 0/2 (0.0%) | {'failed': 2} |
| 0xPolygonHermez/stark-recurser | tool_benchmark | True | ['github_top200', 'team_curated'] | 19 | 5/19 (26.3%) | {'failed': 14, 'success': 2, 'unsupported': 3} |
| alejandro99so/eerc-backend-converter | production | True | ['github_top200'] | 5 | 5/5 (100.0%) | {'partial': 1, 'unsupported': 4} |
| alinush/circom-stdlib | unknown | True | ['github_top200'] | 33 | 0/33 (0.0%) | {'failed': 33} |
| anon-aadhaar/anon-aadhaar | production | True | ['team_curated'] | 3 | 0/3 (0.0%) | {'failed': 3} |
| aptos-labs/keyless-zk-proofs | production | True | ['zkbugs', 'sok_2026'] | 67 | 1/67 (1.5%) | {'failed': 66, 'success': 1} |
| Arianee/arianee-sdk | library | True | ['zkbugs', 'sok_2026'] | 3 | 0/3 (0.0%) | {'failed': 3} |
| ArmanKolozyan/CCC-Check | tool_benchmark | True | ['github_top200'] | 1126 | 937/1126 (83.2%) | {'failed': 198, 'partial': 307, 'success': 367, 'unsupported': 254} |
| ava-labs/EncryptedERC | production | True | ['github_top200'] | 5 | 5/5 (100.0%) | {'partial': 1, 'unsupported': 4} |
| banyancomputer/hot-proofs-blake3-circom | unknown | True | ['zkbugs', 'sok_2026'] | 4 | 4/4 (100.0%) | {'partial': 4} |
| Bitcoin-Wildlife-Sanctuary/circle-plonk-recursive-verifier-circom | unknown | True | ['github_top200'] | 11 | 11/11 (100.0%) | {'partial': 10, 'success': 1} |
| BlocSoc-iitr/Deimos | tool_benchmark | True | ['github_top200'] | 118 | 112/118 (94.9%) | {'failed': 6, 'partial': 52, 'success': 16, 'unsupported': 44} |
| celo-org/self | production | True | ['github_top200'] | 79 | 0/79 (0.0%) | {'failed': 79} |
| dangduongminhnhat/Circheck | tool_benchmark | True | ['github_top200'] | 730 | 615/730 (84.2%) | {'failed': 120, 'partial': 202, 'success': 220, 'unsupported': 188} |
| distributed-lab/circom-dl | library | True | ['github_top200'] | 92 | 90/92 (97.8%) | {'failed': 4, 'partial': 13, 'success': 46, 'unsupported': 29} |
| dl-solarity/circom-lib | library | True | ['github_top200'] | 91 | 89/91 (97.8%) | {'failed': 4, 'partial': 12, 'success': 46, 'unsupported': 29} |
| dl-solarity/zktype | unknown | True | ['github_top200'] | 7 | 7/7 (100.0%) | {'success': 5, 'unsupported': 2} |
| DoraFactory/Vota-Circuits | production | True | ['github_top200'] | 62 | 1/62 (1.6%) | {'failed': 62} |
| EkuboProtocol/privacy-pools | production | True | ['github_top200'] | 2 | 2/2 (100.0%) | {'partial': 1, 'unsupported': 1} |
| Electron-Labs/ed25519-circom | unknown | False | ['team_curated'] | 27 | 24/27 (88.9%) | {'failed': 3, 'partial': 7, 'success': 1, 'unsupported': 16} |
| erhant/circom101 | education_example | True | ['github_top200'] | 43 | 34/43 (79.1%) | {'failed': 9, 'partial': 1, 'success': 25, 'unsupported': 8} |
| Flamki/setu-stellar-zk | unknown | True | ['github_top200'] | 8 | 5/8 (62.5%) | {'failed': 3, 'unsupported': 5} |
| FlynnSC/zk-hunt | education_example | False | ['github_top200', 'team_curated'] | 8 | 0/8 (0.0%) | {'failed': 8} |
| Galactica-corp/galactica-monorepo | production | True | ['team_curated'] | 25 | 3/25 (12.0%) | {'failed': 22, 'success': 1, 'unsupported': 2} |
| Galxe/identity-protocol | production | True | ['github_top200'] | 55 | 48/55 (87.3%) | {'failed': 7, 'partial': 18, 'success': 15, 'unsupported': 15} |
| Hinkal-Protocol/Hinkal-Contracts-Circuits | production | False | ['team_curated'] | 0 | 0/0 (산출 불가) | {} |
| holyaustin/Filecoin-Forge | education_example | True | ['github_top200'] | 5 | 5/5 (100.0%) | {'partial': 4, 'success': 1} |
| htried/zkp-ldp | unknown | True | ['github_top200'] | 117 | 0/117 (0.0%) | {'failed': 117} |
| iden3/circomlib | library | True | ['github_top200', 'zkbugs', 'sok_2026'] | 48 | 48/48 (100.0%) | {'partial': 18, 'success': 15, 'unsupported': 15} |
| iden3/circuits | production | True | ['zkbugs', 'sok_2026'] | 48 | 43/48 (89.6%) | {'failed': 5, 'partial': 19, 'success': 15, 'unsupported': 9} |
| invisibook-lab/invisibook | production | True | ['github_top200'] | 6 | 6/6 (100.0%) | {'partial': 6} |
| jatinsahijwani/zk-ava-sdk | tool_benchmark | True | ['github_top200'] | 49 | 49/49 (100.0%) | {'partial': 19, 'success': 15, 'unsupported': 15} |
| jatinsahijwani/zkArb-sdk | tool_benchmark | True | ['github_top200'] | 54 | 50/54 (92.6%) | {'failed': 4, 'partial': 18, 'success': 17, 'unsupported': 15} |
| jose-compu/opencircom | library | True | ['github_top200'] | 51 | 51/51 (100.0%) | {'partial': 15, 'success': 21, 'unsupported': 15} |
| logos-storage/circom-goldilocks | unknown | True | ['github_top200'] | 1 | 1/1 (100.0%) | {'partial': 1} |
| Miny-Labs/benzo | production | True | ['github_top200'] | 5 | 5/5 (100.0%) | {'partial': 1, 'unsupported': 4} |
| Moonsong-Labs/zksync-social-login-circuit | unknown | True | ['zkbugs', 'sok_2026'] | 4 | 4/4 (100.0%) | {'partial': 2, 'unsupported': 2} |
| ninjra/aion-cycle | unknown | True | ['github_top200'] | 1 | 0/1 (0.0%) | {'failed': 1} |
| nixkitax/circom-schnorr-verify | unknown | True | ['github_top200'] | 2 | 2/2 (100.0%) | {'partial': 2} |
| pantherfoundation/panther-core | production | True | ['zkbugs', 'sok_2026'] | 23 | 17/23 (73.9%) | {'failed': 6, 'partial': 12, 'success': 1, 'unsupported': 4} |
| PepperSieve/nope | unknown | True | ['github_top200'] | 41 | 40/41 (97.6%) | {'failed': 9, 'partial': 4, 'unsupported': 28} |
| pluto/aes-circuits | unknown | True | ['github_top200'] | 1 | 1/1 (100.0%) | {'partial': 1} |
| polymerdao/plonky2-circom | unknown | True | ['github_top200'] | 9 | 3/9 (33.3%) | {'failed': 6, 'partial': 2, 'unsupported': 1} |
| prifilabs/zk-toolbox | library | True | ['github_top200'] | 12 | 9/12 (75.0%) | {'failed': 3, 'partial': 5, 'unsupported': 4} |
| privacy-ethereum/maci | production | True | ['zkbugs', 'sok_2026', 'c02_config_addition'] | 7 | 0/7 (0.0%) | {'failed': 7} |
| proofcarryingdata/zupass | production | True | ['team_curated'] | 16 | 3/16 (18.8%) | {'failed': 13, 'success': 3} |
| qatkk/VerifyUTXO | education_example | True | ['github_top200'] | 9 | 9/9 (100.0%) | {'failed': 1, 'partial': 5, 'success': 1, 'unsupported': 2} |
| Railgun-Privacy/circuits-ppoi | unknown | False | ['github_top200', 'team_curated'] | 1 | 1/1 (100.0%) | {'unsupported': 1} |
| rarimo/passport-zk-circuits | production | True | ['github_top200', 'zkbugs', 'sok_2026'] | 18 | 17/18 (94.4%) | {'failed': 1, 'partial': 4, 'success': 7, 'unsupported': 6} |
| rejwar/Circom | unknown | True | ['github_top200'] | 3 | 1/3 (33.3%) | {'failed': 2, 'success': 1} |
| risc0/risc0 | tool_benchmark | True | ['zkbugs', 'sok_2026'] | 1 | 1/1 (100.0%) | {'success': 1} |
| selfxyz/self | production | True | ['github_top200', 'zkbugs', 'sok_2026'] | 141 | 0/141 (0.0%) | {'failed': 141} |
| semaphore-protocol/semaphore | production | True | ['zkbugs', 'sok_2026', 'c02_config_addition'] | 1 | 0/1 (0.0%) | {'failed': 1} |
| siv-org/verifiable-private-overrides | unknown | True | ['zkbugs', 'sok_2026', 'c02_config_addition'] | 1 | 0/1 (0.0%) | {'failed': 1} |
| SNAPKITTYWEST/treasury-bridge-zk-proofs | unknown | True | ['github_top200'] | 1 | 0/1 (0.0%) | {'failed': 1} |
| stealthdrop/stealthdrop | production | True | ['github_top200'] | 3 | 0/3 (0.0%) | {'failed': 3} |
| stellar/soroban-examples | education_example | True | ['github_top200'] | 6 | 3/6 (50.0%) | {'failed': 3, 'success': 1, 'unsupported': 2} |
| SURUJ404/Zero-proof | tool_benchmark | True | ['github_top200'] | 2 | 1/2 (50.0%) | {'failed': 1, 'success': 1} |
| tanctl/zylith-old | production | True | ['github_top200'] | 8 | 8/8 (100.0%) | {'partial': 7, 'success': 1} |
| tangle-network/protocol-solidity | production | True | ['zkbugs', 'sok_2026'] | 13 | 8/13 (61.5%) | {'failed': 5, 'unsupported': 8} |
| TanishaSangwan/dark-pool-amm | unknown | True | ['github_top200'] | 5 | 5/5 (100.0%) | {'partial': 1, 'unsupported': 4} |
| tiktok-privacy-innovation/trustless-attestation-verification-circom | unknown | True | ['github_top200'] | 4 | 4/4 (100.0%) | {'partial': 4} |
| tokamak-network/DEPRECATED-zvm | tool_benchmark | True | ['github_top200'] | 2 | 0/2 (0.0%) | {'failed': 2} |
| tomiet/zkauth | unknown | True | ['github_top200'] | 2 | 2/2 (100.0%) | {'partial': 2} |
| TreapGoGo/zk-flex | tool_benchmark | True | ['github_top200'] | 1 | 0/1 (0.0%) | {'failed': 1} |
| vacp2p/research | education_example | True | ['github_top200'] | 5 | 1/5 (20.0%) | {'failed': 4, 'unsupported': 1} |
| vocdoni/davinci-circom-circuits | library | False | ['team_curated'] | 5 | 0/5 (0.0%) | {'failed': 5} |
| worm-privacy/proof-of-burn | unknown | True | ['zkbugs', 'sok_2026'] | 50 | 49/50 (98.0%) | {'failed': 1, 'partial': 19, 'success': 15, 'unsupported': 15} |
| ymcrcat/soroban-privacy-pools | education_example | True | ['github_top200'] | 5 | 2/5 (40.0%) | {'failed': 3, 'unsupported': 2} |
| Zellic/zkerc20 | production | True | ['team_curated'] | 1 | 1/1 (100.0%) | {'partial': 1} |
| zero-savvy/zk-remote-attestation | unknown | True | ['github_top200'] | 3 | 2/3 (66.7%) | {'failed': 1, 'partial': 2} |
| zk-kit/zk-kit.circom | library | True | ['github_top200', 'team_curated', 'c02_config_addition'] | 22 | 0/22 (0.0%) | {'failed': 22} |
| zkemail/email-tx-builder | library | True | ['zkbugs', 'sok_2026'] | 11 | 5/11 (45.5%) | {'failed': 8, 'partial': 3} |
| zkemail/zk-email-verify | production | True | ['zkbugs', 'sok_2026', 'team_curated'] | 21 | 0/21 (0.0%) | {'failed': 21} |
| zkemail/zk-regex | tool_benchmark | True | ['zkbugs', 'sok_2026'] | 6 | 6/6 (100.0%) | {'partial': 6} |
| zkFHE/circomlib-fhe | library | True | ['github_top200'] | 42 | 0/42 (0.0%) | {'failed': 42} |
| zkp2p/zkp2p-v1-monorepo | production | True | ['team_curated'] | 40 | 0/40 (0.0%) | {'failed': 40} |
| zksecurity/zkbugs | tool_benchmark | True | ['github_top200'] | 113 | 52/113 (46.0%) | {'failed': 61, 'partial': 18, 'success': 19, 'unsupported': 15} |

고정 C-02 절차·결과 및 AGENTS·팀 CSV의 검증된 원본 참조는 JSON provenance.locks의 procedure-lock.json.source_references에 보존했다. 저장소 분모의 원본 대조 상태: verified. canonical name과 commit으로 이름 변경을 연결하며 별칭은 JSON에 남겼다. CSV 공백 정규화 예외: [{'sheet_item': 10, 'field': 'usage_evidence_declared', 'source_line': 85, 'normalization': 'strip leading/trailing whitespace'}].

C-03은 `src/candidate_review/lifting/`을 수정하지 않았다. 다만 C-03 시작 전 해당 경로의 해시 snapshot은 없어 전후 바이트 동일성을 입증하지 않는다. finalization에 연결된 해시는 현재 상태만 나타낸다.
