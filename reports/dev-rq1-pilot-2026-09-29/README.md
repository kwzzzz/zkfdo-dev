# 개발용 RQ1 파일럿: 통째 실행과 분할 실행 (2026-09-29)

**상태: 완료.** 같은 시간 예산에서 zkFuzz를 entrypoint 전체에 한 번 돌리는 것(통째)과, 프로젝트 자체 템플릿 조각을 차례로 돌리는 것(분할)을 알려진 실제 결함으로 비교했다. 두 사례 모두 개발에 이미 쓴 결함이라 **독립 평가가 아니다.** [계획 개정 제안](../../docs/plan_revision_2026-09-27.md)의 P2이며, 정식 평가(RQ1)의 절차를 미리 시험하는 목적이다.

## 설정

설정은 [pilot-config.json](pilot-config.json)에 적었고, 두 사례에 zkFuzz를 돌리기 전에 커밋했다(`d3716eb`).

| 사례 | entrypoint | 전체 크기 | 조각 | 정답 결함 |
|---|---|---:|---:|---|
| inference | `src/circuit.circom` (production entrypoint) | 제약 196,096 | 21 | `Subtract()`, `Clamp(40)` |
| zk-email | `packages/circuits/tests/test-circuits/rsa-test.circom` (zkbugs Original Entrypoint) | 제약 153,137 | 4 | `FpMul(121, 17)` |

- **통째:** zkFuzz를 entrypoint에 600초 동안 한 번 실행한다(기본 설정, seed 고정).
- **분할:** entrypoint에서 도달하는 고유 인스턴스 중 소스가 프로젝트 안에 있는 것만 조각으로 만든다. circomlib 같은 라이브러리 템플릿은 그것을 쓰는 조각 안에서 함께 실행된다. 조각당 30초, 전체 600초이고, 조각은 한 번에 하나씩 차례로 실행한다.
- **순서:** random(block마다 순위 seed), small-first, path-order. risk-only와 cost-aware는 고정된 Circomspect가 inference의 익명 컴포넌트를 분석하지 못해 뺐다.
- **반복:** zkFuzz seed 3개(2026092931~33). 사례와 방식의 조합 8개를 동시에 실행했다(방식마다 zkFuzz 프로세스 1개).
- **판정:** 통째는 600초 안에 zkFuzz가 `NOT SAFE`를 보고하는지, 분할은 정답 템플릿 조각에서 반례가 나오는지(결함 위치 일치)로 본다. 분할 반례는 이번에 따로 검토하지 않았다.
- **실행 방식의 차이:** inference는 zkfDO의 `experiment prepare`·`plan`·`run`을 그대로 썼다. zk-email은 zkfDO 준비 단계가 조각 4개를 모두 제외해서(아래 발견 3), 조각마다 zkFuzz를 직접 호출하는 방식으로 같은 seed와 제한을 적용했다.

## 결과

### inference: 통째로는 못 찾고, 분할하면 두 결함을 매번 찾음

| 방식 | 찾은 결함 | 첫 정답 탐지 시각 | 비고 |
|---|---|---|---|
| 통째 (3회) | 없음 | – | 600초 동안 세대 0도 끝내지 못함 |
| 분할 small-first (3회) | 둘 다 | 1.4~1.6초 (`Subtract`, 2번째 조각) | `Clamp`는 14번째 조각에서 143~146초 |
| 분할 path-order (3회) | 둘 다 | 1.4~1.6초 (`Clamp`, 3번째 조각) | `Subtract`는 20번째 조각에서 199~202초 |
| 분할 random (3회) | 둘 다 | 60초, 198초, 203초 | 순위 seed에 따라 크게 달라짐 |

- 분할 실행은 조각 21개를 모두 203~206초에 끝냈다. 예산 600초의 3분의 1 정도다.
- 두 정답 외에도 조각 8개(`IntDiv` 3종, `CalculatedScoreFraction(40)`, `DistanceFromScore(40)`, `ResponseTimeMetric(40)`, `ResponseTimeNormalized(40)`, `ScoringFunction(40)`)에서 반례가 나왔다. 검토하지 않았고, 호출하는 쪽 맥락이 빠진 조각의 오탐인지, 정답 결함이 호출자로 번진 것인지, 다른 결함인지는 모른다.

### zk-email: 두 방식 모두 못 찾음

| 방식 | `FpMul(121, 17)` 조각 | 통째 실행 진행 |
|---|---|---|
| 통째 (3회) | – | 600초 동안 세대 20·27·26개, 반례 없음 |
| 분할 (9회) | 모든 실행에서 500세대를 30초 안에 끝내고 반례 없음 | – |

- 정답 결함이 있는 조각을 떼어 내 기본 탐색량(500세대)을 다 돌려도 zkFuzz가 찾지 못했다. 이 결함은 규모가 아니라 **zkFuzz의 탐지 범위 한계** 쪽이다. 분할로 해결될 수 있는 종류가 아니다.
- 모든 분할 실행에서 `BigLessThan(121, 17)` 조각이 세대 1에서 반례를 냈다. 정답이 아니며 검토하지 않았다.
- `RSAPad(121, 17)`은 조각이 작은데도(제약 3,183) 30초 안에 세대 0을 끝내지 못했고, `FpPow65537Mod(121, 17)`(제약 145,656)은 30초에 40~70세대를 돌았다. 조각 크기만으로 실행 비용을 예측할 수 없다는 뜻이다.

## 정답 외 반례 검토 (2026-09-30)

분할 실행에서 정답이 아닌 조각이 낸 반례를, zkFuzz가 보고한 종류와 소스의 호출 관계로 분류했다(block 1 small-first 기준, 같은 조각은 모든 실행에서 같은 종류). 반례 값은 이 폴더에 두지 않는다.

| 조각 | zkFuzz 보고 | 분류 | 근거 |
|---|---|---|---|
| inference `IntDiv(40)`·`IntDiv(80)`·`IntDiv(120)` | 출력 `out`이 달라짐 | 진짜 결함 | `out <-- quot` 뒤에 `out`을 묶는 제약이 없다. zkbugs의 `Subtract` 설명에 같은 PR에서 함께 고쳐졌다고 적혀 있다 |
| inference `DistanceFromScore(40)`, `ResponseTimeNormalized(40)`, `ScoringFunction(40)`, `ResponseTimeMetric(40)`, `CalculatedScoreFraction(40)` | `LessThan` 비교 조건 위반 (zkFuzz의 `LessThan` 넘침 검사) | 실제 회로에서도 일어날 수 있는 것으로 보임 (경로별 정밀 검토 전) | entrypoint의 입력에는 `verified`의 불리언 검사 말고는 범위 검사가 없고, 중간값은 `IntDiv`·`Subtract`의 묶이지 않은 신호를 거친다. 따라서 이 조각들의 `LessThan`에는 실제 회로에서도 n비트를 넘는 값이 들어올 수 있다 |
| zk-email `BigLessThan(121, 17)` | `LessThan` 비교 조건 위반 (`lt[16]`) | **맥락 오탐** | `BigLessThan`은 각 조각이 n비트 안에 든다고 가정한다고 문서화돼 있다. 실제 호출자 `RSAVerifier65537`은 `signature`를 `Num2Bits(n)`로, `modulus`를 `RSAPad` 안의 `Num2Bits(n)`로 먼저 검사한다. 떼어 낸 조각에는 이 검사가 없어서 생긴 반례다 |

- inference는 입력 범위 검사가 거의 없는 프로젝트라, 조각 반례가 대부분 실제로도 일어날 수 있는 쪽이었다. 대신 같은 원인이 여러 조각에서 반복해서 보고됐다.
- zk-email은 호출자가 전제 조건을 지키는 프로젝트라, 떼어 낸 조각에서 **실제로는 일어날 수 없는 반례**가 9번의 분할 실행 모두에서 0.5초 만에 나왔다. 호출자의 전제 조건이 조각 실행에서 빠지는 문제가 실제로 생긴다는 첫 사례다.

## 해석

1. **inference는 RQ1의 효과가 실제 결함에서도 나타난다는 첫 신호다.** 같은 600초에서 통째 실행은 세대 하나도 못 끝내고 두 결함을 놓쳤고, 분할 실행은 3분 남짓에 두 결함을 매번 찾았다. zkFuzz 논문의 한계("실행 시간이 대상 크기에 비례")와 SoK의 프로젝트 모드 결과가 개발 사례에서 그대로 재현됐다.
2. **zk-email은 분할이 도울 수 없는 경우를 보여 준다.** 결함 조각을 따로 돌려도 zkFuzz가 찾지 못했으므로, 정식 평가에서도 이런 결함은 "탐지 범위 한계"로 따로 분류해야 한다. SoK 격리 모드에서 zkFuzz가 이 결함을 찾았는지는 R1에서 확인한다.
3. **순서는 이번에는 찾는 시간만 바꿨다.** inference는 21개 조각이 예산 안에 다 돌아서 모든 순서가 두 결함을 결국 찾았다. 첫 탐지까지는 small-first·path-order가 1.5초 안팎, random은 60~203초였다. path-order가 빨랐던 것은 `Clamp`의 파일 경로가 앞쪽이었기 때문이다. 예산이 60초였다면 random은 세 번 중 두 번 아무것도 못 찾았을 것이다. 순위의 효과를 보려면 RQ2처럼 예산을 줄인 조건이 필요하다.

## 발견 사항 (R2 입력)

1. **SoK 프로젝트 모드의 실제 구성:** zkbugs의 `Original Entrypoint`로 보인다. 56건은 프로젝트 저장소 안의 파일 42건, zkbugs 스크립트가 프로젝트의 최상위 템플릿을 main으로 둔 파일 7건, 결함 템플릿 하나만 감싼 파일 7건이다(2026-09-30 정정: 처음에는 경로 이름만 보고 43건·13건으로 잘못 셌다). 계획에서 RQ1의 주 집합을 앞의 두 종류로 바꿨다.
2. **개발 노출 결함 22건 중 이번에 비교할 수 있었던 건 2건이다.**
   - Moonsong, Self: 의존성 패키지가 없어 컴파일 실패
   - Rarimo: 미지원 구문 69건으로 탐색이 결함 조각까지 가지 못함
   - circom-bigint `BigMod`: 결함 템플릿이 entrypoint의 루트 템플릿이라 더 자를 수 없음
   - Banyan, Tangle, Telepathy 등: 해당 커밋의 로컬 사본이 없음
   - 나머지: Original Entrypoint가 생성 파일이거나 없음
3. **zkfDO 준비 단계의 한계:** zk-email 조각 4개가 모두 제외됐다. 두 가지 이유다.
   - 프로젝트 밖(zkbugs 공용 circomlib)의 의존성을 조각 식별값에 넣지 못한다.
   - 함수로 계산하는 템플릿 파라미터(`log_ceil`)와 컴파일 타임 변수 배열(`poly_interp`)을 탐색기가 지원하지 않는다.

   정식 평가 전에 R2에서 고쳐야 할 항목이다.
4. **조각 비용은 크기와 따로 논다:** 작은 `RSAPad`는 30초에 세대 0도 못 끝냈다. 조각당 시간 제한과 cost-aware의 비용 추정을 정할 때 고려해야 한다.

## 다시 만드는 방법

```sh
P=reports/dev-rq1-pilot-2026-09-29/p2.py
python3 -B $P prepare                    # 프로젝트 복사, 조각 wrapper, 전략별 준비
python3 -B $P sizes zkemail-rsa-test     # 직접 실행 사례의 조각 크기
python3 -B $P run <사례> <방식>          # 방식: whole, random, small-first, path-order
python3 -B $P summarize                  # results.json
```

실행 파일은 `runs/dev-rq1-pilot-2026-09-29/bin/`에 보존했다. 원시 로그, 반례, 컴파일 산출물은 ignored `runs/dev-rq1-pilot-2026-09-29/`에만 있다.
