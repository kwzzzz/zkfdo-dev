# A inference 원본 준비 가능성 결과

2026-10-29. **A는 개발 자료다. 이 시험은 W/S+J 효능·동일 총비용·새 원인을 측정하지 않는다.** aq 이미지·캐시와 B를 사용하지 않았다.

[v1 기준](n7_a_feasibility_protocol_2026-10-29.md)으로 첫 실행했을 때 Circom O0 컴파일은 0.894초에 성공했고 R1CS SHA가 기존 동일 입력 반례 쌍의 원본과 같았다. 이후 합성 전용 파서가 10,000제약 상한으로 401,664제약 헤더를 거부했다. [첫 영수증](../runs/n7-allcost-2026-10-28/a-feasibility-20261029/work/summary.json)은 보존했다. [v2 기준](n7_a_feasibility_protocol_v2_2026-10-29.md)에서 저장소의 일반 R1CS 헤더 판독기로 바꿔 새 worker·계획·출력에서 다시 실행했다.

| v2 단계 | 실측 |
|---|---:|
| O0 컴파일 | 0.895초 |
| 정직 witness 생성 | 0.224초 |
| 원본 snarkjs 검사 | 1.532초, `WITNESS IS CORRECT` |
| 감독 호출 전체 | **2.937초**, peak tree RSS 324,255,744 bytes |

O0 **401,664제약**, R1CS SHA `7efa0199e5da19cbdb1ca503ff35fbaaed69d8757d79a96fe159096ac44880c5`로 [기존 O0 쌍](n5_next_gate_2026-10-28.md)의 원본과 같다. WASM SHA도 기존 쌍의 `e1f2a07a2b737d42378392d53755df7d6a7cb4017b92a190b8b4458694d0519e`와 같다. 감독 상태 `completed`, 후손 정리 참, 시작/끝 내장 여유 약 82.91/82.81 GiB, 산출물 약 98.4 MiB다. [v2 worker 결과](../runs/n7-allcost-2026-10-28/a-feasibility-v2-20261029/work/summary.json) SHA `eea8524503dda689ab8500782327ee6cace6a09e124ffe90175ab799c0a9bde1`, [감독 영수증](../runs/n7-allcost-2026-10-28/a-feasibility-v2-20261029/supervision/receipt.json) SHA `7361e05fe96e5ade78f9fa47b623f90b9ef109b952817be86bcba300a873dd11`, [계획 v2](../runs/n7-allcost-2026-10-28/a-feasibility-plan-v2-20261029.json) SHA `5da436851ae469a5d4f2858e18ecd8c8d69be12a3e5222e8214dc7e69736b8f6`.

선택된 J 기준 입력의 SHA는 `13c9eb44…`이고, 기존 동일 입력 반례 쌍의 특정 요청 입력 SHA는 `d206f8d4…`다. **입력 파일이 다르므로 두 정직 witness의 SHA 불일치는 예상 가능한 일**이며 의미 차이로 해석하지 않는다. 계획에 있던 `expected_honest_o0_witness_sha256`은 이 입력에 적용할 검사가 아니어서 판정에 사용하지 않았다. 컴파일 산출물의 동치와 각 입력의 독립된 원본 검증만 확인했다.

## 자동 조각 준비

[조각 준비 기준](n7_a_split_preparation_protocol_2026-10-29.md)과 [실행 전 계획](../runs/n7-allcost-2026-10-28/a-s-prep-plan-20261029.json)(SHA `c397d1bc9051ddf6a033b627d72f2e33359da6bc3067372c5a27c16a7ca115e5`)에 소스 트리·F-01 도구·설정을 고정했다. 원본을 새 폴더로 복사해 `targets → manifest_for → prepare → small-first plan`을 순서대로 실행했다. [결과 영수증](../runs/n7-allcost-2026-10-28/a-s-prep-20261029/work/summary.json)(SHA `0e0957f0591ebc0b668e7b1b11631a30803b241514a9acaf5a67b5341bace13b`)은 발견 호출 위치 **2,336개**, 준비·계획된 조각 **22개**를 기록한다. 감독 호출 7.399초(발견 3.874초, 준비 3.124초), peak tree RSS 674,201,600 bytes, 작업 산출물 약 261 MiB, 후손 정리 완료였다.

기존 A S spec도 22개 조각이지만 새 계획과 **target ID 집합·순서는 같지 않다.** 새 소스 사본 경로가 식별자에 반영됐을 가능성이 있으며, 지금 확인한 것은 개수와 자동 준비 성공까지다. 동일한 22개 의미 조각이나 같은 퍼징 성과를 재현했다고 말하지 않는다. `known_defects` 필드는 22개 모두 비어 있어 준비 순위에 결함 목록을 사용하지 않았다. 새 S 퍼징과 후보의 J 검증은 실행하지 않았다.

저장소 필수 관문은 `cargo fmt --all` 및 `--check` 통과, 전용 target·nice 19·`-j 1`에서 [Clippy](../runs/n7-allcost-2026-10-28/cargo-monitoring/monitor/n7-a-clippy-20261029-1/result.json) 경고 0, [cargo test](../runs/n7-allcost-2026-10-28/cargo-monitoring/monitor/n7-a-test-20261029-1/result.json) 427 통과·0 실패였다. 대형/격리 J 24시험은 기존 bounded 규칙대로 필터 제외했다. 이번 작업은 Rust 코드를 바꾸지 않았다.

**확인한 것:** A 원본·선택된 기준 입력은 이미지 없이 로컬에서 컴파일·검증 가능하다. 원본 R1CS/WASM은 기존 증거와 일치한다. 2,336 호출 위치에서 22개 조각을 자동 준비하는 경로도 새 사본에서 끝까지 동작했다.

**추정한 것:** 기존 S spec과 새 22개 조각의 의미 동치, 전체 A 퍼징·후보별 J의 시간·공간·수율은 이 준비 시험에서 알 수 없다. A는 결과를 본 뒤 선택됐으므로 여기서 독립 성능이나 ScaleCirc 대비 우위를 주장하지 않는다.
