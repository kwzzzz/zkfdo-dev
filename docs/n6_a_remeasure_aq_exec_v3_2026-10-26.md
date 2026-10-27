# A aq 실행기 v3 작성·검증 (2026-10-26)

담당 miiz. 작성·검증만 완료했다. 실제 J·RQ-C 실행, 실제 정리·캐시 복사, 실행 중인 v2 제어는 하지 않았다. v2 스크립트·상태·출력과 B 자료는 수정하지 않았다.

v2가 종료된 뒤 사람이 실행할 정확한 명령:

```sh
python3 -B /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_a_remeasure_aq_execute_v3.py --action execute --no-new-revision-after 2026-10-28T15:00:00Z
```

스크립트 SHA-256: `fff60b9696d098627b68a36d9e48a1dbc0b91362c074a4a9475d9e1f4003c665`.

v2.2의 우선 7개 리비전을 mapped Pass A → unmapped Pass B로 진행하고, 나머지 6개를 기존 순서로 처리한 뒤 v1에서 같은 순서를 따른다. aq-025의 요청 2185 재시도도 나머지 구간에 유지한다. 총 40구간이며 빈 Pass B도 마감 확인·진행 기록·탐색층 RQ-C 재채점·최종 정리를 수행한다. 마감은 구간마다 적용하며, 이미 시작한 구간은 끝낸다. 반복 요청 실패 5회·전체 리비전 실패 2회 및 재시도 규칙, 엔진·판정·L1 정의는 v2와 같다.

Pass A 증거·캐시는 마지막 Pass B 완료까지 보존한다. 공간 관문은 `ceil(1.2 × max(60 GiB, 관측 요청 peak)) + 보존 공간`이며 부족하면 대기한다. 보존 공간에는 증거와 디렉터리, 지연 정리 캐시·저장소, 보호하는 v2 작업/캐시·저장소, 독립 복사 예약분이 포함된다. v2를 보존하기 위해 새 요청·캐시·저장소는 `v3/`, 상태는 `state-v3.json`, 로그·정리 기록은 v3 이름으로 분리한다. 기존 캐시·저장소는 전체 해시 확인 후 독립 복사한다.

`state.json`을 기준으로, 그 기준 해시를 확인한 `state-v2.json`의 추가 완료도 가져온다. 모든 완료 결과·metrics·join을 해시 재확인한다. 실행 모드에서 공유 잠금과 읽기 전용 프로세스 검사를 통과해야 하며, v2 또는 이전 A 작업 프로세스가 있거나 확인할 수 없으면 시작하지 않는다. validate-only는 잠금·프로세스 제어·상태 쓰기 없이 동작한다.

검증 명령:

```sh
python3 -B /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_a_remeasure_aq_execute_v3.py --action validate-only --no-new-revision-after 2026-10-28T15:00:00Z
```

| 요청 수 | Pass A | Pass B | 나머지 | 합계 |
|---|---:|---:|---:|---:|
| v2.2 | 123 | 60 | 147 | 330 |
| v1 | 123 | 60 | 147 | 330 |
| 전체 | 246 | 120 | 294 | 660 |

최종 validate-only: `valid`. 엔진 2개·요청 인덱스 2개·구성 입력 13개 해시 확인. 상태 스냅샷에서 완료 19건·실패 1건·진행 중 1건을 확인했다. 진행 중 건수는 검증기의 `interrupted` 카운터이며, v2를 중단했다는 뜻이 아니다. 검증 당시 v2 상태는 `running`였고 완료 요청은 실행하지 않았다.

계산 순서 첫 20건은 모두 v2.2 / Pass A이다: aq-024-6f6781246415의 2145, 2147, 2148, 2149, 2151, 2153, 2155, 2156, 2157, 2159, 2161, 2163, 2164, 2165, 2167; 이어 aq-017-9703bbce0c43의 2124, 2125, 2127, 2128, 2130.

`py_compile`·합성검사 55건·`cargo fmt`·`cargo clippy --all-targets --all-features -- -D warnings` 통과. `cargo test`는 J 호출 테스트 24개를 명시적으로 제외하여 352 통과·24 ignored·24 filtered이다. 전체 무필터 테스트는 J 금지 때문에 실행하지 않았다. 임시 자료로 두 패스·지연 정리·구간 마감·부분 v2 재개·실패/재시도·공간 계산·전환 거부·복사 중단 복구를 검증했다.

검증 기록: `runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/validation-v3-20261026/`. 최종 `validate-only.final.json` SHA-256: `e5602fcedaf0508d998be432ac3e059513412ebdf0ae7beb7b59877a93bd3495`. Rust 테스트의 정확한 제외 인수는 같은 폴더의 `cargo-command.json`에 있다. 최종 Python 로그는 `python-tests.final.log`다.
