# RotateLeft32Bits fixture constraint-fidelity review

검토 실행일: 2026-09-17
대상 파일럿: `dev3-ranking-pilot-2026-09-15`

## 질문과 판정

질문은 dev3에서 실제 실행한 `RotateLeft32Bits(3)` fixture가 확보한 수정 전 원본 component의 제약을 보존하는가이다.

**판정: 대응 범위에서 제약 보존 확인.** dev3의 보존 snapshot과 고정 원본 revision `ef9f5a5ad899d852740a26b30eabe5765673c71f`을 정확히 같은 wrapper로 Circom 2.2.3, `--O0 --prime bn128`에서 컴파일했다. 양쪽 모두 wire 5개와 제약 2개를 생성했고, R1CS와 `.sym` 파일이 각각 바이트 단위로 동일했다. 신호 이름을 대응한 뒤 해석한 두 유한체 다항식도 같았다.

이 판정은 `RotateLeft32Bits(3)` component의 제약계 충실도에 한정된다. 기존 RotateLeft 후보의 유효성, 32-bit 입력 전제 충족, 프로젝트 caller에서의 도달성, 감사 당시 전체 snapshot과의 동일성은 확인하지 않았다.

## 실제 dev3 fixture

실행 대상을 현재 외부 checkout에서 다시 고르지 않고 다음 보존 사슬로 확정했다.

| 항목 | 확인값과 근거 |
|---|---|
| target | [dev10 manifest](../../datasets/manifest.dev10.json)이 `RotateLeft32Bits`, 인자 `3`, `bn128`, compile args 없음, direct mode와 project revision `ef9f5a…`을 기록한다. 준비 뒤 ID는 `sha256:76b7b3d1543e77a11a0d9652e29b1547a6b3783de118ac40d4c76702a5805616`이다. [path-order plan](../../runs/dev10-plans/path-order.json) |
| 실행 snapshot | [prepared-target.json](../../runs/dev10-preparation/prepare-e11d82dd-e508-4b69-ab93-38dbed5345f8/targets/0002/prepared-target.json)과 그 아래 `sources/`. 파일럿 집계가 기록한 공통 prepared SHA-256은 `001056ea35a687233e520624f60f439f99a84600f83da64f697d0bb0f563b952`이다. |
| wrapper | `sources/circuit.circom`, SHA-256 `3c3363ed16fba47f0020ce7be9034af34c26fd4752273d7d5803163d10084fad` |
| fixture source | `sources/generics.circom`, SHA-256 `cdd4afc861b5b07de22aa90fe81f0d9142882964586e8531185ca3422c745bae` |
| 실제 실행 연결 | [대표 outcome](../../runs/dev3-ranking-pilot-2026-09-15/rep-01-seed-2026091501/path-order/executions/execution-d825de18-7f45-4afc-8a35-a76e952cf867/outcome.json)이 위 snapshot 경로를 실행했다. [파일럿 집계](../../experiments/dev3-ranking-pilot-2026-09-15.json)의 integrity 절은 49개 outcome이 같은 prepared SHA와 zkFuzz binary SHA `ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd`를 썼고 모든 타깃이 시작됐다고 기록한다. |

따라서 비교 대상 fixture는 당시 실행 snapshot이다. 현재 `.external` 아래 동명 파일의 현재 상태를 실행 소스로 간주하지 않았다.

## 비교 원본과 수정본의 출처

고정된 zkbugs 메타데이터는 프로젝트 revision을 `ef9f5a5ad899d852740a26b30eabe5765673c71f`, fix revision을 `e5e756375fc1fc8dc48667b00cdf38c79a0fdf50`로 기록한다. 보존한 [fix commit 응답](fix-commit.json)으로 `e5e756…`이 `ef9f5a…`의 직접 자식이고 `circuits/generics.circom`을 실제로 변경했음을 확인했다. 따라서 commit 명칭만으로 수정 전 원본을 정하지 않았다.

비교한 원본 `circuits/generics.circom`의 Git blob은 `46ef6207acbd284271f27be9ccd7798e7f26603c`, 파일 SHA-256은 `4dca4517b1804c8d3a6c9fa0699bb31633a117ca1f0e6df7a45d352beb94d366`이다. fixture의 template 본문은 주석과 공백을 제외하면 이 원본과 같고, 수정본과는 다르다. 수정본 source blob은 `6ba242c7a21ab49f759c6eac8035bc5a5df41342`이다.

감사 보고서는 프로젝트 commit hash를 적지 않았으므로 `ef9f5a…`이 감사 당시 전체 snapshot과 정확히 같다는 점은 미확인이다. 여기서 `ef9f5a…`은 zkbugs가 고정했고 실제 fix의 부모로 확인된 비교 원본이다.

## 입력 전제와 신호 대응

| 원본 | fixture | 변환 또는 추가 조건 |
|---|---|---|
| template parameter `L=3` | `L=3` | 없음 |
| `main.in` | `main.in` | 없음 |
| `main.out` | `main.out` | 없음 |
| `main.part1` | `main.part1` | 없음 |
| `main.part2` | `main.part2` | 없음 |

비교에는 dev3 wrapper의 정확한 바이트를 양쪽에 공통으로 사용했다. `component main {public [in]} = RotateLeft32Bits(3);`은 `in`을 public input으로 표시하지만 범위 제약을 추가하지 않는다.

수정 전 원본의 주석과 감사 finding 1은 `in`이 이미 제약된 unsigned 32-bit 값이어야 한다고 전제한다. 원본 component와 dev3 wrapper 모두 이 전제를 강제하지 않으므로 caller 책임이다. 아래 두 제약의 유한체 식이 같은지 판단하는 데 범위 전제는 필요하지 않지만, bit rotation이라는 계산 의미와 후보 유효성을 판단할 때는 필요하다.

## 원본과 fixture의 제약 대응

| 종류 | 수정 전 원본 | dev3 fixture | 비교 결과 | 필요한 입력 전제 |
|---|---|---|---|---|
| witness 계산 | `circuits/generics.circom:42` — `part1 <-- (in << 3) & 0xFFFFFFFF` | `generics.circom:11` | 같은 witness 계산. R1CS 제약은 생성하지 않음 | 의도한 bit 의미에는 32-bit `in` 필요 |
| witness 계산 | `circuits/generics.circom:43` — `part2 <-- in >> 29` | `generics.circom:12` | 같은 witness 계산. R1CS 제약은 생성하지 않음 | 의도한 bit 의미에는 32-bit `in` 필요 |
| 제약 0 | `circuits/generics.circom:44` — `out - part1 - part2 = 0` | `generics.circom:13` | 동일한 유한체 다항식 | 대수적 동일성에는 없음 |
| 제약 1 | `circuits/generics.circom:45` — `part1 / 2^3 + part2 * 2^29 - in = 0` | `generics.circom:14` | 동일한 유한체 다항식 | 대수적 동일성에는 없음 |

컴파일 결과는 다음과 같다.

| 비교값 | fixture | 수정 전 원본 |
|---|---:|---:|
| wires / public outputs / public inputs / private inputs / labels | `5 / 1 / 1 / 0 / 5` | `5 / 1 / 1 / 0 / 5` |
| constraints | `2` | `2` |
| R1CS SHA-256 | `ca66ddb8e7daaa7499b3764cb41973507b4d80177f0b06918b4a7a3a75f4a42a` | 동일 |
| `.sym` SHA-256 | `f9bf7855ea98a8a28be5b8695b49104d2519856daf00fb3fb0eda5463ad554f3` | 동일 |

제약 수만 비교한 것이 아니다. [구조화 결과](comparison.json)에 신호 대응 뒤 정규화한 두 다항식을 보존했고, R1CS와 `.sym`의 실제 바이트 동일성도 `cmp`로 다시 확인했다.

## 실제 실행한 검사와 정적 검토

실제로 실행한 검사는 다음과 같다.

- [비교 스크립트](compare_constraints.py)로 고정 해시를 확인하고 별도 [component-check](component-check/) 아래에 fixture와 원본 복사본을 만들었다.
- 같은 dev3 wrapper, Circom 2.2.3, `--O0 --prime bn128`로 양쪽을 한 번씩 컴파일했다. fixture 컴파일은 약 0.017초, 원본 컴파일은 약 0.006초였다.
- R1CS header, 신호 매핑, 각 유한체 제약을 해석해 비교하고 R1CS 및 `.sym` 바이트를 독립적으로 `cmp`했다.

정적으로만 확인한 부분은 `e5e756…`의 source diff, 감사 문서의 입력 전제, upstream test의 template 인자이다. 수정본은 `part1` witness 계산을 바꾸고 `part2`에 `<==` 제약을 추가하며 재구성 식의 항을 바꾼다. 수정 효과나 감사 client가 설명한 bit-array 변경과의 동등성은 이번 범위에서 평가하지 않았다. 보존한 upstream test는 `L`을 16, 12, 8, 7로 인스턴스화하며 dev3의 `L=3`은 포함하지 않는다.

RotateLeft 반례 JSON이나 witness 값은 읽거나 평가하지 않았고 새 witness도 생성하지 않았다. `comparison.json`의 `candidate_witness_files_read`는 빈 배열이다. 원본 프로젝트 entrypoint와 caller 도달성도 검사하지 않았다.

## 평가에서의 의미와 남은 불확실성

dev3 RotateLeft 타깃은 **고정한 수정 전 `RotateLeft32Bits(3)` component의 제약계를 대상으로 한 탐색**에는 사용할 수 있다. fixture에서 후보가 나왔다는 사실만으로 원본 component의 유효한 결함이 되지는 않는다. 주 지표에 포함하려면 별도 사후 검증에서 후보가 이 두 원본 제약 전체를 만족하고, 명시된 32-bit 입력 전제 아래 검증할 속성을 위반하는지 확인해야 한다.

이번 결과가 확인하지 않은 사항은 다음과 같다.

- 보존된 RotateLeft 후보의 유효성 또는 고유 결함 여부
- 프로젝트 caller가 `L=3`을 사용하거나 해당 입력에 도달하는지
- caller가 32-bit 입력 전제를 실제로 강제하는지
- 고정 원본과 감사 당시 전체 프로젝트 snapshot의 정확한 동일성
- 수정본의 안전성, 다른 파라미터의 충실도, 랭킹 성능

그러므로 이 결과는 RotateLeft 실행 대상의 한 가지 충실도 위험을 제거하지만, 기존 backend 후보 수를 원본 component 결함 수나 프로젝트 결함 수로 바꾸지는 않는다.
