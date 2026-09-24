# 계획 수정과 다음 작업 (2026-09-24)

이 문서는 2026-09-23까지의 실험 결과를 보고 **남은 계획을 어떻게 바꾸는지**, 그리고 **누가 무엇을 해야 하는지**를 정리한다. 팀원 모두 이 문서를 기준으로 작업한다. 이미 고정된 프로토콜(`docs/controlled_v*_protocol.md`)과 기존 실행 결과는 수정하지 않는다. 현재 결과 요약은 [README](../README.md)의 Status와 각 `reports/*/REPORT.md`를 본다.

## 1. 왜 수정하는가

지금까지 확인한 것은 **파이프라인이 알려진 결함을 끝까지 재발견하고, 검토 기준까지 통과시킬 수 있다**는 점이다(v1.1, v2, v3에서 각 1건). 연구의 핵심 주장은 **예산이 부족할 때 순위를 매겨 실행하면 무작위나 단순 기준보다 검토를 통과한 결함을 더 빨리 또는 더 많이 찾는다**는 것인데, 이 주장은 아직 시험하지 못했다. 이유는 다음과 같다.

1. **예산이 부족한 상황을 한 번도 만들지 않았다.** 지금까지 실험의 타깃은 2~4개였고, 예산 안에서 모두 끝까지 실행됐다. 이렇게 되면 전략 간 차이는 순서 효과뿐이다(v2 보고서에도 기록됨). 순위가 의미를 가지려면 전체 예산으로 모든 타깃을 다 실행할 수 없어야 한다.
2. **취약본·수정본 쌍은 순위 평가에 맞지 않는다.** 수정은 보통 제약 몇 줄 차이라서 정적 특징이 거의 같다. v3에서 두 쌍 모두 위험점수가 같았다(`0=0`, `1=1`). 동점은 `target_id`(소스·설정의 SHA-256) 오름차순으로 정리되므로([src/static_rank.rs](../src/static_rank.rs) `risk_order`), 수정본이 먼저 실행된 것은 편향이 아니라 해시 순서에 따른 우연이다. 즉 쌍 설계는 **zkFuzz가 이 결함을 잡는지 확인하는 통제용**이지 순위 평가용이 아니다.
3. **사례 하나를 검증하는 비용이 크다.** 9/15~9/23 동안 한 번에 결함 1~2개를 검증했다. 이 속도로는 원인 5개 이상·프로젝트 3개 이상으로 여러 전략을 짝지어 비교하기 어렵다.
4. **계획한 범위가 구현 범위보다 넓다.** `evaluation_plan.md`의 `cost-aware`, `analyzer-aware`, `adaptive` 전략과 RQ4(smoke→deep)는 구현돼 있지 않다. 현재 구현된 전략은 `path-order`, `random`, `small-first`, `warning-first`, `legacy`, `risk-only`, `risk-grouped` 7개다.

## 2. 수정 결정

| 항목 | 기존 계획 | 수정 |
|---|---|---|
| 평가 세트 구성 | 알려진 원인마다 취약·수정 쌍, 직접 래퍼 중심 | **취약 버전 프로젝트의 실제 `main`에서 도달 가능한 구체 타깃 전부**(결함 타깃 + 결함 없는 타깃)를 한 세트로 둔다. 수정본은 후보 확인용 음성 대조로만 쓴다 |
| 예산 | 모든 타깃을 실행할 수 있는 수준 | **전체 예산 = (타깃 수 × 타깃별 timeout)의 20~40%**. 실행 전에 계산할 수 있고, 반드시 일부 타깃이 실행되지 못하는 조건이다 |
| 비교 전략 | 계획서의 8개 | 필수: `random`(여러 ranking seed), `small-first`, `path-order`, `risk-only`, `cost-aware`(신규). 선택: `warning-first`(Circomspect 설치 시). `adaptive`, `analyzer-aware`는 제외 |
| RQ3 (분석기 경고) | 별도 결합 전략 | `warning-first`와 `risk-only`를 한 번 비교하는 것으로 축소 |
| RQ4 (smoke→deep) | 핵심 기여 | **향후 과제로 이동.** 시간이 남으면 T8의 최소 형태만 구현 |
| RQ5 (대형 프로젝트 관리) | 계획만 있음 | **독립된 실행 가능성 연구로 진행**(T6). 결함을 찾지 못해도 결과로 성립한다 |
| 후보 검토 | 사례마다 수동 스크립트 작성 | **공용 검토 도구로 자동화**(T4). 사람은 사전 속성 정의와 최종 판정 확인만 한다 |
| 동점 처리 | 문서화 안 됨 | 현재 `target_id` 해시 순서를 유지하고 문서화한다. 계획 출력에 동점 그룹 수를 기록한다(T5) |
| 음성 결과 | – | 순위 전략이 이기지 못하면 그대로 보고하고 원인(특징 해상도, 동점, oracle 한계 등)을 분석한다. 가중치를 사후에 바꾸면 그 세트는 개발용으로 강등한다 |

바뀌지 않는 것:

- 주 지표: 실행에서 나온 후보가 (1) 입력 전제 충족, (2) 고정 원본 제약 전체 충족, (3) 사전 정의 속성 위반을 모두 통과한 **고유 원인**의 최초 발견시간과 예산 내 개수
- 프로젝트 호출 경로까지 확인된 결함은 별도로 집계한다
- 원시 후보와 대형 산출물은 ignored `runs/`에 두고, Git에는 해시·판정·시간만 둔다
- 독립 평가 세트는 원인 5개 이상, 프로젝트 3개 이상

## 3. 다음 작업

작업마다 `ID`, 목표, 산출물, 완료 조건, 금지 사항을 적었다. 담당자는 작업을 시작할 때 `담당` 칸에 이름을 적는다.

### 의존 관계

```
T1 제외 목록 ─► T2 후보 조사 ─► T3 v4 프로토콜 고정 ─► T7 독립 평가 실행·분석
                                   ▲                    ▲
T5 cost-aware·동점 기록 ───────────┘                    │
T4 검토 자동화 ─────────────────────────────────────────┘
T6 대형 프로젝트 실행 가능성 (독립, 병행 가능)
T0 PR 정리 (사람)
```

T1, T4, T5, T6은 지금 바로 병행해서 시작할 수 있다.

### T0. PR 정리 — 담당: (사람만)

- **현재 상태(2026-09-24):** main은 `63fae61`(9/8 정적 순위 파이프라인)에서 멈춰 있다. 브랜치는 한 줄로 이어져 있어서 뒤쪽 브랜치가 앞쪽 브랜치를 모두 포함한다.
  - PR #11 `feat/minimal-runner`: 1커밋
  - (PR 없음) `feat/uniform-scheduler-target-discovery`: #11 + 3커밋
  - PR #13 `feat/candidate-validation-evidence`: #11 + 14커밋. 1,088개 파일, 약 40만 줄. 대부분은 증거 스냅샷과 복사한 circomlib이고, `src/`·테스트 변경은 약 1.26만 줄이다
  - `feat/tangle-v3-validation`(원격에 없음): #13 + 6커밋 + 2026-09-24 계획 문서
- **정리 순서:**
  1. **#11은 병합하지 않고 닫는다.** 내용이 #13에 그대로 들어 있다. 닫을 때 "#13에 포함됨"이라고 적는다.
  2. **#13을 검토한다.** 40만 줄을 다 읽지 않는다. `src/`, `tests/`, `docs/`, 각 `REPORT.md`만 본다. `datasets/**/circomlib`, `node_modules`, `reports/**/evidence/` 아래 파일은 해시로 고정한 증거 사본이므로 수정하지 않고 넘어간다. `cargo test`를 통과하는지 확인한다.
  3. **#13을 병합할 때 Squash하지 않는다.** "Create a merge commit" 또는 "Rebase and merge"를 쓴다. 보고서에 적힌 커밋 기준(예: `8e1d60f`)이 main 이력에 남아야 재현할 수 있다.
  4. `feat/tangle-v3-validation`을 push하고 main 대상 새 PR을 연다. 병합한 뒤라서 6커밋과 계획 문서만 보인다.
  5. 병합이 끝난 브랜치(`feat/minimal-runner`, `feat/uniform-scheduler-target-discovery`, `feat/candidate-validation-evidence`)는 삭제해도 된다. 커밋은 main 이력에 남는다.
- 앞으로는 T1~T8마다 main에서 짧은 브랜치를 따서 작업 하나당 PR 하나로 올린다. PR이 몇십 개 커밋씩 쌓이지 않게 한다.

### T1. 개발에 사용한 사례의 제외 목록 — 담당:

- **목표:** 지금까지 본 모든 결함 원인과 프로젝트를 기록해서 독립 평가 세트에 섞이지 않게 한다.
- **산출물:** `datasets/exclusions.development.json` (항목마다 `root_cause_id` 또는 zkbugs 경로, 프로젝트, 처음 사용한 실험, 근거 파일)
- **포함 범위:** controlled-v1/v1.1(Subtract), v2(Banyan, Tangle 및 v2 준비 단계에서 본 Aptos base64, Telepathy array-xor), v3(Decoder, BigLessThan 및 선정에서 탈락한 bigint-bigmod, rarimo-date-encoder, unirep-epoch-key-lite, zkemail-fpmul), dev3·dev10(reclaimprotocol chacha20의 XorWords, Add32Bits, RotateLeft 계열). 출처: `datasets/manifest.*.json`, `datasets/controlled-v*/`, `reports/*/REPORT.md`
- **완료 조건:** 위 보고서에서 언급된 모든 사례가 목록에 있고, 누락 여부를 다른 사람이 한 번 확인했다.
- **금지:** 목록을 줄이기 위해 기존 보고서를 해석하지 않는다. 애매하면 제외 쪽으로 둔다.

### T2. 독립 평가 후보 조사 (실행 금지) — 담당:

- **목표:** zkbugs Circom 사례(`.external/zkbugs/dataset/circom/`, 현재 70건·25개 조직) 중 T1에 없는 것으로 평가 세트 후보를 만든다.
- **사례마다 기록할 것:**
  - 프로젝트, 취약·수정 커밋, 결함 위치
  - 결함 템플릿이 **실제 프로젝트 `main`에서 도달 가능한지**, 그리고 zkfDO `targets`로 그 `main`에서 발견되는 구체 타깃 수
  - wrapper 컴파일 성공 여부
  - 입력 계약(`field_only` 또는 `bounded`)과 사전 정의할 속성의 초안
  - **TCCT 탐지 가능성:** 제약 부족(under-constrained) 유형인지, Tangle처럼 소스와 제약이 함께 틀린 의미 결함인지. 후자는 제외 후보로 표시한다([Tangle 진단](../reports/tangle-diagnostic-2026-09-22/REPORT.md) 참고)
- **산출물:** `reports/heldout-survey-YYYY-MM-DD/SURVEY.md`와 같은 내용의 JSON
- **완료 조건:** 조건을 만족하는 후보가 원인 5개 이상·프로젝트 3개 이상 되거나, 부족하면 부족하다고 명시한다.
- **금지:** 후보 사례에 **zkFuzz를 실행하지 않는다**(실행하면 개발용이 된다). 컴파일과 `targets` 탐색은 허용한다. 선택 기준을 결과를 보고 바꾸지 않는다.

### T3. controlled-v4 독립 평가 프로토콜 작성·고정 — 담당:

- **전제:** T2와 T5 완료
- **목표:** 2절의 "예산 부족" 설계를 프로토콜로 고정한다. 기존 `docs/controlled_v2_execution_protocol.md`의 형식을 따른다.
- **반드시 정할 것:**
  - 사례와 타깃 목록(프로젝트별 도달 가능 타깃 전부), 결함 타깃과 원인 매핑
  - 타깃별 timeout, 전체 예산 비율(20~40% 중 하나로 고정)
  - 전략 목록, `random`의 ranking seed 개수, zkFuzz seed(paired block) 개수
  - 도구 해시(zkfDO 커밋, zkFuzz, circom 버전), 하드웨어
  - 주 지표 계산법, 통계 비교 방법, 실패·timeout 처리
  - 결과를 본 뒤 가중치를 바꾸면 이 세트는 개발용으로 강등된다는 조항
- **산출물:** `docs/controlled_v4_evaluation_protocol.md`, `datasets/manifest.controlled-v4.json`, `datasets/contracts.controlled-v4.json`, preflight 보고서
- **완료 조건:** `experiment prepare`와 `plan`이 모든 전략에서 성공하고, 해시가 기록된 커밋이 있다. 팀원 1명 이상이 검토했다.

### T4. 후보 검토 자동화 — 담당:

- **목표:** [review_candidate.py](../reports/controlled-v3-pilot-2026-09-23/review_candidate.py)를 일반화해서 사례마다 새 스크립트를 쓰지 않게 한다.
- **입력:** 후보 파일, 고정 원본의 R1CS/SYM, 입력 계약, 사전 속성 명세(사례별 작은 predicate 파일)
- **출력:** 값이 들어가지 않은 판정 JSON(세 판정 + 근거 해시). 형식은 기존 `candidate-review.json`과 호환되어야 한다.
- **위치 제안:** `tools/review/` (Python) 또는 `zkfDO experiment review` 하위 명령. 둘 중 하나를 골라서 이 문서에 적는다.
- **완료 조건:** v1.1, v2(Banyan), v3(Decoder)의 기존 후보에 적용했을 때 기존 판정과 같은 결과가 나온다(원시 후보가 있는 로컬에서 확인). 테스트 포함.
- **금지:** 기존 보고서의 판정 파일을 덮어쓰지 않는다. 신호 값을 Git에 커밋하지 않는다.

### T5. `cost-aware` 전략과 동점 기록 — 담당:

- **목표:** `evaluation_plan.md`에는 있지만 구현되지 않은 `cost-aware` 전략을 추가하고, 동점 정보를 계획에 남긴다.
- **내용:**
  - `cost-aware`: `risk_score / cost`. cost는 prepare 단계에서 이미 측정되는 값(예: 제약 수 또는 컴파일 시간) 중 하나로 정하고, 이유를 문서에 적는다. 동점은 기존과 같이 `target_id` 순서로 정리한다.
  - 계획 JSON에 동점 그룹 수와 최대 동점 크기를 기록한다.
  - `docs/static_ranking_experiment.md`에 전략 목록과 동점 규칙을 갱신한다.
- **완료 조건:** `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`를 통과한다. 기존 전략의 계획 출력은 바뀌지 않는다(회귀 테스트).
- **금지:** 기존 전략의 점수나 가중치를 바꾸지 않는다. v1~v3 결과를 보고 가중치를 조정하지 않는다.

### T6. zkbugs 외 대형 프로젝트 실행 가능성 연구 (RQ5) — 담당:

- **목표:** 실제 규모 Circom 프로젝트에서 zkfDO가 타깃을 얼마나 찾고, 비용이 얼마나 드는지 측정한다. 결함을 찾지 못해도 결과로 성립한다.
- **절차:**
  1. zkbugs 데이터셋에 **사례로 들어 있지 않은** 공개 Circom 프로젝트 2~3개를 고르고 커밋을 고정한다. 선정 이유와 제외 이유를 기록한다.
  2. 각 프로젝트의 실제 `main` 파일들에 `zkfDO targets`를 실행한다.
  3. 기록할 항목: 파일·템플릿 수, 발견한 구체 인스턴스 수, 지원하지 않는 구문 때문에 빠진 수, wrapper 컴파일 성공률, 준비 시간, 균일 예산 실행에서 `timeout`, `failure`, `no_counterexample`, `bug_found` 비율, 타깃별 비용 분포.
  4. 실행 전에 예산·seed·도구 해시를 고정한다.
  5. `bug_found` 후보가 나오면 T4 도구로 세 기준을 검토하고, 프로젝트 호출 경로 확인은 별도로 기록한다.
- **산출물:** `reports/real-project-feasibility-YYYY-MM-DD/REPORT.md` 및 값 없는 evidence JSON
- **금지:** 발견한 후보를 검토 없이 "취약점"이라고 쓰지 않는다. 이 결과를 독립 평가 세트(T3)와 합산하지 않는다.

### T7. 독립 평가 실행과 분석 — 담당:

- **전제:** T3, T4 완료
- **목표:** v4 프로토콜대로 한 번 실행하고, 모든 후보를 검토한 뒤 전략을 비교한다.
- **산출물:** 누적 발견 곡선(전략별), 최초 발견시간, 예산 내 고유 원인 수, timeout률, 낭비 시간, 준비·순위·퍼징·검토 시간 분리 표, `reports/controlled-v4-execution-YYYY-MM-DD/REPORT.md`
- **금지:** 실패한 실행을 다시 돌려 교체하지 않는다. 미검토 후보가 남아 있으면 최종 비교를 발표하지 않는다(`provisional`로만 표시).

### T8. (선택) 최소 적응형 배분 — 담당:

- T7이 끝나고 시간이 남을 때만 진행한다. 예: 짧은 smoke 실행에서 timeout이 난 타깃은 뒤로 미루는 규칙 하나. 새로운 평가 세트나 T7과 같은 세트의 별도 부록으로만 보고한다.

## 4. 공통 작업 규칙

- **Git:** commit, push, PR 병합은 변경 내용을 확인한 뒤 한다. 커밋 메시지와 PR 본문에 `Co-Authored-By` 같은 공동 작성자 표기를 넣지 않는다.
- **고정된 자료:** 기존 프로토콜, manifest, contracts, 실행 결과, 판정 파일을 사후 수정하지 않는다. 바꿔야 하면 새 버전 파일을 만든다.
- **개발용과 평가용 분리:** T1 목록에 있는 사례는 평가 세트에 넣지 않는다. 평가 세트 사례에 zkFuzz를 실행한 순간 그 실행은 기록 대상이 되며, 버리거나 다시 돌리지 않는다.
- **증거 보관:** 원시 후보·R1CS·SYM은 `runs/`(ignored)에 두고, Git에는 경로·해시·판정·시간만 둔다.
- **코드 변경:** `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` 통과. 주변 코드 스타일을 따른다.
- **작업 기록:** 작업을 시작하거나 끝내면 3절의 `담당` 칸과 아래 진행 표를 갱신한다.

## 5. 진행 표

| ID | 상태 | 담당 | 메모 |
|---|---|---|---|
| T0 | 대기 | 사람 | |
| T1 | 대기 | | |
| T2 | 대기 | | T1 후 |
| T3 | 대기 | | T2, T5 후 |
| T4 | 대기 | | |
| T5 | 대기 | | |
| T6 | 대기 | | |
| T7 | 대기 | | T3, T4 후 |
| T8 | 보류 | | 선택 |
