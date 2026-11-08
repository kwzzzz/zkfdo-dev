# 관련 연구 원문 대조: 분할, 호출 맥락, 원본 검증

2026-10-29. 논문·저자 원문·공식 도구 문서에서 확인한 **기능의 범위**를 비교한다. 선행 도구를 실행한 성능 비교는 아니다. 아래 11개 행은 선정한 연구의 대조표이며, 분야 전체에 대한 최초성 증명이 아니다. A의 기존 관측은 개발 근거로만 인용한다.

## 읽는 기준

- **분할·단위 구성:** 별도로 분석할 부품·함수·harness를 실제로 구성하는가. 단순한 변이 위치 선택과 구분한다.
- **호출 맥락:** 호출 위치의 정적 관계를 보는 것, 실제 사용 예를 harness에 보존하는 것, 후보가 발생하는 상위 입력을 찾는 것은 서로 다른 기능이다.
- **원본 검증:** 입력으로 받은 분석 대상 전체의 모델 검증, 생성 harness에서의 라이브러리 실행, 원래 entrypoint까지의 도달성 검증을 구분한다. 도구에 조각만 주었다면 그 조각 검증을 원래 응용 전체 검증으로 부르지 않는다.
- **미확인**은 해당 원문의 설명에서 확인하지 못했다는 뜻이다. 기능이 절대 없거나 구현할 수 없다는 뜻이 아니다. 별도 snarkjs 호출이 없다는 이유로 형식 검증 결과를 무효로 취급하지 않는다.

일반 소프트웨어의 *under-constrained symbolic execution*은 실행 앞부분·호출자 전제조건을 생략한 분석을 뜻한다. ZK의 *under-constrained circuit*은 회로 자체의 제약 부족을 뜻한다. 격리 분석의 가짜 후보와 실제 회로 결함을 연결해 논의할 수 있지만, 두 용어를 동일한 결함 정의로 사용하지 않는다.

## ZK 회로 연구

| 연구·확인 판본 | 분할·단위 구성 | 호출 맥락 처리 | 원본 검증의 범위 | 원문 위치 |
|---|---|---|---|---|
| **zkFuzz**, arXiv v3 | 기본 알고리즘은 제출된 프로그램 P·제약 C를 대상으로 계산을 변이한다. 자동 조각 추출은 기술되지 않으며 slicing·부분 실행은 향후 개선으로 제시한다. | 분리한 후보를 원래 부모 입력으로 역합성하는 단계는 기본 알고리즘에서 확인되지 않는다. | 변형 trace의 **대상 C 만족**과 정상 P의 출력·중단을 비교하는 TCCT. 전체 main을 주면 전체 대상 검사이며 조각을 주면 조각 범위다. | [§III-B, §IV-A Algorithm 1, §VIII](https://arxiv.org/html/2504.11961v3) |
| **zkFuzz++**, 같은 v3 | 정적 target selection으로 변이·입력 생성 지점을 고른다. **독립 wrapper 생성과 다르다.** | 제한된 식 풀이를 이용한 입력 유도는 있다. 이를 호출자 관계를 복원하는 일반 절차라고 볼 근거는 없다. | zkFuzz의 TCCT를 사용한다. ++를 별개의 원본 검증 계약으로 해석하지 않는다. | [§V-B, Table III](https://arxiv.org/html/2504.11961v3#S5.SS2) |
| **ScaleCirc**, ASE 2025 | 템플릿·구체 인자별 재귀 분석, 결과 재사용, 자식 치환과 backend 후처리. 안전성 검증과 반례 전파 모두 다룬다. | Eq.17은 **부모 입력에 직접 연결된 자식 입력**을 조건으로 자식 반례 쌍을 부모로 올린다. 이 경로 밖에는 backend가 남는다. | 동일 입력의 유효 witness 쌍과 부모 출력 차이로 UNDER를 확인한다. 안전 자식 제거로 만든 과대근사가 unsafe이면 원래 부분 영역을 재검사한다. 별도의 byte-identical 원본 R1CS/snarkjs 재실행은 이 전파 설명만으로 확인되지 않는다. | [논문·DOI](https://doi.org/10.1109/ASE63991.2025.00124), Algorithm 1 pp.1466–1467, §III-D Eq.16–18 pp.1468–1469, §V-A p.1474. [상세 원문 대조](scalecirc_primary_comparison_2026-10-28.md) |
| **Picus / QED²**, PLDI 2023 | **분할 반례 구성 있음.** 모델 탐색이 오래 걸리면 compiler debug info로 하위 회로들을 구성한다. | 누적 모델 M을 조건으로 하위 회로를 순차 질의하여 부분 모델을 합친다. 정확한 S 후보를 특정 호출 위치로 올리는 계약과 동일하다고 단정할 수는 없다. | §5.2는 입력을 공유하는 회로 두 사본의 유일성을 질의한다. §6의 분할 반례 구성은 **완전한 모델일 때 refuted**, 불완전하면 unknown이다. 별도 snarkjs 재검사는 해당 설명에서 미확인이다. | [§5.2 p.168:14, §6 Counterexample Construction p.168:15](https://www.cs.utexas.edu/~isil/qed.pdf). [Picus=QED² 공식 설명](https://github.com/Veridise/Picus) |
| **Circomspect**, 공식 도구 문서 | 함수·템플릿 정적 분석 패스. 퍼징용 독립 harness 추출은 해당 문서에서 미확인이다. | 인스턴스의 미사용 출력, LessThan 입력의 Num2Bits 범위 제약 등 **호출 맥락 일부를 검사**한다. 구체적인 최상위 입력 합성과는 다르다. | 자동 산출물은 정적 경고다. 모든 경고의 전체 원본 witness를 만들고 TCCT를 재실행하는 경로는 문서에 기술되지 않는다. | [Analysis Passes](https://github.com/trailofbits/circomspect/blob/main/doc/analysis_passes.md): Unused output signal, Unconstrained less-than, Unconstrained division. 확인일 2026-10-29 |
| **ZKAP**, USENIX Security 2024 | CDG에서 부품의 입력→출력 data/constraint 관계를 요약한다. 독립 퍼징 wrapper 추출과는 다르다. | USCI는 부품 밖 신호의 제약 의존성을, USCO는 호출 위치의 출력 제약을 분석한다. **맥락 분석 있음**. 과대근사·휴리스틱을 쓰며 정밀한 원본 입력 합성과 구분된다. | 자동 결과는 패턴 경고다. 평가의 수동 검토·실제 proof 예시는 모든 경고에 대한 자동 witness 복원 절차를 뜻하지 않는다. | [§4.2 pp.7–8/Fig.9, §4.3 pp.8–9, §4.4 p.10, §5.4 p.13, §7 p.15](https://www.cs.utexas.edu/~isil/zkap.pdf) |

zkFuzz/++는 **2026-05-23의 arXiv 2504.11961v3**를 기준으로 읽었다. 우리 W의 고정 실행 파일·설정이 이 판본의 ++ 구성과 같다는 감사는 이번에 하지 않았다. 따라서 기존 W 비교를 곧바로 “최신 zkFuzz++ 대비 우위”로 옮길 수 없다.

ScaleCirc는 사용자가 보유한 [IEEE PDF](</Users/miiz/Library/Mobile Documents/com~apple~CloudDocs/Desktop/TalkFile_ScaleCirc_Scaling_the_Analysis_over_Circom_Circuits.pdf>)를 읽었다. SHA-256은 `0f51d5857d1d7de1ef70748ecf5db16da0b1bf8fd37c237e5cb1413835d5bf70`이다. 표의 ScaleCirc·Picus 페이지는 인쇄 페이지, ZKAP은 저자 PDF 페이지다. Circomspect는 학술논문 대신 공식 문서를 근거로 썼다.

## 일반 소프트웨어: 격리 분석과 harness 생성

| 연구·확인 판본 | 분할·단위 구성 | 호출 맥락 처리 | 원본 검증의 범위 | 원문 위치 |
|---|---|---|---|---|
| **UC-KLEE**, USENIX Security 2015 | C/C++ 함수를 격리해 symbolic execution하며 필요한 입력 메모리를 지연 생성한다. | 빠진 호출자 전제조건의 오탐 문제를 명시하고 사용자 불변식·호출 annotation 및 휴리스틱으로 제한한다. | 개별 함수 분석·패치 비교. 각 오류를 원래 main 입력으로 복원하여 재실행하는 필수 절차는 해당 설명에서 미확인이다. | [Under-Constrained Symbolic Execution: Correctness Checking for Real Code](https://www.usenix.org/system/files/conference/usenixsecurity15/sec15-paper-ramos.pdf), §3.2.5 및 인쇄 pp.55–57, Fig.11 |
| **MACKE**, ASE 2016 | 함수를 분리한 unit test와 KLEE 분석을 구성한다. 분석 중 내부 호출도 실행한다. | 오류 stack 연결 또는 구체 오류 입력의 assertion 요약으로 caller를 targeted symbolic execution한다. main까지 도달성을 조사한다. | **원래 호출 관계를 통한 도달성 조사 있음.** timeout으로 연결하지 못했다고 불가능으로 판정할 수 없다고 명시한다. 별도 native 전체 replay의 일괄 의무화는 미확인이다. | [MACKE: Compositional Analysis of Low-Level Vulnerabilities with Symbolic Execution](https://www.researchgate.net/publication/305641321_MACKE_Compositional_Analysis_of_Low-Level_Vulnerabilities_with_Symbolic_Execution), 저자 업로드 원문 §2.2.1–2.2.2. [DOI](https://doi.org/10.1145/2970276.2970281), pp.780–785 |
| **Wildfire**, arXiv 1903.02981v2, 2019 | 자동 driver를 만들어 **격리된 함수를 퍼징**한다. | 오류 입력을 요약하고 stack matching·targeted symbolic execution으로 caller→interface/API 도달성을 확인한다. **분할 퍼징+맥락 복원의 직접 선행**이다. | 격리 함수용 실행에 crash replay가 있고, 별도로 상위 호출 도달성을 조사한다. main까지 확인된 결과와 중간 함수 chain을 구분한다. 모든 보고가 원래 main 검증 성공은 아니다. | [Compositional Fuzzing Aided by Targeted Symbolic Execution](https://arxiv.org/pdf/1903.02981v2), §4.4–4.6 PDF pp.10–14, §6.6.2 p.26, §7 p.27 |
| **FuzzGen**, USENIX Security 2020 | 실제 consumer의 API 사용을 추출하고 A²DG로 harness를 생성한다. | 호출 순서·인자 의존성·범위를 추론한다. 여러 consumer의 사용을 결합하므로 유효하지 않은 API 경로가 생길 수 있다. | 생성 harness로 실제 라이브러리를 실행한다. API 사용의 타당성 검토와 **기존 특정 consumer main에서의 입력 도달성 증명**은 다르다. 후자의 일괄 자동화는 해당 설명에서 미확인이다. | [FuzzGen: Automatic Fuzzer Generation](https://www.usenix.org/system/files/sec20-ispoglou.pdf), §4.1–4.3 pp.2275–2278, §7 False positives p.2283 |
| **FUDGE**, ESEC/FSE 2019 | 기존 client AST의 data/control 의존성을 추출해 driver와 build 파일을 만든다. | 사용 예의 일부 맥락을 보존한다. 범위 밖 값은 placeholder와 재작성으로 처리하므로 원래 실행 맥락과 동일하지 않다. | 컴파일·짧은 fuzzing·coverage 등으로 driver 품질을 평가하고 개발자가 선택한다. 원래 application main으로 각 반례를 복원하는 절차는 해당 방법에 기술되지 않는다. | [FUDGE: Fuzz Driver Generation at Scale](https://storage.googleapis.com/gweb-research2023-media/pubtools/5118.pdf), §3.1 Algorithm 1, §3.2–3.3, PDF pp.4–6. [저자 기관 페이지](https://research.google/pubs/fudge-fuzz-driver-generation-at-scale/) |

MACKE는 **ASE 2016**으로 표기한다. Wildfire는 확인한 저자 preprint 판본을 기준으로 하며 최종 출판 연도를 추정하지 않았다. FUDGE는 기관 PDF 전문을 확보해 §3을 확인했다. MACKE 대학 PDF 링크는 조회 오류가 있어 저자 업로드 원문을 사용했다.

## 우리 주장에 적용할 반론과 남는 방향

| 넓게 쓰면 반박되는 주장 | 직접 대조 근거 | 남길 수 있는 더 정확한 주장·필요한 증거 |
|---|---|---|
| “처음으로 회로를 나누고 전체 반례를 만든다.” | Picus의 분할 모델 구성, ScaleCirc의 재귀 분석·부모 반례 전파 | 실제 인스턴스에서 퍼징 단위를 구성하고, 어떤 후보를 어떤 원본 입력 계약 아래 수용하는지 명시한다. 자동 준비 성공률과 원본 검증 수율을 측정한다. |
| “분할 퍼징 뒤 맥락을 복원하는 결합이 새롭다.” | Wildfire·MACKE | Circom에서는 정상 witness 계산으로 만들 수 있는 값과 제약을 만족하는 값이 다를 수 있다. 이 차이를 처리하는 구체 알고리즘과 비용 효과를 보여야 한다. **이 의미 차이 자체도 zkFuzz에 이미 있다.** |
| “정적 도구는 맥락을 보지 않는다.” | ZKAP·Circomspect | 그래프·패턴 경고와 구체 원본 witness에 의한 확인은 다르다. 그 차이를 판정 정확도·검증 성공률로 평가한다. |
| “계산된 중간 입력을 다루므로 ScaleCirc보다 강하다.” | Eq.17의 빠른 경로와 전체 backend는 다르다. | 빠른 전파가 적용되지 않는 사례를 구분하되 **backend를 포함한 전체 도구**와 같은 속성·입력 계약·총비용으로 비교한다. |
| “Rust와 snarkjs를 모두 통과하므로 새로운 검증 방법이다.” | 선행의 형식 모델·도달성 증명도 유효한 검증이다. | 두 검사기는 구현 신뢰성과 재현 가능한 증거 계약을 뒷받침한다. 그것만을 새 알고리즘으로 세우지 않는다. |

긍정적인 근거는 **목표가 여전히 실제 문제라는 점**이다. zkFuzz §VIII는 큰 대상의 실행 비용과 slicing·부분 실행을 개선 과제로 남긴다. 우리에게는 [자동 조각 준비](n7_a_feasibility_results_2026-10-29.md)와 [계산된 부품 입력에서 원본 동일 입력 반례 쌍까지 연결한 A 사례](n5_next_gate_2026-10-28.md)가 있다. 이들은 방법의 작동 근거이며, 기존 연구를 조사했다고 없어지는 자산이 아니다. 다만 [총비용 감사](n7_cost_cause_audit_2026-10-28.md)가 지적한 미계측 비용 때문에 일반적인 효율 우위는 아직 결론낼 수 없다.

교수님께 설명할 **현재의 기여 후보**는 다음 정도가 정확하다.

> 큰 Circom 원본에서 구체 인스턴스의 퍼징 단위를 자동으로 구성하고, 조각 후보를 호출 위치의 입력·제약에 다시 연결해 원본에서 확인된 반례만 수용하는 시스템을 구현했다. 분할과 맥락 복원 자체는 선행에 있다. 연구의 남은 핵심은 이 구성이 준비·컴파일·탐색·J·원본 검증을 포함한 같은 총비용에서 더 많은 고유 원인을 확인하거나 첫 확인 시간을 줄이는지를 입증하는 것이다.

다음 평가에서 분리할 질문은 세 가지다. **①** W 대 S+J는 같은 TCCT와 전체 비용으로 비교한다. **②** ScaleCirc/Picus와는 공통인 동일 입력·출력 비결정성을 비교하고, 정상 계산 중단을 같은 성과 칸에 섞지 않는다. **③** 조각화로 늘어난 후보 수, 원본 검증을 통과한 수, 반사실 대조로 구분한 고유 원인 수를 별도로 낸다. A에서 운영과 가설을 점검한 뒤 독립 평가는 고정 N5 규칙을 따른다. 이번 문서는 새 실행을 승인·시작하거나 기존 프로토콜을 바꾸지 않는다.

## 확인한 것과 남은 것

**확인한 것:** 표에 인용한 원문의 방법·검증 범위. Picus의 분할 반례 구성, ZKAP·Circomspect의 부분 맥락 분석, MACKE·Wildfire의 호출자 도달성 검사는 직접 선행이다. 기존 기록상 자동 준비와 A 원본 양성 사례는 존재한다. 이번 작업에서는 코드·판정·고정 기록을 바꾸거나 퍼징·J·대형 비교를 실행하지 않았다.

**추정한 것:** 우리 구성의 같은 총비용 이득, ScaleCirc/Picus 전체보다 높은 원본 검증 수율, 독립 자료로의 일반화. 표만으로 최초성·성능 우위·학회 등급을 확정할 수 없다. 이후 논문 원고에는 현재 사용한 판본과 실제 비교 실행 파일·설정을 맞춰야 한다.
