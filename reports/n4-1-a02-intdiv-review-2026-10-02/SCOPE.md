# S-04 사전 범위: A-02 둘째 후보 `IntDiv(40)` 한 건의 의미 검토

2026-10-02 · 버전 `a02-intdiv-review-v1` · 담당 miiz.

**상태:** 후보 값을 열기 전에 고정했다(2026-10-02T03:30Z). 이 시점까지 후보 파일은 해시와 크기만 계산했다. 근거는 [인계](../../docs/next_a02_semantic_handoff_2026-10-02.md)의 S-04 절이다. A-02 원문, S-01·S-02·S-03의 파일과 판정은 바꾸거나 이 후보에 복사하지 않는다.

## 1. 선정의 독립 재검산(값을 읽지 않음)

[A-02 REPORT](../n4-1-policy-a-engine-2026-10-02/REPORT.md)가 적은 원시 small-first campaign ledger(`8912e24976bc7d7dc414a7eddcda67007fa5aeffff989babf017d09fa0bbcb8e`)를 직접 읽어 다음을 확인했다.

- attempt는 67개, 후보 attempt는 31개다. 후보 attempt마다 후보 파일 1개와 parent `not_safe` 관측 1개가 있고, 관측 결측은 0이다. 파일 SHA-256 31개는 서로 다르다.
- 첫 parent `not_safe` 관측 offset의 오름차순(동률이면 attempt index, 그다음 경로)으로 정렬했다.
  - 1번째: attempt 1(`Subtract()`), 1.108243333초.
  - **2번째: attempt 8(target index 8, `IntDiv(40)`), 77.99670775초.** 동률은 없다. 앞선 occurrence는 attempt 1 하나뿐이다.
- attempt 8의 완료 offset 상한은 78.005990458초다. 두 값은 parent의 로그 관측과 기록 완료 시각이며, 후보 생성시각이 아니다.
- 후보 경로 `runs/n4-1-policy-a-engine-2026-10-02/small-first-campaign-v1/attempts/000008/candidates/zkfdo-targets/src__integerDivision__IntDiv_40.circom_5vPZul9Pul_counterexample.json`이 존재한다. SHA-256 `f5a346327427a1b3a288fc099f8fbcd0635f8b4c289b57bd5f22fa0a1f08a143`, 7,296 bytes이며 인계 표와 ledger 기록과 같다. workspace 복사본의 해시도 같다.
- attempt 8 `result.json`은 `4d8b4fe0…f97`로 ledger 기록과 같다. mutation setting은 `eb097ac3…3fff`, seed 2026092931, pass 0, `bug_found`형 후보, generation 0이다.

## 2. 원본과 컴파일 조건

- **원본 소스:** `inference-labs-inc/subnet-2-circom` revision `d310309c141d36504b3486cebd96ed70ef3a4fdf`.
  - A-02 clean source에서 `src/integerDivision.circom`(`325e1432…c467d`)과 `src/clampTensor.circom`(`ed11afa8…08bf`)을 쓴다.
  - 로컬 클론의 해당 commit blob(`96de8b18…`, `2f758f6d…`)과 같은 바이트다.
- **wrapper:** `zkfdo-targets/src__integerDivision__IntDiv_40.circom`(`8f498bbe…e1`). `component main = IntDiv(40);`이다.
- **원본 R1CS:** A-02 preflight와 P2 prepared가 같은 `1bcdc3ea0ca994a1efcb37631d09fb47efccacbaf331f09becb48aa87e7c3c5d`다. 제약 46, wire 49, 비공개 입력 2, 출력 1이다.
- **엔진 명령:** zkFuzz `ac2d9d16…`, `--search_mode ga`, 명령 SHA-256 `5683e5b2…2223`. A-02 실행기는 `c408ccba…74d`다. 이번 검토에서 zkFuzz는 실행하지 않는다.
- **재컴파일:** circom 2.2.3(`89918878…6227`), `--r1cs --prime bn128`, 기본 최적화, `-l` clean source·zkbugs dependencies·circomlib에 `--sym --wasm`만 더한다. R1CS가 `1bcdc3ea…`와 바이트 단위로 같아야 진행한다.
- **수정본:** fix commit `b8f92bdec1694138df0e069921f1aa0bdc94053e`의 `src/integerDivision.circom`(blob `7e90e2da…`, SHA-256 `7ea9ab0e…dfa`)과, 그것이 include하는 같은 commit의 `src/clampTensor.circom`(blob `f4fbf7f7…`, `8aafab37…`)이다.
  - 로컬 클론에서 commit→tree→blob hash를 다시 계산해 확인한다. 실패하면 수정본 결과는 출처 미검증의 보조 진단이다.
  - 수정 내용은 `out <== quot`와 `quot`·`rem`·`in[1]`의 `Num2Bits(40)` 범위 검사다.
  - 같은 wrapper와 조건으로 컴파일한다. 같은 commit의 `Clamp`는 S-02에서 T3001로 컴파일되지 않았다. 그래서 수정본 컴파일 실패는 오류 그대로 기록하고 수정본 의존 단계만 미판정으로 둔다.
- **도구:** node 26.0.0(`08dad058…`), snarkjs 0.7.6(`cli.cjs` `6d787e37…`).

## 3. 판정층

| 층 | 입력 전제 | 정의와 판정 |
|---|---|---|
| **A. 일반 TCCT(컴포넌트, 주 비교층)** | `in[0]`, `in[1]`은 정규 BN128 필드 원소다(P2·A-02 `field_only`). `in[1] ≠ 0`은 원본 제약(IsZero)이 강제하는 조건이며 별도 전제가 아니다 | **A1:** 후보 할당이 원본 R1CS 전체를 만족하는지 두 독립 방법으로 본다. (a) Python R1CS 평가, (b) 후보 `.wtns`의 snarkjs 검사. snarkjs는 exit 0과 `WITNESS IS CORRECT`이면 만족, `WITNESS IS NOT CORRECT`이면 불만족, 그 밖은 미판정이다. **A2:** 같은 입력으로 원본 WASM의 정직한 witness를 다시 계산하고 wire별로 비교한다. **A3:** A1이 만족이고 `main.out`이 다르거나 정직한 계산이 assert 진단으로 abort하면 위반이다. 동일 출력·정상 실행이면 위반이 아니다 |
| **B. 명세·수정본층(zkbugs 서술, fix commit)** | 수정본이 표현하는 의도 영역: `quot`, `rem`, `in[1]` < 2^40, `out = quot` | **B1:** `main.quot`, `main.rem`, `main.in[1]` 중 2^40 이상인 것을 이름만 기록한다. **B2:** 수정본의 `out = quot`와 범위 검사 중 후보가 어떤 조건을 어기는지 기록한다(§4 D). A층의 근거로 쓰지 않는다 |
| **C. zkFuzz 도구 라벨** | — | `5_flag` 유형 라벨만 기록한다. 판정 근거가 아니다 |
| **D. 단일 원인 귀속** | A3 위반일 때만 | §4 |
| **E. 호출 맥락·entrypoint·프로젝트** | — | 정적 호출자는 기록만 한다(`circuit`, `metricNormalized`, `responseTimeNormalized`, `responseTimeMetric`, `incentiveMetric`, `proofSizeRewardMetric` 소스가 `IntDiv`를 참조). 배제·도달성·투영·entrypoint TCCT는 이번 자료로 판정하지 않고 미판정으로 둔다. 컴포넌트 판정과 섞지 않는다. NB-01을 반례 투영의 증명으로 쓰지 않는다 |

## 4. 단일 원인 귀속과 중복·첫 차이 규칙

귀속은 위반(A3)과 별도로 보고한다. **A3가 위반일 때만** 다음을 시도한다.

1. **첫 차이와 중첩 인스턴스:** 후보와 정직한 witness의 차이를 신호 경로로 분류한다. `main`의 직접 신호(`out`, `quot`, `rem`, `is_non_zero` 등)와 중첩 인스턴스(익명 `IsZero`, `LessThan(40)`과 그 안의 `Num2Bits`·`AssertBit`)를 나눈다. 계산 순서상 가장 앞선 차이 신호를 첫 차이로 기록한다.
2. **단일 원인 후보 C1(`out <-- quot`, Assigned-but-Unconstrained):** 다음 세 조건이 모두 성립할 때만 이 원인에 귀속한다.
   - 차이가 `main.out` 하나뿐이다(중첩 인스턴스·`quot`·`rem` 차이 없음).
   - 수정본이 후보를 `out = quot` 조건으로 거부한다. 수정본 R1CS에서 `main.out`과 `main.quot`가 같은 wire로 합쳐졌거나 명시적 제약으로 묶인다. 후보 자신의 `out ≠ quot`가 그 조건을 어긴다. 동시에 후보의 `quot`·`rem`·`in[1]`은 범위 검사를 통과해 다른 수정 조건은 어기지 않는다.
   - 대조로 같은 입력의 수정본 정직한 witness가 snarkjs `WITNESS IS CORRECT`를 받는다.
3. **다중 원인:** `quot`/`rem` 또는 중첩 인스턴스에 차이가 있거나, 후보가 수정본의 범위 검사도 어기면 단일 원인으로 귀속하지 않고 **미판정(다중 원인 가능)**으로 둔다. 확인된 위반과 미귀속 원인을 분리해 보고한다.
4. **원인 중복:** C1에 귀속되더라도 다음과 같이만 다룬다.
   - S-01 `Subtract`와 같은 원인 유형(Assigned-but-Unconstrained)이지만 위치가 다르다. zkbugs도 `Subtract` 항목에서 이 위치를 같은 PR의 같은 패턴으로 적는다.
   - 같은 원인인지 다른 원인인지의 등록은 사전 규칙(N5)이 없으므로 확정하지 않는다.
   - `IntDiv(80)`·`IntDiv(120)`과 `IntDiv`를 포함한 상위 조각의 후보, 31개 occurrence 전체와 합산하거나 두 번째 고유 원인으로 세지 않는다.
5. **시간:** S-03가 확인되지 않았거나 미판정이면, 이 후보가 확인되더라도 ‘최초 확인 시간’을 확정하지 않는다. parent 관측 offset은 생성시각이 아니다.

## 5. 중단 기준과 실행 범위

**중단 기준.**
- 선정 재검산이나 연결 해시가 불일치하거나 재컴파일 R1CS가 다르면 의존 판정을 중단하고 미판정으로 둔다.
- 도구 오류는 기록하고 의존 단계를 미판정으로 둔다.
- 명령마다 제한 시간은 60초다.
- 인계 기준 3시간 안에 컴포넌트 판정이 끝나지 않으면 완료된 층·미완료 층·장애를 기록하고 멈춘다.
- 새 퍼징, 다른 후보, held-out 자료, A-02·S-03 파일 수정은 하지 않는다.

**실행 범위.** ignored `runs/n4-1-a02-intdiv-review-2026-10-02/`에서 다음만 한다.
1. 원본·수정본 소스와 wrapper를 해시를 확인하며 복사한다. 수정본은 git object에서 꺼낸다.
2. 재컴파일한다.
3. 후보 `.wtns`를 생성하고 검사한다(Python 평가 + snarkjs).
4. 원본·수정본 정직한 witness를 계산하고 검사하며 신호를 비교한다.

원시 값과 로그는 그 디렉터리에만 둔다. 값 없는 [REPORT](REPORT.md)에는 해시, 방법, 층별 판정, 귀속 근거, 비용(도구 프로세스 시간과 담당자 작업 구간을 분리, 사람 실제 시간은 unknown), 한계만 쓴다.
