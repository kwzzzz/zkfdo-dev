# controlled-v1 evaluation protocol

고정일: 2026-09-19

상태: **프로토콜 고정 완료 / controlled-v1 실행 자료 없음 / 성능 분석 미실행**

이 문서는 결과를 확인하기 전에 `risk-only`, `random`, `small-first`의 통제 비교 조건과 분석 방법을 고정한다. 프로토콜 작성은 zkFuzz의 유효 결함 발견이나 전략 성능 검증이 아니다. 실행 결과를 본 뒤 반복 수, seed, 예산, 제외 기준, 지표 또는 분석법을 바꾸지 않는다.

## 평가 질문과 단위

같은 두 target, 도구, 장비와 fuzzing 예산에서 세 전략이 **사후 검토를 통과한 원본 컴포넌트의 고유 결함**을 얼마나 빨리 또는 많이 생성하는지 비교한다.

평가 세트는 `Subtract`의 취약 원본과 수정 비교본 한 쌍이다. 이들은 독립 결함 사례 두 개가 아니다. 공개 결함 표시는 실행 발견이 아니며, 수정본도 전체 안전성을 보장하는 음성 표본으로 취급하지 않는다. 이 작은 세트는 pipeline 회귀와 순서 효과를 확인할 수 있지만 다중 프로젝트 성능으로 일반화할 수 없다.

고정 입력은 다음과 같다.

- manifest: [`datasets/manifest.controlled-v1.json`](../datasets/manifest.controlled-v1.json), SHA-256 `ec27dc5f088d85ae63e4f5a8397a4d3e9ad01c390af24498d1fc56c47a0931e8`
- 계약: [`datasets/contracts.controlled-v1.json`](../datasets/contracts.controlled-v1.json), SHA-256 `d954de5fe6d8adbeb010f307119b9b3a0207d80b900ed9365d53a16a0f293f9a`
- 공통 prepared report: `reports/controlled-v1-static-regression/evidence/preparation/prepare-b5f3a8b3-2539-4318-b988-a2dbaa568439/prepared.json`, SHA-256 `ab180da1918e275d541866b9476728898805df551a9c1457978f62b43c2ebaa1`
- ranking config: [`configs/static-ranking.json`](../configs/static-ranking.json), SHA-256 `8fed87764b001245d600307f7ba7d8453e88e3b977afda656014eac83ea32d26`
- vulnerable target ID: `sha256:1fdbf2dbcb8c5be4cad2ef0937cdc95c1b36cc8321e2d02f1b820f46c1b91474`
- fixed comparator target ID: `sha256:a85819549a69210934d31e3fa4a0ba4e01f1f456bc86b32a480a29c5b18aec91`

모든 전략은 위 prepared report의 동일한 두 eligible target을 사용한다. target 추가·제외, wrapper 변경, 재분석, 특징·가중치 변경은 이 프로토콜의 비교가 아니다.

## 도구와 실행 환경

| 항목 | 고정 값 |
|---|---|
| zkfDO 구현 기준 | Git `9a8bb0319a8b4e127f73be5f1fa279eafb9156db` |
| plan/run/evaluate용 현재 zkfDO binary | SHA-256 `83c5e1ca1d9f4abed46c01b567fa0d8345c5133897f3ee73041f93339020a6d0` |
| 기존 공통 preparation의 zkfDO binary | SHA-256 `98577ff089217c6fdfcb0452e7db8d9f8afefa110f742a30567f828d4ffa2649` ([고정 기록](../reports/controlled-v1-static-regression/run-config.json)) |
| zkFuzz | revision `072bf1fbbd1c9ecad58d4f6d2204c3b96e7fec17`, version `2.2.1`, binary SHA-256 `ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd` |
| Circom | `2.2.3`, binary SHA-256 `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227` |
| preparation analyzer | Circomspect `0.9.0`, revision `ece9efe0a21e6c422a43ab6f2e1c0ce99678013b`, binary SHA-256 `6acebb5f1c00fd3823e96388cb322cd29bd516f8bacecf855fee5652431c3590` |
| field / compile args | `bn128` / 없음 |
| 장비 | MacBook Pro `Mac17,2`, Apple M5 10-core, 24 GB, arm64 |
| OS | macOS `26.2` build `25C56`, Darwin `25.2.0` |

실행은 이 장비 한 대에서 전원 연결, 저전력 모드 해제, 의도적인 고부하 작업 없이 수행한다. 각 block 시작 전에 Git HEAD, 바이너리 해시, OS·모델·메모리, 전원 상태를 구조화된 환경 기록에 남긴다. 개인 식별 가능한 serial number와 hardware UUID는 기록하지 않는다. 환경이 달라진 실행은 같은 표본으로 합치지 않고 deviation으로 별도 표시한다.

## 비교 전략과 순서

- `risk-only`: 준비된 `risk_score` 내림차순. 현재 고정 입력에서는 vulnerable `2`, fixed `0`이다.
- `random`: 현재 `splitmix64-fisher-yates-rejection-v1`과 별도 ranking seed를 사용한다.
- `small-first`: R1CS size 오름차순. 두 target이 모두 `1`이라 target ID tie-break가 적용된다.

현재 세트에서 `risk-only`와 `small-first`는 모두 vulnerable을 먼저 둔다. 따라서 두 전략의 동일 결과는 독립적인 랭킹 우위 증거가 아니며, 이 세트만으로 둘을 실질적으로 비교할 수 없다. `random`은 아래 seed 목록에서 vulnerable-first와 fixed-first를 각각 6회 갖도록 **실행 전에** block randomization했다. 이는 결과를 보고 고른 seed가 아니다.

## 예산, 반복과 seed

각 전략은 정확히 12회, 총 36회 실행한다. 한 target 제한은 30초, 전략별 전체 fuzzing 제한은 60초다. 전체 제한은 scheduler 시작 후 적용되며 마지막 target은 남은 시간 때문에 30초보다 짧아질 수 있다. 이 사실과 `not_started`를 그대로 기록한다. 준비와 plan 계산, 결과 평가 및 사람의 사후 검토 시간은 60초 fuzzing 예산에 포함하지 않고 각각 별도 보고한다.

같은 block의 세 전략에는 같은 비영(非零) zkFuzz execution seed를 준다. ranking seed는 `random`에만 주며 execution seed와 섞지 않는다. 별도 mutation settings 원본 파일은 사용하지 않는다. runner가 execution seed만 담은 설정 파일을 고정하고 나머지는 고정된 zkFuzz binary의 기본값을 사용한다.

| Block | zkFuzz execution seed | random ranking seed | random 순서 | 전략 실행 순서 |
|---:|---:|---:|---|---|
| 1 | 2026091901 | 2026092901 | fixed → vulnerable | risk-only → random → small-first |
| 2 | 2026091902 | 2026092902 | fixed → vulnerable | random → small-first → risk-only |
| 3 | 2026091903 | 2026092903 | fixed → vulnerable | small-first → risk-only → random |
| 4 | 2026091904 | 2026092904 | fixed → vulnerable | risk-only → random → small-first |
| 5 | 2026091905 | 2026092905 | vulnerable → fixed | random → small-first → risk-only |
| 6 | 2026091906 | 2026092906 | vulnerable → fixed | small-first → risk-only → random |
| 7 | 2026091907 | 2026092907 | fixed → vulnerable | risk-only → random → small-first |
| 8 | 2026091908 | 2026092908 | vulnerable → fixed | random → small-first → risk-only |
| 9 | 2026091909 | 2026092909 | vulnerable → fixed | small-first → risk-only → random |
| 10 | 2026091910 | 2026092910 | fixed → vulnerable | risk-only → random → small-first |
| 11 | 2026091911 | 2026092911 | vulnerable → fixed | random → small-first → risk-only |
| 12 | 2026091912 | 2026092913 | vulnerable → fixed | small-first → risk-only → random |

전략 실행 위치는 각 위치마다 네 번씩 되도록 순환한다. 12 block을 모두 실행하며 유리한 결과가 나왔다는 이유로 조기 종료하거나 반복을 추가하지 않는다.

다음 사전 기준만 campaign-invalid로 처리할 수 있다: 실행 전 해시 불일치, 대상/plan 검증 실패, OS 재시작·전원 상실, 저장 공간 고갈처럼 backend 결과와 무관하게 확인되는 환경 중단. backend timeout, 비정상 종료, runner failure, `not_started`, 무발견은 결과이므로 재실행해 교체하지 않는다. campaign-invalid가 생기면 같은 block의 세 전략 전체를 같은 seed로 한 번 다시 수행하고 원래 기록과 사유도 보존한다. 두 번째도 invalid면 중단하고 프로토콜 deviation으로 보고하며 다른 seed로 대체하지 않는다.

## 유효 발견과 사후 검토

주 지표에 들어갈 기록은 평가 schema 2에서 다음을 모두 만족해야 한다.

1. `evidence_origin`이 `backend-execution`이다.
2. confirmation의 `run_id`와 `target_id`가 같은 plan/outcome의 실제 run과 일치한다.
3. 그 run의 backend 상태가 `bug_found`다.
4. scope가 `original-component` 또는 `project`다.
5. 다음 세 판정이 모두 `satisfied`이고 각 판정의 근거와 설명이 존재한다.
   - 입력 전제 충족
   - 고정 원본 component의 전체 제약 충족
   - 실행 전에 고정한 기능·보안 속성 위반

정적 진단, 수동 소스 검토, 공개 결함 annotation, counterexample 파일 존재만으로는 실행 발견이 아니다. `wrapper-only`, `reachability-unknown`, 조건이 `unknown` 또는 `not-satisfied`인 기록도 주 지표에 포함하지 않는다. evaluator는 연결과 형식을 검사하지만 검토 내용의 사실성을 자동 증명하지 않는다.

후보 검토자는 가능한 범위에서 전략명과 순서를 가린 candidate ID를 받아 검토한다. 원본 revision과 target은 제약·전제 판정에 필요하므로 제공한다. 후보별 검토 시작·종료 시각, 수작업 단계, 사용 도구와 판정 근거를 별도 ledger에 기록한다. 검토 시간은 fuzzing 예산 밖의 비용이다.

동일 root cause는 seed, 전략, target, wrapper 또는 같은 실행 안의 반복 발견 횟수와 관계없이 각 strategy/block 평가에서 한 번만 센다. 반복 block의 같은 원인은 발견 비율을 추정하는 반복 관측이지 새로운 고유 원인이므로 더하지 않는다. 전체 campaign의 corpus-level 고유 원인 수도 반복 횟수로 부풀리지 않는다. 취약 variant의 알려진 원인은 계약의 고정 `root_cause_id`를 사용한다. 수정본에서 예상 밖 후보가 나오면 공개 결함 ID를 자동 재사용하지 않고 근거에 따라 별도 원인을 판정한다. 수정본과 취약본은 독립 사례 수를 늘리는 용도로 세지 않는다.

### 검토 완료 상태

backend candidate마다 다음 상태 중 하나를 기록한다.

- `validated`: 필수 검토가 완료됐고 세 기준이 모두 `satisfied`다.
- `rejected`: 필수 검토가 완료됐으며 하나 이상의 기준이 `not-satisfied`다.
- `unresolved`: 필수 검토가 완료됐지만 하나 이상의 기준이 `unknown`이다.
- `unreviewed`: 검토가 시작되지 않았거나 필수 검토가 끝나지 않았다.

`unreviewed`는 무발견, 거부 또는 단순 right-censoring으로 바꾸지 않는다. 후보가 유효한 event인지 아직 모르므로 그 후보가 있는 strategy/block의 판정은 `adjudication-incomplete`다. `unresolved`도 유효 발견에는 포함하지 않지만 검토 완료 거부와 구분한다. 잠정 표에는 backend candidate 수, `validated`, `rejected`, `unresolved`, `unreviewed` 수를 각각 표시한다.

모든 candidate의 필수 검토가 완료되기 전에는 최종 전략 비교, 발견 비율 검정, 생존곡선 비교, restricted mean 비교와 유의성 분석을 수행하지 않는다. 중간 현황은 `provisional`로만 보고하며 미검토 후보를 제외한 수치를 최종 성능으로 제시하지 않는다. 후보 파일이 없거나 검토할 수 없는 경우도 임의로 거부하지 않고 `unreviewed` 또는 `unresolved`와 사유를 보존한다.

## 사전 고정 분석

각 전략과 block에서 다음을 그대로 보고한다.

- 검토된 고유 원인 수
- 최초 유효 발견을 포함한 run의 `completion_offset_seconds` 상한
- `original_component_detection_curve`
- backend candidate 수와 검토 완료·거부·미검토 수
- `timeout`, `runner_failure`, `not_started`와 그 밖의 구조화된 상태 수
- 준비, plan/순위 계산, scheduler 실행, evaluation, 사람의 사후 검토 비용

실행 자료 자체가 없으면 발견 수, 발견 시간, 생존곡선과 restricted mean은 모두 `unmeasured`다. 숫자 0이나 censoring record를 만들지 않는다.

필수 검토가 끝난 자료의 시간 처리는 다음과 같다.

- 유효 발견의 시간은 정확한 backend 발견시각이 아니라 연결된 run의 `completion_offset_seconds` 상한이다.
- 이 상한이 `60.0`초 이하일 때만 예산 내 event와 발견 수에 포함한다.
- 상한이 60초를 넘으면 실제 발견이 더 빨랐을 가능성이 있어도 현재 자료로는 입증할 수 없으므로 예산 내 발견으로 소급하지 않는다. `post-budget completion`으로 실제 완료 상한과 검토 상태를 별도 보고한다.
- 실제 관측이 60초까지 유지됐고 예산 내 유효 발견이 없으면 시간 중앙값은 `not reached`, 0–60초 restricted mean time-to-first-valid-discovery는 60초다. 이는 60초 발견을 뜻하지 않는다.
- 실행이 60초 전에 끝났고 유효 발견이 없으면 실제 관측 종료시각에서 right-censor한다. timeout, runner failure, `not_started`, campaign 중단을 근거 없이 60초 관측으로 늘리지 않는다.
- Kaplan–Meier 생존확률이 0이 되기 전에 risk set의 마지막 관측이 60초보다 먼저 끝나면 0–60초 restricted mean을 비모수적으로 지지할 관측 범위가 없다. 이 경우 `not estimable`과 마지막 지지 시각·이유를 보고한다. 반대로 60초까지 risk set이 남아 있거나 그 전에 생존확률이 0이 된 경우에만 0–60초 restricted mean을 계산한다.

무발견을 0초 발견으로 바꾸지 않으며, 조기 종료와 정상적인 60초 무발견을 같은 값으로 채우지 않는다. 예산 이후 완료 기록은 후보·검토 workload와 운영 지연을 설명하는 보조 자료이고 예산 내 발견 곡선과 고유 원인 수에는 들어가지 않는다.

12개 paired block 집계 방법은 다음과 같이 고정한다.

- budget 종료 시 고유 원인 수와 발견 여부를 block별로 보존하고 전략별 평균·중앙값·발견 비율을 보고한다.
- 발견 비율에는 Wilson 95% 구간을 보고한다.
- `risk-only` 대 `random`, `risk-only` 대 `small-first`의 paired 발견 여부는 exact McNemar 검정과 효과 차이를 보고하고 두 비교에 Holm 보정을 적용한다.
- time-to-first-valid-discovery는 위 관측·검토 완료 규칙을 적용한 Kaplan–Meier 곡선, 중앙값이 도달할 때의 중앙값, 관측 범위가 지지할 때만 0–60초 restricted mean을 보고한다. 60초까지 완전 관측된 전부 무발견 자료의 중앙값은 `not reached`이고 restricted mean은 60초다.
- 전략 간 restricted mean 차이의 불확실성은 block 단위 paired bootstrap 10,000회, 분석 seed `2026100101`로 계산한다.
- 예산 내 평균 누적 고유 원인 곡선은 scheduler 완료 event에서 만들고, 개별 block 곡선도 보존한다.
- p-value만으로 우위를 선언하지 않으며 효과 크기, censoring, 실패·미검토 수를 함께 보고한다.

이 한 쌍에서 얻은 통계는 controlled-v1 내부의 통제된 순서 효과 점검이다. 반복 block은 탐색 변동을 관측할 뿐 독립 결함 사례 수를 늘리지 않는다. 다중 프로젝트 또는 일반적인 Circom 성능 주장이 아니다. 특히 `risk-only`와 `small-first`는 현재 target 순서가 같으므로 두 전략 사이에 관측되는 시간 차이를 순위 알고리즘 효과로 주장하지 않는다. 차이가 있다면 동일 순서에서 생긴 실행 변동 또는 시스템 변동으로 보고한다.

## 합성 경계 사례 검증

실제 후보·반례와 분리된 작은 합성 상태/시간 자료로 아래 기대 처리를 확인한다. 합성 record는 저장된 plan, outcome, confirmation 또는 발견 건수에 추가하지 않는다.

| 합성 사례 | 고정 처리 |
|---|---|
| 실행 자료 없음 | 모든 성능 지표 `unmeasured`; 0건·0초·censoring record를 만들지 않음 |
| 60초까지 전부 관측, 유효 발견 없음 | 발견 수 0, 중앙값 `not reached`, 0–60초 restricted mean 60초 |
| 일부 유효 발견 | 완료 상한이 60초 이하인 `validated` event만 예산 내 곡선에 포함 |
| 60초 전 조기 종료, 발견 없음 | 실제 종료시각에서 censor; 60초까지 외삽하지 않으며 지지가 끊기면 restricted mean `not estimable` |
| 미검토 candidate 존재 | `adjudication-incomplete`; 잠정 수만 분리 표시하고 최종 비교·유의성 분석 보류 |
| 유효 후보의 완료 상한이 60초 초과 | `post-budget completion`으로 별도 기록; 예산 내 발견 수와 곡선에는 미포함 |

2026-09-19에 repository 밖의 임시 Python 자료로 이 여섯 상태를 검사해 6/6이 기대 처리와 일치함을 확인했다. 검사는 전부 무발견·60초 완전 관측의 restricted mean `60.0`, 일부 발견의 예산 내 event 포함, 35초 조기 종료의 실제 시각 censor와 restricted mean `not estimable`, 미검토 후보의 최종 분석 보류, 60.5초 완료의 `post-budget completion` 분리, 실행 자료 없음의 `unmeasured`를 각각 assertion으로 확인했다. 합성 자료와 검사 코드는 실제 plan·outcome·confirmation에 저장하지 않았다.

## 사용 가능한 실행 자료 점검 결과

2026-09-19에 원시 반례·witness·proof를 열지 않고 파일명이 plan/outcome/evaluation/summary/confirmation인 구조화 JSON 251개를 파싱해 세트 이름과 두 target ID의 연결을 확인했다.

- controlled-v1 target과 연결된 plan: 없음
- controlled-v1 outcome 또는 scheduler summary: 없음
- controlled-v1 schema 2 confirmation: 없음
- controlled-v1 evaluation: 없음
- 따라서 검토된 고유 원인 수, 최초 유효 발견 상한, 발견 곡선과 전략별 성능 분석: **미실행**

로컬의 `runs/dev10-smoke/confirmations.json`은 다른 Reclaim target의 schema 1 기록이다. scope도 `wrapper-only` 또는 `reachability-unknown`이며 세 가지 원본 컴포넌트 검토가 없다. dev3의 49회 실행과 backend 후보 119건도 controlled-v1 실행이나 검토 완료 원본 컴포넌트 결함이 아니므로 이 분석에 재사용하지 않는다. 정적 회귀의 `2 대 0` 점수 역시 실행 발견으로 집계하지 않는다.

## 성능 분석을 시작하기 위한 필수 자료

현재 부족한 자료는 다음과 같다.

1. 위 36개 실행 각각의 saved plan과 exact ranking/execution seed 기록
2. 환경·도구 해시와 block 실행 순서를 담은 campaign 환경 기록
3. 각 실행의 구조화된 outcome과 scheduler summary
4. `bug_found` 후보별 schema 2 검토 판정 또는 명시적인 미검토 상태
5. 세 판정의 근거 파일과 candidate별 사후 검토 시간 ledger
6. 실행별 preparation, planning, scheduler, evaluation 비용과 사람 검토 비용
7. 사전 invalid 기준에 해당한 block이 있으면 원본 기록, 사유와 전체-block 재실행 기록

이 자료가 생기기 전에는 발견 수를 0으로 확정하거나 발견 시간을 부여하지 않는다. 추가 출처 조사, 정적 분석 반복, 규칙·가중치 변경으로 빈 실행 자료를 대신하지 않는다.
