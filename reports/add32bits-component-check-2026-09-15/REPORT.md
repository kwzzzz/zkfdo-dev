# Add32Bits 기존 후보의 원본 component 검증 — 2026-09-15

## 결론

**선정한 정확한 후보는 확보한 원본 `Add32Bits` component에서 거부됐다.** 입력
`a=10`, `b=8`은 확인한 32비트 입력 전제를 만족하고 실제 출력은 정상적인 wrap-around
결과 `18`과 다르다. 그러나 후보의 `tmp=p-59`가 원본의 Boolean 제약을 위반한다.
따라서 원본 전체 제약 2개 중 1개만 만족하며, 다음 비교의 주 지표에는 고유 결함 1건으로
집계할 수 없다.

이 판정은 이 정확한 대입 하나에만 적용한다. 다른 Add32Bits 후보, 원본 component의
안전성, 프로젝트 문맥에서의 도달성을 판정한 결과가 아니다.

## 후보 선정

최신 dev3에는 XorWords를 제외하면 Add32Bits 후보 49건과 RotateLeft32Bits(3) 후보
21건이 보존돼 있다. 두 종류 모두 후보·준비 소스·실행 로그가 존재한다. 그중 Add32Bits를
선정한 이유는 다음 네 자료를 한 경로로 연결할 수 있기 때문이다.

- 원본 component와 저장소 자체 테스트 entrypoint
- 덧셈 수정 이름을 가진 commit과 그 직접 부모 revision
- 감사 보고서가 명시한 입력 전제와 wrap-around 속성
- 후보 JSON, 실행 로그, seed와 준비 소스

랭킹 점수와 유효할 것이라는 기대는 선정에 사용하지 않았다. Add32Bits 안에서는 후보
값을 열기 전에 실행 시작 시각과 run ID로 정렬하여 가장 이른 보존 실행을 고정했다.

- target: `sha256:20bbb44092d11a8ef2e2a2bef5ea77d8a3edf68183e40685cbdd1048172801ff`
- run: `d67912ec-19b0-40d0-ac96-d8e40dc9d2c5`
- seed: `2026091501`, generation: `0`
- candidate SHA-256: `acd36135a4c3324ce2da705079c694d7cd6925e064135a5cc18a8d312815860c`

후보 목록과 선택 규칙은 [selection.json](selection.json)에 보존했다. RotateLeft 후보의
assignment는 평가하지 않았고, 이 후보가 거부된 뒤 다른 후보로 넘어가지 않았다.

## 탐색 예산의 실제 측정 범위

dev3의 비교 구간은 `ranking-separated` ordered scheduler이며 타깃당 3초, 전략 실행당
총 10초다. 총 탐색 timer는 plan과 타깃 검증이 끝난 뒤
[`scheduler.rs` 262행](../../src/scheduler.rs#L262)에서 시작하여 마지막 runner가 반환된 뒤
333행에서 캡처된다.

| 비용 | scheduler 탐색 예산 포함 여부 | 실제 구현 |
|---|---:|---|
| corpus 준비, 구조용 R1CS 컴파일, semantic 수집 | 제외 | 앞선 `prepare` 단계에서 수행 |
| 정적 랭킹과 plan 생성 | 제외 | 별도 `plan` 단계의 `planning_elapsed_seconds` |
| plan/source 검증, backend hash, mutation 설정 freeze, 명령 구성 | 제외 | scheduler 호출 전 [`experiment.rs` 367–425행](../../src/experiment.rs#L367) |
| run/log 디렉터리 생성, process spawn | 포함 | runner timer가 [`runner.rs` 151행](../../src/runner.rs#L151)에서 먼저 시작 |
| zkFuzz subprocess 내부 파싱·타입 분석·symbolic 준비·GA 탐색 | 포함 | subprocess 전체 wall time으로 함께 측정 |
| timeout poll, kill/reap, 로그 읽기·상태 분류, `result.json` 저장 | 포함 | scheduler는 runner가 233행에서 반환한 뒤 completion offset 기록 |
| scheduler summary 저장, 후보 별도 보존, 사후 원본 검증 | 제외 | scheduler timer 캡처 및 반환 뒤 수행 |

각 타깃에는 `min(3초, 남은 총예산)`이 전달된다. timeout은 25ms 이하 poll 간격 뒤
process group을 종료하고 reap하므로 설정값은 hard real-time 종료 보장이 아니다.
`outcome.elapsed_seconds`는 plan 검증과 후보 보존까지 포함하는 더 넓은 값이며 탐색
예산 지표가 아니다.

선정 실행은 2026-09-15 07:10:29.916707Z에 runner 측정이 시작되어 0.031548917초 뒤
끝났다. scheduler 시작부터 해당 runner 반환까지의 completion offset은 0.044734208초다.
후보 JSON의 backend 내부 실행 시간은 7.247666ms지만, 어느 시점에 반례가 처음 만들어졌는지
정확한 timestamp는 없다. 이 값들은 2026-09-15 12:36:07Z에 끝난 이번 사후 검증 시간과
구분한다.

## 출처, 전제와 속성

zkbugs 메타데이터는 project `Commit`을 `ef9f5a5...`, `Fix Commit`을 `4551ca64...`로
기록하지만 실제 commit 순서는 `9f98e3...` → `4551ca64...` → `ef9f5a5...`다. 따라서
메타데이터의 필드 이름만으로 취약 덧셈 소스를 정하지 않았다.

검사한 revision은 `4551ca64...`(`fix: add circuit security`)의 직접 부모
`9f98e3aaa95e629515883e0cc6e6cfe6aef6d622`다. 이 revision의 `generics.circom`과
저장소 자체 `circuits/tests/add32bits.circom`을 immutable API 기록으로 확보했다. 두
파일의 Git blob SHA-1을 바이트에서 다시 계산했고 commit tree 항목과 일치했다.

이 소스의 `Add32Bits()`는 파라미터와 외부 의존성이 없다. upstream 테스트는 원본
`generics.circom`을 include하고 `component main = Add32Bits();`만 선언한다. 파일을
변경하거나 제약을 추가한 harness를 만들지 않았다.

소스 주석은 두 32비트 정수의 덧셈을 명시한다. 감사 보고서 finding 0은 입력 `a`, `b`를
각각 32비트 값으로 가정하고, 속성을 `out = (a + b) mod 2^32`로 설명한다. 후보의
`10`, `8`은 이 전제를 만족하고 기대값은 `18`이다.

정확한 감사 전체 snapshot의 project hash는 보고서에 없어 여전히 미확인이다. 또한
`4551ca64...`의 실제 patch는 입력 전제 설명과 기존 출력식에 대수적으로 같은 equality를
추가하지만, 감사 보고서의 client response는 비트 분해 refactor를 설명한다. 따라서
`4551ca64...`를 감사가 말한 최종 수정본과 동일시하지 않았다. 이번에 확인한 범위는
**감사의 취약 코드 조각과 일치하는 확보 component source**다.

## 실제 component 검사

보존 후보의 네 신호를 같은 이름의 원본 신호에 그대로 대응했다. 값 변환, 기본값,
누락 wire가 없고 추가 연결·제약도 없다.

| 신호 | 보존값 | 원본 대응 |
|---|---:|---|
| `main.a` | `10` | `main.a` |
| `main.b` | `8` | `main.b` |
| `main.out` | `253403070482` | `main.out` |
| `main.tmp` | `p-59` | `main.tmp` |

원본 upstream 테스트를 Circom 2.2.3, `--O0 --prime bn128`로 한 번 컴파일했다. 생성된
R1CS는 wire 5개, 제약 2개다. 스크립트가 두 compiled polynomial을 두 원본 식과 각각
대조한 뒤 모든 제약을 평가했다.

| 원본 제약 | 잔여값 mod p | 판정 |
|---|---:|---|
| `tmp * (tmp - 1) === 0` | `3540` | 위반 |
| `out === a + b - tmp * 2^32` | `0` | 만족 |

즉 출력식과 잘못된 출력 사이의 관계는 성립하지만, `tmp`가 원본에서 허용되는 Boolean
값이 아니다. direct fixture에는 이 Boolean 제약이 없어 준비 당시 R1CS가 1개 제약뿐이다.
이번 후보는 그 더 약한 fixture에서는 성립했지만 확보 원본 전체 제약에서는 성립하지
않는다.

실제 실행한 작업은 API source/tree/commit 응답 획득, source/test Git blob 및 tree
대조, 원본 upstream test 재컴파일, `.sym` 기반 4개 신호 매핑, R1CS의 2개 전체 제약
평가와 속성 계산이다. 감사 문구와 commit patch의 의미, fixture와 원본 source 차이,
프로젝트 범위의 한계는 정적으로 검토했다. 프로젝트 entrypoint의 도달성, 전체 프로젝트
witness/proof, 당시 compiler와 배포 artifact는 실행하지 않았다.

기계 판정의 전체 값은 [component-check.json](component-check.json), 재현 코드는
[check_add32bits.py](check_add32bits.py), 컴파일된 R1CS와 로그는
[component-check/](component-check/)에 보존했다. 실제 명령은 다음과 같다.

```sh
python3 reports/add32bits-component-check-2026-09-15/check_add32bits.py \
  --work-dir reports/add32bits-component-check-2026-09-15/component-check \
  --output reports/add32bits-component-check-2026-09-15/component-check.json
```

스크립트는 결과와 work directory의 덮어쓰기를 거부한다. 재검토자는 증거 디렉터리의
복사본이나 새 `--work-dir`/`--output` 경로에서 실행해야 한다.

## 판정과 집계

판정은 **해당 정확한 반례 거부**다. 속성 불일치는 확인됐지만 원본 전체 제약을 만족하지
않으므로 원본 component에서 검증된 반례가 아니다.

- 이번 후보로 집계할 원본 component 고유 결함: **0건**
- 프로젝트 문맥까지 확인된 결함: **0건**
- 검사 도구 상태: 성공; compile exit 0, 모든 source polynomial 대조 완료
- 증거 상태: 자료 부족에 따른 보류가 아니라 정확한 대입의 원본 제약 위반

감사에 같은 Add32Bits 근본 결함이 보고돼 있다는 사실은 이 실행의 유효한 발견을 대신하지
않는다. 나머지 Add32Bits 후보 48건은 검사하지 않았으므로 이번 거부를 일반화하지 않는다.
나중에 각 실행의 자체 후보가 원본 제약과 속성을 통과한다면 동일한
`Unsound Addition Gadget` 근본 원인은 전역 고유 결함 1건으로 중복 제거하고, 전략별
성공 여부는 그 전략 실행의 후보가 직접 검증된 경우에만 인정해야 한다.

## 사후 검증 비용과 남은 불확실성

자동화된 단일 검사는 총 0.020969917초였다. 이 중 컴파일은 0.012448959초, 컴파일 후
source/R1CS 대조·대입·속성 계산은 0.000269292초다. 이는 모두 과거 탐색 예산에서 제외한
사후 검증 비용이다.

수작업에는 비-XOR 후보 inventory, 후보 선정 고정, runner timer 검토, immutable source와
commit/tree 확보, 감사 전제·속성 대조, fixture/원본 mapping 검토, 검증 코드 작성과 결과
판정이 포함됐다. 작업 시작부터 이 문서와 보존 검사가 끝날 때까지의 사람 개입형 wall-clock을
별도 JSON에 기록하되, 활성 수작업만을 계측한 값은 아니므로 사람 검토 비용으로 해석하지
않는다. 구간과 해석은 [validation-cost.json](validation-cost.json)에 기록했다. 검사 전
목록에 있던 1,254개 파일은 모두 동일하며, 비교 결과는
[preservation-result.json](preservation-result.json)에 남겼다.

남은 불확실성은 정확한 감사 전체 revision, 역사적 compiler·proof artifact, 프로젝트
caller에서의 입력 도달성과 출력 사용, 다른 내부 대입 또는 다른 보존 후보의 유효성이다.
원본 component 자체가 안전하다는 결론도 내리지 않는다. 감사 finding은 올바른 carry와
`tmp`의 결박이 부족한 문제를 별도로 보고하지만, 이번 범위에서는 성공 사례를 만들기 위한
새 대입을 구성하거나 탐색하지 않았다.

이 한 건은 49회 전략 실행·147회 타깃 시도·119건 backend 후보 전체의 유효성이나 랭킹
성능에 대한 근거가 아니다.
