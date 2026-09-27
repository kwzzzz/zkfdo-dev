# 개발용 순위 파일럿: 예산 부족 조건 (2026-09-27)

**상태: 완료.** 순위 전략을 예산이 부족한 조건에서 실제로 비교한 첫 실행이다. 쓴 프로젝트(`inference-labs-inc/subnet-2-circom`)는 개발에 이미 썼으므로 **독립 평가가 아니다.** 결함 원인은 하나(O1)만 탐지됐고 반복은 zkFuzz seed 3개뿐이라, 전략 우열을 주장하는 근거가 아니라 B 설계를 점검하는 자료로 읽는다.

## 설정

설정은 [pilot-config.json](pilot-config.json)에 적었고 첫 zkFuzz 실행(20:03:13) 전에 파일을 만들었다(커밋 `39f9277`은 실행 중에 만들었고, 파일은 그대로다).

- **변형 3개:** inference에 주입 결함을 하나씩 넣었다. O1 `Where`(`<==` → `<--`), O2 `Num2Bits(41)`(비트 불리언 제약 제거), O5 `IsZero`(`in * out === 0` 제거). 세 결함 모두 실행 전에 엔진이 `qualified`로 판정했다.
- **타깃:** `src/circuit.circom`에서 도달하는 고유 인스턴스 전부. 변형마다 21·20·21개다. 루트 `IncentiveMechansim(256, 40)`은 소스 파일에 이미 `component main`이 있어 wrapper로 감쌀 수 없어서, 모든 전략에서 똑같이 빠졌다. wrapper는 한 폴더에 `소스경로__템플릿_파라미터` 이름으로 두어, path-order가 소스 경로 순서를 따르게 했다.
- **전략과 반복:** path-order, small-first, risk-only, cost-aware, random. block 3개(zkFuzz seed 2026092711~13)이고, random은 block마다 순위 seed를 하나씩 썼다. 모두 45회 실행했다.
- **예산:** 타깃당 30초, 실행당 총 180초.
- **발견 기준:** zkFuzz 후보를 엔진이 주입 spec으로 검토해 `validated`이고, 다시 실행한 qualification bundle로 주입 결함에 귀속된 경우만 센다. 발견 시간은 그 후보를 낸 타깃 실행이 끝난 시점의 누적 시간(상한)이다.
- **실행 전 조정 두 가지:**
  1. 고정된 Circomspect(0.9.0)가 익명 컴포넌트 호출(`AssertBit()(out[i])` 등)이 있는 템플릿을 분석하지 못해 22개 중 4개만 대상에 남았다. 그래서 익명 호출 3곳을 이름 있는 컴포넌트로 바꾼 정규화 사본을 원본 프로젝트로 썼다([normalization.diff](normalization.diff)). 전체 회로의 제약 수(비선형 179,712개, 선형 16,384개)는 원본과 같다.
  2. prepare는 검토 기록이 없는 bounded 입력 계약을 제외한다. 그래서 모든 타깃을 `field_only`로 두고, 필요한 입력 조건은 predicate가 검사한다.

## 결과

| 변형 | 주입 타깃이 실행된 횟수 | 엔진이 확인한 발견 |
|---|---:|---:|
| O1 `Where` | 12 / 15 | **12** |
| O2 `Num2Bits(41)` | 15 / 15 | 0 (no_counterexample 13, timeout 2) |
| O5 `IsZero` | 11 / 15 | 0 (no_counterexample 11) |

O1에서 전략별 결과(block 3개):

| 전략 | 주입 타깃 계획 순위 (결함본) | 같은 타깃의 원본 특징일 때 순위 | 발견 | 발견 시간 상한 |
|---|---:|---:|---:|---|
| cost-aware | 2 / 21 | 14 / 21 | 3 / 3 | 0.06초 |
| risk-only | 9 / 21 | 17 / 21 | 3 / 3 | 0.3~2.8초 |
| small-first | 4 / 21 | 5 / 21 | 3 / 3 | 4.3~4.8초 |
| random | 10, 6, 13 / 21 | – | 3 / 3 | 30~155초 |
| path-order | 21 / 21 | 21 / 21 | **0 / 3** (9개만 시작) | – |

"원본 특징일 때 순위"는 `Where`가 원본으로 남아 있는 O5 변형의 계획에서 같은 인스턴스의 순위다. 전체 행은 [results.json](results.json)에 있다.

## 해석

1. **O1에서 보인 위험 기반 전략의 이점은 대부분 주입 자체가 만든 것이다.** `<==`를 `<--`로 바꾸자 `Where`의 Circomspect 경고가 0개에서 3개로, 위험 점수가 0에서 2로 올랐다. 그래서 cost-aware 순위가 14위에서 2위로, risk-only 순위가 17위에서 9위로 올라갔다. O5도 제약을 지우자 `IsZero`의 위험 점수가 0에서 1로 올라 cost-aware 순위가 15위에서 2위가 됐다. O2는 제약을 41개 지워 크기가 42에서 1로 줄었고, small-first 순위가 7위에서 4위로 올랐다. 즉 주입 연산자는 순위 전략이 보는 특징을 **전략에 유리한 방향으로** 바꾼다. 설계 초안 7절은 "특징을 바꾸지 않은 결함만 따로 집계"를 계획했지만, 이번 세 결함은 모두 적어도 한 전략의 특징을 바꿨다.
2. **zkFuzz는 O2·O5를 30초 안에 한 번도 찾지 못했다.** 주입 타깃이 실행된 26회에서 발견 0건이다. 반면 O1은 실행될 때마다 1초 안에 찾았다. 탐지 여부가 연산자에 크게 좌우되는데, 설계는 zkFuzz로 잡히는 결함만 고르는 것을 금지한다. 그러면 B에서 탐지되지 않는 결함이 많아져 전략 비교의 검정력이 낮아진다.
3. **예산 부족 조건은 절반 넘게 만들어지지 않았다.** 45회 중 27회가 180초 안에 모든 타깃을 시작했다(risk-only·cost-aware는 9/9). 대부분의 타깃이 몇 초 안에 끝났기 때문이다. 자연 결함 후보로 곧바로 `bug_found`가 되거나, 금방 `no_counterexample`로 끝났다. path-order만 앞쪽에 오래 걸리는 타깃이 몰려 9개만 시작했다.
4. **자연 결함 후보가 많다.** 주입 위치가 아닌 12개 템플릿에서 후보 382개가 나왔다. 많은 순서대로 `Clamp(40)` 42개, `CalculatedScoreFraction(40)` 41개, `Subtract()` 39개, `DistanceFromScore(40)` 38개, `IntDiv` 3종 104개 등이다. 모두 검토하지 않았고 B의 발견 수에 넣지 않는다. `Subtract`는 v1.1의 알려진 결함이고, `IntDiv`의 출력은 제약되지 않은 것으로 관찰된 바 있다. 호출자에서 나온 후보는 이 둘에서 번진 것일 수 있다.
5. **검토 엔진의 결함을 찾아 고쳤다.** 주입 spec은 도달성 재탐색을 위해 entrypoint 전체 closure를 고정하는데, prepare가 만든 plan 타깃은 wrapper가 include하는 파일만 fingerprint한다. 엔진이 둘을 정확히 같게 요구해서 실제 backend 검토가 모두 실패했다(합성 시험에서는 두 목록이 우연히 같았다). 이제 엔진은 spec의 wrapper가 컴파일하는 파일만 골라 plan 타깃과 정확히 비교한다(커밋 `b8425f1`, 수정 전 엔진에서 실패하는 회귀 시험 포함). 캠페인은 수정 전 실행 파일(`runs/dev-ranking-pilot-2026-09-27/bin/`)로 돌렸고, 검토는 수정 후 실행 파일(`bin-v2/`)로 했다. 수정된 엔진이 이전 엔진 소스 목록을 거부하므로 주입을 같은 경로에 바이트 단위로 같게 다시 만들고 다시 qualification했다([injection-rebound](o1-where/injection-rebound/)). 실행 전 기록([injection](o1-where/injection/))은 그대로 두었다.

## B2에 주는 의미

- **주입과 순위 특징의 결합을 설계에서 다뤄야 한다.** 예를 들어 특징은 원본에서 계산하고 실행은 결함본에서 하는 조건을 주 분석으로 둘지, 특징을 바꾸지 않는 연산자·위치만 쓸지 정해야 한다. 지금 설계대로면 O1·O5 주입은 위험 기반 전략에 인위적으로 유리하다.
- **연산자별 탐지 가능성과 타깃당 예산:** T6 보정에서 연산자별로 zkFuzz가 결함을 찾는 데 걸리는 시간을 재고, 예산과 연산자 가중치에 반영해야 한다.
- **부족 조건:** 타깃 대부분이 몇 초 안에 끝나므로, 총 예산은 "타깃 수 × 타깃당 제한"이 아니라 실제 소요 시간 분포로 정해야 한다.
- **도구 조건:** Circomspect의 익명 컴포넌트 미지원(최신 프로젝트에서 타깃이 크게 줄 수 있음)과 bounded 계약 규칙을 B 절차에 반영해야 한다.

## 다시 만드는 방법

```sh
P=reports/dev-ranking-pilot-2026-09-27/pilot.py
python3 -B $P prepare      # 주입 qualification, wrapper, manifest, prepare
python3 -B $P run          # 45회 실행과 장부
python3 -B $P rebind       # 수정된 엔진으로 주입 재qualification
python3 -B $P review       # backend 검토
python3 -B $P summarize    # results.json
```

실행 파일은 `runs/dev-ranking-pilot-2026-09-27/bin/`(캠페인)과 `bin-v2/`(검토)에 보존했다. 원시 후보와 컴파일 산출물은 ignored `runs/`에만 있다.
