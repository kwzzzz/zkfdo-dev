# A-02 첫 두 후보 의미 검토 인계

2026-10-02 · 담당 miiz · `a02-first-two-review-handoff-v1` · 상태: **S-03·S-04 미착수**. 이 문서는 개발용 A-02의 새 후보에서 실제 일반 TCCT 확인 여부를 판정할 다음 범위를 지정한다. [A-02 SCOPE](../reports/n4-1-policy-a-engine-2026-10-02/SCOPE.md)와 [결과](../reports/n4-1-policy-a-engine-2026-10-02/REPORT.md), [보정 evidence](../reports/n4-1-policy-a-engine-2026-10-02/evidence-v2.json)는 보존한다. 과거 [S-01](../reports/n4-1-p2-candidate-review-2026-10-02/REPORT.md)과 [S-02](../reports/n4-1-p2-clamp-review-2026-10-02/REPORT.md)의 판정을 새 후보에 복사하지 않는다.

## 왜 이 두 건인가

A-02는 같은 실행기로 통째 1/1과 small-first 21/21을 각각 600초 돌렸다. 통째는 후보 없이 timeout됐고, 분할은 67시도에서 후보 파일 31개를 냈다. 31개 파일 해시는 서로 다르지만 원인 중복 여부와 의미 판정은 모두 미검토다. 두 후보는 **값을 읽지 않고** small-first 원시 ledger의 parent `NOT SAFE` 관측 offset을 오름차순으로 정해 고른 최초 두 occurrence다. 동률이면 attempt index, 이어서 후보 경로의 사전식 순서를 쓴다. 나머지 29개는 여전히 전체 검토 분모에 남는다. 앞선 시도의 `no-candidate`·`timeout`은 후보 없음과 검토 미완료를 구분해 보존한다.

| 작업 | A-02 attempt / target | parent 관측 offset / 시도 완료 상한 | 값이 있는 후보 경로(ignored `runs/` 아래) | SHA-256 |
|---|---|---|---|---|
| S-03: 첫 occurrence | 1 / `Subtract()` | 1.108243333초 / 1.117240042초 | `runs/n4-1-policy-a-engine-2026-10-02/small-first-campaign-v1/attempts/000001/candidates/zkfdo-targets/src__subtractTensor__Subtract.circom_CGijXpcMP3_counterexample.json` | `dae6e8b397f2b25269f9711443449b73ba6ba86f4ca7a4397cf318fbfc143258` |
| S-04: 둘째 occurrence | 8 / `IntDiv(40)` | 77.996707750초 / 78.005990458초 | `runs/n4-1-policy-a-engine-2026-10-02/small-first-campaign-v1/attempts/000008/candidates/zkfdo-targets/src__integerDivision__IntDiv_40.circom_5vPZul9Pul_counterexample.json` | `f5a346327427a1b3a288fc099f8fbcd0635f8b4c289b57bd5f22fa0a1f08a143` |

두 parent offset은 로그를 읽은 시각이다. 정확한 후보 생성시각이 아니다. S-03이 확인되면 이 캠페인의 **처음 관측된 후보**에 대한 확인 결과를 말할 수 있다. S-03이 비해당·미판정이라면 S-04가 확인되더라도 S-03의 미판정 해소 전에는 ‘최초 확인 시간’을 확정하지 않는다. 두 후보가 모두 확인되더라도 31 occurrence를 두 원인으로 세지 않는다. 범위가 두 후보에만 한정된 결과와 31건 전체의 원인 수·오탐률을 구분한다.

## 공통 판정·중단 기준

각 담당은 **자신의 후보 값을 열기 전에** 독립된 새 `SCOPE.md`에 후보·A-02 ledger/evidence/runner·원본 소스와 컴파일 조건의 해시, 입력 전제, 일반 TCCT의 정직한 계산 대비 출력 차이 또는 abort, 원본 R1CS 전체 만족, 필요하면 도구 특화/프로젝트 명세를 별도 층으로 정의한다. 연결 해시나 재컴파일 R1CS가 맞지 않으면 그 의존 판정을 중단하고 미판정으로 남긴다. 후보 파일명, `NOT SAFE`, zkFuzz 라벨, 같은 template 위치만으로 위반이나 귀속을 확정하지 않는다.

원본 제약 검사는 독립된 방법 둘 이상을 사용하고, 정직한 witness는 같은 후보 입력으로 다시 계산한다. 동일 출력·정상 실행이면 그 후보의 일반 TCCT는 위반 아님이다. 속성이 위반될 때만 첫 divergence, 중첩 인스턴스, 중복 원인과 실제 수정본 또는 동등한 독립 근거로 단일 원인 귀속을 시도한다. 귀속이 모호하면 확인된 위반과 미귀속 원인을 분리한다. 원본 entrypoint 호출 맥락·입력 전제·도달성·투영과 entrypoint TCCT는 **컴포넌트 판정과 분리**해 확인 가능 범위까지만 검사하고, 실패를 음성으로 바꾸지 않는다. 정상 경계 NB-01 결과를 반례 투영의 증명으로 쓰지 않는다.

새 퍼징·다른 후보 선택·held-out 자료 실행은 하지 않는다. 원시 값과 산출물은 ignored `runs/`에, 공유 보고서에는 경로·해시·값 없는 판정·시간·비용만 기록한다. 프로세스 시간과 사람의 실제 검토 시간은 구분하고 계측하지 못한 값은 unknown이다. 두 작업은 서로 다른 SCOPE/REPORT와 계획 행만 직접 수정한다. 사전 범위를 채우기 전에 후보 값을 열지 않는다. 3시간 안에 컴포넌트 또는 맥락 판정이 끝나지 않으면 완료된 층·미완료 층·정확한 장애를 기록하고 확장 여부를 다시 결정한다. 전체 31건 리뷰, 프로젝트 원인 수, N4-1 통과 또는 N5 고정은 자동 선언하지 않는다.

## 작업 분리

- **S-03:** 값 없는 31건 occurrence 인벤토리(경로·해시·attempt·target·parent 시각·결측 사유)를 먼저 만들고 위 표의 첫 후보만 검토한다. 31건을 열거나 자동 판정하지 않는다. 결과가 기존 `Subtract` 원인과 같을 가능성은 검증할 가설로만 두고, 동일 R1CS·원인 여부를 실제 확인한다. entrypoint 층에는 확인/배제/미판정과 근거를 별도 기록한다. 담당은 계획의 S-03 행만 갱신한다.
- **S-04:** A-02 원시 ledger로 선정 규칙과 둘째 후보 해시를 독립 재검산하고 위 표의 `IntDiv(40)` 한 건만 검토한다. S-01·S-02와 다른 template라는 사실은 독립 원인을 뜻하지 않는다. 중첩 인스턴스의 첫 divergence와 원인 중복을 특히 확인한다. 담당은 계획의 S-04 행만 갱신한다. S-03의 작업 파일·보고서는 건드리지 않는다.

두 결과가 나오면 31개 전체 인벤토리·검토 비용·미판정 원인을 보고, 남은 후보를 사전 순서대로 전수 검토할지와 독립 사례로 넘어갈 준비가 됐는지를 다시 판단한다. 통째에 후보가 없는 이번 한 쌍만으로 양쪽 후보의 같은 수준 의미 검토 사례를 충족했다고 쓰지 않는다.
