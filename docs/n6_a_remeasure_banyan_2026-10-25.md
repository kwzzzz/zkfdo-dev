# A 구성 기준 입력: banyan 재측정 (2026-10-25)

miiz의 2026-10-25 승인과 [N5 개정 8절·마지막 기록](n5_amendment_b_judging_2026-10-17.md)에 따른 개발 세트 재측정이다. A 엄격층(완료 765·준비 실패 2,161)과 합치지 않는다. 출력·캐시는 모두 `runs/n6-a-remeasure-2026-10-25.noindex/` 아래에 둔다.

구성 입력은 각 리비전의 기록된 커밋 소스만 확인하고 seed `20261025-a-banyan`의 SHA-256 파생값으로 만든 정상 내부 트리 위치다(`4 ≤ leaf_depth ≤ 64`, `1 ≤ depth < leaf_depth−1`). 후보·요청 행·ledger 후보 필드·J 출력·기존 입력은 생성에 사용하지 않았다. 두 소스의 입력 계약이 같아 별도 생성 결과의 SHA도 같다. 두 번 생성의 결정성과 기존 파일 덮어쓰기 거부를 확인했다.

| 리비전 | 기록된 커밋 | 제약 | 검사 시간(초) |
| --- | --- | ---: | ---: |
| banyan-vulnerable | `76b83107eb00c8f886bde82172eaa3cdd5d57f25` | 29 | 25.6791 |
| banyan-fixed | `e37eb56e29b304024055f3d0a1681e6f22132ecc` | 47 | 24.6632 |

입력은 `inputs/<리비전>/input.json`, 공통 SHA-256은 `d5dd889c55ae49c219eb9d3b4a93f8f64f7d5bfe1ed9e8f7e628895f235e7e06`이다. 두 입력 모두 정직 witness 생성·Rust·snarkjs 원본 R1CS 만족을 통과했고 공개 출력은 전부 0이 아니다. `inputs/<리비전>/check.json`에 기록했다.

| 리비전 | 검사 R1CS SHA-256(공식 index v3와 일치) | 검사 기록 SHA-256 |
| --- | --- | --- |
| vulnerable | `2ce972ae628f4e107f52aaea51994670b39937f4d010e8da895eaa99adacacc9` | `603e99184a8d549fb1423f4c08d9c175dcbb323c4eb93c1d5bfd75d9e56db9bc` |
| fixed | `897b00be0e06cfd7af3a9d8f76aa7f8c7a7cc1aa66f7f007094a0c8bda5520d0` | `b853dfc8838d55a9ca4e8ced573dbd1cc93cca84e6138318b512ff56271572df` |

기존 `n6_b6_check_constructed_input.py --scope A`의 검사 함수를 그대로 호출했다. 기존 CLI의 외장 mount 요구와 B 상태 파일 조회만 새 생성기의 로컬 경로 관문으로 대체했다. 캐시는 `cache/input-checks/`, Cargo는 offline이다. 설치·B 데이터 접근·기존 프로세스 제어는 하지 않았다.

실행 명령(입력 생성은 기존 폴더가 있으면 거부):

```sh
python3 scripts/n6_a_construct_input_banyan.py --revision banyan-vulnerable --check
python3 scripts/n6_a_construct_input_banyan.py --revision banyan-fixed --check
python3 scripts/n6_a_remeasure.py --action prepare
python3 scripts/n6_a_remeasure.py --action execute
python3 scripts/n6_a_remeasure.py --action aggregate
python3 -m py_compile scripts/n6_a_construct_input_banyan.py scripts/n6_a_remeasure.py
```

원래 A v2.2/v1 index에서 banyan 1,831행씩을 선택했다(vulnerable W 1,699·S 108, fixed S 24). 원래 `queue_order` 131–1961과 요청 ID를 유지했다. 요청 JSON은 `base_input`만 바꾸고 새 index의 요청 경로·해시와 준비 상태를 갱신했다. 두 원본 index와 입력 index v3는 보존했다. 소스·wrapper·후보 SHA 및 고정 spec 연결을 기존 러너 함수로 전수 검증했다.

| 새 index | SHA-256 |
| --- | --- |
| `prepared/request-index-v2.2.json` | `e7290c40fa9404f743c734044263e9f911f6d26f0548cc0b9c9e0b97e114b690` |
| `prepared/request-index-v1.json` | `94faefbe435d779cbd84e212e78b27446ff992131efc1b399ba0f1a16c05a7da` |
| `prepared/plan.json` | `26958436b4256a496722b6f436f388f5c54a0458a850269924e3303c03e7917d` |

엔진은 [고정 기록](n6_j4_freeze_v2_2_2026-10-17.md)의 v2.2 `c7816631…`와 v1 `e5cb0184…`를 사용한다. 새 러너는 `run_n6_j1.py`의 실행·RSS 계측·소스 검증·캐시 정리·인스턴스 결합 함수를 재사용한다. 상태에 요청별 wall/RSS·결과/metrics 경로와 SHA를 기록하고 재개 시 재검증한다. 3시간 예상 초과는 요청 사이에서 중단한다. 작은 회로의 저장소 내부 실행을 위해 디스크 잔여 관문은 새 계획에 8 GiB로 기록했다(기존 러너 40 GiB, 실행 전 잔여 약 33 GiB). 엔진의 탐색 예산은 그대로다.

집계는 `n6_b6h_result_gate.py`와 같은 요청별 분류다. 자기 클래스의 `entrypoint_violation` 또는 고정 엔진으로 결합한 실효 `assumption_violation_reachable`이면 L1, 비L1 중 하나라도 자기/실효 배제이면 excluded, 나머지 완료 요청은 unknown이다. 준비 실패·실행 오류·미실행은 별도 분모로 둔다. 배제는 **구성 입력 기준 배제**다. 리비전은 두 개이며 요청 수는 회로·후보 수에 좌우된다. 특히 banyan은 기존 L-03 대조에 쓴 개발 자료이므로 독립 평가나 고유 결함 수로 해석하지 않는다.

두 엔진 각각 **1,831/1,831 완료**, 준비 실패·실행 오류·미실행은 0건이다. 리비전 기준으로 각각 **2/2 판정 완료**이며, vulnerable 1개는 모든 요청이 L1, fixed 1개는 모든 요청이 구성 입력 기준 배제다. 두 엔진의 요청별 3분류는 1,831/1,831 일치한다. fixed W는 원래 요청 0건이다.

| 엔진 | 리비전 | 방식 | 요청/완료 | 준비 실패 | L1 | excluded | unknown |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| v2.2 | vulnerable | W | 1699/1699 | 0 | 1699 | 0 | 0 |
| v2.2 | vulnerable | S | 108/108 | 0 | 108 | 0 | 0 |
| v2.2 | fixed | S | 24/24 | 0 | 0 | 24 | 0 |
| v1 | vulnerable | W | 1699/1699 | 0 | 1699 | 0 | 0 |
| v1 | vulnerable | S | 108/108 | 0 | 108 | 0 | 0 |
| v1 | fixed | S | 24/24 | 0 | 0 | 24 | 0 |

시간은 요청별 최종 시도의 wall seconds다. 평균·중앙값·최대·합계에서 입력 검사·index 검증·인스턴스 결합·정리 비용은 제외한다.

| 엔진 | 리비전·방식 | 평균(초) | 중앙값(초) | 최대(초) | 합계(초) |
| --- | --- | ---: | ---: | ---: | ---: |
| v2.2 | vulnerable W | 0.5707 | 0.5723 | 0.6409 | 969.5371 |
| v2.2 | vulnerable S | 0.6198 | 0.5756 | 1.0847 | 66.9353 |
| v2.2 | fixed S | 0.2527 | 0.2488 | 0.3319 | 6.0647 |
| v1 | vulnerable W | 0.4945 | 0.4999 | 0.5826 | 840.1805 |
| v1 | vulnerable S | 0.5045 | 0.5040 | 0.8283 | 54.4853 |
| v1 | fixed S | 0.1798 | 0.1771 | 0.2549 | 4.3144 |

엔진별 요청 시간 합계는 v2.2 **1,042.5372초**, v1 **898.9802초**다. 두 엔진 순차 실행 루프의 경과는 **2,081.4178초(34분 41초)**로 3시간 이내에 완료했다(입력 생성·검사, 실행 전 index 검증, 이후 집계 제외). macOS `time -l` 사용 가능성 검사 후 직접 `wait4`로 wall/RSS를 계측했으며 요청 최대 RSS는 v2.2 162,889,728바이트·v1 163,037,184바이트다. 리비전 캐시 4/4는 해시 목록을 남기고 정리했고 결과·입력·증거는 보존했다.

최종 집계는 `aggregates/aggregate-0001.json`(SHA-256 `82b91a1c525167667a7ec80dc6555839a5e7af7ca1acad14db81e0607066c683`), 요청별 원자료는 `j-v2.2/state.json`과 `j-v1/state.json`이다. 고정 엔진의 `lift-instances`로 리비전별 결합 4개를 생성했고 충돌은 0건이다.

| 새 스크립트 | SHA-256 |
| --- | --- |
| `scripts/n6_a_construct_input_banyan.py` | `ca81bd7d92acad9ed5c65b74356795e472e38dc7e23640b53c943e3cf9eaa2fb` |
| `scripts/n6_a_remeasure.py` | `d1c3d54edeba4e88ad617767a4ca02a4819aeec25cad934581c1de2d1f546a91` |

검사: 새 스크립트 `py_compile`, 집중 합성 검사 17건, `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`(376 통과·24 ignored)가 통과했다. 실제 J는 필수 Rust 검사 종료 뒤 시작했다. 완료 후 별도 대조에서도 요청·결과·metrics SHA 3,662건, 결합 4개, 분류·통계, 엔진 순서, 캐시 정리 4개가 모두 일치했다(`verification/completed-run-audit-0001.json`).
