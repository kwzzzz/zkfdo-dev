# 논문 근거 색인

담당: miiz · 갱신일: 2026-10-02. 논문을 쓸 때 이 문서에서 시작한다. **구현 사실, 개발 관측, 독립 평가를 구분한다.** 고정 보고서는 보존하고 새 결과를 새 ID와 경로로 추가한다.

기존 종합 해석·허용 문장·조건별 수치·참조 해시는 [연구 체크포인트](../reports/research-checkpoint-2026-10-01/REPORT.md)에 있다. 이후 [정상 호환성 인계](next_normal_compatibility_2026-10-01.md)의 6조건을 실제 실행한 **[NC-01](../reports/n4-1-normal-compatibility-2026-10-01/REPORT.md)은 완료**했다. O0 3조건 성공, O1 3조건은 직접 경계 대응 일부/전체 미지원이다. N3 완료, N4-1 전체 미완료, N4-2 미착수, N5 미고정이다.

[NC-01 이후 인계](next_step_handoff_2026-10-02.md)는 착수 전 기록으로 보존한다. 그 구현 범위인 **[NB-01 O0 정상 경계 입력 연결](../reports/n4-1-normal-boundary-replay-2026-10-02/REPORT.md)은 완료**했다. 기존 원본 입력 9조건·경계 45개에서 수동 경계 입력 공식 없이 원본 witness 입력 연결과 wrapper 독립 계산·출력 비교를 확인했다. [A-01 부분 결과](../reports/n4-1-policy-a-2026-10-02/REPORT.md)는 비보안용 모델·한정 계측·NB 회귀다. 후속 **[A-02 실제 공통 엔진 실행](../reports/n4-1-policy-a-engine-2026-10-02/REPORT.md)은 완료**했다. P2 `inference-main` 한 단위에서 통째 1개와 small-first 21개를 같은 상태기로 각각 600초 실행했다. 후보 occurrence 31건 중 [S-04](../reports/n4-1-a02-intdiv-review-2026-10-02/REPORT.md)·[S-05](../reports/n4-1-a02-first-semantic-review-2026-10-02/REPORT.md)의 2건이 컴포넌트 TCCT로 확인됐고 29건은 미검토다. S-05의 알려진 원인 하나는 두 고정 입력의 entrypoint TCCT로도 연결됐다. [31건 연결표와 시간 정정](a02_review_status.md)에 후속 판정·중복·시계 의미를 모았다. C-01은 부분 완료이며 N4-1 전체·N5는 미완료다. 이전 [A-02/S-02 인계](next_engine_clamp_handoff_2026-10-02.md)와 [S-05·C-01 인계](next_s03_context_handoff_2026-10-02.md)는 당시 착수 기록이다.

## 주장별 바로 찾기

| ID | 논문에서 찾을 내용 | 1차 근거 | 허용 범위·핵심 제한 |
|---|---|---|---|
| NE-01 | 자동 구성 이후 정상 계산·경계 대응 | [정상 실행 보고서](../reports/n4-1-normal-execution-2026-10-01/REPORT.md) · [종합 해석 §2](../reports/research-checkpoint-2026-10-01/REPORT.md#2-ne-01ne-02-정상-실행과-컴파일-재사용) | 두 작은 fixture, O0·scalar·각 3입력. 컴파일 52회·R1CS 검사 168회·경계 144회. 독립 사례 수는 아님 |
| NE-02 | 반복 구성 컴파일 재사용 | 같은 [정상 실행 보고서](../reports/n4-1-normal-execution-2026-10-01/REPORT.md) | 원본 포함 방식별 2회 합계 12→8. 기존 fixture 16→16. artifact 컴파일 정책의 통제 비교 |
| NE-03 | 준비 감소와 측정 구간 전체 비용의 차이 | [비용 재계산 §3](../reports/research-checkpoint-2026-10-01/REPORT.md#3-ne-03-비용-재계산과-해석) | 산술 통제 준비 약 39.55% 감소, 준비+정상 검증 7.692001→7.778089초. 속도 우위·열위 미입증 |
| NC-01 | O0/O1·작은 배열의 정상 호환성 경계 | [6조건 실제 실행](../reports/n4-1-normal-compatibility-2026-10-01/REPORT.md) · [범위](../reports/n4-1-normal-compatibility-2026-10-01/SCOPE.md) · [값 없는 근거](../reports/n4-1-normal-compatibility-2026-10-01/evidence.json) | 3 fixture × O0/O1, 각 3입력. 컴파일 30회·정상 계산/R1CS 각 108회 성공. O0 경계 45/45 일치, O1 15/45 일치·30 미지원. 실제 배열 길이 2/3만 확인. 소실 신호 복원·일반 의미 동등성·성능 우위 미입증 |
| NB-01 | 검증된 원본 witness에서 자동 경계 입력 연결·정상 재계산 | [9조건·45경계 실행](../reports/n4-1-normal-boundary-replay-2026-10-02/REPORT.md) · [범위](../reports/n4-1-normal-boundary-replay-2026-10-02/SCOPE.md) · [값 없는 근거](../reports/n4-1-normal-boundary-replay-2026-10-02/evidence.json) | 기존 3 fixture·O0·각 3입력. 컴파일 15회, 원본 계산/R1CS 9회·wrapper 45회 성공. 경계 입력 연결 45/45, 입력 전달 57leaf와 독립 출력 57leaf 별도 일치. 원본 입력은 고정값이며 범용 합성·모든 입력의 의미 보존·후보 투영·독립 사례 증가 근거 아님 |
| A-01 | 예산 보존·종료 모델과 한정 자원 계측(부분) | [부분 결과](../reports/n4-1-policy-a-2026-10-02/REPORT.md) · [SCOPE](../reports/n4-1-policy-a-2026-10-02/SCOPE.md) · [근거](../reports/n4-1-policy-a-2026-10-02/evidence.json) | 가상 1/21 label 모델만 공통 경로, 실제 자원 probe는 고정 정상 자식 1개. 실제 P2 통째 1·분할 21 모두 미시작. NB 라벨/경로표 독립성 회귀 1개 보완. 실제 엔진 Policy A·프로세스 트리 공정성·탐지 근거 아님 |
| A-02 | 실제 Policy A 공통 상태기·엔진 계측 | [실제 실행](../reports/n4-1-policy-a-engine-2026-10-02/REPORT.md) · [사전 범위](../reports/n4-1-policy-a-engine-2026-10-02/SCOPE.md) · [보정된 값 없는 근거](../reports/n4-1-policy-a-engine-2026-10-02/evidence-v2.json) · [후속 31건 연결표](a02_review_status.md) | 개발용 P2 한 단위, 방식별 600초 한 쌍. 통째 1/1은 timeout·후보 0, small-first 21/21은 67시도(candidate 신호 31·no-candidate 17·timeout 19). 후속 의미 검토 2/31, 미검토 29/31. 다른 시도 상한·고정 실행 순서·OS cache·직접 자식 중심 `wait4` 범위와 parent의 `Popen` 반환 관측 기반 phase 경계 때문에 일반 탐지·비용 우위와 전체 process-tree 공정성 미입증 |
| AG-01 | 집계의 모순·실패·중복 보존 | [독립 검증](../reports/n4-1-aggregate-verification-2026-10-01/REVIEW.md) · [후속 수정 §6](evidence_aggregate_v1.md#6-독립-검증-오류-수정) | N1–N7 수정·회귀 12개·Rust 297 통과. 구현 검증이며 탐지 실험 아님. 수정 전 검토와 수정 후 보고 구분 |
| DEV-P2 | 통째/분할 연구의 동기 관측 | [P2](../reports/dev-rq1-pilot-2026-09-29/README.md) | inference 1개 개발 프로젝트의 정답 위치 후보. 지정 후보 하나의 후속 검토는 S-01로 별도 연결; 나머지 후보는 위치 일치·미검토. zk-email 자동 준비 실패 |
| S-01 | P2 분할 `Subtract` 후보 한 개의 컴포넌트 의미 확인 | [사전 범위](../reports/n4-1-p2-candidate-review-2026-10-02/SCOPE.md) · [검토 결과](../reports/n4-1-p2-candidate-review-2026-10-02/REPORT.md) | 원본 제약 전체 만족·정직한 계산과 출력 차이·사전 속성 위반·고정 수정본 거부로 일반 TCCT 및 기존 unconstrained multiplier 원인 귀속. controlled-v1.1과 같은 원인·R1CS라 새 고유 원인/독립 사례 아님. 호출 맥락·entrypoint·프로젝트·같은 수준 양쪽 비교 미판정 |
| S-02 | P2 분할 `Clamp(40)` 후보 한 개의 층별 의미 검토 | [사전 범위](../reports/n4-1-p2-clamp-review-2026-10-02/SCOPE.md) · [검토 결과](../reports/n4-1-p2-clamp-review-2026-10-02/REPORT.md) | 원본 제약 94개 만족, 정직한 witness와 96개 wire 및 `.wtns` 동일: 이 후보는 일반 TCCT 위반 아님. 40비트 범위 밖 입력과 의도 순서 불일치는 별도 명세 관측. 정확한 수정 commit 소스가 circom 2.2.3에서 T3001로 컴파일 실패해 수정본 거부·원인 귀속 미판정. A-02 새 후보·다른 `Clamp` 후보에 판정 복사 금지 |
| S-03 | A-02 첫 후보 메타데이터 검산 | [부분 결과](../reports/n4-1-a02-first-occurrence-metadata-2026-10-02/REPORT.md) · [31건 인벤토리](../reports/n4-1-a02-first-occurrence-metadata-2026-10-02/INVENTORY.md) | 시간순 첫 `Subtract()` occurrence와 parent 관측 1.108243333초·시도 완료 상한 1.117240042초 확인. 후보 값 미개봉, 의미 검토 0/1. 결함 시간·원인·entrypoint 판정 아님 |
| S-04 | A-02 둘째 후보 `IntDiv(40)` 컴포넌트 의미 확인 | [사전 범위](../reports/n4-1-a02-intdiv-review-2026-10-02/SCOPE.md) · [검토 결과](../reports/n4-1-a02-intdiv-review-2026-10-02/REPORT.md) | 원본 제약 46개 만족(Python+snarkjs), 같은 입력의 정직한 witness와 `main.out`만 달라 일반 TCCT 위반 확인. 실제 수정본은 출력 등식과 범위 검사 둘 다 위반하므로 사전 규칙상 단일 원인 귀속 미판정. 77.996707750초는 parent 관측이며 최초 확인 시간 아님. 호출 맥락·entrypoint·프로젝트 미판정, 새 고유 원인으로 미등록 |
| S-05 | A-02 첫 후보 `Subtract()`의 컴포넌트·entrypoint 의미 확인 | [사전 범위](../reports/n4-1-a02-first-semantic-review-2026-10-02/SCOPE.md) · [검토 결과](../reports/n4-1-a02-first-semantic-review-2026-10-02/REPORT.md) · [시간 정정](a02_review_status.md#시간-정정-time-01) | 컴포넌트 TCCT 위반·알려진 무제약 승수 site 원인 귀속. S-01과 동일 witness·site로 새 고유 원인·독립 발견 0. 사후 구성한 두 고정 입력에서 entrypoint TCCT 위반 확인; 현실적 입력·프로젝트 의미 미판정. 첫 후보의 parent 경고 관측 1.108243333초는 생성시각이나 entrypoint 검증 완료 시간이 아니며 생성시각 하한은 unknown |
| C-01 | 정상 경계 준비 상태 점검(부분) | [부분 결과](../reports/c01-normal-boundary-readiness-2026-10-02/REPORT.md) · [범위](../reports/c01-normal-boundary-readiness-2026-10-02/SCOPE.md) | 기존 합성 회귀 16개 통과. 이 작업의 production 호출 분모·정상 입력 가용성 unknown, 정상 경계 비교 미실행. S-05의 Subtract 특정 호출 위치 결과로 C-01 일반 대응 구현 완료를 주장하지 않음 |
| ENG-T6A | 기존 컴파일 재사용 관측 | [T6a](../reports/t6a-compile-reuse-2026-09-26/REPORT.md) | 5,240→63회. NE-02와 다른 실험·대상이며 탐지 성능이나 최초성 근거로 합산하지 않음 |
| LEG-V1 | Subtract의 과거 검토 기록 | [v1.1](../reports/controlled-v1.1-execution-2026-09-20/REPORT.md) | 당시 고정 계약·프로토콜의 알려진 원인 1개. 새 일반 TCCT/프로젝트 의미 층으로 자동 승격하지 않음 |
| LEG-V2 | Banyan·Tangle의 과거 검토 기록 | [v2](../reports/controlled-v2-execution-2026-09-20/REPORT.md) | 선택 원인 2개 중 당시 Banyan 1개 검토 통과. 별도 캠페인 |
| LEG-V3 | Decoder·BigLessThan의 개발 기록 | [v3](../reports/controlled-v3-pilot-2026-09-23/REPORT.md) | 당시 Decoder 1개 검토 통과, BigLessThan 시간초과. 순위의 일반적 우위 미입증 |
| DATA-N1 | 공개 benchmark 분모·노출·설정 불일치 | [N1 감사](../reports/sok-artifact-audit-2026-10-01/REPORT.md) · [70건 JSON](../reports/sok-artifact-audit-2026-10-01/evidence-summary.json) | 전체 70·공통 56, 10/1/3/42. 5건·3repo는 미노출 세트 아님. 600/300초 실제 제한 미해결 |
| LIT-N2 | 선행과 주장 경계 | [방법론 검토](../reports/methodology-review-2026-10-01/REVIEW.md) · [N3 보정](scope_decision_final_2026-10-01.md) | 읽은 판·절과 접근 한계를 함께 인용. 원 권고를 전부 채택한 것은 아님 |

## 논문 절별 사용 위치

- **동기:** DATA-N1, DEV-P2. 공개 격리/프로젝트 차이와 자동 구성의 필요. 해당 차이가 우리 방법의 성공을 보장하지 않는다.
- **설계·구현:** NE-01·02, NC-01, NB-01, A-02, ENG-T6A, AG-01. 해결한 문제와 지원 경계, 호출 위치 보존, 기록의 의미, 실제 Policy A 상태기와 자원 계측 범위를 기술한다.
- **평가:** NE-01·02·03과 NC-01·NB-01은 개발용 정상 동작/비용·호환성 소절에 둔다. NB-01 입력 전달 확인과 독립 출력 비교를 구분한다. A-02는 개발용 실제 실행·예산·종료·제한된 자원 계측으로 사용한다. S-04·S-05의 후속 의미 판정과 S-05의 두 고정 입력 entrypoint 결과는 별도 연결한다. S-01·S-02는 과거 개발 사례의 검토 예시이고 S-03은 첫 후보의 시간순 메타데이터만 확인했다. C-01은 부분 점검이다. 새 독립 결함 발견 비교의 본표는 아직 없다.
- **타당성 위협:** 작은 정상 fixture, 반복 수, O0·scalar 및 NC-01의 길이 2/3 배열·O1 부분 대응, A-02의 방식별 다른 시도 상한·고정 실행 순서·OS cache·불완전한 process-tree 계측·29건 미검토, 개발/공개 결과 노출, 기존 원인 재발견, S-04 귀속 미판정, S-05의 고정 두 입력과 사후 검증, 검토 비용, 미지원.
- **관련 연구:** LIT-N2에서 1차 문헌으로 돌아가 인용한다. 컴파일 재사용·분해 아이디어의 최초성을 쓰지 않는다.

## 유지 규칙

새 결과마다 ID, 날짜/버전, 실행 조건, 독립 단위와 반복의 분모, 원문/기계 판독 근거, 실측/파생 수치 구분, 허용 주장, 제한, 다음 행동을 연결한다. 숫자만 갱신하지 않는다. 부정·미판정·준비 실패도 남긴다.

같은 근거를 여러 캠페인의 합산 분자로 재사용하지 않는다. 285 Rust+4 Python과 후속 297 Rust는 서로 다른 검사 시점이다. 테스트 수는 독립 프로젝트·결함 수가 아니다. 원본 hash·경로는 원문 또는 버전별 종합 기록에서 확인한다.

새 반례·실제 실험 차단 문제·결론을 바꾸는 근거가 없으면 완료 작업의 포괄 재검토를 반복하지 않는다. 다음 실행의 질문을 하나 정하고, 결과가 나온 뒤 이 색인에 연결한다. 주 기여 가설은 자동 분해 시스템이며 기록/집계 기능 확장 자체를 연구 성과의 대체물로 삼지 않는다.
