# N7 전체 비용 계측 실행기: 합성 운영 시범

2026-10-28. **합성 운영 경로를 확인했다. W 대 S+J의 성능 우위나 새 논문 기여는 측정하지 않았다.** A·B 원본과 aq 이미지·캐시는 사용하지 않았다. J→S 피드백 방법은 종료 상태다.

## 관문과 실제 결과

[v1](n7_allcost_pilot_protocol_v1_2026-10-28.md)·[v2](n7_allcost_pilot_protocol_v2_2026-10-28.md)를 고정하고 실행한 [plan-v5](../runs/n7-allcost-2026-10-28/plan-v5.json)는 프로세스상 12/12 완료였지만 **v2의 “모든 군에서 자연 후보” 관문은 9/12**였다. 음성 회로의 W 3군은 후보 0·J 0이며, 이전 `summary.status=completed`가 그 사실을 가렸다. v5의 전체 의미 관문은 실패로 보존한다.

음성 회로의 자식 출력은 최상위 출력에 닿지 않는다. 이 경우 W에 후보를 강요한 v2 운영 기준이 부정확했다. 결과를 본 뒤 만든 [v3](n7_allcost_pilot_protocol_v3_2026-10-28.md)는 이 변경과 사후성 자체를 명시한다. 기존 기록을 고치지 않고, 코드·기준을 새로 pin한 [plan-v6](../runs/n7-allcost-2026-10-28/plan-v6.json)을 [새 출력](../runs/n7-allcost-2026-10-28/execution-v6/summary.json)으로 재실행했다. v6의 명시적 의미 관문은 **12/12 통과**했다. 이는 v3가 정한 합성 운영 가능성의 확인이다.

| 합성 회로·군 | 군 수 | 자연 후보→예산 안 J | 원본 검사·판정 | 군 wall 범위 | 표본 peak RSS 최대 |
|---|---:|---:|---|---:|---:|
| 최상위 위반, W | 3 | 군마다 2→2 | 각 군 L1 클래스 2, `output_differs` | 11.550–11.563초 | 163.9 MiB |
| 최상위 위반, S+J | 3 | 군마다 2→2 | 각 군 L1 클래스 2, `output_differs` | 12.746–12.988초 | 234.3 MiB |
| 최상위 무영향, W | 3 | 군마다 0→0 | J 판정 없음; 안전 증거로 세지 않음 | 5.650–5.668초 | 108.3 MiB |
| 최상위 무영향, S+J | 3 | 군마다 1→1 | 각 군 `outputs_equal`, L1 0 | 9.808–10.016초 | 230.6 MiB |

12군의 호출 wall 합계는 120.151초다. 모두 O0 **3제약**, 기준 witness의 snarkjs 확인, 30초 상한 안 종료, `cleanup_complete=true`, 잔존 관측 후손 0이었다. 총 J 판정은 15개이며 fsync 이벤트와 결과 색인·J 결과 SHA가 일치했다. 양성의 12 L1은 **반복 후보의 클래스 수**이고 고유 원인 수가 아니다. 군별 준비·퍼징·J 시간과 peak는 [파생 표](../runs/n7-allcost-2026-10-28/execution-v6/derived-operations-summary.json)에 있다. 첫 군 시작 내장 여유 83.678 GiB, 마지막 군 종료 83.651 GiB. OS 캐시는 비우지 않았다.

## 구현·검사 영수증

고치기 전 [백업](../runs/n7-allcost-2026-10-28/backups/pre-v6/sha256.json)의 실행기 SHA는 `20eb9127ea69e1eeb5920e885a2055364e7bcb7c354ee57357d9f1e2ee0d14f4`; 변경 후 [실행기](../scripts/n7_allcost_pilot_20261028.py) SHA는 `29f0230ca7aab6d2bd8aaa9007d47d0e9aa89041efb7b6ff0b0cf31cc34a1813`이다. 새 [v3 정의](n7_allcost_pilot_protocol_v3_2026-10-28.md) SHA는 `5fbe3d84f597b30845b5536a2c878e6b343d9cac44ee4cbcac736201b95a4f99`이다. v5 계획 SHA `7efdac2f926664e07798a1b71ed1e2952b1c9f6bff499a06812f0a1504070f01`, v6 계획 SHA `d799171a63018a3df01f9f76e796c3ae3495af720cca2d0906f68a1d5727b9a5`, v6 요약 SHA `98f4c71e1579b1061480b2a0938e499d5107197ddd06dc3d0141b40c26ab64c8`이다.

[실행기](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/n7_allcost_pilot_20261028.py:372)는 후보가 없는 군을 `no_in_budget_candidate`로 따로 기록하고, [의미 관문](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/n7_allcost_pilot_20261028.py:384)은 자연 후보·원본 검사·예산 안 J·fsync 이벤트 대조를 군별로 확인한다. 상위 요약은 관문 전체의 통과/실패를 표시한다. v5 원본 12군을 v3 검사 함수로 읽는 진단과 고의 결함 주입 3건을 검사했으며, 결함 3건 모두 거부됐다. 이 진단은 v5의 고정 v2 결론을 변경하지 않는다.

`cargo fmt --all` 및 `--check` 통과. 전용 `runs/n7-allcost-2026-10-28/cargo-target`, nice 19, `-j 1`, 30/20/18 GiB 내장·8 GiB target 감시 아래 [Clippy](../runs/n7-allcost-2026-10-28/cargo-monitoring/monitor/n7-clippy-1/result.json) `--all-targets --all-features -- -D warnings` 통과(40.38초), [cargo test](../runs/n7-allcost-2026-10-28/cargo-monitoring/monitor/n7-test-1/result.json) 427 통과·0 실패·24 제외(141.84초). 제외한 24개는 대형/격리 J 검사용이며 이번 새 코드에 Rust 변경은 없다. target 최종 크기 0.674 GiB. 감독기 기존 5검사는 [통과 기록](../runs/n7-allcost-2026-10-28/supervisor-tests-v2/summary.json)을 유지한다. 고정 준비 바이너리 `f8c9f64d…`, J v2.3 `05649971…` SHA는 종료 시에도 일치했다.

## 남은 관문

v4 네 번째 군은 14번째 퍼저 시도 후 후보가 임시 로그에 있었으나 `PermissionError: [Errno 1] Operation not permitted`로 로그 확정 전에 멈췄다. 기존 v4가 traceback을 보존하지 않아 실패 syscall은 모른다. v6의 최대 2회 시도에서는 재발하지 않았다.

고정 v1/v4 소스를 변경하지 않고, v6의 작은 W 입력·preflight를 읽기 전용으로 재사용한 [예외 추적 진단 코드](../runs/n7-allcost-2026-10-28/eprem-diag-worker.py)와 그 [반복판](../runs/n7-allcost-2026-10-28/eprem-diag-worker-v2.py)을 별도 30초 감독 아래 실행했다. 각각 15초·최대 20회 한도에서 **4회×15시도=60시도**, 예외 추적 이벤트 0, 불완전 ledger 0, 정리 4/4이었다([첫 기록](../runs/n7-allcost-2026-10-28/eprem-diag-v1/work/summary.json), [나머지 3회 상태](../runs/n7-allcost-2026-10-28/eprem-diag-v2-state.json)). 입력 spec SHA `6008aa399e00ab1f19d3378712e1a973b1af669fb6fbcc615f568f9721047498`, 첫 진단 코드 SHA `7a3ed0cefc888e383978c575360f9fef3bea80c2ae886191a85cf74121606469`, 반복판 SHA `95da25647c98a78cc6264c64fbfa513feb955b49b3f2d670326ea106780809a3`이다. 이 진단은 예외를 추적해 실행 시각을 바꿀 수 있으므로 **재현 실패는 근본 원인 해결의 증거가 아니다.** 큰 A에서 같은 오류가 나면 인프라 실패·미판정으로 남기고, 해당 예외가 추적된 새 기록으로 위치를 특정해야 한다.

이번 W 음성군은 약 5.7초에 끝나 총 30초 중 나머지 예산이 유휴였다. 따라서 이 시범의 탐지 수·시간으로 W와 S+J의 효능을 비교하면 안 된다. 큰 A 비교의 다음 버전에서는 준비·퍼징·J·원본 검증의 같은 총시간, 유휴 예산 재배분, 독립 seed, 원인 중복 제거, 사람 검토 비용을 **결과 전에** 고정해야 한다. A는 개발 근거이고 독립 평가의 추가 실행은 N5와 채택 개정을 따른다.

**확인한 것:** 자동 발견→퍼징→J→원본 검증→비용 기록이 작은 양성·음성 회로에서 이어졌고, v3 의미 관문 12/12와 필수 검사를 통과했다.

**추정한 것:** 음성 W가 후보 0인 이유는 최상위 출력 경로가 자식 hint를 소비하지 않는 구조와 부합한다. 큰 회로의 수율·속도·안정성, ScaleCirc 대비 기여는 이 결과에서 추정하지 않는다.
