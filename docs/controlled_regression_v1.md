# Controlled regression/evaluation set v1

작성일: 2026-09-19

## 상태

| 항목 | 상태 |
|---|---|
| 원본·수정본 자료 준비 | **완료** |
| manifest/계약/해시 연결 | **완료** |
| 현재 비교 환경의 Circom 컴파일 | **완료** |
| zkFuzz 탐색 | **실행하지 않음** |
| 반례·witness·proof 생성 또는 평가 | **실행하지 않음** |
| 검토된 원본 component 발견 수·시간 | **미측정 (`null`)** |

이 상태는 평가 입력 자료가 준비됐다는 뜻이다. zkFuzz가 결함을 탐지했거나 수정본이
전체적으로 안전하다는 뜻이 아니다.

## 선정한 한 쌍

`inference-labs-inc/subnet-2-circom`의 `Subtract()`를 v1의 유일한 쌍으로
선정했다. dev3에서 사용한 Reclaim 세 원인과 겹치지 않고, 공개 PR이 취약 revision을
첫 부모로 갖는 fix merge이며, 변경 전후 component가 작고 속성이 명확하기 때문이다.

| 역할 | revision | Git blob | 파일 SHA-256 |
|---|---|---|---|
| 공개 취약 원본 | `d310309c141d36504b3486cebd96ed70ef3a4fdf` | `f4f07f3c614299a02b97ea64338e4843a608c03c` | `502ee44b70a368066fafcf09cc2d0356479f8a862bfa726bde8097c728c83cc1` |
| 수정 비교본 | `b8f92bdec1694138df0e069921f1aa0bdc94053e` | `ede21538dc3f7a03e68775d1bd2e0ac482f6366e` | `c5d6aa9de7e95f09283e6b014dcbda85e16e583c3e157d7f8fdd95bb001023ba` |

수정 revision은 merge commit이며 부모는 `d310309c…`와 `4d9012d8…`이다.
따라서 취약 revision이 첫 부모인 관계를 공개 commit API로 확인했다. 공개
[PR #2](https://github.com/inference-labs-inc/subnet-2-circom/pull/2)는
`Subtract`의 불필요한 `<--`를 제거한다고 설명하고, 수정 source는 `d`를 제거해
`c <== a - b`로 바꾼다. 로컬 zkbugs checkout
`a0eed744ba1a816acaa2fae597f4e79b4fd01aea`의 metadata와 README에도 같은 원인이
기록돼 있다.

보존 source는 다음과 같다.

- [취약 source](../datasets/controlled-v1/subtract/vulnerable/subtractTensor.circom)
- [수정 source](../datasets/controlled-v1/subtract/fixed/subtractTensor.circom)
- 두 variant의 [동일한 최소 wrapper](../datasets/controlled-v1/subtract/vulnerable/circuit.circom)는 source를 include하고 `component main = Subtract();`만 선언한다.

wrapper SHA-256은 양쪽 모두
`5160da57762a5a561cf797a44f2dd6f009126536be476cbcec0926459362e079`다.
이는 평가를 위해 만든 direct wrapper이며 원 프로젝트 entrypoint라고 주장하지 않는다.

## 고정 평가 계약

component 인자는 없고 입력은 `a`, `b`, 출력은 `c`다. 입력 전제는 `a`와 `b`가
BN128 scalar field의 canonical element라는 것뿐이다. 별도의 unsigned/signed 정수
범위는 가정하지 않는다.

평가 전에 고정한 속성은 다음과 같다.

```text
모든 만족 assignment에서 c = a - b (mod BN128 scalar-field prime)
```

취약 source는 `d <-- 1`을 R1CS 제약으로 만들지 않고
`c <== (a - b) * d`만 제약한다. 공개 기록은 이를 알려진 under-constraint로
분류한다. 이 정적 사실과 알려진 결함 표시는 이번 실행의 발견이 아니다.

실행 성과로 인정하려면 같은 plan의 `bug_found` run/target에서 나온 후보가 다음을
모두 통과해야 한다.

1. 위 입력 전제를 만족한다.
2. 선택한 고정 revision의 모든 제약을 만족한다.
3. `c != a - b (mod p)`로 사전 고정 속성을 위반한다.

고유 원인 ID는
`inference-labs-inc/subnet-2-circom/koukyosyumei_subtract_unconstrained_multiplier`다.
seed, 전략, wrapper 또는 같은 원인의 변형에서 반복되더라도 한 평가 안에서는 한
원인으로 중복 제거한다.

수정본은 해당 공개 수정의 regression comparator다. 같은 속성을 source에서 직접
제약한다는 제한된 기대만 둔다. 다른 결함이 없거나 프로젝트 전체가 안전하다고
표시하지 않으며, 예상 밖 후보도 같은 세 조건으로 검토한다.

세부 계약과 variant 관계는
[contracts.controlled-v1.json](../datasets/contracts.controlled-v1.json)에 고정했다.
취약·수정 variant와 이후의 parameter/wrapper 변형은 같은 `leakage_group_id`에
속한다. 이 원인을 개발 세트로 옮기거나 결과를 본 뒤 랭킹 가중치를 조정하면
held-out 역할을 잃는다.

## corpus manifest와 준비 검증

[manifest.controlled-v1.json](../datasets/manifest.controlled-v1.json)은 기존
`CorpusManifest` schema 1을 그대로 사용한다. 취약 target의 `known_defects`는 공개
provenance이며 fixed target에는 known defect label을 넣지 않았다.

현재 비교 환경은 다음과 같이 기록했다.

| 항목 | 값 |
|---|---|
| Circom | `circom compiler 2.2.3` |
| Circom binary SHA-256 | `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227` |
| field | 명시적 `bn128` |
| compile args | 없음 |
| zkFuzz | revision `072bf1fbbd1c9ecad58d4f6d2204c3b96e7fec17`, version `2.2.1` |
| zkFuzz binary SHA-256 | `ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd` |

이 환경은 앞으로의 비교 설정이며 과거 프로젝트 빌드 환경이 아니다.

`path-order` 준비 모드로 source inspection과 Circom 컴파일만 수행했다. 두 target은
모두 eligible이고 컴파일에 성공했으며 각각 제약 1개를 생성했다.

| variant | target ID | 준비 판정 |
|---|---|---|
| vulnerable | `sha256:1fdbf2dbcb8c5be4cad2ef0937cdc95c1b36cc8321e2d02f1b820f46c1b91474` | eligible, compile success |
| fixed | `sha256:a85819549a69210934d31e3fa4a0ba4e01f1f456bc86b32a480a29c5b18aec91` | eligible, compile success |

사용한 검증 명령의 형태는 다음과 같다. 출력은 임시 디렉터리에 만들었고 저장소에는
R1CS를 추가하지 않았다.

```sh
cargo run --offline --quiet --bin zkfDO -- experiment prepare \
  --manifest datasets/manifest.controlled-v1.json \
  --strategy path-order \
  --circom-bin /Users/miiz/.cargo/bin/circom \
  --tool-timeout-seconds 30 \
  --output <temporary-directory>
```

manifest SHA-256은
`ec27dc5f088d85ae63e4f5a8397a4d3e9ad01c390af24498d1fc56c47a0931e8`이다.
계약 파일 SHA-256은
`d954de5fe6d8adbeb010f307119b9b3a0207d80b900ed9365d53a16a0f293f9a`다.
JSON parsing, 모든 로컬 참조의 존재, source/wrapper SHA-256, Git blob SHA-1,
manifest와 계약의 variant 대응을 별도로 검산했다.

## 제외한 사례

| 사례 | 제외 이유 |
|---|---|
| Reclaim Add32Bits, XorWords, RotateLeft32Bits | dev3 개발 세트에서 이미 사용한 원인이라 독립 평가 누수를 만든다. 기존 후보 거부 판정을 안전성으로 일반화하지 않는다. |
| iden3 MiMCSponge local fixture | zkbugs 설명 자체가 역사적 원본이 Circom 2에서 재현되지 않아 newer source를 수정한 fixture라고 밝힌다. exact original/fixed pair가 아니다. |
| 나머지 로컬 zkbugs Circom 사례 | v1 범위 안에서 완전한 고정 취약·수정 source closure를 확보하고 검토하지 않았다. 결함의 유효성이나 안전성에 대한 제외 판정이 아니다. |

## 남은 제한

- original project caller의 도달성과 영향은 확인하지 않았다.
- 이 한 쌍은 pipeline의 통제 회귀에는 사용할 수 있지만 전략 성능을 일반화하기에는
  작다.
- 탐색 예산, 전략·seed 반복 수, hardware와 사후 검토 절차를 실행 전에 별도로
  동결해야 한다.
- 실제 비교에는 이 원인과 겹치지 않는 추가 held-out 쌍이 필요하다. 결과를 본 뒤
  이 set으로 랭킹을 조정하면 독립 평가로 사용할 수 없다.
- 현재 발견 건수와 최초 발견 시간은 모두 미측정이다. 임의의 0초나 0건 성과를
  부여하지 않는다.
