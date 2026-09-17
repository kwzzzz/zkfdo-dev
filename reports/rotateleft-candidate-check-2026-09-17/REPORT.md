# RotateLeft32Bits 기존 후보의 원본 component 검증 — 2026-09-17

## 결론

**선정한 정확한 후보는 고정 원본 component의 제약 두 개를 모두 만족하지만, 입력이 32비트 범위 밖이어서 유효한 원본 component 결함으로 집계할 수 없다.** 판정은 `input_precondition_failed`다.

- 원본 component 고유 결함 집계: **0건**
- 프로젝트 문맥 확인 결함: **0건**
- 검사 상태: 성공
- 원본 제약: 2개 모두 만족
- 입력 전제 `0 <= in < 2^32`: 위반
- 정상 32비트 회전 속성: 입력 전제 밖이므로 이 후보에 적용하지 않음

이 결과는 고정한 후보 한 건에만 적용한다. 다른 RotateLeft 후보의 유효성, 원본 component의 안전성, 프로젝트 도달성, 랭킹 성능을 판정하지 않는다.

## 후보 선정

후보 값을 읽기 전에 dev3의 RotateLeft 후보 21건을 실행 시작 시각, run ID, 보존 경로 순으로 정렬했다. 가장 이른 후보 한 건을 고정한 뒤 그 값만 읽었다. 전략·랭킹 점수·성공 가능성은 선택에 사용하지 않았다.

| 항목 | 값 |
|---|---|
| target | `sha256:76b7b3d1543e77a11a0d9652e29b1547a6b3783de118ac40d4c76702a5805616` |
| strategy | `random` |
| run 시작 | `2026-09-15T07:10:56.404240Z` |
| run ID | `4f896cbb-0aa5-475a-b485-6b2be66fcbbe` |
| seed / generation | `2026091502` / `44` |
| 후보 SHA-256 | `8effd6c717f7ac463f956d9581cf0146eff4a0ba1b01e60bf23327d405cb93e4` |

전체 목록과 선택 규칙은 [selection.json](selection.json)에 보존했다. 선택 단계에서는 후보 파일의 해시만 확인했고 assignment는 파싱하지 않았다.

## 출처와 실행 연결

완료된 [fixture fidelity 검토](../rotateleft-fixture-fidelity-2026-09-15/REPORT.md)를 재사용했다. 당시 dev3 prepared snapshot의 `RotateLeft32Bits(3)` fixture와 고정 원본 revision `ef9f5a5ad899d852740a26b30eabe5765673c71f`은 다음 범위에서 일치한다.

- template 인자 `L=3`, field `bn128`, compile args 없음
- wrapper와 입력·출력·내부 신호 대응
- Circom 2.2.3, `--O0 --prime bn128` 컴파일 결과
- wire 5개, 제약 2개
- R1CS와 `.sym` 바이트 및 신호 이름 기준 유한체 다항식

선정 후보는 dev3의 두 번째 반복에서 보존됐고, 해당 실행의 target은 위 prepared snapshot을 가리킨다. 실행은 strategy 전체 10초, target당 3초 설정에서 수행됐다. 이 RotateLeft run은 scheduler 시작 후 약 `0.7854초`에 반환됐고 runner wall time은 약 `0.7054초`였다. 후보 내부 기록 시간 `691.032333ms`는 정확한 최초 발견 timestamp가 아니다.

## 입력·신호·출력 대응

`main.L=3`은 template 인자 확인용 후보 메타데이터다. 원본 R1CS의 네 신호에는 다음 값을 그대로 대응했다. 값 변환, 누락 wire, 기본값, 추가 제약은 없다.

| 신호 | 보존값 | 해석 |
|---|---:|---|
| `main.in` | `p - 4` | BN254 field 값, 32비트 unsigned 범위 밖 |
| `main.out` | `p - 32` | 실제 출력 |
| `main.part1` | `p - 32` | 내부 witness |
| `main.part2` | `0` | 내부 witness |

여기서 `p = 21888242871839275222246405745257275088548364400416034343698204186575808495617`이다.

원본 소스와 감사 finding의 rotation 의미는 `in`이 이미 unsigned 32-bit 값이라는 전제를 둔다. 원본 component와 dev3 wrapper는 이 범위 전제를 강제하지 않는다. 따라서 `in=p-4`인 이번 후보에는 정상 속성

```text
out = ((in << 3) & 0xffffffff) | (in >> 29)
```

을 적용해 유효한 32비트 회전 결함으로 판정할 수 없다. 후보에 저장된 expected output은 보존했지만, 입력 전제 밖에서 계산된 값이므로 합의한 component 지표의 속성 판정 근거로 사용하지 않았다.

## 원본 제약 검사

고정 원본 소스와 정확한 dev3 wrapper를 새 디렉터리에 복사하여 Circom 2.2.3, `--O0 --prime bn128`으로 컴파일했다. 새 R1CS와 `.sym`은 이전 fidelity 검토의 원본 컴파일 결과와 바이트 단위로 같다.

각 compiled polynomial을 원본 두 식에 신호 이름 기준으로 대조하고 후보를 대입했다.

| 원본 제약 | 잔여값 mod p | 판정 |
|---|---:|---|
| `out - part1 - part2 = 0` | `0` | 만족 |
| `part1 / 2^3 + part2 * 2^29 - in = 0` | `0` | 만족 |

즉 후보는 원본 제약계 안의 유효한 assignment다. 그러나 합의한 주 지표는 **입력 전제 충족 + 원본 전체 제약 만족 + 명시한 속성 위반**을 모두 요구한다. 첫 조건이 실패했으므로 집계값은 0이다.

전체 값은 [component-check.json](component-check.json), 검증 코드는 [check_rotateleft.py](check_rotateleft.py)에 기록했다. 스크립트의 집계 조건은 `input_precondition_satisfied and candidate_satisfies_original_component and property_violated`를 명시적으로 사용한다.

## 실제 실행과 정적 검토

실제로 수행한 작업:

- 후보 값을 읽기 전 21건 inventory와 결정적 선택 고정
- 후보·outcome·prepared target·fidelity 자료의 경로와 해시 연결
- 고정 원본 component 재컴파일
- 네 R1CS 신호의 정확한 값 대응
- 두 source polynomial과 compiled constraint 대조
- 두 제약의 유한체 잔여값 계산
- 새 컴파일 결과와 fidelity 검토 결과의 바이트 비교

정적으로 판단한 부분:

- source와 감사 finding이 두는 unsigned 32-bit 입력 전제
- 이 전제가 component와 dev3 wrapper 안에서 강제되지 않는다는 점
- 전제 밖 후보에 정상 32비트 rotation 속성을 적용하지 않는 집계 해석

새 퍼징, witness 생성, 다른 후보 검사, 프로젝트 caller 및 전체 proof 검사는 하지 않았다.

## 검증 비용과 남은 불확실성

자동 component 검사는 약 `0.0304초`였으며, 원본 컴파일은 약 `0.0147초`였다. 이는 과거 탐색 예산과 분리된 사후 검증 비용이다. 사람 개입형 전체 구간에는 후보 목록 작성, 코드 작성, 실행 및 문서화가 포함되므로 활성 수작업 시간으로 해석하지 않는다.

남은 미확인 사항:

- 나머지 RotateLeft 후보 20건 중 32비트 입력 전제를 만족하는 후보의 존재
- 그런 후보가 원본 제약과 정상 rotation 속성을 함께 위반하는지 여부
- 프로젝트 caller가 입력을 32비트로 제한하고 `L=3`에 도달하는지 여부
- 감사 당시 전체 snapshot의 정확한 revision
- dev3의 119개 backend 후보 전체 유효성 및 랭킹 성능

이번 결과는 fixture와 원본의 제약이 같더라도 **평가 domain을 wrapper가 강제하지 않으면 backend 후보가 주 지표에서 제외될 수 있다**는 구체적인 사례다.
