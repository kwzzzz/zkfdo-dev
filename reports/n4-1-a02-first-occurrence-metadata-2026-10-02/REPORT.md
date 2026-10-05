# S-03 첫 occurrence 메타데이터 검산 결과

2026-10-02 · 담당 miiz · `s03-first-occurrence-metadata-report-v1`

**부분 완료: 31건 인벤토리·최초 관측 선정 검산 완료. 요청된 의미 검토는 미수행이며 S-03 전체는 미완료다.** 실제 프로젝트의 특정 결함 후보를 witness·제약 만족·출력 차이로 재현해 확인하는 단계는 수행할 수 없는 범위다. 이는 컴파일 실패·자료 부재 같은 기술적 차단이나 후보 비위반 판정이 아니다. 후보 값은 열지 않았다.

| 확인 항목 | 결과 |
|---|---|
| 원시 small-first ledger | 67시도, index 0–66 연속 |
| 결과 분포 | candidate 31 / no_candidate 17 / timeout 19 |
| 값 없는 occurrence 인벤토리 | 31/31, parent 관측 결측 0·동률 0 |
| 후보 참조 ↔ parent marker | 각 시도에 참조 1개·`NOT SAFE` 관측 1개. marker 자체에는 파일 ID가 없으므로 attempt 수준 연결 |
| evidence-v2 대조 | attempt·target·경로·기록 해시·parent 관측·완료 offset 불일치 0 |
| 최초 기록된 occurrence | attempt 1, `Subtract()`, 지정 SHA-256 `dae6e8b397f2b25269f9711443449b73ba6ba86f4ca7a4397cf318fbfc143258` |
| 후보 파일 메타데이터 확인 | 기존 해시 참조 일치. 파일 존재·크기 31/31 확인, 내용 미개봉·hash 미재계산 |
| S-03 의미 검토 분모 | 지정 1건 중 완료 0. 나머지 30건도 이 작업에서 미검토 |

[전체 31건 표](INVENTORY.md)와 [기계 판독 인벤토리](occurrence-inventory-v1.json)는 원시 ledger에서 직접 만들었다. evidence-v2의 선정값을 답으로 복사하지 않고, parent `NOT SAFE` 관측 offset → attempt index → 경로 사전식 순서로 다시 정렬했다. 별도의 읽기 전용 메타데이터 검산도 같은 수와 순서를 확인했다. 31개의 서로 다른 파일 해시는 31개의 원인을 뜻하지 않는다.

## 시각과 선행 기록

| 값 | 의미 | 확정하지 않는 것 |
|---|---|---|
| 1.108243333초 | 캠페인 기준 parent 로그 소비 관측 offset | 정확 생성시각·파일 생성시각·확인된 결함 시간 |
| 1.117240042초 | 해당 시도의 result 저장 완료 offset 상한 | 후보 생성시각·검토 완료시각 |
| unknown | 정확한 최초 생성시각 및 최초 확인 결함 시각 | 로그 최소값을 대체값으로 사용하지 않음 |

선행 attempt 0은 `AssertBit()` 한 개다. 후보 참조와 `NOT SAFE` 관측이 없고, 정상 시작·exit 0·`no_candidate`, 완료 offset 1.092595708초로 기록됐다. timeout·취소·시작 실패·fatal error는 없다. 이는 해당 시도의 기록상 후보 부재이며 의미적 음성은 아니다. 이번 열거는 **제공된 ledger 내부의 전체 31건**에 대한 것으로, 생산자가 가능한 모든 후보를 수집했다는 독립 인증은 아니다.

## 범위 고정과 의미 미판정

후보 값 미개봉 상태에서 [SCOPE](SCOPE.md)를 고정했다(SHA-256 `4b74d66e02716f412b2718dafbe757cee5e8612b9722a45da406c914a4915845`). 인계·A-02 SCOPE/REPORT/evidence/runner·원본 metadata manifest·compile 조건과 인벤토리의 연결 hash를 남겼다. 원본 revision·소스·wrapper hash와 preflight 컴파일 성공은 기존 기록의 주장으로 보존했으며, 이번 작업에서 원본 소스나 R1CS를 읽거나 다시 컴파일하지 않았다.

| 요청된 의미 층 | 이번 상태·사유 |
|---|---|
| 원본 R1CS 전체 만족, 독립 방법 둘 | 미수행. 제약 검사 0회 |
| 같은 입력의 정직한 witness·출력 또는 abort | 미수행. candidate 값과 witness 미개봉 |
| 첫 차이·실제 원인 귀속 | 미판정. 새로운 의미 증거가 없음 |
| S-01과 같은 R1CS·원인 | 미검증 가설. template·경로·과거 판정으로 귀속하지 않음 |
| 호출 맥락·entrypoint 투영 | 미시도·미판정. 실패 또는 배제로 기록하지 않음 |
| entrypoint TCCT·프로젝트 의미 | 미판정. 컴포넌트 판정도 새로 확보되지 않음 |

S-01·S-02 보고서는 읽었으나 해당 판정을 선택 후보에 적용하지 않았다. selected 1건의 미판정과 나머지 30건의 범위 밖 미검토를 보존한다. 이 인벤토리의 의미 상태는 A-02 기준이며 병렬 S-04 보고서나 판정은 읽거나 합치지 않았다. 따라서 31건 중 이번 작업에서 새로 완료한 의미 검토는 0건이다. 고유 원인 수는 unknown이며 0원인으로 단정하지 않는다.

## 비용·검증·변경 범위

값 없는 메타데이터 추출·hash 참조 대조·후보 stat·인벤토리 JSON/표 쓰기 구간은 **0.013461458초**였다. 이는 [계측 기록](../../runs/n4-1-a02-first-occurrence-metadata-2026-10-02/inventory-measurement-v1.json)의 단일 구간으로, 앞선 문서 읽기·설정·소통·보고서 작성 시간을 포함하지 않는다. 의미 검토 프로세스는 실행하지 않았고 의미 검토 비용과 사람의 실제 작업시간은 unknown이다. 0개 프로세스를 성공적인 0초 검토로 해석하지 않는다.

- 원시 ledger와 evidence-v2의 참조 SHA-256을 재계산해 일치 확인.
- 67개 연속 시도, 31개 일대일 후보/marker 참조, 시각의 완료 이전 순서, 정렬과 지정 hash 일치 확인.
- 별도 읽기 전용 검산에서 Markdown 31행과 JSON의 순서·attempt·시간·기록 hash 일치 확인. 신규 문서 링크 11개·메타데이터 참조 hash 9개와 착수 시 기록한 입력 파일 11개의 보존도 확인.
- 기존 고정 SCOPE·REPORT·evidence·ledger·runner를 변경하지 않음.
- 신규 파일은 이 보고서 디렉터리와 ignored 작업 기록뿐이며, 공통 계획은 S-03 행만 수정. S-04 영역은 미접근·미수정.
- 코드·테스트 변경 없음. 이번 작업에서는 cargo fmt/clippy/test를 새로 수행하지 않으며 과거 검사 결과를 이번 검증으로 재사용하지 않음.
- 새 퍼징·다른 후보 선택·held-out 실행·commit/push/PR 없음.

S-03은 의미·귀속·맥락 검토가 남아 미완료다. N4-1 전체 완료나 N5 고정을 선언하지 않는다.

## 값 없는 근거

| 자료 | SHA-256 |
|---|---|
| [SCOPE](SCOPE.md) | `4b74d66e02716f412b2718dafbe757cee5e8612b9722a45da406c914a4915845` |
| [전체 occurrence 인벤토리](occurrence-inventory-v1.json) | `344585cd7270db2dec889222eac323d5362088408d70d2d5ce22e23fd0ab48cc` |
| [판정 상태 evidence](evidence.json) | `3c6cc8aca481f939b0d18c7b33639012a28495d92727975b1fea905cb25afb7e` |
| [비용 계측 기록](../../runs/n4-1-a02-first-occurrence-metadata-2026-10-02/inventory-measurement-v1.json) | `cf57abdf09cf4dc0d7c76f7ade53b714006ac74026303bee2e07ae9badf934d0` |

입력 문서별 전체 경로·hash는 SCOPE, 시도·target·후보 경로·기록 hash·시각·결측 사유는 인벤토리에 있다.
