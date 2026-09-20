# controlled-v2 held-out execution protocol

고정일: 2026-09-20

상태: **실행 전 고정 완료 / backend 실행 0회 / 후보 검토 0건 / 성능 분석 미실행**

이 평가는 결과를 확인한 controlled-v1.1 Subtract와 dev3 Reclaim 계열을 제외하고, 서로 다른 프로젝트와 원인 유형에서 risk-only, random, small-first를 비교한다. 자료 준비와 정적 점수는 탐지 성공으로 세지 않는다.

## 고정 평가 자료

| 항목 | 고정 값 |
|---|---|
| manifest | datasets/manifest.controlled-v2.json |
| manifest SHA-256 | 758180ae4827f53adbaa35d8075566a3f3eb3a090be221dbd5183527657c70b7 |
| 계약 | datasets/contracts.controlled-v2.json |
| 계약 SHA-256 | a9f0d595dfee347f0d54a9c2b253ea4da84ae74c76d39cb108ad1151dd2152a0 |
| prepared | reports/controlled-v2-preparation-2026-09-20/evidence/accepted-preparation/prepare-6cc01794-1fcf-404d-b577-5c208e94a7cd/prepared.json |
| prepared SHA-256 | 967135b38000ee09b1d82aa15cf1bbbdb354fbecf437692e77a9e440f99dd504 |
| ranking config SHA-256 | 8fed87764b001245d600307f7ba7d8453e88e3b977afda656014eac83ea32d26 |

선정한 원인은 Tangle SetMembership의 잘못된 곱 초기화와 Banyan CheckDepth의 comparator 입력 범위 누락이다. 각 원인마다 공개 취약 revision과 수정 비교본을 한 쌍으로 둔다. 취약·수정본은 독립 사례 두 개가 아니며, 최대 독립 원인 수는 block당 2개다.

| 약어 | target ID | 역할 | risk | 제약 수 |
|---|---|---|---:|---:|
| TV | sha256:39ece08d569693c46d9896a351d6ccd4228b5e9f1b4debb10b2346d4ae0eded5 | Tangle 취약본 | 0 | 6 |
| TF | sha256:46bff69377a67f20a7dd7f5fd4070fa92f97c88cb5d267d40a6fff6b2803e377 | Tangle 수정 비교본 | 0 | 6 |
| BV | sha256:b99bf2694b89536d1c7ca1ef97933456981930df93e7bfc08d0b61149a7bc496 | Banyan 취약본 | 1 | 29 |
| BF | sha256:c7216c1efd7084100b27458fdbf6f4a00d7f9ddb13c09ee485d4bcbfaa0c5a5c | Banyan 수정 비교본 | 1 | 47 |

고정 순서는 risk-only = BV, BF, TV, TF이고 small-first = TV, TF, BV, BF다. 두 전략의 순서가 다르므로 시간 차이는 순서 정책의 차이로 분석할 수 있다. 개별 정적 점수가 공개 결함 여부를 완전히 구분한다는 뜻은 아니다.

## 고정 도구와 환경

| 항목 | 값 |
|---|---|
| zkfDO 구현 | commit 9a8bb0319a8b4e127f73be5f1fa279eafb9156db, tree 4215bea47d73115dd8c5663a5df538803828a746 |
| zkfDO 실행 파일 / SHA-256 | runs/controlled-v1.1/frozen-tools/zkfDO-9a8bb031-debug / e3472909d3d8de4411ee20a9574a822b9c262e7aff935c9bf38eac8f31a16960 |
| zkFuzz revision / SHA-256 | 072bf1fbbd1c9ecad58d4f6d2204c3b96e7fec17 / ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd |
| Circom | 2.2.3 / 8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227 |
| Circomspect | 0.9.0, revision ece9efe0a21e6c422a43ab6f2e1c0ce99678013b / 6acebb5f1c00fd3823e96388cb322cd29bd516f8bacecf855fee5652431c3590 |
| field / structural compile | BN128 / O0 |
| hardware | Mac17,2, Apple M5, 10 cores (4 performance + 6 efficiency), 24 GB |
| OS | macOS 26.2 (25C56), arm64 |

각 block 직전에 파일 해시, source/snapshot fingerprint, target ID, 하드웨어, OS, AC 전원과 저장 공간을 다시 확인한다. 현재 비교 환경은 과거 배포 환경으로 해석하지 않는다.

## 반복, seed, 실행 위치

반복 수는 결과 확인 전에 12 paired block으로 고정한다. 각 block은 세 전략을 한 번씩 실행하므로 총 36개 전략 실행, 144개 target 시도가 계획된다. 같은 block의 세 전략은 같은 execution seed를 사용한다. random ranking seed와 순서는 아래 그대로 사용한다.

| block | execution seed | random ranking seed | 전략 실행 위치 1 → 3 | random target 순서 |
|---:|---:|---:|---|---|
| 1 | 2026092001 | 2026094001 | risk-only, random, small-first | BF, TF, BV, TV |
| 2 | 2026092002 | 2026094002 | random, small-first, risk-only | TV, BV, BF, TF |
| 3 | 2026092003 | 2026094003 | small-first, risk-only, random | BF, BV, TV, TF |
| 4 | 2026092004 | 2026094004 | risk-only, random, small-first | BF, TF, TV, BV |
| 5 | 2026092005 | 2026094005 | random, small-first, risk-only | TF, BV, TV, BF |
| 6 | 2026092006 | 2026094006 | small-first, risk-only, random | TV, BF, BV, TF |
| 7 | 2026092007 | 2026094007 | risk-only, random, small-first | TF, BV, TV, BF |
| 8 | 2026092008 | 2026094008 | random, small-first, risk-only | BV, BF, TF, TV |
| 9 | 2026092009 | 2026094009 | small-first, risk-only, random | TV, BF, BV, TF |
| 10 | 2026092010 | 2026094010 | risk-only, random, small-first | TV, TF, BV, BF |
| 11 | 2026092011 | 2026094011 | random, small-first, risk-only | TF, TV, BV, BF |
| 12 | 2026092012 | 2026094012 | small-first, risk-only, random | BV, TV, BF, TF |

각 전략은 실행 위치 1, 2, 3에 네 번씩 배치된다. seed나 순서는 backend 상태, 후보 수 또는 검토 결과를 보고 교체하지 않는다. 동일 execution seed는 같은 mutation 설정을 뜻하지만 target 순서가 달라 생성 과정 전체가 같다는 보장은 하지 않는다.

## 예산과 시간 경계

- target별 wall-clock 제한은 30초다.
- 전략 실행별 전체 process-attempt 예산은 120초다.
- 준비, 정적 분석, 순위 계산, subprocess 실행, 결과 저장, 사후 검토 시간을 분리 기록한다.
- 주 발견 시간은 정확한 생성 시각이 아니라 전략 실행 시작부터 해당 run이 끝날 때까지의 완료시간 상한이다.
- 120초를 넘겨 저장된 완료 기록은 예산 내 발견으로 소급하지 않는다.
- backend가 일찍 끝나면 실제 관측 종료시각만 사용하고 근거 없이 120초까지 늘리지 않는다.
- 무발견, timeout, failure, not-started를 0초 발견으로 바꾸지 않는다. 생존곡선과 제한평균은 실제 관측 범위가 뒷받침할 때만 계산한다.

30초/120초는 controlled-v1.1의 target별 30초를 네 target에 동일하게 확장한 값이다. 새 사례의 backend 결과를 보고 정하지 않았다.

## 후보 판정과 중복 제거

bug_found만 후보 검토 대상으로 삼는다. 원시 값은 보고서·대화·Git에 복사하지 않고 다음을 구조화해 판정한다.

1. 저장된 plan의 같은 run/target과 연결되고 backend 상태가 bug_found인지 확인한다.
2. 계약에 적힌 입력 전제가 충족되는지 확인한다.
3. 같은 target의 고정 R1CS 전체 제약을 만족하는지 재계산한다.
4. 실행 전에 정의한 속성을 위반하는지 확인한다.

세 내용 판정이 모두 satisfied이고 연결이 유효한 schema 2 backend-execution 기록만 주 지표에 넣는다. 증거 부족은 unknown/unreviewed, 정확한 제약 불만족이나 속성 비위반은 rejected, 검사 도구 실패는 review_failure로 분리한다. 미검토 후보가 남으면 최종 전략 비교와 유의성 분석을 보류한다. 검토 시간은 탐색 예산 밖에서 기록한다.

같은 root_cause_id를 다른 seed·전략·wrapper에서 반복 확인해도 block과 campaign의 고유 원인 수에서는 한 번만 센다. 수정 비교본의 예상 밖 후보는 자동으로 취약본 원인에 붙이지 않는다. 프로젝트 caller 도달성과 영향은 별도 지표다.

## 고정 분석

전략별로 다음을 계산한다.

- 12 block 중 검토된 각 독립 원인을 찾은 비율
- block별 예산 내 검토된 고유 원인 수(0–2)와 평균·중앙값
- 첫 유효 원인 및 각 원인의 최초 완료시간 상한
- 예산 내 평균 누적 고유 원인 곡선
- backend 상태, failure, timeout, not-started, 후보, validated/rejected/unresolved/unreviewed 수
- 준비·계획·실행·사후 검토 비용

paired block 안에서 risk-only - random, risk-only - small-first의 고유 원인 수 차이와 원인별 완료시간 상한을 비교한다. 12회 반복은 독립 결함 사례 수를 늘리지 않는다. 사례가 두 개뿐이므로 통제된 순서 효과 점검이며 다중 프로젝트 일반 성능으로 일반화하지 않는다. 우위가 없거나 어느 원인도 재발견하지 못하면 그대로 보고한다.

## campaign-invalid

실행 전 해시 불일치, target/plan 검증 실패, 전원 상실, OS 재시작, 저장 공간 고갈처럼 backend 결과와 독립적인 사전 환경 중단만 campaign-invalid다. block 기록과 사유를 보존하고 같은 세 seed와 순서로 block 전체를 한 번만 다시 수행한다. 두 번째도 invalid면 campaign을 중단한다.

backend timeout, 비정상 종료, runner failure, not-started, 무발견, 거부된 후보는 campaign-invalid가 아니며 재실행하거나 유리한 결과로 교체하지 않는다.

이 문서를 저장한 뒤 source, wrapper, target, 전략, 가중치, 반복 수, seed, 예산, 판정 기준과 분석법을 결과에 맞춰 바꾸지 않는다.
