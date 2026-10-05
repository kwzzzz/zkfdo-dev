# N4-1 정상 계산·준비 비용 실제 실행

| 실제 실행 대상 | 성공/실패 | 실제 컴파일 수, 미재사용 → 재사용 | 준비 시간, 미재사용 → 재사용 | 정상 경계 비교 |
|---|---|---|---|---|
| 기존 `target_discovery/ProjectMain(64)` 정상 산술 fixture | 4조건 실행 모두 성공, 컴파일 실패 0 | **16 → 16회** | **0.157419 → 0.150831초** | **84/84 일치** |
| 작은 산술 통제 `Root → Step(2), Step(3), Branch(5)` | 4조건 실행 모두 성공, 컴파일 실패 0 | **12 → 8회** | **0.130137 → 0.078667초** | **60/60 일치** |

컴파일 수는 **각 방식 2회 합계이며 원본 컴파일을 포함**한다. 준비 시간은 방식별 1회 평균이다. 각 실행에 고정된 정상 입력 3개를 사용했다. 정상 경계 비교는 미재사용/재사용 각각 2회, 총 4회에 걸친 검사 횟수이며 독립 사례 수가 아니다. 전체 원본 정상 계산 **24회**, wrapper 정상 계산·경계 비교 **144회**, 생성 witness의 R1CS 검사 **168회**가 통과했다. 원본·wrapper의 실제 컴파일은 총 **52회**, 실패·timeout·프로세스 시작 실패는 **0회**다.

2026-10-01, 결과 버전 `normal-preparation-results-v1`, 담당 miiz. [사전 실행 범위](SCOPE.md)를 기록한 뒤 [측정 코드](../../scripts/measure_normal_preparation.py)를 구현·실행했다. 값 없는 수치·해시 근거는 [evidence.json](evidence.json)에 있다. **정상 계산과 이 입력들의 경계 일치 관측이며, 탐지 우위나 일반적인 wrapper 의미 동등성의 증명이 아니다.** N4-1 전체 관문을 완료 처리하지 않는다.

## 실행 대상과 자동 구성

기존 개발용 [discovery fixture](../../tests/fixtures/target_discovery/main.circom)는 모두 입력에 상수를 더했다 빼는 정상 산술이다. 정상 입력 파일과 동일 파라미터 반복 호출은 없어서, 세 정상 입력을 고정하고 작은 결함 없는 산술 통제를 추가했다. 실제 결함이 있는 개발 사례의 재현 입력이나 새 외부 프로젝트를 가져오지 않았다. 통제 소스·정상 입력·할당은 ignored 실행 디렉터리에만 생성했다.

- 기존 fixture: child 호출 위치 7개, wrapper 구성 7개. `Bits(8/32/256)` 등 파라미터가 다른 구성을 포함하며 공유 가능한 동일 구성은 없다.
- 산술 통제: 호출 위치 5개, wrapper 구성 3개. `Step(2)`는 `main.a`, `main.b`, `main.m.inner`에서 쓰이고 `Step(3)`, `Branch(5)`가 별도로 있다. 파라미터가 계산 결과에 실제 영향을 주며 반복 호출에도 서로 다른 정상 경계 입력이 전달된다.
- 기존 `zkfDO targets --no-validate`가 대상과 wrapper를 자동 생성했다. unsupported·누락·수동 wrapper 대체는 없다. discovery 보고서의 wrapper 상태는 원래 `generated`로 보존하며, 실제 후속 artifact 컴파일 성공은 별도 도구 기록에서 확인했다.
- `--no-validate`를 사용했으므로 discovery 안에서 숨은 `--inspect` 컴파일은 하지 않았다. 실제 Circom 호출은 모두 아래 artifact 컴파일 수에 포함한다.

재사용 비교는 **동일 현행 discovery/wrapper 생성 후, artifact 컴파일을 호출 위치마다 수행하는 조건과 완전한 캐시 키마다 수행하는 조건**이다. 제품의 기존 `targets --inspect` 경로 자체의 전후 측정이나 과거 바이너리 전체의 성능 비교라고 해석하지 않는다.

## 조건, 계산과 대응 확인

- 두 대상 모두 같은 `--O0 --r1cs --wasm --sym --inspect --prime bn128`와 대상 snapshot을 사용했다. include 경로는 해당 프로젝트 snapshot이다. 명령별 timeout은 60초다.
- 각 대상에서 1회차 미재사용→재사용, 2회차 재사용→미재사용 순으로 실행했다. 각 조건의 application cache와 artifact 출력 디렉터리는 새로 만들었다. 조건 간 컴파일 산출물 재사용은 없다. OS 파일 캐시는 비우지 않았고, 공유 개발 머신의 모든 백그라운드 활동을 통제하지는 않았다.
- 캐시 키는 wrapper 본문 hash, 전체 include 의존성 경로/hash, 컴파일러 경로/hash, compiler flags, library 경로와 timeout이다. 입력 소스가 discovery 후 바뀌면 실패한다. 같은 wrapper를 공유해도 호출 위치와 원본 경계 경로는 유지한다.
- 정상 계산은 Circom이 생성한 WASM·`generate_witness.js`를 Node로 실행했다. 원본과 각 wrapper의 생성 witness에 `snarkjs wtns check`를 실행하고 성공 exit와 명시적 `WITNESS IS CORRECT` 출력을 확인했다. 할당을 수정하거나 다른 입력을 탐색하지 않았다.
- 원본은 간단한 정상 산술 식으로 계산한 예상 최상위 출력도 확인했다. discovery의 `parent_instance_key`/`instance_key`/component 이름으로 호출 경로를 확장하고, 원본 `.sym`의 해당 `in/out`을 wrapper의 `main.in/out`과 비교했다. wrapper 입력은 확인된 원본 경계 입력에서 가져왔다.
- 소실된 witness index, 없는 signal, 고아/순환/중복 호출 경로는 추정하거나 0으로 채우지 않고 실패하게 했다. 이번 두 scalar `in/out` fixture의 O0 대응만 확인했으며 임의 배열·최적화·다른 프로젝트의 일반 대응은 입증하지 않았다.

## 실제 비용과 원본 도구 기록

준비 시간은 자동 탐색·wrapper 생성부터 원본과 필요한 wrapper artifact 컴파일 및 출처 hash 기록까지의 wall time이다. 정상 계산·제약 검사·witness export·경계 비교 시간은 **별도**이며 준비 시간에 숨겨 넣거나 무료로 취급하지 않는다. 소스 snapshot 생성, 개발 도구 빌드, 버전 조회와 최종 보고 작성은 이 준비 구간 밖이다. CPU 사용량·메모리는 이번에 측정하지 않았다.

| 대상 | 반복·방식 | 원본 + wrapper 컴파일 | 컴파일 성공/실패 | 준비 wall(초) | 컴파일 wall 합계(초) | 정상 검증 wall(초) | 경계 일치 |
|---|---|---:|---|---:|---:|---:|---|
| 기존 fixture | 1 미재사용 | 1 + 7 | 8/0 | 0.172626 | 0.110543 | 10.377363 | 21/21 |
| 기존 fixture | 1 재사용 | 1 + 7 | 8/0 | 0.152684 | 0.099871 | 10.141683 | 21/21 |
| 기존 fixture | 2 재사용 | 1 + 7 | 8/0 | 0.148979 | 0.087673 | 10.303434 | 21/21 |
| 기존 fixture | 2 미재사용 | 1 + 7 | 8/0 | 0.142211 | 0.090251 | 10.482520 | 21/21 |
| 산술 통제 | 1 미재사용 | 1 + 5 | 6/0 | 0.159762 | 0.089934 | 7.815336 | 15/15 |
| 산술 통제 | 1 재사용 | 1 + 3 | 4/0 | 0.079427 | 0.040308 | 7.639796 | 15/15 |
| 산술 통제 | 2 재사용 | 1 + 3 | 4/0 | 0.077908 | 0.039300 | 7.759047 | 15/15 |
| 산술 통제 | 2 미재사용 | 1 + 5 | 6/0 | 0.100513 | 0.058692 | 7.308391 | 15/15 |

표의 수치는 원본 프로세스 기록과 조건별 결과에서 대조한 실측값이다.

**원본 실행 기록:** [commands.jsonl](../../runs/n4-1-normal-execution-2026-10-01/run-v1/commands.jsonl), [conditions.json](../../runs/n4-1-normal-execution-2026-10-01/run-v1/conditions.json), [summary.json](../../runs/n4-1-normal-execution-2026-10-01/run-v1/summary.json). 568개 프로세스 기록은 버전 조회 4, discovery 8, 실제 컴파일 52, 정상 계산 168, 제약 검사 168, witness export 168개다. 집계는 이 ledger와 조건별 `result.json`을 직접 대조했으며 `experiment aggregate`를 호출하지 않았다. 산출물 manifest의 파일 1,964개 해시를 재검사했다.

실험 단계의 오류나 중단은 없었다. 단, snarkjs `--version` 조회는 버전/도움말을 출력하고 exit 99를 반환했으며 원래 로그와 exit를 보존했다. 이를 컴파일·계산 실패로 합산하거나 exit 0으로 고치지 않았다.

## 도구와 보존

| 도구 | 실행 버전 | 실행 파일 SHA-256 |
|---|---|---|
| Circom | 2.2.3 | `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227` |
| Node | 26.0.0 | `08dad0581f00a0cabf4d49ec92ca1f25fdfd01c2c18fa8e92b35f04d4c24c164` |
| snarkjs CLI | 0.7.6 | `6d787e37a4d1a2c6dd6032dadca09c0b3b007d4d4578bb6232a98136555d051a` |
| zkfDO | 0.1.0, 로컬 debug build | `227921c4c6aaf946580cbefc4a416c4833f41b200879d22751bbcf2498d83a60` |

측정 스크립트 SHA-256은 `3cc384a4fa6e52f048073bc1626e03b9370049d221c90090a05f181d6fa80880`, 실행 ledger는 `284c8a280da3be5f7544eaf283a8eb20aff94b04a79e333ccb4e751eea3e3f14`, raw summary는 `fa9efa9d36cd61114642d3312c1d295ab221be2979361e0052c223f2c967b4f0`이다. 소스별 hash, 플랫폼·Python 버전, 명령·로그·각 입력/witness/artifact의 경로/hash는 evidence와 raw manifest에 남겼다. 측정한 zkfDO 바이너리와 discovery 소스 snapshot, Python 실행 파일 및 snarkjs package metadata hash는 별도 [보존 영수증](../../runs/n4-1-normal-execution-2026-10-01/provenance-v1/receipt.json)에 있다.

원시 입력·할당·컴파일 산출물은 ignored `runs/` 안에 있고 기존 실행이나 판정을 덮어쓰지 않았다. 같은 스크립트 재실행은 새 출력 디렉터리를 요구한다. 이번 실행 명령은 다음과 같다.

```text
python3 scripts/measure_normal_preparation.py --output runs/n4-1-normal-execution-2026-10-01/run-v1
```

## 검사와 남은 N4-1 조건

새 [경계 매핑 테스트](../../tests/normal_preparation_test.py) 4개가 통과했다. 재사용 구성의 서로 다른 호출 경로 보존, 고아/순환/모호한 경로 거부, 소실/없는 signal의 비추정, 기존 출력 보존을 검사한다. 실제 정상 실행 결과를 합성 테스트의 성공으로 대신하지 않는다.

- `cargo fmt -- --check` 통과. 구현 담당 소유 소스를 변경하지 않기 위해 포매터는 검사 모드로 실행했다.
- `cargo clippy --all-targets --all-features -- -D warnings` 통과.
- `cargo test`: **285 통과·0 실패·22 ignored**. 기존 ignored 실제 산출물 테스트는 실행하지 않았다. 이번 실제 실행 결과는 위 별도 정상 하네스에서 얻었다.
- Python unittest: **4 통과·0 실패**. 기록/집계 코드·관련 테스트·문서는 수정하지 않았다.

이번 두 작은 회로의 자동 구성 → 실제 artifact 컴파일 → 정상 계산 → 전체 R1CS 검사 → 확인된 경계 비교는 연결됐다. 같은 구성의 wrapper artifact 재사용으로 컴파일 횟수가 줄었고, 확인한 정상 입력의 경계 결과는 유지됐다. 기존 fixture의 작은 시간 차이와 산술 통제 2회 반복으로 통계적 성능 우위나 cold-cache 성능을 주장하지 않는다.

**N4-1 전체 관문은 미완료다.** 임의 회로·최적화에서의 신호/인스턴스 대응, 통째·분할의 같은 수준 판정과 원인 귀속, abort·입력 전제, wrapper 일반 의미 보존, A안 종료/잔여·실제 자원·공정성 검증은 남는다. 정상 witness 계산은 취약점 재현·새 결함 후보 생성이 아니다. 기록·집계 추가 개발은 구현 담당으로 유지하고 이번 수치의 근거로 쓰지 않았다. N4-2 미착수, N5 미고정과 평가 후보 퍼징 금지를 유지한다. commit/push/PR은 하지 않았다.
