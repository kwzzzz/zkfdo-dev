# S-01 결과: P2 `Subtract()` 후보 한 개의 의미 검토

2026-10-02 · 버전 `p2-candidate-review-v1` · 담당 miiz.

**상태: 완료.** 후보 값을 열기 전에 [사전 SCOPE](SCOPE.md)(SHA-256 `24cec8f8fbdb8747cbf68d42722994890ec2a8ef019ada4d851627c2fde7da76`)를 고정했다. 검토 스크립트 [review_candidate.py](review_candidate.py)(`31b8b72201f5cb9bd7aa775c167a414d0c276a496449b546c2122b8e81987d58`)는 이 해시를 확인한 다음에야 후보를 읽는다. 원시 값은 ignored `runs/n4-1-p2-candidate-review-2026-10-02/run-v1/` 안에만 있다.

## 결론

사전 지정한 P2 small-first block 1의 `Subtract()` 후보 하나(후보 SHA-256 `38554c0e4c67fa529044ef8516dee5812a5a28145f72137aa44ddc94a0c80a25`)를 검토했다. 결과는 다음과 같다.

- **컴포넌트 수준의 일반 TCCT(출력 차이형)에서 확인했다.**
- **원인 귀속:** 알려진 원인 `inference-labs-inc/subnet-2-circom/koukyosyumei_subtract_unconstrained_multiplier`에 귀속했다.
- **판정하지 않은 층:** 호출 맥락 배제·도달성, entrypoint TCCT, 프로젝트 의미는 자료가 없어 미판정으로 남긴다.

| 단계 | 판정 | 독립 검산 방법과 근거 |
|---|---|---|
| 0. 연결 | 통과 | 다음이 모두 일치했다: 후보 해시와 outcome(`a84ed780…7e0`)의 후보 기록, run `5be06d85-…`·target `sha256:1830b599…`·plan(`b8843d8b…7cc7f`), backend 상태 `bug_found`, prepared(`da6b4396…4122`)·소스(`502ee44b…3cc1`)·wrapper(`1665e793…8c7b`) 해시 |
| 재현 조건 | 통과 | 같은 circom 2.2.3과 같은 인자에 `--sym --wasm`만 더해 재컴파일했다. R1CS가 준비 R1CS `14c18b08f5697b259526002cb217552c0a08ddc236fdb357bee2f40409cfb04f`와 바이트 단위로 같다. 구조는 wire 5, 출력 1, 비공개 입력 2, 제약 1 |
| 1. 원본 제약 전체 만족 | 통과 | 후보 할당의 신호가 `main.a/b/c/d`와 정확히 같고 모두 정규 필드 원소다. 두 방법이 모두 만족을 확인했다: (a) 독립 Python R1CS 평가기, (b) 후보로 만든 `.wtns`(`c78c7dd5…`)의 `snarkjs wtns check`. 로컬 `.wtns` 작성기는 정직한 witness를 다시 써서 검사하는 양성 대조를 통과했다 |
| 2. 정상 계산과의 차이 | 출력 차이 | 재컴파일 WASM으로 같은 입력의 정직한 witness(`43dacdf9…`)를 계산했고, 제약 검사를 통과했다. 소스 의미(`d = 1`, `c = a − b`)에 따른 Python 재계산과도 일치했다. 후보와 다른 신호는 `main.c`와 `main.d`뿐이다. 소스에 `assert`가 없으며 abort는 관측되지 않았다 |
| 기존 명세와의 일치 | 통과 | 정직한 출력이 zkbugs와 v1 계약의 `subtract-output-binding`(c = a − b mod p)과 같다 |
| 3. 사전 속성 위반 | 위반 확인 | 입력 전제(정규 BN128 원소)가 성립한다. 원본 제약을 모두 만족하면서 같은 입력의 정직한 출력과 다른 `c`를 가진다 |
| 4. 원인 귀속 | 귀속 | 세 조건이 모두 성립했다. (i) 차이가 `{d, c}`로 한정되고 `d`가 정직한 값과 다름. (ii) `a ≠ b`. (iii) 고정 수정본의 R1CS(`842a28ea3c545079f8802e5593bc4d13de4e19f0f453ed432ed77929d9240ac8`)가 후보의 `(a, b, c)`를 거부함: Python 평가기가 불만족을 보였고 snarkjs는 `WITNESS IS NOT CORRECT`로 거부했다. 수정본은 b8f92bde, 소스 `c5d6aa9d…`이며 신호가 a·b·c뿐이라 이 셋이 완전한 할당이다. 대조로 정직한 `(a, b, c_h)`는 두 방법 모두에서 수정본을 만족했다. 방법은 수정 제약 거부와 소스 검토이며, 위치 일치에 기대지 않았다 |
| 호출 맥락 배제·도달성 | 미판정(별도 층) | 검토 범위 밖이다. `MetricNormalized`, `ResponseTimeNormalized` 등의 호출자 제약과 도달성은 검토하지 않았다 |
| entrypoint TCCT·프로젝트 의미 | 미판정(별도 층) | 자료가 없다. 프로젝트 결함으로 승격하지 않는다 |

zkFuzz가 후보 파일에 남긴 메타데이터는 근거로 쓰지 않고 대조에만 썼다. 메타데이터는 템플릿 `Subtract`, 탐색 방식 `ga`, zkFuzz git hash `072bf1fbbd1c9ecad58d4f6d2204c3b96e7fec17`, flag 유형 `UnderConstrained-NonDeterministic`이다. zkFuzz가 보고한 기대 출력은 독립 재계산의 정직한 출력과 같았고, 후보의 출력은 그와 달랐다.

## 증거 경로와 해시

| 자료 | 경로 | SHA-256 |
|---|---|---|
| 값 없는 결과 | `runs/n4-1-p2-candidate-review-2026-10-02/run-v1/result.json` | `9644796f226f2de0117e5f6de0ec9fc2076d23cbed6f2155e564c73e25a15387` |
| 명령 ledger | `…/run-v1/ledger.json` | `78e4af629b87bb56f5dab1972f01403f5e1c093c06f04e1297e5bafde05e13aa` |
| 원시 값(ignored, 값 포함) | `…/run-v1/raw-values.json` | `1ad3904c4539753ec1a82be59089cb42af649a0042d1d6dbc0f04498b6a617d3` |
| 후보 `.wtns` / 정직한 `.wtns` | `…/run-v1/candidate.wtns`, `…/run-v1/honest/honest.wtns` | `c78c7dd5fcd81cba413b3b23199ed20edd8e58600e7dcefc35012f463d6e5eec` / `43dacdf96aa068442987de5f9829bd93a2d71c5c26dad62adea6739e99bc9ac4` |
| 재컴파일 R1CS: 취약본 / 수정본 | `…/compiled-vulnerable/…Subtract.r1cs`, `…/compiled-fixed/circuit.r1cs` | `14c18b08…b04f` / `842a28ea…40ac8` |

도구는 다음과 같다: circom 2.2.3(`8991887889c2…6227`), node 26.0.0(`08dad0581f00…c164`), snarkjs 0.7.6(`cli.cjs` `6d787e37a4d1…051a`). zkFuzz는 실행하지 않았다.

원시 값은 runs 안의 파일에만 저장했다. 메타데이터를 확인하던 중 zkFuzz 기대 출력 값 하나가 검토 터미널에 표시됐지만, 어떤 추적 파일에도 옮기지 않았다.

## 검토 비용

**도구 프로세스:** 9개, wall 합계 1.244초.
- 컴파일 2회: 0.021초
- 제약 검사 5회: 1.090초
- 정직한 계산: 0.044초
- export: 0.088초

**스크립트 전체:** 1.273초(2026-10-01T16:07:52Z 시작).

**담당자 작업 구간:** 인계 확인 시작 16:00Z, SCOPE 고정 16:04Z, 검토 실행 16:07–16:08Z, 이 보고서 완료 16:10Z다(한국 시각 10-02 01:00–01:10). 사람의 실제 작업 시간은 계측하지 않아 unknown이다. 프로세스 시간이나 이 벽시계 구간으로 대신하지 않는다.

## 주장할 수 있는 범위와 한계

사용할 수 있는 문장은 다음 하나다.

> 사전 지정한 P2 개발 실행의 `Subtract()` 조각 후보 하나는, 고정 컴파일 조건에서 원본 제약 전체를 만족하면서 정직한 계산과 다른 출력을 가져 일반 TCCT 컴포넌트 속성을 위반했고, 고정 수정본의 제약 거부와 소스 검토로 알려진 unconstrained multiplier 원인에 귀속됐다.

다음은 이 결과로 주장하지 않는다.
- **같은 수준의 양쪽 비교:** P2에는 통째 후보가 없으므로 통째·분할 비교를 통과한 것이 아니다.
- **P2 기존 기록의 변경:** P2의 위치 일치 판정과 기록은 바꾸지 않는다. 같은 outcome의 다른 후보 9개와 다른 block의 후보는 열거나 판정하지 않았다.
- **새 고유 원인:** 이 원인과 R1CS(`14c18b08…`)는 controlled-v1.1에서 검토한 Subtract 원인과 같다. 따라서 새 고유 원인이나 독립 사례가 아니며, 개발에 노출된 사례다.
- **맥락·entrypoint·프로젝트 결론:** 호출 맥락 배제·도달성, entrypoint TCCT, 프로젝트 결함은 판정하지 않았다.
- **확대 적용:** 탐지 우위가 아니다. 이 판정을 A-01의 새 후보에 자동으로 적용하지 않는다.

기존 P2 run 원문·판정, A-01 코드·행, record/aggregate 코드는 수정하지 않았다. 새 퍼징, 다른 후보 선택, 문헌 조사는 하지 않았다. commit·push·PR은 하지 않았다.
