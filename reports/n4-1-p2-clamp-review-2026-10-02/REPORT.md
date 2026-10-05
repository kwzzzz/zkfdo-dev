# S-02 결과: P2 `Clamp(40)` 후보 한 개의 의미 검토

2026-10-02 · 버전 `p2-clamp-review-v1` · 담당 miiz.

**상태: 완료.** 후보 값을 열기 전에 [사전 SCOPE](SCOPE.md)(SHA-256 `4aaea7a2c263ab12f35cfa20c7c45379efff038a4179d982c8f50c7c967db6ce`)를 고정했다. 검토 스크립트 [review_candidate.py](review_candidate.py)(`be3c1fec33715e66f303f1eda79a745aa4f7c435b7b0374ee27a9b22b4cd1aaa`)는 이 해시를 확인한 다음에야 후보를 읽는다. 원시 값은 ignored `runs/n4-1-p2-clamp-review-2026-10-02/` 안에만 있다.

## 결론

검토 대상은 사전 지정한 P2 small-first block 1의 `Clamp(40)` 후보 하나다(SHA-256 `3a04372930ff052952f54b72615c27751dfab3737596f0e95d2d17d16c80b02d`). 판정은 세 층에서 따로 했다.

- **A. 일반 TCCT: 위반 아님.** 후보 할당은 원본 R1CS 전체를 만족한다. 그러나 같은 입력으로 정직하게 계산한 witness와 모든 wire가 같다. 후보로 만든 `.wtns`와 원본 WASM이 만든 정직한 witness 파일은 바이트 단위로 같았다(`19d695a8…8a70`). 출력 차이도 abort도 없으므로 **주 비교의 일반 TCCT 원인 수에 넣지 않는다.**
- **B. 범위/결함 명세: 관측은 있으나 귀속은 미판정.**
  - `main.val`이 `LessThan(40)`이 가정하는 [0, 2^40) 밖에 있다. 취약 원본은 이 할당을 받아들이며, 출력은 의도한 부호 없는 clamp(`min(max(val, min), max)`)와 다르다. 이는 zkbugs 설명과 맞는 관측이다.
  - 그러나 출처를 확인한 실제 수정 commit의 소스가 고정 컴파일러에서 컴파일되지 않았다. 따라서 수정본 거부(B3)와 범위/명세층 귀속(B4)은 미판정이다.
- **C. zkFuzz 도구 특화 경고:** 라벨은 `UnderConstrained-UnexpectedInput`이다. 판정의 근거로 쓰지 않았다.
- **판정하지 않은 층:** 호출 맥락 배제·도달성, entrypoint TCCT, 프로젝트 의미는 자료가 없어 미판정이다.

| 단계 | 판정 | 독립 검산 방법과 근거 |
|---|---|---|
| 0. 연결 | 통과 | 다음이 모두 일치했다: 후보 해시와 outcome(`a84ed780…7e0`)의 후보 기록, run `1b96a0fa-…`, target `sha256:d59fef91…`, plan(`b8843d8b…`), `bug_found`, prepared·소스(`ed11afa8…`)·wrapper(`76f18863…`) 해시 |
| 재현 조건 | 통과 | 같은 circom 2.2.3과 같은 인자에 `--sym --wasm`만 더해 재컴파일했다. R1CS가 준비 R1CS `7a3f2b61a51f52860e522348457acb13863f86fd8de00ae604749380ea671d56`과 바이트 단위로 같다. 구조는 wire 96, 출력 1, 비공개 입력 3, 제약 94 |
| A1. 원본 제약 전체 만족 | 통과 | `.sym`에서 wire를 가진 이름 95개가 모두 후보에 있고, 값은 모두 정규 원소다. 최적화로 빠진 이름(-1) 87개와 후보에만 있는 이름 1개는 개수만 기록했다. 두 방법이 모두 만족을 확인했다: Python R1CS 평가(불만족 0)와 snarkjs `WITNESS IS CORRECT`. 로컬 `.wtns` 작성기의 양성 대조도 통과했다 |
| A2. 정직한 계산과의 관계 | 동일 | 원본 WASM으로 같은 입력을 정상 계산했고 snarkjs `WITNESS IS CORRECT`를 받았다. wire 96개 중 다른 값은 0개다. abort는 없었다 |
| A3. 일반 TCCT 속성 | 위반 아님 | 출력 차이와 abort가 모두 없다 |
| A4. 일반 TCCT 귀속 | 해당 없음 | A3가 위반이 아니다 |
| B1. 범위 | 범위 밖 | `main.val`만 2^40 이상이다. `main.min`, `main.max`, `main.temp_max`는 범위 안이다 |
| B2. 의도한 순서 | 다름 | 후보 출력이 부호 없는 정수 순서의 `min(max(val, min), max)`와 다르다(정보 기록) |
| 수정본 출처 | 확인 | 로컬 클론(origin `github.com/inference-labs-inc/subnet-2-circom`)에서 fix commit `b8f92bde…` → root tree `f752f08a…` → `src` tree `fed0327a…` → blob `f4fbf7f7…`의 git object hash를 직접 다시 계산했다. 로컬 수정 snapshot(`8aafab37…`)이 이 blob과 같은 바이트다. 취약 commit `d310309c…`의 blob `2f758f6d…`도 P2 소스와 같다. 원격 서버에 다시 조회하지는 않았다 |
| B3. 수정본 거부 | 미판정 | 수정본 소스가 circom 2.2.3에서 컴파일되지 않는다. 오류는 `T3001`(초기화되지 않은 신호 접근)이며, 59행 `Num2Bits[3].in <== temp_max;`가 68행에서야 할당되는 `temp_max`를 먼저 읽는다. 준비 때와 같은 `--r1cs`만 쓴 진단 컴파일도 같은 오류였다(stderr 해시 동일, R1CS 없음). 그래서 수정본 witness 계산의 실제 거부 진단과 범위 안 대조 입력 검사를 실행할 수 없었다. 소스상으로는 `Num2Bits(40)`이 범위 밖 `val`을 받아들이지 않는다는 산술 논증이 가능하지만, 실행 확인이 아니므로 확인으로 세지 않았다 |
| B4. 범위/명세 귀속 | 미판정 | A1과 B1은 성립했지만 B3가 미판정이다 |
| C. 도구 라벨 | `UnderConstrained-UnexpectedInput` | 후보 파일의 `5_flag` 유형이다. 세부 조건 필드는 원시 자료에 남겼다 |

## 실행 경과

- **run-v1(보존):** 수정본 컴파일 실패를 스크립트가 검토 전체의 중단으로 처리해, 후보를 읽기 전에 끝났다. 원시 값 파일이 비어 있고 evidence도 없다. 결과는 `a11e1c40…`, ledger는 `55925cd4…`다.
- **run-v2:** 사전 규칙은 바꾸지 않았다. 스크립트만 고쳐 이 실패가 B3에만 영향을 주게 한 뒤 다시 실행했다. 이것이 판정을 낸 실행이다.
- **진단 컴파일:** 수정본 컴파일 실패를 확인하려고 준비 인자만으로 한 번 더 컴파일했다(기록 `5a61f508…`). 후보 값은 쓰지 않았다.

## 증거 경로와 해시

| 자료 | 경로 | SHA-256 |
|---|---|---|
| 값 없는 결과(run-v2) | `runs/n4-1-p2-clamp-review-2026-10-02/run-v2/result.json` | `d9c02317b0d3293c5877be48fbbbfd62e235214396e308a53e3ab16528eb0580` |
| 명령 ledger(run-v2) | `…/run-v2/ledger.json` | `2330659934e1b18b04b20b7120a5730eac64f96294cb0f036a7b8dbfbea9c920` |
| 원시 값(ignored, 값 포함) | `…/run-v2/raw-values.json` | `ae598e7640b1e711a743352d6fa000f555422dab0266456508899f5c812add54` |
| 후보 `.wtns` = 정직한 witness | `…/run-v2/candidate.wtns`, `…/run-v2/honest-original/witness.wtns` | `19d695a87deab9936b8ff2e6f1a4eb6e0cf06ef66b7eefc364c4ca33d8518a70`(두 파일 동일) |
| 재컴파일 취약 R1CS | `…/run-v2/compiled-vulnerable/src__clampTensor__Clamp_40.r1cs` | `7a3f2b61…1d56` |
| 수정본 컴파일 오류 로그 | `…/run-v2/logs/01-compile-fixed.stderr` | `557597294b1f9254c5e57ab7b0b0705eda2499d1c00a3d4f98eb5e1f6c100a99` |
| 진단 컴파일 기록 | `…/run-v2/diagnostic-fixed-r1cs-only/record.json` | `5a61f50860a6abe765dde5a95851cab41d6b622d4554651f56b5e5b66b0b0f88` |
| 대조 입력(실행 못 함) | zkbugs `direct_input.json` | `2a2786562640d559874f6221bfc06c682d558b2ac8f653a534876b6e58ee451c` |

도구는 circom 2.2.3(`8991887889c2…6227`), node 26.0.0(`08dad0581f00…c164`), snarkjs 0.7.6(`cli.cjs` `6d787e37a4d1…051a`)이다. zkFuzz는 실행하지 않았다. snarkjs 결과는 다음 규칙으로만 판정했다: exit 0과 `WITNESS IS CORRECT`이면 만족, `WITNESS IS NOT CORRECT`이면 불만족, 그 밖에는 미판정. 이번 검토에서 수정본 거부를 snarkjs 오류로 추정한 판정은 없다.

## 검토 비용

**run-v2 도구 프로세스:** 7개, wall 합계 0.751초.
- 컴파일 2회: 0.018초(수정본 실패 포함)
- snarkjs 검사 3회: 0.607초
- 정직한 계산: 0.037초
- export: 0.089초

**그 밖의 실행:** 스크립트 전체 0.840초, run-v1 컴파일 2회 0.019초, 진단 컴파일 0.005초.

**담당자 작업 구간:**
- 1차 구간(2026-10-01, UTC): 인계 확인 16:35Z, SCOPE 고정 16:41Z, run-v1 16:43Z, run-v2 16:45Z, 진단 16:46Z.
- 2차 구간: 보고서 작성 2026-10-02 03:12Z(한국 시각 12:12)부터.
- 두 구간 사이의 대기 시간은 검토 비용에 넣지 않는다. 사람의 실제 작업 시간은 계측하지 않아 unknown이다.

## 주장할 수 있는 범위와 한계

사용할 수 있는 문장은 다음 하나다.

> 사전 지정한 P2 small-first block 1의 `Clamp(40)` 후보는 원본 제약 전체를 만족하지만 같은 입력의 정직한 계산과 모든 wire가 같아 일반 TCCT 위반이 아니다. 40비트 범위 밖 `val`을 받아들이고 의도한 부호 없는 순서와 다른 출력을 내는 범위/명세 관측은 있으나, 출처를 확인한 수정 commit의 소스가 고정 컴파일러에서 컴파일되지 않아 수정본 거부와 원인 귀속은 미판정이다.

다음은 이 결과로 주장하지 않는다.

- **원인 수 집계:**
  - 이 후보를 주 비교의 일반 TCCT 원인으로 세지 않는다.
  - 같은 PR·프로젝트라는 이유로 S-01(`Subtract`, Assigned-but-Unconstrained)과 합치지 않는다.
  - 이름이 다르다는 이유로 독립 확인 원인 2개로 세지도 않는다.
  - 이 block의 정답 위치 후보 두 개 중 일반 TCCT로 확인된 것은 S-01의 `Subtract` 하나다. 같은 block의 다른 후보 8개는 검토하지 않았다.
- **범위/명세 결론:** 범위/명세층의 관측은 귀속 확인이 아니다. 오래된 컴파일러에서 수정본이 동작하는지는 시험하지 않았다. 수정본을 고쳐 컴파일하는 일은 실제 수정본이 아니게 되므로 하지 않았다.
- **기존 기록:** P2의 위치 일치 기록과 분류는 바꾸지 않는다.
- **판정하지 않은 층:** 호출 맥락, entrypoint, 프로젝트 결론을 내리지 않는다.
- **A-02와의 관계:** 이 판정을 A-02의 새 후보에 복사하지 않는다.

기존 P2·S-01 기록, A-02 코드·행, record/aggregate 코드는 수정하지 않았다. 새 퍼징과 다른 후보 선택은 하지 않았다. commit·push·PR은 하지 않았다.
