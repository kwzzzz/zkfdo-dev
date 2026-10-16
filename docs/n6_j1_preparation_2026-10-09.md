# N6-J1 A 맥락 판정 준비 기록

기준: [N5 평가 프로토콜 v1](n5_evaluation_protocol_v1_2026-10-06.md)의 §5–§7 및 부록 마지막 세 절, [N6-J1 지시](../runs/handoff/n6_j1_instruction_2026-10-09.md). 이 문서는 전체 A 맥락 판정(J)의 준비·검증을 기록한다. 전체 J와 B campaign은 실행하지 않았다. 후보 값은 열람하거나 기록하지 않는다.

## 1) 후보 수 재계산

[후보 inventory](../runs/n6-j1-2026-10-09.noindex/candidate-inventory.json)(SHA-256 `0d3b018107640d22f3a18cdb699dd93ee645907d3fcaf90edd96a3cd510e1547`)의 상태는 `verified`다. A 본 표는 [A v4 queue](../runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json)에서 각 단위의 압박 없는 마지막 run을 재선택했고, aq-035·036은 [pragma-b queue](../runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json)의 보정 spec과 [별도 실행](../runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/state.json)을 사용했다. mem20은 [보완 queue](../runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json)의 [별도 실행](../runs/n6-a3-2026-10-08.noindex/mem20-execute-2.noindex/state.json)을 사용했다.

| 구분 | W | S | 합계 |
| --- | ---: | ---: | ---: |
| A 본 표 | 2,276 | 581 | 2,857 |
| mem20 | 0 | 69 | 69 |
| 전체 | 2,276 | 650 | 2,926 |

본 표 W는 banyan-vulnerable 1,699건과 aq-036 577건이다. 모든 후보의 ledger `duplicate_of`는 비어 있고 SHA-256은 전체 2,926개가 고유하다. 각 행에는 lane·대상·seed·방식·시도 번호·후보 순번·`completion_offset_seconds`·target ID/index·선택 queue/spec·후보 절대경로와 ledger 대조 SHA-256이 있다. 후보 파일은 바이트 해시만 계산했다. [원래 target ID 대응](../runs/n6-a3-2026-10-08.noindex/pragma-b/target-id-map.json)이 있는 보정 S 후보에는 `original_target_id`도 기록했다. [inventory 생성기](../scripts/n6_j1_inventory.py)(SHA-256 `ed8b127dde751ac778458c8674711e42d6f6c46abd9adb92eed0f05013378c36`)와 [모의 테스트](../tests/n6_j1_inventory_test.py) 6건이 통과했다.

## 2) 리비전별 기준 입력 표

[27개 리비전 manifest v2](../runs/n6-j1-2026-10-09.noindex/revision-manifest-v2.json)(SHA-256 `f059fe7d6aa21234168b7867537f069ec980c45c2c025184cbc12e169f687441`)는 대표 단위·W entrypoint 경로/SHA·project root·preflight `-l` 경로·zkbugs `item_ids`와 원본 입력 경로/SHA를 기록한다. aq-035·036 W entrypoint는 pragma 보정 사본이다. 27개 중 25개는 기록된 revision commit을 실제 Git 저장소에서 확인했다. Banyan 통제 데이터 두 리비전은 원본 준비 단위의 `item_ids`가 비어 있어 추정 zkbugs 연결을 추가하지 않았고, Git repository path도 비어 있다.

| 리비전 | 기존 규칙 단계 | N5 보충 적용 단계 | 기준 입력 경로·SHA | 정직 witness·Rust/snarkjs R1CS | 앞 단계 실패 사유 |
| --- | --- | --- | --- | --- | --- |
| [aq-006-1680f955c185](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-006-1680f955c185/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: JSON 무효, 키 불일치; d: 원본 테스트/도구 실패; e: 정직 witness 실패 |
| [aq-007-0bb83f9eab0f](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-007-0bb83f9eab0f/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: JSON 무효, 키 불일치; d: 원본 테스트/도구 실패; e: 정직 witness 실패 |
| [aq-008-9c9e702d061d](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-008-9c9e702d061d/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: JSON 무효, 키 불일치; d: 원본 테스트/도구 실패; e: 정직 witness 실패 |
| [aq-011-93343c3cd34c](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-011-93343c3cd34c/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 빌드 실패; e: 정직 witness 실패 |
| [aq-012-44d0df2ab46e](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-012-44d0df2ab46e/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 빌드 실패; e: 정직 witness 실패 |
| [aq-016-0a7d49b1c135](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-016-0a7d49b1c135/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 빌드 실패; e: 정직 witness 실패 |
| [aq-017-9703bbce0c43](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-017-9703bbce0c43/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 빌드 실패; e: 정직 witness 실패 |
| [aq-024-6f6781246415](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-024-6f6781246415/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 빌드 실패; e: 정직 witness 실패 |
| [aq-025-70328d3fd35e](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-025-70328d3fd35e/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 테스트/도구 실패; e: 정직 witness 실패 |
| [aq-026-2bcd7ed6110f](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-026-2bcd7ed6110f/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 테스트/도구 실패; e: 정직 witness 실패 |
| [aq-035-8f826c822cb8](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-035-8f826c822cb8/selection.json) | `a_zkbugs` | `a_zkbugs` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-035-8f826c822cb8/selected-input.json) `99a232bd7b23fc939b45c9382b5bd48769cbba560f081fb1aa51eaf58c0dd606` | 정직 witness·Rust·snarkjs 통과 | — |
| [aq-036-6d7df64759b6](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-036-6d7df64759b6/selection.json) | `a_zkbugs` | `a_zkbugs` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-036-6d7df64759b6/selected-input.json) `99a232bd7b23fc939b45c9382b5bd48769cbba560f081fb1aa51eaf58c0dd606` | 정직 witness·Rust·snarkjs 통과 | — |
| [aq-037-94fe3080fc18](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-037-94fe3080fc18/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 테스트/도구 실패; e: 정직 witness 실패 |
| [aq-039-0ad3923f2f5b](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-039-0ad3923f2f5b/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 테스트/도구 실패; e: 정직 witness 실패 |
| [aq-040-da54d3e7bc8a](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/aq-040-da54d3e7bc8a/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 입력 없음; b: L 입력 없음; c: 키 불일치; d: 원본 테스트/도구 실패; e: 정직 witness 실패 |
| [banyan-fixed](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/banyan-fixed/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 항목 연결 없음; b: L 입력 없음; c: 커밋 JSON 확인 불가; d: 일치 테스트/도구 없음; e: 정직 witness 실패 |
| [banyan-vulnerable](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/banyan-vulnerable/selection.json) | `base_input_unavailable` | `base_input_unavailable` | — | 기준 입력 없음 | a: 항목 연결 없음; b: L 입력 없음; c: 커밋 JSON 확인 불가; d: 일치 테스트/도구 없음; e: 정직 witness 실패 |
| [inference-all-fixed](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-all-fixed/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-all-fixed/selected-input.json) `13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음 |
| [inference-c771c61c-p](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-c771c61c-p/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-c771c61c-p/selected-input.json) `13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음 |
| [inference-c79f42ee](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-c79f42ee/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-c79f42ee/selected-input.json) `13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음 |
| [inference-c9221e8d](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-c9221e8d/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-c9221e8d/selected-input.json) `13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음 |
| [inference-loo-clamp](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-loo-clamp/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-loo-clamp/selected-input.json) `13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음 |
| [inference-loo-dfs](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-loo-dfs/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-loo-dfs/selected-input.json) `13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음 |
| [inference-original](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-original/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-original/selected-input.json) `13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음 |
| [inference-r-intdiv](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-r-intdiv/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/inference-r-intdiv/selected-input.json) `13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음 |
| [zkemail-fpmul-fixed](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/zkemail-fpmul-fixed/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/zkemail-fpmul-fixed/selected-input.json) `866c61aa206763bdf78ed219b2b8d85e66c1ed43d35c626c1497a3e67a2fc54b` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음; b: 키 불일치 |
| [zkemail-fpmul-vulnerable](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/zkemail-fpmul-vulnerable/selection.json) | `b_l_series` | `b_l_series` | [입력](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/zkemail-fpmul-vulnerable/selected-input.json) `866c61aa206763bdf78ed219b2b8d85e66c1ed43d35c626c1497a3e67a2fc54b` | 정직 witness·Rust·snarkjs 통과 | a: 항목 연결 없음; b: 키 불일치 |

N5 최종 보충의 순서는 (a) zkbugs `input.json` → (b) 같은 entrypoint의 L-시리즈 `base_input` → (c) 커밋 JSON → (d) 프로젝트 테스트 입력 → (e) 모두 0 입력이다. [최종 기준 입력 index v3](../runs/n6-j1-2026-10-09.noindex/base-inputs-v3/index.json)(SHA-256 `18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508`)에서 27/27개 리비전을 확인했다. (a) 2개, (b) 10개가 정직 witness 생성과 Rust·snarkjs 두 R1CS 검사를 통과했다. (d) 통과는 0개, 15개는 `base_input_unavailable`이다. 원래 규칙 단계와 최종 단계는 위 표에 모두 적었다. 통과한 12개 기준 입력·witness의 경로/SHA-256, 전 리비전의 제약 수와 단계 기록을 검산했다. 각 행의 `selection.json`에 앞 단계의 전체 실패 사유, 실행 명령·종료 코드·시간이 있다. v1·v2의 이전 기록은 수정하지 않고 보존했다.

JWT의 `tooling/generate-input.ts`는 원본 `tooling/cli.ts`가 호출했으나 필수 환경변수 다섯 개가 없어 종료 코드 1이었다. Panther aq-011/012/016/017/024의 원본 빌드는 패키지 관리자 부재로 127, Rarimo aq-025/026와 zk-regex aq-037/039/040의 원본 테스트는 의존 모듈 부재로 1이었다. (d)의 테스트·입력·프로젝트 소스를 수정하거나 네트워크 설치를 하지 않았다. Banyan 두 통제 리비전은 zkbugs 항목 연결과 커밋 저장소가 없고 0 입력도 실패했다. 이 15개 리비전의 후보는 요청을 만들되 판정 호출 없이 분모에 `preparation_failure`로 남긴다.

## 3) 요청 수와 경로 검사 결과

[요청 index](../runs/n6-j1-2026-10-09.noindex/request-index.json)(SHA-256 `35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c`)에 후보 2,926건당 요청 하나씩 2,926개를 만들었다. 본 표 2,857개와 mem20 69개를 별도 scope로 두었고, 기준 입력 통과로 판정 호출 가능한 요청은 본 표 765개다. 나머지 본 표 2,092개와 mem20 69개, 합계 2,161개는 `base_input_unavailable`로 준비 실패를 기록하며 호출하지 않는다. 요청 파일·후보·W entrypoint·S wrapper의 SHA-256, 절대 경로와 `source_root` 포함 여부를 모두 검증했다. aq-035의 보정 S 조각은 원래 target ID 대응을 유지한다.

[전체 실행기](../scripts/run_n6_j1.py)의 `--action validate-only`는 위 index와 고정 엔진·circom·기준 입력 index를 검증하고 `valid`, 요청 2,926개를 반환했다. 사용된 W/S spec 180개의 SHA·target 대응·원 사전 검사 `-l` 순서를 검산했고, 실제 사용 target의 고유 원본 source snapshot 145개 트리 SHA-256도 일치했다. S의 `{workspace}`는 그 target의 원본 snapshot 경로로 바꾸고 중복 `-l`을 포함한 원 명령 순서를 유지했다. 이 전체 source tree 검증은 시작 시 한 번 수행한다. snapshot 밖의 외부 library root 전체 바이트는 이 검사 범위 밖이며, 해당 경로의 존재와 spec SHA는 검사한다.

## 4) 시범 표

기준 입력 검증과 `cargo test`가 끝나 다른 무거운 작업이 없는 때 [새 시범 기록](../runs/n6-j1-2026-10-09.noindex/pilot-v1.noindex/pilot.json)(SHA-256 `c7c5644f2511d159ed764e3c34d6470cba899e631164b064cf9ab2ada0c7338e`)을 만들었다. 고정 6역과 통과 A-Q 중 최대 제약인 aq-035(3,250개)의 추가 S 후보 1개를 선정했다. 시범의 첫 Banyan W 요청은 기준 입력이 없어서 `preparation_failure: base_input_unavailable`로 기록됐고, N6-J1 5절의 W 실패 중단 조건에 따라 즉시 멈췄다. 판정 엔진은 한 번도 호출하지 않았으며 나머지 6개 요청도 실행하지 않았다. 따라서 시범 통과 조건은 충족되지 않았고 자기·실효 판정, W `sites_found`, 벽시계, 최대 메모리, 디스크 증가는 측정할 수 없었다. 이 중단 기록은 전체 J에 포함하지 않는다.

| 시범 순서·요청 | 상태·판정 | W `sites_found` | 벽시계 | 최대 메모리 | 디스크 증가 |
| --- | --- | --- | ---: | ---: | ---: |
| 1. banyan-vulnerable s01 W, queue 131 | `base_input_unavailable`, 판정 없음 | 측정 전 중단 | — | — | — |
| 2. aq-036 s01 W, queue 2235 | 미실행 | — | — | — | — |
| 3. inference-original s01 S, queue 0 | 미실행 | — | — | — | — |
| 4. banyan-vulnerable s01 S, queue 698 | 미실행 | — | — | — | — |
| 5. aq-035 s01 S, queue 2223 | 미실행 | — | — | — | — |
| 6. zkemail-fpmul-vulnerable s01 S, queue 1962 | 미실행 | — | — | — | — |
| 7. 최대 제약 aq-035 s01 S, queue 2224 | 미실행 | — | — | — | — |

`/usr/bin/time -l`의 `/usr/bin/true` 표본은 `sysctl kern.clockrate: Operation not permitted`로 실패해, 실제 lift가 있었다면 `wait4`로 측정할 예정이었다. [시범의 부분 집계](../runs/n6-j1-2026-10-09.noindex/pilot-summary-v1.json)는 2,926개 요청 중 관측 준비 실패 1, 대기 2,925, 완료 판정 0, 인스턴스 조인 0으로 `partial`이다. 나머지 2,160개의 예정 준비 실패는 관측 결과에 더하지 않았다.

## 5) 실행기 테스트 결과

고정 판정 엔진은 `runs/l07-2026-10-05/tools/zkfDO`(SHA-256 `e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed`), 고정 circom은 `/Users/miiz/.cargo/bin/circom`(SHA-256 `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227`)이다. [전체 실행기](../scripts/run_n6_j1.py)(SHA-256 `af23186151e1162f352d1a27f9020e3054e20bc461404791846fbb245077bd7c`)는 한 번에 요청 하나씩 A queue 순서대로 처리하고, 본 표 뒤 mem20을 별도 리비전 저장소로 처리한다. 요청 SHA와 성공 결과가 같은 때만 이어 하고, 남은 디스크 40 GiB 미만에서는 멈춘다. `--cache-root`는 사용자가 외장 드라이브 절대경로를 인자로 준다. 리비전별 캐시 정리는 선택 사항이며 기본값은 끔이다. 삭제 전 경로·SHA·크기를 기록하고 저장소와 결과는 남긴다. 서로 다른 리비전의 캐시 경로가 중복되면 거부한다. 엔진 종료 코드가 0이어도 `preparation.status != ok`, W의 `sites_found < 1`, 최대 메모리 측정 누락이면 실패를 기록하고 중단한다. 재개 때도 이 검사를 다시 한다.

[값 없는 요약기](../scripts/n6_j1_summarize.py)(SHA-256 `6a02f7f6e4c74a3403bd1dc6b2604ff6c15e4f811d86cf4035016ed8910688e8`)는 요청별 자기/실효 판정·L1·`reach_inputs`·시각, 단위별 최초 L1과 600초 검열, K5a r/l, RQ-C 항목별 관측 인스턴스와 수정 리비전 도달, mem20 비교, J 비용을 산출한다. 시범 일부만 있는 동안은 `partial`로 기록하고 `--require-complete`는 미완료·해시 불일치·오래된 인스턴스 조인을 거부한다. 조인 `conflicts`가 0이 아니거나 누락되면 요약을 중단한다. 아직 실행하지 않은 예정 준비 실패는 관측 실패 수와 분리한다. `lift-instances` 범위는 `joined_predicate_targets`로 명시한다. [RQ-C 인스턴스 매핑](../runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json)(SHA-256 `8ad5d43b51d5ceaab0d95dd83a229f45fdc2a2020485a21ccb3b1a43fb4aab85`)은 15개 선택 A-Q 리비전·26개 항목 연결을 원 준비 캡처의 템플릿 이름에 묶는다. 일치하는 관측 인스턴스가 없으면 비도달로 단정하지 않는다. 공유된 실효 도달의 `reach_inputs`는 조인 인스턴스의 분류도 사용한다. 시범 [부분 집계](../runs/n6-j1-2026-10-09.noindex/pilot-summary-v1.json)(SHA-256 `4078cc962df63fe07579b2ef60e16d5266fb784d97a6696dececb3bf43f1c613`)를 만들고 `partial`임을 확인했다.

Python 모의 테스트는 N6-J1 관련 54건이 통과했다(기준 입력 7, inventory 6, 시범 8, 요청 3, RQ-C 매핑 3, 실행기 18, 요약 9). `cargo fmt`, `cargo fmt -- --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`도 모두 종료 코드 0으로 통과했다. 실제 J 판정은 실행하지 않았다.

## 6) 예상 시간·디스크

시범은 첫 W 기준 입력 부재로 엔진 호출 전에 멈췄으므로 요청별 벽시계·캐시 증가량·최대 메모리의 실측이 없다. 따라서 이 실행의 정리 없는 캐시 합계, 리비전별 정리 시 최대치, 전체 시간은 시범 근거로 추정할 수 없다. 실제 판정 호출 가능한 분모는 765개이고 2,161개는 준비 실패로 남는다. 단순 참고 산술로 [L-07 결과](lifting_l07_results_2026-10-06.md)의 141건 벽시계 합 3,731초와 캐시 44.6 GB를 765건에 비례시키면 약 5.6시간·242 GB다. 회로 크기와 캐시 재사용 양상이 달라 이 수치는 이번 실행의 예측값이 아니다. L-07의 리비전별 최대 캐시는 16.9 GB였으나 이번 리비전별 정리 최대치도 미측정이다. 본 실행의 외장 캐시 위치는 사용자 명령의 `--cache-root`로 받는다. `--cleanup-cache-per-revision`은 기본값으로 쓰지 않고 사용자 선택으로만 켤 수 있다.

## 7) 터미널 명령

[실행 입력 SHA-256 목록](../runs/n6-j1-2026-10-09.noindex/j-execution-inputs.sha256)(목록 파일 SHA-256 `37726457526c0f201adc2d715dd55cd1a462c3d80b4adc02f9618a9e1350fb4e`)은 고정 엔진·circom·실행기·요청 index·기준 입력 index·후보 inventory 6개를 고정한다. `shasum -a 256 -c`에서 6/6 통과했다. 아래는 사용자가 터미널에서 실행할 한 줄 명령이다. 외장 드라이브의 **이미 존재하는 절대 캐시 경로**를 프롬프트에 입력한다. `--cache-root`가 그 경로를 받으며, 저장소·결과·로그는 저장소의 `runs/` 아래에 남는다. 본 표 뒤 mem20을 별도 scope와 저장소로 처리한다. 여기서는 이 명령과 전체 J를 실행하지 않았다. 시범은 첫 W 준비 실패로 통과하지 못했으므로, 아래 명령에는 시범에서 측정한 자원 예상치가 없다.

```sh
printf '외장 캐시 디렉터리의 절대경로: '; read -r J_CACHE_ROOT && test -d "$J_CACHE_ROOT" && shasum -a 256 -c /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/j-execution-inputs.sha256 && caffeinate -dimsu python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/run_n6_j1.py --index /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/request-index.json --index-sha256 35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c --cache-root "$J_CACHE_ROOT" --action execute --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/j-execute.noindex > /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/terminal-j.log 2>&1; rc=$?; printf 'log=%s exit_code=%s\n' /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/terminal-j.log "$rc"
```

전체 J 종료 뒤 값 없는 집계는 `scripts/n6_j1_summarize.py --require-complete`로 새 출력 파일에 만들 수 있다. 위 실행 명령은 집계를 자동 실행하지 않는다. 리비전별 캐시 정리는 기본값이 꺼져 있으며, 기록 후 삭제 스크립트 [n6_j1_cache_cleanup.py](../scripts/n6_j1_cache_cleanup.py)는 별도로 준비했다.

## N5 우선 적용 차이

J1 지시의 원래 기준 입력 설명은 (d)를 모두 0 입력으로 적었으나, [N5 최종 보충](n5_evaluation_protocol_v1_2026-10-06.md)은 (d) 프로젝트 테스트 입력을 추가하고 모두 0 입력을 (e)로 옮겼다. 위 기준 입력 순서와 표는 N5를 따른다.

B2 지시 4절은 첫 seed의 명령으로 B 파서를 시험하라고 했으나 N5의 B 실행 전 보충은 60 spec 전체 수용을 요구한다. [B2 준비 기록](n6_b2_preparation_2026-10-09.md)은 첫 seed의 3,393 entrypoint 실제 검사와 세 seed의 source·명령 동일성 증명으로 60 spec을 결속한 차이를 별도로 기록한다.

## 새 파일 SHA-256 목록

[N6-J1 새 파일 SHA-256 목록](../runs/n6-j1-2026-10-09.noindex/j1-new-files.sha256)에 준비 코드·테스트·결과 문서·주요 증거 파일의 경로와 해시를 적었다. 요청 2,926개 각각의 SHA-256은 요청 index의 `requests[].request_sha256`에 있다. 목록은 전체 J 실행 결과가 아닌 준비 산출물만 포함한다.
