# 문헌·평가 방법론 독립 검토 (N2, 2026-10-01)

**상태: 완료 (2026-10-01).** [현재 계획](../../docs/plan_revision_2026-10-01.md)의 N2다. 선행연구 원문과 [문제 정의](../../docs/problem_statement.md)·[평가 설계](../../docs/evaluation_plan_2026-10-01.md)를 대조해, 현재 방향이 선행연구와 평가 논리 앞에서 방어 가능한지 검토했다.

- 퍼징, 컴파일, 후보 재현, 원시 witness 열람, 도구 구현은 하지 않았다. 코드와 기존 판정은 바꾸지 않았다.
- 계획·평가 설계·문제 정의 본문은 수정하지 않았다. 수정 제안은 이 문서에만 둔다. 반영 위치는 N3 결정 기록이나 N5 프로토콜이다.
- 병렬로 진행 중인 N1(공개 자료 감사)의 파일과 수치는 보지 않았고 쓰지 않았다. 대화에서 나온 교차표(10/1/3/42 등)를 이 문서의 근거로 쓰지 않는다. 아래 SoK 수치는 논문 본문과 그림에서 직접 읽은 것이다.

## 0. 결론 요약

현재 방향은 선행연구 앞에서 **방어할 수 있다.** 단, 범위가 좁은 주장으로 한정할 때다. 분해 퍼징, 부분 결과의 전체 회로 재확인, Circom 회로의 컴포넌트 단위 분석, 컴파일 재사용, 경고의 맥락 실현 가능성 문제는 모두 아이디어로서 선행이 있다(2절). 남는 것은 세 가지다. (1) 결함 위치를 모르는 실제 entrypoint에서 자동 구성의 적용 범위와 비용을 측정하는 일, (2) TCCT 퍼징 결과가 컴포넌트에서 entrypoint로 옮겨질 때의 의미를 정확히 정하는 일, (3) 그 의미에 맞춰 건전한 맥락 배제를 구현하고 미판정까지 측정하는 일이다. 계획 문서들은 이미 이 경계를 대부분 정확히 적고 있다.

그대로 진행하면 결과 해석이 흔들릴 수 있는 지점은 다섯 가지다(자세한 내용은 5.1절).

1. **비교 수준과 구조적 비대칭.** zkFuzz는 첫 반례에서 실행을 끝낸다. 통째 실행은 실행당 반례가 최대 1개이고 분할 실행은 조각당 1개다. 따라서 "같은 예산의 고유 원인 수"는 탐지 능력과 무관하게 분할에 유리하다. 또 통째 실행의 반례는 처음부터 entrypoint 제약 전체를 만족하지만 분할 반례는 컴포넌트 수준이다. 주 지표의 수준과 분석 단위를 먼저 정해야 한다(M1·M2).
2. **무엇을 배제하는가.** 특정 반례 하나를 맥락에서 배제하는 것(점 배제)과 그 경고나 원인을 맥락상 무관하다고 판정하는 것(원인 배제)은 다른 주장이다. 점 배제로 경고를 지우거나 "오탐"이라 부르면, 실제로 실현 가능한 같은 원인의 다른 반례를 숨길 수 있다(M3).
3. **배제 근거의 출처.** 배제는 실제로 컴파일되어 증명에 쓰이는 제약만으로 해야 한다. witness 계산 코드, `assert`, signal tag, 정상 실행에서 본 값은 악의적 prover를 막지 못한다. 고정한 컴파일러 판·옵션의 R1CS와 신호 대응이 근거가 되어야 한다(M3).
4. **입력 전제와 abort형 결함.** zkFuzz가 찾은 원인의 55.2%는 계산 abort형이다. 대표적인 예는 제약 없이 `assert`로만 지킨 조건이다. `assert`나 문서화된 가정을 컴포넌트 입력 전제로 볼지 결함으로 볼지에 따라, 같은 후보가 컴포넌트 확인이 되기도 하고 안 되기도 한다. 이 규칙은 실행 전에 고정해야 한다(M4).
5. **원인 귀속과 오라클 범위의 사전 규칙.** 같은 원인 판정 규칙이 없으면 "양쪽 동일 검토"를 검증할 수 없다. 미탐을 보고 "탐지 범위 밖"으로 분류하면 순환 논리가 된다(M5·M6).

용어는 "최초"를 쓰지 말고 탐색 범위를 밝힌 "알지 못한다"로 바꾼다. "무명세(명세 불필요)"는 TCCT 오라클과 점 배제에만 쓸 수 있다. "자동 확인"은 "고정 기준의 자동 재검사"로, "프로젝트 결함"은 entrypoint와 그 역할을 명시한 수준 표현으로 바꾼다(2.2절, M7).

## 1. 읽은 범위

### 1.1 우선 대조 문헌 8편

사본은 모두 ignored `runs/literature/`에 두었고 SHA-256은 아래와 같다. "전문"은 본문을 처음부터 끝까지 읽었다는 뜻이다. 일부만 읽은 경우 읽은 절을 적었다.

| 문헌 | 판·출처 | 사본·SHA-256 | 읽은 범위 | 접근 |
|---|---|---|---|---|
| zkFuzz (Takahashi et al., IEEE S&P 2026 채택) | arXiv [2504.11961v3](https://arxiv.org/abs/2504.11961v3), 2026-05-23 | `zkfuzz-2504.11961v3.pdf` `be520f0f54d8b496a8eb15c1eff7928f59364f7a4264660cad435d6b529ff411` | §1–§9 전문, 표 1–5·9, 그림 3–4, 부록 B·C 전문, 부록 D 앞부분, 부록 E 표. 부록 A(복잡도 증명)는 읽지 않음 | 전문 |
| 〃 이전 판 | arXiv 2504.11961v2, 2025-10-10 (2026-09-30에 받은 사본) | `06e68ed75260c8fc2feb89c9500cfbb3f7033cd2d8670c86e192494f1b9fb60d` | §8의 slicing 문장과 452·85·zero false positive 문구만 v3와 대조. 같은 문장이 있음 | 부분 대조 |
| SoK: ZKP Security Tools and Verification (Kolozyan, Sorger, Hicks, Chaliasos) | arXiv [2607.23752v1](https://arxiv.org/abs/2607.23752v1), 2026-07-26 | `sok-2607.23752v1.pdf` `a264c6d7a9d1cda92f36f3c915f303d3d0318efdd66835ce26d03b9e95067a00` (기존 `sok-2607.23752.pdf`와 같은 바이트) | 초록, §I–§V 전문, 그림 2와 표 II–IV(텍스트 추출이 깨져 5쪽을 이미지로 렌더링해 판독), §VII 채택 장벽 부분, §VIII–§X. §VI(zkVM 형식 검증)은 훑어봄 | 전문(§VI 제외) |
| Towards Fuzzing ZKP Circuits (Chaliasos, Al-Fath, Donaldson) | arXiv [2504.14881v2](https://arxiv.org/abs/2504.14881v2), ISSTA Companion '25 | `towards-fuzzing-2504.14881v2.pdf` `408a432b1572d6bb13d591b6b784b3818e03c16d302d51d7879da3bb55baab21` | §1–§6 전문, 표 1–2, 그림 4–6 | 전문 |
| Wildfire: Compositional Fuzzing Aided by Targeted Symbolic Execution (Ognawala et al.) | arXiv [1903.02981v2](https://arxiv.org/abs/1903.02981v2), 2019-10-11 저자 preprint. 출판 venue는 PDF에 없음 | `wildfire-1903.02981v2.pdf` `5b4761be6b51daa11291fce372f49ea03e7b93e1f34c0e3b21af95c0b595f0ab` | §1–§8 본문 전문. 표 1–3과 그림 10–13의 수치 셀은 추출이 깨져 판독하지 않음(본문 서술만 사용) | 전문(표 수치 제외) |
| Picus/QED² (Pailoor et al., PACMPL 7 PLDI, Article 168) | [Veridise 공개 PDF](https://veridise.com/wp-content/uploads/2025/01/Automated-Detection-of-Underconstrained-Circuits-for-Zero-Knowledge-Proofs.pdf) | `picus-veridise.pdf` `2468c7d10aab02be621887d123a3c6d8768a23515cb99b5100a454b3ba78eadc` (기존 `picus-pldi23.pdf`와 같은 바이트) | §4, §5 도입과 Algorithm 1, §6 전문, §7 설정·지표·주요 결과, §8 전문. §1–§3은 훑어봄. §5.1 규칙 세부와 §9는 읽지 않음 | 부분 정독 |
| CCC-Check (Kolozyan et al., SoK 참고문헌 [15]에 따르면 IEEE S&P 2026) | IACR ePrint [2025/2120](https://eprint.iacr.org/2025/2120) | `ccc-check-2025-2120.pdf` `654f286d9d489bd9981b8222a252f97bcc80d70f083efc607b37e7974bfc19f9` (기존 `ccc-check.pdf`와 같은 바이트) | 초록, §2–§3의 Definition 2와 SCV 분류 일부, §4.2–§4.3 전문, §5.2–§5.4 전문. 부록은 읽지 않음 | 부분 정독 |
| ZEQUAL: Automated Verification of Consistency in ZKP Circuits (Stephens, Pailoor, Dillig) | [UT Austin 공개 PDF](https://www.cs.utexas.edu/~isil/zequal.pdf). 서지는 SoK 참고문헌 [19](CAV 2025, LNCS 15931)에서 확인 | `zequal.pdf` `bbed45be555e27e66d38102fd64fa180e672da7f2d05d5591347f8ba0a82b3b4` | §1 기여, §3 Definition 1–3, §5.2 일부, §6 마지막 문단(하위 회로 가정), §7 전문. 확장판(ePrint)은 읽지 않음 | 부분 정독 |
| CIVER: Scalable Verification of Zero-Knowledge Protocols (Isabel, Rodríguez-Núñez, Rubio, IEEE S&P 2024) | [IEEE Xplore 10646792](https://ieeexplore.ieee.org/document/10646792/) | 논문 사본 없음 | **본문을 읽지 못했다.** IEEE 페이지 내용을 받지 못했고 공개 사본을 찾지 못했다. 공식 저장소 [costa-group/circom_civer](https://github.com/costa-group/circom_civer) commit `af7d4ed0325e6f7743d8a1ac0e415d0c69b8aae8`의 README(`civer-README-af7d4ed.md`, `12b6ec2996c855e11f0617364b3c044b420477825d3308d71be8b7230bc13d61`)와 SoK §IV·표 II·III, zkFuzz §7의 2차 서술만 읽음. [후속 보고](https://costa.fdi.ucm.es/web/news/CIVER_ZisK.html)는 읽지 않음 | 2차 자료만 |

CIVER에 관한 이 문서의 서술은 README와 다른 논문의 설명에 근거한다. 원 논문의 평가 결과나 보장 범위로 인용하지 않는다.

### 1.2 보조 문헌

| 문헌 | 판·사본 SHA-256 | 읽은 범위 |
|---|---|---|
| FuzzSlice (Murali et al., ICSE '24) | arXiv 2402.01923v1, `fuzzslice.pdf` `62e523de022c60735fce23f2551362110c570ee29c8a37b76c7f37f17c501f7c` | 초록, §1, §2 동기 예, §3의 D3와 네 가지 분류 |
| LIEZZ: Lie to Me (Watzinger, Wüstholz) | arXiv 2608.30648v1, `liezz.pdf` `3ff66ac3438874900a96c3372ec83e5141e9e96942af316ad892b792d8f3383e` | 초록만 |
| zkCraft (Fu et al.) | arXiv 2602.00667v6, `zkcraft.pdf` `69afeaa4ca25c40cb66911b95f3c01c5ea29e109d95b1fb6e3a869ae3ae77cc6` | 초록, 그림 1 설명, §3 도입만 |
| Fuzzing at Scale (Nikolić, Jain) / SoK: Where to Fuzz? (Weissberg et al.) | arXiv 2406.18058v2 / 2502.08341v1 | 초록만 |

2026-10-01에 ZK 회로의 자동 부분 회로·컴포넌트 퍼징과 호출 맥락 오탐을 다룬 2025–2026년 연구를 웹에서 두 번 검색했다. 위 목록 밖의 직접 대응 연구는 찾지 못했다. 검색은 망라적이지 않으므로 이 결과를 "선행 없음"의 근거로 쓰지 않는다.

### 1.3 저장소 자료

AGENTS.md, [START_HERE](../START_HERE.md), 10-01 계획·평가 설계·문제 정의·작업 프롬프트, [P2 보고서](../dev-rq1-pilot-2026-09-29/README.md), [09-27 계획](../../docs/plan_revision_2026-09-27.md) §2–§6, [후보 검토 설계](../../docs/candidate_review_design.md)의 §1·§4·§7 개요, [held-out 선정 기준](../../docs/heldout_selection_rubric.md)의 조사 규칙 부분을 읽었다. 고정 zkFuzz 사본(`.external/zkFuzz`, commit `072bf1fbbd1c9ecad58d4f6d2204c3b96e7fec17`)의 `src/mutator/mutation_test.rs`에서 탐색 종료 조건만 확인했다. 실행은 하지 않았다.

## 2. 주장할 수 있는 것과 없는 것

### 2.1 선행 아이디어, 실제 구현 범위, 우리에게 남은 검증 의무

| 선행 | 이미 있는 아이디어 | 실제 구현·평가 범위 | 우리에게 남은 의무 |
|---|---|---|---|
| zkFuzz | TCCT 오라클. 큰 대상을 잘라 부분 실행하면 나아질 수 있다(§8, 한 문장). 템플릿 결함은 한 번만 센다(§6.1) | 452개 test suite에서 TP/FP를 수동 판정했다(test suite 단위). 첫 위반에서 탐색을 끝낸다(§1, Algorithm 1). 계산 로직만의 결함은 범위 밖이다(§2.2) | slicing 아이디어는 우리 것이 아니다. "zero false positives"는 그 benchmark 단위와 TCCT 정의에서의 결과다. 컴포넌트 결과가 entrypoint 맥락에서도 참이라는 근거가 되지 않는다 |
| SoK | 격리 모드와 프로젝트 모드의 격차. 큰 코드베이스에서 시간 초과와 오류가 늘어난다. 도구는 "focused code-fragment analysis"에 더 맞는다. 향후 과제로 component composition과 interface invariant를 든다(§VIII) | 사람이 결함 위치를 알고 만든 최소 wrapper(격리)와 원본 코드베이스(프로젝트)를 600초로 비교했다. TP는 ground truth 위치·주석과 대조했고 애매하면 두 저자가 수동 확인했다. 오탐은 측정하지 않았다 | 격차 자체는 재현이다. 자동 구성은 결함 위치를 쓰지 않는다는 점이 SoK 격리 모드와 다르다. SoK가 남긴 오탐 분석은 도구 경고 전반에 관한 것이다. 우리 측정은 한 도구에서 분해가 만든 후보만 다룬다. 그 공백을 채운다고 넓게 말하지 않는다 |
| Towards Fuzzing ZKP Circuits | 큰 회로는 부분 회로 단위로 퍼징하되, 부분 회로 결과는 전체 회로에서 검증해야 오탐을 막는다(§3.2) | 구현한 것은 zk-regex 차등 퍼저뿐이다. witness를 퍼징하지 않아 soundness 버그는 찾지 않았다(§4). 부분 회로 퍼징은 구현하지 않았다 | 제안을 명시적으로 인용한다. 우리 몫은 구현, 측정, 그리고 "전체 회로에서 검증"의 의미를 정밀하게 정하는 것(3절)이다 |
| Wildfire | 격리 함수 퍼징 후 호출 맥락에서 실현 가능성을 확인하는 compositional fuzzing. 고립 함수마다 다시 컴파일하지 않도록 compiled bitcode에 entry point를 동적으로 넣는다(§8.2 item 2) | 실현 가능성은 위쪽으로 가는 양성 확인(stack-trace 일치, targeted SE)이다. 확인 실패를 불가능의 증명으로 보지 않는다(§4.6.2). 요약은 구체 인자 값만 비교한다(§4.5). 비교 도구에 약 12배 시간(최대 24시간)을 줬다(§6.3) | compositional fuzzing과 "한 번 컴파일하고 여러 진입점 재사용"은 아이디어로서 선행이다. 우리 차이는 ZK 제약 의미(악의적 prover, 코드 경로가 아닌 제약)와 배제 방향의 건전성이다 |
| Picus/QED² | 컴파일러 debug 정보로 회로를 하위 회로로 나눠 반례를 점진적으로 조립한다(§6). 결과는 ✓/✗/?로 나뉜다 | 하위 모델을 합쳐 완전한 모델이 될 때만 ✗, 아니면 ?(§6). 출력이 아닌 중간 변수의 비유일성은 회로의 under-constraint가 아니다(§5). 13개 반례 회로를 8개 템플릿으로 셌다(§7) | Circom 회로의 자동 분해와 unknown 보고는 새롭지 않다. 우리 차이는 퍼징 후보를 대상으로 한다는 점과 맥락 판정의 측정이다 |
| CCC-Check | 제약에서 값 범위를 건전하게 과대근사한다. 입력 tag는 전제로 가정한다(§4.2) | 보장은 tag 위반 검출에 대해 건전하다는 것이며 과대근사 때문에 오탐이 있다(§4.3, 35개 중 7개). 15개 결함은 6개 프로젝트에 사람이 tag를 단 감사형 평가에서 나왔다(§5.4). 도구 검증(§5.2)과 구별된다 | 범위 추론으로 배제하는 기법은 선행이다. tag를 쓰면 명세 의존이 생기고, 보장은 그 가정에 상대적이다 |
| ZEQUAL | 템플릿 단위 일관성 검증. 호출하는 하위 회로가 일관적이라고 가정한다(§6) | 116개 반례 중 수동 확인으로 26개만 실제 결함이었다. 가정을 풀고 다시 돌려 20개를 더 찾았다(§7). 자동 반증은 하지 못한다 | 모듈 단위 결과는 모듈 가정을 푼 재확인과 수동 판정이 필요하다는 직접 선례다. 컴포넌트 후보에도 같은 의무가 있다 |
| CIVER (README만) | 회로 구조를 따라 모든 컴포넌트를 모듈식으로 검사하고 tag와 전제·후제 조건을 검증한다 | 원 논문 미독. README 기준으로 weak safety, tag, pre/post 세 모드가 있다 | 컴포넌트 분해와 assume-guarantee식 검증은 선행이다. 원 논문을 읽기 전까지 세부 비교는 하지 않는다 |
| FuzzSlice (보조) | 함수 slice 퍼징의 충돌은 호출자가 입력을 막을 수 있어 진양성을 뜻하지 않는다. 충돌이 없으면 "가능한 오탐"이다 | 비대칭은 명시했지만, 충돌 없음 판정은 퍼징의 불완전성 때문에 건전하지 않다 | 맥락 실현 가능성 문제는 일반 소프트웨어에 선례가 있다. ZK판 비대칭(3.2절)으로 위치를 정한다 |
| zkCraft (보조, 일부만 읽음) | R1CS 행 단위 "slicer"로 국소화한다 | 호출 맥락을 가진 컴포넌트 분해는 아니다(읽은 범위 안에서) | "ZK 퍼징 최초의 slicing" 같은 표현을 쓰지 않는다 |
| LIEZZ (보조, 초록만) | 툴체인 버그로 실제 강제되는 제약이 소스 의미보다 약해질 수 있다 | 초록 수준 | 맥락 배제의 근거를 소스 읽기가 아니라 컴파일된 제약에 둬야 하는 이유다(3.4절) |

정리하면, 이번 검토 범위에서 **Circom entrypoint를 결함 위치 없이 자동으로 컴포넌트로 나눠 TCCT 퍼저를 돌리고, 같은 entrypoint의 통째 실행과 같은 자원으로 비교한 평가**는 찾지 못했다. 반면 자동 분해(Picus, CIVER, ZEQUAL), compositional fuzzing(Wildfire), 부분 회로 퍼징과 전체 재확인의 제안(Towards Fuzzing)은 있다. 따라서 주장은 "조합의 구현과 측정"으로 한정해야 한다. 09-27 계획의 "부분 회로 퍼징은 제안만 있었고 구현·평가는 없다"는 문장은 **ZK 회로 퍼징에 한정하고 탐색 범위를 밝혀야** 정확하다. 형식 검증 도구에서는 자동 분해가 이미 구현돼 있다.

### 2.2 표현별 검토

| 표현 | 판단 | 권장 |
|---|---|---|
| "최초" (first, novel) | 쓸 수 없다. 2.1절의 선행 때문에 아이디어 수준의 최초성은 성립하지 않는다. 조합의 최초성도 검색이 망라적이지 않아 입증할 수 없다 | "검토한 문헌(1절 목록, 2026-10-01 기준)에서 같은 조합의 평가를 찾지 못했다"처럼 범위를 밝힌 부정문 |
| "무명세"(명세 불필요) | 부분적으로만 성립한다. 자동 구성과 TCCT 오라클, 컴파일된 제약만 쓰는 점 배제는 사용자 명세가 필요 없다. 그러나 컴포넌트 확인의 "선언된 입력 전제", "사전 속성", 프로젝트 확인의 "프로젝트 속성", 원인 수준 배제의 컴포넌트 전제는 모두 명세다. 고정 검토 엔진도 사례별 계약과 predicate를 사람이 쓴다 | 어떤 단계가 명세 없이 돌고 어떤 판정이 명세에 의존하는지 단계별로 적는다. SoK §IV·§VII·§VIII은 명세 부담을 자동 사용과 도구 채택의 장벽으로 보고한다. 그러므로 명세가 필요한 부분을 숨기지 않는 것이 오히려 방어에 유리하다 |
| "자동 확인" | 과장이다. 검토 엔진은 사전에 사람이 쓴 계약과 predicate로 후보를 고정 R1CS에서 다시 계산한다. 의미 판정(속성 정의, 원인 귀속)은 사람이 만든 기준에 달려 있다. 09-27 계획의 "부분 회로 반례를 전체 회로 맥락에서 자동으로 확인"은 아직 없는 기능이다 | "고정 기준의 자동 재검사", "맥락 배제(점 배제) 자동화"처럼 범위를 붙인다 |
| "프로젝트 결함" | entrypoint의 역할을 확인하지 않으면 쓸 수 없다. P2의 zk-email entrypoint(`packages/circuits/tests/test-circuits/rsa-test.circom`)는 경로로 보면 테스트 회로일 수 있지만 production 여부를 확인하지 않았다. 경로 이름만으로 정하지 않고 역할을 확인해 기록해야 한다. entrypoint TCCT 위반도 공개 출력의 의미와 연결해야 보안 결함이 된다 | "entrypoint 수준 확인(어느 entrypoint, production 여부)"과 "프로젝트 속성 위반 확인"을 나눈다(M7) |
| "오탐"(context false positive) | 점 배제만으로 경고를 오탐이라 부르면 과장이다(3.3절) | "맥락에서 실현 불가한 반례"와 "맥락상 무관한 경고(원인 배제)"를 구별한다 |
| "zkFuzz는 오탐이 없다" | zkFuzz §6.1의 결과는 test suite 단위, TCCT 정의 기준이다. 분해 조각의 결과에는 이어지지 않는다 | 컴포넌트 수준 TCCT 위반 재검사만 그 성질을 상속한다고 쓴다 |
| "컴파일 재사용(5,240→63)" | 공학적 측정 성과로 유지할 수 있다. 아이디어는 Wildfire §8.2에 선례가 있다 | 시스템 기여로 쓰되 신규 기법이라 하지 않는다. 현재 계획과 일치한다 |

## 3. 판정의 보장

### 3.1 성질의 층위: 컴포넌트 TCCT와 entrypoint TCCT는 다르다

zkFuzz의 under-constrained 정의(§3.2, Definition 6)는 중간값을 투영해 버린다. 원래 계산이 `(z, y)`를 낼 때 제약이 `(x, z′, y)`를 받아들여도 출력이 같으면 취약점이 아니다. 컴포넌트를 떼어 돌리면 그 컴포넌트의 출력이 `y`가 된다. 하지만 entrypoint에서는 같은 신호가 중간값 `z`다. 따라서 **컴포넌트의 TCCT 위반은 그 자체로 entrypoint의 TCCT 위반이 아니다.** Picus §5(출력만 ✗), §8(다른 회로가 쓰도록 만든 회로의 의도적 비결정성), ZEQUAL Definition 3(중간 신호 불일치 허용)도 같은 결론이다. 계획의 "조각의 출력이 전체에서는 중간값일 수 있다"는 정확하며, 이 근거로 뒷받침된다.

### 3.2 배제와 양립의 비대칭(단조성)

컴파일된 entrypoint 제약 `C_E`의 부분집합 `C′`(같은 wire 식별자)에서 어떤 호출 위치의 컴포넌트 경계값을 고정한 식이 만족 불가능하면, `C_E`에서도 만족 불가능하다. 제약을 더하면 해 집합은 줄어들기만 하기 때문이다. 따라서

- **배제는 국소적으로 건전하게 할 수 있다.** 직접 호출자의 제약만으로 불가능을 보이면 entrypoint 전체에서도 불가능하다. 단, 그 제약이 실제 컴파일된 제약의 부분집합이고 신호 대응이 정확해야 한다.
- **양립은 국소적으로 확정할 수 없다.** 직접 호출자와 양립해도 위쪽 호출자가 막을 수 있다. 양립 판정에는 범위(직접 호출자, 호출 경로, entrypoint 전체)를 반드시 붙여야 한다.

이것은 FuzzSlice가 일반 소프트웨어에서 말한 비대칭(호출자는 입력을 더 제한할 수만 있다)의 ZK판이다. 계획이 배제 우선으로 시작한 것은 이 성질로 정당화된다. 문제 정의의 `context_compatible`("within the declared context scope")은 범위를 요구하므로 맞다. 다만 집계할 때는 범위가 다른 양립을 하나로 합치지 않는다는 규칙을 명시해야 한다(S4).

판정 대상 값은 **컴포넌트 경계의 입력과 출력**(TCCT 투영과 같은 층위, abort형이면 입력)으로 정하는 것이 좋다. 내부 중간값까지 고정하면 다른 중간값으로 같은 경계값을 만들 수 있는 경우에도 "배제"가 나올 수 있다. Circom 최적화로 컴포넌트 신호가 제거되거나 선형 결합으로 치환되면 대응 규칙이 필요하다(검토 설계의 `eliminated-signal` 처리와 같은 문제).

### 3.3 무엇을 배제하는가: 특정 반례와 경고·원인

| 수준 | 의미 | 증명 의무 | 선례 |
|---|---|---|---|
| 점 배제 | zkFuzz가 낸 **이 반례**의 경계값은 이 호출 위치에서 실현 불가하다 | 한 번의 불가능성 증명(UNSAT 또는 건전한 범위 추론) | Wildfire §4.5의 구체 값 요약과 같은 단위다. 단, Wildfire는 양성 확인 방향이다 |
| 원인 배제 | 이 위반 **종류**(예: 입력이 n비트를 넘는 경우)는 이 호출 위치에서 일어날 수 없다 | 모든 입력에 대한 논증. 보통 "호출자 제약이 컴포넌트 전제를 함의한다"와 "컴포넌트는 그 전제 아래 안전하다"의 두 단계가 필요하다 | CIVER의 pre/post 조건, CCC-Check의 tag 검증 |

점 배제는 건전해도 정보가 약하다. 같은 원인의 다른 반례는 실현 가능할 수 있다. 그러므로 **점 배제로 경고를 보고서에서 지우거나 "오탐"으로 분류하면, 경고 수준에서는 건전하지 않다.** 계획의 "특정 후보의 배제는 템플릿 전체가 안전하다는 판정이 아니다"는 이 점을 일부 담고 있다. 하지만 보고서의 "신뢰성" 주장이 어느 수준인지는 아직 정하지 않았다(M3). P2의 zk-email `BigLessThan` 판단(호출자가 `Num2Bits(n)`로 먼저 검사)은 실제로는 원인 수준의 논증이다. 이를 자동화하려면 원인 배제가 필요하고, 이는 CIVER·CCC-Check 쪽 선행 기법의 영역이다.

### 3.4 근거의 출처: 실제로 강제되는 제약만

- `<--`로 계산한 값, `assert`, witness 생성기의 분기는 악의적 prover가 따르지 않는다. 배제 근거가 될 수 없다. 이는 zkFuzz의 abort형 결함과 CCC-Check Definition 2("not automatically enforced by constraints unless explicitly encoded")의 핵심이다.
- Circom signal tag는 메타데이터다(CCC-Check §4.2, CIVER README). 제약으로 검증된 tag만 근거가 된다.
- 정상 실행에서 관찰한 값의 범위는 가능한 값의 전부가 아니다. 계획이 이미 금지했다.
- 소스를 읽고 내린 판단은 컴파일된 제약과 다를 수 있다. LIEZZ는 툴체인 버그로 제약이 소스 의미보다 약해지는 사례를 보고한다. 따라서 근거는 **고정한 컴파일러 판·옵션으로 만든 R1CS**여야 하며, 가능하면 production 빌드 설정과 같아야 한다. SMT를 쓰면 `UNSAT` 문자열이 아니라 검증 가능한 증거를 남긴다는 기존 검토 설계의 원칙(§4)을 배제에도 적용하는 것이 좋다(S3).

### 3.5 입력 전제와 abort형 결함

zkFuzz §6.1에 따르면 찾은 원인의 55.2%는 계산 abort에서 왔다. 대표적인 예가 제약 없이 `assert`로만 지킨 조건이다(§3.3 Code 4, §6.3 Code 9). TCCT는 이렇게 `assert`로만 지킨 전제를 결함으로 본다. 반면 CCC-Check는 같은 상황을 "입력 전제(precondition)를 호출자가 지켜야 한다"로 볼 수 있게 한다. zkFuzz 부록 B의 `LessThan` 설명도 "implicitly assumes"라고 쓴다. 문제 정의의 `component_confirmed`는 "declared component input assumptions"를 만족할 것을 요구한다. 그러므로 **무엇을 선언된 전제로 인정하는지가 컴포넌트 확인 수를 직접 바꾼다.** 같은 `BigLessThan` 후보도 문서화된 n비트 가정을 전제로 인정하면 컴포넌트 확인이 아니다. 인정하지 않으면 컴포넌트 확인이면서 맥락 배제다.

또 기존 검토 엔진은 사례별로 사람이 쓴 입력 계약과 predicate가 있어야 판정한다(검토 설계 §1·§4·§7). 알려진 결함이 아닌 조각(예: P2 inference의 비정답 조각 8개)에는 사전 predicate가 없다. 결과를 본 뒤 predicate를 쓰면 사후 명세가 된다. 이 규칙은 실행 전에 고정해야 한다(M4).

### 3.6 여러 호출 위치, 인스턴스 재사용, 중복 원인

- 컴파일 재사용은 같은 인스턴스를 한 번만 실행하게 하지만, 맥락 판정은 **호출 위치 수**만큼 의무가 생긴다(inference에서 호출 위치 2,576곳이 조각 21개로 줄었다). 후보마다 "n곳 중 k곳에서 배제, 나머지 미판정"을 기록하고, 모든 곳을 다룬 경우에만 entrypoint 배제로 집계한다. 계획과 문제 정의는 이미 이렇게 요구한다.
- 분할 실행에서는 하위 템플릿의 결함이 그것을 포함한 상위 조각에서도 반례로 나온다. P2 inference의 "같은 원인이 여러 조각에서 반복"이 그 예다. 원인 귀속 규칙이 없으면 고유 원인 수가 부풀거나, 반대로 서로 다른 원인이 합쳐진다(M5).
- zkFuzz, Picus, Wildfire는 모두 위치 단위(템플릿, 취약 명령)로 중복을 제거한다. 현재 계획의 원인 단위 귀속은 이보다 엄격하다. 선행 수치와 직접 비교하지 않는다.

### 3.7 양립에서 프로젝트 확인까지

entrypoint 수준의 확인에는 다음이 모두 필요하다. (1) 고정한 entrypoint 제약 전체를 만족하는 할당, (2) 같은 entrypoint 입력에서 정상 계산과 다른 공개 출력이 나오거나 정상 계산이 abort함, (3) 그 차이가 사전에 정한 프로젝트 속성을 위반함. Picus §6은 하위 모델이 완전한 모델로 합쳐질 때만 ✗를 낸다. Wildfire는 호출자 쪽 실행을 실제로 만들어 확인했다. 둘 다 위쪽으로 들어 올리는 비용이 크다. 따라서 몇 주 범위에서는 entrypoint 확인을 자동화하기보다, 소수 사례의 사전 등록된 수동 사례연구로 두는 것이 현실적이다(D4).

통째 실행의 zkFuzz 반례는 처음부터 (1)·(2)를 만족한다. zkFuzz의 에뮬레이터가 충실하고 검토 엔진의 고정 R1CS 재검사를 통과한다면 그렇다. 이 점이 4.2절의 비대칭이다.

### 3.8 미판정

- 시간 초과, 지원하지 않는 구문, 신호 대응 실패, 일부 호출 위치만 처리한 경우는 모두 미판정이다. 계획과 일치한다.
- FuzzSlice식 "찾지 못했으니 가능한 오탐"은 배제가 아니다. 퍼저나 solver가 반례를 못 찾은 것은 미판정이다.
- 배제 실패는 양성 확인이 아니다. 전체 제약과의 양립도 프로젝트 오류의 충분조건이 아니다. 문제 정의는 두 가지를 모두 명시한다.

### 3.9 범주별 필요한 증거

| 범주 | 필요한 증거 | 충분하지 않은 것 |
|---|---|---|
| 컴포넌트 확인 | 고정 컴포넌트 R1CS 전체 만족. 같은 입력의 정상 계산과 출력이 다르거나 정상 계산이 abort. 사전 규칙에 따른 입력 전제 충족. 사전 규칙에 따른 원인 귀속 | zkFuzz의 `NOT SAFE` 메시지, 정답 위치 일치, 사후에 쓴 predicate |
| 맥락 배제(점) | 모든 관련 호출 위치에서 컴파일된 제약의 부분집합으로 경계값이 실현 불가함을 보인 검증 가능한 증거 | 정상 실행 관찰, tag나 `assert`, 소스 읽기만의 판단, solver 시간 초과 |
| 맥락 배제(원인) | 호출자 제약이 위반 종류를 막는다는 모든 입력에 대한 논증 | 점 배제의 누적 |
| 맥락 양립 | 명시한 범위의 제약 전체를 만족하며 후보 경계값을 담은 구체 할당 | 배제 실패, 직접 호출자만의 양립을 entrypoint 양립으로 확대 |
| entrypoint·프로젝트 확인 | 3.7절의 (1)–(3), entrypoint의 역할 명시 | 양립 가능, zkbugs 라벨, 같은 템플릿 위치 |

## 4. 평가 설계의 주요 문제

심각도는 결과 해석이 뒤집힐 수 있으면 **높음**, 수치가 한쪽으로 치우칠 수 있으면 **중간**, 표현이나 재현성 문제면 **낮음**으로 매겼다.

### 4.1 첫 반례 종료가 만드는 고유 원인 수의 비대칭 — 높음

zkFuzz는 위반을 찾으면 탐색을 끝낸다(논문 §1·§4.1, 고정 사본 `src/mutator/mutation_test.rs`의 "If a counterexample is found, return it immediately"). 통째 실행은 실행당 반례가 최대 1개다. 분할 실행은 조각마다 1개다. 그러므로 평가 설계 §4의 "같은 자원의 검토된 고유 원인" 비교는, 두 방식의 탐지 능력이 같아도 분할에 유리하다. 결함이 둘인 entrypoint(inference)에서는 결함별 재현율도 통째 실행이 실행당 1/2로 제한된다. 계획은 "첫 후보에서 끝난 탐색의 기회 손실"을 사후 배제와 관련해서만 언급하고, RQ1 비교의 편향으로는 다루지 않는다. → M2

### 4.2 주 지표의 수준이 정해지지 않았다 — 높음

평가 설계는 컴포넌트 확인과 프로젝트 확인을 따로 보고하고 합산하지 말라고 한다. 이것은 맞다. 그러나 RQ1의 **주** 비교가 어느 수준의 고유 원인인지는 정하지 않았다. 통째 실행의 결과는 처음부터 entrypoint 수준의 증거다(3.7절). 분할 결과는 컴포넌트 수준이다. 컴포넌트 수준에서 비교하면 통째 실행의 반례도 같은 귀속 규칙으로 컴포넌트 원인에 연결해야 한다. entrypoint 수준에서 비교하면 분할 결과를 들어 올려야 한다. 어느 쪽인지 정하지 않으면 "같은 검토 수준"을 확인할 수 없다. → M1

### 4.3 원인 귀속 규칙이 비어 있다 — 높음

계획은 "같은 고유 원인으로 귀속"과 "위치 일치만으로 성과에 넣지 않음"을 요구하지만, 귀속의 판정 절차는 없다. 검토 엔진의 source-transition attribution은 주입 평가용이었다. 알려지지 않은 원인에는 고친 판이 없다. 통째·분할 반례에 같은 규칙을 적용해야 하고, 상위 조각에서 다시 나타난 하위 원인을 한 번만 세야 한다. → M5

### 4.4 사전 속성·입력 전제가 비정답 조각에는 없다 — 높음

3.5절 참조. 알려진 결함은 결함 설명으로 실행 전에 predicate를 쓸 수 있다. 하지만 자동 구성은 결함 위치를 모르는 조각을 많이 만든다. 그 조각들에 쓸 일반 속성과 전제 규칙이 사전에 없으면, 비정답 후보의 판정은 결과를 본 뒤의 명세가 된다. → M4

### 4.5 오라클 범위의 사후 분류 — 중간

평가 설계 §2는 "oracle 적합성에 따른 조건부 분석"을 분리하라고 한다. 하지만 분류 규칙은 정하지 않았다. P2 보고서는 zk-email `FpMul`을 조각에서 찾지 못하자 "zkFuzz의 탐지 범위 한계"로 해석했다. 계획 §2는 이를 "경험적 미탐"으로 바로잡았다. 조건부 분석의 부분집합을 탐지 결과로 정하면 순환 논리가 된다. zkFuzz §2.2의 범위 밖 정의(계산 로직만의 결함 등)와 결함 메타데이터로 실행 전에 분류해야 한다. held-out 기준이 `Vulnerability: Under-Constrained`로 사전 필터한 방식이 선례다. → M6

### 4.6 자원 동등성과 seed 집계 — 중간

- Wildfire는 12코어 병렬을 근거로 비교 도구에 약 12배 시간을 줬다(§6.3). 초록의 "10% of the analysis time"은 이 계산에 기대고 있다. 병렬·순차와 벽시계·CPU 시간 선택이 결론을 바꿀 수 있다는 사례다. P2는 8개 조합을 한 기계에서 동시에 돌렸다. 평가 설계 §3은 동시 실행 수와 경쟁 작업 통제를 기록하라고 하지만, "같은 자원"의 정의(코어·초, 메모리 상한, 방식별 동시성)는 정하지 않았다.
- seed 집계는 도구마다 다르다. zkFuzz는 5개 seed의 최대·최소를 보고한다(§6.1). Wildfire는 5회 모두에서 나온 결과만 센다(§6.4). "어느 seed에서든", "과반", "모두" 중 무엇을 고르느냐에 따라 수가 바뀐다. 계획 §5는 seed 수만 미고정 항목으로 두고 집계 규칙은 두지 않았다. → M8

### 4.7 분석 단위와 통계 — 중간

평가 설계 §2의 "프로젝트·커밋·entrypoint·설정" 실행 단위와 "seed는 독립 사례가 아니다"는 타당하다. 추가로, 같은 프로젝트나 계열의 여러 entrypoint·결함은 군집이다. 사례가 적으므로 검정보다 entrypoint별 쌍대 결과표와 정확 구간(적용률의 Clopper–Pearson 등)이 맞다. 4.1절 때문에 주 결과는 entrypoint 실행 단위의 이진 결과와 첫 검토 통과 시간이 가장 공정하다. → M2, S5

### 4.8 SoK 수치와의 비교 — 낮음

SoK의 TP는 ground truth 위치·주석 대조와 수동 확인이다(§III-B). SoK 격리 모드의 탐지에는, 원인 위치는 맞지만 그 반례가 원래 맥락에서 실현 불가한 경우도 들어갈 수 있다. 원인 귀속과 맥락 판정을 요구하는 우리 수치와 수준이 다르다. 계획은 이미 SoK 수치를 같은 환경 기준선으로 쓰지 않는다. 덧붙여 SoK 본문은 CIVER 격리 모드 TP를 20건이라 쓰지만 그림 2의 막대는 12다(12+18+26+14=70). SoK 안의 본문 수치도 그림·산출물과 대조가 필요하다는 신호다(N1 범위).

### 4.9 조각 구성 규칙 자체가 분석 범위다 — 낮음

P2의 분할은 프로젝트 안의 인스턴스만 조각으로 만들고 라이브러리 템플릿은 상위 조각 안에서 실행한다. zk-email은 외부 의존성을 식별값에 넣지 못해 조각이 모두 제외됐다. 이 규칙은 개발 자료로 정하고 N5에서 고정하되, 평가 실패를 보고 바꾸지 않는다. 규칙 때문에 생긴 제외는 적용성 표의 사유로 남긴다. 계획의 원칙과 일치한다.

### 4.10 계획이 이미 올바르게 다루는 것

다음은 원문과 대조해도 고칠 필요가 없었다. 위치 일치만으로 성공을 세지 않는다. 격리 성공 사례만 고르지 않는다. 실패·미지원·미판정을 분모에 남긴다. seed를 독립 사례로 세지 않는다. 결과를 보고 최선 순서를 고르지 않는다. 준비·실행·맥락 판정·수동 검토 비용을 나눈다. 사람이 위치를 알고 자른 격리를 기준선이나 상한으로 부르지 않는다. 미판정을 오탐이나 진짜 결함으로 세지 않는다. 사후 배제가 탐색 기회를 되찾았다고 주장하지 않는다. 범용 solver·완전성을 목표에서 뺀다. SoK 본문 600초를 확인했다(§III-B). 14건이 도구 전체의 격리 단독 탐지라는 서술도 SoK §V와 일치한다.

## 5. 필수 수정과 선택 제안

기존 문서는 고치지 않는다. 아래는 N3 결정 기록과 N5 프로토콜에 반영할 내용이다.

### 5.1 필수 수정

- **M1. 주 지표의 수준과 비교 규칙 고정 (N3 결정, N5 고정).** RQ1 주 지표를 "사전 규칙으로 원인 귀속된 컴포넌트 확인 원인"으로 할지, "entrypoint 수준 확인"으로 할지 정한다. 권고는 전자를 주 지표로 하고, 통째 실행 반례에도 같은 귀속 규칙을 적용하는 것이다. entrypoint 수준은 별도 표로 보고하고 두 수준을 합산하거나 섞어 "분해가 프로젝트 결함을 더 찾는다"고 쓰지 않는다.
- **M2. 첫 반례 종료 비대칭을 반영한 주 결과 정의 (N5).** 주 결과는 entrypoint 실행 단위의 "검토를 통과한 사전 등록 원인을 하나 이상 얻었는가"와 "첫 검토 통과 원인의 시간 상한"으로 한다. 결함별 재현율과 고유 원인 수는 보조로 보고하고 "통째 실행은 실행당 최대 1개"라는 구조적 상한을 함께 적는다. 분할에서 나온 사전 등록 밖 원인은 맞대결 수치가 아니라 "추가 컴포넌트 결과"로 따로 보고한다.
- **M3. 맥락 배제의 대상·수준·근거 정의 (N3 결정, N5 고정).** (a) 판정 대상은 컴포넌트 경계의 입력·출력 값(abort형은 입력)이다. (b) 근거는 고정한 컴파일러 판·옵션의 R1CS 부분집합과 검증된 신호 대응뿐이다. witness 코드, `assert`, 검증되지 않은 tag, 정상 실행 관찰은 근거가 아니다. (c) 점 배제와 원인 배제를 다른 범주로 기록하고, 점 배제로 경고를 지우거나 "오탐"이라 부르지 않는다. (d) 양립 판정에는 범위를 붙이고 범위가 다른 결과를 합산하지 않는다.
- **M4. 입력 전제와 사전 속성의 규칙을 실행 전에 고정 (N5).** 전제의 출처(없음, 고정 소스의 Circom tag, 문서화된 주석, `assert`)와 abort형의 처리를 정한다. 비정답 조각에는 일반 TCCT 속성(같은 입력에서 출력 차이 또는 정상 계산 abort)을 사전 속성으로 두는 것을 권한다. 알려진 원인에만 사례별 속성을 실행 전에 등록한다. 전제를 어긴 후보는 버리지 말고 "전제 위반" 표시로 남겨 맥락 판정으로 보낸다.
- **M5. 원인 귀속 규칙 (N5).** 통째·분할 반례에 같은 규칙을 적용한다. 규칙의 재료는 zkFuzz가 변이한 할당 위치, 그 위치를 포함하는 최소 템플릿에서의 재검사, 알려진 원인이면 수정 커밋과의 대응이다. 상위 조각에서 다시 나타난 하위 원인은 한 번만 센다. 위치는 보조 정보로만 쓴다.
- **M6. 오라클 범위 분류를 실행 전에 메타데이터로 (N3 결정, N5 고정).** 결함 설명과 원인 분류로 TCCT 범위 안·밖·불명을 실행 전에 적는다. 미탐을 보고 바꾸지 않는다. 조건부 분석은 이 사전 라벨로만 한다.
- **M7. 용어 (N3 결정 기록부터 적용).** "프로젝트 확인"은 entrypoint 이름과 역할(production, 테스트 회로)을 붙인 "entrypoint 수준 확인"으로 쓴다. "프로젝트 결함"은 프로젝트 속성 위반까지 확인한 경우에만 쓴다. "최초"는 쓰지 않는다. "자동 확인"은 "고정 기준의 자동 재검사"로 바꾼다. "오탐"은 3.3절의 두 수준으로 나눠 쓴다.
- **M8. 자원 동등성과 seed 집계 규칙 (N5).** 방식별 동시 실행 수, 코어·초, 메모리 상한을 같게 정의하고 CPU 시간을 기록한다. seed 집계 규칙(어느 seed, 과반, 모두)을 미리 하나 정하고 나머지는 민감도 분석으로 둔다.

### 5.2 선택 제안

- **S1. 호출자 쪽 수정 쌍을 맥락 배제의 자연 대조군으로 쓰기 (개발 자료 한정).** 수정 커밋이 호출자에 범위 검사를 추가한 경우, 취약판에서는 배제되지 않고 수정판에서는 배제돼야 한다. 주입 없이 배제 정확도를 점검할 수 있다. 평가 자료의 수정판은 프로토콜 고정 전에 열지 않는다.
- **S2. 오라클·검사 종류별 보고.** TCCT 출력 차이, abort형, zkFuzz의 하드코딩 검사(예: P2에서 본 `LessThan` 넘침 검사. SoK §IV는 zkFuzz가 hard-coded check에 의존한다고 쓴다)를 나눠 맥락 판정 결과를 보고한다. 전제 위반형 검사는 맥락 실현 불가 반례가 몰리는 곳일 가능성이 높다(P2 zk-email의 한 사례).
- **S3. 배제 분석 단계와 증거 형식.** 가벼운 건전 추론(비트·범위·선형)을 직접 호출자 제약에 먼저 적용하고, 남은 것만 시간 제한을 둔 SMT로 넘긴다. 단계별 처리율과 미판정률을 보고한다. 이는 CCC-Check·Picus의 기법을 쓰는 것이므로 기법의 신규성을 주장하지 않는다. UNSAT에는 검증 가능한 증거를 남긴다.
- **S4. 호출 위치 단위 기록.** 후보마다 관련 호출 위치 수와 배제·양립·미판정 위치 수, 판정에 쓴 제약 범위를 남긴다. entrypoint 배제는 모든 위치를 다룬 경우만 센다.
- **S5. 통계 보고 형식.** entrypoint별 쌍대 결과표, 프로젝트·계열 군집 표시, 비율의 정확 구간, 효과 크기를 쓰고 소표본 유의성 검정은 하지 않는다.
- **S6. 비용을 맞춘 통째 실행 민감도 분석.** 분할의 준비 비용(탐색·컴파일)을 더한 시간만큼 통째 실행에 준 조건을 보조로 둔다. Wildfire식 자원 환산 논쟁을 미리 막는다.
- **S7. RQ2 예산 문구 명확화.** 평가 설계 §3은 결과를 본 뒤 제한을 줄이지 말라고 한다. 이와 별개로 N5에서 **사전 등록**한 부족 예산 조건은 허용된다고 적어 두면 RQ2 설계가 막히지 않는다.
- **S8. 인용 정밀도.** (a) zkFuzz v3 PDF의 절 번호는 아라비아 숫자다(§3 정의, §6 평가, §8 한계, 부록 B). 계획 §8의 §III·§VI·§VIII은 판과 번호 체계를 함께 적는다. (b) 09-27 계획의 "SoK 그림 2(격리 모드 미탐 16건)"에서 16은 FN 라벨만이다. zkFuzz 격리 모드에서 탐지하지 못한 것은 FN 16, 오류 4, 시간 초과 25로 모두 45건이다. 프로젝트 모드는 TP 4, FN 12, 오류 4, 시간 초과 36이다. (c) CIVER는 원 논문을 읽은 뒤에만 세부 결과를 인용한다.

## 6. 몇 주 안에 필요한 최소 증거와 보류할 확장

**최소 증거.** 이 넷이 있으면 좁은 주장(적용성, 쌍대 비교, 맥락 판정의 측정)을 방어할 수 있다.

1. **적용성 표.** N1이 정한 전체 모수에서 자동 탐색·준비의 성공·실패와 사유를 기록한다. 수동 보완은 따로 둔다. held-out 기준이 허용한 도구(소스 열람, `circom` 컴파일, 타깃 탐색)만으로 만들 수 있는지는 N3에서 정한다(D6).
2. **쌍대 비교.** 사전 고정한 평가 entrypoint에서 통째·분할을 같은 자원으로 실행한다. M1·M2의 주 결과, 시간 상한, 단계별 비용을 보고한다.
3. **맥락 판정 측정.** 2의 분할 후보 전부(또는 사전 등록한 표본)에 M3의 점 배제를 적용한다. 배제·양립(범위 포함)·미판정 비율, 호출 위치 처리율, 비용을 보고한다. 개발 자료로 두 가지를 미리 점검한다. 알려진 실제 원인의 후보를 배제하지 않는가(배제하면 건전성 결함이거나 그 반례가 실제로 실현 불가한 것이므로 수동 확인). P2 `BigLessThan`처럼 수동 논증이 있는 사례를 배제하는가.
4. **수동 감사 표본.** 배제와 양립 판정을 사전 규칙으로 일부 뽑아 사람이 확인한다. 분모와 미판정률을 함께 쓴다.

**보류할 확장.** entrypoint 수준 확인의 자동화(위쪽 들어 올리기), 원인 수준 배제(assume-guarantee), 적응형 배분과 순위 개선, 여러 분석 도구, 컴파일러 교체, 주입 평가. 앞의 둘은 맥락 판정을 넓히는 자연스러운 다음 단계다. 그러나 선행 기법(CIVER, CCC-Check, Picus, Wildfire)과의 차별화가 더 어렵고 몇 주 범위를 넘는다.

## 7. 미결정 항목

### 7.1 N3에서 결정할 것

| ID | 결정 사항 | 이 검토의 권고 |
|---|---|---|
| D1 | RQ1 주 지표의 수준과 분석 단위 | 컴포넌트 확인 원인. 주 결과는 entrypoint 실행 단위의 이진 결과와 첫 검토 통과 시간(M1·M2) |
| D2 | 맥락 후보배제의 목표 수준과 근거 범위 | 점 배제만. 근거는 컴파일된 제약의 부분집합(직접 호출자부터). 원인 배제는 보류(M3) |
| D3 | 입력 전제의 출처와 abort형 처리 원칙 | 비정답 조각은 전제 없는 일반 TCCT 속성. 문서화된 전제는 "전제 위반" 표시로 기록(M4) |
| D4 | entrypoint·프로젝트 확인의 범위 | 사전 등록한 소수 사례의 수동 사례연구로 한정 |
| D5 | 평가 모수·노출층·포함 규칙(N1 결과 필요) | 루트 결함과 테스트 회로 entrypoint를 분모에 남기고 표시. 오라클 범위는 메타데이터로 사전 분류(M6) |
| D6 | 평가 후보에 프로토콜 고정 전 준비 단계(컴파일·탐색)를 허용할지 | held-out 기준의 허용 도구 범위를 따르되, 결과를 본 뒤 구성 규칙을 바꾸지 않는다는 조건을 명시 |
| D7 | N4의 최소 개발 범위 | P2가 드러낸 준비 실패 두 가지(외부 의존성 식별, 함수 계산 파라미터·컴파일 타임 배열) 중 적용성 표에서 비중이 큰 것만. 점 배제 시제품은 개발 자료에서만 |
| D8 | 주장 축소와 중단 기준 | 적격 entrypoint가 적으면 사례연구·적용성 분석으로 줄인다. 배제 시제품이 개발 자료 점검(6절 3)을 통과하지 못하면 맥락 판정은 사전 규칙의 수동 판정으로 대체한다. 기준값은 N1 결과를 보고 정한다 |
| D9 | 수동 검토의 시간 상한과 표본 규칙 | 전수 검토할 범주(주 결과의 양성)와 표본 검토할 범주를 나누고 추출 규칙을 정한다 |

### 7.2 N5에서 고정할 것

계획 §5의 항목에 더해 다음을 고정한다. 원인 귀속 규칙(M5), 일반 TCCT predicate와 사례별 predicate(M4), 전제 위반 표시 규칙, 오라클 범위 사전 라벨(M6), 자원 동등성 정의와 seed 집계 규칙(M8), 맥락 배제의 건전성 서술(제약 모델, 컴파일러 판·옵션, 신호 대응, 신뢰 기반, 증거 형식), 양립 범위 표기, 호출 위치 기록 형식(S4), 통계 보고 형식(S5).

### 7.3 N4에서 확인할 사실

- 고정 zkFuzz의 CLI 경로가 `mutation_test.rs`의 첫 반례 종료를 그대로 따르는지. `LessThan` 넘침 같은 추가 검사가 출력 차이를 요구하는지.
- zkFuzz 반례의 신호를 고정 R1CS의 wire와 SYM에 대응시키는 규칙. 최적화로 제거된 신호의 처리.
- 기존 검토 엔진의 relation-exclusion verifier가 맥락 배제에 어디까지 재사용될 수 있는지. 현재 문서대로 "이미 해결했다"고 가정하지 않는다.
- 통째 실행 반례가 분할 반례와 같은 검토 엔진 경로를 통과하는지.

## 8. 원문 근거 (발췌)

인용은 짧게 하고 절을 밝혔다. 번역은 2–3절 본문에 있다.

- zkFuzz v3 §1: "This process repeats until a violation is found or a timeout occurs."
- zkFuzz v3 §3.2: "if P(x) = (z, y) and C accepts (x, z′, y) such that z ≠ z′, it is not an under-constrained vulnerability"
- zkFuzz v3 §2.2: 범위 밖 "(2) bugs solely in the computation logic"
- zkFuzz v3 §6.1: "A bug in a Circom template may affect all programs that instantiate the template, but we count it as a single bug"
- zkFuzz v3 §6.1: "Since there may be undetected bugs not flagged by any tool, we do not report true or false negatives."
- zkFuzz v3 §6.1: "55.2% of root causes stem from computation abort bugs"
- zkFuzz v3 §8: "slicing and partially executing the target might improve ZKFuzz"
- zkFuzz v3 부록 B: "LessThan implicitly assumes that the bit length of both inputs are not longer than n"
- 고정 zkFuzz `src/mutator/mutation_test.rs` 문서 주석: "If a counterexample is found, return it immediately."
- SoK §III-B: "We do not measure false positives ... We leave a false-positive analysis to future work."
- SoK §III-B: "in a minimal wrapper that isolates the vulnerable code (isolated mode) and in the original project codebase (project mode)"
- SoK §III-B: "two authors manually inspect the raw output and compare it with the dataset annotation"; "600-second timeout"
- SoK §V: "Among the 56 bugs that compile in both modes, 31 are missed in both modes, 6 are detected in both, and 14 are detected only in isolated mode."
- SoK 그림 2 zkFuzz: 격리(n=70) TP 25, FN 16, Error 4, Timeout 25. 프로젝트(n=56) TP 4, FN 12, Error 4, Timeout 36 (5쪽 이미지 판독)
- SoK §V: "CIVER detects 20 TPs in isolated mode" (그림 2 막대는 12)
- SoK §VIII: "connect layers through obligations such as computation–constraint consistency, interface invariants, translation validation, and component composition"
- Towards Fuzzing §3.2: "when sub-circuits are targeted, the findings must be validated against the entire circuit to prevent false positives."
- Towards Fuzzing §4: "it did not uncover soundness bugs since we did not fuzz the witness"
- Wildfire §4.6.2: "it might be because the fuzzer was not able to generate any test-cases ... and not merely because such a path does not exist"
- Wildfire §6.3: "approximately 12 times the total time taken by Wildfire or 24 hours, whichever was smaller"
- Wildfire §6.4: "in almost 90% less time (considering parallelism)"; "we only list those vulnerabilities and chains that were reported by all five runs"
- Wildfire §8.2: "allowing to dynamically insert entry-points in the compiled LLVM bitcode, for every isolated function"
- Picus §5: "unconstrained intermediate variables do not imply that the overall circuit is underconstrained"
- Picus §6: "if M is a complete model, QED2 returns ✗ and ? otherwise"
- Picus §8: "intentional nondeterminism occasionally occur when a circuit is designed to be used by other circuits"
- CCC-Check Def. 2: preconditions "are not automatically enforced by constraints unless explicitly encoded"
- CCC-Check §4.2: "Tags on input signals correspond to preconditions L in the DCM: they are assumed to hold"
- CCC-Check §4.3: over-approximation "we may flag a false positive"; "if a real violation exists, it will be detected"
- CCC-Check §5.4: "we manually tagged six projects, similar to the workflow of security auditors"
- ZEQUAL §6: "Zequal verifies such circuits by assuming the consistency of any invoked subcircuit."
- ZEQUAL §7: "Among the 116 potentially vulnerable circuits we manually inspected, 26 were confirmed to correspond to real bugs."; "Zequal cannot automatically refute correctness"
- CIVER README(`af7d4ed`): "it uses the structure of the circuit definition to modularly check all the components"
- FuzzSlice §1: "a caller function can invalidate the input that causes the observed crash in the slice"
- LIEZZ 초록: "Bugs in these toolchains can leave the enforced constraints weaker than the source-program semantics"

## 9. 남은 불확실성

- CIVER 원 논문을 읽지 못했다. CIVER가 호출자 맥락을 이용한 후보 배제에 해당하는 기능이나 평가를 이미 보고했다면, 2.1절의 차별화 문장을 다시 써야 한다. N3 전에 원문 접근을 다시 시도할 가치가 있다.
- Picus §5.1, CCC-Check 부록, ZEQUAL 확장판, LIEZZ와 zkCraft 본문은 읽지 않았다. 건전성 증명의 세부를 인용할 때는 해당 부분을 먼저 읽어야 한다.
- Wildfire의 표 수치는 판독하지 않았다. 본문 서술만 썼다.
- 웹 검색 두 번은 망라적이지 않다. 2026년 하반기 preprint 가운데 직접 대응 연구가 있을 수 있다.
- zkFuzz 첫 반례 종료는 논문과 고정 사본의 한 함수에서 확인했다. CLI 전체 경로의 동작은 N4에서 확인한다.
- 이 검토는 계획 문서의 논리를 원문과 대조한 것이다. 실제 자료에서 맥락 배제가 얼마나 가능하고 비용이 얼마인지는 아직 측정되지 않았다.
