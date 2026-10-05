# S-04 결과: A-02 둘째 후보 `IntDiv(40)` 한 건의 의미 검토

2026-10-02 · 버전 `a02-intdiv-review-v1` · 담당 miiz.

**상태: 완료.** 후보 값을 열기 전에 [사전 SCOPE](SCOPE.md)(SHA-256 `e122217998acfcd12fb007ed7022825068b7110bdc1b4cffa1f9c6feed39ffa7`)를 고정했다. 검토 스크립트 [review_candidate.py](review_candidate.py)(`334a7873b23d1e7e4582365987847997cc57c79735d66101e1671bc4f26e772e`)는 이 해시를 확인한 다음에야 후보를 읽는다. 원시 값은 ignored `runs/n4-1-a02-intdiv-review-2026-10-02/run-v1/` 안에만 있다.

## 결론

- **선정 재검산: 통과.**
  - A-02 원시 ledger(`8912e249…cb8e`)로 다시 계산했다. 이 후보는 parent `NOT SAFE` 관측순 둘째이며, 앞선 occurrence는 attempt 1(`Subtract()`) 하나뿐이다.
  - attempt 8, target `sha256:0afd371f…`, 경로, SHA-256 `f5a34632…a143`, 관측 77.99670775초, 완료 상한 78.005990458초, `result.json` 해시가 모두 인계·ledger와 일치했다. 동률은 없다.
  - 정오: SCOPE §1의 `result.json` 해시 약기 `4d8b4fe0…f97`은 끝자리를 잘못 옮긴 것이다. 전체 해시는 `4d8b4fe0…be97f`이고, 스크립트는 ledger의 전체 해시와 비교했다. SCOPE는 값 확인 전 고정본이므로 고치지 않는다.
- **일반 TCCT(컴포넌트): 위반 확인(출력 차이형).**
  - 후보 할당은 원본 R1CS 제약 46개를 모두 만족한다(Python 평가와 snarkjs 두 방법).
  - 같은 입력으로 다시 계산한 정직한 witness와 wire가 있는 신호 48개를 비교하면 `main.out` 하나만 다르다. 중첩 인스턴스(`IsZero`, `LessThan(40)`과 그 안의 `Num2Bits`·`AssertBit`)와 `quot`·`rem`에는 차이가 없다.
- **단일 원인 귀속: 사전 규칙상 미판정.**
  - 출처를 확인한 실제 수정본(`b8f92bde`)은 이 후보를 두 조건으로 동시에 거부한다.
    - 하나는 `out <== quot`다. 수정본을 만족하는 할당은 언제나 `out = quot`인데, 후보는 `out ≠ quot`다.
    - 다른 하나는 `quot`의 40비트 범위 검사다. 후보의 `quot`는 2^40 이상이다. 후보와 정직한 witness의 `quot`가 같으므로(A2), 이 입력의 정직한 몫 자체가 범위 밖이다. 실제로 같은 입력의 수정본 정직한 계산은 `quot` 범위 검사 줄(수정 소스 28행 `Num2Bits(n)(quot)`)의 assert로 중단됐다.
  - 따라서 수정본 비교만으로는 `out <-- quot` 하나를 원인으로 분리할 수 없다. 같은 입력으로 수정본을 통과하는 대조도 만들 수 없었다. 확인된 위반과 미귀속 원인을 분리해 보고한다.
- **도구 라벨:** zkFuzz `UnderConstrained-NonDeterministic`. 판정의 근거로 쓰지 않았다.
- **판정하지 않은 층:** 호출 맥락·entrypoint·프로젝트는 판정하지 않았다(미판정).
- **최초 확인 시간: 미확정.** S-03가 첫 occurrence의 의미 검토를 수행하지 않았다. 계획 표에는 "메타데이터 검산 완료·의미 검토 미수행"으로 적혀 있다. 03:40Z에 읽은 S-03 REPORT(`75879652…ebf6c5`)에도 "지정 1건 중 완료 0"으로 적혀 있다. 그래서 이 후보가 확인됐어도 이 캠페인의 ‘최초 확인 시간’을 확정하지 않는다.

| 단계 | 판정 | 방법과 근거 |
|---|---|---|
| 선정·연결 | 통과 | ledger 67 attempt, 후보 31건, 결측 0, SHA-256 31개 모두 다름. 정렬 키는 관측 offset → attempt → 경로 |
| 재현 조건 | 통과 | clean source(`325e1432…`, `ed11afa8…`, wrapper `8f498bbe…`)를 circom 2.2.3 기본 최적화와 `--sym --wasm`만 더해 재컴파일했다. R1CS가 A-02/P2의 `1bcdc3ea0ca994a1efcb37631d09fb47efccacbaf331f09becb48aa87e7c3c5d`와 바이트 단위로 같다. 구조는 wire 49, 비공개 입력 2, 출력 1, 제약 46 |
| A1. 원본 제약 전체 만족 | 통과 | wire가 있는 이름 48개가 모두 후보에 있다. 최적화로 빠진 이름 48개와 후보에만 있는 이름 1개는 개수만 기록했다. (a) Python R1CS 평가에서 불만족 0, (b) 후보 `.wtns`(`a379d36e…`)의 snarkjs `WITNESS IS CORRECT`. 로컬 `.wtns` 작성기의 양성 대조도 통과했다 |
| A2. 정직한 계산과의 관계 | 출력 차이 | 원본 WASM으로 같은 입력의 정직한 witness(`60e0ba01…`)를 계산했고 snarkjs `WITNESS IS CORRECT`를 받았다. 다른 wire는 `main.out` 하나이며, 첫 차이도 `main.out`이다. abort는 없다 |
| A3. 일반 TCCT 속성 | **위반** | 입력 전제(정규 필드 원소)가 성립하고, 원본 제약을 만족하면서 정직한 출력과 다른 `out`을 가진다 |
| B1. 수정본 범위 | 범위 밖 | `main.quot`가 2^40 이상이다. `main.rem`, `main.in[1]`은 범위 안이다 |
| B2. 수정본과의 관계 | 거부(두 조건) | 수정본 출처는 fix commit의 git object chain(commit → tree → `src` → blob `7e90e2da…`, `f4fbf7f7…`)으로 확인했다. `IntDiv(40)`는 컴파일됐다(R1CS `24ecca25…3839`, wire 168, 제약 169). 수정본 `.sym`에서 `main.quot`는 최적화로 제거됐고(wire -1), `out <== quot`가 둘을 같게 묶는다. 후보는 `out ≠ quot`다. 같은 입력의 수정본 정직한 계산은 assert로 중단됐다(stderr `81b98327…`, `IntDiv` 28행 `quot` 범위 검사 안의 `Num2Bits`). 범위 안 대조 입력은 사전 범위에 없어 실행하지 않았다 |
| D. 단일 원인 귀속 | 미판정 | 사전 규칙의 세 조건 중 첫째(차이가 `main.out` 하나뿐)만 성립했다. 둘째는 `out = quot` 거부와 함께 범위 검사 통과를 요구하는데, 후보의 `quot`가 범위 밖이다. 셋째(수정본 정직 대조의 snarkjs `CORRECT`)는 대조 계산이 중단돼 성립하지 않았다. 다중 원인 가능성을 배제하지 못했다 |
| C. 도구 라벨 | `UnderConstrained-NonDeterministic` | 근거로 쓰지 않음 |
| E. 호출 맥락·entrypoint·프로젝트 | 미판정 | 정적 호출자 기록만 있다(SCOPE §3). 호출자가 `out`을 제약하는지, 도달성, 투영, entrypoint TCCT는 검토하지 않았다 |

**보충 관측(판정을 바꾸지 않음).** 원본 R1CS에서 `main.out`의 wire는 제약 46개 중 어디에도 나타나지 않는다. 수정본 R1CS에서는 `main.out`의 wire가 제약 169개 중 2개에 나타난다. 후보와 정직한 계산의 차이도 `main.out` 하나뿐이다. 이는 `src/integerDivision.circom` 31행의 `out <-- quot;`(Assigned-but-Unconstrained)와 맞는 구조 관측이다. 다만 이 구조 관측만으로 귀속하는 규칙은 사전에 정하지 않았다. 그런 규칙을 채택할지는 별도 결정 사항이다.

## 원인 중복과 세는 규칙

- 이 위반은 S-01 `Subtract`와 같은 원인 유형(Assigned-but-Unconstrained)으로 보이지만 코드 위치가 다르다. 로컬 zkbugs 사본에는 `IntDiv` 별도 항목이 없다. `Subtract` 항목이 이 위치를 같은 PR의 같은 패턴으로 적고, 자신을 대표 항목이라고 쓴다.
- 같은 원인 등록인지 다른 원인인지는 N5 규칙이 없으므로 확정하지 않는다.
- 새 고유 원인으로 세지 않는다. `IntDiv(80)`·`IntDiv(120)`, `IntDiv`를 포함한 상위 조각의 후보, 31개 occurrence 전체와 합산하지 않는다.
- 이 결과는 컴포넌트 수준이다. entrypoint나 프로젝트 결함, 통째 대비 탐지 우위가 아니다. 통째 시도는 timeout이었고 후보가 없었다.

## 증거 경로와 해시

| 자료 | 경로 | SHA-256 |
|---|---|---|
| 값 없는 결과 | `runs/n4-1-a02-intdiv-review-2026-10-02/run-v1/result.json` | `ca0ef092b6b829fc54d15649edb4950b34babee225239cea8c83656e9853c1a1` |
| 명령 ledger | `…/run-v1/ledger.json` | `3eaad852f5b3a3c018b8822e58ddedaf022b3a258bd91c032f223d45113b941f` |
| 원시 값(ignored, 값 포함) | `…/run-v1/raw-values.json` | `634cf1c004ce1af1dd4b1dee1118ac9c8a9bb81ad0e40bdcbfd9c07fcef98f2b` |
| 후보 `.wtns` / 원본 정직한 witness | `…/run-v1/candidate.wtns`, `…/run-v1/honest-original/witness.wtns` | `a379d36eb856d2ade633f0b740e1b33561eaed0c7a415d2c98e4b653fa8b2976` / `60e0ba0120ccf211b9a68e5d0ee99e9a07d386344a493d5c60263b3442692e75` |
| 원본 / 수정본 R1CS | `…/compiled-original/…IntDiv_40.r1cs`, `…/compiled-fixed/…IntDiv_40.r1cs` | `1bcdc3ea…7c3c5d` / `24ecca25ea10cc6d31f5617350c5afe9430872688c8895ce3d63559303ad3839` |
| 수정본 정직 계산 중단 로그 | `…/run-v1/logs/07-honest-fixed.stderr` | `81b98327c71d55a623e30c28ac20e3fe2783a6b8b9a30529211802c6ea4d9c07` |
| A-02 원문 | small-first ledger, attempt 8 `result.json` | `8912e24976bc7d7dc414a7eddcda67007fa5aeffff989babf017d09fa0bbcb8e`, `4d8b4fe0dff5602bade02aa95496902694166dd73ef56476024abbf38bcbe97f` |

도구는 circom 2.2.3(`89918878…6227`), node 26.0.0(`08dad058…c164`), snarkjs 0.7.6(`cli.cjs` `6d787e37…051a`)이다. zkFuzz는 실행하지 않았다.

snarkjs 결과는 다음 규칙으로만 판정했다: exit 0과 `WITNESS IS CORRECT`이면 만족, `WITNESS IS NOT CORRECT`이면 불만족, 그 밖에는 미판정. 수정본 거부에는 snarkjs 오류를 쓰지 않았다. 근거는 수정 소스의 `out <== quot` 제약과 수정본 `.sym`의 `quot` 제거, 그리고 수정본 witness 생성기의 실제 assert 진단이다.

## 검토 비용

**도구 프로세스:** 8개, wall 합계 0.959초.
- 컴파일 2회: 0.043초
- snarkjs 검사 3회: 0.728초
- 원본 정직 계산: 0.043초
- export: 0.099초
- 수정본 정직 계산(중단): 0.046초

**스크립트 전체:** 1.035초. 그 뒤 구조 관측(제약 수 계산)은 새 프로세스 없이 저장된 R1CS·`.sym`만 읽었다.

**담당자 작업 구간(2026-10-02, UTC):**
- 03:25Z 인계 확인·계획 행 시작
- 03:26Z 선정 재검산
- 03:27–03:28Z 수정본 출처와 고정 해시 확인
- 03:29–03:30Z SCOPE 작성·해시 고정
- 03:31:34–03:31:35Z 검토 실행
- 03:33–03:42Z 보고서 작성, 원자료와 수치 대조, 원시 값·링크 점검

사람의 실제 작업 시간은 계측하지 않아 unknown이다. 인계의 3시간 상한 안에서 컴포넌트 층을 끝냈다. 맥락 층은 자료가 없어 미판정이다.

## 주장할 수 있는 범위와 한계

사용할 수 있는 문장은 다음 하나다.

> A-02 small-first에서 parent `NOT SAFE` 관측순 둘째인 `IntDiv(40)` 후보 한 건은 원본 제약 46개를 모두 만족하면서 같은 입력의 정직한 계산과 `main.out`만 달라 컴포넌트 수준 일반 TCCT 위반(출력 차이형)으로 확인됐다. 실제 수정본은 이 후보를 `out = quot`와 `quot` 범위 검사 두 조건으로 동시에 거부하므로, 사전 규칙상 단일 원인 귀속은 미판정이다.

다음은 이 결과로 주장하지 않는다.
- **시간:** 최초 확인 시간이 아니다(S-03 의미 검토 미수행). 관측 offset은 생성시각이 아니다.
- **원인 수:** 고유 원인 수나 S-01과 같은/다른 원인이라는 결론이 아니다. 31건 전체의 원인 수나 오탐률도 아니다.
- **다른 층:** 호출 맥락 배제·도달성, entrypoint TCCT, 프로젝트 결함은 판정하지 않았다.
- **탐지 비교:** 통째 대비 탐지 우위가 아니다. 이 판정을 다른 occurrence에 복사하지 않는다.

A-02 원문·S-01·S-02·S-03 파일, A-02 코드, record/aggregate 코드는 수정하지 않았다. S-03 파일의 수정 시각(03:27–03:31Z)은 이 작업 구간 안에 있지만, 이 작업의 도구 호출 기록에는 그 파일을 쓴 명령이 없다. A-02 SCOPE·REPORT·evidence-v2·preflight·후보 파일 해시는 작업 끝에 다시 계산해 처음 값과 같았다. 새 퍼징, 다른 후보 선택, held-out 실행은 하지 않았다. commit·push·PR은 하지 않았다.
