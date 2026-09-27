# 개발용 주입 시험 (T4c) — 중간 기록

날짜: 2026-09-27. **상태: 진행 중.** B 전용 제외 스냅샷에 이미 있는 프로젝트만 썼다. 이번 기록의 대상은 T1 제외 목록의 개발 프로젝트 `inference-labs-inc/subnet-2-circom`(커밋 `d310309c141d36504b3486cebd96ed70ef3a4fdf`)이다. zkFuzz는 실행하지 않았다.

## 도구

- `zkfDO experiment inject --plan PLAN.json`: 값 없는 주입 계획 하나로 clean·mutant·교란 쌍둥이 소스 트리, 고정한 컴파일러와 witness 생성기, 같은 입력의 두 assignment, 신호 이름 기반 projection, 주입 관련 원본 제약, relation-exclusion 증명서, 도달성 증거, review-spec·request를 만든다. 적격 판정은 하지 않는다. 판정은 `zkfDO experiment review`가 모두 다시 계산한다.
- `zkfdo-relation-verifier`: `operator-proof` 방식의 고정 외부 verifier다. 계약 입력과 속성 신호를 고정하고, 미지수가 하나뿐이며 선형이고 계수가 0이 아닌 원본 제약을 반복해서 풀어 값이 강제되는 wire를 정한다. 이렇게 정한 값은 고정 신호가 같은 모든 원본 assignment에서 같으므로, 모든 wire가 정해진 주입 관련 제약이 깨지면 그런 원본 assignment가 없다는 증명이 된다.
- 원시 입력, witness, assignment, 컴파일 산출물은 ignored `runs/dev-injection-2026-09-27/`에만 있다. 이 폴더에는 계획, 값 없는 manifest·증명서·도달성 증거, spec·request, qualification 보고서와 index만 둔다.

## 결과

| 주입 | 연산자 | 대상 | 교란 쌍둥이 | relation exclusion | 주입 관련 원본 제약 | 판정 |
|---|---|---|---|---|---:|---|
| [inference-o2-num2bits41](inference-o2-num2bits41/) | O2 비트 불리언 제약 제거 | `clampTensor.circom::Num2Bits(41)` | 비트 합을 유지한 채 bit 0을 2로 만든다 | fully-fixed | 41 | qualified |
| [inference-o1-where](inference-o1-where/) | O1 `<==` → `<--` | `where.circom::Where()` | 선택된 값에 1을 더해 출력한다 | unique-propagation | 1 | qualified |
| [inference-o5-iszero](inference-o5-iszero/) | O5 출력-조건 제약 제거 | `integerDivision.circom::IsZero()` | 역원 힌트를 0으로 계산해 0이 아닌 입력에 출력 1을 낸다 | fully-fixed | 1 | qualified |

세 사례 모두 공통 기준 4개와 qualification 기준 9개가 전부 `satisfied`다. 엔진은 세 변형을 임시 폴더에서 다시 컴파일해 R1CS·SYM 해시를 재현했고, 두 witness 생성기를 다시 실행해 witness·assignment 해시를 재현했다. production entrypoint `src/circuit.circom`의 `IncentiveMechansim(256, 40)`에서 대상 인스턴스까지의 부모 사슬도 다시 탐색해 확인했다. O2 사례는 작업 폴더를 지우고 처음부터 다시 만들어 핵심 산출물 7개가 바이트 단위로 같음을 확인했다.

세 사례의 속성은 비트성, 선택기 결과, 0 판정처럼 입력과 출력만으로 판정하는 명세다. 원본 회로의 출력과 비교하지 않으므로, 나중에 zkFuzz 후보를 backend로 검토할 때도 같은 predicate를 쓸 수 있다.

**중간 결과다.** 세 사례는 도구를 고치는 도중에 만들어 서로 다른 중간 실행 파일로 검토했다. T4c를 끝낼 때 하나의 보존 실행 파일로 모든 사례를 새 폴더에 다시 만든다.

## 발견 사항 (B2 입력)

1. **O1은 대부분 fully-fixed로 증명할 수 없다.** `<==`로 정의한 신호는 보통 내부 신호를 거친다. 예를 들어 `Where`의 `out`은 `temp_signal_1 + temp_signal_2`로 정의되므로, 깨지는 원본 제약의 wire가 모두 계약 신호일 수 없다. unique-propagation이 이 경우를 다룬다. 비트 분해처럼 값이 비선형 제약으로만 정해지는 경우에는 이 방식으로도 증명되지 않으며, 그런 위치는 탈락으로 기록해야 한다.
2. **O3는 증명자가 고르는 보조 신호의 범위 검사에만 맞는다.** 입력 자체의 범위 검사를 없애면 결함본이 원본이 거부하는 입력을 받아들이게 되는데, 현재 qualification은 같은 입력에서 원본 witness가 존재해야 하므로 이 형태를 표현할 수 없다. `<--`로 계산한 몫·나머지 같은 보조 신호의 범위 검사를 없애는 형태(BigMod, FpMul 유형)만 같은 입력에서 다른 출력을 만든다. B2에서 O3의 적용 조건을 이렇게 좁히거나 설계를 넓혀야 한다.
3. **코퍼스 inspection과 target ID가 라이브러리 경로를 지원하지 않는다.** `experiment prepare`의 entrypoint inspection은 include를 그 파일의 폴더와 프로젝트 루트에서만 찾는다. `include "circomlib/..."`처럼 `-l node_modules`에 기대는 프로젝트(개발 프로젝트 중 zk-email, Self, Rarimo)는 prepare에서 제외되고, 주입 도구도 target ID를 계산하지 못한다. T6a는 탐색(`targets`)에만 라이브러리 경로를 넣었다. B2·T3 전에 보완해야 하며, O3·O4 개발 주입도 이것 때문에 아직 막혀 있다.
4. **B의 backend 판정에는 명세 속성이 필요하다.** zkFuzz 후보에는 같은 입력의 원본 기준 출력이 없으므로, "원본 출력과 다르다" 같은 속성은 backend에서 판정할 수 없다. B에서 대상과 위치를 무작위로 고르면 위치마다 명세 predicate를 미리 써야 하는데, 그 작업량과 사전 고정 방식을 B2에서 정해야 한다. 대안은 엔진이 후보 입력으로 고정된 원본 witness 생성기를 다시 실행해 기준 출력을 얻는 확장이다.
5. **엔진 수정:** predicate worker가 predicate를 import하면서 Git 추적 폴더에 `__pycache__`를 쓰고 있었다. Python을 `-B`로 실행하도록 고쳤다.
6. **관찰:** inference의 `IntDiv`는 `out <-- quot;` 뒤에 `out`을 묶는 제약이 없는 것으로 보인다. 검토하지 않은 관찰이며, 주입 대상에서 제외했다.

## 다시 만드는 방법

```sh
D=reports/dev-injection-2026-09-27/<주입>
zkfDO experiment inject --plan $D/plan.json
M=$D/engine-source-manifest.json
zkfDO experiment review --request $D/request.json --output $D/qualification \
  --source-revision "worktree-engine-manifest:$(shasum -a 256 $M | cut -d' ' -f1)" \
  --engine-source-manifest $M
```

작업 폴더(`runs/dev-injection-2026-09-27/<주입>`)는 비어 있어야 한다. 공통 입력은 `runs/dev-injection-2026-09-27/inputs/`에 있다. 보고서에 실행 파일 경로가 기록되므로, 도구는 `runs/` 아래에 보존한 실행 파일로 실행한다.

## 남은 일

- O3(보조 신호 범위 검사)와 O4(엄밀한 비트 분해) 사례. 발견 3의 라이브러리 경로 지원이 먼저 필요하다.
- 탈락 위치를 값 없는 기록으로 남기는 기능, 연산자별 적용 위치 자동 탐색과 표집
- circom·node가 필요한 도구 통합 시험(`#[ignore]`)
- 하나의 보존 실행 파일로 모든 사례를 다시 만들고, 설계 초안의 연산자 규칙을 갱신
