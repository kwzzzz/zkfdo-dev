# RQ1 inference 원인 귀속 진단 (2026-10-28)

**A 개발 자료의 사후 진단이다. J 보강 성과나 N5 L2 판정이 아니다.** [읽기 전용 검토 규칙 v1](rq1_inference_causal_review_rule_2026-10-28.md)은 새 컴파일을 금지한다. 아래 격리 컴파일은 그 규칙의 결과로 소급하지 않고 **별도 사후 반사실 실험**으로 기록한다. 원본 N6/L-06 파일은 수정하지 않았다.

## 먼저 바로잡은 수치

[기존 RQ1 증거 문서](rq1_inference_evidence_2026-10-28.md)는 **196,096개를 O0 제약 수라고 잘못 표기**했다. 이는 최적화된 기본/O1 R1CS(179,712 비선형 + 16,384 선형, 197,898 wires)의 수다. 같은 원본 소스를 J와 동일한 circom 2.2.3 옵션으로 재컴파일한 **O0는 401,664제약**(183,552 + 218,112, 401,930 wires)이다. O0 R1CS SHA-256 `7efa0199e5da19cbdb1ca503ff35fbaaed69d8757d79a96fe159096ac44880c5`가 N6 영수증과 같고, SYM SHA-256 `6eecf15837ca1b918f890ef9f04e1becfb138294a16c5d343431d7948d0a6ed4`는 L-06 사본과 같다. **W 실행의 회로 크기는 최적화 R1CS 196,096제약으로, J의 엄격 O0 검사는 401,664제약으로 각각 적어야 한다.**

## 원본 증인에 대한 한 줄 반사실

원본 [integerDivision.circom:31](../runs/n6-a1b-2026-10-08/units/inference-original/project/src/integerDivision.circom#L31)의 `out <-- quot`를 격리 사본에서 `out <== quot`로만 바꿨다. 원본 소스 SHA-256 `325e1432…`, 수정 사본 `1d053ab2…`. 수정 O0 R1CS는 403,712제약, SHA-256 `6852a55608543231cf1e554bea891507c6cfa588859c953145315d6d1510a5c1`; SYM은 원본과 바이트 단위로 동일하다. 도구는 circom 2.2.3(SHA `89918878…`), snarkjs 0.7.6이다.

| 보존된 원본 O0 증인 | 원본 snarkjs | 한 줄 수정본 | 실패 제약 전체 |
|---|---:|---:|---|
| TCCT 양성 5/7요청, 13파일·고유 SHA 7개 | 모두 통과 | 모두 거부 | 각 증인의 실패 제약 **전부** IntDiv 인스턴스들의 `out = quot` |
| 술어 양성 22/36요청, 22파일·고유 SHA 14개 | 모두 통과 | 모두 거부 | 각 증인의 실패 제약 **전부** IntDiv `out = quot` |
| 합계 27/43요청, 35파일·고유 SHA 21개 | 21/21 통과 | 21/21 거부 | 다른 종류의 실패 제약 0 |

처음 고른 TCCT 대표 2개의 원본 WTNS SHA는 `3b1d5cd1…`(`honest_aborted`)와 `2f20a25b…`(`output_differs`)이다. 수정본의 첫 실패는 각각 0기반 제약 **136712**, **87560**이며 SYM으로 해독하면 `main.int_div_3[0].out - quot = 0`, `main.int_div[0].out - quot = 0`이다. 실패 제약 전체는 각각 512개와 768개이고 모두 같은 소스 줄에서 생긴 등식이다. [개별 영수증](../runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/counterfactual_result_v1.json)(SHA `c401a8fb…`), [TCCT 전체 분류](../runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/preserved_tcct_failure_classification_v1.json)(SHA `c290b32d…`), [술어 전체 분류](../runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/predicate_failure_classification_v1.json)(SHA `7b4c88a6…`)에 파일별 결과를 남겼다.

**귀속 범위:** TCCT 5요청에서 저장된 특정 위반 증인은 IntDiv 출력 제약 누락에 반사실적으로 귀속된다. 술어 22요청에서 확인한 것은 **저장된 증인의 IntDiv 의존성**이다. 술어는 다른 입력에서 계속 참일 수 있으므로, 22개 술어 자체가 IntDiv 때문에만 성립한다고 결론 내리지 않는다. O0가 현지에 없는 나머지 16요청은 이번 직접 대조 밖이다(Subtract TCCT 2, O1만 있는 술어 탐색 1, 인스턴스 공유 영수증 13). 요청 43개, 기계 군집 12·10개, 증인 21개를 고유 원인 수로 바꾸지 않는다.

## 별개의 DFS 범위 누락 메커니즘

L-06의 기존 A 입력(SHA `cb589bb9…`)을 IntDiv **한 줄 수정본의 정직한 O0 생성기**에 넣었다. 생성된 WTNS SHA `dbed958f…`는 L-06에 기록된 원본 정직 O0 증인 SHA와 정확히 같다. 원본과 IntDiv 수정본의 O0·snarkjs가 모두 통과한다. `main.distance_from_score_fn[0].positive`는 입력 `(p−1, 4)`에 출력 `1`인데 정수 비교 `p−1 < 4`는 거짓이다. [도달 영수증](../runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/dfs_property_persistence/dfs_property_persistence_v1.json)(SHA `a10f1f44…`).

여기에 [DistanceFromScore](../runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/dfs_property_persistence/fixed-both/src/distanceFromScore.circom#L17)의 두 입력에만 L-06과 같은 `Num2Bits(40)` 범위 제약을 추가하자, **같은 입력**의 정직 생성이 `previous_score` 연결 23행에서 `Num2Bits` assert로 중단됐다. `p−1 > 2^40−1`이므로 이 입력은 그 추가 제약으로 수학적으로도 불가능하다. [선택 수정 영수증](../runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/dfs_property_persistence/dfs_selective_fix_v1.json)(SHA `bf078db4…`). 이는 IntDiv의 출력 무제약과 **독립된, 공개 입력 범위 누락에 따른 의미 위반**이다. 같은 입력의 출력 비유일성을 보인 것은 아니다. 외부 검증자가 공개 입력을 40비트로 보장한다면 실제 공격 해석은 달라진다. 이 별도 입력은 N6 대표 요청의 입력이 아니므로 **N6 DFS 요청의 원인 귀속으로 세지 않는다.**

## 일곱 대표와 결론

| 대표 부류 | 이번에 확인한 범위 |
|---|---|
| IntDiv `honest_aborted` / `output_differs` | 실제 N6 증인의 한 줄 수정 반사실 확인. 검토된 TCCT의 소스 메커니즘 1개 |
| Clamp `LessThan[0]` | L-06/L-07에서 IntDiv 연쇄. 이번 직접 O0 증인은 없음 |
| DistanceFromScore `positive` | N6 저장 증인은 IntDiv 의존. 별도 L-06 정직 입력에서 IntDiv 수정 후에도 위반 유지 |
| ResponseTimeNormalized `LessThan`, ScoringFunction `lt` | 저장 증인만 IntDiv 의존 확인. 술어 자체의 독립성은 미판정 |
| Subtract `honest_aborted` | 로컬 O0 증인 없음. 중단 원인 미판정 |

따라서 **A 원본 회로에서 서로 다른 도달 메커니즘 최소 2개**(IntDiv 출력 무제약, DFS 공개 입력 범위 누락)는 확인했다. **N6의 43 L1요청에 대한 완전한 고유 원인 수는 미산정**이다. 여기서 새 결함 발견이나 N5 L2 점수, ScaleCirc 대비 우위는 주장하지 않는다. 같은 600초 *퍼징* 예산에서 W 후보 0·S 후보 69·J L1 43요청이라는 기존 관측은 유효하지만, S+J에는 J 1,907.873초가 추가되어 같은 총시간 우위가 아니다. 기여 후보는 “조각 탐색의 양성 신호를 원본에서 검증하고, 저장 증인의 수정 의존성과 술어의 대체 도달성을 구분하는 절차”이며, 이 절차의 일반성과 선행 대비 우위는 아직 평가가 필요하다.

외부 검토와 반론을 주고받으며 고유 원인·회로 크기·27요청 귀속의 과장을 각각 좁혔다. 현재 A 개발 진단은 여기서 닫고, 다음에는 고정 N5 절차의 본 평가와 총비용·대조군을 우선한다. [기계 요약](../runs/rq1-causal-review-2026-10-28/intdiv_fix_pilot/summary_v1.json)(SHA `e8860baa…`)은 위 수치를 원천 영수증과 대조한다. Rust/실행기 코드는 변경하지 않았고 새 퍼징·J·solver 판정도 실행하지 않았다.

**확인한 것:** 원본 O0 해시 재현, 21개 보존 O0 증인의 원본 통과와 수정본의 IntDiv 등식 전용 실패, 별도 DFS 정직 입력의 IntDiv 수정 후 위반 및 DFS 범위 수정의 동일 입력 차단, O0/O1 크기 정정.

**추정한 것:** 저장되지 않은 16요청의 원인, 43요청 전체의 고유 원인 수, 다른 입력에서의 RTN·Scoring 술어 지속 여부, 외부 공개 입력 계약에서의 악용성, ScaleCirc/zkFuzz 대비 일반 우위.
