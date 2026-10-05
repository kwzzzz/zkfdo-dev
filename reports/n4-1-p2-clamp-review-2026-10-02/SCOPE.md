# S-02 사전 범위: P2 `Clamp(40)` 후보 한 개의 의미 검토

2026-10-02 · 버전 `p2-clamp-review-v1` · 담당 miiz. **후보 값을 열기 전에 고정**했다(2026-10-01T16:41Z, 한국 시각 10-02 01:41). 이 시점까지 후보 파일은 해시만 계산했다. 근거는 [인계](../../docs/next_engine_clamp_handoff_2026-10-02.md) S-02 절과 [N3 결정용 기록](../../docs/scope_decision_final_2026-10-01.md) §3–4다. A-02와 무관하다. P2와 S-01의 기록은 바꾸지 않는다.

## 1. 대상 후보

인계가 지정한 한 개뿐이다. 결과를 보고 고르지 않는다.

| 항목 | 값 |
|---|---|
| 후보 | `runs/dev-rq1-pilot-2026-09-29/inference-main/campaign/small-first/block-1/execution/execution-dea86966-f3b8-425b-b67c-607073d18d40/counterexample-candidates/0014/src__clampTensor__Clamp_40.circom_TDjO5oZz4N_counterexample.json` |
| 후보 SHA-256 / 크기 | `3a04372930ff052952f54b72615c27751dfab3737596f0e95d2d17d16c80b02d` / 11,149 bytes |
| outcome / plan | `a84ed780…7e0`(S-01과 같은 실행) / `b8843d8b…7cc7f`. small-first block 1, zkFuzz seed 2026092931 |
| run / target | run `1b96a0fa-e320-4d55-a88f-b47c050cb016`, target `sha256:d59fef915c37c148f4c3c6bc3e06a901e47fb771af21c13d959c404db12a2a51` |
| 실행 기록 | plan의 14번째 조각, `bug_found`, generation 0, wall 0.030562초 |

같은 outcome의 다른 후보 9개와 같은 target의 다른 block 후보 2개는 열지 않는다.

## 2. 원본과 컴파일 조건

- **원본 소스:** `inference-labs-inc/subnet-2-circom` revision `d310309c141d36504b3486cebd96ed70ef3a4fdf`. P2 snapshot의 `targets/0002/sources/src/clampTensor.circom`(SHA-256 `ed11afa8…08bf`)를 쓴다.
  - 이 파일은 로컬 클론(`runs/dev-projects/inference`, origin `github.com/inference-labs-inc/subnet-2-circom`)의 해당 commit blob `2f758f6d…`와 같은 바이트다.
  - `Clamp`·`LessThan`·`Num2Bits`·`AssertBit`는 모두 이 파일 안에 정의돼 있고 외부 include는 없다.
- **wrapper:** `targets/0002/sources/zkfdo-targets/src__clampTensor__Clamp_40.circom`(`76f18863…ced4`). `component main = Clamp(40);`이다.
- **준비 R1CS:** `7a3f2b61a51f52860e522348457acb13863f86fd8de00ae604749380ea671d56`. 제약 94개.
- **컴파일 인자:** circom 2.2.3(`89918878…6227`), `--r1cs --prime bn128`, `-l` P2 tree·zkbugs dependencies·circomlib. 최적화 flag는 지정하지 않아 컴파일러 기본값이다. 재컴파일은 `--sym --wasm`만 더하며, 준비 R1CS와 바이트 단위로 같아야 진행한다.
- **수정본:** fix commit `b8f92bdec1694138df0e069921f1aa0bdc94053e`(부모 `d310309c`·`4d9012d8`)의 `src/clampTensor.circom`, blob `f4fbf7f7845fc4a9a7f6978f658b293cbc617108`.
  - 로컬 snapshot은 `runs/controlled-v3-preflight/excluded-source-snapshots/inference-clamp/fixed/project/src/clampTensor.circom`(SHA-256 `8aafab37043d81658e61965e2fea720a3f138379c3f84887fd96432e9c6a3d9f`)과 wrapper `circuit.circom`(`353fe9ba…e22`, `Clamp(40)`)다.
  - **출처 확인 결과(사전):** 로컬 클론에서 commit→root tree→`src` tree→blob의 git object hash를 직접 다시 계산했다. 네 단계가 모두 일치했고 snapshot 바이트도 blob과 같았다. 따라서 바이트 동일성은 fix commit의 content address로 확인됐다. 원격 서버에 다시 조회하지는 않았다. 검토 실행 때 이 확인을 반복하며, 실패하면 수정본 결과는 출처 미검증의 보조 진단으로만 쓴다.
- **도구:** node 26.0.0(`08dad058…`), snarkjs 0.7.6(`cli.cjs` `6d787e37…`). zkFuzz는 실행하지 않는다.

## 3. 판정층과 사전 속성

세 층을 따로 판정하고 서로의 근거로 쓰지 않는다. **일반 TCCT(A층)만 주 비교의 컴포넌트 원인 수에 들어갈 수 있다.**

| 층 | 입력 전제 | 사전 속성과 판정 |
|---|---|---|
| **A. 일반 TCCT** | `val`, `min`, `max`는 정규 BN128 필드 원소다(P2 `field_only`). 범위 전제는 없다 | 후보 할당이 원본 R1CS 전체를 만족하고, 같은 입력의 정직한 계산(원본 WASM)과 비교해 `main.out`이 다르거나 정직한 계산이 abort하면 위반이다. 원본 제약을 만족하는 다른 할당이 없고 출력이 같으면 위반이 아니다 |
| **B. 범위/결함 명세** | zkbugs `koukyosyumei_clamp_comparator_overflow`(README `327a4abc…`, config `5c09c5ac…`): `LessThan(40)`의 두 입력과 `val`, `min`, `max`, `temp_max`는 [0, 2^40) 안에 있다고 가정한다 | **B1 범위:** 후보의 `main.val`, `main.min`, `main.max`, `main.temp_max` 중 정수 대표값이 2^40 이상인 것을 이름만 기록한다. **B2 의도 순서:** 부호 없는 정수 순서의 `min(max(val, min), max)`와 후보 출력의 일치 여부를 정보로 기록한다. **B3 수정본 거부:** (i) 수정본은 `val`, `min`, `max`, `temp_max`에 `Num2Bits(40)`을 적용한다. `Num2Bits(40)`은 입력 x에 대해 x < 2^40일 때만 만족 가능하므로(비트 합이 2^40 − 1 이하이고 p보다 작음), 범위 밖 입력이 있으면 수정본 R1CS에는 만족 할당이 없다. (ii) 수정본 WASM으로 후보 입력을 계산하면 `Num2Bits`의 assert에서 실제로 중단돼야 한다(stderr 진단 확인). (iii) 대조로 zkbugs `direct_input.json`(`2a278656…`, 범위 안)은 수정본에서 witness를 만들고 `WITNESS IS CORRECT`를 받아야 한다. 세 가지가 모두 성립하면 확인이다 |
| **C. zkFuzz 도구 특화 경고** | — | 후보 파일의 `5_flag` 유형 라벨만 기록한다. A·B의 근거로 쓰지 않는다. 넘침 경고만으로 일반 TCCT나 원인을 선언하지 않는다 |

## 4. 단계별 판정과 중단 기준

| 단계 | 방법 | 통과 | 실패 / 미판정 |
|---|---|---|---|
| 0. 연결 | 후보 해시, outcome의 후보 기록, run·target·plan·`bug_found`, prepared(`da6b4396…`)·소스·wrapper·준비 R1CS 해시를 대조한다 | 모두 일치 | 불일치하면 중단하고 전체 미판정 |
| A1. 원본 제약 전체 | 재컴파일 `.sym`에서 wire ≥ 0인 신호 이름이 모두 후보 `7_assignment`에 있어야 한다. 같은 wire에 대응하는 이름들의 값은 같아야 한다. 모든 wire를 정확히 한 번 채우고 값의 정규성을 확인한다. (a) Python R1CS 평가와 (b) 후보 `.wtns`의 `snarkjs wtns check`로 모든 제약을 본다. snarkjs는 exit 0과 `WITNESS IS CORRECT`일 때만 만족, `WITNESS IS NOT CORRECT`일 때만 불만족으로 본다 | 두 방법 모두 만족 | 둘 다 명시적 불만족이면 실패. 이름 결측, 별칭 값 불일치, 비정규 값, 두 방법의 불일치, snarkjs의 다른 출력은 미판정이다. 탈락한 `.sym`(-1)과 후보에만 있는 이름은 개수만 기록한다 |
| A2. 정직한 계산과의 관계 | 원본 WASM으로 후보 입력의 정직한 witness를 계산하고, 같은 snarkjs 판정 규칙으로 검사한다. wire별로 비교한다 | `main.out`이 다르면 출력 차이. 정직한 계산이 assert 진단으로 중단되면 abort | 모든 wire가 같으면 차이 없음. assert 진단이 없는 도구 오류는 미판정 |
| A3. 일반 TCCT 속성 | §3 A층 | A1 통과이고 A2가 출력 차이나 abort이면 위반 | A2가 차이 없음이면 위반 아님. 앞 단계가 미판정이면 미판정 |
| A4. 일반 TCCT 원인 귀속 | A3가 위반일 때만 차이 신호와 소스로 귀속한다 | 사전 규칙에 맞는 단일 원인 | A3가 위반이 아니면 해당 없음. 그 밖에는 미판정 |
| B1–B3 | §3 B층. 출처 확인(git object chain)을 다시 실행한다 | B1 범위 밖 있음, B3 세 조건 성립 | B1 범위 밖이 없으면 B 속성 위반 아님. 출처 확인이 실패하면 B3는 보조 진단. 진단이 기대와 다르면 미판정 |
| B4. 범위/명세 귀속 | A1 통과(취약 원본이 받아들임) + B1 범위 밖 + B3 확인 | 범위/명세층에서 zkbugs 원인에 귀속. **일반 TCCT 원인 아님** | 하나라도 성립하지 않으면 미판정 |
| C. 도구 경고 | 라벨 기록 | — | — |

**판정하지 않는 층.** 호출 맥락 배제·도달성(`clampTensor` 등 호출자), entrypoint TCCT, 프로젝트 의미는 이번에 판정하지 않고 미판정으로 둔다.

**세는 규칙.**
- A3가 위반이 아니면 이 후보는 주 비교의 일반 TCCT 원인 수에 넣지 않는다. B층 결과는 별도 층으로만 보고한다.
- 같은 PR·프로젝트라는 이유로 S-01(`Subtract`, Assigned-but-Unconstrained)과 합치지 않는다.
- 이름이 다르다는 이유만으로 독립 확인 원인 2개로 세지도 않는다.

**중단 기준.**
- 재컴파일 R1CS가 준비본과 다르면 중단한다.
- 도구 오류는 기록하고, 그 결과에 의존하는 단계를 미판정으로 둔다.
- 명령마다 제한 시간은 60초다.
- 새 퍼징, 다른 후보 선택, P2·S-01·A-02 파일 수정은 하지 않는다.

## 5. 실행 범위

다음만 실행한다.
1. ignored `runs/n4-1-p2-clamp-review-2026-10-02/`에 취약본·수정본 소스와 wrapper를 해시 확인 후 복사한다.
2. 각각 재컴파일한다.
3. 원본 WASM으로 후보 입력의 정직한 witness를 계산하고, 후보 `.wtns`를 만들어 검사한다.
4. 수정본 WASM으로 후보 입력과 대조 입력을 계산하고 검사한다.
5. Python R1CS 평가와 git object chain 확인을 한다.

원시 값과 진단 로그는 이 디렉터리에만 둔다. 값 없는 [REPORT](REPORT.md)에는 해시, 방법, 판정, 비용, 한계만 쓴다. 검토 비용은 도구 프로세스 시간과 담당자 작업 구간을 나누어 쓰며, 사람의 실제 작업 시간은 unknown이다.
