# 연구 방향과 다음 작업 (2026-10-01)

**상태: 현재 작업 계획. 평가 프로토콜은 아직 고정하지 않았다.** 2026-10-01 논의에서 정한 방향을 반영한다. 이전 계획의 향후 작업 지시와 충돌하면 이 문서를 따른다. 기존 고정 프로토콜·manifest·입력 계약·실행 기록·검토 판정은 계속 보존한다.

- 목표: [문제 정의](problem_statement.md)
- 평가 설계: [2026-10-01 평가 계획](evaluation_plan_2026-10-01.md)
- 현재 결정·착수 범위: [N3 채택 기록](scope_decision_accepted_2026-10-01.md)과 후속 [정상 개발 실행](../reports/n4-1-normal-execution-2026-10-01/SCOPE.md) — N3 완료, miiz 담당 N4-1 정상 계산·준비 비용 실측 및 재현된 오프라인 집계 오류 수정 완료, 전체 관문 미통과
- 논문 작성: [주장별 근거 색인](paper_evidence_index.md) · [최신 연구 체크포인트](../reports/research-checkpoint-2026-10-01/REPORT.md)
- 최신 정상 개발 결과: [NB-01 O0 자동 경계 입력 연결](../reports/n4-1-normal-boundary-replay-2026-10-02/REPORT.md) 완료 — 원본 입력 9조건·경계 45개. [NC-01 이후 인계](next_step_handoff_2026-10-02.md)는 당시 기록으로 보존. [A-01 부분 결과](../reports/n4-1-policy-a-2026-10-02/REPORT.md)는 비보안용 예산 모델·정상 자식 계측·NB 회귀를 완료했으며 실제 엔진 연결/캠페인은 미실행. [인계 원문](next_policy_a_handoff_2026-10-02.md)은 보존
- 완료 작업의 인계 이력: [N1·N2 프롬프트](handoff_prompts_2026-10-01.md)
- 현재 증거: [연구 현황](../reports/START_HERE.md)

## 1. 결정한 목표와 범위

zkfDO의 주 질문은 **결함 위치를 사전에 알려주지 않은 Circom entrypoint에서 분석 대상을 자동 구성했을 때, 전체 회로 분석과 비교해 같은 자원·시간에서 검토된 고유 결함을 얼마나 얻으며, 호출 맥락을 잃은 결과를 얼마나 신뢰할 수 있게 해석할 수 있는가**이다.

| 항목 | 이번 계획의 결정 |
|---|---|
| RQ1 | 주 연구. 자동 구성의 적용성, 동일 예산의 확인된 고유 원인, 준비·실행·검토 비용을 함께 평가 |
| 호출 맥락 판정 | 핵심 타당성 과제. 초기 목표는 특정 후보가 해당 맥락에서 불가능함을 건전하게 입증해 배제하는 것. 미배제는 미판정 |
| RQ2 | 보조 분석. 순서에 따른 최초 발견시간·예산 내 결과를 비교하되, 순위의 우위를 논문 성립 조건으로 삼지 않음 |
| 컴파일 재사용·실행 관리·검토 엔진 | 유지할 시스템 구성요소. 각각의 존재만으로 새로운 알고리즘이나 최초성을 주장하지 않음 |
| 새 결함 발견 | 필수 완료 조건이 아님. 알려진 실제 결함으로도 가설을 평가할 수 있음 |
| 기존 주입 평가 B1~B3 | 보류. 첨부에서 부른 맥락 판정의 “방법 B”와 혼동하지 않도록 이후 문서에서는 **맥락 후보배제**라고 부름 |
| 적응형 배분·ML·LLM 의존·새 SMT 통합·여러 분석 도구 지원 | 이번 범위에서 보류 |
| 컴파일러/해석기 전면 교체 | 보류. 적용성 병목의 근거를 먼저 모으고 최소 변경을 선택 |

분해 퍼징, 모듈식 검증, 부분 결과 합성, 컴파일 재사용에는 선행이 있다. 기여 가설은 이들을 나열하는 것이 아니라 **자동 구성의 적용 범위, 확인된 결과의 증가, 맥락 손실에 따른 후보의 신뢰성, 실제 총비용**을 함께 입증하는 데 있다. “최초 구현”, “일반적 우위”는 현재 확정한 사실이 아니다.

주 기여 가설은 자동 분해 시스템으로 유지한다. 기존 랭킹과 RQ2 보조 분석을 유지하며, 맥락 후보배제는 자동 분해 결과의 타당성 과제다. [N3 결정용 기록 §2·6](scope_decision_final_2026-10-01.md#2-기술적-기여와-현재-입증-범위)은 기술적 차별성·개발과 분리된 평가·신뢰성·총비용과 지표별 판단 기준을 제안한다. 랭킹 폐기나 맥락 오탐 제거 중심 전환을 확정하지 않으며, 미검증 투영·원인 귀속·wrapper 의미 보존을 현재 성과로 쓰지 않는다. miiz는 [별도 결정 기록](scope_decision_accepted_2026-10-01.md)으로 보정안을 채택했다. 결정용 원문의 대기 문구는 당시 상태로 보존한다.

## 2. 현재 증거와 한계

- v1.1~v3는 서로 다른 개발 캠페인에서 알려진 원인을 검토한 기록이다. 반복 횟수나 캠페인별 결과를 하나의 독립 성능 점수로 합치지 않는다.
- [P2](../reports/dev-rq1-pilot-2026-09-29/README.md)는 inference에서 분해의 가능성을 보였다. 한 개발 프로젝트의 두 알려진 결함 위치에서 반복적으로 후보가 나왔으며, 해당 P2 정답 후보의 별도 검토는 하지 않았다. zk-email은 준비 실패 후 수동 조각 실행이므로 자동 파이프라인 적용 성공으로 세지 않는다. 8개 조합 동시 실행 결과는 개발 자료로 남긴다.
- 같은 설정의 500세대 미탐은 경험적 미탐이다. oracle의 원리적 한계를 별도 논증한 경우와 구분한다. 과거 보고서의 문구·판정을 덮어쓰지 않고 후속 해석에서 이 제한을 명시한다.
- [컴파일 재사용](../reports/t6a-compile-reuse-2026-09-26/REPORT.md)은 5,240회에서 63회로 줄인 공학적 성과다. 이 수치만으로 탐지 성능이나 독립적인 알고리즘 신규성을 주장하지 않는다.
- 넓은 독립 평가와 프로젝트 수준 결과는 아직 확보된 성과가 아니다. 맥락 후보배제는 제안 단계이며, 기존 전파 검증기가 이 작업까지 완성했다는 뜻이 아니다.

### N1 감사와 N2 검토 완료: N3에 넘긴 근거

[N1 감사](../reports/sok-artifact-audit-2026-10-01/REPORT.md)는 고정 revision·해시에서 전체 Circom **70건**, original 선언/결과 **56건**, 공통 ID의 zkFuzz **격리만 TP 10·프로젝트만 TP 1·양쪽 TP 3·양쪽 비TP 42**를 재확인했다. 비TP에는 오류·timeout·정답 일치 판정 결측이 포함된다. 도구 전체의 격리 단독 TP는 14건이다. original 부재 14건은 부재 사유 unknown으로 보존하며, 공개 compiled flag로 현재 준비 성공을 선언하지 않는다.

기존 repo 제외목록 미등재 **5건·3repo**는 후속 조사·프로젝트 노출 이력이 있어 미노출로 복원할 수 없다. 70건 모두 메타데이터·공개 결과 지식에 노출돼 있다. 56개 original 행의 **36개 잠재 묶음**은 설정·의존성 미확인으로 확정 실행 단위가 아니다. 전체 분모와 노출·계열·entrypoint 정보를 보존하고 성공 사례만 주 집합으로 고르지 않는다. 독립 평가 세트를 확보했다는 결론은 내리지 않았다.

SoK 논문·README는 600초, 공개 JSON은 300초, 같은 revision의 builder는 600초 상수를 사용한다. **실제 실행 제한은 미해결**이다. SoK 과거 결과는 우리 환경의 직접 기준선이 아니다.

[N2 검토](../reports/methodology-review-2026-10-01/REVIEW.md)는 완료 상태다. 같은 검토 수준, 첫 후보 종료, 전제·abort형, 특정 후보 배제와 원인/경고의 구분, 원인 귀속과 자원 집계를 지적했다. CIVER 본문 미접근 등 읽은 범위의 한계는 유지한다. N2 M2는 원인 수를 구조적 상한을 병기한 보조 지표로 권고했다. [N3 초안](scope_decision_2026-10-01.md)과 [독립 검토](../reports/n3-scope-review-2026-10-01/REVIEW.md)를 보존하며, [결정용 기록](scope_decision_final_2026-10-01.md)은 파이프라인 수율 비교와 알려진/추가 원인의 대칭 규칙을 유지한다. 이진 지표도 조기 종료 문제를 해결하지 않으며 검토의 모든 제안을 자동 채택하지 않는다.

## 3. 판정의 의미

판정은 한 줄의 성공/실패로 합치지 않고 별도 차원으로 기록한다. 아래 용어는 연구 설계 용어다. [공통 기록 v1](evidence_record_v1.md)은 컴포넌트·entrypoint TCCT·투영·귀속·검토 완료 상태를 분리해 보존하지만, 이 메타데이터 구조가 각 의미 판정을 수행하거나 입증하지는 않는다.

| 차원 | 의미 |
|---|---|
| 컴포넌트 확인 | 실행에 연결된 후보가 사전 입력 전제·고정 원본 제약 전체·사전 속성 위반 검토를 통과하고, 같은 고유 원인으로 귀속됨 |
| 맥락상 배제 | 정확한 대응과 건전한 판정 아래, 특정 후보가 관련 호출 맥락에서 불가능함을 입증. 그 특정 후보를 선택한 entrypoint 전체에서 배제하려면 관련 호출 위치를 모두 다뤄야 함 |
| 맥락 미판정 | 대응·범위·비용·분석 능력의 한계 등으로 결론을 얻지 못함. 배제 실패도 이 범주 |
| 맥락 양립 가능 | 검토 범위의 제약과 양립하는 근거가 있음. 이것만으로 프로젝트 결함이 확인되지는 않음 |
| entrypoint TCCT 확인 | 고정 entrypoint 제약 전체와 정상 계산/관찰 관계를 재검사하고 역할을 명시하는 별도 층. 원인 미귀속 결과를 컴포넌트 확인 원인 수에 섞거나 프로젝트 의미 속성 위반으로 자동 승격하지 않음 |
| 프로젝트 확인 | 별도 증거로 사전 정의한 프로젝트 의미 속성의 위반까지 확인 |

컴포넌트 확인과 프로젝트 맥락에서의 배제는 함께 성립할 수 있다. 조각의 출력이 전체에서는 중간값일 수 있으므로, 전체 제약과 양립하는 내부 차이가 최상위 속성 위반을 뜻하지 않는다. 정상 witness 계산에서 관찰한 값만을 가능한 값의 전부로 가정하지 않는다. 특정 후보의 배제는 해당 템플릿 전체가 안전하다는 판정이 아니다.

같은 템플릿 위치에서 나왔다는 사실은 원인 귀속의 보조 정보다. **위치 일치만으로 주 성과에 넣지 않는다.** 양쪽 비교 방식에 같은 검토 수준을 적용하고, 투영·귀속 미판정의 수·사유·비용과 같은 수준의 집계에 미치는 영향을 따로 보고한다. 사후 후보배제의 효과와 첫 후보에서 끝난 탐색의 기회 손실은 별도 문제다.

## 4. 작업 순서와 완료 기준

N1·N2는 완료했고 miiz가 [N3 채택 기록](scope_decision_accepted_2026-10-01.md)에 범위·주장·고정 방식, A안 우선, 단계 순서와 작업 상한을 확정했다. **N3 완료, N4 진행 중(N4-1), N5 미고정**이다. 초기 정상 계산·준비 비용 실측과 별도 오프라인 집계 오류 수정에 이어 [NC-01 정상 호환성](../reports/n4-1-normal-compatibility-2026-10-01/REPORT.md)과 [NB-01 O0 정상 경계 입력 연결](../reports/n4-1-normal-boundary-replay-2026-10-02/REPORT.md)을 완료했다. NB-01은 원본 입력 9조건·경계 45개에서 입력 전달 57leaf와 독립 출력 비교 57leaf를 기록했다. [이전 인계](next_step_handoff_2026-10-02.md)는 당시 기록으로 보존한다. O0는 개발 범위이며 평가 옵션 고정이 아니다. [A-01 부분 결과](../reports/n4-1-policy-a-2026-10-02/REPORT.md)는 비보안용 모델과 한정 계측이고, 후속 [A-02](../reports/n4-1-policy-a-engine-2026-10-02/REPORT.md)가 통째 1/1·분할 21/21을 같은 실제 실행기로 각각 600초 수행했다. A-02 후보는 현재 31건 중 [S-04](../reports/n4-1-a02-intdiv-review-2026-10-02/REPORT.md)·[S-05](../reports/n4-1-a02-first-semantic-review-2026-10-02/REPORT.md)의 2건이 컴포넌트 TCCT로 검토됐고 29건은 미검토다. S-05의 알려진 원인 하나는 고정된 두 입력의 entrypoint에서도 TCCT 위반으로 확인됐다. [현재 연결표와 시간 정정](a02_review_status.md)에 원인 중복과 관측시각의 의미를 기록했다. 자원 공정성·N4-1 전체·N5는 미완료다.

| ID | 작업 | 선행 | 완료 기준 |
|---|---|---|---|
| D0 | 목표·계획·인계 문서 정리 | 이번 논의 | 현재 문서의 우선순위·지표·링크가 일치하고 고정 자료가 보존됨 |
| N1 | 공개 메타데이터·노출목록 감사 | D0 | 전체 모수, ID/프로젝트 계열 매핑, 공개 결과 교차표, entrypoint 정보의 확인 수준, 시간 설정 불일치, 미확인 항목을 출처와 함께 기록. 소스 추가 조사·컴파일·퍼징 없음 |
| N2 | 문헌·판정·평가 방법론 검토 | D0, N1과 병렬 가능 | 원문 절·표 근거, 신규성 경계, 판정 보장, 평가 편향, 필요한 증거와 미결정 항목을 독립 검토. 코드·실험 없음 |
| N3 | 평가 범위와 최소 개발 범위 결정 | N1, N2 | 결정용 기록의 채택/변경을 miiz가 별도 기록. 문서 정리만으로 완료 처리하지 않음 |
| N4 | 개발 자료에서 최소 기능·검토 설계 정리 | N3, 별도 착수 범위 | 비교 가능성 → 준비 병목 → 맥락 판정 → N5 기록 순서와 첫 단계 관문. 구현·새 실행은 별도 범위이며 코드 변경 시 의미 있는 검증과 필수 검사를 통과 |
| N5 | 새 평가 프로토콜 작성·고정 | N3, N4 | 초기 대상 목록·포함·단위 생성/중복 제거·예산·준비 실패·검토·집계 규칙, 도구/자료 해시와 miiz 기록을 먼저 고정. 준비 산출물은 이후 생성·대응 실행 전 기록 가능, 성공 사례 사후 선정 금지 |
| N6 | 고정 범위의 평가 기록 | N5 | 고정된 규칙의 전체 실행과 실패·미판정 기록 보존. 이 문서는 실행 명령이나 자동 캠페인 지시가 아님 |
| N7 | 분석·논문 주장 정리 | N6 | 전체 분모와 조건부 분석, 고유 원인·프로젝트 단위 결과, 불확실성·비용·한계를 함께 보고 |

N1·N2와 N3 독립 검토는 완료했다. [채택 기록 §2](scope_decision_accepted_2026-10-01.md#2-miiz의-결정)에 따라 총 40 담당자 작업시간·12/10/10/8시간을 작업 상한으로 채택했다. 완료 예상시간이 아니다. 비교 가능성 → 준비 병목 → 조건부 맥락 판정 → N5 기록 순서이며 첫 관문에서 후속 범위를 판단한다. 기존 기록·집계 작업에 이어 별도 승인된 [정상 개발 실행 범위](../reports/n4-1-normal-execution-2026-10-01/SCOPE.md)를 수행했다. 아래 기존 집계 검사 결과는 당시 기록이며 이번 실측 수치 산출에 집계기를 사용하지 않았다. 구조 테스트나 제한된 정상 입력 일치를 전체 의미 검증으로 세지 않고 N4-2로 자동 확장하지 않는다.

### N4-1 이번 구현 결과와 남은 관문

[공통 기록 v1](evidence_record_v1.md)의 importer에 이어, miiz의 후속 지시 범위인 [오프라인 집계 v1](evidence_aggregate_v1.md)을 구현했다. `experiment aggregate --request ... --output ...`은 해시 고정 record만 읽어 실행 단위·방식·캠페인/반복·검토 층별 결과를 새 파일에 쓴다. 설정/버전/정책 충돌을 분리하고 unknown 실행을 묶지 않는다. 단위 다중 상태, 후보/검토/캠페인 완전성, 범위 있는 원인 등록과 중복, 호환되는 후보별 시간의 정확 최초/완료 상한/관측 최소/산출 불가를 구분한다. 입력이 보고한 주장 집계이며 의미 인증이 아니다. v1 읽기를 유지하고 새 v2 기록에는 완전성·시간 연결·위반 유형·국소화 메타데이터를 둘 수 있다.

`cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 통과했다. 전체 **285 통과·0 실패·22 ignored**, 그중 기록 통합 32·집계 통합 29·legacy 단위 4개다. 이번에 집계 29개와 importer 회귀 16개를 추가했다. 기존 ignored 실제 산출물/설치 도구 검사는 실행하지 않았다. [기록 코드 검토](../reports/n4-1-record-code-review-2026-10-01/REVIEW.md)와 [계약 검토](../reports/n4-1-review-contract-2026-10-01/REVIEW.md)는 보존했으며, [의견별 반영](evidence_aggregate_v1.md#5-코드-검토-반영)에 F1–F13의 수정·범위 제한을 남겼다. 회로·후보·witness·predicate 참조를 열거나 실행하지 않았으며 반복 실행기·새 후보 생성은 추가하지 않았다.

이후 [독립 검증](../reports/n4-1-aggregate-verification-2026-10-01/REVIEW.md)이 재현한 오프라인 집계 오류 N1–N7을 수정했다. 위치·바뀐 규칙·수정 전후 결과·회귀 테스트는 [수정 기록](evidence_aggregate_v1.md#6-독립-검증-오류-수정)에 있다. 수정 후 `cargo test`는 **297 통과·0 실패·22 ignored**다. 오프라인 구조 수정이며 N4-1 의미 관문 통과가 아니다.

**N4-1 전체 관문은 미통과, N4-2는 미착수다.** 구조 관문에는 실제 수집 경로의 완전성·후보별 시간·원인 등록 근거 연결, A안 반복/종료/잔여 및 실제 자원 계측이 남는다. 의미 관문에는 통째·분할 후보의 같은 수준 정상/abort 검토·원인 귀속, 투영·wrapper 대응, 하네스 시간 기준 및 공정성 입증이 남는다. 이번 구조 테스트가 이를 대신하지 않는다. N5는 미고정이고 평가 후보 퍼징은 금지다.

### N4-1 정상 개발 실행 결과

[실행 보고서](../reports/n4-1-normal-execution-2026-10-01/REPORT.md)와 [값 없는 근거](../reports/n4-1-normal-execution-2026-10-01/evidence.json)에 실제 결과를 남겼다. 기존 정상 discovery fixture와 작은 산술 통제를 각각 미재사용/재사용 2회씩 순서를 바꿔 실행했다. 원본과 자동 wrapper의 실제 컴파일 **52/52 성공**, 정상 witness 제약 검사 **168/168 통과**, 확인된 원본 경계와 wrapper 입출력 비교 **144/144 일치**다. 원시 산출물은 ignored `runs/`에 있고 당시 오류가 알려진 `experiment aggregate`는 사용하지 않았다.

원본 포함 컴파일 횟수는 각 방식 2회 합계로 기존 fixture **16→16**, 산술 통제 **12→8**이다. 준비 wall 1회 평균은 각각 **0.157419→0.150831초**, **0.130137→0.078667초**다. 같은 현행 자동 탐색 뒤 artifact 컴파일 재사용 유무를 비교했으며 OS 캐시는 비우지 않았다. 정상 계산·제약/경계 검사 비용은 별도 보고한다. 세 정상 입력의 관측으로 탐지 우위·일반 의미 동등성·통계적 속도 우위를 주장하지 않는다.

후속 [비용 재계산](../reports/research-checkpoint-2026-10-01/REPORT.md#3-ne-03-비용-재계산과-해석)은 산술 통제의 준비 감소 약 39.55%와 준비+정상 검증의 측정 구간 합계 7.692001→7.778089초를 함께 기록했다. 준비 개선을 전체 처리시간 개선으로 확대하지 않는다. 조건·분모·허용 주장·한계는 [논문 근거 색인](paper_evidence_index.md)에 연결한다.

측정 스크립트와 경계 매핑 테스트 4개를 추가했다. fmt 검사·지정 clippy·cargo test(285 통과·22 ignored)와 Python 테스트 4개가 통과했다. 기록·집계 소스/테스트/문서는 수정하지 않았다. **정상 계산 연결은 확인했지만 N4-1 전체와 A안 실행 검증은 미완료**이며, 같은 수준 판정·원인 귀속·일반 대응·abort/전제·자원/종료 공정성은 남는다.

### N3의 범위 결정 원칙

- 독립 사례가 적으면 주장 범위를 사례연구·적용성 분석으로 줄인다. 종전의 “원인 5개·프로젝트 3개”는 계획상 목표였으며 통계적 충분성이나 논문 성립을 보장하지 않는다.
- 수치를 맞추기 위해 성공 사례만 추가하거나 포함 조건을 사후 완화하지 않는다. 공개 탐지 결과는 진단층으로 사용하고 주 집합 선정 근거와 분리한다.
- 준비 실패, 미지원, 시간 초과, 미판정을 숨기지 않는다. 전체 사전 대상 모수와 분석 가능한 부분집합을 모두 보고한다.
- 전체 회로와 분해의 비교에 동일한 증거 기준을 적용한다. 컴포넌트 결과와 프로젝트 결과를 합쳐 우위를 주장하지 않는다.
- 컴파일러 산출물을 이용하는 방향은 검토할 수 있으나, 완전한 복원이 가능하다고 전제하지 않는다. 원본 의미·인스턴스·최적화 대응과 유지 비용을 보고 최소 변경을 선택한다.

## 5. 아직 고정하지 않은 것

초기 평가 대상 목록과 포함 규칙·노출층, 단위 생성/중복 제거·준비 실패 처리, 계열·entrypoint 역할·root 처리 규칙, RQ1 기본 순서, 보조 전략 수, 총예산·타깃별 제한, seed 수, 실행 순서·동시성, 캐시·비용 범위, 맥락 후보배제·검토/표본 규칙은 **N5 전까지 미고정**이다. 준비로만 확인되는 실제 단위·설정·산출물은 고정한 생성 규칙에 따라 이후 기록할 수 있으나 성공한 대상만 남길 수 없다. 600초·30초·seed 3개를 이전 파일럿에서 자동으로 상속하지 않는다.

주 지표의 구조와 공정성 요구는 [평가 계획](evaluation_plan_2026-10-01.md)에 적었다. 이 계획이나 인계 프롬프트를 고정 프로토콜로 해석하지 않는다.

같은 수준 확인 여부·최초 확인 대상 시간·고유 원인 수, 종료/잔여 예산, 대칭 검토, 후보 배제·전제·abort 규칙도 N3 결정과 N5 고정을 구분한다. 현재 [N5 고정안](scope_decision_final_2026-10-01.md#5-n5-고정-방식과-평가층)은 로컬 버전 문서·대상 목록·도구/파일 해시·miiz 결정 기록을 사용하며 새 git commit을 요구하지 않는다. 과거 준비 이력은 별도 층으로 보존한다. 종료 정책의 연구 권고와 향후 구현·검증을 구분하고 실제 사용 자원을 같다고 가정하지 않는다.

## 6. 기존 작업과의 관계

| 이전 작업 | 현재 처리 |
|---|---|
| T1, T2a, T2b, v1~v3, P1, P2 | 과거 조사·실행·판정 보존. 새 계획의 편의에 맞게 재분류하거나 덮어쓰지 않음 |
| T4b·T4c·T5·T6a | 기존 구현 자산 유지. 재사용 범위와 한계를 N4에서 명시 |
| B1~B3, T3, T7 | 이전 계획의 대기 작업은 보류 유지. 새 평가 절차는 N3~N7로 관리 |
| T6 | 기존 미개봉 풀을 자동으로 열지 않음. 추가 자료가 필요하면 N3에서 범위를 기록 |
| T8 및 09-27 계획의 다중 도구 확장 | 보류 |
| 09-27 R1~R5 | 새 작업 N1~N7로 대체. 위치 일치 성공 판정과 RQ2 핵심 기여 방침은 현재 계획에 적용하지 않음 |

로컬 파일만 수정한다. 과거 문서의 커밋·업로드·PR 관련 작업 지시보다 현재 AGENTS.md의 금지 규칙이 우선한다. 원시 후보·witness·컴파일 산출물은 ignored `runs/`에 보존하고, 공유 문서에는 값 없는 식별자·경로·해시·판정·시간만 둔다. 코드 변경 시 `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`를 실행한다.

## 7. 진행 표

D0–D5의 메모는 각 작업 완료 당시 기록이다. 현재 상태와 다음 범위 결정은 N4 행을 따른다.

| ID | 상태 | 담당 | 다음 행동 |
|---|---|---|---|
| LIC-01 | 완료 — 저장소에 포함된 제3자 코드의 출처·라이선스 정리 (2026-10-06 시작·완료) | miiz | [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)·`third_party/licenses/`(고정 리비전 기준 원문 6개). git 추적 `.circom` 558개 중 제3자 출처는 circomlib(파일 머리 GPL-3.0), tangle(MIT/Apache-2.0), Banyan·Unirep·zkbugs(MIT), circom-bigint(GPL-3.0)이다. **라이선스가 없는 저장소 2개**(inference `subnet-2-circom`, `circom-chacha20`)의 사본은 비공개 검토용으로만 두고, 공개 산출물에서는 저장소·커밋 해시로만 가리킨다. README에 License 절 추가. 고정된 datasets·reports 폴더는 수정하지 않음 |
| N6-B1 | 진행 중 — 검수 보정: 전체 사전 점검 분리·대기열 상태기 보완 (2026-10-06 재개, 기한 2026-10-07) | miiz | v1/v2·대상·예산·seed·순서 원칙을 보존한 채 `preflight-all` 선행 관문, W 사전 점검 실패 시 S 유지, RSS 1초 측정, 큰 회로 비차단 스케줄링, 사전 점검 산출물 기록·정리를 구현·재검증 중. B 퍼징은 시작하지 않음 |
| E-02 | 완료 — 측정·검수 보완 (2026-10-06, 기한 2026-10-08) | miiz | [결과](e02_production_mains_results_2026-10-05.md)·[JSON](e02_production_mains_results_2026-10-05.json). 329개 역할 분모(배포 main 177·test/mock 152), 새 원본 compile 성공 100개, 준비 101개 측정·제약 10만 이상 배포 main 90개 개별 보고. 원본 옵션은 E-01과 같은 기본 O1이며 절차 O0는 표기 오류로 명시. 120/600초 compile·300/900초 prepare와 실제 준비 상태를 분리하고 host load·필수 검사 중첩을 기록. 검증된 생성 산출물만 원장 기록 후 정리, 캡처 확인 부족 1개는 전체 보존. 공유 JSON 절대 경로 2,591개를 상대화하고 생성 시 잔존 차단. discovery timeout 33건의 캡처 시간·wrapper 수, partial 55건 조각 유효 비율(중앙 97.674%·최소 84.068%·최대 100%)·root 실패 50/55 추가. 검수 보완 Python 24건·fmt·지정 clippy·cargo test(348 통과·22 ignored) 통과·zkFuzz 0회. 구조 준비 조사이며 N4-1 전체·N5 완료 아님 |
| M-01 | 완료 — E-01 컴파일 성공 entrypoint를 F-01 고정 탐색기로 재측정 (2026-10-03 시작·2026-10-05 완료, 기한 2026-10-05) | miiz | [결과](m01_discovery_results_2026-10-03.md)·[JSON](m01_discovery_results_2026-10-03.json). E-01 원본 컴파일 성공 125개(10만 제약 이상 49개) 전부 같은 최종 F-01 고정 바이너리로 instance capture 포함 탐색·준비·plan 재측정. discovery·compiler capture 125/125 완전, 준비 success 97·partial 22·failed 6; 대형은 success 24·partial 20·failed 5. setup·원본 compile은 재사용하고 zkFuzz 0회. 컴파일 산출물과 보호 경로 밖 진단 사본 25,033개·32,673,355,992바이트를 manifest 후 삭제, 삭제 가능 잔존 0; `node_modules` 사본은 보존. Python 5건·결과/정리 검사·cargo fmt·지정 clippy·cargo test(344 통과·22 ignored) 통과. 구조적 준비 결과이며 결함 탐지·의미 동등성 근거 아님 |
| E-01 | 완료 — C-03 production setup 실패 저장소 자동 환경 구성 확장 (2026-10-03 시작·완료, 기한 2026-10-07) | miiz | [결과](e01_setup_results_2026-10-03.md)·[JSON](e01_setup_results_2026-10-03.json)·[사전 절차](e01_setup_procedure_2026-10-03.md). 동일 commit·entrypoint 9 repo/329개 전부 재측정: setup 0/9→6/9, compile 성공 6/329→125/329(timeout 17·failure 187), 준비 success 18·partial 123·unsupported 19·failed 169. 성공 컴파일 기준 10만 제약 이상 49개. Celo lock 불일치·selfxyz 인증·Stealthdrop 외부 artifact 부재를 자동 setup 실패로 보존. 산출물 2,361개·21,342,872,854바이트 manifest 후 삭제. Python 회귀 3건·결과/잔존 검사·cargo fmt·지정 clippy·cargo test 통과. zkFuzz 0회; C-03 고정 결과 보존 |
| D7 | 완료 — 졸업프로젝트 등록용 제목과 소개문 갱신 (2026-10-02 시작·완료) | miiz | [등록용 문안](capstone_introduction_v1_2026-10-02.md): 후속 설계 논의의 자동 분해→전체 회로 맥락 확인, 자동 검증을 핵심 기여로 발전시키는 방향과 다섯 판정 구분을 반영. 구현·제한된 개발 관측·향후 평가를 구분하고 로컬 링크 확인. 소개문만 갱신했으며 코드·실험·외부 등록 화면 변경 없음 |
| C-03 | 완료 — 환경 구성·설정 entrypoint 포함 재측정 (2026-10-02 시작·2026-10-03 완료, 기한 2026-10-07) | miiz | [결과](c03_corpus_results_2026-10-02.md)·[JSON](c03_corpus_results_2026-10-02.json)·[사전 절차](c03_corpus_procedure_2026-10-02.md). 80 repo(주 조건 75, team_curated 14; 출처 중복)·설치 후 3,677 entrypoint. 동일 entrypoint paired compile 2,308/3,629→2,470/3,629, setup 60/80 성공, 완전 자동 준비 881/3,677(partial 832·unsupported 775·failed 1,189), config_generated 42. production 10만 제약 이상 25개와 실패·목록 결측·중단 이력 보존. cargo fmt·지정 clippy·cargo test(333 통과·22 ignored)·C-03 메타데이터 검사 213 통과. 고정 driver zkFuzz 0회; 구조 준비 조사이며 N4-1 전체·N5는 미완료 |
| C-02 | 완료 — complete_known_inventory (2026-10-02, 기한 2026-10-10) | miiz | [결과](c02_corpus_results_2026-10-02.md)·[JSON](c02_corpus_results_2026-10-02.json). 239 repo: 포함 65·제외 168·미확정 6; 확인된 main 3,470파일 모두 기록, 포함 inventory 불완전 10 repo의 추가 main 수 unknown. 원본 컴파일 2296/3470, 완전 자동 준비 845/3470 (root-only 448, ≥1조각 397). [fmt/clippy/cargo test](../runs/c02-corpus-2026-10-02/checks-final/checks.json) 316 통과·22 ignored, [메타데이터·축약 검사](../runs/c02-corpus-2026-10-02/checks-final/python_c02_tests.log) 49 통과. zkFuzz 0회; N4-1 전체·N5 미완료 유지 |
| LF-02 | 완료 — 새 fixture 5종·진위 검사·엔진 결과 구분 (2026-10-02 시작·완료, 기한 2026-10-06) | miiz | [fixture와 판정 근거](../tests/fixtures/lifting/README.md): 기존 O1 파일 보존, 호출 부재·bus 입력 식별 미지원의 실제 준비 실패 확인. 선형·bit 역산은 엔진 위반 확인, 8비트 범위 밖 중간값은 독립 원본 제약 증명상 배제이나 엔진은 unknown(PENDING). 신규 O0 컴파일 10조건·후보/정상 대조 각 5/5, 후속 진위 8개·기존 14개 통과. 전체 엔진 요청 18건 중 목표 일치 17·PENDING 1. fmt·지정 clippy·cargo test(315 통과·22 ignored) 통과. 비이탈 대조 및 기존 ToyHash의 역산 지원 기대값은 새 버전으로 기록. 엔진 기능·L-02 전체·N4/N5 완료 선언 아님 |
| LF-01 | 완료 — 합성 fixture 5종·독립 진위 검사 (2026-10-02 시작·완료) | miiz | [fixture와 한계](../tests/fixtures/lifting/README.md): Circom 2.2.3 기본 10조건 및 O0 준비 대조 1조건 컴파일, 후보 5/5 전체 R1CS 만족·동일 입력 정직 계산과 차이, 정상 대조 5/5 확인. fixture 회귀 14개·fmt·지정 clippy·cargo test(304 통과·22 ignored) 통과. 첫 4종 request-v1 연결 자료 작성; O1 준비 실패는 형식이 옵션을 지원하지 않아 별도 검사로 보존. 자동 승격 엔진의 통과 판정은 아니며 N4-1 전체·N5 상태 유지 |
| D5 | 완료 — A-01 인계 준비 (2026-10-02) | miiz | [A-01 공통 실행·계측 인계](next_policy_a_handoff_2026-10-02.md): NB-01 사전 기준과 구현을 제한적으로 대조하고, 동일 예산·종료·실사용 계측 및 기존 P2 `inference-main` 결함 개발 사례 한 쌍을 다음 단계로 정함. P2 `Subtract` 후보 하나의 독립 의미 검토를 병렬로 지정. 새 코드·실험은 미착수 |
| D6 | 완료 — 실제 엔진·두 번째 후보 인계 (2026-10-02) | miiz | [A-02/S-02 인계](next_engine_clamp_handoff_2026-10-02.md): A-01 부분 완료·S-01 검토를 반영하고, 통째 30초 강제 재시작의 비교 편향을 바로잡아 실제 P2 한 쌍과 `Clamp` 후보 층별 검토를 각각 준비. 새 코드·실행 없음 |
| A-01 | 부분 완료 — 모델·한정 계측 검증, 실제 엔진 미실행 (2026-10-02) | miiz | [결과](../reports/n4-1-policy-a-2026-10-02/REPORT.md)·[SCOPE](../reports/n4-1-policy-a-2026-10-02/SCOPE.md): 예산 모델 회귀 10개·NB 독립성 회귀 1개 및 필수 검사 통과. 실제 결함 반복 생성용 엔진 연결/실행은 수행하지 않아 통째 1·분할 21 모두 미시작. A-01 전체 미완료 |
| A-02 | 완료 — 실제 공통 엔진 개발 캠페인 한 쌍 (2026-10-02 시작·완료) | miiz | [결과](../reports/n4-1-policy-a-engine-2026-10-02/REPORT.md)·[SCOPE](../reports/n4-1-policy-a-engine-2026-10-02/SCOPE.md)·[보정된 값 없는 근거](../reports/n4-1-policy-a-engine-2026-10-02/evidence-v2.json)·[후속 31건 연결표](a02_review_status.md): 같은 상태기로 P2 `inference-main` 통째 1/1과 small-first 21/21을 각각 600초 실제 실행. 통째 1회 timeout·후보 0, 분할 67회(candidate 신호 31·no-candidate 17·timeout 19). 실행 당시 모두 미검토였고 후속 S-04·S-05에서 두 건의 컴포넌트 TCCT를 확인했다. v1 phase 필드는 parent의 `Popen` 반환·`wait4` 관측 경계이며 OS 내부 시작시각이 아님을 보정하고 원본·v1을 보존. A-02 당시 필수 검사 통과. N4-1 전체·N5는 미완료 |
| S-01 | 완료 — P2 한 후보 의미 검토 (2026-10-02) | miiz | [사전 SCOPE](../reports/n4-1-p2-candidate-review-2026-10-02/SCOPE.md)·[결과](../reports/n4-1-p2-candidate-review-2026-10-02/REPORT.md): 지정 `Subtract` 후보 1개가 원본 제약 전체 만족·정직한 계산과 출력 차이·일반 TCCT 속성 위반·수정 제약 거부로 알려진 원인에 귀속. 호출 맥락·entrypoint·프로젝트 층은 미판정. v1.1과 같은 원인·R1CS라 새 고유 원인이 아니며, 통째 후보가 없어 같은 수준 양쪽 비교 아님 |
| S-02 | 완료 — P2 `Clamp` 한 후보 의미 검토 (2026-10-02) | miiz | [사전 SCOPE](../reports/n4-1-p2-clamp-review-2026-10-02/SCOPE.md)·[결과](../reports/n4-1-p2-clamp-review-2026-10-02/REPORT.md): 지정 후보는 원본 제약을 만족하지만 정직한 계산과 모든 wire가 같아 **일반 TCCT 위반 아님**(주 비교 원인 수 제외). `val`의 40비트 범위 밖·의도 순서와 다른 출력은 범위/명세 관측. 수정 commit 출처는 git object chain으로 확인했으나 그 소스가 circom 2.2.3에서 T3001로 컴파일되지 않아 수정본 거부·귀속은 미판정. zkFuzz 라벨 `UnderConstrained-UnexpectedInput`은 근거로 쓰지 않음 |
| S-03 | 부분 완료 — 31건 메타데이터 검산 완료·의미 검토 미수행 (2026-10-02 시작·종료) | miiz | [결과](../reports/n4-1-a02-first-occurrence-metadata-2026-10-02/REPORT.md)·[범위](../reports/n4-1-a02-first-occurrence-metadata-2026-10-02/SCOPE.md)·[인벤토리](../reports/n4-1-a02-first-occurrence-metadata-2026-10-02/occurrence-inventory-v1.json): attempt 1의 지정 `Subtract()`가 ledger상 최초 관측임을 검산(1.108243333초 / 완료 상한 1.117240042초). 후보 값 미개봉, 실제 결함 후보 재현·검증은 수행 제한으로 미수행; 원본 R1CS·정직한 계산·귀속·entrypoint 모두 미판정. 지정 1건 및 나머지 30건은 이 작업에서 의미 미검토. 전체 S-03 미완료 |
| S-04 | 완료 — A-02 둘째 후보 `IntDiv(40)` 의미 검토 (2026-10-02 시작·종료) | miiz | [사전 SCOPE](../reports/n4-1-a02-intdiv-review-2026-10-02/SCOPE.md)·[결과](../reports/n4-1-a02-intdiv-review-2026-10-02/REPORT.md): 원시 ledger로 parent `NOT SAFE` 관측순 둘째(앞선 것은 attempt 1뿐)·경로·해시·시각을 독립 확인. 원본 제약 46개를 두 방법으로 모두 만족하고 같은 입력의 정직한 계산과 `main.out`만 달라 **컴포넌트 일반 TCCT 위반(출력 차이형)**. 출처를 확인한 수정본은 `out = quot`와 `quot` 40비트 범위 검사 두 조건으로 동시에 거부하고 같은 입력의 수정본 정직 계산도 중단돼, 사전 규칙상 **단일 원인 귀속은 미판정**. S-03 의미 검토가 없어 최초 확인 시간은 확정하지 않음. S-01과 합치거나 새 고유 원인으로 세지 않음. zkFuzz 라벨은 근거 아님. 호출 맥락·entrypoint·프로젝트 미판정 |
| S-05 | 완료 — A-02 첫 후보 `Subtract()` 의미·호출 맥락 검토 (2026-10-02 시작·종료) | miiz | [사전 SCOPE](../reports/n4-1-a02-first-semantic-review-2026-10-02/SCOPE.md)·[결과](../reports/n4-1-a02-first-semantic-review-2026-10-02/REPORT.md): attempt 1 후보가 컴포넌트 일반 TCCT를 위반하고 `Subtract`의 무제약 승수에 귀속됐다. S-01과 같은 witness·site 원인이라 새 고유 원인·독립 사례가 아니다. K1·K2의 고정 두 입력에서 사후 구성한 전체 witness가 entrypoint 제약을 만족하며 출력 차이를 보여 **entrypoint TCCT 위반**이 확인됐다(프로젝트 의미 미판정). 사후 확인된 첫 후보의 parent 경고 관측은 1.108243333초, 파일 존재 상한은 1.117240042초다. 원문의 1.103817667초는 OS 시작·생성시각 하한이 아니므로 [TIME-01 정정](a02_review_status.md#시간-정정-time-01)에 따라 하한 unknown. 31건 중 29건 미검토. 새 Python 코드 두 개에 대한 AGENTS.md 필수 검사 완료 근거는 아직 없다 |
| C-01 | 부분 완료 — 기존 정상 경계 회귀 16개 통과, production 매핑 미수행 (2026-10-02 시작·종료) | miiz | [결과](../reports/c01-normal-boundary-readiness-2026-10-02/REPORT.md)·[부분 범위](../reports/c01-normal-boundary-readiness-2026-10-02/SCOPE.md): NB-01 코드·회귀의 지원 범위만 확인. 알려진 후보의 production 투영에 연결되는 대상별 호출·신호 매핑은 수행 제한으로 미구현. 실제 전체 호출 분모·정상 자료 가용성 unknown, 정상 비교 not_run. 후보/S-05 미접근, C-01 전체 미완료 |
| L-01 | 완료 — 자동 맥락 확인 가능성 1차 판정, 관문 조건부 통과 (2026-10-02 시작·종료, 기한 2026-10-09) | miiz | [기준](lifting_feasibility_2026-10-02.md)·[결과표](lifting_feasibility_results_2026-10-02.md)·[근거 JSON](lifting_feasibility_evidence_2026-10-02.json): 구조 기반 `experiment lift`로 S-05 K1–K5를 후보별 규칙 없이 재현(K1·K2 entrypoint_violation). S-04는 5 class unknown(중간값 입력)·1 excluded. LF-01 fixture 요청 8/8 일치, `preparation_failure` fixture는 O0 대응 설계와 전제가 맞지 않아 교체 필요(5/5 미충족). A-02 31건 모두 처리(class 62: violation 8·excluded 22·unknown 32), 후보당 최대 7.9초. 원인 귀속 아님. 필수 검사 통과(Rust 306 통과·22 ignored) |
| L-02 | 완료 — 역방향 입력 합성 1차와 L-01 보완 (2026-10-02 시작·종료, 기한 2026-10-12) | miiz | [결과](lifting_synthesis_results_2026-10-02.md)·[근거 JSON](lifting_synthesis_evidence_2026-10-02.json): 보완 3건(반증은 직접 묶인 입력일 때만 배제·`reference_input_refuted` 분리, 상수 배제 17건 모두 O0 기준 명시, 비이탈 후보 `not_tcct_deviation` 분리) 반영. (a) 구체 역전파·(b) z3 국소 풀이·(c) L-01 경로 재검증 구현. A-02 TCCT 이탈 13건 class 44: violation 8→9·excluded 17·unknown 19→18(미판정 43.2→40.9%), 18건은 not_tcct_deviation. (b) 후보당 최대 0.5초. 두 번째 자료 Banyan 36·zk-email 9는 모두 not_tcct_deviation, Decoder는 Multiplexer 호출자 맥락에서 excluded(L-03 결정 2: 메커니즘 시연, 프로젝트 근거 아님). fixture 17 일치·1 PENDING(`range_unreachable` 승격 여부 miiz 결정). 원인 귀속 아님. 필수 검사 통과(Rust 316 통과·22 ignored) |
| L-03 | 완료 — 입력 가정 위반 후보의 맥락 도달성, 닫힌 원뿔 UNSAT 승격 (2026-10-02 시작·종료, 기한 2026-10-09) | miiz | [결과](lifting_assumption_results_2026-10-02.md)·[근거 JSON](lifting_assumption_evidence_2026-10-02.json): 결정 1(후보 위치 입력·직접 바인딩만 고정한 원뿔의 z3 unsat → excluded, O0 기준·제약 index·고정 wire·방법 기록, range fixture 통과, 범위 안 200 반대 대조 회귀)·결정 2(Decoder 메커니즘 시연) 반영. 사람 정답 대조: Banyan 36/36 assumption_input_reachable(정답 실제 결함과 일치), zk-email 9/9 excluded_in_context(정답 맥락 오탐과 일치, RSAPad Num2Bits 근거). A-02: TCCT 13건 class 44 violation 9·excluded 17·unknown 18, 입력 가정 18건 reachable 0·excluded 6·unknown 12. abort 제약 34·assert 0. **중단 기준 해당:** A-02 (b) 후보당 60초 초과 3/31(IntDiv(40)), 가지 원뿔 탐색 예산 소진이 원인, 미조정 보고. 필수 검사 통과(Rust 318 통과·22 ignored) |
| L-04 | 완료 — 배제 탐색 예산·비트 분해 범위·hint 주입 구현, 위반 조건 대응(1·2단계)과 zk-email 서비스 entrypoint(5단계)는 막힘 (2026-10-02 시작, 2026-10-03 종료, 기한 2026-10-07) | miiz | [결과](lifting_l04_results_2026-10-03.md)·[근거 JSON](lifting_l04_evidence_2026-10-03.json): 0) 후보당 배제 탐색 20초 상한. A-02 판정 1건 변화(#27 excluded→unknown `budget_exhausted`), A-02 비용 합계 1034.7→500.3초·요청당 최대 168.7→39.5초, 상한 소진 14/31(과반 아님). 1) zkFuzz `pos`는 저장되지 않는 내부 `symbolic_trace` index라 대응 불가 → 2) 생략. 가정 술어 판정·결과 위반 관측은 모두 not_evaluated. 3) 비트 분해 구간 전파(선행 연구 CCC-Check). zk-email 9/9·range fixture가 이 방법으로 배제. A-02 제약 abort 22건은 변화 없음(IntDiv hint에서 전파 중단, 인스턴스 특정 0/22). 4) hint 주입. 모델 재현 실패 8건 중 `DistanceFromScore` 3건 assumption_input_reachable(두 검사기 통과), 5건은 주입 생성기가 범위 검사 제약에서 중단. 5) 같은 리비전 zk-email에 서비스 main 없음(`component main` 12개 모두 tests/test-circuits). 임의 호출자·의존성 설치 없이 중단. Banyan 36/36 reachable(결과 위반 미평가). A-02 미판정 class 30→28. 후보·프로젝트별 규칙 없음. 원인 귀속 아님. 필수 검사 통과(Rust 324 통과·22 ignored, fixture 18/18 일치) |
| F-01 | 완료 — 대상 탐색 적용성 개선: 컴파일러 산출물(진단 사본 O0 R1CS)로 템플릿 인스턴스 인자 캡처 (2026-10-03 시작·종료, 기한 2026-10-07) | miiz | [결과](f01_discovery_results_2026-10-03.md)·[근거 JSON](f01_discovery_evidence_2026-10-03.json). C-03 1,493 entrypoint(production 656 + 준비 성공 881) 발견·준비만 재실행. production 자동 준비 성공 44 → 107(미지원 58 → 0), 컴파일 성공 174 캡처 174/174 완전. 큰 회로 25개 성공 1 → 6·부분 10 → 16·미지원 13 → 0·실패 1 → 3(3건 준비 300초 상한). 회귀 881 중 880 키·조각 동일, 불일치 1건(`Sign`, C-03 해석기가 `/`를 정수 나눗셈으로 계산; F-01 값이 맞음). 측정 중 찾은 `var` 선언 범위 결함은 고친 바이너리로 6건 보충 측정(6/6 동일). 중립성 대표 8개 회로 동일. 진단 O0 컴파일은 원본 O1의 중앙값 1.94배. 남은 사유는 래퍼 생성 한계(템플릿 파일 include 43, 태그 main 입력 34)와 시간 상한. 컴파일 산출물 23,884개(16.9 GB)와 진단 사본 1,520 트리(1,391,441 파일·508,505 링크, 41.7 GB; 캡처 값 보존 확인·재생성 4건 일치)를 기록 후 삭제. 새 zkFuzz 실행 0회, 프로젝트·템플릿별 특수 규칙 없음. 필수 검사 통과(Rust 343 통과·22 ignored) |
| L-05 | 완료 — 깨진 조건 복원·가정 술어 판정·실패 인스턴스 특정·DistanceFromScore 확인·실행기 조건 문자열 연결 (2026-10-03 시작·종료, 기한 2026-10-06) | miiz | [결과](lifting_l05_results_2026-10-03.md)·[근거 JSON](lifting_l05_evidence_2026-10-03.json). 1) 입력 가정 후보 63건 모두 `LessThan` 정수 비교 조건이 깨짐, zk-email 로그 조건 9/9 일치. zkFuzz `pos`는 첫 실패가 아니라 **마지막** 실패 원소. 2) 가정 술어: Banyan 36/36 `assumption_violation_reachable`, zk-email 9/9 `assumption_excluded_in_context`(69 인스턴스, z3+범위 사실), A-02 18건 도달 17·미판정 1. 후보 값과 다른 경우 6건. 3) 진단 사본(검사 공백 처리)으로 실패 인스턴스 27/28 특정, 수리로 10 클래스 판정 변화, A-02 미판정 class 28→18. IntDiv 제수 0은 wasm이 위치 없이 멈춰 2건 막힘. 허브 입력 TCCT 14건 미수렴. A-02 도달은 알려진 `IntDiv.out` 무제약 hint 주입에 의존. 4) DistanceFromScore 3건: 반사실에서 2건 `new_score[0]` 변화, 1건 무변화(`verified = 0`). 수정본이 3건 거부. zkbugs 항목 위치가 아니므로 알려진 목록에 없는 후보로만 표시(수정은 `79f42ee`). 5) `--save_output`과 보고서가 배타적임을 확인. v1 고정, v2 래퍼·파서 추가(실행 없음). 새 zkFuzz 실행 0회. 필수 검사 통과(Rust 333 통과·22 ignored) |
| L-06 | 완료 — IntDiv 의존 분리·수정 커밋 대조·수리 컴파일 캐시 (2026-10-03 시작·2026-10-05 완료, 기한 2026-10-06) | miiz | [결과](lifting_l06_results_2026-10-05.md)·[근거 JSON](lifting_l06_evidence_2026-10-05.json). IntDiv만 고친 커밋은 없어 원본+`9221e8d` IntDiv 변경 패치(R_intdiv) 사용. Clamp 수정은 `771c61c`(지시의 `79f42ee`는 DistanceFromScore 수정; `771c61c`는 circom 2.2.3 컴파일 불가라 `024227f` 순서 수정만 얹음). Clamp 3·CalculatedScoreFraction 2의 L-05 도달은 모두 IntDiv.out hint 주입 의존 → R_intdiv부터 미판정. 소스 수동 증명: IntDiv 수정 시 Clamp.LessThan[0] 위반 불가(IntDiv에 연쇄된 결함). DistanceFromScore #13은 R_intdiv·Subtract+IntDiv 수정·PR 전체−DFS(leave-one-out)에서 hint 없이 도달(두 검사기), 원본 정직 생성기에서도 같은 입력으로 깨짐(snarkjs 통과) — 단 공개 입력(previous_score·maximum_score) 변경 필요. 수정본 도달 0. 엔진 한계: 같은 인스턴스 술어 판정이 후보마다 다름, 수정본에서 술어 판정 누락. 수리 컴파일 캐시: A-02 31건 판정 L-05와 31/31 동일, 컴파일 811→197초(동시 부하로 벽시계 비교 불가). 컴파일 산출물 1,054개(27.2 GB) 기록 후 삭제. 새 zkFuzz 실행 0회. 필수 검사 통과(Rust 344 통과·22 ignored) |
| L-07 | 완료 — 가정 술어를 (entrypoint, 인스턴스) 단위로 판정 (2026-10-05 시작·2026-10-06 완료, 기한 2026-10-08) | miiz | [결과](lifting_l07_results_2026-10-06.md)·[근거 JSON](lifting_l07_evidence_2026-10-06.json). 인스턴스 저장소(`--instance-store`)와 순서 무관 합치기(`experiment lift-instances`), 후보 없는 술어 판정(컴포넌트 `LessThan` 전부), 도달 근거 공개/사설 분류, bit 분해 범위의 선형 전파(CCC-Check 선행, 기여 아님), hint entrypoint 컴파일 캐시. 141회 판정 충돌 0. A-02 31·Banyan 36·zk-email 9 클래스 판정 L-05와 변화 0. inference 리비전 행렬 변화 52건 전부 미판정/없음 → 도달·배제: DistanceFromScore `positive`는 미수정 리비전 모두 도달(공개 입력)·수정 리비전 모두 배제, Clamp `LessThan[0]`은 원본만 도달(IntDiv hint, 사설만)·IntDiv 수정 리비전 모두 배제(loo_clamp 포함; L-06 수동 증명을 엔진이 확인). Banyan 실제 결함 2 인스턴스는 사설만으로 도달. 새 zkFuzz 실행 0회. 필수 검사 통과(Rust 348 통과·22 ignored) |
| D4 | 완료 (2026-10-02) | miiz | [다음 한 단계와 인계](next_step_handoff_2026-10-02.md): NC-01 완료 확인·현재 안내 동기화. 기존 O0 정상 자료의 입력 연결 자동화와 제한된 사전 수용 기준을 역할별로 정리. 새 구현·실험은 미착수 |
| D0 | 완료 (2026-10-01) | miiz | 목표·계획·평가 설계·인계 프롬프트 및 현재 문서 링크 갱신. 독립 문구 검토·로컬 링크 점검 완료. 코드·실험 실행 없음 |
| D1 | 완료 (2026-10-01) | miiz | [논문 근거 색인](paper_evidence_index.md)·[체크포인트](../reports/research-checkpoint-2026-10-01/REPORT.md)에 정상 실측·비용 재계산·집계 수정과 주장 한계를 연결. 다음 정상 호환성 인계 준비 완료·미착수. 문서 링크·산술·보존 해시 확인; 코드 변경·새 실험 없음 |
| D3 | 완료 (2026-10-01) | miiz | [기여 위치와 공개 준비](contribution_position_2026-10-01.md): 문헌 확인 범위·기술 문제/설계/근거 연결·현 기여의 한계 기록. 인계 제목 중립화 및 고정 정상 실행의 별도 공유판 작성. 원본 해시·수치·링크 확인. D2·NC-01 진행 중이므로 전체 작업 트리 업로드 준비 완료는 아님 |
| D2 | 완료 — 논문 본문 초안 v1 (2026-10-01 시작, 2026-10-02 완료) | miiz | [본문 초안 v1](paper_draft_system_evaluation_v1.md): 설계·평가 방법·예비 결과·선행과 한계, 주장-근거-제한 표, 남은 질문 3개, 근거 SHA-256. NC-01은 결과 대기로 둠. 새 실험·코드 실행 없음. N5 고정·N7 분석 착수 아님 |
| N1 | 완료 (2026-10-01) | miiz | [감사 보고서](../reports/sok-artifact-audit-2026-10-01/REPORT.md)·70건 근거 JSON 작성. 공통 56건 10/1/3/42 검산, 노출 이력·계열·설정 불일치와 unknown 기록. N3 채택 기록의 근거로 보존. N1에서 코드·실험 실행 없음 |
| N2 | 완료 (2026-10-01, 보고서 상태 확인) | miiz | [방법론 검토](../reports/methodology-review-2026-10-01/REVIEW.md) 보존. 8편 검토(CIVER 본문 미접근, README·2차 자료). 결정용 기록에 권고 해석 반영. 코드·실험 실행 없음 |
| N3 | 완료 — miiz 결정 기록 완료 (2026-10-01) | miiz | [채택 기록](scope_decision_accepted_2026-10-01.md): 보정 범위·주장·고정 방식, A안 우선, 순서·작업 상한과 이번 N4-1 착수 범위. 버전·날짜·참조 SHA-256 보존 |
| N4 | 진행 중 — A-02·S-04·S-05 개발 실행/검토 반영, N4-1 전체 미완료 (2026-10-02) | miiz | [현재 31건 연결표](a02_review_status.md): 통째 1/1·분할 21/21에 각 600초, 후보 신호 0 대 31. 분할의 2건은 컴포넌트 TCCT 확인, 29건은 미검토다. S-05는 알려진 Subtract site 원인을 재확인하고 사후 구성한 두 고정 입력의 entrypoint TCCT까지 확인했으나 연구 전체 새 고유 원인은 0이다. S-04 IntDiv의 단일 원인은 미귀속이다. 최초 후보의 parent 경고 관측 1.108243333초는 생성시각이나 사후 entrypoint 검증 완료 시간이 아니다. C-01은 부분 완료. N4-1 자원 공정성·사람 포함 총비용·독립 평가가 남고 N4-2 미착수, N5 미고정 |
| N5 | 완료 — 평가 프로토콜 v1 고정 (2026-10-06, miiz 최종 확인) | miiz | [v1](n5_evaluation_protocol_v1_2026-10-06.md)([초안 v0](n5_evaluation_protocol_draft_2026-10-06.md) 보존): seed 3·시도 30초, 총예산 A 600초·B 3,600초(600초 시점·조각 커버리지 함께 보고). A는 설치 기록 있는 수정 커밋 항목부터, B는 1단계 저장소당 2개·총 최대 10개와 2단계 전부를 미리 고정. B 사설 도달·TCCT 위반 전부 사람 검토, 동시 실행 3, 알려진 결함(Q)과 B 새 발견 후보 분리. B 목록은 E-02 완료 후 zkFuzz 실행 전에 규칙으로 생성·해시 기록 |
| N6 | 대기 — B1 실행 준비 완료, B 실행 검수 후 지시 대기 | miiz | [N6-B1](n6_b1_readiness_2026-10-06.md)에서 B stage1 10개×seed 3개 W/S spec·queue 고정과 개발 시험 완료. B 대상 실행은 아직 0회. 1단계 A-D·A-Q와 B 실제 실행은 별도 시작 기록 후 수행 |
| N7 | 대기 | miiz | 기록과 판정이 완성된 뒤 분석 |

## 8. 우선 대조할 문헌

- [zkFuzz v3](https://arxiv.org/html/2504.11961v3): PDF §3의 관찰 범위, §6의 집계·설정, §8의 slicing 한계, 부록 B의 추가 의미 검사(N2에서 판·절 번호 대조).
- [SoK](https://arxiv.org/html/2607.23752v1): §III-B의 평가 방법, §V와 그림 2의 분모, §VIII의 보장·한계. [공개 산출물](https://github.com/t-sorger/zkp-security-tools)과 대조.
- [Towards Fuzzing ZKP Circuits](https://arxiv.org/html/2504.14881v2): §3.2의 부분 회로 제안과 §4의 실제 구현 범위.
- [Wildfire](https://arxiv.org/html/1903.02981v2): §4~6의 격리 분석과 호출 맥락 확인, §8.2의 컴파일 재사용.
- [Picus/QED²](https://veridise.com/wp-content/uploads/2025/01/Automated-Detection-of-Underconstrained-Circuits-for-Zero-Knowledge-Proofs.pdf): §6의 부분 회로 처리와 unknown.
- [CCC-Check](https://eprint.iacr.org/2025/2120): 입력 태그 가정, 값 추론의 건전성, 태그 검증과 감사 평가의 구분.
- [ZEQUAL](https://www.cs.utexas.edu/~isil/zequal.pdf): §6~7의 모듈식 검증과 반례/실제 오류 구분.
- [CIVER](https://ieeexplore.ieee.org/document/10646792/): 원문 접근 여부를 명시. [공식 저장소](https://github.com/costa-group/circom_civer)·[후속 보고](https://costa.fdi.ucm.es/web/news/CIVER_ZisK.html)를 원 논문 평가와 혼동하지 않음.
