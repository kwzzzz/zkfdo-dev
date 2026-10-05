# S-05 사전 범위: A-02 첫 후보 `Subtract()` 한 건의 의미·호출 맥락 검토

2026-10-02 · 버전 `a02-first-semantic-review-v1` · 담당 miiz.

**상태:** 후보 값을 열기 전에 고정했다(2026-10-02T04:04Z). 이 시점까지 후보 파일은 해시와 크기만 계산했고 파싱하지 않았다. 근거는 [인계](../../docs/next_s03_context_handoff_2026-10-02.md)(`fc1b5590…68e5`)의 S-05 절이다.
- [S-03](../n4-1-a02-first-occurrence-metadata-2026-10-02/REPORT.md)은 메타데이터 부분 완료 기록으로 보존한다.
- S-01·S-04의 판정은 이 후보에 복사하지 않는다.
- 아래 해시와 개수는 값 없는 준비 스크립트 [prepare_context.py](prepare_context.py)(`9f8d6bae…099a`)의 기록 `runs/n4-1-a02-first-semantic-review-2026-10-02/prep-v1/prep.json`(`362ef99b…c8d3`)에서 왔다.

## 1. 선정과 연결(값을 읽지 않음)

- **ledger 재정렬:** A-02 원시 ledger(`8912e249…cb8e`)를 직접 정렬했다. 67 attempt, 31 occurrence, parent 관측 결측 0이다. 정렬 키는 parent `NOT SAFE` 관측 offset → attempt → 경로다.
  - 1번째는 attempt 1(target `sha256:1830b599…`, `Subtract()`)이며 동률이 없다. 2번째는 S-04의 attempt 8이다.
  - 선행 attempt 0(`AssertBit()`)은 `no_candidate`이고 후보·`NOT SAFE` 관측이 없다.
- **후보 파일:** `runs/n4-1-policy-a-engine-2026-10-02/small-first-campaign-v1/attempts/000001/candidates/zkfdo-targets/src__subtractTensor__Subtract.circom_CGijXpcMP3_counterexample.json`
  - SHA-256 `dae6e8b397f2b25269f9711443449b73ba6ba86f4ca7a4397cf318fbfc143258`, 2,107 bytes. workspace 복사본도 같다.
  - attempt 1 `result.json`(`6b219e38…8a42`)은 ledger 기록과 같다.
- **S-03 기록:** [인벤토리](../n4-1-a02-first-occurrence-metadata-2026-10-02/occurrence-inventory-v1.json)(`344585cd…48cc`)의 첫 행(순서·attempt·해시·두 offset)과 일치한다. S-03 SCOPE `4b74d66e…5845`, REPORT `75879652…f6c5`, evidence `3c6cc8ac…b7e`, INVENTORY `dd222bda…c47d`를 고정한다.
- **attempt 1 시각(캠페인 단조시계 offset, 초):**

  | 항목 | offset |
  |---|---|
  | dispatch | 1.092691708 |
  | zkFuzz 프로세스 시작 | 1.103817667 |
  | parent `NOT SAFE` 관측 | 1.108243333 |
  | 프로세스 종료 | 1.115699667 |
  | 시도 완료 | 1.117240042 |

  zkFuzz 출력에는 내부 후보 생성시각이 없다.
- **A-02 고정 자료:** SCOPE `6908aeb4…02fa`, REPORT `0c345ffa…70a7`, evidence-v2 `41855eae…b8e`, small-first spec `bc9e8f58…09e6`, whole spec `62c68534…1314`, source manifest `69574bb4…75e9`, 실행기 `c408ccba…874d`, small-first preflight `284ff020…442e`, whole preflight `fd2d5698…31a9`.

## 2. 원본·수정본·도구

- **프로젝트:** `inference-labs-inc/subnet-2-circom` revision `d310309c…`. A-02 clean tree는 manifest 37개 파일과 모두 같다.
  - 로컬 클론의 해당 commit blob과 바이트가 같은지 다시 확인했다: `src/subtractTensor.circom`(`502ee44b…3cc1`, blob `f4f07f3c…`), `src/circuit.circom`(`f1b6abc4…7464`, blob `8a14db94…`), `src/responseTimeNormalized.circom`(`8a7a72e2…2f`, blob `14641cc8…`), `src/responseTimeMetric.circom`(`5d23e694…d167`, blob `db0ad8ff…`).
- **컴파일:** circom 2.2.3(`89918878…6227`), `--r1cs --prime bn128`, 기본 최적화, `-l` clean tree·zkbugs dependencies·circomlib에 `--sym --wasm`만 더한다.
- **컴포넌트:** wrapper `zkfdo-targets/src__subtractTensor__Subtract.circom`(`1665e793…8c7b`, `component main = Subtract();`).
  - 재컴파일 R1CS `14c18b08…b04f`는 A-02 preflight와 같다. wire 5(이름 `main.a/b/c/d` 모두 wire 있음), 출력 1, 비공개 입력 2, 제약 1. `.sym` `b378da79…1a47`.
- **수정본:** fix commit `b8f92bde…`의 `src/subtractTensor.circom`을 git object chain으로 꺼냈다(blob `ede21538…`, SHA-256 `c5d6aa9d…23ba`). 내용은 `c <== (a - b);`이고 `d`가 없다.
  - 같은 wrapper로 컴파일한 R1CS는 `842a28ea…0ac8`(wire 4, 제약 1), `.sym` `052e3ee4…547d`다.
  - 수정 소스와 수정본 R1CS는 S-01이 쓴 수정 snapshot·수정본 R1CS와 바이트가 같다. 이는 산출물 동일성일 뿐 S-01 판정의 복사가 아니다.
- **production entrypoint:** `src/circuit.circom`의 `IncentiveMechansim(256, 40)`이다(모든 입력 public).
  - 재컴파일 R1CS `39022971…7220`은 A-02 whole preflight와 같다. wire 197,898, 출력 1,024, public 입력 2,825, 제약 196,096.
  - `.sym` `3f984da9…6ea8`, WASM `e418fb74…0b27`.
- **도구:** node 26.0.0(`08dad058…c164`), snarkjs 0.7.6(`cli.cjs` `6d787e37…051a`). zkFuzz는 실행하지 않는다.

## 3. 판정층

| 층 | 입력 전제 | 정의와 판정 |
|---|---|---|
| **A. 일반 TCCT(컴포넌트, 주 비교층)** | `a`, `b`는 정규 BN128 필드 원소(A-02 `field_only`) | **A1:** 후보 할당이 원본 R1CS 전체를 만족하는지 두 방법으로 본다: (a) Python R1CS 평가, (b) 후보 `.wtns`의 snarkjs 검사. 이름 대응은 엄격 규칙이다(wire가 있는 이름 모두 존재, 정규 값). snarkjs는 exit 0과 `WITNESS IS CORRECT`이면 만족, `WITNESS IS NOT CORRECT`이면 불만족, 그 밖은 미판정이다. 로컬 `.wtns` 작성기는 정직한 witness로 양성 대조한다. **A2:** 원본 WASM으로 같은 입력의 정직한 witness를 계산해 wire별로 비교한다. **A3:** A1 만족이고 `main.c`가 다르거나 정직한 계산이 assert로 abort하면 위반이다. 출력이 같고 정상 실행이면 **명시적 비해당**이다 |
| **첫 차이** | A2 | 소스 평가 순서는 입력 `a`, `b` → `d`(8행 `d <-- 1`) → `c`(9행)다. 차이 집합과 이 순서의 첫 차이를 기록한다 |
| **B. 실제 수정본층** | 수정본 출처 확인됨 | **B1:** 후보의 `(a, b, c)`를 수정본 R1CS에 이름으로 대응해 두 방법으로 검사한다(거부 기대). **B2:** 정직한 `(a, b, c_h)` 대조를 두 방법으로 검사한다(수용 기대). **B3:** 수정본 WASM의 같은 입력 정직한 계산이 성공하고 출력이 `c_h`와 같은지 본다 |
| **C. zkFuzz 라벨** | — | `5_flag` 유형만 기록한다. 근거가 아니다 |
| **D. 단일 원인 귀속** | A3 위반일 때만 | §4 |
| **S. S-01과 같은 원인인지** | D 귀속일 때만 | §4 |
| **E. 호출 맥락·entrypoint** | A3 위반일 때만 | §5. 컴포넌트 판정과 섞지 않는다 |
| **T. 최초 확인 대상 시간** | A3가 위반 또는 명시적 비해당일 때만 | §6 |

## 4. 원인 귀속과 같은 원인 판정

**D. 단일 원인 귀속(`Subtract`의 무제약 승수 `d`).** 다음이 모두 성립할 때만 귀속한다. 하나라도 아니면 미판정이다.
1. A3 위반이고, 정직한 witness와 다른 wire 이름이 정확히 `{main.c, main.d}`이며 첫 차이가 `main.d`다.
2. `a ≠ b`다(같으면 `d`와 무관하게 `c = 0`).
3. B1에서 수정본이 후보를 두 방법 모두로 거부한다(Python 불만족 1개 이상, snarkjs `NOT CORRECT`).
4. B2에서 정직한 대조를 두 방법 모두로 수용하고, B3의 수정본 정직 계산이 성공하며 출력이 `c_h`와 같다.
5. 수정본 출처가 git object chain으로 확인됐다. 수정본은 `d`를 없애고 `c = a - b` 하나만 남기므로, 거부 사유는 이 관계 하나다.

**S. S-01과 같은 원인.** S-01의 판정문은 쓰지 않는다. S-01이 기록한 산출물 해시와 이번 후보의 증거만 비교한다. D 귀속에 더해 다음이 모두 성립하면 "S-01과 같은 site 원인 근거 성립"으로 적는다.
- (s1) 이번 컴포넌트 R1CS가 S-01의 취약 R1CS `14c18b08…`와 바이트가 같다.
- (s2) 같은 소스 지점이다(`src/subtractTensor.circom` `502ee44b…`의 `Subtract`).
- (s3) 이번 차이 집합이 `{c, d}`이고 첫 차이가 `d`다.
- (s4) 같은 실제 수정본(소스 `c5d6aa9d…`, R1CS `842a28ea…`)이 이번 후보를 거부하고 이번 정직한 대조를 수용한다.

인계의 방향에 따라 같은 site 원인은 반복 seed·호출 위치와 함께 한 원인으로 병합하며 새 고유 원인으로 세지 않는다. 최종 등록과 대칭 집계는 N5에서 정한다. `IntDiv`(S-04)와는 소스 지점과 수리 관계가 다르므로 site 원인으로 합치지 않는다. 같은 fix PR/zkbugs 대표 항목이라는 클러스터 관계만 기록한다.

## 5. 호출 맥락과 entrypoint 투영

**E1. 호출 위치(입력 대응).** 원본 entrypoint에서 `Subtract`가 인스턴스화되는 위치는 다음 다섯 종류다. 각 종류는 배치 index 0–255마다 하나씩 있다.
- `.sym` 열거: `{a, b, c, d}` 신호를 가진 인스턴스 1,280개가 모두 이 다섯 종류로 분류되고, 미분류는 0개다.
- `MetricNormalized`·`IncentiveMetric`의 `Subtract` 호출은 entrypoint에 include되지 않아 인스턴스가 없다.
- template 이름으로 한 위치를 고르지 않는다.

| 종류 | 인스턴스 경로(i = 0–255) | `a` ← | `b` ← | `c`의 하류 사용 | `.sym` wire |
|---|---|---|---|---|---|
| K1 | `response_time_normalized_fn[i].subtract1` | public 입력 `response_time[i]` | public 입력 `minimum_response_time[i]` | `IntDiv(40)` `in[0] = c·scaling` | `a`,`b` 제거, `c`,`d` 있음 |
| K2 | `response_time_normalized_fn[i].subtract2` | public 입력 `maximum_response_time[i]` | public 입력 `minimum_response_time[i]` | `IntDiv(40)` `in[1] = c` | `a`,`b`,`c` 제거, `d` 있음 |
| K3 | `response_time_reward_metric_fn[i].scoring_function.temp_sub[0]` | 중간값 `ResponseTimeNormalized` 출력 | 상수 50000000 | `temp_shift[0] = c·lt.out` | `a`,`b` 제거, `c`,`d` 있음 |
| K4 | `response_time_reward_metric_fn[i].scoring_function.temp_sub[1]` | 상수 50000000 | 중간값 `ResponseTimeNormalized` 출력 | `temp_shift[1] = c·(1 − lt.out)` | `a`,`b` 제거, `c`,`d` 있음 |
| K5 | `response_time_reward_metric_fn[i].subtract` | public 입력 `scaling` | 중간값 `ScoringFunction` 출력 | `temp_mul = c·RESPONSE_TIME_WEIGHT` | `a`,`b` 제거, `c`,`d` 있음 |

**E2. 도달성(이 후보의 `(a, b)`가 그 위치에 들어갈 수 있는가).**
- K1·K2: 두 입력이 모두 public 입력이므로 후보 값을 그대로 공급할 수 있다(입력 수준 도달 가능). 정직한 계산 완료와 전체 witness는 E3에서 본다.
- K3: 후보 `b`가 50000000이 아니면 **도달 불가**(제약이 `b`를 상수로 고정)다. 같으면 `a`가 정직한 `ResponseTimeNormalized` 출력과 같아야 하는데, 역산을 하지 않으므로 미판정이다.
- K4: 후보 `a`에 대해 같은 규칙을 적용한다.
- K5: `b`가 `ScoringFunction` 출력이다. 역산·탐색을 하지 않으므로 **미판정**이다.

**E3. 전체 witness 투영(K1·K2, i = 0만).** 다른 255개 index는 같은 소스 대응이지만 실행하지 않는다. 다른 입력이나 재시도는 없다.
- **기준 입력 B0:** 후보와 무관하게 고정했다(`input.json` `13c9eb44…d9ca`). 원본 정직 계산이 성공했고, 그 witness(`0c94af6d…25ab`)는 snarkjs `CORRECT`, Python 불만족 0, `Subtract` 1,280개의 `d`가 모두 1이다.
  - 스칼라: `RATE_OF_DECAY` 2e7, `RATE_OF_RECOVERY` 1e7, `RESPONSE_TIME_WEIGHT` 3e7, `MAXIMUM_RESPONSE_TIME_DECIMAL` 1e8, `COMPETITION_WEIGHT` 2e7, `scaling` 1e8, 나머지 0.
  - index별 값: `maximum_score` 1e8, `previous_score` 1e7, `verified` 1, `proof_size` 1000, `response_time` 30, `competition` 5e7, `maximum_response_time` 100, `minimum_response_time` 0, `block_number` 1, `validator_uid` 0, `miner_uid` = index.
- **투영 입력:** X1 = B0에서 `response_time[0]`, `minimum_response_time[0]`만 후보 `a`, `b`로 바꾼 것(K1). X2 = B0에서 `maximum_response_time[0]`, `minimum_response_time[0]`만 바꾼 것(K2).
- **정직한 계산:** 원본 entrypoint WASM으로 X를 계산한다. 성공하면 snarkjs로 원본 R1CS를 검사한다.
- **단일 지점 이탈 계산:** clean tree 복사본에서 `subtractTensor.circom` 8행만 `d <-- (a == A && b == B) ? D : 1;`로 바꾼다(A, B, D는 후보 값). 제약 없는 hint만 바꾼 것이다.
  - 같은 조건으로 컴파일한 R1CS와 `.sym`이 원본 entrypoint와 바이트가 같아야 진행한다. 다르면 E3는 미판정이다.
  - 이 생성기로 X를 계산해 W′를 만든다. W′는 **원본** R1CS에 대해 Python 평가와 snarkjs로 검사한다.
  - 1,280개 `d` 중 1이 아닌 것이 정확히 목표 인스턴스 하나이고 그 값이 후보 `d`인지 확인한다. K1은 wire가 있는 `c`도 확인한다.
- **판정:**
  - 정직 계산 성공 + W′ 두 방법 만족 + 이탈 유일 + 출력 1,024개 중 하나 이상 다름이면 **entrypoint TCCT 위반(출력 차이형)**이다.
  - 정직 계산이 assert로 중단 + W′ 두 방법 만족 + 이탈 유일이면 **abort형 위반**이다.
  - 출력이 모두 같으면 이 투영에서 위반이 보이지 않은 것이다(미판정, 비위반 아님).
  - W′ 생성 중단·검사 실패·생성기 불일치는 **투영 실패**(미판정)다.
- **E4. entrypoint TCCT:** E3 성공이 있을 때만 결론을 쓴다. 그 밖에는 미판정이며, 한 입력 구성의 실패를 비위반으로 해석하지 않는다.
- **E5. 프로젝트 의미:** 판정하지 않는다.

## 6. 최초 확인 대상 시간

A3가 **위반**이면 최초 확인 대상은 attempt 1이다. **명시적 비해당**이면 S-04의 attempt 8(컴포넌트 일반 TCCT 위반 확인)이다. 어느 경우든 S-04보다 앞선 occurrence가 attempt 1 하나뿐이고 이번에 검토가 끝났는지 확인한 뒤 다음을 계산한다.
- **관측 상한:** 해당 attempt의 parent `NOT SAFE` 관측 offset.
- **후보 파일 존재 상한:** 시도 완료 offset.
- **하한:** 해당 zkFuzz 프로세스 시작 offset.

이 값들은 캠페인 시계의 관측 경계이며 정확한 생성시각이 아니다. A3가 미판정이면 계산하지 않는다. 사람의 검토 시간은 포함하지 않는다.

## 7. 중단 기준과 실행 범위

**중단 기준.**
- 고정 해시·재컴파일 R1CS·`.sym`이 다르면 의존 판정을 중단하고 미판정으로 둔다.
- 도구 오류는 기록하고 의존 단계를 미판정으로 둔다.
- 제한 시간은 컴포넌트 명령 60초, entrypoint 컴파일·계산·검사 명령 600초, 전체 3시간이다.
- 새 퍼징, 다른 후보, 다른 투영 입력, held-out 자료, S-03·S-04·A-02 파일 수정은 하지 않는다.

**실행 범위.** ignored `runs/n4-1-a02-first-semantic-review-2026-10-02/run-v1/`에서 검토 스크립트 하나로 다음을 한다.
1. 재컴파일하고 준비 기록과 해시를 대조한다.
2. 후보를 읽는다.
3. A·B·D·S를 판정한다.
4. E2 규칙을 적용하고 E3 투영을 한 번 실행한다.
5. T를 계산한다.

후보 값, 투영 입력, 후보 값이 들어간 수정 생성기 소스와 산출물, witness는 그 디렉터리에만 둔다. 값 없는 REPORT에는 판정·해시·비용(도구 프로세스 시간과 담당자 작업 구간을 분리, 사람 실제 시간 unknown)·한계·남은 29건의 미검토 상태만 쓴다.
