# S-05 결과: A-02 첫 후보 `Subtract()` 한 건의 의미·호출 맥락 검토

2026-10-02 · 버전 `a02-first-semantic-review-v1` · 담당 miiz.

**상태: 완료.** 후보 값을 열기 전에 [사전 SCOPE](SCOPE.md)(SHA-256 `20444675ca7cd0299ea5b706728e3da129e9525a8b8d22ee7f8a8358c42748bf`)를 고정했다. 두 스크립트를 썼다.
- [prepare_context.py](prepare_context.py)(`9f8d6bae…099a`): 값 없는 준비 단계다. 후보는 해시만 계산하고 파싱하지 않았다.
- [review_candidate.py](review_candidate.py)(`c7056645b3d11a2d6ad87d3165c36e36fe82deee96ad361ca7402e340bd90bae`): SCOPE·준비 기록·기준 입력의 해시를 확인한 다음에야 후보를 읽는다.

원시 값은 ignored `runs/n4-1-a02-first-semantic-review-2026-10-02/` 안에만 있다. [S-03](../n4-1-a02-first-occurrence-metadata-2026-10-02/REPORT.md)·[S-04](../n4-1-a02-intdiv-review-2026-10-02/REPORT.md) 파일은 수정하지 않았다.

## 결론

- **선정 재검산: 통과.** A-02 원시 ledger(`8912e249…cb8e`)에서 attempt 1이 parent `NOT SAFE` 관측순 첫째이고 동률이 없다. 선행 attempt 0은 후보가 없다. 경로·SHA-256 `dae6e8b3…3258`·2,107 bytes·workspace 복사본·`result.json`·S-03 인벤토리 첫 행이 모두 일치했다.
- **일반 TCCT(컴포넌트): 위반 확인(출력 차이형).**
  - 후보는 원본 R1CS(제약 1개)를 두 방법 모두로 만족한다.
  - 같은 입력의 정직한 witness와 `main.d`, `main.c`가 다르다. 소스 평가 순서상 첫 차이는 `main.d`(8행 `d <-- 1`)다.
- **단일 원인 귀속: 귀속됨(`Subtract`의 무제약 승수 `d`).** SCOPE §4의 다섯 조건이 모두 성립했다.
  - 출처를 확인한 실제 수정본(`b8f92bde`, `c <== (a - b)`)은 후보를 두 방법 모두로 거부했다(Python 불만족 1, snarkjs `NOT CORRECT`).
  - 정직한 대조는 두 방법 모두로 수용했다. 수정본 정직 계산은 성공했고 출력이 원본 정직 출력과 같다.
- **S-01과의 관계: 같은 site 원인 근거 성립(s1–s4 모두 성립).** R1CS 바이트(`14c18b08…`), 소스 지점, 차이 집합·첫 차이, 같은 실제 수정본(소스 `c5d6aa9d…`, R1CS `842a28ea…`)의 거부·수용이 같다.
  - 추가로, 이번 후보로 만든 `.wtns`(`c78c7dd5…`)와 정직한 witness(`43dacdf9…`)는 S-01 run의 두 파일과 바이트가 같다. 즉 신호 값까지 S-01 후보와 같다.
  - P2 block 1 기록도 같은 zkFuzz seed `2026092931`을 쓴다. zkFuzz의 결정성 자체는 검증하지 않았다.
  - 따라서 이 후보는 새 고유 원인도, 새 독립 사례도 아니다.
- **도구 라벨:** `UnderConstrained-NonDeterministic`. 판정 근거로 쓰지 않았다.
- **호출 맥락(E2): 위치마다 따로 판정했다.**
  - K1·K2: public 입력으로 바로 공급되므로 입력 수준에서 도달할 수 있다.
  - K3·K4: 상수 입력(50000000)이 후보 값과 달라 이 후보로는 **도달 불가**다.
  - K5: `ScoringFunction` 출력의 역산이 필요하므로 미판정이다.
- **entrypoint 투영(E3): K1·K2 두 위치 모두 성공했다(index 0).** 한 위치의 `d`만 후보 값으로 바꾼 전체 witness가 원본 entrypoint R1CS(제약 196,096개)를 두 방법 모두로 만족했다. 같은 public 입력의 정직한 출력과 비교하면 출력 1,024개 중 `main.new_score[0]` 하나가 다르다.
- **entrypoint TCCT(E4): 위반(출력 차이형).** 이 결론은 고정한 두 입력 X1·X2에서의 존재 증명이다. 프로젝트 의미(E5)는 판정하지 않았다. 위 컴포넌트 판정과는 별도 층이다.
- **최초 확인 대상 시간(T): 계산했다.** S-04보다 앞선 occurrence는 attempt 1 하나이며, 이번에 검토가 끝났다. 최초 확인 대상은 attempt 1이다. 캠페인 offset 기준 경계는 다음과 같다.
  - 하한: zkFuzz 프로세스 시작 1.103817667초
  - 관측 상한: parent `NOT SAFE` 관측 1.108243333초
  - 후보 파일 존재 상한: 시도 완료 1.117240042초

  이 값들은 정확한 생성시각이 아니며, 검토 시간을 포함하지 않는다.
- **남은 검토:** 31건 중 attempt 1(S-05)과 attempt 8(S-04)만 검토했다. 나머지 **29건은 미검토**다(S-03 인벤토리 순서 3–31).

| 단계 | 판정 | 방법과 근거 |
|---|---|---|
| 선정·연결 | 통과 | 67 attempt, 31 occurrence, 관측 결측 0. 정렬 키는 관측 offset → attempt → 경로. 둘째는 S-04의 attempt 8 |
| 재현 조건 | 통과 | 준비 단계와 검토 단계에서 각각 재컴파일했다. 컴포넌트·수정본·entrypoint R1CS와 `.sym`, entrypoint WASM이 준비 기록과 모두 같다. 컴포넌트 R1CS `14c18b08…`는 A-02 preflight와, entrypoint R1CS `39022971…`는 A-02 whole preflight와 바이트가 같다 |
| A1. 원본 제약 전체 만족 | 통과 | wire가 있는 이름 4개(`main.a/b/c/d`)가 후보 이름 4개와 정확히 대응하고 정규 값이다. (a) Python 평가 불만족 0, (b) 후보 `.wtns`(`c78c7dd5…`)의 snarkjs `WITNESS IS CORRECT`. 로컬 `.wtns` 작성기의 양성 대조도 통과했다 |
| A2. 정직한 계산과의 관계 | 출력 차이 | 원본 WASM 정직 witness(`43dacdf9…`)는 snarkjs `CORRECT`, Python 불만족 0이다. 다른 신호는 `main.d`, `main.c`이고 첫 차이는 `main.d`다. abort는 없다 |
| A3. 일반 TCCT 속성 | **위반** | 입력 전제(정규 필드 원소)가 성립하고, 원본 제약을 만족하면서 정직한 출력과 다른 `c`를 가진다 |
| B1. 수정본의 후보 거부 | 거부(두 방법) | 수정본 R1CS(wire 4, 제약 1)에 `(a, b, c)`를 이름으로 대응했다. Python 불만족 1, snarkjs `NOT CORRECT`(`718feeba…`) |
| B2. 수정본의 정직 대조 수용 | 수용(두 방법) | 정직한 `(a, b, c_h)`: Python 불만족 0, snarkjs `CORRECT`(`c3f9c927…`) |
| B3. 수정본 정직 계산 | 성공·출력 같음 | 수정본 WASM 계산이 성공했고, 출력이 원본 정직 출력과 같다 |
| D. 단일 원인 귀속 | **귀속** | 차이 `{d, c}`·첫 차이 `d`, `a ≠ b`, B1 거부, B2·B3 수용, 수정본 출처 확인. 수정본은 `d`를 없애고 `c = a − b`만 남기므로 거부 사유가 하나다 |
| S. S-01과 같은 원인 | 같은 site 원인 근거 성립 | s1–s4 모두 참. 신호 값도 S-01 후보와 같다(위 결론) |
| C. 도구 라벨 | `UnderConstrained-NonDeterministic` | 근거로 쓰지 않음 |

## 호출 위치별 판정

entrypoint `IncentiveMechansim(256, 40)`의 `Subtract` 인스턴스 1,280개를 `.sym`에서 모두 열거했다.
- 다섯 종류(K1–K5) × index 0–255로 빠짐없이 분류됐고, 미분류는 0개다.
- `MetricNormalized`·`IncentiveMetric`의 호출은 include되지 않아 인스턴스가 없다.
- template 이름으로 한 위치를 고르지 않았다.

| 종류 | 위치(index i) | 입력 대응 | E2 도달성 | E3 투영(i = 0) |
|---|---|---|---|---|
| K1 | `response_time_normalized_fn[i].subtract1` | `a` ← `response_time[i]`, `b` ← `minimum_response_time[i]` | 입력 수준 도달 가능 | **성공**: 출력 차이 1개(`new_score[0]`), 다른 wire 168개 |
| K2 | `response_time_normalized_fn[i].subtract2` | `a` ← `maximum_response_time[i]`, `b` ← `minimum_response_time[i]` | 입력 수준 도달 가능 | **성공**: 출력 차이 1개(`new_score[0]`), 다른 wire 272개 |
| K3 | `…scoring_function.temp_sub[0]` | `a` ← 중간값, `b` ← 상수 | 도달 불가(상수 불일치) | 해당 없음 |
| K4 | `…scoring_function.temp_sub[1]` | `a` ← 상수, `b` ← 중간값 | 도달 불가(상수 불일치) | 해당 없음 |
| K5 | `response_time_reward_metric_fn[i].subtract` | `a` ← `scaling`, `b` ← `ScoringFunction` 출력 | 미판정(역산 미수행) | 해당 없음 |

**투영 방법(SCOPE §5, 한 번만 실행).**
- **입력:** 기준 입력 B0(`13c9eb44…`)는 후보를 열기 전에 정상 계산과 두 방법의 제약 검사를 통과시켜 고정했다. X1·X2는 B0의 index 0에서 대응 입력 두 개만 후보 `a`, `b`로 바꾼 것이다.
- **이탈 생성기:** clean tree 복사본에서 `Subtract`의 8행 hint만 "입력이 후보 `(a, b)`일 때 `d`를 후보 값으로" 바꿨다. 이 생성기의 R1CS와 `.sym`은 원본과 바이트가 같다. 제약은 바꾸지 않고 증명자 쪽 계산만 바꾼 것이다.

**두 위치 모두에서 확인한 것.**
- X의 원본 정직 계산이 성공했고, snarkjs `CORRECT`였다.
- 이탈 witness W′가 원본 R1CS에 대해 Python 불만족 0/196,096이고 snarkjs `CORRECT`였다.
- 1,280개 `d` 중 1이 아닌 것은 목표 인스턴스 하나이며 값이 후보 `d`와 같다. K1은 wire가 있는 `c`도 후보 값과 같고, K2의 `c`는 제거돼 제약으로 함의된다.
- public 입력 2,825개가 정직 witness와 같다.

W′는 목표 인스턴스의 `d` 하나만 정직 계산에서 벗어났고, 나머지 값은 원본 생성기가 그 이탈을 정직하게 전파한 결과다. 따라서 다른 결함(예: `IntDiv`의 무제약 출력)의 자유도는 쓰지 않았다.

## 원인 중복과 세는 규칙

- **S-01과의 관계:** 이 후보는 S-01과 같은 site 원인이고, 신호 값도 S-01의 P2 후보와 같다. 반복 seed에서 나온 중복 반례로 보고 새 고유 원인이나 독립 사례로 세지 않는다. 최종 등록과 대칭 집계는 N5에서 정한다.
- **S-04와의 관계:** S-04 `IntDiv(40)`과는 소스 지점과 수리 관계가 달라 site 원인으로 합치지 않는다. 같은 fix PR(`b8f92bde`)·zkbugs 대표 항목이라는 클러스터 관계만 있다.
- **entrypoint 결과:** 같은 site 원인의 호출 위치 두 곳에서 확인된 것이다. 원인 수나 프로젝트 수를 늘리지 않는다.

## 증거 경로와 해시

| 자료 | 경로(`runs/n4-1-a02-first-semantic-review-2026-10-02/` 아래) | SHA-256 |
|---|---|---|
| 준비 기록(값 없음) / 준비 ledger | `prep-v1/prep.json`, `prep-v1/ledger.json` | `362ef99bd1a3c29fbaa53e5f58cf03f30c7d29d1e03e4e739e331824bc1dc8d3` / `a59f1888b94d437bbb3318690fcf6890b4fb7e5f97bc1ed3045bab29a7877653` |
| 기준 입력 B0 / B0 정직 witness | `prep-v1/base/input.json`, `prep-v1/base/witness.wtns` | `13c9eb44dc735d1c0cd5ff30e49df13640764468e63594bd1f05470af71dd9ca` / `0c94af6d1e2a511a46ea592114362fd060b5b457458892a1dc42ec9cf24425ab` |
| 값 없는 결과 / 명령 ledger | `run-v1/result.json`, `run-v1/ledger.json` | `048c0c713723372f8285a5f05fdc3e607a68ac838a14b5a0e76d29ebba0f4e6c` / `033afb9f8d86f835d6dc65168cd7053c45859c628262202ff2f08f9839e563dc` |
| 원시 값(ignored, 값 포함) | `run-v1/raw-values.json` | `482713fd0dd761e83c62ee5363d9cec637d50785c8fef65c541b65ca454e4bde` |
| 후보 `.wtns` / 정직 witness | `run-v1/candidate.wtns`, `run-v1/honest/witness.wtns` | `c78c7dd5fcd81cba413b3b23199ed20edd8e58600e7dcefc35012f463d6e5eec` / `43dacdf96aa068442987de5f9829bd93a2d71c5c26dad62adea6739e99bc9ac4` |
| 수정본 검사용 `.wtns`(후보 / 정직 대조) | `run-v1/fixed-candidate.wtns`, `run-v1/fixed-honest-control.wtns` | `718feeba5ec7216dee4b44064e5305130fafc8b6b1cc7f324c49efd805c7dd5e` / `c3f9c927dc4185ee0cf119282746060c8aeae0adc85c0df94e9e56e97512d535` |
| hint 소스(후보 값 포함) | `run-v1/projection/hint-tree/src/subtractTensor.circom` | `60abc80d7b546ed265e75651ed5c76b6cab0af3b79e443855fef7de63afba95f` |
| K1 입력 X1 / 정직 witness / 이탈 witness | `run-v1/projection/K1/{honest/input.json, honest/witness.wtns, deviated/witness.wtns}` | `f6d61827…17e8db` / `8d54c4d3…bf85d6` / `cc9905e0…0204f` |
| K2 입력 X2 / 정직 witness / 이탈 witness | `run-v1/projection/K2/{honest/input.json, honest/witness.wtns, deviated/witness.wtns}` | `2874d5e4…3589b9` / `1b395362…90bb7e` / `2dfcdc79…168beed` |
| entrypoint R1CS / `.sym` | `run-v1/compiled-entry/circuit.{r1cs,sym}` | `39022971…7220` / `3f984da9…6ea8` |

도구는 circom 2.2.3(`89918878…6227`), node 26.0.0(`08dad058…c164`), snarkjs 0.7.6(`cli.cjs` `6d787e37…051a`)이다. zkFuzz는 실행하지 않았다.

snarkjs 결과는 다음 규칙으로만 판정했다: exit 0과 `WITNESS IS CORRECT`이면 만족, `WITNESS IS NOT CORRECT`이면 불만족, 그 밖에는 미판정. Python 평가기는 R1CS 파일의 모든 제약을 직접 계산한다. 후보·대조 할당은 `.sym` 이름 대응으로 만든 벡터를 쓰고, WASM이 만든 witness는 `.wtns`를 직접 읽는다.

## 검토 비용

**준비 단계(후보 미개봉):** 프로세스 5개, wall 합계 3.172초. 스크립트 전체는 3.883초다(기준 witness의 Python 평가 포함).
- 컴파일 3회: 1.790초
- 기준 입력 정직 계산: 0.242초
- 기준 snarkjs 검사: 1.140초

**검토 단계:** 프로세스 19개, wall 합계 9.243초. 스크립트 전체는 10.250초다(Python 평가 포함).
- 컴포넌트·수정본 컴파일 2회: 0.027초
- entrypoint 컴파일 2회(원본·hint): 3.422초
- 컴포넌트 snarkjs 검사 5회: 1.082초
- 컴포넌트 witness 계산 2회: 0.088초
- entrypoint witness 계산 4회: 0.578초
- entrypoint snarkjs 검사 4회: 4.047초

**담당자 작업 구간(2026-10-02, UTC):**
- 03:47Z 인계 확인·계획 행 시작
- 03:48–03:59Z 입력 문서·소스·호출 위치 확인, 준비 스크립트 작성
- 04:00:22–04:00:26Z 준비 실행
- 04:03–04:04Z SCOPE 작성·해시 고정
- 04:06:58–04:07:08Z 검토 실행
- 04:07–04:09Z 결과 대조
- 04:10–04:12Z 보고서 작성, 원시 값·링크·보존 해시 점검

사람의 실제 작업 시간은 계측하지 않아 unknown이다. 3시간 상한 안에서 끝냈다.

## 주장할 수 있는 범위와 한계

사용할 수 있는 문장은 다음 하나다.

> A-02 small-first에서 parent `NOT SAFE` 관측순 첫째인 `Subtract()` 후보 한 건은 원본 제약을 만족하면서 같은 입력의 정직한 계산과 출력이 달라 컴포넌트 수준 일반 TCCT를 위반했고, 출처를 확인한 실제 수정본의 단일 조건 거부로 `Subtract`의 무제약 승수 원인에 귀속됐다. 같은 후보 값을 production entrypoint의 두 호출 위치(K1·K2, index 0)에 단일 지점으로 투영한 전체 witness는 원본 entrypoint 제약을 만족하면서 같은 public 입력의 정직한 출력과 `new_score[0]`이 달라, 그 두 입력에서 entrypoint 수준 TCCT 위반이 확인됐다.

다음은 이 결과로 주장하지 않는다.
- **새 원인·독립 사례:** S-01과 같은 site 원인이고 신호 값까지 같다(같은 seed). 고유 원인 수를 늘리지 않는다.
- **entrypoint 일반화:**
  - index 1–255, K5 위치, 다른 입력에서의 결과는 실행하지 않았다.
  - K3·K4의 도달 불가는 이 후보 값에 대한 판정이며, 그 위치에 다른 반례가 없다는 뜻이 아니다.
  - X1·X2가 현실적인 응답시간 입력인지, 이 출력 차이가 보상에 미치는 영향 같은 프로젝트 의미(E5)는 판정하지 않았다.
- **시간:**
  - T의 세 값은 캠페인 시계의 관측 경계다. 정확한 생성시각이 아니며 사람의 검토 시간도 포함하지 않는다.
  - 통째 campaign은 후보가 0개였지만, 이 한 개발 쌍으로 탐지 우위를 주장하지 않는다.
- **남은 occurrence:** 29건은 미검토다. 이 판정을 다른 `Subtract()` occurrence(attempt 22·43·64)에 복사하지 않는다.

**값 노출 기록.** 결과 대조 중 hint 소스 diff를 3자리 이상 숫자만 가려 출력했다. 이 때문에 짧은 후보 값 두 개가 검토 터미널에 표시됐다. 이 값들은 어떤 추적 파일에도 옮기지 않았다.

**수정하지 않은 것.**
- S-03·S-04·S-01 파일, A-02 원문·코드, record/aggregate 코드
- 새 퍼징, 다른 후보 선택, 다른 투영 입력 재시도, held-out 실행
- commit·push·PR

Rust 코드는 바꾸지 않았다. 새 코드는 이 디렉터리의 Python 검토 스크립트 두 개뿐이다.
