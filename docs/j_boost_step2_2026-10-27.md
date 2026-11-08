안 됨 — aq 정지 뒤 A 측정을 바로 시작할 상태는 아니다. A 메타데이터 957클래스·개발 사례 127개가 뒤늦게 도착했지만, 요청 127개 모두 원본 source root와 entrypoint가 `j-dev` 밖을 가리키고 원본 소스 사본이 없다. 국소 반박 10건에는 O0 R1CS/SYM 사본도 없다. 이 경로들을 열지 않았고 J를 돌리지 않았다. 4d 사본에서 추정한 이미지·내장 공간도 실제 여유 확인이 필요하다.

# J 보강 2차: 공통 기반 구현·합성 검사 (2026-10-27)

## 범위와 격리

설계 2판 `docs/j_boost_design_v2_2026-10-27.md`를 먼저 작성했다(SHA-256 `6678b7f3133d8ccbcdd53d09fbc7628bd81239107878b2808a64038c1aac0706`, 작성 21:09:37 KST). 1판은 고치지 않았다. 이번 코드는 직접 완성, 클래스별 sweep 예산, 주입 진단만 포함한다. 술어, ④, core 해제, 잔차 확장은 구현하지 않았다. 기존 `result.json`의 판정 종류·사유는 그대로 쓰며 새 정보만 `j-boost.json`에 `constraint_witness` 등의 이름으로 적는다. 옵션은 기본으로 모두 꺼져 있다.

`n6_a_remeasure_aq_execute_v3_2.py:139–143`의 실행기는 `scripts/n6_a_remeasure_aq.py:32–46`이 고정한 파일을 실행한다. 작업 트리 소스 재빌드·기본 `target/` 사용 경로는 확인되지 않았다. 금지된 aq 판정 폴더와 외부 캐시는 열지 않았다. 설계 2판을 쓴 시점에는 A 사례 폴더가 없었다. 이후 도착한 파일은 아래에서 별도 집계한다. 빌드·시험 출력은 모두 `runs/j-boost-2026-10-27/` 안이다. 4c 감시기의 nice 19, 시작 30/20 GiB, 실행 18 GiB, 전용 cargo target 8 GiB 상한을 사용했다. 이 작업에서는 `runs/` 전체를 재귀 조사하지 않았다.

| 고정 실행 파일 | 경로 | 시작·종료 SHA-256 |
|---|---|---|
| aq v2.2 J | `runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2` | `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835` |
| aq v1 J | `runs/l07-2026-10-05/tools/zkfDO` | `e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed` |
| 4d v2.3 J | `runs/s-round4-2026-10-27/round4b/bin/zkfDO-v2.3-development` | `05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700` |

## 코드와 검증 범위

- `src/candidate_review/lifting/boost.rs:53,88,152,172`: solver 질의 wire 전체를 시작 O0 벡터에 반영한다. 밖의 wire는 시작값이다. O0 전체 제약·후보 목표·기록된 입력 고정을 검사하고, O1의 모든 wire·별칭 및 입출력 역할을 대응시킨 뒤 Rust와 snarkjs로 최종 `.wtns`를 확인한다. 대응 누락은 `unknown`이다. 최상위 영향은 같은 입력의 정상 계산과 따로 비교한다.
- `src/candidate_review/lifting/repair.rs:1629`, `lifting/mod.rs:3158`: 기존 수리 지역 SAT 및 닫힌 원뿔 모델에 선택적 직접 완성을 붙였다. 수리나 기존 판정의 반환값은 바꾸지 않는다.
- `src/candidate_review/lifting/mod.rs:1069`, `src/bin/zkfdo-j-v23.rs:31`: 클래스별 동일 sweep 초 옵션. 미지정 시 요청 공유 20초 경로다. 측정에서는 요청 전체의 외부 시간 상한도 같이 묶는다.
- `src/candidate_review/lifting/mod.rs:2354,2599`, `lifting/boost.rs:307`: source statement·호출 인스턴스·입력 guard별 후보/실제 signal, 값 및 불일치를 새 기록에 남긴다. O1 `carried=false`에서도 O0 진단을 수행하지만 기존 주입 판정은 변경하지 않는다.
- `src/candidate_review/lifting/wtns.rs:61`: 직렬화 함수를 선택적 실행 경로에서 사용할 수 있게 했다.

**합성 시험 (O0 원본 2제약, O1 및 모든 사례 1,000제약 이하):**

| 경우 | 지금 J/수리 경로 | 새 경로 | 기대 확인 |
|---|---|---|---|
| (가) 보호된 호출 값의 지역 SAT | `no_progress`; 모델 투영에서 변경 없음 | `constraint_witness` 도달, L1=true; 두 검사 통과 | 같음 |
| (나) 모델이 O0 제약을 깨뜨림 | 해당 변형 모델의 기존 전체 J 판정은 실행 안 함 | `original_o0_constraints_rejected` | 같음 |
| (다) O0 목표 대응 누락 | 해당 변형 모델의 기존 전체 J 판정은 실행 안 함 | `unknown` (`goal_mapping_missing`) | 같음 |
| (다′) O1 wire 대응 누락 | 해당 변형 모델의 기존 전체 J 판정은 실행 안 함 | `unknown` (`o1_wire_mapping_missing`) | 같음 |
| (라) 원본 만족, 최상위 출력 동일 | `no_progress`; 모델 투영에서 변경 없음 | 도달, L1=false | 같음 |
| guard 값 불일치 | 기존 판정 미변경 | statement·인스턴스·`main.a` 불일치 기록 | 같음 |
| guard 대응 누락 | 기존 판정 미변경 | statement·인스턴스·`main.a` mapping_missing 기록 | 같음 |

`runs/j-boost-2026-10-27/synthetic-receipt-verified.json`에 모델, 상태, 증거 파일 경로가 있다. (가)·(라)의 구 J 결과는 합성 회로에서 **실제 `repair::search` 호출**의 결과다. (나)·(다)는 변형 모델의 완성 검증이며 구 J 전체 실행과 비교한 수치가 아니다. 합성 결과를 A나 최종 평가 성과로 주장하지 않는다.

## 뒤늦게 도착한 A 자료의 적용표 (읽기만 함)

`j-dev/classes-v1.json`은 설계 2판 작성 뒤 21:39 KST에 만들어진 **unknown·국소 반박 부분집합**이다(SHA-256 `acd98ae05a0a236a86adadde86a304034391dd16c6f01128d840e98df3f9fd9a`). 전체 957클래스 중 unknown 783, 기존 `local_constraint_refutation` 배제 174다. 첫 출발 자료의 767 unknown과는 집계 시점·범위가 달라 증감 효과로 해석하지 않는다.

| 기록 필드 | 현재 A 사본의 건수 (분모 957) |
|---|---|
| `cause_before_budget` | `synthesis_timeout` 493, `cone_refuted_by_propagation_only` 127, `synthesis_model_not_reproduced` 90, null 247; 그 밖의 4종 0 |
| `b_outcome` | `timeout` 506, `propagation_only` 127, `model_not_reproduced` 108, null 216; 그 밖의 10종 0 |
| 최종 이유 | `budget_exhausted` 710, `injection_not_applied` 42, `synthesis_timeout` 13, `synthesis_model_not_reproduced` 18, 국소 반박 174 |
| `exclusion_search_seconds_site_steps` > 0 | 957/957 (site-step 시간 필드만 확인; 클래스별 sweep의 실제 배정·소모량은 이 파일만으로 분리되지 않음) |

`j-dev/cases/index.json`(SHA-256 `1ac1fb11ee2bf82397da8dc365035260462f4f4aa2d139633c6a6`)의 **개발 사례 127개**를 모두 `runs/j-boost-2026-10-27/a-materials-audit-v4.json`(SHA-256 `334153b5e43349dcd870e1fc93a3e0b82ef5375d6b587662416175d757d2a775`)에 ID별 기존 J 코드 위치로 연결했다. 부품명·버그 위치·RQ-C 정보로 고르거나 정렬하지 않았다.

| 사례군 | 수 | 지금 J가 멈추는 코드 |
|---|---:|---|
| 모델 미재현 | 108 | `lifting/mod.rs:3157,3180,3230,3353,3395/3397`, 기존 모델 투영 `lifting/repair.rs:1720` |
| 원뿔 전파만으로 반박 | 3 | `lifting/mod.rs:3300,3356,3395` (solver UNSAT 미확정) |
| 합성 시간 초과 (budget exhausted) | 3 | `lifting/mod.rs:3301,3354,3395` |
| 합성 시간 초과 (예산 소진 전) | 3 | `lifting/mod.rs:3301,3354,3397` |
| 구성 입력 기준 국소 반박 | 10 | `lifting/mod.rs:3607,3618,3658,3663` (main 입력 고정) |

각 사례의 요청 사본은 `j-dev` 안에 있지만, 원래 요청의 `source_root`, wrapper, entrypoint, input, candidate 참조는 127/127 모두 바깥 경로다. candidate·base input·wrapper의 **내용 사본**은 사례 폴더에 있으나, 완전한 source root·entrypoint 사본은 없고 10개 국소 반박 사례의 O0 R1CS/SYM도 없다. 외부 참조는 문자열만 기록했고 파일은 열지 않았다. 이것이 현 측정 준비의 직접적인 차단 원인이다. 이 자료로 기존 J의 기록 위치는 찾았지만 새 J 결과는 하나도 측정하지 않았다.

현재 사례 수로 환산한 단계별 *순차* 시간은 아래와 같다. `기타`에는 model 미재현·국소 반박 외의 unknown 9개가 포함된다. 국소 반박 10개는 두 J군과 원본 재질의 한 번씩이다.

| A 리비전 | 모델/기타/국소 사례 | 계획 명령 | 예상/2배 상한 |
|---|---:|---:|---:|
| aq-011 | 6 / 8 / 10 | 64 | 8.73 / 17.46시간 |
| aq-016 | 30 / 1 / 0 | 92 | 42.32 / 84.64시간 |
| aq-017 | 34 / 0 / 0 | 102 | 46.24 / 92.48시간 |
| aq-026 | 38 / 0 / 0 | 114 | 110.99 / 221.98시간 |
| 합계 | 108 / 9 / 10 | 372 | 208.28 / 416.56시간 |

## aq 뒤 측정 명령 (오늘 실행하지 않음)

A 사례의 원본 source closure·entrypoint와 국소 반박 10개의 O0 R1CS/SYM을 `j-dev`에 갖추고 요청을 그 사본에 결속한 뒤 `scripts/j_boost_prepare_measurement_20261027.py`에 현재의 `runs/j-dev-2026-10-27/cases/index.json`을 준다. 현 상태에서 실행하면 첫 요청의 외부 source root 때문에 준비가 중지되며 불완전한 계획 폴더도 만들지 않는다. 외부 경로는 해석·열기 전에 거부하고 `j-dev` 안의 심볼릭 링크도 거부한다. 같은 seed 0 및 같은 리비전별 외부 상한으로 ① 기존 J(공유 예산), ①′ 새 바이너리의 공정 예산 옵션, ③a 공정 예산+직접 완성을 만든다. `model_not_reproduced` 계열은 세 군 전부, 나머지는 앞의 두 군이다. 국소 반박에는 무관한 main 입력을 고정하지 않은 **원본 전체 O0 exact 후보** 재질의를 별도로 만든다. 그 UNSAT은 명시적 입력 계약 아래 exact 후보 배제에 한하며 술어 전체 배제가 아니다. SAT은 `recheck_not_refuted`로만 해석한다. `scripts/j_boost_run_measurement_20261027.py`는 aq 중지 확인 인자를 요구하고, 각 명령의 외부 시간·내장 공간 상한을 적용한다.

```sh
python3 -B scripts/j_boost_prepare_measurement_20261027.py --cases runs/j-dev-2026-10-27/cases/index.json --output runs/j-boost-2026-10-27/measurement-plan-v1 --seed 0 --class-budget-seconds 20
/usr/bin/nice -n 19 python3 -B scripts/j_boost_run_measurement_20261027.py --plan runs/j-boost-2026-10-27/measurement-plan-v1/commands.json --output runs/j-boost-2026-10-27/measurement-results-v1 --aq-stopped
```

예상은 허용된 **4d aq state 사본** `runs/s-round4-2026-10-27/round4c-main/continuation-20261027/state-v3_2.json`(SHA-256 `24928906ab4b244508c1d09353c2c4db96b931788d860dcdae32d230330286fa`)의 완료된 v2.2 요청 최대시간을 올림한 것이다. 한 사례의 각 군에 같은 값을 주고, 상한은 두 배다. 단계별 총시간은 해당 리비전 사례 수에 군 수를 곱해 합산한다.

| 리비전 | 군당 예상/상한 | 기록된 요청 작업공간 최대 | 이미지 요구 추정 |
|---|---:|---:|---:|
| aq-011 | 491/982초 | 12.16 GiB | 479.63 GiB |
| aq-016 | 1,656/3,312초 | 44.90 GiB | 479.63 GiB |
| aq-017 | 1,632/3,264초 | 32.12 GiB | 479.63 GiB |
| aq-024 | 2,228/4,456초 | 기록 없음 | 479.63 GiB |
| aq-025 | 4,602/9,204초 | 기록 없음 | 479.63 GiB |
| aq-026 | 3,505/7,010초 | 198.67 GiB | 479.63 GiB |

요청 공간의 알려진 최대 198.67 GiB에 두 배 상한을 적용하면 397.34 GiB다. 이미지 요구 추정 479.63 GiB의 두 배는 959.26 GiB다. 현재 내장 여유는 빌드 시작 시 약 98 GiB였으므로 큰 단계는 그대로 실행할 수 없다. 이미지 실제 여유는 금지된 경로를 열지 않아 미확인이다. 현재 index 기준 108개의 모델 미재현, 9개의 기타 unknown, 10개의 국소 반박으로 합계 127사례다. 같은 입력에 대한 비교 명령은 각각 3·2·3개(국소 재질의 포함)로 372개다. 완료된 v2.2 요청의 리비전별 최대시간을 대입하면 **총 예상 208.28시간, 두 배 상한 416.56시간**이다. 이는 실행 견적이며 127개를 수행했다는 뜻이 아니다.

## 회귀, 해시, 오류

- `cargo fmt --all`, 최종 `cargo fmt --all -- --check`, `cargo clippy --offline -j 1 --all-targets --all-features -- -D warnings` 모두 통과. `cargo test --offline -j 1`은 24개 J 시험을 전용 harness로 분리해 425 통과·0 실패·24 기존 ignored·24 분리했다. 분리한 [4d J harness](../scripts/s_round4d_j_tests_20261027.py)와 같은 24개 assertion은 새 바이너리 기본 경로에서 **24/24 통과**, 컴파일된 fixture 20개의 최대 크기는 31제약이었다.
- 합성 옵션 확인: 원본 4d, 새 공정 예산+진단, 새 공정 예산+직접 완성 세 경로가 `main.child: assumption_input_reachable / input_reached`로 일치했다. 원본은 `j-boost.json`을 만들지 않았다. 새 경로에는 별도 클래스 예산 기록만 추가됐다. [두 클래스 합성 회로](../runs/j-boost-2026-10-27/multi-class-budget-summary.json)는 원본 4제약, 기존 J와 공정 예산 J의 두 판정이 같고 클래스마다 20초 배정 기록이 남았다. 이 회로에서는 sweep 소모 0초이므로 공정 예산이 결과를 개선했다는 증거는 아니다.
- `runs/j-boost-2026-10-27/cargo-target` 최대 관측 크기는 약 0.78 GiB, 필수 관문 최대 RSS는 약 1.16 GiB였다. 8 GiB 상한 중단은 없었다. 24개 harness 결과는 `runs/j-boost-2026-10-27/j-harness-results-v1/summary.json`, 감시기 시간·공간 영수증은 `runs/j-boost-2026-10-27/monitoring/`에 있다.

변경 전 파일은 `runs/j-boost-2026-10-27/backup/`에 원본 그대로 복사했다. 아래 SHA-256은 그 백업과 최종 파일을 다시 읽어 계산했다.

| 기존 파일 | 변경 전 | 변경 후 |
|---|---|---|
| `src/bin/zkfdo-j-v23.rs` | `80a57cae158cf772f5ce3cca5269d57e739e6a7840ab0708099ebd117789ac52` | `2b0783f360f117ead9d83f76fe6bb2cc96dee1c1ac5cd04ac3a39bbd79cdb151` |
| `src/candidate_review/lifting/mod.rs` | `0a5f59c265c72c664f89f67193372fb35d0c337b0651e397d84bf845fc19b780` | `9f93a5a6b9ef290a786cbfeabd9a99296abfba6bc2282c8cc80456a7569e2d58` |
| `src/candidate_review/lifting/repair.rs` | `93e7ddfac28cb3502c2b1e5f787831d5aa50c6cc453507dc7db38401d283ca05` | `4d35f2caa36d869c8e24a8ba6f5fc5dd96c67561b3fe7fd2701a38ae7c2d6729` |
| `src/candidate_review/lifting/wtns.rs` | `9f77d2454e2e62867a8c8e8d2ed9830de5d0142def38df5c44eb1b91f0382fb9` | `eeeff2ece243b6c495e685a83cc13b7ad963ead20bdcbb26cc0026b783a17eb7` |
| `docs/plan_revision_2026-10-01.md` | `b81c3dcb8e9df7d734aba425b5656f109a9b05ade45784d935115f9655e09cd1` | `90bb2cba5f8506823e3b16745cb0722591197282a2d78c61e8419bec3f341582` |

새 `boost.rs` SHA는 `86c436ffd84bad5dac89ec6d7e23bf5ac9ae05f850e65be6f7b772d67b20c7dc`다. 새 전용 바이너리 `runs/j-boost-2026-10-27/cargo-target/debug/zkfdo-j-v23` SHA는 **`a82d654287e2e12403ed84a0a2d2395b2daa3e0ecab1fdff0a003e8d286bcfc6`**다. 측정 준비·감시·회귀 스크립트의 SHA는 `runs/j-boost-2026-10-27/`의 영수증 및 아래 새 파일 목록에 기록한다.

| 새 스크립트(변경 전 없음) | SHA-256 |
|---|---|
| `scripts/j_boost_monitor_20261027.py` | `fd05852343c0a391532412e48d91786d09bacf2853fb3b9221975731dd43aabd` |
| `scripts/j_boost_regression_20261027.py` | `c1c6c1cbb95fe343be43e15987c14867c42a7c6413b945a0e7cba77ec6d5b539` |
| `scripts/j_boost_prepare_measurement_20261027.py` | `f9dfa4598d1088424bbcd9c4fa7eda4b2e594c1ab60ba06568372d0c9c879bde` |
| `scripts/j_boost_a_materials_audit_20261027.py` | `af0ff98cd9512a42e687b9780356d17e33bd7f264351e8474d2bf087fe195c55` |
| `scripts/j_boost_run_measurement_20261027.py` | `c4a8abd7a8f9ac5e71b1a9b5da6a6befd8518e6a190cb7461fa2d229d46585aa` |
| `scripts/j_boost_cargo_tests_20261027.py` | `d1a09a0fe68033da49b4916c297dc197754bd1758590b6b9cfc217b3df1a4cb9` |
| `scripts/j_boost_option_probe_20261027.py` | `22ab549df9824e6a5de27954578bf966de1f410f0f95615bf8306770716af48a` |
| `scripts/j_boost_multi_budget_probe_20261027.py` | `5cbc7036f05ea9c7fea65ebd92f1458e34bd25da4570f9a24c5d50efc18bff35` |

준비·감사 스크립트의 최종 정정 전 사본과 SHA-256(`883116e78b962ceb696a3169b67ddf05618ee694a133af0fc4c68393933a3aae`, `2cf3139e434d5463be6b9a03274220caf87d572f5d0b77bb30b223128250bdfa`)도 `backup/scripts/`에 남겼다. 외부 source 참조를 가진 실제 A index로 준비 명령의 안전한 사전 거부와 계획 폴더 미생성을 확인했다. 이는 J 측정이 아니다.

끝에 재확인한 고정 바이너리 SHA: aq v2.2 `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835`, aq v1 `e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed`, 4d v2.3 `05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700`. 세 파일 모두 시작과 종료 SHA가 같다. 경로·크기·시각은 `runs/j-boost-2026-10-27/preflight.json`과 `final-pins-v2.json`에 있다.

해결한 오류: 초기 합성식 `q <== a/d`는 Circom이 비이차식으로 거부해 지원되는 hint+곱 제약으로 바꾸었다. Clippy가 지적한 범위 인덱싱과 시험 보조 함수 위치를 고쳐 재검사했다. O1 최적화로 입력 대응이 없어질 수 있는 경우에는 값을 추정하지 않고 unknown으로 남긴다. 남은 한계는 A 원본 source closure·국소 반박 O0 파일 부재, O1 `carried=false`의 실제 A 발생원인 미확인, 직접 완성이 종전 unknown을 얼마나 줄이는지 미측정인 점이다. 1,000제약 초과 원본 측정은 위의 준비 명령만 기록하고 실행하지 않았다.

**확인한 것:** 설계 2판 선행 작성, 옵션 기본 off, 원본 전체 검사와 O1 대응 fail closed, 합성 시험의 결과, 감시기 범위, A 메타데이터 도착과 원본 자료 부재, 4d state 사본의 수치. **추정한 것:** aq 뒤 시간·이미지·내장 작업공간 필요량과 새 방법의 실대상 효과. 논문 기여의 증거는 이 구현만으로 아직 나오지 않았다.
