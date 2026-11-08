# ScaleCirc 원문 대조: zkfDO의 남는 주장과 필요한 증거

2026-10-28. 자료는 데스크탑의 [*ScaleCirc: Scaling the Analysis over Circom Circuits* PDF](</Users/miiz/Library/Mobile Documents/com~apple~CloudDocs/Desktop/TalkFile_ScaleCirc_Scaling_the_Analysis_over_Circom_Circuits.pdf>) (ASE 2025, DOI `10.1109/ASE63991.2025.00124`, 13쪽, SHA-256 `0f51d5857d1d7de1ef70748ecf5db16da0b1bf8fd37c237e5cb1413835d5bf70`)와 [저자 공개 코드](https://github.com/jinan789/ScaleCirc) 리비전 `3d05d0f3e82816135419dba37dde91d48cb65068`이다. PDF는 사용자가 저장한 IEEE 라이선스 사본이며 재배포하지 않는다. 아래의 페이지는 PDF 뷰어 페이지가 아닌 인쇄 페이지(1464–1476)다. 이 문서는 [전문 미확보였던 10-27 검토](scalecirc_overlap_review_2026-10-27_v1.md)와 [10-28 경로 점검의 원문·코드 미확인 문장](../runs/j-boost-2026-10-27/step5/continuation/rq1_course_check_20261028.md)을 **정정**한다. 공식 논문과 코드는 확인 가능하다.

## 원문에서 확인한 방법과 보장

| 위치 | ScaleCirc의 실제 내용 | 우리 주장에 주는 영향 |
|---|---|---|
| §II-B, p.1466 | under-constrained는 **동일한 회로 입력을 가진 유효 witness 두 개의 출력이 다른 경우**다. | 계산 중단(`honest_aborted`)까지 포함하는 zkFuzz식 TCCT와 목표가 다르다. 출력 차이만 공통 교집합으로 비교한다. |
| Algorithm 1, pp.1466–1467 | AST·템플릿 인자별 재귀 분석, 결과 캐시, 자식 결과의 부모 전파, backend 후처리. | 자동 분할·재사용·부모 연결이라는 큰 줄기는 선행에 있다. |
| §III-D1, pp.1467–1468 | `ConstProp`의 추론 규칙 1–14가 제약 연산, 배열 범위, 분기, 반복문, 대입 이력을 다룬다. | ScaleCirc를 단순 R1CS 쪼개기나 단순 정적 경고로 축소하면 틀린다. |
| §III-D2 Eq.16, pp.1468–1469 | 안전한 자식의 출력을 부모의 자유 입력으로 치환해 과대근사한다. 변형 부모도 안전하면 원본 안전이다. 변형 부모의 unsafe는 원본에서 다시 확인한다. | 이 안전 증명은 J의 **특정 후보값**에 대한 배제보다 범위가 넓다. 두 결과를 같은 종류의 판정으로 비교하지 않는다. |
| §III-D2 Eq.17, p.1469 | **자식의 두 반례 witness를 부모 입력에 연결하고**, 자식을 출력 신호로 치환해 부모 WASM witness 두 개의 출력 차이를 본다. 조건은 자식 입력이 제약 연산으로 부모 입력에 직접 연결된 경우다. 같은 출력이면 이 전파를 끝내며, 후처리 backend가 남는다. | “자식 반례를 원본 맥락으로 올려 출력 영향을 검사한다”는 J의 독립 신규성이 아니다. |
| §III-E–F, pp.1470–1471 | ZKAP의 자료 흐름·제약 그래프 기반 불일치 분석과 Circom `--inspect`의 미제약 신호 분석에도 틀을 적용한다. | ScaleCirc가 witness/constraint 불일치 문제를 아예 다루지 않는다고 말할 수 없다. |
| §V-A, p.1474 | EC 암호 회로, 실행 시 값에 좌우되는 맥락, 자기 재귀 연결 등의 한계를 명시하고 일부는 원래 backend로 돌아간다. | 그 한계를 근거로 우리 도구의 우위를 선언하려면 실제 해결 사례가 필요하다. 현재 A의 EC 사례는 우리도 막혀 있다. |

공개 구현의 [자식 UNDER 전파](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L1820-L2030)는 실제 호출 경로 [L2090](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L2090)을 가진다. `check_UNDER_case`는 입력 직접 대응을 확인하고 두 자식 반례로 부모 사본을 만들며, 남는 부모 입력 조합을 최대 20회 시도해 부모 출력 차이를 확인한다. [입력 채우기](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L2198-L2292)는 자유 슬롯의 값을 선택한다. 따라서 논문의 “추가 탐색 없이 종료”를 문자 그대로 단 한 번의 실행으로 읽어서도 안 된다. 이 경로가 직접 연결 외의 모든 경우를 처리한다는 뜻은 아니며 [후처리 backend로 돌아가는 경로](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L2090-L2179)까지 포함해 비교해야 한다.

**구현에서 별도 확인이 필요한 지점:** 두 부모 witness 생성은 같은 `tried_combos`를 순서대로 사용하고([L1919–1925](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L1919-L1925)), 자유 부모 입력에는 아직 쓰지 않은 비트 조합을 넣는다([L2257–2288](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L2257-L2288)). 출력 비교 [L1941](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L1941) 직전에는 두 부모 입력의 동일성 검사가 보이지 않는다. 자유 슬롯이 있으면 다른 입력 때문에 출력이 달라질 위험이 있다는 **정적 코드 우려**다. 실제 거짓 양성이나 논문 결과 오류를 재현한 것은 아니다. 이것을 우리 신규성·우위의 증거로 사용하지 않는다.

## 기능별 중복·차이·입증 상태

| 기능 | ScaleCirc 원문·코드 | 현재 zkfDO S/J | 판정 |
|---|---|---|---|
| 조각 자동 구성·재사용 | Algorithm 1; 템플릿 캐시 | [`targets.rs:2660–2685`](../src/targets.rs), 구체 인자 wrapper와 호출 위치 유지 | 일반 아이디어는 중복. 실제 적용성과 총비용만 비교 가능 |
| 자식 반례의 부모 영향 | Eq.17; `check_UNDER_case` | [`lifting/mod.rs:2331–2405`](../src/candidate_review/lifting/mod.rs), 같은 입력·출력/중단 비교 | **직접 중복**. J 자체의 신규성으로 쓰지 않음 |
| 계산된 중간 입력으로 역탐색 | Eq.17의 빠른 전파는 부모 입력 직접 연결 조건; 그 밖에는 backend | [`lifting/mod.rs:2679–2724`](../src/candidate_review/lifting/mod.rs), 상류 입력 합성과 수리 | 구현상 차이 후보. ScaleCirc 전체 backend보다 낫다는 결과 없음 |
| 정확 후보값과 의미 위반 술어 분리 | §II-B의 회로 전체 underconstraint; 동일한 두 질문을 분리한 계약은 확인하지 못함 | 정확 후보를 맥락에서 확인/배제/unknown; 술어는 현재 제한적으로만 지원 | 문제 설정 차이 후보. `∃` 질의 두 개를 쓴다는 사실만으로 신규성 아님 |
| 배제 근거의 범위 | Eq.16의 원본 전체 안전 추론과 unknown | [`lifting/mod.rs:3516–3595`](../src/candidate_review/lifting/mod.rs), 고정 입력·후보 신호의 국소 모순 | **서로 다른 보장**. J 배제로 전체 회로 안전을 주장할 수 없음 |
| 원본 witness 검증 | 논문은 두 유효 witness의 출력 차이를 보장으로 설명; Eq.17은 변형 부모 생성과 반례 구성. 해당 코드 경로만 읽어 원본 R1CS 재검사 호출 여부를 확정하지 않음 | [`lifting/mod.rs:2288–2328`](../src/candidate_review/lifting/mod.rs), 선택 기능 [`boost.rs:330–392`](../src/candidate_review/lifting/boost.rs)의 O0/O1 Rust·snarkjs 검사 | 명시적 증거 계약의 차이 후보. 검사기 두 개 자체를 새 알고리즘으로 세우지 않음 |
| 정상 계산과 출력 영향 | ScaleCirc의 UNDER는 동일 입력의 두 유효 witness·다른 출력 | [`lifting/mod.rs:2402–2405`](../src/candidate_review/lifting/mod.rs), `honest_aborted` 또는 `output_differs`; 선택 기능의 `aligned` | `output_differs`는 비교 가능, abort는 zkFuzz에서 물려받은 범주. 별도 신규성 아님 |

논문 §IV-B4, p.1472에는 Window4의 MontgomeryDouble 자식 반례를 부모로 전파한 실제 사례도 있다. 따라서 EC 부품 반례 전파 자체를 우리 첫 사례로 소개해서는 안 된다. 반대로 이 논문의 `safe/unsafe/unknown`과 J의 `excluded_in_context`를 서로 대응하는 세 칸으로 묶으면 논리 범위가 틀어진다. J는 입력과 후보값을 고정한 `UNSAT`만으로 **다른 값의 같은 위반**이나 전체 안전을 배제하지 않는다.

우리 기존 J는 정직/변형 witness를 [같은 `input.json`에서 생성](../src/candidate_review/lifting/mod.rs)하지만, [`public_inputs_equal` 확인](../src/candidate_review/lifting/mod.rs)은 이름 그대로 공개 입력만 직접 비교한다. 선택적 직접 완성 경로는 [`boost.rs:393–435`](../src/candidate_review/lifting/boost.rs)에서 원본 witness의 모든 입력 wire와 정직 witness의 동일성을 확인한다. 따라서 기존 J 전체가 두 witness의 **모든** 입력 wire 동일성을 독립 검사한다고 과장하지 않는다. ScaleCirc 구현 우려를 우위로 삼기 전에 양쪽에서 같은 입력 조건을 재현 실험으로 확인해야 한다.

## 평가에서 확인한 숫자와 불일치

§IV-A–B, pp.1471–1472의 데이터는 **691회로**(circomlib 183, GitHub 19프로젝트 508), 평균 **225,327제약**, 600초 제한이다. ScaleCirc는 Picus가 못 푼 70회로, ConsCS가 못 푼 56회로를 추가로 검증했다. Table I에는 좋아진 행뿐 아니라 변화가 없거나 시간 악화인 행도 있다. 이는 우리 W 대 S+J 동일 예산 평가와 다른 연구 질문이다.

§IV-B4의 **zkFuzz 직접 비교**는 같은 벤치마크에서 zkFuzz 93개(비결정 29, 계산 중단 64), ScaleCirc 24개(비결정), 비결정 유형의 한쪽만 찾은 수는 zkFuzz 7·ScaleCirc 2라고 보고한다. 버그 회로당 평균 시간은 각각 152.44초와 10.59초다. zkFuzz의 중단 검출은 우리만의 발명이 아니고, 논문의 성능 숫자만으로 우리 S+J가 어느 쪽을 넘는다고 할 수 없다. [학회 공식 초록](https://conf.researchr.org/details/ase-2025/ase-2025-papers/173/ScaleCirc-Scaling-the-Analysis-over-Circom-Circuits)은 “미보고 결함 3건”이라고 적지만, 본문 §IV-B4는 **이번 기준선이 놓친 3건이며 다른 곳에 이미 보고되었다**고 쓴다. 이 충돌은 본문의 더 좁은 설명으로 인용한다.

## 긍정적으로 볼 수 있는 실제 자산

**연구 질문이 다르다.** ScaleCirc의 주된 성과는 회로의 안전성 검증을 확장한 것이다. 우리 주 질문은 위치를 미리 주지 않고 작은 퍼징 단위를 자동 구성해 **결함 후보를 생성**하고, 원본 호출 위치에서 도달·배제·미판정을 구별하는 것이다. ScaleCirc 논문 자체가 zkFuzz가 자신보다 많은 결함, 특히 계산 중단을 찾았다고 보고한다. [zkFuzz 원논문 §VIII](https://arxiv.org/html/2504.11961v3#S8)는 실행 비용이 대상 크기에 비례하며 slicing·부분 실행이 개선 방향일 수 있다고 쓴다. 즉 자동 조각 퍼징은 선행이 남긴 실질적 문제를 다룬다. 단, zkFuzz에 퍼징이 이미 있고 ScaleCirc에 부모 반례 전파가 이미 있으므로 **단순 결합**을 최초 발명이라고 주장하지 않는다.

| 이미 확인한 것 | 긍정적 의미 | 제한 |
|---|---|---|
| [A 대형 회로](contribution_assessment_2026-10-27_v1.md#2-실제-결과와-정확한-해석): inference-original 196,096제약, 세 seed 총 1,800초에 W 후보 0·S 후보 신호 69. 10만 제약 이상 공식 main 21리비전에서는 W 후보 0, S는 20리비전에서 후보를 생성했다. | 큰 원본에서 탐색이 멈춰도 자동 조각 퍼징은 후보를 만들 수 있다. | 후보 69개·20리비전은 검증된 결함 수가 아니며 총비용 우위도 아니다. |
| [Subtract 원본 검토](../reports/n4-1-a02-first-semantic-review-2026-10-02/REPORT.md): S 후보가 원본 196,096제약과 snarkjs를 통과하고, 두 호출 위치에서 같은 공개 입력의 1,024개 최상위 출력 중 하나를 바꿨다. | 조각 후보가 원본 의미의 양성 결과로 이어진 실제 end-to-end 사례다. | 이미 알려진 같은 원인의 반복이며 새 고유 결함이 아니다. 해당 개발 실행은 W와 S의 총예산이 공정하지 않았다. |
| [J의 맥락 검토](lifting_l05_results_2026-10-03.md), [수정본 대조](lifting_l07_results_2026-10-06.md): 개발 사례에서 Banyan 36/36 도달, zk-email 9/9 배제, Clamp의 후보값 배제와 같은 오류 술어 도달을 구별했다. | 조각 신호를 무조건 버그로 세지 않고 호출 위치·입력 범위에 따라 판정하는 기능이 실제로 작동한다. | 알려진 개발 사례이며 비교 도구 대비 검증 수율 우위는 아니다. |
| [자동 준비](f01_discovery_results_2026-10-03.md): production 656개 중 성공 44→107. [컴파일 재사용](../reports/t6a-compile-reuse-2026-09-26/REPORT.md): 18 entrypoint의 5,240 호출 위치 컴파일을 63회로 줄이고 전체 시간 164.2→14.1초. | 자동 적용성과 대규모 실행 비용을 낮추는 시스템 자산이다. | ScaleCirc에도 캐시가 있다. 탐지 성과와 별개로 평가해야 한다. |

따라서 가장 강한 **긍정적 가설**은 “자동 조각 구성으로 전체 zkFuzz가 후보를 내지 못하는 큰 회로에서 퍼징 가능한 단위를 만들고, J가 그중 원본에서 실제 가능한 결과와 맥락상 불가능한 후보를 분리해 **검증된 고유 원인/총비용**을 개선한다”이다. ScaleCirc와는 발견 목표, zkFuzz 전체 실행과는 자동 조각과 호출 맥락 검토가 다르다. **가설을 시험할 구현과 양성 개발 사례는 이미 있다.** 고정 18항목에서 W와 S+J의 원본 L1은 각각 1항목이고 W가 더 빨랐으므로, 아직 일반 우위는 입증되지 않았다.

## 스스로 반박한 뒤의 결정

1. **가장 강한 반론:** 우리 파이프라인은 “zkFuzz 후보 + ScaleCirc도 하는 부모 반례 전파 + 후보별 국소 UNSAT”로 보일 수 있다. 더구나 ScaleCirc의 안전 판정은 J의 정확 후보 배제보다 강하다. Eq.17의 직접 연결이 실패해도 원래 backend가 부모 전체를 분석하므로, 계산된 중간 입력의 역탐색이 **능력** 차이가 아니라 **비용** 차이에 그칠 수 있다. 지금은 동일한 문제·회로·전체 비용에서 ScaleCirc가 못 한 원본 검증 결과를 우리만 얻었다는 증거가 없다. 별도 외부 반론도 이 점에 집중했다.
2. **남는 최소 가설:** 직접 연결되지 않은 **계산된 자식 입력**에서도, S의 조각 위반을 호출 위치별로 원본에서 확인하거나 범위를 한정해 배제하고 `unknown`을 유지하는 조합이 실용적일 수 있다. 이는 이미 구현한 자산을 쓰는 가설이다. A 4·5차의 추가 원본 도달/L1은 **0건**이므로 성과로 쓰지 않는다. 합성 MAdd의 “정확값 UNSAT, 같은 위반의 다른 값 SAT”는 두 질문의 차이를 보인 교육용 예시이지 실제 개선 증거가 아니다.
3. **반증 가능한 다음 비교:** 먼저 기존 A의 원본 검증 L1 한 항목이 **계산된 중간 자식 입력** 사례인지 기록만으로 확인한다. 맞는 사례가 없다면 해당 방법 가설을 뒷받침할 양성 사례도 없는 것이다. 사례가 있으면 같은 **출력 비결정성** 속성, 같은 entrypoint·입력 계약·총시간(준비·분석·검토 포함)으로 ScaleCirc 공식 구현, zkFuzz W, S+J를 비교한다. ScaleCirc의 `safe/unsafe/unknown`과 J의 후보별 도달·배제를 별도 열에 남기고, 최종 원본 witness 쌍과 고유 원인만 공통 성과로 센다. ScaleCirc가 같은 결과를 내면 능력 차이 가설은 반증되고 비용 비교만 남는다. 계산 중단은 zkFuzz W 대 S+J에서 별도 평가한다. 규모가 작은 실제 회로에서 차이가 먼저 확인되지 않으면 대형 EC 사례 SMT에 시간을 더 쓰지 않는다. 이 비교 전에는 “ScaleCirc를 넘어섰다”는 문장을 쓰지 않는다.

**작업 우선순위:** 추가 논의에서는 위의 세 도구 비교를 곧바로 실행하는 것보다, 먼저 4d의 준비 결손을 해결해 **동일 총예산 W 대 S+J**를 판별 가능하게 만드는 쪽이 주 연구 질문에 더 직접적이라는 결론에 도달했다. ScaleCirc 한 번의 실행은 차별화 검토에는 유익하지만 W 대비 이득을 답하지 못한다. 4d도 A 개발 결과이며 그 자체를 독립 성과로 세지 않는다.

**확인한 것:** PDF 원문과 공개 코드의 전파 경로, 안전/불안전/미판정의 범위, 691회로와 zkFuzz 비교 수치, 현행 J의 합성·검증·배제 코드, A 추가 도달/L1 0건.

**추정한 것:** 계산된 입력에서 S+J가 ScaleCirc 전체보다 높은 수율을 낼지, 제한된 술어 일반화가 실제 결함을 추가로 찾을지, 같은 예산의 W 대 S+J가 유리할지. 아직 비교 실험이 없다.
