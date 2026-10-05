# A-02 후보 검토 결과 연결표

담당 miiz · 갱신 2026-10-02. 기존 고정 인벤토리와 검토 보고서의 결론을 연결하는 현재 상태표다. 새 의미 판정이나 재현 실행이 아니며 후보 값·witness·검토 스크립트를 열지 않았다. 원문 SCOPE/REPORT는 보존한다. 기계 판독본은 [a02_review_status.json](a02_review_status.json)이다.

## 현재 집계

| 항목 | 현재 보고된 결과 |
|---|---|
| 전체 occurrence | 31 |
| 발생 target label | 10종: `Subtract()` 4건, 나머지 9종 각 3건. 검토된 occurrence가 있는 label은 2종이며 어느 label도 전체 occurrence 검토가 끝나지 않음 |
| 컴포넌트 의미 검토 완료 | 2: S-04·S-05, 둘 다 출력 차이형 TCCT |
| 미검토 | 29. 다른 occurrence에 기존 판정을 복사하지 않음 |
| 귀속된 알려진 site 원인 | 현재 확인된 범위에서 1: S-01과 같은 Subtract 원인 |
| 원인 미귀속 위반 | 1: S-04 IntDiv |
| entrypoint 확인 | S-05 한 occurrence의 사후 구성한 두 고정 입력. 같은 원인·같은 프로젝트 |
| 연구 전체 새 고유 원인 증가 | S-05는 0. 독립 사례 증가도 0 |
| 일반적 효율 우위·사람 포함 총비용·프로젝트 의미 | 미입증 / 미판정 |

한 개발 사례의 동일 600초 할당 비교에서 통째는 후보 없이 timeout됐고, 분할은 사후 확인된 컴포넌트 TCCT 후보를 생성했다. 그중 알려진 원인 하나가 두 고정 입력의 entrypoint TCCT 위반으로 연결됐다는 서술은 가능하다. 전체 entrypoint 결과는 별도 입력 구성·사후 검토로 얻었으며, 완전 자동 entrypoint 발견이나 검증 시간의 우위로 쓰지 않는다.

## 시간 정정 TIME-01

S-05가 생성시각 하한으로 적은 1.103817667초는 A-02 evidence-v2상 성공한 Popen 반환 직후 parent 관측이다. 자식은 그보다 먼저 실행될 수 있으므로 실제 OS 시작 또는 후보 생성 하한으로 사용할 수 없다. 고정 S-05 SCOPE/REPORT는 수정하지 않고 현재 집계에서 하한을 unknown으로 둔다. 이 정정은 의미 판정과 후보 순서를 바꾸지 않는다.

- 사후 확인된 첫 컴포넌트 후보의 parent 경고 관측: 1.108243333초.
- 수집된 후보 파일의 존재 상한: 시도 완료 1.117240042초.
- 정확 생성시각·entrypoint 검증까지의 총시간: unknown.
- S-05 준비/검토 자식 프로세스 wall 합은 12.415초이고 이를 포함한 스크립트 wall 합은 14.133초다. 두 합계를 서로 더하지 않는다. 사람 실제 활동시간은 unknown.

## 중복·검사·작업 처리

동일 seed만으로 같은 반례나 같은 원인이라고 판정하지 않는다. S-05는 S-01과 동일 witness 및 같은 site 원인이라는 보고 근거가 있다. 캠페인별 발생/재발견 기록은 각각 보존하고 연구 전체 고유 원인은 한 번만 센다. 동일 witness의 두 관측은 독립 발견 사례가 아니다. 고유 site, fix PR/결함 클러스터, 프로젝트를 별도 수준으로 보고한다.

C-01 자체는 부분 완료다. S-05가 별도로 제공한 Subtract 호출 위치·두 맥락의 결과를 참조하되 C-01을 완료로 바꾸거나 범용 mapping 구현 성과로 승격하지 않는다. C-01의 기존 합성 회귀를 다시 실행할 이유는 새 코드·오류가 있을 때로 한정한다.

후속 검토의 효율을 위해 occurrence 31건과 target label 10종을 함께 추적한다. 아직 검토 결과가 전혀 없는 label 8종을 먼저 파악하면 증거 범위가 빨리 넓어진다. 같은 label의 다른 occurrence나 다른 seed에 판정을 자동 복사하지 않고, 같은 원인인지 확인된 연결만 중복 집계한다. 후보 파일 해시가 서로 다르다는 사실만으로 원인이 31개라는 뜻도 아니다.

S-05에는 새 Python 코드 두 개가 있지만 필수 fmt/clippy/cargo test는 미실행으로 보고됐다. AGENTS.md의 코드 변경 규칙은 Rust에 한정되지 않으므로 해당 변경 묶음의 필수 검사 완료 근거는 아직 없다. 이는 보고된 TCCT 판정을 자동으로 부정하지 않지만, 업로드 전 확인할 절차상 미완료다.

## 31건 결과 연결

| 순서 | attempt | target | 컴포넌트 TCCT | 원인 | entrypoint | 원문 |
|---:|---:|---|---|---|---|---|
| 1 | 1 | `Subtract()` | 확인 | 기존 site 귀속 | 두 고정 맥락 확인 | [S-05](../reports/n4-1-a02-first-semantic-review-2026-10-02/REPORT.md) |
| 2 | 8 | `IntDiv(40)` | 확인 | 미귀속 | 미판정 | [S-04](../reports/n4-1-a02-intdiv-review-2026-10-02/REPORT.md) |
| 3 | 9 | `DistanceFromScore(40)` | 미검토 | 미검토 | 미검토 | — |
| 4 | 12 | `IntDiv(80)` | 미검토 | 미검토 | 미검토 | — |
| 5 | 13 | `Clamp(40)` | 미검토 | 미검토 | 미검토 | — |
| 6 | 14 | `CalculatedScoreFraction(40)` | 미검토 | 미검토 | 미검토 | — |
| 7 | 15 | `ResponseTimeNormalized(40)` | 미검토 | 미검토 | 미검토 | — |
| 8 | 18 | `IntDiv(120)` | 미검토 | 미검토 | 미검토 | — |
| 9 | 19 | `ScoringFunction(40)` | 미검토 | 미검토 | 미검토 | — |
| 10 | 20 | `ResponseTimeMetric(40)` | 미검토 | 미검토 | 미검토 | — |
| 11 | 22 | `Subtract()` | 미검토 | 미검토 | 미검토 | — |
| 12 | 29 | `IntDiv(40)` | 미검토 | 미검토 | 미검토 | — |
| 13 | 30 | `DistanceFromScore(40)` | 미검토 | 미검토 | 미검토 | — |
| 14 | 33 | `IntDiv(80)` | 미검토 | 미검토 | 미검토 | — |
| 15 | 34 | `Clamp(40)` | 미검토 | 미검토 | 미검토 | — |
| 16 | 35 | `CalculatedScoreFraction(40)` | 미검토 | 미검토 | 미검토 | — |
| 17 | 36 | `ResponseTimeNormalized(40)` | 미검토 | 미검토 | 미검토 | — |
| 18 | 39 | `IntDiv(120)` | 미검토 | 미검토 | 미검토 | — |
| 19 | 40 | `ScoringFunction(40)` | 미검토 | 미검토 | 미검토 | — |
| 20 | 41 | `ResponseTimeMetric(40)` | 미검토 | 미검토 | 미검토 | — |
| 21 | 43 | `Subtract()` | 미검토 | 미검토 | 미검토 | — |
| 22 | 50 | `IntDiv(40)` | 미검토 | 미검토 | 미검토 | — |
| 23 | 51 | `DistanceFromScore(40)` | 미검토 | 미검토 | 미검토 | — |
| 24 | 54 | `IntDiv(80)` | 미검토 | 미검토 | 미검토 | — |
| 25 | 55 | `Clamp(40)` | 미검토 | 미검토 | 미검토 | — |
| 26 | 56 | `CalculatedScoreFraction(40)` | 미검토 | 미검토 | 미검토 | — |
| 27 | 57 | `ResponseTimeNormalized(40)` | 미검토 | 미검토 | 미검토 | — |
| 28 | 60 | `IntDiv(120)` | 미검토 | 미검토 | 미검토 | — |
| 29 | 61 | `ScoringFunction(40)` | 미검토 | 미검토 | 미검토 | — |
| 30 | 62 | `ResponseTimeMetric(40)` | 미검토 | 미검토 | 미검토 | — |
| 31 | 64 | `Subtract()` | 미검토 | 미검토 | 미검토 | — |

## 원문 고정 참조

| 자료 | SHA-256 |
|---|---|
| [inventory](../reports/n4-1-a02-first-occurrence-metadata-2026-10-02/occurrence-inventory-v1.json) | `344585cd7270db2dec889222eac323d5362088408d70d2d5ce22e23fd0ab48cc` |
| [S04](../reports/n4-1-a02-intdiv-review-2026-10-02/REPORT.md) | `4d257fe5c07f1f9a99f31541214ad7fa83a3b0da675f40959b308040167ec422` |
| [S04_scope](../reports/n4-1-a02-intdiv-review-2026-10-02/SCOPE.md) | `e122217998acfcd12fb007ed7022825068b7110bdc1b4cffa1f9c6feed39ffa7` |
| [S05](../reports/n4-1-a02-first-semantic-review-2026-10-02/REPORT.md) | `b34d55aef3f3277ba679c68598925cb2555549c3b57492e96aabd829a9512ef5` |
| [S05_scope](../reports/n4-1-a02-first-semantic-review-2026-10-02/SCOPE.md) | `20444675ca7cd0299ea5b706728e3da129e9525a8b8d22ee7f8a8358c42748bf` |
| [S01](../reports/n4-1-p2-candidate-review-2026-10-02/REPORT.md) | `8a0110f1c419b07b0a114062bea20ce054f62329c979ef02f8fcb08bd6a3543e` |
| [A02_v2](../reports/n4-1-policy-a-engine-2026-10-02/evidence-v2.json) | `41855eae4d04b3426dd71ceff960fe7d925202d56180170a8681d0c85cfacb8e` |
| [C01](../reports/c01-normal-boundary-readiness-2026-10-02/REPORT.md) | `605e5fe2c176a349e91ce81d789189cc40592a01215182d194cb6c4193ce24c0` |
