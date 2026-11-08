# ScaleCirc와 zkfDO의 기여 중복 검토 v1

2026-10-27 KST. **공개 구현 대조 결과, 자동 분해·분석 재사용뿐 아니라 하위 반례의 부모 회로 전파까지 상당히 겹친다.** 따라서 “기존 연구는 확장성만 다루고 우리는 로컬 반례를 전체 맥락으로 연결한다”는 구분은 사용할 수 없다. 현재 zkfDO에서 더 구체적으로 비교할 부분은 계산된 내부 입력의 역합성·수리, 후보 값과 의미 위반 술어의 구별, 원본 제약에 연결된 도달·배제 근거다.

**본문 전문 대조는 미완료다.** IEEE 본문 PDF의 접근 권한이 없었으며 저자 홈페이지의 Paper 링크는 자기 페이지로 돌아온다. 이번 판단은 공식 초록, 공개 부록 2쪽 전체와 공개 구현의 관련 경로에 근거한다. 본문 정리·증명·평가표까지 읽었다는 뜻이 아니다. 기존 [기여 재평가](contribution_assessment_2026-10-27_v1.md)와 [29일 설명안](contribution_brief_2026-10-29_v1.md)은 당시 기록으로 보존한다.

## 확인한 자료

- 논문: Jinan Jiang, Haoran Qin, Xiapu Luo, *ScaleCirc: Scaling the Analysis over Circom Circuits*, ASE 2025, pp. 1464–1476, DOI `10.1109/ASE63991.2025.00124`. [학회 공식 설명](https://conf.researchr.org/details/ase-2025/ase-2025-papers/173/ScaleCirc-Scaling-the-Analysis-over-Circom-Circuits), [IEEE](https://ieeexplore.ieee.org/document/11334720/).
- [공개 artifact](https://github.com/jinan789/ScaleCirc), 확인 리비전 `3d05d0f3e82816135419dba37dde91d48cb65068` (커밋 날짜 2025-10-13). 이전 평가에서 artifact를 확보하지 못했다는 제한은 이번 대조로 해소했다.
- [부록](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/appendix.pdf): Appendix A와 Table III, 총 2쪽. 실제 파일은 데이터셋 설명만 담는다. README가 언급하는 Algorithm 1의 replacement 예시는 이 PDF에 없다.
- [저자 홈페이지](https://jinan789.github.io/)와 [공개 artifact 목록](https://snielebock.github.io/mrpua/)의 PDF 연결을 확인했다. 후자의 실제 PDF 주소도 같은 IEEE 문서로 연결되며 공개 저자판이 아니다.

부록은 20개 벤치마크의 691회로, 그중 Picus에서 가져온 circomlib 183회로와 나머지 19저장소를 설명한다. 전체 평균은 225,327제약이며 220만 제약을 넘는 회로도 포함한다. 이 숫자는 수집 대상의 규모다. 691개 전부를 성공적으로 분석했다거나 모든 대형 회로를 검증했다는 뜻으로 확대하면 안 된다.

## 코드에서 확인한 직접 중복

| 축 | ScaleCirc 공개 구현 | zkfDO에 대한 판단 |
|---|---|---|
| 템플릿별 자동 분석 | 구체 인자로 standalone 회로 생성, 필요 시 하위 템플릿 분석 재귀 호출 | 자동 wrapper·부분 분석 자체로 차별화하기 어려움 |
| 중복 제거·재사용 | 정규화된 소스 내용·템플릿 인자별 결과를 저장하고 재사용 | 컴파일 캐시와 정확히 같지는 않지만 재사용을 통한 확장성이라는 기여 축은 직접 겹침 |
| 정상 제약성 전파 | 입력의 결정성과 하위 템플릿 결과를 이용해 출력으로 전파하며, 이미 분석한 컴포넌트를 치환 | “부분 결과를 부모 맥락에 반영한다”도 선행 범위 |
| 구체 반례 전파 | 하위 UNDER 반례 쌍을 이용해 부모 witness를 생성하고 부모 출력 차이를 검사, 원본 신호 순서로 반례 재구성 | “로컬 반례를 부모로 올린다”는 일반 주장도 직접 겹침 |
| 분석 과제 | UNDER는 ConsCS/Picus, UNCONS는 Circom inspect, DISCREPENCY는 ZKAP 경로 | ScaleCirc를 단순 정적 경고기나 단일 underconstraint 검사기로 축소하면 안 됨 |
| 후보 값과 의미 술어를 별도로 판정 | 검토한 코드 경로에서 zkfDO와 같은 두 판정 계약은 확인되지 않음 | 남는 구체적 차이 후보. 본문 전체의 부재 주장이나 신규성 확정은 아님 |

직접 근거:

- [Source_Code_Manager.py L542–568](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_Source_Code_Manager.py#L542-L568): 구체 인자의 main·standalone 생성.
- [GlobalAnalysis](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_GA.py#L18-L165): 소스 내용 대조와 분석 결과 캐시. `get_fit_category_from_cache`는 인자별 일치·일반 결과를 구분하고 하위 분석을 호출한다.
- [OneTemplateAnalysis L1613–1619](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L1613-L1619): 세 분석 과제의 dispatch. ZKAP 경로는 assignment/constraint 관계를 가져와 부모 분석에 연결한다(L1708–1816).

## 반례 전파는 실제 호출되는 경로다

핵심은 [check_UNDER_case L1820–2030](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L1820-L2030)다. 주 분석 함수의 L2090에서 호출되므로 사용되지 않는 보조 함수만 발견한 것이 아니다.

1. 하위 입력과 부모 입력의 직접 대응을 확인하고, 하위 UNDER 결과에서 두 반례를 가져온다(L1833–1878).
2. 하위 출력을 각 반례 값으로 치환한 부모 사본 두 개를 만든다. 부모 입력은 하위 반례와 연결하고 나머지 입력을 채운다([Source_Code_Manager L928–1042](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_Source_Code_Manager.py#L928-L1042)).
3. 최대 20회 시도에서 부모 witness의 출력 부분 차이를 확인한다(L1908–1944).
4. 원본 sym의 신호 순서로 하위 반례와 부모 계산 결과를 합쳐 부모의 UNDER 반례 쌍으로 저장한다(L1947–2028).

따라서 초기 초록만으로 추측할 때보다 중복 위험이 크다. **반례의 부모 출력 영향 확인까지 선행 코드가 있다.** 다만 이는 정적 코드 독해이며 해당 경로의 건전성·실행 성공률을 새로 검증한 결과는 아니다.

해당 전파에는 직접 부모 입력 연결과 비배열 컴포넌트 등 제한이 있다. 단순한 주석 외에 [L4207–4238](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L4207-L4238)의 대응 기록 조건으로도 확인된다. 이 제한은 그 전파 경로의 제한이며, ScaleCirc 전체가 그 밖의 회로를 분석하지 못한다는 뜻은 아니다. 전파가 안 되면 원래 분석기로 돌아가는 경로도 있다(L2093–2182).

또한 `Circom_Manager.check_witness`는 존재하지만, 읽은 반례 전파 호출 경로에서는 재구성 뒤 이 함수를 호출하지 않는다. 이것만으로 ScaleCirc의 결과가 틀렸다고 판단하지 않는다. 원본 R1CS 재검사·변환 보장·반례 입력 동일성의 전체 계약은 본문과 전체 호출자 대조가 필요하다. zkfDO의 두 검사기 확인도 독립적인 주요 신규성으로 세우지 않는다.

정적 검토에서 추가 주의점도 확인했다. L1919·1925의 두 witness 생성 호출은 같은 `tried_combos` 목록을 공유하고, L2265–2270은 그 목록에 있는 나머지 입력 조합을 피한다. 따라서 고정하지 않은 부모 입력이 있으면 두 witness에 서로 다른 나머지 입력이 선택될 수 있는데, L1941의 출력 비교 앞에는 부모 입력 동일성 검사가 없다. 이 경로의 출력 차이를 검증된 underconstraint 증명으로 받아들일 수는 없다. 실제 오판 재현은 하지 않았으며, 이 정적 우려와 반례 전파를 시도하는 선행 설계의 존재는 별개다.

## 남는 차이는 좁고 구체적으로 제시해야 한다

**계산된 입력의 합성과 수리.** zkfDO는 원래 위치의 입력이 상위 입력에서 계산된 경우를 대상으로 역합성과 실패 인스턴스 수리를 수행한다. 진단·수리 사본은 탐색에 쓰고, 성공 근거는 원본 전체 제약으로 확인한다. [L-02](lifting_synthesis_results_2026-10-02.md), [L-05](lifting_l05_results_2026-10-03.md). ScaleCirc의 직접 연결 전파와 구별할 수 있는 구현 범위다. 그러나 ScaleCirc의 fallback까지 포함한 동일 사례 비교 없이 성능·탐지 우위를 주장할 수는 없다.

**후보 값과 위반 술어는 다른 질문이다.** 현재 [판정 계약](contribution_brief_2026-10-29_v1.md#2-방법을-설명하는-정확한-판정-계약)은 특정 값 보존 `exists w. C_E(w) and B_s(w,c)`와 의미 위반 `exists w. C_E(w) and V_s(w)`를 구별한다. 자동 술어 복원은 현재 LessThan 정수 비교 조건이다. Clamp에서는 후보 값은 상수 맥락과 충돌하지만, 다른 값으로 동일한 술어 위반에 도달했다. 이 차이를 결과와 비용으로 입증하는 것이 단순 backend 교체보다 강한 기여 후보다. 양화의 구별 자체는 새로운 논리 이론이 아니다.

ScaleCirc가 반례 하나의 전파 실패를 곧 “안전”으로 판정한다고 주장해서는 안 된다. 공개 구현에는 원본 backend 분석으로 돌아가는 경로가 있다. 우리가 설명할 것은 선행의 미입증 오판을 고친다는 이야기가 아니라, 특정 의미 술어에서 추가로 얻는 도달·배제 능력이다.

**결과 해석.** [L-07](lifting_l07_results_2026-10-06.md)은 인스턴스별 술어 판정, 공개 입력 변경 여부, 수정 전후와 leave-one-out의 연쇄 의존성을 구분한다. Clamp는 IntDiv만 수정해도 배제되고 DistanceFromScore는 다른 결함 수정 뒤에도 공개 입력 변경으로 도달한다. 이는 좋은 사례 근거지만 각각 독립적인 주요 알고리즘 발명은 아니다. 공개 입력 변경 여부는 발견한 witness의 분류이며 필요조건 증명이 아니다.

UNDER의 출력 결정성과 LessThan의 정수 의미는 같은 속성이 아니다. 출력이 유일해도 비교 의미가 틀릴 수 있다. 다만 ScaleCirc는 ZKAP 기반 DISCREPENCY 경로도 제공하므로 “ScaleCirc는 의미 문제를 전혀 다루지 않는다”는 주장은 쓰지 않는다. zkFuzz의 오라클을 사용하는 것 자체도 zkfDO의 신규성은 아니다.

## 연구 주장에 미치는 영향

| 주장 | 현재 판단 |
|---|---|
| 큰 Circom 회로를 나눠 기존 도구를 적용하는 새로운 프레임워크 | 중복 위험 높음. 이것만으로 주 기여를 세우기 어려움 |
| 로컬 반례를 부모 맥락으로 전파하는 최초 시스템 | 공개 코드와 충돌하므로 사용하지 않음 |
| 정적 분석 대신 퍼징이므로 별개 연구 | backend 차이만으로 충분한 차별성이 되지 않음 |
| 계산된 호출 맥락에서 witness를 합성·수리하고 특정 의미 술어의 도달과 배제를 분리 | 방어 가능한 차이 후보. 전문 비교와 효과성 평가 필요 |
| ScaleCirc 때문에 연구 전체가 이미 동일하거나 무가치함 | 현재 근거로는 성립하지 않음. 직접 겹치는 기반과 더 좁은 확장을 구별해야 함 |

29일 설명에서 사용할 수 있는 잠정 문장은 다음과 같다.

> ScaleCirc를 비롯한 조합 분석은 회로 분해, 결과 재사용과 제한된 반례 전파를 제공한다. 본 연구는 퍼징으로 얻은 로컬 후보에 대해 계산된 호출 맥락의 witness 합성·수리를 연결하고, 특정 후보 값의 도달성과 해당 의미 위반 술어의 도달·배제를 분리해 판정한다. 현재 개발 사례에서 이 구분이 결과 해석을 바꾸는 것을 확인했으며, 선행 대비 일반적인 효용과 총비용은 추가 평가가 필요하다.

이는 기존 설명안의 넓은 아이디어를 구체화한 잠정 포지셔닝이며 새로운 범위 결정·평가 프로토콜이 아니다. 현재 고정 A 매핑은 W와 S+J 각각 L1 1항목이고, B는 부분 완료다. 또한 B의 배제 발생 350건 중 36건은 구성 입력 고정 반박이므로 입력 공간 전체 배제로 확대할 수 없다. [기존 기여 평가의 근거와 한계](contribution_assessment_2026-10-27_v1.md)를 유지한다.

## 전문 확보 후 결정할 비교

필요한 자료는 본문 13쪽의 저자판 또는 접근 가능한 PDF다. 확보하면 constrainedness 전파 규칙, 반례 전파의 명시적 보장, ZKAP 통합의 속성 범위, 기능 제거 실험, 691회로의 성공·실패 분모를 절·표 단위로 대조해야 한다.

실험 비교를 설계한다면 직접 연결, 계산된 내부 입력, 후보 값 배제와 술어 도달의 공존, 호출자에 의한 술어 배제의 네 조건이 유용하다. ScaleCirc의 반례 전파 실패만 세지 말고 원본 backend fallback의 최종 결과까지 포함해야 한다. 같은 속성에서 의미 있는 결과와 준비·분석·판정 총비용을 비교한다. 이것은 후속 설계 제안이며 이번에 도구 실행이나 새 후보 생성은 하지 않았다.

## 확인 버전과 변경 범위

다운로드 위치는 `/private/tmp/scalecirc-review-20261027/`다. 제3자 코드를 실행하지 않았다. 새 검토 문서와 계획 진행 표만 수정했고 기존 코드·고정 프로토콜·판정·실험은 바꾸지 않았다. 코드 변경이 없어 Cargo 검사는 새로 실행하지 않았다.

| 파일 | SHA-256 |
|---|---|
| appendix.pdf | `4eda44657cfb44de0ca697ca04da58cae58872cb65b8c2d8dd468a5808bcfdca` |
| utils_GA.py | `984fd4f21b8babe85340bff5e9f1a88fe9ebec7b924e0a09f5abc8615e0c8b82` |
| utils_Source_Code_Manager.py | `22b6fa3536d6025662ceb4103ebf83b428427c3abcdcd1922713d8a6132b2028` |
| utils_One_Template_Analysis.py | `07be4817d51fd6e7f2b433be052e93cfc898a43e07346fdfea40ac582dbba763` |
| utils_circom_manager.py | `f81ac11bc00845bf2174253a2f0e131b60ae773293b85b482591efa45ad58f42` |
