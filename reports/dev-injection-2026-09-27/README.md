# 개발용 주입 시험 (T4c)

날짜: 2026-09-27. **상태: 완료.** B 전용 제외 스냅샷에 이미 있는 프로젝트만 썼다. zkFuzz는 실행하지 않았다.

| 프로젝트 | 고정 revision | 의존성 |
|---|---|---|
| `inference-labs-inc/subnet-2-circom` | `d310309c141d36504b3486cebd96ed70ef3a4fdf` | 없음 |
| `iden3/circomlib` | `cff5ab6288b55ef23602221694a6a38a0239dcc0` (v3에서 쓴 커밋) | 없음 |
| `0xbok/circom-bigint` | `436665bf01728ae8c581fdb39e8428cb6b835c37` | `yarn.lock`이 고정한 circomlib 2.0.2 |

circom-bigint는 회로가 쓰는 circomlib 하나만 설치했다. npm 레지스트리의 tarball을 받아 `yarn.lock`의 sha512 integrity와 일치함을 확인한 뒤 `node_modules/circomlib`에 풀었다(SHA-256 `0322020b…`). 설치 스크립트는 실행하지 않았다. Rarimo에도 O4 위치를 찾으려고 circomlib 2.0.5를 같은 방식으로 풀었지만(lockfile이 없어 `^2.0.5`를 만족하는 유일한 릴리스), 도달하는 탐색이 불완전해 사례로 쓰지 않았다(발견 5).

## 도구

- `zkfDO experiment inject --plan PLAN.json`: 값 없는 주입 계획 하나로 clean·mutant·교란 쌍둥이 소스 트리, 고정한 컴파일러와 witness 생성기, 같은 입력의 두 assignment, 신호 이름 기반 projection, 주입 관련 원본 제약, relation-exclusion 증명서, 도달성 증거, review-spec·request를 만든다. 계획에 entrypoint가 없으면 대상 소스의 closure만 쓰고 production 도달성을 `unknown`으로 기록한다. 적격 판정은 하지 않는다. 판정은 `zkfDO experiment review`가 모두 다시 계산한다.
- `zkfdo-relation-verifier`: `operator-proof` 방식의 고정 외부 verifier(unique-propagation). 계약 입력과 속성 신호를 고정하고, 원본 제약에서 선형으로 결정되는 wire와, 서로 다른 2의 거듭제곱으로 가중된 불리언 비트 분해를 유일한 이진 표현으로 정한다. 모든 wire가 정해진 주입 관련 제약이 깨지거나, 알려진 값을 그 비트들로 표현할 수 없으면 원본 확장이 없다는 증명이다. 규칙의 건전성 근거는 [설계 초안 4.1절](../../docs/injection_evaluation_design.md)에 있다.
- 원시 입력, witness, assignment, 컴파일 산출물은 ignored `runs/dev-injection-2026-09-27/`에만 있다. 이 폴더에는 계획, 값 없는 manifest·증명서·도달성 증거, spec·request, qualification 보고서와 index만 둔다. 원시 입력값과 6자리 이상 witness 값이 이 폴더의 어떤 파일에도 없음을 확인했다.

## 결과

| 주입 | 연산자 | 대상 | 교란 쌍둥이 | relation exclusion | 주입 관련 원본 제약 | 판정 |
|---|---|---|---|---|---:|---|
| [inference-o2-num2bits41](inference-o2-num2bits41/) | O2 비트 불리언 제약 제거 | `clampTensor.circom::Num2Bits(41)` | 비트 합을 유지한 채 bit 0을 2로 | fully-fixed | 41 | qualified |
| [inference-o1-where](inference-o1-where/) | O1 `<==` → `<--` | `where.circom::Where()` | 선택된 값에 1을 더해 출력 | unique-propagation | 1 | qualified |
| [inference-o5-iszero](inference-o5-iszero/) | O5 출력-조건 제약 제거 | `integerDivision.circom::IsZero()` | 역원 힌트를 0으로 계산 | fully-fixed | 1 | qualified |
| [bigint-o3-split](bigint-o3-split/) | O3 보조 신호 범위 검사 제거 | `bigint.circom::Split(64, 64)` | 상위 limb의 1을 하위 limb에 `2^64`로 옮김 | unique-propagation | 65 | unresolved |
| [circomlib-o4-num2bits-strict](circomlib-o4-num2bits-strict/) | O4 엄밀한 분해 → 필드 크기 분해 | `bitify.circom::Num2Bits_strict()` | `in + p`의 비트 | unique-propagation | 263 | unresolved |

- inference의 세 사례는 공통 기준 4개와 qualification 기준 9개가 모두 `satisfied`다. production entrypoint `src/circuit.circom`의 `IncentiveMechansim(256, 40)`에서 대상 인스턴스까지의 부모 사슬을 엔진이 다시 탐색해 확인했다.
- O3·O4는 `production_reachability`를 뺀 12개 기준이 모두 `satisfied`다. 두 대상에 완전한 탐색으로 도달하는 entrypoint가 개발 프로젝트에 없어(circom-bigint의 `Split`은 어디서도 인스턴스화되지 않고, circomlib에서 `Num2Bits_strict`에 도달하는 테스트 main 4개는 모두 탐색이 불완전하다) 도달성을 `unknown`으로 두었다. 연산자의 교란 규칙과 relation-exclusion 증명은 동작함을 확인한 것이고, 그대로 B의 정답 결함이 되는 것은 아니다.
- 엔진은 모든 사례에서 세 변형을 임시 폴더에서 다시 컴파일해 R1CS·SYM 해시를, 두 witness 생성기를 다시 실행해 witness·assignment 해시를 재현했다.
- 다섯 사례 모두 속성은 원본 회로 출력과 비교하지 않는 명세(비트성, 선택기 결과, 0 판정, 표준 limb 분해, 표준 이진 표현)다.
- 모든 사례를 마지막에 하나의 보존 실행 파일(`runs/dev-injection-2026-09-27/bin/`, `zkfDO` SHA-256 `7ff5c85c…`, `zkfdo-relation-verifier` `e8d8b246…`)로 빈 작업 폴더에서 다시 만들었다. O2 사례는 그 전에도 처음부터 두 번 만들어 핵심 산출물 7개가 바이트 단위로 같음을 확인했다.
- 음성 대조: 합성 통합 시험(`tests/injection_builder_test.rs`, circom·node 필요)에서 쌍둥이가 같은 값을 다른 식으로만 계산하면 도구가 "주입 관련 원본 제약이 깨지지 않는다"며 거부한다.

## 발견 사항 (B2 입력)

1. **O1은 대부분 fully-fixed로 증명할 수 없다.** `<==`로 정의한 신호는 보통 내부 신호를 거친다(`Where`의 `out = temp_signal_1 + temp_signal_2`). unique-propagation이 이 경우를 다룬다.
2. **O3는 증명자가 고르는 보조 신호의 범위 검사에만 맞는다.** 입력 자체의 범위 검사를 없애면 결함본이 원본이 거부하는 입력을 받아들이는 형태가 되어, 같은 입력의 원본 witness가 존재해야 하는 현재 qualification으로 표현할 수 없다. 출력이 없는 검사 템플릿(예: `CheckCarryToZero`)도 같은 이유로 맞지 않는다. 설계 초안의 O3 적용 조건을 이렇게 좁혔다.
3. **코퍼스 inspection과 target ID의 라이브러리 경로(보완함).** `experiment prepare`의 inspection이 include를 그 파일의 폴더와 프로젝트 루트에서만 찾아, `include "circomlib/..."`처럼 `-l node_modules`에 기대는 프로젝트(개발 프로젝트 중 zk-email, Self, Rarimo)가 prepare에서 제외되고 있었다. 이제 `compile_args`의 `-l` 경로를 그 뒤에 차례로 찾는다. 원래 해석되던 include는 같은 파일로 해석되므로 기존 target ID는 바뀌지 않는다.
4. **B의 backend 판정에는 명세 속성이 필요하다.** zkFuzz 후보에는 같은 입력의 원본 기준 출력이 없으므로 "원본 출력과 다르다"는 속성을 backend에서 판정할 수 없다. B에서 대상과 위치를 무작위로 고르면 위치마다 명세 predicate를 미리 써야 한다. 그 작업량과 사전 고정 방식, 또는 엔진이 후보 입력으로 고정 원본 witness 생성기를 다시 실행하는 확장을 B2에서 정해야 한다.
5. **탐색이 circomlib Poseidon 등을 펼치지 못한다(B 실행 가능성 위험).** Rarimo `voteSMT`의 entrypoint 두 개는 O4 대상(프로젝트 자체 `SMTVerifier`)에 도달하지만 탐색이 미지원 구문 51·53건으로 불완전하다. 거의 모두 `poseidon.circom` 안의 컴파일 타임 변수 배열, 함수로 계산하는 파라미터·반복 경계다. circomlib의 테스트 main에서도 MiMC·Poseidon·escalarmul 때문에 같은 일이 생긴다. 지금 기준(탐색이 불완전하면 제외)으로는 B 후보 다수가 탈락할 수 있다. 주입과 순위 대상은 프로젝트 자체 템플릿뿐이므로, 라이브러리 템플릿 내부는 펼치지 않는 탐색 방식이나 파서 확장을 T6·B2 전에 정해야 한다.
6. **엔진 수정:** predicate worker가 predicate를 import하면서 Git 추적 폴더에 `__pycache__`를 쓰고 있었다. Python을 `-B`로 실행하도록 고쳤다.
7. **관찰:** inference의 `IntDiv`는 `out <-- quot;` 뒤에 `out`을 묶는 제약이 없는 것으로 보이고, circom-bigint의 `Split`·`SplitThree`는 어디서도 쓰이지 않는다. Self의 `smt.circom`은 해시 출력을 `Num2Bits(254)`로 분해한다. 모두 검토하지 않은 관찰이며 주입 대상 선택에만 참고했다.

## 다시 만드는 방법

```sh
B=runs/dev-injection-2026-09-27/bin
D=reports/dev-injection-2026-09-27/<주입>
$B/zkfDO experiment inject --plan $D/plan.json
M=$D/engine-source-manifest.json
$PWD/$B/zkfDO experiment review --request $D/request.json --output $D/qualification \
  --source-revision "worktree-engine-manifest:$(shasum -a 256 $M | cut -d' ' -f1)" \
  --engine-source-manifest $M
```

작업 폴더(`runs/dev-injection-2026-09-27/<주입>`)와 `$D`의 산출물은 비어 있어야 한다(계획 파일 제외). 공통 입력은 `runs/dev-injection-2026-09-27/inputs/`에 있다. 보고서에 실행 파일 경로가 기록되므로 도구는 `runs/` 아래에 보존한 실행 파일로 실행한다.

## B2 준비로 넘기는 일

- 연산자별 적용 위치 자동 탐색과 고정 seed 표집(5절), 탈락 위치를 값 없는 기록으로 남기는 기능. 이번에는 위치를 계획 파일에 직접 적었다.
- 발견 4(backend 속성)와 발견 5(라이브러리 내부 탐색)의 결정
- production entrypoint 지정 근거를 프로젝트 provenance에 묶는 절차(엔진은 선택한 entrypoint로부터의 도달만 확인한다)
