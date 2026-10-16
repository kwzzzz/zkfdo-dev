# 맥락 판정 기여 후보의 선행 연구 확인

담당: miiz. 기준일: 2026-10-07. 대상: (1) 깨진 가정 단위의 맥락 도달·배제 판정, (2) 수정 커밋 전·후와 leave-one-out으로 판정 정확도를 재는 방법. 원문을 직접 확인한 범위만 적는다. 망라적 검색이 아니다.

## 1. 깨진 가정 단위의 맥락 판정

| 선행 | 확인한 내용 | 우리와의 차이 |
|---|---|---|
| CCC-Check (Kolozyan et al., IEEE S&P 2026, [ePrint 2025/2120](https://eprint.iacr.org/2025/2120), [코드](https://github.com/ArmanKolozyan/CCC-Check), MIT) | 전체 회로의 값 범위를 추상 해석으로 건전하게 과대근사하고, `maxbit` 같은 tag로 적은 가정(예: LessThan(n) 입력이 n비트 이내)을 제약이 보장하지 못하면 경고한다. 과대근사라 거짓 양성이 있을 수 있고, 참·거짓 구분에는 SMT를 쓸 수 있다고 적었다. 실제 프로젝트에서 15건을 찾았고 그중 12건이 산술 넘침이다. Self 1건(버그 바운티, 수정됨), ZKP2P 1건(미수정) 포함 | 가정 위반 가능성을 전체 회로에서 판단한다는 점은 같다. CCC-Check는 "위반 가능할 수 있음"(may)을 경고하고 구체 witness를 주지 않는다. 우리는 퍼저 후보에서 출발해 도달이면 원본 제약을 두 검사기로 만족하는 entrypoint witness, 배제면 증명, 둘 다 아니면 unknown을 낸다(must + 증명 + 미판정) |
| Circomspect `unconstrained-less-than` ([Trail of Bits 2023](https://blog.trailofbits.com/2023/03/21/circomspect-static-analyzer-circom-more-passes/)) | LessThan 입력이 Num2Bits로 범위 검사되지 않으면 경고. 호출 지점 근처를 보는 구문 수준 검사이며 상수 입력 오탐 수정 이력이 있다 | 템플릿 경계를 넘는 맥락을 보지 않고 증거를 내지 않는다 |
| CIVER ([저장소](https://github.com/costa-group/circom_civer), [ZisK 사례](https://costa.fdi.ucm.es/web/news/CIVER_ZisK.html)) | 모듈 단위로 weak safety를 검증하고, 개발자가 적은 pre/postcondition·tag를 검사한다. 문제 컴포넌트와 그 인스턴스의 반례를 낸다 | 가정은 사람이 적은 명세에서 온다. 우리는 퍼저 오라클(zkFuzz의 LessThan 의미 조건)에서 가정을 얻고 entrypoint 맥락에서 판정한다 |
| Towards Fuzzing ZKP Circuits (Chaliasos et al., ISSTA'25 short, [PDF](https://www.doc.ic.ac.uk/~afd/papers/2025/FUZZING.pdf)) | 큰 회로는 하위 회로 퍼징이 유익할 수 있고, 다른 회로가 빠진 검사를 포함할 수 있으므로 결과를 전체 회로에서 검증해야 오탐을 막는다고 제안 | 아이디어 제안. 구현·판정 의미·측정이 없다 |
| UC-KLEE (Ramos & Engler, USENIX Security 2015, [PDF](https://www.usenix.org/system/files/conference/usenixsecurity15/sec15-paper-ramos.pdf)) | 호출자 없이 함수를 실행하면 전제가 빠져 거짓 양성이 생기고, 사람이 전제를 나중에 추가해 억제한다 | 일반 소프트웨어의 같은 문제. 우리는 ZK 회로에서 자동으로 판정한다 |
| FalseCrashReducer (Amusuo et al., 2025, [arXiv 2510.02185](https://arxiv.org/abs/2510.02185)) | OSS-Fuzz-Gen에서 LLM 에이전트가 호출자를 분석해 라이브러리 퍼징 크래시가 진입점에서 가능한지 판단 | 일반 소프트웨어, LLM 추론. 우리는 witness·증명 기반 |
| Jacobian Diagnostics (Singh, [ePrint 2026/1852](https://eprint.iacr.org/2026/1852)) | 제약 Jacobian으로 under-constrained 후보를 빠르게 찾지만 정직한 witness 근처만 보므로 확정은 못 하고, 적대적 witness 생성과 solver·증명 기반 확인과 결합하라고 제안 | 후보 탐지기. 확인 단계가 필요하다는 주장은 우리 방향과 맞는다 |
| Liezz (Watzinger et al., 2026, [arXiv 2608.30648](https://arxiv.org/abs/2608.30648)) | 두 실행의 witness를 이어 붙여 ZK DSL 툴체인(컴파일러)의 건전성 결함을 찾는다 | 대상이 툴체인이다. 회로 맥락 판정과 겹치지 않는다 |

**판단.** "조각 결과를 전체 회로 맥락에서 확인해야 한다"는 문제 제기와 "LessThan 입력 가정이 전체 회로에서 보장되는지 판단"하는 분석은 선행에 있다(ISSTA'25, CCC-Check). 우리가 주장할 수 있는 범위는 다음으로 좁힌다.

1. 퍼저가 낸 구체 후보에서 출발해, 깨진 가정을 퍼저 오라클에서 자동으로 얻고, **도달 witness(원본 제약을 독립된 두 검사기로 확인) / 배제 증명 / 미판정**의 세 값으로 판정한다. CCC-Check의 may 경고와 달리 도달 판정에는 거짓 양성이 없고, 배제는 증명이 있을 때만 낸다.
2. 후보 값 단위가 아니라 가정 단위로 판정해야 한다는 근거(L-05·L-06·L-07의 DFS·Clamp 사례)와 정답 대조 측정.
3. 위치 정보 없는 자동 분해와 결합해 큰 실제 회로에 적용하는 시스템.

CCC-Check와는 경쟁보다 보완 관계로 쓰는 것이 설득력 있다. 같은 대상에서 CCC-Check·Circomspect의 LessThan 경고를 우리 엔진으로 도달 확인·배제 증명·미판정으로 나누는 비교가 가능하다.

## 2. 정답 검증 방법(수정 커밋 전·후, leave-one-out)

| 선행 | 확인한 내용 |
|---|---|
| Magma (Hazimeh et al., SIGMETRICS 2021, [arXiv 2009.01120](https://arxiv.org/pdf/2009.01120)) | 실제 결함을 한 줄 패치로 켜고 끌 수 있게 하고, canary로 도달(reached)과 촉발(triggered)을 구분해 퍼저를 평가한다 |
| zkbugs, SoK(Kolozyan et al. 2026) | 결함 커밋과 수정 커밋을 함께 기록한 ZK 결함 데이터셋과 그 평가 |

**판단.** 결함·수정 쌍과 결함별 켜고 끄기는 표준 평가 방법이다. 우리 기여로 주장하지 않고 방법으로 인용한다. 같은 수정에 묶인 다른 결함을 되돌려 도달이 다른 결함에 기대는지 보는 `chained` 분류는 이번 확인 범위에서 같은 형태를 찾지 못했지만, 작은 방법론 세부로만 쓴다.

## 3. 평가와 B 결과 보고에 미치는 영향

- **기준 도구 추가 검토:** CCC-Check(MIT, 공개)와 Circomspect를 A·B 대상에 돌려 LessThan 계열 경고를 얻고, 우리 엔진의 판정과 대조하는 비교가 기여를 가장 분명하게 보여 준다. N5 v1에는 없는 항목이므로 넣으려면 실행 전에 새 버전 부록으로 고정해야 한다.
- **B 새 발견 주장 전 대조:** CCC-Check가 공개한 결함(Self 1, ZKP2P 1, TikTok TAV 7, Microsoft Crescent 4, co-snarks 등), zkFuzz 논문의 zero-day 목록, 각 저장소 이슈 트래커와 겹치는지 확인한 뒤에만 "새 발견"으로 부른다.

## 4. CCC-Check 원문 확인 (로컬 사본 `runs/literature/ccc-check-2025-2120.txt`)

| 질문 | 원문에서 확인한 답 | 우리와의 관계 |
|---|---|---|
| LessThan 입력 가정은 자동으로 검사하나 | 아니다. 넘침은 신호에 `maxbit(n)` tag를 붙여야 잡는다. 표시 없이 자동으로 보는 것은 0 나눗셈과 배열 범위뿐이다(§4). 실제 프로젝트 평가(RQ4)는 "보안 감사자처럼" 여섯 프로젝트에 **사람이 직접 tag를 붙여** 수행했다 | 우리는 가정을 퍼저 오라클(zkFuzz의 LessThan 의미 조건)에서 자동으로 얻는다. 사람이 tag를 붙이지 않는다 |
| 맥락 오탐(zk-email처럼 호출자가 Num2Bits로 막는 경우) | 값 추론이 범위를 건전하게 과대근사하므로, tag가 있으면 호출자의 범위 검사가 반영되어 경고하지 않을 수 있다. 과대근사 때문에 범위를 넓게 잡으면 거짓 경고가 날 수 있다고 명시(§4.3) | 배제 판단은 비슷하게 건전하다. 우리 배제도 비트 분해 범위 추론을 쓰며 이 부분은 선행(CCC-Check)으로 인용한다 |
| 실제로 뚫리는 경우(Banyan) | 경고만 낸다. 위반을 보여 주는 구체 입력·witness는 내지 않는다. 참·거짓 구분에는 SMT를 쓸 수 있다고만 적었다 | 우리는 원본 제약을 두 검사기로 만족하는 entrypoint witness를 낸다. 도달 판정에 거짓 양성이 없다 |
| 출력이 달라지는 TCCT 위반(Subtract 승수, IntDiv `out <-- quot`) | 형식 모델(DCM)은 넓게 정의하지만, 도구의 탐지는 tag 위반과 암묵 검사(0 나눗셈·배열 범위) 중심이다. 일반적인 비결정성 탐지는 CIVER·Picus 영역으로 둔다 | 우리는 퍼징 후보로 이 유형도 entrypoint까지 확인한다 |

- CCC-Check가 Self·ZKP2P에 보고한 결함: Self issue #578·PR #579(Sha256Bytes 범위 검사 누락), ZKP2P issue #428·PR #429(원문 표 8).
- S&P 메타리뷰의 채택 이유: 중요한 문제, 실용적이고 빠른 도구, 실제 프로그램에서 취약점 발견. 우리에게도 같은 기준이 적용될 것이다.

**tag 차이에 대한 정정(2026-10-07).** "사람이 tag를 붙이느냐 자동이냐"는 큰 차이가 아니다. CCC-Check는 LessThan 템플릿 입력에 `maxbit` tag를 한 번 붙여 그 템플릿의 모든 사용을 검사한다(부록 Listing 2). 우리가 오라클에서 자동으로 얻는 가정도 zkFuzz에 내장된 LessThan 의미 조건 하나뿐이라 범위가 같다. 프로젝트 고유 가정은 명세 없이는 어느 쪽도 자동으로 얻지 못한다. 따라서 이 차이를 기여로 내세우지 않는다.

**실제 차이.** (1) 명세 없는 TCCT 오라클로 출력이 틀리는 결함까지 찾는 퍼징을, 위치 정보 없는 자동 분해로 큰 실제 회로에 적용한다(오라클 자체는 zkFuzz). (2) 분해로 생긴 결과를 도달 witness·배제 증명·미판정으로 판정한다(경고가 아니라 증거). 주 비교 상대는 통째 퍼징(zkFuzz W)이며 N5 RQ1이 그대로 맞다. LessThan 넘침 유형에서 CCC-Check와 겹치는 부분은 보완 관계로 쓴다.

**30초 설명(수정):** zkFuzz 같은 퍼저는 명세 없이 결함을 찾지만 큰 실제 회로에서는 시간 안에 돌지 못한다. 저희는 회로를 결함 위치 정보 없이 자동으로 쪼개 퍼징하고, 쪼개서 생긴 결과가 원래 회로에서도 성립하는지 실제로 통과하는 입력(도달), 증명(배제), 미판정으로 판정한다. CCC-Check 같은 정적 분석은 사람이 적은 가정을 기준으로 위반 가능성을 경고하는 반면, 저희는 명세 없는 오라클로 찾은 후보에 증거를 붙인다는 점에서 보완적이다.
