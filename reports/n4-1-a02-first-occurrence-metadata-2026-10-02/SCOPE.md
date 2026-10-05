# S-03 첫 occurrence 메타데이터 범위

2026-10-02 · 담당 miiz · `s03-first-occurrence-metadata-scope-v1` · 고정 시각 `2026-10-02T03:29:01.835444+00:00`

**상태: 후보 값 미개봉 상태에서 메타데이터 범위 고정. 요청된 S-03 의미 검토는 미수행.**

이 기록은 [인계](../../docs/next_a02_semantic_handoff_2026-10-02.md)의 31건 occurrence 선정·시간·연결 메타데이터 검산을 다룬다. 실제 프로젝트의 지정 결함 후보를 재현·확인하는 단계는 수행할 수 없는 범위여서 후보 값은 열지 않는다. 이 제한은 도구 오류나 파일 부재가 아니며, 사용자 요청 전체를 완료한 것으로 기록하지 않는다.

이번 [인벤토리](occurrence-inventory-v1.json)는 원시 ledger에서 31건을 열거한 뒤 고정했다. 후보 파일은 존재와 크기만 확인했고 내용 파싱이나 파일 hash 재계산을 하지 않았다. 보고서·ledger·spec·manifest의 SHA-256만 새로 계산했다. SCOPE는 후보 값 열람·컴파일·witness 계산·제약 검사보다 앞선 상태로 남으며 해당 실행을 승인하거나 완료한 기록이 아니다.

## 선정과 분모

- 전체 기록: small-first 시도 67개, occurrence 31개. `NOT SAFE` parent 관측 offset, attempt index, 후보 경로 사전식 순서로 정렬한다.
- 지정 선택: 0-based attempt 1, target `sha256:1830b5991e7c31effb5249dccfc0f125fa1e5cc8099cfcdb5dc7d0e9bde75cb3`, `Subtract()`.
- 기록된 후보 SHA-256: `dae6e8b397f2b25269f9711443449b73ba6ba86f4ca7a4397cf318fbfc143258`.
- 경로: `runs/n4-1-policy-a-engine-2026-10-02/small-first-campaign-v1/attempts/000001/candidates/zkfdo-targets/src__subtractTensor__Subtract.circom_CGijXpcMP3_counterexample.json`.
- parent 관측 offset 1.108243333초, 시도 완료 상한 1.117240042초. 생성시각·최초 확인시각으로 바꾸지 않는다.
- 선택 1건은 의미 미판정, 선택 범위 밖 30건도 이 작업에서 미검토. 병렬 S-04의 값·파일·판정을 읽거나 합치지 않는다.

## 출처·컴파일 조건: 기존 메타데이터 주장

| 항목 | 기록값 | 이번 확인 수준 |
|---|---|---|
| 원본 revision | `d310309c141d36504b3486cebd96ed70ef3a4fdf` | A-02 spec의 기록; checkout 재검증 없음 |
| 원본 소스 | `src/subtractTensor.circom`, SHA-256 `502ee44b70a368066fafcf09cc2d0356479f8a862bfa726bde8097c728c83cc1` | source manifest의 기록; 소스 미열람 |
| wrapper | `zkfdo-targets/src__subtractTensor__Subtract.circom`, SHA-256 `1665e793a060f63336a8256b48b789915897b8eeb40d65f60118dd5605068c7b` | manifest·spec 참조 일치; wrapper 미열람 |
| production entrypoint | `src/circuit.circom`, SHA-256 `f1b6abc4987d25cb53f9da6a72ade48703e99ba9499badb8c3dfee242c3a7464` | manifest의 기록; 호출 맥락 미검토 |
| preflight 컴파일 | Circom 2.2.3, BN128, default 최적화, R1CS 출력 | A-02 SCOPE·spec·preflight 성공 기록만 확인 |
| 캠페인 엔진 | zkFuzz 2.2.1 | A-02의 기록; 이번 실행 없음 |
| 원본 R1CS 동일성 | unknown | R1CS 열람·해시 재계산·재컴파일 없음 |
| 엔진 내부 컴파일과 preflight 동일성 | unknown | preflight 성공을 엔진 내부 R1CS 일치로 승격하지 않음 |

## 판정 층과 보류

| 층 | 정의·필요 근거 | 이번 상태 |
|---|---|---|
| 입력 전제 | 선택 후보의 입력이 해당 범위의 전제를 충족하는지 별도 확인 | 후보 미개봉으로 unknown. 과거 S-01의 입력 전제 성립을 복사하지 않음 |
| 일반 TCCT | 원본 제약 전체를 만족하는 후보가 같은 입력의 정직한 계산과 출력 차이 또는 abort 관계를 보이는지 판정 | not_performed. 컴포넌트 위반/비위반 어느 쪽도 아님 |
| 첫 차이·실제 원인 | 후보별 독립 근거가 있어야 귀속 가능 | unknown. 파일명·target·라벨은 귀속 근거가 아님 |
| 중복 원인 | 범위가 명시된 원인 근거와 대응이 필요 | S-01과 같은 원인이라는 주장은 가설. 같은 R1CS 여부도 미검증 |
| 호출 맥락·투영 | 호출 위치와 전제·도달성·대응 근거가 필요 | not_attempted. 실패 또는 미검토를 후보 배제로 해석하지 않음 |
| entrypoint TCCT | entrypoint 수준의 별도 근거가 필요 | unresolved; 컴포넌트 상태로 자동 승격하지 않음 |

## 중단·보존·완료 기준

- 지정 해시/attempt/target과 메타데이터가 충돌하면 다른 후보를 고르지 않고 해당 연결 판정을 중단한다.
- 시각 결측·여러 후보/marker로 연결이 모호하면 임의로 시간을 붙이지 않고 사유를 기록한다.
- 실제 후보 제약 검증·정직한 witness·차이·원인·투영 재현 단계에는 들어가지 않는다. 제한을 기술 오류나 정상/음성 결과로 바꾸지 않는다.
- 메타데이터 산출물과 의미 미판정 이유를 남기면 이번 부분 작업은 종료한다. 인계의 3시간 상한은 새 실행의 승인이 아니며 S-03 전체 완료·N4-1 통과·N5 고정을 선언하지 않는다.
- S-03 행만 시작·종료 상태를 갱신한다. 기존 고정 파일·S-04 영역·코드와 테스트는 보존한다. 원시 작업 기록은 ignored `runs/`에 둔다.
- 검토 프로세스 미실행과 성공적인 검토 비용 0초를 구분한다. 사람의 실제 작업시간은 계측하지 않으면 unknown이다.

## 연결 해시

| 자료 | 저장소 상대 경로 | SHA-256 |
|---|---|---|
| 인계 | `docs/next_a02_semantic_handoff_2026-10-02.md` | `cbad78e065a52c0a38eb586afc813a27afbd4f1f7f6ed0f738b521c9b35c7166` |
| A-02 SCOPE | `reports/n4-1-policy-a-engine-2026-10-02/SCOPE.md` | `6908aeb42a746ecbc1d55d0d84e5339ee5ea52ceb09000532fef78d34c4b02fa` |
| A-02 REPORT | `reports/n4-1-policy-a-engine-2026-10-02/REPORT.md` | `0c345ffaca10aed7345b978745b3e93a582cb191da57445b4cb40462b2d270a7` |
| A-02 evidence v2 | `reports/n4-1-policy-a-engine-2026-10-02/evidence-v2.json` | `41855eae4d04b3426dd71ceff960fe7d925202d56180170a8681d0c85cfacb8e` |
| small-first spec | `reports/n4-1-policy-a-engine-2026-10-02/small-first-spec-v1.json` | `bc9e8f58ce99f44b13faf27fd339490b75d6e823bb5afa06b04cddaf56f709e6` |
| source manifest | `reports/n4-1-policy-a-engine-2026-10-02/source-manifest-v1.txt` | `69574bb41330e20ce1716fb0203688ef965e5dd985f171409d0dc630ca0075e9` |
| 공통 실행기 | `scripts/run_policy_a_engine.py` | `c408ccbad8cc0847bc471b7b38cde0c21d81071157c50b95ab943b16055f874d` |
| small-first ledger | `runs/n4-1-policy-a-engine-2026-10-02/small-first-campaign-v1/ledger.json` | `8912e24976bc7d7dc414a7eddcda67007fa5aeffff989babf017d09fa0bbcb8e` |
| small-first preflight | `runs/n4-1-policy-a-engine-2026-10-02/small-first-preflight-v1/preflight.json` | `284ff020e843e183c886131b92fd2b7c39795b2c7708538e5b4e088f03bc442e` |
| S-01 보고서 | `reports/n4-1-p2-candidate-review-2026-10-02/REPORT.md` | `8a0110f1c419b07b0a114062bea20ce054f62329c979ef02f8fcb08bd6a3543e` |
| S-02 보고서 | `reports/n4-1-p2-clamp-review-2026-10-02/REPORT.md` | `3f78bc7839c647bfd6a9e017bfb91b0480f7acc532c7cc06e7d1e054e76adc49` |
| 이번 인벤토리 | `reports/n4-1-a02-first-occurrence-metadata-2026-10-02/occurrence-inventory-v1.json` | `344585cd7270db2dec889222eac323d5362088408d70d2d5ce22e23fd0ab48cc` |
