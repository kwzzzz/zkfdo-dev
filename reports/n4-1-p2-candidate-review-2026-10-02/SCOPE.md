# S-01 사전 범위: P2 `Subtract()` 후보 한 개의 의미 검토

2026-10-02 · 버전 `p2-candidate-review-v1` · 담당 miiz.

**상태:** 후보 값을 열기 전에 고정했다(2026-10-01T16:04Z, 한국 시각 10-02 01:04). 이 시점까지 후보 파일은 해시만 계산했고 내용은 열지 않았다.

[A-01 인계](../../docs/next_policy_a_handoff_2026-10-02.md)의 독립 검토 범위이며 A-01 구현과 무관하다. 기존 P2의 판정·실행 기록은 바꾸지 않는다.

## 1. 대상 후보

[인계](../../docs/next_policy_a_handoff_2026-10-02.md)가 지정한 한 개다. 결과를 보고 고른 후보가 아니다.

| 항목 | 값 |
|---|---|
| 후보 파일 | `runs/dev-rq1-pilot-2026-09-29/inference-main/campaign/small-first/block-1/execution/execution-dea86966-f3b8-425b-b67c-607073d18d40/counterexample-candidates/0002/src__subtractTensor__Subtract.circom_VtOrmtp2AL_counterexample.json` |
| 후보 SHA-256, 크기 | `38554c0e4c67fa529044ef8516dee5812a5a28145f72137aa44ddc94a0c80a25`, 2,152 bytes |
| outcome | 같은 실행의 `outcome.json`, `a84ed78074bb885c74bf22e1b1e2835b3465b4db2ccead4325269e043b3a27e0`, outcome ID `6f8a169f-db6c-43b7-86ef-a062b14dd9e1` |
| plan | `b8843d8b816c6b36934556a98b78d75f711f714212015688e3b0025e76e1cc7f`, 전략 small-first, block 1, zkFuzz seed 2026092931, mutation 설정 `eb097ac3…3fff` |
| run / target | run `5be06d85-4440-4c29-aaa9-1307c54d8ba0` (plan 두 번째 조각, `bug_found`, last generation 0, wall 0.030471초) / target `sha256:1830b5991e7c31effb5249dccfc0f125fa1e5cc8099cfcdb5dc7d0e9bde75cb3` |

outcome에는 후보가 10개 있다. 검토 대상은 이 한 개뿐이다. 다른 후보와 다른 block의 후보는 열거나 판정하지 않는다.

## 2. 원본과 컴파일 조건

- **프로젝트:** `inference-labs-inc/subnet-2-circom` revision `d310309c141d36504b3486cebd96ed70ef3a4fdf`. P2 설정과 zkbugs의 Commit이 같다.
- **템플릿 소스:** P2 snapshot의 `targets/0019/sources/src/subtractTensor.circom`, SHA-256 `502ee44b70a368066fafcf09cc2d0356479f8a862bfa726bde8097c728c83cc1`. 저장소에 고정된 취약본 `datasets/controlled-v1/subtract/vulnerable/subtractTensor.circom`(git blob `f4f07f3c…`)과 같은 바이트다.
- **wrapper:** `targets/0019/sources/zkfdo-targets/src__subtractTensor__Subtract.circom`, SHA-256 `1665e793a060f63336a8256b48b789915897b8eeb40d65f60118dd5605068c7b`. 내용은 `include "../src/subtractTensor.circom"`과 `component main = Subtract();`뿐이다.
- **준비 R1CS:** `14c18b08f5697b259526002cb217552c0a08ddc236fdb357bee2f40409cfb04f`(prepared.json `da6b4396…4122`).
- **컴파일:** circom 2.2.3(`8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227`), `--r1cs --prime bn128`, 라이브러리 경로는 P2 tree·zkbugs dependencies·circomlib 순서, 최적화 flag는 지정하지 않음(컴파일러 기본값). 재컴파일은 출력 경로와 `--sym --wasm`만 더하며, 준비 R1CS와 바이트 단위로 같아야 한다.
- **수정 비교본:** 저장소에 고정된 `datasets/controlled-v1/subtract/fixed/subtractTensor.circom`. revision `b8f92bdec1694138df0e069921f1aa0bdc94053e`, SHA-256 `c5d6aa9de7e95f09283e6b014dcbda85e16e583c3e157d7f8fdd95bb001023ba`, git blob `ede21538…`, wrapper `circuit.circom`(`5160da57…`). 같은 방식으로 컴파일한다.
- **재계산 도구:** node 26.0.0(`08dad058…`), snarkjs 0.7.6(`cli.cjs` `6d787e37…`). zkFuzz(`ac2d9d16…`)는 실행하지 않는다.

## 3. 입력 전제와 일반 TCCT 속성

**인터페이스와 제약.** 입력은 `a`, `b`, 출력은 `c`다. 내부 신호 `d`는 `d <-- 1`로 값만 계산되고 제약되지 않는다. 제약은 `c <== (a - b)*d` 하나다.

**입력 전제.** `a`, `b`는 정규 BN128 스칼라 필드 원소다(0 ≤ a, b < p). 다른 범위 전제는 없다. 근거는 세 가지다: 소스에 범위 검사가 없음, P2 target 계약 `field_only`, [v1 계약](../../datasets/contracts.controlled-v1.json)(`d954de5f…`)의 같은 진술.

**일반 TCCT 속성(출력 차이형).** 후보와 같은 입력으로 고정 컴파일 산출물의 정직한 계산(Circom witness 생성기)을 수행해 정직한 출력 `c_h`를 얻는다. 다음 세 조건이 모두 성립하면 후보가 속성을 위반한 것이다: 후보의 전체 할당이 원본 제약을 모두 만족함, 입력 전제가 성립함, `c ≠ c_h`. 소스에 `assert`가 없으므로 abort형은 해당하지 않는다. 그래도 정직한 계산이 중단되면 abort로 기록하고, 속성 판정은 미판정으로 둔다.

**기존 명세와의 일치 확인.** zkbugs README(`15ac12cf…`)·config(`891a2606…`)와 v1 계약의 속성 `subtract-output-binding`(c = a − b mod p)에 대해, `c_h = a − b mod p`인지를 별도 단계로 확인한다. 속성 판정 자체는 정직한 계산과의 비교로 한다.

zkFuzz가 스스로 보고한 flag나 출력은 메타데이터로만 쓴다. 위치 일치는 근거로 쓰지 않는다.

## 4. 단계별 판정과 중단 기준

| 단계 | 방법 | 통과 | 실패 / 미판정 |
|---|---|---|---|
| 0. 연결 | 후보 해시와 outcome 기록, run·target·plan, `bug_found`, 소스·wrapper·R1CS 해시를 대조 | 모두 일치 | 하나라도 불일치하면 중단하고 미판정 |
| 1. 원본 제약 전체 만족 | 후보 할당의 신호 이름이 `main.a/b/c/d`와 정확히 같아야 한다. 재컴파일 `.sym`으로 wire에 대응시키고 정규성을 확인한다. 두 방법으로 모든 제약을 평가한다: (a) Python R1CS 평가기, (b) 후보로 만든 `.wtns`의 `snarkjs wtns check` | 두 방법 모두 만족 | 둘 다 불만족이면 실패(확인 아님). 결과가 엇갈리거나 이름이 결측·추가·모호하면 미판정 |
| 2. 정상 계산과의 차이 | 재컴파일 WASM으로 후보 입력의 정직한 witness를 계산한다. 그 witness도 `wtns check`를 통과해야 한다. 신호별(`a, b, c, d`)로 비교하고, 소스 의미에 따른 Python 재계산으로 교차 확인한다 | `c`가 다르면 출력 차이 | 같으면 차이 없음. 정직한 계산이 중단되면 abort로 기록하고 그 뒤 단계는 미판정 |
| 3. 사전 속성 위반 | §3의 정의 | 위반 확인 | `c = c_h`이면 위반 아님(실패). 입력 전제 불충족이나 앞 단계 미판정이면 미판정 |
| 4. 원인 귀속 | 알려진 원인 `koukyosyumei_subtract_unconstrained_multiplier`. 세 조건을 모두 본다: (i) 후보와 정직한 할당의 차이가 `{d, c}`로 한정되고 `d ≠ d_h`, (ii) `a ≠ b`, (iii) 수정 비교본 R1CS가 후보의 `(a, b, c)`를 거부한다. 수정본의 신호는 이 셋뿐이므로 이 셋이 완전한 할당이다. 대조로 정직한 `(a, b, c_h)`는 수정본을 만족해야 한다. 판정은 두 평가 방법으로 한다 | 세 조건 모두 성립 | 하나라도 성립하지 않으면 미판정(다중 원인이나 대응 실패 가능성). 위치 일치만으로는 귀속하지 않음 |

다음 층은 자료가 없으므로 이번에 판정하지 않고 미판정·별도 층으로 남긴다: 호출 맥락의 배제와 도달성(entrypoint의 `MetricNormalized`, `ResponseTimeNormalized` 등), entrypoint TCCT, 프로젝트 의미.

**중단 기준.**
- 재컴파일 R1CS가 준비 R1CS와 다르면 중단하고 미판정으로 둔다.
- 도구 오류가 나면 기록하고, 그 결과에 의존하는 단계를 미판정으로 둔다.
- 각 명령의 제한 시간은 60초다.
- 새 퍼징, 다른 후보 선택, P2 기록·A-01 코드·record/aggregate 코드 수정은 하지 않는다.

## 5. 실행 범위

정직한 witness 재계산을 포함해 다음만 실행한다.

1. ignored `runs/n4-1-p2-candidate-review-2026-10-02/`에 소스와 wrapper(취약본·수정본)를 해시를 확인하며 복사한다.
2. 위 조건으로 각각 컴파일한다.
3. 정직한 witness를 계산하고 `snarkjs wtns check`·`export`를 실행한다.
4. 후보 `.wtns`를 생성하고 검사한다.
5. Python으로 R1CS를 평가하고 신호를 비교한다.

후보 할당과 witness의 원시 값은 이 디렉터리 밖으로 옮기지 않는다. 명령·종료 코드·시간 ledger도 이 디렉터리에 둔다. 값 없는 [REPORT](REPORT.md)에는 증거 해시, 단계별 판정, 독립 검산 방법, 검토 비용, 주장 한계만 적는다.

**검토 비용.** 도구 프로세스 시간(ledger)과 담당자 작업 구간(이 SCOPE 고정부터 REPORT 완료까지의 벽시계)을 따로 적는다. 사람의 실제 작업 시간은 계측하지 않으므로 unknown으로 둔다.

이 검토는 개발 사례 후보 하나의 의미 검토다. P2에는 통째 후보가 없으므로 같은 수준의 양쪽 비교를 통과한 것이 아니다. 결과를 A-01의 새 후보에 자동으로 복사하지 않는다.
