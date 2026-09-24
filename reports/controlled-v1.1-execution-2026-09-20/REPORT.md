# controlled-v1.1 Subtract 실행·검토 결과

실행일: 2026-09-20

## 결론

고정된 12 paired block, 36개 전략 실행이 모두 완료됐다. `risk-only`, `random`, `small-first`는 각각 12/12 block에서 사후 검토를 통과한 같은 Subtract 원본 컴포넌트 원인을 발견했다.

- campaign 전체의 검토된 고유 원본 컴포넌트 원인: **1건**
- 프로젝트 문맥까지 확인한 결함: **0건**
- backend 후보: **36건**
- 검토 판정: **validated 36 / rejected 0 / unresolved 0 / unreviewed 0**
- 수정 비교본 후보: **0건**
- invalid block, timeout, runner failure, `not_started`: **0건**

36건은 서로 독립적인 결함이 아니라 같은 원인의 반복 관측이다. 정적 위험점수 `2` 대 `0`과 공개 known defect는 발견 수에 포함하지 않았다.

## v1 보존과 v1.1 고정

기존 v1이 요구한 zkfDO SHA-256 `83c5e1ca…` 파일을 저장소와 관련 임시 경로의 후보 파일 616개에서 한 번 다시 확인했지만 찾지 못했다. 기존 v1은 plan 0회, zkFuzz 실행 0회 상태로 유지한다.

결과를 보기 전에 [v1.1 실행 프로토콜](../../docs/controlled_v1_1_execution_protocol.md)을 별도로 고정했다. 대상·전략·12 block/36회·순서·seed·30초/60초 예산·검토 기준·분석법은 v1과 같고 실행 파일 식별 정보만 다음과 같이 교체했다.

| 항목 | 고정 값 |
|---|---|
| 구현 커밋 | `9a8bb0319a8b4e127f73be5f1fa279eafb9156db` |
| Git tree | `4215bea47d73115dd8c5663a5df538803828a746` |
| 보관 경로 | `runs/controlled-v1.1/frozen-tools/zkfDO-9a8bb031-debug` |
| SHA-256 | `e3472909d3d8de4411ee20a9574a822b9c262e7aff935c9bf38eac8f31a16960` |
| 빌드 | `cargo build --locked --bin zkfDO`, Cargo dev profile |

초안의 current HEAD 비교 조건은 고정 바이너리의 출처를 검증하는 조건으로 교체했다. invalid는 backend 결과와 독립적인 사전 환경·plan·driver 실패로만 제한하고, 같은 block 전체를 최대 한 번 다시 수행하도록 했다. 이번 campaign에는 invalid가 없어 모든 block이 첫 시도 기록을 사용한다.

## 실행 무결성

[campaign ledger](evidence/campaign-ledger.json)에 block별 환경, seed, 전략 순서, plan·outcome 경로와 해시, planning/scheduler 시간과 backend 상태를 저장했다. [증거 색인](evidence/record-index.json)은 원래 ignored campaign 파일과 Git에 보존한 바이트 동일 복사본의 경로·SHA-256을 연결한다. 이 복사본에는 [실행 driver](evidence/campaign-driver.py), 12개 block·환경 기록, 36개 plan·outcome이 포함된다. 원시 반례 값은 Git에서 제외된 `runs/`에만 보존했다.

| 항목 | 결과 |
|---|---:|
| paired block | 12 |
| strategy 실행 | 36 |
| plan / outcome | 36 / 36 |
| 첫 시도에 유효한 block | 12 |
| invalid 재시도 | 0 |
| run/target 연결 실패 | 0 |
| 취약 target `bug_found` | 36 |
| 수정 target `no_counterexample` | 36 |

각 전략은 취약 target `bug_found` 12회와 수정 target `no_counterexample` 12회를 기록했다. random은 사전 고정대로 vulnerable-first 6회와 fixed-first 6회였다. 모든 outcome은 plan ID·plan SHA-256·strategy·seed·예산·target 순서·zkFuzz 해시와 연결됐다.

## 후보 검토

prepared 취약 source를 Circom 2.2.3, bn128의 동일 설정으로 R1CS와 심볼만 다시 만들었다. R1CS SHA-256은 `14c18b08…`이며 campaign 준비 단계의 R1CS와 바이트 단위로 같았다. witness·proof는 생성하지 않았다.

[candidate-review.json](candidate-review.json)은 각 후보에 대해 다음을 분리해 기록한다.

1. 보존 파일 SHA-256과 같은 outcome의 `bug_found` run/target 연결
2. 입력 `a`, `b`가 canonical BN128 field element라는 전제
3. 고정 취약 revision의 R1CS 제약 1개 전체 만족
4. 사전 정의한 `c = a - b mod p` 속성 위반

36건 모두 네 연결·검토를 통과했다. compiled R1CS 직접 평가와 source 식 독립 계산을 교차검산했다. 원시 후보 신호 값은 보고서·검토 JSON·평가 JSON에 복사하지 않았다.

zkFuzz가 prepared source 디렉터리에 남긴 원시 후보 36개는 campaign의 보존본과 SHA-256이 각각 같음을 확인했다. Git 작업 트리에 원시 값이 노출되지 않도록 source 쪽 중복본만 제거했고, 보존본은 ignored campaign 디렉터리에 유지했다. 경로·해시 대응과 제거 결과는 [raw-candidate-storage-cleanup.json](raw-candidate-storage-cleanup.json)에 값 없이 기록했다.

각 outcome에는 schema 2 confirmation 한 건을 연결하고 고정 zkfDO evaluator로 다시 읽었다. [evaluation-index.json](evaluation-index.json)의 36개 평가 모두 `confirmed_original_component_defect_count = 1`, `confirmed_project_defect_count = 0`이다. 후보별 자동 검토는 총 약 `0.0330초`, 36개 evaluator 호출은 driver wall time 약 `0.3704초`였다. 별도의 사람 검토 시간을 정확히 계측하지 않아 `null`로 남겼다.

## 전략 결과

모든 event는 60초 예산 안에 있었고 시간은 정확한 발견시각이 아니라 후보와 연결된 run의 scheduler 완료시간 상한이다.

| 전략 | 유효 발견 block | 발견 비율 (Wilson 95%) | 완료 상한 평균 | 0–60초 제한평균 |
|---|---:|---:|---:|---:|
| risk-only | 12/12 | 1.000 (`0.758–1.000`) | `0.032641초` | `0.032641초` |
| random | 12/12 | 1.000 (`0.758–1.000`) | `0.423327초` | `0.423327초` |
| small-first | 12/12 | 1.000 (`0.758–1.000`) | `0.031279초` | `0.031279초` |

유효 발견 여부는 모든 paired block에서 같았다.

| 사전 비교 | 발견 비율 차이 | exact McNemar p | Holm p | 제한평균 차이, risk-only − 비교전략 (paired bootstrap 95%) |
|---|---:|---:|---:|---:|
| risk-only vs random | `0` | `1.0` | `1.0` | `-0.390685초` (`-0.592510`, `-0.192499`) |
| risk-only vs small-first | `0` | `1.0` | `1.0` | `+0.001363초` (`+0.000141`, `+0.002639`) |

random의 시간에는 fixed-first 6회가 포함돼 있다. 따라서 risk-only와 random의 차이는 이 한 쌍에서 사전 고정된 target 순서가 만든 시간 차이를 보여준다. risk-only와 small-first는 모두 취약 target을 먼저 실행했으므로 둘 사이의 작은 차이를 랭킹 알고리즘 효과로 해석하지 않는다.

## 비용

| 단계 | 기록 |
|---|---:|
| 공유 preparation | `1.876862초` |
| 36 plan 계산 합계 | `0.097998초` |
| 36 scheduler 실행 합계 | `30.1510초` |
| campaign wall time | `46.5229초` |
| 후보 자동 검토 | `0.0330초` |
| evaluator 내부 시간 합계 | `0.1659초` |
| evaluation driver wall time | `0.3704초` |
| 사람 검토 시간 | 미계측 (`null`) |

준비·plan·사후 검토·evaluation은 60초 fuzzing 예산과 분리했다. backend가 빠르게 결과를 반환해 실제 scheduler wall time은 명목상 최대 예산보다 짧았다.

## 해석 범위

이 결과는 고정된 Subtract 원본·수정본 한 쌍의 통제된 순서 효과 회귀다. 반복 block은 탐색 변동을 관측하지만 독립 결함 사례 수를 늘리지 않는다. 프로젝트 caller 도달성·영향, 수정본 전체 안전성, 다중 프로젝트에서의 성능 우위는 확인하지 않았다. 결과를 본 뒤 source, ranking 규칙, 특징 또는 가중치를 변경하지 않았다.

기계 판독 결과와 재현 코드는 [analysis.json](analysis.json), [review_candidates.py](review_candidates.py), [evaluate_campaign.py](evaluate_campaign.py), [analyze_campaign.py](analyze_campaign.py)에 남겼다.
